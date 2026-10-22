"""三地指数：独立境内外供应商、同交易日未复权收盘核验。只经注入请求联网。"""
import csv
from datetime import datetime, timezone
from html import escape
import io
import json
import math
import os
import statistics
import time
import urllib.parse

from octopus_quant import providers

# 不以 ETF、期货或另一市场指数替代；供应商不是指数编制机构。
SPECS = [
    ("港股", "恒生指数", "^HSI", "100.HSI"),
    ("港股", "恒生科技", "^HSTECH", "100.HSTECH"),
    ("港股", "国企指数", "^HSCE", "100.HSCEI"),
    ("A股", "沪深300", "000300.SS", "1.000300"),
    ("A股", "上证指数", "000001.SS", "1.000001"),
    ("A股", "深证成指", "399001.SZ", "0.399001"),
    ("美股", "标普500", "^GSPC", "100.SPX"),
    ("美股", "纳斯达克综合", "^IXIC", "100.NDX"),
    ("美股", "道琼斯工业", "^DJI", "100.DJIA"),
]
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/"
YAHOO_HOSTS = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
)
EM = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EM_KLINE_URLS = (
    EM,
    "https://91.push2his.eastmoney.com/api/qt/stock/kline/get",
    "https://63.push2his.eastmoney.com/api/qt/stock/kline/get",
)
STOOQ_CSV_URL = "https://stooq.com/q/d/l/"
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

_YAHOO_SYMBOL_CANDIDATES = {
    "^HSTECH": ("^HSTECH", "HSTECH.HK"),
    "^HSCE": ("^HSCE", "^HSCEI"),
}

_STOOQ_SYMBOL = {
    "^HSI": "^hsi",
    "^HSTECH": "hstech.hk",
    "^HSCE": "^hsce",
    "000001.SS": "^shc",
    "^GSPC": "^spx",
    "^IXIC": "^ndq",
    "^DJI": "^dji",
}

_EM_SECID_CANDIDATES = {
    "^HSTECH": ("100.HSTECH", "124.HSTECH"),
}

_TENCENT_KLINE_CODE = {
    "^HSI": "hkHSI",
    "^HSTECH": "hkHSTECH",
    "^HSCE": "hkHSCEI",
    "000300.SS": "sh000300",
    "000001.SS": "sh000001",
    "399001.SZ": "sz399001",
}

_EM_NAME_TOKEN = {
    "^HSI": ("恒生", ()),
    "^HSTECH": ("科技", ()),
    "^HSCE": ("国企", ()),
    "000300.SS": ("300", ()),
    "000001.SS": ("上证", ()),
    "399001.SZ": ("深证", ()),
    "^GSPC": ("标普", ()),
    "^IXIC": ("纳斯达克", ("100",)),
    "^DJI": ("道琼斯", ()),
}


def _valid_price(v):
    return v is not None and not isinstance(v, bool) and math.isfinite(float(v)) and float(v) > 0


def _validate_em_name(symbol, actual):
    # 东财 100.NDX 返回 name="纳斯达克"（综合指数），须拒绝 "纳斯达克100" 等错误映射。
    expected, forbidden = _EM_NAME_TOKEN[symbol]
    if expected not in actual:
        raise ValueError(f"指数名称校验未通过：{actual!r} 不含 {expected!r}")
    for bad in forbidden:
        if bad in actual:
            raise ValueError(f"指数名称校验拒绝：{actual!r} 含禁用词 {bad!r}")


def _clean(rows, symbol, now):
    result = {}
    for day, close in rows:
        try:
            value = float(close)
            if math.isfinite(value) and value > 0 and providers.is_session_closed(symbol, day, now=now):
                result[str(day)] = value
        except (TypeError, ValueError):
            continue
    return dict(sorted(result.items()))


def _request_raw(fetch_json, url, *, params=None, timeout=8, retries=1):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = fetch_json(url, params=params, timeout=timeout)
            if resp is not None:
                return resp, None
        except Exception as exc:
            last_exc = exc
        if attempt < retries:
            time.sleep(0.2 * (attempt + 1))
    return None, last_exc


def _request_json(fetch_json, url, *, params=None, timeout=8, retries=1):
    resp, exc = _request_raw(fetch_json, url, params=params, timeout=timeout, retries=retries)
    if resp is None:
        return None, exc
    if isinstance(resp, dict):
        return resp, None
    if hasattr(resp, "json"):
        try:
            return resp.json(), None
        except Exception as jexc:
            return None, jexc
    return None, None


def _parse_yahoo_bars(data, symbol, now):
    tz = providers.market_timezone(symbol)
    result = ((data or {}).get("chart") or {}).get("result") or []
    if not result or not isinstance(result[0], dict):
        return {}
    r0 = result[0]
    ts = r0.get("timestamp") or []
    quotes = ((r0.get("indicators") or {}).get("quote") or [{}])
    closes = (quotes[0] if quotes and isinstance(quotes[0], dict) else {}).get("close") or []
    rows = [
        (datetime.fromtimestamp(t, tz).strftime("%Y-%m-%d"), c)
        for t, c in zip(ts, closes)
        if t is not None and c is not None
    ]
    meta = r0.get("meta") if isinstance(r0.get("meta"), dict) else {}
    rm_price = meta.get("regularMarketPrice")
    rm_time = meta.get("regularMarketTime")
    if _valid_price(rm_price) and isinstance(rm_time, (int, float)) and rm_time > 0:
        meta_day = datetime.fromtimestamp(rm_time, tz).strftime("%Y-%m-%d")
        rows.append((meta_day, rm_price))
    return _clean(rows, symbol, now)


def _fetch_stooq(fetch_json, stooq_sym):
    resp, exc = _request_raw(
        fetch_json, STOOQ_CSV_URL, params={"s": stooq_sym, "i": "d"}, timeout=8, retries=0
    )
    if resp is None:
        return [], exc
    text = resp.text if hasattr(resp, "text") else (resp if isinstance(resp, str) else "")
    text = (text or "").strip()
    if not text or "No data" in text or "Exceeded" in text or "Date" not in text:
        return [], ValueError("stooq empty")
    rows = []
    for rec in csv.DictReader(io.StringIO(text)):
        d = (rec.get("Date") or "").strip()
        c = (rec.get("Close") or "").strip()
        if d and c:
            rows.append((d, c))
    return rows, None


def _fetch_tencent_kline(fetch_json, tx_code):
    data, exc = _request_json(
        fetch_json, TENCENT_KLINE_URL, params={"param": f"{tx_code},day,,,130"}, timeout=8, retries=0
    )
    if not isinstance(data, dict):
        return [], exc
    inner = (data.get("data") or {}).get(tx_code) or {}
    raw = inner.get("day") or inner.get("qfqday") or []
    return [(str(item[0]), item[2]) for item in raw if isinstance(item, (list, tuple)) and len(item) >= 3], None


def _mainland_from_db(db_dir, symbol, now):
    if not db_dir or not os.path.isdir(db_dir):
        return {}, None
    files = sorted(f for f in os.listdir(db_dir) if f.endswith(".json") and f[:8].isdigit())
    if not files:
        return {}, None
    rows = []
    src_used = None
    for fname in files[-120:]:
        try:
            with open(os.path.join(db_dir, fname), encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        slots = doc.get("slots") or {}
        for slot in ("2100", "1700", "0830"):
            q = ((slots.get(slot) or {}).get("quotes") or {}).get(symbol)
            if not isinstance(q, dict):
                continue
            cons = q.get("consensus") or {}
            eod = cons.get("eod_close_check") or {}
            if eod.get("source") == "em_kline" and eod.get("date") and _valid_price(eod.get("close")):
                rows.append((str(eod["date"]), float(eod["close"])))
                src_used = "东方财富日K(库)"
                break
            by_src = cons.get("by_source") or {}
            picked = False
            for dom_src, label in (("eastmoney", "东方财富(库)"), ("sina", "新浪财经(库)"), ("tencent", "腾讯财经(库)")):
                rec = by_src.get(dom_src)
                if not isinstance(rec, dict) or not _valid_price(rec.get("price")):
                    continue
                qt = str(rec.get("quote_time") or "")
                qday = qt[:10] if len(qt) >= 10 and qt[4] == "-" and qt[7] == "-" else ""
                if qday:
                    rows.append((qday, float(rec["price"])))
                    src_used = label
                    picked = True
                    break
            if picked:
                break
    return _clean(rows, symbol, now), src_used


def _ordered_hosts(items, strikes):
    return sorted(items, key=lambda pair: 1 if strikes.get(pair[0], 0) >= 2 else 0)


def _collect_overseas(fetch_json, symbol, now, strikes=None):
    strikes = strikes if strikes is not None else {}
    last_err = None
    candidates = _YAHOO_SYMBOL_CANDIDATES.get(symbol, (symbol,))
    yahoo_hosts = [(YAHOO_HOSTS[0], "Yahoo"), (YAHOO_HOSTS[1], "Yahoo镜像")]
    for tmpl, lbl in _ordered_hosts(yahoo_hosts, strikes):
        retries = 0 if strikes.get(tmpl, 0) >= 2 else 1
        for cand in candidates:
            url = tmpl.format(symbol=urllib.parse.quote(cand))
            data, exc = _request_json(
                fetch_json, url, params={"range": "6mo", "interval": "1d"}, timeout=8, retries=retries
            )
            if exc is not None:
                last_err = type(exc).__name__
            if not isinstance(data, dict):
                strikes[tmpl] = strikes.get(tmpl, 0) + 1
                continue
            try:
                bars = _parse_yahoo_bars(data, symbol, now)
                if bars:
                    strikes[tmpl] = 0
                    return bars, url, lbl, None
            except Exception as exc2:
                last_err = type(exc2).__name__
                strikes[tmpl] = strikes.get(tmpl, 0) + 1
    stooq_sym = _STOOQ_SYMBOL.get(symbol)
    if stooq_sym:
        rows, exc = _fetch_stooq(fetch_json, stooq_sym)
        if exc is not None:
            last_err = type(exc).__name__
        bars = _clean(rows, symbol, now)
        if bars:
            return bars, f"{STOOQ_CSV_URL}?s={stooq_sym}&i=d", "Stooq", None
    return {}, YAHOO + symbol, "Yahoo", last_err


def _collect_mainland(fetch_json, symbol, secid, now, db_dir=None, strikes=None, allow_db=False):
    strikes = strikes if strikes is not None else {}
    last_err = None
    secids = _EM_SECID_CANDIDATES.get(symbol, (secid,))
    em_hosts = [(u, "东方财富" if u == EM else "东方财富镜像") for u in EM_KLINE_URLS]
    for url, lbl in _ordered_hosts(em_hosts, strikes):
        retries = 0 if strikes.get(url, 0) >= 2 else 1
        for cand_secid in secids:
            data, exc = _request_json(
                fetch_json,
                url,
                params={
                    "secid": cand_secid,
                    "klt": 101,
                    "fqt": 0,
                    "lmt": 130,
                    "end": "20500101",
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56",
                },
                timeout=8,
                retries=retries,
            )
            if exc is not None:
                last_err = type(exc).__name__
            if not isinstance(data, dict):
                strikes[url] = strikes.get(url, 0) + 1
                continue
            try:
                payload = data["data"]
                actual = str(payload.get("name", ""))
                _validate_em_name(symbol, actual)
                rows = [(x.split(",")[0], x.split(",")[2]) for x in payload["klines"]]
                bars = _clean(rows, symbol, now)
                if bars:
                    strikes[url] = 0
                    return bars, url, lbl, None
            except Exception as exc2:
                last_err = type(exc2).__name__
                strikes[url] = strikes.get(url, 0) + 1

    tx_code = _TENCENT_KLINE_CODE.get(symbol)
    if tx_code:
        rows, exc = _fetch_tencent_kline(fetch_json, tx_code)
        if exc is not None:
            last_err = type(exc).__name__
        bars = _clean(rows, symbol, now)
        if bars:
            return bars, f"{TENCENT_KLINE_URL}?param={tx_code},day", "腾讯财经", None

    if allow_db and db_dir:
        db_bars, db_src = _mainland_from_db(db_dir, symbol, now)
        if db_bars:
            return db_bars, f"market_db://{symbol}", db_src or "本地库境内源", None

    return {}, EM, "东方财富", last_err


def collect(fetch_json, *, now=None, tolerance_pct=0.1, max_age_days=4, db_dir=None):
    """保守日历天时效门槛；长假可能标过期，不推测交易所假期。"""
    now = now or datetime.now(timezone.utc)
    strikes = {}
    output = []
    for market, name, symbol, secid in SPECS:
        row = dict(
            market=market, name=name, symbol=symbol, secid=secid,
            collected_at=now.isoformat(), overseas_url=YAHOO + symbol,
            mainland_url=EM, overseas_source="Yahoo", mainland_source="东方财富",
            status="双源缺失", usable=False,
            overseas_date=None, mainland_date=None, difference_pct=None,
        )
        overseas, ov_url, ov_src, ov_err = _collect_overseas(fetch_json, symbol, now, strikes=strikes)
        mainland, ml_url, ml_src, ml_err = _collect_mainland(
            fetch_json, symbol, secid, now, db_dir=db_dir, strikes=strikes, allow_db=bool(overseas)
        )
        row.update(overseas_url=ov_url, mainland_url=ml_url, overseas_source=ov_src, mainland_source=ml_src)
        if ov_err and not overseas:
            row["overseas_error"] = ov_err
        if ml_err and not mainland:
            row["mainland_error"] = ml_err
        row["overseas_date"] = max(overseas) if overseas else None
        row["overseas_close"] = overseas[row["overseas_date"]] if overseas else None
        row["mainland_date"] = max(mainland) if mainland else None
        row["mainland_close"] = mainland[row["mainland_date"]] if mainland else None

        if not overseas or not mainland:
            row["status"] = "单源待核验" if overseas or mainland else "双源缺失"
        elif max(overseas) != max(mainland):
            row["status"] = "交易日错位"
        else:
            day = max(overseas)
            diff = abs(overseas[day] / mainland[day] - 1) * 100
            age = (now.astimezone(providers.market_timezone(symbol)).date()
                   - datetime.strptime(day, "%Y-%m-%d").date()).days
            row.update(difference_pct=diff, as_of=day)
            row["status"] = (
                "数据过期" if age > max_age_days
                else "来源冲突" if diff > tolerance_pct
                else "双源一致"
            )
            row["usable"] = row["status"] == "双源一致"
            if row["usable"]:
                row["history"] = [{"date": d, "close": overseas[d]} for d in sorted(overseas)]
                row.update(metrics(row["history"]))
        output.append(row)
    return output


def metrics(history):
    """仅使用已过滤日线；不足完整窗口的指标不外推。收益单位为百分比。"""
    closes = [b["close"] for b in history]
    out = {"samples": len(closes)}
    for n in (1, 5, 20, 60):
        out[f"ret_{n}d"] = (closes[-1] / closes[-n - 1] - 1) * 100 if len(closes) > n else None
    for n in (20, 60):
        out[f"ma{n}"] = sum(closes[-n:]) / n if len(closes) >= n else None
    daily = [b / a - 1 for a, b in zip(closes, closes[1:])]
    out["vol_20"] = statistics.stdev(daily[-20:]) * math.sqrt(252) * 100 if len(daily) >= 20 else None
    out["win_20"] = sum(r > 0 for r in daily[-20:]) / 20 * 100 if len(daily) >= 20 else None
    out["max_dd_60"] = None
    if len(closes) >= 60:
        peak, dd = closes[-60], 0
        for c in closes[-60:]:
            peak = max(peak, c)
            dd = min(dd, (c / peak - 1) * 100)
        out["max_dd_60"] = dd
    ma20, ma60 = out["ma20"], out["ma60"]
    out["trend"] = "样本不足"
    if ma20 is not None and ma60 is not None:
        out["trend"] = (
            "多头排列" if closes[-1] > ma20 > ma60
            else "空头排列" if closes[-1] < ma20 < ma60
            else "震荡"
        )
    # 简单可解释的规则状态，不冒充概率或回测策略净值。
    out["momentum_signal"] = (
        ("正动量" if out["ret_20d"] > 0 else "非正动量") if out["ret_20d"] is not None else "样本不足"
    )
    out["trend_signal"] = {"多头排列": "趋势观察", "空头排列": "防守观察", "震荡": "等待确认"}.get(
        out["trend"], "样本不足"
    )
    return out


def render(rows, kit=None):
    from strategy_quant import _kit_sub
    def number(value):
        return "—" if value is None else f"{value:.2f}"

    items = []
    for idx, r in enumerate(rows):
        border = "" if idx == len(rows) - 1 else "border-bottom:1px solid #EDEDEF;"
        ov_lbl = escape(r.get("overseas_source") or "Yahoo")
        ml_lbl = escape(r.get("mainland_source") or "东方财富")
        diff_str = number(r.get("difference_pct")) + ("%" if r.get("difference_pct") is not None else "")
        r20_str = number(r.get("ret_20d") if r.get("usable") else None) + (
            "%" if r.get("usable") and r.get("ret_20d") is not None else ""
        )
        tr_str = r.get("trend", "样本不足") if r.get("usable") else "暂停判断"
        items.append(
            f'<div style="padding:5px 0;{border}color:#222">'
            f'<b style="color:#111">{escape(r["market"] + " · " + r["name"])}</b>'
            f'（{escape(r.get("status", "双源缺失"))}）<br>'
            f'{ov_lbl} {escape(str(r.get("overseas_date") or "暂缺"))} / {number(r.get("overseas_close"))} ｜ '
            f'{ml_lbl} {escape(str(r.get("mainland_date") or "暂缺"))} / {number(r.get("mainland_close"))} ｜ '
            f'差异 {diff_str} ｜ 20日 {r20_str} ｜ 趋势 {escape(str(tr_str))}</div>'
        )
    collected = escape(max((r.get("collected_at", "") for r in rows), default="") or "暂缺")
    head = _kit_sub(kit, "港股 / A股 / 美股指数 · 境内外交叉核验") if kit is not None else ""
    meta_note = (
        '<div style="margin:6px 0;padding:6px 9px;background:#F7F7F9;'
        'border-left:3px solid #8E8E93;font-size:12px;line-height:1.6;color:#333">'
        '<b style="color:#111">核验口径</b>：同指数、同交易日、未复权已收盘日线；容差0.1%，超过4个日历日保守标过期（长假需人工核查）。'
        '仅双源一致输出动量与趋势；单源、错位、冲突暂停判断。两供应商一致不等于交易所认证；20日收益不是策略回测收益。<br>'
        '<b style="color:#111">境外 / 境内</b>：Yahoo Chart（query1/query2）/ Stooq × 东方财富历史K线（主站/镜像）/ 腾讯日K / 本地库境内源 ｜ '
        f'<b style="color:#111">采集时间</b>：{collected}</div>'
    )
    return (
        head
        + '<div style="margin:6px 0;padding:4px 10px;background:#fff;border:1px solid #E5E5E8;'
        f'border-radius:8px;font-size:12px;line-height:1.62;color:#222">{"".join(items)}</div>'
        + meta_note
    )
