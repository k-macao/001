"""🐣 入门版（PLAIN）回归测试（全部离线）。

2026-10-03 用户反馈「阅读不适合入门，减少说明文字，过程文字」→ 默认日报在精简版面
之上再收一层：方法论 / 口径 / 供数过程 / 折叠披露 / 每栏重复免责整段不渲染；
结论、数字、AI帮你提鲜、今日预判、速查卡、数据日期与「暂缺」点名一个不少。

守的三条口径：
  · 默认即入门版：OCTOPUS_LITE=1 且未要求说明文字 → PLAIN() 为真；
  · --notes / OCTOPUS_NOTES=1 逐字找回 2026-09-30 的「精简 + 说明文字」版；
    --full / OCTOPUS_LITE=0 仍是全量长版，与入门版开关无关；
  · 入门版只删说明文字 / 过程文字：结论型内容与新鲜度标记必须原样在。
"""
import importlib.util
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("requests", types.SimpleNamespace())
sys.path.insert(0, str(Path(__file__).parents[1] / "output"))
sys.path.insert(0, str(Path(__file__).parent))

import pipeline  # noqa: E402
import octopus_short as short  # noqa: E402
import octopus_ren as ren  # noqa: E402

_render = pipeline._quant.render


def _strip(html):
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def _rich_data():
    """整链数据：复用速查卡测试的多源夹具（日程 / 量化引擎 / 每周预测 / 全景 / 情绪…），
    再补 MACD / 板块轮动两路，覆盖所有带说明文字的栏目。"""
    import test_short_card as tsc
    import test_sector_rotation as tsr
    import test_macd_strategy as tms
    case = tsc.CardRenderingTests()
    case.setUpClass()
    data = case._data()
    concepts, stocks, benchmark, headlines = tsr._full_inputs()
    rotation = tsr.rotation.build_rotation(concepts, stocks, benchmark, headlines,
                                           catalog_complete=True, now=tsr.NOW)
    rotation["source_names"] = ["东方财富 A股概念库", "Yahoo / 东方财富港股日线"]
    data[pipeline.SECTOR_ROTATION_SOURCE_NAME] = pipeline._source_result(
        "东方财富 A股概念库 + 港股日线/快照", "success", is_today=True,
        content_date="2026-08-02", result=rotation)
    data[pipeline.MACD_SOURCE_NAME] = pipeline._source_result(
        pipeline.MACD_SOURCE_NAME, "success", content_date="2026-08-02", result=tms.result_for())
    return data


class SwitchSemanticsTests(unittest.TestCase):
    def test_default_is_plain_and_notes_restores(self):
        self.assertTrue(pipeline.LITE_ENABLED)
        self.assertFalse(pipeline.NOTES_REQUESTED)
        self.assertTrue(pipeline.PLAIN())
        self.assertTrue(_render._plain())
        with pipeline.notes_mode():
            self.assertTrue(pipeline.NOTES_REQUESTED)
            self.assertFalse(pipeline.PLAIN())
            self.assertFalse(_render.PLAIN)
            self.assertFalse(_render._plain())
        # 退出后恢复
        self.assertFalse(pipeline.NOTES_REQUESTED)
        self.assertTrue(pipeline.PLAIN())
        self.assertTrue(_render.PLAIN)

    def test_full_mode_is_never_plain(self):
        with patch.object(pipeline, "LITE_ENABLED", False):
            self.assertFalse(pipeline.PLAIN())
            _render.LITE = False
            try:
                self.assertFalse(_render._plain())
            finally:
                _render.LITE = True

    def test_set_notes_requested_returns_previous_and_syncs_render(self):
        prev = pipeline.set_notes_requested(True)
        try:
            self.assertFalse(prev)
            self.assertFalse(_render.PLAIN)
        finally:
            pipeline.set_notes_requested(prev)
        self.assertTrue(_render.PLAIN)

    def test_gz_note_hidden_in_plain_visible_with_notes(self):
        self.assertEqual(pipeline.gz_note("口径说明"), "")
        with pipeline.notes_mode():
            self.assertIn("口径说明", pipeline.gz_note("口径说明"))
        self.assertEqual(pipeline.gz_note(""), "")


class CalendarDigestTests(unittest.TestCase):
    def _res(self):
        import test_pipeline as tp
        res, _ = tp.EconCalendarTests()._fetch()
        return res

    def test_cal_digest_default_keeps_full_text_plain_drops_process(self):
        res = self._res()
        full = dict(pipeline._cal_digest(res)["pairs"])
        plain = dict(pipeline._cal_digest(res, plain=True)["pairs"])
        self.assertIn("筛选口径", full)
        self.assertNotIn("筛选口径", plain)
        self.assertIn("时间点合计", plain)
        self.assertIn("最密集日", plain)
        self.assertNotIn("规则合成，非方向判断", plain["最密集日"])
        self.assertIn("规则合成，非方向判断", full["最密集日"])
        # 数字一致：合计 / 星级来自同一批 items
        self.assertEqual(full["时间点合计"].split("（")[0].split(" · 另")[0],
                         plain["时间点合计"].split("（")[0].split(" · 另")[0])


class ReportPlainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = _rich_data()
        cls.plain = {}
        cls.notes = {}
        for theme in ("guizang", "pixel"):
            cls.plain[theme] = pipeline.generate_report(
                cls.data, "2026年8月2日 · 周日", "20260802", theme=theme)
            with pipeline.notes_mode():
                cls.notes[theme] = pipeline.generate_report(
                    cls.data, "2026年8月2日 · 周日", "20260802", theme=theme)

    # ---- 说明文字 / 过程文字：入门版不出，--notes 回来 ----
    PROCESS_MARKERS = (
        "--full 看全文", "--full 查看", "规则合成 · 大白话翻译", "计算口径", "执行规则",
        "无未来函数口径", "先存档后结算", "筛选口径", "五维权重", "GitHub 方法参考",
        "推进式（walk-forward）", "Brier", "对数损失", "动态权重依据", "概率动态修正",
        "对概率的修正", "Amihud", "统计口径）", "数字与下文各栏同源", "百句股票梗库",
        "精简版面", "归因：精确名", "映射命中词", "可用权重", "分页完整", "每日 09:00 前更新",
        "归藏简洁排版",
    )

    def test_plain_report_has_no_process_text_in_default_theme(self):
        text = _strip(self.plain["guizang"])
        for marker in self.PROCESS_MARKERS:
            self.assertNotIn(marker, text, marker)

    def test_notes_report_restores_process_text(self):
        text = _strip(self.notes["guizang"])
        # 「推进式（walk-forward）」只出现在已下线的量化分析总览里（2026-10-23），
        # 其余过程文字仍由各个在栏章节在 --notes 模式下恢复。
        for marker in ("--full 看全文", "规则合成 · 大白话翻译", "计算口径", "执行规则",
                       "无未来函数口径", "先存档后结算", "筛选口径", "五维权重",
                       "Brier", "数字与下文各栏同源", "百句股票梗库"):
            self.assertIn(marker, text, marker)

    def test_plain_is_materially_shorter_than_notes(self):
        # guizang 入门版至少砍掉两成文字；pixel 主题只要求确实更短
        for theme, ratio in (("guizang", 0.8), ("pixel", 1.0)):
            plain_len = len(_strip(self.plain[theme]))
            notes_len = len(_strip(self.notes[theme]))
            self.assertLess(plain_len, notes_len * ratio,
                            f"{theme}: 入门版 {plain_len} 字 vs 说明版 {notes_len} 字")

    # ---- 结论型内容：一个不少 ----
    def test_plain_keeps_conclusions_numbers_and_fresh_markers(self):
        for theme in ("guizang", "pixel"):
            html = self.plain[theme]
            text = _strip(html)
            # 「模型自检 / 指数概率」原属量化分析总览（2026-10-23 下线），
            # 概率与逐日表格仍在每日趋势量化推演里。
            for marker in ("结论", "AI帮你提鲜", "活鲜度", pipeline.SECTION_TITLE_FORECAST,
                           pipeline.SECTION_TITLE_SHORT_CARD, "新手三句话",
                           "P(7日涨)", "逐日表格",
                           "时间点合计", "最密集日", "数据覆盖", "暂缺：",
                           "当天", "非投资建议"):
                self.assertIn(marker, text, f"{theme}: {marker}")
            # 数字不丢：量化表的概率、日程星级、速查卡数据底
            self.assertIn("★★★", text, theme)
            self.assertRegex(text, r"当天源 \d+/\d+", theme)

    def test_plain_short_card_caption_and_tips_title(self):
        text = _strip(self.plain["guizang"])
        self.assertIn(short.CAPTION_PLAIN, text)
        self.assertIn(short.TIPS_TITLE_PLAIN, text)
        self.assertNotIn(short.CAPTION, text)

    def test_plain_keeps_single_disclaimer_in_footer(self):
        html = self.plain["guizang"]
        self.assertNotIn(ren.DISCLAIMER, html)
        self.assertIn("仅供参考，非投资建议", html)
        self.assertIn("未抓到内容的栏目自动缺席", html)

    def test_plain_merged_intro_rows_have_no_process_sub(self):
        for theme in ("guizang", "pixel"):
            self.assertNotIn("原独立栏目并入本节", self.plain[theme], theme)

    def test_push_eligibility_and_audit_meta_unchanged_by_plain(self):
        meta_plain = pipeline._report_meta(self.plain["guizang"])
        meta_notes = pipeline._report_meta(self.notes["guizang"])
        self.assertEqual(meta_plain["total_sources"], meta_notes["total_sources"])
        self.assertEqual(meta_plain["today_sources"], meta_notes["today_sources"])


class WeeklyCardsPlainTests(unittest.TestCase):
    def _daily(self, same_warn=True):
        rows = []
        for k in range(1, 8):
            notes = ["仓位", "低波动环境，止损从紧", "尾注"]
            if not same_warn and k == 4:
                notes = ["仓位", "事件日：美联储议息", "尾注"]
            rows.append({"k": k, "date": f"2026-04-{19 + k:02d}", "direction": "up",
                         "reason": "动量 5日 +3%",
                         "advice": {"stance": "偏多", "stop_pct": 0.03, "stop_price": 25000,
                                    "take_profit": 27000, "entry_hint": "分批建仓", "notes": notes}})
        return {"rows": rows}

    def test_identical_daily_warning_collapses_once_in_plain(self):
        text = _strip(pipeline._weekly_daily_cards(self._daily(), pipeline.GUIZANG_KIT))
        self.assertEqual(text.count("低波动环境"), 1)
        self.assertIn("7 天共同提醒", text)
        self.assertNotIn("为什么", text)
        self.assertNotIn("--full", text)
        with pipeline.notes_mode():
            text = _strip(pipeline._weekly_daily_cards(self._daily(), pipeline.GUIZANG_KIT))
        self.assertEqual(text.count("低波动环境"), 7)        # 说明版：逐日照旧
        self.assertIn("为什么", text)

    def test_differing_daily_warnings_stay_per_day(self):
        text = _strip(pipeline._weekly_daily_cards(self._daily(same_warn=False), pipeline.GUIZANG_KIT))
        self.assertEqual(text.count("低波动环境"), 6)
        self.assertEqual(text.count("事件日"), 1)
        self.assertNotIn("7 天共同提醒", text)


class QuantRenderPlainTests(unittest.TestCase):
    def _quant_result(self):
        from test_quant import run_engine
        with tempfile.TemporaryDirectory() as tmp:
            return run_engine(tmpdir=tmp, n_stocks=12)

    def test_forecast_and_hk_probability_and_liquidity_blocks(self):
        res = self._quant_result()
        kit = pipeline.GUIZANG_KIT
        plain = _strip(_render.render_forecast(res, kit) + _render.render_hk_probability(res, kit)
                       + _render.render_liquidity(res, kit))
        with pipeline.notes_mode():
            notes = _strip(_render.render_forecast(res, kit) + _render.render_hk_probability(res, kit)
                           + _render.render_liquidity(res, kit))
        # 入门版：结论与表格在
        for marker in ("预测概括", "数据时效", "指数概率", "模型自检", "趋势状态", "个股概率",
                       "宽度综合分", "流动性概括", "南向 / 北向资金", "流动性综合分"):
            self.assertIn(marker, plain, marker)
        # 入门版：方法论与推导不出
        for marker in ("动态调整", "预测目标", "概率 = 五因子", "推进式", "Brier", "五因子拆解",
                       "动态权重依据", "综合分 S", "概率动态修正", "60日回归", "Amihud",
                       "对概率的修正", "统计口径", "--full"):
            self.assertNotIn(marker, plain, marker)
        # --notes：回到精简版原样
        for marker in ("动态调整", "预测目标", "推进式", "Brier", "五因子拆解", "对概率的修正"):
            self.assertIn(marker, notes, marker)
        # 数字同源：1 日命中率两版一致（整数百分比）
        m_plain = re.search(r"1日命中 (\d+)%", plain)
        m_notes = re.search(r"1日命中 ([\d.]+)%", notes)
        self.assertIsNotNone(m_plain)
        self.assertIsNotNone(m_notes)
        self.assertEqual(int(m_plain.group(1)), round(float(m_notes.group(1))))


if __name__ == "__main__":
    unittest.main()
