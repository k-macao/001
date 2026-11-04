"""🇭🇰 港股 Yahoo 代码格式回归测试（不发任何网络请求）。

复现 2026-11-04 用户贴的「大量请求失败」：

    ⚠️ 请求失败 [https://query1.finance.yahoo.com/v8/finance/chart/06160.HK?range=2y&interval=1d]:
    404 Client Error: Not Found

根因：**Yahoo 的港股代码是 4 位补零，不是交易所 / 东财的 5 位**。同一天、同一接口实测：

| 代码 | Yahoo 结果 |
|---|---|
| `0700.HK` | ✅ 腾讯 401.6 |
| `00700.HK` | ❌ `result:null`「No data found, symbol may be delisted」 |
| `0005.HK` | ✅ 汇丰 136.4 |
| `6160.HK` | ✅ BeOne Medicines 231.6，2 年日线齐全 |
| `06160.HK` | ❌ HTTP 404 |

内部一律存 5 位（东财 / 交易所口径），**只在拼 Yahoo URL 时**折成 4 位。
本文件守住四件事：
  ① 所有 Yahoo 取数路径拿到的都是 4 位代码（低因子批量 / 量化引擎 / 行情库 / 快照）；
  ② 环境变量给的任意写法（`700.HK` / `00700.HK` / `06160.HK`）先折成内部 5 位；
  ③ 长代码（>4 位，如 5 位新能源车 / 生物科技代码）只去掉前导零，绝不截断；
  ④ 批量取数不再逐条刷失败日志，改成一行汇总（线程池里的 worker 也要看得见闸门）。
"""
import sys
import types
import unittest
from pathlib import Path

sys.modules.setdefault("requests", types.SimpleNamespace())

REPO_ROOT = Path(__file__).parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
if str(OUTPUT_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUT_DIR))

import backup_sources as bk                 # noqa: E402
import lowfreq_factors as lf                # noqa: E402
import market_db as mdb                     # noqa: E402
from octopus_quant import providers         # noqa: E402


class YahooHkCodeTests(unittest.TestCase):
    def test_five_digit_codes_fold_to_four(self):
        self.assertEqual(bk.yahoo_hk_code("06160"), "6160")
        self.assertEqual(bk.yahoo_hk_code("00700"), "0700")
        self.assertEqual(bk.yahoo_hk_code("09988"), "9988")
        self.assertEqual(bk.yahoo_hk_code("00005"), "0005")
        self.assertEqual(providers.yahoo_hk_code("06160.HK"), "6160.HK")
        self.assertEqual(providers.yahoo_hk_code("00700.HK"), "0700.HK")

    def test_already_correct_codes_are_untouched(self):
        self.assertEqual(bk.yahoo_hk_code("0700"), "0700")
        self.assertEqual(bk.yahoo_hk_code("6160"), "6160")
        self.assertEqual(bk.yahoo_hk_code("0005"), "0005")

    def test_short_and_long_codes_are_padded_not_truncated(self):
        self.assertEqual(bk.yahoo_hk_code("700"), "0700")      # 3 位补到 4 位
        self.assertEqual(bk.yahoo_hk_code("5"), "0005")
        # 5 位有效代码（如 06160 之外的真·5 位代码）只去前导零，绝不截断成 4 位
        self.assertEqual(bk.yahoo_hk_code("12345"), "12345")

    def test_non_hk_symbols_pass_through(self):
        for sym in ("^HSI", "HSTECH.HK", "600519.SS", "MSFT", "CL=F", "^HSTECH"):
            with self.subTest(symbol=sym):
                self.assertEqual(bk.yahoo_hk_code(sym), sym)
                self.assertFalse(bk.is_hk_yahoo_symbol(sym))

    def test_symbol_chain_starts_with_four_digit_form(self):
        self.assertEqual(bk.yahoo_symbols_for("06160.HK"), ("6160.HK", "06160.HK"))
        self.assertEqual(bk.yahoo_symbols_for("00700.HK"), ("0700.HK", "00700.HK"))
        self.assertEqual(bk.yahoo_symbols_for("0700.HK"), ("0700.HK",))
        self.assertEqual(providers.yahoo_symbols_for("06160.HK"), ("6160.HK", "06160.HK"))

    def test_yahoo_urls_never_use_five_digit_hk_code(self):
        urls = bk.get_yahoo_urls("06160.HK")
        self.assertEqual(urls[:2], [
            "https://query1.finance.yahoo.com/v8/finance/chart/6160.HK",
            "https://query2.finance.yahoo.com/v8/finance/chart/6160.HK",
        ])
        self.assertTrue(all("06160.HK" not in u for u in urls[:2]))
        # 指数 / A股 / 美股不受影响
        self.assertEqual(bk.get_yahoo_urls("^HSTECH")[0],
                         "https://query1.finance.yahoo.com/v8/finance/chart/HSTECH.HK")

    def test_data_line_registry_rewrites_symbol_for_bars_and_snapshot(self):
        for line in ("yahoo_chart", "yahoo_bars"):
            with self.subTest(line=line):
                self.assertTrue(bk.urls(line, symbol="06160.HK")[0].endswith("/6160.HK"))
                self.assertTrue(bk.candidates(line, symbol="06160.HK")[0][1].endswith("/6160.HK"))


class FetchPathTests(unittest.TestCase):
    """四条 Yahoo 取数路径都要拿到 4 位代码。"""

    def test_lowfreq_batch_uses_four_digit_symbols(self):
        self.assertEqual(lf._yahoo_hk_symbol("06160"), "6160.HK")
        self.assertEqual(lf._yahoo_hk_symbol("00700"), "0700.HK")
        self.assertEqual(lf._yahoo_hk_symbol("0005"), "0005.HK")
        seen = []

        def batch(fetch_json, specs, **kw):
            seen.extend(specs)
            return {sym: [{"date": "2026-11-04", "close": 1.0}] for _code, sym in specs}

        with unittest.mock.patch.object(providers, "fetch_series_batch", side_effect=batch):
            out = lf.fetch_hk_bars(lambda *a, **k: None, ["06160", "00700", "0005"])
        self.assertEqual({sym for _code, sym in seen},
                         {"6160.HK", "0700.HK", "0005.HK"})
        self.assertEqual(sorted(out), ["00005", "00700", "06160"])   # 内部仍是 5 位

    def test_market_db_yahoo_codes(self):
        self.assertEqual(mdb._yahoo_hk_code("06160.HK"), "6160.HK")
        self.assertEqual(mdb._yahoo_hk_code("^HSTECH"), "^HSTECH")

    def test_env_universe_is_canonicalised(self):
        for raw in ("700.HK", "0700.HK", "00700.HK"):
            with self.subTest(raw=raw):
                self.assertEqual(providers._canonical_hk_symbol(raw), "00700.HK")
        self.assertEqual(providers._canonical_hk_symbol("06160.HK"), "06160.HK")
        self.assertEqual(providers._canonical_hk_symbol("^HSI"), "^HSI")

    def test_env_universe_roundtrip_to_yahoo(self):
        import os
        from unittest.mock import patch as _patch
        with _patch.dict(os.environ, {"OCTOPUS_HK_UNIVERSE": "700.HK:腾讯,06160.HK:百济"}):
            universe = providers.hk_stock_universe()
        codes = [code for _label, code in universe]
        self.assertEqual(codes, ["00700.HK", "06160.HK"])
        self.assertEqual([providers.yahoo_symbols_for(c)[0] for c in codes],
                         ["0700.HK", "6160.HK"])


class RequestLogGateTests(unittest.TestCase):
    """批量取数不该把日志刷成一片「⚠️ 请求失败」。"""

    def test_batch_mode_counts_without_printing(self):
        printed = []
        providers._REQUEST_FAILURES.update({"batch": 0, "single": 0})

        def raiser(*a, **k):
            raise RuntimeError("404 Client Error: Not Found")

        with unittest.mock.patch.object(providers, "request_log_quiet", return_value=True), \
                unittest.mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            # 直接验证计数口径（pipeline.safe_request 用同一个闸门）
            quiet = providers.note_request_failure()
        self.assertTrue(quiet)
        self.assertEqual(printed, [])
        self.assertEqual(providers.request_failures()["batch"], 1)

    def test_gate_is_process_wide_so_thread_pool_workers_see_it(self):
        import concurrent.futures as cf
        seen = []

        def worker(_i):
            seen.append(providers.request_log_quiet())
            return providers.note_request_failure()

        with providers.request_quiet() as quiet:
            with cf.ThreadPoolExecutor(4) as pool:
                list(pool.map(worker, range(8)))
        self.assertTrue(all(seen), "worker 线程必须看见静音开关")
        self.assertEqual(quiet.failed, 8)
        self.assertFalse(providers.request_log_quiet())      # 退出后恢复

    def test_single_request_still_prints(self):
        printed = []
        pipeline_module = self._pipeline()
        with unittest.mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            pipeline_module.safe_request("https://example.invalid/x")
        self.assertTrue(any("请求失败" in line for line in printed))

    def test_batch_request_is_silent(self):
        printed = []
        pipeline_module = self._pipeline()
        with providers.request_quiet() as quiet, \
                unittest.mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            for i in range(5):
                pipeline_module.safe_request(f"https://example.invalid/{i}")
        self.assertEqual([p for p in printed if "请求失败" in p], [])
        self.assertEqual(quiet.failed, 5)

    @staticmethod
    def _pipeline():
        import importlib.util
        spec = importlib.util.spec_from_file_location("pipeline_under_hkcode_test",
                                                      OUTPUT_DIR / "pipeline.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


import unittest.mock  # noqa: E402  (放在末尾避免与 unittest 别名混淆)

if __name__ == "__main__":
    unittest.main()
