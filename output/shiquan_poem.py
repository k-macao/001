#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诗泉（palemoky/chinese-poetry-api）随机古诗词模块
===================================================

对接 GitHub 开源项目「📜 诗泉：高性能中国古诗词 API 服务」
（https://github.com/palemoky/chinese-poetry-api ，数据子模块
https://github.com/palemoky/chinese-poetry `@fix-typo`，关联 Skill
https://github.com/lianginx/chinese-poetry-api-skill），在每次日报生成与推送
最开始随机抽取并展示一首中国古典诗词。

核心能力：
1. 在线 API 优先：支持调用诗泉 REST 接口 ``GET /api/v1/poems/random``
   （兼容 ``/api/poems/random``），完整支持 ``dynasty`` / ``author`` /
   ``type`` / ``char``（单字飞花令，与前三项互斥）/ ``lang``（``zh-Hans`` / ``zh-Hant``）
   过滤参数；
2. 离线语料无缝兜底：内置 ``tools/chinese-poetry-api/data/poems.json``
   （按诗泉 ``internal/classifier`` 与 ``internal/api/rest/handler/formatter.go``
   口径预构建的跨朝代经典诗词库），当运行环境离线、外网受限或单测运行时，
   自动在本地语料库中按完全一致的过滤条件随机抽取一首诗词；
3. 五套主题卷首渲染：支持 ``lime`` / ``guizang`` / ``dossier`` / ``forum`` /
   ``pixel`` 五套日报主题的诗卡渲染；与 ☯ 今日卦象同属刊头后的「诗与远方的海」栏目。
"""

from __future__ import annotations

import html as _html
import json
import os
import random
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import urlencode

UPSTREAM_NAME = "诗泉"
UPSTREAM_REPO = "https://github.com/palemoky/chinese-poetry-api"
UPSTREAM_DATA_REPO = "https://github.com/palemoky/chinese-poetry"
UPSTREAM_SKILL_REPO = "https://github.com/lianginx/chinese-poetry-api-skill"
DEFAULT_API_BASE_URL = "https://poetry.palemoky.com"
RANDOM_POEM_ENDPOINTS = ("/api/v1/poems/random", "/api/poems/random")

SHIQUAN_META_KEY = "_shiquan_poem"
SHIQUAN_SOURCE_NAME = "诗泉"

_REPO_ROOT = Path(__file__).resolve().parent.parent
VENDORED_DIR = _REPO_ROOT / "tools" / "chinese-poetry-api"
VENDORED_POEMS_PATH = VENDORED_DIR / "data" / "poems.json"

# 朝代映射（完全对齐 palemoky/chinese-poetry-api/internal/classifier/dynasty.go）
DYNASTY_INFO: Dict[str, Dict[str, Any]] = {
    "先秦": {"id": 1, "name": "先秦", "name_en": "Pre-Qin", "start_year": -2070, "end_year": -221},
    "两汉": {"id": 2, "name": "两汉", "name_en": "Han", "start_year": -206, "end_year": 220},
    "魏晋": {"id": 3, "name": "魏晋", "name_en": "Wei-Jin", "start_year": 220, "end_year": 420},
    "南北朝": {"id": 4, "name": "南北朝", "name_en": "Northern and Southern", "start_year": 420, "end_year": 589},
    "隋": {"id": 5, "name": "隋", "name_en": "Sui", "start_year": 581, "end_year": 618},
    "唐": {"id": 6, "name": "唐", "name_en": "Tang", "start_year": 618, "end_year": 907},
    "五代": {"id": 7, "name": "五代", "name_en": "Five Dynasties", "start_year": 907, "end_year": 960},
    "宋": {"id": 8, "name": "宋", "name_en": "Song", "start_year": 960, "end_year": 1279},
    "元": {"id": 9, "name": "元", "name_en": "Yuan", "start_year": 1271, "end_year": 1368},
    "清": {"id": 10, "name": "清", "name_en": "Qing", "start_year": 1644, "end_year": 1912},
    "其他": {"id": 11, "name": "其他", "name_en": "Other", "start_year": None, "end_year": None},
}

# 体裁映射（完全对齐 palemoky/chinese-poetry-api/internal/classifier/type.go）
TYPE_INFO: Dict[str, Dict[str, Any]] = {
    "诗经": {"id": 1, "name": "诗经", "category": "诗经", "lines": None, "chars_per_line": 4, "description": "中国最早的诗歌总集，多为四言诗"},
    "楚辞": {"id": 2, "name": "楚辞", "category": "楚辞", "lines": None, "chars_per_line": None, "description": "战国时期屈原等人创立的新诗体"},
    "乐府诗": {"id": 3, "name": "乐府诗", "category": "唐诗", "lines": None, "chars_per_line": None, "description": "汉魏六朝及唐代乐府旧题或新题诗歌"},
    "五言绝句": {"id": 4, "name": "五言绝句", "category": "唐诗", "lines": 4, "chars_per_line": 5, "description": "四句五言近体诗"},
    "七言绝句": {"id": 5, "name": "七言绝句", "category": "唐诗", "lines": 4, "chars_per_line": 7, "description": "四句七言近体诗"},
    "五言律诗": {"id": 6, "name": "五言律诗", "category": "唐诗", "lines": 8, "chars_per_line": 5, "description": "八句五言近体诗"},
    "七言律诗": {"id": 7, "name": "七言律诗", "category": "唐诗", "lines": 8, "chars_per_line": 7, "description": "八句七言近体诗"},
    "五代词": {"id": 8, "name": "五代词", "category": "词", "lines": None, "chars_per_line": None, "description": "五代十国时期词作"},
    "宋词": {"id": 9, "name": "宋词", "category": "词", "lines": None, "chars_per_line": None, "description": "词牌体裁作品"},
    "元曲": {"id": 10, "name": "元曲", "category": "曲", "lines": None, "chars_per_line": None, "description": "元代散曲与杂剧唱词"},
    "论语": {"id": 12, "name": "论语", "category": "论语", "lines": None, "chars_per_line": None, "description": "儒家经典语录"},
    "四书五经": {"id": 13, "name": "四书五经", "category": "四书五经", "lines": None, "chars_per_line": None, "description": "儒家四书五经经典"},
    "蒙学": {"id": 14, "name": "蒙学", "category": "蒙学", "lines": None, "chars_per_line": None, "description": "传统蒙学经典读物"},
    "其他": {"id": 11, "name": "其他", "category": "其他", "lines": None, "chars_per_line": None, "description": "古体诗及杂言诗"},
}

YUEFU_TITLES: Sequence[str] = (
    "关山月", "出塞", "塞下曲", "塞上曲", "从军行", "陇西行", "长歌行", "短歌行",
    "燕歌行", "古朗月行", "行路难", "将进酒", "蜀道难", "梁甫吟", "游子吟",
    "子夜吴歌", "玉阶怨", "长干行", "采莲曲", "竹枝词", "杨柳枝", "清平调",
    "凉州词", "渭城曲", "少年行", "侠客行", "白头吟", "怨歌行", "琵琶行", "长恨歌",
)

_SENTENCE_END_MARKERS = frozenset("，。！？；,.!?;")
_CLOSING_QUOTES = frozenset("”》】」』")

_BUILTIN_FALLBACK_POEMS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "title": "登鹳雀楼",
        "content": ["白日依山尽，黄河入海流。", "欲穷千里目，更上一层楼。"],
        "author": {"id": 1, "name": "王之涣"},
        "dynasty": DYNASTY_INFO["唐"],
        "type": TYPE_INFO["五言绝句"],
        "dataset_key": "tangshisanbaishou",
    },
    {
        "id": 2,
        "title": "静夜思",
        "content": ["床前明月光，疑是地上霜。", "举头望明月，低头思故乡。"],
        "author": {"id": 2, "name": "李白"},
        "dynasty": DYNASTY_INFO["唐"],
        "type": TYPE_INFO["五言绝句"],
        "dataset_key": "tangshisanbaishou",
    },
    {
        "id": 3,
        "title": "定风波",
        "content": [
            "莫听穿林打叶声，何妨吟啸且徐行。",
            "竹杖芒鞋轻胜马，谁怕？一蓑烟雨任平生。",
            "料峭春风吹酒醒，微冷，山头斜照却相迎。",
            "回首向来萧瑟处，归去，也无风雨也无晴。",
        ],
        "author": {"id": 3, "name": "苏轼"},
        "dynasty": DYNASTY_INFO["宋"],
        "type": TYPE_INFO["宋词"],
        "dataset_key": "songci",
    },
]

_VENDORED_CACHE: Optional[List[Dict[str, Any]]] = None
_API_UNREACHABLE: bool = False


def reset_circuit_breaker() -> None:
    """重置在线 API 熔断状态（供单测与手动重试使用）。"""
    global _API_UNREACHABLE
    _API_UNREACHABLE = False


def is_enabled() -> bool:
    """检查环境变量 ``OCTOPUS_SHIQUAN`` 是否开启（默认开启）。"""
    val = os.environ.get("OCTOPUS_SHIQUAN", "1").strip().lower()
    return val not in ("0", "false", "no", "off")


def normalize_and_split_paragraphs(paragraphs: Sequence[str]) -> List[str]:
    """对齐诗泉 ``classifier.NormalizeAndSplitParagraphs``：归一化并按句末标点切分粘连诗句。"""
    result: List[str] = []
    for raw in paragraphs or ():
        text = " ".join(str(raw or "").strip().split())
        if not text:
            continue
        start = 0
        n = len(text)
        i = 0
        while i < n:
            ch = text[i]
            if ch in ("。", "！", "？"):
                end = i + 1
                if end < n and text[end] in _CLOSING_QUOTES:
                    end += 1
                    i += 1
                seg = text[start:end].strip()
                if seg:
                    result.append(seg)
                start = end
            i += 1
        if start < n:
            seg = text[start:].strip()
            if seg:
                result.append(seg)
    return result


def _split_into_sentences(paragraphs: Sequence[str]) -> List[str]:
    sentences: List[str] = []
    for para in paragraphs or ():
        cur: List[str] = []
        for ch in str(para or ""):
            cur.append(ch)
            if ch in _SENTENCE_END_MARKERS:
                s = "".join(cur).strip()
                if s:
                    sentences.append(s)
                cur = []
        if cur:
            s = "".join(cur).strip()
            if s:
                sentences.append(s)
    return sentences


def _count_chinese_chars(line: str) -> int:
    return sum(1 for ch in (line or "") if "\u4e00" <= ch <= "\u9fff")


def classify_poetry_type(
    paragraphs: Sequence[str],
    rhythmic: str = "",
    dataset_key: str = "",
    title: str = "",
) -> Dict[str, Any]:
    """对齐诗泉 ``classifier.ClassifyPoetryTypeWithDataset`` 的诗词体裁分类器。"""
    dk = (dataset_key or "").strip()
    if dk == "shijing":
        return dict(TYPE_INFO["诗经"])
    if dk == "chuci":
        return dict(TYPE_INFO["楚辞"])
    if dk == "lunyu":
        return dict(TYPE_INFO["论语"])
    if dk == "mengzi":
        return dict(TYPE_INFO["四书五经"])
    if dk == "yuanqu":
        return dict(TYPE_INFO["元曲"])
    if dk in ("wudai-huajianji", "wudai-nantang"):
        return dict(TYPE_INFO["五代词"])
    if dk == "nalanxingde":
        return dict(TYPE_INFO["宋词"])
    if dk == "caocao":
        return dict(TYPE_INFO["乐府诗"])
    if (rhythmic or "").strip():
        return dict(TYPE_INFO["宋词"])

    clean_title = (title or "").strip()
    for yf in YUEFU_TITLES:
        if clean_title == yf or clean_title.startswith(yf + "·") or clean_title.startswith(yf + " "):
            return dict(TYPE_INFO["乐府诗"])

    sentences = _split_into_sentences(paragraphs)
    if not sentences:
        return dict(TYPE_INFO["其他"])
    lengths = [_count_chinese_chars(s) for s in sentences]
    first = lengths[0]
    if first > 0 and all(length == first for length in lengths):
        pair = (len(sentences), first)
        if pair == (4, 5):
            return dict(TYPE_INFO["五言绝句"])
        if pair == (4, 7):
            return dict(TYPE_INFO["七言绝句"])
        if pair == (8, 5):
            return dict(TYPE_INFO["五言律诗"])
        if pair == (8, 7):
            return dict(TYPE_INFO["七言律诗"])
    return dict(TYPE_INFO["其他"])


def infer_dynasty_info(dynasty: Any) -> Dict[str, Any]:
    """对齐诗泉 ``classifier.GetDynastyInfo``：把朝代名或朝代字典标准化为完整结构。"""
    if isinstance(dynasty, dict):
        name = str(dynasty.get("name") or "其他").strip() or "其他"
        base = dict(DYNASTY_INFO.get(name, DYNASTY_INFO["其他"]))
        for k in ("id", "name", "name_en", "start_year", "end_year"):
            if dynasty.get(k) is not None:
                base[k] = dynasty[k]
        return base
    name = str(dynasty or "").strip()
    if name.endswith("代") and name[:-1] in DYNASTY_INFO:
        name = name[:-1]
    return dict(DYNASTY_INFO.get(name, DYNASTY_INFO["其他"]))


def normalize_poem_payload(raw: Any, *, source: str = "vendored") -> Optional[Dict[str, Any]]:
    """将诗泉 REST API 响应（含 ``/api/v1/poems/random`` 与 ``/api/poems/random``）
    或 ``chinese-poetry`` 原始条目统一规整为诗泉 ``formatPoem`` 标准结构。
    """
    if not isinstance(raw, dict):
        return None
    # 兼容 /api/poems/random 顶层 {"data": {...}, "lang": "zh-Hans"} 包装
    payload = raw.get("data") if isinstance(raw.get("data"), dict) else raw

    raw_content = (
        payload.get("content")
        or payload.get("paragraphs")
        or payload.get("para")
        or []
    )
    if isinstance(raw_content, str):
        try:
            parsed = json.loads(raw_content)
            raw_content = parsed if isinstance(parsed, list) else [raw_content]
        except Exception:
            raw_content = [line for line in raw_content.splitlines() if line.strip()]
    if not isinstance(raw_content, list):
        return None

    content = normalize_and_split_paragraphs([str(x) for x in raw_content if str(x).strip()])
    if not content:
        return None

    rhythmic = str(payload.get("rhythmic") or "").strip()
    title = str(payload.get("title") or rhythmic or payload.get("chapter") or "无题").strip() or "无题"

    raw_author = payload.get("author")
    if isinstance(raw_author, dict):
        author_name = str(raw_author.get("name") or "佚名").strip() or "佚名"
        author_id = raw_author.get("id") or 0
    else:
        author_name = str(raw_author or "佚名").strip() or "佚名"
        author_id = 0

    dynasty = infer_dynasty_info(payload.get("dynasty"))
    dataset_key = str(payload.get("dataset_key") or "").strip()

    raw_type = payload.get("type")
    if isinstance(raw_type, dict) and raw_type.get("name"):
        t_name = str(raw_type.get("name")).strip()
        poem_type = dict(TYPE_INFO.get(t_name, TYPE_INFO["其他"]))
        for k in ("id", "name", "category", "lines", "chars_per_line", "description"):
            if raw_type.get(k) is not None:
                poem_type[k] = raw_type[k]
    elif isinstance(raw_type, str) and raw_type.strip():
        t_name = raw_type.strip()
        poem_type = dict(TYPE_INFO.get(t_name, TYPE_INFO["其他"]))
        poem_type["name"] = t_name
    else:
        poem_type = classify_poetry_type(content, rhythmic=rhythmic, dataset_key=dataset_key, title=title)

    return {
        "id": payload.get("id") or 1,
        "title": title,
        "content": content,
        "author": {"id": author_id, "name": author_name},
        "dynasty": dynasty,
        "type": poem_type,
        "source": str(payload.get("source") or source),
        "upstream_repo": UPSTREAM_REPO,
    }


def load_vendored_poems(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """加载本地 vendor 的诗泉精选诗词库（``tools/chinese-poetry-api/data/poems.json``）。"""
    global _VENDORED_CACHE
    target = Path(path) if path is not None else VENDORED_POEMS_PATH
    if path is None and _VENDORED_CACHE is not None:
        return list(_VENDORED_CACHE)

    poems: List[Dict[str, Any]] = []
    if target.is_file():
        try:
            raw_list = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(raw_list, list):
                for item in raw_list:
                    norm = normalize_poem_payload(item, source="vendored")
                    if norm is not None:
                        poems.append(norm)
        except Exception:
            poems = []

    if not poems:
        poems = [
            norm for item in _BUILTIN_FALLBACK_POEMS
            if (norm := normalize_poem_payload(item, source="builtin")) is not None
        ]

    if path is None:
        _VENDORED_CACHE = list(poems)
    return poems


def filter_poems(
    poems: Sequence[Dict[str, Any]],
    *,
    dynasty: str = "",
    dynasty_id: Optional[int] = None,
    author: str = "",
    author_id: Optional[int] = None,
    poem_type: str = "",
    type_id: Optional[int] = None,
    char: str = "",
) -> List[Dict[str, Any]]:
    """对齐诗泉 ``internal/api/rest/handler/poem.go`` 的过滤逻辑：
    - ``char``（单字飞花令）与 ``author``/``dynasty``/``type`` 互斥；
    - 支持按朝代、作者、体裁（名称或分类）过滤。
    """
    char = (char or "").strip()
    dynasty = (dynasty or "").strip()
    author = (author or "").strip()
    poem_type = (poem_type or "").strip()

    if char:
        # 对齐 poem.go:55-65：char 必须为单个字符，且不能与 author/type/dynasty 组合使用
        if len(char) != 1:
            raise ValueError("char parameter must be a single character")
        if any([dynasty, dynasty_id is not None, author, author_id is not None, poem_type, type_id is not None]):
            raise ValueError("char parameter cannot be combined with author, type, or dynasty filters")
        return [
            p for p in poems
            if char in (p.get("title") or "") or any(char in line for line in (p.get("content") or []))
        ]

    matched: List[Dict[str, Any]] = []
    norm_dynasty = dynasty[:-1] if (dynasty.endswith("代") and dynasty[:-1] in DYNASTY_INFO) else dynasty
    for p in poems:
        p_dyn = p.get("dynasty") or {}
        p_aut = p.get("author") or {}
        p_typ = p.get("type") or {}
        if norm_dynasty and p_dyn.get("name") != norm_dynasty and p_dyn.get("name_en") != dynasty:
            continue
        if dynasty_id is not None and p_dyn.get("id") != dynasty_id:
            continue
        if author and p_aut.get("name") != author:
            continue
        if author_id is not None and p_aut.get("id") != author_id:
            continue
        if poem_type and p_typ.get("name") != poem_type and p_typ.get("category") != poem_type:
            continue
        if type_id is not None and p_typ.get("id") != type_id:
            continue
        matched.append(p)
    return matched


def pick_local_random_poem(
    *,
    dynasty: str = "",
    dynasty_id: Optional[int] = None,
    author: str = "",
    author_id: Optional[int] = None,
    poem_type: str = "",
    type_id: Optional[int] = None,
    char: str = "",
    rng: Optional[random.Random] = None,
    corpus: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """从本地诗泉语料库中按过滤条件随机抽取一首诗词（过滤无命中时自动回退全量随机）。"""
    poems = list(corpus) if corpus is not None else load_vendored_poems()
    try:
        candidates = filter_poems(
            poems,
            dynasty=dynasty,
            dynasty_id=dynasty_id,
            author=author,
            author_id=author_id,
            poem_type=poem_type,
            type_id=type_id,
            char=char,
        )
    except ValueError:
        candidates = []
    if not candidates:
        candidates = poems or list(_BUILTIN_FALLBACK_POEMS)
    chooser = rng if rng is not None else random.SystemRandom()
    picked = dict(chooser.choice(candidates))
    picked["source"] = picked.get("source") or "vendored"
    picked["upstream_repo"] = UPSTREAM_REPO
    return picked


def build_random_poem_url(
    base_url: Optional[str] = None,
    *,
    endpoint: str = RANDOM_POEM_ENDPOINTS[0],
    dynasty: str = "",
    dynasty_id: Optional[int] = None,
    author: str = "",
    author_id: Optional[int] = None,
    poem_type: str = "",
    type_id: Optional[int] = None,
    char: str = "",
    lang: str = "",
) -> str:
    """构造诗泉 ``/api/v1/poems/random`` 请求 URL 与查询参数。"""
    root = (base_url or os.environ.get("OCTOPUS_SHIQUAN_BASE_URL") or DEFAULT_API_BASE_URL).strip().rstrip("/")
    path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    params: Dict[str, Any] = {}
    if char:
        params["char"] = char
    else:
        if author:
            params["author"] = author
        if author_id is not None:
            params["author_id"] = author_id
        if dynasty:
            params["dynasty"] = dynasty
        if dynasty_id is not None:
            params["dynasty_id"] = dynasty_id
        if poem_type:
            params["type"] = poem_type
        if type_id is not None:
            params["type_id"] = type_id
    if lang:
        params["lang"] = lang
    query = urlencode(params)
    return f"{root}{path}?{query}" if query else f"{root}{path}"


def fetch_random_poem(
    request_fn: Optional[Callable[..., Any]] = None,
    *,
    base_url: Optional[str] = None,
    dynasty: Optional[str] = None,
    author: Optional[str] = None,
    poem_type: Optional[str] = None,
    char: Optional[str] = None,
    lang: Optional[str] = None,
    allow_network: bool = True,
    timeout: float = 2.5,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """获取诗泉随机一首诗（优先请求在线 API，失败或离线时无缝回退本地诗泉语料库）。"""
    global _API_UNREACHABLE

    dynasty_val = (dynasty if dynasty is not None else os.environ.get("OCTOPUS_SHIQUAN_DYNASTY", "")).strip()
    author_val = (author if author is not None else os.environ.get("OCTOPUS_SHIQUAN_AUTHOR", "")).strip()
    type_val = (poem_type if poem_type is not None else os.environ.get("OCTOPUS_SHIQUAN_TYPE", "")).strip()
    char_val = (char if char is not None else os.environ.get("OCTOPUS_SHIQUAN_CHAR", "")).strip()
    lang_val = (lang if lang is not None else os.environ.get("OCTOPUS_SHIQUAN_LANG", "zh-Hans")).strip()
    mode = os.environ.get("OCTOPUS_SHIQUAN_MODE", "auto").strip().lower()

    if allow_network and mode != "offline" and not _API_UNREACHABLE:
        # 优先使用传入的 request_fn（仅当真实网络可用或显式传入自定义函数时）
        if request_fn is not None:
            for ep in RANDOM_POEM_ENDPOINTS:
                url = build_random_poem_url(
                    base_url,
                    endpoint=ep,
                    dynasty=dynasty_val,
                    author=author_val,
                    poem_type=type_val,
                    char=char_val,
                    lang=lang_val,
                )
                try:
                    raw = request_fn(url, timeout=timeout)
                    norm = normalize_poem_payload(raw, source="api")
                    if norm is not None:
                        norm["api_url"] = url
                        return norm
                except Exception:
                    continue
            _API_UNREACHABLE = True
        else:
            try:
                import requests as _requests  # type: ignore
                get_fn = getattr(_requests, "get", None)
            except Exception:
                get_fn = None
            if callable(get_fn):
                headers = {
                    "Accept": "application/json",
                    "User-Agent": "OctopusReport-ShiquanClient/1.0 (+https://github.com/palemoky/chinese-poetry-api)",
                }
                if lang_val:
                    headers["Accept-Language"] = lang_val
                for ep in RANDOM_POEM_ENDPOINTS:
                    url = build_random_poem_url(
                        base_url,
                        endpoint=ep,
                        dynasty=dynasty_val,
                        author=author_val,
                        poem_type=type_val,
                        char=char_val,
                        lang=lang_val,
                    )
                    try:
                        resp = get_fn(url, headers=headers, timeout=timeout)
                        if getattr(resp, "status_code", 0) == 200:
                            raw = resp.json() if callable(getattr(resp, "json", None)) else json.loads(resp.text)
                            norm = normalize_poem_payload(raw, source="api")
                            if norm is not None:
                                norm["api_url"] = url
                                return norm
                    except Exception:
                        break
                _API_UNREACHABLE = True

    return pick_local_random_poem(
        dynasty=dynasty_val,
        author=author_val,
        poem_type=type_val,
        char=char_val,
        rng=rng,
    )


def get_opening_poem(
    data: Optional[Dict[str, Any]] = None,
    *,
    allow_network: bool = False,
    rng: Optional[random.Random] = None,
) -> Optional[Dict[str, Any]]:
    """从 ``data`` 中读取已抽取的诗泉诗词；若尚未抽取则立即抽取一首并缓存到 ``data["_shiquan_poem"]``。"""
    if not is_enabled():
        return None
    if isinstance(data, dict):
        for key in (SHIQUAN_META_KEY, SHIQUAN_SOURCE_NAME):
            existing = data.get(key)
            if isinstance(existing, dict):
                norm = normalize_poem_payload(existing, source=str(existing.get("source") or "cached"))
                if norm is not None:
                    return norm
    poem = fetch_random_poem(allow_network=allow_network, rng=rng)
    if isinstance(data, dict) and poem is not None:
        try:
            data[SHIQUAN_META_KEY] = poem
        except Exception:
            pass
    return poem


def format_cli_banner(poem: Optional[Dict[str, Any]]) -> str:
    """格式化终端开篇诗词横幅（在 ``collect_all_data`` / ``main`` 最开始打印）。"""
    if not isinstance(poem, dict):
        return ""
    title = str(poem.get("title") or "无题").strip()
    author = str((poem.get("author") or {}).get("name") or "佚名").strip()
    dynasty = str((poem.get("dynasty") or {}).get("name") or "").strip()
    type_name = str((poem.get("type") or {}).get("name") or "").strip()
    content = [str(line).strip() for line in (poem.get("content") or []) if str(line).strip()]
    dynasty_prefix = f"〔{dynasty}〕" if dynasty else ""
    type_suffix = f" · {type_name}" if type_name else ""
    lines = [
        f"📜 【诗泉 · 随机一首诗】《{title}》 — {dynasty_prefix}{author}{type_suffix}",
    ]
    for line in content[:8]:
        lines.append(f"   {line}")
    lines.append(f"   🔗 来源: GitHub 诗泉 ({UPSTREAM_REPO})")
    return "\n".join(lines)


def _esc(val: Any) -> str:
    return _html.escape(str(val or ""), quote=True)


def render_opening_poem_html(poem: Optional[Dict[str, Any]], theme: str = "lime") -> str:
    """按五套主题（``lime`` / ``guizang`` / ``dossier`` / ``forum`` / ``pixel``）
    渲染「诗与远方的海」栏目内的「今日一首诗」子块。

    设计约束：
    - 不另起 ``<h2>`` 或 ``SECTION_BODY_MARK``，诗卡与卦象共属一个卷首栏目；
    - 全表（``<table>``）内联样式排版，兼容微信 / PushPlus ``v-html`` 清洗与所有字色对比度门禁；
    - 表格内文字缩小一号且不加粗（2026-10-23 用户要求，与日报数据表同口径）：
      诗题 15→14、诗句 14→13、左栏标签 11/12→10/11、徽标 10→9，字重一律 400；
      颜色、字距、圆角与底色不变，五套主题同步收一档。
    """
    if not isinstance(poem, dict):
        return ""
    norm = normalize_poem_payload(poem, source=str(poem.get("source") or "vendored"))
    if norm is None:
        return ""

    title = _esc(norm["title"])
    author = _esc(norm["author"]["name"])
    dynasty = _esc(norm["dynasty"]["name"])
    type_name = _esc(norm["type"]["name"])
    verses = [_esc(line) for line in norm["content"][:8] if line]
    if not verses:
        return ""

    meta_parts = [p for p in (f"〔{dynasty}〕{author}" if dynasty else author, type_name) if p]
    meta_str = " · ".join(meta_parts)
    theme_key = (theme or "lime").strip().lower()

    if theme_key == "pixel":
        verse_html = "<br>".join(verses)
        return (
            '<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#101426" '
            'style="width:100%!important;border-collapse:collapse;margin:12px 0;'
            'background:#101426;border:1px solid #39FFB6;box-shadow:5px 5px 0 #000;color:#F4F7FF;">'
            '<tr><td width="28%" valign="top" style="padding:8px 10px;border-bottom:1px solid #1E2440;'
            'font-size:10px;font-weight:400;letter-spacing:0.12em;color:#39FFB6;">'
            '📜 今日一首诗 // 诗泉</td>'
            f'<td valign="top" style="padding:8px 10px;border-bottom:1px solid #1E2440;'
            f'font-size:14px;font-weight:400;color:#FFE66D;">'
            f'《{title}》 <span style="font-size:11px;font-weight:400;color:#A6AEC9;">{meta_str}</span></td></tr>'
            '<tr><td width="28%" valign="top" style="padding:8px 10px;font-size:11px;color:#A6AEC9;">诗句正文</td>'
            f'<td valign="top" style="padding:8px 10px;font-size:13px;line-height:1.75;color:#F4F7FF;">{verse_html}</td></tr>'
            '</table>'
        )

    if theme_key == "forum":
        verse_html = "<br>".join(verses)
        return (
            '<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#2C2C2E" '
            'style="width:100%!important;border-collapse:collapse;margin:12px 0;'
            'background:#2C2C2E;border:1px solid #3A3A3C;border-radius:10px;color:#F2F2F7;">'
            '<tr><td width="28%" valign="top" style="padding:8px 12px;border-bottom:1px solid #3A3A3C;'
            'font-size:10px;font-weight:400;letter-spacing:0.10em;color:#BF5AF2;">'
            '📜 今日一首诗 · 诗泉</td>'
            f'<td valign="top" style="padding:8px 12px;border-bottom:1px solid #3A3A3C;'
            f'font-size:14px;font-weight:400;color:#FFFFFF;">'
            f'《{title}》 <span style="font-size:11px;font-weight:400;color:#A1A1AA;">{meta_str}</span></td></tr>'
            '<tr><td width="28%" valign="top" style="padding:8px 12px;font-size:11px;color:#A1A1AA;">诗句正文</td>'
            f'<td valign="top" style="padding:8px 12px;font-size:13px;line-height:1.75;color:#F2F2F7;">{verse_html}</td></tr>'
            '</table>'
        )

    if theme_key == "dossier":
        verse_html = "<br>".join(verses)
        return (
            '<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#EFECE6" '
            'style="width:100%!important;border-collapse:collapse;margin:12px 0;'
            'background:#EFECE6;border-top:2px solid #0E0E0E;border-bottom:1px solid #C8C4BC;color:#1F1F1F;">'
            '<tr><td width="28%" valign="top" style="padding:8px 10px;border-bottom:1px solid #D8D4CC;'
            'font-size:9px;font-weight:400;letter-spacing:0.12em;color:#0E0E0E;">'
            '<span style="background:#39FF14;color:#0E0E0E;padding:1px 6px;margin-right:6px;">诗泉</span>'
            '📜 今日一首诗</td>'
            f'<td valign="top" style="padding:8px 10px;border-bottom:1px solid #D8D4CC;'
            f'font-size:14px;font-weight:400;color:#0E0E0E;">'
            f'《{title}》 <span style="font-size:11px;font-weight:400;color:#333333;">{meta_str}</span></td></tr>'
            '<tr><td width="28%" valign="top" style="padding:8px 10px;font-size:11px;color:#333333;">诗句正文</td>'
            f'<td valign="top" style="padding:8px 10px;font-size:13px;line-height:1.75;color:#1F1F1F;">{verse_html}</td></tr>'
            '</table>'
        )

    if theme_key == "guizang":
        verse_html = "<br>".join(verses)
        return (
            '<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#F6F6F6" '
            'style="width:100%!important;border-collapse:collapse;margin:12px 0;'
            'background:#F6F6F6;border-left:3px solid #002FA7;border-top:1px solid #DDDDDD;'
            'border-right:1px solid #DDDDDD;border-bottom:1px solid #DDDDDD;color:#222222;">'
            '<tr><td width="28%" valign="top" style="padding:8px 12px;border-bottom:1px solid #E5E5E5;'
            'font-size:10px;font-weight:400;letter-spacing:0.10em;color:#002FA7;">'
            '📜 今日一首诗 · 诗泉</td>'
            f'<td valign="top" style="padding:8px 12px;border-bottom:1px solid #E5E5E5;'
            f'font-size:14px;font-weight:400;color:#111111;">'
            f'《{title}》 <span style="font-size:11px;font-weight:400;color:#333333;">{meta_str}</span></td></tr>'
            '<tr><td width="28%" valign="top" style="padding:8px 12px;font-size:11px;color:#333333;">诗句正文</td>'
            f'<td valign="top" style="padding:8px 12px;font-size:13px;line-height:1.75;color:#222222;">{verse_html}</td></tr>'
            '</table>'
        )

    # 默认 lime（青柠白卡杂志风）
    verse_html = "<br>".join(verses)
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#FFFFFF" '
        'style="width:100%!important;border-collapse:collapse;margin:12px 0;'
        'background:#FFFFFF;border:1px solid #E2E5EC;border-radius:16px;color:#18181B;">'
        '<tr><td width="28%" valign="top" style="padding:8px 12px;border-bottom:1px solid #ECEEF3;'
        'font-size:10px;font-weight:400;letter-spacing:0.08em;color:#111111;">'
        '<span style="display:inline-block;padding:1px 8px;margin-right:6px;border-radius:999px;'
        'background:#D4FF00;color:#111111;font-size:9px;font-weight:400;">诗泉</span>'
        '📜 今日一首诗</td>'
        f'<td valign="top" style="padding:8px 12px;border-bottom:1px solid #ECEEF3;'
        f'font-size:14px;font-weight:400;color:#111111;">'
        f'《{title}》 <span style="font-size:11px;font-weight:400;color:#333333;">{meta_str}</span></td></tr>'
        '<tr><td width="28%" valign="top" style="padding:8px 12px;font-size:11px;color:#333333;">诗句正文</td>'
        f'<td valign="top" style="padding:8px 12px;font-size:13px;line-height:1.75;color:#18181B;">{verse_html}</td></tr>'
        '</table>'
    )
