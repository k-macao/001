"""申万一级行业轮动「能否进推送」的离线回归：取数健壮性 → 判死原因 → 拼版与审计。

沙箱 / CI 都访问不到东方财富，整条链路用可复现的假接口驱动：
既验证「数据正常时栏目一定出现」，也验证「数据异常时原因可追溯、绝不静默」。

2026-09-29 起股票池改为 31 个申万一级行业固定表（octopus_quant.industry_rotation.SW_L1_SECTORS），
2026-10-04 起从被删除的 output/sector_rotation.py 移植回 output/octopus_quant/industry_rotation.py，
栏目名【巡游旗鱼】申万一级行业轮动，存档键 industry_rotation*（与港股板块轮动互不覆盖）：
主流程不再调用 clist 列表接口；本文件同时覆盖：固定表 → 日线名称复核 → 覆盖门槛 →
申万官方源逐行业兜底 → 月度持仓 T+1 执行跟踪 → 拼版。
"""
import io
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "output"))
sys.modules.setdefault("requests", types.SimpleNamespace())
from octopus_quant import industry_rotation as ir   # noqa: E402
import backup_sources             # noqa: E402
import pipeline                   # noqa: E402

CST = timezone(timedelta(hours=8))


def _trading_days(asof, count):
    """生成以 asof 结尾、跳过周末的 count 个交易日（YYYY-MM-DD）。"""
    end = datetime.strptime(asof, "%Y-%m-%d").date()
    days, cursor = [], end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return list(reversed(days))


def _bars(asof, count=90, seed=0.0):
    """构造既有正收益窗口又有负收益窗口的日线（否则赔率无定义，行业不评分）。"""
    dates = _trading_days(asof, count)
    price = 100.0 * (1.0 + seed)
    rows = []
    for i, day in enumerate(dates):
        daily = 0.004 if (i // 5) % 2 == 0 else -0.003
        price *= (1.0 + daily)
        rows.append((day, round(price, 4)))
    return rows


def _kline_payload(bars, code="BK0001", name=None):
    """按东财 kline 接口字段序拼装：日期,开,收,高,低,量。name 可缺（老响应不带）。"""
    klines = []
    for day, close in bars:
        klines.append(f"{day},{close - 1:.4f},{close:.4f},{close + 1:.4f},{close - 2:.4f},100000")
    data = {"code": code, "market": 90, "klines": klines}
    if name:
        data["name"] = name
    return {"data": data}


def _sw_payload(bars, sw_code="801010"):
    """申万官方指数发布接口的形状：code 为字符串 "200"，data 为逐日字典。"""
    return {"code": "200", "message": "ok",
            "data": [{"swindexcode": sw_code, "bargaindate": day, "closeindex": close,
                      "openindex": close, "maxindex": close, "minindex": close}
                     for day, close in bars]}


class FakeAPI:
    """可编排的假接口：记录每次请求，按 fqt / 代码 / 主机返回设定好的响应。"""

    def __init__(self, pages=None, bars_by_code=None, empty_fqt=(), accept_headers=True,
                 names=None, sw_bars=None, dead_codes=(), flaky_codes=(), primary_dead_codes=()):
        self.pages = pages or []                 # 行业列表逐页响应（仅 fetch_universe 用）
        self.bars_by_code = bars_by_code or {}   # 东财代码 -> [(日期, 收盘)]
        self.empty_fqt = set(empty_fqt)          # 这些复权口径一律返回空日线
        self.accept_headers = accept_headers
        self.names = names or {}                 # 东财代码 -> kline 返回的 name
        self.sw_bars = sw_bars or {}             # 申万代码 -> [(日期, 收盘)]
        self.dead_codes = set(dead_codes)        # 东财三主机都取不到的代码
        self.primary_dead = set(primary_dead_codes)   # 只有主源取不到（镜像正常）
        self.flaky = {c: True for c in flaky_codes}   # 第一次整条链失败、重试成功
        self.calls = []

    def __call__(self, url, params=None, timeout=15, **kwargs):
        params = params or {}
        if not self.accept_headers and "headers" in kwargs:
            raise TypeError("unexpected keyword argument 'headers'")   # 老式取数函数
        self.calls.append((url, dict(params)))
        if "clist" in url:
            page = int(params.get("pn", "1"))
            return self.pages[page - 1] if page <= len(self.pages) else None
        if "swsresearch" in url:
            bars = self.sw_bars.get(params.get("swindexcode"))
            return _sw_payload(bars, params.get("swindexcode")) if bars else {"code": "500", "data": []}
        code = params.get("secid", "").split(".", 1)[-1]
        if code in self.dead_codes:
            return None
        if code in self.primary_dead and url == ir.KLINE_URLS[0]:
            return None
        if self.flaky.get(code):
            # 主源 + 两个镜像各失败一次，之后恢复
            self.flaky[code] = sum(1 for u, p in self.calls
                                   if "kline" in u and p.get("secid") == params.get("secid")) < len(ir.KLINE_URLS)
            return None
        if params.get("fqt") in self.empty_fqt:
            return {"data": {"klines": []}}
        bars = self.bars_by_code.get(code)
        return _kline_payload(bars, code, self.names.get(code)) if bars else {"data": None}

    def kline_calls(self):
        return [(u, p) for u, p in self.calls if "kline" in u]

    def clist_calls(self):
        return [(u, p) for u, p in self.calls if "clist" in u]


FIVE = [("BK001", "行业BK001"), ("BK002", "行业BK002"), ("BK003", "行业BK003"),
        ("BK004", "行业BK004"), ("BK005", "行业BK005")]


def _universe_page(codes, total=None):
    return {"data": {"total": total if total is not None else len(codes),
                     "diff": [{"f12": code, "f14": f"行业{code}"} for code in codes]}}


class FixedUniverseTests(unittest.TestCase):
    """股票池：31 个申万一级行业固定表；主流程不再碰 clist 列表接口。"""

    def test_sw_l1_table_is_31_unique_boards_in_official_order(self):
        codes = [c for c, _n, _s in ir.SW_L1_SECTORS]
        sw = [s for _c, _n, s in ir.SW_L1_SECTORS]
        self.assertEqual(len(ir.SW_L1_SECTORS), 31)
        self.assertEqual(len(set(codes)), 31)
        self.assertEqual(len(set(sw)), 31)
        self.assertTrue(all(c.startswith("BK") and len(c) == 6 for c in codes))
        self.assertTrue(all(s.startswith("801") and len(s) == 6 for s in sw))
        self.assertEqual(sw, sorted(sw))                      # 申万官方编码顺序
        self.assertEqual(ir.SW_L1_SECTORS[0][1], "农林牧渔")
        self.assertEqual(ir.SW_L1_SECTORS[-1][1], "美容护理")
        names = {n for _c, n, _s in ir.SW_L1_SECTORS}
        for expected in ("银行", "非银金融", "电子", "医药生物", "电力设备", "煤炭", "石油石化"):
            self.assertIn(expected, names)

    def test_default_run_uses_fixed_table_without_clist(self):
        asof = "2026-09-28"
        bars = {code: _bars(asof, seed=i / 1000) for i, (code, _n, _s) in enumerate(ir.SW_L1_SECTORS)}
        names = {code: name for code, name, _s in ir.SW_L1_SECTORS}
        api = FakeAPI(bars_by_code=bars, names=names)
        with tempfile.TemporaryDirectory() as tmp:
            res = ir.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 9, 28, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))
        self.assertEqual(api.clist_calls(), [])
        self.assertEqual(res["universe_count"], 31)
        self.assertEqual(res["scored_count"], 31)
        self.assertEqual(res["diag"]["universe_kind"], "sw_l1_fixed")
        self.assertEqual(res["diag"]["required"], 19)          # max(5, ceil(0.6×31))
        self.assertEqual(res["sources"], {"eastmoney": 31})
        self.assertEqual(res["missing"], [])
        self.assertNotIn("renamed", res["diag"])
        self.assertIn("申万一级", res["universe_label"])
        # 每个行业的日线只按「主源」取一次（探测口径的 2 个样本除外），没有逐镜像重复请求
        secids = [p["secid"] for _u, p in api.kline_calls()]
        self.assertEqual(len(set(secids)), 31)
        self.assertEqual(ir.normalize_universe()[0], {"code": "BK0433", "name": "农林牧渔", "sw": "801010"})

    def test_name_drift_recorded_and_live_name_used(self):
        asof = "2026-09-28"
        bars = {code: _bars(asof, seed=i / 1000) for i, (code, _n, _s) in enumerate(ir.SW_L1_SECTORS)}
        names = {code: name for code, name, _s in ir.SW_L1_SECTORS}
        names["BK0436"] = "纺织服装"          # 东财改名 → 展示用实时名，诊断记录漂移
        api = FakeAPI(bars_by_code=bars, names=names)
        with tempfile.TemporaryDirectory() as tmp:
            res = ir.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 9, 28, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))
        self.assertEqual(res["diag"]["renamed"],
                         {"BK0436": {"expected": "纺织服饰", "live": "纺织服装"}})
        self.assertIn("纺织服装", [s["name"] for s in res["scores"]])

    def test_fetch_universe_still_available_for_research(self):
        """clist 分页抓取保留为研究 / 探测工具：取不全就返回空，不冒充全行业。"""
        page1 = _universe_page([f"BK{i:03d}" for i in range(100)], total=150)
        page2 = _universe_page([f"BK{i:03d}" for i in range(100, 150)], total=150)
        self.assertEqual(len(ir.fetch_universe(FakeAPI(pages=[page1, page2]))), 150)
        self.assertEqual(ir.fetch_universe(FakeAPI(pages=[page1])), [])
        self.assertEqual(ir.fetch_universe(FakeAPI(pages=[{"data": None}])), [])


class KlineFetchTests(unittest.TestCase):
    """日线口径自适应：板块指数在前复权 / 不复权下可用性不同，取能返回数据的那个。"""

    def _api(self, asof, empty_fqt=(), accept_headers=True, **kw):
        return FakeAPI(
            bars_by_code={f"BK00{i}": _bars(asof, seed=i / 1000) for i in range(1, 6)},
            empty_fqt=empty_fqt, accept_headers=accept_headers, **kw)

    def _run(self, api, now, universe=FIVE, tmp=None):
        if tmp is not None:
            return ir.run(api, state_path=os.path.join(tmp, "s.json"), now=now, universe=universe)
        with tempfile.TemporaryDirectory() as tmp:
            return ir.run(api, state_path=os.path.join(tmp, "s.json"), now=now, universe=universe)

    def test_forward_adjusted_default(self):
        asof = "2026-09-25"
        api = self._api(asof)
        res = self._run(api, datetime(2026, 9, 25, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))
        self.assertEqual(res["diag"]["fqt"], "1")
        self.assertEqual(res["universe_count"], 5)
        self.assertEqual(res["scored_count"], 5)
        self.assertEqual(len(res["state"]["holdings"]), 5)
        self.assertEqual(res["diag"]["universe_kind"], "custom")
        # 日线请求带 180 根 / 板块 secid 前缀 90.
        params = [p for _u, p in api.kline_calls()]
        self.assertTrue(all(p["lmt"] == str(ir.KLINE_LIMIT) and p["secid"].startswith("90.") for p in params))

    def test_falls_back_to_unadjusted(self):
        asof = "2026-09-25"
        api = self._api(asof, empty_fqt=("1",))
        res = self._run(api, datetime(2026, 9, 25, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))
        self.assertEqual(res["diag"]["fqt"], "0")

    def test_both_adjustments_empty_stops_early(self):
        """两种口径都取不到 → 只探测样本行业就停手，不对 31 个行业逐个重试。"""
        asof = "2026-09-25"
        api = self._api(asof, empty_fqt=("0", "1"))
        res = self._run(api, datetime(2026, 9, 25, 20, 0, tzinfo=CST))
        self.assertFalse(res["available"])
        self.assertIn("行业日K接口未返回数据", res["reason"])
        # 2 个样本 × 2 种口径；每次探测按「主源 + 2 个同格式镜像」依次尝试
        # （空响应也会试镜像，避免把单主机故障误判成口径不可用）；名单不带申万代码 → 不探测官方源。
        self.assertEqual(len(api.calls), 4 * len(ir.KLINE_URLS))
        probed = {p["secid"] for u, p in api.kline_calls()}
        self.assertEqual(len(probed), 2)

    def test_legacy_fetcher_without_headers_still_works(self):
        asof = "2026-09-25"
        api = self._api(asof, accept_headers=False)
        res = self._run(api, datetime(2026, 9, 25, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))

    def test_stale_anchor_rejects_section(self):
        """共同收盘日距今超过 14 天 → 整栏缺席（不用过期锚点冒充当日信号）。"""
        asof = "2026-09-25"
        api = self._api(asof)
        res = self._run(api, datetime(2026, 10, 20, 20, 0, tzinfo=CST))
        self.assertFalse(res["available"])
        self.assertIn("过期", res["reason"])

    def test_extras_present_and_display_only(self):
        """20 日 / 60 日 / MA20 偏离随评分一起给出，但综合分公式不变。"""
        asof = "2026-09-25"
        res = self._run(self._api(asof), datetime(2026, 9, 25, 20, 0, tzinfo=CST))
        for s in res["scores"]:
            self.assertIsNotNone(s["ret20"])
            self.assertIsNotNone(s["ret60"])
            self.assertIsNotNone(s["ma20_gap"])
            self.assertAlmostEqual(s["score"], 100 * (.8 * s["win_rate"] + .2 * s["odds"] / (1 + s["odds"])))
        breadth = res["breadth"]
        self.assertEqual(breadth["total"], 5)
        self.assertTrue(0 <= breadth["up_week"] <= 5)
        self.assertTrue(0 <= breadth["above_ma20"] <= 5)
        self.assertIsNotNone(breadth["avg_week"])


class CoverageAndFallbackTests(unittest.TestCase):
    """单行业失败只剔除该行业；覆盖不足才整栏缺席；东财缺席时逐行业走申万官方源。"""

    def _sw_universe(self, n=31):
        return list(ir.SW_L1_SECTORS[:n])

    def _bars_for(self, asof, universe, lag_days=0):
        out = {}
        for i, (code, _n, _s) in enumerate(universe):
            out[code] = _bars(asof, seed=i / 1000)
        return out

    def test_single_sector_outage_only_drops_that_sector(self):
        asof = "2026-09-28"
        uni = self._sw_universe()
        api = FakeAPI(bars_by_code=self._bars_for(asof, uni), dead_codes={"BK1217"})
        with tempfile.TemporaryDirectory() as tmp:
            res = ir.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 9, 28, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))
        self.assertEqual(res["missing"], ["BK1217"])
        self.assertEqual(res["scored_count"], 30)
        self.assertEqual(res["diag"]["kline_series"], 30)

    def test_flaky_mirror_recovered_by_retry_pass(self):
        asof = "2026-09-28"
        uni = self._sw_universe()
        api = FakeAPI(bars_by_code=self._bars_for(asof, uni), flaky_codes={"BK1283"})
        with tempfile.TemporaryDirectory() as tmp:
            res = ir.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 9, 28, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))
        self.assertEqual(res["missing"], [])
        self.assertEqual(res["scored_count"], 31)

    def test_mirror_hits_recorded_as_backup_source(self):
        """主源单台故障 → 镜像供数：行业照常评分，诊断记 em_mirror，来源计数分开。"""
        asof = "2026-09-28"
        uni = self._sw_universe()
        api = FakeAPI(bars_by_code=self._bars_for(asof, uni), primary_dead_codes={"BK1283", "BK0464"})
        with tempfile.TemporaryDirectory() as tmp:
            res = ir.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 9, 28, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))
        self.assertEqual(res["sources"], {"eastmoney": 29, "eastmoney_mirror": 2})
        self.assertEqual(res["diag"]["em_mirror"], ["BK0464", "BK1283"])
        self.assertEqual(res["scored_count"], 31)
        got = ir.fetch_series(api, "BK1283")
        self.assertEqual(got["via"], 1)
        self.assertEqual(ir.fetch_series(api, "BK0433")["via"], 0)

    def test_coverage_below_60pct_hides_section(self):
        asof = "2026-09-28"
        uni = self._sw_universe()
        dead = {code for code, _n, _s in uni[-13:]}           # 31-13 = 18 < 19（样本行业仍正常）
        api = FakeAPI(bars_by_code=self._bars_for(asof, uni), dead_codes=dead)
        with tempfile.TemporaryDirectory() as tmp:
            res = ir.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 9, 28, 20, 0, tzinfo=CST),
                         universe=[(c, n) for c, n, _s in uni])    # 不带申万代码：无兜底
        self.assertFalse(res["available"])
        self.assertIn("覆盖不足", res["reason"])
        self.assertIn("18/31", res["reason"])
        self.assertEqual(res["diag"]["required"], 19)

    def test_sw_official_fallback_per_sector(self):
        """东财取不到的行业走申万官方源；官方源滞后一天时该行业不评分，绝不混源。"""
        asof = "2026-09-28"
        uni = self._sw_universe()
        bars = self._bars_for(asof, uni)
        prev = _trading_days(asof, 2)[0]                     # 官方源只到前一交易日
        api = FakeAPI(bars_by_code=bars, dead_codes={"BK1283", "BK1203"},
                      sw_bars={"801780": bars["BK1283"],               # 银行：官方源与东财同步
                               "801790": [b for b in bars["BK1203"] if b[0] <= prev]})  # 非银：滞后
        with tempfile.TemporaryDirectory() as tmp:
            res = ir.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 9, 28, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))
        self.assertEqual(res["sources"], {"eastmoney": 29, "sw_official": 2})
        self.assertEqual(res["missing"], [])
        scored = {s["code"] for s in res["scores"]}
        self.assertIn("BK1283", scored)
        self.assertNotIn("BK1203", scored)                   # 滞后行业按锚点规则不评分
        self.assertEqual(res["scored_count"], 30)
        sw_calls = [p for u, p in api.calls if "swsresearch" in u]
        self.assertEqual({p["swindexcode"] for p in sw_calls}, {"801780", "801790"})
        self.assertTrue(all(p["period"] == "DAY" for p in sw_calls))

    def test_sw_official_only_when_eastmoney_fully_down(self):
        asof = "2026-09-28"
        uni = self._sw_universe()
        bars = self._bars_for(asof, uni)
        api = FakeAPI(dead_codes={c for c, _n, _s in uni},
                      sw_bars={s: bars[c] for c, _n, s in uni})
        with tempfile.TemporaryDirectory() as tmp:
            res = ir.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 9, 28, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))
        self.assertEqual(res["diag"]["fallback"], "sw_official")
        self.assertIsNone(res["diag"]["fqt"])
        self.assertEqual(res["sources"], {"sw_official": 31})

    def test_fetch_sw_series_parses_official_shape(self):
        bars = _bars("2026-09-24", count=30)
        api = FakeAPI(sw_bars={"801780": bars})
        self.assertEqual(ir.fetch_sw_series(api, "801780"), bars)
        self.assertEqual(ir.fetch_sw_series(api, "801999"), [])
        self.assertEqual(ir.fetch_sw_series(api, None), [])
        url, params = api.calls[0]
        self.assertEqual(url, ir.SW_TREND_URL)
        self.assertEqual(params, {"swindexcode": "801780", "period": "DAY"})

    def test_registry_line_for_rotation(self):
        line = backup_sources.DATA_LINES["sw_industry_index"]
        self.assertIn("【巡游旗鱼】申万一级行业轮动", line["used_by"])
        urls = [u for _l, u, _s in backup_sources.candidates("sw_industry_index", sw_code="801780")]
        self.assertEqual(urls[0], ir.KLINE_URLS[0])
        self.assertEqual(urls[1], ir.KLINE_URLS[1])
        self.assertTrue(urls[2].startswith(ir.SW_TREND_URL))
        self.assertIn("swindexcode=801780", urls[2])
        self.assertNotIn("每日量化策略·行业列表", backup_sources.DATA_LINES["em_clist"]["used_by"])
        self.assertIn("【巡游旗鱼】申万一级行业轮动·板块指数日K备用",
                      backup_sources.DATA_LINES["em_kline"]["used_by"])


class TrackingTests(unittest.TestCase):
    """月度持仓反馈闭环：信号日收盘产生、下一交易日收盘执行，从执行日起算表现。"""

    def _state(self, codes, reb):
        return {"month": reb[:7], "rebalance_date": reb,
                "holdings": [{"code": c, "name": c, "score": 60.0, "weight": 0.2} for c in codes]}

    def test_pending_on_signal_day(self):
        asof = "2026-09-25"
        bars = {f"BK00{i}": _bars(asof, seed=i / 1000) for i in range(1, 6)}
        tr = ir.track_holdings(self._state(list(bars), asof), bars, asof)
        self.assertTrue(tr["pending"])
        self.assertIsNone(tr["exec_date"])
        self.assertIsNone(tr["portfolio"])
        self.assertTrue(all(r["since_exec"] is None for r in tr["holdings"]))

    def test_since_exec_uses_t_plus_one_close(self):
        asof = "2026-09-28"
        days = _trading_days(asof, 90)
        bars = {}
        for i in range(1, 8):
            bars[f"BK00{i}"] = [(d, 100.0 + i + k * (0.5 if i % 2 else -0.25)) for k, d in enumerate(days)]
        reb = days[-3]                                       # 信号日：倒数第 3 个交易日
        tr = ir.track_holdings(self._state([f"BK00{i}" for i in range(1, 6)], reb), bars, asof)
        self.assertFalse(tr["pending"])
        self.assertEqual(tr["exec_date"], days[-2])          # 执行日 = 信号日后第一个交易日
        for r in tr["holdings"]:
            series = dict(bars[r["code"]])
            self.assertAlmostEqual(r["since_exec"], series[asof] / series[days[-2]] - 1)
        expected = sum(0.2 * r["since_exec"] for r in tr["holdings"])
        self.assertAlmostEqual(tr["portfolio"], expected)
        bench = [dict(b)[asof] / dict(b)[days[-2]] - 1 for b in bars.values()]
        self.assertAlmostEqual(tr["benchmark"], sum(bench) / len(bench))
        self.assertEqual(tr["benchmark_n"], 7)

    def test_run_result_carries_tracking(self):
        asof = "2026-09-28"
        days = _trading_days(asof, 90)
        bars = {f"BK00{i}": _bars(asof, seed=i / 1000) for i in range(1, 6)}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "items": [],
                           "industry_rotation": {"month": "2026-09", "rebalance_date": days[-4],
                                               "holdings": [{"code": f"BK00{i}", "name": f"行业BK00{i}",
                                                             "score": 60.0, "weight": 0.2}
                                                            for i in range(1, 6)]}}, f)
            res = ir.run(FakeAPI(bars_by_code=bars), state_path=path, universe=FIVE,
                         now=datetime(2026, 9, 28, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))
        self.assertEqual(res["diag"]["state"], "reused")
        self.assertEqual(res["tracking"]["exec_date"], days[-3])
        self.assertIsNotNone(res["tracking"]["portfolio"])
        self.assertIsNotNone(res["tracking"]["benchmark"])


class DiagPersistenceTests(unittest.TestCase):
    """诊断落盘：成功与失败都写，且不破坏存档里的其它字段（新闻标题等）。"""

    def test_failure_reason_persisted_without_clobbering_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "news_history.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "items": [{"title": "旧标题", "date": "2026-09-01"}]}, f)
            api = FakeAPI()                                   # 任何日线都取不到
            res = ir.run(api, state_path=path, now=datetime(2026, 9, 28, 20, 0, tzinfo=CST))
            self.assertFalse(res["available"])
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["items"], [{"title": "旧标题", "date": "2026-09-01"}])
            self.assertIn("行业日K接口未返回数据", saved["industry_rotation_diag"]["reason"])
            self.assertEqual(saved["industry_rotation_diag"]["universe"], 31)
            self.assertIn("ran_at", saved["industry_rotation_diag"])

    def test_success_persists_holdings_and_diag(self):
        asof = "2026-09-25"
        api = FakeAPI(bars_by_code={f"BK00{i}": _bars(asof, seed=i / 1000) for i in range(1, 6)})
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "news_history.json")
            res = ir.run(api, state_path=path, now=datetime(2026, 9, 25, 20, 0, tzinfo=CST),
                         universe=FIVE)
            self.assertTrue(res["available"], res.get("reason"))
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(len(saved["industry_rotation"]["holdings"]), 5)
            self.assertEqual(saved["industry_rotation"]["month"], "2026-09")
            self.assertEqual(saved["industry_rotation_diag"]["state"], "built")
            self.assertTrue(res["tracking"]["pending"])       # 当日建仓：待下一交易日执行
            # 同月再跑：沿用原持仓，不换仓
            again = ir.run(api, state_path=path, now=datetime(2026, 9, 26, 20, 0, tzinfo=CST),
                           universe=FIVE)
            self.assertEqual(again["state"]["holdings"], saved["industry_rotation"]["holdings"])
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["industry_rotation_diag"]["state"], "reused")


class PushRenderTests(unittest.TestCase):
    """推送拼版：数据够 → 栏目必现；数据不够 → 审计点名、正文不留空栏。"""

    @staticmethod
    def _source(asof, ok=True, tracking=None):
        if not ok:
            return pipeline._source_result(
                pipeline.INDUSTRY_ROTATION_SOURCE_LABEL, "unavailable", result={
                    "available": False, "reason": "行业日K接口未返回数据",
                    "diag": {"universe": 31, "fqt": None}})
        bars = {f"BK00{i}": _bars(asof, seed=i / 1000) for i in range(1, 6)}
        scores = ir.build_scores([(c, f"行业{c}", b) for c, b in bars.items()], asof)
        result = {"available": True, "asof": asof, "scores": scores,
                  "scored_count": len(scores), "universe_count": 31,
                  "universe_label": ir.UNIVERSE_LABEL,
                  "breadth": ir.breadth_summary(scores),
                  "sources": {"eastmoney": 4, "sw_official": 1}, "missing": ["BK1217"],
                  "tracking": tracking,
                  "state": {"month": asof[:7], "rebalance_date": asof,
                            "holdings": ir.allocate(scores)},
                  "diag": {"fqt": "1", "state": "built"}}
        return pipeline._source_result(pipeline.INDUSTRY_ROTATION_SOURCE_LABEL, "success",
                                       is_today=True, content_date=asof, result=result)

    def test_section_rendered_when_available(self):
        html = pipeline.generate_report({pipeline.INDUSTRY_ROTATION_SOURCE_NAME: self._source("2026-09-25")},
                                        "2026年9月25日", "20260925")
        self.assertIn("【巡游旗鱼】申万一级行业轮动", html)
        self.assertIn("目标权重", html)
        self.assertIn("80%", html)
        self.assertIn("2026-09-25", html)
        self.assertIn("申万一级行业 31 个", html)
        self.assertIn("有效 5/31", html)
        self.assertIn("行业宽度", html)
        self.assertIn("vs MA20", html)
        self.assertIn("东方财富 4 / 申万官方 1", html)
        self.assertIn("未取到日线：BK1217", html)
        self.assertIn("待下一交易日执行", html)

    def test_tracking_rendered_after_exec_day(self):
        tracking = {"rebalance_date": "2026-09-19", "exec_date": "2026-09-22", "pending": False,
                    "holdings": [{"code": f"BK00{i}", "name": f"行业BK00{i}", "weight": 0.2,
                                  "since_exec": 0.01 * i} for i in range(1, 6)],
                    "portfolio": 0.03, "benchmark": 0.012, "benchmark_n": 30}
        html = pipeline.generate_report({pipeline.INDUSTRY_ROTATION_SOURCE_NAME: self._source("2026-09-25", tracking=tracking)},
                                        "2026年9月25日", "20260925")
        self.assertIn("执行日 2026-09-22 收盘起算表现", html)
        self.assertIn("组合执行日以来 +3.00%", html)
        self.assertIn("全行业等权 +1.20%", html)
        self.assertIn("超额 +1.80pp", html)
        self.assertIn("执行日以来 +1.00%", html)
        self.assertNotIn("待下一交易日执行", html)

    def test_absent_section_named_in_audit_only(self):
        html = pipeline.generate_report({pipeline.INDUSTRY_ROTATION_SOURCE_NAME: self._source("2026-09-25", ok=False)},
                                        "2026年9月25日", "20260925")
        self.assertNotIn("INDUSTRY ROTATION", html)        # 正文不留空栏
        self.assertNotIn("目标权重", html)                  # 也不留半截表格
        self.assertEqual(html.count(pipeline.INDUSTRY_ROTATION_SOURCE_NAME), 1)
        self.assertIn(pipeline.INDUSTRY_ROTATION_SOURCE_NAME, html.split("数据覆盖")[-1])

    def test_fetch_logs_reason_on_failure(self):
        api = FakeAPI()                                       # 东财三主机与申万官方源都无数据
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            # 存档路径指向临时目录：诊断落盘不得碰仓库里的 output/news_history.json
            # （pipeline 侧按 REPORT_DIR 定位存档，模块侧按 STATE_FILE，两处都要隔离）
            with patch.object(ir, "STATE_FILE", os.path.join(tmp, "news_history.json")), \
                    patch.object(pipeline, "REPORT_DIR", tmp), \
                    patch.object(pipeline, "safe_request", api), redirect_stdout(buf):
                src = pipeline.fetch_industry_rotation()
        self.assertEqual(src["status"], "unavailable")
        self.assertEqual(src["source"], pipeline.INDUSTRY_ROTATION_SOURCE_LABEL)
        self.assertIn("行业轮动栏目缺席", buf.getvalue())
        self.assertIn("行业日K接口未返回数据", buf.getvalue())
        self.assertIn("申万官方源亦无数据", buf.getvalue())
        self.assertIn("universe=31", buf.getvalue())
        self.assertEqual(api.clist_calls(), [])

    def test_fetch_registers_backup_events(self):
        """镜像 / 申万官方供数时登记备用源事件（总结「数据覆盖」一行点名）。"""
        asof = "2026-09-28"
        bars = {code: _bars(asof, seed=i / 1000) for i, (code, _n, _s) in enumerate(ir.SW_L1_SECTORS)}
        api = FakeAPI(bars_by_code=bars, primary_dead_codes={"BK1201"}, dead_codes={"BK1283"},
                      sw_bars={"801780": bars["BK1283"]})
        fixed_now = datetime(2026, 9, 28, 20, 0, tzinfo=CST)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "BACKUP_EVENTS", []), \
                patch.object(ir, "STATE_FILE", os.path.join(tmp, "news_history.json")), \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline, "safe_request", api), \
                patch.object(ir, "datetime", _FrozenDatetime(fixed_now)), redirect_stdout(io.StringIO()):
            src = pipeline.fetch_industry_rotation()
            events = list(pipeline.BACKUP_EVENTS)
        self.assertEqual(src["status"], "success")
        self.assertEqual({e[1] for e in events}, {"备用源1", "备用源2"})
        self.assertTrue(all(e[0] == "申万一级行业指数日线（31 个 · 东财板块指数 / 申万官方）" for e in events))
        text = pipeline.backup_events_text(events)
        self.assertIn("备用源2（申万宏源研究所 官方指数发布）", text)
        self.assertEqual(src["result"]["sources"], {"eastmoney": 29, "eastmoney_mirror": 1, "sw_official": 1})

    def test_fetch_logs_success_summary(self):
        asof = "2026-09-28"
        bars = {code: _bars(asof, seed=i / 1000) for i, (code, _n, _s) in enumerate(ir.SW_L1_SECTORS)}
        api = FakeAPI(bars_by_code=bars, dead_codes={"BK1217"})
        buf = io.StringIO()
        fixed_now = datetime(2026, 9, 28, 20, 0, tzinfo=CST)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ir, "STATE_FILE", os.path.join(tmp, "news_history.json")), \
                    patch.object(pipeline, "REPORT_DIR", tmp), \
                    patch.object(pipeline, "safe_request", api), \
                    patch.object(ir, "datetime", _FrozenDatetime(fixed_now)), redirect_stdout(buf):
                src = pipeline.fetch_industry_rotation()
        self.assertEqual(src["status"], "success", buf.getvalue())
        self.assertIn("有效 30/31", buf.getvalue())
        self.assertIn("未取到 BK1217", buf.getvalue())
        self.assertEqual(src["content_date"], asof)


class SectionWiringTests(unittest.TestCase):
    """2026-10-04 移植时新增的接线：正文顺序、图标、开关键、来源名与港股板块轮动区分。"""

    def test_section_registered_in_order_and_icons(self):
        self.assertIn("INDUSTRY ROTATION", pipeline.REPORT_SECTION_ORDER)
        # 排在港股板块轮动之后（同族栏目相邻），且在政策因子之前
        self.assertGreater(pipeline.REPORT_SECTION_ORDER.index("INDUSTRY ROTATION"),
                           pipeline.REPORT_SECTION_ORDER.index("SECTOR ROTATION"))
        # 2026-10-14 重排：行业轮动属「④我们该怎么办」，位于「③可能会怎样」之后
        self.assertGreater(pipeline.REPORT_SECTION_ORDER.index("INDUSTRY ROTATION"),
                           pipeline.REPORT_SECTION_ORDER.index("WEEKLY FORECAST"))
        for icon_map in (pipeline._SECTION_ICON_META, pipeline.DOSSIER_ICONS):
            self.assertIn("INDUSTRY ROTATION", icon_map)
        self.assertNotEqual(pipeline._SECTION_ICON_META["INDUSTRY ROTATION"],
                            pipeline._SECTION_ICON_META["SECTOR ROTATION"])
        self.assertNotEqual(pipeline.DOSSIER_ICONS["INDUSTRY ROTATION"],
                            pipeline.DOSSIER_ICONS["SECTOR ROTATION"])
        self.assertIn("申万一级", pipeline.SECTION_TITLE_INDUSTRY_ROTATION)
        self.assertNotEqual(pipeline.INDUSTRY_ROTATION_SOURCE_NAME,
                            pipeline.SECTOR_ROTATION_SOURCE_NAME)

    def test_disabled_switch_returns_unavailable_without_network(self):
        """关掉开关：不联网、不写诊断、不落持仓，只回一个 unavailable 来源。"""
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "INDUSTRY_ROTATION_ENABLED", False), \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(ir, "STATE_FILE", os.path.join(tmp, "news_history.json")), \
                patch.object(pipeline, "safe_request",
                             side_effect=AssertionError("关闭时不得联网")):
            src = pipeline.fetch_industry_rotation()
        self.assertEqual(src["status"], "unavailable")
        self.assertIn("已关闭", src["error"])
        self.assertFalse(os.path.exists(os.path.join(tmp, "news_history.json")))

    def test_freshness_registry_has_current_name(self):
        import freshness_checker as fc
        self.assertIn(pipeline.INDUSTRY_ROTATION_SOURCE_NAME, fc.FRESHNESS_THRESHOLDS)

    def test_section_title_does_not_collide_with_hk_rotation(self):
        html = pipeline.generate_report(
            {pipeline.INDUSTRY_ROTATION_SOURCE_NAME: PushRenderTests._source("2026-09-25")},
            "2026年9月25日", "20260925")
        self.assertIn(pipeline.SECTION_TITLE_INDUSTRY_ROTATION, html)
        self.assertNotIn("【滚滚翻车鱼】", html.split(pipeline.SECTION_TITLE_INDUSTRY_ROTATION)[0].split("数据覆盖")[-1])


def _FrozenDatetime(fixed):
    """返回把 now() 钉在固定时刻的 datetime 子类（strptime 等其余行为不变），
    用于让 industry_rotation.run() 在没有传 now 时也可复现。"""
    return type("FrozenDatetime", (datetime,), {
        "now": classmethod(lambda cls, tz=None: fixed.astimezone(tz) if tz else fixed),
    })


if __name__ == "__main__":
    unittest.main()
