"""无需网络的日报新鲜度回归测试。"""
import datetime as dt
import importlib.util
from html.parser import HTMLParser
import os
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# pipeline 在导入时只需要 requests 存在；本测试不发出 HTTP 请求。
sys.modules.setdefault("requests", types.SimpleNamespace())
MODULE_PATH = Path(__file__).parents[1] / "output" / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class ReportFreshnessTests(unittest.TestCase):
    def test_compact_push_html_preserves_section_text_and_clickable_links(self):
        original = (
            '<!doctype html><html><head><meta name="octopus-report-date" content="20260929"></head>'
            '<body><header>刊头</header><!--SPLIT--><section><h2>市场复盘</h2>'
            '<table style="' + ('padding:0;margin:0;border-collapse:collapse;' * 50) + '"><tr><td>收盘</td><td>恒指 24643 点，涨幅 +1.2% '
            '<a href="https://example.com/report?a=1&amp;b=2">查看原文</a></td></tr></table>'
            '</section><!--FOOT--><footer>免责声明</footer></body></html>'
        )
        compact = pipeline._compact_html_for_push(original)
        self.assertIsNotNone(compact)
        self.assertLess(len(compact), len(original))
        self.assertIn("市场复盘", compact)
        self.assertIn("恒指 24643 点，涨幅 +1.2%", compact)
        self.assertIn('href="https://example.com/report?a=1&amp;b=2"', compact)
        self.assertIn("查看原文", compact)
        self.assertIn("刊头", compact)
        self.assertIn("免责声明", compact)
        self.assertEqual(len(pipeline._split_html_for_push(compact, limit=10000)), 1)

    def test_render_uses_current_quote_and_never_the_removed_static_quote(self):
        data = {
            "实时行情": pipeline._source_result(
                "test quote", "success", quotes={
                    "标普500": {"price": 6123.45, "change_pct": 1.25, "currency": "USD"}
                }
            ),
            "全球头条": pipeline._source_result("test news", "unavailable", headlines=[], error="offline"),
        }
        html = pipeline.generate_report(data, "2026年8月1日 · 周六", "20260801")
        self.assertIn("6,123", html)
        # 精简排版：缺失品种不出「数据暂缺」行，来源状态压成总结里的一行
        self.assertNotIn("数据暂缺", html)
        self.assertIn("总结", html)
        self.assertRegex(html, r"暂缺：[^<]*全球头条")
        self.assertNotIn("51,618 -2.19%", html)
        self.assertNotIn("3,813 +0.40%", html)

    def test_duplicate_output_gets_date_and_three_digit_random_name(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "daily_report.html"
            target.write_text("old", encoding="utf-8")
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                actual = pipeline.save_report("new", str(target), {})
            finally:
                pipeline.REPORT_DIR = old_report_dir
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertRegex(Path(actual).name, r"daily_report_\d{8}_\d{3}\.html")
            self.assertEqual(Path(actual).read_text(encoding="utf-8"), "new")
            self.assertEqual((Path(directory) / "latest.html").read_text(encoding="utf-8"), "new")

    def test_locked_daily_file_creates_new_timestamped_report(self):
        with tempfile.TemporaryDirectory() as directory:
            requested = str(Path(directory) / "daily_report_20260801.html")
            original_write = pipeline._atomic_write

            def locked_first_write(path, content):
                if path == requested:
                    raise PermissionError("file is locked")
                return original_write(path, content)

            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                with patch.object(pipeline, "_atomic_write", side_effect=locked_first_write):
                    actual = pipeline.save_report("newest", requested, {})
            finally:
                pipeline.REPORT_DIR = old_report_dir

            self.assertNotEqual(actual, requested)
            self.assertRegex(Path(actual).name, r"daily_report_\d{8}_\d{3}\.html")
            self.assertEqual(Path(actual).read_text(encoding="utf-8"), "newest")
            self.assertEqual((Path(directory) / "latest.html").read_text(encoding="utf-8"), "newest")

    # ------------------------------------------------------------------
    # 新版：港股名家频道 + 空区块不渲染 + 当天检验 + 每频道前 3 条
    # ------------------------------------------------------------------
    def _sample_data(self, yt_today=True, market_today=True):
        data = {
            "实时行情": pipeline._source_result(
                "test quote", "success", is_today=market_today, content_date="2026-08-01",
                quotes={
                    "标普500": {"price": 6123.45, "change_pct": 1.25, "currency": "USD"},
                    "上证指数": {"price": 3813.5, "change_pct": 0.4, "currency": "CNY"},
                },
            ),
            "港股名家频道": pipeline._source_result(
                "test channels", "success", is_today=yt_today, content_date="2026-08-01",
                channels=[{
                    "name": "郭思治（郭Sir）",
                    "desc": "香港著名股評人，專注大盤技術走勢。",
                    "url": "https://www.youtube.com/@KwokSirFinance",
                    "is_today": yt_today,
                    "newest_date": "2026-08-01 10:00",
                    "videos": [{
                        "title": "今日市场解读",
                        "video_id": "abc123",
                        "url": "https://www.youtube.com/watch?v=abc123",
                        "published": "2026-08-01T02:00:00+00:00",
                        "published_cst": "2026-08-01 10:00",
                        "is_today": yt_today,
                    }],
                }],
                unsupported=[{
                    "name": "智通財經App（微信公众号）",
                    "desc": "每日推送港股早報與板塊機會。",
                    "note": "微信公众号需登录，暂不支持自动抓取",
                }],
            ),
            "全球头条": pipeline._source_result("test news", "unavailable", headlines=[], error="offline"),
        }
        return data

    def test_new_layout_hides_channels_section_but_keeps_data(self):
        """2026-10-02：「港股名家频道」栏目在页面隐藏，抓取数据仍进审计与其他栏目。"""
        html = pipeline.generate_report(self._sample_data(), "2026年8月1日 · 周六", "20260801")
        self.assertNotIn("港股名家频道</h2>", html)   # 栏目头不再渲染
        self.assertNotIn("HK GURU CHANNELS", html)    # 像素关卡名也不再出现
        self.assertNotIn("郭思治（郭Sir）", html)      # 频道卡片整体隐藏
        self.assertNotIn("今日市场解读", html)
        self.assertNotIn("h-hk-01-01", html)          # 不留指向已隐藏栏目的锚点
        self.assertIn("当天", html)          # 当天徽标
        self.assertNotIn("📅 当天内容检验", html)   # 页面不显示检验横幅
        # 需登录/未配置的频道不在日报中渲染
        self.assertNotIn("智通財經App（微信公众号）", html)
        self.assertNotIn("微信公众号需登录", html)
        # 数据侧不变：港股名家频道仍是一个基础数据源，计入当天/总源审计
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["total_sources"], 8)
        self.assertGreaterEqual(meta["today_sources"], 2)   # 行情 + 港股名家频道

    def test_new_layout_omits_empty_sections_and_keeps_meta(self):
        data = self._sample_data()
        data["港股名家频道"] = pipeline._source_result("test channels", "unavailable",
                                                      channels=[], unsupported=[], error="offline")
        data["全球头条"] = pipeline._source_result("test news", "success", is_today=True,
                                                    content_date="2026-08-01",
                                                    headlines=["一则今天的全球头条"])
        html = pipeline.generate_report(data, "2026年8月1日 · 周六", "20260801")
        # 没有数据也没有需登录频道的卡片不渲染主体
        self.assertNotIn("郭思治（郭Sir）", html)
        self.assertNotIn("每个频道列出最新", html)
        # 总结仍一行留痕缺失来源
        self.assertIn("数据覆盖", html)
        self.assertIn("暂缺：", html)
        self.assertIn("港股名家频道", html)
        # 元信息可供 --push-only 二次当天检验
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["date"], "20260801")
        self.assertGreaterEqual(meta["today_sources"], 1)
        self.assertEqual(meta["total_sources"], 8)  # 8 个基础数据源（A股资讯已移除、含「港股量化引擎」）；多平台趋势线索另计，本样本未含

    def test_push_eligibility_requires_today_content(self):
        # 有内容但全部非当天 → 不推送
        data = self._sample_data(yt_today=False, market_today=False)
        can_push, reason = pipeline.check_push_eligibility(data)
        self.assertFalse(can_push)
        self.assertIn("当天", reason)
        # 有当天内容 → 推送
        can_push, reason = pipeline.check_push_eligibility(self._sample_data(yt_today=True))
        self.assertTrue(can_push)
        # 全部无内容 → 不推送
        empty = {k: pipeline._source_result(k, "unavailable", error="offline")
                 for k in ["实时行情", "港股名家频道", "全球头条", "东财快讯"]}
        can_push, reason = pipeline.check_push_eligibility(empty)
        self.assertFalse(can_push)
        self.assertIn("0/", reason)

    def test_channel_block_shows_only_top3(self):
        ch = {
            "name": "郭思治（郭Sir）", "url": "https://www.youtube.com/@KwokSirFinance",
            "is_today": True, "desc": "測試",
            "videos": [{"title": f"视频{i}", "url": f"https://x/{i}",
                        "published_cst": "2026-08-01 10:00", "is_today": True} for i in range(5)],
        }
        html = pipeline._channel_block(ch)
        # Retro Pixel 风格：每频道只列前 3 条，图标改为 cyber [>> FEED] / >> / ▶ / ■ 等
        # 兼容旧 ▶️ 计数与新风格：以实际渲染的视频标题数量为准
        rendered = sum(1 for i in range(5) if f"视频{i}" in html)
        self.assertEqual(rendered, pipeline.CHANNEL_TOP_N)
        self.assertIn("视频0", html)
        self.assertIn("视频2", html)
        self.assertNotIn("视频3", html)  # 第 4/5 条不展示

    def test_unsupported_channel_block_marks_zhanque(self):
        ch = {"name": "港股交易員（微博大V）", "desc": "測試",
              "note": "微博需登录 / 反爬限制，暂不支持自动抓取"}
        html = pipeline._channel_block(ch)
        self.assertIn("暂缺", html)
        self.assertIn("微博需登录", html)
        # Retro Pixel 风格：无内容时不伪造视频行，Badge 显示 [● 暂缺]
        self.assertNotIn("视频", html)

    def test_fetch_hk_channels_marks_manual_as_unsupported(self):
        # 全部为 manual 频道时：不发起任何请求，返回 unavailable + unsupported 列表
        manual = [{"name": "测试公众号", "desc": "", "kind": "manual",
                   "note": "需登录"}]
        with patch.object(pipeline, "HK_CHANNELS", manual), \
             patch.object(pipeline, "safe_request", return_value=None) as req:
            result = pipeline.fetch_hk_channels()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["channels"], [])
        self.assertEqual(len(result["unsupported"]), 1)
        self.assertEqual(result["unsupported"][0]["name"], "测试公众号")
        req.assert_not_called()  # manual 频道不产生网络请求

    def test_fetch_hk_channels_youtube_and_rss_kinds(self):
        # kind="rss"：safe_request 返回一个 RSS 2.0 文档 → 成功解析
        from datetime import datetime, timedelta
        now_cst = datetime.now(pipeline.CST)
        today_rfc = (now_cst - timedelta(hours=4)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>今日深度报告</title><link>https://example.com/a</link><pubDate>{today_rfc}</pubDate></item>
  <item><title>第二篇</title><link>https://example.com/b</link><pubDate>{today_rfc}</pubDate></item>
</channel></rss>"""
        conf = [
            {"name": "郭思治（郭Sir）", "desc": "", "kind": "youtube", "handle": "@KwokSirFinance"},
            {"name": "港股策略通訊（Substack）", "desc": "", "kind": "rss",
             "feed_url": "https://example.com/feed"},
            {"name": "青姐（胡孟青）", "desc": "", "kind": "manual", "note": "需登录"},
        ]
        with patch.object(pipeline, "HK_CHANNELS", conf), \
             patch.object(pipeline, "resolve_channel_id", return_value=None), \
             patch.object(pipeline, "safe_request", return_value=rss_xml):
            result = pipeline.fetch_hk_channels()
        # rss 成功 1 个；youtube 解析失败进入暂缺；manual 进入暂缺
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["channels"]), 1)
        self.assertEqual(result["channels"][0]["name"], "港股策略通訊（Substack）")
        self.assertEqual(len(result["channels"][0]["videos"]), 2)
        self.assertEqual(len(result["unsupported"]), 2)
        unsupported_names = {u["name"] for u in result["unsupported"]}
        self.assertEqual(unsupported_names, {"青姐（胡孟青）", "郭思治（郭Sir）"})
        self.assertTrue(any("暂缺" in u["note"] for u in result["unsupported"]))

    def test_failed_rss_feed_marks_unsupported_not_silent(self):
        # RSS 源抓取失败 → 进入 unsupported（页面标注暂缺），不会从页面消失
        conf = [{"name": "港股研究社（Bilibili）", "desc": "", "kind": "rss",
                 "feed_url": "https://rsshub.example/bilibili/user/video/1"}]
        with patch.object(pipeline, "HK_CHANNELS", conf), \
             patch.object(pipeline, "safe_request", return_value=None):
            result = pipeline.fetch_hk_channels()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["channels"], [])
        self.assertEqual(len(result["unsupported"]), 1)
        self.assertIn("暂缺", result["unsupported"][0]["note"])

    def test_rss2_pubdate_parsing(self):
        items = pipeline._parse_rss_items("""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>报告A</title><link>https://a/1</link><pubDate>Fri, 01 Aug 2026 12:00:00 +0800</pubDate></item>
  <item><title>报告B</title><link>https://a/2</link></item>
</channel></rss>""")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "报告A")
        self.assertEqual(items[0]["published_cst"], "2026-08-01 12:00")
        self.assertEqual(items[1]["published_cst"], "—")  # 无时间字段不崩溃

    def test_youtube_rss_parser_marks_today(self):
        # 用 RSS 文本验证解析逻辑（不联网）；日期动态生成，保证任何一天都能跑
        from datetime import datetime, timedelta
        now_cst = datetime.now(pipeline.CST)
        # 用当天/前一天的正午 UTC 时间构造，保证转换回北京时间后一定落在对应日期
        today_utc = f"{now_cst:%Y-%m-%d}T04:00:00+00:00"          # 北京时间当天 12:00
        yesterday_utc = f"{(now_cst - timedelta(days=1)):%Y-%m-%d}T12:00:00+00:00"  # 北京时间前一天 20:00
        rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>今日视频</title>
    <published>{today_utc}</published>
    <yt:videoId>abc123</yt:videoId>
  </entry>
  <entry>
    <title>昨日视频</title>
    <published>{yesterday_utc}</published>
    <yt:videoId>xyz789</yt:videoId>
  </entry>
</feed>"""
        root = pipeline.ET.fromstring(rss)
        videos = []
        for entry in root.findall("a:entry", pipeline.YT_NS):
            title = (entry.findtext("a:title", "", pipeline.YT_NS) or "").strip()
            published = entry.findtext("a:published", "", pipeline.YT_NS) or ""
            pub_cst = pipeline._cst_from_iso(published)
            videos.append({
                "title": title,
                "published_cst": pub_cst.strftime("%Y-%m-%d %H:%M") if pub_cst else "—",
                "is_today": pipeline._date_is_today(pub_cst),
            })
        self.assertTrue(videos[0]["is_today"])   # 当天 10:00 视频
        self.assertFalse(videos[1]["is_today"])  # 昨天视频


class _FakeResp:
    """模拟 PushPlus HTTP 响应。"""

    def __init__(self, code, msg="fake-msg", status_code=200):
        self._code = code
        self._msg = msg
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return {"code": self._code, "msg": self._msg}


class GoogleNewsSourceTests(unittest.TestCase):
    """2026-08-02 新增：全球头条改用 Google News 中文版。"""

    ZH_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>美联储释放降息信号 - 华尔街见闻</title><link>https://news.google.com/a</link><pubDate>Sat, 02 Aug 2026 04:00:00 GMT</pubDate></item>
  <item><title>科技股财报推动股市上涨 - 彭博</title><link>https://news.google.com/b</link><pubDate>Sat, 02 Aug 2026 03:00:00 GMT</pubDate></item>
</channel></rss>"""

    def test_fetch_google_news_uses_chinese_feed(self):
        with patch.object(pipeline, "safe_request", return_value=self.ZH_RSS) as req:
            result = pipeline.fetch_google_news()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source"], "Google News")
        self.assertEqual(result["headlines"][0]["title"], "美联储释放降息信号")
        self.assertEqual(result["headlines"][0]["source"], "华尔街见闻")
        self.assertEqual(result["headlines"][1]["title"], "科技股财报推动股市上涨")
        # 直接抓中文源
        self.assertIn("hl=zh-CN", req.call_args[0][0])

    def test_fetch_google_news_unavailable_marks_error(self):
        with patch.object(pipeline, "safe_request", return_value=None):
            result = pipeline.fetch_google_news()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["headlines"], [])


class EastmoneySourceTests(unittest.TestCase):
    """2026-08-02 新增：东方财富快讯（5 条最新新闻）与热门榜单（A股/港股/美股成交量前五）。"""

    def test_fetch_eastmoney_news_parses_five_items(self):
        payload = {"data": {"list": [
            {"title": f"<b>东财新闻{i}</b>", "url": f"https://finance.eastmoney.com/a/{i}.html",
             "showTime": "2026-08-02 10:00:00", "summary": f"摘要{i}"}
            for i in range(6)
        ]}}
        with patch.object(pipeline, "safe_request", return_value=payload):
            result = pipeline.fetch_eastmoney_news()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source"], "东方财富")
        self.assertEqual(len(result["headlines"]), 5)          # 只取 5 条
        self.assertNotIn("<b>", result["headlines"][0]["title"])  # 剥掉 HTML 标签
        self.assertEqual(result["headlines"][0]["summary"], "摘要0")

    def test_fetch_eastmoney_news_unavailable(self):
        with patch.object(pipeline, "safe_request", return_value=None):
            result = pipeline.fetch_eastmoney_news()
        self.assertEqual(result["status"], "unavailable")

    def test_fetch_hot_stocks_parses_three_markets(self):
        requested_page_sizes = []

        def fake_request(url, params=None, **kw):
            requested_page_sizes.append(params["pz"])
            return {"data": {"diff": [
                {"f12": f"60000{i}", "f14": f"股票{i}", "f2": "10.5", "f3": "9.87"}
                for i in range(10)
            ]}}

        with patch.object(pipeline, "safe_request", side_effect=fake_request):
            result = pipeline.fetch_hot_stocks()
        self.assertEqual(result["status"], "success")
        self.assertEqual(requested_page_sizes, [str(pipeline.HOT_STOCK_TOP_N)] * 3)
        self.assertEqual(set(result["markets"].keys()), {"A股", "港股", "美股"})
        self.assertEqual(len(result["markets"]["A股"]["stocks"]), pipeline.HOT_STOCK_TOP_N)
        self.assertEqual(result["markets"]["港股"]["stocks"][0]["code"], "600000")
        self.assertEqual(result["markets"]["美股"]["stocks"][4]["change_pct"], "9.87")

    def test_fetch_hot_stocks_unavailable(self):
        with patch.object(pipeline, "safe_request", return_value=None):
            result = pipeline.fetch_hot_stocks()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["markets"]["A股"]["stocks"], [])




class NewLayoutRenderingTests(unittest.TestCase):
    """2026-08-02 新增：东财快讯 / 热门榜单渲染（不含 AI 总览表）。"""

    def _rich_data(self):
        data = ReportFreshnessTests()._sample_data()
        data["全球头条"] = pipeline._source_result(
            "Google News", "success", is_today=True, content_date="2026-08-02",
            headlines=[{"title": "美联储释放降息信号", "source": "华尔街见闻",
                        "url": "", "published_cst": "2026-08-02 10:00", "is_today": True}])
        data["东财快讯"] = pipeline._source_result(
            "东方财富", "success", is_today=True, content_date="2026-08-02",
            headlines=[{"title": "A股三大指数集体收涨", "url": "", "time": "2026-08-02 15:30",
                        "summary": "沪指涨1.2%", "is_today": True}])
        data["热门榜单"] = pipeline._source_result(
            "东方财富热门榜", "success", is_today=True, content_date="2026-08-02",
            markets={m: {"desc": f"{m}测试", "stocks": [
                {"code": f"00000{i}", "name": f"{m}股票{i}", "price": "10.5", "change_pct": "9.87"}
                for i in range(10)]} for m in ["A股", "港股", "美股"]})
        return data

    def test_report_renders_new_sections(self):
        html = pipeline.generate_report(self._rich_data(), "2026年8月2日 · 周日", "20260802")
        self.assertIn("当天 5/8 源", html)  # 东财快讯与热门榜单只计入总结的数据覆盖与AI信号
        # 2026-10-02 起页面隐藏「东方财富快讯」栏目（与热门榜单一致，仅保留后台抓取供 AI 分析）
        self.assertNotIn("东方财富快讯</h2>", html)
        self.assertNotIn("EASTMONEY WIRE", html)
        self.assertNotIn("A股三大指数集体收涨", html)
        # 2026-08-06 起不再单独渲染三个成交量榜单栏目，只保留 AI 研判结果
        self.assertNotIn("A股成交量前五", html)
        self.assertNotIn("港股成交量前五", html)
        self.assertNotIn("美股成交量前五", html)
        # 2026-10-02 起「【无敌帝王蟹】全球头条」与「港股名家频道」两栏也在页面隐藏
        # （与东方财富快讯同口径：抓取 / 审计 / AI 分析输入不变，只是不成栏目）
        self.assertNotIn(f"{pipeline.SECTION_TITLE_GLOBAL_HEADLINES}</h2>", html)
        self.assertNotIn("GLOBAL HEADLINES", html)
        self.assertNotIn("港股名家频道</h2>", html)
        self.assertNotIn("h-gh-01", html)             # 头条正文锚点不再写入页面
        self.assertNotIn(">全球头条</h2>", html)      # 旧栏目头不得回潮
        self.assertNotIn("A股资讯</h2>", html)
        # 三个资讯栏目全部隐藏；A股资讯已删除，不再出现其栏目标题。
        # 不再渲染 AI 总览相关元素
        self.assertNotIn("AI 总览", html)
        self.assertNotIn("栏目 AI 研判表", html)
        self.assertNotIn("Gemini", html)
        self.assertNotIn("GEMINI", html)
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["total_sources"], 8)  # 8 个基础数据源（A股资讯已移除、含「港股量化引擎」）；多平台趋势线索另计，本样本未含

    def test_eastmoney_wire_hidden_on_page_but_feeds_ai_and_audit(self):
        """2026-10-02：东方财富快讯栏目在页面隐藏，但后台数据仍用于政策因子/策略研判/新闻情绪/审计。"""
        data = self._rich_data()
        data["东财快讯"] = pipeline._source_result(
            "东方财富", "success", is_today=True, content_date="2026-08-02",
            headlines=[
                {"title": "某大型房企债务违约爆雷引发市场担忧", "url": "",
                 "time": "2026-08-02 15:40", "summary": "", "is_today": True},
            ])
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(
                data, "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertNotIn("东方财富快讯</h2>", html)
            self.assertNotIn("EASTMONEY WIRE", html)
            # 东财快讯已隐藏，命中风险提示时必须保留完整标题（shown=False），不生成死链锚点
            self.assertIn("某大型房企债务违约爆雷引发市场担忧", html)
            self.assertNotIn("h-em-01", html)
        ai = pipeline.build_ai_analysis(data)
        em_risk = [r for r in ai["risks"] if "债务违约爆雷" in r["title"]][0]
        self.assertFalse(em_risk["shown"])

    def test_global_headlines_and_guru_hidden_but_feed_ai_and_audit(self):
        """2026-10-02：全球头条 / 港股名家频道栏目在页面隐藏，数据仍供 AI 分析与审计。"""
        data = self._rich_data()
        data["全球头条"] = pipeline._source_result(
            "Google News", "success", is_today=True, content_date="2026-08-02",
            headlines=[{"title": "某科技巨头业绩爆雷引发全球市场暴跌担忧",
                        "source": "华尔街见闻", "url": "",
                        "published_cst": "2026-08-02 10:00", "is_today": True}])
        data["港股名家频道"] = pipeline._source_result(
            "test channels", "success", is_today=True, content_date="2026-08-02",
            channels=[{"name": "郭思治（郭Sir）", "desc": "", "url": "",
                       "is_today": True, "newest_date": "2026-08-02 09:00",
                       "videos": [{"title": "名家警示：港股爆雷股名单更新", "video_id": "v1",
                                   "url": "https://www.youtube.com/watch?v=v1",
                                   "published": "2026-08-02T01:00:00+00:00",
                                   "published_cst": "2026-08-02 09:00", "is_today": True}]}],
            unsupported=[])
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(
                data, "2026年8月2日 · 周日", "20260802", theme=theme)
            for gone in (f"{pipeline.SECTION_TITLE_GLOBAL_HEADLINES}</h2>", "港股名家频道</h2>",
                         "GLOBAL HEADLINES", "HK GURU CHANNELS",
                         f"{pipeline.SECTION_TITLE_GLOBAL_HEADLINES}：", "港股名家频道："):
                self.assertNotIn(gone, html, f"{theme} 仍出现 {gone}")
            # 隐藏栏目不留锚点；命中风险提示时保留完整标题（shown=False）
            self.assertNotIn("h-gh-01", html)
            self.assertNotIn("h-hk-01-01", html)
            self.assertIn("某科技巨头业绩爆雷引发全球市场暴跌担忧", html)
            self.assertIn("名家警示：港股爆雷股名单更新", html)
            # 数据侧不变：两路仍计入基础数据源审计
            meta = pipeline._report_meta(html)
            self.assertEqual(meta["total_sources"], 8)
            self.assertGreaterEqual(meta["today_sources"], 4)
        ai = pipeline.build_ai_analysis(data)
        for key in ("业绩爆雷引发全球市场暴跌", "港股爆雷股名单更新"):
            risk = [r for r in ai["risks"] if key in r["title"]][0]
            self.assertFalse(risk["shown"])


class RetroPixelVisualTests(unittest.TestCase):
    """Retro Pixel v3：大图标、明确涨跌与 AI 主结论必须稳定渲染。"""

    def test_pixel_table_stacks_into_single_column(self):
        """多行多列排版：像素主题三列及以上按标准多行多列表格展示（含表头行 + 多列数据行）。"""
        html = pipeline._pixel_table(["日期", "事件", "重要度"],
                                     [["10-13", "美国 CPI", "★★★"]])
        self.assertEqual(html.count("<tr>"), 2)            # 1 行表头 + 1 行数据 = 2 行
        self.assertEqual(html.count("<td"), 6)             # 2 行 × 3 列 = 6 个单元格
        self.assertIn("日期", html)
        self.assertIn("事件", html)
        self.assertIn("重要度", html)
        self.assertIn("10-13", html)
        self.assertIn("美国 CPI", html)
        self.assertIn("★★★", html)
        self.assertIn("table-layout:fixed", html)

    def test_pixel_table_keeps_empty_cells_off_but_dashes_on(self):
        """多行多列表格：表头与占位短横「—」保留在对应列单元格中。"""
        html = pipeline._pixel_table(["名称", "涨跌", "成交额"],
                                     [["腾讯控股", "—", ""]])
        self.assertEqual(html.count("<tr>"), 2)
        self.assertIn("名称", html)
        self.assertIn("涨跌", html)
        self.assertIn("成交额", html)
        self.assertIn("腾讯控股", html)
        self.assertIn(">—</td>", html)

    def test_trend_badge_uses_color_arrow_and_text_triple_encoding(self):
        up = pipeline._trend_badge(1.25)
        down = pipeline._trend_badge("-2.50%")
        flat = pipeline._trend_badge(0)
        self.assertIn("▲ 涨 +1.25%", up)
        self.assertIn(pipeline.C_GREEN, up)
        self.assertIn("▼ 跌 -2.50%", down)
        self.assertIn(pipeline.C_RED, down)
        self.assertIn("■ 平 0.00%", flat)
        self.assertIn(pipeline.C_AMBER, flat)

    def test_report_prioritizes_pixel_icons_and_ai_core_content(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["实时行情"]["quotes"]["深证成指"] = {
            "price": 12345.67, "change_pct": -2.5, "currency": "CNY"
        }
        # 像素视觉回归显式走 pixel 主题，不依赖当前推送默认主题
        parts = pipeline._collect_report_parts(data, pipeline.PIXEL_KIT, date_str="20260802")
        kickers = [s[0] for s in parts["sections"]]
        marker = lambda key: f"LVL {kickers.index(key):02d} // {key}"
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802", theme="pixel")

        self.assertIn("OCTOPUS_OS v3.0", html)
        self.assertIn("aria-label=\"章鱼像素图标\"", html)
        self.assertIn(marker("STRATEGY READ"), html)
        self.assertIn(marker("MARKET REVIEW"), html)
        self.assertIn("// POLICY SHOCK", html)
        # 2026-10-14 重排：行情复盘（①）先于策略研判（④）
        self.assertLess(kickers.index("MARKET REVIEW"), kickers.index("STRATEGY READ"))
        self.assertEqual(kickers[0], "FORECAST")  # 今日预判置顶
        self.assertLess(kickers.index("SUMMARY"), kickers.index("SHORT CARD")
                        if "SHORT CARD" in kickers else len(kickers))
        if "SHORT CARD" in kickers:
            self.assertLess(kickers.index("FORECAST"), kickers.index("SHORT CARD"))
            self.assertIn(marker("SHORT CARD"), html)
        self.assertIn("QUANT CORE", html)
        self.assertIn("量化主结论 // QUANT THESIS", html)
        self.assertIn("FINAL TAKEAWAY // 核心结论", html)
        self.assertIn("▲ 涨 +1.25%", html)  # 标普行情
        self.assertIn("▼ 跌 -2.50%", html)  # 深证行情（AI 行情复盘：明细数字唯一出处）
        # 2026-09-09 页内去重：TECH READ 不再逐条复述 compact 徽标，只保留聚合
        self.assertIn("指数动能聚合", html)
        self.assertNotIn("明细数值见「AI 行情复盘」", html)  # 说明性脚注已移除
        # 逐指数 compact 徽标只在行情数据栏出现一次，不在专业分析栏重复
        self.assertEqual(html.count("▼ -2.50%"), 1)
        # 2026-10-13 起今日预判置顶，紧凑徽标的唯一出现位置在其内（最前）
        self.assertLess(html.find(marker("FORECAST")), html.find("▼ -2.50%"))
        self.assertLess(html.find("▼ -2.50%"), html.find(marker("MARKET REVIEW")))
        self.assertIn("▲ 涨 / UP", html)    # 页首方向图例
        self.assertIn("▼ 跌 / DOWN", html)
        self.assertNotIn("<style", html)     # 微信 / PushPlus 仍保持全内联样式

    def test_pixel_default_report_splits_with_theme_and_size_limits(self):
        data = NewLayoutRenderingTests()._rich_data()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802",
                                        theme="pixel")
        pieces = pipeline._split_html_for_push(html, 20_000)
        self.assertIsNotNone(pieces)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(piece) <= 20_000 for piece in pieces))
        self.assertTrue(all('name="octopus-theme" content="pixel"' in piece
                            for piece in pieces))
        joined = "".join(pieces)
        for kicker in ("MARKET REVIEW", "POLICY SHOCK", "SUMMARY", "FORECAST"):
            self.assertIn(kicker, joined)

    def test_watch_list_keeps_theme_only_and_omits_stock_rows(self):
        """2026-08-06 起 WATCH LIST // 明日关注 不再列出榜单个股，只保留主题行。"""
        data = NewLayoutRenderingTests()._rich_data()
        # 让舆情命中板块关键词，保证有「明日主题」可展示
        data["全球头条"]["headlines"].append({
            "title": "英伟达AI芯片需求超预期", "source": "测试源",
            "url": "", "published_cst": "2026-08-02 11:00", "is_today": True,
        })
        res = pipeline.build_ai_analysis(data)
        self.assertTrue(res["available"])
        self.assertNotIn("watch", res)          # 不再产出个股清单
        self.assertIn("AI/算力", res["themes"])  # 主题行保留
        html = pipeline._ai_analysis_block(res)
        self.assertIn("QUANT ALLOC // 量化配置", html)
        self.assertIn("★ THEME UNLOCKED // AI/算力", html)
        # 个股不再以「关注清单」形式渲染（榜单股名为 A股股票0 等）
        self.assertNotIn("<b>A股股票", html)


class GuizangThemeTests(unittest.TestCase):
    """归藏简洁排版 × 克莱因蓝 + 灰（2026-09-29 起）

    设计契约：全量内容压进单条微信消息（一页推）、纯内联样式、无 <style> / class /
    远程图片，克莱因蓝 #002FA7 是页面上唯一的有色，其余层级全部由灰阶承担。
    2026-10-07 起默认主题改为 pixel；本类的归藏视觉契约显式指定 theme="guizang"，
    另有一项回归锁定新默认主题及所有主题的解析。
    """

    def _html(self):
        return pipeline.generate_report(NewLayoutRenderingTests()._rich_data(),
                                        "2026年8月2日 · 周日", "20260802",
                                        theme="guizang")

    def test_default_theme_is_pixel_and_resolves_all_themes(self):
        self.assertEqual(pipeline.DEFAULT_PUSH_THEME, "lime")
        self.assertEqual(pipeline.PUSH_THEMES,
                         ("lime", "pixel", "forum", "dossier", "guizang"))
        with patch.dict(os.environ, {"OCTOPUS_PUSH_THEME": ""}):
            self.assertEqual(pipeline._resolve_push_theme(None), "lime")
            self.assertEqual(pipeline._resolve_push_theme(""), "lime")
            self.assertEqual(pipeline._resolve_push_theme("nonsense"), "lime")
            self.assertEqual(pipeline._resolve_push_theme("LIME"), "lime")
            self.assertEqual(pipeline._resolve_push_theme("PIXEL"), "pixel")
            self.assertEqual(pipeline._resolve_push_theme("  guizang "), "guizang")
            self.assertEqual(pipeline._resolve_push_theme("DOSSIER"), "dossier")
            self.assertEqual(pipeline._resolve_push_theme(" Forum "), "forum")
            default_html = pipeline.generate_report(
                NewLayoutRenderingTests()._rich_data(), "2026年8月2日 · 周日", "20260802")
        self.assertIn('name="octopus-theme" content="lime"', default_html)
        self.assertIn("OCTOPUS AI · FIELD GUIDE", default_html)

    def test_type_scale_is_one_page_friendly(self):
        """字号阶梯为「一页推」整体收一档：刊头 26 / 栏目 18 / 正文 14 / 次要 12"""
        self.assertEqual(pipeline.GZ_FS_DISPLAY, 26)
        self.assertEqual(pipeline.GZ_FS_SECTION, 18)
        self.assertEqual(pipeline.GZ_FS_BODY, 14)
        self.assertEqual(pipeline.GZ_FS_META, 12)
        self.assertEqual(pipeline.DEFAULT_FONT_SCALE, 1.0)
        self.assertEqual(pipeline._gz_fs(26), 26)
        self.assertEqual(pipeline._resolve_font_scale(), 1.0)
        html = self._html()
        self.assertIn("font-size:26px", html)
        self.assertIn("font-size:18px", html)

    def test_klein_blue_plus_gray_palette(self):
        """克莱因蓝 #002FA7 + 灰阶：页面上唯一的有色只能是克莱因蓝系，灰色字体强制全局深灰 #333"""
        self.assertEqual(pipeline.GZ_KLEIN, "#002FA7")
        self.assertEqual(pipeline.GZ_PRIMARY, pipeline.GZ_KLEIN)
        self.assertEqual(pipeline.GZ_UP, pipeline.GZ_KLEIN)      # 涨 = 克莱因蓝
        self.assertEqual(pipeline.GZ_INK, "#222")                # 正文灰黑
        self.assertEqual(pipeline.GZ_META, "#333")               # 次要灰（强制全局深灰）
        self.assertEqual(pipeline.GZ_FAINT, "#333")              # 辅助灰（强制全局深灰）
        self.assertEqual(pipeline.GZ_DOWN, "#333")               # 下跌辅助灰（深灰）
        self.assertEqual(pipeline.GZ_FLAT, "#333")               # 平盘辅助灰（深灰）
        html = self._html()
        self.assertIn(pipeline.GZ_KLEIN, html)
        allowed = {"#002FA7", "#00227A", "#F3F6FF"}
        for color in re.findall(r"#[0-9A-Fa-f]{6}", html):
            r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            if r == g == b:
                continue                                          # 灰阶白黑都允许
            self.assertIn(color.upper(), allowed,
                          f"除克莱因蓝系外不应出现有色 {color}")
        for color in re.findall(r"#[0-9A-Fa-f]{3}\b", html):
            r, g, b = (int(c * 2, 16) for c in color[1:])
            self.assertTrue(r == g == b, f"三位色值必须是灰阶：{color}")
            self.assertIn(color.lower(), {"#111", "#222", "#333", "#ddd", "#eee", "#fff"},
                          f"三位色值只允许深灰文字或细分隔线：{color}")
        for old_color in ("#2563EB", "#1D4ED8", "#EFF6FF", "#3b82f6",
                          "#FF5576", "#35F29A", "#FFD166", "#FF3CAC", "#22DFFF"):
            self.assertNotIn(old_color, html)

    def test_global_dark_gray_font_enforced(self):
        """强制全局：所有灰色字体（含表头、摘要、时间、来源、精简推送与落盘日报）统一为深灰 #333"""
        html = self._html()
        font_colors = set(re.findall(r"(?<![-\w])color\s*:\s*(#[0-9A-Fa-f]{3,6})\b", html))
        for c in font_colors:
            self.assertFalse(
                pipeline._is_light_or_mid_gray_hex(c),
                f"页面字体颜色不应出现中/浅灰 {c}（应强制为深灰 #333）",
            )
        for light_gray in ("color:#444", "color:#555", "color:#666", "color:#777",
                           "color:#888", "color:#999", "color:#aaa", "color:#bbb", "color:#ddd"):
            self.assertNotIn(light_gray, html.lower())

        sample_raw = (
            '<div style="color:#777;border-top:1px solid #ddd">'
            '<small style="color:#aaa">副标题</small>'
            '<span style="color:#555">标签</span>'
            '<span style="color:#6B6B6B">旧灰</span>'
            '<a style="color:#002FA7">链接</a></div>'
            '<div style="padding:5px 0;border-top:1px solid #eee">无色块文本</div>'
            '<table style="border-collapse:separate"><tr><td>无色表单元格</td></tr></table>'
        )
        enforced = pipeline._enforce_dark_gray_font(sample_raw)
        self.assertEqual(enforced.count("color:#333"), 4)
        self.assertEqual(enforced.count("color:#222"), 2)
        self.assertIn("border-top:1px solid #ddd", enforced)
        self.assertIn("color:#002FA7", enforced)

        output_dir = Path(__file__).parents[1] / "output"
        for name in ("latest.html", "日报排版示例.html", "daily_report_20260929.html"):
            p = output_dir / name
            if p.is_file():
                # --push-only 与常规推送都会先应用灰字强制；审计实际送达内容，而非历史原文件。
                disk_html = pipeline._enforce_dark_gray_font(p.read_text(encoding="utf-8"))
                disk_colors = set(re.findall(r"(?<![-\w])color\s*:\s*(#[0-9A-Fa-f]{3,6})\b", disk_html))
                for c in disk_colors:
                    self.assertFalse(
                        pipeline._is_light_or_mid_gray_hex(c),
                        f"{name} 仍含未加深的灰色字体 {c}",
                    )

    def test_every_text_node_has_explicit_color_without_body_tag(self):
        """PushPlus v-html 会剥离 <body> 标签：剥离 <body> 后，每个文本节点都必须在自身或 <body> 内祖先节点上拥有显式内联 color。"""
        from html.parser import HTMLParser

        class _BodylessColorAudit(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack = []
                self.unstyled = []
                self.total = 0

            def handle_starttag(self, tag, attrs):
                style = dict(attrs).get("style") or ""
                m = re.search(r"(?<![-\w])color\s*:\s*([^;\"'\s]+)", style, re.I)
                self.stack.append((tag.lower(), m.group(1) if m else None))

            def handle_endtag(self, tag):
                t = tag.lower()
                for i in range(len(self.stack) - 1, -1, -1):
                    if self.stack[i][0] == t:
                        self.stack.pop(i)
                        break

            def handle_data(self, data):
                txt = data.strip()
                if not txt:
                    return
                if self.stack and self.stack[-1][0] in ("title", "style", "script"):
                    return
                self.total += 1
                color_in_fragment = None
                for t, col in reversed(self.stack):
                    if t == "body":
                        break
                    if col:
                        color_in_fragment = col
                        break
                if color_in_fragment is None:
                    path = "/".join(t for t, _ in self.stack)
                    self.unstyled.append((txt[:30], path))

        html = self._html()
        audit = _BodylessColorAudit()
        audit.feed(html)
        self.assertGreater(audit.total, 50)
        self.assertEqual(
            audit.unstyled, [],
            f"剥离 <body> 后仍有未声明 color 的文本节点：{audit.unstyled[:5]}",
        )

        compact = pipeline._compact_html_for_push(html)
        self.assertIsNotNone(compact)
        compact_audit = _BodylessColorAudit()
        compact_audit.feed(compact)
        # 精简推送版节点数：2026-10-02 起全球头条 / 港股名家频道两栏隐藏后为 17 个
        self.assertGreater(compact_audit.total, 15)
        self.assertEqual(
            compact_audit.unstyled, [],
            f"精简推送版剥离 <body> 后仍有未声明 color 的文本节点：{compact_audit.unstyled[:5]}",
        )

        output_dir = Path(__file__).parents[1] / "output"
        for name in ("latest.html", "日报排版示例.html", "daily_report_20260929.html"):
            p = output_dir / name
            if p.is_file():
                disk_audit = _BodylessColorAudit()
                disk_audit.feed(p.read_text(encoding="utf-8"))
                self.assertEqual(
                    disk_audit.unstyled, [],
                    f"{name} 剥离 <body> 后仍有未声明 color 的文本节点：{disk_audit.unstyled[:5]}",
                )

    def test_kv_and_channel_rows_use_simple_tables(self):
        """正文项目和资讯以简单双列表展示。"""
        kv_html = pipeline.gz_kv_table([("市场倾向", "中性 ■"), ("核心判断", "指数温和偏多")])
        self.assertIn("<table", kv_html)
        self.assertIn("市场倾向</td>", kv_html)
        self.assertIn("中性 ■</td>", kv_html)
        self.assertIn("核心判断</td>", kv_html)
        self.assertIn("指数温和偏多</td>", kv_html)
        self.assertNotIn("市场倾向 · <b", kv_html)

        ch_html = pipeline.gz_channel_block({
            "name": "郭思治（郭Sir）",
            "desc": "港股评论",
            "url": "https://example.com/kwok",
            "is_today": True,
            "videos": [{
                "title": "港股收市汇报",
                "url": "https://example.com/v1",
                "published_cst": "2026-09-29 18:00",
                "is_today": True,
            }],
        }, ch_idx=1)
        self.assertIn('id="h-hk-01-01"', ch_html)
        self.assertIn('<br><small style="color:#333">2026-09-29 18:00</small>', ch_html)
        self.assertIn("<table", ch_html)

    def test_no_washy_text_colors(self):
        """文字可读性硬门禁：任何文字色与白底对比度 ≥ 4.5:1（WCAG AA），禁止浅灰文字回潮。

        背景：用户两次反馈文字看不清（「灰色改深灰色」「浅灰色看不清」）——表头、脚注、
        时间戳、刊头 meta 曾用 #777 / #AAA，白底对比度仅 4.48:1 / 2.32:1，手机上 11~12px
        浅灰小字根本看不清。此门禁保证任何排版改动都回不到「浅灰文字」。
        例外只有三种纯装饰用法：#fff（深底白字备用）、#ddd / #eee（信号格未点亮的
        ○ 与细分隔线同色，可读性由实心格数量承担，不承载文字信息）。
        """
        html = self._html()

        def _lum(hex_color):
            c = hex_color.lstrip("#")
            if len(c) == 3:
                c = "".join(ch * 2 for ch in c)
            r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))

            def _f(v):
                return ((v + 0.055) / 1.055) ** 2.4 if v > 0.03928 else v / 12.92

            return 0.2126 * _f(r) + 0.7152 * _f(g) + 0.0722 * _f(b)

        decorative = {"#fff", "#ddd", "#eee"}
        seen = set()
        for color in re.findall(r"color:\s*(#[0-9A-Fa-f]{3,6})", html):
            if color.lower() in decorative or color.lower() in seen:
                continue
            seen.add(color.lower())
            contrast = 1.05 / (_lum(color) + 0.05)      # 与纯白底 #FFFFFF 的对比度
            self.assertGreaterEqual(
                contrast, 4.5,
                f"文字色 {color} 与白底对比度仅 {contrast:.2f}:1（需 ≥ 4.5:1），浅灰看不清")

    def test_true_white_background_and_gray_hairlines(self):
        """真白底 #ffffff + 1px 浅灰分割线，不靠背景色块分区"""
        html = self._html()
        self.assertIn('bgcolor="#FFFFFF"', html)
        self.assertIn("background:#FFFFFF", html)
        self.assertNotIn("#f8fafc", html.lower())
        self.assertNotIn("#fafaf9", html.lower())
        self.assertEqual(pipeline.GZ_HAIR, "#ddd")
        self.assertEqual(pipeline.GZ_HAIR_W, 1)
        self.assertIn("1px solid #ddd", html)

    def test_inline_only_and_no_remote_assets(self):
        """微信 / PushPlus 兼容：全内联样式，无 <style> / class / 图标外链 / 图片"""
        html = self._html()
        self.assertNotIn("<style", html)
        self.assertNotIn("class=", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("<svg", html)
        self.assertNotIn("koboyo.com/icons/svg", html)
        self.assertNotIn("<script", html)
        self.assertIn("<table", html)      # 多列数据仍用表格对齐

    def test_data_tables_stack_into_single_column(self):
        """多行多列排版：三列及以上按标准多行多列表格渲染（表头行 + 多列数据行）。"""
        html = pipeline.gz_data_table(["名称", "最新价", "涨跌"],
                                      [["恒生指数", "26,881.4", "▼ -0.43%"]])
        self.assertEqual(html.count("<tr>"), 2)            # 1 行表头 + 1 行数据 = 2 行
        self.assertEqual(html.count("<td"), 6)             # 2 行 × 3 列 = 6 个单元格
        self.assertIn("名称</td>", html)
        self.assertIn("最新价</td>", html)
        self.assertIn("涨跌</td>", html)
        self.assertIn("恒生指数</td>", html)
        self.assertIn("26,881.4</td>", html)
        self.assertIn("▼ -0.43%</td>", html)
        self.assertNotIn("<td style=\"padding:5px 8px", html)   # 旧写法：每格 20+ 字

    def test_two_column_kv_stays_one_line_per_pair(self):
        """两列键值仍是「标签 值」多行双列：含表头与键值行。"""
        html = pipeline.gz_data_table(["项目", "口径"], [["市场倾向", "中性"]], kv=True)
        self.assertIn("市场倾向</td>", html)
        self.assertIn("中性</td>", html)

    def test_section_header_is_number_kicker_and_title(self):
        """栏目头：编号 + 克莱因蓝 kicker → <h2> 标题（无图标）"""
        html = pipeline.gz_section("07", "WEEKLY FORECAST",
                                   pipeline.SECTION_TITLE_WEEKLY_FORECAST, "正文在这里")
        self.assertIn("07 · WEEKLY FORECAST", html)
        self.assertIn(f"{pipeline.SECTION_TITLE_WEEKLY_FORECAST}</h2>", html)
        self.assertIn("正文在这里", html)
        self.assertIn(pipeline.GZ_KLEIN, html)
        self.assertNotIn("<svg", html)

    def test_market_snapshot_table_keeps_labels_and_numbers(self):
        data = ReportFreshnessTests()._sample_data()
        html = pipeline.generate_report(data, "2026年8月1日 · 周六", "20260801",
                                        theme="guizang")
        self.assertIn("6,123", html)
        # 多行多列表格保留完整表头「名称」「最新价」「涨跌」
        self.assertIn("最新价</td>", html)

    def test_minimal_news_card_leads_with_title_and_keeps_source(self):
        html = pipeline.gz_headline_row({
            "title": "港股市场观察", "source": "测试来源", "published_cst": "2026-09-08 10:00"
        }, 1)
        self.assertLess(html.index("港股市场观察"), html.index("测试来源"))
        self.assertIn("2026-09-08 10:00", html)
        self.assertIn("<table", html)   # 资讯行以简单双列表展示

    def test_full_report_fits_single_push_message(self):
        """一页推：常规栏目的完整日报必须在单条上限内，且拆分为恰好 1 条"""
        data = SectionReadingOrderTests()._full_data()
        data["A股大盘全景"] = MarketPanoramaTests()._panorama_payload()
        import test_weekly as tw
        data["每周走势预测"] = tw.WeeklyPipelineIntegrationTests()._source()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802",
                                        theme="guizang")
        self.assertLess(len(html), pipeline.PUSHPLUS_MAX_CONTENT_CHARS)
        parts = pipeline._split_html_for_push(html, pipeline.PUSHPLUS_MAX_CONTENT_CHARS)
        self.assertEqual(len(parts or []), 1)

    def test_multipart_split_keeps_every_section_and_visible_text(self):
        """超限时按栏目边界全量分条：每段不超限、栏目不重不漏、可见文本节点不丢"""
        data = SectionReadingOrderTests()._full_data()
        data["A股大盘全景"] = MarketPanoramaTests()._panorama_payload()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802",
                                        theme="guizang")
        limit = 6000
        # 测试用 6,000 字小上限会人为放大分条数；提高仅测试用的条数上限，
        # 验证完整分页时每个栏目与可见文本节点都保留（生产默认仍为 12 条）。
        parts = pipeline._split_html_for_push(html, limit, max_parts=30)
        self.assertIsNotNone(parts)
        self.assertGreater(len(parts), 1)
        for index, part in enumerate(parts, 1):
            self.assertLessEqual(len(part), limit, f"第 {index} 条超过单条上限")
        for title in re.findall(r"<h2[^>]*>([^<]+)</h2>", html):
            hits = sum(1 for part in parts if f">{title}</h2>" in part)
            self.assertGreaterEqual(hits, 1, f"栏目「{title}」在 {len(parts)} 条里一次都没出现")
            # 「尽量合并」允许在同一栏内部续接：续片会重开栏目头，但必须在横幅里如实
            # 标注「承接上条「栏目名」（续）」，所以标题出现次数 = 1 + 标了续接的条数
            cont = sum(1 for part in parts if f"承接上条「{title}」（续）" in part)
            self.assertEqual(
                hits, 1 + cont,
                f"栏目「{title}」在 {len(parts)} 条里出现 {hits} 次，其中 {cont} 条标了「承接上条（续）」")
        class VisibleText(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.nodes = []

            def handle_data(self, data):
                text = re.sub(r"\s+", "", data)
                if text:
                    self.nodes.append(text)

        def visible_nodes(fragment):
            parser = VisibleText()
            parser.feed(fragment)
            return parser.nodes

        delivered = "".join(visible_nodes("".join(parts)))
        source_nodes = visible_nodes(html)
        missing = [node for node in source_nodes if node not in delivered]
        self.assertEqual(missing[:3], [], f"{len(missing)} 个可见文本节点在分条后丢失")


class GuizangOnePageTests(unittest.TestCase):
    """重日压力测试：把最能堆字数的栏目按重日体量灌满，仍要一页装得下。

    口径：全量内容（含量化三段真实引擎产物、60 条日程、五路资讯、多平台趋势线索）
    渲染后 ≤ PUSHPLUS_MAX_CONTENT_CHARS，「按栏目分条」只需 1 条 → 微信端一页推。
    真正超限的极重日仍按栏目边界全量分条（见 test_multipart_split_keeps_every_section_and_visible_text），不截断、不摘要。
    """

    def _heavy_data(self):
        from test_quant import run_engine            # 真实量化引擎（合成行情，离线）
        data = NewsSentimentFactorTests()._senti_data()
        data["实时行情"] = pipeline._source_result(
            "Yahoo Finance Chart", "success", is_today=True, content_date="2026-09-29",
            quotes={
                "道琼斯指数": {"price": 46312.0, "change_pct": -0.67, "as_of": "2026-09-28"},
                "标普500": {"price": 6691.2, "change_pct": -0.77, "as_of": "2026-09-29"},
                "纳斯达克": {"price": 22871.4, "change_pct": -0.92, "as_of": "2026-09-29"},
                "WTI 原油": {"price": 65.31, "change_pct": 1.20, "as_of": "2026-09-29"},
                "微软 MSFT": {"price": 512.3, "change_pct": -0.4, "as_of": "2026-09-29"},
                "Meta META": {"price": 731.5, "change_pct": 0.8, "as_of": "2026-09-29"},
                "上证指数": {"price": 3838.31, "change_pct": 0.38, "as_of": "2026-09-29"},
                "深证成指": {"price": 12877.4, "change_pct": 0.72, "as_of": "2026-09-29"},
                "创业板指": {"price": 3012.9, "change_pct": 1.18, "as_of": "2026-09-29"},
                "科创50": {"price": 1188.6, "change_pct": -0.22, "as_of": "2026-09-29"},
                "恒生指数": {"price": 26881.4, "change_pct": -0.43, "as_of": "2026-09-29"},
                "恒生科技": {"price": 6012.7, "change_pct": -0.91, "as_of": "2026-09-29"},
            })
        data["A股大盘全景"] = MarketPanoramaTests()._panorama_payload()
        with tempfile.TemporaryDirectory() as tmp:
            data["港股量化"] = pipeline._source_result(
                "港股量化引擎", "success", is_today=True, content_date="2026-09-29",
                result=run_engine(tmpdir=tmp, n_stocks=12))
        data[pipeline.FED_TREND_KEY] = AiTrendAnalysisTests()._fed_data()[pipeline.FED_TREND_KEY]
        data[pipeline.GEO_TREND_KEY] = \
            AiTrendAnalysisTests()._both_topics_data()[pipeline.GEO_TREND_KEY]

        # 五路资讯 + 舆情归因：把标题量拉到重日水平
        data["东财快讯"]["headlines"] = [
            {"title": f"东方财富快讯样例{i}：市场盘中异动与资金流向观察", "url": "",
             "time": "2026-09-29 1%d:30" % (i % 10), "summary": "盘面综述与板块资金流向",
             "is_today": True} for i in range(1, 13)]
        data["全球头条"]["headlines"] = [
            {"title": f"全球头条样例{i}：海外市场与政策动态观察", "source": "华尔街见闻",
             "url": "", "published_cst": "2026-09-29 0%d:00" % (i % 10), "is_today": True}
            for i in range(1, 9)]
        # 政策因子需要方向性政策标题（降准/加息/地产等）才会出现
        data["全球头条"]["headlines"].append({
            "title": "央行宣布降准0.5个百分点释放长期资金", "source": "新华社", "url": "",
            "published_cst": "2026-09-29 09:00", "is_today": True})
        data["港股名家频道"]["channels"] = [
            {"name": f"频道{c}", "desc": "港股评论", "url": f"https://example.com/{c}",
             "is_today": True,
             "videos": [{"title": f"频道{c}视频{v}：港股大盘技术面与板块轮动解读",
                         "url": f"https://www.youtube.com/watch?v=c{c}v{v}",
                         "published_cst": f"2026-09-2{9 - v} 1{v}:00", "is_today": v == 1}
                        for v in range(1, 3)]}
            for c in range(1, 6)]
        for mkt in ("A股", "港股", "美股"):
            for i in range(1, 11):
                nm = f"{mkt}股票{(i - 1) % 10}"
                data["全球头条"]["headlines"].append({
                    "title": f"{nm}获机构上调目标价，主力资金净流入明显", "source": "财联社",
                    "url": "", "published_cst": "2026-09-29 1%d:00" % (i % 10), "is_today": True})
        data.update(self._trend_data())

        # 财经日历：未来 30 天灌满（重日约 40~60 行）
        base = dt.date(2026, 9, 30)
        rows = []
        for i in range(120):
            day = base + dt.timedelta(days=i // 3)
            if day > dt.date(2026, 10, 29):
                break
            rows.append({"START_DATE": f"{day.isoformat()} {8 + i % 12:02d}:30:00",
                         "FE_NAME": "中国:CPI:同比(报告期:2026年10月)", "FE_TYPE": "经济数据",
                         "STD_TYPE_CODE": "3" if i % 2 == 0 else "2",
                         "CITY": "中国" if i % 2 else "美国"})
        with patch.object(pipeline, "safe_request",
                          lambda *a, **k: {"success": True,
                                           "result": {"count": len(rows), "data": rows}}):
            data["财经日历"] = pipeline.fetch_econ_calendar(today=dt.date(2026, 9, 29), days=30)
        return data

    def _trend_data(self):
        """趋势跟踪重日体量：10 个 Reddit 板块 + 3 个平台 + 36 个新闻源头。"""
        data = {}
        boards = pipeline._REDDIT_BOARDS
        reddit = [{"title": f"r/{board} 热门帖样本{i}：港股与美股资金面观察，讨论热度持续",
                   "url": f"https://www.reddit.com/r/{board}/comments/x{i}/t{i}/",
                   "detail": f"发布于 2026-09-2{8 - i % 2} 1{i % 10}:00（北京时间） · {100 - i} 赞 · {30 + i} 评论",
                   "published_cst": f"2026-09-2{8 - i % 2} 1{i % 10}:00",
                   "community": f"r/{board}", "is_today": True}
                  for board, _ in boards for i in range(1, 6)]
        data["Reddit"] = pipeline._public_site_result("Reddit", reddit, latest="2026-09-29")
        for name, n in (("StockTwits", 8), ("TradingView", 10), ("Bogleheads", 10)):
            items = [{"title": f"{name} 公开样本{i}：港股估值与长期配置的讨论",
                      "url": f"https://{name.lower()}.example/x{i}",
                      "detail": f"发布于 2026-09-29 0{i % 9}:10（北京时间） · 关注 {50 + i}",
                      "community": f"{name} 榜单{i % 3}", "is_today": True}
                     for i in range(1, n + 1)]
            data[name] = pipeline._public_site_result(name, items, latest="2026-09-29")
        per_source = [{"title": f"源头{i % 20 + 1}·第{i}条：港股主题资金流向与估值讨论",
                       "url": f"https://news{i % 20}.example/a{i}",
                       "detail": "发布于 2026-09-29 09:0%d（北京时间）" % (i % 10),
                       "published_cst": "2026-09-29 09:0%d" % (i % 10), "is_today": True}
                      for i in range(1, 4)]
        data[pipeline.HK_NEWS_SOURCE_NAME] = pipeline._source_result(
            pipeline.HK_NEWS_SOURCE_NAME, "success", is_today=True,
            content_date="2026-09-29",
            analysis={"total": 20, "ok_n": 20, "scanned": 400, "hk_n": 60},
            sources=[{"name": f"新闻源头{i}", "region": "香港" if i % 2 else "国际",
                      "url": f"https://source{i}.example/", "hosts": (f"source{i}.example",),
                      "hk_n": 3, "items": per_source} for i in range(1, 21)])
        return data

    def test_heavy_day_report_keeps_original_theme_when_split(self):
        html = pipeline.generate_report(self._heavy_data(), "2026年9月29日 · 周二", "20260929",
                                        theme="guizang")
        # 真实重日会超过平台上限；不允许为了少发一条而改成无主题的文字版。
        with (
            patch.object(pipeline, "_push_html_parts", return_value=True) as multipart,
            patch.object(pipeline, "_push_one_message", return_value=True) as single,
            patch.object(pipeline, "_compact_html_for_push", side_effect=AssertionError("丢失风格")),
        ):
            self.assertTrue(pipeline.push_to_wechat("重日报测试", html, token="test-token"))
        self.assertFalse(single.called)
        delivered = multipart.call_args.args[1]
        self.assertGreaterEqual(len(delivered), 2)
        for part in delivered:
            self.assertLessEqual(len(part), pipeline.PUSHPLUS_MAX_CONTENT_CHARS)
            self.assertIn('name="octopus-theme" content="guizang"', part)
            self.assertNotIn("推送精简排版", part)
            self.assertIn(pipeline.GZ_KLEIN, part)

    def test_heavy_day_report_keeps_every_section(self):
        """全量：重日栏目一个都不能少，只靠排版瘦身换一页"""
        data = self._heavy_data()
        html = pipeline.generate_report(data, "2026年9月29日 · 周二", "20260929",
                                       theme="guizang")
        titles = [s[1] for s in pipeline._collect_report_parts(
            data, pipeline.GUIZANG_KIT, date_str="20260929")["sections"]]
        # 2026-09-29 起七个栏目更名；AI 全篇速览已移除，社会情绪因子由真实样本驱动。
        # 未来30天影响经济时间点 / 量化分析总览 / 全球头条 / 趋势跟踪 / 政策因子 /
        # 每周量化走势预测 分别加上鱼名前缀；
        # 2026-09-30 起「行情速览」+「全球大盘全景复盘」合并为「【及时秋刀鱼】AI 行情复盘」；
        # 2026-10-02 起「东方财富快讯」「【无敌帝王蟹】全球头条」「港股名家频道」
        # 三个资讯栏目在页面隐藏（保留后台抓取供 AI 分析与审计）。
        for title in (pipeline.SECTION_TITLE_RETAIL_SENTIMENT, "【回游金枪鱼】今日预判",
                      "【探照安康鱼】时间节点量化分析",
                      "每日趋势量化推演", "资金流动性分析", "【及时秋刀鱼】AI 行情复盘",
                      "【深海肥蓝鲸】政策因子", pipeline.SECTION_TITLE_STRATEGY,
                      "【深海大鲨鱼】趋势跟踪",
                      pipeline.SECTION_TITLE_NEWS_SENTIMENT, "总结"):
            self.assertIn(title, titles)
            self.assertIn(f"{title}</h2>", html)
        self.assertIn("港股概率走势分析", html)  # 作为栏目内子块显示，不再单列 h2
        self.assertNotIn("港股概率走势分析</h2>", html)
        # 2026-10-23「量化分析总览」整栏下线
        self.assertNotIn("量化分析总览", titles)
        self.assertNotIn("量化分析总览</h2>", html)
        for hidden in ("东方财富快讯", "【无敌帝王蟹】全球头条", "港股名家频道"):
            self.assertNotIn(hidden, titles)
            self.assertNotIn(f"{hidden}</h2>", html)


class CleanOldReportsTests(unittest.TestCase):
    """2026-08-02 新增：手动/自动推送前必须清理历史 HTML 报告。

    避免历史残留文件（含旧版本特征）被 latest.html 引用或被 --push-only 误推。
    清理函数 clean_old_html_reports 是 main() 正常流程的第一步（--dry-run 跳过）。
    """

    def _seed_reports(self, directory):
        """在测试目录里放几份旧报告 + latest.html，返回它们的路径。"""
        files = [
            "daily_report_20260801.html",
            "daily_report_20260802_20260802_069.html",
            "daily_report_20260802_20260802_098.html",
            "daily_report_20260802_20260802_243.html",
            "latest.html",
        ]
        created = []
        for name in files:
            p = Path(directory) / name
            p.write_text(f"OLD-CONTENT-{name}", encoding="utf-8")
            created.append(p)
        return created

    def test_clean_old_html_reports_removes_daily_reports_and_latest(self):
        """默认行为：删除全部 daily_report_*.html 和 latest.html。"""
        with tempfile.TemporaryDirectory() as directory:
            self._seed_reports(directory)
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                deleted, latest_deleted = pipeline.clean_old_html_reports()
            finally:
                pipeline.REPORT_DIR = old_report_dir
            self.assertEqual(deleted, 4)
            self.assertTrue(latest_deleted)
            # 目录里现在应只剩 pipeline 自身的非 HTML 文件
            remaining = list(Path(directory).glob("*.html"))
            self.assertEqual(remaining, [], f"应无 HTML 残留，实际: {remaining}")

    def test_clean_old_html_reports_keep_latest_keeps_latest(self):
        """keep_latest=True 时保留 latest.html，仅清 daily_report_*.html。"""
        with tempfile.TemporaryDirectory() as directory:
            self._seed_reports(directory)
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                deleted, latest_deleted = pipeline.clean_old_html_reports(keep_latest=True)
            finally:
                pipeline.REPORT_DIR = old_report_dir
            self.assertEqual(deleted, 4)
            self.assertFalse(latest_deleted)
            # latest.html 仍存在
            self.assertTrue((Path(directory) / "latest.html").is_file())
            self.assertTrue((Path(directory) / "latest.html").read_text(
                encoding="utf-8").startswith("OLD-CONTENT-latest.html"))

    def test_clean_old_html_reports_on_empty_directory(self):
        """空目录：不报错，返回 (0, False)。"""
        with tempfile.TemporaryDirectory() as directory:
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                deleted, latest_deleted = pipeline.clean_old_html_reports()
            finally:
                pipeline.REPORT_DIR = old_report_dir
            self.assertEqual(deleted, 0)
            self.assertFalse(latest_deleted)

    def test_clean_old_html_reports_ignores_non_html_files(self):
        """清理只匹配 .html，不动其他扩展名文件。"""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "daily_report_20260801.html").write_text("old", encoding="utf-8")
            (Path(directory) / "notes.txt").write_text("keep me", encoding="utf-8")
            (Path(directory) / "data.json").write_text("{}", encoding="utf-8")
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                pipeline.clean_old_html_reports()
            finally:
                pipeline.REPORT_DIR = old_report_dir
            # HTML 被清，txt/json 保留
            self.assertFalse((Path(directory) / "daily_report_20260801.html").exists())
            self.assertTrue((Path(directory) / "notes.txt").exists())
            self.assertTrue((Path(directory) / "data.json").exists())

    def test_main_normal_flow_cleans_only_after_report_saved(self):
        """main() 正常流程：清理必须在新报告保存之后执行，且保留本次日报。

        回归 2026-10-14 事故：旧的「采集前清理」让崩溃后工作区没有任何日报，
        workflow 的 git add 把整批历史日报当作删除提交。
        """
        with tempfile.TemporaryDirectory() as directory:
            self._seed_reports(directory)
            old_report_dir = pipeline.REPORT_DIR
            call_order = []
            clean_kwargs = []

            original_collect = pipeline.collect_all_data
            original_clean = pipeline.clean_old_html_reports

            def tracking_clean(*a, **kw):
                call_order.append("clean")
                clean_kwargs.append(kw)
                return original_clean(*a, **kw)

            def tracking_collect():
                call_order.append("collect")
                return original_collect()

            def fake_save(html, output_path=None, data=None):
                call_order.append("save")
                p = Path(directory) / "daily_report_test.html"
                p.write_text(html, encoding="utf-8")
                return str(p)

            try:
                pipeline.REPORT_DIR = directory
                with patch.object(sys, "argv", ["pipeline.py"]), \
                     patch.object(pipeline, "collect_all_data",
                                  side_effect=tracking_collect), \
                     patch.object(pipeline, "clean_old_html_reports",
                                  side_effect=tracking_clean), \
                     patch.object(pipeline, "generate_report",
                                  return_value="<html>ok</html>"), \
                     patch.object(pipeline, "save_report", side_effect=fake_save), \
                     patch.object(pipeline, "push_to_wechat", return_value=True):
                    pipeline.main()
                new_report_exists = (Path(directory) / "daily_report_test.html").exists()
                old_report_exists = (Path(directory) / "daily_report_20260801.html").exists()
            finally:
                pipeline.REPORT_DIR = old_report_dir

            self.assertEqual(call_order, ["collect", "save", "clean"],
                             "清理必须在采集和保存新报告之后执行")
            self.assertTrue(new_report_exists, "本次日报必须保留")
            self.assertFalse(old_report_exists, "旧日报应在新报告保存后被清理")
            self.assertEqual(clean_kwargs[0].get("keep"),
                             (str(Path(directory) / "daily_report_test.html"),))

    def test_main_collect_crash_keeps_old_reports(self):
        """采集阶段崩溃：旧日报必须原封不动（不能先清空再崩溃）。"""
        with tempfile.TemporaryDirectory() as directory:
            self._seed_reports(directory)
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                with patch.object(sys, "argv", ["pipeline.py"]), \
                     patch.object(pipeline, "collect_all_data",
                                  side_effect=RuntimeError("boom")):
                    with self.assertRaises(RuntimeError):
                        pipeline.main()
            finally:
                pipeline.REPORT_DIR = old_report_dir

            self.assertTrue((Path(directory) / "daily_report_20260801.html").exists())
            self.assertTrue((Path(directory) / "latest.html").exists())
            self.assertEqual((Path(directory) / "latest.html").read_text(encoding="utf-8"),
                             "OLD-CONTENT-latest.html")

    def test_main_generate_crash_keeps_old_reports(self):
        """生成阶段崩溃（如 Counter NameError）：旧日报必须保留，工作区不得变空。"""
        with tempfile.TemporaryDirectory() as directory:
            self._seed_reports(directory)
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                with patch.object(sys, "argv", ["pipeline.py"]), \
                     patch.object(pipeline, "collect_all_data", return_value={}), \
                     patch.object(pipeline, "generate_report",
                                  side_effect=NameError("name 'Counter' is not defined")):
                    with self.assertRaises(NameError):
                        pipeline.main()
            finally:
                pipeline.REPORT_DIR = old_report_dir

            remaining = sorted(p.name for p in Path(directory).glob("daily_report_*.html"))
            self.assertEqual(remaining, ["daily_report_20260801.html",
                                         "daily_report_20260802_20260802_069.html",
                                         "daily_report_20260802_20260802_098.html",
                                         "daily_report_20260802_20260802_243.html"])

    def test_clean_old_html_reports_keep_preserves_given_path(self):
        """keep 参数：指定路径不被删除，其余历史日报照常清理。"""
        with tempfile.TemporaryDirectory() as directory:
            self._seed_reports(directory)
            keep_path = str(Path(directory) / "daily_report_20260802_20260802_098.html")
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                deleted, latest_deleted = pipeline.clean_old_html_reports(
                    keep_latest=True, keep=(keep_path,))
            finally:
                pipeline.REPORT_DIR = old_report_dir

            self.assertEqual(deleted, 3)
            self.assertFalse(latest_deleted)
            self.assertTrue(Path(keep_path).exists())
            self.assertTrue((Path(directory) / "latest.html").exists())

    def test_main_dry_run_skips_clean(self):
        """--dry-run 模式：不清理（不写文件，清理无意义且会产生空目录警告）。"""
        with tempfile.TemporaryDirectory() as directory:
            self._seed_reports(directory)
            old_report_dir = pipeline.REPORT_DIR
            original_clean = pipeline.clean_old_html_reports
            clean_called = []

            def tracking_clean(*a, **kw):
                clean_called.append(True)
                return original_clean(*a, **kw)

            try:
                pipeline.REPORT_DIR = directory
                with patch.object(sys, "argv", ["pipeline.py", "--dry-run"]), \
                     patch.object(pipeline, "collect_all_data", return_value={}), \
                     patch.object(pipeline, "clean_old_html_reports",
                                  side_effect=tracking_clean):
                    pipeline.main()
            finally:
                pipeline.REPORT_DIR = old_report_dir

            self.assertEqual(clean_called, [],
                             "--dry-run 不应调用 clean_old_html_reports")
            # 旧文件应原封不动
            self.assertTrue((Path(directory) / "daily_report_20260801.html").exists())
            self.assertTrue((Path(directory) / "latest.html").exists())


class MarketPanoramaTests(unittest.TestCase):
    """2026-09-08 新增：A股大盘全景（指数表现 / 涨跌家数 / 成交额 / 北向资金 / 板块热力）。

    2026-09-30 起该数据与「实时行情」合并渲染进同一栏【及时秋刀鱼】AI 行情复盘：
    重复的数字只出一份（全球指数概览整块删除、A股指数表并入报价栏、沪深京分市场
    成交额与指数成交额同值不再重列），其余子块内容与口径完全不变。

    全部用 fake safe_request 按 URL 分发，不发真实网络请求。
    """

    QUOTE_TS = int(pipeline.datetime(2026, 9, 8, 15, 0, tzinfo=pipeline.CST).timestamp())

    @staticmethod
    def _indices_diff():
        # f12 代码与 PANORAMA_INDEX_SPECS 一一对应；三大载体指数附带市场宽度统计
        return [
            {"f12": "000001", "f14": "上证指数", "f2": 3123.45, "f3": 1.25, "f4": 38.50,
             "f6": 5.1e11, "f17": 3090.0, "f15": 3130.0, "f16": 3081.0, "f18": 3084.95,
             "f104": 1800, "f105": 500, "f106": 60, "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "399001", "f14": "深证成指", "f2": 10456.78, "f3": -0.62, "f4": -65.30,
             "f6": 6.2e11, "f17": 10500.0, "f15": 10580.0, "f16": 10400.0, "f18": 10522.08,
             "f104": 2100, "f105": 700, "f106": 80, "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "399006", "f14": "创业板指", "f2": 2101.23, "f3": 2.10, "f4": 43.19,
             "f6": 3.0e11, "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "000688", "f14": "科创50", "f2": 901.10, "f3": 0.0, "f4": 0.0,
             "f6": 8.0e10, "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "899050", "f14": "北证50", "f2": 801.50, "f3": 0.85, "f4": 6.76,
             "f6": 8.0e9, "f104": 150, "f105": 100, "f106": 10,
             "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "000300", "f14": "沪深300", "f2": 3980.20, "f3": 0.90, "f4": 35.54,
             "f6": 2.9e11, "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "000016", "f14": "上证50", "f2": 2601.30, "f3": 0.55, "f4": 14.22,
             "f6": 1.1e11, "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "000905", "f14": "中证500", "f2": 5902.40, "f3": 1.10, "f4": 64.20,
             "f6": 2.2e11, "f124": MarketPanoramaTests.QUOTE_TS},
        ]

    @staticmethod
    def _sector_rows(po):
        sign = 1 if po == "1" else -1
        return [
            {"f12": f"BK10{i}", "f14": f"板块{i}", "f3": sign * (3.5 - i * 0.3),
             "f62": 1.5e9 - i * 1e8, "f104": 30 - i, "f105": 5 + i,
             "f128": f"领涨股{i}", "f136": 9.9 - i}
            for i in range(pipeline.PANORAMA_SECTOR_TOP_N)
        ]

    def _install_fake_requests(self, with_kline=True, with_hsgt=True, with_sectors=True):
        def fake(url, params=None, **kw):
            if "ulist.np" in url:
                return {"data": {"diff": self._indices_diff()}}
            if "stock/kline" in url:
                if not with_kline:
                    return None
                base = {"1.000001": 4.8e11, "0.399001": 6.0e11, "0.899050": 7.0e9}[
                    (params or {}).get("secid")]
                return {"data": {"klines": [f"2026-09-07,{base}", f"2026-09-08,{base * 1.05:.0f}"]}}
            if "datacenter-web.eastmoney.com" in url:
                if not with_hsgt:
                    return None
                return {"result": {"data": [
                    {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-08 00:00:00", "DEAL_AMT": 135025.0},
                    {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-08 00:00:00", "DEAL_AMT": 8850.0},
                ]}}
            if "clist/get" in url:
                if not with_sectors:
                    return None
                return {"data": {"diff": self._sector_rows((params or {}).get("po"))}}
            return None
        return patch.object(pipeline, "safe_request", side_effect=fake)

    # ------------------------------------------------------------------
    # 采集层
    # ------------------------------------------------------------------
    def test_fetch_market_panorama_parses_all_blocks(self):
        with self._install_fake_requests():
            result = pipeline.fetch_market_panorama()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source"], "东方财富·A股全景")
        self.assertEqual(result["content_date"], "2026-09-08")
        self.assertEqual(result["quote_time"], "2026-09-08 15:00:00")
        self.assertEqual(result["is_today"], pipeline._today_display() == "2026-09-08")

        # ① 指数表现：按 spec 顺序保留八大宽基，名称统一为正式中文名
        self.assertEqual(len(result["indices"]), 8)
        self.assertEqual([i["name"] for i in result["indices"]],
                         [label for _, label in pipeline.PANORAMA_INDEX_SPECS])
        self.assertEqual(result["indices"][0]["price"], 3123.45)
        self.assertEqual(result["indices"][0]["chg_pct"], 1.25)

        # ② 涨跌家数：沪深京三市合计 + 涨跌比 + 情绪定调
        b = result["breadth"]
        self.assertEqual((b["up"], b["down"], b["flat"]), (4050, 1300, 150))
        self.assertEqual(b["ratio"], 3.12)
        self.assertEqual(b["mood"], "普涨强势")
        self.assertFalse(b["partial"])

        # ③ 成交额：沪深京合计 + 上一交易日环比（K 线末根日期==报价日时取前一根）
        t = result["turnover"]
        self.assertAlmostEqual(t["total"], 5.1e11 + 6.2e11 + 8.0e9)
        self.assertAlmostEqual(t["sh_sz"], 5.1e11 + 6.2e11)
        self.assertAlmostEqual(t["prev_total"], 4.8e11 + 6.0e11 + 7.0e9)
        self.assertAlmostEqual(t["chg_pct"], (t["total"] / t["prev_total"] - 1) * 100, places=6)

        # ④ 南北向资金：RPT_MUTUAL_DEAL_HISTORY 的 005/006 成交总额（百万元→亿元）
        north = result["north"]
        self.assertTrue(north["available"])
        self.assertEqual(north["amount_yi"], 1350.25)
        self.assertEqual(north["date"], "2026-09-08")
        self.assertTrue(north["south_available"])
        self.assertEqual(north["south_amount_yi"], 88.50)
        self.assertEqual(north["south_date"], "2026-09-08")
        self.assertIn("2024-08-19", north["policy_note"])

        # ⑤ 板块热力：领涨 TOP 涨幅降序、领跌 TOP 跌幅最深在前
        leading = result["sectors"]["leading"]
        lagging = result["sectors"]["lagging"]
        self.assertEqual(len(leading), pipeline.PANORAMA_SECTOR_TOP_N)
        self.assertEqual([r["chg_pct"] for r in leading],
                         sorted((r["chg_pct"] for r in leading), reverse=True))
        self.assertEqual([r["chg_pct"] for r in lagging],
                         sorted((r["chg_pct"] for r in lagging)))
        self.assertEqual(leading[0]["lead_stock"], "领涨股0")
        self.assertEqual(leading[0]["main_inflow"], 1.5e9)

    def test_fetch_market_panorama_unavailable_when_quote_request_fails(self):
        with patch.object(pipeline, "safe_request", return_value=None):
            result = pipeline.fetch_market_panorama()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["indices"], [])
        self.assertIsNone(result["breadth"])
        self.assertIsNone(result["turnover"])

    def test_fetch_market_panorama_degrades_per_subblock(self):
        # 指数 / 宽度在线，K 线、北向、板块全挂：整体仍 success，对应子块缺席并标 partial
        with self._install_fake_requests(with_kline=False, with_hsgt=False, with_sectors=False):
            result = pipeline.fetch_market_panorama()
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["indices"]), 8)
        self.assertIsNotNone(result["turnover"])
        self.assertIsNone(result["turnover"]["prev_total"])
        self.assertIsNone(result["turnover"]["chg_pct"])
        self.assertFalse(result["north"]["available"])
        self.assertFalse(result["north"]["south_available"])
        self.assertEqual(result["sectors"], {"leading": [], "lagging": []})
        self.assertTrue(result["partial"])
        self.assertIn("北向", result["error"])
        self.assertIn("南向", result["error"])
        self.assertIn("板块热力", result["error"])

    def test_breadth_mood_thresholds(self):
        self.assertEqual(pipeline._panorama_breadth_mood(2.0), "普涨强势")
        self.assertEqual(pipeline._panorama_breadth_mood(1.2), "偏多震荡")
        self.assertEqual(pipeline._panorama_breadth_mood(0.8), "多空均衡")
        self.assertEqual(pipeline._panorama_breadth_mood(0.5), "偏空承压")
        self.assertEqual(pipeline._panorama_breadth_mood(0.49), "普跌弱势")
        self.assertEqual(pipeline._panorama_breadth_mood(None), "数据不足")

    def test_northbound_previous_close_selection_when_latest_row_is_today(self):
        """最新行日期==今天时，取它前一行作为「前一收盘」（南向同规则）。"""
        payload = {"result": {"data": [
            {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-04 00:00:00", "DEAL_AMT": 10000.0},
            {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-07 00:00:00", "DEAL_AMT": 20000.0},
            {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-08 00:00:00", "DEAL_AMT": 30000.0},
            {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-04 00:00:00", "DEAL_AMT": 1000.0},
            {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-07 00:00:00", "DEAL_AMT": 2000.0},
            {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-08 00:00:00", "DEAL_AMT": 3000.0},
        ]}}
        with patch.object(pipeline, "safe_request", return_value=payload), \
             patch.object(pipeline, "_today_display", return_value="2026-09-08"):
            north = pipeline._fetch_panorama_northbound()
        self.assertTrue(north["available"])
        self.assertEqual(north["date"], "2026-09-07")
        self.assertEqual(north["amount_yi"], 200.0)   # 20000 百万元 ÷ 100
        self.assertTrue(north["south_available"])
        self.assertEqual(north["south_date"], "2026-09-07")
        self.assertEqual(north["south_amount_yi"], 20.0)

    def test_northbound_uses_last_row_when_latest_is_not_today(self):
        """最新行不是今天（盘前/非交易日/休市）时，最后一行即最近完整交易日。"""
        payload = {"result": {"data": [
            {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-04 00:00:00", "DEAL_AMT": 10000.0},
            {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-07 00:00:00", "DEAL_AMT": 20000.0},
            {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-08 00:00:00", "DEAL_AMT": 30000.0},
            {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-04 00:00:00", "DEAL_AMT": 1000.0},
            {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-07 00:00:00", "DEAL_AMT": 2000.0},
            {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-08 00:00:00", "DEAL_AMT": 3000.0},
        ]}}
        with patch.object(pipeline, "safe_request", return_value=payload), \
             patch.object(pipeline, "_today_display", return_value="2026-09-09"):
            north = pipeline._fetch_panorama_northbound()
        self.assertTrue(north["available"])
        self.assertEqual(north["date"], "2026-09-08")
        self.assertEqual(north["amount_yi"], 300.0)
        self.assertEqual(north["south_date"], "2026-09-08")
        self.assertEqual(north["south_amount_yi"], 30.0)

    def test_format_amount_keeps_minus_sign_for_main_outflow(self):
        # 板块主力净流入（f62）常为负：负号必须保留，不能只显示绝对值或原始大数
        self.assertEqual(pipeline._format_amount(-1.2e9), "-12.00亿")
        self.assertEqual(pipeline._format_amount(-8.0e4), "-8.00万")
        self.assertEqual(pipeline._format_amount(-500), "-500.00")
        # 非负值行为保持不变
        self.assertEqual(pipeline._format_amount(1.5e9), "15.00亿")
        self.assertEqual(pipeline._format_amount("—"), "—")

    # ------------------------------------------------------------------
    # 渲染层
    # ------------------------------------------------------------------
    def _panorama_payload(self):
        return pipeline._source_result(
            "东方财富·A股全景", "success", is_today=True, content_date="2026-09-08",
            indices=[
                {"code": "000001", "name": "上证指数", "price": 3123.45, "chg_pct": 1.25,
                 "amount": 5.1e11, "chg": 38.50},
                {"code": "399001", "name": "深证成指", "price": 10456.78, "chg_pct": -0.62,
                 "amount": 6.2e11, "chg": -65.30},
            ],
            breadth={"up": 4050, "down": 1300, "flat": 150, "ratio": 3.12,
                     "mood": "普涨强势", "partial": False,
                     "markets": {"沪": {"up": 1800, "down": 500, "flat": 60},
                                 "深": {"up": 2100, "down": 700, "flat": 80},
                                 "京": {"up": 150, "down": 100, "flat": 10}}},
            turnover={"total": 1.138e12, "sh_sz": 1.13e12, "prev_total": 1.087e12,
                      "chg_pct": 4.69,
                      "by_market": {"沪": 5.1e11, "深": 6.2e11, "京": 8.0e9},
                      "partial": False},
            north={"available": True, "amount_yi": 1350.25, "date": "2026-09-08",
                   "south_available": True, "south_amount_yi": 88.50,
                   "south_date": "2026-09-08",
                   "policy_note": pipeline.PANORAMA_NORTH_POLICY_NOTE, "error": None},
            sectors={
                "leading": [{"code": "BK100", "name": "领涨板块甲", "chg_pct": 3.50,
                             "main_inflow": 1.5e9, "lead_stock": "领涨牛股", "lead_stock_pct": 9.9}],
                "lagging": [{"code": "BK200", "name": "领跌板块乙", "chg_pct": -2.10,
                             "main_inflow": -8.0e8, "lead_stock": "领跌熊股", "lead_stock_pct": -6.5}],
            },
            quote_time="2026-09-08 15:00:00")

    def test_panorama_section_renders_in_guizang_theme(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["A股大盘全景"] = self._panorama_payload()
        html = pipeline.generate_report(data, "2026年9月8日 · 周二", "20260908",
                                       theme="guizang")
        self.assertIn(pipeline.SECTION_TITLE_MARKET_REVIEW, html)
        self.assertNotIn("全球大盘全景复盘", html)   # 旧栏目名随合并消失
        # 指数表并入「A股指数」一块：fixture 的 Yahoo 报价没有 as_of，按
        # _reconcile_market_snapshot 同一口径「无法比较日期就不动 Yahoo 的值」，
        # 上证指数用报价数字；东财独有的深证成指补进来并标「（东财）」；成交额来自东财 f6。
        self.assertIn("A股指数", html)
        self.assertNotIn("指数表现", html)
        self.assertIn("上证指数", html)
        self.assertIn("3,813.50", html)
        self.assertIn("深证成指（东财）", html)
        self.assertIn("10,456.78", html)
        # 沪深京分市场成交额与指数「成交额」列同值 → 只出一份
        self.assertEqual(html.count("5100.00亿"), 1)
        self.assertEqual(html.count("6200.00亿"), 1)
        self.assertIn("沪深京成交额合计", html)
        self.assertIn("涨跌家数", html)
        self.assertIn("4,050 家", html)
        self.assertIn("沪深京合计", html)
        self.assertIn("普涨强势", html)
        self.assertIn("3.12", html)
        self.assertIn("成交额", html)
        self.assertIn("南北向资金（前一收盘）", html)
        self.assertIn("北向资金", html)
        self.assertIn("1,350.25 亿元", html)
        self.assertIn("南向成交总额", html)
        self.assertIn("88.50 亿元", html)
        self.assertNotIn("2024-08-19", html)       # 披露口径说明已精简
        self.assertIn("板块热力", html)
        self.assertIn("领涨板块甲", html)
        self.assertIn("领跌板块乙", html)
        self.assertIn("领涨牛股", html)
        # guizang 页面只允许 GZ_* 色板，像素主题高对比色不得泄漏
        for leaked in (pipeline.C_RED, pipeline.C_GREEN, pipeline.C_AMBER,
                       pipeline.C_LEMON, pipeline.C_CYAN):
            self.assertNotIn(leaked, html, f"像素主题配色 {leaked} 泄漏进 guizang 页面")

    def test_panorama_section_renders_in_pixel_theme(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["A股大盘全景"] = self._panorama_payload()
        html = pipeline.generate_report(data, "2026年9月8日 · 周二", "20260908", theme="pixel")
        self.assertIn(pipeline.SECTION_TITLE_MARKET_REVIEW, html)
        self.assertNotIn("全球大盘全景复盘", html)
        self.assertIn("A股指数", html)
        self.assertNotIn("指数表现", html)
        self.assertIn("成交额 6200.00亿", html)     # pixel 把成交额挂在指数名后
        self.assertIn("涨跌家数", html)
        self.assertIn("▲ 上涨 4,050 家", html)
        self.assertIn("普涨强势", html)
        self.assertIn("南北向资金（前一收盘）", html)
        self.assertIn("北向资金", html)
        self.assertIn("南向成交总额", html)
        self.assertIn("1,350.25 亿元", html)
        self.assertIn("88.50 亿元", html)
        self.assertIn("板块热力", html)
        self.assertIn("领涨板块甲", html)

    def test_global_indices_render_once_after_merge(self):
        """合并去重（2026-09-30）：美股 / 港股指数在整份日报里只出现一次。

        原「全球大盘全景复盘」的首个子块「全球指数概览（Yahoo 报价）」复用的就是
        「行情速览」同一次抓取的 Yahoo 快照（道指 / 标普 / 纳指 / 恒指 / 恒科），逐项数字
        完全相同 → 合并后整块删除，报价块成为这些指数的唯一出处。
        """
        quotes = {
            "道琼斯指数": {"price": 44000.0, "change_pct": 0.60, "as_of": "2026-09-08"},
            "标普500": {"price": 6123.45, "change_pct": 1.25, "as_of": "2026-09-08"},
            "纳斯达克": {"price": 19500.0, "change_pct": -0.40, "as_of": "2026-09-08"},
            "恒生指数": {"price": 25000.0, "change_pct": 0.80, "as_of": "2026-09-08"},
            "恒生科技": {"price": 5600.0, "change_pct": -1.10, "as_of": "2026-09-08"},
        }
        for theme in ("guizang", "pixel"):
            with self.subTest(theme=theme):
                data = NewLayoutRenderingTests()._rich_data()
                data["A股大盘全景"] = self._panorama_payload()
                data["实时行情"] = pipeline._source_result(
                    "Yahoo Finance Chart", "success", is_today=True,
                    content_date="2026-09-08", quotes=quotes)
                html = pipeline.generate_report(
                    data, "2026年9月8日 · 周二", "20260908", theme=theme)
                self.assertIn(pipeline.SECTION_TITLE_MARKET_REVIEW, html)
                self.assertNotIn("全球指数概览", html)      # 重复子块已删
                self.assertNotIn("指数表现", html)          # 已并入「A股指数」
                self.assertEqual(html.count("全球与美股"), 1)
                self.assertEqual(html.count("港股双指数"), 1)
                self.assertEqual(html.count("A股指数"), 1)
                for label, price in (("道琼斯指数", "44,000"), ("标普500", "6,123"),
                                     ("纳斯达克", "19,500"), ("恒生指数", "25,000.00"),
                                     ("恒生科技", "5,600.00")):
                    self.assertIn(label, html, f"{theme} 缺少 {label}")
                    # 每个指数的价格全文只出现一次（合并前报价块 + 概览块各一次）
                    self.assertEqual(html.count(price), 1, f"{theme} {label} 报价重复")
                # 阅读顺序：全球与美股 → A股指数 → 港股双指数 → 全景各子块
                self.assertLess(html.find("全球与美股"), html.find("A股指数"))
                self.assertLess(html.find("A股指数"), html.find("港股双指数"))
                self.assertLess(html.find("港股双指数"), html.find("涨跌家数"))

        # 报价快照不可用 → 合并栏只出东财那半边：全球 / 港股块缺席，A股指数整块走东财口径
        data = NewLayoutRenderingTests()._rich_data()
        data["A股大盘全景"] = self._panorama_payload()
        data["实时行情"] = pipeline._source_result(
            "Yahoo Finance Chart", "unavailable", quotes={}, error="offline")
        html = pipeline.generate_report(data, "2026年9月8日 · 周二", "20260908")
        self.assertIn(pipeline.SECTION_TITLE_MARKET_REVIEW, html)
        self.assertNotIn("全球与美股", html)
        self.assertNotIn("港股双指数", html)
        self.assertIn("A股指数 · 截至 09-08（东财）", html)   # 整块东财口径 → 标东财行情日
        self.assertIn("上证指数（东财）", html)
        self.assertIn("3,123.45", html)
        self.assertIn("暂缺：报价", html)                     # 副标题写明缺哪一路
        self.assertIn("涨跌家数", html)                       # 其余子块照常

    def test_panorama_section_absent_and_audited_when_unavailable(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["A股大盘全景"] = pipeline._source_result(
            "东方财富·A股全景", "unavailable", indices=[], breadth=None, turnover=None,
            north={"available": False, "amount_yi": None, "date": None,
                   "south_available": False, "south_amount_yi": None,
                   "south_date": None,
                   "policy_note": pipeline.PANORAMA_NORTH_POLICY_NOTE, "error": "offline"},
            sectors={"leading": [], "lagging": []}, quote_time=None, error="offline")
        html = pipeline.generate_report(data, "2026年9月8日 · 周二", "20260908")
        self.assertNotIn("全球大盘全景复盘", html)   # 旧栏目名不再出现
        # 东财全景暂缺 → 合并栏只出报价那半边：全景子块全部缺席，栏目本身照常渲染
        self.assertIn(pipeline.SECTION_TITLE_MARKET_REVIEW, html)
        for gone in ("涨跌家数", "板块热力", "南北向资金（前一收盘）"):
            self.assertNotIn(gone, html)
        self.assertIn("暂缺：A股全景", html)         # 副标题写明缺哪一路
        self.assertIn("A股大盘全景", html)           # 数据审计栏仍留痕
        self.assertIn("暂缺", html)
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["total_sources"], 8)  # 源数与是否有数据无关（A股资讯已移除）

    def test_panorama_counts_in_audit_and_eligibility(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["A股大盘全景"] = self._panorama_payload()
        html = pipeline.generate_report(data, "2026年9月8日 · 周二", "20260908")
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["total_sources"], 8)  # 审计源数固定，与实收数据无关（A股资讯已移除）
        ok, reason = pipeline.check_push_eligibility(data)
        self.assertTrue(ok)
        # check_push_eligibility 按实收数据源动态计数（rich fixture 未含流动性源 → 8 项缺 1）
        n_dict_sources = len([v for v in data.values() if isinstance(v, dict)])
        self.assertIn(f"/{n_dict_sources}", reason)
        # 全景单独作为唯一「当天」源时也能通过当天检验，证明它真正计入推送门禁
        ok_solo, reason_solo = pipeline.check_push_eligibility(
            {"A股大盘全景": self._panorama_payload()})
        self.assertTrue(ok_solo)
        self.assertIn("1/1", reason_solo)


class ReportInnerDedupeTests(unittest.TestCase):
    """2026-09-09 页内去重：同一标题 / 数字在单份日报只出现一次。"""

    RISK_TITLE = "美股暴跌引发全球市场恐慌情绪蔓延"

    def _dedupe_data(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["实时行情"]["quotes"]["深证成指"] = {
            "price": 12345.67, "change_pct": -2.5, "currency": "CNY"}
        data["实时行情"]["quotes"]["恒生指数"] = {
            "price": 25000.0, "change_pct": 0.8, "currency": "HKD"}
        data["全球头条"]["headlines"].append({
            "title": self.RISK_TITLE, "source": "测试源",
            "url": "", "published_cst": "2026-08-02 11:00", "is_today": True})
        return data

    def test_pixel_risk_from_hidden_section_renders_full_title(self):
        """2026-10-02：全球头条栏目隐藏后，风险区保留完整标题、不生成死链锚点。"""
        html = pipeline.generate_report(
            self._dedupe_data(), "2026年8月2日 · 周日", "20260802", theme="pixel")
        self.assertEqual(html.count(self.RISK_TITLE), 1)  # 全文只在风险区出现一次
        # 栏目已隐藏 → 不做「栏目名 + 第NN条」引用定位，也不留跳转锚点
        self.assertNotIn(f"「{pipeline.SECTION_TITLE_GLOBAL_HEADLINES}」第02条", html)
        self.assertNotIn('href="#h-gh-02"', html)
        self.assertNotIn('id="h-gh-02"', html)
        self.assertIn("命中：", html)                      # 风险行携带命中关键词（新增信息）
        res = pipeline.build_ai_analysis(self._dedupe_data())
        risk = [r for r in res["risks"] if r["title"] == self.RISK_TITLE][0]
        self.assertFalse(risk["shown"])                   # 已隐藏栏目的标题一律 shown=False
        self.assertIn("暴跌", risk["keywords"])

    def test_guizang_risk_full_title_and_tech_aggregate(self):
        """guizang 主题同样口径：风险保留全文 + 动能聚合。"""
        html = pipeline.generate_report(
            self._dedupe_data(), "2026年8月2日 · 周日", "20260802", theme="guizang")
        self.assertEqual(html.count(self.RISK_TITLE), 1)
        self.assertNotIn(f"「{pipeline.SECTION_TITLE_GLOBAL_HEADLINES}」第02条", html)
        self.assertNotIn('href="#h-gh-02"', html)
        self.assertIn("指数动能", html)
        self.assertIn("4 个指数", html)
        self.assertNotIn("明细数值见「AI 行情复盘」", html)

    def test_tech_aggregate_counts_match_quotes(self):
        """动能聚合的涨跌家数与输入行情一致（3 涨 / 1 跌 / 0 平）。"""
        html = pipeline.generate_report(
            self._dedupe_data(), "2026年8月2日 · 周日", "20260802", theme="pixel")
        self.assertIn("指数动能聚合（4 个指数）", html)
        self.assertIn("▲ 3", html)
        self.assertIn("▼ 1", html)
        res = pipeline.build_ai_analysis(self._dedupe_data())
        self.assertEqual(res["tech_stats"]["count"], 4)
        self.assertEqual(
            (res["tech_stats"]["ups"], res["tech_stats"]["downs"], res["tech_stats"]["flats"]),
            (3, 1, 0))

    def test_market_section_shows_hk_indices_in_both_themes(self):
        """恒生指数补缺：双主题【及时秋刀鱼】AI 行情复盘都有港股双指数小节。"""
        for theme in ("pixel", "guizang"):
            html = pipeline.generate_report(
                self._dedupe_data(), "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertIn("港股双指数", html)
            self.assertIn("恒生指数", html)

    def test_multi_factor_matrix_does_not_repeat_quotes(self):
        """多因子矩阵不再复述报价数字：价格只在【及时秋刀鱼】AI 行情复盘出现一次。"""
        for theme in ("pixel", "guizang"):
            html = pipeline.generate_report(
                self._dedupe_data(), "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertEqual(html.count("12,345.67"), 1, f"theme={theme}")  # 千分位价格仅出现一次
            # 涨跌幅：行情复盘明细 + 最终「今日预判」摘要各一次
            self.assertLessEqual(html.count("-2.50%"), 2, f"theme={theme}")

    def test_unshown_channel_risk_keeps_full_title(self):
        """正文截断未展示的风险标题（港股频道第 4 条）：风险区保留全文。"""
        data = self._dedupe_data()
        videos = data["港股名家频道"]["channels"][0]["videos"]
        videos.extend([
            {"title": "午盘点评：恒指窄幅震荡", "video_id": f"v{i}",
             "url": f"https://www.youtube.com/watch?v=v{i}",
             "published": "2026-08-02T02:00:00+00:00",
             "published_cst": "2026-08-02 10:00", "is_today": True}
            for i in (2, 3)
        ])
        videos.append({
            "title": "恒指爆雷股预警名单更新", "video_id": "v4",
            "url": "https://www.youtube.com/watch?v=v4",
            "published": "2026-08-02T08:00:00+00:00",
            "published_cst": "2026-08-02 16:00", "is_today": True})
        html = pipeline.generate_report(
            data, "2026年8月2日 · 周日", "20260802", theme="pixel")
        # 第 4 条正文不展示（只展示前 3 条），风险区必须保留全文以免信息丢失
        self.assertIn("恒指爆雷股预警名单更新", html)
        self.assertNotIn("h-hk-01-04", html)  # 正文无此锚点，不做引用跳转
        res = pipeline.build_ai_analysis(data)
        risk = [r for r in res["risks"] if r["title"] == "恒指爆雷股预警名单更新"][0]
        self.assertFalse(risk["shown"])


class NewsSentimentFactorTests(unittest.TestCase):
    """新闻情绪：词表评分 / 个股归因 / 4 因子数学 / 历史 / 双主题渲染。"""

    def _senti_data(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["全球头条"]["headlines"].extend([
            {"title": "A股股票3大涨创新高，机构上调评级", "source": "华尔街见闻",
             "url": "", "published_cst": "2026-08-02 10:00", "is_today": True},
            {"title": "A股股票3获北向资金净流入超十亿", "source": "财联社",
             "url": "", "published_cst": "2026-08-02 12:00", "is_today": True},
            {"title": "港股股票1暴跌，爆雷风险预警", "source": "智通财经",
             "url": "", "published_cst": "2026-08-02 11:00", "is_today": True},
            # 72h 窗口（2026-08-02 23:59 起算）之外 → 不计入情绪评分/归因
            {"title": "7月30日旧闻：A股股票3不涨令人失望", "source": "旧源",
             "url": "", "published_cst": "2026-07-30 08:00", "is_today": False},
        ])
        return data

    def _senti_history(self):
        return {"version": 1, "stocks": {"A股:000003": {
            "market": "A股", "code": "000003", "name": "A股股票3", "days": {
                "20260727": {"pos": 0, "neu": 0, "neg": 1, "total": 1, "score": -1.0},
                "20260728": {"pos": 0, "neu": 1, "neg": 1, "total": 2, "score": -0.5},
                "20260729": {"pos": 0, "neu": 0, "neg": 0, "total": 0, "score": None},
                "20260730": {"pos": 1, "neu": 1, "neg": 0, "total": 2, "score": 0.5},
                "20260731": {"pos": 1, "neu": 0, "neg": 0, "total": 1, "score": 1.0},
                "20260801": {"pos": 2, "neu": 0, "neg": 0, "total": 2, "score": 1.0},
            }}}}

    def test_headline_scoring_basic(self):
        pos = pipeline._score_headline_sentiment("A股股票3大涨创新高，机构上调评级")
        self.assertEqual(pos["s"], 1)
        self.assertIn("大涨", pos["pos"])
        neg = pipeline._score_headline_sentiment("港股股票1暴跌，爆雷风险预警")
        self.assertEqual(neg["s"], -1)
        self.assertIn("暴跌", neg["neg"])
        neu = pipeline._score_headline_sentiment("公司发布例行公告")
        self.assertEqual(neu["s"], 0)
        self.assertEqual(neu["pos"], [])
        self.assertEqual(neu["neg"], [])

    def test_headline_negation_flip(self):
        down = pipeline._score_headline_sentiment("A股不涨令人失望")
        self.assertEqual(down["s"], -1)   # 不+涨 → 翻转为负
        self.assertIn("涨", down["neg"])
        up = pipeline._score_headline_sentiment("大盘不跌")
        self.assertEqual(up["s"], 1)      # 不+跌 → 翻转为正

    def test_headline_overlap_longest_first(self):
        r = pipeline._score_headline_sentiment("市场暴跌引发恐慌")
        self.assertEqual(r["neg"], ["暴跌"])  # 不与「跌」重复计数
        self.assertEqual(r["neg_n"], 1)

    def test_headline_traditional_chinese(self):
        r = pipeline._score_headline_sentiment("港股創新高，北水淨流入")
        self.assertEqual(r["s"], 1)
        self.assertTrue(r["pos"])

    def test_attribution_and_72h_window(self):
        res = pipeline.build_news_sentiment(self._senti_data(), "20260802", None)
        self.assertTrue(res["available"])
        self.assertEqual(res["total_matched"], 2)
        self.assertEqual(res["scored_headlines"], 3)  # 3 条窗口内标题被归因
        self.assertEqual(res["unattributed_n"], 3)    # 全球头条/东财/港股频道各1条大盘级
        a3 = [s for s in res["stocks"] if s["code"] == "000003"][0]
        self.assertEqual(a3["total"], 2)  # 72h 窗口之外（07-30）旧闻未计入
        self.assertEqual(a3["score"], 1.0)
        self.assertEqual(a3["label"], "偏多")
        # 与报告日同一自然日的标题才进入「今日」桶（供 MOM/ANV 与历史落盘）
        self.assertEqual(res["today_counts"]["A股:000003"]["total"], 2)

    def test_72h_window_includes_recent_prior_day(self):
        # 报告日前 48h 内（08-01）的标题计入 DNS 窗口，但只落 08-01，不进今日桶
        data = NewLayoutRenderingTests()._rich_data()
        corpus = {"version": 1, "items": [
            {"title": "A股股票3大涨创新高，机构上调评级", "source": "华尔街见闻",
             "section": "全球头条", "ts": "2026-08-02 10:00", "date": "2026-08-02"},
            {"title": "A股股票3获北向资金净流入超十亿", "source": "财联社",
             "section": "全球头条", "ts": "2026-08-02 12:00", "date": "2026-08-02"},
            {"title": "A股股票3昨晚暴跌，爆雷风险预警", "source": "智通财经",
             "section": "东财快讯", "ts": "2026-08-01 23:00", "date": "2026-08-01"},
        ]}
        res = pipeline.build_news_sentiment(data, "20260802", None,
                                            news_corpus=corpus)
        a3 = [s for s in res["stocks"] if s["code"] == "000003"][0]
        self.assertEqual((a3["pos"], a3["neg"]), (2, 1))     # 72h 窗口含 08-01
        self.assertAlmostEqual(a3["score"], 1 / 3)
        self.assertEqual(a3["headlines"][-1]["old"], True)   # 旧日标题带 old 标记
        self.assertIn("08-01", pipeline._senti_headline_sub(a3["headlines"][-1]))
        self.assertEqual(res["today_counts"]["A股:000003"]["total"], 2)  # 今日桶只含 08-02

    def test_news_corpus_merge_dedupe_prune_roundtrip(self):
        # news_history.json 的 合并(按 日期+标题 去重) / 剪枝 / 损坏回退
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "news_history.json")
            corpus = pipeline._load_news_corpus(path)  # 缺失 → 空存档
            self.assertEqual(corpus["items"], [])
            fresh = [
                {"title": "央行降准0.5个百分点", "date": "2026-08-02",
                 "source": "新华社", "section": "全球头条", "ts": "2026-08-02 09:00"},
                {"title": "央行降准0.5个百分点", "date": "2026-08-02",  # 同日重复 → 去重
                 "source": "财联社", "section": "东财快讯", "ts": "2026-08-02 10:00"},
                {"title": "统计局公布CPI", "date": "2026-08-01",
                 "source": "统计局", "section": "全球头条", "ts": ""},
            ]
            pipeline._merge_news_corpus(corpus, fresh)
            pipeline._merge_news_corpus(corpus, fresh)  # 幂等：再并一次不增加
            self.assertEqual(len(corpus["items"]), 2)
            pipeline._save_news_corpus(path, corpus)
            loaded = pipeline._load_news_corpus(path)
            self.assertEqual(len(loaded["items"]), 2)
            loaded["items"].append({"title": "老新闻", "date": "2026-07-01",
                                    "source": "", "section": "", "ts": ""})
            pipeline._prune_news_corpus(loaded, "2026-08-02")  # 保留 ~18 日
            self.assertEqual([i["title"] for i in loaded["items"]],
                             ["央行降准0.5个百分点", "统计局公布CPI"])
            bad_path = str(Path(directory) / "broken.json")
            Path(bad_path).write_text("not json{{{", encoding="utf-8")
            self.assertEqual(pipeline._load_news_corpus(bad_path)["items"], [])

    def test_daily_score_math(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["全球头条"]["headlines"].extend([
            {"title": "美股股票0大涨创新高", "source": "s", "url": "",
             "published_cst": "2026-08-02 10:00", "is_today": True},
            {"title": "美股股票0获机构上调评级", "source": "s", "url": "",
             "published_cst": "2026-08-02 11:00", "is_today": True},
            {"title": "美股股票0发布例行公告", "source": "s", "url": "",
             "published_cst": "2026-08-02 12:00", "is_today": True},
            {"title": "美股股票0遭大股东减持", "source": "s", "url": "",
             "published_cst": "2026-08-02 13:00", "is_today": True},
        ])
        res = pipeline.build_news_sentiment(data, "20260802", None)
        s0 = [s for s in res["stocks"] if s["code"] == "000000"][0]
        self.assertEqual((s0["pos"], s0["neu"], s0["neg"]), (2, 1, 1))
        self.assertAlmostEqual(s0["score"], 0.25)  # (2−1)/4
        self.assertEqual(s0["label"], "偏多")

    def test_momentum_math_and_label(self):
        res = pipeline.build_news_sentiment(
            self._senti_data(), "20260802", self._senti_history())
        a3 = [s for s in res["stocks"] if s["code"] == "000003"][0]
        mom = a3["momentum"]
        self.assertTrue(mom["enough"])
        self.assertEqual((mom["short_n"], mom["long_n"]), (3, 6))
        self.assertAlmostEqual(mom["short_mean"], 1.0)
        self.assertAlmostEqual(mom["long_mean"], 1 / 3)
        self.assertAlmostEqual(mom["value"], 2 / 3)
        self.assertEqual(mom["label"], "加速转暖")

    def test_momentum_insufficient_cold_start(self):
        res = pipeline.build_news_sentiment(self._senti_data(), "20260802", None)
        hk1 = [s for s in res["stocks"] if s["code"] == "000001"][0]
        self.assertFalse(hk1["momentum"]["enough"])
        self.assertEqual(hk1["momentum"]["need"], "2/5")

    def test_volume_abnormal_flag(self):
        data = NewLayoutRenderingTests()._rich_data()
        for i in range(4):
            data["全球头条"]["headlines"].append({
                "title": f"美股股票0发布例行公告（{i}）", "source": "s", "url": "",
                "published_cst": "2026-08-02 10:00", "is_today": True})
        days = {}
        for n, (day, total) in enumerate([("20260727", 1), ("20260728", 1),
                                          ("20260729", 2), ("20260730", 1),
                                          ("20260731", 2), ("20260801", 1)]):
            days[day] = {"pos": 0, "neu": total, "neg": 0, "total": total, "score": 0.0}
        history = {"version": 1, "stocks": {"美股:000000": {
            "market": "美股", "code": "000000", "name": "美股股票0", "days": days}}}
        res = pipeline.build_news_sentiment(data, "20260802", history)
        s0 = [s for s in res["stocks"] if s["code"] == "000000"][0]
        vol = s0["volume"]
        self.assertTrue(vol["enough"])
        self.assertTrue(vol["abnormal"])  # 今日4条 > 均值1.33+2σ(1.03)
        self.assertEqual(vol["label"], "异常放量")
        self.assertGreater(vol["z"], 5.0)

    def test_volume_insufficient_few_days(self):
        history = {"version": 1, "stocks": {"A股:000003": {
            "market": "A股", "code": "000003", "name": "A股股票3",
            "days": {"20260801": {"pos": 1, "neu": 0, "neg": 0,
                                  "total": 1, "score": 1.0}}}}}
        res = pipeline.build_news_sentiment(
            self._senti_data(), "20260802", history)
        a3 = [s for s in res["stocks"] if s["code"] == "000003"][0]
        self.assertFalse(a3["volume"]["enough"])
        self.assertEqual(a3["volume"]["n"], 1)

    def test_history_update_merge_prune_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "sentiment_history.json")
            universe = [
                {"market": "A股", "code": "000003", "name": "A股股票3",
                 "key": "A股:000003"},
                {"market": "A股", "code": "000004", "name": "A股股票4",
                 "key": "A股:000004"},
            ]
            history = pipeline._load_sentiment_history(path)  # 缺失 → 空历史
            self.assertEqual(history["stocks"], {})
            counts = {"A股:000003": {"pos": 2, "neu": 0, "neg": 0, "total": 2}}
            pipeline._save_sentiment_history(
                path, pipeline._update_sentiment_history(
                    history, "20260802", universe, counts))
            loaded = pipeline._load_sentiment_history(path)
            day = loaded["stocks"]["A股:000003"]["days"]["20260802"]
            self.assertEqual(day["score"], 1.0)
            zero = loaded["stocks"]["A股:000004"]["days"]["20260802"]
            self.assertEqual(zero["total"], 0)
            self.assertIsNone(zero["score"])  # 零报道日无评分
            # 同日重复落盘幂等
            pipeline._save_sentiment_history(
                path, pipeline._update_sentiment_history(
                    loaded, "20260802", universe, counts))
            reloaded = pipeline._load_sentiment_history(path)
            self.assertEqual(reloaded["stocks"], loaded["stocks"])
            # 超 45 天的数据被修剪，无保留日的个股被清理
            reloaded["stocks"]["A股:000003"]["days"]["20260601"] = {
                "pos": 1, "neu": 0, "neg": 0, "total": 1, "score": 1.0}
            reloaded["stocks"]["过期股"] = {"market": "A股", "code": "", "name": "x",
                                            "days": {"20260601": {
                                                "pos": 0, "neu": 0, "neg": 0,
                                                "total": 0, "score": None}}}
            pruned = pipeline._update_sentiment_history(
                reloaded, "20260810", universe, {})
            self.assertNotIn("20260601",
                             pruned["stocks"]["A股:000003"]["days"])
            self.assertIn("20260802", pruned["stocks"]["A股:000003"]["days"])
            self.assertNotIn("过期股", pruned["stocks"])

    def test_history_corrupt_file_falls_back_to_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sentiment_history.json"
            path.write_text("not json{{{", encoding="utf-8")
            history = pipeline._load_sentiment_history(str(path))
            self.assertEqual(history["stocks"], {})

    def test_by_market_top5_with_per_stock_comment_reason(self):
        res = pipeline.build_news_sentiment(self._senti_data(), "20260802", None)
        by_market = res["by_market"]
        self.assertEqual([m["market"] for m in by_market], ["A股", "港股", "美股"])
        for mb in by_market:
            self.assertEqual(len(mb["stocks"]), pipeline.HOT_STOCK_TOP_N)
        a3 = next(s for s in by_market[0]["stocks"] if s["code"] == "000003")
        self.assertTrue(a3["matched"])
        self.assertAlmostEqual(a3["score"], 1.0)
        self.assertIn("AI情绪分", a3["comment"])
        self.assertIn("近72小时命中 2 条相关新闻", a3["comment"])
        self.assertIn("命中情绪词", a3["reason"])
        self.assertIn("正面主要来自", a3["reason"])
        hk1 = next(s for s in by_market[1]["stocks"] if s["code"] == "000001")
        self.assertTrue(hk1["matched"])
        self.assertAlmostEqual(hk1["score"], -1.0)
        self.assertIn("负面主要来自", hk1["reason"])
        a0 = next(s for s in by_market[0]["stocks"] if s["code"] == "000000")
        self.assertFalse(a0["matched"])
        self.assertIsNone(a0["score"])
        self.assertIn("近72小时无相关点名新闻", a0["comment"])
        self.assertIn("窗口内标题未通过精确名/别名代码/行业概念归因到该股", a0["reason"])
        self.assertIn("暂无评分", a0["label"])

    def test_build_news_sentiment_available_without_match(self):
        # 无归因但榜单存在 → 栏目仍可渲染（逐股「暂无评分」），available 由榜单宇宙决定
        res = pipeline.build_news_sentiment(
            NewLayoutRenderingTests()._rich_data(), "20260802", None)
        self.assertTrue(res["available"])
        self.assertTrue(res["by_market"])
        self.assertEqual(res["total_matched"], 0)
        stocks = [s for mb in res["by_market"] for s in mb["stocks"]]
        self.assertTrue(all(not s["matched"] for s in stocks))
        self.assertTrue(all(s["score"] is None for s in stocks))

    def test_pixel_render_contains_factors(self):
        html = pipeline.generate_report(
            self._senti_data(), "2026年8月2日 · 周日", "20260802",
            theme="pixel", sentiment_history=self._senti_history())
        self.assertIn("新闻情绪", html)
        self.assertIn("A股股票3", html)
        self.assertIn("DNS +1.00", html)
        self.assertIn("MOM +0.67", html)
        self.assertIn("加速转暖", html)
        self.assertIn("z=+0.8", html)
        self.assertIn("S+1", html)
        self.assertIn("S−1", html)
        self.assertIn("命中：大涨", html)
        self.assertIn("样本不足", html)  # 无历史的港股股票1
        self.assertIn("总结评论", html)   # 2026-09-09 逐股 AI 总结评论
        self.assertIn("原因", html)      # 逐股评论原因
        self.assertIn("A股 · 成交量前5", html)

    def test_guizang_render_contains_factors(self):
        html = pipeline.generate_report(
            self._senti_data(), "2026年8月2日 · 周日", "20260802",
            theme="guizang", sentiment_history=self._senti_history())
        self.assertIn("新闻情绪", html)
        self.assertIn("DNS +1.00", html)
        self.assertIn("AI 情绪分", html)
        self.assertIn("A股 · 成交量前5", html)
        self.assertNotIn("暂无评分", html)   # 未被点名的个股不再占位
        if pipeline.LITE_ENABLED:
            # 精简模式（2026-09-30 起默认）：逐股只留「情绪分 + 1 条最强证据」，
            # 原因段与动量 / 新闻量三行折叠（本夹具每市场只有 1~2 只被点名，
            # 不够触发「按只折叠」，因此只断言逐股因子行确实收起）。
            self.assertIn("▲ S+1", html)     # 黑白模式用符号区分方向
            self.assertNotIn("MOM +0.67", html)
            self.assertNotIn("原因", html)
        else:
            self.assertIn("▲ S+1", html)
            self.assertIn("▼ S−1", html)
            self.assertIn("MOM +0.67", html)
            self.assertIn("原因", html)

    def test_guizang_full_mode_keeps_per_stock_factors(self):
        """--full / OCTOPUS_LITE=0：逐股原因段与情绪动量 / 新闻量一行不少地回来。"""
        with patch.object(pipeline, "LITE_ENABLED", False):
            html = pipeline.generate_report(
                self._senti_data(), "2026年8月2日 · 周日", "20260802",
                theme="guizang", sentiment_history=self._senti_history())
        for text in ("MOM +0.67", "▼ S−1", "原因", "AI 情绪分", "A股 · 成交量前5"):
            self.assertIn(text, html)
        self.assertNotIn("已折叠", html)

    def test_per_stock_render_without_attribution(self):
        # 2026-09-27 精简排版：窗口内标题未点名任何榜单个股时栏目整体缺席，
        # 不再逐股输出「暂无评分」占位，也不伪造 DNS 数值。
        data = NewLayoutRenderingTests()._rich_data()  # 标题未提及任何榜单个股
        for theme in ("pixel", "guizang"):
            html = pipeline.generate_report(
                data, "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertNotIn("新闻情绪", html)
            self.assertNotIn("暂无评分", html)
            self.assertNotIn("DNS +", html)
            self.assertNotIn("S+1", html)

    def test_absent_without_hot_rankings(self):
        # 热门榜单（个股宇宙）缺席且无当天标题 → 栏目缺席
        data = NewLayoutRenderingTests()._rich_data()
        for src in ("全球头条", "东财快讯", "港股名家频道"):
            data[src] = pipeline._source_result(src, "unavailable", headlines=[],
                                                channels=[], error="offline")
        data["热门榜单"] = pipeline._source_result(
            "东方财富热门榜", "unavailable", markets={}, error="offline")
        for theme in ("pixel", "guizang"):
            html = pipeline.generate_report(
                data, "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertNotIn("新闻情绪", html)
            self.assertNotIn("样本不足：", html)

    def test_cold_start_renders_with_insufficient_labels(self):
        html = pipeline.generate_report(
            self._senti_data(), "2026年8月2日 · 周日", "20260802",
            theme="pixel")  # 不传历史 → 冷启动
        self.assertIn("新闻情绪", html)
        self.assertIn("DNS +1.00", html)  # 日度因子不受影响
        self.assertIn("MOM 样本不足", html)
        self.assertIn("ANV 样本不足", html)


class PolicyFactorTests(unittest.TestCase):
    """政策因子：关键词矩阵 / 行业 PSI / 量化趋势分 / 总结 / 专业分析区渲染。

    2026-09-09 起标题窗口放宽为近 15 个自然日（含报告日）：
    单日无政策但近 15 日有政策/宏观新闻时栏目照常出现；更早（窗口外）
    的标题不参与。引擎调用统一带 date_str=报告日（YYYYMMDD）固定锚点，
    与生产 main() 一致。
    """

    def _policy_data(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["全球头条"]["headlines"].extend([
            {"title": "央行宣布降准0.5个百分点释放长期资金", "source": "新华社",
             "url": "", "published_cst": "2026-08-02 09:00", "is_today": True},
            {"title": "新能源汽车补贴政策延续，最高补2万", "source": "财联社",
             "url": "", "published_cst": "2026-08-02 10:00", "is_today": True},
            {"title": "美国加征半导体关税，商务部回应", "source": "环球网",
             "url": "", "published_cst": "2026-08-02 11:00", "is_today": True},
            {"title": "机构预计短期暂不降息", "source": "旧逻辑",
             "url": "", "published_cst": "2026-08-02 12:00", "is_today": True},
            # 报告日前一天（08-01）的政策旧闻：15 日窗口内 → 计入，标 old
            {"title": "昨日：证监会约谈多家券商", "source": "旧源",
             "url": "", "published_cst": "2026-08-01 10:00", "is_today": False},
        ])
        data["东财快讯"]["headlines"].append({
            "title": "证监会约谈多家券商，严查违规行为", "source": "东方财富",
            "url": "", "time": "2026-08-02 13:00", "is_today": True})
        return data

    def _minimal_data(self, titles_today):
        return {"全球头条": pipeline._source_result(
            "test", "success", is_today=True, content_date="2026-08-02",
            headlines=[{"title": t, "source": "s", "url": "",
                        "published_cst": "2026-08-02 10:00", "is_today": True}
                       for t in titles_today])}

    def test_easing_fixed_weights(self):
        res = pipeline.build_policy_factor(
            self._minimal_data(["央行宣布降准0.5个百分点释放长期资金"]), "20260802")
        self.assertTrue(res["available"])
        scores = {s["name"]: s["score"] for s in res["industries"]}
        self.assertEqual(scores, {"银行": -1, "证券": 2, "地产链": 2,
                                  "消费": 1, "科技成长": 1})
        self.assertEqual(res["broad_score"], 1)
        self.assertEqual(res["broad_label"], "偏暖")
        self.assertEqual(res["dim_counts"], {"货币宽松": 1})
        self.assertEqual(res["window_days"], 15)   # 标题窗口 = 近 15 自然日
        self.assertEqual(res["total_headlines"], 1)
        head = res["headlines"][0]
        self.assertEqual(head["date"], "2026-08-02")
        self.assertFalse(head["old"])              # 当日标题不带日期前缀

    def test_support_attributes_mentioned_industries(self):
        res = pipeline.build_policy_factor(
            self._minimal_data(["新能源汽车补贴政策延续，最高补2万"]), "20260802")
        scores = {s["name"]: s["score"] for s in res["industries"]}
        self.assertEqual(scores, {"新能源": 2, "汽车": 2})
        self.assertEqual(res["broad_score"], 0)  # 有行业归因，不落宽基
        head = res["headlines"][0]
        self.assertEqual(head["dims"], ["产业扶持"])
        self.assertEqual(head["direction"], 1)

    def test_regulation_without_industry_falls_to_broad(self):
        res = pipeline.build_policy_factor(
            self._minimal_data(["监管部门发布新规规范行业发展"]), "20260802")
        self.assertTrue(res["available"])
        self.assertEqual(res["industries"], [])
        self.assertEqual(res["broad_score"], -1)
        self.assertEqual(res["broad_label"], "偏冷")
        self.assertEqual(res["headlines"][0]["industries"], [])

    def test_negated_trigger_skipped(self):
        res = pipeline.build_policy_factor(self._minimal_data(
            ["机构预计短期暂不降息", "央行年内不会降准"]), "20260802")
        self.assertFalse(res["available"])  # 否定修饰的触发词不计入
        self.assertEqual(res["policy_n"], 0)

    def test_prior_day_policy_news_within_window_counts_as_old(self):
        # 15 日窗口含报告日前一天：08-01 的降准标题计入，并带 old 标记
        data = {"全球头条": pipeline._source_result(
            "test", "success", is_today=True, content_date="2026-08-02",
            headlines=[{"title": "央行宣布降准0.5个百分点", "source": "s",
                        "url": "", "published_cst": "2026-08-01 10:00",
                        "is_today": False}])}
        res = pipeline.build_policy_factor(data, "20260802")
        self.assertTrue(res["available"])
        self.assertEqual(res["policy_n"], 1)
        self.assertEqual(res["headlines"][0]["date"], "2026-08-01")
        self.assertTrue(res["headlines"][0]["old"])  # 旧日标题渲染 MM-DD 前缀
        self.assertEqual(res["headlines"][0]["old"], True)

    def test_outside_15day_window_excluded(self):
        # 2026-08-02 − 14 自然日 = 07-19 起；07-15 的旧闻在窗口外 → 不参与
        data = {"全球头条": pipeline._source_result(
            "test", "success", is_today=True, content_date="2026-08-02",
            headlines=[{"title": "央行宣布降准0.5个百分点", "source": "s",
                        "url": "", "published_cst": "2026-07-15 10:00",
                        "is_today": False}])}
        res = pipeline.build_policy_factor(data, "20260802")
        self.assertFalse(res["available"])
        self.assertEqual(res["policy_n"], 0)
        self.assertEqual(res["total_headlines"], 0)

    def test_multi_trigger_same_dimension_counts_once(self):
        res = pipeline.build_policy_factor(
            self._minimal_data(["降准降息双落地"]), "20260802")
        self.assertEqual(res["dim_counts"], {"货币宽松": 1})  # 同维度只计一次
        scores = {s["name"]: s["score"] for s in res["industries"]}
        self.assertEqual(scores["证券"], 2)  # 权重只落一次

    def test_traditional_triggers(self):
        res = pipeline.build_policy_factor(
            self._minimal_data(["人行降準0.5厘釋放流動性"]), "20260802")
        self.assertTrue(res["available"])
        self.assertEqual(res["broad_score"], 1)
        self.assertEqual(res["dim_counts"], {"货币宽松": 1})

    def test_aggregation_and_summary(self):
        res = pipeline.build_policy_factor(self._policy_data(), "20260802")
        # 降息 + 降准 + 补贴 + 关税 + 约谈×2（含 08-01 旧闻，15 日窗口内）
        # = 6 条；「暂不降息」否定不计入
        self.assertEqual(res["policy_n"], 6)
        self.assertEqual(res["total_headlines"], 9)
        self.assertEqual(res["dim_counts"],
                         {"货币宽松": 2, "产业扶持": 1, "监管收紧": 2, "贸易壁垒": 1})
        self.assertEqual(res["broad_score"], 2)
        self.assertEqual(res["broad_label"], "偏暖")
        self.assertEqual([w["score"] for w in res["winners"]], [4, 2, 2, 2, 2])
        self.assertEqual(
            {w["name"] for w in res["winners"]},
            {"地产链", "科技成长", "新能源", "汽车", "消费"})
        self.assertEqual([w["name"] for w in res["losers"]], ["半导体", "银行"])
        # 证券多空相抵（+2/+2/−2/−2）后 score 归零但仍在榜上
        sec = [s for s in res["industries"] if s["name"] == "证券"][0]
        self.assertEqual((sec["score"], sec["count"]), (0, 4))
        self.assertIn("近15日窗口内检出政策类新闻 6 条", res["summary"])
        self.assertIn("（占窗口资讯 6/9）", res["summary"])
        self.assertIn("PSI +2", res["summary"])
        self.assertIn("偏暖", res["summary"])
        self.assertIn("货币宽松×2", res["summary"])
        # 08-01 旧闻计入并带 old 标记（渲染时加 MM-DD 前缀）
        yesterday = [h for h in res["headlines"] if "昨日" in h["title"]][0]
        self.assertTrue(yesterday["old"])
        self.assertEqual(yesterday["date"], "2026-08-01")
        self.assertEqual(yesterday["dims"], ["监管收紧"])

    def test_macro_data_dimension_counts_cpi_ppi(self):
        # 2026-09-09 增补：CPI/PPI/统计局等宏观数据视为政策因子输入，
        # 让“0 政策新闻”的宏观数据日也能出栏目（不再整日缺席）
        res = pipeline.build_policy_factor(self._minimal_data(
            ["国家统计局：8月份CPI同比温和回升，PPI同比涨幅扩大"]), "20260802")
        self.assertTrue(res["available"])
        self.assertEqual(res["policy_n"], 1)
        self.assertEqual(res["dim_counts"], {"宏观数据": 1})
        self.assertEqual(res["broad_score"], 1)   # 中性偏暖启发式 → 大盘 PSI +1
        names = {s["name"] for s in res["winners"]}
        self.assertIn("消费", names)               # CPI 回升利多消费
        self.assertIn("有色金属", names)           # PPI 涨幅扩大利多上游资源
        self.assertIn("政策及宏观数据类新闻 1 条", res["summary"])

    def test_pixel_renders_policy_in_analysis_group(self):
        html = pipeline.generate_report(
            self._policy_data(), "2026年8月2日 · 周日", "20260802", theme="pixel")
        # 版面从首个有数据的正文栏目开始；本夹具没有 Reddit / StockTwits 样本，情绪栏缺席。
        self.assertIn("LVL 00 // FORECAST", html)      # 今日预判置顶
        self.assertIn("// POLICY SHOCK", html)
        # 2026-10-14 重排：行情复盘 → 政策因子 → 策略研判
        self.assertLess(html.find("// MARKET REVIEW"), html.find("// POLICY SHOCK"))
        self.assertLess(html.find("// POLICY SHOCK"), html.find("// STRATEGY READ"))
        self.assertIn("政策冲击指数", html)
        self.assertIn("量化强度", html)
        self.assertIn("PSI +2", html)
        self.assertIn("政策类新闻 6 条", html)
        self.assertIn("地产链", html)
        # 旧日政策标题以 MM-DD 前缀标注
        self.assertIn("08-01 ·", html)
        self.assertIn("昨日：证监会约谈多家券商", html)

    def test_guizang_renders_policy_after_market_review_before_strategy(self):
        # 2026-10-14 重排：政策因子属「①发生了什么」，位于行情复盘之后、策略研判之前
        html = pipeline.generate_report(
            self._policy_data(), "2026年8月2日 · 周日", "20260802", theme="guizang")
        policy_head = f"{pipeline.SECTION_TITLE_POLICY}</h2>"
        strategy_head = f"{pipeline.SECTION_TITLE_STRATEGY}</h2>"
        market_head = f"{pipeline.SECTION_TITLE_MARKET_REVIEW}</h2>"
        self.assertLess(html.find(market_head), html.find(policy_head))
        self.assertLess(html.find(policy_head), html.find(strategy_head))
        self.assertLess(html.find("【回游金枪鱼】今日预判</h2>"), html.find(strategy_head))
        self.assertIn("PSI +2", html)
        self.assertIn("6 条（近 15 日）", html)
        self.assertIn("政策冲击强度榜", html)
        self.assertNotIn("政策因子口径", html)          # 口径说明已移除
        self.assertIn("08-01 ·", html)

    def test_absent_without_policy_news(self):
        data = self._minimal_data(["美股三大指数集体收涨"])
        for theme in ("pixel", "guizang"):
            html = pipeline.generate_report(
                data, "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertNotIn("政策因子</h2>", html)          # 新旧标题都不出现
            self.assertNotIn(f"{pipeline.SECTION_TITLE_POLICY}</h2>", html)
            self.assertNotIn("政策因子<span", html)

    def test_main_stage_result_honored(self):
        data = self._policy_data()
        html = pipeline.generate_report(
            data, "2026年8月2日 · 周日", "20260802", theme="pixel",
            policy_result={"available": False})  # main 阶段结果优先
        self.assertNotIn("政策因子<span", html)
        html2 = pipeline.generate_report(
            data, "2026年8月2日 · 周日", "20260802", theme="pixel",
            policy_result=None)  # 缺省时渲染侧兜底构建
        self.assertIn("政策因子<span", html2)



class NationalPolicySourceTests(unittest.TestCase):
    """中国政府网官方政策源：解析、降级、存档和双主题溯源。"""

    GOV_HTML = """
    <html><body>
      <ul class="policy-list">
        <li><a href="/zhengce/content/2026/08/content_7070001.htm">
          <span>国务院关于推进绿色低碳发展的意见</span>
        </a><span class="date">2026年8月2日</span></li>
        <li><a href="https://www.gov.cn/zhengce/202607/content_7070002.html">
          国务院办公厅关于做好就业工作的通知
        </a><time>2026-07-31</time></li>
        <li><a href="/zhengce/content/2026/08/content_7070003.htm">没有日期的政策办法</a></li>
        <li><a href="https://example.com/zhengce/content/2026/08/content_7070004.htm">
          第三方转载，不应作为官方政策
        </a><span>2026-08-02</span></li>
        <li><a href="/zhengce/202608/index.htm">政策栏目导航，不是正文</a></li>
        <li><a href="javascript:alert(1)">脚本链接</a></li>
      </ul>
    </body></html>
    """

    def test_parser_keeps_only_official_policy_articles_and_dates(self):
        items = pipeline._parse_gov_policy_html(self.GOV_HTML, limit=10)
        self.assertEqual([item["title"] for item in items], [
            "国务院关于推进绿色低碳发展的意见",
            "国务院办公厅关于做好就业工作的通知",
            "没有日期的政策办法",
        ])
        self.assertEqual(items[0]["url"],
                         "https://www.gov.cn/zhengce/content/2026/08/content_7070001.htm")
        self.assertEqual(items[0]["date"], "2026-08-02")
        self.assertEqual(items[1]["date"], "2026-07-31")
        self.assertEqual(items[2]["date"], "")
        self.assertEqual(items[2]["published_cst"], "—")
        self.assertTrue(all(item["official"] for item in items))

    def test_parser_accepts_bytes_and_limit(self):
        items = pipeline._parse_gov_policy_html(self.GOV_HTML.encode("utf-8"), limit=2)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["source"], "中国政府网")

    def test_fetch_falls_back_to_policy_home(self):
        with patch.object(pipeline, "safe_request", side_effect=[None, self.GOV_HTML]) as request:
            result = pipeline.fetch_gov_policy()
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["official"])
        self.assertEqual(result["page_url"], pipeline.GOV_POLICY_FALLBACK_URL)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(result["headlines"]), 3)

    def test_fetch_is_explicitly_unavailable_without_history_fallback(self):
        with patch.object(pipeline, "safe_request", return_value=None):
            result = pipeline.fetch_gov_policy()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["headlines"], [])
        self.assertTrue(result["official"])
        self.assertIn("gov.cn", result["page_url"])

    def test_official_fields_reach_corpus_and_neutral_policy_factor(self):
        parsed = pipeline._parse_gov_policy_html(self.GOV_HTML, limit=1)
        data = {"国家政策": pipeline._source_result(
            "中国政府网·最新政策", "success", headlines=parsed)}
        items = pipeline._collect_headline_items(data, "2026-08-02")
        self.assertEqual(items[0]["url"], parsed[0]["url"])
        self.assertTrue(items[0]["official"])
        corpus = {"version": 1, "items": []}
        pipeline._merge_news_corpus(corpus, items)
        self.assertEqual(corpus["items"][0]["url"], parsed[0]["url"])
        self.assertTrue(corpus["items"][0]["official"])

        result = pipeline.build_policy_factor(data, "20260802")
        self.assertTrue(result["available"])
        self.assertEqual(result["official_n"], 1)
        self.assertEqual(result["dim_counts"], {"政策发布": 1})
        self.assertIn("中国政府网官方发布 1 条", result["summary"])

    def test_both_themes_render_safe_official_original_link(self):
        data = {"国家政策": pipeline._source_result(
            "中国政府网·最新政策", "success", headlines=[{
                "title": "国务院发布稳增长政策",
                "source": "中国政府网",
                "url": "https://www.gov.cn/zhengce/content/2026/08/content_7070009.htm?a=1&b=2",
                "date": "2026-08-02",
                "published_cst": "2026-08-02",
                "official": True,
            }])}
        for theme in ("pixel", "guizang"):
            html = pipeline.generate_report(
                data, "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertIn("官方原文", html)
            self.assertIn("中国政府网（官方发布）", html)
            self.assertIn("https://www.gov.cn/zhengce/content/2026/08/content_7070009.htm?a=1&amp;b=2", html)
            self.assertLess(html.find("政策因子"), html.find("总结"))


class SectionReadingOrderTests(unittest.TestCase):
    """日报栏目固定为专业分析 → 数据显示 → 结论（两主题共用 _collect_report_parts）。

    正文分析在前、行情与资讯数据居中、今日结论收尾，短线速查卡置于全文末端。
    不生成全篇速览或推导摘要；无数据栏目缺席但不打乱其余顺序。
    2026-09-30 起「行情速览」与「全球大盘全景复盘」合并成一栏「【及时秋刀鱼】AI 行情复盘」，
    2026-10-02 起「东方财富快讯」「【无敌帝王蟹】全球头条」「港股名家频道」三个资讯
    栏目在页面隐藏（保留后台抓取供 AI 分析与审计）。
    """

    def _full_data(self):
        data = NewsSentimentFactorTests()._senti_data()  # 行情/频道/全球/东财/榜单 + 个股标题
        data["全球头条"]["headlines"].append({
            "title": "央行宣布降准0.5个百分点释放长期资金", "source": "新华社",
            "url": "", "published_cst": "2026-08-02 09:00", "is_today": True})
        data["A股大盘全景"] = MarketPanoramaTests()._panorama_payload()
        return data

    # guizang 栏目标题统一以 </h2> 收尾，用它定位真实栏目头，避免命中
    # 策略研判内部的「→ 「全球头条」第N条」等跨栏目引用文字。
    GUIZANG_ORDER = [
        f"{pipeline.SECTION_TITLE_FORECAST}</h2>",
        # ① 发生了什么 → ② 传播得怎么样 → ④ 我们该怎么办 → 总结（2026-10-14 重排）
        f"{pipeline.SECTION_TITLE_MARKET_REVIEW}</h2>",
        f"{pipeline.SECTION_TITLE_POLICY}</h2>",
        f"{pipeline.SECTION_TITLE_NEWS_SENTIMENT}</h2>",
        f"{pipeline.SECTION_TITLE_STRATEGY}</h2>",
        "总结</h2>",
        f"{pipeline.SECTION_TITLE_SHORT_CARD}</h2>",
    ]

    def test_guizang_section_reading_order(self):
        html = pipeline.generate_report(
            self._full_data(), "2026年8月2日 · 周日", "20260802", theme="guizang")
        positions = [html.find(h) for h in self.GUIZANG_ORDER]
        self.assertNotIn(-1, positions, "存在未渲染的栏目标题")
        self.assertEqual(positions, sorted(positions),
                         "栏目顺序不符合阅读逻辑:\n" + "\n".join(
                             f"  {h}: {p}" for h, p in zip(self.GUIZANG_ORDER, positions)))
        self.assertNotIn("东方财富快讯</h2>", html)
        self.assertNotIn("EASTMONEY WIRE", html)
        # 2026-10-02 起另外两个资讯栏目（全球头条 / 港股名家频道）同样隐藏
        self.assertNotIn(f"{pipeline.SECTION_TITLE_GLOBAL_HEADLINES}</h2>", html)
        self.assertNotIn("港股名家频道</h2>", html)

    def _lvl_markers(self, data, kickers):
        """按本次实际渲染的栏目序列生成「LVL nn // KICKER」标记。

        速查卡已收在结论之后，栏目编号按当前实际渲染序列推导；
        编号由栏目序列计算而不是写死，精简 / 全量两种版面共用同一份断言。
        """
        sections = pipeline._collect_report_parts(data, pipeline.PIXEL_KIT,
                                                  date_str="20260802")["sections"]
        index = {kick: i for i, (kick, *_rest) in enumerate(sections)}
        return [f"LVL {index[k]:02d} // {k}" for k in kickers if k in index], index

    def test_pixel_lvl_numbering_follows_reading_order(self):
        data = self._full_data()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802", theme="pixel")
        # 2026-10-14 重排：今日预判 → ①行情复盘 / 政策 → ②新闻情绪 → ④策略研判 → 总结 → 速查卡
        kickers = ["FORECAST", "MARKET REVIEW", "POLICY SHOCK",
                   "NEWS SENTIMENT", "STRATEGY READ", "SUMMARY", "SHORT CARD"]
        order, index = self._lvl_markers(data, kickers)
        self.assertEqual(len(order), len(kickers), "存在未渲染的栏目")
        positions = [html.find(s) for s in order]
        self.assertNotIn(-1, positions, "存在未渲染的 LVL 关卡")
        self.assertEqual(positions, sorted(positions),
                         "LVL 关卡编号顺序不符合阅读逻辑:\n" + "\n".join(
                             f"  {s}: {p}" for s, p in zip(order, positions)))
        # 三个已隐藏的资讯栏目：关卡名既不进栏目序列，也不出现在页面任何位置
        for hidden_kick in ("EASTMONEY WIRE", "GLOBAL HEADLINES", "HK GURU CHANNELS"):
            self.assertNotIn(hidden_kick, index)
            self.assertNotIn(hidden_kick, html)
        # 正文分析 → 数据 → 结论，短线速查卡在最终结论之后收尾。
        self.assertEqual([index[k] for k in kickers], sorted(index[k] for k in kickers))
        self.assertNotIn("AI DIGEST", index)
        self.assertEqual(index["FORECAST"], 0)  # 今日预判置顶
        if "RETAIL SENTIMENT" in index and "MARKET REVIEW" in index:
            # 「发生了什么」组（行情复盘）先于「传播得怎么样」组（散户情绪）
            self.assertLess(index["MARKET REVIEW"], index["RETAIL SENTIMENT"])
        if "SHORT CARD" in index:
            self.assertGreater(index["SHORT CARD"], index["SUMMARY"])

    def test_order_skips_missing_sections_without_shifting_rest(self):
        # 无新闻/无政策/无情绪归因（缺席栏目）时，剩余栏目顺序与编号仍正确
        data = self._full_data()
        for src in ("全球头条", "东财快讯", "港股名家频道"):
            data[src] = pipeline._source_result(
                src, "unavailable", headlines=[], channels=[], error="offline")
        data["热门榜单"] = pipeline._source_result(
            "东方财富热门榜", "unavailable", markets={}, error="offline")
        html = pipeline.generate_report(
            data, "2026年8月2日 · 周日", "20260802", theme="pixel")
        order, _index = self._lvl_markers(
            data, ["FORECAST", "MARKET REVIEW", "STRATEGY READ", "SUMMARY"])
        positions = [html.find(s) for s in order]
        self.assertNotIn(-1, positions, "缺席栏目后剩余关卡渲染不完整")
        self.assertEqual(positions, sorted(positions))
        self.assertNotRegex(html, r"LVL \d+ // QUANT POLICY")
        self.assertNotRegex(html, r"LVL \d+ // NEWS SENTIMENT")


class ConciseLayoutTests(unittest.TestCase):
    """精简排版：专业分析 → 数据显示 → 结论收尾，去过程与无效内容。"""

    def _data(self):
        data = SectionReadingOrderTests()._full_data()
        data["港股名家频道"]["channels"].append({
            "name": "过期频道", "desc": "频道简介不应出现", "url": "",
            "is_today": False,
            "videos": [{"title": "两年前的旧视频", "url": "https://www.youtube.com/watch?v=old",
                        "published_cst": "2024-07-30 16:52", "is_today": False}],
        })
        return data

    def test_analysis_data_conclusion_order_and_emphasis(self):
        html = pipeline.generate_report(
            self._data(), "2026年8月2日 · 周日", "20260802", theme="guizang")
        strategy = html.find(f"{pipeline.SECTION_TITLE_STRATEGY}</h2>")
        market = html.find("【及时秋刀鱼】AI 行情复盘</h2>")
        recap = html.find("总结</h2>")
        forecast = html.find("【回游金枪鱼】今日预判</h2>")
        short_card = html.find(f"{pipeline.SECTION_TITLE_SHORT_CARD}</h2>")
        self.assertGreaterEqual(strategy, 0)
        # 2026-10-14 重排：行情复盘（①）→ 策略研判（④）→ 总结 → 速查卡
        self.assertLess(market, strategy)
        self.assertLess(strategy, recap)
        self.assertLess(recap, short_card)
        # 2026-10-13：今日预判置顶，位于策略研判之前
        self.assertLess(forecast, strategy)
        sections = pipeline._collect_report_parts(
            self._data(), pipeline.GUIZANG_KIT, date_str="20260802")["sections"]
        self.assertEqual(sections[0][0], "FORECAST")
        # 渲染顺序必须与 REPORT_SECTION_ORDER 一致（不依赖具体夹具里有哪些栏目）
        kickers = [section[0] for section in sections if section[0] != "SHORT CARD"]
        self.assertEqual(kickers, [k for k in pipeline.REPORT_SECTION_ORDER if k in kickers])
        self.assertNotIn("AI DIGEST", [section[0] for section in sections])
        self.assertIn("结论 · 重点", html)
        self.assertIn("核心判断", html)
        self.assertIn("今日盘点", html)
        self.assertIn("数据覆盖", html)
        self.assertNotIn("本次数据可用性", html)

    def test_stale_channel_and_explanations_removed(self):
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(
                self._data(), "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertNotIn("两年前的旧视频", html)
            self.assertNotIn("过期频道", html)
            self.assertNotIn("数据暂缺", html)
            self.assertNotIn("/*", html)                      # 像素脚注
            self.assertNotIn("每个频道列出最新", html)
            self.assertNotIn("非交易时段显示最近收盘", html)
        guizang = pipeline.generate_report(
            self._data(), "2026年8月2日 · 周日", "20260802", theme="guizang")
        self.assertNotIn("频道简介不应出现", guizang)
        self.assertNotIn("香港著名股評人", guizang)
        self.assertNotIn("策略研判由公开数据经确定性规则合成", guizang)

    def test_concise_detail_drops_disclaimers(self):
        self.assertEqual(
            pipeline._concise_detail("发布于 2026-09-27 08:00（北京时间）· 社区观点未经核实"),
            "发布于 2026-09-27 08:00")
        self.assertEqual(pipeline._concise_detail("官网公开榜单；数值为抓取快照"), "")
        self.assertEqual(pipeline._concise_detail("营收 TTM 1.2 万亿 · PE 30"), "营收 TTM 1.2 万亿 · PE 30")


class AiTrendAnalysisTests(unittest.TestCase):
    """「【火爆大鱿鱼】美联储因子量化分析」「【巡回巨鲸】地缘政治因子量化分析」：专门抓取 + 词表定调 + 证据引用。

    2026-09-28 按用户要求新增两栏目：阅读位置在政策因子之后、策略研判之前；
    各自由 Google News RSS 主题查询专门抓取，抓取失败整栏缺席、不以旧闻兜底。
    """

    FED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>美联储按兵不动但释放鹰派信号 - 财联社</title>
        <link>https://news.google.com/f1</link>
        <pubDate>Mon, 28 Sep 2026 00:43:23 GMT</pubDate></item>
  <item><title>美联储10月加息的概率为65.9% - 东方财富</title>
        <link>https://news.google.com/f2</link>
        <pubDate>Sun, 27 Sep 2026 15:28:28 GMT</pubDate></item>
</channel></rss>"""

    GEO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>美中同意削减关税并启动AI对话 - 华尔街日报中文网</title>
        <link>https://news.google.com/g1</link>
        <pubDate>Sun, 27 Sep 2026 15:44:54 GMT</pubDate></item>
  <item><title>地区军事摩擦升级互相威胁 - BBC</title>
        <link>https://news.google.com/g2</link>
        <pubDate>Mon, 28 Sep 2026 01:03:00 GMT</pubDate></item>
</channel></rss>"""

    # ---------- ① 专门抓取：Google News RSS 主题查询 ----------
    def test_fetch_fed_trend_uses_dedicated_search_query(self):
        with patch.object(pipeline, "safe_request", return_value=self.FED_XML) as req:
            res = pipeline.fetch_fed_trend()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["source"], pipeline.FED_TREND_SOURCE)
        self.assertIn("news.google.com/rss/search", req.call_args[0][0])
        self.assertIn("hl=zh-CN", req.call_args[0][0])
        self.assertEqual(res["query"], "美联储 OR FOMC OR 鲍威尔")
        self.assertEqual(res["headlines"][0]["title"], "美联储按兵不动但释放鹰派信号")
        self.assertEqual(res["headlines"][0]["source"], "财联社")
        # 允许 is_today 为 False（若测试日期与 pubDate 跨天），但 content_date 应在 3 天内
        self.assertTrue(res["is_today"] or res.get("content_date") is not None)

    def test_fetch_geo_trend_uses_dedicated_search_query(self):
        with patch.object(pipeline, "safe_request", return_value=self.GEO_XML) as req:
            res = pipeline.fetch_geo_trend()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["source"], pipeline.GEO_TREND_SOURCE)
        self.assertIn("news.google.com/rss/search", req.call_args[0][0])
        self.assertEqual(res["query"], "地缘政治 OR 制裁 OR 冲突 OR 关税")
        self.assertEqual(len(res["headlines"]), 2)

    def test_fetch_failure_marks_unavailable_without_fallback(self):
        for fn in (pipeline.fetch_fed_trend, pipeline.fetch_geo_trend):
            with patch.object(pipeline, "safe_request", return_value=None):
                res = fn()
            self.assertEqual(res["status"], "unavailable")
            self.assertEqual(res["headlines"], [])
            self.assertIn("未取得有效新闻", res["error"])

    # ---------- ② 规则定调：词表命中计数 + 证据引用 ----------
    def _fed_data(self):
        return {
            pipeline.FED_TREND_KEY: pipeline._source_result(
                pipeline.FED_TREND_SOURCE, "success", is_today=True,
                content_date="2026-09-28",
                headlines=[
                    {"title": "美联储释放鹰派信号，加息预期升温", "source": "财联社",
                     "url": "", "published_cst": "2026-09-28 08:00", "is_today": True},
                    {"title": "贝森特敦促美联储对通胀保持开放心态", "source": "新浪财经",
                     "url": "", "published_cst": "2026-09-27 16:25", "is_today": False},
                    {"title": "市场押注美联储10月加息", "source": "东方财富",
                     "url": "", "published_cst": "2026-09-27 23:28", "is_today": False},
                ]),
        }

    def test_fed_verdict_counts_hawk_dove_and_cites_evidence(self):
        res = pipeline.build_fed_trend_analysis(self._fed_data())
        self.assertTrue(res["available"])
        # 鹰派/加息 ×2 轮 > 无鸽派词 → 偏鹰
        self.assertEqual(res["verdict"], "偏鹰（紧缩倾向）")
        self.assertEqual(res["negative_label"], "鹰派（紧缩）")
        self.assertEqual(res["positive_n"], 0)
        self.assertGreater(res["negative_n"], 0)
        # 未命中词表的标题不进证据（无方向信息）
        self.assertEqual(len(res["evidence"]), 2)
        ev = res["evidence"][0]
        self.assertIn("鹰派", ev["neg_hits"])
        # 每条证据可溯源：来源 + 发布时间
        self.assertEqual(ev["source"], "财联社")
        self.assertEqual(ev["time"], "2026-09-28 08:00")

    def test_fed_verdict_dovish_and_neutral(self):
        data = self._fed_data()
        data[pipeline.FED_TREND_KEY]["headlines"] = [
            {"title": "美联储释放降息信号，宽松预期升温", "source": "x",
             "url": "", "published_cst": "2026-09-28 08:00", "is_today": True},
            {"title": "官员讨论放缓加息", "source": "y",
             "url": "", "published_cst": "2026-09-28 07:00", "is_today": True}]
        self.assertEqual(pipeline.build_fed_trend_analysis(data)["verdict"],
                         "偏鸽（宽松倾向）")
        data[pipeline.FED_TREND_KEY]["headlines"] = [
            {"title": "美联储官员出席活动", "source": "z",
             "url": "", "published_cst": "2026-09-28 08:00", "is_today": True}]
        self.assertEqual(pipeline.build_fed_trend_analysis(data)["verdict"], "观望")

    def test_geo_verdict_heat_calm_and_neutral(self):
        def geo(title):
            return {pipeline.GEO_TREND_KEY: pipeline._source_result(
                pipeline.GEO_TREND_SOURCE, "success", is_today=True,
                content_date="2026-09-28",
                headlines=[{"title": title, "source": "s", "url": "",
                            "published_cst": "2026-09-28 08:00", "is_today": True}])}
        self.assertEqual(pipeline.build_geo_trend_analysis(
            geo("两国互相威胁，军事摩擦升级"))["verdict"], "升温（对抗）")
        self.assertEqual(pipeline.build_geo_trend_analysis(
            geo("双方会谈达成协议，局势降温"))["verdict"], "缓和（降温）")
        self.assertEqual(pipeline.build_geo_trend_analysis(
            geo("国际新闻简讯"))["verdict"], "平稳")

    def test_fed_board_shows_related_calendar_timepoints(self):
        data = self._fed_data()
        data["财经日历"] = pipeline._source_result(
            "东方财富财经日历", "success", is_today=False, snapshot=True,
            items=[
                {"date": "2026-10-08", "time": "02:00", "name": "美联储议息会议",
                 "imp": 3, "city": "美国", "kind": "事件", "period": ""},
                {"date": "2026-10-03", "time": "20:30", "name": "美国9月非农就业人口",
                 "imp": 3, "city": "美国", "kind": "数据", "period": "2609"},
                {"date": "2026-10-10", "time": "16:00", "name": "中国9月社会融资规模",
                 "imp": 2, "city": "中国", "kind": "数据", "period": "2609"},
            ])
        res = pipeline.build_fed_trend_analysis(data)
        names = [e["name"] for e in res["events"]]
        self.assertIn("美联储议息会议", names)      # FOMC/议息命中
        self.assertIn("美国9月非农就业人口", names)  # 非农命中
        self.assertNotIn("中国9月社会融资规模", names)  # 无关日程不进美联储板
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(
                data, "2026年9月28日 · 周一", "20260928", theme=theme)
            self.assertIn("未来相关时间点（财经日程）", html)
            self.assertIn("美联储议息会议", html)

    def test_fed_board_hides_calendar_subblock_when_calendar_absent(self):
        html = pipeline.generate_report(
            self._fed_data(), "2026年9月28日 · 周一", "20260928")
        self.assertIn("【火爆大鱿鱼】美联储因子量化分析", html)   # 栏目仍渲染
        self.assertNotIn("未来相关时间点（财经日程）", html)  # 只隐藏日程子块

    # ---------- ③ 渲染：双主题 + 阅读位置 + 证据行 ----------
    def _both_topics_data(self):
        data = self._fed_data()
        data[pipeline.GEO_TREND_KEY] = pipeline._source_result(
            pipeline.GEO_TREND_SOURCE, "success", is_today=True,
            content_date="2026-09-28",
            headlines=[
                {"title": "地区军事摩擦升级，双方互相威胁", "source": "BBC",
                 "url": "", "published_cst": "2026-09-28 01:03", "is_today": True},
                {"title": "美中同意削减关税并启动AI对话", "source": "华尔街日报中文网",
                 "url": "", "published_cst": "2026-09-27 23:44", "is_today": False},
            ])
        data["实时行情"] = pipeline._source_result("quote", "success", is_today=True,
                                                  content_date="2026-09-28",
                                                  quotes={"标普500": {"price": 6123.45,
                                                                     "change_pct": 1.25}})
        data["A股大盘全景"] = MarketPanoramaTests()._panorama_payload()
        data["全球头条"] = pipeline._source_result(
            "Google News", "success", is_today=True, content_date="2026-09-28",
            headlines=[{"title": "央行宣布降准0.5个百分点释放长期资金", "source": "新华社",
                        "url": "", "published_cst": "2026-09-28 09:00", "is_today": True}])
        return data

    def test_both_topics_render_in_both_themes_between_policy_and_strategy(self):
        for theme in ("guizang", "pixel"):
            with self.subTest(theme=theme):
                data = self._both_topics_data()
                kit = pipeline.PIXEL_KIT if theme == "pixel" else pipeline.GUIZANG_KIT
                titles = [s[1] for s in pipeline._collect_report_parts(
                    data, kit, date_str="20260928")["sections"]]
                self.assertIn("【火爆大鱿鱼】美联储因子量化分析", titles)
                self.assertIn("【巡回巨鲸】地缘政治因子量化分析", titles)
                self.assertLess(titles.index(pipeline.SECTION_TITLE_POLICY),
                                titles.index("【火爆大鱿鱼】美联储因子量化分析"))
                self.assertLess(titles.index("【火爆大鱿鱼】美联储因子量化分析"),
                                titles.index("【巡回巨鲸】地缘政治因子量化分析"))
                self.assertLess(titles.index("【巡回巨鲸】地缘政治因子量化分析"),
                                titles.index(pipeline.SECTION_TITLE_STRATEGY))
                # 2026-10-14 重排：行情复盘（①）先于政策因子（①）
                self.assertLess(titles.index(pipeline.SECTION_TITLE_MARKET_REVIEW),
                                titles.index(pipeline.SECTION_TITLE_POLICY))
                html = pipeline.generate_report(
                    data, "2026年9月28日 · 周一", "20260928", theme=theme)
                # 证据逐条引用：命中词 + 来源 + 发布时间
                self.assertIn("命中：", html)
                self.assertIn("财联社", html)
                self.assertIn("2026-09-28 08:00", html)

    def test_pixel_kickers_are_fed_and_geo_trend(self):
        html = pipeline.generate_report(
            self._both_topics_data(), "2026年9月28日 · 周一", "20260928", theme="pixel")
        self.assertRegex(html, r"LVL \d+ // FED TREND")
        self.assertRegex(html, r"LVL \d+ // GEO TREND")

    def test_ai_judge_row_attaches_to_both_new_sections(self):
        data = self._both_topics_data()
        notes = pipeline.build_section_ai_notes(
            data,
            fed_trend=pipeline.build_fed_trend_analysis(data),
            geo_trend=pipeline.build_geo_trend_analysis(data))
        self.assertIn("FED TREND", notes)
        self.assertIn("GEO TREND", notes)
        for key in ("FED TREND", "GEO TREND"):
            note = notes[key]
            self.assertEqual(note["bull_pct"] + note["bear_pct"], 100)
            self.assertIn("→ 预测：", note["text"])
        html = pipeline.generate_report(
            data, "2026年9月28日 · 周一", "20260928")
        self.assertGreaterEqual(html.count("⌁ AI 研判"), 3)  # 行情/全景/两专题 + …

    # ---------- ④ 降级与审计 ----------
    def test_failed_fetches_drop_sections_and_are_named_in_coverage(self):
        data = self._both_topics_data()
        data[pipeline.FED_TREND_KEY] = pipeline._source_result(
            pipeline.FED_TREND_SOURCE, "unavailable", headlines=[], error="offline")
        data[pipeline.GEO_TREND_KEY] = pipeline._source_result(
            pipeline.GEO_TREND_SOURCE, "unavailable", headlines=[], error="offline")
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(
                data, "2026年9月28日 · 周一", "20260928", theme=theme)
            self.assertNotIn("【火爆大鱿鱼】美联储因子量化分析", html)
            self.assertNotIn("【巡回巨鲸】地缘政治因子量化分析", html)
            self.assertNotIn("FED TREND", html)
            self.assertNotIn("offline", html)  # 错误详情不进正文
            self.assertIn("暂缺：", html)
            self.assertIn("美联储趋势", html)   # 总结数据覆盖点名
            self.assertIn("地缘政治趋势", html)
        # 采集过就计入审计源数
        meta = pipeline._report_meta(pipeline.generate_report(
            data, "2026年9月28日 · 周一", "20260928"))
        self.assertEqual(meta["total_sources"], 10)  # 8 基础 + 2 专题

    def test_topics_count_in_push_gate(self):
        data = self._both_topics_data()
        ok, reason = pipeline.check_push_eligibility(data)
        self.assertTrue(ok)
        self.assertIn("当天", reason)
        # 两个专题作为唯一当天内容也能通过当天检验
        solo = {pipeline.FED_TREND_KEY: self._fed_data()[pipeline.FED_TREND_KEY]}
        ok_solo, reason_solo = pipeline.check_push_eligibility(solo)
        self.assertTrue(ok_solo)
        self.assertIn("1/1", reason_solo)

    def test_duplicate_headline_not_resurfaced_but_counted(self):
        """全球头条标题不在专题栏目重列，仍计入定调（栏目 2026-10-02 起已隐藏）。

        用不触发政策因子的标题做重复样本，排除政策因子自身条目展示的干扰。
        """
        data = self._both_topics_data()
        dup_title = "地区军事摩擦升级，双方互相威胁"
        data["全球头条"]["headlines"].append({
            "title": dup_title, "source": "新华社", "url": "",
            "published_cst": "2026-09-28 09:30", "is_today": True})
        html = pipeline.generate_report(
            data, "2026年9月28日 · 周一", "20260928", theme="pixel")
        # 全球头条栏目已隐藏，其标题既不成栏目、也不作为专题证据换栏重现
        self.assertEqual(html.count(dup_title), 0)
        self.assertIn("另 1 条重复不重列（已计入定调）", html)

    def test_untruncated_topic_headlines_pruned_by_age(self):
        data = self._fed_data()
        data[pipeline.FED_TREND_KEY]["headlines"].append({
            "title": "两年前的旧闻：美联储曾经降息", "source": "旧闻",
            "url": "", "published_cst": "2024-07-30 10:00", "is_today": False})
        html = pipeline.generate_report(
            data, "2026年9月28日 · 周一", "20260928")
        self.assertNotIn("两年前的旧闻", html)


class SectionAiJudgeTests(unittest.TestCase):
    """逐栏目 AI 研判（规则合成）：概率化多空判断确定性、且只附在有数据的栏目。"""

    def test_prob_mapping_and_labels(self):
        p = pipeline._ai_judge_prob
        self.assertEqual(p(0, 0), 50)
        self.assertEqual(p(1, 1), 50)
        self.assertEqual(p(3, 1), 72)   # 50+45*0.5=72.5 → 72（银行家舍入）
        self.assertEqual(p(1, 3), 28)
        self.assertEqual(p(100, 0), 95)   # 全偏一侧也绝不绝对化
        self.assertEqual(p(0, 100), 5)
        self.assertEqual(pipeline._ai_judge_label(60), ("▲", "偏多"))
        self.assertEqual(pipeline._ai_judge_label(40), ("▼", "偏空"))
        self.assertEqual(pipeline._ai_judge_label(50), ("■", "中性"))

    def _sample_data(self):
        return {
            "实时行情": pipeline._source_result("quote", "success", quotes={
                "标普500": {"price": 6100, "change_pct": 1.2},
                "纳斯达克": {"price": 19000, "change_pct": 2.1},
                "WTI 原油": {"price": 70, "change_pct": -0.8},
            }),
            "Reddit": pipeline._public_site_result("Reddit", [
                {"title": "$TSLA rally to the moon, YOLO and record high",
                 "url": "https://www.reddit.com/r/wallstreetbets/comments/1/a/",
                 "detail": "发布于 2026-09-27 10:00（北京时间）",
                 "published_cst": "2026-09-27 10:00", "community": "r/wallstreetbets",
                 "is_today": True},
                {"title": "$NVDA dump risk",
                 "url": "https://www.reddit.com/r/stocks/comments/2/b/",
                 "detail": "发布于 2026-09-27 11:00（北京时间）",
                 "published_cst": "2026-09-27 11:00", "community": "r/stocks",
                 "is_today": True},
            ], latest="2026-09-27"),
            "全球头条": pipeline._source_result("google", "success", is_today=True,
                                                content_date="2026-09-27",
                                                headlines=[{"title": "美联储释放降息信号，AI 算力需求走强",
                                                            "source": "新华网", "url": "",
                                                            "published_cst": "2026-09-27 09:00",
                                                            "is_today": True}]),
        }

    def test_notes_only_for_sections_with_data_and_valid_probs(self):
        notes = pipeline.build_section_ai_notes(self._sample_data())
        self.assertEqual(set(notes), {"MARKET SNAPSHOT", "TREND TRACKING", "GLOBAL HEADLINES"})
        for note in notes.values():
            self.assertEqual(note["bull_pct"] + note["bear_pct"], 100)
            self.assertTrue(5 <= note["bull_pct"] <= 95)
            self.assertIn("→ 预测：", note["text"])

    def test_reddit_note_tickers_and_direction(self):
        notes = pipeline.build_section_ai_notes(self._sample_data())
        n = notes["TREND TRACKING"]
        self.assertIn("TSLA×1", n["text"])
        self.assertIn("NVDA×1", n["text"])
        # 多词 rally/moon/yolo/record high=4 > 空词 dump=1 → 偏多
        self.assertEqual(n["label"], "偏多")
        self.assertGreater(n["bull_pct"], 50)

    def test_market_note_and_render_in_both_themes(self):
        data = self._sample_data()
        notes = pipeline.build_section_ai_notes(data)
        # 2 涨 1 跌且涨幅合计 > 跌幅 → 偏多
        self.assertEqual(notes["MARKET SNAPSHOT"]["label"], "偏多")
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            for theme in ("guizang", "pixel"):
                with self.subTest(theme=theme):
                    report = pipeline.generate_report(
                        data, "2026年9月27日 · 周日", "20260927", theme=theme)
                    # 有数据的 2 个渲染栏目（行情 / 趋势跟踪）各一条研判行；
                    # 全球头条研判照算（notes 里仍在），但栏目 2026-10-02 起隐藏 → 不成行
                    self.assertEqual(report.count("⌁ AI 研判"), 2)
                    self.assertIn("GLOBAL HEADLINES", notes)
                    self.assertNotIn("条头条", report)
                    # 栏首大白话块统一展示一次上涨概率；后接的「AI 研判」只列数据依据，
                    # 不再重复一遍多头 / 空头概率与同方向预测。
                    self.assertIn("上涨概率", report)
                    self.assertRegex(report, r"上涨概率 \d{2}%")
                    self.assertNotRegex(report, r"多头 \d{2}%")
                    self.assertNotRegex(report, r"空头 \d{2}%")
                    # 研判行位于所属栏目内：首条研判在趋势跟踪栏目之前
                    # （页面 <title> 也含「趋势跟踪」，必须用真实栏目标题定位）
                    trend_pin = ("TREND TRACKING" if theme == "pixel"
                                 else f"{pipeline.SECTION_TITLE_TREND}</h2>")
                    self.assertLess(report.find("⌁ AI 研判"), report.find(trend_pin))
        # 无任何数据 → 不出现研判行
        empty = {"实时行情": pipeline._source_result("quote", "unavailable", error="offline")}
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            report = pipeline.generate_report(empty, "2026年9月27日 · 周日", "20260927")
        self.assertNotIn("⌁ AI 研判", report)


class EconCalendarTests(unittest.TestCase):
    """「时间节点」栏目（原「未来 N 天影响经济时间点」· 东方财富财经日历 RPT_CPH_FECALENDAR）。

    全程离线：接口用 mock 响应替换 safe_request。重点守住四件事——
    ① 筛选口径确定可复现（噪音必须被剔除、重要度分级稳定）；
    ② 窗口诚实（栏目写「未来 30 天」就不能出现 T+30 之外的行）；
    ③ 前瞻日程不得单独打开推送闸门（is_today=False + snapshot=True）；
    ④ 版面裁剪必须如实披露被裁条数，绝不静默丢内容。
    """

    TODAY = dt.date(2026, 9, 28)

    # ---------- 工具 ----------
    @staticmethod
    def _row(day, hm, name, city, ftype="经济数据", std="2"):
        return {"START_DATE": f"{day} {hm}:00", "END_DATE": None, "FE_CODE": "demo",
                "FE_NAME": name, "FE_TYPE": ftype, "STD_TYPE_CODE": std, "CITY": city}

    def _day(self, offset):
        return (self.TODAY + dt.timedelta(days=offset)).isoformat()

    def _rows(self):
        """一批覆盖三类内容 + 各类噪音的样本行。"""
        return [
            # 经济数据：中美核心读数（★★★）、其他主要市场（★★）
            self._row(self._day(1), "09:30", "中国:制造业PMI(报告期:2026年09月)", "中国"),
            self._row(self._day(11), "09:30", "中国:CPI:同比(报告期:2026年09月)", "中国"),
            self._row(self._day(11), "09:30", "中国:CPI:环比(报告期:2026年09月)", "中国"),
            self._row(self._day(11), "09:30", "中国:CPI(报告期:2026年09月)", "中国"),
            self._row(self._day(4), "20:30", "美国:非农就业人数(报告期:2026年09月)", "美国"),
            self._row(self._day(21), "10:00", "欧元区:PMI(报告期:2026年10月)", "欧元区"),
            # 事件：主要央行议息（★★★）、中国宏观决策会议（★★★）、小国央行（★★）、展会（★）
            self._row(self._day(28), "02:00", "美联储议息会议", "华盛顿", "美联储议息会议", "1"),
            self._row(self._day(20), "10:00", "国民经济运行情况发布会", "北京",
                      "国民经济运行情况发布会", "1"),
            self._row(self._day(17), "15:00", "泰国央行公布利率决议", "曼谷", "利率决议", "1"),
            self._row(self._day(13), "09:00", "2026上海国际汽车工业展览会", "上海", "展览会", "1"),
            # 动态：会议纪要 / 周报（★★）、一般资讯（★）
            self._row(self._day(9), "02:00", "美联储公布货币政策会议纪要", "美国", "", "2"),
            self._row(self._day(15), "16:00", "台积电公布月度营业额", "中国台湾", "", "2"),
            # 噪音：个股事项 / 非保留地区 / 冗余子序列 / 「:值」结尾 / 超长条目
            self._row(self._day(6), "09:30", "中国:新股申购:某某科技", "中国", "", "2"),
            self._row(self._day(8), "16:00", "中国:库存:铁矿石:46港", "中国"),
            self._row(self._day(8), "09:30", "泰国:CPI:同比(报告期:2026年09月)", "泰国"),
            self._row(self._day(9), "09:30", "中国:GDP:现价(报告期:2026年09月)", "中国"),
            self._row(self._day(10), "20:30", "美国:货物出口金额:值", "美国"),
            self._row(self._day(12), "09:30", "中国:某超长条目" + "很长" * 30, "中国"),
            # 远期口径：条目保留、误导性报告期标注丢掉
            self._row(self._day(16), "09:30", "中国:CPI:同比(报告期:2027年07月)", "中国"),
        ]

    def _fetch(self, rows=None, count=None, pages=1):
        """用 mock 响应跑一次抓取；pages>1 时验证翻页。"""
        rows = self._rows() if rows is None else rows
        total = len(rows) if count is None else count
        calls = []

        def fake_request(url, headers=None, params=None, timeout=15, is_json=True):
            calls.append(params)
            page = int(params["pageNumber"])
            if page > pages:
                return {"success": True, "result": {"count": total, "data": []}}
            per = max(1, len(rows) // pages)
            chunk = rows[(page - 1) * per:page * per] if page <= pages else []
            return {"success": True, "result": {"count": total, "data": chunk}}

        with patch.object(pipeline, "safe_request", fake_request), \
             patch.object(pipeline.time, "sleep", lambda *_: None):
            res = pipeline.fetch_econ_calendar(today=self.TODAY)
        return res, calls

    def _data(self, cal=None, with_today_source=True):
        data = {}
        if with_today_source:
            data["实时行情"] = pipeline._source_result(
                "quote", "success", is_today=True, content_date=self.TODAY.isoformat(),
                quotes={"上证指数": {"price": 3812.66, "change_pct": 0.31}})
        if cal is not None:
            data["财经日历"] = cal
        return data

    def _report(self, data, theme="guizang"):
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False), \
             patch.object(pipeline, "HK_QUANT_ENABLED", False):
            return pipeline.generate_report(data, "2026年9月28日 · 周一", "20260928",
                                            theme=theme)

    # ---------- ① 筛选口径 ----------
    def test_classify_keeps_core_readings_and_drops_noise(self):
        kept = [it for it in (pipeline._cal_classify(r) for r in self._rows()) if it]
        names = [it["name"] for it in kept]
        self.assertIn("制造业PMI", names)
        self.assertIn("非农就业人数", names)
        # 噪音必须全部剔除
        for noise in ("新股申购", "铁矿石", "现价", "货物出口金额", "某超长条目"):
            self.assertNotIn(noise, "".join(names), f"{noise} 不应进正文")
        # 非保留地区的读数不进正文（泰国 CPI），但小国央行「事件」仍保留为 ★★
        self.assertFalse(any(it["city"] == "泰国" and it["kind"] == 0 for it in kept))
        self.assertTrue(any("泰国央行" in it["name"] for it in kept))

    def test_importance_tiers_are_stable(self):
        kept = [it for it in (pipeline._cal_classify(r) for r in self._rows()) if it]
        by_name = {it["name"]: it for it in kept}
        self.assertEqual(by_name["制造业PMI"]["imp"], 3)          # 中国一级读数
        self.assertEqual(by_name["非农就业人数"]["imp"], 3)        # 美国一级读数
        self.assertEqual(by_name["PMI"]["imp"], 2)                # 欧元区一级读数 → ★★
        self.assertEqual(by_name["美联储议息会议"]["imp"], 3)
        self.assertEqual(by_name["国民经济运行情况发布会"]["imp"], 3)
        self.assertEqual(by_name["泰国央行公布利率决议"]["imp"], 2)  # 小国央行
        self.assertEqual(by_name["2026上海国际汽车工业展览会"]["imp"], 1)  # 展会
        self.assertEqual(by_name["美联储公布货币政策会议纪要"]["kind"], 2)  # 动态
        self.assertLessEqual(by_name["美联储公布货币政策会议纪要"]["imp"], 2)

    def test_event_importance_reads_name_not_city_field(self):
        """事件行的 CITY 常是城市名（华盛顿 / 法兰克福），不能拿它当国家判定。"""
        fed = pipeline._cal_classify(self._row(self._day(5), "02:00", "美联储议息会议",
                                               "华盛顿", "美联储议息会议", "1"))
        self.assertEqual(fed["imp"], 3)
        minor = pipeline._cal_classify(self._row(self._day(5), "15:00", "某国央行公布利率决议",
                                                 "未知市", "利率决议", "1"))
        self.assertEqual(minor["imp"], 2)

    def test_far_future_period_label_dropped_but_item_kept(self):
        item = pipeline._cal_classify(
            self._row(self._day(16), "09:30", "中国:CPI:同比(报告期:2027年07月)", "中国"))
        self.assertIsNotNone(item, "远期口径不应整条丢掉")
        self.assertEqual(item["period"], "", "误导性报告期标注必须丢掉")
        normal = pipeline._cal_classify(
            self._row(self._day(11), "09:30", "中国:CPI:同比(报告期:2026年09月)", "中国"))
        self.assertEqual(normal["period"], "2609")
        self.assertEqual(pipeline._cal_period_label("2609", self.TODAY), "9月")
        self.assertEqual(pipeline._cal_period_label("2701", self.TODAY), "2027年1月")

    def test_dedupe_merges_same_indicator_variants_into_one_row(self):
        rows = [
            self._row(self._day(11), "09:30", "中国:CPI:同比(报告期:2026年09月)", "中国"),
            self._row(self._day(11), "09:30", "中国:CPI:环比(报告期:2026年09月)", "中国"),
            self._row(self._day(11), "09:30", "中国:CPI(报告期:2026年09月)", "中国"),
            self._row(self._day(11), "09:30", "中国:核心CPI:同比(报告期:2026年09月)", "中国"),
        ]
        items = pipeline._cal_dedupe([it for it in (pipeline._cal_classify(r) for r in rows) if it])
        cpi = [it for it in items if pipeline._cal_base_of(it["name"]) == "CPI"]
        self.assertEqual(len(cpi), 1, "同比 / 环比 / 裸名应合并成一行")
        self.assertEqual(cpi[0]["kou"], ["同比", "环比"])
        self.assertIn("CPI:同比/环比", pipeline._cal_item_text(cpi[0], self.TODAY))
        # 核心CPI 是另一个指标，不能被合并掉
        self.assertTrue(any("核心CPI" in it["name"] for it in items))

    def test_strip_country_prefix_without_hurting_real_words(self):
        self.assertEqual(pipeline._cal_strip_country("美国:CPI:同比", "美国"), "CPI:同比")
        self.assertEqual(pipeline._cal_strip_country("美国EIA原油库存", "美国"), "EIA原油库存")
        # 「中国银行间同业拆借」里的「中国」是词的一部分，不能剥
        self.assertEqual(pipeline._cal_strip_country("中国银行间同业拆借", "中国"),
                         "中国银行间同业拆借")

    # ---------- ② 窗口诚实 ----------
    def test_rows_outside_window_are_clamped_locally(self):
        rows = self._rows() + [self._row(self._day(32), "19:00", "欧洲央行公布利率决议",
                                         "法兰克福", "利率决议", "1")]
        res, _ = self._fetch(rows=rows)
        self.assertEqual(res["status"], "success")
        dates = {it["date"] for it in res["items"]}
        self.assertNotIn(self._day(32), dates, "T+32 不得出现在「未来30天」栏目里")
        self.assertNotIn(self._day(32), res["window"])
        self.assertTrue(all(self.TODAY.isoformat() <= d <= self._day(30) for d in dates))

    def test_paging_follows_server_count(self):
        rows = self._rows()
        res, calls = self._fetch(rows=rows, count=len(rows) * 2, pages=2)
        self.assertEqual(res["status"], "success")
        self.assertGreaterEqual(len(calls), 2, "count 未取满时必须继续翻页")
        self.assertEqual(calls[0]["reportName"], "RPT_CPH_FECALENDAR")
        self.assertIn("START_DATE>='2026-09-28'", calls[0]["filter"])
        self.assertIn("START_DATE<'2026-10-29'", calls[0]["filter"])

    def test_failure_degrades_to_zanque_with_reason(self):
        with patch.object(pipeline, "safe_request", lambda *a, **k: None):
            res = pipeline.fetch_econ_calendar(today=self.TODAY)
        self.assertEqual(res["status"], "failed")
        self.assertTrue(res.get("error"), "失败必须给出原因，不能静默")
        self.assertEqual(res["items"], [])
        self.assertFalse(res.get("is_today"))
        self.assertFalse(res.get("snapshot"))

    def test_empty_window_is_reported_as_failure_not_as_empty_calendar(self):
        with patch.object(pipeline, "safe_request",
                          lambda *a, **k: {"success": True, "result": {"count": 0, "data": []}}):
            res = pipeline.fetch_econ_calendar(today=self.TODAY)
        self.assertEqual(res["status"], "failed")
        self.assertIn("接口未返回窗口内日程", res["error"])

    # ---------- ③ 推送闸门与审计口径 ----------
    def test_calendar_alone_never_unlocks_push_gate(self):
        """前瞻日程不是「当天内容」：只有它成功时仍不得推送（防旧内容/空报告）。"""
        res, _ = self._fetch()
        can_push, reason = pipeline.check_push_eligibility(self._data(res, with_today_source=False))
        self.assertFalse(can_push)
        self.assertIn("当天检验未通过", reason)
        self.assertFalse(res["is_today"])
        self.assertTrue(res["snapshot"], "应标为「今日抓取」快照，而不是当天发布")

    def test_calendar_does_not_change_today_source_count(self):
        res, _ = self._fetch()
        base = self._report(self._data(with_today_source=True))
        with_cal = self._report(self._data(res))
        meta_base = pipeline._report_meta(base)
        meta_cal = pipeline._report_meta(with_cal)
        self.assertEqual(meta_cal["today_sources"], meta_base["today_sources"])
        self.assertEqual(meta_cal["total_sources"], meta_base["total_sources"] + 1)

    def test_absent_calendar_keeps_source_count_unchanged(self):
        """OCTOPUS_CALENDAR=0 时不采集 → 不进审计，总源数与改动前一致（+1 只在采集时发生）。"""
        base = pipeline._report_meta(self._report(self._data(with_today_source=True)))
        res, _ = self._fetch()
        with_cal = pipeline._report_meta(self._report(self._data(res)))
        self.assertEqual(base["total_sources"], 8, "基础审计源数量不应被本次改动改变")
        self.assertEqual(with_cal["total_sources"], base["total_sources"] + 1)

    def test_failed_calendar_is_named_in_coverage_line(self):
        with patch.object(pipeline, "safe_request", lambda *a, **k: None):
            res = pipeline.fetch_econ_calendar(today=self.TODAY)
        html = self._report(self._data(res))
        self.assertNotIn("【探照安康鱼】时间节点量化分析", html, "抓取失败的栏目不进正文")
        self.assertNotIn("未来30天影响经济时间点", html, "旧栏目名不得回潮")
        self.assertRegex(html, r"暂缺：[^<]*财经日历")

    # ---------- ④ 排版与披露 ----------
    def test_calendar_is_in_data_group_before_conclusion(self):
        res, _ = self._fetch()
        data = self._data(res)
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False), \
             patch.object(pipeline, "HK_QUANT_ENABLED", False):
            kickers = [s[0] for s in pipeline._collect_report_parts(
                data, pipeline.PIXEL_KIT, date_str="20260928")["sections"]]
        pixel_markers = [f"LVL {kickers.index(k):02d} // {k}"
                         for k in ("FORECAST", "MARKET REVIEW", "ECON CALENDAR", "SUMMARY",
                                   "SHORT CARD") if k in kickers]
        for theme, markers in (
            ("guizang", ["【回游金枪鱼】今日预判</h2>", "【及时秋刀鱼】AI 行情复盘</h2>",
                         "【探照安康鱼】时间节点量化分析</h2>", "总结</h2>",
                         f"{pipeline.SECTION_TITLE_SHORT_CARD}</h2>"]),
            ("pixel", pixel_markers),
        ):
            html = self._report(data, theme=theme)
            positions = [html.find(m) for m in markers]
            self.assertNotIn(-1, positions, f"{theme} 栏目缺失: {markers}")
            self.assertEqual(positions, sorted(positions),
                             f"{theme} 顺序必须为今日预判 → 发生了什么（行情/日程）→ 总结 → 速查卡")

    def test_section_body_carries_window_summary_and_star_levels(self):
        res, _ = self._fetch()
        with pipeline.notes_mode():          # 「筛选口径」是过程说明：--notes 下可见
            html = self._report(self._data(res))
        for text in ("窗口摘要", "时间窗口", "时间点合计", "央行议息 / 重要会议",
                     "中国关键读数", "美国关键读数", "最密集日", "筛选口径",
                     pipeline._calendar_table_label(), "★★★", "美联储议息会议"):
            self.assertIn(text, html, f"摘要/正文缺少 {text}")
        plain_html = self._report(self._data(res))      # 入门版：数字摘要都在，筛选过程不出
        for text in ("窗口摘要", "时间点合计", "最密集日", pipeline._calendar_table_label(),
                     "★★★", "美联储议息会议"):
            self.assertIn(text, plain_html, f"入门版缺少 {text}")
        self.assertNotIn("筛选口径", plain_html)
        self.assertNotIn("规则合成，非方向判断", plain_html)
        self.assertIn("未来 30 天", html)
        # 每个列出的时间点都要能看到地区与类型标签（数据 / 事件 / 动态）
        self.assertIn("数据", html)
        self.assertIn("事件", html)

    def test_row_cap_discloses_every_dropped_item_by_level(self):
        rows = []
        for i in range(70):                      # 造出远超上限的 ★★★ 条目
            rows.append(self._row(self._day(1 + i % 29), f"{9 + i % 8}:30",
                                  f"中国:CPI:同比{i}(报告期:2026年09月)", "中国"))
        res, _ = self._fetch(rows=rows)
        limit = pipeline.ECON_CALENDAR_MAX_ROWS
        self.assertEqual(len(res["items"]), limit)
        self.assertEqual(res["dropped"], len(rows) - limit)
        self.assertEqual(sum(int(v) for v in res["dropped_imp"].values()), res["dropped"])
        digest = pipeline._cal_digest(res, self.TODAY)
        total_line = dict(digest["pairs"])["时间点合计"]
        self.assertIn(f"版面另有 {res['dropped']} 条未列出", total_line)
        self.assertIn("★★★", total_line, "被裁条目的重要度分布必须写清楚")

    def test_low_importance_rows_are_cut_before_core_readings(self):
        rows = self._rows() + [
            self._row(self._day(2), "09:00", f"某展会{i}届博览会", "上海", "博览会", "1")
            for i in range(80)
        ]
        with patch.object(pipeline, "ECON_CALENDAR_MAX_ROWS", 20):
            res, _ = self._fetch(rows=rows)
        names = "".join(it["name"] for it in res["items"])
        self.assertIn("美联储议息会议", names, "★★★ 事件不能被 ★ 级展会挤掉")
        self.assertIn("制造业PMI", names)
        self.assertLessEqual(sum(1 for it in res["items"] if it["imp"] == 1), 20 - 8)

    def test_digest_counts_match_items(self):
        res, _ = self._fetch()
        digest = pipeline._cal_digest(res, self.TODAY)
        pairs = dict(digest["pairs"])
        counts = pipeline._cal_imp_counts(res["items"])
        self.assertIn(f"{len(res['items'])} 个", pairs["时间点合计"])
        self.assertIn(f"★★★ {counts['3']}", pairs["时间点合计"])
        day_items = sum(len(items) for _d, _l, _t, items in digest["days"])
        self.assertEqual(day_items, len(res["items"]), "逐日展开必须与条目数一致")
        # 摘要里点名的时间点必须真的在列表里（不得凭空生成日程）
        for label in ("央行议息 / 重要会议", "中国关键读数", "美国关键读数"):
            for chunk in re.split(r"[、,]", pairs[label].split(" 等 ")[0]):
                name = chunk.split(" ", 1)[-1].strip()
                if name and name != "窗口内暂无":
                    self.assertIn(name[:6], "".join(it["name"] for it in res["items"]),
                                  f"{label} 里的 {name} 不在抓取结果中")

    def test_calendar_block_renders_in_both_kits_and_stays_balanced(self):
        res, _ = self._fetch()
        for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
            block = kit.calendar_block(res)
            self.assertIn("窗口摘要", block)
            self.assertEqual(block.count("<table"), block.count("</table>"),
                             "表格必须成对闭合（微信端半截标签会整页崩版）")

    def test_calendar_only_cli_mode_prints_without_pushing(self):
        res, _ = self._fetch()
        with patch.object(pipeline, "fetch_econ_calendar", lambda days=None: res), \
             patch.object(pipeline, "push_to_wechat", lambda *a, **k: self.fail("研究模式不得推送")), \
             patch.object(pipeline, "generate_report", lambda *a, **k: self.fail("研究模式不得生成日报")):
            self.assertEqual(pipeline.calendar_only_report(), 0)



class OpeningDigestRemovalTests(unittest.TestCase):
    """报告直接从首个有真实数据支持的正文栏目开始，不再生成 AI 全篇速览。"""

    def test_first_section_is_the_data_backed_retail_factor(self):
        data = {"Reddit": pipeline._public_site_result("Reddit", [{
            "title": "Bullish market rally", "url": "https://www.reddit.com/r/stocks/comments/1/a/",
            "community": "r/stocks", "published_cst": "2026-09-28 10:00",
            "score": 10, "comments": 2,
        }], latest="2026-09-28")}
        for theme in ("guizang", "pixel"):
            with self.subTest(theme=theme):
                parts = pipeline._collect_report_parts(
                    data, pipeline.GUIZANG_KIT if theme == "guizang" else pipeline.PIXEL_KIT,
                    date_str="20260928")
                self.assertEqual(parts["sections"][0][0], "RETAIL SENTIMENT")
                html = pipeline.generate_report(
                    data, "2026年9月28日", "20260928", theme=theme)
                self.assertIn("【麻辣大龙虾】散户群体情绪量化分析", html)
                self.assertNotIn("【爪爪八爪鱼】AI 全篇速览", html)
                self.assertNotIn("AI DIGEST", html)
                self.assertNotIn("当前信息不足以形成综合方向判断", html)
                if theme == "pixel":
                    self.assertIn("LVL 00 // RETAIL SENTIMENT", html)
                self.assertLess(html.index("【麻辣大龙虾】散户群体情绪量化分析"),
                                html.index(pipeline.SECTION_TITLE_TREND))

    def test_factor_and_opening_digest_both_absent_without_community_samples(self):
        parts = pipeline._collect_report_parts({}, pipeline.GUIZANG_KIT, date_str="20260928")
        self.assertNotIn("RETAIL SENTIMENT", [section[0] for section in parts["sections"]])
        html = pipeline.generate_report({}, "2026年9月28日", "20260928")
        self.assertNotIn("【麻辣大龙虾】散户群体情绪量化分析", html)
        self.assertNotIn("【爪爪八爪鱼】AI 全篇速览", html)
        self.assertNotIn("AI DIGEST", html)
        self.assertNotIn("当前信息不足以形成综合方向判断", html)



class SectionRenameTests(unittest.TestCase):
    """正文标题改名回归；已移除的 AI 全篇速览不再是栏目或标题常量。"""

    EXPECTED = {
        "FORECAST": "【回游金枪鱼】今日预判",
        "ECON CALENDAR": "【探照安康鱼】时间节点量化分析",
    }

    def _data(self):
        """离线夹具：实时行情（当天）+ 财经日历（mock 东财响应）。"""
        cal = EconCalendarTests()
        res, _ = cal._fetch()
        return cal._data(res)

    def test_title_constants_match_requested_names(self):
        self.assertEqual(pipeline.SECTION_TITLE_RETAIL_SENTIMENT,
                         "【麻辣大龙虾】散户群体情绪量化分析")
        self.assertEqual(pipeline.SECTION_TITLE_FORECAST, self.EXPECTED["FORECAST"])
        self.assertEqual(pipeline.SECTION_TITLE_ECON_CALENDAR, self.EXPECTED["ECON CALENDAR"])
        # 2026-10-23 栏目下线：标题常量随之移除
        self.assertFalse(hasattr(pipeline, "SECTION_TITLE_QUANT_FORECAST"))

    def test_sections_carry_current_names_and_no_opening_digest(self):
        data = self._data()
        for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
            titles = {s[0]: s[1] for s in pipeline._collect_report_parts(
                data, kit, date_str="20260928")["sections"]}
            self.assertNotIn("AI DIGEST", titles)
            for kick in ("FORECAST", "ECON CALENDAR"):
                want = self.EXPECTED[kick]
                self.assertEqual(titles.get(kick), want,
                                 f"{kick} 栏目标题应为 {want}")
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(data, "2026年9月28日 · 周一", "20260928",
                                            theme=theme)
            self.assertNotIn("【爪爪八爪鱼】AI 全篇速览", html)
            self.assertNotIn("AI DIGEST", html)
            for kick in ("FORECAST", "ECON CALENDAR"):
                want = self.EXPECTED[kick]
                self.assertIn(want, html, f"{theme} 缺少栏目标题 {want}")
            self.assertNotIn(">今日预判<", html)
            self.assertNotIn("未来30天影响经济时间点", html)

    def test_calendar_window_still_disclosed_after_title_shortened(self):
        """标题不再带天数后，窗口天数仍须在栏目「窗口摘要 · 时间窗口」里如实显示。"""
        html = pipeline.generate_report(self._data(), "2026年9月28日 · 周一", "20260928")
        self.assertIn("时间窗口", html)
        self.assertIn("未来 30 天", html)


class SectionRenameBatch2Tests(unittest.TestCase):
    """2026-09-29 第二批栏目改名回归：只改标题文字，内容 / 顺序 / 抓取 / 门禁不变。

    全球头条 → 【无敌帝王蟹】全球头条；趋势跟踪 → 【深海大鲨鱼】趋势跟踪；
    政策因子 → 【深海肥蓝鲸】政策因子；每周量化走势预测 → 【嗜血大白鲨】逐日走势量化分析。
    边界：数据源键名（全球头条 / 国家政策 / 每周走势预测 / Reddit…）、新鲜度阈值键、
    审计标签、像素主题英文关卡名与图标砖短标签一律不变；风险提示里的跨栏目引用
    （「『栏目名』第NN条」）指向正文栏目头，因此同步用新标题。
    """

    EXPECTED = {
        "STRATEGY READ": "【六眼飞鱼】量化 MACD 策略",
        "GLOBAL HEADLINES": "【无敌帝王蟹】全球头条",
        "TREND TRACKING": "【深海大鲨鱼】趋势跟踪",
        "POLICY SHOCK": "【深海肥蓝鲸】政策因子",
        "WEEKLY FORECAST": "每日趋势量化推演",
    }
    # 2026-10-02 起「【无敌帝王蟹】全球头条」与「港股名家频道」在页面隐藏（数据照抓）：
    # 标题常量与数据线名字保持原样，但不再渲染成栏目。
    HIDDEN_KICKERS = ("GLOBAL HEADLINES", "HK GURU CHANNELS")
    # 旧标题（改名前的栏目头文字）：不得再以任何主题的栏目头形式出现
    OLD_HEADS = (">策略研判</h2>", ">全球头条</h2>", ">趋势跟踪</h2>", ">政策因子</h2>",
                 ">每周量化走势预测</h2>")

    def _data(self):
        """离线夹具：政策因子 + 全球头条 + 趋势跟踪（Reddit）+ 每周量化走势预测。"""
        import test_weekly as tw                            # 真实周度引擎（合成行情，离线）
        data = PolicyFactorTests()._policy_data()          # 行情 / 全球头条 / 东财 / 榜单 / 政策标题
        data["Reddit"] = pipeline._public_site_result("Reddit", [
            {"title": "$TSLA rally to the moon, YOLO and record high",
             "url": "https://www.reddit.com/r/wallstreetbets/comments/1/a/",
             "detail": "发布于 2026-08-02 10:00（北京时间）",
             "published_cst": "2026-08-02 10:00", "community": "r/wallstreetbets",
             "is_today": True}], latest="2026-08-02")
        data["每周走势预测"] = tw.WeeklyPipelineIntegrationTests()._source()
        return data

    def test_title_constants_match_requested_names(self):
        self.assertEqual(pipeline.SECTION_TITLE_STRATEGY, self.EXPECTED["STRATEGY READ"])
        self.assertEqual(pipeline.SECTION_TITLE_STRATEGY_READ, self.EXPECTED["STRATEGY READ"])
        self.assertEqual(pipeline.SECTION_TITLE_GLOBAL_HEADLINES, self.EXPECTED["GLOBAL HEADLINES"])
        self.assertEqual(pipeline.SECTION_TITLE_TREND, self.EXPECTED["TREND TRACKING"])
        self.assertEqual(pipeline.SECTION_TITLE_POLICY, self.EXPECTED["POLICY SHOCK"])
        self.assertEqual(pipeline.SECTION_TITLE_WEEKLY_FORECAST, self.EXPECTED["WEEKLY FORECAST"])

    def test_sections_carry_new_names_in_both_themes(self):
        data = self._data()
        rendered = {k: v for k, v in self.EXPECTED.items()
                    if k not in self.HIDDEN_KICKERS}
        for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
            titles = {s[0]: s[1]
                      for s in pipeline._collect_report_parts(data, kit,
                                                             date_str="20260802")["sections"]}
            for kick, want in rendered.items():
                self.assertEqual(titles.get(kick), want, f"{kick} 栏目标题应为 {want}")
            # 已隐藏栏目不再成栏，但数据仍被抓取（审计里照旧点名）
            for kick in self.HIDDEN_KICKERS:
                self.assertNotIn(kick, titles, f"{kick} 已隐藏，不应再成栏目")
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802",
                                            theme=theme)
            for kick, want in rendered.items():
                self.assertIn(want, html, f"{theme} 缺少新栏目标题 {want}")
            for kick in self.HIDDEN_KICKERS:
                self.assertNotIn(kick, html, f"{theme} 仍渲染已隐藏栏目 {kick}")
            for old_head in self.OLD_HEADS:
                self.assertNotIn(old_head, html, f"{theme} 旧栏目头回潮：{old_head}")

    def test_reading_order_is_analysis_then_data_then_conclusion(self):
        order = pipeline.REPORT_SECTION_ORDER
        # 2026-10-14 重排：今日预判 → ①发生了什么 → ②传播得怎么样 → ③可能会怎样 → ④怎么办 → 总结
        self.assertEqual(order[1], "MARKET REVIEW")
        self.assertLess(order.index("MARKET REVIEW"), order.index("POLICY SHOCK"))
        self.assertLess(order.index("POLICY SHOCK"), order.index("RETAIL SENTIMENT"))
        self.assertLess(order.index("RETAIL SENTIMENT"), order.index("TREND TRACKING"))
        self.assertLess(order.index("TREND TRACKING"), order.index("NEWS SENTIMENT"))
        self.assertLess(order.index("NEWS SENTIMENT"), order.index("WEEKLY FORECAST"))
        self.assertLess(order.index("WEEKLY FORECAST"), order.index("STRATEGY READ"))
        self.assertLess(order.index("STRATEGY READ"), order.index("SECTOR ROTATION"))
        # 2026-10-13：今日预判置顶，总结仍在末尾
        self.assertEqual(order[0], "FORECAST")
        self.assertEqual(order[-1], "SUMMARY")
        # 2026-10-02 起两个资讯栏目退出正文顺序表（与 EASTMONEY WIRE 同口径）
        for kick in self.HIDDEN_KICKERS:
            self.assertNotIn(kick, order)
        titles = [s[1] for s in pipeline._collect_report_parts(
            self._data(), pipeline.GUIZANG_KIT, date_str="20260802")["sections"]]
        pos = [titles.index(self.EXPECTED[k]) for k in
               ("POLICY SHOCK", "TREND TRACKING", "WEEKLY FORECAST", "STRATEGY READ")]
        self.assertEqual(pos, sorted(pos))

    def test_data_line_names_and_audit_labels_unchanged(self):
        """只改栏目标题：数据源键名 / 新鲜度阈值键 / 审计标签不动。"""
        self.assertIn("全球头条", pipeline._freshness.FRESHNESS_THRESHOLDS)
        self.assertIn("每周量化走势预测", pipeline._freshness.FRESHNESS_THRESHOLDS)
        # 数据线注册表的 used_by 写的是栏目标题 → 跟随改名（与 2026-09-29 第一批一致）
        used_by = [u for line in pipeline._backup.DATA_LINES.values() for u in line["used_by"]]
        self.assertIn(f"{pipeline.SECTION_TITLE_STRATEGY}·MACD日线", used_by)
        self.assertIn(pipeline.SECTION_TITLE_GLOBAL_HEADLINES, used_by)
        self.assertIn(pipeline.SECTION_TITLE_POLICY, used_by)
        self.assertIn(pipeline.SECTION_TITLE_TREND, used_by)
        self.assertIn(pipeline.SECTION_TITLE_WEEKLY_FORECAST, used_by)
        self.assertIn(pipeline.SECTION_TITLE_NEWS_SENTIMENT, used_by)
        for stale in ("策略研判", "策略研判·MACD日线", "全球头条", "政策因子", "趋势跟踪",
                      "每周量化走势预测", "新闻情绪"):
            self.assertNotIn(stale, used_by, f"注册表里仍写着旧栏目标题：{stale}")
        # 审计标签（数据源名）不随栏目标题改名
        data = self._data()
        parts = pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT, date_str="20260802")
        footer = pipeline._status_footer([("全球头条", data["全球头条"]),
                                          ("每周量化走势预测（恒指·7交易日）",
                                           data["每周走势预测"])])
        self.assertIn("全球头条", footer)
        self.assertIn("每周量化走势预测（恒指·7交易日）", footer)
        self.assertGreater(parts["total"], 0)

    def test_pixel_kickers_and_icon_labels_unchanged(self):
        """像素主题英文关卡名与图标砖短标签是关卡标识，不随中文标题改名。"""
        html = pipeline.generate_report(self._data(), "2026年8月2日 · 周日", "20260802",
                                        theme="pixel")
        for kicker in ("STRATEGY READ", "TREND TRACKING", "POLICY SHOCK", "WEEKLY FORECAST"):
            self.assertIn(kicker, html)
        # 全球头条栏目已隐藏 → 关卡名不再出现在页面（视觉注册表本身保持不变）
        self.assertNotIn("GLOBAL HEADLINES", html)
        self.assertEqual(pipeline._section_visual("STRATEGY READ")[1], "STRAT")
        self.assertEqual(pipeline._section_visual("GLOBAL HEADLINES")[1], "NEWS")
        self.assertEqual(pipeline._section_visual("TREND TRACKING")[1], "TREND")
        self.assertEqual(pipeline._section_visual("POLICY SHOCK")[1], "POLICY")
        self.assertEqual(pipeline._section_visual("WEEKLY FORECAST")[1], "WEEK-FX")

    def test_weekly_window_disclosure_survives_shortened_title(self):
        """新标题不再带「每周」，七日视界口径仍须在栏目内如实披露（2026-09-29 起 5→7 个交易日）。"""
        html = pipeline.generate_report(self._data(), "2026年8月2日 · 周日", "20260802")
        self.assertIn("个交易日", html)
        self.assertIn("P(7日涨)", html)
        self.assertNotIn("先存档后结算", html)       # 入门版（默认）：口径披露不出
        with pipeline.notes_mode():
            html = pipeline.generate_report(self._data(), "2026年8月2日 · 周日", "20260802")
        self.assertIn("先存档后结算", html)

    def test_risk_reference_uses_new_headline_title(self):
        """风险提示的跨栏目引用指向正文栏目头，因此用新标题（读者按名字能找到）。"""
        label = pipeline._risk_ref_label(
            {"section": pipeline.SECTION_TITLE_GLOBAL_HEADLINES, "index": 2})
        self.assertEqual(label, f"「{pipeline.SECTION_TITLE_GLOBAL_HEADLINES}」第02条")


class MarketReviewMergeTests(unittest.TestCase):
    """2026-09-30 栏目合并：「行情速览」+「全球大盘全景复盘」→【及时秋刀鱼】AI 行情复盘。

    用户指出两栏内容重复，合并去重（重复的数字只出一份，独有数据一律保留）：
      · 全景「全球指数概览（Yahoo 报价）」= 报价栏「全球与美股」+「港股双指数」同一次
        Yahoo 抓取的同一份快照（道指 / 标普 / 纳指 / 恒指 / 恒科）→ 整块删除；
      · 全景「指数表现」（东财八大宽基）与报价栏「A股四指数」四个指数重复 → 并成一张
        「A股指数」表：同名指数只出一行，成交额与东财独有宽基（北证50 / 沪深300 /
        上证50 / 中证500）全部保留；
      · guizang「成交额」子块的沪 / 深 / 京市成交额就是上证指数 / 深证成指 / 北证50 的
        同一批 f6 数字 → 指数表已带成交额列时不再重列（合计、环比、上一交易日保留）。
    抓取逻辑、数据源名称（实时行情 / A股大盘全景）、审计口径与推送门禁一律不变。
    """

    QUOTES = {
        "道琼斯指数": {"price": 44000.0, "change_pct": 0.60, "as_of": "2026-09-29"},
        "标普500": {"price": 6123.45, "change_pct": 1.25, "as_of": "2026-09-29"},
        "上证指数": {"price": 3813.50, "change_pct": 0.40, "as_of": "2026-09-29"},
        "恒生指数": {"price": 25000.0, "change_pct": 0.80, "as_of": "2026-09-29"},
    }

    def _market(self, quotes=None, status="success"):
        return pipeline._source_result(
            "Yahoo Finance Chart", status, is_today=(status == "success"),
            content_date="2026-09-29" if status == "success" else None,
            quotes=self.QUOTES if quotes is None else quotes,
            **({} if status == "success" else {"error": "offline"}))

    def _pan(self, indices=None, content_date="2026-09-29", with_amount=True, status="success"):
        if indices is None:
            indices = [
                {"code": "000001", "name": "上证指数", "price": 3820.00, "chg_pct": 0.58,
                 "amount": 5.1e11 if with_amount else None},
                {"code": "399001", "name": "深证成指", "price": 12800.00, "chg_pct": -0.30,
                 "amount": 6.2e11 if with_amount else None},
                {"code": "899050", "name": "北证50", "price": 1024.00, "chg_pct": 1.10,
                 "amount": 8.0e9 if with_amount else None},
            ]
        return pipeline._source_result(
            "东方财富·A股全景", status, is_today=(status == "success"), content_date=content_date,
            indices=indices,
            breadth={"up": 3000, "down": 2000, "flat": 100, "ratio": 1.50, "mood": "涨跌互现",
                     "partial": False, "markets": {"沪": {"up": 1500, "down": 900, "flat": 50}}},
            turnover={"total": 1.138e12, "sh_sz": 1.13e12, "prev_total": 1.087e12, "chg_pct": 4.69,
                      "by_market": {"沪": 5.1e11, "深": 6.2e11, "京": 8.0e9}, "partial": False},
            north={"available": True, "amount_yi": 1350.25, "date": "2026-09-29",
                   "south_available": False, "south_amount_yi": None, "south_date": None,
                   "policy_note": pipeline.PANORAMA_NORTH_POLICY_NOTE, "error": None},
            sectors={"leading": [{"code": "BK100", "name": "领涨板块甲", "chg_pct": 3.50,
                                  "main_inflow": 1.5e9, "lead_stock": "领涨牛股",
                                  "lead_stock_pct": 9.9}],
                     "lagging": []},
            quote_time="2026-09-29 15:00:00",
            **({} if status == "success" else {"error": "offline"}))

    def _data(self, market=None, pan=None, rich=True):
        data = NewLayoutRenderingTests()._rich_data() if rich else {}
        data["实时行情"] = self._market() if market is None else market
        data["A股大盘全景"] = self._pan() if pan is None else pan
        return data

    def _section(self, data, kit):
        for s in pipeline._collect_report_parts(data, kit)["sections"]:
            if s[0] == "MARKET REVIEW":
                return s
        return None

    # ------------------------------------------------------------------
    # 栏目本身：一个位置、一个新名字、旧名不回潮
    # ------------------------------------------------------------------
    def test_one_section_replaces_two_in_order_and_titles(self):
        order = pipeline.REPORT_SECTION_ORDER
        self.assertIn("MARKET REVIEW", order)
        self.assertNotIn("MARKET SNAPSHOT", order)
        self.assertNotIn("GLOBAL PANORAMA", order)
        self.assertEqual(pipeline.SECTION_TITLE_MARKET_REVIEW, "【及时秋刀鱼】AI 行情复盘")
        # 2026-10-14 重排：行情复盘位于 ①发生了什么 首位，政策因子随后，周度预测位于 ③
        self.assertLess(order.index("MARKET REVIEW"), order.index("POLICY SHOCK"))
        self.assertLess(order.index("POLICY SHOCK"), order.index("WEEKLY FORECAST"))

        for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
            kicks = [s[0] for s in pipeline._collect_report_parts(self._data(), kit)["sections"]]
            self.assertEqual(kicks.count("MARKET REVIEW"), 1)
            self.assertNotIn("MARKET SNAPSHOT", kicks)
            self.assertNotIn("GLOBAL PANORAMA", kicks)
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(self._data(), "2026年9月29日 · 周二", "20260929",
                                            theme=theme)
            # 栏目标题仅在正文栏目头出现一次。
            head = (f"{pipeline.SECTION_TITLE_MARKET_REVIEW}</h2>" if theme == "guizang"
                    else "// MARKET REVIEW")
            self.assertEqual(html.count(head), 1, theme)
            self.assertNotIn("行情速览", html, theme)
            self.assertNotIn("全球大盘全景复盘", html, theme)

    def test_section_absent_only_when_both_sources_fail(self):
        gone = self._data(market=self._market(status="unavailable"),
                          pan=self._pan(status="unavailable"), rich=False)
        for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
            self.assertIsNone(self._section(gone, kit))
        # 任意一路成功即渲染（合并前也是「有哪路出哪路」，不因合并丢内容）
        for data in (self._data(market=self._market(status="unavailable"), rich=False),
                     self._data(pan=self._pan(status="unavailable"), rich=False)):
            for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
                self.assertIsNotNone(self._section(data, kit))

    # ------------------------------------------------------------------
    # A股指数合并规则：同名指数只出一行，日期新者胜
    # ------------------------------------------------------------------
    def test_ashare_rows_merge_by_fresher_date_and_keep_unique_data(self):
        rows = {r["label"]: r for r in pipeline._market_review_ashare_rows(
            self._market(), self._pan(content_date="2026-09-30"))}
        # 东财行情日更新 → 用东财价并标「（东财）」，成交额一并带上
        self.assertIn("3,820.00", rows["上证指数（东财）"]["price_str"])
        self.assertEqual(rows["上证指数（东财）"]["amount"], 5.1e11)
        self.assertEqual(rows["上证指数（东财）"]["via"], "eastmoney")
        # 东财独有的宽基补在后面（Yahoo 侧没有对应品种），不因为合并而丢失
        self.assertIn("北证50", rows)
        self.assertEqual(rows["北证50"]["amount"], 8.0e9)
        # 同名指数只出一行
        self.assertEqual(len([k for k in rows if k.startswith("上证指数")]), 1)

        # 东财不比 Yahoo 新 → 保留 Yahoo 值（滞后标注照旧），成交额仍来自东财
        rows = {r["label"]: r for r in pipeline._market_review_ashare_rows(
            self._market(), self._pan(content_date="2026-09-29"))}
        self.assertIn("3,813.50", rows["上证指数"]["price_str"])
        self.assertEqual(rows["上证指数"]["amount"], 5.1e11)

        # Yahoo 缺某个指数 → 用东财同一次抓取的值补上，不出空行
        market = self._market(quotes={"标普500": self.QUOTES["标普500"]})
        rows = {r["label"]: r for r in pipeline._market_review_ashare_rows(market, self._pan())}
        self.assertIn("上证指数（东财）", rows)
        self.assertNotIn("道琼斯指数", rows)

        # 两路都没有的品种不出「数据暂缺」行；两路都空 → 整块缺席
        self.assertEqual(pipeline._market_review_ashare_rows(self._market(quotes={}), {}), [])

    def test_ashare_caption_never_claims_a_date_it_cannot_support(self):
        # 报价侧有日期 → 用报价侧「截至」（含滞后口径）
        self.assertIn("截至", pipeline._market_review_ashare_caption(self._market(), self._pan()))
        # 整块都是东财口径 → 标东财行情日
        self.assertEqual(
            pipeline._market_review_ashare_caption(self._market(quotes={}), self._pan()),
            "A股指数 · 截至 09-29（东财）")
        # 两路口径混在一起而报价侧没有日期 → 标题不写日期（各行自己标「（东财）」）
        no_date = self._market(quotes={"上证指数": {"price": 3813.50, "change_pct": 0.40}})
        self.assertEqual(pipeline._market_review_ashare_caption(no_date, self._pan()), "A股指数")

    # ------------------------------------------------------------------
    # 去重：重复数字全文只出现一次，独有数据一个不少
    # ------------------------------------------------------------------
    def test_duplicate_numbers_gone_and_unique_data_kept_in_both_themes(self):
        for theme, kit in (("guizang", pipeline.GUIZANG_KIT), ("pixel", pipeline.PIXEL_KIT)):
            with self.subTest(theme=theme):
                sec = self._section(self._data(), kit)
                html = pipeline.generate_report(self._data(), "2026年9月29日 · 周二", "20260929",
                                                theme=theme)
                body = sec[2]
                self.assertNotIn("全球指数概览", body)     # 与报价块完全重复 → 删除
                self.assertNotIn("指数表现", body)         # 并入「A股指数」
                self.assertEqual(body.count("全球与美股"), 1)
                self.assertEqual(body.count("A股指数"), 1)
                self.assertEqual(body.count("港股双指数"), 1)
                # 每个指数的价格全文只出现一次（合并前报价块 + 概览块各一次）
                for price in ("44,000", "6,123", "25,000.00"):
                    self.assertEqual(html.count(price), 1, f"{theme} {price} 重复")
                # 沪 / 深市成交额 = 上证指数 / 深证成指 成交额，指数表已带 → 不再重列
                self.assertNotIn("沪市成交额", body)
                self.assertNotIn("深市成交额", body)
                self.assertEqual(body.count("5100.00亿"), 1, theme)
                # 独有数据一个不少：合计与环比、宽度、南北向、板块热力
                for kept in ("沪深京成交额合计", "上一交易日合计（沪深京）", "涨跌家数",
                             "1.50", "涨跌互现", "北向成交总额（2026-09-29）", "1,350.25 亿元",
                             "领涨板块甲", "领涨牛股"):
                    self.assertIn(kept, body, f"{theme} 缺少 {kept}")

    def test_turnover_by_market_kept_when_index_amounts_missing(self):
        """指数表拿不到成交额时，分市场成交额照旧展示（去重不能变成丢数据）。"""
        pan = self._pan(with_amount=False)
        body = pipeline.gz_market_review(self._market(), pan)
        self.assertIn("沪市成交额", body)
        self.assertNotIn("成交额", body.split("涨跌家数")[0].split("A股指数")[-1])  # 指数表无成交额列
        # 直接调用全景块（未合并）时行为不变：指数表 + 分市场成交额都在
        solo = pipeline.gz_panorama_block(pan)
        self.assertIn("指数表现", solo)
        self.assertIn("沪市成交额", solo)

    def test_market_only_renders_quotes_without_panorama_blocks(self):
        sec = self._section(self._data(pan=self._pan(status="unavailable"), rich=False),
                            pipeline.GUIZANG_KIT)
        self.assertIsNotNone(sec)
        self.assertIn("全球与美股", sec[2])
        for gone in ("涨跌家数", "板块热力", "南北向资金"):
            self.assertNotIn(gone, sec[2])
        self.assertNotIn("成交额", sec[2])          # 没有东财成交额 → 不出这一列
        self.assertIn("暂缺：A股全景", sec[4])

    # ------------------------------------------------------------------
    # 徽标 / 副标题 / 研判：两路数据各自表态，不混算
    # ------------------------------------------------------------------
    def test_badge_and_caption_report_each_source_separately(self):
        for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
            with pipeline.notes_mode():          # 来源名属于说明文字：--notes 下副标题列全
                badge, caption = pipeline._market_review_meta(kit, self._market(), self._pan())
                self.assertIn("报价", badge)
                self.assertIn("A股全景", badge)
                self.assertEqual(caption, "Yahoo Finance Chart ＋ 东方财富·A股全景")

                badge, caption = pipeline._market_review_meta(kit, None, self._pan())
                self.assertNotIn("报价", badge)
                self.assertEqual(caption, "东方财富·A股全景 · 暂缺：报价")
            # 入门版（默认）：徽标照旧，副标题只留「暂缺」提示
            badge, caption = pipeline._market_review_meta(kit, self._market(), self._pan())
            self.assertIn("报价", badge)
            self.assertEqual(caption, "")
            badge, caption = pipeline._market_review_meta(kit, None, self._pan())
            self.assertEqual(caption, "暂缺：报价")

            badge, caption = pipeline._market_review_meta(kit, self._market(), None)
            self.assertEqual(caption, "暂缺：A股全景")
            with pipeline.notes_mode():
                badge, caption = pipeline._market_review_meta(kit, self._market(), None)
            self.assertEqual(caption, "Yahoo Finance Chart · 暂缺：A股全景")

            badge, caption = pipeline._market_review_meta(kit, None, None)
            self.assertEqual(badge, "")
            self.assertEqual(caption, "暂缺：报价、A股全景")

    def test_two_judge_rows_keep_their_own_methodology(self):
        """合并栏保留两行研判（报价面 / A股全景面），不把两套口径混算成一个概率。"""
        for theme, kit in (("guizang", pipeline.GUIZANG_KIT), ("pixel", pipeline.PIXEL_KIT)):
            with self.subTest(theme=theme):
                body = self._section(self._data(), kit)[2]
                self.assertEqual(body.count("AI 研判（报价面）"), 1)
                self.assertEqual(body.count("AI 研判（A股全景面）"), 1)
                self.assertLess(body.find("AI 研判（报价面）"), body.find("AI 研判（A股全景面）"))
                self.assertIn("项报价", body)        # 报价面证据
                self.assertIn("宽度", body)          # 全景面证据
        # notes 的键名不变（仍是两路证据各自的键），只是渲染进同一栏
        notes = pipeline.build_section_ai_notes(self._data())
        self.assertIn("MARKET SNAPSHOT", notes)
        self.assertIn("GLOBAL PANORAMA", notes)
        self.assertEqual(pipeline._section_note_keys("MARKET REVIEW"),
                         (("报价面", "MARKET SNAPSHOT"), ("A股全景面", "GLOBAL PANORAMA")))
        self.assertEqual(pipeline._section_note_keys("POLICY SHOCK"), (("", "POLICY SHOCK"),))

    def test_audit_sources_unchanged_by_merge(self):
        """合并的是栏目，不是数据线：两路来源仍各自留痕，审计源数与门禁不变。"""
        with pipeline.notes_mode():
            html = pipeline.generate_report(self._data(), "2026年9月29日 · 周二", "20260929")
        # 栏目副标题同时给出两路来源名（合并前分别在两个栏目里各写一次）
        self.assertIn("Yahoo Finance Chart ＋ 东方财富·A股全景", html)
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["total_sources"], 8)
        ok, _ = pipeline.check_push_eligibility(self._data())
        self.assertTrue(ok)


class DossierThemeTests(unittest.TestCase):
    """可切换 Dossier 排版（德国文件 / 档案风 + 包豪斯几何）

    设计契约：牛皮纸文件夹标签（AKTE 编号）、2px 黑粗线、等宽卷宗号、红色
    RESEARCH 印章、ENDE DER AKTE 档案尾注；包豪斯图标只用 圆/三角/方/菱 等
    几何字形 × 红蓝黄三原色；内容块与 guizang 同源，纯内联样式、无 <style> /
    class / 远程资源；分条推送与推送门禁逻辑不变。
    """

    def _html(self, theme="dossier"):
        return pipeline.generate_report(
            ReportFreshnessTests()._sample_data(),
            "2026年8月1日 · 周六", "20260801", theme=theme)

    # ---------------- 主题注册与解析 ----------------
    def test_dossier_is_registered_and_resolvable(self):
        """dossier 保持注册可切换；默认主题为白底圆角卡片 + 荧光绿强调 lime。"""
        self.assertIn("dossier", pipeline.PUSH_THEMES)
        self.assertEqual(pipeline.DEFAULT_PUSH_THEME, "lime")
        self.assertEqual(pipeline._resolve_push_theme("dossier"), "dossier")
        self.assertEqual(pipeline._resolve_push_theme("DOSSIER"), "dossier")
        self.assertEqual(pipeline._resolve_push_theme("nope"), pipeline.DEFAULT_PUSH_THEME)

    def test_dossier_meta_readback_roundtrip(self):
        html = self._html()
        self.assertIn('name="octopus-theme" content="dossier"', html)
        self.assertEqual(pipeline._report_theme(html), "dossier")

    def test_full_mode_keeps_dossier_style_and_omits_short_card(self):
        with patch.object(pipeline, "LITE_ENABLED", False), \
             patch.object(pipeline._quant.render, "LITE", False):
            html = self._html()
        self.assertIn('name="octopus-theme" content="dossier"', html)
        self.assertIn("OCTOPUS · Fresh-keeping", html)
        self.assertIn("ENDE DER AKTE", html)
        self.assertNotIn(pipeline.SECTION_TITLE_SHORT_CARD, html)

    # ---------------- 德国文件 / 卷宗 chrome ----------------
    def test_german_file_chrome(self):
        html = self._html()
        # 卷宗封面：刊名条 + 档号 + 档案元信息表
        self.assertIn("OCTOPUS · Fresh-keeping", html)
        self.assertIn("AKT-20260801", html)
        self.assertIn("DATE · 日期", html)
        self.assertIn("QUELLEN · 当天源", html)
        self.assertIn("SIGNATUR · 档号", html)
        # 栏目文件夹标签（AKTE 编号，等宽 kicker）
        self.assertIn("AKTE 00", html)
        self.assertIn("AKTE 01", html)
        self.assertIn("border-top:2px solid", html)   # 卷宗黑粗线
        # 档案尾注
        self.assertIn("ENDE DER AKTE", html)
        # 牛皮纸文件夹标签底色
        self.assertIn(pipeline.D_TAB, html)

    def test_every_section_has_numbered_tab_and_h2(self):
        html = self._html()
        tabs = re.findall(r"AKTE (\d\d) · ", html)
        self.assertGreaterEqual(len(tabs), 3)
        self.assertEqual(tabs[0], "00")
        self.assertEqual(tabs, sorted(set(tabs)))          # 编号连续不重
        # 分条横幅靠 <h2> 取栏目名：每个标签后都跟一个 h2
        self.assertGreaterEqual(html.count("<h2"), len(tabs))

    def test_dossier_stamp_present_with_notes_absent_in_plain(self):
        with pipeline.notes_mode():
            html_notes = self._html()
        self.assertIn("RESEARCH · 非投资建议", html_notes)
        self.assertIn("内部资料 · 非投资建议", html_notes)   # 封面大章
        html_plain = self._html()
        self.assertNotIn("RESEARCH · 非投资建议", html_plain)
        self.assertNotIn("内部资料 · 非投资建议", html_plain)

    # ---------------- 包豪斯图标 ----------------
    def test_bauhaus_icons_are_geometric_and_duotone(self):
        """图标只用几何字形 × 落字深绿 / 落字深红 / 黑；原色只用于填充与描边。"""
        allowed = {pipeline.D_GREEN_INK.upper(), pipeline.D_RED_INK.upper(),
                   pipeline.D_BLACK.upper(), pipeline.D_INK_STRONG.upper()}
        for kicker, spec in pipeline.DOSSIER_ICONS.items():
            g1, c1, g2, c2 = spec
            self.assertNotIn("svg", g1 + g2)
            for color in (c1, c2):
                self.assertIn(color.upper(), allowed,
                              f"{kicker} 图标颜色 {color} 不在荧光绿/鲜红/黑之内")
        html = self._html()
        self.assertNotIn("<svg", html)
        self.assertNotIn("<img", html)
        self.assertIn("font-size:13px", html)   # 主字形

    def test_dossier_section_icon_fallback_for_unknown_kicker(self):
        icon = pipeline.dossier_icon("SOME UNKNOWN KICKER")
        self.assertIn("●", icon)
        self.assertIn(pipeline.D_GREEN_INK, icon)

    # ---------------- 色盘：浅灰底 + 黑标题 + 深灰正文 + 荧光绿/鲜红 ----------------
    def test_dossier_palette_and_no_old_colors_leak(self):
        """设计契约（2026-10-04 换色）：浅灰底、黑标题、深灰正文，强调色只有荧光绿与鲜红。"""
        html = self._html()
        self.assertIn(f"bgcolor=\"{pipeline.D_PAPER}\"", html)
        self.assertIn(pipeline.D_PAPER, html)
        self.assertNotIn("#002FA7", html)      # 克莱因蓝不得渗入 dossier
        self.assertNotIn("#F3F6FF", html)      # 归藏淡蓝底不得渗入
        self.assertNotIn("#F2F2F2", html)      # 归藏斑马灰不得渗入
        # 旧配色（浅黄牛皮纸底 / 暖墨 / 红蓝黄三原色）必须全部退场
        for old in ("#F7F4EC", "#EDE4CE", "#EFEADF", "#201D18", "#111009", "#3A382F",
                    "#141310", "#B9AF99", "#C9BC9C", "#DAD2BD", "#E9EDF6",
                    "#C93A2B", "#1E4E9C", "#163C7C", "#C8930E"):
            self.assertNotIn(old, html, f"旧配色 {old} 不应再出现在 dossier 日报里")

    def test_dossier_palette_values_and_contrast_floor(self):
        """色值本身也守契约：黑标题、深灰正文、荧光绿/鲜红两支突出色，落字版过 AA 4.5:1。"""
        self.assertEqual(pipeline.D_INK, "#333333")          # 正文深灰
        self.assertEqual(pipeline.D_INK_STRONG, "#000000")   # 标题纯黑
        self.assertEqual(pipeline.D_BLACK, "#000000")
        self.assertEqual(pipeline.D_GREEN, "#39FF14")        # 荧光绿填充
        self.assertEqual(pipeline.D_RED, "#FF1F1F")          # 鲜红填充
        self.assertEqual(pipeline.D_GREEN_INK, "#0A6724")    # 落字绿
        self.assertEqual(pipeline.D_RED_INK, "#C01010")      # 落字红
        self.assertEqual(pipeline.D_TAB, pipeline.D_GREEN)   # 高亮标签 = 荧光绿块

        def _lum(hex_color):
            h = hex_color.lstrip("#")
            channels = []
            for i in (0, 2, 4):
                c = int(h[i:i + 2], 16) / 255
                channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
            r, g, b = channels
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        def _contrast(a, b):
            la, lb = _lum(a), _lum(b)
            hi, lo = max(la, lb), min(la, lb)
            return (hi + 0.05) / (lo + 0.05)

        paper = pipeline.D_PAPER
        # 浅灰画布：比旧牛皮纸更冷更灰（R=G=B），也不是归藏那种纯白
        self.assertEqual(paper, "#F1F1F1")
        self.assertTrue(paper[1:3] == paper[3:5] == paper[5:7], "画布必须是中性浅灰")
        self.assertLess(paper, "#FFFFFF")
        # 灰字强制门禁不会被浅灰画布触发（> #E8 的中性灰是底不是字）
        self.assertFalse(pipeline._is_light_or_mid_gray_hex(paper))
        # 正文 / 次要文字 / 涨跌字色要同时适配画布、斑马灰与荧光绿强调底。
        for color in (pipeline.D_INK, pipeline.D_GRAY, pipeline.D_GREEN_INK,
                      pipeline.D_RED_INK, pipeline.D_INK_STRONG):
            for background in (paper, pipeline.D_ZEBRA, pipeline.D_GREEN):
                self.assertGreaterEqual(round(_contrast(color, background), 2), 4.5,
                                        f"{color} 在 {background} 上对比度不足 4.5:1")
        # 荧光绿 / 鲜红是填充色：块内黑字必须够亮够清楚。
        self.assertGreaterEqual(_contrast(pipeline.D_INK_STRONG, pipeline.D_GREEN), 12)
        # 原荧光色不作为浅底文字 / 图标，避免对比不足。
        self.assertLess(_contrast(pipeline.D_GREEN, paper), 3)
        self.assertLess(_contrast(pipeline.D_RED, paper), 4.5)
        # 涨 = 绿、跌 = 红（与像素主题、量化表一致），用落字版
        self.assertEqual(pipeline._DOSSIER_GZ_SWAP["GZ_UP"], pipeline.D_GREEN_INK)
        self.assertEqual(pipeline._DOSSIER_GZ_SWAP["GZ_DOWN"], pipeline.D_RED_INK)
        self.assertEqual(pipeline._DOSSIER_GZ_SWAP["GZ_KLEIN_WASH"], pipeline.D_GREEN)
        self.assertEqual(pipeline._DOSSIER_GZ_SWAP["GZ_KLEIN"], pipeline.D_GREEN_INK)
        self.assertEqual(pipeline._DOSSIER_GZ_SWAP["GZ_KLEIN_DEEP"], pipeline.D_GREEN_DEEP)

    def test_rendered_text_contrast_meets_aa_on_actual_backgrounds(self):
        """生成后的 Dossier 页面也要过 AA，覆盖色盘常量测试漏掉的嵌套底色组合。"""
        from html.parser import HTMLParser

        class _ContrastAudit(HTMLParser):
            _COLOR = re.compile(r"(?<![-\w])color\s*:\s*(#[0-9a-f]{3,6})\b", re.I)
            _BACKGROUND = re.compile(
                r"(?<![-\w])background(?:-color)?\s*:\s*(#[0-9a-f]{3,6})\b", re.I)
            _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                     "link", "meta", "param", "source", "track", "wbr"}

            def __init__(self):
                super().__init__()
                self.stack = []
                self.samples = []
                self.unstyled = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                style = attrs.get("style") or ""
                color_match = self._COLOR.search(style)
                bg_match = self._BACKGROUND.search(style)
                color = color_match.group(1).upper() if color_match else None
                background = (bg_match.group(1).upper() if bg_match else
                              str(attrs.get("bgcolor") or "").upper() or None)
                if tag.lower() not in self._VOID:
                    self.stack.append((tag.lower(), color, background))

            def handle_endtag(self, tag):
                tag = tag.lower()
                for index in range(len(self.stack) - 1, -1, -1):
                    if self.stack[index][0] == tag:
                        self.stack = self.stack[:index]
                        break

            def handle_data(self, data):
                text = data.strip()
                if not text or (self.stack and self.stack[-1][0] in ("title", "style", "script")):
                    return
                color = background = None
                for tag, fg, bg in reversed(self.stack):
                    if tag == "body":
                        break  # PushPlus v-html 会剥掉 body，不能依赖其样式
                    if color is None and fg:
                        color = fg
                    if background is None and bg:
                        background = bg
                if color is None or background is None:
                    self.unstyled.append((text[:40], color, background))
                else:
                    self.samples.append((text[:40], color, background))

        html = self._html()
        audit = _ContrastAudit()
        audit.feed(html)
        self.assertGreater(len(audit.samples), 50)
        self.assertEqual(audit.unstyled, [], f"Dossier 有无色文本或未识别底色：{audit.unstyled[:5]}")

        def _luminance(color):
            h = color.lstrip("#")
            channels = []
            for index in (0, 2, 4):
                channel = int(h[index:index + 2], 16) / 255
                channels.append(channel / 12.92 if channel <= 0.04045
                                else ((channel + 0.055) / 1.055) ** 2.4)
            r, g, b = channels
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        for text, color, background in audit.samples:
            light, dark = sorted((_luminance(color), _luminance(background)), reverse=True)
            ratio = (light + 0.05) / (dark + 0.05)
            self.assertGreaterEqual(round(ratio, 2), 4.5,
                                    f"文字「{text}」色 {color} 在 {background} 上仅 {ratio:.2f}:1")

    def test_dossier_has_no_klein_leak_in_quant_tables(self):
        """行情复盘里的 MACD 量化表是按 GUIZANG_KIT 渲染的（历史实现）：
        档案色板必须连 kit 色槽一起换，否则克莱因蓝漏进浅灰页，换色后尤其扎眼。"""
        import test_plain_mode as tpm
        data = tpm._rich_data()                     # 含 MACD 量化策略 + 行情复盘
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802",
                                        theme="dossier")
        self.assertIn("MACD 量化策略", html)
        self.assertNotIn("#002FA7", html)
        # 退出换色后 kit 色槽还原：guizang 依旧克莱因蓝，不带 dossier 色
        self.assertEqual(pipeline.GUIZANG_KIT.ok_color, pipeline.GZ_UP)
        guizang = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802",
                                           theme="guizang")
        self.assertIn("#002FA7", guizang)
        self.assertNotIn(pipeline.D_GREEN, guizang)

    def test_palette_globals_restored_after_render(self):
        before = {k: getattr(pipeline, k) for k in
                  ("GZ_KLEIN", "GZ_INK", "GZ_PAPER", "GZ_FONT", "GZ_DARK_GRAY",
                   "GZ_ZEBRA", "GZ_UP")}
        self._html()
        after = {k: getattr(pipeline, k) for k in before}
        self.assertEqual(before, after)
        # 还原后 guizang 依旧原盘
        self.assertIn("#002FA7", self._html("guizang"))

    # ---------------- 微信兼容与分条 ----------------
    def test_inline_only_and_no_remote_assets(self):
        html = self._html()
        self.assertNotIn("<style", html)
        self.assertNotIn('class="', html)
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertIn("font-family:'Courier New'", html)   # 等宽卷宗号

    def test_multipart_split_works_on_dossier_report(self):
        data = SectionReadingOrderTests()._full_data()
        data["A股大盘全景"] = MarketPanoramaTests()._panorama_payload()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802",
                                        theme="dossier")
        # dossier 卷宗封面 + 尾注比 guizang 重，6000 上限下无拆分空间，取 12000 强制多分条
        limit = 12000
        parts = pipeline._split_html_for_push(html, limit)
        self.assertIsNotNone(parts)
        self.assertGreater(len(parts), 1)
        for index, part in enumerate(parts, 1):
            self.assertLessEqual(len(part), limit, f"第 {index} 条超过单条上限")
        for title in re.findall(r"<h2[^>]*>([^<]+)</h2>", html):
            self.assertGreaterEqual(
                sum(1 for part in parts if f">{title}</h2>" in part), 1,
                f"栏目「{title}」在分条后丢失")


class ForumThemeTests(unittest.TestCase):
    """可切换的暗色社区主题 forum：卡片暗底 + 彩色图标 + 暗色字色保护。

    设计契约：画布 #1C1C1E / 卡片 #2C2C2E / 1px rgba(255,255,255,0.08) 描边 + 圆角；
    正文 #F2F2F7、标题 #FFFFFF、次要 #A1A1AA、点缀 #D8B4FE（紫，2026-10-06 起，
    原闪电黄 #FFD60A）；彩色微型图标（紫闪电 / 红行情 / 红火焰 / 紫机器人 /
    橙文档 / 青日历 / 青趋势）；涨跌走 A 股口径：涨 ▲ 红 #FF6B6B、跌 ▼ 绿
    #32D74B；所有可见文字在 #1C1C1E、#2C2C2E 与结论块底 #241A2E 上都 ≥ WCAG AA
    4.5:1；纯内联样式，无 <style> / class / 远程资源；分条推送与推送门禁逻辑不变。
    历史浅色主题（guizang / dossier / pixel）一律不得渗进暗色页面。
    """

    def _data(self):
        return NewLayoutRenderingTests()._rich_data()

    def _html(self, theme="forum"):
        return pipeline.generate_report(self._data(), "2026年8月2日 · 周日", "20260802",
                                        theme=theme)

    @staticmethod
    def _bodyless_unstyled(html):
        """剥离 <body> 后仍没有任何祖先声明 color 的文本节点（PushPlus v-html 场景）。"""
        from html.parser import HTMLParser

        class _Audit(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack, self.unstyled, self.total = [], [], 0

            def handle_starttag(self, tag, attrs):
                style = dict(attrs).get("style") or ""
                m = re.search(r"(?<![-\w])color\s*:\s*([^;\"'\s]+)", style, re.I)
                self.stack.append((tag.lower(), m.group(1) if m else None))

            def handle_endtag(self, tag):
                t = tag.lower()
                for i in range(len(self.stack) - 1, -1, -1):
                    if self.stack[i][0] == t:
                        self.stack.pop(i)
                        break

            def handle_data(self, data):
                if not data.strip():
                    return
                if self.stack and self.stack[-1][0] in ("title", "style", "script"):
                    return
                self.total += 1
                for t, col in reversed(self.stack):
                    if t == "body":
                        break
                    if col:
                        return
                self.unstyled.append(data.strip()[:30])

        audit = _Audit()
        audit.feed(html)
        return audit

    # ---------------- 主题注册与元信息 ----------------
    def test_forum_is_registered_and_selectable(self):
        self.assertIn("forum", pipeline.PUSH_THEMES)
        self.assertEqual(pipeline.DEFAULT_PUSH_THEME, "lime")
        self.assertEqual(pipeline._resolve_push_theme(None), "lime")
        self.assertEqual(pipeline._resolve_push_theme("FORUM"), "forum")
        self.assertEqual(pipeline._resolve_push_theme(" forum "), "forum")

    def test_forum_meta_readback_and_split_anchors(self):
        html = self._html()
        self.assertIn('name="octopus-theme" content="forum"', html)
        self.assertIn('name="color-scheme" content="dark only"', html)
        self.assertEqual(pipeline._report_theme(html), "forum")
        self.assertIn(pipeline.PART_BREAK_MARK, html)
        self.assertIn(pipeline.DOC_FOOT_MARK, html)
        self.assertGreaterEqual(html.count("<h2"), 3)

    # ---------------- 暗色色板与卡片 chrome ----------------
    def test_dark_palette_values_and_card_chrome(self):
        self.assertEqual(pipeline.F_BG, "#1C1C1E")          # 画布：深灰而非纯黑
        self.assertEqual(pipeline.F_CARD, "#2C2C2E")        # 卡片容器
        self.assertEqual(pipeline.F_INK, "#F2F2F7")         # 正文近白
        self.assertEqual(pipeline.F_INK_STRONG, "#FFFFFF")  # 标题纯白
        self.assertEqual(pipeline.F_MUTED, "#A1A1AA")       # 次要中灰
        self.assertEqual(pipeline.F_ACCENT, "#D8B4FE")      # 点缀：落字紫
        self.assertEqual(pipeline.F_ACCENT_DEEP, "#C77DFF")  # 紫加深（按下 / 更重）
        self.assertEqual(pipeline.F_WASH, "#241A2E")        # 结论 / AI 块：深紫底
        self.assertEqual(pipeline.F_ACCENT, pipeline.F_PURPLE)  # 点缀紫＝AI 紫，同一支
        html = self._html()
        self.assertIn(f'bgcolor="{pipeline.F_BG}"', html)
        self.assertIn(f"background:{pipeline.F_CARD}", html)
        self.assertIn("border:1px solid rgba(255,255,255,0.08)", html)
        self.assertIn("border-radius:", html)
        self.assertIn("linear-gradient(180deg", html)       # 顶亮渐变按钮 / 胶囊
        for banned in ("<style", 'class="', "<img", "<svg", "<script", "koboyo.com"):
            self.assertNotIn(banned, html, banned)
        # 彩色微型图标（emoji / 几何字形）确实进了栏目头
        self.assertTrue(any(glyph in html for glyph in ("⚡", "📈", "📅", "🤖")))

    def test_every_text_color_is_legible_on_dark(self):
        """暗色硬门禁：文字色必须是主题色板内的可读色，且在画布 / 卡片 / 结论块底上都 ≥ 4.5:1。"""
        html = self._html()
        colors = set(re.findall(r"(?<![-\w])color\s*:\s*(#[0-9A-Fa-f]{3,6})\b", html))
        self.assertTrue(colors)
        allowed = {c.upper() for c in pipeline.FORUM_TEXT_ALLOWED}
        on_fill = {pipeline.F_ON_FILL.upper(), "#000000"}
        for color in sorted(colors):
            self.assertIn(color.upper(), allowed, f"文字色 {color} 不在暗色主题色板内")
            if color.upper() in on_fill:
                continue
            for bg in (pipeline.F_BG, pipeline.F_CARD, pipeline.F_WASH):
                ratio = pipeline._contrast_ratio(color, bg)
                self.assertGreaterEqual(
                    round(ratio, 2), 4.5,
                    f"文字色 {color} 在 {bg} 上对比度仅 {ratio:.2f}:1（需 ≥ 4.5:1）")

    def test_accent_is_purple_and_no_yellow_left(self):
        """2026-10-06 换色：点缀文字色由闪电黄改落字紫，页面里不留任何黄字 / 黄砖。"""
        html = self._html()
        self.assertIn(f"color:{pipeline.F_ACCENT}", html)          # 点缀紫确实落字
        for legacy_yellow in ("#FFD60A", "#FFC400", "#2E2712", "#5C4B10", "#2E2718"):
            self.assertNotIn(legacy_yellow, html, f"旧闪电黄残留：{legacy_yellow}")
        # 色板内允许的每一支字色都在结论块底上过 AA（含新的深档紫 #C77DFF）
        for color in dict.fromkeys(pipeline.FORUM_TEXT_ALLOWED):
            if color.upper() == pipeline.F_ON_FILL.upper():
                continue
            self.assertGreaterEqual(
                round(pipeline._contrast_ratio(color, pipeline.F_WASH), 2), 4.5,
                f"{color} 在结论块底 {pipeline.F_WASH} 上不足 4.5:1")
        # 黄色锚点已撤：历史黄字按色相落到橙，不会变成紫
        self.assertNotIn(0.14, [hue for _, hue in pipeline.FORUM_HUE_SNAP])
        self.assertEqual(pipeline._dark_text_color_for("#FFE66D"), pipeline.F_ORANGE)

    def test_forum_up_red_down_green(self):
        """涨跌改 A 股口径：涨 ▲ 落字红、跌 ▼ 落字绿，图例 / 刊头 / kit 色槽同口径。"""
        self.assertEqual(pipeline._FORUM_GZ_SWAP["GZ_UP"], pipeline.F_RED)
        self.assertEqual(pipeline._FORUM_GZ_SWAP["GZ_DOWN"], pipeline.F_GREEN)
        self.assertEqual(pipeline._FORUM_GZ_SWAP["GZ_UP_INK"], pipeline.F_RED)
        self.assertEqual(pipeline._FORUM_GZ_SWAP["GZ_DOWN_INK"], pipeline.F_GREEN)
        self.assertEqual(pipeline.FORUM_KIT.ok_color, pipeline.F_RED)
        self.assertEqual(pipeline.FORUM_KIT.bad_color, pipeline.F_GREEN)
        self.assertEqual(pipeline._forum_palette._KIT_COLORS["ok_color"], pipeline.F_RED)
        html = self._html()
        # 尾注图例：▲ 涨＝红、▼ 跌＝绿（符号与颜色双编码）
        self.assertIn(f'color:{pipeline.F_RED};font-size:11px;white-space:nowrap;">▲ 涨', html)
        self.assertIn(f'color:{pipeline.F_GREEN};font-size:11px;white-space:nowrap;">▼ 跌', html)
        # 渲染期确实换了涨跌色，退出后浅色主题的 GZ_* 原样还原
        with pipeline._forum_palette():
            self.assertEqual(pipeline.GZ_UP, pipeline.F_RED)
            self.assertEqual(pipeline.GZ_DOWN, pipeline.F_GREEN)
        self.assertEqual(pipeline.GZ_UP, pipeline.GZ_KLEIN)
        self.assertEqual(pipeline.GUIZANG_KIT.ok_color, pipeline.GZ_UP)
        # 其它主题不受影响：guizang 仍是克莱因蓝涨 / 深灰跌，dossier 仍是绿涨红跌
        guizang = self._html("guizang")
        self.assertIn("#002FA7", guizang)
        dossier = self._html("dossier")
        self.assertIn(pipeline.D_GREEN_INK, dossier)

    def test_no_light_theme_colors_leak_into_forum(self):
        html = self._html()
        # 浅色主题的正文 / 强调色不得作为文字色出现
        for legacy in ("#002FA7", "#00227A", "#333333", "#4A4A4A", "#39FF14",
                       "#FF1F1F", "#D01818", "#0F7A2B", "#F1F1F1", "#222", "#555"):
            self.assertNotIn(f"color:{legacy}", html, f"浅色主题色 {legacy} 漏进暗色页面")
        # dossier 的画布 / 高亮标签、pixel 的街机底也不得出现
        self.assertNotIn(pipeline.D_PAPER, html)
        self.assertNotIn(pipeline.D_TAB, html)
        self.assertNotIn("#050711", html)

    def test_forum_has_no_klein_leak_in_quant_tables(self):
        """量化栏目（按 GUIZANG_KIT 渲染的历史实现）不得把浅色主题的蓝 / 灰漏进暗色卡片。"""
        data = SectionReadingOrderTests()._full_data()
        data["A股大盘全景"] = MarketPanoramaTests()._panorama_payload()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802",
                                        theme="forum")
        self.assertIn("量化", html)
        self.assertNotIn("#002FA7", html)
        self.assertNotIn(pipeline.D_GREEN_INK, html)
        # kit 色槽换过又还原：guizang 依旧浅底克莱因蓝
        self.assertEqual(pipeline.GUIZANG_KIT.ok_color, pipeline.GZ_UP)
        guizang = self._html("guizang")
        self.assertIn("#002FA7", guizang)
        self.assertNotIn(pipeline.F_CARD, guizang)

    def test_forum_palette_globals_restored_after_render(self):
        keys = ("GZ_KLEIN", "GZ_INK", "GZ_PAPER", "GZ_FONT", "GZ_DARK_GRAY",
                "GZ_ZEBRA", "GZ_UP")
        before = {k: getattr(pipeline, k) for k in keys}
        self._html()
        self.assertEqual(before, {k: getattr(pipeline, k) for k in keys})

    # ---------------- 暗色字色保护 ----------------
    def test_enforce_dark_mode_font_rewrites_light_colors_and_fills_missing(self):
        sample = (
            '<div style="color:#777;border-top:1px solid #ddd">灰字</div>'
            '<div style="color:#002FA7">克莱因蓝</div>'
            '<div style="color:#111">近黑</div>'
            '<div style="padding:5px 0;border-top:1px solid #eee">无色块文本</div>'
            '<table style="border-collapse:separate"><tr><td>无色表单元格</td></tr></table>'
        )
        out = pipeline._enforce_dark_mode_font(sample)
        allowed = {c.upper() for c in pipeline.FORUM_TEXT_ALLOWED}
        colors = re.findall(r"(?<![-\w])color\s*:\s*(#[0-9A-Fa-f]{3,6})\b", out)
        self.assertGreaterEqual(len(colors), 5)          # 5 处字色（含补齐的两处）
        for color in colors:
            self.assertIn(color.upper(), allowed, f"{color} 不在暗色色板内")
            if color.upper() != pipeline.F_ON_FILL.upper():
                self.assertGreaterEqual(
                    round(pipeline._contrast_ratio(color, pipeline.F_BG), 2), 4.5)
        self.assertIn("border-top:1px solid #ddd", out)  # 分割线不被误改
        self.assertIn("border-top:1px solid #eee", out)
        # 彩色的克莱因蓝保持色相提亮，而不是简单变灰
        self.assertFalse(pipeline._is_light_or_mid_gray_hex(colors[1]))
        # 无色容器全部补齐了显式前景色（剥离 <body> 后不回退宿主浅灰字）
        self.assertEqual(out.count("无色块"), out.count("无色块"))
        audit = self._bodyless_unstyled(out.replace("<body", "<xbody"))
        self.assertGreaterEqual(audit.total, 4)
        self.assertEqual(audit.unstyled, [])

    def test_forum_html_colors_every_text_node_without_body(self):
        from html.parser import HTMLParser

        class _Audit(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack, self.unstyled, self.total = [], [], 0

            def handle_starttag(self, tag, attrs):
                style = dict(attrs).get("style") or ""
                m = re.search(r"(?<![-\w])color\s*:\s*([^;\"'\s]+)", style, re.I)
                self.stack.append((tag.lower(), m.group(1) if m else None))

            def handle_endtag(self, tag):
                t = tag.lower()
                for i in range(len(self.stack) - 1, -1, -1):
                    if self.stack[i][0] == t:
                        self.stack.pop(i)
                        break

            def handle_data(self, data):
                if not data.strip():
                    return
                if self.stack and self.stack[-1][0] in ("title", "style", "script"):
                    return
                self.total += 1
                for t, col in reversed(self.stack):
                    if t == "body":
                        break
                    if col:
                        return
                self.unstyled.append((data.strip()[:30], "/".join(t for t, _ in self.stack)))

        for theme in ("forum", "dossier", "guizang"):
            audit = _Audit()
            audit.feed(self._html(theme))
            self.assertGreater(audit.total, 50)
            self.assertEqual(audit.unstyled, [],
                             f"{theme}：剥离 <body> 后仍有未声明 color 的文本节点 "
                             f"{audit.unstyled[:5]}")

    # ---------------- 分条推送与推送前保护 ----------------
    def test_forum_push_protection_keeps_dark_palette(self):
        """推送前再次保护必须走暗色版：绝不能套用浅色版灰字强制（会把字改成 #333）。"""
        html = self._html()
        with patch.object(pipeline, "_push_one_message", return_value=True) as single:
            self.assertTrue(pipeline.push_to_wechat("暗色主题测试", html, token="test-token"))
        sent = single.call_args.args[1]
        self.assertIn('name="octopus-theme" content="forum"', sent)
        self.assertNotIn("color:#333", sent.lower())
        self.assertIn(pipeline.F_CARD, sent)

    def test_forum_multipart_split_keeps_theme_and_every_section(self):
        data = SectionReadingOrderTests()._full_data()
        data["A股大盘全景"] = MarketPanoramaTests()._panorama_payload()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802",
                                        theme="forum")
        limit = 12000
        parts = pipeline._split_html_for_push(html, limit)
        self.assertIsNotNone(parts)
        self.assertGreater(len(parts), 1)
        for index, part in enumerate(parts, 1):
            self.assertLessEqual(len(part), limit, f"第 {index} 条超过单条上限")
            self.assertIn('name="octopus-theme" content="forum"', part)
            self.assertIn(pipeline.F_CARD, part)
            self.assertEqual(part.count("<div"), part.count("</div>"))
        for title in re.findall(r"<h2[^>]*>([^<]+)</h2>", html):
            self.assertGreaterEqual(
                sum(1 for part in parts if f">{title}</h2>" in part), 1,
                f"栏目「{title}」在分条后丢失")

    def test_forum_chrome_stays_lean_against_dossier(self):
        """版面契约：暗色版只换视觉，不靠体积膨胀换效果（同数据不得比 dossier 大 3k 以上）。"""
        forum = self._html("forum")
        dossier = self._html("dossier")
        self.assertLessEqual(len(forum), len(dossier) + 3000,
                             f"forum {len(forum)} vs dossier {len(dossier)}：暗色版面开销过大")


class LimeThemeTests(unittest.TestCase):
    """白底圆角卡片 + 荧光绿强调风（lime，2026-10-10 起默认主题）"""

    def _html(self, theme="lime"):
        data = NewLayoutRenderingTests()._rich_data()
        return pipeline.generate_report(
            data, "2026年10月10日 · 周六", "20261010", theme=theme)

    def test_lime_is_default_and_resolvable(self):
        self.assertEqual(pipeline.DEFAULT_PUSH_THEME, "lime")
        self.assertIn("lime", pipeline.PUSH_THEMES)
        self.assertEqual(pipeline._resolve_push_theme(None), "lime")
        self.assertEqual(pipeline._resolve_push_theme("LIME"), "lime")

    def test_lime_palette_values_and_card_chrome(self):
        self.assertEqual(pipeline.L_BG, "#FFFFFF")
        self.assertEqual(pipeline.L_CARD, "#F5F5F6")
        self.assertEqual(pipeline.L_INK_STRONG, "#111111")
        self.assertEqual(pipeline.L_LIME, "#C8F03C")
        self.assertEqual(pipeline.L_LIME_WASH, "#F0F9C4")
        html = self._html()
        self.assertIn('name="octopus-theme" content="lime"', html)
        self.assertIn(f'bgcolor="{pipeline.L_BG}"', html)
        self.assertIn(f"background:{pipeline.L_CARD}", html)
        self.assertIn(f"background:{pipeline.L_LIME}", html)
        self.assertIn("border-radius:22px", html)
        self.assertIn("border-radius:999px", html)
        for banned in ("<style", 'class="', "<img", "<svg", "<script"):
            self.assertNotIn(banned, html, banned)

    def test_lime_text_colors_meet_wcag_aa_contrast(self):
        html = self._html()
        fg_colors = set(re.findall(r"(?<![-\w])color\s*:\s*(#[0-9A-Fa-f]{3,6})", html))
        self.assertTrue(fg_colors)
        for fg in fg_colors:
            self.assertFalse(pipeline._is_light_or_mid_gray_hex(fg), f"浅灰文字漏网: {fg}")
            for bg in (pipeline.L_BG, pipeline.L_CARD, pipeline.L_ZEBRA, pipeline.L_LIME_WASH):
                ratio = pipeline._contrast_ratio(fg, bg)
                self.assertGreaterEqual(ratio, 4.5, f"{fg} on {bg} contrast {ratio:.2f} < 4.5")

    def test_lime_multipart_split_and_push_preserve_theme(self):
        html = self._html()
        parts = pipeline._split_html_for_push(html, 20_000)
        self.assertIsNotNone(parts)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertIn('name="octopus-theme" content="lime"', part)
            self.assertIn(pipeline.L_CARD, part)
            self.assertIn(pipeline.L_LIME, part)


class FinanceSummaryRegressionTests(unittest.TestCase):
    """内地热点榜词汇摘要：标题数 / 媒体覆盖口径正确，不渲染未校准概率。"""

    def test_finance_summary_counts_title_mentions_and_media(self):
        headlines = [
            {"title": "AI大模型算力提升", "source": "媒体甲"},
            {"title": "AI算力需求增加", "source": "媒体乙"},
            {"title": "AI芯片公告", "source": "媒体甲"},
            {"title": "无财经分析的标题", "source": "媒体丙"},
        ]
        summary = pipeline._calculate_finance_summary(headlines)
        self.assertTrue(summary["enabled"])
        self.assertTrue(summary["has_data"])
        self.assertEqual(summary["total_titles"], 4)
        ai = next(item for item in summary["top_terms"] if item["term"] == "AI")
        self.assertEqual(ai["title_count"], 3)
        self.assertEqual(ai["media_count"], 2)
        self.assertNotIn("overall_positive_probability", summary)
        self.assertNotIn("overall_negative_probability", summary)


if __name__ == "__main__":
    unittest.main()
