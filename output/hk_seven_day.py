#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""◈ AI 七日港股走势分析概率 —— 未来 7 个交易日三大港股指数升跌概率。

定位与方法学来源（对齐 GitHub 开源量化分析最佳工程实践）：
  · k-macao/03 PR #54「AI 预测 · 未来函数」栏目（同组织姊妹仓）：
      四大硬约束：输入闭合（只读当次快照）、目标日严格在后（t_target > t_base）、
      先存档后结算（settled=False 独立落盘，真实行情回填）、零写死叙事；
  · akfamily/akquant（docs/zh/advanced/ml.md）：
      防未来函数因果律：特征 X 只能用 t 及之前；标签 y 描述 t 之后；
      统计量均值/方差必须逐期扩张因果计算，绝不全样本归一；
  · arielb57/peekahead（黑箱前视偏差检测器）：
      截断不变性：删掉 / 扰动 t 之后的数据，过去时刻信号输出逐位不变；
  · paidaxing1234/quant-backtest-guard（回测照妖镜）：
      杜绝标签泄漏，禁止全样本标准化，无未来函数；
  · haeganm/walkforward（purged / embargo walk-forward splits）：
      类比锚点标签必须在预测时点前全部结算（s + horizon ≤ t）。

三层预测架构：
  ① 预测因子层（Predictive Factors）：
       · MOM 动量延展与均值回归项：z = ret20 / σ_20，|z|≤2σ 动能延续，|z|>2σ 均值回归；
       · TRD 均线趋势与通道排列项：MA20 / MA60 均线偏离度与 20 日通道分位；
       · REV 反转与震荡振荡器项：Wilder RSI14 超买超卖均值回归与 20 日高位回撤；
       · CARRY 跨市场隔夜联动项：美股三指（标普/纳指/道指）隔夜映射 × 标的 β 敏感度；
       · FLOW 资金流与流动性深度项：南向资金净额强度与港股市场流动性综合评分；
       · VOL 波动率自适应收缩项：20 日年化波动分位对极端概率做有界收缩；
       · MACRO 宏观日程风险项：未来两周重大（★★★）事件密度带来的不确定性缓冲。
  ② 量化基准层（Quant Baseline）：
       由扩张基准率 + 20 日特征已结算最近邻（K=8，s+7≤t 锚点）作为核心，叠加多因子
       有界微调量（tanh 软压缩，ΔP ∈ [−0.12, +0.12]），夹在 5%~95% 之间；
  ③ 研判层（Optional：大模型 / Jev 类型化决策，二选一，优先级 大模型 > Jev > 量化基准）：
       · 大模型（OpenAI 兼容）：把结构化预测因子与量化基准作为唯一依据交给大模型；
         严格三道防线：偏离量化基准 >20pp 自动收敛到基准 ±20pp、文本数字 100% 溯源
         （编造数字退回量化文案）、绝对化措辞（一定/必然/100%…）命中即退回；
       · Jev 类型化决策（output/jev_bridge.py，本地 /v1/systemone，无 API Key）：
         只输出类型化值 + 已校准概率，没有自然语言就没有编造数字的入口；概率与量化
         基准按同一份常量对账（>20pp 收敛、5%~95% 夹边），文案仍走量化模板；
         留痕单独一份 output/jev_forecast.json（同一套 T+7 结算口径）。

留痕与结算：预测先写入 output/hk7_forecast.json（settled=False），满 7 个交易日后
按真实收盘回填方向命中与 Brier 得分；样本 <10 只报样本量，不下命中率结论。
Jev 引擎的预测同时在 output/jev_forecast.json 留一份研究留痕（按 engine 字段区分）。
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
TRADING_DAYS = 252

# ---- 口径常量（写死可复现；改任何一条都会改变预测，必须同步测试）----
HORIZON = 7                  # 预测视界 = 未来 7 个交易日（按交易日计数，假期顺延）
WINDOW = 20                  # 特征窗口（交易日）
MIN_BARS = 60                # 最少日线根数（与 octopus_weekly 同口径）
PROB_FLOOR = 0.05            # 概率硬边界：统计模型永远保留被证伪的余地
PROB_CAP = 0.95
DIR_UP = 0.58                # 展示方向阈值（结算一律按 P ≥ 0.5 的底牌方向）
DIR_DOWN = 0.42
MAX_PROB_DEVIATION = 0.20    # 大模型概率相对量化基准的最大偏离（超出即收敛）
MIN_JOURNAL_FOR_HITRATE = 10  # 结算样本 <10 只报样本量，不下命中率结论
JOURNAL_FILENAME = "hk7_forecast.json"
JOURNAL_MAX_ENTRIES = 120
MAX_TEXT_NEWS = 10           # 交给大模型的港股相关标题上限

# 三只标的：Yahoo 代码按顺序尝试（国企指数在 Yahoo 是 ^HSCE；^HSCEI 作兜底）
TARGETS = (
    {"name": "恒生指数", "short": "恒指", "symbols": ("^HSI",)},
    {"name": "恒生科技", "short": "恒科", "symbols": ("^HSTECH",)},
    {"name": "国企指数", "short": "国企", "symbols": ("^HSCE", "^HSCEI")},
)

# 典型日波动基准参数 σ（策略参数，非未来行情）：恒指 1.2%，恒科 1.8%，国企 1.3%，标普 1.1%
DAILY_SIGMA = {
    "^HSI": 0.012,
    "^HSTECH": 0.018,
    "^HSCE": 0.013,
    "^HSCEI": 0.013,
    "SPX": 0.011,
}

# 跨市场隔夜联动敏感度 β（美股三指隔夜映射到港股的敏感度）
# 港股科技成长板块弹性最大，对美股纳指最敏感；国企偏稳健防御；恒指居中
BETA_GLOBAL = {
    "^HSI": 0.55,
    "^HSTECH": 0.75,
    "^HSCE": 0.50,
    "^HSCEI": 0.50,
}

# 预测因子权重体系（加权合计 1.0）
FACTOR_WEIGHTS = {
    "mom": 0.25,     # 动量延续与均值回归
    "trd": 0.20,     # 均线趋势与通道位置
    "rev": 0.15,     # RSI14超买超卖反转
    "carry": 0.20,   # 美股隔夜联动 (β * carry_z)
    "flow": 0.10,    # 南向资金与流动性
    "vol": 0.10,     # 波动率分位与风险收缩
}

# 大模型配置：任何 OpenAI 兼容服务都能用（默认 DeepSeek，可在环境变量里改）
# Key / 地址 / 模型三组变量都按「本仓专用名 → 厂商通用名」的顺序回落，任一个非空即生效：
# 于是「仓库里本来就有 DEEPSEEK_API_KEY 这类既有配置」不必改名换值，直接就能被这一栏用上。
ENV_KEY_NAMES = ("OCTOPUS_LLM_API_KEY", "OCTOPUS_HK7_LLM_KEY",
                 "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
                 "MOONSHOT_API_KEY", "DASHSCOPE_API_KEY")
ENV_BASE_NAMES = ("OCTOPUS_LLM_BASE_URL", "DEEPSEEK_BASE_URL", "OPENAI_BASE_URL")
ENV_MODEL_NAMES = ("OCTOPUS_LLM_MODEL", "DEEPSEEK_MODEL", "OPENAI_MODEL")
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
# 未显式指定模型名时按序尝试的候选链：DeepSeek 官方把「版本名」与「档位别名」都收在
# /models 目录里，别名随版本滚动（deepseek-chat / deepseek-reasoner 是历史别名，
# deepseek-flash / deepseek-v4-flash 是现行档位）——只写死一个名字，官方改名那天整栏就没了。
MODEL_FALLBACKS = ("deepseek-flash", "deepseek-v4-pro", "deepseek-chat",
                   "deepseek-reasoner", "deepseek-v4-flash")
MODEL_ATTEMPTS_MAX = 3       # 单次运行最多换几个模型名（只有「模型名不对」才换，见 _model_fault）
MODEL_PROBE_MAX = 5          # --llm-check 探活最多试几个模型（含 /models 目录里的其余模型）
DEFAULT_TIMEOUT = 60
USER_AGENT = "octopus-ai-daily/1.0 (+hk-seven-day)"

# 「一定 / 必然」这类绝对化措辞：命中即该条文案回退量化口径
_FORBIDDEN_RE = re.compile(
    r"一定|必然|保证|确保|稳赚|必涨|必跌|无风险|百分百|100\s*%|零风险|包赚", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+")
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*%?")

# 允许出现在模型文案里的常量数字（口径本身：视界 / 窗口 / 概率边界 / 指标参数 / 敏感度等）
_CONST_NUMBERS = {
    "1", "2", "3", "4", "5", "7", "8", "10", "14", "20", "30", "50", "52", "60", "70", "95",
    "0.55", "0.75", "0.50", "1.5", "2.0", "3.0", "0.12", "0.30", "0.35"
}


# ============================================================
# 基础工具与时序自检（纯函数，防未来函数）
# ============================================================
def _clamp(p):
    return max(PROB_FLOOR, min(PROB_CAP, float(p)))


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _direction_label(p_up):
    """P(7日涨) → (方向, 展示文案)；展示可以中性，结算只认 P ≥ 0.5 的底牌。"""
    p_up = _clamp(p_up)
    if p_up >= DIR_UP:
        return "up", f"▲ 偏多 · P(7日涨) {p_up * 100:.0f}%"
    if p_up <= DIR_DOWN:
        return "down", f"▼ 偏空 · P(7日涨) {p_up * 100:.0f}%"
    lean = "涨" if p_up >= 0.5 else "跌"
    return "neutral", f"■ 中性（略偏{lean}）· P(7日涨) {p_up * 100:.0f}%"


def _is_date(val):
    s = str(val or "").strip()
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _to_date(val):
    if isinstance(val, (datetime, date)):
        return val if isinstance(val, date) and not isinstance(val, datetime) else val.date()
    s = str(val or "").strip()
    if _is_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def next_trading_days(date_str, n=HORIZON):
    """下一交易日：基准日开始向前推进 n 个工作日（跳过周六周日）。"""
    d = _to_date(date_str)
    if d is None:
        return ""
    cur = d
    count = 0
    while count < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            count += 1
    return cur.strftime("%Y-%m-%d")


def assert_no_lookahead(base_date, target_date):
    """未来函数时序检验：目标日必须严格晚于基准日。返回 (ok, 说明)。"""
    b = _to_date(base_date)
    t = _to_date(target_date)
    if b is None or t is None:
        return False, "基准日或目标日缺失，无法核验时序"
    if t <= b:
        return False, f"目标日 {target_date} 未晚于基准日 {base_date} —— 判定为未来函数污染"
    return True, f"目标日 {target_date} 严格晚于基准日 {base_date}（未来 {HORIZON} 个交易日），时序成立"


def check_input_closure(base_date, extra):
    """输入闭合性检验：确保外部输入的证据日期均 ≤ base_date（防止引入未来数据）。

    返回 (ok, warnings, cleaned_extra)。
    """
    if not base_date or not extra:
        return True, [], extra or {}
    b = _to_date(base_date)
    if not b:
        return True, [], extra
    cleaned = dict(extra)
    warnings = []

    # 检查资金流日期
    flows = dict(cleaned.get("flows") or {})
    s_date = _to_date(flows.get("south_date"))
    if s_date and s_date > b:
        warnings.append(f"南向资金日期 {flows.get('south_date')} 晚于基准日 {base_date}，已剔除")
        flows.pop("south_date", None)
        flows.pop("south_amount_yi", None)
    cleaned["flows"] = flows

    # 检查美股行情日期
    g_quotes = dict(cleaned.get("global_quotes") or {})
    for sym, q in list(g_quotes.items()):
        if isinstance(q, dict) and q.get("as_of"):
            q_date = _to_date(q["as_of"])
            if q_date and q_date > b:
                warnings.append(f"美股行情 {sym} 日期 {q['as_of']} 晚于基准日 {base_date}，已剔除")
                g_quotes.pop(sym, None)
    cleaned["global_quotes"] = g_quotes

    return len(warnings) == 0, warnings, cleaned


# ============================================================
# 基础技术特征与分布
# ============================================================
def _features(closes, t, window=WINDOW):
    """t 时刻（含）之前的窗口特征 —— 只读 closes[0..t]，无未来数据。"""
    c0 = closes[t]

    def _ret(k):
        prev = closes[t - k] if t - k >= 0 else None
        return (c0 / prev - 1.0) if prev else 0.0

    w = closes[t - window + 1:t + 1]
    rets = [w[i] / w[i - 1] - 1.0 for i in range(1, len(w)) if w[i - 1] > 0]
    peak = max(w) if w else c0
    n = len(rets)
    vol = 0.0
    if n >= 2:
        mu = sum(rets) / n
        vol = math.sqrt(sum((r - mu) ** 2 for r in rets) / n) * math.sqrt(TRADING_DAYS)
    return {
        "ret5": _ret(5),
        "ret10": _ret(10),
        "ret20": _ret(window),
        "vol20": vol,
        "dd20": (c0 / peak - 1.0) if peak > 0 else 0.0,
    }


def _ret_over(closes, k):
    """最近 k 个交易日的收益（样本不足返回 None）。"""
    if not closes or len(closes) <= k or k <= 0 or closes[-1 - k] <= 0:
        return None
    return closes[-1] / closes[-1 - k] - 1.0


def _var7(closes):
    """历史 7 交易日收益分布（重叠窗口，仅用于展示 5%/95% 区间，不参与概率）。

    样本 <60 时返回 None（不给出置信区间，绝不编造）。
    """
    rets = []
    for i in range(len(closes) - HORIZON):
        base = closes[i]
        if base > 0:
            rets.append(closes[i + HORIZON] / base - 1.0)
    if len(rets) < 60:
        return None
    rets.sort()

    def _q(p):
        pos = (len(rets) - 1) * p
        lo = int(math.floor(pos))
        hi = min(lo + 1, len(rets) - 1)
        return rets[lo] + (rets[hi] - rets[lo]) * (pos - lo)

    return {"q05": _q(0.05), "q50": _q(0.50), "q95": _q(0.95), "n": len(rets)}


def _rsi14(closes):
    """Wilder RSI14 —— 直接复用港股量化引擎的实现，保证两个港股指数的 RSI 口径一致。"""
    from octopus_quant import stats as _stats
    return _stats.rsi(closes, 14)


def _sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def _vol_pct(closes):
    """当前 20 日年化波动在过去一年里的分位（只用 ≤ 最新一根的数据）。"""
    hist = []
    for t in range(WINDOW, len(closes)):
        hist.append(_features(closes, t)["vol20"])
    if len(hist) < 2:
        return None
    cur = hist[-1]
    past = hist[:-1]
    return sum(1 for v in past if v <= cur) / len(past)


# ============================================================
# 预测因子体系（Predictive Factors）
# ============================================================
def compute_momentum_factor(ret20, sigma=0.012):
    """动量延续与延展均值回归因子（MOM）。

    |z| <= 2.0σ: 动能延续，贡献 +0.30 * z
    |z| > 2.0σ: 均值回归，超出部分反向扣除 -0.35 * 超出量
    """
    if ret20 is None:
        return 0.0, "动量数据缺失"
    sigma_20 = sigma * math.sqrt(20)
    z = ret20 / sigma_20 if sigma_20 > 0 else 0.0
    z = max(-4.0, min(4.0, z))
    MOM_STRETCH = 2.0
    MOM_CONT = 0.30
    MOM_REVERT = 0.35
    if abs(z) <= MOM_STRETCH:
        val = MOM_CONT * z
        desc = f"20日动量 {z:+.2f}σ 处于延续区间（贡献 {val:+.2f}）"
    else:
        sign = 1.0 if z > 0 else -1.0
        over = abs(z) - MOM_STRETCH
        val = sign * (MOM_CONT * MOM_STRETCH - MOM_REVERT * over)
        desc = f"20日动量 {z:+.2f}σ 延展过大（超出 {over:.2f}σ），均值回归修正"
    return max(-1.5, min(1.5, val)), desc


def compute_trend_factor(ma20_dev, ma60_dev, lo20, hi20, close):
    """均线趋势与通道排列因子（TRD）。"""
    score = 0.0
    bits = []
    if ma20_dev is not None:
        score += math.tanh(ma20_dev * 15.0) * 0.6
        bits.append(f"MA20偏离 {ma20_dev * 100:+.1f}%")
    if ma60_dev is not None:
        score += math.tanh(ma60_dev * 10.0) * 0.4
    if lo20 is not None and hi20 is not None and hi20 > lo20 and close is not None:
        pos = (close - lo20) / (hi20 - lo20)
        pos_score = (pos - 0.5) * 0.8
        score += pos_score
        bits.append(f"20日通道分位 {pos * 100:.0f}%")
    score = max(-1.5, min(1.5, score))
    desc = " · ".join(bits) if bits else "趋势指标中性"
    return score, desc


def compute_reversal_factor(rsi14, dd20):
    """RSI14超买超卖与高点回撤反转因子（REV）。"""
    if rsi14 is None:
        return 0.0, "RSI数据缺失"
    if rsi14 > 70.0:
        val = -((rsi14 - 70.0) / 30.0) * 1.2
        desc = f"RSI14 {rsi14:.1f} 处于超买区，面临均值回归"
    elif rsi14 < 30.0:
        val = ((30.0 - rsi14) / 30.0) * 1.2
        desc = f"RSI14 {rsi14:.1f} 处于超卖区，具有反弹动能"
    else:
        val = (50.0 - rsi14) / 50.0 * 0.25
        desc = f"RSI14 {rsi14:.1f} 处于中性震荡区间"
    if dd20 is not None and dd20 < -0.10:
        val += math.tanh(abs(dd20) - 0.10) * 0.3
    val = max(-1.5, min(1.5, val))
    return val, desc


def compute_global_carry_factor(symbol, global_quotes):
    """跨市场全球联动隔夜映射因子（CARRY）：β * carry_z。"""
    beta = BETA_GLOBAL.get(symbol, 0.50)
    if not global_quotes:
        return 0.0, f"隔夜美股联动按中性计（β={beta:.2f}）"
    pcts = []
    for code in ("标普500", "纳斯达克", "道琼斯指数", "^GSPC", "^IXIC", "%5EGSPC", "%5EIXIC"):
        q = global_quotes.get(code)
        if isinstance(q, dict) and q.get("change_pct") is not None:
            pcts.append(float(q["change_pct"]) / 100.0)
    if not pcts:
        return 0.0, f"无可用美股隔夜报价（β={beta:.2f}）"
    avg_pct = sum(pcts) / len(pcts)
    spx_sigma = DAILY_SIGMA["SPX"]
    carry_z = max(-3.0, min(3.0, avg_pct / spx_sigma))
    contrib = beta * carry_z
    contrib = max(-1.5, min(1.5, contrib))
    desc = f"美股隔夜均值 {avg_pct * 100:+.2f}%（{carry_z:+.2f}σ）× β={beta:.2f}"
    return contrib, desc


def compute_capital_flow_factor(flows):
    """南向资金流与流动性深度因子（FLOW / LIQ）。"""
    if not flows:
        return 0.0, "资金流数据中性"
    score = 0.0
    bits = []
    south_amt = flows.get("south_amount_yi")
    if south_amt is not None:
        try:
            amt = float(south_amt)
            z_flow = (amt - 300.0) / 200.0 if amt > 0 else 0.0
            flow_s = math.tanh(z_flow) * 0.8
            score += flow_s
            bits.append(f"南向规模 {amt:.1f}亿")
        except (TypeError, ValueError):
            pass
    liq_s = flows.get("liquidity_score")
    if liq_s is not None:
        try:
            l = float(liq_s)
            liq_contr = ((l - 50.0) / 50.0) * 0.4
            score += liq_contr
            bits.append(f"流动性分 {l:.1f}")
        except (TypeError, ValueError):
            pass
    score = max(-1.5, min(1.5, score))
    desc = " · ".join(bits) if bits else "资金面中性"
    return score, desc


def compute_volatility_shrinkage(vol_pct):
    """波动率自适应收缩因子（VOL）：在极端波动环境下收缩预测概率。"""
    if vol_pct is None:
        return 1.0, "波动率分位正常"
    if vol_pct >= 0.80:
        shrink = 0.80
        desc = f"20日年化波动分位 {vol_pct * 100:.0f}% 偏高，概率向基准收缩"
    elif vol_pct <= 0.20:
        shrink = 0.95
        desc = f"20日年化波动分位 {vol_pct * 100:.0f}% 偏低，趋势延续度高"
    else:
        shrink = 1.0
        desc = f"20日年化波动分位 {vol_pct * 100:.0f}% 处于适中区间"
    return shrink, desc


def compute_macro_factor(events):
    """宏观日程风险因子（MACRO）：评估未来 7 个交易日内重大事件密度。"""
    events = events or []
    imp3_count = sum(1 for e in events if isinstance(e, dict))
    if imp3_count >= 3:
        shrink = 0.85
        desc = f"未来窗口有 {imp3_count} 项重大日程，防范事件冲击"
    else:
        shrink = 1.0
        desc = f"宏观日程密度适中（{imp3_count} 项重大事件）"
    return shrink, desc


# ============================================================
# 量化多因子基准：因果引擎 + 多因子微调与收缩
# ============================================================
def quant_probability(closes, factor_scores=None):
    """返回 {ok, reason, p_up, p_base, p_sim, factor_delta, factor_score, ...}。

    基于 octopus_weekly 因果引擎（历史基准率 + 20 日扩张特征最近邻，s+horizon ≤ t 已结算锚点）；
    若注入 factor_scores，则融合多因子方向评分进行有界微调（tanh 软压缩 ΔP ∈ [−0.12, +0.12]），
    最终概率锁定在 5%~95% 之间。
    """
    import octopus_weekly as _weekly  # 惰性导入：同一份经过回归测试的因果引擎

    computed = _weekly.compute_signals(list(closes), horizon=HORIZON)
    if not computed.get("ok"):
        return {"ok": False, "reason": computed.get("reason") or "信号不可计算"}
    last = computed["signals"][-1]
    if not last:
        return {"ok": False, "reason": "最新一根 K 线尚无足够已结算样本"}
    ok, msg = _weekly.check_no_lookahead(list(closes), horizon=HORIZON)
    if not ok:
        return {"ok": False, "reason": f"未来函数自检未通过：{msg}"}

    base_p = float(last["p_up"])
    factor_delta = 0.0
    factor_score = 0.0
    if factor_scores and isinstance(factor_scores, dict):
        factor_score = float(factor_scores.get("composite_score") or 0.0)
        factor_delta = float(factor_scores.get("factor_delta") or 0.0)

    p_final = _clamp(base_p + factor_delta)

    return {
        "ok": True,
        "p_up": p_final,
        "p_base": last.get("p_base"),
        "p_sim": last.get("p_sim"),
        "base_p_up": base_p,
        "factor_delta": factor_delta,
        "factor_score": factor_score,
        "n_analog": last.get("n_analog"),
        "n_resolved": last.get("n_resolved"),
        "blended": last.get("blended"),
        "features": last.get("features"),
        "backtest": _weekly._backtest(list(closes), computed["signals"], horizon=HORIZON),
        "self_check": msg,
    }


# ============================================================
# 大模型：配置 / 调用 / 严格 JSON 解析 / 校验
# ============================================================
def _env_first(env, names):
    """按顺序取第一个非空环境变量；返回 (值, 变量名)，都没有时返回 ("", "")。

    变量名一并返回是为了排障：以后台日志只能报「Key 来自哪个变量名」，绝不回显 Key 本身。
    """
    for name in names:
        val = str(env.get(name) or "").strip()
        if val:
            return val, name
    return "", ""


def llm_config(env=None):
    """读取大模型配置；无 Key 时 enabled=False。

    Key / 地址 / 模型各自按 ``ENV_KEY_NAMES`` / ``ENV_BASE_NAMES`` / ``ENV_MODEL_NAMES``
    的顺序回落，所以「仓库里既有的 DEEPSEEK_API_KEY」不需要改名或复制到新变量名上；
    ``key_source`` / ``base_source`` / ``model_source`` 记录实际生效的变量名（不含值），
    供日志与 ``--llm-check`` 报「这次到底用了哪一个」。

    ``models``：本次按序尝试的模型名（显式指定 ``OCTOPUS_LLM_MODEL`` 时只有它自己；
    未指定时是 ``MODEL_FALLBACKS`` 里的 DeepSeek 档位/版本别名，遇到「模型名不对」才换下一个）。

    ``fallback`` 三档（``OCTOPUS_HK7_FALLBACK``）：
      · auto（默认）——未配置 Key → 上层整栏缺席；已配 Key 但大模型不可用 → 降级量化基准；
      · always（=1）——没有 Key 也降级渲染（量化基准 + 栏内标注）；
      · never（=0）——任何大模型不可用（含调用失败）都整栏缺席。
    """
    env = os.environ if env is None else env
    key, key_source = _env_first(env, ENV_KEY_NAMES)
    base, base_source = _env_first(env, ENV_BASE_NAMES)
    model, model_source = _env_first(env, ENV_MODEL_NAMES)
    base = (base or DEFAULT_BASE_URL).rstrip("/")
    model_explicit = bool(model_source)
    model = model or DEFAULT_MODEL
    timeout = 60
    try:
        timeout = max(5, min(180, int(str(env.get("OCTOPUS_LLM_TIMEOUT") or DEFAULT_TIMEOUT))))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    try:
        max_tokens = int(str(env.get("OCTOPUS_LLM_MAX_TOKENS") or "0").strip() or 0)
    except (TypeError, ValueError):
        max_tokens = 0
    max_tokens = max(0, min(8192, max_tokens))     # 0 = 不带该字段，用服务端默认
    mode = str(env.get("OCTOPUS_HK7_FALLBACK", "auto")).strip().lower()
    if mode in ("1", "true", "yes", "always"):
        fallback = "always"
    elif mode in ("0", "false", "no", "never"):
        fallback = "never"
    else:
        fallback = "auto"
    return {"enabled": bool(key), "key": key, "key_source": key_source,
            "base": base, "base_source": base_source,
            "model": model, "model_source": model_source, "model_explicit": model_explicit,
            "models": model_chain({"base": base, "model": model,
                                   "model_explicit": model_explicit}),
            "max_tokens": max_tokens,
            "timeout": timeout, "fallback": fallback}


def is_deepseek_base(base):
    """地址是不是 DeepSeek 官方域名（决定未指定模型时要不要走 DeepSeek 档位别名轮换链）。"""
    host = str(base or "").lower()
    return "deepseek.com" in host


def model_chain(config, catalog=None):
    """本次按序尝试的模型名（纯函数，不发请求；``catalog`` 为 /models 目录 id 列表，可选）。

    规则：
      · 显式指定了模型名 → 只用它（用户指定的名字优先，绝不偷偷换掉）；
      · 未指定 + 官方地址 → DeepSeek 档位/版本别名链；给了目录就先用目录过滤掉不存在的名字；
      · 未指定 + 自建 / 第三方地址 → 只试配置里的默认名（别人的服务上不存在 DeepSeek 别名）；
      · 最多 ``MODEL_ATTEMPTS_MAX`` 个，防止把超时预算耗在换名上。
    """
    cfg = config or {}
    model = str(cfg.get("model") or DEFAULT_MODEL).strip()
    if cfg.get("model_explicit") or not is_deepseek_base(cfg.get("base")):
        return (model,)
    chain = [m for m in MODEL_FALLBACKS]
    if catalog:
        ids = [str(x).strip() for x in catalog if str(x or "").strip()]
        present = [m for m in chain if m in ids]
        if present:
            chain = present
    return tuple(chain[:max(1, MODEL_ATTEMPTS_MAX)])


def _model_fault(err):
    """错误像不像「模型名不对 / 无权限」——只有这类错误才值得换下一个模型名重试。

    网络中断、超时、限流换名字也一样失败，换名字只会把预算烧光，所以一律不重试。
    """
    text = str(err or "").lower()
    if not text:
        return False
    if any(k in text for k in ("timed out", "timeout", "urlopen error", "connection",
                               "temporarily", "rate limit", "429", "500", "502", "503", "504")):
        return False
    return ("model" in text) and any(k in text for k in ("not exist", "not found", "invalid",
                                                         "unsupported", "unknown", "无此",
                                                         "不存在", "不支持", "no permission",
                                                         "permission denied", "401", "403", "404"))


def http_error_message(exc):
    """HTTPError → 带服务端原话的一句话（裸「HTTP Error 402」看不出是余额不足还是模型名不对）。"""
    code = getattr(exc, "code", "")
    reason = getattr(exc, "reason", "") or ""
    body = ""
    try:
        body = exc.read().decode("utf-8", "replace").strip()
    except Exception:                             # 响应体读不到就只用状态行
        body = ""
    body = re.sub(r"\s+", " ", body)[:300]
    return f"HTTP {code} {reason}".strip() + (f"：{body}" if body else "")


def llm_error_hint(reason):
    """把大模型错误翻译成「下一步做什么」（可空串）：写进日志与探活报告，不写进日报正文。"""
    text = str(reason or "").lower()
    if not text:
        return ""
    if any(k in text for k in ("402", "insufficient", "balance", "quota", "欠费", "余额")):
        return ("402 余额/额度不足 → 到 DeepSeek 控制台充值，或换一把有额度的 Key"
                "（充值后重跑 --llm-check 即可确认）")
    if any(k in text for k in ("401", "invalid api key", "authentication", "unauthorized")):
        return "401 鉴权失败 → 检查 Secret 里的 Key（前后不能带空格或换行）"
    if "403" in text:
        return "403 无权限 → 该 Key 被限制调用这个模型（换 Key 或换 OCTOPUS_LLM_MODEL）"
    if any(k in text for k in ("429", "rate limit", "too many requests")):
        return "429 触发限流 → 稍后重试，或调大 OCTOPUS_LLM_TIMEOUT"
    if "model" in text and any(k in text for k in ("not exist", "not found", "invalid",
                                                   "unsupported", "unknown")):
        return "模型名不存在 → 用 --llm-check 看 /models 目录，或显式设置 OCTOPUS_LLM_MODEL"
    if any(k in text for k in ("timed out", "timeout")):
        return "请求超时 → 调大 OCTOPUS_LLM_TIMEOUT（默认 60 秒）"
    if "json" in text:
        return "回复不是合法 JSON → 调大 OCTOPUS_LLM_MAX_TOKENS（如 2048），或换更稳的模型"
    return ""


def _http_json(url, payload=None, headers=None, timeout=DEFAULT_TIMEOUT, method=None):
    """标准库 HTTP → 解析 JSON；任何异常直接抛出，由调用方降级（不静默）。

    HTTPError 会被换成带响应体原话的 RuntimeError：402/401/模型名不对这些排障关键信息
    都在响应体里，只抛「HTTP Error 402」等于让人再去猜一遍。
    """
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method=method or ("POST" if body is not None else "GET"),
        headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(http_error_message(exc)) from exc


def http_post_json(url, payload, headers, timeout=DEFAULT_TIMEOUT):
    """标准库 POST → 解析 JSON；任何异常直接抛出，由调用方降级（不静默）。"""
    return _http_json(url, payload=payload, timeout=timeout,
                      headers={"Content-Type": "application/json", **headers})


def http_get_json(url, headers, timeout=DEFAULT_TIMEOUT):
    """标准库 GET → 解析 JSON（读 /models 目录用）；异常直接抛出，由调用方决定降级口径。"""
    return _http_json(url, headers=headers, timeout=timeout, method="GET")


def list_models(config, get_json=None):
    """读 ``{base}/models`` 目录：返回 {ok, ids, reason}；端点不支持就 ok=False + 原因。

    这一层只做「探明有哪些模型可选」，不参与预测；失败绝不抛给上层（探活/选名用）。
    """
    cfg = config or {}
    getter = get_json or http_get_json
    url = f"{str(cfg.get('base') or DEFAULT_BASE_URL).rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {cfg.get('key') or ''}"}
    try:
        data = getter(url, headers, int(cfg.get("timeout") or DEFAULT_TIMEOUT))
    except Exception as exc:
        return {"ok": False, "ids": [], "reason": f"{type(exc).__name__}: {exc}"}
    items = data.get("data") if isinstance(data, dict) else None
    ids = []
    for it in items or []:
        if isinstance(it, dict):
            mid = str(it.get("id") or "").strip()
            if mid:
                ids.append(mid)
        elif isinstance(it, str) and it.strip():
            ids.append(it.strip())
    if not ids:
        return {"ok": False, "ids": [], "reason": "目录里没有模型 id"}
    return {"ok": True, "ids": ids, "reason": ""}


def build_prompt(context):
    """(system, user)：把结构化预测因子与输出结构写清楚，禁止自由发挥。"""
    system = (
        "你是港股量化研究员，只做多因子概率研判、不做投资建议。硬性要求："
        "① 只能使用用户消息里给出的预测因子与事实数据，禁止编造任何数字、日期、点位或新闻；"
        "② 概率必须在 0.05~0.95 之间，绝不出现 0%/100% 的假确定性；"
        "③ 不使用「一定 / 必然 / 保证」等绝对化措辞；"
        "④ 研判需综合动量、均线趋势、RSI反转、美股隔夜联动与南向资金五大因子；"
        "⑤ 只输出一个 JSON 对象，不要 markdown 代码块、不要多余文字。")
    user = (
        "任务：估计下列港股指数在未来 {h} 个交易日（按交易日计数，假期顺延）收盘价"
        "高于当前收盘价的概率。\n"
        "可用数据（包含各标的量化多因子评分与唯一依据）：\n{ctx}\n\n"
        "请输出 JSON，结构（不要增删字段）：\n"
        '{{"targets":[{{"code":"^HSI","p_up":0.57,"summary":"不超过60字的结论",'
        '"drivers":["不超过30字的依据","…"],"risks":["不超过30字的风险"],'
        '"support":24500,"resistance":25600}}],"cross_note":"不超过60字的跨市场一句",'
        '"confidence":"低或中或高"}}\n'
        "要求：targets 必须恰好覆盖上面列出的每个 code；support/resistance 必须落在"
        "该指数的近期波动区间内；每个 drivers / risks 最多 3 条。".format(
            h=HORIZON, ctx=json.dumps(context, ensure_ascii=False, indent=1)))
    return system, user


def _extract_json(text):
    """从模型回复里取出 JSON 对象（容忍 ```json 代码块与前后废话）。"""
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(s[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def build_request(config, model, context):
    """组装一次 chat/completions 请求体（严格 JSON 输出模式；模型名由调用方决定）。"""
    system, user = build_prompt(context)
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    if int(config.get("max_tokens") or 0) > 0:
        payload["max_tokens"] = int(config["max_tokens"])
    return payload


def _read_completion(data):
    """从响应里取 (parsed_json, error)：结构不对时把服务端 error.message 原样带出来。"""
    if not isinstance(data, dict):
        return None, "大模型返回不是 JSON 对象"
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        err = data.get("error") if isinstance(data.get("error"), dict) else {}
        return None, str(err.get("message") or "大模型响应缺少 choices[0].message.content")
    parsed = _extract_json(content)
    if parsed is None:
        return None, "大模型回复不是合法 JSON"
    return parsed, ""


def call_llm(config, context, post_json=None, models=None, trace=None):
    """调用大模型；返回 (payload, error)。任何一步失败都返回 (None, 原因)。

    ``models`` 缺省取 ``config['models']``（未显式指定模型名时是 DeepSeek 档位别名轮换链）。
    只有「模型名不对 / 无权限」这类错误才换下一个名字重试，网络与限流错误直接上报；
    实际用上的模型名写进 ``trace['model']``（缺省不传就丢弃），供引擎标注与排障。
    """
    if not config.get("enabled"):
        return None, "未配置大模型 API Key"
    post = post_json or http_post_json
    url = f"{str(config.get('base') or DEFAULT_BASE_URL).rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {config.get('key') or ''}"}
    timeout = int(config.get("timeout") or DEFAULT_TIMEOUT)
    chain = [m for m in (models or config.get("models")
                         or (config.get("model") or DEFAULT_MODEL,)) if str(m or "").strip()]
    if not chain:
        chain = [config.get("model") or DEFAULT_MODEL]
    tried, errors = [], []
    for model in chain:
        tried.append(str(model))
        try:
            data = post(url, build_request(config, model, context), headers, timeout)
        except Exception as exc:                  # 网络 / HTTP / 解析异常一律降级（不静默）
            err = f"{type(exc).__name__}: {exc}"
            errors.append(f"{model} → {err}")
            if not _model_fault(err):
                break
            continue
        payload, err = _read_completion(data)
        if payload is not None:
            if trace is not None:
                trace["model"] = str(model)
                trace["tried"] = tried
            return payload, ""
        errors.append(f"{model} → {err}")
        if not _model_fault(err):
            break
    if trace is not None:
        trace["tried"] = tried
    tail = f"（已试模型：{'、'.join(tried)}）" if len(tried) > 1 else ""
    return None, (errors[-1] if errors else "大模型调用失败") + tail


# ------------------------------------------------------------
# 接口探活（--llm-check）：不生成日报、不进留痕，只回答「这个 Key 现在能不能用」
# ------------------------------------------------------------
# 探活用的结构样本：字段与真实预测因子块同构，但数字是写死的示意值（不是行情），
# 因此可以脱离行情源单独验证「鉴权 → 模型名 → JSON 合同」这三层。
PROBE_CONTEXT = {
    "as_of": "2026-01-05",
    "target_date": "2026-01-14",
    "horizon_trading_days": HORIZON,
    "probe": True,
    "probe_note": "接口探活样本：数字为示意值，不构成预测、不进留痕、不推送",
    "anti_lookahead_guarantee": "输入闭合（所有数据 ≤ as_of）· 目标日严格在后",
    "indices": [{
        "code": "^HSI", "name": "恒生指数", "close": 25000.0,
        "predictive_factors": {
            "momentum_factor": {"ret5_pct": 1.2, "ret20_pct": 2.4, "ret60_pct": 5.0,
                                "score": 0.3, "driver": "探活样本"},
            "trend_channel_factor": {"ma20_dev_pct": 0.8, "ma60_dev_pct": 1.6,
                                     "range20_low": 24200.0, "range20_high": 25800.0,
                                     "score": 0.2, "driver": "探活样本"},
        },
        "quant_baseline": {"p_up": 0.55, "n_resolved": 0, "horizon_trading_days": HORIZON},
    }],
    "news_titles": [],
}


def llm_probe(config=None, get_json=None, post_json=None, models=None):
    """大模型接口探活：读配置 → 列 /models 目录 → 逐个候选模型发一次真实 JSON 请求。

    返回结构与结论（不抛异常、不生成日报、不写留痕）：

      {ok, verdict, problems, config{key_source,base,base_source,model,...},
       catalog{ok, ids, reason}, attempts[{model, ok, ms, error, targets, field_ok}]}

    ``ok=True`` 的含义是「这一栏现在能出内容」：至少一个模型返回了结构合法的 JSON
    （targets 覆盖探活样本里的 code、p_up 在 0.05~0.95 之间）。
    """
    cfg = config if config is not None else llm_config()
    problems = []
    if not cfg.get("enabled"):
        key_names = "、".join(ENV_KEY_NAMES)
        return {"ok": False, "problems": [f"未配置大模型 API Key（可用变量名：{key_names}）"],
                "verdict": "未配置 Key → AI 七日港股走势分析概率整栏缺席",
                "config": _probe_config_view(cfg), "catalog": {"ok": False, "ids": [], "reason": ""},
                "attempts": []}
    catalog = list_models(cfg, get_json=get_json)
    # 探活要的是「到底哪个能通」：候选链之外，把目录里剩下的模型也一并试掉（上限 MODEL_PROBE_MAX）。
    chain = list(models) if models else list(model_chain(cfg, catalog.get("ids")))
    for mid in catalog.get("ids") or []:
        if mid not in chain and len(chain) < MODEL_PROBE_MAX:
            chain.append(mid)
    post = post_json or http_post_json
    url = f"{str(cfg.get('base') or DEFAULT_BASE_URL).rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.get('key') or ''}"}
    timeout = int(cfg.get("timeout") or DEFAULT_TIMEOUT)
    attempts = []
    for model in chain:
        started = datetime.now(CST)
        row = {"model": str(model), "ok": False, "ms": 0, "error": "", "targets": [],
               "field_ok": False}
        try:
            data = post(url, build_request(cfg, model, PROBE_CONTEXT), headers, timeout)
            payload, err = _read_completion(data)
        except Exception as exc:
            payload, err = None, f"{type(exc).__name__}: {exc}"
        row["ms"] = int((datetime.now(CST) - started).total_seconds() * 1000)
        if payload is None:
            row["error"] = str(err)
            row["hint"] = llm_error_hint(err)
            attempts.append(row)
            # 探活要把范围量出来：HTTP 层面的错误（402 余额 / 401 鉴权 / 404 模型名…）继续试下一个，
            # 传输层面的错误（超时 / 连不上）换名字也一样，立即收手省时间。
            if "http " not in str(err).lower():
                break
            continue
        targets = [t for t in (payload.get("targets") or []) if isinstance(t, dict)]
        row["targets"] = [str(t.get("code") or "") for t in targets]
        row["field_ok"] = bool(targets) and all(
            t.get("p_up") is not None and PROB_FLOOR <= float(t["p_up"]) <= PROB_CAP
            for t in targets if str(t.get("code") or "").upper() == "^HSI")
        covers = any(str(t.get("code") or "").upper() == "^HSI" for t in targets)
        row["ok"] = bool(targets) and covers
        if not covers:
            row["error"] = "返回 JSON 里没有探活样本的 ^HSI"
        attempts.append(row)
        if row["ok"]:
            break
    ok = any(a["ok"] for a in attempts)
    hint = next((a.get("hint") for a in attempts if a.get("hint")), "")
    if not ok:
        problems.append("候选模型都没能返回合法的 JSON（逐条错误见下）")
    if catalog.get("ok") and attempts and all(a["model"] not in catalog["ids"] for a in attempts):
        problems.append("尝试的模型名都不在 /models 目录里")
    if hint:
        problems.append("下一步：" + hint)
    good = next((a["model"] for a in attempts if a["ok"]), "")
    return {
        "ok": ok,
        "problems": problems,
        "verdict": (f"就绪：模型 {good} 返回合法 JSON，这一栏可以出内容"
                    if ok else f"不可用：这一栏会按降级口径处理（{hint or '见 problems'}）"),
        "config": _probe_config_view(cfg),
        "catalog": catalog,
        "attempts": attempts,
    }


def _probe_config_view(config):
    """探活报告里的配置视图：只报「哪一个变量名生效」与不敏感的字面值，绝不回显 Key。"""
    cfg = config or {}
    return {"key_source": str(cfg.get("key_source") or ("(直接传入)" if cfg.get("key") else "")),
            "key_len": len(str(cfg.get("key") or "")),
            "base": str(cfg.get("base") or ""),
            "base_source": str(cfg.get("base_source") or ""),
            "model": str(cfg.get("model") or ""),
            "model_source": str(cfg.get("model_source") or ""),
            "model_explicit": bool(cfg.get("model_explicit")),
            "max_tokens": int(cfg.get("max_tokens") or 0),
            "timeout": int(cfg.get("timeout") or DEFAULT_TIMEOUT),
            "fallback": str(cfg.get("fallback") or "auto")}


# ------------------------------------------------------------
# 数字溯源：文案里的每个数字都必须能在给定数据里找到
# ------------------------------------------------------------
def _number_forms(value):
    """一个数值在文案里的常见写法（整数 / 一两位小数 / 千分位 / 百分号，正负号忽略）。"""
    forms = set()
    val = _num(value)
    if val is None:
        return forms
    for v in (val, abs(val)):                     # 符号不参与溯源：方向由概率字段负责
        for spec in ("{:.0f}", "{:.1f}", "{:.2f}", "{:,.0f}", "{:,.2f}"):
            try:
                forms.add(spec.format(v))
            except (ValueError, TypeError):
                continue
        if abs(v) <= 1000:
            for spec in ("{:.0f}%", "{:.1f}%", "{:.2f}%"):
                try:
                    forms.add(spec.format(v))
                except (ValueError, TypeError):
                    continue
    return forms


def _normalize_number(tok):
    return str(tok or "").strip().lstrip("+-").rstrip("%").replace(",", "")


def _collect_numbers(obj, strings, values):
    """递归收集数据里的全部数值（字符串只做原样收录，不解析）。"""
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, strings, values)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_numbers(v, strings, values)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        val = _num(obj)
        if val is None:
            return
        values.append(val)
        strings.update(_number_forms(val))
    elif isinstance(obj, str):
        for tok in _NUM_RE.findall(obj):
            strings.add(_normalize_number(tok))
    return strings, values


def _allowed_numbers(context, extra_values=()):
    """本次给定数据允许出现的数字集合（字符串写法 + 原值，供近似比对）。"""
    strings = {_normalize_number(t) for t in _CONST_NUMBERS}
    values = []
    _collect_numbers(context, strings, values)
    for v in extra_values:
        val = _num(v)
        if val is not None:
            values.append(val)
            strings.update({_normalize_number(f) for f in _number_forms(val)})
    return {"strings": strings, "values": values}


def _trace_numbers(text, allowed):
    """返回文案里查不到来源的数字集合（空集 = 全部可溯源）。"""
    missing = set()
    for tok in _NUM_RE.findall(str(text or "")):
        norm = _normalize_number(tok)
        if norm in allowed.get("strings", ()):
            continue
        try:
            val = float(norm)
        except ValueError:
            missing.add(tok)
            continue
        if any(abs(val - a) <= max(0.01, abs(a) * 0.005) for a in allowed.get("values") or ()):
            continue
        missing.add(tok)
    return missing


def _sanitize_text(text, limit, allowed):
    """清 HTML / 链接 / 绝对化措辞；数字查不到来源时返回 (None, missing)。"""
    s = _TAG_RE.sub(" ", str(text or ""))
    s = _URL_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return "", set()
    if _FORBIDDEN_RE.search(s):
        return None, {"绝对化措辞"}
    missing = _trace_numbers(s, allowed)
    if missing:
        return None, missing
    if len(s) > limit:
        s = s[:limit].rstrip(" ，,。.;；") + "…"
    return s, set()


def _quant_texts(ctx):
    """量化口径的文案模板（大模型文案不可用时的兜底，数字全部来自本次数据）。"""
    q = ctx.get("quant") or {}
    fb = ctx.get("factor_breakdown") or {}
    n_res = int(q.get("n_resolved") or 0)
    p_up_pct = float(ctx.get("p_up") or q.get("p_up") or 0.5) * 100
    summary = (f"量化基准 P(7日涨) {p_up_pct:.1f}%"
               f"（已结算 {n_res} 个 {HORIZON} 日样本）")

    primary = (f"扩张基准率 + 20日特征最近邻（K=8，已结算锚点，无未来函数）"
               f" · 已结算 {n_res} 个 {HORIZON} 日样本")
    drivers = [primary]
    candidates = []
    if fb.get("carry", {}).get("driver"):
        candidates.append(fb["carry"]["driver"])
    if fb.get("mom", {}).get("driver"):
        candidates.append(fb["mom"]["driver"])
    if fb.get("flow", {}).get("driver"):
        candidates.append(fb["flow"]["driver"])
    if fb.get("trd", {}).get("driver"):
        candidates.append(fb["trd"]["driver"])
    for d in candidates[:2]:
        if d and d not in drivers:
            drivers.append(d)

    risks = ["统计口径不含事件冲击与政策突发；样本外表现见留痕，非投资建议"]
    if fb.get("vol", {}).get("driver"):
        risks.append(fb["vol"]["driver"])
    return summary, drivers, risks


# ------------------------------------------------------------
# 合并大模型输出：概率收敛 + 文案溯源 + 兜底
# ------------------------------------------------------------
def merge_llm_estimate(payload, contexts, allowed):
    """把大模型 JSON 合并进量化上下文。

    返回 (by_symbol, notes)：by_symbol[code] = {texts..., "converged": bool, ...}；
    notes 汇总降级原因（供栏目与日志展示，绝不静默）。
    """
    notes = {"targets": 0, "p_fallback": 0, "text_fallback": 0, "converged": 0,
             "texts_offered": 0, "texts_traced": 0, "dropped": []}
    by_code = {}
    for item in (payload or {}).get("targets") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip().upper()
        if code:
            by_code[code] = item
    out = {}
    for ctx in contexts:
        code = ctx["symbol"].upper()
        item = by_code.get(code) or {}
        q = ctx.get("quant") or {}
        q_p = _clamp(q.get("p_up") if q.get("p_up") is not None else 0.5)
        p_up = _num(item.get("p_up"))
        converged = False
        if p_up is None:
            p_up = q_p
            notes["p_fallback"] += 1
        else:
            p_up = _clamp(p_up)
            if abs(p_up - q_p) > MAX_PROB_DEVIATION:      # 偏离过大 → 向量化基准收敛
                p_up = _clamp(q_p + math.copysign(MAX_PROB_DEVIATION, p_up - q_p))
                converged = True
                notes["converged"] += 1
        extra_values = [p_up * 100, ctx.get("close"),
                        item.get("support"), item.get("resistance")]
        allowed_for_target = _allowed_numbers(ctx, extra_values)
        allowed_for_target["strings"].update(allowed.get("strings", set()))
        allowed_for_target["values"].extend(allowed.get("values", []))

        def _pick(field, limit, max_items=3):
            raw = item.get(field)
            values = raw if isinstance(raw, list) else ([raw] if raw else [])
            good, dropped = [], 0
            for v in values[:max_items]:
                notes["texts_offered"] += 1
                text, missing = _sanitize_text(v, limit, allowed_for_target)
                if text is None or not text:
                    dropped += 1
                    if missing:
                        notes["dropped"].extend(sorted(missing)[:3])
                    continue
                notes["texts_traced"] += 1
                good.append(text)
            return good, dropped

        summary, drop_s = _pick("summary", 64)
        drivers, drop_d = _pick("drivers", 32)
        risks, drop_r = _pick("risks", 32)
        cross, _drop_c = _sanitize_text(payload.get("cross_note"), 80, allowed_for_target)
        d_sum, d_drv, d_rsk = _quant_texts(ctx)
        summary = summary[0] if summary else d_sum
        if not drivers:
            drivers = d_drv
        if not risks:
            risks = d_rsk
        notes["text_fallback"] += drop_s + drop_d + drop_r
        support = _num(item.get("support"))
        resistance = _num(item.get("resistance"))
        close = _num(ctx.get("close")) or 0.0
        if support is not None and not (close * 0.85 <= support <= close * 1.15):
            support = None
        if resistance is not None and not (close * 0.85 <= resistance <= close * 1.15):
            resistance = None
        out[code] = {
            "p_up": p_up, "quant_p_up": q_p, "converged": converged,
            "summary": summary, "drivers": drivers, "risks": risks,
            "support": support, "resistance": resistance,
            "cross_note": cross,
        }
        notes["targets"] += 1
    return out, notes


# ============================================================
# 留痕与结算：先存档（settled=False）→ 满 7 个交易日按真实收盘回填
# ============================================================
def _load_journal(path):
    empty = {"version": 1, "entries": []}
    if not path or not os.path.isfile(path):
        return empty
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return empty


def _save_journal(path, journal):
    if not path:
        return
    try:
        entries = journal.get("entries")
        if isinstance(entries, list) and len(entries) > JOURNAL_MAX_ENTRIES:
            journal["entries"] = entries[-JOURNAL_MAX_ENTRIES:]
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(journal, fh, ensure_ascii=False, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        pass  # 留痕写不进去不影响本次展示；下次运行再写


def _settle(entries, series, now=None):
    """结算所有已到龄的预测（目标日 = 锚定日 + 7 个交易日，没有那根 K 线就不结算）。"""
    now = now or datetime.now(CST)
    resolved_today = []
    today = now.strftime("%Y-%m-%d")
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("settled"):
            continue
        pair = series.get(entry.get("symbol"))
        if not pair:
            continue
        dates, closes = pair
        index = {d: i for i, d in enumerate(dates)}
        b = index.get(entry.get("base_date"))
        if b is None:
            continue
        j = b + HORIZON
        if j >= len(closes) or closes[b] <= 0:
            continue
        actual = closes[j] / closes[b] - 1.0
        entry["settled"] = True
        entry["settle_date"] = dates[j]
        entry["actual_ret"] = actual
        entry["actual_dir"] = "up" if actual > 0 else ("down" if actual < 0 else "flat")
        entry["hit"] = bool((entry.get("p_up") or 0.5) >= 0.5) == (actual > 0)
        entry["brier"] = (float(entry.get("p_up") or 0.5) - (1.0 if actual > 0 else 0.0)) ** 2
        if dates[j] == today:
            resolved_today.append(entry)
    return resolved_today


def _issue(ctx, merged, dates, closes, now):
    """按最新一根 K 线签发预测（同一锚定日同一标的只签发一次）。"""
    i = len(dates) - 1
    direction, label = _direction_label(merged["p_up"])
    base_date = dates[i]
    target_date = ctx.get("target_date") or next_trading_days(base_date, HORIZON)
    ok_seq, seq_note = assert_no_lookahead(base_date, target_date)
    return {
        "base_date": base_date,
        "base_close": closes[i],
        "target_date": target_date,
        "symbol": ctx["symbol"],
        "symbol_label": ctx["name"],
        "target_sessions": HORIZON,
        "target_note": f"锚定日后第 {HORIZON} 个交易日收盘（按交易日计数，假期顺延，目标日 {target_date}）",
        "p_up": merged["p_up"],
        "quant_p_up": merged.get("quant_p_up"),
        "factor_score": ctx.get("factor_score"),
        "engine": ctx.get("engine") or "quant",
        "direction": direction,
        "label": label,
        "no_lookahead": {"ok": ok_seq, "note": seq_note},
        "issued_cst": now.strftime("%Y-%m-%d %H:%M:%S%z"),
        "settled": False,
    }


def _journal_stats(entries):
    settled = [e for e in entries if isinstance(e, dict) and e.get("settled")]
    n = len(settled)
    hits = sum(1 for e in settled if e.get("hit"))
    recent = [{"date": e.get("settle_date"), "ret": e.get("actual_ret"),
               "hit": bool(e.get("hit")), "p_up": e.get("p_up")}
              for e in settled[-3:]]
    brier = None
    if n:
        vals = [e.get("brier") for e in settled if e.get("brier") is not None]
        if vals:
            brier = sum(vals) / len(vals)
    return {
        "n": n,
        "hits": hits,
        "hit_rate": (hits / n) if n >= MIN_JOURNAL_FOR_HITRATE else None,
        "brier": brier if n >= MIN_JOURNAL_FOR_HITRATE else None,
        "note": (None if n >= MIN_JOURNAL_FOR_HITRATE
                 else f"已结算 {n} 个样本（<{MIN_JOURNAL_FOR_HITRATE}，只报样本量）"),
        "recent": recent,
        "standing": sum(1 for e in entries if isinstance(e, dict) and not e.get("settled")),
    }


# ============================================================
# 对外入口与上下文构建
# ============================================================
def _fetch_bars_for(fetch_json, target, rng):
    """按候选代码顺序取日线；返回 (symbol, bars)，全失败返回 (None, [])。"""
    from octopus_quant.providers import fetch_bars  # 唯一复用的联网数据层

    for symbol in target["symbols"]:
        try:
            bars = fetch_bars(fetch_json, symbol, rng=rng)
        except Exception:
            bars = []
        if len(bars) >= MIN_BARS:
            return symbol, bars
    return None, []


def _build_context(target, symbol, bars, engine, extra=None):
    closes = [float(b["close"]) for b in bars]
    highs = [float(b.get("high") or b["close"]) for b in bars]
    lows = [float(b.get("low") or b["close"]) for b in bars]
    close = closes[-1]

    # 基础技术与价格特征
    ret5 = _ret_over(closes, 5)
    ret10 = _ret_over(closes, 10)
    ret20 = _ret_over(closes, 20)
    ret60 = _ret_over(closes, 60)
    ma20, ma60 = _sma(closes, 20), _sma(closes, 60)
    ma20_dev = (close / ma20 - 1.0) if ma20 else None
    ma60_dev = (close / ma60 - 1.0) if ma60 else None
    rsi14 = _rsi14(closes)
    vol_pct = _vol_pct(closes)
    hi20, lo20 = max(highs[-20:]), min(lows[-20:])
    hi52, lo52 = max(highs[-252:]), min(lows[-252:])
    var = _var7(closes)

    # 计算预测因子体系
    extra = extra or {}
    sigma = DAILY_SIGMA.get(symbol, 0.012)
    mom_score, mom_desc = compute_momentum_factor(ret20, sigma)
    trd_score, trd_desc = compute_trend_factor(ma20_dev, ma60_dev, lo20, hi20, close)
    rev_score, rev_desc = compute_reversal_factor(rsi14, (close / hi20 - 1.0) if hi20 > 0 else 0.0)
    carry_score, carry_desc = compute_global_carry_factor(symbol, extra.get("global_quotes"))
    flow_score, flow_desc = compute_capital_flow_factor(extra.get("flows"))
    vol_shrink, vol_desc = compute_volatility_shrinkage(vol_pct)
    macro_shrink, macro_desc = compute_macro_factor(extra.get("events"))

    raw_composite = (
        FACTOR_WEIGHTS["mom"] * mom_score +
        FACTOR_WEIGHTS["trd"] * trd_score +
        FACTOR_WEIGHTS["rev"] * rev_score +
        FACTOR_WEIGHTS["carry"] * carry_score +
        FACTOR_WEIGHTS["flow"] * flow_score
    )
    composite_score = math.tanh(raw_composite / 1.5) * 1.5 * vol_shrink * macro_shrink
    factor_delta = math.tanh(composite_score * 0.25) * 0.12

    factor_breakdown = {
        "mom": {"score": round(mom_score, 3), "driver": mom_desc},
        "trd": {"score": round(trd_score, 3), "driver": trd_desc},
        "rev": {"score": round(rev_score, 3), "driver": rev_desc},
        "carry": {"score": round(carry_score, 3), "driver": carry_desc},
        "flow": {"score": round(flow_score, 3), "driver": flow_desc},
        "vol": {"shrinkage": round(vol_shrink, 3), "driver": vol_desc},
        "macro": {"shrinkage": round(macro_shrink, 3), "driver": macro_desc},
        "composite_score": round(composite_score, 3),
        "factor_delta": round(factor_delta, 4),
    }

    q = quant_probability(closes, factor_scores=factor_breakdown)
    if not q.get("ok"):
        return None, q.get("reason") or "量化基准不可用"

    feats = q.get("features") or _features(closes, len(closes) - 1)
    vol20_ann = None
    if feats.get("vol20") is not None:
        vol20_ann = float(feats["vol20"]) * math.sqrt(TRADING_DAYS)

    as_of = bars[-1]["date"]
    target_date = next_trading_days(as_of, HORIZON)
    ok_seq, seq_note = assert_no_lookahead(as_of, target_date)

    # 因子摘要（给页面和大模型展示核心驱动）
    top_factors = []
    if abs(carry_score) >= 0.2:
        top_factors.append(carry_desc.split("（")[0])
    if abs(mom_score) >= 0.2:
        top_factors.append("动量延续" if mom_score > 0 else "动量回归")
    if abs(trd_score) >= 0.2:
        top_factors.append("趋势向上" if trd_score > 0 else "趋势偏弱")
    if abs(rev_score) >= 0.3:
        top_factors.append("超卖反弹" if rev_score > 0 else "超买回踩")
    if abs(flow_score) >= 0.2:
        top_factors.append("南向资金流入" if flow_score > 0 else "资金面偏紧")
    factor_summary = " · ".join(top_factors[:3]) if top_factors else "各因子表现中性均衡"

    ctx = {
        "name": target["name"], "short": target["short"], "symbol": symbol,
        "asof": as_of, "target_date": target_date, "close": close,
        "ret5": ret5, "ret10": ret10, "ret20": ret20, "ret60": ret60,
        "ma20_dev": ma20_dev, "ma60_dev": ma60_dev,
        "rsi14": rsi14, "vol_pct": vol_pct, "vol20_ann": vol20_ann,
        "hi20": hi20, "lo20": lo20, "hi52": hi52, "lo52": lo52,
        "var7": var,
        "lo95": close * (1.0 + var["q05"]) if var else None,
        "hi95": close * (1.0 + var["q95"]) if var else None,
        "features": feats, "quant": q, "engine": engine,
        "factor_breakdown": factor_breakdown,
        "factor_score": round(composite_score, 3),
        "factor_delta": round(factor_delta, 4),
        "factor_summary": factor_summary,
        "no_lookahead": {"ok": ok_seq, "note": seq_note},
        "bars_n": len(closes),
    }
    return ctx, ""


def _context_for_prompt(contexts, extra):
    """交给大模型的数据块（唯一可用依据）——按预测因子体系结构化组织。"""
    def _r2(v):
        x = _num(v)
        return None if x is None else round(x, 2)

    def _pct(v):
        x = _num(v)
        return None if x is None else round(x * 100, 1)

    asof = contexts[0]["asof"] if contexts else None
    target_date = contexts[0].get("target_date") if contexts else None

    ctx = {
        "as_of": asof,
        "target_date": target_date,
        "horizon_trading_days": HORIZON,
        "anti_lookahead_guarantee": "输入闭合（所有数据 ≤ as_of）· 目标日严格在后 · 截断不变性自检通过",
        "indices": [],
    }
    for c in contexts:
        fb = c.get("factor_breakdown") or {}
        ctx["indices"].append({
            "code": c["symbol"], "name": c["name"],
            "close": _r2(c["close"]),
            "predictive_factors": {
                "momentum_factor": {
                    "ret5_pct": _pct(c.get("ret5")),
                    "ret20_pct": _pct(c.get("ret20")),
                    "ret60_pct": _pct(c.get("ret60")),
                    "score": fb.get("mom", {}).get("score"),
                    "driver": fb.get("mom", {}).get("driver"),
                },
                "trend_channel_factor": {
                    "ma20_dev_pct": _pct(c.get("ma20_dev")),
                    "ma60_dev_pct": _pct(c.get("ma60_dev")),
                    "range20_low": _r2(c.get("lo20")),
                    "range20_high": _r2(c.get("hi20")),
                    "score": fb.get("trd", {}).get("score"),
                    "driver": fb.get("trd", {}).get("driver"),
                },
                "reversal_oscillator": {
                    "rsi14": _r2(c.get("rsi14")),
                    "drawdown20_pct": _pct((c.get("features") or {}).get("dd20")),
                    "score": fb.get("rev", {}).get("score"),
                    "driver": fb.get("rev", {}).get("driver"),
                },
                "global_carry_factor": {
                    "score": fb.get("carry", {}).get("score"),
                    "driver": fb.get("carry", {}).get("driver"),
                },
                "capital_flow_factor": {
                    "score": fb.get("flow", {}).get("score"),
                    "driver": fb.get("flow", {}).get("driver"),
                },
                "volatility_regime": {
                    "vol20_annual_pct": _pct(c.get("vol20_ann")),
                    "vol_percentile_pct": _pct(c.get("vol_pct")),
                    "shrinkage": fb.get("vol", {}).get("shrinkage"),
                },
                "composite_factor_score": fb.get("composite_score"),
                "factor_delta_pct": _pct(fb.get("factor_delta")),
            },
            "quant_base_prob_up": round(float((c.get("quant") or {}).get("p_up") or 0.5), 3),
            "quant_resolved_samples": int((c.get("quant") or {}).get("n_resolved") or 0),
            "hist_7d_q05_pct": _pct((c.get("var7") or {}).get("q05")),
            "hist_7d_q95_pct": _pct((c.get("var7") or {}).get("q95")),
            "hist_7d_samples": int((c.get("var7") or {}).get("n") or 0),
        })
    g_quotes = extra.get("global_quotes") or {}
    if g_quotes:
        ctx["global_us_indices"] = g_quotes
    flows = extra.get("flows") or {}
    if any(v is not None for v in flows.values()):
        ctx["southbound"] = flows
    events = extra.get("events") or []
    if events:
        ctx["upcoming_events"] = events[:6]
    news = extra.get("news") or []
    if news:
        ctx["hk_headlines"] = news[:MAX_TEXT_NEWS]
    return ctx


def run_seven_day(fetch_json=None, *, history_path=None, extra=None, post_json=None,
                  now=None, targets=None, rng="2y", bars_by_symbol=None,
                  config=None, jev_config=None):
    """计算 + 研判（大模型 > Jev 类型化决策 > 量化基准）+ 留痕结算；返回供管线消费的结果字典。

    研判引擎优先级（2026-10-03 起新增 Jev 第三引擎，见 output/jev_bridge.py）：
      · 大模型（config 里有 Key 且调用成功）；
      · Jev（jev_config 里有端点且调用成功；概率与量化基准按同一份常量对账，
        另在 jev_forecast.json 留一份研究留痕，同一套 T+7 结算口径）；
      · 量化基准（两者都不可用时的兜底）。
    jev_config 缺省时读环境变量（OCTOPUS_JEV_BASE_URL / TYPESAFE_BASE_URL）；
    未配置端点时行为与引入 Jev 之前完全一致。

    可用时：{available: True, asof, target_date, horizon, engine, engine_label, llm_reason,
             targets: [...], journal, notes, method, grounded, jev: {enabled, ready,
             tried, used, model, reason, mode, stats}}
    不可用：{available: False, reason}（同样带 jev 状态，供「数据覆盖」点名）
    """
    now = now or datetime.now(CST)
    extra = extra or {}
    config = config or llm_config()
    targets = targets or TARGETS

    # Jev 类型化决策（第三引擎）：这里只读配置、不发请求；实际调用在 2b 步，
    # 且仅当大模型没有给出结果时才轮到它（优先级：大模型 > Jev > 量化基准）。
    import jev_bridge as _jev  # 惰性导入：避免与 jev_bridge 对本模块常量的引用形成循环
    jcfg = jev_config if jev_config is not None else _jev.jev_config()
    jev_info = {"enabled": bool(jcfg.get("enabled")), "mode": jcfg.get("mode") or "auto",
                "ready": False, "tried": False, "used": False, "model": "", "reason": "",
                "stats": None}

    # 1) 取日线并确定基准日
    used, contexts = {}, []
    for target in targets:
        bars = []
        symbol = None
        if bars_by_symbol:
            for cand in target["symbols"]:
                if len(bars_by_symbol.get(cand) or []) >= MIN_BARS:
                    symbol, bars = cand, bars_by_symbol[cand]
                    break
        else:
            symbol, bars = _fetch_bars_for(fetch_json, target, rng)
        if not bars:
            continue
        used[symbol] = bars

    if not used:
        return {"available": False,
                "reason": f"三只指数都没有足够的日线样本（每只至少 {MIN_BARS} 根）",
                "jev": jev_info}

    # 确定基准日，并执行输入闭合性检验（防止未来日期混入证据）
    base_date = next((bars[-1]["date"] for bars in used.values() if bars), "")
    closure_ok, closure_warns, cleaned_extra = check_input_closure(base_date, extra)

    for target in targets:
        symbol = next((cand for cand in target["symbols"] if cand in used), None)
        if not symbol:
            continue
        bars = used[symbol]
        engine = "llm" if config.get("enabled") else "quant"
        ctx, reason = _build_context(target, symbol, bars, engine, extra=cleaned_extra)
        if ctx is None:
            continue
        contexts.append(ctx)

    if not contexts:
        return {"available": False,
                "reason": f"三只指数都没有足够的日线样本（每只至少 {MIN_BARS} 根）",
                "jev": jev_info}
    if len(contexts) < len(targets):
        missing = [t["name"] for t in targets
                   if t["name"] not in {c["name"] for c in contexts}]
        reason = "部分标的日线不可用：" + "、".join(missing)
    else:
        reason = ""

    # 2) 大模型研判（可选，第一优先）
    prompt_ctx = _context_for_prompt(contexts, cleaned_extra)
    llm_payload, llm_error = (None, "未配置大模型 API Key")
    llm_trace = {"model": "", "tried": []}
    if config.get("enabled"):
        llm_payload, llm_error = call_llm(config, prompt_ctx, post_json=post_json,
                                          trace=llm_trace)

    # 2b) Jev 类型化决策（第三引擎）：只有大模型没有给出结果、且端点已配置时才调用。
    #      概率与量化基准按同一份常量对账（>20pp 收敛 / 5%~95% 夹边），模型不产文本；
    #      它自己的研究留痕写在 jev_forecast.json（同一套 T+7 结算口径）。
    series = {sym: ([b["date"] for b in bars], [float(b["close"]) for b in bars])
              for sym, bars in used.items()}
    jev_items = {}
    if not llm_payload and jev_info["enabled"]:
        jev_info["tried"] = True
        if history_path:
            jev_journal_path = os.path.join(os.path.dirname(history_path) or ".",
                                            _jev.JOURNAL_FILENAME)
            jj = _load_journal(jev_journal_path)   # 先结算已到龄的 Jev 留痕，再签发新的
            if _settle(jj["entries"], series, now=now):
                _save_journal(jev_journal_path, jj)
        else:
            jev_journal_path = None
        baseline_map = {c["symbol"]: {"quant_p_up": (c.get("quant") or {}).get("p_up"),
                                      "name": c.get("short") or c.get("name")}
                        for c in contexts}
        jev_result = _jev.run(config=jcfg, contexts=contexts, baseline_map=baseline_map,
                              journal_path=jev_journal_path, post_json=post_json)
        jev_info["ready"] = bool(jev_result.get("ready"))
        jev_info["stats"] = jev_result.get("stats")
        jev_info["model"] = next((t.get("model_meta", {}).get("model") or ""
                                  for t in jev_result.get("targets") or []
                                  if (t.get("model_meta") or {}).get("model")), "")
        for item in jev_result.get("targets") or []:
            jev_items[item.get("symbol")] = item

    jev_used = {}
    for ctx in contexts:
        item = jev_items.get(ctx["symbol"]) or {}
        jm = item.get("merged")
        if jm and jm.get("source") in ("noul", "choice"):
            jev_used[ctx["symbol"]] = jm
    jev_info["used"] = bool(jev_used)
    if not jev_used and jev_info["enabled"] and not llm_payload:
        if not jev_info["tried"]:
            jev_info["reason"] = "未调用"
        elif not jev_info["ready"]:
            problems = [p for p in ((jev_result or {}).get("problems") or [])
                        if "always" not in p]
            jev_info["reason"] = problems[0] if problems else "端点探活失败"
        else:
            problems = [p for p in ((jev_result or {}).get("problems") or [])
                        if "always" not in p]
            jev_info["reason"] = problems[0] if problems else "模型未返回可用概率"

    # 降级与缺席口径（引入 Jev 后：Jev 顶上了「大模型不可用」的位置，
    # 只有大模型与 Jev 都拿不到概率时才落到量化基准 / 整栏缺席）：
    if not llm_payload and not jev_used and config.get("fallback") == "never":
        return {"available": False, "llm_reason": llm_error,
                "reason": f"大模型不可用（{llm_error}）", "jev": jev_info}
    if (not llm_payload and not jev_used and not config.get("enabled")
            and jev_info["enabled"] and jev_info["mode"] == "always"):
        return {"available": False, "llm_reason": llm_error,
                "reason": (f"Jev 端点不可用且 OCTOPUS_JEV_MODE=always → 整栏缺席"
                           f"（{jev_info.get('reason') or jev_info.get('model') or '原因未知'}）"),
                "jev": jev_info}

    engine = "llm" if llm_payload else ("jev" if jev_used else "quant")
    for ctx in contexts:
        ctx["engine"] = engine

    merged, notes = {}, {"targets": 0, "text_fallback": 0, "converged": 0}
    if llm_payload:
        merged, notes = merge_llm_estimate(
            llm_payload, contexts, _allowed_numbers(prompt_ctx))
    if not merged:
        merged = {}
        for ctx in contexts:
            d_sum, d_drv, d_rsk = _quant_texts(ctx)
            q_p = _clamp((ctx.get("quant") or {}).get("p_up") or 0.5)
            jm = jev_used.get(ctx["symbol"])
            if jm:
                # Jev 只给值 + 概率，不给文案：文案一律走量化模板，只附一句概率对账说明
                merged[ctx["symbol"]] = {
                    "p_up": _clamp(jm.get("p_up") or q_p),
                    "quant_p_up": q_p,
                    "converged": bool(jm.get("converged")),
                    "summary": d_sum + (f" · {jm.get('note')}" if jm.get("note") else ""),
                    "drivers": d_drv, "risks": d_rsk,
                    "support": None, "resistance": None,
                    "cross_note": "",
                }
            else:
                merged[ctx["symbol"]] = {
                    "p_up": q_p,
                    "quant_p_up": q_p,
                    "converged": False, "summary": d_sum, "drivers": d_drv, "risks": d_rsk,
                    "support": None, "resistance": None,
                    "cross_note": "",
                }
        notes["targets"] = len(contexts)
        notes["converged"] = sum(1 for jm in jev_used.values() if jm.get("converged"))

    # 3) 留痕：先结算历史，再按最新锚定日签发（同一锚定日不重复签发；
    #    Jev 引擎的预测同样写进本栏留痕，engine 字段区分，另在 jev_forecast.json 留研究留痕）
    journal = _load_journal(history_path)
    entries = journal.setdefault("entries", [])
    resolved_today = _settle(entries, series, now=now)
    changed = bool(resolved_today)
    for ctx in contexts:
        sig = merged.get(ctx["symbol"])
        if not sig:
            continue
        b_date = ctx["asof"]
        if any(isinstance(e, dict) and e.get("symbol") == ctx["symbol"]
               and e.get("base_date") == b_date for e in entries):
            continue
        entries.append(_issue(ctx, sig, *series[ctx["symbol"]], now))
        changed = True
    if changed:
        journal["updated_cst"] = now.strftime("%Y-%m-%d %H:%M:%S%z")
        _save_journal(history_path, journal)
    stats = _journal_stats(entries)

    # 4) 组装展示结构
    out_targets = []
    for ctx in contexts:
        sig = merged.get(ctx["symbol"]) or {}
        p_up = _clamp(sig.get("p_up") if sig.get("p_up") is not None else
                      (ctx.get("quant") or {}).get("p_up") or 0.5)
        direction, label = _direction_label(p_up)
        q = ctx.get("quant") or {}
        q_p = _clamp(q.get("p_up") if q.get("p_up") is not None else 0.5)
        out_targets.append({
            "code": ctx["symbol"], "name": ctx["name"], "short": ctx["short"],
            "close": ctx["close"], "asof": ctx["asof"], "target_date": ctx.get("target_date"),
            "ret5": ctx.get("ret5"), "ret20": ctx.get("ret20"),
            "rsi14": ctx.get("rsi14"), "vol20": ctx.get("vol20_ann"),
            "vol_pct": ctx.get("vol_pct"), "dd20": (ctx.get("features") or {}).get("dd20"),
            "lo95": ctx.get("lo95"), "hi95": ctx.get("hi95"),
            "var_n": (ctx.get("var7") or {}).get("n"),
            "p_up": p_up, "direction": direction, "label": label,
            "quant_p_up": q_p, "deviation": p_up - q_p,
            "converged": bool(sig.get("converged")),
            "factor_score": ctx.get("factor_score"),
            "factor_delta": ctx.get("factor_delta"),
            "factor_summary": ctx.get("factor_summary"),
            "factor_breakdown": ctx.get("factor_breakdown"),
            "no_lookahead": ctx.get("no_lookahead"),
            "summary": sig.get("summary") or "", "drivers": sig.get("drivers") or [],
            "risks": sig.get("risks") or [],
            "support": sig.get("support"), "resistance": sig.get("resistance"),
            "backtest": q.get("backtest"), "self_check": q.get("self_check"),
        })
    crosses = [c for c in (merged.get(c2["symbol"], {}).get("cross_note")
                           for c2 in contexts) if c]
    if engine == "llm":
        engine_label = f"大模型 · {llm_trace.get('model') or config.get('model')}"
    elif engine == "jev":
        engine_label = (f"Jev 本地模型 · {jev_info.get('model') or '类型化决策'}"
                        f" · 概率已按基准收敛")
    else:
        engine_label = "量化多因子规则（无大模型 Key 或调用失败已降级）"
    offered = int(notes.get("texts_offered") or 0)
    traced = int(notes.get("texts_traced") or 0)
    grounded = (f"{traced}/{offered}" if (engine == "llm" and offered)
                else ("—" if engine in ("quant", "jev") else "0/0"))
    is_today = any(t["asof"] == now.strftime("%Y-%m-%d") for t in out_targets)
    return {
        "available": True,
        "asof": contexts[0]["asof"],
        "target_date": contexts[0].get("target_date"),
        "horizon": HORIZON,
        "engine": engine,
        "engine_label": engine_label,
        "llm_model": (llm_trace.get("model") or config.get("model")) if engine == "llm" else None,
        "llm_models_tried": list(llm_trace.get("tried") or []),
        "llm_key_source": str(config.get("key_source") or ""),
        "llm_reason": "" if engine == "llm" else str(llm_error or "未配置大模型 API Key"),
        "targets": out_targets,
        "journal": stats,
        "notes": notes,
        "grounded": grounded,
        "cross_note": crosses[0] if crosses else "",
        "missing": reason,
        "is_today": bool(is_today),
        "jev": jev_info,
        "method": (f"量化多因子基准（扩张基准率 + 20日特征最近邻 + 动量延展/均值回归 + 均线趋势 + 美股隔夜联动(β) + 南向资金流 + 波动率收缩，s+{HORIZON}≤t 已结算锚点）"
                   + (" + 大模型合成（概率收敛 + 数字溯源）" if engine == "llm" else "")
                   + (" + Jev 类型化决策（choice/noul/score，不产文本，概率与基准同常量对账）"
                      if engine == "jev" else "")),
    }
