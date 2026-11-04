# 🇭🇰 诊断报告：为什么一次抓出成片「⚠️ 请求失败 … 404」

| 序号 | 维度 / 条目 | 详细内容与说明 |
|---:|---|---|
| 01 | 2026-11-04 · 排查对象 | 用户贴的 `⚠️ 请求失败 [https://query1.finance.yahoo.com/v8/finance/chart/06160.HK?range=2y&interval=1d]: 404 Client Error: Not Found`，以及同批出现的「大量请求失败」 |
| 02 | 结论先行 | **Yahoo 的港股代码是 4 位补零，代码里一直在用交易所 / 东财的 5 位。** 凡是被东财补成 5 位的港股代码（`06160.HK`、`00700.HK`…）在 Yahoo 全部拿不到数据，于是「低因子批量抓 320 只日线」一轮就刷出几十上百条 404。不是限流、不是网络、也不是 Yahoo 挂了。 |
| 03 | 修复一句话 | 内部继续存 5 位（东财 / 交易所口径），**只在拼 Yahoo URL 时折成 4 位**；同时把批量取数的逐条失败日志收成一行汇总。 |

---

## 一、实测对照（2026-11-04，同一天、同一接口）

| 代码 | Yahoo 返回 | 说明 |
|---|---|---|
| `0700.HK` | ✅ 腾讯 401.6（2 年日线齐全） | 4 位 = 正确写法 |
| `00700.HK` | ❌ `{"chart":{"result":null,"error":{"code":"Not Found","description":"No data found, symbol may be delisted"}}}` | 5 位 = 无数据 |
| `0005.HK` | ✅ 汇丰 136.4 | 4 位 = 正确写法 |
| `6160.HK` | ✅ BeOne Medicines 231.6，`validRanges` 含 `2y` | 4 位 = 正确写法 |
| `06160.HK` | ❌ **HTTP 404** | 5 位 = 直接 404（就是用户贴的那条） |

> 对照：`^HSI`、`HSTECH.HK`、`600519.SS`、`MSFT` 在同一天全部正常 → 不是 Yahoo 整体故障。

---

## 二、根因（代码级）

| 序号 | 维度 / 条目 | 详细内容与说明 |
|---:|---|---|
| 01 | 批量抓日线拼错代码 | `output/lowfreq_factors.py:fetch_hk_bars()` 把内部 5 位代码直接拼成 `f"{code}.HK"` → `06160.HK` → Yahoo 404。**这是日志里成片失败的来源**（320 只池子 × 3 轮重试） |
| 02 | 其它路径同源风险 | `providers.fetch_bars()` / `market_db.fetch_yahoo()` 只把调用方给的代码原样拼接；一旦上游给的是 5 位（东财补零口径），同样 404 |
| 03 | 环境变量口径漂移 | `OCTOPUS_HK_UNIVERSE` / `OCTOPUS_MACD_SYMBOLS` 允许写 `700.HK`、`0700.HK`、`00700.HK`，此前不做归一，写 5 位就整只丢 |
| 04 | 日志放大器 | `safe_request()` 每条失败都 `print`。批量场景下 40 只一批 × 8 批 × 3 轮，失败一次就一行 → 用户看到的「大量请求失败」 |

---

## 三、修复内容（本分支）

| 序号 | 改动 | 文件 | 说明 |
|---:|---|---|---|
| 01 | 新增 `yahoo_hk_code()` / `is_hk_yahoo_symbol()` / `normalize_yahoo_symbol()` / `HK_YAHOO_CODE_WIDTH = 4` | `output/backup_sources.py` | 5 位补零 → 4 位补零；**只认 `.HK` 后缀**，`600519.SS` / `^HSI` / `HSTECH.HK` 一律原样返回；超过 4 位的有效代码只去前导零，绝不截断 |
| 02 | `yahoo_symbols_for()` 接入 4 位口径 | `output/backup_sources.py` | `06160.HK → ("6160.HK", "06160.HK")`、`00700.HK → ("0700.HK", "00700.HK")`；`get_yahoo_urls()` / `candidates()`（`yahoo_chart`、`yahoo_bars` 两条线）自动生效 |
| 03 | `providers.yahoo_hk_code()` / `_canonical_hk_symbol()` | `output/octopus_quant/providers.py` | `fetch_bars()` 的 Yahoo 代码候选链带上 4 位口径；环境变量标的池先折成内部 5 位（三种写法都能用），拼 URL 时再折 4 位 |
| 04 | `lowfreq_factors._yahoo_hk_symbol()` | `output/lowfreq_factors.py` | 批量抓日线改成 `specs = [(5位code, "6160.HK")]`，内部键仍是 5 位，`fetch_hk_bars` 返回口径不变 |
| 05 | `market_db._yahoo_hk_code()` + `fetch_yahoo._codes()` | `output/market_db.py` | 行情库快照同样先 4 位、再原写法 |
| 06 | 批量取数日志闸门 `request_quiet()` / `note_request_failure()` | `output/octopus_quant/providers.py` | **进程级**（不是 threading.local——批量走线程池，worker 必须看得见）；`pipeline.safe_request()` 在批量段内只计数不打印 |
| 07 | 批次汇总一行 | `output/lowfreq_factors.py` | `ℹ️ 日线批次：28/40 只取到（其中 12 次请求失败），未取到的会按重试阶梯再试` |
| 08 | 新增 `tests/test_hk_code_format.py` | 测试 | 15 个用例：代码折算、后缀保护、长代码不截断、四条取数路径、环境变量归一、日志闸门（含线程池可见性） |

---

## 四、口径与边界

| 序号 | 边界 | 说明 |
|---:|---|---|
| 01 | 内部口径不变 | 全仓内部仍用 **5 位**（`00700` / `06160`），与东财 `116.00700`、交易所、`media_risk` 的 `00700.HK` 一致；只有 Yahoo URL 用 4 位 |
| 02 | 两种写法都试 | 4 位优先（Yahoo 现行口径），原写法留作最后一试；两种写法相同的标的只请求一次，不产生额外流量 |
| 03 | 不吞后缀 | `yahoo_hk_code("600519.SS")` 返回 `600519.SS`，不会把 A股 / 指数写成港股代码 |
| 04 | 不编数据 | 取不到的仍然取不到，只是不再刷屏；原有的「覆盖不足 60% 就不出名单」门槛照旧 |
| 05 | 单只失败仍然可见 | 只有**批量段**静音；单只请求（行情快照、单标的诊断）依旧逐条打印 `⚠️ 请求失败` |

---

## 五、验证

| 序号 | 验证项 | 结果 |
|---:|---|---|
| 01 | `python3 -m pytest tests/test_hk_code_format.py -q` | **15 passed, 11 subtests** |
| 02 | `python3 -m pytest tests/test_hstech_symbol.py -q` | **15 passed, 9 subtests**（同一天的上一个修复未回归） |
| 03 | 全量 `python3 -m pytest tests -q` | **1229 passed / 1 skipped / 3 failed**，3 项为既有失败（`git stash` 后在 `main` 上同样失败，见 PR 说明） |
| 04 | 实测对照 | `06160.HK` → 404；`6160.HK` → BeOne Medicines 231.6，2 年日线；`0700.HK` → 腾讯 401.6；`00700.HK` → result:null |
| 05 | 日志量 | 批量段内失败只计数，一轮批量输出从「几十行 ⚠️」降到「每批一行 ℹ️」 |
