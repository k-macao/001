#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reddit / StockTwits 社区样本的散户情绪因子计算与渲染。

只读取本次采集结果，不请求网络、不补历史数据、不把缺失项伪装成数值。
报告正文只展示样本数、来源分项、净情绪指数、分歧熵与热度榜，不渲染方法说明。
"""
from __future__ import annotations

import math
import re

SECTION_KICKER = "RETAIL SENTIMENT"
SECTION_TITLE = "【麻辣大龙虾】散户群体情绪量化分析"
SECTION_CAPTION = "Reddit · StockTwits · 非投资建议"

# Reddit 仅提供公开标题；方向计数使用固定词表，单条帖子最多计入一个方向。
# StockTwits 优先使用平台消息自带的 Bullish / Bearish 标签。
_RETAIL_BULL_RE = re.compile(
    r"\b(?:rall(?:y|ies|ied)|surge\w*|soar\w*|pump\w*|moon\w*|bulls?|bullish|"
    r"breakout|rebound\w*|recover\w*|upgrade\w*|record\s+high|all[- ]time\s+high|"
    r"beat\w*|boom\w*|gain\w*|outperform\w*)\b"
    r"|看多|利好|上涨|大涨|暴涨|拉升|反弹|突破|创新高|走强|涨停|牛市",
    re.IGNORECASE,
)
_RETAIL_BEAR_RE = re.compile(
    r"\b(?:crash\w*|dump\w*|tank\w*|plunge\w*|selloff|bear\w*|short\w*|fud|"
    r"scam|bankrupt\w*|layoff\w*|warn\w*|loss\w*|correction|decline\w*|"
    r"tumble\w*|slump\w*|sank|sink|underperform\w*)\b"
    r"|看空|利空|下跌|大跌|暴跌|跳水|回落|走弱|跌停|熊市|崩盘|亏损|做空",
    re.IGNORECASE,
)


def _integer(value, *, minimum=None):
    """Parse an integer-like source value; invalid values remain missing."""
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _source_items(data, name, *, require_symbol=False):
    source = (data or {}).get(name)
    if not isinstance(source, dict) or source.get("status") != "success":
        return source if isinstance(source, dict) else {}, []
    raw_items = source.get("items")
    if not isinstance(raw_items, list):
        return source, []
    items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        if require_symbol:
            if not str(item.get("symbol") or "").strip():
                continue
        elif not str(item.get("title") or "").strip():
            continue
        items.append(item)
    return source, items


def _reddit_class(title):
    bull = len(_RETAIL_BULL_RE.findall(str(title or "")))
    bear = len(_RETAIL_BEAR_RE.findall(str(title or "")))
    if bull > bear:
        return "bull"
    if bear > bull:
        return "bear"
    if bull and bear:
        return "mixed"
    return "unclassified"


def _nbi(bull, bear):
    total = bull + bear
    if total <= 0:
        return None
    return round(100.0 * (bull - bear) / total, 1)


def _nbi_label(value):
    if value is None:
        return "样本不足"
    if value >= 20:
        return "偏多"
    if value <= -20:
        return "偏空"
    return "中性"


def _dispersion_entropy(bull, bear):
    total = bull + bear
    if total <= 0:
        return None
    p = bull / total
    if p in (0.0, 1.0):
        return 0.0
    entropy = -(p * math.log2(p) + (1 - p) * math.log2(1 - p))
    return round(entropy * 100, 1)


def _retail_reddit(source, items):
    counts = {"bull": 0, "bear": 0, "mixed": 0, "unclassified": 0}
    score_sum = comments_sum = 0
    score_n = comments_n = 0
    seen = set()
    for item in items:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        identity = url or (str(item.get("community") or ""), title,
                           str(item.get("published_cst") or ""))
        if identity in seen:
            continue
        seen.add(identity)
        counts[_reddit_class(title)] += 1
        score = _integer(item.get("score"))
        comments = _integer(item.get("comments"), minimum=0)
        if score is not None:
            score_sum += score
            score_n += 1
        if comments is not None:
            comments_sum += comments
            comments_n += 1
    return {
        "available": bool(items),
        "content_date": str(source.get("content_date") or ""),
        "sample_n": sum(counts.values()),
        **counts,
        "score_sum": score_sum if score_n else None,
        "score_n": score_n,
        "comments_sum": comments_sum if comments_n else None,
        "comments_n": comments_n,
        "nbi": _nbi(counts["bull"], counts["bear"]),
    }


def _retail_stocktwits(source, items):
    checked = bull = bear = streams_available = 0
    unique = {}
    labels_seen = set()
    for item in items:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        rank = _integer(item.get("rank"), minimum=1)
        watchers = _integer(item.get("watchlist_count"), minimum=0)
        current = unique.get(symbol)
        entry = {
            "symbol": symbol,
            "title": str(item.get("title") or symbol),
            "rank": rank,
            "watchlist_count": watchers,
            "trending_score": _integer(item.get("trending_score"), minimum=0),
        }
        if current is None:
            unique[symbol] = entry
            current = entry
        else:
            current_rank = current.get("rank")
            if rank is not None and (current_rank is None or rank < current_rank):
                current["rank"] = rank
            if watchers is not None and (current.get("watchlist_count") is None
                                         or watchers > current["watchlist_count"]):
                current["watchlist_count"] = watchers

        sentiment = item.get("sentiment_counts")
        if not isinstance(sentiment, dict):
            continue
        n_checked = _integer(sentiment.get("checked"), minimum=0)
        n_bull = _integer(sentiment.get("bull"), minimum=0)
        n_bear = _integer(sentiment.get("bear"), minimum=0)
        if n_checked is None or n_bull is None or n_bear is None:
            continue
        # 采集端由同一消息数组统计，若异常 payload 出现多计数则整条不纳入。
        if n_bull + n_bear > n_checked:
            continue
        current["sentiment_counts"] = {
            "checked": n_checked, "bull": n_bull, "bear": n_bear,
            "unclassified": n_checked - n_bull - n_bear,
        }
        # 同一标的若重复出现，平台 feed 计数只纳入一次。
        if symbol in labels_seen:
            continue
        labels_seen.add(symbol)
        checked += n_checked
        bull += n_bull
        bear += n_bear
        streams_available += 1

    ranked = sorted(unique.values(), key=lambda row: (
        row["rank"] if row["rank"] is not None else 10**9,
        -(row["watchlist_count"] if row["watchlist_count"] is not None else -1),
        row["symbol"],
    ))
    return {
        "available": bool(ranked),
        "content_date": str(source.get("content_date") or ""),
        "symbol_n": len(ranked),
        "checked": checked,
        "bull": bull,
        "bear": bear,
        "unclassified": max(0, checked - bull - bear),
        "streams_available": streams_available,
        "nbi": _nbi(bull, bear),
        "top_symbols": ranked[:5],
    }


def calculate(data):
    """仅由本次 Reddit / StockTwits 原始结果计算散户情绪数据。"""
    reddit_source, reddit_items = _source_items(data, "Reddit")
    stocktwits_source, stocktwits_items = _source_items(
        data, "StockTwits", require_symbol=True)
    reddit = _retail_reddit(reddit_source, reddit_items)
    stocktwits = _retail_stocktwits(stocktwits_source, stocktwits_items)

    bull = reddit["bull"] + stocktwits["bull"]
    bear = reddit["bear"] + stocktwits["bear"]
    total = bull + bear
    score = _nbi(bull, bear)
    return {
        "available": reddit["available"] or stocktwits["available"],
        "reddit": reddit,
        "stocktwits": stocktwits,
        "bull": bull,
        "bear": bear,
        "directional_n": total,
        "mixed": reddit["mixed"],
        "unclassified": reddit["unclassified"] + stocktwits["unclassified"],
        "nbi": score,
        "label": _nbi_label(score),
        "dispersion": _dispersion_entropy(bull, bear),
    }


def _format_score(value):
    return "—" if value is None else f"{value:+.1f}"


def _render_stocktwits_top(rows):
    bits = []
    for row in rows:
        bit = row["symbol"]
        if row.get("rank") is not None:
            bit += f" #{row['rank']}"
        if row.get("watchlist_count") is not None:
            bit += f" · 关注 {row['watchlist_count']:,}"
        counts = row.get("sentiment_counts") or {}
        if counts:
            bit += (f" · 标签 多{counts['bull']} / 空{counts['bear']}"
                    f" / 未标记{counts['unclassified']}")
        bits.append(bit)
    return "；".join(bits)


def build_section(kit, data, result=None):
    """返回数据驱动栏目元组；两路社区源都没有样本时不占版面。

    ``result`` 可由调用方传入同一次 ``calculate`` 的结果，让栏首大白话结论与正文
    严格复用同一对象；省略时保持原有独立调用兼容性。
    """
    result = result if isinstance(result, dict) else calculate(data)
    if not result["available"]:
        return None

    esc = kit.esc
    rows = []
    nbi = result["nbi"]
    if nbi is None:
        nbi_value = "—"
    else:
        nbi_value = f"{_format_score(nbi)} / 100 · {result['label']}"
    rows.append(("综合净情绪 NBI", nbi_value))
    rows.append(("方向样本", f"看多 {result['bull']} · 看空 {result['bear']}"
                              f" · 混合 {result['mixed']} · 未标记 {result['unclassified']}"))
    if result["dispersion"] is not None:
        rows.append(("多空分歧熵", f"{result['dispersion']:.1f} / 100"))

    reddit = result["reddit"]
    if reddit["available"]:
        rows.append(("Reddit", f"{reddit['sample_n']} 帖 · 看多 {reddit['bull']}"
                                f" / 看空 {reddit['bear']} · 混合 {reddit['mixed']}"
                                f" · 未命中 {reddit['unclassified']}"
                                f" · NBI {_format_score(reddit['nbi'])}"))
        if reddit["score_n"] or reddit["comments_n"]:
            engagement = []
            if reddit["score_n"]:
                engagement.append(f"得分 {reddit['score_sum']:,}（{reddit['score_n']} 帖）")
            if reddit["comments_n"]:
                engagement.append(f"评论 {reddit['comments_sum']:,}（{reddit['comments_n']} 帖）")
            rows.append(("Reddit 互动", " · ".join(engagement)))
    else:
        rows.append(("Reddit", "暂缺"))

    stocktwits = result["stocktwits"]
    if stocktwits["available"]:
        stocktwits_row = (f"标的流样本 {stocktwits['checked']} 条"
                          f"（{stocktwits['streams_available']}/{stocktwits['symbol_n']} 标的可读）")
        if stocktwits["checked"]:
            stocktwits_row += (f" · 看多 {stocktwits['bull']} / 看空 {stocktwits['bear']}"
                               f" · 未标记 {stocktwits['unclassified']}")
        elif stocktwits["streams_available"]:
            stocktwits_row += " · 暂无情绪消息样本"
        else:
            stocktwits_row += " · 情绪标签不可读"
        stocktwits_row += f" · NBI {_format_score(stocktwits['nbi'])}"
        rows.append(("StockTwits", stocktwits_row))
        top = _render_stocktwits_top(stocktwits["top_symbols"])
        if top:
            rows.append(("StockTwits 热度前五", top))
    else:
        rows.append(("StockTwits", "暂缺"))

    source_dates = []
    if reddit.get("available") and reddit.get("content_date"):
        source_dates.append(f"Reddit {reddit['content_date']}")
    if stocktwits.get("available") and stocktwits.get("content_date"):
        source_dates.append(f"StockTwits {stocktwits['content_date']}")
    if source_dates:
        rows.append(("数据日期", " · ".join(source_dates)))

    content = kit.kv([(esc(label), esc(value)) for label, value in rows])
    badge = kit.badge("因子结果", "ai")
    return (SECTION_KICKER, SECTION_TITLE, content, badge, SECTION_CAPTION)
