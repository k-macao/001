#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧬 生成物合并策略：把「远端已入库的版本」与「本次刚生成的版本」合成一份不丢数据的文件。

为什么需要它（2026-10-04 事故复盘）：
    日报工作流从「检出时的那份 main」出发跑 2 分钟，再把生成物提交推回 main。
    这 2 分钟里 main 可能已经被别人推动（另一个工作流、手动重跑、甚至一个 PR 合并），
    于是 `git push` 被拒（`! [rejected] HEAD -> main (fetch first)`）。
    补救动作是「把本次改动重放到远端最新提交之上」，而重放时同一个文件两边都改过：
      · 日报 HTML（daily_report_*.html / latest.html）——每次都是整份重新生成，
        本次运行的数据更新，**以本次为准**；
      · 留痕 JSON（news_history / sentiment_history / quant_history / hk7_forecast /
        weekly_forecast）——**追加型账本**，两边各自记了不同的条目；直接取一边就会
        永久丢掉另一边的条目（丢一次 = 少一条预测留痕、少一段情绪基线，命中率统计
        会跟着失真）。所以按各文件自己的键做**并集合并**；
      · 市场数据库 output/market_db/*.json——文件里带 sha256 自校验
        （`integrity.hash`，见 output/market_db.py 的 `verify_integrity`），
        任何内容级合并都会让哈希对不上，**只能整份取一边**（取本次，并告警）。

口径（与 output/pipeline.py 的 `_merge_news_corpus` / `_update_sentiment_history 一致）：
    · 同一条目两边都有 → 本次（local）优先，但远端的非空字段补进来，
      且**已结算（settled=True）的留痕绝不被未结算的副本覆盖**；
    · 只有远端有 → 保留（这是本次检出之后别人新记的账）；
    · 只有本次有 → 保留；
    · 本次的值是 None / 空串 / 空容器，而远端有实值 → 用远端的实值
      （防止「本次没跑到结算」把已结算结果擦掉）。

用法（tools/safe_push.sh 调用，也可手工排查）：
    python3 tools/merge_generated.py policy output/news_history.json
    python3 tools/merge_generated.py merge <仓库相对路径> <远端文件> <本次文件> -o <输出文件>

退出码：0 成功；1 参数 / 读写错误；2 无法识别的用法。
本模块只用标准库，离线确定性，可被 tests/test_safe_push.py 直接单测。
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# 每个文件的合并规则（按仓库相对路径匹配；前缀规则放最后）
# ============================================================
# 追加型「条目列表」账本：list 字段名 + 判定「同一条」的身份键 + 可选的排序时间键
JOURNAL_RULES: Dict[str, Dict[str, Any]] = {
    "output/news_history.json": {
        "list": "items",
        "identity": ("date", "title"),
        "protect": "official",               # 远端已确认的中国政府网溯源不被媒体记录降级
        # 不排序：条目顺序对下游无意义（pipeline 按日期窗口过滤），保持「远端在前、
        # 本次新增在后」的追加顺序，diff 最小
    },
    "output/hk7_forecast.json": {
        "list": "entries",
        "identity": ("symbol", "base_date"),
        "sort_by": "issued_cst",             # 留痕按「尾部 N 条」裁剪，必须保持时间顺序
        "settle_key": "settled",             # 已结算者优先（历史事实不可回退）
    },
    "output/weekly_forecast.json": {
        "list": "entries",
        "identity": ("symbol", "base_date"),
        "sort_by": "issued_cst",
        "settle_key": "settled",
    },
}

# 追加型「按键字典」账本：map 字段名 + 可选的第二层字典键（如每只个股下按日期）
LEDGER_RULES: Dict[str, Dict[str, Any]] = {
    "output/sentiment_history.json": {"map": "stocks", "sub_map": "days"},
    "output/quant_history.json": {"map": "days", "sub_map": None},
    "output/push_state.json": {"map": "days", "sub_map": None},
}

# 只能整份取一边：文件自带内容哈希，合并后哈希必然对不上
LOCAL_ONLY_PREFIXES: Tuple[str, ...] = ("output/market_db/",)

# 输出格式必须与各文件的写入方保持一致，否则每次运行都会产生「无意义的全文件 diff」：
#   output/pipeline.py::_atomic_write         → json.dumps(..., ensure_ascii=False, indent=1)
#   output/hk_seven_day.py::_save_journal     → json.dump(..., ensure_ascii=False, sort_keys=True)
#   output/octopus_weekly.py::_save_journal   → 同上
#   output/octopus_quant/engine.py::_save     → 同上（compact + sort_keys）
#   tools/push_gate.py::_atomic_write_json    → json.dumps(..., ensure_ascii=False, indent=2, sort_keys=True)
STYLE_RULES: Dict[str, Dict[str, Any]] = {
    "output/news_history.json": {"indent": 1, "sort_keys": False},
    "output/sentiment_history.json": {"indent": 1, "sort_keys": False},
    "output/quant_history.json": {"indent": None, "sort_keys": True},
    "output/hk7_forecast.json": {"indent": None, "sort_keys": True},
    "output/weekly_forecast.json": {"indent": None, "sort_keys": True},
    "output/push_state.json": {"indent": 2, "sort_keys": True},
}

POLICY_JOURNAL = "journal"     # 条目列表并集
POLICY_LEDGER = "ledger"       # 按键字典并集
POLICY_DEEP = "deep"           # 其它 JSON：递归合并，本次优先、远端补空
POLICY_LOCAL = "local"         # 非 JSON / 自校验文件：整份以本次为准


def _norm(relpath: str) -> str:
    """统一成仓库相对路径（反斜杠、前导 ./ 都去掉），便于规则匹配。"""
    path = (relpath or "").replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    return path


def policy_for(relpath: str) -> str:
    """返回该路径的合并策略名（journal / ledger / deep / local）。"""
    path = _norm(relpath)
    if path in JOURNAL_RULES:
        return POLICY_JOURNAL
    if path in LEDGER_RULES:
        return POLICY_LEDGER
    if any(path.startswith(prefix) for prefix in LOCAL_ONLY_PREFIXES):
        return POLICY_LOCAL
    if path.endswith(".json") or path.endswith(".jsonl"):
        return POLICY_DEEP
    return POLICY_LOCAL


# ============================================================
# 基础合并原语
# ============================================================
def _is_empty(value: Any) -> bool:
    """None / 空串 / 空列表 / 空字典 视为「本次没有值」。"""
    if value is None:
        return True
    if isinstance(value, (str, list, dict, tuple)) and len(value) == 0:
        return True
    return False


def deep_merge(remote: Any, local: Any) -> Any:
    """递归合并：本次（local）优先，远端补空缺。

    · 两边都是 dict → 逐键递归；
    · 本次为空、远端有实值 → 用远端（保住已结算结果 / 已抓到的字段）；
    · 其它情况 → 用本次（本次是更新的一轮运行）。
    """
    if isinstance(remote, dict) and isinstance(local, dict):
        merged: Dict[str, Any] = {}
        for key in list(remote.keys()) + [k for k in local.keys() if k not in remote]:
            if key in local and key in remote:
                merged[key] = deep_merge(remote[key], local[key])
            elif key in local:
                merged[key] = local[key]
            else:
                merged[key] = remote[key]
        return merged
    if _is_empty(local) and not _is_empty(remote):
        return remote
    return local


def _fill_missing(preferred: Dict[str, Any], filler: Dict[str, Any]) -> Dict[str, Any]:
    """同一条目两边都有：preferred 的字段优先，filler 只补 preferred 的空缺。"""
    merged = dict(filler)
    for key, value in preferred.items():
        if not _is_empty(value) or _is_empty(merged.get(key)):
            merged[key] = value
    return merged


def _richness(record: Dict[str, Any]) -> int:
    """条目「信息量」= 非空字段数，用于同一条目两边都有时挑更完整的一份。"""
    return sum(1 for value in record.values() if not _is_empty(value))


def _resolve_collision(rule: Dict[str, Any], existing: Any, incoming: Any) -> Any:
    """同一身份键的两份记录怎么裁决（existing 已在表里，incoming 是刚遇到的那条）。

    默认「本次优先、另一边补空缺」——本次是更晚完成的一轮运行，数据更新；
    但两种**历史事实**不许被降级：
      · settle_key（settled）：已按真实收盘结算过的留痕，不能被未结算副本覆盖；
      · protect（official）：已确认的中国政府网官方溯源，不能被媒体同名记录覆盖。
    """
    if not (isinstance(existing, dict) and isinstance(incoming, dict)):
        return incoming
    for key in (rule.get("settle_key"), rule.get("protect")):
        if key and existing.get(key) and not incoming.get(key):
            return _fill_missing(existing, incoming)      # 受保护的一方优先，另一方补空缺
    return _fill_missing(incoming, existing)              # 默认：incoming（本次）优先


def _identity(record: Any, keys: Tuple[str, ...]) -> Optional[Tuple[Any, ...]]:
    if not isinstance(record, dict):
        return None
    ident = tuple(record.get(key) for key in keys)
    if all(part in (None, "") for part in ident):
        return None          # 没有任何身份字段 → 不参与去重，原样保留
    return ident


# ============================================================
# 三种 JSON 合并
# ============================================================
def merge_journal(relpath: str, remote: Dict[str, Any], local: Dict[str, Any]) -> Dict[str, Any]:
    """条目列表并集（news_history.items / *_forecast.entries）。"""
    rule = JOURNAL_RULES[_norm(relpath)]
    list_key = rule["list"]
    ident_keys: Tuple[str, ...] = tuple(rule["identity"])
    sort_by = rule.get("sort_by")

    merged = dict(local)                      # 顶层标量（version / updated_cst）以本次为准
    remote_items = remote.get(list_key) if isinstance(remote, dict) else None
    local_items = local.get(list_key) if isinstance(local, dict) else None
    if not isinstance(remote_items, list) or not isinstance(local_items, list):
        return merged                         # 结构不认识 → 不猜，以本次为准

    by_ident: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    order: List[Tuple[Any, ...]] = []
    anonymous: List[Any] = []

    # 远端先入表、本次后覆盖：跨边碰撞时 incoming 恒为本次（更晚完成的一轮运行）
    for record in list(remote_items) + list(local_items):
        ident = _identity(record, ident_keys)
        if ident is None:
            anonymous.append(record)          # 没有身份字段的条目不去重，原样保留
            continue
        existing = by_ident.get(ident)
        if existing is None:
            by_ident[ident] = dict(record) if isinstance(record, dict) else record
            order.append(ident)
        else:
            by_ident[ident] = _resolve_collision(rule, existing, record)

    result: List[Any] = [by_ident[ident] for ident in order] + anonymous

    # 声明了 sort_by 的账本（预测留痕）按时间稳定排序：这些文件按「尾部 N 条」裁剪，
    # 顺序错了就会把新条目裁掉、把旧条目留下
    if sort_by:
        def stamp(record: Any) -> Optional[str]:
            if not isinstance(record, dict):
                return None
            value = record.get(sort_by)
            return value if isinstance(value, str) and value else None

        if all(stamp(record) is not None for record in result):
            result.sort(key=lambda record: stamp(record) or "")

    merged[list_key] = result
    return merged


def merge_ledger(relpath: str, remote: Dict[str, Any], local: Dict[str, Any]) -> Dict[str, Any]:
    """按键字典并集（sentiment_history.stocks[个股][日期] / quant_history.days[日期]）。"""
    rule = LEDGER_RULES[_norm(relpath)]
    map_key = rule["map"]
    sub_key = rule.get("sub_map")

    merged = dict(local)
    remote_map = remote.get(map_key) if isinstance(remote, dict) else None
    local_map = local.get(map_key) if isinstance(local, dict) else None
    if not isinstance(remote_map, dict) or not isinstance(local_map, dict):
        return merged

    combined: Dict[str, Any] = {}
    for name in list(remote_map.keys()) + [k for k in local_map if k not in remote_map]:
        remote_rec = remote_map.get(name)
        local_rec = local_map.get(name)
        if local_rec is None:
            combined[name] = remote_rec                  # 只有远端有 → 保住
            continue
        if remote_rec is None:
            combined[name] = local_rec
            continue
        if isinstance(remote_rec, dict) and isinstance(local_rec, dict):
            if sub_key and isinstance(remote_rec.get(sub_key), dict) \
                    and isinstance(local_rec.get(sub_key), dict):
                record = dict(local_rec)
                days: Dict[str, Any] = dict(remote_rec[sub_key])
                for day, value in local_rec[sub_key].items():
                    days[day] = deep_merge(days[day], value) if day in days else value
                record[sub_key] = days
                combined[name] = _fill_missing(record, remote_rec)   # 本次优先，远端补标量
            else:
                combined[name] = deep_merge(remote_rec, local_rec)
        else:
            combined[name] = deep_merge(remote_rec, local_rec)

    merged[map_key] = combined
    return merged


def merge_docs(relpath: str, remote: Any, local: Any) -> Any:
    """按路径规则合并两份已解析的文档。规则不认识时退回「本次优先、远端补空」。"""
    policy = policy_for(relpath)
    if policy == POLICY_JOURNAL and isinstance(remote, dict) and isinstance(local, dict):
        return merge_journal(relpath, remote, local)
    if policy == POLICY_LEDGER and isinstance(remote, dict) and isinstance(local, dict):
        return merge_ledger(relpath, remote, local)
    if policy == POLICY_DEEP:
        return deep_merge(remote, local)
    return local


# ============================================================
# 文本层：保持与各写入方一致的输出格式（避免整文件无意义 diff）
# ============================================================
def _detect_style(text: str) -> Dict[str, Any]:
    """从本次文件内容反推缩进与键排序，尽量与原写入方保持一致。"""
    match = re.search(r"\n( +)\S", text)
    indent: Optional[int] = len(match.group(1)) if match else None
    if indent is not None and indent not in (1, 2, 4):
        indent = 1
    sort_keys = False
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict) and len(data) > 1:
        keys = list(data.keys())
        sort_keys = keys == sorted(keys) and indent is None
    return {"indent": indent, "sort_keys": sort_keys}


def style_for(relpath: str, local_text: str) -> Dict[str, Any]:
    """输出格式：已知文件用固定表（与各写入方逐字一致），未知 JSON 现场反推。"""
    style = dict(STYLE_RULES.get(_norm(relpath)) or _detect_style(local_text))
    style["trailing_newline"] = local_text.endswith("\n")
    return style


def dumps_styled(data: Any, style: Dict[str, Any]) -> str:
    text = json.dumps(data, ensure_ascii=False,
                      indent=style.get("indent"), sort_keys=bool(style.get("sort_keys")))
    if style.get("trailing_newline"):
        text += "\n"
    return text


def merge_texts(relpath: str, remote_text: str, local_text: str) -> str:
    """合并两份文件内容（字符串进、字符串出）；任一侧解析失败就以本次为准。"""
    if policy_for(relpath) == POLICY_LOCAL:
        return local_text
    try:
        remote = json.loads(remote_text)
    except (ValueError, TypeError) as exc:
        print(f"⚠️ 远端 {relpath} 不是合法 JSON（{exc}）→ 以本次为准", file=sys.stderr)
        return local_text
    try:
        local = json.loads(local_text)
    except (ValueError, TypeError) as exc:
        print(f"⚠️ 本次 {relpath} 不是合法 JSON（{exc}）→ 保留远端版本", file=sys.stderr)
        return remote_text
    merged = merge_docs(relpath, remote, local)
    return dumps_styled(merged, style_for(relpath, local_text))


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _write(path: str, text: str) -> None:
    """原子写入（与 output/pipeline.py::_atomic_write 同一思路，避免半个文件）。"""
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
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


def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 2
    command = argv[0]

    if command == "policy":
        if len(argv) != 2:
            print("用法: merge_generated.py policy <仓库相对路径>", file=sys.stderr)
            return 2
        print(policy_for(argv[1]))
        return 0

    if command == "merge":
        args = argv[1:]
        out_path = None
        if "-o" in args:
            index = args.index("-o")
            try:
                out_path = args[index + 1]
            except IndexError:
                print("-o 后面缺少输出路径", file=sys.stderr)
                return 2
            args = args[:index] + args[index + 2:]
        if len(args) != 3:
            print("用法: merge_generated.py merge <仓库相对路径> <远端文件> <本次文件> [-o 输出]",
                  file=sys.stderr)
            return 2
        relpath, remote_path, local_path = args
        try:
            merged_text = merge_texts(relpath, _read(remote_path), _read(local_path))
        except OSError as exc:
            print(f"❌ 读取失败：{exc}", file=sys.stderr)
            return 1
        if out_path in (None, "-"):
            sys.stdout.write(merged_text)
            return 0
        try:
            _write(out_path, merged_text)
        except OSError as exc:
            print(f"❌ 写入失败：{exc}", file=sys.stderr)
            return 1
        policy = policy_for(relpath)
        print(f"  🧬 {relpath}：按 {policy} 合并远端与本次生成物"
              + ("（自校验文件，整份取本次）" if policy == POLICY_LOCAL else ""))
        return 0

    print(f"未知子命令：{command}（支持 policy / merge）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
