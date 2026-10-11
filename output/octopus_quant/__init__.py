#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🐙 章鱼 AI · 港股量化引擎（概率预测 / 资金流动性 / 全过程校验）

分层结构（每层只依赖下层，可单独离线测试）：

    ① providers   数据层    Yahoo 日线 + 东财沪深港通 / 港股成交 / 主力资金流
    ② features    特征层    动量 MOM / 趋势 TRD / 反转 REV / 量能 VOL / 资金 FLOW
    ③ probability 概率层    滚动重算 → 分桶 + 保序(PAVA) + 逻辑回归校准 → 推进式回测
    ④ liquidity   流动性层  南向北向 / 大盘量能 / Amihud 深度 / 集中度 → 综合分与修正
    ⑤ engine      编排层    collect → features → probability → liquidity → validate → decide
    ⑥ render      呈现层    结果字典 → HTML（排版由 pipeline 的 kit 注入，兼容两套主题）

外加**反馈闭环**：每次预测写入 ``output/quant_history.json``，之后每次运行自动用
真实收盘结算「方向命中 / 区间命中 / Brier」，模型表现自己记账。

离线使用（回测 / 研究，不发任何网络请求）::

    from octopus_quant import run_series_study      # 见 engine.run_series_study

产品使用（由 pipeline 调用）::

    from octopus_quant import run_quant
    result = run_quant(safe_request)

约定：抓不到的数据一律返回 None / 空，并显式标注「暂缺」；
      绝不用历史数字冒充实时数据，绝不编造净买入。
"""
from __future__ import annotations

from . import (features, industry_rotation, liquidity, macd_derivatives, macd_strategy,
               probability, providers, render, sector_rotation, stats, trend_jury)
from .engine import (FORECAST_HORIZONS, JOURNAL_FILENAME, VALIDATE_HORIZONS,
                     QuantEngine, run_quant)

__all__ = [
    "features", "industry_rotation", "liquidity", "macd_derivatives", "macd_strategy",
    "probability", "providers", "render", "sector_rotation", "stats", "trend_jury",
    "QuantEngine", "run_quant",
    "FORECAST_HORIZONS", "VALIDATE_HORIZONS", "JOURNAL_FILENAME",
]

__version__ = "1.0.0"
