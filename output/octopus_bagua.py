#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""☯ 今日八卦运程与利忌 —— 「诗与远方的海」卷首栏的娱乐子块。

口径（诚实披露，写进页面与测试）：
  * **公历梅花变体、章鱼自创**：不用农历、不冒充传统黄历。起卦只用报告日
    公历日期 + 年支 + 星期，公式写死在本文件，同一天永远同一卦。
  * 上卦数 = (年支数 + 月 + 日) % 8；下卦数 = (月 + 日 + 星期数) % 8；
    动爻 = (年支数 + 月 + 日) % 6 + 1（余 0 按 8 / 6 计，梅花先天数序）。
  * 利忌由本卦 / 变卦的卦象、五行生克与动爻**规则推演**，不是随机抽签，
    也不是对任何真实事件的预测；财运等星级只是卦象倾向的娱乐化表达。
  * 与行情结论完全独立：不改变量化概率、不构成投资建议。市场一栏只把
    卦意翻译成「蓄势 / 追高」一类的操作纪律提醒。
  * OCTOPUS_BAGUA=0 可整体关闭；关闭或日期非法时子栏缺席，日报照常。
"""
from __future__ import annotations

import argparse
import html as _html
import os
from datetime import date, datetime

ENABLED = str(os.environ.get("OCTOPUS_BAGUA", "1")).strip().lower() not in ("0", "false", "no")
TITLE = "今日八卦运程与利忌"
DISCLAIMER = "公历梅花变体 · 规则推演 · 娱乐参考 · 非传统黄历 · 不构成投资建议"

# 先天八卦数：乾1 兑2 离3 震4 巽5 坎6 艮7 坤8
TRIGRAMS = {
    1: {"name": "乾", "symbol": "☰", "element": "金", "direction": "西北", "lines": (1, 1, 1),
        "color": "金白 / 银灰", "nature": "天 · 刚健"},
    2: {"name": "兑", "symbol": "☱", "element": "金", "direction": "西", "lines": (1, 1, 0),
        "color": "亮白 / 浅金", "nature": "泽 · 喜悦"},
    3: {"name": "离", "symbol": "☲", "element": "火", "direction": "南", "lines": (1, 0, 1),
        "color": "红 / 橙紫", "nature": "火 · 光明"},
    4: {"name": "震", "symbol": "☳", "element": "木", "direction": "东", "lines": (1, 0, 0),
        "color": "青绿", "nature": "雷 · 启动"},
    5: {"name": "巽", "symbol": "☴", "element": "木", "direction": "东南", "lines": (0, 1, 1),
        "color": "浅绿 / 青", "nature": "风 · 渗透"},
    6: {"name": "坎", "symbol": "☵", "element": "水", "direction": "北", "lines": (0, 1, 0),
        "color": "黑 / 深蓝", "nature": "水 · 险中求通"},
    7: {"name": "艮", "symbol": "☶", "element": "土", "direction": "东北", "lines": (0, 0, 1),
        "color": "黄 / 咖", "nature": "山 · 止定"},
    8: {"name": "坤", "symbol": "☷", "element": "土", "direction": "西南", "lines": (0, 0, 0),
        "color": "米黄 / 大地色", "nature": "地 · 包容"},
}
_BY_NAME = {v["name"]: (k, v) for k, v in TRIGRAMS.items()}

# 六十四卦名（上卦, 下卦）-> 卦名；卦辞大意只给通行关键词，不杜撰原文。
HEXAGRAM_NAMES = {
    ("乾", "乾"): "乾为天", ("乾", "兑"): "天泽履", ("乾", "离"): "天火同人", ("乾", "震"): "天雷无妄",
    ("乾", "巽"): "天风姤", ("乾", "坎"): "天水讼", ("乾", "艮"): "天山遁", ("乾", "坤"): "天地否",
    ("兑", "乾"): "泽天夬", ("兑", "兑"): "兑为泽", ("兑", "离"): "泽火革", ("兑", "震"): "泽雷随",
    ("兑", "巽"): "泽风大过", ("兑", "坎"): "泽水困", ("兑", "艮"): "泽山咸", ("兑", "坤"): "泽地萃",
    ("离", "乾"): "火天大有", ("离", "兑"): "火泽睽", ("离", "离"): "离为火", ("离", "震"): "火雷噬嗑",
    ("离", "巽"): "火风鼎", ("离", "坎"): "火水未济", ("离", "艮"): "火山旅", ("离", "坤"): "火地晋",
    ("震", "乾"): "雷天大壮", ("震", "兑"): "雷泽归妹", ("震", "离"): "雷火丰", ("震", "震"): "震为雷",
    ("震", "巽"): "雷风恒", ("震", "坎"): "雷水解", ("震", "艮"): "雷山小过", ("震", "坤"): "雷地豫",
    ("巽", "乾"): "风天小畜", ("巽", "兑"): "风泽中孚", ("巽", "离"): "风火家人", ("巽", "震"): "风雷益",
    ("巽", "巽"): "巽为风", ("巽", "坎"): "风水涣", ("巽", "艮"): "风山渐", ("巽", "坤"): "风地观",
    ("坎", "乾"): "水天需", ("坎", "兑"): "水泽节", ("坎", "离"): "水火既济", ("坎", "震"): "水雷屯",
    ("坎", "巽"): "水风井", ("坎", "坎"): "坎为水", ("坎", "艮"): "水山蹇", ("坎", "坤"): "水地比",
    ("艮", "乾"): "山天大畜", ("艮", "兑"): "山泽损", ("艮", "离"): "山火贲", ("艮", "震"): "山雷颐",
    ("艮", "巽"): "山风蛊", ("艮", "坎"): "山水蒙", ("艮", "艮"): "艮为山", ("艮", "坤"): "山地剥",
    ("坤", "乾"): "地天泰", ("坤", "兑"): "地泽临", ("坤", "离"): "地火明夷", ("坤", "震"): "地雷复",
    ("坤", "巽"): "地风升", ("坤", "坎"): "地水师", ("坤", "艮"): "地山谦", ("坤", "坤"): "坤为地",
}
# 通行卦意关键词（娱乐解读锚点；未列者按上下卦五行生克生成）
HEXAGRAM_KEYWORDS = {
    "乾为天": ("刚健进取", "大吉"), "地天泰": ("通达顺遂", "大吉"), "山天大畜": ("蓄势储能", "吉"),
    "天雷无妄": ("守正勿妄动", "平"), "风天小畜": ("小有积蓄", "平"), "水天需": ("等待时机", "平"),
    "火天大有": ("收获丰盛", "大吉"), "雷天大壮": ("声势壮盛", "吉"), "山火贲": ("文饰得体", "吉"),
    "火地晋": ("稳步上升", "吉"), "水火既济": ("事已成局", "吉"), "火水未济": ("临门一脚未成", "平"),
    "风雷益": ("增益互利", "吉"), "雷风恒": ("持之以恒", "平"), "风山渐": ("循序渐进", "吉"),
    "地风升": ("拾级而上", "吉"), "天泽履": ("谨慎践行", "平"), "地山谦": ("谦退得福", "吉"),
    "山地剥": ("剥落守成", "谨慎"), "地雷复": ("一阳来复", "吉"), "天地否": ("闭塞不通", "谨慎"),
    "天山遁": ("退守避锋", "平"), "泽水困": ("受困待变", "谨慎"), "水山蹇": ("步履维艰", "谨慎"),
    "坎为水": ("险中求通", "谨慎"), "坤为地": ("厚德载物", "吉"), "离为火": ("附丽光明", "平"),
}

_GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
_CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}
_TIME_WINDOWS = ("05:00–07:00", "07:00–09:00", "09:00–11:00",
                 "13:00–15:00", "15:00–17:00", "19:00–21:00")
_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _num(n: int) -> int:
    return n % 8 or 8


def _relation(a: str, b: str) -> str:
    if a == b:
        return "比和"
    if _GENERATES.get(a) == b:
        return "相生"
    if _GENERATES.get(b) == a:
        return "得生"
    if _CONTROLS.get(a) == b:
        return "相克"
    return "受克"


def _stars(score: int) -> str:
    return "★" * score + "☆" * (5 - score)


def daily_bagua(day: date | None = None) -> dict:
    """按公历梅花变体起卦；同一天结果恒定。日期非法直接抛错，不猜。"""
    if day is None:
        day = date.today()
    if isinstance(day, datetime):
        day = day.date()
    if not isinstance(day, date):
        raise TypeError("day 必须是 datetime.date")

    branch = (day.year - 4) % 12 + 1          # 子=1 … 亥=12；2026 丙午年 -> 7
    weekday_no = day.isoweekday()             # 周一=1 … 周日=7
    upper_no = _num(branch + day.month + day.day)
    lower_no = _num(day.month + day.day + weekday_no)
    moving = (branch + day.month + day.day) % 6 + 1

    upper, lower = TRIGRAMS[upper_no], TRIGRAMS[lower_no]
    lines = list(lower["lines"] + upper["lines"])       # 自下而上六爻
    changed = list(lines)
    changed[moving - 1] = 1 - changed[moving - 1]
    ch_lower = next(v for v in TRIGRAMS.values() if v["lines"] == tuple(changed[:3]))
    ch_upper = next(v for v in TRIGRAMS.values() if v["lines"] == tuple(changed[3:]))
    name = HEXAGRAM_NAMES[(upper["name"], lower["name"])]
    changed_name = HEXAGRAM_NAMES[(ch_upper["name"], ch_lower["name"])]
    keyword, level = HEXAGRAM_KEYWORDS.get(name, (_relation(upper["element"], lower["element"]), "平"))

    rel = _relation(lower["element"], upper["element"])
    base = {"大吉": 5, "吉": 4, "平": 3, "谨慎": 2}.get(level, 3)
    rel_adj = {"相生": 1, "得生": 1, "比和": 0, "相克": -1, "受克": -1}.get(rel, 0)

    def _score(offset: int) -> int:
        return max(1, min(5, base + rel_adj + ((day.day + offset) % 3) - 1))

    fortune = {
        "财运": _score(0), "事业": _score(1), "人际": _score(2), "健康": _score(3),
    }
    # 利忌：由卦意等级 + 变卦方向规则生成（宜取「顺卦意」，忌取「逆卦意」）
    cautious = level == "谨慎"
    favorable = (
        ["整理形象与桌面", "复盘计划、补齐功课", "小步展示成果", "储蓄与积累"]
        if name == "山火贲" else
        ["顺势推进既定计划", "与人合作互利", "整理复盘、补齐功课", "适度展示成果"]
        if not cautious else
        ["守成复盘、低调行事", "预留现金与余地", "求助可信之人", "整理旧事、清理积压"]
    )
    unfavorable = (
        ["过度包装、虚荣消费", "追涨杀跌、冲动下单", "满仓梭哈、听消息动手", "只做门面不做里子"]
        if name == "山火贲" else
        ["冲动决策、逆势硬扛", "借贷冒进、满仓梭哈", "轻信传言、追涨杀跌", "争强好胜、言语过激"]
        if not cautious else
        ["签大额新约、借贷冒进", "逆势硬扛、追涨杀跌", "轻信传言冲动下单", "熬夜透支、争强好胜"]
    )
    market_favorable = (["逢低分批观察", "止盈落袋一部分", "按计划蓄势、不追高"]
                        if not cautious else ["降低仓位预期", "只看不动、多复盘", "严守止损不摊平"])
    return {
        "date": day.isoformat(), "weekday": _WEEKDAYS[day.weekday()],
        "method": "公历梅花变体（年支+月日定上卦，月日+星期定下卦）",
        "upper": dict(upper, no=upper_no), "lower": dict(lower, no=lower_no),
        "hexagram": name, "changed_hexagram": changed_name,
        "lines": lines, "changed_lines": changed, "moving_line": moving,
        "keyword": keyword, "level": level, "relation": rel,
        "changed_lower": ch_lower, "changed_upper": ch_upper,
        "fortune": fortune,
        "lucky_direction": ch_lower["direction"],
        "lucky_color": ch_lower["color"],
        "lucky_numbers": sorted({lower_no, upper_no, moving}),
        "lucky_time": _TIME_WINDOWS[moving - 1],
        "favorable": favorable, "unfavorable": unfavorable,
        "market_favorable": market_favorable,
        "one_liner": f"{name}（{keyword}）{moving}爻动化{changed_name}：宜借势蓄力，忌逆势逞强。",
        "disclaimer": DISCLAIMER,
    }


def _esc(s) -> str:
    return _html.escape(str(s or ""), quote=True)


def render_bagua_html(result: dict | None = None, day: date | None = None) -> str:
    """渲染卷首卦象子块 HTML（纯内联样式，不依赖主题 kit，任何主题可嵌）。

    使用可见的 ☯ 图标标记算卦内容；不靠脚本/折叠控件显示，否则微信清洗 HTML
    后卦象可能被隐藏。只用灰阶：归藏主题除克莱因蓝外不得出现有色值。
    """
    if not ENABLED:
        return ""
    r = result or daily_bagua(day)
    # 加粗、缩小的爻线：用实色块代替字符，阳爻一整条、阴爻两段，细而清晰
    def _bar(yang: bool) -> str:
        if yang:
            return '<div style="display:flex;justify-content:center;margin:2px auto;"><div style="width:44px;height:5px;background:#111111;border-radius:1px;"></div></div>'
        return '<div style="display:flex;justify-content:center;gap:5px;margin:2px auto;"><div style="width:19px;height:5px;background:#111111;border-radius:1px;"></div><div style="width:19px;height:5px;background:#111111;border-radius:1px;"></div></div>'
    lines_html = "".join(_bar(bool(ln)) for ln in reversed(r["lines"]))
    fort = " · ".join(f'{k} {_stars(v)}' for k, v in r["fortune"].items())
    return (
        f'<div style="border:1px dashed #999999;border-radius:8px;padding:10px 12px;margin:8px 0;">'
        f'<div style="font-weight:900;font-size:15px;line-height:1.5;">'
        f'<span role="img" aria-label="算卦" style="display:inline-block;vertical-align:middle;'
        f'border:1px solid #999999;border-radius:6px;padding:0 6px;margin-right:7px;'
        f'font-size:22px;line-height:1.4;color:#555555;">☯</span>'
        f'{TITLE} · {_esc(r["date"])}（{_esc(r["weekday"])}）</div>'
        f'<table style="width:100%;border-collapse:collapse;margin-top:6px;"><tr>'
        f'<td style="width:68px;vertical-align:top;text-align:center;padding-top:2px;">{lines_html}'
        f'<div style="font-size:11px;margin-top:5px;line-height:1.4;color:#222222;">{r["upper"]["symbol"]}上 {r["lower"]["symbol"]}下<br>第{r["moving_line"]}爻动</div></td>'
        f'<td style="vertical-align:top;padding-left:10px;font-size:13px;line-height:1.7;">'
        f'<b>本卦 {_esc(r["hexagram"])}</b>（{_esc(r["keyword"])} · {_esc(r["level"])}）'
        f' → <b>变卦 {_esc(r["changed_hexagram"])}</b><br>{_esc(r["one_liner"])}<br>{_esc(fort)}</td></tr></table>'
        f'<div style="font-size:13px;line-height:1.8;">'
        f'<b>利方</b> {_esc(r["lucky_direction"])} · <b>利色</b> {_esc(r["lucky_color"])} · '
        f'<b>利数</b> {"、".join(map(str, r["lucky_numbers"]))} · <b>吉时</b> {_esc(r["lucky_time"])}<br>'
        f'<b>宜</b> {"、".join(_esc(x) for x in r["favorable"])}<br>'
        f'<b>忌</b> {"、".join(_esc(x) for x in r["unfavorable"])}<br>'
        f'<b>看盘宜</b> {"、".join(_esc(x) for x in r["market_favorable"])}（卦意翻译，非行情结论）</div>'
        f'<div style="font-size:11px;opacity:.75;">{_esc(r["disclaimer"])}｜起卦：{_esc(r["method"])}</div></div>'
    )


def render_bagua_text(result: dict | None = None, day: date | None = None) -> str:
    r = result or daily_bagua(day)
    fort = " · ".join(f'{k} {_stars(v)}' for k, v in r["fortune"].items())
    return "\n".join([
        f'☯ {TITLE} · {r["date"]}（{r["weekday"]}）',
        f'本卦：{r["hexagram"]}（{r["upper"]["symbol"]}{r["upper"]["name"]}上 / '
        f'{r["lower"]["symbol"]}{r["lower"]["name"]}下，{r["keyword"]} · {r["level"]}）',
        f'动爻：第{r["moving_line"]}爻 → 变卦：{r["changed_hexagram"]}',
        f'一句：{r["one_liner"]}',
        f'运程：{fort}',
        f'利方：{r["lucky_direction"]}｜利色：{r["lucky_color"]}｜'
        f'利数：{"、".join(map(str, r["lucky_numbers"]))}｜吉时：{r["lucky_time"]}',
        f'宜：{"、".join(r["favorable"])}',
        f'忌：{"、".join(r["unfavorable"])}',
        f'看盘宜：{"、".join(r["market_favorable"])}',
        DISCLAIMER,
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="今日八卦运程与利忌（公历梅花变体）")
    ap.add_argument("--date", help="YYYY-MM-DD，默认今天")
    ap.add_argument("--html", action="store_true", help="输出 HTML 片段")
    args = ap.parse_args(argv)
    day = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    r = daily_bagua(day)
    print(render_bagua_html(r) if args.html else render_bagua_text(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
