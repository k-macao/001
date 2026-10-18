"""【游资剑鱼】多专家流派趋势分析的离线回归（全部不联网）。

覆盖：
  · vendored 规则引擎装载（66 位评委 / 242 条规则）与缺席降级；
  · 指标口径（满窗口 MA、Weinstein 四阶段、RSI / KDJ / Williams%R、区间收益窗口）；
  · 「缺数据不打假分」——算不出来的特征让规则整条出局，评委按准入门禁整位撤下并点名；
  · run_trend 的覆盖 / 缺项 / 定调；
  · pipeline 集成：私有日线键用完即弃、五套主题渲染、入门版与全量版差异、HTML 转义；
  · 「🦑 AI帮你提鲜」接入（2026-10-13）：解读数字与正文同一份 run_trend() 结果、
    本栏无概率口径故几率条缺席、栏目缺席 / 关解读时的降级行为。
"""
import importlib.util
import math
import os
import sys
import types
import unittest
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("requests", types.SimpleNamespace())
ROOT = Path(__file__).parents[1]
OUTPUT = ROOT / "output"
if str(OUTPUT) not in sys.path:
    sys.path.insert(0, str(OUTPUT))

import market_db
from octopus_quant import macd_strategy as macd, providers, uzi_trend as uzi

spec = importlib.util.spec_from_file_location("pipeline_under_uzi_test", OUTPUT / "pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)
CST = providers.CST
NOW = datetime(2026, 10, 2, 13, 30, tzinfo=CST)
END = date(2026, 9, 30)


def series(n=260, drift=0.4, wiggle=0.6, end=END, volume=True):
    """确定性日线：drift 控制方向，wiggle 给一点噪声（不引入随机数，回归可复现）。"""
    days, day = [], end
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day -= timedelta(days=1)
    days.reverse()
    out = []
    for i, day in enumerate(days):
        price = 100 * math.exp(drift / 100 * i) + math.sin(i / 4) * wiggle
        out.append({"date": day, "close": round(price, 4), "open": round(price, 4),
                    "high": round(price * 1.004, 4), "low": round(price * 0.996, 4),
                    "volume": 100000 + i * 100 if volume else None})
    return out


def two_symbols():
    return {"^HSI": series(260, drift=0.4), "000001.SS": series(260, drift=-0.4)}


SPECS = [("恒生指数", "^HSI"), ("上证指数", "000001.SS")]


class EngineLoadTest(unittest.TestCase):
    def test_vendored_engine_is_loaded_with_full_roster(self):
        engine = uzi.load_engine(force=True)
        self.assertIsNotNone(engine, uzi.engine_error())
        self.assertEqual(len(engine["investors"]), 66)
        self.assertEqual(sum(len(v) for v in engine["rules"].values()), 242)
        self.assertTrue(engine["commit"].startswith("650788c5"))
        self.assertTrue(Path(engine["path"], "lib", "investor_evaluator.py").is_file())

    def test_missing_engine_degrades_instead_of_faking_scores(self):
        with patch.dict(os.environ, {"OCTOPUS_UZI_SKILL": "/nonexistent/uzi"}):
            self.assertIsNone(uzi.load_engine(force=True))
            self.assertIn("未找到 UZI-Skill 规则引擎", uzi.engine_error())
            result = uzi.run_trend(two_symbols(), specs=SPECS, now=NOW)
            self.assertFalse(result["available"])
            self.assertIn("规则引擎", result["reason"])
            row = uzi.analyze_symbol(series(260), label="恒生指数", code="^HSI", now=NOW)
            self.assertFalse(row["available"])
        self.assertIsNotNone(uzi.load_engine(force=True))    # 还原，避免影响后续用例

    def test_default_panel_is_the_price_only_judges(self):
        self.assertEqual(uzi.panel_ids(), ["livermore", "minervini", "darvas", "gann", "simons"])
        with patch.dict(os.environ, {"OCTOPUS_UZI_PANEL": "all"}):
            self.assertGreater(len(uzi.panel_ids()), 5)
        with patch.dict(os.environ, {"OCTOPUS_UZI_PANEL": "gann,darvas"}):
            self.assertEqual(uzi.panel_ids(), ["gann", "darvas"])


class IndicatorTest(unittest.TestCase):
    def test_ma_requires_full_window(self):
        values = list(range(1, 31))
        ma = uzi._ma(values, 20)
        self.assertIsNone(ma[18])
        self.assertAlmostEqual(ma[19], sum(values[:20]) / 20)
        self.assertAlmostEqual(ma[-1], sum(values[-20:]) / 20)

    def test_weinstein_stage_follows_ma200(self):
        closes_up = [100 * math.exp(0.004 * i) for i in range(300)]
        closes_down = [100 * math.exp(-0.004 * i) for i in range(300)]
        self.assertEqual(uzi._stage(closes_up, uzi._ma(closes_up, 200)), 2)
        self.assertEqual(uzi._stage(closes_down, uzi._ma(closes_down, 200)), 4)
        # MA200 历史不足（<20 根）→ 不给阶段，不用短窗口硬凑
        self.assertIsNone(uzi._stage(closes_up[:210], uzi._ma(closes_up[:210], 200)))

    def test_stage_slope_window_needs_ma200_history(self):
        self.assertEqual(uzi.stage_slope_window(219), 0)      # MA200 历史只有 20 根 → 不够
        self.assertEqual(uzi.stage_slope_window(220), 20)
        self.assertEqual(uzi.stage_slope_window(252), 52)
        self.assertEqual(uzi.stage_slope_window(500), uzi.STAGE_SLOPE_MAX)

    def test_short_series_reports_insufficient_bars(self):
        ind = uzi.compute_indicators(series(40), code="^HSI")
        self.assertFalse(ind["available"])
        self.assertIn("已收盘日线不足", ind["reason"])

    def test_indicator_values_are_finite_and_windowed(self):
        ind = uzi.compute_indicators(series(260, drift=0.4), code="^HSI")
        self.assertTrue(ind["available"])
        self.assertEqual(ind["bars_n"], 260)
        self.assertEqual(ind["stage_num"], 2)
        self.assertTrue(ind["ma_bull_aligned"])
        self.assertGreater(ind["rsi"], 60)
        self.assertLess(ind["rsi"], 100)
        self.assertGreater(ind["kdj_j"], ind["kdj_d"] - 200)
        self.assertLessEqual(ind["williams_r"], 0)
        self.assertGreater(ind["pct_from_60d_high"], -25)
        self.assertEqual(ind["ytd_window"], 252)             # 满 252 根 → 上游口径
        closes = [bar["close"] for bar in series(260, drift=0.4)]
        self.assertAlmostEqual(ind["ytd_return"],
                               (closes[-1] / closes[-253] - 1) * 100, delta=0.01)
        self.assertGreater(ind["volatility_1y"], 0)
        self.assertTrue(ind["obv_trend_up"])

    def test_missing_volume_leaves_obv_absent_not_false(self):
        ind = uzi.compute_indicators(series(260, drift=0.4, volume=False), code="^HSI")
        self.assertIsNone(ind["obv_trend_up"])
        self.assertFalse(ind["volume_available"])

    def test_lookback_return_falls_back_to_available_window(self):
        short = uzi.compute_indicators(series(150, drift=0.4), code="^HSI")
        self.assertEqual(short["ytd_window"], 149)
        self.assertIsNotNone(short["ytd_return"])
        tiny = uzi.compute_indicators(series(120, drift=0.4), code="^HSI")
        self.assertIsNone(tiny["ytd_return"])                # 不足 120 根不冒充 YTD


class FeatureAndPanelTest(unittest.TestCase):
    def test_features_only_carry_computable_keys(self):
        ind = uzi.compute_indicators(series(260, drift=0.4), code="^HSI")
        features = uzi.build_features(ind, label="恒生指数", code="^HSI")
        self.assertEqual(features["market"], "HK")
        self.assertEqual(features["stage_num"], 2)
        self.assertTrue(features["ma_bull_aligned"])
        # 150 根：MA 多头排列够窗口（≥120），Weinstein 阶段不够（≥220）→ 只放前者
        mid = uzi.build_features(uzi.compute_indicators(series(150, drift=0.4), code="^HSI"),
                                 label="恒生指数", code="^HSI")
        self.assertTrue(mid["ma_bull_aligned"])
        self.assertNotIn("stage_num", mid)
        # 100 根：两个都不够 → 两个键都缺席（不以默认值顶替）
        tiny = uzi.build_features(uzi.compute_indicators(series(100, drift=0.4), code="^HSI"),
                                  label="恒生指数", code="^HSI")
        self.assertNotIn("stage_num", tiny)
        self.assertNotIn("ma_bull_aligned", tiny)

    def test_market_of_follows_this_repo_symbol_style(self):
        self.assertEqual(uzi.market_of("000001.SS"), "A")
        self.assertEqual(uzi.market_of("399006.SZ"), "A")
        self.assertEqual(uzi.market_of("^HSI"), "HK")
        self.assertEqual(uzi.market_of("0700.HK"), "HK")
        self.assertEqual(uzi.market_of("^GSPC"), "US")

    def test_stage_rules_drop_out_when_stage_is_unknown(self):
        engine = uzi.load_engine(force=True)
        ind = uzi.compute_indicators(series(150, drift=0.4), code="^HSI")
        features = uzi.build_features(ind, label="恒生指数", code="^HSI")
        rows, coverage, dropped = uzi.evaluate_panel(features, engine, uzi.panel_ids(engine))
        names = {row["id"] for row in rows}
        self.assertIn("minervini", names)
        self.assertNotIn("darvas", names)                    # 只剩 1/2 条 → 整位撤下
        self.assertIn("达瓦斯", [k for k in (engine["by_id"][i]["name"] for i in dropped)])
        for row in rows:
            self.assertNotIn("处于 Stage 2 上升期", row["rule_names"])
            self.assertNotIn("严格 Stage 2 (SEPA 核心)", row["rule_names"])

    def test_coverage_gate_can_be_relaxed(self):
        engine = uzi.load_engine(force=True)
        ind = uzi.compute_indicators(series(150, drift=0.4), code="^HSI")
        features = uzi.build_features(ind, label="恒生指数", code="^HSI")
        with patch.dict(os.environ, {"OCTOPUS_UZI_MIN_COVERAGE": "0"}):
            rows, _coverage, _dropped = uzi.evaluate_panel(features, engine, uzi.panel_ids(engine))
            # 权重门禁放开后，仍要满足「可评估规则 ≥2 条」：达瓦斯 / 江恩只剩 1 条 → 仍撤下
            self.assertEqual({row["id"] for row in rows}, {"livermore", "minervini", "simons"})
        with patch.dict(os.environ, {"OCTOPUS_UZI_MIN_COVERAGE": "0"}), \
                patch.object(uzi, "MIN_PANEL_RULES", 1):
            rows, _coverage, _dropped = uzi.evaluate_panel(features, engine, uzi.panel_ids(engine))
        self.assertEqual(len(rows), 5)                       # 两道门禁都放开 → 5 位全进


class RunTrendTest(unittest.TestCase):
    def test_rising_and_falling_series_get_opposite_tones(self):
        result = uzi.run_trend(two_symbols(), specs=SPECS, now=NOW)
        self.assertTrue(result["available"])
        tones = {row["label"]: row for row in result["items"]}
        self.assertEqual(tones["恒生指数"]["tone_key"], "up")
        self.assertEqual(tones["上证指数"]["tone_key"], "down")
        self.assertGreaterEqual(tones["恒生指数"]["bullish_n"], 4)   # 西蒙斯看波动，可能中性
        self.assertEqual(tones["恒生指数"]["bearish_n"], 0)
        self.assertEqual(tones["上证指数"]["bearish_n"], 5)
        self.assertEqual(result["rules_enabled"], 14)
        self.assertEqual(result["rules_total"], 242)
        self.assertEqual(result["coverage"], {"valid": 2, "total": 2})
        self.assertEqual(result["as_of"], series(1)[0]["date"])

    def test_missing_symbols_are_named_not_invented(self):
        result = uzi.run_trend({"^HSI": series(260, drift=0.4)}, specs=SPECS, now=NOW)
        self.assertTrue(result["available"])
        self.assertEqual(result["coverage"], {"valid": 1, "total": 2})
        self.assertEqual(result["missing"][0]["label"], "上证指数")
        self.assertIn("没有可用已收盘日线", result["missing"][0]["reason"])

    def test_all_symbols_missing_means_section_absent(self):
        result = uzi.run_trend({}, specs=SPECS, now=NOW)
        self.assertFalse(result["available"])
        self.assertIn("全部标的", result["reason"])

    def test_unclosed_intraday_bar_never_becomes_the_signal_bar(self):
        moment = datetime(2026, 10, 2, 11, 0, tzinfo=CST)     # 港股盘中
        bars = series(260, drift=0.4, end=date(2026, 10, 2))
        row = uzi.analyze_symbol(bars, label="恒生指数", code="^HSI", now=moment)
        self.assertTrue(row["available"])
        self.assertLess(row["as_of"], "2026-10-02")          # 未收盘的当天日线被剔除
        self.assertEqual(row["bars_n"], 259)


class RenderTest(unittest.TestCase):
    def result(self):
        return uzi.run_trend(two_symbols(), specs=SPECS, now=NOW)

    def test_all_five_themes_render_the_section(self):
        result = self.result()
        for kit in (pipeline.LIME_KIT, pipeline.PIXEL_KIT, pipeline.GUIZANG_KIT,
                    pipeline.FORUM_KIT, pipeline.DOSSIER_KIT):
            html = uzi.render_trend(result, kit)
            self.assertIn("多专家流派趋势分析", html)
            self.assertIn("恒生指数", html)
            self.assertIn("Stage 2 上升", html)

    def test_html_is_escaped(self):
        result = self.result()
        result["items"][0]["label"] = "<script>bad</script>"
        for kit in (pipeline.LIME_KIT, pipeline.PIXEL_KIT):
            html = uzi.render_trend(result, kit)
            self.assertNotIn("<script>", html)
            self.assertIn("&lt;script&gt;", html)

    def test_plain_mode_hides_rules_but_keeps_conclusion(self):
        result = self.result()
        plain = uzi.render_trend(result, pipeline.LIME_KIT, plain=True)
        full = uzi.render_trend(result, pipeline.LIME_KIT, plain=False)
        self.assertIn("评委结论", plain)
        self.assertNotIn("规则覆盖", plain)
        self.assertNotIn("方法来源", plain)
        self.assertIn("规则覆盖", full)
        self.assertIn("方法来源", full)
        self.assertIn("准入门禁", full)

    def test_truncated_rows_are_disclosed(self):
        result = self.result()
        html = uzi.render_trend(result, pipeline.LIME_KIT, limit=1, plain=True)
        self.assertIn("已收起 1 个有效标的", html)

    def test_empty_result_renders_nothing(self):
        self.assertEqual(uzi.render_trend({"available": False}, pipeline.LIME_KIT), "")
        self.assertEqual(uzi.render_trend(None, pipeline.LIME_KIT), "")


class MacdBarsHandoffTest(unittest.TestCase):
    def test_include_bars_is_opt_in(self):
        existing = {"^HSI": macd.completed_bars(series(80), "^HSI", now=NOW)}
        with patch("market_db.load_daily_bars", return_value={}):
            plain = macd.run_macd(None, existing=existing, specs=SPECS[:1], now=NOW)
            with_bars = macd.run_macd(None, existing=existing, specs=SPECS[:1], now=NOW,
                                      include_bars=True)
        self.assertNotIn("bars_by_code", plain)
        self.assertEqual(len(with_bars["bars_by_code"]["^HSI"]), 80)
        self.assertEqual(with_bars["items"][0]["as_of"], with_bars["bars_by_code"]["^HSI"][-1]["date"])


class PipelineIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.bars = two_symbols()

    def test_disabled_flag_skips_the_section_entirely(self):
        with patch.object(pipeline, "UZI_TREND_ENABLED", False):
            self.assertIsNone(pipeline.fetch_uzi_trend({}, self.bars))

    def test_no_bars_means_unavailable_source(self):
        source = pipeline.fetch_uzi_trend({}, {})
        self.assertEqual(source["status"], "unavailable")
        self.assertIn("没有可用已收盘日线", source["error"])

    def test_success_source_carries_result_and_content_date(self):
        source = pipeline.fetch_uzi_trend({}, self.bars)
        self.assertEqual(source["status"], "success")
        self.assertEqual(source["source"], pipeline.UZI_TREND_SOURCE_LABEL)
        self.assertTrue(source["result"]["available"])
        self.assertEqual(source["content_date"], source["result"]["latest_as_of"])
        self.assertNotIn("_bars_by_code", source)

    def test_macd_source_hands_bars_over_as_private_key(self):
        macd_result = {"available": True, "items": [], "missing": [], "warnings": [],
                       "coverage": {"valid": 0, "total": 0}, "as_of": None,
                       "latest_as_of": None, "golden_n": 0, "death_n": 0,
                       "bars_by_code": self.bars}
        with patch.object(pipeline._quant.macd_strategy, "run_macd", return_value=macd_result), \
                patch.object(pipeline, "_note_backup_served"):
            source = pipeline.fetch_macd_strategy({})
        self.assertEqual(set(source["_bars_by_code"]), {"^HSI", "000001.SS"})
        self.assertNotIn("bars_by_code", source["result"])
        # 私有键交给趋势栏目后立即消失，不进 data / 不入库
        trend = pipeline.fetch_uzi_trend({pipeline.MACD_SOURCE_NAME: source}, None)
        self.assertEqual(trend["status"], "success")
        self.assertNotIn("_bars_by_code", source)

    def test_section_title_is_in_analysis_order(self):
        self.assertEqual(pipeline.SECTION_TITLE_UZI_TREND, "【游资剑鱼】多专家流派趋势分析")
        self.assertIn("UZI TREND", pipeline.REPORT_ANALYSIS_SECTIONS)
        order = pipeline.REPORT_ANALYSIS_SECTIONS
        self.assertLess(order.index("STRATEGY READ"), order.index("UZI TREND"))
        # 2026-10-14 重排：UZI 趋势与策略研判同属「④我们该怎么办」，位于板块轮动之前
        self.assertLess(order.index("UZI TREND"), order.index("SECTOR ROTATION"))
        self.assertIn("UZI TREND", pipeline.REPORT_SECTION_ORDER)

    def test_render_helper_respects_availability(self):
        source = pipeline.fetch_uzi_trend({}, self.bars)
        for kit in (pipeline.LIME_KIT, pipeline.PIXEL_KIT, pipeline.GUIZANG_KIT,
                    pipeline.FORUM_KIT, pipeline.DOSSIER_KIT):
            self.assertIn("多专家流派趋势分析", pipeline._render_uzi_trend(source, kit))
        self.assertEqual(pipeline._render_uzi_trend({"status": "unavailable"}, pipeline.LIME_KIT), "")
        self.assertEqual(pipeline._render_uzi_trend({"status": "success", "result": {}},
                                                    pipeline.LIME_KIT), "")

    def test_env_switch_turns_the_section_off(self):
        with patch.dict(os.environ, {"OCTOPUS_UZI_TREND": "0"}):
            self.assertFalse(uzi.enabled())                  # 开关按调用时读取环境变量
        self.assertTrue(uzi.enabled())


class ReportIntegrationTest(unittest.TestCase):
    """整份日报层面的集成：栏目位置、五套主题、缺席时的审计口径。"""

    def _data(self, uzi_status="success"):
        macd_row = macd.analyze_bars(series(80), label="恒生指数", code="^HSI", now=NOW)
        data = {pipeline.MACD_SOURCE_NAME: pipeline._source_result(
            pipeline.MACD_SOURCE_NAME, "success", content_date="2026-09-30",
            result={"available": True, "items": [macd_row], "missing": [], "warnings": [],
                    "coverage": {"valid": 1, "total": 1}, "as_of": macd_row["as_of"],
                    "latest_as_of": macd_row["as_of"], "golden_n": 0, "death_n": 0,
                    "derived_coverage": {}})}
        if uzi_status == "success":
            data[pipeline.UZI_TREND_SOURCE_NAME] = pipeline.fetch_uzi_trend({}, two_symbols())
        else:
            data[pipeline.UZI_TREND_SOURCE_NAME] = pipeline._source_result(
                pipeline.UZI_TREND_SOURCE_LABEL, "unavailable", error="本次没有可用已收盘日线")
        return data

    def _html(self, data, theme):
        with patch.object(pipeline, "safe_request", side_effect=AssertionError("渲染不能联网")), \
                patch.object(market_db, "load_daily_bars", side_effect=AssertionError("渲染不能读库")):
            return pipeline.generate_report(data, "2026年10月2日", "20261002", theme=theme)

    def test_section_lands_between_strategy_and_quant_forecast_in_every_theme(self):
        data = self._data()
        for theme in ("lime", "guizang", "pixel", "forum", "dossier"):
            html = self._html(data, theme)
            self.assertIn(pipeline.SECTION_TITLE_UZI_TREND, html, theme)
            self.assertIn("多专家流派趋势分析 · 已收盘日线", html, theme)
            self.assertIn("Stage 2 上升", html, theme)
            self.assertLess(html.find(pipeline.SECTION_TITLE_STRATEGY),
                            html.find(pipeline.SECTION_TITLE_UZI_TREND), theme)
            self.assertLess(html.find(pipeline.SECTION_TITLE_UZI_TREND),
                            html.find("总结"), theme)      # 专业分析栏目一律在结论之前

    def test_plain_report_keeps_conclusion_and_drops_rule_detail(self):
        data = self._data()
        plain = self._html(data, "lime")
        with pipeline.notes_mode():
            full = self._html(data, "lime")
        self.assertIn("评委结论", plain)
        self.assertNotIn("方法来源", plain)
        self.assertIn("方法来源", full)
        self.assertIn("准入门禁", full)

    def test_absent_section_is_named_in_coverage_audit(self):
        html = self._html(self._data("unavailable"), "lime")
        self.assertNotIn(pipeline.SECTION_TITLE_UZI_TREND, html)
        self.assertNotIn("多专家流派趋势分析 · 已收盘日线", html)
        self.assertIn(pipeline.UZI_TREND_SOURCE_NAME, html)   # 数据覆盖里点名缺席
        parts = pipeline._collect_report_parts(self._data("unavailable"), pipeline.LIME_KIT,
                                               date_str="20261002")
        self.assertNotIn("UZI TREND", [section[0] for section in parts["sections"]])

    def test_section_carries_its_own_ren_block_with_same_source_numbers(self):
        """「🦑 AI帮你提鲜」接进本栏（2026-10-13）：解读引用的数字与正文同一份结果。

        真跑 run_trend()（不手搓 fixture）：ctx["uzi"] 与 blocks["UZI TREND"] 走
        pipeline._uzi_result() 同一个出口，解读里的数字必须能在正文结果里逐字对上。
        """
        data = self._data()
        result = data[pipeline.UZI_TREND_SOURCE_NAME]["result"]
        self.assertTrue(result["available"])
        html = self._html(data, "guizang")
        self.assertIn(pipeline.SECTION_TITLE_UZI_TREND, html)
        self.assertIn("趋势评审团：", html)
        cover, panel = result["coverage"], result["panel"]
        self.assertIn(f"观察池 {cover['total']} 只里 {cover['valid']} 只这次算出了结果", html)
        self.assertIn(f"{panel['investors']} 位方法评委按 {result['rules_enabled']} 条规则投票",
                      html)
        self.assertIn(f"看多 {panel['bullish']} / 看空 {panel['bearish']} / "
                      f"中性 {panel['neutral']}", html)
        # 定调用语取 items 自带的 tone（与正文同一套 _verdict，不另写一份翻译）
        for row in result["items"]:
            self.assertIn(row["tone"], html)
        # 本栏没有概率口径 → 解读块不出几率条（绝不硬凑一个涨跌概率）
        block = pipeline._ren.section_ren_block(
            "UZI TREND", {"uzi": result, "date_str": "20261002"})
        self.assertIsNotNone(block)
        self.assertIsNone(block["p_pct"])
        self.assertIsNone(block["label"])

    def test_ren_block_disappears_with_the_section(self):
        """栏目缺席时解读一起缺席：不留一句硬编的大白话。"""
        self.assertNotIn("趋势评审团：", self._html(self._data("unavailable"), "guizang"))

    def test_ren_can_be_switched_off_without_touching_the_section(self):
        """OCTOPUS_REN=0 / --no-ren 与其它栏目同一开关：关解读不关栏目。"""
        data = self._data()
        with patch.object(pipeline, "REN_ENABLED", False):
            html = self._html(data, "guizang")
        self.assertIn(pipeline.SECTION_TITLE_UZI_TREND, html)
        self.assertIn("多专家流派趋势分析 · 已收盘日线", html)
        self.assertNotIn("趋势评审团：", html)


if __name__ == "__main__":
    unittest.main()
