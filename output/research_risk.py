#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚠️ 研报 AI 风险点提示 —— 移植自 k-macao/007 的独立栏目，接进本仓库日报。

来源与定位
----------
本栏目原样取自兄弟仓库 **k-macao/007**（`pushplus_deepseek.render_brief_risk_rule()` 与
`foreign_institution_weekly.render_foreign_weekly_rule()` 里那个固定置顶的
「## ⚠️ 研报 AI 风险点提示」板块：机构研报 + 快讯标题 → 风险词表打标 → 3~5 条风险点）。
007 那边是「BofA 牛熊指标 → 风险点提示 → 国外研报 → 其他内容」的简报固定顺序，
这里只搬这一个栏目，并且**排在日报卷首「新手三句话」之后、今日预判之前**
（2026-11-04 用户要求：新手三句话后加入调用 007 的研报 AI 风险点提示）。

取数三路（按用户 2026-11-04 选择：C 两者都要 + A 精简 + B 有大模型就润色）
------------------------------------------------------------------
① 在线（优先）：配置 ``OCTOPUS_007_BASE_URL``（007 的 server_dashboard 地址）时，
   GET ``{base}/api/foreign_weekly?hours=168``，从它的 ``rule_md`` 里解析出
   「⚠️ 研报 AI 风险点提示」那一段的 ``- **[国外投行 · 机构]** 标题（评级）`` 条目；
② 本地（兜底）：未配置端点、端点不可达或返回空 → 用本仓库当次 7 日标题池
   （与政策因子 / 媒体风险同一份 ``news_corpus``）按同一套风险词表 + 机构别名打标；
③ 文风：配置了 ``OCTOPUS_LLM_API_KEY`` / ``DEEPSEEK_API_KEY`` 等任一大模型 Key 时，
   把规则挑出的风险点交给大模型写一句「定调」+「关注点」（只润色文案，不改事实）；
   未配置或调用失败 → 用确定性规则文案，脚注里如实标注「规则兜底」。

诚实边界
--------
* 风险点是**标题级线索**，不是事实定论，也不是概率；不输出涨跌概率、不给买卖点；
* 每条风险点都带机构、日期与来源，AI 不许新增机构、不许引入标题里没有的数字；
* 窗口内一条风险线索都没有 → 栏目照常出现并写明「本期未检出」，绝不静默消失；
* 纯标准库实现（复用 hk_seven_day 的 OpenAI 兼容调用与护栏），不新增第三方依赖。
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

CST = timezone(timedelta(hours=8))

# ------------------------------------------------------------ 常量
# 窗口：007 原栏用一周（168h）。但本仓库的标题池以快讯 / 媒体稿为主，机构研报 7 日内
# 经常一条研报体裁的标题都没有（2026-11-04 实测：168h 内 0 条，360h 内才凑够 3 条），
# 因此本地兜底放宽到 15 日（= 政策因子同一窗口 360h），在线 007 仍按其 168h 口径取。
WINDOW_HOURS = 360
REMOTE_HOURS = 168                  # 请求 007 时仍用一周，与它自己的栏目口径一致
MAX_POINTS = 5                      # 精简版面：最多 5 条风险点
MIN_POINTS = 3                      # 尽量凑够 3 条；不够就如实少给
TIMEOUT = 20
REMOTE_TIMEOUT = 15
USER_AGENT = "octopus-ai-daily/1.0 (+research-risk)"
SECTION_TITLE = "研报 AI 风险点提示"
CAPTION = "007 研报风控栏目 · 机构研报与快讯标题 · 风险线索非概率"
DISCLAIMER = "风险点为标题级线索，需回看研报原文；规则打分不是概率，不构成投资建议。"

ENV_007_BASE = ("OCTOPUS_007_BASE_URL", "OCTOPUS_007_BASE", "RESEARCH_007_BASE_URL")
ENV_007_TIMEOUT = "OCTOPUS_007_TIMEOUT"
ENABLED_ENV = "OCTOPUS_RESEARCH_RISK"

# ------------------------------------------------------------ 机构名单
# 只认「研报主体」：外资大行 + 中资券商。别名尽量取机构全称片段，避免误伤站名
# （如「中金在线」这类资讯站名，故 CICC 只收「中金公司 / 中金研究」，不收裸「中金」）。
INSTITUTIONS = (
    {"name": "高盛", "intl": True, "aliases": ["高盛", "Goldman Sachs", "Goldman"]},
    {"name": "摩根士丹利", "intl": True, "aliases": ["摩根士丹利", "大摩", "Morgan Stanley"]},
    {"name": "摩根大通", "intl": True, "aliases": ["摩根大通", "小摩", "JPMorgan", "J.P. Morgan"]},
    {"name": "美银", "intl": True, "aliases": ["美银", "BofA", "Bank of America"]},
    {"name": "花旗", "intl": True, "aliases": ["花旗", "Citi", "Citigroup"]},
    {"name": "瑞银", "intl": True, "aliases": ["瑞银", "UBS"]},
    {"name": "德意志银行", "intl": True, "aliases": ["德意志银行", "德银", "Deutsche Bank"]},
    {"name": "巴克莱", "intl": True, "aliases": ["巴克莱", "Barclays"]},
    {"name": "汇丰", "intl": True, "aliases": ["汇丰", "HSBC"]},
    {"name": "晨星", "intl": True, "aliases": ["晨星", "Morningstar"]},
    {"name": "伯恩斯坦", "intl": True, "aliases": ["伯恩斯坦", "Bernstein"]},
    {"name": "野村", "intl": True, "aliases": ["野村", "Nomura"]},
    {"name": "中金公司", "intl": False, "aliases": ["中金公司", "中金研究", "CICC"]},
    {"name": "中信证券", "intl": False, "aliases": ["中信证券", "中信建投", "CITIC"]},
    {"name": "华泰证券", "intl": False, "aliases": ["华泰证券", "华泰研究"]},
    {"name": "国泰海通", "intl": False, "aliases": ["国泰君安", "国泰海通", "海通证券"]},
    {"name": "招商证券", "intl": False, "aliases": ["招商证券"]},
    {"name": "广发证券", "intl": False, "aliases": ["广发证券"]},
)
INSTITUTION_NAMES = tuple(it["name"] for it in INSTITUTIONS)

# ------------------------------------------------------------ 词表
# 风险方向（007 的 caution 词表 + 本仓库研报语料补充）：命中即视为「风险线索」
CAUTION_RE = re.compile(
    r"下调|减持|卖出|观望|谨慎|风险|承压|回调|警告|分歧|放缓|通胀|衰退|萎缩|违约|爆雷|"
    r"立案|调查(?!显示|报告|丨)|处罚|问询|警示|退市|停牌|商誉减值|低于预期|不及预期|毛利率下滑|"
    r"裁员|关停|减产|亏损|下调目标价|降级|看空|做空|空头|"
    r"underweight|sell|neutral|downgrade|cut|risk|headwind|warning|miss|recall",
    re.I)
# 噪音词表：行情播报 / 公告摘要 / 资金通道数据 / 人事与分红这类「不是研报观点」的条目，
# 命中即整条剔除。不做这一步，本地兜底会挑出一堆「机构席位卖出…龙虎榜」的流水账。
NOISE_RE = re.compile(
    r"龙虎榜|席位|公告内容摘要|预披露|股东.*减持|减持股份|港股通|沪深股通|净买入|净卖出|"
    r"调仓|任职资格|人事变动|分红|回购|股权激励|限售|解禁|直播|带货|中签|招股|"
    r"涨停|跌停|停复牌|复牌|开市起|盘前|盘中|午间|早盘|尾盘|热搜|股价异动|"
    r"经参调查丨|ETF|基金份额|溢折率",
    re.I)
# 研报体裁词：有机构署名的排第一档，其次是「像研报观点」的（评级 / 目标价 / 策略 / 分析师…
# 再其次是其他风险标题。三档合起来够 3 条就停，版面不会被 C 档水位灌满。
RESEARCH_HINT_RE = re.compile(
    r"评级|目标价|研报|调降|降级|展望|策略|周报|研究部|分析师|策略师|首席|投行|券商|"
    r"research|rating|target|outlook|downgrade|initiat|warns|warning",
    re.I)
# 反证词：同一句里出现「上调 / 买入 / 超预期」等强多头措辞且无风险词的，不算风险线索
_BULL_RE = re.compile(r"上调|增持|买入|超配|看好|超预期|创历史新高|upgrade|overweight|buy|beat", re.I)
# 研报体裁：标题像研报 / 评级 / 目标价的优先（纯快讯也能进，但排序靠后）
_RESEARCH_RE = re.compile(r"研报|评级|目标价|策略周报|展望|research|rating|target|outlook|initiat", re.I)

# 风险类别：按顺序匹配，先命中先归类（顺序 = 严重度直觉排序）
CATEGORIES = (
    ("评级与目标价", re.compile(r"下调|降级|评级|目标价|underweight|downgrade|cut|减持|卖出", re.I)),
    ("合规与监管", re.compile(r"立案|调查|处罚|问询|警示|违规|退市|停牌|诉讼|罚|probe|inquir|fine", re.I)),
    ("业绩与基本面", re.compile(r"低于预期|不及预期|亏损|下滑|萎缩|违约|爆雷|减值|裁员|关停|减产|miss", re.I)),
    ("宏观与利率", re.compile(r"通胀|利率|加息|缩表|衰退|放缓|CPI|PPI|美联储|央行|yield|inflation|recession", re.I)),
    ("资金与情绪", re.compile(r"资金流|净流出|抛售|空头|做空|分歧|观望|谨慎|selloff|outflow|short", re.I)),
    ("行业与政策", re.compile(r"关税|制裁|出口管制|补贴|监管|政策|tariff|sanction|ban|subsid", re.I)),
)
CATEGORY_NAMES = tuple(name for name, _ in CATEGORIES)

ALIAS_INDEX = [(it["name"], it["intl"], a.lower())
               for it in INSTITUTIONS for a in it["aliases"]]
INTL_NAMES = {it["name"] for it in INSTITUTIONS if it["intl"]}
LOCAL_NAMES = {it["name"] for it in INSTITUTIONS if not it["intl"]}


# ------------------------------------------------------------ 小工具
def is_enabled():
    return str(os.environ.get(ENABLED_ENV, "1")).strip().lower() not in ("0", "false", "no")


def _clean_title(text):
    """去掉站点后缀 / 电头：避免「中金在线」这类站名被当成机构。"""
    t = str(text or "").strip()
    t = re.sub(r"[_|｜]\s*(?:股市直播|市场|财经|新闻)\s*$", "", t)
    t = re.sub(r"\s*[-–—]\s*[^-–—]{2,12}(?:网|在线|财经|新闻|时报|日报|官网)\s*$", "", t)
    t = re.sub(r"^(?:\s*[【\[](?:快讯|研报|券商聚焦|机构观点)[】\]]\s*)", "", t)
    return t.strip()


def normalize_title(text):
    """去重用的归一化标题：只留中日韩字与字母数字。"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(text or "").lower())


def parse_datetime(value):
    """把多种时间写法揉成带时区的 datetime；解析不出来返回 None。"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=CST)
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%m-%d %H:%M"):
        try:
            dt = datetime.strptime(text[:len(datetime.now().strftime(fmt))], fmt)
            return dt.replace(tzinfo=CST) if dt.year > 1900 else dt.replace(
                year=datetime.now(CST).year, tzinfo=CST)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=CST)
    except ValueError:
        return None


def match_institution(title):
    """标题 → (机构名, 是否外资)；没命中返回 (\"\", False)。"""
    low = _clean_title(title).lower()
    for name, intl, alias in ALIAS_INDEX:
        if alias in low:
            return name, intl
    return "", False


def classify(title):
    """风险类别：按 CATEGORIES 顺序取第一个命中项，全不命中归「其他」。"""
    text = _clean_title(title)
    for name, pattern in CATEGORIES:
        if pattern.search(text):
            return name
    return "其他"


def extract_rating(title):
    """从标题里取评级词（006/007 同款正则的收敛版）。"""
    m = re.search(r"(增持|买入|中性|减持|卖出|跑赢行业|跑输行业|"
                  r"overweight|underweight|buy|sell|neutral|outperform|underperform)",
                  _clean_title(title), re.I)
    return m.group(1) if m else ""


def is_risk_title(title):
    """风险线索判定：命中风险词，且不是「上调 / 买入」这类纯多头口径。"""
    text = _clean_title(title)
    if not CAUTION_RE.search(text):
        return False
    if _BULL_RE.search(text) and not re.search(r"下调|减持|卖出|风险|承压|downgrade|underweight", text, re.I):
        return False
    return True


# ------------------------------------------------------------ ① 在线：007 端点
def remote_base():
    for name in ENV_007_BASE:
        value = str(os.environ.get(name) or "").strip().rstrip("/")
        if value:
            return value, name
    return "", ""


def _http_json(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def parse_rule_md(markdown):
    """从 007 的 rule_md 里抠出风险点条目。

    007 的格式（`foreign_institution_weekly.render_foreign_weekly_rule`）：
        ## ⚠️ 研报 AI 风险点提示
        - **[国外投行 · 高盛]** 下调某某评级至中性（neutral）
    只认这一段里的列表项，别的段落（国外研报明细 / 数据新鲜度）一律不看。
    """
    points = []
    inside = False
    for raw in str(markdown or "").splitlines():
        line = raw.strip()
        if line.startswith("##"):
            inside = "研报 AI 风险点提示" in line
            continue
        if not inside or not line.startswith(("-", "*")):
            continue
        m = re.match(r"^[-*]\s*\*\*\[([^\]]+)\]\*\*\s*(.+)$", line)
        if not m:
            continue
        tag, body = m.group(1), m.group(2).strip()
        institution = ""
        for part in re.split(r"[·•]\s*", tag):
            part = part.strip()
            if part in INSTITUTION_NAMES:
                institution = part
        if not institution:
            institution, _ = match_institution(body)
        points.append({
            "institution": institution,
            "intl": institution in INTL_NAMES,
            "title": _clean_title(re.sub(r"（[^）]*）\s*$", "", body))[:120],
            "rating": extract_rating(body),
            "category": classify(body),
            "date": "",
            "source": "007 在线",
        })
    return points


def fetch_remote(hours=REMOTE_HOURS):
    """在线取 007 的风险点。返回 {"ok", "points", "url", "reason"}；任何失败都不抛。"""
    base, env_name = remote_base()
    if not base:
        return {"ok": False, "points": [], "url": "", "reason": "未配置 007 端点"}
    url = f"{base}/api/foreign_weekly?{urlencode({'hours': int(hours)})}"
    try:
        timeout = int(str(os.environ.get(ENV_007_TIMEOUT) or REMOTE_TIMEOUT))
    except (TypeError, ValueError):
        timeout = REMOTE_TIMEOUT
    try:
        payload = _http_json(url, timeout=max(3, min(60, timeout)))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "points": [], "url": url, "reason": f"HTTP {exc.code}", "env": env_name}
    except Exception as exc:                       # noqa: BLE001 网络/解析异常一律降级
        return {"ok": False, "points": [], "url": url,
                "reason": f"{type(exc).__name__}: {str(exc)[:80]}", "env": env_name}
    if not isinstance(payload, dict) or not payload.get("ok"):
        reason = str((payload or {}).get("error") or "端点返回 ok=false") if isinstance(payload, dict) else "返回不是对象"
        return {"ok": False, "points": [], "url": url, "reason": reason[:100], "env": env_name}
    points = parse_rule_md(payload.get("rule_md") or payload.get("teaser_md") or "")
    return {"ok": bool(points), "points": points, "url": url, "env": env_name,
            "reason": "" if points else "端点未返回风险点条目",
            "count": int(payload.get("count") or 0)}


# ------------------------------------------------------------ ② 本地：标题池
def collect_local(items, anchor_dt, hours=WINDOW_HOURS):
    """当次标题池 → 风险点，按体裁分三档（档位越小越像研报观点）。

    tier 0：标题带机构署名（高盛 / 中信证券 …）；
    tier 1：带研报体裁词（评级 / 目标价 / 策略 / 分析师 …）；
    tier 2：其余风险标题（亏损、立案、停牌…）——只在 0/1 档不够 3 条时补位。
    噪音（龙虎榜流水账、公告摘要、行情播报、基金份额…）直接剔除。
    """
    cutoff = anchor_dt - timedelta(hours=hours)
    seen, out = set(), []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        title = _clean_title(item.get("title"))
        if len(title) < 8 or NOISE_RE.search(title):
            continue
        dt = parse_datetime(item.get("ts")) or parse_datetime(item.get("date"))
        if dt is not None and not (cutoff <= dt <= anchor_dt + timedelta(hours=1)):
            continue
        if not is_risk_title(title):
            continue
        institution, intl = match_institution(title)
        key = normalize_title(title)
        if not key or key in seen:
            continue
        seen.add(key)
        tier = 0 if institution else (1 if RESEARCH_HINT_RE.search(title) else 2)
        out.append({
            "institution": institution,
            "intl": intl,
            "title": title[:120],
            "rating": extract_rating(title),
            "category": classify(title),
            # 与政策因子同口径：日期取标题真实发布时间，缺失则用采集日
            "date": (dt.strftime("%Y-%m-%d") if dt else str(item.get("date") or "")[:10]),
            "source": item.get("source") or item.get("section") or "公开来源",
            "tier": tier,
        })
    return out


# ------------------------------------------------------------ ③ 合并与排序
def _rank(point):
    """排序：体裁档（署名 > 研报观点 > 其他风险）> 外资机构 > 类别严重度 > 日期新。

    日期是最后一档且只做「同日稳定」用，最新一条永远排在本档第一行。
    """
    cat = point.get("category") or "其他"
    try:
        cat_rank = CATEGORY_NAMES.index(cat)
    except ValueError:
        cat_rank = len(CATEGORY_NAMES)
    tier = point.get("tier")
    if tier is None:
        tier = 0 if point.get("institution") else 1
    return (
        int(tier),
        0 if point.get("intl") else 1,
        cat_rank,
        "".join(chr(0x10FFFF - ord(c)) for c in str(point.get("date") or "")) or "~",
        normalize_title(point.get("title")),
    )


def merge_points(remote_points, local_points, limit=MAX_POINTS, min_points=MIN_POINTS):
    """在线 + 本地并集去重后按档位取前 limit 条。

    在线 007 的条目直接算 tier 0/1（它本来就是研报栏目）；本地条目用 collect_local 给的档位。
    0/1 档凑够 min_points 就不再让 2 档水位灌进来——否则「亏损 / 停牌」这类个股流水账
    会挤掉真正的研报观点。
    """
    merged, seen = [], set()
    for bucket in (remote_points or [], local_points or []):
        for point in bucket:
            key = normalize_title(point.get("title"))
            if not key or key in seen:
                continue
            seen.add(key)
            item = dict(point)
            item.setdefault("tier", 0 if item.get("institution") else 1)
            merged.append(item)
    merged.sort(key=_rank)
    premium = [p for p in merged if int(p.get("tier") or 0) <= 1]
    if len(premium) >= min_points:
        return premium[:limit]
    return merged[:limit]


def category_counts(points):
    counts = {}
    for point in points or []:
        name = point.get("category") or "其他"
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


# ------------------------------------------------------------ ④ 大模型：只润色文案
# 提示词要求严格 JSON；事实（机构 / 标题 / 日期）由调用方另行渲染，模型只写定调与关注点，
# 因此「编造一条不存在的研报」在结构上就落不了地。
SYSTEM_PROMPT = (
    "你是中文财经日报的风控编辑。用户给你一批来自券商研报与财经快讯的**标题级风险线索**，"
    "你要写一句定调 + 一句关注点。硬性要求：\n"
    "1) 只依据给你的线索，不得新增机构、研报、数字、日期或事件；\n"
    "2) 不预测涨跌、不给点位与仓位、不使用「一定/必然/保证/无风险」等绝对化措辞；\n"
    "3) 定调 ≤ 40 个汉字，关注点 ≤ 60 个汉字，中文书面语，不用 markdown；\n"
    "4) 只输出 JSON：{\"summary\": \"...\", \"focus\": \"...\"}，不要任何额外文字。"
)


def build_context(points, market=None):
    """给大模型的闭合输入：只含已检出的线索与一句盘面方向（都不含未来信息）。"""
    return {
        "window_hours": WINDOW_HOURS,
        "risk_points": [{"institution": p.get("institution") or "未署名",
                         "category": p.get("category") or "其他",
                         "title": p.get("title") or "",
                         "date": p.get("date") or ""} for p in points[:MAX_POINTS]],
        "market_direction": str((market or {}).get("direction") or "")[:40],
        "category_counts": category_counts(points),
    }


def _numbers(text):
    return set(re.findall(r"\d+(?:\.\d+)?", str(text or "")))


def polish_with_llm(points, market=None, config=None):
    """大模型写一句定调 + 关注点。返回 {"ok", "summary", "focus", "model", "reason"}。"""
    if not points:
        return {"ok": False, "summary": "", "focus": "", "reason": "无风险线索，跳过润色"}
    try:
        import hk_seven_day as hk7
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "summary": "", "focus": "", "reason": f"LLM 模块不可用：{exc}"}
    cfg = config if config is not None else hk7.llm_config()
    if not cfg.get("enabled"):
        return {"ok": False, "summary": "", "focus": "", "reason": "未配置大模型 Key"}
    context = build_context(points, market)
    context["_system_prompt"] = SYSTEM_PROMPT
    trace = {}
    payload, err = hk7.call_llm(cfg, context, trace=trace,
                                models=[cfg.get("model")] if cfg.get("model") else None)
    if payload is None:
        return {"ok": False, "summary": "", "focus": "", "reason": str(err or "调用失败")[:120]}
    summary = str(payload.get("summary") or "").strip()
    focus = str(payload.get("focus") or "").strip()
    if not summary:
        return {"ok": False, "summary": "", "focus": "", "reason": "模型未给出定调"}
    # 护栏：绝对化措辞 / 长度 / 凭空数字 / 凭空机构 —— 命中任意一条就退回规则文案
    problems = []
    for label, text, limit in (("定调", summary, 60), ("关注点", focus, 100)):
        if hk7._FORBIDDEN_RE.search(text):
            problems.append(f"{label}含绝对化措辞")
        if len(text) > limit:
            problems.append(f"{label}超长({len(text)}字)")
    allowed_numbers = set()
    for point in points[:MAX_POINTS]:
        allowed_numbers |= _numbers(point.get("title")) | _numbers(point.get("date"))
    stray = _numbers(summary) | _numbers(focus)
    if stray - allowed_numbers:
        problems.append(f"{label if False else '文案'}新增了线索里没有的数字：{'、'.join(sorted(stray - allowed_numbers))[:40]}")
    for name in re.findall(r"[\u4e00-\u9fffA-Za-z]{2,10}(?:证券|高盛|大摩|小摩|花旗|瑞银|汇丰|野村)", summary + focus):
        if name not in INSTITUTION_NAMES and not any(name in n or n in name for n in INSTITUTION_NAMES):
            problems.append(f"文案提到未在名单内的机构：{name}")
            break
    if problems:
        return {"ok": False, "summary": "", "focus": "", "reason": "；".join(problems[:3]),
                "model": trace.get("model") or ""}
    return {"ok": True, "summary": summary, "focus": focus,
            "model": trace.get("model") or cfg.get("model") or "", "reason": ""}


# ------------------------------------------------------------ ⑤ 规则定调（兜底）
def rule_summary(points, market=None):
    """无大模型时的确定性定调：由类别分布与机构构成直接合成，可复现。"""
    if not points:
        return ("本期窗口内未检出研报风险线索：机构研报与快讯标题里没有触发下调 / 减持 / "
                "监管或基本面警示的条目"), "继续观察评级与目标价变动即可"
    counts = category_counts(points)
    top = "、".join(f"{k}{v}条" for k, v in list(counts.items())[:2])
    intl_n = sum(1 for p in points if p.get("intl"))
    local_n = sum(1 for p in points if p.get("institution") and not p.get("intl"))
    signed = intl_n + local_n
    if points[0].get("category") == "评级与目标价":
        tone = "机构口径偏谨慎，下调与降级集中在评级端"
    elif points[0].get("category") == "宏观与利率":
        tone = "风险主要来自宏观与利率预期"
    elif points[0].get("category") == "合规与监管":
        tone = "监管与合规事项是本期最需要盯的线"
    else:
        tone = "风险线索偏散，未见单一方向集中发酵"
    direction = str((market or {}).get("direction") or "").strip()
    tail = f"；与盘面「{direction}」的方向对照看" if direction else ""
    summary = f"{tone}（{top}）"
    focus = (f"署名线索 {signed} 条（外资 {intl_n} / 中资 {local_n}），"
             f"按标题线索先做防守清单，不当作事实定论") + tail
    return summary[:60], focus[:100]


# ------------------------------------------------------------ ⑥ 入口
def build(data=None, date_str=None, news_corpus=None, llm_config=None,
          market=None, allow_network=True, now=None):
    """构建「研报 AI 风险点提示」结果（渲染在 pipeline，本函数只产出结构化事实）。

    返回字典字段（渲染层只用这些，不再二次计算）：
      available / points / summary / focus / tone_source / summary_source
      remote{ok,url,reason} / local_n / window_hours / categories / newest_date
      llm{ok,model,reason} / enabled
    """
    anchor = now or datetime.now(CST)
    text = str(date_str or "").strip()
    if len(text) == 8 and text.isdigit():
        try:
            anchor = datetime.strptime(text, "%Y%m%d").replace(hour=23, minute=59, tzinfo=CST)
        except ValueError:
            pass
    items = []
    if isinstance(news_corpus, dict):
        items = list(news_corpus.get("items") or [])
    if not items and data is not None:
        try:
            import pipeline as _pipeline
            items = _pipeline._collect_headline_items(data, anchor.strftime("%Y-%m-%d"))
        except Exception:                          # noqa: BLE001 兜底失败就按空样本处理
            items = []
    remote = (fetch_remote() if allow_network
              else {"ok": False, "points": [], "url": "", "reason": "本次禁用在线取数"})
    local = collect_local(items, anchor)
    points = merge_points(remote.get("points") or [], local)
    summary, focus = rule_summary(points, market)
    llm = {"ok": False, "model": "", "reason": "未启用"}
    tone_source = "规则"
    if points and (llm_config is None or llm_config.get("enabled")):
        llm = polish_with_llm(points, market, llm_config)
        if llm.get("ok"):
            summary, focus = llm["summary"], (llm.get("focus") or focus)
            tone_source = "AI"
    # 每条线索补齐「评分口径」用的可读字段，渲染层不再算
    enriched = []
    for point in points:
        item = dict(point)
        item.pop("tier", None)
        item["institution"] = item.get("institution") or "未署名"
        item["category"] = item.get("category") or "其他"
        item["date"] = str(item.get("date") or "")[:10]
        enriched.append(item)
    dates = [p["date"] for p in enriched if p["date"]]
    return {
        "enabled": is_enabled(),
        "available": bool(enriched),
        "points": enriched,
        "summary": summary,
        "focus": focus,
        "tone_source": tone_source,
        "summary_source": "远程 007 + 本地规则" if (remote.get("ok") and local) else
                          ("007 在线" if remote.get("ok") else "本地规则"),
        "remote": {k: remote.get(k) for k in ("ok", "url", "reason", "env", "count") if k in remote},
        "local_n": len(local),
        "window_hours": WINDOW_HOURS,
        "categories": category_counts(enriched),
        "newest_date": max(dates) if dates else "",
        "llm": llm,
        "corpus_n": len(items),
    }


def selftest():
    """离线自检：词表 / 机构识别 / 去重排序 / 007 报文解析 / 文案护栏，全部不触网。"""
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    check("风险词表命中下调", is_risk_title("花旗：下调中广核电力目标价，评级降至中性"))
    check("纯多头标题不算风险", not is_risk_title("高盛：上调英伟达目标价至 220 美元，维持买入"))
    check("机构识别（外资）", match_institution("Morgan Stanley：下调半导体板块评级") == ("摩根士丹利", True))
    check("站名不当机构（中金在线）", match_institution("港股概念追踪_股市直播_市场 - 中金在线")[0] == "")
    check("类别归类（评级）", classify("大摩下调目标价至 100 港元") == "评级与目标价")
    check("类别归类（合规）", classify("某公司遭立案调查") == "合规与监管")
    md = ("## 🧭 美银牛熊指标\n- 不要把这条当风险点\n\n"
          "## ⚠️ 研报 AI 风险点提示\n\n"
          "- **[国外投行 · 高盛]** 下调某车企评级至中性（neutral）\n"
          "- **[国外投行 · 瑞银]** 中国互联网板块盈利预期存在下修风险\n\n"
          "## 🏛 国外研报\n- 明细条目\n")
    parsed = parse_rule_md(md)
    check("007 报文只取风险段", len(parsed) == 2 and parsed[0]["institution"] == "高盛", str(len(parsed)))
    check("007 报文带类别与评级", parsed[0]["category"] == "评级与目标价" and parsed[0]["rating"] == "中性")
    merged = merge_points(parsed, [{"title": "下调某车企评级至中性", "category": "评级与目标价"}])
    check("在线 + 本地去重", len(merged) == 2, str(len(merged)))
    now = datetime(2026, 11, 4, 12, tzinfo=CST)
    local = collect_local([
        {"title": "高盛：下调某车企评级至中性", "ts": "2026-11-03 10:00", "source": "研报"},
        {"title": "花旗：上调目标价", "ts": "2026-11-03 11:00", "source": "研报"},
        {"title": "瑞银：看好明年行情", "ts": "2026-10-01 11:00", "source": "研报"},
    ], now)
    check("本地只收风险且在窗口内", len(local) == 1, str([x["title"] for x in local]))
    summary, focus = rule_summary(local, {"direction": "偏空"})
    check("规则定调可复现", "评级与目标价" in summary and "偏空" in focus, summary)
    check("空样本不编造", "未检出" in rule_summary([])[0])
    bad = polish_with_llm([], None, {})       # 无线索不调用
    check("无线索不调大模型", bad["ok"] is False)
    banned = "一定上涨"
    check("绝对化措辞拦截", bool(__import__("hk_seven_day")._FORBIDDEN_RE.search(banned)))
    return checks


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="研报 AI 风险点提示（移植自 k-macao/007）")
    parser.add_argument("--selftest", action="store_true", help="离线自检后退出")
    parser.add_argument("--json", action="store_true", help="打印构建结果 JSON")
    parser.add_argument("--no-network", action="store_true", help="禁用 007 在线取数")
    parser.add_argument("--date", default="", help="报告日 YYYYMMDD")
    args = parser.parse_args(argv)
    if args.selftest:
        failed = 0
        for name, ok, detail in selftest():
            print(f"  {'✅' if ok else '❌'} {name}{('：' + detail) if detail and not ok else ''}")
            failed += 0 if ok else 1
        print(("✅ 研报 AI 风险点提示自检通过" if not failed else f"❌ {failed} 项失败"))
        return 0 if not failed else 1
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_history.json")
    corpus = {"items": []}
    try:
        with open(path, encoding="utf-8") as fh:
            corpus = json.load(fh)
    except (OSError, ValueError):
        pass
    result = build(date_str=args.date, news_corpus=corpus, allow_network=not args.no_network)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    else:
        print(f"⚠️ {SECTION_TITLE} · {'有线索' if result['available'] else '未检出'} · "
              f"{result['summary_source']} · 定调来源 {result['tone_source']}")
        print(f"  {result['summary']}")
        print(f"  {result['focus']}")
        for point in result["points"]:
            print(f"  · [{point['category']}] {point['institution']} {point['date']} "
                  f"{point['title'][:40]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
