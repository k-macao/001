"""🕐「今日预判」行情新鲜度回归测试（不发任何网络请求）。

复现 2026-09-29 凌晨的真实事故：Yahoo Chart API 在交易所本地 0 点后几小时内会暂时丢掉
刚收盘那天的日线（恒指 / 上证在周二凌晨回退到上周五收盘），而美股（仍在盘中）正常——
「今日预判」里港股一句话、核心判断的指数均值、周度预测锚点、量化分析因此整体过期，
且页面把整份快照标成美股的日期，读者无从分辨。

三道防线各自可测：
  ① 数据层：providers.session_bar_from_meta 用 meta 最新报价补出缺失的已收盘日线
     （量化引擎 / 周度预测 /【及时秋刀鱼】AI 行情复盘共用）；
  ② 核对层：pipeline._reconcile_market_snapshot 用东方财富行情时间做独立基准回补；
  ③ 呈现层：每个品种记录 as_of，按市场标注「截至 MM-DD」，滞后品种标明并不计入均值。
"""
import importlib.util
import re
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("requests", types.SimpleNamespace())

REPO_ROOT = Path(__file__).parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
if str(OUTPUT_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUT_DIR))

from octopus_quant import providers  # noqa: E402

MODULE_PATH = OUTPUT_DIR / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_freshness_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

HKT = timezone(timedelta(hours=8))
ET = timezone(timedelta(hours=-4))


def _ts(y, m, d, hh, mm, tz):
    return int(datetime(y, m, d, hh, mm, tzinfo=tz).timestamp())


def _chart(symbol, days, closes, tz, gmtoffset, *, meta_price=None, meta_time=None,
           regular=None, currency="HKD", with_ctp=True):
    """构造 Yahoo v8 chart 响应；days 为 2026-09 的日号，K 线时间戳取当地 09:30。"""
    stamps = [_ts(2026, 9, d, 9, 30, tz) for d in days]
    meta = {"currency": currency, "symbol": symbol, "gmtoffset": gmtoffset}
    if meta_price is not None:
        meta.update({"regularMarketPrice": meta_price, "regularMarketTime": meta_time,
                     "regularMarketDayHigh": meta_price * 1.01,
                     "regularMarketDayLow": meta_price * 0.99,
                     "regularMarketVolume": 987654})
    if regular and with_ctp:
        meta["currentTradingPeriod"] = {"regular": {"start": regular[0], "end": regular[1],
                                                    "gmtoffset": gmtoffset}}
    return {"chart": {"result": [{
        "meta": meta, "timestamp": stamps,
        "indicators": {"quote": [{"close": closes, "open": closes, "high": closes,
                                  "low": closes, "volume": [1000] * len(closes)}]},
    }]}}


def _strip(html):
    return unescape(re.sub(r"<[^>]+>", "", html or ""))


# 2026-09-29（周二）02:56 北京时间：港股 / A股日线只到 09-25，meta 仍是 09-28 收盘；
# 美股 09-28 盘中（K 线含 09-28 实时根）；WTI 电子盘已进入 09-29。
TUE_HK_SESSION = (_ts(2026, 9, 29, 9, 30, HKT), _ts(2026, 9, 29, 16, 0, HKT))
MON_US_SESSION = (_ts(2026, 9, 28, 9, 30, ET), _ts(2026, 9, 28, 16, 0, ET))


def _hsi_gap(meta_stale=False):
    return _chart("^HSI", [22, 23, 24, 25], [24800.0, 24700.0, 24760.0, 24510.09], HKT, 28800,
                  meta_price=24510.09 if meta_stale else 24642.51,
                  meta_time=_ts(2026, 9, 25, 16, 8, HKT) if meta_stale else _ts(2026, 9, 28, 16, 8, HKT),
                  regular=TUE_HK_SESSION)


def _sse_gap(meta_stale=False):
    return _chart("000001.SS", [22, 23, 24, 25], [3900.0, 3910.0, 3936.4, 3888.37], HKT, 28800,
                  meta_price=3888.37 if meta_stale else 3823.62,
                  meta_time=_ts(2026, 9, 25, 15, 0, HKT) if meta_stale else _ts(2026, 9, 28, 15, 0, HKT),
                  regular=(_ts(2026, 9, 29, 9, 30, HKT), _ts(2026, 9, 29, 15, 0, HKT)),
                  currency="CNY")


def _dji_live():
    return _chart("^DJI", [22, 23, 24, 25, 28], [51000.0, 51200.0, 51350.0, 51829.0, 51545.0],
                  ET, -14400, meta_price=51545.0, meta_time=_ts(2026, 9, 28, 14, 56, ET),
                  regular=MON_US_SESSION, currency="USD")


def _wti_ahead():
    return _chart("CL=F", [23, 24, 25, 28, 29], [91.0, 92.0, 92.41, 92.4, 92.4], ET, -14400,
                  currency="USD")


def _install_yahoo(mapping):
    def fake(url, headers=None, params=None, timeout=15, is_json=True):
        for key, payload in mapping.items():
            if key in url:
                return payload
        return None
    return patch.object(pipeline, "safe_request", side_effect=fake)


# ======================================================================
# ① 数据层：meta 回补
# ======================================================================
class SessionBarFromMetaTests(unittest.TestCase):
    def test_gap_after_midnight_is_filled_from_meta(self):
        result = _hsi_gap()["chart"]["result"][0]
        bars = providers.parse_chart_result(result)
        self.assertEqual(bars[-1]["date"], "2026-09-28")
        self.assertTrue(bars[-1]["from_meta"])
        self.assertAlmostEqual(bars[-1]["close"], 24642.51)
        self.assertEqual(bars[-2]["date"], "2026-09-25")
        self.assertIsNone(bars[-1]["open"])              # 开盘价无从得知，不编
        self.assertEqual(bars[-1]["volume"], 987654)

    def test_intraday_quote_is_not_treated_as_a_closed_session(self):
        # 周一 09:53：Yahoo 尚未给出 09-28 实时根，但 meta 已是盘中价 → 不能补成「收盘」
        live = _chart("^HSI", [22, 23, 24, 25], [24800.0, 24700.0, 24760.0, 24510.09], HKT, 28800,
                      meta_price=24710.53, meta_time=_ts(2026, 9, 28, 9, 53, HKT),
                      regular=(_ts(2026, 9, 28, 9, 30, HKT), _ts(2026, 9, 28, 16, 0, HKT)))
        bars = providers.parse_chart_result(live["chart"]["result"][0])
        self.assertEqual(bars[-1]["date"], "2026-09-25")
        self.assertFalse(bars[-1].get("from_meta"))

    def test_meta_not_newer_than_last_bar_is_ignored(self):
        bars = providers.parse_chart_result(_hsi_gap(meta_stale=True)["chart"]["result"][0])
        self.assertEqual(bars[-1]["date"], "2026-09-25")
        self.assertFalse(bars[-1].get("from_meta"))

    def test_missing_trading_period_means_no_fill(self):
        payload = _chart("^HSI", [24, 25], [24760.0, 24510.09], HKT, 28800,
                         meta_price=24642.51, meta_time=_ts(2026, 9, 28, 16, 8, HKT),
                         regular=TUE_HK_SESSION, with_ctp=False)
        self.assertIsNone(providers.session_bar_from_meta(payload["chart"]["result"][0], [
            {"date": "2026-09-25", "close": 24510.09}]))

    def test_trailing_null_close_bar_does_not_advance_date(self):
        # 周一 09:07：Yahoo 已经放出 09-28 的空 K 线（close=None），有效收盘仍是 09-25
        payload = _chart("^HSI", [24, 25, 28], [24760.0, 24510.09, None], HKT, 28800,
                         meta_price=24510.09, meta_time=_ts(2026, 9, 25, 16, 8, HKT),
                         regular=(_ts(2026, 9, 28, 9, 30, HKT), _ts(2026, 9, 28, 16, 0, HKT)))
        bars = providers.parse_chart_result(payload["chart"]["result"][0])
        self.assertEqual([b["date"] for b in bars], ["2026-09-24", "2026-09-25"])

    def test_fetch_bars_uses_meta_fill_for_quant_and_weekly(self):
        calls = []

        def fetch_json(url, params=None, timeout=15):
            calls.append((url, params))
            return _hsi_gap()
        bars = providers.fetch_bars(fetch_json, "^HSI", rng="1y")
        self.assertEqual(bars[-1]["date"], "2026-09-28")
        self.assertTrue(bars[-1]["from_meta"])
        self.assertEqual(calls[0][1]["range"], "1y")

    def test_hk_index_quotes_expose_quote_time(self):
        ts = _ts(2026, 9, 28, 16, 8, HKT)

        def fetch_json(url, params=None, timeout=12):
            self.assertIn("f124", params["fields"])
            return {"data": {"diff": [
                {"f12": "HSI", "f14": "恒生指数", "f2": 24642.51, "f3": 0.54, "f6": 1.2e11, "f124": ts},
                {"f12": "HSTECH", "f14": "恒生科技", "f2": 5600.0, "f3": "-", "f6": "-", "f124": "-"},
            ]}}
        out = providers.fetch_hk_index_quotes(fetch_json)
        self.assertEqual(out["HSI"]["as_of"], "2026-09-28")
        self.assertEqual(out["HSI"]["quote_time"], "2026-09-28 16:08:00")
        self.assertIsNone(out["HSTECH"]["as_of"])
        self.assertIsNone(out["HSTECH"]["chg_pct"])


# ======================================================================
# ② 采集 + 核对层
# ======================================================================
class MarketSnapshotFreshnessTests(unittest.TestCase):
    def test_snapshot_dates_each_quote_and_fills_gap_from_meta(self):
        with _install_yahoo({"HSI": _hsi_gap(), "000001.SS": _sse_gap(),
                             "DJI": _dji_live(), "CL=F": _wti_ahead()}):
            m = pipeline.fetch_market_snapshot()
        q = m["quotes"]
        self.assertEqual(q["恒生指数"]["as_of"], "2026-09-28")
        self.assertEqual(q["恒生指数"]["via"], "meta")
        self.assertAlmostEqual(q["恒生指数"]["change_pct"], (24642.51 / 24510.09 - 1) * 100, places=6)
        self.assertEqual(q["上证指数"]["as_of"], "2026-09-28")
        self.assertAlmostEqual(q["上证指数"]["price"], 3823.62)
        self.assertEqual(q["道琼斯指数"]["as_of"], "2026-09-28")
        self.assertEqual(q["道琼斯指数"]["via"], "bar")
        # WTI 电子盘日期领先，但不能把整份快照拉成 09-29 / 当天
        self.assertEqual(q["WTI 原油"]["as_of"], "2026-09-29")
        self.assertEqual(m["content_date"], "2026-09-28")
        self.assertEqual(m["group_dates"]["港股"], "2026-09-28")
        self.assertEqual(m["lagging"], {})
        self.assertEqual(m["source"], "Yahoo Finance Chart")

    def test_snapshot_flags_lagging_markets_when_meta_is_stale_too(self):
        with _install_yahoo({"HSI": _hsi_gap(meta_stale=True), "000001.SS": _sse_gap(meta_stale=True),
                             "DJI": _dji_live()}):
            m = pipeline.fetch_market_snapshot()
        self.assertEqual(m["quotes"]["恒生指数"]["as_of"], "2026-09-25")
        self.assertEqual(m["content_date"], "2026-09-28")      # 以股票市场最新日期为准
        self.assertEqual(m["lagging"], {"上证指数": "2026-09-25", "恒生指数": "2026-09-25"})

    def test_snapshot_is_not_today_when_only_an_empty_bar_carries_today(self):
        today = datetime.now(pipeline.CST)
        y = today - timedelta(days=1)
        payload = {"chart": {"result": [{
            "meta": {"currency": "HKD", "gmtoffset": 28800},
            "timestamp": [int((y - timedelta(days=1)).replace(hour=9, minute=30).timestamp()),
                          int(y.replace(hour=9, minute=30).timestamp()),
                          int(today.replace(hour=9, minute=30).timestamp())],
            "indicators": {"quote": [{"close": [100.0, 101.0, None], "volume": [1, 1, None]}]},
        }]}}
        with _install_yahoo({"HSI": payload}):
            m = pipeline.fetch_market_snapshot()
        self.assertEqual(m["quotes"]["恒生指数"]["as_of"], y.strftime("%Y-%m-%d"))
        self.assertFalse(m["is_today"])
        self.assertEqual(m["content_date"], y.strftime("%Y-%m-%d"))

    def test_reconcile_replaces_stale_yahoo_rows_with_newer_eastmoney(self):
        with _install_yahoo({"HSI": _hsi_gap(meta_stale=True), "000001.SS": _sse_gap(meta_stale=True),
                             "DJI": _dji_live()}):
            m = pipeline.fetch_market_snapshot()
        pan = {"status": "success", "content_date": "2026-09-28", "quote_time": "2026-09-28 15:00:00",
               "indices": [{"name": "上证指数", "price": 3823.62, "chg_pct": -1.67},
                           {"name": "深证成指", "price": 12858.75, "chg_pct": -3.44}]}
        hk_ref = {"HSI": {"price": 24642.51, "chg_pct": 0.54, "as_of": "2026-09-28",
                          "quote_time": "2026-09-28 16:08:00"},
                  "HSTECH": {"price": 5600.0, "chg_pct": 1.2, "as_of": "2026-09-28",
                             "quote_time": "2026-09-28 16:08:00"}}
        pipeline._reconcile_market_snapshot(m, pan, hk_ref)
        q = m["quotes"]
        self.assertEqual(q["恒生指数"]["via"], "eastmoney")
        self.assertEqual(q["恒生指数"]["as_of"], "2026-09-28")
        self.assertEqual(q["恒生指数"]["yahoo_as_of"], "2026-09-25")
        self.assertAlmostEqual(q["恒生指数"]["change_pct"], 0.54)
        self.assertEqual(q["上证指数"]["via"], "eastmoney")
        self.assertAlmostEqual(q["上证指数"]["price"], 3823.62)
        # A股只回补 Yahoo 已给出的品种（深证成指 Yahoo 没给 → 不填，全景表已有）
        self.assertNotIn("深证成指", q)
        # 港股是主市场：Yahoo 缺失的恒生科技用东财补上
        self.assertEqual(q["恒生科技"]["via"], "eastmoney")
        self.assertEqual(q["道琼斯指数"]["via"], "bar")        # 美股不动
        self.assertEqual(m["lagging"], {})
        self.assertEqual(m["content_date"], "2026-09-28")
        self.assertIn("东方财富回补", m["source"])
        self.assertEqual(sorted(m["patched"]), ["上证指数", "恒生指数", "恒生科技"])

    def test_reconcile_never_downgrades_to_older_or_equal_reference(self):
        with _install_yahoo({"HSI": _hsi_gap(), "DJI": _dji_live()}):
            m = pipeline.fetch_market_snapshot()
        before = dict(m["quotes"]["恒生指数"])
        pipeline._reconcile_market_snapshot(
            m, {"status": "unavailable"},
            {"HSI": {"price": 24510.09, "chg_pct": -1.01, "as_of": "2026-09-25"}})
        self.assertEqual(m["quotes"]["恒生指数"], before)
        pipeline._reconcile_market_snapshot(
            m, None, {"HSI": {"price": 24642.51, "chg_pct": 0.54, "as_of": "2026-09-28"}})
        self.assertEqual(m["quotes"]["恒生指数"]["via"], "meta")   # 同一天不替换
        self.assertEqual(m["patched"], [])
        self.assertEqual(m["source"], "Yahoo Finance Chart")

    def test_reconcile_ignores_unavailable_snapshot(self):
        m = {"status": "unavailable", "quotes": {}}
        self.assertIs(pipeline._reconcile_market_snapshot(m, None, None), m)

    def test_collect_all_data_runs_reconcile_after_panorama(self):
        order = []

        def fake_snapshot():
            order.append("snapshot")
            return {"status": "success", "quotes": {}, "source": "Yahoo Finance Chart"}

        def fake_pan():
            order.append("pan")
            return {"status": "success", "indices": [], "content_date": "2026-09-28"}

        def fake_reconcile(market, pan=None, hk_ref=None):
            order.append("reconcile")
            return market

        stub_result = pipeline._source_result("x", "unavailable", error="stub")
        names = [n for n in dir(pipeline) if n.startswith("fetch_") and n not in
                 ("fetch_market_snapshot", "fetch_market_panorama")]
        patches = [patch.object(pipeline, n, return_value=(
            {} if n == "fetch_public_sites" else stub_result)) for n in names]
        with patch.object(pipeline, "fetch_market_snapshot", side_effect=fake_snapshot), \
                patch.object(pipeline, "fetch_market_panorama", side_effect=fake_pan), \
                patch.object(pipeline, "_reconcile_market_snapshot", side_effect=fake_reconcile), \
                patch.object(pipeline, "_fetch_hk_index_reference", return_value={}), \
                patch.object(pipeline.time, "sleep", return_value=None):
            for p in patches:
                p.start()
            try:
                pipeline.collect_all_data()
            finally:
                for p in patches:
                    p.stop()
        self.assertEqual(order[:3], ["snapshot", "pan", "reconcile"])


# ======================================================================
# ③ 呈现层：日期随数字一起出现
# ======================================================================
class ForecastDatesRenderingTests(unittest.TestCase):
    def _market(self, stale=False):
        with _install_yahoo({"HSI": _hsi_gap(meta_stale=stale), "000001.SS": _sse_gap(meta_stale=stale),
                             "DJI": _dji_live(), "CL=F": _wti_ahead()}):
            return pipeline.fetch_market_snapshot()

    def test_conclusion_lines_carry_as_of_dates(self):
        m = self._market()
        pan = {"status": "success", "content_date": "2026-09-28", "quote_time": "2026-09-28 15:00:00",
               "indices": [{"name": "上证指数", "price": 3823.62, "chg_pct": -1.67}],
               "breadth": {"mood": "普跌弱势", "up": 910, "down": 4607},
               "turnover": {"total": 1716851000000.0, "chg_pct": 2.85}}
        ai = pipeline.build_daily_quant_strategy({"实时行情": m})
        pairs = dict((k, _strip(v)) for k, v in
                     pipeline._conclusion_pairs(pipeline.GUIZANG_KIT, ai, m, pan, {}, None, None))
        self.assertIn("（截至 09-28 15:00）", pairs["A股"])
        self.assertIn("（截至 09-28）", pairs["美股"])
        self.assertIn("恒指 ▲ +0.54%", pairs["港股"])
        self.assertIn("（截至 09-28）", pairs["港股"])
        self.assertIn("（截至 09-28）", pairs["核心判断"])
        self.assertNotIn("数据提示", pairs)
        self.assertNotIn("滞后", " ".join(pairs.values()))

    def test_lagging_markets_are_labelled_and_excluded_from_average(self):
        m = self._market(stale=True)
        pipeline._reconcile_market_snapshot(m, {"status": "unavailable"}, {})   # 东财也拿不到
        ai = pipeline.build_daily_quant_strategy({"实时行情": m})
        self.assertIn("A股、港股行情滞后未计入", ai["reason"])
        self.assertIn("截至 09-28", ai["reason"])
        # 均值只剩美股 + WTI：(-0.55% + 0%) / 2
        self.assertIn("-0.27%", ai["reason"])
        pairs = dict((k, _strip(v)) for k, v in
                     pipeline._conclusion_pairs(pipeline.GUIZANG_KIT, ai, m,
                                                {"status": "unavailable"}, {}, None, None))
        self.assertIn("（截至 09-25 · 滞后）", pairs["港股"])
        self.assertIn("（截至 09-25 · 滞后）", pairs["A股"])
        self.assertIn("数据提示", pairs)
        # 入门版（默认）：数据提示压成一句——落后的市场 / 日期 / 最新交易日都在，逐指数清单不列
        self.assertIn("A股、港股行情截至 09-25", pairs["数据提示"])
        self.assertIn("09-28", pairs["数据提示"])
        self.assertNotIn("上游行情源尚未更新", pairs["数据提示"])
        with pipeline.notes_mode():
            pairs = dict((k, _strip(v)) for k, v in
                         pipeline._conclusion_pairs(pipeline.GUIZANG_KIT, ai, m,
                                                    {"status": "unavailable"}, {}, None, None))
        self.assertIn("恒生指数 09-25", pairs["数据提示"])
        self.assertIn("09-28", pairs["数据提示"])

    def test_market_section_captions_show_dates_in_both_themes(self):
        m = self._market(stale=True)
        for section in (pipeline.gz_market_section(m), pipeline._pixel_market_section(m)):
            text = _strip(section)
            self.assertIn("全球与美股 · 截至 09-28", text)
            self.assertIn("港股双指数 · 截至 09-25 · 滞后", text)
            self.assertIn("恒生指数（09-25）", text)
        pipeline._reconcile_market_snapshot(
            m, None, {"HSI": {"price": 24642.51, "chg_pct": 0.54, "as_of": "2026-09-28"}})
        text = _strip(pipeline.gz_market_section(m))
        self.assertIn("港股双指数 · 截至 09-28", text)
        self.assertIn("恒生指数（东财）", text)
        self.assertNotIn("滞后", text.split("港股双指数")[1])

    def test_generated_report_forecast_block_shows_dates(self):
        m = self._market()
        data = {"实时行情": m}
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(data, "2026年9月29日 · 周二", "20260929", theme=theme)
            text = _strip(html)
            i = text.find("【回游金枪鱼】今日预判")
            self.assertGreater(i, -1)
            self.assertIn("截至 09-28", text[i:i + 1500])
            self.assertIn("恒指 ▲ +0.54%", text[i:i + 1500])
            self.assertIn("全球与美股 · 截至 09-28", text)


if __name__ == "__main__":
    unittest.main()
