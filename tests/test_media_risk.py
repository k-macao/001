"""A/H 媒体舆情风险点：事件抽取、权威度、时点护栏、热度基线与五主题渲染。"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# pipeline 导入时只要求 requests 模块存在；本文件全部离线。
sys.modules.setdefault("requests", types.SimpleNamespace())
ROOT = Path(__file__).parents[1]
OUTPUT = ROOT / "output"
if str(OUTPUT) not in sys.path:
    sys.path.insert(0, str(OUTPUT))

spec = importlib.util.spec_from_file_location("pipeline_media_risk_test", OUTPUT / "pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)
media_risk = pipeline._media_risk


class MediaRiskRuleTests(unittest.TestCase):
    def test_user_facing_section_name_is_warning_blowfish(self):
        self.assertEqual(
            pipeline.SECTION_TITLE_MEDIA_RISK,
            "【警戒爆炸豚】媒体舆情风险点量化分析",
        )

    def test_specific_event_taxonomy_and_generic_risk_not_overmatched(self):
        event = media_risk.classify_title(
            "公司收到证监会立案调查通知，审计报告为无法表示意见")
        self.assertIsNotNone(event)
        self.assertEqual(event["severity"], 4)
        self.assertEqual({c["category"] for c in event["categories"]},
                         {"合规与监管", "财务与审计"})
        self.assertIn("立案调查", event["hits"])
        self.assertIn("无法表示意见", event["hits"])
        # 不用“风险/调查/亏损”等过宽单词兜底，避免标题级误报。
        self.assertIsNone(media_risk.classify_title("公司提示市场波动风险，经营一切正常"))
        self.assertIsNone(media_risk.classify_title("机构开展行业例行调查"))

    def test_remaining_required_categories_are_detected(self):
        cases = {
            "控股股东高比例质押，董事长失联": "治理与股东",
            "实控人变更、董监高变动且核心人员离职": "治理与股东",
            "一致行动人解约，核心技术人员离职": "治理与股东",
            "核心供应商供应中断，重大订单取消并发生核心客户流失": "经营与供应链",
            "行业政策急转、补贴退坡并实施出口管制": "行业与政策",
            "公司暂停交易并出现流动性危机": "交易与流动性",
            "公司被实施退市风险警示且资产遭司法冻结": "合规与监管",
            "应收账款异常、存货异常、现金流紧张并出现利润调节疑点": "财务与审计",
            "舆情发酵、异常成交量且换手率异常": "异常关注",
        }
        for title, category in cases.items():
            with self.subTest(category=category):
                event = media_risk.classify_title(title)
                self.assertIsNotNone(event)
                self.assertIn(category, {row["category"] for row in event["categories"]})

    def test_level_four_red_line_terms_are_covered(self):
        for phrase in ("监管立案", "监管调查", "财务造假", "无法表示意见",
                       "强制措施", "退市预警"):
            with self.subTest(phrase=phrase):
                event = media_risk.classify_title(f"测试股份触发{phrase}")
                self.assertIsNotNone(event)
                self.assertEqual(event["severity"], 4)

    def test_specific_english_headline_phrases_are_case_insensitive(self):
        event = media_risk.classify_title(
            "Company Faces REGULATORY INVESTIGATION and AUDITOR RESIGNATION")
        self.assertIsNotNone(event)
        self.assertEqual({row["category"] for row in event["categories"]},
                         {"合规与监管", "财务与审计"})

    def test_denial_or_resolution_context_is_kept_but_downgraded(self):
        direct = media_risk.classify_title("测试股份被立案调查")
        denied = media_risk.classify_title("测试股份澄清未被立案调查，传闻不实")
        self.assertFalse(direct["disputed"])
        self.assertTrue(denied["disputed"])
        self.assertLess(denied["severity"], direct["severity"])

    def test_source_weight_changes_the_same_event_score(self):
        universe = [{"market": "A股", "code": "600001", "name": "测试股份",
                     "key": "A股:600001"}]

        def attribute(_title, _universe):
            return [{**universe[0], "tag": "name"}]

        base = {"title": "测试股份收到监管问询函", "section": "全球头条",
                "ts": "2026-08-02 09:00", "date": "2026-08-02"}
        official = media_risk.analyze(
            [{**base, "source": "中国证监会"}], universe, attribute, {}, "20260802")
        commentary = media_risk.analyze(
            [{**base, "source": "某财经博主", "section": "港股名家频道"}],
            universe, attribute, {}, "20260802")
        self.assertGreater(official["stocks"][0]["risk_index"],
                           commentary["stocks"][0]["risk_index"])

    def test_volume_baseline_does_not_borrow_samples_older_than_30_days(self):
        history = {"stocks": {"A股:600001": {"days": {
            "20260801": {"total": 1}, "20260731": {"total": 1},
            "20260730": {"total": 1}, "20260729": {"total": 1},
            "20260601": {"total": 99},
        }}}}
        rows = media_risk._history_prior_totals(history, "A股:600001", "20260802")
        self.assertEqual(rows, [1.0, 1.0, 1.0, 1.0])
        self.assertFalse(media_risk._volume_anomaly(4, rows)["enough"])

    def test_attention_three_times_mean_is_abnormal_even_when_z_below_two(self):
        metric = media_risk._volume_anomaly(12, [0, 10, 0, 10, 0])
        self.assertLess(metric["z"], 2)
        self.assertEqual(metric["multiple"], 3.0)
        self.assertTrue(metric["triple_mean"])
        self.assertTrue(metric["abnormal"])
        self.assertEqual(metric["label"], "达到均值3倍")

    def test_zero_attention_mean_does_not_fabricate_a_baseline_multiple(self):
        metric = media_risk._volume_anomaly(3, [0, 0, 0, 0, 0])
        self.assertIsNone(metric["multiple"])
        self.assertFalse(metric["triple_mean"])
        self.assertTrue(metric["abnormal"])
        self.assertEqual(metric["label"], "极端突增")

    def test_event_lifecycle_is_deterministic_and_time_aware(self):
        self.assertEqual(media_risk._event_status(
            "公司被立案调查", "2026-08-02", "2026-08-02"), "Current")
        self.assertEqual(media_risk._event_status(
            "公司或将收到监管问询", "2026-08-02", "2026-08-02"), "Emerging")
        self.assertEqual(media_risk._event_status(
            "回顾公司被立案调查", "2026-07-31", "2026-08-02"), "Historical")
        self.assertEqual(media_risk._event_status(
            "讨论量突增", "2026-08-02", "2026-08-02", signal_type="attention"),
            "Emerging")

    def test_price_rise_without_negative_sentiment_is_not_bearish_divergence(self):
        universe = [{"market": "A股", "code": "600001", "name": "测试股份",
                     "key": "A股:600001"}]

        def attribute(_title, _universe):
            return [{**universe[0], "tag": "name"}]

        result = media_risk.analyze(
            [{"title": "测试股份收到监管问询函", "source": "财联社",
              "section": "内地财经媒体", "ts": "2026-08-02 09:00",
              "date": "2026-08-02", "url": "https://example.com/no-divergence"}],
            universe, attribute, {}, "20260802",
            prices={"A股:600001": 3.0},
            sentiment_scores={"A股:600001": {"score": 0.3, "sample_n": 1}},
            as_of="2026-08-02 23:59:59")
        stock = result["stocks"][0]
        self.assertEqual(stock["score_components"]["bearish_divergence_bonus"], 0.0)
        self.assertFalse(stock["agent_payload"]["sentiment_metrics"]["bearish_divergence"])
        self.assertIn("不判空头背离", stock["divergence"])

    def test_english_entity_alignment_is_case_insensitive_without_ai_substrings(self):
        universe = [
            {"market": "港股", "code": "00700", "name": "腾讯控股", "key": "港股:00700"},
            {"market": "A股", "code": "688981", "name": "中芯国际", "key": "A股:688981"},
        ]
        matched = pipeline._attribute_headline("TENCENT faces a probe", universe)
        self.assertEqual([item["key"] for item in matched], ["港股:00700"])
        self.assertEqual(pipeline._attribute_headline("chairman detained", universe), [])

    def test_ticker_normalization_is_market_aware_and_idempotent(self):
        self.assertEqual(media_risk._ticker("A股", "600001"), "600001.SH")
        self.assertEqual(media_risk._ticker("A股", "000001"), "000001.SZ")
        self.assertEqual(media_risk._ticker("A股", "920001"), "920001.BJ")
        self.assertEqual(media_risk._ticker("港股", "700"), "00700.HK")
        self.assertEqual(media_risk._ticker("港股", "00700.HK"), "00700.HK")

    def test_source_authority_layers(self):
        official = media_risk.source_authority({"source": "中国证监会"})
        authority = media_risk.source_authority({"source": "新华社"})
        professional = media_risk.source_authority({"source": "财联社"})
        company_filing = media_risk.source_authority(
            {"source": "发行人", "section": "公司公告"})
        commentary = media_risk.source_authority(
            {"source": "某财经博主", "section": "港股名家频道"})
        self.assertEqual(official["tier"], "官方/监管")
        self.assertEqual(company_filing["tier"], "官方/监管")
        self.assertGreater(official["weight"], authority["weight"])
        self.assertGreater(authority["weight"], professional["weight"])
        self.assertGreater(professional["weight"], commentary["weight"])


class MediaRiskPipelineTests(unittest.TestCase):
    DATE = "20260802"
    ISO_DATE = "2026-08-02"

    def _data(self, headlines=None):
        return {
            "热门榜单": pipeline._source_result(
                "东方财富热门榜", "success", is_today=True,
                content_date=self.ISO_DATE,
                markets={
                    "A股": {"stocks": [
                        {"code": "600001", "name": "测试股份", "change_pct": 3.20,
                         "price": 10.0, "amount": 100},
                        {"code": "688981", "name": "中芯国际", "change_pct": 0.40,
                         "price": 80.0, "amount": 90},
                    ]},
                    "港股": {"stocks": [
                        {"code": "00700", "name": "腾讯控股", "change_pct": -2.50,
                         "price": 500.0, "amount": 80},
                    ]},
                    "美股": {"stocks": [
                        {"code": "NVDA", "name": "英伟达", "change_pct": -4.00,
                         "price": 180.0, "amount": 70},
                    ]},
                }),
            "全球头条": pipeline._source_result(
                "Google News", "success", is_today=True, content_date=self.ISO_DATE,
                headlines=headlines or []),
        }

    def _corpus(self, data):
        return {"version": 1,
                "items": pipeline._collect_headline_items(data, self.ISO_DATE)}

    def _history(self):
        days = {
            f"202607{day:02d}": {"pos": 0, "neu": 1, "neg": 0,
                                  "total": 1, "score": 0.0}
            for day in range(26, 32)
        }
        return {"version": 1, "stocks": {
            "A股:600001": {"market": "A股", "code": "600001",
                            "name": "测试股份", "days": days},
        }}

    def test_official_direct_event_is_red_and_us_is_out_of_scope(self):
        data = self._data([
            {"title": "证监会对测试股份立案调查，涉嫌财务造假", "source": "证监会",
             "published_cst": "2026-08-02 09:30", "url": "https://example.com/a"},
            {"title": "英伟达收到退市决定", "source": "交易所",
             "published_cst": "2026-08-02 10:00", "url": "https://example.com/us"},
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, {}, news_corpus=self._corpus(data))
        self.assertTrue(result["available"])
        self.assertEqual(result["universe_n"], 3)  # A股2 + 港股1；美股不进入
        self.assertEqual(result["risk_stock_n"], 1)
        stock = result["stocks"][0]
        self.assertEqual(stock["name"], "测试股份")
        self.assertEqual(stock["level"]["key"], "red")
        self.assertGreaterEqual(stock["risk_index"], 90)
        self.assertFalse(result["score_is_probability"])
        self.assertNotIn("英伟达", [s["name"] for s in result["stocks"]])

    def test_agent_schema_is_json_serializable_explainable_and_not_probability(self):
        data = self._data([
            {"title": "证监会对测试股份立案调查，涉嫌财务造假", "source": "证监会",
             "published_cst": "2026-08-02 09:30", "url": "https://example.com/schema"},
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, {}, news_corpus=self._corpus(data))
        self.assertEqual(result["agent_schema_version"], "octopus-media-risk-agent/2")
        self.assertEqual(len(result["agent_records"]), 1)
        record = result["agent_records"][0]
        encoded = json.dumps(record, ensure_ascii=False)
        self.assertTrue({
            "stock_code", "stock_name", "timestamp", "overall_risk_score",
            "risk_level", "risk_events", "sentiment_metrics",
            "actionable_recommendation", "risk_logic_summary", "score_components",
        }.issubset(record))
        self.assertEqual(record["stock_code"], "600001.SH")
        self.assertEqual(record["stock_name"], "测试股份")
        self.assertEqual(record["timestamp"], "2026-08-02 23:59:59")
        self.assertEqual(record["timezone"], "Asia/Shanghai")
        self.assertGreaterEqual(record["overall_risk_score"], 0.0)
        self.assertLessEqual(record["overall_risk_score"], 1.0)
        self.assertEqual(record["score_semantics"],
                         "normalized_ordinal_rule_index_not_probability")
        self.assertEqual(record["risk_level"], "Level 4 (CRITICAL)")
        self.assertEqual(record["risk_level_number"], 4)
        self.assertEqual({event["category"] for event in record["risk_events"]},
                         {"Regulatory", "Financial"})
        self.assertTrue(all(event["category"] in {
            "Regulatory", "Financial", "Governance", "Sentiment"}
                            for event in record["risk_events"]))
        event = record["risk_events"][0]
        self.assertTrue({"event_type", "summary", "severity", "status", "evidence"}
                        .issubset(event))
        self.assertIn(event["secondary_category"], {"合规与监管", "财务与审计"})
        self.assertEqual(event["status"], "Current")
        self.assertGreater(event["score_inputs"]["event_impact"], 0)
        self.assertEqual(event["evidence"], "证监会对测试股份立案调查，涉嫌财务造假")
        self.assertEqual(event["evidence_metadata"]["source"], "证监会")
        self.assertEqual(event["evidence_metadata"]["timestamp"], "2026-08-02 09:30")
        self.assertEqual(event["evidence_metadata"]["time_precision"], "minute")
        self.assertEqual(event["evidence_metadata"]["url"], "https://example.com/schema")
        self.assertEqual(record["sentiment_metrics"]["sentiment_score"], -1.0)
        self.assertEqual(record["sentiment_metrics"]["media_authority_level"], "High")
        self.assertEqual(record["sentiment_metrics"]["media_authority_type"], "Official")
        self.assertIsNotNone(record["sentiment_metrics"]["first_authoritative_negative"])
        self.assertEqual(record["actionable_recommendation"]["action"], "Blacklist")
        self.assertTrue(record["actionable_recommendation"]["sop"])
        self.assertFalse(record["actionable_recommendation"]["automatic_execution"])
        self.assertTrue(record["risk_logic_summary"])
        self.assertIn("primary_event_impact", record["score_components"])
        self.assertTrue(record["data_quality"]["future_information_excluded"])
        self.assertNotIn("chain_of_thought", encoded.lower())

    def test_official_attention_letter_is_level_three_and_reduce_exposure(self):
        data = self._data([
            {"title": "上交所向测试股份下发关注函", "source": "上交所",
             "published_cst": "2026-08-02 09:15", "url": "https://example.com/letter"},
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, {}, news_corpus=self._corpus(data))
        stock = result["stocks"][0]
        self.assertEqual(stock["events"][0]["severity"], 3)
        self.assertEqual(stock["level"]["key"], "orange")
        payload = stock["agent_payload"]
        self.assertEqual(payload["risk_level"], "Level 3 (HIGH)")
        self.assertEqual(payload["actionable_recommendation"]["action"], "Reduce_Exposure")

    def test_english_hk_alias_and_event_are_attributed(self):
        data = self._data([
            {"title": "tEnCeNt faces regulatory investigation after trading suspension",
             "source": "Reuters", "published_cst": "2026-08-02 08:30",
             "url": "https://example.com/tencent"},
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, {}, news_corpus=self._corpus(data))
        self.assertTrue(result["available"])
        self.assertEqual(result["risk_stock_n"], 1)
        stock = result["stocks"][0]
        self.assertEqual(stock["name"], "腾讯控股")
        self.assertEqual(stock["events"][0]["attribution"], "alias")
        self.assertEqual(stock["agent_payload"]["stock_code"], "00700.HK")
        self.assertIn("合规与监管", stock["categories"])
        self.assertIn("交易与流动性", stock["categories"])

    def test_uncorroborated_self_media_is_capped_as_propagation_risk(self):
        titles = [
            "测试股份被立案调查",
            "测试股份财务造假",
            "测试股份供应中断",
            "测试股份暂停交易",
        ]
        data = self._data([
            {"title": title, "source": f"YouTube自媒体{idx}",
             "published_cst": f"2026-08-02 {8 + idx:02d}:00",
             "url": f"https://example.com/self-media-{idx}"}
            for idx, title in enumerate(titles)
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, {}, news_corpus=self._corpus(data))
        stock = result["stocks"][0]
        self.assertTrue(stock["commentary_only"])
        self.assertLessEqual(stock["risk_index"], 59)
        self.assertNotIn(stock["level"]["key"], ("red", "orange"))
        self.assertIn("仅评论/社区来源", " ".join(
            stock["agent_payload"]["score_components"]["caps"]))

    def test_cross_platform_propagation_uses_mainstream_and_commentary_evidence(self):
        data = self._data([
            {"title": "Tencent faces regulatory investigation", "source": "Reuters",
             "published_cst": "2026-08-02 08:30", "url": "https://example.com/mainstream"},
            {"title": "Tencent trading suspension sparks panic selling", "source": "YouTube财经博主",
             "published_cst": "2026-08-02 09:30", "url": "https://example.com/social"},
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, {}, news_corpus=self._corpus(data))
        metrics = result["stocks"][0]["agent_payload"]["sentiment_metrics"]
        self.assertEqual(metrics["propagation_stage"], "Cross_Platform")
        self.assertTrue(metrics["cross_platform_confirmed"])
        self.assertEqual(metrics["source_count"], 2)
        self.assertEqual(metrics["channel_types"], ["media", "social_or_self_media"])
        self.assertEqual({node["source"] for node in metrics["propagation_nodes"]},
                         {"Reuters", "YouTube财经博主"})
        self.assertEqual(metrics["first_authoritative_negative"]["source"], "Reuters")
        self.assertEqual(metrics["first_report_scope"],
                         "first_observed_in_72h_window_not_global_first")

    def test_attention_only_requires_three_current_day_titles(self):
        data = self._data([
            {"title": f"测试股份发布经营更新{idx}", "source": f"媒体{idx}",
             "published_cst": f"2026-08-02 {8 + idx:02d}:00",
             "url": f"https://example.com/attention-floor-{idx}"}
            for idx in range(2)
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, self._history(), news_corpus=self._corpus(data))
        self.assertFalse(result["available"])

    def test_marketing_noise_does_not_create_attention_signal(self):
        data = self._data([
            {"title": f"测试股份直播预告抽奖活动{idx}", "source": f"自媒体{idx}",
             "published_cst": f"2026-08-02 {8 + idx:02d}:00",
             "url": f"https://example.com/noise-{idx}"}
            for idx in range(4)
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, self._history(), news_corpus=self._corpus(data))
        self.assertFalse(result["available"])
        self.assertEqual(result["noise_filtered_n"], 4)
        universe = pipeline._extract_stock_universe(data["热门榜单"])
        headlines = pipeline._filter_headlines_window(
            self._corpus(data)["items"], pipeline._factor_anchor_dt(self.DATE), hours=72)
        self.assertNotIn("A股:600001",
                         pipeline._media_risk_sentiment_scores(headlines, universe))

    def test_attention_spike_can_form_cautious_standalone_signal(self):
        data = self._data([
            {"title": f"测试股份发布经营更新{idx}", "source": f"媒体{idx}",
             "published_cst": f"2026-08-02 {8 + idx:02d}:00",
             "url": f"https://example.com/attention-{idx}"}
            for idx in range(4)
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, self._history(), news_corpus=self._corpus(data))
        self.assertTrue(result["available"])
        self.assertEqual(result["risk_event_n"], 0)
        self.assertEqual(result["abnormal_attention_n"], 1)
        stock = result["stocks"][0]
        self.assertTrue(stock["attention_only"])
        self.assertIn("异常关注", stock["categories"])
        self.assertLessEqual(stock["risk_index"], 59)
        self.assertNotIn(stock["level"]["key"], ("red", "orange"))
        self.assertIn("未检出具体负面事件", stock["action"])
        html = pipeline._media_risk_block(result, pipeline.GUIZANG_KIT)
        self.assertIn("热度异常证据", html)
        self.assertIn("不代表负面", html)

    def test_attention_spike_uses_prior_natural_day_baseline(self):
        data = self._data([
            {"title": "测试股份收到监管问询函", "source": "证券时报",
             "published_cst": "2026-08-02 09:00", "url": "https://example.com/1"},
            {"title": "测试股份发布经营更新一", "source": "媒体甲",
             "published_cst": "2026-08-02 10:00", "url": "https://example.com/2"},
            {"title": "测试股份发布经营更新二", "source": "媒体乙",
             "published_cst": "2026-08-02 11:00", "url": "https://example.com/3"},
            {"title": "测试股份发布经营更新三", "source": "媒体丙",
             "published_cst": "2026-08-02 12:00", "url": "https://example.com/4"},
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, self._history(), news_corpus=self._corpus(data))
        stock = result["stocks"][0]
        attention = stock["attention"]
        self.assertTrue(attention["enough"])
        self.assertTrue(attention["abnormal"])
        self.assertEqual(attention["today"], 4)
        self.assertEqual(attention["mean"], 1.0)
        self.assertEqual(attention["label"], "极端突增")
        self.assertEqual(result["abnormal_attention_n"], 1)
        self.assertEqual(stock["divergence"], "价涨/情绪偏空空头背离")
        self.assertTrue(stock["agent_payload"]["sentiment_metrics"]["bearish_divergence"])

    def test_all_denial_context_is_capped_below_orange(self):
        data = self._data([
            {"title": "测试股份澄清未被立案调查，相关传闻不实", "source": "公司公告",
             "published_cst": "2026-08-02 09:00", "url": "https://example.com/denial"},
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, {}, news_corpus=self._corpus(data))
        stock = result["stocks"][0]
        self.assertTrue(stock["disputed_only"])
        self.assertLessEqual(stock["risk_index"], 49)
        self.assertNotIn(stock["level"]["key"], ("red", "orange"))
        self.assertTrue(stock["events"][0]["disputed"])

    def test_sector_mapping_is_weak_and_cannot_become_high_alert(self):
        data = self._data([
            {"title": "半导体行业整顿升级", "source": "新华社",
             "published_cst": "2026-08-02 09:00", "url": "https://example.com/sector"},
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, {}, news_corpus=self._corpus(data))
        target = next(s for s in result["stocks"] if s["name"] == "中芯国际")
        self.assertTrue(target["sector_only"])
        self.assertLess(target["risk_index"], 60)
        self.assertNotIn(target["level"]["key"], ("red", "orange"))
        self.assertEqual(target["events"][0]["attribution_label"], "行业链映射")
        self.assertEqual(target["agent_payload"]["actionable_recommendation"]["action"], "Hedge")
        self.assertIn("仅行业链弱归因", " ".join(
            target["agent_payload"]["score_components"]["caps"]))

    def test_historical_and_emerging_only_events_cannot_force_level_four(self):
        fixtures = [
            ("此前测试股份被立案调查", "2026-07-31 12:00", "Historical", 49),
            ("测试股份或将被监管调查", "2026-08-02 08:00", "Emerging", 79),
        ]
        for title, ts, status, cap in fixtures:
            with self.subTest(status=status):
                data = self._data([])
                corpus = {"version": 1, "items": [{
                    "title": title, "source": "证监会", "section": "监管",
                    "ts": ts, "date": ts[:10], "url": "https://example.com/lifecycle",
                }]}
                result = pipeline.build_media_risk(data, self.DATE, {}, news_corpus=corpus)
                stock = result["stocks"][0]
                self.assertEqual(stock["events"][0]["status"], status)
                self.assertLessEqual(stock["risk_index"], cap)
                self.assertNotEqual(stock["level"]["key"], "red")

    def test_agent_events_emit_all_three_lifecycle_states(self):
        data = self._data([])
        corpus = {"version": 1, "items": [
            {"title": "此前测试股份被立案调查", "source": "证券时报",
             "section": "内地财经媒体", "ts": "2026-07-31 12:00",
             "date": "2026-07-31", "url": "https://example.com/historical"},
            {"title": "测试股份或将收到监管问询函", "source": "财联社",
             "section": "内地财经媒体", "ts": "2026-08-02 08:00",
             "date": "2026-08-02", "url": "https://example.com/emerging"},
            {"title": "测试股份收到监管问询函", "source": "上交所",
             "section": "交易所", "ts": "2026-08-02 09:00",
             "date": "2026-08-02", "url": "https://example.com/current"},
        ]}
        result = pipeline.build_media_risk(data, self.DATE, {}, news_corpus=corpus)
        statuses = {event["status"] for event in result["agent_records"][0]["risk_events"]}
        self.assertEqual(statuses, {"Historical", "Emerging", "Current"})

    def test_future_timestamp_is_excluded_and_date_only_is_disclosed(self):
        data = self._data([])
        corpus = {"version": 1, "items": [
            {"title": "测试股份收到监管问询函", "source": "证券时报",
             "section": "内地财经媒体", "ts": "2026-08-02 21:00",
             "date": "2026-08-02", "url": "https://example.com/in"},
            # 报告日锚点为 08-02 23:59；下一日条目属于未来信息，必须排除。
            {"title": "测试股份被立案调查", "source": "证监会",
             "section": "全球头条", "ts": "2026-08-03 00:01",
             "date": "2026-08-03", "url": "https://example.com/future"},
            {"title": "腾讯控股大股东减持", "source": "公司公告",
             "section": "公司公告", "ts": "", "date": "2026-08-02",
             "url": "https://example.com/day"},
        ]}
        result = pipeline.build_media_risk(data, self.DATE, {}, news_corpus=corpus)
        titles = [event["title"] for stock in result["stocks"] for event in stock["events"]]
        self.assertNotIn("测试股份被立案调查", titles)
        day_event = next(event for stock in result["stocks"]
                         for event in stock["events"] if "腾讯控股" in event["title"])
        self.assertEqual(day_event["time_precision"], "date")
        hk_payload = next(stock["agent_payload"] for stock in result["stocks"]
                          if stock["name"] == "腾讯控股")
        self.assertEqual(hk_payload["risk_events"][0]["evidence_metadata"]["timestamp"],
                         "2026-08-02")
        html = pipeline._media_risk_block(result, pipeline.GUIZANG_KIT)
        self.assertIn("日级时间，禁用于日内回测", html)

    def test_evidence_link_output_accepts_only_safe_https(self):
        self.assertEqual(pipeline._media_risk_href("https://example.com/report?a=1&b=2"),
                         "https://example.com/report?a=1&b=2")
        for unsafe in (
            "http://example.com/report", "javascript:alert(1)",
            "https://user:pass@example.com/report", "https://example.com:8443/report",
            "https://example.com/<script>",
        ):
            with self.subTest(url=unsafe):
                self.assertEqual(pipeline._media_risk_href(unsafe), "")
                self.assertIsNone(media_risk._safe_https_url(unsafe))
        data = self._data([{
            "title": "测试股份被立案调查", "source": "证监会",
            "published_cst": "2026-08-02 09:30", "url": "javascript:alert(1)",
        }])
        result = pipeline.build_media_risk(
            data, self.DATE, {}, news_corpus=self._corpus(data))
        metadata = result["agent_records"][0]["risk_events"][0]["evidence_metadata"]
        self.assertIsNone(metadata["url"])

    def test_hk_news_pool_enters_corpus_with_source_time_and_url(self):
        data = self._data([])
        data[pipeline.HK_NEWS_SOURCE_NAME] = pipeline._source_result(
            pipeline.HK_NEWS_SOURCE_NAME, "success", sources=[{
                "name": "香港交易所", "items": [{
                    "title": "腾讯控股收到监管问询函",
                    "published_cst": "2026-08-02 08:45",
                    "url": "https://www.hkex.com.hk/example",
                }],
            }])
        items = pipeline._collect_headline_items(data, self.ISO_DATE)
        item = next(row for row in items if "腾讯控股" in row["title"])
        self.assertEqual(item["source"], "香港交易所")
        self.assertEqual(item["ts"], "2026-08-02 08:45")
        self.assertEqual(item["url"], "https://www.hkex.com.hk/example")

    def test_section_renders_in_all_themes_and_keeps_clickable_evidence(self):
        data = self._data([
            {"title": "证监会对测试股份立案调查", "source": "证监会",
             "published_cst": "2026-08-02 09:30",
             "url": "https://example.com/risk?a=1&b=2"},
        ])
        corpus = self._corpus(data)
        for theme in ("pixel", "guizang", "dossier", "forum", "lime"):
            with self.subTest(theme=theme):
                html = pipeline.generate_report(
                    data, "2026年8月2日 · 周日", self.DATE,
                    theme=theme, news_corpus=corpus)
                self.assertIn(pipeline.SECTION_TITLE_MEDIA_RISK, html)
                self.assertIn("红色预警", html)
                self.assertIn("风险指数", html)
                self.assertIn("https://example.com/risk?a=1&amp;b=2", html)
                self.assertIn("暂停新增仓位", html)
                self.assertIn("标准动作", html)
                self.assertIn("Blacklist", html)
                self.assertIn("事件时态", html)
                self.assertIn("结构化预警 1 只", html)
                # 同一风险标题也进入新闻情绪；正文必须先呈现可核验的具体事件。
                self.assertLess(html.index(pipeline.SECTION_TITLE_MEDIA_RISK),
                                html.index(pipeline.SECTION_TITLE_NEWS_SENTIMENT))
        self.assertLess(pipeline.REPORT_SECTION_ORDER.index("MEDIA RISK"),
                        pipeline.REPORT_SECTION_ORDER.index("NEWS SENTIMENT"))

    def test_feature_switch_removes_only_the_derived_section(self):
        data = self._data([
            {"title": "证监会对测试股份立案调查", "source": "证监会",
             "published_cst": "2026-08-02 09:30", "url": "https://example.com/risk"},
        ])
        corpus = self._corpus(data)
        with patch.object(pipeline, "MEDIA_RISK_ENABLED", False):
            html = pipeline.generate_report(
                data, "2026年8月2日 · 周日", self.DATE,
                theme="guizang", news_corpus=corpus)
        self.assertNotIn(pipeline.SECTION_TITLE_MEDIA_RISK, html)
        # 开关只关派生栏目，不应连带删除共享标题池的新闻情绪栏目。
        self.assertIn(pipeline.SECTION_TITLE_NEWS_SENTIMENT, html)

    def test_section_absent_without_event_or_reliable_attention_baseline(self):
        # 2026-10-21 起：无风险时不再静默缺席，改为“监控中”占位，避免“栏目不见”误判
        data = self._data([
            {"title": "测试股份发布例行经营公告", "source": "公司",
             "published_cst": "2026-08-02 09:30", "url": "https://example.com/normal"},
        ])
        result = pipeline.build_media_risk(
            data, self.DATE, {}, news_corpus=self._corpus(data))
        self.assertFalse(result["available"])
        self.assertIn("headline_n", result)
        self.assertIn("window_text", result)
        html = pipeline.generate_report(
            data, "2026年8月2日 · 周日", self.DATE,
            theme="guizang", news_corpus=self._corpus(data))
        self.assertIn(pipeline.SECTION_TITLE_MEDIA_RISK, html)
        self.assertIn("监控中", html)
        self.assertIn("未检出", html)
        self.assertIn("标题覆盖", html)


if __name__ == "__main__":
    unittest.main()
