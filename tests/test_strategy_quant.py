"""策略大类量化（output/strategy_quant.py）离线回归。

口径与日报其它栏目一致：
  · 取不到基准指数日线的细分**如实标暂缺**，绝不补造数字；
  · 只有显式 `allow_synthetic`（OCTOPUS_STRATEGY_DEMO=1 / 测试）才用确定性合成序列兜底，
    并在结果里 `synthetic=True`，页面点名「演示序列」；
  · 大类 = 细分均值；信号分只用于大类内排序，不是涨跌概率；
  · 本栏是内部衍生，不计入当天检验（is_today=False），取不到时在「数据覆盖」点名。
"""
import importlib.util
import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("requests", types.SimpleNamespace())
MODULE_PATH = Path(__file__).parents[1] / "output" / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_strategy_quant_under_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

sq = pipeline._strategy_quant


def _bars(symbol, n=160, drift=0.0004, vol=0.011, seed_extra=""):
    """确定性合成日线（测试夹具；与产品里的兜底序列无关）。"""
    import random
    rng = random.Random(sum(map(ord, symbol + seed_extra)))
    price, out = 100.0, []
    for i in range(n):
        price *= 1 + rng.gauss(drift, vol)
        out.append({"date": f"2026-{(i // 28) + 3:02d}-{(i % 28) + 1:02d}",
                    "close": round(price, 2)})
    return out


class StrategyQuantEngineTests(unittest.TestCase):
    """计算层：缺数不造假 / 合成需显式开启 / 指标口径确定。"""

    def test_unavailable_without_bars_and_without_synthetic(self):
        res = sq.run_strategy_quant(None, date_str="20261021", allow_synthetic=False)
        self.assertFalse(res["available"])
        self.assertEqual(len(res["missing"]), 6)
        self.assertIn("基准指数日线均未取得", res["reason"])
        self.assertEqual(res["strategies"], [])

    def test_synthetic_only_when_explicitly_allowed(self):
        res = sq.run_strategy_quant(None, date_str="20261021", allow_synthetic=True)
        self.assertTrue(res["available"])
        self.assertTrue(res["synthetic"])
        self.assertEqual(len(res["strategies"]), 6)
        self.assertEqual(set(res["by_major"]), {"权益多头", "纯债策略", "CTA策略", "套利策略"})
        for s in res["strategies"]:
            self.assertTrue(s["synthetic"])
            self.assertEqual(s["source"], "合成演示序列")

    def test_synthetic_is_deterministic(self):
        first = sq.run_strategy_quant(None, date_str="20261021", allow_synthetic=True)
        second = sq.run_strategy_quant(None, date_str="20261021", allow_synthetic=True)
        self.assertEqual(
            [(s["label"], s["close"], s["ret_20d"], s["score"]) for s in first["strategies"]],
            [(s["label"], s["close"], s["ret_20d"], s["score"]) for s in second["strategies"]],
        )

    def test_real_bars_path_computes_metrics_and_records_source(self):
        def fake_fetch(fetch_json, symbol, **kw):
            return _bars(symbol)

        import octopus_quant.providers as providers
        original = providers.fetch_bars
        providers.fetch_bars = fake_fetch
        try:
            res = sq.run_strategy_quant(lambda *a, **k: {}, date_str="20261021")
        finally:
            providers.fetch_bars = original
        self.assertTrue(res["available"])
        self.assertFalse(res["synthetic"])
        self.assertEqual(res["missing"], [])
        self.assertEqual(len(res["strategies"]), 6)
        for s in res["strategies"]:
            self.assertTrue(s["source"].startswith("基准指数 "))
            self.assertIsNotNone(s["ret_20d"])
            self.assertIsNotNone(s["vol_20"])
            self.assertIsNotNone(s["max_dd_60"])
            self.assertIsNotNone(s["sharpe_20"])
            self.assertGreaterEqual(s["score"], -100)
            self.assertLessEqual(s["score"], 100)
        self.assertEqual(res["diag"]["synthetic_n"], 0)

    def test_partial_failure_marks_only_missing_items(self):
        def fake_fetch(fetch_json, symbol, **kw):
            return [] if symbol in ("GSG", "DBC") else _bars(symbol)

        import octopus_quant.providers as providers
        original = providers.fetch_bars
        providers.fetch_bars = fake_fetch
        try:
            res = sq.run_strategy_quant(lambda *a, **k: {}, date_str="20261021")
        finally:
            providers.fetch_bars = original
        self.assertTrue(res["available"])
        self.assertEqual(set(res["missing"]), {"主观CTA", "量化CTA"})
        self.assertNotIn("CTA策略", res["by_major"])       # 该大类无可用细分 → 整类不出现
        self.assertIn("权益多头", res["by_major"])
        self.assertEqual(res["diag"]["bars_source"]["主观CTA"], "暂缺")

    def test_fallback_symbol_used_when_primary_fails(self):
        def fake_fetch(fetch_json, symbol, **kw):
            # 511010.SS（国债ETF）取不到 → 应回退 BND
            return [] if symbol == "511010.SS" else _bars(symbol)

        import octopus_quant.providers as providers
        original = providers.fetch_bars
        providers.fetch_bars = fake_fetch
        try:
            res = sq.run_strategy_quant(lambda *a, **k: {}, date_str="20261021")
        finally:
            providers.fetch_bars = original
        bond = next(s for s in res["strategies"] if s["label"] == "纯债基金")
        self.assertEqual(bond["source"], "备用基准 BND")

    def test_signal_thresholds_and_labels(self):
        self.assertEqual(sq._signal_label(30), "▲ 偏多")
        self.assertEqual(sq._signal_label(-30), "▼ 偏空")
        self.assertEqual(sq._signal_label(10), "▲ 微多")
        self.assertEqual(sq._signal_label(-10), "▼ 微空")
        self.assertEqual(sq._signal_label(0), "■ 中性")
        self.assertEqual(sq._signal_label(None), "—")

    def test_signal_score_is_bounded_and_direction_aware(self):
        self.assertGreater(sq._signal_score(10, 30, None, "多头排列"), 0)
        self.assertLess(sq._signal_score(-10, -30, None, "空头排列"), 0)
        self.assertLessEqual(abs(sq._signal_score(99, 99, None, "多头排列")), 100)

    def test_max_drawdown_and_trend_math(self):
        self.assertAlmostEqual(sq._max_drawdown([100, 120, 60, 80]), -50.0, places=6)
        self.assertEqual(sq._max_drawdown([100, 110, 120]), 0.0)
        self.assertEqual(sq._trend_label(120, 110, 100), "多头排列")
        self.assertEqual(sq._trend_label(80, 90, 100), "空头排列")
        self.assertEqual(sq._trend_label(105, 100, 110), "偏多震荡")
        self.assertEqual(sq._trend_label(95, 100, 90), "偏空震荡")
        self.assertEqual(sq._trend_label(None, None, None), "数据不足")

    def test_major_trend_is_divergence_when_subs_disagree(self):
        def fake_fetch(fetch_json, symbol, **kw):
            # 沪深300 上涨、中证500 下跌 → 权益多头「分化」
            if symbol == "000300.SS":
                return _bars(symbol, drift=0.004)
            if symbol == "000905.SS":
                return _bars(symbol, drift=-0.004)
            return _bars(symbol)

        import octopus_quant.providers as providers
        original = providers.fetch_bars
        providers.fetch_bars = fake_fetch
        try:
            res = sq.run_strategy_quant(lambda *a, **k: {}, date_str="20261021")
        finally:
            providers.fetch_bars = original
        self.assertEqual(res["by_major"]["权益多头"]["trend"], "分化")


class StrategyQuantReportTests(unittest.TestCase):
    """渲染层：5 个栏目、五种主题、暂缺披露、版面顺序与审计口径。"""

    TITLES = (
        pipeline.SECTION_TITLE_STRATEGY_OVERVIEW,
        pipeline.SECTION_TITLE_STRATEGY_EQUITY,
        pipeline.SECTION_TITLE_STRATEGY_BOND,
        pipeline.SECTION_TITLE_STRATEGY_CTA,
        pipeline.SECTION_TITLE_STRATEGY_ARBITRAGE,
    )

    def _demo_source(self):
        res = sq.run_strategy_quant(None, date_str="20261021", allow_synthetic=True)
        return pipeline._source_result(pipeline.STRATEGY_QUANT_SOURCE, "success",
                                       result=res, content_date=res["as_of"],
                                       is_today=False, snapshot=True)

    def _data(self, source="__demo__"):
        data = {
            "实时行情": pipeline._source_result(
                "Yahoo Finance Chart", "success", is_today=True,
                content_date="2026-10-21",
                quotes={"上证指数": {"price": 3800.0, "change_pct": 0.5,
                                     "as_of": "2026-10-21"}}),
            "A股大盘全景": pipeline._source_result(
                "东方财富·A股全景", "unavailable", indices=[], error="offline"),
        }
        if source == "__demo__":
            src = self._demo_source()
        else:
            src = source

        if src is not None:
            data[pipeline.STRATEGY_QUANT_SOURCE] = src
        return data

    def test_five_sections_render_in_every_theme(self):
        data = self._data()
        for theme in ("lime", "guizang", "pixel", "dossier", "forum"):
            with self.subTest(theme=theme):
                html = pipeline.generate_report(data, "2026年10月21日 · 周三", "20261021",
                                                theme=theme)
                for title in self.TITLES:
                    self.assertIn(title, html, f"{theme} 缺少 {title}")
                # 图中 6 个细分名称都要出现在页面上（分类表 + 明细表）
                for sub in ("主观多头", "量化多头", "纯债基金", "主观CTA", "量化CTA", "综合指数"):
                    self.assertIn(sub, html, f"{theme} 缺少细分 {sub}")
                # 合成序列必须显式点名，绝不冒充真实行情
                self.assertIn("演示序列", html, f"{theme} 未披露合成序列")

    def test_section_order_is_after_industry_rotation_before_summary(self):
        kickers = [s[0] for s in pipeline._collect_report_parts(
            self._data(), pipeline.PIXEL_KIT, date_str="20261021")["sections"]]
        for kick in ("STRATEGY OVERVIEW", "STRATEGY EQUITY", "STRATEGY BOND",
                     "STRATEGY CTA", "STRATEGY ARBITRAGE"):
            self.assertIn(kick, kickers)
        order = [k for k in kickers if k in pipeline.REPORT_STRATEGY_SECTIONS]
        self.assertEqual(order, ["STRATEGY OVERVIEW", "STRATEGY EQUITY", "STRATEGY BOND",
                                 "STRATEGY CTA", "STRATEGY ARBITRAGE"])
        self.assertLess(kickers.index("STRATEGY OVERVIEW"), kickers.index("SUMMARY"))
        # 栏目顺序表本身也要登记（不依赖夹具里有哪些栏）
        seq = pipeline.REPORT_SECTION_ORDER
        self.assertLess(seq.index("INDUSTRY ROTATION"), seq.index("STRATEGY OVERVIEW"))
        self.assertLess(seq.index("STRATEGY ARBITRAGE"), seq.index("SUMMARY"))

    def test_absent_and_named_in_coverage_when_bars_unavailable(self):
        src = pipeline._source_result(pipeline.STRATEGY_QUANT_SOURCE, "unavailable",
                                      result=None, error="6 个细分策略的基准指数日线均未取得")
        html = pipeline.generate_report(self._data(source=src),
                                        "2026年10月21日 · 周三", "20261021")
        for title in self.TITLES:
            self.assertNotIn(title, html, "无数据时不得出现空栏目")
        self.assertIn("暂缺", html)
        self.assertIn(pipeline.STRATEGY_QUANT_SOURCE, html)      # 数据覆盖点名

    def test_audit_counts_new_source_once(self):
        base = pipeline._report_meta(pipeline.generate_report(
            self._data(source=None), "2026年10月21日 · 周三", "20261021"))  # 无本栏数据源键
        with_sq = pipeline._report_meta(pipeline.generate_report(
            self._data(), "2026年10月21日 · 周三", "20261021"))
        self.assertEqual(with_sq["total_sources"], base["total_sources"] + 1)
        # 内部衍生（上一收盘回看）不计入当天源
        self.assertEqual(with_sq["today_sources"], base["today_sources"])

    def test_synthetic_flag_absent_for_real_bars(self):
        def fake_fetch(fetch_json, symbol, **kw):
            return _bars(symbol)

        import octopus_quant.providers as providers
        original = providers.fetch_bars
        providers.fetch_bars = fake_fetch
        try:
            res = sq.run_strategy_quant(lambda *a, **k: {}, date_str="20261021")
        finally:
            providers.fetch_bars = original
        src = pipeline._source_result(pipeline.STRATEGY_QUANT_SOURCE, "success",
                                      result=res, content_date=res["as_of"])
        html = pipeline.generate_report(self._data(source=src),
                                        "2026年10月21日 · 周三", "20261021")
        self.assertNotIn("演示序列", html)
        for title in self.TITLES:
            self.assertIn(title, html)

    def test_fetch_wrapper_respects_switch_and_demo_flag(self):
        with patch.object(pipeline, "STRATEGY_QUANT_ENABLED", False):
            self.assertIsNone(pipeline.fetch_strategy_quant())
        with patch.object(pipeline, "safe_request", return_value=None), \
             patch.object(pipeline, "STRATEGY_QUANT_DEMO", False):
            src = pipeline.fetch_strategy_quant(date_str="20261021")
        self.assertEqual(src["status"], "unavailable")
        self.assertIn("基准指数日线均未取得", src["error"])
        with patch.object(pipeline, "safe_request", return_value=None), \
             patch.object(pipeline, "STRATEGY_QUANT_DEMO", True):
            src = pipeline.fetch_strategy_quant(date_str="20261021")
        self.assertEqual(src["status"], "success")
        self.assertTrue(src["result"]["synthetic"])
        self.assertFalse(src["is_today"])          # 内部衍生不打开当天检验

    def test_push_split_keeps_every_strategy_section(self):
        html = pipeline.generate_report(self._data(), "2026年10月21日 · 周三", "20261021")
        parts = pipeline._split_html_for_push(html, 20000)
        self.assertIsNotNone(parts)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part), 20000)
        for title in self.TITLES:
            self.assertGreaterEqual(
                sum(1 for p in parts if f">{title}</h2>" in p), 1,
                f"分条后 {title} 丢失")


if __name__ == "__main__":
    unittest.main()
