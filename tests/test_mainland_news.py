"""📰 内地财经媒体源头（18 家）回归测试（全部离线，不发网络请求）。

2026-10-12 按用户指定新增：中证网（中国证券报）、证券日报网、证券日报之声、中国基金报、
财闻、经济参考网、IT之家、券商中国、每日经济新闻、北京商报网、21世纪经济报道、证券之星、
证券时报网、和讯网、金融投资报、时代财经、经济观察网、凤凰网财经。

本文件守住四件事：
  ① 注册表：恰好 18 家、名称与用户给的名单一一对应、各自带主页 / 域名白名单 / 说明，
     且每个域名都能生成「Bing → Google News」两路站内检索 RSS（数据线 mainland_news_rss）；
  ② 抓取口径（与港股新闻源头同一套）：官方订阅优先 → 站内检索；只收 72h 窗口内、
     带可验证时区发布时间的条目；链接按来源域名白名单校验（防注入）；每源条数上限；
     跨源同题只留首次出现的一条；抓不到就如实标暂缺，绝不历史兜底；
  ③ 落地：标题进标题池（section=内地财经媒体）→ 新闻情绪因子能归因、政策因子能命中；
  ④ 开关：OCTOPUS_MAINLAND_NEWS=0 时整体缺席（不写 data 键、群采集不调用）。
"""
import importlib.util
import re
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

sys.modules.setdefault("requests", types.SimpleNamespace())

REPO_ROOT = Path(__file__).parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
if str(OUTPUT_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUT_DIR))

import backup_sources as bk  # noqa: E402

MODULE_PATH = OUTPUT_DIR / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_mainland_news_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

# 用户点名要加的 18 家（顺序即用户给出的顺序；抓取 / 审计展示同序）
USER_LIST = (
    "中证网", "证券日报网", "中国基金报", "财闻", "经济参考网", "IT之家", "证券日报之声",
    "券商中国", "每日经济新闻", "北京商报", "21世纪经济报道", "证券之星", "证券时报网",
    "和讯网", "金融投资报", "时代财经", "经济观察网", "凤凰网财经",
)
# 每家媒体「必须落在白名单里」的官方域名
EXPECTED_HOSTS = {
    "中证网": "cs.com.cn", "证券日报网": "zqrb.cn", "中国基金报": "chnfund.com",
    "财闻": "caiwennews.com", "经济参考网": "jjckb.cn", "IT之家": "ithome.com",
    "证券日报之声": "zqrb.cn", "券商中国": "stcn.com", "每日经济新闻": "nbd.com.cn",
    "北京商报": "bbtonline.com.cn", "21世纪经济报道": "21jingji.com",
    "证券之星": "stockstar.com", "证券时报网": "stcn.com", "和讯网": "hexun.com",
    "金融投资报": "jrtzb.com.cn", "时代财经": "tfcaijing.com",
    "经济观察网": "eeo.com.cn", "凤凰网财经": "ifeng.com",
}


def _rss(items):
    # 真实 RSS 会把 & 转义成 &amp;（Bing 的跳转链接里全是 &），夹具同口径，
    # 否则 ElementTree 直接解析失败，测的就不是我们要测的东西了。
    from xml.sax.saxutils import escape as _esc_xml
    body = "".join(f"<item><title>{_esc_xml(t)}</title><link>{_esc_xml(u)}</link>"
                   f"<pubDate>{p}</pubDate></item>" for t, u, p in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'


def _rfc(dt):
    return dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def _cfg(name):
    return next(c for c in pipeline.MAINLAND_NEWS_SOURCES if c["name"].startswith(name))


def _bing_of(name):
    return bk.get_mainland_news_site_urls(pipeline._hk_news_site_host(_cfg(name)))[0]


# ======================================================================
# ① 注册表
# ======================================================================
class RegistryTests(unittest.TestCase):
    def test_exactly_eighteen_sources(self):
        self.assertEqual(pipeline.MAINLAND_NEWS_TOTAL, 18)
        self.assertEqual(len(pipeline.MAINLAND_NEWS_SOURCES), 18)
        self.assertEqual(len({c["name"] for c in pipeline.MAINLAND_NEWS_SOURCES}), 18,
                         "媒体名不得重复（审计与标题池按名字归属）")

    def test_every_user_named_media_is_registered(self):
        names = [c["name"] for c in pipeline.MAINLAND_NEWS_SOURCES]
        for user_name in USER_LIST:
            with self.subTest(media=user_name):
                self.assertTrue(any(user_name in n for n in names),
                                f"用户点名的「{user_name}」不在源头表里")

    def test_each_source_declares_official_host_and_desc(self):
        for cfg in pipeline.MAINLAND_NEWS_SOURCES:
            with self.subTest(src=cfg["name"]):
                self.assertEqual(cfg["region"], "内地")
                self.assertTrue(cfg["url"].startswith("https://"))
                self.assertTrue(cfg["hosts"], "必须有链接白名单域名")
                self.assertTrue(cfg["desc"])
                self.assertIn("feed", cfg)          # 结构完整：官方订阅地址留空也要显式声明
                # 2026-10-13：多数媒体仍无官方订阅（feed 留空 → 走站内检索）；
                # 少数实测可用的官方订阅已填上（如 IT之家 https://www.ithome.com/rss/）。
                # 填了的必须 https 且主机在自己的白名单里，否则抓取时会被外链校验拒掉。
                feed = str(cfg.get("feed") or "").strip()
                if feed:
                    self.assertTrue(feed.startswith("https://"), f"{cfg['name']} 官方订阅必须 https")
                    self.assertIn(urlparse(feed).hostname, cfg["hosts"],
                                  f"{cfg['name']} 官方订阅主机不在白名单里")
                # site 覆盖（凤凰网财经 = finance.ifeng.com）：给了就必须是白名单里的主机
                site = str(cfg.get("site") or "").strip()
                if site:
                    self.assertIn(site, cfg["hosts"],
                                  f"{cfg['name']} 的 site: 检索域不在白名单里")

    def test_domains_match_the_media(self):
        for user_name, host in EXPECTED_HOSTS.items():
            with self.subTest(media=user_name):
                cfg = _cfg(user_name)
                self.assertIn(host, cfg["hosts"], f"{cfg['name']} 白名单应含 {host}")

    def test_site_search_backups_are_registered_data_line(self):
        line = bk.DATA_LINES["mainland_news_rss"]
        self.assertIn("内地财经媒体", line["name"])
        self.assertEqual(len(line["backups"]), 2)
        self.assertTrue(any("新闻情绪" in u for u in line["used_by"]))
        self.assertTrue(any("政策因子" in u for u in line["used_by"]))
        for cfg in pipeline.MAINLAND_NEWS_SOURCES:
            urls = bk.get_mainland_news_site_urls(pipeline._hk_news_site_host(cfg))
            self.assertEqual(len(urls), 2, cfg["name"])
            self.assertIn("bing.com", urls[0])
            self.assertIn("news.google.com", urls[1])

    def test_hk_pool_and_mainland_pool_coexist(self):
        """两套源头并存（用户 2026-10-12 选定：B 方案）：

        · 「全网新闻源头」池 = 香港 7 + 内地 23 + 国际 6 = 36（内地段含 main 侧并入的 16 家）；
        · 「内地财经媒体源头」= 独立 18 家（含 证券时报网 / 证券日报之声 这两条 main 侧未加的）；
        · 同域媒体会同时出现在两条线上，但**是两条独立数据线**（hk_news_rss / mainland_news_rss），
          各自采集、各自审计计数，不互相替代；
        · 18 家池自身不得混进 36 源池（源表彼此独立）。
        """
        self.assertEqual(pipeline.HK_NEWS_TOTAL, 36)
        self.assertEqual(len(pipeline.HK_NEWS_SOURCES), 36)
        hk_names = [c["name"] for c in pipeline.HK_NEWS_SOURCES]
        self.assertIn("证券时报·快讯", hk_names)
        self.assertNotIn(pipeline.MAINLAND_NEWS_SOURCE_NAME, hk_names)
        self.assertEqual(pipeline.MAINLAND_NEWS_TOTAL, 18)
        # 两条线各有自己的站内检索数据线（审计归属分开）
        self.assertIn("hk_news_rss", bk.DATA_LINES)
        self.assertIn("mainland_news_rss", bk.DATA_LINES)
        # 同域并存是明确选择：两条线的域名存在交集（例如 cs.com.cn）
        hk_hosts = {h for c in pipeline.HK_NEWS_SOURCES for h in (c.get("hosts") or ())}
        ml_hosts = {h for c in pipeline.MAINLAND_NEWS_SOURCES for h in (c.get("hosts") or ())}
        self.assertTrue(hk_hosts & ml_hosts, "两套源头并存时域名本就应有交集")

    def test_declared_hosts_cover_their_own_home_url(self):
        """主页域名必须在白名单里，否则主源取到的原文链接会被自己拦掉。"""
        for cfg in pipeline.MAINLAND_NEWS_SOURCES:
            host = re.sub(r"^www\\.", "", cfg["url"].split("//", 1)[1].split("/", 1)[0])
            with self.subTest(src=cfg["name"]):
                self.assertIn(host, {h for h in cfg["hosts"]})


# ======================================================================
# ② 抓取口径
# ======================================================================
class FetchTests(unittest.TestCase):
    def _run(self, feeds, calls=None):
        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            if calls is not None:
                calls.append(url)
            return feeds.get(url)
        with patch.object(pipeline, "safe_request", side_effect=fake):
            return pipeline.fetch_mainland_news_sources()

    def test_collects_site_search_titles_with_window_and_host_checks(self):
        now = datetime.now(pipeline.CST)
        fresh = _rfc(now - timedelta(hours=2))
        stale = _rfc(now - timedelta(hours=100))          # 超出 72h 窗口
        no_tz = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")   # 缺时区
        cs_bing = _bing_of("中证网")
        nbd_bing = _bing_of("每日经济新闻")
        feeds = {
            cs_bing: _rss([
                ("央行宣布降准0.5个百分点释放长期资金 - 中证网", "https://www.cs.com.cn/a/1.html", fresh),
                ("三天前的旧闻 - 中证网", "https://www.cs.com.cn/a/2.html", stale),
                ("没有时区的条目 - 中证网", "https://www.cs.com.cn/a/3.html", no_tz),
                ("外站注入", "https://evil.example.com/x.html", fresh),
            ]),
            nbd_bing: _rss([
                ("央行宣布降准0.5个百分点释放长期资金 - 每日经济新闻",   # 跨源同题
                 "https://www.nbd.com.cn/articles/1.html", fresh),
                ("某公司三季报预增 - 每日经济新闻", "https://www.nbd.com.cn/articles/2.html", fresh),
            ]),
        }
        res = self._run(feeds)
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["is_today"])
        recs = {r["name"]: r for r in res["sources"]}
        cs = recs["中证网（中国证券报）"]
        self.assertEqual(cs["status"], "ok")
        self.assertEqual(cs["served_by"], "站内检索")
        self.assertEqual([it["title"] for it in cs["items"]], ["央行宣布降准0.5个百分点释放长期资金"])
        self.assertEqual(cs["scanned"], 1)                # 旧闻 / 无时区 / 外站链接都不算
        self.assertIn("站内检索", cs["note"])
        titles = [h["title"] for h in res["headlines"]]
        self.assertEqual(titles.count("央行宣布降准0.5个百分点释放长期资金"), 1,
                         "跨源同题只留首次出现的一条")
        self.assertEqual(res["analysis"]["merged"], 1)
        self.assertEqual(res["headlines"][0]["section"], "内地财经媒体")
        self.assertEqual(res["headlines"][0]["source"], "中证网（中国证券报）")
        self.assertTrue(res["headlines"][0]["is_today"])
        # 没配 feed 的媒体抓不到 → 如实标暂缺并列名，绝不用历史内容兜底
        self.assertEqual(recs["IT之家"]["status"], "fail")
        self.assertTrue(res["partial"])
        self.assertIn("暂缺（16 家）", res["note"])

    def test_official_feed_wins_and_backup_event_is_logged(self):
        now = datetime.now(pipeline.CST)
        fresh = _rfc(now - timedelta(hours=3))
        cfg = _cfg("中国基金报")
        with_feed = dict(cfg, feed="https://www.chnfund.com/rss/news.xml")
        with patch.object(pipeline, "MAINLAND_NEWS_SOURCES", (with_feed,)):
            pipeline.BACKUP_EVENTS.clear()
            res = self._run({
                with_feed["feed"]: _rss([("公募费率改革落地", "https://www.chnfund.com/a/1.html", fresh)]),
            })
        rec = res["sources"][0]
        self.assertEqual(rec["served_by"], "官方订阅")
        self.assertEqual(rec["items"][0]["url"], "https://www.chnfund.com/a/1.html")
        self.assertFalse(any("内地财经媒体" in e[0] for e in pipeline.BACKUP_EVENTS),
                         "官方订阅成功时不应记备用源事件")

        with patch.object(pipeline, "MAINLAND_NEWS_SOURCES", (with_feed,)):
            pipeline.BACKUP_EVENTS.clear()
            res2 = self._run({                              # 官方订阅挂 → Bing 站内检索顶上
                _bing_of("中国基金报"): _rss([
                    ("公募费率改革落地 - 中国基金报", "https://www.chnfund.com/a/2.html", fresh)]),
            })
        rec2 = res2["sources"][0]
        self.assertEqual(rec2["served_by"], "备用源（站内检索）")
        self.assertEqual(rec2["items"][0]["title"], "公募费率改革落地")
        self.assertIn("Bing", rec2["note"])
        self.assertTrue(any(e[0].startswith("内地财经媒体") for e in pipeline.BACKUP_EVENTS))
        pipeline.BACKUP_EVENTS.clear()

    def test_per_source_cap_and_empty_window(self):
        now = datetime.now(pipeline.CST)
        fresh = _rfc(now - timedelta(hours=1))
        items = [(f"新闻{i} - 证券之星", f"https://www.stockstar.com/a/{i}.html", fresh)
                 for i in range(6)]
        with patch.object(pipeline, "MAINLAND_NEWS_PER_SOURCE", 2):
            res = self._run({_bing_of("证券之星"): _rss(items)})
        rec = next(r for r in res["sources"] if r["name"].startswith("证券之星"))
        self.assertEqual(len(rec["items"]), 2)
        self.assertEqual(rec["scanned"], 6)

        stale = _rfc(now - timedelta(hours=200))
        res2 = self._run({_bing_of("和讯网"): _rss([("陈年旧闻 - 和讯网",
                                                   "https://www.hexun.com/a/1.html", stale)])})
        rec2 = next(r for r in res2["sources"] if r["name"].startswith("和讯网"))
        self.assertEqual(rec2["status"], "empty")
        self.assertIn("无可验证发布时间", rec2["note"])

    def test_all_sources_failing_is_unavailable_not_silent(self):
        res = self._run({})
        self.assertEqual(res["status"], "unavailable")
        self.assertEqual(res["headlines"], [])
        self.assertIn("均未取得", res["error"])
        self.assertEqual(len(res["sources"]), 18)

    def test_switch_off_short_circuits(self):
        with patch.object(pipeline, "MAINLAND_NEWS_ENABLED", False):
            res = pipeline.fetch_mainland_news_sources()
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("OCTOPUS_MAINLAND_NEWS=0", res["error"])


# ======================================================================
# ③ 落地：标题池 → 新闻情绪 / 政策因子
# ======================================================================
class TitlePoolTests(unittest.TestCase):
    def _source(self, titles):
        return pipeline._source_result(
            pipeline.MAINLAND_NEWS_SOURCE_NAME, "success", is_today=True,
            content_date="2026-08-02",
            sources=[], analysis={"scanned": len(titles), "ok_n": 1, "today_n": len(titles)},
            headlines=[{"title": t, "source": "证券时报网", "section": pipeline.MAINLAND_NEWS_SECTION,
                        "url": "https://www.stcn.com/a/1.html",
                        "published_cst": "2026-08-02 10:00", "date": "2026-08-02",
                        "is_today": True} for t in titles])

    def test_headlines_enter_the_shared_title_pool(self):
        data = {pipeline.MAINLAND_NEWS_SOURCE_NAME: self._source(
            ["央行宣布降准0.5个百分点释放长期资金"])}
        items = pipeline._collect_headline_items(data, "2026-08-02")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["section"], pipeline.MAINLAND_NEWS_SECTION)
        self.assertEqual(items[0]["source"], "证券时报网")
        self.assertEqual(items[0]["ts"], "2026-08-02 10:00")
        self.assertEqual(items[0]["url"], "https://www.stcn.com/a/1.html")

    def test_policy_factor_picks_up_mainland_policy_headline(self):
        data = {pipeline.MAINLAND_NEWS_SOURCE_NAME: self._source(
            ["国常会部署稳增长举措 央行宣布降准0.5个百分点释放长期资金"])}
        res = pipeline.build_policy_factor(data, "20260802")
        self.assertTrue(res.get("available"))
        titles = [h.get("title") for h in res.get("headlines") or []]
        self.assertTrue(any("降准" in str(t) for t in titles), f"政策因子应命中该标题：{titles}")

    def test_news_sentiment_attributes_mainland_headline_to_hot_stock(self):
        data = {
            "热门榜单": pipeline._source_result(
                "热门榜单", "success", is_today=True, content_date="2026-08-02",
                markets={"A股": {"stocks": [{"code": "300750", "name": "宁德时代"}]}}),
            pipeline.MAINLAND_NEWS_SOURCE_NAME: self._source(
                ["宁德时代获机构上调目标价，主力资金净流入明显"]),
        }
        with patch.dict(pipeline.LITE_LIMITS, {"senti_stocks": (3, 3), "senti_headlines": (2, 2)}):
            res = pipeline.build_news_sentiment(data, "20260802", None)
        self.assertTrue(res.get("available"))
        rows = [s for mb in res.get("by_market") or [] for s in mb.get("stocks") or []]
        self.assertTrue(rows)
        titles = [h["title"] for s in rows for h in (s.get("headlines") or [])]
        self.assertTrue(any("宁德时代" in t for t in titles), titles)
        self.assertTrue(all(h.get("section") == pipeline.MAINLAND_NEWS_SECTION
                            for s in rows for h in (s.get("headlines") or [])))

    def test_source_enters_coverage_audit(self):
        data = {pipeline.MAINLAND_NEWS_SOURCE_NAME: self._source(["某篇内地财经新闻"])}
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            report = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802")
        # 8 个基础数据源（实时行情…港股量化，缺数据也占位）+ 本源头 = 9
        parts = pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT)
        self.assertEqual(parts["total"], 9)
        self.assertEqual(parts["today_n"], 1)
        self.assertEqual(parts["content_n"], 1)
        self.assertEqual(pipeline._report_meta(report)["total_sources"], 9)
        self.assertEqual(pipeline._report_meta(report)["today_sources"], 1)

    def test_absent_key_keeps_legacy_source_counts(self):
        """外部旧调用不传该键时，基础数据源数量与审计口径完全不变。"""
        data = {}
        parts = pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT)
        self.assertEqual(parts["total"], 8, "基础数据源占位不因新增源头而变")
        self.assertEqual(parts["today_n"], 0)
        self.assertNotIn(pipeline.MAINLAND_NEWS_SOURCE_NAME, data)


# ======================================================================
# ③b 趋势跟踪栏目里的源头展示行（源头级覆盖，不重复列标题）
# ======================================================================
class TrendSectionTests(unittest.TestCase):
    def _data(self):
        items = [{"title": "国常会部署稳增长举措 央行宣布降准0.5个百分点释放长期资金",
                  "source": "中证网（中国证券报）", "section": pipeline.MAINLAND_NEWS_SECTION,
                  "url": "https://www.cs.com.cn/a/1.html",
                  "published_cst": "2026-08-02 10:00", "date": "2026-08-02", "is_today": True},
                 {"title": "半导体设备板块领涨", "source": "凤凰网财经",
                  "section": pipeline.MAINLAND_NEWS_SECTION,
                  "url": "https://finance.ifeng.com/a/3.html",
                  "published_cst": "2026-08-02 10:05", "date": "2026-08-02", "is_today": True}]
        recs = [{"name": "中证网（中国证券报）", "status": "ok", "items": [items[0]]},
                {"name": "凤凰网财经", "status": "ok", "items": [items[1]]}]
        return {pipeline.MAINLAND_NEWS_SOURCE_NAME: pipeline._source_result(
            pipeline.MAINLAND_NEWS_SOURCE_NAME, "success", is_today=True,
            content_date="2026-08-02", sources=recs, headlines=items,
            analysis={"scanned": 2, "ok_n": 2, "today_n": 2, "items_n": 2, "merged": 0})}

    def test_trend_block_reports_source_coverage_without_relisting_titles(self):
        digest = pipeline._trend_clues_block(self._data(), pipeline.GUIZANG_KIT)
        self.assertIn(f"内地财经媒体 ×{pipeline.MAINLAND_NEWS_TOTAL}", digest)
        self.assertIn("标题池 2 条", digest)
        # 标题不在这里重复列出（它们在被引用处出现：新闻情绪证据行 / 政策因子引用行）
        self.assertNotIn("国常会部署稳增长举措", digest)
        self.assertNotIn("半导体设备板块领涨", digest)

    def test_full_mode_lists_coverage_names(self):
        with patch.object(pipeline, "LITE_ENABLED", True), \
                patch.object(pipeline, "NOTES_REQUESTED", True):
            digest = pipeline._trend_clues_block(self._data(), pipeline.GUIZANG_KIT)
        self.assertIn("覆盖面", digest)
        self.assertIn("中证网（中国证券报） 1", digest)
        self.assertIn("凤凰网财经 1", digest)
        self.assertIn("标题去向", digest)

    def test_trend_section_renders_when_only_mainland_source_is_available(self):
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            html = pipeline.generate_report(self._data(), "2026年8月2日 · 周日", "20260802")
        self.assertIn(f"内地财经媒体 ×{pipeline.MAINLAND_NEWS_TOTAL}", html)
        self.assertIn(pipeline.SECTION_TITLE_TREND, html)

    def test_trend_block_absent_when_source_unavailable(self):
        data = {pipeline.MAINLAND_NEWS_SOURCE_NAME: pipeline._source_result(
            pipeline.MAINLAND_NEWS_SOURCE_NAME, "unavailable", sources=[], headlines=[],
            analysis=None, error="offline")}
        digest = pipeline._trend_clues_block(data, pipeline.GUIZANG_KIT)
        self.assertNotIn("内地财经媒体 ×", digest or "")


# ======================================================================
# ④ 采集主流程接线
# ======================================================================
class CollectorWiringTests(unittest.TestCase):
    def _run_collect(self, mainland_enabled=True, mainland_result=None):
        legacy = ("fetch_market_snapshot", "fetch_market_panorama", "fetch_gov_policy",
                  "fetch_hk_channels", "fetch_google_news", "fetch_fed_trend",
                  "fetch_geo_trend", "fetch_eastmoney_news", "fetch_hot_stocks",
                  "fetch_hk_quant", "fetch_weekly_forecast", "fetch_hk_seven_day",
                  "fetch_econ_calendar", "fetch_industry_rotation",
                  "fetch_sector_rotation", "fetch_uzi_trend", "fetch_macd_strategy")
        mocks = [patch.object(pipeline, fn, return_value={"status": "unavailable"})
                 for fn in legacy]
        for p in mocks:
            p.start()
        try:
            with patch.object(pipeline, "time", types.SimpleNamespace(sleep=lambda s: None)):
                with patch.object(pipeline, "fetch_public_sites", return_value={}):
                    with patch.object(pipeline, "fetch_hk_news_sources",
                                      return_value={"status": "unavailable"}):
                        with patch.object(pipeline, "MAINLAND_NEWS_ENABLED", mainland_enabled):
                            with patch.object(pipeline, "fetch_mainland_news_sources",
                                              return_value=mainland_result or {"status": "unavailable"},
                                              ) as spy:
                                data = pipeline.collect_all_data()
                                return data, spy
        finally:
            for p in reversed(mocks):
                p.stop()

    def test_collector_calls_mainland_fetch_when_enabled(self):
        data, spy = self._run_collect(True, {"status": "unavailable"})
        self.assertTrue(spy.called)
        self.assertIn(pipeline.MAINLAND_NEWS_SOURCE_NAME, data)

    def test_collector_skips_mainland_fetch_when_switched_off(self):
        with patch.object(pipeline, "fetch_mainland_news_sources",
                          side_effect=AssertionError("开关关闭时不得调用")):
            data, _spy = self._run_collect(False)
        self.assertNotIn(pipeline.MAINLAND_NEWS_SOURCE_NAME, data)


if __name__ == "__main__":
    unittest.main()


# ======================================================================
# ⑤ 取数修复（2026-10-13）：检索源链接还原 + 候选源回退
#    根因：Bing News 站内检索 RSS 的 <link> 是明文 http 的平台跳转地址，
#    被「https + 白名单主机」整条拒绝 → 依赖站内检索的源头天天 0 条。
# ======================================================================
class SearchLinkTests(unittest.TestCase):
    CS_HOSTS = ("cs.com.cn", "www.cs.com.cn") + pipeline._HK_NEWS_BACKUP_LINK_HOSTS
    ZQ_HOSTS = ("zqrb.cn", "www.zqrb.cn") + pipeline._HK_NEWS_BACKUP_LINK_HOSTS

    def test_bing_http_redirect_resolves_to_original_article(self):
        link = ("http://www.bing.com/news/apiclick.aspx?ref=FexRss&aid=&tid=t"
                "&url=https%3a%2f%2fwww.cs.com.cn%2fa%2f1.html&c=1&mkt=en-us")
        self.assertEqual(pipeline._news_url(link, self.CS_HOSTS), "",
                         "旧口径：明文 http 跳转链接必然被拒（这正是 18 家长期暂缺的原因）")
        self.assertEqual(pipeline._resolve_search_link(link, self.CS_HOSTS),
                         "https://www.cs.com.cn/a/1.html")

    def test_http_only_original_falls_back_to_platform_https_redirect(self):
        link = ("http://www.bing.com/news/apiclick.aspx?ref=FexRss&aid=&tid=t"
                "&url=http%3a%2f%2fwww.zqrb.cn%2fa%2f1.html&c=1&mkt=en-us")
        got = pipeline._resolve_search_link(link, self.ZQ_HOSTS)
        self.assertTrue(got.startswith("https://www.bing.com/news/apiclick.aspx"), got)
        self.assertIn("http%3a%2f%2fwww.zqrb.cn", got)

    def test_verified_http_host_is_upgraded_to_https(self):
        """已实测支持 https 的站（jjckb.cn）：http 原文升级成 https 直达，不用跳转。"""
        link = ("http://www.bing.com/news/apiclick.aspx?ref=FexRss&tid=t"
                "&url=http%3a%2f%2fwww.jjckb.cn%2f2026%2fa.html&c=1&mkt=en-us")
        self.assertEqual(
            pipeline._resolve_search_link(link, ("jjckb.cn", "www.jjckb.cn")
                                          + pipeline._HK_NEWS_BACKUP_LINK_HOSTS),
            "https://www.jjckb.cn/2026/a.html")

    def test_unverified_http_host_is_not_guessed(self):
        """没实测过的站不猜 https：原文直链被拒，但平台跳转链接仍可升级后使用。"""
        hosts = ("zqrb.cn", "www.zqrb.cn") + pipeline._HK_NEWS_BACKUP_LINK_HOSTS
        self.assertEqual(pipeline._resolve_search_link("http://www.zqrb.cn/a.html", hosts), "")
        got = pipeline._resolve_search_link(
            "http://www.bing.com/news/apiclick.aspx?tid=t"
            "&url=http%3a%2f%2fwww.zqrb.cn%2fa.html&c=1", hosts)
        self.assertTrue(got.startswith("https://www.bing.com/news/apiclick.aspx"), got)

    def test_direct_https_link_is_untouched(self):
        url = "https://www.cs.com.cn/a/1.html"
        self.assertEqual(pipeline._resolve_search_link(url, self.CS_HOSTS), url)

    def test_non_whitelisted_and_junk_links_are_rejected(self):
        for bad in ("https://evil.example.com/a.html", "javascript:alert(1)",
                    "http://www.cs.com.cn:8080/a.html", "", None):
            self.assertEqual(pipeline._resolve_search_link(bad, self.CS_HOSTS), "", bad)


class CandidateFallbackTests(unittest.TestCase):
    def _run(self, feeds, calls=None):
        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            if calls is not None:
                calls.append(url)
            return feeds.get(url)
        with patch.object(pipeline, "safe_request", side_effect=fake):
            return pipeline.fetch_mainland_news_sources()

    def test_unusable_first_candidate_falls_through_to_the_next(self):
        """解析得出条目、但链接全被拒（0 条可用）→ 继续试下一路候选源。

        旧版只试第一个「解析成功」的源，于是停在 Bing 上永远 0 条，
        后面真正能用的 Google News 根本轮不到——18 家因此天天判暂缺。
        """
        now = datetime.now(pipeline.CST)
        fresh = _rfc(now - timedelta(hours=2))
        cfg = _cfg("财闻")
        calls = []
        with patch.object(pipeline, "MAINLAND_NEWS_SOURCES", (cfg,)):
            res = self._run({
                bk.get_mainland_news_site_urls(_cfg("财闻")["hosts"][0])[0]: _rss([
                    ("第一路全是拿不到可用链接的条目 - 财闻",
                     "http://www.caiwennews.com/article/0.shtml", fresh)]),
                bk.get_mainland_news_site_urls(_cfg("财闻")["hosts"][0])[1]: _rss([
                    ("Google 备用源顶上 - 财闻", "https://www.caiwennews.com/article/1.shtml",
                     fresh)]),
            }, calls=calls)
        self.assertEqual(len(calls), 2, "第一路 0 条可用后应继续尝试第二路")
        rec = res["sources"][0]
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["items"][0]["title"], "Google 备用源顶上")
        self.assertIn("Google", rec["via"])

    def test_zero_usable_from_all_candidates_is_reported_honestly(self):
        now = datetime.now(pipeline.CST)
        fresh = _rfc(now - timedelta(hours=2))
        cfg = _cfg("财闻")
        with patch.object(pipeline, "MAINLAND_NEWS_SOURCES", (cfg,)):
            res = self._run({
                bk.get_mainland_news_site_urls("caiwennews.com")[0]: _rss([
                    ("外站注入 - 财闻", "https://evil.example.com/a.html", fresh)]),
                bk.get_mainland_news_site_urls("caiwennews.com")[1]: _rss([
                    ("外站注入 - 财闻", "https://evil.example.com/b.html", fresh)]),
            })
        rec = res["sources"][0]
        self.assertEqual(rec["status"], "empty")
        self.assertIn("已试 2 路候选源", rec["note"])
        self.assertEqual(rec["state"], "暂缺")

    def test_bing_redirect_links_enter_the_pool_after_fix(self):
        """真实 Bing 报文（明文 http 跳转）如今能解出原文链接并进标题池。"""
        now = datetime.now(pipeline.CST)
        fresh = _rfc(now - timedelta(hours=3))
        cfg = _cfg("中证网")
        with patch.object(pipeline, "MAINLAND_NEWS_SOURCES", (cfg,)):
            res = self._run({_bing_of("中证网"): _rss([
                ("IMF上调2026年世界经济增长预期至3.1% - 中证网",
                 "http://www.bing.com/news/apiclick.aspx?ref=FexRss&tid=t"
                 "&url=https%3a%2f%2fwww.cs.com.cn%2fxwzx%2f01%2f2026%2f10%2f13%2fd1.html&c=1&mkt=en-us",
                 fresh)])})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["headlines"][0]["url"],
                         "https://www.cs.com.cn/xwzx/01/2026/10/13/d1.html",
                         "解出的是原文直达链接，不是平台跳转")

    def test_health_metrics_are_recorded_per_source(self):
        now = datetime.now(pipeline.CST)
        fresh = _rfc(now - timedelta(hours=5))
        with patch.object(pipeline, "MAINLAND_NEWS_SOURCES", (_cfg("中证网"),)):
            res = self._run({_bing_of("中证网"): _rss([
                ("央行宣布降准 - 中证网", "https://www.cs.com.cn/a/1.html", fresh)])})
        an = res["analysis"]
        self.assertIsNotNone(an["newest_cst"])
        self.assertGreaterEqual(float(an["lag_hours"]), 4.5)
        self.assertLessEqual(float(an["lag_hours"]), 6.0)
        self.assertEqual(len(an["health"]), 1)
        self.assertEqual(an["health"][0]["state"], "当天")
        self.assertEqual(an["health"][0]["via"], "Bing 站内检索")


# ======================================================================
# ⑥ 【沸腾花蛤】情绪热点因子量化分析（2026-10-13 新增栏目「内地财经热点榜」，2026-10-19 更名）
# ======================================================================
def _hotlist_data(entries=(), missing=("北京商报（北京商报网）",), ok_n=2):
    """构造一份「内地财经媒体源头」结果：entries = (标题, 媒体, 链接, 北京时间)。"""
    items, records = [], []
    for i, (title, src, url, cst) in enumerate(entries):
        item = {"title": title, "source": src, "section": pipeline.MAINLAND_NEWS_SECTION,
                "url": url, "published_cst": cst, "date": cst[:10], "is_today": True}
        items.append(item)
        records.append({"name": src, "status": "ok", "items": [item], "scanned": 1,
                        "today": 1, "newest": cst[:10], "newest_cst": cst,
                        "lag_hours": 2.0 + i, "state": "当天", "via": "Bing 站内检索"})
    for name in missing:
        records.append({"name": name, "status": "empty", "items": [], "scanned": 0,
                        "today": 0, "newest": None, "newest_cst": None,
                        "lag_hours": None, "state": "暂缺", "via": "—"})
    newest = max((r["newest_cst"] for r in records if r.get("newest_cst")), default=None)
    return {pipeline.MAINLAND_NEWS_SOURCE_NAME: pipeline._source_result(
        pipeline.MAINLAND_NEWS_SOURCE_NAME, "success", is_today=True,
        content_date="2026-10-13", sources=records, headlines=items,
        analysis={"scanned": len(items), "ok_n": ok_n, "today_n": len(items),
                  "items_n": len(items), "merged": 0, "newest_cst": newest,
                  "lag_hours": 2.0,
                  "health": [{"name": r["name"], "status": r["status"],
                              "items": len(r.get("items") or []),
                              "newest_cst": r.get("newest_cst"),
                              "lag_hours": r.get("lag_hours"),
                              "state": r["state"], "via": r["via"]} for r in records]})}


_HOT_ENTRIES = (
    ("A股三大指数集体低开 创业板指跌超2%", "经济观察网",
     "https://www.eeo.com.cn/2026/1013/1.shtml", "2026-10-13 05:27"),
    ("半导体企业频频披露大订单 A股板块年营收有望破万亿", "和讯网",
     "https://stock.hexun.com/2026-10-12/1.html", "2026-10-12 09:28"),
    ("证监会主席吴清将出席金融街论坛并作演讲", "凤凰网财经",
     "https://finance.ifeng.com/c/1", "2026-10-12 23:28"),
    ("3年期大额存单利率重回2% 部分中小银行逆势上调存款利率", "证券日报网",
     "http://www.zqrb.cn/jrjg/1.html", "2026-10-13 02:35"),
    ("存储芯片供给紧张、需求旺盛格局没有变化", "财闻",
     "https://www.caiwennews.com/article/1.shtml", "2026-10-12 23:16"),
    ("今天天气不错，饭很好吃", "时代财经",
     "https://www.tfcaijing.com/article/page/1", "2026-10-12 23:47"),
)


class HotlistBuildTests(unittest.TestCase):
    def test_theme_counts_sum_to_the_pool_size(self):
        data = _hotlist_data(_HOT_ENTRIES)
        hot = pipeline.build_mainland_hotlist(data[pipeline.MAINLAND_NEWS_SOURCE_NAME])
        self.assertEqual(sum(t["count"] for t in hot["themes"]), hot["total"])
        self.assertEqual(hot["total"], len(_HOT_ENTRIES))

    def test_vocabulary_summary_is_added_without_mutating_the_source_pool(self):
        mainland = _hotlist_data(_HOT_ENTRIES)[pipeline.MAINLAND_NEWS_SOURCE_NAME]
        original = mainland["headlines"][0]
        hot = pipeline.build_mainland_hotlist(mainland)
        self.assertNotIn("finance_analysis", original, "渲染分析不能改写采集层标题池")
        self.assertTrue(hot["finance_summary"]["has_data"])
        self.assertEqual(hot["finance_summary"]["total_titles"], len(_HOT_ENTRIES))
        self.assertTrue(hot["finance_summary"]["top_terms"])
        self.assertTrue(all("title_count" in term and "media_count" in term
                            for term in hot["finance_summary"]["top_terms"]))

    def test_headlines_are_classified_and_sorted(self):
        hot = pipeline.build_mainland_hotlist(
            _hotlist_data(_HOT_ENTRIES)[pipeline.MAINLAND_NEWS_SOURCE_NAME])
        labels = [t["label"] for t in hot["themes"]]
        self.assertIn("A股盘面", labels)
        self.assertIn("政策与监管", labels)            # 「证监会」命中
        self.assertIn("半导体与算力", labels)          # 「芯片 / 半导体 / A股」按序命中
        self.assertIn(pipeline.MAINLAND_HOT_OTHER_LABEL, labels,
                      "未命中词表的标题进「其他 / 未归类」，不静默丢弃")
        counts = [t["count"] for t in hot["themes"]]
        self.assertEqual(counts, sorted(counts, reverse=True), "按条数降序")
        first = [t for t in hot["themes"] if t["label"] == "A股盘面"][0]
        self.assertEqual(first["items"][0]["published_cst"], "2026-10-13 05:27",
                         "主题内按时间倒序，最新的一条在最前")

    def test_is_deterministic(self):
        data = _hotlist_data(_HOT_ENTRIES)[pipeline.MAINLAND_NEWS_SOURCE_NAME]
        a = pipeline.build_mainland_hotlist(data)
        b = pipeline.build_mainland_hotlist(data)
        self.assertEqual([(t["label"], t["count"]) for t in a["themes"]],
                         [(t["label"], t["count"]) for t in b["themes"]])
        self.assertEqual(a["finance_summary"], b["finance_summary"])
        # 2026-10-19 新增的三块本地 AI 分析也必须逐字段可复现
        self.assertEqual(a["sentiment_agg"], b["sentiment_agg"])
        self.assertEqual(a["hotspots"], b["hotspots"])
        self.assertEqual(a["risk_report"], b["risk_report"])

    def test_sentiment_risk_hotspot_summaries_are_attached(self):
        hot = pipeline.build_mainland_hotlist(
            _hotlist_data(_HOT_ENTRIES)[pipeline.MAINLAND_NEWS_SOURCE_NAME])
        agg = hot["sentiment_agg"]
        self.assertTrue(agg["has_data"])
        self.assertEqual(agg["total_titles"], len(_HOT_ENTRIES))
        self.assertEqual(agg["pos_n"] + agg["neu_n"] + agg["neg_n"], len(_HOT_ENTRIES))
        self.assertIn(agg["label"], ("偏多", "中性", "偏空"))
        # 「创业板指跌超2%」命中风险词表（市场波动），天气标题不命中
        risk = hot["risk_report"]
        self.assertTrue(risk["has_data"])
        cats = [p["category"] for p in risk["points"]]
        self.assertIn("市场波动风险", cats)
        self.assertTrue(all(p["level"] in ("高", "中", "关注") for p in risk["points"]))
        self.assertTrue(all(p["samples"] for p in risk["points"]), "每类风险点都附证据标题")
        hotspots = hot["hotspots"]
        self.assertTrue(hotspots["has_data"])
        terms = {c["term"] for c in hotspots["clusters"]}
        self.assertIn("A股", terms)
        for c in hotspots["clusters"]:
            self.assertEqual(c["pos_n"] + c["neu_n"] + c["neg_n"], c["title_count"])
            self.assertEqual(c["aggregated"], c["title_count"] >= 2)

    def test_theme_buckets_carry_mood_counts(self):
        hot = pipeline.build_mainland_hotlist(
            _hotlist_data(_HOT_ENTRIES)[pipeline.MAINLAND_NEWS_SOURCE_NAME])
        for t in hot["themes"]:
            self.assertEqual(t["pos_n"] + t["neu_n"] + t["neg_n"], t["count"],
                             "主题级情绪折叠计数之和 = 主题条数")
            self.assertIn(t["mood"], ("偏多", "中性", "偏空"))

    def test_health_and_missing_are_carried(self):
        hot = pipeline.build_mainland_hotlist(
            _hotlist_data(_HOT_ENTRIES)[pipeline.MAINLAND_NEWS_SOURCE_NAME])
        self.assertEqual(hot["missing"], ["北京商报（北京商报网）"])
        self.assertEqual(hot["today_sources"], 6)
        self.assertEqual(hot["lag_sources"], 0)
        self.assertEqual(hot["newest_cst"], "2026-10-13 05:27")
        self.assertEqual(hot["status"], "success")

    def test_absent_when_source_is_unavailable_or_empty(self):
        for src in (
            pipeline._source_result(pipeline.MAINLAND_NEWS_SOURCE_NAME, "unavailable",
                                    sources=[], headlines=[], analysis=None, error="offline"),
            pipeline._source_result(pipeline.MAINLAND_NEWS_SOURCE_NAME, "success",
                                    sources=[], headlines=[], analysis={"items_n": 0}),
            None, {},
        ):
            self.assertIsNone(pipeline.build_mainland_hotlist(src))


class HotlistRenderTests(unittest.TestCase):
    def test_renders_in_all_five_themes(self):
        data = _hotlist_data(_HOT_ENTRIES)
        for theme, kit in (("lime", pipeline.LIME_KIT), ("pixel", pipeline.PIXEL_KIT),
                           ("forum", pipeline.FORUM_KIT), ("dossier", pipeline.DOSSIER_KIT),
                           ("guizang", pipeline.GUIZANG_KIT)):
            with self.subTest(theme=theme):
                html = pipeline.generate_report(data, "2026年10月13日 · 周二", "20261013",
                                                theme=theme)
                self.assertIn(pipeline.SECTION_TITLE_MAINLAND_HOTLIST, html)
                self.assertIn("情绪热点因子量化分析", html)
                self.assertNotIn("内地财经热点榜", html, "2026-10-19 更名后旧栏目名不再出现")
                self.assertIn("A股盘面", html)
                self.assertIn("情绪总览", html)
                self.assertIn("热点聚合", html)
                self.assertIn("预警风险点", html)
                self.assertIn("半导体", html)
                self.assertIn("北京商报（北京商报网）", html, "暂缺的媒体要在栏目里点名")
        hot = pipeline.build_mainland_hotlist(data[pipeline.MAINLAND_NEWS_SOURCE_NAME])
        self.assertEqual(len([t for t in hot["themes"]]), len(set(
            t["label"] for t in hot["themes"])), "主题不重复")

    def test_block_shows_health_and_missing(self):
        data = _hotlist_data(_HOT_ENTRIES)
        hot = pipeline.build_mainland_hotlist(data[pipeline.MAINLAND_NEWS_SOURCE_NAME])
        block = pipeline._mainland_hotlist_block(hot, pipeline.GUIZANG_KIT)
        self.assertIn("时效体检", block)
        self.assertIn("滞后", block)
        self.assertIn("暂缺", block)
        self.assertIn("https://www.eeo.com.cn/2026/1013/1.shtml", block,
                      "代表标题要带可点原文链接")
        self.assertIn(pipeline.MAINLAND_HOT_OTHER_LABEL, block)
        self.assertNotIn("AI词汇分析", block, "旧词汇分析已升级并入「热点聚合」")
        self.assertIn("热点聚合", block)
        self.assertIn("jieba 本地分词", block)
        self.assertNotIn("利好概率", block, "词典分数不能伪装成预测概率")

    def test_block_shows_sentiment_risk_and_hotspot_rows(self):
        data = _hotlist_data(_HOT_ENTRIES)
        hot = pipeline.build_mainland_hotlist(data[pipeline.MAINLAND_NEWS_SOURCE_NAME])
        block = pipeline._mainland_hotlist_block(hot, pipeline.GUIZANG_KIT)
        # ⚖ 情绪总览行：三档计数 + 净情绪分 + 「非校准概率」如实标注
        self.assertIn("情绪总览", block)
        self.assertIn("净情绪分", block)
        self.assertIn("非校准概率", block)
        # 🔥 热点聚合行：同题聚合标记 + 主题级情绪折叠
        self.assertIn("同题聚合", block)
        self.assertIn("情绪中性", block)
        # ⚠ 预警风险点行：等级 + 类别 + 命中词（「低开 / 跌超」来自创业板标题）
        self.assertIn("预警风险点", block)
        self.assertIn("市场波动风险", block)
        self.assertIn("【关注】", block)
        self.assertIn("命中词", block)

    def test_risk_evidence_row_does_not_repeat_theme_headline(self):
        data = _hotlist_data(_HOT_ENTRIES)
        hot = pipeline.build_mainland_hotlist(data[pipeline.MAINLAND_NEWS_SOURCE_NAME])
        with patch.object(pipeline, "LITE_ENABLED", False):
            block = pipeline._mainland_hotlist_block(hot, pipeline.GUIZANG_KIT)
        # 唯一的风险证据标题（eeo）已在主题榜代表行出现 → 风险点不重复贴同一条原文
        self.assertEqual(block.count("https://www.eeo.com.cn/2026/1013/1.shtml"), 1,
                         "栏内同一条原文只列一次")

    def test_block_reports_zero_risk_hits_honestly(self):
        entries = (("白酒板块逆市拉升，多股涨停", "时代财经",
                    "https://www.tfcaijing.com/article/page/9", "2026-10-13 02:35"),)
        hot = pipeline.build_mainland_hotlist(
            _hotlist_data(entries, missing=(), ok_n=1)[pipeline.MAINLAND_NEWS_SOURCE_NAME])
        block = pipeline._mainland_hotlist_block(hot, pipeline.GUIZANG_KIT)
        self.assertIn("预警风险点", block)
        self.assertIn("未命中风险词表", block, "0 命中要如实说，不硬造风险")

    def test_plain_mode_keeps_a_compact_health_row(self):
        data = _hotlist_data(_HOT_ENTRIES)
        hot = pipeline.build_mainland_hotlist(data[pipeline.MAINLAND_NEWS_SOURCE_NAME])
        with patch.object(pipeline, "LITE_ENABLED", True):
            block = pipeline._mainland_hotlist_block(hot, pipeline.GUIZANG_KIT)
            self.assertIn("时效体检", block, "入门版也要报时效，只是压成一行")
            self.assertIn("当天 6 家", block)
            self.assertNotIn("窗口内条数 · 最新 / 滞后", block, "入门版不展开逐家清单")

    def test_section_absent_without_data(self):
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            html = pipeline.generate_report(
                {pipeline.MAINLAND_NEWS_SOURCE_NAME: pipeline._source_result(
                    pipeline.MAINLAND_NEWS_SOURCE_NAME, "unavailable", sources=[],
                    headlines=[], analysis=None, error="offline")},
                "2026年10月13日 · 周二", "20261013")
        self.assertNotIn(pipeline.SECTION_TITLE_MAINLAND_HOTLIST, html)

    def test_switch_off_removes_only_the_column(self):
        data = _hotlist_data(_HOT_ENTRIES)
        with patch.object(pipeline, "MAINLAND_HOTLIST_ENABLED", False):
            with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
                html = pipeline.generate_report(data, "2026年10月13日 · 周二", "20261013")
        self.assertNotIn(pipeline.SECTION_TITLE_MAINLAND_HOTLIST, html)
        self.assertIn(pipeline.SECTION_TITLE_TREND, html, "趋势跟踪栏目不受影响")


def _corpus_items(*days):
    """存档夹具：news_history.json 条目口径（section=内地财经媒体，date=存档日期）。"""
    items = []
    for day, pairs in days:
        for t, s in pairs:
            items.append({"title": t, "source": s,
                          "section": pipeline.MAINLAND_NEWS_SECTION,
                          "ts": f"{day} 10:00", "date": day})
    return items


# 基准日 10-12：市场波动【关注】1 条 + 信用【关注】1 条 + 资金【关注】1 条；
# 今日 10-13：市场波动 3 条 3 家 →【高】（升级）+ 信用 1 条（持续）+ 1 条无命中；
# 资金流向今日缺席 → 解除。今日存档 5 条 ≥ 5 → 非低样本。
_TREND_CORPUS = _corpus_items(
    ("2026-10-12", (("个股大跌", "券商中国"), ("房企违约传闻", "和讯网"),
                    ("股东减持公告", "证券之星"))),
    ("2026-10-13", (("指数跌超3%", "甲媒体"), ("板块大跌", "乙媒体"),
                    ("个股低开", "丙媒体"), ("公司亏损扩大", "丁媒体"),
                    ("白酒板块逆市拉升", "戊媒体"))),
)


class HotlistTrendPostureTests(unittest.TestCase):
    """2026-10-20 预警风险点「平时也有功能」：🔭 预警趋势 + ⚠ 今日风险态势。"""

    def _hot(self, entries=_HOT_ENTRIES, corpus=None, date_str="20261013"):
        src = _hotlist_data(entries)[pipeline.MAINLAND_NEWS_SOURCE_NAME]
        return pipeline.build_mainland_hotlist(src, news_corpus=corpus, date_str=date_str)

    def test_trend_attached_only_with_corpus_and_date(self):
        hot = self._hot(corpus=_TREND_CORPUS)
        t = hot["risk_trend"]
        self.assertTrue(t["has_history"])
        self.assertEqual(t["baseline_date"], "2026-10-12")
        self.assertEqual(t["today"], "2026-10-13")
        self.assertFalse(t["low_sample"])
        status = {c["category"]: c["status"] for c in t["changes"]}
        self.assertEqual(status, {"市场波动风险": "升级", "信用与财务风险": "持续",
                                  "资金流向风险": "解除"})
        self.assertTrue(hot["risk_posture"]["has_data"])
        # 无存档 / 日期解析不出 → 趋势如实缺席，态势行仍在（历史存档不足口径）
        for kwargs in ({}, {"corpus": _TREND_CORPUS, "date_str": None}):
            h = self._hot(**kwargs)
            self.assertIsNone(h["risk_trend"])
            self.assertEqual(h["risk_posture"]["trend_phrase"], "历史存档不足，暂不按日对比")

    def test_corpus_only_counts_mainland_section(self):
        corpus = list(_TREND_CORPUS)
        corpus.append({"title": "某股暴跌", "source": "东方财富", "section": "东财快讯",
                       "ts": "2026-10-13 09:00", "date": "2026-10-13"})
        hot = self._hot(corpus=corpus)
        today = [d for d in hot["risk_trend"]["days"] if d["date"] == "2026-10-13"][0]
        self.assertEqual(today["total_titles"], 5, "只统计「内地财经媒体」段的存档")
        self.assertEqual(today["hit_n"], 4, "其他栏目的风险标题不混进本栏趋势")

    def test_full_block_renders_trend_and_posture_rows(self):
        hot = self._hot(corpus=_TREND_CORPUS)
        with patch.object(pipeline, "LITE_ENABLED", False):
            block = pipeline._mainland_hotlist_block(hot, pipeline.GUIZANG_KIT)
        self.assertIn("预警趋势", block)
        self.assertIn("近 7 日按日重算", block)
        self.assertIn("逐日命中 3·4（10-12→10-13）", block)
        self.assertIn("升级【关注→高】市场波动风险", block)
        self.assertIn("持续【关注】信用与财务风险", block)
        self.assertIn("解除 资金流向风险（前日【关注】）", block)
        self.assertIn("今日风险态势", block)
        self.assertIn("预警风险点", block, "命中日的预警风险点头行照旧")

    def test_full_block_shows_low_sample_caveat(self):
        corpus = _corpus_items(
            ("2026-10-12", (("房企违约传闻", "和讯网"),)),
            ("2026-10-13", (("指数跌超3%", "甲媒体"), ("个股大跌", "乙媒体"))))
        hot = self._hot(corpus=corpus)
        self.assertTrue(hot["risk_trend"]["low_sample"])
        with patch.object(pipeline, "LITE_ENABLED", False):
            block = pipeline._mainland_hotlist_block(hot, pipeline.GUIZANG_KIT)
        self.assertIn("今日存档 2 条样本尚少，对比仅作提示", block)
        self.assertIn("新增【中】市场波动风险", block)
        self.assertIn("解除 信用与财务风险（前日【关注】）", block)

    def test_plain_block_compresses_trend_and_posture(self):
        hot = self._hot(corpus=_TREND_CORPUS)
        with patch.object(pipeline, "LITE_ENABLED", True):
            block = pipeline._mainland_hotlist_block(hot, pipeline.GUIZANG_KIT)
        self.assertIn("预警趋势", block)
        self.assertNotIn("逐日命中", block, "入门版不出逐日明细")
        self.assertIn(hot["risk_trend"]["trend_phrase"], block)
        self.assertIn("今日风险态势", block)
        self.assertIn(hot["risk_posture"]["plain_text"], block)
        self.assertNotIn("近 7 日按日重算", block, "入门版不带口径长注")

    def test_trend_row_absent_without_history(self):
        hot = self._hot()
        with patch.object(pipeline, "LITE_ENABLED", False):
            block = pipeline._mainland_hotlist_block(hot, pipeline.GUIZANG_KIT)
        self.assertNotIn("预警趋势", block, "缺存档不出趋势行，不硬造变化")
        self.assertIn("今日风险态势", block)
        self.assertIn("历史存档不足", block)

    def test_zero_hit_day_keeps_disclosure_and_gains_posture(self):
        entries = (("白酒板块逆市拉升，多股涨停", "时代财经",
                    "https://www.tfcaijing.com/article/page/9", "2026-10-13 02:35"),)
        hot = self._hot(entries=entries, corpus=_TREND_CORPUS)
        self.assertFalse(hot["risk_report"]["has_data"])
        block = pipeline._mainland_hotlist_block(hot, pipeline.GUIZANG_KIT)
        self.assertIn("未命中风险词表", block, "0 命中披露行保留")
        self.assertIn("预警风险点", block)
        self.assertIn("今日风险态势", block)
        self.assertIn("无预警命中", block)
        self.assertIn("预警趋势", block, "平时也有趋势对比——这就是「平时也有功能」")

    def test_note_and_ren_consume_same_result(self):
        hot = self._hot(corpus=_TREND_CORPUS)
        notes = pipeline.build_section_ai_notes({}, hotlist=hot)
        note = notes["MAINLAND HOTLIST"]
        self.assertIn("→ 预测：", note["text"])
        self.assertNotIn("预警趋势", note["text"], "趋势不进研判行（避免同栏三处同句）")
        ren_txt = pipeline._ren._ren_mainland_hotlist(
            {"hotlist": hot, "date_str": "20261013", "notes": notes})
        self.assertIn("今日风险态势", ren_txt)
        self.assertIn(hot["risk_trend"]["trend_brief"], ren_txt)
        self.assertNotIn(hot["risk_trend"]["trend_phrase"], ren_txt,
                         "提鲜用 brief、态势行用 phrase——同栏不许同句")

    def test_build_with_corpus_is_deterministic(self):
        a = self._hot(corpus=_TREND_CORPUS)
        b = self._hot(corpus=_TREND_CORPUS)
        self.assertEqual(a["risk_trend"], b["risk_trend"])
        self.assertEqual(a["risk_posture"], b["risk_posture"])

    def test_page_renders_trend_and_posture_with_corpus(self):
        data = _hotlist_data(_HOT_ENTRIES)
        html = pipeline.generate_report(data, "2026年10月13日 · 周二", "20261013",
                                        news_corpus=_TREND_CORPUS)
        self.assertIn(pipeline.SECTION_TITLE_MAINLAND_HOTLIST, html)
        self.assertIn("预警趋势", html)
        self.assertIn("今日风险态势", html)
