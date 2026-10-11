# UZI-Skill 安装 + 趋势分析栏目（【深海剑鱼】趋势多维评审团）

> 任务：安装 <https://github.com/wbh604/UZI-Skill>，并以它的方法方案在本日报里
> 增加一个**独立显示**的趋势分析栏目。
> 完成时间：2026-10-11（北京时间）· 分支 `arena/0f6e648f-02` · 零新依赖、零密钥。

## 结论一览

| 交付项 | 状态 | 落点 |
|---|---|---|
| 安装上游 UZI-Skill | ✅ 已装（v3.9.4 · `650788c` · MIT），并给出可重复安装脚本 | `tools/install_uzi_skill.sh` → `vendor/UZI-Skill`（已 gitignore） |
| 上游镜像与移植对照 | ✅ | `tools/uzi-skill/VENDORED.md` |
| 趋势分析方法移植（规则引擎 + 评委 + 闸门） | ✅ 自研确定性模块 | `output/octopus_quant/trend_jury.py`（约 1500 行） |
| 独立栏目（正文自己的 `<section>`） | ✅ 第 12 栏，专业分析组末位 | `【深海剑鱼】趋势多维评审团` · kicker `TREND JURY` |
| 采集接线 + 数据审计 + 逐栏 AI 研判 | ✅ | `output/pipeline.py`（`fetch_trend_jury` / ④b / ⑥b / `LITE_LIMITS` / 三套主题图标） |
| 社区版渲染接入 | ✅ | `output/octopus_ren.py` · `_ren_trend_jury`（生成器 `TREND JURY`） |
| 离线回归测试 | ✅ 50 项 | `tests/test_trend_jury.py` |
| README 栏目说明 | ✅ | README.md「栏目阅读顺序」+ 专业策略组表格 |

一句话：**上游本体不跑在日报里，日报跑的是把它的方法逐条移植出来的确定性模块**——
这样 GitHub Actions 零密钥环境每天都能出这一栏，且同输入必同输出。

---

## ① 安装

上游是一个多平台通用的「个股深度分析」skill/插件（Claude Code / Codex / Cursor / OpenCode /
Gemini / Hermes），入口 `python3 run.py <代码> --no-browser`，重依赖
`akshare` / `yfinance` / `baostock` / `playwright` / `ddgs`。

安装动作：

```bash
cd /home/user/02
bash tools/install_uzi_skill.sh                  # clone / 更新到 vendor/UZI-Skill
bash tools/install_uzi_skill.sh --ref main --deps --verify   # 顺带装依赖并跑 run.py --help
```

脚本行为：存在则 `fetch + checkout FETCH_HEAD`（幂等更新）、支持 `--dest` 装到仓库外、
`--ref` 可钉分支 / 标签 / 40 位提交；只访问 `github.com` / `pypi.org`，**取不到就报错退出，
不会伪造「已安装」**；结束时打印提交号、日期、上游版本与 License。

本次安装记录：

| 项 | 值 |
|---|---|
| 上游提交 | `650788c54a9b2e042bf7f983f16dbf8d727fce1d`（2026-09-05） |
| 提交标题 | `feat: align daily screening with verifiable public market data` |
| 版本 / License | v3.9.4 / MIT |
| 镜像位置 | 本机参考副本在仓库外（`/home/user/UZI-Skill`）；按脚本装则在 `vendor/UZI-Skill` |
| 是否进版本库 | 否（`.gitignore` 新增 `vendor/`）；上游源码一律原样保留、不 fork 不改 |

为什么不把 1.5 万行上游引擎连同它的依赖树塞进日报仓库：见
`tools/uzi-skill/VENDORED.md`「为什么不把上游整个塞进版本库」（两套取数口径、两套备用源审计、
CI 环境依赖、维护责任四条），以及本仓库「同一批实参、不另算一套」的既有约定。

需要上游完整能力（DCF / LBO / 三表建模、龙虎榜、杀猪盘扫描、Bloomberg 风 HTML 报告）时：

```bash
cd vendor/UZI-Skill && python3 run.py 00700 --no-browser        # 单流派视角：--school F
```

---

## ② 移植了哪些方法（上游 → 本栏目）

完整对照表在 `tools/uzi-skill/VENDORED.md`，这里是口径摘要：

1. **带权重量化规则库 + 规则引擎裁决**
   `Rule(rule_id, name, weight 1–5, check(features) → bool, pass_msg, fail_msg)`；
   评委只读 `features` 字典，**从不直接读原始抓取结果**。
   本栏目实现为 **12 位方法评委 × 54 条规则 × 6 个流派**；
   得分 = 命中权重 / 可评权重 × 100，`≥65 → bullish`、`<35 → bearish`（阈值逐字沿用上游），
   置信度 = 覆盖率与极端度的合成，封顶 95。
2. **数据不足 = skip，不占分母**（上游 `_safe_check` 的核心口径）
   每条规则声明它需要的维度，任一维度缺失即 skip；可评权重覆盖率 <60% 的评委**整位跳过**。
   绝不把「没取到数据」渲染成「看空」。
3. **流派分组与单一流派锁定**（上游 `SCHOOL_LABELS` + `--school` + 锁定 banner）
   `A 趋势跟随 / B 阶段均线 / C 强度动量 / D 量能确认 / E 市场环境 / F 风险纪律`；
   `OCTOPUS_TREND_SCHOOL=A..F` 只评该流派，其余评委记 skip，栏目顶部出「流派锁定」行，
   避免被误读成全体评委结论。
4. **数据完整性闸门**（上游 `data_integrity.CRITICAL_CHECKS`）
   ≥120 根已收盘日线；关键维度（收盘价 / MA50 / 均线排列 / 20 日动量 / 箱体上沿 / 趋势 t 值）
   缺任何一个 → 整行不进评审并写明原因；滞后 >4 个自然日 → 不进评审并在缺项点名。
5. **The Great Divide（多空对撞）**
   最强多头评委 vs 最强空头评委并置，必须给出分差；`punchline()` 一句定调**必须带数字**。
   评委分歧熵（多空二元 Shannon 熵，与【麻辣大龙虾】栏同算法）本身进正文——分歧越大，
   定调越要保守。
6. **禁用空泛话术 + 出稿自检**（上游 HARD-GATE 与 `quality-checklist.md`）
   「基本面良好 / 值得关注 / 前景广阔 / 建议重视 / 存在一定风险」出现即 `self_check` 失败；
   另有 9 条不变量（评审池非空、每位评委 ≥4 条规则、规则总数与注册表一致、逐标的带裁决明细、
   每行带维度覆盖率、8 信号齐备、定调含具体数字、无空泛话术、缺数据标暂不冒充中性）。
7. **8 信号风险扫描**（上游 trap-detector「每格必须标」）
   移植成趋势语境的「趋势失效风险 8 信号」，每格只能取 **命中 / 未命中 / 数据不足** 三态，
   命中必须附证据（如假突破：突破 20 日关键位后 N 根内跌回该关键位下方；
   突破日「当时」的枢轴价才是基准，不能用今天的 20 日高点——突破本身会把它抬高）。
8. **可审计推导链**（上游 `data-contracts.md` 的 `methodology_log`）
   每行随正文带 Step 1–6（取数 → 维度 → 裁决 → 截面 → 定调 → 自检）与
   `parameters` / `coverage` / `missing` / `warnings`（全量模式可见）。

**不移植的部分**：真人投资人 persona 的 LLM role-play（日报是无大模型的确定性流程，
故把「人」换成该投资人公开可查的方法框架：Livermore 关键点、Darvas 箱体、Gann 时间窗、
海龟通道、Minervini Trend Template + Stage-2 硬门、Weinstein 四阶段、O'Neil 相对强度…），
以及需要财报的估值建模（DCF / LBO / 三表）与上游 akshare 取数层。

---

## ③ 栏目长什么样

**位置**：专业分析组最后一栏（美联储 / 地缘政治之后、数据显示组之前），有数据才渲染。
**标题**：`【深海剑鱼】趋势多维评审团` · kicker `TREND JURY` · 图标 `◭`（像素版）/ `▲`（档案版）/ `🧭`（社区版）。

正文五块（自上而下）：

| 块 | 内容 | 精简模式 |
|---|---|---|
| 概览表 | 趋势定调（带色符号 + 分档）、评委投票票型、分歧熵、数据覆盖、一句话定调 | 全出 |
| 逐标的趋势卡 | 趋势分 / 定调 / 阶段（Weinstein Stage 1–4）/ 20 日动量 / 箱体位置 / 评委票型 | 最多 4 行（`LITE_LIMITS["jury_rows"]`），其余计数「另有 N 只未列出」 |
| 评委打分板 | 12 位方法评委在本池的平均分、票型、置信度 | 最多 6 行（`jury_verdicts`） |
| 重点裁决 | 分歧最大标的的多空对撞 + 12 位评委逐条裁决与首条证据 | 仅全量模式 |
| 趋势失效风险 | 8 信号三态扫描（命中必附证据） | 仅全量模式 |
| 数据卡覆盖 | 每行维度覆盖 X/32 与缺失维度点名 | 仅全量模式 |

定调分档：`≥72 ▲ 强多头` / `≥58 △ 偏多` / `42–58 ■ 中性` / `28–42 ▽ 偏空` / `<28 ▼ 强空头`。

取数与复用口径：

- 行情阶梯与【六眼飞鱼】MACD 栏**完全一致**：市场库 → 本次已有日线 → Yahoo / 东财免费主备链，
  整段选源、绝不拼接不同源或复权口径；抓不到就少一行，并在缺项写明原因。
- 「市场环境派」用的 7 个市场级维度（涨跌家数、成交额环比、板块净强弱、流动性分、
  社区净情绪、标题多空、头条净值）**全部复用日报本次已抓到的同一批实参**，
  不新取数、不用均值或 0 补位；对应路由缺席 → 该维度缺席 → 相关规则 skip。
- 无新增网络请求数（`fetch_trend_jury` 只读 `data["港股量化"]` 等已有对象）。

实际运行输出（控制台）：

```
🧭 正在计算趋势多维评审团（UZI 方法移植：市场库 → 已有日线 → Yahoo/东财免费源）...
  ✅ 趋势评审团：3/3 只 · 维度 91/96 · 定调 ■ 56.4（中性）· 评委 多14 / 空12 / 跳0
```

逐栏 AI 研判里新增一行：

```
3 只标的 · 方法评委看多 13 / 看空 10 / 中性 10 / 数据不足 3（分歧熵 99/100）
 → 预测：■ 中性 · 趋势分 56.7
```

---

## ④ 开关与配置

| 环境变量 / 参数 | 默认 | 作用 |
|---|---|---|
| `OCTOPUS_TREND_JURY` | `1` | 置 `0/false/no` 整栏关闭：不进正文、不进数据覆盖审计、总源数不变 |
| `OCTOPUS_TREND_SYMBOLS` | 9 只大盘指数 | 自定义标的池，`"^HSI:恒生指数,0700.HK:腾讯控股"`，去重、最多 12 只 |
| `OCTOPUS_TREND_SCHOOL` | 空 | `A`–`F` 锁定单一流派视角（其余评委 skip，正文顶部出锁定提示） |
| `--lite` / 默认精简 | 精简 | 标的表 4 行、打分板 6 行，重点裁决与风险扫描不出 |
| `--full` / `--notes` | — | 全量长版；`--notes` 恢复说明性文字 |

默认标的池：`^HSI` 恒生指数、`^HSTECH` 恒生科技、`^HSCEI` 国企指数、`000001.SS` 上证指数、
`399001.SZ` 深证成指、`399006.SZ` 创业板指、`^DJI` 道指、`^GSPC` 标普 500、`^IXIC` 纳指。
选它是因为这三段市场（港股 / A股 / 美股）的指数日线在本仓库免费源最稳定，
截面相对强度也在这同一批可比标的内部计算，不跨源混算。

---

## ⑤ 验证记录

| 验证 | 命令 | 结果 |
|---|---|---|
| 本栏目离线回归 | `cd tests && python3 -m unittest test_trend_jury` | **Ran 50 tests … OK**（全离线、假数据确定性） |
| 全仓库回归 | `python3 -m unittest discover -s tests -p "test_*.py"` | `Ran 848 tests … FAILED (failures=1, skipped=1)`（新栏目的测试已并入 848） |
| 唯一失败项 | `test_sector_rotation.PipelineAndFreshnessTests.test_collection_uses_concept_and_market_inputs_without_live_network` | **与本次改动无关**：`assertTrue(source["is_today"])`，夹具日期 2026-09-30 距系统日期 2026-10-11 已超过 `MAX_LAG`。已用 `git stash` 回到干净树复现同一失败，属日期漂移的既有问题 |
| 五套主题渲染 | `test_both_modes_and_themes_render`（LIME / GUIZANG / PIXEL / FORUM / DOSSIER × 精简 / 全量） | 通过；精简版严格短于全量版 |
| 栏目顺序 | `REPORT_SECTION_ORDER` 内 `TREND JURY` 位于专业分析组末位 | 通过 |
| 审计计数 | 启用时数据覆盖审计总源数 +1；关闭时源名、计数、`backup_sources` 一律不出现 | 通过 |
| 异常降级 | `fetch_trend_jury` 内部异常 → 该源标 `unavailable` 且不炸整份日报 | 通过 |
| 话术闸门 | 禁用词命中即自检失败；定调句必含数字 | 通过 |

注：本沙箱没有 `akshare`、也没有 Yahoo / 东财的外网出口，所以**没有跑通一次真实联网日报**；
联网路径沿用【六眼飞鱼】已验证过的同一份 `providers.fetch_bars` 阶梯，接线部分另用
「已有日线 + 已有环境读数」的离线注入跑通（含 `build_report` 全链路渲染自检）。

---

## ⑥ 边界（这一栏明确不做什么）

- 不猜数字：任何维度缺失即 skip，绝不用 0 / 均值 / 上一日补位。
- 不做 persona 演出、不引经据典编观点；评委是规则函数，可复现。
- 不给目标价、不给仓位建议、不构成投资建议（与日报「概率夹在 5%–95%」同口径，置信度封顶 95）。
- 不改写历史归档日报；老归档没有这一栏属正常。
- 不与【六眼飞鱼】共用信号分：栏内 MACD 维度同参数但独立计算，只作本栏裁决输入。
