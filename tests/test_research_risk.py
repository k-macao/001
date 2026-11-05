#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚠️「研报 AI 风险点提示」栏目回归（2026-11-04 原样复制粘贴 k-macao/007 推送同样栏目文字）。

守五件事：
  · 原文——在线取到 007 就整段一字不差直搬（不解析重组、不与本地条目合并）；
    取不到就用 007 推送原文模板逐字生成（开头句 / 条目标签 / 空样本句 / 收尾段），
    本仓不自创「定调 / 关注点」等文字、不调大模型润色；
  · 位置——每个推送主题里都排在 🐣 新手三句话之后、正文（今日预判）之前，整篇只出现一处，
    且原文不按精简版裁条数（007 原文最多 5 条）；
  · 内容——本地条目来自研报 / 快讯标题池，标题先转义；007 原文不带链接，渲染不生成 href；
  · 诚实——一条线索都没有时栏目照常出，用 007 原文空样本句如实说明，绝不静默消失；
  · 数字——收尾段利空条数 / 情绪均值 / 多头胜率锚点按 007 同一把打分尺与锚点公式
    对本地标题池计算，样本为 0 时不写收尾段（不出现「0/0 条」）。
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
        "先把防线划清楚。翻开这周外资大行的研报夹，唱多声里其实夹着几记颇为冷静的刹车声——"
        "凡是机构主动下调评级或改口观望的地方，往往正对着市场最脆弱的预期软肋：\n\n"
        "- **[国外投行 · 摩根士丹利]** 下调半导体板块评级至中性（neutral）\n"
        "- **[国外投行 · 瑞银]** 中国互联网板块盈利预期存在下修风险\n\n"
        "从样本冷暖来看，这 7 篇外资报告里利空占 2 篇、中性 3 篇、利好 2 篇。"
        "在多数情况下，大行的纸面评级只是参考坐标，真正在牌桌上决定方向的，"
        "还得看资金愿不愿意掏真金白银跟进。\n\n"
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

    def test_build_remote_verbatim_not_merged_with_local(self):
        section = rr.extract_section_md(REMOTE_PAYLOAD["rule_md"])
        self.assertTrue(section.startswith("## ⚠️ 研报 AI 风险点提示"))
        with patch.object(rr, "fetch_remote",
                          return_value={"ok": True, "section_md": section,
                                        "points": rr.parse_rule_md(REMOTE_PAYLOAD["rule_md"]),
                                        "url": "http://x/api/foreign_weekly",
                                        "env": "OCTOPUS_007_BASE_URL"}):
            res = rr.build(date_str="20261104", news_corpus=CORPUS)
        self.assertTrue(res["available"])
        # 整段原文一字不差：不解析重组、不混进本地条目（高盛 / BMO 都不许出现）
        self.assertEqual(res["verbatim_md"], section)
        self.assertEqual(res["verbatim_source"], "007在线原文")
        self.assertNotIn("高盛", res["verbatim_md"])
        self.assertNotIn("BMO", res["verbatim_md"])
        institutions = {p["institution"] for p in res["points"]}
        self.assertEqual(institutions, {"摩根士丹利", "瑞银"})

    def test_build_remote_section_without_items_still_verbatim(self):
        section = ("## ⚠️ 研报 AI 风险点提示\n\n"
                   "说起来，这周命中的外资研报表面上一团和气，没看到密集的下调评级。")
        with patch.object(rr, "fetch_remote",
                          return_value={"ok": True, "section_md": section, "points": [],
                                        "url": "http://x/api/foreign_weekly"}):
            res = rr.build(date_str="20261104", news_corpus=CORPUS)
        self.assertEqual(res["verbatim_md"], section,
                         "在线原文哪怕一条条目都没有，也整段直搬，不回落本地")
        self.assertEqual(res["points"], [])
        self.assertFalse(res["available"])

    def test_build_falls_back_to_local_when_remote_fails(self):
        with patch.object(rr, "fetch_remote",
                          return_value={"ok": False, "section_md": "", "points": [],
                                        "url": "", "reason": "连接失败"}):
            res = rr.build(date_str="20261104", news_corpus=CORPUS)
        self.assertTrue(res["available"])
        self.assertEqual(res["summary_source"], "本地规则")
        self.assertEqual(res["remote"]["reason"], "连接失败")
        # 本地兜底 = 007 推送原文模板逐字生成（开头句 / 条目标签 / 收尾段一字不差）
        md = res["verbatim_md"]
        self.assertTrue(md.startswith("## ⚠️ 研报 AI 风险点提示"))
        self.assertIn("先把丑话说在前面。盘面上热闹归热闹，但下面这几处暗礁眼下还真不能假装看不见——"
                      "尤其是机构开始收紧口径的地方，往往藏着资金最真实的顾虑：", md)
        # 评级尾注用 007 _mk_item 正则：取标题里第一个命中的评级词（「下调」先于「减持」）
        self.assertIn("- **[国外投行 · 高盛]** 高盛下调韩国股指目标价，维持减持评级（下调）", md)
        self.assertIn("- **[快讯风险信号 · 智通财经]** BMO维持美洲白银公司买入评级 "
                      "下调目标价至6.4美元（情绪 -1.00）", md)
        # 收尾段数字按 007 打分尺对同一标题池计算：窗口内 4 条，利空 2 条，均值 -0.50，锚点 5%
        self.assertIn("翻看这批快讯底稿，利空消息占了 2/4 条"
                      "（情绪均值 -0.50，多头胜率锚点大概在 5% 上下）。", md)
        self.assertNotIn("机构口径偏谨慎", md, "不得出现本仓自创定调")

    def test_empty_window_still_reports_honestly(self):
        res = rr.build(date_str="20261104", news_corpus={"items": []}, allow_network=False)
        self.assertFalse(res["available"])
        self.assertEqual(res["points"], [])
        # 栏目文字用 007 原文零样本句，且不写「0/0 条」收尾
        self.assertIn("眼下这个时间窗抓到的有效快讯和研报样本偏少", res["verbatim_md"])
        self.assertIn("眼下这个时间窗抓到的有效快讯和研报样本偏少", res["summary"])
        self.assertNotIn("0/0", res["verbatim_md"])

    def test_brief_md_buckets_match_007_push_labels(self):
        points = [
            {"institution": "中金公司", "intl": False, "source": "研报",
             "title": "中金公司：下调某地产评级至中性，提示销售风险"},
            {"institution": "", "intl": False, "source": "东财快讯",
             "title": "某公司预亏并收到处罚，股价大跌"},
            {"institution": "高盛", "intl": True, "source": "研报",
             "title": "高盛：维持标普500中性"},
        ]
        md = rr.render_brief_risk_md(points, {"n": 0})
        # 007 顺序：国外投行 → 香港券商 → 快讯风险信号，与输入顺序无关
        self.assertLess(md.index("[国外投行 · 高盛]"), md.index("[香港券商 · 中金公司]"))
        self.assertLess(md.index("[香港券商 · 中金公司]"), md.index("[快讯风险信号 · 东财快讯]"))
        self.assertIn("高盛：维持标普500中性（中性）", md)
        self.assertIn("某公司预亏并收到处罚，股价大跌（情绪 -1.00）", md)

    def test_build_never_calls_llm(self):
        cfg = {"enabled": True, "model": "m", "base": "http://x", "key": "k", "timeout": 5}
        with patch("hk_seven_day.call_llm") as mock_llm:
            mock_llm.side_effect = AssertionError("原文直搬不得调用大模型")
            res = rr.build(date_str="20261104", news_corpus=CORPUS,
                           llm_config=cfg, allow_network=False)
        mock_llm.assert_not_called()
        self.assertEqual(res["tone_source"], "原文")
        self.assertFalse(res["llm"]["ok"])
        self.assertEqual(res["verbatim_md"],
                         rr.render_brief_risk_md(res["points"], res["feed_agg"]))


class ResearchRiskReportTests(unittest.TestCase):
    """渲染层：位置 / 唯一 / 诚实占位 / 转义。"""

    @classmethod
    def setUpClass(cls):
        cls.pipeline = pipeline

    def _data(self):
        return pipeline_report_data(self.pipeline)

    _FEED_AGG = {"n": 4, "pos": 0, "neg": 2, "neu": 2, "mean": -0.5,
                 "综合多头概率锚点": 5}

    def _result(self, **kwargs):
        points = [
            {"institution": "高盛", "intl": True, "category": "评级与目标价",
             "date": "2026-11-03", "source": "研报",
             "title": "高盛下调韩国股指目标价<script>alert(1)</script>",
             "url": "javascript:alert(1)"},
            {"institution": "未署名", "intl": False, "category": "合规与监管",
             "date": "2026-11-02", "source": "东财", "title": "某公司被立案调查",
             "url": "https://example.com/b"},
        ]
        # 与生产路径一致：展示文字由 007 原文模板从 points 生成；
        # summary 故意填本仓旧自创定调，渲染必须对它视而不见。
        base = {"enabled": True, "available": True,
                "points": points,
                "verbatim_md": rr.render_brief_risk_md(points, self._FEED_AGG),
                "verbatim_source": "007推送原文模板（本地标题池）",
                "feed_agg": dict(self._FEED_AGG),
                "summary": "机构口径偏谨慎，下调集中在评级端",
                "focus": "先按标题线索做防守清单", "tone_source": "原文",
                "summary_source": "本地规则", "remote": {}, "window_hours": 360,
                "newest_date": "2026-11-03",
                "categories": {"评级与目标价": 1, "合规与监管": 1}, "llm": {}}
        base.update(kwargs)
        return base

    def test_block_sits_after_beginner_tips_and_before_forecast_in_every_theme(self):
        self.assertEqual(self.pipeline.SECTION_TITLE_RESEARCH_RISK, "全球研报 AI 速递")
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
                # 不进正文编号序列：风险块仍在卷首；正文栏首是前置的速查卡
                # （原 24 号，2026-11-04 移到本块之后），再是今日预判
                parts = self.pipeline._collect_report_parts(
                    data, self.pipeline.GUIZANG_KIT, date_str="20260802",
                    research_risk=self._result())
                kickers = [s[0] for s in parts["sections"]]
                self.assertEqual(kickers[0], "SHORT CARD")
                self.assertLess(kickers.index("SHORT CARD"), kickers.index("FORECAST"))
                self.assertNotIn("RESEARCH RISK", kickers)
                # 可见顺序：研报风险点（卷首）→ 速查卡 → 今日预判
                self.assertLess(html.index(self.pipeline.SECTION_TITLE_RESEARCH_RISK),
                                html.index(self.pipeline.SECTION_TITLE_SHORT_CARD),
                                f"{theme}: 速查卡必须紧随研报风险点之后")
                self.assertLess(html.index(self.pipeline.SECTION_TITLE_SHORT_CARD),
                                html.index(self.pipeline.SECTION_TITLE_FORECAST),
                                f"{theme}: 速查卡必须在今日预判之前")

    def test_verbatim_render_escaped_no_links_no_invented_rows(self):
        parts = self.pipeline._collect_report_parts(
            self._data(), self.pipeline.GUIZANG_KIT, date_str="20260802",
            research_risk=self._result())
        html = parts["research_risk_html"]
        # 007 原文整段在场（开头句 / 条目标签 / 收尾段），可见文字与 007 推送一致
        self.assertIn("先把丑话说在前面。盘面上热闹归热闹", html)
        self.assertIn("[国外投行 · 高盛]", html)
        self.assertIn("高盛下调韩国股指目标价", html)
        self.assertIn("[快讯风险信号 · 东财]", html)
        self.assertIn("某公司被立案调查（情绪 +0.00）", html)
        self.assertIn("翻看这批快讯底稿，利空消息占了 2/4 条", html)
        # 标题先转义，007 原文不带链接 ⇒ 不生成任何 href（js: 与 https: 都不出）
        self.assertNotIn("<script>", html, "标题必须转义")
        self.assertNotIn("javascript:alert", html)
        self.assertNotIn('href="https://example.com/b"', html)
        # 本仓自创文字（定调 / 关注点 / 类别小字等）一律不许再出现
        for invented in ("机构口径偏谨慎", "先按标题线索做防守清单", "定调", "关注点",
                         "线索条数", "合规与监管", "风险类别", "文风"):
            self.assertNotIn(invented, html, f"不得出现本仓自创文字：{invented}")

    def test_remote_verbatim_renders_char_for_char_text(self):
        section = rr.extract_section_md(REMOTE_PAYLOAD["rule_md"])
        res = self._result(verbatim_md=section, verbatim_source="007在线原文",
                           points=rr.parse_rule_md(REMOTE_PAYLOAD["rule_md"]))
        parts = self.pipeline._collect_report_parts(
            self._data(), self.pipeline.GUIZANG_KIT, date_str="20260802",
            research_risk=res)
        html = parts["research_risk_html"]
        expected = re.sub(
            r"\s+", "", section.replace("## ⚠️ 研报 AI 风险点提示", "全球研报 AI 速递")
            .replace("**", "").replace("- ", ""))
        # 去掉 data-rr-compact 隐藏摘要与主题列表符（◆ 等价于 md 的「-」）后，
        # 可见正文必须与 007 原文逐字一致
        text = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "",
                      re.sub(r'<div data-rr-compact="[^"]*"[^>]*></div>', "", html)
                      .replace("◆", "")))
        self.assertEqual(text, expected)

    def test_empty_points_still_render_the_section(self):
        parts = self.pipeline._collect_report_parts(
            self._data(), self.pipeline.GUIZANG_KIT, date_str="20260802",
            research_risk=self._result(
                available=False, points=[],
                verbatim_md=rr.render_brief_risk_md([], {"n": 0}),
                summary="本期未检出研报风险线索（自创句不应出现）",
                feed_agg={"n": 0}, categories={}, newest_date=""))
        html = parts["research_risk_html"]
        self.assertIn(self.pipeline.SECTION_TITLE_RESEARCH_RISK, html)
        self.assertIn("眼下这个时间窗抓到的有效快讯和研报样本偏少", html,
                      "空样本也必须出栏目，且用 007 原文句")
        self.assertNotIn("未检出研报风险线索（自创句不应出现）", html)

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
        """分条拥挤时压成一行摘要，尾栏（今日总结）与前置的速查卡都不再被截掉。"""
        from test_pipeline import SectionReadingOrderTests, MarketPanoramaTests
        data = SectionReadingOrderTests()._full_data()
        data["A股大盘全景"] = MarketPanoramaTests()._panorama_payload()
        html = self.pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802",
                                             theme="forum",
                                             research_risk=self._result())
        parts = self.pipeline._split_html_for_push(html, 12000) or []
        self.assertLessEqual(len(parts), self.pipeline.PUSHPLUS_MAX_PARTS)
        self.assertTrue(any(self.pipeline.SECTION_TITLE_SHORT_CARD in part for part in parts),
                        "压缩卷首块之后，前置速查卡必须还在")
        self.assertTrue(any(self.pipeline.SECTION_TITLE_SUMMARY in part for part in parts),
                        "压缩卷首块之后，尾栏今日总结必须还在")


if __name__ == "__main__":
    unittest.main(verbosity=2)
