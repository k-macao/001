#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MACD 日线策略：市场库 → 本次已有日线 → 免费主备源，计算与呈现不联网。

固定 MACD(12,26,9)，国内柱体 = 2×(DIF−DEA)。只研究已收盘日线；
金叉且双线在零轴上方才提示入场，死叉退出，只做多 / 空仓，不推导上涨概率。
"""
from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import macd_derivatives as derived
from . import providers, stats

FAST, SLOW, SIGNAL = 12, 26, 9
MIN_BARS = SLOW + SIGNAL + 1       # 36 根：最新值与前一日均已过预热门槛
MAX_LAG_DAYS = 4                  # 与交易类新鲜度一致，长假超过门槛也不发旧信号
DEFAULT_SPECS = [
    ("恒生指数", "^HSI"), ("恒生科技", "^HSTECH"), ("国企指数", "^HSCEI"),
    ("上证指数", "000001.SS"), ("深证成指", "399001.SZ"), ("创业板指", "399006.SZ"),
    ("道琼斯", "^DJI"), ("标普500", "^GSPC"), ("纳斯达克", "^IXIC"),
]


def symbol_specs():
    """OCTOPUS_MACD_SYMBOLS='^HSI:恒生指数,0700.HK:腾讯控股'；去重且最多 30 只。"""
    raw = os.environ.get("OCTOPUS_MACD_SYMBOLS", "").strip()
    if not raw:
        return list(DEFAULT_SPECS)
    specs, seen = [], set()
    for chunk in raw.split(","):
        code, _, name = chunk.strip().partition(":")
        if code and code not in seen:
            seen.add(code)
            specs.append((name.strip() or code, code))
    return specs[:30] or list(DEFAULT_SPECS)


def _now(now=None):
    moment = now or datetime.now(providers.CST)
    return moment.replace(tzinfo=providers.CST) if moment.tzinfo is None else moment


def completed_bars(bars, code, *, now=None):
    """有限正收盘 + 合法已收盘行情日，按日去重、升序；不补缺日或补数。"""
    moment = _now(now)
    by_date = {}
    for bar in bars or []:
        if not isinstance(bar, dict) or isinstance(bar.get("close"), bool):
            continue
        try:
            close = float(bar["close"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        day = str(bar.get("date") or "")
        if (not math.isfinite(close) or close <= 0
                or not providers.is_session_closed(code, day, now=moment)):
            continue
        by_date[day] = {**bar, "date": day, "close": close}
    return [by_date[day] for day in sorted(by_date)]


def _data_problem(bars, code, now):
    if len(bars) < MIN_BARS:
        return f"已收盘日线不足（{len(bars)}/{MIN_BARS} 根）"
    report_day = now.astimezone(providers.CST).date()
    age = (report_day - datetime.strptime(bars[-1]["date"], "%Y-%m-%d").date()).days
    if age > MAX_LAG_DAYS:
        return f"日线过旧（截至 {bars[-1]['date']}，滞后 {age} 天）"
    return None


def _cross(previous, current, epsilon):
    if previous <= epsilon and current > epsilon:
        return "golden"
    if previous >= -epsilon and current < -epsilon:
        return "death"
    return None


def analyze_bars(bars, *, label, code, source="已有日线", now=None, weekly=None):
    """纯计算入口。每个时点的 EMA / 交叉只读取 ≤该日的数据。"""
    moment = _now(now)
    bars = completed_bars(bars, code, now=moment)
    problem = _data_problem(bars, code, moment)
    if problem:
        return {"available": False, "label": label, "code": code, "reason": problem,
                "bars_n": len(bars)}
    sequence = stats.macd_series([b["close"] for b in bars], FAST, SLOW, SIGNAL)
    dif, dea, gap = sequence[-1]
    previous_dif, previous_dea, previous_gap = sequence[-2]
    if not all(v is not None and math.isfinite(v) for v in sequence[-1] + sequence[-2]):
        return {"available": False, "label": label, "code": code,
                "reason": "指标计算出现非有限值", "bars_n": len(bars)}
    epsilon = max(bars[-1]["close"], 1.0) * 1e-10
    cross = _cross(previous_gap, gap, epsilon)
    above, below = min(dif, dea) > epsilon, max(dif, dea) < -epsilon
    axis = "零轴上方" if above else ("零轴下方" if below else "零轴附近/跨轴")
    state = ("金叉" if cross == "golden" else "死叉" if cross == "death" else
             "多头延续" if gap > epsilon else "空头延续" if gap < -epsilon else "双线贴合")
    if gap > epsilon:
        momentum = "红柱扩大" if gap > previous_gap + epsilon else (
            "红柱收敛" if gap < previous_gap - epsilon else "红柱持平")
    elif gap < -epsilon:
        momentum = "绿柱扩大" if gap < previous_gap - epsilon else (
            "绿柱收敛" if gap > previous_gap + epsilon else "绿柱持平")
    else:
        momentum = "柱体近零"

    if cross == "death" or gap < -epsilon:
        action_key, action = "exit", "▼ 退出/规避"
    elif above and gap > epsilon:
        action_key, action = ("entry", "▲ 试探入场") if cross == "golden" else ("hold", "▲ 多头持有")
    elif cross == "golden" or (below and gap > epsilon):
        action_key, action = "watch", "■ 观察反弹"
    else:
        action_key, action = "watch", "■ 等待确认"

    last_cross = None
    for i in range(MIN_BARS - 1, len(sequence)):
        event = _cross(sequence[i - 1][2], sequence[i][2],
                       max(bars[i]["close"], 1.0) * 1e-10)
        if event:
            last_cross = {"kind": event, "date": bars[i]["date"],
                          "bars_ago": len(bars) - 1 - i}
    row = {
        "available": True, "label": label, "code": code, "as_of": bars[-1]["date"],
        "bars_n": len(bars), "source": source, "dif": dif, "dea": dea,
        "hist": 2.0 * gap, "previous_hist": 2.0 * previous_gap,
        "previous_dif": previous_dif, "previous_dea": previous_dea,
        "cross": cross, "last_cross": last_cross, "axis": axis, "state": state,
        "momentum": momentum, "action_key": action_key, "action": action,
        "zero_filter": {"mode": "strict_both_lines", "long_allowed": above and gap > epsilon,
                        "dif_above": dif > epsilon, "dea_above": dea > epsilon,
                        "relaxed_only": cross == "golden" and dif > epsilon and not above},
    }
    row["derived"] = derived.analyze_derivatives(bars, sequence, code=code, base=row,
                                                 now=moment, weekly=weekly)
    return row


def _indicator_ready(bars):
    points = stats.macd_series([b["close"] for b in bars], FAST, SLOW, SIGNAL)
    return len(points) >= MIN_BARS and all(
        v is not None and math.isfinite(v) for point in points[-2:] for v in point)


def _history_ready(bars, code, now):
    if len(bars) < derived.MIN_SLOPE_BARS or not derived.weekly_ready(bars, code, now=now, verified=False):
        return False
    lows = derived._low_values(bars)
    high = derived._finite(bars[-1].get("high"), positive=True)
    return (sum(v is not None for v in lows[-derived.DIVERGENCE_WINDOW:]) >= derived.DIVERGENCE_MIN
            and lows[-1] is not None and high is not None
            and high >= bars[-1]["close"] * (1 - 1e-8) and high >= lows[-1])


def run_macd(fetch_json=None, *, existing=None, db_root=None, specs=None, now=None,
             extend_history=True, include_bars=False):
    """编排入口。整段选源，绝不拼接不同源 / 复权口径的价格或用快照补日线。

    基础不足 / 过旧时补取 1 年；派生历史不足时尝试 2 年整段替换，失败保留基础。
    已有足够长且不倒退日期的序列优先于短库，避免反复联网。周五报价不完整时
    用免费原生周 K 核验，不推断假期。extend_history=False 禁止这些额外请求。
    """
    moment = _now(now)
    specs = list(specs) if specs is not None else symbol_specs()
    existing = existing or {}
    warnings, db = [], {}
    try:
        import market_db
        db = market_db.load_daily_bars(symbols=[code for _name, code in specs],
                                      root=db_root or market_db.DB_ROOT, now=moment)
    except Exception as exc:
        warnings.append(f"市场库读取失败（{type(exc).__name__}），改用已有日线 / 免费源")

    selected, pending, attempts, newest_known = {}, [], {}, {}
    for label, code in specs:
        db_bars = completed_bars(db.get(code), code, now=moment)
        existing_bars = completed_bars(existing.get(code), code, now=moment)
        attempts[code] = {"db_bars": len(db_bars), "existing_bars": len(existing_bars)}
        newest_known[code] = max((bs[-1]["date"] for bs in (db_bars, existing_bars) if bs), default="")
        # 日期不倒退；同日期的长已有序列可补足短库缺失的派生历史。
        candidates = []
        if (not _data_problem(db_bars, code, moment) and db_bars[-1]["date"] >= newest_known[code]
                and _indicator_ready(db_bars)):
            origins = list(dict.fromkeys(b.get("source") or "市场库·日线" for b in db_bars))
            candidates.append((db_bars, " / ".join(origins), "market_db", None))
        if (not _data_problem(existing_bars, code, moment) and existing_bars[-1]["date"] >= newest_known[code]
                and _indicator_ready(existing_bars)):
            origin = "东方财富" if any(b.get("from_eastmoney") for b in existing_bars) else "Yahoo"
            candidates.append((existing_bars, f"本次量化日线·{origin}", "reused", None))
        if candidates:
            rich = [r for r in candidates if _history_ready(r[0], code, moment)]
            selected[code] = next((r for r in rich if derived.weekly_ready(r[0], code, now=moment)),
                                  rich[0] if rich else candidates[0])
        else:
            pending.append((label, code))

    def _fetch(spec):
        label, code = spec

        def valid(raw_bars):
            clean = completed_bars(raw_bars, code, now=moment)
            return (not _data_problem(clean, code, moment)
                    and clean[-1]["date"] >= newest_known[code] and _indicator_ready(clean))

        try:
            response = providers.fetch_bars(fetch_json, code, rng="1y", timeout=10,
                                              validate_bars=valid, with_source=True)
            bars = completed_bars(response["bars"], code, now=moment)
            if not bars:
                prior = max(attempts[code].values(), default=0)
                return code, None, f"库/已有序列不可用（最多 {prior} 根）；免费主备源无足够新鲜日线"
            return code, (bars, response["source"], "free", response["url"]), None
        except Exception as exc:
            return code, None, f"免费日线补取异常（{type(exc).__name__}）"

    errors = {}
    if pending:
        with ThreadPoolExecutor(max_workers=min(6, len(pending))) as pool:
            for code, record, error in pool.map(_fetch, pending):
                if record:
                    selected[code] = record
                else:
                    errors[code] = error

    history_notes, weekly_selected = {}, {}
    if extend_history and fetch_json:
        short = [(label, code) for label, code in specs if code in selected
                 and not _history_ready(selected[code][0], code, moment)]

        def _extend(spec):
            _label, code = spec
            floor = selected[code][0][-1]["date"]

            def valid(raw):
                clean = completed_bars(raw, code, now=moment)
                return (not _data_problem(clean, code, moment) and clean[-1]["date"] >= floor
                        and _history_ready(clean, code, moment) and _indicator_ready(clean))

            try:
                response = providers.fetch_bars(fetch_json, code, rng="2y", timeout=10,
                                                  validate_bars=valid, with_source=True)
                clean = completed_bars(response["bars"], code, now=moment)
                if clean and valid(clean):
                    return code, (clean, response["source"], "free", response["url"])
            except Exception:
                pass
            return code, None

        if short:
            with ThreadPoolExecutor(max_workers=min(6, len(short))) as pool:
                for code, record in pool.map(_extend, short):
                    if record:
                        selected[code] = record
                    else:
                        history_notes[code] = "免费派生日线补足未成功（历史/高低价），保留基础 MACD；不可用项分别标缺。"

        need_weekly = [(label, code) for label, code in specs if code in selected
                       and not derived.weekly_ready(selected[code][0], code, now=moment)]

        def _fetch_weekly(spec):
            _label, code = spec
            as_of = selected[code][0][-1]["date"]

            def valid(raw):
                weeks = derived.native_weeks(raw, code, as_of=as_of, now=moment)
                if len(weeks) < derived.WEEKLY_MIN:
                    return False
                age = (datetime.strptime(as_of, "%Y-%m-%d").date()
                       - datetime.strptime(weeks[-1]["week_end"], "%Y-%m-%d").date()).days
                return age <= derived.WEEKLY_MAX_LAG and all(
                    v is not None and math.isfinite(v) for v in stats.macd([w["close"] for w in weeks]))

            try:
                response = providers.fetch_bars(fetch_json, code, rng="2y", interval="1wk", timeout=10,
                                                  validate_bars=valid, with_source=True)
                if response["bars"] and valid(response["bars"]):
                    return code, response
            except Exception:
                pass
            return code, None

        if need_weekly:
            with ThreadPoolExecutor(max_workers=min(6, len(need_weekly))) as pool:
                for code, response in pool.map(_fetch_weekly, need_weekly):
                    if response:
                        weekly_selected[code] = response

    items, missing = [], []
    for label, code in specs:
        record = selected.get(code)
        if not record:
            missing.append({"label": label, "code": code, "reason": errors.get(code) or "日线不可用"})
            continue
        bars, source, route, source_url = record
        row = analyze_bars(bars, label=label, code=code, source=source, now=moment,
                           weekly=weekly_selected.get(code))
        if row["available"]:
            row["data_route"] = route
            row["source_url"] = source_url
            if code in history_notes:
                row["history_note"] = history_notes[code]
            items.append(row)
        else:
            missing.append(row)
    dates = sorted({row["as_of"] for row in items})
    result = {
        "available": bool(items), "reason": None if items else "全部标的缺少足够新鲜的已收盘日线",
        "parameters": {"fast": FAST, "slow": SLOW, "signal": SIGNAL},
        "items": items, "missing": missing, "warnings": warnings,
        "coverage": {"valid": len(items), "total": len(specs)},
        "as_of": dates[0] if dates else None, "latest_as_of": dates[-1] if dates else None,
        "golden_n": sum(row["cross"] == "golden" for row in items),
        "death_n": sum(row["cross"] == "death" for row in items),
        "attempts": attempts,
        "derived_coverage": {key: {
            "valid": sum(row["derived"][key]["available"] for row in items),
            "active": sum(row["derived"][key]["active"] for row in items),
            "total": len(items),
        } for key in derived.KEYS},
    }
    # include_bars=True：把本次真正选中的日线一并交出（【游资剑鱼】UZI 趋势分析栏目复用，
    # 避免为同一批标的再取一次数）。调用方负责在入库 / 渲染前弹出，不要把整段日线写进 JSON。
    if include_bars:
        result["bars_by_code"] = {code: list(record[0]) for code, record in selected.items()}
    return result


def render_strategy(result, kit, *, limit=0, plain=False):
    """注入主题套件渲染，不取数。关键公式 / 规则用正文而非可被主题隐藏的脚注。

    plain=True（入门版，2026-10-03）：只留覆盖行、信号表、派生命中与缺项 / 数据提醒；
    供数来源 / 根数 / 最近交叉日、计算口径、执行规则、风险口径与「版面收起」这些
    说明文字、过程文字整段不渲染。--notes / --full（plain=False）逐字回到原样。
    """
    if not result or not result.get("available") or not result.get("items"):
        return ""
    esc = kit.esc
    items = result["items"]
    shown = items[:limit] if limit else items
    coverage = result["coverage"]
    out = [kit.sub("MACD 量化策略 · 日线（12 / 26 / 9）")]
    out.append(kit.kv([
        ("覆盖 / 交叉", esc(f"有效 {coverage['valid']}/{coverage['total']} · 最新收盘金叉 {result['golden_n']} / 死叉 {result['death_n']}（各标的日期见表）")),
    ]))
    rows = []
    for row in shown:
        color = kit.bad_color if row["action_key"] == "exit" else (
            kit.ok_color if row["action_key"] in ("entry", "hold") else kit.warn_color)
        rows.append([
            f"<b>{esc(row['label'])}</b><br>{esc(row['code'])}<br>{esc(row['as_of'])}",
            f"{row['dif']:+.4f}<br>{row['dea']:+.4f}",
            f"{row['hist']:+.4f}<br>{esc(row['momentum'])}",
            f"{esc(row['state'])}<br>{esc(row['axis'])}",
            f'<span style="color:{color};font-weight:700">{esc(row["action"])}</span>',
        ])
    out.append(kit.table(["标的 / 收盘日", "DIF / DEA", "MACD柱", "状态", "基础动作"], rows,
                         aligns=("left", "right", "right", "left", "left")))
    if plain:
        # 入门版：最近一次交叉（日期）是结论，压成一行；供数来源 / 根数不出。
        crosses = []
        for row in shown:
            cross = row.get("last_cross")
            if cross:
                name = "金叉" if cross["kind"] == "golden" else "死叉"
                crosses.append(f"{row['label']} 最近{name} {cross['date']}")
        if crosses:
            out.append(kit.kv([("最近交叉", esc(" · ".join(crosses)))]))
        # 派生命中照常展示（缺项 / 数据提醒也保留），其余说明文字不出。
        out.append(derived.render_derivatives(shown, kit, full=False, plain=True))
        rules = []
        missing = [row["label"] for row in result.get("missing") or []]
        if missing:
            rules.append(("暂缺", "、".join(missing)))
        for warning in result.get("warnings") or []:
            rules.append(("数据提醒", warning))
        if rules:
            out.append(kit.kv([(esc(label), esc(text)) for label, text in rules]))
        return "".join(out)
    provenance = []
    for row in shown:
        cross = row.get("last_cross")
        detail = f"{row['source']} · {row['bars_n']} 根"
        if cross:
            name = "金叉" if cross["kind"] == "golden" else "死叉"
            detail += f" · 最近{name} {cross['date']}（{cross['bars_ago']} 根日线前）"
        else:
            detail += " · 预热后未发生交叉"
        provenance.append((esc(row["label"]), esc(detail)))
    out.append(kit.kv(provenance))
    out.append(derived.render_derivatives(shown, kit, full=not bool(limit)))
    rules = [
        ("计算口径", "DIF=EMA12−EMA26；DEA=EMA9(DIF)；MACD柱=2×(DIF−DEA)。至少 36 根已收盘日线，EMA 以首窗口均值播种。"),
        ("执行规则", "金叉且 DIF、DEA 均在零轴上方→下一交易日观察入场；多头排列且双线在零轴上方→持有；死叉/空头排列→退出或规避；零轴下方金叉仅观察反弹。只做多/空仓。"),
        ("风险 / 数据", f"不并入原市场信号分，信号不等于上涨概率；MACD 滞后，震荡市易反复，需独立设置止损。排除盘中日线，超过 {MAX_LAG_DAYS} 个自然日的旧数据不发信号；整段选源不混接，个股复权差异会影响数值。非投资建议。"),
    ]
    if len(shown) < len(items):
        rules.append(("版面收起", f"已收起 {len(items) - len(shown)} 个有效标的，--full 查看全部。"))
    for row in result.get("missing") or []:
        rules.append(("缺项·" + row["label"], row["reason"]))
    for warning in result.get("warnings") or []:
        rules.append(("数据提醒", warning))
    out.append(kit.kv([(esc(label), esc(text)) for label, text in rules]))
    return "".join(out)
