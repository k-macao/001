"""📅 每周量化走势预测离线回归测试（不发任何网络请求）。

核心是两条「防自欺」未来函数测试：
  · 截断不变性（arielb57/peekahead 不变量）：对任意切点 k，signals[k] 只依赖 ≤k 的
    输入——把 k 之后的未来数据删掉 / 扰动，过去时刻的输出必须逐位不变；自检覆盖
    全部 7 个视界（2026-09-29 起视界 5→7，逐日表格 7 行同一次因果扫描）；
  · 结算严格在后（k-macao/03 PR #54 约束②③）：类比锚点标签必须已结算（s+7 ≤ t），
    预测先存档 settled=False，满 7 个交易日才按真实收盘回填（旧档仍按其签发时的
    5 个交易日结算，历史不篡改），当次运行不可能结算当次。

另覆盖：概率夹逼 5%~95%、基准率独立双记账、回测样本不足只报样本量、
留痕档案 issue→settle→reissue 流转、两主题渲染与栏目顺序、审计与结论接入；
逐日表格引擎（compute_path_signals / build_daily_path / build_advice / _var_horizon /
trading_days_after / _lean_word）的离线纯函数回归。
"""
import importlib.util
import json
import math
import random
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# pipeline 在导入时只需要 requests 存在；本测试不发出 HTTP 请求。
sys.modules.setdefault("requests", types.SimpleNamespace())

REPO_ROOT = Path(__file__).parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
if str(OUTPUT_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUT_DIR))

import octopus_weekly as w  # noqa: E402
from octopus_quant import providers  # noqa: E402

MODULE_PATH = OUTPUT_DIR / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_weekly_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

CST = timezone(timedelta(hours=8))


def synthetic_closes(n=300, seed=42):
    """确定性随机游走收盘价（无网络、可复现）。"""
    rng = random.Random(seed)
    closes, x = [], 24000.0
    for _ in range(n):
        x *= 1 + rng.gauss(0.0002, 0.011)
        closes.append(x)
    return closes


def weekday_dates(n, start=datetime(2026, 1, 5)):
    dates, d = [], start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return dates


def fake_chart_fetch(closes):
    """伪造 Yahoo chart JSON（fetch_bars 的输入契约），只读给定 closes 序列。"""
    dates = weekday_dates(len(closes))

    def fetch_json(url, params=None, timeout=None):
        stamps = [int(datetime.strptime(dt, "%Y-%m-%d")
                      .replace(hour=8, tzinfo=CST).timestamp()) for dt in dates]
        return {"chart": {"result": [{
            "timestamp": stamps,
            "indicators": {"quote": [{
                "close": list(closes), "open": list(closes),
                "high": list(closes), "low": list(closes),
                "volume": [1] * len(closes),
            }]},
        }]}}

    return fetch_json


class WeeklySignalsLookaheadTests(unittest.TestCase):
    """未来函数（look-ahead）防线：截断不变性 / 扰动不变性 / embargo 双记账。"""

    @classmethod
    def setUpClass(cls):
        cls.closes = synthetic_closes(300, seed=42)
        cls.computed = w.compute_signals(cls.closes)

    def test_constants_lock_the_lookahead_contract(self):
        # 口径常量一旦改动就会改变预测，必须与文档/README 一致
        self.assertEqual(w.HORIZON, 7)       # 2026-09-29 起：未来 7 个交易日（逐日表格）
        self.assertEqual(w.PATH_MAX, 7)      # 逐日表格行数 = 7
        self.assertEqual(w.LEGACY_HORIZON, 5)  # 旧档（改视界前签发）仍按 5 个交易日结算
        self.assertEqual(w.WINDOW, 20)
        self.assertEqual(w.ANALOG_K, 8)
        self.assertEqual(w.MIN_ANALOGS, 4)
        self.assertEqual((w.PROB_FLOOR, w.PROB_CAP), (0.05, 0.95))

    def test_compute_signals_ok_on_sufficient_bars(self):
        self.assertTrue(self.computed["ok"])
        first = self.computed.get("first_signal")
        self.assertIsNotNone(first)
        # 首个信号必须已积累 ≥ MIN_RESOLVED 个已结算周样本（s+5 ≤ t）
        self.assertGreaterEqual(self.computed["signals"][first]["n_resolved"],
                                w.MIN_RESOLVED)

    def test_truncation_invariance(self):
        """peekahead 核心不变量：删掉未来数据，历史输出逐位不变。"""
        full = self.computed
        n = len(self.closes)
        f0 = full["first_signal"]
        k0 = max(f0, w.MIN_BARS - 1)
        cuts = sorted({k0, k0 + (n - 1 - k0) // 2, n - 1})
        for k in cuts:
            trunc = w.compute_signals(self.closes[:k + 1])
            self.assertTrue(trunc["ok"])
            a, b = full["signals"][k], trunc["signals"][k]
            self.assertIsNotNone(a, f"切点 {k} 应有信号")
            self.assertIsNotNone(b, f"切点 {k} 截断后应仍有信号")
            self.assertEqual(a, b, f"切点 {k} 的输出被未来数据改变了")

    def test_future_perturbation_invariance(self):
        """扰动 t 之后的一切（暴涨/腰斩），signals[:t+1] 必须与原序列一致。"""
        k = 200
        mod = self.closes[:k + 1] + [c * (3.14 if i % 2 else 0.13)
                                     for i, c in enumerate(self.closes[k + 1:])]
        a = w.compute_signals(self.closes)
        b = w.compute_signals(mod)
        self.assertEqual(a["signals"][:k + 1], b["signals"][:k + 1])

    def test_base_rate_embargo_double_entry(self):
        """基准率只数 s+5 ≤ t 的已结算标签（独立复算，双记账对账）。"""
        H, W = w.HORIZON, w.WINDOW
        signals = self.computed["signals"]
        for t in (60, 150, 250, len(self.closes) - 1):
            sig = signals[t]
            self.assertIsNotNone(sig, f"t={t} 应有信号")
            ys = [1.0 if self.closes[s + H] > self.closes[s] else 0.0
                  for s in range(W, t - H + 1)]
            p0 = (sum(ys) + 1.0) / (len(ys) + 2.0)
            self.assertEqual(sig["n_resolved"], len(ys), f"t={t} 已结算样本数不一致")
            self.assertAlmostEqual(sig["p_base"], p0, places=12, msg=f"t={t} 基准率不一致")
            # 相似锚点上限：锚点 s 必须满足 s ≤ t - H（标签已结算）
            self.assertLessEqual(sig["n_analog"], w.ANALOG_K)

    def test_probability_bounds_everywhere(self):
        for i, sig in enumerate(self.computed["signals"]):
            if not sig:
                continue
            self.assertGreaterEqual(sig["p_up"], w.PROB_FLOOR, f"t={i}")
            self.assertLessEqual(sig["p_up"], w.PROB_CAP, f"t={i}")
            if sig["p_sim"] is not None:
                self.assertGreaterEqual(sig["p_sim"], w.PROB_FLOOR)
                self.assertLessEqual(sig["p_sim"], w.PROB_CAP)

    def test_deterministic_on_same_input(self):
        a = w.compute_signals(synthetic_closes(200, seed=7))
        b = w.compute_signals(synthetic_closes(200, seed=7))
        self.assertEqual(a["signals"], b["signals"])

    def test_insufficient_bars_degrades_without_signals(self):
        short = w.compute_signals(self.closes[:w.MIN_BARS - 1])
        self.assertFalse(short["ok"])
        self.assertIn("样本不足", short["reason"])

    def test_check_no_lookahead_passes_and_rejects_bad_cut(self):
        ok, msg = w.check_no_lookahead(self.closes)
        self.assertTrue(ok, msg)
        self.assertIn("逐位一致", msg)
        bad_ok, bad_msg = w.check_no_lookahead(self.closes, cuts=[3])
        self.assertFalse(bad_ok)
        self.assertIn("越界", bad_msg)

    def test_backtest_sample_honesty(self):
        bt = w._backtest(self.closes, self.computed["signals"])
        self.assertGreater(bt["n"], 0)
        if bt["hit_rate"] is None:
            # 样本 <10 只报样本量，绝不下命中率结论
            self.assertIn("只报样本量", bt["note"])
            self.assertLess(bt["n"], 10)
        else:
            self.assertGreaterEqual(bt["hit_rate"], 0.0)
            self.assertLessEqual(bt["hit_rate"], 1.0)
            self.assertGreaterEqual(bt["brier"], 0.0)
            self.assertLessEqual(bt["brier"], 1.0)
            self.assertTrue(0 < bt["base_rate"] <= 1)


class WeeklyJournalSettleTests(unittest.TestCase):
    """先存档后结算：issue → 满 5 个交易日 settle → 再 issue 的档案流转。"""

    def _run(self, closes, history_path, now):
        return w.run_weekly(fake_chart_fetch(closes), history_path=history_path, now=now)

    def test_issue_settle_reissue_flow(self):
        base = synthetic_closes(300, seed=11)[:75]
        with tempfile.TemporaryDirectory() as td:
            hp = str(Path(td) / "weekly_forecast.json")
            now1 = datetime(2026, 4, 10, 9, 0, tzinfo=CST)
            r1 = self._run(base, hp, now1)
            self.assertTrue(r1["available"])
            with open(hp, encoding="utf-8") as fh:
                journal = json.load(fh)
            self.assertEqual(len(journal["entries"]), 1)
            e0 = journal["entries"][0]
            self.assertFalse(e0["settled"])              # ③ 先存档 settled=False
            self.assertEqual(e0["base_date"], weekday_dates(75)[-1])
            self.assertGreaterEqual(e0["p_up"], w.PROB_FLOOR)
            self.assertLessEqual(e0["p_up"], w.PROB_CAP)

            # 不足 7 个交易日：即使重跑也绝不结算（目标日在严格之后）
            r_mid = self._run(base, hp, now1)
            self.assertTrue(r_mid["available"])
            with open(hp, encoding="utf-8") as fh:
                journal = json.load(fh)
            self.assertEqual(len(journal["entries"]), 1)
            self.assertFalse(journal["entries"][0]["settled"])
            self.assertEqual(journal["entries"][0]["target_sessions"], w.HORIZON)  # 新档 = 7

            # 长出 7 根 K 线 → 按真实收盘结算，同一次运行里再签发新预测
            grown = synthetic_closes(300, seed=11)[:82]
            now2 = datetime(2026, 4, 21, 9, 0, tzinfo=CST)
            r2 = self._run(grown, hp, now2)
            self.assertTrue(r2["available"])
            with open(hp, encoding="utf-8") as fh:
                journal = json.load(fh)
            self.assertEqual(len(journal["entries"]), 2)
            e0, e1 = journal["entries"]
            self.assertTrue(e0["settled"])
            self.assertEqual(e0["settle_date"], weekday_dates(82)[-1])
            # 结算内容 = 真实收盘价差与底牌方向的命中判定（独立复算对账；视界 7 → 索引 74→81）
            actual = grown[81] / grown[74] - 1.0
            self.assertAlmostEqual(e0["actual_ret"], actual, places=12)
            self.assertEqual(e0["hit"], bool((e0["p_up"] >= 0.5) == (actual > 0)))
            # 当次运行不可能结算当次预测：新签发的第二条必为未结算
            self.assertFalse(e1["settled"])
            self.assertEqual(e1["base_date"], weekday_dates(82)[-1])
            # 留痕统计：样本 <10 不下命中率结论
            self.assertEqual(r2["journal"]["n"], 1)
            self.assertIsNone(r2["journal"]["hit_rate"])
            self.assertGreaterEqual(r2["journal"]["hits"], 0)

    def test_unavailable_when_fetch_fails_or_bars_short(self):
        with tempfile.TemporaryDirectory() as td:
            hp = str(Path(td) / "wf.json")
            res = w.run_weekly(lambda *a, **k: None, history_path=hp)
            self.assertFalse(res["available"])
            self.assertIn("样本不足", res["reason"])
            res2 = w.run_weekly(None, history_path=hp)
            self.assertFalse(res2["available"])
            # 无数据时绝不写档案（不造假）
            self.assertFalse(Path(hp).exists())

    def test_run_weekly_self_check_reported(self):
        closes = synthetic_closes(300, seed=3)
        with tempfile.TemporaryDirectory() as td:
            hp = str(Path(td) / "wf.json")
            res = w.run_weekly(fake_chart_fetch(closes), history_path=hp,
                               now=datetime(2026, 5, 8, 9, 0, tzinfo=CST))
            self.assertTrue(res["available"])
            self.assertIn("逐位一致", res["self_check"])
            self.assertIn("entry", res)
            self.assertIn("backtest", res)


class WeeklyPipelineIntegrationTests(unittest.TestCase):
    """管线接入：fetch 降级 / 栏目渲染 / 顺序 / 审计 / 今日结论。"""

    def _result(self):
        closes = synthetic_closes(300, seed=5)[:75]
        with tempfile.TemporaryDirectory() as td:
            hp = str(Path(td) / "wf.json")
            return w.run_weekly(fake_chart_fetch(closes), history_path=hp,
                                now=datetime(2026, 4, 10, 9, 0, tzinfo=CST))

    def _source(self, res=None):
        res = res if res is not None else self._result()
        return {"source": "每周量化走势预测", "status": "success",
                "fetched_at": "2026-04-10 09:00:00",
                "is_today": True, "content_date": res.get("as_of"),
                "result": res}

    def test_fetch_weekly_forecast_switch_and_degradation(self):
        # 关闭开关 → unavailable，不调用引擎
        with patch.object(pipeline, "WEEKLY_ENABLED", False):
            res = pipeline.fetch_weekly_forecast()
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("关闭", res["error"])
        # 引擎异常 → 单源降级，不影响其它栏目
        with patch.object(pipeline, "_weekly") as fake:
            fake.run_weekly.side_effect = ValueError("boom")
            res = pipeline.fetch_weekly_forecast()
        self.assertEqual(res["status"], "unavailable")
        self.assertEqual(res["error"], "boom")
        # 样本不足 → unavailable + 原因
        with patch.object(pipeline, "_weekly") as fake:
            fake.run_weekly.return_value = {"available": False, "reason": "日线样本不足"}
            res = pipeline.fetch_weekly_forecast()
        self.assertEqual(res["status"], "unavailable")
        self.assertEqual(res["error"], "日线样本不足")

    def test_section_order_lock(self):
        order = pipeline.REPORT_SECTION_ORDER
        self.assertIn("WEEKLY FORECAST", order)
        self.assertLess(order.index("LIQUIDITY FLOW"), order.index("WEEKLY FORECAST"))
        # 2026-09-30 起「行情速览」+「全球大盘全景复盘」合并为 MARKET REVIEW 一栏
        # 2026-10-14 重排：MARKET REVIEW 属「①发生了什么」，先于「③可能会怎样」的 WEEKLY FORECAST
        self.assertLess(order.index("MARKET REVIEW"), order.index("WEEKLY FORECAST"))
        self.assertLess(order.index("WEEKLY FORECAST"), order.index("SUMMARY"))

    def test_render_section_in_both_themes(self):
        source = self._source()
        data = {"每周走势预测": source}
        date_display = "2026年4月10日 · 周五"
        for theme in ("guizang", "pixel"):
            plain_html = pipeline.generate_report(data, date_display, "20260410", theme=theme)
            self.assertIn(pipeline.SECTION_TITLE_WEEKLY_FORECAST, plain_html, theme)
            self.assertIn("P(7日涨)", plain_html, theme)
            self.assertNotIn("无未来函数口径", plain_html, theme)   # 入门版：口径披露不出
            with pipeline.notes_mode():
                html = pipeline.generate_report(data, date_display, "20260410", theme=theme)
            self.assertIn(pipeline.SECTION_TITLE_WEEKLY_FORECAST, html, theme)
            self.assertIn("无未来函数口径", html, theme)
            self.assertIn("截断不变性自检通过", html, theme)
            self.assertIn("先存档后结算", html, theme)
            # 审计口径：元数据总源数含每周预测（9 个基础源 + 每周走势预测 = 10）
            self.assertIn('octopus-total-sources" content="9"', html, theme)
            # 栏目副标题 = 来源名（_short_source）：数据源名不随栏目标题改名（2026-09-29）
            self.assertIn("每周量化走势预测", html, theme)
            self.assertGreaterEqual(
                html.count(pipeline.SECTION_TITLE_WEEKLY_FORECAST), 1, theme)
            # 最终今日预判包含七日方向结论（2026-09-29 起视界 5→7）
            self.assertIn("七日预测", html, theme)
            if theme == "pixel":
                self.assertIn("WEEKLY FORECAST", html)

    def test_render_absent_when_unavailable(self):
        data = {"每周走势预测": {"source": "每周量化走势预测", "status": "unavailable",
                                "is_today": False, "content_date": None,
                                "error": "日线样本不足"}}
        html = pipeline.generate_report(data, "2026年4月10日 · 周五", "20260410")
        self.assertNotIn("每周量化走势预测</h2>", html)
        self.assertNotIn(f"{pipeline.SECTION_TITLE_WEEKLY_FORECAST}</h2>", html)
        self.assertNotIn("七日预测", html)          # 栏目缺席时最终结论也不出现
        self.assertNotIn("逐日表格", html)

    def test_market_snapshot_before_weekly_section_in_html(self):
        data = {"每周走势预测": self._source(),
                "实时行情": {"source": "行情", "status": "success", "is_today": True,
                             "content_date": "2026-04-10",
                             "quotes": {"恒生指数": {"price": 24600, "change_pct": 0.38}}}}
        html = pipeline.generate_report(data, "2026年4月10日 · 周五", "20260410",
                                        theme="guizang")
        # 用栏目 kicker（只在正文栏目头出现）定位顺序，避免命中正文中的跨栏目引用。
        # 本回归显式选 Guizang，核对栏目头，不依赖默认主题。
        def _kicker_at(text, kicker):
            for anchor in (f"· {kicker}<", f"{kicker}</span>"):
                at = text.find(anchor)
                if at > -1:
                    return at
            return -1

        i_wk = _kicker_at(html, "WEEKLY FORECAST")
        i_mk = _kicker_at(html, "MARKET REVIEW")
        self.assertGreater(i_wk, -1)
        self.assertGreater(i_mk, -1)
        # 2026-10-14 重排：行情复盘（①）先于周度预测（③）
        self.assertLess(i_mk, i_wk)

    def test_collect_report_parts_counts_weekly_source(self):
        parts = pipeline._collect_report_parts({"每周走势预测": self._source()},
                                               pipeline.GUIZANG_KIT, date_str="20260410")
        # 8 个基础数据源 + 每周走势预测 = 9（财经日历 / Reddit / 新闻源头本次缺席）
        self.assertEqual(parts["total"], 9)
        self.assertEqual(parts["today_n"], 1)
        kickers = [s[0] for s in parts["sections"]]
        self.assertIn("WEEKLY FORECAST", kickers)
        # 审计状态表渲染出每周预测的审计标签（与港股量化引擎并列）
        footer = pipeline._status_footer([
            ("港股量化引擎", {"status": "success", "is_today": True,
                              "fetched_at": "2026-04-10 09:00:00"}),
            ("每周量化走势预测（恒指·7交易日）", self._source()),
        ])
        self.assertIn("每周量化走势预测（恒指·7交易日）", footer)
        self.assertIn("港股量化引擎", footer)


class DailyPathEngineTests(unittest.TestCase):
    """2026-09-29 起：未来 7 个交易日逐日表格引擎（纯函数，离线可复现）。

    覆盖 compute_path_signals（视界 1..7 一次扫描）、build_daily_path（7 行摊平）、
    build_advice（规则合成档位 / 仓位 / 止损止盈 / 事件提醒）、_var_horizon（分位自足）、
    trading_days_after（跳周末）、_lean_word（50% = 五五开），以及 7 视界截断不变性自检。
    """

    @classmethod
    def setUpClass(cls):
        cls.closes = synthetic_closes(300, seed=42)
        cls.dates = weekday_dates(len(cls.closes))
        cls.path = w.compute_path_signals(cls.closes)
        cls.var7 = w._var_horizon(cls.closes, w.PATH_MAX)

    def _daily(self, **over):
        kw = dict(vol_pct=None, base_date=self.dates[-1], symbol="^HSI",
                  events=None, var7=self.var7)
        kw.update(over)
        return w.build_daily_path(self.closes, self.dates,
                                  dict(self.path, horizon=w.PATH_MAX), **kw)

    # ---- compute_path_signals：一次扫描出 7 个视界 ----
    def test_compute_path_signals_covers_seven_horizons(self):
        self.assertTrue(self.path["ok"], self.path.get("reason"))
        self.assertEqual(tuple(self.path["horizons"]), tuple(range(1, 8)))
        by_h = self.path["signals_by_h"]
        self.assertEqual(sorted(by_h), list(range(1, 8)))
        for h in range(1, 8):
            col = by_h[h]
            self.assertEqual(len(col), len(self.closes), h)   # 逐 bar 一列，长度对齐
            last = col[-1]
            self.assertTrue(last, f"视界 {h} 最新 bar 应有信号")
            self.assertTrue(w.PROB_FLOOR <= last["p_up"] <= w.PROB_CAP, h)
            for key in ("p_base", "p_sim", "n_analog", "n_resolved", "features"):
                self.assertIn(key, last, (h, key))

    # ---- build_daily_path：7 行逐日表格 ----
    def test_build_daily_path_yields_seven_rows(self):
        d = self._daily()
        self.assertTrue(d["available"], d.get("reason"))
        self.assertEqual(d["horizon"], 7)
        self.assertEqual(d["symbol_label"], "恒生指数")
        self.assertAlmostEqual(d["base_close"], self.closes[-1])
        rows = d["rows"]
        self.assertEqual(len(rows), 7)
        prev_date = d["base_date"]
        for i, r in enumerate(rows, start=1):
            self.assertEqual(r["k"], i)
            self.assertEqual(r["target_sessions"], i)
            self.assertEqual(r["weekday"], w._weekday_cn(r["date"]))
            self.assertGreater(r["date"], prev_date)            # 严格递增、都在锚定日之后
            prev_date = r["date"]
            self.assertLess(datetime.strptime(r["date"], "%Y-%m-%d").weekday(), 5)  # 跳周末
            self.assertTrue(w.PROB_FLOOR <= r["p_up"] <= w.PROB_CAP, i)
            self.assertLess(r["band_lo"], d["base_close"])       # 80% 区间夹住锚定收盘
            self.assertGreater(r["band_hi"], d["base_close"])
            self.assertTrue(r["reason"] and r["analysis"], i)
            self.assertIsInstance(r["advice"], dict)

    def test_daily_dod_probability_chains_to_previous_row(self):
        """当日环比 = 上一行的累计概率（同一批数字，绝不另算一套）。"""
        rows = self._daily()["rows"]
        self.assertIsNone(rows[0]["p_day"])                      # T+1 没有「上一日」
        for i in range(1, 7):
            self.assertAlmostEqual(rows[i]["p_day"], rows[i - 1]["p_up"], places=9)

    def test_daily_event_reminds_on_day_and_within_holding_window(self):
        """事件日当天点名「当天有」；之后各天仍在持有窗口内 → 继续提醒；之前的天不挂事件。"""
        target = w.trading_days_after(self.dates[-1], 7)
        ev = [{"date": target[2], "name": "测试 CPI", "imp": 3}]
        rows = self._daily(events=ev)["rows"]

        def _idx(pred):
            return [i for i, r in enumerate(rows) if any(pred(n) for n in r["advice"]["notes"])]

        self.assertEqual(_idx(lambda n: "当天有 ★★★" in n), [2])           # 事件当天
        self.assertEqual(_idx(lambda n: "持有窗口内" in n and "★★★" in n), [3, 4, 5, 6])
        self.assertEqual(_idx(lambda n: "★★★" in n), [2, 3, 4, 5, 6])       # T+1/T+2 不受惊扰
        self.assertEqual(rows[0]["events"], [])
        self.assertEqual(rows[1]["events"], [])
        self.assertTrue(any(e["name"] == "测试 CPI" for e in rows[2]["events"]))

    def test_build_daily_path_degrades_honestly(self):
        short = w.build_daily_path(self.closes[:30], self.dates[:30],
                                   dict(self.path, horizon=w.PATH_MAX),
                                   base_date=self.dates[29], symbol="^HSI")
        self.assertFalse(short["available"])
        self.assertIn("样本不足", short["reason"])
        self.assertEqual(short["rows"], [])
        # 任一视界缺信号 → 整段降级，绝不用别的数据凑行
        blank = {"horizon": 7, "vol_hist": [],
                 "signals_by_h": {h: [None] * len(self.closes) for h in range(1, 8)}}
        miss = w.build_daily_path(self.closes, self.dates, blank,
                                  base_date=self.dates[-1], symbol="^HSI")
        self.assertFalse(miss["available"])
        self.assertEqual(miss["rows"], [])

    # ---- build_advice：规则合成档位 / 仓位 / 止损止盈 ----
    def _advice(self, p, **over):
        kw = dict(base_close=24000.0, vol20=0.01, k=3, vol_pct=None,
                  band_hi=24500.0, band_lo=23500.0, q95=None,
                  events=None, day_events=None)
        kw.update(over)
        return w.build_advice(p, **kw)

    def test_advice_tiers_position_and_stop_direction(self):
        bull = self._advice(0.70)
        self.assertEqual(bull["stance"], "积极看涨 · 顺势做多")
        self.assertEqual(bull["tone"], "看涨")
        self.assertEqual(bull["position"], 60)                   # 上限 60%，统计模型不给满仓
        self.assertLess(bull["stop_price"], 24000.0)             # 看涨止损挂下方
        self.assertEqual(bull["take_profit"], 24500.0)
        self.assertIn("分批建仓", bull["entry_hint"])
        self.assertEqual(bull["notes"][-1], "规则合成参考，非投资建议")

        flat = self._advice(0.50)
        self.assertEqual(flat["stance"], "中性 · 观望为主")
        self.assertEqual(flat["tone"], "中性")
        self.assertEqual(flat["position"], 5)                    # 非看跌档观察仓下限
        self.assertIn("底仓不动", flat["entry_hint"])

        bear = self._advice(0.30, k=2)
        self.assertEqual(bear["tone"], "看跌")
        self.assertEqual(bear["position"], 0)                    # 看跌档可以空仓
        self.assertGreater(bear["stop_price"], 24000.0)          # 看跌止损挂上方（减仓点）
        self.assertIn("减仓", bear["entry_hint"])

    def test_advice_high_volatility_shrinks_position(self):
        calm = self._advice(0.60, vol_pct=0.10)
        wild = self._advice(0.60, vol_pct=0.85)
        self.assertGreater(calm["position"], wild["position"])   # 高波动自动降杠杆
        self.assertTrue(any("偏高" in n for n in wild["notes"]))

    def test_advice_take_profit_takes_more_conservative_of_band_and_q95(self):
        # q95 给出的止盈比 80% 区间上沿更低时，取更低的那个（更保守）
        adv = self._advice(0.60, q95=0.005)                      # 24000×1.005=24120 < 24500
        self.assertAlmostEqual(adv["take_profit"], 24120.0)

    def test_advice_calendar_event_halves_execution(self):
        adv = self._advice(0.60, day_events=[{"date": "2026-04-13", "name": "CPI", "imp": 3}])
        self.assertTrue(any("★★★" in n and "减半执行" in n for n in adv["notes"]))
        # imp<3 的日程不触发减半提醒（不拿低级别日程吓人）
        calm = self._advice(0.60, day_events=[{"date": "2026-04-13", "name": "普通数据", "imp": 1}])
        self.assertFalse(any("减半执行" in n for n in calm["notes"]))

    # ---- _var_horizon / trading_days_after / _lean_word ----
    def test_var_horizon_quantiles_and_min_samples(self):
        v = self.var7
        self.assertIsNotNone(v)
        self.assertLess(v["q05"], v["q50"])
        self.assertLess(v["q50"], v["q95"])
        self.assertGreaterEqual(v["n"], 60)
        # 样本不足 → None（不给分位，绝不编造）
        self.assertIsNone(w._var_horizon(self.closes[:40], w.PATH_MAX, min_samples=60))

    def test_trading_days_after_skips_weekends(self):
        out = w.trading_days_after("2026-04-10", 7)               # 2026-04-10 是周五
        self.assertEqual(len(out), 7)
        prev = "2026-04-10"
        for ds in out:
            self.assertGreater(ds, prev)
            prev = ds
            self.assertLess(datetime.strptime(ds, "%Y-%m-%d").weekday(), 5)

    def test_lean_word_neutral_is_even_not_biased(self):
        self.assertEqual(w._lean_word(0.50), "五五开")
        self.assertEqual(w._lean_word(0.55), "略偏涨")
        self.assertEqual(w._lean_word(0.45), "略偏跌")

    # ---- 7 视界截断不变性自检（含 hk_seven_day 的 horizon= 兼容别名）----
    def test_no_lookahead_covers_all_seven_horizons(self):
        ok, msg = w.check_no_lookahead(self.closes)
        self.assertTrue(ok, msg)
        self.assertIn("视界", msg)
        self.assertTrue(w.check_no_lookahead(self.closes, horizon=7)[0])   # 别名（hk7 调用）
        self.assertTrue(w.check_no_lookahead(self.closes, max_horizon=3)[0])  # 子集也须成立


if __name__ == "__main__":
    unittest.main()
