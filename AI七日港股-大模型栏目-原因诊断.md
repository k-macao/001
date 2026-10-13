# 🤖 诊断报告：「AI 七日港股走势分析概率」为什么整栏缺席（大模型：未配置 OCTOPUS_LLM_API_KEY）

| 序号 | 维度 / 条目 | 详细内容与说明 |
|---:|---|---|
| 01 | 2026-10-13 · 现象 | 每日工作流日志固定一行：`◧ 大模型：未配置 OCTOPUS_LLM_API_KEY → AI 七日港股走势分析概率整栏缺席`，日报里这一栏长期为空。 |
| 02 | 用户要求 | 用已经有的 DeepSeek API（`k-macao/272` 里那把 `DEEPSEEK_API_KEY`）。 |
| 03 | 结论先行 | **仓库里其实早就配了 DeepSeek Key**（`DEEPSEEK_API_KEY`，长度 35），代码也认这个名字——但工作流只把 `secrets.OCTOPUS_LLM_API_KEY` 传进去，而那个 Secret 从来没配过，于是 Key 一直"看得见、用不上"。 |
| 04 | 补充结论 | 接线补上之后，那把 Key 仍然出不了内容：DeepSeek 返回 **HTTP 402 `Insufficient Balance`**（账户余额为 0）。这一步在仓库里无解，只能充值或换一把有额度的 Key。 |
| 05 | 附带修好 | ① 手动抓取推送工作流此前完全不传大模型 Key → 手动跑出来的日报这一栏永远缺席；② 工作流里那个「只探活大模型 API」的勾选项引用了**根本不存在的** `--llm-check`，一点就报 `unrecognized arguments`；③ 代码默认模型写的是 `deepseek-chat`，而 DeepSeek 现行目录只有 `deepseek-flash` / `deepseek-v4-pro`。 |

---

## 一、根因：三层，逐层验证

| 层 | 问题 | 证据 |
|---|---|---|
| ① 接线层（真正的原因） | `octopus-daily.yml` 只传 `OCTOPUS_LLM_API_KEY: ${{ secrets.OCTOPUS_LLM_API_KEY }}`；该 Secret 未配置 → 值为空字符串。`output/hk_seven_day.py` 的 `ENV_KEY_NAMES` 里明明有 `DEEPSEEK_API_KEY`，但工作流没把它传进环境，代码就永远看不到。 | 走查 `.github/workflows/octopus-daily.yml` env 段 + `hk_seven_day.py` `llm_config()`；CI 实测 `OCTOPUS_LLM_API_KEY = (empty)`、`DEEPSEEK_API_KEY = SET`。 |
| ② 模型名层 | 代码默认 `deepseek-chat`（历史别名），DeepSeek 现行目录已改成 `deepseek-flash`（V4.1-Flash）/ `deepseek-v4-pro`。即使 Key 能用，写死旧名字也会 400 `Model Not Exist`。 | 探活实测：`GET /v1/models → deepseek-flash、deepseek-v4-pro`。 |
| ③ 供应商层 | 该 Key 鉴权通过（目录能读），但两次请求都返回 `HTTP 402 Payment Required：{"error":{"message":"Insufficient Balance ..."}}`。 | 见下面「二、探活原文」。 |

## 二、探活原文（CI，2026-10-14 04:51 · run 38466123000）

| 序号 | 维度 / 条目 | 详细内容与说明 |
|---:|---|---|
| 01 | Secret 有无 | `OCTOPUS_LLM_API_KEY = (empty)` · **`DEEPSEEK_API_KEY = SET`** · `OPENAI_API_KEY = (empty)` |
| 02 | Key 来源（不回声值） | `Key 来源：DEEPSEEK_API_KEY（长度 35）` |
| 03 | 端点 | `https://api.deepseek.com/v1`（未设置 `OCTOPUS_LLM_BASE_URL`，用默认值） |
| 04 | 模型目录 | `可选模型：deepseek-flash、deepseek-v4-pro` |
| 05 | 逐模型探活 | `❌ deepseek-flash · 718 ms · HTTP 402 Payment Required：{"error":{"message":"Insufficient Balance (request_id: 6076951b-…)","type":"unknown_error"…}}`<br>`❌ deepseek-v4-pro · 654 ms · 同上 402` |
| 06 | 结论 | `❌ 不可用：这一栏会按降级口径处理（402 余额/额度不足 → 到 DeepSeek 控制台充值，或换一把有额度的 Key）` |

## 三、接线到底通不通：用本地假端点把两类问题分开

真实 Key 只会回 402，证明不了「代码接线」这一层。于是把端点换成本地回环的假模型
（`tools/llm_mock_server.py`，实现 `/v1/models` + `/v1/chat/completions`，不出网），同一套流水线再跑：

| 步骤 | 命令（CI 实测） | 结果 |
|---|---|---|
| 探活 | `OCTOPUS_LLM_BASE_URL=http://127.0.0.1:8899/v1 python3 output/pipeline.py --llm-check` | `✅ 就绪：模型 deepseek-flash 返回合法 JSON，这一栏可以出内容`（1 ms） |
| 单栏 | 同上 + `OCTOPUS_LLM_MODEL=deepseek-flash python3 output/pipeline.py --hk7-only` | `✅ AI 七日港股：锚定 2026-10-13 收盘 · 大模型 · deepseek-flash · 数字溯源 6/6` |
| 整份日报 | 同上 + `python3 output/pipeline.py --no-push` | 日报里出现该栏目，引擎标注 `大模型 · deepseek-flash · 锚定 2026-10-13 收盘 · 未来 7 …` |

结论：**Key → 环境变量 → 研判引擎 → 日报栏目**这条链路现在是通的；剩下唯一卡点是供应商侧的余额。

## 四、这次改了什么

| 序号 | 文件 | 改动 |
|---:|---|---|
| 01 | `.github/workflows/octopus-daily.yml` | Key 按原名透传（`OCTOPUS_LLM_API_KEY` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`），由代码按「本仓专用名 → 厂商通用名」回落选择；日志改成打印**实际生效的变量名**；补上 `OCTOPUS_LLM_MAX_TOKENS`；去掉从未被代码读取的 `OCTOPUS_LLM_THINKING`。 |
| 02 | `.github/workflows/manual.yml` · `output/manual_push_workflow.yml.example` | 「手动抓取推送」此前**一个 Key 都不传**，补齐同一套；否则手动跑出来的日报这一栏永远是缺的。 |
| 03 | `output/hk_seven_day.py` | ① Key/地址/模型三组变量支持厂商通用名回落（`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DEEPSEEK_BASE_URL`…）；② 未显式指定模型名时走候选链 `deepseek-flash → deepseek-v4-pro → deepseek-chat → …`，**只有「模型名不对」才换下一个**（超时/限流换名字没意义），显式指定则绝不替换；③ `HTTPError` 现在带上服务端响应体原话（裸「HTTP Error 402」看不出是余额还是模型名）；④ 新增 `llm_error_hint()`：402/401/403/429/超时/模型名不存在各自给出下一步动作；⑤ 新增 `llm_probe()` 探活。 |
| 04 | `output/pipeline.py` | 补上工作流引用却不存在的 **`--llm-check`**（读配置 → 列 `/models` → 逐个候选模型发一次真实 JSON 请求 → 给结论）；降级日志统一追加 `🛠 下一步：…`。 |
| 05 | `tools/llm_mock_server.py` | 本地假模型端点（回环、不出网、不写文件）：把接线问题与供应商问题分开验证。 |
| 06 | `tests/test_hk_seven_day.py` | 新增 3 组离线用例：厂商通用名回落与候选链、只有模型名错误才换名、探活报告只报来源不回声 Key（并断言报告里不出现 Key 本身）。 |
| 07 | `README.md` | 环境变量表与「相关诊断记录」同步。 |

## 五、还需要你做的两件事

| 序号 | 事项 | 怎么做 |
|---:|---|---|
| 01 | **充值或换 Key**（唯一剩下的卡点） | 到 DeepSeek 控制台给这把 Key 所属账户充值；或把有额度的 Key 更新到仓库 Secret `DEEPSEEK_API_KEY`。 |
| 02 | 充值后点一次探活 | Actions → **🐙 章鱼AI · 每日自动推送** → **Run workflow** → 勾上 **只探活大模型 API（llm_check）**。看到 `✅ 结论：就绪：模型 deepseek-flash 返回合法 JSON` 就说明这一栏下一轮会自动出内容。 |

| 序号 | 维度 / 条目 | 详细内容与说明 |
|---:|---|---|
| 01 | 充值前的表现（已改善） | Key「已配置但调用失败」按 `OCTOPUS_HK7_FALLBACK=auto` 的口径降级为**量化基准**并照常出栏（栏内点名降级原因 + `🛠 下一步`），不再整栏消失；若想让「没有 Key 也出栏」，设 `OCTOPUS_HK7_FALLBACK=1`。 |
| 02 | 不想用 DeepSeek 时 | 任何 OpenAI 兼容端点都行：`OCTOPUS_LLM_BASE_URL` + `OCTOPUS_LLM_MODEL` + `OCTOPUS_LLM_API_KEY`（或对应的厂商通用名）。 |
| 03 | 本地复现 | `python3 output/pipeline.py --llm-check`；假端点联调见 `tools/llm_mock_server.py` 顶部注释。 |
| 04 | 边界 | 探活只读配置与端点，不抓行情、不生成日报、不写留痕；日志与探活报告一律**只报变量名与长度，绝不回显 Key 本身**。 |
