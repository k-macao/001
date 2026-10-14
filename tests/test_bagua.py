#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""☯ 今日八卦运程与利忌：确定性起卦、变卦、渲染与日报接入。"""
import os
import sys
import unittest
from datetime import date, timedelta

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

    def test_pipeline_forecast_section_contains_bagua(self):
        # 真渲染（非源码 grep）：今日预判必须是首栏且栏内含八卦子栏。
        # date_str 必须用流水线真实口径 YYYYMMDD（_today_str()），不能只测 ISO 格式——
        # 2026-10-14 首发版只解析 "%Y-%m-%d"，线上 "20261014" 抛错被吞，子栏整体缺席，
        # 而当时测试传的是 "2026-10-14"，所以绿灯却没上线。
        pipeline = self._import_pipeline()
        data = self._data_with_conclusion(pipeline)
        for date_str in ("20261014", "2026-10-14"):
            with self.subTest(date_str=date_str):
                parts = pipeline._collect_report_parts(data, pipeline.LIME_KIT,
                                                       date_str=date_str)
                secs = parts["sections"] if isinstance(parts, dict) else parts
                self.assertTrue(secs and secs[0][0] == "FORECAST")
                self.assertIn("今日八卦运程与利忌", secs[0][2])
                self.assertIn("山火贲", secs[0][2])
                self.assertIn("山天大畜", secs[0][2])

    def test_pipeline_full_render_all_themes_contain_today_hexagram(self):
        # 走 generate_report 全链路（含各主题的后处理），五个主题都要带今日卦象
        pipeline = self._import_pipeline()
        data = self._data_with_conclusion(pipeline)
        for theme in ("lime", "pixel", "forum", "dossier", "guizang"):
            with self.subTest(theme=theme):
                html = pipeline.generate_report(data, "2026年10月14日 · 周三", "20261014",
                                                theme=theme)
                self.assertIn("今日八卦运程与利忌", html)
                self.assertIn("山火贲", html)
                self.assertIn("山天大畜", html)

    def test_pipeline_bagua_does_not_fabricate_forecast_without_conclusion(self):
        # 没有任何行情 / 量化 / 政策结论时，不能靠娱乐子栏单独撑出一个「今日预判」栏
        pipeline = self._import_pipeline()
        parts = pipeline._collect_report_parts({}, pipeline.LIME_KIT, date_str="20261014")
        kicks = [s[0] for s in parts["sections"]]
        self.assertNotIn("FORECAST", kicks)
        self.assertNotIn("今日八卦运程与利忌",
                         "".join(s[2] for s in parts["sections"]))

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

    def test_pipeline_wires_bagua_into_forecast(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        src = open(os.path.join(root, "output", "pipeline.py"), encoding="utf-8").read()
        self.assertIn("import octopus_bagua as _bagua", src)
        self.assertIn("render_bagua_html", src)


if __name__ == "__main__":
    unittest.main()
