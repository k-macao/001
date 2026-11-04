#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚠️「研报 AI 风险点提示」栏目回归（2026-11-04 接入，移植自 k-macao/007）。

守五件事：
  · 位置——每个推送主题里都排在 🐣 新手三句话之后、正文（今日预判）之前，整篇只出现一处；
  · 内容——线索来自研报 / 快讯标题池，机构署名与类别可追溯，标题先转义、链接只放 http(s)；
  · 诚实——一条线索都没有时栏目照常出并写明「未检出」，绝不静默消失；
  · 取数——配了 007 端点就先取在线、不通回落到本地规则；远程条目与本地条目去重合并；
  · 边界——大模型只写定调与关注点，绝对化措辞 / 凭空数字 / 名单外机构一律退回规则文案。
"""
import json
import os
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline  # noqa: E402
import research_risk as rr  # noqa: E402
from test_short_card import pipeline_report_data  # noqa: E402


CORPUS = {"version": 1, "items": [
    # 研报体裁 + 机构署名（tier 0）
    {"title": "高盛下调韩国股指目标价，维持减持评级", "source": "研报",
     "section": "内地财经媒体", "ts": "2026-11-03 09:20", "date": "2026-11-03",
     "url": "https://example.com/a"},
    # 研报体裁无署名（tier 1）
    {"title": "BMO维持美洲白银公司买入评级 下调目标价至6.4美元", "source": "智通财经",
     "section": "港股新闻源头", "ts": "2026-11-02 10:00", "date": "2026-11-02"},
    # 个股流水账（tier 2，且应被噪音词表剔除）
    {"title": "机构席位卖出1.57万 新三板基础层公司摘牌安泽登龙虎榜", "source": "东财",
     "section": "东财快讯", "ts": "2026-11-02 11:00", "date": "2026-11-02"},
    # 纯多头标题：不是风险线索
    {"title": "瑞银上调中国互联网板块至增持，阿里腾讯为首选", "source": "研报",
     "section": "内地财经媒体", "ts": "2026-11-01 10:00", "date": "2026-11-01"},
    # 窗口外（16 天前）
    {"title": "花旗：下调某车企评级至中性", "source": "研报",
     "section": "内地财经媒体", "ts": "2026-10-19 10:00", "date": "2026-10-19"},
]}

REMOTE_PAYLOAD = {
    "ok": True, "topic": "全球市场", "hours": 168, "count": 7,
    "rule_md": (
        "## 🧭 美银牛熊指标 · BofA Bull & Bear Indicator\n"
        "- 这一行不是风险点，不该被收进栏目\n\n"
        "## ⚠️ 研报 AI 风险点提示\n\n"
        "- **[国外投行 · 摩根士丹利]** 下调半导体板块评级至中性（neutral）\n"
        "- **[国外投行 · 瑞银]** 中国互联网板块盈利预期存在下修风险\n\n"
        "## 🏛 国外研报\n- 明细条目也不该进来\n"),
}


class ResearchRiskModuleTests(unittest.TestCase):
    """数据层：词表 / 机构 / 去重排序 / 007 报文 / 大模型护栏。"""

    def test_selftest_passes(self):
        failed = [name for name, ok, _ in rr.selftest() if not ok]
        self.assertEqual(failed, [], f"自检未通过：{failed}")

    def test_local_points_exclude_noise_bull_and_out_of_window(self):
        now = rr.parse_datetime("2026-11-04 12:00")
        points = rr.collect_local(CORPUS["items"], now)
        titles = [p["title"] for p in points]
        self.assertEqual(len(points), 2, titles)
        self.assertTrue(any("高盛" in t for t in titles))
        self.assertFalse(any("龙虎榜" in t for t in titles), "流水账必须剔除")
        self.assertFalse(any("上调中国互联网" in t for t in titles), "纯多头不算风险")
        self.assertFalse(any("花旗" in t for t in titles), "15 日窗口外的标题不计入")
        signed = [p for p in points if p["institution"]]
        self.assertEqual(signed[0]["institution"], "高盛")
        self.assertTrue(signed[0]["intl"])

    def test_merge_prefers_signed_points_and_dedupes(self):
        remote = rr.parse_rule_md(REMOTE_PAYLOAD["rule_md"])
        self.assertEqual(len(remote), 2)
        local = rr.collect_local(CORPUS["items"], rr.parse_datetime("2026-11-04 12:00"))
        merged = rr.merge_points(remote, local + [dict(local[0])])   # 故意重复一条
        self.assertEqual(len(merged), {p["title"] for p in merged}.__len__())
        self.assertLessEqual(len(merged), rr.MAX_POINTS)
        self.assertTrue(merged[0]["institution"], "有署名的排最前")

    def test_build_uses_remote_first_then_local(self):
        with patch.object(rr, "fetch_remote",
                          return_value={"ok": True, "points": rr.parse_rule_md(REMOTE_PAYLOAD["rule_md"]),
                                        "url": "http://x/api/foreign_weekly", "env": "OCTOPUS_007_BASE_URL"}):
            res = rr.build(date_str="20261104", news_corpus=CORPUS)
        self.assertTrue(res["available"])
        self.assertEqual(res["summary_source"], "远程 007 + 本地规则")
        institutions = {p["institution"] for p in res["points"]}
        self.assertIn("摩根士丹利", institutions)
        self.assertIn("高盛", institutions)

    def test_build_falls_back_to_local_when_remote_fails(self):
        with patch.object(rr, "fetch_remote",
                          return_value={"ok": False, "points": [], "url": "", "reason": "连接失败"}):
            res = rr.build(date_str="20261104", news_corpus=CORPUS)
        self.assertTrue(res["available"])
        self.assertEqual(res["summary_source"], "本地规则")
        self.assertEqual(res["remote"]["reason"], "连接失败")

    def test_empty_window_still_reports_honestly(self):
        res = rr.build(date_str="20261104", news_corpus={"items": []}, allow_network=False)
        self.assertFalse(res["available"])
        self.assertIn("未检出", res["summary"])
        self.assertEqual(res["points"], [])

    def test_llm_polish_rejects_forbidden_numbers_and_unknown_institutions(self):
        points = rr.collect_local(CORPUS["items"], rr.parse_datetime("2026-11-04 12:00"))
        cfg = {"enabled": True, "model": "m", "base": "http://x", "key": "k", "timeout": 5}
        bad_cases = [
            {"summary": "一定要减仓", "focus": "观望"},
            {"summary": "机构下调评级", "focus": "目标价 250 元"},
            {"summary": "瑞信证券下调评级", "focus": "观望"},
        ]
        for payload in bad_cases:
            with self.subTest(payload=payload), \
                 patch("hk_seven_day.call_llm", return_value=(payload, "")):
                out = rr.polish_with_llm(points, None, cfg)
                self.assertFalse(out["ok"], f"应被护栏拦下：{payload}")
        with patch("hk_seven_day.call_llm",
                   return_value=({"summary": "评级端偏谨慎，下调集中在科技权重",
                                  "focus": "先建防守清单，等研报原文确认"}, "")):
            out = rr.polish_with_llm(points, None, cfg)
        self.assertTrue(out["ok"])
        self.assertIn("评级端", out["summary"])


class ResearchRiskReportTests(unittest.TestCase):
    """渲染层：位置 / 唯一 / 诚实占位 / 转义。"""

    @classmethod
    def setUpClass(cls):
        cls.pipeline = pipeline

    def _data(self):
        return pipeline_report_data(self.pipeline)

    def _result(self, **kwargs):
        base = {"enabled": True, "available": True,
                "points": [
                    {"institution": "高盛", "intl": True, "category": "评级与目标价",
                     "date": "2026-11-03", "source": "研报",
                     "title": "高盛下调韩国股指目标价<script>alert(1)</script>",
                     "url": "javascript:alert(1)"},
                    {"institution": "未署名", "intl": False, "category": "合规与监管",
                     "date": "2026-11-02", "source": "东财", "title": "某公司被立案调查",
                     "url": "https://example.com/b"},
                ],
                "summary": "机构口径偏谨慎，下调集中在评级端",
                "focus": "先按标题线索做防守清单", "tone_source": "规则",
                "summary_source": "本地规则", "remote": {}, "window_hours": 360,
                "newest_date": "2026-11-03",
                "categories": {"评级与目标价": 1, "合规与监管": 1}, "llm": {}}
        base.update(kwargs)
        return base

    def test_block_sits_after_beginner_tips_and_before_forecast_in_every_theme(self):
        data = self._data()
        for theme in self.pipeline.PUSH_THEMES:
            with self.subTest(theme=theme):
                html = self.pipeline.generate_report(
                    data, "2026年8月2日 · 周日", "20260802", theme=theme,
                    research_risk=self._result())
                # 分条压缩版藏在 data-rr-compact 属性里（display:none，页面上看不见），
                # 统计可见标题前先把它摘掉，避免把同一段文字数成两处。
                visible = re.sub(r'<div data-rr-compact="[^"]*"[^>]*></div>', "", html)
                self.assertEqual(visible.count(self.pipeline.SECTION_TITLE_RESEARCH_RISK), 1,
                                 f"{theme}: 整篇只能出现一处")
                self.assertLess(html.index("新手三句话"),
                                html.index(self.pipeline.SECTION_TITLE_RESEARCH_RISK),
                                f"{theme}: 必须排在新手三句话之后")
                self.assertLess(html.index(self.pipeline.SECTION_TITLE_RESEARCH_RISK),
                                html.index(self.pipeline.SECTION_TITLE_FORECAST),
                                f"{theme}: 必须在正文（今日预判）之前")
                # 不进正文编号序列：今日预判仍是第一个编号栏目
                parts = self.pipeline._collect_report_parts(
                    data, self.pipeline.GUIZANG_KIT, date_str="20260802",
                    research_risk=self._result())
                self.assertEqual(parts["sections"][0][0], "FORECAST")
                self.assertNotIn("RESEARCH RISK", [s[0] for s in parts["sections"]])

    def test_points_render_escaped_and_only_http_links(self):
        parts = self.pipeline._collect_report_parts(
            self._data(), self.pipeline.GUIZANG_KIT, date_str="20260802",
            research_risk=self._result())
        html = parts["research_risk_html"]
        self.assertIn("高盛", html)
        self.assertNotIn("<script>", html, "标题必须转义")
        self.assertNotIn("javascript:alert", html, "非 http(s) 链接不得进入 href")
        self.assertIn('href="https://example.com/b"', html)
        self.assertIn("合规与监管", html)

    def test_empty_points_still_render_the_section(self):
        parts = self.pipeline._collect_report_parts(
            self._data(), self.pipeline.GUIZANG_KIT, date_str="20260802",
            research_risk=self._result(available=False, points=[], summary="本期未检出研报风险线索",
                                       focus="继续观察评级与目标价变动", categories={},
                                       newest_date=""))
        html = parts["research_risk_html"]
        self.assertIn(self.pipeline.SECTION_TITLE_RESEARCH_RISK, html)
        self.assertIn("未检出", html)

    def test_bagua_off_still_keeps_the_block_in_opening(self):
        import octopus_bagua as bagua
        data = self._data()
        with patch.object(bagua, "ENABLED", False):
            parts = self.pipeline._collect_report_parts(
                data, self.pipeline.GUIZANG_KIT, date_str="20260802",
                research_risk=self._result())
            opening = self.pipeline._poetry_sea_section(parts, self.pipeline.GUIZANG_KIT)
        self.assertIn(self.pipeline.SECTION_TITLE_RESEARCH_RISK, opening)
        self.assertNotIn("新手三句话", opening, "卦象关闭时三句话回落速查卡末尾")

    def test_env_switch_turns_the_block_off(self):
        with patch.object(self.pipeline, "RESEARCH_RISK_ENABLED", False):
            parts = self.pipeline._collect_report_parts(
                self._data(), self.pipeline.GUIZANG_KIT, date_str="20260802")
        self.assertEqual(parts["research_risk_html"], "")

    def test_split_condenses_block_when_one_part_over_the_cap(self):
        """分条拥挤时压成一行摘要，尾栏（短线速查卡）不再被截掉。"""
        from test_pipeline import SectionReadingOrderTests, MarketPanoramaTests
        data = SectionReadingOrderTests()._full_data()
        data["A股大盘全景"] = MarketPanoramaTests()._panorama_payload()
        html = self.pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802",
                                             theme="forum",
                                             research_risk=self._result())
        parts = self.pipeline._split_html_for_push(html, 12000) or []
        self.assertLessEqual(len(parts), self.pipeline.PUSHPLUS_MAX_PARTS)
        self.assertTrue(any(self.pipeline.SECTION_TITLE_SHORT_CARD in part for part in parts),
                        "压缩卷首块之后，尾栏必须还在")


if __name__ == "__main__":
    unittest.main(verbosity=2)
