# Vendored: 诗泉 (`palemoky/chinese-poetry-api`)

本目录固定（vendor）了 [`palemoky/chinese-poetry-api`](https://github.com/palemoky/chinese-poetry-api)（**📜 诗泉：高性能中国古诗词 API 服务**）的核心随机诗词接口定义、朝代/体裁分类器实现与离线精选语料库（源自上游数据子模块 [`palemoky/chinese-poetry`](https://github.com/palemoky/chinese-poetry) `fix-typo` 分支），供 `output/shiquan_poem.py` 与 `output/pipeline.py` 在每次日报最开始展示随机一首古诗词。

## 上游来源

| 字段 | 值 |
| --- | --- |
| 仓库 | `https://github.com/palemoky/chinese-poetry-api` |
| Commit | `6de8d1d95ad954d14bc6793b1a9c55d4bb8cd01a` |
| Commit 日期 | 2026-10-07 |
| 数据子模块 | `https://github.com/palemoky/chinese-poetry` (`fix-typo` @ `041b8ab50bdf07bf498bba2d1666b1d1fd707f4e`) |
| 关联 Skill | `https://github.com/lianginx/chinese-poetry-api-skill` |
| 在线服务 | `https://poetry.palemoky.com` (`GET /api/v1/poems/random`) |
| 许可证 | GPL-3.0（见同目录 [`LICENSE`](./LICENSE)） |

## 保留文件（相对 `tools/chinese-poetry-api/`）

```text
LICENSE                                    ← 上游 GPL-3.0 许可证原文
README.md                                  ← 上游项目说明与接口概览
requests.http                              ← 上游 REST/GraphQL/gRPC 请求示例（含 /api/v1/poems/random）
internal/
├── api/rest/handler/
│   ├── poem.go                            ← GetRandomPoem 随机一首诗处理逻辑与过滤参数（dynasty/author/type/char/lang）
│   └── formatter.go                       ← formatPoem 标准 JSON 响应结构
├── classifier/
│   ├── dynasty.go                         ← 朝代映射（先秦/两汉/魏晋/南北朝/隋/唐/五代/宋/元/清）
│   └── type.go                            ← 诗词体裁分类器（五言/七言绝句、律诗、乐府诗、宋词、五代词、诗经、楚辞、元曲）
└── loader/
    └── json_loader.go                     ← 上游数据集加载与朝代推断规则
data/
└── poems.json                             ← 按诗泉 formatPoem + classifier 口径预构建的 141 首跨朝代经典诗词离线语料
```

## 调用与降级链路

`output/shiquan_poem.py` 严格遵循诗泉 `/api/v1/poems/random`（兼容 `/api/poems/random`）协议与过滤参数（`dynasty` / `author` / `type` / `char` / `lang`）：

1. **在线 API 优先**：优先请求 `https://poetry.palemoky.com/api/v1/poems/random`（可通过 `OCTOPUS_SHIQUAN_BASE_URL` 覆盖）；
2. **离线语料无缝兜底**：当运行环境无外网连接、API 超时或单测离线运行时，自动从 `tools/chinese-poetry-api/data/poems.json` 按相同过滤条件随机抽取一首诗词，返回与诗泉 REST API 完全一致的字典结构。
