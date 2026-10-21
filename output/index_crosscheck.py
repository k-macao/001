"""三地指数：独立境内外供应商、同交易日未复权收盘核验。只经注入请求联网。"""
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
EM = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


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


def collect(fetch_json, *, now=None, tolerance_pct=0.1, max_age_days=4):
    """保守日历天时效门槛；长假可能标过期，不推测交易所假期。"""
    now = now or datetime.now(timezone.utc)
    output = []
    for market, name, symbol, secid in SPECS:
        row = dict(market=market, name=name, symbol=symbol, secid=secid,
                   collected_at=now.isoformat(), overseas_url=YAHOO + symbol,
                   mainland_url=EM, status="双源缺失", usable=False,
                   overseas_date=None, mainland_date=None, difference_pct=None)
        sources = []
        for kind in ("overseas", "mainland"):
            try:
                if kind == "overseas":
                    data = fetch_json(YAHOO + symbol, params={"range": "6mo", "interval": "1d"}, timeout=12)
                    result = data["chart"]["result"][0]
                    rows = [(datetime.fromtimestamp(t, providers.market_timezone(symbol)).strftime("%Y-%m-%d"), c)
                            for t, c in zip(result["timestamp"], result["indicators"]["quote"][0]["close"])]
                else:
                    data = fetch_json(EM, params={"secid": secid, "klt": 101, "fqt": 0,
                        "lmt": 130, "end": "20500101", "fields1": "f1,f2,f3,f4,f5,f6",
                        "fields2": "f51,f52,f53,f54,f55,f56"}, timeout=12)
                    # 名称校验阻止错误的跨供应商代码映射被当成同指数。
                    actual = str(data["data"].get("name", ""))
                    if symbol == "^IXIC" and ("100" in actual or "综合" not in actual):
                        raise ValueError("纳指映射须为综合指数而非纳指100")
                    rows = [(x.split(",")[0], x.split(",")[2]) for x in data["data"]["klines"]]
                bars = _clean(rows, symbol, now)
            except Exception as exc:
                bars = {}
                row[kind + "_error"] = type(exc).__name__
            sources.append(bars)
            row[kind + "_date"] = max(bars) if bars else None
            row[kind + "_close"] = bars[max(bars)] if bars else None
        overseas, mainland = sources
        if not overseas or not mainland:
            row["status"] = "单源待核验" if overseas or mainland else "双源缺失"
        elif max(overseas) != max(mainland):
            row["status"] = "交易日错位"
        else:
            day = max(overseas)
            diff = abs(overseas[day] / mainland[day] - 1) * 100
            age = (now.astimezone(providers.market_timezone(symbol)).date() - datetime.strptime(day, "%Y-%m-%d").date()).days
            row.update(difference_pct=diff, as_of=day)
            row["status"] = "数据过期" if age > max_age_days else "来源冲突" if diff > tolerance_pct else "双源一致"
            row["usable"] = row["status"] == "双源一致"
            if row["usable"]:
                row["history"] = [{"date": d, "close": overseas[d]} for d in sorted(overseas)]
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
    daily = [b/a-1 for a,b in zip(closes, closes[1:])]
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
    cells = [[_esc(r["market"] + "·" + r["name"]),
              _esc(str(r["overseas_date"] or "暂缺")) + " / " + number(r.get("overseas_close")),
              _esc(str(r["mainland_date"] or "暂缺")) + " / " + number(r.get("mainland_close")),
              number(r.get("difference_pct")), _esc(r["status"]),
              number(r.get("ret_20d") if r.get("usable") else None), _esc(r.get("trend", "样本不足") if r.get("usable") else "暂停判断")] for r in rows]
    return (_kit_sub(kit, "港股 / A股 / 美股指数 · 境内外交叉核验") +
            _kit_table(kit, ["指数", "Yahoo日期 / 收盘", "东方财富日期 / 收盘", "差异%", "核验", "20日%", "趋势"], cells) +
            _kit_kv(kit, [("核验口径", "同指数、同交易日、未复权已收盘日线；容差0.1%，超过4个日历日保守标过期（长假需人工核查）。仅双源一致输出动量与趋势；单源、错位、冲突暂停判断。两供应商一致不等于交易所认证；20日收益不是策略回测收益。"), ("境外 / 境内", "Yahoo Chart（query1.finance.yahoo.com） / 东方财富历史K线（push2his.eastmoney.com）"), ("采集时间", _esc(max((r.get("collected_at", "") for r in rows), default="") or "暂缺"))]))
