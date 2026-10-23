"""🐙 港股量化引擎离线回归测试（不发任何网络请求）。

覆盖分层结构的每一层：
  stats → providers → features → probability → liquidity → engine → render → pipeline 集成

另含两条「防自欺」测试：
  · 未来函数检测：在纯反转序列上，模型**不允许**出现虚假高胜率（否则说明偷看未来）；
  · 概率边界：任何概率都夹在 5%~95%，绝不出现 0% / 100% 的假确定性。
"""
import importlib.util
import json
import math
import os
import random
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# pipeline 在导入时只需要 requests 存在；本测试不发出 HTTP 请求。
sys.modules.setdefault("requests", types.SimpleNamespace())

REPO_ROOT = Path(__file__).parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
if str(OUTPUT_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUT_DIR))

import octopus_quant as oq                                    # noqa: E402
from octopus_quant import engine, features, liquidity, probability, providers, render, stats  # noqa: E402

MODULE_PATH = OUTPUT_DIR / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_quant_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

CST = timezone(timedelta(hours=8))


# ==================================================================
# 合成数据工具
# ==================================================================
def synth_bars(n=280, start=20000.0, drift=0.0003, vol=0.013, seed=7,
               first_day=(2025, 8, 1)):
    """几何布朗运动日线（跳过周末），结构可被 providers 解析。"""
    rnd = random.Random(seed)
    bars, price = [], start
    day = datetime(*first_day)
    while len(bars) < n:
        day += timedelta(days=1)
        if day.weekday() >= 5:
            continue
        price = max(1.0, price * math.exp(rnd.gauss(drift, vol)))
        bars.append({
            "date": day.strftime("%Y-%m-%d"),
            "open": price * (1 - rnd.gauss(0, 0.002)),
            "high": price * (1 + abs(rnd.gauss(0, 0.006))),
            "low": price * (1 - abs(rnd.gauss(0, 0.006))),
            "close": price,
            "volume": max(1e5, 1e8 * (1 + 0.4 * rnd.gauss(0, 1))),
        })
    return bars


def make_fetcher(index_bars, stock_bars, south, north, *, top_rows=None,
                 fail_fundflow=False):
    """伪造整个网络层：识别 Yahoo / 东财三种接口，返回结构一致的假数据。"""

    def fetch_json(url, params=None, timeout=10):
        if "query1.finance.yahoo.com" in url:
            symbol = url.rsplit("/", 1)[-1].split("?")[0]
            bars = index_bars.get(symbol) or stock_bars.get(symbol)
            if not bars:
                return None
            return {
                "chart": {"result": [{
                    "timestamp": [int(datetime.strptime(b["date"], "%Y-%m-%d")
                                      .replace(tzinfo=CST).timestamp()) for b in bars],
                    "indicators": {"quote": [{
                        "open": [b["open"] for b in bars],
                        "high": [b["high"] for b in bars],
                        "low": [b["low"] for b in bars],
                        "close": [b["close"] for b in bars],
                        "volume": [b["volume"] for b in bars],
                    }]},
                    "meta": {"currency": "HKD"},
                }]}}
        if "RPT_MUTUAL_DEAL_HISTORY" in str((params or {}).get("reportName", "")):
            rows = []
            for day, amt in south:
                rows.append({"TRADE_DATE": f"{day} 00:00:00",
                             "MUTUAL_TYPE": "006", "DEAL_AMT": amt * 100})
            for day, amt in north:
                rows.append({"TRADE_DATE": f"{day} 00:00:00",
                             "MUTUAL_TYPE": "005", "DEAL_AMT": amt * 100})
            return {"result": {"data": rows}}
        if "clist/get" in url:
            rows = top_rows
            if rows is None:
                rows = [{"f12": f"{i:05d}", "f14": f"样本股{i}", "f2": 100 + i,
                         "f3": 1.2 - i * 0.05, "f6": 5e9 / (i + 1)}
                        for i in range(1, 31)]
            return {"data": {"diff": rows}}
        if "ulist.np/get" in url:
            secids = str(params.get("secids", ""))
            if secids.startswith("100."):
                return {"data": {"diff": [
                    {"f12": "HSI", "f14": "恒生指数", "f2": 25432.1,
                     "f3": 0.42, "f6": 2.1e11}]}}
            if fail_fundflow:
                return None
            codes = [s.split(".")[-1] for s in secids.split(",")]
            return {"data": {"diff": [
                {"f12": c, "f14": f"港股{c}", "f2": 100.0, "f3": 0.5,
                 "f6": 8e8 * (i + 1), "f9": 10.0 + i, "f23": 1.0 + i * 0.1,
                 "f62": 1.2e8 * (i + 1), "f184": 3.2}
                for i, c in enumerate(codes)]}}
        return None
    return fetch_json


def mutual_series(days=300, base_south=380.0, base_north=1200.0):
    """生成 ``days`` 个交易日（不是日历日）的南向 / 北向成交总额序列。"""
    south, north, day, i = [], [], datetime(2025, 8, 1), 0
    while len(south) < days:
        day += timedelta(days=1)
        if day.weekday() >= 5:
            continue
        south.append((day.strftime("%Y-%m-%d"),
                      base_south + 60 * math.sin(i / 9.0) + i * 0.6))
        north.append((day.strftime("%Y-%m-%d"),
                      base_north + 180 * math.sin(i / 7.0)))
        i += 1
    return south, north


def sample_inputs(n_stocks=6, **bar_kw):
    index_bars = {
        "^HSI": synth_bars(280, 20000, 0.00035, 0.0125, seed=11, **bar_kw),
        "^HSTECH": synth_bars(280, 4200, 0.0005, 0.019, seed=12, **bar_kw),
        "^HSCEI": synth_bars(280, 7200, 0.0002, 0.013, seed=13, **bar_kw),
    }
    universe = providers.HK_STOCK_UNIVERSE[:n_stocks]
    stock_bars = {code: synth_bars(200, 100 + i * 13, 0.0002 + i * 5e-5,
                                   0.018 + i * 0.001, seed=100 + i, **bar_kw)
                  for i, (_label, code) in enumerate(universe)}
    south, north = mutual_series()
    return index_bars, stock_bars, south, north, universe


def run_engine(tmpdir=None, **kw):
    index_bars, stock_bars, south, north, universe = sample_inputs(**kw)
    fetcher = make_fetcher(index_bars, stock_bars, south, north)
    path = os.path.join(tmpdir, "quant_history.json") if tmpdir else None
    return oq.run_quant(fetcher, history_path=path, stock_universe=universe)


# ==================================================================
# ① stats
# ==================================================================
class StatsTests(unittest.TestCase):
    def test_mean_stdev_zscore_and_percentile(self):
        self.assertAlmostEqual(stats.mean([1, 2, 3, 4]), 2.5)
        self.assertAlmostEqual(stats.stdev([2, 4, 4, 4, 5, 5, 7, 9]), 2.13809, places=4)
        self.assertIsNone(stats.mean([]))
        self.assertIsNone(stats.stdev([1.0]))
        self.assertAlmostEqual(stats.zscore(5, [1, 2, 3, 4, 5]), 1.2649, places=3)
        self.assertIsNone(stats.zscore(1, []))
        self.assertAlmostEqual(stats.percentile(list(range(101)), 0.5), 50.0)

    def test_pct_rank_bounded_and_half_for_median(self):
        xs = list(range(1, 11))
        self.assertAlmostEqual(stats.pct_rank(5.5, xs), 0.5)
        self.assertGreaterEqual(stats.pct_rank(-99, xs), 0.0)
        self.assertLessEqual(stats.pct_rank(99, xs), 1.0)

    def test_linreg_recovers_known_slope(self):
        ys = [3.0 + 2.0 * i for i in range(30)]
        reg = stats.linreg(ys)
        self.assertAlmostEqual(reg["slope"], 2.0, places=6)
        self.assertAlmostEqual(reg["r2"], 1.0, places=6)
        self.assertIsNotNone(reg["t_stat"])
        self.assertIsNone(stats.linreg([1, 2]))

    def test_rsi_bounds_and_extremes(self):
        rising = [100 + i for i in range(40)]
        falling = [140 - i for i in range(40)]
        self.assertAlmostEqual(stats.rsi(rising, 14), 100.0, places=5)
        self.assertAlmostEqual(stats.rsi(falling, 14), 0.0, places=5)
        self.assertIsNone(stats.rsi([1, 2, 3], 14))

    def test_ewma_vol_positive_and_annualizes(self):
        rnd = random.Random(3)
        rets = [rnd.gauss(0, 1.2) for _ in range(200)]
        daily = stats.ewma_vol(rets, annualize=False)
        annual = stats.ewma_vol(rets, annualize=True)
        self.assertGreater(daily, 0)
        self.assertAlmostEqual(annual / daily, math.sqrt(252), places=4)

    def test_bollinger_and_macd_shapes(self):
        closes = [100 + 10 * math.sin(i / 5.0) for i in range(120)]
        boll = stats.bollinger(closes, 20)
        self.assertGreater(boll["upper"], boll["lower"])
        self.assertGreaterEqual(boll["pctb"], 0.0)
        self.assertLessEqual(boll["pctb"], 1.0)
        dif, dea, hist = stats.macd(closes)
        self.assertIsNotNone(dif)
        self.assertAlmostEqual(hist, dif - dea, places=9)

    def test_max_drawdown_sharpe_brier_and_binomial_z(self):
        self.assertAlmostEqual(stats.max_drawdown([1.0, 1.2, 0.6, 1.0]), -50.0)
        self.assertIsNone(stats.max_drawdown([1.0]))
        self.assertAlmostEqual(stats.brier([1.0, 0.0], [1, 0]), 0.0)
        self.assertAlmostEqual(stats.brier([0.5, 0.5], [1, 0]), 0.25)
        self.assertAlmostEqual(stats.log_loss([0.5, 0.5], [1, 0]), math.log(2), places=6)
        # 100 次里 60 次命中：z ≈ 2.0
        self.assertAlmostEqual(stats.binomial_z(60, 100), 2.0, places=6)
        self.assertIsNotNone(stats.sharpe([r * 0.01 for r in range(-50, 50)]))

    def test_norm_ppf_and_prob_above(self):
        self.assertAlmostEqual(stats.norm_ppf(0.975), 1.959964, places=5)
        self.assertAlmostEqual(stats.prob_above(0.0, 1.0, 0.0), 0.5, places=6)
        self.assertIsNone(stats.prob_above(0, 0, 0))


# ==================================================================
# ② providers
# ==================================================================
class ProviderTests(unittest.TestCase):
    def test_fetch_bars_parses_yahoo_payload(self):
        bars = synth_bars(30, seed=5)
        fetcher = make_fetcher({"^HSI": bars}, {}, [], [])
        got = providers.fetch_bars(fetcher, "^HSI")
        self.assertEqual(len(got), 30)
        self.assertEqual(got[0]["date"] < got[-1]["date"], True)
        self.assertTrue(all(b["close"] > 0 for b in got))

    def test_fetch_bars_returns_empty_on_garbage(self):
        self.assertEqual(providers.fetch_bars(lambda *a, **k: {}, "^HSI"), [])
        self.assertEqual(providers.fetch_bars(lambda *a, **k: None, "^HSI"), [])
        self.assertEqual(providers.fetch_bars(None, "^HSI"), [])

    def test_mutual_series_splits_north_south_and_converts_units(self):
        south, north = mutual_series(10)
        fetcher = make_fetcher({}, {}, south, north)
        got = providers.fetch_mutual_series(fetcher)
        self.assertEqual(len(got["south"]), len(south))
        self.assertEqual(len(got["north"]), len(north))
        # DEAL_AMT 单位百万元 → 亿元（÷100），往返后应还原
        self.assertAlmostEqual(got["south"][-1][1], south[-1][1], places=6)

    def test_top_turnover_sorted_descending(self):
        fetcher = make_fetcher({}, {}, [], [])
        rows = providers.fetch_hk_top_turnover(fetcher)
        amounts = [r["amount"] for r in rows]
        self.assertEqual(amounts, sorted(amounts, reverse=True))

    def test_fundflow_degrades_to_empty_when_interface_missing(self):
        fetcher = make_fetcher({}, {}, [], [], fail_fundflow=True)
        self.assertEqual(providers.fetch_hk_fundflow(fetcher,
                                                     providers.HK_STOCK_UNIVERSE[:4]), {})


# ==================================================================
# ③ features
# ==================================================================
class FeatureTests(unittest.TestCase):
    def test_compute_features_core_keys(self):
        feat = features.compute_features(synth_bars(200, seed=21))
        self.assertTrue(feat["ok"])
        for key in ("close", "chg_pct", "sma20", "sma60", "rsi14", "vol20",
                    "mom_z20", "trend_t", "z20", "vol_ratio", "amihud", "vol_pct"):
            self.assertIn(key, feat)
            self.assertIsNotNone(feat[key], f"{key} 不应为 None")
        self.assertEqual(feat["date"], synth_bars(200, seed=21)[-1]["date"])

    def test_compute_features_rejects_short_history(self):
        self.assertFalse(features.compute_features(synth_bars(10, seed=1))["ok"])
        self.assertFalse(features.compute_features([])["ok"])

    def test_factor_scores_are_bounded_and_flow_optional(self):
        feat = features.compute_features(synth_bars(220, seed=31))
        with_flow = features.factor_scores(feat, flow_z=1.2)
        without_flow = features.factor_scores(feat)
        self.assertTrue(with_flow["ok"] and without_flow["ok"])
        for res in (with_flow, without_flow):
            self.assertLessEqual(abs(res["score"]), 2.0 + 1e-9)
        # 缺失 FLOW 因子时权重重分配，合计仍为 1
        self.assertAlmostEqual(sum(without_flow["weights_used"].values()), 1.0, places=9)
        self.assertIn("flow", without_flow["missing"])
        # 有资金流时得分应被资金方向推动
        up = features.factor_scores(feat, flow_z=1.5)["score"]
        down = features.factor_scores(feat, flow_z=-1.5)["score"]
        self.assertGreater(up, down)

    def test_trend_state_three_state_probs_sum_to_100(self):
        feat = features.compute_features(synth_bars(240, seed=41))
        label, probs, _note = features.trend_state(feat)
        self.assertIn(label, ("上升趋势", "下降趋势", "震荡整理"))
        self.assertAlmostEqual(sum(probs.values()), 100.0, places=4)
        self.assertLessEqual(max(probs.values()), 85.0 + 1e-6)
        self.assertGreaterEqual(min(probs.values()), 5.0 - 1e-6)

    def test_breadth_percentages(self):
        rows = []
        for i in range(6):
            bars = synth_bars(160, 100 + i * 10, seed=200 + i)
            rows.append({"feat": features.compute_features(bars)})
        b = features.breadth(rows)
        self.assertTrue(b["available"])
        self.assertEqual(b["n"], 6)
        for key in ("above20_pct", "above60_pct", "bull_align_pct", "up20_pct", "score"):
            self.assertGreaterEqual(b[key], 0.0)
            self.assertLessEqual(b[key], 100.0)


# ==================================================================
# ④ probability（含「防自欺」测试）
# ==================================================================
class ProbabilityTests(unittest.TestCase):
    def test_forward_outcomes_uses_only_future_data(self):
        closes = [10.0, 11.0, 10.5, 12.0, 11.0]
        out = probability.forward_outcomes(closes, 1)
        # 末位无法计算未来 → None；其余与「下一日是否上涨」一致
        self.assertIsNone(out[-1])
        self.assertEqual(out[0], 1.0)   # 10 → 11 涨
        self.assertEqual(out[1], 0.0)   # 11 → 10.5 跌
        self.assertEqual(out[2], 1.0)
        self.assertEqual(out[3], 0.0)

    def test_isotonic_is_monotone(self):
        blocks = probability._pava([0.9, 0.2, 0.7, 0.1], [1, 1, 1, 1])
        vals = [b[0] for b in blocks]
        self.assertEqual(vals, sorted(vals))

    def test_calibrator_monotone_bounded_and_shrunk(self):
        rnd = random.Random(9)
        scores, outcomes = [], []
        for i in range(400):
            s = rnd.uniform(-2, 2)
            p_true = 1.0 / (1.0 + math.exp(-s))
            scores.append(s)
            outcomes.append(1.0 if rnd.random() < p_true else 0.0)
        cal = probability.fit_calibrator(scores, outcomes)
        self.assertEqual(cal.method, "blend")
        lo = cal.predict(-2.0)
        mid = cal.predict(0.0)
        hi = cal.predict(2.0)
        self.assertGreater(hi, mid)
        self.assertGreater(mid, lo)
        for p in (lo, mid, hi):
            self.assertGreaterEqual(p, probability.PROB_FLOOR)
            self.assertLessEqual(p, probability.PROB_CAP)
        # 真实概率 0.5 附近的校准误差不应过大
        self.assertLess(abs(mid - 0.5), 0.12)

    def test_calibrator_falls_back_to_base_when_samples_short(self):
        cal = probability.fit_calibrator([0.1, -0.2], [1.0, 0.0])
        self.assertEqual(cal.method, "base")
        self.assertEqual(cal.predict(1.5), 0.5)

    def test_walk_forward_calibration_window_contains_past_only(self):
        """结构性验证：第 t 步的校准器只能收到 [0, t) 的得分与标签。

        这是对「无未来函数」最强的断言——直接检查喂给校准器的数据窗口，
        而不是间接猜胜率。若实现里误用全量数据，窗口长度会恒等于 n。
        """
        closes = [b["close"] for b in synth_bars(200, seed=99)]
        scores = [float(i % 7 - 3) for i in range(len(closes))]
        seen = []
        real_fit = probability.fit_calibrator

        def spy(scores_, outcomes_, **kw):
            seen.append((len(scores_), list(outcomes_)))
            return real_fit(scores_, outcomes_, **kw)

        probability.fit_calibrator = spy
        try:
            probability.walk_forward(scores, closes, horizons=(1,), min_train=60)
        finally:
            probability.fit_calibrator = real_fit

        self.assertTrue(seen)
        lengths = [item[0] for item in seen]
        self.assertEqual(lengths, list(range(60, 60 + len(lengths))))
        # 标签窗口必须与长度一致（不含第 t 个及之后的未来标签）
        full_outcomes = probability.forward_outcomes(closes, 1)
        for idx, (_n, outs) in enumerate(seen):
            t = 60 + idx
            self.assertEqual(len(outs), t)
            self.assertEqual(len(outs), len(full_outcomes[:t]))

    def test_walk_forward_gives_no_spurious_skill_on_random_walk(self):
        """随机游走 + 纯噪声得分：不该凭空产生高胜率。"""
        closes = [b["close"] for b in synth_bars(320, seed=1234)]
        rnd = random.Random(2024)
        scores = [rnd.uniform(-1, 1) for _ in closes]
        val = probability.walk_forward(scores, closes, horizons=(1, 5), min_train=60)
        for horizon, row in val.items():
            self.assertGreater(row["hit_rate"], 0.30, f"{horizon} 日胜率过低")
            self.assertLess(row["hit_rate"], 0.70, f"{horizon} 日胜率虚高（疑有未来函数）")

    def test_walk_forward_metrics_shape(self):
        bars = synth_bars(260, seed=77)
        closes = [b["close"] for b in bars]
        scores = [0.0] * len(closes)
        val = probability.walk_forward(scores, closes, horizons=(1, 5), min_train=60)
        self.assertIn(1, val)
        self.assertIn(5, val)
        for row in val.values():
            self.assertGreater(row["n"], 0)
            self.assertGreaterEqual(row["hit_rate"], 0.0)
            self.assertLessEqual(row["hit_rate"], 1.0)

    def test_forecast_bands_ordering_and_width(self):
        bars = synth_bars(200, seed=88)
        closes = [b["close"] for b in bars]
        bands = probability.forecast_bands(closes[-1], stats.log_returns(closes), 5)
        self.assertLess(bands["lo95"], bands["lo68"])
        self.assertLess(bands["lo68"], bands["hi68"])
        self.assertLess(bands["hi68"], bands["hi95"])
        # 期限越长区间越宽
        wide = probability.forecast_bands(closes[-1], stats.log_returns(closes), 20)
        self.assertGreater(wide["hi95"] - wide["lo95"], bands["hi95"] - bands["lo95"])

    def test_summarize_validation_mentions_sample_and_hit_rate(self):
        text = probability.summarize_validation(
            {1: {"n": 120, "hit_rate": 0.55, "base_rate": 0.52, "z": 2.1,
                 "brier": 0.24, "reliability": []}}, 1)
        self.assertIn("120", text)
        self.assertIn("55.0%", text)
        self.assertIn("显著", text)


# ==================================================================
# ⑤ liquidity（资金流动性）
# ==================================================================
class LiquidityTests(unittest.TestCase):
    def test_flow_stats_core_fields(self):
        south, _north = mutual_series(80)
        s = liquidity.flow_stats(south)
        self.assertTrue(s["available"])
        for key in ("latest", "ma5", "ma20", "chg_pct", "z20", "pct60", "slope5_t"):
            self.assertIsNotNone(s[key], key)
        self.assertLessEqual(s["pct60"], 1.0)

    def test_flow_stats_unavailable_when_short_or_empty(self):
        self.assertFalse(liquidity.flow_stats([])["available"])
        self.assertFalse(liquidity.flow_stats([("2026-01-01", 1.0)])["available"])

    def test_amihud_series_reflects_liquidity(self):
        tight = [{"close": 100 * (1 + 0.001 * (i % 3 - 1)), "volume": 1e9}
                 for i in range(60)]
        loose = [{"close": 100 * (1 + 0.05 * (i % 3 - 1)), "volume": 1e6}
                 for i in range(60)]
        self.assertLess(liquidity.amihud_series(tight)[-1],
                        liquidity.amihud_series(loose)[-1])

    def test_concentration_cr5_between_zero_and_hundred(self):
        rows = [{"amount": 1e9 * (30 - i), "name": f"s{i}"} for i in range(30)]
        conc = liquidity.concentration(rows)
        self.assertTrue(conc["available"])
        self.assertGreater(conc["cr5"], 0)
        self.assertLessEqual(conc["cr5"], 100)
        self.assertGreater(conc["cr20"], conc["cr5"])

    def test_analyze_score_bounded_and_delta_prob_small(self):
        index_bars = synth_bars(260, seed=55)
        south, north = mutual_series(120)
        res = liquidity.analyze(south=south, north=north, index_bars=index_bars,
                                top_turnover=[{"amount": 1e9 * (30 - i), "name": f"s{i}"}
                                              for i in range(30)])
        self.assertTrue(res["available"])
        self.assertGreaterEqual(res["score"], 0.0)
        self.assertLessEqual(res["score"], 100.0)
        self.assertIsNotNone(res["flow_z"])
        self.assertLessEqual(abs(res["delta_prob"]), 0.05 + 1e-9)
        self.assertIn(res["label"], ("流动性极度宽松", "流动性偏宽松", "流动性中性",
                                     "流动性偏紧", "流动性紧张"))
        # 每个分项权重合计为 1
        self.assertAlmostEqual(sum(c["weight"] for c in res["components"].values()),
                               1.0, places=6)

    def test_cr5_uses_journal_history_percentile_when_available(self):
        index_bars = synth_bars(260, seed=56)
        history = [{"cr5": 30.0 + (i % 10)} for i in range(40)]
        top = [{"amount": 1e9 * (30 - i), "name": f"s{i}"} for i in range(30)]
        res = liquidity.analyze(south=[], north=[], index_bars=index_bars,
                                top_turnover=top, history=history)
        self.assertIn("cr5", res["components"])
        self.assertIn("留痕分位", res["components"]["cr5"]["note"])

    def test_market_amount_prefers_eastmoney_quote_not_yahoo_volume(self):
        """恒指成交额必须取东财实时字段，不能用 Yahoo 成交量 × 点位换算。"""
        index_bars = synth_bars(260, seed=57)
        res = liquidity.analyze(
            south=[], north=[], index_bars=index_bars,
            index_quotes={"HSI": {"name": "恒生指数", "price": 25000.0,
                                  "chg_pct": 0.4, "amount": 2.1e11}})
        self.assertAlmostEqual(res["turnover"]["market_amount_yi"], 2100.0, places=1)
        self.assertAlmostEqual(res["depth"]["market_amount_yi"], 2100.0, places=1)
        # 没有东财报价时该字段应为 None，而不是拿 Yahoo 成交量硬凑
        res2 = liquidity.analyze(south=[], north=[], index_bars=index_bars)
        self.assertIsNone(res2["turnover"]["market_amount_yi"])

    def test_analyze_degrades_gracefully_when_nothing_available(self):
        res = liquidity.analyze()
        self.assertFalse(res["available"])
        self.assertIsNone(res["score"])
        self.assertEqual(res["label"], "数据不足")


# ==================================================================
# ⑥ engine + 留痕闭环
# ==================================================================
class EngineTests(unittest.TestCase):
    def test_run_returns_full_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_engine(tmpdir=tmp)
        self.assertTrue(res["available"], res.get("reason"))
        self.assertTrue(res["as_of"])
        self.assertTrue(res["target_date"])
        self.assertIn(res["target_label"].split()[0], ("今日", "下一交易日"))
        self.assertGreaterEqual(len(res["indices"]), 2)
        for row in res["indices"]:
            self.assertIn(row["label"], ("恒生指数", "恒生科技", "国企指数"))
            for h in oq.FORECAST_HORIZONS:
                p = row["probs"][h]["p_up"]
                self.assertGreaterEqual(p, probability.PROB_FLOOR)
                self.assertLessEqual(p, probability.PROB_CAP)
        self.assertTrue(res["stocks"])
        for row in res["stocks"]:
            for key in ("main_net_yi", "main_pct", "main_amount", "pe_ttm", "pb", "quote_as_of"):
                self.assertIn(key, row)
        self.assertIsNotNone(res["stocks"][0]["pe_ttm"])
        self.assertIsNotNone(res["stocks"][0]["pb"])
        self.assertIn(res["primary"]["label"], ("恒生指数", "恒生科技", "国企指数"))
        self.assertTrue(res["breadth"]["available"])
        self.assertTrue(res["liquidity"]["available"])
        self.assertIn(1, res["validation"])
        self.assertIn("text", res["headline"])

    def test_probabilities_never_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_engine(tmpdir=tmp)
        for row in res["indices"] + res["stocks"]:
            for h in row["probs"]:
                p = row["probs"][h]["p_up"]
                if p is None:
                    continue
                self.assertGreaterEqual(p, 0.05)
                self.assertLessEqual(p, 0.95)

    def test_validation_has_no_future_leakage_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_engine(tmpdir=tmp)
        row = res["validation"][1]
        self.assertGreater(row["n"], 20)
        self.assertGreaterEqual(row["hit_rate"], 0.0)
        self.assertLessEqual(row["hit_rate"], 1.0)
        self.assertIsNotNone(row["brier"])
        self.assertLessEqual(row["brier"], 0.30)   # 好于「乱猜 0.5」的 0.25 附近

    def test_journal_written_then_resolved_on_later_run(self):
        index_bars, stock_bars, south, north, universe = sample_inputs()
        fetcher = make_fetcher(index_bars, stock_bars, south, north)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "quant_history.json")
            oq.run_quant(fetcher, history_path=path, stock_universe=universe)
            with open(path, "r", encoding="utf-8") as fh:
                journal = json.load(fh)
            self.assertEqual(len(journal["days"]), 1)
            day = list(journal["days"])[0]
            entry = journal["days"][day]
            self.assertIn("target", entry)
            self.assertIn("marks", entry)
            self.assertIn("liq", entry)              # 流动性指标留痕
            self.assertIn("cr5", entry["liq"])

            # 手工把目标日改成历史中已存在的日期 → 下次运行应结算出命中率
            bars = index_bars["^HSI"]
            target = bars[len(bars) - 3]["date"]
            journal["days"][day]["target"] = target
            # 让预测日早于目标日
            journal["days"] = {bars[len(bars) - 6]["date"]: journal["days"][day]}
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(journal, fh)

            res2 = oq.run_quant(fetcher, history_path=path, stock_universe=universe)
            self.assertGreaterEqual(res2["journal"]["n"], 1)
            self.assertIsNotNone(res2["journal"]["hit_rate"])
            self.assertLessEqual(res2["journal"]["hit_rate"], 1.0)
            self.assertTrue(res2["journal"]["recent"])

    def test_engine_disabled_without_fetcher(self):
        res = oq.run_quant(None)
        self.assertFalse(res["available"])
        self.assertEqual(res["reason"], "未取得港股指数日线")

    def test_next_trading_day_skips_weekend(self):
        self.assertEqual(engine._next_trading_day("2026-09-25"), "2026-09-28")  # 周五→周一
        self.assertEqual(engine._next_trading_day("2026-09-28"), "2026-09-29")


# ==================================================================
# ⑦ render + pipeline 集成
# ==================================================================
class RenderIntegrationTests(unittest.TestCase):
    def test_render_sections_contain_expected_titles(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_engine(tmpdir=tmp)
        kit = pipeline.GUIZANG_KIT
        fc = render.render_forecast(res, kit)
        hk = render.render_hk_probability(res, kit)
        lq = render.render_liquidity(res, kit)
        self.assertIn("预测概括", fc)
        self.assertIn("模型可信度", fc)
        self.assertIn("个股概率", hk)
        self.assertIn("南向", lq)
        self.assertIn("流动性综合分", lq)
        # 缺数据不写 0，只写「暂缺」
        for html in (fc, hk, lq):
            self.assertNotIn("0.00% 亿", html)

    def test_pixel_kit_renders_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_engine(tmpdir=tmp)
        html = render.render_forecast(res, pipeline.PIXEL_KIT)
        self.assertIsInstance(html, str)
        self.assertIn("预测概括", html)

    def test_daily_conclusion_labels_quantitative_forecast_as_analysis(self):
        quant = {
            "available": True,
            "headline": {"available": True, "arrow": "■", "label": "中性", "p_up": 0.55},
            "target_label": "下一交易日",
        }
        weekly = {"available": True, "entry": {
            "p_up": 0.53, "target_sessions": 7, "base_date": "2026-09-28",
            "label": "▲ 看涨 · P(7日涨) 53%"}}
        pairs = pipeline._conclusion_pairs(
            pipeline.GUIZANG_KIT, None, None, None, None, quant=quant, weekly=weekly)
        self.assertEqual(pairs[0][0], "量化分析")
        panel = pipeline._conclusion_panel(pipeline.GUIZANG_KIT, pairs)
        self.assertIn("量化分析", panel)
        # 2026-10-23 用户要求：今日预判不显示涨跌概率 → 只留方向定调与目标交易日
        self.assertIn("中性", panel)
        self.assertIn("▲ 看涨", panel)          # 七日预测只留方向
        for token in ("55%", "53%", "P(7日涨)"):
            self.assertNotIn(token, panel)

    def test_report_includes_quant_sections_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_engine(tmpdir=tmp)
        data = {
            "实时行情": pipeline._source_result(
                "test quote", "success", is_today=True,
                quotes={"标普500": {"price": 6123.45, "change_pct": 1.25,
                                    "currency": "USD"}}),
            "港股量化": pipeline._source_result(
                "港股量化引擎", "success", is_today=False,
                content_date=res["as_of"], result=res),
        }
        parts = pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT,
                                               date_str=res["as_of"].replace("-", ""))
        kickers = [s[0] for s in parts["sections"]]
        # 2026-10-23「量化分析总览」整栏下线：概率只留在资金流动性与逐日推演两栏
        self.assertNotIn("QUANT FORECAST", kickers)
        self.assertIn("LIQUIDITY FLOW", kickers)
        self.assertIn("WEEKLY FORECAST", kickers)
        self.assertNotIn("HK PROBABILITY", kickers)
        self.assertLess(kickers.index("LIQUIDITY FLOW"),
                        kickers.index("WEEKLY FORECAST"))
        # 港股概率走势分析已作为子块合入同一个逐日趋势量化推演栏目。
        weekly_section = next(s for s in parts["sections"] if s[0] == "WEEKLY FORECAST")
        self.assertIn("港股概率走势分析", weekly_section[2])
        # 2026-10-14 重排：量化栏目（③可能会怎样）位于行情复盘（①发生了什么）之后
        self.assertLess(kickers.index("MARKET REVIEW"),
                        kickers.index("LIQUIDITY FLOW"))

    def test_generated_html_has_quant_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_engine(tmpdir=tmp)
        data = {
            "实时行情": pipeline._source_result(
                "test quote", "success", is_today=True,
                quotes={"标普500": {"price": 6123.45, "change_pct": 1.25,
                                    "currency": "USD"}}),
            "港股量化": pipeline._source_result(
                "港股量化引擎", "success", is_today=False,
                content_date=res["as_of"], result=res),
        }
        html = pipeline.generate_report(data, "2026年9月28日 · 周一",
                                       res["as_of"].replace("-", ""))
        for title in ("每日趋势量化推演", "港股概率走势分析", "资金流动性分析"):
            self.assertIn(title, html)
        # 2026-10-23 整栏下线：标题 / 栏目都不再出现在页面
        self.assertNotIn("量化分析总览", html)
        self.assertEqual(html.count("每日趋势量化推演</h2>"), 1)
        self.assertNotIn("港股概率走势分析</h2>", html)
        # 2026-10-23 起「量化分析总览」下线，「预测概括 / 指数概率」等块随该栏一并消失
        self.assertNotIn("预测概括", html)

    def test_forecast_section_never_shows_updown_probability(self):
        """2026-10-23 用户要求：今日预判只给方向，不显示涨跌概率 / 几率条。"""
        with tempfile.TemporaryDirectory() as tmp:
            res = run_engine(tmpdir=tmp)
        data = {
            "港股量化": pipeline._source_result(
                "港股量化引擎", "success", is_today=False,
                content_date=res["as_of"], result=res),
            "每周走势预测": pipeline._source_result(
                "每周量化走势预测", "success", is_today=False,
                content_date=res["as_of"],
                result={"available": True,
                        "entry": {"p_up": 0.53, "target_sessions": 7,
                                  "label": "▲ 看涨 · P(7日涨) 53%"}}),
        }
        parts = pipeline._collect_report_parts(
            data, pipeline.GUIZANG_KIT, date_str=res["as_of"].replace("-", ""))
        content = next(s[2] for s in parts["sections"] if s[0] == "FORECAST")
        self.assertIn("量化分析", content)
        self.assertIn("▲ 看涨", content)          # 七日预测只留方向定调
        for token in ("ODDS METER", "上涨概率", "P(7日涨)", "几率"):
            self.assertNotIn(token, content)

    def test_report_without_quant_source_does_not_break(self):
        data = {"实时行情": pipeline._source_result("test quote", "unavailable",
                                                quotes={}, error="offline")}
        html = pipeline.generate_report(data, "2026年9月28日 · 周一", "20260928",
                                       theme="guizang")
        self.assertNotIn("量化分析总览", html)   # 改名后仍不得出现（含鱼名前缀版本）
        self.assertIn("总结</h2>", html)  # 栏目名 2026-09-28 由「盘点总结」改为「总结」


if __name__ == "__main__":
    unittest.main()
