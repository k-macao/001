import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "output"))
import index_crosscheck as ic


class SingleSourceFailoverTests(unittest.TestCase):
    def _yahoo_chart(self, close=100, day=(2026, 10, 20, 8)):
        stamp = int(datetime(*day, tzinfo=timezone.utc).timestamp())
        return {"chart": {"result": [{"timestamp": [stamp], "indicators": {"quote": [{"close": [close]}]}}]}}

    def test_primary_yahoo_query1_succeeds_without_touching_backups(self):
        urls = []

        def fetch(url, **kwargs):
            urls.append(url)
            if "query1.finance.yahoo.com" in url:
                return self._yahoo_chart(100)
            raise AssertionError(f"备用源不应在主源成功时被请求: {url}")

        with patch.object(ic, "SPECS", ic.SPECS[:1]):
            r = ic.collect(fetch, now=datetime(2026, 10, 21, tzinfo=timezone.utc))[0]
        self.assertTrue(r["usable"])
        self.assertEqual(r["status"], "正常")
        self.assertFalse(r["is_backup"])
        self.assertEqual(r["close"], 100.0)
        self.assertEqual(r["as_of"], "2026-10-20")
        self.assertIsNone(r["ret_20d"])
        self.assertEqual(len(urls), 1)

    def test_query1_fails_falls_back_to_query2_without_eastmoney(self):
        urls = []

        def fetch(url, **kwargs):
            urls.append(url)
            if "query1.finance.yahoo.com" in url:
                return None
            if "query2.finance.yahoo.com" in url:
                return self._yahoo_chart(105)
            raise AssertionError(f"东财备用源不应在 query2 已成功时被请求: {url}")

        with patch.object(ic, "SPECS", ic.SPECS[:1]):
            r = ic.collect(fetch, now=datetime(2026, 10, 21, tzinfo=timezone.utc))[0]
        self.assertTrue(r["usable"])
        self.assertEqual(r["status"], "备用源启用")
        self.assertTrue(r["is_backup"])
        self.assertEqual(r["close"], 105.0)
        self.assertTrue(all("eastmoney" not in u for u in urls))

    def test_yahoo_fails_falls_back_to_eastmoney_mirror_and_secid_alias(self):
        def fetch(url, params=None, **kwargs):
            if "yahoo.com" in url:
                return None
            # 模拟主域名及 100.HSTECH 均失败，91 镜像 + 124.HSTECH 成功
            if "91.push2his.eastmoney.com" in url and (params or {}).get("secid") == "124.HSTECH":
                return {"data": {"name": "恒生科技指数", "klines": ["2026-10-20,5800,5860,5900,5790,1"]}}
            return None

        hstech_spec = [s for s in ic.SPECS if s[2] == "^HSTECH"]
        with patch.object(ic, "SPECS", hstech_spec):
            r = ic.collect(fetch, now=datetime(2026, 10, 21, tzinfo=timezone.utc))[0]
        self.assertTrue(r["usable"])
        self.assertEqual(r["status"], "备用源启用")
        self.assertTrue(r["is_backup"])
        self.assertEqual(r["close"], 5860.0)
        self.assertEqual(r["source"], "eastmoney")
        self.assertIn("东方财富", r["source_label"])

    def test_eastmoney_nasdaq_guard_accepts_nasdaq_and_rejects_100(self):
        ixic_spec = [s for s in ic.SPECS if s[2] == "^IXIC"]

        def fetch_bad(url, **kwargs):
            if "yahoo.com" in url:
                return None
            return {"data": {"name": "纳斯达克100", "klines": ["2026-10-20,18000,18100,18200,17900,1"]}}

        def fetch_good(url, **kwargs):
            if "yahoo.com" in url:
                return None
            return {"data": {"name": "纳斯达克", "klines": ["2026-10-20,18000,18100,18200,17900,1"]}}

        with patch.object(ic, "SPECS", ixic_spec):
            bad = ic.collect(fetch_bad, now=datetime(2026, 10, 21, 10, tzinfo=timezone.utc))[0]
            good = ic.collect(fetch_good, now=datetime(2026, 10, 21, 10, tzinfo=timezone.utc))[0]
        self.assertFalse(bad["usable"])
        self.assertEqual(bad["status"], "暂缺")
        self.assertTrue(good["usable"])
        self.assertEqual(good["status"], "备用源启用")

    def test_all_sources_missing(self):
        with patch.object(ic, "SPECS", ic.SPECS[:1]):
            r = ic.collect(lambda *a, **kw: None, now=datetime(2026, 10, 21, tzinfo=timezone.utc))[0]
        self.assertFalse(r["usable"])
        self.assertEqual(r["status"], "暂缺")

    def test_stale(self):
        def fetch(url, **kwargs):
            if "query1.finance.yahoo.com" in url:
                return self._yahoo_chart(100, day=(2026, 10, 20, 8))
            return None

        with patch.object(ic, "SPECS", ic.SPECS[:1]):
            r = ic.collect(fetch, now=datetime(2026, 10, 27, tzinfo=timezone.utc))[0]
        self.assertFalse(r["usable"])
        self.assertEqual(r["status"], "数据过期")

    def test_invalid_close_triggers_failover_or_unavailable(self):
        for close in [float("nan"), float("inf"), -1, 0]:
            def fetch(url, _c=close, **kwargs):
                if "yahoo.com" in url:
                    return self._yahoo_chart(_c)
                return None

            with patch.object(ic, "SPECS", ic.SPECS[:1]):
                r = ic.collect(fetch, now=datetime(2026, 10, 21, tzinfo=timezone.utc))[0]
            self.assertFalse(r["usable"])

    def test_intraday_filtered(self):
        self.assertEqual(ic._clean([("2026-10-21", 100)], "^HSI", datetime(2026, 10, 21, 3, tzinfo=timezone.utc)), {})

    def test_closed_session_meta_supplements_lagging_kline(self):
        t_prev = int(datetime(2026, 10, 19, 8, tzinfo=timezone.utc).timestamp())
        t_close = int(datetime(2026, 10, 20, 8, 10, tzinfo=timezone.utc).timestamp())
        payload = {
            "chart": {
                "result": [{
                    "meta": {"regularMarketPrice": 20500.5, "regularMarketTime": t_close},
                    "timestamp": [t_prev],
                    "indicators": {"quote": [{"close": [20300.0]}]},
                }]
            }
        }
        with patch.object(ic, "SPECS", [s for s in ic.SPECS if s[2] == "^HSI"]):
            r = ic.collect(lambda url, **kw: payload if "query1" in url else None,
                           now=datetime(2026, 10, 20, 9, tzinfo=timezone.utc))[0]
        self.assertTrue(r["usable"])
        self.assertEqual(r["as_of"], "2026-10-20")
        self.assertEqual(r["close"], 20500.5)


if __name__ == "__main__":
    unittest.main()
