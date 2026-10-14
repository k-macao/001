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

    def test_pipeline_forecast_section_contains_bagua(self):
        # 真渲染（非源码 grep）：今日预判必须是首栏且栏内含八卦子栏
        try:
            import pipeline
        except Exception as e:  # 依赖缺失的环境跳过，不假装通过
            self.skipTest(f"pipeline 不可导入: {e}")
        parts = pipeline._collect_report_parts({}, pipeline.LIME_KIT,
                                               date_str="2026-10-14")
        secs = parts["sections"] if isinstance(parts, dict) else parts
        self.assertTrue(secs and secs[0][0] == "FORECAST")
        self.assertIn("今日八卦运程与利忌", secs[0][2])
        self.assertIn("山火贲", secs[0][2])

    def test_pipeline_wires_bagua_into_forecast(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        src = open(os.path.join(root, "output", "pipeline.py"), encoding="utf-8").read()
        self.assertIn("import octopus_bagua as _bagua", src)
        self.assertIn("render_bagua_html", src)


if __name__ == "__main__":
    unittest.main()
