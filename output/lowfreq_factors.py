#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""【策略】低频五因子选股（2026-10-28 新增）

用户口径（五个低频小因子，港股落地）：

  1. 小市值      全市场按市值从小到大排；计算 f = -ln(总市值)。
                 **市值不是越小越好**：一家上市公司的价值 = 基本面价值 + 壳价值，
                 所以要先把壳价值从市值里剥掉，再对小市值排序（见 SHELL_FLOOR）。
  2. 短期反转    全市场按最近 21 个交易日累计收益排序，跌得多的可能涨；
                 计算 = 最近 21 个交易日 log 收益和。
                 本栏的核心用法**不是构建组合，而是当一面镜子**：买在无人问津处、
                 卖在人声鼎沸时（见「因子镜子」一节）。
  3. 动量        经典 12-1 动量：ln(P[-22] / P[-251])，过去 250 个交易日剔除最近 21 个交易日。
  4. 换手率      最近 3 个月日换手率均值；换手率 = 当日成交股数 / 流通股本。
  5. 价值 EP     EP = 净利润 / 总市值 = 1/PE；三个配套动作：
                 ① 剔除市值最小的；② 同行业内部比较（不做全市场比较）；③ 剔除亏损股单独看。

港股推荐 20 只：五因子横截面分位（0–100，方向已统一成「越大越好」）加权合成，
硬门槛（纯壳 / 流动性）与缺失项规则见下；用户要求「港股推荐 20 个」，默认 TOP_N=20。

设计约束（与日报其它量化栏目同口径）：
  · 唯一的联网层是 providers（东财 clist / 日线 + Yahoo 日线备用），本模块不新增联网口；
  · 取不到就如实标暂缺，绝不补造行情数字；只有显式 allow_synthetic（OCTOPUS_LOWFREQ_DEMO=1）
    才用确定性合成序列做**版面演示**，并在结果与页面上点名「演示序列」；
  · 内部衍生计算（读已收盘日线），不计入「当天源」检验；
  · 渲染只用 kit 原语（table / kv / sub / note），五种主题都能出；
  · 规则合成、可复现，不是投资建议，也不构成对未来收益的承诺。
"""
from __future__ import annotations

import hashlib
import math
import os
import time
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))

SECTION_TITLE = "【策略】低频五因子选股"
KICKER = "LOWFREQ FACTORS"
SOURCE_NAME = "低频小因子量化策略"
SOURCE_LABEL = "东方财富港股快照 + 日线（Yahoo 备用）· 五因子横截面排序"

# ------------------------------------------------------------------
# 默认参数（页面「口径」行会如实列出本次实际生效的值）
# ------------------------------------------------------------------
DEFAULT_UNIVERSE = 320          # 按总市值从大到小取前 N 只建立计算池（控制日线请求量）
DEFAULT_TOP_N = 20              # 用户要求：港股推荐 20 个
DEFAULT_SHELL_FLOOR = 3e8       # 壳价值下限（港元）：低于它的市值基本是「上市资格」的价钱
DEFAULT_MIN_AMOUNT = 1e7        # 21 日日均成交额下限（港元），流动性门槛
DEFAULT_EP_MIN_CAP = 2e9        # EP 只在市值 ≥ 20 亿港元的票里比较（剔除市值最小的）
DEFAULT_MIN_INDUSTRY_PEERS = 5  # 同行业可比公司数；不足则退回全市场分位并标注
DEFAULT_WORKERS = 6
MIN_BARS = 22                   # 反转最少需要的日线根数
MOMENTUM_LOOKBACK = 250
MOMENTUM_SKIP = 21
REVERSAL_WINDOW = 21
TURNOVER_WINDOW = 63            # 约 3 个月交易日
# 日线请求的重试阶梯：(并发, 超时秒, 区间)。第一轮并发抓，失败的在更低并发下重试，
# 最后一轮退到 1 年日线（够算反转与换手；动量会因样本不足留空，不硬凑）。
BARS_RETRY_LEVELS = ((6, 12, "2y"), (2, 20, "2y"), (1, 20, "1y"))
BARS_BATCH_SIZE = 40            # 单批请求数：再大就容易触发镜像限流
BARS_BATCH_PAUSE = 0.8          # 批间停顿（秒）
# 名单发布门槛：可排序只数太少，或日线覆盖不到合格池的 60%，就**不出名单**。
# 原因很实在——日线抓取失败集中在某一端时，横截面会系统性偏向另一端（例如只剩大票，
# 于是把 1500 亿的大票标成「市值小」）。宁可缺席，也不出版一张口径错位的名单。
MIN_PUBLISH_RANKED = 30
MIN_PUBLISH_SHARE = 0.60

MIN_FACTORS = 3                 # 综合分至少要有 3 个因子可比
MIN_WEIGHT_SHARE = 0.60         # 且可用因子权重合计不低于 60%

# 权重（用户未指定，默认等权；可用环境变量覆盖）
FACTOR_META = {
    "size": {
        "name": "小市值",
        "formula": "f = -ln(总市值 - 壳价值下限)",
        "direction": "市值越小越好（先剥壳价值）",
        "higher_is_better": True,
    },
    "reversal": {
        "name": "短期反转",
        "formula": "Σ ln(1+r)，最近 21 个交易日",
        "direction": "跌得越多越靠前（当镜子，不当买入理由）",
        "higher_is_better": False,
    },
    "momentum": {
        "name": "动量 12-1",
        "formula": "ln(P[-22] / P[-251])",
        "direction": "剔除最近 21 日后的过去 250 日涨幅越大越好",
        "higher_is_better": True,
    },
    "turnover": {
        "name": "换手率",
        "formula": "近 63 日「成交股数 / 流通股本」均值",
        "direction": "越冷清越好（低换手溢价）",
        "higher_is_better": False,
    },
    "ep": {
        "name": "价值 EP",
        "formula": "EP = 净利润 / 总市值 = 1 / PE",
        "direction": "同行业内部越高越好；亏损股与微市值股不参与",
        "higher_is_better": True,
    },
}
FACTOR_ORDER = ("size", "reversal", "momentum", "turnover", "ep")
DEFAULT_WEIGHTS = {key: 0.2 for key in FACTOR_ORDER}

# 行业兜底关键词表：东财 f100 行业字段对港股常为空，空值时按公司名做粗分组；
# 粗分组只用于「同行业内部比较 EP」，不参与板块强弱判断。
_INDUSTRY_RULES = (
    ("银行", ("银行",)),
    ("保险", ("保险", "人寿", "财险", "友邦")),
    ("券商与交易所", ("证券", "券商", "香港交易所", "港交所")),
    ("地产与物业", ("地产", "置业", "物业", "房托", "REIT")),
    ("半导体与电子", ("半导体", "中芯", "华虹", "电子", "芯片", "晶圆")),
    ("软件与互联网", ("软件", "科技", "云", "网络", "集团-W", "在线", "信息",
                     "腾讯", "阿里", "百度", "小米", "美团", "京东", "网易", "快手",
                     "哔哩哔哩", "金蝶", "联想", "商汤", "优必选", "金山", "携程", "舜宇")),
    ("医药与生物", ("药", "生物", "医疗", "健康", "医")),
    ("能源与资源", ("石油", "石化", "煤", "能源", "矿业", "黄金", "铝", "铜", "钢铁")),
    ("公用与基建", ("电力", "燃气", "水务", "高速", "港口", "铁路", "基建", "环保")),
    ("消费与零售", ("食品", "饮料", "啤酒", "乳", "零售", "超市", "餐饮", "纺织", "服装", "体育")),
    ("汽车与出行", ("汽车", "车", "电池", "锂")),
    ("工业与制造", ("机械", "重工", "建材", "水泥", "化工", "造纸", "包装", "设备")),
    ("电讯", ("电信", "通信", "移动", "联通", "电讯")),
    ("航空与物流", ("航空", "机场", "物流", "航运", "货运")),
    ("博彩与酒店", ("赌", "博彩", "酒店", "旅游", "娱乐")),
)

# 一句话入选理由的措辞（各因子分位 ≥ 80 时触发，按顺序取前两条）
_REASON_PHRASES = {
    "size": "市值小（已剥壳价）",
    "reversal": "近一月跌得多",
    "momentum": "12-1 动量强",
    "turnover": "换手冷清",
    "ep": "同行业 EP 高",
}


# ------------------------------------------------------------------
# 环境变量（全部按调用时读取，测试可即时 patch）
# ------------------------------------------------------------------
def _env_flag(name, default="1"):
    return str(os.environ.get(name, default)).strip().lower() not in ("0", "false", "no", "off")


def _env_float(name, default):
    try:
        raw = os.environ.get(name)
        return float(raw) if raw not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)


def _env_int(name, default):
    try:
        raw = os.environ.get(name)
        return int(float(raw)) if raw not in (None, "") else int(default)
    except (TypeError, ValueError):
        return int(default)


def enabled():
    """OCTOPUS_LOWFREQ=0 关闭整栏（不采集、不渲染、不进审计）。"""
    return _env_flag("OCTOPUS_LOWFREQ", "1")


def allow_synthetic():
    """OCTOPUS_LOWFREQ_DEMO=1 才允许合成演示序列（默认关闭，取不到就缺席）。"""
    return _env_flag("OCTOPUS_LOWFREQ_DEMO", "0")


def params():
    """本次生效的参数（页面口径行直接引用这一份，避免两边各写一套）。"""
    weights = {}
    for key in FACTOR_ORDER:
        weights[key] = _env_float(f"OCTOPUS_LOWFREQ_W_{key.upper()}", DEFAULT_WEIGHTS[key])
    total = sum(weights.values())
    if total <= 0:  # 权重全 0 时回到等权，绝不出现除零
        weights = dict(DEFAULT_WEIGHTS)
    else:
        weights = {k: v / total for k, v in weights.items()}
    return {
        "universe": max(20, _env_int("OCTOPUS_LOWFREQ_UNIVERSE", DEFAULT_UNIVERSE)),
        "top_n": max(1, _env_int("OCTOPUS_LOWFREQ_TOP_N", DEFAULT_TOP_N)),
        "shell_floor": max(0.0, _env_float("OCTOPUS_LOWFREQ_SHELL_FLOOR", DEFAULT_SHELL_FLOOR)),
        "min_amount": max(0.0, _env_float("OCTOPUS_LOWFREQ_MIN_AMOUNT", DEFAULT_MIN_AMOUNT)),
        "ep_min_cap": max(0.0, _env_float("OCTOPUS_LOWFREQ_EP_MIN_CAP", DEFAULT_EP_MIN_CAP)),
        "min_peers": max(2, _env_int("OCTOPUS_LOWFREQ_MIN_PEERS", DEFAULT_MIN_INDUSTRY_PEERS)),
        "workers": max(1, _env_int("OCTOPUS_LOWFREQ_WORKERS", DEFAULT_WORKERS)),
        "min_publish_ranked": max(1, _env_int("OCTOPUS_LOWFREQ_MIN_RANKED", MIN_PUBLISH_RANKED)),
        "min_publish_share": min(1.0, max(0.0, _env_float("OCTOPUS_LOWFREQ_MIN_COVERAGE",
                                                          MIN_PUBLISH_SHARE))),
        "weights": weights,
    }


# ------------------------------------------------------------------
# 数据层：港股快照（东财 clist）+ 日线（providers，Yahoo 主源 / 东财备用）
# ------------------------------------------------------------------
_HK_CLIST_FS = "m:128+t:1,m:128+t:2,m:128+t:3,m:128+t:4"
_CLIST_FIELDS = "f2,f3,f6,f8,f9,f12,f14,f20,f21,f23,f100,f124"


def _providers_module():
    try:
        from octopus_quant import providers as _p
        return _p
    except Exception:  # pragma: no cover - 单独运行 / 打包缺包时才走到
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from octopus_quant import providers as _p
            return _p
        except Exception:
            return None


def _num(value):
    try:
        if value is None or value in ("-", ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_code(value):
    digits = "".join(ch for ch in str(value or "").split(".", 1)[0] if ch.isdigit())
    return digits.zfill(5) if digits else ""


def fetch_hk_snapshot(fetch_json, *, max_pages=6, page_size=100, timeout=12):
    """港股快照（总市值降序）：``{items, pages, complete, errors, served_urls}``。

    只取当前快照，不含历史成分；分页有硬上限，接口给出的 total 与实际拿到的不一致时
    如实写 ``complete=False``，绝不把「前几页」当成全市场。
    """
    empty = {"items": [], "pages": 0, "complete": False, "errors": [], "served_urls": [],
             "reported_total": None}
    prov = _providers_module()
    if not fetch_json or prov is None:
        empty["errors"].append("取数函数未注入或 providers 不可用")
        return empty
    items, errors, urls = [], [], []
    reported_total = None
    for page in range(1, max_pages + 1):
        params = {
            "pn": str(page), "pz": str(page_size), "po": "1", "np": "1", "fltt": "2",
            "invt": "2", "fid": "f20", "fs": _HK_CLIST_FS, "fields": _CLIST_FIELDS,
        }
        data, url = prov.fetch_json_chain(
            fetch_json, prov.chain_urls("em_clist"), params,
            ok=lambda d: bool(((d or {}).get("data") or {}).get("diff")), timeout=timeout)
        if data is None:
            errors.append(f"第 {page} 页取数失败")
            break
        if url:
            urls.append(url)
        block = (data.get("data") or {})
        if reported_total is None:
            reported_total = _num(block.get("total"))
        diff = block.get("diff") or []
        items.extend(diff)
        if len(diff) < page_size:
            break
    rows = []
    for it in items:
        code = _normalize_code(it.get("f12"))
        name = str(it.get("f14") or "").strip()
        if not code or not name:
            continue
        rows.append({
            "code": code,
            "name": name,
            "price": _num(it.get("f2")),
            "chg_pct": _num(it.get("f3")),
            "amount": _num(it.get("f6")),
            "turnover_today": _num(it.get("f8")),
            "pe": _num(it.get("f9")),
            "mcap": _num(it.get("f20")),
            "float_cap": _num(it.get("f21")),
            "pb": _num(it.get("f23")),
            "industry": str(it.get("f100") or "").strip(),
        })
    return {
        "items": rows,
        "pages": len(urls),
        "complete": bool(reported_total is not None and len(items) >= reported_total),
        "reported_total": reported_total,
        "errors": errors,
        "served_urls": urls,
    }


def _fetch_order(codes):
    """抓取顺序：按代码散列，**与市值无关**。

    2026-10-28 实测：按总市值降序抓 320 只日线，被限流掐掉的是排在后面的小票，
    结果只剩前 37 只大票，横截面整体偏向大市值（把 1500 亿的票标成「市值小」）。
    散列顺序让失败均匀落在各个市值段，即使覆盖不全也不系统性偏向某一端。
    """
    return sorted(set(codes), key=lambda c: hashlib.md5(str(c).encode()).hexdigest())


def fetch_hk_bars(fetch_json, codes, *, workers=DEFAULT_WORKERS, timeout=12, levels=None):
    """并发取港股日线（默认 2 年）：``{5位代码: [bars]}``；失败的键不出现（不造假）。

    失败会按 ``BARS_RETRY_LEVELS`` 逐级重试（降并发、加超时、最后缩到 1 年区间），
    每级之间留一点间隔，专治 Yahoo / 东财对密集请求的限流。
    """
    prov = _providers_module()
    if not fetch_json or prov is None or not codes:
        return {}
    pending = _fetch_order(codes)
    out = {}
    for idx, (level_workers, level_timeout, rng) in enumerate(levels or BARS_RETRY_LEVELS):
        if not pending:
            break
        if idx:
            time.sleep(1.5 * idx)          # 让限流窗口过去一点，别把重试也撞死在墙上
        concurrency = max(1, workers if idx == 0 else min(workers, level_workers))
        # 分批抓 + 批间短停：一次甩出几百个请求最容易吃到 429（2026-10-28 生产实测
        # 320 只里只回来 37 只）。分批后单批突发量小，限流触发概率明显下降。
        for start in range(0, len(pending), BARS_BATCH_SIZE):
            chunk = pending[start:start + BARS_BATCH_SIZE]
            specs = [(code, f"{code}.HK") for code in chunk]
            try:
                raw = prov.fetch_series_batch(fetch_json, specs, rng=rng,
                                              workers=concurrency, timeout=level_timeout)
            except Exception:
                raw = {}
            for symbol, bars in (raw or {}).items():
                code = _normalize_code(symbol)
                if code and bars and code not in out:
                    out[code] = bars
            if start + BARS_BATCH_SIZE < len(pending):
                time.sleep(BARS_BATCH_PAUSE)
        pending = [c for c in pending if c not in out]
    return out


# ------------------------------------------------------------------
# 计算层（纯函数，无网络）
# ------------------------------------------------------------------
def log_return_sum(bars, window):
    """最近 ``window`` 个交易日的 log 收益和 = ln(close[-1] / close[-1-window])。"""
    if not bars or len(bars) < window + 1:
        return None
    try:
        last = float(bars[-1]["close"])
        base = float(bars[-1 - window]["close"])
    except (KeyError, TypeError, ValueError):
        return None
    if last <= 0 or base <= 0:
        return None
    return math.log(last / base)


def momentum_12_1(bars, lookback=MOMENTUM_LOOKBACK, skip=MOMENTUM_SKIP):
    """12-1 动量：过去 ``lookback`` 个交易日、剔除最近 ``skip`` 个交易日的累计 log 收益。"""
    if not bars or len(bars) < lookback + 1:
        return None
    try:
        end = float(bars[-1 - skip]["close"])
        start = float(bars[-1 - lookback]["close"])
    except (KeyError, TypeError, ValueError):
        return None
    if end <= 0 or start <= 0:
        return None
    return math.log(end / start)


def mean_turnover(bars, float_cap, price, window=TURNOVER_WINDOW):
    """近 ``window`` 日日换手率均值（%）。

    换手率 = 当日成交股数 / 流通股本；流通股本用「流通市值 / 现价」反推（东财快照口径），
    因此是近似值：股本数据缺失 / 价格为 0 / 日线不足时返回 None，不用市值总量硬顶。
    """
    if not bars or not float_cap or not price or price <= 0:
        return None
    float_shares = float(float_cap) / float(price)
    if float_shares <= 0:
        return None
    sample = bars[-window:]
    vals = []
    for bar in sample:
        vol = _num(bar.get("volume"))
        if vol is None or vol <= 0:
            continue
        vals.append(vol / float_shares * 100.0)
    if len(vals) < max(10, window // 3):
        return None
    return sum(vals) / len(vals)


def mean_amount(bars, window=REVERSAL_WINDOW):
    """近 ``window`` 日成交额均值（港元近似：收盘价 × 成交量）；只用于流动性门槛。"""
    if not bars:
        return None
    sample = bars[-window:]
    vals = []
    for bar in sample:
        close = _num(bar.get("close"))
        vol = _num(bar.get("volume"))
        if close is None or vol is None or close <= 0 or vol <= 0:
            continue
        vals.append(close * vol)
    if not vals:
        return None
    return sum(vals) / len(vals)


def classify_industry(name, raw_industry=""):
    """行业归属：东财 f100 优先，空值按名称关键词粗分组（只用于同行业 EP 比较）。"""
    text = str(raw_industry or "").strip()
    if text and text not in ("-", "—"):
        return text
    name = str(name or "")
    for label, keys in _INDUSTRY_RULES:
        if any(k in name for k in keys):
            return label
    return "未分类"


def percentile_scores(values, higher_is_better=True):
    """横截面百分位（0–100，越大越优）；并列取平均名次，缺失键不出现在结果里。

    与「排名第一 = 100」不同，这里用 (rank - 0.5) / n，保证全市场 0–100 均匀铺开、
    且样本量变化时分数可比；n < 2 时无法比较，直接返回空。
    """
    items = [(k, v) for k, v in (values or {}).items()
             if v is not None and isinstance(v, (int, float)) and math.isfinite(v)]
    n = len(items)
    if n < 2:
        return {}
    items.sort(key=lambda kv: kv[1])
    out = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0          # 1..n
        pct = (avg_rank - 0.5) / n * 100.0
        for k in range(i, j + 1):
            out[items[k][0]] = pct if higher_is_better else 100.0 - pct
        i = j + 1
    return out


def industry_ep_scores(ep_values, industries, min_peers=DEFAULT_MIN_INDUSTRY_PEERS):
    """EP 的同行业分位：先在行业内排，样本不足的行业退回全市场分位并标注。

    返回 ``(scores, meta)``；meta 里记录每个行业用了哪种口径，页面如实展示。
    """
    groups = {}
    for code, ep in (ep_values or {}).items():
        if ep is None:
            continue
        groups.setdefault(industries.get(code) or "未分类", []).append(code)
    market_scores = percentile_scores(ep_values, higher_is_better=True)
    scores, meta = {}, {}
    for industry, codes in groups.items():
        if len(codes) >= min_peers:
            sub = {c: ep_values[c] for c in codes}
            scores.update(percentile_scores(sub, higher_is_better=True))
            meta[industry] = {"peers": len(codes), "basis": "同行业"}
        else:
            for code in codes:
                if code in market_scores:
                    scores[code] = market_scores[code]
            meta[industry] = {"peers": len(codes), "basis": "全市场（同行业样本不足）"}
    return scores, meta


def _reason_text(scores, keys_order=FACTOR_ORDER, threshold=80.0, limit=2):
    hits = [k for k in keys_order if (scores.get(k) or 0) >= threshold]
    if not hits:
        best = max(((k, scores.get(k) or -1) for k in keys_order), key=lambda kv: kv[1], default=None)
        if not best or best[1] < 0:
            return "五因子均在中间区，无突出项"
        return f"相对靠前：{FACTOR_META[best[0]]['name']}（分位 {best[1]:.0f}）"
    return "、".join(_REASON_PHRASES[k] for k in hits[:limit])


def _snapshot_pool(rows, cfg):
    """快照层：只用「价格 + 总市值 + PE」就能定性的一切（不依赖日线）。

    返回值 ``(pool, excluded)``：``pool`` 是所有通过报价 / 壳价值闸门的股票，
    **包含没有日线的**——小市值与 EP 的分位必须在这整池上算，否则横截面会被
    日线抓取成功率带偏（2026-10-28 生产实测踩过这个坑）。
    """
    shell_floor = float(cfg["shell_floor"])
    pool, excluded = [], {"no_quote": 0, "shell": 0, "illiquid": 0, "no_bars": 0, "short_bars": 0}
    for row in rows or []:
        code = row.get("code")
        if not code:
            continue
        mcap = _num(row.get("mcap"))
        price = _num(row.get("price"))
        if not mcap or mcap <= 0 or not price or price <= 0:
            excluded["no_quote"] += 1
            continue
        # ① 壳价值闸门：市值 ≤ 壳价值下限 → 视为纯壳（上市资格价），不进小市值排序
        if mcap <= shell_floor:
            excluded["shell"] += 1
            continue
        pe = _num(row.get("pe"))
        loss = bool(pe is not None and pe <= 0)
        ep = (1.0 / pe) if (pe is not None and pe > 0) else None
        ep_eligible = bool(ep is not None and mcap >= float(cfg["ep_min_cap"]) and not loss)
        pool.append({
            "code": code,
            "name": str(row.get("name") or code),
            "industry": classify_industry(row.get("name"), row.get("industry")),
            "price": price,
            "chg_pct": _num(row.get("chg_pct")),
            "mcap": mcap,
            "float_cap": _num(row.get("float_cap")),
            "snapshot_amount": _num(row.get("amount")),
            "pe": pe,
            "pb": _num(row.get("pb")),
            "loss": loss,
            "ep": ep if ep_eligible else None,
            "ep_display": ep,
            "ep_eligible": ep_eligible,
            "shell_ratio": min(1.0, shell_floor / mcap) if mcap > 0 else None,
            "net_value": mcap - shell_floor,
            "size_raw": -math.log(max(mcap - shell_floor, 1.0)),
        })
    return pool, excluded


def score_universe(rows, bars_map, cfg, *, synthetic=False):
    """把快照 + 日线算成「五因子横截面 + 综合分 + 是否够格出版名单」。

    ``rows``：快照行（见 fetch_hk_snapshot）；``bars_map``：{代码: bars}。

    分两层（2026-10-28 修正）：
      ① **快照层**：小市值、EP 只用快照就能算，分位在整个合格池（含无日线的票）上算；
      ② **日线层**：反转 / 动量 / 换手必须有日线，分位只在「有日线的子集」上算，
         并把覆盖率和偏差方向如实披露。
    这样即使日线只抓到一半，小市值排序仍然是**全市场口径**的相对便宜，而不是
    「一堆大票里最小的那只」。
    """
    shell_floor = float(cfg["shell_floor"])
    min_amount = float(cfg["min_amount"])
    weights = cfg["weights"]

    pool, excluded = _snapshot_pool(rows, cfg)

    # ---- ① 快照层分位（全池）----
    size_scores = percentile_scores({s["code"]: s["size_raw"] for s in pool},
                                    higher_is_better=True)
    industry_of = {s["code"]: s["industry"] for s in pool}
    ep_values = {s["code"]: s["ep"] for s in pool if s["ep"] is not None}
    ep_scores, ep_meta = industry_ep_scores(ep_values, industry_of, min_peers=cfg["min_peers"])

    # ---- ② 日线层：反转 / 动量 / 换手 ----
    stocks, bar_basis = [], {"bars_21d": 0, "snapshot_1d": 0}
    for s in pool:
        code = s["code"]
        bars = (bars_map or {}).get(code) or []
        if not bars:
            excluded["no_bars"] += 1
            continue
        if len(bars) < MIN_BARS + 1:
            excluded["short_bars"] += 1
            continue
        avg_amount = mean_amount(bars)
        basis = "bars_21d"
        if avg_amount is None:                     # 日线有收盘但没量：退回快照当日成交额
            avg_amount = s.get("snapshot_amount")
            basis = "snapshot_1d"
        # ③ 流动性门槛：日均成交额不足 → 进出都难，不进推荐池
        if min_amount > 0 and (avg_amount is None or avg_amount < min_amount):
            excluded["illiquid"] += 1
            continue
        bar_basis[basis] = bar_basis.get(basis, 0) + 1
        stock = dict(s)
        stock.update({
            "avg_amount": avg_amount,
            "liquidity_basis": "21 日均额" if basis == "bars_21d" else "今日成交额",
            "bars": len(bars),
            "reversal": (lambda v: v * 100 if v is not None else None)(
                log_return_sum(bars, REVERSAL_WINDOW)),
            "momentum": (lambda v: v * 100 if v is not None else None)(momentum_12_1(bars)),
            "turnover": mean_turnover(bars, s.get("float_cap"), s.get("price")),
            "synthetic": bool(synthetic),
        })
        stocks.append(stock)

    eligible = len(pool)
    base = {
        "params": {
            "universe": cfg["universe"], "top_n": cfg["top_n"], "shell_floor": shell_floor,
            "min_publish_ranked": cfg.get("min_publish_ranked"), "min_publish_share": cfg.get("min_publish_share"),
            "min_amount": min_amount, "ep_min_cap": cfg["ep_min_cap"],
            "min_peers": cfg["min_peers"], "weights": weights,
        },
        "universe": {
            "scanned": len(rows or []),
            "eligible": eligible,
            "with_bars": len(stocks),
            "ranked": 0,
            "bars_coverage": (len(stocks) / eligible * 100.0) if eligible else 0.0,
            "excluded": excluded,
            "liquidity_basis": {"21 日均额": bar_basis.get("bars_21d", 0),
                                "今日成交额": bar_basis.get("snapshot_1d", 0)},
        },
        "ep_basis": ep_meta,
        "synthetic": bool(synthetic),
    }

    if not stocks:
        base.update({
            "available": False,
            "reason": ("港股快照未取得" if not pool
                       else f"日线全缺（合格池 {eligible} 只，一只都没抓到日线）"),
            "mirrors": {},
            "factors": [],
            "stocks": [],
            "top": [],
            "portfolio": {},
            "publish": False,
            "publish_reason": "无可排序标的",
            "warnings": [],
        })
        return base

    # ---- 日线层分位 ----
    reversal_scores = percentile_scores({s["code"]: s["reversal"] for s in stocks},
                                        higher_is_better=False)
    momentum_scores = percentile_scores({s["code"]: s["momentum"] for s in stocks},
                                        higher_is_better=True)
    turnover_scores = percentile_scores({s["code"]: s["turnover"] for s in stocks},
                                       higher_is_better=False)
    lookups = {"size": size_scores, "reversal": reversal_scores, "momentum": momentum_scores,
               "turnover": turnover_scores, "ep": ep_scores}

    for s in stocks:
        s["scores"] = {k: lookups[k].get(s["code"]) for k in FACTOR_ORDER}
        # 小市值 / EP 来自全池分位；若该票不在池内（理论上不会）才缺
        have = {k: v for k, v in s["scores"].items() if v is not None}
        weight_sum = sum(weights.get(k, 0.0) for k in have)
        s["factor_count"] = len(have)
        if len(have) >= MIN_FACTORS and weight_sum >= MIN_WEIGHT_SHARE:
            s["composite"] = sum(have[k] * weights.get(k, 0.0) for k in have) / weight_sum
        else:
            s["composite"] = None
        s["missing_factors"] = [FACTOR_META[k]["name"] for k in FACTOR_ORDER
                                if s["scores"][k] is None]

    ranked = sorted([s for s in stocks if s["composite"] is not None],
                    key=lambda s: s["composite"], reverse=True)
    for i, s in enumerate(ranked, 1):
        s["rank"] = i
        s["reason"] = _reason_text(s["scores"])

    # ---- 出版门槛：样本太薄就不出名单（宁可缺席，不出版口径错位的名单）----
    publish, publish_reason = _publish_gate(len(ranked), eligible, cfg)

    # ---- 因子镜子：本栏对反转/动量的用法是「看市场体温」，不是选股指令 ----
    def _median(key, source):
        vals = sorted(x[key] for x in source if x.get(key) is not None)
        if not vals:
            return None
        mid = len(vals) // 2
        return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0

    reversal_vals = [s["reversal"] for s in stocks if s["reversal"] is not None]
    momentum_n = sum(1 for s in stocks if s["momentum"] is not None)
    mirrors = {
        "sample": len(stocks),
        "reversal_median": _median("reversal", stocks),
        "reversal_up_share": (sum(1 for v in reversal_vals if v > 0) / len(reversal_vals) * 100.0
                              if reversal_vals else None),
        "reversal_worst": min(reversal_vals) if reversal_vals else None,
        "reversal_best": max(reversal_vals) if reversal_vals else None,
        "momentum_median": _median("momentum", stocks),
        "momentum_positive_share": (
            sum(1 for s in stocks if (s["momentum"] or 0) > 0) / momentum_n * 100.0
            if momentum_n else None),
        "turnover_median": _median("turnover", stocks),
        "ep_median": _median("ep", pool),
        "mcap_median": _median("mcap", pool),
    }

    # ---- 因子覆盖与分位分布（按有值的样本算）----
    factors = []
    for key in FACTOR_ORDER:
        sample = pool if key in ("size", "ep") else stocks
        vals = [x["scores"].get(key) if isinstance(x.get("scores"), dict)
                else lookups[key].get(x["code"]) for x in sample]
        vals = [v for v in vals if v is not None]
        raw_key = {"size": "size_raw"}.get(key, key)
        raw_vals = sorted(x[raw_key] for x in sample
                          if isinstance(x.get(raw_key), (int, float)))
        factors.append({
            "key": key,
            "name": FACTOR_META[key]["name"],
            "formula": FACTOR_META[key]["formula"],
            "direction": FACTOR_META[key]["direction"],
            "weight": weights.get(key, 0.0),
            "universe_n": len(sample),
            "scored": len(vals),
            "coverage": len(vals) / len(sample) * 100.0 if sample else None,
            "raw_median": (raw_vals[len(raw_vals) // 2] if raw_vals else None),
        })

    top = ranked[:cfg["top_n"]] if publish else []
    base.update({
        "available": True,
        "as_of": _as_of_from_bars(bars_map),
        "factors": factors,
        "mirrors": mirrors,
        "stocks": ranked,
        "top": top,
        "portfolio": _portfolio_profile(top),
        "publish": publish,
        "publish_reason": publish_reason,
        "warnings": _warnings(pool, stocks, ranked, cfg, publish),
    })
    base["universe"]["ranked"] = len(ranked)
    return base


def _publish_gate(ranked_n, eligible_n, cfg):
    """名单出版门槛：可排序只数 ≥ max(min_publish_ranked, 合格池 × min_publish_share)。"""
    floor_n = int(cfg.get("min_publish_ranked", MIN_PUBLISH_RANKED))
    share = float(cfg.get("min_publish_share", MIN_PUBLISH_SHARE))
    need = max(floor_n, int(round(eligible_n * share)))
    if eligible_n == 0:
        return False, "合格池为空"
    if ranked_n < need:
        return False, (f"可排序 {ranked_n} 只 < 门槛 {need} 只"
                       f"（合格池 {eligible_n} 只 × {share:.0%}，且不少于 {floor_n} 只）")
    return True, f"可排序 {ranked_n} 只 ≥ 门槛 {need} 只"


def _warnings(pool, stocks, ranked, cfg, publish):
    out = []
    eligible = len(pool)
    if not ranked:
        out.append("没有一只股票拿到 3 个以上因子分位，综合分整体缺席（不硬排）")
    coverage = (len(stocks) / eligible * 100.0) if eligible else 0.0
    if eligible and coverage < MIN_PUBLISH_SHARE * 100.0:
        out.append(f"日线只覆盖 {len(stocks)}/{eligible} 只（{coverage:.0f}%）：反转 / 动量 / 换手的分位"
                   f"只在这部分股票里算，小市值与 EP 仍是全池口径；名单按出版门槛"
                   f"{'照常给出' if publish else '暂缓'}。")
    elif stocks and len(ranked) < max(5, len(stocks) * 0.3):
        out.append(f"仅 {len(ranked)}/{len(stocks)} 只有完整分位，样本偏薄")
    loss_n = sum(1 for s in pool if s["loss"])
    if loss_n:
        out.append(f"{loss_n} 只亏损股（PE ≤ 0）不进 EP 比较，只在正文单独点名")
    micro = sum(1 for s in pool if s["mcap"] < cfg["ep_min_cap"])
    if micro:
        out.append(f"{micro} 只市值低于 {cfg['ep_min_cap'] / 1e8:.0f} 亿港元，只参与小市值/反转/动量/换手，不参与 EP")
    snapshot_basis = sum(1 for s in stocks if s.get("liquidity_basis") == "今日成交额")
    if snapshot_basis:
        out.append(f"{snapshot_basis} 只日线缺成交量，流动性门槛改用快照当日成交额判断")
    return out


def _portfolio_profile(top):
    if not top:
        return {}
    def _avg(key):
        vals = [s[key] for s in top if isinstance(s.get(key), (int, float))]
        return sum(vals) / len(vals) if vals else None

    industries = {}
    for s in top:
        industries[s["industry"]] = industries.get(s["industry"], 0) + 1
    ranked_ind = sorted(industries.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "count": len(top),
        "avg_mcap": _avg("mcap"),
        "min_mcap": min((s["mcap"] for s in top), default=None),
        "avg_reversal": _avg("reversal"),
        "avg_momentum": _avg("momentum"),
        "avg_turnover": _avg("turnover"),
        "avg_ep": _avg("ep"),
        "avg_composite": _avg("composite"),
        "avg_shell_ratio": _avg("shell_ratio"),
        "loss_n": sum(1 for s in top if s["loss"]),
        "industries": ranked_ind,
        "top_industry": ranked_ind[0] if ranked_ind else None,
        "max_shell": max(top, key=lambda s: s["shell_ratio"] or 0) if top else None,
    }


def _as_of_from_bars(bars_map):
    dates = []
    for bars in (bars_map or {}).values():
        if bars:
            last = bars[-1].get("date")
            if last:
                dates.append(str(last)[:10])
    return max(dates) if dates else None


# ------------------------------------------------------------------
# 合成演示序列（只有显式开启才走这里；页面上点名「演示序列」）
# ------------------------------------------------------------------
def synthetic_inputs(count=60, date_str=""):
    """确定性合成快照 + 日线，仅供版面演示与离线回归。

    不参与任何真实结论：结果里 ``synthetic=True``，页面顶部会写「演示序列」。
    """
    import random
    seed = sum(map(ord, f"lowfreq|{date_str}"))
    rng = random.Random(seed)
    universes = [
        ("银行", 2600e8), ("保险", 900e8), ("软件与互联网", 3200e8), ("半导体与电子", 1100e8),
        ("医药与生物", 420e8), ("能源与资源", 780e8), ("消费与零售", 260e8), ("地产与物业", 210e8),
        ("公用与基建", 350e8), ("汽车与出行", 640e8), ("券商与交易所", 300e8), ("工业与制造", 120e8),
    ]
    rows, bars_map = [], {}
    for i in range(count):
        industry, base_cap = universes[i % len(universes)]
        code = f"{1000 + i * 7:05d}"
        mcap = base_cap * (0.2 + rng.random() * 1.6)
        price = round(2 + rng.random() * 240, 2)
        pe = round(rng.uniform(4, 40), 2) if rng.random() > 0.18 else -round(rng.uniform(1, 30), 2)
        rows.append({
            "code": code, "name": f"演示{industry}{i + 1:02d}", "price": price,
            "chg_pct": round(rng.gauss(0, 1.6), 2), "amount": 3e7 + rng.random() * 1e9,
            "turnover_today": round(abs(rng.gauss(0.5, 0.4)), 2), "pe": pe,
            "mcap": mcap, "float_cap": mcap * rng.uniform(0.4, 0.95),
            "pb": round(abs(rng.gauss(1.4, 0.8)) + 0.2, 2), "industry": industry,
        })
        drift = rng.gauss(0.0003, 0.0011)
        vol = 0.010 + rng.random() * 0.014
        px, bars = price, []
        start = datetime(2026, 1, 5)
        for d in range(300):
            px = max(0.2, px * math.exp(rng.gauss(drift, vol)))
            bars.append({"date": (start + timedelta(days=d)).strftime("%Y-%m-%d"),
                         "close": round(px, 3),
                         "volume": int(abs(rng.gauss(4e6, 1.6e6)) + 5e5)})
        bars_map[code] = bars
    return rows, bars_map


# ------------------------------------------------------------------
# 编排
# ------------------------------------------------------------------
def run_lowfreq_factors(fetch_json=None, date_str="", allow_synthetic_flag=False):
    """取数 → 计算 → 返回结构化结果（取不到就 available=False，不补造）。"""
    cfg = params()
    if not enabled():
        return {"available": False, "disabled": True, "reason": "OCTOPUS_LOWFREQ=0"}
    if fetch_json is None:
        if allow_synthetic_flag or allow_synthetic():
            rows, bars_map = synthetic_inputs(date_str=date_str)
            res = score_universe(rows, bars_map, cfg, synthetic=True)
            res["source_note"] = "合成演示序列（OCTOPUS_LOWFREQ_DEMO=1）"
            return res
        return {"available": False, "reason": "未注入取数函数（离线 / 测试环境）"}

    snapshot = fetch_hk_snapshot(fetch_json)
    rows = snapshot.get("items") or []
    if not rows:
        if allow_synthetic_flag or allow_synthetic():
            srows, bars_map = synthetic_inputs(date_str=date_str)
            res = score_universe(srows, bars_map, cfg, synthetic=True)
            res["source_note"] = "合成演示序列（OCTOPUS_LOWFREQ_DEMO=1）"
            return res
        return {"available": False,
                "reason": "港股快照未取得" + (f"（{snapshot['errors'][0]}）" if snapshot.get("errors") else ""),
                "snapshot": snapshot}

    # 按总市值降序取前 N 只建立计算池：控制日线请求量（港股前列已覆盖绝大多数成交与估值
    # 有意义的中大型标的）。注意：**排序只决定「进不进池」，不决定抓取顺序**——
    # 日线抓取按代码散列进行（见 _fetch_order），避免限流掐掉某一市值段。
    rows = sorted(rows, key=lambda r: r.get("mcap") or 0, reverse=True)[:cfg["universe"]]
    codes = [r["code"] for r in rows if (r.get("mcap") or 0) > cfg["shell_floor"]]
    bars_map = fetch_hk_bars(fetch_json, codes, workers=cfg["workers"])
    res = score_universe(rows, bars_map, cfg)
    res["snapshot"] = {
        "scanned": len(snapshot.get("items") or []),
        "pages": snapshot.get("pages"),
        "complete": snapshot.get("complete"),
        "reported_total": snapshot.get("reported_total"),
        "errors": snapshot.get("errors") or [],
        "universe_cap": cfg["universe"],
        "bars_requested": len(codes),
        "bars_fetched": len(bars_map),
        "bars_missing": max(0, len(codes) - len(bars_map)),
    }
    if res.get("available") and not res.get("publish"):
        # 数据抓到了但样本不够出版：把原因写进结果，页面与日志共用同一句话。
        res.setdefault("warnings", []).append(f"名单暂缓：{res.get('publish_reason')}")
    if not res.get("available") and (allow_synthetic_flag or allow_synthetic()):
        srows, sbars = synthetic_inputs(date_str=date_str)
        res = score_universe(srows, sbars, cfg, synthetic=True)
        res["source_note"] = "合成演示序列（OCTOPUS_LOWFREQ_DEMO=1）"
    return res


# ------------------------------------------------------------------
# 呈现层（只用 kit 原语）
# ------------------------------------------------------------------
def _esc(text):
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _kit_call(kit, name, *args, **kwargs):
    fn = getattr(kit, name, None)
    if callable(fn):
        try:
            return fn(*args, **kwargs)
        except TypeError:
            try:
                return fn(*args)
            except Exception:
                return ""
        except Exception:
            return ""
    return ""


def _sub(kit, text):
    html = _kit_call(kit, "sub", text)
    if html:
        return html
    return f'<div style="font-size:12px;font-weight:900;margin:8px 0 4px 0;">{_esc(text)}</div>'


def _table(kit, headers, rows, aligns=None):
    html = _kit_call(kit, "table", headers, rows, aligns=aligns) if aligns else \
        _kit_call(kit, "table", headers, rows)
    if html:
        return html
    head = "".join(f'<th style="padding:4px 6px;background:#F1F3F4;border:1px solid #ddd;'
                   f'font-size:11px;text-align:left;">{_esc(h)}</th>' for h in headers)
    body = ""
    for row in rows:
        body += "<tr>" + "".join(f'<td style="padding:4px 6px;border:1px solid #eee;'
                                 f'font-size:11px;">{cell}</td>' for cell in row) + "</tr>"
    return f'<table style="width:100%;border-collapse:collapse;">{head and "<tr>" + head + "</tr>"}{body}</table>'


def _kv(kit, pairs):
    html = _kit_call(kit, "kv", pairs)
    if html:
        return html
    rows = "".join(f'<tr><td style="padding:4px 6px;border:1px solid #eee;color:#666;'
                   f'font-size:11px;">{_esc(k)}</td>'
                   f'<td style="padding:4px 6px;border:1px solid #eee;font-size:11px;">{v}</td></tr>'
                   for k, v in pairs)
    return f'<table style="width:100%;border-collapse:collapse;">{rows}</table>'


def _note(kit, text):
    return _kit_call(kit, "note", text) or \
        f'<div style="font-size:11px;color:#666;margin:6px 0;">{_esc(text)}</div>'


def _pct(value, digits=1):
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "—"
    return f"{value:+.{digits}f}%"


def _num_text(value, digits=1, suffix=""):
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "—"
    return f"{value:,.{digits}f}{suffix}"


def _yi(value):
    """港元金额 → 亿元。"""
    if value is None or not isinstance(value, (int, float)):
        return "—"
    return f"{value / 1e8:,.1f}"


def _dir_color(value):
    if value is None:
        return "#666"
    return "#B23A2E" if value > 0 else ("#2E7D32" if value < 0 else "#666")


def _arrow(value):
    if value is None:
        return "—"
    return "▲" if value > 0 else ("▼" if value < 0 else "■")


def _score_chip(score):
    if score is None:
        return "—"
    bg, ink = ("#EAF7C9", "#3D5200") if score >= 70 else (
        ("#F1F3F4", "#333") if score >= 45 else ("#FFF3E0", "#8D4E00"))
    return (f'<span style="display:inline-block;padding:1px 6px;border-radius:999px;'
            f'background:{bg};color:{ink};font-size:11px;">{score:.0f}</span>')


def render(res, kit, plain=False, top_n=None):
    """栏目正文：口径 → 因子镜子 → 推荐 20 只 → 组合画像 → 剔除与风险。"""
    if not res or not res.get("available"):
        return ""
    cfg = res.get("params") or {}
    weights = cfg.get("weights") or DEFAULT_WEIGHTS
    top = res.get("top") or []
    if top_n:
        top = top[:int(top_n)]
    out = []

    # ---- ① 口径 ----
    excluded = (res.get("universe") or {}).get("excluded") or {}
    universe = res.get("universe") or {}
    coverage = universe.get("bars_coverage") or 0.0
    publish = bool(res.get("publish"))
    # 数据覆盖是实质披露：入门版也照出一行，不能把「只抓到一半日线」藏起来。
    out.append(_kv(kit, [(
        "样本覆盖",
        f"快照 {universe.get('scanned', 0)} 只 → 合格池 {universe.get('eligible', 0)} 只"
        f"（剥壳后）→ 有日线 {universe.get('with_bars', 0)} 只（{coverage:.0f}%）"
        f"→ 可排序 {universe.get('ranked', 0)} 只"
        + ("" if publish else f" · 名单暂缓：{_esc(res.get('publish_reason') or '')}"))]))
    if not publish:
        out.append(_note(kit, "⚠ 本次样本不足，**不出推荐名单**：日线抓取不全时横截面会偏向抓得到的那一端"
                              "（例如只剩大票，于是把千亿市值标成「市值小」）。宁可缺席，也不出版口径错位的名单。"))
    if not plain:
        out.append(_sub(kit, "本次口径"))
        out.append(_kv(kit, [
            ("数据时点", f"{_esc(res.get('as_of') or '—')} 收盘 · 港股 {universe.get('scanned', 0)} 只快照"),
            ("计算池", f"按总市值取前 {cfg.get('universe')} 只 → 合格池 {universe.get('eligible', 0)} 只"
                     f"（小市值 / EP 在全池上打分）→ 有日线 {universe.get('with_bars', 0)} 只"
                     f"（反转 / 动量 / 换手只用这部分）"),
            ("壳价值下限", f"{cfg.get('shell_floor', 0) / 1e8:,.1f} 亿港元 · 市值不高于它的按「纯壳」剔除，不参与小市值排序"),
            ("流动性门槛", f"21 日日均成交额 ≥ {cfg.get('min_amount', 0) / 1e8:,.2f} 亿港元"),
            ("EP 比较池", f"市值 ≥ {cfg.get('ep_min_cap', 0) / 1e8:,.0f} 亿港元且不亏损 · 同行业内部排序（同行业不足 {cfg.get('min_peers')} 只退回全市场分位）"),
            ("因子权重", " / ".join(
                f"{FACTOR_META[k]['name']} {weights.get(k, 0) * 100:.0f}%" for k in FACTOR_ORDER)),
            ("综合分规则", f"各因子横截面分位（0–100，方向已统一）加权；至少 {MIN_FACTORS} 个因子且可用权重 ≥ {MIN_WEIGHT_SHARE * 100:.0f}% 才给分，否则如实留空"),
            ("出版门槛", f"可排序 ≥ max({cfg.get('min_publish_ranked')} 只, 合格池 × "
                      f"{(cfg.get('min_publish_share') or 0) * 100:.0f}%)；不够就不出名单，"
                      f"不拿残缺样本凑数"),
        ]))

    # ---- ② 因子镜子：反转与动量的正确用法 ----
    mirrors = res.get("mirrors") or {}
    rev_med = mirrors.get("reversal_median")
    out.append(_sub(kit, "因子镜子 · 市场体温（不是选股指令）"))
    mirror_rows = [
        ["短期反转", "近 21 日 log 收益中位数", _pct(rev_med),
         _num_text(mirrors.get("reversal_up_share"), 1, "%") + " 的股票近一月上涨",
         "买在无人问津处，卖在人声鼎沸时"],
        ["动量 12-1", "过去 250 日（剔除最近 21 日）中位数", _pct(mirrors.get("momentum_median")),
         _num_text(mirrors.get("momentum_positive_share"), 1, "%") + " 的股票 12-1 为正",
         "强者恒强只在中期成立，短期常被反转打断"],
        ["换手率", "近 63 日日均换手率中位数", _num_text(mirrors.get("turnover_median"), 2, "%"),
         "冷清一端更容易出现低换手溢价", "换手越高越拥挤，越容易被交易成本吃掉"],
        ["价值 EP", "可比较样本的 EP 中位数", _num_text(mirrors.get("ep_median"), 4),
         "约等于 1/PE，需与同行业对照看", "全市场 EP 中位数受行业结构影响，不做跨行业直接比"],
    ]
    out.append(_table(kit, ["因子", "本次中位数", "数值", "分布", "怎么读"], mirror_rows,
                      aligns=("left", "left", "right", "left", "left")))

    # ---- ③ 港股推荐 20 只 ----
    if top:
        heading = f"港股推荐 {len(top)} 只（五因子综合分降序）"
    elif not publish:
        heading = "港股推荐：本次样本不足，名单暂缓"
    else:
        heading = "港股推荐：本次无可排序标的"
    out.append(_sub(kit, heading))
    if top:
        rows = []
        for s in top:
            rows.append([
                str(s.get("rank") or "—"),
                f"{_esc(s['name'])}<br><span style='color:#666;font-size:10px;'>{_esc(s['code'])}</span>",
                _esc(s.get("industry") or "未分类"),
                _yi(s.get("mcap")),
                f'<span style="color:{_dir_color(s.get("reversal"))};">{_pct(s.get("reversal"))}</span>',
                f'<span style="color:{_dir_color(s.get("momentum"))};">{_pct(s.get("momentum"))}</span>',
                _num_text(s.get("turnover"), 2, "%"),
                _num_text(s.get("ep_display"), 3),
                _score_chip(s.get("composite")),
                _esc(s.get("reason") or "—"),
            ])
        out.append(_table(kit,
                          ["#", "标的", "行业", "市值(亿)", "反转21日", "动量12-1", "换手3月", "EP", "综合分", "入选理由"],
                          rows,
                          aligns=("center", "left", "left", "right", "right", "right",
                                  "right", "right", "center", "left")))
        out.append(_note(kit, "分位分已统一为「越大越好」：反转一列显示的是原始涨跌幅（越绿越靠前，"
                              "说明近一月跌得多），换手一列显示的是原始换手率（越低越靠前）。"
                              "综合分是相对排序值，不是上涨概率。"))
    elif not publish:
        out.append(_note(kit, f"出版门槛未达：{res.get('publish_reason') or '样本不足'}。"
                             "名单不凑数——残缺样本上选出来的「小市值」，多半只是「抓得到日线的大票」。"))
    else:
        out.append(_note(kit, "本次没有标的凑齐 3 个以上因子分位，不硬排、不凑数量。"))

    # ---- ④ 组合画像 ----
    pf = res.get("portfolio") or {}
    if pf:
        ind_text = "、".join(f"{name} {n} 只" for name, n in (pf.get("industries") or [])[:4]) or "—"
        shell_top = pf.get("max_shell") or {}
        out.append(_sub(kit, "组合画像"))
        out.append(_kv(kit, [
            ("只数与综合分", f"{pf.get('count')} 只 · 综合分均值 {_num_text(pf.get('avg_composite'), 1)}"),
            ("市值结构", f"平均 {_yi(pf.get('avg_mcap'))} 亿港元 · 最小 {_yi(pf.get('min_mcap'))} 亿"),
            ("因子平均值", f"反转 {_pct(pf.get('avg_reversal'))} · 动量 {_pct(pf.get('avg_momentum'))} · "
                         f"换手 {_num_text(pf.get('avg_turnover'), 2, '%')} · EP {_num_text(pf.get('avg_ep'), 4)}"),
            ("行业分布", ind_text + (f"（最大行业：{pf['top_industry'][0]}）" if pf.get("top_industry") else "")),
            ("壳价值", f"平均壳价值占比 {_num_text((pf.get('avg_shell_ratio') or 0) * 100, 1, '%')}"
                      + (f" · 最高 {_esc(shell_top.get('name') or '')} {_num_text((shell_top.get('shell_ratio') or 0) * 100, 1, '%')}"
                         if shell_top else "")),
            ("亏损股", f"组合内 {pf.get('loss_n', 0)} 只（EP 不参与它的排序，单独标注）"),
        ]))

    # ---- ⑤ 剔除与风险 ----
    if not plain:
        out.append(_sub(kit, "剔除与风险披露"))
        out.append(_kv(kit, [
            ("纯壳剔除", f"{excluded.get('shell', 0)} 只市值不高于壳价值下限（上市资格价，不是便宜）"),
            ("流动性剔除", f"{excluded.get('illiquid', 0)} 只 21 日日均成交额不足"),
            ("数据不足", f"无日线 {excluded.get('no_bars', 0)} 只 · 日线不足 {excluded.get('short_bars', 0)} 只 · 无有效报价 {excluded.get('no_quote', 0)} 只"),
            ("未参与 EP", f"亏损股 {sum(1 for s in res.get('stocks') or [] if s.get('loss'))} 只、"
                        f"微市值 {sum(1 for s in res.get('stocks') or [] if not s.get('loss') and s.get('ep') is None)} 只"),
        ]))
        for warn in res.get("warnings") or []:
            out.append(_note(kit, f"⚠ {warn}"))
        ep_basis = res.get("ep_basis") or {}
        fallback = [k for k, v in ep_basis.items() if str(v.get("basis", "")).startswith("全市场")]
        if fallback:
            out.append(_note(kit, "EP 退回全市场分位的行业（同行业可比公司不足）："
                                  + "、".join(f"{k}({ep_basis[k].get('peers')}只)" for k in fallback[:6])
                                  + ("…" if len(fallback) > 6 else "")))
    if res.get("synthetic"):
        out.append(_note(kit, "⚠ 本次为合成演示序列（OCTOPUS_LOWFREQ_DEMO=1），数字只用于版面演示，"
                              "不代表任何真实港股，不可据此交易。"))
    if not plain:
        out.append(_note(kit, "口径：低估值、小市值、低换手与强动量都是「相对排序」，不是收益承诺；"
                              "五因子在港股同样会撞上流动性折价、老千股与壳股陷阱，所以本栏先做壳价值与"
                              "流动性两道硬门槛，再把亏损股从 EP 里剔除。规则合成、可复现，不构成投资建议。"))
    return "".join(out)
