#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎨 呈现层 —— 量化引擎的第 5 层。

只做一件事：把 engine 的结果字典翻译成 HTML。**不自带任何配色或字体**——
主题相关的排版函数（表格 / 小标题 / 涨跌徽标 / 信号格）全部由 pipeline 的
``kit`` 注入，因此 guizang（黑白墨水屏）与 pixel（复古像素）两套主题自动兼容，
也避免了「量化包反向依赖日报」的循环引用。

约束（与日报其它栏目一致）：
  · 纯内联样式、单列满宽表格；
  · 涨跌用 ▲ / ▼ / ■ + 正负号三重编码，不依赖颜色；
  · 取不到的数字一律显示「暂缺」，绝不留空、更不填 0。

精简模式（2026-09-30 起，pipeline 用 ``render.LITE = pipeline.LITE_ENABLED`` 同步）：
  · **结论与自检数字一个不删**，只把「方法论长注 / 校准曲线表 / 分项评分表 /
    五因子逐行」压成一行结论，并注明「--full 看全文」；
  · 个股概率表只留 5 日概率**最强的 5 只 + 最弱的 3 只**，被折叠的只数如实写出；
  · 关掉精简（OCTOPUS_LITE=0 / --full）→ 逐字回到全量长版。
"""
from __future__ import annotations

import os

from . import liquidity

MISS = '<span style="font-weight:700;">■ 暂缺</span>'

# 精简模式开关：pipeline 启动时会用自己的 LITE_ENABLED 覆盖（--full / OCTOPUS_LITE=0）。
LITE = str(os.environ.get("OCTOPUS_LITE", "1")).strip().lower() not in ("0", "false", "no")

# 入门版开关（2026-10-03）：精简模式下再把「说明文字 / 过程文字」收掉——方法论脚注、
# 口径行、校准细节、来源过程只在 --notes / --full 时出现；数字与结论一个不删。
# pipeline 启动时按 OCTOPUS_NOTES / --notes 覆盖；LITE=False 时本开关无效（全量照旧）。
PLAIN = str(os.environ.get("OCTOPUS_NOTES", "0")).strip().lower() not in ("1", "true", "yes")


def _plain():
    return bool(LITE) and bool(PLAIN)

# 精简模式下个股概率表的留行数：最强 5 只 + 最弱 3 只（短线客只关心两头）。
LITE_STOCK_HEAD = 5
LITE_STOCK_TAIL = 3

# 指数简称（窄屏表格用）：恒生指数 → 恒指、恒生科技 → 恒科、国企指数 → 国企
SHORT_NAMES = {"恒生指数": "恒指", "恒生科技": "恒科", "国企指数": "国企"}


def short_name(label):
    return SHORT_NAMES.get(label) or str(label or "")


# ------------------------------------------------------------------
# 数字格式化（None → 暂缺，绝不补 0）
# ------------------------------------------------------------------
def pct(value, digits=2, sign=True):
    if value is None:
        return MISS
    try:
        return f"{float(value):{'+' if sign else ''}.{digits}f}%"
    except (TypeError, ValueError):
        return MISS


def num(value, digits=2, comma=True):
    if value is None:
        return MISS
    try:
        v = float(value)
    except (TypeError, ValueError):
        return MISS
    return f"{v:,.{digits}f}" if comma else f"{v:.{digits}f}"


def yi(value, digits=0):
    """亿元格式化。"""
    if value is None:
        return MISS
    try:
        return f"{float(value):,.{digits}f} 亿"
    except (TypeError, ValueError):
        return MISS


def prob(value, digits=0):
    if value is None:
        return MISS
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return MISS


def arrow_of(p_up):
    """概率 → 方向箭头（≥60% 偏多 / ≤40% 偏空 / 其余中性）。"""
    if p_up is None:
        return "■"
    if p_up >= 0.60:
        return "▲"
    if p_up <= 0.40:
        return "▼"
    return "■"


def signal_word(p_up):
    if p_up is None:
        return "无信号"
    if p_up >= 0.62:
        return "▲偏多"
    if p_up >= 0.55:
        return "▲微多"
    if p_up <= 0.38:
        return "▼偏空"
    if p_up <= 0.45:
        return "▼微空"
    return "■中性"


def prob_cell(kit, p_up, trend_value=None, digits=0):
    """概率单元格：箭头 + 百分比（涨跌用符号表达，不靠颜色）。"""
    if p_up is None:
        return MISS
    arrow = arrow_of(p_up)
    return f"{arrow} {prob(p_up, digits)}"


def band_text(bands, digits=0):
    if not bands:
        return MISS
    lo, hi = bands.get("lo95"), bands.get("hi95")
    if lo is None or hi is None:
        return MISS
    return f"{lo:,.{digits}f} – {hi:,.{digits}f}"


# ------------------------------------------------------------------
# ① 量化分析总览
# ------------------------------------------------------------------
def render_forecast(res, kit):
    """预测概括 + 指数概率表 + 模型可信度 + 预测复盘。"""
    esc = kit.esc
    out = []
    head = res.get("headline") or {}
    if head.get("available"):
        out.append(kit.kv([
            ("预测概括", f'<b>{esc(head.get("arrow", "■"))} '
                       f'{esc(head.get("label", "中性"))} '
                       f'{prob(head.get("p_up"))}</b> · {esc(head["text"])}'),
        ]))
        # 数据新鲜度与动态调整摘要（确保最新数据 + 动态调整可视化）
        as_of = res.get("as_of")
        gen_at = res.get("generated_at")
        freshness_note = []
        if as_of:
            freshness_note.append(f'{esc(as_of)} 收盘 → {esc(res.get("target_label") or "下一交易日")}')
        if gen_at:
            freshness_note.append(f'生成于 {esc(gen_at)}')
        # 检查是否有动态调整记录
        primary = res.get("primary") or {}
        p5 = (primary.get("probs") or {}).get(5) or {}
        adjustments = []
        if p5.get("delta") is not None and abs(p5["delta"]) > 1e-6:
            adjustments.append(f'流动性 {p5["delta"]*100:+.1f}pp')
        if p5.get("vol_adjust") is not None and abs(p5["vol_adjust"]) > 1e-6:
            adjustments.append(f'波动率 {p5["vol_adjust"]*100:+.1f}pp')
        if p5.get("perf_adjust") is not None and abs(p5["perf_adjust"]) > 1e-6:
            adjustments.append(f'表现 {p5["perf_adjust"]*100:+.1f}pp')
        if _plain():
            # 入门版：只留「哪天收盘 → 预测哪天」；生成时间、更新节奏、三重调整、预测目标
            # （与数据时效重复）都是过程说明，--notes 再看。
            if as_of:
                out.append(kit.kv([("数据时效", freshness_note[0])]))
        else:
            if freshness_note:
                out.append(kit.kv([("数据时效", " · ".join(freshness_note) + " · 每日 09:00 前更新（港股开盘前）")]))
            if adjustments:
                out.append(kit.kv([("动态调整", " · ".join(adjustments) + "（已含在概率中，有界 ±5pp，波动率与表现收缩额外）")]))
            else:
                out.append(kit.kv([("动态调整", "流动性/波动率/历史表现三重动态调整（本次无显著修正，概率为模型原始校准值）")]))

            out.append(kit.kv([("预测目标",
                                f'{esc(res.get("as_of") or "—")} 收盘后 → '
                                f'{esc(res.get("target_label") or "下一交易日")}')]))

    # ---- 指数概率表 ----
    rows = []
    bands_pairs = []
    for row in res.get("indices") or []:
        feat = row["feat"]
        p1 = row["probs"].get(1) or {}
        p5 = row["probs"].get(5) or {}
        p20 = row["probs"].get(20) or {}
        short = short_name(row["label"])
        rows.append([
            esc(row["label"]),
            num(feat.get("close"), 0),
            kit.trend(feat.get("chg_pct"), compact=True),
            prob_cell(kit, p1.get("p_up")),
            prob_cell(kit, p5.get("p_up")),
            prob_cell(kit, p20.get("p_up")),
            esc(row["trend"]["label"]),
        ])
        bands_pairs.append(
            (f'{esc(short)} 5日区间（95%）',
             band_text(p5.get("bands"), 0) +
             (f' · 期望 {(p5.get("bands") or {}).get("mu_pct", 0):+.1f}%'
              if p5.get("bands") else "")))
    if rows:
        out.append(kit.sub("指数概率" if _plain() else "指数概率（校准后）"))
        out.append(kit.table(
            ["标的", "现价", "涨跌", "1日", "5日", "20日", "趋势"],
            rows, aligns=("left", "right", "right", "right", "right", "right", "right")))
        out.append(kit.kv(bands_pairs))
        if _plain():
            pass                  # 入门版：方法论脚注不出
        elif LITE:
            # 精简模式：方法论长注压成一行（校准口径 + 三重调整 + 概率夹，一个不删；
            # 权重细则与「短高长低属正常」的解释指回全量版）。
            out.append(kit.note("概率 = 五因子综合分经自身历史校准（分桶 + 保序 + 逻辑回归）后的上涨频率，"
                                "已含流动性 ±5pp / 波动率分位 / 历史表现三重动态调整，最终夹在 5%~95%；"
                                "1 / 5 / 20 日各自独立校准。权重与调整细则 --full 看全文。"))
        else:
            out.append(kit.note("概率 = 五因子综合分经自身历史「分桶 + 保序 + 逻辑回归」校准后的"
                                "上涨频率，已含三重动态调整：① 流动性有界修正 ±5pp（量能与深度，"
                                "南向已计入 FLOW 因子不重复）；② 波动率分位动态收缩（高波动 85%+ 分位收缩 20% 向 50%，"
                                "低波动 15%- 分位轻微放大）；③ 历史表现反馈收缩（近 5 次以上预测命中 <48% 或 Brier>0.27 时收缩 10%~20%）；"
                                "最终夹在 5%~95%；1 / 5 / 20 日三档各自独立校准（基准频率与样本不同，"
                                "出现短高长低属正常，表示短中期动能不一致）。因子权重本身也动态调整："
                                "高波动降 MOM 提 REV，强趋势提 TRD，资金流强提 FLOW，详见五因子拆解。"))

    # ---- 模型可信度（推进式回测）----
    val = res.get("validation") or {}
    v1 = val.get(1)
    if _plain() and v1:
        # 入门版：自检只报「命中率 vs 基准」与留痕命中——z 值 / Brier / 对数损失 /
        # 回测口径这些统计过程文字 --notes 再看。
        v5 = val.get(5) or {}
        check = [("模型自检",
                  f'1日命中 {v1["hit_rate"] * 100:.0f}%（基准 {v1["base_rate"] * 100:.0f}%）'
                  + (f' · 5日命中 {v5["hit_rate"] * 100:.0f}%（基准 {v5["base_rate"] * 100:.0f}%）'
                     if v5 else ""))]
        jr = res.get("journal") or {}
        if jr.get("n") and jr.get("hit_rate") is not None:
            check.append(("预测复盘", f'已结算 {jr["n"]} 次 · 方向命中 {prob(jr["hit_rate"], 0)}'))
        out.append(kit.sub("模型可信度"))
        out.append(kit.kv(check))
        return "".join(out)
    if LITE and v1:
        # 精简模式：**自检数字一个不删**，六行键值 + 校准曲线表 + 复盘表压成三行结论
        # （命中率 / 显著性 / Brier / 留痕命中全在），被折叠的表格如实点名、指回全量版。
        v5 = val.get(5) or {}
        sig = ""
        if v1.get("z") is not None:
            sig = ("显著" if abs(v1["z"]) >= 1.96
                   else ("弱显著" if abs(v1["z"]) >= 1.28 else "不显著"))
        check = [
            ("模型自检", f'1日命中 {v1["hit_rate"] * 100:.1f}%（基准 {v1["base_rate"] * 100:.1f}%'
                        f' · 样本 {v1["n"]} · z={v1.get("z", 0):+.2f} {sig or "—"}）'
                        + (f' · 5日命中 {v5["hit_rate"] * 100:.1f}%（基准 '
                           f'{v5["base_rate"] * 100:.1f}% · 样本 {v5["n"]}）' if v5 else "")),
        ]
        quality = []
        if v1.get("brier") is not None:
            quality.append(f'Brier {v1["brier"]:.3f}（0.25=瞎猜）')
        if v1.get("log_loss") is not None:
            quality.append(f'对数损失 {v1["log_loss"]:.3f}（0.693=瞎猜）')
        if v1.get("mean_ret_when_up") is not None:
            quality.append(f'看多日均 {v1["mean_ret_when_up"]:+.2f}% / '
                           f'看空日均 {v1["mean_ret_when_down"]:+.2f}%')
        if quality:
            check.append(("概率质量", " · ".join(quality)))
        jr = res.get("journal") or {}
        if jr.get("n"):
            replay = f'已结算 {jr["n"]} 次'
            if jr.get("hit_rate") is not None:
                replay += f' · 方向命中 {prob(jr["hit_rate"], 0)}'
            if jr.get("band_hit_rate") is not None:
                replay += f' · 区间命中 {prob(jr["band_hit_rate"], 0)}（理论 95%）'
            if jr.get("brier") is not None:
                replay += f' · 留痕 Brier {jr["brier"]:.3f}'
            check.append(("预测复盘", replay))
        check.append(("口径", "推进式（walk-forward）回测，每步只用该日之前的数据校准，无未来函数 · "
                             "校准曲线 / 逐次复盘表已折叠，--full 看全文"))
        out.append(kit.sub("模型可信度（自己检验自己）"))
        out.append(kit.kv(check))
        return "".join(out)
    if v1:
        pairs = []
        pairs.append(("回测口径", "推进式（walk-forward）：每步只用该日之前的数据校准，无未来函数"))
        pairs.append(("1日方向", (f'命中 {v1["hit_rate"]*100:.1f}% · 基准 {v1["base_rate"]*100:.1f}%'
                                 f' · 样本 {v1["n"]}')))
        if v1.get("z") is not None:
            sig = "显著（p<0.05）" if abs(v1["z"]) >= 1.96 else (
                "弱显著（p<0.20）" if abs(v1["z"]) >= 1.28 else "不显著")
            pairs.append(("显著性", f'z={v1["z"]:+.2f} · {sig}'))
        v5 = val.get(5)
        if v5:
            pairs.append(("5日方向", (f'命中 {v5["hit_rate"]*100:.1f}% · 基准 '
                                     f'{v5["base_rate"]*100:.1f}% · 样本 {v5["n"]}')))
        if v1.get("brier") is not None:
            pairs.append(("概率质量", f'Brier {v1["brier"]:.3f}（0.25=瞎猜）'
                                     + (f' · 对数损失 {v1["log_loss"]:.3f}（0.693=瞎猜）'
                                        if v1.get("log_loss") is not None else "")))
        if v1.get("mean_ret_when_up") is not None:
            pairs.append(("信号收益", f'看多日均值 {v1["mean_ret_when_up"]:+.2f}% · '
                                     f'看空日均值 {v1["mean_ret_when_down"]:+.2f}%'))
        out.append(kit.sub("模型可信度（自己检验自己）"))
        out.append(kit.kv(pairs))

        curve = v1.get("reliability") or []
        if curve:
            out.append(kit.table(
                ["预测档", "次数", "平均预测", "实际频率"],
                [[f'{c["lo"]*100:.0f}–{c["hi"]*100:.0f}%', str(c["n"]),
                  prob(c["pred"], 1), prob(c["actual"], 1)] for c in curve],
                aligns=("left", "right", "right", "right")))
            out.append(kit.note("校准曲线：平均预测与实际频率越接近，概率越可信。"))

    # ---- 预测留痕复盘 ----
    jr = res.get("journal") or {}
    if jr.get("n"):
        pairs = [("已结算", f'{jr["n"]} 次预测（每日留痕，次日按真实收盘结算）')]
        if jr.get("hit_rate") is not None:
            pairs.append(("方向命中", prob(jr["hit_rate"], 0)))
        if jr.get("band_hit_rate") is not None:
            pairs.append(("区间命中", f'{prob(jr["band_hit_rate"], 0)}（95% 区间，理论 95%）'))
        if jr.get("brier") is not None:
            pairs.append(("留痕 Brier", f'{jr["brier"]:.3f}'))
        out.append(kit.sub("预测复盘（反馈闭环）"))
        out.append(kit.kv(pairs))
        recent = [r for r in (jr.get("recent") or []) if r.get("chg") is not None]
        if recent:
            out.append(kit.table(
                ["预测日", "目标日", "概率", "实际", "结果"],
                [[esc(r["date"][5:]), esc((r.get("target") or "—")[5:]),
                  prob(r.get("p_up")), pct(r["chg"]),
                  "✓ 命中" if r.get("hit") else "✗ 未中"] for r in recent],
                aligns=("left", "left", "right", "right", "right")))
    return "".join(out)


# ------------------------------------------------------------------
# ② 港股概率走势分析
# ------------------------------------------------------------------
def render_hk_probability(res, kit):
    """指数状态 + 个股概率表 + 市场宽度 + 因子贡献。"""
    esc = kit.esc
    out = []

    # ---- 指数状态详表 ----
    rows = []
    state_pairs = []
    for row in res.get("indices") or []:
        f = row["feat"]
        tr = row["trend"]
        probs = tr.get("probs") or {}
        short = short_name(row["label"])
        rows.append([
            esc(row["label"]),
            num(f.get("sma20"), 0),
            num(f.get("sma60"), 0),
            num(f.get("rsi14"), 1),
            num(f.get("mom_z20"), 2, comma=False),
            num(f.get("vol20"), 1),
            (f'{f["vol_pct"]*100:.0f}%' if f.get("vol_pct") is not None else MISS),
            num(f.get("trend_t"), 2, comma=False),
        ])
        state_pairs.append(
            (f'{esc(short)} 趋势状态',
             f'{esc(tr["label"])} · ↑{probs.get("up", 0):.0f}% / '
             f'↓{probs.get("down", 0):.0f}% / →{probs.get("flat", 0):.0f}%'
             + (f'<br><span style="font-weight:400;">{esc(tr["note"])}</span>'
                if tr.get("note") and not _plain() else "")))
    if rows:
        # 入门版：小标题不带「统计口径」，趋势状态不附「60日回归 t / R² / 均线排列」推导行，
        # 指标定义脚注不出；表格数字一个不少。
        out.append(kit.sub("指数趋势与波动" if _plain() else "指数趋势与波动（统计口径）"))
        out.append(kit.table(
            ["标的", "MA20", "MA60", "RSI14", "动量z", "年化波动%", "波动分位", "趋势t"],
            rows, aligns=("left", "right", "right", "right", "right", "right",
                          "right", "right")))
        out.append(kit.kv(state_pairs))
        if not _plain():
            out.append(kit.note("动量z = 20 日收益相对自身一年分布；趋势t = 60 日回归斜率 t 值"
                                "（|t|>2 才算趋势成立）；↑↓→ 三态概率各自夹在 5%~85%，"
                                "绝不出现「0% / 100%」的假确定性。"))

    # ---- 因子贡献（恒指）----
    #    入门版整段不出：五因子 → 综合分 → 校准概率是推导过程，结论（5 日概率）已在
    #    预测表里；--notes / --full 照常输出。
    primary = res.get("primary")
    if primary and primary.get("factors") and not _plain():
        names = {"mom": "动量 MOM", "trd": "趋势 TRD", "rev": "反转 REV",
                 "vol": "量能 VOL", "flow": "资金 FLOW"}
        pairs = []
        # 动态权重说明
        feat = primary.get("feat") or {}
        dyn_reason = []
        vol_pct = feat.get("vol_pct")
        if vol_pct is not None:
            if vol_pct >= 0.80:
                dyn_reason.append(f"高波动 {vol_pct*100:.0f}% 分位 → 降 MOM 提 REV")
            elif vol_pct <= 0.15:
                dyn_reason.append(f"低波动 {vol_pct*100:.0f}% 分位 → 提 MOM/TRD 降 REV")
        t_val = feat.get("trend_t")
        if t_val is not None and abs(t_val) > 2.0:
            dyn_reason.append(f"强趋势 t={t_val:.1f} → 提 TRD 降 REV")
        align = feat.get("ma_align")
        if align is not None and abs(align) >= 2:
            dyn_reason.append(f"均线强排列 {align:+d} → 提 TRD/MOM")

        for key, label in names.items():
            v = primary["factors"].get(key)
            w = (primary.get("weights") or {}).get(key)
            base_w = None
            try:
                # 如果有动态权重的基线，显示调整
                base_w = (primary.get("feat") or {}).get("_weights_base") or {}
            except Exception:
                base_w = {}
            if v is None:
                pairs.append((esc(label), f'暂缺（权重已重分配）'))
            else:
                pairs.append((esc(label),
                              f'{v:+.2f} · 权重 {w*100:.0f}%（动态调整）'))
        out.append(kit.sub(f'{esc(primary["label"])} 五因子拆解（动态权重）'))
        if LITE:
            # 精简模式：五个因子压成一行（数值 + 权重原样保留，暂缺的仍写暂缺）
            bits = []
            for key, label in names.items():
                v = primary["factors"].get(key)
                w = (primary.get("weights") or {}).get(key)
                short_label = str(label).split(" ")[0]
                bits.append(f'{short_label} 暂缺' if v is None
                            else f'{short_label} {v:+.2f}（权重 {w * 100:.0f}%）')
            out.append(kit.kv([("五因子", " · ".join(bits))]))
        else:
            out.append(kit.kv(pairs))
        if dyn_reason:
            out.append(kit.kv([("动态权重依据", " · ".join(dyn_reason))]))
        out.append(kit.kv([("综合分 S", f'{primary["score"]:+.2f}'
                                       f' → 校准后 5 日上涨概率 '
                                       f'{prob((primary["probs"].get(5) or {}).get("p_up"))}')]))
        # 展示概率的动态修正明细
        p5 = (primary.get("probs") or {}).get(5) or {}
        adj_bits = []
        if p5.get("delta") is not None and abs(p5["delta"]) > 1e-6:
            adj_bits.append(f'流动性 {p5["delta"]*100:+.1f}pp')
        if p5.get("vol_adjust") is not None and abs(p5["vol_adjust"]) > 1e-6:
            adj_bits.append(f'波动率 {p5["vol_adjust"]*100:+.1f}pp')
        if p5.get("perf_adjust") is not None and abs(p5["perf_adjust"]) > 1e-6:
            adj_bits.append(f'表现 {p5["perf_adjust"]*100:+.1f}pp')
        if adj_bits:
            out.append(kit.kv([("概率动态修正", " · ".join(adj_bits))]))

    # ---- 个股概率表 ----
    stocks = [s for s in (res.get("stocks") or []) if s.get("probs")]
    if stocks:
        ordered = sorted(stocks, key=lambda s: -((s["probs"].get(5) or {}).get("p_up") or 0))
        # 精简模式：只列 5 日概率**最强 5 只 + 最弱 3 只**（短线客只关心两头），
        # 中间被折叠的只数如实写进小标题与脚注，--full 看全表。
        hidden_n = 0
        if LITE and len(ordered) > LITE_STOCK_HEAD + LITE_STOCK_TAIL:
            hidden_n = len(ordered) - LITE_STOCK_HEAD - LITE_STOCK_TAIL
            ordered = ordered[:LITE_STOCK_HEAD] + ordered[-LITE_STOCK_TAIL:]
        rows = []
        for s in ordered:
            f = s["feat"]
            p5 = (s["probs"].get(5) or {}).get("p_up")
            p20 = (s["probs"].get(20) or {}).get("p_up")
            flow_txt = MISS
            if s.get("main_net_yi") is not None:
                flow_txt = f'{s["main_net_yi"]:+.2f}亿'
            rows.append([
                f'{esc(s["label"])}<br>{esc(s["code"].split(".")[0])}',
                num(f.get("close"), 2),
                kit.trend(f.get("chg_pct"), compact=True),
                prob_cell(kit, p5),
                prob_cell(kit, p20),
                num(f.get("vol_ratio"), 2, comma=False),
                flow_txt,
                signal_word(p5),
            ])
        if not hidden_n:
            title = f'个股概率（{len(rows)} 只 · 按 5 日上涨概率排序）'
        elif _plain():
            title = (f'个股概率（最强 {LITE_STOCK_HEAD} + 最弱 {LITE_STOCK_TAIL} 只 · '
                     f'另 {hidden_n} 只未列）')
        else:
            title = (f'个股概率（最强 {LITE_STOCK_HEAD} + 最弱 {LITE_STOCK_TAIL} 只 · '
                     f'共 {len(stocks)} 只，按 5 日上涨概率排序）')
        out.append(kit.sub(title))
        out.append(kit.table(
            ["标的", "现价", "涨跌", "5日", "20日", "量比", "主力净额", "信号"],
            rows, aligns=("left", "right", "right", "right", "right", "right",
                          "right", "right")))
        if hidden_n and not _plain():
            out.append(kit.note(f'中间 {hidden_n} 只（概率 45%~55% 的「震荡档」）已折叠，'
                                "--full 看全表；概率是排名不是荐股，隔夜就可能换一批。"))

    # ---- 市场宽度 ----
    b = res.get("breadth") or {}
    if b.get("available"):
        out.append(kit.sub("港股宽度" if _plain() else "港股宽度（个股池统计）"))
        if LITE:
            # 精简模式：七行键值压成两行（数字一个不少，只是并排站）
            out.append(kit.kv([
                ("宽度综合分", f'<b>{b["score"]:.0f} / 100</b> · 样本 {b["n"]} 只港股蓝筹 / 科技龙头'),
                ("分项", f'站上 MA20 {pct(b["above20_pct"], 0, sign=False)} · '
                        f'MA60 {pct(b["above60_pct"], 0, sign=False)} · '
                        f'多头排列 {pct(b["bull_align_pct"], 0, sign=False)} · '
                        f'近 20 日上涨 {pct(b["up20_pct"], 0, sign=False)} · '
                        f'当日上涨 {pct(b["up1_pct"], 0, sign=False)}'),
            ]))
            return "".join(out)
        out.append(kit.kv([
            ("样本", f'{b["n"]} 只港股蓝筹 / 科技龙头'),
            ("站上 MA20", pct(b["above20_pct"], 0, sign=False)),
            ("站上 MA60", pct(b["above60_pct"], 0, sign=False)),
            ("均线多头排列", pct(b["bull_align_pct"], 0, sign=False)),
            ("近 20 日上涨", pct(b["up20_pct"], 0, sign=False)),
            ("当日上涨", pct(b["up1_pct"], 0, sign=False)),
            ("宽度综合分", f'{b["score"]:.0f} / 100'),
        ]))
    return "".join(out)


# ------------------------------------------------------------------
# ③ 资金流动性分析
# ------------------------------------------------------------------
def render_liquidity(res, kit):
    """南向 / 北向 + 量能 + 深度 + 综合评分。"""
    esc = kit.esc
    liq = res.get("liquidity") or {}
    out = []
    if not liq.get("available"):
        out.append(kit.note("本次未取到沪深港通 / 港股成交数据，资金流动性分析整体缺席。"))
        return "".join(out)

    if liq.get("summary"):
        out.append(kit.kv([("流动性概括", esc(liq["summary"]))]))

    # ---- 南北向资金 ----
    rows = []
    for key, label in (("south", "南向（港股通）"), ("north", "北向（陆股通）")):
        s = liq.get(key) or {}
        if not s.get("available"):
            rows.append([esc(label)] + [MISS] * 7)
            continue
        rows.append([
            esc(label),
            yi(s.get("latest")),
            pct(s.get("chg_pct"), 1),
            pct(s.get("vs_ma20_pct"), 1),
            yi(s.get("ma5")),
            yi(s.get("ma20")),
            num(s.get("z20"), 2, comma=False),
            (f'{s["pct60"]*100:.0f}%' if s.get("pct60") is not None else MISS),
        ])
    out.append(kit.sub("南向 / 北向资金" if _plain() else "南向 / 北向资金（成交总额口径）"))
    out.append(kit.table(
        ["方向", "最新", "环比", "vs20日均", "5日均", "20日均", "z值", "分位"],
        rows, aligns=("left", "right", "right", "right", "right", "right",
                      "right", "right")))
    south = liq.get("south") or {}
    if south.get("available"):
        out.append(kit.kv([
            ("南向解读", esc(liquidity.flow_label(south))),
            ("数据日期", esc(south.get("date") or "—")),
        ]))
    if not _plain():                 # 入门版：口径 / 政策说明脚注不出
        out.append(kit.note(esc(liq.get("policy_note") or "")))

    # ---- 量能 ----
    t = liq.get("turnover") or {}
    if t.get("available"):
        out.append(kit.sub("港股大盘成交与量能"))
        pairs = []
        if t.get("market_amount_yi"):
            pairs.append(("恒指成交额" if _plain() else "恒指成交额（东财口径）", yi(t["market_amount_yi"])))
        pairs.extend([
            ("量比（20日均量基准）", num(t.get("ratio"), 2, comma=False)),
            ("量能 z 值", num(t.get("z"), 2, comma=False)),
            ("一年分位", (f'{t["ratio_pct"]*100:.0f}%' if t.get("ratio_pct") is not None else MISS)),
            ("量能标签", esc(t.get("label") or "—")),
        ])
        out.append(kit.kv(pairs))
        if not LITE:
            out.append(kit.note("量比 / z 值由恒指成交量序列计算（相对口径，与成交额单位无关）；"
                                "成交额取东财恒指实时字段，取不到时该行缺席。"))

    # ---- 深度 ----
    d = liq.get("depth") or {}
    if d.get("amihud") is not None:
        out.append(kit.sub("流动性深度与集中度"))
        # Amihud 的绝对量级取决于指数成交量口径，**只有分位可跨期比较**，
        # 因此这里只展示分位，不展示会误导人的原始数值。
        # 入门版：标签去掉学术名，只说「交易拥挤度」+ 分位；说明脚注不出。
        pairs = [
            ("交易拥挤度" if _plain() else "冲击成本（Amihud）",
             (f'{d["amihud_pct"]*100:.0f}% 分位（越低越宽松）'
              if d.get("amihud_pct") is not None else MISS)),
        ]
        if d.get("market_amount_yi"):
            pairs.insert(0, ("恒指成交额", yi(d["market_amount_yi"])))
        if d.get("cr5") is not None:
            pairs.append(("成交额 CR5", f'{d["cr5"]:.1f}%'))
        if d.get("cr20") is not None:
            pairs.append(("成交额 CR20", f'{d["cr20"]:.1f}%'))
        if d.get("total_yi"):
            pairs.append(("样本合计成交额", yi(d["total_yi"])))
        out.append(kit.kv(pairs))
        if not _plain():
            out.append(kit.note("Amihud = 均值(|日收益| ÷ 成交额)：数值越大，同样资金造成的价格冲击"
                                "越大、流动性越差；绝对量级随口径变化，请以「分位」纵向比较。"
                                "CR5 越高说明资金越扎堆、市场广度越弱。"))
        if d.get("top"):
            out.append(kit.table(
                ["成交额前五", "成交额", "涨跌"],
                [[esc(r["name"]), yi(r["amount"] / 1e8),
                  kit.trend(r.get("chg_pct"), compact=True)] for r in d["top"]],
                aligns=("left", "right", "right")))

    # ---- 个股资金流 ----
    ff = liq.get("fundflow") or {}
    if ff.get("available"):
        out.append(kit.sub("龙头主力资金流" if _plain() else "龙头主力资金流（东财口径）"))
        out.append(kit.kv([
            ("样本", f'{ff["n"]} 只'),
            ("主力净额合计", yi(ff.get("net_total_yi"), 2)),
            ("净流入个股占比", pct(ff.get("pos_pct"), 0, sign=False)),
            ("资金广度", esc(ff.get("breadth_label") or "—")),
        ]))

    # ---- 综合评分 ----
    comps = liq.get("components") or {}
    if liq.get("score") is not None:
        out.append(kit.sub("流动性综合分"))
        out.append(kit.kv([
            ("综合分", f'<b>{liq["score"]:.0f} / 100</b> · {esc(liq["label"])}'),
        ]))
        names = {"turnover": "大盘量能", "south": "南向活跃度", "ratio": "南北向比",
                 "amihud": "冲击成本（反向）", "cr5": "集中度（反向）"}
        if comps and _plain():
            # 入门版：分项只给「名字 + 得分」，权重与依据（z 值 / 分位的推导）不出
            out.append(kit.kv([(
                "分项", " · ".join(
                    f'{esc(names.get(k, k))} {v["score"]:.0f}' for k, v in comps.items()))]))
        elif comps and LITE:
            # 精简模式：四行评分表压成一行（得分 + 权重 + 依据原样保留，只是并排站）
            out.append(kit.kv([(
                "分项", " · ".join(
                    f'{esc(names.get(k, k))} {v["score"]:.0f}（{v["weight"] * 100:.0f}% · '
                    f'{esc(v.get("note") or "—")}）' for k, v in comps.items()))]))
        elif comps:
            out.append(kit.table(
                ["分项", "得分", "权重", "依据"],
                [[esc(names.get(k, k)), f'{v["score"]:.0f}', f'{v["weight"]*100:.0f}%',
                  esc(v.get("note") or "—")] for k, v in comps.items()],
                aligns=("left", "right", "right", "left")))
    if liq.get("delta_prob") and not _plain():      # 入门版：对概率的修正属于推导过程
        out.append(kit.kv([("对概率的修正",
                            f'{liq["delta_prob"]*100:+.1f} 个百分点（量能与深度，有界 ±5pp；'
                            f'南向已计入 FLOW 因子，不重复计算）')]))
    return "".join(out)
