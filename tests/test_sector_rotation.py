"""A 股概念 → 港股观察篮子轮动的离线回归测试。"""
import importlib.util
import sys
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from unittest.mock import patch

sys.modules.setdefault("requests", types.SimpleNamespace())
REPO_ROOT = Path(__file__).parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
if str(OUTPUT_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUT_DIR))

from octopus_quant import providers, sector_rotation as rotation  # noqa: E402
import freshness_checker  # noqa: E402

MODULE_PATH = OUTPUT_DIR / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_sector_rotation_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=CST)


def _bars(n=150, *, end=date(2026, 9, 30), base=100.0, daily_growth=0.002):
    """生成截止指定日期的确定性工作日日线，不访问网络。"""
    days = []
    day = end
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    days.reverse()
    return [{
        "date": day.isoformat(),
        "open": base * (1 + daily_growth) ** i,
        "high": base * (1 + daily_growth) ** i,
        "low": base * (1 + daily_growth) ** i,
        "close": base * (1 + daily_growth) ** i,
        "volume": 1_000_000,
    } for i, day in enumerate(days)]


def _concept(name="人工智能", **extra):
    row = {
        "code": "BK1001",
        "name": name,
        "chg_pct": 1.2,
        "up": 8,
        "down": 2,
        "main_net": 50_000_000,
        "amount": 1_000_000_000,
        "as_of": "2026-09-30",
    }
    row.update(extra)
    return row


def _full_inputs():
    concepts = [
        _concept(),
        _concept("半导体", code="BK1002", chg_pct=-0.4, up=2, down=5,
                 main_net=-30_000_000, amount=900_000_000),
        _concept("房地产", code="BK1003"),  # 不在白名单中，必须保持未映射
    ]
    codes = rotation.mapped_stock_codes(concepts)
    stocks = {}
    for i, code in enumerate(codes):
        stocks[code] = {
            "bars": _bars(base=80 + i * 7, daily_growth=0.002 + i * 0.0001),
            "main_pct": 1.0 + i * 0.5,
            "main_net": (1.0 + i) * 10_000_000,
            "amount": 500_000_000,
            "pe_ttm": 10.0 + i * 2.0,
            "pb": 1.0 + i * 0.3,
            "quote_as_of": "2026-09-30",
        }
    benchmark = _bars(base=20_000, daily_growth=0.0005)
    headlines = [
        {"title": "人工智能公司获新订单并实现增长", "source": "测试源",
         "published_cst": "2026-10-01 10:00"},
        # 同题跨源只计一次
        {"title": "人工智能公司获新订单并实现增长", "source": "转载源",
         "published_cst": "2026-10-01 10:30"},
        # 超出 72 小时的旧标题不能影响事件分
        {"title": "腾讯公司业绩下滑", "source": "旧源",
         "published_cst": "2026-09-20 10:00"},
        # 即使上游标记“当天抓取”，没有可核实发布日期也不能计入事件维度
        {"title": "阿里巴巴获批新业务", "is_today": True},
    ]
    return concepts, stocks, benchmark, headlines


class MappingAndScoringTests(unittest.TestCase):
    def test_keyword_mapping_is_explicit_and_unknown_concepts_stay_unmapped(self):
        mapped, unmapped = rotation.map_concepts([
            _concept(), _concept("半导体", code="BK2"), _concept("稀有金属", code="BK3")])
        self.assertEqual([row["name"] for row in mapped], ["人工智能", "半导体"])
        self.assertEqual(unmapped[0]["name"], "稀有金属")
        self.assertIsNone(unmapped[0]["mapping_method"])
        self.assertTrue(all(row["mapping_method"] == "local_keyword_proxy" for row in mapped))
        self.assertIn("00700", mapped[0]["mapped_codes"])
        self.assertEqual(mapped[1]["mapped_codes"], ["00981", "01347"])

    def test_fixed_weights_and_three_strategy_votes_are_separate_from_score(self):
        concepts, stocks, benchmark, headlines = _full_inputs()
        result = rotation.build_rotation(concepts, stocks, benchmark, headlines,
                                         catalog_complete=True, now=NOW)
        self.assertEqual(result["weights"], {
            "技术面": 0.35, "资金面": 0.35, "基本面": 0.10,
            "行业板块": 0.10, "事件驱动": 0.10,
        })
        self.assertAlmostEqual(sum(result["weights"].values()), 1.0)
        self.assertEqual(result["concept_total"], 3)
        self.assertEqual(result["mapped_total"], 2)
        self.assertEqual(result["unmapped_total"], 1)
        self.assertGreaterEqual(result["scored_total"], 1)

        ai = next(row for row in result["items"] if row["name"] == "人工智能")
        self.assertEqual(ai["available_dimensions"], 5)
        self.assertEqual(ai["available_weight"], 1.0)
        self.assertIsNotNone(ai["overall_score"])
        self.assertEqual(ai["dimensions"]["事件驱动"]["valid"], 1)
        self.assertEqual(ai["dimensions"]["事件驱动"]["score"], 100.0)
        # 资金分结合 A 股板块与港股映射篮子，两个来源组等权。
        self.assertEqual(ai["dimensions"]["资金面"]["valid"], 2)
        self.assertEqual(ai["dimensions"]["资金面"]["total"], 2)
        self.assertIsNotNone(ai["dimensions"]["资金面"]["a_share_main_pct"])
        self.assertIsNotNone(ai["dimensions"]["资金面"]["hk_group_score"])

        self.assertEqual(len(ai["strategy_votes"]), 3)
        self.assertTrue(all(vote["available"] for vote in ai["strategy_votes"]))
        self.assertEqual([vote["key"] for vote in ai["strategy_votes"]],
                         ["ma_trend", "multi_momentum", "relative_rotation"])
        self.assertEqual(ai["strategy_summary"]["available_n"], 3)
        self.assertIn("quote_as_of", ai["mapped_stocks"][0])
        self.assertEqual(result["data_dates"]["hk_quotes_latest"], "2026-09-30")
        self.assertEqual(result["data_dates"]["latest_seen"], "2026-09-30")

    def test_missing_inputs_are_not_filled_with_neutral_scores(self):
        result = rotation.build_rotation(
            [_concept(main_net=None, amount=None)], stock_data={}, benchmark_bars=[],
            headlines=[], now=NOW)
        item = result["items"][0]
        self.assertIsNone(item["dimensions"]["技术面"]["score"])
        self.assertIsNone(item["dimensions"]["资金面"]["score"])
        self.assertIsNone(item["dimensions"]["基本面"]["score"])
        self.assertIsNotNone(item["dimensions"]["行业板块"]["score"])
        self.assertIsNone(item["dimensions"]["事件驱动"]["score"])
        self.assertIsNone(item["overall_score"])
        self.assertEqual(item["strategy_summary"]["available_n"], 0)
        self.assertIn("至少 3 个维度", item["score_reason"])

    def test_event_dimension_excludes_stale_undated_and_duplicate_headlines(self):
        concepts, stocks, benchmark, headlines = _full_inputs()
        result = rotation.build_rotation(concepts, stocks, benchmark, headlines, now=NOW)
        ai = next(row for row in result["items"] if row["name"] == "人工智能")
        evidence = ai["event_evidence"]
        self.assertEqual(len(evidence), 1)
        self.assertIn(evidence[0]["source"], {"测试源", "转载源"})
        self.assertIn("获新订单", evidence[0]["title"])
        self.assertNotIn("腾讯公司业绩下滑", str(evidence))
        self.assertEqual(ai["dimensions"]["事件驱动"]["positive"], 1)
        self.assertEqual(ai["dimensions"]["事件驱动"]["negative"], 0)


class ProviderTests(unittest.TestCase):
    def test_fetch_concept_boards_parses_and_pages_current_snapshot(self):
        requests = []
        stamp = int(datetime(2026, 9, 30, 15, 0, tzinfo=CST).timestamp())

        def fetch_json(url, params=None, timeout=10):
            requests.append((url, dict(params or {})))
            page = int(params["pn"])
            if page == 1:
                diff = [
                    {"f12": "BK1001", "f14": "人工智能", "f3": "1.2", "f6": "1e9",
                     "f62": "5e7", "f104": "8", "f105": "2", "f124": str(stamp)},
                    {"f12": "BK1002", "f14": "半导体", "f3": "-0.4", "f6": "9e8",
                     "f62": "-3e7", "f104": "2", "f105": "5", "f124": str(stamp)},
                ]
            else:
                diff = [{"f12": "BK1003", "f14": "房地产", "f3": "0.1", "f6": "8e8",
                         "f62": "1e7", "f104": "4", "f105": "3", "f124": str(stamp)}]
            return {"data": {"total": 3, "diff": diff}}

        result = providers.fetch_concept_boards(fetch_json, page_size=2, max_pages=3)
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(result["total"], 3)
        self.assertTrue(result["complete"])
        self.assertEqual(result["items"][0]["as_of"], "2026-09-30")
        self.assertEqual(result["items"][0]["main_net"], 50_000_000.0)
        self.assertEqual(result["items"][0]["up"], 8.0)
        self.assertEqual(requests[0][1]["fs"], "m:90+t:3")
        self.assertEqual([call[1]["pn"] for call in requests], ["1", "2"])

    def test_fetch_concept_boards_discloses_page_cap(self):
        def fetch_json(url, params=None, timeout=10):
            return {"data": {"total": 99, "diff": [
                {"f12": f"BK{params['pn']}A", "f14": f"概念{params['pn']}A"},
                {"f12": f"BK{params['pn']}B", "f14": f"概念{params['pn']}B"},
            ]}}

        result = providers.fetch_concept_boards(fetch_json, page_size=2, max_pages=2)
        self.assertEqual(len(result["items"]), 4)
        self.assertFalse(result["complete"])
        self.assertTrue(any("分页达到上限" in error for error in result["errors"]))

    def test_unknown_total_at_page_cap_is_not_reported_complete(self):
        def fetch_json(url, params=None, timeout=10):
            page = int(params["pn"])
            return {"data": {"diff": [
                {"f12": f"BK{page}A", "f14": f"概念{page}A"},
                {"f12": f"BK{page}B", "f14": f"概念{page}B"},
            ]}}

        result = providers.fetch_concept_boards(fetch_json, page_size=2, max_pages=2)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["reported_total"])
        self.assertTrue(any("总数未返回" in error for error in result["errors"]))

    def test_unknown_total_empty_page_confirms_end(self):
        def fetch_json(url, params=None, timeout=10):
            if params["pn"] == "1":
                return {"data": {"diff": [
                    {"f12": "BK1A", "f14": "概念1A"},
                    {"f12": "BK1B", "f14": "概念1B"},
                ]}}
            return {"data": {"diff": []}}

        result = providers.fetch_concept_boards(fetch_json, page_size=2, max_pages=3)
        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(result["complete"])
        self.assertIsNone(result["reported_total"])
        self.assertEqual(result["errors"], [])

    def test_unknown_total_page_failure_is_not_reported_complete(self):
        def fetch_json(url, params=None, timeout=10):
            if params["pn"] == "1":
                return {"data": {"diff": [
                    {"f12": "BK1A", "f14": "概念1A"},
                    {"f12": "BK1B", "f14": "概念1B"},
                ]}}
            return None

        result = providers.fetch_concept_boards(fetch_json, page_size=2, max_pages=3)
        self.assertEqual(len(result["items"]), 2)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["reported_total"])
        self.assertTrue(any("第 2 页未取得" in error for error in result["errors"]))

    def test_hk_snapshot_parses_flow_valuation_and_quote_date(self):
        stamp = int(datetime(2026, 9, 30, 16, 0, tzinfo=CST).timestamp())
        seen = []

        def fetch_json(url, params=None, timeout=10):
            seen.append(dict(params or {}))
            return {"data": {"diff": [{
                "f12": "700", "f14": "腾讯控股", "f2": "600", "f3": "1.2",
                "f6": "1200000000", "f9": "25.5", "f23": "5.6",
                "f62": "30000000", "f184": "2.5", "f124": str(stamp),
            }]}}

        quotes = providers.fetch_hk_fundflow(fetch_json, [("腾讯控股", "0700.HK")])
        self.assertIn("00700", quotes)
        quote = quotes["00700"]
        self.assertEqual(quote["main_net"], 30_000_000.0)
        self.assertEqual(quote["main_pct"], 2.5)
        self.assertEqual(quote["amount"], 1_200_000_000.0)
        self.assertEqual(quote["pe_ttm"], 25.5)
        self.assertEqual(quote["pb"], 5.6)
        self.assertEqual(quote["as_of"], "2026-09-30")
        self.assertIn("f9", seen[0]["fields"])
        self.assertIn("f23", seen[0]["fields"])


class PipelineAndFreshnessTests(unittest.TestCase):
    def test_source_date_controls_today_gate_and_freshness(self):
        self.assertTrue(pipeline._sector_rotation_is_today("2026-09-28", today=date(2026, 10, 1)))
        self.assertFalse(pipeline._sector_rotation_is_today("2026-09-26", today=date(2026, 10, 1)))
        self.assertFalse(pipeline._sector_rotation_is_today("not-a-date", today=date(2026, 10, 1)))

        source = pipeline._source_result(
            pipeline.SECTOR_ROTATION_SOURCE_NAME, "success", is_today=False,
            content_date="2026-09-25", result={"items": []})
        self.assertFalse(source.get("snapshot", False))
        status = freshness_checker.check_single_freshness(
            pipeline.SECTOR_ROTATION_SOURCE_NAME, source, today=date(2026, 10, 1))
        self.assertEqual(status["status"], "expired")
        self.assertFalse(status["should_include"])
        can_push, _reason = pipeline.check_push_eligibility({
            pipeline.SECTOR_ROTATION_SOURCE_NAME: source,
        })
        self.assertFalse(can_push)

        recent = pipeline._source_result(
            pipeline.SECTOR_ROTATION_SOURCE_NAME, "success", is_today=True,
            content_date="2026-09-30", result={"items": []})
        recent_status = freshness_checker.check_single_freshness(
            pipeline.SECTOR_ROTATION_SOURCE_NAME, recent, today=date(2026, 10, 1))
        self.assertEqual(recent_status["status"], "fresh")
        self.assertTrue(recent_status["should_include"])

    def test_collection_uses_concept_and_market_inputs_without_live_network(self):
        concepts, stocks, benchmark, _headlines = _full_inputs()
        catalog = {"items": concepts[:2], "total": 2, "complete": True,
                   "served_urls": [], "errors": []}
        with patch.object(pipeline, "SECTOR_ROTATION_ENABLED", True), \
             patch.object(pipeline._quant.providers, "fetch_concept_boards", return_value=catalog), \
             patch.object(pipeline, "_sector_rotation_market_inputs",
                          return_value=(stocks, benchmark)), \
             patch.object(pipeline, "_sector_rotation_headlines", return_value=[]):
            source = pipeline.fetch_sector_rotation({})
        self.assertEqual(source["status"], "success")
        self.assertEqual(source["content_date"], "2026-09-30")
        self.assertTrue(source["is_today"])
        self.assertFalse(source.get("snapshot", False))
        self.assertEqual(source["result"]["mapped_total"], 2)
        self.assertEqual(source["result"]["source_names"][0],
                         "东方财富 push2 概念列表（fs=m:90+t:3）")

    def test_new_column_renders_in_both_themes_with_disclosures(self):
        concepts, stocks, benchmark, headlines = _full_inputs()
        result = rotation.build_rotation(concepts, stocks, benchmark, headlines,
                                         catalog_complete=True, now=NOW)
        result["source_names"] = ["东方财富 A股概念库", "Yahoo / 东方财富港股日线"]
        source = pipeline._source_result(
            "东方财富 A股概念库 + 港股日线/快照", "success", is_today=True,
            content_date="2026-09-30", result=result)
        data = {
            pipeline.SECTOR_ROTATION_SOURCE_NAME: source,
            "实时行情": pipeline._source_result(
                "测试行情", "success", is_today=True,
                quotes={"恒生指数": {"price": 26000, "change_pct": 0.5, "as_of": "2026-09-30"}}),
        }
        self.assertIn("SECTOR ROTATION", pipeline.REPORT_SECTION_ORDER)
        self.assertGreater(pipeline.REPORT_SECTION_ORDER.index("SECTOR ROTATION"),
                           pipeline.REPORT_SECTION_ORDER.index("WEEKLY FORECAST"))
        # 2026-10-14 重排：板块轮动属「④我们该怎么办」，位于总结之前
        self.assertLess(pipeline.REPORT_SECTION_ORDER.index("SECTOR ROTATION"),
                        pipeline.REPORT_SECTION_ORDER.index("SUMMARY"))

        for theme, kit in (("guizang", pipeline.GUIZANG_KIT), ("pixel", pipeline.PIXEL_KIT)):
            with pipeline.notes_mode():          # 权重表 / 映射限制 / 方法参考属于说明文字
                html = pipeline.generate_report(data, "2026年10月1日 · 周四", "20261001", theme=theme)
            self.assertIn("【滚滚翻车鱼】板块轮动量化策略", html, theme)
            self.assertIn("技术面 35% · 资金面 35% · 基本面 10% · 行业板块 10% · 事件驱动 10%", html)
            self.assertIn("仓库内白名单关键词", html)
            self.assertIn("非标准 JdK RRG", html)
            self.assertIn("MA 趋势模板", html)
            kicks = [row[0] for row in pipeline._collect_report_parts(data, kit)["sections"]]
            self.assertIn("SECTOR ROTATION", kicks)
            # 2026-10-14 重排：板块轮动（④）位于行情复盘（①）之后，即在 SUMMARY 之前
            self.assertLess(kicks.index("MARKET REVIEW"), kicks.index("SECTOR ROTATION"))
            self.assertLess(kicks.index("SECTOR ROTATION"), kicks.index("SUMMARY"))
            # 入门版（默认）：评分 / 篮子 / 行情日期在，权重表与方法论整段不出，只留一句提示
            plain_html = pipeline.generate_report(data, "2026年10月1日 · 周四", "20261001", theme=theme)
            self.assertIn("【滚滚翻车鱼】板块轮动量化策略", plain_html, theme)
            self.assertIn("概念覆盖", plain_html, theme)
            self.assertIn("行情日期", plain_html, theme)
            self.assertIn("港股观察篮子", plain_html, theme)
            self.assertIn("人工维护，不是官方成分", plain_html, theme)
            for text in ("五维权重", "非标准 JdK RRG", "GitHub 方法参考", "映射命中词", "可用权重"):
                self.assertNotIn(text, plain_html, f"{theme}: {text}")

    def test_source_registry_and_off_switch(self):
        from backup_sources import DATA_LINES
        self.assertIn("【滚滚翻车鱼】板块轮动量化策略·A股概念库",
                      DATA_LINES["em_clist"]["used_by"])
        self.assertIn("【滚滚翻车鱼】板块轮动量化策略·港股快照",
                      DATA_LINES["em_ulist"]["used_by"])
        self.assertIn("【滚滚翻车鱼】板块轮动量化策略·港股与恒指日线",
                      DATA_LINES["yahoo_bars"]["used_by"])
        with patch.object(pipeline, "SECTOR_ROTATION_ENABLED", False):
            source = pipeline.fetch_sector_rotation({})
        self.assertEqual(source["status"], "unavailable")
        self.assertIn("OCTOPUS_SECTOR_ROTATION=0", source["error"])


if __name__ == "__main__":
    unittest.main()
