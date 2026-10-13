#!/usr/bin/env python3
"""Render 整理.md as a self-contained, multi-row multi-column HTML table report with inline data bars."""
from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "整理.md"
OUTPUT = ROOT / "整理-表格可视化.html"

SECTION_TONES = {
    1: "blue",
    2: "teal",
    3: "indigo",
    4: "violet",
    5: "amber",
    6: "rose",
    7: "green",
}

INLINE_TOKEN = re.compile(r"(`[^`]+`|\*\*.*?\*\*|\[[^\]]+\]\([^)]+\))")
RATIO = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*$")
PERCENT = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*%\s*$")
NUMBER = re.compile(r"^\s*([+-]?[\d,]+(?:\.\d+)?)\s*([kKmM])?\s*(ms|s|秒)?\s*$")


def split_table_row(line: str) -> list[str]:
    """Split a Markdown pipe-table row, respecting escaped literal pipes."""
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]

    cells: list[str] = []
    cell: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value) and value[i + 1] == "|":
            cell.append("|")
            i += 2
            continue
        if value[i] == "|":
            cells.append("".join(cell).strip())
            cell = []
        else:
            cell.append(value[i])
        i += 1
    cells.append("".join(cell).strip())
    return cells


def is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def parse_alignments(separator_cells: list[str], col_count: int) -> list[str]:
    aligns: list[str] = []
    for cell in separator_cells:
        s = cell.replace(" ", "")
        if s.startswith(":") and s.endswith(":"):
            aligns.append("center")
        elif s.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("left")
    while len(aligns) < col_count:
        aligns.append("left")
    return aligns[:col_count]


def plain_text(markdown: str) -> str:
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", markdown)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    return value.replace(r"\|", "|").strip()


def render_inline(markdown: str) -> str:
    """Render the small inline-Markdown subset used by 整理.md safely."""
    output: list[str] = []
    position = 0
    for match in INLINE_TOKEN.finditer(markdown):
        output.append(html.escape(markdown[position:match.start()], quote=False).replace(r"\|", "|"))
        token = match.group(0)
        if token.startswith("`"):
            code_value = html.escape(token[1:-1], quote=False).replace("\\|", "|")
            output.append(f"<code>{code_value}</code>")
        elif token.startswith("**"):
            output.append(f"<strong>{render_inline(token[2:-2])}</strong>")
        else:
            link = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", token)
            if link:
                label, href = link.groups()
                safe_href = href if href.startswith(("https://", "http://", "./", "../", "#")) else "#"
                output.append(f'<a href="{html.escape(safe_href, quote=True)}">{render_inline(label)}</a>')
        position = match.end()
    output.append(html.escape(markdown[position:], quote=False).replace(r"\|", "|"))
    return "".join(output)


def metric_header(header: str) -> str | None:
    """Return a visualization kind for columns that contain comparable data."""
    label = plain_text(header).lower().replace(" ", "")
    if label == "维度":
        return "share-in-label"
    if any(term in label for term in ("保留", "削幅", "≥±", "出现率", "近10次出现", "稳定出现", "当天源")):
        return "share"
    if label in {"原始值", "显示值"} or "raw" in label or "p95" in label:
        return "relative"
    if "★" in label or "单题延迟" in label or "耗时" in label or "时间" == label:
        return "relative"
    return None


def parse_metric(value: str, kind: str) -> tuple[float, str] | None:
    text = plain_text(value)
    ratio = RATIO.fullmatch(text)
    if ratio and kind == "share":
        numerator, denominator = map(float, ratio.groups())
        return (abs(numerator) / denominator if denominator else 0.0), "share"

    percent = PERCENT.fullmatch(text)
    if percent and kind == "share":
        return abs(float(percent.group(1))) / 100.0, "share"

    if kind == "share-in-label":
        matches = re.findall(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", text)
        if len(matches) == 1:
            return float(matches[0]) / 100.0, "share"

    if kind != "relative":
        return None
    number = NUMBER.fullmatch(text)
    if not number:
        return None
    raw, multiplier, _unit = number.groups()
    amount = float(raw.replace(",", ""))
    if multiplier:
        amount *= 1_000 if multiplier.lower() == "k" else 1_000_000
    return abs(amount), "relative"


def meter_widths(rows: list[list[str]], headers: list[str]) -> dict[tuple[int, int], tuple[float, str]]:
    """Compute in-cell bar widths; source values remain visible verbatim."""
    result: dict[tuple[int, int], tuple[float, str]] = {}
    for column, header in enumerate(headers):
        kind = metric_header(header)
        if not kind:
            continue
        parsed = [(row_index, parse_metric(row[column], kind)) for row_index, row in enumerate(rows)]
        valid = [(index, metric) for index, metric in parsed if metric is not None]
        if len(valid) < 2:
            continue
        modes = {metric[1] for _, metric in valid}
        if modes == {"share"}:
            for row_index, (amount, mode) in valid:
                result[(row_index, column)] = (max(0.0, min(1.0, amount)) * 100.0, mode)
        else:
            maximum = max(amount for _, (amount, _) in valid) or 1.0
            for row_index, (amount, mode) in valid:
                result[(row_index, column)] = (max(0.0, min(1.0, amount / maximum)) * 100.0, mode)
    return result


def render_cell_content(value: str) -> str:
    text = plain_text(value)
    normalized = text.strip()
    badges = {
        "开": "badge-on",
        "关": "badge-off",
        "failed": "badge-fail",
        "P": "badge-pass",
        ".": "badge-missing",
        "—": "badge-neutral",
        "无冲突": "badge-pass",
        "保持开放": "badge-warn",
    }
    if normalized in badges:
        return f'<span class="badge {badges[normalized]}">{render_inline(value)}</span>'
    for symbol, class_name in (("✅", "badge-pass"), ("❌", "badge-fail"), ("⚠️", "badge-warn"), ("⛔", "badge-fail")):
        if normalized.startswith(symbol):
            rest = value[value.find(symbol) + len(symbol):].strip()
            return f'<span class="badge {class_name}">{symbol}</span>{(" " + render_inline(rest)) if rest else ""}'
    return render_inline(value)


def render_meter(cell: str, metric: tuple[float, str]) -> str:
    """Inline mini-bar: keeps the number on the same line (no extra row)."""
    width, mode = metric
    explanation = "按实际比例" if mode == "share" else "按同组最大值归一"
    tooltip = html.escape(f"原值：{plain_text(cell)}；条形{explanation}", quote=True)
    return (f'<span class="meter" title="{tooltip}" aria-hidden="true">'
            f'<span class="meter-fill" style="width:{width:.1f}%"></span></span>')


def render_table(
    rows: list[list[str]],
    tone: str,
    block_number: int,
    aligns: list[str] | None = None,
) -> str:
    """Render a Markdown table as a multi-row, multi-column HTML table."""
    if len(rows) < 2:
        return ""
    headers = rows[0]
    body = rows[1:]
    col_count = len(headers)
    col_aligns = aligns if aligns and len(aligns) == col_count else ["left"] * col_count
    widths = meter_widths(body, headers)

    out = [
        f'<div class="table-wrap">',
        f'<table class="data-table tone-{tone}" id="table-{block_number}" '
        f'aria-label="数据表 {block_number}">',
        "<thead><tr>",
        '<th class="col-index" scope="col">#</th>',
    ]
    for col_idx, h in enumerate(headers):
        align_cls = f" align-{col_aligns[col_idx]}" if col_aligns[col_idx] != "left" else ""
        out.append(f'<th scope="col" class="col-head{align_cls}">{render_inline(h)}</th>')
    out.append("</tr></thead><tbody>")

    for row_index, row in enumerate(body):
        out.append("<tr>")
        out.append(f'<td class="cell-index"><span class="record-no">{row_index + 1:02d}</span></td>')
        for column in range(col_count):
            cell = row[column] if column < len(row) else ""
            align_cls = f" align-{col_aligns[column]}" if col_aligns[column] != "left" else ""
            key_cls = " cell-key" if column == 0 else ""
            metric = widths.get((row_index, column))
            meter_html = render_meter(cell, metric) if metric is not None else ""
            content_html = render_cell_content(cell) if plain_text(cell) else '<span class="cell-empty">—</span>'
            out.append(f'<td class="cell{key_cls}{align_cls}">{content_html}{meter_html}</td>')
        out.append("</tr>")

    out.append("</tbody></table></div>")
    return "".join(out)


# Backward-compatible alias
render_records = render_table


def render_text_as_table(label: str, text_html: str, tone: str, block_number: int) -> str:
    """Render any non-table note or paragraph as a 2-row, 2-column table."""
    return (
        f'<div class="table-wrap">'
        f'<table class="data-table tone-{tone}" id="note-table-{block_number}" aria-label="{html.escape(label)}">'
        f'<thead><tr><th scope="col" class="col-index">类别</th><th scope="col">说明内容</th></tr></thead>'
        f'<tbody><tr><td class="cell-index"><span class="record-no">说明</span></td>'
        f'<td class="cell">{text_html}</td></tr></tbody>'
        f'</table></div>'
    )


def heading_slug(index: int) -> str:
    return f"chapter-{index}"


def build_report(markdown: str) -> tuple[str, int, list[tuple[str, str]], str]:
    lines = markdown.splitlines()
    chapter_titles: list[tuple[str, str]] = []
    seen_h1 = False
    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match and len(match.group(1)) == 1:
            if not seen_h1:
                seen_h1 = True
                continue
            chapter_titles.append((heading_slug(len(chapter_titles) + 1), match.group(2)))

    rendered: list[str] = []
    current_tone = "blue"
    chapter_index = 0
    h1_seen = False
    section_open = False
    subheading_index = 0
    table_count = 0
    note_count = 0
    index = 0

    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2)
            if level == 1 and not h1_seen:
                h1_seen = True
                index += 1
                continue
            if level == 1:
                if section_open:
                    rendered.append("</section>")
                chapter_index += 1
                current_tone = SECTION_TONES.get(chapter_index, "blue")
                subheading_index = 0
                section_open = True
                rendered.append(f'<section class="report-section tone-{current_tone}" id="{heading_slug(chapter_index)}">')
                rendered.append(
                    f'<div class="table-wrap section-head-wrap">'
                    f'<table class="data-table section-head-table tone-{current_tone}" aria-label="章节标题 {chapter_index:02d}">'
                    f'<thead><tr><th scope="col" class="col-index">章节编号</th><th scope="col">章节主题</th></tr></thead>'
                    f'<tbody><tr>'
                    f'<td class="cell-index"><span class="chapter-label">SECTION {chapter_index:02d}</span></td>'
                    f'<td class="cell"><h2 class="chapter-title">{render_inline(title)}</h2></td>'
                    f'</tr></tbody></table></div>'
                )
            else:
                h_level = min(level + 1, 6)
                if level == 2:
                    subheading_index += 1
                    anchor = f"sub-{chapter_index}-{subheading_index}"
                    rendered.append(
                        f'<div class="table-wrap subhead-wrap" id="{anchor}">'
                        f'<table class="data-table subhead-table tone-{current_tone}">'
                        f'<thead><tr><th scope="col" class="col-index">小节</th><th scope="col">子栏标题</th></tr></thead>'
                        f'<tbody><tr>'
                        f'<td class="cell-index"><span class="record-no">{chapter_index}.{subheading_index}</span></td>'
                        f'<td class="cell"><h{h_level} class="subheading">{render_inline(title)}</h{h_level}></td>'
                        f'</tr></tbody></table></div>'
                    )
                else:
                    rendered.append(
                        f'<div class="table-wrap subhead-wrap">'
                        f'<table class="data-table subhead-table tone-{current_tone}">'
                        f'<thead><tr><th scope="col" class="col-index">条目组</th><th scope="col">分组标题</th></tr></thead>'
                        f'<tbody><tr>'
                        f'<td class="cell-index"><span class="record-no">◆</span></td>'
                        f'<td class="cell"><h{h_level} class="minor-heading">{render_inline(title)}</h{h_level}></td>'
                        f'</tr></tbody></table></div>'
                    )
            index += 1
            continue

        if line.startswith("> "):
            note_count += 1
            rendered.append(render_text_as_table("引用说明", render_inline(line[2:].strip()), current_tone, note_count))
            index += 1
            continue

        if line.strip() in {"---", "***", "___"}:
            index += 1
            continue

        if is_table_line(line):
            raw_rows: list[list[str]] = []
            while index < len(lines) and is_table_line(lines[index]):
                raw_rows.append(split_table_row(lines[index]))
                index += 1
            if len(raw_rows) >= 2 and is_separator_row(raw_rows[1]):
                headers = raw_rows[0]
                aligns = parse_alignments(raw_rows[1], len(headers))
                data_rows = raw_rows[2:]
                if any(len(row) != len(headers) for row in data_rows):
                    raise ValueError(f"Table has inconsistent columns near line {index - len(raw_rows) + 1}")
                table_count += 1
                rendered.append(render_table([headers, *data_rows], current_tone, table_count, aligns=aligns))
            else:
                table_count += 1
                col_n = max((len(r) for r in raw_rows), default=2)
                headers = [f"列 {i + 1}" for i in range(col_n)]
                rendered.append(render_table([headers, *raw_rows], current_tone, table_count))
            continue

        paragraph = [line.strip()]
        index += 1
        while (
            index < len(lines)
            and lines[index].strip()
            and not re.match(r"^#{1,6}\s+", lines[index])
            and not is_table_line(lines[index])
            and lines[index].strip() not in {"---", "***", "___"}
        ):
            paragraph.append(lines[index].strip())
            index += 1
        note_count += 1
        rendered.append(render_text_as_table("补充说明", render_inline(" ".join(paragraph)), current_tone, note_count))

    if section_open:
        rendered.append("</section>")

    body = "\n".join(rendered)
    toc_rows = "\n".join(
        f'<tr>'
        f'<td class="cell-index"><span class="record-no">{i:02d}</span></td>'
        f'<td class="cell cell-key"><a class="toc-link tone-{SECTION_TONES.get(i, "blue")}" href="#{slug}">{render_inline(title)}</a></td>'
        f'<td class="cell">#{slug}</td>'
        f'</tr>'
        for i, (slug, title) in enumerate(chapter_titles, start=1)
    )
    toc = (
        '<div class="table-wrap toc-wrap">'
        '<table class="data-table toc-table" aria-label="章节导航表">'
        '<thead><tr><th scope="col" class="col-index">序号</th><th scope="col">章节名称（点击跳转）</th><th scope="col">锚点</th></tr></thead>'
        f'<tbody>{toc_rows}</tbody></table></div>'
    )
    return body, table_count, [(slug, title) for slug, title in chapter_titles], toc


CSS = r"""
:root{color-scheme:light;--ink:#111111;--muted:#68686e;--paper:#ffffff;--card:#f5f5f6;--white:#fff;--line:#e4e4e7;--lime:#c8f03c;--lime-deep:#7a9a00;--shadow:none}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:24px}
body{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;line-height:1.6;-webkit-font-smoothing:antialiased}
.page{max-width:1120px;margin:0 auto;padding:36px 24px 72px}
.hero{position:relative;margin-bottom:18px}
.hero h1{margin:0;font-size:clamp(26px,4vw,40px);font-weight:900;line-height:1.18;letter-spacing:-.03em;color:var(--ink)}
.eyebrow{display:inline-block;color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
.pill{display:inline-block;padding:4px 10px;border-radius:999px;background:var(--card);color:#222;font-size:12px;font-weight:700;margin-right:6px}
.swatch{display:inline-block;width:22px;height:10px;border-radius:3px;background:#e2e2e5;vertical-align:middle;margin-right:6px}
.bar-swatch{display:inline-block;width:44px;height:6px;border-radius:99px;background:linear-gradient(90deg,var(--lime) 64%,#e4e4e7 64%);vertical-align:middle;margin-right:6px}
.toc-link{display:inline-flex;align-items:center;gap:7px;padding:3px 10px;border-radius:999px;color:var(--ink);text-decoration:none;font-size:13px;font-weight:700;background:#f5f5f6;transition:background .15s ease}
.toc-link:hover{background:var(--lime);color:var(--ink)}
.tone-blue,.tone-teal,.tone-indigo,.tone-violet,.tone-amber,.tone-rose,.tone-green{--accent:var(--lime-deep);--accent-dark:var(--ink);--accent-soft:#f0f9c4;--row-a:#fafafa;--row-hover:#f3f7e0;--bar-rgb:200,240,60}
.report-section{margin:0 0 24px;padding:24px;border-radius:24px;background:var(--card);border:0}
.chapter-label{display:inline-flex;align-items:center;gap:6px;color:var(--ink);font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;background:var(--lime);padding:3px 9px;border-radius:999px}
.chapter-title{margin:0;color:var(--ink);font-size:clamp(20px,2.6vw,28px);font-weight:900;line-height:1.25;letter-spacing:-.02em}
.subheading{margin:0;color:var(--ink);font-size:16px;font-weight:800;line-height:1.35}
.minor-heading{margin:0;color:var(--ink);font-size:14px;font-weight:800;line-height:1.35}
.table-wrap{margin:0 0 14px;border-radius:16px;background:#fff;border:1px solid var(--line);overflow-x:auto}
.section-head-wrap{margin-bottom:16px;border:2px solid var(--ink)}
.subhead-wrap{margin:18px 0 8px;background:#fcfcfd}
.data-table{width:100%;border-collapse:collapse;font-size:13.5px;line-height:1.55;color:var(--ink)}
.data-table thead tr{background:#f0f1f4;border-bottom:1px solid var(--line)}
.data-table th{padding:10px 14px;text-align:left;font-size:12px;font-weight:800;color:#333;letter-spacing:.03em;white-space:nowrap}
.data-table td{padding:10px 14px;border-top:1px solid #f0f0f2;vertical-align:top;color:#2c2c30;overflow-wrap:anywhere}
.data-table tbody tr:nth-child(odd){background:#ffffff}
.data-table tbody tr:nth-child(even){background:#fafafb}
.data-table tbody tr:hover{background:#f3f7e0}
.col-index,.cell-index{width:64px;white-space:nowrap;text-align:center!important}
.cell-key{font-weight:700;color:var(--ink)}
.cell-empty{color:#9a9aa0}
.align-right{text-align:right!important;font-variant-numeric:tabular-nums}
.align-center{text-align:center!important}
.record-no{display:inline-block;min-width:24px;padding:1px 7px;border-radius:999px;background:var(--lime);color:var(--ink);font-size:11px;font-weight:900;line-height:18px;text-align:center}
.meter{display:inline-block;width:64px;height:6px;margin-left:8px;border-radius:99px;background:#e4e4e7;vertical-align:middle;overflow:hidden}
.meter-fill{display:block;height:100%;border-radius:99px;background:var(--lime)}
code{padding:.1em .4em;border-radius:6px;background:#f7f7f9;border:1px solid #e4e4e7;color:#111;font-size:.9em;overflow-wrap:anywhere}
.badge{display:inline-flex;align-items:center;justify-content:center;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:800;line-height:1.5;white-space:nowrap;border:0}
.badge-on,.badge-pass{background:var(--lime);color:var(--ink)}
.badge-off,.badge-neutral{background:#e4e4e7;color:#55555a}
.badge-warn{background:#fef08a;color:#111}
.badge-missing{background:#f4f4f5;color:#71717a}
.badge-fail{background:#111;color:#fff}
.footer{margin-top:24px}
@media(max-width:760px){.page{padding:20px 10px 44px}.report-section{padding:14px 10px;border-radius:18px}.data-table th,.data-table td{padding:8px 10px;font-size:12.5px}}
@media print{body{background:#fff}.page{max-width:none;padding:0}.report-section{break-inside:avoid}.record-no,.meter-fill,.bar-swatch{print-color-adjust:exact;-webkit-print-color-adjust:exact}}
"""


def main() -> None:
    markdown = SOURCE.read_text(encoding="utf-8")
    body, table_count, chapters, toc = build_report(markdown)
    page = f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="description" content="章鱼 AI 内容分类整理：多行多列表格排版，数据源、量化、页面推送与问题诊断">
<title>章鱼 AI · 内容分类整理（多行多列表格版）</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">
  <header class="hero">
    <div class="table-wrap">
      <table class="data-table" aria-label="文档刊头信息表">
        <thead>
          <tr>
            <th scope="col" class="col-index">编号</th>
            <th scope="col">刊头字段</th>
            <th scope="col">核心内容</th>
            <th scope="col">规格说明</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="cell-index"><span class="record-no">01</span></td>
            <td class="cell cell-key">文档标题</td>
            <td class="cell"><h1>章鱼 AI · 内容分类整理</h1></td>
            <td class="cell"><span class="eyebrow">OCTOPUS AI · FIELD GUIDE</span></td>
          </tr>
          <tr>
            <td class="cell-index"><span class="record-no">02</span></td>
            <td class="cell cell-key">排版模式</td>
            <td class="cell">全站内容统一采用<strong>多行多列表格</strong>显示（含表头、行号、分栏字段、交错底色与行内数值条）</td>
            <td class="cell"><span class="pill">多行多列 · 结构化对齐</span></td>
          </tr>
          <tr>
            <td class="cell-index"><span class="record-no">03</span></td>
            <td class="cell cell-key">统计概览</td>
            <td class="cell"><span class="pill">{len(chapters)} 个内容分区</span><span class="pill">{table_count} 张多行多列数据表</span></td>
            <td class="cell"><span class="pill">独立 HTML · 离线可读</span></td>
          </tr>
          <tr>
            <td class="cell-index"><span class="record-no">04</span></td>
            <td class="cell cell-key">阅读图例</td>
            <td class="cell"><span class="swatch"></span>表格行底色奇偶交替，悬停高亮；显示数字始终保留原值</td>
            <td class="cell"><span class="bar-swatch"></span>行内迷你条：比例类按实际比例，其他指标按同列最大值归一</td>
          </tr>
        </tbody>
      </table>
    </div>
  </header>
  <nav class="toc" aria-label="章节导航">{toc}</nav>
  <main>
{body}
  </main>
  <footer class="footer">
    <div class="table-wrap">
      <table class="data-table" aria-label="页脚说明表">
        <thead>
          <tr>
            <th scope="col" class="col-index">编号</th>
            <th scope="col">页脚项目</th>
            <th scope="col">详细说明</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="cell-index"><span class="record-no">01</span></td>
            <td class="cell cell-key">生成来源</td>
            <td class="cell">由 <code>整理.md</code> 自动经 <code>tools/render_table_report.py</code> 渲染生成</td>
          </tr>
          <tr>
            <td class="cell-index"><span class="record-no">02</span></td>
            <td class="cell cell-key">运行依赖</td>
            <td class="cell">内嵌样式，无外部字体、脚本或网络依赖；所有内容均以多行多列表格呈现</td>
          </tr>
        </tbody>
      </table>
    </div>
  </footer>
</div>
</body>
</html>
'''
    OUTPUT.write_text(page, encoding="utf-8")
    print(f"Rendered {SOURCE.name} → {OUTPUT.name} ({table_count} multi-column tables)")


if __name__ == "__main__":
    main()
