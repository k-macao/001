#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""☯ 今日八卦运程与利忌：确定性起卦、变卦及卷首合并栏目接入。"""
import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "output"))
import octopus_bagua as bagua  # noqa: E402


class TestBagua(unittest.TestCase):
    def test_today_20261014_known_hexagram(self):
        r = bagua.daily_bagua(date(2026, 10, 14))
        self.assertEqual(r["weekday"], "周三")
        self.assertEqual((r["upper"]["name"], r["lower"]["name"]), ("艮", "离"))
        self.assertEqual(r["hexagram"], "山火贲")
        self.assertEqual(r["moving_line"], 2)
        self.assertEqual(r["changed_hexagram"], "山天大畜")
        self.assertEqual(r["lucky_direction"], "西北")  # 变卦下卦乾·西北
        self.assertIn("追涨杀跌", "、".join(r["unfavorable"]))

    def test_deterministic_and_moving_line_flips_one(self):
        a, b = bagua.daily_bagua(date(2026, 10, 14)), bagua.daily_bagua(date(2026, 10, 14))
        self.assertEqual(a, b)
        diff = [i for i, (x, y) in enumerate(zip(a["lines"], a["changed_lines"])) if x != y]
        self.assertEqual(diff, [a["moving_line"] - 1])

    def test_full_year_all_valid(self):
        self.assertEqual(len(bagua.HEXAGRAM_NAMES), 64)
        d = date(2026, 1, 1)
        for i in range(365):
            r = bagua.daily_bagua(d + timedelta(days=i))
            self.assertIn(r["hexagram"], bagua.HEXAGRAM_NAMES.values())
            self.assertTrue(all(1 <= v <= 5 for v in r["fortune"].values()))
            self.assertTrue(r["favorable"] and r["unfavorable"])

    def test_render_has_favorable_unfavorable_and_disclaimer(self):
        h = bagua.render_bagua_html(day=date(2026, 10, 14))
        for token in ("今日八卦运程与利忌", "山火贲", "山天大畜", "宜", "忌",
                      "西北", "非传统黄历", "不构成投资建议"):
            self.assertIn(token, h)
        self.assertIn("娱乐参考", bagua.render_bagua_text(day=date(2026, 10, 14)))

    def test_bad_date_type_rejected(self):
        with self.assertRaises(TypeError):
            bagua.daily_bagua("2026-10-14")

    def _import_pipeline(self):
        try:
            import pipeline
        except BaseException as e:  # 依赖缺失时 pipeline 会 sys.exit(1)；跳过，不假装通过
            self.skipTest(f"pipeline 不可导入: {e}")
        return pipeline

    @staticmethod
    def _data_with_conclusion(pipeline):
        """最小真实数据：一条实时行情就足以让「今日预判」有结论行（八卦只附在结论之后）。"""
        return {"实时行情": pipeline._source_result(
            "test quote", "success",
            quotes={"标普500": {"price": 6123.45, "change_pct": 1.25, "currency": "USD"}})}

    def test_pipeline_opening_section_contains_bagua_not_forecast(self):
        # 两种日期格式均按报告日起卦；卦象与诗选同在卷首，不混入真实市场预判。
        pipeline = self._import_pipeline()
        data = self._data_with_conclusion(pipeline)
        for date_str in ("20261014", "2026-10-14"):
            with self.subTest(date_str=date_str):
                parts = pipeline._collect_report_parts(data, pipeline.LIME_KIT,
                                                       date_str=date_str)
                self.assertEqual(parts["sections"][0][0], "FORECAST")
                self.assertNotIn("今日八卦运程与利忌", parts["sections"][0][2])
                opening = pipeline._poetry_sea_section(parts, pipeline.LIME_KIT)
                for token in ("诗与远方的海", "今日八卦运程与利忌", "山火贲", "山天大畜",
                              'aria-label="算卦"', "☯", "娱乐参考"):
                    self.assertIn(token, opening)
                self.assertEqual(opening.count(pipeline.SECTION_BODY_MARK), 1)

    def test_pipeline_full_render_all_themes_contain_one_combined_opening(self):
        # 真渲染（含各主题的后处理）：卦象只在新栏目，预判仍是第一个编号的市场栏。
        pipeline = self._import_pipeline()
        data = self._data_with_conclusion(pipeline)
        for theme in pipeline.PUSH_THEMES:
            with self.subTest(theme=theme):
                html = pipeline.generate_report(data, "2026年10月14日 · 周三", "20261014",
                                                theme=theme)
                self.assertEqual(html.count(pipeline.SECTION_TITLE_POETRY_SEA), 1)
                self.assertEqual(html.count("今日八卦运程与利忌"), 1)
                self.assertIn('aria-label="算卦"', html)
                self.assertIn("山火贲", html)
                self.assertIn("山天大畜", html)
                self.assertLess(html.index(pipeline.SECTION_TITLE_POETRY_SEA),
                                html.index("今日八卦运程与利忌"))
                self.assertLess(html.index("今日八卦运程与利忌"),
                                html.index(pipeline.SECTION_TITLE_FORECAST))
                self.assertNotIn("今日八卦运程与利忌",
                                 html.split(pipeline.SECTION_TITLE_FORECAST, 1)[1])

    def test_pipeline_bagua_is_independent_of_market_forecast(self):
        # 没有行情 / 量化 / 政策结论时，卷首仍展示日期卦象，不能凭娱乐内容撑出预判栏。
        pipeline = self._import_pipeline()
        parts = pipeline._collect_report_parts({}, pipeline.LIME_KIT, date_str="20261014")
        kicks = [s[0] for s in parts["sections"]]
        self.assertNotIn("FORECAST", kicks)
        self.assertNotIn("今日八卦运程与利忌", "".join(s[2] for s in parts["sections"]))
        self.assertIn("山火贲", parts["bagua_html"])
        opening = pipeline._poetry_sea_section(parts, pipeline.LIME_KIT)
        self.assertIn("诗与远方的海", opening)
        self.assertIn("今日八卦运程与利忌", opening)

    def test_render_uses_only_grayscale_colors(self):
        # 子栏要能嵌进任何主题：归藏主题禁止克莱因蓝以外的有色值，所以这里只许灰阶
        import re
        h = bagua.render_bagua_html(day=date(2026, 10, 14))
        for color in re.findall(r"#[0-9A-Fa-f]{6}\b", h):
            r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
            self.assertTrue(r == g == b, f"八卦子栏不得带有色值：{color}")
        for color in re.findall(r"#[0-9A-Fa-f]{3}\b", h):
            self.assertEqual(len(set(color[1:])), 1, f"八卦子栏不得带有色值：{color}")

    def test_pipeline_bagua_report_day_accepts_both_formats(self):
        pipeline = self._import_pipeline()
        self.assertEqual(pipeline._bagua_report_day("20261014"), date(2026, 10, 14))
        self.assertEqual(pipeline._bagua_report_day("2026-10-14"), date(2026, 10, 14))
        self.assertEqual(pipeline._bagua_report_day("2026-10-14 15:09:16"), date(2026, 10, 14))
        # 非法 / 缺省：回退到北京时间当天，而不是让子栏缺席
        self.assertIsInstance(pipeline._bagua_report_day(None), date)
        self.assertIsInstance(pipeline._bagua_report_day("garbage"), date)

    def test_bagua_can_be_disabled_without_hiding_poem(self):
        pipeline = self._import_pipeline()
        data = {pipeline.SHIQUAN_META_KEY: {
            "title": "江雪", "content": ["千山鸟飞绝，万径人踪灭。"],
            "author": {"name": "柳宗元"}, "dynasty": {"name": "唐"},
        }}
        with patch.object(bagua, "ENABLED", False):
            html = pipeline.generate_report(data, "2026年10月14日", "20261014", theme="lime")
        self.assertIn("诗与远方的海", html)
        self.assertIn("《江雪》", html)
        self.assertNotIn("今日八卦运程与利忌", html)
        self.assertNotIn('aria-label="算卦"', html)

    def test_failed_bagua_render_does_not_hide_poem_or_forecast(self):
        pipeline = self._import_pipeline()
        data = self._data_with_conclusion(pipeline)
        with patch.object(bagua, "render_bagua_html", side_effect=ValueError("bad bagua")):
            html = pipeline.generate_report(data, "2026年10月14日", "20261014", theme="lime")
        self.assertIn("诗与远方的海", html)
        self.assertIn("今日一首诗", html)
        self.assertNotIn("今日八卦运程与利忌", html)
        self.assertIn(pipeline.SECTION_TITLE_FORECAST, html)


if __name__ == "__main__":
    unittest.main()
