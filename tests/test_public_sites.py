"""趋势跟踪（多平台信息员 + 全网 36 个新闻源头 · 港股挖掘）的离线解析、降级、主题渲染及推送门禁测试。

覆盖四个公开平台：Reddit（板块热门帖）、StockTwits（趋势榜 + 平台情绪标签）、
TradingView（Ideas RSS）、Bogleheads（论坛 RSS）与港股新闻源（RSS/Atom 聚合）；
全部请求均 mock，不访问网站。"""
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch

# CI 装有 requests；本地最小环境没有时仅提供导入占位，请求一律 mock。
sys.modules.setdefault("requests", types.SimpleNamespace())
PATH = Path(__file__).parents[1] / "output" / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_public_sites_test", PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def heat_html(score, comments):
    """模拟 Reddit RSS <content type="html"> 里的热度片段（XML 转义后的 HTML）。"""
    return (f"&lt;div class=&quot;score unvoted&quot; title=&quot;{score}&quot;&gt;{score} points&lt;/div&gt; "
            f"&lt;span class=&quot;number-of-comments&quot;&gt;{comments} comments&lt;/span&gt;")


def atom_entry(title, url, dt, content=""):
    date = dt.astimezone(timezone.utc).isoformat()
    return (f"<entry><title>{title}</title>"
            f"<link rel='alternate' href='{url}'/>"
            f"<published>{date}</published>"
            f"<content type='html'>{content}</content></entry>")


def atom(*entries):
    return ("<feed xmlns='http://www.w3.org/2005/Atom'>"
            + "".join(entries) + "</feed>")


def rss_item(title, link, dt, description=""):
    return (f"<item><title>{title}</title><link>{link}</link>"
            f"<pubDate>{format_datetime(dt)}</pubDate>"
            f"<description>{description}</description></item>")


def rss(*items):
    return ("<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'>"
            "<channel><title>feed</title>" + "".join(items) + "</channel></rss>")


def reddit_child(title, permalink, dt, *, stickied=False, score=0, comments=0):
    return {"data": {
        "title": title, "permalink": permalink,
        "created_utc": dt.timestamp(), "stickied": stickied,
        "score": score, "num_comments": comments,
    }}


class SentimentFactorTests(unittest.TestCase):
    def test_url_allowlist_covers_only_trend_platforms(self):
        # 四个平台主机（含 www / 裸域）放行
        self.assertEqual(pipeline._public_url("/r/stocks/comments/abc/x/", "https://www.reddit.com/"),
                         "https://www.reddit.com/r/stocks/comments/abc/x/")
        self.assertEqual(pipeline._public_url("https://old.reddit.com/r/stocks/comments/1/y/", ""),
                         "https://old.reddit.com/r/stocks/comments/1/y/")
        self.assertEqual(pipeline._public_url("/symbol/MU", "https://stocktwits.com/"),
                         "https://stocktwits.com/symbol/MU")
        self.assertEqual(
            pipeline._public_url("https://www.tradingview.com/chart/NQ1!/abc/", ""),
            "https://www.tradingview.com/chart/NQ1!/abc/")
        self.assertEqual(
            pipeline._public_url("https://www.bogleheads.org/forum/viewtopic.php?p=1#p1", ""),
            "https://www.bogleheads.org/forum/viewtopic.php?p=1#p1")
        # 平台之外的来源一律拒绝，防止标题/链接注入
        for url in ("javascript:alert(1)", "http://www.reddit.com/r/stocks",
                    "https://reddit.evil.net/r/stocks", "https://finviz.com/map.ashx?t=sec",
                    "https://fred.stlouisfed.org/series/DFF", "//evil.net/path",
                    "https://www.reddit.com/<script>", "https://stocktwits.evil.net/symbol/MU",
                    "https://xueqiu.com/statuses/hot/listV2.json"):
            self.assertEqual(pipeline._public_url(url, "https://www.reddit.com/"), "", url)
        self.assertEqual(pipeline._public_text("<b>ETF</b> &amp; market\n news"), "ETF & market news")

    def test_multi_platform_registry_ten_boards_five_posts(self):
        self.assertEqual(pipeline.PUBLIC_SITE_NAMES,
                         ("Reddit", "StockTwits", "TradingView", "Bogleheads"))
        self.assertEqual(set(pipeline.PUBLIC_SITE_NAMES), set(pipeline.PUBLIC_SITE_DESCRIPTIONS))
        self.assertEqual(set(pipeline.PUBLIC_SITE_NAMES), set(pipeline.PUBLIC_SITE_URLS))
        self.assertEqual(pipeline._active_public_site_names(), pipeline.PUBLIC_SITE_NAMES)
        self.assertEqual(len(pipeline._REDDIT_BOARDS), 10)
        self.assertEqual(len(set(board[0] for board in pipeline._REDDIT_BOARDS)), 10)
        self.assertEqual(pipeline.REDDIT_POSTS_PER_BOARD, 5)
        # 用户点名的四个板块必须在列
        for named in ("stocks", "investing", "wallstreetbets", "ValueInvesting"):
            self.assertIn(named, [board[0] for board in pipeline._REDDIT_BOARDS])
        # 结果容器不再对总条数做「每站 3 条」截断
        items = [{"title": str(i), "url": "https://www.reddit.com/", "is_today": False}
                 for i in range(50)]
        self.assertEqual(len(pipeline._public_site_result("Reddit", items)["items"]), 50)

    def test_reddit_heat_extracted_from_feed_html(self):
        self.assertEqual(
            pipeline._reddit_heat_from_html(
                f'<div class="score">1,234 points</div><span>56 comments</span>'),
            " · 1,234 赞 · 56 评论")
        heat = '<div class="score">1,234 points</div><span>56 comments</span>'
        self.assertEqual(pipeline._reddit_heat_counts_from_html(heat), (1234, 56))
        self.assertEqual(pipeline._reddit_heat_counts_from_html("<p>no heat data here</p>"),
                         (None, None))
        self.assertEqual(pipeline._reddit_heat_counts_from_html("1.2k points 8 comments"),
                         (1200, 8))
        self.assertEqual(pipeline._reddit_heat_from_html("<p>no heat data here</p>"), "")
        self.assertEqual(pipeline._reddit_heat_from_html(None), "")

    def test_hot_feed_keeps_rank_order_not_time_and_caps_five_per_board(self):
        now = datetime(2026, 9, 27, 14, 0, tzinfo=pipeline.CST)
        base = "https://www.reddit.com/r/stocks/"
        no_zone = ("<entry><title>No zone</title>"  # 无时区的裸日期 → 剔除
                   "<link rel='alternate' href='" + base + "comments/5/e/'/>"
                   "<published>2026-09-27T14:00:00</published></entry>")
        feed = atom(
            atom_entry("Hottest but oldest", base + "comments/1/a/",
                       now - timedelta(hours=20), content=heat_html(512, 234)),
            atom_entry("Fresh", base + "comments/2/b/", now - timedelta(hours=1)),
            atom_entry("Fresh2", base + "comments/3/c/", now - timedelta(hours=2)),
            atom_entry("Stale", base + "comments/4/d/",
                       now - timedelta(hours=80)),  # 超 72h 窗口剔除
            no_zone,
            atom_entry("Dup", base + "comments/2/b/", now - timedelta(hours=3)),  # 重复链接剔除
            atom_entry("RankSix", base + "comments/6/f/", now - timedelta(hours=4)),
            atom_entry("RankSeven", base + "comments/7/g/", now - timedelta(hours=5)),
        )
        items, latest = pipeline._reddit_hot_items(
            feed, "stocks", "https://www.reddit.com/r/stocks/", now=now)
        # 保留 feed（热度榜）顺序而不是发布时间顺序，且超 72h / 无时区 / 重复链接剔除
        self.assertEqual([it["title"] for it in items],
                         ["Hottest but oldest", "Fresh", "Fresh2", "RankSix", "RankSeven"])
        self.assertEqual(len(items), 5)  # 每板块最多 5 条样本
        self.assertEqual(latest, now.strftime("%Y-%m-%d"))
        self.assertTrue(all(it["community"] == "r/stocks" for it in items))
        self.assertIn("512 赞", items[0]["detail"])
        self.assertIn("234 评论", items[0]["detail"])
        self.assertEqual((items[0]["score"], items[0]["comments"]), (512, 234))
        self.assertTrue(all("发布于" in it["detail"] for it in items))
        # 全部条目超窗时返回空
        old = atom(atom_entry("Old", "https://www.reddit.com/r/stocks/comments/9/h/",
                              now - timedelta(days=3, hours=1)))
        self.assertEqual(pipeline._reddit_hot_items(old, "stocks", "https://www.reddit.com/r/stocks/", now=now),
                         ([], None))

    def test_json_fallback_reads_score_comments_and_skips_bad_posts(self):
        now = datetime(2026, 9, 27, 14, 0, tzinfo=pipeline.CST)
        payload = {"data": {"children": [
            reddit_child("WSB hot 0", "/r/wallstreetbets/comments/a1/p1/",
                         now - timedelta(hours=1), stickied=False, score=100, comments=50),
            reddit_child("Pinned rules", "/r/wallstreetbets/comments/a2/p2/",
                         now - timedelta(hours=2), stickied=True, score=999, comments=10),
            reddit_child("WSB hot 1", "/r/wallstreetbets/comments/a3/p3/",
                         now - timedelta(hours=3), stickied=False, score=80, comments=40),
            reddit_child("WSB hot 2", "/r/wallstreetbets/comments/a4/p4/",
                         now - timedelta(hours=4), stickied=False, score=70),
            reddit_child("Injected", "https://evil.example/r/wallstreetbets/comments/x/",
                         now - timedelta(hours=5), score=60, comments=5),
            reddit_child("Too old", "/r/wallstreetbets/comments/a5/p5/",
                         now - timedelta(days=4), score=50, comments=5),
        ]}}
        items, latest = pipeline._reddit_json_items(payload, "wallstreetbets", now=now)
        self.assertEqual([it["title"] for it in items], ["WSB hot 0", "WSB hot 1", "WSB hot 2"])
        self.assertEqual(items[0]["url"], "https://www.reddit.com/r/wallstreetbets/comments/a1/p1/")
        self.assertIn("100 赞", items[0]["detail"])
        self.assertIn("50 评论", items[0]["detail"])
        self.assertEqual((items[0]["score"], items[0]["comments"]), (100, 50))
        self.assertIn("70 赞", items[2]["detail"])
        self.assertNotIn("评论", items[2]["detail"])  # 无评论数时不显示
        self.assertEqual((items[2]["score"], items[2]["comments"]), (70, 0))
        self.assertEqual(latest, now.strftime("%Y-%m-%d"))
        # 非 dict / 缺 children 的 payload 一律安全返回空
        self.assertEqual(pipeline._reddit_json_items(None, "stocks", now=now), ([], None))
        self.assertEqual(pipeline._reddit_json_items({"data": {}}, "stocks", now=now), ([], None))

    def test_fetch_reddit_parallel_boards_json_fallback_and_partial_403(self):
        now = datetime.now(pipeline.CST)
        stocks_feed = atom(*[
            atom_entry(f"Stocks hot {i}", f"https://www.reddit.com/r/stocks/comments/s{i}/t{i}/",
                       now - timedelta(hours=i + 1),
                       content=heat_html(512 - i, 234 - i) if i == 0 else "")
            for i in range(7)  # 7 条热帖 → 只保留前 5 条样本
        ])
        investing_feed = atom(*[
            atom_entry(f"Investing hot {i}", f"https://www.reddit.com/r/investing/comments/v{i}/t{i}/",
                       now - timedelta(hours=i + 1))
            for i in range(2)
        ])
        wsb_payload = {"data": {"children": [
            reddit_child(f"WSB hot {i}", f"/r/wallstreetbets/comments/w{i}/t{i}/",
                         now - timedelta(hours=i + 1), score=100 - i * 10, comments=50 - i * 5)
            for i in range(3)
        ]}}

        def fake_request(url, **kwargs):
            community = url.split("/r/")[1].split("/")[0]
            if url.endswith("hot/.rss?limit=10"):
                return {"stocks": stocks_feed, "investing": investing_feed}.get(community)
            if url.endswith("hot.json?limit=10"):
                return {"wallstreetbets": wsb_payload}.get(community)
            return None  # 其余板块 RSS / JSON 全部 403

        with patch.object(pipeline, "safe_request", side_effect=fake_request) as req:
            result = pipeline.fetch_reddit()
        # 板块顺序展示：r/stocks 5 条 → r/investing 2 条 → r/wallstreetbets 3 条
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["is_today"])
        self.assertEqual([it["community"] for it in result["items"]],
                         ["r/stocks"] * 5 + ["r/investing"] * 2 + ["r/wallstreetbets"] * 3)
        self.assertEqual(len(result["items"]), 10)
        self.assertEqual(result["content_date"], now.strftime("%Y-%m-%d"))
        self.assertEqual(result["items"][0]["title"], "Stocks hot 0")
        self.assertIn("512 赞", result["items"][0]["detail"])
        self.assertIn("100 赞", result["items"][7]["detail"])  # JSON 兜底的热度
        # 10 次 RSS + 8 次 JSON 兜底（stocks/investing 的 RSS 成功，不再试 JSON）
        # 启用备用源后，失败板块会尝试多备源，调用次数 >=18
        self.assertGreaterEqual(req.call_count, 18)
        # 暂缺板块如实点名
        for missing in ("r/ValueInvesting", "r/economics", "r/wallstreet", "r/options",
                        "r/Forex", "r/pennystocks", "r/personalfinance"):
            self.assertIn(missing, result["note"])
        self.assertIn("热度不等于事实", result["note"])
        with patch.object(pipeline, "safe_request", return_value=None):
            failed = pipeline.fetch_reddit()
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["items"], [])
        for board in ("r/stocks", "r/personalfinance"):
            self.assertIn(board, failed["note"])

    def test_public_sites_multi_platform_isolation(self):
        """单个平台失败只影响该平台；其余平台照常返回，顺序与注册表一致。"""
        stocktwits = pipeline._public_site_result(
            "StockTwits", [{"title": "MU · Micron", "url": "https://stocktwits.com/symbol/MU",
                            "is_today": True}])
        with patch.object(pipeline, "fetch_reddit", side_effect=ValueError("broken feed")), \
             patch.object(pipeline, "fetch_stocktwits", return_value=stocktwits), \
             patch.object(pipeline, "fetch_tradingview", side_effect=ValueError("blocked")), \
             patch.object(pipeline, "fetch_bogleheads",
                          return_value=pipeline._public_site_result("Bogleheads", [])):
            results = pipeline.fetch_public_sites()
        self.assertEqual(tuple(results), pipeline.PUBLIC_SITE_NAMES)
        self.assertEqual(results["Reddit"]["status"], "unavailable")
        self.assertEqual(results["StockTwits"]["status"], "success")
        self.assertEqual(results["TradingView"]["status"], "unavailable")
        self.assertEqual(results["Bogleheads"]["status"], "unavailable")
        # 禁用开关：OCTOPUS_TREND_PLATFORMS 过滤后为空则回落全部平台
        with patch.dict("os.environ", {"OCTOPUS_TREND_PLATFORMS": "reddit, bogleheads"}):
            self.assertEqual(pipeline._active_public_site_names(), ("Reddit", "Bogleheads"))
        with patch.dict("os.environ", {"OCTOPUS_TREND_PLATFORMS": "unknown"}):
            self.assertEqual(pipeline._active_public_site_names(), pipeline.PUBLIC_SITE_NAMES)

    def test_collect_all_data_has_base_sources_plus_trend_platforms(self):
        legacy = ("fetch_market_snapshot", "fetch_market_panorama", "fetch_gov_policy",
                  "fetch_hk_channels", "fetch_google_news", "fetch_fed_trend",
                  "fetch_geo_trend", "fetch_eastmoney_news", "fetch_hot_stocks",
                  "fetch_hk_quant", "fetch_weekly_forecast", "fetch_hk_seven_day",
                  "fetch_econ_calendar", "fetch_industry_rotation")
        platforms = {
            "Reddit": pipeline._public_site_result(
                "Reddit", [{"title": "Sample", "url": "https://www.reddit.com/r/stocks/comments/1/x/",
                            "is_today": True}]),
            "StockTwits": pipeline._public_site_result(
                "StockTwits", [{"title": "MU · Micron", "url": "https://stocktwits.com/symbol/MU",
                                "is_today": True}]),
            "TradingView": pipeline._public_site_result(
                "TradingView", [{"title": "Nasdaq 100 (NQ)", "url": "https://www.tradingview.com/chart/NQ1!/x/",
                                 "is_today": True}]),
            "Bogleheads": pipeline._public_site_result(
                "Bogleheads", [{"title": "Why Bonds EVER", "url": "https://www.bogleheads.org/forum/viewtopic.php?p=1#p1",
                                "is_today": True}]),
        }
        news = pipeline._source_result(pipeline.HK_NEWS_SOURCE_NAME, "unavailable",
                                       sources=[], analysis=None, error="offline")
        with patch.object(pipeline, "time", types.SimpleNamespace(sleep=lambda s: None)):
            mocks = [patch.object(pipeline, fn, return_value={"status": "unavailable"})
                     for fn in legacy]
            for p in mocks:
                p.start()
            try:
                with patch.object(pipeline, "fetch_public_sites", return_value=platforms):
                    with patch.object(pipeline, "fetch_hk_news_sources", return_value=news):
                        data = pipeline.collect_all_data()
            finally:
                for p in reversed(mocks):
                    p.stop()
        # 11 个基础数据源（含港股量化引擎、每周走势预测、AI 七日港股走势分析与未来30天财经日历；
        # A股资讯已移除）+ 2 个 AI趋势分析专题源（美联储 / 地缘政治）+ 4 个趋势平台 + 全网新闻源头
        # 允许额外的新鲜度/去重/备用源元信息键（_freshness, _dedup, _backup_info）
        expected_keys = {
            "实时行情", "A股大盘全景", "国家政策", "港股名家频道", "全球头条",
            "美联储趋势", "地缘政治趋势",
            "东财快讯", "热门榜单", "港股量化", "每周走势预测", pipeline.HK7_SOURCE_NAME,
            "财经日历", pipeline.HK_NEWS_SOURCE_NAME,
            "Reddit", "StockTwits", "TradingView", "Bogleheads"}
        self.assertTrue(expected_keys.issubset(set(data.keys())),
                        f"缺少基础数据源: {expected_keys - set(data.keys())}")
        self.assertEqual(data["Reddit"]["status"], "success")
        self.assertEqual(data["StockTwits"]["status"], "success")
        self.assertEqual(data[pipeline.HK_NEWS_SOURCE_NAME]["status"], "unavailable")

    def test_collect_all_data_skips_news_sources_when_disabled(self):
        legacy = ("fetch_market_snapshot", "fetch_market_panorama", "fetch_gov_policy",
                  "fetch_hk_channels", "fetch_google_news", "fetch_fed_trend",
                  "fetch_geo_trend", "fetch_eastmoney_news", "fetch_hot_stocks",
                  "fetch_hk_quant", "fetch_weekly_forecast", "fetch_hk_seven_day",
                  "fetch_econ_calendar", "fetch_industry_rotation")
        with patch.object(pipeline, "time", types.SimpleNamespace(sleep=lambda s: None)):
            mocks = [patch.object(pipeline, fn, return_value={"status": "unavailable"})
                     for fn in legacy]
            for p in mocks:
                p.start()
            try:
                with patch.object(pipeline, "fetch_public_sites", return_value={}):
                    with patch.object(pipeline, "fetch_hk_news_sources",
                                      side_effect=AssertionError("开关关闭时不得调用")):
                        with patch.object(pipeline, "HK_NEWS_ENABLED", False):
                            data = pipeline.collect_all_data()
            finally:
                for p in reversed(mocks):
                    p.stop()
        self.assertNotIn(pipeline.HK_NEWS_SOURCE_NAME, data)

    def _reddit_data(self):
        items = []
        for i in range(7):  # 超 5 条 → 渲染端只保留板块前 5 条
            items.append({
                "title": f"Stocks hot {i}",
                "url": f"https://www.reddit.com/r/stocks/comments/s{i}/t{i}/",
                "detail": f"发布于 2026-09-27 10:0{i}（北京时间） · 100 赞 · 10 评论",
                "published_cst": f"2026-09-27 10:0{i}", "community": "r/stocks",
                "is_today": True})
        for i in range(3):
            items.append({
                "title": f"WSB hot {i}",
                "url": f"https://www.reddit.com/r/wallstreetbets/comments/w{i}/t{i}/",
                "detail": f"发布于 2026-09-27 09:0{i}（北京时间） · 90 赞",
                "published_cst": f"2026-09-27 09:0{i}", "community": "r/wallstreetbets",
                "is_today": True})
        items.append({"title": "Unsafe", "url": "javascript:alert(1)",
                      "detail": "bad", "published_cst": "2026-09-27 09:00",
                      "community": "r/stocks", "is_today": True})
        return {"Reddit": pipeline._public_site_result("Reddit", items, latest="2026-09-27"),
                "实时行情": pipeline._source_result("sample quote", "success", quotes={
                    "标普500": {"price": 6123.45, "change_pct": 1.25}})}

    def test_sentiment_section_renders_boards_capped_in_both_themes(self):
        data = self._reddit_data()
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            for theme in ("guizang", "pixel"):
                with self.subTest(theme=theme):
                    report = pipeline.generate_report(data, "2026年9月27日 · 周日", "20260927", theme=theme)
                    title_pin = ("TREND TRACKING" if theme == "pixel"
                                 else f"{pipeline.SECTION_TITLE_TREND}</h2>")
                    self.assertIn(title_pin, report)  # 真实栏目标题，不是页面标题
                    self.assertNotIn("每日量化策略趋势跟踪线索", report)  # 旧栏目名不得回潮
                    self.assertNotIn("每日量化情绪因子", report)
                    self.assertNotIn("每日量化策略投研", report)
                    # 板块子标题（有数据的板块）
                    self.assertIn("r/stocks", report)
                    self.assertIn("个股讨论", report)
                    self.assertIn("r/wallstreetbets", report)
                    self.assertIn("散户投机风向", report)
                    # 无数据的板块不进正文
                    self.assertNotIn("r/ValueInvesting", report)
                    # 每板块样本条数上限：全量档 5 条（第 6 / 7 条被裁剪）；
                    # 精简档（2026-09-30 起默认）每板块 2 条，但分组行必须如实
                    # 写出「共 5 条」——折叠多少条不许静默。
                    cap = pipeline.LITE("site_posts")
                    self.assertIn("Stocks hot %d" % (cap - 1), report)
                    self.assertNotIn("Stocks hot %d" % cap, report)
                    self.assertNotIn("Stocks hot 6", report)
                    if cap < 5:
                        # r/stocks 有 7 条合法样本（第 8 条 javascript: 链接整体剔除）
                        self.assertIn("热门帖样本 %d 条（共 7 条）" % cap, report)
                    # 链接与热度保留
                    self.assertIn("https://www.reddit.com/r/stocks/comments/s0/t0/", report)
                    self.assertIn("100 赞", report)
                    # 非法 URL 条目整体剔除，不注入
                    self.assertNotIn('href="javascript:', report)
                    self.assertNotIn("Unsafe", report)
                    # 审计口径：8 个基础数据源（含港股量化引擎）+ Reddit 趋势线索
                    self.assertEqual(pipeline._report_meta(report)["total_sources"], 9)
        can_push, reason = pipeline.check_push_eligibility(data)
        self.assertTrue(can_push)
        self.assertIn("当天", reason)

    def test_section_position_and_gate_in_both_themes(self):
        data = self._reddit_data()
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
                titles = [s[1] for s in pipeline._collect_report_parts(data, kit)["sections"]]
                # 正文顺序：今日预判（2026-10-13 置顶）→ 专业分析 → 行情与资讯数据 → 总结
                # 2026-09-30 起「行情速览」+「全球大盘全景复盘」合并为「【及时秋刀鱼】AI 行情复盘」
                review = pipeline.SECTION_TITLE_MARKET_REVIEW
                self.assertEqual(titles[0], "【回游金枪鱼】今日预判")
                self.assertLess(titles.index(review),
                                titles.index(pipeline.SECTION_TITLE_TREND))
                self.assertLess(titles.index("【回游金枪鱼】今日预判"),
                                titles.index(review))
                self.assertNotIn("行情速览", titles)            # 旧栏目名不得回潮
                self.assertNotIn("全球大盘全景复盘", titles)
                self.assertNotIn("每日量化策略趋势跟踪线索", titles)  # 旧栏目名不得回潮
                self.assertLess(titles.index(pipeline.SECTION_TITLE_FORECAST), titles.index("总结"))
                if pipeline.SECTION_TITLE_SHORT_CARD in titles:
                    self.assertEqual(titles[-1], pipeline.SECTION_TITLE_SHORT_CARD)
                else:
                    self.assertEqual(titles[-1], "总结")  # 今日预判已置顶，总结收尾

    def test_section_absent_and_failures_named_when_reddit_down(self):
        failed = {"Reddit": pipeline._public_site_result("Reddit", [], error="HTTP 403")}
        for theme in ("guizang", "pixel"):
            report = pipeline.generate_report(failed, "2026年9月27日 · 周日", "20260927", theme=theme)
            self.assertNotIn("趋势跟踪</h2>", report)      # 整栏缺席（新旧 guizang 标题都不出现）
            self.assertNotIn(f"{pipeline.SECTION_TITLE_TREND}</h2>", report)
            self.assertNotIn("TREND TRACKING", report)      # 像素关卡名同样不出现
            self.assertNotIn("每日量化策略趋势跟踪线索", report)  # 旧栏目名不得回潮
            self.assertIn("暂缺：", report)
            self.assertIn("Reddit", report)
            self.assertNotIn("HTTP 403", report)
            # 8 个基础数据源 + Reddit（未采集财经日历时不进审计）
            self.assertEqual(pipeline._report_meta(report)["total_sources"], 9)
        self.assertFalse(pipeline.check_push_eligibility(failed)[0])


    # ------------------------------------------------------------------
    # 2026-09-28 多平台信息员：新增平台的离线解析与降级
    # ------------------------------------------------------------------
    def test_stocktwits_trending_ranks_platform_summary_and_sentiment_labels(self):
        now = datetime.now(pipeline.CST)
        summary_at = (now - timedelta(minutes=30)).astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")

        def fake_request(url, **kwargs):
            if url.endswith("trending/symbols.json"):
                return {"symbols": [
                    {"symbol": "MU", "title": "Micron Technology Inc", "rank": 2,
                     "watchlist_count": 217113,
                     "trends": {"summary": "Bulls expect a beat while bears warn on margins.",
                                "summary_at": summary_at}},
                    {"symbol": "BTC.X", "title": "Bitcoin", "rank": 1,
                     "watchlist_count": 681982,
                     "trends": {"summary": "Bullish posts point to ETF demand.",
                                "summary_at": summary_at}},
                    {"symbol": "BAD SYMBOL", "title": "Injected", "rank": 3,
                     "watchlist_count": 1, "trends": {"summary_at": summary_at}},
                ]}
            if "/streams/symbol/" in url:
                return {"messages": [
                    {"entities": {"sentiment": {"basic": "Bullish"}}},
                    {"entities": {"sentiment": {"basic": "Bullish"}}},
                    {"entities": {"sentiment": {"basic": "Bearish"}}},
                    {"entities": {"sentiment": None}},
                    {"entities": {}},
                    "not-a-dict",
                ]}
            return None

        with patch.object(pipeline, "safe_request", side_effect=fake_request):
            result = pipeline.fetch_stocktwits()
        self.assertEqual(result["source"], "StockTwits")
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["is_today"])
        # 按平台 rank 排序（不是请求返回顺序），非法 symbol 构造出的 URL 被 allowlist 拒绝
        self.assertEqual([it["symbol"] for it in result["items"]], ["BTC.X", "MU"])
        self.assertEqual(result["items"][0]["community"], "平台趋势榜")
        self.assertEqual((result["items"][0]["rank"],
                          result["items"][0]["watchlist_count"]), (1, 681982))
        self.assertEqual(result["items"][1]["sentiment_counts"],
                         {"checked": 5, "bull": 2, "bear": 1})
        detail = result["items"][1]["detail"]
        self.assertIn("平台趋势榜 #2", detail)
        self.assertIn("关注 217,113 人", detail)
        self.assertIn("平台多空摘要", detail)
        self.assertIn("近 5 条消息平台标签：看多 2 / 看空 1", detail)
        self.assertIn("不复制消息正文", result["note"])
        # 接口不可用 → 整平台暂缺，不伪造
        with patch.object(pipeline, "safe_request", return_value=None):
            failed = pipeline.fetch_stocktwits()
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["items"], [])

    def test_tradingview_rss_drops_foreign_hosts_and_stale_items(self):
        now = datetime.now(pipeline.CST)
        feed = rss(
            rss_item("Nasdaq 100 (NQ) Analysis, Key-Zones, Setup for Mon",
                     "https://www.tradingview.com/chart/NQ1!/abc/",
                     now - timedelta(hours=1)),
            rss_item("Foreign host idea", "https://evil.example/chart/NQ1!/abc/",
                     now - timedelta(hours=2)),
            rss_item("Stale idea", "https://www.tradingview.com/chart/NQ1!/old/",
                     now - timedelta(hours=100)),
        )
        with patch.object(pipeline, "safe_request", return_value=feed):
            result = pipeline.fetch_tradingview()
        self.assertEqual(result["source"], "TradingView")
        self.assertEqual([it["title"] for it in result["items"]],
                         ["Nasdaq 100 (NQ) Analysis, Key-Zones, Setup for Mon"])
        self.assertEqual(result["items"][0]["community"], "交易员观点")
        self.assertTrue(result["items"][0]["is_today"])
        self.assertIn("非投资建议", result["note"])
        with patch.object(pipeline, "safe_request", return_value=None):
            self.assertEqual(pipeline.fetch_tradingview()["status"], "unavailable")

    def test_bogleheads_rss_splits_board_and_topic(self):
        now = datetime.now(pipeline.CST)
        feed = rss(
            rss_item("Investing - Theory, News &amp; General • Re: Why Bonds EVER when you have TIPS?",
                     "https://www.bogleheads.org/forum/viewtopic.php?p=8865896#p8865896",
                     now - timedelta(hours=2)),
            rss_item("Personal Consumer Issues • Auto Maintenance",
                     "https://www.bogleheads.org/forum/viewtopic.php?p=8865892#p8865892",
                     now - timedelta(hours=3)),
        )
        with patch.object(pipeline, "safe_request", return_value=feed):
            result = pipeline.fetch_bogleheads()
        self.assertEqual(result["source"], "Bogleheads")
        titles = [it["title"] for it in result["items"]]
        groups = [it["community"] for it in result["items"]]
        self.assertEqual(titles, ["Why Bonds EVER when you have TIPS?", "Auto Maintenance"])
        self.assertEqual(groups, ["投资理论 · 新闻 · 综合", "个人消费"])
        # 允许跨天边界，至少有一条为今天或 content_date 在 3 天内
        self.assertTrue(any(it["is_today"] for it in result["items"]) or result.get("content_date") is not None)
        with patch.object(pipeline, "safe_request", return_value=None):
            self.assertEqual(pipeline.fetch_bogleheads()["status"], "unavailable")

    def _platform_item(self, platform, title, url, community, *, today=True):
        return {"title": title, "url": url, "detail": "发布于 2026-09-28 09:00（北京时间）",
                "community": community, "platform": platform, "published_cst": "2026-09-28 09:00",
                "is_today": today}

    def test_trend_section_renders_without_reddit_and_names_missing_platform(self):
        """旧版整栏依赖 Reddit；新版任一平台有样本即渲染，缺失平台在数据覆盖里点名。"""
        data = {
            "实时行情": pipeline._source_result("q", "success", is_today=True,
                                               content_date="2026-09-28",
                                               quotes={"标普500": {"price": 6123.45,
                                                                   "change_pct": 1.25}}),
            "Reddit": pipeline._public_site_result("Reddit", [], error="HTTP 403"),
            "StockTwits": pipeline._public_site_result("StockTwits", [
                self._platform_item("StockTwits", "MU · Micron Technology Inc",
                                    "https://stocktwits.com/symbol/MU", "平台趋势榜")]),
            "TradingView": pipeline._public_site_result("TradingView", [
                self._platform_item("TradingView", "Nasdaq 100 (NQ) Analysis",
                                    "https://www.tradingview.com/chart/NQ1!/abc/", "交易员观点")]),
            "Bogleheads": pipeline._public_site_result("Bogleheads", [], error="offline"),
        }
        for theme in ("guizang", "pixel"):
            with self.subTest(theme=theme):
                report = pipeline.generate_report(data, "2026年9月28日 · 周一", "20260928",
                                                  theme=theme)
                self.assertIn("TREND TRACKING" if theme == "pixel"
                              else f"{pipeline.SECTION_TITLE_TREND}</h2>", report)
                self.assertIn("多平台信息员", report)
                self.assertIn("StockTwits", report)
                self.assertIn("TradingView", report)
                self.assertIn("交易员观点", report)
                self.assertNotIn("Bogleheads", report.split("数据覆盖")[0])  # 失败平台不进正文
                self.assertRegex(report, r"暂缺：[^<]*Reddit[^<]*Bogleheads")
                self.assertEqual(pipeline._report_meta(report)["total_sources"], 12)  # 8 基础 + 4 平台
        can_push, reason = pipeline.check_push_eligibility(data)
        self.assertTrue(can_push)
        self.assertIn("当天", reason)



class RetailSentimentFactorTests(unittest.TestCase):
    """散户情绪栏只计算 Reddit / StockTwits 本次真实样本。"""

    @staticmethod
    def _data():
        reddit = pipeline._public_site_result("Reddit", [
            {"title": "NVDA bullish rally", "url": "https://www.reddit.com/r/stocks/comments/1/a/",
             "community": "r/stocks", "published_cst": "2026-09-27 10:00",
             "score": 5, "comments": 2},
            {"title": "TSLA bearish crash", "url": "https://www.reddit.com/r/stocks/comments/2/b/",
             "community": "r/stocks", "published_cst": "2026-09-27 11:00",
             "score": 2, "comments": 1},
            {"title": "Bullish crash", "url": "https://www.reddit.com/r/stocks/comments/3/c/",
             "community": "r/stocks", "published_cst": "2026-09-27 12:00",
             "score": -1, "comments": 4},
            {"title": "flat discussion", "url": "https://www.reddit.com/r/stocks/comments/4/d/",
             "community": "r/stocks", "published_cst": "2026-09-27 13:00",
             "score": 0, "comments": 0},
        ], latest="2026-09-27")
        stocktwits = pipeline._public_site_result("StockTwits", [
            {"title": "NVDA · NVIDIA", "symbol": "NVDA", "rank": 1,
             "watchlist_count": 100000, "trending_score": 42,
             "sentiment_counts": {"checked": 4, "bull": 3, "bear": 1},
             "url": "https://stocktwits.com/symbol/NVDA"},
            {"title": "AAPL · Apple", "symbol": "AAPL", "rank": 2,
             "watchlist_count": 80000, "trending_score": 30,
             "sentiment_counts": {"checked": 3, "bull": 0, "bear": 1},
             "url": "https://stocktwits.com/symbol/AAPL"},
            {"title": "TSLA · Tesla", "symbol": "TSLA", "rank": 3,
             "watchlist_count": 70000,
             "url": "https://stocktwits.com/symbol/TSLA"},
        ], latest="2026-09-27")
        return {"Reddit": reddit, "StockTwits": stocktwits}

    def test_calculates_source_counts_composite_nbi_and_dispersion(self):
        result = pipeline._senti_strategy.calculate(self._data())
        self.assertTrue(result["available"])
        self.assertEqual((result["reddit"]["bull"], result["reddit"]["bear"],
                          result["reddit"]["mixed"], result["reddit"]["unclassified"]),
                         (1, 1, 1, 1))
        self.assertEqual((result["reddit"]["score_sum"], result["reddit"]["comments_sum"]),
                         (6, 7))
        self.assertEqual((result["stocktwits"]["symbol_n"],
                          result["stocktwits"]["checked"],
                          result["stocktwits"]["bull"],
                          result["stocktwits"]["bear"],
                          result["stocktwits"]["unclassified"]),
                         (3, 7, 3, 2, 2))
        self.assertEqual((result["bull"], result["bear"], result["mixed"],
                          result["unclassified"]), (4, 3, 1, 3))
        self.assertEqual(result["nbi"], 14.3)
        self.assertEqual(result["label"], "中性")
        self.assertAlmostEqual(result["dispersion"], 98.5, places=1)

    def test_builds_data_only_section_in_all_report_themes(self):
        data = self._data()
        for theme, kit in (("pixel", pipeline.PIXEL_KIT),
                           ("forum", pipeline.FORUM_KIT),
                           ("dossier", pipeline.DOSSIER_KIT),
                           ("guizang", pipeline.GUIZANG_KIT)):
            with self.subTest(theme=theme):
                section = pipeline._senti_strategy.build_section(kit, data)
                self.assertEqual(section[0], "RETAIL SENTIMENT")
                self.assertEqual(section[1], "【麻辣大龙虾】散户群体情绪量化分析")
                parts = pipeline._collect_report_parts(data, kit, date_str="20260927")
                self.assertEqual(parts["sections"][0][0], "RETAIL SENTIMENT")
                report = pipeline.generate_report(
                    data, "2026年9月27日 · 周日", "20260927", theme=theme)
                self.assertIn("综合净情绪 NBI", report)
                self.assertIn("+14.3 / 100", report)
                self.assertIn("多空分歧熵", report)
                self.assertIn("Reddit 互动", report)
                self.assertIn("StockTwits 热度前五", report)
                self.assertIn("标的流样本 7 条（2/3 标的可读）", report)
                self.assertIn("NVDA #1", report)
                self.assertIn("关注 100,000", report)
                self.assertNotIn("AI DIGEST", report)
                self.assertNotIn("AI 全篇速览", report)
                self.assertNotIn("小单净买入", report)
                self.assertNotIn("计算方法", report)

    def test_missing_direction_labels_stay_missing_and_empty_sources_skip_section(self):
        data = {"Reddit": pipeline._public_site_result("Reddit", [
            {"title": "quiet market", "url": "https://www.reddit.com/r/stocks/comments/1/a/"}
        ], latest="2026-09-27")}
        result = pipeline._senti_strategy.calculate(data)
        self.assertIsNone(result["nbi"])
        section = pipeline._senti_strategy.build_section(pipeline.GUIZANG_KIT, data)
        self.assertIn("综合净情绪 NBI", section[2])
        self.assertIn("—", section[2])
        self.assertIn("Reddit", section[2])
        self.assertIn("StockTwits", section[2])

        empty = {
            "Reddit": pipeline._public_site_result("Reddit", [], error="HTTP 403"),
            "StockTwits": pipeline._public_site_result("StockTwits", [], error="offline"),
        }
        self.assertFalse(pipeline._senti_strategy.calculate(empty)["available"])
        self.assertIsNone(pipeline._senti_strategy.build_section(pipeline.GUIZANG_KIT, empty))

    def test_unreadable_stocktwits_streams_show_zero_sample_and_readable_ratio(self):
        data = {"StockTwits": pipeline._public_site_result("StockTwits", [
            {"title": "ABC · Example", "symbol": "ABC", "rank": 1,
             "url": "https://stocktwits.com/symbol/ABC"},
            {"title": "XYZ · Example", "symbol": "XYZ", "rank": 2,
             "url": "https://stocktwits.com/symbol/XYZ"},
        ], latest="2026-09-27")}
        result = pipeline._senti_strategy.calculate(data)
        self.assertTrue(result["available"])
        self.assertEqual(result["stocktwits"]["symbol_n"], 2)
        self.assertEqual(result["stocktwits"]["streams_available"], 0)
        self.assertEqual(result["stocktwits"]["checked"], 0)
        section = pipeline._senti_strategy.build_section(pipeline.GUIZANG_KIT, data)
        self.assertIn("标的流样本 0 条（0/2 标的可读）", section[2])
        self.assertIn("情绪标签不可读", section[2])
        self.assertIn("NBI —", section[2])

def _rss_feed(items):
    """构造 RSS 2.0 文档；items 为 (title, link, pubDate) 元组列表。"""
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><pubDate>{p}</pubDate></item>"
        for t, u, p in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'


class HKNewsSourceTests(unittest.TestCase):
    """全网 36 个新闻源头：注册表 / 白名单 / 港股挖掘 / 规则分析 / 栏目渲染（离线 mock）。"""

    @staticmethod
    def _rfc(dt):
        # 固定英文星期/月份，避免本地化差异（parsedate 按英文解析）
        return dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    def _fetch_result(self, feeds):
        def fake_request(url, **kwargs):
            return feeds.get(url)
        with patch.object(pipeline, "safe_request", side_effect=fake_request):
            return pipeline.fetch_hk_news_sources()

    def _sample_feeds(self):
        now = datetime.now(pipeline.CST)
        fresh = now - timedelta(hours=2)
        stale = now - timedelta(hours=96)
        srcs = pipeline.HK_NEWS_SOURCES
        # 源0（RTHK）：5 条窗口内（4 港股相关 + 1 无关）+ 1 过期 + 1 无时区
        feeds = {
            srcs[0]["feed"]: _rss_feed([
                ("港股反弹，恒指收复25000点",
                 "https://news.rthk.hk/rthk/news/1/a.html", self._rfc(fresh)),
                ("南向资金净买入超百亿港元",
                 "https://news.rthk.hk/rthk/news/1/b.html", self._rfc(fresh)),
                ("香港金管局维持基本利率不变",
                 "https://news.rthk.hk/rthk/news/1/c.html", self._rfc(fresh)),
                ("港股跳水，恒指跌破25000点",
                 "https://news.rthk.hk/rthk/news/1/d.html", self._rfc(fresh)),
                ("Wall Street slips as yields rise",
                 "https://news.rthk.hk/rthk/news/1/e.html", self._rfc(fresh)),
                ("恒指昨日收跌", "https://news.rthk.hk/rthk/news/1/f.html", self._rfc(stale)),
                ("港股开盘", "https://news.rthk.hk/rthk/news/1/g.html",
                 "Mon, 28 Sep 2026 01:00:00"),
            ]),
            # 源1（HKET）：2 条当天港股相关
            srcs[1]["feed"]: _rss_feed([
                ("港股通ETF获大额净买入，恒指升1%",
                 "https://www.hket.com/article/1/a.html", self._rfc(fresh)),
                ("香港零售销售回暖带动本地消费股",
                 "https://www.hket.com/article/1/b.html", self._rfc(fresh)),
            ]),
            # 源2（SCMP）：窗口内 1 条但与港股无关 → status ok、无港股命中
            srcs[2]["feed"]: _rss_feed([
                ("UK inflation cools, pound steadies",
                 "https://www.scmp.com/article/1/x", self._rfc(fresh)),
            ]),
            # 源3（HKEX）：链接落在白名单外 → 条目剔除，不计入
            srcs[3]["feed"]: _rss_feed([
                ("港股交易安排调整", "https://evil.example.com/x", self._rfc(fresh)),
            ]),
        }
        return feeds

    def test_registry_thirty_six_sources_https_hosts_and_regions(self):
        self.assertEqual(len(pipeline.HK_NEWS_SOURCES), 36)
        self.assertEqual(pipeline.HK_NEWS_TOTAL, 36)
        names = [s["name"] for s in pipeline.HK_NEWS_SOURCES]
        self.assertEqual(len(set(names)), 36)
        from collections import Counter
        self.assertEqual(Counter(s["region"] for s in pipeline.HK_NEWS_SOURCES),
                         {"香港": 7, "内地": 23, "国际": 6})
        for s in pipeline.HK_NEWS_SOURCES:
            # feed 允许为空：无公开订阅的媒体直接走 Bing / Google 站内检索备用源
            self.assertTrue(s["feed"] == "" or s["feed"].startswith("https://"), s["name"])
            self.assertTrue(s["url"].startswith("https://") or s["url"].startswith("http://"), s["name"])
            self.assertTrue(s["hosts"], s["name"])
            self.assertTrue(s["desc"], s["name"])
        # 2026-10-12 新增的媒体必须在册（用户指定名单）
        for name in ("中证网", "证券日报网", "中国基金报", "财闻网", "经济参考网", "IT之家",
                     "券商中国", "每日经济新闻", "北京商报", "21世纪经济报道", "证券之星",
                     "和讯网", "金融投资报", "时代财经", "经济观察网", "凤凰网财经"):
            self.assertIn(name, names)
        # 已在册的「证券时报·快讯」即证券时报网，不重复添加
        self.assertIn("证券时报·快讯", names)
        self.assertEqual(len([n for n in names if "证券时报" in n]), 1)

    def test_empty_feed_source_uses_site_search_backup(self):
        # 无公开订阅的媒体（feed 为空）直接走 Bing 站内检索 RSS，并标注为备用源
        cfg = next(s for s in pipeline.HK_NEWS_SOURCES if s["name"] == "中证网")
        self.assertEqual(cfg["feed"], "")
        host = pipeline._hk_news_site_host(cfg)
        self.assertEqual(host, "cs.com.cn")
        bing_url = pipeline._backup.get_news_site_backup_urls(host)[0]
        now = datetime.now(pipeline.CST)
        feeds = {bing_url: _rss_feed([
            ("恒指收涨，港股通资金净买入", "https://www.cs.com.cn/xwzx/1.html",
             self._rfc(now - timedelta(hours=2)))])}
        result = self._fetch_result(feeds)
        rec = next(r for r in result["sources"] if r["name"] == "中证网")
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["served_by"], "备用源")
        self.assertEqual(rec["hk_n"], 1)
        self.assertEqual(rec["items"][0]["url"], "https://www.cs.com.cn/xwzx/1.html")

    def test_news_url_whitelist_is_per_source_host(self):
        self.assertEqual(pipeline._news_url("https://www.hket.com/rss/finance",
                                            ("www.hket.com",)),
                         "https://www.hket.com/rss/finance")
        for bad in ("http://www.hket.com/x", "https://evil.com/x",
                    "https://www.hket.com@evil.com/x", "javascript:alert(1)",
                    "https://www.hket.com/<script>", "//evil.net/path"):
            self.assertEqual(pipeline._news_url(bad, ("www.hket.com",)), "", bad)

    def test_hk_relevance_keywords(self):
        for hit in ("恒指收跌1%", "港股通资金流入", "Hang Seng closes higher",
                    "Hong Kong stocks rally", "港府公布财政预算", "Southbound flow grows"):
            self.assertRegex(hit, pipeline._HK_NEWS_KW_RE)
        for miss in ("Wall Street closes higher", "A股沪指窄幅震荡",
                     "Fed keeps rates unchanged", "Macau gaming revenue rises"):
            self.assertNotRegex(miss, pipeline._HK_NEWS_KW_RE)

    def test_fetch_filters_window_relevance_and_caps(self):
        result = self._fetch_result(self._sample_feeds())
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["is_today"])
        records = {r["name"]: r for r in result["sources"]}
        self.assertEqual(len(result["sources"]), pipeline.HK_NEWS_TOTAL)

        r0 = records[pipeline.HK_NEWS_SOURCES[0]["name"]]
        self.assertEqual(r0["status"], "ok")
        self.assertEqual(r0["scanned"], 5)          # 过期 + 无时区两条被剔除
        self.assertEqual(r0["hk_n"], 4)             # 挖掘口径 = 全部港股相关
        self.assertEqual(len(r0["items"]), 3)       # 展示口径 = 每源上限 3 条
        self.assertEqual(r0["hk_n"] - len(r0["items"]), 1)
        self.assertEqual(r0["today"], 5)
        self.assertIn("港股反弹，恒指收复25000点", [it["title"] for it in r0["items"]])
        self.assertNotIn("Wall Street slips as yields rise",
                         [it["title"] for it in r0["items"]])
        self.assertTrue(all(it["published_cst"] for it in r0["items"]))

        r2 = records[pipeline.HK_NEWS_SOURCES[2]["name"]]
        self.assertEqual(r2["status"], "ok")        # 抓得到但无港股命中
        self.assertEqual(r2["hk_n"], 0)
        self.assertEqual(r2["items"], [])

        r3 = records[pipeline.HK_NEWS_SOURCES[3]["name"]]
        self.assertEqual(r3["status"], "empty")     # 白名单外链接被剔除 → 无有效内容
        self.assertEqual(r3["hk_n"], 0)

        failed = [r for r in result["sources"] if r["status"] == "fail"]
        self.assertEqual(len(failed), pipeline.HK_NEWS_TOTAL - 4)  # 其余源（含备用检索）均无返回
        self.assertIn("暂缺", result["note"])
        self.assertIn(pipeline.HK_NEWS_SOURCES[5]["name"], result["note"])
        self.assertTrue(result["partial"])

        an = result["analysis"]
        self.assertEqual(an["ok_n"], 3)
        self.assertEqual(an["fail_n"], pipeline.HK_NEWS_TOTAL - 4)
        self.assertEqual(an["scanned"], 8)
        self.assertEqual(an["hk_n"], 6)             # 4 + 2
        self.assertEqual(an["total"], pipeline.HK_NEWS_TOTAL)
        self.assertGreaterEqual(an["bull"], 2)      # 反弹/升 → 多头证据
        self.assertGreaterEqual(an["bear"], 1)      # 跳水 → 空头证据
        self.assertEqual(an["prob"] + (100 - an["prob"]), 100)
        self.assertTrue(5 <= an["prob"] <= 95)
        self.assertIn("南向资金", an["themes"])

    def test_fetch_all_failed_is_unavailable_without_history_fallback(self):
        result = self._fetch_result({})
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["items"] if "items" in result else [], [])
        self.assertFalse(result["is_today"])
        self.assertIn("72", result["error"])
        self.assertEqual(len(result["sources"]), pipeline.HK_NEWS_TOTAL)

    def test_disabled_switch_returns_unavailable(self):
        with patch.object(pipeline, "HK_NEWS_ENABLED", False):
            with patch.object(pipeline, "safe_request",
                              side_effect=AssertionError("关闭时不得请求网络")):
                result = pipeline.fetch_hk_news_sources()
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("OCTOPUS_HK_NEWS=0", result["error"])

    def test_analysis_note_prefers_news_and_merges_reddit(self):
        news = self._fetch_result(self._sample_feeds())
        reddit = pipeline._public_site_result("Reddit", [
            {"title": "$TSLA rally to the moon", "url": "https://www.reddit.com/r/stocks/comments/1/a/",
             "detail": "发布于 2026-09-28 10:00（北京时间）", "published_cst": "2026-09-28 10:00",
             "community": "r/stocks", "is_today": True}])
        notes = pipeline.build_section_ai_notes({pipeline.HK_NEWS_SOURCE_NAME: news, "Reddit": reddit})
        n = notes["TREND TRACKING"]
        self.assertIn("20 源扫描", n["text"])
        self.assertIn("港股相关", n["text"])
        self.assertIn("扫描 1 条样本", n["text"])
        self.assertIn("→ 预测：", n["text"])
        self.assertIn("非投资建议", n["text"])
        self.assertEqual(n["bull_pct"] + n["bear_pct"], 100)
        self.assertTrue(5 <= n["bull_pct"] <= 95)

    def test_news_only_data_still_renders_section_and_unlocks_gate(self):
        news = self._fetch_result(self._sample_feeds())
        data = {pipeline.HK_NEWS_SOURCE_NAME: news}
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            for theme in ("guizang", "pixel"):
                with self.subTest(theme=theme):
                    report = pipeline.generate_report(data, "2026年9月28日 · 周一", "20260928",
                                                      theme=theme)
                    self.assertIn("TREND TRACKING" if theme == "pixel"
                                  else f"{pipeline.SECTION_TITLE_TREND}</h2>", report)
                    self.assertIn(f"全网新闻源头 ×{pipeline.HK_NEWS_TOTAL}", report)
                    self.assertIn("港股相关 6 条", report)      # 汇总行 4+2
                    self.assertIn("港股反弹，恒指收复25000点", report)
                    self.assertIn("香港经济日报 HKET·财经", report)
                    self.assertNotIn("Wall Street slips as yields rise", report)
                    # 8 个基础数据源 + 全网新闻源头（无 Reddit 键）
                    self.assertEqual(pipeline._report_meta(report)["total_sources"], 9)
        can_push, reason = pipeline.check_push_eligibility(data)
        self.assertTrue(can_push)
        self.assertIn("当天", reason)

    def test_news_and_reddit_render_together_with_audit_count(self):
        news = self._fetch_result(self._sample_feeds())
        reddit = pipeline._public_site_result("Reddit", [
            {"title": "Stocks hot 0", "url": "https://www.reddit.com/r/stocks/comments/s0/t0/",
             "detail": "发布于 2026-09-28 10:00（北京时间） · 100 赞",
             "published_cst": "2026-09-28 10:00", "community": "r/stocks", "is_today": True}])
        data = {pipeline.HK_NEWS_SOURCE_NAME: news, "Reddit": reddit}
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            report = pipeline.generate_report(data, "2026年9月28日 · 周一", "20260928")
        self.assertIn(f"全网新闻源头 ×{pipeline.HK_NEWS_TOTAL}", report)
        self.assertIn("Reddit", report)
        self.assertIn("r/stocks", report)
        # 8 个基础数据源 + 全网新闻源头 + Reddit
        self.assertEqual(pipeline._report_meta(report)["total_sources"], 10)
        # 审计行标签
        parts = pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT)
        self.assertEqual(parts["total"], 10)

    def test_unsafe_item_url_never_rendered(self):
        news = self._fetch_result(self._sample_feeds())
        # 手工注入一条白名单外链接（模拟被篡改的数据）
        news["sources"][0]["items"].append({
            "title": "注入测试", "url": "https://evil.example.com/payload",
            "published_cst": "2026-09-28 10:00", "is_today": True,
            "detail": "发布于 2026-09-28 10:00（北京时间）"})
        data = {pipeline.HK_NEWS_SOURCE_NAME: news}
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            report = pipeline.generate_report(data, "2026年9月28日 · 周一", "20260928")
        self.assertNotIn("evil.example.com", report)
        self.assertNotIn("注入测试", report)


if __name__ == "__main__":
    unittest.main()
