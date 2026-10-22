"""三地指数全页（默认关闭 · 2026-10-23 回滚为纯港股日报）：

本文件同时守两件事：
  1) 默认（不设 OCTOPUS_INDEX_PAGE）必须回到原港股日报，不采集、不渲染任何三地指数；
  2) 显式 OCTOPUS_INDEX_PAGE=1 时，保留的指数全页仍然口径正确（离线、单源优先+备用源
     待命、无预测概率/旧资产代理泄漏、五主题一致），便于一键恢复。
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "output"))
import index_crosscheck as ic
import index_page

spec = importlib.util.spec_from_file_location("pipeline_index_page_test", ROOT / "output/pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def rows():
    result = []
    for m, n, symbol, secid in ic.SPECS:
        r = dict(
            market=m, name=n, symbol=symbol, secid=secid,
            as_of="2026-10-20", date="2026-10-20", close=160.0,
            source="Yahoo Chart 主源（query1）", source_role="主源",
            is_backup=False, status="正常", usable=True,
        )
        r.update(ic.metrics([{"close": float(i), "date": str(i)} for i in range(100, 161)]))
        result.append(r)
    return result


class MetricsTests(unittest.TestCase):
    def test_full_windows(self):
        r = ic.metrics([{"close": float(i)} for i in range(100, 161)])
        self.assertAlmostEqual(r["ret_20d"], (160 / 140 - 1) * 100)
        self.assertAlmostEqual(r["ma20"], 150.5)
        self.assertEqual(r["max_dd_60"], 0)
        self.assertEqual(r["win_20"], 100)
        self.assertEqual(r["trend"], "多头排列")

    def test_short_history_does_not_invent_risk(self):
        r = ic.metrics([{"close": 100.0}, {"close": 99.0}])
        for k in ("ret_20d", "ret_60d", "vol_20", "win_20", "ma60", "max_dd_60"):
            self.assertIsNone(r[k])
        self.assertEqual(r["trend"], "样本不足")

    def test_drawdown(self):
        r = ic.metrics([{"close": 100.0}] * 59 + [{"close": 80.0}])
        self.assertAlmostEqual(r["max_dd_60"], -20)

    def test_ranking_never_mixes_markets_or_dates(self):
        rs = rows()
        rs[1]["as_of"] = "2026-10-19"
        rs[2]["usable"] = False
        ranks = index_page.relative_rows(rs)
        self.assertNotIn("港股", str(ranks))
        self.assertEqual(len(ranks), 6)


class RollbackDefaultTests(unittest.TestCase):
    """默认关闭：页面回到纯港股日报，三地指数既不采集也不显示。"""

    def data(self, rs):
        return {
            pipeline.STRATEGY_QUANT_SOURCE: {"status": "success", "result": {"index_checks": rs}},
            "港股量化": {"status": "success", "result": {"available": True, "leak": "OLD_HK_SIGNAL"}},
            "实时行情": {"status": "success", "leak": "OLD_STOCK_SIGNAL"},
        }

    def test_flag_defaults_to_off(self):
        with patch.dict(os.environ, {}):
            os.environ.pop("OCTOPUS_INDEX_PAGE", None)
            self.assertFalse(pipeline._index_page_enabled())
            import strategy_quant as sq
            self.assertFalse(sq.index_page_enabled())

    def test_flag_is_opt_in_only(self):
        for value in ("0", "false", "no", "off", "", "2"):
            with self.subTest(value=value), patch.dict(os.environ, {"OCTOPUS_INDEX_PAGE": value}):
                self.assertFalse(pipeline._index_page_enabled())
        for value in ("1", "true", "yes", "on", " 1 "):
            with self.subTest(value=value), patch.dict(os.environ, {"OCTOPUS_INDEX_PAGE": value}):
                self.assertTrue(pipeline._index_page_enabled())

    def test_default_page_is_hk_only(self):
        # 即使快照里残留 index_checks 契约（历史采集），默认也不得接管页面。
        with patch.dict(os.environ, {"OCTOPUS_INDEX_PAGE": "0"}):
            parts = pipeline._collect_report_parts(self.data(rows()), pipeline.GUIZANG_KIT, date_str="20261021")
        titles = "".join(s[1] for s in parts["sections"])
        html = titles + "".join(s[2] for s in parts["sections"])
        for text in ("三地指数", "沪深300", "上证指数", "标普500", "纳斯达克综合", "道琼斯工业"):
            self.assertNotIn(text, html)
        self.assertNotIn("恒生科技", html)
        self.assertNotIn("分析标的仅限A股", html)
        self.assertNotIn("分析范围", html)
        # 旧港股日报口径回来了：栏目仍按原港股源清单做数据覆盖点名，源数不再是指数全页的 1。
        self.assertIn("港股名家频道", html)
        self.assertGreater(parts["total"], 1)

    def test_default_overview_hides_index_table(self):
        import strategy_quant as sq
        res = {"available": True, "index_checks": rows(), "strategies": [], "by_major": {}, "overview": {}}
        with patch.dict(os.environ, {"OCTOPUS_INDEX_PAGE": "0"}):
            self.assertEqual(sq.render_overview(res, pipeline.GUIZANG_KIT), "")
        with patch.dict(os.environ, {"OCTOPUS_INDEX_PAGE": "1"}):
            self.assertIn("沪深300", sq.render_overview(res, pipeline.GUIZANG_KIT))

    def test_default_run_does_not_collect_indices(self):
        collector = MagicMock(side_effect=AssertionError("默认不应采集三地指数"))
        quant = MagicMock()
        quant.run_strategy_quant.return_value = {
            "available": True, "strategies": [{"label": "主观多头"}], "by_major": [],
            "as_of": "2026-10-20", "diag": {},
        }
        with patch.dict(os.environ, {"OCTOPUS_INDEX_PAGE": "0"}), \
                patch.dict(sys.modules, {"index_crosscheck": MagicMock(collect=collector)}), \
                patch.object(pipeline, "_strategy_quant", quant), \
                patch.object(pipeline, "STRATEGY_QUANT_ENABLED", True):
            src = pipeline.fetch_strategy_quant("20261021")
        collector.assert_not_called()
        self.assertEqual(src["status"], "success")
        self.assertNotIn("index_checks", src["result"])

    def test_enabled_run_still_collects_indices(self):
        collector = MagicMock(return_value=rows())
        quant = MagicMock()
        quant.run_strategy_quant.return_value = {
            "available": True, "strategies": [{"label": "主观多头"}], "by_major": [],
            "as_of": "2026-10-20", "diag": {},
        }
        with patch.dict(os.environ, {"OCTOPUS_INDEX_PAGE": "1"}), \
                patch.dict(sys.modules, {"index_crosscheck": MagicMock(collect=collector)}), \
                patch.object(pipeline, "_strategy_quant", quant), \
                patch.object(pipeline, "STRATEGY_QUANT_ENABLED", True):
            src = pipeline.fetch_strategy_quant("20261021")
        collector.assert_called_once()
        self.assertEqual(len(src["result"]["index_checks"]), len(ic.SPECS))


class FullPageTests(unittest.TestCase):
    """显式开启（OCTOPUS_INDEX_PAGE=1）后，保留的指数全页口径不变。"""

    def setUp(self):
        env = patch.dict(os.environ, {"OCTOPUS_INDEX_PAGE": "1"})
        env.start()
        self.addCleanup(env.stop)

    def data(self, rs):
        return {
            pipeline.STRATEGY_QUANT_SOURCE: {"status": "success", "result": {"index_checks": rs}},
            "港股量化": {"status": "success", "result": {"available": True, "leak": "OLD_HK_SIGNAL"}},
            "实时行情": {"status": "success", "leak": "OLD_STOCK_SIGNAL"},
        }

    def test_order_and_missing_evidence(self):
        parts = pipeline._collect_report_parts(self.data(rows()), pipeline.GUIZANG_KIT, date_str="20261021")
        self.assertEqual([s[0] for s in parts["sections"]], list(pipeline.REPORT_SECTION_ORDER))
        html = "".join(s[2] for s in parts["sections"])
        self.assertIn("证据不足", html)
        self.assertNotIn("OLD_HK_SIGNAL", html)
        self.assertNotIn("OLD_STOCK_SIGNAL", html)
        self.assertNotIn("多头概率", html)
        self.assertEqual(parts["today_n"], 0)

    def test_no_data_still_keeps_all_indices_and_columns(self):
        data = self.data([])
        data[pipeline.STRATEGY_QUANT_SOURCE]["status"] = "unavailable"
        parts = pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT, date_str="20261021")
        self.assertEqual(len(parts["sections"]), len(pipeline.REPORT_SECTION_ORDER))
        html = "".join(s[2] for s in parts["sections"])
        for _, name, _, _ in ic.SPECS:
            self.assertIn(name, html)
        self.assertIn("暂缺", html)
        self.assertNotIn("511010", html)

    def test_backup_source_disclosed_when_triggered(self):
        rs = rows()
        rs[4]["is_backup"] = True
        rs[4]["status"] = "备用源启用"
        rs[4]["source_label"] = "备用源2 · 东方财富"
        parts = index_page.build_parts(rs, pipeline.GUIZANG_KIT, pipeline.REPORT_SECTION_ORDER, date_str="20261021")
        html = "".join(s[2] for s in parts["sections"])
        self.assertIn("备用源启用 1 个", html)
        self.assertIn("备用源2 · 东方财富", html)

    def test_all_themes_use_index_scope(self):
        for theme in ("lime", "pixel", "forum", "dossier", "guizang"):
            with self.subTest(theme=theme):
                html = pipeline.generate_report(self.data(rows()), "2026年10月21日", "20261021", theme=theme)
                for text in ("三地指数", "沪深300", "恒生指数", "标普500"):
                    self.assertIn(text, html)
                for text in ("OLD_HK_SIGNAL", "OLD_STOCK_SIGNAL", "GSG", "BND", "私募综合 / 上证指数代理"):
                    self.assertNotIn(text, html)
                self.assertIn(pipeline.SECTION_BODY_MARK, html)

    def test_unusable_index_has_no_signal(self):
        rs = rows()
        rs[0]["usable"] = False
        rs[0]["trend"] = "SHOULD_NOT_RENDER"
        parts = index_page.build_parts(rs, pipeline.GUIZANG_KIT, pipeline.REPORT_SECTION_ORDER)
        self.assertNotIn("SHOULD_NOT_RENDER", "".join(s[2] for s in parts["sections"]))

    def test_plain_mode_keeps_material_disclosures(self):
        with patch.object(pipeline, "PLAIN", return_value=True):
            parts = pipeline._collect_report_parts(self.data(rows()), pipeline.GUIZANG_KIT, date_str="20261021")
        html = "".join(s[2] for s in parts["sections"])
        self.assertIn("缺少按指数归因的新闻样本", html)
        self.assertIn("行情供应商数据不等于交易所官方认证", html)
        self.assertIn("不是未来概率", html)

    def test_split_push_preserves_all_sections(self):
        html = pipeline.generate_report(self.data(rows()), "2026年10月21日", "20261021", theme="guizang")
        chunks = pipeline._split_html_for_push(html, 20000)
        self.assertIsNotNone(chunks)
        for title in index_page.TITLES.values():
            self.assertTrue(any(title in chunk for chunk in chunks), title)

    def test_switch_turns_index_page_back_on(self):
        # 回滚后仍可一键恢复：同一份快照，开关决定走指数全页还是旧港股页。
        data = self.data(rows())
        with patch.dict(os.environ, {"OCTOPUS_INDEX_PAGE": "0"}):
            off = pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT, date_str="20261021")
        on = pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT, date_str="20261021")
        self.assertNotIn("三地指数", off["sections"][0][1])
        self.assertIn("三地指数", on["sections"][0][1])
        self.assertEqual(on["today_n"], 0)


if __name__ == "__main__":
    unittest.main()
