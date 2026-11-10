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

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
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
RUN_007_TIMEOUT = 210
USER_AGENT = "octopus-ai-daily/1.0 (+research-risk)"
SECTION_TITLE = "研报 AI 风险点提示"
SECTION_HEADING_MD = "## ⚠️ 研报 AI 风险点提示"   # 007 原文段首行（逐字）

DEFAULT_007_REPO = "k-macao/007"
DEFAULT_007_BRANCH = "main"
ENV_007_REPO = "OCTOPUS_007_REPO"
ENV_007_BRANCH = "OCTOPUS_007_BRANCH"
ENV_007_BRIEF_URL = ("OCTOPUS_007_BRIEF_URL",)
ENV_007_GH_TOKEN = ("OCTOPUS_007_GH_TOKEN", "GH_TOKEN_007", "GITHUB_TOKEN_007", "GH_TOKEN")
ENV_007_BASE = ("OCTOPUS_007_BASE_URL", "OCTOPUS_007_BASE", "RESEARCH_007_BASE_URL")
ENV_007_TIMEOUT = "OCTOPUS_007_TIMEOUT"
ENV_007_AUTO_RUN = "OCTOPUS_007_AUTO_RUN"
ENV_007_LOCAL_DIR = "OCTOPUS_007_LOCAL_DIR"
ENV_007_RUN_TIMEOUT = "OCTOPUS_007_RUN_TIMEOUT"
ENABLED_ENV = "OCTOPUS_RESEARCH_RISK"

_007_STRIP_ENV_VARS = (
    "PUSHPLUS_TOKEN",
    "PUSHPLUS_TOPIC",
    "WECOM_KEY",
    "SERVERCHAN_SENDKEY",
    "PUSH_TITLE",
    "PUSH_STATE_PATH",
)

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
    r"受托管理|受托事务|可转债|"
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
    # 「汇丰控股 / HSBC Holdings」是股票主体而非汇丰研报机构署名
    low_masked = re.sub(r"汇丰控股|hsbc\s+holdings", "", low)
    for name, intl, alias in ALIAS_INDEX:
        haystack = low_masked if name == "汇丰" else low
        if alias in haystack:
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


# ------------------------------------------------------------ 007 原文口径（逐字复刻）
# 下面三件套与 007 推送脚本 pushplus_deepseek.py 同源，本地兜底生成「同样栏目文字」时
# 必须用同一把尺：情绪词典 score_text（POS_WORDS / NEG_WORDS / 0.12 阈值）、
# 快讯聚合锚点公式（50 + 45 × clamp(mean×3)），以及 _mk_item 的评级提取正则。
_POS_WORDS_007 = ["利好", "上涨", "大涨", "增长", "中标", "突破", "创新高", "创纪录",
                  "回购", "预增", "超预期", "盈利", "签约", "订单", "扩产", "获批",
                  "分红", "surge", "rally", "beat", "upgrade", "record", "profit",
                  "bullish", "soar", "win", "growth", "boost"]
_NEG_WORDS_007 = ["利空", "下跌", "大跌", "亏损", "减持", "违约", "下调", "预警",
                  "预亏", "低于预期", "处罚", "诉讼", "削减", "延期", "停产",
                  "plunge", "miss", "downgrade", "loss", "lawsuit", "cut", "bearish",
                  "slump", "drop", "warning", "fraud"]
_RATING_RE_007 = re.compile(
    r"(增持|买入|中性|减持|卖出|上调|下调|overweight|underweight|buy|sell|neutral|outperform)",
    re.I)


def _count_word_007(low, word):
    """英文词按词边界匹配（防止 win 命中 downwind），中文按子串——007 同步实现。"""
    if word.isascii():
        return len(re.findall(r"\b" + re.escape(word.lower()) + r"\b", low))
    return low.count(word)


def score_text_007(text):
    """007 推送脚本的词典法情绪打分：返回 (score∈[-1,1], 标签, 置信度∈[0,1])。逐字复刻。"""
    low = str(text or "").lower()
    pos = sum(_count_word_007(low, w) for w in _POS_WORDS_007)
    neg = sum(_count_word_007(low, w) for w in _NEG_WORDS_007)
    total = pos + neg
    score = 0.0 if total == 0 else max(-1.0, min(1.0, (pos - neg) / total))
    label = "利好" if score > 0.12 else ("利空" if score < -0.12 else "中性")
    return round(score, 2), label, round(min(1.0, total / 4), 2)


def extract_rating_007(title):
    """007 _mk_item 的评级提取正则：原文条目尾注「（评级）」就用这一把尺。"""
    m = _RATING_RE_007.search(_clean_title(title))
    return m.group(1) if m else ""


def is_risk_title(title):
    """风险线索判定：命中风险词，且不是「上调 / 买入」这类纯多头口径。"""
    text = _clean_title(title)
    if not CAUTION_RE.search(text):
        return False
    if _BULL_RE.search(text) and not re.search(r"下调|减持|卖出|风险|承压|downgrade|underweight", text, re.I):
        return False
    return True


# ------------------------------------------------------------ ① 在线：007 最新一篇与同源生成
_RISK_HEADING_RE = re.compile(r"研报\s*AI\s*风险点提示")
_TOP_HEADING_RE = re.compile(r"^#{1,2}(?!#)\s+\S")
_LOG_TS_RE = re.compile(r"^\ufeff?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s?")


def _first_env(*names):
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value, name
    return "", ""


def _remote_timeout():
    try:
        timeout = int(str(os.environ.get(ENV_007_TIMEOUT) or REMOTE_TIMEOUT))
    except (TypeError, ValueError):
        timeout = REMOTE_TIMEOUT
    return max(3, min(60, timeout))


def _007_repo():
    repo = str(os.environ.get(ENV_007_REPO) or DEFAULT_007_REPO).strip().strip("/")
    return repo or DEFAULT_007_REPO


def _007_branch():
    branch = str(os.environ.get(ENV_007_BRANCH) or DEFAULT_007_BRANCH).strip()
    return branch or DEFAULT_007_BRANCH


def remote_base():
    for name in ENV_007_BASE:
        value = str(os.environ.get(name) or "").strip().rstrip("/")
        if value:
            return value, name
    return "", ""


def _http_bytes(url, timeout=TIMEOUT, headers=None):
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_text(url, timeout=TIMEOUT, headers=None):
    return _http_bytes(url, timeout=timeout, headers=headers).decode("utf-8", "replace")


def _http_json(url, timeout=TIMEOUT, headers=None):
    return json.loads(_http_text(url, timeout=timeout, headers=headers))


def _extract_brief_from_007_log(log_text):
    """从 007 的运行日志里提取「📝 生成的内容：」之后一对 `----` 分隔线间的完整 Markdown。

    支持剥离 GitHub Actions 每行前缀的 UTC 时间戳；若输入本身就是纯 Markdown
    （无「📝 生成的内容：」标记），原样返回剥离时间戳后的文本。
    """
    lines = [_LOG_TS_RE.sub("", raw.rstrip("\r")) for raw in str(log_text or "").splitlines()]
    marker_idx = -1
    for idx, line in enumerate(lines):
        if "📝 生成的内容：" in line or "生成的内容：" in line:
            marker_idx = idx
    if marker_idx < 0:
        return "\n".join(lines).strip()
    i = marker_idx + 1
    while i < len(lines) and not re.match(r"^-{40,}$", lines[i].strip()):
        i += 1
    if i >= len(lines):
        return "\n".join(lines[marker_idx + 1:]).strip()
    i += 1
    body = []
    while i < len(lines) and not re.match(r"^-{40,}$", lines[i].strip()):
        body.append(lines[i])
        i += 1
    return "\n".join(body).strip()


def extract_section_md(markdown):
    """从 007 的正文或 rule_md 里**原样**抠出「## ⚠️ 研报 AI 风险点提示」整段原文。

    从段首标题行起、到下一个同级/一级标题（``#`` / ``##``，不含 ``###`` 小节标题）前为止，
    逐行一字不改（只去掉段首尾空行与段尾 ``---`` 分隔线）；段里没有条目、
    只有空样本段落时同样照单全收——那也是 007 推送的原文。
    找不到该段返回空串，调用方回落下一路来源。
    """
    out, inside = [], False
    for raw in str(markdown or "").splitlines():
        stripped = raw.strip()
        if _TOP_HEADING_RE.match(stripped):
            if inside:
                break
            inside = bool(_RISK_HEADING_RE.search(stripped))
            if inside:
                out.append(stripped)
            continue
        if inside:
            out.append(raw.rstrip())
    while out and (not out[-1].strip() or re.match(r"^-{3,}$", out[-1].strip())):
        out.pop()
    return "\n".join(out).strip()


def parse_rule_md(markdown):
    """从 007 的正文或 rule_md 里抠出风险点条目（仅作结构化元数据；展示走整段原文）。

    兼容 007 两种正文字体：
      ① 规则模板 / foreign_weekly：``- **[国外投行 · 高盛]** 下调某某评级至中性（neutral）``
      ② DeepSeek 自然投研列表：``- **美债收益率升温**：高盛警告…`` 或 ``1. **…**``
    只认风险段里的列表项；若原文是纯自然段（无列表项）则返回空列表，展示仍整段直搬。
    """
    points = []
    inside = False
    for raw in str(markdown or "").splitlines():
        line = raw.strip()
        if _TOP_HEADING_RE.match(line):
            inside = bool(_RISK_HEADING_RE.search(line))
            continue
        if not inside or re.match(r"^-{3,}$", line):
            continue
        m_item = re.match(r"^(?:[-*]|\d+[.)])\s+(.+)$", line)
        if not m_item:
            continue
        item_text = m_item.group(1).strip()
        m_bracket = re.match(r"^\*\*\[([^\]]+)\]\*\*\s*(.+)$", item_text)
        if m_bracket:
            tag, body = m_bracket.group(1), m_bracket.group(2).strip()
            institution = ""
            for part in re.split(r"[·•]\s*", tag):
                part = part.strip()
                if part in INSTITUTION_NAMES:
                    institution = part
            if not institution:
                institution, _ = match_institution(body)
        else:
            body = re.sub(r"\*\*(.+?)\*\*", r"\1", item_text).strip()
            if not body:
                continue
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


def _parse_007_payload_text(text):
    """把 007 的 Markdown / JSON / 运行日志解析成 (section_md, points, count)。"""
    raw = str(text or "").strip()
    if not raw:
        return "", [], 0
    count = 0
    markdown = raw
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                if payload.get("ok") is False:
                    return "", [], 0
                markdown = (payload.get("rule_md") or payload.get("teaser_md")
                            or payload.get("markdown") or payload.get("content") or "")
                count = int(payload.get("count") or 0)
        except ValueError:
            pass
    brief = _extract_brief_from_007_log(markdown)
    section_md = extract_section_md(brief)
    return section_md, parse_rule_md(section_md), count


def _fetch_remote_brief_url(timeout):
    """① 显式配置 OCTOPUS_007_BRIEF_URL 或 007 仓库已提交的公开简报正文。"""
    repo = _007_repo()
    branch = _007_branch()
    candidates = []
    explicit_url, explicit_env = _first_env(*ENV_007_BRIEF_URL)
    if explicit_url:
        candidates.append((explicit_url, explicit_env, "007公开正文", timeout))
    else:
        raw_t = min(5, timeout)
        candidates.append((
            f"https://raw.githubusercontent.com/{repo}/{branch}/output/latest_brief.md",
            "", "007仓库最新正文", raw_t))
        candidates.append((
            f"https://raw.githubusercontent.com/{repo}/{branch}/latest_brief.md",
            "", "007仓库最新正文", raw_t))
    reasons = []
    for url, env_name, label, req_t in candidates:
        try:
            text = _http_text(url, timeout=req_t)
        except urllib.error.HTTPError as exc:
            reasons.append(f"{label} HTTP {exc.code}")
            continue
        except Exception as exc:                   # noqa: BLE001
            reasons.append(f"{label} {type(exc).__name__}")
            continue
        section_md, points, count = _parse_007_payload_text(text)
        if section_md:
            return {"ok": True, "section_md": section_md, "points": points,
                    "url": url, "env": env_name, "source_label": label,
                    "reason": "", "count": count or len(points)}
        reasons.append(f"{label} 未含风险点段")
    return {"ok": False, "section_md": "", "points": [], "url": candidates[0][0],
            "reason": "；".join(reasons)}


def _fetch_remote_github_actions(timeout):
    """② 若配置了跨仓 Token，直接读 k-macao/007 最新一次 Scheduled Market Brief 的产物或运行日志。"""
    token, token_env = _first_env(*ENV_007_GH_TOKEN)
    if not token:
        return {"ok": False, "section_md": "", "points": [], "url": "",
                "reason": f"未配置 {'/'.join(ENV_007_GH_TOKEN[:2])}"}
    repo = _007_repo()
    gh_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    runs_url = (f"https://api.github.com/repos/{repo}/actions/workflows/"
                f"market-brief.yml/runs?status=success&per_page=5")
    try:
        runs_data = _http_json(runs_url, timeout=timeout, headers=gh_headers)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "section_md": "", "points": [], "url": runs_url,
                "env": token_env, "reason": f"007 Actions HTTP {exc.code}"}
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "section_md": "", "points": [], "url": runs_url,
                "env": token_env, "reason": f"007 Actions {type(exc).__name__}"}
    runs = [r for r in (runs_data or {}).get("workflow_runs") or []
            if isinstance(r, dict) and r.get("conclusion") == "success"]
    if not runs:
        return {"ok": False, "section_md": "", "points": [], "url": runs_url,
                "env": token_env, "reason": "007 暂无成功的定时简报运行"}
    run = runs[0]
    run_id = run.get("id")
    run_html = str(run.get("html_url") or runs_url)

    # 先试 Artifact（若 007 上传了文本/Markdown 产物）
    try:
        art_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts"
        arts = (_http_json(art_url, timeout=timeout, headers=gh_headers) or {}).get("artifacts") or []
        for art in arts:
            dl_url = str(art.get("archive_download_url") or "")
            if not dl_url or art.get("expired"):
                continue
            blob = _http_bytes(dl_url, timeout=timeout, headers=gh_headers)
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                for name in zf.namelist():
                    if not name.lower().endswith((".md", ".txt", ".json")):
                        continue
                    text = zf.read(name).decode("utf-8", "replace")
                    section_md, points, count = _parse_007_payload_text(text)
                    if section_md:
                        return {"ok": True, "section_md": section_md, "points": points,
                                "url": run_html, "env": token_env,
                                "source_label": f"007最新运行产物(run#{run_id})",
                                "run_id": run_id, "reason": "",
                                "count": count or len(points)}
    except Exception:                              # noqa: BLE001 Artifact 不可用继续读 Job 日志
        pass

    # 再读 Job 运行日志（「📝 生成的内容：」分隔线内即真实推送原文）
    jobs_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
    try:
        jobs_data = _http_json(jobs_url, timeout=timeout, headers=gh_headers)
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "section_md": "", "points": [], "url": run_html,
                "env": token_env, "reason": f"007 Jobs {type(exc).__name__}"}
    jobs = [j for j in (jobs_data or {}).get("jobs") or []
            if isinstance(j, dict) and j.get("conclusion") == "success"]
    if not jobs:
        return {"ok": False, "section_md": "", "points": [], "url": run_html,
                "env": token_env, "reason": f"007 run#{run_id} 无成功 job"}
    job_id = jobs[0].get("id")
    log_url = f"https://api.github.com/repos/{repo}/actions/jobs/{job_id}/logs"
    try:
        log_text = _http_text(log_url, timeout=max(timeout, 25), headers=gh_headers)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "section_md": "", "points": [], "url": run_html,
                "env": token_env, "reason": f"007 日志 HTTP {exc.code}"}
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "section_md": "", "points": [], "url": run_html,
                "env": token_env, "reason": f"007 日志 {type(exc).__name__}"}
    section_md, points, count = _parse_007_payload_text(log_text)
    if section_md:
        return {"ok": True, "section_md": section_md, "points": points,
                "url": run_html, "env": token_env,
                "source_label": f"007最新运行日志(run#{run_id})",
                "run_id": run_id, "reason": "", "count": count or len(points)}
    return {"ok": False, "section_md": "", "points": [], "url": run_html,
            "env": token_env, "reason": f"007 run#{run_id} 日志未含风险点段"}


def _fetch_remote_api(hours, timeout):
    """③ 兼容旧式 OCTOPUS_007_BASE_URL（007 server_dashboard /api/foreign_weekly）。"""
    base, env_name = remote_base()
    if not base:
        return {"ok": False, "section_md": "", "points": [], "url": "", "reason": "未配置 007 端点"}
    url = f"{base}/api/foreign_weekly?{urlencode({'hours': int(hours)})}"
    try:
        payload = _http_json(url, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "section_md": "", "points": [], "url": url,
                "reason": f"HTTP {exc.code}", "env": env_name}
    except Exception as exc:                       # noqa: BLE001 网络/解析异常一律降级
        return {"ok": False, "section_md": "", "points": [], "url": url,
                "reason": f"{type(exc).__name__}: {str(exc)[:80]}", "env": env_name}
    if not isinstance(payload, dict) or not payload.get("ok"):
        reason = str((payload or {}).get("error") or "端点返回 ok=false") if isinstance(payload, dict) else "返回不是对象"
        return {"ok": False, "section_md": "", "points": [], "url": url,
                "reason": reason[:100], "env": env_name}
    markdown = payload.get("rule_md") or payload.get("teaser_md") or ""
    section_md = extract_section_md(markdown)
    return {"ok": bool(section_md), "section_md": section_md,
            "points": parse_rule_md(section_md), "url": url, "env": env_name,
            "source_label": "007服务接口",
            "reason": "" if section_md else "端点未返回风险点栏目原文",
            "count": int(payload.get("count") or 0)}


def _safe_extract_tar_gz(blob, dest_dir):
    """安全解压 GitHub tarball 到临时目录，返回含 pushplus_deepseek.py 的根目录。"""
    dest_abs = os.path.abspath(dest_dir)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for member in tf.getmembers():
            if member.issym() or member.islnk() or (not member.isfile() and not member.isdir()):
                continue
            target = os.path.abspath(os.path.join(dest_abs, member.name))
            if os.path.commonpath([dest_abs, target]) != dest_abs:
                continue
            if member.isdir():
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                src = tf.extractfile(member)
                if src is not None:
                    with src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
    if os.path.isfile(os.path.join(dest_abs, "pushplus_deepseek.py")):
        return dest_abs
    for entry in os.listdir(dest_abs):
        cand = os.path.join(dest_abs, entry)
        if os.path.isdir(cand) and os.path.isfile(os.path.join(cand, "pushplus_deepseek.py")):
            return cand
    return ""


def _build_007_subprocess_env(base_env=None):
    """构造 007 子进程环境与 ai_provider：彻底剥离推送通道密钥，复用 001 的 LLM Key。"""
    sub_env = dict(os.environ if base_env is None else base_env)
    for secret_key in _007_STRIP_ENV_VARS:
        sub_env.pop(secret_key, None)
    sub_env["BOFA_BB_AUTO"] = "0"
    sub_env["BOFA_BB_BLOCK"] = "0"
    sub_env["AI_COMPRESS"] = "0"
    sub_env["PYTHONIOENCODING"] = "utf-8"
    sub_env["PYTHONUNBUFFERED"] = "1"

    inf_key = str(sub_env.get("INFERENCE_API_KEY") or "").strip()
    ds_key = str(sub_env.get("DEEPSEEK_API_KEY") or "").strip()
    octo_key = str(sub_env.get("OCTOPUS_LLM_API_KEY") or "").strip()
    octo_base = str(sub_env.get("OCTOPUS_LLM_BASE_URL") or "").strip()
    octo_model = str(sub_env.get("OCTOPUS_LLM_MODEL") or "").strip()
    openai_key = str(sub_env.get("OPENAI_API_KEY") or "").strip()

    if inf_key:
        ai_provider = "deepseek"
    elif ds_key:
        ai_provider = "deepseek"
    elif octo_key:
        if octo_base or octo_model:
            sub_env["INFERENCE_API_KEY"] = octo_key
            if octo_base:
                sub_env["INFERENCE_BASE_URL"] = octo_base
            if octo_model:
                sub_env["INFERENCE_MODEL"] = octo_model
        else:
            sub_env["DEEPSEEK_API_KEY"] = octo_key
        ai_provider = "deepseek"
    elif openai_key:
        ai_provider = "openai"
    else:
        ai_provider = "rule"
    return sub_env, ai_provider


def run_007_latest_code(timeout=None):
    """④ 自动拉取公开的 k-macao/007 最新代码并安全 --dry-run 执行 feedscan 提取风险段。"""
    auto_flag = str(os.environ.get(ENV_007_AUTO_RUN, "1")).strip().lower()
    if auto_flag in ("0", "false", "no", "off"):
        return {"ok": False, "section_md": "", "points": [], "url": "",
                "reason": "已关闭自动运行 007 源码（OCTOPUS_007_AUTO_RUN=0）"}
    repo = _007_repo()
    branch = _007_branch()
    repo_url = f"https://github.com/{repo}"
    try:
        run_timeout = int(str(os.environ.get(ENV_007_RUN_TIMEOUT) or (timeout or RUN_007_TIMEOUT)))
    except (TypeError, ValueError):
        run_timeout = RUN_007_TIMEOUT
    run_timeout = max(15, min(420, run_timeout))

    local_dir = str(os.environ.get(ENV_007_LOCAL_DIR) or "").strip()
    with tempfile.TemporaryDirectory(prefix="octopus-007-run-") as tmpdir:
        src_dir = ""
        if local_dir and os.path.isfile(os.path.join(local_dir, "pushplus_deepseek.py")):
            src_dir = os.path.abspath(local_dir)
        else:
            tar_url = f"https://codeload.github.com/{repo}/tar.gz/refs/heads/{branch}"
            try:
                blob = _http_bytes(tar_url, timeout=min(30, run_timeout))
                src_dir = _safe_extract_tar_gz(blob, tmpdir)
            except Exception as exc:       # noqa: BLE001
                return {"ok": False, "section_md": "", "points": [], "url": repo_url,
                        "reason": f"拉取 007 源码失败：{type(exc).__name__}: {str(exc)[:80]}"}
        if not src_dir:
            return {"ok": False, "section_md": "", "points": [], "url": repo_url,
                    "reason": "007 源码包缺少 pushplus_deepseek.py"}

        work_dir = os.path.join(tmpdir, "work")
        os.makedirs(work_dir, exist_ok=True)
        sub_env, ai_provider = _build_007_subprocess_env()
        existing_pp = str(sub_env.get("PYTHONPATH") or "").strip()
        sub_env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing_pp}" if existing_pp else src_dir

        req_timeout = min(45, max(15, run_timeout // 3))
        cst_hour = datetime.now(CST).hour
        brief_topic = "全球市场早报" if cst_hour < 13 else "全球市场晚报"
        cmd = [
            sys.executable,
            os.path.join(src_dir, "pushplus_deepseek.py"),
            "--template", "feedscan",
            "--topic", brief_topic,
            "--title", "章鱼 AI.券商研报 007",
            "--channel", "console",
            "--ai-provider", ai_provider,
            "--theme", "dos",
            "--hours", "24",
            "--no-chart",
            "--no-bofa-bb",
            "--no-state",
            "--no-ai-compress",
            "--timeout", str(req_timeout),
            "--dry-run",
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=work_dir,
                env=sub_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=run_timeout,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "section_md": "", "points": [], "url": repo_url,
                    "reason": f"007 源码执行超时（>{run_timeout}s）"}
        except Exception as exc:           # noqa: BLE001
            return {"ok": False, "section_md": "", "points": [], "url": repo_url,
                    "reason": f"007 源码执行失败：{type(exc).__name__}: {str(exc)[:80]}"}

        section_md, points, count = _parse_007_payload_text(proc.stdout)
        if section_md:
            return {
                "ok": True,
                "section_md": section_md,
                "points": points,
                "url": repo_url,
                "env": ENV_007_LOCAL_DIR if local_dir else "k-macao/007",
                "source_label": f"007最新源码同源生成({ai_provider})",
                "reason": "",
                "count": count or len(points),
            }
        err_tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        return {"ok": False, "section_md": "", "points": [], "url": repo_url,
                "reason": f"007 源码退出({proc.returncode})未产出风险段：{err_tail[0][:80]}"}


def fetch_remote(hours=REMOTE_HOURS):
    """按优先级取 007 最新一篇「⚠️ 研报 AI 风险点提示」原文，任何失败都不抛。

    优先级：① OCTOPUS_007_BRIEF_URL / 007 公开正文 → ② OCTOPUS_007_GH_TOKEN
    读 007 最新 Scheduled Market Brief 运行日志/产物 → ③ OCTOPUS_007_BASE_URL
    服务接口 → ④ 自动拉取公开 k-macao/007 最新源码在本地安全 --dry-run 同源生成。
    """
    timeout = _remote_timeout()
    reasons = []
    for getter in (
        lambda: _fetch_remote_brief_url(timeout),
        lambda: _fetch_remote_github_actions(timeout),
        lambda: _fetch_remote_api(hours, timeout),
        lambda: run_007_latest_code(),
    ):
        res = getter()
        if res.get("ok") and res.get("section_md"):
            return res
        if res.get("reason"):
            reasons.append(res["reason"])
    return {"ok": False, "section_md": "", "points": [], "url": "",
            "reason": "；".join(reasons)[:240] or "未取到 007 原文"}


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


# ------------------------------------------------------------ ④ 本地兜底：007推送原文模板
# 与 007 推送脚本 pushplus_deepseek.render_brief_risk_rule() 逐字同源：
# 同样的开头句、条目标签、空样本句与收尾段，一个字不改。差异只在输入——
# 007 用它当次采集的国外投行 / 香港券商 / 快讯三包，这里用本仓当次标题池
# 检出的风险点（外资署名 → 国外投行；中资券商署名 → 香港券商一档，与 007
# hk_brokers 按别名归入驻港券商的口径一致；未署名 → 快讯风险信号，情绪分用
# 007 score_text 同一把尺现算）。收尾段数字来自 feed_agg_local() 对同一标题池
# 的聚合（007 同公式），样本为 0 时整段不写，绝不出现「0/0 条」。
def feed_agg_local(items, anchor_dt, hours=WINDOW_HOURS):
    """本地标题池 → 007 快讯聚合口径 {n, pos, neg, neu, mean, 综合多头概率锚点}。

    逐条标题用 score_text_007 打分（007 POS/NEG 词表 + 0.12 阈值），锚点用
    007 collect_feed_pack 的公式 ``50 + 45 × clamp(mean×3)``；窗口与 collect_local
    一致（默认 360h），无时间戳的条目与 collect_local 一样按在窗口内处理。
    """
    cutoff = anchor_dt - timedelta(hours=hours)
    scores, labels = [], []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        title = _clean_title(item.get("title"))
        if len(title) < 8:
            continue
        dt = parse_datetime(item.get("ts")) or parse_datetime(item.get("date"))
        if dt is not None and not (cutoff <= dt <= anchor_dt + timedelta(hours=1)):
            continue
        score, label, _conf = score_text_007(title)
        scores.append(score)
        labels.append(label)
    n = len(scores)
    mean = round(sum(scores) / n, 2) if n else 0.0
    pos = labels.count("利好")
    neg = labels.count("利空")
    return {"n": n, "pos": pos, "neg": neg, "neu": n - pos - neg, "mean": mean,
            "综合多头概率锚点": round(50 + 45 * max(-1.0, min(1.0, mean * 3)))}


def render_brief_risk_md(points, feed_agg=None):
    """007 推送「⚠️ 研报 AI 风险点提示」的原文模板（render_brief_risk_rule 逐字复刻）。

    points 为已检出的风险点（字段同 collect_local / parse_rule_md）；展示顺序与
    007 一致：国外投行 → 香港券商 → 快讯风险信号（快讯按情绪分从低到高），最多 5 条。
    """
    lines = [SECTION_HEADING_MD, ""]
    risk_hits = []
    seen_titles = set()

    def _take(point):
        title = str(point.get("title") or "").strip()
        key = normalize_title(title)
        if not title or not key or key in seen_titles:
            return ""
        seen_titles.add(key)
        return title

    def _signed(point):
        # build() 的结构化条目把空机构补成「未署名」；两种写法都不算署名
        return str(point.get("institution") or "") not in ("", "未署名")

    for point in points or []:
        if not _signed(point) or not point.get("intl"):
            continue
        title = _take(point)
        if not title:
            continue
        rating = extract_rating_007(title)
        tag = f"（{rating}）" if rating else ""
        risk_hits.append(f"- **[国外投行 · {point.get('institution')}]** {title}{tag}")

    for point in points or []:
        if not _signed(point) or point.get("intl"):
            continue
        title = _take(point)
        if not title:
            continue
        rating = extract_rating_007(title)
        tag = f"（{rating}）" if rating else ""
        risk_hits.append(f"- **[香港券商 · {point.get('institution')}]** {title}{tag}")

    unsigned = [p for p in (points or [])
                if not p.get("institution") or p.get("institution") == "未署名"]
    unsigned.sort(key=lambda p: score_text_007(str(p.get("title") or ""))[0])
    for point in unsigned:
        title = _take(point)
        if not title:
            continue
        src = str(point.get("source") or "市场快讯")
        score = score_text_007(title)[0]
        risk_hits.append(f"- **[快讯风险信号 · {src}]** {title}（情绪 {score:+.2f}）")
        if len(risk_hits) >= 5:
            break

    if risk_hits:
        lines.append(
            "先把丑话说在前面。盘面上热闹归热闹，但下面这几处暗礁眼下还真不能假装看不见——"
            "尤其是机构开始收紧口径的地方，往往藏着资金最真实的顾虑："
        )
        lines.append("")
        lines.extend(risk_hits[:5])
    else:
        total_n = int((feed_agg or {}).get("n", 0) or 0)
        if total_n > 0:
            lines.append(
                "说起来，这轮窗口期里各大机构倒是没集中亮出降级红牌。但盘面越是顺风顺水，"
                "我们反而越得留个心眼：热门赛道的筹码是不是已经挤在窄门里了？"
                "一旦海外利率路径或汇率预期轻轻晃一下，拥挤交易松动起来往往不打招呼。"
            )
        else:
            lines.append(
                "坦白讲，眼下这个时间窗抓到的有效快讯和研报样本偏少——或许正赶上休市空窗，"
                "又或许是部分公开信源暂时卡壳。越是这种像在薄雾里开车的时刻，"
                "越别急着重仓押单边，等跨市场的暗流看清了再落子也不迟。"
            )

    if feed_agg and int(feed_agg.get("n", 0) or 0) > 0:
        a = feed_agg
        lines.append("")
        lines.append(
            f"翻看这批快讯底稿，利空消息占了 {a.get('neg', 0)}/{a.get('n', 0)} 条"
            f"（情绪均值 {a.get('mean', 0.0):+.2f}，多头胜率锚点大概在 {a.get('综合多头概率锚点', 50)}% 上下）。"
            "实际上，在多数情况下，单靠一两条刺耳标题未必能砸出深坑；"
            "真正要追问一句的是：这些零散的逆风信号，接下来会不会和资金面形成共振？"
        )
    return "\n".join(lines)


def first_paragraph(section_md):
    """原文段的第一段正文（跳过标题行与分割线；若全篇只有条目则退回首条）——只供日志与分条压缩摘要引用。"""
    first_bullet = ""
    for raw in str(section_md or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or re.match(r"^-{3,}$", line):
            continue
        if line.startswith(("-", "*")) or re.match(r"^\d+[.)]\s+", line):
            if not first_bullet:
                cleaned = re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line)
                first_bullet = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned).strip()
            continue
        return line.lstrip(">").strip()
    return first_bullet


# ------------------------------------------------------------ ⑥ 入口
def build(data=None, date_str=None, news_corpus=None, llm_config=None,
          market=None, allow_network=True, now=None):
    """构建「研报 AI 风险点提示」结果：展示文字只有 ``verbatim_md`` 一份 007 原文。

    原文二选一，绝不拼凑改写：在线取到 → 007 接口整段原文（不与本地条目合并）；
    取不到 → 007 推送原文模板（render_brief_risk_md）+ 本地标题池条目与聚合数字。
    ``llm_config`` / ``market`` 参数仅为兼容旧调用保留——原文直搬后这一栏不再
    调用大模型、也不再合成定调（历史上的「定调 / 关注点」字段保留为空兼容）。

    返回字典字段（渲染层只用这些，不再二次计算）：
      verbatim_md / verbatim_source / available / points（结构化元数据）
      summary（= 原文第一段，供日志与压缩摘要引用）/ focus（恒空串，兼容）
      tone_source（恒「原文」）/ summary_source / feed_agg
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
              else {"ok": False, "section_md": "", "points": [], "url": "",
                    "reason": "本次禁用在线取数"})
    local = collect_local(items, anchor)
    feed_agg = feed_agg_local(items, anchor)
    section_md = str(remote.get("section_md") or "") if remote.get("ok") else ""
    if section_md:
        # ① 在线原文整段直搬：不解析重组、不与本地条目合并、不润色
        verbatim_md = section_md
        verbatim_source = "007在线原文"
        points = merge_points(remote.get("points") or [], [])
    else:
        # ② 本地兜底：007 推送原文模板逐字生成，条目与聚合数字来自本地标题池
        points = merge_points([], local)
        verbatim_md = render_brief_risk_md(points, feed_agg)
        verbatim_source = "007推送原文模板（本地标题池）"
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
        "verbatim_md": verbatim_md,
        "verbatim_source": verbatim_source,
        "summary": first_paragraph(verbatim_md),
        "focus": "",
        "tone_source": "原文",
        "summary_source": "007 在线" if section_md else "本地规则",
        "feed_agg": feed_agg,
        "remote": {k: remote.get(k) for k in ("ok", "url", "reason", "env", "count", "source_label", "run_id")
                   if k in remote},
        "local_n": len(local),
        "window_hours": WINDOW_HOURS,
        "categories": category_counts(enriched),
        "newest_date": max(dates) if dates else "",
        "llm": {"ok": False, "model": "", "reason": "原文直搬，不调用大模型"},
        "corpus_n": len(items),
    }


def selftest():
    """离线自检：词表 / 机构识别 / 去重排序 / 007 整段原文提取 / 007 原文模板，全部不触网。"""
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
          "先把防线划清楚。翻开这周外资大行的研报夹，唱多声里其实夹着几记颇为冷静的刹车声——"
          "凡是机构主动下调评级或改口观望的地方，往往正对着市场最脆弱的预期软肋：\n\n"
          "- **[国外投行 · 高盛]** 下调某车企评级至中性（neutral）\n"
          "- **[国外投行 · 瑞银]** 中国互联网板块盈利预期存在下修风险\n\n"
          "从样本冷暖来看，这 5 篇外资报告里利空占 1 篇、中性 2 篇、利好 2 篇。"
          "在多数情况下，大行的纸面评级只是参考坐标，真正在牌桌上决定方向的，"
          "还得看资金愿不愿意掏真金白银跟进。\n\n"
          "## 🏛 国外研报\n- 明细条目\n")
    section = extract_section_md(md)
    check("007 整段原文一字不差",
          section.startswith(SECTION_HEADING_MD)
          and "先把防线划清楚" in section and "从样本冷暖来看" in section
          and "下调某车企评级至中性（neutral）" in section
          and "美银牛熊指标" not in section and "明细条目" not in section,
          section[:80])
    check("无该段时返回空串", extract_section_md("## 其他\n- x\n") == "")
    ai_log = ("2026-11-09T19:21:55.1234567Z 📝 生成的内容：\n"
              "2026-11-09T19:21:55.1234567Z ------------------------------------------------------------\n"
              "2026-11-09T19:21:55.1234567Z # 章鱼 AI.券商研报 007\n\n"
              "2026-11-09T19:21:55.1234567Z ## ⚠️ 研报 AI 风险点提示\n\n"
              "2026-11-09T19:21:55.1234567Z ### 1. 宏观暗礁\n"
              "2026-11-09T19:21:55.1234567Z - **高盛提示利率粘性**：美债长端收益率承压\n\n---\n\n"
              "2026-11-09T19:21:55.1234567Z ## 🏛 国外研报\n- 明细\n"
              "2026-11-09T19:21:55.1234567Z ------------------------------------------------------------\n")
    brief_from_log = _extract_brief_from_007_log(ai_log)
    ai_sec = extract_section_md(brief_from_log)
    check("007 日志提取与 ### 子标题保留",
          ai_sec.startswith(SECTION_HEADING_MD)
          and "### 1. 宏观暗礁" in ai_sec
          and not ai_sec.endswith("---")
          and "国外研报" not in ai_sec,
          ai_sec)
    ai_parsed = parse_rule_md(ai_sec)
    check("007 自然列表解析机构", len(ai_parsed) == 1 and ai_parsed[0]["institution"] == "高盛", str(ai_parsed))
    parsed = parse_rule_md(md)
    check("007 报文只取风险段", len(parsed) == 2 and parsed[0]["institution"] == "高盛", str(len(parsed)))
    check("007 报文带类别与评级", parsed[0]["category"] == "评级与目标价" and parsed[0]["rating"] == "中性")
    merged = merge_points(parsed, [{"title": "下调某车企评级至中性", "category": "评级与目标价"}])
    check("在线 + 本地去重", len(merged) == 2, str(len(merged)))
    check("007 打分与评级尺",
          score_text_007("大跌亏损，下调评级")[1] == "利空"
          and extract_rating_007("下调特斯拉评级至中性") == "下调")
    now = datetime(2026, 11, 4, 12, tzinfo=CST)
    local = collect_local([
        {"title": "高盛：下调某车企评级至中性", "ts": "2026-11-03 10:00", "source": "研报"},
        {"title": "花旗：上调目标价", "ts": "2026-11-03 11:00", "source": "研报"},
        {"title": "瑞银：看好明年行情", "ts": "2026-10-01 11:00", "source": "研报"},
    ], now)
    check("本地只收风险且在窗口内", len(local) == 1, str([x["title"] for x in local]))
    agg = feed_agg_local([
        {"title": "高盛：下调某车企评级至中性", "ts": "2026-11-03 10:00", "source": "研报"},
        {"title": "花旗：盈利增长超预期，上调目标价", "ts": "2026-11-03 11:00", "source": "研报"},
    ], now)
    check("本地聚合 007 口径", agg["n"] == 2 and agg["neg"] == 1
          and agg["综合多头概率锚点"] == 50, str(agg))
    brief_md = render_brief_risk_md(local, agg)
    check("本地兜底 007 原文模板",
          brief_md.startswith(SECTION_HEADING_MD)
          and "先把丑话说在前面。盘面上热闹归热闹，但下面这几处暗礁眼下还真不能假装看不见——" in brief_md
          and "- **[国外投行 · 高盛]** 高盛：下调某车企评级至中性（下调）" in brief_md
          and "翻看这批快讯底稿，利空消息占了 1/2 条（情绪均值 +0.00，多头胜率锚点大概在 50% 上下）。" in brief_md,
          brief_md[:120])
    check("有样本无风险用 007 空样本句",
          "这轮窗口期里各大机构倒是没集中亮出降级红牌" in render_brief_risk_md([], agg))
    empty_md = render_brief_risk_md([], {"n": 0})
    check("零样本用 007 空样本句且不写 0/0 收尾",
          "有效快讯和研报样本偏少" in empty_md and "0/0" not in empty_md, empty_md[:80])
    built = build(date_str="20261104",
                  news_corpus={"items": [
                      {"title": "高盛：下调某车企评级至中性",
                       "ts": "2026-11-03 10:00", "source": "研报"}]},
                  allow_network=False)
    check("构建只出原文不润色",
          built["verbatim_source"].startswith("007推送原文模板")
          and built["verbatim_md"] == render_brief_risk_md(
              built["points"], built["feed_agg"])
          and built["summary"] == first_paragraph(built["verbatim_md"])
          and built["llm"]["ok"] is False, built.get("verbatim_source", ""))
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
        print(f"⚠️ {SECTION_TITLE} · {'有线索' if result['available'] else '无风险线索'} · "
              f"{result['verbatim_source']}")
        print(result["verbatim_md"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
