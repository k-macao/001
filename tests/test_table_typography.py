"""表格排版口径（2026-10-23 用户要求）：表格内文字**缩小一号**且**一律不加粗**。

覆盖三层：
  1) 字号阶梯常量（归藏系 GZ_FS_TABLE 13→12；pixel 终端各档同步收一号）；
  2) 各表格渲染器的内联样式（微信 / PushPlus 会清洗 <style> 块，只能写内联）；
  3) 整页回归：五套主题的数据表里不再出现 <b>/<strong> 与 600~900 字重，
     而刊头、栏目标题、徽标、八卦卡等**版面装饰**保持原字号阶梯不受影响。
"""
import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "output"))

spec = importlib.util.spec_from_file_location("pipeline_table_typo", ROOT / "output/pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

import shiquan_poem as _shiquan  # noqa: E402
import strategy_quant as _sq  # noqa: E402

BOLD_RE = re.compile(r"<b[\s>]|<strong[\s>]|font-weight:\s*(?:600|700|800|900|bold|bolder)")
# 数据表签名：表级同时写了表格字号与常规字重（版面装饰表不带这组样式）。
DATA_TABLE_RE = re.compile(
    r'<table[^>]*style="[^"]*font-size:12px;font-weight:400[^"]*"[^>]*>(.*?)</table>', re.S)


def sample_data():
    return {
        "实时行情": pipeline._source_result(
            "Yahoo Finance", "success", is_today=True, content_date="2026-10-11",
            quotes={
                "恒生指数": {"price": 21200.0, "change": 180.0, "change_pct": 0.86, "as_of": "2026-10-11"},
                "标普500": {"price": 6123.45, "change": -12.5, "change_pct": -0.2, "as_of": "2026-10-11"},
            },
        ),
        pipeline.SHIQUAN_META_KEY: {
            "id": 101, "title": "终南望余雪",
            "content": ["终南阴岭秀，积雪浮云端。", "林表明霁色，城中增暮寒。"],
            "author": {"id": 12, "name": "祖咏"},
            "dynasty": {"id": 6, "name": "唐", "name_en": "Tang"},
            "type": {"id": 4, "name": "五言绝句", "category": "唐诗"},
        },
    }


class LadderTests(unittest.TestCase):
    def test_gz_table_step_dropped_one_and_stays_above_floor(self):
        self.assertEqual(pipeline.GZ_FS_TABLE, 12)          # 原 13 → 缩小一号
        self.assertEqual(pipeline.GZ_W_TABLE, 400)          # 表格内文字不加粗
        self.assertGreater(pipeline.GZ_FS_TABLE, pipeline.GZ_FS_FLOOR)
        self.assertLess(pipeline.GZ_FS_TABLE, pipeline.GZ_FS_BODY)

    def test_other_ladder_steps_untouched(self):
        # 刊头 / 栏目 / 关键数字 / 正文 / 次要文字不属于「表格内文字」，保持原阶梯。
        self.assertEqual(pipeline.GZ_FS_DISPLAY, 26)
        self.assertEqual(pipeline.GZ_FS_SECTION, 18)
        self.assertEqual(pipeline.GZ_FS_PRICE, 20)
        self.assertEqual(pipeline.GZ_FS_BODY, 14)
        self.assertEqual(pipeline.GZ_FS_META, 12)

    def test_pixel_table_ladder_dropped_one_each(self):
        self.assertEqual(pipeline.PIXEL_FS_GRID, 10)        # 数据表表身 11 → 10
        self.assertEqual(pipeline.PIXEL_FS_GRID_HEAD, 9)    # 数据表表头 10 → 9
        self.assertEqual(pipeline.PIXEL_FS_LEDGER, 11)      # 账本双列 12 → 11
        self.assertEqual(pipeline.PIXEL_FS_LEDGER_NUM, 12)  # 表内关键数值 13 → 12
        self.assertEqual(pipeline.PIXEL_FS_ITEM, 11)        # 资讯行 12 → 11
        self.assertEqual(pipeline.PIXEL_FS_ITEM_ICON, 10)   # 资讯行序号 11 → 10


class DeboldHelperTests(unittest.TestCase):
    def test_b_and_strong_become_span_keeping_other_styles(self):
        out = pipeline._table_text('<b style="color:#002FA7">21,200</b>')
        self.assertEqual(out, '<span style="color:#002FA7">21,200</span>')
        self.assertEqual(pipeline._table_text("<strong>x</strong>"), "<span>x</span>")

    def test_inline_bold_weights_rewritten_to_400(self):
        for weight in ("600", "700", "800", "900", "bold", "bolder"):
            with self.subTest(weight=weight):
                out = pipeline._table_text(f'<span style="font-weight:{weight};color:#333">▲ 涨</span>')
                self.assertIn("font-weight:400", out)
                self.assertIn("color:#333", out)

    def test_regular_weight_and_other_markup_untouched(self):
        self.assertEqual(pipeline._table_text('<span style="font-weight:400">x</span>'),
                         '<span style="font-weight:400">x</span>')
        # <br> / <span> 不能被误改成 <spanr> 之类；纯文本原样返回。
        self.assertEqual(pipeline._table_text("a<br>b"), "a<br>b")
        self.assertEqual(pipeline._table_text("恒生指数"), "恒生指数")
        self.assertEqual(pipeline._table_text(""), "")
        self.assertIsNone(pipeline._table_text(None))

    def test_strategy_quant_fallback_helper_matches(self):
        self.assertEqual(_sq._plain_cell('<b style="color:#123">v</b>'),
                         '<span style="color:#123">v</span>')
        self.assertIn("font-weight:400", _sq._plain_cell('<i style="font-weight:900">v</i>'))


class GzTableRendererTests(unittest.TestCase):
    """归藏系（lime / guizang / dossier / forum 共用）数据表与 KV 表。"""

    def test_data_table_uses_12px_and_regular_weight(self):
        html = pipeline.gz_data_table(
            ["指数", "最新价", "涨跌"],
            [["<b>恒生指数</b>", pipeline._gz_num("21,200"), pipeline.gz_trend_badge(0.86)]])
        self.assertIn(f"font-size:{pipeline.GZ_FS_TABLE}px", html)
        self.assertIn(f"font-weight:{pipeline.GZ_W_TABLE}", html)
        self.assertNotRegex(html, BOLD_RE)
        self.assertIn("21,200", html)                 # 文字与颜色仍在，只是不再加粗
        self.assertIn(pipeline.GZ_KLEIN, html)
        self.assertIn("▲", html)

    def test_kv_table_debolds_labels_and_values(self):
        html = pipeline.gz_kv_table([("数据覆盖", '<b style="color:#002FA7">9/9 源</b>'),
                                     ("风险关注", '<span style="font-weight:700">南向资金</span>')])
        self.assertIn("font-size:12px;font-weight:400", html)
        self.assertNotRegex(html, BOLD_RE)
        self.assertIn("9/9 源", html)

    def test_news_card_table_debolded(self):
        html = pipeline._gz_news_card("01", "<b>港股早盘走高</b>", sub="<b>10:00</b>")
        self.assertIn(f"font-size:{pipeline.GZ_FS_TABLE}px", html)
        self.assertIn(f"font-weight:{pipeline.GZ_W_TABLE}", html)
        self.assertNotRegex(html, BOLD_RE)
        self.assertIn("港股早盘走高", html)

    def test_section_row_content_wrapper_follows_table_rules(self):
        html = pipeline.gz_section("01", "MARKET REVIEW", "行情复盘",
                                   '<tr><td><b>恒指</b></td><td>21,200</td></tr>')
        self.assertIn("font-size:12px;font-weight:400", html)
        self.assertNotIn("<b>恒指</b>", html)
        self.assertIn("<span>恒指</span>", html)

    def test_ai_conclusion_table_one_size_smaller_and_not_bold(self):
        html = pipeline._ren_judgment_row("恒指偏多，证据为南向资金与均线排列。", pipeline.LIME_KIT,
                                          meta={"label": "偏多", "p_pct": 62})
        self.assertIn("本栏结论", html)
        self.assertIn(f"font-weight:{pipeline.GZ_W_TABLE}", html)
        self.assertNotRegex(html, BOLD_RE)
        self.assertIn("font-size:16px", html)     # 上涨概率大数字 17 → 16
        self.assertIn("font-size:11px", html)     # 结论文字 12 → 11
        self.assertNotIn("font-size:17px", html)
        self.assertNotIn("font-size:13px", html)


class PixelTableRendererTests(unittest.TestCase):
    def test_grid_table_head_and_body_dropped_one(self):
        html = pipeline._pixel_table(["指数", "最新价"], [["<b>恒指</b>", "21,200"]])
        self.assertIn(f"font-size:{pipeline.PIXEL_FS_GRID_HEAD}px;font-weight:400", html)
        self.assertIn(f"font-size:{pipeline.PIXEL_FS_GRID}px", html)
        self.assertNotRegex(html, BOLD_RE)
        self.assertIn("<span>恒指</span>", html)

    def test_ledger_table_dropped_one_and_value_not_bold(self):
        html = pipeline._data_table([("恒生指数", "<b>21,200</b>", pipeline.C_INK)])
        self.assertEqual(html.count(f"font-size:{pipeline.PIXEL_FS_LEDGER}px"), 2)
        self.assertNotRegex(html, BOLD_RE)
        self.assertNotIn("font-size:12px", html)

    def test_item_row_dropped_one_and_not_bold(self):
        html = pipeline._item_row("[01]", "<b>港股早盘走高</b>", sub="<b>10:00</b>")
        self.assertIn(f"font-size:{pipeline.PIXEL_FS_ITEM_ICON}px;font-weight:400", html)
        self.assertIn(f"font-size:{pipeline.PIXEL_FS_ITEM}px", html)
        self.assertNotRegex(html, BOLD_RE)

    def test_quote_value_inside_ledger_follows_table_rules(self):
        market = {"quotes": {"恒生指数": {"price": 21200.0, "change_pct": 0.86}}}
        value, _color = pipeline._quote_value(market, "恒生指数")
        # 报价数值本身：13px/900 → 12px/常规字重。
        self.assertIn(f"font-size:{pipeline.PIXEL_FS_LEDGER_NUM}px", value)
        self.assertIn(f"font-weight:{pipeline.GZ_W_TABLE}", value)
        self.assertNotIn("font-size:13px", value)
        # 涨跌徽标自身仍是徽标口径，但一旦落进表格单元格就随表格去粗。
        rendered = pipeline._data_table([("恒生指数", value, pipeline.C_INK)])
        self.assertNotRegex(rendered, BOLD_RE)
        self.assertIn("▲ 涨 +0.86%", rendered)


class PoemCardTests(unittest.TestCase):
    def test_poem_card_tables_dropped_one_and_not_bold_in_every_theme(self):
        poem = sample_data()[pipeline.SHIQUAN_META_KEY]
        for theme in ("lime", "guizang", "dossier", "forum", "pixel"):
            with self.subTest(theme=theme):
                html = _shiquan_poem_html(poem, theme)
                self.assertNotRegex(html, BOLD_RE)
                self.assertIn("font-size:13px", html)     # 诗句 14 → 13
                self.assertIn("font-size:14px", html)     # 诗题 15 → 14
                self.assertIn("《终南望余雪》", html)


def _shiquan_poem_html(poem, theme):
    return _shiquan.render_opening_poem_html(poem, theme=theme)


class StrategyQuantFallbackTests(unittest.TestCase):
    def test_fallback_table_and_kv_are_11px_and_regular(self):
        table = _sq._kit_table(None, ["指数", "趋势"], [["<b>恒生指数</b>", "多头排列"]])
        self.assertIn("font-size:11px", table)
        self.assertNotRegex(table, BOLD_RE)
        self.assertIn("<span>恒生指数</span>", table)
        kv = _sq._kit_kv(None, [("数据口径", '<b style="color:#666">单源</b>')])
        self.assertIn("font-size:11px", kv)
        self.assertNotRegex(kv, BOLD_RE)


class FullPageTests(unittest.TestCase):
    """整页回归：数据表内不再有粗体；版面装饰（刊头 / 栏目标题 / 徽标）不受影响。"""

    def _html(self, theme):
        return pipeline.generate_report(sample_data(), "2026年10月11日 · 周日", "20261011", theme=theme)

    def test_gz_themes_data_tables_are_regular_weight(self):
        for theme in ("lime", "guizang", "dossier", "forum"):
            with self.subTest(theme=theme):
                html = self._html(theme)
                tables = DATA_TABLE_RE.findall(html)
                self.assertGreaterEqual(len(tables), 3, f"{theme} 未找到足够的数据表")
                for body in tables:
                    self.assertNotRegex(body, BOLD_RE)
                # _gz_num 的克莱因蓝加粗数值只用于表格，整页不应再出现。
                self.assertNotIn(f'<b style="color:{pipeline.GZ_KLEIN}">', html)

    def test_gz_themes_keep_chrome_ladder(self):
        html = self._html("lime")
        self.assertIn(f"font-size:{pipeline.GZ_FS_DISPLAY}px", html)   # 刊头 26
        self.assertIn(f"font-size:{pipeline.GZ_FS_SECTION}px", html)   # 栏目 18
        self.assertIn("font-weight:900", html)                         # 刊头/栏目标题仍加粗

    def test_pixel_theme_tables_are_regular_weight(self):
        html = self._html("pixel")
        self.assertIn(f"font-size:{pipeline.PIXEL_FS_GRID_HEAD}px;font-weight:400", html)
        self.assertIn(f"font-size:{pipeline.PIXEL_FS_LEDGER}px", html)
        self.assertIn(f"font-size:{pipeline.PIXEL_FS_LEDGER_NUM}px", html)
        self.assertNotIn(f'<b style="color:{pipeline.GZ_KLEIN}">', html)
        # 行情表里的报价数值不再加粗（原来 13px/900）。
        self.assertNotIn("font-size:13px;font-weight:900", html)

    def test_market_review_rows_show_numbers_without_bold(self):
        html = self._html("guizang")
        bodies = [b for b in DATA_TABLE_RE.findall(html) if "21,200" in b]
        self.assertTrue(bodies, "行情数据表未按表格口径渲染")
        for body in bodies:
            self.assertNotRegex(body, BOLD_RE)
            self.assertIn("恒生指数", body)
        # 关键数值仍用克莱因蓝着色，只是不再加粗（重点靠颜色与位置，不靠字重）。
        self.assertIn(f'<span style="color:{pipeline.GZ_KLEIN}">21,200', html)


if __name__ == "__main__":
    unittest.main()
