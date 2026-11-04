"""🔄 数据线主备回归测试：每条数据线 1 个主源 + 2 个备用源（全部离线，不发网络请求）。

覆盖三件事：
  ① 注册表完整性：backup_sources.DATA_LINES 每条恰好两个备用源、URL 全 https、互不重复；
  ② 切换逻辑：主源无响应 / 返回 200 但正文无效（data=null）时依次切到备用源1、备用源2，
     独立源（东财快照 / 东财日K / 新浪指数 / 新浪 7×24 / StockTwits 消息流 / Bing·Google 站内检索）
     经适配器解析成与主源相同的内部结构；三路都失败才「暂缺」，绝不编造；
  ③ 可见性：启用了哪一路记入 BACKUP_EVENTS → data["_backup_info"]["events"] → 总结「备用源」一行。
"""
import importlib.util
import re
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("requests", types.SimpleNamespace())

REPO_ROOT = Path(__file__).parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
if str(OUTPUT_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUT_DIR))

import backup_sources as bk  # noqa: E402
from octopus_quant import providers  # noqa: E402

MODULE_PATH = OUTPUT_DIR / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_data_lines_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

HKT = timezone(timedelta(hours=8))


def _strip(html):
    return unescape(re.sub(r"<[^>]+>", " ", html or ""))


def _rss(items):
    body = "".join(f"<item><title>{t}</title><link>{u}</link><pubDate>{p}</pubDate></item>"
                   for t, u, p in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'


def _rfc(dt):
    return dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


# ======================================================================
# ① 注册表
# ======================================================================
class RegistryTests(unittest.TestCase):
    def test_every_line_has_one_primary_and_two_backups(self):
        self.assertGreaterEqual(len(bk.DATA_LINES), 15)
        for lid, line in bk.DATA_LINES.items():
            with self.subTest(line=lid):
                self.assertEqual(len(line["primary"]), 2)
                self.assertEqual(len(line["backups"]), 2, f"{lid} 必须恰好两个备用源")
                urls = [line["primary"][1]] + [b[1] for b in line["backups"]]
                self.assertEqual(len(set(urls)), 3, f"{lid} 主备 URL 不得重复")
                for u in urls:
                    self.assertTrue(u.startswith("https://") or u == "{feed}", u)
                for label, _u, same in line["backups"]:
                    self.assertTrue(label)
                    self.assertIsInstance(same, bool)
                self.assertTrue(line["name"] and line["used_by"])

    def test_candidates_and_labels(self):
        cands = bk.candidates("yahoo_chart", symbol="^HSI")
        self.assertEqual([c[0].split("（")[0] for c in cands],
                         ["Yahoo Finance query1", "Yahoo Finance query2", "东方财富 行情快照"])
        self.assertEqual(cands[0][1], "https://query1.finance.yahoo.com/v8/finance/chart/^HSI")
        self.assertEqual(bk.urls("yahoo_chart", symbol="^HSI"),
                         [cands[0][1], cands[1][1]])            # 独立源不进同格式列表
        self.assertEqual(bk.label_for("yahoo_chart", cands[1][1], symbol="^HSI"), "备用源1")
        self.assertEqual(bk.label_for("yahoo_chart", cands[2][1], symbol="^HSI"), "备用源2")
        self.assertEqual(bk.label_for("yahoo_chart", cands[0][1], symbol="^HSI"), "主源")

    def test_same_format_chains_have_three_hosts(self):
        for lid in ("em_ulist", "em_clist", "em_kline", "em_datacenter", "google_news",
                    "google_news_search", "gov_policy", "youtube_feed", "tradingview", "bogleheads"):
            with self.subTest(line=lid):
                self.assertEqual(len(bk.urls(lid, symbol="x", query="q", channel_id="UC1")), 3)
        self.assertEqual(len(bk.get_eastmoney_quote_urls()), 3)
        self.assertEqual(len(bk.get_eastmoney_kline_urls()), 3)
        self.assertEqual(len(bk.get_calendar_urls()), 3)
        self.assertEqual(len(bk.get_youtube_urls("UCabc")), 3)
        self.assertEqual(bk.get_youtube_urls(""), [])
        self.assertEqual(len(bk.get_news_site_backup_urls("hket.com")), 2)
        self.assertIn("site%3Ahket.com", bk.get_news_site_backup_urls("hket.com")[0])

    def test_secid_mapping(self):
        self.assertEqual(bk.em_secid_for_yahoo("^HSI"), "100.HSI")
        self.assertEqual(bk.em_secid_for_yahoo("%5EDJI"), "100.DJIA")
        self.assertEqual(bk.em_secid_for_yahoo("0700.HK"), "116.00700")
        self.assertEqual(bk.em_secid_for_yahoo("000001.SS"), "1.000001")
        self.assertEqual(bk.em_secid_for_yahoo("399006.SZ"), "0.399006")
        self.assertEqual(bk.em_secid_for_yahoo("XYZ"), "")

    def test_describe_and_summary_cover_every_line(self):
        text = bk.describe()
        summary = bk.get_backup_summary()
        for lid, line in bk.DATA_LINES.items():
            self.assertIn(f"[{lid}]", text)
            self.assertIn(line["name"], summary)
        self.assertEqual(set(bk.ALL_BACKUP_MAP), {l["name"] for l in bk.DATA_LINES.values()})

    def test_cli_sources_prints_registry(self):
        printed = []
        with patch.object(sys, "argv", ["pipeline.py", "--sources"]), \
                patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            code = pipeline.main()
        self.assertEqual(code, 0)
        self.assertIn("每条 1 主源 + 2 备用源", "\n".join(printed))


# ======================================================================
# ② 切换逻辑
# ======================================================================
class FallbackChainTests(unittest.TestCase):
    def setUp(self):
        pipeline.BACKUP_EVENTS.clear()

    def test_invalid_body_from_primary_moves_on_to_mirror(self):
        urls = bk.get_eastmoney_quote_urls()
        seen = []

        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            seen.append(url)
            if url == urls[0]:
                return {"rc": 0, "data": None}            # 200 但没有数据
            if url == urls[1]:
                return None                              # 镜像 1 无响应
            return {"data": {"diff": [{"f12": "1"}]}}
        with patch.object(pipeline, "safe_request", side_effect=fake):
            data, served, errors = pipeline.safe_request_with_fallback(
                urls, line="em_clist",
                validate=lambda d: bool(((d or {}).get("data") or {}).get("diff")))
        self.assertEqual(served, urls[2])
        self.assertEqual(seen, urls)
        self.assertEqual(len(errors), 2)
        self.assertEqual(pipeline.BACKUP_EVENTS, [("东方财富 榜单列表（clist）", "备用源2",
                                                   "东方财富 72.push2（同格式镜像）")])
        self.assertIn("东方财富 榜单列表（clist）→备用源2（东方财富 72.push2）",
                      pipeline.backup_events_text())

    def test_primary_success_records_no_event(self):
        with patch.object(pipeline, "safe_request", return_value={"data": {"diff": [1]}}):
            _d, served, _e = pipeline.safe_request_with_fallback(
                bk.get_eastmoney_quote_urls(), line="em_clist",
                validate=lambda d: bool(d["data"]["diff"]))
        self.assertEqual(served, bk.get_eastmoney_quote_urls()[0])
        self.assertEqual(pipeline.BACKUP_EVENTS, [])

    def test_market_snapshot_falls_back_to_eastmoney_when_yahoo_hosts_fail(self):
        ts = int(datetime(2026, 9, 28, 16, 8, tzinfo=HKT).timestamp())
        rows = {"100.HSI": {"f12": "HSI", "f13": 100, "f14": "恒生指数", "f2": 24642.51, "f3": 0.54, "f124": ts},
                "1.000001": {"f12": "000001", "f13": 1, "f14": "上证指数", "f2": 3823.62, "f3": -1.67, "f124": ts},
                "100.DJIA": {"f12": "DJIA", "f13": 100, "f14": "道琼斯", "f2": 51545.0, "f3": -0.55, "f124": ts}}
        yahoo_hosts = []

        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            if "yahoo" in url:
                yahoo_hosts.append(url.split("/")[2])
                return None
            if "ulist.np" in url:
                want = params["secids"].split(",")
                self.assertIn("f13", params["fields"])
                return {"data": {"diff": [rows[s] for s in want if s in rows]}}
            return None
        with patch.object(pipeline, "safe_request", side_effect=fake):
            m = pipeline.fetch_market_snapshot()
        # 每个品种都试过 query1 + query2 两路
        self.assertEqual(set(yahoo_hosts), {"query1.finance.yahoo.com", "query2.finance.yahoo.com"})
        q = m["quotes"]
        self.assertEqual(set(q), {"恒生指数", "上证指数", "道琼斯指数"})
        self.assertEqual(q["恒生指数"]["via"], "eastmoney")
        self.assertEqual(q["恒生指数"]["as_of"], "2026-09-28")
        self.assertEqual(q["恒生指数"]["currency"], "HKD")
        self.assertEqual(q["上证指数"]["currency"], "CNY")
        self.assertEqual(q["道琼斯指数"]["currency"], "USD")
        self.assertEqual(m["served_by"]["恒生指数"], "备用源2")
        self.assertIn("来自东方财富备用源", m["source"])
        self.assertEqual(m["content_date"], "2026-09-28")
        self.assertTrue(any(e[0].startswith("实时行情") and e[1] == "备用源2" for e in pipeline.BACKUP_EVENTS))

    def test_market_snapshot_uses_query2_mirror_before_eastmoney(self):
        good = {"chart": {"result": [{
            "meta": {"currency": "HKD", "gmtoffset": 28800},
            "timestamp": [int(datetime(2026, 9, 25, 9, 30, tzinfo=HKT).timestamp()),
                          int(datetime(2026, 9, 28, 9, 30, tzinfo=HKT).timestamp())],
            "indicators": {"quote": [{"close": [24510.09, 24642.51], "volume": [1, 1]}]}}]}}
        em_called = []

        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            if "query1" in url:
                return {"chart": {"result": None, "error": {"code": "Not Found"}}}   # 200 但无效
            if "query2" in url and "HSI" in url:
                return good
            if "ulist.np" in url:
                em_called.append(params)
            return None
        with patch.object(pipeline, "safe_request", side_effect=fake):
            m = pipeline.fetch_market_snapshot()
        self.assertEqual(m["served_by"]["恒生指数"], "备用源1")
        self.assertEqual(m["quotes"]["恒生指数"]["via"], "bar")
        self.assertAlmostEqual(m["quotes"]["恒生指数"]["price"], 24642.51)
        # 其余品种才交给东财备用源2：一次批量请求（三主机依次尝试），恒指不在其中
        self.assertEqual(len({p["secids"] for p in em_called}), 1)
        self.assertEqual(len(em_called), len(bk.get_eastmoney_ulist_urls()))
        self.assertNotIn("100.HSI", em_called[0]["secids"])

    def test_panorama_indices_fall_back_to_sina(self):
        ulist = bk.urls("sina_index")
        sina = ('var hq_str_sh000001="上证指数,3888.37,3888.37,3823.62,3890,3810,0,0,804013244,'
                '804013244000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-09-28,15:00:00,00,";\n'
                'var hq_str_sz399001="深证成指,13300,13316.97,12858.75,13320,12800,0,0,1,'
                '9000000000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-09-28,15:00:00,00,";')

        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            if url == ulist[0]:
                return {"rc": 0, "data": None}
            if url == ulist[1]:
                return None
            if "hq.sinajs" in url:
                self.assertEqual(headers, bk.SINA_HQ_HEADERS)
                self.assertIn("sh000001", url)
                return sina
            return None
        with patch.object(pipeline, "safe_request", side_effect=fake):
            indices, by_code, quote_time = pipeline._fetch_panorama_indices()
        self.assertEqual([r["name"] for r in indices], ["上证指数", "深证成指"])
        self.assertAlmostEqual(indices[0]["price"], 3823.62)
        self.assertAlmostEqual(indices[0]["chg_pct"], -1.67, places=2)
        self.assertAlmostEqual(indices[0]["amount"], 804013244000.0)
        self.assertIsNone(by_code["000001"]["up"])            # 新浪没有涨跌家数 → 不编
        self.assertEqual(quote_time, "2026-09-28 15:00:00")
        self.assertTrue(any(e[0].startswith("A股宽基指数") and e[1] == "备用源2" for e in pipeline.BACKUP_EVENTS))
        with patch.object(pipeline, "safe_request", side_effect=fake):
            pan = pipeline.fetch_market_panorama()
        self.assertEqual(pan["status"], "success")
        self.assertIsNone(pan["breadth"])
        self.assertTrue(pan["partial"])
        self.assertEqual(pan["content_date"], "2026-09-28")

    def test_eastmoney_news_falls_back_to_sina_live(self):
        em_hosts = []

        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            if "eastmoney" in url:
                em_hosts.append(url.split("/")[2])
                return {"data": {"list": []}}                   # 200 但空列表
            if "zhibo.sina" in url:
                return {"result": {"data": {"feed": {"list": [
                    {"rich_text": "【央行开展逆回购】央行今日开展2000亿元逆回购操作。",
                     "create_time": "2026-09-29 09:20:00", "docurl": "https://finance.sina.com.cn/x.html"},
                    {"rich_text": "港股高开，恒指涨0.6%", "create_time": "2026-09-29 09:21:00"},
                ]}}}}
            return None
        with patch.object(pipeline, "safe_request", side_effect=fake):
            res = pipeline.fetch_eastmoney_news()
        self.assertEqual(em_hosts, ["np-weblist.eastmoney.com", "np-listapi.eastmoney.com"])
        self.assertEqual(res["status"], "success")
        self.assertIn("新浪财经 7×24", res["source"])
        self.assertEqual(res["headlines"][0]["title"], "【央行开展逆回购】央行今日开展2000亿元逆回购操作。")
        self.assertEqual(res["headlines"][1]["url"], "https://finance.sina.com.cn/7x24/")
        self.assertEqual(res["content_date"], "2026-09-29")
        self.assertTrue(any(e[0] == "东方财富 快讯" and e[1] == "备用源2" for e in pipeline.BACKUP_EVENTS))

    def test_eastmoney_news_all_three_fail_is_unavailable(self):
        with patch.object(pipeline, "safe_request", return_value=None):
            res = pipeline.fetch_eastmoney_news()
        self.assertEqual(res["status"], "unavailable")
        self.assertEqual(res["source"], "东方财富")

    def test_stocktwits_stream_adapter_and_fallback(self):
        stream = {"messages": [
            {"symbols": [{"symbol": "NVDA", "title": "NVIDIA", "watchlist_count": 900}]},
            {"symbols": [{"symbol": "NVDA", "title": "NVIDIA", "watchlist_count": 900},
                         {"symbol": "TSLA", "title": "Tesla", "watchlist_count": 800}]},
        ]}
        ranked = pipeline._stocktwits_symbols_from_stream(stream)
        self.assertEqual([(r["symbol"], r["rank"], r["trending_score"]) for r in ranked],
                         [("NVDA", 1, 2), ("TSLA", 2, 1)])

        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            if "trending/symbols" in url:
                return None
            if "streams/trending" in url:
                return stream
            return None
        with patch.object(pipeline, "safe_request", side_effect=fake):
            res = pipeline.fetch_stocktwits()
        self.assertEqual(res["status"], "success")
        self.assertEqual([it["symbol"] for it in res["items"]], ["NVDA", "TSLA"])
        self.assertTrue(any(e[0].endswith("StockTwits 趋势榜") and e[1] == "备用源2" for e in pipeline.BACKUP_EVENTS))

    def test_hk_news_source_falls_back_to_site_search_feeds(self):
        srcs = pipeline.HK_NEWS_SOURCES
        now = datetime.now(pipeline.CST)
        fresh = _rfc(now - timedelta(hours=2))
        host1 = pipeline._hk_news_site_host(srcs[1])
        bing_url, google_url = bk.get_news_site_backup_urls(host1)
        host0 = pipeline._hk_news_site_host(srcs[0])
        _bing0, google0 = bk.get_news_site_backup_urls(host0)
        feeds = {
            # 源0：官方 + Bing 都挂 → Google News 站内检索（跳转链接放行、去掉「 - 媒体名」）
            google0: _rss([("港股反弹，恒指收复25000点 - 香港电台",
                            "https://news.google.com/rss/articles/abc", fresh)]),
            # 源1：官方挂 → Bing 站内检索（链接直达原文，白名单照常）
            bing_url: _rss([("港股通ETF获大额净买入，恒指升1%", "https://www.hket.com/article/1/a.html", fresh),
                            ("外站注入", "https://evil.example.com/x", fresh)]),
        }
        calls = []

        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            calls.append(url)
            return feeds.get(url)
        with patch.object(pipeline, "safe_request", side_effect=fake):
            res = pipeline.fetch_hk_news_sources()
        recs = {r["name"]: r for r in res["sources"]}
        r0, r1 = recs[srcs[0]["name"]], recs[srcs[1]["name"]]
        self.assertEqual(r1["status"], "ok")
        self.assertEqual(r1["served_by"], "备用源")
        self.assertEqual([it["url"] for it in r1["items"]], ["https://www.hket.com/article/1/a.html"])
        self.assertIn("Bing", r1["note"])
        self.assertEqual(r0["status"], "ok")
        self.assertEqual(r0["items"][0]["title"], "港股反弹，恒指收复25000点")
        self.assertEqual(r0["items"][0]["url"], "https://news.google.com/rss/articles/abc")
        self.assertIn("Google News", r0["note"])
        # 每个源头都按 主源 → Bing → Google 的顺序尝试
        self.assertEqual(calls.index(srcs[1]["feed"]) < calls.index(bing_url), True)
        self.assertNotIn(google_url, calls)                   # Bing 成功后不再试 Google
        self.assertTrue(any(e[0].startswith("港股新闻源头") for e in pipeline.BACKUP_EVENTS))

    def test_providers_fetch_bars_chain(self):
        good = {"chart": {"result": [{
            "meta": {"currency": "HKD", "gmtoffset": 28800},
            "timestamp": [int(datetime(2026, 9, 25, 9, 30, tzinfo=HKT).timestamp())],
            "indicators": {"quote": [{"close": [24510.09], "volume": [1]}]}}]}}
        seen = []

        def fj_mirror(url, params=None, timeout=15):
            seen.append(url)
            if "query1" in url:
                return {"chart": {"result": None}}
            if "query2" in url:
                return good
            return None
        bars = providers.fetch_bars(fj_mirror, "^HSI", rng="1y")
        self.assertEqual(bars[-1]["close"], 24510.09)
        self.assertEqual(len(seen), 2)

        def fj_em(url, params=None, timeout=15):
            if "push2his" in url:
                self.assertEqual(params["secid"], "116.00700")
                self.assertEqual(params["lmt"], "520")
                return {"data": {"klines": ["2026-09-25,600,610.5,612,598,1000,1e9",
                                            "2026-09-28,611,615.0,620,605,1200,1.2e9"]}}
            return None
        bars = providers.fetch_bars(fj_em, "0700.HK", rng="2y")
        self.assertEqual([(b["date"], b["close"], b["open"]) for b in bars],
                         [("2026-09-25", 610.5, 600.0), ("2026-09-28", 615.0, 611.0)])
        self.assertTrue(bars[0]["from_eastmoney"])
        self.assertEqual(providers.fetch_bars(lambda *a, **k: None, "ZZZ"), [])   # 映射不到 → 空
        self.assertEqual(len(providers.chain_urls("em_kline")), 3)

    def test_providers_eastmoney_helpers_try_mirrors(self):
        urls_seen = []

        def fj(url, params=None, timeout=15):
            urls_seen.append(url)
            if url.startswith("https://push2.eastmoney.com"):
                return {"data": None}
            if "82.push2" in url:
                return {"data": {"diff": [{"f12": "HSI", "f14": "恒生指数", "f2": 24642.51,
                                           "f3": 0.54, "f6": 1e11, "f124": "-"}]}}
            return None
        out = providers.fetch_hk_index_quotes(fj)
        self.assertAlmostEqual(out["HSI"]["price"], 24642.51)
        # 第一批（主域名 + 82 镜像）已是 2 次；恒科缺行 → 用兜底编号 100.HSTECH 再补一批。
        self.assertEqual(len(urls_seen), 4)

    def test_hk_index_quotes_retry_only_missing_symbol_with_alternate_secid(self):
        batches = []

        def fj(url, params=None, timeout=15):
            if "push2" not in url:
                return None
            secids = (params or {}).get("secids", "").split(",")
            batches.append(secids)
            if "124.HSTECH" in secids:                 # 现行恒科编号：一次拿全
                return {"data": {"diff": [
                    {"f12": "HSI", "f14": "恒生指数", "f2": 24642.51, "f3": 0.54, "f6": 1e11, "f124": 1790000000},
                    {"f12": "HSTECH", "f14": "恒生科技指数", "f2": 3936.02, "f3": 1.77, "f6": 5e10, "f124": 1790000000},
                    {"f12": "HSCEI", "f14": "国企指数", "f2": 8057.59, "f3": 1.44, "f6": 6e10, "f124": 1790000000}]}}
            return {"rc": 102, "data": None}           # 失效编号 → 整批 rc:102
        out = providers.fetch_hk_index_quotes(fj)
        self.assertEqual(batches, [["100.HSI", "124.HSTECH", "100.HSCEI"]])
        self.assertEqual(sorted(out), ["HSCEI", "HSI", "HSTECH"])
        self.assertAlmostEqual(out["HSTECH"]["price"], 3936.02)

# ======================================================================
# ③ 可见性
# ======================================================================
class VisibilityTests(unittest.TestCase):
    def test_summary_lists_backup_events(self):
        events = [("东方财富 快讯", "备用源2", "新浪财经 7×24 快讯（独立源）"),
                  ("实时行情 · Yahoo 日线快照", "备用源1", "Yahoo Finance query2（同格式镜像）")]
        pairs = dict(pipeline._summary_pairs(None, None, None, [], 0, 0, backup_events=events))
        self.assertIn("备用源", pairs)
        self.assertIn("东方财富 快讯→备用源2（新浪财经 7×24 快讯）", pairs["备用源"])
        self.assertIn("实时行情 · Yahoo 日线快照→备用源1（Yahoo Finance query2）", pairs["备用源"])
        pairs = dict(pipeline._summary_pairs(None, None, None, [], 0, 0, backup_events=[]))
        self.assertNotIn("备用源", pairs)

    def test_report_shows_backup_row_in_summary(self):
        data = {"_backup_info": {"events": [("东方财富 快讯", "备用源2", "新浪财经 7×24 快讯（独立源）")]}}
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(data, "2026年9月29日 · 周二", "20260929", theme=theme)
            text = _strip(html)
            self.assertIn("备用源", text)
            self.assertIn("东方财富 快讯→备用源2（新浪财经 7×24 快讯）", text)

    def test_collect_all_data_resets_and_exports_events(self):
        stub = pipeline._source_result("x", "unavailable", error="stub")
        names = [n for n in dir(pipeline) if n.startswith("fetch_")]
        patches = [patch.object(pipeline, n, return_value=({} if n == "fetch_public_sites" else stub))
                   for n in names]
        pipeline.BACKUP_EVENTS.append(("旧记录", "备用源1", ""))
        with patch.object(pipeline, "_fetch_hk_index_reference", return_value={}), \
                patch.object(pipeline.time, "sleep", return_value=None):
            for p in patches:
                p.start()
            try:
                data = pipeline.collect_all_data()
            finally:
                for p in patches:
                    p.stop()
        self.assertEqual(data["_backup_info"]["events"], [])       # 每次运行重新计数
        self.assertEqual(data["_backup_info"]["lines"], len(bk.DATA_LINES))


if __name__ == "__main__":
    unittest.main()
