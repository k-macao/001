"""「🎯 短线速查卡」（output/octopus_short.py）回归测试（全部离线）。

用户要求「内容再精炼，适合短线操作，入门观看」→ 日报末尾加一张 ≤600 字的行动速查卡。
本文件守的是整仓「防自欺」四条口径：
  · 确定性——同一份输入永远得到同一张卡（可复现，绝不随机跳变）；
  · 不伪造——数据缺失时对应行缺席，一行都没有时整卡缺席（返回 None）；
  · 同源——卡上每个数字都能在输入实参里逐字找到（不另算一套、不加戏）；
  · 诚实——字数超预算时按优先级**整行**撤下并留痕（dropped），绝不截断半句话；
    【新手三句话】读取 `output/stock_memes.json` 百句股票梗句库，按当次盘面与种子随时配对使用。

2026-10-16（用户要求「新手三句话，放在卦象后」）：三句话的配对逻辑不动，渲染位置
改到卷首「诗与远方的海」卦象之后——见 `BeginnerTipsPlacementTests` 一条条守住位置、
回落（卦象关闭时回卡尾）与「同一份日报只出现一处」。
"""
import datetime as dt
import importlib.util
import json
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

SHORT_PATH = Path(__file__).parents[1] / "output" / "octopus_short.py"
spec = importlib.util.spec_from_file_location("octopus_short_under_test", SHORT_PATH)
short = importlib.util.module_from_spec(spec)
spec.loader.exec_module(short)


def rich_ctx():
    """一份信息量充足的 ctx（数字全部是测试造的，断言围绕它们展开）。"""
    return {
        "date_str": "20260930",
        "today": dt.date(2026, 9, 30),
        "weekly": {
            "available": True,
            "entry": {"label": "■ 中性（略偏涨）", "p_up": 0.52, "target_sessions": 7,
                      "base_date": "2026-09-30"},
            "daily": {
                "base_date": "2026-09-30", "base_close": 24589, "symbol_label": "恒生指数",
                "rows": [
                    {"k": 1, "date": "2026-10-01", "weekday": "周四", "direction": "flat",
                     "label": "■ 中性（略偏跌）", "p_day": 0.46, "p_cum": 0.46,
                     "band_lo": 24342.0, "band_hi": 24836.0, "reason": "动量 5日 -1.0%",
                     "advice": {"stance": "谨慎偏空 · 减仓防守", "position": 15,
                                "stop_pct": 0.016, "stop_price": 24982.0,
                                "take_profit": 24836.0,
                                "entry_hint": "逢反弹至 24,836 一带减仓 / 对冲",
                                "notes": ["T+1 持有口径", "当天有 ★★★ ISM:PMI"]}},
                    {"k": 2, "date": "2026-10-02", "weekday": "周五", "direction": "flat",
                     "label": "■ 中性", "p_day": 0.52, "p_cum": 0.52,
                     "band_lo": 24240.0, "band_hi": 24938.0,
                     "advice": {"stance": "中性 · 观望为主", "position": 5,
                                "stop_pct": 0.022, "stop_price": 24048.0,
                                "take_profit": 24938.0, "notes": ["x", "y"]}},
                ],
            },
        },
        "quant": {
            "available": True,
            "target_label": "下一交易日 10-01（周四）",
            "headline": {"available": True, "label": "中性", "p_up": 0.50, "arrow": "■"},
            "liquidity": {
                "available": True, "score": 41, "label": "流动性偏紧",
                "south": {"available": True, "latest": 640.0, "z20": -1.78,
                          "pct60": 0.02, "date": "2026-09-29"},
            },
        },
        "ai": {
            "available": True, "sentiment_label": "中性", "score": 0, "confidence": "高",
            "quant_sectors": [
                {"name": "视频媒体", "chg": 6.06, "composite": 0.92},
                {"name": "医美耗材", "chg": 5.68, "composite": 0.84},
                {"name": "疫苗", "chg": 4.80, "composite": 0.80},
                {"name": "种子", "chg": 4.98, "composite": 0.78},
                {"name": "印制电路板", "chg": -4.35, "composite": -0.90},
                {"name": "集成电路封测", "chg": -3.90, "composite": -0.70},
                {"name": "元件", "chg": -3.81, "composite": -0.60},
                {"name": "半导体材料", "chg": -3.11, "composite": -0.55},
            ],
        },
        "pan": {"status": "success",
                "sectors": {"leading": [{"name": "视频媒体", "chg_pct": 6.06}],
                            "lagging": [{"name": "印制电路板", "chg_pct": -4.35}]}},
        "cal": {"status": "success", "items": [
            {"date": "2026-09-30", "time": "09:30", "city": "中国",
             "name": "非制造业PMI:商务活动", "imp": 3},
            {"date": "2026-09-30", "time": "20:30", "city": "美国",
             "name": "核心PCE物价指数:同比", "imp": 3},
            {"date": "2026-10-01", "time": "22:00", "city": "美国",
             "name": "ISM:PMI:制造业:季调", "imp": 3},
            {"date": "2026-10-02", "time": "20:30", "city": "美国",
             "name": "非农就业人数:季调", "imp": 3},
            {"date": "2026-10-28", "time": "02:00", "city": "华盛顿",
             "name": "美联储议息会议", "imp": 3},
        ]},
        "senti": {"available": True, "market_summary": {
            "available": True, "overall_dns": -0.02, "overall_label": "中性",
            "hottest": {"name": "纳斯达克100ETF", "score": 1.0, "key": "a"},
            "coldest": {"name": "亨通光电", "score": -1.0, "key": "b"}}},
        "coverage": {"today": 14, "total": 17},
    }


def visible_text(card):
    """卡片可见文字（去 HTML 标签），字数预算断言用。"""
    return short.card_char_count(card)


class CardDeterminismTests(unittest.TestCase):
    def test_same_input_same_card(self):
        ctx = rich_ctx()
        self.assertEqual(short.build_card(ctx), short.build_card(rich_ctx()))
        self.assertEqual(short.build_card(ctx)["text"], short.build_card(ctx)["text"])

    def test_card_does_not_depend_on_dict_order(self):
        ctx = rich_ctx()
        shuffled = {k: ctx[k] for k in reversed(list(ctx))}
        self.assertEqual(short.build_card(ctx)["text"], short.build_card(shuffled)["text"])


class CardBudgetTests(unittest.TestCase):
    def test_card_within_char_budget(self):
        card = short.build_card(rich_ctx())
        self.assertIsNotNone(card)
        self.assertLessEqual(visible_text(card), short.CARD_CHAR_BUDGET,
                             f"速查卡 {visible_text(card)} 字 > 预算 {short.CARD_CHAR_BUDGET}")

    def test_budget_is_600_by_default(self):
        self.assertEqual(short.CARD_CHAR_BUDGET, 600)

    def test_over_budget_drops_whole_lines_and_records_them(self):
        """预算压紧 → 按 DROP_ORDER 整行撤下并留痕；「明日剧本 / 数据底 / 小抄」永不撤。

        地板说明：小抄 + 明日剧本 + 数据底 + 定调这四行是「撤无可撤」的下限，
        预算再小也不会低于它（宁可如实超长，也不许砍掉明天怎么做）。
        """
        card = short.build_card(rich_ctx())
        keys = [label for label, _ in card["pairs"]]
        self.assertIn("明日剧本", " ".join(keys))
        self.assertLessEqual(visible_text(card), short.CARD_CHAR_BUDGET)
        with patch.object(short, "CARD_CHAR_BUDGET", 430):
            tight = short.build_card(rich_ctx())
        self.assertLessEqual(visible_text(tight), 430)
        self.assertTrue(tight["dropped"], "超预算必须留下撤行记录，不许静默丢")
        kept = " ".join(label for label, _ in tight["pairs"])
        self.assertIn("明日剧本", kept, "「明天怎么做」是最后一道，绝不先撤")
        self.assertIn("数据底", kept, "当天源 n/m 永不撤：数据不新鲜是最该先知道的事")
        # 撤下顺序必须是 DROP_ORDER：news 先走，week 最后走
        order = {k: i for i, k in enumerate(short.DROP_ORDER)}
        ranks = [order[k] for k in tight["dropped"] if k in order]
        self.assertEqual(ranks, sorted(ranks), f"撤行顺序不对：{tight['dropped']}")

    def test_no_half_sentence_truncation(self):
        """任何一行要么是完整的一句话，要么整行不在——不允许出现省略号截断。"""
        with patch.object(short, "CARD_CHAR_BUDGET", 300):
            card = short.build_card(rich_ctx())
        for _label, value in card["pairs"]:
            self.assertNotIn("…", value)


class CardHonestyTests(unittest.TestCase):
    def test_empty_ctx_returns_none(self):
        self.assertIsNone(short.build_card({}))
        self.assertIsNone(short.build_card(None))

    def test_line_absent_when_its_source_is_missing(self):
        ctx = rich_ctx()
        ctx["quant"] = {}                       # 量化缺席 → 水位行不出现
        ctx["senti"] = {}                       # 情绪缺席 → 风声行不出现
        ctx["cal"] = {}                         # 日程缺席 → 今明必看行不出现
        ctx["ai"] = {}                          # 策略缺席 → 板块行退化到全景兜底
        labels = " ".join(label for label, _ in short.build_card(ctx)["pairs"])
        self.assertNotIn("水位", labels)
        self.assertNotIn("风声", labels)
        self.assertNotIn("今明必看", labels)
        self.assertIn("明日剧本", labels)        # 周度引擎还在 → 主线不缺席

    def test_setup_absent_without_t1_row(self):
        ctx = rich_ctx()
        ctx["weekly"]["daily"]["rows"] = [ctx["weekly"]["daily"]["rows"][1]]   # 只剩 T+2
        self.assertIsNone(next((line for line in (short._line_setup(ctx),) if line), None))

    def test_setup_absent_when_only_one_number(self):
        ctx = rich_ctx()
        row = ctx["weekly"]["daily"]["rows"][0]
        row.update({"label": "", "p_day": None, "band_lo": None, "band_hi": None,
                    "advice": {}})
        self.assertIsNone(short._line_setup(ctx))

    def test_lead_admits_insufficient_data(self):
        ctx = rich_ctx()
        ctx["ai"] = {}
        ctx["quant"] = {}
        card = short.build_card(ctx)
        self.assertIn("不足以判断方向", card["lead"])

    def test_mustsee_only_covers_today_and_tomorrow(self):
        card = short.build_card(rich_ctx())
        mustsee = dict(card["pairs"])["⏰ 今明必看"]
        self.assertIn("09-30", mustsee)
        self.assertIn("10-01", mustsee)
        self.assertNotIn("10-28", mustsee, "远期日程不许冒充「今明」")
        self.assertNotIn("10-02", mustsee, "T+2 不是明天")

    def test_mustsee_without_base_date_is_absent(self):
        ctx = rich_ctx()
        ctx.pop("today")
        self.assertIsNone(short._line_mustsee(ctx))

    def test_mustsee_says_none_when_today_and_tomorrow_are_quiet(self):
        ctx = rich_ctx()
        ctx["cal"]["items"] = [it for it in ctx["cal"]["items"]
                               if it["date"] not in ("2026-09-30", "2026-10-01")]
        _key, (_label, text) = short._line_mustsee(ctx)
        self.assertIn("无 ★★ 以上", text)

    def test_strong_and_weak_are_never_mixed(self):
        """领跌板块绝不能出现在「强」那一堆（隐喻必须说真话）。"""
        ctx = rich_ctx()
        _key, (_label, text) = short._line_sector(ctx)
        strong, weak = text.split(" · 弱 ")
        for name in ("印制电路板", "集成电路封测", "元件", "半导体材料"):
            self.assertNotIn(name, strong, "领跌板块绝不能出现在「强」那一堆")
        self.assertIn("视频媒体", strong)
        self.assertIn("半导体材料", weak)
        # 强 / 弱各只取 3 个（完整榜单在「策略研判」栏目里，卡上不重复占字数）
        self.assertEqual(strong.count("、"), 2)
        self.assertEqual(weak.count("、"), 2)

    def test_sector_line_falls_back_to_panorama(self):
        ctx = rich_ctx()
        ctx["ai"] = {}
        _key, (_label, text) = short._line_sector(ctx)
        self.assertIn("视频媒体", text)
        self.assertIn("印制电路板", text)

    def test_sector_line_absent_without_any_source(self):
        ctx = rich_ctx()
        ctx["ai"] = {}
        ctx["pan"] = {}
        self.assertIsNone(short._line_sector(ctx))


class CardNumbersTraceableTests(unittest.TestCase):
    def test_every_number_comes_from_input(self):
        """卡上出现的每个数字都能在输入实参里逐字找到（同源，不另算一套）。"""
        ctx = rich_ctx()
        card = short.build_card(ctx)
        row = ctx["weekly"]["daily"]["rows"][0]
        adv = row["advice"]
        allowed = {
            "46", "52",                                   # T+1 概率 / 七日累计概率
            "24,342", "24,836",                           # T+1 80% 预期区间
            "15",                                          # 建议仓位
            "24,982",                                      # 止损价
            "50",                                          # 量化 headline 5 日概率
            "6.06", "5.68", "4.80", "3.90", "3.81", "3.11",      # 板块涨跌（负号另算）
            "41", "100", "640",                            # 流动性综合分 / 南向成交
            "0.02", "0",                                    # DNS / 策略信号 +0
            "5", "20", "22", "09", "00",                    # 「5 日」「20:30」「22:00」等碎片
            "14", "17",                                    # 当天源 / 总源
            "60", "3",                                     # 新手小抄里的固定阈值
            "09", "30", "10", "01", "09:30", "20:30", "22:00",   # 日期与时间
            "7",                                           # P(7日涨)
        }
        for token in re.findall(r"\d[\d,\.]*", card["text"]):
            bare = token.strip(".,")
            self.assertTrue(bare in allowed or bare.replace(",", "") in allowed,
                            f"卡上出现了无来源的数字：{token}")
        # 关键数字必须真的在（不是「碰巧没出现」）
        self.assertIn("24,342–24,836", card["text"])
        self.assertIn("24,982", card["text"])
        self.assertIn(f'≤{adv["position"]}%', card["text"])
        self.assertIn("41/100", card["text"])
        self.assertIn("640 亿", card["text"])
        self.assertIn("当天源 14/17", card["text"])

    def test_flow_label_reuses_quant_thresholds(self):
        """南向的「温和缩量」用量化包同一套阈值，不在卡里另写一份。"""
        ctx = rich_ctx()
        _key, (_label, text) = short._line_money(ctx)
        self.assertIn("温和缩量", text)
        self.assertIs(short._liquidity is not None, True)


class BeginnerTipsTests(unittest.TestCase):
    def test_meme_library_file_has_one_hundred_unique_stock_memes(self):
        """库文件（output/stock_memes.json）存在且正好包含 100 句不重复的股票梗句。"""
        lib_path = Path(short.MEME_LIB_PATH)
        self.assertTrue(lib_path.is_file(), f"未找到股票梗句库文件：{lib_path}")
        memes = short.load_meme_library(force=True)
        self.assertEqual(len(memes), 100)
        self.assertEqual(len(memes), short.MEME_LIBRARY_SIZE)
        self.assertEqual(len({m["id"] for m in memes}), 100)
        self.assertEqual(len({m["meme"] for m in memes}), 100)
        self.assertEqual(len({m["pair"] for m in memes}), 100)
        self.assertEqual(len({m["text"] for m in memes}), 100)
        digit_re = re.compile(r"[0-9０-９]")
        for m in memes:
            self.assertIn(m["slot"], ("direction", "stoploss", "discipline"))
            self.assertIn(m["label"], ("① 看方向", "② 放止损", "③ 别动手"))
            self.assertIn("——", m["text"])
            self.assertNotIn("…", m["text"])
            self.assertIsNone(digit_re.search(m["text"]),
                              f"梗句库不得伪造阿拉伯数字：{m['id']} {m['text']}")
            self.assertTrue(m["keywords"], f"{m['id']} 缺少配对关键词")
        # 三个槽位与九个子场景均有充足候选
        for slot, scenes in short.SLOT_SCENES.items():
            self.assertGreaterEqual(len(short.memes_by_slot(slot)), 30)
            for sc in scenes:
                self.assertGreaterEqual(len(short.memes_by_slot(slot, scene=sc)), 10,
                                        f"{slot}/{sc} 候选梗句不足")

    def test_tips_are_three_paired_lines_from_library(self):
        lib_texts = {m["text"] for m in short.load_meme_library()}
        card = short.build_card(rich_ctx())
        self.assertEqual(len(card["tips"]), 3)
        self.assertEqual([label for label, _ in card["tips"]],
                         ["① 看方向", "② 放止损", "③ 别动手"])
        for _label, text in card["tips"]:
            self.assertIn(text, lib_texts, f"卡片三句话必须来自百句股票梗库：{text}")

    def test_tips_pair_dynamically_with_market_state_and_date(self):
        """不同行情场景或不同日期会从百句库中配对出不同的股票梗句；同输入则严格一致。"""
        base = rich_ctx()
        bull = rich_ctx()
        bull["ai"]["score"] = 25
        bull["ai"]["sentiment_label"] = "偏多"
        bull["weekly"]["daily"]["rows"][0]["direction"] = "up"
        bull["weekly"]["daily"]["rows"][0]["p_day"] = 0.68
        bull["weekly"]["daily"]["rows"][0]["advice"]["position"] = 30
        bull["quant"]["liquidity"]["score"] = 72
        bull["cal"]["items"] = []

        bear = rich_ctx()
        bear["ai"]["score"] = -22
        bear["ai"]["sentiment_label"] = "偏空"
        bear["weekly"]["daily"]["rows"][0]["direction"] = "down"
        bear["weekly"]["daily"]["rows"][0]["p_day"] = 0.34
        bear["coverage"] = {"today": 8, "total": 18}

        self.assertEqual(short.infer_card_scenes(bull),
                         {"direction": "up", "stoploss": "volatile", "discipline": "wait"})
        self.assertEqual(short.infer_card_scenes(bear),
                         {"direction": "down", "stoploss": "defensive", "discipline": "missing"})
        self.assertEqual(short.infer_card_scenes(base),
                         {"direction": "flat", "stoploss": "defensive", "discipline": "event"})

        tips_base = short.build_card(base)["tips"]
        tips_bull = short.build_card(bull)["tips"]
        tips_bear = short.build_card(bear)["tips"]
        self.assertNotEqual(tips_base, tips_bull)
        self.assertNotEqual(tips_bull, tips_bear)
        self.assertNotEqual(tips_base, tips_bear)

        # 同一份数据无有效行情行时整卡仍然缺席
        minimal = rich_ctx()
        for key in ("ai", "quant", "cal", "senti", "pan", "weekly"):
            minimal[key] = {}
        minimal["coverage"] = {"today": 1, "total": 9}
        self.assertIsNone(short.build_card(minimal), "一行数据都没有 → 整卡缺席")

    def test_reads_custom_library_file_and_falls_back_when_missing(self):
        """支持读取自定义库文件；库文件缺失或损坏时回退 FALLBACK_BEGINNER_TIPS。"""
        custom_doc = {
            "memes": [
                {"id": "C1", "slot": "direction", "scene": "flat",
                 "meme": "自定义看方向梗", "pair": "先看概率方向再动手。"},
                {"id": "C2", "slot": "stoploss", "scene": "defensive",
                 "meme": "自定义放止损梗", "pair": "先挂好止损单保本金。"},
                {"id": "C3", "slot": "discipline", "scene": "event",
                 "meme": "自定义别动手梗", "pair": "遇到大事先场外观望。"},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            custom_path = Path(tmp) / "custom_memes.json"
            custom_path.write_text(json.dumps(custom_doc, ensure_ascii=False), encoding="utf-8")
            with patch.object(short, "MEME_LIB_PATH", str(custom_path)):
                card = short.build_card(rich_ctx())
            self.assertEqual(card["tips"], [
                ("① 看方向", "自定义看方向梗——先看概率方向再动手。"),
                ("② 放止损", "自定义放止损梗——先挂好止损单保本金。"),
                ("③ 别动手", "自定义别动手梗——遇到大事先场外观望。"),
            ])
            missing_path = Path(tmp) / "nonexistent.json"
            with patch.object(short, "MEME_LIB_PATH", str(missing_path)):
                fallback_card = short.build_card(rich_ctx())
            self.assertEqual(fallback_card["tips"], list(short.FALLBACK_BEGINNER_TIPS))

    def test_on_demand_pairing_by_slot_scene_keyword_and_cross_pair(self):
        """随时配对使用：支持按槽位、场景、关键词检索配对，以及上下句交叉配对。"""
        m_up = short.pair_stock_meme("up", slot="direction", seed="s1")
        self.assertEqual(m_up["slot"], "direction")
        self.assertEqual(m_up["scene"], "up")
        m_kw = short.pair_stock_meme(keyword="鳄鱼法则", seed="s2")
        self.assertIn("鳄鱼法则", m_kw["meme"])
        m_cross = short.pair_stock_meme("up", slot="direction", seed="s3", cross_pair=True)
        self.assertNotEqual(m_cross["id"], m_cross["pair_id"])
        self.assertIn("——", m_cross["text"])
        batch = short.pair_memes(5, slot="stoploss", seed="batch")
        self.assertEqual(len(batch), 5)
        self.assertEqual(len({x["id"] for x in batch}), 5)

    def test_tips_survive_tight_budget(self):
        expected = short.pair_beginner_tips(rich_ctx())
        with patch.object(short, "CARD_CHAR_BUDGET", 260):
            card = short.build_card(rich_ctx())
        self.assertEqual(card["tips"], expected,
                         "字数再紧也不能把新手三句话撤掉")

    def test_tips_mention_direction_stop_loss_and_no_go_conditions(self):
        for seed in ("20260930", "20261001", "20261002", "bull", "bear"):
            tips = short.pair_beginner_tips(rich_ctx(), seed=seed)
            blob = "".join(text for _label, text in tips)
            self.assertIn("方向", blob)
            self.assertIn("止损", blob)
            self.assertIn("观望", blob)


def pipeline_report_data(pipeline):
    """整链渲染用的一份真实结构数据（各测试类共用；数字来自测试夹具，全程离线）。"""
    import test_weekly as tw
    from test_quant import run_engine
    import test_pipeline as tp
    data = tp.SectionReadingOrderTests()._full_data()
    data["A股大盘全景"] = tp.MarketPanoramaTests()._panorama_payload()
    data["每周走势预测"] = tw.WeeklyPipelineIntegrationTests()._source()
    with tempfile.TemporaryDirectory() as tmp:
        data["港股量化"] = pipeline._source_result(
            "港股量化引擎", "success", is_today=True, content_date="2026-08-02",
            result=run_engine(tmpdir=tmp, n_stocks=12))
    cal = tp.EconCalendarTests()
    res, _ = cal._fetch()
    data["财经日历"] = res
    return data


class CardRenderingTests(unittest.TestCase):
    """整链（pipeline）层面的断言：卡片位置、两主题、开关、字数。"""

    @classmethod
    def setUpClass(cls):
        import pipeline
        cls.pipeline = pipeline

    def _data(self):
        return pipeline_report_data(self.pipeline)

    def test_card_closes_report_after_analysis_data_and_conclusion(self):
        data = self._data()
        for kit in (self.pipeline.GUIZANG_KIT, self.pipeline.PIXEL_KIT):
            sections = self.pipeline._collect_report_parts(data, kit,
                                                           date_str="20260802")["sections"]
            self.assertNotEqual(sections[0][0], "AI DIGEST")
            self.assertIn(sections[0][0], self.pipeline.REPORT_SECTION_ORDER)
            self.assertEqual(sections[-1][0], "SHORT CARD")
            self.assertEqual(sections[-1][1], self.pipeline.SECTION_TITLE_SHORT_CARD)
            titles = [section[1] for section in sections]
            # 2026-10-14 重排：行情复盘（①）先于策略研判（④）
            self.assertLess(titles.index(self.pipeline.SECTION_TITLE_MARKET_REVIEW),
                            titles.index(self.pipeline.SECTION_TITLE_STRATEGY))
            self.assertLess(titles.index(self.pipeline.SECTION_TITLE_MARKET_REVIEW),
                            titles.index("总结"))
            # 2026-10-13：今日预判置顶，总结仍在速查卡之前
            self.assertLess(titles.index(self.pipeline.SECTION_TITLE_FORECAST),
                            titles.index(self.pipeline.SECTION_TITLE_STRATEGY))
            self.assertLess(titles.index("总结"), titles.index(self.pipeline.SECTION_TITLE_SHORT_CARD))
        for theme in ("guizang", "pixel"):
            html = self.pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802",
                                                theme=theme)
            self.assertIn(self.pipeline.SECTION_TITLE_SHORT_CARD, html)
            self.assertLess(html.index(self.pipeline.SECTION_TITLE_FORECAST),
                            html.index(sections[1][1]))
            self.assertLess(html.index("总结<"),
                            html.index(self.pipeline.SECTION_TITLE_SHORT_CARD),
                            f"{theme} 速查卡必须作为结论后的收尾")
            # 2026-10-16：三句话移到卷首卦象之后，仍在日报里，但不在速查卡内部
            self.assertIn("新手三句话", html)
            self.assertLess(html.index("新手三句话"),
                            html.index(self.pipeline.SECTION_TITLE_SHORT_CARD),
                            f"{theme} 三句话必须排在速查卡之前（卷首卦象之后）")

    def test_card_text_stays_within_budget_in_full_report(self):
        data = self._data()
        sections = self.pipeline._collect_report_parts(data, self.pipeline.GUIZANG_KIT,
                                                       date_str="20260802")["sections"]
        card_html = next(section[2] for section in sections if section[0] == "SHORT CARD")
        text = re.sub(r"<[^>]+>", "", card_html)
        self.assertLessEqual(len(text), short.CARD_CHAR_BUDGET + 40,
                             f"渲染后的速查卡 {len(text)} 字，超出预算太多")

    def test_full_flag_removes_card_and_restores_long_form(self):
        data = self._data()
        with patch.object(self.pipeline, "LITE_ENABLED", False):
            self.pipeline._quant.render.LITE = False
            try:
                sections = self.pipeline._collect_report_parts(
                    data, self.pipeline.GUIZANG_KIT, date_str="20260802")["sections"]
                html = self.pipeline.generate_report(
                    data, "2026年8月2日 · 周日", "20260802", theme="guizang")
            finally:
                self.pipeline._quant.render.LITE = True
        self.assertNotIn("SHORT CARD", [s[0] for s in sections])
        self.assertNotIn(self.pipeline.SECTION_TITLE_SHORT_CARD, html)
        self.assertNotEqual(sections[0][0], "AI DIGEST")
        # 全量长版：日程逐日表与逐日走势表回来（校准曲线随量化分析总览于 2026-10-23 下线）
        self.assertIn("逐日时间点（北京时间）", html)
        self.assertIn("逐日表格", html)

    def test_lite_mode_collapses_long_form_and_discloses(self):
        data = self._data()
        with self.pipeline.notes_mode():          # 精简 + 说明文字（--notes）
            html = self.pipeline.generate_report(
                data, "2026年8月2日 · 周日", "20260802", theme="guizang")
        # 方法论长注折叠成一句，但结论与概率数字仍在
        # （「模型自检」随量化分析总览于 2026-10-23 下线，概率仍在逐日推演里）
        self.assertIn("P(7日涨)", html)
        self.assertIn("无未来函数口径", html)
        self.assertIn("先存档后结算", html)
        # 日程只列近端，并如实披露折叠条数
        self.assertIn("今明 + 近端 ★★★ 时间点（北京时间）", html)
        self.assertIn("精简版面", html)

    def test_plain_mode_keeps_conclusions_and_drops_methodology(self):
        """Guizang 入门版：结论与自检数字在，口径 / 折叠披露 / 重复免责不出。"""
        data = self._data()
        html = self.pipeline.generate_report(
            data, "2026年8月2日 · 周日", "20260802", theme="guizang")
        self.assertIn("P(7日涨)", html)
        self.assertIn("今明 + 近端 ★★★ 时间点（北京时间）", html)
        self.assertIn(self.pipeline.SECTION_TITLE_SHORT_CARD, html)
        self.assertIn(short.CAPTION_PLAIN, html)
        self.assertIn(short.TIPS_TITLE_PLAIN, html)
        for text in ("无未来函数口径", "先存档后结算", "精简版面", "--full 看全文",
                     "数字与下文各栏同源", "百句股票梗库", "规则合成 · 大白话翻译"):
            self.assertNotIn(text, html, text)

    def test_card_absent_when_no_data_at_all(self):
        html = self.pipeline.generate_report({}, "2026年8月2日 · 周日", "20260802")
        self.assertNotIn(self.pipeline.SECTION_TITLE_SHORT_CARD, html,
                         "一行数据都没有时整卡必须缺席，不许硬编文案占位")

    def test_guizang_report_still_fits_one_push_message(self):
        data = self._data()
        html = self.pipeline.generate_report(
            data, "2026年8月2日 · 周日", "20260802", theme="guizang")
        self.assertLess(len(html), self.pipeline.PUSHPLUS_MAX_CONTENT_CHARS)
        parts = self.pipeline._split_html_for_push(
            html, self.pipeline.PUSHPLUS_MAX_CONTENT_CHARS)
        self.assertEqual(len(parts or []), 1)

    def test_card_html_no_longer_carries_beginner_tips(self):
        """2026-10-16：三句话搬到卷首后，速查卡正文里不该再出现同一句话。"""
        data = self._data()
        sections = self.pipeline._collect_report_parts(
            data, self.pipeline.GUIZANG_KIT, date_str="20260802")["sections"]
        card_html = next(section[2] for section in sections if section[0] == "SHORT CARD")
        self.assertNotIn("新手三句话", card_html)
        self.assertNotIn("① 看方向", card_html)


class BeginnerTipsPlacementTests(unittest.TestCase):
    """🐣【新手三句话】2026-10-16 改位：紧跟卷首卦象之后（用户要求「放在卦象后」）。

    守四件事：
      · 位置——每个推送主题里，三句话都排在「今日八卦运程与利忌」之后、正文之前；
      · 唯一——同一份日报只出现一处，速查卡里不再重复一遍；
      · 回落——OCTOPUS_BAGUA=0 / 起卦失败时，三句话回到速查卡末尾，内容不丢；
      · 预算——移出卡片后不再占速查卡字数预算（口径跟实际渲染一致，见
        `octopus_short.build_card(tips_in_card=)`）。
    """

    @classmethod
    def setUpClass(cls):
        import pipeline
        cls.pipeline = pipeline

    def _data(self):
        return pipeline_report_data(self.pipeline)

    def test_tips_right_after_bagua_in_every_push_theme(self):
        data = self._data()
        for theme in self.pipeline.PUSH_THEMES:
            with self.subTest(theme=theme):
                html = self.pipeline.generate_report(
                    data, "2026年8月2日 · 周日", "20260802", theme=theme)
                self.assertEqual(html.count("新手三句话"), 1,
                                 f"{theme}: 三句话整篇只能出现一处")
                self.assertLess(html.index("今日八卦运程与利忌"),
                                html.index("新手三句话"),
                                f"{theme}: 三句话必须排在卦象之后")
                self.assertLess(html.index("新手三句话"),
                                html.index(self.pipeline.SECTION_TITLE_FORECAST),
                                f"{theme}: 三句话必须在正文（今日预判）之前")
                self.assertLess(html.index("新手三句话"),
                                html.index(self.pipeline.SECTION_TITLE_SHORT_CARD),
                                f"{theme}: 三句话不在速查卡里")

    def test_opening_section_carries_tips_with_bagua(self):
        data = self._data()
        parts = self.pipeline._collect_report_parts(
            data, self.pipeline.GUIZANG_KIT, date_str="20260802")
        opening = self.pipeline._poetry_sea_section(parts, self.pipeline.GUIZANG_KIT)
        self.assertIn(short.TIPS_TITLE_PLAIN, opening)
        self.assertLess(opening.index("今日八卦运程与利忌"),
                        opening.index(short.TIPS_TITLE_PLAIN))
        for label in ("① 看方向", "② 放止损", "③ 别动手"):
            self.assertIn(label, opening, label)

    def test_tips_fall_back_to_card_tail_when_bagua_disabled(self):
        import octopus_bagua as bagua
        data = self._data()
        with patch.object(bagua, "ENABLED", False):
            html = self.pipeline.generate_report(
                data, "2026年8月2日 · 周日", "20260802", theme="guizang")
        self.assertNotIn("今日八卦运程与利忌", html)
        self.assertEqual(html.count("新手三句话"), 1, "回落后也只能出现一处")
        self.assertLess(html.index(self.pipeline.SECTION_TITLE_SHORT_CARD),
                        html.index("新手三句话"), "卦象关闭时三句话回到速查卡末尾")

    def test_tips_absent_in_full_long_form(self):
        """--full / OCTOPUS_LITE=0：与改位前一致，速查卡与三句话都整块不出。"""
        data = self._data()
        with patch.object(self.pipeline, "LITE_ENABLED", False):
            self.pipeline._quant.render.LITE = False
            try:
                html = self.pipeline.generate_report(
                    data, "2026年8月2日 · 周日", "20260802", theme="guizang")
            finally:
                self.pipeline._quant.render.LITE = True
        self.assertNotIn(self.pipeline.SECTION_TITLE_SHORT_CARD, html)
        self.assertNotIn("新手三句话", html)

    def test_card_budget_follows_render_position(self):
        """三句话移出卡片后不再占字数预算；两处共用同一组配对结果。"""
        ctx = rich_ctx()
        in_card = short.build_card(ctx, tips_in_card=True)     # 默认：向后兼容
        moved = short.build_card(ctx, tips_in_card=False)      # 改位后：卷首渲染
        self.assertEqual(in_card["tips"], moved["tips"], "两处必须是同一组三句话")
        first_tip = in_card["tips"][0][1]
        self.assertIn(first_tip, in_card["text"])
        self.assertNotIn(first_tip, moved["text"])
        self.assertLessEqual(len(moved["text"]), len(in_card["text"]))


if __name__ == "__main__":
    unittest.main()
