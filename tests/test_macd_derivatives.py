"""派生规则离线回归：相关信号去重、极值、形态确认、布林状态、真周线及取数补长。"""
import copy
import json
import math
import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch

from test_macd_strategy import NOW, bars, chart as close_chart, macd, market_db, pipeline, providers, stats
from octopus_quant import macd_derivatives as d


def chart(series):
    payload = close_chart(series)
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    for field in ("open", "high", "low", "volume"):
        quote[field] = [b.get(field) for b in series]
    return payload


def sequence(hist, dif=None):
    """手工指标夹具：hist 是国内双倍柱，绝不用待测 MACD 内核构造期望。"""
    dif = dif if dif is not None else [h / 2 for h in hist]
    return [(None, None, None) if i < 34 else (f, f - h / 2, h / 2)
            for i, (h, f) in enumerate(zip(hist, dif))]


def slope_fixture(red=False):
    series = bars([100.0] * 100)
    anchor = len(series) - 4
    series[anchor]["close"] = 110.0 if red else 90.0
    series[anchor]["high"] = series[anchor]["low"] = series[anchor]["close"]
    hist = [0.2 if red else -0.2] * len(series)
    hist[-4:] = [6, 5, 4, 3] if red else [-6, -5, -4, -3]
    return series, sequence(hist)


def divergence_fixture(n=80, p1=40, p2=55, d1=41, d2=56):
    series = bars([100.0] * n)
    series[p1]["low"], series[p2]["low"] = 90.0, 88.0
    dif = [-1.0] * n
    dif[d1], dif[d2] = -8.0, -5.0
    return series, sequence([-0.2] * n, dif=dif)


def bb_fixture(up=False):
    prices = [110 + i * .5 for i in range(70)] if up else [100 + (-1) ** i for i in range(70)]
    series = bars(prices)
    band = stats.bollinger(prices[:-1])
    series[-1].update(close=(band["upper"] + 1 if up else 99.0),
                      low=(band["upper"] if up else band["lower"] - 1),
                      high=(band["upper"] + 2 if up else 100.0))
    hist = [0.5] * 70 if up else [-0.5] * 67 + [-3.0, -2.0, -1.0]
    base = {"cross": None, "dif": 1.0, "dea": .5, "as_of": series[-1]["date"]}
    return series, sequence(hist), base


def native_fixture(n=52, end=date(2026, 9, 25), monday=True):
    return [{"date": (end - timedelta(weeks=n - 1 - i, days=4 if monday else 0)).isoformat(),
             "close": 100 + .5 * i * i} for i in range(n)]


def weekly_base(series, *, golden=True, water=True):
    return {"cross": "golden" if golden else None, "dif": 1.0 if water else -1.0,
            "dea": .5 if water else -2.0, "as_of": series[-1]["date"]}


def result_of(row):
    return {"available": True, "items": [row], "coverage": {"valid": 1, "total": 1},
            "golden_n": int(row["cross"] == "golden"), "death_n": int(row["cross"] == "death"),
            "as_of": row["as_of"], "latest_as_of": row["as_of"], "missing": [], "warnings": []}


class MergeAndIsolationTests(unittest.TestCase):
    def test_dif_only_above_zero_does_not_relax_existing_double_line_gate(self):
        series = bars(n=70)
        points = [(None, None, None)] * 34 + [(-2.0, -1.0, -1.0)] * 35 + [(1.0, -1.0, 2.0)]
        with patch.object(stats, "macd_series", return_value=points):
            row = macd.analyze_bars(series, label="恒指", code="^HSI", now=NOW)
        self.assertEqual(row["cross"], "golden")
        self.assertTrue(row["zero_filter"]["relaxed_only"])
        self.assertFalse(row["zero_filter"]["long_allowed"])
        self.assertEqual(row["action_key"], "watch")
        self.assertEqual(set(row["derived"]), set(d.KEYS))  # 无重复第五票

    def test_left_side_warning_never_overrides_bearish_base_action(self):
        series, points = slope_fixture()
        with patch.object(stats, "macd_series", return_value=points):
            row = macd.analyze_bars(series, label="恒指", code="^HSI", now=NOW)
        self.assertTrue(row["derived"]["slope"]["active"])
        self.assertEqual(row["action_key"], "exit")
        self.assertEqual(row["derived"]["slope"]["role"], "动能预警")

    def test_large_finite_prices_keep_base_when_bollinger_overflows(self):
        series = bars([1e200 * (1 + .001 * i + .01 * math.sin(i)) for i in range(100)])
        row = macd.analyze_bars(series, label="极端值", code="^HSI", now=NOW)
        self.assertTrue(row["available"])
        self.assertFalse(row["derived"]["bollinger"]["available"])
        self.assertIn("OverflowError", row["derived"]["bollinger"]["reason"])
        json.dumps(row, allow_nan=False)

    def test_nonfinite_ratios_do_not_leak_into_json_or_drop_base(self):
        row = macd.analyze_bars(bars([1e300] * 70 + [1e-300] * 30), label="比例极值", code="^HSI", now=NOW)
        self.assertTrue(row["available"])
        json.dumps(row, allow_nan=False)
        self.assertTrue(all(d._all_finite(r) for r in row["derived"].values()))


class HistogramTests(unittest.TestCase):
    def test_three_negative_contractions_after_extreme_and_decline_warn(self):
        series, points = slope_fixture()
        record = d.histogram_reversal(series, points)
        self.assertTrue(record["active"])
        self.assertTrue(record["triggered"])
        self.assertEqual(record["streak"], 3)
        self.assertEqual(record["signal"], "rebound_warning")
        self.assertEqual(record["anchor_date"], series[-4]["date"])
        self.assertEqual(record["baseline_n"], 60)
        self.assertAlmostEqual(record["q10"], -.2)  # 不含 -6 的极值当天
        self.assertAlmostEqual(record["hist_pct"], -6 / 90 * 100)
        self.assertAlmostEqual(record["drawdown_pct"], -10)

    def test_fourth_contraction_is_continuation_not_another_event(self):
        series, points = slope_fixture()
        series.append({"date": "2026-10-01", "close": 95.0})
        points.append((-1.0, 0.0, -1.0))
        record = d.histogram_reversal(series, points)
        self.assertTrue(record["active"])
        self.assertFalse(record["triggered"])
        self.assertEqual(record["streak"], 4)
        self.assertEqual(record["anchor_date"], series[-5]["date"])

    def test_positive_contractions_warn_to_trim_not_to_short(self):
        series, points = slope_fixture(red=True)
        record = d.histogram_reversal(series, points)
        self.assertTrue(record["triggered"])
        self.assertEqual(record["signal"], "trim_warning")
        self.assertAlmostEqual(record["advance_pct"], 10)

    def test_needs_extreme_price_move_and_consecutive_three(self):
        series, points = slope_fixture()
        flat = copy.deepcopy(series)
        for bar in flat:
            bar["close"] = 100.0
        self.assertFalse(d.histogram_reversal(flat, points)["active"])
        for tail in ([-6, -5, -5.5, -4], [-.2, -6, -5, -4], [-6, -5, -4, 1]):
            p = sequence([-.2] * 96 + tail)
            self.assertFalse(d.histogram_reversal(series, p)["active"])
        hist = [-7.0] * 95 + [-.5, -6, -5, -4, -3]
        self.assertFalse(d.histogram_reversal(series, sequence(hist))["active"])

    def test_extreme_is_scale_invariant_not_cross_asset_raw_macd_rank(self):
        series, points = slope_fixture()
        original = d.histogram_reversal(series, points)
        scaled = [{**b, "close": b["close"] * 1000} for b in series]
        scaled_points = [tuple(v * 1000 if v is not None else None for v in p) for p in points]
        other = d.histogram_reversal(scaled, scaled_points)
        for key in ("hist_pct", "q10", "q90", "drawdown_pct"):
            self.assertAlmostEqual(original[key], other[key])
        self.assertEqual(other["triggered"], original["triggered"])

    def test_short_history_is_missing_not_neutral(self):
        series, points = slope_fixture()
        record = d.histogram_reversal(series[:67], points[:67])
        self.assertFalse(record["available"])
        self.assertFalse(record["active"])
        self.assertNotIn("q10", record)


class DivergenceTests(unittest.TestCase):
    def test_waits_for_matching_window_and_dates_signal_at_confirmation(self):
        series, points = divergence_fixture()
        before = d.bottom_divergence(series[:60], points[:60])
        self.assertFalse(before["active"])
        after = d.bottom_divergence(series[:61], points[:61])
        self.assertTrue(after["triggered"])
        self.assertEqual(after["confirmed_at"], series[60]["date"])
        self.assertEqual(after["price2_date"], series[55]["date"])
        self.assertEqual(after["dif2_date"], series[56]["date"])
        self.assertGreater(after["confirmed_at"], after["price2_date"])
        self.assertFalse(after["zero_path"])  # 经典双谷均在水下，不强制跨轴

    def test_event_prefix_does_not_repaint_after_future_bars(self):
        series, points = divergence_fixture()
        points[65] = (-20.0, -19.9, -.1)
        full = d.divergence_events(series, points)
        for length in (45, 56, 60, 61, 65, 70, 80):
            prefix = d.divergence_events(series[:length], points[:length])
            self.assertEqual(prefix, [e for e in full if e["confirmed"] < length])

    def test_zero_down_then_rise_is_extra_tag_not_a_second_vote(self):
        series, points = divergence_fixture()
        points[49], points[50], points[51] = (1, 1.1, -.1), (-.5, -.4, -.1), (0, .1, -.1)
        record = d.bottom_divergence(series[:61], points[:61])
        self.assertTrue(record["active"])
        self.assertTrue(record["zero_path"])
        self.assertEqual(record["signal"], "bullish_divergence")

    def test_breaking_second_low_invalidates_and_old_patterns_expire(self):
        series, points = divergence_fixture()
        expired = d.bottom_divergence(series[:72], points[:72])
        self.assertFalse(expired["active"])
        self.assertIn("过期", expired["summary"])
        series[61]["low"] = 80
        broken = d.bottom_divergence(series[:62], points[:62])
        self.assertFalse(broken["active"])
        self.assertTrue(broken["invalidated"])
        self.assertIn("失效", broken["summary"])

    def test_low_broken_while_waiting_for_matching_confirmation_never_becomes_signal(self):
        series, points = divergence_fixture()
        series[58]["low"] = 80  # 价格谷 p2=55 的左右 2 根已确认，但最终匹配尚未完成
        self.assertEqual(d.divergence_events(series[:61], points[:61]), [])
        self.assertFalse(d.bottom_divergence(series[:61], points[:61])["active"])
        series[58]["low"] = None
        self.assertEqual(d.divergence_events(series[:61], points[:61]), [])

    def test_requires_lower_price_higher_negative_dif_and_minimum_spacing(self):
        series, points = divergence_fixture()
        for price2 in (90, 89.9):
            altered = copy.deepcopy(series)
            altered[55]["low"] = price2
            self.assertFalse(d.bottom_divergence(altered[:61], points[:61])["active"])
        altered_points = list(points)
        altered_points[56] = (-10, -9.9, -.1)
        self.assertFalse(d.bottom_divergence(series[:61], altered_points[:61])["active"])
        short, short_points = divergence_fixture(p2=43, d2=44)
        self.assertFalse(d.bottom_divergence(short[:61], short_points[:61])["active"])

    def test_rejects_unmatched_or_reused_dif_pivot_and_price_platform(self):
        series, points = divergence_fixture(d2=59)
        self.assertFalse(d.bottom_divergence(series[:65], points[:65])["active"])
        series, points = divergence_fixture(p2=45, d1=43, d2=43)
        self.assertFalse(d.bottom_divergence(series[:65], points[:65])["active"])
        series, points = divergence_fixture()
        series[54]["low"] = series[55]["low"]
        self.assertFalse(d.bottom_divergence(series[:61], points[:61])["active"])

    def test_missing_or_invalid_lows_are_not_faked_from_close(self):
        series, points = divergence_fixture()
        for bar in series:
            bar["low"] = None
        record = d.bottom_divergence(series, points)
        self.assertFalse(record["available"])
        self.assertNotIn("price2", record)
        for invalid in (True, float("nan"), 10000):
            changed, seq = divergence_fixture()
            changed[55]["low"] = invalid
            self.assertFalse(d.bottom_divergence(changed[:61], seq[:61])["active"])


class BollingerTests(unittest.TestCase):
    def test_requires_touch_reentry_momentum_and_flat_midline(self):
        series, points, base = bb_fixture()
        record = d.bollinger_reversion(series, points, base)
        self.assertTrue(record["triggered"])
        self.assertEqual(record["signal"], "reversion_watch")
        self.assertTrue(record["ranging"])
        self.assertEqual(record["bands"], stats.bollinger([b["close"] for b in series[:-1]]))
        self.assertEqual(record["band_date"], series[-2]["date"])

    def test_touch_without_reentry_or_momentum_is_not_entry(self):
        series, points, base = bb_fixture()
        series[-1].update(close=94, low=93, high=95)
        record = d.bollinger_reversion(series, points, base)
        self.assertTrue(record["touched_low"])
        self.assertFalse(record["reclaimed"])
        self.assertFalse(record["active"])
        series, points, base = bb_fixture()
        self.assertFalse(d.bollinger_reversion(series, sequence([-.5] * 70), base)["active"])
        base["cross"] = "golden"
        self.assertTrue(d.bollinger_reversion(series, sequence([-.5] * 70), base)["active"])

    def test_steep_downtrend_rejects_left_side_lower_band_setup(self):
        series = bars([110 - .5 * i for i in range(70)])
        band = stats.bollinger([b["close"] for b in series[:-1]])
        series[-1].update(close=band["lower"] + .25, low=band["lower"] - 1, high=band["lower"] + 1)
        record = d.bollinger_reversion(series, sequence([-.5] * 67 + [-3, -2, -1]), {"cross": None})
        self.assertTrue(record["touched_low"])
        self.assertTrue(record["repair"])
        self.assertFalse(record["ranging"])
        self.assertFalse(record["active"])

    def test_strong_band_walking_is_not_forced_exit_but_death_cross_is(self):
        series, points, base = bb_fixture(up=True)
        record = d.bollinger_reversion(series, points, base)
        self.assertTrue(record["touched_high"])
        self.assertFalse(record["active"])
        self.assertIn("不自动卖", record["summary"])
        base["cross"] = "death"
        record = d.bollinger_reversion(series, points, base)
        self.assertEqual(record["signal"], "reversion_exit")
        self.assertIn("沿用基础", record["summary"])

    def test_ranging_upper_touch_is_only_reversion_exit_hint_and_pctb_unbounded(self):
        series, points, base = bb_fixture()
        series[-1].update(close=110, low=105, high=111)
        record = d.bollinger_reversion(series, points, base)
        self.assertEqual(record["signal"], "reversion_exit")
        self.assertGreater(record["pctb"], 1)

    def test_touching_both_bands_does_not_invent_intraday_execution_order(self):
        series, points, base = bb_fixture()
        series[-1]["high"] = 105
        record = d.bollinger_reversion(series, points, base)
        self.assertTrue(record["touched_low"] and record["touched_high"])
        self.assertTrue(record["ambiguous_touch"])
        self.assertFalse(record["triggered"])
        self.assertIn("路径未知", record["summary"])

    def test_zero_width_or_missing_ohlc_is_disclosed(self):
        for series in (bars([100.0] * 70), bars(n=70)):
            if series[-1]["close"] != 100:
                series[-1]["high"] = None
            record = d.bollinger_reversion(series, sequence([-.5] * 70), {"cross": None})
            self.assertFalse(record["available"])
            self.assertFalse(record["active"])


class WeeklyTests(unittest.TestCase):
    def test_actual_week_count_and_weekly_macd_not_daily_sampling(self):
        series = bars([100 + .01 * i * i for i in range(260)])
        record = d.weekly_daily_confluence(series, "^HSI", weekly_base(series), now=NOW)
        weeks = d.completed_weeks(series, "^HSI", now=NOW)
        expected = stats.macd([w["close"] for w in weeks])
        self.assertTrue(record["triggered"])
        self.assertEqual(record["weekly_bars"], len(weeks))
        self.assertEqual((record["weekly_dif"], record["weekly_dea"], record["weekly_hist"]),
                         (expected[0], expected[1], 2 * expected[2]))
        self.assertNotEqual(record["weekly_dif"], stats.macd([b["close"] for b in series])[0])
        self.assertEqual(record["week_end"], "2026-09-25")

    def test_incomplete_week_is_excluded_even_when_wall_clock_advances(self):
        series = bars(n=260)
        original = d.completed_weeks(series, "^HSI", now=NOW)
        changed = copy.deepcopy(series)
        changed[-1]["close"] = 9999999
        self.assertEqual(original, d.completed_weeks(changed, "^HSI", now=NOW.replace(day=20)))
        for day in ("2026-10-01", "2026-10-02"):
            changed.append({"date": day, "close": 5000000})
        self.assertEqual(original, d.completed_weeks(changed, "^HSI", now=NOW))
        after = d.completed_weeks(changed, "^HSI", now=NOW.replace(hour=17))
        self.assertEqual(after[-1]["week_end"], "2026-10-02")
        self.assertEqual(after[-1]["close"], 5000000)

    def test_36_daily_bars_do_not_masquerade_as_35_weeks(self):
        series = bars(n=36)
        record = d.weekly_daily_confluence(series, "^HSI", weekly_base(series), now=NOW)
        self.assertFalse(record["available"])
        self.assertIn("周", record["reason"])
        self.assertNotIn("weekly_dif", record)

    def test_weekly_positive_gap_is_not_weekly_above_zero_or_months_safe(self):
        series = bars([200 - .3 * min(i, 200) for i in range(260)])
        record = d.weekly_daily_confluence(series, "^HSI", weekly_base(series, water=False), now=NOW)
        self.assertTrue(record["weekly_bullish"])
        self.assertLess(record["weekly_dif"], 0)
        self.assertTrue(record["triggered"])
        self.assertFalse(record["strict_gate"])
        self.assertEqual(record["signal"], "countertrend_watch")

    def test_bullish_week_is_only_context_without_new_daily_cross(self):
        series = bars([100 + .01 * i * i for i in range(260)])
        record = d.weekly_daily_confluence(series, "^HSI", weekly_base(series, golden=False), now=NOW)
        self.assertTrue(record["weekly_bullish"])
        self.assertFalse(record["active"])
        self.assertFalse(record["daily_trigger"])

    def test_missing_friday_cannot_be_assumed_a_holiday_and_promoted_to_week_close(self):
        series = [b for b in bars(n=260) if b["date"] != "2026-09-18"]
        record = d.weekly_daily_confluence(series, "^HSI", weekly_base(series), now=NOW)
        self.assertFalse(record["available"])
        self.assertIn("缺少周五", record["reason"])
        self.assertFalse(d.weekly_ready(series, "^HSI", now=NOW))
        self.assertTrue(d.weekly_ready(series, "^HSI", now=NOW, verified=False))

    def test_native_weekly_labels_not_quote_dates_and_partial_week_filtered(self):
        series = bars(n=36)
        raw = native_fixture() + [{"date": "2026-09-28", "close": 99999999}]
        weekly = {"bars": raw, "source": "Yahoo 周K", "url": "https://query1.finance.yahoo.com/weekly"}
        record = d.weekly_daily_confluence(series, "^HSI", weekly_base(series), now=NOW, weekly=weekly)
        self.assertTrue(record["available"])
        self.assertEqual(record["weekly_bars"], 52)
        self.assertEqual(record["week_end"], "2026-09-25")
        self.assertIsNone(record["actual_close_date"])
        self.assertIn("周期标签", record["detail"])
        self.assertEqual(record["source_url"], weekly["url"])
        self.assertAlmostEqual(record["weekly_dif"], stats.macd([b["close"] for b in raw[:-1]])[0])

    def test_us_week_closes_on_new_york_cutoff_not_cst_friday_midnight(self):
        raw = native_fixture(end=date(2026, 10, 2))
        before = NOW.replace(day=3, hour=3)
        after = NOW.replace(day=3, hour=5)
        early = d.native_weeks(raw, "^GSPC", as_of="2026-10-02", now=before)
        closed = d.native_weeks(raw, "^GSPC", as_of="2026-10-02", now=after)
        self.assertEqual(early[-1]["week_end"], "2026-09-25")
        self.assertEqual(closed[-1]["week_end"], "2026-10-02")

    def test_meta_snapshot_cannot_pad_native_weekly_minimum(self):
        raw = native_fixture(n=35)
        raw[-1]["from_meta"] = True
        self.assertEqual(len(d.native_weeks(raw, "^HSI", as_of="2026-09-30", now=NOW)), 34)

    def test_native_weekly_minimum_35_and_stale_weekly_not_faked(self):
        series = bars(n=36)
        for raw, available in ((native_fixture(n=34), False), (native_fixture(n=35), True),
                               (native_fixture(end=date(2026, 9, 4)), False)):
            record = d.weekly_daily_confluence(series, "^HSI", weekly_base(series), now=NOW,
                                               weekly={"bars": raw, "source": "test"})
            self.assertEqual(record["available"], available)


class HistoryAndRenderTests(unittest.TestCase):
    def test_long_existing_series_beats_thin_same_date_library_without_network(self):
        forbidden = Mock(side_effect=AssertionError("不应联网"))
        with patch.object(market_db, "load_daily_bars", return_value={"^HSI": bars(n=70)}):
            result = macd.run_macd(forbidden, existing={"^HSI": bars(n=260)}, specs=[("恒指", "^HSI")], now=NOW)
        forbidden.assert_not_called()
        self.assertEqual(result["items"][0]["data_route"], "reused")
        self.assertEqual(result["items"][0]["bars_n"], 260)
        self.assertEqual(result["derived_coverage"]["timeframe"]["valid"], 1)

    def test_mathematically_invalid_library_cannot_mask_valid_same_date_existing(self):
        forbidden = Mock(side_effect=AssertionError("已有基础日线可用不应联网"))
        with patch.object(market_db, "load_daily_bars", return_value={"^HSI": bars([1e308] * 70)}):
            result = macd.run_macd(forbidden, existing={"^HSI": bars(n=70)}, specs=[("恒指", "^HSI")],
                                   now=NOW, extend_history=False)
        forbidden.assert_not_called()
        self.assertTrue(result["available"])
        self.assertEqual(result["items"][0]["data_route"], "reused")

    def test_history_extends_whole_source_no_splicing_or_date_regression(self):
        seen = []

        def fetch(url, params=None, timeout=10):
            seen.append(params)
            return chart(bars(n=260, end=date(2026, 9, 29)) if "query1" in url else bars(n=260))

        with patch.object(market_db, "load_daily_bars", return_value={"^HSI": bars(n=70)}):
            result = macd.run_macd(fetch, specs=[("恒指", "^HSI")], now=NOW)
        row = result["items"][0]
        self.assertEqual(row["data_route"], "free")
        self.assertEqual(row["bars_n"], 260)  # 不是 70+260
        self.assertEqual(row["as_of"], "2026-09-30")
        self.assertEqual(seen, [{"range": "2y", "interval": "1d"}] * 2)
        self.assertIn("query2", row["source"])

    def test_missing_ohlc_library_does_not_hide_complete_existing_data(self):
        closes_only = [{"date": b["date"], "close": b["close"]} for b in bars(n=260)]
        forbidden = Mock(side_effect=AssertionError("已有完整数据不应联网"))
        with patch.object(market_db, "load_daily_bars", return_value={"^HSI": closes_only}):
            result = macd.run_macd(forbidden, existing={"^HSI": bars(n=260)}, specs=[("恒指", "^HSI")], now=NOW)
        forbidden.assert_not_called()
        self.assertEqual(result["items"][0]["data_route"], "reused")
        self.assertTrue(result["items"][0]["derived"]["divergence"]["available"])
        self.assertTrue(result["items"][0]["derived"]["bollinger"]["available"])

    def test_overflow_history_extension_does_not_replace_valid_base(self):
        response = chart(bars([1e308] * 260))
        with patch.object(market_db, "load_daily_bars", return_value={"^HSI": bars(n=36)}):
            result = macd.run_macd(lambda *a, **kw: response, specs=[("恒指", "^HSI")], now=NOW)
        self.assertTrue(result["available"])
        row = result["items"][0]
        self.assertEqual(row["data_route"], "market_db")
        self.assertEqual(row["bars_n"], 36)
        self.assertTrue(math.isfinite(row["dif"]))

    def test_failed_history_extension_preserves_base_and_individual_missing(self):
        with patch.object(market_db, "load_daily_bars", return_value={"^HSI": bars(n=36)}):
            result = macd.run_macd(lambda *a, **kw: None, specs=[("恒指", "^HSI")], now=NOW)
        self.assertTrue(result["available"])
        row = result["items"][0]
        self.assertEqual(row["data_route"], "market_db")
        self.assertIn("保留基础", row["history_note"])
        self.assertFalse(row["derived"]["slope"]["available"])
        self.assertFalse(row["derived"]["timeframe"]["available"])
        self.assertEqual(row["source_url"], None)

    def test_native_weekly_free_chain_fills_friday_gap_without_replacing_daily(self):
        series = [b for b in bars(n=260) if b["date"] != "2026-09-18"]
        seen = []

        def fetch(url, params=None, timeout=10):
            seen.append(params)
            if "yahoo" in url:
                return None
            return {"data": {"klines": [f"{b['date']},{b['close']},{b['close']},{b['close']},{b['close']},1000"
                                        for b in native_fixture(monday=False)]}}

        with patch.object(market_db, "load_daily_bars", return_value={"^HSI": series}):
            result = macd.run_macd(fetch, specs=[("恒指", "^HSI")], now=NOW)
        row = result["items"][0]
        self.assertEqual(row["data_route"], "market_db")
        self.assertEqual(row["bars_n"], 259)
        tf = row["derived"]["timeframe"]
        self.assertTrue(tf["available"])
        self.assertIn("东方财富周K", tf["source"])
        self.assertTrue(all(p.get("interval") == "1wk" for p in seen[:2]))
        self.assertEqual(seen[2]["klt"], "102")
        self.assertEqual(seen[2]["lmt"], "106")
        self.assertIsNone(row["source_url"])
        self.assertTrue(tf["source_url"])

    def test_unverified_ndx_mapping_not_used_as_nasdaq_composite_daily_or_weekly(self):
        forbidden = Mock(side_effect=AssertionError("不能请求可能串标的的源"))
        with patch.object(providers, "em_secid_for_yahoo", return_value="100.NDX"):
            for interval in ("1d", "1wk"):
                for symbol in ("^IXIC", "%5EIXIC"):
                    response = providers.fetch_bars_eastmoney(forbidden, symbol, interval=interval, with_source=True)
                    self.assertEqual(response["bars"], [])
        forbidden.assert_not_called()

    def test_weekly_provider_does_not_use_daily_meta_as_a_weekly_bar(self):
        response = chart(native_fixture(n=35))
        extra = {"date": "2026-09-30", "close": 123, "from_meta": True}
        with patch.object(providers, "session_bar_from_meta", return_value=extra) as meta:
            result = providers.fetch_bars(lambda *a, **kw: response, "^HSI", interval="1wk")
        meta.assert_not_called()
        self.assertEqual(len(result), 35)
        with patch.object(providers, "session_bar_from_meta", return_value=extra) as meta:
            daily = providers.fetch_bars(lambda *a, **kw: response, "^HSI")
        self.assertTrue(meta.called)
        self.assertEqual(daily[-1], extra)  # 日线旧行为不变

    def test_weekly_backup_usage_is_audited_even_when_daily_is_library(self):
        row = macd.analyze_bars(bars(n=260), label="恒指", code="^HSI", now=NOW)
        row["source_url"] = None
        row["derived"]["timeframe"]["source_url"] = "https://91.push2his.eastmoney.com/api/qt/stock/kline/get"
        result = result_of(row)
        with patch.object(pipeline, "MACD_ENABLED", True), patch.object(pipeline, "AI_ANALYSIS_ENABLED", True), \
                patch.object(macd, "run_macd", return_value=result), patch.object(pipeline, "_note_backup_served") as note:
            pipeline.fetch_macd_strategy({})
        self.assertTrue(any(call.args == ("em_kline", row["derived"]["timeframe"]["source_url"])
                            for call in note.call_args_list))

    def test_both_themes_render_new_rules_evidence_missing_and_safe_html(self):
        row = macd.analyze_bars(bars(n=70), label='<script>alert("x")</script>', code="^HSI", now=NOW)
        result = result_of(row)
        for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
            with patch.object(providers, "fetch_bars", side_effect=AssertionError("渲染不能联网")):
                html = macd.render_strategy(result, kit, limit=9)
            for required in ("不重复计票", "DIF、DEA 均&gt;0", "完整周线不足", "连续 3 根", "前一日带", "第 5 根", "样本外收益验证"):
                self.assertIn(required, html)
            self.assertNotIn('<script>alert("x")</script>', html)
            self.assertIn("&lt;script&gt;", html)
            self.assertEqual(html.count("MACD 派生 · 分工研判"), 1)

    def test_full_expands_idle_numeric_evidence_and_existing_score_is_unchanged(self):
        row = macd.analyze_bars(bars(n=260), label="恒指", code="^HSI", now=NOW)
        result = result_of(row)
        lite = macd.render_strategy(result, pipeline.GUIZANG_KIT, limit=9)
        full = macd.render_strategy(result, pipeline.GUIZANG_KIT, limit=0)
        self.assertGreater(len(full), len(lite))
        self.assertIn("周 DIF=", full)
        self.assertNotIn("收起", full)
        data = {"实时行情": {"status": "success", "quotes": {
            "恒生指数": {"price": 123.4, "change_pct": .2, "as_of": "2026-09-30"}}}}
        baseline = pipeline.build_daily_quant_strategy(data)["score"]
        data[pipeline.MACD_SOURCE_NAME] = {"status": "success", "result": result}
        self.assertEqual(pipeline.build_daily_quant_strategy(data)["score"], baseline)

    def test_causal_prefix_analysis_matches_original_with_future_bars_present(self):
        series = bars([100 + .002 * i * i + 6 * math.sin(i / 8) for i in range(300)])
        full = stats.macd_series([b["close"] for b in series])
        for length in (70, 140, 200, 260):
            prefix = series[:length]
            day = date.fromisoformat(prefix[-1]["date"])
            moment = NOW.replace(year=day.year, month=day.month, day=day.day, hour=17)
            base = macd.analyze_bars(prefix, label="恒指", code="^HSI", now=moment)
            expected = d.analyze_derivatives(prefix, full[:length], code="^HSI", base=base, now=moment)
            self.assertEqual(base["derived"], expected)
            truncated = macd.analyze_bars(series, label="恒指", code="^HSI", now=moment)
            self.assertEqual(base["derived"], truncated["derived"])
            self.assertEqual(base["action_key"], truncated["action_key"])


if __name__ == "__main__":
    unittest.main()
