"""低频小因子量化策略（output/lowfreq_factors.py）离线回归。

口径（与日报其它量化栏目一致）：
  · 取不到快照 / 日线 → available=False，绝不补造行情；
  · 只有显式 allow_synthetic（OCTOPUS_LOWFREQ_DEMO=1 / 测试）才用确定性合成序列，
    结果与页面都点名「演示序列」；
  · 小市值因子先剥壳价值（市值 ≤ 壳价下限 = 纯壳，剔除）；
  · 反转 = 近 21 个交易日 log 收益和；动量 = 12-1（250 剔除 21）；
  · 换手率 = 成交股数 / 流通股本，取近 63 日均值，方向为低换手优先；
  · EP = 1/PE，只对「市值达标 + 不亏损」的票做同行业内部比较，样本不足退回全市场并标注；
  · 综合分 = 各因子横截面分位加权，至少 3 个因子且可用权重 ≥ 60%，否则留空。
"""
import importlib.util
import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("requests", types.SimpleNamespace())
MODULE_PATH = Path(__file__).parents[1] / "output" / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_lowfreq_under_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

lf = pipeline._lowfreq


# ------------------------------------------------------------------
# 夹具
# ------------------------------------------------------------------
def make_bars(n=300, start=100.0, step=0.001, volume=4_000_000, tail=None):
    """确定性日线：主段按 ``step`` 复利，``tail`` 指定最后 k 根的累计对数收益。"""
    bars = []
    price = float(start)
    for i in range(n):
        price *= math.exp(step)
        bars.append({"date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                     "close": round(price, 4), "volume": int(volume)})
    if tail:
        k, total_log = tail
        base = bars[n - 1 - k]["close"]
        for j in range(k):
            bars[n - k + j]["close"] = round(base * math.exp(total_log * (j + 1) / k), 4)
    return bars


def snapshot_row(code, name, mcap, pe, price=10.0, industry="", float_ratio=0.6):
    return {
        "code": code, "name": name, "price": price, "chg_pct": 0.0,
        "amount": mcap * 0.01, "turnover_today": 0.5, "pe": pe,
        "mcap": mcap, "float_cap": mcap * float_ratio, "pb": 1.2,
        "industry": industry,
    }


def base_cfg(**over):
    cfg = lf.params()
    cfg.update({"universe": 320, "top_n": 20, "shell_floor": 3e8, "min_amount": 1e7,
                "ep_min_cap": 2e9, "min_peers": 5, "weights": dict(lf.DEFAULT_WEIGHTS),
                # 算法单测用小门槛；出版门槛本身另有专项测试（test_publish_gate_*）
                "min_publish_ranked": 1, "min_publish_share": 0.0})
    cfg.update(over)
    return cfg


def universe_fixture():
    """8 只可比较的股票 + 各类应当被剔除 / 特殊处理的样本。"""
    rows, bars = [], {}
    # 银行 5 只（同行业可比，≥ min_peers），EP 各不相同
    for i, pe in enumerate((5.0, 8.0, 12.0, 20.0, 40.0)):
        code = f"0000{i + 1}"
        rows.append(snapshot_row(code, f"测试银行{i + 1}", 5e10 + i * 1e9, pe, industry="银行"))
        bars[code] = make_bars(step=0.0002 * (i + 1), volume=8_000_000)
    # 科技 2 只：同行业只有 2 只 → EP 退回全市场分位
    for i in range(2):
        code = f"0001{i + 1}"
        rows.append(snapshot_row(code, f"测试科技{i + 1}", 3e10, 15.0, industry="软件与互联网"))
        bars[code] = make_bars(step=-0.0005 * (i + 1), volume=9_000_000)
    # 小市值但高于壳价、低于 EP 门槛：只参与四个因子
    rows.append(snapshot_row("000201", "测试小盘", 8e8, 6.0))
    bars["000201"] = make_bars(step=0.0001, volume=3_000_000)
    # 纯壳：市值低于壳价下限
    rows.append(snapshot_row("000301", "测试纯壳", 2e8, 3.0))
    bars["000301"] = make_bars()
    # 流动性不足：成交量极低
    rows.append(snapshot_row("000401", "测试冷门", 6e10, 10.0))
    bars["000401"] = make_bars(volume=1000)
    # 亏损股：PE < 0
    rows.append(snapshot_row("000501", "测试亏损", 4e10, -6.0))
    bars["000501"] = make_bars(step=-0.001)
    # 无日线
    rows.append(snapshot_row("000601", "测试无日线", 5e10, 9.0))
    return rows, bars


# ------------------------------------------------------------------
# 计算层
# ------------------------------------------------------------------
class LowFreqFormulaTests(unittest.TestCase):
    def test_log_return_sum_matches_definition(self):
        bars = make_bars(n=60, start=100.0, step=0.0)
        for i, bar in enumerate(bars):
            bar["close"] = 100.0 * math.exp(0.01 * i)
        got = lf.log_return_sum(bars, 21)
        self.assertAlmostEqual(got, 0.21, places=9)

    def test_momentum_uses_250_lookback_and_skips_21(self):
        bars = make_bars(n=300, step=0.0)
        for i, bar in enumerate(bars):
            bar["close"] = 100.0 * math.exp(0.002 * i)
        got = lf.momentum_12_1(bars)
        self.assertAlmostEqual(got, 0.002 * (len(bars) - 1 - 21 - (len(bars) - 1 - 250)), places=9)
        # 日线不足 251 根 → None（不硬算，也不退化成 21 日反转）
        self.assertIsNone(lf.momentum_12_1(make_bars(n=200)))

    def test_mean_turnover_uses_shares_and_needs_history(self):
        bars = make_bars(n=100, volume=1_000_000)
        for bar in bars:
            bar["close"] = 10.0
        # 流通市值 1e9 / 价格 10 = 1 亿流通股；每日 100 万股 = 1%
        got = lf.mean_turnover(bars, float_cap=1e9, price=10.0)
        self.assertAlmostEqual(got, 1.0, places=6)
        self.assertIsNone(lf.mean_turnover(bars[:5], float_cap=1e9, price=10.0))
        self.assertIsNone(lf.mean_turnover(bars, float_cap=None, price=10.0))

    def test_percentile_scores_are_monotone_and_tie_averaged(self):
        scores = lf.percentile_scores({"a": 1.0, "b": 2.0, "c": 3.0})
        self.assertLess(scores["a"], scores["b"])
        self.assertLess(scores["b"], scores["c"])
        self.assertAlmostEqual(scores["b"], 50.0, places=6)
        rev = lf.percentile_scores({"a": 1.0, "b": 2.0, "c": 3.0}, higher_is_better=False)
        self.assertGreater(rev["a"], rev["c"])
        tie = lf.percentile_scores({"a": 1.0, "b": 1.0})
        self.assertEqual(tie["a"], tie["b"])
        self.assertEqual(lf.percentile_scores({"a": 1.0}), {})

    def test_industry_ep_falls_back_to_market_when_peers_are_few(self):
        ep = {"a": 0.20, "b": 0.10, "c": 0.05, "d": 0.02, "e": 0.01}
        industries = {"a": "银行", "b": "银行", "c": "银行", "d": "银行", "e": "银行"}
        scores, meta = lf.industry_ep_scores(ep, industries, min_peers=5)
        self.assertEqual(meta["银行"]["basis"], "同行业")
        self.assertGreater(scores["a"], scores["e"])
        scores2, meta2 = lf.industry_ep_scores(ep, industries, min_peers=6)
        self.assertTrue(meta2["银行"]["basis"].startswith("全市场"))
        self.assertIn("a", scores2)

    def test_classify_industry_prefers_source_field(self):
        self.assertEqual(lf.classify_industry("腾讯控股", "软件"), "软件")
        self.assertEqual(lf.classify_industry("腾讯控股"), "软件与互联网")
        self.assertEqual(lf.classify_industry("某某控股有限公司"), "未分类")


# ------------------------------------------------------------------
# 打分与门槛
# ------------------------------------------------------------------
class LowFreqScoringTests(unittest.TestCase):
    def setUp(self):
        rows, bars = universe_fixture()
        self.rows, self.bars = rows, bars
        self.res = lf.score_universe(rows, bars, base_cfg())

    def _by_code(self, code):
        return next(s for s in self.res["stocks"] if s["code"] == code)

    def test_available_and_counts(self):
        self.assertTrue(self.res["available"])
        excluded = self.res["universe"]["excluded"]
        self.assertEqual(excluded["shell"], 1)        # 纯壳
        self.assertEqual(excluded["illiquid"], 1)     # 冷门
        self.assertEqual(excluded["no_bars"], 1)      # 无日线
        codes = {s["code"] for s in self.res["stocks"]}
        self.assertNotIn("000301", codes)
        self.assertNotIn("000401", codes)
        self.assertNotIn("000601", codes)

    def test_small_cap_factor_strips_shell_value(self):
        # 小市值因子的原值是 -ln(市值 - 壳价下限)，不是 -ln(市值)
        small = self._by_code("000201")
        self.assertAlmostEqual(small["size_raw"], -math.log(8e8 - 3e8), places=9)
        self.assertAlmostEqual(small["shell_ratio"], 3e8 / 8e8, places=9)

    def test_ep_excludes_loss_and_micro_cap_and_uses_industry(self):
        loss = self._by_code("000501")
        self.assertTrue(loss["loss"])
        self.assertIsNone(loss["ep"])               # 亏损不进 EP
        self.assertIn("价值 EP", loss["missing_factors"])
        small = self._by_code("000201")
        self.assertIsNone(small["ep"])              # 微市值不进 EP
        bank = [self._by_code(c) for c in ("00001", "00002", "00003", "00004", "00005")]
        self.assertTrue(all(s["ep"] is not None for s in bank))
        # 同行业 EP：PE 最低（EP 最高）的银行分位应最高
        self.assertGreater(bank[0]["scores"]["ep"], bank[4]["scores"]["ep"])

    def test_composite_needs_three_factors_and_reweights(self):
        loss = self._by_code("000501")
        self.assertEqual(loss["factor_count"], 4)
        weights = base_cfg()["weights"]
        expect = sum(loss["scores"][k] * weights[k]
                     for k in ("size", "reversal", "momentum", "turnover")) / 0.8
        self.assertAlmostEqual(loss["composite"], expect, places=6)

    def test_short_history_stock_gets_no_composite(self):
        bars = dict(self.bars)
        bars["00001"] = make_bars(n=20)            # 不足 22 根
        res = lf.score_universe(self.rows, bars, base_cfg())
        self.assertTrue(all(s["code"] != "00001" for s in res["stocks"]))
        self.assertEqual(res["universe"]["excluded"]["short_bars"], 1)

    def test_top_n_is_twenty_by_default(self):
        self.assertEqual(lf.params()["top_n"], 20)   # 用户要求：港股推荐 20 个
        self.assertLessEqual(len(self.res["top"]), 20)
        ranks = [s["rank"] for s in self.res["top"]]
        self.assertEqual(ranks, sorted(ranks))

    def test_reversal_mirror_reports_market_temperature(self):
        mirrors = self.res["mirrors"]
        self.assertIsNotNone(mirrors["reversal_median"])
        self.assertIsNotNone(mirrors["reversal_up_share"])
        self.assertGreaterEqual(mirrors["reversal_up_share"], 0)
        self.assertLessEqual(mirrors["reversal_up_share"], 100)

    def test_unavailable_without_any_bars(self):
        """一只日线都没有：栏目整栏缺席，但快照层的合格池仍如实报出（不谎称 0）。"""
        res = lf.score_universe(self.rows, {}, base_cfg())
        self.assertFalse(res["available"])
        self.assertIn("日线全缺", res["reason"])
        self.assertEqual(res["universe"]["with_bars"], 0)
        # 12 只快照里 1 只是纯壳 → 合格池 11 只
        self.assertEqual(res["universe"]["eligible"], 11)
        self.assertEqual(res["top"], [])
        self.assertFalse(res["publish"])


# ------------------------------------------------------------------
# 编排：默认不合成、合成需显式开启且可复现
# ------------------------------------------------------------------
class LowFreqRunnerTests(unittest.TestCase):
    def test_offline_without_fetch_is_unavailable(self):
        res = lf.run_lowfreq_factors(None, date_str="20261028", allow_synthetic_flag=False)
        self.assertFalse(res["available"])
        self.assertIn("未注入取数函数", res["reason"])

    def test_disabled_by_env(self):
        with patch.dict("os.environ", {"OCTOPUS_LOWFREQ": "0"}):
            res = lf.run_lowfreq_factors(None, date_str="20261028", allow_synthetic_flag=True)
        self.assertFalse(res["available"])
        self.assertTrue(res.get("disabled"))

    def test_synthetic_only_when_explicit_and_deterministic(self):
        first = lf.run_lowfreq_factors(None, date_str="20261028", allow_synthetic_flag=True)
        second = lf.run_lowfreq_factors(None, date_str="20261028", allow_synthetic_flag=True)
        self.assertTrue(first["available"])
        self.assertTrue(first["synthetic"])
        self.assertEqual([s["code"] for s in first["top"]], [s["code"] for s in second["top"]])
        self.assertEqual([round(s["composite"], 6) for s in first["top"]],
                         [round(s["composite"], 6) for s in second["top"]])

    def test_fetch_failure_without_demo_flag_returns_empty(self):
        def failing(url, params=None, timeout=10):
            return None
        with patch.dict("os.environ", {"OCTOPUS_LOWFREQ_DEMO": "0"}):
            res = lf.run_lowfreq_factors(failing, date_str="20261028")
        self.assertFalse(res["available"])

    def test_snapshot_and_bars_path_produces_top_list(self):
        rows, bars = universe_fixture()

        def fake_snapshot(fetch_json, **kw):
            return {"items": rows, "pages": 1, "complete": True, "reported_total": len(rows),
                    "errors": [], "served_urls": []}

        with patch.object(lf, "fetch_hk_snapshot", fake_snapshot), \
                patch.object(lf, "fetch_hk_bars", lambda *a, **k: bars), \
                patch.dict("os.environ", {"OCTOPUS_LOWFREQ_DEMO": "0",
                                          "OCTOPUS_LOWFREQ_MIN_RANKED": "1",
                                          "OCTOPUS_LOWFREQ_MIN_COVERAGE": "0"}):
            res = lf.run_lowfreq_factors(lambda *a, **k: {}, date_str="20261028")
        self.assertTrue(res["available"])
        self.assertFalse(res["synthetic"])
        self.assertTrue(res["publish"])
        self.assertEqual(len(res["top"]), min(20, res["universe"]["ranked"]))
        self.assertEqual(res["snapshot"]["bars_requested"], res["snapshot"]["bars_fetched"])


# ------------------------------------------------------------------
# 2026-10-28 生产事故回归：日线抓取残缺 → 横截面偏向大市值
# ------------------------------------------------------------------
def ladder_fixture(n=320, with_bars=37):
    """复现事故现场：320 只按市值降序的池子，只有前 ``with_bars`` 只（最大的）抓到日线。"""
    rows = []
    for i in range(n):
        mcap = max(2.6e11 * (0.55 ** (i / 20)), 4e8)
        rows.append({"code": f"{i:05d}", "name": f"样本{i:03d}", "price": 20.0, "chg_pct": 0.0,
                     "amount": 2e8, "turnover_today": 0.4, "pe": 8.0 + (i % 20),
                     "mcap": mcap, "float_cap": mcap * 0.6, "pb": 1.1, "industry": ""})
    bars = {rows[i]["code"]: make_bars(n=300, step=0.0002 * i) for i in range(with_bars)}
    return rows, bars


class BarCoverageIncidentTests(unittest.TestCase):
    """事故根因与修复：分位口径 + 抓取顺序 + 出版门槛 + 流动性兜底。"""

    def setUp(self):
        self.rows, self.bars = ladder_fixture()
        cfg = lf.params()
        cfg.update({"universe": 320, "top_n": 20, "shell_floor": 3e8, "min_amount": 1e7,
                    "ep_min_cap": 2e9, "min_peers": 5, "weights": dict(lf.DEFAULT_WEIGHTS)})
        self.cfg = cfg                       # 用默认出版门槛（不做放宽）
        self.res = lf.score_universe(self.rows, self.bars, self.cfg)

    def test_size_percentile_uses_full_pool_not_bar_subset(self):
        """最大的票（2600 亿）不能因为「在抓到日线的子集里最小」而被当成小市值。"""
        biggest = min(self.res["stocks"], key=lambda s: s["mcap"])
        self.assertGreater(biggest["mcap"], 5e10)            # 抓到日线的都是大票
        self.assertLess(biggest["scores"]["size"], 15.0)     # 全池口径：仍是「大市值 → 分位很低」
        self.assertNotIn("市值小", biggest["reason"])

    def test_ep_percentile_also_uses_full_pool(self):
        ep_factor = next(f for f in self.res["factors"] if f["key"] == "ep")
        self.assertEqual(ep_factor["universe_n"], self.res["universe"]["eligible"])
        size_factor = next(f for f in self.res["factors"] if f["key"] == "size")
        self.assertEqual(size_factor["universe_n"], self.res["universe"]["eligible"])

    def test_publish_gate_blocks_list_on_thin_coverage(self):
        uni = self.res["universe"]
        self.assertTrue(self.res["available"])               # 有快照、有部分日线：栏目还在
        self.assertLess(uni["bars_coverage"], 60)
        self.assertFalse(self.res["publish"])                # 但名单不发
        self.assertEqual(self.res["top"], [])
        self.assertIn("门槛", self.res["publish_reason"])
        self.assertTrue(any("日线只覆盖" in w for w in self.res["warnings"]))

    def test_publish_gate_passes_with_full_coverage(self):
        rows, bars = ladder_fixture(with_bars=320)
        res = lf.score_universe(rows, bars, self.cfg)
        self.assertTrue(res["publish"])
        self.assertEqual(len(res["top"]), 20)
        self.assertGreaterEqual(res["universe"]["bars_coverage"], 99)

    def test_render_discloses_coverage_and_withheld_list(self):
        html = lf.render(self.res, pipeline.LIME_KIT, plain=False)
        self.assertIn("样本覆盖", html)
        self.assertIn("名单暂缓", html)
        self.assertNotIn("港股推荐 20 只", html)
        # 入门版也必须看到覆盖披露
        plain = lf.render(self.res, pipeline.LIME_KIT, plain=True)
        self.assertIn("样本覆盖", plain)

    def test_fetch_order_is_not_market_cap_order(self):
        """抓取顺序必须与市值无关：否则限流会整段掐掉小票。"""
        codes_desc = [f"{i:05d}" for i in range(40)]        # 已按市值降序传入
        order = lf._fetch_order(codes_desc)
        self.assertEqual(sorted(order), sorted(codes_desc))  # 不丢不重
        self.assertNotEqual(order, codes_desc)               # 打散
        self.assertEqual(order, lf._fetch_order(list(reversed(codes_desc))))  # 确定性

    def test_bars_retry_levels_escalate(self):
        calls = []

        def fake_batch(fetch_json, specs, rng="1y", workers=6, timeout=12):
            calls.append((rng, workers, timeout))
            # 第一轮只给前一半，重试再补齐
            take = len(specs) if len(calls) > 1 else max(1, len(specs) // 2)
            return {sym: make_bars(n=30) for _l, sym in specs[:take]}

        import octopus_quant.providers as providers
        original = providers.fetch_series_batch
        providers.fetch_series_batch = fake_batch
        try:
            out = lf.fetch_hk_bars(lambda *a, **k: {}, [f"{i:05d}" for i in range(10)])
        finally:
            providers.fetch_series_batch = original
        self.assertEqual(len(out), 10)                        # 重试补齐
        self.assertGreaterEqual(len(calls), 2)
        self.assertLessEqual(calls[1][1], calls[0][1])        # 降并发
        self.assertGreaterEqual(calls[1][2], calls[0][2])     # 加超时

    def test_liquidity_falls_back_to_snapshot_amount_without_volume(self):
        rows = [snapshot_row("000901", "测试无量", 5e10, 10.0)]
        bars = {"000901": [{"date": f"2026-01-{i + 1:02d}", "close": 10.0, "volume": None}
                           for i in range(30)]}
        cfg = base_cfg(min_amount=1e7)
        res = lf.score_universe(rows, bars, cfg)
        self.assertEqual(res["universe"]["with_bars"], 1)
        self.assertEqual(res["universe"]["liquidity_basis"]["今日成交额"], 1)
        self.assertTrue(any("快照当日成交额" in w for w in res["warnings"]))


# ------------------------------------------------------------------
# 呈现层
# ------------------------------------------------------------------
class LowFreqRenderTests(unittest.TestCase):
    def setUp(self):
        self.res = lf.run_lowfreq_factors(None, date_str="20261028", allow_synthetic_flag=True)

    def test_render_contains_all_five_factors_and_twenty_picks(self):
        html = lf.render(self.res, pipeline.LIME_KIT, plain=False)
        for word in ("因子镜子", "港股推荐", "组合画像", "剔除与风险披露",
                     "综合分", "壳价值", "EP"):
            self.assertIn(word, html)
        self.assertIn("20 只", html)
        for key in lf.FACTOR_ORDER:
            self.assertIn(lf.FACTOR_META[key]["name"], html)

    def test_demo_banner_is_explicit(self):
        html = lf.render(self.res, pipeline.LIME_KIT, plain=False)
        self.assertIn("合成演示序列", html)

    def test_plain_mode_hides_methodology_rows(self):
        plain = lf.render(self.res, pipeline.LIME_KIT, plain=True)
        self.assertNotIn("剔除与风险披露", plain)
        self.assertIn("港股推荐", plain)

    def test_empty_result_renders_nothing(self):
        self.assertEqual(lf.render({"available": False}, pipeline.LIME_KIT), "")

    def test_all_themes_render(self):
        for kit in (pipeline.LIME_KIT, pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT,
                    pipeline.DOSSIER_KIT, pipeline.FORUM_KIT):
            html = lf.render(self.res, kit)
            self.assertGreater(len(html), 500)


# ------------------------------------------------------------------
# 日报接入
# ------------------------------------------------------------------
class LowFreqPipelineTests(unittest.TestCase):
    def test_section_registered_after_industry_rotation(self):
        self.assertIn("LOWFREQ FACTORS", pipeline.REPORT_SECTION_ORDER)
        self.assertGreater(pipeline.REPORT_SECTION_ORDER.index("LOWFREQ FACTORS"),
                           pipeline.REPORT_SECTION_ORDER.index("INDUSTRY ROTATION"))
        self.assertLess(pipeline.REPORT_SECTION_ORDER.index("LOWFREQ FACTORS"),
                        pipeline.REPORT_SECTION_ORDER.index("SUMMARY"))

    def test_title_and_source_name(self):
        self.assertEqual(pipeline.SECTION_TITLE_LOWFREQ, "【慢游小丑鱼】低频小因子量化策略")
        self.assertEqual(pipeline.LOWFREQ_SOURCE_NAME, "低频小因子量化策略")

    def test_theme_metadata_present(self):
        self.assertIn("LOWFREQ FACTORS", pipeline._SECTION_ICON_META)
        self.assertIn("LOWFREQ FACTORS", pipeline.DOSSIER_ICONS)
        self.assertIn("LOWFREQ FACTORS", pipeline.FORUM_ICONS)

    def test_fetch_entry_returns_none_when_disabled(self):
        with patch.dict("os.environ", {"OCTOPUS_LOWFREQ": "0"}):
            with patch.object(pipeline, "LOWFREQ_ENABLED", False):
                self.assertIsNone(pipeline.fetch_lowfreq_factors("20261028"))

    def test_block_rendered_from_data(self):
        res = lf.run_lowfreq_factors(None, date_str="20261028", allow_synthetic_flag=True)
        src = {"source": pipeline.LOWFREQ_SOURCE_NAME, "status": "success",
               "fetched_at": "2026-10-28 09:00", "is_today": False,
               "content_date": res.get("as_of"), "result": res}
        parts = pipeline._collect_report_parts(
            {pipeline.LOWFREQ_SOURCE_NAME: src}, pipeline.LIME_KIT, date_str="20261028")
        kicks = [s[0] for s in parts["sections"]]
        self.assertIn("LOWFREQ FACTORS", kicks)
        block = next(s for s in parts["sections"] if s[0] == "LOWFREQ FACTORS")
        self.assertEqual(block[1], pipeline.SECTION_TITLE_LOWFREQ)
        self.assertIn("港股推荐", block[2])

    def test_absent_without_data_key(self):
        parts = pipeline._collect_report_parts({}, pipeline.LIME_KIT, date_str="20261028")
        self.assertNotIn("LOWFREQ FACTORS", [s[0] for s in parts["sections"]])


if __name__ == "__main__":
    unittest.main()
