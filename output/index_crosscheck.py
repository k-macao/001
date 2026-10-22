"""三地指数：单源直取未复权已收盘日线，Yahoo 主源优先、备用源待命兜底。只经注入请求联网。

🔙 2026-10-23 已回滚为**纯港股日报**：默认不再调用 `collect()`（不发起这 9 个指数的请求），
`render()` 的指数表也只在 `OCTOPUS_INDEX_PAGE=1` 时由 strategy_quant.render_overview 输出。
开关判断见 output/pipeline.py:_index_page_enabled 与 output/strategy_quant.py:index_page_enabled。
"""
from datetime import datetime, timezone
import math
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
YAHOO_MIRROR = "https://query2.finance.yahoo.com/v8/finance/chart/"
EM_HOSTS = ("push2his.eastmoney.com", "91.push2his.eastmoney.com", "63.push2his.eastmoney.com")
EM = f"https://{EM_HOSTS[0]}/api/qt/stock/kline/get"

YAHOO_CODES = {
    "^HSTECH": ("^HSTECH", "HSTECH.HK"),
    "^HSCE": ("^HSCE", "^HSCEI"),
}
EM_SECIDS = {
    "^HSTECH": ("100.HSTECH", "124.HSTECH"),
}


def _clean(rows, symbol, now):
    result = {}
    for day, close in rows:
        try:
            value = float(close)
            if math.isfinite(value) and value > 0 and providers.is_session_closed(symbol, day, now=now):
                result[day] = value
        except (TypeError, ValueError):
            continue
    return result


def _parse_yahoo_bars(data, symbol, now):
    result = data["chart"]["result"][0]
    tz = providers.market_timezone(symbol)
    timestamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    rows = [(datetime.fromtimestamp(t, tz).strftime("%Y-%m-%d"), c)
            for t, c in zip(timestamps, closes)]
    meta = result.get("meta")
    if isinstance(meta, dict) and meta.get("regularMarketPrice") is not None and meta.get("regularMarketTime"):
        try:
            m_day = datetime.fromtimestamp(int(meta["regularMarketTime"]), tz).strftime("%Y-%m-%d")
            if all(d != m_day for d, _ in rows):
                rows.append((m_day, meta["regularMarketPrice"]))
        except (TypeError, ValueError, OSError, OverflowError):
            pass
    return _clean(rows, symbol, now)


def _try_yahoo(fetch_json, base_url, symbol, now):
    last_err = None
    for code in YAHOO_CODES.get(symbol, (symbol,)):
        url = base_url + code
        try:
            data = fetch_json(url, params={"range": "6mo", "interval": "1d"}, timeout=12)
            bars = _parse_yahoo_bars(data, symbol, now)
            if bars:
                return bars, url, None
        except Exception as exc:
            last_err = type(exc).__name__
    return {}, None, last_err


def _try_eastmoney(fetch_json, symbol, secid, now):
    last_err = None
    for host in EM_HOSTS:
        url = f"https://{host}/api/qt/stock/kline/get"
        for cand_secid in EM_SECIDS.get(symbol, (secid,)):
            try:
                data = fetch_json(url, params={
                    "secid": cand_secid, "klt": 101, "fqt": 0,
                    "lmt": 130, "end": "20500101", "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56",
                }, timeout=12)
                actual = str(data["data"].get("name", ""))
                if symbol == "^IXIC" and (
                    not actual or "100" in actual
                    or ("纳斯达克" not in actual and "NASDAQ" not in actual.upper())
                ):
                    raise ValueError("纳指映射须为纳斯达克综合而非纳指100")
                rows = [(x.split(",")[0], x.split(",")[2]) for x in data["data"]["klines"]]
                bars = _clean(rows, symbol, now)
                if bars:
                    return bars, url, None
            except Exception as exc:
                last_err = type(exc).__name__
    return {}, None, last_err


def collect(fetch_json, *, now=None, max_age_days=4, **_unused):
    """单源采集 + 备用源故障切换：主源成功且未过期即返回，仅在主源不可用时尝试备用源。"""
    now = now or datetime.now(timezone.utc)
    output = []
    for market, name, symbol, secid in SPECS:
        local_today = now.astimezone(providers.market_timezone(symbol)).date()

        def _age_days(day_str):
            return (local_today - datetime.strptime(day_str, "%Y-%m-%d").date()).days

        row = dict(
            market=market, name=name, symbol=symbol, secid=secid,
            collected_at=now.isoformat(), primary_url=YAHOO + symbol,
            source=None, source_role=None, source_label="暂缺", source_url=None,
            is_backup=False, date=None, as_of=None, close=None,
            status="暂缺", usable=False,
        )

        # 按「主源 → 备用源1 → 备用源2」顺序惰性求值：前序源拿到新鲜数据即停止，绝不多源并跑比价。
        chain = (
            ("yahoo", "主源", "主源 · Yahoo", lambda s=symbol: _try_yahoo(fetch_json, YAHOO, s, now)),
            ("yahoo_mirror", "备用源1", "备用源1 · Yahoo镜像",
             lambda s=symbol: _try_yahoo(fetch_json, YAHOO_MIRROR, s, now)),
            ("eastmoney", "备用源2", "备用源2 · 东方财富",
             lambda s=symbol, sc=secid: _try_eastmoney(fetch_json, s, sc, now)),
        )
        chosen = None
        stale_fallback = None
        errors = {}
        for src_id, role, label, runner in chain:
            bars, used_url, err = runner()
            if err:
                errors[src_id] = err
            if not bars:
                continue
            day = max(bars)
            if _age_days(day) <= max_age_days:
                chosen = (bars, day, src_id, role, label, used_url, False)
                break
            if stale_fallback is None or day > stale_fallback[1]:
                stale_fallback = (bars, day, src_id, role, label, used_url, True)

        picked = chosen or stale_fallback
        if errors:
            row["errors"] = errors
        if picked is not None:
            bars, day, src_id, role, label, used_url, is_stale = picked
            is_backup = role != "主源"
            row.update(
                source=src_id, source_role=role, source_label=label, source_url=used_url,
                is_backup=is_backup, date=day, as_of=day, close=bars[day],
                status="数据过期" if is_stale else ("备用源启用" if is_backup else "正常"),
                usable=not is_stale,
            )
            if row["usable"]:
                row["history"] = [{"date": d, "close": bars[d]} for d in sorted(bars)]
                row.update(metrics(row["history"]))
        output.append(row)
    return output


def metrics(history):
    """仅使用已过滤日线；不足完整窗口的指标不外推。收益单位为百分比。"""
    import statistics
    closes = [b["close"] for b in history]
    out = {"samples": len(closes)}
    for n in (1, 5, 20, 60):
        out[f"ret_{n}d"] = (closes[-1] / closes[-n-1] - 1) * 100 if len(closes) > n else None
    for n in (20, 60):
        out[f"ma{n}"] = sum(closes[-n:]) / n if len(closes) >= n else None
    daily = [b/a-1 for a, b in zip(closes, closes[1:])]
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
        out["trend"] = ("多头排列" if closes[-1] > ma20 > ma60 else
                        "空头排列" if closes[-1] < ma20 < ma60 else "震荡")
    # 简单可解释的规则状态，不冒充概率或回测策略净值。
    out["momentum_signal"] = ("正动量" if out["ret_20d"] > 0 else "非正动量") if out["ret_20d"] is not None else "样本不足"
    out["trend_signal"] = {"多头排列": "趋势观察", "空头排列": "防守观察", "震荡": "等待确认"}.get(out["trend"], "样本不足")
    return out


def render(rows, kit):
    from strategy_quant import _kit_sub, _kit_table, _kit_kv, _esc

    def number(value):
        return "—" if value is None else f"{value:.2f}"

    cells = [[
        _esc(r["market"] + "·" + r["name"]),
        _esc(str(r.get("as_of") or r.get("date") or r.get("overseas_date") or r.get("mainland_date") or "暂缺"))
        + " / " + number(r.get("close") if r.get("close") is not None else r.get("overseas_close")),
        _esc(r.get("source_label") or r.get("source") or "暂缺"),
        _esc(r.get("status") or "暂缺"),
        number(r.get("ret_20d") if r.get("usable") else None),
        _esc(r.get("trend", "样本不足") if r.get("usable") else "暂停判断"),
    ] for r in rows]
    return (
        _kit_sub(kit, "港股 / A股 / 美股指数 · 单源行情与主备状态") +
        _kit_table(kit, ["指数", "交易日 / 收盘", "数据源", "状态", "20日%", "趋势"], cells) +
        _kit_kv(kit, [
            ("数据口径", "采用单源未复权已收盘日线，主源优先、失败自动切换备用源（不做跨源比价交叉核验）；超过4个日历日保守标过期（长假需人工核查）。过期或缺数暂停判断；行情供应商数据不等于交易所官方认证；20日收益不是策略回测收益。"),
            ("主源 / 备用源", "主源：Yahoo Chart（query1.finance.yahoo.com）｜备用源：Yahoo镜像（query2）→ 东方财富历史K线（push2his 含镜像，待命备用）"),
            ("采集时间", _esc(max((r.get("collected_at", "") for r in rows), default="") or "暂缺")),
        ])
    )
