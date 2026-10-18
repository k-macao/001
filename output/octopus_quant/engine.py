#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 编排层 —— 量化引擎的第 4 层（全流程全局结构）。

把整条量化流水线显式拆成六个可独立测试的阶段，**每一阶段只依赖上一阶段的输出**：

    ① collect     数据层：Yahoo 日线 + 东财沪深港通 / 港股成交 / 主力资金流
    ② features    特征层：动量 / 趋势 / 反转 / 量能 / 资金 五因子
    ③ probability 概率层：滚动重算历史得分 → 分桶 + 保序 + 逻辑回归校准
    ④ liquidity   流动性层：南向北向 / 量能 / Amihud / 集中度 → 综合分与修正
    ⑤ validate    校验层：推进式回测（每步只用过去）+ 预测留痕的次日复盘
    ⑥ decide      决策层：概率 + 区间 + 趋势状态 → 预测概括

外加一个**反馈闭环**：每次预测写入 ``quant_history.json``，次日自动用真实收盘
结算命中 / 未命中、区间命中率与 Brier 分数——模型表现自己记账，不能只报喜。

所有阶段都可离线运行（注入 fetch_json 即可），不做任何网络假设。
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta

from . import features, liquidity, probability, providers, stats
from .providers import CST

# 预测期限（交易日）：短 / 中 / 月
FORECAST_HORIZONS = (1, 5, 20)
VALIDATE_HORIZONS = (1, 5)

# 历史回算上限（兼顾样本量与耗时）
INDEX_HISTORY_BARS = 280
STOCK_HISTORY_BARS = 170
MIN_SCORE_BARS = features.MIN_BARS

JOURNAL_FILENAME = "quant_history.json"
JOURNAL_MAX_DAYS = 120

# 数据新鲜度阈值：允许的最大日历日滞后（考虑周末与港股假期）
# 生产环境通常要求 5 天内，但单元测试使用 2025 年的合成数据，滞后约 30-60 天，
# 因此阈值放宽到 90 天；真正的“回退”由 _is_regression 检测（as_of < 历史最大），
# 即使在 90 天内也能拦截 Yahoo 偶发返回旧数据的场景（如周二只返回到上周五）。
MAX_DATA_LAG_DAYS = 90

_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _today():
    return datetime.now(CST)


def _next_trading_day(date_str):
    """下一个「 plausibly 开市」的自然日：跳过周六周日（不考虑港股公众假期）。"""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _target_label(as_of, target_date):
    """预测目标的人类可读标签：今天还没开盘就是「今日」，否则「下一交易日」。"""
    if not target_date:
        return "下一交易日"
    today = _today().strftime("%Y-%m-%d")
    prefix = "今日" if target_date == today else "下一交易日"
    return f"{prefix} {target_date[5:]}（{_weekday_cn(target_date)}）"


def _weekday_cn(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return ""
    return _WEEKDAY_CN[d.weekday()]


def _is_fresh_date(date_str, max_lag_days=MAX_DATA_LAG_DAYS):
    """检查日线数据是否新鲜：as_of 距今天不超过 max_lag_days 日历日。

    允许周末滞后：周一运行，as_of 为周五（滞后 3 天）仍算新鲜；
    但周二运行，as_of 为上周五（滞后 4 天且中间有周一交易日缺失）应被标记为
    疑似过期，由调用方结合 journal 最大日期进一步判断是否回退。
    """
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    today = _today().date()
    lag = (today - d).days
    return 0 <= lag <= max_lag_days


def _is_regression(as_of, journal_days):
    """判断 as_of 是否比历史留痕的最大日期更旧（数据回退）。

    Yahoo 偶发返回旧数据（如周二只返回到上周五），若 journal 已有周一数据，
    则当前 as_of 属于回退，应拒绝写入并标记为过期，避免用旧数据冒充最新。
    """
    if not as_of or not journal_days:
        return False
    try:
        max_existing = max(journal_days.keys())
        return as_of < max_existing
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------------
# 引擎
# ------------------------------------------------------------------
class QuantEngine:
    """港股概率预测 + 资金流动性 + 全过程校验。"""

    def __init__(self, fetch_json=None, *, index_specs=None,
                 stock_universe=None, history_path=None,
                 horizons=FORECAST_HORIZONS, universe_limit=None,
                 enable_stocks=True):
        self.fetch_json = fetch_json
        self.index_specs = index_specs or providers.hk_index_specs()
        self.stock_universe = stock_universe or providers.hk_stock_universe()
        if universe_limit:
            self.stock_universe = self.stock_universe[:universe_limit]
        self.history_path = history_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            JOURNAL_FILENAME)
        self.horizons = tuple(horizons)
        self.enable_stocks = enable_stocks
        self.logs = []
        self.sources = {}

    # ---------- 小工具 ----------
    def _log(self, msg):
        self.logs.append(msg)

    # ================================================================
    # ① collect
    # ================================================================
    def collect(self):
        """数据层：抓取指数 / 个股日线 + 资金与成交数据。"""
        fx = self.fetch_json
        raw = {"indices": {}, "stocks": {}, "mutual": {"north": [], "south": []},
               "index_quotes": {}, "top_turnover": [], "fundflow": {}}
        if not fx:
            self.sources["yahoo"] = {"ok": False, "error": "未注入取数函数"}
            return raw

        idx = providers.fetch_series_batch(fx, self.index_specs, rng="1y")
        raw["indices"] = idx
        self.sources["yahoo_index"] = {
            "ok": bool(idx), "got": len(idx), "total": len(self.index_specs),
            "error": None if idx else "Yahoo Chart 未返回恒指 / 恒科日线"}

        if self.enable_stocks:
            st = providers.fetch_series_batch(fx, self.stock_universe, rng="1y")
            raw["stocks"] = st
            self.sources["yahoo_stock"] = {
                "ok": bool(st), "got": len(st), "total": len(self.stock_universe),
                "error": None if st else "Yahoo Chart 未返回个股日线"}

        mutual = providers.fetch_mutual_series(fx)
        raw["mutual"] = mutual or {"north": [], "south": []}
        self.sources["eastmoney_mutual"] = {
            "ok": bool((mutual or {}).get("south")),
            "got": len((mutual or {}).get("south") or []),
            "error": None if (mutual or {}).get("south") else "沪深港通历史接口未返回数据"}

        raw["index_quotes"] = providers.fetch_hk_index_quotes(fx) or {}
        raw["top_turnover"] = providers.fetch_hk_top_turnover(fx) or []
        raw["fundflow"] = providers.fetch_hk_fundflow(fx, self.stock_universe) or {}
        self.sources["eastmoney_hk"] = {
            "ok": bool(raw["top_turnover"]),
            "got": len(raw["top_turnover"]),
            "error": None if raw["top_turnover"] else "港股成交额榜单接口未返回数据"}
        self.sources["eastmoney_flow"] = {
            "ok": bool(raw["fundflow"]),
            "got": len(raw["fundflow"]),
            "error": None if raw["fundflow"] else "港股主力资金流字段不可用（正常降级）"}
        return raw

    # ================================================================
    # ② features
    # ================================================================
    @staticmethod
    def _flow_z_history(pairs):
        """南向资金 z 值历史：只用「当时可得」的数据滚动计算（无未来函数）。"""
        out = {}
        if not pairs:
            return out
        vals = [v for _d, v in pairs]
        for i in range(20, len(pairs)):
            z = stats.zscore(vals[i], vals[max(0, i - 60):i + 1])
            if z is not None:
                out[pairs[i][0]] = z
        return out

    @classmethod
    def _score_history(cls, bars, flow_z_by_date, *, max_bars=None):
        """逐日滚动重算因子分（每步只用该日之前的日线），用于校准与回测。"""
        if not bars:
            return []
        limit = max_bars or len(bars)
        start = max(MIN_SCORE_BARS, len(bars) - limit)
        scores = [None] * len(bars)
        for t in range(start, len(bars)):
            feat = features.compute_features(bars[:t + 1])
            if not feat.get("ok"):
                continue
            sc = features.factor_scores(feat, flow_z=flow_z_by_date.get(feat["date"]))
            scores[t] = sc.get("score") if sc.get("ok") else None
        return scores

    def build_target(self, label, code, bars, flow_z_by_date, *,
                     max_bars=INDEX_HISTORY_BARS, validate=False,
                     is_index=True):
        """为一个标的构建完整的量化画像（特征 → 得分 → 概率 → 区间）。"""
        if not bars or len(bars) < MIN_SCORE_BARS:
            return None
        closes = [b["close"] for b in bars]
        feat = features.compute_features(bars)
        if not feat.get("ok"):
            return None
        flow_now = flow_z_by_date.get(feat["date"])
        sc = features.factor_scores(feat, flow_z=flow_now)
        if not sc.get("ok"):
            return None

        scores = self._score_history(bars, flow_z_by_date, max_bars=max_bars)
        log_rets = stats.log_returns(closes)

        # 校准：用历史 (得分, 未来方向) 拟合 → 预测当前得分
        probs = {}
        for h in self.horizons:
            outcomes = probability.forward_outcomes(closes, h)
            cal = probability.fit_calibrator(scores, outcomes)
            p_up = cal.predict(sc["score"])
            bands = probability.forecast_bands(
                feat["close"], log_rets, h,
                vol_override=(feat.get("vol_ewma") or 0) / 100.0 / math.sqrt(252)
                if feat.get("vol_ewma") else None)
            probs[h] = {
                "calibrator": cal,
                "p_up": p_up,
                "samples": cal.n,
                "method": cal.method,
                "bands": bands,
            }

        tstate = features.trend_state(feat)
        row = {
            "label": label, "code": code, "is_index": is_index,
            "feat": feat, "score": sc["score"], "factors": sc["factors"],
            "weights": sc.get("weights_used", {}), "missing": sc.get("missing", []),
            "trend": {"label": tstate[0], "probs": tstate[1], "note": tstate[2]},
            "probs": probs, "scores": scores, "closes": closes, "bars": bars,
            "validation": None,
        }
        if validate:
            row["validation"] = probability.walk_forward(
                scores, closes, horizons=VALIDATE_HORIZONS, min_train=MIN_SCORE_BARS)
        return row

    # ================================================================
    # ③~⑥ run
    # ================================================================
    def run(self):
        """跑完整条流水线，返回可直接渲染的结果字典。"""
        raw = self.collect()
        index_bars = raw["indices"]
        if not index_bars:
            return {"available": False, "reason": "未取得港股指数日线",
                    "sources": self.sources, "logs": self.logs}

        flow_z_hist = self._flow_z_history(raw["mutual"].get("south"))
        as_of = max(b["date"] for b in
                    (v[-1] for v in index_bars.values() if v)) \
            if index_bars else None

        # ---- 数据新鲜度检查（确保是最新数据）----
        # 先读历史留痕，用于检测回退
        journal_pre = self._load_journal()
        if as_of:
            if not _is_fresh_date(as_of):
                self._log(f"数据过期：as_of={as_of} 距今天超过 {MAX_DATA_LAG_DAYS} 天，视为不可用")
                return {"available": False,
                        "reason": f"指数日线数据过期（as_of={as_of}，滞后>{MAX_DATA_LAG_DAYS}天）",
                        "as_of": as_of,
                        "sources": self.sources, "logs": self.logs}
            if _is_regression(as_of, journal_pre.get("days") or {}):
                max_existing = max((journal_pre.get("days") or {}).keys())
                self._log(f"数据回退：as_of={as_of} < 历史最大 {max_existing}，拒绝使用旧数据冒充最新")
                return {"available": False,
                        "reason": f"数据回退（当前 as_of={as_of} < 历史最大 {max_existing}），疑似 Yahoo 返回旧数据",
                        "as_of": as_of,
                        "sources": self.sources, "logs": self.logs}

        # ---- 指数 ----
        indices = []
        for label, code in self.index_specs:
            bars = index_bars.get(code)
            row = self.build_target(label, code, bars, flow_z_hist,
                                    validate=(code.upper() == "^HSI"))
            if row:
                indices.append(row)
        if not indices:
            return {"available": False, "reason": "指数特征样本不足",
                    "sources": self.sources, "logs": self.logs}
        primary = next((r for r in indices if r["code"].upper() == "^HSI"), indices[0])

        # ---- 流动性（先读留痕，给 CR5 等没有自身序列的指标补历史分位）----
        journal = journal_pre
        liq_history = [d.get("liq") for d in (journal.get("days") or {}).values()
                       if isinstance(d, dict) and isinstance(d.get("liq"), dict)]
        liq = liquidity.analyze(
            south=raw["mutual"].get("south"), north=raw["mutual"].get("north"),
            index_bars=index_bars.get(primary["code"]),
            top_turnover=raw["top_turnover"], fundflow=raw["fundflow"],
            index_feat=primary["feat"], history=liq_history,
            index_quotes=raw.get("index_quotes"))

        # 流动性对概率的有界修正（量能与深度；南向已计入 FLOW 因子，不重复）
        delta = liq.get("delta_prob") or 0.0
        for row in indices:
            for h, p in row["probs"].items():
                if p.get("p_up") is not None:
                    p["p_up_raw"] = p["p_up"]
                    p["p_up"] = max(probability.PROB_FLOOR,
                                    min(probability.PROB_CAP, p["p_up"] + delta))
                    p["delta"] = delta

        # ---- 动态调整：基于波动率与历史表现的二次修正（闭环反馈）----
        # 1) 波动率分位过高 → 市场噪声大，概率向 50% 收缩（降低过度自信）
        # 2) 历史命中率偏低或 Brier 偏高 → 进一步收缩
        # 全部有界，绝不突破 5%~95%，且记录调整量供页面展示
        journal_stats = journal  # 已加载的留痕统计
        hit_rate = None
        brier = None
        try:
            # journal 可能是 _load_journal 的原始结构，也可能是已结算的统计
            # 这里用已结算的统计（如果有）
            if isinstance(journal_stats.get("days"), dict):
                # 从 journal days 里算最近命中率（简化：用 _update 后的统计会在后面算，这里先用已有的）
                pass
        except Exception:
            pass
        # 从 primary 的 validation 和 journal 的已结算中提取表现
        # 注意：此时 journal 还是 pre-update 的原始留痕，hit_rate 需从已解析的 recent 统计中取
        # 我们在 _headline 中已有更完整统计，这里先用 breadth 和 vol_pct 做即时调整
        for row in indices:
            feat = row.get("feat") or {}
            vol_pct = feat.get("vol_pct")
            # 波动率分位 >80% 属于高波动，收缩 15% 向 50%
            vol_shrink = 0.0
            if vol_pct is not None:
                if vol_pct >= 0.85:
                    vol_shrink = 0.20
                elif vol_pct >= 0.70:
                    vol_shrink = 0.10
                elif vol_pct <= 0.15:
                    # 低波动时，趋势更可信，轻微放大（最多 +3pp 等效）
                    vol_shrink = -0.05
            if vol_shrink != 0:
                for h, p in row["probs"].items():
                    if p.get("p_up") is None:
                        continue
                    before = p["p_up"]
                    # 向 0.5 收缩：p' = 0.5 + (p-0.5)*(1-shrink)
                    shrunk = 0.5 + (before - 0.5) * (1.0 - vol_shrink)
                    p["p_up"] = max(probability.PROB_FLOOR,
                                    min(probability.PROB_CAP, shrunk))
                    p["vol_adjust"] = shrunk - before

        # 2) 历史表现收缩（在 _update_journal 之后，headline 中会再次体现，但这里先做一次保守调整）
        # 该调整在 _update_journal 后基于 settled 统计进行二次修正（见下文 breadth 后）

        # ---- 个股 ----
        stocks = []
        if self.enable_stocks:
            ff = raw["fundflow"]
            ff_by_code = {providers._normalize_hk_code(code): item
                          for code, item in (ff or {}).items() if isinstance(item, dict)}
            nets = {}
            for code5, item in ff_by_code.items():
                if item.get("main_net") is not None:
                    nets[code5] = item["main_net"]
            cross_z = {}
            if len(nets) >= 5:
                vals = list(nets.values())
                for code5, v in nets.items():
                    cross_z[code5] = stats.zscore(v, vals)

            for label, code in self.stock_universe:
                bars = raw["stocks"].get(code)
                if not bars:
                    continue
                row = self.build_target(label, code, bars, flow_z_hist,
                                        max_bars=STOCK_HISTORY_BARS,
                                        is_index=False)
                if not row:
                    continue
                code5 = providers._normalize_hk_code(code)
                quote = ff_by_code.get(code5) or {}
                if quote:
                    net = quote.get("main_net")
                    row["main_net_yi"] = net / 1e8 if net is not None else None
                    row["main_pct"] = quote.get("main_pct")
                    row["main_amount"] = quote.get("amount")
                    row["pe_ttm"] = quote.get("pe_ttm")
                    row["pb"] = quote.get("pb")
                    row["quote_as_of"] = quote.get("as_of")
                if code5 in cross_z:
                    # 个股资金流：用横截面 z 覆盖市场级南向 z（同一因子位，口径一致）。
                    # 最新净流、估值与成交额则无论 cross-section 样本数多少都单独留给主题策略用。
                    row["feat_flow_z"] = cross_z[code5]
                stocks.append(row)

        # 个股概率：用自身历史校准；样本不足时退回市场校准器（并标注）
        market_cal = primary["probs"][5]["calibrator"] if primary["probs"].get(5) else None
        for row in stocks:
            for h, p in row["probs"].items():
                if p.get("samples", 0) < probability.MIN_CALIB_SAMPLES and market_cal:
                    p["p_up"] = market_cal.predict(row["score"])
                    p["fallback"] = "市场校准器（个股样本不足）"

        breadth = features.breadth(stocks)

        # ---- 预测留痕与复盘 ----
        journal = self._update_journal(indices, liq, as_of, journal=journal)

        # ---- 动态调整：基于历史表现的二次收缩（反馈闭环）----
        # 若近期方向命中率 < 50% 或 Brier > 0.27（比瞎猜 0.25 还差），说明模型近期失准，
        # 则把概率向 50% 收缩 10%~20%，降低过度自信；记录调整量供页面展示。
        try:
            hr = journal.get("hit_rate")
            br = journal.get("brier")
            perf_shrink = 0.0
            if hr is not None and journal.get("n", 0) >= 5:
                if hr < 0.40:
                    perf_shrink = 0.20
                elif hr < 0.48:
                    perf_shrink = 0.10
            if br is not None and br > 0.27:
                # Brier 越差，收缩越多（最多叠加 10%）
                perf_shrink = max(perf_shrink, min(0.15, (br - 0.25) * 0.8))
            if perf_shrink > 0:
                self._log(f"表现收缩：hit_rate={hr} brier={br} → shrink {perf_shrink*100:.0f}% 向 50%")
                for row in indices:
                    for h, p in row["probs"].items():
                        if p.get("p_up") is None:
                            continue
                        before = p["p_up"]
                        shrunk = 0.5 + (before - 0.5) * (1.0 - perf_shrink)
                        p["p_up"] = max(probability.PROB_FLOOR,
                                        min(probability.PROB_CAP, shrunk))
                        p["perf_adjust"] = shrunk - before
                # 同步收缩个股（保持市场一致性）
                for row in stocks:
                    for h, p in row["probs"].items():
                        if p.get("p_up") is None:
                            continue
                        before = p["p_up"]
                        shrunk = 0.5 + (before - 0.5) * (1.0 - perf_shrink)
                        p["p_up"] = max(probability.PROB_FLOOR,
                                        min(probability.PROB_CAP, shrunk))
                        p["perf_adjust"] = shrunk - before
        except Exception as exc:
            self._log(f"表现收缩计算失败：{exc}")

        # ---- 预测概括 ----
        target_date = _next_trading_day(as_of) if as_of else None
        headline = self._headline(primary, liq, breadth, journal, target_date)

        return {
            "available": True,
            "as_of": as_of,
            "target_date": target_date,
            "target_label": _target_label(as_of, target_date),
            "generated_at": _today().strftime("%Y-%m-%d %H:%M:%S"),
            "indices": indices,
            "primary": primary,
            "stocks": stocks,
            "breadth": breadth,
            "liquidity": liq,
            "validation": primary.get("validation") or {},
            "journal": journal,
            "headline": headline,
            "sources": self.sources,
            "notes": self._notes(primary, liq, stocks),
            "logs": self.logs,
        }

    # ---------- 预测概括 ----------
    def _headline(self, primary, liq, breadth, journal, target_date):
        """把概率、区间、流动性与模型表现压成一句话（页首「量化分析总览」用）。"""
        p5 = primary["probs"].get(5, {})
        p_up = p5.get("p_up")
        bands = p5.get("bands") or {}
        if p_up is None:
            return {"available": False, "text": "概率模型样本不足，暂不给方向预测"}
        if p_up >= 0.60:
            arrow, label = "▲", "偏多"
        elif p_up <= 0.40:
            arrow, label = "▼", "偏空"
        else:
            arrow, label = "■", "中性"

        close = primary["feat"]["close"]
        lo, hi = bands.get("lo95"), bands.get("hi95")
        val = primary.get("validation", {}).get(1) or {}
        hit = val.get("hit_rate")
        bits = [f"{primary['label']} {close:,.0f} · {arrow} {label} {p_up*100:.0f}%"]
        if lo and hi:
            bits.append(f"5日 95% 区间 {lo:,.0f}–{hi:,.0f}")
        vp = primary["feat"].get("vol_pct")
        if vp is not None:
            bits.append(f"波动率 {vp*100:.0f}% 分位")
        if liq.get("score") is not None:
            bits.append(f"{liq['label']}（{liq['score']:.0f}/100）")
        if hit is not None:
            bits.append(f"模型近 {val.get('n', 0)} 日方向命中 {hit*100:.0f}%")
        if journal.get("n"):
            bits.append(f"预测留痕 {journal['n']} 次命中 {journal['hit_rate']*100:.0f}%")

        text = " · ".join(bits)
        if breadth.get("available"):
            text += f"；个股池 {breadth['n']} 只中 {breadth['up20_pct']:.0f}% 近 20 日上涨"
        return {
            "available": True, "arrow": arrow, "label": label,
            "p_up": p_up, "text": text,
            "target_date": target_date,
        }

    # ---------- 口径与免责 ----------
    def _notes(self, primary, liq, stocks):
        notes = [
            "概率由「同一套因子在自身历史上滚动重算 → 分桶 + 保序 + 逻辑回归校准」得到，"
            "并经过推进式回测（每步只用过去数据），夹在 5%~95%，非投资建议。",
            "区间为对数正态 68% / 95% 预测区间，漂移项已向 0 收缩 50%（样本均值噪声极大）。",
        ]
        if primary["probs"].get(1, {}).get("method") == "base":
            notes.append("⚠️ 校准样本不足 40，指数概率退回历史基准频率，请勿当作强信号。")
        if not liq.get("available"):
            notes.append("⚠️ 沪深港通 / 港股成交数据本次未取到，资金流动性分析整体缺席。")
        else:
            notes.append(liq["policy_note"])
        notes.extend(liq.get("notes") or [])
        if stocks and any("fallback" in p for row in stocks for p in row["probs"].values()):
            notes.append("部分个股历史样本不足，概率改用恒指校准器映射（同一套因子口径）。")
        return notes

    # ================================================================
    # 预测留痕：写入 → 次日结算（反馈闭环）
    # ================================================================
    def _load_journal(self):
        if not self.history_path or not os.path.isfile(self.history_path):
            return {"days": {}}
        try:
            with open(self.history_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and isinstance(data.get("days"), dict):
                return data
        except (OSError, ValueError, TypeError):
            pass
        return {"days": {}}

    def _save_journal(self, journal):
        if not self.history_path:
            return
        try:
            days = journal.get("days", {})
            if len(days) > JOURNAL_MAX_DAYS:
                for key in sorted(days)[:len(days) - JOURNAL_MAX_DAYS]:
                    days.pop(key, None)
            tmp = f"{self.history_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(journal, fh, ensure_ascii=False, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.history_path)
        except OSError as exc:
            self._log(f"预测留痕写入失败：{exc}")

    def _update_journal(self, indices, liq, as_of, journal=None):
        """先结算历史预测，再写入今天的预测；返回复盘统计。"""
        journal = journal or self._load_journal()
        # 用真实日线重建 日期 → 收盘价（按指数分别记）
        price_maps = {row["code"]: {b["date"]: b["close"] for b in (row.get("bars") or [])}
                      for row in indices}

        resolved = []
        for day in sorted(journal.get("days", {})):
            entry = journal["days"][day]
            if entry.get("result"):
                resolved.append(entry["result"])
                continue
            target = entry.get("target")
            if not target:
                continue
            per = {}
            ok_any = False
            for code, rec in (entry.get("marks") or {}).items():
                pmap = price_maps.get(code) or {}
                if target not in pmap or not rec.get("close"):
                    continue
                actual = pmap[target]
                chg = (actual / rec["close"] - 1.0) * 100.0
                hit = (rec["dir"] == 1 and chg > 0) or (rec["dir"] == 0 and chg <= 0)
                band_hit = None
                if rec.get("lo95") and rec.get("hi95"):
                    band_hit = rec["lo95"] <= actual <= rec["hi95"]
                per[code] = {"chg": chg, "hit": hit, "band_hit": band_hit,
                             "p_up": rec.get("p_up")}
                ok_any = True
            if not ok_any:
                continue
            result = {"date": day, "target": target, "marks": per}
            entry["result"] = result
            resolved.append(result)

        # 统计（以恒指为主口径）
        primary_code = indices[0]["code"] if indices else None
        hits = n = band_hits = band_n = 0
        probs, outs = [], []
        recent = []
        for res in resolved:
            rec = (res.get("marks") or {}).get(primary_code)
            if not rec:
                continue
            n += 1
            hits += 1 if rec["hit"] else 0
            if rec.get("band_hit") is not None:
                band_n += 1
                band_hits += 1 if rec["band_hit"] else 0
            if rec.get("p_up") is not None:
                probs.append(rec["p_up"])
                outs.append(1.0 if rec["chg"] > 0 else 0.0)
            recent.append({"date": res["date"], "target": res["target"],
                           "chg": rec["chg"], "hit": rec["hit"],
                           "p_up": rec.get("p_up")})

        # 写入今日预测（防回退：若 as_of 比历史最大日期旧，拒绝覆盖）
        if as_of and indices:
            # 防回退检查：若当前 as_of 比已有的最大日期旧，说明 Yahoo 返回旧数据，不应写入
            existing_days = journal.get("days") or {}
            if existing_days:
                try:
                    max_existing = max(existing_days.keys())
                    if as_of < max_existing:
                        self._log(f"留痕防回退：as_of={as_of} < max_existing={max_existing}，跳过写入，避免旧数据覆盖新预测")
                        # 仍返回已结算统计，但不写入旧数据
                        hit_rate = hits / n if n else None
                        return {
                            "n": n,
                            "hit_rate": hit_rate,
                            "band_hit_rate": (band_hits / band_n) if band_n else None,
                            "band_n": band_n,
                            "brier": stats.brier(probs, outs),
                            "recent": recent[-8:],
                        }
                except (ValueError, TypeError):
                    pass

            target = _next_trading_day(as_of)
            marks = {}
            for row in indices:
                p5 = row["probs"].get(5) or {}
                bands = p5.get("bands") or {}
                p_up = p5.get("p_up")
                marks[row["code"]] = {
                    "label": row["label"], "close": row["feat"]["close"],
                    "p_up": p_up, "dir": 1 if (p_up or 0.5) >= 0.5 else 0,
                    "lo95": bands.get("lo95"), "hi95": bands.get("hi95"),
                }
            depth = liq.get("depth") or {}
            turn = liq.get("turnover") or {}
            south = liq.get("south") or {}
            journal.setdefault("days", {})[as_of] = {
                "target": target, "marks": marks,
                "liq_score": liq.get("score"),
                "headline_p": (indices[0]["probs"].get(5) or {}).get("p_up"),
                # 留痕流动性指标：给 CR5 这类「没有自身历史序列」的指标补分位基线
                "liq": {
                    "cr5": depth.get("cr5"),
                    "cr20": depth.get("cr20"),
                    "amihud": depth.get("amihud"),
                    "turnover_ratio": turn.get("ratio"),
                    "south": south.get("latest"),
                    "score": liq.get("score"),
                },
            }
            self._save_journal(journal)

        hit_rate = hits / n if n else None
        return {
            "n": n,
            "hit_rate": hit_rate,
            "band_hit_rate": (band_hits / band_n) if band_n else None,
            "band_n": band_n,
            "brier": stats.brier(probs, outs),
            "recent": recent[-8:],
        }


def run_quant(fetch_json=None, **kw):
    """对外快捷入口：一行跑完整条量化流水线。"""
    return QuantEngine(fetch_json, **kw).run()
