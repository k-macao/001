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
    body = "".join(f"<item><title>{t}</title><link>{u}</link><pubDate>{p}</pubDate></item>"
                   for t, u, p in items)
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
                self.assertFalse(cfg["feed"], "默认没有官方 RSS：应留空并走站内检索")

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
