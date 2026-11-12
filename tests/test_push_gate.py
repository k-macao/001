#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📅 自动推送门禁（tools/push_gate.py）与早/晚定时拆分工作流离线回归测试。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import push_gate as pg  # noqa: E402


class TestPushGateWindowAndDedup(unittest.TestCase):
    """覆盖全天 24 小时窗口判定、延迟补推、跨日兜底与防重推逻辑。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="octopus-gate-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.state_path = str(self.tmp / "push_state.json")

    def _decide(self, iso_cst: str):
        return pg.decide(self.state_path, now_cst=pg.parse_cst_now(iso_cst))

    def test_on_time_morning_and_delayed_morning_both_push_once(self):
        # 09:17 准点或延迟至 14:47 / 18:10，只要早盘未推过都应当执行 push
        for ts in ("2026-11-10T09:17:00+08:00", "2026-11-10T14:47:00+08:00", "2026-11-10T19:29:00+08:00"):
            d = self._decide(ts)
            self.assertEqual(d["mode"], "push", ts)
            self.assertEqual(d["target_date"], "2026-11-10")
            self.assertEqual(d["slot"], pg.SLOT_MORNING)

        # 记入 2026-11-10 早盘成功推送后，午后/傍晚再触发一律转 --no-push
        pg.record_push(self.state_path, "2026-11-10", pg.SLOT_MORNING,
                       workflow="octopus-daily.yml", run_id="1001",
                       now_cst=pg.parse_cst_now("2026-11-10T14:50:00+08:00"))
        for ts in ("2026-11-10T15:23:00+08:00", "2026-11-10T17:41:00+08:00", "2026-11-10T19:29:00+08:00"):
            d = self._decide(ts)
            self.assertEqual(d["mode"], "no-push", ts)
            self.assertEqual(d["slot"], pg.SLOT_MORNING)

    def test_evening_window_starts_at_1930_and_dedups(self):
        pg.record_push(self.state_path, "2026-11-10", pg.SLOT_MORNING,
                       now_cst=pg.parse_cst_now("2026-11-10T14:50:00+08:00"))

        d = self._decide("2026-11-10T19:30:00+08:00")
        self.assertEqual(d["mode"], "push")
        self.assertEqual(d["target_date"], "2026-11-10")
        self.assertEqual(d["slot"], pg.SLOT_EVENING)

        pg.record_push(self.state_path, "2026-11-10", pg.SLOT_EVENING,
                       now_cst=pg.parse_cst_now("2026-11-10T21:25:00+08:00"))
        for ts in ("2026-11-10T22:10:00+08:00", "2026-11-10T23:59:00+08:00"):
            d2 = self._decide(ts)
            self.assertEqual(d2["mode"], "no-push", ts)
            self.assertEqual(d2["slot"], pg.SLOT_EVENING)

    def test_midnight_spillover_only_recovers_yesterday_evening_never_steals_today_morning(self):
        # 11-10 00:45 触发：若 11-09 晚间未推，应补推 11-09 evening，且不影响 11-10 morning
        d = self._decide("2026-11-10T00:45:00+08:00")
        self.assertEqual(d["mode"], "push")
        self.assertEqual(d["target_date"], "2026-11-09")
        self.assertEqual(d["slot"], pg.SLOT_EVENING)

        pg.record_push(self.state_path, "2026-11-09", pg.SLOT_EVENING,
                       now_cst=pg.parse_cst_now("2026-11-10T00:48:00+08:00"))
        # 同一晚 01:30 再来不再重复推昨日晚间
        d_repeat = self._decide("2026-11-10T01:30:00+08:00")
        self.assertEqual(d_repeat["mode"], "no-push")
        self.assertEqual(d_repeat["target_date"], "2026-11-09")

        # 11-10 白天早盘依然可以正常推送！
        d_morning = self._decide("2026-11-10T09:20:00+08:00")
        self.assertEqual(d_morning["mode"], "push")
        self.assertEqual(d_morning["target_date"], "2026-11-10")
        self.assertEqual(d_morning["slot"], pg.SLOT_MORNING)

    def test_deep_night_0200_to_0659_is_always_silent(self):
        for ts in ("2026-11-10T02:00:00+08:00", "2026-11-10T03:17:00+08:00", "2026-11-10T06:59:00+08:00"):
            d = self._decide(ts)
            self.assertEqual(d["mode"], "no-push", ts)
            self.assertEqual(d["slot"], pg.SLOT_QUIET)

    def test_corrupt_state_file_recovers_gracefully(self):
        Path(self.state_path).write_text("{corrupt json", encoding="utf-8")
        d = self._decide("2026-11-10T14:30:00+08:00")
        self.assertEqual(d["mode"], "push")
        self.assertEqual(d["slot"], pg.SLOT_MORNING)

    def test_retention_prunes_old_days(self):
        pg.record_push(self.state_path, "2026-08-01", pg.SLOT_MORNING,
                       now_cst=pg.parse_cst_now("2026-08-01T09:20:00+08:00"),
                       retain_days=30)
        pg.record_push(self.state_path, "2026-11-10", pg.SLOT_MORNING,
                       now_cst=pg.parse_cst_now("2026-11-10T09:20:00+08:00"),
                       retain_days=30)
        data = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertNotIn("2026-08-01", data["days"])
        self.assertIn("2026-11-10", data["days"])

    def test_verify_pipeline_log_distinguishes_report_push_from_no_push_alert(self):
        ok, _ = pg.verify_pipeline_log("📤 当天检验通过：11/25\n🎉 全部完成！\n")
        self.assertTrue(ok)

        alert_log = "⏸️ 当天检验未通过，本次不推送日报。\n🎉 全部完成（日报未推，已发出检验未通过告警）！\n"
        ok_alert, _ = pg.verify_pipeline_log(alert_log)
        self.assertFalse(ok_alert)

        fail_log = "❌ 流程完成，但推送未成功\n"
        ok_fail, _ = pg.verify_pipeline_log(fail_log)
        self.assertFalse(ok_fail)

    def test_cli_tsv_and_record_round_trip(self):
        out = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "push_gate.py"),
             "decide", "--state", self.state_path, "--now", "2026-11-10T15:00:00+08:00", "--format", "tsv"],
            capture_output=True, text=True, check=True,
        )
        mode, date_s, slot, reason = out.stdout.strip().split("\t")
        self.assertEqual((mode, date_s, slot), ("push", "2026-11-10", "morning"))
        self.assertIn("早盘", reason)

        subprocess.run(
            [sys.executable, str(TOOLS_DIR / "push_gate.py"),
             "record", "--state", self.state_path, "--date", date_s, "--slot", slot,
             "--workflow", "octopus-daily.yml", "--run-id", "42",
             "--now", "2026-11-10T15:04:00+08:00"],
            capture_output=True, text=True, check=True,
        )

        out2 = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "push_gate.py"),
             "decide", "--state", self.state_path, "--now", "2026-11-10T17:00:00+08:00", "--format", "tsv"],
            capture_output=True, text=True, check=True,
        )
        mode2, date2, slot2, _ = out2.stdout.strip().split("\t")
        self.assertEqual((mode2, date2, slot2), ("no-push", "2026-11-10", "morning"))

    def test_morning_workflow_delayed_past_1930_does_not_steal_evening_slot(self):
        # 复现 2026-11-10 事故：早盘 11:47 档延迟到 19:49 才触发时，绝不可抢发 evening
        pg.record_push(self.state_path, "2026-11-10", pg.SLOT_MORNING,
                       workflow="octopus-daily.yml", run_id="1001",
                       now_cst=pg.parse_cst_now("2026-11-10T16:33:27+08:00"))

        for ts, expected_date in (
            ("2026-11-10T19:49:05+08:00", "2026-11-10"),
            ("2026-11-11T00:45:00+08:00", "2026-11-10"),
        ):
            d = pg.decide(self.state_path, now_cst=pg.parse_cst_now(ts),
                          allow_slots=(pg.SLOT_MORNING,))
            self.assertEqual(d["mode"], "no-push", ts)
            self.assertEqual(d["target_date"], expected_date, ts)
            self.assertEqual(d["slot"], pg.SLOT_EVENING, ts)
            self.assertIn("仅允许推送早盘", d["reason"])

        # 随后晚间工作流在 23:41 到场仍应正常推送 2026-11-10 evening
        d_evening = pg.decide(self.state_path,
                              now_cst=pg.parse_cst_now("2026-11-10T23:41:30+08:00"))
        self.assertEqual(d_evening["mode"], "push")
        self.assertEqual(d_evening["target_date"], "2026-11-10")
        self.assertEqual(d_evening["slot"], pg.SLOT_EVENING)

    def test_allow_slots_rejects_invalid_and_empty_inputs_and_cli_round_trip(self):
        with self.assertRaises(ValueError):
            pg.decide(self.state_path, now_cst=pg.parse_cst_now("2026-11-10T04:00:00+08:00"),
                      allow_slots=("quiet",))
        with self.assertRaises(ValueError):
            pg.parse_allow_slots("")
        with self.assertRaises(ValueError):
            pg.parse_allow_slots("noon")

        bad = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "push_gate.py"),
             "decide", "--state", self.state_path, "--allow-slots", "noon", "--format", "tsv"],
            capture_output=True, text=True,
        )
        self.assertEqual(bad.returncode, 2)

        ok = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "push_gate.py"),
             "decide", "--state", self.state_path, "--allow-slots", "morning",
             "--now", "2026-11-10T19:49:05+08:00", "--format", "tsv"],
            capture_output=True, text=True, check=True,
        )
        mode, date_s, slot, reason = ok.stdout.strip().split("\t")
        self.assertEqual((mode, date_s, slot), ("no-push", "2026-11-10", "evening"))
        self.assertIn("仅允许推送早盘", reason)


class TestAutoScheduleWorkflowsConfig(unittest.TestCase):
    """确保早盘与晚间两条工作流已拆分、错开整点并接入 push_gate。"""

    def test_morning_and_evening_workflows_avoid_top_of_hour_and_hour_cutoff(self):
        for fname in ("octopus-daily.yml", "octopus-evening.yml"):
            text = (WORKFLOW_DIR / fname).read_text(encoding="utf-8")
            with self.subTest(workflow=fname):
                self.assertIn("tools/push_gate.py decide", text)
                self.assertIn("tools/push_gate.py verify-log", text)
                self.assertIn("tools/push_gate.py record", text)
                self.assertIn("output/push_state.json", text)
                # 不得退回旧版固定小时截断逻辑
                self.assertNotIn('"$CURRENT_HOUR" != "09"', text)
                crons = re.findall(r'cron:\s*"([^"]+)"', text)
                self.assertTrue(crons, f"{fname} 缺少 cron 触发配置")
                for expr in crons:
                    minute_field = expr.split()[0]
                    self.assertNotEqual(minute_field, "0", f"{fname} cron 不应设在整点 0 分: {expr}")
        daily_text = (WORKFLOW_DIR / "octopus-daily.yml").read_text(encoding="utf-8")
        self.assertIn("--allow-slots morning", daily_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
