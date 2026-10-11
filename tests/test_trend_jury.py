# -*- coding: utf-8 -*-
"""趋势分析模块（【深海剑鱼】趋势多维评审团 · UZI-Skill 方法移植）离线回归。

守护的是「方法」而不是「运气」：
  ① 规则引擎三态（命中 / 未达 / 数据不足即 skip，缺数据绝不能算成看空）；
  ② 权重通过率打分 + 65/35 阈值 + 覆盖率打折的置信度（上限 95，不出现 100% 把握）；
  ③ 流派锁定（SCHOOL LOCK）只让该派评委参与，其余记 skip 且原因可追溯；
  ④ 数据闸门：日线不足 / 滞后 / 关键维度缺失 → 不进评审并在缺项点名；
  ⑤ 截面相对强度必须全池就位后二阶段裁决（<3 只不排名）；
  ⑥ 趋势失效风险 8 信号每格都有「命中 / 未命中 / 数据不足」；
  ⑦ 禁用空泛话术 + 定调句必须带数字；
  ⑧ 与日报的接线：采集 → 审计计数 → 两主题渲染 → 逐栏 AI 研判 → 关开关后不留痕。

沙箱 / CI 都访问不到 Yahoo 与东方财富，全部用假日线与假网络驱动，绝不联网。
"""
import copy
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("requests", types.SimpleNamespace())
OUTPUT = Path(__file__).parents[1] / "output"
if str(OUTPUT) not in sys.path:
    sys.path.insert(0, str(OUTPUT))

from octopus_quant import providers, stats, trend_jury as tj   # noqa: E402

spec = importlib.util.spec_from_file_location("pipeline_under_trend_jury_test", OUTPUT / "pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

CST = providers.CST
NOW = datetime(2026, 10, 11, 9, 0, tzinfo=CST)
AS_OF = date(2026, 10, 9)          # 周五收盘，周日跑日报：滞后 2 天，仍在门槛内


def bars(n=260, end=AS_OF, drift=0.0025, vol=0.012, seed=7, with_ohlc=True):
    """确定性假日线（同 seed 同形状）：周末跳过，close/open/high/low/volume 齐全。"""
    rnd = seed

    def rand():
        nonlocal rnd
        rnd = (rnd * 1103515245 + 12345) % 2147483648
        return rnd / 2147483648 - 0.5

    days, day = [], end
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    days = list(reversed(days))
    price, out = 100.0, []
    for d in days:
        price *= (1 + drift + rand() * vol)
        open_ = price * (1 + rand() * 0.004)
        high = max(open_, price) * (1 + abs(rand()) * 0.006)
        low = min(open_, price) * (1 - abs(rand()) * 0.006)
        row = {"date": d.isoformat(), "close": price, "volume": 1e6 * (1 + abs(rand()))}
        if with_ohlc:
            row.update({"open": open_, "high": high, "low": low})
        out.append(row)
    return out


def ups(**kw):
    return bars(seed=3, drift=0.0028, **kw)


def downs(**kw):
    return bars(seed=11, drift=-0.0030, **kw)


def flats(**kw):
    return bars(seed=99, drift=0.0, vol=0.002, **kw)


EXTRAS = {
    "breadth_up_n": 3200, "breadth_down_n": 1700, "breadth_ratio_txt": "涨跌比 1.88",
    "turnover_chg_pct": 6.4, "sector_net": 0.9, "sector_up_n": 8, "sector_dn_n": 5,
    "liquidity_score": 58.0,
    "crowd_bull": 30, "crowd_bear": 18, "crowd_net": 12, "crowd_nbi": 25.0,
    "crowd_nbi_txt": "+25.0/100",
    "headline_bull": 10, "headline_bear": 6, "headline_net": 4,
}

THREE = [("恒生指数", "^HSI"), ("恒生科技", "^HSTECH"), ("上证指数", "000001.SS")]
POOL = {"^HSI": ups(), "^HSTECH": downs(), "000001.SS": flats()}


def run_pool(existing=None, **kw):
    kw.setdefault("extras", EXTRAS)
    kw.setdefault("specs", THREE)
    kw.setdefault("now", NOW)
    kw.setdefault("db_root", str(Path(tempfile.mkdtemp(prefix="tj-db-"))))  # 绝不读仓库真实库
    return tj.run_trend(None, existing=existing if existing is not None else dict(POOL), **kw)


def kit_html(result, theme_kit, *, limit=0, plain=False):
    return tj.render_jury(result, theme_kit, limit=limit, plain=plain)


# ------------------------------------------------------------------
# ① 规则引擎：三态裁决与阈值
# ------------------------------------------------------------------
class RuleEngineTests(unittest.TestCase):
    def test_every_judge_has_at_least_four_rules(self):
        """上游「每人 ≥4 规则」的回归门槛：低于 4 条的评委不许进池。"""
        for judge in tj.JUDGES:
            self.assertGreaterEqual(len(judge.rules), 4, judge.id)
            self.assertEqual(len({r.rule_id for r in judge.rules}), len(judge.rules), judge.id)
        self.assertEqual(sum(len(j.rules) for j in tj.JUDGES), tj.RULE_TOTAL_N)

    def test_every_judge_maps_to_a_known_school(self):
        for judge in tj.JUDGES:
            self.assertIn(judge.school, tj.SCHOOLS)

    def test_rule_ids_unique_across_judges(self):
        seen = [r.rule_id for j in tj.JUDGES for r in j.rules]
        self.assertEqual(len(seen), len(set(seen)))

    def test_missing_dimension_skips_rule_instead_of_failing_it(self):
        """缺数据 → skip（不占分母）：这是上游 _safe_check 的核心口径。"""
        judge = tj.JUDGE_BY_ID["oneill"]          # 全部规则依赖截面 RS 维度
        empty = {"ok": True, "close": 100.0}
        verdict = tj.evaluate_judge(judge, empty)
        self.assertEqual(verdict["signal"], "skip")
        self.assertIsNone(verdict["score"])
        self.assertIn("低于", verdict["reason"])
        self.assertEqual(verdict["weight_total"], 0)
        self.assertEqual(len(verdict["skip_rules"]), len(judge.rules))

    def test_partial_data_lowers_coverage_and_confidence(self):
        full = tj.build_features(ups(), code="^HSI", extras=EXTRAS, now=NOW)
        self.assertTrue(full["ok"])
        judge = tj.JUDGE_BY_ID["gann"]
        rich = tj.evaluate_judge(judge, full)
        thin = dict(full)
        for key in ("slope_per_bar", "atr_val", "fib_gap", "days_from_lo", "ma50"):
            thin[key] = None
        poor = tj.evaluate_judge(judge, thin)
        self.assertLessEqual(poor["coverage"], rich["coverage"])
        if poor["signal"] != "skip":
            self.assertLess(poor["confidence"], rich["confidence"])

    def test_signal_thresholds_match_upstream(self):
        judge = tj.JUDGE_BY_ID["minervini"]
        feat = {"close": 120.0, "ma150": 110.0, "ma200": 100.0, "ma50": 115.0,
                "ma200_up": True, "ma200_chg_pct": 1.2, "dist_lo_252": 45.0,
                "dist_hi_252": -3.0, "range_collapse": 0.4}
        verdict = tj.evaluate_judge(judge, feat)
        self.assertEqual(verdict["signal"], "bullish")
        self.assertGreaterEqual(verdict["score"], tj.BULLISH_THRESHOLD)
        self.assertTrue(all(1 <= rule.weight <= 5 for rule in judge.rules))

    def test_confidence_never_reaches_certainty(self):
        for code, series in (("^HSI", ups()), ("^HSTECH", downs()), ("000001.SS", flats())):
            feat = tj.build_features(series, code=code, extras=EXTRAS, now=NOW)
            for judge in tj.JUDGES:
                verdict = tj.evaluate_judge(judge, feat)
                if verdict["confidence"] is not None:
                    self.assertLessEqual(verdict["confidence"], 95, judge.id)
                    self.assertGreaterEqual(verdict["confidence"], 10, judge.id)

    def test_evidence_messages_carry_numbers(self):
        """每条命中 / 未达都要引用具体数字（上游：禁止空泛话术、必须定量）。"""
        feat = tj.build_features(ups(), code="^HSI", extras=EXTRAS, now=NOW)
        verdict = tj.evaluate_judge(tj.JUDGE_BY_ID["minervini"], feat)
        rules = verdict["pass_rules"] + verdict["fail_rules"]
        self.assertTrue(rules)
        import re
        for rule in rules:
            self.assertTrue(re.search(r"\d", rule["msg"]), rule["rule_id"] + ": " + rule["msg"])
        self.assertNotIn("{", verdict["headline"])       # 占位符必须已被替换
        self.assertNotIn("?", verdict["headline"])       # 缺失值不应出现在证据里


# ------------------------------------------------------------------
# ② 数据闸门：不足就不进评审
# ------------------------------------------------------------------
class DataGateTests(unittest.TestCase):
    def test_too_few_bars_is_unavailable_with_reason(self):
        row = tj.analyze_bars(bars(n=80), label="恒生指数", code="^HSI", now=NOW)
        self.assertFalse(row["available"])
        self.assertIn(f"{tj.MIN_BARS}", row["reason"])

    def test_no_price_data_never_invents_a_verdict(self):
        row = tj.analyze_bars([], label="恒生指数", code="^HSI", now=NOW)
        self.assertFalse(row["available"])
        self.assertIsNone(row.get("score"))

    def test_stale_bars_are_rejected_by_the_panel(self):
        stale = bars(n=260, end=AS_OF - timedelta(days=30))
        result = tj.run_trend(None, existing={"^HSI": stale}, specs=[("恒生指数", "^HSI")],
                              extras=EXTRAS, now=NOW,
                              db_root=str(Path(tempfile.mkdtemp(prefix="tj-db-"))))
        self.assertFalse(result["available"])
        self.assertIn("日线过旧", result["missing"][0]["reason"])

    def test_missing_extras_are_listed_as_missing_dims(self):
        """没有环境读数时，那些维度进 missing_keys（保留为缺失，不当 0）。"""
        row = tj.analyze_bars(ups(), label="恒生指数", code="^HSI", extras={}, now=NOW)
        self.assertTrue(row["available"])
        for key in ("liquidity_score", "crowd_net", "headline_net", "turnover_chg_pct"):
            self.assertIn(key, row["dims"]["missing_keys"])
        self.assertFalse(row["dims"]["critical_missing"])
        self.assertLess(row["dims"]["available"], row["dims"]["total"])

    def test_critical_dimension_missing_blocks_row(self):
        """关键维度（收盘价 / 50 日线 / 20 日动量 / 箱体上沿…）缺任何一个 → 整行不进评审。"""
        fake = {"ok": True, "code": "^HSI", "close": 100.0, "date": "2026-10-09",
                "bars_n": 260, "ma50": None, "ret_20": 1.0, "ma_align": 1,
                "trend_t": 1.0, "box_hi_20": 99.0}
        with patch.object(tj, "build_features", return_value=fake):
            row = tj.prepare_row(bars(), label="恒生指数", code="^HSI", now=NOW)
        self.assertFalse(row["available"])
        self.assertIn("50 日均线", row["reason"])

    def test_empty_panel_renders_nothing(self):
        result = tj.run_trend(None, existing={}, specs=THREE, extras=EXTRAS, now=NOW,
                              db_root=str(Path(tempfile.mkdtemp(prefix="tj-db-"))))
        self.assertFalse(result["available"])
        self.assertEqual(kit_html(result, pipeline.GUIZANG_KIT), "")


# ------------------------------------------------------------------
# ③ 趋势定调的方向性：同一段规则必须能区分涨跌
# ------------------------------------------------------------------
class VerdictTests(unittest.TestCase):
    def test_uptrend_scores_above_downtrend(self):
        up = tj.analyze_bars(ups(), label="A", code="^HSI", extras=EXTRAS, now=NOW)
        down = tj.analyze_bars(downs(), label="B", code="^HSTECH", extras=EXTRAS, now=NOW)
        self.assertTrue(up["available"] and down["available"])
        self.assertGreater(up["score"], down["score"])
        self.assertEqual(up["mark"], "▲")
        self.assertIn(down["mark"], ("▼", "■"))
        self.assertGreater(up["metrics"]["box"], down["metrics"]["box"])

    def test_stage_label_is_derived_not_hardcoded(self):
        up = tj.analyze_bars(ups(), label="A", code="^HSI", extras=EXTRAS, now=NOW)
        down = tj.analyze_bars(downs(), label="B", code="^HSTECH", extras=EXTRAS, now=NOW)
        self.assertEqual(up["metrics"]["stage"], "Stage 2 上升")
        self.assertEqual(down["metrics"]["stage"], "Stage 4 下跌")

    def test_absent_extras_skip_env_judge_instead_of_fake_neutral(self):
        """没有环境读数时，环境派整位 skip——不能拿 0 当「中性」把分数抹平。"""
        solo = tj.run_trend(None, existing={"^HSI": ups()}, specs=[("恒生指数", "^HSI")],
                            extras={}, now=NOW,
                            db_root=str(Path(tempfile.mkdtemp(prefix="tj-db-"))))
        row = solo["items"][0]
        env = next(j for j in row["judges"] if j["judge_id"] == "env")
        self.assertEqual(env["signal"], "skip")
        self.assertIn("可评权重", env["reason"])

    def test_cross_section_rank_requires_three_symbols(self):
        solo = tj.analyze_bars(ups(), label="A", code="^HSI", extras=EXTRAS, now=NOW)
        self.assertIsNone(solo["feat"].get("rs_rank"))          # 单只不排名
        result = run_pool()
        rows = {r["label"]: r for r in result["items"]}
        ranks = [r["feat"]["rs_rank"] for r in rows.values()]
        self.assertTrue(all(v is not None for v in ranks))
        self.assertEqual(max(ranks), 100.0 * stats.pct_rank(max(ranks) / 100.0,
                                                            [v / 100.0 for v in ranks]))
        self.assertEqual(rows["恒生指数"]["metrics"]["rs_rank"], max(ranks))   # 上行样本排最前

    def test_panel_judges_are_evaluated_after_cross_section(self):
        """二阶段裁决：截面维度补齐后欧奈尔评委必须参与（回归「永远 skip」的旧 bug）。"""
        result = run_pool()
        oneill = next(b for b in result["board"] if b["id"] == "oneill")
        self.assertEqual(oneill["skip"], 0)
        self.assertIsNotNone(oneill["avg_score"])


# ------------------------------------------------------------------
# ④ 流派锁定（移植上游 --school + banner）
# ------------------------------------------------------------------
class SchoolLockTests(unittest.TestCase):
    def test_lock_keeps_only_that_school(self):
        result = run_pool(school_lock="A")
        self.assertEqual(result["school_lock"]["label"], "趋势跟随")
        row = result["items"][0]
        for judge in row["judges"]:
            if judge["school"] == "A":
                self.assertNotEqual(judge["signal"], "skip", judge["name"])
            else:
                self.assertEqual(judge["signal"], "skip", judge["name"])
                self.assertIn("锁定", judge["reason"])
        self.assertEqual(row["counts"]["skip"], len(tj.JUDGES) - 4)      # 4 位 A 派参与
        self.assertEqual(result["consensus"]["judge_skip"],
                         row["counts"]["skip"] * len(result["items"]))     # 全池累计

    def test_lock_banner_shown_in_plain_mode(self):
        html = kit_html(run_pool(school_lock="A"), pipeline.LIME_KIT, limit=4, plain=True)
        self.assertIn("流派锁定", html)
        self.assertIn("不代表全体结论", html)

    def test_env_var_lock_roundtrip(self):
        with patch.dict(os.environ, {"OCTOPUS_TREND_SCHOOL": "f"}):
            self.assertEqual(tj.locked_school(), "F")
        with patch.dict(os.environ, {"OCTOPUS_TREND_SCHOOL": "Z"}):
            self.assertEqual(tj.locked_school(), "")


# ------------------------------------------------------------------
# ⑤ 风险八信号 + 话术闸门 + 自检
# ------------------------------------------------------------------
class RiskAndGateTests(unittest.TestCase):
    def test_eight_risk_signals_always_three_state(self):
        for series in (ups(), downs(), flats(), bars(n=260, with_ohlc=False)):
            row = tj.analyze_bars(series, label="X", code="^HSI", extras=EXTRAS, now=NOW)
            self.assertEqual(len(row["risks"]), 8)
            for risk in row["risks"]:
                self.assertIn(risk["state"], ("命中", "未命中", "数据不足"))
                if risk["state"] == "命中":
                    self.assertTrue(risk["evidence"])      # 命中必须给证据

    def test_false_breakout_signal_fires(self):
        """第 3 根前突破「当时」的 20 日上沿、如今又跌回去 → 假突破命中（手工构造，不靠运气）。"""
        series = flats()
        pivot = max(row["high"] for row in series[-23:-3])
        series[-3] = dict(series[-3], close=pivot * 1.03, high=pivot * 1.032, low=pivot * 1.02)
        series[-2] = dict(series[-2], close=pivot * 1.00, high=pivot * 1.005, low=pivot * 0.99)
        series[-1] = dict(series[-1], close=pivot * 0.98, high=pivot * 0.99, low=pivot * 0.97)
        row = tj.analyze_bars(series, label="X", code="^HSI", extras=EXTRAS, now=NOW)
        hit = {r["id"]: r for r in row["risks"]}
        self.assertEqual(hit["break_back"]["state"], "命中")
        self.assertIn("按假突破处理", hit["break_back"]["evidence"])
        self.assertEqual(round(row["feat"]["break_pivot"], 6), round(pivot, 6))
        self.assertFalse(any(r["state"] == "命中" for r in
                             tj.analyze_bars(flats(), label="Y", code="^HSI",
                                              extras=EXTRAS, now=NOW)["risks"]
                             if r["id"] == "break_back"))

    def test_no_breakout_event_is_miss_not_missing_data(self):
        """窗口内压根没突破事件 = 未命中；样本不足（<22 根）才是「数据不足」。"""
        quiet = tj.analyze_bars(flats(), label="Q", code="^HSI", extras=EXTRAS, now=NOW)
        risk = {r["id"]: r for r in quiet["risks"]}["break_back"]
        self.assertEqual(risk["state"], "未命中")
        self.assertIsNone(quiet["feat"]["break_pivot"])       # 无突破事件 → 没有枢轴价
        self.assertEqual(quiet["feat"]["break_state"], "miss")

        # 样本不足时 break_state 为 None（无从判定），扫描器必须写「数据不足」而不是「未命中」
        unknown = {r["id"]: r for r in tj.scan_risks({"break_state": None})}["break_back"]
        self.assertEqual(unknown["state"], "数据不足")
        self.assertEqual(unknown["evidence"], "")
        thin = tj.analyze_bars(flats()[:20], label="S", code="^HSI", extras=EXTRAS, now=NOW)
        self.assertFalse(thin["available"])
        self.assertIn(str(tj.MIN_BARS), thin["reason"])      # 样本不足：整行不进评审并写明原因

    def test_banned_phrases_gate(self):
        self.assertTrue(tj.fluff_check("估值合理，基本面良好"))
        self.assertTrue(tj.fluff_check("该股值得关注"))
        self.assertEqual(tj.fluff_check("20 日 +4.30%，距年线 +27.15%"), [])

    def test_punchline_is_quantitative_and_fluff_free(self):
        result = run_pool()
        line = result["consensus"]["punchline"]
        self.assertTrue(any(ch.isdigit() for ch in line), line)
        self.assertEqual(tj.fluff_check(line), [])
        self.assertIn("平均趋势分", line)

    def test_self_check_passes_on_a_normal_run_and_reports_failures(self):
        result = run_pool()
        self.assertTrue(result["self_check"]["all_ok"], result["self_check"]["checks"])
        broken = copy.deepcopy(result)
        broken["items"][0]["risks"] = broken["items"][0]["risks"][:3]
        self.assertFalse(tj.self_check(broken)["all_ok"])

    def test_methodology_log_documents_the_derivation(self):
        row = tj.analyze_bars(ups(), label="A", code="^HSI", extras=EXTRAS, now=NOW)
        joined = " ".join(row["log"])
        for step in ("Step 1", "Step 2", "Step 3", "Step 4", "Step 5", "Step 6"):
            self.assertIn(step, joined)
        self.assertIn(str(row["bars_n"]), joined)
        self.assertIn(str(row["dims"]["available"]), joined)


# ------------------------------------------------------------------
# ⑥ 渲染：入门版只留结论与数字，全量版补口径与推导链
# ------------------------------------------------------------------
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_pool()

    def test_both_modes_and_themes_render(self):
        for kit_name in ("LIME_KIT", "GUIZANG_KIT", "PIXEL_KIT", "FORUM_KIT", "DOSSIER_KIT"):
            kit = getattr(pipeline, kit_name)
            full = kit_html(self.result, kit)
            lite = kit_html(self.result, kit, limit=2, plain=True)
            self.assertIn("趋势评审团", full)
            self.assertIn("评委打分板", full)
            self.assertIn("趋势失效风险", full)
            self.assertIn("趋势评审团", lite)
            self.assertLess(len(lite), len(full))

    def test_plain_mode_drops_methodology_text_but_keeps_numbers(self):
        plain = kit_html(self.result, pipeline.LIME_KIT, limit=3, plain=True)
        notes = kit_html(self.result, pipeline.LIME_KIT, limit=3, plain=False)
        for marker in ("方法来源", "计算口径", "推导链"):
            self.assertIn(marker, notes)
            self.assertNotIn(marker, plain)
        self.assertIn("趋势分", plain)
        self.assertRegex(plain, r"\d+\.\d")

    def test_render_has_no_banned_phrases(self):
        for plain in (True, False):
            html = kit_html(self.result, pipeline.LIME_KIT, limit=0, plain=plain)
            for phrase in tj.BANNED_PHRASES:
                self.assertNotIn(phrase, html)

    def test_missing_and_stale_rows_are_disclosed(self):
        result = run_pool(existing={"^HSI": ups()})          # 另两只缺日线
        html = kit_html(result, pipeline.LIME_KIT, plain=True)
        self.assertIn("暂缺", html)
        self.assertIn("恒生科技", html)

    def test_missing_dimensions_are_named_not_hidden(self):
        """缺维度要在覆盖表里点名（上游「缺失保留为缺失」），不能默默当 0。"""
        html = kit_html(self.result, pipeline.GUIZANG_KIT, plain=False)
        self.assertIn("数据卡覆盖", html)
        self.assertTrue("全维可用" in html or "缺失维度" in html)
        thin = tj.run_trend(None, existing={"^HSI": ups()}, specs=[("恒生指数", "^HSI")],
                            extras={}, now=NOW, db_root=str(Path(tempfile.mkdtemp(prefix="tj-db-"))))
        thin_html = kit_html(thin, pipeline.GUIZANG_KIT, plain=False)
        self.assertIn("流动性综合分暂缺" if False else "缺失维度", thin_html)
        self.assertTrue(any(word in thin_html for word in ("社区", "成交额环比", "板块净强弱")))


# ------------------------------------------------------------------
# ⑦ pipeline 接线：审计计数、正文顺序、开关与研判行
# ------------------------------------------------------------------
def source_of(result, *, is_today=True):
    return pipeline._source_result(pipeline.TREND_JURY_SOURCE_NAME, "success",
                                   result=result, content_date=result["as_of"],
                                   is_today=is_today)


class PipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_pool()

    def _data(self, result=None):
        return {pipeline.TREND_JURY_SOURCE_NAME:
                source_of(result or self.result, is_today=False)}

    def test_column_registered_in_order_after_analysis_block(self):
        order = list(pipeline.REPORT_SECTION_ORDER)
        self.assertIn(tj.SECTION_KICKER, order)
        self.assertLess(order.index("GEO TREND"), order.index(tj.SECTION_KICKER))
        self.assertLess(order.index(tj.SECTION_KICKER), order.index("ECON CALENDAR"))
        self.assertEqual(pipeline.SECTION_TITLE_TREND_JURY, "【深海剑鱼】趋势多维评审团")

    def test_section_rendered_with_ai_note_in_both_themes(self):
        for theme in ("lime", "guizang", "pixel", "forum", "dossier"):
            html = pipeline.generate_report(self._data(), "2026年10月11日 · 周日", "20261011",
                                            theme=theme)
            self.assertIn(pipeline.SECTION_TITLE_TREND_JURY, html, theme)
            self.assertIn("⌁ AI 研判", html, theme)
            self.assertIn("方法评委", html, theme)

    def test_audit_counts_the_new_data_line_only_when_present(self):
        """总源数只在本次确实采集过时 +1（与 MACD / 行业轮动同口径），当天计数看收盘日。"""
        without = pipeline._collect_report_parts({}, pipeline.GUIZANG_KIT, date_str="20261011")
        with_ = pipeline._collect_report_parts(self._data(), pipeline.GUIZANG_KIT,
                                               date_str="20261011")
        self.assertEqual(with_["total"] - without["total"], 1)
        self.assertEqual(with_["today_n"], without["today_n"])          # is_today=False
        fresh = pipeline._collect_report_parts(
            {pipeline.TREND_JURY_SOURCE_NAME: source_of(self.result, is_today=True)},
            pipeline.GUIZANG_KIT, date_str="20261011")
        self.assertEqual(fresh["today_n"] - without["today_n"], 1)

    def test_disabled_switch_leaves_no_trace(self):
        with patch.object(pipeline, "TREND_JURY_ENABLED", False):
            parts = pipeline._collect_report_parts(self._data(), pipeline.GUIZANG_KIT,
                                                   date_str="20261011")
            self.assertNotIn(tj.SECTION_KICKER, [s[0] for s in parts["sections"]])

    def test_unavailable_source_does_not_render_column(self):
        data = {pipeline.TREND_JURY_SOURCE_NAME: {"source": pipeline.TREND_JURY_SOURCE_NAME,
                                                   "status": "unavailable", "result": None}}
        parts = pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT, date_str="20261011")
        self.assertNotIn(tj.SECTION_KICKER, [s[0] for s in parts["sections"]])

    def test_ren_block_uses_the_same_numbers(self):
        """「AI帮你提鲜」只翻译评审结果，不新增数字。"""
        ctx = {"trend_jury": self.result, "notes": {}, "date_str": "20261011"}
        text = pipeline._ren.section_ren("TREND JURY", ctx)
        self.assertIn("趋势评审团", text)
        self.assertIn("过了数据闸门", text)
        self.assertEqual(tj.fluff_check(text), [])

    def test_fetch_wrapper_marks_today_only_for_fresh_close(self):
        with patch.object(pipeline._quant.trend_jury, "run_trend", return_value=self.result), \
             patch.object(pipeline, "_trend_jury_extras", return_value=EXTRAS):
            src = pipeline.fetch_trend_jury({})
        self.assertEqual(src["status"], "success")
        self.assertFalse(src["is_today"])                 # 收盘日 10-09 ≠ 今天
        self.assertEqual(src["content_date"], self.result["as_of"])

    def test_fetch_wrapper_off_returns_none(self):
        with patch.object(pipeline, "TREND_JURY_ENABLED", False):
            self.assertIsNone(pipeline.fetch_trend_jury({}))

    def test_fetch_wrapper_swallows_engine_crash(self):
        def boom(*_a, **_k):
            raise RuntimeError("boom")
        with patch.object(pipeline._quant.trend_jury, "run_trend", side_effect=boom), \
             patch.object(pipeline, "_trend_jury_extras", return_value={}):
            src = pipeline.fetch_trend_jury({})
        self.assertEqual(src["status"], "unavailable")
        self.assertIn("RuntimeError", src["error"])

    def test_extras_read_from_the_same_objects(self):
        data = {
            "A股大盘全景": {"status": "success",
                            "breadth": {"up": 3000, "down": 1500, "ratio": 2.0},
                            "turnover": {"chg_pct": 8.0},
                            "sectors": {"leading": [{"chg_pct": 2.0}, {"chg_pct": 1.0}],
                                        "lagging": [{"chg_pct": -0.5}]}},
            "港股量化": {"result": {"liquidity": {"available": True, "score": 62.0}}},
        }
        extras = pipeline._trend_jury_extras(data)
        self.assertEqual(extras["breadth_up_n"], 3000)
        self.assertEqual(extras["breadth_down_n"], 1500)
        self.assertIn("涨跌比 2.00", extras["breadth_ratio_txt"])
        self.assertEqual(extras["turnover_chg_pct"], 8.0)
        self.assertAlmostEqual(extras["sector_net"], 1.5 - 0.5, places=6)
        self.assertEqual(extras["liquidity_score"], 62.0)
        self.assertNotIn("crowd_nbi", extras)         # 没有社区样本就不写这一维

    def test_extras_zero_down_breadth_does_not_invent_a_ratio(self):
        data = {"A股大盘全景": {"breadth": {"up": 4000, "down": 0, "ratio": None}}}
        extras = pipeline._trend_jury_extras(data)
        self.assertEqual(extras["breadth_up_n"], 4000)
        self.assertIn("比率不适用", extras["breadth_ratio_txt"])

    def test_extras_empty_data_returns_empty(self):
        self.assertEqual(pipeline._trend_jury_extras({}), {})
        self.assertEqual(pipeline._trend_jury_extras(None), {})


# ------------------------------------------------------------------
# ⑧ 取数阶梯：库优先、整段选源、离线不联网
# ------------------------------------------------------------------
class LoadLadderTests(unittest.TestCase):
    def test_market_db_wins_over_existing_bars(self):
        db_bars = bars(n=260, seed=77, drift=0.0040)
        with tempfile.TemporaryDirectory() as tmp:
            module = types.ModuleType("market_db")
            module.DB_ROOT = tmp
            module.load_daily_bars = lambda **kw: {"^HSI": db_bars}
            with patch.dict(sys.modules, {"market_db": module}):
                result = run_pool(existing={"^HSI": downs()})
        row = next(r for r in result["items"] if r["code"] == "^HSI")
        self.assertIn("市场库", row["source"])
        self.assertGreater(row["score"], 50)          # 用的是库里的上行序列

    def test_existing_bars_are_used_without_network(self):
        result = run_pool(existing={"^HSI": ups()})
        self.assertEqual([r["code"] for r in result["items"]], ["^HSI"])
        self.assertIn("本次量化日线", result["items"][0]["source"])
        self.assertTrue(all(r["data_route"] == "cached" for r in result["items"]))

    def test_never_splices_two_sources(self):
        """库里 60 根 + 免费源 260 根：不许拼串，取整段可用的那一段。"""
        with tempfile.TemporaryDirectory() as tmp:
            module = types.ModuleType("market_db")
            module.DB_ROOT = tmp
            module.load_daily_bars = lambda **kw: {"^HSI": bars(n=60)}
            calls = []

            def fake_fetch(fetch_json, symbol, **kw):
                calls.append((symbol, kw.get("rng")))
                return {"bars": bars(n=260, seed=5), "source": "Yahoo Finance test",
                        "url": "https://query1.finance.yahoo.com/x"}

            with patch.dict(sys.modules, {"market_db": module}), \
                 patch.object(providers, "fetch_bars", fake_fetch):
                result = tj.run_trend(lambda *a, **k: None, existing={},
                                      specs=[("恒生指数", "^HSI")], extras=EXTRAS, now=NOW)
        row = result["items"][0]
        self.assertEqual(row["bars_n"], 260)
        self.assertNotEqual(row["bars_n"], 320)
        self.assertTrue(calls)

    def test_free_source_only_used_when_local_missing(self):
        calls = []

        def fake_fetch(fetch_json, symbol, **kw):
            calls.append(symbol)
            return {"bars": bars(n=260, seed=13), "source": "Yahoo Finance test",
                    "url": "https://query1.finance.yahoo.com/x"}

        with patch.dict(sys.modules, {"market_db": types.ModuleType("market_db")}):
            with patch.object(providers, "fetch_bars", fake_fetch):
                result = tj.run_trend(lambda *a, **k: None, existing={"^HSI": ups()},
                                      specs=[("恒生指数", "^HSI"), ("恒生科技", "^HSTECH")],
                                      extras=EXTRAS, now=NOW)
        self.assertEqual(calls, ["^HSTECH"])                 # 已有的那只不再联网
        codes = {r["code"] for r in result["items"]}
        self.assertEqual(codes, {"^HSI", "^HSTECH"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
