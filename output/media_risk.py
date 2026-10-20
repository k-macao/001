#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A 股 / 港股媒体舆情风险事件提取（纯规则、可解释、离线）。

本模块只把已经采集并完成时间窗口过滤的标题转成结构化风险事件 / 异常关注信号；不联网、不生成
涨跌概率，也不把单一标题直接等同于事实。调用方负责：

* 提供 A/H 个股观察池与标题→个股归因函数；
* 严格按报告时点过滤标题，避免未来函数；
* 渲染原文来源、发布时间与「规则分不是概率」说明。

风险指数用于日报排序与分级，不是发生概率、收益预测或自动交易指令。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import urlsplit

WINDOW_HOURS = 72
HISTORY_DAYS = 30
MIN_BASELINE_DAYS = 5
MIN_ATTENTION_ONLY_TODAY = 3
MAX_STOCKS = 8
MAX_EVENTS_PER_STOCK = 6

SEVERITY_LABELS = {1: "关注", 2: "中等", 3: "高", 4: "严重"}
SEVERITY_BASE = {1: 24.0, 2: 44.0, 3: 68.0, 4: 90.0}
ATTRIBUTION_WEIGHTS = {"name": 1.0, "alias": 0.92, "sector": 0.55}
ATTRIBUTION_LABELS = {"name": "公司全名", "alias": "别名/代码", "sector": "行业链映射"}
AGENT_SCHEMA_VERSION = "octopus-media-risk-agent/2"
LEVEL_EN = {
    "blue": "Level 1 (LOW)",
    "yellow": "Level 2 (MEDIUM)",
    "orange": "Level 3 (HIGH)",
    "red": "Level 4 (CRITICAL)",
}
SEVERITY_EN = {1: "Low", 2: "Medium", 3: "High", 4: "Critical"}
# 下游 Schema 保持四个主维度；供应链 / 流动性 / 行业政策等细节放在
# secondary_category，分别归入最接近的 Governance / Financial / Regulatory 主类。
AGENT_CATEGORY = {
    "合规与监管": "Regulatory",
    "财务与审计": "Financial",
    "治理与股东": "Governance",
    "经营与供应链": "Financial",
    "交易与流动性": "Financial",
    "行业与政策": "Regulatory",
    "异常关注": "Sentiment",
}

_HISTORICAL_CUES = (
    "此前", "曾于", "去年", "历史事件", "事件回顾", "回顾", "已解除", "已撤销", "已终止",
    "previously", "last year", "historical", "recap", "was lifted", "was withdrawn", "case closed",
)
_EMERGING_CUES = (
    "传闻", "據悉", "据悉", "或将", "拟", "计划", "预警", "发酵", "质疑", "疑似",
    "rumor", "reportedly", "may face", "plans to", "warning", "questions",
)
_NOISE_RE = re.compile(
    r"抽奖|优惠券|促销|广告合作|品牌推广|带货|投票活动|招聘广告|课程报名|"
    r"直播预告|点击关注|扫码关注|giveaway|sponsored content|subscribe now|"
    r"webinar registration|brand promotion|recruitment advertisement",
    re.IGNORECASE,
)

# 关键词按「具体短语优先」设计，避免用“风险/调查/亏损”等过宽单词制造大量误报。
# severity: 4=严重事实型触发；3=高风险；2=中等；1=观察。
RISK_RULES: Sequence[Dict[str, Any]] = (
    {
        "category": "合规与监管",
        "terms": {
            "强制退市": 4, "终止上市": 4, "退市决定": 4, "退市预警": 4,
            "立案调查": 4, "监管立案": 4, "监管调查": 4,
            "被立案": 4, "立案侦查": 4, "刑事拘留": 4, "依法逮捕": 4,
            "留置调查": 4, "市场禁入": 4, "反垄断调查": 3,
            "行政处罚": 3, "处罚决定": 3, "重大处罚": 4, "重大违规": 3,
            "公开谴责": 3, "纪律处分": 3,
            "重大诉讼": 3, "重大仲裁": 3, "诉讼仲裁": 2, "遭起诉": 3, "被起诉": 3,
            "监管问询": 2, "问询函": 2, "关注函": 2, "警示函": 2,
            "责令改正": 2, "违规担保": 3, "资金占用": 3, "虚假陈述": 3,
            "违规减持": 3, "司法冻结": 3, "资产冻结": 3,
            "采取强制措施": 4, "强制措施": 4, "刑事责任": 4,
            "退市风险警示": 4, "实施退市风险警示": 4, "被实施ST": 3,
            "被实施*ST": 4, "披星戴帽": 3,
            "forced delisting": 4, "delisting decision": 4, "criminal investigation": 4,
            "securities fraud": 4, "regulatory investigation": 3,
            "regulatory probe": 3, "antitrust investigation": 3,
            "disciplinary action": 3, "regulatory inquiry": 2,
        },
    },
    {
        "category": "财务与审计",
        "terms": {
            "财务造假": 4, "審計造假": 4, "审计造假": 4, "虚增收入": 4,
            "虚增利润": 4, "无法表示意见": 4, "無法表示意見": 4,
            "否定意见": 4, "否定意見": 4, "债务违约": 4, "債務違約": 4,
            "未按期兑付": 4, "未能兑付": 4, "破产清算": 4, "破產清算": 4,
            "清盘呈请": 4, "清盤呈請": 4, "清盘令": 4, "清盤令": 4,
            "保留意见": 3, "保留意見": 3, "非标审计": 3, "非標審計": 3,
            "审计意见异常": 3, "審計意見異常": 3,
            "审计机构辞任": 3, "核数师辞任": 3, "核數師辭任": 3,
            "更换审计机构": 2, "更換核數師": 2, "财报延期": 3, "財報延期": 3,
            "年报延期": 3, "年報延期": 3, "业绩延期": 2, "業績延期": 2,
            "做空报告": 3, "沽空报告": 3, "沽空報告": 3, "做空机构": 2,
            "会计差错": 2, "會計差錯": 2, "大额计提": 2, "大額計提": 2,
            "商誉减值": 2, "商譽減值": 2, "逾期债务": 3, "逾期債務": 3,
            "审计意见变更": 2, "審計意見變更": 2, "应收账款异常": 3,
            "應收賬款異常": 3, "存货异常": 3, "存貨異常": 3,
            "业绩预亏": 2, "業績預虧": 2, "利润调节": 3, "利潤調節": 3,
            "流动性枯竭": 4, "流動性枯竭": 4, "现金流断裂": 4,
            "現金流斷裂": 4, "现金流紧张": 3, "現金流緊張": 3,
            "持续经营重大不确定性": 4,
            "持續經營重大不確定性": 4,
            "accounting fraud": 4, "financial fraud": 4, "audit disclaimer": 4,
            "adverse audit opinion": 4, "debt default": 4, "missed payment": 4,
            "winding-up petition": 4, "winding up petition": 4,
            "liquidation order": 4, "auditor resignation": 3,
            "qualified audit opinion": 3, "annual report delay": 3,
            "short seller report": 3, "short-selling report": 3,
            "receivables irregularities": 3, "inventory irregularities": 3,
            "profit warning": 2, "earnings loss warning": 2,
            "going concern uncertainty": 4, "cash flow crisis": 4,
        },
    },
    {
        "category": "治理与股东",
        "terms": {
            "高管失联": 4, "高管失聯": 4, "董事长失联": 4, "董事長失聯": 4,
            "实控人失联": 4, "實控人失聯": 4, "董事长被查": 4,
            "董事長被查": 4, "实际控制人被查": 4, "實際控制人被查": 4,
            "高管被查": 3, "集体辞职": 3, "集體辭職": 3, "控制权争夺": 3,
            "控制權爭奪": 3, "质押爆仓": 4, "質押爆倉": 4, "质押违约": 3,
            "股权冻结": 3, "股權凍結": 3, "股份冻结": 3, "股份凍結": 3,
            "高比例质押": 2, "高比例質押": 2, "控股股东减持": 2,
            "控股股東減持": 2, "大股东减持": 2, "大股東減持": 2,
            "董事长辞职": 2, "董事長辭職": 2, "高管辞职": 2, "高管辭職": 2,
            "控制权变更": 2, "控制權變更": 2, "实控人变更": 2, "實控人變更": 2,
            "高管频繁变动": 3, "高管頻繁變動": 3, "董监高变动": 2, "董監高變動": 2,
            "一致行动人解约": 3, "一致行動人解約": 3,
            "一致行动关系变化": 3, "一致行動關係變化": 3,
            "核心技术人员离职": 3, "核心技術人員離職": 3,
            "核心人员离职": 3, "核心人員離職": 3,
            "质押平仓风险": 3, "質押平倉風險": 3, "平仓风险": 3, "平倉風險": 3,
            "chairman detained": 4, "chairman missing": 4, "executive detained": 3,
            "share pledge default": 3, "shares frozen": 3,
            "controlling shareholder cuts stake": 2,
            "controlling shareholder stake sale": 2,
            "concert party agreement terminated": 3,
            "core technical staff departure": 3, "management turmoil": 3,
        },
    },
    {
        "category": "经营与供应链",
        "terms": {
            "供应中断": 4, "供應中斷": 4, "被制裁": 4, "出口禁令": 4,
            "重大事故": 4, "安全事故": 3, "工厂爆炸": 4, "工廠爆炸": 4,
            "发生爆炸": 4, "發生爆炸": 4, "数据泄露": 3, "數據洩露": 3,
            "网络攻击": 3, "網絡攻擊": 3, "大规模召回": 3, "大規模召回": 3,
            "产品召回": 2, "產品召回": 2, "全面停产": 4, "全面停產": 4,
            "停工停产": 3, "停工停產": 3, "断供": 3, "斷供": 3,
            "停产": 2, "停產": 2, "重大裁员": 3, "大规模裁员": 3,
            "大規模裁員": 3, "产品缺陷": 2, "產品缺陷": 2,
            "核心客户流失": 3, "核心客戶流失": 3, "大客户流失": 3,
            "大客戶流失": 3, "重大订单取消": 3, "重大訂單取消": 3,
            "supply disruption": 4, "supply chain disruption": 3,
            "export ban": 4, "major accident": 4, "factory explosion": 4,
            "data breach": 3, "cyberattack": 3, "mass recall": 3,
            "production halt": 3, "mass layoffs": 3,
        },
    },
    {
        "category": "交易与流动性",
        "terms": {
            "暂停交易": 4, "暫停交易": 4, "长期停牌": 4, "長期停牌": 4,
            "连续跌停": 4, "連續跌停": 4, "一字跌停": 4, "流动性危机": 4,
            "流動性危機": 4, "质押平仓": 4, "質押平倉": 4, "强制平仓": 4,
            "強制平倉": 4, "挤兑": 4, "擠兌": 4, "闪崩": 3, "閃崩": 3,
            "停牌核查": 3, "暂停上市": 4, "暫停上市": 4, "爆仓": 3, "爆倉": 3,
            "trading suspension": 4, "trading halted": 4, "liquidity crisis": 4,
            "forced liquidation": 4, "margin call": 3, "flash crash": 3,
        },
    },
    {
        "category": "行业与政策",
        "terms": {
            "行业整顿": 3, "行業整頓": 3, "专项整治": 3, "專項整治": 3,
            "监管收紧": 3, "監管收緊": 3, "出口管制": 3, "加征关税": 3,
            "加徵關稅": 3, "进口禁令": 3, "進口禁令": 3, "反垄断处罚": 3,
            "反壟斷處罰": 3, "价格战升级": 2, "價格戰升級": 2,
            "补贴退坡": 3, "補貼退坡": 3, "政府补贴依赖": 2, "政府補貼依賴": 2,
            "行业政策急转": 3, "行業政策急轉": 3,
            "industry crackdown": 3, "regulatory tightening": 3,
            "export controls": 3, "tariff hike": 3, "import ban": 3,
            "antitrust penalty": 3, "price war intensifies": 2,
        },
    },
    {
        "category": "异常关注",
        "terms": {
            "踩踏式抛售": 4, "踩踏式拋售": 4, "恐慌性抛售": 3, "恐慌性拋售": 3,
            "散户挤兑": 3, "散戶擠兌": 3, "跨平台扩散": 2, "跨平台擴散": 2,
            "舆情发酵": 2, "輿情發酵": 2, "利好出尽": 2, "利好出盡": 2,
            "异常成交量": 2, "異常成交量": 2, "成交量异常": 2, "成交量異常": 2,
            "换手率异常": 2, "換手率異常": 2, "资金异常流出": 2,
            "資金異常流出": 2, "主力资金异常流出": 2, "主力資金異常流出": 2,
            "panic selling": 3, "retail run": 3, "cross-platform spread": 2,
            "viral negative sentiment": 2,
        },
    },
)

# 命中词附近出现这些语境时，不把“澄清/解除”当成同等强度的已确认风险事实；
# 事件仍保留在观察层，避免标题中的争议本身被静默吞掉。
_MITIGATION_CUES = (
    "否认", "否認", "澄清", "不实", "不實", "不存在", "不涉及", "未被",
    "未发现", "未發現", "并无", "並無", "解除", "撤销", "撤銷", "驳回", "駁回",
    "完成整改", "恢复生产", "恢復生產", "解除制裁", "终止调查", "終止調查",
    "denies", "denied", "clarifies", "clarification", "false report", "no investigation",
    "lifted", "withdrawn", "dismissed", "resumes production", "investigation closed",
)

_OFFICIAL_RE = re.compile(
    r"证监会|證監會|上交所|深交所|北交所|港交所|联交所|聯交所|香港交易所|"
    r"香港证监会|香港證監會|中国政府网|中國政府網|人民法院|公安(?:局|部)|检察院|檢察院|"
    r"国家金融监督管理总局|國家金融監督管理總局|国家市场监督管理总局|國家市場監督管理總局|"
    r"公司公告|上市公司公告|公告原文|\bCSRC\b|\bSFC\b|\bHKEX\b|\bHKMA\b|"
    r"Hong Kong Exchanges|Shanghai Stock Exchange|Shenzhen Stock Exchange",
    re.IGNORECASE,
)
_AUTHORITY_RE = re.compile(
    r"新华社|新華社|人民日报|人民日報|央视|央視|中国证券报|中國證券報|中证网|中證網|"
    r"证券时报|證券時報|证券日报|證券日報|财新|財新|第一财经|第一財經|经济日报|經濟日報|"
    r"香港电台|香港電台|RTHK|\bBBC\b|Associated Press|\bAP News\b",
    re.IGNORECASE,
)
_PROFESSIONAL_RE = re.compile(
    r"财联社|財聯社|每日经济新闻|每日經濟新聞|21世纪经济报道|21世紀經濟報道|"
    r"经济观察|經濟觀察|中国基金报|中國基金報|券商中国|券商中國|智通财经|智通財經|"
    r"格隆汇|格隆匯|华尔街见闻|華爾街見聞|HKET|SCMP|彭博|Bloomberg|路透|Reuters|"
    r"MarketWatch|Financial Times|FT中文",
    re.IGNORECASE,
)
_COMMENTARY_RE = re.compile(
    r"YouTube|名家频道|名家頻道|自媒体|自媒體|博客|论坛|論壇|Reddit|StockTwits",
    re.IGNORECASE,
)


def _normalise_title(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_noise_title(title: str) -> bool:
    """只剔除明确营销 / 导流标题；若同时命中具体风险事件，调用方仍会保留。"""
    return bool(_NOISE_RE.search(title or ""))


def _safe_https_url(value: Any) -> Optional[str]:
    """只输出无凭据、标准端口且无危险字符的 HTTPS 原文地址。"""
    raw = str(value or "").strip()
    if not raw or any(char.isspace() or char in '<>\\"\'' for char in raw):
        return None
    try:
        parsed = urlsplit(raw)
        if (parsed.scheme.lower() != "https" or not parsed.hostname
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            return None
    except ValueError:
        return None
    return raw


def _event_status(title: str, event_date: str, report_date: str, *,
                  signal_type: str = "risk_event", disputed: bool = False) -> str:
    """确定性时态标签：Historical / Current / Emerging，不推断未给出的事实。"""
    text = (title or "").lower()
    if signal_type == "attention":
        return "Emerging"
    if any(cue.lower() in text for cue in _HISTORICAL_CUES):
        return "Historical"
    if disputed or any(cue.lower() in text for cue in _EMERGING_CUES):
        return "Emerging"
    try:
        age = (datetime.strptime(report_date, "%Y-%m-%d")
               - datetime.strptime(event_date, "%Y-%m-%d")).days
    except (TypeError, ValueError):
        age = 0
    return "Historical" if age >= 2 else "Current"


def _near_mitigation(title: str, start: int, length: int) -> bool:
    """命中词前后有限窗口内是否是澄清、否认、解除等缓释语境。"""
    context = title[max(0, start - 8): min(len(title), start + length + 8)]
    return any(cue in context for cue in _MITIGATION_CUES)


def classify_title(title: Any) -> Optional[Dict[str, Any]]:
    """把一条标题分类为一个或多个风险事件类型；未命中返回 ``None``。

    同一类别只保留最高严重度，但完整保留去重后的命中短语。出现澄清/否认/解除
    语境时整体严重度下调一级（最低为 1），并写 ``disputed=True``。
    """
    text = _normalise_title(title)
    if not text:
        return None
    # 英文风险短语按大小写不敏感匹配；lower() 不改变常见中英文标题的字符位置。
    search_text = text.lower()
    categories: List[Dict[str, Any]] = []
    any_mitigated = False
    for rule in RISK_RULES:
        hits: List[Dict[str, Any]] = []
        # 最长短语优先，避免“暂停交易/停牌”等近义片段重复放大。
        occupied: List[range] = []
        for term, severity in sorted(rule["terms"].items(), key=lambda item: (-len(item[0]), item[0])):
            start = 0
            while True:
                idx = search_text.find(term.lower(), start)
                if idx < 0:
                    break
                span = range(idx, idx + len(term))
                if not any(set(span).intersection(old) for old in occupied):
                    mitigated = _near_mitigation(search_text, idx, len(term))
                    hits.append({"term": term, "severity": int(severity),
                                 "mitigated": mitigated})
                    occupied.append(span)
                    any_mitigated = any_mitigated or mitigated
                start = idx + max(1, len(term))
        if not hits:
            continue
        severity = max(hit["severity"] for hit in hits)
        categories.append({
            "category": rule["category"],
            "severity": severity,
            "hits": list(dict.fromkeys(hit["term"] for hit in hits)),
        })
    if not categories:
        return None
    severity = max(cat["severity"] for cat in categories)
    if any_mitigated:
        severity = max(1, severity - 1)
        for cat in categories:
            cat["severity"] = min(cat["severity"], severity)
    return {
        "severity": severity,
        "severity_label": SEVERITY_LABELS[severity],
        "categories": categories,
        "hits": list(dict.fromkeys(
            term for cat in categories for term in cat["hits"])),
        "disputed": any_mitigated,
    }


def source_authority(item: Mapping[str, Any]) -> Dict[str, Any]:
    """按来源身份分层；返回标签和确定性权重（只用于排序，不代表真实性概率）。"""
    source = str(item.get("source") or "")
    section = str(item.get("section") or "")
    text = f"{source} {section}"
    if item.get("official") or _OFFICIAL_RE.search(text):
        return {"tier": "官方/监管", "weight": 1.0}
    if _AUTHORITY_RE.search(text):
        return {"tier": "权威媒体", "weight": 0.90}
    if _PROFESSIONAL_RE.search(text):
        return {"tier": "专业财经媒体", "weight": 0.78}
    if _COMMENTARY_RE.search(text):
        return {"tier": "评论/社区", "weight": 0.50}
    return {"tier": "其他公开来源", "weight": 0.65}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _volume_anomaly(today: int, prior: Sequence[Any]) -> Dict[str, Any]:
    vals = []
    for value in prior:
        number = _number(value)
        if number is not None and number >= 0:
            vals.append(number)
    if len(vals) < MIN_BASELINE_DAYS:
        return {"enough": False, "today": int(today), "n": len(vals),
                "need": MIN_BASELINE_DAYS, "label": "基线不足"}
    mean = sum(vals) / len(vals)
    variance = (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
                if len(vals) > 1 else 0.0)
    std = math.sqrt(max(0.0, variance))
    if std <= 1e-9:
        z = 0.0 if today == mean else (9.99 if today > mean else -9.99)
        z_text = "σ=0"
    else:
        z = (today - mean) / std
        z_text = f"{z:+.1f}"
    multiple = (float(today) / mean) if mean > 1e-9 else None
    # 基线均值为 0 时没有可定义的“倍数”；仍可由 z/σ=0 分支识别异常，
    # 但不得把无穷比值伪装成「达到均值 3 倍」。
    triple_mean = bool(today >= MIN_ATTENTION_ONLY_TODAY
                       and multiple is not None and multiple >= 3.0)
    abnormal = bool(z >= 2 or triple_mean)
    if z >= 3:
        label = "极端突增"
    elif z >= 2:
        label = "异常突增"
    elif triple_mean:
        label = "达到均值3倍"
    elif z >= 1:
        label = "偏热"
    else:
        label = "正常"
    return {"enough": True, "today": int(today), "n": len(vals),
            "mean": mean, "std": std, "z": z, "z_display": z_text,
            "multiple": multiple, "triple_mean": triple_mean,
            "abnormal": abnormal, "label": label}


def _level(score: int, *, force_red: bool = False) -> Dict[str, Any]:
    if force_red or score >= 80:
        return {"rank": 4, "key": "red", "label": "红色预警"}
    if score >= 60:
        return {"rank": 3, "key": "orange", "label": "橙色预警"}
    if score >= 40:
        return {"rank": 2, "key": "yellow", "label": "黄色关注"}
    return {"rank": 1, "key": "blue", "label": "蓝色观察"}


def _action(level_key: str) -> str:
    return {
        "red": "暂停新增仓位；优先核验监管/公司公告；已有敞口按流动性预案处理",
        "orange": "限制单票风险敞口；下一交易窗口前复核；避免追价与无量卖出假设",
        "yellow": "列入灰名单；等待权威来源交叉确认；适度收紧仓位上限",
        "blue": "保留观察；核验原文与后续公告；不依据单一标题自动交易",
    }.get(level_key, "保留观察并核验原文")


def _effective_severity(risk: Mapping[str, Any], authority: Mapping[str, Any], tag: str) -> int:
    """交易所 / 监管直接发出的问询或关注函按 Level 3 处理，普通问询仍为 Level 2。"""
    severity = int(risk.get("severity") or 1)
    official_letter = {"监管问询", "问询函", "关注函", "警示函", "regulatory inquiry"}
    if (severity == 2 and authority.get("tier") == "官方/监管"
            and tag in ("name", "alias")
            and official_letter.intersection(set(risk.get("hits") or []))
            and not risk.get("disputed")):
        return 3
    return severity


def _ticker(market: Any, code: Any, name: Any = "") -> str:
    """把榜单代码规范为下游稳定的 ``代码.交易所`` 格式，且保持幂等。"""
    raw = str(code or "").strip().upper()
    market = str(market or "")
    if "." in raw:
        base, suffix = raw.rsplit(".", 1)
        suffix = "SH" if suffix == "SS" else suffix
        if suffix in ("HK", "SH", "SZ", "BJ"):
            return f"{base.zfill(5) if suffix == 'HK' else base}.{suffix}"
    if market == "港股" and raw:
        return f"{raw.zfill(5)}.HK"
    if market == "A股" and raw:
        if raw.startswith(("4", "8", "92")):
            suffix = "BJ"
        elif raw.startswith(("5", "6", "9")):
            suffix = "SH"
        else:
            suffix = "SZ"
        return f"{raw}.{suffix}"
    return raw or str(name or "")


def _agent_action(stock: Mapping[str, Any]) -> str:
    level_key = str(((stock.get("level") or {}).get("key") or "blue"))
    categories = set(stock.get("categories") or [])
    if level_key == "red":
        return "Blacklist"
    if level_key == "orange":
        return "Reduce_Exposure"
    if stock.get("sector_only") or "行业与政策" in categories:
        return "Hedge"
    return "Watch"


_ACTION_LABELS = {
    "Blacklist": "列入禁入观察名单",
    "Reduce_Exposure": "降低风险敞口",
    "Hedge": "组合对冲",
    "Watch": "持续观察",
}
_ACTION_SOPS = {
    "Blacklist": [
        "暂停新增仓位", "优先核验监管或公司公告", "已有敞口按流动性预案处理"],
    "Reduce_Exposure": [
        "限制单票风险敞口", "下一交易窗口前复核原文与公告", "避免追价或无量卖出假设"],
    "Hedge": [
        "核验行业政策与个股相关性", "优先使用组合层对冲", "不得把行业弱归因当成公司事实"],
    "Watch": ["保留观察", "等待权威来源交叉确认", "不依据单一标题自动交易"],
}


def _authority_level(events: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    """把最高来源映射成可排序等级，并保留来源类型与中文层级。"""
    if not events:
        return {"value": "Unknown", "type": "Unknown", "tier_zh": "未知来源"}
    event = max(events, key=lambda row: float(row.get("authority_weight") or 0))
    tier = str(event.get("authority_tier") or "其他公开来源")
    if tier == "官方/监管":
        value, source_type = "High", "Official"
    elif tier == "权威媒体":
        value, source_type = "High", "Authoritative_Media"
    elif tier == "专业财经媒体":
        value, source_type = "Moderate", "Professional_Media"
    elif tier == "评论/社区":
        section = str(event.get("section") or "")
        source_type = ("Social_Media" if re.search(
            r"Reddit|StockTwits|论坛|論壇", section, re.I) else "Self_Media")
        value = "Low"
    else:
        value, source_type = "Moderate", "Public_Source"
    return {"value": value, "type": source_type, "tier_zh": tier}


def _logic_summary(stock: Mapping[str, Any]) -> List[str]:
    """输出可审计的判定依据摘要，而非模型隐藏思维链。"""
    parts = []
    components = stock.get("score_components") or {}
    if stock.get("attention_only"):
        parts.append("未命中具体负面事件词；仅因新闻量达到可靠异常门槛进入观察")
    else:
        parts.append("具体事件触发：" + "、".join(stock.get("top_hits") or ["—"]))
    parts.append(
        f'{int(stock.get("source_n") or 0)} 个来源 / {int(stock.get("category_n") or 0)} 类信号；'
        f'最高来源权重 {float(components.get("max_authority_weight") or 0):.2f}')
    final_score = int(components.get("final_score") or stock.get("risk_index") or 0)
    if stock.get("attention_only"):
        parts.append(
            f'分数组件：热度基础 {float(components.get("attention_base") or 0):.1f}'
            f' + 权威度 {float(components.get("authority_bonus") or 0):.1f}'
            f' + 来源广度 {float(components.get("source_diversity_bonus") or 0):.1f}；'
            f'最终 {final_score}/100（归一化 {final_score / 100:.2f}，不是概率）')
    else:
        parts.append(
            f'分数组件：主事件 {float(components.get("primary_event_impact") or 0):.1f}'
            f' + 跨源 {float(components.get("source_confirmation_bonus") or 0):.1f}'
            f' + 跨类 {float(components.get("category_breadth_bonus") or 0):.1f}'
            f' + 热度 {float(components.get("attention_bonus") or 0):.1f}'
            f' + 空头背离 {float(components.get("bearish_divergence_bonus") or 0):.1f}；'
            f'最终 {final_score}/100（归一化 {final_score / 100:.2f}，不是概率）')
    attention = stock.get("attention") or {}
    if attention.get("enough"):
        multiple = attention.get("multiple")
        multiple_text = (f"{float(multiple):.1f}倍" if type(multiple) in (int, float) else "基线为0")
        parts.append(
            f'当日 {int(attention.get("today") or 0)} 条，历史均值 '
            f'{float(attention.get("mean") or 0):.1f} 条（{multiple_text}，{attention.get("label") or "正常"}）')
    for cap in components.get("caps") or []:
        parts.append(str(cap))
    return parts


def _reported_at(event: Mapping[str, Any]) -> str:
    """保留证据实际精度；日期级证据不得伪造 00:00:00。"""
    ts = str(event.get("ts") or "").strip()
    if len(ts) >= 19:
        return ts[:19]
    if len(ts) >= 16:
        return ts[:16]
    return str(event.get("date") or "").strip()


def _agent_record(stock: Mapping[str, Any], date_str: str, as_of: str = "") -> Dict[str, Any]:
    """生成下游 Agent 可直接解析的稳定 Schema；归一化分数仍是序数，不是概率。"""
    events = list(stock.get("_agent_events") or stock.get("events") or [])
    agent_events = []
    for event in events:
        category_hits = event.get("category_hits") or {}
        categories = list(event.get("categories") or ["异常关注"])
        for category in categories:
            hits = list(category_hits.get(category) or event.get("hits") or [])
            severity = int((event.get("category_severity") or {}).get(
                category, event.get("severity") or 1))
            agent_events.append({
                "event_type": str(hits[0] if hits else category),
                "category": AGENT_CATEGORY.get(category, "Sentiment"),
                "secondary_category": category,
                "summary": str(event.get("title") or ""),
                "severity": SEVERITY_EN.get(severity, "Low"),
                "severity_level": severity,
                "status": str(event.get("status") or "Current"),
                "lifecycle_weight": round(float(event.get("lifecycle_weight") or 1.0), 2),
                "mitigation": bool(event.get("disputed")),
                "score_inputs": {
                    "signal_type": str(event.get("signal_type") or "risk_event"),
                    "severity_base": (10.0 if event.get("signal_type") == "attention"
                                      else SEVERITY_BASE.get(severity, 24.0)),
                    "source_weight": round(float(event.get("authority_weight") or 0), 2),
                    "attribution_weight": round(float(ATTRIBUTION_WEIGHTS.get(
                        str(event.get("attribution") or "alias"), ATTRIBUTION_WEIGHTS["alias"])), 2),
                    "mitigation_weight": 0.55 if event.get("disputed") else 1.0,
                    "lifecycle_weight": round(float(event.get("lifecycle_weight") or 1.0), 2),
                    "event_impact": round(float(event.get("impact") or 0), 2),
                },
                # 与用户约定的最小 Schema 一致：evidence 本身始终是可直接检索的客观文本；
                # 来源、时点、归因和安全 URL 放在并列元数据中，供 RAG / 工具调用过滤。
                "evidence": str(event.get("title") or ""),
                "evidence_metadata": {
                    "scope": "headline_only",
                    "source": str(event.get("source") or ""),
                    "authority_tier": str(event.get("authority_tier") or ""),
                    "timestamp": _reported_at(event),
                    "timezone": "Asia/Shanghai",
                    "time_precision": str(event.get("time_precision") or "date"),
                    "url": _safe_https_url(event.get("url")),
                    "attribution": str(event.get("attribution") or ""),
                    "attribution_label": str(event.get("attribution_label") or ""),
                    "matched_phrase": str(hits[0] if hits else ""),
                },
            })
    authority = _authority_level(events)
    attention = stock.get("attention") or {}
    sentiment = stock.get("sentiment") or {}
    sentiment_score = _number(sentiment.get("score"))
    change_pct = _number(stock.get("change_pct"))
    bearish_divergence = bool(
        sentiment_score is not None and sentiment_score <= -0.2
        and change_pct is not None and change_pct >= 2.0)
    channel_types = set()
    propagation_by_source: Dict[str, Dict[str, Any]] = {}
    for event in events:
        tier = str(event.get("authority_tier") or "")
        if tier == "官方/监管":
            channel_type = "official"
        elif tier == "评论/社区":
            channel_type = "social_or_self_media"
        else:
            channel_type = "media"
        channel_types.add(channel_type)
        source = str(event.get("source") or "未知来源")
        node = {
            "source": source,
            "channel_type": channel_type,
            "authority_tier": tier,
            "first_observed_at": _reported_at(event),
            "timezone": "Asia/Shanghai",
            "time_precision": str(event.get("time_precision") or "date"),
            "url": _safe_https_url(event.get("url")),
        }
        previous = propagation_by_source.get(source)
        if (previous is None or (node["first_observed_at"] or "9999-99-99")
                < (previous["first_observed_at"] or "9999-99-99")):
            propagation_by_source[source] = node
    propagation_nodes = sorted(
        propagation_by_source.values(),
        key=lambda node: (node["first_observed_at"] or "9999-99-99", node["source"]))
    has_social = "social_or_self_media" in channel_types
    has_mainstream = bool(channel_types.intersection({"official", "media"}))
    if has_social and has_mainstream:
        propagation_stage = "Cross_Platform"
    elif int(stock.get("source_n") or 0) >= 2:
        propagation_stage = "Cross_Source"
    else:
        propagation_stage = "Single_Source"
    authoritative_events = [
        event for event in events
        if event.get("signal_type") == "risk_event" and not event.get("disputed")
        and event.get("authority_tier") in ("官方/监管", "权威媒体", "专业财经媒体")
    ]
    first_authoritative_event = (min(
        authoritative_events,
        key=lambda event: (_reported_at(event) or "9999-99-99", int(event.get("sequence") or 0)))
        if authoritative_events else None)
    first_authoritative = ({
        "timestamp": _reported_at(first_authoritative_event),
        "timezone": "Asia/Shanghai",
        "time_precision": str(first_authoritative_event.get("time_precision") or "date"),
        "source": str(first_authoritative_event.get("source") or ""),
        "authority_tier": str(first_authoritative_event.get("authority_tier") or ""),
        "url": _safe_https_url(first_authoritative_event.get("url")),
        "scope": "first_observed_in_72h_window_not_global_first",
    } if first_authoritative_event else None)
    level_key = str(((stock.get("level") or {}).get("key") or "blue"))
    action = _agent_action(stock)
    try:
        report_date = datetime.strptime(str(date_str), "%Y%m%d").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        report_date = str(date_str or "")[:10]
    timestamp = str(as_of or "").strip() or (f"{report_date} 23:59:59" if report_date else "")
    rationale = str(stock.get("action") or "")
    if stock.get("top_hits"):
        rationale += "；核心触发：" + "、".join(stock.get("top_hits") or [])
    return {
        "schema_version": AGENT_SCHEMA_VERSION,
        "stock_code": _ticker(stock.get("market"), stock.get("code"), stock.get("name")),
        "stock_name": str(stock.get("name") or ""),
        "market": str(stock.get("market") or ""),
        "timestamp": timestamp,
        "timezone": "Asia/Shanghai",
        "overall_risk_score": round(float(stock.get("risk_index") or 0) / 100.0, 2),
        "score_semantics": "normalized_ordinal_rule_index_not_probability",
        "risk_level": LEVEL_EN.get(level_key, "Level 1 (LOW)"),
        "risk_level_number": int(((stock.get("level") or {}).get("rank") or 1)),
        "risk_level_zh": str(((stock.get("level") or {}).get("label") or "蓝色观察")),
        "risk_events": agent_events,
        "sentiment_metrics": {
            "sentiment_score": round(sentiment_score, 4) if sentiment_score is not None else None,
            "sentiment_available": sentiment_score is not None,
            "sentiment_sample_n": int(sentiment.get("sample_n") or 0),
            "attention_spike": bool(attention.get("abnormal")),
            "attention_label": str(attention.get("label") or "基线不足"),
            "attention_z_score": (round(float(attention.get("z") or 0), 2)
                                  if attention.get("enough") else None),
            "attention_baseline_mean": (round(float(attention.get("mean") or 0), 4)
                                        if attention.get("enough") else None),
            "attention_baseline_days": int(attention.get("n") or 0),
            "attention_multiple": (round(float(attention["multiple"]), 2)
                                   if type(attention.get("multiple")) in (int, float) else None),
            "attention_three_times_mean": bool(attention.get("triple_mean")),
            "media_authority_level": authority["value"],
            "media_authority_type": authority["type"],
            "media_authority_tier_zh": authority["tier_zh"],
            "source_count": int(stock.get("source_n") or 0),
            "channel_count": len(channel_types),
            "channel_types": sorted(channel_types),
            "propagation_stage": propagation_stage,
            "propagation_nodes": propagation_nodes,
            "cross_platform_confirmed": bool(has_social and has_mainstream),
            "first_authoritative_negative": first_authoritative,
            "first_report_scope": "first_observed_in_72h_window_not_global_first",
            "price_change_pct": round(change_pct, 4) if change_pct is not None else None,
            "bearish_divergence": bearish_divergence,
        },
        "actionable_recommendation": {
            "action": action,
            "action_label": _ACTION_LABELS[action],
            "rationale": rationale,
            "sop": list(_ACTION_SOPS[action]),
            "automatic_execution": False,
        },
        "risk_logic_summary": _logic_summary(stock),
        "score_components": dict(stock.get("score_components") or {}),
        "data_quality": {
            "window_hours": int(stock.get("window_hours") or WINDOW_HOURS),
            "report_anchor": timestamp,
            "future_information_excluded": bool(as_of),
            "headline_only": True,
            "evidence_count": len(events),
            "total_evidence_count": int(stock.get("event_n") or len(events)),
            "minute_precision_evidence_count": sum(
                1 for event in events if event.get("time_precision") == "minute"),
            "date_only_evidence_count": sum(
                1 for event in events if event.get("time_precision") != "minute"),
            "input_noise_filtered_count": int(stock.get("noise_filtered_count") or 0),
        },
    }


def _history_prior_totals(history: Mapping[str, Any], key: str, date_str: str) -> List[float]:
    """读取报告日前 30 个自然日的新闻量（缺跑日期不向更早历史借样本）。"""
    days = (((history.get("stocks") or {}).get(key) or {}).get("days") or {})
    rows = []
    if not isinstance(days, dict):
        return rows
    report_key = str(date_str or "")
    try:
        cutoff = (datetime.strptime(report_key, "%Y%m%d")
                  - timedelta(days=HISTORY_DAYS)).strftime("%Y%m%d")
    except (TypeError, ValueError):
        cutoff = ""
    for day, value in sorted(days.items(), reverse=True):
        if day >= report_key or (cutoff and day < cutoff) or not isinstance(value, dict):
            continue
        total = _number(value.get("total"))
        if total is not None:
            rows.append(total)
        if len(rows) >= HISTORY_DAYS:
            break
    return rows


def _price_map(prices: Optional[Mapping[str, Any]]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    for key, value in (prices or {}).items():
        if isinstance(value, Mapping):
            value = value.get("change_pct")
        out[str(key)] = _number(value)
    return out


def analyze(
    headlines: Iterable[Mapping[str, Any]],
    universe: Sequence[Mapping[str, Any]],
    attribute_headline: Callable[[str, Sequence[Mapping[str, Any]]], Sequence[Mapping[str, Any]]],
    history: Optional[Mapping[str, Any]],
    date_str: str,
    *,
    prices: Optional[Mapping[str, Any]] = None,
    sentiment_scores: Optional[Mapping[str, Any]] = None,
    as_of: str = "",
    window_hours: int = WINDOW_HOURS,
) -> Dict[str, Any]:
    """构建 A/H 热门标的的媒体风险结果。

    ``headlines`` 必须由调用方先按报告时点过滤。函数仍会去重并只接受 A股/港股
    观察池，避免美股或窗口外标题混入。``attribute_headline`` 的返回项需含
    key/market/code/name/tag（与 pipeline._attribute_headline 一致）。
    """
    history = history if isinstance(history, Mapping) else {}
    sentiment_scores = sentiment_scores if isinstance(sentiment_scores, Mapping) else {}
    ah_universe = [dict(stock) for stock in universe
                   if str(stock.get("market") or "") in ("A股", "港股")]
    price_changes = _price_map(prices)
    try:
        today_iso = datetime.strptime(str(date_str), "%Y%m%d").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        today_iso = str(date_str or "")[:10]

    # 日期+标题去重：不同日期的同题保留；同日重复转载只保留权威度更高的一条。
    dedup: Dict[tuple, Dict[str, Any]] = {}
    order: List[tuple] = []
    for raw in headlines or []:
        if not isinstance(raw, Mapping):
            continue
        title = _normalise_title(raw.get("title"))
        if not title:
            continue
        date = str(raw.get("date") or raw.get("ts") or "")[:10]
        key = (date, re.sub(r"[\W_]+", "", title, flags=re.UNICODE).lower())
        item = dict(raw)
        item["title"] = title
        old = dedup.get(key)
        if old is None:
            dedup[key] = item
            order.append(key)
        elif source_authority(item)["weight"] > source_authority(old)["weight"]:
            dedup[key] = item
    rows = [dedup[key] for key in order]

    slots: Dict[str, Dict[str, Any]] = {
        str(stock["key"]): {"info": stock, "events": [], "headlines": [],
                            "window_titles": set(), "today_titles": set()}
        for stock in ah_universe if stock.get("key")
    }
    scanned_attributions = 0
    noise_n = 0
    for sequence, item in enumerate(rows):
        title = item["title"]
        risk = classify_title(title)
        if not risk and _is_noise_title(title):
            noise_n += 1
            continue
        targets = attribute_headline(title, ah_universe) or []
        targets = [target for target in targets
                   if target.get("key") in slots and target.get("market") in ("A股", "港股")]
        if not targets:
            continue
        date = str(item.get("date") or item.get("ts") or "")[:10]
        ts = str(item.get("ts") or "").strip()
        authority = source_authority(item)
        for target in targets:
            slot = slots[target["key"]]
            identity = (date, title)
            slot["window_titles"].add(identity)
            if date == today_iso:
                slot["today_titles"].add(identity)
            scanned_attributions += 1
            tag = str(target.get("tag") or "name")
            attr_weight = ATTRIBUTION_WEIGHTS.get(tag, ATTRIBUTION_WEIGHTS["alias"])
            evidence = {
                "title": title,
                "source": str(item.get("source") or item.get("section") or "未知来源"),
                "section": str(item.get("section") or ""),
                "url": _safe_https_url(item.get("url")) or "",
                "ts": ts,
                "date": date,
                "time_precision": "minute" if ts else "date",
                "sequence": sequence,
                "authority_tier": authority["tier"],
                "authority_weight": authority["weight"],
                "attribution": tag,
                "attribution_label": ATTRIBUTION_LABELS.get(tag, tag),
            }
            slot["headlines"].append(evidence)
            if not risk:
                continue
            severity = _effective_severity(risk, authority, tag)
            status = _event_status(
                title, date, today_iso, signal_type="risk_event", disputed=risk["disputed"])
            lifecycle_weight = {"Historical": 0.65, "Emerging": 0.80, "Current": 1.0}[status]
            impact = (SEVERITY_BASE[severity] * float(authority["weight"])
                      * attr_weight * (0.55 if risk["disputed"] else 1.0)
                      * lifecycle_weight)
            category_hits = {cat["category"]: list(cat["hits"])
                             for cat in risk["categories"]}
            category_severity = {cat["category"]: int(cat["severity"])
                                 for cat in risk["categories"]}
            # 官方直接问询升档时，同步反映在对应类别的标准输出中。
            if severity > int(risk["severity"]) and "合规与监管" in category_severity:
                category_severity["合规与监管"] = severity
            slot["events"].append({
                **evidence,
                "severity": severity,
                "severity_label": SEVERITY_LABELS[severity],
                "categories": [cat["category"] for cat in risk["categories"]],
                "category_hits": category_hits,
                "category_severity": category_severity,
                "hits": risk["hits"],
                "disputed": risk["disputed"],
                "status": status,
                "lifecycle_weight": lifecycle_weight,
                "signal_type": "risk_event",
                "impact": round(impact, 2),
            })

    stocks: List[Dict[str, Any]] = []
    concrete_event_ids = set()
    attention_evidence_ids = set()
    category_counts: Counter = Counter()
    authority_counts: Counter = Counter()
    for key, slot in slots.items():
        info = slot["info"]
        prior_totals = _history_prior_totals(history, key, str(date_str))
        attention = _volume_anomaly(len(slot["today_titles"]), prior_totals)
        events = list(slot["events"])
        # 没有负面事件词时，只有“基线可靠 + z≥2 + 当日至少 3 条”才单独形成
        # 异常关注信号；它最高停留黄色，且正文明确“不代表负面事实”。
        attention_only = bool(
            not events and attention.get("enough") and attention.get("abnormal")
            and int(attention.get("today") or 0) >= MIN_ATTENTION_ONLY_TODAY
        )
        if attention_only:
            attention_evidence = [
                dict(item) for item in slot["headlines"]
                if item.get("date") == today_iso
            ]
            attention_evidence.sort(key=lambda item: (
                -float(item.get("authority_weight") or 0), item.get("sequence") or 0))
            for evidence in attention_evidence:
                tag = str(evidence.get("attribution") or "name")
                events.append({
                    **evidence,
                    "severity": 1,
                    "severity_label": "关注",
                    "categories": ["异常关注"],
                    "category_hits": {"异常关注": [f'新闻量{attention.get("label") or "异常突增"}']},
                    "category_severity": {"异常关注": 1},
                    "hits": [f'新闻量{attention.get("label") or "异常突增"}'],
                    "disputed": False,
                    "status": "Emerging",
                    "signal_type": "attention",
                    "impact": round(
                        10.0 * float(evidence.get("authority_weight") or 0.65)
                        * ATTRIBUTION_WEIGHTS.get(tag, ATTRIBUTION_WEIGHTS["alias"]), 2),
                })
        if not events:
            continue
        events.sort(key=lambda ev: (-ev["impact"], -ev["severity"], ev["sequence"]))
        sources = {ev["source"] for ev in events if ev["source"]}
        categories = {cat for ev in events for cat in ev["categories"]}
        max_authority_weight = max(float(ev.get("authority_weight") or 0) for ev in events)
        sentiment_raw = sentiment_scores.get(key)
        if isinstance(sentiment_raw, Mapping):
            sentiment = dict(sentiment_raw)
        else:
            sentiment = {"score": _number(sentiment_raw),
                         "sample_n": 1 if _number(sentiment_raw) is not None else 0}
        sentiment_score = _number(sentiment.get("score"))
        change_pct = price_changes.get(key)
        divergence = ""
        caps: List[str] = []
        score_components: Dict[str, Any] = {
            "mode": "attention_only" if attention_only else "risk_event",
            "max_authority_weight": round(max_authority_weight, 2),
            "source_count": len(sources),
            "category_count": len(categories),
            "caps": caps,
        }
        if attention_only:
            z = float(attention.get("z") or 0.0)
            attention_base = 40.0 if z >= 3 else 32.0
            authority_bonus = 4.0 * max_authority_weight
            diversity_bonus = min(4.0, max(0, len(sources) - 1) * 2.0)
            raw_score = attention_base + authority_bonus + diversity_bonus
            score = int(round(min(59.0, raw_score)))
            score_components.update({
                "attention_base": round(attention_base, 2),
                "authority_bonus": round(authority_bonus, 2),
                "source_diversity_bonus": round(diversity_bonus, 2),
                "raw_score": round(raw_score, 2),
            })
            caps.append("纯异常关注信号封顶 59（最高黄色关注）")
            if change_pct is not None:
                if change_pct >= 2:
                    divergence = "价涨/关注度异常并行（不代表负面）"
                elif change_pct <= -2:
                    divergence = "价跌/关注度异常并行（不代表因果）"
                else:
                    divergence = "价格波动未形成显著背离"
        else:
            max_impact = max(ev["impact"] for ev in events)
            source_bonus = min(12.0, max(0, len(sources) - 1) * 4.0)
            category_bonus = min(6.0, max(0, len(categories) - 1) * 3.0)
            attention_bonus = 0.0
            if attention.get("enough"):
                z = float(attention.get("z") or 0.0)
                attention_bonus = (12.0 if z >= 3 else
                                   (8.0 if (z >= 2 or attention.get("triple_mean")) else
                                    (3.0 if z >= 1 else 0.0)))
            divergence_bonus = 0.0
            if change_pct is not None:
                if (change_pct >= 2 and sentiment_score is not None
                        and sentiment_score <= -0.2):
                    divergence = "价涨/情绪偏空空头背离"
                    divergence_bonus = 4.0
                elif change_pct >= 2:
                    divergence = "价涨/风险事件并行（情绪未偏空，不判空头背离）"
                elif change_pct <= -2:
                    divergence = "价格与风险舆情同向走弱"
                else:
                    divergence = "价格波动未形成显著背离"
            raw_score = (max_impact + source_bonus + category_bonus
                         + attention_bonus + divergence_bonus)
            score = int(round(min(100.0, raw_score)))
            score_components.update({
                "primary_event_impact": round(max_impact, 2),
                "source_confirmation_bonus": round(source_bonus, 2),
                "category_breadth_bonus": round(category_bonus, 2),
                "attention_bonus": round(attention_bonus, 2),
                "bearish_divergence_bonus": round(divergence_bonus, 2),
                "raw_score": round(raw_score, 2),
            })
        # 只有行业链弱归因时，不把行业新闻直接升级成单家公司高等级预警。
        sector_only = all(ev["attribution"] == "sector" for ev in events)
        disputed_only = all(ev["disputed"] for ev in events)
        commentary_only = all(ev["authority_tier"] == "评论/社区" for ev in events)
        historical_only = all(ev.get("status") == "Historical" for ev in events)
        emerging_only = all(ev.get("status") == "Emerging" for ev in events)
        if sector_only:
            score = min(score, 59)
            caps.append("仅行业链弱归因，风险指数封顶 59")
        # 未获官方 / 媒体交叉确认的社交、自媒体说法主要作为传播和情绪风险，
        # 不允许仅靠转载广度进入高等级事实预警。
        if commentary_only:
            score = min(score, 59)
            caps.append("仅评论/社区来源，作为传播与情绪风险，风险指数封顶 59")
        if historical_only:
            score = min(score, 49)
            caps.append("仅 Historical 历史事件，风险指数封顶 49")
        elif emerging_only and not attention_only:
            score = min(score, 79)
            caps.append("仅 Emerging 待确认事件，风险指数封顶 79")
        # 全部为澄清/否认/解除语境时只保留观察或黄色关注。
        if disputed_only:
            score = min(score, 49)
            caps.append("全部证据为澄清/否认/解除语境，风险指数封顶 49")
        force_red = any(
            ev["severity"] >= 4 and ev["authority_tier"] == "官方/监管"
            and ev["attribution"] in ("name", "alias") and not ev["disputed"]
            and ev.get("status") == "Current"
            for ev in events
        )
        if force_red:
            score_components["official_critical_force_red"] = True
        score_components["final_score"] = score
        level = _level(score, force_red=force_red)
        action = ("核验异常关注来源与最新公告；当前未检出具体负面事件，"
                  "不依据热度自动交易" if attention_only else _action(level["key"]))
        top_hits = [term for term, _ in Counter(
            term for ev in events for term in ev["hits"]).most_common(6)]
        for ev in events:
            event_id = (ev["date"], ev["title"])
            if ev.get("signal_type") == "attention":
                attention_evidence_ids.add(event_id)
            else:
                concrete_event_ids.add(event_id)
            category_counts.update(ev["categories"])
            authority_counts[ev["authority_tier"]] += 1
        stocks.append({
            "market": info.get("market"), "code": info.get("code"),
            "name": info.get("name"), "key": key,
            "risk_index": score, "level": level, "action": action,
            "events": events[:MAX_EVENTS_PER_STOCK], "_agent_events": events,
            "event_n": len(events),
            "source_n": len(sources), "category_n": len(categories),
            "categories": sorted(categories), "top_hits": top_hits,
            "attention": attention, "window_news_n": len(slot["window_titles"]),
            "today_news_n": len(slot["today_titles"]),
            "change_pct": change_pct, "divergence": divergence,
            "sentiment": sentiment,
            "status_counts": dict(Counter(str(ev.get("status") or "Current") for ev in events)),
            "score_components": score_components,
            "attention_only": attention_only,
            "sector_only": sector_only,
            "disputed_only": disputed_only,
            "commentary_only": commentary_only,
            "historical_only": historical_only,
            "emerging_only": emerging_only,
            "window_hours": int(window_hours),
            "noise_filtered_count": noise_n,
        })

    stocks.sort(key=lambda stock: (-stock["level"]["rank"], -stock["risk_index"],
                                   -stock["event_n"], str(stock["name"])))
    stocks = stocks[:MAX_STOCKS]
    agent_records = []
    for stock in stocks:
        payload = _agent_record(stock, str(date_str), as_of=as_of)
        stock.pop("_agent_events", None)
        stock["agent_payload"] = payload
        agent_records.append(payload)
    level_counts = Counter(stock["level"]["key"] for stock in stocks)
    abnormal_attention_n = sum(
        1 for stock in stocks if (stock.get("attention") or {}).get("abnormal"))
    return {
        "available": bool(stocks),
        "date": date_str,
        "scope": "A股＋港股成交活跃标的",
        "window_hours": int(window_hours),
        "universe_n": len(ah_universe),
        "headline_n": len(rows),
        "noise_filtered_n": noise_n,
        "attribution_n": scanned_attributions,
        "risk_stock_n": len(stocks),
        "risk_event_n": len(concrete_event_ids),
        "attention_evidence_n": len(attention_evidence_ids),
        "abnormal_attention_n": abnormal_attention_n,
        "precise_ts_n": sum(1 for item in rows if str(item.get("ts") or "").strip()),
        "stocks": stocks,
        "agent_schema_version": AGENT_SCHEMA_VERSION,
        "agent_records": agent_records,
        "level_counts": dict(level_counts),
        "category_counts": dict(category_counts),
        "authority_counts": dict(authority_counts),
        "top_categories": category_counts.most_common(5),
        "top_stock": stocks[0] if stocks else None,
        "method": "风险事件词表×来源权威度×归因强度＋跨源确认＋舆情热度异常",
        "score_is_probability": False,
    }


__all__ = [
    "WINDOW_HOURS", "HISTORY_DAYS", "MIN_BASELINE_DAYS", "MIN_ATTENTION_ONLY_TODAY",
    "MAX_STOCKS", "AGENT_SCHEMA_VERSION",
    "SEVERITY_LABELS", "RISK_RULES", "classify_title", "source_authority", "analyze",
]
