"""内地财经热点榜标题词汇分析回归（本地 jieba，无网络请求）。"""
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


if __name__ == "__main__":
    unittest.main()
