#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 数据层 —— 量化引擎的第 1 层（唯一的联网层）。

所有函数都通过注入的 ``fetch_json(url, params=..., timeout=...)`` 取数，
因此单元测试可以在完全离线的情况下用假数据替换整个网络层。

取数原则（与日报其它数据源一致）：
  · 抓不到就返回空 / None，绝不返回历史兜底数字，绝不「用旧数据冒充实时」；
  · 每个函数只负责「把原始接口解析成标准结构」，不做任何统计判断。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

CST = timezone(timedelta(hours=8))  # 北京时间 / 澳门时间

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
EASTMONEY_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_ULIST = "https://push2.eastmoney.com/api/qt/ulist.np/get"
EASTMONEY_DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

# ------------------------------------------------------------------
# 每条数据线 1 主源 + 2 备用源（注册表在 output/backup_sources.py；引擎可脱离注册表独立运行）
# ------------------------------------------------------------------
try:                                   # 与日报共用同一份注册表
    import backup_sources as _bk
except Exception:                      # 单独使用引擎时退回内置候选
    _bk = None

_FALLBACK_CHAINS = {
    "yahoo_chart": [YAHOO_CHART, "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"],
    "em_clist": [EASTMONEY_CLIST, "https://82.push2.eastmoney.com/api/qt/clist/get",
                 "https://72.push2.eastmoney.com/api/qt/clist/get"],
    "em_ulist": [EASTMONEY_ULIST, "https://82.push2.eastmoney.com/api/qt/ulist.np/get",
                 "https://72.push2.eastmoney.com/api/qt/ulist.np/get"],
    "em_kline": [EASTMONEY_KLINE, "https://91.push2his.eastmoney.com/api/qt/stock/kline/get",
                 "https://63.push2his.eastmoney.com/api/qt/stock/kline/get"],
    "em_datacenter": [EASTMONEY_DATACENTER, "https://datacenter.eastmoney.com/api/data/v1/get",
                      "https://datacenter.eastmoney.com/securities/api/data/v1/get"],
}


def chain_urls(line, **fmt):
    """数据线的同格式候选 URL（主源在前）。"""
    if _bk is not None and hasattr(_bk, "urls"):
        try:
            return _bk.urls("yahoo_bars" if line == "yahoo_chart" else line, **fmt)
        except Exception:
            pass
    return [u.format(**fmt) if fmt else u for u in _FALLBACK_CHAINS[line]]


def em_secid_for_yahoo(symbol):
    if _bk is not None and hasattr(_bk, "em_secid_for_yahoo"):
        return _bk.em_secid_for_yahoo(symbol)
    sym = str(symbol or "")
    table = {"^HSI": "100.HSI", "^HSTECH": "100.HSTECH", "^HSCE": "100.HSCEI"}
    if sym in table:
        return table[sym]
    if sym.endswith(".HK") and sym[:-3].isdigit():
        return f"116.{int(sym[:-3]):05d}"
    return ""


def fetch_json_chain(fetch_json, urls, params, ok, timeout=15):
    """依次请求候选 URL，返回第一个通过 ok(data) 校验的 (data, url)；全部失败 (None, None)。

    镜像主机可能 200 但正文 data=null，所以必须按解析结果判定，而不是只看有没有响应。
    """
    for url in urls:
        try:
            data = fetch_json(url, params=params, timeout=timeout)
        except Exception:
            data = None
        if data is None:
            continue
        try:
            if ok(data):
                return data, url
        except Exception:
            continue
    return None, None

# ------------------------------------------------------------------
# 标的池（可用环境变量覆盖，逗号分隔的 Yahoo 代码即可）
# ------------------------------------------------------------------
# 指数：恒指（大盘）/ 恒生科技（成长）/ 国企指数（中资）
HK_INDEX_SPECS = [
    ("恒生指数", "^HSI"),
    ("恒生科技", "^HSTECH"),
    ("国企指数", "^HSCEI"),
]

# 个股：港股市值 / 成交活跃度居前的中资与本地蓝筹（Yahoo 代码 = 5 位数字.HK）
HK_STOCK_UNIVERSE = [
    ("腾讯控股", "0700.HK"),
    ("阿里巴巴-W", "9988.HK"),
    ("美团-W", "3690.HK"),
    ("小米集团-W", "1810.HK"),
    ("友邦保险", "1299.HK"),
    ("汇丰控股", "0005.HK"),
    ("建设银行", "0939.HK"),
    ("中国移动", "0941.HK"),
    ("香港交易所", "0388.HK"),
    ("中芯国际", "0981.HK"),
    ("比亚迪股份", "1211.HK"),
    ("快手-W", "1024.HK"),
    ("京东集团-SW", "9618.HK"),
    ("中国海洋石油", "0883.HK"),
    ("中国平安", "2318.HK"),
    ("安踏体育", "2020.HK"),
    ("网易-S", "9999.HK"),
    ("药明生物", "2269.HK"),
]

# 港股在东方财富的 secid 前缀（1=A股 0=深/京 100=HK指数 105~107=美股 116=港股个股）
EM_HK_PREFIX = "116."


def _env_list(name, default):
    """从环境变量读取标的池（``代码:名称,代码:名称``）。"""
    raw = os.environ.get(name, "")
    items = []
    for chunk in str(raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            code, label = chunk.split(":", 1)
            items.append((label.strip() or code.strip(), code.strip()))
        else:
            items.append((chunk, chunk))
    return items or default


def hk_index_specs():
    return _env_list("OCTOPUS_HK_INDEX_SPECS", HK_INDEX_SPECS)


def hk_stock_universe():
    return _env_list("OCTOPUS_HK_UNIVERSE", HK_STOCK_UNIVERSE)


# ------------------------------------------------------------------
# 日线完成性：不能把盘中 close 字段当作当天的最终收盘
# ------------------------------------------------------------------
def market_timezone(symbol):
    """本模块股票 / 指数代码对应的交易所时区（美股自动处理夏令时）。"""
    sym = str(symbol or "").upper()
    if sym.endswith((".HK", ".SS", ".SZ")) or sym in ("^HSI", "^HSTECH", "^HSCEI", "^HSCE"):
        return CST
    return ZoneInfo("America/New_York")


def is_session_closed(symbol, session_date, *, now=None):
    """是否已过该交易日收盘缓冲：A股 15:10、港股 16:15、美股当地 16:15。

    周末 / 非法日期返回 False。只判完成性，不猜法定假日或补造交易日；
    提前收市日按常规收盘保守等待。库读取时须传入快照的原始采集时刻。
    """
    try:
        day = datetime.strptime(str(session_date), "%Y-%m-%d").date()
        if day.weekday() >= 5:
            return False
        sym = str(symbol or "").upper()
        hour, minute = (15, 10) if sym.endswith((".SS", ".SZ")) else (16, 15)
        cutoff = datetime(day.year, day.month, day.day, hour, minute,
                          tzinfo=market_timezone(sym))
        moment = now or datetime.now(CST)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=CST)
        return moment >= cutoff
    except (TypeError, ValueError, AttributeError):
        return False


# ------------------------------------------------------------------
# Yahoo Finance Chart —— 日线序列
# ------------------------------------------------------------------
def _meta_tz(meta):
    """交易所本地时区：优先 ``meta.gmtoffset``（秒），缺失时退回北京时间。"""
    try:
        off = (meta or {}).get("gmtoffset")
        if off is not None:
            return timezone(timedelta(seconds=int(off)))
    except (TypeError, ValueError):
        pass
    return CST


def session_bar_from_meta(result, bars):
    """用 ``meta`` 里的最新报价补出 Yahoo 日线暂时缺失的「最近一个已收盘交易日」。

    背景（2026-09-29 凌晨实测）：Yahoo Chart API 在交易所本地 0 点之后的几个小时里，
    ``interval=1d`` 序列会暂时丢掉刚刚收盘那一天的 K 线（要等官方 EOD 数据入库才回来），
    此时 ``timestamp/close`` 的最后一根只到上上个交易日，而 ``meta.regularMarketPrice`` /
    ``meta.regularMarketTime`` 仍是刚收盘的价格与时间。若不处理，「最新收盘」会整体
    回退一个交易日（周二凌晨看到的是上周五收盘）。

    规则（全部满足才补，否则返回 None，绝不凭空造数）：
      1. ``regularMarketPrice`` / ``regularMarketTime`` 都存在；
      2. 报价所在交易所本地日期 **晚于** 序列最后一根 K 线的日期；
      3. 报价属于**已收盘**的交易日：``regularMarketTime`` 不落在
         ``currentTradingPeriod.regular`` 的 [start, end) 区间内（盘中不补，避免把半天
         行情当收盘）。``currentTradingPeriod`` 缺失时视为无法判断 → 不补。
    返回的 K 线带 ``from_meta=True`` 标记；开盘价无从得知记为 None。
    """
    meta = (result or {}).get("meta") or {}
    price = meta.get("regularMarketPrice")
    ts = meta.get("regularMarketTime")
    if price is None or ts in (None, 0, ""):
        return None
    try:
        price = float(price)
        ts = int(ts)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    tz = _meta_tz(meta)
    m_date = datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d")
    last_date = bars[-1]["date"] if bars else None
    if last_date and m_date <= last_date:
        return None
    regular = ((meta.get("currentTradingPeriod") or {}).get("regular") or {})
    try:
        start = int(regular.get("start"))
        end = int(regular.get("end"))
    except (TypeError, ValueError):
        return None          # 无法判断是否已收盘 → 宁缺毋滥
    if start <= ts < end:
        return None          # 当前交易日盘中：不把半日行情当收盘
    vol = meta.get("regularMarketVolume")
    try:
        vol = float(vol) if vol not in (None, "") else None
    except (TypeError, ValueError):
        vol = None
    return {
        "date": m_date,
        "open": None,
        "high": _num(meta.get("regularMarketDayHigh")),
        "low": _num(meta.get("regularMarketDayLow")),
        "close": price,
        "volume": vol,
        "from_meta": True,
    }


def parse_chart_result(result, *, with_meta=True):
    """把 Yahoo Chart ``result[0]`` 解析成升序日线（含 meta 回补），供日线与快照共用。

    返回 ``[{date, open, high, low, close, volume[, from_meta]}]``；解析失败返回 ``[]``。
    """
    try:
        stamps = result.get("timestamp") or []
        quote = result["indicators"]["quote"][0]
        closes = quote.get("close") or []
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        volumes = quote.get("volume") or []
    except (KeyError, TypeError, IndexError, AttributeError):
        return []

    bars = []
    for i, ts in enumerate(stamps):
        try:
            close = closes[i]
            if close is None:
                continue
            bars.append({
                "date": datetime.fromtimestamp(int(ts), CST).strftime("%Y-%m-%d"),
                "open": opens[i] if i < len(opens) else None,
                "high": highs[i] if i < len(highs) else None,
                "low": lows[i] if i < len(lows) else None,
                "close": float(close),
                "volume": (volumes[i] if i < len(volumes) else None),
            })
        except (IndexError, TypeError, ValueError):
            continue
    bars.sort(key=lambda b: b["date"])
    # meta 是单日快照，不能伪装成完整周 K；日线/快照调用保持默认兼容。
    extra = session_bar_from_meta(result, bars) if with_meta else None
    if extra:
        bars.append(extra)
    return bars


def fetch_bars(fetch_json, symbol, *, rng="1y", interval="1d", timeout=15,
               validate_bars=None, with_source=False):
    """取一只标的的 K 线（默认日线，支持 1wk 周线），默认返回升序 bars 列表。

    ``validate_bars`` 可附加样本数 / 日期门禁，不合格时继续尝试备用源。
    ``with_source=True`` 返回 {bars, source, url}，供策略逐标的溯源。
    失败返回 []（with_source 时 bars=[]），绝不编造数据。
    Yahoo 临时丢掉刚收盘日线时，用 meta 的已收盘报价补回（见 session_bar_from_meta）。
    """
    empty = {"bars": [], "source": None, "url": None}
    if not fetch_json:
        return empty if with_source else []

    def _result(data):
        try:
            return (data or {})["chart"]["result"][0]
        except (KeyError, TypeError, IndexError, AttributeError):
            return None

    def _ok(data):
        result = _result(data)
        bars = parse_chart_result(result, with_meta=interval == "1d") if result else []
        return bool(bars) and (validate_bars(bars) if validate_bars else True)

    # 数据线 yahoo_bars：query1 → query2 → 东财日 K（独立解析）
    data, url = fetch_json_chain(
        fetch_json, chain_urls("yahoo_chart", symbol=symbol),
        {"range": rng, "interval": interval}, ok=_ok, timeout=timeout)
    if data is not None:
        bars = parse_chart_result(_result(data), with_meta=interval == "1d")
        result = {"bars": bars, "source": "Yahoo Finance " + url.split("/")[2], "url": url}
        return result if with_source else bars
    if interval not in ("1d", "1wk"):
        return empty if with_source else []
    return fetch_bars_eastmoney(fetch_json, symbol, rng=rng, timeout=timeout, interval=interval,
                                validate_bars=validate_bars, with_source=with_source)


_EM_LIMIT_FOR_RANGE = {"5d": 8, "1mo": 25, "3mo": 70, "6mo": 135, "1y": 260, "2y": 520,
                       "5y": 1300, "10y": 2600, "max": 10000}


def _parse_eastmoney_bars(data):
    """东方财富日 K 的独立解析器，供返回值与主备门禁共用。"""
    bars = []
    for line in (((data or {}).get("data") or {}).get("klines") or []):
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        close = _num(parts[2])
        if close is None or close <= 0:
            continue
        bars.append({"date": parts[0].strip(), "open": _num(parts[1]), "high": _num(parts[3]),
                     "low": _num(parts[4]), "close": close, "volume": _num(parts[5]),
                     "from_eastmoney": True})
    bars.sort(key=lambda b: b["date"])
    return bars


def fetch_bars_eastmoney(fetch_json, symbol, *, rng="1y", timeout=15, interval="1d",
                         validate_bars=None, with_source=False):
    """东方财富前复权日/周 K；主机依次回退，解析无效也回退。"""
    empty = {"bars": [], "source": None, "url": None}
    secid = em_secid_for_yahoo(symbol)
    if not fetch_json or not secid or interval not in ("1d", "1wk"):
        return empty if with_source else []
    # 旧注册表把综合指数 ^IXIC 映射到 100.NDX；未经核验不能串成另一只指数。
    if str(symbol).strip().upper().replace("%5E", "^") == "^IXIC" and secid == "100.NDX":
        return empty if with_source else []
    limit = _EM_LIMIT_FOR_RANGE.get(str(rng), 520)
    if interval == "1wk" and str(rng) != "max":
        limit = (limit + 4) // 5 + 2  # range 表是日线数量，周 K 使用约 1/5 + 边界缓冲
    params = {"secid": secid, "klt": "102" if interval == "1wk" else "101", "fqt": "1", "end": "20500101",
              "lmt": str(limit),
              "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56,f57"}

    def _ok(data):
        bars = _parse_eastmoney_bars(data)
        return bool(bars) and (validate_bars(bars) if validate_bars else True)

    data, url = fetch_json_chain(fetch_json, chain_urls("em_kline"), params,
                                 ok=_ok, timeout=timeout)
    if data is None:
        return empty if with_source else []
    bars = _parse_eastmoney_bars(data)
    result = {"bars": bars, "source": ("东方财富周K " if interval == "1wk" else "东方财富日K ") + url.split("/")[2], "url": url}
    return result if with_source else bars


def fetch_series_batch(fetch_json, specs, *, rng="1y", workers=6, timeout=15,
                       executor=None):
    """并发抓一批标的；返回 ``{代码: [bars]}``（失败的键不出现，不造假）。"""
    from concurrent.futures import ThreadPoolExecutor

    if not fetch_json or not specs:
        return {}
    out = {}

    def _one(item):
        label, symbol = item
        return symbol, fetch_bars(fetch_json, symbol, rng=rng, timeout=timeout)

    if executor is not None:
        for symbol, bars in executor.map(_one, specs):
            if bars:
                out[symbol] = bars
        return out
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for symbol, bars in pool.map(_one, specs):
            if bars:
                out[symbol] = bars
    return out


# ------------------------------------------------------------------
# 东方财富 —— A股概念板块列表（只取当前快照，不提供点时成分历史）
# ------------------------------------------------------------------
def fetch_concept_boards(fetch_json, page_size=500, max_pages=5, timeout=12):
    """拉取东方财富 ``fs=m:90+t:3`` 概念板块列表及当日字段。

    返回 ``{items, total, reported_total, complete, served_urls, errors}``。分页数有上限；接口
    total 缺失时按有效短页 / 空页停止，网络中断不会误报完整。这里只返回当前概念行情快照，不把它当历史成分库。
    ``served_urls`` 供日报层记录主 / 备用镜像来源。
    """
    empty = {"items": [], "total": 0, "reported_total": None,
             "complete": False, "served_urls": [], "errors": []}
    if not fetch_json:
        empty["errors"].append("未注入取数函数")
        return empty
    try:
        page_size = max(1, int(page_size))
        max_pages = max(1, int(max_pages))
    except (TypeError, ValueError):
        page_size, max_pages = 500, 5

    items, served_urls, errors = [], [], []
    reported_total = None
    pagination_ended = False
    for page in range(1, max_pages + 1):
        params = {
            "pn": str(page), "pz": str(page_size), "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3", "fs": "m:90+t:3",
            "fields": "f2,f3,f6,f12,f14,f20,f21,f23,f62,f104,f105,f124,f128,f136",
        }
        data, served = fetch_json_chain(
            fetch_json, chain_urls("em_clist"), params,
            ok=lambda body: (isinstance((body or {}).get("data"), dict)
                             and isinstance(body["data"].get("diff"), (list, dict))),
            timeout=timeout)
        if data is None:
            errors.append(f"概念板块第 {page} 页未取得有效 diff")
            break
        if served and served not in served_urls:
            served_urls.append(served)
        payload = data.get("data") or {}
        diff = payload.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        try:
            count = int(payload.get("total")) if payload.get("total") is not None else None
        except (TypeError, ValueError):
            count = None
        if count is not None:
            reported_total = count
        page_rows = []
        for row in diff:
            if not isinstance(row, dict):
                continue
            code = str(row.get("f12") or "").strip()
            name = str(row.get("f14") or "").strip()
            if not code or not name:
                continue
            quote_ts = None
            raw_ts = row.get("f124")
            try:
                quote_ts = int(float(raw_ts)) if raw_ts not in (None, "", "-") else None
                if quote_ts and quote_ts > 100_000_000_000:  # 防接口改为毫秒时间戳
                    quote_ts //= 1000
            except (TypeError, ValueError, OverflowError):
                quote_ts = None
            page_rows.append({
                "code": code,
                "name": name,
                "chg_pct": _num(row.get("f3")),
                "amount": _num(row.get("f6")),
                "main_net": _num(row.get("f62")),
                "up": _num(row.get("f104")),
                "down": _num(row.get("f105")),
                "lead_stock": str(row.get("f128") or "").strip(),
                "lead_stock_pct": _num(row.get("f136")),
                "quote_ts": quote_ts,
                "as_of": (datetime.fromtimestamp(quote_ts, CST).strftime("%Y-%m-%d")
                          if quote_ts else None),
            })
        items.extend(page_rows)
        if not diff or len(diff) < page_size:
            pagination_ended = True
            break
        if reported_total is not None and len(items) >= reported_total:
            pagination_ended = True
            break
    total = reported_total if reported_total is not None else len(items)
    hit_page_cap = len(items) >= page_size * max_pages
    complete = bool(items) and (
        len(items) >= reported_total if reported_total is not None else pagination_ended
    )
    if not complete and reported_total is not None and hit_page_cap:
        errors.append(f"分页达到上限 {max_pages}，已取 {len(items)}/{reported_total} 个概念")
    elif not complete and reported_total is None and hit_page_cap:
        errors.append(f"分页达到上限 {max_pages}，总数未返回；至少已取 {len(items)} 个概念")
    elif not complete and reported_total is not None:
        errors.append(f"仅取得 {len(items)}/{reported_total} 个概念，分页完整性未确认")
    return {"items": items, "total": total, "reported_total": reported_total,
            "complete": complete, "served_urls": served_urls, "errors": errors}


# ------------------------------------------------------------------
# 东方财富 —— 南向 / 北向资金（沪深港通成交总额历史）
# ------------------------------------------------------------------
MUTUAL_TYPE_NORTH = "005"   # 北向合计（沪股通 + 深股通）
MUTUAL_TYPE_SOUTH = "006"   # 南向合计（港股通沪 + 港股通深）


def fetch_mutual_series(fetch_json, page_size=500, timeout=15):
    """沪深港通每日成交总额（单位：亿元）。

    返回 ``{"north": [(date, 亿元)], "south": [(date, 亿元)]}``（按日期升序）。
    说明：港交所自 2024-08-19 起停披南北向净买入，只披露成交总额，
    因此这里用「成交总额」刻画资金活跃度，不估算、更不编造净流入。
    """
    empty = {"north": [], "south": []}
    if not fetch_json:
        return empty
    params = {
        "reportName": "RPT_MUTUAL_DEAL_HISTORY",
        "columns": "ALL",
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": "TRADE_DATE,MUTUAL_TYPE",
        "sortTypes": "-1,1",
        "source": "WEB",
        "client": "WEB",
    }
    data, _url = fetch_json_chain(
        fetch_json, chain_urls("em_datacenter"), params,
        ok=lambda d: bool(((d or {}).get("result") or {}).get("data")), timeout=timeout)
    try:
        rows = ((data or {}).get("result") or {}).get("data") or []
    except (AttributeError, TypeError):
        return empty

    def _collect(mtype):
        pairs = []
        for it in rows:
            if str(it.get("MUTUAL_TYPE") or "") != mtype:
                continue
            day = str(it.get("TRADE_DATE") or "")[:10]
            try:
                amt = float(it.get("DEAL_AMT"))
            except (TypeError, ValueError):
                continue
            if day and amt > 0:
                pairs.append((day, amt / 100.0))  # 百万元 → 亿元
        pairs.sort(key=lambda p: p[0])
        return pairs

    return {"north": _collect(MUTUAL_TYPE_NORTH),
            "south": _collect(MUTUAL_TYPE_SOUTH)}


# ------------------------------------------------------------------
# 东方财富 —— 港股大盘成交 / 龙头成交额集中度
# ------------------------------------------------------------------
def fetch_hk_index_quotes(fetch_json, timeout=12):
    """恒指 / 恒科 / 国企指数的最新价与成交额（东财口径）。

    返回 ``{代码: {name, price, chg_pct, amount}}``；失败返回 {}。
    """
    if not fetch_json:
        return {}
    secids = ",".join(f"100.{code}" for code in ("HSI", "HSTECH", "HSCEI"))
    data, _url = fetch_json_chain(fetch_json, chain_urls("em_ulist"), {
        "fltt": "2", "invt": "2", "secids": secids,
        # f124 = 行情时间戳（秒）：用来标注这条报价属于哪个交易日，
        # 也是「行情速览」核对 Yahoo 是否回退的独立时间基准。
        "fields": "f2,f3,f4,f6,f12,f14,f124",
    }, ok=lambda d: bool(((d or {}).get("data") or {}).get("diff")), timeout=timeout)
    out = {}
    try:
        rows = ((data or {}).get("data") or {}).get("diff") or []
    except (AttributeError, TypeError):
        return out
    for it in rows:
        code = str(it.get("f12") or "").strip()
        try:
            price = float(it.get("f2"))
        except (TypeError, ValueError):
            continue
        amount = None
        try:
            amount = float(it.get("f6"))
        except (TypeError, ValueError):
            amount = None
        quote_ts = None
        try:
            quote_ts = int(it.get("f124")) if it.get("f124") not in (None, "", "-") else None
        except (TypeError, ValueError):
            quote_ts = None
        out[code] = {
            "name": str(it.get("f14") or "").strip() or code,
            "price": price,
            "chg_pct": _num(it.get("f3")),
            "amount": amount,  # 单位：元
            "quote_ts": quote_ts,
            "as_of": (datetime.fromtimestamp(quote_ts, CST).strftime("%Y-%m-%d")
                      if quote_ts else None),
            "quote_time": (datetime.fromtimestamp(quote_ts, CST).strftime("%Y-%m-%d %H:%M:%S")
                           if quote_ts else None),
        }
    return out


def fetch_hk_top_turnover(fetch_json, top_n=50, timeout=12):
    """港股主板成交额前 N 只（东财 push2 免费接口）。

    返回 ``[{code, name, price, chg_pct, amount}]``（amount 单位：元，降序）。
    用于计算「资金集中度 CR5 / CR20」——资金扎堆在哪里，是流动性分析的核心。
    """
    if not fetch_json:
        return []
    data, _url = fetch_json_chain(fetch_json, chain_urls("em_clist"), {
        "pn": "1", "pz": str(top_n), "po": "1", "np": "1", "fltt": "2",
        "invt": "2", "fid": "f6",
        "fs": "m:128+t:1,m:128+t:2,m:128+t:3,m:128+t:4",
        "fields": "f2,f3,f6,f12,f14",
    }, ok=lambda d: bool(((d or {}).get("data") or {}).get("diff")), timeout=timeout)
    try:
        diff = ((data or {}).get("data") or {}).get("diff") or []
    except (AttributeError, TypeError):
        return []
    rows = []
    for it in diff[:top_n]:
        name = str(it.get("f14") or "").strip()
        amount = _num(it.get("f6"))
        if not name or amount is None:
            continue
        rows.append({
            "code": str(it.get("f12") or "").strip(),
            "name": name,
            "price": _num(it.get("f2")),
            "chg_pct": _num(it.get("f3")),
            "amount": amount,
        })
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return rows


def _normalize_hk_code(code):
    """港股代码内部统一为 5 位数字，兼容 Yahoo / 东财的前导零写法。"""
    digits = "".join(ch for ch in str(code or "").split(".", 1)[0] if ch.isdigit())
    return digits.zfill(5) if digits else str(code or "").strip()


def fetch_hk_fundflow(fetch_json, universe=None, timeout=12):
    """港股快照：主力资金、主力净占比、成交额与 PE/PB（东财 ulist 字段）。

    返回 ``{5位代码: {name, main_net, main_pct, amount, pe_ttm, pb, ...}}``。
    港股主力资金字段不保证可用；若资金字段缺失但估值字段存在，仍保留该证券记录。
    """
    if not fetch_json:
        return {}
    universe = universe or hk_stock_universe()
    secids = []
    for _label, symbol in universe:
        code = symbol.split(".")[0]
        if code.isdigit():
            secids.append(f"{EM_HK_PREFIX}{code}")
    if not secids:
        return {}
    out = {}
    for i in range(0, len(secids), 8):  # 小批量，避免单请求过长
        data, _url = fetch_json_chain(fetch_json, chain_urls("em_ulist"), {
            "fltt": "2", "invt": "2", "secids": ",".join(secids[i:i + 8]),
            "fields": "f12,f14,f2,f3,f6,f9,f23,f62,f124,f184",
        }, ok=lambda d: bool(((d or {}).get("data") or {}).get("diff")), timeout=timeout)
        try:
            rows = ((data or {}).get("data") or {}).get("diff") or []
        except (AttributeError, TypeError):
            continue
        for it in rows:
            raw_code = str(it.get("f12") or "").strip()
            code = _normalize_hk_code(raw_code)
            if not raw_code or not code:
                continue
            net = _num(it.get("f62"))
            main_pct = _num(it.get("f184"))
            amount = _num(it.get("f6"))
            pe_ttm = _num(it.get("f9"))
            pb = _num(it.get("f23"))
            if all(value is None for value in (net, main_pct, amount, pe_ttm, pb)):
                continue
            quote_ts = None
            try:
                quote_ts = int(float(it.get("f124"))) if it.get("f124") not in (None, "", "-") else None
                if quote_ts and quote_ts > 100_000_000_000:
                    quote_ts //= 1000
            except (TypeError, ValueError, OverflowError):
                quote_ts = None
            out[code] = {
                "name": str(it.get("f14") or "").strip() or code,
                "price": _num(it.get("f2")),
                "chg_pct": _num(it.get("f3")),
                "main_net": net,
                "main_pct": main_pct,
                "amount": amount,
                "pe_ttm": pe_ttm,
                "pb": pb,
                "quote_ts": quote_ts,
                "as_of": (datetime.fromtimestamp(quote_ts, CST).strftime("%Y-%m-%d")
                          if quote_ts else None),
            }
    return out


def _num(val):
    """东财字段可能是 ``"-"`` / None / 字符串数字。"""
    try:
        if val is None or val == "-" or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None
