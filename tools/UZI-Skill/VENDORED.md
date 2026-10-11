# VENDORED —— 本目录是 UZI-Skill 的本地镜像（只取规则引擎）

| 项 | 值 |
|---|---|
| 上游仓库 | <https://github.com/wbh604/UZI-Skill> |
| 上游提交 | `650788c54a9b2e042bf7f983f16dbf8d727fce1d`（2026-09-05，`feat: align daily screening with verifiable public market data`，对应上游版本 v3.9.4） |
| 拉取日期 | 2026-10-11（北京时间） |
| License | 上游 MIT（`Copyright (c) 2026 Float Future`），License 全文见本目录 `LICENSE` |
| 本地改动 | ① 新增 `VENDORED.md` / `UPSTREAM.json`；② `skills/deep-analysis/scripts/lib/__init__.py` 去掉 `.cache` / `.market_router` / `.data_sources` 三个**取数层**模块的导入（这三个文件未 vendor）。其余 6 个文件与上游逐字一致 |

## 为什么只 vendor 这 7 个文件

日报流水线要的是 UZI-Skill 的**方法**——「评委规则 → 加权打分 → 面板汇总」这套可追溯的
规则引擎，不是它的取数层（akshare / yfinance / 东财 / 雪球，需要 pandas、requests 等重依赖，
且与本仓库自己的数据线重复）。所以本地只保留纯标准库的规则引擎闭包：

```
skills/deep-analysis/scripts/lib/
├── __init__.py            ← 本地裁剪（去掉取数层导入）
├── investor_db.py         66 位评委名册（id / 中文名 / 流派分组 A-I）
├── investor_criteria.py   242 条量化规则（Rule: rule_id / name / weight / check / pass_msg / fail_msg）
├── investor_evaluator.py  evaluate() / evaluate_all() / panel_summary() —— 规则打分与面板汇总
├── investor_knowledge.py  reality_check()：市场 / 能力圈 / 已知持仓前置判断
├── investor_profile.py    每位评委的持仓周期 / 仓位风格 / 「什么会让他翻盘」
└── seat_db.py             F 组游资射程表（本仓库栏目未启用 F 组）
```

导入自检（沙箱内实测，未装 akshare / pandas / requests）：

```bash
python3 -c "import sys; sys.path.insert(0,'tools/UZI-Skill/skills/deep-analysis/scripts'); \
from lib.investor_evaluator import evaluate, panel_summary; \
from lib.investor_criteria import INVESTOR_RULES; print(sum(len(v) for v in INVESTOR_RULES.values()))"
# → 242
```

## 谁在用它

`output/octopus_quant/uzi_trend.py`（【游资剑鱼】UZI 趋势分析栏目的算法层）：

```
本次已收盘日线（复用 MACD 栏目同一批，零新增联网）
        │  指标：Weinstein 四阶段 / 均线多头排列 / MACD / RSI14 / KDJ / OBV / Williams%R / 波动 / YTD
        ▼
features（只放**算得出来**的键；算不出来的键整条缺席）
        │  lib.investor_evaluator.evaluate(investor_id, features)   ← 上游规则引擎，未重写
        ▼
逐评委得分 + 面板汇总 → 独立栏目 HTML
```

指标口径对齐上游 `skills/deep-analysis/scripts/fetch_kline.py::compute_indicators`
（该文件依赖 akshare，未 vendor，故按原公式在本仓库重写；差异见
`output/octopus_quant/uzi_trend.py` 顶部注释）。

## 边界与诚实口径

- **不联网、不装依赖**：规则引擎只用标准库；栏目在 Actions 里照常跑，不需要 `pip install`。
- **缺数据不打假分**：某条规则引用的特征本次算不出来（例如日线不足 200 根 → 无 MA200 →
  Weinstein 阶段未知），该规则**整条不参与打分**，绝不用 `0` / 中性值顶替后判「不达标」。
  每只标的都会在栏目里披露「参与 N 条 / 未参与 M 条」。
- **只用价格类规则**：242 条里只有 37 条的输入全部来自已收盘日线（28 位评委）；其余 205 条
  依赖财报 / 估值 / 资金 / 舆情等本栏目不采集的数据，默认不进面板
  （`OCTOPUS_UZI_PANEL=all` 可放开到全部价格类规则，仍不碰缺数据的规则）。
- **不是投资建议**：评委打分是规则合成的研究口径，不含交易成本，也不预测点位。

## 如何同步上游

```bash
git clone --depth 1 https://github.com/wbh604/UZI-Skill.git /tmp/uzi
cd /tmp/uzi && git log -1 --format='%H %ad %s' --date=short      # 记下新提交
for f in investor_db investor_criteria investor_evaluator investor_knowledge investor_profile seat_db; do
  cp skills/deep-analysis/scripts/lib/$f.py \
     /path/to/02/tools/UZI-Skill/skills/deep-analysis/scripts/lib/$f.py
done
# __init__.py 保持本地裁剪版；更新 UPSTREAM.json 的 commit / 日期 / 版本，并重跑 tests/test_uzi_trend.py
```
