#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日报大纲与跨栏重复率核对工具（离线，只读 HTML 产物）。

用途
----
把 `output/latest.html`（或任一 `daily_report_*.html`）拆成
「栏目（SECTION）→ 子栏 / 行」两层大纲，并逐栏核对内容重复率：

1. **数字事实口径**：价格、百分比、成交额、概率等可核对数据点；
   同一数字在多个栏目重复出现 = 内容重复；
2. **文字口径**：行 / 子栏正文（去 HTML、去标点）的相似度（复用 `output/dedup.py`）；
3. **跨栏口径**：同一行（同子栏）在哪些栏目重复、每栏的跨栏重复数字率。

输出
----
- 控制台：每栏重复率排行 + ≥阈值的跨栏重复行（同子栏）清单；
- `--md PATH`：写一份 Markdown 大纲（栏目 → 子栏 → 事实数 / 跨栏重复率 / 重复子栏对）；
- `--json PATH`：写完整统计，便于二次核对。

只用标准库 + 仓库内 `output/dedup.py` 的相似度实现，不联网、不改产物。
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("dedup_under_test", ROOT / "output" / "dedup.py")
dedup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dedup)

# ---------------------------------------------------------------- 解析

SECTION_RE = re.compile(r'SECTION\s+(\d{2})\s+·\s+([A-Z0-9 ]+)')
TITLE_RE = re.compile(r'<h2[^>]*>(.*?)</h2>', re.S)
SUB_RE = re.compile(r'<div style="[^"]*font-weight:700[^"]*">([^<]{1,60})</div>')
ROW_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
CELL_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.S)

# 数字事实：百分比 / 千分位 / 小数 / 3 位以上整数（含 亿 / 万 / 倍 单位）
NUM_RE = re.compile(
    r'(?<![\w.])'
    r'((?:\d{1,3}(?:,\d{3})+(?:\.\d+)?)|(?:\d+\.\d+)|(?:\d{3,})|(?:\d{1,2}))'
    r'(\s*%|\s*亿|\s*万|\s*倍)?'
)
DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')
# 口径性 / 结构性数字，跨栏重复不算内容重复（阈值、分母、样本上限等）
GENERIC = {"100", "10", "50", "20", "60", "30", "5", "3", "2", "1", "0", "24", "72", "12",
           "26", "9", "18", "8", "7", "6", "4", "15", "40", "80", "95", "30%", "50%", "5%",
           "1%", "2%", "3%", "4%", "5%", "6%", "7%", "8%", "9%", "10%", "20%", "60%", "70%",
           "80%", "90%", "0%", "100%"}


def strip_tags(fragment: str) -> str:
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', fragment, flags=re.S)
    text = re.sub(r'<br\s*/?>', ' / ', text)
    text = re.sub(r'</(tr|table|div|h2|p)>', '\n', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'[ \t\u00a0]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    return text.strip()


def content_of(fragment: str) -> str:
    return re.sub(r'\s+', ' ', strip_tags(fragment)).strip()


def facts_of(text: str, strict: bool = True) -> set:
    """数字事实集合：去掉日期与年份，保留可核对的数据点（含单位）。

    strict=True（默认）只收「可核对」的事实：带千分位 / 小数 / 单位（% 亿 万 倍）或
    ≥3 位整数；纯样本数、评委数这种小整数不进集合，避免把「8」「10」当成重复。
    """
    clean = DATE_RE.sub(' ', text)
    out = set()
    for num, unit in NUM_RE.findall(clean):
        if re.fullmatch(r'(19|20)\d{2}', num):
            continue
        value = num.replace(',', '')
        if unit:
            value += unit.strip()
        if value in GENERIC or len(value) < 2:
            continue
        if strict and not (unit or "," in num or "." in num or len(value) >= 3):
            continue
        out.add(value)
    return out


def parse_rows(chunk: str):
    """栏目正文 → 行列表：{label, text, facts}；label 取首个单元格（≤24 字）。"""
    rows = []
    for m in ROW_RE.finditer(chunk):
        cells = [content_of(c) for c in CELL_RE.findall(m.group(1))]
        cells = [c for c in cells if c]
        if not cells:
            continue
        label = cells[0] if len(cells) > 1 and len(cells[0]) <= 24 else ""
        text = " ".join(cells)
        rows.append({"label": label, "text": text, "facts": facts_of(text)})
    return rows


def parse_report(path: Path):
    raw = path.read_text(encoding="utf-8")
    marks = [(m.start(), m.group(1), m.group(2).strip()) for m in SECTION_RE.finditer(raw)]
    sections = []
    for i, (pos, num, kicker) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(raw)
        chunk = raw[pos:end]
        title_m = TITLE_RE.search(chunk)
        title = content_of(title_m.group(1)) if title_m else kicker
        subs = []
        subs_m = list(SUB_RE.finditer(chunk))
        for j, m in enumerate(subs_m):
            s_end = subs_m[j + 1].start() if j + 1 < len(subs_m) else len(chunk)
            body = content_of(chunk[m.end():s_end])
            subs.append({"label": content_of(m.group(1)), "text": body, "facts": facts_of(body)})
        rows = parse_rows(chunk)
        body_text = content_of(chunk)
        sections.append({
            "num": num, "kicker": kicker, "title": title,
            "subs": subs, "rows": rows,
            "text": body_text, "facts": facts_of(body_text),
        })
    return sections


# ---------------------------------------------------------------- 重复率

def row_duplicates(sections, threshold=0.7, min_shared=2, min_facts=2):
    """跨栏重复行（同子栏）：共享 ≥min_shared 个数字事实，且文本或标签相似度 ≥ threshold。"""
    items = []
    for s in sections:
        for r in s["rows"]:
            if len(r["facts"]) >= min_facts:
                items.append((s["num"], s["title"], r))
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            an, at, a = items[i]
            bn, bt, b = items[j]
            if an == bn:
                continue
            shared = a["facts"] & b["facts"]
            if len(shared) < min_shared:
                continue
            overlap = len(shared) / max(1, min(len(a["facts"]), len(b["facts"])))
            sim = dedup.combined_similarity(a["text"], b["text"])
            label_sim = (dedup.combined_similarity(a["label"], b["label"])
                         if a["label"] and b["label"] else 0.0)
            if max(sim, label_sim, overlap) < threshold:
                continue
            pairs.append({
                "a": f'{an} {at}', "a_label": a["label"] or a["text"][:30],
                "b": f'{bn} {bt}', "b_label": b["label"] or b["text"][:30],
                "sim": round(sim, 2), "label_sim": round(label_sim, 2),
                "overlap": round(overlap, 2), "shared": sorted(shared),
            })
    pairs.sort(key=lambda p: (-len(p["shared"]), -p["sim"]))
    return pairs


def sub_duplicates(sections, min_shared=3, threshold=0.5):
    """跨栏重复子栏：共享 ≥min_shared 个事实且事实重叠率 ≥ threshold。"""
    items = [(s["num"], s["title"], sub) for s in sections for sub in s["subs"]]
    out = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            an, at, a = items[i]
            bn, bt, b = items[j]
            if an == bn or not a["facts"] or not b["facts"]:
                continue
            shared = a["facts"] & b["facts"]
            overlap = len(shared) / max(1, min(len(a["facts"]), len(b["facts"])))
            if len(shared) >= min_shared and overlap >= threshold:
                sim = dedup.combined_similarity(a["text"], b["text"])
                out.append({"a": f'{an} {at} · {a["label"]}',
                            "b": f'{bn} {bt} · {b["label"]}',
                            "sim": round(sim, 2), "overlap": round(overlap, 2),
                            "shared": sorted(shared)})
    out.sort(key=lambda p: (-len(p["shared"]), -p["overlap"]))
    return out


def section_pairs(sections, min_rate=0.15, min_shared=2):
    """栏目两两对照：A 栏数字事实里有多少在 B 栏也出现（同一批数据的重复展示）。"""
    out = []
    for a in sections:
        for b in sections:
            if a["num"] == b["num"] or not a["facts"]:
                continue
            shared = a["facts"] & b["facts"]
            rate = len(shared) / len(a["facts"])
            if len(shared) >= min_shared and rate >= min_rate:
                out.append({"a": f'{a["num"]} {a["title"]}', "b": f'{b["num"]} {b["title"]}',
                            "shared": len(shared), "rate": round(rate, 2),
                            "examples": sorted(shared)[:8]})
    out.sort(key=lambda p: (-p["rate"], -p["shared"]))
    return out


def section_redundancy(sections):
    """每栏跨栏重复数字率：本栏数字事实里有多少在别的栏目也出现。"""
    fact_home = defaultdict(set)
    for s in sections:
        for f in s["facts"]:
            fact_home[f].add(s["num"])
    rows = []
    for s in sections:
        total = len(s["facts"])
        shared = sum(1 for f in s["facts"] if len(fact_home[f]) > 1)
        rows.append({
            "num": s["num"], "kicker": s["kicker"], "title": s["title"],
            "subs": len(s["subs"]), "rows": len(s["rows"]),
            "facts": total, "shared": shared,
            "rate": round(shared / total, 2) if total else 0.0,
            "examples": sorted((f for f in s["facts"] if len(fact_home[f]) > 1))[:10],
        })
    rows.sort(key=lambda r: -r["rate"])
    return rows, fact_home


TITLE_INNER_RE = re.compile(r"【([^】]{6,80})】")
LONG_SENT_RE = re.compile(r"[\u4e00-\u9fff][\u4e00-\u9fff，。、：；！？0-9A-Za-z%（）\-—·「」《》\s]{11,}")


def inner_duplicates(sections, min_sent=14):
    """栏内重复（同一栏目里重复出现的标题 / 长句）。

    跨栏重复由本文件上面的口径管；这里补栏内：一条快讯被多只个股引用（标题重复）、
    或同一句点缀话在栏内被贴两次。返回 [(栏目, 文案指纹, 次数)]，按次数降序。
    """
    skip = re.compile(r"^(发布于|更新于|来源|数据来源|\d{4})")
    found = []
    for s in sections:
        counts = defaultdict(int)
        for r in s["rows"]:
            for t in TITLE_INNER_RE.findall(r["text"]):
                counts[f"【{t}】"] += 1
            # 标题本身已在上一行计入 → 长句扫描前把标题挖掉，避免同一处重复被数两遍
            rest = TITLE_INNER_RE.sub(" ", r["text"])
            row_hits = set()
            for chunk in re.split(r"[。；！？]", rest):
                key = re.sub(r"\s+", "", chunk).strip("，、：·—-")
                cjk = len(re.findall(r"[\u4e00-\u9fff]", key))
                if len(key) >= min_sent and cjk >= 8 and not skip.match(key):
                    row_hits.add(key[:40])
            # 再按「长句窗口」扫一遍：一句话被 / 或 —— 打断时也能认出（例如共用同一篮子）
            for sent in LONG_SENT_RE.findall(rest):
                key = re.sub(r"\s+", "", sent).strip("，、：·—-")
                cjk = len(re.findall(r"[\u4e00-\u9fff]", key))
                if len(key) >= min_sent and cjk >= 8 and not skip.match(key):
                    row_hits.add(key[:40])
            for key in row_hits:
                counts[key] += 1
        for key, n in counts.items():
            if n >= 2:
                found.append((f'{s["num"]} {s["title"]}', key, n))
    found.sort(key=lambda x: -x[2])
    return found


def render_md(sections, rows, spairs2, rpairs, spairs, fact_home, src_name, threshold, inner=()):
    out = [f"# 日报大纲 · 栏目 / 子栏与跨栏重复率核对\n",
           "| 核对项 | 内容说明 |",
           "|---|---|",
           f"| 核对对象 | `{src_name}`（{len(sections)} 栏 / "
           f"{sum(len(s['subs']) for s in sections)} 个子栏 / "
           f"{sum(len(s['rows']) for s in sections)} 行） |",
           f"| 重复判定口径 | 共享 ≥2 个数字事实且相似度 ≥ {threshold:.0%} |\n",
           "## 一、各栏目跨栏重复数字率\n",
           "| 栏目 | 行数 | 数字事实 | 跨栏重复 | 重复率 | 重复示例 |",
           "|---|---:|---:|---:|---:|---|"]
    for r in rows:
        out.append(f"| {r['num']} {r['title']} | {r['rows']} | {r['facts']} | {r['shared']} | "
                   f"{r['rate']*100:.0f}% | {'、'.join(r['examples'][:6]) or '—'} |")
    out.append("")
    out.append("## 二、栏目两两对照（A 栏事实中出现在 B 栏的比例 ≥15%）\n")
    if not spairs2:
        out.append("| 栏目 A | 栏目 B | 共有事实 | 占 A 栏比例 | 共有事实示例 |")
        out.append("|---|---|---:|---:|---|")
        out.append("| — | — | 0 | 0% | 未发现达到该口径的栏目对 |")
        out.append("| 判定阈值 | A 栏事实在 B 栏占比 ≥15% | 0 | 0% | — |\n")
    else:
        out.append("| 栏目 A | 栏目 B | 共有事实 | 占 A 栏比例 | 共有事实示例 |")
        out.append("|---|---|---:|---:|---|")
        for p in spairs2[:40]:
            out.append(f"| {p['a']} | {p['b']} | {p['shared']} | {p['rate']*100:.0f}% "
                       f"| {'、'.join(p['examples'][:6])} |")
        out.append("")
    out.append("## 三、重复子栏（跨栏，事实重叠 ≥50% 且共享 ≥3 个事实）\n")
    if not spairs:
        out.append("| 子栏 A | 子栏 B | 事实重叠率 | 文本相似度 | 共有事实 |")
        out.append("|---|---|---:|---:|---|")
        out.append("| — | — | 0% | 0.00 | 未发现达到该口径的重复子栏 |")
        out.append("| 判定阈值 | 事实重叠 ≥50% 且共享 ≥3 个事实 | — | — | — |\n")
    else:
        out.append("| 子栏 A | 子栏 B | 事实重叠率 | 文本相似度 | 共有事实 |")
        out.append("|---|---|---:|---:|---|")
        for p in spairs:
            out.append(f"| {p['a']} | {p['b']} | {p['overlap']*100:.0f}% | {p['sim']:.2f} "
                       f"| {'、'.join(p['shared'][:6])} |")
        out.append("")
    out.append("## 四、重复行（跨栏，同子栏逐行对照）\n")
    agg = defaultdict(list)
    for p in rpairs:
        agg[(p["a"], p["b"])].append(p)
    out.append("| 栏目对 | 重复行数 | 行标签对照 | 共有事实与相似度 |")
    out.append("|---|---:|---|---|")
    if not agg:
        out.append("| — | 0 | — | 未发现达到该口径的重复行 |")
        out.append(f"| 判定阈值 | 0 | 共享 ≥2 个数字事实 | 相似度 ≥ {threshold:.0%} |")
    for (a, b), group in sorted(agg.items(), key=lambda kv: -len(kv[1]))[:20]:
        for idx_p, p in enumerate(group[:4]):
            pair_col = f"**{a}** ⇄ **{b}**" if idx_p == 0 else "↳ 同上栏目对"
            cnt_col = str(len(group)) if idx_p == 0 else "—"
            lbl_col = f"{p['a_label']} ｜ {p['b_label']}".replace("|", "丨")
            sim_col = f"共有 {'、'.join(p['shared'][:5])}（文本 {p['sim']:.2f} / 标签 {p['label_sim']:.2f}）".replace("|", "丨")
            out.append(f"| {pair_col} | {cnt_col} | {lbl_col} | {sim_col} |")
    out.append("")
    out.append("## 五、栏内重复（同一栏目里重复出现的标题 / 长句）\n")
    if not inner:
        out.append("| 栏目 | 重复文案 | 次数 |")
        out.append("|---|---|---:|")
        out.append("| — | 未发现栏内重复（同一栏目内没有同一篇标题或同一句长句出现两次） | 0 |")
        out.append("| 判定阈值 | 同一栏目内长句或标题出现 ≥2 次 | 2 |\n")
    else:
        out.append("| 栏目 | 重复文案 | 次数 |")
        out.append("|---|---|---:|")
        for num_title, key, n in inner[:40]:
            safe = key.replace("|", "丨")
            out.append(f"| {num_title} | {safe} | {n} |")
        out.append("")
    out.append("## 六、大纲（栏目 → 子栏）\n")
    out.append("| 栏目序号与名称 | Kicker / 行数 / 事实数 | 子栏名称 | 子栏数字事实与跨栏重复 |")
    out.append("|---|---|---|---|")
    for s in sections:
        sec_label = f"**{s['num']} · {s['title']}**".replace("|", "丨")
        sec_meta = f"`{s['kicker']}` · 行 {len(s['rows'])} · 数字事实 {len(s['facts'])}"
        if not s["subs"]:
            out.append(f"| {sec_label} | {sec_meta} | （正文直出） | 数字事实 {len(s['facts'])} 个 |")
        else:
            for idx_sub, sub in enumerate(s["subs"]):
                cross = sorted(f for f in sub["facts"] if len(fact_home[f]) > 1)
                mark = ""
                if sub["facts"] and len(cross) / len(sub["facts"]) >= 0.5:
                    mark = f" · ⚠ 跨栏重复 {len(cross)}/{len(sub['facts'])}"
                c0 = sec_label if idx_sub == 0 else "↳ 同上栏目"
                c1 = sec_meta if idx_sub == 0 else "—"
                c2 = sub["label"].replace("|", "丨")
                c3 = f"数字事实 {len(sub['facts'])} 个{mark}"
                out.append(f"| {c0} | {c1} | {c2} | {c3} |")
    out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="日报大纲与跨栏重复率核对")
    ap.add_argument("html", nargs="?", default=str(ROOT / "output" / "latest.html"))
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--min-shared", type=int, default=2)
    ap.add_argument("--md", help="把大纲 Markdown 写到指定路径")
    ap.add_argument("--json", help="把统计结果写到指定路径")
    args = ap.parse_args(argv)

    path = Path(args.html)
    sections = parse_report(path)
    rows, fact_home = section_redundancy(sections)
    inner = inner_duplicates(sections)
    rpairs = row_duplicates(sections, args.threshold, args.min_shared)
    spairs = sub_duplicates(sections)
    sec_pairs = section_pairs(sections)

    print(f"📄 {path.name}：{len(sections)} 栏 / "
          f"{sum(len(s['subs']) for s in sections)} 个子栏 / "
          f"{sum(len(s['rows']) for s in sections)} 行")
    print("\n各栏目跨栏重复数字率：")
    for r in rows:
        bar = "█" * int(round(r["rate"] * 20))
        print(f"  {r['num']} {r['title'][:26]:<26} {r['shared']:>3}/{r['facts']:<4} "
              f"{r['rate']*100:>5.1f}% {bar}")
    print(f"\n跨栏重复子栏（≥50% 事实重叠、≥3 个共有事实）：{len(spairs)}")
    for p in spairs[:30]:
        print(f"  {p['overlap']*100:.0f}% 事实 / 文本 {p['sim']:.2f}  "
              f"{p['a']}  ⇄  {p['b']}")
    print(f"\n跨栏重复行（同子栏，相似度 ≥{args.threshold:.0%}）：{len(rpairs)}")
    for p in rpairs[:25]:
        print(f"  {len(p['shared'])} 事实  {p['a']} · {p['a_label'][:18]}  ⇄  "
              f"{p['b']} · {p['b_label'][:18]}  共 {'、'.join(p['shared'][:5])}")
    print(f"\n栏目两两对照（≥15% 事实重复）：{len(sec_pairs)} 对，前 12：")
    for p in sec_pairs[:12]:
        print(f"  {p['rate']*100:>5.1f}%  {p['a']}  ⇒  {p['b']}  共 {p['shared']} 个事实")
    if inner:
        print(f"\n栏内重复（同一栏目里重复的标题 / 长句）{len(inner)} 处，前 6：")
        for num_title, key, n in inner[:6]:
            print(f"  ×{n}  {num_title} :: {key[:60]}")
    else:
        print("\n栏内重复：未发现。")
    if args.md:
        Path(args.md).write_text(
            render_md(sections, rows, sec_pairs, rpairs, spairs, fact_home, path.name,
                      args.threshold, inner),
            encoding="utf-8")
        print(f"\n✅ 大纲写入 {args.md}")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"source": path.name,
             "sections": [{**{k: v for k, v in s.items() if k not in ("rows", "facts", "subs")},
                           "facts": sorted(s["facts"]),
                           "subs": [{**{k: v for k, v in sub.items() if k != "facts"},
                                     "facts": sorted(sub["facts"])} for sub in s["subs"]]}
                          for s in sections],
             "redundancy": rows,
             "sub_pairs": [{**p, "shared": list(p["shared"])} for p in spairs],
             "row_pairs": [{**p, "shared": list(p["shared"])} for p in rpairs],
             "inner_duplicates": [{"section": a, "text": b, "count": c} for a, b, c in inner]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"✅ 统计写入 {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
