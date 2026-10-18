"""◈ AI 七日港股走势分析概率离线回归测试（不发任何网络请求）。

覆盖：
  · 量化基准（复用 octopus_weekly 因果引擎、视界 7）：概率夹 5%~95%、截断不变性
    （未来数据不得影响过去输出）、样本不足 → available=False 且带原因；
  · 大模型链路（注入假 post_json）：严格 JSON 解析、概率偏离量化基准 >20pp 收敛、
    数字溯源（编造的数字 / 绝对化措辞 → 该条文案回退量化口径，绝不写进日报）；
  · 留痕：先存档（settled=False）、满 7 个交易日才结算、当次运行不可能结算当次；
  · 管线接入：fetch_hk_seven_day 的 source 结果与审计名、栏目渲染（两主题）、
    无 Key 默认整栏缺席（OCTOPUS_HK7_FALLBACK=1 才降级渲染）、OCTOPUS_HK7=0 关闭、
    原「行业轮动」栏目与模块已彻底下线。
"""
import importlib.util
import io
import json
import random
import re
import sys
import tempfile
import types
import unittest
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# pipeline 在导入时只需要 requests 存在；本测试不发出 HTTP 请求。
sys.modules.setdefault("requests", types.SimpleNamespace())

REPO_ROOT = Path(__file__).parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
if str(OUTPUT_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUT_DIR))

import hk_seven_day as hk7  # noqa: E402
import octopus_weekly as weekly  # noqa: E402

MODULE_PATH = OUTPUT_DIR / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_hk7_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

CST = timezone(timedelta(hours=8))


def synthetic_closes(n=320, seed=42):
    rng = random.Random(seed)
    closes, x = [], 24500.0
    for _ in range(n):
        x *= 1 + rng.gauss(0.0002, 0.011)
        closes.append(x)
    return closes


def weekday_dates(n, start=date(2025, 1, 6)):
    dates, d = [], start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += timedelta(days=1)
    return dates


def synthetic_bars(n=320, seed=42, start=date(2025, 1, 6)):
    closes = synthetic_closes(n, seed=seed)
    dates = weekday_dates(n, start=start)
    return [{"date": dates[i], "open": c, "high": c * 1.012, "low": c * 0.988,
             "close": c, "volume": 1.2e8} for i, c in enumerate(closes)]


def bars_by_symbol(n=320, seed=42):
    return {"^HSI": synthetic_bars(n, seed=seed),
            "^HSTECH": synthetic_bars(n, seed=seed + 1),
            "^HSCE": synthetic_bars(n, seed=seed + 2)}


def quant_config(**over):
    cfg = {"enabled": False, "key": "", "base": "https://example.invalid/v1",
           "model": "test-model", "timeout": 10, "fallback": "auto"}
    cfg.update(over)
    return cfg


def yahoo_chart_payload(symbol, bars):
    def ts(day_str):
        d = datetime.strptime(day_str, "%Y-%m-%d").replace(hour=16, tzinfo=CST)
        return int(d.timestamp())
    return {"chart": {"result": [{
        "meta": {"symbol": symbol},
        "timestamp": [ts(b["date"]) for b in bars],
        "indicators": {"quote": [{
            "open": [b["open"] for b in bars], "high": [b["high"] for b in bars],
            "low": [b["low"] for b in bars], "close": [b["close"] for b in bars],
            "volume": [b["volume"] for b in bars]}]}}]}}


# ======================================================================
# ① 量化基准 + 因果性
# ======================================================================
class QuantEngineTests(unittest.TestCase):
    def test_horizon_is_seven_trading_days(self):
        self.assertEqual(hk7.HORIZON, 7)

    def test_quant_probability_is_bounded_and_labelled(self):
        closes = synthetic_closes()
        out = hk7.quant_probability(closes)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["p_up"], hk7.PROB_FLOOR)
        self.assertLessEqual(out["p_up"], hk7.PROB_CAP)
        direction, label = hk7._direction_label(out["p_up"])
        self.assertIn(direction, ("up", "down", "neutral"))
        self.assertIn("P(7日涨)", label)

    def test_short_sample_is_unavailable_with_reason(self):
        res = hk7.run_seven_day(None, bars_by_symbol={"^HSI": synthetic_bars(40)},
                                history_path=None, config=quant_config())
        self.assertFalse(res["available"])
        self.assertIn("日线样本", res["reason"])

    def test_truncation_invariance_of_seven_day_engine(self):
        """截断不变性：删掉 k 之后的数据，signals[k] 必须逐位不变（无未来函数）。"""
        closes = synthetic_closes(280, seed=9)
        full = weekly.compute_signals(closes, horizon=hk7.HORIZON)
        self.assertTrue(full["ok"])
        for k in (80, 150, 230):
            trunc = weekly.compute_signals(closes[:k + 1], horizon=hk7.HORIZON)
            self.assertTrue(trunc["ok"], f"cut={k}")
            a, b = full["signals"][k], trunc["signals"][k]
            for key in ("p_up", "p_base", "p_sim", "n_analog", "n_resolved"):
                self.assertEqual(a.get(key), b.get(key), f"{key} @ {k}")

    def test_run_reports_three_targets_and_journal_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / hk7.JOURNAL_FILENAME
            res = hk7.run_seven_day(None, bars_by_symbol=bars_by_symbol(),
                                    history_path=str(journal), config=quant_config())
            self.assertTrue(res["available"])
            self.assertEqual(res["engine"], "quant")
            self.assertEqual(len(res["targets"]), 3)
            self.assertEqual(res["journal"]["n"], 0)
            self.assertEqual(res["journal"]["standing"], 3)
            saved = json.loads(journal.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["entries"]), 3)
            self.assertTrue(all(e["settled"] is False for e in saved["entries"]))
            # 同一锚定日重复运行：不重复签发
            again = hk7.run_seven_day(None, bars_by_symbol=bars_by_symbol(),
                                      history_path=str(journal), config=quant_config())
            self.assertEqual(again["journal"]["standing"], 3)


# ======================================================================
# ② 留痕：先存档后结算（7 个交易日）
# ======================================================================
class JournalSettleTests(unittest.TestCase):
    def test_settle_only_after_seven_sessions(self):
        bars = synthetic_bars(120, seed=3)
        base_index = 114                       # 之后只有 5 根 K 线 → 还不够 7 个交易日
        series = {"^HSI": ([b["date"] for b in bars], [b["close"] for b in bars])}
        entries = [{"symbol": "^HSI", "base_date": bars[base_index]["date"], "p_up": 0.6,
                    "settled": False}]
        hk7._settle(entries, series, now=datetime(2030, 1, 1, tzinfo=CST))
        self.assertFalse(entries[0]["settled"])
        # 补齐第 7 根 K 线 → 结算并回填命中 / Brier（当次运行不可能结算当次预测）
        more = synthetic_bars(122, seed=3)
        series2 = {"^HSI": ([b["date"] for b in more], [b["close"] for b in more])}
        hk7._settle(entries, series2, now=datetime(2030, 1, 1, tzinfo=CST))
        self.assertTrue(entries[0]["settled"])
        self.assertEqual(entries[0]["settle_date"], more[base_index + hk7.HORIZON]["date"])
        self.assertIn("hit", entries[0])
        self.assertIsNotNone(entries[0]["brier"])

    def test_journal_stats_hold_back_hit_rate_below_ten(self):
        entries = [{"settled": True, "hit": True, "brier": 0.1, "p_up": 0.6,
                    "settle_date": "2026-01-01", "actual_ret": 0.01}] * 4
        stats = hk7._journal_stats(entries)
        self.assertIsNone(stats["hit_rate"])
        self.assertEqual(stats["n"], 4)
        self.assertIn("只报样本量", stats["note"])


# ======================================================================
# ③ 大模型链路：解析 / 收敛 / 数字溯源
# ======================================================================
class LLMTests(unittest.TestCase):
    def test_llm_config_env_precedence_and_fallback(self):
        cfg = hk7.llm_config({"DEEPSEEK_API_KEY": " k ", "OCTOPUS_LLM_MODEL": "m1",
                              "OCTOPUS_LLM_TIMEOUT": "3"})
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["key"], "k")
        self.assertEqual(cfg["model"], "m1")
        self.assertEqual(cfg["timeout"], 5)          # 夹到下限 5 秒
        # fallback 三档：默认 auto（无 Key 即整栏缺席）· =1 always · =0 never
        self.assertEqual(hk7.llm_config({})["fallback"], "auto")
        self.assertEqual(hk7.llm_config({"OCTOPUS_LLM_API_KEY": "x"})["fallback"], "auto")
        self.assertEqual(hk7.llm_config({"OCTOPUS_HK7_FALLBACK": "1"})["fallback"], "always")
        self.assertEqual(hk7.llm_config({"OCTOPUS_HK7_FALLBACK": "0"})["fallback"], "never")
        self.assertFalse(hk7.llm_config({})["enabled"])

    def test_llm_config_accepts_vendor_key_names_and_model_chain(self):
        """既有的 DEEPSEEK_API_KEY 不必改名就能用；未指定模型时走档位别名候选链。"""
        cfg = hk7.llm_config({"DEEPSEEK_API_KEY": "sk-demo", "OCTOPUS_LLM_MAX_TOKENS": "2048"})
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["key_source"], "DEEPSEEK_API_KEY")
        self.assertEqual(cfg["max_tokens"], 2048)
        self.assertFalse(cfg["model_explicit"])          # 没显式指定 → 走候选链
        self.assertEqual(cfg["models"][0], "deepseek-flash")
        self.assertIn("deepseek-chat", cfg["models"])    # 历史别名也在链上兜底
        # 显式指定模型名 → 只用它，绝不偷偷换掉
        self.assertEqual(hk7.llm_config({"DEEPSEEK_API_KEY": "k",
                                         "OCTOPUS_LLM_MODEL": "m1"})["models"], ("m1",))
        # 自建 / 第三方地址：不往别人的服务上试 DeepSeek 别名
        other = hk7.llm_config({"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "https://api.openai.com/v1"})
        self.assertEqual(other["models"], ("deepseek-chat",))
        self.assertEqual(other["key_source"], "OPENAI_API_KEY")
        self.assertEqual(other["base_source"], "OPENAI_BASE_URL")
        # 目录过滤：只留服务端真有的名字
        self.assertEqual(hk7.model_chain({"base": "https://api.deepseek.com/v1",
                                          "model": "deepseek-chat"},
                                         catalog=["deepseek-v4-pro", "deepseek-chat"]),
                         ("deepseek-v4-pro", "deepseek-chat"))   # 目录过滤后仍按候选链顺序

    def test_call_llm_switches_model_only_on_model_fault(self):
        """模型名不对 → 换下一个名字；网络 / 超时错误 → 不换（换了也一样失败，白烧预算）。"""
        cfg = hk7.llm_config({"DEEPSEEK_API_KEY": "k"})
        seen = []

        def fake_post(url, payload, headers, timeout):
            seen.append(payload["model"])
            if payload["model"] != "deepseek-v4-pro":        # 候选链里的第二个名字
                raise RuntimeError("Error code: 400 - model does not exist")
            return {"choices": [{"message": {"content": "{\"targets\": []}"}}]}

        trace = {}
        payload, err = hk7.call_llm(cfg, hk7.PROBE_CONTEXT, post_json=fake_post, trace=trace)
        self.assertEqual(payload, {"targets": []})
        self.assertEqual(err, "")
        self.assertEqual(trace["model"], "deepseek-v4-pro")
        self.assertEqual(seen, ["deepseek-flash", "deepseek-v4-pro"])

        seen.clear()

        def boom(url, payload, headers, timeout):
            seen.append(payload["model"])
            raise RuntimeError("urlopen error timed out")

        payload, err = hk7.call_llm(cfg, hk7.PROBE_CONTEXT, post_json=boom)
        self.assertIsNone(payload)
        self.assertEqual(seen, ["deepseek-flash"])       # 只试一次
        self.assertIn("timed out", err)

    def test_llm_probe_reports_sources_without_echoing_key(self):
        """探活报告：报「哪个变量名生效」+ 目录 + 逐模型结果；全文不得出现 Key 本身。"""
        cfg = hk7.llm_config({"DEEPSEEK_API_KEY": "sk-demo-secret"})

        def fake_get(url, headers, timeout):
            self.assertTrue(url.endswith("/models"))
            self.assertEqual(headers["Authorization"], "Bearer sk-demo-secret")
            return {"data": [{"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"}]}

        def fake_post(url, payload, headers, timeout):
            self.assertTrue(url.endswith("/chat/completions"))
            body = {"targets": [{"code": "^HSI", "p_up": 0.57, "summary": "探活",
                                 "drivers": [], "risks": []}]}
            return {"choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}]}

        probe = hk7.llm_probe(cfg, get_json=fake_get, post_json=fake_post)
        self.assertTrue(probe["ok"])
        self.assertEqual(probe["catalog"]["ids"], ["deepseek-flash", "deepseek-v4-pro"])
        self.assertEqual(probe["config"]["key_source"], "DEEPSEEK_API_KEY")
        self.assertEqual(probe["config"]["key_len"], len("sk-demo-secret"))
        self.assertTrue(probe["attempts"][0]["ok"])
        self.assertTrue(probe["attempts"][0]["field_ok"])
        self.assertNotIn("sk-demo-secret", json.dumps(probe, ensure_ascii=False))
        # 没配 Key：结论直说整栏缺席，且不抛异常
        empty = hk7.llm_probe(hk7.llm_config({}))
        self.assertFalse(empty["ok"])
        self.assertIn("整栏缺席", empty["verdict"])

    def test_http_error_message_keeps_server_words(self):
        """裸「HTTP Error 402」看不出是余额还是模型名；带上服务端响应体原话才可排障。"""
        exc = urllib.error.HTTPError(
            "https://api.deepseek.com/v1/chat/completions", 402, "Payment Required", {},
            io.BytesIO(b'{"error":{"message":"Insufficient Balance","type":"unknown_error"}}'))
        msg = hk7.http_error_message(exc)
        self.assertIn("HTTP 402", msg)
        self.assertIn("Insufficient Balance", msg)
        self.assertIn("充值", hk7.llm_error_hint(msg))
        # 其他常见失败各自给出下一步动作
        self.assertIn("Secret", hk7.llm_error_hint("HTTP 401 Unauthorized: invalid api key"))
        self.assertIn("限流", hk7.llm_error_hint("HTTP 429 Too Many Requests"))
        self.assertIn("模型名不存在", hk7.llm_error_hint("HTTP 400：Model Not Exist"))
        self.assertIn("超时", hk7.llm_error_hint("RuntimeError: urlopen error timed out"))
        self.assertEqual(hk7.llm_error_hint(""), "")
        self.assertEqual(hk7.llm_error_hint(None), "")

    def test_probe_enumerates_catalog_models_beyond_the_chain(self):
        """探活要把「目录里有、候选链里没有」的模型也试掉，否则量不出可用范围。"""
        cfg = hk7.llm_config({"DEEPSEEK_API_KEY": "k"})

        def fake_get(url, headers, timeout):
            # 目录里多出一个候选链之外的新模型（官方改名 / 上新的情形）
            return {"data": [{"id": "deepseek-flash"}, {"id": "deepseek-next-gen"}]}

        def fake_post(url, payload, headers, timeout):
            model = payload["model"]
            if model != "deepseek-next-gen":
                raise RuntimeError(f'HTTP 400 Bad Request：{{"error":{{"message":"Model Not Exist: {model}"}}}}')
            body = {"targets": [{"code": "^HSI", "p_up": 0.55, "summary": "探活",
                                 "drivers": [], "risks": []}]}
            return {"choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}]}

        probe = hk7.llm_probe(cfg, get_json=fake_get, post_json=fake_post)
        self.assertTrue(probe["ok"])
        self.assertEqual([a["model"] for a in probe["attempts"]],
                         ["deepseek-flash", "deepseek-next-gen"])     # 链外的目录模型也试了
        self.assertEqual(probe["attempts"][-1]["model"], "deepseek-next-gen")
        self.assertTrue(probe["attempts"][0]["hint"])                # 失败条目带下一步动作
        # 目录与候选链有交集时，先试交集（顺序跟候选链一致），不再重复试链外名字
        cfg2 = hk7.llm_config({"DEEPSEEK_API_KEY": "k"})
        probe2 = hk7.llm_probe(cfg2, get_json=fake_get, post_json=fake_post,
                               models=["deepseek-flash"])
        self.assertEqual([a["model"] for a in probe2["attempts"]],
                         ["deepseek-flash", "deepseek-next-gen"])

    def test_extract_json_tolerates_fences_and_noise(self):
        self.assertEqual(hk7._extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(hk7._extract_json('前言 {"a": {"b": 2}} 后记'), {"a": {"b": 2}})
        self.assertIsNone(hk7._extract_json("no json here"))
        self.assertIsNone(hk7._extract_json(""))

    def _llm_run(self, payload, tmp, allowed_extra=None):
        def fake_post(url, body, headers, timeout):
            self.assertIn("chat/completions", url)
            self.assertEqual(headers["Authorization"], "Bearer test-key")
            return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}
        return hk7.run_seven_day(
            None, bars_by_symbol=bars_by_symbol(), history_path=str(Path(tmp) / "j.json"),
            post_json=fake_post, config=quant_config(enabled=True, key="test-key"))

    def test_probability_is_converged_to_quant_base(self):
        bars = bars_by_symbol()
        base = hk7.run_seven_day(None, bars_by_symbol=bars, history_path=None,
                                 config=quant_config())
        p_hsi = next(t["quant_p_up"] for t in base["targets"] if t["code"] == "^HSI")
        payload = {"targets": [{"code": "^HSI", "p_up": 0.97, "summary": "偏强"}],
                   "cross_note": ""}
        with tempfile.TemporaryDirectory() as tmp:
            res = self._llm_run(payload, tmp)
        self.assertEqual(res["engine"], "llm")
        hsi = next(t for t in res["targets"] if t["code"] == "^HSI")
        self.assertTrue(hsi["converged"])
        self.assertAlmostEqual(hsi["p_up"], min(hk7.PROB_CAP, p_hsi + hk7.MAX_PROB_DEVIATION),
                               places=6)
        self.assertLessEqual(hsi["p_up"], hk7.PROB_CAP)

    def test_fabricated_numbers_and_absolute_words_fall_back_to_quant(self):
        payload = {"targets": [
            {"code": "^HSI", "p_up": 0.6, "summary": "目标位 12345.67 点",
             "drivers": ["必涨无风险"], "risks": ["政策不确定性"]}],
            "cross_note": "南向资金回暖"}
        with tempfile.TemporaryDirectory() as tmp:
            res = self._llm_run(payload, tmp)
        hsi = next(t for t in res["targets"] if t["code"] == "^HSI")
        # 编造数字 → summary 回退量化口径；绝对化措辞 → drivers 回退量化口径
        self.assertIn("量化基准", hsi["summary"])
        self.assertNotIn("12345.67", hsi["summary"])
        self.assertTrue(any("扩张基准率" in d for d in hsi["drivers"]))
        self.assertIn("12345.67", res["notes"]["dropped"])
        self.assertIn("绝对化措辞", res["notes"]["dropped"])
        # 可溯源的文案保留（南向资金一句不含数字，直接通过）
        self.assertEqual(res["cross_note"], "南向资金回暖")

    def test_traceable_numbers_are_kept(self):
        bars = bars_by_symbol()
        close = bars["^HSI"][-1]["close"]
        payload = {"targets": [
            {"code": "^HSI", "p_up": 0.6,
             "summary": "现价 %.2f 附近震荡" % close,
             "drivers": ["现价 %.2f 上方运行" % close], "risks": ["波动放大"]}],
            "cross_note": ""}
        with tempfile.TemporaryDirectory() as tmp:
            res = self._llm_run(payload, tmp)
        hsi = next(t for t in res["targets"] if t["code"] == "^HSI")
        self.assertIn(f"{close:.2f}", hsi["summary"])
        self.assertIn(f"{close:.2f}", hsi["drivers"][0])
        # summary / drivers / risks 三条都没有编造数字 → 全部保留
        self.assertEqual(res["grounded"], "3/3")

    def test_broken_llm_reply_degrades_to_quant(self):
        def bad_post(url, body, headers, timeout):
            return {"choices": [{"message": {"content": "抱歉，我无法给出概率。"}}]}
        with tempfile.TemporaryDirectory() as tmp:
            res = hk7.run_seven_day(
                None, bars_by_symbol=bars_by_symbol(), history_path=str(Path(tmp) / "j.json"),
                post_json=bad_post, config=quant_config(enabled=True, key="k"))
        self.assertTrue(res["available"])
        self.assertEqual(res["engine"], "quant")
        self.assertIn("合法 JSON", res["llm_reason"])

    def test_strict_mode_marks_unavailable_when_llm_fails(self):
        """OCTOPUS_HK7_FALLBACK=0：配了 Key 但大模型不可用 → 整体不可用（不落量化留痕）。"""
        def boom(url, body, headers, timeout):
            raise RuntimeError("network down")
        with tempfile.TemporaryDirectory() as tmp:
            res = hk7.run_seven_day(
                None, bars_by_symbol=bars_by_symbol(), history_path=str(Path(tmp) / "j.json"),
                post_json=boom, config=quant_config(enabled=True, key="k", fallback="never"))
        self.assertFalse(res["available"])
        self.assertIn("大模型不可用", res["reason"])

    def test_llm_exception_degrades_and_never_raises(self):
        def boom(url, body, headers, timeout):
            raise RuntimeError("network down")
        with tempfile.TemporaryDirectory() as tmp:
            res = hk7.run_seven_day(
                None, bars_by_symbol=bars_by_symbol(), history_path=str(Path(tmp) / "j.json"),
                post_json=boom, config=quant_config(enabled=True, key="k"))
        self.assertTrue(res["available"])
        self.assertEqual(res["engine"], "quant")
        self.assertIn("RuntimeError", res["llm_reason"])

    def test_prompt_only_carries_given_data(self):
        bars = bars_by_symbol()
        with tempfile.TemporaryDirectory() as tmp:
            res = hk7.run_seven_day(
                None, bars_by_symbol=bars, history_path=str(Path(tmp) / "j.json"),
                extra={"flows": {"south_amount_yi": 612.34},
                       "events": [{"date": "2026-10-02", "name": "非农就业人数:季调"}],
                       "news": [{"title": "港股成交回暖", "source": "香港经济日报"}]},
                config=quant_config())
        self.assertEqual(len(res["targets"]), 3)
        # 证据缺失时不编造：extra 为空时也不报错
        res2 = hk7.run_seven_day(None, bars_by_symbol=bars, history_path=None,
                                 extra={}, config=quant_config())
        self.assertTrue(res2["available"])


# ======================================================================
# ④ 管线接入：source 结果 / 审计 / 渲染 / 开关
# ======================================================================
class PipelineWiringTests(unittest.TestCase):
    def _fallback_config(self, **over):
        """OCTOPUS_HK7_FALLBACK=1：没有 Key 也降级渲染量化基准（测试用显式配置）。"""
        cfg = {"enabled": False, "key": "", "base": "https://example.invalid/v1",
               "model": "test-model", "timeout": 10, "fallback": "always"}
        cfg.update(over)
        return cfg

    def _fake_request(self, bars):
        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            m = re.search(r"chart/([^?/]+)", url)
            if not m:
                return None
            return yahoo_chart_payload(m.group(1), bars)
        return fake

    def test_fetch_returns_success_source_and_audit_name(self):
        bars = synthetic_bars()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline._hk7, "llm_config",
                             return_value=self._fallback_config()), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
        self.assertEqual(src["status"], "success")
        self.assertEqual(src["source"], pipeline.HK7_SOURCE_NAME)
        self.assertEqual(src["result"]["engine"], "quant")
        self.assertEqual(src["content_date"], bars[-1]["date"])

    def test_disabled_switch_makes_column_absent(self):
        with patch.object(pipeline, "HK7_ENABLED", False):
            src = pipeline.fetch_hk_seven_day({})
        self.assertIsNone(src)              # 不写 data 键 → 栏目与审计都不出现

    def test_no_key_makes_column_absent_by_default(self):
        with patch.object(pipeline, "HK7_ENABLED", True), \
                patch.object(pipeline._hk7, "llm_config",
                             return_value={"enabled": False, "fallback": "auto",
                                           "key": "", "base": "", "model": "m",
                                           "timeout": 10}), \
                patch.object(pipeline._jev, "jev_config",
                             return_value={"enabled": False, "base": "", "key": "",
                                           "timeout": 10, "mode": "auto"}):
            src = pipeline.fetch_hk_seven_day({})
        self.assertIsNone(src)              # 默认：没有 Key、没有 Jev 端点就没有这个栏目

    def test_no_key_with_fallback_renders_quant_baseline(self):
        bars = synthetic_bars()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline._hk7, "llm_config",
                             return_value=self._fallback_config()), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
        self.assertEqual(src["status"], "success")
        self.assertEqual(src["result"]["engine"], "quant")

    def test_key_configured_but_llm_fails_is_unavailable_in_strict_mode(self):
        bars = synthetic_bars()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline._hk7, "llm_config",
                             return_value={"enabled": True, "fallback": "never",
                                           "key": "k", "base": "https://example.invalid/v1",
                                           "model": "m", "timeout": 10}), \
                patch.object(pipeline._hk7, "http_post_json",
                             side_effect=RuntimeError("network down")), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
        self.assertEqual(src["status"], "unavailable")
        self.assertIn("大模型不可用", src["error"])

    def test_key_configured_llm_success_renders_ai_column(self):
        """配了 Key 且大模型给出合法 JSON → engine=llm，栏目带引擎/数字溯源标注。"""
        bars = synthetic_bars()
        config = {"enabled": True, "fallback": "auto", "key": "k",
                  "base": "https://example.invalid/v1", "model": "m", "timeout": 10}

        def fake_post(url, payload, headers, timeout):
            self.assertIn("chat/completions", url)
            body = {"targets": [{"code": "^HSI", "p_up": 0.62, "summary": "偏强震荡",
                                 "drivers": ["动能延续"], "risks": ["波动放大"],
                                 "support": 24000, "resistance": 25000}],
                    "cross_note": "南向资金回暖"}
            return {"choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}]}

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline._hk7, "llm_config", return_value=config), \
                patch.object(pipeline._hk7, "http_post_json", side_effect=fake_post), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
        self.assertEqual(src["status"], "success")
        self.assertEqual(src["result"]["engine"], "llm")
        with pipeline.notes_mode():                  # 溯源条数是过程说明：--notes 下可见
            html = pipeline.generate_report_guizang(
                {pipeline.HK7_SOURCE_NAME: src, "_backup_info": {"events": []}},
                "2026年9月29日", "20260929")
        self.assertIn("文案数字溯源", html)
        plain_html = pipeline.generate_report_guizang(
            {pipeline.HK7_SOURCE_NAME: src, "_backup_info": {"events": []}},
            "2026年9月29日", "20260929")
        self.assertIn("P(7日涨)", plain_html)       # 入门版：结论在，溯源过程不出
        self.assertNotIn("文案数字溯源", plain_html)

    def test_block_renders_both_themes_and_hides_when_unavailable(self):
        bars = synthetic_bars()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline._hk7, "llm_config",
                             return_value=self._fallback_config()), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
        res = src["result"]
        for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
            with pipeline.notes_mode():
                html = pipeline._hk_seven_day_block(res, kit)
            self.assertIn("恒生指数", html)
            self.assertIn("P(7日涨)", html)
            self.assertIn("预测留痕", html)
            plain_html = pipeline._hk_seven_day_block(res, kit)   # 入门版：未结算就不出留痕状态
            self.assertIn("恒生指数", plain_html)
            self.assertIn("P(7日涨)", plain_html)
            self.assertNotIn("预测留痕", plain_html)
            self.assertNotIn("七日口径", plain_html)
        self.assertEqual(pipeline._hk_seven_day_block({"available": False}, pipeline.GUIZANG_KIT), "")
        self.assertEqual(pipeline._hk_seven_day_block({"available": True, "targets": []},
                                                      pipeline.GUIZANG_KIT), "")

    def test_report_contains_section_and_coverage_line(self):
        """2026-09-30 合并：hk7 由独立栏目并入【嗜血大白鲨】逐日走势量化分析的栏内子块。"""
        bars = synthetic_bars()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline._hk7, "llm_config",
                             return_value=self._fallback_config()), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
        html = pipeline.generate_report_guizang(
            {pipeline.HK7_SOURCE_NAME: src, "_backup_info": {"events": []}},
            "2026年9月29日", "20260929")
        # 子块标题与三指数内容仍在（并入 WEEKLY FORECAST 栏目，栏目头用合并后的标题）
        self.assertIn("AI 七日港股走势分析概率", html)
        self.assertIn("恒生科技", html)
        self.assertIn(pipeline.SECTION_TITLE_WEEKLY_FORECAST, html)
        # 独立栏目已取消：英文 kicker 不再单列
        self.assertNotIn("HK 7D PROB", html)
        # 顺序：合并后随 WEEKLY FORECAST，仍在趋势跟踪之前
        self.assertLess(html.index(pipeline.SECTION_TITLE_WEEKLY_FORECAST),
                        html.index("TREND TRACKING") if "TREND TRACKING" in html else len(html))

    def test_hk7_column_merged_into_weekly_section(self):
        """独立栏目取消：kicker 退出顺序表与图标砖；抓取 / 渲染 / 数据源键名 / 审计全保留。"""
        self.assertNotIn("HK 7D PROB", pipeline.REPORT_SECTION_ORDER)
        self.assertNotIn("HK 7D PROB", pipeline._SECTION_ICON_META)
        self.assertTrue(hasattr(pipeline, "_hk_seven_day_block"))   # 渲染函数保留（作子块）
        self.assertTrue(hasattr(pipeline, "fetch_hk_seven_day"))    # 抓取保留（数据源仍进审计）
        self.assertEqual(pipeline.HK7_SOURCE_NAME, "AI 七日港股走势分析概率")

    def test_report_without_key_hides_column_and_audit_entry(self):
        """无 Key（默认）→ 栏目整栏缺席：正文与数据覆盖审计里都不出现。"""
        html = pipeline.generate_report_guizang(
            {"_backup_info": {"events": []}}, "2026年9月29日", "20260929")
        self.assertNotIn("AI 七日港股走势分析概率", html)
        self.assertNotIn("HK 7D PROB", html)

    def test_sector_rotation_column_is_registered_as_a_separate_section(self):
        self.assertTrue(hasattr(pipeline, "fetch_sector_rotation"))
        self.assertTrue(hasattr(pipeline, "_render_sector_rotation"))
        self.assertEqual(pipeline.SECTION_TITLE_SECTOR_ROTATION,
                         "【滚滚翻车鱼】板块轮动量化策略")
        self.assertIn("SECTOR ROTATION", pipeline.REPORT_SECTION_ORDER)
        self.assertIn("SECTOR ROTATION", pipeline._SECTION_ICON_META)
        self.assertLess(pipeline.REPORT_SECTION_ORDER.index("WEEKLY FORECAST"),
                        pipeline.REPORT_SECTION_ORDER.index("SECTOR ROTATION"))
        # 2026-10-14 重排：板块轮动属「④我们该怎么办」，位于总结之前、①发生了什么之后
        self.assertLess(pipeline.REPORT_SECTION_ORDER.index("SECTOR ROTATION"),
                        pipeline.REPORT_SECTION_ORDER.index("SUMMARY"))
        self.assertLess(pipeline.REPORT_SECTION_ORDER.index("MARKET REVIEW"),
                        pipeline.REPORT_SECTION_ORDER.index("SECTOR ROTATION"))
        self.assertTrue((OUTPUT_DIR / "octopus_quant" / "sector_rotation.py").exists())


# ======================================================================
# ④b Jev 本地模型作为第三引擎的管线接入（2026-10-03 起）
# ======================================================================
class JevPipelineWiringTests(unittest.TestCase):
    def _disabled_llm(self):
        return {"enabled": False, "fallback": "auto", "key": "",
                "base": "", "model": "m", "timeout": 10}

    def _jev_config(self, **over):
        cfg = {"enabled": True, "base": "http://mock-jev.invalid", "key": "",
               "timeout": 10, "mode": "auto",
               "label": "Jev 类型化决策（/v1/systemone）"}
        cfg.update(over)
        return cfg

    def _fake_jev_echo(self):
        """协议兼容的假 /v1/systemone：结构合法，概率温和（不触发收敛）。"""
        def fake_post(url, payload, headers, timeout):
            self.assertIn("/v1/systemone", url)
            answers = {}
            for qid, qdef in (payload.get("questions") or {}).items():
                if qdef.get("type") == "choice":
                    keys = list(qdef["criteria"].keys())
                    answers[qid] = {"type": "choice", "choice": keys[0],
                                    "probabilities": {keys[0]: 0.6, keys[1]: 0.3,
                                                      keys[2]: 0.1},
                                    "confidence": 0.7}
                elif qdef.get("type") == "noul":
                    answers[qid] = {"type": "noul", "noul": 0.62, "confidence": 0.8}
                else:
                    answers[qid] = {"type": "score", "score": 2.0,
                                    "probabilities": {"0": 0.1, "1": 0.2, "2": 0.4,
                                                      "3": 0.2, "4": 0.1},
                                    "confidence": 0.6}
            return {"model": "mock-jev", "answers": answers}
        return fake_post

    def _fake_request(self, bars):
        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            m = re.search(r"chart/([^?/]+)", url)
            if not m:
                return None
            return yahoo_chart_payload(m.group(1), bars)
        return fake

    def test_fetch_jev_engine_when_no_llm_key(self):
        """无大模型 Key + 配了 Jev 端点 → 栏目照常出，engine=jev，留痕与渲染都带 Jev。"""
        bars = synthetic_bars()
        # 全量版渲染（LITE_ENABLED=False）：引擎行 / 量化基准对账行 / 七日口径行都可见
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline, "LITE_ENABLED", False), \
                patch.object(pipeline._hk7, "llm_config", return_value=self._disabled_llm()), \
                patch.object(pipeline._jev, "jev_config", return_value=self._jev_config()), \
                patch.object(pipeline._jev, "_get_json",
                             side_effect=lambda *a, **k: {"model": "mock-jev",
                                                          "backend": "mock",
                                                          "precision": "n/a"}), \
                patch.object(pipeline._jev, "_post_json",
                             side_effect=self._fake_jev_echo()), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
            self.assertEqual(src["status"], "success")
            # 渲染（全量版，patch 生效期内）：引擎行点名 Jev，量化基准对账行仍在
            html = pipeline._hk_seven_day_block(src["result"], pipeline.GUIZANG_KIT)
            self.assertIn("Jev", html)
            self.assertIn("量化基准 P", html)
            # 口径行：Jev 引擎不要求文案溯源（模型不产文本），但收敛护栏同一份常量
            self.assertIn("Jev 概率偏离基准", html)
            # Jev 研究留痕落盘（与栏内留痕分文件；在 tmp 销毁前检查）
            self.assertTrue((Path(tmp) / "jev_forecast.json").exists())
        self.assertEqual(src["result"]["engine"], "jev")
        self.assertIn("Jev", src["result"]["engine_label"])
        self.assertTrue(src["jev_note"])
        self.assertIn("使用中", src["jev_note"])

    def test_fetch_no_key_no_jev_still_absent(self):
        """无 Key 且无 Jev 端点（默认）→ 整栏缺席，行为不变。"""
        with patch.object(pipeline._hk7, "llm_config", return_value=self._disabled_llm()), \
                patch.object(pipeline._jev, "jev_config",
                             return_value={"enabled": False, "base": "", "key": "",
                                           "timeout": 10, "mode": "auto"}):
            self.assertIsNone(pipeline.fetch_hk_seven_day({}))

    def test_fetch_jev_dead_endpoint_falls_back_to_quant(self):
        """Jev 端点已配但连不上 → 降级量化基准，jev_note 点名失败原因。"""
        bars = synthetic_bars()
        dead = self._jev_config(base="http://127.0.0.1:1")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline._hk7, "llm_config", return_value=self._disabled_llm()), \
                patch.object(pipeline._jev, "jev_config", return_value=dead), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
        self.assertEqual(src["status"], "success")
        self.assertEqual(src["result"]["engine"], "quant")
        self.assertIn("回退量化基准", src["jev_note"])

    def test_report_data_coverage_names_jev(self):
        """「数据覆盖」审计行点名 Jev 端点状态（落地清单 P1）。"""
        bars = synthetic_bars()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline._hk7, "llm_config", return_value=self._disabled_llm()), \
                patch.object(pipeline._jev, "jev_config", return_value=self._jev_config()), \
                patch.object(pipeline._jev, "_get_json",
                             side_effect=lambda *a, **k: {"model": "mock-jev"}), \
                patch.object(pipeline._jev, "_post_json",
                             side_effect=self._fake_jev_echo()), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
        html = pipeline.generate_report_guizang(
            {pipeline.HK7_SOURCE_NAME: src, "_backup_info": {"events": []}},
            "2026年9月29日", "20260929")
        self.assertIn("数据覆盖", html)
        self.assertIn("Jev：使用中", html)

    def test_report_data_coverage_names_jev_absent_when_endpoint_unset(self):
        """端点未配置时也点名（读者知道 Jev 这条路为什么没走）。"""
        bars = synthetic_bars()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline._hk7, "llm_config",
                             return_value={"enabled": False, "fallback": "always",
                                           "key": "", "base": "", "model": "m",
                                           "timeout": 10}), \
                patch.object(pipeline._jev, "jev_config",
                             return_value={"enabled": False, "base": "", "key": "",
                                           "timeout": 10, "mode": "auto"}), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
        self.assertEqual(src["result"]["engine"], "quant")
        self.assertIn("端点未配置", src["jev_note"])
        html = pipeline.generate_report_guizang(
            {pipeline.HK7_SOURCE_NAME: src, "_backup_info": {"events": []}},
            "2026年9月29日", "20260929")
        self.assertIn("Jev：端点未配置", html)


# ======================================================================
# ⑤ 预测因子与未来函数防线专项测试
# ======================================================================
class PredictiveFactorsAndAntiLookaheadTests(unittest.TestCase):
    def test_assert_no_lookahead_temporal_verification(self):
        ok, msg = hk7.assert_no_lookahead("2026-09-28", "2026-10-07")
        self.assertTrue(ok)
        self.assertIn("时序成立", msg)

        # 目标日等于或早于基准日 -> 判定为未来函数污染
        bad1, msg1 = hk7.assert_no_lookahead("2026-09-28", "2026-09-28")
        self.assertFalse(bad1)
        self.assertIn("未来函数污染", msg1)

        bad2, msg2 = hk7.assert_no_lookahead("2026-09-28", "2026-09-25")
        self.assertFalse(bad2)
        self.assertIn("未来函数污染", msg2)

    def test_next_trading_days_skips_weekends(self):
        # 2026-09-28 是周一；向前推进 7 个工作日：
        # 09-29(二), 09-30(三), 10-01(四), 10-02(五), [跳过周末 10-03/04], 10-05(一), 10-06(二), 10-07(三)
        target = hk7.next_trading_days("2026-09-28", 7)
        self.assertEqual(target, "2026-10-07")

    def test_check_input_closure_rejects_future_dates(self):
        base = "2026-09-28"
        # 未来日期渗入
        leaked_extra = {
            "flows": {"south_amount_yi": 500.0, "south_date": "2026-09-30"},
            "global_quotes": {"标普500": {"change_pct": 0.5, "as_of": "2026-09-29"}},
        }
        ok, warns, cleaned = hk7.check_input_closure(base, leaked_extra)
        self.assertFalse(ok)
        self.assertEqual(len(warns), 2)
        self.assertNotIn("south_date", cleaned["flows"])
        self.assertNotIn("标普500", cleaned["global_quotes"])

        # 合法日期闭合
        valid_extra = {
            "flows": {"south_amount_yi": 500.0, "south_date": "2026-09-28"},
            "global_quotes": {"标普500": {"change_pct": 0.5, "as_of": "2026-09-28"}},
        }
        ok_v, warns_v, cleaned_v = hk7.check_input_closure(base, valid_extra)
        self.assertTrue(ok_v)
        self.assertEqual(len(warns_v), 0)
        self.assertEqual(cleaned_v["flows"]["south_amount_yi"], 500.0)

    def test_predictive_factors_momentum_continuation_and_stretch(self):
        # 适度动量 -> 延续
        score_norm, desc_norm = hk7.compute_momentum_factor(0.02, sigma=0.012)
        self.assertGreater(score_norm, 0)
        self.assertIn("延续", desc_norm)

        # 极端超涨 (>2σ) -> 均值回归反向扣减
        score_extreme, desc_extreme = hk7.compute_momentum_factor(0.20, sigma=0.012)
        self.assertIn("均值回归", desc_extreme)

    def test_predictive_factors_rsi_oscillator(self):
        # 超买 > 70 -> 看跌/回调
        rev_ob, desc_ob = hk7.compute_reversal_factor(78.0, 0.0)
        self.assertLess(rev_ob, 0)
        self.assertIn("超买", desc_ob)

        # 超卖 < 30 -> 反弹
        rev_os, desc_os = hk7.compute_reversal_factor(22.0, -0.15)
        self.assertGreater(rev_os, 0)
        self.assertIn("超卖", desc_os)

    def test_predictive_factors_global_carry_beta(self):
        quotes = {
            "标普500": {"change_pct": 1.1},
            "纳斯达克": {"change_pct": 1.5},
            "道琼斯指数": {"change_pct": 0.8},
        }
        score_tech, _ = hk7.compute_global_carry_factor("^HSTECH", quotes)
        score_hsi, _ = hk7.compute_global_carry_factor("^HSI", quotes)
        score_soe, _ = hk7.compute_global_carry_factor("^HSCE", quotes)
        # 恒生科技 beta=0.75 > 恒指 0.55 > 国企 0.50
        self.assertGreater(score_tech, score_hsi)
        self.assertGreater(score_hsi, score_soe)

    def test_predictive_factors_capital_flow(self):
        flows = {"south_amount_yi": 650.0, "liquidity_score": 75.0}
        score, desc = hk7.compute_capital_flow_factor(flows)
        self.assertGreater(score, 0)
        self.assertIn("南向", desc)

    def test_volatility_shrinkage_on_extreme_vol(self):
        shrink_high, desc_high = hk7.compute_volatility_shrinkage(0.88)
        self.assertLess(shrink_high, 1.0)
        self.assertIn("收缩", desc_high)

        shrink_normal, _ = hk7.compute_volatility_shrinkage(0.50)
        self.assertEqual(shrink_normal, 1.0)

    def test_extra_context_extracts_global_quotes_in_pipeline(self):
        sample_data = {
            "实时行情": {
                "status": "success",
                "quotes": {
                    "标普500": {"change_pct": 0.65, "as_of": "2026-09-28"},
                    "纳斯达克": {"change_pct": 0.82, "as_of": "2026-09-28"},
                    "道琼斯指数": {"change_pct": 0.40, "as_of": "2026-09-28"},
                }
            },
            "A股大盘全景": {
                "north": {"south_available": True, "south_amount_yi": 521.8, "south_date": "2026-09-28"}
            }
        }
        extra = pipeline._hk7_extra_context(sample_data)
        self.assertIn("标普500", extra.get("global_quotes", {}))
        self.assertEqual(extra["global_quotes"]["标普500"]["change_pct"], 0.65)
        self.assertEqual(extra["flows"]["south_amount_yi"], 521.8)


if __name__ == "__main__":
    unittest.main()
