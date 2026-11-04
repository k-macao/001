"""📉 恒生科技代码回归测试（不发任何网络请求）。

复现 2026-11-04 线上事故：抓行情时刷出

    📡 正在抓取全球/A股实时行情...
      ⚠️ 请求失败 [https://query1.finance.yahoo.com/v8/finance/chart/%5EHSTECH?...]: 404 ...

根因（当日实测）：
  ① Yahoo 已不再提供 ``^HSTECH`` —— HTTP 200，正文是
     ``{"chart":{"result":null,"error":{"code":"Not Found",
     "description":"No data found, symbol may be delisted"}}}``；
  ② 同一接口的 ``^HSI`` 正常 → 不是 Yahoo 整体故障；
  ③ Yahoo 搜索里恒生科技指数只剩 ``HSTECH.HK``，而它只返回 **一根** 当日报价
     （``validRanges:["1d","5d"]``，没有历史序列），旧解析器要求 ≥2 根 K 线，
     于是把唯一还能用的 Yahoo 报价也判死（「报价记录不足」）；
  ④ 东方财富的现行 secid 是 ``124.HSTECH``，旧的 ``100.HSTECH`` 已失效
     （日K ``rc:100 / data:null``，ulist ``rc:102 / data:null``）。

三道防线各自可测：
  ① 代码层：``^HSTECH`` 的 Yahoo / 东财代码候选链先给现行代码（backup_sources / providers）；
  ② 解析层：meta-only 响应（1 根报价）用 meta 最新价 + ``chartPreviousClose`` 组出报价，
     不再因为「报价记录不足」丢掉整行；缺字段时仍然判失败，绝不拿猜的数字充数；
  ③ 备用源层：东财批量快照里一个失效 secid 不再拖垮整批，缺行的品种用备用编号单独补请。
"""
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("requests", types.SimpleNamespace())

REPO_ROOT = Path(__file__).parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
if str(OUTPUT_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUT_DIR))

import backup_sources as bk             # noqa: E402
from octopus_quant import providers     # noqa: E402

MODULE_PATH = OUTPUT_DIR / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_hstech_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

HKT = timezone(timedelta(hours=8))

# 2026-11-04 16:08 HKT（收盘后）——与东财 124.HSTECH、腾讯 r_hkHSTECH 同一个报价时点
QUOTE_TS = int(datetime(2026, 11, 4, 16, 8, 34, tzinfo=HKT).timestamp())


def _meta_only_chart(symbol="HSTECH.HK", price=3936.02, prev=3867.73, ts=QUOTE_TS):
    """Yahoo 对 ``HSTECH.HK`` 的真实返回：只有 1 根报价，没有历史序列。"""
    return {"chart": {"result": [{
        "meta": {
            "currency": None, "symbol": symbol, "exchangeName": "HKG",
            "instrumentType": "INDEX", "gmtoffset": 28800, "timezone": "HKT",
            "regularMarketTime": ts, "regularMarketPrice": price,
            "regularMarketDayHigh": 3939.53, "regularMarketDayLow": 3796.23,
            "regularMarketVolume": 0, "chartPreviousClose": prev,
            "currentTradingPeriod": {
                "regular": {"start": QUOTE_TS - 6 * 3600, "end": QUOTE_TS - 480, "gmtoffset": 28800}},
            "dataGranularity": "1d", "range": "5d", "validRanges": ["1d", "5d"],
        },
        "timestamp": [ts],
        "indicators": {"quote": [{"open": [3848.21], "high": [3939.53], "low": [3796.23],
                                  "close": [price], "volume": [0]}]},
    }], "error": None}}


def _delisted_chart():
    """Yahoo 对 ``^HSTECH`` 的真实返回：200 + result:null。"""
    return {"chart": {"result": None, "error": {
        "code": "Not Found", "description": "No data found, symbol may be delisted"}}}


# ======================================================================
# ① 代码候选链
# ======================================================================
class SymbolChainTests(unittest.TestCase):
    def test_yahoo_urls_never_lead_with_delisted_code(self):
        for symbol in ("^HSTECH", "%5EHSTECH"):
            with self.subTest(symbol=symbol):
                urls = bk.get_yahoo_urls(symbol)
                self.assertEqual(urls[:2], [
                    "https://query1.finance.yahoo.com/v8/finance/chart/HSTECH.HK",
                    "https://query2.finance.yahoo.com/v8/finance/chart/HSTECH.HK",
                ])
                # 已下线的原代码留作最后一试（万一恢复），但绝不排在前面白等一次超时
                self.assertEqual(urls[2:], [
                    f"https://query{i}.finance.yahoo.com/v8/finance/chart/{symbol}"
                    for i in (1, 2)])

    def test_other_symbols_are_untouched(self):
        self.assertEqual(bk.get_yahoo_urls("^HSI"), [
            "https://query1.finance.yahoo.com/v8/finance/chart/^HSI",
            "https://query2.finance.yahoo.com/v8/finance/chart/^HSI",
        ])
        self.assertEqual(bk.yahoo_symbols_for("0700.HK"), ("0700.HK",))

    def test_eastmoney_secid_primary_is_124(self):
        for symbol in ("^HSTECH", "%5EHSTECH"):
            with self.subTest(symbol=symbol):
                self.assertEqual(bk.em_secid_for_yahoo(symbol), "124.HSTECH")
                self.assertEqual(bk.em_secids_for_yahoo(symbol), ("124.HSTECH", "100.HSTECH"))
        self.assertEqual(bk.em_secid_for_yahoo("^HSI"), "100.HSI")
        self.assertEqual(bk.em_secids_for_yahoo("^HSI"), ("100.HSI",))
        self.assertEqual(bk.em_secids_for_yahoo("XYZ"), ())

    def test_data_line_registry_uses_current_code(self):
        # yahoo_chart / yahoo_bars 两条线拼 URL 时都要换成现行代码
        for line in ("yahoo_chart", "yahoo_bars"):
            with self.subTest(line=line):
                urls = bk.urls(line, symbol="^HSTECH")
                self.assertEqual(len(urls), 2)
                self.assertTrue(all(u.endswith("HSTECH.HK") for u in urls))

    def test_providers_fallbacks_match_registry(self):
        self.assertEqual(providers.em_secid_for_yahoo("^HSTECH"), "124.HSTECH")
        self.assertEqual(providers.em_secids_for_yahoo("^HSTECH"), ("124.HSTECH", "100.HSTECH"))
        self.assertEqual(providers.yahoo_symbols_for("^HSTECH"), ("HSTECH.HK",))


# ======================================================================
# ② meta-only 解析
# ======================================================================
class MetaOnlyQuoteTests(unittest.TestCase):
    def test_single_bar_payload_yields_meta_only_quote(self):
        quote = pipeline._yahoo_quote_from_chart(_meta_only_chart())
        self.assertEqual(quote["via"], "meta_only")
        self.assertAlmostEqual(quote["price"], 3936.02)
        self.assertAlmostEqual(quote["change_pct"], (3936.02 / 3867.73 - 1) * 100, places=6)
        self.assertEqual(quote["as_of"], "2026-11-04")   # 交易所本地（HKT）日期
        self.assertIsNone(quote["prev_date"])            # meta 不提供前收所属交易日 → 不编
        self.assertEqual(quote["volume"], 0)

    def test_null_result_is_a_failed_source_not_an_exception_type(self):
        # result:null 让校验函数返回 False → safe_request_with_fallback 继续试下一路，
        # 而不是抛 AttributeError/TypeError 把整个抓取流程打断。
        def _chart_ok(payload):
            try:
                pipeline._yahoo_quote_from_chart(payload)
                return True
            except (KeyError, TypeError, IndexError, ValueError, ZeroDivisionError):
                return False
        self.assertFalse(_chart_ok(_delisted_chart()))
        self.assertFalse(_chart_ok({"chart": {"result": []}}))
        self.assertFalse(_chart_ok({}))
        with self.assertRaises(ValueError):
            pipeline._yahoo_quote_from_chart(_delisted_chart())

    def test_missing_meta_fields_fall_back_to_failure(self):
        for key in ("regularMarketPrice", "chartPreviousClose", "regularMarketTime"):
            with self.subTest(missing=key):
                payload = _meta_only_chart()
                del payload["chart"]["result"][0]["meta"][key]
                with self.assertRaises(ValueError):
                    pipeline._yahoo_quote_from_chart(payload)

    def test_two_bar_payload_still_uses_bars(self):
        payload = _meta_only_chart()
        result = payload["chart"]["result"][0]
        result["timestamp"] = [QUOTE_TS - 86400, QUOTE_TS]
        result["indicators"]["quote"][0] = {"close": [3867.73, 3936.02], "volume": [1, 2]}
        quote = pipeline._yahoo_quote_from_chart(payload)
        self.assertEqual(quote["via"], "bar")
        self.assertEqual(quote["prev_date"], "2026-11-03")


# ======================================================================
# ③ 东财备用源：失效 secid 不拖垮整批
# ======================================================================
class EastmoneySnapshotTests(unittest.TestCase):
    def _payload(self, rows):
        return {"rc": 0, "data": {"total": len(rows), "diff": rows}}

    def test_dead_secid_does_not_kill_the_whole_batch(self):
        """历史事故：secids 里混进 100.HSTECH 会让整条 ulist 返回 rc:102 / data:null。"""
        calls = []

        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            if "ulist.np" not in url:
                return None
            secids = params["secids"].split(",")
            calls.append(secids)
            if "124.HSTECH" in secids:
                return self._payload([
                    {"f12": "HSTECH", "f13": 124, "f14": "恒生科技指数", "f2": 3936.02,
                     "f3": 1.77, "f124": QUOTE_TS},
                    {"f12": "HSI", "f13": 100, "f14": "恒生指数", "f2": 23919.5, "f3": 1.67,
                     "f124": QUOTE_TS},
                ])
            return {"rc": 102, "data": None}

        with patch.object(pipeline, "safe_request", side_effect=fake):
            out = pipeline._eastmoney_snapshot_quotes([("恒生科技", "%5EHSTECH"), ("恒生指数", "%5EHSI")])
        self.assertEqual(calls, [["124.HSTECH", "100.HSI"]])
        self.assertAlmostEqual(out["恒生科技"]["price"], 3936.02)
        self.assertEqual(out["恒生科技"]["currency"], "HKD")     # 124 = 港股指数
        self.assertEqual(out["恒生科技"]["via"], "eastmoney")
        self.assertAlmostEqual(out["恒生指数"]["price"], 23919.5)

    def test_missing_row_triggers_one_retry_with_alternate_secid(self):
        calls = []

        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            if "ulist.np" not in url:
                return None
            secids = params["secids"].split(",")
            calls.append(secids)
            if "100.HSTECH" in secids:                       # 备用编号这一次拿到了
                return self._payload([{"f12": "HSTECH", "f13": 100, "f14": "恒生科技指数",
                                       "f2": 3936.02, "f3": 1.77, "f124": QUOTE_TS}])
            return self._payload([{"f12": "HSI", "f13": 100, "f14": "恒生指数",
                                   "f2": 23919.5, "f3": 1.67, "f124": QUOTE_TS}])

        with patch.object(pipeline, "safe_request", side_effect=fake):
            out = pipeline._eastmoney_snapshot_quotes([("恒生科技", "%5EHSTECH"), ("恒生指数", "%5EHSI")])
        self.assertEqual(calls, [["124.HSTECH", "100.HSI"], ["100.HSTECH"]])
        self.assertAlmostEqual(out["恒生科技"]["price"], 3936.02)


class ProvidersBarsTests(unittest.TestCase):
    def test_fetch_bars_tries_124_before_100(self):
        seen = []

        def fetch_json(url, params=None, timeout=15):
            if "yahoo" in url:
                return None
            secid = params.get("secid")
            seen.append(secid)
            if secid == "124.HSTECH":
                return {"rc": 0, "data": {"klines": ["2026-11-03,3853.17,3867.73,3898.71,3832.93,1273905776",
                                                     "2026-11-04,3848.21,3936.02,3939.53,3796.23,1453555216"]}}
            return {"rc": 100, "data": None}                 # 100.HSTECH 已失效

        bars = providers.fetch_bars(fetch_json, "^HSTECH", rng="1mo")
        self.assertEqual(bars[-1]["date"], "2026-11-04")
        self.assertAlmostEqual(bars[-1]["close"], 3936.02)
        self.assertEqual(set(seen), {"124.HSTECH"})

    def test_dead_primary_secid_falls_through_to_backup(self):
        seen = []

        def fetch_json(url, params=None, timeout=15):
            if "yahoo" in url:
                return None
            secid = params.get("secid")
            seen.append(secid)
            if secid == "100.HSTECH":
                return {"rc": 0, "data": {"klines": ["2026-11-04,3848.21,3936.02,3939.53,3796.23,1453555216"]}}
            return {"rc": 100, "data": None}

        bars = providers.fetch_bars(fetch_json, "^HSTECH", rng="1mo")
        self.assertAlmostEqual(bars[-1]["close"], 3936.02)
        self.assertEqual(seen[0], "124.HSTECH")          # 现行编号先试
        self.assertIn("100.HSTECH", seen)


# ======================================================================
# ④ 端到端：恒生科技不再缺行、不再刷「请求失败」
# ======================================================================
class SnapshotEndToEndTests(unittest.TestCase):
    def test_hstech_row_survives_meta_only_yahoo(self):
        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            if "HSTECH.HK" in url:
                return _meta_only_chart()
            if "eastmoney" in url or "push2" in url:
                return None                                  # 备用源也不可用
            return None

        printed = []
        with patch.object(pipeline, "safe_request", side_effect=fake), \
                patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            market = pipeline.fetch_market_snapshot()
        quote = market["quotes"].get("恒生科技")
        self.assertIsNotNone(quote, "恒生科技不应整行缺失")
        self.assertEqual(quote["via"], "meta_only")
        self.assertAlmostEqual(quote["price"], 3936.02)
        self.assertEqual(quote["as_of"], "2026-11-04")
        self.assertEqual(market["served_by"]["恒生科技"], "主源")
        # 请求路径里不再出现已下线的 ^HSTECH / %5EHSTECH
        joined = "\n".join(printed)
        self.assertNotIn("%5EHSTECH", joined)

    def test_market_snapshot_reports_failure_for_delisted_payload(self):
        """若 Yahoo 两个代码都失效，恒生科技应如实缺席（不编数字），其余品种不受影响。"""
        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            if "HSI" in url and "HSTECH" not in url:
                payload = _meta_only_chart(symbol="^HSI", price=23919.5, prev=23525.97)
                return payload
            if "HSTECH" in url:
                return _delisted_chart()
            return None

        with patch.object(pipeline, "safe_request", side_effect=fake), \
                patch("builtins.print"):
            market = pipeline.fetch_market_snapshot()
        self.assertNotIn("恒生科技", market["quotes"])
        self.assertIn("恒生指数", market["quotes"])
        self.assertTrue(market["partial"])


if __name__ == "__main__":
    unittest.main()
