# VENDORED —— 上游 UZI-Skill（游资 Skills）的本地镜像与移植说明

| 项 | 值 |
|---|---|
| 上游仓库 | <https://github.com/wbh604/UZI-Skill> |
| 上游分支 / 提交 | `main` · `650788c54a9b2e042bf7f983f16dbf8d727fce1d`（2026-09-05，`feat: align daily screening with verifiable public market data`） |
| 上游版本 | v3.9.4（见 `SKILL.md` / `package.json`） |
| 拉取日期 | 2026-10-11（北京时间） |
| License | MIT（上游 `LICENSE`） |
| 安装方式 | `bash tools/install_uzi_skill.sh`（默认 clone 到 `vendor/UZI-Skill`，该目录已 gitignore，不进版本库） |
| 本地改动 | **无**。本目录只有本文档；上游源码一律原样保留在 `vendor/` 下，不 fork、不改 |

## 为什么不把上游整个塞进版本库

上游是一个**独立的 CLI / 插件**（Claude Code / Codex / Cursor / OpenCode / Gemini 通用），
入口 `run.py <ticker>`，依赖 `akshare` / `yfinance` / `baostock` / `playwright` / `ddgs` 等
（见上游 `requirements.txt`），跑一次是个股深度研究：22 维取数 → 66 位投资人评委
role-play → 22 种机构方法建模 → Bloomberg 风 HTML 报告。

本仓库是**每日定时跑的日报流水线**（GitHub Actions · 零密钥 · 只读免费公开源），
两者运行形态不同：

- 把上游 1.5 万行引擎塞进版本库，等于引入一条我们不会维护的依赖树；
- 上游默认取数走 akshare，本仓库的取数口径是「市场库 → 本次已有日线 → Yahoo / 东财主备链」，
  混用会出现两套数据源与两套备用源审计，违背本仓库「同一批实参、不另算一套」的既有约定；
- 沙箱 / Actions 环境没有装上游依赖，也不该为了一个栏目去装。

因此只**移植方法**，代码落在 `output/octopus_quant/trend_jury.py`（自研、零新依赖、可离线测试），
上游保留在 `vendor/` 供随时对照与按需运行。

## 移植对照表（上游方法 → 本地实现）

| 上游位置 | 方法 | 本地落点（`output/octopus_quant/trend_jury.py`） |
|---|---|---|
| `skills/deep-analysis/scripts/lib/investor_criteria.py` | `Rule(rule_id, name, weight 1–5, check, pass_msg, fail_msg)` 带权重规则库 | `Rule` dataclass + 12 位方法评委 × 54 条规则（`JUDGES`） |
| `.../lib/investor_evaluator.py` | 三层裁决：能力圈 → 规则引擎 → 合成；`score = 权重通过率 ×100`；`≥65 bullish / <35 bearish`；置信度按参与规则数与极端度 | `evaluate_judge()`（阈值常量 `BULLISH_THRESHOLD` / `BEARISH_THRESHOLD` 逐字沿用） |
| `.../lib/investor_evaluator.py::_safe_check` | 数据缺失 → 返回 `None` → **skip，不占分母**（缺数据不等于不达标） | `_rule()` + `_known()`：规则声明 `dims`，任一维度缺失即 skip；可评权重覆盖率 < 60% 整位评委 skip |
| `.../lib/investor_evaluator.py`（`SCHOOL_LABELS`）+ `--school` + `_render_school_lock_banner` | 流派分组与「单一流派视角」锁定 banner，防止被误读为全体结论 | `SCHOOLS`（A 趋势跟随 / B 阶段均线 / C 强度动量 / D 量能确认 / E 市场环境 / F 风险纪律）· `OCTOPUS_TREND_SCHOOL=A..F` · 正文顶部「流派锁定」行 |
| `.../lib/data_integrity.py`（`CRITICAL_CHECKS`） | 关键字段体检：缺失即告警 / 降级，不猜 | `DIMENSIONS` 的 `critical` 标记 + `prepare_row()` 闸门（缺关键维直接 `available=False` 并写原因） |
| `skills/deep-analysis/SKILL.md` 硬性门控 4/5（禁空泛话术、矛盾必须呈现） | 禁用「基本面良好 / 值得关注 / 前景广阔」；DCF 与 Comps 冲突时把冲突写进报告；The Great Divide 多空对撞 + punchline | `BANNED_PHRASES` / `fluff_check()` / `punchline()` / `great_divide()`（命中禁用词记 warning 并降级为定量句） |
| `skills/deep-analysis/assets/quality-checklist.md` | 报告出稿前逐项自检清单 | `self_check()`：9 条不变量（评审池、每人 ≥4 规则、规则数与注册表一致、8 信号齐备、无空泛话术……），未过项在控制台与正文点名 |
| `skills/trap-detector` + `scripts/fetch_trap_signals.py` | 8 信号扫描，每格必须「命中 / 未命中 / 数据不足」 | `RISK_SIGNALS`（趋势失效风险 8 信号）+ `scan_risks()` |
| `.../lib/personas/*.yaml` + `HARD-GATE-PERSONA-ROLEPLAY` | 66 位真人投资人 persona（需要大模型 role-play） | **不移植**：日报是无人工、无大模型的确定性流程，故把「人」换成「公开可查证的方法框架」（Minervini Trend Template、Darvas 箱体、Livermore 关键点、Gann 时间窗、海龟通道、O'Neil 相对强度、Weinstein 四阶段…），规则即该框架原始判据 |
| `.../lib/pipeline/score_fns.py` / `compute_deep_methods.py` | 22 种机构分析方法（DCF / LBO / 3-Stmt / VCP / 单位经济……） | **不移植估值与财务建模**（需要财报数据）；只取其中纯价格可算的趋势方法：Trend Template、VCP 收缩、箱体、时间窗、量能确认、相对强度、回撤纪律 |
| `.../assets/data-contracts.md` | Task 间 JSON 契约 + `methodology_log` 可审计推导链 | 行内 `log`（Step 1–6 推导链）+ `parameters` / `coverage` / `missing` / `warnings` 全量随正文出（全量模式） |
| 上游 `run.py` 取数层（akshare / yfinance / baostock） | 22 维 fetcher 与备用源 | **不移植**：改用本仓库既有取数阶梯（市场库 → 本次量化日线 → Yahoo / 东财主备链，`providers.fetch_bars`），备用源命中沿用 `backup_sources` 审计 |

## 与日报的接口（本仓库侧）

```
output/pipeline.py::collect_all_data()
        └─ fetch_trend_jury(data)                      # 采集阶段唯一取数点
             └─ octopus_quant.trend_jury.run_trend()   # 取数阶梯 + 18(32) 维 + 评委裁决
                  └─ render_jury(result, kit)          # 呈现层（五套主题共用 kit）
                       └─ 栏目【深海剑鱼】趋势多维评审团（kicker TREND JURY）
```

开关与口径：

| 项 | 值 |
|---|---|
| 栏目开关 | `OCTOPUS_TREND_JURY=0` 整栏关闭（不进正文、不进数据审计、总源数不变） |
| 标的池 | `OCTOPUS_TREND_SYMBOLS="^HSI:恒生指数,0700.HK:腾讯控股"`（默认 9 只大盘指数，最多 12 只） |
| 流派锁定 | `OCTOPUS_TREND_SCHOOL=A..F` |
| 数据闸门 | ≥120 根已收盘日线；滞后 > 4 个自然日不进评审并在缺项点名 |
| 回归 | `tests/test_trend_jury.py`（49 项，全离线） |

## 边界与诚实口径

- **只借方法，不借数据**：本栏目所有数字都来自本仓库当次已抓到的日线与环境读数；
  上游的 akshare 明细（财报、龙虎榜、股东、研报）一概不参与。
- **不做 role-play、不编观点**：评委是规则函数，输出可复现；同输入必同输出。
- **数据不足 = skip，不是看空**：缺维度的规则不占分母，覆盖率不足 60% 的评委整位跳过，
  并在正文「数据卡覆盖」里点名缺了哪些维度。
- **概率封顶**：置信度上限 95，定调不使用绝对化措辞（与日报「概率夹在 5%–95%」同口径）。
- **不构成投资建议**：上游与本仓库均是规则研究工具，不是持牌投资建议。
