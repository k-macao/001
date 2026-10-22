#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🗄️ 市场数据库 —— 隐藏功能（不进日报、不推送、不出现在 --help）

定位
    每天三次（北京时间 08:00 / 12:30 / 17:00）把股票行情快照落库，写进
    ``output/market_db/YYYYMMDD.json``（**文件以日期为名字**，当天三次快照按
    0800 / 1230 / 1700 三档依次写进同一个文件）。这份库是 AI 分析 / AI 预测 /
    AI 模型的**基础数据**：记录单源行情快照（Yahoo 主源优先、备用源待命兜底）、
    特征与标签（见 build_dataset / export_dataset / ai_context）。

三条硬规则
    ① 单源优先（Yahoo 主源）：默认仅从主源 ``Yahoo Finance chart``（query1 → query2 镜像）
       取数，成功覆盖全部标的时**不触发任何备用源请求**，不做多源并发比价交叉验证；
    ② 备用源待命（按序故障切换）：仅当主源失败或漏采部分标的时，按顺序依次启用备用源 ——
       ``东方财富 push2 快照`` → ``腾讯财经 qt`` → ``新浪财经 hq`` →
       ``通达信行情 mootdx（沪深）`` → ``东方财富 push2his 日K``，且只补拉仍缺失的标的；
       未被调用的备用源标记为 ``standby``（备用待命）；全部源失败**不落库**；
    ③ 自我检查：每次落库对自己做一遍体检（结构 / 时段 / 主备源可用性 / 标的覆盖 /
       数值合理性 / 跨时段与跨日跳变 / 当天行情时效 / 文件哈希），结果写进文件
       ``self_check``，可随时 ``verify`` 复核（兼容历史版本库文件）。

通达信通道（mootdx，作为沪深备用源待命；保留防卡死四道闸）
    · 行情：``Quotes.factory(market='std')`` → ``quotes()``，覆盖沪深股票与指数
      （代码映射 sh600519 / sz000858 / sh000001）；港美股不在通达信标准行情内，
      仅在前序 HTTP 源仍缺失沪深标的（或显式指定 ``--sources tdx``）时启用；
    · 多主站：``OCTOPUS_DB_TDX_SERVERS="ip:port,…"`` 可指定，否则用 mootdx / tdxpy
      内置主站池依次试连（连不上自动换站，最多 4 站），命中站点写进 ``sources.tdx.host``；
    · 财务 / 除权除息：当通达信通道在 17:00 档被启用时，可附带 ``fundamentals`` 与
      ``corporate_actions``；未启用或未安装 mootdx 时绝不伪造数字。

防卡死四道闸（2026-10-01：一次 20 分钟作业被单台死主站拖到超时取消，逐条对症）
    ① 预置配置：创建客户端前先写好 ``~/.mootdx/config.json``（SERVER 主机池 + BESTIP）；
    ② TCP 预检：先用自己的 socket 探一次（``TDX_PROBE_TIMEOUT`` 3s），连不上的站不交给 mootdx；
    ③ 先验活后明细：每台主站先做一次 ``quotes()`` 验活，行情为空立刻换站，``auto_retry=False``；
    ④ 总预算：``TDX_BUDGET_SEC``（90s，可用 ``OCTOPUS_DB_TDX_BUDGET`` 覆盖）为通道墙钟上限。

绝不伪造
    主源与全部备用源都取不到某只标的就如实缺席（不猜数、不补历史数字）；全部源失败不写文件。

用法（隐藏入口二选一）
    python3 output/market_db.py pull      [--slot auto|0800|1230|1700] [--no-enrich] [--no-tdx]
    python3 output/market_db.py verify    [--date YYYY-MM-DD | --all] [--strict]
    python3 output/market_db.py export    --out FILE [--format jsonl|csv] [--start D] [--end D]
    python3 output/market_db.py stats     [--days 7]
    python3 output/market_db.py ai-context [--date YYYY-MM-DD] [--symbols 0700.HK,^HSI]
    python3 output/market_db.py prune     [--keep-days 90] [--dry-run]

    python3 output/pipeline.py --stock-db pull        # 同上（隐藏参数，--help 不显示）

给 AI 用（Python）
    import market_db
    ctx = market_db.ai_context()                       # 最近一档单源行情 + 新鲜度 + 质量标记
    rows, meta = market_db.build_dataset()             # 特征（只用过去）+ 标签（只用未来）
    market_db.export_dataset("ai.jsonl", fmt="jsonl")  # 落盘给训练 / 分析
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import socket
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlencode

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_ROOT = os.path.join(SCRIPT_DIR, "market_db")
CST = timezone(timedelta(hours=8))          # 北京时间 / 澳门时间
SCHEMA = "octopus-market-db/2"   # v2：新增通达信源 / 财务 / 除权除息

# ------------------------------------------------------------
# 口径常量（写死可复现；改任何一条都会影响库内容与自检结论）
# ------------------------------------------------------------
SLOTS: Tuple[str, ...] = ("0800", "1230", "1700")
SLOT_LABELS = {"0800": "盘前 08:00", "1230": "午间 12:30", "1700": "盘后 17:00"}
SLOT_HM = {"0800": (8, 0), "1230": (12, 30), "1700": (17, 0)}

PRIMARY_SOURCE = "yahoo"
BACKUP_SOURCES: Tuple[str, ...] = ("eastmoney", "tencent", "sina", "tdx", "em_kline")
SOURCE_ORDER: Tuple[str, ...] = (PRIMARY_SOURCE, *BACKUP_SOURCES)

CONF_HIGH, CONF_MID, CONF_LOW, CONF_SINGLE = 3, 2, 1, 0
CONF_LABELS = {3: "高", 2: "中", 1: "低", 0: "单源"}
MIN_SOURCES = 1           # 单源优先：主源（或任一备用源）成功即可落库，不要求多源并发比价
MIN_SYMBOL_COVER = 0.80   # 标的覆盖率下限
SCHEDULE_TOL_MIN = 180    # 拉取时刻与计划时刻的容差（GitHub 定时常有延迟）
SLOT_JUMP_PCT = 15.0      # 同日相邻时段价格跳变告警阈值
DAY_JUMP_PCT = 30.0       # 与前一交易日收盘价格跳变告警阈值
DEFAULT_TIMEOUT = 12
MAX_WORKERS = 6
TDX_SERVER_LIMIT = 4       # 通达信主站最多试连几个（内置池 38+ 个，逐个降级）
TDX_ACTION_DAYS = 45       # 除权除息只留最近 N 天（超过就不是「本次跳变」的原因了）
TDX_PROBE_TIMEOUT = 3      # 建 mootdx 客户端前的 TCP 预检上限（2026-10-01 修复）
TDX_SOCKET_TIMEOUT = 8     # 通达信单次调用 socket 超时（比 HTTP 的 12s 更紧，它是快协议）
TDX_BUDGET_SEC = 90        # 整个通达信通道的墙钟预算（秒）：到点收工，绝不拖垮作业


# ------------------------------------------------------------
# 数据源注册表（1 个主源 + 5 个备用源待命；每路内部可换镜像主机）
# ------------------------------------------------------------
SOURCES: Dict[str, Dict[str, Any]] = {
    "yahoo": {
        "label": "Yahoo Finance chart（主源）",
        "role": "primary", "kind": "quote", "delay": "可能延迟 15 分钟",
        "hosts": ("query1.finance.yahoo.com", "query2.finance.yahoo.com"),
    },
    "eastmoney": {
        "label": "东方财富 push2 行情快照（备用源）",
        "role": "backup", "kind": "quote", "delay": "实时",
        "hosts": ("push2.eastmoney.com", "82.push2.eastmoney.com", "72.push2.eastmoney.com"),
    },
    "tencent": {
        "label": "腾讯财经 qt.gtimg.cn（备用源）",
        "role": "backup", "kind": "quote", "delay": "实时",
        "hosts": ("qt.gtimg.cn",),
    },
    "sina": {
        "label": "新浪财经 hq.sinajs.cn（备用源）",
        "role": "backup", "kind": "quote", "delay": "实时",
        "hosts": ("hq.sinajs.cn",),
    },
    # 通达信通道（mootdx）：作为沪深备用源待命，主站池由 _tdx_servers() 依次试连。
    "tdx": {
        "label": "通达信行情 mootdx（沪深 · 备用源）",
        "role": "backup", "kind": "quote", "delay": "实时",
        "hosts": ("mootdx-tdx-server-pool",),
    },
    "em_kline": {
        "label": "东方财富 push2his 日K收盘（兜底备用源）",
        "role": "backup", "kind": "close", "delay": "收盘后",
        "hosts": ("push2his.eastmoney.com", "91.push2his.eastmoney.com", "63.push2his.eastmoney.com"),
    },
}

DEFAULT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
SINA_HEADERS = {"Referer": "https://finance.sina.com.cn/"}

# ------------------------------------------------------------
# 标的池：指数 + 港股蓝筹 + 美股龙头（可用 OCTOPUS_DB_SYMBOLS 覆盖）
#   · 港股个股池直接复用量化引擎的 HK_STOCK_UNIVERSE（单一事实来源，避免两处漂移）；
#   · 代码统一用 Yahoo 代码作主键（.HK / .SS / .SZ / ^XXX / 美股 ticker）。
# ------------------------------------------------------------
# 美股：只留两只会进 AI 行情复盘 / 情绪归因的龙头（东财 / Yahoo / 腾讯三路可覆盖）
US_STOCKS: List[Tuple[str, str, str]] = [
    ("微软", "MSFT", "US"), ("Meta", "META", "US"),
]

# A股：2026-10-01 随通达信通道（mootdx）补入的沪深蓝筹与热门标的。
# 这些标的在东财 / 新浪 / 腾讯 / Yahoo / 东财日K / 通达信六路都有行情，
# 是交叉验证最扎实的一批，也把数据库从「港股为主」扩成「港 + A + 美」。
A_STOCKS: List[Tuple[str, str, str]] = [
    ("贵州茅台", "600519.SS", "A"), ("宁德时代", "300750.SZ", "A"),
    ("中际旭创", "300308.SZ", "A"), ("比亚迪", "002594.SZ", "A"),
    ("招商银行", "600036.SS", "A"), ("中国平安", "601318.SS", "A"),
    ("五粮液", "000858.SZ", "A"), ("美的集团", "000333.SZ", "A"),
]

CORE_SYMBOLS: List[Tuple[str, str, str]] = [
    ("恒生指数", "^HSI", "HK"), ("恒生科技", "^HSTECH", "HK"), ("国企指数", "^HSCEI", "HK"),
    ("上证指数", "000001.SS", "A"), ("深证成指", "399001.SZ", "A"), ("创业板指", "399006.SZ", "A"),
    ("道琼斯", "^DJI", "US"), ("标普500", "^GSPC", "US"), ("纳斯达克", "^IXIC", "US"),
] + US_STOCKS + A_STOCKS

_EM_EXTRA_US = "105."        # 东财美股 secid 前缀（105 = 纳斯达克）


def _providers_universe() -> List[Tuple[str, str, str]]:
    """港股个股池：优先复用 octopus_quant.providers.HK_STOCK_UNIVERSE。"""
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from octopus_quant import providers as _p                  # noqa: WPS433
        return [(name, code, "HK") for name, code in _p.HK_STOCK_UNIVERSE]
    except Exception:
        return [
            ("腾讯控股", "0700.HK"), ("阿里巴巴-W", "9988.HK"), ("美团-W", "3690.HK"),
            ("小米集团-W", "1810.HK"), ("友邦保险", "1299.HK"), ("汇丰控股", "0005.HK"),
            ("建设银行", "0939.HK"), ("中国移动", "0941.HK"), ("香港交易所", "0388.HK"),
            ("中芯国际", "0981.HK"), ("比亚迪股份", "1211.HK"), ("快手-W", "1024.HK"),
            ("京东集团-SW", "9618.HK"), ("中国海洋石油", "0883.HK"), ("中国平安", "2318.HK"),
            ("安踏体育", "2020.HK"), ("网易-S", "9999.HK"), ("药明生物", "2269.HK"),
        ]


def symbol_universe() -> List[Tuple[str, str, str]]:
    """(名称, 代码, 市场)；OCTOPUS_DB_SYMBOLS 形如 ``0700.HK:腾讯控股,^HSI`` 可覆盖。"""
    env = os.environ.get("OCTOPUS_DB_SYMBOLS", "").strip()
    if env:
        out = []
        for chunk in env.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if ":" in chunk:
                code, name = chunk.split(":", 1)
                out.append((name.strip() or code.strip(), code.strip(), market_of(code.strip())))
            else:
                out.append((chunk, chunk, market_of(chunk)))
        return out or _default_universe()
    return _default_universe()


def _default_universe() -> List[Tuple[str, str, str]]:
    seen, out = set(), []
    for name, code, mk in list(CORE_SYMBOLS) + _providers_universe():
        if code in seen:
            continue
        seen.add(code)
        out.append((name, code, mk or market_of(code)))
    return out


def market_of(symbol: str) -> str:
    sym = str(symbol or "").strip()
    if sym.endswith(".HK") or sym in ("^HSI", "^HSTECH", "^HSCEI"):
        return "HK"
    if sym.endswith(".SS") or sym.endswith(".SZ"):
        return "A"
    return "US"


def em_secid(symbol: str) -> str:
    """Yahoo 代码 → 东财 secid（复用 backup_sources 的口径，美股补 105 前缀）。"""
    try:
        sys.path.insert(0, SCRIPT_DIR)
        import backup_sources as _bk                                # noqa: WPS433
        secid = _bk.em_secid_for_yahoo(symbol)
        if secid:
            return secid
    except Exception:
        pass
    sym = str(symbol or "").strip()
    table = {"^HSI": "100.HSI", "^HSTECH": "100.HSTECH", "^HSCEI": "100.HSCEI", "^HSCE": "100.HSCEI",
             "^DJI": "100.DJIA", "^GSPC": "100.SPX", "^IXIC": "100.NDX"}
    if sym in table:
        return table[sym]
    if sym.endswith(".HK") and sym[:-3].isdigit():
        return f"116.{int(sym[:-3]):05d}"
    if sym.endswith(".SS") and sym[:-3].isdigit():
        return f"1.{sym[:-3]}"
    if sym.endswith(".SZ") and sym[:-3].isdigit():
        return f"0.{sym[:-3]}"
    if re.fullmatch(r"[A-Za-z.]{1,6}", sym):
        return f"{_EM_EXTRA_US}{sym.upper()}"
    return ""


def em_secids(symbol: str) -> Tuple[str, ...]:
    """东财 secid 候选列表（恒生科技同时尝试 100.HSTECH 与 124.HSTECH）。"""
    sym = str(symbol or "").strip()
    if sym == "^HSTECH":
        return ("100.HSTECH", "124.HSTECH")
    sec = em_secid(sym)
    return (sec,) if sec else ()


def sina_code(symbol: str) -> str:
    """Yahoo 代码 → 新浪 hq 代码。新浪美股字段顺序与 A/港不同，不纳入（避免误读数字）。"""
    sym = str(symbol or "").strip()
    hk_index = {"^HSI": "hkHSI", "^HSTECH": "hkHSTECH", "^HSCEI": "hkHSCEI", "^HSCE": "hkHSCEI"}
    if sym in hk_index:
        return hk_index[sym]
    if sym.endswith(".HK") and sym[:-3].isdigit():
        return f"hk{int(sym[:-3]):05d}"
    if sym.endswith(".SS") and sym[:-3].isdigit():
        return f"sh{sym[:-3]}"
    if sym.endswith(".SZ") and sym[:-3].isdigit():
        return f"sz{sym[:-3]}"
    return ""


def tdx_code(symbol: str) -> str:
    """Yahoo 代码 → 通达信代码（仅沪深：sh600519 / sz000858 / sh000001）。

    通达信标准行情（mootdx std）只有沪深市场；扩展市场接口在 mootdx 内部已标注失效，
    港美股一律返回空串 → 该源不参与这些标的，绝不拿错市场的数字充数。
    """
    sym = str(symbol or "").strip()
    if sym.endswith(".SS") and sym[:-3].isdigit():
        return f"sh{sym[:-3]}"
    if sym.endswith(".SZ") and sym[:-3].isdigit():
        return f"sz{sym[:-3]}"
    return ""


def tencent_code(symbol: str) -> str:
    """Yahoo 代码 → 腾讯 qt 代码。"""
    sym = str(symbol or "").strip()
    table = {"^HSI": "hkHSI", "^HSTECH": "hkHSTECH", "^HSCEI": "hkHSCEI",
             "^DJI": "usDJI", "^GSPC": "usINX", "^IXIC": "usIXIC"}
    if sym in table:
        return table[sym]
    if sym.endswith(".HK") and sym[:-3].isdigit():
        return f"hk{int(sym[:-3]):05d}"
    if sym.endswith(".SS") and sym[:-3].isdigit():
        return f"sh{sym[:-3]}"
    if sym.endswith(".SZ") and sym[:-3].isdigit():
        return f"sz{sym[:-3]}"
    if re.fullmatch(r"[A-Za-z.]{1,6}", sym):
        return f"us{sym.upper()}"
    return ""


# ============================================================
# HTTP（requests 优先，缺失回退 urllib；可整体注入假实现供离线测试）
# ============================================================
class Http:
    """极简 HTTP 客户端：``get(url) -> (payload, error)``，永不抛异常。"""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT, retries: int = 1):
        self.timeout = timeout
        self.retries = max(0, int(retries))
        try:
            import requests as _requests                            # noqa: WPS433
        except Exception:
            _requests = None
        self._requests = _requests

    def get(self, url: str, headers: Optional[Dict[str, str]] = None,
            timeout: Optional[int] = None, is_text: bool = False):
        timeout = int(timeout or self.timeout)
        merged = {**DEFAULT_HEADERS, **(headers or {})}
        last_err = "未知错误"
        for _ in range(self.retries + 1):
            payload, err = self._once(url, merged, timeout, is_text)
            if err is None:
                return payload, None
            last_err = err
        return None, last_err

    def _once(self, url, headers, timeout, is_text):
        if self._requests is not None:
            try:
                resp = self._requests.get(url, headers=headers, timeout=timeout)
                resp.raise_for_status()
                return (resp.text if is_text else resp.json()), None
            except Exception as exc:                                # noqa: BLE001
                return None, f"{type(exc).__name__}: {exc}"
        try:
            import urllib.request                                   # noqa: WPS433
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            text = raw.decode("utf-8", "replace")
            if is_text:
                return text, None
            try:
                return json.loads(text), None
            except Exception:                                       # noqa: BLE001
                return None, "返回内容不是合法 JSON"
        except Exception as exc:                                    # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"


def _num(value, ndigits: Optional[int] = 6) -> Optional[float]:
    """容错取数：'—' / '' / None / 非数字 → None；非法值绝不折算成 0。"""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        out = float(value)
    else:
        text = str(value).strip().replace(",", "").replace("%", "")
        if not text or text in ("-", "—", "null", "None"):
            return None
        try:
            out = float(text)
        except ValueError:
            return None
    if math.isnan(out) or math.isinf(out):
        return None
    return round(out, ndigits) if ndigits is not None else out


def _pct(price: Optional[float], prev: Optional[float]) -> Optional[float]:
    if price is None or prev is None or prev <= 0:
        return None
    return round((price / prev - 1.0) * 100.0, 4)


def _ts_text(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), CST).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return None


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(CST)


def resolve_slot(slot: str = "auto", now: Optional[datetime] = None) -> str:
    """auto：按北京时间就近匹配三档（08:00 / 12:30 / 17:00，跨零点按环形距离）。"""
    if slot and slot != "auto":
        return str(slot)
    minutes = _now(now).hour * 60 + _now(now).minute
    return min(SLOTS, key=lambda s: min(abs(minutes - (SLOT_HM[s][0] * 60 + SLOT_HM[s][1])),
                                        1440 - abs(minutes - (SLOT_HM[s][0] * 60 + SLOT_HM[s][1]))))


def scheduled_at(date_str: str, slot: str) -> str:
    hour, minute = SLOT_HM[slot]
    return f"{date_str} {hour:02d}:{minute:02d}:00"


# ============================================================
# 各源适配器：统一返回 _source_result(...)
# ============================================================
def _source_result(key: str, status: str, *, quotes: Optional[Dict[str, Any]] = None,
                   host: str = "", error: str = "", elapsed_ms: int = 0,
                   quote_time: Optional[str] = None) -> Dict[str, Any]:
    return {
        "key": key, "label": SOURCES[key]["label"], "status": status,
        "role": SOURCES[key].get("role", "backup"),
        "host": host, "error": error or None, "elapsed_ms": int(elapsed_ms),
        "quote_time": quote_time, "quotes": quotes or {},
        "symbols": len(quotes or {}),
    }


def _quote(price, *, prev_close=None, open_=None, high=None, low=None, volume=None,
           amount=None, quote_time=None, name="") -> Optional[Dict[str, Any]]:
    price = _num(price)
    if price is None or price <= 0:
        return None
    prev_close = _num(prev_close)
    high, low = _num(high), _num(low)
    if high is not None and low is not None and high < low:
        high, low = low, high
    return {
        "price": price, "prev_close": prev_close, "open": _num(open_),
        "high": high, "low": low, "volume": _num(volume, 0), "amount": _num(amount, 2),
        "change_pct": _pct(price, prev_close),
        "quote_time": quote_time, "name": str(name or "").strip(),
    }


# ------------------------------------------------------------
# ① 东方财富 push2 行情快照
# ------------------------------------------------------------
def fetch_eastmoney(symbols: Sequence[str], http, timeout: int = DEFAULT_TIMEOUT,
                    **_kw) -> Dict[str, Any]:
    started = time.time()
    secids: Dict[str, str] = {}
    for s in symbols:
        for sec in em_secids(s):
            secids.setdefault(sec, s)
    if not secids:
        return _source_result("eastmoney", "failed", error="无可用 secid 映射")
    params = {
        "fltt": "2", "invt": "2", "secids": ",".join(secids),
        "fields": "f2,f3,f4,f5,f6,f12,f13,f14,f15,f16,f17,f18,f124",
    }
    last_err = "无可用主机"
    for host in SOURCES["eastmoney"]["hosts"]:
        url = f"https://{host}/api/qt/ulist.np/get?{urlencode(params)}"
        data, err = http.get(url, timeout=timeout)
        if err:
            last_err = err
            continue
        rows = ((data or {}).get("data") or {}).get("diff") or []
        if not rows:
            last_err = "返回 data.diff 为空"
            continue
        quotes, stamps = {}, []
        for row in rows:
            secid = f"{row.get('f13')}.{row.get('f12')}"
            sym = secids.get(secid)
            item = _quote(row.get("f2"), prev_close=row.get("f18"), open_=row.get("f17"),
                          high=row.get("f15"), low=row.get("f16"), volume=row.get("f5"),
                          amount=row.get("f6"), quote_time=_ts_text(row.get("f124")),
                          name=row.get("f14"))
            if not sym or item is None:
                continue
            if item["quote_time"]:
                stamps.append(item["quote_time"])
            quotes[sym] = item
        if not quotes:
            last_err = "返回行情全部无效"
            continue
        return _source_result("eastmoney", "ok", quotes=quotes, host=host,
                              quote_time=max(stamps) if stamps else None,
                              elapsed_ms=(time.time() - started) * 1000)
    return _source_result("eastmoney", "failed", error=last_err,
                          elapsed_ms=(time.time() - started) * 1000)


# ------------------------------------------------------------
# ② 新浪财经 hq.sinajs.cn（A股 / 港股）
# ------------------------------------------------------------
def _parse_sina_line(code: str, payload: str) -> Optional[Dict[str, Any]]:
    parts = payload.split(",")
    if code.startswith(("sh", "sz")):
        if len(parts) < 10:
            return None
        stamp = None
        if len(parts) >= 32 and re.match(r"\d{4}-\d{2}-\d{2}$", parts[30].strip()):
            stamp = f"{parts[30].strip()} {parts[31].strip()[:8] or '00:00:00'}"
        return _quote(parts[3], prev_close=parts[2], open_=parts[1], high=parts[4], low=parts[5],
                      volume=parts[8], amount=parts[9], quote_time=stamp, name=parts[0])
    if code.startswith("hk"):
        # 港股：名称(英),名称(中),今开,昨收,最高,最低,现价,涨跌额,涨跌幅,…,日期,时间
        if len(parts) < 7:
            return None
        stamp = None
        tail = [p.strip() for p in parts[-3:]]
        for idx, token in enumerate(tail):
            if re.match(r"\d{4}[-/]\d{2}[-/]\d{2}$", token) and idx + 1 < len(tail):
                stamp = f"{token.replace('/', '-')} {tail[idx + 1][:8] or '00:00:00'}"
        return _quote(parts[6], prev_close=parts[3], open_=parts[2], high=parts[4], low=parts[5],
                      quote_time=stamp, name=parts[1] or parts[0])
    return None


def fetch_sina(symbols: Sequence[str], http, timeout: int = DEFAULT_TIMEOUT,
               **_kw) -> Dict[str, Any]:
    started = time.time()
    code_to_sym = {}
    for sym in symbols:
        code = sina_code(sym)
        if code:
            code_to_sym[code] = sym
    if not code_to_sym:
        return _source_result("sina", "failed", error="无可用 hq 代码映射")
    url = "https://hq.sinajs.cn/list=" + ",".join(code_to_sym)
    text, err = http.get(url, headers=SINA_HEADERS, timeout=timeout, is_text=True)
    if err:
        return _source_result("sina", "failed", error=err, elapsed_ms=(time.time() - started) * 1000)
    quotes, stamps = {}, []
    for match in re.finditer(r'hq_str_([A-Za-z]{2}\w+)="([^"]*)"', str(text or "")):
        code, payload = match.group(1), match.group(2)
        sym = code_to_sym.get(code)
        if not sym or not payload.strip():
            continue
        item = _parse_sina_line(code, payload)
        if item is None:
            continue
        if item["quote_time"]:
            stamps.append(item["quote_time"])
        quotes[sym] = item
    if not quotes:
        return _source_result("sina", "failed", error="返回内容无可用行情",
                              elapsed_ms=(time.time() - started) * 1000)
    return _source_result("sina", "ok", quotes=quotes, host="hq.sinajs.cn",
                          quote_time=max(stamps) if stamps else None,
                          elapsed_ms=(time.time() - started) * 1000)


# ------------------------------------------------------------
# ③ 腾讯财经 qt.gtimg.cn
# ------------------------------------------------------------
def _parse_tencent_line(payload: str) -> Optional[Dict[str, Any]]:
    parts = payload.split("~")
    if len(parts) < 6:
        return None
    stamp = None
    for token in parts:
        token = token.strip()
        if re.fullmatch(r"\d{14}", token):
            stamp = (f"{token[0:4]}-{token[4:6]}-{token[6:8]} "
                     f"{token[8:10]}:{token[10:12]}:{token[12:14]}")
            break
    price = _num(parts[3])
    high, low = None, None
    if len(parts) > 34 and price:
        # 高 / 低只做「合理性校验后」才采用：位置不符或数值不合理（不满足 low ≤ price ≤ high、
        # 偏离 >25%）一律丢弃。宁可少一个字段，也不写入位置错位的数字。
        cand_high, cand_low = _num(parts[33]), _num(parts[34])
        if (cand_high and cand_low and cand_low <= price <= cand_high
                and cand_high <= price * 1.25 and cand_low >= price * 0.75):
            high, low = cand_high, cand_low
    amount = _num(parts[37], 2) if len(parts) > 37 else None
    if amount is not None and not (0 < amount < 1e13):
        amount = None
    return _quote(parts[3], prev_close=parts[4], open_=parts[5], high=high, low=low,
                  amount=amount, quote_time=stamp, name=parts[1] if len(parts) > 1 else "")


def fetch_tencent(symbols: Sequence[str], http, timeout: int = DEFAULT_TIMEOUT,
                  **_kw) -> Dict[str, Any]:
    started = time.time()
    code_to_sym = {}
    for sym in symbols:
        code = tencent_code(sym)
        if code:
            code_to_sym[code] = sym
    if not code_to_sym:
        return _source_result("tencent", "failed", error="无可用 qt 代码映射")
    url = "https://qt.gtimg.cn/q=" + ",".join(code_to_sym)
    text, err = http.get(url, headers={"Referer": "https://gu.qq.com/"}, timeout=timeout, is_text=True)
    if err:
        return _source_result("tencent", "failed", error=err, elapsed_ms=(time.time() - started) * 1000)
    quotes, stamps = {}, []
    for match in re.finditer(r'v_([A-Za-z0-9_]+)="([^"]*)"', str(text or "")):
        code, payload = match.group(1), match.group(2)
        sym = code_to_sym.get(code)
        if not sym or not payload.strip():
            continue
        item = _parse_tencent_line(payload)
        if item is None:
            continue
        if item["quote_time"]:
            stamps.append(item["quote_time"])
        quotes[sym] = item
    if not quotes:
        return _source_result("tencent", "failed", error="返回内容无可用行情",
                              elapsed_ms=(time.time() - started) * 1000)
    return _source_result("tencent", "ok", quotes=quotes, host="qt.gtimg.cn",
                          quote_time=max(stamps) if stamps else None,
                          elapsed_ms=(time.time() - started) * 1000)


# ------------------------------------------------------------
# ④ Yahoo Finance chart（逐只取最新快照）
# ------------------------------------------------------------
def _yahoo_quote_from_chart(data) -> Optional[Dict[str, Any]]:
    try:
        result = ((data or {}).get("chart") or {}).get("result") or []
        meta = (result[0] or {}).get("meta") or {}
    except (AttributeError, IndexError, TypeError):
        return None
    price = _num(meta.get("regularMarketPrice"))
    if price is None or price <= 0:
        return None
    prev = _num(meta.get("chartPreviousClose")) or _num(meta.get("previousClose"))
    ts = meta.get("regularMarketTime")
    quote_time = None
    try:
        quote_time = datetime.fromtimestamp(int(ts), CST).strftime("%Y-%m-%d %H:%M:%S") if ts else None
    except (OverflowError, OSError, TypeError, ValueError):
        quote_time = None
    return _quote(price, prev_close=prev, open_=meta.get("regularMarketOpen"),
                  high=meta.get("regularMarketDayHigh"), low=meta.get("regularMarketDayLow"),
                  volume=meta.get("regularMarketVolume"),
                  quote_time=quote_time, name=meta.get("shortName") or "")


_YAHOO_ALIASES: Dict[str, Tuple[str, ...]] = {
    "^HSTECH": ("^HSTECH", "HSTECH.HK"),
    "^HSCEI": ("^HSCEI", "^HSCE"),
    "^HSCE": ("^HSCE", "^HSCEI"),
}


def fetch_yahoo(symbols: Sequence[str], http, timeout: int = DEFAULT_TIMEOUT,
                **_kw) -> Dict[str, Any]:
    started = time.time()

    def one(sym: str):
        # 单只标的的异常绝不允许拖垮整路源（网络抖动 / 返回结构变化只丢这一只）
        try:
            for host in SOURCES["yahoo"]["hosts"]:
                for cand in _YAHOO_ALIASES.get(sym, (sym,)):
                    url = (f"https://{host}/v8/finance/chart/{cand}"
                           f"?range=1d&interval=1d&includePrePost=false")
                    data, err = http.get(url, timeout=timeout)
                    if err:
                        continue
                    item = _yahoo_quote_from_chart(data)
                    if item is not None:
                        return sym, item
        except Exception:                                           # noqa: BLE001
            return sym, None
        return sym, None

    quotes, stamps, workers = {}, [], max(1, min(MAX_WORKERS, len(symbols)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for sym, item in pool.map(one, list(symbols)):
            if item is None:
                continue
            if item["quote_time"]:
                stamps.append(item["quote_time"])
            quotes[sym] = item
    if not quotes:
        return _source_result("yahoo", "failed", error="双主机均无有效快照",
                              elapsed_ms=(time.time() - started) * 1000)
    return _source_result("yahoo", "ok", quotes=quotes, host=SOURCES["yahoo"]["hosts"][0],
                          quote_time=max(stamps) if stamps else None,
                          elapsed_ms=(time.time() - started) * 1000)


# ------------------------------------------------------------
# ⑤ 东方财富 push2his 日K（收盘校验源：只给昨收 / 收盘，不参与盘中比价）
# ------------------------------------------------------------
def _em_kline_last_close(data) -> Optional[Dict[str, Any]]:
    try:
        klines = ((data or {}).get("data") or {}).get("klines") or []
        row = str(klines[-1]).split(",")
        date_str, close = row[0].strip(), _num(row[2])
    except (AttributeError, IndexError, TypeError):
        return None
    if not date_str or close is None or close <= 0:
        return None
    return {"close": close, "date": date_str, "open": _num(row[1]) if len(row) > 1 else None,
            "high": _num(row[3]) if len(row) > 3 else None,
            "low": _num(row[4]) if len(row) > 4 else None,
            "volume": _num(row[5], 0) if len(row) > 5 else None,
            "amount": _num(row[6], 2) if len(row) > 6 else None}


def fetch_em_kline(symbols: Sequence[str], http, timeout: int = DEFAULT_TIMEOUT,
                   **_kw) -> Dict[str, Any]:
    """返回 {代码: {close, date, …}}：注意 close 是**最近一个已收盘交易日**的收盘价。"""
    started = time.time()
    sym_cands = [(s, em_secids(s)) for s in symbols if em_secids(s)]
    if not sym_cands:
        return _source_result("em_kline", "failed", error="无可用 secid 映射")

    def one(pair: Tuple[str, Tuple[str, ...]]):
        sym, cands = pair
        # 单只标的的异常只丢这一只，不影响整路兜底源
        try:
            for secid in cands:
                params = {"secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
                          "fields2": "f51,f52,f53,f54,f55,f56,f57", "klt": "101", "fqt": "1",
                          "end": "20500101", "lmt": "3"}
                for host in SOURCES["em_kline"]["hosts"]:
                    url = f"https://{host}/api/qt/stock/kline/get?{urlencode(params)}"
                    data, err = http.get(url, timeout=timeout)
                    if err:
                        continue
                    item = _em_kline_last_close(data)
                    if item is not None:
                        return sym, item
        except Exception:                                           # noqa: BLE001
            return sym, None
        return sym, None

    rows, stamps, workers = {}, [], max(1, min(MAX_WORKERS, len(sym_cands)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for sym, item in pool.map(one, sym_cands):
            if item is None:
                continue
            stamps.append(item["date"])
            rows[sym] = item
    if not rows:
        return _source_result("em_kline", "failed", error="三主机均无有效日K",
                              elapsed_ms=(time.time() - started) * 1000)
    return _source_result("em_kline", "ok", quotes=rows, host=SOURCES["em_kline"]["hosts"][0],
                          quote_time=max(stamps) if stamps else None,
                          elapsed_ms=(time.time() - started) * 1000)


# ------------------------------------------------------------
# ⑥ 通达信行情（mootdx，2026-10-01 升级）—— 沪深行情 + 收盘校验 + 财务 / 除权除息
# ------------------------------------------------------------
def _records(obj) -> List[Dict[str, Any]]:
    """把 mootdx 的返回拍成「字典列表」：支持 pandas.DataFrame / list[dict] / dict[list]。

    单独做一层适配是为了让测试可以注入「纯 Python 假客户端」（不依赖 pandas），
    生产环境里 mootdx 返回的 DataFrame 走 to_dict("records") 同一路径。
    """
    if obj is None:
        return []
    if isinstance(obj, list):
        return [row for row in obj if isinstance(row, dict)]
    if isinstance(obj, dict):
        keys = list(obj)
        if not keys:
            return []
        if isinstance(obj[keys[0]], (list, tuple)):
            return [dict(zip(keys, values)) for values in zip(*[obj[k] for k in keys])]
        return [dict(obj)]
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            return [row for row in (to_dict("records") or []) if isinstance(row, dict)]
        except Exception:                                           # noqa: BLE001
            return []
    return []


def _tdx_servers(limit: int = TDX_SERVER_LIMIT) -> List[Tuple[str, int]]:
    """候选主站：OCTOPUS_DB_TDX_SERVERS → mootdx 内置池 → tdxpy 内置池（去重后取前 N 个）。"""
    out: List[Tuple[str, int]] = []
    for chunk in os.environ.get("OCTOPUS_DB_TDX_SERVERS", "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        host, _, port = chunk.partition(":")
        if host.strip():
            out.append((host.strip(), int(port) if port.strip().isdigit() else 7709))
    try:
        from mootdx import consts as _consts                    # noqa: WPS433
        out.extend((str(ip), int(port)) for _n, ip, port in (getattr(_consts, "HQ_HOSTS", ()) or ()))
    except Exception:                                               # noqa: BLE001
        pass
    try:
        from tdxpy.constants import hq_hosts as _hosts          # noqa: WPS433
        out.extend((str(ip), int(port)) for _n, ip, port in (_hosts or ()))
    except Exception:                                               # noqa: BLE001
        pass
    seen, unique = set(), []
    for host, port in out:
        if (host, port) in seen:
            continue
        seen.add((host, port))
        unique.append((host, port))
    return unique[:max(1, int(limit))]


def _tdx_installed() -> bool:
    try:
        import importlib.util as _ilu                              # noqa: WPS433
        return _ilu.find_spec("mootdx") is not None
    except Exception:                                               # noqa: BLE001
        return False


_TDX_CONFIG_LOCK = threading.Lock()      # 预置配置只做一次，多个客户端并发也不会写花


def _mootdx_config_path() -> str:
    """mootdx 的配置文件路径：``$HOME/.mootdx/config.json``（与 mootdx 自己的规则一致）。

    · 不调 ``mootdx.utils.get_config_path``：那个函数会顺手 mkdir，只读路径的调用不该有副作用
      （口径一致性由 tests 里的 `test_config_path_matches_mootdx_rule` 盯着）；
    · ``OCTOPUS_DB_TDX_CONFIG`` 可覆盖（HOME 只读、或想把配置放在工作区内时用）。
    """
    override = os.environ.get("OCTOPUS_DB_TDX_CONFIG", "").strip()
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".mootdx", "config.json")


def _tdx_config_payload(server: Optional[Tuple[str, int]] = None) -> Optional[Dict[str, Any]]:
    """构造一份 mootdx 认的配置（结构必须与 mootdx 自己写出来的一模一样）。

    ``SERVER`` 直接搬 mootdx 内置主机池（JSON 里元组变列表，mootdx 也这么存）；
    ``BESTIP`` 写本次要连的主站，mootdx 就不会再去跑 bestip 探测。
    """
    try:
        from mootdx import consts as _consts                     # noqa: WPS433
    except Exception:                                               # noqa: BLE001
        return None
    if not getattr(_consts, "HQ_HOSTS", None):
        return None
    hosts = {}
    for key in ("HQ", "EX", "GP"):
        rows = getattr(_consts, f"{key}_HOSTS", ()) or ()
        hosts[key] = [[str(site), str(ip), int(port)] for site, ip, port in rows]
    bestip: Dict[str, Any] = {"HQ": "", "EX": "", "GP": ""}
    if server:
        bestip["HQ"] = [str(server[0]), int(server[1])]
    return {"SERVER": hosts, "BESTIP": bestip, "TDXDIR": str(getattr(_consts, "TDXDIR", "C:/new_tdx"))}


def _ensure_tdx_config(host: str, port: int, *, path: Optional[str] = None) -> Optional[str]:
    """创建 mootdx 客户端**之前**把配置文件写好（返回写好的路径 / None=没写）。

    · 已存在且是合法 JSON → 原样尊重（CI 或用户可自行预置主站）；
    · 缺失 / 损坏 → 用 mootdx 内置主机池 + 本次选中的主站写一份；
    · HOME 只读等写不进去 → 返回 None 静默降级（后面还有预检 + 预算兜底），绝不抛异常。
    """
    target = path or _mootdx_config_path()
    with _TDX_CONFIG_LOCK:
        try:
            with open(target, "r", encoding="utf-8") as fh:
                if isinstance(json.load(fh), dict):
                    return target
        except (OSError, ValueError):
            pass
        payload = _tdx_config_payload((host, port))
        if payload is None:
            return None
        try:
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
        except OSError:
            return None
        return target


def _tdx_probe(host: str, port: int, timeout: int = TDX_PROBE_TIMEOUT, *,
               connector: Optional[Callable[..., Any]] = None) -> Tuple[bool, str]:
    """TCP 预检：能连上才算「活着」（3s 上限），连不上的站根本不交给 mootdx。

    为什么必须自己先探一次：tdxpy 的 ``connect()`` 把 socket.timeout 吞掉并 return False，
    ``mootdx.StdQuotes.__init__`` 又不检查这个返回值 —— SYN 被丢弃的死站会被当成
    「连上了」，随后每次 API 调用都跑一遍 auto_retry 阶梯（4 次重连 × 5s + 退避 sleep），
    单台主站就足以把 20 分钟的作业拖到被取消。
    """
    connect = connector or socket.create_connection
    try:
        sock = connect((str(host), int(port)), timeout=max(1, int(timeout)))
    except Exception as exc:                                        # noqa: BLE001
        return False, f"{host}:{port} TCP 预检失败（{type(exc).__name__}）"
    try:
        close = getattr(sock, "close", None)
        close and close()
    except Exception:                                               # noqa: BLE001
        pass
    return True, ""


def _open_tdx_client(host: str, port: int, timeout: int, *, connector: Optional[Callable[..., Any]] = None,
                     factory: Optional[Callable[..., Any]] = None):
    """连接一台通达信主站；未安装 mootdx / 预检不过 / 建连异常都返回 (None, 原因)。

    · 预检通过才建客户端（SYN 被丢 / 端口不通 3s 内换下一台）；
    · ``auto_retry=False``：tdxpy 的重连阶梯是「单台死站拖垮整个作业」的主因，
      重试责任交给 ``fetch_tdx`` 的主站池逐个降级（语义更清楚，也不再重复烧墙钟）。
    """
    if factory is None and not _tdx_installed():
        return None, "未安装 mootdx（pip install mootdx）"
    ok, err = _tdx_probe(host, port, min(TDX_PROBE_TIMEOUT, max(1, int(timeout))), connector=connector)
    if not ok:
        return None, err
    _ensure_tdx_config(host, port)
    maker = factory
    if maker is None:
        try:
            from mootdx.quotes import Quotes                     # noqa: WPS433
        except Exception as exc:                                    # noqa: BLE001
            return None, f"未安装 mootdx（pip install mootdx）：{type(exc).__name__}"
        maker = Quotes.factory
    try:
        return maker(market="std", server=(host, int(port)), timeout=int(timeout), heartbeat=False,
                     auto_retry=False), ""
    except Exception as exc:                                        # noqa: BLE001
        return None, f"{host}:{port} {type(exc).__name__}: {exc}"


def _tdx_budget(budget: Optional[float] = None) -> float:
    """本次通达信通道的墙钟预算（秒）：参数 → ``OCTOPUS_DB_TDX_BUDGET`` → 默认 90s。"""
    if budget is None:
        raw = os.environ.get("OCTOPUS_DB_TDX_BUDGET", "")
        try:
            budget = float(raw) if str(raw).strip() else float(TDX_BUDGET_SEC)
        except ValueError:
            budget = float(TDX_BUDGET_SEC)
    return max(0.0, float(budget))


def _tdx_time_left(deadline: Optional[float]) -> float:
    """距预算到点还剩几秒；没有 deadline 就是无限（测试注入 fake 客户端时走这条）。"""
    return math.inf if deadline is None else deadline - time.monotonic()


def _tdx_quote_time(servertime: Any, date_str: str) -> Optional[str]:
    """通达信只给 HH:MM:SS[.mmm]（不含日期）→ 用落库日期补全成时间戳。"""
    match = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", str(servertime or "").strip())
    if not match:
        return None
    return f"{date_str} {int(match.group(1)):02d}:{match.group(2)}:{match.group(3) or '00'}"


def _tdx_symbols_by_code(pairs: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """通达信返回的 code 不带市场前缀 → 建两级索引，避免沪深同号撞车。

    返回 ({(market, code): symbol}, {code: symbol})：
      · 主索引用 ``market`` 字段（mootdx：1=沪 0=深）精确定位（如 000001.SS vs 000001.SZ）；
      · 备索引只按数字代码，用于 market 字段缺失的客户端。
    """
    keyed, bare = {}, {}
    for code, sym in pairs.items():
        prefix, digits = (code[:2], code[2:]) if code[:2] in ("sh", "sz") else ("", code)
        bare.setdefault(digits, sym)
        if prefix:
            keyed[f"{1 if prefix == 'sh' else 0}.{digits}"] = sym
    return keyed, bare


def _tdx_quotes(client, pairs: Dict[str, str], date_str: str,
                session_dates: Optional[Dict[str, str]] = None) -> Dict[str, Dict[str, Any]]:
    """通达信只给 HH:MM:SS；日期用日K最后一根推出来的「交易日」补全（缺了才退回落库日）。

    这一点很关键：08:00 盘前拉到的其实是**上一交易日**的收盘快照，
    若不按交易日补日期，就会把昨天的价记成今天 14:59，等于凭空造时间戳。
    """
    rows = _records(client.quotes(symbol=list(pairs)))
    keyed, bare = _tdx_symbols_by_code(pairs)
    quotes: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("code") or "").strip()
        sym = keyed.get(f"{row.get('market')}.{code}") or bare.get(code)
        if not sym:
            continue
        stamp_date = (session_dates or {}).get(sym) or date_str
        item = _quote(row.get("price"), prev_close=row.get("last_close"), open_=row.get("open"),
                      high=row.get("high"), low=row.get("low"), volume=row.get("vol"),
                      amount=row.get("amount"), quote_time=_tdx_quote_time(row.get("servertime"), stamp_date))
        if item is not None:
            quotes[sym] = item
    return quotes


def _tdx_restamp(quotes: Dict[str, Dict[str, Any]],
                 session_dates: Optional[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    """日K给出的交易日回填行情时间戳的日期部分（盘前拉到的是**上一交易日**的收盘快照）。

    只换日期、保留 ``HH:MM:SS``：通达信只回报时刻，日期本来就只能从日K推。
    """
    for sym, item in quotes.items():
        day = str((session_dates or {}).get(sym) or "")
        stamp = str(item.get("quote_time") or "")
        if len(day) == 10 and len(stamp) >= 19:
            item["quote_time"] = f"{day} {stamp[11:]}"
    return quotes


def _tdx_eod_closes(client, pairs: Dict[str, str],
                    deadline: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """日K（frequency=9）最后一条收盘 → 与东财日K组成「双源收盘核对」。

    deadline 到点就收手：宁可少几只收盘核对，也不让通道拖过总预算（数据只少不假）。
    """
    out: Dict[str, Dict[str, Any]] = {}
    for code, sym in pairs.items():
        if _tdx_time_left(deadline) <= 0:
            break
        try:
            rows = _records(client.bars(symbol=code, frequency=9, offset=2))
        except Exception:                                           # noqa: BLE001
            rows = []
        if not rows:
            continue
        last = rows[-1]
        close, stamp = _num(last.get("close")), str(last.get("datetime") or "")
        if close is None or close <= 0 or len(stamp) < 10:
            continue
        out[sym] = {"close": close, "date": stamp[:10], "source_kind": "day_bar"}
    return out


def _tdx_fundamentals(client, pairs: Dict[str, str], price_by_sym: Dict[str, Any],
                      deadline: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """财务快照 → 市值 / PE / PB（缺失就留空，不猜）。

    单位：mootdx 的 parser 已把通达信原始值 ×10000，股本单位=股、金额单位=元。
    """
    out: Dict[str, Dict[str, Any]] = {}
    for code, sym in pairs.items():
        if _tdx_time_left(deadline) <= 0:
            break
        try:
            rows = _records(client.finance(symbol=code))
        except Exception:                                           # noqa: BLE001
            rows = []
        if not rows:
            continue
        row = rows[0]
        total_shares = _num(row.get("zongguben"), 0)
        float_shares = _num(row.get("liutongguben"), 0)
        net_profit, bvps = _num(row.get("jinglirun"), 2), _num(row.get("meigujingzichan"), 4)
        quote = price_by_sym.get(sym)
        price = _num(quote.get("price") if isinstance(quote, dict) else quote)
        eps = (net_profit / total_shares) if (net_profit and total_shares) else None
        out[sym] = {
            "updated_date": str(row.get("updated_date") or "") or None,
            "total_shares": total_shares, "float_shares": float_shares,
            "bvps": bvps, "net_profit": net_profit, "eps": round(eps, 6) if eps else None,
            "total_mv": round(price * total_shares, 2) if (price and total_shares) else None,
            "float_mv": round(price * float_shares, 2) if (price and float_shares) else None,
            "pe": round(price / eps, 4) if (price and eps and eps > 0) else None,
            "pb": round(price / bvps, 4) if (price and bvps and bvps > 0) else None,
        }
    return out


def _tdx_corporate_actions(client, pairs: Dict[str, str], date_str: str,
                           days: int = TDX_ACTION_DAYS,
                           deadline: Optional[float] = None) -> Dict[str, List[Dict[str, Any]]]:
    """近 N 天除权除息 / 送配股（用来解释跨日跳变，也作为 AI 特征）。"""
    try:
        cut = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    except ValueError:
        cut = date_str
    out: Dict[str, List[Dict[str, Any]]] = {}
    for code, sym in pairs.items():
        if _tdx_time_left(deadline) <= 0:
            break
        try:
            rows = _records(client.xdxr(symbol=code))
        except Exception:                                           # noqa: BLE001
            rows = []
        items = []
        for row in rows:
            try:
                stamp = f"{int(row.get('year')):04d}-{int(row.get('month')):02d}-{int(row.get('day')):02d}"
            except (TypeError, ValueError):
                continue
            if not (cut <= stamp <= date_str):
                continue
            items.append({"date": stamp, "category": row.get("category"),
                          "name": str(row.get("name") or ""),
                          "fenhong": _num(row.get("fenhong"), 4),
                          "songzhuangu": _num(row.get("songzhuangu"), 4),
                          "peigu": _num(row.get("peigu"), 4),
                          "peigujia": _num(row.get("peigujia"), 4)})
        if items:
            out[sym] = sorted(items, key=lambda item: item["date"])
    return out


def _tdx_from_client(client, pairs: Dict[str, str], label: str, enrich: bool,
                     date_str: str, deadline: Optional[float] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """用给定客户端取一轮数据；返回 (源结果, 附加数据)。

    取数顺序（2026-10-01 加固）：**先行情验活，后逐只明细**。
    ``quotes()`` 一次拿全部标的，既是数据也是「这台主站在不在服务」的验活；
    行情为空立刻返回 failed 交给下一台主站，绝不在一台半死的主站上逐只跑
    bars / finance / xdxr —— 那是 11 只标的几十次调用，每次都可能吃满 tdxpy 的
    重连阶梯，单站就能把作业拖到超时被取消。

    附加数据：eod_closes 每档都有；fundamentals / corporate_actions 只有 enrich=True 时才有。
    """
    started = time.time()
    try:
        quotes = _tdx_quotes(client, pairs, date_str)
    except Exception as exc:                                        # noqa: BLE001
        return _source_result("tdx", "failed", host=label, error=f"{type(exc).__name__}: {exc}",
                              elapsed_ms=(time.time() - started) * 1000), {}
    if not quotes:
        return _source_result("tdx", "failed", host=label, error="返回内容无有效行情（验活不通过）",
                              elapsed_ms=(time.time() - started) * 1000), {}
    eod_closes = _tdx_eod_closes(client, pairs, deadline)           # 验活通过才做收盘核对
    session_dates = {sym: str(item.get("date") or "") for sym, item in eod_closes.items()}
    quotes = _tdx_restamp(quotes, session_dates)                    # 交易日补全行情日期
    stamps = [q["quote_time"] for q in quotes.values() if q.get("quote_time")]
    result = _source_result("tdx", "ok", quotes=quotes, host=label,
                            quote_time=max(stamps) if stamps else None,
                            elapsed_ms=(time.time() - started) * 1000)
    extras: Dict[str, Any] = {"eod_closes": eod_closes}
    if enrich:
        extras["fundamentals"] = _tdx_fundamentals(client, pairs, quotes, deadline)
        extras["corporate_actions"] = _tdx_corporate_actions(client, pairs, date_str,
                                                             deadline=deadline)
    bits = []
    if extras["eod_closes"]:
        bits.append(f"收盘核对 {len(extras['eod_closes'])} 只")
    if extras.get("fundamentals"):
        bits.append(f"财务 {len(extras['fundamentals'])} 只")
    if extras.get("corporate_actions"):
        bits.append(f"除权除息 {sum(len(v) for v in extras['corporate_actions'].values())} 条")
    result["summary"] = " · ".join(bits) or "无附加数据"
    result.update(extras)
    return result, extras


def fetch_tdx(symbols: Sequence[str], http=None, timeout: int = DEFAULT_TIMEOUT, *,
              client: Optional[Any] = None, servers: Optional[Sequence[Tuple[str, int]]] = None,
              enrich: bool = False, slot: Optional[str] = None, date_str: Optional[str] = None,
              budget: Optional[float] = None, connector: Optional[Callable[..., Any]] = None,
              factory: Optional[Callable[..., Any]] = None, **_kw) -> Dict[str, Any]:
    """通达信行情源（沪深）：主站池逐个降级，且整条通道有墙钟预算。

    每档都附带日K收盘（与东财日K组成双源收盘核对）；enrich=True（默认只有 17:00 档）
    再抓财务快照与近 45 天除权除息。连不上 / 没装 mootdx 就明确降级，绝不编数。

    防卡死（2026-10-01）：
      · 每台主站先 TCP 预检（``TDX_PROBE_TIMEOUT``），连不上直接换站，不交给 mootdx；
      · 连上后先做一次 ``quotes()`` 验活，通过才做逐只的日K / 财务 / 除权除息；
      · 全程受 ``budget``（默认 ``TDX_BUDGET_SEC`` 90s，``OCTOPUS_DB_TDX_BUDGET`` 可覆盖）
        约束，到点立即收工并如实写失败原因 —— 单台死主站拖垮整个作业是绝不允许的。

    connector / factory 仅用于测试注入（真实场景走 socket + mootdx 主站池）。
    """
    pairs = {tdx_code(sym): sym for sym in symbols if tdx_code(sym)}
    if not pairs:
        return _source_result("tdx", "failed", error="无沪深标的（通达信标准行情不覆盖港美股）")
    when = date_str or _now().strftime("%Y-%m-%d")
    started = time.time()
    if client is not None:                                          # 测试注入 / 复用连接
        result, _extras = _tdx_from_client(client, pairs, "injected", enrich, when)
        return result
    servers = list(servers or _tdx_servers())
    if not servers:
        err = ("未安装 mootdx（pip install mootdx）" if not _tdx_installed()
               else "OCTOPUS_DB_TDX_SERVERS 为空且内置主站池为空")
        return _source_result("tdx", "unavailable", error=err)
    budget_sec = _tdx_budget(budget)
    deadline = time.monotonic() + budget_sec
    sock_timeout = min(int(timeout), TDX_SOCKET_TIMEOUT)
    errors: List[str] = []
    tried = 0
    for host, port in servers:
        if _tdx_time_left(deadline) <= 0:
            errors.append(f"总预算 {budget_sec}s 用尽，停止试连（已试 {tried} 台）")
            break
        tried += 1
        opened, err = _open_tdx_client(host, port, sock_timeout, connector=connector, factory=factory)
        if opened is None:
            errors.append(err)
            continue
        result, _extras = _tdx_from_client(opened, pairs, f"{host}:{port}", enrich, when, deadline)
        if result["status"] == "ok":
            result["elapsed_ms"] = int((time.time() - started) * 1000)
            return result
        errors.append(f"{host}:{port} {result.get('error') or '返回内容无效'}")
    last_err = "；".join(errors[-3:]) or "无可用主站"
    status = "unavailable" if "未安装 mootdx" in last_err else "failed"
    return _source_result("tdx", status, error=last_err, elapsed_ms=(time.time() - started) * 1000)


FETCHERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "yahoo": fetch_yahoo, "eastmoney": fetch_eastmoney, "tencent": fetch_tencent,
    "sina": fetch_sina, "tdx": fetch_tdx, "em_kline": fetch_em_kline,
}


def _normalize_quote(key: str, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """将各源（含兜底日K源 em_kline）统一归一化为单源行情字典。"""
    if not isinstance(raw, dict):
        return None
    if raw.get("price") is not None:
        return _quote(
            raw.get("price"), prev_close=raw.get("prev_close"), open_=raw.get("open"),
            high=raw.get("high"), low=raw.get("low"), volume=raw.get("volume"),
            amount=raw.get("amount"), quote_time=raw.get("quote_time"), name=raw.get("name") or "",
        )
    if key == "em_kline" and raw.get("close") is not None:
        day = str(raw.get("date") or "").strip()
        return _quote(
            raw.get("close"), prev_close=None, open_=raw.get("open"),
            high=raw.get("high"), low=raw.get("low"), volume=raw.get("volume"),
            amount=raw.get("amount"), quote_time=f"{day} 15:00:00" if day else None,
            name=raw.get("name") or "",
        )
    return None


def collect(symbols: Sequence[str], http, sources: Optional[Sequence[str]] = None,
            timeout: int = DEFAULT_TIMEOUT, **extra) -> Dict[str, Any]:
    """按「主源优先 → 备用源待命」顺序取数：仅对未覆盖标的依次启用下一备用源，不做多源并发比价。

    特例：收盘档 enrich=True 且含沪深标的时，通达信通道作为财务/除权除息的唯一单源运行，但行情仍只取主源。
    """
    keys = list(sources or SOURCE_ORDER)
    remaining = list(symbols)
    has_a_share = any(tdx_code(s) for s in symbols)
    out: Dict[str, Any] = {}
    for idx, key in enumerate(keys):
        role = "primary" if idx == 0 else "backup"
        need_enrich = (key == "tdx" and bool(extra.get("enrich")) and has_a_share)
        if not remaining and not need_enrich:
            out[key] = {**_source_result(key, "standby"), "role": role}
            continue
        target_syms = remaining if remaining else [s for s in symbols if tdx_code(s)]
        try:
            res = FETCHERS[key](target_syms, http, timeout, **extra)
        except Exception as exc:                                # noqa: BLE001
            res = _source_result(key, "failed", error=f"{type(exc).__name__}: {exc}")
        res["role"] = role
        out[key] = res
        if res.get("status") == "ok" and remaining:
            covered = {
                sym for sym, q in (res.get("quotes") or {}).items()
                if _normalize_quote(key, q) is not None
            }
            remaining = [s for s in remaining if s not in covered]
    return out


# ============================================================
# 价格工具与自我检查（无多源交叉验证）
# ============================================================
def _pct_diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return abs(a - b) / abs(b) * 100.0


def _slot_prices(slot_doc: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """提取一档快照的价格字典（兼容单源新结构与历史 cross_check 旧结构）。"""
    if not isinstance(slot_doc, dict):
        return {}
    ss = slot_doc.get("source_summary") or {}
    if isinstance(ss.get("prices"), dict) and ss["prices"]:
        return {k: float(v) for k, v in ss["prices"].items() if _num(v) is not None}
    cc = slot_doc.get("cross_check") or {}
    if isinstance(cc.get("median_prices"), dict) and cc["median_prices"]:
        return {k: float(v) for k, v in cc["median_prices"].items() if _num(v) is not None}
    out: Dict[str, float] = {}
    for sym, q in (slot_doc.get("quotes") or {}).items():
        if not isinstance(q, dict):
            continue
        p = _num(q.get("price") if q.get("price") is not None else (q.get("consensus") or {}).get("price"))
        if p is not None and p > 0:
            out[sym] = p
    return out


def _check(name: str, ok: bool, detail: str, *, warn_only: bool = False) -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "warn_only": bool(warn_only), "detail": detail}


def _explain_action(actions: Optional[Dict[str, List[Dict[str, Any]]]], sym: str,
                    date_str: str, days: int = 5) -> str:
    """跳变是不是除权除息造成的？是就给出「疑似除权除息」的说明（通达信通道提供）。"""
    items = (actions or {}).get(sym) or []
    if not items:
        return ""
    try:
        low = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    except ValueError:
        return ""
    recent = [it for it in items if low <= str(it.get("date") or "") <= date_str]
    if not recent:
        return ""
    item = recent[-1]
    return f"（疑似除权除息：{item.get('name') or item.get('category') or '除权除息'} {item['date']}）"


def self_check(slot_doc: Dict[str, Any], *, prev_slot: Optional[Dict[str, Any]] = None,
               prev_day: Optional[Dict[str, Any]] = None, trading_day: bool = True,
               corporate_actions: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """对一次落库做体检：结构 / 时段 / 主备源可用性 / 标的覆盖 / 数值 / 跳变 / 时效。

    corporate_actions —— 近 45 天除权除息；若跳变日正好有除权除息，
    该跳变会写明原因且不计分（正常的除权缺口不是数据错误）。
    """
    checks: List[Dict[str, Any]] = []
    alerts: List[str] = []
    explained = 0

    slot = slot_doc.get("slot")
    checks.append(_check("slot_valid", slot in SLOTS, f"时段 {slot} ∈ {list(SLOTS)}"))

    drift = None
    try:
        drift = abs((datetime.strptime(slot_doc["pulled_at"], "%Y-%m-%d %H:%M:%S")
                     - datetime.strptime(slot_doc["scheduled_at"], "%Y-%m-%d %H:%M:%S")).total_seconds()) / 60.0
    except (KeyError, ValueError, TypeError):
        pass
    checks.append(_check("schedule_window", drift is not None and drift <= SCHEDULE_TOL_MIN,
                         f"拉取时刻距计划 ±{drift:.0f} 分钟（容差 {SCHEDULE_TOL_MIN}）" if drift is not None
                         else "拉取时刻无法解析", warn_only=True))

    sources_meta = slot_doc.get("sources") or {}
    ok_sources = [k for k, s in sources_meta.items() if s.get("status") == "ok"]
    standby_sources = [k for k, s in sources_meta.items() if s.get("status") == "standby"]
    checks.append(_check(
        "source_available", len(ok_sources) >= MIN_SOURCES,
        f"启用源 {len(ok_sources)}（{', '.join(ok_sources) or '无'}）"
        + (f" · 备用待命 {len(standby_sources)}" if standby_sources else ""),
    ))

    quotes = slot_doc.get("quotes") or {}
    summary = slot_doc.get("source_summary") or slot_doc.get("cross_check") or {}
    total = int(summary.get("symbols_total") or len(quotes))
    ok_n = int(summary.get("symbols_ok") or len(quotes))
    cover = (ok_n / total) if total else 0.0
    checks.append(_check("symbol_coverage", cover >= MIN_SYMBOL_COVER,
                         f"标的覆盖 {ok_n}/{total}（{cover*100:.0f}%，下限 {MIN_SYMBOL_COVER*100:.0f}%）"))

    bad_numeric = []
    for sym, q in quotes.items():
        c = q.get("consensus") or {}
        price = q.get("price") if q.get("price") is not None else c.get("price")
        prev = q.get("prev_close") if q.get("prev_close") is not None else c.get("prev_close")
        pct = _pct(price, prev) if (price and prev) else None
        if price is None or price <= 0:
            bad_numeric.append(f"{sym} 价≤0")
        elif pct is not None and abs(pct) > 40:
            bad_numeric.append(f"{sym} 涨跌幅 {pct:.1f}%")
    checks.append(_check("numeric_sanity", not bad_numeric,
                         "全部价格 >0 且涨跌幅在容差内" if not bad_numeric else "；".join(bad_numeric[:5])))

    jump = None
    p_prev = _slot_prices(prev_slot)
    p_now = _slot_prices(slot_doc)
    if p_prev and p_now:
        worst = max(((sym, _pct_diff(p_now.get(sym), p_prev.get(sym))) for sym in p_now
                     if sym in p_prev and p_now.get(sym) and p_prev.get(sym)),
                    key=lambda x: (x[1] is None, x[1] or 0), default=(None, None))
        jump = worst[1]
        if jump is not None and jump > SLOT_JUMP_PCT:
            note = _explain_action(corporate_actions, str(worst[0]), str(slot_doc.get("date") or ""))
            alerts.append(f"跨时段跳变：{worst[0]} 较上一时段 {jump:.1f}%{note}")
            explained += 1 if note else 0
    checks.append(_check("slot_jump", jump is None or jump <= SLOT_JUMP_PCT,
                         f"同日内相邻时段最大价差 {jump:.2f}%" if jump is not None else "无可比时段"))

    if prev_day:
        prev_slots = sorted((prev_day.get("slots") or {}).keys())
        prev_prices: Dict[str, float] = {}
        for s in reversed(prev_slots):
            prev_prices = _slot_prices(prev_day["slots"][s])
            if prev_prices:
                break
        worst = max(((sym, _pct_diff(p_now.get(sym), prev_prices.get(sym)))
                     for sym in p_now if sym in prev_prices and prev_prices.get(sym)),
                    key=lambda x: (x[1] is None, x[1] or 0), default=(None, None))
        if worst[1] is not None and worst[1] > DAY_JUMP_PCT:
            note = _explain_action(corporate_actions, str(worst[0]), str(slot_doc.get("date") or ""))
            alerts.append(f"跨日跳变：{worst[0]} 较上一交易日收盘 {worst[1]:.1f}%{note}")
            explained += 1 if note else 0

    live = False
    target_date = str(slot_doc.get("date") or "")
    for _sym, q in quotes.items():
        if str(q.get("quote_time") or "").startswith(target_date) and target_date:
            live = True
            break
        for st in (q.get("consensus") or {}).get("by_source", {}).values():
            if str(st.get("quote_time") or "").startswith(target_date) and target_date:
                live = True
                break
        if live:
            break
    checks.append(_check("freshness", live or not trading_day,
                         "本时段存在当天行情" if live else
                         ("非交易日（休市）：沿用最近收盘，不计缺陷" if not trading_day
                          else "行情时间不是当天：可能休市或源延迟"), warn_only=True))

    penalty = sum(0 if c["ok"] or c["warn_only"] else 12 for c in checks)
    penalty += sum(4 for c in checks if not c["ok"] and c["warn_only"])
    penalty += 6 * max(0, len(alerts) - explained)       # 被除权除息解释的跳变不计分
    score = max(0, 100 - penalty)
    for c in checks:
        if not c["ok"] and not c["warn_only"]:
            alerts.append(f"{c['name']}：{c['detail']}")
        elif not c["ok"]:
            alerts.append(f"提示·{c['name']}：{c['detail']}")
    return {"score": score, "ok": all(c["ok"] for c in checks if not c["warn_only"]),
            "checks": checks, "alerts": alerts}


# ============================================================
# 落库（写文件 / 合并当天三档 / 原子替换 / 哈希）
# ============================================================
def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def db_path(date_compact: str, root: str = DB_ROOT) -> str:
    return os.path.join(root, f"{date_compact}.json")


def load_day(date_compact: str, root: str = DB_ROOT) -> Optional[Dict[str, Any]]:
    path = db_path(date_compact, root)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def load_days(root: str = DB_ROOT) -> List[Dict[str, Any]]:
    if not os.path.isdir(root):
        return []
    docs = []
    for name in sorted(os.listdir(root)):
        if re.fullmatch(r"\d{8}\.json", name):
            doc = load_day(name[:8], root)
            if doc:
                docs.append(doc)
    return docs


def latest_day(root: str = DB_ROOT) -> Optional[Dict[str, Any]]:
    docs = load_days(root)
    return docs[-1] if docs else None


def load_daily_bars(*, symbols: Optional[Sequence[str]] = None, root: str = DB_ROOT,
                    docs: Optional[Sequence[Dict[str, Any]]] = None,
                    now: Optional[datetime] = None) -> Dict[str, List[Dict[str, Any]]]:
    """只读重建已收盘日线，供 MACD 等研究使用；绝不把三档快照当成三根日 K。

    优先用 eod_close / eod_close_tdx 的实际行情日；指数另可用有收盘后报价时间的
    单源报价（兼容历史共识快照，历史冲突/分歧条目仍排除）。原采集时刻尚未收盘的日 K
    永远不采纳，即使现在已经收盘；同一行情日去重，不以文件名 / 抓取日为行情日期。
    个股的东财前复权与通达信未复权序列分组，选择最长一组，不混接价格口径。
    已知除权除息落在个股序列窗口内时不供数，交给免费源重取完整历史。
    """
    from octopus_quant import providers

    moment = _now(now)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=CST)
    wanted = set(symbols) if symbols is not None else None
    groups: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
    actions: Dict[str, set] = {}
    index_symbols = {code for _name, code, _mk in CORE_SYMBOLS[:9]} | {"000300.SS", "^HSCE"}

    def _moment(text):
        try:
            parsed = datetime.fromisoformat(str(text))
            return parsed.replace(tzinfo=CST) if parsed.tzinfo is None else parsed
        except (TypeError, ValueError):
            return None

    def _add(sym, bar, collected, source, basis, rank):
        if not isinstance(bar, dict):
            return
        day = str(bar.get("date") or "")[:10]
        close = _num(bar.get("close"), None)
        if close is None or close <= 0 or not providers.is_session_closed(sym, day, now=collected):
            return
        row = {"date": day, "close": close, "open": _num(bar.get("open")),
               "high": _num(bar.get("high")), "low": _num(bar.get("low")),
               "volume": _num(bar.get("volume")), "source": source, "price_basis": basis,
               "collected_at": collected.isoformat(), "_rank": rank}
        dates = groups.setdefault((sym, basis), {})
        previous = dates.get(day)
        if not previous or (rank, row["collected_at"]) >= (previous["_rank"], previous["collected_at"]):
            dates[day] = row

    for doc in (docs if docs is not None else load_days(root)):
        if not isinstance(doc, dict):
            continue
        slots = doc.get("slots") or {}
        if not isinstance(slots, dict):
            continue
        for slot_doc in slots.values():
            if not isinstance(slot_doc, dict):
                continue
            collected = _moment(slot_doc.get("pulled_at"))
            if collected is None or collected > moment:
                continue
            corporate_actions = slot_doc.get("corporate_actions") or {}
            if isinstance(corporate_actions, dict):
                for sym, entries in corporate_actions.items():
                    for entry in (entries if isinstance(entries, (list, tuple)) else []):
                        if isinstance(entry, dict) and entry.get("date"):
                            actions.setdefault(sym, set()).add(str(entry["date"])[:10])
            quotes = slot_doc.get("quotes") or {}
            if not isinstance(quotes, dict):
                continue
            for sym, quote in quotes.items():
                if (not isinstance(sym, str) or (wanted is not None and sym not in wanted)
                        or not isinstance(quote, dict)):
                    continue
                is_index = sym.startswith("^") or sym in index_symbols
                _add(sym, quote.get("eod_close"), collected, "市场库·东财日K",
                     "指数点位" if is_index else "东财前复权留存", 2)
                _add(sym, quote.get("eod_close_tdx"), collected, "市场库·通达信日K",
                     "指数点位" if is_index else "未复权", 1)
                cons = quote.get("consensus") if isinstance(quote.get("consensus"), dict) else {}
                spot_price = _num(quote.get("price") if quote.get("price") is not None else cons.get("price"), None)
                # 原始报价时间必须真的在收盘后；只用指数快照，不混入个股复权序列。
                stamp = _moment(quote.get("quote_time"))
                if (not is_index or spot_price is None or spot_price <= 0
                        or stamp is None or stamp > collected + timedelta(minutes=5)
                        or cons.get("verdict") in ("冲突", "分歧", "无数据")):
                    continue
                day = stamp.astimezone(providers.market_timezone(sym)).strftime("%Y-%m-%d")
                if providers.is_session_closed(sym, day, now=stamp):
                    src_tag = f"市场库·{quote.get('source') or '收盘快照'}"
                    _add(sym, {**quote, "date": day, "close": spot_price},
                         collected, src_tag, "指数点位", 0)

    result: Dict[str, List[Dict[str, Any]]] = {}
    for (sym, _basis), dates in groups.items():
        bars = [dates[d] for d in sorted(dates)]
        if any(bars[0]["date"] <= d <= bars[-1]["date"] for d in actions.get(sym, ())):
            continue
        current = result.get(sym) or []
        if (len(bars), bars[-1]["date"]) > (len(current), current[-1]["date"] if current else ""):
            result[sym] = [{k: v for k, v in bar.items() if k != "_rank"} for bar in bars]
    return result


def is_trading_day(date_str: str) -> bool:
    """粗判交易日：周一~周五。法定节假日由 self-check 的 freshness 项以「无当天行情」体现。"""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").weekday() < 5
    except ValueError:
        return True


def _slot_payload(slot_doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in slot_doc.items() if k != "integrity"}


def pull(slot: str = "auto", *, root: str = DB_ROOT, symbols: Optional[Sequence[str]] = None,
         http: Optional[Any] = None, sources: Optional[Sequence[str]] = None,
         now: Optional[datetime] = None, timeout: int = DEFAULT_TIMEOUT,
         dry_run: bool = False, verbose: bool = True, enrich: Optional[bool] = None,
         tdx_client: Optional[Any] = None) -> Dict[str, Any]:
    """拉一次快照：主源优先采集（失败切备用源）→ 自检 → 合并写进当天文件（以日期为名字）。

    enrich —— 当通达信通道被调用时，是否附带财务 / 除权除息（默认 auto：只在 17:00 收盘档抓）。
    tdx_client —— 测试注入的通达信客户端；生产走 mootdx 主站池。
    """
    log = (lambda msg: print(msg)) if verbose else (lambda msg: None)
    moment = _now(now)
    date_compact = moment.strftime("%Y%m%d")
    date_str = moment.strftime("%Y-%m-%d")
    slot = resolve_slot(slot, moment)
    if slot not in SLOTS:
        raise SystemExit(f"❌ 未知时段 {slot}，可选 {list(SLOTS)}")
    universe = list(symbols) if symbols else [code for _n, code, _m in symbol_universe()]
    names = {code: name for name, code, _m in symbol_universe()}
    http = http or Http(timeout=timeout)
    chosen = list(sources) if sources else list(SOURCE_ORDER)
    if os.environ.get("OCTOPUS_DB_TDX", "1").strip() == "0" and "tdx" in chosen:
        chosen.remove("tdx")                                   # 显式关闭通达信通道
    enrich = (slot == SLOTS[-1]) if enrich is None else bool(enrich)
    primary_key = chosen[0] if chosen else PRIMARY_SOURCE

    log(f"🗄️ 市场数据库 · 拉取 {date_str} {SLOT_LABELS[slot]}（{slot}）")
    log(f"   标的 {len(universe)} 只 · 主源 {primary_key} · 备用源 {max(0, len(chosen) - 1)} 路待命")
    source_results = collect(universe, http, sources=chosen, timeout=timeout,
                             enrich=enrich, slot=slot, date_str=date_str, client=tdx_client)
    ok = {k: s for k, s in source_results.items() if s["status"] == "ok"}
    for key, s in source_results.items():
        if s["status"] == "ok":
            extra = f" · {s['summary']}" if s.get("summary") else ""
            tag = "主源" if key == primary_key else "备用源启用"
            log(f"   ✅ [{tag}] {s['label']}：{s['symbols']} 只 · {s['elapsed_ms']/1000:.1f}s{extra}")
        elif s["status"] == "standby":
            log(f"   ⏸️ [备用待命] {s['label']}")
        elif s["status"] == "unavailable":
            log(f"   🚫 {s['label']}：跳过（{s['error']}）")
        else:
            log(f"   ⚠️ {s['label']}：{s['error']}")
    if not ok:
        log("❌ 主源与备用源均失败：按「绝不伪造」原则不写文件。")
        return {"status": "failed", "written": False, "date": date_str, "slot": slot,
                "sources": source_results}

    # ---- 单源定标（按主源 → 备用源顺序取首个有效行情，不做多源比价交叉验证）----
    tdx_closes = (source_results.get("tdx") or {}).get("eod_closes") or {}
    fundamentals = (source_results.get("tdx") or {}).get("fundamentals") or {}
    corporate_actions = (source_results.get("tdx") or {}).get("corporate_actions") or {}
    quotes: Dict[str, Dict[str, Any]] = {}
    prices_map: Dict[str, float] = {}
    primary_hits, backup_hits = 0, 0
    backup_used_set = []
    for sym in universe:
        picked_src, picked_q, raw_q = None, None, None
        for key in chosen:
            s = ok.get(key)
            if not s or sym not in s["quotes"]:
                continue
            raw_item = s["quotes"][sym]
            norm = _normalize_quote(key, raw_item)
            if norm is not None:
                picked_src, picked_q, raw_q = key, norm, raw_item
                break
        if picked_src is None or picked_q is None:
            continue
        is_backup = picked_src != primary_key
        if is_backup:
            backup_hits += 1
            if picked_src not in backup_used_set:
                backup_used_set.append(picked_src)
        else:
            primary_hits += 1
        entry: Dict[str, Any] = {
            "name": names.get(sym) or picked_q.get("name") or sym,
            "market": market_of(sym),
            "price": picked_q["price"],
            "prev_close": picked_q.get("prev_close"),
            "change_pct": _pct(picked_q["price"], picked_q.get("prev_close")),
            "open": picked_q.get("open"),
            "high": picked_q.get("high"),
            "low": picked_q.get("low"),
            "volume": picked_q.get("volume"),
            "amount": picked_q.get("amount"),
            "quote_time": picked_q.get("quote_time"),
            "source": picked_src,
            "source_label": SOURCES[picked_src]["label"],
            "source_role": "备用源" if is_backup else "主源",
            "is_backup": is_backup,
            "sources": [picked_src],
            "n_sources": 1,
        }
        if picked_src == "em_kline" and isinstance(raw_q, dict):
            entry["eod_close"] = raw_q
        if tdx_closes.get(sym):
            entry["eod_close_tdx"] = tdx_closes[sym]
        prices_map[sym] = picked_q["price"]
        quotes[sym] = entry

    standby_list = [k for k, s in source_results.items() if s.get("status") == "standby"]
    source_summary = {
        "mode": "single_with_backup",
        "primary_source": primary_key,
        "active_sources": list(ok),
        "backup_sources_used": backup_used_set,
        "standby_sources": standby_list,
        "sources_ok": len(ok),
        "sources_total": len(source_results),
        "symbols_total": len(universe),
        "symbols_ok": len(quotes),
        "primary_hit": primary_hits,
        "backup_hit": backup_hits,
        "prices": prices_map,
    }

    slot_doc: Dict[str, Any] = {
        "slot": slot, "label": SLOT_LABELS[slot], "date": date_str,
        "pulled_at": moment.strftime("%Y-%m-%d %H:%M:%S"),
        "scheduled_at": scheduled_at(date_str, slot),
        "trading_day": is_trading_day(date_str),
        "sources": {k: {kk: vv for kk, vv in s.items()
                        if kk not in ("quotes", "fundamentals", "corporate_actions", "eod_closes")}
                    for k, s in source_results.items()},
        "quotes": quotes, "source_summary": source_summary,
    }
    if fundamentals:
        slot_doc["fundamentals"] = fundamentals
    if corporate_actions:
        slot_doc["corporate_actions"] = corporate_actions

    # ---- 自检（与上一时段 / 上一交易日对比）----
    prev_doc = load_day(date_compact, root)
    prev_slots = sorted((prev_doc.get("slots") or {})) if prev_doc else []
    earlier = [s for s in prev_slots if SLOTS.index(s) < SLOTS.index(slot)]
    prev_slot = prev_doc["slots"][earlier[-1]] if earlier else None
    prev_days = [d for d in load_days(root) if d.get("date_compact", "") < date_compact]
    slot_doc["self_check"] = self_check(slot_doc, prev_slot=prev_slot,
                                        prev_day=prev_days[-1] if prev_days else None,
                                        trading_day=slot_doc["trading_day"],
                                        corporate_actions=corporate_actions)
    slot_doc["integrity"] = {"algo": "sha256", "hash": _sha256(_slot_payload(slot_doc))}

    log(f"   🔍 自检 {slot_doc['self_check']['score']}/100"
        + (f" · {len(slot_doc['self_check']['alerts'])} 条提示" if slot_doc["self_check"]["alerts"] else ""))

    if dry_run:
        return {"status": "dry-run", "written": False, "date": date_str, "slot": slot,
                "sources": source_results, "quotes": quotes, "self_check": slot_doc["self_check"]}

    # ---- 合并写文件（同一天三档依次进同一个文件）----
    doc = prev_doc or {"schema": SCHEMA, "db_date": date_str, "date_compact": date_compact,
                       "timezone": "Asia/Shanghai", "created_at": slot_doc["pulled_at"],
                       "slots": {}, "audit": {"pulls": [], "pull_count": 0}}
    overwrote = slot in (doc.get("slots") or {})
    doc["updated_at"] = slot_doc["pulled_at"]
    doc["slots"][slot] = slot_doc
    doc["slots"] = {s: doc["slots"][s] for s in SLOTS if s in doc["slots"]}
    audit = doc.setdefault("audit", {"pulls": [], "pull_count": 0})
    audit["pull_count"] = int(audit.get("pull_count") or 0) + 1
    audit["pulls"] = (audit.get("pulls") or []) + [{
        "slot": slot, "pulled_at": slot_doc["pulled_at"], "overwrote": overwrote,
        "sources_ok": len(ok), "symbols_ok": len(quotes),
        "score": slot_doc["self_check"]["score"],
    }]
    doc["ai"] = ai_summary(doc)
    doc["integrity"] = {"algo": "sha256", "hash": _sha256({**doc, "integrity": None})}

    os.makedirs(root, exist_ok=True)
    path = db_path(date_compact, root)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)
    log(f"   💾 已写入 {os.path.relpath(path, SCRIPT_DIR)}"
        f"（{len(doc['slots'])}/3 档 · {os.path.getsize(path)/1024:.1f} KB）")
    return {"status": "ok", "written": True, "path": path, "date": date_str, "slot": slot,
            "doc": doc, "sources": source_results, "self_check": slot_doc["self_check"]}


def ai_summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    """给库里的 AI 元信息（由当天已落库的档位实时计算，随时可 rebuild）。"""
    rows, meta = build_dataset(root=None, docs=[doc])
    return {"row_count": len(rows), "symbols": meta["symbols"], "slots_present": meta["slots"],
            "feature_names": meta["feature_names"], "label_names": meta["label_names"]}


# ============================================================
# 校验 / 复核
# ============================================================
def verify_integrity(doc: Dict[str, Any]) -> Dict[str, Any]:
    """校验文件级 + 时段级哈希（发现被改写 / 手工编辑过的库文件）。"""
    out = {"ok": True, "problems": []}
    stored = (doc.get("integrity") or {}).get("hash")
    actual = _sha256({**doc, "integrity": None})
    if stored and stored != actual:
        out["ok"] = False
        out["problems"].append("day 级哈希不匹配（文件被改写）")
    for slot, slot_doc in (doc.get("slots") or {}).items():
        s_stored = (slot_doc.get("integrity") or {}).get("hash")
        if s_stored and s_stored != _sha256(_slot_payload(slot_doc)):
            out["ok"] = False
            out["problems"].append(f"{slot} 档哈希不匹配")
    if not stored and not (doc.get("slots") or {}):
        out["ok"] = False
        out["problems"].append("空文件")
    return out


def verify(root: str = DB_ROOT, date_compact: Optional[str] = None, all_days: bool = False,
           strict: bool = False, verbose: bool = True) -> Dict[str, Any]:
    docs = load_days(root) if (all_days or not date_compact) else [load_day(date_compact, root)]
    docs = [d for d in docs if d]
    if not docs:
        msg = f"{date_compact} 无库文件（先跑 pull）" if date_compact else "暂无库文件（先跑 pull）"
        if verbose:
            print(f"🗄️ 市场数据库：{msg}")
        return {"ok": False, "days": 0, "problems": [msg], "alerts": []}
    problems, alerts, per_day = [], [], []
    for doc in docs:
        integ = verify_integrity(doc)
        problems += [f"{doc.get('db_date')}：{p}" for p in integ["problems"]]
        missing = [s for s in SLOTS if s not in (doc.get("slots") or {})]
        if missing:
            alerts.append(f"{doc.get('db_date')}：缺 {len(missing)} 档（{', '.join(missing)}）")
        day_alerts, scores, sources_n, symbols_n, backup_n = [], [], [], [], []
        for slot, slot_doc in (doc.get("slots") or {}).items():
            sc = slot_doc.get("self_check") or {}
            scores.append(int(sc.get("score") or 0))
            for a in sc.get("alerts") or []:
                day_alerts.append(f"{slot} {a}")
                alerts.append(f"{doc.get('db_date')} {slot}：{a}")
            summary = slot_doc.get("source_summary") or slot_doc.get("cross_check") or {}
            sources_n.append(int(summary.get("sources_ok") or 0))
            symbols_n.append(int(summary.get("symbols_ok") or 0))
            backup_n.append(int(summary.get("backup_hit") or 0))
        per_day.append({
            "date": doc.get("db_date"), "slots": len(doc.get("slots") or {}),
            "sources_avg": round(sum(sources_n) / len(sources_n), 2) if sources_n else 0,
            "symbols_max": max(symbols_n) if symbols_n else 0,
            "backup_hits": sum(backup_n),
            "score_avg": round(sum(scores) / len(scores), 1) if scores else 0,
            "alerts": day_alerts, "integrity_ok": integ["ok"],
        })
    ok = not problems and (not strict or not alerts)
    if verbose:
        print(f"🗄️ 市场数据库复核 · {len(docs)} 个日期文件")
        for row in per_day:
            flag = "✅" if row["integrity_ok"] and row["score_avg"] >= 60 else "⚠️"
            bk_txt = f" · 备用兜底 {row['backup_hits']} 次" if row["backup_hits"] else ""
            print(f"   {flag} {row['date']}：{row['slots']}/3 档 · 启用源均 {row['sources_avg']}"
                  f" · 标的 {row['symbols_max']}{bk_txt} · 自检均分 {row['score_avg']}")
            for a in row["alerts"]:
                print(f"      · {a}")
        for p in problems:
            print(f"   ❌ {p}")
        print("   ✅ 全部通过" if ok else "   ⚠️ 存在缺陷（见上）")
    return {"ok": ok, "days": len(docs), "problems": problems, "alerts": alerts, "per_day": per_day}


# ============================================================
# AI 基础数据：特征 / 标签数据集 + 给分析用的上下文
# ============================================================
def _timeline(docs: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """按标的重建时间线：{代码: [ {ts, date, slot, price, …} ]}（先排序，供因果特征使用）。

    兼容单源新结构（直接读 q.price / q.source_role）与历史旧结构（读 q.consensus）。
    以 (日期, 档位, 标的) 去重：同一天的文件可能被多次读到（同一档被重拉覆盖），
    保留**后出现**的版本（docs 按日期排序，同日多份时后一份是最新快照）。
    """
    series: Dict[str, List[Dict[str, Any]]] = {}
    seen: Dict[Tuple[str, str, str], int] = {}
    for doc in sorted(docs, key=lambda d: str(d.get("date_compact") or "")):
        date_str = doc.get("db_date") or ""
        for slot in SLOTS:
            slot_doc = (doc.get("slots") or {}).get(slot)
            if not slot_doc:
                continue
            ts = slot_doc.get("pulled_at") or f"{date_str} 00:00:00"
            for sym, q in (slot_doc.get("quotes") or {}).items():
                cons = q.get("consensus") or {}
                price = _num(q.get("price") if q.get("price") is not None else cons.get("price"))
                if price is None:
                    continue
                prev_close = _num(q.get("prev_close") if q.get("prev_close") is not None else cons.get("prev_close"))
                n_src = int(q.get("n_sources") or cons.get("n_agree") or 1)
                verdict = q.get("source_role") or cons.get("verdict") or "主源"
                key = (date_str, slot, sym)
                row = {
                    "ts": ts, "date": date_str, "slot": slot, "price": price,
                    "prev_close": prev_close, "change_pct": q.get("change_pct"),
                    "spread_pct": cons.get("spread_pct"), "n_agree": n_src,
                    "confidence": cons.get("confidence", CONF_SINGLE), "name": q.get("name"), "market": q.get("market"),
                    "volume": q.get("volume"), "amount": q.get("amount"), "high": q.get("high"),
                    "low": q.get("low"), "open": q.get("open"),
                    "lagged": cons.get("lagged") or [], "verdict": verdict,
                    "source": q.get("source") or (q.get("sources") or [None])[0],
                    "is_backup": bool(q.get("is_backup")),
                    "day": doc.get("date_compact"),
                    "fund": (slot_doc.get("fundamentals") or {}).get(sym),
                    "actions": (slot_doc.get("corporate_actions") or {}).get(sym) or [],
                }
                idx = seen.get(key)
                if idx is None:
                    seen[key] = len(series.setdefault(sym, []))
                    series[sym].append(row)
                else:                                    # 同一 (日期, 档位, 标的) 只留最新版本
                    series[sym][idx] = row
    for sym in series:
        series[sym].sort(key=lambda r: r["ts"])
    return series


FEATURE_NAMES = ["price", "change_pct", "prev_close", "open", "high", "low", "volume", "amount",
                 "spread_pct", "n_sources", "confidence", "n_lagged", "slot_index",
                 "ret_prev_slot", "ret_day_open", "ret_1d", "ret_5d", "vol_5d",
                 # 通达信通道（2026-10-01）：财务与除权除息 —— 全部按「当时已知」前向填充
                 "pe", "pb", "total_mv", "float_mv", "days_since_action"]
LABEL_NAMES = ["next_slot_ret", "eod_ret", "next_day_eod_ret"]


def build_dataset(*, root: Optional[str] = DB_ROOT, docs: Optional[Sequence[Dict[str, Any]]] = None,
                  symbols: Optional[Sequence[str]] = None,
                  start: Optional[str] = None, end: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """把库拍平成 AI 数据集（特征只用当次及之前；标签只用之后 —— 无未来函数）。"""
    docs = list(docs) if docs is not None else load_days(root or DB_ROOT)
    docs = [d for d in docs
            if (not start or str(d.get("db_date") or "") >= start)
            and (not end or str(d.get("db_date") or "") <= end)]
    series = _timeline(docs)
    if symbols:
        keep = set(symbols)
        series = {k: v for k, v in series.items() if k in keep}

    eod_by_day: Dict[str, Dict[str, float]] = {}
    for sym, rows in series.items():
        for row in rows:
            if row["slot"] == SLOTS[-1]:
                eod_by_day.setdefault(row["date"], {})[sym] = row["price"]
    day_order = sorted(eod_by_day)

    def _eod_before(date_str: str, back: int, sym: str) -> Optional[float]:
        prev = [d for d in day_order if d < date_str]
        if len(prev) < back:
            return None
        return eod_by_day[prev[-back]].get(sym)

    rows_out: List[Dict[str, Any]] = []
    for sym, rows in sorted(series.items()):
        fund: Optional[Dict[str, Any]] = None       # 最近一次「当时已知」的财务快照
        action_dates: List[str] = []                # 当时已知的除权除息日期
        for idx, row in enumerate(rows):
            if row.get("fund"):
                fund = row["fund"]
            for item in row.get("actions") or []:
                stamp = str(item.get("date") or "")
                if stamp and stamp not in action_dates and stamp <= row["date"]:
                    action_dates.append(stamp)
            day_rows = [r for r in rows if r["date"] == row["date"] and r["ts"] <= row["ts"]]
            first_today = day_rows[0]["price"] if day_rows else None
            prev_slot = day_rows[-2]["price"] if len(day_rows) >= 2 else None
            eod_hist = [_eod_before(row["date"], k, sym) for k in (1, 2, 3, 4, 5, 6)]
            rets = []
            prev_eod = _eod_before(row["date"], 1, sym)
            for j in range(5):
                a, b = eod_hist[j], eod_hist[j + 1]
                if a and b:
                    rets.append(a / b - 1.0)
            later = [r for r in rows if r["ts"] > row["ts"]]
            next_slot = next((r for r in later if r["date"] == row["date"]), None)
            eod_today = next((r for r in later if r["date"] == row["date"] and r["slot"] == SLOTS[-1]), None)
            next_day_eod = None
            nd = [d for d in day_order if d > row["date"]]
            if nd:
                next_day_eod = eod_by_day[nd[0]].get(sym)

            def _ret(target: Optional[float]) -> Optional[float]:
                if not target or not row["price"]:
                    return None
                return round(target / row["price"] - 1.0, 6)

            rows_out.append({
                "date": row["date"], "slot": row["slot"], "ts": row["ts"], "symbol": sym,
                "name": row.get("name"), "market": row.get("market"),
                "features": {
                    "price": row["price"], "change_pct": row.get("change_pct"),
                    "prev_close": (prev_eod or row.get("prev_close")),
                    "open": row.get("open"), "high": row.get("high"), "low": row.get("low"),
                    "volume": row.get("volume"), "amount": row.get("amount"),
                    "spread_pct": row.get("spread_pct"), "n_sources": row.get("n_agree"),
                    "confidence": row.get("confidence"), "n_lagged": len(row.get("lagged") or []),
                    "slot_index": SLOTS.index(row["slot"]),
                    "ret_prev_slot": (round(row["price"] / prev_slot - 1.0, 6)
                                      if prev_slot else None),
                    "ret_day_open": (round(row["price"] / first_today - 1.0, 6)
                                     if first_today else None),
                    "ret_1d": _ret(prev_eod),
                    "ret_5d": (round(row["price"] / eod_hist[4] - 1.0, 6) if eod_hist[4] else None),
                    "vol_5d": (round(statistics.pstdev(rets), 6) if len(rets) >= 2 else None),
                    "pe": (fund or {}).get("pe"), "pb": (fund or {}).get("pb"),
                    "total_mv": (fund or {}).get("total_mv"), "float_mv": (fund or {}).get("float_mv"),
                    "days_since_action": (
                        (datetime.strptime(row["date"], "%Y-%m-%d")
                         - datetime.strptime(max(action_dates), "%Y-%m-%d")).days
                        if action_dates else None),
                },
                "labels": {
                    "next_slot_ret": _ret(next_slot["price"] if next_slot else None),
                    "eod_ret": _ret(eod_today["price"] if eod_today else None),
                    "next_day_eod_ret": _ret(next_day_eod),
                },
                "quality": {"verdict": row.get("verdict"), "source": row.get("source"),
                            "is_backup": bool(row.get("is_backup")),
                            "lagged": row.get("lagged") or [],
                            "consensus": bool(row.get("price") is not None)},
            })
    meta = {
        "rows": len(rows_out), "symbols": len(series), "slots": sorted({r["slot"] for r in rows_out}),
        "dates": sorted({r["date"] for r in rows_out}),
        "feature_names": FEATURE_NAMES, "label_names": LABEL_NAMES,
        "built_at": _now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return rows_out, meta


def export_dataset(out_path: str, *, fmt: str = "jsonl", root: str = DB_ROOT,
                   start: Optional[str] = None, end: Optional[str] = None,
                   symbols: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    rows, meta = build_dataset(root=root, start=start, end=end, symbols=symbols)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    if fmt == "csv":
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["date", "slot", "ts", "symbol", "name", "market"]
                            + [f"f_{n}" for n in FEATURE_NAMES]
                            + [f"y_{n}" for n in LABEL_NAMES]
                            + ["verdict", "lagged", "consensus"])
            for r in rows:
                writer.writerow([r["date"], r["slot"], r["ts"], r["symbol"], r["name"], r["market"]]
                                + [r["features"].get(n) for n in FEATURE_NAMES]
                                + [r["labels"].get(n) for n in LABEL_NAMES]
                                + [r["quality"]["verdict"], "|".join(r["quality"]["lagged"]),
                                   int(r["quality"]["consensus"])])
    else:
        with open(out_path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"path": out_path, "format": fmt, "rows": len(rows), "meta": meta}


def _latest_fundamentals(docs: Sequence[Dict[str, Any]], sym: str,
                         lookback: int = 30) -> Optional[Dict[str, Any]]:
    """最近一次「已落库」的财务快照（从最新日期往前找，最多回看 lookback 天）。"""
    for doc in reversed(list(docs)[-lookback:]):
        slots = doc.get("slots") or {}
        for key in sorted(slots, reverse=True):
            fund = (slots[key].get("fundamentals") or {}).get(sym)
            if fund:
                return fund
    return None


def _recent_actions(docs: Sequence[Dict[str, Any]], sym: str,
                    lookback: int = 5) -> List[Dict[str, Any]]:
    """最近几档里记录过的除权除息（跨日期文件回看，最多 lookback 档）。"""
    out: List[Dict[str, Any]] = []
    seen = set()
    for doc in reversed(list(docs)[-lookback:]):
        slots = doc.get("slots") or {}
        for key in sorted(slots, reverse=True):
            for item in ((slots[key].get("corporate_actions") or {}).get(sym) or []):
                stamp = str(item.get("date") or "")
                if stamp and stamp not in seen:
                    seen.add(stamp)
                    out.append(item)
    return sorted(out, key=lambda item: str(item.get("date")), reverse=True)


def ai_context(date_compact: Optional[str] = None, *, root: str = DB_ROOT,
               symbols: Optional[Sequence[str]] = None,
               max_age_hours: int = 18, now: Optional[datetime] = None) -> Dict[str, Any]:
    """给 AI 分析 / 预测的紧凑上下文：最近一次单源行情（含主备来源）+ 新鲜度 + 质量标记。

    只读库文件，不联网；没有任何可用档位时返回空上下文（调用方自行降级）。
    """
    docs = load_days(root)
    if not docs:
        return {"available": False, "reason": "库为空"}
    if date_compact:
        docs = [d for d in docs if d.get("date_compact") == date_compact]
    if not docs:
        return {"available": False, "reason": "指定日期无库文件"}
    doc = docs[-1]
    slots = doc.get("slots") or {}
    slot_key = sorted(slots)[-1] if slots else None
    slot = slots.get(slot_key) or {}
    age_h = None
    try:
        age_h = round((_now(now) - datetime.strptime(slot["pulled_at"], "%Y-%m-%d %H:%M:%S")
                       .replace(tzinfo=CST)).total_seconds() / 3600, 2)
    except (KeyError, ValueError, TypeError):
        pass
    keep = set(symbols) if symbols else None
    quotes = {}
    for sym, q in (slot.get("quotes") or {}).items():
        if keep and sym not in keep:
            continue
        cons = q.get("consensus") or {}
        price = q.get("price") if q.get("price") is not None else cons.get("price")
        prev_close = q.get("prev_close") if q.get("prev_close") is not None else cons.get("prev_close")
        fund = _latest_fundamentals(docs, sym)
        actions = _recent_actions(docs, sym)
        quotes[sym] = {
            "name": q.get("name"), "market": q.get("market"),
            "price": price, "change_pct": q.get("change_pct"),
            "prev_close": prev_close,
            "source": q.get("source") or (q.get("sources") or [None])[0],
            "source_role": q.get("source_role") or ("历史共识" if cons else "主源"),
            "is_backup": bool(q.get("is_backup")),
            "fundamentals": fund, "recent_actions": actions,
        }
    summary = slot.get("source_summary") or slot.get("cross_check") or {}
    return {
        "available": bool(quotes), "db_date": doc.get("db_date"), "slot": slot_key,
        "pulled_at": slot.get("pulled_at"), "age_hours": age_h,
        "stale": bool(age_h is not None and age_h > max_age_hours),
        "primary_source": summary.get("primary_source", PRIMARY_SOURCE),
        "backup_sources_used": summary.get("backup_sources_used") or [],
        "sources_ok": summary.get("sources_ok"),
        "self_check_score": (slot.get("self_check") or {}).get("score"),
        "alerts": (slot.get("self_check") or {}).get("alerts") or [],
        "quotes": quotes,
    }


# ============================================================
# CLI
# ============================================================
def _print_stats(root: str = DB_ROOT, days: int = 7) -> int:
    docs = load_days(root)[-days:]
    if not docs:
        print("🗄️ 市场数据库：暂无库文件")
        return 0
    print(f"🗄️ 市场数据库 · 最近 {len(docs)} 个日期")
    for doc in docs:
        slots = doc.get("slots") or {}
        scores = [int((s.get("self_check") or {}).get("score") or 0) for s in slots.values()]
        summaries = [(s.get("source_summary") or s.get("cross_check") or {}) for s in slots.values()]
        src = [int(sm.get("sources_ok") or 0) for sm in summaries]
        sym = [int(sm.get("symbols_ok") or 0) for sm in summaries]
        backups = sum(int(sm.get("backup_hit") or 0) for sm in summaries)
        bk_note = f" · 备用兜底 {backups}" if backups else ""
        print(f"   {doc.get('db_date')}：{len(slots)}/3 档 · 启用源 {max(src) if src else 0}"
              f" · 标的 {max(sym) if sym else 0}{bk_note}"
              f" · 自检均分 {(sum(scores)/len(scores) if scores else 0):.0f}")
    return 0


def prune(root: str = DB_ROOT, keep_days: int = 90, *, dry_run: bool = False,
          verbose: bool = True) -> Dict[str, Any]:
    """保留最近 N 天的日期文件（更早的删除）。删前请先 export 出 AI 数据集。"""
    docs = load_days(root)
    if keep_days <= 0 or len(docs) <= keep_days:
        if verbose:
            print(f"🗄️ 无需清理：现有 {len(docs)} 个日期文件 ≤ 保留 {keep_days} 天")
        return {"removed": [], "kept": len(docs)}
    keep = {d.get("date_compact") for d in docs[-keep_days:]}
    removed = []
    for doc in docs:
        dc = doc.get("date_compact")
        if dc in keep:
            continue
        path = db_path(dc, root)
        removed.append(dc)
        if not dry_run and os.path.isfile(path):
            os.remove(path)
    if verbose:
        print(f"🗄️ {'预演：' if dry_run else ''}清理 {len(removed)} 个历史日期文件"
              f"（保留最近 {keep_days} 天：{min(keep)} ~ {max(keep)}）")
    return {"removed": removed, "kept": len(keep)}


def main(argv: Optional[Sequence[str]] = None, *, http: Optional[Any] = None,
         root: str = DB_ROOT, now: Optional[datetime] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="market_db", add_help=True,
        description="🗄️ 市场数据库（隐藏功能）：每天 3 次单源快照落库（备用源待命兜底）+ 自检，供 AI 分析 / 预测使用")
    sub = parser.add_subparsers(dest="cmd")

    p_pull = sub.add_parser("pull", help="拉一次快照并写进当天文件（以日期为名字）")
    p_pull.add_argument("--slot", default="auto", choices=["auto", *SLOTS], help="时段（默认按北京时间就近匹配）")
    p_pull.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p_pull.add_argument("--sources", default="", help="指定主备源顺序（逗号分隔），默认 yahoo 主源 + 备用源待命")
    p_pull.add_argument("--symbols", default="", help="只取指定代码（逗号分隔），默认全部标的池")
    p_pull.add_argument("--dry-run", action="store_true", help="只采集与自检，不写文件")
    p_pull.add_argument("--no-enrich", action="store_true",
                        help="不抓通达信财务 / 除权除息（默认只在 17:00 收盘档抓）")
    p_pull.add_argument("--no-tdx", action="store_true", help="跳过通达信通道（也可用 OCTOPUS_DB_TDX=0）")

    p_verify = sub.add_parser("verify", help="复核库文件（哈希 / 自检 / 覆盖）")
    p_verify.add_argument("--date", default="")
    p_verify.add_argument("--all", action="store_true")
    p_verify.add_argument("--strict", action="store_true", help="任何提示都算失败（退出码 1）")

    p_export = sub.add_parser("export", help="导出 AI 数据集（特征 + 标签）")
    p_export.add_argument("--out", required=True)
    p_export.add_argument("--format", default="jsonl", choices=["jsonl", "csv"])
    p_export.add_argument("--start", default="")
    p_export.add_argument("--end", default="")
    p_export.add_argument("--symbols", default="")

    p_stats = sub.add_parser("stats", help="看最近几天的覆盖与自检得分")
    p_stats.add_argument("--days", type=int, default=7)

    p_prune = sub.add_parser("prune", help="保留最近 N 天的库文件（删前先 export 数据集）")
    p_prune.add_argument("--keep-days", type=int, default=90)
    p_prune.add_argument("--dry-run", action="store_true")

    p_ctx = sub.add_parser("ai-context", help="打印给 AI 分析用的紧凑上下文（JSON）")
    p_ctx.add_argument("--date", default="")
    p_ctx.add_argument("--symbols", default="")

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "pull":
        if args.no_tdx:
            os.environ["OCTOPUS_DB_TDX"] = "0"                  # 只影响本次进程
        result = pull(args.slot, root=root, http=http, timeout=args.timeout,
                      sources=[s for s in args.sources.split(",") if s] or None,
                      symbols=[s for s in args.symbols.split(",") if s] or None,
                      dry_run=args.dry_run, now=now,
                      enrich=False if args.no_enrich else None)
        return 0 if result["status"] in ("ok", "dry-run") else 1

    if args.cmd == "verify":
        return 0 if verify(root, date_compact=args.date or None, all_days=args.all,
                           strict=args.strict)["ok"] else 1

    if args.cmd == "export":
        info = export_dataset(args.out, fmt=args.format, root=root,
                              start=args.start or None, end=args.end or None,
                              symbols=[s for s in args.symbols.split(",") if s] or None)
        print(f"🧠 已导出 {info['rows']} 行 → {args.out}（{args.format}）")
        return 0

    if args.cmd == "stats":
        return _print_stats(root, args.days)

    if args.cmd == "prune":
        prune(root, args.keep_days, dry_run=args.dry_run)
        return 0

    if args.cmd == "ai-context":
        ctx = ai_context(args.date or None, root=root,
                         symbols=[s for s in args.symbols.split(",") if s] or None)
        print(json.dumps(ctx, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
