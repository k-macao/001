#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📅 【嗜血大白鲨】逐日走势量化分析 —— 未来 7 个交易日港股逐日走势表格（无未来函数）。

栏目形态（2026-09-29 按用户要求升级；原「每周量化走势预测 · 未来 5 个交易日」）：
  · **逐日表格**：未来 7 个交易日每天一行 —— 预测（方向 + 累计上涨概率 + 当日环比概率）、
    预期区间（80% 中心区间）、理由（可解释的因子数字 + 基准率 / 相似样本合成过程）、
    分析（一句人话解读）、AI 操作建议（规则合成：操作倾向 + 仓位区间 + 止损 + 止盈参考）；
  · **七日整段结论**：P(未来 7 个交易日上涨) = 逐日表格第 7 行的累计口径（同一份数字，
    不另算一套）；留痕按 entry 自带的 target_sessions 结算（新档满 7 个交易日，
    旧档仍按签发时的 5 个交易日结算完，历史不篡改）。
  因果口径与旧版完全一致：每个视界 h ∈ [1, 7] 的标签只数 s+h ≤ t 的已结算样本，
  类比锚点同样要求 s+h ≤ t；运行时截断不变性自检覆盖全部 7 个视界。

方法学来源（GitHub 公开量化工程实践调研，2026-09-28）：

  · akfamily/akquant（AKQuant · docs/zh/advanced/ml.md）
      防未来函数教义：特征 X 只能用 t 及之前；标签 y 描述 t 之后；预处理统计量
      （均值/方差）不得来自全样本，必须滚动 / 扩张因果计算。
  · arielb57/peekahead（黑箱前视偏差检测器）
      核心不变量「截断不变性」：输出 ≤ t 的行只依赖输入 ≤ t 的行——删掉 / 扰动 t
      之后的数据，过去时刻的输出必须逐位不变。本模块把该检测做成运行时自检
      （check_no_lookahead），自检不过整栏降级，绝不产出预测。
  · paidaxing1234/quant-backtest-guard（回测照妖镜）
      未来函数 / 标签泄漏为致命项：不用 close[i+1] 预测 close[i]、不做全样本
      z-score 归一化、信号不得在未收盘前生效。
  · haeganm/walkforward（purged / embargo walk-forward splits）
      相似样本（类比锚点）的标签必须在预测时点之前全部结算：锚点 s 需满足 s+H ≤ t。
  · k-macao/03 PR #54「AI 预测 · 未来函数」栏目（同组织姊妹仓）
      四条硬约束：①输入闭合（只读当次快照）②目标日在严格之后（不成立即整栏降级）
      ③先存档后结算（先落盘 settled=False，后续按真实行情回填）④零写死叙事；
      结算样本 <10 只报样本量，不下命中率结论。
  · 本仓库 output/octopus_quant/probability.py：推进式（walk-forward）回测与概率夹逼。

预测器（三条腿，纯确定性规则，无随机数、不调外部模型、纯标准库）：
  1. 历史基准 P0 —— 过去已结算周度涨跌的拉普拉斯平滑频率（只数 s+H ≤ t 的标签）；
  2. 相似样本 P_sim —— 当前 20 日特征（逐期扩张 z 标准化，绝不全样本归一）在已结算
     锚点里取 K=8 最近邻，其周度方向的拉普拉斯平滑频率；
  3. 合成 P = (P0 + P_sim) / 2，夹在 5%~95%；已结算锚点 <4 个时退化为 P0 并如实标注。

留痕与结算：预测先写入 output/weekly_forecast.json（settled=False），满 7 个交易日
（2026-09-29 前签发的旧档仍按其签发时的 5 个交易日）后按真实收盘回填实际涨跌与命中
——当次运行结构上不可能结算当次预测。

对外入口：run_weekly(fetch_json, history_path=...)；任一步失败都返回
available=False + 原因，由上层决定整栏缺席（绝不编造数据）。
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))

# ---- 口径常量（写死可复现；改任何一条都会改变预测，必须同步测试）----
WINDOW = 20            # 特征窗口（交易日）
HORIZON = 7            # 预测视界 = 未来 7 个交易日（逐日表格的最大视界，也是整段结论口径）
LEGACY_HORIZON = 5     # 旧档案（2026-09-29 之前签发）的视界：按签发时口径结算，不篡改历史
PATH_MAX = HORIZON     # 逐日表格行数 = 7 个交易日
BAND_Z = 1.2816        # 预期区间用 80% 中心区间（正态 10%~90% 分位）；σ 取 20 日实测波动
TRADING_DAYS = 252     # 年化系数（与港股量化引擎 / hk_seven_day 同口径）
ANALOG_K = 8           # 相似样本（最近邻）个数
MIN_ANALOGS = 4         # 相似样本退化阈值：不足则只用历史基准
MIN_RESOLVED = 30      # 历史基准最少已结算样本数（不足则不产出信号）
MIN_BARS = 60          # 最少日线根数（≈ WINDOW + HORIZON + MIN_RESOLVED + 余量）
PROB_FLOOR = 0.05      # 概率硬边界：统计模型永远保留被证伪的余地
PROB_CAP = 0.95
DIR_UP = 0.58          # 展示方向阈值（结算一律按 P ≥ 0.5 的底牌方向）
DIR_DOWN = 0.42
JOURNAL_FILENAME = "weekly_forecast.json"
JOURNAL_MAX_ENTRIES = 40
FEATURE_KEYS = ("ret5", "ret10", "ret20", "vol20", "dd20")

# 可展示的指数别名（不写死任何具体日期 / 点位叙事）
_SYMBOL_LABELS = {
    "^HSI": "恒生指数",
    "^HSTECH": "恒生科技",
    "^HSCEI": "国企指数",
}


# ============================================================
# 基础工具（纯函数，可离线单测）
# ============================================================
def _clamp(p):
    return max(PROB_FLOOR, min(PROB_CAP, float(p)))


def _pstdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    mu = sum(xs) / n
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / n)


def _features(closes, t):
    """t 时刻（含）之前的窗口特征 —— 只读 closes[0..t]，无未来数据。"""
    c0 = closes[t]

    def _ret(k):
        prev = closes[t - k]
        return (c0 / prev - 1.0) if prev > 0 else 0.0

    w = closes[t - WINDOW + 1:t + 1]
    rets = [w[i] / w[i - 1] - 1.0 for i in range(1, len(w)) if w[i - 1] > 0]
    peak = max(w)
    return {
        "ret5": _ret(5),
        "ret10": _ret(10),
        "ret20": _ret(WINDOW),
        "vol20": _pstdev(rets),
        "dd20": (c0 / peak - 1.0) if peak > 0 else 0.0,
    }


def _dist2(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _lean_word(p_up):
    """中性档里的倾向措辞：50% 就是五五开，绝不写成「略偏涨」误导读者。"""
    if p_up > 0.5:
        return "略偏涨"
    if p_up < 0.5:
        return "略偏跌"
    return "五五开"


def _horizon_label(p_up, horizon=HORIZON):
    """P(未来 h 个交易日上涨) → (结算方向, 展示文案)。展示可中性，结算只认 P ≥ 0.5 的底牌。"""
    p_up = _clamp(p_up)
    noun = f"P({horizon}日涨)"
    if p_up >= DIR_UP:
        return "up", f"▲ 看涨 · {noun} {p_up * 100:.0f}%"
    if p_up <= DIR_DOWN:
        return "down", f"▼ 看跌 · {noun} {p_up * 100:.0f}%"
    return "neutral", f"■ 中性（{_lean_word(p_up)}）· {noun} {p_up * 100:.0f}%"


# 兼容旧名（tests / 外部调用）：默认视界即当前 HORIZON
def _weekly_label(p_up, horizon=HORIZON):
    return _horizon_label(p_up, horizon)


def _day_label(p_up, horizon=None):
    """逐日表格的方向文案：▲ 看涨 / ▼ 看跌 / ■ 中性 + 概率（不含「P(周涨)」口径词）。"""
    p_up = _clamp(p_up)
    if p_up >= DIR_UP:
        return "up", f"▲ 看涨 {p_up * 100:.0f}%"
    if p_up <= DIR_DOWN:
        return "down", f"▼ 看跌 {p_up * 100:.0f}%"
    return "neutral", f"■ 中性（{_lean_word(p_up)}）{p_up * 100:.0f}%"


# ============================================================
# 信号计算：单向前向扫描，每个 t 的输出只吃 ≤t 的输入（截断不变）
# ============================================================
def _blend(z_t, candidates, resolved_ys):
    """历史基准 + 相似样本最近邻 → 合成概率（三个视界共用同一口径，不另算一套）。

    1) 历史基准 P0：已结算标签的拉普拉斯平滑上涨频率；
    2) 相似样本 P_sim：已结算锚点里按「两侧各自当期扩张 z 坐标」的欧氏距离取 K 最近邻，
       取其方向的拉普拉斯平滑频率；锚点 ≥ MIN_ANALOGS 个才参与合成，否则退化为 P0
       （blended=False，如实标注）。
    """
    n_res = len(resolved_ys)
    p0 = _clamp((sum(resolved_ys) + 1.0) / (n_res + 2.0))
    ranked = sorted(candidates, key=lambda c: _dist2(c[0], z_t))[:ANALOG_K]
    n_analog = len(ranked)
    if n_analog >= MIN_ANALOGS:
        p_sim = _clamp((sum(c[1] for c in ranked) + 1.0) / (n_analog + 2.0))
        p = _clamp((p0 + p_sim) / 2.0)
        blended = True
    else:
        p_sim, p, blended = None, p0, False
    return {"p_up": p, "p_base": p0, "p_sim": p_sim, "n_analog": n_analog,
            "n_resolved": n_res, "blended": blended}


def _scan(closes, horizons):
    """一次因果扫描算出多个视界的信号（特征与扩张 z 只算一遍，各视界独立记账）。

    因果性（每条都被 tests/test_weekly.py 的截断不变性测试锁死）：
      · 特征只用 closes[0..t]；扩张 z 标准化的均值/方差逐期更新（非全样本统计量）；
      · 每个视界 h 的基准率只数已结算标签：s + h ≤ t；
      · 相似锚点同样要求 s + h ≤ t（purged/embargo 依据）
        —— 锚点带自己当期的 z 坐标（z_at[s]），绝不借用未来统计量；
      · 距离只在两侧各自的「当期扩张标准化」坐标里比较，未来行不参与。
    """
    closes = [float(c) for c in (closes or [])]
    n = len(closes)
    horizons = tuple(sorted({int(h) for h in horizons if int(h) > 0}))
    if n < MIN_BARS:
        return {"ok": False, "reason": f"日线样本不足（{n} < {MIN_BARS} 根）",
                "signals": {h: [None] * n for h in horizons}, "vol_hist": [],
                "first_signal": {}, "horizons": horizons}

    # 逐特征 Welford 扩张统计（count, mean, M2）；含当期 t（当期值在 t 时刻可观测）
    wstats = {k: [0, 0.0, 0.0] for k in FEATURE_KEYS}
    z_at = {}                                  # t → 当期扩张 z 坐标
    cand = {h: [] for h in horizons}           # h → [(z_s, y_s, s)] 已结算类比锚点
    resolved = {h: [] for h in horizons}       # h → 已结算方向标签（历史基准样本）
    vol_hist = []                              # 逐期 vol20（因果序列，供扩张分位展示）
    signals = {h: [None] * n for h in horizons}

    for t in range(WINDOW, n):
        f = _features(closes, t)
        for k in FEATURE_KEYS:
            m = wstats[k]
            x = f[k]
            m[0] += 1
            delta = x - m[1]
            m[1] += delta / m[0]
            m[2] += delta * (x - m[1])
        z = []
        for k in FEATURE_KEYS:
            m = wstats[k]
            sd = math.sqrt(m[2] / m[0]) if m[0] > 1 else 0.0
            z.append(0.0 if sd < 1e-12 else (f[k] - m[1]) / sd)
        z_t = tuple(z)
        z_at[t] = z_t
        vol_hist.append(f["vol20"])

        for h in horizons:
            # t 推进后，锚点 s = t - h 的标签此刻已经结算（严格在先）
            s = t - h
            if s >= WINDOW:
                y = 1.0 if closes[s + h] > closes[s] else 0.0
                cand[h].append((z_at[s], y, s))
                resolved[h].append(y)
            if len(resolved[h]) < MIN_RESOLVED:
                continue
            sig = _blend(z_t, cand[h], resolved[h])
            sig["features"] = f
            signals[h][t] = sig

    first = {h: next((i for i, sg in enumerate(signals[h]) if sg), None) for h in horizons}
    if all(v is None for v in first.values()):
        return {"ok": False, "reason": "已结算样本不足（<%d 个）" % MIN_RESOLVED,
                "signals": signals, "vol_hist": vol_hist, "first_signal": first,
                "horizons": horizons}
    return {"ok": True, "reason": "", "signals": signals, "vol_hist": vol_hist,
            "first_signal": first, "horizons": horizons}


def compute_signals(closes, horizon=HORIZON):
    """逐期滚动计算某个视界的方向信号（horizon 默认 = 未来 7 个交易日）。

    返回 {"ok", "reason", "signals", "vol_hist"}：
      signals[t] = None（样本不足）或
      {"p_up", "p_base", "p_sim", "n_analog", "n_resolved", "blended", "features"}
    """
    out = _scan(closes, (horizon,))
    horizon = int(horizon)
    signals = out["signals"].get(horizon) or []
    res = {"ok": out["ok"], "reason": out.get("reason") or "",
           "signals": signals, "vol_hist": out["vol_hist"]}
    if out["ok"]:
        res["first_signal"] = out["first_signal"].get(horizon)
    return res


def compute_path_signals(closes, max_horizon=PATH_MAX):
    """逐日表格的信号底座：一次扫描算出视界 1..max_horizon 的全部因果信号。

    signals_by_h[h][t] = P(closes[t+h] > closes[t] | 信息集 ≤ t)；
    h = k 就是「未来第 k 个交易日相对锚定日的累计涨跌」，k=1..7 正好是表格的 7 行。
    """
    out = _scan(closes, tuple(range(1, int(max_horizon) + 1)))
    return {"ok": out["ok"], "reason": out.get("reason") or "",
            "signals_by_h": out["signals"], "vol_hist": out["vol_hist"],
            "first_signal": out["first_signal"],
            "horizons": tuple(range(1, int(max_horizon) + 1))}


# ------------------------------------------------------------
# 未来函数自检：peekahead 式截断不变性（运行时执行，不过则整栏降级）
# ------------------------------------------------------------
def check_no_lookahead(closes, cuts=None, max_horizon=PATH_MAX, horizon=None):
    """对任意截断点 k，**全部 7 个视界**的 signals[k] 必须逐位不依赖 k 之后的输入。

    返回 (ok, message)。ok=False 时上层必须整栏降级——这是「目标日严格在后」的
    运行时等价物（k-macao/03 PR #54 约束②：assert 不成立不出预测）。
    逐日表格的 7 行都出自同一次扫描，因此自检也必须覆盖 7 个视界，不能只查 h=7。

    ``horizon`` 为向后兼容别名（hk_seven_day 以 ``horizon=7`` 调用）；显式给出时覆盖 max_horizon。
    """
    if horizon is not None:
        max_horizon = horizon
    closes = [float(c) for c in (closes or [])]
    n = len(closes)
    full = compute_path_signals(closes, max_horizon=max_horizon)
    if not full.get("ok"):
        return False, full.get("reason") or "信号不可计算"
    if cuts is None:
        f0 = min((v for v in (full.get("first_signal") or {}).values() if v is not None),
                 default=MIN_BARS - 1)
        k0 = max(f0, MIN_BARS - 1)
        k_mid = k0 + max(0, (n - 1 - k0)) // 2
        cuts = sorted({k0, k_mid, n - 1})
    cuts = list(cuts)
    keys = ("p_up", "p_base", "p_sim", "n_analog", "n_resolved")
    for k in cuts:
        if k < MIN_BARS - 1 or k >= n:
            return False, f"切点 {k} 越界（需 {MIN_BARS - 1} ≤ k < {n}）"
        trunc = compute_path_signals(closes[:k + 1], max_horizon=max_horizon)
        for h in full.get("horizons") or ():
            a = (full["signals_by_h"].get(h) or [None] * n)[k]
            b = ((trunc["signals_by_h"].get(h) or [None] * (k + 1))[k]
                 if trunc.get("ok") else None)
            if a is None and b is None:
                continue
            if a is None or b is None:
                return False, f"切点 {k} 视界 {h} 信号存在性不一致（截断改变了输出）"
            for key in keys:
                if a.get(key) != b.get(key):
                    return False, f"切点 {k} 视界 {h} 的 {key} 被未来数据改变了"
    return True, (f"{len(cuts)} 个切点 × {len(full.get('horizons') or ())} 个视界逐位一致")


# ============================================================
# 滚动样本外回测（walk-forward 体检：每步只用 ≤t 的输入打分）
# ============================================================
def _backtest(closes, signals, horizon=HORIZON):
    n = len(closes)
    probs, outs = [], []
    for t, sig in enumerate(signals):
        if not sig or t + horizon >= n:
            continue
        y = 1.0 if closes[t + horizon] > closes[t] else 0.0
        probs.append(sig["p_up"])
        outs.append(y)
    n_bt = len(probs)
    up_rate = (sum(outs) / n_bt) if n_bt else None
    base_hit = max(up_rate, 1.0 - up_rate) if n_bt else None
    result = {"n": n_bt, "hit_rate": None, "base_rate": base_hit,
              "brier": None, "up_rate": up_rate}
    if n_bt < 10:
        # 与 k-macao/03 结算口径一致：样本不足只报样本量，不下命中率结论。
        result["note"] = f"样本不足 10 期（{n_bt} 期），只报样本量"
        return result
    hits = sum(1 for p, y in zip(probs, outs) if (p >= 0.5) == (y >= 0.5))
    brier = sum((p - y) ** 2 for p, y in zip(probs, outs)) / n_bt
    result.update({"hit_rate": hits / n_bt, "brier": brier})
    return result


# ============================================================
# 逐日表格（未来 7 个交易日）：预测 / 预期区间 / 理由 / 分析 / AI 操作建议
# ------------------------------------------------------------
# 全部为确定性规则合成（不调大模型、无随机数）：
#   · 预测数字 = 上面那一次因果扫描的信号（h=1..7），表格与整段结论共用同一批数字；
#   · 预期区间 = 锚定收盘 × (1 ± z·σ20·√k)，σ20 是 20 日实测日波动、z=1.2816（80% 中心区间）
#     —— 统计口径如实标注，不假装知道未来点位；
#   · 理由 = 当次特征数字（5/10/20 日动量、波动、距 20 日高点）+ 基准率 / 相似样本合成过程；
#   · 分析 = 累计口径与当日环比口径的关系 + |z| 最大的驱动因子（模板化，不写死叙事）；
#   · AI 操作建议 = 概率档位 → 操作倾向与仓位区间，波动分位 → 仓位收缩，σ20·√k → 止损幅度，
#     区间上沿（与历史 7 日 95% 分位取更保守者）→ 止盈参考；窗口内 ★★★ 日程 → 事件日提醒。
# 每一行都跟着「规则合成参考，非投资建议」的口径披露（渲染侧统一挂在栏目末尾）。
# ============================================================
WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
ANN = math.sqrt(TRADING_DAYS)      # 日波动 → 年化波动的系数（252 个交易日）
MAX_POSITION = 0.60                # 仓位建议硬上限：统计模型不给满仓信号
NEUTRAL_POSITION = 0.20            # 中性档的底仓上限（观察仓）

# 操作倾向档位（按累计上涨概率；0.58 / 0.42 与展示方向阈值 DIR_UP / DIR_DOWN 同源）
# 第三项 = 该档的仓位上限（None 表示用中性底仓 NEUTRAL_POSITION）
STANCE_TIERS = (
    (0.65, "积极看涨 · 顺势做多", 0.60),
    (0.58, "偏多 · 逢低布局", 0.45),
    (0.52, "谨慎偏多 · 轻仓试多", 0.30),
    (0.48, "中性 · 观望为主", None),
    (0.42, "谨慎偏空 · 减仓防守", 0.20),
    (0.35, "偏空 · 以避险为主", 0.10),
    (0.00, "强烈看跌 · 空仓避险", 0.00),
)

# 因子键 → 人话名（分析与理由两行共用，避免同一个因子在两处叫两个名字）
_FACTOR_CN = {"ret5": "5日动量", "ret10": "10日动量", "ret20": "20日动量",
              "vol20": "20日波动", "dd20": "距20日高点"}


def _var_horizon(closes, horizon=PATH_MAX, min_samples=60):
    """历史 horizon 交易日收益分布的 5%/50%/95% 分位（重叠窗口，仅用于展示区间）。

    样本 <min_samples 时返回 None（不给分位，绝不编造）；与 hk_seven_day._var7 同口径，
    这里自带一份是为了让 run_weekly 离线自足（不反向依赖大模型栏目）。
    """
    rets = []
    for i in range(len(closes) - int(horizon)):
        base = closes[i]
        if base > 0:
            rets.append(closes[i + int(horizon)] / base - 1.0)
    if len(rets) < int(min_samples):
        return None
    rets.sort()

    def _q(pr):
        pos = (len(rets) - 1) * pr
        lo = int(math.floor(pos))
        hi = min(lo + 1, len(rets) - 1)
        return rets[lo] + (rets[hi] - rets[lo]) * (pos - lo)

    return {"q05": _q(0.05), "q50": _q(0.50), "q95": _q(0.95), "n": len(rets)}


def trading_days_after(base_date, n=PATH_MAX):
    """锚定日之后的 n 个交易日（跳过周六周日；假期顺延由交易日计数自然处理）。"""
    from hk_seven_day import next_trading_days   # 同仓同口径，不另写一套日历
    out = []
    for k in range(1, int(n) + 1):
        d = next_trading_days(base_date, k)
        if not d:
            break
        out.append(d)
    return out


def _weekday_cn(date_str):
    try:
        return WEEKDAY_CN[datetime.strptime(str(date_str)[:10], "%Y-%m-%d").weekday()]
    except (TypeError, ValueError):
        return ""


# 各因子的「典型幅度」尺度：把不同量纲的因子换算成同一把尺子（相当于几个典型波动），
# 才能排出「当期最主要的驱动」。尺度是策略常量（写死可复现），不是行情数据。
FACTOR_SCALES = {
    "ret5": 0.025,     # 5 日动量 ±2.5% 记 1 个单位
    "ret10": 0.035,    # 10 日动量 ±3.5%
    "ret20": 0.050,    # 20 日动量 ±5.0%
    "dd20": 0.060,     # 距 20 日高点 −6.0%
    "vol20": 0.120,    # 年化波动相对 22% 中枢偏离 12 个百分点
}
VOL_ANNUAL_CENTER = 0.22


def _rank_drivers(features, vol_ann):
    """按「典型幅度倍数」排出当期最主要的驱动因子（只用 ≤t 数据算出的特征，可解释）。"""
    ranked = []
    for key in ("ret5", "ret10", "ret20", "dd20"):
        v = (features or {}).get(key)
        scale = FACTOR_SCALES.get(key) or 0.0
        if v is None or scale <= 0:
            continue
        ranked.append((abs(float(v)) / scale, key, float(v)))
    if vol_ann is not None:
        scale = FACTOR_SCALES["vol20"]
        ranked.append((abs(vol_ann - VOL_ANNUAL_CENTER) / scale, "vol20", vol_ann))
    ranked.sort(key=lambda r: (-r[0], r[1]))
    return ranked


def build_advice(p_cum, *, base_close, vol20, k, vol_pct=None,
                 band_hi=None, band_lo=None, q95=None, events=None, day_events=None):
    """规则合成的「AI 操作建议」：操作倾向 + 仓位区间 + 止损 + 止盈参考 + 提醒。

    · 概率只决定档位与仓位比例，绝不给出「一定涨 / 满仓」这类绝对化结论；
    · 仓位 = 概率偏离 50% 的幅度线性放大到上限 60%，再被档位上限压住；
      波动分位 ≥70% 时再乘 0.8（高波动自动降杠杆），分位缺失就不调整；
    · 止损幅度 = 2.0 × σ20 × √k，夹在 1%~8%（统计口径，不是拍脑袋的固定 3%）；
      看涨 / 中性档止损挂在锚定收盘下方，看跌档挂在上方（减仓 / 对冲的止损点）；
    · 止盈参考 = 80% 区间上沿，若给了历史 7 日 95% 分位则取更保守（更低）的那个；
    · 事件提醒优先点名「当天」的 ★★★ 日程，其次才是持有窗口内的第一项。
    """
    p = _clamp(p_cum)
    stance, cap = "中性 · 观望为主", NEUTRAL_POSITION
    for threshold, label, position_cap in STANCE_TIERS:
        if p >= threshold:
            stance, cap = label, (NEUTRAL_POSITION if position_cap is None else position_cap)
            break
    # 倾向与档位同源（不用 DIR_UP / DIR_DOWN 另判一次，避免「谨慎偏多」配「底仓不动」）
    tone = ("看涨" if p >= 0.52 else ("看跌" if p <= 0.48 else "中性"))

    dist = abs(p - 0.5)
    base_pos = min(MAX_POSITION, 2.0 * dist / 0.35 * MAX_POSITION)
    position = min(cap, base_pos)
    if vol_pct is not None and vol_pct >= 0.7:
        position *= 0.8
    position = int(round(min(MAX_POSITION, position) * 20) * 5)      # 取整到 5%
    if position <= 0 and tone != "看跌":
        position = 5          # 非看跌档给个观察仓下限，避免「仓位 ≤0%」这种自相矛盾的写法

    sigma = float(vol20) if vol20 else None
    stop_pct = None
    if sigma:
        stop_pct = round(min(0.08, max(0.01, 2.0 * sigma * math.sqrt(max(1, int(k))))), 3)
    stop_price = None
    if stop_pct is not None and base_close:
        stop_price = (base_close * (1 + stop_pct) if tone == "看跌"
                      else base_close * (1 - stop_pct))
    take_profit = None
    if band_hi:
        take_profit = float(band_hi)
        if q95 is not None and base_close:
            take_profit = min(take_profit, base_close * (1.0 + float(q95)))

    if tone == "看涨":
        entry = (f'分批建仓区 {band_lo:,.0f}–{base_close:,.0f}，不追高'
                 if (base_close and band_lo) else "分批建仓，不追高")
    elif tone == "看跌":
        entry = (f'逢反弹至 {band_hi:,.0f} 一带减仓 / 对冲，不逆势加仓'
                 if band_hi else "以减仓、对冲为主，不逆势加仓")
    else:
        entry = (f'底仓不动，等累计概率走出 {DIR_UP * 100:.0f}% / {DIR_DOWN * 100:.0f}% '
                 f'区间再动手')

    notes = [f'T+{int(k)} 持有口径 · 仓位建议 ≤{position}%']
    if vol_pct is not None:
        if vol_pct >= 0.7:
            notes.append(f'波动分位 {vol_pct * 100:.0f}%（偏高）→ 仓位已再压 20%，止损放宽执行')
        elif vol_pct <= 0.3:
            notes.append(f'波动分位 {vol_pct * 100:.0f}%（偏低）→ 低波动环境，止损从紧')
    day_hits = [e for e in (day_events or []) if int(e.get("imp") or 0) >= 3]
    win_hits = [e for e in (events or []) if int(e.get("imp") or 0) >= 3]
    if day_hits:
        first = day_hits[0]
        notes.append(f'当天有 ★★★ {str(first.get("name") or "")[:16]}'
                     f'（{first.get("date")}）→ 事件日波动可能放大，建议减半执行或等数据落地')
    elif win_hits:
        first = win_hits[0]
        notes.append(f'持有窗口内 {first.get("date")} 有 ★★★ {str(first.get("name") or "")[:16]}'
                     f'（共 {len(win_hits)} 项）→ 事件日波动可能放大，建议减半执行')
    notes.append("规则合成参考，非投资建议")
    return {
        "stance": stance, "tone": tone, "position": position, "entry_hint": entry,
        "stop_pct": stop_pct, "stop_price": stop_price, "take_profit": take_profit,
        "notes": notes,
    }


def _day_reason(sig, features, vol_ann, vol_pct, horizon):
    """理由行：把概率怎么来的摊开写（因子数字 + 基准率 / 相似样本合成过程）。"""
    bits = []
    mom = "、".join(
        f'{label} {(features or {}).get(key) * 100:+.1f}%'
        for key, label in (("ret5", "5日"), ("ret10", "10日"), ("ret20", "20日"))
        if (features or {}).get(key) is not None)
    if mom:
        bits.append(f'动量 {mom}')
    if vol_ann is not None:
        vol_txt = f'20日波动年化 {vol_ann * 100:.1f}%'
        if vol_pct is not None:
            vol_txt += f'（扩张分位 {vol_pct * 100:.0f}%）'
        bits.append(vol_txt)
    dd = (features or {}).get("dd20")
    if dd is not None:
        bits.append(f'距20日高点 {dd * 100:+.1f}%')
    n_res = int(sig.get("n_resolved") or 0)
    p_base = sig.get("p_base")
    if p_base is not None:
        bits.append(f'已结算 {n_res} 个 {horizon} 日样本基准率 {p_base * 100:.0f}%')
    n_analog = int(sig.get("n_analog") or 0)
    if sig.get("blended") and sig.get("p_sim") is not None:
        bits.append(f'最像的 {n_analog} 个历史片段里 {sig["p_sim"] * 100:.0f}% 上涨')
    else:
        bits.append(f'相似样本不足 {MIN_ANALOGS} 个（当前 {n_analog} 个）→ 只用基准率')
    bits.append(f'50/50 合成 {sig.get("p_up") * 100:.0f}%（夹 5%~95%）'
                if sig.get("blended") else
                f'取基准率 {sig.get("p_up") * 100:.0f}%（夹 5%~95%）')
    return " · ".join(bits)


def _day_analysis(k, p_cum, p_dod, top_driver, features):
    """分析行：一句人话解读（累计口径 vs 当日环比口径 + 最主要的驱动因子）。"""
    cum_txt = (f'第 {k} 个交易日累计上涨概率 {p_cum * 100:.0f}%'
               if k > 1 else f'当日上涨概率 {p_cum * 100:.0f}%')
    if k == 1:
        dod_txt = "（首日累计口径与当日环比口径为同一个数字）"
    elif p_dod is None:
        dod_txt = ""
    elif p_dod >= 0.55:
        dod_txt = f'，当日环比也偏涨（{p_dod * 100:.0f}%）→ 节奏顺势'
    elif p_dod <= 0.45:
        dod_txt = f'，但当日环比偏跌（{p_dod * 100:.0f}%）→ 路径上先回踩再修复'
    else:
        dod_txt = f'，当日环比 {p_dod * 100:.0f}%（{_lean_word(p_dod)}）→ 以震荡看待'
    drv = ""
    if top_driver:
        name = _FACTOR_CN.get(top_driver[1], top_driver[1])
        value = top_driver[2]
        if top_driver[1] == "vol20":
            drv = f'当期最主要驱动是{name}（年化 {value * 100:.1f}%）'
        elif top_driver[1] == "dd20":
            drv = f'当期最主要驱动是{name}（{value * 100:+.1f}%）'
        else:
            drv = f'当期最主要驱动是{name}（{value * 100:+.1f}%）'
        if top_driver[1] != "ret20" and (features or {}).get("ret20") is not None:
            drv += f'，20日动量 {features["ret20"] * 100:+.1f}%'
    return cum_txt + dod_txt + ("；" + drv if drv else "") + "。"


def build_daily_path(closes, dates, path, *, vol_pct=None, base_date=None,
                     symbol=None, events=None, var7=None):
    """把 7 个视界的因果信号摊成逐日表格行（纯函数：不联网、不写盘、可离线单测）。

    返回 {"available", "reason", "base_date", "base_close", "symbol", "symbol_label",
          "horizon", "rows", "band_z", "method"}；任一视界缺信号就如实降级（available=False）。
    """
    horizon = int(path.get("horizon") or PATH_MAX)
    signals_by_h = path.get("signals_by_h") or {}
    if not closes or len(closes) < MIN_BARS:
        return {"available": False, "reason": f"日线样本不足（{len(closes or [])} < {MIN_BARS} 根）",
                "rows": []}
    base_close = float(closes[-1])
    base_date = str(base_date or dates[-1] or "")
    target_dates = trading_days_after(base_date, horizon)
    if len(target_dates) < horizon:
        return {"available": False, "reason": "交易日历推算不足 7 个交易日", "rows": []}
    vol_hist = path.get("vol_hist") or []
    if vol_pct is None and len(vol_hist) >= 2:
        past, cur = vol_hist[:-1], vol_hist[-1]
        vol_pct = sum(1 for v in past if v <= cur) / len(past)
    q95 = (var7 or {}).get("q95")
    rows, missing = [], []
    for k in range(1, horizon + 1):
        sig = (signals_by_h.get(k) or [None])[-1]
        if not sig:
            missing.append(k)
            continue
        features = dict(sig.get("features") or {})
        sigma = float(features.get("vol20") or 0.0)
        vol_ann = sigma * ANN if sigma else None
        p_cum = _clamp(sig.get("p_up"))
        direction, label = _day_label(p_cum, k)
        span = BAND_Z * sigma * math.sqrt(k) if sigma else None
        band_lo = base_close * (1 - span) if span else None
        band_hi = base_close * (1 + span) if span else None
        prev = (signals_by_h.get(k - 1) or [None])[-1] if k > 1 else None
        p_dod = _clamp(prev.get("p_up")) if prev else None
        ranked = _rank_drivers(features, vol_ann)
        # 事件提醒只看「持有到第 k 天」这段窗口里的 ★★★ 日程（窗口外的不拿来吓人）
        window_events = [e for e in (events or [])
                         if base_date <= str(e.get("date") or "")[:10] <= target_dates[k - 1]]
        day_events = [e for e in (events or [])
                      if str(e.get("date") or "")[:10] == target_dates[k - 1]]
        advice = build_advice(p_cum, base_close=base_close,
                              vol20=sigma, k=k, vol_pct=vol_pct,
                              band_hi=band_hi, band_lo=band_lo, q95=q95,
                              events=window_events, day_events=day_events)
        rows.append({
            "k": k, "date": target_dates[k - 1],
            "weekday": _weekday_cn(target_dates[k - 1]),
            "target_sessions": k,
            "p_up": p_cum, "direction": direction, "label": label,
            "p_day": p_dod,
            "p_base": sig.get("p_base"), "p_sim": sig.get("p_sim"),
            "n_analog": sig.get("n_analog"), "n_resolved": sig.get("n_resolved"),
            "blended": bool(sig.get("blended")),
            "features": features,
            "sigma_daily": sigma or None, "vol_annual": vol_ann,
            "band_lo": band_lo, "band_hi": band_hi, "band_z": BAND_Z,
            "reason": _day_reason(sig, features, vol_ann, vol_pct, k),
            "analysis": _day_analysis(k, p_cum, p_dod, ranked[0] if ranked else None, features),
            "advice": advice,
            "events": [e for e in day_events if int(e.get("imp") or 0) >= 2],
        })
    if missing:
        return {"available": False,
                "reason": f"视界 {'、'.join(str(m) for m in missing)} 的已结算样本不足"
                          f"（<{MIN_RESOLVED} 个），不产出逐日预测",
                "rows": []}
    return {
        "available": True, "reason": "",
        "base_date": base_date, "base_close": base_close,
        "symbol": symbol or "", "symbol_label": _SYMBOL_LABELS.get(symbol or "", symbol or ""),
        "horizon": horizon, "rows": rows, "band_z": BAND_Z,
        "vol_pct": vol_pct, "var_n": (var7 or {}).get("n"),
        "method": (f'视界 1~{horizon} 各自独立记账的因果信号（基准率 + 相似样本，'
                   f's+h≤t 已结算锚点）· 区间为 80% 中心区间（z={BAND_Z}，σ 取 20 日实测波动）'),
    }


# ============================================================
# 预测留痕：先存档（settled=False）→ 满 target_sessions 个交易日按真实收盘结算
# （新档 = 7 个交易日；2026-09-29 之前签发的旧档仍按其签发时的 5 个交易日结算，历史不篡改）
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
        pass  # 留痕写不进去不影响本次预测展示；下次运行再写


def _entry_horizon(entry):
    """这条预测签发时的视界（交易日数）。

    2026-09-29 起新档写 target_sessions=7；此前签发的旧档只有 5 日口径，
    没有该字段时按 LEGACY_HORIZON 结算——**历史不篡改**，旧预测仍按旧口径对账。
    """
    try:
        h = int(entry.get("target_sessions") or LEGACY_HORIZON)
    except (TypeError, ValueError):
        return LEGACY_HORIZON
    return h if h > 0 else LEGACY_HORIZON


def _settle(entries, dates, closes, now=None):
    """结算所有已到龄的预测；返回今日是否有结算事件。

    目标日严格在后（约束②）：结算点 = base + 该条预测签发时的视界（target_sessions）
    个**交易日**，数据里没有这根 K 线就绝不结算——假期顺延由交易日计数自然处理。
    """
    now = now or datetime.now(CST)
    index = {d: i for i, d in enumerate(dates)}
    settled_today = False
    today = now.strftime("%Y-%m-%d")
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("settled"):
            continue
        b = index.get(entry.get("base_date"))
        if b is None:
            continue
        j = b + _entry_horizon(entry)
        if j >= len(closes) or closes[b] <= 0:
            continue
        actual = closes[j] / closes[b] - 1.0
        entry["settled"] = True
        entry["settle_date"] = dates[j]
        entry["actual_ret"] = actual
        entry["actual_dir"] = "up" if actual > 0 else ("down" if actual < 0 else "flat")
        # 底牌方向 = 发布时存档的 P ≥ 0.5；展示可以写中性，结算认底牌。
        entry["hit"] = bool((entry.get("p_up") or 0.5) >= 0.5) == (actual > 0)
        if dates[j] == today:
            settled_today = True
    return settled_today


def _issue(sig, dates, closes, now, symbol):
    """按最新一根 K 线签发新预测（结构上只可能发生在结算完成之后）。"""
    i = len(dates) - 1
    f = dict(sig["features"])
    direction, label = _horizon_label(sig["p_up"], HORIZON)
    return {
        "base_date": dates[i],
        "base_close": closes[i],
        "symbol": symbol,
        "symbol_label": _SYMBOL_LABELS.get(symbol, symbol),
        "target_sessions": HORIZON,
        "target_note": (f"锚定日后第 {HORIZON} 个交易日收盘"
                        f"（按交易日计数，假期顺延）"),
        "p_up": sig["p_up"],
        "direction": direction,
        "label": label,
        "p_base": sig["p_base"],
        "p_sim": sig["p_sim"],
        "n_analog": sig["n_analog"],
        "n_resolved": sig["n_resolved"],
        "blended": sig["blended"],
        "factors": {k: f.get(k) for k in FEATURE_KEYS},
        "issued_cst": now.strftime("%Y-%m-%d %H:%M:%S%z"),
        "settled": False,
    }


# ============================================================
# 对外入口
# ============================================================
def run_weekly(fetch_json=None, *, history_path=None, symbol=None, rng="2y", now=None,
               events=None, var7=None):
    """计算 + 逐日表格 + 留痕 + 结算；返回供管线消费的结果字典。

    events: 未来窗口内的财经日程（[{"date", "name", "imp"}]），只用于「事件日提醒」，
            绝不参与概率计算（日程本身不含方向信息）。
    var7:   历史 7 交易日收益分位（{"q05","q50","q95","n"}），用于止盈参考取更保守值。

    可用时：{"available": True, "entry", "daily", "backtest", "journal", "as_of",
             "symbol", "symbol_label", "self_check", "is_today", "vol_pct"}
    不可用：{"available": False, "reason": "..."} —— 由上层整栏缺席。
    """
    from octopus_quant.providers import fetch_bars  # 惰性导入：唯一复用的联网数据层

    symbol = symbol or os.environ.get("OCTOPUS_WEEKLY_SYMBOL", "^HSI")
    now = now or datetime.now(CST)
    today = now.strftime("%Y-%m-%d")

    bars = fetch_bars(fetch_json, symbol, rng=rng) if fetch_json else []
    if len(bars) < MIN_BARS:
        return {"available": False,
                "reason": f"日线样本不足（{len(bars)} < {MIN_BARS} 根）"}

    dates = [b["date"] for b in bars]
    closes = [float(b["close"]) for b in bars]

    # 1) 信号：一次因果扫描算出视界 1..7（逐日表格与整段结论共用同一批数字）
    path = compute_path_signals(closes, max_horizon=PATH_MAX)
    if not path.get("ok"):
        return {"available": False, "reason": path.get("reason") or "信号不可计算"}
    signals = path["signals_by_h"].get(PATH_MAX) or []
    last = signals[-1] if signals else None
    if not last:
        return {"available": False,
                "reason": f"最新一根 K 线尚无足够已结算 {PATH_MAX} 日样本"}

    # 2) 未来函数自检（截断不变性 · 覆盖全部 7 个视界）：不过则整栏降级，绝不出预测
    ok, check_msg = check_no_lookahead(closes)
    if not ok:
        return {"available": False, "reason": f"未来函数自检未通过：{check_msg}"}

    # 2b) 逐日表格（纯函数；缺任一视界就整栏降级，绝不用别的数据凑行）
    vol_hist = path.get("vol_hist") or []
    vol_pct_path = None
    if len(vol_hist) >= 2:
        past, cur = vol_hist[:-1], vol_hist[-1]
        vol_pct_path = sum(1 for v in past if v <= cur) / len(past)
    if var7 is None:
        var7 = _var_horizon(closes, PATH_MAX)
    daily = build_daily_path(closes, dates, dict(path, horizon=PATH_MAX),
                             vol_pct=vol_pct_path, base_date=dates[-1],
                             symbol=symbol, events=events, var7=var7)
    if not daily.get("available"):
        return {"available": False,
                "reason": daily.get("reason") or "逐日预测不可计算"}

    # 3) 滚动样本外体检（整段 7 日口径）
    backtest = _backtest(closes, signals, horizon=PATH_MAX)

    # 4) 留痕：先结算历史，再（无未决预测时）签发新预测
    journal = _load_journal(history_path)
    entries = journal.setdefault("entries", [])
    settled_today = _settle(entries, dates, closes, now=now)
    standing = next((e for e in reversed(entries)
                     if isinstance(e, dict) and not e.get("settled")), None)
    changed = settled_today
    if standing is None:
        standing = _issue(last, dates, closes, now, symbol)
        entries.append(standing)
        changed = True
    if changed:
        journal["updated_cst"] = now.strftime("%Y-%m-%d %H:%M:%S%z")
        _save_journal(history_path, journal)

    # 5) 留痕统计（样本 <10 只报样本量）
    settled = [e for e in entries
               if isinstance(e, dict) and e.get("settled")]
    n_settled = len(settled)
    hits = sum(1 for e in settled if e.get("hit"))
    recent = [{"date": e.get("settle_date"),
               "ret": e.get("actual_ret"),
               "hit": bool(e.get("hit"))}
              for e in settled[-3:]]
    # 混合视界的样本不合成一个命中率：旧档（5 个交易日）与新档（7 个交易日）分开记账，
    # 任何一组样本 <10 都只报样本量，绝不下命中率结论。
    by_horizon = {}
    for e in settled:
        h = _entry_horizon(e)
        slot = by_horizon.setdefault(h, {"n": 0, "hits": 0})
        slot["n"] += 1
        slot["hits"] += 1 if e.get("hit") else 0
    journal_stats = {
        "n": n_settled,
        "hit_rate": (hits / n_settled) if n_settled >= 10 else None,
        "hits": hits,
        "recent": recent,
        "by_horizon": {h: dict(v, hit_rate=(v["hits"] / v["n"]) if v["n"] >= 10 else None)
                       for h, v in sorted(by_horizon.items())},
    }

    # 6) 展示用扩张分位（vol20 相对自身过去分位，只用 ≤ 最新一根的数据）
    #    与逐日表格用的是同一条因果序列（vol_pct_path），不另算一套。
    vol_pct = vol_pct_path

    # is_today：今天有签发或结算事件（预测本身的锚定日可能是最近收盘日）
    is_today = (standing.get("base_date") == today) or any(
        e.get("settle_date") == today for e in settled)

    return {
        "available": True,
        "entry": standing,
        "daily": daily,
        "backtest": backtest,
        "journal": journal_stats,
        "as_of": dates[-1],
        "symbol": symbol,
        "symbol_label": _SYMBOL_LABELS.get(symbol, symbol),
        "self_check": check_msg,
        "vol_pct": vol_pct,
        "is_today": bool(is_today),
        "horizon": PATH_MAX,
        "method": (f"扩张基准率 + 20日特征最近邻（s+{PATH_MAX}≤t 已结算锚点）混合 · "
                   f"逐日表格 {PATH_MAX} 行同一次因果扫描"),
    }
