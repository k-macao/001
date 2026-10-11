# UZI-Skill 趋势分析栏目 · 接入说明

> 2026-10-11 新增栏目：**【游资剑鱼】UZI 多流派趋势分析**（正文顺序 02，紧跟【六眼飞鱼】量化 MACD 策略）。
> 方法来自第三方开源项目 **UZI-Skill** 的规则引擎，按本仓库「缺数据不出栏目、不用缺失值冒充中性」的口径接入。
> 纯规则研究口径，不含交易成本，**不构成投资建议**。

## 1. 装了什么

| 项 | 值 |
|---|---|
| 上游 | <https://github.com/wbh604/UZI-Skill>（游资 UZI Skills，MIT） |
| 上游提交 | `650788c54a9b2e042bf7f983f16dbf8d727fce1d`（2026-09-05，对应上游版本 v3.9.4） |
| 安装方式 | **vendor 到 `tools/UZI-Skill/`**（与 `tools/patchright-enhanced/` 同一套做法），不用 submodule、不装 pip 依赖 |
| 装了哪些文件 | `skills/deep-analysis/scripts/lib/` 下的 6 个规则引擎文件 + `__init__.py`（本地裁剪）+ `LICENSE` + `VENDORED.md` + `UPSTREAM.json` |
| 没装什么 | 上游的取数层（akshare / yfinance / baostock / 东财 / 雪球）、报告渲染、截图、personas、screen 等；本仓库日线走自己的数据线 |
| 运行时依赖 | **零**（规则引擎只用 Python 标准库；导入自检在沙箱内实测通过，未装 akshare / pandas / requests） |
| Actions 影响 | 无需改 workflow，无需 `pip install`，无需联网 |

为什么只 vendor 规则引擎：日报要的是它的**方法**（评委规则 → 加权打分 → 面板汇总），不是它的取数层。
把 1500 行的 `data_sources.py` 拉进来只会增加一份用不到的第三方网络代码。裁剪细节见 `tools/UZI-Skill/VENDORED.md`。

## 2. 栏目在算什么

```
MACD 栏目取好的同一批已收盘日线（零新增联网）
   │
   │ ① 指标重算（口径对齐上游 fetch_kline.compute_indicators）
   │    MA5/20/60/120/200 · 均线多头排列 · MACD(12,26,9) · RSI14
   │    KDJ(9,3,3) · OBV 20 日方向 · Williams%R(14) · Weinstein 四阶段
   │    距 60 日高低点 · 区间收益 · 年化波动 · 最大回撤
   ▼
features（只放**算得出来**的键；算不出来的键整条缺席）
   │
   │ ② 规则可评估性筛选：规则引用的特征是否全部在场？不在场 → 整条规则出局
   │ ③ 评委准入门禁：可评估规则 ≥2 条且权重占比 ≥50%，否则整位评委撤下并点名
   ▼
lib.investor_evaluator.evaluate(investor_id, features)   ← 上游规则引擎，未重写
   │
   ▼
逐评委得分 / 命中 / 未达 + 面板汇总 + 趋势定调 → 独立栏目 HTML
```

**趋势定调**（`_verdict`，规则合成、可复现）：

| 条件 | 定调 |
|---|---|
| Stage 2 且 ≥60% 评委看多 | 多头趋势成立 |
| Stage 2 但评委分歧 | 上升但分歧 |
| Stage 1 | 底部构筑 |
| Stage 3 | 高位转弱 |
| Stage 4 | 空头趋势 |
| MA200 斜率窗口不足 | 阶段未定（不定调，并说明差多少根日线） |

## 3. 为什么只启用 5 位评委 / 14 条规则

上游 66 位评委共 242 条规则。用字节码静态读出每条规则 `check` 引用的特征键后统计（脚本可复现，
见 `tests/test_uzi_trend.py` 的口径断言）：

- 输入**全部**来自已收盘日线的规则：**37 条 / 28 位评委**；
- 其余 205 条依赖财报、估值、资金流、股东、舆情、龙虎榜等本栏目**不采集**的数据。

如果照单全收，上游 `evaluate()` 会把取不到的特征按 `f.get(key, 默认值)` 处理 —— 缺数据被当成
「不达标」扣分。实测：只喂价格特征时，66 位评委里 33 位给出 `bearish`，包括「净利增速 ?% < 25%」
这种根本没有数据的判断。这类分数没有意义，所以本栏目做了两层收口：

| 门禁 | 规则 | 效果 |
|---|---|---|
| 规则级 | 规则引用的特征本次必须**全部算得出来**，否则整条不参与打分 | 不会出现「用 0 顶替后判不达标」 |
| 评委级 | 可评估规则 ≥ `MIN_PANEL_RULES`(2) 条，且其权重 ≥ 该评委规则总权重 × `MIN_COVERAGE`(0.5) | 不会用 1 条规则代表一整套方法论（如江恩只剩「波动率正常」一条时不会给 100 分看多） |

默认名单（每位评委的**全部**规则都能用价格数据评估，合计 14 条 / 权重 46）：

| 评委 | 流派 | 规则 | 权重 |
|---|---|---|---|
| 利弗莫尔 | D 技术趋势派 | Stage 2 上升期 · 均线多头排列 · 接近高点但未超买 | 11 |
| 米内尔维尼 | D 技术趋势派 | 严格 Stage 2 · MA 多头堆叠 · 距 52 周高点 <25% · YTD 相对强度 · RSI 未严重超买 | 16 |
| 达瓦斯 | D 技术趋势派 | 趋势向上（Stage 2）· 均线支撑 | 8 |
| 江恩 | D 技术趋势派 | 趋势向上 · 波动率正常(<60%) | 6 |
| 西蒙斯 | G 量化派 | 统计信号（近 1 年正收益）· 波动率可交易 | 5 |

另有 23 位评委存在价格类规则（多为游资的「Stage 2 才看」单条前置规则，以及欧奈尔 / 索罗斯 / 大卫·肖的
1~2 条趋势规则），但可评估权重占其规则总权重不足 50%，默认不进面板。需要时用
`OCTOPUS_UZI_PANEL=all` + `OCTOPUS_UZI_MIN_COVERAGE=0` 放开（栏目会逐条披露参与与撤下情况）。

KDJ / OBV / Williams%R / MACD 是**同口径展示项**：上游 242 条规则里没有任何一条引用它们，
所以它们只出现在指标行，不参与打分（栏目里明写这一点）。

## 4. 与上游的三处口径差异（都在栏目「指标口径」行披露）

1. **指标本地重算**。上游指标在 `scripts/fetch_kline.py::compute_indicators`，该文件 import
   akshare / data_sources（重依赖 + 联网），未 vendor；本仓库按同一组公式在
   `output/octopus_quant/uzi_trend.py` 重算，输入只用本次已收盘日线。
2. **均线要求满窗口**。上游 `_ma` 用「部分窗口均值」（60 根日线也能算出 MA120）；本仓库要求满窗口
   （MA120 需 ≥120 根，多头排列同门槛；MA200 需 ≥200 根），不足则该指标缺席。
   Weinstein 阶段因此需要 ≥`STAGE_MIN_BARS`(220) 根，且 MA200 斜率窗口取
   `min(60, 可用 MA200 历史)`、下限 20 根（1 年日线约 252 根 → 约 52 根斜率窗口）。
3. **区间收益窗口如实披露**。上游 `ytd_return` 实为「回看 252 根日线的收益」（不是日历年初至今）；
   本仓库满 252 根时用 252，不足则回看全部可用日线（下限 120 根），并在页面写成「近 N 日 ±x%」。

## 5. 数据边界

- **零新增联网**：日线由 `fetch_macd_strategy()` 取好后经私有键 `_bars_by_code` 直接交给
  `fetch_uzi_trend()`，用完即弹出，不写进 `data`、不进 JSON 留痕、不进日报 HTML。
  同一批标的、同一来源、同一复权口径，不会出现「MACD 用 A 源、趋势用 B 源」。
- **MACD 栏目关闭 → 本栏目缺席**（`OCTOPUS_MACD=0` 时不编造日线）。
- 排除未收盘日线；最新日线滞后超过 `MAX_LAG_DAYS`(4) 天不发信号。
- 指数常无成交量 → OBV 整项缺席（不当成「资金流出」）。
- 某只标的日线不足 → 少一行 + 在「缺项」点名原因；全部不足 → 整栏缺席，不占位。
- 规则引擎（`tools/UZI-Skill`）缺失或导入失败 → 整栏缺席，日志点名原因。

## 6. 开关

| 变量 / 参数 | 作用 |
|---|---|
| `OCTOPUS_UZI_TREND=0` / `--no-uzi-trend` | 关闭整栏（关闭时不写 data 键，审计口径不变） |
| `OCTOPUS_UZI_PANEL` | `default`（默认 5 位）/ `all`（全部有价格类规则的评委）/ `gann,darvas` 指定 |
| `OCTOPUS_UZI_MIN_COVERAGE` | 评委准入门禁的权重占比阈值，默认 `0.5` |
| `OCTOPUS_UZI_SKILL` | 指向另一份 UZI-Skill 的 `skills/deep-analysis/scripts` 目录 |
| `OCTOPUS_UZI_SYMBOLS` | 覆盖观察池，语法同 `OCTOPUS_MACD_SYMBOLS`（默认与 MACD 同一批 9 只指数） |

版面：入门版（默认）只留结论表 + 每标的一句评委结论 + 定调 + 暂缺；`--notes` / `--full` 补齐
逐评委命中与未达、规则覆盖、被门禁撤下的评委、评委档案（持仓周期 / 翻盘条件）与方法来源。

## 7. 本地验证

```bash
python3 -m pip install requests pytest
python3 -m pytest tests/test_uzi_trend.py -q          # 34 项离线回归
python3 -m pytest tests -q                            # 全量回归
```

`tests/test_uzi_trend.py` 覆盖：规则引擎装载（66 评委 / 242 规则）与缺席降级、满窗口均线与
Weinstein 四阶段、缺数据时规则整条出局与评委整位撤下、`run_trend` 的覆盖 / 缺项 / 定调、
五套主题渲染、入门版与全量版差异、HTML 转义、私有日线键用完即弃、栏目在正文中的位置与
缺席时的数据覆盖点名。

## 8. 同步上游

见 `tools/UZI-Skill/VENDORED.md` 末尾的同步步骤：拷贝 6 个 lib 文件 → 保持本地裁剪的
`__init__.py` → 更新 `UPSTREAM.json` 的提交号与日期 → 重跑 `tests/test_uzi_trend.py`
（其中 `test_vendored_engine_is_loaded_with_full_roster` 会对提交号与「66 / 242」计数做断言，
上游一改就会红，提醒复核规则变化）。
