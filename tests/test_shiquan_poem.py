#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诗泉（palemoky/chinese-poetry-api）随机一首诗模块与日报开篇集成单测
"""

import json
import os
import random
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "output"))
sys.path.insert(0, str(ROOT / "tests"))

sys.modules.setdefault("requests", types.SimpleNamespace())
sys.modules.setdefault("bs4", types.SimpleNamespace(BeautifulSoup=None))

import shiquan_poem as shiquan  # noqa: E402
import pipeline  # noqa: E402


class ShiquanVendoredAssetsTests(unittest.TestCase):
    """验证 tools/chinese-poetry-api 目录下的上游快照、元数据与离线语料完整性。"""

    def test_vendored_files_exist_and_upstream_metadata_matches(self):
        vdir = ROOT / "tools" / "chinese-poetry-api"
        self.assertTrue((vdir / "LICENSE").is_file())
        self.assertTrue((vdir / "VENDORED.md").is_file())
        self.assertTrue((vdir / "UPSTREAM.json").is_file())
        self.assertTrue((vdir / "requests.http").is_file())
        self.assertTrue((vdir / "internal" / "api" / "rest" / "handler" / "poem.go").is_file())
        self.assertTrue((vdir / "internal" / "api" / "rest" / "handler" / "formatter.go").is_file())
        self.assertTrue((vdir / "internal" / "classifier" / "dynasty.go").is_file())
        self.assertTrue((vdir / "internal" / "classifier" / "type.go").is_file())
        self.assertTrue((vdir / "data" / "poems.json").is_file())

        upstream = json.loads((vdir / "UPSTREAM.json").read_text(encoding="utf-8"))
        self.assertEqual(upstream["upstream_repo"], "https://github.com/palemoky/chinese-poetry-api")
        self.assertEqual(upstream["upstream_data_repo"], "https://github.com/palemoky/chinese-poetry")
        self.assertIn("poetry.palemoky.com", upstream["online_service"])

    def test_vendored_poems_corpus_covers_dynasties_and_types(self):
        poems = shiquan.load_vendored_poems()
        self.assertGreaterEqual(len(poems), 100)
        dynasties = {p["dynasty"]["name"] for p in poems}
        types_set = {p["type"]["name"] for p in poems}
        for expected_dyn in ("先秦", "魏晋", "唐", "五代", "宋", "元", "清"):
            self.assertIn(expected_dyn, dynasties)
        for expected_type in ("五言绝句", "七言绝句", "五言律诗", "乐府诗", "宋词", "五代词", "诗经", "楚辞", "元曲"):
            self.assertIn(expected_type, types_set)


class ShiquanClassifierAndProtocolTests(unittest.TestCase):
    """验证与诗泉 Go 实现（classifier / formatter / poem handler）一致的分类与协议解析。"""

    def test_classify_poetry_type_matches_go_classifier(self):
        # 五言绝句（4 句 × 5 字）
        t1 = shiquan.classify_poetry_type(
            ["白日依山尽，黄河入海流。", "欲穷千里目，更上一层楼。"], title="登鹳雀楼"
        )
        self.assertEqual(t1["name"], "五言绝句")
        self.assertEqual(t1["category"], "唐诗")

        # 七言绝句（4 句 × 7 字）
        t2 = shiquan.classify_poetry_type(
            ["朝辞白帝彩云间，千里江陵一日还。", "两岸猿声啼不住，轻舟已过万重山。"], title="早发白帝城"
        )
        self.assertEqual(t2["name"], "七言绝句")

        # 乐府旧题优先识别
        t3 = shiquan.classify_poetry_type(
            ["秦时明月汉时关，万里长征人未还。", "但使龙城飞将在，不教胡马度阴山。"], title="出塞"
        )
        self.assertEqual(t3["name"], "乐府诗")

        # 词牌优先识别为宋词
        t4 = shiquan.classify_poetry_type(["明月几时有，把酒问青天。"], rhythmic="水调歌头")
        self.assertEqual(t4["name"], "宋词")

        # 数据集标识优先识别
        self.assertEqual(shiquan.classify_poetry_type(["关关雎鸠"], dataset_key="shijing")["name"], "诗经")
        self.assertEqual(shiquan.classify_poetry_type(["帝高阳之苗裔兮"], dataset_key="chuci")["name"], "楚辞")
        self.assertEqual(shiquan.classify_poetry_type(["枯藤老树昏鸦"], dataset_key="yuanqu")["name"], "元曲")

    def test_normalize_poem_payload_supports_v1_and_legacy_envelope(self):
        # /api/v1/poems/random 顶层 formatPoem 响应
        v1_resp = {
            "id": 2045,
            "title": "静夜思",
            "content": ["床前明月光，疑是地上霜。", "举头望明月，低头思故乡。"],
            "author": {"id": 10, "name": "李白"},
            "dynasty": {"id": 6, "name": "唐", "name_en": "Tang", "start_year": 618, "end_year": 907},
            "type": {"id": 4, "name": "五言绝句", "category": "唐诗"},
        }
        norm_v1 = shiquan.normalize_poem_payload(v1_resp, source="api")
        self.assertIsNotNone(norm_v1)
        self.assertEqual(norm_v1["title"], "静夜思")
        self.assertEqual(norm_v1["author"]["name"], "李白")
        self.assertEqual(norm_v1["dynasty"]["name"], "唐")
        self.assertEqual(norm_v1["type"]["name"], "五言绝句")
        self.assertEqual(norm_v1["source"], "api")

        # /api/poems/random 带 data 包装响应
        legacy_resp = {
            "data": {
                "id": 88,
                "title": "相见欢",
                "content": ["无言独上西楼，月如钩。", "寂寞梧桐深院锁清秋。"],
                "author": {"name": "李煜"},
                "dynasty": {"name": "五代"},
                "type": {"name": "五代词", "category": "词"},
            },
            "lang": "zh-Hans",
        }
        norm_legacy = shiquan.normalize_poem_payload(legacy_resp, source="api")
        self.assertIsNotNone(norm_legacy)
        self.assertEqual(norm_legacy["title"], "相见欢")
        self.assertEqual(norm_legacy["author"]["name"], "李煜")
        self.assertEqual(norm_legacy["dynasty"]["name"], "五代")

    def test_filter_poems_respects_feihualing_char_constraints(self):
        poems = shiquan.load_vendored_poems()
        moon_poems = shiquan.filter_poems(poems, char="月")
        self.assertGreater(len(moon_poems), 0)
        for p in moon_poems:
            self.assertTrue("月" in p["title"] or any("月" in line for line in p["content"]))

        # char 必须单字，且与朝代/作者/体裁过滤互斥
        with self.assertRaises(ValueError):
            shiquan.filter_poems(poems, char="明月")
        with self.assertRaises(ValueError):
            shiquan.filter_poems(poems, char="月", dynasty="唐")

    def test_fetch_random_poem_uses_live_api_when_available_and_falls_back_offline(self):
        shiquan.reset_circuit_breaker()
        sample_api_payload = {
            "id": 999,
            "title": "鹿柴",
            "content": ["空山不见人，但闻人语响。", "返景入深林，复照青苔上。"],
            "author": {"id": 7, "name": "王维"},
            "dynasty": {"id": 6, "name": "唐", "name_en": "Tang"},
            "type": {"id": 4, "name": "五言绝句", "category": "唐诗"},
        }
        called_urls = []

        def fake_request(url, timeout=2.5):
            called_urls.append(url)
            return sample_api_payload

        poem = shiquan.fetch_random_poem(request_fn=fake_request, dynasty="唐", lang="zh-Hans")
        self.assertEqual(poem["title"], "鹿柴")
        self.assertEqual(poem["source"], "api")
        self.assertEqual(len(called_urls), 1)
        self.assertIn("/api/v1/poems/random", called_urls[0])
        self.assertIn("dynasty=", called_urls[0])

        # 当在线接口抛异常时，自动熔断并回退到本地诗泉语料库
        shiquan.reset_circuit_breaker()

        def failing_request(url, timeout=2.5):
            raise ConnectionError("network unreachable")

        fallback = shiquan.fetch_random_poem(
            request_fn=failing_request, dynasty="宋", rng=random.Random(42)
        )
        self.assertEqual(fallback["source"], "vendored")
        self.assertEqual(fallback["dynasty"]["name"], "宋")
        self.assertTrue(len(fallback["content"]) >= 1)


class ShiquanPipelineIntegrationTests(unittest.TestCase):
    """验证诗选与卦象共用卷首栏，五套主题及微信分条推送均兼容。"""

    def _sample_data(self):
        return {
            "实时行情": pipeline._source_result(
                "Yahoo Finance", "success", is_today=True, content_date="2026-10-11",
                quotes={
                    "恒生指数": {"price": 21200.0, "change": 180.0, "change_pct": 0.86, "as_of": "2026-10-11"},
                    "上证指数": {"price": 3350.0, "change": 25.0, "change_pct": 0.75, "as_of": "2026-10-11"},
                },
            ),
            "Reddit": pipeline._public_site_result(
                "Reddit",
                [{"title": "HSI breakout discussion", "url": "https://www.reddit.com/r/stocks/comments/1/a/",
                  "published_cst": "2026-10-11 09:00", "community": "r/stocks", "is_today": True}],
                latest="2026-10-11",
            ),
        }

    def test_poem_and_bagua_share_one_opening_section_across_all_themes(self):
        for theme in pipeline.PUSH_THEMES:
            data = self._sample_data()
            data[pipeline.SHIQUAN_META_KEY] = {
                "id": 101,
                "title": "终南望余雪",
                "content": ["终南阴岭秀，积雪浮云端。", "林表明霁色，城中增暮寒。"],
                "author": {"id": 12, "name": "祖咏"},
                "dynasty": {"id": 6, "name": "唐", "name_en": "Tang"},
                "type": {"id": 4, "name": "五言绝句", "category": "唐诗"},
            }
            html = pipeline.generate_report(data, "2026年10月11日 · 周日", "20261011", theme=theme)
            self.assertEqual(html.count(pipeline.SECTION_TITLE_POETRY_SEA), 1)
            self.assertIn("诗泉", html, f"{theme} 主题缺少诗泉来源标识")
            self.assertIn("今日一首诗", html)
            self.assertIn("《终南望余雪》", html, f"{theme} 主题缺少诗题")
            self.assertIn("终南阴岭秀，积雪浮云端。", html, f"{theme} 主题缺少诗句")
            self.assertIn("☯", html)
            self.assertIn("今日八卦运程与利忌", html)
            self.assertNotIn("开篇随机一首诗", html)  # 原栏目名不再单独出现

            # 一个栏目、两个子块，紧挨刊头且排在首个市场栏目（今日预判）之前。
            opening = html.split(pipeline.PART_BREAK_MARK)[1]
            self.assertIn("今日一首诗", opening)
            self.assertIn("今日八卦运程与利忌", opening)
            self.assertEqual(opening.count(pipeline.SECTION_BODY_MARK), 1)
            self.assertLess(html.index(pipeline.SECTION_TITLE_POETRY_SEA),
                            html.index("《终南望余雪》"))
            self.assertLess(html.index("《终南望余雪》"), html.index("今日八卦运程与利忌"))
            self.assertLess(html.index("今日八卦运程与利忌"),
                            html.index(pipeline.SECTION_TITLE_FORECAST))

    def test_generate_report_auto_picks_random_poem_when_data_has_no_cached_poem(self):
        data = self._sample_data()
        parts = pipeline._collect_report_parts(data, pipeline.LIME_KIT, date_str="20261011")
        self.assertIsNotNone(parts.get("poem"))
        html = pipeline.generate_report(data, "2026年10月11日 · 周日", "20261011", theme="lime")
        self.assertIn(pipeline.SECTION_TITLE_POETRY_SEA, html)
        self.assertIn("今日一首诗", html)
        self.assertIn("今日八卦运程与利忌", html)
        self.assertLess(html.index("今日一首诗"), html.index(pipeline.SECTION_TITLE_FORECAST))

    def test_shiquan_can_be_disabled_via_env(self):
        data = self._sample_data()
        with patch.dict(os.environ, {"OCTOPUS_SHIQUAN": "0"}):
            html = pipeline.generate_report(data, "2026年10月11日 · 周日", "20261011", theme="lime")
        self.assertNotIn("今日一首诗", html)
        self.assertIn(pipeline.SECTION_TITLE_POETRY_SEA, html)
        self.assertIn("今日八卦运程与利忌", html)  # 八卦开关独立

    def test_both_features_off_hide_opening_without_changing_market_sections(self):
        data = self._sample_data()
        with (patch.dict(os.environ, {"OCTOPUS_SHIQUAN": "0"}),
              patch.object(pipeline._bagua, "ENABLED", False)):
            html = pipeline.generate_report(data, "2026年10月11日 · 周日", "20261011", theme="lime")
        self.assertNotIn(pipeline.SECTION_TITLE_POETRY_SEA, html)
        self.assertNotIn("今日一首诗", html)
        self.assertNotIn('aria-label="算卦"', html)
        self.assertIn(pipeline.SECTION_TITLE_FORECAST, html)

    def test_multipart_split_retains_opening_poem_in_first_part(self):
        data = self._sample_data()
        data[pipeline.SHIQUAN_META_KEY] = {
            "id": 102,
            "title": "江雪",
            "content": ["千山鸟飞绝，万径人踪灭。", "孤舟蓑笠翁，独钓寒江雪。"],
            "author": {"id": 15, "name": "柳宗元"},
            "dynasty": {"id": 6, "name": "唐", "name_en": "Tang"},
            "type": {"id": 4, "name": "五言绝句", "category": "唐诗"},
        }
        html = pipeline.generate_report(data, "2026年10月11日 · 周日", "20261011", theme="guizang")
        opening = html.split(pipeline.PART_BREAK_MARK)[1]
        self.assertIn("《江雪》", opening)
        self.assertIn("孤舟蓑笠翁，独钓寒江雪。", opening)
        self.assertIn("今日八卦运程与利忌", opening)
        self.assertNotIn("FORECAST", opening)
        # 分条推送仍保留完整栏目头与卦象图标；即使栏目超额切为续片也不丢内容。
        pieces = pipeline._split_html_for_push(html, 9000, max_parts=20)
        self.assertIsNotNone(pieces)
        self.assertIn(pipeline.SECTION_TITLE_POETRY_SEA, pieces[0])
        self.assertIn("《江雪》", pieces[0])
        self.assertIn("今日八卦运程与利忌", "".join(pieces))


if __name__ == "__main__":
    unittest.main()
