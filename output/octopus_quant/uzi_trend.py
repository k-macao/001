#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""【游资剑鱼】多专家流派趋势分析 —— 独立栏目的算法层（2026-10-11 新增）。

方法来自 vendored 的 UZI-Skill 规则引擎（`tools/UZI-Skill`，MIT，上游提交见
`tools/UZI-Skill/UPSTREAM.json`）：66 位评委 × 242 条量化规则 + `evaluate()` 加权打分 +
`panel_summary()` 面板汇总。本栏目**不重写规则**，直接调上游 `lib.investor_evaluator`。

与上游的三处口径差异（都在下面逐条点名，不藏在注释里）：

1. **指标自己算，不装 akshare**。上游指标在 `skills/deep-analysis/scripts/fetch_kline.py::
   compute_indicators`，该文件 import akshare / data_sources（重依赖 + 联网）。本模块按同一
   组公式（EMA / MA / RSI14 / KDJ(9,3,3) / OBV / Williams%R(14) / Weinstein 四阶段 / 年化波动 /
   最大回撤）在本地重算，输入只用**本次已收盘日线**，与 MACD 栏目同一批数据、同一复权口径。
2. **均线不足整窗口就不供值**。上游 `_ma` 用「部分窗口均值」（60 根日线也能算出 MA120），
   本模块要求满窗口（MA120 需 ≥120 根、MA200 需 ≥200 根），不足则该指标缺席。
3. **缺数据 → 规则整条不参与打分**。上游 `evaluate()` 对取不到的特征按 `f.get(key, 默认值)`
   处理，缺失会被当成「不达标」而扣分。本模块先按「规则引用的特征是否全部算得出来」筛掉
   不可评估的规则，再交给上游打分；每个标的披露「参与 N 条 / 未参与 M 条」。

数据侧零新增联网：日线由 `pipeline.fetch_macd_strategy()` 取好后直接传进来
（`run_macd(..., include_bars=True)`），本模块不 fetch、不读市场库。

开关：`OCTOPUS_UZI_TREND=0` 关闭整栏；`OCTOPUS_UZI_SKILL=/path/to/scripts` 指向另一份
UZI-Skill；`OCTOPUS_UZI_PANEL=all` 或 `id1,id2` 调整评委范围；`OCTOPUS_UZI_SYMBOLS`
沿用 MACD 栏目的标的语法（默认与 MACD 同一批 9 只指数）。
"""
from __future__ import annotations

import contextlib
import importlib
import json
import math
import os
import sys
from datetime import datetime
from statistics import mean, stdev

from . import macd_strategy
from . import providers

# 上游规则引擎（vendored）位置：仓库根 / tools / UZI-Skill / skills/deep-analysis/scripts
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_SKILL_SCRIPTS = os.path.join(
    REPO_ROOT, "tools", "UZI-Skill", "skills", "deep-analysis", "scripts")
UPSTREAM_META_FILE = os.path.join(REPO_ROOT, "tools", "UZI-Skill", "UPSTREAM.json")

# 评委默认名单：上游 242 条规则里，**输入全部来自已收盘日线**的只有 37 条 / 28 位评委。
# 这 28 位里，只有下面 5 位的「全部规则」都能用价格数据评估（其余多为游资「Stage 2 才看」
# 的单条前置规则，或用 1 条规则代表一整套方法论，容易误导）：
#   livermore 3 条(权重 11) · minervini 5 条(16) · darvas 2 条(8) · gann 2 条(6) · simons 2 条(5)
DEFAULT_PANEL = ("livermore", "minervini", "darvas", "gann", "simons")
# 评委准入门禁：可评估规则 ≥ MIN_PANEL_RULES 条，且其权重 ≥ 该评委规则总权重 × MIN_COVERAGE。
# 达不到就把这位评委整位撤出面板（并在栏目里点名），绝不用 1 条规则代表一个人的方法论。
MIN_PANEL_RULES = 2
MIN_COVERAGE = 0.5

# 满窗口要求（见模块 docstring 第 2 条）
MA_WINDOWS = (5, 20, 60, 120, 200)
BULL_ALIGN_WINDOW = 120          # 多头排列要比较 MA5>MA10>MA20>MA60>MA120
# Weinstein 四阶段以 MA200 为轴：满窗口 MA200 需 200 根，再要求 ≥20 根 MA200 历史做斜率对比
# （上游固定回看 60 根，但上游 MA 用部分窗口均值、任意长度都有值；本仓库满窗口口径下
#  1 年日线只有约 50 根 MA200 历史，故斜率窗口取 min(60, 可用历史)，下限 20 根）。
STAGE_MIN_BARS = 220
STAGE_SLOPE_MAX, STAGE_SLOPE_MIN = 60, 20
RSI_N, KDJ_N, WR_N = 14, 9, 14
HIGH_LOW_WINDOW = 60             # 距 60 日高 / 低点
VOL_WINDOW = 252                 # 年化波动 / 最大回撤窗口（不足则用全部可用日线）
# 上游 ytd_return 实为「回看 252 根日线的收益」（并非日历年初至今）；本仓库不足 252 根时
# 退化为「回看全部可用日线」，下限 120 根，并在栏目里点名真实窗口，不冒充 YTD。
YTD_MAX_BARS, YTD_MIN_BARS = 252, 120
MIN_BARS = 60                    # 少于 60 根：阶段 / 高低点 / 均线全部无意义，整只缺席
MAX_LAG_DAYS = macd_strategy.MAX_LAG_DAYS

STAGE_LABEL = {0: "阶段未定", 1: "Stage 1 底部", 2: "Stage 2 上升",
               3: "Stage 3 顶部", 4: "Stage 4 下跌"}

_ENGINE = None
_ENGINE_ERROR = None


# ============================================================
# 开关与标的
# ============================================================
def enabled():
    """OCTOPUS_UZI_TREND=0 / --no-uzi-trend 关闭；默认开启（缺规则引擎时栏目自然缺席）。"""
    return str(os.environ.get("OCTOPUS_UZI_TREND", "1")).strip().lower() not in ("0", "false", "no")


def panel_ids(engine=None):
    """评委名单：默认 8 位趋势派；OCTOPUS_UZI_PANEL=all 放开到全部价格类规则可评估的评委。"""
    raw = os.environ.get("OCTOPUS_UZI_PANEL", "").strip()
    engine = engine or load_engine()
    if not raw or raw.lower() in ("default", "trend"):
        return [i for i in DEFAULT_PANEL if engine and i in engine["rules"]]
    if raw.lower() == "all":
        return [inv["id"] for inv in (engine["investors"] if engine else [])
                if engine["rules"].get(inv["id"])]
    wanted = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    return [i for i in wanted if engine and i in engine["rules"]]


def symbol_specs():
    """默认与 MACD 栏目同一批标的（同一批日线、同一次取数），可用 OCTOPUS_UZI_SYMBOLS 覆盖。"""
    raw = os.environ.get("OCTOPUS_UZI_SYMBOLS", "").strip()
    if not raw:
        return list(macd_strategy.symbol_specs())
    with_macd = os.environ.get("OCTOPUS_MACD_SYMBOLS", "")
    os.environ["OCTOPUS_MACD_SYMBOLS"] = raw
    try:
        return macd_strategy.symbol_specs()
    finally:
        if with_macd:
            os.environ["OCTOPUS_MACD_SYMBOLS"] = with_macd
        else:
            os.environ.pop("OCTOPUS_MACD_SYMBOLS", None)


def market_of(code):
    """按本仓库的代码写法判市场（上游 market_router 不认 Yahoo 指数写法，故不用它）。"""
    text = str(code or "").upper()
    if text.endswith(".SS") or text.endswith(".SZ") or text.endswith(".BJ"):
        return "A"
    if text.endswith(".HK") or text in ("^HSI", "^HSTECH", "^HSCEI"):
        return "HK"
    if text.startswith("^") or (text.isalpha() and len(text) <= 5):
        return "US"
    return "A"


# ============================================================
# 上游规则引擎装载（缺文件 / 缺依赖 → 栏目缺席，绝不伪造打分）
# ============================================================
def skill_scripts_dir():
    override = os.environ.get("OCTOPUS_UZI_SKILL", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return DEFAULT_SKILL_SCRIPTS


def upstream_meta():
    try:
        with open(UPSTREAM_META_FILE, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def load_engine(force=False):
    """装载 vendored 规则引擎；返回 None 时调用方整栏缺席。NEVER raises。"""
    global _ENGINE, _ENGINE_ERROR
    if _ENGINE is not None and not force:
        return _ENGINE
    if _ENGINE_ERROR and not force:
        return None
    path = skill_scripts_dir()
    if not os.path.isfile(os.path.join(path, "lib", "investor_evaluator.py")):
        _ENGINE, _ENGINE_ERROR = None, f"未找到 UZI-Skill 规则引擎（{path}）"
        return None
    previous = sys.modules.get("lib")
    if previous is not None and not str(getattr(previous, "__file__", "") or "").startswith(path):
        _ENGINE, _ENGINE_ERROR = None, "进程内已存在同名 lib 包，避免劫持，栏目缺席"
        return None
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        evaluator = importlib.import_module("lib.investor_evaluator")
        criteria = importlib.import_module("lib.investor_criteria")
        db = importlib.import_module("lib.investor_db")
    except Exception as exc:
        _ENGINE, _ENGINE_ERROR = None, f"规则引擎导入失败（{type(exc).__name__}）"
        return None
    meta = upstream_meta()
    _ENGINE = {
        "evaluate": evaluator.evaluate,
        "panel_summary": evaluator.panel_summary,
        "evaluator": evaluator,
        "rules": criteria.INVESTOR_RULES,
        "investors": list(db.INVESTORS),
        "by_id": {inv["id"]: inv for inv in db.INVESTORS},
        "groups": dict(getattr(evaluator, "SCHOOL_LABELS", {})),
        "path": path,
        "commit": meta.get("upstream_commit", ""),
        "upstream": meta.get("upstream_repo", ""),
        "version": meta.get("upstream_version", ""),
    }
    _ENGINE_ERROR = None
    return _ENGINE


def engine_error():
    load_engine()
    return _ENGINE_ERROR


@contextlib.contextmanager
def _restricted_rules(engine, mapping):
    """临时把上游 INVESTOR_RULES 换成「本次可评估」的子集，退出即还原（不改 vendored 文件）。"""
    original = engine["evaluator"].INVESTOR_RULES
    engine["evaluator"].INVESTOR_RULES = mapping
    try:
        yield
    finally:
        engine["evaluator"].INVESTOR_RULES = original


def rule_feature_keys(rule):
    """静态读出规则引用的特征键：check 的字节码里出现的字符串常量即 `f.get("<key>")` 的键。"""
    keys, stack = set(), [getattr(rule.check, "__code__", None)]
    while stack:
        code = stack.pop()
        if code is None:
            continue
        for item in code.co_consts:
            if isinstance(item, str):
                keys.add(item)
            elif hasattr(item, "co_consts"):
                stack.append(item)
    return keys


# ============================================================
# 指标（口径对齐上游 fetch_kline.compute_indicators，满窗口才供值）
# ============================================================
def _ema(values, n):
    factor = 2 / (n + 1)
    out, prev = [], None
    for value in values:
        prev = value if prev is None else value * factor + prev * (1 - factor)
        out.append(prev)
    return out


def _ma(values, n):
    """满窗口简单均线；不足窗口的位置为 None（与上游「部分窗口均值」的差异见 docstring）。"""
    out = []
    for i in range(len(values)):
        out.append(sum(values[i - n + 1:i + 1]) / n if i + 1 >= n else None)
    return out


def _rsi(closes, n=RSI_N):
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_loss = mean(losses[-n:]) or 1e-9
    return 100 - 100 / (1 + mean(gains[-n:]) / avg_loss)


def _kdj(closes, highs, lows, n=KDJ_N):
    if len(closes) < n or any(v is None for v in highs[-n:] + lows[-n:]):
        return None, None, None
    k, d = 50.0, 50.0
    for i in range(n - 1, len(closes)):
        window_high = max(highs[i - n + 1:i + 1])
        window_low = min(lows[i - n + 1:i + 1])
        rsv = (closes[i] - window_low) / (window_high - window_low) * 100 \
            if window_high > window_low else 50.0
        k = 2 / 3 * k + 1 / 3 * rsv
        d = 2 / 3 * d + 1 / 3 * k
    return round(k, 1), round(d, 1), round(3 * k - 2 * d, 1)


def _obv_trend(closes, volumes):
    """OBV 末 20 日方向；成交量整段缺失时返 None（指数常见），不当成「资金流出」。"""
    if len(closes) < 21 or any(v is None for v in volumes[-21:]):
        return None
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + (volumes[i] or 0.0))
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - (volumes[i] or 0.0))
        else:
            obv.append(obv[-1])
    return obv[-1] > obv[-21]


def _williams_r(closes, highs, lows, n=WR_N):
    if len(closes) < n or any(v is None for v in highs[-n:] + lows[-n:]):
        return None
    highest, lowest = max(highs[-n:]), min(lows[-n:])
    if highest <= lowest:
        return -50.0
    return round((highest - closes[-1]) / (highest - lowest) * -100, 1)


def stage_slope_window(bars_n):
    """MA200 斜率对比窗口：min(60, 可用 MA200 历史)，不足 20 根则不给阶段。"""
    history = bars_n - 200 + 1          # 满窗口 MA200 的可用根数
    if history < STAGE_SLOPE_MIN + 1:
        return 0
    return min(STAGE_SLOPE_MAX, history - 1)


def _stage(closes, ma200_series):
    """Weinstein 四阶段：收盘 vs MA200 + MA200 斜率（上游同式，斜率窗口见上）。"""
    lookback = stage_slope_window(len(closes))
    if not lookback or ma200_series[-1] is None or ma200_series[-1 - lookback] is None:
        return None
    above = closes[-1] > ma200_series[-1]
    rising = ma200_series[-1] > ma200_series[-1 - lookback]
    if above and rising:
        return 2
    if not above and rising:
        return 1
    if above and not rising:
        return 3
    return 4


def _lookback_return(closes):
    """回看窗口收益（%）：满 252 根用 252，否则用全部可用日线（≥120 根），窗口如实披露。"""
    if len(closes) <= YTD_MIN_BARS:
        return None
    window = min(YTD_MAX_BARS, len(closes) - 1)
    base = closes[-1 - window]
    return (closes[-1] - base) / base * 100 if base > 0 else None


def _annual_volatility(closes):
    if len(closes) < 20:
        return None
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))
               if closes[i - 1] > 0]
    if len(returns) < 20:
        return None
    try:
        return stdev(returns[-VOL_WINDOW:]) * math.sqrt(252) * 100
    except Exception:
        return None


def _max_drawdown(closes):
    window = closes[-VOL_WINDOW:]
    if len(window) < 20:
        return None
    peak, worst = window[0], 0.0
    for close in window:
        peak = max(peak, close)
        worst = min(worst, (close - peak) / peak)
    return worst * 100


def _series(bars, key):
    values = []
    for bar in bars:
        raw = bar.get(key)
        if isinstance(raw, bool) or raw is None:
            values.append(None)
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            values.append(None)
        else:
            values.append(value if math.isfinite(value) and value > 0 else None)
    return values


def compute_indicators(bars, *, code=""):
    """本地重算上游指标集；算不出来的项一律 None（不用 0 顶替）。"""
    closes = [float(bar["close"]) for bar in bars]
    highs = _series(bars, "high")
    lows = _series(bars, "low")
    volumes = _series(bars, "volume")
    if len(closes) < MIN_BARS:
        return {"available": False, "bars_n": len(closes),
                "reason": f"已收盘日线不足（{len(closes)}/{MIN_BARS} 根）"}

    mas = {n: _ma(closes, n) for n in MA_WINDOWS}
    ma_last = {n: mas[n][-1] for n in MA_WINDOWS}
    ma10 = _ma(closes, 10)[-1]
    dif = [a - b for a, b in zip(_ema(closes, 12), _ema(closes, 26))]
    dea = _ema(dif, 9)
    hist = 2 * (dif[-1] - dea[-1])
    golden = dif[-1] > dea[-1] and dif[-2] <= dea[-2]

    bull_aligned = None
    if len(closes) >= BULL_ALIGN_WINDOW and all(
            v is not None for v in (ma_last[5], ma10, ma_last[20], ma_last[60], ma_last[120])):
        bull_aligned = ma_last[5] > ma10 > ma_last[20] > ma_last[60] > ma_last[120]

    stage = _stage(closes, mas[200])
    k, d, j = _kdj(closes, highs, lows)
    rsi = _rsi(closes)
    williams = _williams_r(closes, highs, lows)

    recent_high = [v for v in highs[-HIGH_LOW_WINDOW:] if v is not None]
    recent_low = [v for v in lows[-HIGH_LOW_WINDOW:] if v is not None]
    pct_high = ((closes[-1] - max(recent_high)) / max(recent_high) * 100
                if len(recent_high) >= HIGH_LOW_WINDOW and max(recent_high) > 0 else None)
    pct_low = ((closes[-1] - min(recent_low)) / min(recent_low) * 100
               if len(recent_low) >= HIGH_LOW_WINDOW and min(recent_low) > 0 else None)

    vol5 = [v for v in volumes[-5:] if v is not None]
    vol20 = [v for v in volumes[-20:] if v is not None]
    macd_label = ("金叉水上" if (golden and dif[-1] > 0) else
                  "死叉水上" if (dif[-1] > 0 and hist < 0) else
                  "水下" if dif[-1] < 0 else "中性")
    return {
        "available": True, "bars_n": len(closes), "as_of": bars[-1]["date"],
        "last_close": closes[-1],
        "ma": {str(n): ma_last[n] for n in MA_WINDOWS},
        "ma_bull_aligned": bull_aligned,
        "ma_align": ("多头排列" if bull_aligned else "非多头") if bull_aligned is not None else None,
        "stage_num": stage, "stage_label": STAGE_LABEL.get(stage or 0, "阶段未定"),
        "macd_dif": dif[-1], "macd_dea": dea[-1], "macd_hist": hist,
        "macd_label": macd_label, "macd_golden_cross": bool(golden and dif[-1] > 0),
        "rsi": rsi, "kdj_k": k, "kdj_d": d, "kdj_j": j,
        "kdj_golden_cross": (k > d) if (k is not None and d is not None) else None,
        "obv_trend_up": _obv_trend(closes, volumes),
        "williams_r": williams,
        "pct_from_60d_high": pct_high, "pct_from_60d_low": pct_low,
        "ytd_return": _lookback_return(closes),
        "ytd_window": (min(YTD_MAX_BARS, len(closes) - 1) if len(closes) > YTD_MIN_BARS else None),
        "volatility_1y": _annual_volatility(closes),
        "max_drawdown_1y": _max_drawdown(closes),
        "vol_5_vs_20": (mean(vol5) / mean(vol20)) if (len(vol5) == 5 and len(vol20) == 20
                                                      and mean(vol20) > 0) else None,
        "volume_available": len(vol20) == 20,
    }


def build_features(ind, *, label, code):
    """指标 → 上游 features 键名；**只放算得出来的键**（缺失键让规则整条出局）。"""
    features = {"market": market_of(code), "ticker": code, "name": label, "industry": "指数"}

    def put(key, value):
        if value is not None and not (isinstance(value, float) and not math.isfinite(value)):
            features[key] = value

    put("stage", ind.get("stage_label"))
    put("stage_num", ind.get("stage_num"))
    put("ma_align", ind.get("ma_align"))
    put("ma_bull_aligned", ind.get("ma_bull_aligned"))
    put("macd", ind.get("macd_label"))
    put("macd_golden_cross", ind.get("macd_golden_cross"))
    put("rsi", ind.get("rsi"))
    put("kdj_k", ind.get("kdj_k"))
    put("kdj_d", ind.get("kdj_d"))
    put("kdj_j", ind.get("kdj_j"))
    put("kdj_golden_cross", ind.get("kdj_golden_cross"))
    put("obv_trend_up", ind.get("obv_trend_up"))
    put("williams_r", ind.get("williams_r"))
    put("ytd_return", ind.get("ytd_return"))
    put("volatility_1y", ind.get("volatility_1y"))
    put("max_drawdown_1y", ind.get("max_drawdown_1y"))
    put("pct_from_60d_high", ind.get("pct_from_60d_high"))
    put("pct_from_60d_low", ind.get("pct_from_60d_low"))
    if features.get("rsi") is not None:
        features["rsi_overbought"] = features["rsi"] > 70
        features["rsi_oversold"] = features["rsi"] < 30
    if features.get("williams_r") is not None:
        features["williams_overbought"] = features["williams_r"] > -20
        features["williams_oversold"] = features["williams_r"] < -80
    return features


# ============================================================
# 评委打分（调上游 evaluate；不可评估的规则先出局）
# ============================================================
def rule_evaluable(rule, features):
    """该规则引用的特征本次是否全部算得出来（算不出来 → 整条不参与打分）。"""
    keys = rule_feature_keys(rule)
    return bool(keys) and all(key in features for key in keys)


def coverage_gate():
    """准入门禁可放宽：OCTOPUS_UZI_MIN_COVERAGE=0 + OCTOPUS_UZI_PANEL=all 看全部价格类规则。"""
    try:
        ratio = float(os.environ.get("OCTOPUS_UZI_MIN_COVERAGE", "") or MIN_COVERAGE)
    except ValueError:
        ratio = MIN_COVERAGE
    return max(0.0, min(1.0, ratio))


def evaluate_panel(features, engine, ids):
    """逐评委打分。返回 (rows, coverage, dropped)。

    coverage —— 进面板的评委：{id: {"rules": n, "weight_ok": w, "weight_all": w, "names": […]}}
    dropped  —— 被门禁撤下的评委：{id: "可评估 1/4 条（权重 3/17 = 18%）"}
    规则可评估性按「该规则引用的特征本次是否全部算得出来」判定；算不出来的规则整条出局，
    不以缺失值顶替后判「不达标」。
    """
    usable, coverage, dropped = {}, {}, {}
    gate = coverage_gate()
    for investor_id in ids:
        rules = engine["rules"].get(investor_id) or []
        keep = [rule for rule in rules if rule_evaluable(rule, features)]
        weight_ok = sum(rule.weight for rule in keep)
        weight_all = sum(rule.weight for rule in rules) or 1
        ratio = weight_ok / weight_all
        if len(keep) >= MIN_PANEL_RULES and ratio >= gate:
            usable[investor_id] = keep
            coverage[investor_id] = {"rules": len(keep), "rules_all": len(rules),
                                     "weight_ok": weight_ok, "weight_all": weight_all,
                                     "ratio": round(ratio * 100),
                                     "names": [rule.name for rule in keep]}
        else:
            dropped[investor_id] = (f"可评估 {len(keep)}/{len(rules)} 条"
                                    f"（权重 {weight_ok}/{weight_all} = {ratio * 100:.0f}%）")
    if not usable:
        return [], coverage, dropped

    with _restricted_rules(engine, usable):
        results = {investor_id: engine["evaluate"](investor_id, features)
                   for investor_id in usable}

    rows = []
    for investor_id, result in results.items():
        if result.get("signal") == "skip" or result.get("skip_reason"):
            dropped[investor_id] = result.get("skip_reason") or "评委不适用"
            coverage.pop(investor_id, None)
            continue
        profile = engine["by_id"].get(investor_id, {})
        rows.append({
            "id": investor_id,
            "name": profile.get("name") or investor_id,
            "group": profile.get("group") or "",
            "school": engine["groups"].get(profile.get("group") or "", ""),
            "score": result.get("score"),
            "signal": result.get("signal"),
            "headline": result.get("headline") or "",
            "weight_pass": result.get("weight_pass", 0),
            "weight_total": result.get("weight_total", 0),
            "rules_n": coverage[investor_id]["rules"],
            "rule_names": list(coverage[investor_id]["names"]),
            "coverage": f"{coverage[investor_id]['rules']}/{coverage[investor_id]['rules_all']} 条"
                        f"（权重 {coverage[investor_id]['ratio']}%）",
            "pass_rules": [item["msg"] for item in result.get("pass_rules") or []],
            "fail_rules": [item["msg"] for item in result.get("fail_rules") or []],
            "time_horizon": result.get("time_horizon") or "",
            "change_mind": result.get("what_would_change_my_mind") or "",
        })
    rows.sort(key=lambda row: -(row["score"] or 0))
    return rows, coverage, dropped


def _verdict(ind, rows, bars_n=0):
    """趋势定调：上游阶段判断为主，评委面板一致性为辅（规则合成，可复现）。"""
    stage = ind.get("stage_num")
    bullish = sum(1 for row in rows if row["signal"] == "bullish")
    bearish = sum(1 for row in rows if row["signal"] == "bearish")
    total = len(rows) or 1
    if stage == 2:
        if bullish / total >= 0.6:
            return "up", "多头趋势成立", f"Stage 2 上升 · {bullish}/{len(rows)} 位评委看多"
        return "mixed", "上升但分歧", f"Stage 2 上升 · 看多 {bullish} / 看空 {bearish}"
    if stage == 1:
        return "base", "底部构筑", f"Stage 1 底部 · 看多 {bullish} / 看空 {bearish}"
    if stage == 3:
        return "top", "高位转弱", f"Stage 3 顶部 · 看空 {bearish}/{len(rows)}"
    if stage == 4:
        return "down", "空头趋势", f"Stage 4 下跌 · 看空 {bearish}/{len(rows)}"
    return ("unknown", "阶段未定",
            f"日线 {bars_n} 根 < {STAGE_MIN_BARS} 根，MA200 斜率窗口不足，不定调")


def analyze_symbol(bars, *, label, code, source="本次已收盘日线", now=None):
    """单标的：日线 → 指标 → 评委面板 → 定调。不联网。"""
    moment = now or datetime.now(providers.CST)
    clean = macd_strategy.completed_bars(bars, code, now=moment)
    if len(clean) < MIN_BARS:
        return {"available": False, "label": label, "code": code, "bars_n": len(clean),
                "reason": f"已收盘日线不足（{len(clean)}/{MIN_BARS} 根）"}
    if not providers.is_session_closed(code, clean[-1]["date"], now=moment):
        return {"available": False, "label": label, "code": code, "bars_n": len(clean),
                "reason": f"最新日线未收盘（{clean[-1]['date']}）"}
    ind = compute_indicators(clean, code=code)
    if not ind.get("available"):
        return {"available": False, "label": label, "code": code,
                "bars_n": ind.get("bars_n", 0), "reason": ind.get("reason")}

    engine = load_engine()
    if not engine:
        return {"available": False, "label": label, "code": code, "bars_n": len(clean),
                "reason": engine_error() or "规则引擎不可用"}

    features = build_features(ind, label=label, code=code)
    rows, coverage, dropped = evaluate_panel(features, engine, panel_ids(engine))
    if not rows:
        detail = "；".join(f"{engine['by_id'].get(k, {}).get('name', k)}：{v}"
                          for k, v in dropped.items())
        return {"available": False, "label": label, "code": code, "bars_n": len(clean),
                "reason": f"评委全部未过准入门禁（{detail}）" if detail
                          else "价格类规则全部因数据不足出局",
                "indicators": ind, "dropped": dropped}
    tone_key, tone, tone_detail = _verdict(ind, rows, bars_n=ind["bars_n"])
    scores = [row["score"] for row in rows if row["score"] is not None]
    return {
        "available": True, "label": label, "code": code, "market": market_of(code),
        "as_of": ind["as_of"], "bars_n": ind["bars_n"], "source": source,
        "indicators": ind, "panel": rows,
        "coverage": coverage,
        "dropped": {engine["by_id"].get(k, {}).get("name", k): v for k, v in dropped.items()},
        "rules_used": sum(item["rules"] for item in coverage.values()),
        "rules_dropped": sum(len(engine["rules"].get(k) or []) for k in dropped),
        "weight_ok": sum(item["weight_ok"] for item in coverage.values()),
        "weight_all": sum(item["weight_all"] for item in coverage.values()),
        "score_avg": round(sum(scores) / len(scores), 1) if scores else None,
        "bullish_n": sum(1 for row in rows if row["signal"] == "bullish"),
        "bearish_n": sum(1 for row in rows if row["signal"] == "bearish"),
        "neutral_n": sum(1 for row in rows if row["signal"] == "neutral"),
        "tone_key": tone_key, "tone": tone, "tone_detail": tone_detail,
    }


def run_trend(bars_by_code, *, specs=None, now=None):
    """编排入口。bars_by_code 由 MACD 栏目取好的日线直接传入（本模块不取数）。"""
    moment = now or datetime.now(providers.CST)
    specs = list(specs) if specs is not None else symbol_specs()
    engine = load_engine()
    if not engine:
        return {"available": False, "reason": engine_error() or "UZI-Skill 规则引擎不可用",
                "engine": None, "items": [], "missing": [],
                "coverage": {"valid": 0, "total": len(specs)}}

    bars_by_code = bars_by_code or {}
    items, missing = [], []
    for label, code in specs:
        bars = bars_by_code.get(code)
        if not bars:
            missing.append({"label": label, "code": code, "reason": "本次没有可用已收盘日线"})
            continue
        row = analyze_symbol(bars, label=label, code=code, now=moment)
        (items if row.get("available") else missing).append(row)

    if not items:
        return {"available": False, "engine": _engine_info(engine), "items": [],
                "missing": missing, "coverage": {"valid": 0, "total": len(specs)},
                "reason": "全部标的缺少足够新鲜的已收盘日线"}

    dates = sorted({row["as_of"] for row in items})
    panel_rows = [row for item in items for row in item["panel"]]
    scores = [row["score"] for row in panel_rows if row["score"] is not None]
    return {
        "available": True, "reason": None, "engine": _engine_info(engine),
        "items": items, "missing": missing,
        "coverage": {"valid": len(items), "total": len(specs)},
        "as_of": dates[0], "latest_as_of": dates[-1],
        "rules_enabled": len({(row["id"], name) for item in items
                              for row in item["panel"] for name in row["rule_names"]}),
        "rules_total": sum(len(v) for v in engine["rules"].values()),
        "dropped": {name: reason for item in items
                    for name, reason in (item.get("dropped") or {}).items()},
        "panel": {
            "investors": len({row["id"] for row in panel_rows}),
            "bullish": sum(1 for row in panel_rows if row["signal"] == "bullish"),
            "bearish": sum(1 for row in panel_rows if row["signal"] == "bearish"),
            "neutral": sum(1 for row in panel_rows if row["signal"] == "neutral"),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        },
        "tones": {key: sum(1 for item in items if item["tone_key"] == key)
                  for key in ("up", "mixed", "base", "top", "down", "unknown")},
    }


def _engine_info(engine):
    return {
        "path": engine["path"], "commit": engine["commit"], "upstream": engine["upstream"],
        "version": engine["version"], "investors_total": len(engine["investors"]),
        "rules_total": sum(len(v) for v in engine["rules"].values()),
        "panel": [engine["by_id"].get(i, {}).get("name", i) for i in panel_ids(engine)],
    }


# ============================================================
# 呈现（注入主题套件，与 macd_strategy.render_strategy 同一套口径）
# ============================================================
SIGNAL_WORD = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}


def _pct(value, digits=1, signed=True):
    if value is None:
        return "—"
    return f"{value:+.{digits}f}%" if signed else f"{value:.{digits}f}%"


def missing_summary(missing, max_names=4):
    """暂缺行按原因归并：同一原因只点名一次，标的多于上限时给出总数（不静默丢）。"""
    groups = {}
    for row in missing:
        groups.setdefault(row.get("reason") or "日线不可用", []).append(row.get("label") or row.get("code") or "?")
    parts = []
    for reason, labels in groups.items():
        names = "、".join(labels[:max_names]) + (f" 等 {len(labels)} 只" if len(labels) > max_names else "")
        parts.append(f"{names}（{reason}）")
    return "；".join(parts)


def _ma_text(ind):
    """MA20 / MA60 / MA200 一行：缺席的窗口直接点名，不用 0 或 nan 顶替。"""
    parts = []
    for label, key in (("MA20", "20"), ("MA60", "60"), ("MA200", "200")):
        value = (ind.get("ma") or {}).get(key)
        parts.append(f"{label} {value:,.2f}" if value else f"{label} 缺席")
    return " · ".join(parts)


def render_trend(result, kit, *, limit=0, plain=False):
    """渲染独立栏目。plain=True（入门版）只留结论表 + 定调 + 缺项；口径 / 规则明细不出。"""
    if not result or not result.get("available") or not result.get("items"):
        return ""
    esc = kit.esc
    items = result["items"]
    shown = items[:limit] if limit else items
    engine = result.get("engine") or {}
    panel = result.get("panel") or {}

    out = [kit.sub("多专家流派趋势分析 · 已收盘日线")]
    out.append(kit.kv([(
        "面板 / 定调",
        esc(f"{panel.get('investors', 0)} 位评委 × {result.get('rules_enabled', 0)} 条价格类规则 · "
            f"看多 {panel.get('bullish', 0)} / 中性 {panel.get('neutral', 0)} / 看空 {panel.get('bearish', 0)}"
            + (f" · 均分 {panel['avg_score']}" if panel.get("avg_score") is not None else "")
            + f" · 收盘日 {result['as_of']}~{result['latest_as_of']}"))]))

    rows = []
    for row in shown:
        ind = row["indicators"]
        tone_color = {"up": kit.ok_color, "mixed": kit.warn_color, "base": kit.warn_color,
                      "top": kit.warn_color, "down": kit.bad_color}.get(row["tone_key"], kit.warn_color)
        position = ("—" if ind.get("pct_from_60d_high") is None
                    else f"距60日高 {ind['pct_from_60d_high']:+.1f}%")
        ytd = ("—" if ind.get("ytd_return") is None
               else f"近{ind.get('ytd_window')}日 {ind['ytd_return']:+.1f}%")
        rows.append([
            f"<b>{esc(row['label'])}</b><br>{esc(row['code'])}<br>{esc(row['as_of'])} · {row['bars_n']} 根",
            f"<b>{esc(ind.get('stage_label') or '阶段未定')}</b><br>"
            f"{esc(ind.get('ma_align') or '均线样本不足')}",
            (f"RSI {ind['rsi']:.0f}" if ind.get("rsi") is not None else "RSI —") + "<br>"
            + (f"KDJ(J) {ind['kdj_j']:.0f}" if ind.get("kdj_j") is not None else "KDJ —") + "<br>"
            + (f"WR {ind['williams_r']:.0f}" if ind.get("williams_r") is not None else "WR —"),
            f"{ytd}<br>{position}<br>年化波动 {_pct(ind.get('volatility_1y'), signed=False)}",
            (f"{row['bullish_n']}多/{row['neutral_n']}中/{row['bearish_n']}空<br>"
             + (f"均分 {row['score_avg']}" if row["score_avg"] is not None else "")
             + f"<br>{len(row['panel'])} 位评委"),
            f'<span style="color:{tone_color};font-weight:700">{esc(row["tone"])}</span><br>'
            f'{esc(row["tone_detail"])}',
        ])
    out.append(kit.table(
        ["标的 / 收盘日", "阶段 / 均线", "RSI / KDJ / WR", "区间收益 / 位置 / 波动", "评委面板", "趋势定调"],
        rows, aligns=("left", "left", "right", "right", "right", "left")))

    if plain:
        # 入门版：每只标的一行「谁最看多 / 最看空 + 为什么」，口径与规则明细整段不出。
        lines = []
        for row in shown:
            if not row["panel"]:
                continue
            top = row["panel"][0]
            lines.append(f"{row['label']}：{top['name']} {top['score']} 分"
                         f"（{SIGNAL_WORD.get(top['signal'], '中性')}）· {top['headline']}")
        if lines:
            out.append(kit.kv([("评委结论", esc(" ｜ ".join(lines)))]))
        notes = [("定调", esc("；".join(f"{row['label']} {row['tone']}" for row in shown)))]
        if len(shown) < len(items):
            notes.append(("版面收起", esc(f"已收起 {len(items) - len(shown)} 个有效标的，--full 查看全部。")))
        grouped = missing_summary(result.get("missing") or [])
        if grouped:
            notes.append(("暂缺", esc(grouped)))
        notes.append(("口径", esc("只统计已收盘日线；规则输入全部来自价格，缺数据的规则不参与打分。")))
        out.append(kit.kv(notes))
        return "".join(out)

    # 全量版：逐标的披露指标、逐评委命中 / 未达、规则覆盖与被门禁撤下的评委。
    for row in shown:
        ind = row["indicators"]
        detail = [(esc(f"{row['label']} · 指标"),
                   esc(f"收盘 {ind['last_close']:,.2f} · {_ma_text(ind)}"
                       f" · MACD {ind['macd_label']}（柱 {ind['macd_hist']:+.4f}）"
                       f" · OBV {'向上' if ind.get('obv_trend_up') else '向下' if ind.get('obv_trend_up') is False else '成交量缺席'}"
                       f" · 供数 {row['source']}"))]
        for judge in row["panel"]:
            detail.append((esc(f"{judge['name']}（{judge['school'] or judge['group']}）"
                               f"{judge['score']} 分 · {SIGNAL_WORD.get(judge['signal'], '中性')}"),
                           esc(f"命中：{'；'.join(judge['pass_rules']) or '无'}"
                               f" ｜ 未达：{'；'.join(judge['fail_rules']) or '无'}")))
        cover = (f"参与 {row['rules_used']} 条（权重 {row['weight_ok']}/{row['weight_all']}）"
                 f" · {len(row['panel'])} 位评委进面板")
        if row.get("dropped"):
            cover += "（撤下：" + "；".join(f"{k} {v}" for k, v in row["dropped"].items()) + "）"
        detail.append((esc(f"{row['label']} · 规则覆盖"), esc(cover)))
        out.append(kit.kv(detail))

    profiles = {}
    for row in shown:
        for judge in row["panel"]:
            profiles.setdefault(judge["name"], judge)
    if profiles:
        out.append(kit.sub("评委档案 · 持仓周期与翻盘条件（上游口径）"))
        out.append(kit.kv([
            (esc(name), esc(f"周期 {judge['time_horizon'] or '—'} ｜ 翻盘条件 {judge['change_mind'] or '—'}"))
            for name, judge in profiles.items()]))

    notes = [
        ("方法来源", f"规则引擎 vendored 自 UZI-Skill（{engine.get('upstream', '')}"
                     f"{(' · ' + engine['commit'][:10]) if engine.get('commit') else ''}"
                     f"{(' · ' + engine['version']) if engine.get('version') else ''} · MIT）；"
                     f"本栏目直接调用其 evaluate()，不重写规则。"),
        ("启用范围", f"上游 {engine.get('investors_total', 0)} 位评委 / {result.get('rules_total', 0)} 条规则中，"
                     f"本次启用 {panel.get('investors', 0)} 位评委的 {result.get('rules_enabled', 0)} 条"
                     f"「输入全部来自已收盘日线」的规则；准入门禁 = 可评估规则 ≥{MIN_PANEL_RULES} 条"
                     f"且权重占比 ≥{MIN_COVERAGE * 100:.0f}%，达不到就把这位评委整位撤下（见逐标的「规则覆盖」行）。"
                     f"其余规则依赖财报 / 估值 / 资金 / 舆情等本栏目不采集的数据，一律不参与打分"
                     f"（不用缺失值冒充中性）。"),
        ("指标口径", f"EMA/MA、RSI{RSI_N}、KDJ({KDJ_N},3,3)、OBV、Williams%R({WR_N})、Weinstein 四阶段与年化波动"
                     f"按上游 fetch_kline.compute_indicators 同式本地重算；均线要求满窗口"
                     f"（多头排列需 ≥{BULL_ALIGN_WINDOW} 根、阶段需 ≥{STAGE_MIN_BARS} 根且 MA200 斜率窗口 "
                     f"min({STAGE_SLOPE_MAX}, 可用历史) ≥{STAGE_SLOPE_MIN} 根），不足则该指标缺席。"
                     f"区间收益按上游 ytd_return 口径回看 {YTD_MAX_BARS} 根，不足则回看全部可用日线"
                     f"（≥{YTD_MIN_BARS} 根）并点名真实窗口。KDJ / OBV / Williams%R / MACD 是同口径展示项，"
                     f"上游规则未引用它们，不参与打分。"),
        ("数据边界", f"日线复用 MACD 栏目同一批（零新增联网），排除未收盘日线，滞后超过 {MAX_LAG_DAYS} 天不发信号；"
                     f"指数无成交量时 OBV 整项缺席。评委打分是规则合成的研究口径，不含交易成本，"
                     f"不构成投资建议。"),
    ]
    if len(shown) < len(items):
        notes.append(("版面收起", f"已收起 {len(items) - len(shown)} 个有效标的，--full 查看全部。"))
    grouped = missing_summary(result.get("missing") or [], max_names=12)
    if grouped:
        notes.append(("缺项", grouped))
    out.append(kit.kv([(esc(label), esc(text)) for label, text in notes]))
    return "".join(out)
