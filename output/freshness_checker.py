#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🕐 数据新鲜度检查模块 · 全栏目覆盖

目标：
- 对所有数据源统一检查新鲜度，不只是量化引擎
- 每个数据源根据自身特性设定不同的新鲜度阈值
- 输出详细的新鲜度报告，供日报总结和推送门禁使用

设计原则：
- 确定性、可复现、无未来函数
- 不同类型数据源有不同阈值（行情 vs 新闻 vs 政策 vs 量化）
- 滞后天数按自然日计算，交易类数据额外考虑周末/假期
- 不伪造数据，只标记状态
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple, List

CST = timezone(timedelta(hours=8))

# 各类数据源的新鲜度阈值（日历天）
FRESHNESS_THRESHOLDS = {
    # 行情类：交易日数据，允许周末滞后
    "实时行情": {"max_lag_days": 3, "type": "trading", "desc": "Yahoo 行情，交易日收盘数据"},
    "A股大盘全景": {"max_lag_days": 3, "type": "trading", "desc": "东财 A股全景，交易日收盘后"},
    "热门榜单": {"max_lag_days": 3, "type": "trading", "desc": "东财热门榜，交易日收盘后"},
    "港股量化引擎": {"max_lag_days": 4, "type": "trading", "desc": "港股量化，恒指日线，允许周一跑周五数据"},
    "每周量化走势预测": {"max_lag_days": 7, "type": "trading", "desc": "七日预测，基于日线（未来 7 个交易日），允许一周滞后"},
    # 2026-10-04 起栏目名随「申万一级 31 行业固定股票池」版本更新（旧名已随 09-29 的下线失效）
    "申万一级行业轮动策略": {"max_lag_days": 5, "type": "trading", "desc": "申万一级 31 行业日线（东财板块指数 / 申万官方兜底）"},
    "板块轮动量化策略": {"max_lag_days": 4, "type": "trading", "desc": "A股概念快照与港股日线/快照；以结果中最近数据日期检查"},
    "MACD量化策略": {"max_lag_days": 4, "type": "trading", "desc": "MACD 已收盘日线；按有效标的中最早收盘日保守检查"},
    # 新闻资讯类：要求当天或 72h 内
    "全球头条": {"max_lag_days": 1, "type": "news", "desc": "Google News 头条，要求当天"},
    "东财快讯": {"max_lag_days": 1, "type": "news", "desc": "东财快讯，要求当天"},
    "港股名家频道": {"max_lag_days": 7, "type": "news", "desc": "YouTube/RSS 频道，允许一周内"},
    "全网新闻源头（36家）": {"max_lag_days": 3, "type": "news", "desc": "36 家新闻源，72h 窗口"},
    "港股新闻源头": {"max_lag_days": 3, "type": "news", "desc": "36 家新闻源，72h 窗口"},
    # 内地财经媒体源头（2026-10-12）：18 家内地财经 / 证券 / 科技媒体，72h 窗口
    "内地财经媒体源头": {"max_lag_days": 3, "type": "news", "desc": "18 家内地财经媒体，72h 窗口"},
    "内地财经媒体（18家）": {"max_lag_days": 3, "type": "news", "desc": "18 家内地财经媒体，72h 窗口"},
    
    # 社区平台：72h 窗口
    "Reddit": {"max_lag_days": 3, "type": "community", "desc": "Reddit 热帖，72h 窗口"},
    "StockTwits": {"max_lag_days": 3, "type": "community", "desc": "StockTwits 趋势榜，实时"},
    "TradingView": {"max_lag_days": 3, "type": "community", "desc": "TradingView Ideas，72h 窗口"},
    "Bogleheads": {"max_lag_days": 3, "type": "community", "desc": "Bogleheads 论坛，72h 窗口"},
    
    # 专题分析：基于新闻，要求当天
    "美联储趋势": {"max_lag_days": 2, "type": "analysis", "desc": "美联储专题，Google News 查询"},
    "地缘政治趋势": {"max_lag_days": 2, "type": "analysis", "desc": "地缘政治专题，Google News 查询"},
    
    # 政策类：官方发布，允许 3 天内
    "国家政策（中国政府网）": {"max_lag_days": 3, "type": "policy", "desc": "中国政府网，官方政策"},
    "中国政府网": {"max_lag_days": 3, "type": "policy", "desc": "中国政府网，官方政策"},
    "国家政策": {"max_lag_days": 3, "type": "policy", "desc": "中国政府网，官方政策"},
    
    # 日历类：未来时间点，快照性质
    "财经日历": {"max_lag_days": 1, "type": "calendar", "desc": "财经日历，今日抓取快照"},
    
    # 默认
    "default": {"max_lag_days": 3, "type": "general", "desc": "通用，3 天内"},
}


def _parse_date(date_str: str):
    """解析日期字符串，支持 YYYY-MM-DD 和 YYYYMMDD"""
    if not date_str:
        return None
    try:
        # 尝试 YYYY-MM-DD
        if "-" in date_str:
            return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        # 尝试 YYYYMMDD
        if len(date_str) >= 8 and date_str[:8].isdigit():
            return datetime.strptime(date_str[:8], "%Y%m%d").date()
    except (ValueError, TypeError):
        pass
    return None


def _today_cst():
    return datetime.now(CST).date()


def check_single_freshness(source_name: str, source_data: Dict, today=None) -> Dict:
    """
    检查单个数据源的新鲜度
    
    返回:
    {
        "source": 源名,
        "status": "fresh" | "stale" | "expired" | "unavailable" | "snapshot",
        "is_fresh": bool,
        "lag_days": int | None,
        "content_date": str | None,
        "fetched_at": str | None,
        "threshold": int,
        "reason": str,
        "should_include": bool  # 是否应包含在日报中
    }
    """
    today = today or _today_cst()
    cfg = FRESHNESS_THRESHOLDS.get(source_name) or FRESHNESS_THRESHOLDS.get("default")
    threshold = cfg["max_lag_days"]
    
    src_status = source_data.get("status", "unavailable")
    content_date_str = source_data.get("content_date")
    fetched_at_str = source_data.get("fetched_at")
    is_snapshot = source_data.get("snapshot", False)
    
    # 无数据
    if src_status != "success":
        return {
            "source": source_name,
            "status": "unavailable",
            "is_fresh": False,
            "lag_days": None,
            "content_date": content_date_str,
            "fetched_at": fetched_at_str,
            "threshold": threshold,
            "reason": f"数据源不可用（{source_data.get('error', '未知原因')}）",
            "should_include": False,
        }
    
    # 快照类（财经日历等）：只要今天抓取就算新鲜
    if is_snapshot:
        return {
            "source": source_name,
            "status": "snapshot",
            "is_fresh": True,
            "lag_days": 0,
            "content_date": content_date_str,
            "fetched_at": fetched_at_str,
            "threshold": threshold,
            "reason": f"今日抓取快照（{cfg['desc']}）",
            "should_include": True,
        }
    
    # 解析内容日期
    content_date = _parse_date(content_date_str)
    if not content_date:
        # 没有内容日期，但有 is_today 标记
        if source_data.get("is_today"):
            return {
                "source": source_name,
                "status": "fresh",
                "is_fresh": True,
                "lag_days": 0,
                "content_date": content_date_str,
                "fetched_at": fetched_at_str,
                "threshold": threshold,
                "reason": f"标记为当天内容（{cfg['desc']}）",
                "should_include": True,
            }
        return {
            "source": source_name,
            "status": "stale",
            "is_fresh": False,
            "lag_days": None,
            "content_date": content_date_str,
            "fetched_at": fetched_at_str,
            "threshold": threshold,
            "reason": f"无有效内容日期，无法判断新鲜度（{cfg['desc']}）",
            "should_include": False,
        }
    
    lag = (today - content_date).days
    
    # 判断新鲜度
    if lag < 0:
        # 未来日期（异常）
        return {
            "source": source_name,
            "status": "stale",
            "is_fresh": False,
            "lag_days": lag,
            "content_date": content_date_str,
            "fetched_at": fetched_at_str,
            "threshold": threshold,
            "reason": f"内容日期在未来（{content_date_str}），异常",
            "should_include": False,
        }
    elif lag == 0:
        return {
            "source": source_name,
            "status": "fresh",
            "is_fresh": True,
            "lag_days": lag,
            "content_date": content_date_str,
            "fetched_at": fetched_at_str,
            "threshold": threshold,
            "reason": f"当天内容（{cfg['desc']}）",
            "should_include": True,
        }
    elif lag <= threshold:
        # 在阈值内，算新鲜（考虑周末/假期）
        # 交易类数据，lag 1-3 天可能仍是最新交易日
        if cfg["type"] == "trading" and lag <= 4:
            return {
                "source": source_name,
                "status": "fresh",
                "is_fresh": True,
                "lag_days": lag,
                "content_date": content_date_str,
                "fetched_at": fetched_at_str,
                "threshold": threshold,
                "reason": f"近 {lag} 天内（{cfg['desc']}），含周末/假期，视为新鲜",
                "should_include": True,
            }
        elif lag <= 1:
            return {
                "source": source_name,
                "status": "fresh",
                "is_fresh": True,
                "lag_days": lag,
                "content_date": content_date_str,
                "fetched_at": fetched_at_str,
                "threshold": threshold,
                "reason": f"近 {lag} 天内（{cfg['desc']}）",
                "should_include": True,
            }
        else:
            return {
                "source": source_name,
                "status": "stale",
                "is_fresh": False,
                "lag_days": lag,
                "content_date": content_date_str,
                "fetched_at": fetched_at_str,
                "threshold": threshold,
                "reason": f"滞后 {lag} 天（阈值 {threshold} 天，{cfg['desc']}），视为过期",
                "should_include": False,
            }
    else:
        # 超过阈值，过期
        return {
            "source": source_name,
            "status": "expired",
            "is_fresh": False,
            "lag_days": lag,
            "content_date": content_date_str,
            "fetched_at": fetched_at_str,
            "threshold": threshold,
            "reason": f"过期 {lag} 天（阈值 {threshold} 天，{cfg['desc']}）",
            "should_include": False,
        }


def check_all_freshness(data: Dict, today=None) -> Dict:
    """
    检查所有数据源的新鲜度
    
    返回:
    {
        "total": 总源数,
        "fresh": 新鲜数,
        "stale": 过期数,
        "unavailable": 不可用数,
        "snapshot": 快照数,
        "details": [各源详情],
        "fresh_sources": [新鲜源名],
        "stale_sources": [过期源名],
        "summary": 总结文本
    }
    """
    today = today or _today_cst()
    details = []
    fresh = stale = unavailable = snapshot = 0
    fresh_sources = []
    stale_sources = []
    
    for name, src_data in data.items():
        if str(name).startswith("_") or not isinstance(src_data, dict):
            continue
        result = check_single_freshness(name, src_data, today=today)
        details.append(result)
        
        if result["status"] == "fresh":
            fresh += 1
            fresh_sources.append(name)
        elif result["status"] in ("stale", "expired"):
            stale += 1
            stale_sources.append(name)
        elif result["status"] == "unavailable":
            unavailable += 1
        elif result["status"] == "snapshot":
            snapshot += 1
            fresh_sources.append(name)
    
    total = len(details)
    
    # 生成总结
    if fresh + snapshot == 0:
        summary = f"无新鲜数据（{stale} 过期 / {unavailable} 不可用），日报可能为旧内容"
    elif stale == 0 and unavailable == 0:
        summary = f"全部 {total} 个源新鲜（{fresh} 当天 + {snapshot} 快照）"
    else:
        summary = f"新鲜 {fresh+snapshot}/{total} 源（{fresh} 当天 + {snapshot} 快照），{stale} 过期，{unavailable} 不可用"
        if stale_sources:
            summary += f"；过期：{', '.join(stale_sources[:3])}" + (f" 等 {len(stale_sources)} 个" if len(stale_sources) > 3 else "")
    
    return {
        "total": total,
        "fresh": fresh,
        "stale": stale,
        "unavailable": unavailable,
        "snapshot": snapshot,
        "fresh_total": fresh + snapshot,
        "details": details,
        "fresh_sources": fresh_sources,
        "stale_sources": stale_sources,
        "summary": summary,
        "today": today.isoformat(),
    }


def format_freshness_report(freshness_result: Dict) -> str:
    """格式化新鲜度报告为人类可读文本"""
    lines = []
    lines.append(f"📅 数据新鲜度检查（{freshness_result['today']}）：{freshness_result['summary']}")
    lines.append("")
    lines.append("各源详情：")
    for detail in sorted(freshness_result["details"], key=lambda x: (x["status"], x["source"])):
        icon = {
            "fresh": "✅",
            "snapshot": "📸",
            "stale": "🕓",
            "expired": "⚠️",
            "unavailable": "❌",
        }.get(detail["status"], "❓")
        lag_txt = f"滞后 {detail['lag_days']} 天" if detail["lag_days"] is not None else "无日期"
        lines.append(f"{icon} {detail['source']}：{detail['status']}（{lag_txt}，阈值 {detail['threshold']} 天）- {detail['reason']}")
    
    return "\n".join(lines)
