"""「🦑 AI帮你提鲜」（output/octopus_ren.py，原名鲜鲜解读）回归测试（全部离线）。

防自欺口径与整仓一致：
  · 确定性——同一份输入永远得到同一份解读（可复现，绝不随机跳变）；
  · 不伪造——数据缺失 / available=False 时必须返回空串，该栏目自动缺席；
  · 同源——解读引用的数字与正文（⌁ AI 研判 / 总结）来自同一批实参；
  · 诚实——概率接近 50% 时解读必须出现「抛硬币」级措辞，不得夸大把握。
"""
import importlib.util
import sys
import types
import unittest
import unittest.mock
from pathlib import Path

sys.modules.setdefault("requests", types.SimpleNamespace())

REN_PATH = Path(__file__).parents[1] / "output" / "octopus_ren.py"
spec = importlib.util.spec_from_file_location("octopus_ren_under_test", REN_PATH)
ren = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ren)

ALL_KICKERS = (
    "STRATEGY READ", "UZI TREND", "HK PROBABILITY", "LIQUIDITY FLOW",
    "WEEKLY FORECAST", "POLICY SHOCK", "FED TREND", "GEO TREND", "ECON CALENDAR",
    "MARKET REVIEW", "RETAIL SENTIMENT", "MEDIA RISK", "TREND TRACKING",
    "SECTOR ROTATION", "INDUSTRY ROTATION", "GLOBAL HEADLINES", "EASTMONEY WIRE",
    "HK GURU CHANNELS", "NEWS SENTIMENT", "HK 7D PROB", "SUMMARY", "FORECAST",
)


def uzi_result():
    """一份【游资剑鱼】多专家流派趋势分析的 run_trend() 结果（数字均为测试造的）。

    键与 output/octopus_quant/uzi_trend.py 的真实返回一一对应：coverage / panel /
    rules_enabled / rules_total / tones / items（含 tone_key + tone + score_avg）/
    dropped（被准入门禁撤下的评委）/ missing（没拿到合格日线的标的）。
    """
    return {
        "available": True, "reason": None,
        "engine": {"version": "v3.9.4", "investors_total": 66, "rules_total": 242,
                   "panel": ["利弗莫尔", "米内尔维尼", "达瓦斯", "江恩", "西蒙斯"]},
        "items": [
            {"available": True, "label": "恒生指数", "code": "^HSI", "as_of": "2026-09-29",
             "tone_key": "up", "tone": "多头趋势成立",
             "tone_detail": "Stage 2 上升 · 4/5 位评委看多",
             "score_avg": 18.4, "bullish_n": 4, "bearish_n": 1, "neutral_n": 0,
             "panel": [{"id": "livermore", "name": "利弗莫尔", "score": 22.0,
                        "signal": "bullish"}],
             "dropped": {}},
            {"available": True, "label": "腾讯控股", "code": "0700.HK", "as_of": "2026-09-29",
             "tone_key": "base", "tone": "底部构筑",
             "tone_detail": "Stage 1 底部 · 看多 2 / 看空 2",
             "score_avg": 6.1, "bullish_n": 2, "bearish_n": 2, "neutral_n": 1,
             "panel": [{"id": "darvas", "name": "达瓦斯", "score": 6.1, "signal": "neutral"}],
             "dropped": {"江恩": "可评估 1/4 条（权重 3/17 = 18%）"}},
        ],
        "missing": [{"label": "恒生科技", "code": "^HSTECH",
                     "reason": "本次没有可用已收盘日线"}],
        "coverage": {"valid": 2, "total": 3},
        "as_of": "2026-09-29", "latest_as_of": "2026-09-29",
        "rules_enabled": 14, "rules_total": 242,
        "dropped": {"江恩": "可评估 1/4 条（权重 3/17 = 18%）"},
        "panel": {"investors": 5, "bullish": 6, "bearish": 3, "neutral": 1,
                  "avg_score": 12.3},
        "tones": {"up": 1, "mixed": 0, "base": 1, "top": 0, "down": 0, "unknown": 0},
    }


def rich_ctx():
    """一份信息量充足的 ctx（数字均为测试造的数据，断言围绕它们展开）。"""
    return {
        "date_str": "20260929",
        "notes": {},
        "market": {"status": "success", "quotes": {}},
        "pan": {
            "status": "success",
            "breadth": {"up": 3525, "down": 1944, "mood": "偏多震荡", "ratio": 1.81},
            "turnover": {"total": 14217.23, "chg_pct": -17.19},
            "sectors": {"leading": [{"name": "燃料电池", "chg_pct": 7.73}]},
        },
        "policy": {"available": True, "broad_score": -9, "broad_label": "偏冷",
                   "winners": [{"name": "银行"}], "losers": [{"name": "地产链"}]},
        "ai": {"available": True, "sentiment_label": "中性", "score": 7,
               "confidence": "高", "themes": ["AI/算力", "新能源/锂电"]},
        "retail_sentiment": {
            "available": True, "bull": 12, "bear": 8, "directional_n": 20,
            "nbi": 20.0, "label": "偏多", "dispersion": 97.1,
        },
        "media_risk": {
            "available": True, "window_hours": 72, "risk_stock_n": 2,
            "risk_event_n": 1, "attention_evidence_n": 3,
            "stocks": [{"name": "测试股份"}, {"name": "样本控股"}],
            "top_stock": {"name": "测试股份", "risk_index": 64,
                          "level": {"label": "橙色预警"}, "attention_only": False},
        },
        "sector_rotation": {
            "concept_total": 10, "mapped_total": 4, "scored_total": 2,
            "items": [
                {"name": "AI应用", "overall_score": 76.5, "score_label": "靠前",
                 "strategy_summary": {"available_n": 3, "consensus": "偏多"}},
                {"name": "机器人", "overall_score": 61.0, "score_label": "中游",
                 "strategy_summary": {"available_n": 2, "consensus": "中性"}},
            ],
        },
        "industry_rotation": {
            "available": True, "scored_count": 31,
            "breadth": {"total": 31, "up_week": 19, "above_ma20": 18, "avg_week": 0.0123},
            "scores": [{"name": "电子", "score": 71.2}],
            "state": {"holdings": [{"name": name} for name in
                                    ("电子", "通信", "银行", "汽车", "医药生物")]},
        },
        "uzi": uzi_result(),
        "quant": {
            "available": True,
            "headline": {"available": True, "label": "中性", "p_up": 0.52, "arrow": "■"},
            "target_label": "下一交易日 09-30（周三）",
            "validation": {1: {"hit_rate": 0.519, "base_rate": 0.508, "n": 185, "z": 0.51}},
            "stocks": [
                {"label": "汇丰控股", "probs": {5: {"p_up": 0.63}}},
                {"label": "小米集团-W", "probs": {5: {"p_up": 0.36}}},
                {"label": "腾讯控股", "probs": {5: {"p_up": 0.52}}},
            ],
            "breadth": {"available": True, "score": 24},
            "liquidity": {
                "available": True,
                "summary": "流动性偏紧（综合分 45/100）",
                "score": 45, "label": "流动性偏紧",
                "south": {"available": True, "latest": 640, "pct60": 0.02},
            },
        },
        "weekly": {"available": True,
                   "entry": {"p_up": 0.53, "label": "中性（略偏涨）", "target_sessions": 5}},
        "hk7": {},
        "fed": {"available": True, "verdict": "偏鹰（紧缩倾向）",
                "positive_label": "鸽派（宽松）", "negative_label": "鹰派（紧缩）",
                "positive_n": 0, "negative_n": 7, "total": 8},
        "geo": {"available": True, "verdict": "升温（对抗）",
                "positive_label": "缓和（降温）", "negative_label": "升温（对抗）",
                "positive_n": 1, "negative_n": 5, "total": 8},
        "senti": {"available": True, "total_matched": 12,
                  "market_summary": {"overall_dns": 0.10, "overall_label": "中性",
                                     "hottest": {"name": "纳指ETF", "key": "qqq"},
                                     "coldest": {"name": "亨通光电", "key": "htgd"},
                                     "most_covered": {"name": "英伟达", "total": 25}}},
        "cal": {"status": "success",
                "window": "2026-09-29 ~ 2026-10-29 · 未来 30 天",
                "items": [
                    {"date": "2026-10-28", "time": "02:00", "imp": 3, "kind": 1,
                     "name": "美联储议息会议"},
                    {"date": "2026-10-14", "time": "09:30", "imp": 3, "kind": 0,
                     "name": "CPI:同比/环比"},
                    {"date": "2026-10-14", "time": "09:30", "imp": 3, "kind": 0,
                     "name": "PPI:全部工业品:同比"},
                    {"date": "2026-10-02", "time": "20:30", "imp": 3, "kind": 0,
                     "name": "非农就业人数:季调"},
                ]},
        "yt": {"channels": [{"is_today": True, "videos": [{"title": "a"}]},
                            {"is_today": False, "videos": [{"title": "b"}]}]},
        "google": {"status": "success",
                   "headlines": [{"title": "新型电池产业迎重磅利好"}, {"title": "AI 模型突破"}]},
        "em": {"status": "success",
               "headlines": [{"title": "红塔证券首次回购股份"}, {"title": "长盈通签订订单"}]},
        "trend": {"platforms": ["Reddit", "StockTwits"], "samples": 33,
                  "bull": 8, "bear": 30,
                  "news_an": {"scanned": 94, "hk_n": 31, "total": 20, "themes": ["AI/科技"]}},
        "coverage": {"today": 15, "total": 18, "missing": ["每日量化策略（行业轮动）"]},
    }


class DeterminismTests(unittest.TestCase):
    def test_same_input_same_output(self):
        """可复现：同一 ctx 重复调用，结果逐字一致（绝不随机）。"""
        ctx = rich_ctx()
        for kicker in ALL_KICKERS:
            first = ren.section_ren(kicker, ctx)
            second = ren.section_ren(kicker, ctx)
            self.assertEqual(first, second, kicker)

    def test_day_seed_changes_wording_pool_only(self):
        """隔天措辞从池里换花样，但数字口径不变（53% 还是 53%，绝不变造数字）。"""
        ctx_a, ctx_b = rich_ctx(), dict(rich_ctx(), date_str="20260930")
        for ctx in (ctx_a, ctx_b):
            self.assertIn("53%", ren.section_ren("WEEKLY FORECAST", ctx))
        # 2026-10-23 用户要求：今日预判不展示涨跌概率 → 两个日期都不出现任何百分比概率
        for ctx in (ctx_a, ctx_b):
            text = ren.section_ren("FORECAST", ctx)
            self.assertIn("方向定调", text)
            self.assertNotIn("%", text)


class NoFabricationTests(unittest.TestCase):
    def test_empty_ctx_returns_empty_for_every_section(self):
        """数据缺失 → 空串（生成器不硬编；实际有正文时由渲染层给诚实后备结论）。"""
        for kicker in ALL_KICKERS:
            self.assertEqual(ren.section_ren(kicker, {}), "", kicker)
            self.assertEqual(ren.section_ren(kicker, {"date_str": "20260101"}), "", kicker)

    def test_unavailable_results_return_empty(self):
        """available=False / status!=success 时整行缺席，绝不用旧数据充数。"""
        ctx = rich_ctx()
        for key in ("policy", "ai", "uzi", "weekly", "fed", "geo", "senti"):
            broken = dict(ctx, **{key: {"available": False}})
            if key == "weekly":
                # WEEKLY FORECAST now combines weekly output and HK probability analysis;
                # make both inputs unavailable to verify the combined interpretation is absent.
                broken["quant"] = {"available": False}
            kicker = {"policy": "POLICY SHOCK", "ai": "STRATEGY READ",
                      "uzi": "UZI TREND",
                      "weekly": "WEEKLY FORECAST",
                      "fed": "FED TREND", "geo": "GEO TREND",
                      "senti": "NEWS SENTIMENT"}[key]
            self.assertEqual(ren.section_ren(kicker, broken), "", kicker)
        broken = dict(ctx, cal={"status": "failed", "items": []})
        self.assertEqual(ren.section_ren("ECON CALENDAR", broken), "")
        broken = dict(ctx, pan={"status": "failed"}, market={"status": "failed"})
        self.assertEqual(ren.section_ren("MARKET REVIEW", broken), "")
        self.assertEqual(ren.section_ren(
            "RETAIL SENTIMENT", dict(ctx, retail_sentiment={"available": False})), "")
        self.assertEqual(ren.section_ren(
            "MEDIA RISK", dict(ctx, media_risk={"available": False})), "")
        self.assertEqual(ren.section_ren(
            "SECTOR ROTATION", dict(ctx, sector_rotation={})), "")
        self.assertEqual(ren.section_ren(
            "INDUSTRY ROTATION", dict(ctx, industry_rotation={"available": False})), "")

    def test_strategy_uses_macd_fallback_without_inventing_cross_market_signal(self):
        ctx = rich_ctx()
        ctx["ai"] = {"available": False}
        ctx["macd"] = {
            "available": True, "coverage": {"valid": 3, "total": 4},
            "items": [{"action_key": "hold"}, {"action_key": "watch"},
                      {"action_key": "exit"}],
        }
        text = ren.section_ren("STRATEGY READ", ctx)
        self.assertIn("只解读已有 MACD", text)
        self.assertIn("有效 3/4", text)
        self.assertIn("试探 0 / 持有 1 / 观察 1 / 规避 1", text)
        self.assertNotIn("中性", text)

    def test_unknown_kicker_returns_empty(self):
        self.assertEqual(ren.section_ren("NOT A KICKER", rich_ctx()), "")

    def test_numbers_come_from_input_only(self):
        """解读引用的概率 / 命中率 / 分数必须能在输入里找到（防凭空造数）。"""
        ctx = rich_ctx()
        cases = {
            # 2026-10-23 起今日预判只翻译方向与信号，不再出现涨跌概率
            "FORECAST": ["方向定调", "+7"],
            "HK PROBABILITY": ["63%", "36%", "24"],
            "LIQUIDITY FLOW": ["640", "45/100"],
            "UZI TREND": ["3 只里 2 只", "5 位方法评委按 14 条规则", "评委库 66 位 / 242 条规则",
                          "看多 6 / 看空 3 / 中性 1", "均分 12.3"],
            "WEEKLY FORECAST": ["53%"],
            "POLICY SHOCK": ["-9"],
            "FED TREND": ["命中 7 次", "8 条"],
            "GEO TREND": ["命中 5 次"],
            "RETAIL SENTIMENT": ["20 条", "看多 12", "看空 8", "+20.0", "97.1/100"],
            "MEDIA RISK": ["72 小时", "2 只", "1 条", "3 条", "64/100"],
            "TREND TRACKING": ["33", "94", "31", "20 家"],
            "SECTOR ROTATION": ["2 个", "AI应用", "76.5/100", "3 套"],
            "INDUSTRY ROTATION": ["31 个", "19 个", "+1.23%", "71.2/100"],
            "SUMMARY": ["15", "18"],
        }
        for kicker, tokens in cases.items():
            text = ren.section_ren(kicker, ctx)
            self.assertTrue(text, kicker)
            for token in tokens:
                self.assertIn(token, text, f"{kicker} 缺少输入数字 {token}")

    def test_coin_probability_wording_is_honest(self):
        """概率 45%~55% 区间必须出现「抛硬币 / 五五开」级措辞，不许吹成稳了。"""
        for p in (46, 50, 52, 54):
            tone = ren._coin_tone(p, "20260929")
            self.assertTrue(any(w in tone for w in ("抛硬币", "五五开", "神仙", "氛围")), tone)

    def test_forecast_never_shows_updown_probability(self):
        """2026-10-23 用户要求：【回游金枪鱼】今日预判不显示涨跌概率。"""
        ctx = rich_ctx()
        # 周度 label 真实形态自带「· P(7日涨) 53%」：翻译层必须把概率剥掉，只留方向。
        ctx["weekly"] = {"available": True, "entry": {
            "p_up": 0.53, "target_sessions": 7,
            "label": "■ 中性（略偏涨）· P(7日涨) 53%"}}
        text = ren.section_ren("FORECAST", ctx)
        self.assertTrue(text)
        self.assertIn("中性（略偏涨）", text)
        for word in ("概率", "几率", "P(", "%"):
            self.assertNotIn(word, text)
        block = ren.section_ren_block("FORECAST", ctx)
        self.assertIsNone(block["p_pct"])       # 几率条整条缺席


class ContentTests(unittest.TestCase):
    def test_rich_ctx_every_section_has_text(self):
        ctx = rich_ctx()
        # HK 7D PROB 只在配置大模型（hk7.available）时出现：未配置 → 空，绝不硬编。
        self.assertEqual(ren.section_ren("HK 7D PROB", ctx), "")
        for kicker in ALL_KICKERS:
            if kicker == "HK 7D PROB":
                continue
            self.assertTrue(ren.section_ren(kicker, ctx), kicker)

    def test_hk7_ren_only_when_available(self):
        ctx = rich_ctx()
        ctx["hk7"] = {"available": True, "engine": "llm",
                      "targets": [{"label": "恒生指数", "p_up": 0.57},
                                  {"label": "恒生科技", "p_up": 0.49}]}
        text = ren.section_ren("HK 7D PROB", ctx)
        self.assertIn("57%", text)
        self.assertIn("49%", text)
        self.assertIn("大模型研判", text)
        degraded = dict(ctx, hk7={"available": True, "engine": "quant_base",
                                  "targets": [{"label": "恒生指数", "p_up": 0.55}]})
        self.assertIn("量化基准", ren.section_ren("HK 7D PROB", degraded))

    def test_meme_flavor_present(self):
        ctx = rich_ctx()
        self.assertIn("开盲盒", ren.section_ren("ECON CALENDAR", ctx))
        self.assertIn("紧箍咒", ren.section_ren("FED TREND", ctx))
        self.assertIn("吃瓜", ren.section_ren("GEO TREND", ctx))
        self.assertIn("显眼包", ren.section_ren("GEO TREND", ctx))
        self.assertIn("热帖和头条", ren.section_ren("TREND TRACKING", ctx))
        self.assertIn("后视镜", ren.section_ren("NEWS SENTIMENT", ctx))
        self.assertIn("非投资建议", ren.section_ren("SUMMARY", ctx) + ren.DISCLAIMER)



class UziTrendRenTests(unittest.TestCase):
    """【游资剑鱼】多专家流派趋势分析的「AI帮你提鲜」（2026-10-13 接入）。

    防自欺口径与该栏正文一致：解读只引用 run_trend() 结果里已有的数字与 items 自带的
    tone 文案；本栏没有概率口径 → 几率条整条缺席（绝不硬凑一个涨跌概率）。
    """

    def test_text_only_quotes_numbers_from_the_result(self):
        text = ren._ren_uzi_trend(rich_ctx())
        for token in ("观察池 3 只里 2 只这次算出了结果",
                      "5 位方法评委按 14 条规则投票",
                      "评委库 66 位 / 242 条规则",
                      "看多 6 / 看空 3 / 中性 1",
                      "均分 12.3",
                      "多头趋势成立 1 只",
                      "底部构筑 1 只",
                      "最高分：恒生指数（均分 18.4 · 多头趋势成立）",
                      "1 位评委没过准入门禁被整位撤下（江恩）",
                      "恒生科技这次没算出来，整只缺席，不拿旧数据顶",
                      "非投资建议"):
            self.assertIn(token, text)

    def test_tone_wording_is_taken_from_items_not_retranslated(self):
        """定调用语直接取 items 的 tone（与正文同一套 _verdict 口径，不另写翻译）。"""
        ctx = rich_ctx()
        uzi = dict(ctx["uzi"],
                   items=[dict(row, tone="测试定调文案") for row in ctx["uzi"]["items"]])
        self.assertIn("测试定调文案", ren._ren_uzi_trend(dict(ctx, uzi=uzi)))

    def test_dropped_judges_are_named_not_smoothed_over(self):
        """被门禁撤下的评委如实点名，并说清「不是弃权，是缺数据」。"""
        ctx = rich_ctx()
        text = ren._ren_uzi_trend(ctx)
        self.assertIn("江恩", text)
        self.assertIn("不是弃权，是真的缺数据", text)
        many = dict(ctx["uzi"], dropped={"江恩": "r1", "西蒙斯": "r2", "达瓦斯": "r3"})
        text = ren._ren_uzi_trend(dict(ctx, uzi=many))
        self.assertIn("3 位评委没过准入门禁被整位撤下（江恩、西蒙斯等）", text)

    def test_unavailable_or_empty_items_returns_empty(self):
        ctx = rich_ctx()
        for broken in ({"available": False}, {"available": True, "items": []}, {}):
            self.assertEqual(ren._ren_uzi_trend(dict(ctx, uzi=broken)), "")
        self.assertEqual(ren._ren_uzi_trend(dict(ctx, uzi=None)), "")

    def test_no_odds_meter_because_the_column_has_no_probability(self):
        """本栏没有概率 → label / p_pct 都是 None，渲染层跳过几率条（不造新数字）。"""
        block = ren.section_ren_block("UZI TREND", rich_ctx())
        self.assertIsNotNone(block)
        self.assertIsNone(block["p_pct"])
        self.assertIsNone(block["label"])

    def test_garnish_reads_the_same_result_object(self):
        """活鲜度点缀与解读读同一份对象；本栏是「本次现算」的分析栏 → 计活鲜。"""
        ctx = rich_ctx()
        self.assertIs(ren._garnish_obj("UZI TREND", ctx), ctx["uzi"])
        self.assertTrue(ren._garnish_available(ctx["uzi"]))
        self.assertTrue(ren._garnish_is_today("UZI TREND", ctx["uzi"]))
        self.assertIn("🦐", ren.section_ren("UZI TREND", ctx))

    def test_wording_follows_the_vote_but_never_gives_advice(self):
        ctx = rich_ctx()
        bearish = dict(ctx["uzi"], panel=dict(ctx["uzi"]["panel"], bullish=1, bearish=9))
        text = ren._ren_uzi_trend(dict(ctx, uzi=bearish))
        self.assertTrue(any(w in text for w in ("空头票更多", "看空票占上风")), text)
        neutral = dict(ctx["uzi"], panel=dict(ctx["uzi"]["panel"],
                                              bullish=0, bearish=0, neutral=5))
        self.assertIn("全是中性票", ren._ren_uzi_trend(dict(ctx, uzi=neutral)))
        tied = dict(ctx["uzi"], panel=dict(ctx["uzi"]["panel"], bullish=4, bearish=4))
        text = ren._ren_uzi_trend(dict(ctx, uzi=tied))
        self.assertTrue(any(w in text for w in ("多空打平", "五五开的评审团")), text)
        for sample in (bearish, neutral, tied):
            self.assertIn("非投资建议", ren._ren_uzi_trend(dict(ctx, uzi=sample)))

    def test_day_seed_changes_wording_but_not_numbers(self):
        """隔天换措辞，数字口径不变（均分 12.3 还是 12.3）。"""
        ctx_a, ctx_b = rich_ctx(), dict(rich_ctx(), date_str="20260930")
        for ctx in (ctx_a, ctx_b):
            text = ren._ren_uzi_trend(ctx)
            self.assertIn("均分 12.3", text)
            self.assertIn("看多 6 / 看空 3 / 中性 1", text)
        self.assertEqual(ren.section_ren("UZI TREND", ctx_a),
                         ren.section_ren("UZI TREND", ctx_a))


class FreshMeterTests(unittest.TestCase):
    """2026-10-06 改版：涨跌几率条字符图（▓/░）+ 更名「AI帮你提鲜」。"""

    def test_title_constant(self):
        """改名只认 REN_TITLE 一处出口：页面 / 测试 / 文档统一口径。"""
        self.assertEqual(ren.REN_TITLE, "AI帮你提鲜")

    def test_fresh_meter_rounding_and_bounds(self):
        """概率 → 格数半进位取整、越界夹紧；▓+░ 恒等于 10 格，不凭空多格。"""
        cases = {0: (0, 10), 5: (1, 9), 25: (3, 7), 45: (5, 5), 52: (5, 5),
                 55: (6, 4), 62: (6, 4), 95: (10, 0), 100: (10, 0)}
        for p, (filled, empty) in cases.items():
            m = ren.fresh_meter(p)
            self.assertEqual((m["filled"], m["empty"]), (filled, empty), p)
            self.assertEqual(len(m["bar"]), 10, p)
            self.assertEqual(m["bar"], "▓" * filled + "░" * empty, p)
        # 越界 / 非法输入：绝不硬画一条，直接 None（渲染层整条几率条缺席）
        self.assertIsNone(ren.fresh_meter(None))
        self.assertIsNone(ren.fresh_meter("52%"))
        self.assertIsNone(ren.fresh_meter(120))
        self.assertIsNone(ren.fresh_meter(-5))

    def test_fresh_meter_odds_no_new_numbers(self):
        """几率「涨 52 ： 48 跌」只是同一概率的重新排版，不引入新数字。"""
        m = ren.fresh_meter(52.0)
        self.assertEqual(m["odds"], "涨 52 ： 48 跌")
        m = ren.fresh_meter(62.3)
        self.assertEqual(m["odds"], "涨 62 ： 38 跌")   # 62.3% → 62 : 38（同源四舍五入）

    def test_section_ren_block_meta_same_source(self):
        """整块数据：text 与 section_ren 一字不差；label/p_pct 与 ⌁AI研判同源取数。"""
        ctx = rich_ctx()
        block = ren.section_ren_block("WEEKLY FORECAST", ctx)
        self.assertIsNotNone(block)
        self.assertEqual(block["text"], ren.section_ren("WEEKLY FORECAST", ctx))
        self.assertEqual(block["label"], "中性（略偏涨）")   # weekly.entry.label 同源
        self.assertAlmostEqual(block["p_pct"], 53.0)        # 0.53 → 53.0，不另算一套

    def test_section_ren_block_empty_when_no_data(self):
        """数据缺失 → None（调用方就不加块），绝不硬编。"""
        self.assertIsNone(ren.section_ren_block("NOT A KICKER", rich_ctx()))
        self.assertIsNone(ren.section_ren_block("FORECAST", {}))
        self.assertIsNone(ren.section_ren_block("HK 7D PROB", rich_ctx()))

    def test_section_ren_block_meta_optional(self):
        """栏目没有研判概率 → p_pct=None（几率条缺席），正文照常。"""
        ctx = rich_ctx()
        ctx["notes"] = {}
        # SUMMARY 走 coverage，不带方向概率
        block = ren.section_ren_block("SUMMARY", ctx)
        self.assertIsNotNone(block)
        self.assertTrue(block["text"])
        self.assertIsNone(block["p_pct"])
        self.assertIsNone(block["label"])



class PipelineIntegrationTests(unittest.TestCase):
    """走完整的 generate_report（离线合成数据），验证两主题都会挂上「AI帮你提鲜」块。"""

    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("requests", types.SimpleNamespace())
        pipeline_path = Path(__file__).parents[1] / "output" / "pipeline.py"
        spec = importlib.util.spec_from_file_location(
            "pipeline_for_ren_test", pipeline_path)
        cls.pipeline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.pipeline)

    @staticmethod
    def _data():
        p = PipelineIntegrationTests.pipeline
        return {
            "实时行情": p._source_result(
                "test quote", "success",
                quotes={
                    "上证指数": {"price": 3830.45, "change_pct": 0.18, "currency": "CNY",
                                "as_of": "2026-09-29"},
                    "恒生指数": {"price": 24523.57, "change_pct": -0.48, "currency": "HKD",
                                "as_of": "2026-09-29"},
                },
                is_today=True),
            "全球头条": p._source_result(
                "test news", "success",
                headlines=[{"title": "新型电池产业迎重磅利好，长寿命锂电池突破",
                            "source": "测试源", "published_cst": "2026-09-29 10:00"}],
                content_date="2026-09-29", is_today=True),
            "东财快讯": p._source_result(
                "test wire", "success",
                headlines=[{"title": "红塔证券首次回购股份103万股",
                            "time": "2026-09-29 18:10"}],
                content_date="2026-09-29", is_today=True),
            "港股名家频道": p._source_result(
                "test yt", "success", channels=[],
                content_date="2026-09-29", is_today=True),
        }

    def test_guizang_and_pixel_both_render_ren_rows(self):
        for theme in ("guizang", "pixel"):
            html = self.pipeline.generate_report(
                self._data(), "2026年9月29日 · 周二", "20260929", theme=theme)
            self.assertIn(ren.REN_TITLE, html, theme)
            self.assertIn("🦑", html, theme)
            self.assertIn("AI帮你提鲜", html, theme)
            # 入门版（默认）：每栏重复的免责副行不出，全篇只在页脚保留一句
            self.assertNotIn(ren.DISCLAIMER, html, theme)
            with self.pipeline.notes_mode():
                html = self.pipeline.generate_report(
                    self._data(), "2026年9月29日 · 周二", "20260929", theme=theme)
            self.assertIn(ren.REN_TITLE, html, theme)
            self.assertIn(ren.DISCLAIMER, html, theme)

    def test_ren_disabled_by_flag(self):
        with unittest.mock.patch.object(self.pipeline, "REN_ENABLED", False):
            html = self.pipeline.generate_report(
                self._data(), "2026年9月29日 · 周二", "20260929")
        self.assertNotIn(ren.REN_TITLE, html)
        self.assertNotIn("鲜鲜解读", html)
        self.assertNotIn("🦑", html)

    def test_ren_numbers_match_body(self):
        """解读行里的数字必须来自正文同源数据（这里验证实时行情涨跌家数）。"""
        html = self.pipeline.generate_report(
            self._data(), "2026年9月29日 · 周二", "20260929")
        self.assertIn("0.18", html)          # 上证 +0.18% 与正文同源
        self.assertIn("1 涨 / 1 跌", html)  # 报价面计数进入解读

    def test_every_rendered_data_section_starts_with_conclusion(self):
        """五套主题的每个实际数据栏目（含速查卡）都必须先结论、后依据与正文。"""
        parts = None
        kits = (self.pipeline.GUIZANG_KIT, self.pipeline.PIXEL_KIT,
                self.pipeline.LIME_KIT, self.pipeline.FORUM_KIT,
                self.pipeline.DOSSIER_KIT)
        for kit in kits:
            with self.subTest(theme=kit.theme):
                themed = self.pipeline._collect_report_parts(
                    self._data(), kit, date_str="20260929")
                self.assertTrue(themed["sections"])
                for kicker, _title, content, _badge, _caption in themed["sections"]:
                    self.assertIn(
                        self.pipeline.SECTION_AI_CONCLUSION_MARKER, content[:500],
                        f"{kicker} 没有把栏首结论放在正文第一位",
                    )
                parts = parts or themed

        market = next(content for kicker, _title, content, _badge, _caption
                      in parts["sections"] if kicker == "MARKET REVIEW")
        self.assertLess(market.find("AI帮你提鲜"), market.find("⌁ AI 研判"))
        self.assertLess(market.find("⌁ AI 研判"), market.find("上证指数"))
        # 旧研判在大白话结论后只保留数据依据，不再重复概率或「→ 预测」结论。
        self.assertIn("数据依据", market)
        self.assertNotRegex(market, r"多头 \d+%|空头 \d+%")
        self.assertNotIn("→ 预测：", market)

    def test_ren_block_char_art_and_odds_meter(self):
        """2026-10-06 改版：独立内容区 + 字符图头 + 概率 / 几率条（两主题都出）。"""
        for theme in ("guizang", "pixel"):
            html = self.pipeline.generate_report(
                self._data(), "2026年9月29日 · 周二", "20260929", theme=theme)
            self.assertIn("AI帮你提鲜", html, theme)
            # 字符图：头部渐变条 + 几率条（▓ 涨 / ░ 跌）都真实上页
            self.assertIn("█▓▒░", html, theme)
            self.assertIn("░▒▓█", html, theme)
            self.assertIn("▓", html, theme)
            self.assertIn("░", html, theme)
            # 概率 / 几率口径（报价面 note 同源，绝不另算一套数字）
            self.assertIn("上涨概率", html, theme)
            self.assertRegex(html, r"几率 涨 \d+ ： \d+ 跌", theme)
            # 独立内容区域：块标题与大白话正文同块出现
            self.assertIn("大白话", html, theme)

    def test_uzi_column_carries_its_own_ren_block(self):
        """【游资剑鱼】的解读走 ctx["uzi"]（该栏正文渲染另由 tests/test_uzi_trend.py 覆盖，
        这里把正文渲染打桩，只验解读块确实挂进了这一栏）。"""
        p = self.pipeline
        data = self._data()
        data[p.UZI_TREND_SOURCE_NAME] = p._source_result(
            p.UZI_TREND_SOURCE_LABEL, "success", result=uzi_result(),
            content_date="2026-09-29", is_today=True)
        stub = "<p>UZI 正文（测试桩）</p>"
        with unittest.mock.patch.object(p, "_render_uzi_trend", return_value=stub):
            html = p.generate_report(data, "2026年9月29日 · 周二", "20260929")
        self.assertIn(p.SECTION_TITLE_UZI_TREND, html)
        self.assertIn(stub, html)
        self.assertIn("趋势评审团：", html)
        self.assertIn("观察池 3 只里 2 只这次算出了结果", html)
        self.assertIn("最高分：恒生指数（均分 18.4 · 多头趋势成立）", html)

    def test_uzi_ren_disappears_when_the_column_is_absent(self):
        """栏目缺席 → 解读也缺席，不留一句硬编的大白话。"""
        p = self.pipeline
        data = self._data()
        data[p.UZI_TREND_SOURCE_NAME] = p._source_result(
            p.UZI_TREND_SOURCE_LABEL, "unavailable", result=None,
            error="MACD 栏目本次没有可用已收盘日线")
        html = p.generate_report(data, "2026年9月29日 · 周二", "20260929")
        self.assertNotIn(p.SECTION_TITLE_UZI_TREND, html)
        self.assertNotIn("趋势评审团：", html)


if __name__ == "__main__":
    unittest.main()
