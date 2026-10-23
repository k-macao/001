#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🦑 AI帮你提鲜 —— 日报每个数据栏目的「先结论、后证据」翻译层（2026-09-29 新增）。

用户是入门兼职投资者，看不懂专业术语。本模块把日报里每个栏目的关键数字
翻译成一句到三句大白话，放在栏目正文开头：先告诉小散户「这栏怎么看」，
再由正文展示数据、证据与详细分析。
（2026-10-06 由「鲜鲜解读」更名：名字直接说人话——AI 帮你把这栏的数字「提鲜」；
标题常量 REN_TITLE 统一出口，改名只改一处。）

设计原则（与整仓「防自欺」文化一致，写进 tests/test_ren.py 兜底）：
  1. 纯确定性规则合成：不调大模型、可复现——同一份输入永远得到同一份解读；
     措辞变体按 `crc32(日期 + 栏目)` 选池，隔天自动换说法，当天重跑不跳变。
  2. 不伪造数字：解读里出现的每一个数字都来自当次渲染用的同一批实参
     （与「⌁ AI 研判」行同源，趋势跟踪等共享统计走同一个 helper，不另算一套）。
  3. 数据缺失 → 返回空串，由渲染层在实际存在的栏目开头给出「证据不足、不硬判」
     的后备结论；绝不硬编数字、方向，也不用旧数据充数。
  4. 不给投资建议：只做「翻译」，方向提示一律紧跟「非投资建议」式的提醒，
     并明确概率 ≈ 抛硬币的诚实口径（模型命中 52% 时就说它是抛硬币水平）。
  5. 环境变量 OCTOPUS_REN=0 整体关闭（默认开启）；单栏出错只丢该行，不影响日报。

ctx 约定（键全部可选，缺了就降级）：
  date_str  报告日 YYYYMMDD（措辞变体的种子）
  notes     build_section_ai_notes 的结果（与页面 ⌁ AI 研判行同源的方向定调）
  market/pan/policy/ai/quant/weekly/hk7/fed/geo/senti/cal/yt/google/em
            与 _collect_report_parts 里渲染正文用的同一批对象
  retail_sentiment / media_risk / sector_rotation / industry_rotation / macd
            散户情绪、媒体风险、板块轮动、行业轮动与 MACD 栏目的同源结构化结果
  uzi       _uzi_result(data) 的结果（【游资剑鱼】多专家流派趋势分析，与正文同一份）
  trend     _trend_section_stats(data) 的结果（趋势跟踪共享统计）
  coverage  {today, total, missing: [...]}（总结栏数据覆盖同源）
"""
from __future__ import annotations

import os
import re
import zlib

# OCTOPUS_REN=0 / false / no 关闭「AI帮你提鲜」；其余值（含未设置）默认开启。
ENABLED = str(os.environ.get("OCTOPUS_REN", "1")).strip().lower() not in ("0", "false", "no")

# 块标题（2026-10-06 由「鲜鲜解读」更名）：渲染层（pipeline._ren_judgment_row）与
# 测试都从这里取，保证改名后页面 / 文档 / 测试三处口径一致。
REN_TITLE = "AI帮你提鲜"
REN_ICON = "🦑"
# 每条解读块下面的小字口径（诚实标注：规则合成 + 非投资建议）。
DISCLAIMER = "规则合成 · 大白话翻译，非投资建议"


# ------------------------------------------------------------------
# 字符图：涨跌几率条（▓ 涨 / ░ 跌，每格 10%）——纯字符、双主题可上色
# ------------------------------------------------------------------
def fresh_meter(p_pct, width=10):
    """多头概率（0~100）→ 几率条字符图：{"filled", "empty", "bar", "odds"}。

    filled/empty：▓ 与 ░ 的格数（渲染层按格数分段上色，两段颜色不同）；
    bar：拼好的纯文本条（▓▓▓▓▓░░░░░，供纯文本场景直接用）；
    odds：几率口径文案「涨 52 ： 48 跌」——只是同一概率的另一种写法，
    不引入任何新数字（防自欺：52 : 48 就是 52% 的重新排版）。
    p_pct 非法（None / 非数）→ 返回 None，渲染层整条几率条缺席。
    """
    try:
        p = float(p_pct)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= p <= 100.0):
        return None
    # 半进位取格（+0.5 再取整）：5% 至少亮 1 格、95% 顶满 10 格，视觉上不失真；
    # 格数始终夹在 [0, width]，绝不出现 11 格或负格。
    filled = max(0, min(width, int(p / 100.0 * width + 0.5)))
    empty = width - filled
    p_int = int(round(p))
    return {
        "filled": filled,
        "empty": empty,
        "bar": "▓" * filled + "░" * empty,
        "odds": f"涨 {p_int} ： {100 - p_int} 跌",
    }


# ------------------------------------------------------------------
# 基础工具：确定性选池 + 数字格式化（None → 缺席，绝不补 0）
# ------------------------------------------------------------------
def _pick(options, seed):
    """按种子稳定挑一条措辞：同一天同一栏目永远同一条，隔天自动换花样。"""
    if not options:
        return ""
    return options[zlib.crc32(str(seed).encode("utf-8")) % len(options)]


def _pct(value, digits=0, sign=False):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return f"{v * 100:+.{digits}f}%" if sign else f"{v * 100:.{digits}f}%"


def _int(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return None


def _f(value, digits=2):
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return None


def _note_label(notes, key):
    """与页面 ⌁ AI 研判行同源的方向定调：偏多 / 中性 / 偏空（缺了给 None）。"""
    note = (notes or {}).get(key) or {}
    label = str(note.get("label") or "")
    return label or None


# 概率口语库：把「52%」这种数字翻译成人能听懂的话（按档位选池）。
def _coin_tone(p_pct, seed):
    """p_pct: 0~100 的上涨概率 → 一句人话点评。"""
    if p_pct is None:
        return ""
    if p_pct >= 65:
        pool = ["模型难得硬气一次，但它历史上也翻过车，别上头",
                "偏多信号比较明显，不过概率不是保证书"]
    elif p_pct >= 55:
        pool = ["略偏涨，但离「稳」还差得远，手别伸太快",
                "多头稍微占上风，别脑补成躺赢"]
    elif p_pct > 45:
        pool = ["基本等于抛硬币，模型自己心里也没底",
                "跟抛硬币差不多，纯看氛围",
                "五五开局面，神仙来了也说不准"]
    elif p_pct > 35:
        pool = ["略偏空，防守优先，先保住本金",
                "空头稍微占上风，别急着抄底"]
    else:
        pool = ["模型在拉响小警报，这种时候少动多看",
                "偏空信号比较明显，别逆势硬冲"]
    return _pick(pool, seed + "|coin")


def _strip_prob(text):
    """去掉标签自带的概率口径（如「· P(7日涨) 62%」），只留方向定调。

    2026-10-23 用户要求【回游金枪鱼】今日预判不显示涨跌概率；周度 entry["label"]
    自带宽口径概率，本栏只翻译方向，概率仍在「每日趋势量化推演」正文。
    """
    text = str(text or "")
    text = re.sub(r"\s*[·,，]?\s*P\(\d*日涨\)\s*\d+(?:\.\d+)?%", "", text)
    text = re.sub(r"\s*\d+(?:\.\d+)?%\s*$", "", text)
    return text.strip()


def _dir_tone(label, seed):
    """方向定调（偏多 / 中性 / 偏空）→ 一句人话点评；不引用概率数字。"""
    text = str(label or "")
    if "偏多" in text or "看多" in text:
        pool = ["多头稍微占上风，但别脑补成躺赢", "方向偏上，手别伸太快",
                "气氛偏暖，先看量能跟不跟"]
    elif "偏空" in text or "看空" in text:
        pool = ["空头稍微占上风，防守优先", "方向偏下，少动多看",
                "气氛偏冷，先保住本金"]
    else:
        pool = ["方向不明，基本等于五五开", "多空拉锯，先看懂再动手",
                "没有稳赚的方向，观察为主"]
    return _pick(pool, seed + "|dir")


_STATIC_TIPS = ["多看少动，攒经验值", "管住手，别急着 all in", "先看懂再动手，不亏就是赚",
                "别浪，机会每天都有", "保持在线，别下牌桌也别重仓压注"]


def _tip(seed):
    return _pick(_STATIC_TIPS, seed + "|tip")


# ------------------------------------------------------------------
# 各栏目生成器：只读 ctx，缺数据返回 ""（渲染层对已存在栏目给诚实后备结论）
# ------------------------------------------------------------------
def _ren_forecast(ctx):
    """【回游金枪鱼】今日预判：只翻译方向定调与信号，**不显示涨跌概率**。

    2026-10-23 按用户要求：这一栏只给「偏多 / 中性 / 偏空」的方向结论与信号分，
    不写上涨概率、周涨概率或「涨 xx ： xx 跌」几率——概率模型仍在
    「每日趋势量化推演 · 港股概率走势分析」里展示，本栏不重复。
    """
    quant = ctx.get("quant") or {}
    weekly = ctx.get("weekly") or {}
    ai = ctx.get("ai") or {}
    seed = f"{ctx.get('date_str') or ''}|FORECAST"
    bits = []
    head = quant.get("headline") or {}
    if head.get("available") and head.get("label"):
        tgt = str(quant.get("target_label") or "下一交易日")
        bits.append(f"模型对{tgt}的方向定调是「{head.get('label')}」"
                    f"（{_dir_tone(str(head.get('label')), seed)}）")
    wk = weekly.get("entry") or {}
    wk_label = _strip_prob(wk.get("label"))
    if wk_label:
        bits.append(f"未来一周整段定调「{wk_label}」")
    if ai.get("available"):
        bits.append(f"综合倾向「{ai.get('sentiment_label') or '中性'}」"
                    f"（信号 {int(ai.get('score') or 0):+d}）")
    if not bits:
        return ""
    text = "；".join(bits) + "。"
    text += f"翻译一下：现在没有稳赚的方向，今天的正确姿势是{_tip(seed)}。"
    return text


def _ren_econ_calendar(ctx):
    """【探照安康鱼】时间节点量化分析：把日程表讲成「开盲盒预告」。"""
    cal = ctx.get("cal") or {}
    if cal.get("status") != "success":
        return ""
    items = [it for it in (cal.get("items") or []) if isinstance(it, dict)]
    if not items:
        return ""
    seed = f"{ctx.get('date_str') or ''}|ECON"
    n3 = sum(1 for it in items if int(it.get("imp") or 0) >= 3)
    by_day = {}
    for it in items:
        by_day[str(it.get("date") or "")] = by_day.get(str(it.get("date") or ""), 0) + 1
    hot_date = sorted(by_day, key=lambda d: (-by_day[d], d))[0] if by_day else ""
    hot_txt = f"{hot_date[5:10]}（{by_day[hot_date]} 件扎堆）" if hot_date else ""
    fed = next((it for it in items if "美联储" in str(it.get("name") or "")
                and "议息" in str(it.get("name") or "")), None)
    window = str(cal.get("window") or "")
    window_days = window.split("·")[-1].replace("未来", "").replace("天", "").strip()
    bits = [f"未来 {window_days or '30'} 天是「开盲盒季」：{len(items)} 个重要时间点，"
            f"{n3} 个是三星大事件"]
    if hot_txt:
        bits.append(f"最挤的一天是 {hot_txt}")
    if fed is not None:
        bits.append(f"重头戏：{str(fed.get('name'))} 排在 {str(fed.get('date'))[5:10]}")
    text = "，".join(bits) + "。"
    text += ("翻译：大数据和大会议前后，市场爱坐过山车——这不是让你去猜方向，"
             "而是提醒你别在这些日子前一把押满。")
    return text


def _ren_hk_probability(ctx):
    """港股概率走势分析：把个股概率榜讲成「种草 / 劝退名单」。"""
    quant = ctx.get("quant") or {}
    if not quant.get("available"):
        return ""
    stocks = [s for s in (quant.get("stocks") or [])
              if isinstance(s, dict) and s.get("probs")]
    if not stocks:
        return ""
    seed = f"{ctx.get('date_str') or ''}|HKPROB"
    scored = []
    for s in stocks:
        p5 = ((s.get("probs") or {}).get(5) or {}).get("p_up")
        if p5 is not None:
            scored.append((str(s.get("label") or ""), float(p5)))
    if not scored:
        return ""
    bull = [(n, p) for n, p in scored if p >= 0.60]
    bear = [(n, p) for n, p in scored if p <= 0.40]
    mid = len(scored) - len(bull) - len(bear)
    top_n, top_p = max(scored, key=lambda x: x[1])
    bot_n, bot_p = min(scored, key=lambda x: x[1])
    bits = [f"{len(scored)} 只港股里：{len(bull)} 只偏多、{len(bear)} 只偏空、"
            f"{mid} 只在中间晃"]
    bits.append(f"模型心头好是{top_n}（5 日 {top_p * 100:.0f}%），"
                f"最不待见{bot_n}（{bot_p * 100:.0f}%）")
    b = quant.get("breadth") or {}
    if b.get("available") and b.get("score") is not None:
        bits.append(f"整池宽度 {_int(b['score'])}/100——大部队基本在趴窝")
    text = "；".join(bits) + "。"
    text += ("翻译：行情不给你白送钱的时候，赚钱靠挑不靠冲；"
             "而且这只是概率排名，不是荐股，明天可能就换一批。")
    return text


def _ren_liquidity(ctx):
    """资金流动性分析：把「南向缩量」讲成「池子水少」。"""
    quant = ctx.get("quant") or {}
    liq = quant.get("liquidity") or {}
    if not (quant.get("available") and liq.get("available")):
        return ""
    seed = f"{ctx.get('date_str') or ''}|FLOW"
    bits = []
    score, label = liq.get("score"), str(liq.get("label") or "")
    if score is not None:
        bits.append(f"流动性综合分 {_f(score, 0)}/100{('（' + label + '）') if label else ''}")
    south = liq.get("south") or {}
    if south.get("available") and south.get("latest") is not None:
        latest = _int(south["latest"])
        pct60 = south.get("pct60")
        low_txt = ""
        if pct60 is not None:
            low_txt = ("，处近 120 日 " + (_pct(pct60) or "") + " 分位"
                       + ("——内地买家明显在歇" if float(pct60) <= 0.2 else ""))
        bits.append(f"南向（内地资金）今天成交 {latest} 亿{low_txt}")
    if not bits:
        return ""
    text = "；".join(bits) + "。"
    if score is not None and float(score) < 40:
        text += "翻译：池子水位偏浅，鱼不活跃，涨了也别急着追。"
    elif score is not None and float(score) >= 60:
        text += "翻译：池子水位还行，但水多也可能水花大，别把热闹当信号。"
    else:
        text += ("翻译：池子水多鱼才活跃，水少的时候涨了也别急着追，"
                 f"今天的姿势是{_tip(seed)}。")
    return text


def _ren_weekly(ctx):
    """每日趋势量化推演：翻译逐日表格、七日结论与并入的港股概率分析。"""
    weekly = ctx.get("weekly") or {}
    entry = weekly.get("entry") or {}
    weekly_available = bool(weekly.get("available") and entry.get("p_up") is not None)
    if not weekly_available:
        return _ren_hk_probability(ctx)
    seed = f"{ctx.get('date_str') or ''}|WEEKLY"
    p = float(entry["p_up"]) * 100
    dir_txt = {"up": "看涨", "down": "看跌"}.get(str(entry.get("direction") or ""), "中性观望")
    n = int(entry.get("target_sessions") or 7)
    p_txt = _pct(entry["p_up"])
    text = (f"未来 {n} 个交易日，模型态度：{dir_txt}，整段累计上涨概率 {p_txt}"
            f"（{_coin_tone(p, seed)}）。")
    # 逐日表格：把最乐观 / 最谨慎的一天点出来，数字全部来自当次 daily rows（同源，不另算）
    rows = [r for r in (weekly.get("daily") or {}).get("rows") or []
            if isinstance(r, dict) and r.get("p_up") is not None]
    if rows:
        ups = sum(1 for r in rows if r.get("direction") == "up")
        downs = sum(1 for r in rows if r.get("direction") == "down")
        best = max(rows, key=lambda r: float(r.get("p_up") or 0))
        worst = min(rows, key=lambda r: float(r.get("p_up") or 0))
        text += (f"逐日看：{ups} 天偏涨 / {downs} 天偏跌，"
                 f"最乐观 T+{int(best.get('k') or 0)}（{_pct(best.get('p_up'))}）、"
                 f"最谨慎 T+{int(worst.get('k') or 0)}（{_pct(worst.get('p_up'))}）。")
    text += ("翻译：逐日表格像导航的分段路况，越往后越不准；仓位和止损都按「留一手」来，"
             "别看见一天看涨就一把梭。")
    hk_text = _ren_hk_probability(ctx)
    if hk_text:
        text += " 港股指数与个股概率补充：" + hk_text
    return text


def _ren_market_review(ctx):
    """【及时秋刀鱼】AI 行情复盘：把涨跌家数 / 成交额讲成「情绪到位、资金没到位」。"""
    pan = ctx.get("pan") or {}
    market = ctx.get("market") or {}
    notes = ctx.get("notes") or {}
    seed = f"{ctx.get('date_str') or ''}|REVIEW"
    bits = []
    b = pan.get("breadth") or {}
    if pan.get("status") == "success" and b:
        up, down = int(b.get("up") or 0), int(b.get("down") or 0)
        if up or down:
            mood = str(b.get("mood") or "")
            bits.append(f"A股 {_int(up)} 家涨 / {_int(down)} 家跌（{mood}）")
    t = pan.get("turnover") or {}
    if t.get("chg_pct") is not None:
        chg = float(t["chg_pct"])
        if chg <= -5:
            bits.append(f"成交额缩了 {abs(chg):.0f}%——看热闹的多、掏钱得少，钱包捂得死死的")
        elif chg >= 5:
            bits.append(f"成交额放了 {chg:.0f}%——真金白银在进场，人有点多")
    if not bits and market.get("status") == "success":
        rows = [(lbl, (q or {}).get("change_pct"))
                for lbl, q in (market.get("quotes") or {}).items()]
        rows = [(l, p) for l, p in rows if p is not None]
        if rows:
            up_n = sum(1 for _, p in rows if p > 0)
            bits.append(f"{len(rows)} 项主要报价：{up_n} 涨 / {len(rows) - up_n} 跌")
    if not bits:
        return ""
    lead = ((pan.get("sectors") or {}).get("leading") or [{}])
    lead = lead[0] if lead else {}
    if lead.get("name") and lead.get("chg_pct") is not None:
        bits.append(f"今天最靓的板块是{lead['name']}（{float(lead['chg_pct']):+.1f}%）")
    label = _note_label(notes, "GLOBAL PANORAMA") or _note_label(notes, "MARKET SNAPSHOT")
    text = "；".join(bits) + "。"
    if label == "偏多":
        text += "翻译：气氛在线，但「涨」不等于「你的票涨」，别看见红盘就上头。"
    elif label == "偏空":
        text += "翻译：气氛一般，防守为主，别逆势逞强。"
    else:
        text += f"翻译：涨跌互现的分歧局，{_tip(seed)}。"
    return text


def _ren_policy(ctx):
    """政策因子：把 PSI 讲成「政策温度计」。"""
    policy = ctx.get("policy") or {}
    if not policy.get("available"):
        return ""
    score = int(policy.get("broad_score") or 0)
    label = str(policy.get("broad_label") or "中性")
    winners = "、".join(str(w.get("name")) for w in (policy.get("winners") or [])[:2])
    losers = "、".join(str(w.get("name")) for w in (policy.get("losers") or [])[:2])
    temp = ("官方最近话风偏谨慎，没有大放水信号" if score < 0 else
            ("政策在吹暖风，明示的顺风方向可以多看两眼" if score > 0 else "不冷不热，维持现状"))
    text = f"政策温度计 PSI {score:+d}（{label}）：{temp}。"
    if winners:
        text += f"被点名的顺风方向（{winners}）相对扛造；"
    if losers:
        text += f"承压方向（{losers}）先观望，别急着抄底。"
    text += "翻译：政策这阵子不是行情发动机，跟车不如系好安全带。"
    return text


def _ren_fed(ctx):
    """【火爆大鱿鱼】美联储因子量化分析：把鹰鸽讲成「紧箍咒」。"""
    fed = ctx.get("fed") or {}
    if not fed.get("available"):
        return ""
    pos, neg, total = int(fed.get("positive_n") or 0), int(fed.get("negative_n") or 0), int(fed.get("total") or 0)
    verdict = str(fed.get("verdict") or "")
    if "鹰" in verdict or "紧缩" in verdict:
        tone = ("借钱的利息下不来，全球股市容易「门可罗雀」，科技成长股最敏感——"
                "它们的故事都靠「未来的钱」撑估值")
    elif "鸽" in verdict or "宽松" in verdict:
        tone = "放水预期升温，市场容易嗨，但嗨完一地瓜子皮的案例也不少"
    else:
        tone = "信号混杂，大家都在等下一次开会揭晓答案"
    return (f"美联储频道：扫了 {total} 条新闻，「紧缩」词命中 {neg} 次 vs「宽松」{pos} 次，"
            f"定调「{verdict}」。翻译：{tone}。这只「紧箍咒」一念，全球资产都得听响。")


def _ren_geo(ctx):
    """【巡回巨鲸】地缘政治因子量化分析：把冲突/缓和讲成「国际大瓜」。"""
    geo = ctx.get("geo") or {}
    if not geo.get("available"):
        return ""
    pos, neg, total = int(geo.get("positive_n") or 0), int(geo.get("negative_n") or 0), int(geo.get("total") or 0)
    verdict = str(geo.get("verdict") or "")
    if "升温" in verdict or "对抗" in verdict:
        tone = ("火药味 > 和气，这种氛围里黄金、原油爱当「避险显眼包」——"
                "但它们跳得快摔得也快，新手别追着热点跑")
    elif "缓和" in verdict:
        tone = "气氛在缓和，市场紧绷的神经能松一扣"
    else:
        tone = "有来有往，属于常规吃瓜量级"
    return (f"地缘吃瓜榜：{total} 条新闻里「升温」词命中 {neg} 次 vs「缓和」{pos} 次，"
            f"定调「{verdict}」。翻译：{tone}。")


def _ren_retail_sentiment(ctx):
    """【麻辣大龙虾】散户情绪：只翻译社区样本，不把网友观点当事实。"""
    result = ctx.get("retail_sentiment") or {}
    if not result.get("available"):
        return ""
    bull = int(result.get("bull") or 0)
    bear = int(result.get("bear") or 0)
    directional_n = int(result.get("directional_n") or 0)
    label = str(result.get("label") or "方向不足")
    nbi = result.get("nbi")
    if directional_n and isinstance(nbi, (int, float)):
        text = (f"社区里可分方向的样本有 {directional_n} 条：看多 {bull} / 看空 {bear}，"
                f"净情绪 NBI {float(nbi):+.1f}（{label}）。")
    else:
        text = "社区这次有热度样本，但可可靠归成看多或看空的内容不足，所以不硬判方向。"
    dispersion = result.get("dispersion")
    if isinstance(dispersion, (int, float)):
        text += f"多空分歧度 {float(dispersion):.1f}/100；"
    text += "小散户把它当「大家在聊什么」就好，社区观点未经公告或权威媒体印证，不是事实和买卖信号。"
    return text


def _ren_media_risk(ctx):
    """【警戒爆炸豚】媒体风险：区分具体风险事件与单纯异常关注。"""
    result = ctx.get("media_risk") or {}
    if not result.get("available"):
        return ""
    stocks = [row for row in (result.get("stocks") or []) if isinstance(row, dict)]
    risk_stock_n = int(result.get("risk_stock_n") or len(stocks))
    event_n = int(result.get("risk_event_n") or 0)
    attention_n = int(result.get("attention_evidence_n") or 0)
    if event_n:
        text = (f"近 {int(result.get('window_hours') or 0)} 小时媒体证据覆盖到 {risk_stock_n} 只 A/H 活跃标的，"
                f"其中有 {event_n} 条具体风险事件证据、{attention_n} 条关注度证据。")
    else:
        text = (f"本栏覆盖 {risk_stock_n} 只 A/H 活跃标的，当前没有检出具体负面事件；"
                f"{attention_n} 条证据只说明关注度变化，不能当成风险事实。")
    top = result.get("top_stock") or {}
    if top:
        level = str((top.get("level") or {}).get("label") or "观察")
        score = top.get("risk_index")
        score_txt = f"，启发式风险分 {int(score)}/100" if isinstance(score, (int, float)) else ""
        qualifier = "异常关注" if top.get("attention_only") else level
        text += f"排在最前的是{top.get('name') or '未命名标的'}（{qualifier}{score_txt}）。"
    text += "风险分用于排序，不是事件发生概率；先核对公告和原文，再决定是否继续观察，非投资建议。"
    return text


def _ren_sector_rotation(ctx):
    """【滚滚翻车鱼】板块轮动：把最高分与覆盖门槛先讲清楚。"""
    result = ctx.get("sector_rotation") or {}
    if not result:
        return ""
    items = [row for row in (result.get("items") or []) if isinstance(row, dict)]
    scored = [row for row in items if isinstance(row.get("overall_score"), (int, float))]
    concepts = int(result.get("concept_total") or 0)
    mapped = int(result.get("mapped_total") or 0)
    if not scored:
        return (f"这次读取 {concepts} 个 A 股概念、命中 {mapped} 个港股观察映射，"
                "但没有概念达到综合评分门槛，所以本栏不硬选强弱。映射是仓库关键词观察篮子，不是官方成分。")
    lead = scored[0]
    score = float(lead["overall_score"])
    vote_summary = lead.get("strategy_summary") or {}
    consensus = str(vote_summary.get("consensus") or "数据不足")
    available_n = int(vote_summary.get("available_n") or 0)
    text = (f"{len(scored)} 个概念达到评分门槛，综合分最前的是「{lead.get('name') or '未命名概念'}」"
            f"（{score:.1f}/100，{lead.get('score_label') or '未分档'}）")
    if available_n:
        text += f"，三套独立策略有 {available_n} 套可用，合议「{consensus}」"
    text += "。分数用于同批候选相对比较，不是上涨概率；A/H 对应关系也不是官方成分，先看正文覆盖与缺项再判断。"
    return text


def _ren_industry_rotation(ctx):
    """【巡游旗鱼】行业轮动：先报行业宽度、榜首与月度观察组合。"""
    result = ctx.get("industry_rotation") or {}
    if not result.get("available"):
        return ""
    breadth = result.get("breadth") or {}
    total = int(breadth.get("total") or result.get("scored_count") or 0)
    up_week = int(breadth.get("up_week") or 0)
    text = f"本次有 {total} 个行业可评分，近 5 个交易日上涨 {up_week} 个"
    avg_week = breadth.get("avg_week")
    if isinstance(avg_week, (int, float)):
        text += f"，全行业等权平均 {float(avg_week) * 100:+.2f}%"
    scores = [row for row in (result.get("scores") or []) if isinstance(row, dict)]
    if scores:
        lead = scores[0]
        text += f"；综合分第一是{lead.get('name') or '未命名行业'}（{float(lead.get('score') or 0):.1f}/100）"
    holdings = ((result.get("state") or {}).get("holdings") or [])
    names = [str(row.get("name") or "") for row in holdings if isinstance(row, dict) and row.get("name")]
    if names:
        text += f"。本月规则观察组合是{'、'.join(names[:5])}"
    text += "。这是月频轮动规则的相对排序，不是个股买入清单；执行日、权重和跟踪表现见正文。"
    return text


def _ren_macd_only(macd):
    """跨市场策略缺席时，用同栏已有 MACD 结果给出不越界的后备结论。"""
    if not (isinstance(macd, dict) and macd.get("available")):
        return ""
    items = [row for row in (macd.get("items") or []) if isinstance(row, dict)]
    if not items:
        return ""
    coverage = macd.get("coverage") or {}
    counts = {key: sum(row.get("action_key") == key for row in items)
              for key in ("entry", "hold", "watch", "exit")}
    return (f"跨市场综合信号不足，本栏只解读已有 MACD 日线：有效 "
            f"{int(coverage.get('valid') or len(items))}/{int(coverage.get('total') or len(items))} 只，"
            f"规则状态为试探 {counts['entry']} / 持有 {counts['hold']} / 观察 {counts['watch']} / 规避 {counts['exit']}。"
            "它只是趋势温度计，不是买卖指令；各标的收盘日期和信号细节见正文。")


def _ren_strategy(ctx):
    """策略研判：优先翻译综合策略；缺席时只总结同栏已有 MACD。"""
    ai = ctx.get("ai") or {}
    if not ai.get("available"):
        return _ren_macd_only(ctx.get("macd") or ai.get("macd"))
    label = str(ai.get("sentiment_label") or "中性")
    score = int(ai.get("score") or 0)
    confidence = str(ai.get("confidence") or "")
    themes = str(ai.get("themes") or "").strip()
    text = (f"策略引擎今天定调「{label}」（信号 {score:+d}，把握{confidence}）"
            + (f"，它盯的方向：{themes}。" if themes else "。"))
    text += ("翻译：这是程序按规则算出来的剧本，不是老师带飞——"
             "「趋势跟踪」的意思是跟着强势方向走，弱势的别恋战。")
    return text


def _ren_uzi_trend(ctx):
    """【游资剑鱼】多专家流派趋势分析：把「一套公开规则逐条打分」讲成面试现场。

    只引用 uzi_trend.run_trend() 结果里已有的数字——过门禁的标的数 / 评委数 / 规则数 /
    票型 / 均分 / 定调分布 / 被门禁撤下的评委 / 缺席标的，一个都不新造；定调用语直接取
    items 自带的 tone 文案（与正文同一套 _verdict 口径，这里不另写一份翻译）。
    数据不足（available=False / 没有 item）→ 返回空串，栏目自动不加解读。
    """
    uzi = ctx.get("uzi") or {}
    if not uzi.get("available"):
        return ""
    items = [row for row in (uzi.get("items") or []) if isinstance(row, dict)]
    if not items:
        return ""
    cov, panel = uzi.get("coverage") or {}, uzi.get("panel") or {}
    seed = f"{ctx.get('date_str') or ''}|UZI TREND"
    valid, total = int(cov.get("valid") or 0), int(cov.get("total") or 0)
    investors = int(panel.get("investors") or 0)
    rules_used, rules_all = int(uzi.get("rules_enabled") or 0), int(uzi.get("rules_total") or 0)
    bull, bear = int(panel.get("bullish") or 0), int(panel.get("bearish") or 0)
    neutral = int(panel.get("neutral") or 0)

    bits = []
    if total:
        # coverage 是「标的级」计数（有没有合格已收盘日线、指标算不算得出来），
        # 与下面「评委级」的准入门禁是两道不同的门，措辞不能混。
        bits.append(f"观察池 {total} 只里 {valid} 只这次算出了结果")
    if investors:
        rule_txt = (f"{investors} 位方法评委按 {rules_used} 条规则投票" if rules_used
                    else f"{investors} 位方法评委投票")
        # 如实交代「为什么只有这几条」：主要是评委范围（默认只放价格类规则能评估的几位上场），
        # 其次才是上场后缺数据的规则整条出局——不能把范围限制说成缺数据。
        roster = int((uzi.get("engine") or {}).get("investors_total") or 0)
        if rules_all and roster > investors:
            rule_txt += (f"（评委库 {roster} 位 / {rules_all} 条规则，本栏只放这几位上场，"
                         f"上场后缺数据的规则整条出局）")
        bits.append(rule_txt)
    if bull or bear or neutral:
        bits.append(f"看多 {bull} / 看空 {bear} / 中性 {neutral}")
    avg = _f(panel.get("avg_score"), 1)
    if avg:
        bits.append(f"均分 {avg}")
    text = ("趋势评审团：" + "，".join(bits) + "。") if bits else "趋势评审团："

    # 定调分布：按固定顺序数 tones，标签用 items 自带的 tone 文案（与正文同源，不另翻译）
    tones = uzi.get("tones") or {}
    tone_bits = []
    for key in ("up", "mixed", "base", "top", "down", "unknown"):
        n = int(tones.get(key) or 0)
        if n <= 0:
            continue
        label = next((str(row.get("tone") or "").strip() for row in items
                      if row.get("tone_key") == key and str(row.get("tone") or "").strip()), "")
        tone_bits.append(f"{label or '阶段未定'} {n} 只")
    if tone_bits:
        text += "定调：" + "、".join(tone_bits) + "。"

    # 最高分那只：均分排序，同分按 items 原顺序取第一只（可复现，不随机）
    scored = [(i, row) for i, row in enumerate(items)
              if isinstance(row.get("score_avg"), (int, float))]
    if scored:
        _, lead = min(scored, key=lambda pair: (-float(pair[1]["score_avg"]), pair[0]))
        lead_avg = _f(lead.get("score_avg"), 1)
        if lead_avg:
            text += (f"最高分：{lead.get('label') or '—'}（均分 {lead_avg}"
                     + (f" · {lead['tone']}" if lead.get("tone") else "") + "）。")

    # 被准入门禁撤下的评委 / 没算出来的标的：如实点名，不粉饰成「中性」
    dropped = uzi.get("dropped") or {}
    if dropped:
        names = [str(name) for name in list(dropped)[:2]]
        text += (f"{len(dropped)} 位评委没过准入门禁被整位撤下（{'、'.join(names)}"
                 f"{'等' if len(dropped) > 2 else ''}）——他们不是弃权，是真的缺数据。")
    missing = [row for row in (uzi.get("missing") or []) if isinstance(row, dict)]
    if missing:
        names = [str(row.get("label") or "").strip() for row in missing[:3]]
        names = [name for name in names if name]
        who = ("、".join(names) + ("等" if len(missing) > len(names) else "")) if names \
            else f"{len(missing)} 只标的"
        text += f"{who}这次没算出来，整只缺席，不拿旧数据顶（逐只原因见正文「暂缺」行）。"

    # 翻译：票型决定说法，但一律不落到买卖建议
    if bear > bull:
        tone = _pick(["翻译：空头票更多，这些方法眼下都在防守，别把「分低」当成抄底信号",
                      "翻译：看空票占上风，评审团的态度是「先看戏」，不是「快上车」"], seed)
    elif bull > bear:
        tone = _pick(["翻译：多头票占上风，但趋势分只是规则打分，不是预言，更别当买入键",
                      "翻译：这几套方法难得投了同一边，热度上来了，手别比脑子快"], seed)
    elif bull or bear:
        tone = _pick(["翻译：多空打平，谁都说服不了谁——这种时候「数据全不全」比「跟谁」更重要",
                      "翻译：五五开的评审团，结论就是没有结论，别硬读出一个方向"], seed)
    else:
        tone = "翻译：全是中性票，等于评审团集体说「看不出来」，看不出来就别装懂"
    return text + tone + "。规则打分不含交易成本，非投资建议。"


def _ren_trend(ctx):
    """趋势跟踪：把海外论坛 / 36 家媒体讲成「吃瓜前线」。"""
    trend = ctx.get("trend") or {}
    if not trend:
        return ""
    seed = f"{ctx.get('date_str') or ''}|TREND"
    platforms = list(trend.get("platforms") or [])
    bits = []
    if platforms:
        bits.append(f"{len(platforms)} 个海外平台（{'、'.join(platforms[:3])}"
                    f"{'等' if len(platforms) > 3 else ''}）扫了 "
                    f"{_int(trend.get('samples') or 0)} 条热帖")
    news_an = trend.get("news_an") or {}
    if news_an.get("scanned"):
        src_total = int(news_an.get("total") or 0)
        src_n = _int(src_total) if src_total > 0 else "20"
        bits.append(f"{src_n} 家媒体源扫了 {_int(news_an.get('scanned'))} 条，"
                    f"港股相关的 {_int(news_an.get('hk_n'))} 条")
    bull, bear = int(trend.get("bull") or 0), int(trend.get("bear") or 0)
    if bull or bear:
        mood = "评论区情绪偏空" if bear > bull else ("评论区情绪偏多" if bull > bear else "多空吵得五五开")
        bits.append(f"多空词 {bull}:{bear}，{mood}")
    if not bits:
        return ""
    themes = "、".join(str(t) for t in (news_an.get("themes") or [])[:2])
    text = "；".join(bits) + "。"
    if themes:
        text += f"热议方向：{themes}。"
    text += ("翻译：热帖和头条都是情绪放大器，不是事实核查，更不是买卖信号；"
             f"把梗当研报，钱包会让你长记性。今天的姿势：{_tip(seed)}。")
    return text


def _ren_mainland_hotlist(ctx):
    """【沸腾花蛤】情绪热点因子量化分析（2026-10-13 新增，2026-10-19 由「内地财经热点榜」更名）：
    把 18 家内地媒体的主题热度、情绪面与预警风险点讲成人话。

    数字全部来自 build_mainland_hotlist() 的同一份结果（不另算一套）：
    谁在说、说多少、多新 + 情绪偏多还是偏空 + 热点聚合到哪些词 + 风险词表点亮了什么。
    2026-10-19 起几率条与「⌁ AI 研判」同源（情绪词典多/空计数合成），仍是词典启发式，
    不是校准概率，也不构成投资建议。
    2026-10-20 起附「今日风险态势」与「预警趋势」：零命中 / 低等级的平时日子也给
    分析结论（与正文态势行 / 趋势行同一份结果、同一句话）。
    """
    res = ctx.get("hotlist") or {}
    themes = list(res.get("themes") or [])
    if not themes:
        return ""
    seed = f"{ctx.get('date_str') or ''}|MAINLAND HOTLIST"
    top = themes[0]
    total = int(res.get("total") or 0)
    share = (top["count"] / total * 100) if total else 0.0
    bits = [f"{_int(res.get('ok_n'))}/{_int(res.get('total_sources'))} 家内地媒体在 72 小时窗口里更新了，"
            f"进榜 {_int(total)} 条"]
    if total:
        bits.append(f"最热的是「{top['label']}」{_int(top['count'])} 条（占 {share:.0f}%，"
                    f"{_int(top.get('media_n'))} 家在说"
                    + (f"，措辞{top['mood']}" if top.get("mood") else "") + "）")
        if len(themes) > 1:
            bits.append("接着是" + "、".join(f"「{t['label']}」{_int(t['count'])} 条"
                                           for t in themes[1:3]))
    agg = res.get("sentiment_agg") or {}
    if agg.get("has_data"):
        avg = agg.get("avg_score")
        bits.append(f"情绪面 偏多 {_int(agg.get('pos_n'))} 条 / 中性 {_int(agg.get('neu_n'))} 条 / "
                    f"偏空 {_int(agg.get('neg_n'))} 条"
                    + (f"，净情绪分 {avg:+.2f}（{agg.get('label')}）"
                       if isinstance(avg, (int, float)) else ""))
    hot = res.get("hotspots") or {}
    terms = [str(c.get("term") or "") for c in (hot.get("clusters") or [])
             if isinstance(c, dict) and c.get("term")]
    if terms:
        bit = "热点聚合到「" + "、".join(terms[:4]) + "」"
        if int(hot.get("aggregated_n") or 0):
            bit += f"，其中 {int(hot.get('aggregated_n'))} 个是跨媒体同题热点（≥2 条在说同一件事）"
        bits.append(bit)
    risk = res.get("risk_report") or {}
    points = [p for p in (risk.get("points") or []) if isinstance(p, dict)]
    if points:
        top_risk = points[0]
        bit = (f"预警风险点 {int(risk.get('points_total') or len(points))} 类，"
               f"最扎眼的是「{top_risk.get('category')}」【{top_risk.get('level')}】"
               f"{_int(top_risk.get('count'))} 条 / {_int(top_risk.get('media_n'))} 家在说")
        kws = [str(k) for k in (top_risk.get("keywords") or []) if k][:3]
        if kws:
            bit += f"，命中词：{'、'.join(kws)}"
        bits.append(bit)
    # 🔭 2026-10-20 新增：今日风险态势 + 预警趋势（「平时也有功能」——零命中 / 低等级
    #    的日子也给分析结论；与正文「⚠ 今日风险态势」「🔭 预警趋势」行同一份结果、
    #    同一句话，不另算一套）。posture 缺失的老结果对象退回旧文案，保持向后兼容。
    posture = res.get("risk_posture") or {}
    trend = res.get("risk_trend") or {}
    if posture.get("verdict"):
        bit = f"今日风险态势：{posture['verdict']}"
        if not points:
            bit += "——未命中 ≠ 没有风险"
        if trend.get("has_history") and trend.get("trend_brief"):
            bit += f"；预警趋势{trend['trend_brief']}"
            if trend.get("low_sample"):
                bit += "（今日存档样本少，提示性看待）"
        bits.append(bit)
    elif not points and int(risk.get("total_titles") or 0):
        bits.append("风险词表本窗口 0 命中（未命中 ≠ 没有风险）")
    newest = str(res.get("newest_cst") or "")
    if newest:
        bit = f"最新一条 {newest[5:]}"
        lag = res.get("lag_hours")
        if isinstance(lag, (int, float)):
            bit += f"，落后现在 {lag:g} 小时"
        bits.append(bit)
    bits.append(f"其中当天 {_int(res.get('today_sources'))} 家、窗口内滞后 "
                f"{_int(res.get('lag_sources'))} 家、暂缺 {len(res.get('missing') or [])} 家")
    text = "；".join(bits) + "。"
    text += ("翻译：主题榜数「谁在说、说了多少」，情绪分和风险等级都是本地词典启发式——"
             "情绪分只看措辞正负，预警等级只看几条几家在说，都不能证明消息真假，也不是涨跌信号；"
             "看到风险词点亮，先点开原文核对再决定信不信。"
             f"今天的姿势：{_tip(seed)}。")
    return text


def _ren_headlines(ctx):
    """全球头条 / 东财快讯：把新闻列表讲成「热搜拼盘」。"""
    kind = ctx.get("_wire_kind") or ""
    src = ctx.get("google") or {} if kind == "google" else ctx.get("em") or {}
    titles = [str((h or {}).get("title") or "") for h in (src.get("headlines") or [])
              if isinstance(h, dict)]
    titles = [t for t in titles if t]
    if not titles:
        return ""
    notes = ctx.get("notes") or {}
    key = "GLOBAL HEADLINES" if kind == "google" else "EASTMONEY WIRE"
    note = notes.get(key) or {}
    text_bits = [f"{len(titles)} 条{'大新闻' if kind == 'google' else '快讯'}"]
    themes = "、".join(str(t) for t in (note.get("themes") or [])[:2])
    if themes:
        text_bits.append(f"主线是{themes}")
    text = "，".join(text_bits) + "。"
    if kind == "google":
        text += ("翻译：新闻只告诉你「发生了什么」，不保证「接下来会涨」——"
                 "看到「重磅利好」先让子弹飞一会儿。")
    else:
        text += ("翻译：基本是公告拼盘（回购、减持、接订单），"
                 "属于公司日常操作，单条别脑补成大行情。")
    return text


def _ren_guru(ctx):
    """港股名家频道：把大V观点讲成「听逻辑、别抄作业」。"""
    yt = ctx.get("yt") or {}
    channels = [ch for ch in (yt.get("channels") or []) if isinstance(ch, dict)]
    if not channels:
        return ""
    active = sum(1 for ch in channels if ch.get("is_today"))
    notes = ctx.get("notes") or {}
    label = _note_label(notes, "HK GURU CHANNELS")
    text = f"今天 {active} 个频道更新了内容"
    if label:
        text += f"，大V观点整体「{label}」"
    text += "。翻译：大V嘴上的涨跌和真实涨跌是两回事——"
    text += "听他们讲逻辑可以，抄作业不行；他们喊单不负责，亏了也没人赔。"
    return text


def _ren_sentiment(ctx):
    """新闻情绪：把 DNS / 最暖最冷讲成「后视镜」。"""
    senti = ctx.get("senti") or {}
    if not (senti.get("available") and senti.get("total_matched")):
        return ""
    ms = senti.get("market_summary") or senti
    dns = ms.get("overall_dns")
    label = str(ms.get("overall_label") or "中性")
    dns_txt = ""
    if dns is not None:
        if label == "中性":
            dns_txt = f"（DNS {_f(dns)}，正负相抵后接近零就是中性）"
        else:
            dns_txt = (f"（DNS {_f(dns)}，"
                       + ("正数=夸的比骂的多）" if dns > 0 else "负数=骂的比夸的多）"))
    bits = [f"近 72 小时新闻情绪整体「{label}」" + dns_txt]
    hot = ms.get("hottest") or {}
    cold = ms.get("coldest") or {}
    covered = ms.get("most_covered") or {}
    if hot.get("name"):
        bits.append(f"被夸得最凶：{hot['name']}")
    if cold.get("name") and cold.get("key") != hot.get("key"):
        bits.append(f"被骂得最惨：{cold['name']}")
    if covered.get("name") and covered.get("total"):
        bits.append(f"上新闻最多：{covered['name']}（{_int(covered['total'])} 条）")
    text = "；".join(bits) + "。"
    text += ("翻译：新闻热度是后视镜——它解释昨天，不预告明天；"
             "热搜上得猛不代表股票会涨，别拿情绪当信号。")
    return text


def _ren_summary(ctx):
    """总结：把数据覆盖讲成「本份日报的配料表」。"""
    cov = ctx.get("coverage") or {}
    if not cov:
        return ""
    today, total = int(cov.get("today") or 0), int(cov.get("total") or 0)
    missing = [str(m) for m in (cov.get("missing") or [])]
    text = f"本次日报的配料表：{total} 路数据里 {today} 路是当天新鲜货"
    if missing:
        text += f"，缺的 {len(missing)} 路（{'、'.join(missing[:3])}{'等' if len(missing) > 3 else ''}）直接点名、不装样子"
    text += "。全篇是真实数据 + 规则计算，没有玄学。"
    text += ("新手三件套送给你：只用闲钱、别一把梭、先看懂再下单——"
             "市场天天开门，本金没了就得退游重练。")
    return text


def _ren_hk7(ctx):
    """AI 七日港股走势分析概率：只在配置了大模型时出现。"""
    hk7 = ctx.get("hk7") or {}
    if not hk7.get("available"):
        return ""
    targets = [t for t in (hk7.get("targets") or []) if isinstance(t, dict)]
    bits = []
    for t in targets:
        label = str(t.get("label") or "")
        p = t.get("p_up")
        if label and p is not None:
            bits.append(f"{label} {_pct(p)}")
    if not bits:
        return ""
    engine = str(hk7.get("engine") or "")
    engine_txt = "大模型研判" if engine == "llm" else "量化基准（大模型没接上）"
    return (f"未来 7 个交易日上涨概率：{'、'.join(bits)}（{engine_txt}）。"
            "翻译：7 天已经算「天气预报里的中长期」了，误差会放大，"
            "看看就好，别按这个排期打款。")


# ------------------------------------------------------------------
# 派发：栏目 kicker → 生成器
# ------------------------------------------------------------------
def _ren_global_headlines(ctx):
    ctx = dict(ctx, _wire_kind="google")
    return _ren_headlines(ctx)


def _ren_eastmoney_wire(ctx):
    ctx = dict(ctx, _wire_kind="em")
    return _ren_headlines(ctx)


_GENERATORS = {
    "FORECAST": _ren_forecast,
    "ECON CALENDAR": _ren_econ_calendar,
    "HK PROBABILITY": _ren_hk_probability,
    "LIQUIDITY FLOW": _ren_liquidity,
    "WEEKLY FORECAST": _ren_weekly,
    "MARKET REVIEW": _ren_market_review,
    "RETAIL SENTIMENT": _ren_retail_sentiment,
    "MEDIA RISK": _ren_media_risk,
    "POLICY SHOCK": _ren_policy,
    "FED TREND": _ren_fed,
    "GEO TREND": _ren_geo,
    "STRATEGY READ": _ren_strategy,
    "UZI TREND": _ren_uzi_trend,
    "TREND TRACKING": _ren_trend,
    "SECTOR ROTATION": _ren_sector_rotation,
    "INDUSTRY ROTATION": _ren_industry_rotation,
    "GLOBAL HEADLINES": _ren_global_headlines,
    "EASTMONEY WIRE": _ren_eastmoney_wire,
    "HK GURU CHANNELS": _ren_guru,
    "NEWS SENTIMENT": _ren_sentiment,
    # 情绪热点因子量化分析（2026-10-13 新增，2026-10-19 由「内地财经热点榜」更名）：
    # 18 家内地媒体的主题热度 + 情绪总览 + 热点聚合 + 预警风险点
    "MAINLAND HOTLIST": _ren_mainland_hotlist,
    "HK 7D PROB": _ren_hk7,
    "SUMMARY": _ren_summary,
}


# ------------------------------------------------------------------
# 🦐 活鲜度点缀（2026-09-30 新增）：把行情状态翻译成海鲜市场比喻
# —— 调用 output/octopus_lexicon.py 活鲜词库；条件驱动、确定性、无数字。
#    数据不足就不点缀（与解读本体同一套防自欺口径）；点缀出错只丢点缀，不拖垮解读。
# ------------------------------------------------------------------
_LEX = None


def _lexicon():
    """惰性导入活鲜词库（output 不在 sys.path 时自动补，保证 ren 可被独立加载）。"""
    global _LEX
    if _LEX is None:
        try:
            import octopus_lexicon as _m
        except ImportError:
            import os as _os
            import sys as _sys
            _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
            import octopus_lexicon as _m
        _LEX = _m
    return _LEX


# 抓取型内容栏目：新鲜度看 is_today（内容有发布 / 收盘日）；其余为「本次现算」的
# 分析栏目：available 即视为当天活鲜（现杀现做），无需 is_today 标记。
_FETCHED_KICKERS = {"MARKET REVIEW", "ECON CALENDAR", "GLOBAL HEADLINES",
                    "EASTMONEY WIRE", "HK GURU CHANNELS", "TREND TRACKING",
                    "MAINLAND HOTLIST"}


def _garnish_obj(kicker, ctx):
    """kicker → ctx 里的主数据对象（与各栏生成器读的是同一批对象，状态一致）。"""
    ctx = ctx or {}
    quant = ctx.get("quant") or {}
    ai = ctx.get("ai") or {}
    strategy_obj = ai if ai.get("available") else (ctx.get("macd") or ai.get("macd"))
    table = {
        "FORECAST": quant,
        "ECON CALENDAR": ctx.get("cal"),
        "HK PROBABILITY": quant,
        "LIQUIDITY FLOW": quant.get("liquidity"),
        "WEEKLY FORECAST": ctx.get("weekly"),
        "MARKET REVIEW": ctx.get("market") or ctx.get("pan"),
        "RETAIL SENTIMENT": ctx.get("retail_sentiment"),
        "MEDIA RISK": ctx.get("media_risk"),
        "POLICY SHOCK": ctx.get("policy"),
        "FED TREND": ctx.get("fed"),
        "GEO TREND": ctx.get("geo"),
        "STRATEGY READ": strategy_obj,
        "UZI TREND": ctx.get("uzi"),
        "TREND TRACKING": ctx.get("trend"),
        "SECTOR ROTATION": ctx.get("sector_rotation"),
        "INDUSTRY ROTATION": ctx.get("industry_rotation"),
        "GLOBAL HEADLINES": ctx.get("google"),
        "EASTMONEY WIRE": ctx.get("em"),
        "HK GURU CHANNELS": ctx.get("yt"),
        "NEWS SENTIMENT": ctx.get("senti"),
        "MAINLAND HOTLIST": ctx.get("hotlist"),
    }
    return table.get(kicker) or {}


def _garnish_available(obj):
    if not obj:
        return False
    if isinstance(obj, dict):
        if "status" in obj:
            return obj.get("status") == "success"
        if "available" in obj:
            return bool(obj.get("available"))
    return bool(obj)        # trend / yt 等：有内容即算「在」


def _garnish_is_today(kicker, obj):
    v = obj.get("is_today") if isinstance(obj, dict) else None
    if isinstance(v, bool):
        return v
    # 无显式当天标记：抓取型内容保守按「非当天」(冰鲜)，分析型按「本次现算」(活鲜)
    return kicker not in _FETCHED_KICKERS


def _garnish_dir(kicker, ctx, obj):
    """方向定调 + 概率：优先用 ⌁AI研判 同源 notes，其次结论型栏目取自身 label。"""
    notes = (ctx or {}).get("notes") or {}
    keys = ("MARKET SNAPSHOT", "GLOBAL PANORAMA") if kicker == "MARKET REVIEW" else (kicker,)
    for key in keys:
        n = notes.get(key)
        if isinstance(n, dict) and n.get("label"):
            return n.get("label"), n.get("bull_pct")
    if kicker == "WEEKLY FORECAST":
        e = (obj or {}).get("entry") or {}
        p = e.get("p_up")
        return e.get("label"), (p * 100 if isinstance(p, (int, float)) else None)
    if kicker in ("FORECAST", "HK PROBABILITY"):
        h = ((ctx or {}).get("quant") or {}).get("headline") or {}
        if h.get("available"):
            p = h.get("p_up")
            return h.get("label"), (p * 100 if isinstance(p, (int, float)) else None)
    return None, None


def _seafood_garnish_parts(kicker, ctx):
    """返回 (点缀串, 本次选中的比喻句)；数据不足时是 ("", "")。

    「同一份日报里同一句比喻只出现一次」（2026-10-12 同子栏合并的栏内口径）：词库短语池
    不大，两个栏目可能抽到同一句（例如两栏都是「活鲜 — 今天的货是活的，现捞现看」）。
    上层（pipeline 逐栏生成时）把已用过的比喻句放进 ctx["_garnish_avoid"]，这里撞句就按
    **确定性顺序**换下一个变体（最多试 8 个）；全试完仍撞句就照用。

    本函数**只读 ctx、不改 ctx**：同输入永远同输出（可复现性靠上层按固定栏目顺序递进）。
    """
    obj = _garnish_obj(kicker, ctx)
    if not _garnish_available(obj):
        return "", ""
    lex = _lexicon()
    label, p_pct = _garnish_dir(kicker, ctx, obj)
    vol_pct = obj.get("vol_pct") if isinstance(obj, dict) else None
    base_seed = f"{(ctx or {}).get('date_str') or ''}|{kicker}|SEAFOOD"
    avoid = set()
    if isinstance(ctx, dict):
        avoid = {str(x) for x in (ctx.get("_garnish_avoid") or ()) if str(x)}
    g = None
    for attempt in range(8):
        seed = base_seed if attempt == 0 else f"{base_seed}|alt{attempt}"
        g = lex.section_garnish(
            available=True, is_today=_garnish_is_today(kicker, obj),
            label=label, p_pct=p_pct, vol_pct=vol_pct, seed=seed)
        metaphor = (g or {}).get("metaphor") or ""
        if not avoid or not metaphor or metaphor not in avoid:
            break
    return lex.seafood_line(g), ((g or {}).get("metaphor") or "")


def _seafood_garnish(kicker, ctx):
    """（兼容旧入口）只返回「｜🦐 活鲜度：X — 比喻」串；数据不足返回 ""（不点缀）。"""
    return _seafood_garnish_parts(kicker, ctx)[0]


def section_ren_with_meta(kicker, ctx):
    """返回 (「AI帮你提鲜」正文, 本次选中的活鲜比喻句)；数据不足 / 出错返回 ("", "")。

    2026-09-30 起：解读末尾按行情状态确定性点缀「🦐 活鲜度」标签 + 一句活鲜比喻
    （octopus_lexicon 词库；条件驱动、无数字、可复现）。数据不足时整行仍缺席。
    比喻句随返回值交给上层做「同一份日报里同一句只出现一次」的去重。
    """
    gen = _GENERATORS.get(kicker)
    if gen is None:
        return "", ""
    try:
        text = str(gen(ctx) or "")
    except Exception as exc:            # 单栏出措不拖垮整份日报
        print(f"  ⚠️ AI帮你提鲜（{kicker}）生成失败，本栏跳过：{exc}")
        return "", ""
    if not text:
        return "", ""
    try:
        garnish, metaphor = _seafood_garnish_parts(kicker, ctx)
    except Exception as exc:            # 点缀出错只丢点缀，解读本体照常
        print(f"  ⚠️ 活鲜点缀（{kicker}）生成失败，跳过点缀：{exc}")
        garnish, metaphor = "", ""
    return (text + garnish if garnish else text), metaphor


def section_ren(kicker, ctx):
    """返回某栏目的「AI帮你提鲜」正文文本；数据不足 / 出错返回 ""（调用方就不加块）。"""
    return section_ren_with_meta(kicker, ctx)[0]


def section_ren_block(kicker, ctx):
    """「AI帮你提鲜」整块数据（2026-10-06 新增）：正文 + 方向 label + 概率 p_pct。

    返回 {"text", "label", "p_pct"}（text 非空才返回，否则 None，调用方就不加块）。
    label / p_pct 与「⌁ AI 研判」行同源（_garnish_dir 同一套取数，不另算一套），
    渲染层只负责把 p_pct 画成几率条字符图，绝不在这里造新数字。
    p_pct 缺失（栏目没有研判概率）→ None：渲染层跳过几率条，只出字符图头 + 正文。
    """
    text, metaphor = section_ren_with_meta(kicker, ctx)
    if not text:
        return None
    try:
        obj = _garnish_obj(kicker, ctx)
        label, p_pct = _garnish_dir(kicker, ctx, obj)
    except Exception as exc:            # 元数据出错只丢几率条，正文照常
        print(f"  ⚠️ AI帮你提鲜（{kicker}）几率条元数据失败，跳过几率条：{exc}")
        label, p_pct = None, None
    if isinstance(p_pct, (int, float)):
        p_pct = round(float(p_pct), 1)
    else:
        p_pct = None
    # 2026-10-23 按用户要求：【回游金枪鱼】今日预判不展示涨跌概率 → 几率条整条缺席
    # （label 仍保留，方向色与 ▲▼■ 定调不变；概率模型不在本栏重复出现）。
    if kicker == "FORECAST":
        p_pct = None
    return {"text": text, "label": label or None, "p_pct": p_pct,
            "metaphor": metaphor or None}
