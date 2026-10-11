"""Shared library for stock-deep-analyzer fetcher scripts.

⚠️ 本仓库（k-macao/02）本地裁剪版：上游原文件还会 import `.cache` / `.market_router` /
`.data_sources`（akshare / yfinance / requests 的取数层）。日报流水线只复用**规则引擎**
（评委规则 + 打分 + 面板汇总），取数一律走本仓库自己的数据线，因此这里去掉三个取数模块的
导入，避免把用不到的第三方依赖面拉进日报运行时。其余文件与上游逐字一致。
详见 tools/UZI-Skill/VENDORED.md。
"""
from . import seat_db, investor_db

__all__ = ["seat_db", "investor_db"]
