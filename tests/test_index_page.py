"""全页指数口径：离线、单源优先+备用源待命、无预测概率/旧资产代理泄漏、五主题一致。"""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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


class FullPageTests(unittest.TestCase):
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

    def test_legacy_rollback_switch(self):
        with patch.dict("os.environ", {"OCTOPUS_INDEX_PAGE": "0"}):
            parts = pipeline._collect_report_parts(self.data([]), pipeline.GUIZANG_KIT, date_str="20261021")
        self.assertNotIn("三地指数", parts["sections"][0][1])


if __name__ == "__main__":
    unittest.main()
