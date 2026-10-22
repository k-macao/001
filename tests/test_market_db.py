"""🗄️ 市场数据库（隐藏功能）回归测试 —— 全部离线，不发任何网络请求。

覆盖五件事：
  ① 多源契约：源头 >3（6 路，其中 5 路参与比价）、每路可换镜像、代码映射正确、
     单只标的异常不拖垮整路源、单路全失败只记 failed；
  ⑤ 通达信通道（mootdx）：代码映射只认沪深、未装 mootdx / 连不上就明确降级、
     注入假客户端时行情 / 日K / 财务 / 除权除息全通、17:00 档才附带财务、
  ② 交叉验证：一致 / 离群 / 滞后 / 冲突 / 孤证五种判定，共识价只用可信源；
  ③ 自我检查：源覆盖、标的覆盖、数值合理性、跨时段与跨日跳变、非交易日不误判；
  ④ 落库与 AI 数据集：日期命名文件、同日三档合并、同档重拉覆盖留痕、哈希防改写、
     特征只用过去（截断不变性）、标签只用未来、jsonl / csv 导出、ai_context 新鲜度。

网络层用 FixtureHttp 注入（与 octopus_quant 的 fetch_json 注入同一思路），
因此本测试可在无网络环境下完整跑通。
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.modules.setdefault("requests", types.SimpleNamespace())

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")
if OUTPUT_DIR not in sys.path:
    sys.path.insert(0, OUTPUT_DIR)

import market_db as m  # noqa: E402

# 测试全程离线（见模块 docstring）：装了 mootdx 的环境里，通达信通道默认**关掉**
# （老用例只测其它 5 路），配置写进临时目录、主站指向必然拒绝连接的本机端口 ——
# 不碰真实主站，也不碰真实 $HOME。要验通达信通道的用例自己注入假客户端
# （防卡死用例注入 connector / factory），`TdxPullIntegrationTests` 会显式把开关打开。
os.environ.setdefault("OCTOPUS_DB_TDX", "0")
os.environ.setdefault("OCTOPUS_DB_TDX_SERVERS", "127.0.0.1:1")
os.environ.setdefault("OCTOPUS_DB_TDX_CONFIG",
                      os.path.join(tempfile.gettempdir(), "octopus_tdx_test_config.json"))

CST = timezone(timedelta(hours=8))
DAY1 = datetime(2026, 10, 1, 8, 0, 12, tzinfo=CST)      # 周四
DAY2 = datetime(2026, 10, 2, 12, 30, 20, tzinfo=CST)    # 周五
SATURDAY = datetime(2026, 10, 3, 12, 30, 5, tzinfo=CST)

SYMBOLS = ["^HSI", "0700.HK", "000001.SS", "MSFT"]
PRICES = {"^HSI": 26123.4, "0700.HK": 629.5, "000001.SS": 3842.19, "MSFT": 512.3}
PREV = {"^HSI": 26016.0, "0700.HK": 625.6, "000001.SS": 3830.3, "MSFT": 513.3}


def stamp(moment: datetime) -> int:
    return int(moment.timestamp())


TDX_PRICES = {"600519.SS": 1690.0, "000001.SS": 3842.19}
TDX_PREV = {"600519.SS": 1680.5, "000001.SS": 3830.3}
TDX_MAP = {"sh600519": "600519.SS", "sh000001": "000001.SS", "sz300750": "300750.SZ"}


class FakeTdxClient:
    """假的 mootdx StdQuotes：返回纯 Python dict 列表（不依赖 pandas / 网络）。"""

    def __init__(self, prices=None, prev=None, *, quote_time="14:59:58", boom=(), empty=()):
        self.prices = dict(prices or TDX_PRICES)
        self.prev = dict(prev or TDX_PREV)
        self.quote_time = quote_time
        self.boom = set(boom)
        self.empty = set(empty)

    @staticmethod
    def _bare(symbol):
        return symbol[2:] if symbol[:2] in ("sh", "sz") else symbol

    def quotes(self, symbol):
        if "quotes" in self.boom:
            raise RuntimeError("主站断开")
        rows = []
        for code in symbol or []:
            sym = TDX_MAP.get(code)
            if not sym or sym in self.empty or sym not in self.prices:
                continue
            value = self.prices[sym]
            rows.append({"market": 1 if code.startswith("sh") else 0, "code": self._bare(code),
                         "price": value, "last_close": self.prev.get(sym),
                         "open": round(value * 0.999, 3), "high": round(value * 1.01, 3),
                         "low": round(value * 0.99, 3), "vol": 12345, "amount": 6.7e8,
                         "servertime": self.quote_time})
        return rows

    def bars(self, symbol, frequency=9, offset=800):
        if "bars" in self.boom:
            raise RuntimeError("K 线主站断开")
        sym = TDX_MAP.get(symbol)
        if not sym or sym in self.empty:
            return []
        close = self.prev.get(sym) or self.prices[sym]
        return [{"open": close, "close": close, "high": close, "low": close, "vol": 1000.0,
                 "amount": 1.0e7, "year": 2026, "month": 9, "day": 30, "hour": 15, "minute": 0,
                 "datetime": "2026-09-30 15:00:00"}]

    def finance(self, symbol):
        if "finance" in self.boom:
            raise RuntimeError("财务主站断开")
        sym = TDX_MAP.get(symbol)
        if not sym or sym in self.empty:
            return []
        return [{"code": self._bare(symbol), "updated_date": 20260630, "ipo_date": 20010827,
                 "zongguben": 1.2e9, "liutongguben": 1.0e9, "jinglirun": 5.4e10,
                 "meigujingzichan": 160.0, "industry": "白酒"}]

    def xdxr(self, symbol):
        if "xdxr" in self.boom:
            raise RuntimeError("除权除息主站断开")
        sym = TDX_MAP.get(symbol)
        if not sym or sym in self.empty:
            return []
        return [{"year": 2026, "month": 9, "day": 30, "category": 1, "name": "除权除息",
                 "fenhong": 25.9, "songzhuangu": 0.0, "peigu": 0.0, "peigujia": 0.0},
                {"year": 2025, "month": 6, "day": 20, "category": 1, "name": "除权除息",
                 "fenhong": 23.8, "songzhuangu": 0.0, "peigu": 0.0, "peigujia": 0.0}]


def _em_payload(prices, prev, deviate, when):
    diff = []
    for sym, price in prices.items():
        secid = m.em_secid(sym)
        if not secid:
            continue
        market, code = secid.split(".", 1)
        value = round(price * deviate.get(sym, 1.0), 4)
        diff.append({"f2": value, "f3": 0.5, "f4": 0.1, "f5": 10000, "f6": 1.2e8,
                     "f12": code, "f13": int(market) if market.isdigit() else market, "f14": sym,
                     "f15": round(value * 1.01, 4), "f16": round(value * 0.99, 4),
                     "f17": round(value * 0.995, 4), "f18": prev.get(sym), "f124": stamp(when)})
    return {"data": {"diff": diff}}


def _sina_payload(prices, prev, deviate, when):
    lines = []
    for sym, price in prices.items():
        code = m.sina_code(sym)
        if not code:
            continue
        value = round(price * deviate.get(sym, 1.0), 4)
        date_str, clock = when.strftime("%Y-%m-%d"), when.strftime("%H:%M:%S")
        prev_close = prev.get(sym)
        if code.startswith("hk"):
            parts = [sym, sym, f"{value*0.999:.3f}", f"{prev_close:.3f}", f"{value*1.01:.3f}",
                     f"{value*0.99:.3f}", f"{value:.3f}", "3.900", "0.623"] + ["0"] * 20 + [date_str, clock]
        else:
            parts = [sym, f"{value*0.999:.3f}", f"{prev_close:.3f}", f"{value:.3f}",
                     f"{value*1.01:.3f}", f"{value*0.99:.3f}", "0", "0", "1000", "1.2e8"] \
                + ["0"] * 20 + [date_str, clock]
        lines.append(f'var hq_str_{code}="' + ",".join(parts) + '";')
    return "\n".join(lines)


def _tencent_payload(prices, prev, deviate, when):
    lines = []
    for sym, price in prices.items():
        code = m.tencent_code(sym)
        if not code:
            continue
        value = round(price * deviate.get(sym, 1.0), 4)
        parts = [""] * 40
        parts[1], parts[2] = sym, code
        parts[3], parts[4], parts[5] = f"{value:.3f}", f"{prev.get(sym):.3f}", f"{value*0.999:.3f}"
        parts[30] = when.strftime("%Y%m%d%H%M%S")
        parts[33], parts[34], parts[37] = f"{value*1.01:.3f}", f"{value*0.99:.3f}", "1.2e8"
        lines.append(f'v_{code}="' + "~".join(parts) + '";')
    return "\n".join(lines)


def _yahoo_payload(sym, prices, prev, deviate, when):
    value = round(prices[sym] * deviate.get(sym, 1.0), 4)
    return {"chart": {"result": [{"meta": {
        "regularMarketPrice": value, "chartPreviousClose": prev.get(sym),
        "regularMarketTime": stamp(when), "regularMarketDayHigh": round(value * 1.01, 4),
        "regularMarketDayLow": round(value * 0.99, 4), "regularMarketOpen": round(value * 0.998, 4),
        "regularMarketVolume": 10000, "shortName": sym}}]}}


class FixtureHttp:
    """按 URL 路由的假 HTTP：可模拟单源失败、滞后时间、单源偏离、单只抛异常。"""

    def __init__(self, prices=None, prev=None, *, fail=(), lag_minutes=None, deviate=None,
                 when=None, raise_for=()):
        self.prices = dict(prices or PRICES)
        self.prev = dict(prev or PREV)
        self.fail = set(fail)
        self.lag_minutes = dict(lag_minutes or {})
        self.deviate = {k: dict(v) for k, v in (deviate or {}).items()}
        self.when = when or DAY1
        self.raise_for = set(raise_for)
        self.calls = []

    def _moment(self, source):
        return self.when - timedelta(minutes=self.lag_minutes.get(source, 0))

    def get(self, url, headers=None, timeout=None, is_text=False):
        self.calls.append(url)
        if "ulist.np" in url:
            source = "eastmoney"
            if source in self.fail:
                return None, "模拟失败"
            return _em_payload(self.prices, self.prev, self.deviate.get(source, {}),
                               self._moment(source)), None
        if "hq.sinajs" in url:
            source = "sina"
            if source in self.fail:
                return None, "模拟失败"
            return _sina_payload(self.prices, self.prev, self.deviate.get(source, {}),
                                 self._moment(source)), None
        if "qt.gtimg" in url:
            source = "tencent"
            if source in self.fail:
                return None, "模拟失败"
            return _tencent_payload(self.prices, self.prev, self.deviate.get(source, {}),
                                    self._moment(source)), None
        if "finance.yahoo.com" in url:
            source = "yahoo"
            sym = url.split("/chart/")[1].split("?")[0]
            if source in self.fail or sym in self.raise_for:
                return None, "模拟失败"
            if sym not in self.prices:
                return None, "无此标的"
            return _yahoo_payload(sym, self.prices, self.prev, self.deviate.get(source, {}),
                                  self._moment(source)), None
        if "kline/get" in url:
            if "em_kline" in self.fail:
                return None, "模拟失败"
            from urllib.parse import parse_qs, urlparse
            secid = parse_qs(urlparse(url).query).get("secid", [""])[0]
            sym = next((s for s in self.prices if m.em_secid(s) == secid), None)
            if not sym:
                return None, "无此标的"
            return {"data": {"klines": [f"2026-09-30,{self.prev[sym]*0.999:.2f},"
                                        f"{self.prev[sym]:.2f},{self.prev[sym]*1.01:.2f},"
                                        f"{self.prev[sym]*0.99:.2f},10000,1.2e8"]}}, None
        return None, "无路由"


class TempRootCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="octopus_db_test_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def pull(self, http=None, slot="0800", now=DAY1, **kw):
        return m.pull(slot, root=self.root, http=http or FixtureHttp(), now=now,
                      symbols=SYMBOLS, verbose=False, **kw)


# ======================================================================
# ① 注册表与代码映射
# ======================================================================
class RegistryTests(unittest.TestCase):
    def test_more_than_three_sources_and_price_peers(self):
        """源头 >3：注册表至少 4 路，其中至少 4 路参与比价。"""
        self.assertGreaterEqual(len(m.SOURCES), 4)
        self.assertGreaterEqual(sum(1 for s in m.SOURCES.values() if s["price_peer"]), 4)
        for key, spec in m.SOURCES.items():
            with self.subTest(source=key):
                self.assertTrue(spec["hosts"])
                self.assertTrue(all(host and "/" not in host for host in spec["hosts"]))
                self.assertTrue(spec["label"])

    def test_hosts_are_mirror_sets(self):
        self.assertGreaterEqual(len(m.SOURCES["eastmoney"]["hosts"]), 2)
        self.assertGreaterEqual(len(m.SOURCES["yahoo"]["hosts"]), 2)
        self.assertGreaterEqual(len(m.SOURCES["em_kline"]["hosts"]), 2)

    def test_code_mappings(self):
        self.assertEqual(m.em_secid("0700.HK"), "116.00700")
        self.assertEqual(m.em_secid("^HSI"), "100.HSI")
        self.assertEqual(m.em_secid("000001.SS"), "1.000001")
        self.assertEqual(m.em_secid("399006.SZ"), "0.399006")
        self.assertEqual(m.em_secid("MSFT"), "105.MSFT")
        self.assertEqual(m.sina_code("0700.HK"), "hk00700")
        self.assertEqual(m.sina_code("^HSTECH"), "hkHSTECH")
        self.assertEqual(m.sina_code("000001.SS"), "sh000001")
        self.assertEqual(m.sina_code("MSFT"), "")            # 新浪美股字段口径不同，不纳入
        self.assertEqual(m.tencent_code("0700.HK"), "hk00700")
        self.assertEqual(m.tencent_code("MSFT"), "usMSFT")

    def test_universe_covers_hk_and_more(self):
        codes = [code for _n, code, _mk in m.symbol_universe()]
        self.assertIn("^HSI", codes)
        self.assertIn("0700.HK", codes)
        self.assertGreaterEqual(len(codes), 20)
        self.assertEqual(len(codes), len(set(codes)))         # 不重复
        self.assertEqual(m.market_of("0700.HK"), "HK")
        self.assertEqual(m.market_of("^GSPC"), "US")
        self.assertEqual(m.market_of("000001.SS"), "A")

    def test_slots_and_schedule(self):
        self.assertEqual(m.SLOTS, ("0800", "1230", "1700"))
        self.assertEqual(m.scheduled_at("2026-10-01", "1230"), "2026-10-01 12:30:00")
        self.assertEqual(m.resolve_slot("auto", datetime(2026, 10, 1, 8, 2, tzinfo=CST)), "0800")
        self.assertEqual(m.resolve_slot("auto", datetime(2026, 10, 1, 12, 30, tzinfo=CST)), "1230")
        self.assertEqual(m.resolve_slot("auto", datetime(2026, 10, 1, 17, 1, tzinfo=CST)), "1700")
        self.assertEqual(m.resolve_slot("auto", datetime(2026, 10, 1, 21, 0, tzinfo=CST)), "1700")
        self.assertEqual(m.resolve_slot("auto", datetime(2026, 10, 1, 3, 0, tzinfo=CST)), "0800")


# ======================================================================
# ② 各源适配器
# ======================================================================
class AdapterTests(unittest.TestCase):
    def test_parse_sina_a_and_hk(self):
        rows = {}
        text = _sina_payload(PRICES, PREV, {}, DAY1)
        for match in __import__("re").finditer(r'hq_str_(\w+)="([^"]*)"', text):
            rows[match.group(1)] = m._parse_sina_line(match.group(1), match.group(2))
        self.assertAlmostEqual(rows["hk00700"]["price"], PRICES["0700.HK"], places=3)
        self.assertEqual(rows["hk00700"]["prev_close"], PREV["0700.HK"])
        self.assertTrue(rows["hk00700"]["quote_time"].startswith("2026-10-01"))
        self.assertAlmostEqual(rows["sh000001"]["price"], PRICES["000001.SS"], places=3)
        self.assertEqual(rows["sh000001"]["name"], "000001.SS")

    def test_parse_tencent_and_yahoo_and_kline(self):
        text = _tencent_payload(PRICES, PREV, {}, DAY1)
        payload = text.split('"')[1]
        row = m._parse_tencent_line(payload)
        self.assertAlmostEqual(row["price"], PRICES["^HSI"], places=3)
        self.assertEqual(row["quote_time"], "2026-10-01 08:00:12")
        yahoo = m._yahoo_quote_from_chart(_yahoo_payload("MSFT", PRICES, PREV, {}, DAY1))
        self.assertAlmostEqual(yahoo["price"], PRICES["MSFT"], places=3)
        self.assertIsNone(m._yahoo_quote_from_chart({"chart": {"result": []}}))
        kline = m._em_kline_last_close({"data": {"klines": ["2026-09-30,1,2,3,0.5,7,8"]}})
        self.assertEqual(kline["close"], 2.0)
        self.assertEqual(kline["date"], "2026-09-30")
        self.assertIsNone(m._em_kline_last_close({"data": {}}))

    def test_invalid_payload_marks_source_failed(self):
        class Empty(FixtureHttp):
            def get(self, url, headers=None, timeout=None, is_text=False):
                if "ulist.np" in url:
                    return {"data": {"diff": []}}, None
                return super().get(url, headers=headers, timeout=timeout, is_text=is_text)

        result = m.fetch_eastmoney(SYMBOLS, Empty())
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["error"])

    def test_one_bad_symbol_does_not_break_yahoo_source(self):
        http = FixtureHttp(raise_for={"000001.SS"})
        result = m.fetch_yahoo(SYMBOLS, http)
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("000001.SS", result["quotes"])
        self.assertIn("0700.HK", result["quotes"])

    def test_all_sources_cover_quotes_for_universe(self):
        http = FixtureHttp()
        for key, fetcher in m.FETCHERS.items():
            with self.subTest(source=key):
                # 通达信通道不是 HTTP 源：注入假客户端（真实场景连 mootdx 主站池）
                extra = {"client": FakeTdxClient()} if key == "tdx" else {}
                result = fetcher(SYMBOLS, http, **extra)
                self.assertEqual(result["status"], "ok")
                self.assertTrue(result["quotes"])
                self.assertEqual(result["key"], key)
                if key == "tdx":       # 通达信只有沪深
                    self.assertNotIn("0700.HK", result["quotes"])


# ======================================================================
# ③ 交叉验证
# ======================================================================
class CrossValidateTests(unittest.TestCase):
    def _by_source(self, price=100.0, **overrides):
        out = {}
        for key in ("eastmoney", "sina", "tencent", "yahoo"):
            value = overrides.get(key, price)
            out[key] = {"price": value, "prev_close": 99.0, "quote_time": "2026-10-01 12:30:00",
                        "name": key, "open": None, "high": None, "low": None, "volume": None,
                        "amount": None, "change_pct": None}
        return out

    def test_agree_high_confidence(self):
        res = m.cross_validate("0700.HK", self._by_source())
        self.assertEqual(res["verdict"], "一致")
        self.assertEqual(res["confidence"], m.CONF_HIGH)
        self.assertEqual(res["n_agree"], 4)
        self.assertAlmostEqual(res["price"], 100.0, places=6)
        self.assertEqual(res["outliers"], [])

    def test_outlier_flagged_and_excluded(self):
        res = m.cross_validate("0700.HK", self._by_source(yahoo=103.0))
        self.assertIn("yahoo", res["outliers"])
        self.assertTrue(res["by_source"]["yahoo"]["outlier"])
        self.assertEqual(res["verdict"], "一致")
        self.assertAlmostEqual(res["price"], 100.0, places=6)     # 共识价不含离群源

    def test_lagged_source_flagged(self):
        by_source = self._by_source()
        by_source["yahoo"]["quote_time"] = "2026-10-01 11:30:00"   # 落后 60 分钟
        res = m.cross_validate("0700.HK", by_source)
        self.assertIn("yahoo", res["lagged"])
        self.assertTrue(res["by_source"]["yahoo"]["lagged"])
        self.assertEqual(res["n_agree"], 4)                        # 滞后源仍参与一致性统计

    def test_conflict_verdict(self):
        res = m.cross_validate("0700.HK", {"eastmoney": self._by_source()["eastmoney"],
                                           "sina": dict(self._by_source()["sina"], price=106.0)})
        self.assertEqual(res["verdict"], "冲突")
        self.assertEqual(res["confidence"], m.CONF_LOW)
        self.assertGreater(res["spread_pct"], m.CONFLICT_PCT)

    def test_single_source_is_single_evidence(self):
        res = m.cross_validate("0700.HK", {"eastmoney": self._by_source()["eastmoney"]})
        self.assertEqual(res["verdict"], "孤证")
        self.assertEqual(res["confidence"], m.CONF_SINGLE)

    def test_eod_close_cross_check(self):
        res = m.cross_validate("0700.HK", self._by_source(),
                               eod_close={"close": 99.05, "date": "2026-09-30"})
        check = res["eod_close_check"]
        self.assertTrue(check["ok"])
        self.assertLess(check["dev_pct"], m.SOFT_TOL_PCT)

    def test_non_peer_source_excluded_from_price_consensus(self):
        by_source = self._by_source()
        by_source["em_kline"] = {"close": 12.0, "date": "2026-09-30"}
        res = m.cross_validate("0700.HK", by_source)
        self.assertAlmostEqual(res["price"], 100.0, places=6)
        self.assertNotIn("em_kline", res["sources"])


# ======================================================================
# ④ 自我检查
# ======================================================================
class SelfCheckTests(TempRootCase):
    def test_clean_slot_scores_full(self):
        result = self.pull(slot="1230", now=DAY1.replace(hour=12, minute=30, second=12))
        slot = result["doc"]["slots"]["1230"]
        self.assertEqual(slot["self_check"]["score"], 100)
        self.assertTrue(slot["self_check"]["ok"])
        self.assertEqual(slot["cross_check"]["sources_ok"], 5)
        self.assertEqual(slot["cross_check"]["symbols_ok"], len(SYMBOLS))
        self.assertEqual(slot["cross_check"]["agreement_rate"], 1.0)

    def test_source_shortage_and_coverage_penalised(self):
        result = self.pull(http=FixtureHttp(fail={"sina", "tencent"}))
        check = {c["name"]: c for c in result["self_check"]["checks"]}
        self.assertFalse(check["sources_min"]["ok"])
        self.assertLess(result["self_check"]["score"], 100)
        self.assertFalse(result["self_check"]["ok"])

    def test_low_symbol_coverage_penalised(self):
        http = FixtureHttp(prices={"^HSI": PRICES["^HSI"]}, prev={"^HSI": PREV["^HSI"]})
        result = m.pull("1230", root=self.root, http=http, now=DAY1,
                        symbols=SYMBOLS, verbose=False)      # 只有 1 只标的能取到
        check = {c["name"]: c for c in result["self_check"]["checks"]}
        self.assertFalse(check["symbol_coverage"]["ok"])

    def test_numeric_sanity_flags_wild_change(self):
        bad_prev = {"^HSI": PRICES["^HSI"] / 1.6, "0700.HK": PREV["0700.HK"],
                    "000001.SS": PREV["000001.SS"], "MSFT": PREV["MSFT"]}
        result = self.pull(http=FixtureHttp(prev=bad_prev))
        check = {c["name"]: c for c in result["self_check"]["checks"]}
        self.assertFalse(check["numeric_sanity"]["ok"])

    def test_slot_jump_alert_across_slots(self):
        self.pull(slot="0800", now=DAY1, http=FixtureHttp())
        jumped = {k: v * 1.2 for k, v in PRICES.items()}
        result = self.pull(slot="1230", now=DAY1,
                           http=FixtureHttp(prices=jumped, prev=PRICES))
        alerts = " ".join(result["self_check"]["alerts"])
        self.assertIn("跨时段跳变", alerts)

    def test_weekend_freshness_not_penalised(self):
        result = self.pull(now=SATURDAY)
        check = {c["name"]: c for c in result["self_check"]["checks"]}
        self.assertTrue(check["freshness"]["ok"])            # 休市不算缺陷
        self.assertTrue(check["freshness"]["warn_only"])
        self.assertIn("非交易日", check["freshness"]["detail"])
        self.assertFalse(result["doc"]["slots"]["0800"]["trading_day"])

    def test_stale_quotes_alert_on_trading_day(self):
        # 行情时间停在昨天：节假日 / 盘前都会出现隔夜价，因此只亮灯扣分、不判「缺陷」
        stale = FixtureHttp(when=datetime(2026, 9, 30, 12, 0, tzinfo=CST))
        result = self.pull(http=stale)
        check = {c["name"]: c for c in result["self_check"]["checks"]}
        self.assertFalse(check["freshness"]["ok"])
        self.assertTrue(check["freshness"]["warn_only"])
        self.assertIn("可能休市或源延迟", check["freshness"]["detail"])
        self.assertLess(result["self_check"]["score"], 100)
        self.assertTrue(any("freshness" in a for a in result["self_check"]["alerts"]))
        self.assertTrue(result["doc"]["slots"]["0800"]["trading_day"])


# ======================================================================
# ⑤ 落库 / 文件 / 哈希
# ======================================================================
class DatabaseFileTests(TempRootCase):
    def test_file_named_by_date_and_three_slots_merged(self):
        for slot, moment in (("0800", DAY1), ("1230", DAY1),
                             ("1700", DAY1.replace(hour=17, minute=0))):
            self.pull(slot=slot, now=moment)
        path = os.path.join(self.root, "20261001.json")
        self.assertTrue(os.path.isfile(path))
        doc = json.load(open(path, encoding="utf-8"))
        self.assertEqual(list(doc["slots"]), ["0800", "1230", "1700"])
        self.assertEqual(doc["schema"], m.SCHEMA)
        self.assertEqual(doc["audit"]["pull_count"], 3)
        self.assertEqual(doc["ai"]["slots_present"], ["0800", "1230", "1700"])
        self.assertGreater(doc["ai"]["row_count"], 0)

    def test_repull_same_slot_overwrites_and_audits(self):
        self.pull(slot="1230", now=DAY1)
        self.pull(slot="1230", now=DAY1.replace(minute=31))
        doc = json.load(open(os.path.join(self.root, "20261001.json"), encoding="utf-8"))
        self.assertEqual(list(doc["slots"]), ["1230"])
        self.assertEqual(doc["audit"]["pull_count"], 2)
        self.assertFalse(doc["audit"]["pulls"][0]["overwrote"])
        self.assertTrue(doc["audit"]["pulls"][1]["overwrote"])

    def test_all_sources_failed_writes_nothing(self):
        http = FixtureHttp(fail={"eastmoney", "sina", "tencent", "yahoo", "em_kline"})
        result = m.pull("1230", root=self.root, http=http, now=DAY1, symbols=SYMBOLS, verbose=False)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["written"])
        self.assertEqual(os.listdir(self.root), [])

    def test_dry_run_writes_nothing(self):
        result = self.pull(dry_run=True)
        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(os.listdir(self.root), [])

    def test_integrity_detects_tampering(self):
        self.pull()
        path = os.path.join(self.root, "20261001.json")
        self.assertTrue(m.verify(self.root, all_days=True, verbose=False)["ok"])
        doc = json.load(open(path, encoding="utf-8"))
        doc["slots"]["0800"]["quotes"]["^HSI"]["price"] = 1.234     # 手工改价
        json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        report = m.verify(self.root, all_days=True, verbose=False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("哈希" in p for p in report["problems"]))

    def test_verify_reports_missing_slots(self):
        self.pull(slot="1230", now=DAY1)
        report = m.verify(self.root, all_days=True, verbose=False)
        self.assertTrue(any("缺 2 档" in a for a in report["alerts"]))

    def test_prune_keeps_recent_days(self):
        for offset in range(3):
            day = DAY1 - timedelta(days=offset)
            m.pull("1230", root=self.root, http=FixtureHttp(when=day), now=day,
                   symbols=SYMBOLS, verbose=False)
        self.assertEqual(len(m.load_days(self.root)), 3)
        info = m.prune(self.root, 2, verbose=False)
        self.assertEqual(len(info["removed"]), 1)
        self.assertEqual(len(m.load_days(self.root)), 2)


# ======================================================================
# ⑥ AI 数据集（特征因果 / 标签前瞻 / 导出 / 上下文）
# ======================================================================
class DatasetTests(TempRootCase):
    def _build_days(self, days=3):
        """逐日逐档落库（与线上一致：每次都合并进当天文件）。"""
        price = dict(PRICES)
        for day_index in range(days):
            for slot, hour, minute in (("0800", 8, 1), ("1230", 12, 31), ("1700", 17, 1)):
                moment = DAY1 + timedelta(days=day_index, hours=hour - 8, minutes=minute - 12)
                prev = {k: v for k, v in price.items()}
                price = {k: round(v * (1 + 0.01 * (day_index + 1) * 0.1), 4) for k, v in price.items()}
                http = FixtureHttp(prices=price, prev=prev, when=moment)
                m.pull(slot, root=self.root, http=http, now=moment,
                       symbols=SYMBOLS, verbose=False)

    def test_feature_truncation_invariance(self):
        """截断未来数据不改变过去行情的特征（无未来函数）。"""
        self._build_days(3)
        docs = m.load_days(self.root)
        full, _meta = m.build_dataset(docs=docs)
        cut, _meta2 = m.build_dataset(docs=docs[:-1])            # 去掉最后一天
        by_key = {(r["date"], r["slot"], r["symbol"]): r for r in full}
        for row in cut:
            key = (row["date"], row["slot"], row["symbol"])
            self.assertIn(key, by_key)
            self.assertEqual(row["features"], by_key[key]["features"])

    def test_labels_only_from_later_snapshots(self):
        self._build_days(2)
        rows, meta = m.build_dataset(root=self.root)
        self.assertEqual(len(meta["dates"]), 2)
        last = [r for r in rows if r["date"] == "2026-10-02" and r["slot"] == "1700"]
        self.assertTrue(last)
        for row in last:                                          # 最后一档没有任何后续数据
            self.assertIsNone(row["labels"]["next_slot_ret"])
            self.assertIsNone(row["labels"]["eod_ret"])
        first = next(r for r in rows if r["date"] == "2026-10-01" and r["slot"] == "0800"
                     and r["symbol"] == "^HSI")
        self.assertIsNotNone(first["labels"]["next_slot_ret"])
        self.assertIsNotNone(first["labels"]["eod_ret"])
        self.assertIsNotNone(first["labels"]["next_day_eod_ret"])
        self.assertEqual(first["features"]["ret_day_open"], 0.0)
        self.assertIsNone(first["features"]["ret_prev_slot"])       # 当天第一档没有前档

    def test_export_jsonl_and_csv(self):
        self._build_days(1)
        self.assertTrue(m.load_days(self.root))
        jsonl = os.path.join(self.root, "ai.jsonl")
        csv_path = os.path.join(self.root, "ai.csv")
        info = m.export_dataset(jsonl, fmt="jsonl", root=self.root)
        self.assertGreater(info["rows"], 0)
        first = json.loads(open(jsonl, encoding="utf-8").readline())
        self.assertIn("features", first)
        self.assertIn("labels", first)
        m.export_dataset(csv_path, fmt="csv", root=self.root)
        header = open(csv_path, encoding="utf-8").readline().strip()
        self.assertIn("f_price", header)
        self.assertIn("y_eod_ret", header)

    def test_ai_context_quality_flags(self):
        self._build_days(1)
        last_slot = DAY1.replace(hour=16, minute=49, second=12)
        ctx = m.ai_context(root=self.root, symbols=["^HSI"], now=last_slot)
        self.assertTrue(ctx["available"])
        self.assertEqual(list(ctx["quotes"]), ["^HSI"])
        self.assertEqual(ctx["self_check_score"], 100)
        self.assertFalse(ctx["stale"])
        self.assertEqual(ctx["sources_ok"], 5)
        later = m.ai_context(root=self.root, now=last_slot + timedelta(days=2))
        self.assertTrue(later["stale"])                     # 超过 max_age_hours 默认 18 小时
        self.assertEqual(m.load_days(self.root)[0]["date_compact"], "20261001")

    def test_empty_db_context_is_unavailable(self):
        ctx = m.ai_context(root=self.root)
        self.assertFalse(ctx["available"])
        self.assertTrue(ctx["reason"])


# ======================================================================
# ⑦ CLI 与 pipeline 隐藏入口
# ======================================================================
class CliTests(TempRootCase):
    def test_cli_pull_verify_stats_export_ai_context(self):
        rc = m.main(["pull", "--slot", "1230"], http=FixtureHttp(), root=self.root,
                    now=DAY1.replace(hour=12, minute=30, second=12))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "20261001.json")))
        self.assertEqual(m.main(["verify", "--all"], root=self.root), 0)
        self.assertEqual(m.main(["stats", "--days", "3"], root=self.root), 0)
        out = os.path.join(self.root, "dataset.jsonl")
        self.assertEqual(m.main(["export", "--out", out], root=self.root), 0)
        self.assertTrue(os.path.getsize(out) > 0)
        self.assertEqual(m.main(["ai-context"], root=self.root), 0)

    def test_cli_pull_returns_one_when_everything_fails(self):
        http = FixtureHttp(fail={"eastmoney", "sina", "tencent", "yahoo", "em_kline"})
        rc = m.main(["pull"], http=http, root=self.root, now=DAY1)
        self.assertEqual(rc, 1)

    def test_unknown_slot_rejected(self):
        with self.assertRaises(SystemExit):
            m.pull("9999", root=self.root, http=FixtureHttp(), now=DAY1, verbose=False)


class PipelineHiddenEntryTests(unittest.TestCase):
    """隐藏入口：--help 不显示 --stock-db，但参数本身可用。"""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "pipeline_under_market_db_test", os.path.join(OUTPUT_DIR, "pipeline.py"))
        cls.pipeline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.pipeline)

    def _run(self, argv):
        old = sys.argv
        sys.argv = ["pipeline.py", *argv]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = self.pipeline.main()
        except SystemExit as exc:                     # --help 走 argparse 的退出
            rc = exc.code
        finally:
            sys.argv = old
        return rc, buf.getvalue()

    def test_help_does_not_advertise_hidden_feature(self):
        rc, out = self._run(["--help"])
        self.assertEqual(rc, 0)
        self.assertNotIn("stock-db", out)
        self.assertNotIn("market_db", out)
        self.assertIn("--sources", out)               # 正常参数仍在

    def test_hidden_flag_is_still_usable(self):
        rc, out = self._run(["--stock-db", "stats", "--stock-db-days", "1"])
        self.assertEqual(rc, 0)
        self.assertIn("市场数据库", out)


if __name__ == "__main__":
    unittest.main()


# ======================================================================
# ⑥ 通达信通道（mootdx，2026-10-01 升级）：沪深行情 / 日K核对 / 财务 / 除权除息
# ======================================================================
A_SYMBOLS = ["600519.SS", "300750.SZ", "000001.SS"]
A_PRICES = {"600519.SS": 1690.0, "300750.SZ": 402.5, "000001.SS": 3842.19}
A_PREV = {"600519.SS": 1680.5, "300750.SZ": 399.8, "000001.SS": 3830.3}


class TdxChannelTests(unittest.TestCase):
    """全部用注入的假客户端验证：不需要 mootdx / pandas / 网络。"""

    def test_registry_has_six_sources_with_tdx_peer(self):
        self.assertEqual(len(m.SOURCES), 6)
        self.assertIn("tdx", m.SOURCES)
        self.assertTrue(m.SOURCES["tdx"]["price_peer"])
        self.assertIn("通达信", m.SOURCES["tdx"]["label"])

    def test_code_mapping_only_a_shares(self):
        self.assertEqual(m.tdx_code("600519.SS"), "sh600519")
        self.assertEqual(m.tdx_code("300750.SZ"), "sz300750")
        for sym in ("0700.HK", "MSFT", "^HSI", ""):
            self.assertEqual(m.tdx_code(sym), "")

    def test_universe_now_covers_a_shares(self):
        codes = [code for _n, code, _mk in m.symbol_universe()]
        for sym in ("600519.SS", "300750.SZ", "000858.SZ", "MSFT"):
            self.assertIn(sym, codes)
        self.assertEqual(m.market_of("600519.SS"), "A")

    def test_records_accepts_dataframe_dict_and_none(self):
        class FakeFrame:
            def __init__(self):
                self.orient = None

            def to_dict(self, orient):
                self.orient = orient
                return [{"code": "600519", "price": 1.0}]

        frame = FakeFrame()
        self.assertEqual(m._records(frame)[0]["code"], "600519")
        self.assertEqual(frame.orient, "records")
        self.assertEqual(m._records(None), [])
        self.assertEqual(m._records({"a": [1, 2], "b": [3, 4]}),
                         [{"a": 1, "b": 3}, {"a": 2, "b": 4}])
        self.assertEqual(m._records({"price": 1.0}), [{"price": 1.0}])
        self.assertEqual(m._records([]), [])

    def test_quotes_hit_and_hk_excluded(self):
        result = m.fetch_tdx(["600519.SS", "000001.SS", "0700.HK"], None,
                             client=FakeTdxClient(), date_str="2026-10-01")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(sorted(result["quotes"]), ["000001.SS", "600519.SS"])
        self.assertEqual(result["host"], "injected")
        self.assertIn("300750.SZ", m.fetch_tdx(["300750.SZ"], None, client=FakeTdxClient(
            prices=A_PRICES, prev=A_PREV), date_str="2026-10-01")["quotes"])   # 深市路径
        quote = result["quotes"]["600519.SS"]
        self.assertAlmostEqual(quote["price"], 1690.0)
        self.assertAlmostEqual(quote["prev_close"], 1680.5)
        self.assertEqual(quote["quote_time"], "2026-09-30 14:59:58")   # 日期由最后一根日K给出

    def test_same_bare_code_disambiguated_by_market(self):
        """沪深同号（000001.SS 指数 vs 000001.SZ 个股）不能串行。"""
        TDX_MAP["sz000001"] = "000001.SZ"
        self.addCleanup(TDX_MAP.pop, "sz000001", None)
        client = FakeTdxClient(prices={"000001.SS": 3842.19, "000001.SZ": 11.5},
                               prev={"000001.SS": 3830.3, "000001.SZ": 11.4})
        result = m.fetch_tdx(["000001.SS", "000001.SZ"], None, client=client,
                             date_str="2026-10-01")
        self.assertEqual(sorted(result["quotes"]), ["000001.SS", "000001.SZ"])
        self.assertAlmostEqual(result["quotes"]["000001.SS"]["price"], 3842.19)
        self.assertAlmostEqual(result["quotes"]["000001.SZ"]["price"], 11.5)

    def test_quote_date_comes_from_last_daily_bar(self):
        """盘前（日K最后一根是上一交易日）不能把昨天的价记成今天 14:59。"""
        result = m.fetch_tdx(["600519.SS"], None, client=FakeTdxClient(), date_str="2026-10-01")
        self.assertEqual(result["quotes"]["600519.SS"]["quote_time"], "2026-09-30 14:59:58")

    def test_quote_date_falls_back_when_no_daily_bar(self):
        client = FakeTdxClient(boom={"bars"})
        result = m.fetch_tdx(["600519.SS"], None, client=client, date_str="2026-10-01")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["quotes"]["600519.SS"]["quote_time"], "2026-10-01 14:59:58")

    def test_enrich_adds_closes_fundamentals_actions(self):
        result = m.fetch_tdx(["600519.SS"], None, client=FakeTdxClient(), enrich=True,
                             date_str="2026-10-01")
        self.assertIn("收盘核对", result["summary"])
        close = result["eod_closes"]["600519.SS"]
        self.assertEqual(close["date"], "2026-09-30")
        self.assertEqual(close["source_kind"], "day_bar")
        fund = result["fundamentals"]["600519.SS"]
        self.assertEqual(fund["total_shares"], 1.2e9)
        self.assertEqual(fund["float_shares"], 1.0e9)
        self.assertAlmostEqual(fund["eps"], round(5.4e10 / 1.2e9, 6))
        self.assertAlmostEqual(fund["pe"], round(1690.0 / (5.4e10 / 1.2e9), 4))
        self.assertAlmostEqual(fund["pb"], round(1690.0 / 160.0, 4))
        self.assertAlmostEqual(fund["total_mv"], round(1690.0 * 1.2e9, 2))
        actions = result["corporate_actions"]["600519.SS"]
        self.assertEqual([a["date"] for a in actions], ["2026-09-30"])   # 45 天窗口外的旧记录被剔除
        self.assertEqual(actions[0]["fenhong"], 25.9)

    def test_enrich_off_by_default(self):
        result = m.fetch_tdx(["600519.SS"], None, client=FakeTdxClient(), date_str="2026-10-01")
        self.assertIn("eod_closes", result)                # 收盘核对每档都做
        self.assertNotIn("fundamentals", result)           # 财务 / 除权除息只在收盘档
        self.assertNotIn("corporate_actions", result)

    def test_non_a_share_universe_is_failed_not_faked(self):
        result = m.fetch_tdx(["0700.HK", "MSFT"], None, client=FakeTdxClient())
        self.assertEqual(result["status"], "failed")
        self.assertIn("不覆盖港美股", result["error"])
        self.assertEqual(result["quotes"], {})

    def test_empty_reply_is_failed(self):
        client = FakeTdxClient(empty={"600519.SS"})
        result = m.fetch_tdx(["600519.SS"], None, client=client)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["error"])

    def test_broken_client_is_failed_not_raised(self):
        client = FakeTdxClient(boom={"quotes"})
        result = m.fetch_tdx(["600519.SS"], None, client=client)
        self.assertEqual(result["status"], "failed")
        self.assertIn("主站断开", result["error"])

    @unittest.skipIf(importlib.util.find_spec("mootdx") is not None,
                     "环境已装 mootdx，跳过「未安装」分支")
    def test_missing_mootdx_degrades_gracefully(self):
        prior = os.environ.get("OCTOPUS_DB_TDX_SERVERS")
        os.environ["OCTOPUS_DB_TDX_SERVERS"] = "127.0.0.1:1"
        self.addCleanup(self._restore_env, "OCTOPUS_DB_TDX_SERVERS", prior)
        result = m.fetch_tdx(["600519.SS"], None)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("未安装 mootdx", result["error"])

    @unittest.skipIf(importlib.util.find_spec("mootdx") is not None,
                     "环境已装 mootdx，跳过「未安装」分支")
    def test_no_mootdx_and_no_pool_says_install(self):
        prior = os.environ.pop("OCTOPUS_DB_TDX_SERVERS", None)
        self.addCleanup(self._restore_env, "OCTOPUS_DB_TDX_SERVERS", prior)
        result = m.fetch_tdx(["600519.SS"], None)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("pip install mootdx", result["error"])

    def test_server_pool_prefers_env_and_dedupes(self):
        prior = os.environ.get("OCTOPUS_DB_TDX_SERVERS")
        os.environ["OCTOPUS_DB_TDX_SERVERS"] = "10.0.0.1:7709, 10.0.0.2"
        self.addCleanup(self._restore_env, "OCTOPUS_DB_TDX_SERVERS", prior)
        servers = m._tdx_servers()
        self.assertEqual(servers[0], ("10.0.0.1", 7709))
        self.assertIn(("10.0.0.2", 7709), servers)
        self.assertEqual(len(servers), len(set(servers)))
        self.assertLessEqual(len(servers), m.TDX_SERVER_LIMIT)

    def test_cli_no_tdx_and_no_enrich(self):
        prior = os.environ.pop("OCTOPUS_DB_TDX", None)
        self.addCleanup(self._restore_env, "OCTOPUS_DB_TDX", prior)
        root = tempfile.mkdtemp(prefix="octopus_db_cli_")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = m.main(["pull", "--slot", "0800", "--symbols", "600519.SS,000001.SS",
                         "--dry-run", "--no-tdx", "--no-enrich"],
                        http=FixtureHttp(prices=A_PRICES, prev=A_PREV), root=root, now=DAY1)
        self.assertEqual(rc, 0)
        self.assertIn("源 5 路", buf.getvalue())          # --no-tdx → 只剩 5 路
        self.assertNotIn("通达信", buf.getvalue())
        self.assertEqual(os.listdir(root), [])

    @staticmethod
    def _restore_env(key, value):
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    def test_env_switch_can_disable_tdx(self):
        os.environ["OCTOPUS_DB_TDX"] = "0"
        self.addCleanup(os.environ.pop, "OCTOPUS_DB_TDX", None)
        result = m.pull("0800", root=tempfile.mkdtemp(prefix="octopus_db_tdx_"),
                        http=FixtureHttp(prices=A_PRICES, prev=A_PREV), now=DAY1,
                        symbols=A_SYMBOLS, verbose=False, tdx_client=FakeTdxClient())
        self.assertNotIn("tdx", result["doc"]["slots"]["0800"]["sources"])


class _FakeSock:
    """TCP 预检用的假 socket：只关心「连上了」和「有没有关掉」。"""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class TdxAntiHangTests(unittest.TestCase):
    """防卡死四道闸（2026-10-01 事故回归）：预置配置 / TCP 预检 / 先验活后明细 / 总预算。

    事故：一台 SYN 被丢弃的死主站，tdxpy 的 connect() 把 socket.timeout 吞掉并 return
    False，mootdx 又不看返回值 → 死站被当成「连上了」，之后每次调用都跑 auto_retry 阶梯
    （4 次重连 × 5s + 退避）。11 只沪深标的 ≈ 34 次调用，单站 ~6 分钟、4 站 ~24 分钟，
    直接把 20 分钟上限的作业拖到「Error: The operation was canceled.」。
    """

    SNY_DROP = ("10.255.255.1", 7709)

    def setUp(self):
        # mootdx 配置一律写到临时目录：这些用例谁都不许碰真实 $HOME
        cfg_dir = tempfile.mkdtemp(prefix="octopus_tdx_home_")
        self.addCleanup(shutil.rmtree, cfg_dir, ignore_errors=True)
        self.cfg_path = os.path.join(cfg_dir, "config.json")
        os.environ["OCTOPUS_DB_TDX_CONFIG"] = self.cfg_path
        self.addCleanup(os.environ.pop, "OCTOPUS_DB_TDX_CONFIG", None)

    @staticmethod
    def _dead_connector(calls=None):
        def connector(address, timeout=None):
            calls is not None and calls.append((address, timeout))
            raise socket.timeout("SYN dropped")
        return connector

    def test_probe_rejects_dead_host_with_reason(self):
        calls = []
        ok, err = m._tdx_probe("10.255.255.1", 7709, connector=self._dead_connector(calls))
        self.assertFalse(ok)
        self.assertIn("TCP 预检失败", err)
        self.assertIn("TimeoutError", err)
        self.assertIn("10.255.255.1:7709", err)
        self.assertEqual(calls[0][0], ("10.255.255.1", 7709))
        self.assertLessEqual(calls[0][1], m.TDX_PROBE_TIMEOUT)   # 预检必须是短超时

    def test_probe_accepts_live_host_and_closes_socket(self):
        sock = _FakeSock()
        ok, err = m._tdx_probe("1.2.3.4", 7709, connector=lambda address, timeout=None: sock)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertTrue(sock.closed)          # 预检只探端口，探完立刻放掉

    def test_dead_host_never_reaches_mootdx(self):
        def factory(**_kw):
            raise AssertionError("预检不过就不该构造 mootdx 客户端")

        client, err = m._open_tdx_client(*self.SNY_DROP, 8, factory=factory,
                                         connector=self._dead_connector())
        self.assertIsNone(client)
        self.assertIn("TCP 预检失败", err)

    def test_client_is_built_without_auto_retry(self):
        seen = {}

        def factory(**kw):
            seen.update(kw)
            return object()

        client, err = m._open_tdx_client("1.2.3.4", 7709, m.TDX_SOCKET_TIMEOUT, factory=factory,
                                         connector=lambda address, timeout=None: _FakeSock())
        self.assertIsNotNone(client)
        self.assertEqual(err, "")
        if importlib.util.find_spec("mootdx") is not None:
            self.assertTrue(os.path.exists(self.cfg_path))   # 预置配置写在（临时）指定路径
        self.assertIs(seen["auto_retry"], False)     # tdxpy 重连阶梯 = 事故主因，关掉
        self.assertIs(seen["heartbeat"], False)
        self.assertEqual(seen["server"], ("1.2.3.4", 7709))
        self.assertEqual(seen["market"], "std")

    def test_quotes_liveness_comes_before_per_symbol_detail(self):
        """行情为空立刻换站：绝不在一台死站上逐只跑 bars / finance / xdxr。"""

        class DeadClient:
            def __init__(self):
                self.calls = []

            def quotes(self, symbol):
                self.calls.append("quotes")
                return []

            def bars(self, **kw):
                self.calls.append("bars")
                return []

            def finance(self, **kw):
                self.calls.append("finance")
                return []

            def xdxr(self, **kw):
                self.calls.append("xdxr")
                return []

        client = DeadClient()
        result = m.fetch_tdx(["600519.SS", "000001.SS"], None, client=client, enrich=True,
                             date_str="2026-10-01")
        self.assertEqual(result["status"], "failed")
        self.assertIn("验活", result["error"])
        self.assertEqual(client.calls, ["quotes"])   # 后面三次调用一次都不许发

    def test_deadline_stops_per_symbol_calls(self):
        class MustNotCall:
            def bars(self, **kw):
                raise AssertionError("预算已到点，不该再逐只取数")

            def finance(self, **kw):
                raise AssertionError("预算已到点，不该再逐只取数")

            def xdxr(self, **kw):
                raise AssertionError("预算已到点，不该再逐只取数")

        past = time.monotonic() - 1
        pairs = {"sh600519": "600519.SS"}
        self.assertEqual(m._tdx_eod_closes(MustNotCall(), pairs, past), {})
        self.assertEqual(m._tdx_fundamentals(MustNotCall(), pairs, {}, past), {})
        self.assertEqual(m._tdx_corporate_actions(MustNotCall(), pairs, "2026-10-01", deadline=past), {})
        self.assertEqual(m._tdx_time_left(None), float("inf"))   # 注入客户端时不设 deadline

    def test_budget_zero_stops_before_any_server(self):
        def factory(**_kw):
            raise AssertionError("预算为 0 时不该建客户端")

        result = m.fetch_tdx(["600519.SS"], None,
                             servers=[("1.1.1.1", 7709), ("1.1.1.2", 7709)], budget=0,
                             connector=lambda address, timeout=None: _FakeSock(), factory=factory)
        self.assertEqual(result["status"], "failed")
        self.assertIn("预算", result["error"])

    def test_budget_expires_midway_and_reports_reason(self):
        clock = {"t": 1_000.0}

        def fake_monotonic():
            clock["t"] += 3.0
            return clock["t"]

        tried = []

        def factory(**kw):
            tried.append(kw["server"])
            raise ConnectionResetError("reset by peer")

        servers = [("1.1.1.%d" % i, 7709) for i in range(1, 7)]
        with mock.patch.object(m.time, "monotonic", fake_monotonic):
            result = m.fetch_tdx(["600519.SS"], None, servers=servers, budget=10,
                                 connector=lambda address, timeout=None: _FakeSock(), factory=factory)
        self.assertEqual(result["status"], "failed")
        self.assertIn("预算", result["error"])
        self.assertLess(len(tried), len(servers))    # 到点就收工，不把 4 台全试一遍
        self.assertTrue(tried)

    def test_dead_servers_reported_with_real_reasons(self):
        tried = []

        def factory(**kw):
            tried.append(kw["server"])
            raise ConnectionResetError("reset by peer")

        result = m.fetch_tdx(["600519.SS"], None,
                             servers=[("1.1.1.1", 7709), ("1.1.1.2", 7709)], budget=30,
                             connector=lambda address, timeout=None: _FakeSock(), factory=factory)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(tried, [("1.1.1.1", 7709), ("1.1.1.2", 7709)])
        self.assertIn("1.1.1.2:7709 ConnectionResetError", result["error"])
        self.assertIn("1.1.1.1:7709", result["error"])

    def test_config_path_env_override(self):
        os.environ["OCTOPUS_DB_TDX_CONFIG"] = "/tmp/octopus_tdx_config.json"
        self.addCleanup(os.environ.pop, "OCTOPUS_DB_TDX_CONFIG", None)
        self.assertEqual(m._mootdx_config_path(), "/tmp/octopus_tdx_config.json")

    def test_config_path_matches_mootdx_rule(self):
        """我们算的路径必须和 mootdx 自己用的一致，否则预置配置等于白写。"""
        if importlib.util.find_spec("mootdx") is None:
            self.skipTest("环境未装 mootdx，路径口径由装了 mootdx 的 CI 覆盖")
        from mootdx.utils import get_config_path
        with mock.patch.dict(os.environ):                  # 临时摘掉覆盖，看默认口径
            os.environ.pop("OCTOPUS_DB_TDX_CONFIG", None)
            self.assertEqual(m._mootdx_config_path(), str(get_config_path("config.json")))

    def test_seed_config_never_overwrites_existing_file(self):
        path = os.path.join(tempfile.mkdtemp(prefix="octopus_tdx_cfg_"), "config.json")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), ignore_errors=True)
        payload = {"SERVER": {"HQ": [["自定义", "9.9.9.9", 7709]]},
                   "BESTIP": {"HQ": ["9.9.9.9", 7709], "EX": "", "GP": ""}, "TDXDIR": "/dx"}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        self.assertEqual(m._ensure_tdx_config("1.2.3.4", 7709, path=path), path)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), payload)     # 用户 / CI 预置的主站被尊重

    def test_seed_config_writes_mootdx_layout(self):
        if importlib.util.find_spec("mootdx") is None:
            path = os.path.join(tempfile.mkdtemp(prefix="octopus_tdx_cfg_"), "config.json")
            self.addCleanup(shutil.rmtree, os.path.dirname(path), ignore_errors=True)
            self.assertIsNone(m._ensure_tdx_config("1.2.3.4", 7709, path=path))
            self.assertFalse(os.path.exists(path))       # 没装 mootdx 就不写半个文件
            return
        path = os.path.join(tempfile.mkdtemp(prefix="octopus_tdx_cfg_"), "config.json")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), ignore_errors=True)
        self.assertEqual(m._ensure_tdx_config("1.2.3.4", 7709, path=path), path)
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["BESTIP"]["HQ"], ["1.2.3.4", 7709])   # 写进去就不会跑 bestip
        self.assertEqual(sorted(data["SERVER"]), ["EX", "GP", "HQ"])
        self.assertTrue(data["SERVER"]["HQ"])
        self.assertIn("TDXDIR", data)

    def test_restamp_swaps_date_and_keeps_time(self):
        quotes = {"600519.SS": {"quote_time": "2026-10-01 14:59:58", "price": 1.0},
                  "000001.SS": {"quote_time": None, "price": 2.0}}
        m._tdx_restamp(quotes, {"600519.SS": "2026-09-30"})
        self.assertEqual(quotes["600519.SS"]["quote_time"], "2026-09-30 14:59:58")
        self.assertIsNone(quotes["000001.SS"]["quote_time"])         # 没日K就别动


class TdxCrossCheckTests(unittest.TestCase):
    def _by_source(self):
        return {"eastmoney": {"price": 100.0, "prev_close": 99.0,
                              "quote_time": "2026-10-01 12:30:00", "name": "x", "open": None,
                              "high": None, "low": None, "volume": None, "amount": None,
                              "change_pct": None}}

    def test_single_close_source_keeps_backward_compatible_fields(self):
        res = m.cross_validate("600519.SS", self._by_source(),
                               eod_close={"close": 99.05, "date": "2026-09-30"})
        self.assertEqual(len(res["eod_close_checks"]), 1)
        self.assertEqual(res["eod_close_check"]["kline_close"], 99.05)
        self.assertTrue(res["eod_close_check"]["ok"])

    def test_two_close_sources_listed(self):
        res = m.cross_validate("600519.SS", self._by_source(), eod_closes=[
            {"source": "em_kline", "close": 99.05, "date": "2026-09-30"},
            {"source": "tdx", "close": 99.0, "date": "2026-09-30", "source_kind": "day_bar"}])
        self.assertEqual([c["source"] for c in res["eod_close_checks"]], ["em_kline", "tdx"])
        self.assertTrue(all(c["ok"] for c in res["eod_close_checks"]))
        self.assertEqual(res["eod_close_check"]["source"], "em_kline")

    def test_disagreeing_tdx_close_flagged(self):
        res = m.cross_validate("600519.SS", self._by_source(),
                               eod_closes=[{"source": "tdx", "close": 120.0, "date": "2026-09-30"}])
        self.assertFalse(res["eod_close_checks"][0]["ok"])
        self.assertGreater(res["eod_close_checks"][0]["dev_pct"], m.SOFT_TOL_PCT)


class TdxPullIntegrationTests(TempRootCase):
    """整链：Fixtures(HTTP) + 假通达信客户端 → 落库文件里能看到 6 路源与附带数据。"""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"OCTOPUS_DB_TDX": "1"})   # 本类要验通达信参与
        patcher.start()
        self.addCleanup(patcher.stop)

    def _http(self, **kw):
        return FixtureHttp(prices=A_PRICES, prev=A_PREV, **kw)

    def _pull(self, slot, when, **kw):
        return m.pull(slot, root=self.root, http=self._http(), now=when, symbols=A_SYMBOLS,
                      verbose=False, tdx_client=FakeTdxClient(prices=A_PRICES, prev=A_PREV), **kw)

    def test_six_sources_and_two_close_checks(self):
        self._pull("0800", DAY1)
        doc = json.load(open(os.path.join(self.root, "20261001.json"), encoding="utf-8"))
        self.assertEqual(len(doc["slots"]["0800"]["sources"]), 6)
        self.assertEqual(doc["slots"]["0800"]["sources"]["tdx"]["status"], "ok")
        self.assertEqual(doc["slots"]["0800"]["cross_check"]["sources_ok"], 6)
        self.assertIn("pe", doc["ai"]["feature_names"])
        quote = doc["slots"]["0800"]["quotes"]["600519.SS"]
        self.assertEqual(quote["n_sources"], 5)                # 5 路参与比价（em_kline 不在内）
        self.assertEqual([c["source"] for c in quote["consensus"]["eod_close_checks"]],
                         ["em_kline", "tdx"])
        self.assertTrue(all(c["ok"] for c in quote["consensus"]["eod_close_checks"]))

    def test_fundamentals_only_at_closing_slot(self):
        self._pull("0800", DAY1)
        self._pull("1700", DAY1.replace(hour=17, minute=0))
        doc = json.load(open(os.path.join(self.root, "20261001.json"), encoding="utf-8"))
        self.assertNotIn("fundamentals", doc["slots"]["0800"])
        self.assertNotIn("corporate_actions", doc["slots"]["0800"])
        fund = doc["slots"]["1700"]["fundamentals"]["600519.SS"]
        self.assertAlmostEqual(fund["pb"], round(1690.0 / 160.0, 4))
        self.assertIn("2026-09-30",
                      [a["date"] for a in doc["slots"]["1700"]["corporate_actions"]["600519.SS"]])

    def test_ai_dataset_carries_fundamental_features(self):
        self._pull("0800", DAY1)
        self._pull("1700", DAY1.replace(hour=17, minute=0))
        rows, meta = m.build_dataset(root=self.root, symbols=["600519.SS"])
        self.assertIn("pe", meta["feature_names"])
        self.assertIn("days_since_action", meta["feature_names"])
        self.assertTrue(rows)
        early = [r for r in rows if r["slot"] == "0800"]
        late = [r for r in rows if r["slot"] == "1700"]
        self.assertIsNone(early[0]["features"]["pe"])           # 早上还没有财务数据 → 不凭空填
        self.assertIsNotNone(late[0]["features"]["pe"])         # 17:00 档已知
        self.assertEqual(late[0]["features"]["days_since_action"], 1)

    def test_ai_context_exposes_fundamentals_and_actions(self):
        self._pull("1700", DAY1.replace(hour=17, minute=0))
        ctx = m.ai_context("20261001", root=self.root)
        item = ctx["quotes"]["600519.SS"]
        self.assertAlmostEqual(item["fundamentals"]["pb"], round(1690.0 / 160.0, 4))
        self.assertEqual(item["recent_actions"][0]["date"], "2026-09-30")
        self.assertEqual(len(item["close_checks"]), 2)

    def test_enrich_can_be_forced_off_at_closing_slot(self):
        self._pull("1700", DAY1.replace(hour=17, minute=0), enrich=False)
        doc = json.load(open(os.path.join(self.root, "20261001.json"), encoding="utf-8"))
        slot = doc["slots"]["1700"]
        self.assertNotIn("fundamentals", slot)
        self.assertNotIn("corporate_actions", slot)
        self.assertEqual(slot["sources"]["tdx"]["status"], "ok")
        self.assertIn("收盘核对", slot["sources"]["tdx"]["summary"])

    def test_self_check_explains_dividend_jump(self):
        """除权除息造成的跳变：写明原因，且不再按数据错误扣分。"""
        slot_doc = {"date": "2026-10-01", "slot": "1230", "trading_day": True,
                    "quotes": {"600519.SS": {"name": "贵州茅台", "market": "A",
                                             "consensus": {"price": 100.0, "prev_close": 100.0}}},
                    "sources": {k: {"status": "ok", "symbols": 1} for k in m.SOURCES},
                    "cross_check": {"median_prices": {"600519.SS": 100.0}, "consensus_ok": True,
                                    "symbols_total": 1, "symbols_ok": 1, "symbols_with_quorum": 1}}
        prev_day = {"slots": {"1700": {"cross_check": {"median_prices": {"600519.SS": 170.0},
                                                       "consensus_ok": True}}}}
        plain = m.self_check(slot_doc, prev_day=prev_day)
        explained = m.self_check(slot_doc, prev_day=prev_day, corporate_actions={
            "600519.SS": [{"date": "2026-09-30", "category": 1, "name": "除权除息"}]})
        self.assertTrue(any("跨日跳变" in a for a in plain["alerts"]))
        note = [a for a in explained["alerts"] if "跨日跳变" in a][0]
        self.assertIn("疑似除权除息", note)
        self.assertIn("2026-09-30", note)
        self.assertGreater(explained["score"], plain["score"])   # 有解释的跳变不惩罚

    def test_explain_action_ignores_old_or_unknown(self):
        actions = {"600519.SS": [{"date": "2026-01-05", "category": 1, "name": "除权除息"}]}
        self.assertEqual(m._explain_action(actions, "600519.SS", "2026-10-01"), "")
        self.assertEqual(m._explain_action(actions, "000001.SS", "2026-10-01"), "")
        self.assertEqual(m._explain_action(None, "600519.SS", "2026-10-01"), "")
