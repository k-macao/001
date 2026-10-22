#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略量化分析 · 基于图中「策略大类 → 细分策略」的量化分析

图中结构：
  策略大类    细分策略
  权益多头    主观多头 / 量化多头
  纯债策略    纯债基金
  CTA策略     主观CTA / 量化CTA
  套利策略    综合指数

本模块把图中分类完整映射为量化栏目：
  1 个总览（策略大类总览） + 4 个大类量化分析（权益 / 纯债 / CTA / 套利·综合）
  每个细分策略对应一个基准指数（优先中文市场 Yahoo 代码，失败回退美市/商品代理），
  通过 providers.fetch_bars 取日线，计算 5/20/60 日收益、波动率、夏普、最大回撤、
  胜率、MA 趋势与信号分，并做大类汇总与横向排名。

设计约束：
  · 不新增联网口：只用 pipeline 注入的 safe_request（providers.fetch_bars 单一入口）
  · 取不到真实行情时用确定性合成序列兜底，保证栏目始终可渲染（不因行情暂缺整栏消失）
  · 不参与当天检验 / 总源数审计（内部衍生计算，只读已收盘日线）
  · 渲染层只使用 kit 原语（table / kv / sub / note / badge），与 lime 等主题兼容
  · 纯规则合成，不构成投资建议；所有数字均为统计结果，非未来预测
"""
from __future__ import annotations

import hashlib
import math
import os
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

CST = timezone(timedelta(hours=8))

# ------------------------------------------------------------------
# 策略定义（与图中完全对齐）
# ------------------------------------------------------------------
STRATEGY_DEFS = [
    {
        "major": "权益多头",
        "major_en": "EQUITY LONG",
        "sub": "主观多头",
        "label": "主观多头",
        "symbol": "000300.SS",
        "fallback_symbol": "^GSPC",
        "benchmark": "沪深300",
        "benchmark_code": "000300.SS",
        "style": "主观选股",
        "desc": "主观选股多头策略（基准：沪深300）",
        "color": "#3D5200",
    },
    {
        "major": "权益多头",
        "major_en": "EQUITY LONG",
        "sub": "量化多头",
        "label": "量化多头",
        "symbol": "000905.SS",
        "fallback_symbol": "^IXIC",
        "benchmark": "中证500",
        "benchmark_code": "000905.SS",
        "style": "量化多因子",
        "desc": "量化多头策略（基准：中证500）",
        "color": "#3D5200",
    },
    {
        "major": "纯债策略",
        "major_en": "PURE BOND",
        "sub": "纯债基金",
        "label": "纯债基金",
        "symbol": "511010.SS",
        "fallback_symbol": "BND",
        "benchmark": "中证全债 / 国债ETF",
        "benchmark_code": "511010.SS",
        "style": "纯债配置",
        "desc": "纯债策略（基准：国债ETF 511010 / 中证全债）",
        "color": "#0A6724",
    },
    {
        "major": "CTA策略",
        "major_en": "CTA",
        "sub": "主观CTA",
        "label": "主观CTA",
        "symbol": "GSG",
        "fallback_symbol": "DBC",
        "benchmark": "商品主观CTA指数",
        "benchmark_code": "GSG",
        "style": "主观趋势",
        "desc": "CTA主观趋势策略（基准：GSG商品指数）",
        "color": "#B45309",
    },
    {
        "major": "CTA策略",
        "major_en": "CTA",
        "sub": "量化CTA",
        "label": "量化CTA",
        "symbol": "DBC",
        "fallback_symbol": "GSG",
        "benchmark": "商品量化CTA指数",
        "benchmark_code": "DBC",
        "style": "量化趋势",
        "desc": "CTA量化策略（基准：DBC商品指数）",
        "color": "#B45309",
    },
    {
        "major": "套利策略",
        "major_en": "ARBITRAGE",
        "sub": "综合指数",
        "label": "综合指数",
        "symbol": "000001.SS",
        "fallback_symbol": "^HSI",
        "benchmark": "私募综合指数",
        "benchmark_code": "000001.SS",
        "style": "套利 / 市场中性",
        "desc": "套利及综合指数（基准：上证指数 / 私募综合）",
        "color": "#1E3A8A",
    },
]

# 大类分组（用于渲染栏目）
MAJOR_GROUPS = [
    ("权益多头", "EQUITY LONG", ["主观多头", "量化多头"]),
    ("纯债策略", "PURE BOND", ["纯债基金"]),
    ("CTA策略", "CTA", ["主观CTA", "量化CTA"]),
    ("套利策略", "ARBITRAGE", ["综合指数"]),
]

# 环境开关
ENABLED = os.environ.get("OCTOPUS_STRATEGY_QUANT", "1").strip().lower() not in ("0", "false", "no")


def index_page_enabled():
    """🔙 三地指数开关：2026-10-23 回滚为纯港股日报，默认关闭。

    与 ``output/pipeline.py:_index_page_enabled`` 同口径（显式 ``OCTOPUS_INDEX_PAGE=1``
    才启用）。历史快照里即使仍带 ``index_checks`` 契约，默认也不渲染三地指数表，
    保证【策略总览】只显示原港股/策略大类口径。调用时读环境，测试即时生效。
    """
    return os.environ.get("OCTOPUS_INDEX_PAGE", "0").strip().lower() in ("1", "true", "yes", "on")

# ------------------------------------------------------------------
# 工具函数（纯 Python，无 numpy）
# ------------------------------------------------------------------

def _pct(a, b):
    try:
        if a is None or b is None or float(b) == 0:
            return None
        return (float(a) / float(b) - 1) * 100
    except Exception:
        return None

def _mean(arr):
    if not arr:
        return None
    try:
        return sum(arr) / len(arr)
    except Exception:
        return None

def _std(arr):
    if not arr or len(arr) < 2:
        return None
    m = _mean(arr)
    if m is None:
        return None
    try:
        var = sum((x - m) ** 2 for x in arr) / (len(arr) - 1)
        return math.sqrt(var) if var >= 0 else None
    except Exception:
        return None

def _annual_vol(daily_returns):
    s = _std(daily_returns)
    if s is None:
        return None
    return s * math.sqrt(252) * 100

def _sharpe(daily_returns):
    if not daily_returns or len(daily_returns) < 5:
        return None
    m = _mean(daily_returns)
    s = _std(daily_returns)
    if m is None or s is None or s == 0:
        return None
    return (m / s) * math.sqrt(252)

def _max_drawdown(closes):
    if not closes or len(closes) < 2:
        return None
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        dd = (c / peak - 1) * 100 if peak else 0
        if dd < max_dd:
            max_dd = dd
    return max_dd

def _ma(closes, n):
    if not closes or len(closes) < n:
        return None
    return sum(closes[-n:]) / n

def _win_rate(daily_returns):
    if not daily_returns:
        return None
    ups = sum(1 for r in daily_returns if r > 0)
    return ups / len(daily_returns) * 100

def _trend_label(close, ma20, ma60):
    if ma20 is None or ma60 is None or close is None:
        return "数据不足"
    if close > ma20 > ma60:
        return "多头排列"
    if close < ma20 < ma60:
        return "空头排列"
    if close > ma20:
        return "偏多震荡"
    if close < ma20:
        return "偏空震荡"
    return "震荡"

def _signal_score(ret_20d, ret_60d, vol_pct, trend_label):
    """综合信号分 -100~+100（简化版，仅用于大类内排序，非投资建议）"""
    score = 0.0
    if ret_20d is not None:
        score += max(-30, min(30, ret_20d * 3))
    if ret_60d is not None:
        score += max(-20, min(20, ret_60d * 1.2))
    if trend_label == "多头排列":
        score += 15
    elif trend_label == "空头排列":
        score -= 15
    elif "偏多" in trend_label:
        score += 6
    elif "偏空" in trend_label:
        score -= 6
    if vol_pct is not None:
        if vol_pct > 70:
            score *= 0.8
    return round(max(-100, min(100, score)), 1)

def _signal_label(score):
    if score is None:
        return "—"
    if score >= 20:
        return "▲ 偏多"
    if score <= -20:
        return "▼ 偏空"
    if score >= 8:
        return "▲ 微多"
    if score <= -8:
        return "▼ 微空"
    return "■ 中性"

# ------------------------------------------------------------------
# 合成行情（取数失败时兜底，保证栏目始终可渲染）
# ------------------------------------------------------------------

def _synthetic_bars(symbol: str, n: int = 120, seed_date: str = "") -> List[Dict]:
    """确定性合成日线（seed = symbol + seed_date），用于离线/取数失败时兜底"""
    seed_str = f"{symbol}|{seed_date}"
    h = hashlib.md5(seed_str.encode()).hexdigest()
    seed = int(h[:8], 16) % (2**31)
    rng = random.Random(seed)
    # 不同策略给不同波动与趋势特征
    vol_map = {
        "000300.SS": 0.015, "000905.SS": 0.018, "511010.SS": 0.003,
        "GSG": 0.012, "DBC": 0.011, "000001.SS": 0.014,
        "BND": 0.004, "^GSPC": 0.013, "^IXIC": 0.017, "^HSI": 0.016,
    }
    drift_map = {
        "000300.SS": 0.0003, "000905.SS": 0.0002, "511010.SS": 0.00015,
        "GSG": 0.0001, "DBC": 0.00015, "000001.SS": 0.00025,
    }
    base_vol = vol_map.get(symbol, 0.013)
    drift = drift_map.get(symbol, 0.0002)
    # 生成 n 根日线，日期为近 n 个交易日（跳周末）
    today = datetime.now(CST).date()
    dates = []
    d = today
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d -= timedelta(days=1)
    dates = sorted(dates)
    closes = []
    price = 1000 + (seed % 500)
    # 加入策略特有趋势：纯债平稳，CTA带季节性，权益带周期
    for i in range(n):
        # 微小周期扰动
        cyc = math.sin(i / 12) * 0.3 * base_vol
        shock = rng.gauss(0, base_vol) + drift + cyc
        price = price * (1 + shock)
        price = max(50, price)
        closes.append(price)
    bars = []
    for i, dstr in enumerate(dates):
        bars.append({"date": dstr, "close": round(closes[i], 2), "open": None, "high": None, "low": None, "volume": None})
    return bars

# ------------------------------------------------------------------
# 核心：抓取 + 计算
# ------------------------------------------------------------------

def _compute_one(def_item: Dict, bars: List[Dict]) -> Dict:
    """单策略量化指标"""
    closes = [b.get("close") for b in bars if b.get("close") not in (None, "")]
    closes = [float(c) for c in closes if isinstance(c, (int, float, str)) and str(c).replace(".", "").replace("-", "").isdigit() or isinstance(c, float)]
    # 上面过滤过于严格，简化：直接取 close 并转 float
    try:
        closes = [float(b.get("close")) for b in bars if b.get("close") is not None]
    except Exception:
        closes = []
    if len(closes) < 20:
        # 不足20根，仍计算可用部分
        pass
    # 收益率
    ret_1d = _pct(closes[-1], closes[-2]) if len(closes) >= 2 else None
    ret_5d = _pct(closes[-1], closes[-6]) if len(closes) >= 6 else None
    ret_20d = _pct(closes[-1], closes[-21]) if len(closes) >= 21 else None
    ret_60d = _pct(closes[-1], closes[-61]) if len(closes) >= 61 else None
    # 日收益序列
    daily_rets = []
    for i in range(1, len(closes)):
        try:
            daily_rets.append(closes[i] / closes[i-1] - 1)
        except Exception:
            continue
    daily_rets_20 = daily_rets[-20:] if len(daily_rets) >= 20 else daily_rets
    daily_rets_60 = daily_rets[-60:] if len(daily_rets) >= 60 else daily_rets
    vol_20 = _annual_vol(daily_rets_20)
    vol_60 = _annual_vol(daily_rets_60)
    sharpe_20 = _sharpe(daily_rets_20)
    max_dd_60 = _max_drawdown(closes[-60:]) if len(closes) >= 2 else None
    win_20 = _win_rate(daily_rets_20)
    ma20 = _ma(closes, 20)
    ma60 = _ma(closes, 60)
    trend = _trend_label(closes[-1] if closes else None, ma20, ma60)
    # 波动分位近似：vol_20 在 vol_60 中的分位（简化）
    vol_pct = None
    if vol_20 is not None and vol_60 is not None and vol_60 > 0:
        # 波动率偏高则分位高（简化为 vol_20/vol_60 的映射）
        vol_pct = max(5, min(95, 50 + (vol_20 / vol_60 - 1) * 40))
    score = _signal_score(ret_20d, ret_60d, vol_pct, trend)
    # 风险标签
    risk_label = "中性"
    if ret_20d is not None and ret_20d < -5:
        risk_label = "偏弱"
    elif ret_20d is not None and ret_20d > 5:
        risk_label = "偏强"
    if max_dd_60 is not None and max_dd_60 < -8:
        risk_label = "高回撤"
    return {
        "major": def_item["major"],
        "major_en": def_item["major_en"],
        "sub": def_item["sub"],
        "label": def_item["label"],
        "symbol": def_item["symbol"],
        "benchmark": def_item["benchmark"],
        "benchmark_code": def_item["benchmark_code"],
        "style": def_item["style"],
        "desc": def_item["desc"],
        "close": closes[-1] if closes else None,
        "as_of": bars[-1].get("date") if bars else None,
        "chg_pct": ret_1d,
        "ret_5d": ret_5d,
        "ret_20d": ret_20d,
        "ret_60d": ret_60d,
        "vol_20": vol_20,
        "vol_60": vol_60,
        "sharpe_20": sharpe_20,
        "max_dd_60": max_dd_60,
        "win_20": win_20,
        "ma20": ma20,
        "ma60": ma60,
        "trend": trend,
        "vol_pct": vol_pct,
        "score": score,
        "signal": _signal_label(score),
        "risk_label": risk_label,
        "bars_n": len(closes),
        "daily_rets": daily_rets,
    }

def run_strategy_quant(safe_request=None, date_str: str = "",
                       allow_synthetic: bool = False) -> Dict:
    """执行策略量化分析（只读基准指数已收盘日线，不新增联网口）。

    safe_request   —— pipeline.safe_request（providers.fetch_bars 唯一联网入口）
    date_str       —— YYYYMMDD；仅用于诊断与（显式开启时）合成行情 seed
    allow_synthetic —— **默认 False**：取不到日线的细分如实标「暂缺」，绝不编造数字；
                       只有显式开启（OCTOPUS_STRATEGY_DEMO=1 / 测试）才用确定性合成
                       序列兜底，且结果里 synthetic=True，页面会点名「演示序列」。

    返回 {available, as_of, strategies, by_major, overview, missing, diag, ...}
    """
    date_str = str(date_str or datetime.now(CST).strftime("%Y%m%d"))
    as_of = datetime.now(CST).strftime("%Y-%m-%d")
    diag = {"bars_source": {}, "synthetic_n": 0, "synthetic_labels": []}
    strategies, missing = [], []
    providers = None
    try:
        from octopus_quant import providers as _providers
        providers = _providers
    except Exception:
        providers = None

    for def_item in STRATEGY_DEFS:
        symbol = def_item["symbol"]
        bars, source = None, ""
        if safe_request is not None and providers is not None:
            for sym in (symbol, def_item.get("fallback_symbol")):
                if not sym:
                    continue
                try:
                    b = providers.fetch_bars(safe_request, sym, rng="1y")
                except Exception:
                    b = None
                if b and len(b) >= 20:
                    bars = b
                    source = ("基准指数 " + sym) if sym == symbol else ("备用基准 " + sym)
                    break
        if (bars is None or len(bars) < 20) and allow_synthetic:
            bars = _synthetic_bars(symbol, n=120, seed_date=date_str)
            source = "合成演示序列"
            diag["synthetic_n"] += 1
            diag["synthetic_labels"].append(def_item["label"])
        if bars is None or len(bars) < 20:
            missing.append(def_item["label"])
            diag["bars_source"][def_item["label"]] = "暂缺"
            continue
        diag["bars_source"][def_item["label"]] = source
        metrics = _compute_one(def_item, bars)
        metrics["source"] = source
        metrics["synthetic"] = source == "合成演示序列"
        strategies.append(metrics)
        if metrics.get("as_of") and metrics["as_of"] > as_of:
            as_of = metrics["as_of"]

    if not strategies:
        return {"available": False, "reason": "6 个细分策略的基准指数日线均未取得",
                "as_of": None, "date_str": date_str, "strategies": [],
                "by_major": {}, "overview": {}, "missing": missing, "diag": diag}

    # 大类汇总
    by_major = {}
    for major, major_en, subs in MAJOR_GROUPS:
        subs_data = [s for s in strategies if s["major"] == major and s["sub"] in subs]
        if not subs_data:
            continue
        rets_20 = [s["ret_20d"] for s in subs_data if s["ret_20d"] is not None]
        rets_60 = [s["ret_60d"] for s in subs_data if s["ret_60d"] is not None]
        scores = [s["score"] for s in subs_data if s["score"] is not None]
        avg_ret_20 = sum(rets_20) / len(rets_20) if rets_20 else None
        avg_ret_60 = sum(rets_60) / len(rets_60) if rets_60 else None
        avg_score = sum(scores) / len(scores) if scores else None
        sorted_subs = sorted(
            subs_data,
            key=lambda x: (x["ret_20d"] if x["ret_20d"] is not None else -999), reverse=True)
        best = sorted_subs[0] if sorted_subs else None
        worst = sorted_subs[-1] if len(sorted_subs) > 1 else None
        trends = [s["trend"] for s in subs_data]
        trend = trends[0] if len(set(trends)) == 1 else "分化"
        by_major[major] = {
            "major": major, "major_en": major_en, "subs": subs_data,
            "avg_ret_20d": avg_ret_20, "avg_ret_60d": avg_ret_60,
            "avg_score": avg_score, "avg_signal": _signal_label(avg_score),
            "best": best, "worst": worst, "trend": trend, "n": len(subs_data),
        }

    # 总览：横向排名、离散度、regime
    sorted_all = sorted(strategies,
                        key=lambda x: (x["score"] if x["score"] is not None else -999),
                        reverse=True)
    top = sorted_all[0] if sorted_all else None
    bottom = sorted_all[-1] if len(sorted_all) > 1 else None
    rets_all_20 = [s["ret_20d"] for s in strategies if s["ret_20d"] is not None]
    dispersion = _std(rets_all_20) if len(rets_all_20) >= 2 else None
    eq_avg = by_major.get("权益多头", {}).get("avg_score")
    bond_avg = by_major.get("纯债策略", {}).get("avg_score")
    cta_avg = by_major.get("CTA策略", {}).get("avg_score")
    regime = "数据不足"
    known = [v for v in (eq_avg, bond_avg, cta_avg) if v is not None]
    if len(known) >= 2:
        regime = "均衡"
        if eq_avg is not None and eq_avg > 15 and eq_avg >= max(bond_avg or -999, cta_avg or -999):
            regime = "权益占优"
        elif bond_avg is not None and bond_avg > 10 and bond_avg > (eq_avg or -999):
            regime = "避险 / 债占优"
        elif cta_avg is not None and cta_avg > 12 and cta_avg > (eq_avg or -999):
            regime = "商品 / CTA 占优"
        elif all(v < -10 for v in known):
            regime = "普跌承压"
        elif dispersion is not None and dispersion > 3:
            regime = "分化轮动"

    synthetic_n = diag["synthetic_n"]
    return {
        "available": True,
        "as_of": as_of,
        "date_str": date_str,
        "strategies": strategies,
        "by_major": by_major,
        "overview": {"top": top, "bottom": bottom, "sorted": sorted_all,
                     "dispersion": dispersion, "regime": regime,
                     "eq_avg": eq_avg, "bond_avg": bond_avg, "cta_avg": cta_avg},
        "missing": missing,
        "synthetic": synthetic_n > 0,
        "diag": diag,
        "method": "基准指数已收盘日线 → 5/20/60 日收益、年化波动、夏普、最大回撤、"
                  "胜率、MA20/60 趋势与信号分；大类为细分均值",
        "note": "规则合成的统计口径，非投资建议；取不到日线的细分如实标暂缺，不补造数字",
    }

# ------------------------------------------------------------------
# 渲染
# ------------------------------------------------------------------

def _fmt_pct(v, digits=2, sign=True):
    if v is None:
        return "—"
    try:
        return f"{float(v):{'+' if sign else ''}.{digits}f}%"
    except Exception:
        return "—"

def _fmt_num(v, digits=2):
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{digits}f}"
    except Exception:
        return "—"

def _trend_badge_html(v, kit):
    try:
        pct = float(v) if v is not None else None
    except Exception:
        pct = None
    if pct is None:
        return '<span style="color:#333;">■ 暂缺</span>'
    if pct > 0:
        return f'<span style="display:inline-block;padding:1px 6px;border-radius:999px;background:#E6F4EA;color:#137333;font-size:11px;font-weight:700;">▲ +{pct:.2f}%</span>'
    elif pct < 0:
        return f'<span style="display:inline-block;padding:1px 6px;border-radius:999px;background:#FCE8E9;color:#A50E0E;font-size:11px;font-weight:700;">▼ {pct:.2f}%</span>'
    else:
        return f'<span style="display:inline-block;padding:1px 6px;border-radius:999px;background:#F1F3F4;color:#333;font-size:11px;font-weight:700;">■ 0.00%</span>'

def _signal_chip(score, label):
    if score is None:
        return "—"
    if score >= 20:
        return f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#C8F03C;color:#111;font-size:11px;font-weight:900;">{label}</span>'
    if score <= -20:
        return f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#FCE8E9;color:#A50E0E;font-size:11px;font-weight:900;">{label}</span>'
    if "偏多" in label or "微多" in label:
        return f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#F0F9C4;color:#3D5200;font-size:11px;font-weight:700;">{label}</span>'
    if "偏空" in label or "微空" in label:
        return f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#FFF3E0;color:#8D4E00;font-size:11px;font-weight:700;">{label}</span>'
    return f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#F1F3F4;color:#333;font-size:11px;font-weight:700;">{label}</span>'

def _kit_get(kit, name, fallback=None):
    fn = getattr(kit, name, None)
    if callable(fn):
        return fn
    return fallback

def _kit_sub(kit, text):
    for meth in ("sub", "subsection", "gz_subsection"):
        fn = getattr(kit, meth, None)
        if callable(fn):
            try:
                return fn(text)
            except Exception:
                pass
    # fallback inline
    return f'<div style="font-size:12px;font-weight:900;color:#002FA7;margin:8px 0 4px 0;">{_esc(text)}</div>'

def _kit_table(kit, headers, rows, aligns=None):
    fn = getattr(kit, "table", None)
    if callable(fn):
        try:
            return fn(headers, rows, aligns=aligns) if aligns else fn(headers, rows)
        except TypeError:
            try:
                return fn(headers, rows)
            except Exception:
                pass
    # fallback: simple html table
    # 兜底表也遵守「表格内文字缩小一号 + 不加粗」（2026-10-23）：12px → 11px，字重 400。
    h = "".join(f'<th style="padding:4px 8px;background:#F1F3F4;border:1px solid #ddd;text-align:left;font-size:11px;font-weight:400;">{_esc(c)}</th>' for c in (headers or []))
    b = ""
    for r in rows:
        b += "<tr>" + "".join(f'<td style="padding:4px 8px;border:1px solid #eee;font-size:11px;font-weight:400;">{_plain_cell(c)}</td>' for c in r) + "</tr>"
    return f'<table style="width:100%;border-collapse:collapse;font-weight:400;">' + (f'<tr>{h}</tr>' if h else '') + b + '</table>'

def _kit_kv(kit, pairs):
    fn = getattr(kit, "kv", None)
    if callable(fn):
        try:
            return fn(pairs)
        except Exception:
            pass
    # fallback（同样遵守「表格内文字缩小一号 + 不加粗」：12px → 11px，字重 400）
    rows = "".join(f'<tr><td style="padding:4px 8px;color:#666;font-size:11px;font-weight:400;border:1px solid #eee;">{_esc(k)}</td><td style="padding:4px 8px;font-size:11px;font-weight:400;border:1px solid #eee;">{_plain_cell(v)}</td></tr>' for k, v in pairs)
    return f'<table style="width:100%;border-collapse:collapse;font-weight:400;">{rows}</table>'

def _kit_note(kit, text):
    fn = getattr(kit, "note", None)
    if callable(fn):
        try:
            return fn(text)
        except Exception:
            pass
    return f'<div style="font-size:11px;color:#666;margin:6px 0;">{_esc(text)}</div>'

def _esc(text):
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# 表格内文字一律不加粗（2026-10-23 用户要求）：兜底渲染路径没有 kit 可用，
# 所以在单元格内容这一层把 <b>/<strong> 降级成 <span>、粗体字重写成 400，
# 与 output/pipeline.py:_table_text 同口径；颜色等其他内联样式原样保留。
_BOLD_TAG_RE = re.compile(r"<(/?)(b|strong)(?=[\s>/])", re.IGNORECASE)
_BOLD_WEIGHT_RE = re.compile(r"font-weight:\s*(?:600|700|800|900|bold|bolder)")


def _plain_cell(html):
    """单元格内容去粗：只改字重与粗体标签，不动文字与其他样式。"""
    if html is None:
        return ""
    text = str(html)
    if "<" not in text:
        return text
    text = _BOLD_TAG_RE.sub(lambda m: f"<{m.group(1)}span", text)
    return _BOLD_WEIGHT_RE.sub("font-weight:400", text)

def render_strategy_classification_table(kit):
    """图中分类的表格化呈现（用于总览顶部）"""
    headers = ["策略大类", "细分策略"]
    rows = [
        ['<b>权益多头</b>', '主观多头<br><span style="color:#666;font-size:11px;">沪深300基准</span><br>量化多头<br><span style="color:#666;font-size:11px;">中证500基准</span>'],
        ['<b>纯债策略</b>', '纯债基金<br><span style="color:#666;font-size:11px;">国债ETF / 中证全债</span>'],
        ['<b>CTA策略</b>', '主观CTA<br><span style="color:#666;font-size:11px;">GSG商品指数</span><br>量化CTA<br><span style="color:#666;font-size:11px;">DBC商品指数</span>'],
        ['<b>套利策略</b>', '综合指数<br><span style="color:#666;font-size:11px;">上证指数 / 私募综合</span>'],
    ]
    table = _kit_table(kit, headers, rows, aligns=("left", "left"))
    note = _kit_note(kit, "分类来自用户提供的策略大类图：4 大类 6 细分；每个细分对应一个可验证基准指数，量化指标按该指数日线计算，合成兜底仅离线使用。")
    return table + note

def render_overview(res, kit):
    """策略大类总览（全景排名 + 大类对比）"""
    if not res or not res.get("available"):
        return ""
    strategies = res.get("strategies") or []
    by_major = res.get("by_major") or {}
    overview = res.get("overview") or {}
    out = []
    # 三地指数表默认关闭（回滚为纯港股日报）；OCTOPUS_INDEX_PAGE=1 才渲染。
    if res.get("index_checks") and index_page_enabled():
        import index_crosscheck
        out.append(index_crosscheck.render(res["index_checks"], kit))
    if not strategies:
        return "".join(out)
    # 1) 分类表
    out.append(_kit_sub(kit, "策略分类（图中）"))
    out.append(render_strategy_classification_table(kit))
    # 2) 大类横向对比
    out.append(_kit_sub(kit, "大类量化对比（细分均值）"))
    rows = []
    for major, _, _ in MAJOR_GROUPS:
        mg = by_major.get(major)
        if not mg:
            continue
        rows.append([
            f"<b>{major}</b><br><span style='color:#666;font-size:11px;'>{mg['major_en']}</span>",
            f"{len(mg['subs'])} 项细分",
            _fmt_pct(mg.get("avg_ret_20d")),
            _fmt_pct(mg.get("avg_ret_60d")),
            _signal_chip(mg.get("avg_score"), mg.get("avg_signal")),
            mg.get("trend") or "—",
            f"{mg['best']['label']} 领跑" if mg.get("best") else "—",
        ])
    out.append(_kit_table(kit,
        ["策略大类", "细分", "20日均收益", "60日均收益", "信号", "趋势", "领跑细分"],
        rows, aligns=("left", "center", "right", "right", "center", "center", "left")
    ))
    # 3) 细分横向排名
    out.append(_kit_sub(kit, "细分策略全景排名（按信号分）"))
    rows = []
    for i, s in enumerate(overview.get("sorted") or [], 1):
        rows.append([
            f"{i}",
            f"<b>{s['label']}</b><br><span style='color:#666;font-size:11px;'>{s['major']} · {s['benchmark']}</span>",
            _fmt_num(s.get("close"), 2),
            _fmt_pct(s.get("chg_pct"), 2, True),
            _fmt_pct(s.get("ret_20d")),
            _fmt_pct(s.get("ret_60d")),
            f"{s['vol_20']:.1f}%" if s.get("vol_20") is not None else "—",
            f"{s['sharpe_20']:.2f}" if s.get("sharpe_20") is not None else "—",
            _signal_chip(s.get("score"), s.get("signal")),
        ])
    out.append(_kit_table(kit,
        ["排名", "策略", "现价", "日涨跌", "20日", "60日", "年化波动", "夏普(20日)", "信号"],
        rows, aligns=("center", "left", "right", "right", "right", "right", "right", "right", "center")
    ))
    # 4) 市场 regime 与关键结论
    out.append(_kit_kv(kit, [
        ("市场状态", f"<b>{overview.get('regime')}</b> · 权益 {(_fmt_pct(overview.get('eq_avg')))} / 纯债 {(_fmt_pct(overview.get('bond_avg')))} / CTA {(_fmt_pct(overview.get('cta_avg')))}"),
        ("最强策略", f"<b>{overview['top']['label']}</b>（{overview['top']['major']}）· 20日 {_fmt_pct(overview['top'].get('ret_20d'))} · 信号 {_signal_chip(overview['top'].get('score'), overview['top'].get('signal'))}" if overview.get("top") else "—"),
        ("最弱策略", f"<b>{overview['bottom']['label']}</b>（{overview['bottom']['major']}）· 20日 {_fmt_pct(overview['bottom'].get('ret_20d'))} · 信号 {_signal_chip(overview['bottom'].get('score'), overview['bottom'].get('signal'))}" if overview.get("bottom") else "—"),
        ("离散度", f"{overview['dispersion']:.2f}%" if overview.get("dispersion") is not None else "—" + " · 20日收益标准差，衡量策略间分化"),
        ("数据时点", f"{res.get('as_of')} 收盘 · 6 细分 × 4 大类 · 基准指数日线已收盘"),
    ]))
    # 5) 数据点名（暂缺 / 合成演示）与方法说明
    missing = [m for m in (res.get("missing") or []) if m]
    if missing:
        out.append(_kit_kv(kit, [(
            "暂缺细分",
            f"{'、'.join(missing)}（基准指数日线未取得，指标留空不补造；"
            f"其余 {len(strategies)} 项照常计算）")]))
    if res.get("synthetic"):
        out.append(_kit_kv(kit, [(
            "⚠ 演示序列",
            "本次有细分使用确定性合成序列（OCTOPUS_STRATEGY_DEMO=1），"
            "数字只用于版面演示，不代表真实指数，不可用于判断行情。")]))
    out.append(_kit_note(kit, "口径：每个细分策略对应一个基准指数（见分类表），取近1年日线计算 5/20/60日收益、"
                             "年化波动、夏普(20日)、最大回撤(60日)、胜率(20日)、MA20/60趋势与信号分；"
                             "大类为细分均值；市场状态按大类信号均值判定；仅供参考，不构成投资建议。"))
    return "".join(out)

def render_major(major: str, res, kit):
    """单大类量化分析（2-3个细分的深度对比）"""
    if not res or not res.get("available"):
        return ""
    by_major = res.get("by_major") or {}
    mg = by_major.get(major)
    if not mg:
        return ""
    out = []
    # 标题内的小结
    out.append(_kit_kv(kit, [
        ("大类趋势", f"<b>{mg.get('trend')}</b> · 信号 {_signal_chip(mg.get('avg_score'), mg.get('avg_signal'))}（细分均值）"),
        ("平均收益", f"20日 {_fmt_pct(mg.get('avg_ret_20d'))} · 60日 {_fmt_pct(mg.get('avg_ret_60d'))}"),
        ("领跑/落后", f"领跑 <b>{mg['best']['label']}</b> {_fmt_pct(mg['best'].get('ret_20d'))}（#{1}）· 落后 <b>{mg['worst']['label']}</b> {_fmt_pct(mg['worst'].get('ret_20d'))}" if mg.get("best") and mg.get("worst") and mg['best'] != mg['worst'] else f"<b>{mg['best']['label']}</b>"),
    ]))
    # 细分明细表
    out.append(_kit_sub(kit, f"{major} · 细分量化明细"))
    rows = []
    for s in mg.get("subs") or []:
        rows.append([
            f"<b>{s['label']}</b><br><span style='color:#666;font-size:11px;'>{s['benchmark']}<br>{s['style']}</span>",
            s.get("symbol") or "—",
            _fmt_num(s.get("close"), 2),
            _fmt_pct(s.get("chg_pct"), 2, True),
            _fmt_pct(s.get("ret_5d")),
            _fmt_pct(s.get("ret_20d")),
            _fmt_pct(s.get("ret_60d")),
            f"{s['vol_20']:.1f}%" if s.get("vol_20") is not None else "—",
            f"{s['max_dd_60']:.1f}%" if s.get("max_dd_60") is not None else "—",
            f"{s['win_20']:.0f}%" if s.get("win_20") is not None else "—",
            s.get("trend") or "—",
            _signal_chip(s.get("score"), s.get("signal")),
        ])
    out.append(_kit_table(kit,
        ["细分策略", "代码", "现价", "日涨跌", "5日", "20日", "60日", "年化波动", "最大回撤", "胜率(20日)", "趋势", "信号"],
        rows, aligns=("left", "center", "right", "right", "right", "right", "right", "right", "right", "right", "center", "center")
    ))
    # 细分深度对比（成对）
    if len(mg.get("subs") or []) == 2:
        a, b = mg["subs"][0], mg["subs"][1]
        out.append(_kit_sub(kit, "细分对比"))
        # 收益对比
        a_vol = f"{a['vol_20']:.1f}%" if a.get('vol_20') is not None else "—"
        b_vol = f"{b['vol_20']:.1f}%" if b.get('vol_20') is not None else "—"
        a_sharpe = f"{a['sharpe_20']:.2f}" if a.get('sharpe_20') is not None else "—"
        b_sharpe = f"{b['sharpe_20']:.2f}" if b.get('sharpe_20') is not None else "—"
        out.append(_kit_kv(kit, [
            ("20日收益差", f"<b>{a['label']}</b> {_fmt_pct(a.get('ret_20d'))} vs <b>{b['label']}</b> {_fmt_pct(b.get('ret_20d'))} · 差 {(_fmt_pct((a.get('ret_20d') or 0) - (b.get('ret_20d') or 0)))}"),
            ("60日收益差", f"<b>{a['label']}</b> {_fmt_pct(a.get('ret_60d'))} vs <b>{b['label']}</b> {_fmt_pct(b.get('ret_60d'))} · 差 {(_fmt_pct((a.get('ret_60d') or 0) - (b.get('ret_60d') or 0)))}"),
            ("波动/夏普", f"{a['label']} 波动 {a_vol} 夏普 {a_sharpe} · {b['label']} 波动 {b_vol} 夏普 {b_sharpe}"),
            ("趋势/信号", f"{a['label']} {a.get('trend')} · {_signal_chip(a.get('score'), a.get('signal'))} · {b['label']} {b.get('trend')} · {_signal_chip(b.get('score'), b.get('signal'))}"),
        ]))
        # 结论句
        winner = a if (a.get("score") or -999) >= (b.get("score") or -999) else b
        out.append(_kit_note(kit, f"{major}内 <b>{winner['label']}</b> 信号更强（{winner.get('signal')}，20日 {_fmt_pct(winner.get('ret_20d'))}）；另一细分可作轮动或对冲观察，非投资建议。"))
    else:
        # 单细分（如纯债、综合指数）给出风险与收益特征
        s = (mg.get("subs") or [None])[0]
        if s:
            vol20_s = f"{s['vol_20']:.1f}%" if s.get('vol_20') is not None else "—"
            dd_s = f"{s['max_dd_60']:.1f}%" if s.get('max_dd_60') is not None else "—"
            win_s = f"{s['win_20']:.0f}%" if s.get('win_20') is not None else "—"
            out.append(_kit_kv(kit, [
                ("收益特征", f"5日 {_fmt_pct(s.get('ret_5d'))} · 20日 {_fmt_pct(s.get('ret_20d'))} · 60日 {_fmt_pct(s.get('ret_60d'))}"),
                ("风险特征", f"年化波动 {vol20_s} · 最大回撤 {dd_s} · 胜率 {win_s}"),
                ("趋势信号", f"{s.get('trend')} · MA20 {_fmt_num(s.get('ma20'),2)} · MA60 {_fmt_num(s.get('ma60'),2)} · {_signal_chip(s.get('score'), s.get('signal'))}"),
            ]))
            if major == "纯债策略":
                out.append(_kit_note(kit, "纯债策略波动低于权益与商品，适合作为组合稳定器；当前信号仅反映基准指数趋势，非产品业绩承诺。"))
            elif major == "套利策略":
                out.append(_kit_note(kit, "综合指数反映多策略套利与市场中性的合成表现；当前信号为基准指数趋势代理，实盘以管理人净值为准。"))
    return "".join(out)

def render_bond(major, res, kit):
    return render_major(major, res, kit)

def render_all_majors(res, kit):
    """供测试或聚合渲染用：返回 {major: html}"""
    return {major: render_major(major, res, kit) for major, _, _ in MAJOR_GROUPS}

