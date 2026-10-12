"""🔁 跨栏「同子栏」合并回归测试（全部离线）。

2026-10-12 用户要求：「给大纲，核对内容重复率，重复就合并同子栏」。
`tools/report_outline.py` 核对出的正文栏重复（结论三栏是设计内的复述，不计）：

  · 【及时秋刀鱼】AI 行情复盘 · 南北向资金（前一收盘）  ⇄  【资金流动性分析】南向 / 北向；
  · 【六眼飞鱼】量化 MACD 策略 · 板块趋势跟踪强度榜    ⇄  AI 行情复盘 · 板块热力
    （涨跌 / 主力净流入是同一批 A股全景数据）。

合并口径（SUB_MERGE_ENABLED，OCTOPUS_SUB_MERGE=0 关闭）：
  · 同一批数据只展开一次，**后出现**的栏目保留子栏标题 + 一行「↳ 同子栏合并」指针，
    数字不静默消失；指针指到栏目名（不带序号，序号随当日出场栏数浮动）；
  · 结论三栏（总结 / 今日预判 / 短线速查卡）不参与合并：它们本来就负责复述结论；
  · 合并只在「保留栏确实在场」时发生（资金流动性栏缺席 → 行情复盘照常出数字），
    绝不让指针指向一个没渲染出来的栏目。

本文件守住：① 合并生效时数字只出现一次；② 保留栏缺席 / 开关关闭时逐字回到旧行为；
③ 结论栏的复述不受影响；④ 切片口径与两个 panorama 渲染器一致。

栏内同子栏的两处（2026-10-12 同日追加）：
  · 新闻情绪栏目（15 栏）：一条快讯同时点名多只个股时，同一篇长标题只展开一次，
    后面几处只留「↳ 同一篇：见 XX」，并在「市场情绪关键词」里如实写出「同题合并 N 条」；
  · 活鲜词库点缀：同一份日报里同一句比喻只出现一次（撞句就按确定性顺序换变体）。
"""
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("requests", types.SimpleNamespace())
sys.path.insert(0, str(Path(__file__).parents[1] / "output"))
sys.path.insert(0, str(Path(__file__).parent))

import pipeline  # noqa: E402
import test_plain_mode as tpm  # noqa: E402


def _text(html):
    text = re.sub(r"<br\s*/?>", " ", html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def _section(html, title):
    """按栏目名截出正文（到下一个栏目头为止），找不到返回空串。"""
    idx = html.find(title)
    if idx < 0:
        return ""
    rest = html[idx:]
    nxt = re.search(r'SECTION\s+\d{2}\s+·', rest)
    # 跳过自身栏目头里的 kicker（本栏标题在 kicker 之后）
    nxt2 = re.search(r'SECTION\s+\d{2}\s+·', rest[rest.find("<!--BODY-->") + 11:])
    return _text(rest if nxt2 is None else rest[:rest.find("<!--BODY-->") + 11 + nxt2.start()])


class SubMergeRenderTests(unittest.TestCase):
    """整页渲染：两处正文栏重复的合并行为。"""

    @classmethod
    def setUpClass(cls):
        cls.data = tpm._rich_data()

    def render(self, data=None):
        return pipeline.generate_report(data if data is not None else self.data,
                                        "2026年10月12日 · 周一", "20261012")

    # ---- ① 南北向资金：资金流动性分析在场 → 行情复盘只留指针 ----
    def test_flow_merge_keeps_numbers_once_and_points_to_liquidity(self):
        html = self.render()
        text = _text(html)
        self.assertIn(pipeline.SUB_MERGE_POINTER, text)
        self.assertIn(f"见 {pipeline.SUB_MERGE_OWNER_LIQUIDITY}", text)
        # A股全景里的 1,350.25 / 88.50 亿不再重复出现（同一批数据只在资金流动性栏展开）
        self.assertNotIn("1,350.25", text)
        self.assertNotIn("88.50", text)
        # 资金流动性栏自己的成交总额照常显示
        self.assertIn("南向（港股通）", text)
        self.assertIn("北向（陆股通）", text)
        # 子栏标题保留：读者仍知道这里本来是南北向资金
        self.assertIn("南北向资金（前一收盘）", text)

    def test_flow_numbers_return_when_liquidity_section_absent(self):
        data = dict(self.data)
        data.pop("港股量化", None)
        text = _text(self.render(data))
        self.assertIn("1,350.25", text)          # 行情复盘照常出数字
        self.assertNotIn(f"见 {pipeline.SUB_MERGE_OWNER_LIQUIDITY}", text)
        self.assertNotIn("资金流动性分析", text)   # 没有保留栏，就没有指向它的指针

    def test_flow_merge_can_be_switched_off(self):
        with patch.object(pipeline, "SUB_MERGE_ENABLED", False):
            text = _text(self.render())
        self.assertIn("1,350.25", text)
        self.assertNotIn(pipeline.SUB_MERGE_POINTER, text)

    # ---- ② 板块涨跌 / 主力净流入：行情复盘的板块热力为准 ----
    def test_board_merge_dedupes_price_and_flow(self):
        text = _text(self.render())
        board = _section(self.render(), "板块趋势跟踪 · 量化强度榜")
        self.assertIn(pipeline.SUB_MERGE_POINTER, board)
        self.assertNotIn("+3.50%", board)        # 涨跌已由行情复盘展示
        self.assertNotIn("15.00亿", board)       # 主力净流入同理
        self.assertIn("趋势分", board)            # 趋势分 / 趋势 / 信号一个不少
        # 全篇只出现一次（行情复盘 · 板块热力）
        self.assertEqual(text.count("15.00亿"), 1)
        self.assertEqual(text.count("-8.00亿"), 1)

    def _ten_board_pan(self):
        """10 个板块（5 涨 5 跌）的全景数据：用来验证「只合并 12 栏真的展示过的板块」。"""
        def row(name, chg, inflow):
            return {"name": name, "chg_pct": chg, "main_inflow": inflow,
                    "lead_stock": "龙头", "lead_stock_pct": 9.9}
        return {
            "indices": [], "breadth": None, "turnover": None,
            "north": {"available": True, "amount_yi": 1.0, "date": "2026-10-12",
                      "south_available": True, "south_amount_yi": 2.0, "south_date": "2026-10-12"},
            "sectors": {
                "leading": [row(f"甲{i}", 3.0 + i, 1e9 * (i + 1)) for i in range(5)],
                "lagging": [row(f"乙{i}", -3.0 - i, -1e9 * (i + 1)) for i in range(5)],
            },
        }

    def test_board_merge_only_covers_boards_shown_in_heat_list(self):
        """12 栏只展示前 N 个热点板块 → 强度榜里没被展示的板块必须保留自己的数字。"""
        data = dict(self.data)
        pan = self._ten_board_pan()
        data["A股大盘全景"] = pipeline._source_result(
            "A股全景（测试）", "success", is_today=True, content_date="2026-10-12", **pan)
        with patch.dict(pipeline.LITE_LIMITS, {"sector_heat": (1, 1)}):
            html = self.render(data)
            shown = pipeline._panorama_heat_selection(pan, "lime")
        board = _section(html, "板块趋势跟踪 · 量化强度榜")
        body = board.split("▼ 规避")[0]
        names = [f"{g}{i}" for g in ("甲", "乙") for i in range(5)]
        shown_rows = [n for n in names if n in body]
        self.assertTrue(shown_rows)
        expected = sum(1 for n in shown_rows if n in shown)
        # 每行合并一次（涨跌单元格里的指针）+ 表下的一行合并说明（有合并才出现）
        self.assertEqual(body.count(pipeline.SUB_MERGE_POINTER),
                         expected + (1 if expected else 0))
        self.assertTrue(any(n not in shown for n in shown_rows),
                        "该夹具应至少有一个板块没被 12 栏展示，才能守住「不误合并」")

    def test_board_merge_can_be_switched_off(self):
        with patch.object(pipeline, "SUB_MERGE_ENABLED", False):
            html = self.render()
        board = _section(html, "板块趋势跟踪 · 量化强度榜")
        self.assertIn("+3.50%", board)
        self.assertIn("15.00亿", board)
        self.assertNotIn(pipeline.SUB_MERGE_POINTER, _text(html))

    # ---- ③ 结论三栏不受合并影响（它们的职责就是复述结论） ----
    def test_conclusion_sections_still_restate_numbers(self):
        text = _text(self.render())
        card = _section(self.render(), "【闪电飞鱼】短线速查卡")
        self.assertIn("板块强弱", card)
        self.assertIn("+3.50%", card)            # 速查卡照旧复述


class PanoramaHeatSelectionTests(unittest.TestCase):
    """切片口径：pixel 版不切，其余主题按 LITE("sector_heat") 切（与渲染器同源）。"""

    def _pan(self, n=5):
        return {"sectors": {
            "leading": [{"name": f"板块{i}"} for i in range(n)],
            "lagging": [{"name": f"跌{i}"} for i in range(n)],
        }}

    def test_pixel_theme_keeps_every_row(self):
        names = pipeline._panorama_heat_selection(self._pan(), "pixel")
        self.assertEqual(len(names), 10)
        self.assertIn("板块4", names)

    def test_other_themes_follow_lite_budget(self):
        names = pipeline._panorama_heat_selection(self._pan(), "lime")
        self.assertEqual(len(names), pipeline.LITE("sector_heat") * 2)
        with patch.object(pipeline, "LITE_ENABLED", False):
            full = pipeline._panorama_heat_selection(self._pan(), "lime")
        self.assertEqual(len(full), 10)

    def test_pointer_text_always_names_the_owner(self):
        text = pipeline.sub_merge_pointer_text(pipeline.SUB_MERGE_NOTE_BOARD,
                                               pipeline.SUB_MERGE_OWNER_MARKET_REVIEW)
        self.assertIn(pipeline.SUB_MERGE_OWNER_MARKET_REVIEW, text)
        self.assertIn("不重复展示", text)


class SentiSameHeadlineTests(unittest.TestCase):
    """栏内同子栏合并：同一篇标题在多只个股的证据行里只展开一次。"""

    TITLE = "宁德时代、新易盛、贵州茅台集体获机构上调目标价，主力资金净流入明显"

    def _res(self):
        data = {
            "热门榜单": pipeline._source_result(
                "热门榜单", "success", is_today=True, content_date="2026-08-02",
                markets={"A股": {"stocks": [
                    {"code": "000001", "name": "宁德时代"},
                    {"code": "000002", "name": "新易盛"},
                    {"code": "000003", "name": "贵州茅台"}]}}),
            "全球头条": pipeline._source_result(
                "全球头条", "success", is_today=True, content_date="2026-08-02",
                headlines=[{"title": self.TITLE, "source": "财联社", "url": "",
                            "published_cst": "2026-08-02 10:00", "is_today": True}]),
        }
        with patch.dict(pipeline.LITE_LIMITS, {"senti_stocks": (3, 3), "senti_headlines": (2, 2)}):
            with patch.object(pipeline, "LITE_ENABLED", True):
                return pipeline.build_news_sentiment(data, "20260802", None)

    def test_gz_theme_shows_headline_once_and_points_to_first_stock(self):
        res = self._res()
        text = _text(pipeline.gz_sentiment_block(res))
        self.assertEqual(text.count(self.TITLE), 1, "同一篇标题只应展开一次")
        self.assertIn(pipeline.SUB_MERGE_SAME_HEADLINE, text)
        self.assertIn("见 宁德时代 000001 · A股", text)
        # 精简版面每市场只列最强 / 最弱各 1 只 → 本夹具被合并 1 条，计数行如实披露
        self.assertIn("同题合并 1 条", text)

    def test_pixel_theme_shows_headline_once_in_evidence_and_reason(self):
        res = self._res()
        text = _text(pipeline._pixel_sentiment_block(res))
        # 全量版三只个股都展示：证据行只留一次标题 + 两条指针；「原因」行引用同篇时改为「见下方证据」
        self.assertEqual(text.count(self.TITLE), 1, "同一篇标题只应展开一次（含原因行引用）")
        self.assertIn(pipeline.SUB_MERGE_SAME_HEADLINE, text)
        self.assertIn("见 宁德时代 000001 · A股", text)
        self.assertIn("见下方证据", text)
        self.assertIn("同题合并 2 条", text)

    def test_reason_helper_only_replaces_the_quoted_title(self):
        heads = [{"title": self.TITLE}]
        s = {"reason": f"命中情绪词：净流入；正面主要来自「{self.TITLE[:40]}」；来源：全球头条1条。"}
        out = pipeline._senti_reason_text(s, heads)
        self.assertNotIn(self.TITLE[:20], out)
        self.assertIn("见下方证据", out)
        self.assertIn("命中情绪词：净流入", out)      # 其余原因文字原样保留
        other = {"reason": "命中情绪词：净流入；情绪动量样本不足。"}
        self.assertEqual(pipeline._senti_reason_text(other, heads), other["reason"])

    def test_switch_off_restores_repeated_titles(self):
        res = self._res()
        with patch.object(pipeline, "SUB_MERGE_ENABLED", False):
            text = _text(pipeline.gz_sentiment_block(res))
        # 精简版面每市场只列最强 / 最弱各 1 只 → 旧行为是本夹具里同篇标题出现 2 次
        self.assertEqual(text.count(self.TITLE), 2, "关闭开关后回到逐股各贴一次的旧行为")
        self.assertNotIn(pipeline.SUB_MERGE_SAME_HEADLINE, text)
        self.assertNotIn("同题合并", text)

    def test_owner_helper_is_deterministic(self):
        seen = {}
        self.assertEqual(pipeline.senti_headline_owner(seen, self.TITLE, "甲 · A股"), "")
        self.assertEqual(pipeline.senti_headline_owner(seen, self.TITLE, "乙 · 港股"), "甲 · A股")
        self.assertEqual(pipeline.senti_headline_owner(seen, "  " + self.TITLE + " ", "丙 · 美股"),
                         "甲 · A股")
        self.assertEqual(pipeline.senti_headline_owner(seen, "另一篇完全不同标题", "丙 · 美股"), "")


class GarnishUniquePerReportTests(unittest.TestCase):
    """活鲜词库点缀：同一份日报里同一句比喻只出现一次（撞句换变体，确定性）。"""

    def _run_once(self):
        """按 pipeline 的调用协议跑 6 栏：把已用过的比喻句递进 ctx["_garnish_avoid"]。"""
        import octopus_ren
        ctx = {"date_str": "20261012",
               "notes": {"HK PROBABILITY": {"label": "中性", "bull_pct": 55.0}},
               "quant": {"headline": {"available": True, "label": "中性", "p_up": 0.55}}}
        lines, used = [], []
        for _ in range(6):
            ctx["_garnish_avoid"] = tuple(used)
            lines.append(octopus_ren._seafood_garnish("HK PROBABILITY", ctx).strip())
            _, metaphor = octopus_ren._seafood_garnish_parts("HK PROBABILITY", ctx)
            used.append(metaphor)
        return lines

    def test_six_sections_never_share_the_same_metaphor(self):
        lines = self._run_once()
        self.assertEqual(len(lines), 6)
        self.assertTrue(all(lines), "夹具里每栏都应拿得到点缀")
        self.assertEqual(len(set(lines)), 6, f"点缀句重复：{lines}")

    def test_sequence_is_reproducible(self):
        self.assertEqual(self._run_once(), self._run_once())

    def test_module_itself_stays_stateless(self):
        """同输入同输出：不递进 avoid 时，同一个 ctx 反复调用结果不变（可复现性）。"""
        import octopus_ren
        ctx = {"date_str": "20261012",
               "notes": {"HK PROBABILITY": {"label": "中性", "bull_pct": 55.0}},
               "quant": {"headline": {"available": True, "label": "中性", "p_up": 0.55}}}
        first = octopus_ren._seafood_garnish("HK PROBABILITY", ctx)
        self.assertEqual([octopus_ren._seafood_garnish("HK PROBABILITY", ctx)] * 3, [first] * 3)
        self.assertNotIn("_garnish_used", ctx)      # 模块不改 ctx


class SectorRotationBasketTests(unittest.TestCase):
    """栏内同子栏合并（07 板块轮动）：多个概念共用同一只港股观察篮子时名单只列一次。"""

    def _item(self, name, rank, stocks):
        return {"name": name, "rank": rank, "overall_score": 45.0, "score_label": "中性",
                "mapped_stocks": [{"name": n, "code": c} for n, c in stocks],
                "dimensions": {}, "strategy_votes": [], "strategy_summary": {}}

    def test_same_basket_is_listed_once(self):
        kit = pipeline.GUIZANG_KIT
        seen = {}
        basket = [("腾讯控股", "00700"), ("快手-W", "01024")]
        first = _text(pipeline._sector_rotation_rows(
            self._item("AI应用", 2, basket), kit, rank_label=2, basket_seen=seen))
        second = _text(pipeline._sector_rotation_rows(
            self._item("AIGC概念", 3, basket), kit, rank_label=3, basket_seen=seen))
        self.assertIn("腾讯控股 00700", first)
        self.assertNotIn("腾讯控股 00700", second, "同一篮子的名单不应第二次展开")
        self.assertIn(pipeline.SUB_MERGE_SAME_BASKET, second)
        self.assertIn("见 02 AI应用", second)
        self.assertIn("2 只", second)             # 只数来自同一份映射数据

    def test_different_basket_still_lists_full_names(self):
        kit = pipeline.GUIZANG_KIT
        seen = {}
        pipeline._sector_rotation_rows(
            self._item("AI应用", 2, [("腾讯控股", "00700")]), kit, rank_label=2, basket_seen=seen)
        other = _text(pipeline._sector_rotation_rows(
            self._item("汽车整车", 7, [("比亚迪股份", "01211")]), kit,
            rank_label=7, basket_seen=seen))
        self.assertIn("比亚迪股份 01211", other)
        self.assertNotIn(pipeline.SUB_MERGE_SAME_BASKET, other)

    def test_switch_off_restores_repeated_baskets(self):
        kit = pipeline.GUIZANG_KIT
        basket = [("腾讯控股", "00700"), ("快手-W", "01024")]
        rows = [_text(pipeline._sector_rotation_rows(
            self._item("AI应用", 2, basket), kit, rank_label=2, basket_seen=None)),
            _text(pipeline._sector_rotation_rows(
                self._item("AIGC概念", 3, basket), kit, rank_label=3, basket_seen=None))]
        self.assertIn("腾讯控股 00700", rows[1])
        self.assertNotIn(pipeline.SUB_MERGE_SAME_BASKET, rows[1])

    def test_single_stock_basket_never_gets_a_pointer(self):
        kit = pipeline.GUIZANG_KIT
        seen = {}
        rows = [_text(pipeline._sector_rotation_rows(
            self._item("概念A", 1, [("腾讯控股", "00700")]), kit, rank_label=1, basket_seen=seen)),
            _text(pipeline._sector_rotation_rows(
                self._item("概念B", 2, [("腾讯控股", "00700")]), kit, rank_label=2, basket_seen=seen))]
        self.assertIn("腾讯控股 00700", rows[1])   # 单只篮子照常显示，不做指针
        self.assertNotIn(pipeline.SUB_MERGE_SAME_BASKET, rows[1])


if __name__ == "__main__":
    unittest.main()
