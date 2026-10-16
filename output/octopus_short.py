#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 短线速查卡 —— 日报分析、数据与结论之后的行动要点收尾卡（2026-09-30 新增，2026-10-02 升级百句梗库）。

用户要求：内容再精炼，适合短线操作，入门观看；【新手三句话】改成读取库文件，
找到一百句股票梗句，随时配对使用。本模块只回答短线客开场三问——
**今天什么风、明天怎么做、哪些日子别碰**——外加从库文件（`output/stock_memes.json`，
100 句股票梗句）读取并按当次盘面随时配对的【新手三句话】。

2026-10-16（用户要求「新手三句话，放在卦象后」）：三句话的**配对仍在本模块**，
渲染位置改到卷首「诗与远方的海」卦象之后（pipeline 用 `build_card(..., tips_in_card=False)`
把预算也一并交出去）；卦象关闭（OCTOPUS_BAGUA=0）或起卦失败时回落到卡尾原处，
同一份日报里三句话**只出现一处**。

设计原则（与整仓「防自欺」文化一致，写进 tests/test_short_card.py 兜底）：
  1. **纯规则合成、可复现**：不调大模型、不掷骰子；同一份输入永远得到同一张卡与同一组三句话。
  2. **零新增计算**：卡上每个数字都直接取自本次渲染正文用的同一批实参
     （weekly 逐日表 T+1 行 / entry 整段结论 / quant headline+liquidity /
     ai_result quant_sectors / pan 板块热力 / cal items / senti market_summary），
     不另算一套、不把数字四舍五入成新口径、不给方向「加戏」。
     南向的「温和缩量 / 显著放量」标签直接调用量化包同一个 `liquidity.flow_label`，
     阈值只有一处定义；百句股票梗库一律不含阿拉伯数字，绝不伪造行情数字。
  3. **数据不足自动缺席**：哪一路没数据，对应那一行就不出现；全都没数据 → 整卡缺席，
     绝不用旧数据或写死文案充数。
  4. **字数硬预算**：正文可见文字 ≤ CARD_CHAR_BUDGET（默认 600 字；
     三句话留在卡尾时含【新手三句话】，移到卷首后不再计入——见 build_card）。
     超预算时按 DROP_ORDER 从「最不影响动手」的行开始**整行**撤下，绝不截断半句话，
     撤了哪几行如实记在 card["dropped"] 里（测试与日志都能查）。
     地板：定调 + 明日剧本 + 数据底 + 新手小抄永不撤（撤完可撤行仍超预算时如实超长，
     也不砍「明天怎么做」）。
  5. **读取库文件、随时配对**：【新手三句话】从 `output/stock_memes.json` 读取 100 句股票梗句，
     按三槽位（① 看方向 / ② 放止损 / ③ 别动手）与当前盘面场景（方向偏多/偏空/震荡、
     风控防守/高波/轻仓、纪律重磅日程/数据缺口/观望）+ 日期种子确定性配对，
     同时支持按槽位、场景、关键词或上下句随时配对调用；库文件异常时优雅降级兜底。
  6. **不给投资建议**：仓位 / 止损 / 止盈都是引擎既有输出，卡上原样搬运；
     末尾固定「规则合成 · 非投资建议」。
  7. 环境变量 OCTOPUS_LITE=0（或命令行 --full）整体关闭，日报回到全量长版。

ctx 约定（键全部可选，缺了就降级）：
  date_str   报告日 YYYYMMDD
  today      报告日 date 对象（「今明必看」的日基准；缺了该行直接缺席，绝不猜今明）
  weekly     每周走势预测 result（daily.rows / entry）
  quant      港股量化 result（headline / liquidity / target_label）
  ai         策略研判结果（quant_sectors / sentiment_label / score）
  pan        A股大盘全景 source_result（sectors 领涨领跌，作 ai 的兜底）
  cal        财经日历 source_result（items）
  senti      新闻情绪结果（market_summary）
  coverage   {"today": n, "total": m}
"""
from __future__ import annotations

import json
import os
import re
import sys
import zlib
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:                                    # 南向标签复用量化包同一套阈值（不另写一份）
    from octopus_quant import liquidity as _liquidity
except Exception:                       # pragma: no cover - 包缺失时只丢标签，不丢数字
    _liquidity = None

# OCTOPUS_LITE=0 / false / no → 关闭速查卡（同时关闭全篇瘦身，回到全量长版）。
ENABLED = str(os.environ.get("OCTOPUS_LITE", "1")).strip().lower() not in ("0", "false", "no")

# 速查卡正文可见文字的字数预算（不含 HTML 标签）。超出按 DROP_ORDER 整行撤下。
CARD_CHAR_BUDGET = max(200, int(os.environ.get("OCTOPUS_CARD_CHARS", "600") or 600))

# 卡片副标（口径披露，诚实标注：规则合成 + 非投资建议）。
CAPTION = "30 秒读完 · 数字与下文各栏同源 · 非投资建议"
# 入门版（pipeline.PLAIN()，2026-10-03）：副标与小抄标题去掉口径 / 来源说明，只留一句免责。
CAPTION_PLAIN = "30 秒读完 · 非投资建议"
DISCLAIMER = "规则合成 · 非投资建议"

# ------------------------------------------------------------------
# 🐣 【新手三句话】百句股票梗句库（读取库文件，随时配对使用）
# ------------------------------------------------------------------
MEME_LIB_FILENAME = "stock_memes.json"
MEME_LIB_PATH = os.environ.get("OCTOPUS_MEME_LIB") or os.path.join(_SCRIPT_DIR, MEME_LIB_FILENAME)
MEME_LIBRARY_SIZE = 100

SLOT_LABELS = (
    ("direction", "① 看方向"),
    ("stoploss", "② 放止损"),
    ("discipline", "③ 别动手"),
)
LABEL_BY_SLOT = dict(SLOT_LABELS)
SLOT_BY_LABEL = {label: slot for slot, label in SLOT_LABELS}
SLOT_SCENES = {
    "direction": ("up", "down", "flat"),
    "stoploss": ("defensive", "volatile", "light"),
    "discipline": ("event", "missing", "wait"),
}

# 兜底三句话：仅在库文件缺失或损坏时启用，保证日报永不因文件异常中断。
FALLBACK_BEGINNER_TIPS = (
    ("① 看方向", "概率够六成才算有方向，五五开就是抛硬币——没有方向的时候，不亏就是赚。"),
    ("② 放止损", "按卡上「止损」价位挂单；没有价位就给自己画好止损红线，先想输多少再想赚多少。"),
    ("③ 别动手", "数据缺、当天有 ★★★ 大数据、概率五五开——三种情况都先观望，市场天天开门。"),
)
TIPS_TITLE = "🐣 新手三句话（百句股票梗库 · 随时配对）"
TIPS_TITLE_PLAIN = "🐣 新手三句话"

_MEME_CACHE = {"path": None, "mtime_ns": None, "items": ()}


def _pick(options, seed):
    """按 crc32(seed) 确定性选池：同一输入永远同一句，不同日期/场景自动切换。"""
    if not options:
        return None
    idx = zlib.crc32(str(seed).encode("utf-8")) % len(options)
    return options[idx]


def _norm_slot(slot):
    """把 'direction' / '① 看方向' / '看方向' 等别名归一到标准槽位键。"""
    if not slot:
        return None
    s = str(slot).strip()
    if s in LABEL_BY_SLOT:
        return s
    if s in SLOT_BY_LABEL:
        return SLOT_BY_LABEL[s]
    for key, label in SLOT_LABELS:
        if s in label:
            return key
    return None


def compose_meme_pair(meme_item, pair_item=None):
    """把上句「股票梗句」与下句「新手心法」配对拼成完整一句（<梗句>——<心法>）。"""
    meme_txt = (meme_item.get("meme") if isinstance(meme_item, dict) else meme_item) or ""
    meme_txt = str(meme_txt).strip().rstrip("—-，。； ")
    if pair_item is None and isinstance(meme_item, dict):
        pair_txt = str(meme_item.get("pair") or "").strip()
    else:
        pair_txt = (pair_item.get("pair") if isinstance(pair_item, dict) else pair_item) or ""
        pair_txt = str(pair_txt).strip()
    if meme_txt and pair_txt:
        return f"{meme_txt}——{pair_txt}"
    return meme_txt or pair_txt


def _normalize_meme_entry(raw, index):
    """校验并标准化库文件中的单条股票梗句记录；非法记录返回 None。"""
    if not isinstance(raw, dict):
        return None
    slot = _norm_slot(raw.get("slot") or raw.get("label")) or "direction"
    label = LABEL_BY_SLOT.get(slot, "① 看方向")
    meme = str(raw.get("meme") or "").strip()
    pair = str(raw.get("pair") or "").strip()
    text = str(raw.get("text") or "").strip()
    if not meme and "——" in text:
        meme, pair = [p.strip() for p in text.split("——", 1)]
    if not text and (meme or pair):
        text = compose_meme_pair(meme, pair)
    if not meme or not text:
        return None
    scene = str(raw.get("scene") or "general").strip() or "general"
    mid = str(raw.get("id") or f"M{index:03d}").strip()
    kw_raw = raw.get("keywords") or []
    keywords = [str(k).strip() for k in kw_raw if str(k).strip()] if isinstance(kw_raw, (list, tuple)) else []
    return {
        "id": mid,
        "slot": slot,
        "label": label,
        "scene": scene,
        "meme": meme,
        "pair": pair,
        "text": text,
        "keywords": keywords,
    }


def load_meme_library(path=None, *, force=False):
    """读取股票梗句库文件（默认 `output/stock_memes.json`），返回标准化词条列表。

    按 (abspath, mtime_ns) 自动缓存：库文件更新或切换路径时自动重读；
    文件不存在或格式损坏时返回空列表（调用方回退到 FALLBACK_BEGINNER_TIPS）。
    """
    target_raw = path or os.environ.get("OCTOPUS_MEME_LIB") or MEME_LIB_PATH
    target = os.path.abspath(str(target_raw))
    try:
        st = os.stat(target)
        mtime_ns = st.st_mtime_ns
    except OSError:
        return []
    if not force and _MEME_CACHE["path"] == target and _MEME_CACHE["mtime_ns"] == mtime_ns:
        return [dict(item, keywords=list(item["keywords"])) for item in _MEME_CACHE["items"]]
    try:
        with open(target, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception:
        return []
    raw_list = doc.get("memes") if isinstance(doc, dict) else (doc if isinstance(doc, list) else [])
    if not isinstance(raw_list, list):
        return []
    items = []
    for idx, entry in enumerate(raw_list, start=1):
        norm = _normalize_meme_entry(entry, idx)
        if norm:
            items.append(norm)
    if path is None:
        _MEME_CACHE["path"] = target
        _MEME_CACHE["mtime_ns"] = mtime_ns
        _MEME_CACHE["items"] = tuple(items)
    return [dict(item, keywords=list(item["keywords"])) for item in items]


def all_stock_memes(path=None):
    """返回库文件中的全部股票梗句列表（默认 100 句）。"""
    return load_meme_library(path=path)


def meme_by_id(meme_id, *, library=None, path=None):
    """按 ID（如 'M001'）查找单条股票梗句。"""
    lib = library if library is not None else load_meme_library(path=path)
    target = str(meme_id or "").strip()
    for item in lib:
        if item.get("id") == target:
            return dict(item, keywords=list(item.get("keywords") or []))
    return None


def memes_by_slot(slot, *, scene=None, library=None, path=None):
    """按槽位（direction / stoploss / discipline）及可选场景筛选梗句池。"""
    lib = library if library is not None else load_meme_library(path=path)
    slot_key = _norm_slot(slot)
    out = [item for item in lib if not slot_key or item.get("slot") == slot_key]
    if scene:
        sc = str(scene).strip()
        out = [item for item in out if item.get("scene") == sc]
    return [dict(item, keywords=list(item.get("keywords") or [])) for item in out]


def infer_card_scenes(ctx):
    """根据当次盘面 ctx 推断三句话各自对应的行情场景（纯确定性、无副作用）。

    返回 {"direction": "up"|"down"|"flat",
          "stoploss":  "defensive"|"volatile"|"light",
          "discipline": "event"|"missing"|"wait"}
    """
    ctx = ctx if isinstance(ctx, dict) else {}
    ai = ctx.get("ai") or {}
    weekly = ctx.get("weekly") or {}
    quant = ctx.get("quant") or {}
    rows = ((weekly.get("daily") or {}).get("rows")) or []
    t1 = next((r for r in rows if isinstance(r, dict) and int(r.get("k") or 0) == 1), None) or {}
    adv = t1.get("advice") or {}

    # ① 看方向场景：优先策略信号分与 T+1 概率/方向，其次周度与量化概率
    p_t1 = t1.get("p_day") if t1.get("p_day") is not None else t1.get("p_cum")
    try:
        p_t1_val = float(p_t1) if p_t1 is not None else None
    except (TypeError, ValueError):
        p_t1_val = None
    try:
        ai_score = float(ai.get("score")) if ai.get("available") and ai.get("score") is not None else None
    except (TypeError, ValueError):
        ai_score = None
    ai_label = str(ai.get("sentiment_label") or "") if ai.get("available") else ""
    head_q = quant.get("headline") or {}
    try:
        q_p = float(head_q.get("p_up")) if head_q.get("available") and head_q.get("p_up") is not None else None
    except (TypeError, ValueError):
        q_p = None
    entry_w = weekly.get("entry") or {}
    try:
        w_p = float(entry_w.get("p_up")) if entry_w.get("p_up") is not None else None
    except (TypeError, ValueError):
        w_p = None

    t1_dir = str(t1.get("direction") or "").strip().lower()
    if ((ai_score is not None and ai_score > 8)
            or any(w in ai_label for w in ("偏多", "看涨", "看多"))
            or t1_dir == "up"
            or (p_t1_val is not None and p_t1_val >= 0.60)
            or (ai_score is None and p_t1_val is None
                and ((q_p is not None and q_p >= 0.60) or (w_p is not None and w_p >= 0.60)))):
        dir_scene = "up"
    elif ((ai_score is not None and ai_score < -8)
          or any(w in ai_label for w in ("偏空", "看跌", "看空"))
          or t1_dir == "down"
          or (p_t1_val is not None and p_t1_val <= 0.40)
          or (ai_score is None and p_t1_val is None
              and ((q_p is not None and q_p <= 0.40) or (w_p is not None and w_p <= 0.40)))):
        dir_scene = "down"
    else:
        dir_scene = "flat"

    # ② 放止损场景：看流动性水位、建议仓位与板块波动
    liq = quant.get("liquidity") or {}
    try:
        liq_score = float(liq.get("score")) if liq.get("available") and liq.get("score") is not None else None
    except (TypeError, ValueError):
        liq_score = None
    try:
        pos = int(adv.get("position")) if adv.get("position") is not None else None
    except (TypeError, ValueError):
        pos = None
    sectors = [s for s in (ai.get("quant_sectors") or []) if isinstance(s, dict)]
    max_sec_chg = 0.0
    for s in sectors:
        try:
            max_sec_chg = max(max_sec_chg, abs(float(s.get("chg") or 0.0)))
        except (TypeError, ValueError):
            pass

    if (dir_scene == "down"
            or (liq_score is not None and liq_score < 45)
            or (pos is not None and pos <= 15 and p_t1_val is not None and p_t1_val < 0.48)):
        stop_scene = "defensive"
    elif (pos is not None and pos >= 25) or max_sec_chg >= 6.5:
        stop_scene = "volatile"
    else:
        stop_scene = "light"

    # ③ 别动手场景：看今明重要日程与数据覆盖率
    cov = ctx.get("coverage") or {}
    try:
        cov_today = int(cov.get("today")) if cov.get("today") is not None else None
        cov_total = int(cov.get("total")) if cov.get("total") is not None else None
    except (TypeError, ValueError):
        cov_today = cov_total = None

    has_big_event = False
    base = ctx.get("today")
    cal_items = [it for it in ((ctx.get("cal") or {}).get("items") or []) if isinstance(it, dict)]
    if base is not None and cal_items:
        for it in cal_items:
            iso = str(it.get("date") or "")
            try:
                day = datetime.strptime(iso, "%Y-%m-%d").date()
            except ValueError:
                continue
            if 0 <= (day - base).days < MUSTSEE_DAYS and int(it.get("imp") or 0) >= MUSTSEE_MIN_IMP:
                has_big_event = True
                break

    if cov_total and cov_today is not None and cov_today * 4 < cov_total * 3:
        disc_scene = "missing"
    elif has_big_event:
        disc_scene = "event"
    else:
        disc_scene = "wait"

    return {
        "direction": dir_scene,
        "stoploss": stop_scene,
        "discipline": disc_scene,
    }


def _ctx_seed(ctx, scenes=None):
    """从 ctx 提炼与字典键顺序无关的确定性种子：同输入必同，跨日或变盘自动换句。"""
    ctx = ctx if isinstance(ctx, dict) else {}
    scenes = scenes or infer_card_scenes(ctx)
    date_str = str(ctx.get("date_str") or "").strip()
    today_obj = ctx.get("today")
    today_iso = today_obj.isoformat() if hasattr(today_obj, "isoformat") else str(today_obj or "")
    ai = ctx.get("ai") or {}
    ai_part = f"{ai.get('sentiment_label') or ''}:{ai.get('score') if ai.get('available') else ''}"
    weekly = ctx.get("weekly") or {}
    rows = ((weekly.get("daily") or {}).get("rows")) or []
    t1 = next((r for r in rows if isinstance(r, dict) and int(r.get("k") or 0) == 1), None) or {}
    adv = t1.get("advice") or {}
    t1_part = f"{t1.get('date') or ''}:{t1.get('p_day')}:{adv.get('position')}:{adv.get('stop_price')}"
    quant = ctx.get("quant") or {}
    liq = quant.get("liquidity") or {}
    q_part = f"{(quant.get('headline') or {}).get('p_up')}:{liq.get('score') if liq.get('available') else ''}"
    cov = ctx.get("coverage") or {}
    cov_part = f"{cov.get('today')}/{cov.get('total')}"
    sc_part = f"{scenes.get('direction')}|{scenes.get('stoploss')}|{scenes.get('discipline')}"
    return f"{date_str}|{today_iso}|{sc_part}|{ai_part}|{t1_part}|{q_part}|{cov_part}"


def pair_stock_meme(scene=None, *, slot=None, keyword=None, seed="",
                    library=None, path=None, cross_pair=False):
    """从百句股票梗句库中随时配对抽取一条梗句（支持按槽位/场景/关键词/上下句自由配对）。

    参数：
      scene      场景名（如 'up'/'down'/'flat'/'defensive'/'volatile'/'light'/'event'/'missing'/'wait'）
      slot       槽位（'direction'/'stoploss'/'discipline' 或 '① 看方向'/'② 放止损'/'③ 别动手'）
      keyword    可选关键词（匹配 meme / pair / text / keywords）
      seed       确定性种子（默认空串）
      library    可选外部传入的词条列表；未传则读取库文件
      path       可选自定义库文件路径
      cross_pair 为 True 时将同池内一条「股票梗句」与另一条「新手心法」交叉配对组合
    """
    lib = library if library is not None else load_meme_library(path=path)
    if not lib:
        return None
    slot_key = _norm_slot(slot)
    sc = str(scene or "").strip()
    kw = str(keyword or "").strip()

    def _match_kw(item):
        if not kw:
            return True
        if kw in item.get("meme", "") or kw in item.get("pair", "") or kw in item.get("text", ""):
            return True
        return any(kw in k or k in kw for k in (item.get("keywords") or []))

    slot_pool = [it for it in lib if not slot_key or it.get("slot") == slot_key] or list(lib)
    candidates = [it for it in slot_pool if (not sc or it.get("scene") == sc) and _match_kw(it)]
    if not candidates and sc:
        candidates = [it for it in slot_pool if it.get("scene") == sc]
    if not candidates and kw:
        candidates = [it for it in slot_pool if _match_kw(it)]
    if not candidates and sc:
        candidates = [it for it in lib if it.get("scene") == sc]
    if not candidates and kw:
        candidates = [it for it in lib if _match_kw(it)]
    if not candidates:
        candidates = slot_pool

    chosen = dict(_pick(candidates, f"{seed}|meme"), keywords=list(_pick(candidates, f"{seed}|meme").get("keywords") or []))
    if cross_pair and len(candidates) > 1:
        idx_m = zlib.crc32(f"{seed}|meme".encode("utf-8")) % len(candidates)
        idx_p = zlib.crc32(f"{seed}|pair".encode("utf-8")) % len(candidates)
        if idx_p == idx_m:
            idx_p = (idx_m + 1) % len(candidates)
        partner = candidates[idx_p]
        chosen["pair"] = partner["pair"]
        chosen["pair_id"] = partner["id"]
        chosen["text"] = compose_meme_pair(chosen["meme"], partner["pair"])
    else:
        chosen["pair_id"] = chosen["id"]
        chosen["text"] = compose_meme_pair(chosen["meme"], chosen["pair"])
    return chosen


def pair_memes(count=3, *, ctx=None, slot=None, scene=None, keyword=None,
               seed="", library=None, path=None, cross_pair=False):
    """随时配对抽取多条不重复的股票梗句（默认 3 条）。"""
    lib = library if library is not None else load_meme_library(path=path)
    if not lib or count <= 0:
        return []
    if ctx is not None and not slot and not scene and not keyword and count == 3:
        return pair_beginner_entries(ctx, seed=seed or None, library=lib, cross_pair=cross_pair)
    picked = []
    used_ids = set()
    base_seed = str(seed or _ctx_seed(ctx or {}))
    for i in range(int(count)):
        remaining = [it for it in lib if it.get("id") not in used_ids] or list(lib)
        entry = pair_stock_meme(scene, slot=slot, keyword=keyword,
                                seed=f"{base_seed}|#{i}", library=remaining,
                                cross_pair=cross_pair)
        if entry:
            used_ids.add(entry["id"])
            picked.append(entry)
    return picked


def pair_beginner_entries(ctx=None, *, seed=None, library=None, path=None, cross_pair=False):
    """按 ctx 为【新手三句话】配对 3 条完整词条（① 看方向 / ② 放止损 / ③ 别动手）。"""
    lib = library if library is not None else load_meme_library(path=path)
    if not lib:
        return []
    scenes = infer_card_scenes(ctx)
    base_seed = str(seed) if seed is not None else _ctx_seed(ctx, scenes)
    entries = []
    for slot_key, slot_label in SLOT_LABELS:
        sc = scenes.get(slot_key)
        entry = pair_stock_meme(sc, slot=slot_key,
                                seed=f"{base_seed}|{slot_key}|{sc}",
                                library=lib, cross_pair=cross_pair)
        if entry:
            entry["label"] = slot_label
            entries.append(entry)
    return entries


def pair_beginner_tips(ctx=None, *, seed=None, library=None, path=None, cross_pair=False):
    """按 ctx 从百句股票梗句库配对生成【新手三句话】[(label, text), ...]；库缺失时回退兜底。"""
    entries = pair_beginner_entries(ctx, seed=seed, library=library, path=path, cross_pair=cross_pair)
    if len(entries) == len(SLOT_LABELS):
        return [(e["label"], e["text"]) for e in entries]
    return list(FALLBACK_BEGINNER_TIPS)


# 模块导入时预读一次百句股票梗库，并生成默认配对三句话（兼容旧引用 short.BEGINNER_TIPS）。
STOCK_MEMES = load_meme_library()
BEGINNER_TIPS = tuple(pair_beginner_tips())

# 超预算时的撤行顺序：**先撤锦上添花，最后才动「明天怎么做」**；
# setup（明日剧本）与 coverage（数据底）永不撤。
DROP_ORDER = ("news", "money", "sector", "mustsee", "week")

# 行顺序（小的排前面）：明日剧本 → 七日风 → 今明必看 → 板块强弱 → 水位 → 风声 → 数据底。
LINE_ORDER = {"setup": 0, "week": 1, "mustsee": 2, "sector": 3,
              "money": 4, "news": 5, "coverage": 6}

# 短线客真正要盯的重要度门槛：★★ 以上（★ 级多为周报 / 讲话，噪音大）。
MUSTSEE_MIN_IMP = 2
MUSTSEE_MAX = 4
MUSTSEE_MAX_CHARS = 88      # 这一行的字数上限：装不下就少列几条并如实写「等 N 项」
MUSTSEE_NAME_CHARS = 16     # 单条时点名称截断字数（完整名称仍在「时间节点」栏目里）
MUSTSEE_DAYS = 2            # 只看今天 + 明天
SECTOR_MAX = 3
SECTOR_NAME_CHARS = 8       # 板块名截断字数（完整榜单仍在「策略研判」栏目里）


# ------------------------------------------------------------------
# 数字格式化：None → 缺席（绝不补 0），口径与正文渲染层一致
# ------------------------------------------------------------------
def _p0(value):
    """0.52 → '52%'；非法值返回 None。"""
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return None


def _n0(value):
    """24589.4 → '24,589'；非法值返回 None。"""
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return None


def _signed(value, digits=2):
    """1.234 → '+1.23'；非法值返回 None。"""
    try:
        return f"{float(value):+.{digits}f}"
    except (TypeError, ValueError):
        return None


def _yi(value):
    """亿元（与资金流动性栏同一口径：整数亿）。"""
    try:
        return f"{float(value):,.0f} 亿"
    except (TypeError, ValueError):
        return None


def _day_md(date_str):
    """'2026-10-01' → '10-01'；已短或空值原样返回。"""
    text = str(date_str or "")
    return text[5:10] if len(text) >= 10 else text


def _dns_arrow(dns):
    """新闻情绪 DNS → ▲/▼/■（阈值与正文「市场情绪全景」一致：±0.2）。"""
    try:
        value = float(dns)
    except (TypeError, ValueError):
        return "■"
    return "▲" if value > 0.2 else ("▼" if value < -0.2 else "■")


def _strip_tags(text):
    return re.sub(r"<[^>]+>", "", str(text or ""))


def _pack(labels, budget, sep="、"):
    """按字数预算装条数：装不下的不硬塞，末尾如实写「等 N 项」（绝不静默丢内容）。"""
    labels = [str(x) for x in labels if str(x).strip()]
    if not labels:
        return ""
    kept = []
    used = 0
    for text in labels:
        extra = len(text) + (len(sep) if kept else 0)
        if kept and used + extra > budget:
            break
        kept.append(text)
        used += extra
    out = sep.join(kept)
    if len(labels) > len(kept):
        out += f" 等 {len(labels)} 项"
    return out


# ------------------------------------------------------------------
# 各行取材（每行一个函数：数据不在就返回 None，绝不留占位符）
# ------------------------------------------------------------------
def _line_setup(ctx):
    """① 明日剧本：T+1 的概率 / 预期区间 / 建议仓位 / 止损 / 止盈（逐日表第一行原样搬运）。"""
    weekly = ctx.get("weekly") or {}
    rows = ((weekly.get("daily") or {}).get("rows")) or []
    row = next((r for r in rows if isinstance(r, dict) and int(r.get("k") or 0) == 1), None)
    if not row:
        return None
    adv = row.get("advice") or {}
    head = (f'{_day_md(row.get("date"))} {str(row.get("weekday") or "")}'.strip()
            or "下一交易日")
    bits = []
    label = str(row.get("label") or "").strip()
    prob = row.get("p_day") if row.get("p_day") is not None else row.get("p_cum")
    p_txt = _p0(prob)
    if label and p_txt:
        bits.append(f"{label} {p_txt}")
    elif label or p_txt:
        bits.append(label or p_txt)
    lo, hi = _n0(row.get("band_lo")), _n0(row.get("band_hi"))
    if lo and hi:
        bits.append(f"区间 {lo}–{hi}")
    if adv.get("position") is not None:
        bits.append(f"仓位 ≤{int(adv['position'])}%")
    stop = _n0(adv.get("stop_price"))
    if stop:
        bits.append(f"止损 {stop}")
    take = _n0(adv.get("take_profit"))
    if take:
        bits.append(f"止盈 {take}")
    if len(bits) < 2:            # 只剩一个数字就不成「剧本」，整行缺席
        return None
    icon = {"up": "▲", "down": "▼"}.get(row.get("direction"), "■")
    return ("setup", (f"{icon} 明日剧本", f"<b>{head}</b> · " + " · ".join(bits)))


def _line_week(ctx):
    """② 七日风：整段累计概率（+ 量化 5 日概率；两者视界不同，如实并列不混算）。"""
    bits = []
    entry = (ctx.get("weekly") or {}).get("entry") or {}
    if entry.get("label"):
        p_up = _p0(entry.get("p_up"))
        horizon = entry.get("target_sessions")
        label = str(entry["label"])
        # 展示文案（_horizon_label）本身已带「P(7日涨) 62%」时不再重复拼一次
        bits.append(label + (f' · P({horizon}日涨) {p_up}'
                             if p_up and horizon and "P(" not in label else ""))
    quant = ctx.get("quant") or {}
    head_q = quant.get("headline") or {}
    if head_q.get("available") and head_q.get("p_up") is not None:
        bits.append(f'量化 5 日 {head_q.get("arrow", "■")} {_p0(head_q["p_up"])}'
                    f'（{str(quant.get("target_label") or "下一交易日")}）')
    if not bits:
        return None
    return ("week", ("■ 七日风", " · ".join(bits)))


def _line_mustsee(ctx):
    """③ 今明必看：今天 + 明天的 ★★ 以上时点（最多 4 条），没有就如实说没有。

    「今明」以 ctx["today"]（报告日的 date 对象，由 pipeline 传入）为基准逐日算 T+n，
    而不是取窗口里最早的两天——否则报告日之后的远期读数会被误当成「明天」。
    """
    cal = ctx.get("cal") or {}
    items = [it for it in (cal.get("items") or []) if isinstance(it, dict)]
    dated = [(str(it.get("date") or ""), _day_md(it.get("date")), it) for it in items]
    dated = [x for x in dated if x[0]]
    if not dated:
        return None
    base = ctx.get("today")
    near = set()
    if base is not None:
        for iso, _md, _it in dated:
            try:
                day = datetime.strptime(iso, "%Y-%m-%d").date()
            except ValueError:
                continue
            if 0 <= (day - base).days < MUSTSEE_DAYS:
                near.add(iso)
    else:                                   # 没有报告日基准 → 不猜「今明」，整行缺席
        return None
    picked = [x for x in dated if x[0] in near
              and int(x[2].get("imp") or 0) >= MUSTSEE_MIN_IMP]
    if not picked:               # 今明没有重要时点 → 如实说「无」，不硬凑远处的日子
        return ("mustsee", ("⏰ 今明必看", "无 ★★ 以上数据 / 事件（可正常操作）"))
    picked.sort(key=lambda x: (x[0], str(x[2].get("time") or "99:99")))
    labels = []
    for iso, md, it in picked[:MUSTSEE_MAX]:
        name = str(it.get("name") or "")[:MUSTSEE_NAME_CHARS]
        city = str(it.get("city") or "")
        when = str(it.get("time") or "")[:5]
        when = "" if when in ("", "99:99") else when
        labels.append(f'{md}{" " + city if city else ""} {name}{" " + when if when else ""}')
    return ("mustsee", ("⏰ 今明必看",
                        _pack([x.strip() for x in labels], MUSTSEE_MAX_CHARS)))


def _line_sector(ctx):
    """④ 板块强弱：各取前 3（优先策略研判量化强度榜，缺席时用 A股全景板块热力）。"""
    sectors = [s for s in ((ctx.get("ai") or {}).get("quant_sectors") or [])
               if isinstance(s, dict)]

    def tag(name, chg):
        name = str(name or "")[:SECTOR_NAME_CHARS]
        chg = _signed(chg)
        return name + (f" {chg}%" if chg else "")

    # 强弱按趋势分（composite）的正负号分堆：样本不足 3+3 时有几只列几只，
    # 绝不让「领跌板块」混进强的一堆（隐喻必须说真话）。
    strong, weak = [], []
    for sec in [s for s in sectors if (s.get("composite") or 0) > 0][:SECTOR_MAX]:
        strong.append(tag(sec.get("name"), sec.get("chg")))
    for sec in [s for s in sectors if (s.get("composite") or 0) < 0][-SECTOR_MAX:]:
        weak.append(tag(sec.get("name"), sec.get("chg")))
    if not strong:               # 策略研判缺席 → 用 A股全景的板块热力兜底（同源同口径）
        pan_sectors = (ctx.get("pan") or {}).get("sectors") or {}
        for key, bucket in (("leading", strong), ("lagging", weak)):
            for it in (pan_sectors.get(key) or [])[:SECTOR_MAX]:
                if isinstance(it, dict):
                    bucket.append(tag(it.get("name"), it.get("chg_pct")))
    strong = [s.strip() for s in strong if s.strip()][:SECTOR_MAX]
    weak = [w.strip() for w in weak if w.strip()][:SECTOR_MAX]
    if not strong and not weak:
        return None
    bits = []
    if strong:
        bits.append("强 " + "、".join(strong))
    if weak:
        bits.append("弱 " + "、".join(weak))
    return ("sector", ("⚡ 板块强弱", " · ".join(bits)))


def _line_money(ctx):
    """⑤ 水位：流动性综合分 + 南向成交与量能标签（水少就别追高）。"""
    liq = (ctx.get("quant") or {}).get("liquidity") or {}
    if not liq.get("available"):
        return None
    bits = []
    if liq.get("score") is not None:
        bits.append(f'{float(liq["score"]):.0f}/100 {str(liq.get("label") or "")}'.strip())
    south = liq.get("south") or {}
    if south.get("available"):
        amount = _yi(south.get("latest"))
        flow = ""
        if _liquidity is not None:
            try:
                # 只取标签的第一段（放量 / 缩量 / 中性）：分位那句在「资金流动性分析」
                # 栏目里原样保留，卡上不重复占字数。
                flow = str(_liquidity.flow_label(south) or "").split(" · ")[0]
            except Exception:
                flow = ""
        if amount:
            bits.append("南向 " + amount + (f"（{flow}）" if flow and flow != "None" else ""))
    if not bits:
        return None
    return ("money", ("💧 水位", " · ".join(bits)))


def _line_news(ctx):
    """⑥ 风声：新闻情绪整体 DNS + 最暖 / 最冷点名（情绪是后视镜，只作氛围参考）。"""
    ms = (ctx.get("senti") or {}).get("market_summary") or {}
    if not ms.get("available") or ms.get("overall_dns") is None:
        return None
    bits = [f'{_dns_arrow(ms["overall_dns"])} {str(ms.get("overall_label") or "中性")}'
            f' DNS {_signed(ms["overall_dns"])}']
    hot, cold = ms.get("hottest") or {}, ms.get("coldest") or {}
    if hot.get("name"):
        bits.append(f'最暖 {hot["name"]}')
    if cold.get("name") and cold.get("key") != hot.get("key"):
        bits.append(f'最冷 {cold["name"]}')
    return ("news", ("📣 风声", " · ".join(bits)))


def _line_coverage(ctx):
    """⑦ 数据底：当天源 n/m（数据不新鲜时，短线客最该先知道这件事）。"""
    cov = ctx.get("coverage") or {}
    today, total = cov.get("today"), cov.get("total")
    if not total:
        return None
    return ("coverage", ("🔎 数据底", f"当天源 {today}/{total} · 数字与下文各栏同源"))


_LINE_BUILDERS = (_line_setup, _line_week, _line_mustsee, _line_sector,
                  _line_money, _line_news, _line_coverage)


# ------------------------------------------------------------------
# 组卡：取材 → 预算内整行裁剪 → 输出纯文本（渲染交给 pipeline 的 kit）
# ------------------------------------------------------------------
def _lead_text(ctx):
    """一句定调：策略研判倾向（信号分）→ 量化 headline → 诚实兜底「信息不足」。"""
    ai = ctx.get("ai") or {}
    if ai.get("available"):
        score = ai.get("score") or 0
        arrow = "▲" if score > 8 else ("▼" if score < -8 else "■")
        try:
            score_txt = f"{int(score):+d}"
        except (TypeError, ValueError):
            score_txt = ""
        return (f'{arrow} 今日定调 {str(ai.get("sentiment_label") or "中性")}'
                + (f"（信号 {score_txt}）" if score_txt else ""))
    quant = ctx.get("quant") or {}
    head = quant.get("headline") or {}
    if head.get("available") and head.get("label"):
        p_up = _p0(head.get("p_up"))
        return (f'{head.get("arrow", "■")} 今日定调 {head["label"]}'
                + (f" {p_up}" if p_up else "")
                + f'（{str(quant.get("target_label") or "下一交易日")}）')
    return "■ 今日定调：现有数据不足以判断方向，先看下面的时点与水位"


def build_card(ctx, *, tips=None, tips_in_card=True):
    """按 ctx 组装速查卡；一行数据都拿不到时返回 None（整卡缺席，不占版面）。

    返回 {"lead": str, "pairs": [(label, value)], "tips": [(label, text)],
          "dropped": [key], "text": str}
      lead    —— 一句定调（大字）；
      pairs   —— 数据行（已按预算整行撤下部分行，顺序按 LINE_ORDER）；
      tips    —— 从库文件（100 句股票梗句）按当次盘面配对出的【新手三句话】；
      dropped —— 因字数预算被撤下的行 key（如实留痕，绝不静默丢内容）；
      text    —— 全部可见文字（去标签）拼接，字数预算与测试断言共用同一口径。

    tips / tips_in_card（2026-10-16 新增，用户要求「新手三句话放在卦象后」）：
      tips_in_card=True（默认，向后兼容）时【新手三句话】计入卡片字数预算，
      由调用方渲染在卡尾；传 False 表示三句话改由卷首卦象之后渲染（pipeline），
      此时预算与 text 都不再计入这三句话——**预算口径永远跟实际渲染的一致**，
      否则卡片会为不存在的文字白白撤行。tips 可由调用方预先配对好传入，
      保证「卷首三句话」与「卡上原本的三句话」是同一组，绝不出现两套。
    """
    ctx = ctx if isinstance(ctx, dict) else {}
    lines = []
    for build in _LINE_BUILDERS:
        try:
            line = build(ctx)
        except Exception:                       # 单行出错只丢该行，不影响日报
            line = None
        if line:
            lines.append(line)

    droppable = [ln for ln in lines if ln[0] != "coverage"]
    if not droppable:
        return None                             # 一行数据都没有 → 整卡缺席

    lead = _lead_text(ctx)
    if tips is None:
        tips = pair_beginner_tips(ctx)

    def plain(pairs):
        blob = [lead, DISCLAIMER]
        blob += [f"{a}{b}" for a, b in pairs]
        if tips_in_card:                    # 三句话移出卡片后不再占卡片的字数预算
            blob += [f"{a}{b}" for a, b in tips]
        return _strip_tags("".join(blob))

    kept = list(droppable)
    dropped = []
    while kept and len(plain([(a, b) for _k, (a, b) in kept])) > CARD_CHAR_BUDGET:
        rank = {key: i for i, key in enumerate(DROP_ORDER)}
        victim = min(kept, key=lambda ln: rank.get(ln[0], len(rank)))
        kept.remove(victim)
        dropped.append(victim[0])

    kept.sort(key=lambda ln: LINE_ORDER.get(ln[0], 99))
    pairs = [(label, value) for _key, (label, value) in kept]
    pairs += [(label, value) for key, (label, value) in lines if key == "coverage"]
    return {"lead": lead, "pairs": pairs, "tips": tips,
            "dropped": dropped, "text": plain(pairs)}


def card_char_count(card):
    """卡片可见文字字数（不含 HTML 标签）；测试用它守字数预算。"""
    if not card:
        return 0
    return len(str(card.get("text") or ""))
