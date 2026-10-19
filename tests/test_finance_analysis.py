"""【沸腾花蛤】情绪热点因子量化分析（原内地财经热点榜）标题分析回归（本地 jieba，无网络请求）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
if str(OUTPUT) not in sys.path:
    sys.path.insert(0, str(OUTPUT))

import finance_analysis as finance  # noqa: E402


class FinanceVocabularyTests(unittest.TestCase):
    def test_extracts_domain_terms_and_filters_numbers_and_boilerplate(self):
        terms = finance.extract_finance_vocabulary(
            "今日公司称：AI算力与半导体芯片受关注，2026年新增订单300亿元"
        )
        self.assertIn("AI", terms)
        self.assertTrue(any(term in terms for term in ("算力", "半导体", "芯片")))
        self.assertNotIn("今日", terms)
        self.assertNotIn("公司", terms)
        self.assertFalse(any(term.isdigit() for term in terms))

    def test_title_terms_are_unique_and_ascii_aliases_normalize(self):
        terms = finance.extract_finance_vocabulary("AI AI算力算力 ai芯片")
        self.assertEqual(terms.count("AI"), 1)
        self.assertEqual(terms.count("算力"), 1)
        self.assertIn("芯片", terms)

    def test_summary_counts_titles_and_distinct_media_not_raw_occurrences(self):
        headlines = [
            {"title": "AI算力半导体", "source": "媒体甲",
             "finance_analysis": {"vocabulary_terms": ["AI", "AI", "算力", "半导体"]}},
            {"title": "AI芯片", "source": "媒体乙",
             "finance_analysis": {"vocabulary_terms": ["AI", "芯片"]}},
            {"title": "AI算力", "source": "媒体甲",
             "finance_analysis": {"vocabulary_terms": ["AI", "算力"]}},
            {"title": "无效空标题", "source": "媒体丙", "finance_analysis": {}},
            {"source": "媒体丙"},
        ]
        summary = finance.summarize_hotlist_vocabulary(headlines)
        self.assertTrue(summary["has_data"])
        self.assertEqual(summary["total_titles"], 4)
        terms = {item["term"]: item for item in summary["top_terms"]}
        self.assertEqual(terms["AI"]["title_count"], 3)
        self.assertEqual(terms["AI"]["media_count"], 2)
        self.assertEqual(terms["算力"]["title_count"], 2)
        self.assertEqual(terms["算力"]["media_count"], 1)
        self.assertEqual(terms["半导体"]["title_count"], 1)
        self.assertEqual(terms["芯片"]["title_count"], 1)

    def test_summary_is_deterministic_and_has_no_fake_probabilities(self):
        headlines = [
            {"title": "AI算力与大模型", "source": "媒体甲"},
            {"title": "半导体芯片与AI", "source": "媒体乙"},
        ]
        first = finance.summarize_hotlist_vocabulary(headlines)
        second = finance.summarize_hotlist_vocabulary(headlines)
        self.assertEqual(first, second)
        self.assertEqual(first["method"], "jieba 本地分词 + 财经停用词表")
        self.assertEqual(first["counting_unit"], "标题级去重")
        self.assertNotIn("positive_probability", first)
        self.assertNotIn("negative_probability", first)

    def test_empty_and_unusable_headlines_are_reported_as_no_vocabulary(self):
        self.assertFalse(finance.summarize_hotlist_vocabulary([])["has_data"])
        summary = finance.summarize_hotlist_vocabulary([{"title": "。。。。", "source": "媒体甲"}])
        self.assertEqual(summary["total_titles"], 1)
        self.assertFalse(summary["has_data"])
        self.assertEqual(summary["top_terms"], [])

    def test_analyze_item_exposes_vocabulary_terms_from_title_only(self):
        result = finance.analyze_finance_item(
            "证监会发布人工智能产业政策", "正文另提黄金与原油价格变化"
        )
        self.assertIn("vocabulary_terms", result)
        self.assertTrue(result["vocabulary_terms"])
        self.assertIn("证监会", result["vocabulary_terms"])
        self.assertNotIn("黄金", result["vocabulary_terms"])
        self.assertNotIn("原油", result["vocabulary_terms"])
        # Compatibility scores exist, but the hotlist summary never presents them as calibrated odds.
        self.assertEqual(result["positive_probability"] + result["negative_probability"], 100)

    def test_summary_ignores_cached_terms_not_present_in_the_title(self):
        summary = finance.summarize_hotlist_vocabulary([{
            "title": "AI算力需求增长", "source": "媒体甲",
            "finance_analysis": {"vocabulary_terms": ["黄金", "原油"]},
        }])
        terms = {item["term"] for item in summary["top_terms"]}
        self.assertIn("AI", terms)
        self.assertIn("算力", terms)
        self.assertNotIn("黄金", terms)
        self.assertNotIn("原油", terms)


class SentimentHotspotRiskTests(unittest.TestCase):
    """2026-10-19 情绪热点因子三件套：情绪总览 / 热点聚合 / 预警风险点。"""

    def test_match_risk_keywords_hits_categories_in_lexicon_order(self):
        hits = finance.match_risk_keywords("证监会对某公司立案调查，股价跌停")
        cats = [c for c, _ in hits]
        kws = [k for _, k in hits]
        self.assertIn("立案", kws)
        self.assertIn("调查", kws)
        self.assertIn("跌停", kws)
        self.assertEqual(cats[0], "监管与合规风险", "按词表顺序返回")
        self.assertIn("市场波动风险", cats)

    def test_match_risk_keywords_is_empty_for_benign_title(self):
        self.assertEqual(finance.match_risk_keywords("白酒板块逆市拉升，多股涨停"), [])
        self.assertEqual(finance.match_risk_keywords(""), [])

    def test_title_mood_collapses_dictionary_classes(self):
        self.assertEqual(finance.title_mood("重大利好：政策红利大力支持新能源")["label"],
                         finance.MOOD_POSITIVE)
        self.assertEqual(finance.title_mood("某公司暴雷退市，股价暴跌")["label"],
                         finance.MOOD_NEGATIVE)
        self.assertEqual(finance.title_mood("央行召开工作会议")["label"],
                         finance.MOOD_NEUTRAL)

    def test_sentiment_summary_counts_are_deterministic_and_honest(self):
        headlines = [{"title": "重大利好政策红利", "source": "甲"},
                     {"title": "公司暴雷退市", "source": "乙"},
                     {"title": "央行召开会议", "source": "甲"}]
        a = finance.aggregate_hotlist_sentiment(headlines)
        b = finance.aggregate_hotlist_sentiment(headlines)
        self.assertEqual(a, b)
        self.assertTrue(a["has_data"])
        self.assertEqual(a["total_titles"], 3)
        self.assertEqual(a["pos_n"] + a["neu_n"] + a["neg_n"], 3)
        self.assertIn("非校准概率", a["note"])
        self.assertNotIn("positive_probability", a)
        empty = finance.aggregate_hotlist_sentiment([])
        self.assertFalse(empty["has_data"])
        self.assertIsNone(empty["avg_score"])
        self.assertIsNone(empty["label"])

    def test_hotspots_aggregate_same_term_titles_with_mood_and_risk(self):
        headlines = [
            {"title": "AI算力芯片需求大增", "source": "甲",
             "url": "u1", "published_cst": "2026-10-13 05:00"},
            {"title": "AI大模型芯片出口遭制裁", "source": "乙",
             "url": "u2", "published_cst": "2026-10-13 06:00"},
            {"title": "白酒消费回暖", "source": "丙",
             "url": "u3", "published_cst": "2026-10-13 04:00"},
        ]
        first = finance.aggregate_hotlist_hotspots(headlines)
        second = finance.aggregate_hotlist_hotspots(headlines)
        self.assertEqual(first, second, "热点聚合必须确定性可复现")
        self.assertTrue(first["has_data"])
        clusters = {c["term"]: c for c in first["clusters"]}
        self.assertIn("AI", clusters)
        ai = clusters["AI"]
        self.assertEqual(ai["title_count"], 2)
        self.assertEqual(ai["media_count"], 2)
        self.assertTrue(ai["aggregated"], "≥2 条同题 = 聚合热点")
        self.assertIn("外部冲击风险", ai["risk_categories"], "「制裁」要标注到簇上")
        self.assertEqual(ai["pos_n"] + ai["neu_n"] + ai["neg_n"], ai["title_count"])
        self.assertEqual(ai["samples"][0]["published_cst"], "2026-10-13 06:00",
                         "样例标题按时间倒序")
        self.assertGreaterEqual(first["aggregated_n"], 1)

    def test_risk_points_level_rule_and_evidence(self):
        headlines = [
            {"title": "某公司被立案调查", "source": "甲",
             "url": "u1", "published_cst": "2026-10-13 01:00"},
            {"title": "另一公司违规被处罚", "source": "乙",
             "url": "u2", "published_cst": "2026-10-13 02:00"},
            {"title": "第三家公司遭约谈整改", "source": "甲",
             "url": "u3", "published_cst": "2026-10-13 03:00"},
        ]
        rep = finance.analyze_hotlist_risks(headlines)
        self.assertTrue(rep["has_data"])
        self.assertEqual(rep["hit_n"], 3)
        self.assertEqual(rep["total_titles"], 3)
        top = rep["points"][0]
        self.assertEqual(top["category"], "监管与合规风险")
        self.assertEqual(top["count"], 3)
        self.assertEqual(top["media_n"], 2)
        self.assertEqual(top["level"], finance.RISK_LEVEL_HIGH, "≥3 条且 ≥2 家 → 高")
        self.assertEqual(len(top["samples"]), 2)
        self.assertEqual(top["samples"][0]["published_cst"], "2026-10-13 03:00",
                         "证据标题最新在前")
        self.assertIn("约谈", top["samples"][0]["matched"])
        again = finance.analyze_hotlist_risks(headlines)
        self.assertEqual(rep, again, "预警风险点必须确定性可复现")

    def test_risk_title_counted_once_per_category(self):
        headlines = [{"title": "公司被立案调查并处罚", "source": "甲"}]
        rep = finance.analyze_hotlist_risks(headlines)
        self.assertEqual(rep["hit_n"], 1)
        top = rep["points"][0]
        self.assertEqual(top["count"], 1, "同一标题命中同类多个词只算 1 条")
        self.assertEqual(top["level"], finance.RISK_LEVEL_WATCH)

    def test_risk_report_is_empty_when_no_hits(self):
        rep = finance.analyze_hotlist_risks([{"title": "白酒板块逆市拉升", "source": "甲"}])
        self.assertFalse(rep["has_data"])
        self.assertEqual(rep["hit_n"], 0)
        self.assertEqual(rep["points"], [])
        self.assertEqual(rep["total_titles"], 1)


if __name__ == "__main__":
    unittest.main()
