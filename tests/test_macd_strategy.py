"""MACD 策略的离线回归：指标、交叉、日线完成性、库/免费源优先级、双主题集成。"""
import copy
import importlib.util
import json
import math
import os
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

sys.modules.setdefault("requests", types.SimpleNamespace())
OUTPUT = Path(__file__).parents[1] / "output"
if str(OUTPUT) not in sys.path:
    sys.path.insert(0, str(OUTPUT))

import market_db
import freshness_checker
from octopus_quant import macd_strategy as macd, providers, stats

spec = importlib.util.spec_from_file_location("pipeline_under_macd_test", OUTPUT / "pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)
CST = providers.CST
NOW = datetime(2026, 10, 2, 13, 30, tzinfo=CST)


def bars(prices=None, n=70, end=date(2026, 9, 30)):
    prices = list(prices) if prices is not None else [100 + i * 0.15 + math.sin(i / 3) for i in range(n)]
    days, day = [], end
    while len(days) < len(prices):
        if day.weekday() < 5:
            days.append(day.isoformat())
        day -= timedelta(days=1)
    return [{"date": day, "close": price, "open": price, "high": price, "low": price,
             "volume": 1000} for day, price in zip(reversed(days), prices)]


def chart(series):
    return {"chart": {"result": [{
        "timestamp": [int(datetime.fromisoformat(b["date"] + "T09:30:00").replace(tzinfo=CST).timestamp()) for b in series],
        "indicators": {"quote": [{"close": [b["close"] for b in series]}]},
    }]}}


def db_docs(series, symbol="^HSI"):
    return [{"db_date": b["date"], "date_compact": b["date"].replace("-", ""),
             "slots": {"1700": {"pulled_at": b["date"] + " 17:00:00",
                                 "quotes": {symbol: {"eod_close": dict(b)}}}}} for b in series]


def result_for(series=None, code="^HSI", label="恒生指数"):
    row = macd.analyze_bars(series or bars(), label=label, code=code, now=NOW)
    assert row["available"]
    return {"available": True, "items": [row], "missing": [], "warnings": [],
            "coverage": {"valid": 1, "total": 1}, "as_of": row["as_of"],
            "latest_as_of": row["as_of"], "golden_n": int(row["cross"] == "golden"),
            "death_n": int(row["cross"] == "death")}


class IndicatorTests(unittest.TestCase):
    def test_series_preserves_existing_macd_semantics_and_is_causal(self):
        prices = [b["close"] for b in bars()]
        full = stats.macd_series(prices)
        self.assertEqual(len(full), len(prices))
        self.assertTrue(all(p == (None, None, None) for p in full[:34]))
        for end in (34, 35, 36, 50, 70):
            self.assertEqual(full[end - 1], stats.macd(prices[:end]))
            self.assertEqual(full[:end], stats.macd_series(prices[:end]))
        extended = stats.macd_series(prices + [1, 10000, 1])
        self.assertEqual(extended[:len(prices)], full)
        dif, dea, hist = full[-1]
        self.assertAlmostEqual(hist, dif - dea)

    def test_golden_cross_above_zero_is_entry_and_domestic_hist_is_doubled(self):
        series = bars([100.0] * 35 + [110.0])
        row = macd.analyze_bars(series, label="恒指", code="^HSI", now=NOW)
        self.assertEqual(row["cross"], "golden")
        self.assertEqual(row["action_key"], "entry")
        self.assertEqual(row["axis"], "零轴上方")
        self.assertAlmostEqual(row["hist"], 2 * (row["dif"] - row["dea"]))
        # 35 根平盘后单日 +10：可独立手算，而不只是两个内核函数互相印证。
        expected_dif = 10 * (2 / 13 - 2 / 27)
        self.assertAlmostEqual(row["dif"], expected_dif)
        self.assertAlmostEqual(row["dea"], expected_dif * 2 / 10)
        self.assertAlmostEqual(row["hist"], expected_dif * 1.6)
        self.assertEqual(row["last_cross"], {"kind": "golden", "date": "2026-09-30", "bars_ago": 0})

    def test_death_cross_and_bearish_continuation_exit_without_shorting(self):
        series = bars([100.0] * 35 + [90.0])
        row = macd.analyze_bars(series, label="恒指", code="^HSI", now=NOW)
        self.assertEqual(row["cross"], "death")
        self.assertEqual(row["action_key"], "exit")
        self.assertEqual(row["axis"], "零轴下方")
        following = macd.analyze_bars(bars([100.0] * 35 + [90.0, 85.0]),
                                     label="恒指", code="^HSI", now=NOW)
        self.assertIsNone(following["cross"])
        self.assertEqual(following["state"], "空头延续")
        self.assertEqual(following["last_cross"]["bars_ago"], 1)

    def test_below_zero_golden_cross_only_observes_rebound(self):
        prices = [100 - 0.2 * i for i in range(60)]
        row = macd.analyze_bars(bars(prices + [prices[-1] + 2]), label="恒指", code="^HSI", now=NOW)
        self.assertEqual(row["cross"], "golden")
        self.assertEqual(row["axis"], "零轴下方")
        self.assertEqual(row["action_key"], "watch")
        self.assertIn("观察反弹", row["action"])

    def test_ongoing_bullish_state_does_not_repeat_golden_cross(self):
        row = macd.analyze_bars(bars([100.0] * 35 + [110.0, 112.0]), label="恒指", code="^HSI", now=NOW)
        self.assertIsNone(row["cross"])
        self.assertEqual(row["state"], "多头延续")
        self.assertEqual(row["action_key"], "hold")
        self.assertEqual(row["last_cross"]["bars_ago"], 1)

    def test_flat_or_insufficient_data_never_fakes_a_signal(self):
        row = macd.analyze_bars(bars([100.0] * 60), label="恒指", code="^HSI", now=NOW)
        self.assertEqual((row["dif"], row["dea"], row["hist"]), (0.0, 0.0, 0.0))
        self.assertIsNone(row["cross"])
        self.assertIsNone(row["last_cross"])
        self.assertEqual(row["action_key"], "watch")
        for n in (0, 10, 34, 35):
            result = macd.analyze_bars(bars(n=n), label="恒指", code="^HSI", now=NOW)
            self.assertFalse(result["available"])
            self.assertIn("不足", result["reason"])

    def test_bad_values_duplicate_dates_future_and_intraday_bars_are_removed(self):
        original = bars()
        original[-1]["close"] = 123.4
        malformed = original + [None, {}, {"date": "oops", "close": 1},
                                {"date": "2026-10-03", "close": 1},
                                {"date": "2026-10-02", "close": 9999},
                                {"date": "2026-09-29", "close": float("nan")},
                                {"date": "2026-09-29", "close": float("inf")},
                                {"date": "2026-09-29", "close": 0},
                                {"date": "2026-09-29", "close": True}]
        got = macd.completed_bars(malformed, "^HSI", now=NOW)
        self.assertEqual(got, original)
        duplicated = macd.completed_bars(original[::-1] + [original[-1]], "^HSI", now=NOW)
        self.assertEqual(duplicated, original)
        self.assertFalse(macd.analyze_bars(bars(end=date(2026, 9, 20)), label="恒指", code="^HSI", now=NOW)["available"])

    def test_overflow_never_emits_non_finite_indicator_values(self):
        row = macd.analyze_bars(bars([1e308] * 40), label="异常", code="^HSI", now=NOW)
        self.assertFalse(row["available"])
        self.assertIn("非有限值", row["reason"])

    def test_exchange_close_and_us_dst_not_cst_date_guessing(self):
        self.assertFalse(providers.is_session_closed("^HSI", "2026-10-02", now=NOW))
        self.assertTrue(providers.is_session_closed("^HSI", "2026-10-02", now=NOW.replace(hour=17)))
        self.assertTrue(providers.is_session_closed("000001.SS", "2026-10-02", now=NOW.replace(hour=15, minute=10)))
        # 北京 10/2 凌晨 1 时 = 纽约 10/1 下午 1 时，10/1 日线尚未收盘。
        self.assertFalse(providers.is_session_closed("^GSPC", "2026-10-01", now=NOW.replace(hour=1)))
        self.assertTrue(providers.is_session_closed("^GSPC", "2026-10-01", now=NOW.replace(hour=4, minute=15)))
        winter = datetime(2026, 1, 7, 4, 30, tzinfo=CST)
        self.assertFalse(providers.is_session_closed("^GSPC", "2026-01-06", now=winter))
        self.assertTrue(providers.is_session_closed("^GSPC", "2026-01-06", now=winter.replace(hour=5, minute=15)))
        self.assertFalse(providers.is_session_closed("^HSI", "2026-10-03", now=NOW + timedelta(days=2)))


class DailyDatabaseTests(unittest.TestCase):
    def test_deduplicates_by_actual_session_not_file_date_and_does_not_mutate(self):
        docs = db_docs(bars(n=1))
        first = docs[0]["slots"]["1700"]
        docs.append({"db_date": "2026-10-01", "slots": {
            "0800": {**copy.deepcopy(first), "pulled_at": "2026-10-01 08:00:00"},
            "1230": {**copy.deepcopy(first), "pulled_at": "2026-10-01 12:30:00"},
            "1700": {**copy.deepcopy(first), "pulled_at": "2026-10-01 17:00:00"}}})
        before = copy.deepcopy(docs)
        result = market_db.load_daily_bars(docs=docs, now=NOW)
        self.assertEqual([b["date"] for b in result["^HSI"]], ["2026-09-30"])
        self.assertEqual(docs, before)

    def test_persisted_partial_daily_bar_stays_partial_after_market_closes(self):
        docs = db_docs(bars(n=1, end=date(2026, 10, 2)))
        docs[0]["slots"]["1700"]["pulled_at"] = "2026-10-02 13:00:00"
        self.assertEqual(market_db.load_daily_bars(docs=docs, now=NOW.replace(hour=18)), {})
        # 美股当天的东财“日K”即使叫 eod_close，盘中采集也不能接受。
        us_docs = db_docs(bars(n=1, end=date(2026, 10, 1)), "^GSPC")
        us_docs[0]["slots"]["1700"]["pulled_at"] = "2026-10-01 23:30:00"
        self.assertEqual(market_db.load_daily_bars(docs=us_docs, now=NOW), {})
        us_docs[0]["slots"]["1700"]["pulled_at"] = "2026-10-02 05:00:00"
        self.assertEqual(market_db.load_daily_bars(docs=us_docs, now=NOW)["^GSPC"][0]["date"], "2026-10-01")

    def test_index_quote_accepts_single_source_post_close_and_rejects_intraday_or_legacy_conflict(self):
        single = {"quote_time": "2026-09-30 16:20:00", "price": 100.0, "source": "yahoo", "n_sources": 1}
        doc = {"slots": {"1700": {"pulled_at": "2026-09-30 17:00:00", "quotes": {"^HSTECH": single}}}}
        self.assertEqual(market_db.load_daily_bars(docs=[doc], now=NOW)["^HSTECH"][0]["close"], 100.0)
        legacy_single = {"quote_time": "2026-09-30 16:20:00", "consensus": {"price": 101.0, "n_agree": 1}}
        doc["slots"]["1700"]["quotes"]["^HSTECH"] = legacy_single
        self.assertEqual(market_db.load_daily_bars(docs=[doc], now=NOW)["^HSTECH"][0]["close"], 101.0)
        for bad in ({"quote_time": None, "price": 100.0},
                    {"quote_time": "2026-09-30 12:30:00", "price": 100.0},
                    {"quote_time": "2026-09-30 16:20:00", "consensus": {"price": 100.0, "n_agree": 3, "verdict": "冲突"}}):
            doc["slots"]["1700"]["quotes"]["^HSTECH"] = bad
            self.assertEqual(market_db.load_daily_bars(docs=[doc], now=NOW), {})
        doc["slots"]["1700"]["quotes"] = {"0700.HK": single}
        self.assertEqual(market_db.load_daily_bars(docs=[doc], now=NOW), {})

    def test_price_bases_are_never_stitched_and_known_actions_force_refetch(self):
        series = bars(n=3)
        docs = db_docs(series, "600519.SS")
        for doc in docs[:2]:
            q = doc["slots"]["1700"]["quotes"]["600519.SS"]
            q["eod_close_tdx"] = {**q.pop("eod_close"), "close": 1234}
        result = market_db.load_daily_bars(docs=docs, now=NOW)
        self.assertEqual(len(result["600519.SS"]), 2)
        self.assertTrue(all(b["price_basis"] == "未复权" for b in result["600519.SS"]))
        docs[-1]["slots"]["1700"]["corporate_actions"] = {"600519.SS": [{"date": series[1]["date"]}]}
        adjusted = market_db.load_daily_bars(docs=docs, now=NOW)
        self.assertEqual(len(adjusted.get("600519.SS", [])), 1)  # 排除跨除权窗口的旧 raw 序列

    def test_corrupt_and_future_files_are_not_used(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "20260929.json").write_text("broken", encoding="utf-8")
            doc = db_docs(bars(n=1))[0]
            Path(root, "20260930.json").write_text(json.dumps(doc), encoding="utf-8")
            future = db_docs(bars(n=1, end=date(2026, 10, 5)))[0]
            Path(root, "20261005.json").write_text(json.dumps(future), encoding="utf-8")
            result = market_db.load_daily_bars(root=root, now=NOW)
            self.assertEqual([b["date"] for b in result["^HSI"]], ["2026-09-30"])
        malformed = [None, [], {"slots": [1]}, {"slots": {"1700": None}},
                     {"slots": {"1700": {"pulled_at": "2026-09-30 17:00:00", "quotes": [1]}}}]
        result = market_db.load_daily_bars(docs=malformed + [doc], now=NOW)
        self.assertEqual([b["date"] for b in result["^HSI"]], ["2026-09-30"])


class DataRoutingTests(unittest.TestCase):
    def test_database_then_existing_then_fetch_only_missing_symbols(self):
        database = market_db.load_daily_bars(docs=db_docs(bars()), now=NOW)
        seen = []

        def fetch(url, params=None, timeout=10):
            seen.append(url)
            return chart(bars()) if url.endswith("^GSPC") else None

        with patch.object(market_db, "load_daily_bars", return_value=database):
            result = macd.run_macd(fetch, existing={"^HSI": bars([200] * 70), "^HSTECH": bars()},
                                   specs=[("恒指", "^HSI"), ("恒科", "^HSTECH"), ("标普", "^GSPC")], now=NOW, extend_history=False)
        self.assertEqual([r["data_route"] for r in result["items"]], ["market_db", "reused", "free"])
        self.assertEqual(result["coverage"], {"valid": 3, "total": 3})
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].endswith("^GSPC"))
        self.assertIn("query1.finance.yahoo.com", result["items"][-1]["source"])
        expected = macd.analyze_bars(bars(), code="^HSI", label="恒指", now=NOW)
        self.assertEqual(result["items"][0]["dif"], expected["dif"])

    def test_short_or_stale_library_falls_back_to_existing_without_http(self):
        for db in ({"^HSI": bars(n=2)}, {"^HSI": bars(end=date(2026, 9, 20))}):
            forbidden = Mock(side_effect=AssertionError("不应联网"))
            with patch.object(market_db, "load_daily_bars", return_value=db):
                result = macd.run_macd(forbidden, existing={"^HSI": bars()}, specs=[("恒指", "^HSI")], now=NOW, extend_history=False)
            self.assertEqual(result["items"][0]["data_route"], "reused")
            forbidden.assert_not_called()

    def test_newer_existing_close_overrides_still_fresh_library_and_free_cannot_regress(self):
        with patch.object(market_db, "load_daily_bars", return_value={"^HSI": bars(end=date(2026, 9, 29))}):
            result = macd.run_macd(Mock(side_effect=AssertionError("不应联网")), existing={"^HSI": bars()},
                                   specs=[("恒指", "^HSI")], now=NOW, extend_history=False)
        self.assertEqual(result["items"][0]["data_route"], "reused")
        self.assertEqual(result["items"][0]["as_of"], "2026-09-30")
        seen = []

        def fetch(url, params=None, timeout=10):
            seen.append(url)
            return chart(bars(end=date(2026, 9, 29)) if "query1" in url else bars())

        # 库只有 2 根，但已经知道 9/30 真实收盘；免费源的长历史也不能回退到 9/29。
        with patch.object(market_db, "load_daily_bars", return_value={"^HSI": bars(n=2)}):
            result = macd.run_macd(fetch, specs=[("恒指", "^HSI")], now=NOW, extend_history=False)
        self.assertEqual(len(seen), 2)
        self.assertEqual(result["items"][0]["as_of"], "2026-09-30")
        self.assertIn("query2", result["items"][0]["source"])

    def test_short_stale_and_invalid_primary_each_continue_to_yahoo_mirror(self):
        for primary in (bars(n=2), bars(end=date(2026, 9, 10)), [{"date": "2026-09-30", "close": float("nan")} ]):
            seen = []

            def fetch(url, params=None, timeout=10):
                seen.append(url)
                return chart(primary if "query1" in url else bars())

            with patch.object(market_db, "load_daily_bars", return_value={}):
                result = macd.run_macd(fetch, specs=[("恒指", "^HSI")], now=NOW, extend_history=False)
            self.assertTrue(result["available"])
            self.assertEqual(len(seen), 2)
            self.assertIn("query2.finance.yahoo.com", result["items"][0]["source"])

    def test_yahoo_failure_and_invalid_em_primary_use_independent_mirror(self):
        seen = []

        def fetch(url, params=None, timeout=10):
            seen.append(url)
            if "yahoo" in url:
                return None
            if "91.push2his" not in url:
                return {"data": {"klines": ["bad"]}}
            return {"data": {"klines": [f"{b['date']},{b['close']},{b['close']},{b['close']},{b['close']},1000,0" for b in bars()]}}

        with patch.object(market_db, "load_daily_bars", return_value={}):
            result = macd.run_macd(fetch, specs=[("上证", "000001.SS")], now=NOW, extend_history=False)
        self.assertTrue(result["available"])
        self.assertEqual(len(seen), 4)
        self.assertIn("91.push2his.eastmoney.com", result["items"][0]["source"])

    def test_single_symbol_failure_and_database_exception_are_isolated(self):
        def fetch(url, params=None, timeout=10):
            if url.endswith("^GSPC"):
                raise RuntimeError("offline")
            return None

        with patch.object(market_db, "load_daily_bars", side_effect=OSError("corrupt")):
            result = macd.run_macd(fetch, existing={"^HSI": bars()},
                                   specs=[("恒指", "^HSI"), ("标普", "^GSPC")], now=NOW, extend_history=False)
        self.assertTrue(result["available"])
        self.assertEqual(result["coverage"], {"valid": 1, "total": 2})
        self.assertEqual(result["missing"][0]["code"], "^GSPC")
        self.assertTrue(result["warnings"])

    def test_empty_sources_have_no_fabricated_numbers(self):
        with patch.object(market_db, "load_daily_bars", return_value={}):
            result = macd.run_macd(lambda *a, **kw: None, specs=[("恒指", "^HSI")], now=NOW, extend_history=False)
        self.assertFalse(result["available"])
        self.assertEqual(result["items"], [])
        self.assertNotIn("dif", result)
        self.assertEqual(macd.render_strategy(result, pipeline.GUIZANG_KIT), "")

    def test_default_pool_and_custom_symbol_configuration(self):
        with patch.dict(os.environ, {"OCTOPUS_MACD_SYMBOLS": ""}):
            self.assertEqual(len(macd.symbol_specs()), 9)
        with patch.dict(os.environ, {"OCTOPUS_MACD_SYMBOLS": "^HSI:恒指,0700.HK:腾讯,^HSI:重复"}):
            self.assertEqual(macd.symbol_specs(), [("恒指", "^HSI"), ("腾讯", "0700.HK")])


class PipelineIntegrationTests(unittest.TestCase):
    def _data(self, with_market=True):
        data = {pipeline.MACD_SOURCE_NAME: pipeline._source_result(
            pipeline.MACD_SOURCE_NAME, "success", content_date="2026-09-30", result=result_for())}
        if with_market:
            data["实时行情"] = pipeline._source_result("test", "success", quotes={
                "恒生指数": {"price": 24613.27, "change_pct": 0.36, "as_of": "2026-09-30"}})
        return data

    def test_both_themes_render_macd_inside_strategy_once_and_keep_existing_market_score(self):
        data = self._data()
        old_score = pipeline.build_daily_quant_strategy({"实时行情": data["实时行情"]})["score"]
        self.assertEqual(pipeline.build_daily_quant_strategy(data)["score"], old_score)
        for theme in ("guizang", "pixel"):
            with patch.object(pipeline, "safe_request", side_effect=AssertionError("渲染不能联网")), \
                    patch.object(market_db, "load_daily_bars", side_effect=AssertionError("渲染不能读库")), \
                    pipeline.notes_mode():            # 计算口径 / 执行规则属于说明文字：--notes 下齐全
                html = pipeline.generate_report(data, "2026年10月2日", "20261002", theme=theme)
            self.assertEqual(html.count("MACD 量化策略 · 日线"), 1)
            marker = f"{pipeline.SECTION_TITLE_STRATEGY}</h2>" if theme == "guizang" else "// STRATEGY READ"
            self.assertIn(marker, html)
            self.assertLess(html.find(marker), html.find("MACD 量化策略 · 日线"))
            for text in ("DIF / DEA", "MACD柱", "2026-09-30", "EMA12−EMA26", "非投资建议", "信号不等于上涨概率", "36 根"):
                self.assertIn(text, html)

    def test_plain_mode_keeps_macd_table_without_methodology(self):
        """入门版（默认）：MACD 表格与数字照出，计算口径 / 执行规则 / 风险长文不出。"""
        data = self._data()
        for theme in ("guizang", "pixel"):
            with patch.object(pipeline, "safe_request", side_effect=AssertionError("渲染不能联网")), \
                    patch.object(market_db, "load_daily_bars", side_effect=AssertionError("渲染不能读库")):
                html = pipeline.generate_report(data, "2026年10月2日", "20261002", theme=theme)
            self.assertEqual(html.count("MACD 量化策略 · 日线"), 1)
            for text in ("DIF / DEA", "MACD柱", "2026-09-30", "退出/规避"):
                self.assertIn(text, html, theme)
            for text in ("EMA12−EMA26", "计算口径", "执行规则", "信号不等于上涨概率", "--full"):
                self.assertNotIn(text, html, theme)

    def test_macd_only_still_has_strategy_column_without_fake_market_neutral_score(self):
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(self._data(False), "2026年10月2日", "20261002", theme=theme)
            self.assertIn(f"{pipeline.SECTION_TITLE_STRATEGY}</h2>" if theme == "guizang" else "// STRATEGY READ", html)
            self.assertIn("MACD 量化策略", html)
            self.assertNotIn("市场倾向", html)
            self.assertNotIn("量化信号 · 策略总览", html)

    def test_failure_omits_empty_macd_but_is_in_missing_source_audit(self):
        data = self._data()
        data[pipeline.MACD_SOURCE_NAME] = pipeline._source_result(pipeline.MACD_SOURCE_NAME, "unavailable", error="offline")
        html = pipeline.generate_report(data, "2026年10月2日", "20261002")
        self.assertNotIn("MACD 量化策略 · 日线", html)
        self.assertIn("MACD量化策略", html)
        parts = pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT, date_str="20261002")
        self.assertEqual(parts["total"], 9)     # 原有 8 路 + 真正采集的 MACD 来源

    def test_fetch_wrapper_reuses_bars_and_does_not_mark_old_data_as_today_snapshot(self):
        result = result_for()
        with patch.object(pipeline._quant.macd_strategy, "run_macd", return_value=result) as run:
            source = pipeline.fetch_macd_strategy({"港股量化": {"result": {"indices": [{"code": "^HSI", "bars": bars()}]}}})
        self.assertIn("^HSI", run.call_args.kwargs["existing"])
        self.assertFalse(source["is_today"])
        self.assertFalse(source.get("snapshot", False))
        self.assertEqual(source["content_date"], "2026-09-30")
        self.assertFalse(pipeline.check_push_eligibility({pipeline.MACD_SOURCE_NAME: source})[0])
        status = freshness_checker.check_single_freshness(pipeline.MACD_SOURCE_NAME, source, today=NOW.date())
        self.assertTrue(status["is_fresh"])
        self.assertEqual(status["threshold"], macd.MAX_LAG_DAYS)

    def test_free_backup_hits_are_registered_in_summary_audit(self):
        for url, expected_tags in (
                ("https://query2.finance.yahoo.com/v8/finance/chart/^HSI", {"备用源1"}),
                ("https://91.push2his.eastmoney.com/api/qt/stock/kline/get", {"备用源1", "备用源2"})):
            result = result_for()
            result["items"][0]["source_url"] = url
            with patch.object(pipeline, "BACKUP_EVENTS", []), \
                    patch.object(macd, "run_macd", return_value=result):
                pipeline.fetch_macd_strategy({})
                self.assertEqual({event[1] for event in pipeline.BACKUP_EVENTS}, expected_tags)
                self.assertTrue(pipeline.backup_events_text())

    def test_macd_remains_enabled_when_probability_engine_is_disabled(self):
        with patch.object(pipeline, "HK_QUANT_ENABLED", False), \
                patch.object(macd, "run_macd", return_value=result_for()) as run:
            source = pipeline.fetch_macd_strategy({"港股量化": {"status": "unavailable"}})
        self.assertEqual(source["status"], "success")
        self.assertEqual(run.call_args.kwargs["existing"], {})

    def test_disabled_macd_does_not_fetch_or_render(self):
        with patch.object(pipeline, "MACD_ENABLED", False), \
                patch.object(pipeline._quant.macd_strategy, "run_macd", side_effect=AssertionError("不应取数")):
            self.assertIsNone(pipeline.fetch_macd_strategy())
            html = pipeline.generate_report(self._data(), "2026年10月2日", "20261002")
            self.assertNotIn("MACD 量化策略 · 日线", html)

    def test_collection_registers_macd_before_freshness_check(self):
        source = self._data(False)[pipeline.MACD_SOURCE_NAME]
        legacy = ("fetch_market_snapshot", "fetch_market_panorama", "fetch_gov_policy",
                  "fetch_hk_channels", "fetch_google_news", "fetch_fed_trend", "fetch_geo_trend",
                  "fetch_eastmoney_news", "fetch_hot_stocks", "fetch_hk_quant", "fetch_weekly_forecast",
                  "fetch_sector_rotation", "fetch_industry_rotation")
        with ExitStack() as stack:
            for fn in legacy:
                stack.enter_context(patch.object(pipeline, fn, return_value={"status": "unavailable"}))
            for flag in ("HK_NEWS_ENABLED", "ECON_CALENDAR_ENABLED"):
                stack.enter_context(patch.object(pipeline, flag, False))
            stack.enter_context(patch.object(pipeline, "fetch_hk_seven_day", return_value=None))
            stack.enter_context(patch.object(pipeline, "fetch_public_sites", return_value={}))
            stack.enter_context(patch.object(pipeline, "time", types.SimpleNamespace(sleep=lambda _: None)))
            stack.enter_context(patch.object(pipeline, "safe_request", side_effect=AssertionError("不应联网")))
            collect_macd = stack.enter_context(patch.object(pipeline, "fetch_macd_strategy", return_value=source))
            data = pipeline.collect_all_data()
        collect_macd.assert_called_once()
        self.assertIs(data[pipeline.MACD_SOURCE_NAME], source)
        self.assertIn(pipeline.MACD_SOURCE_NAME, [r["source"] for r in data["_freshness"]["details"]])

    def test_row_limit_is_disclosed_and_html_text_is_escaped(self):
        result = result_for(label="<script>bad</script>")
        result["items"] *= 2
        result["coverage"] = {"valid": 2, "total": 2}
        for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
            html = macd.render_strategy(result, kit, limit=1)
            self.assertIn("已收起 1 个有效标的", html)
            self.assertNotIn("<script>", html)
            self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
