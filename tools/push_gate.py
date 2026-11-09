#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📅 自动推送门禁与状态账本（按「当日早盘 / 晚间是否已推」去重，而非卡死整点小时数）。

解决的问题（2026-10-01 ~ 11-09 核查复盘）：
  GitHub Actions 的 `schedule` 触发受平台队列负载影响，经常延迟 4~8 小时，且
  2 小时步长的单条 cron 会被合并丢档。此前工作流用「当前北京时间必须是
  09/10/21/22 时，否则 --no-push」的硬小时窗口，导致：
    · 09:00 早盘档延迟到 13~15 时后，39 天内 39/39 次被转成 --no-push（100% 漏推）；
    · 晚间档落在 19~20 时或跨日到 23~03 时同样被 --no-push。

新机制（与 .github/workflows/octopus-daily.yml、octopus-evening.yml 配套）：
  1. 将北京时间划分为两个推送窗口 + 一个凌晨兜底窗口 + 深夜静默窗口：
       · 07:00 ~ 19:29  → 当日「早盘（morning）」窗口（覆盖 09:17 准点及最多 ~10h 延迟）
       · 19:30 ~ 23:59  → 当日「晚间（evening）」窗口（A 股/港股收盘且晚间要闻齐备后）
       · 00:00 ~ 01:59  → 昨日「晚间（evening）」跨日兜底窗口（若昨日晚间仍未推则补推；
                          绝不占用今日早盘额度）
       · 02:00 ~ 06:59  → 深夜静默窗口（一律 --no-push，不凌晨扰民，不抢占今日早盘）
  2. 每次定时触发先查 `output/push_state.json`：
       · 该窗口对应的 `(逻辑日期, 时段)` 尚未成功推过日报正文 → `mode=push`；
       · 已经成功推过 → `mode=no-push`（只更新网页与留痕，不再重复打扰微信）。
  3. 只有当 `output/pipeline.py` 退出码为 0 且确认真正发出日报正文（未落入
     「当天检验未通过，本次不推送日报」告警分支）时，才调用 `record` 记入账本。

本工具只用 Python 标准库，离线确定性，便于 tests/test_push_gate.py 全覆盖回归。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

CST = timezone(timedelta(hours=8))
DEFAULT_RETAIN_DAYS = 60

SLOT_MORNING = "morning"
SLOT_EVENING = "evening"
SLOT_QUIET = "quiet"

# 与 output/pipeline.py::main() 末尾打印严格对齐：
# · 当天检验通过并推送成功 → 打印 "🎉 全部完成！"
# · 当天检验未通过仅发提醒 → 打印 "⏸️ 当天检验未通过，本次不推送日报。" 与
#   "🎉 全部完成（日报未推，已发出检验未通过告警）！"
NO_PUSH_ALERT_MARKERS = (
    "当天检验未通过，本次不推送日报",
    "日报未推，已发出检验未通过告警",
)
PUSH_SUCCESS_MARKER = "🎉 全部完成！"


def parse_cst_now(now_str: Optional[str] = None) -> datetime:
    """解析可选 ISO 时间戳并转换到北京时间（UTC+8）；未传则取当前时刻。"""
    if not now_str:
        return datetime.now(CST)
    text = now_str.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=CST)
    return dt.astimezone(CST)


def resolve_window(now_cst: datetime) -> Tuple[str, str, str]:
    """根据当前北京时间返回 `(逻辑日期 YYYY-MM-DD, 时段, 窗口说明)`。"""
    minutes = now_cst.hour * 60 + now_cst.minute
    today = now_cst.strftime("%Y-%m-%d")
    yesterday = (now_cst.date() - timedelta(days=1)).strftime("%Y-%m-%d")

    if 7 * 60 <= minutes < 19 * 60 + 30:
        return today, SLOT_MORNING, "早盘窗口 07:00-19:29"
    if minutes >= 19 * 60 + 30:
        return today, SLOT_EVENING, "晚间窗口 19:30-23:59"
    if minutes < 2 * 60:
        return yesterday, SLOT_EVENING, "昨日晚间跨日兜底窗口 00:00-01:59"
    return today, SLOT_QUIET, "深夜静默窗口 02:00-06:59"


def load_state(path: str) -> Dict[str, Any]:
    """加载推送状态账本；缺失或损坏时按空账本冷启动（不阻断日报推送）。"""
    empty: Dict[str, Any] = {"version": 1, "days": {}, "updated_cst": ""}
    if not path or not os.path.isfile(path):
        return empty
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"⚠️ 读取推送状态账本失败（{path}: {exc}）→ 按空账本冷启动", file=sys.stderr)
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
        return empty
    days = {k: v for k, v in data["days"].items() if isinstance(k, str) and isinstance(v, dict)}
    return {
        "version": int(data.get("version") or 1),
        "days": days,
        "updated_cst": str(data.get("updated_cst") or ""),
    }


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def decide(state_path: str, now_cst: Optional[datetime] = None) -> Dict[str, str]:
    """判定本次定时运行应当 `push` 还是 `no-push`。"""
    current = (now_cst.astimezone(CST) if now_cst and now_cst.tzinfo
               else (now_cst.replace(tzinfo=CST) if now_cst else datetime.now(CST)))
    target_date, slot, window_desc = resolve_window(current)
    hhmm = current.strftime("%H:%M")

    if slot == SLOT_QUIET:
        return {
            "mode": "no-push",
            "target_date": target_date,
            "slot": slot,
            "reason": f"当前北京 {hhmm}（{window_desc}），保持静默更新，不打扰微信且不占用早盘额度",
        }

    state = load_state(state_path)
    day_rec = state["days"].get(target_date)
    slot_rec = day_rec.get(slot) if isinstance(day_rec, dict) else None
    slot_label = "早盘" if slot == SLOT_MORNING else "晚间"

    if isinstance(slot_rec, dict) and slot_rec.get("pushed") is True:
        prev_at = slot_rec.get("at_cst") or "早前"
        return {
            "mode": "no-push",
            "target_date": target_date,
            "slot": slot,
            "reason": f"{target_date} {slot_label}已于 {prev_at} 推送成功（当前北京 {hhmm}），本次转为静默更新",
        }

    return {
        "mode": "push",
        "target_date": target_date,
        "slot": slot,
        "reason": f"{target_date} {slot_label}尚未成功推送（当前北京 {hhmm} · {window_desc}），执行推微信",
    }


def prune_days(days: Dict[str, Any], anchor_date: str, retain_days: int = DEFAULT_RETAIN_DAYS) -> Dict[str, Any]:
    """只保留最近 retain_days 天的状态记录，避免文件无限增长。"""
    if retain_days <= 0:
        return dict(days)
    try:
        cutoff = (datetime.strptime(anchor_date, "%Y-%m-%d").date() - timedelta(days=retain_days)).strftime("%Y-%m-%d")
    except ValueError:
        return dict(days)
    return {d: v for d, v in days.items() if d >= cutoff}


def record_push(
    state_path: str,
    target_date: str,
    slot: str,
    workflow: str = "",
    run_id: str = "",
    now_cst: Optional[datetime] = None,
    retain_days: int = DEFAULT_RETAIN_DAYS,
) -> Dict[str, Any]:
    """在确认日报正文已送达后，把 `(target_date, slot)` 写入推送状态账本。"""
    if slot not in (SLOT_MORNING, SLOT_EVENING):
        raise ValueError(f"不支持写入推送账本的时段: {slot}")
    current = (now_cst.astimezone(CST) if now_cst and now_cst.tzinfo
               else (now_cst.replace(tzinfo=CST) if now_cst else datetime.now(CST)))
    stamp = current.strftime("%Y-%m-%d %H:%M:%S%z")

    state = load_state(state_path)
    days = dict(state["days"])
    day_rec = dict(days.get(target_date) or {})
    entry: Dict[str, Any] = {
        "pushed": True,
        "at_cst": stamp,
    }
    if workflow:
        entry["workflow"] = workflow
    if run_id:
        entry["run_id"] = str(run_id)
    day_rec[slot] = entry
    days[target_date] = day_rec

    new_state = {
        "version": 1,
        "days": prune_days(days, target_date, retain_days=retain_days),
        "updated_cst": stamp,
    }
    _atomic_write_json(state_path, new_state)
    return new_state


def verify_pipeline_log(log_text: str) -> Tuple[bool, str]:
    """检查 pipeline.py 标准输出日志，确认是否真正发送了日报正文。"""
    for marker in NO_PUSH_ALERT_MARKERS:
        if marker in log_text:
            return False, f"命中未推日报告警标记：{marker}"
    if PUSH_SUCCESS_MARKER in log_text:
        return True, "确认日报正文已推送成功"
    return False, "日志中未出现日报推送成功标记"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="🐙 自动推送门禁与状态账本")
    sub = parser.add_subparsers(dest="command", required=True)

    p_decide = sub.add_parser("decide", help="判断本次定时运行应 push 还是 no-push")
    p_decide.add_argument("--state", required=True, help="状态文件（如 output/push_state.json）")
    p_decide.add_argument("--now", default="", help="可选 ISO 时间戳（单测用）")
    p_decide.add_argument("--format", choices=("tsv", "json"), default="tsv")

    p_record = sub.add_parser("record", help="记录本次定时推送成功")
    p_record.add_argument("--state", required=True, help="状态文件（如 output/push_state.json）")
    p_record.add_argument("--date", required=True, help="逻辑日期 YYYY-MM-DD")
    p_record.add_argument("--slot", required=True, choices=(SLOT_MORNING, SLOT_EVENING))
    p_record.add_argument("--workflow", default="")
    p_record.add_argument("--run-id", default="")
    p_record.add_argument("--now", default="", help="可选 ISO 时间戳（单测用）")
    p_record.add_argument("--retain-days", type=int, default=DEFAULT_RETAIN_DAYS)

    p_verify = sub.add_parser("verify-log", help="校验 pipeline 输出是否真正送达了日报正文")
    p_verify.add_argument("--log", required=True, help="pipeline 日志文件路径")

    args = parser.parse_args(argv)

    if args.command == "decide":
        now_cst = parse_cst_now(args.now) if args.now else None
        result = decide(args.state, now_cst=now_cst)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False))
        else:
            # 替换潜在制表符/换行，保证单行 TSV 严格安全
            fields = [
                result["mode"],
                result["target_date"],
                result["slot"],
                result["reason"].replace("\t", " ").replace("\n", " "),
            ]
            print("\t".join(fields))
        return 0

    if args.command == "record":
        now_cst = parse_cst_now(args.now) if args.now else None
        record_push(
            args.state,
            args.date,
            args.slot,
            workflow=args.workflow,
            run_id=args.run_id,
            now_cst=now_cst,
            retain_days=args.retain_days,
        )
        print(f"✅ 已记录自动推送状态：{args.date} {args.slot}")
        return 0

    if args.command == "verify-log":
        with open(args.log, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        ok, msg = verify_pipeline_log(text)
        if not ok:
            print(f"ℹ️ {msg}")
            return 1
        print(f"✅ {msg}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
