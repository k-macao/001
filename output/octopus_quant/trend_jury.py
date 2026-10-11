#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 趋势分析模块 —— UZI-Skill（游资 Skills）方法移植：方法评委团 × 量化规则 × 证据闸门。

上游：<https://github.com/wbh604/UZI-Skill>（MIT · v3.9.4）
本地镜像与移植对照：tools/uzi-skill/VENDORED.md · UZISkill-安装与趋势分析栏目.md

移植了上游的哪几件「方法」，而不是它的行情口径
--------------------------------------------------------
① **规则引擎裁决**（lib/investor_criteria.py + investor_evaluator.py）
   每位评委一组带权重的量化规则（weight 1–5），得分 = 权重通过率 ×100；
   ≥65 看多 / <35 看空 / 其间中性（沿用上游阈值）；置信度按参与规则数与
   「维度覆盖率」折算。每条命中 / 未达都要写出带数字的理由（pass_msg / fail_msg）。
② **数据不足即 skip，不判负**（上游 _safe_check 返回 None → 该规则不占分母）
   —— 缺字段绝不能当「不达标」，否则会把「没数据」渲染成「看空」。
③ **流派（school）分组与 SCHOOL LOCK**（上游 --school A..I + banner）
   本栏把 6 个流派做成 6 组方法评委，`OCTOPUS_TREND_SCHOOL=A..F` 锁定单一流派视角，
   其余评委记 skip 并在栏目顶部出 banner，避免被误读成「全体评委结论」。
④ **数据完整性闸门**（lib/data_integrity.py 的 CRITICAL_CHECKS）
   关键维度缺失 → 该标的不打分并写明原因；整栏覆盖率写进正文。
⑤ **矛盾必须呈现**（The Great Divide）：最强多头评委 vs 最强空头评委 + 一句带数字的
   punchline；分歧度用多空二元 Shannon 熵（与【麻辣大龙虾】栏同一口径）本身入正文。
⑥ **禁用空泛话术**（quality-checklist.md）：「基本面良好 / 值得关注 / 前景广阔 /
   建议重视 / 存在一定风险」出现即判失败，自检不过就换成带数字的句子并记 warning。
⑦ **趋势失效风险扫描**（skills/trap-detector 的 8 信号结构）：每格必须给出
   「命中 / 未命中 / 数据不足」三态之一，风险清单永不为空。
⑧ **可审计 methodology_log**：每一步计算写出推导链（全量模式随正文出，供复核）。

上游没搬过来的部分（明确说明，避免误传）
    · 22 维 fetcher 依赖 akshare / yfinance / baostock 与个股财报，本栏只需要
      「已收盘日线 + 市场级环境」，因此数据一律复用本仓库既有免费源
      （市场库 → 本次量化日线 → Yahoo / 东财主备链），不新增依赖、不联网取财报；
    · 66 位真人投资人 persona（role-play 需要大模型）——本栏是纯确定性流水线，
      所以把「人」换成「方法」：评委 = 公开可查证的技术分析框架（Trend Template、
      箱体、关键点、时间窗、量能确认、相对强度、风险纪律…），规则 = 该框架的原始判据。
      每位方法评委 ≥4 条规则（对齐上游「每人 ≥4 规则」的回归门槛）。

口径：确定性计算、可复现、不调大模型、不编数字；抓不到就标「暂缺」，
      缺维度就 skip，绝不把「没有数据」画成「看空」。**不构成投资建议**。
"""
from __future__ import annotations

import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from . import features as _feat_mod
from . import providers, stats

# ------------------------------------------------------------------
# 栏目常量（pipeline 只按这几个键接线，渲染不联网）
# ------------------------------------------------------------------
SECTION_KICKER = "TREND JURY"
SECTION_TITLE = "【深海剑鱼】趋势多维评审团"
SECTION_CAPTION = "方法评委团 · 量化规则 · 非投资建议"

# 参与评审的标的池：与【六眼飞鱼】MACD 栏同一大盘篮子（可用环境变量覆盖）。
DEFAULT_SPECS = [
    ("恒生指数", "^HSI"), ("恒生科技", "^HSTECH"), ("国企指数", "^HSCEI"),
    ("上证指数", "000001.SS"), ("深证成指", "399001.SZ"), ("创业板指", "399006.SZ"),
    ("道琼斯", "^DJI"), ("标普500", "^GSPC"), ("纳斯达克", "^IXIC"),
]
# 相对强度基准：同市场指数互为基准；跨市场比较不做（口径不同，宁缺不混）。
BENCHMARK_OF = {
    "^HSI": None, "^HSTECH": "^HSI", "^HSCEI": "^HSI",
    "000001.SS": None, "399001.SZ": "000001.SS", "399006.SZ": "000001.SS",
    "^DJI": None, "^GSPC": "^DJI", "^IXIC": "^GSPC",
}

MIN_BARS = 120                  # 少于 120 根已收盘日线不进评审（样本不足以谈趋势成立）
MAX_LAG_DAYS = 4                # 与交易类栏目一致：滞后超过 4 个自然日不发定调
BULLISH_THRESHOLD = 65          # 沿用上游 Signal thresholds
BEARISH_THRESHOLD = 35
MIN_JUDGE_COVERAGE = 0.60       # 评委可评权重 < 60% → 整位 skip（上游「数据不足即 skip」）
LABEL_BANDS = ((72, "强多头"), (58, "偏多"), (42, "中性"), (28, "偏空"), (0, "强空头"))

# 上游 quality-checklist 的禁用话术：出现即判定文案不合格，重写为带数字的句子。
BANNED_PHRASES = ("基本面良好", "值得关注", "前景广阔", "建议重视", "存在一定风险")

# ------------------------------------------------------------------
# 流派（移植上游 SCHOOL_LABELS）
# ------------------------------------------------------------------
SCHOOLS = {
    "A": ("趋势跟随", "利弗莫尔 关键点 / 达瓦斯 箱体 / 江恩 时间窗 / 海龟 通道"),
    "B": ("阶段与均线", "米内尔维尼 Trend Template / 200 日均线牛熊"),
    "C": ("强度与动量", "欧奈尔 相对强度 / MACD 趋势 / 多周期动量"),
    "D": ("量能确认", "量在价先 / VCP 波动收缩"),
    "E": ("市场环境", "涨跌家数 / 成交额 / 板块 / 社区与标题多空"),
    "F": ("风险纪律", "ATR 止损距离 / 回撤 / 假突破 / 数据新鲜度"),
}


def locked_school():
    """OCTOPUS_TREND_SCHOOL=A..F（移植上游 --school）；无效值按未锁定处理。"""
    raw = str(os.environ.get("OCTOPUS_TREND_SCHOOL", "")).strip().upper()
    return raw if raw in SCHOOLS else ""


# ------------------------------------------------------------------
# 18 维数据卡（上游 22 维在「已收盘日线 + 市场级环境」下的可行子集）
#   critical=True 的维度缺失 → 该标的不进评审（上游 data_integrity 口径）
# ------------------------------------------------------------------
DIMENSIONS = [
    {"key": "close",            "title": "最新收盘价",   "group": "价格", "critical": True},
    {"key": "ma50",             "title": "50 日均线",     "group": "均线", "critical": True},
    {"key": "ma150",            "title": "150 日均线",    "group": "均线", "critical": False},
    {"key": "ma200",            "title": "200 日均线",    "group": "均线", "critical": False},
    {"key": "ma200_up",         "title": "200 日均线走向", "group": "均线", "critical": False},
    {"key": "ma_align",         "title": "均线多空排列",  "group": "均线", "critical": True},
    {"key": "ret_20",           "title": "20 日动量",     "group": "动量", "critical": True},
    {"key": "ret_60",           "title": "60 日动量",     "group": "动量", "critical": False},
    {"key": "rs_bench",         "title": "相对基准超额",   "group": "强度", "critical": False},
    {"key": "rs_rank",          "title": "截面相对强度",   "group": "强度", "critical": False},
    {"key": "box_hi_20",        "title": "20 日箱体上沿",  "group": "箱体", "critical": True},
    {"key": "box_lo_20",        "title": "20 日箱体下沿",  "group": "箱体", "critical": False},
    {"key": "breakout_55",      "title": "55 日新高突破",  "group": "箱体", "critical": False},
    {"key": "vol_ratio",        "title": "量比（20 日）",  "group": "量能", "critical": False},
    {"key": "updn_vol_ratio",   "title": "涨日/跌日均量",  "group": "量能", "critical": False},
    {"key": "range_collapse",   "title": "波幅收缩比",     "group": "量能", "critical": False},
    {"key": "atr_pct",          "title": "ATR 占价比",     "group": "风险", "critical": False},
    {"key": "dd_from_high",     "title": "距区间高点回撤",  "group": "风险", "critical": False},
    {"key": "fib_gap",          "title": "时间窗偏离（日）", "group": "时间", "critical": False},
    {"key": "macd_hist",        "title": "MACD 柱",       "group": "动量", "critical": False},
    {"key": "trend_t",          "title": "趋势回归 t 值",   "group": "趋势", "critical": True},
    {"key": "trend_r2",         "title": "趋势拟合 R²",    "group": "趋势", "critical": False},
    {"key": "rsi14",            "title": "RSI(14)",       "group": "摆动", "critical": False},
    {"key": "dist_hi_252",      "title": "距 252 日高点",   "group": "位置", "critical": False},
    {"key": "dist_lo_252",      "title": "距 252 日低点",   "group": "位置", "critical": False},
    {"key": "breadth_up_n",     "title": "A股上涨家数",    "group": "环境", "critical": False},
    {"key": "breadth_down_n",   "title": "A股下跌家数",    "group": "环境", "critical": False},
    {"key": "turnover_chg_pct", "title": "成交额环比",     "group": "环境", "critical": False},
    {"key": "sector_net",       "title": "板块净强弱（涨跌幅和）", "group": "环境", "critical": False},
    {"key": "liquidity_score",  "title": "资金流动性分",    "group": "环境", "critical": False},
    {"key": "crowd_net",        "title": "社区多空净额",    "group": "环境", "critical": False},
    {"key": "headline_net",     "title": "标题多空净额",    "group": "环境", "critical": False},
]
DIM_TITLES = {d["key"]: d["title"] for d in DIMENSIONS}
CRITICAL_DIMS = tuple(d["key"] for d in DIMENSIONS if d.get("critical"))
# 环境维度是市场级、各标的共用（不是个股证据），正文要如实说明。
MARKET_LEVEL_DIMS = ("breadth_up_n", "breadth_down_n", "turnover_chg_pct", "sector_net",
                     "liquidity_score", "crowd_net", "headline_net")


# ------------------------------------------------------------------
# 规则引擎（移植上游 Rule dataclass + _safe_check + evaluate 三层结构）
# ------------------------------------------------------------------
@dataclass
class Rule:
    rule_id: str
    name: str                                  # 中文规则名（直接进正文）
    weight: int                                # 1–5，重要性
    check: Callable[[dict], bool]
    dims: tuple[str, ...] = ()                 # 依赖的数据维：任一缺失 → skip 该规则
    pass_msg: str = ""
    fail_msg: str = ""


@dataclass
class Judge:
    id: str
    name: str
    school: str
    origin: str
    rules: list = field(default_factory=list)


def _known(features: dict, *keys: str) -> bool:
    """所有引用的维度都必须是有意义的数值（None / 非有限 / NaN 都算缺数据）。"""
    for key in keys:
        value = features.get(key)
        if value is None:
            return False
        if isinstance(value, float) and not math.isfinite(value):
            return False
    return True


def _rule(rule: Rule, features: dict):
    """单条规则的三态裁决：True 命中 / False 未达 / None 数据不足（跳过，不占分母）。"""
    if rule.dims and not _known(features, *rule.dims):
        return None
    try:
        return bool(rule.check(features))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None          # 上游同款：比较遇到缺失值 → skip，不判负


def _fmt(template: str, features: dict) -> str:
    """按上游 _fmt_msg 的做法：缺键渲染成 '?'，不让整条消息炸掉。"""
    if not template:
        return ""

    class _Missing:
        def __format__(self, _spec):
            return "?"

        def __str__(self):
            return "?"

    class _Safe(dict):
        def __missing__(self, _key):
            return _Missing()

        def __getitem__(self, key):
            value = super().get(key, _Missing())
            return _Missing() if value is None else value

    try:
        return template.format_map(_Safe(features))
    except (KeyError, IndexError, ValueError, TypeError):
        return template


# ── A 组 · 趋势跟随 ──────────────────────────────────────────────
LIVERMORE_RULES = [
    Rule("pivot_break", "站上 20 日关键点（前 20 日高点）", 5,
         dims=("close", "box_hi_20"),
         check=lambda f: f["close"] > f["box_hi_20"],
         pass_msg="收盘 {close:.2f} 在关键点 {box_hi_20:.2f} 上方",
         fail_msg="收盘 {close:.2f} 未过关键点 {box_hi_20:.2f}"),
    Rule("line_of_least_resistance", "趋势方向与 20 日动量同向", 4,
         dims=("ret_20", "trend_t"),
         check=lambda f: (f["trend_t"] > 0) == (f["ret_20"] > 0) and abs(f["trend_t"]) >= 1.0,
         pass_msg="阻力最小方向向上：60 日回归 t={trend_t:+.2f} · 20 日 {ret_20:+.2f}%",
         fail_msg="t={trend_t:+.2f} 与 20 日 {ret_20:+.2f}% 打架，方向未明"),
    Rule("volume_on_break", "突破当日量能配合（量比 ≥ 1.2）", 4,
         dims=("vol_ratio", "box_hi_20", "close"),
         check=lambda f: f["close"] > f["box_hi_20"] and f["vol_ratio"] >= 1.2,
         pass_msg="量比 {vol_ratio:.2f}，突破有量",
         fail_msg="量比 {vol_ratio:.2f}，突破无量易反抽"),
    Rule("stop_clear", "止损位清晰且距离可控（≤ 3×ATR）", 4,
         dims=("close", "box_lo_20", "atr_pct"),
         check=lambda f: f["atr_pct"] and 0 < (f["close"] - f["box_lo_20"]) / f["close"] * 100 <= 3 * f["atr_pct"],
         pass_msg="箱体下沿 {box_lo_20:.2f} 止损距离 {stop_dist_pct:.2f}% ≤ 3×ATR({atr_pct:.2f}%)",
         fail_msg="距箱体下沿 {stop_dist_pct:.2f}%，超过 3×ATR({atr_pct:.2f}%) 的纪律位"),
]

DARVAS_RULES = [
    Rule("box_top_break", "箱体上沿被有效突破（收盘 > 20 日高 ×1.005）", 5,
         dims=("close", "box_hi_20"),
         check=lambda f: f["close"] > f["box_hi_20"] * 1.005,
         pass_msg="新箱顶打开：{close:.2f} > {box_hi_20:.2f}",
         fail_msg="仍在旧箱体内：{close:.2f} vs 上沿 {box_hi_20:.2f}"),
    Rule("box_position", "价格处在箱体上半区（位置 ≥ 60%）", 3,
         dims=("box_pos",),
         check=lambda f: f["box_pos"] >= 60,
         pass_msg="箱体位置 {box_pos:.0f}/100，靠上沿",
         fail_msg="箱体位置 {box_pos:.0f}/100，贴着下沿"),
    Rule("box_stop_below", "箱底未破（收盘 > 20 日低）", 4,
         dims=("close", "box_lo_20"),
         check=lambda f: f["close"] > f["box_lo_20"],
         pass_msg="箱底 {box_lo_20:.2f} 未破",
         fail_msg="收盘已跌破箱底 {box_lo_20:.2f}"),
    Rule("pyramid_add", "可加仓：55 日新高且量能未失控（量比 < 3）", 3,
         dims=("breakout_55", "vol_ratio"),
         check=lambda f: bool(f["breakout_55"]) and f["vol_ratio"] < 3.0,
         pass_msg="55 日新高 + 量比 {vol_ratio:.2f}，金字塔加仓位",
         fail_msg="55 日新高={breakout_55}、量比 {vol_ratio:.2f}，不满足加仓条件"),
]

GANN_RULES = [
    Rule("fib_window", "处在斐波那契时间窗口（距 21/34/55/89/144 日 ≤2 天）", 3,
         dims=("fib_gap",),
         check=lambda f: f["fib_gap"] <= 2,
         pass_msg="距最近时间窗 {fib_gap:.0f} 天（转折点附近）",
         fail_msg="距最近时间窗 {fib_gap:.0f} 天，不在线上"),
    Rule("days_since_low", "距上一低点 ≥ 21 个交易日（时间换空间已给足）", 3,
         dims=("days_from_lo",),
         check=lambda f: f["days_from_lo"] >= 21,
         pass_msg="低点已走出 {days_from_lo:.0f} 天",
         fail_msg="距低点仅 {days_from_lo:.0f} 天，转折尚未确认"),
    Rule("one_by_one", "1×1 角度线近似成立（日均涨速 ≥ 0.6×ATR）", 4,
         dims=("slope_per_bar", "atr_val"),
         check=lambda f: f["slope_per_bar"] >= 0.6 * f["atr_val"],
         pass_msg="日均涨速 {slope_per_bar:.3f} ≥ 0.6×ATR({atr_val:.3f})",
         fail_msg="日均涨速 {slope_per_bar:.3f} 弱于 0.6×ATR({atr_val:.3f})"),
    Rule("time_price_agree", "时间与价格同向（窗口内且价在 50 日线上）", 3,
         dims=("fib_gap", "close", "ma50"),
         check=lambda f: f["fib_gap"] <= 5 and f["close"] > f["ma50"],
         pass_msg="时间窗 {fib_gap:.0f} 天内且价在 50 日线上方",
         fail_msg="时价不一致（窗口偏离 {fib_gap:.0f} 天 / 价 {close:.2f} vs MA50 {ma50:.2f}）"),
]

TURTLE_RULES = [
    Rule("enter_20", "20 日通道突破（进场信号）", 4,
         dims=("close", "box_hi_20"),
         check=lambda f: f["close"] > f["box_hi_20"],
         pass_msg="20 日高点 {box_hi_20:.2f} 已破",
         fail_msg="未破 20 日高点 {box_hi_20:.2f}"),
    Rule("enter_55", "55 日通道突破（强趋势确认）", 4,
         dims=("breakout_55",),
         check=lambda f: bool(f["breakout_55"]),
         pass_msg="55 日高点同步突破，趋势级别上调",
         fail_msg="55 日高点未破，只是短周期反弹"),
    Rule("unit_risk", "风险单位可控（2N 止损 ≤ 6%）", 4,
         dims=("atr_pct",),
         check=lambda f: 0 < f["atr_pct"] <= 3.0,
         pass_msg="N={atr_pct:.2f}%，2N 止损 {stop_2n_pct:.2f}%",
         fail_msg="N={atr_pct:.2f}% 过大，2N 止损已到 {stop_2n_pct:.2f}%"),
    Rule("exit_10", "未触发 10 日出场信号（收盘 > 10 日低）", 3,
         dims=("close", "box_lo_10"),
         check=lambda f: f["close"] > f["box_lo_10"],
         pass_msg="10 日低点 {box_lo_10:.2f} 完好，可持有",
         fail_msg="已跌破 10 日低点 {box_lo_10:.2f}，按纪律减仓"),
]

# ── B 组 · 阶段与均线 ────────────────────────────────────────────
MINERVINI_RULES = [
    Rule("tt_above_150_200", "价 > 150 日线 > 200 日线", 5,
         dims=("close", "ma150", "ma200"),
         check=lambda f: f["close"] > f["ma150"] > f["ma200"],
         pass_msg="{close:.2f} > MA150 {ma150:.2f} > MA200 {ma200:.2f}",
         fail_msg="均线长端次序未到 Stage 2（{close:.2f} / MA150 {ma150:.2f} / MA200 {ma200:.2f}）"),
    Rule("tt_ma200_rising", "200 日线至少上行 1 个月", 4,
         dims=("ma200_up",),
         check=lambda f: bool(f["ma200_up"]),
         pass_msg="MA200 21 日变化 {ma200_chg_pct:+.2f}%，年线向上",
         fail_msg="MA200 21 日变化 {ma200_chg_pct:+.2f}%，年线未走多"),
    Rule("tt_50_above", "50 日线 > 150 日线 > 200 日线", 4,
         dims=("ma50", "ma150", "ma200"),
         check=lambda f: f["ma50"] > f["ma150"] > f["ma200"],
         pass_msg="MA50 {ma50:.2f} > MA150 > MA200，多头排列",
         fail_msg="MA50 {ma50:.2f} 未压住长端均线"),
    Rule("tt_above_50", "价格在 50 日线上", 3,
         dims=("close", "ma50"),
         check=lambda f: f["close"] > f["ma50"],
         pass_msg="价 {close:.2f} > MA50 {ma50:.2f}",
         fail_msg="价 {close:.2f} 已失守 MA50 {ma50:.2f}"),
    Rule("tt_off_low", "距 252 日低点 ≥ 30%", 4,
         dims=("dist_lo_252",),
         check=lambda f: f["dist_lo_252"] >= 30,
         pass_msg="高于 252 日低点 {dist_lo_252:+.1f}%",
         fail_msg="仅高于 252 日低点 {dist_lo_252:+.1f}%（门槛 30%）"),
    Rule("tt_near_high", "距 252 日高点 ≤ 25%", 4,
         dims=("dist_hi_252",),
         check=lambda f: abs(f["dist_hi_252"]) <= 25,
         pass_msg="距高点 {dist_hi_252:+.1f}%，仍在强势区",
         fail_msg="距高点 {dist_hi_252:+.1f}%，回撤过深"),
    Rule("vcp_contract", "波动收缩（VCP：20 日波幅 / 60 日波幅 ≤ 0.6）", 4,
         dims=("range_collapse",),
         check=lambda f: 0 <= f["range_collapse"] <= 0.6,
         pass_msg="波幅收缩比 {range_collapse:.2f}，蓄势形态",
         fail_msg="波幅收缩比 {range_collapse:.2f}，尚未收缩"),
]

STAGE_RULES = [
    Rule("ma_align_bull", "均线多头排列（MA5>MA20>MA60 全中）", 5,
         dims=("ma_align",),
         check=lambda f: f["ma_align"] >= 3,
         pass_msg="均线排列 {ma_align:+d}/3 全多头",
         fail_msg="均线排列 {ma_align:+d}/3，排列未理顺"),
    Rule("above_200", "站上 200 日线（牛熊分界）", 4,
         dims=("close", "ma200"),
         check=lambda f: f["close"] > f["ma200"],
         pass_msg="价 {close:.2f} 在年线上方 {above_ma200_pct:+.2f}%",
         fail_msg="价 {close:.2f} 在年线下方 {above_ma200_pct:+.2f}%"),
    Rule("stage_two_signs", "Stage 2 特征：动量与趋势同向为正", 4,
         dims=("ret_60", "trend_t", "ma_align"),
         check=lambda f: f["ret_60"] > 0 and f["trend_t"] > 0 and f["ma_align"] >= 1,
         pass_msg="60 日 {ret_60:+.2f}% · t={trend_t:+.2f} · 排列 {ma_align:+d} → Stage 2",
         fail_msg="Stage 2 未成立（60 日 {ret_60:+.2f}% / t={trend_t:+.2f} / 排列 {ma_align:+d}）"),
    Rule("no_stage_four", "未处 Stage 4（距高点回撤 > −25%）", 3,
         dims=("dd_from_high",),
         check=lambda f: f["dd_from_high"] > -25,
         pass_msg="回撤 {dd_from_high:+.1f}%，未进 Stage 4 区间",
         fail_msg="回撤 {dd_from_high:+.1f}%，Stage 4 特征明显"),
]

# ── C 组 · 强度与动量 ────────────────────────────────────────────
ONEILL_RULES = [
    Rule("rs_70", "截面相对强度 ≥ 70（本池内排名）", 5,
         dims=("rs_rank",),
         check=lambda f: f["rs_rank"] >= 70,
         pass_msg="60 日动量截面分位 {rs_rank:.0f}/100，属强势组",
         fail_msg="相对强度分位 {rs_rank:.0f}/100，弱于池内多数标的"),
    Rule("accel_20_60", "动量加速（20 日 > 60 日日均）", 4,
         dims=("ret_20", "ret_60"),
         check=lambda f: f["ret_20"] > f["ret_60"] / 3.0,
         pass_msg="20 日 {ret_20:+.2f}% 快于 60 日均速 {ret_60_3m_pct:+.2f}%",
         fail_msg="20 日 {ret_20:+.2f}% 慢于 60 日均速 {ret_60_3m_pct:+.2f}%"),
    Rule("beat_bench", "跑赢同市场基准（60 日超额 > 0）", 4,
         dims=("rs_bench",),
         check=lambda f: f["rs_bench"] > 0,
         pass_msg="60 日相对基准超额 {rs_bench:+.2f} 个百分点",
         fail_msg="60 日跑输基准 {rs_bench:+.2f} 个百分点"),
    Rule("follow_through", "跟随日：涨 > 1% 且量比 > 1.3", 3,
         dims=("chg_pct", "vol_ratio"),
         check=lambda f: f["chg_pct"] > 1.0 and f["vol_ratio"] > 1.3,
         pass_msg="今日 {chg_pct:+.2f}% · 量比 {vol_ratio:.2f}，出现跟随",
         fail_msg="今日 {chg_pct:+.2f}% · 量比 {vol_ratio:.2f}，无跟随"),
]

MOMENTUM_RULES = [
    Rule("mom_z20_positive", "20 日动量 z 值为正", 4,
         dims=("mom_z20",),
         check=lambda f: f["mom_z20"] > 0,
         pass_msg="动量 z={mom_z20:+.2f}，快于自身一年分布",
         fail_msg="动量 z={mom_z20:+.2f}，慢于自身一年分布"),
    Rule("macd_above_signal", "MACD：DIF 在 DEA 上方", 4,
         dims=("macd_dif", "macd_hist"),
         check=lambda f: f["macd_hist"] > 0,
         pass_msg="DIF {macd_dif:+.4f} 高于 DEA，柱体 {macd_hist:+.4f}",
         fail_msg="柱体 {macd_hist:+.4f}，短线动能在下"),
    Rule("macd_hist_expand", "柱体扩张（动能未衰竭）", 3,
         dims=("macd_hist", "macd_hist_prev"),
         check=lambda f: abs(f["macd_hist"]) >= abs(f["macd_hist_prev"]),
         pass_msg="柱体由 {macd_hist_prev:+.4f} 扩到 {macd_hist:+.4f}",
         fail_msg="柱体由 {macd_hist_prev:+.4f} 缩到 {macd_hist:+.4f}，动能收敛"),
    Rule("trend_significant", "60 日趋势显著（|t| ≥ 2）", 4,
         dims=("trend_t", "trend_r2"),
         check=lambda f: abs(f["trend_t"]) >= 2.0 and f["trend_r2"] >= 0.3,
         pass_msg="t={trend_t:+.2f} · R²={trend_r2:.2f}，趋势线站得住",
         fail_msg="t={trend_t:+.2f} · R²={trend_r2:.2f}，趋势不显著"),
]

# ── D 组 · 量能确认 ──────────────────────────────────────────────
VOLUME_RULES = [
    Rule("up_dn_volume", "涨日均量 > 跌日均量（20 日）", 4,
         dims=("updn_vol_ratio",),
         check=lambda f: f["updn_vol_ratio"] > 1.05,
         pass_msg="涨/跌日均量比 {updn_vol_ratio:.2f}，买盘占优",
         fail_msg="涨/跌日均量比 {updn_vol_ratio:.2f}，卖压更重"),
    Rule("vol_trend", "量能趋势未衰减（5 日均量 / 20 日均量 ≥ 0.9）", 3,
         dims=("vol_trend_ratio",),
         check=lambda f: f["vol_trend_ratio"] >= 0.9,
         pass_msg="5 日/20 日均量 {vol_trend_ratio:.2f}，参与意愿维持",
         fail_msg="5 日/20 日均量 {vol_trend_ratio:.2f}，参与萎缩"),
    Rule("dry_pullback", "回踩缩量（跌日且量比 < 0.9）", 3,
         dims=("chg_pct", "vol_ratio"),
         check=lambda f: f["chg_pct"] <= 0 and f["vol_ratio"] < 0.9,
         pass_msg="今日 {chg_pct:+.2f}% · 量比 {vol_ratio:.2f}，缩量回调",
         fail_msg="跌日量比 {vol_ratio:.2f}，不是缩量回踩"),
    Rule("no_climax", "未出现天量警示（量比 < 3.5）", 3,
         dims=("vol_ratio",),
         check=lambda f: f["vol_ratio"] < 3.5,
         pass_msg="量比 {vol_ratio:.2f}，未见失控放量",
         fail_msg="量比 {vol_ratio:.2f}，天量之后需防冲高回落"),
]

VCP_RULES = [
    Rule("vol_squeeze", "已实现波动处于自身低位（20 日波动分位 ≤ 40%）", 4,
         dims=("vol_pct",),
         check=lambda f: 0 <= f["vol_pct"] <= 0.40,
         pass_msg="波动分位 {vol_pct_pct:.0f}%，处于收敛段",
         fail_msg="波动分位 {vol_pct_pct:.0f}%，未见收敛"),
    Rule("boll_squeeze", "布林带宽收口（带宽 ≤ 自身中位数）", 3,
         dims=("boll_width", "boll_width_median"),
         check=lambda f: f["boll_width"] <= f["boll_width_median"],
         pass_msg="带宽 {boll_width:.2f}% ≤ 一年中位 {boll_width_median:.2f}%",
         fail_msg="带宽 {boll_width:.2f}% 高于一年中位 {boll_width_median:.2f}%"),
    Rule("tight_action", "近 10 日振幅收敛（10 日波幅 / 60 日波幅 ≤ 0.45）", 3,
         dims=("range_collapse10",),
         check=lambda f: 0 <= f["range_collapse10"] <= 0.45,
         pass_msg="10/60 日波幅比 {range_collapse10:.2f}，抛压转轻",
         fail_msg="10/60 日波幅比 {range_collapse10:.2f}，仍在宽幅换手"),
    Rule("breakout_ready", "收缩 + 价在 20 日线上（蓄势待突破）", 3,
         dims=("range_collapse", "ma20",),
         check=lambda f: f["range_collapse"] <= 0.7 and f["close"] > f["ma20"],
         pass_msg="收缩比 {range_collapse:.2f} 且价在 MA20 {ma20:.2f} 上方",
         fail_msg="收缩比 {range_collapse:.2f} / 价 {close:.2f} vs MA20 {ma20:.2f}，形态未成"),
]

# ── E 组 · 市场环境（市场级证据，各标的共用）──────────────────
ENV_RULES = [
    Rule("breadth_up", "A股涨跌家数占优（上涨 > 下跌 ×1.2）", 4,
         dims=("breadth_up_n", "breadth_down_n"),
         check=lambda f: f["breadth_up_n"] > f["breadth_down_n"] * 1.2,
         pass_msg="涨跌家数 {breadth_up_n:.0f} / {breadth_down_n:.0f}"
                  "（{breadth_ratio_txt}），宽度配合",
         fail_msg="涨跌家数 {breadth_up_n:.0f} / {breadth_down_n:.0f}"
                  "（{breadth_ratio_txt}），宽度未配合"),
    Rule("turnover_expand", "两市成交额环比放大（≥ +5%）", 3,
         dims=("turnover_chg_pct",),
         check=lambda f: f["turnover_chg_pct"] >= 5,
         pass_msg="成交额环比 {turnover_chg_pct:+.1f}%，钱在进场",
         fail_msg="成交额环比 {turnover_chg_pct:+.1f}%，量能未跟上"),
    Rule("sector_net_positive", "板块净强弱为正（领涨均涨幅 + 领跌均跌幅 > 0）", 3,
         dims=("sector_net",),
         check=lambda f: f["sector_net"] > 0,
         pass_msg="板块净强弱 {sector_net:+.2f} 个百分点"
                  "（领涨 {sector_up_n:.0f} / 领跌 {sector_dn_n:.0f} 个板块）",
         fail_msg="板块净强弱 {sector_net:+.2f} 个百分点，弱势面更重"),
    Rule("liquidity_ok", "港股资金流动性分不差（≥ 45）", 3,
         dims=("liquidity_score",),
         check=lambda f: f["liquidity_score"] >= 45,
         pass_msg="流动性综合分 {liquidity_score:.0f}/100",
         fail_msg="流动性综合分 {liquidity_score:.0f}/100，出货环境偏紧"),
    Rule("crowd_not_extreme_bear", "社区情绪未极端悲观（NBI > −40）", 3,
         dims=("crowd_nbi",),
         check=lambda f: f["crowd_nbi"] is None or f["crowd_nbi"] > -40,
         pass_msg="社区 NBI {crowd_nbi_txt}（多 {crowd_bull:.0f} / 空 {crowd_bear:.0f}）",
         fail_msg="社区 NBI {crowd_nbi_txt} 已极端悲观，反弹易但反转难"),
    Rule("headline_net_positive", "标题多空净额不为负（新闻面顺风）", 3,
         dims=("headline_net",),
         check=lambda f: f["headline_net"] >= 0,
         pass_msg="标题多空净额 {headline_net:+d}（多 {headline_bull:.0f} / 空 {headline_bear:.0f}）",
         fail_msg="标题多空净额 {headline_net:+d}，负面读数更密"),
]

# ── F 组 · 风险纪律 ──────────────────────────────────────────────
RISK_RULES = [
    Rule("atr_band_ok", "波动在可交易区间（0.4% ≤ ATR% ≤ 3.5%）", 4,
         dims=("atr_pct",),
         check=lambda f: 0.4 <= f["atr_pct"] <= 3.5,
         pass_msg="ATR {atr_pct:.2f}%，波动可承受",
         fail_msg="ATR {atr_pct:.2f}%，波动超出可交易区间"),
    Rule("not_extended", "未追高（RSI14 < 75）", 3,
         dims=("rsi14",),
         check=lambda f: f["rsi14"] < 75,
         pass_msg="RSI {rsi14:.1f}，尚未极端",
         fail_msg="RSI {rsi14:.1f} 超买，追价赔率差"),
    Rule("no_false_break", "突破未回落（仍在 20 日箱体上方）", 4,
         dims=("close", "box_hi_20", "break_state"),
         check=lambda f: f["break_state"] != "hit",
         pass_msg="突破后未跌回关键点下方，假突破风险低",
         fail_msg="突破 {break_pivot:.2f} 后 {break_back_days:.0f} 根内跌回，按假突破处理"),
    Rule("drawdown_ok", "回撤可控（距 252 日高点 > −15%）", 3,
         dims=("dd_from_high",),
         check=lambda f: f["dd_from_high"] > -15,
         pass_msg="距高点 {dd_from_high:+.1f}%，净值曲线未受伤",
         fail_msg="距高点 {dd_from_high:+.1f}%，先修回撤再谈进攻"),
    Rule("data_fresh", "日线新鲜度达标（滞后 ≤ 4 天）", 4,
         dims=("lag_days",),
         check=lambda f: 0 <= f["lag_days"] <= MAX_LAG_DAYS,
         pass_msg="收盘日 {date}，滞后 {lag_days:.0f} 天",
         fail_msg="收盘日 {date} 已滞后 {lag_days:.0f} 天，定调只作参考"),
]

JUDGES: list[Judge] = [
    Judge("livermore", "利弗莫尔 · 关键点突破", "A",
          "Reminiscences of a Stock Operator (1923)", LIVERMORE_RULES),
    Judge("darvas", "达瓦斯 · 箱体理论", "A",
          "How I Made $2,000,000 in the Stock Market (1960)", DARVAS_RULES),
    Judge("gann", "江恩 · 时间与角度线", "A",
          "Truth of the Stock Tape (1923)", GANN_RULES),
    Judge("turtle", "海龟 · 通道与头寸", "A",
          "Turtle Trading Rules（D. Darst / Curtis Faith 记录）", TURTLE_RULES),
    Judge("minervini", "米内尔维尼 · Trend Template", "B",
          "Trade Like a Stock Market Wizard（SEPA）", MINERVINI_RULES),
    Judge("stage", "周线阶段 · Stage 1–4 分析", "B",
          "Stan Weinstein, Secrets for Profiting in Bull and Bear Markets", STAGE_RULES),
    Judge("oneill", "欧奈尔 · 相对强度", "C",
          "How to Make Money in Stocks（CAN SLIM 的 R/S）", ONEILL_RULES),
    Judge("momentum", "动量与动能确认", "C",
          "Jegadeesh & Titman 12-1 动量框架 + MACD(12,26,9)", MOMENTUM_RULES),
    Judge("volume", "量能确认派", "D",
          "量在价先（Granville 量能分析 / 相对强弱量）", VOLUME_RULES),
    Judge("vcp", "波动收缩派", "D",
          "Minervini VCP + 布林带宽收缩", VCP_RULES),
    Judge("env", "市场环境派", "E",
          "市场宽度 / 成交额 / 资金 / 舆论（本仓库既有栏目同源读数）", ENV_RULES),
    Judge("risk", "风险纪律派", "F",
          "ATR 头寸与止损 / 假突破 / 数据新鲜度闸门", RISK_RULES),
]
JUDGE_BY_ID = {j.id: j for j in JUDGES}
RULE_TOTAL_N = sum(len(j.rules) for j in JUDGES)


# ------------------------------------------------------------------
# 特征层：已收盘日线 → 18 维数据卡
# ------------------------------------------------------------------
def _finite(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def build_features(bars, *, benchmark=None, extras=None, code="", now=None) -> dict:
    """把日线序列折成评审用的维度字典。

    复用引擎特征层（动量 / 均线排列 / 回归 t 值 / RSI / ATR / MACD / 波动分位），
    再补齐趋势专用维度（150/200 日线、箱体、时间窗、量能结构、位置）。
    任何算不出来的维度一律留 None（缺失），绝不填 0 冒充中性。
    """
    base = _feat_mod.compute_features(bars or [])
    out = {"ok": False, "code": code, "reason": base.get("reason") or "日线样本不足",
           "bars_n": base.get("bars", 0)}
    if not base.get("ok"):
        return out

    clean = [b for b in (bars or []) if _finite(b.get("close")) is not None]
    closes = [_finite(b["close"]) for b in clean]
    highs = [_finite(b.get("high")) if _finite(b.get("high")) is not None else c
             for b, c in zip(clean, closes)]
    lows = [_finite(b.get("low")) if _finite(b.get("low")) is not None else c
            for b, c in zip(clean, closes)]
    vols = [_finite(b.get("volume")) for b in clean]
    close = closes[-1]

    out = dict(base)
    out.update({"ok": True, "code": code, "close": close, "date": clean[-1]["date"],
                "bars_n": len(clean)})

    # ---- 均线体系（50 / 150 / 200 与年线走向）----
    ma50 = stats.sma(closes, 50)
    ma150 = stats.sma(closes, 150)
    ma200 = stats.sma(closes, 200)
    out["ma50"] = ma50[-1] if ma50 else None
    out["ma150"] = ma150[-1] if ma150 else None
    out["ma200"] = ma200[-1] if ma200 else None
    if ma200 and len(ma200) >= 22 and ma200[-22]:
        out["ma200_chg_pct"] = (ma200[-1] / ma200[-22] - 1.0) * 100.0
        out["ma200_up"] = out["ma200_chg_pct"] > 0
    else:
        out["ma200_chg_pct"] = out["ma200_up"] = None
    out["above_ma200_pct"] = ((close / out["ma200"] - 1.0) * 100.0
                              if out["ma200"] else None)
    out["ma20"] = base.get("sma20")
    out["ma60"] = base.get("sma60")

    # ---- 位置（252 日高低点、距今交易日数）----
    win = closes[-252:]
    hi_252, lo_252 = max(win), min(win)
    out["dist_hi_252"] = (close / hi_252 - 1.0) * 100.0 if hi_252 else None
    out["dist_lo_252"] = (close / lo_252 - 1.0) * 100.0 if lo_252 else None
    out["days_from_hi"] = len(win) - 1 - win.index(hi_252)
    out["days_from_lo"] = len(win) - 1 - win.index(lo_252)

    # ---- 箱体 / 关键点（达瓦斯 + 海龟）----
    def _box(n):
        if len(clean) < n + 1:
            return None, None
        return max(highs[-n - 1:-1]), min(lows[-n - 1:-1])

    hi20, lo20 = _box(20)
    hi10, lo10 = _box(10)
    hi55, _lo55 = _box(55)
    out["box_hi_20"], out["box_lo_20"] = hi20, lo20
    out["box_hi_55"], out["box_hi_10"], out["box_lo_10"] = hi55, hi10, lo10
    span = (hi20 - lo20) if (hi20 and lo20 is not None and hi20 > lo20) else None
    out["box_pos"] = (close - lo20) / span * 100.0 if span else None
    out["breakout_55"] = bool(hi55 and close > hi55)
    out["stop_dist_pct"] = ((close - lo20) / close * 100.0) if lo20 and close else None
    out["stop_2n_pct"] = (2.0 * out["atr_pct"]) if out.get("atr_pct") is not None else None
    # 假突破：近 5 根内曾突破「当时」的 20 日箱体上沿，如今又跌回那个上沿下方。
    # （用当时的枢轴价判定，不能用现在的 hi20 —— 突破日的高点本身已把它抬高了。）
    # break_state 三态：None = 样本不足、无从判定；"hit" = 假突破；"miss" = 无假突破
    # （含「窗口内根本没有突破事件」——那属于未命中，不是数据不足）。
    broke_back, break_pivot, break_days = False, None, None
    break_state = "miss" if len(closes) >= 22 else None
    if break_state == "miss":
        for back in range(1, min(6, len(closes))):
            idx = len(closes) - back
            if idx < 21:
                break
            pivot_at = max(highs[idx - 20:idx])
            if closes[idx] > pivot_at:        # 这一根确实创了当时 20 日新高
                break_pivot, break_days = pivot_at, back
                if closes[-1] < pivot_at:
                    broke_back, break_state = True, "hit"
                break
    out["broke_below_pivot_after_break"] = broke_back
    out["break_state"] = break_state
    out["break_pivot"] = break_pivot
    out["break_back_days"] = break_days

    # ---- 量能结构 ----
    if len(vols) >= 21 and all(v is not None for v in vols[-21:]):
        ups, dns = [], []
        for i in range(len(closes) - 20, len(closes)):
            if i <= 0 or vols[i] is None:
                continue
            (ups if closes[i] >= closes[i - 1] else dns).append(vols[i])
        avg_up = stats.mean(ups) if ups else None
        avg_dn = stats.mean(dns) if dns else None
        out["updn_vol_ratio"] = (avg_up / avg_dn) if (avg_up and avg_dn) else None
        v5 = stats.mean([v for v in vols[-5:] if v is not None])
        v20 = stats.mean([v for v in vols[-20:] if v is not None])
        out["vol_trend_ratio"] = (v5 / v20) if (v5 and v20) else None
    else:
        out["updn_vol_ratio"] = out["vol_trend_ratio"] = None

    # ---- 波幅收缩（VCP）----
    def _range(win_highs, win_lows, n):
        if len(win_highs) < n:
            return None
        h, lo = max(win_highs[-n:]), min(win_lows[-n:])
        return (h - lo) if (h > lo and lo > 0) else None

    r20 = _range(highs, lows, 20)
    r60 = _range(highs, lows, 60)
    r10 = _range(highs, lows, 10)
    out["range_collapse"] = (r20 / r60) if (r20 and r60) else None
    out["range_collapse10"] = (r10 / r60) if (r10 and r60) else None

    # ---- 布林带宽的自身一年中位数 ----
    widths = []
    for i in range(20, len(closes) + 1):
        window = closes[max(0, i - 20):i]
        if len(window) < 20:
            continue
        mid = sum(window) / 20.0
        sd = stats.stdev(window) or 0.0
        if mid:
            widths.append(4.0 * sd / mid * 100.0)
    out["boll_width_median"] = stats.percentile(widths[-252:], 0.5) if len(widths) >= 60 else None

    # ---- 江恩时间窗（斐波那契计数）----
    fibs = (21, 34, 55, 89, 144)
    anchors = [d for d in (out["days_from_hi"], out["days_from_lo"]) if d is not None]
    gaps = [min(abs(d - f) for f in fibs) for d in anchors]
    out["fib_gap"] = min(gaps) if gaps else None

    # ---- 1×1 角度线近似：日均涨速 vs ATR ----
    atr_val = base.get("atr_pct")
    reg = stats.linreg([math.log(c) for c in closes[-60:] if c > 0]) if len(closes) >= 60 else None
    if reg and out.get("ma20"):
        out["slope_per_bar"] = reg["slope"] * out["ma20"]
        out["atr_val"] = atr_val / 100.0 * out["ma20"] if atr_val is not None else None
    else:
        out["slope_per_bar"] = out["atr_val"] = None

    # ---- MACD（与【六眼飞鱼】栏同参数，独立计算、不并入其信号分）----
    series = stats.macd_series(closes)
    dif, dea, gap = series[-1] if series else (None, None, None)
    out["macd_dif"], out["macd_hist"] = dif, gap
    out["macd_hist_prev"] = series[-2][2] if len(series) > 1 else None

    # ---- 动量加速用的换算 ----
    out["ret_60_3m_pct"] = (out.get("ret_60") / 3.0) if out.get("ret_60") is not None else None
    out["vol_pct_pct"] = (out["vol_pct"] * 100.0) if out.get("vol_pct") is not None else None

    # ---- 相对基准超额（60 日，同市场；跨市场不混比）----
    out["rs_bench"] = None
    if benchmark and len(benchmark) > 60:
        bench = _feat_mod.compute_features(benchmark)
        if bench.get("ok") and bench.get("ret_60") is not None and out.get("ret_60") is not None:
            out["rs_bench"] = out["ret_60"] - bench["ret_60"]

    # ---- 新鲜度（滞后自然日数）----
    moment = now or datetime.now(providers.CST)
    try:
        as_of = datetime.strptime(str(out["date"])[:10], "%Y-%m-%d").date()
        out["lag_days"] = max(0, (moment.date() - as_of).days)
    except (TypeError, ValueError):
        out["lag_days"] = None

    # ---- 市场级环境维度（各标的共用，来源由调用方注入）----
    extras = extras or {}
    for key in MARKET_LEVEL_DIMS:
        out[key] = _finite(extras.get(key))
    for key in ("breadth_up_n", "breadth_down_n", "sector_up_n", "sector_dn_n",
                "crowd_bull", "crowd_bear", "headline_bull", "headline_bear"):
        value = extras.get(key)
        out[key] = _finite(value)
    out["crowd_nbi"] = extras.get("crowd_nbi")
    out["breadth_ratio_txt"] = str(extras.get("breadth_ratio_txt") or "涨跌比暂缺")
    out["crowd_nbi_txt"] = str(extras.get("crowd_nbi_txt") or "—")
    out["liquidity_score"] = _finite(extras.get("liquidity_score"))
    return out


def apply_cross_section(rows):
    """截面相对强度：把 60 日动量在评审池内做百分位排名（欧奈尔 RS 的可实现口径）。

    样本 < 3 不给分位（排名无意义），该行 RS 维度留 None → 相关规则 skip。
    """
    scored = [(row, row["feat"].get("ret_60")) for row in rows
              if row.get("feat", {}).get("ok") and row["feat"].get("ret_60") is not None]
    if len(scored) < 3:
        for row, _ in scored:
            row["feat"]["rs_rank"] = None
        row_note = "评审池有效标的不足 3 只，截面相对强度不计算"
        return row_note
    values = [value for _row, value in scored]
    for row, value in scored:
        rank = stats.pct_rank(value, values)
        row["feat"]["rs_rank"] = rank * 100.0 if rank is not None else None
    return ""


# ------------------------------------------------------------------
# 评委裁决（移植上游 evaluate 的三层结构：能力圈 → 规则 → 合成）
# ------------------------------------------------------------------
def evaluate_judge(judge: Judge, feat: dict, *, school_lock: str = "") -> dict:
    """单位方法评委对单一标的的裁决。返回带 pass/fail/skip 明细的可审计结果。"""
    lock = school_lock if school_lock is not None else locked_school()
    if lock and judge.school != lock:
        return {"judge_id": judge.id, "name": judge.name, "school": judge.school,
                "signal": "skip", "score": None, "confidence": None,
                "reason": f"锁定 {SCHOOLS.get(lock, (lock,))[0]} 派视角 · 非该派评委不参与",
                "pass_rules": [], "fail_rules": [], "skip_rules": [],
                "weight_pass": 0, "weight_total": 0, "weight_all": sum(r.weight for r in judge.rules),
                "headline": "—"}

    passed, failed, skipped = [], [], []
    weight_pass = weight_total = 0
    for rule in judge.rules:
        verdict = _rule(rule, feat)
        if verdict is None:
            skipped.append({"rule_id": rule.rule_id, "name": rule.name, "weight": rule.weight,
                            "msg": "输入维度缺失（" + "、".join(DIM_TITLES.get(d, d) for d in rule.dims) + "）"
                            if rule.dims else "输入维度缺失"})
            continue
        weight_total += rule.weight
        entry = {"rule_id": rule.rule_id, "name": rule.name, "weight": rule.weight,
                 "msg": _fmt(rule.pass_msg if verdict else rule.fail_msg, feat) or rule.name}
        if verdict:
            weight_pass += rule.weight
            passed.append(entry)
        else:
            failed.append(entry)

    weight_all = sum(r.weight for r in judge.rules)
    coverage = (weight_total / weight_all) if weight_all else 0.0
    if not weight_total or coverage < MIN_JUDGE_COVERAGE:
        return {"judge_id": judge.id, "name": judge.name, "school": judge.school,
                "signal": "skip", "score": None, "confidence": None,
                "reason": (f"可评权重 {weight_total}/{weight_all}（覆盖率 {coverage * 100:.0f}%）"
                           f"低于 {MIN_JUDGE_COVERAGE * 100:.0f}% 门槛"),
                "pass_rules": passed, "fail_rules": failed, "skip_rules": skipped,
                "weight_pass": weight_pass, "weight_total": weight_total,
                "weight_all": weight_all, "coverage": coverage, "headline": "—"}

    score = round(weight_pass / weight_total * 100.0, 1)
    if score >= BULLISH_THRESHOLD:
        signal = "bullish"
    elif score < BEARISH_THRESHOLD:
        signal = "bearish"
    else:
        signal = "neutral"
    # 置信度 = 参与规则数 + 结论极端度，再按维度覆盖率打折（覆盖率越低越没把握）。
    # 上限 95：任何评委都不给「100% 把握」，与日报里概率夹在 5%~95% 同一口径。
    extremeness = min(25.0, abs(score - 50.0) * 0.5)
    volume_bonus = min(20.0, (len(passed) + len(failed)) * 4.0)
    confidence = int(max(10, min(95, round((50.0 + volume_bonus + extremeness)
                                           * (0.55 + 0.45 * coverage)))))
    # headline：看多说最强的命中理由，看空说最重的未达项，中性说最接近翻转的那条。
    if signal == "bearish" and failed:
        top = max(failed, key=lambda r: r["weight"])
        headline = f"✗ {top['name']}：{top['msg']}"
    elif passed:
        top = max(passed, key=lambda r: r["weight"])
        headline = f"✓ {top['name']}：{top['msg']}"
    elif failed:
        top = max(failed, key=lambda r: r["weight"])
        headline = f"✗ {top['name']}：{top['msg']}"
    else:
        headline = "—"
    return {"judge_id": judge.id, "name": judge.name, "school": judge.school,
            "signal": signal, "score": score, "confidence": confidence,
            "pass_rules": sorted(passed, key=lambda r: -r["weight"]),
            "fail_rules": sorted(failed, key=lambda r: -r["weight"]),
            "skip_rules": skipped,
            "weight_pass": weight_pass, "weight_total": weight_total,
            "weight_all": weight_all, "coverage": coverage, "headline": headline,
            "reason": None}


def evaluate_symbol(feat: dict, *, school_lock: str = "") -> dict:
    """单标的的全体评委裁决 + 加权定调（权重 = 可评权重 × 置信度，缺数据不占票）。"""
    judges = [evaluate_judge(j, feat, school_lock=school_lock) for j in JUDGES]
    scored = [j for j in judges if j["signal"] != "skip"]
    weighted = [(j["score"] * j["weight_total"] * j["confidence"]) for j in scored]
    weights = [j["weight_total"] * j["confidence"] for j in scored]
    total_w = sum(weights)
    score = round(sum(weighted) / total_w, 1) if total_w else None
    label = _label(score)
    counts = {k: sum(1 for j in judges if j["signal"] == k)
              for k in ("bullish", "bearish", "neutral", "skip")}
    return {"judges": judges, "score": score, "label": label, "counts": counts,
            "coverage": round(sum(j["weight_total"] for j in scored)
                              / max(1, sum(j["weight_all"] for j in judges)) * 100.0, 1),
            "gaps": [{"name": j["name"], "reason": j.get("reason") or ""}
                     for j in judges if j["signal"] == "skip" and j.get("reason")]}


def _label(score):
    if score is None:
        return "数据不足"
    for floor, name in LABEL_BANDS:
        if score >= floor:
            return name
    return "强空头"


def _direction(score):
    """定调 → 方向标记（沿用日报 ▲ / ▼ / ■ 双编码口径）。"""
    if score is None:
        return "■"
    if score >= 58:
        return "▲"
    if score < 42:
        return "▼"
    return "■"


def _divergence(bull, bear):
    """多空分歧熵（0–100）：与【麻辣大龙虾】栏同一算法，评委二元方向分歧越大越接近 100。"""
    total = bull + bear
    if total <= 0:
        return None
    p = bull / total
    if p in (0.0, 1.0):
        return 0.0
    return round(-(p * math.log2(p) + (1 - p) * math.log2(1 - p)) * 100.0, 1)


# ------------------------------------------------------------------
# 趋势失效风险扫描（移植上游 trap-detector 的「8 信号 · 三态」结构）
# ------------------------------------------------------------------
RISK_SIGNALS = [
    ("break_back", "假突破：突破 20 日关键位后跌回箱体",
     ("break_state",),
     lambda f: f["break_state"] == "hit",
     lambda f: (f"突破 {f['break_pivot']:.2f} 后 {f['break_back_days']:.0f} 根内收在 "
                f"{f['close']:.2f}，按假突破处理")),
    ("high_volume_reject", "高位放量长上影（冲高回落）",
     ("close", "high", "open"),
     lambda f: (f["high"] - max(f["close"], f["open"])) / f["close"] * 100 >= 1.2
     and (f.get("vol_ratio") or 0) >= 1.5,
     lambda f: f"上影 {f['upper_shadow_pct']:.2f}% · 量比 {f['vol_ratio']:.2f}"),
    ("ma_flatten", "均线走平且价贴 50 日线（趋势衰竭）",
     ("close", "ma50"),
     lambda f: abs((f["close"] / f["ma50"] - 1.0) * 100) <= 0.8 and abs(f["trend_t"]) < 1.5,
     lambda f: f"价距 MA50 {(f['close'] / f['ma50'] - 1.0) * 100:+.2f}% · t={f['trend_t']:+.2f}"),
    ("overextended", "短线过热（20 日涨幅 > 15% 且量能背离）",
     ("ret_20", "updn_vol_ratio"),
     lambda f: f["ret_20"] > 15 and f["updn_vol_ratio"] < 1.0,
     lambda f: f"20 日 {f['ret_20']:+.2f}% 但涨/跌日均量比仅 {f['updn_vol_ratio']:.2f}"),
    ("rsi_extreme_high", "超买极端（RSI14 ≥ 80 且距 252 日高点 < 2%）",
     ("rsi14", "dist_hi_252"),
     lambda f: f["rsi14"] >= 80 and abs(f["dist_hi_252"]) <= 2,
     lambda f: f"RSI {f['rsi14']:.1f} · 距高点 {f['dist_hi_252']:+.2f}%"),
    ("below_ma20_streak", "连续破位（收盘 < MA20 且 MA20 下行）",
     ("close", "ma20", "ret_20"),
     lambda f: f["close"] < f["ma20"] and f["ret_20"] < -2,
     lambda f: f"收盘 {f['close']:.2f} < MA20 {f['ma20']:.2f} · 20 日 {f['ret_20']:+.2f}%"),
    ("vol_spike_abnormal", "异常波动（单日真实波幅 > 3×ATR）",
     ("tr_pct", "atr_pct"),
     lambda f: f["atr_pct"] and f["tr_pct"] > 3 * f["atr_pct"],
     lambda f: f"当日波幅 {f['tr_pct']:.2f}% > 3×ATR({f['atr_pct']:.2f}%)"),
    ("stale_data", "数据风险：日线滞后超过门槛",
     ("lag_days",),
     lambda f: f["lag_days"] > MAX_LAG_DAYS,
     lambda f: f"最新收盘日 {f['date']}，已滞后 {f['lag_days']:.0f} 天（门槛 {MAX_LAG_DAYS} 天）"),
]


def scan_risks(feat: dict) -> list:
    """逐信号给三态结论：命中 / 未命中 / 数据不足（上游「8 信号每格都要标」的口径）。"""
    rows = []
    for rid, name, dims, check, evidence in RISK_SIGNALS:
        if not _known(feat, *dims):
            rows.append({"id": rid, "name": name, "state": "数据不足", "evidence": ""})
            continue
        try:
            hit = bool(check(feat))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            rows.append({"id": rid, "name": name, "state": "数据不足", "evidence": ""})
            continue
        rows.append({"id": rid, "name": name,
                     "state": "命中" if hit else "未命中",
                     "evidence": _fmt(evidence(feat), feat) if hit else ""})
    return rows


# ------------------------------------------------------------------
# 话术闸门 + 自检（移植上游 quality-checklist / self_review）
# ------------------------------------------------------------------
_BANNED_RE = re.compile("|".join(re.escape(p) for p in BANNED_PHRASES))


def fluff_check(*texts) -> list:
    """返回命中禁用话术的文本（上游：出现即失败，必须换成定量句）。"""
    return [t for t in texts if t and _BANNED_RE.search(str(t))]


def self_check(result: dict) -> dict:
    """栏目级自检：任何 ❌ 都由调用方打印警告；测试守护这几条不变量。"""
    items = result.get("items") or []
    board = result.get("board") or []
    checks = [
        ("评审池有标的", bool(items)),
        ("每位评委规则数 ≥ 4", all(len(j.rules) >= 4 for j in JUDGES)),
        ("规则总数与注册表一致", result.get("parameters", {}).get("rules_total") == RULE_TOTAL_N),
        ("逐标的都带评委裁决明细", all(len(it.get("judges") or []) == len(JUDGES) for it in items)),
        ("每行都有维度覆盖率", all((it.get("dims") or {}).get("coverage_pct") is not None for it in items)),
        ("风险清单 8 信号齐备", all(len(it.get("risks") or []) == len(RISK_SIGNALS) for it in items)),
        ("定调含具体数字", bool(re.search(r"\d", str(result.get("consensus", {}).get("punchline") or "")))),
        ("无空泛话术", not result.get("fluff_hits")),
        ("缺数据标暂缺、不冒充中性", all(bool(it.get("dims")) for it in items)),
    ]
    return {"checks": [{"name": name, "ok": bool(ok)} for name, ok in checks],
            "all_ok": all(ok for _n, ok in checks)}


# ------------------------------------------------------------------
# 单标的分析入口（纯计算，测试直接喂假日线）
# ------------------------------------------------------------------
def prepare_row(bars, *, label, code, source="已有日线", benchmark=None,
                extras=None, now=None) -> dict:
    """第一阶段：日线 → 18 维数据卡 + 风险扫描（不做裁决，留给截面计算之后）。

    样本 / 新鲜度不达标时返回 available=False + 原因（上游 data_integrity 闸门口径：
    宁可整行不进评审，也不拿半截数据凑分）。
    """
    moment = now or datetime.now(providers.CST)
    feat = build_features(bars, benchmark=benchmark, extras=extras, code=code, now=moment)
    if not feat.get("ok"):
        return {"available": False, "label": label, "code": code,
                "reason": f"日线不足（{feat.get('bars_n', 0)}/{MIN_BARS} 根）",
                "bars_n": feat.get("bars_n", 0)}
    if feat["bars_n"] < MIN_BARS:
        return {"available": False, "label": label, "code": code,
                "reason": f"已收盘日线不足（{feat['bars_n']}/{MIN_BARS} 根）", "bars_n": feat["bars_n"]}
    critical_missing = [k for k in CRITICAL_DIMS if not _known(feat, k)]
    if critical_missing:
        return {"available": False, "label": label, "code": code,
                "reason": "关键维度缺失：" + "、".join(DIM_TITLES.get(k, k) for k in critical_missing),
                "bars_n": feat["bars_n"]}

    # 风险扫描要用的补充字段（当日真实波幅 / 上影线），只在这里算一次。
    clean = [b for b in (bars or []) if _finite(b.get("close")) is not None]
    last = clean[-1]
    close = feat["close"]
    prev_close = _finite(clean[-2]["close"]) if len(clean) > 1 else None
    high = _finite(last.get("high")) or close
    low = _finite(last.get("low")) or close
    open_ = _finite(last.get("open")) or close
    feat["tr_pct"] = ((max(high, prev_close or high) - min(low, prev_close or low))
                      / close * 100.0) if prev_close else None
    feat["upper_shadow_pct"] = (high - max(close, open_)) / close * 100.0
    feat["high"], feat["open"] = high, open_

    dims_available = [d["key"] for d in DIMENSIONS if _known(feat, d["key"])]
    dims_missing = [d["key"] for d in DIMENSIONS if d["key"] not in dims_available]
    lag = feat.get("lag_days")
    return {
        "available": True, "label": label, "code": code, "as_of": feat.get("date"),
        "bars_n": feat["bars_n"], "source": source, "close": close, "feat": feat,
        "lag_days": lag, "stale": bool(lag is not None and lag > MAX_LAG_DAYS),
        "risks": scan_risks(feat),
        "dims": {"available": len(dims_available), "total": len(DIMENSIONS),
                 "coverage_pct": round(len(dims_available) / len(DIMENSIONS) * 100.0, 1),
                 "available_keys": dims_available, "missing_keys": dims_missing,
                 "critical_missing": critical_missing},
    }


def judge_row(row, *, school_lock="") -> dict:
    """第二阶段：截面维度补齐后才做评委裁决（欧奈尔的 RS 分位依赖全池样本）。"""
    feat = row["feat"]
    verdict = evaluate_symbol(feat, school_lock=school_lock)
    # 滞后超门槛：数字与逐条裁决全部保留，只把定调降级（不硬造方向）。
    score = None if row.get("stale") else verdict["score"]
    row.update({
        "score": score, "label_dir": _label(score), "mark": _direction(score),
        "raw_score": verdict["score"], "counts": verdict["counts"],
        "coverage": verdict["coverage"], "judges": verdict["judges"],
        "gaps": verdict["gaps"],
        "metrics": {
            "stage": _stage_text(feat),
            "box": (f"{feat['box_pos']:.0f}/100" if feat.get("box_pos") is not None else None),
            "ret_20": feat.get("ret_20"), "ret_60": feat.get("ret_60"),
            "rs_rank": feat.get("rs_rank"), "rs_bench": feat.get("rs_bench"),
            "atr_pct": feat.get("atr_pct"), "dd_from_high": feat.get("dd_from_high"),
            "trend_t": feat.get("trend_t"), "trend_r2": feat.get("trend_r2"),
            "vol_ratio": feat.get("vol_ratio"), "rsi14": feat.get("rsi14"),
            "ma50": feat.get("ma50"), "ma200": feat.get("ma200"),
            "above_ma200_pct": feat.get("above_ma200_pct"),
            "pivot_hi": feat.get("box_hi_20"), "pivot_lo": feat.get("box_lo_20"),
            "breakout_55": bool(feat.get("breakout_55")),
        },
    })
    row["log"] = methodology_log(row)
    return row


def analyze_bars(bars, *, label, code, source="已有日线", benchmark=None,
                 extras=None, now=None, school_lock=None) -> dict:
    """单标的纯计算入口（测试与离线研究直接用）：准备 → 裁决，一次到底。"""
    row = prepare_row(bars, label=label, code=code, source=source, benchmark=benchmark,
                      extras=extras, now=now)
    if not row.get("available"):
        return row
    return judge_row(row, school_lock=school_lock or "")


def _stage_text(feat: dict) -> str:
    """Weinstein 四阶段粗判（只用已算出的维度，不引入新数据）。"""
    close, ma200, ma50 = feat.get("close"), feat.get("ma200"), feat.get("ma50")
    ret20 = feat.get("ret_20")
    if close is None or ma200 is None or ma50 is None or ret20 is None:
        return ""
    above = close > ma200
    rising = bool(feat.get("ma200_up"))
    if above and rising and close > ma50 and ret20 > 0:
        return "Stage 2 上升"
    if not above and not rising and close < ma50 and ret20 < 0:
        return "Stage 4 下跌"
    if above and abs(close / ma200 - 1) < 0.05 and abs(ret20) < 3:
        return "Stage 1 筑底"
    return "Stage 3 顶部/整理" if above else "Stage 3 弱势整理"


def methodology_log(row: dict) -> list:
    """可审计推导链（上游 methodology_log 口径）：每一步写出「用了什么 → 怎么算 → 得什么」。"""
    feat, out = row.get("feat") or {}, []
    out.append(f"Step 1 · 样本：{row['bars_n']} 根已收盘日线（源 {row.get('source') or '—'}，"
               f"收盘日 {row['as_of']}，滞后 {row.get('lag_days') if row.get('lag_days') is not None else '?'} 天）")
    out.append(f"Step 2 · 维度：{row['dims']['available']}/{row['dims']['total']} 维可用"
               f"（{row['dims']['coverage_pct']:.1f}%）"
               + (f"；缺：{'、'.join(DIM_TITLES.get(k, k) for k in row['dims']['missing_keys'][:6])}"
                  if row["dims"]["missing_keys"] else ""))
    out.append(f"Step 3 · 规则：12 位方法评委 × {RULE_TOTAL_N} 条；命中 "
               f"{sum(len(j['pass_rules']) for j in row['judges'])} 条 · 未达 "
               f"{sum(len(j['fail_rules']) for j in row['judges'])} 条 · 数据不足 "
               f"{sum(len(j['skip_rules']) for j in row['judges'])} 条（缺失不判负，不占分母）")
    scored = [j for j in row["judges"] if j["signal"] != "skip"]
    if scored:
        top = max(scored, key=lambda j: (j["weight_total"] * j["confidence"], j["score"]))
        out.append(f"Step 4 · 加权：以「可评权重 × 置信度」为票权取加权均值，"
                   f"票权最重的评委 {top['name']} 给 {top['score']:.1f} 分"
                   f"（命中权重 {top['weight_pass']}/{top['weight_total']} · 置信 {top['confidence']}）")
    else:
        out.append("Step 4 · 加权：全体评委均因维度覆盖不足 skip，不给定调")
    out.append(f"Step 5 · 定调：趋势分 {row['score'] if row['score'] is not None else '暂缺'}"
               f" → {row['label_dir']}（阈值 ≥{BULLISH_THRESHOLD} 看多 / <{BEARISH_THRESHOLD} 看空）"
               + ("；日线滞后超门槛，定调降级为只作参考" if row.get("stale") else ""))
    hit = [r["name"] for r in row["risks"] if r["state"] == "命中"]
    out.append(f"Step 6 · 风险：{len(hit)} / {len(RISK_SIGNALS)} 个失效信号命中"
               + (f"（{'、'.join(hit[:3])}）" if hit else ""))
    return [x for x in out if x]


# ------------------------------------------------------------------
# 评委打分板（跨标的聚合）与定调合成
# ------------------------------------------------------------------
def build_board(items: list) -> list:
    """评委 × 流派聚合板：每位方法评委在本栏标的池上的平均分与投票分布。"""
    board = []
    for judge in JUDGES:
        results = [row["judges"][JUDGE_LIST_INDEX[judge.id]] for row in items
                   if row.get("judges") and len(row["judges"]) > JUDGE_LIST_INDEX[judge.id]]
        scored = [r for r in results if r["signal"] != "skip"]
        avg = round(sum(r["score"] * r["weight_total"] for r in scored)
                    / max(1e-9, sum(r["weight_total"] for r in scored)), 1) if scored else None
        board.append({
            "id": judge.id, "name": judge.name, "school": judge.school,
            "school_name": SCHOOLS[judge.school][0], "origin": judge.origin,
            "rules_total": len(judge.rules), "avg_score": avg,
            "bull": sum(1 for r in scored if r["signal"] == "bullish"),
            "bear": sum(1 for r in scored if r["signal"] == "bearish"),
            "neutral": sum(1 for r in scored if r["signal"] == "neutral"),
            "skip": sum(1 for r in results if r["signal"] == "skip"),
            "avg_confidence": (round(sum(r["confidence"] for r in scored) / len(scored))
                               if scored else None),
            "best": (max(scored, key=lambda r: r["score"]) if scored else None),
            "worst": (min(scored, key=lambda r: r["score"]) if scored else None),
        })
    return board


JUDGE_LIST_INDEX = {j.id: i for i, j in enumerate(JUDGES)}


def great_divide(board: list) -> dict:
    """The Great Divide：把最强多头与最强空头并置，冲突写进正文而不是抹平。"""
    rated = [b for b in board if b.get("avg_score") is not None]
    if not rated:
        return {}
    bull = max(rated, key=lambda b: b["avg_score"])
    bear = min(rated, key=lambda b: b["avg_score"])
    out = {"bull": bull["name"], "bull_score": bull["avg_score"],
           "bear": bear["name"], "bear_score": bear["avg_score"],
           "gap": round(bull["avg_score"] - bear["avg_score"], 1)}
    if out["gap"] <= 0.5:
        out["tone"] = (f"{len(board)} 位方法评委平均后仍高度一致（最大分差 "
                       f"{out['gap']:.1f} 分）· 本次分歧本身没有信息量，重点看覆盖率")
    else:
        out["tone"] = (f"{bull['name']} 平均 {bull['avg_score']:.1f} 分 vs "
                       f"{bear['name']} {bear['avg_score']:.1f} 分，差 {out['gap']:.1f} 分")
    return out


def punchline(items: list, board: list, consensus: dict) -> str:
    """一句带数字、有冲突感的定调（上游禁止空泛话术，要求定量 + 反预期）。

    只说本次真算出来的数：全池均分、最强 / 最弱标的、重点标的的两个关键位置、
    评委两极分差与分歧熵。任何一项缺数据就整段省略，不拿占位数字凑句子。
    """
    rated = [b for b in board if b.get("avg_score") is not None]
    bull = max(rated, key=lambda b: b["avg_score"]) if rated else None
    bear = min(rated, key=lambda b: b["avg_score"]) if rated else None
    scored_rows = [r for r in items if r.get("score") is not None]
    bits = []
    if consensus.get("score") is not None and scored_rows:
        head = f"{len(scored_rows)} 只标的平均趋势分 {consensus['score']:.1f}（{consensus.get('label')}）"
        if len(scored_rows) > 1:
            strongest = max(scored_rows, key=lambda r: r["score"])
            weakest = min(scored_rows, key=lambda r: r["score"])
            head += f"；最强 {strongest['label']} {strongest['score']:.1f}、" \
                    f"最弱 {weakest['label']} {weakest['score']:.1f}"
        bits.append(head)
    focus = next((r for r in items if r["label"] == consensus.get("focus_label")), None)
    if focus:
        metrics = focus.get("metrics") or {}
        if metrics.get("ret_20") is not None and metrics.get("above_ma200_pct") is not None:
            bits.append(f"分歧最大的 {focus['label']} 20 日 {metrics['ret_20']:+.2f}%、"
                        f"距年线 {metrics['above_ma200_pct']:+.2f}%")
    if bull and bear and bull is not bear and bull["avg_score"] - bear["avg_score"] > 0.5:
        bits.append(f"{bull['name']} 均分 {bull['avg_score']:.1f}，{bear['name']} 只有 "
                    f"{bear['avg_score']:.1f}（差 {bull['avg_score'] - bear['avg_score']:.1f} 分）")
    if consensus.get("divergence") is not None:
        bits.append(f"评委分歧熵 {consensus['divergence']:.0f}/100")
    text = " · ".join(bits) if bits else "样本不足，本轮不给定调句"
    return text, bool(fluff_check(text))


# ------------------------------------------------------------------
# 编排层：市场库 → 本次已有日线 → 免费主备源（与【六眼飞鱼】栏同一取数阶梯）
# ------------------------------------------------------------------
def symbol_specs():
    """OCTOPUS_TREND_SYMBOLS='^HSI:恒生指数,0700.HK:腾讯控股'；去重、最多 12 只。"""
    raw = str(os.environ.get("OCTOPUS_TREND_SYMBOLS", "")).strip()
    if not raw:
        return list(DEFAULT_SPECS)
    specs, seen = [], set()
    for chunk in raw.split(","):
        code, _, name = chunk.strip().partition(":")
        if code and code not in seen:
            seen.add(code)
            specs.append((name.strip() or code, code))
    return specs[:12] or list(DEFAULT_SPECS)


def _completed_bars(bars, code, *, now=None):
    """只保留有限正收盘 + 已收盘行情日，按日去重升序（复用 MACD 栏的同一口径）。"""
    from .macd_strategy import completed_bars
    return completed_bars(bars, code, now=now)


def _bars_ready(bars, code, now):
    if len(bars) < MIN_BARS:
        return False, f"已收盘日线不足（{len(bars)}/{MIN_BARS} 根）"
    try:
        as_of = datetime.strptime(str(bars[-1]["date"])[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False, "日线缺少合法收盘日"
    lag = (now.date() - as_of).days
    if lag > MAX_LAG_DAYS:
        return False, f"日线过旧（截至 {as_of.isoformat()}，滞后 {lag} 天）"
    return True, ""


def run_trend(fetch_json=None, *, existing=None, extras=None, specs=None,
              db_root=None, now=None, school_lock=None, depth="standard") -> dict:
    """栏目主编排入口：取数 → 18 维 → 评委裁决 → 打分板 → 定调 → 自检。

    取数阶梯与【六眼飞鱼】MACD 栏完全一致（市场库 → 本次量化日线 → Yahoo/东财主备链），
    整段选源、绝不拼接不同源 / 复权口径；抓不到就少一行，并在缺项里写明原因。
    """
    moment = now or datetime.now(providers.CST)
    specs = list(specs) if specs is not None else symbol_specs()
    existing = existing or {}
    lock = school_lock if school_lock is not None else locked_school()
    warnings = []

    db, db_error = {}, None
    try:
        import market_db
        db = market_db.load_daily_bars(symbols=[code for _name, code in specs],
                                       root=db_root or market_db.DB_ROOT, now=moment) or {}
    except Exception as exc:
        db_error = f"市场库读取失败（{type(exc).__name__}）"

    selected, pending, attempts, rejected = {}, [], {}, {}
    for label, code in specs:
        candidates = []
        for origin, raw in (("市场库·日线", db.get(code)),
                           ("本次量化日线", existing.get(code))):
            bars = _completed_bars(raw, code, now=moment)
            attempts[code] = max(attempts.get(code, 0), len(bars))
            if not bars:
                continue
            ok, reason = _bars_ready(bars, code, moment)
            if ok:
                candidates.append((bars, origin))
            else:
                rejected[code] = f"{origin}：{reason}"
        if candidates:
            # 同日取更长的那一段（更长历史 → 更多维度可用），不混接。
            bars, origin = max(candidates, key=lambda item: (len(item[0]), item[1] == "市场库·日线"))
            selected[code] = (bars, origin, "cached", None)
        else:
            pending.append((label, code))

    ranges = ["2y", "1y"] if depth == "deep" else ["2y"]

    def _fetch(spec):
        _nm, code = spec
        last_reason = ""
        for rng in ranges:
            try:
                response = providers.fetch_bars(fetch_json, code, rng=rng, timeout=12,
                                                with_source=True)
            except Exception:
                last_reason = f"{rng} 段请求异常"
                continue
            bars = _completed_bars((response or {}).get("bars"), code, now=moment)
            if not bars:
                last_reason = f"{rng} 段未返回可用日线"
                continue
            ok, reason = _bars_ready(bars, code, moment)
            if ok:
                return code, (bars, f"Yahoo/东财·{rng}", "free", (response or {}).get("url")), ""
            last_reason = f"{rng} 段：{reason}"
        prior = attempts.get(code, 0)
        return code, None, (f"库/已有序列不可用（最多 {prior} 根）；"
                            f"免费主备源{last_reason or '无足够新鲜日线'}")

    errors = dict(rejected)      # 本地序列过短 / 过旧的真实原因优先透出来，不被联网状态盖掉
    if pending and fetch_json:
        with ThreadPoolExecutor(max_workers=min(6, len(pending))) as pool:
            for code, record, reason in pool.map(_fetch, pending):
                if record:
                    selected[code] = record
                if reason:
                    errors[code] = reason
    elif pending:
        for _nm, code in pending:          # 变量名不能叫 _label：会遮住模块级 _label() 函数
            errors.setdefault(code, "本次未启用联网取数（离线模式）")

    prepared, missing = [], []
    for label, code in specs:
        record = selected.get(code)
        if not record:
            missing.append({"label": label, "code": code,
                            "reason": errors.get(code) or "日线不可用"})
            continue
        bars, origin, route, url = record
        bench = BENCHMARK_OF.get(code)
        bench_bars = (selected.get(bench) or (None,))[0] if bench else None
        row = prepare_row(bars, label=label, code=code, source=origin,
                          benchmark=bench_bars, extras=extras, now=moment)
        if not row.get("available"):
            missing.append({"label": label, "code": code,
                            "reason": row.get("reason") or "维度不足"})
            continue
        row["data_route"] = route
        row["source_url"] = url
        prepared.append(row)

    # 截面维度（欧奈尔 RS 分位）必须先于裁决：全池就位后再逐行打分。
    note = apply_cross_section(prepared)
    if note:
        warnings.append(note)
    rows = [judge_row(row, school_lock=lock) for row in prepared]
    if db_error:
        warnings.append(db_error + "，改用本次已有日线 / 免费源")
    for row in rows:
        if row.get("stale"):
            warnings.append(f"{row['label']} 收盘日 {row['as_of']} 滞后 "
                            f"{row['lag_days']} 天（门槛 {MAX_LAG_DAYS}）：数字保留、定调降级")

    board = build_board(rows)
    scores = [r["score"] for r in rows if r.get("score") is not None]
    cons_score = round(sum(scores) / len(scores), 1) if scores else None
    bull_n = sum(1 for r in rows if r["mark"] == "▲")
    bear_n = sum(1 for r in rows if r["mark"] == "▼")
    judge_bull = sum(b["bull"] for b in board)
    judge_bear = sum(b["bear"] for b in board)
    lead = (max(rows, key=lambda r: (r["score"] or 0) if r.get("score") is not None else 0)
            if rows else {})
    focus = (max(rows, key=lambda r: abs((r["score"] or 50) - 50)) if rows else {})
    consensus = {
        "score": cons_score, "label": _label(cons_score), "mark": _direction(cons_score),
        "symbol_n": len(rows), "bull_n": bull_n, "bear_n": bear_n,
        "neutral_n": len(rows) - bull_n - bear_n,
        "judge_bull": judge_bull, "judge_bear": judge_bear,
        "judge_neutral": sum(b["neutral"] for b in board),
        "judge_skip": sum(b["skip"] for b in board),
        "divergence": _divergence(judge_bull, judge_bear),
        "lead_symbol": {"label": lead.get("label"), "score": lead.get("score"),
                        "label_dir": lead.get("label_dir")} if lead else {},
        "focus_label": focus.get("label"),
    }
    consensus["divide"] = great_divide(board)
    punch, fluff = punchline(rows, board, consensus) if rows else ("样本不足，本轮不给定调句", False)
    consensus["punchline"] = punch
    if fluff:
        warnings.append("定调句命中禁用话术，已记录并降级为定量句复核")

    dims_available = sum(r["dims"]["available"] for r in rows)
    result = {
        "available": bool(rows),
        "reason": None if rows else (missing[0]["reason"] if missing else "全部标的缺少足够新鲜的已收盘日线"),
        "engine": "UZI-Skill v3.9.4 方法移植（规则引擎 + 覆盖率闸门 + Great Divide + 风险八信号）",
        "parameters": {"schools": len(SCHOOLS), "judges": len(JUDGES), "rules_total": RULE_TOTAL_N,
                       "dims_total": len(DIMENSIONS), "min_bars": MIN_BARS,
                       "max_lag_days": MAX_LAG_DAYS, "bullish": BULLISH_THRESHOLD,
                       "bearish": BEARISH_THRESHOLD, "judge_coverage_floor": MIN_JUDGE_COVERAGE,
                       "depth": depth, "lock": lock or None},
        "school_lock": ({"school": lock, "label": SCHOOLS[lock][0],
                         "members": SCHOOLS[lock][1]} if lock else None),
        "items": rows, "board": board, "consensus": consensus,
        "missing": missing, "warnings": warnings,
        "coverage": {"valid": len(rows), "total": len(specs),
                     "dims": f"{dims_available}/{len(DIMENSIONS) * max(1, len(rows))}"},
        "as_of": min((r["as_of"] for r in rows if r.get("as_of")), default=None),
        "latest_as_of": max((r["as_of"] for r in rows if r.get("as_of")), default=None),
    }
    result["self_check"] = self_check(result)
    return result


# ------------------------------------------------------------------
# 呈现层（只排版，不取数；主题差异由 pipeline 注入的 kit 承担）
# ------------------------------------------------------------------
def _signal_word(signal):
    return {"bullish": "看多", "bearish": "看空", "neutral": "中性", "skip": "跳过"}.get(signal, signal or "—")


def render_jury(result, kit, *, limit=0, plain=False):
    """栏目正文。limit>0 为精简档（只展开重点标的的 N 条裁决）；plain=True 为入门版。"""
    if not result or not result.get("available") or not result.get("items"):
        return ""
    esc = kit.esc
    out = []
    cons = result.get("consensus") or {}
    parameters = result.get("parameters") or {}
    out.append(kit.sub(f"趋势评审团 · {parameters.get('judges', len(JUDGES))} 位方法评委 × "
                       f"{parameters.get('rules_total', RULE_TOTAL_N)} 条量化规则"
                       f"（{parameters.get('schools', len(SCHOOLS))} 个流派）"))

    # SCHOOL LOCK banner（移植上游单一流派视角锁定提示）
    lock = result.get("school_lock")
    if isinstance(lock, dict) and lock.get("school"):
        out.append(kit.kv([(esc("流派锁定"),
                            esc(f"{lock['school']} · {lock.get('label')}｜仅该派评委参与，"
                                f"其余评委记 skip（不代表全体结论）· 代表方法：{lock.get('members', '')}"))]))

    coverage = result.get("coverage") or {}
    score = cons.get("score")
    score_txt = f"{score:.1f}/100 · {cons.get('label')}" if score is not None else "暂缺（维度覆盖不足）"
    rows_kv = [
        ("趋势定调", esc(f"{cons.get('mark', '■')} {score_txt}")),
        ("评委投票", esc(f"看多 {cons.get('judge_bull', 0)} / 看空 {cons.get('judge_bear', 0)} / "
                        f"中性 {cons.get('judge_neutral', 0)} / 跳过 {cons.get('judge_skip', 0)}"
                        f"（标的 {cons.get('bull_n', 0)}▲ / {cons.get('bear_n', 0)}▼ / "
                        f"{cons.get('neutral_n', 0)}■）")),
        ("分歧熵", esc(f"{cons['divergence']:.1f}/100" if cons.get("divergence") is not None else "样本不足")),
        ("数据覆盖", esc(f"标的 {coverage.get('valid', 0)}/{coverage.get('total', 0)} · "
                        f"维度 {coverage.get('dims', '—')} · 收盘日 "
                        f"{result.get('as_of') or '—'}"
                        + (f" ~ {result['latest_as_of']}" if result.get('latest_as_of')
                           and result.get('latest_as_of') != result.get('as_of') else ""))),
    ]
    if cons.get("punchline"):
        rows_kv.append(("一句话定调", esc(cons["punchline"])))
    out.append(kit.kv(rows_kv))

    # 标的 × 定调表
    items = result["items"]
    shown = items[:limit] if limit else items
    table_rows = []
    for row in shown:
        metrics = row.get("metrics") or {}
        color = (kit.bad_color if row["mark"] == "▼"
                 else kit.ok_color if row["mark"] == "▲" else kit.warn_color)
        verdict = f'<span style="color:{color};font-weight:700">{esc(row["label_dir"])}</span>'
        score_cell = f"{row['score']:.1f}" if row.get("score") is not None else "—"
        if row.get("raw_score") is not None and row.get("stale"):
            score_cell += "（原始 {:.1f}·滞后降级）".format(row["raw_score"])
        table_rows.append([
            f"<b>{esc(row['label'])}</b><br>{esc(row['code'])} · {esc(row['as_of'])}",
            score_cell,
            verdict,
            esc(metrics.get("stage") or "—"),
            f"{metrics['ret_20']:+.2f}%" if metrics.get("ret_20") is not None else "—",
            esc(metrics.get("box") or "—"),
            f"{row['counts']['bullish']}▲/{row['counts']['bearish']}▼/{row['counts']['skip']}跳",
        ])
    out.append(kit.table(["标的 / 收盘日", "趋势分", "定调", "阶段", "20日动量", "箱体位置", "评委票型"],
                         table_rows, aligns=("left", "right", "left", "left", "right", "right", "left")))

    # 评委打分板（跨标的平均）
    board_rows = []
    for b in result.get("board") or []:
        avg = f"{b['avg_score']:.1f}" if b.get("avg_score") is not None else "跳过"
        board_rows.append([
            f"{esc(b['school'])} · {esc(b['school_name'])}",
            esc(b["name"]),
            avg,
            f"{b['bull']}▲ / {b['bear']}▼ / {b['neutral']}■ / {b['skip']}跳",
            f"{b['avg_confidence']}" if b.get("avg_confidence") is not None else "—",
        ])
    if board_rows:
        out.append(kit.sub("评委打分板 · 各方法在本池的平均分") + kit.table(
            ["流派", "方法评委", "平均分", "票型（标的数）", "置信度"], board_rows,
            aligns=("left", "left", "right", "left", "right")))

    # 重点标的逐条裁决（Great Divide + 规则明细）
    focus_label = cons.get("focus_label")
    focus = next((r for r in items if r["label"] == focus_label), shown[0] if shown else None)
    if focus:
        out.append(kit.sub(f"重点裁决 · {esc(focus['label'])}（分歧最大）"))
        divide = cons.get("divide") or {}
        if divide:
            out.append(kit.kv([
                ("多空对撞", esc(divide.get("tone") or "—")),
                ("定调句", esc(cons.get("punchline") or "—")),
            ]))
        detail_rows = []
        for judge in focus["judges"]:
            if judge["signal"] == "skip":
                detail_rows.append([esc(judge["name"]), "跳过",
                                    esc(judge.get("reason") or "输入维度缺失")])
                continue
            best = (judge["pass_rules"] or judge["fail_rules"] or [{}])[0]
            word = "✓" if judge["signal"] == "bullish" else ("✗" if judge["signal"] == "bearish" else "≈")
            detail_rows.append([
                f"{word} {esc(judge['name'])}",
                f"{judge['score']:.0f} 分 · 置信 {judge['confidence']}",
                (esc(f"{best.get('name', '')}｜{best.get('msg', '')}"
                     f" · 命中权重 {judge['weight_pass']}/{judge['weight_total']}")
                 if best else "—"),
            ])
        if limit and len(detail_rows) > limit * 4:
            detail_rows = detail_rows[:limit * 4]
        out.append(kit.table(["方法评委", "裁决", "首条证据"], detail_rows))
        if not plain:
            hits, misses = [], []
            for judge in focus["judges"]:
                for rule in judge["pass_rules"]:
                    hits.append([esc(judge["name"]), "✓ " + esc(rule["name"]),
                                 esc(_clip(rule["msg"], 90)), str(rule["weight"])])
                for rule in judge["fail_rules"]:
                    misses.append([esc(judge["name"]), "✗ " + esc(rule["name"]),
                                   esc(_clip(rule["msg"], 90)), str(rule["weight"])])
            if hits:
                out.append(kit.sub("命中规则 · 逐条引用数字") + kit.table(
                    ["方法评委", "规则", "证据", "权重"], hits[:24]))
            if misses:
                out.append(kit.sub("未达规则 · 逐条引用数字") + kit.table(
                    ["方法评委", "规则", "证据", "权重"], misses[:18]))

    # 风险八信号（重点标的）
    if focus:
        risk_rows = []
        for risk in focus.get("risks") or []:
            state = risk["state"]
            color = kit.bad_color if state == "命中" else (kit.warn_color if state == "数据不足" else kit.ok_color)
            risk_rows.append([
                f'<span style="color:{color};font-weight:700">{esc(state)}</span>',
                esc(risk["name"]),
                esc(risk.get("evidence") or "—"),
            ])
        out.append(kit.sub(f"趋势失效风险 · {len(RISK_SIGNALS)} 信号扫描（{esc(focus['label'])}）")
                   + kit.table(["状态", "信号", "证据"], risk_rows))

    # 维度覆盖与缺项（诚实口径）
    dim_rows = []
    for row in shown:
        dims = row.get("dims") or {}
        missing_keys = [DIM_TITLES.get(k, k) for k in (dims.get("missing_keys") or [])]
        dim_rows.append([esc(row["label"]),
                         f"{dims.get('available', 0)}/{dims.get('total', len(DIMENSIONS))}"
                         f"（{dims.get('coverage_pct', 0):.0f}%）",
                         esc("、".join(missing_keys[:6]) + ("…" if len(missing_keys) > 6 else "")
                             if missing_keys else "全维可用")])
    if dim_rows:
        out.append(kit.sub("数据卡覆盖 · 缺维度即 skip，不判负") + kit.table(
            ["标的", "维度覆盖", "缺失维度"], dim_rows, aligns=("left", "right", "left")))

    if plain:
        rules = []
        missing = [f"{r['label']}（{r['reason']}）" for r in result.get("missing") or []]
        if missing:
            rules.append(("暂缺", "、".join(missing)))
        for warning in result.get("warnings") or []:
            rules.append(("数据提醒", warning))
        if rules:
            out.append(kit.kv([(esc(a), esc(b)) for a, b in rules]))
        return "".join(out)

    methodology = [
        ("方法来源", "UZI-Skill v3.9.4（wbh604/UZI-Skill · MIT）：规则引擎裁决 + 数据不足即 skip + "
                    "流派锁定 banner + 数据完整性闸门 + Great Divide + 禁用空泛话术 + 杀猪盘式 8 信号扫描。"),
        ("计算口径", f"每位评委得分 = 命中权重 / 可评权重 ×100；可评权重不足 {MIN_JUDGE_COVERAGE * 100:.0f}% 时整位 skip；"
                    f"≥{BULLISH_THRESHOLD} 看多、<{BEARISH_THRESHOLD} 看空；置信度 = "
                    f"(参与规则数 + 极端度) × 覆盖率折扣；趋势分 = 各评委「可评权重 × 置信度」加权均值。"),
        ("环境维度", "涨跌家数 / 成交额环比 / 板块净强弱 / 流动性分 / 社区与标题多空为市场级读数，"
                    "本池所有标的共用同一数值（不是个股证据），且全部取自日报本次已抓到的同一批实参。"),
        ("数据与限制", f"只用已收盘日线（≥{MIN_BARS} 根；滞后 > {MAX_LAG_DAYS} 个自然日的标的不进评审，"
                    f"在缺项里点名）；"
                       f"整段选源不混接；相对强度只在同市场基准与本池截面内计算；"
                       f"MACD 维度与【六眼飞鱼】栏同参数但独立计算，不并入其信号分。规则口径为技术分析，"
                       f"不含基本面与估值；概率化定调不构成投资建议。"),
    ]
    out.append(kit.sub("方法学与口径") + kit.kv([(esc(a), esc(b)) for a, b in methodology]))
    checks = (result.get("self_check") or {}).get("checks") or []
    if checks:
        out.append(kit.kv([("栏目自检", esc(" · ".join(
            f"{c['name']}{'✅' if c['ok'] else '❌'}" for c in checks))) ]))
    for row in result.get("missing") or []:
        out.append(kit.kv([(esc("缺项 · " + str(row["label"])), esc(row["reason"]))]))
    for warning in result.get("warnings") or []:
        out.append(kit.kv([(esc("数据提醒"), esc(warning))]))
    log = (focus or {}).get("log") or []
    if log:
        out.append(kit.sub("推导链（可审计）") + kit.kv(
            [(esc(_clip(line, 120)), "") for line in log]))
    if len(shown) < len(items):
        out.append(kit.note(f"版面已收起 {len(items) - len(shown)} 个有效标的，--full 查看全部。"))
    return "".join(out)


def _clip(text, n):
    text = str(text or "")
    return text if len(text) <= n else text[: n - 1] + "…"
