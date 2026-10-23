#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔄 数据线注册表 · 每条数据线 = 1 个主源 + 2 个备用源（2026-09-29 重构）

目标：
- 日报用到的每一条「数据线」都在 DATA_LINES 里登记：主源 1 个、备用源 2 个，缺一不可
  （tests/test_data_lines.py 逐条校验）；
- 备用源分两类：
    · 同格式镜像（same_format=True）：换主机 / 换路径，返回结构与主源完全一致，直接复用主源解析器；
    · 独立数据源（same_format=False）：其它供应商的公开接口，由 pipeline / providers 里对应的
      适配器（adapter）解析成与主源相同的内部结构；
- 只在主源失败或返回无效内容时才依次尝试备用源；启用了哪一路在日志与「数据覆盖」里写明；
- ``used_by`` 写的是**日报栏目标题**，栏目改名时同步（2026-09-29 第二批改名：全球头条→
  【无敌帝王蟹】全球头条、趋势跟踪→【深海大鲨鱼】趋势跟踪、政策因子→【深海肥蓝鲸】政策因子、
  每周量化走势预测→【嗜血大白鲨】逐日走势量化分析）；**数据源键名与新鲜度阈值键不改**
  （freshness_checker.FRESHNESS_THRESHOLDS 仍按 全球头条 / 每周量化走势预测 等源名匹配）；
- 绝不伪造数据：全部候选都失败就如实「暂缺」。

用法：
    urls(line_id, **fmt)         → 同格式候选 URL 列表（主源在前），供 safe_request_with_fallback
    candidates(line_id, **fmt)   → [(label, url, same_format)]，含独立源，供需要适配器的调用方
    describe()                   → 人类可读的数据线总览（python3 output/pipeline.py --sources）
"""

from typing import Any, Callable, Dict, List, Tuple
from urllib.parse import quote

# ------------------------------------------------------------------
# 主机常量
# ------------------------------------------------------------------
# 东方财富 push2 行情集群：push2 主站 + 编号镜像（官方站点与 akshare 等开源库长期使用的
# 72 / 82 / 79 等编号节点，返回结构完全一致）；历史 K 线在 push2his 集群（63 / 91 编号镜像同理）。
EM_PUSH2_HOSTS = ("push2.eastmoney.com", "82.push2.eastmoney.com", "72.push2.eastmoney.com")
EM_PUSH2HIS_HOSTS = ("push2his.eastmoney.com", "91.push2his.eastmoney.com", "63.push2his.eastmoney.com")
# 东方财富数据中心（报表型接口）：主站 -web 域名 + 两个同构入口
EM_DATACENTER_URLS = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get",
    "https://datacenter.eastmoney.com/api/data/v1/get",
    "https://datacenter.eastmoney.com/securities/api/data/v1/get",
)
RSSHUB_BASES = ("https://rsshub.app", "https://rsshub.rssforever.com", "https://rsshub.pseudoyu.com")

# Yahoo 代码 → 东方财富 secid（独立备用源的字段映射；映射不到的品种只走 Yahoo 双主机）
EM_SECID_FOR_YAHOO = {
    "^DJI": "100.DJIA", "%5EDJI": "100.DJIA",
    "^GSPC": "100.SPX", "%5EGSPC": "100.SPX",
    "^IXIC": "100.NDX", "%5EIXIC": "100.NDX",
    "^HSI": "100.HSI", "%5EHSI": "100.HSI",
    "^HSTECH": "100.HSTECH", "%5EHSTECH": "100.HSTECH",
    "^HSCE": "100.HSCEI", "%5EHSCE": "100.HSCEI",
    "MSFT": "105.MSFT", "META": "105.META",
    # NYMEX 美原油连续（东财 globalfuture/CL00Y）；若接口不认该代码，AI 行情复盘的 WTI 行
    # 只在 Yahoo 双主机失败时缺席，不会出现错误数字。
    "CL=F": "102.CL00Y",
}
# 新浪行情代码（A股宽基指数快照的独立备用源）：东财 secid → 新浪 hq 代码
SINA_CODE_FOR_EM = {
    "1.000001": "sh000001", "0.399001": "sz399001", "0.399006": "sz399006",
    "1.000688": "sh000688", "0.899050": "bj899050", "1.000300": "sh000300",
    "1.000016": "sh000016", "1.000905": "sh000905",
}
SINA_HQ_URL = "https://hq.sinajs.cn/list={codes}"
SINA_HQ_HEADERS = {"Referer": "https://finance.sina.com.cn/"}
SINA_LIVE_NEWS_URL = ("https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=20"
                      "&zhibo_id=152&tag_id=0&dire=f&dpc=1")


def em_secid_for_yahoo(symbol: str) -> str:
    """Yahoo 代码 → 东财 secid；港股 0700.HK → 116.00700，A股 600519.SS → 1.600519。"""
    sym = str(symbol or "").strip()
    if sym in EM_SECID_FOR_YAHOO:
        return EM_SECID_FOR_YAHOO[sym]
    if sym.endswith(".HK") and sym[:-3].isdigit():
        return f"116.{int(sym[:-3]):05d}"
    if sym.endswith(".SS") and sym[:-3].isdigit():
        return f"1.{sym[:-3]}"
    if sym.endswith(".SZ") and sym[:-3].isdigit():
        return f"0.{sym[:-3]}"
    return ""


def _em(host: str, path: str) -> str:
    return f"https://{host}{path}"


def _google_search_rss(query: str, hl: str, gl: str, ceid: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl={hl}&gl={gl}&ceid={ceid}"


# ------------------------------------------------------------------
# 数据线注册表：line_id → 主源 + 两个备用源
# ------------------------------------------------------------------
# 字段：name 数据线名；used_by 日报栏目；primary (label, url)；backups 恰好两项 (label, url, same_format)
#       note 说明（独立源的适配器位置 / 覆盖范围）
DATA_LINES: Dict[str, Dict[str, Any]] = {
    "yahoo_chart": {
        "name": "实时行情 · Yahoo 日线快照",
        # 2026-09-30 起「行情速览」与「全球大盘全景复盘」合并为【及时秋刀鱼】AI 行情复盘；
        # 原全景首块「全球指数概览」复用的就是本数据线的同一份 Yahoo 快照，已随合并删除。
        "used_by": ("【及时秋刀鱼】AI 行情复盘·报价", "【回游金枪鱼】今日预判"),
        "primary": ("Yahoo Finance query1", "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"),
        "backups": (
            ("Yahoo Finance query2（同格式镜像）",
             "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}", True),
            ("东方财富 行情快照（独立源，secid 映射）",
             _em(EM_PUSH2_HOSTS[0], "/api/qt/ulist.np/get"), False),
        ),
        "note": "适配器 pipeline._eastmoney_snapshot_quotes；美股/港股/A股指数与 MSFT/META 全覆盖，WTI 视东财代码可用性",
    },
    "yahoo_bars": {
        "name": "日线序列 · 港股量化 / 每周预测 / 板块轮动 / MACD",
        "used_by": ("每日趋势量化推演",
                    "【滚滚翻车鱼】板块轮动量化策略·港股与恒指日线",
                    "【六眼飞鱼】量化 MACD 策略·MACD日线"),
        "primary": ("Yahoo Finance query1", "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"),
        "backups": (
            ("Yahoo Finance query2（同格式镜像）",
             "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}", True),
            ("东方财富 日K（独立源，secid 映射）",
             _em(EM_PUSH2HIS_HOSTS[0], "/api/qt/stock/kline/get"), False),
        ),
        "note": "适配器 octopus_quant.providers.fetch_bars_eastmoney；恒指/恒科/国企指数、港股个股、A股与美股宽基指数；MACD 先读市场库 / 复用本次日线",
    },
    "em_ulist": {
        "name": "东方财富 指数 / 个股快照（ulist.np）",
        "used_by": ("【及时秋刀鱼】AI 行情复盘·A股全景",
                    "【及时秋刀鱼】AI 行情复盘·港股核对", "资金流动性分析",
                    "【滚滚翻车鱼】板块轮动量化策略·港股快照"),
        "primary": ("东方财富 push2", _em(EM_PUSH2_HOSTS[0], "/api/qt/ulist.np/get")),
        "backups": (
            ("东方财富 82.push2（同格式镜像）", _em(EM_PUSH2_HOSTS[1], "/api/qt/ulist.np/get"), True),
            ("东方财富 72.push2（同格式镜像）", _em(EM_PUSH2_HOSTS[2], "/api/qt/ulist.np/get"), True),
        ),
        "note": "A股宽基指数另有独立第三路：新浪 hq（见 sina_index）",
    },
    "sina_index": {
        "name": "A股宽基指数快照 · 独立第三源",
        "used_by": ("【及时秋刀鱼】AI 行情复盘·A股指数",),
        "primary": ("东方财富 push2 ulist.np", _em(EM_PUSH2_HOSTS[0], "/api/qt/ulist.np/get")),
        "backups": (
            ("东方财富 82.push2（同格式镜像）", _em(EM_PUSH2_HOSTS[1], "/api/qt/ulist.np/get"), True),
            ("新浪财经 hq.sinajs（独立源，代码映射）", SINA_HQ_URL, False),
        ),
        "note": "适配器 pipeline._sina_index_rows；新浪不提供涨跌家数，启用时 A股全景只报指数与成交额（partial）",
    },
    "em_clist": {
        "name": "东方财富 榜单列表（clist）",
        "used_by": ("热门榜单", "【及时秋刀鱼】AI 行情复盘·板块热力",
                    "资金流动性·港股成交榜",
                    "【滚滚翻车鱼】板块轮动量化策略·A股概念库"),
        "primary": ("东方财富 push2", _em(EM_PUSH2_HOSTS[0], "/api/qt/clist/get")),
        "backups": (
            ("东方财富 82.push2（同格式镜像）", _em(EM_PUSH2_HOSTS[1], "/api/qt/clist/get"), True),
            ("东方财富 72.push2（同格式镜像）", _em(EM_PUSH2_HOSTS[2], "/api/qt/clist/get"), True),
        ),
        "note": "",
    },
    "em_kline": {
        "name": "东方财富 日K（push2his）",
        "used_by": ("【及时秋刀鱼】AI 行情复盘·上日成交额",
                    "【巡游旗鱼】申万一级行业轮动·板块指数日K备用", "日线序列备用",
                    "【滚滚翻车鱼】板块轮动量化策略·港股与恒指日线备用"),
        "primary": ("东方财富 push2his", _em(EM_PUSH2HIS_HOSTS[0], "/api/qt/stock/kline/get")),
        "backups": (
            ("东方财富 91.push2his（同格式镜像）", _em(EM_PUSH2HIS_HOSTS[1], "/api/qt/stock/kline/get"), True),
            ("东方财富 63.push2his（同格式镜像）", _em(EM_PUSH2HIS_HOSTS[2], "/api/qt/stock/kline/get"), True),
        ),
        "note": "",
    },
    "sw_industry_index": {
        "name": "申万一级行业指数日线（31 个 · 东财板块指数 / 申万官方）",
        "used_by": ("【巡游旗鱼】申万一级行业轮动",),
        "primary": ("东方财富 push2his 板块指数日K（secid=90.BKxxxx）",
                    _em(EM_PUSH2HIS_HOSTS[0], "/api/qt/stock/kline/get")),
        "backups": (
            ("东方财富 91.push2his（同格式镜像）",
             _em(EM_PUSH2HIS_HOSTS[1], "/api/qt/stock/kline/get"), True),
            ("申万宏源研究所 官方指数发布（801xxx，独立源）",
             "https://www.swsresearch.com/institute-sw/api/index_publish/trend/?swindexcode={sw_code}&period=DAY",
             False),
        ),
        "note": "股票池为固定表 octopus_quant.industry_rotation.SW_L1_SECTORS（申万一级 801xxx ↔ 东财 BKxxxx，"
                "2026-09-29 逐个按 kline 返回的公司名核对），不再依赖 clist 大页列表（境外出口被 502 拒绝）；"
                "官方源适配器 industry_rotation.fetch_sw_series，整段历史一次返回且通常滞后一个交易日，"
                "只在东财三主机都取不到该行业时逐行业兜底，同一行业绝不混源",
    },
    "em_datacenter": {
        "name": "东方财富 数据中心报表（沪深港通成交 / 财经日历）",
        "used_by": ("【及时秋刀鱼】AI 行情复盘·南北向", "资金流动性分析",
                    "【探照安康鱼】时间节点量化分析"),
        "primary": ("东方财富 datacenter-web", EM_DATACENTER_URLS[0]),
        "backups": (
            ("东方财富 datacenter（同格式镜像）", EM_DATACENTER_URLS[1], True),
            ("东方财富 datacenter/securities（同格式镜像）", EM_DATACENTER_URLS[2], True),
        ),
        "note": "",
    },
    "em_news": {
        "name": "东方财富 快讯",
        "used_by": ("东方财富快讯", "【亮亮灯光鱿鱼】新闻情绪因子量化分析"),
        "primary": ("东方财富 np-weblist", "https://np-weblist.eastmoney.com/comm/web/getNewsByColumns"),
        "backups": (
            ("东方财富 np-listapi（同格式镜像）",
             "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns", True),
            ("新浪财经 7×24 快讯（独立源）", SINA_LIVE_NEWS_URL, False),
        ),
        "note": "适配器 pipeline._sina_live_news_items；启用时栏目来源标注「新浪财经 7×24」",
    },
    "google_news": {
        "name": "全球头条 · Google News 财经",
        "used_by": ("【无敌帝王蟹】全球头条", "【亮亮灯光鱿鱼】新闻情绪因子量化分析"),
        "primary": ("Google News 中文（中国大陆版）",
                    "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
        "backups": (
            ("Google News 中文（香港版）",
             "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-HK&gl=HK&ceid=HK:zh-Hant", True),
            ("Google News 搜索「财经」", _google_search_rss("财经", "zh-CN", "CN", "CN:zh-Hans"), True),
        ),
        "note": "",
    },
    "google_news_search": {
        "name": "专题新闻搜索 · 美联储 / 地缘政治",
        "used_by": ("【火爆大鱿鱼】美联储因子量化分析", "【巡回巨鲸】地缘政治因子量化分析"),
        "primary": ("Google News 搜索（中文·大陆版）", "https://news.google.com/rss/search?q={query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
        "backups": (
            ("Google News 搜索（中文·香港版）",
             "https://news.google.com/rss/search?q={query}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant", True),
            ("Google News 搜索（英文·美国版）",
             "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en", True),
        ),
        "note": "英文备用仍按同一关键词检索；标题语言可能为英文，页面照实展示",
    },
    "gov_policy": {
        "name": "国家政策 · 中国政府网",
        "used_by": ("【深海肥蓝鲸】政策因子",),
        "primary": ("政府网 最新政策", "https://www.gov.cn/zhengce/zuixin/"),
        "backups": (
            ("政府网 政策首页（同格式页面）", "https://www.gov.cn/zhengce/", True),
            ("政府网 政策文库（同格式页面）", "https://www.gov.cn/zhengce/zhengceku/", True),
        ),
        "note": "三路都是 gov.cn 官方页面，解析器按「日期 + 标题链接」通用提取",
    },
    "youtube_feed": {
        "name": "港股名家频道 · YouTube 频道订阅",
        "used_by": ("港股名家频道",),
        "primary": ("YouTube 官方 Atom", "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"),
        "backups": (
            ("RSSHub youtube/channel（同格式 Atom）", "https://rsshub.app/youtube/channel/{channel_id}", True),
            ("Invidious yewtu.be 频道订阅（同格式 Atom）", "https://yewtu.be/feed/channel/{channel_id}", True),
        ),
        "note": "",
    },
    "reddit": {
        "name": "趋势跟踪 · Reddit 板块热帖",
        "used_by": ("【深海大鲨鱼】趋势跟踪",),
        "primary": ("Reddit 公开 Atom", "https://www.reddit.com/r/{community}/hot/.rss?limit={limit}"),
        "backups": (
            ("old.reddit 公开 Atom（同格式）", "https://old.reddit.com/r/{community}/hot/.rss?limit={limit}", True),
            ("Reddit 公开 JSON（独立解析器）", "https://www.reddit.com/r/{community}/hot.json?limit={limit}", False),
        ),
        "note": "适配器 pipeline._reddit_json_items",
    },
    "stocktwits": {
        "name": "趋势跟踪 · StockTwits 趋势榜",
        "used_by": ("【深海大鲨鱼】趋势跟踪",),
        "primary": ("StockTwits trending/symbols", "https://api.stocktwits.com/api/2/trending/symbols.json"),
        "backups": (
            ("StockTwits trending/symbols/equities（同格式）",
             "https://api.stocktwits.com/api/2/trending/symbols/equities.json", True),
            ("StockTwits streams/trending（独立解析：按消息聚合标的）",
             "https://api.stocktwits.com/api/2/streams/trending.json", False),
        ),
        "note": "适配器 pipeline._stocktwits_symbols_from_stream",
    },
    "tradingview": {
        "name": "趋势跟踪 · TradingView Ideas",
        "used_by": ("【深海大鲨鱼】趋势跟踪",),
        "primary": ("TradingView Ideas RSS", "https://www.tradingview.com/feed/"),
        "backups": (
            ("TradingView Ideas RSS（stream=all）", "https://www.tradingview.com/feed/?stream=all", True),
            ("RSSHub tradingview/ideas（同格式 RSS）", "https://rsshub.app/tradingview/ideas", True),
        ),
        "note": "",
    },
    "bogleheads": {
        "name": "趋势跟踪 · Bogleheads 论坛",
        "used_by": ("【深海大鲨鱼】趋势跟踪",),
        "primary": ("Bogleheads 论坛 RSS", "https://www.bogleheads.org/forum/feed"),
        "backups": (
            ("Bogleheads app.php/feed（phpBB 同格式）", "https://www.bogleheads.org/forum/app.php/feed", True),
            ("Bogleheads feed.php（phpBB 同格式）", "https://www.bogleheads.org/forum/feed.php", True),
        ),
        "note": "",
    },
    "mainland_news_rss": {
        "name": "内地财经媒体 · 18 家（官方订阅 / 站内检索 RSS）",
        "used_by": ("【沸腾花蛤】情绪热点因子量化分析",
                    "【亮亮灯光鱿鱼】新闻情绪因子量化分析",
                    "【深海肥蓝鲸】政策因子",
                    "策略研判 / 逐栏 AI 研判（标题池）"),
        "primary": ("各媒体官方 RSS / Atom（若有）", "{feed}"),
        "backups": (
            ("Bing News 站内检索 RSS（同格式 RSS，链接直达原文）",
             "https://www.bing.com/news/search?q=site%3A{host}&format=rss", True),
            ("Google News 站内检索 RSS（同格式 RSS，链接经 news.google.com 跳转）",
             "https://news.google.com/rss/search?q=site%3A{host}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", True),
        ),
        "note": ("2026-10-13 取数修复：站内检索返回的条目链接是明文 http 的平台跳转地址，"
                 "会在外链白名单处被整条拒绝，18 家因此长期 0 条；现在先解出跳转地址里的"
                 "原文链接（直达原文），解不出才把跳转链接自身升级为 https，"
                 "候选源也改成「拿到可用条目才停」（第一路 0 条可用继续试下一路）。"
                 "这 18 家媒体多数在 2022 年后下线或从未提供官方 RSS，"
                 "默认直接走「站内检索 RSS（Bing → Google News）」按站点取公开标题；"
                 "任一媒体若拿到官方订阅地址，填进 MAINLAND_NEWS_SOURCES 的 feed 即自动优先走官方源。"
                 "只收标题 / 发布时间 / 原文链接，不复制正文，不绕过付费墙。"),
    },
    "hk_news_rss": {
        "name": "港股新闻源头 · 36 家媒体 RSS",
        "used_by": ("【深海大鲨鱼】趋势跟踪·新闻源头",),
        "primary": ("各媒体官方 RSS / Atom", "{feed}"),
        "backups": (
            ("Bing News 站内检索 RSS（同格式 RSS，链接直达原文）",
             "https://www.bing.com/news/search?q=site%3A{host}&format=rss", True),
            ("Google News 站内检索 RSS（同格式 RSS，链接经 news.google.com 跳转）",
             "https://news.google.com/rss/search?q=site%3A{host}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant", True),
        ),
        "note": "按每家媒体的主域名生成 site: 检索；备用源条目的链接主机名放行 bing.com / news.google.com",
    },
}


# ------------------------------------------------------------------
# 查询接口
# ------------------------------------------------------------------
def _fmt(template: str, fmt: Dict[str, Any]) -> str:
    try:
        return template.format(**fmt) if fmt else template
    except (KeyError, IndexError):
        return template


def candidates(line_id: str, **fmt) -> List[Tuple[str, str, bool]]:
    """[(label, url, same_format)]：主源 + 两个备用源（按尝试顺序）。"""
    line = DATA_LINES[line_id]
    label, url = line["primary"]
    out = [(label, _fmt(url, fmt), True)]
    for b_label, b_url, same in line["backups"]:
        out.append((b_label, _fmt(b_url, fmt), bool(same)))
    return out


def urls(line_id: str, **fmt) -> List[str]:
    """同格式候选 URL（主源 + 同格式备用），去重保序；独立源需调用方按 candidates 走适配器。"""
    return list(dict.fromkeys(u for _l, u, same in candidates(line_id, **fmt) if same))


def label_for(line_id: str, url: str, **fmt) -> str:
    """URL → 「主源」/「备用源1」/「备用源2」（供日志与数据覆盖标注）。"""
    for i, (_label, u, _same) in enumerate(candidates(line_id, **fmt)):
        if u == url:
            return "主源" if i == 0 else f"备用源{i}"
    return "备用源"


def describe() -> str:
    """全部数据线的主 / 备一览（纯文本）。"""
    lines = ["🔄 数据线主备总览（每条 1 主源 + 2 备用源）："]
    for lid, line in DATA_LINES.items():
        lines.append(f"· {line['name']} [{lid}] —— 用于 {'、'.join(line['used_by'])}")
        lines.append(f"    主源   {line['primary'][0]}：{line['primary'][1]}")
        for i, (label, url, same) in enumerate(line["backups"], 1):
            kind = "" if "（" in label else ("（同格式）" if same else "（独立源）")
            lines.append(f"    备用{i} {label}{kind}：{url}")
        if line.get("note"):
            lines.append(f"    说明   {line['note']}")
    return "\n".join(lines)


def get_backup_summary() -> str:
    """一行一条数据线的简表（沿用旧函数名，供采集日志打印）。"""
    lines = ["🔄 数据源备用方案总览（每条数据线 1 主 + 2 备）："]
    for lid, line in DATA_LINES.items():
        names = " → ".join([line["primary"][0]] + [b[0].split("（")[0] for b in line["backups"]])
        lines.append(f"· {line['name']}：{names}")
    return "\n".join(lines)


# 旧接口：数据源完整备用映射（供外部查询 / 审计）
ALL_BACKUP_MAP = {
    line["name"]: {"primary": line["primary"][1], "backups": [b[1] for b in line["backups"]]}
    for line in DATA_LINES.values()
}

# 通用请求头（模拟浏览器，避免被 WAF 拦截）
BACKUP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def try_urls_with_fallback(fetch_func: Callable, urls_: List[str], **kwargs) -> Tuple[Any, str, List[str]]:
    """依次尝试多个 URL，任一成功即返回 (result, success_url, errors)；全部失败 (None, None, errors)。"""
    errors = []
    for url in urls_:
        try:
            result = fetch_func(url, **kwargs)
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
            continue
        if result is None:
            errors.append(f"{url}: 返回 None")
            continue
        if isinstance(result, dict):
            if not result:
                errors.append(f"{url}: 返回空数据")
                continue
            if result.get("code") and result.get("code") != 200:
                errors.append(f"{url}: code={result.get('code')} msg={result.get('msg')}")
                continue
        if isinstance(result, str) and len(result.strip()) < 10:
            errors.append(f"{url}: 返回内容过短")
            continue
        return result, url, errors
    return None, None, errors


# ------------------------------------------------------------------
# 兼容旧调用名（全部改为从注册表取值）
# ------------------------------------------------------------------
def get_yahoo_urls(symbol: str) -> List[str]:
    """Yahoo Chart 同格式主备（query1 → query2）；东财独立备用由调用方走适配器。"""
    return urls("yahoo_chart", symbol=symbol)


def get_google_news_urls(category: str = "zh", query: str = "") -> List[str]:
    """Google News 主备：zh → 头条三路；search/fed/geo → 按关键词三路。"""
    if category in ("search", "fed", "geo") and query:
        return urls("google_news_search", query=quote(query))
    return urls("google_news")


def get_gov_policy_urls() -> List[str]:
    return urls("gov_policy")


def get_reddit_urls(community: str, limit: int = 10, mode: str = "rss") -> List[str]:
    """Reddit 主备；mode=rss 返回两路 Atom（www → old），mode=json 返回两路 JSON。
    兼容旧调用 get_reddit_urls(community, 'rss')。"""
    if isinstance(limit, str) and limit in ("rss", "json"):
        mode, limit = limit, 10
    if isinstance(mode, int):
        limit, mode = mode, "rss"
    if mode == "json":
        templates = ["https://www.reddit.com/r/{community}/hot.json?limit={limit}",
                     "https://old.reddit.com/r/{community}/hot.json?limit={limit}"]
    else:
        templates = ["https://www.reddit.com/r/{community}/hot/.rss?limit={limit}",
                     "https://old.reddit.com/r/{community}/hot/.rss?limit={limit}"]
    return list(dict.fromkeys(t.format(community=community, limit=limit) for t in templates))


def get_eastmoney_news_urls() -> List[str]:
    """东财快讯同格式主备（np-weblist → np-listapi）；新浪 7×24 独立备用由调用方走适配器。"""
    return urls("em_news")


def get_eastmoney_quote_urls() -> List[str]:
    """东财榜单 clist 三主机（主 + 两镜像）。"""
    return urls("em_clist")


def get_eastmoney_ulist_urls() -> List[str]:
    """东财快照 ulist.np 三主机（主 + 两镜像）。"""
    return urls("em_ulist")


def get_eastmoney_panorama_urls() -> List[str]:
    """旧名：全景快照 = ulist.np 三主机。"""
    return urls("em_ulist")


def get_eastmoney_kline_urls() -> List[str]:
    """东财日 K 三主机（主 + 两镜像）。"""
    return urls("em_kline")


def get_eastmoney_datacenter_urls() -> List[str]:
    """东财数据中心三入口。"""
    return urls("em_datacenter")


def get_calendar_urls() -> List[str]:
    return urls("em_datacenter")


def get_youtube_urls(channel_id: str) -> List[str]:
    return urls("youtube_feed", channel_id=channel_id) if channel_id else []


def get_stocktwits_urls(kind: str = "trending", symbol: str = "") -> List[str]:
    if kind == "stream" and symbol:
        return [f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json",
                f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json?filter=top"]
    return urls("stocktwits")


def get_tradingview_urls() -> List[str]:
    return urls("tradingview")


def get_bogleheads_urls() -> List[str]:
    return urls("bogleheads")


def get_news_site_backup_urls(host: str, line_id: str = "hk_news_rss") -> List[str]:
    """新闻源头按主域名生成的两路站内检索 RSS（Bing → Google）。

    line_id 缺省沿用港股新闻源头那条数据线；内地财经媒体传
    "mainland_news_rss"（两条线的检索模板相同，但审计归属分开记）。
    """
    if not host:
        return []
    return [u for _l, u, same in candidates(line_id, feed="", host=host)[1:] if same]


def get_mainland_news_site_urls(host: str) -> List[str]:
    """内地财经媒体：按主域名生成的两路站内检索 RSS（Bing → Google）。"""
    return get_news_site_backup_urls(host, line_id="mainland_news_rss")


def get_rsshub_fallbacks(feed_url: str) -> List[str]:
    """为 RSSHub 订阅生成备用基地址。"""
    if "rsshub.app" not in feed_url:
        return [feed_url]
    out = [feed_url]
    for base in RSSHUB_BASES[1:]:
        alt = feed_url.replace(RSSHUB_BASES[0], base)
        if alt not in out:
            out.append(alt)
    return out
