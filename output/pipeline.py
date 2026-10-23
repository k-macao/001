#!/usr/bin/env python3
"""
🐙 章鱼 AI · 上水日报 ——「每日上水，新鲜活泼」· 全网多模型协同 · 每日财经日报流水线
每次运行都重新抓取全网最新数据 → 分析 → 生成 → 当天检验 → 推送

核心规则（2026-08-02 新版，当天修订）：
  1. 没有数据的区块不出现在页面里，也不推送空内容。
  1.1 手动 / 自动推送前先清理 output/ 目录下的全部历史 HTML 报告（含
      daily_report_*.html 与 latest.html），再抓取数据并生成新报告；
      避免历史残留文件（含旧版本特征）被误推或被 latest.html 引用。
      --push-only / --list / --dry-run / --quant-only / --calendar-only 不清理
      （前者基于旧文件，后四者不写文件）。
  2. 每次生成后先做「当天内容检验」：每个数据源标注 ✅当天 / 🕓非当天 / ⚠️无数据，
     只有当「至少一个数据源含当天内容」时才自动推送日报；否则不推日报，
     但会推一条「纯文本告警」说明原因与各来源状态，避免彻底沉默。
  3. 「港股名家频道」数据源：香港股评人/财经平台的 YouTube 与通用 RSS 抓取
     （无需 API Key），每频道取最新 3 条；需登录平台明确标注「暂缺」及原因，
     不伪造内容。2026-10-02 起该栏目在页面隐藏（见第 24 条），数据仍照常抓取并
     供政策因子 / 策略研判 / 新闻情绪 / 逐栏 AI 研判与审计使用。
  4. 「全球头条」改用 Google News 数据源（替换原 Yahoo Finance News）：直接抓
     Google News 中文版，标题本身即中文，无需翻译。2026-10-02 起该栏目
     （【无敌帝王蟹】全球头条）同样在页面隐藏（见第 24 条），数据用途不变。
  5. 新增「东方财富快讯」数据源：东方财富免费公开接口的最新 5 条财经新闻。
     2026-10-02 起页面隐藏「东方财富快讯」栏目（正文不再单独展示），
     原始快讯数据仅作为政策因子、策略研判、新闻情绪与数据审计的信号源。
  6. 新增「热门榜单」数据源：最近交易日收盘后 A股/港股/美股 成交量前五
     （东方财富 push2 免费接口）。2026-08-06 起不再单独渲染三个成交量榜单栏目，
     原始榜单数据仅作为策略研判与数据审计的信号源；
     页面只保留策略研判结果。
  6.1 新增 A股大盘全景数据（数据源：东方财富 push2/push2his 免费接口；2026-09-30 起
      与「实时行情」合并渲染进栏目【及时秋刀鱼】AI 行情复盘，见第 20 条）：
      ① 指数表现（A股）——上证 / 深证 / 创业板 / 科创50 / 北证50 / 沪深300 / 上证50 / 中证500
      最新价、涨跌幅与成交额（合并后与 Yahoo 报价并成栏目里的「A股指数」一张表）；
      ② 涨跌家数——沪深京市场宽度（上涨/下跌/平盘家数、涨跌比与情绪定调）；
      ③ 成交额——沪深京合计与上一交易日环比（日 K 补齐前值）；
      ④ 南北向资金——港交所 2024-08-19 起停披净买入，按最近完整交易日（前一收盘）
      展示北向、南向成交总额与披露口径说明，绝不编造净买入；
      ⑤ 板块热力——行业板块领涨/领跌 TOP5（附主力净流入与领涨股）。
      子块独立降级：单个接口失败只隐藏对应子块，A股指数与宽度全缺时整块才缺席；
      规则合成，非投资建议。
      （原「全球指数概览」子块——美股道琼斯 / 标普500 / 纳斯达克与港股恒生指数 / 恒生科技
      最新价与涨跌幅，复用同一次抓取的 Yahoo 报价——已于 2026-09-30 随两栏合并删除：
      它与报价块「全球与美股」「港股双指数」逐项数字完全相同，属于纯重复。）
  6.2 逐栏目 AI 研判（2026-09-27 新增）：每个有数据的内容栏目（【及时秋刀鱼】AI 行情复盘 /
      政策因子 / 趋势跟踪 / 新闻情绪）正文末尾追加一行概率化多空判断
      （全球头条 / 东方财富快讯 / 港股名家频道三栏已于 2026-10-02 在页面隐藏，
      其研判照旧计算，但因栏目不再渲染而不会成行）：
      「⌁ AI 研判 ▲偏多 / ▼偏空 / ■中性 · 多头 x% / 空头 y% — 栏内证据 → 预测：结论」。
      概率 = 50 + 45*(多−空)/(多+空)，夹在 5%–95%（持平 50%，绝不绝对化）；≥60% 偏多 /
      ≤40% 偏空 / 其间中性；多头 + 空头恒 100%。证据仅取自该栏目已抓取数据；结论类栏目
      （【回游金枪鱼】今日预判 / 策略研判 / 总结）与前瞻日程类栏目（【探照安康鱼】时间节点量化分析：
      日程不含方向信息，只给「最密集日 + 事件密度提示」）不附加，栏目无数据自然缺席。
      规则合成，非投资建议。
  6.3 新增「未来30天影响经济时间点」栏目（2026-09-28，位于专业分析之后的首个数据栏目；
      2026-09-29 起更名为「【探照安康鱼】时间节点量化分析」）：
      数据源为东方财富财经日历（数据中心公开报表 RPT_CPH_FECALENDAR，无需密钥，
      START_DATE 即北京时间）。服务端只支持按日期过滤，故一次拉全窗口 + 翻页，
      再在本地按写死的口径筛选：保留 数据（中美欧日英港等市场的宏观读数）/
      事件（央行议息、国民经济运行情况发布会、中央全会等重要会议）/ 动态（央行官员
      讲话、货币政策会议纪要、CFTC 周度持仓）三类，剔除个股事项、非保留地区读数、
      冗余子序列与超长条目；同一天同一指标的 同比/环比/初值/终值 多行合并为一行。
      重要度 ★★★（中美一级读数 + 主要央行议息与中国宏观决策会议）/ ★★ / ★；
      抓取后本地再夹一次窗口，栏目写「未来 N 天」就绝不出现窗口外的行。
      正文行数上限（默认 60）只作版面保护，被裁条数按重要度如实写进摘要。
      前瞻性日程属于「今日抓取快照」而非当天发布内容：is_today=False + snapshot=True，
      因此它永远不会单独把日报推过当天检验闸门；抓取失败则整栏缺席并在总结点名。
      OCTOPUS_CALENDAR=0 关闭、OCTOPUS_CALENDAR_DAYS 调窗口、OCTOPUS_CALENDAR_ROWS 调行数。
  4. 支持手动推送：--manual / manual_push.sh / GitHub Actions 手动按钮（可勾选 force_push），
     内容非当天时可用 --force-push 强制推送（谨慎）。
  5. 任何「应当推送却失败」的情况（PushPlus 报错、未配置 PUSHPLUS_TOKEN、网络异常，
     含「检验未通过」告警发送失败）都以退出码 1 结束：GitHub Actions 会显红并触发
     失败通知，杜绝“推送失败却显示成功”的假象。
  6. PushPlus 推送对「发送频繁 / 稍后再试 / 服务器繁忙 / 网络异常 / HTTP 429·5xx」
     等可恢复错误按 10s→30s→60s 退避自动重试（最多 4 次）；对「当日配额已达上限、
     token 失效、内容违规」等重试无意义的错误不重试、立即失败。日报多次推送仍失败时
     会再发一条纯文本「推送失败」告警（含 PushPlus 返回的 code/msg 与处理建议），
     让微信侧也能感知原因，而不是只看到 Actions 变红。
  7. 推送标题固定为「[OCTOPUS] 章鱼 AI · 上水日报 - 08/01 18:30」：前缀是过滤关键词，
     末尾带当日时分（北京时间），同一天多次手动推送不会因标题完全重复
     触发反垃圾/去重拦截，也便于区分每一次推送（2026-10-13 起，见 28）。
  7.1 页面风格：复古像素游戏（RETRO PIXEL MARKET QUEST v3）——
     暗色街机终端底、霓虹青 / 电光蓝 / 像素黄 / 品红，纯直角像素块 + 3px 硬描边 + 实色阴影；
     等宽字体栈（Courier New / Lucida Console / monospace，回退苹方/雅黑）。刊头含纯 HTML 8-bit
     章鱼图标；每个 LVL 关卡配独立 44px 大图标砖。涨跌用高对比底色 + ▲涨 / ▼跌 / ■平三重
     编码，并覆盖行情等板块。策略研判栏目使用 QUANT CORE 主控卡、方向 / 信号分 /
     置信度计分板和大字号「AI 主结论」，板块 / 技术 / 风险 / 关注各自成独立像素面板；窗口标题栏
     升级为 OCTOPUS_OS v3。成交量榜单不再单独成栏，只保留 策略研判结果。
     硬约束：全部内联样式 + 表格布局（微信/PushPlus 会剥离 <style> 与 class）。
  8. 超长日报「尽量合并」后全量分条推送：超过 PushPlus 单条上限（默认会员 10 万字符）时，
     把每条都填到单条上限为止——整栏放得下就整栏装，放不下就在完整标签边界切开、
     续片重开栏目头并在横幅标注「承接上条（续）」——因此条数就是「总字数 ÷ 单条上限」的
     理论下限（旧版整栏装箱会浪费 30%+ 空间、白多推几条）。全部明细不丢，
     磁盘 / GitHub 始终保留一份完整日报；发请求前还按平台频率限制（默认 1 分钟 5 次）
     主动排队，条数多也一条不丢；见 _pack_section_units / _split_html_for_push / _wait_push_rate_limit。
  9. 「策略研判」栏目：基于当日多源信号（实时行情、A股板块热力、热门榜单、全球/东财头条与
     港股名家频道观点）做确定性量化合成，输出板块趋势跟踪策略（量化信号 +
     趋势分 + 置信度、板块趋势强度榜、技术速读、风险控制、量化配置）。无需大模型 API、
     可复现、不伪造内容，明确标注「非投资建议」；数据源不足时该区块自动缺席。
     2026-09-09 起页内去重：指数动能只保留聚合（明细数值见【及时秋刀鱼】AI 行情复盘），
     风险提示对正文已展示的标题仅引用定位（栏目 + 序号 + 命中关键词 + 锚点），
     多因子矩阵不再复述雅虎逐只报价。
     2026-10-02 起加入 MACD(12,26,9) 日线子策略：市场库 → 本次已有日线 →
     Yahoo / 东财免费源，仅已收盘、足够新鲜的序列；展示交叉、零轴、动能与规则动作，
     不改变原市场信号分、不把技术信号转换成未经校准的概率。
  10. 「新闻情绪」栏目（2026-10-10 起更名「【亮亮灯光鱿鱼】新闻情绪因子量化分析」，
      见第 25 条）：按「最近交易日 A股 / 港股 / 美股 成交量前五」
      逐股输出 AI 新闻情绪分与总结评论（含原因）。标题窗口为近
      SENTI_WINDOW_HOURS=72 小时（含历史存档），对窗口内标题逐条词表评分（S，
      附命中词）并按热门榜单个股名归因；每只上榜股输出 DNS 情绪=
      (正−负)/总数（72h 窗口口径）、MOM 情绪动量=近3有评分日均−近20有评分日均、
      ANV 异常新闻量=今日条数 vs 近30天均值±σ（z 值，>均值+2σ 标异常；
      MOM/ANV 与跨日基线按自然日口径，存 output/sentiment_history.json，随日报
      提交），以及「总结评论 + 原因」（由命中标题、词表、动量与新闻量规则生成）。
      窗口内无相关点名新闻的上榜股明确显示「暂无评分」与原因，不凭价格涨跌反推
      新闻情绪；无热门榜单则栏目缺席。标题存档存 output/news_history.json
      （每次运行合并本次抓取并按 日期+标题 去重）。冷启动/样本不足明确标注。
      渲染位置：各资讯栏目之后。规则合成、非投资建议。
  11. 「港股量化引擎」（output/octopus_quant/，2026-09-28 起）：把整条流程按量化
      思维重构成六个可独立测试的层——providers(数据) → features(五因子特征) →
      probability(分桶+保序+逻辑回归校准 / 推进式回测) → liquidity(资金流动性) →
      engine(编排) → render(呈现)，外加「预测留痕 → 次日按真实收盘结算」的反馈闭环
      （output/quant_history.json）。核心栏目两个（2026-10-23 起；原第三个「【蜉蝣天地水母】
      量化分析总览」已按用户要求整栏下线，见第 32 条）：**每日趋势量化推演**（逐日走势预测 +
      恒指/恒科/国企指数 + 个股池逐只概率 + 市场宽度 + 五因子拆解）、
      **资金流动性分析**（南向/北向成交总额
      与 z 值分位、恒指量能、Amihud 非流动性、CR5 集中度、主力资金流、流动性综合分
      0~100 与对概率的有界修正）。概率全部由「同一套因子在自身历史上滚动重算 →
      分桶 + 保序 + 逻辑回归校准」得到，并经推进式回测检验（每步只用过去数据），
      夹在 5%~95%，非投资建议；数据取不到时对应子块明确显示「暂缺」，绝不编造。
  12. 「政策因子」栏目：抓取后、推送前单独构建，归入专业分析组。除资讯标题外，
      直接读取中国政府网「最新政策」官方页面，保留发布日期与 gov.cn 原文链接；
      近 POLICY_WINDOW_DAYS=15 日窗口（自然日，含历史存档）内标题做政策维度识别
      （货币/监管/扶持/财政/地产/开放/贸易/宏观数据——宏观数据含 CPI / PPI /
      社融 / 统计局 等经济数据口径），经关键词矩阵映射到行业受益/受损权重，
      汇总为 PolicyShockIndex（行业 PSI 与大盘 PSI，附规则生成的总结），并做量化趋势预判：
      PSI 归一 50% + 政策新闻量 30% + 维度覆盖 20% 复合分，输出趋势分、政策冲击强度榜、
      趋势预判信号与风险预算。官方条例、规划、办法等没有方向性触发词时按中性「政策发布」纳入；
      触发词被否定修饰时跳过；窗口内零政策/宏观新闻时栏目缺席。规则合成、非投资建议。
  13. 「A股资讯」（新浪财经滚动新闻）栏目已移除（2026-09-28 按用户要求）：不再抓取、
      不再渲染、不再进入审计与新闻语料；A股内容由【及时秋刀鱼】AI 行情复盘
      （指数/宽度/成交额/南北向/板块）与「东方财富快讯」承担，避免来源重复与同质化。
  14. 「趋势跟踪」升级（2026-09-28）：栏目为两段结构——「全网 36 个新闻源头 · 港股信息挖掘 + 分析」
      与「多平台信息员」社区样本。36 个源头按 香港 7 / 内地 23 / 国际 6 配置（RTHK、HKET、
      SCMP、HKEX、Now、TVB、HKFP、财联社、格隆汇、智通、证券时报、同花顺、东财策略研报、
      Google 新闻中/英文聚合、Bloomberg、MarketWatch、Investing.com、FT、BBC，
      以及 2026-10-12 按用户指定新增的 16 家内地媒体：中证网、证券日报网、中国基金报、
      财闻网、经济参考网、IT之家、券商中国、每日经济新闻、北京商报、21世纪经济报道、
      证券之星、和讯网、金融投资报、时代财经、经济观察网、凤凰网财经），只读公开
      RSS/Atom 订阅：只保留 72 小时窗口内、带可验证时区发布时间的标题 + 原文链接（北京时间），
      链接按每源域名白名单校验（https + 主机名精确匹配）；按港股关键词命中挖掘相关信息
      （未命中只计扫描数），每源至多 3 条、正文合计至多 24 条。多平台信息员 = Reddit（散户
      论坛：10 个财经/投资/金融/经济类板块各取热门帖 5 条）+ StockTwits（美股/加密散户情绪
      平台）+ TradingView（交易员公开 Ideas 观点）+ Bogleheads（长期投资者论坛最新主题）
      四个公开平台。各源 / 各平台独立采集、独立降级：单个失败只影响该来源，缺失来源在总结
      「数据覆盖」定点名；只读公开 feed / 公开 JSON，不登录、不绕过付费墙、不复制帖子正文；
      社区观点未经核实，热度不等于事实或投资建议。分析为确定性规则合成：覆盖度 + 中英多空词
      概率（50±45，夹 5%~95%）+ 主题词表热点 TOP3 + 热股提取，并入栏目末尾「⌁ AI 研判」行。
      OCTOPUS_HK_NEWS=0 关闭新闻源段、OCTOPUS_TREND_PLATFORMS 关闭社区段、
      OCTOPUS_RSSHUB_BASE 换 RSSHub 实例、OCTOPUS_HK_NEWS_PER_SOURCE / OCTOPUS_HK_NEWS_MAX
      调条数；规则合成，非投资建议。
  15. 栏目更名（2026-09-28 按用户要求，功能不变）：今日预判→今日预判、A股大盘全景→
      全球大盘全景复盘（同时新增「全球指数概览」子块；该栏已于 2026-09-30 并入
      【及时秋刀鱼】AI 行情复盘，见第 20 条）、AI 盘研判→策略研判、每日量化策略
      趋势跟踪线索→趋势跟踪、新闻情绪→新闻情绪、总结→总结；行情速览 / 政策因子 /
      全球头条 / 东方财富快讯 / 港股名家频道 名称不变（其中 政策因子 / 全球头条 已于
      2026-09-29 再次改名，见第 21 条；行情速览见第 20 条）。像素主题英文关卡名同步更名
      （CONCLUSION→FORECAST、A-SHARE PANORAMA→GLOBAL PANORAMA、AI READ→STRATEGY READ、
      TREND CLUES→TREND TRACKING、WRAP-UP→SUMMARY），图标砖短标签同步为 STRAT / GLOBAL / SENTI。
  16. 新增「【火爆大鱿鱼】美联储因子量化分析」与「【巡回巨鲸】地缘政治因子量化分析」两栏目（2026-09-28
      按用户要求）：阅读位置在政策因子之后、策略研判之前。各有**专门抓取**——Google News
      RSS 搜索查询（美联储：`美联储 OR FOMC OR 鲍威尔`；地缘政治：`地缘政治 OR 制裁 OR
      冲突 OR 关税`），抓取失败整栏缺席并在总结「数据覆盖」点名，绝不以旧闻兜底。
      栏目内容 = 方向定调（美联储：偏鹰 / 偏鸽 / 观望；地缘政治：升温 / 平稳 / 缓和，
      由标题词表命中计数确定性判定）+ 命中证据逐条引用（标题 + 来源 + 发布时间 + 命中词，
      与正文其他栏目重复的标题不重复展示、只计入分析）+ 美联储板附财经日程里的相关
      时间点（FOMC / 议息 / 非农 / CPI 等，日程缺失只隐藏该子块）+ 末尾「⌁ AI 研判」
      概率行（宽松 / 缓和记多头，紧缩 / 升温记空头）。规则合成、非投资建议。
  17. 「每周量化走势预测」栏目（output/octopus_weekly.py，2026-09-28 起；2026-09-29 起
      视界由 5 个交易日升级为 **未来 7 个交易日逐日表格**，2026-09-30 起合并原「AI 七日
      港股走势分析概率」为栏内子块）：恒生指数未来 7 个交易日（T+1…T+7，按交易日计数、
      假期顺延）逐日给出 ① 预测（累计上涨概率 P(7日涨) + 当日环比 + 80% 预期区间）
      ② 理由（因子证据）③ 分析 ④ AI 操作建议（操作倾向 / 建议仓位 / 止损止盈，规则合成、
      非投资建议），外加七日整段结论。方法来自 GitHub 无未来函数（look-ahead）量化工程
      实践调研：特征只用 ≤t 数据且扩张因果归一（akfamily/akquant）、相似样本标签必须已
      结算 s+7≤t（haeganm/walkforward 的 purged/embargo 依据）、运行时「截断不变性」自检
      覆盖全部 7 个视界（arielb57/peekahead：输出 ≤t 只依赖输入 ≤t，不过则整栏降级）、
      预测先存档 settled=False 满 7 个交易日再按真实收盘结算（k-macao/03 PR #54 四条硬
      约束，留痕 output/weekly_forecast.json，样本 <10 只报样本量；2026-09-29 前入档的
      5 日视界旧条目仍按原 5 日口径结算，绝不篡改历史）、回测体检清单
      （paidaxing1234/quant-backtest-guard）。预测器 = 扩张基准率 + 20 日特征最近邻
      （K=8）50/50 合成、夹 5%~95%，逐日路径由一次因果扫描的视界 1..7 信号合成；纯标准库
      + providers.fetch_bars 单一联网口。OCTOPUS_WEEKLY=0 / --no-weekly 关闭、
      --weekly-only 研究模式；数据取不到、样本不足或自检不过 → 整栏缺席。规则合成，
      非投资建议。

  18. 「AI 七日港股走势分析概率」子块（output/hk_seven_day.py，2026-09-29 起，取代原
      「每日量化策略（行业轮动）」栏目：该栏目从上线到 09-28 的 58 份日报出现率 0/58，
      东财行业板块两步取数在真实环境未跑通；2026-09-30 起由独立栏目并入第 17 节
      【嗜血大白鲨】逐日走势量化分析与港股概率走势分析合并为「每日趋势量化推演」，逐日表格 / 港股概率 / AI七日任一路可用即出栏目，数据源键名 /
      审计标签 / 留痕文件各自保留）：恒生指数 / 恒生科技 / 国企指数三只标的、未来 7 个
      交易日（按交易日计数、假期顺延）的收盘上涨概率 + 依据 / 风险 / 三道防线，与港股概率走势分析共用
      **每日趋势量化推演**栏目头。量化基准
      复用 octopus_weekly 的因果引擎（视界 7：扩张基准率 + 20 日特征最近邻、s+7≤t 已结算
      锚点、截断不变性自检、5%~95% 夹逼）；研判引擎按优先级三选一——
      ① 大模型（OpenAI 兼容 /chat/completions：OCTOPUS_LLM_API_KEY /
      OCTOPUS_LLM_BASE_URL / OCTOPUS_LLM_MODEL）只在给定数据内做合成研判：Key / 地址 /
      模型三组变量都支持厂商通用名回落（DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL、DEEPSEEK_MODEL
      等），既有的 DeepSeek 配置不必改名；未显式指定模型时按 DeepSeek 档位/版本别名候选链
      （deepseek-flash → deepseek-v4-pro → deepseek-chat …）逐个尝试，只有「模型名不对」
      才换下一个；--llm-check 可单独探活（Key 来源 / /models 目录 / JSON 合同）。
      概率偏离量化
      基准 >20pp 即收敛、文案数字必须能在本次数据里溯源、绝对化措辞与编造数字一律回退
      量化口径；② Jev 类型化决策本地模型（output/jev_bridge.py，2026-10-03 接入，
      OCTOPUS_JEV_BASE_URL / OCTOPUS_JEV_API_KEY / OCTOPUS_JEV_MODE）：只输出值 + 已校准
      概率（不产文本、无编数字入口），概率与量化基准按同一份常量对账（>20pp 收敛），
      端点未配置即缺席、调用失败逐标的记因并回退量化基准，研究留痕单独一份
      output/jev_forecast.json（同一套 T+7 结算口径）；③ 量化基准兜底。
      OCTOPUS_HK7_FALLBACK 三档：默认 auto —— 大模型 Key 与 Jev 端点都未配置时该子块
      缺席且不进审计，已配置但调用失败才降级量化基准；=1 都没有也降级渲染；
      =0 任何研判引擎不可用都整子块缺席。预测先存档（output/hk7_forecast.json，
      settled=False），满 7 个交易日按真实收盘结算，样本 <10 只报样本量。
      「数据覆盖」审计里会点名 Jev 端点状态（未配置 / 探活失败 / 调用失败 / 使用中）。
      OCTOPUS_HK7=0 / --no-hk7 关闭；--hk7-only 研究模式。非投资建议。

  19. 栏目更名（2026-09-29 按用户要求，只改标题文字，内容 / 顺序 / 抓取 / 推送门禁
      与拆分逻辑完全不变）：今日预判→**【回游金枪鱼】今日预判**、
      未来30天影响经济时间点→**【探照安康鱼】时间节点量化分析**、
      量化分析总览→**【蜉蝣天地水母】量化分析总览**。相关标题集中定义为
      SECTION_TITLE_FORECAST / SECTION_TITLE_ECON_CALENDAR / SECTION_TITLE_QUANT_FORECAST
      （其中 SECTION_TITLE_QUANT_FORECAST 已于 2026-10-23 随该栏下线移除，见第 32 条），
      guizang 与 pixel 两个主题共用。「时间节点」栏目的窗口天数不再写在标题里，
      仍在栏目内「窗口摘要 · 时间窗口」如实显示（OCTOPUS_CALENDAR_DAYS 改窗口时同步变化）。
      其余栏目名称不变。

  20. 栏目合并（2026-09-30 按用户要求：「行情速览」与「全球大盘全景复盘」内容重复）：
      两栏合并为一栏 **【及时秋刀鱼】AI 行情复盘**（kicker MARKET REVIEW，标题常量
      SECTION_TITLE_MARKET_REVIEW，两主题共用），占原「行情速览」的阅读位置
      （每周量化走势预测之后、政策因子之前），原 GLOBAL PANORAMA 位置取消。
      **去重（重复的数字只出一份）**：
        · 原全景首块「全球指数概览（Yahoo 报价）」= 道指 / 标普 / 纳指 / 恒指 / 恒科，
          与报价块「全球与美股」「港股双指数」是同一次 Yahoo 抓取的同一份快照，
          逐项数字完全相同 → 整块删除（PANORAMA_GLOBAL_INDEX_SPECS 一并移除）；
        · 原全景「指数表现」（东财八大宽基）与报价块「A股四指数」有四个指数重复
          → 并成一张「A股指数」表，同名指数只出一行；
        · guizang「成交额」子块的沪 / 深 / 京市成交额就是上证指数 / 深证成指 / 北证50
          的同一批 f6 数字 → 指数表已带成交额列时不再重列（合计、环比、上一交易日保留）。
      **不丢数据**：合并后仍完整呈现逐项报价（含「截至 / 滞后 / 东财回补」标注）、
      A股八大宽基 + 成交额（东财独有的北证50 / 沪深300 / 上证50 / 中证500 一并入表）、
      涨跌家数与涨跌比情绪、成交额合计与环比、南北向成交总额（前一收盘）、
      板块热力领涨 / 领跌 TOP。同名指数取值按 _reconcile_market_snapshot 同一口径
      「日期新者胜」：东财行情日比 Yahoo 的 as_of 新才用东财价并标「（东财）」，
      无法比较日期就不动 Yahoo 的值；子块标题只在自己能支撑时写截止日期。
      **研判不混算**：原两栏各自的「⌁ AI 研判」保留为两行——「（报价面）」与
      「（A股全景面）」，两套口径的证据与概率算法都不变（不合成一个没有依据的概率）。
      **徽标 / 副标题**：两路数据各自出状态徽标并标明「报价 / A股全景」是哪一路，
      来源名用「 ＋ 」相接，暂缺的一路在副标题点名（如「暂缺：报价」）；任意一路成功
      即渲染该栏，两路都失败才整栏缺席。
      **不变的**：抓取逻辑与接口、数据源名称（实时行情 / A股大盘全景）、审计口径
      （总源数仍为 8，两路仍分别留痕）、当天检验与推送门禁、超长日报拆分逻辑。
      历史归档日报不改写。

  21. 第二批栏目更名（2026-09-29 按用户要求，只改标题文字，栏目内容 / 顺序 / 抓取 /
      推送门禁与拆分逻辑完全不变）：
        全球头条          → **【无敌帝王蟹】全球头条**
        趋势跟踪          → **【深海大鲨鱼】趋势跟踪**
        政策因子          → **【深海肥蓝鲸】政策因子**
        每周量化走势预测   → **【嗜血大白鲨】逐日走势量化分析**（按用户给的新名，标题不再带「每周」，
                          周度口径仍在栏目内如实披露：「未来 5 个交易日」「锚定 X 收盘」）
      四个标题集中定义为 SECTION_TITLE_GLOBAL_HEADLINES / SECTION_TITLE_TREND /
      SECTION_TITLE_POLICY / SECTION_TITLE_WEEKLY_FORECAST，与第 19 条的现行栏目常量并列，
      guizang 与 pixel 两个主题共用。
      **只改「标题文字」的边界**：数据源键名与审计标签（全球头条 / 国家政策（中国政府网）/
      每周走势预测 / Reddit…）、freshness_checker 与 backup_sources 的源名、新闻情绪里的
      来源归属（「全球头条1条」）、像素主题英文关卡名（GLOBAL HEADLINES / TREND TRACKING /
      POLICY SHOCK / WEEKLY FORECAST）与图标砖短标签一律不变——它们是数据线的名字，
      不是栏目标题。风险提示里的跨栏目引用（「『栏目名』第NN条」）指向正文栏目头，
      因此同步用新标题，读者按名字能找到栏目。历史归档日报不改写。

  22. 隐藏功能「市场数据库」（2026-10-01 按用户要求，output/market_db.py；2026-10-23 改为单源 + 备用源待命）：
      每天三次（北京时间 08:00 / 12:30 / 17:00）抓取股票行情快照，落库到
      output/market_db/YYYYMMDD.json（**文件以日期为名字**，当天三档写同一个文件），
      作为 AI 分析 / AI 预测 / AI 模型的基础数据（特征 + 标签数据集 / ai_context）。
      ① 单源优先 + 备用源待命：Yahoo Finance chart 为主源直取；仅当主源失败或漏采某只标的时，
         按顺序依次切换东方财富 push2、腾讯财经 qt、新浪财经 hq、通达信 mootdx（沪深）、
         东方财富 push2his 日K 等备用源补齐（主源已覆盖的标的绝不重复并发多源比价，全部失败不落库）；
      ② 自我检查：结构 / 时段 / 主备源可用性 / 标的覆盖 / 数值合理性 /
         跨时段与跨日跳变 / 当天行情时效 / 文件哈希，结论写进 self_check，可随时 verify。
      **边界**：不进日报正文、不进微信推送、不出现在 --help（隐藏入口 --stock-db，
      见 .github/workflows/market-db.yml），因此不改动日报的当天检验与推送门禁。

  23. 新增「【深水石斑鱼】港股行情」栏目 + 港股境外数据源（2026-10-02 按用户要求，
      output/hk_overseas.py）——**该栏目已于 2026-10-19 按用户要求整体下线，见第 30 条**：
      四路**境外**公开源，无需密钥、各自独立降级，取不到就少一行 / 整栏缺席，绝不编数字：
        ① Yahoo Finance Chart（query1 → query2 镜像）：港股指数（恒指 / 恒科 / 恒生国企）
           + 港股个股篮子（腾讯 / 阿里 / 美团 / 小米 / 中移动 / 友邦 / 港交所 / 平安）；
        ② Stooq（stooq.com → stooq.pl 镜像）：主源缺某只时补位；OCTOPUS_HK_CROSSCHECK=1
           时对主源价格做交叉校验，偏差 >1.5% 写进栏目说明（不覆盖主源数字）；
        ③ HKEX 港交所官网「每日市场统计」：市场层成交额；解析必须「数字 + 单位」成对
           才采纳，只有数字没有单位一律标暂缺（不做单位猜测）；
        ④ stealth 浏览器（tools/patchright-enhanced/probe.js，patchright）：
           渲染带 WAF 的香港站点（etnet 經濟通 / aastocks 阿斯達克 / HKEX），
           仅补主源没给的字段，**默认关闭**，OCTOPUS_HK_BROWSER=1 且本机装好
           Node + patchright + Chrome 才启用；只读公开页面，不登录、不绕付费墙。
      栏目口径：逐行标供数来源（YH/ST/HKEX/+BR）与行情日；snapshot=True（行情快照），
      因此不会单独把日报推过当天检验闸门；OCTOPUS_HK_OVERSEAS=0 可关闭整路采集。
      本条与既有栏目的分工：【及时秋刀鱼】AI 行情复盘给全市场报价快照（含港股双指数），
      【每日趋势量化推演】给逐日走势与港股概率模型，本栏给**境外口径的港股个股与市场层明细**。

  24. 隐藏「【无敌帝王蟹】全球头条」与「港股名家频道」两个栏目（2026-10-02 按用户要求，
      与同日隐藏「东方财富快讯」同一口径）：
      · 页面侧：两个 kicker（GLOBAL HEADLINES / HK GURU CHANNELS）退出正文顺序表
        REPORT_DATA_SECTIONS，_collect_report_parts 不再建区块，因此正文、像素主题
        关卡名与推送分条里都不再出现这两栏；
      · 数据侧完全不变：Google News 全球头条与港股名家频道（YouTube / 通用 RSS）
        照旧抓取，仍进数据覆盖审计（当天源 / 总源计数不变）、政策因子、策略研判、
        新闻情绪归因、逐栏 AI 研判与「AI帮你提鲜」的输入，freshness_checker 与
        backup_sources 的源名 / 阈值不动；
      · 风险提示：命中这两批标题时 shown=False（同东财快讯），保留完整标题展示，
        不再生成指向已隐藏栏目的锚点跳转（h-gh-* / h-hk-* 不再写入页面）；
      · 历史归档日报不改写。
  25. 「新闻情绪」栏目更名为「【亮亮灯光鱿鱼】新闻情绪因子量化分析」（2026-10-10
      按用户要求，标题常量 SECTION_TITLE_NEWS_SENTIMENT 与其余鱼名栏目同口径）：
      只改显示标题与 backup_sources 的 used_by 标注；数据源键名、审计标签、
      kicker（NEWS SENTIMENT）与 DNS/MOM/ANV 计算口径一律不变；历史归档日报不改写。
  26. 跨栏「同子栏」合并（2026-10-12 按用户要求：「给大纲，核对内容重复率，重复就合并同子栏」）：
      核对工具 tools/report_outline.py 把任一 HTML 日报拆成「栏目 → 子栏 / 行」两层大纲，
      按**数字事实**（价格 / 百分比 / 成交额 / 概率）与文本相似度两路口径算跨栏重复率。
      实测出的正文栏重复（结论三栏的复述是设计内行为，不计）按下面口径合并：
        · 同一批数据一份日报只展开一次；后出现的栏目**保留子栏标题**，只留一行
          「↳ 同子栏合并：…｜见 XX 栏目（同一批数据，不重复展示）」——数字不静默消失；
        · 指针指到**栏目名**（不带序号）：栏目序号按当日出场栏数动态编号，写死序号会在
          缺栏的那天指错栏目；
        · 合并只在「保留栏确实在场」时发生（保留栏缺席 → 原栏目照常出数字），
          绝不让指针指向一个没渲染出来的栏目（见 _panorama_heat_selection 与 lq_html）；
        · 结论三栏（总结 / 今日预判 / 短线速查卡）不参与合并：它们本来就负责复述结论。
      本版合并两处跨栏 + 三处栏内：
        ① 【及时秋刀鱼】AI 行情复盘 · 南北向资金（前一收盘）→ 只在【资金流动性分析】
           展开（环比 / z 值 / 分位 / 冲击成本 / 综合分，口径更专业）；
        ② 【六眼飞鱼】量化 MACD 策略 · 量化强度榜的涨跌 / 主力净流入 → 只在 AI 行情复盘
           「板块热力」展开（行情口径，附领涨股）；强度榜只留趋势分 / 趋势 / 信号。
        ③ 【亮亮灯光鱿鱼】新闻情绪：一条快讯常同时点名多只个股，同一篇标题只展开一次，
           后面几处留「↳ 同一篇：见 XX」，并在「市场情绪关键词」如实写「同题合并 N 条」；
           全量版「原因」行引用同篇标题时改写为「见下方证据」，不把长标题连贴两次。
        ④ 【滚滚翻车鱼】板块轮动：多个概念共用同一只港股观察篮子时，名单只展开一次，
           后面几行留「↳ 同一篮子：见 XX（N 只）」。
        ⑤ 🦐 活鲜词库点缀：同一份日报里同一句比喻只出现一次（撞句按确定性顺序换变体，
           登记表在 pipeline 逐栏生成时递进，词库函数本身无状态、同输入同输出）。
      OCTOPUS_SUB_MERGE=0 关闭（版式回到 2026-10-12 之前，仅用于对照）；
      逐条重复清单与未合并项的理由见《大纲-栏目重复率核对.md》，回归测试
      tests/test_sub_merge.py（数字只出现一次 / 保留栏缺席时逐字回旧行为 / 结论栏不受影响）。

  27. 新增「内地财经媒体源头」数据源（2026-10-12 按用户指定）：
      18 家内地财经 / 证券 / 科技媒体的公开标题池——中证网（中国证券报）、证券日报网、
      证券日报之声、中国基金报、财闻、经济参考网、IT之家、券商中国、每日经济新闻、
      北京商报网、21世纪经济报道、证券之星、证券时报网、和讯网、金融投资报、时代财经、
      经济观察网、凤凰网财经。
      口径与「港股新闻源头」完全一致（只读公开订阅、72h 窗口 + 可验证时区、来源域名白名单、
      只留标题 / 发布时间 / 原文链接；抓不到就如实标暂缺）；区别是**不做港股过滤**——
      这 18 家是内地财经媒体，标题进同一标题池，供新闻情绪因子、政策因子、策略研判与
      逐栏 AI 研判共用（新闻情绪里的「来源：内地财经媒体N条」即此源）。
      这些媒体多数 2022 年后已下线或从未提供官方 RSS，因此默认走「站内检索 RSS
      （Bing → Google News）」按站点取公开标题（数据线 mainland_news_rss）；谁拿到官方
      订阅地址，把 MAINLAND_NEWS_SOURCES 里对应条目的 feed 填上即自动优先走官方源。
      可调开关：OCTOPUS_MAINLAND_NEWS=0 整体关闭；OCTOPUS_MAINLAND_NEWS_PER_SOURCE、
      OCTOPUS_MAINLAND_NEWS_MAX 控制每源与全栏目条数上限。数据源键名「内地财经媒体源头」，
      审计标签「内地财经媒体（18家）」。页面可见位置有三处：① 趋势跟踪栏目的
      「内地财经媒体 ×18」源头行（报覆盖：几家有更新 / 扫描条数 / 进标题池条数；
      非入门版另列「覆盖面（内地源头 · 窗口内条数）」——**不在这里重复列标题**，
      标题只在被引用处出现，避免跨栏重复展示）；② 新闻情绪证据行 / 政策因子引用行
      （标题 + 媒体名 + 原文链接）；③ 总结「数据覆盖」行（缺失时按 18 家点名）。
  28. 微信推送标题改版（2026-10-13 按用户要求，只改标题文字，推送内容 / 分条 / 门禁不动）：
      · 新格式：`[OCTOPUS] 章鱼 AI · 上水日报 - MM/DD HH:MM`（强制推送为
        `...(强制) - MM/DD HH:MM`，状态报告为 `...(状态) - ...`，超长分条仍追加 ` (i/N)`）；
      · 前缀由 emoji「🐙」换成方括号关键词「[OCTOPUS]」：emoji 在部分微信客户端与转发链路
        会被裁掉，关键词既能在消息列表里一眼认出、也能直接用作消息过滤规则；
      · 只影响 PushPlus 的 title 字段：刊头、页面 `<title>`、正文与归档文件名仍用
        REPORT_TITLE「章鱼 AI · 上水日报」，不加 [OCTOPUS]；
      · 集中定义在 PUSH_TITLE_PREFIX / PUSH_TITLE_TIME_FMT，--push-only / 常规 / 强制 /
        状态四条推送路径统一走 build_push_title()，标题不会各写各的
        （回归测试 tests/test_push_split.py::PushTitleTests 按源码数调用点，漏改会红）；
      · 「日报未推送提醒」「日报推送失败提醒」两条纯文本告警的标题保持原样
        （仍带 🐙）：它们是提醒而非日报本体，不与 [OCTOPUS] 关键词混在一起。
  29. 【游资剑鱼】多专家流派趋势分析接入「🦑 AI帮你提鲜」（2026-10-13）：该栏目此前是
      正文表格里唯一没有大白话解读的分析栏（octopus_ren._GENERATORS 缺 "UZI TREND" 条目）。
      · 解读生成器 octopus_ren._ren_uzi_trend 只引用 run_trend() 结果里已有的数字
        （算出结果的标的数 / 评委数 / 规则数 / 票型 / 均分 / 定调分布 / 被门禁撤下的评委 /
        缺席标的），定调用语直接取 items 自带的 tone 文案，不另写一份翻译、不新造读数；
      · ctx["uzi"] 走 pipeline._uzi_result(data) 单一出口，与正文 blocks["UZI TREND"]
        渲染用的是同一份对象（同 _trend_section_stats 的「不另算一套」口径）；
      · 本栏没有概率口径 → _garnish_dir 返回 (None, None)，几率条整条缺席（不硬凑一个
        涨跌概率）；活鲜度点缀按「本次现算的分析栏」计活鲜，与其它分析栏一致；
      · available=False / items 为空 → 返回空串，栏目自动不加解读；
        OCTOPUS_REN=0 / --no-ren 与其它栏目同一开关。回归测试 tests/test_ren.py。
  30. 下线「【深水石斑鱼】港股行情」栏目及其专用数据线（2026-10-19 按用户要求）：
      · 栏目整体删除（不是隐藏）：正文顺序表 REPORT_FACT_SECTIONS 里的 "HK QUOTES"、
        SECTION_TITLE_HK_QUOTES 标题常量、像素 / 归藏 / 档案 / 社区 / lime 五套主题的
        hk_quotes_block 渲染钩子与各自的栏目图标映射（HK-MKT / 🏦）一并移除，
        页面、像素关卡名与微信分条里都不会再出现这一栏；
      · 数据线整体删除：output/hk_overseas.py（Yahoo / Stooq / HKEX / stealth 浏览器
        四路境外源）与 tests/test_hk_overseas.py 一并删除，采集入口不再调用，
        数据覆盖审计里也不再统计「港股境外数据源」这一路（总源数相应回落）；
      · 三个环境开关 OCTOPUS_HK_OVERSEAS / OCTOPUS_HK_BROWSER / OCTOPUS_HK_CROSSCHECK
        随之失效（代码里已无读取处），README 与 Actions 补丁说明同步更新；
      · 配套资产一并清理：只服务于该栏目的 stealth 浏览器工具
        tools/patchright-enhanced/（vendor 的上游仓库 + 本仓库的 probe.js 适配器）
        与 .github/patches/octopus-hk-browser.patch（只注入 OCTOPUS_HK_* 三个变量）删除；
      · 港股行情本身不受影响：恒指 / 恒科报价仍在【及时秋刀鱼】AI 行情复盘的
        「港股双指数」子块，港股概率模型仍在【嗜血大白鲨】逐日走势量化分析
        （2026-10-23 起「量化分析总览」下线后，这里是概率模型的唯一正文出口），
        删除的只是重复的境外个股明细那一栏
        （重复率见《大纲-栏目重复率核对.md》：与「港股概率走势分析」重复 32%）；
      · 历史归档日报（output/daily_report_*.html）按仓库惯例不改写，仍是当时的真实
        快照；output/latest.html 已按新口径去掉该栏并重排后续栏目序号。

  31. 新增「策略量化分析」5 个栏目（2026-10-21 按用户提供的「策略大类 → 细分策略」图）：
      图中 **权益多头{主观多头 / 量化多头}、纯债策略{纯债基金}、CTA策略{主观CTA /
      量化CTA}、套利策略{综合指数}** 共 4 大类 6 细分，落地为 1 个总览 + 4 个大类栏目：
        · 【策略总览】量化策略全景（kicker STRATEGY OVERVIEW）：分类映射表 → 大类横向
          对比（细分均值）→ 细分全景排名（按信号分）→ 市场状态 / 最强-最弱 / 离散度；
        · 【权益多头】【纯债策略】【CTA策略】【套利策略·综合指数】（STRATEGY EQUITY /
          BOND / CTA / ARBITRAGE）：大类小结 → 细分量化明细 → 成对细分对比或单细分
          收益 / 风险 / 趋势特征 → 结论句。
      方法（output/strategy_quant.py）：每个细分映射一个**可验证基准指数**——
      沪深300（000300.SS）/ 中证500（000905.SS）/ 国债ETF（511010.SS，缺则 BND）/
      GSG / DBC / 上证指数（000001.SS），经 providers.fetch_bars 取近 1 年已收盘日线，
      计算 5/20/60 日收益、年化波动、夏普（20 日）、最大回撤（60 日）、胜率（20 日）、
      MA20/MA60 趋势与信号分（−100~+100，只用于大类内排序，不是涨跌概率）。
      大类 = 细分均值，趋势一致沿用、分歧标「分化」；市场状态按权益 / 纯债 / CTA
      三类信号均值判定。
      **缺数不造假**：主基准取不到自动试备用基准（^GSPC / ^IXIC / BND / DBC / GSG /
      ^HSI），仍然取不到的细分如实标「暂缺」并把指标留空，绝不补造数字；整类无可用
      细分 → 该大类栏目缺席，并在「数据覆盖」点名。合成序列**默认关闭**，只有显式
      OCTOPUS_STRATEGY_DEMO=1（离线演示 / 测试）才启用确定性序列，结果 synthetic=True、
      页面额外点名「演示序列」并注明不可用于判断行情。
      编排与边界：collect_all_data 在行业轮动之后调用 fetch_strategy_quant()，写入
      data["策略量化"]，计入数据覆盖总源数；但本栏是**已收盘回看的内部衍生**
      （is_today=False + snapshot=True），不虚增当天源、不单独打开推送门禁；
      取数 / 计算 / 渲染各自 try，单栏异常只影响该栏。
      OCTOPUS_STRATEGY_QUANT=0 关闭全部 5 栏（不采集、不渲染、不进审计）。
      规则合成的统计口径，非投资建议；逐条口径见《策略量化分析-接入说明.md》，
      回归见 tests/test_strategy_quant.py。

  32. 下线「【蜉蝣天地水母】量化分析总览」+「今日预判」去掉涨跌概率（2026-10-23 按用户要求）：
      · **取消栏目**：正文顺序表 REPORT_OUTLOOK_SECTIONS 里的 "QUANT FORECAST"、
        SECTION_TITLE_QUANT_FORECAST 标题常量、_collect_report_parts 里建块的
        blocks["QUANT FORECAST"]、五套主题的栏目图标映射与
        octopus_ren 的解读生成器（_ren_quant_forecast / 生成器表 / 取数表 / 概率映射）
        一并移除——页面、微信分条与像素关卡名都不会再出现这一栏；
      · **只删栏目，不删模型**：港股量化引擎照常采集（仍计入数据覆盖总源数），
        港股概率走势分析仍并入「每日趋势量化推演」，资金流动性分析仍单独成栏；
        octopus_quant/render.render_forecast 作为可复用渲染函数保留（便于日后恢复）；
      · **今日预判不显示涨跌概率**：_conclusion_pairs 的「量化分析」只给 ▲▼■ 方向定调与
        目标交易日、「七日预测」只给整段方向与锚定日，不再写上涨概率 / P(7日涨)；
        octopus_ren._ren_forecast 改为只翻译方向定调与信号分，section_ren_block 对
        FORECAST 返回 p_pct=None → 栏首「涨跌概率 / 几率 ODDS METER」整条缺席；
      · 概率数字仍在「每日趋势量化推演」与「资金流动性分析」如实展示，口径 / 留痕 /
        结算不变；历史归档日报按惯例不改写。

  34. 一对多群组编码落位 `oai.1`（2026-10-23）：群组编码仍走 `PUSHPLUS_TOPIC`，代码里不写死；
      Actions 三个工作流（每日 / 手动 / 示例）把 Secret 缺省值兜底成 `${{ secrets.PUSHPLUS_TOPIC || 'oai.1' }}`
      ——配了 Secret 以 Secret 为准，没配则直接发到群组 oai.1，不再走「告警 + 回退一对一」；
      本地直跑仍以环境变量为准，未配置时照旧告警回退一对一（群里不会收到半截日报）。

  33. 推送模式由「一对一」改为「一对多」（2026-10-23 按用户要求）：
      · 默认 `PUSHPLUS_MODE=one2many`：带 topic 发到 PushPlus 群组，群组编码从
        `PUSHPLUS_TOPIC` 读取（环境变量 / GitHub Secret），代码里不写死任何编码；
      · 未配置群组编码 → 日志打印明确告警「PUSHPLUS_TOPIC 未配置 → 本次回退一对一」，
        绝不静默降级；`PUSHPLUS_MODE=one2one` 显式改回一对一直发自己（即使配了群组编码
        也不携带 topic），未知模式值告警后按默认一对多处理；
      · 路由集中在 `resolve_push_route()` 单一出口：显式 `topic` 参数（非空 = 群组、
        空串 = 强制一对一）优先于环境配置；`push_to_wechat` / `_push_one_message` /
        分条推送共用同一份解析，分条不会出现「前几条发群组、后几条发自己」；
      · Actions 工作流（每日 / 手动 / 示例）透传 `PUSHPLUS_TOPIC`（Secret）与
        `PUSHPLUS_MODE`（Variable，缺省 one2many）；页面、分条、重试与频率排队逻辑不变；
      · 回归见 tests/test_push_split.py::PushDeliveryModeTests（默认一对多、群组编码路由、
        缺失告警回退、one2one 忽略群组、未知模式告警、显式 topic 覆盖）。

退出码约定：
  0 = 正常完成（含 --no-push / --dry-run 等有意的跳过，或检验未通过但告警已送达）；
  1 = 应当推送却失败，或用法错误。

用法:
  python3 output/pipeline.py                  # 全流程（当天检验通过才推送）
  python3 output/pipeline.py --no-push        # 只生成，不推送
  python3 output/pipeline.py --dry-run        # 采集+预览，不推送
  python3 output/pipeline.py -o custom.html   # 指定输出路径
  python3 output/pipeline.py --manual         # 手动推送模式
  python3 output/pipeline.py --manual --force-push   # 手动强制推送（内容非当天）
  python3 output/pipeline.py --push-only              # 推送实际最后更新的一份日报（当天检验）
  python3 output/pipeline.py --push-only path/to/report.html
  python3 output/pipeline.py --list           # 列出日报

退出码：0 = 正常完成；1 = 应当推送却失败 / 用法错误（GitHub Actions 据此标红）。
"""
import os
import sys
import time
import argparse
import colorsys
import random
import re
import glob
import json
import threading
import xml.etree.ElementTree as ET
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from html import escape as _html_escape, unescape as _html_unescape
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse, parse_qs, unquote
from datetime import date, datetime, timezone, timedelta
from typing import Dict, List

try:
    import requests
except ImportError:
    print("❌ 缺少依赖 requests，请运行: pip install requests")
    sys.exit(1)

# ============================================================
# 全局配置
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = SCRIPT_DIR

# ============================================================
# 港股量化引擎（output/octopus_quant/）
# ------------------------------------------------------------
# 分层：providers(数据) → features(特征) → probability(概率/校准/回测) →
#       liquidity(资金流动性) → engine(编排) → render(呈现)。
# pipeline 只做两件事：注入取数函数 ``safe_request``、注入排版套件 ``kit``；
# 量化包不反向依赖日报，因此可完全离线单测（见 tests/test_quant.py）。
# 另有反馈闭环：每次预测写入 output/quant_history.json，之后按真实收盘结算
# 「方向命中 / 区间命中 / Brier」，模型表现自己记账。
# ============================================================
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import octopus_quant as _quant  # noqa: E402
from octopus_quant import sector_rotation as _sector_rotation  # noqa: E402
# A股申万一级行业轮动（2026-10-04 移植回上线）：独立于港股「板块轮动」，可整体关闭。
from octopus_quant import industry_rotation as _industry_rotation  # noqa: E402
# 【游资剑鱼】多专家流派趋势分析（2026-10-11 新增）：方法来自 vendored 的 UZI-Skill 规则引擎
# （tools/UZI-Skill，MIT，66 位评委 × 242 条规则），日线复用 MACD 栏目同一批，零新增联网。
from octopus_quant import uzi_trend as _uzi_trend  # noqa: E402
import octopus_weekly as _weekly  # noqa: E402
import octopus_ren as _ren  # noqa: E402
import octopus_short as _short  # noqa: E402  # 🎯 短线速查卡（≤600 字，日报结尾）
import sentiment_strategy as _senti_strategy  # noqa: E402  # 📐 散户情绪因子（有 Reddit / StockTwits 样本时渲染）
import media_risk as _media_risk  # noqa: E402  # 🚨 A/H 媒体舆情风险事件提取（规则分，不是概率）
import octopus_lexicon as _lex  # noqa: E402  # 🦐 活鲜词库（AI帮你提鲜 / AI 研判点缀）
import hk_seven_day as _hk7  # noqa: E402
import jev_bridge as _jev  # noqa: E402
import freshness_checker as _freshness  # noqa: E402
import backup_sources as _backup  # noqa: E402
import dedup as _dedup  # noqa: E402
import shiquan_poem as _shiquan  # noqa: E402  # 📜 诗泉（palemoky/chinese-poetry-api）卷首随机一首古诗词
import finance_analysis as _finance  # noqa: E402  # 🧩 本地 jieba 财经标题分析（情绪热点因子量化分析增强：词汇 + 情绪 + 风险词表）
import octopus_bagua as _bagua  # noqa: E402  # ☯ 今日八卦运程与利忌（「诗与远方的海」卷首栏）
try:
    import strategy_quant as _strategy_quant  # noqa: E402  # 📊 策略大类量化（图中 4 大类 6 细分，可离线兜底）
except Exception:  # pragma: no cover
    _strategy_quant = None

QUANT_HISTORY_FILENAME = "quant_history.json"
# 📜 诗泉（palemoky/chinese-poetry-api）开篇随机一首诗开关：OCTOPUS_SHIQUAN=0 可关闭。
SHIQUAN_ENABLED = _shiquan.is_enabled()
SHIQUAN_META_KEY = _shiquan.SHIQUAN_META_KEY
# 量化引擎开关：OCTOPUS_QUANT=0 或 --no-quant 可整体跳过（离线/赶时间时用）
HK_QUANT_ENABLED = str(os.environ.get("OCTOPUS_QUANT", "1")).strip().lower() not in ("0", "false", "no")
# 是否逐只跑个股概率（关掉后只出指数与流动性，明显更快）
HK_QUANT_STOCKS = str(os.environ.get("OCTOPUS_QUANT_STOCKS", "1")).strip().lower() not in ("0", "false", "no")
# A股概念 → 港股观察篮子轮动：独立于港股量化开关；OCTOPUS_SECTOR_ROTATION=0 可关闭。
SECTOR_ROTATION_ENABLED = str(os.environ.get("OCTOPUS_SECTOR_ROTATION", "1")).strip().lower() not in ("0", "false", "no")
SECTOR_ROTATION_SOURCE_NAME = "板块轮动量化策略"
# 申万一级行业轮动（A股 31 个行业 · 周度评分 + 月度纯多头组合）：与港股「板块轮动」
# 完全独立（不同股票池、不同数据线、不同存档键），OCTOPUS_INDUSTRY_ROTATION=0 可关闭。
INDUSTRY_ROTATION_ENABLED = str(os.environ.get("OCTOPUS_INDUSTRY_ROTATION", "1")).strip().lower() not in ("0", "false", "no")
INDUSTRY_ROTATION_SOURCE_NAME = "申万一级行业轮动策略"
INDUSTRY_ROTATION_SOURCE_LABEL = "东方财富 · 申万一级行业指数日线（31 个）"
# 策略研判内的 MACD 子策略：独立于港股概率引擎，优先市场库 / 本次日线，缺项补免费源。
MACD_ENABLED = str(os.environ.get("OCTOPUS_MACD", "1")).strip().lower() not in ("0", "false", "no")
MACD_SOURCE_NAME = "MACD量化策略"
# 【游资剑鱼】多专家流派趋势分析（独立栏目）：Weinstein 四阶段 + 均线排列 + 上游评委规则打分。
# OCTOPUS_UZI_TREND=0 或 --no-uzi-trend 关闭；规则引擎（tools/UZI-Skill）缺席时栏目自然缺席。
UZI_TREND_ENABLED = str(os.environ.get("OCTOPUS_UZI_TREND", "1")).strip().lower() not in ("0", "false", "no")
UZI_TREND_SOURCE_NAME = "UZI多流派趋势分析"
UZI_TREND_SOURCE_LABEL = "UZI-Skill 规则引擎（vendored）· 复用 MACD 栏目同一批已收盘日线"
# 每周量化走势预测开关：OCTOPUS_WEEKLY=0 或 --no-weekly 可整体跳过
WEEKLY_ENABLED = str(os.environ.get("OCTOPUS_WEEKLY", "1")).strip().lower() not in ("0", "false", "no")
WEEKLY_HISTORY_FILENAME = _weekly.JOURNAL_FILENAME
# 「AI帮你提鲜」开关（2026-09-29 新增，原名「鲜鲜解读」，2026-10-06 更名）：每个实际
# 渲染的数据栏目开头先放「🦑 AI帮你提鲜」结论区（字符图头 + 可用时的概率几率条 + 大白话），
# 再列同源量化依据与正文，帮入门读者先看懂结论；卷首诗 / 卦象不属于数据栏目。
# 纯规则合成（output/octopus_ren.py）：可复现、不伪造数字；专用生成器证据不足但正文存在时，
# 只给「证据不足、不硬判」后备结论，不补数字或方向。
# 2026-09-30 起解读末尾按行情状态确定性点缀「🦐 活鲜度」标签 + 一句活鲜比喻，
# 「⌁ AI 研判」行也按方向点缀一句短比喻——词库见 output/octopus_lexicon.py
# （条件驱动、点缀不含数字、认不出方向就不点缀；随 OCTOPUS_REN 一并开关）。
# OCTOPUS_REN=0 / --no-ren 整体关闭。
REN_ENABLED = _ren.ENABLED
# ------------------------------------------------------------
# 🎯 精简模式（2026-09-30 按用户要求：「内容再精炼，适合短线操作，入门观看」）
# 两件事，一个开关：
#   ① 日报末尾加「【闪电飞鱼】短线速查卡」——≤600 字收束今日动作要点
#      （明日剧本 / 七日风 / 今明必看时点 / 板块强弱 / 水位 / 风声 / 数据底），
#      末尾【新手三句话】从库文件（output/stock_memes.json，100 句股票梗句）读取并按盘面随时配对使用；
#   ② 全篇瘦身——**栏目一个不少、口径一句不隐**，只把重复展开的长文压成结论行：
#      日程只留今明 + 近端 ★★★、个股概率只留前5/后3、七日逐日理由压成一行、
#      校准曲线 / 分项评分 / 方法论长注折叠成一句、社区样本每组 2 条、
#      情绪逐股只留评分 + 1 条证据。被折叠 / 被裁的条数一律**如实披露**（不静默丢）。
# OCTOPUS_LITE=0 或 --full 回到全量长版（旧行为）。
# ------------------------------------------------------------
LITE_ENABLED = _short.ENABLED
# A/H 媒体舆情风险点：复用现有标题池与情绪历史，不新增联网；0 可独立关闭栏目。
MEDIA_RISK_ENABLED = str(os.environ.get("OCTOPUS_MEDIA_RISK", "1")).strip().lower() not in ("0", "false", "no")
# 量化呈现层（octopus_quant/render.py）跟日报同一个开关：--full / OCTOPUS_LITE=0 时
# 校准曲线表 / 分项评分表 / 五因子逐行 / 全量个股表全部回来。
_quant.render.LITE = LITE_ENABLED
# ------------------------------------------------------------
# 🐣 入门版（2026-10-03 按用户要求：「阅读不适合入门，减少说明文字、过程文字」）
# 精简模式之上再收一层：页面只留**结论、数字、动作**，下面这些「说明文字 / 过程文字」
# 整段不渲染（不是折叠成一句，而是不出现）：
#   · 方法论：计算口径 / 执行规则 / 回测口径 / 校准公式 / 无未来函数披露 / 派生策略规则；
#   · 过程：数据来源与供数路径、筛选过程、折叠条数、「--full 看全文」、动态权重依据、
#     概率修正明细、备用源启用清单、每栏重复的「规则合成 · 大白话翻译，非投资建议」副行。
# 结论、关键数字、风险提示、数据日期 / 非当天标记 / 暂缺点名一个不少；
# 新鲜度门禁、审计口径、留痕文件与 --full 全量长版完全不变。
#   --full / OCTOPUS_LITE=0 → 全量长版（说明文字全部回来）；
#   OCTOPUS_NOTES=1 / --notes → 精简版面里单独找回说明文字（即 2026-09-30 的精简版）。
# ------------------------------------------------------------
NOTES_REQUESTED = str(os.environ.get("OCTOPUS_NOTES", "0")).strip().lower() in ("1", "true", "yes")


def PLAIN():
    """入门版是否生效：精简模式开启、且没有要求保留说明文字。

    写成函数而不是常量：--full 与测试里 patch LITE_ENABLED 之后无需再同步第二个开关。
    """
    return bool(LITE_ENABLED) and not NOTES_REQUESTED


# 量化呈现层同步：render.PLAIN 只记录「是否要求说明文字」，入门版 = render.LITE and render.PLAIN。
_quant.render.PLAIN = not NOTES_REQUESTED


def set_notes_requested(flag):
    """切换「说明文字」开关（--notes / OCTOPUS_NOTES），同步量化呈现层；返回切换前的值。"""
    global NOTES_REQUESTED
    previous = NOTES_REQUESTED
    NOTES_REQUESTED = bool(flag)
    _quant.render.PLAIN = not NOTES_REQUESTED
    return previous


class notes_mode:
    """上下文管理器：块内临时打开 / 关闭说明文字（测试与二次渲染用），退出时恢复。

    with pipeline.notes_mode():          # 精简 + 说明文字（2026-09-30 的精简版）
        html = pipeline.generate_report(...)
    """

    def __init__(self, enabled=True):
        self.enabled = bool(enabled)
        self._previous = None

    def __enter__(self):
        self._previous = set_notes_requested(self.enabled)
        return self

    def __exit__(self, *exc):
        set_notes_requested(self._previous)
        return False
# 精简模式的版面预算（full 值 = 原有常量，一个都不动）：
#   键 → (精简值, 全量值)；LITE() 取当前模式那一档。
LITE_LIMITS = {
    "cal_days": (2, 0),              # 时间节点：正文只列今明两天（0 = 全窗口）
    "cal_rows": (12, -1),            # 且最多 N 行（全量档 = OCTOPUS_CALENDAR_ROWS，见 LITE）
    "cal_pairs": (3, 0),             # 窗口摘要只留 3 行（0 = 全部）
    "stock_rows": (8, 0),            # 个股概率表：前5 + 后3（0 = 全部）
    "sector_rows": (4, 6),           # 板块量化强度榜行数
    "sector_heat": (3, 5),           # A股全景板块热力 领涨/领跌 各几条
    "trend_evidence": (3, 0),        # 美联储/地缘 命中证据条数（0 = 全部）
    "trend_events": (4, 0),          # 未来相关时间点行数
    "news_per_source": (1, 3),       # 每个新闻源头列几条
    "news_total": (8, 24),           # 新闻源头正文条数总上限
    "site_posts": (2, 5),            # 每个社区板块/榜单的样本条数
    "senti_stocks": (2, 15),         # 情绪逐股：每市场最多几只
    "senti_headlines": (1, 3),       # 每只股票的证据标题条数
    "media_risk_stocks": (4, 8),     # 媒体风险：预警标的（按等级 / 风险指数排序）
    "media_risk_evidence": (2, 4),   # 媒体风险：每只标的列出的可追溯证据
    "em_summary": (60, 0),           # 东财快讯摘要截断字数（0 = 不截断）
    "notes": (0, 1),                 # 方法论长注：0 = 折叠成一句，1 = 全文
    "risk_cards": (2, 0),            # 风险提示卡条数（0 = 全部）
}


def LITE(key):
    """取当前模式的版面预算值（精简 / 全量两档，见 LITE_LIMITS）。

    全量档写 -1 表示「沿用原常量」（如 OCTOPUS_CALENDAR_ROWS 调过的日程行数上限），
    保证 --full / OCTOPUS_LITE=0 与 2026-09-30 之前的行为逐字一致。
    """
    lite, full = LITE_LIMITS[key]
    if LITE_ENABLED:
        return lite
    if full == -1 and key == "cal_rows":
        return ECON_CALENDAR_MAX_ROWS
    return full

# AI 七日港股走势分析概率开关：OCTOPUS_HK7=0 或 --no-hk7 可整体跳过；
# 大模型 Key 走 OCTOPUS_LLM_API_KEY（兼容 OPENAI_API_KEY / DEEPSEEK_API_KEY 等）。
HK7_ENABLED = str(os.environ.get("OCTOPUS_HK7", "1")).strip().lower() not in ("0", "false", "no")
HK7_HISTORY_FILENAME = _hk7.JOURNAL_FILENAME
HK7_SOURCE_NAME = "AI 七日港股走势分析概率"

# 时区
CST = timezone(timedelta(hours=8))  # 北京时间 / 澳门时间（东八区）

# PushPlus 配置
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_URL = "https://www.pushplus.plus/send"
# PushPlus 内容长度上限：实名用户 2 万字、会员用户 10 万字（账号已升级会员，默认按 10 万）。
# 超过上限的内容会被平台截断，截断点常落在标签中间，导致微信端整页排版崩坏
# （表现为整页只剩浅灰背景、正文缺失）。因此发送前先按完整标签边界截断并闭合标签，
# 末尾附「完整版」链接；磁盘上的日报文件始终保留完整版。
# 如账号额度变化，可用环境变量 PUSHPLUS_MAX_CONTENT_CHARS 覆盖（如 20000 / 100000）。
PUSHPLUS_MAX_CONTENT_CHARS = int(os.environ.get("PUSHPLUS_MAX_CONTENT_CHARS", "100000"))
# 完整推送：超过单条上限时，按完整栏目拆成多条独立 HTML 消息依次发送，全部明细不丢。
# PUSHPLUS_MULTIPART=0 可恢复旧行为（安全截断 + 完整版链接）；磁盘日报始终保留完整版。
PUSHPLUS_MULTIPART = str(os.environ.get("PUSHPLUS_MULTIPART", "1")).strip().lower() not in ("0", "false", "no")
# 多条推送之间的间隔秒数，避免触发 PushPlus「发送频繁」频率限制（每条仍各自退避重试）。
PUSHPLUS_PART_DELAY = float(os.environ.get("PUSHPLUS_PART_DELAY", "2"))
# PushPlus 频率限制：同一 token「1 分钟内接收 5 次请求，超出的请求将不再推送」。
# 分条推送时按这个窗口主动排队（而不是等被平台丢弃后再退避重试），保证每条都能送达。
PUSHPLUS_RATE_WINDOW = float(os.environ.get("PUSHPLUS_RATE_WINDOW", "60"))
PUSHPLUS_RATE_MAX = int(os.environ.get("PUSHPLUS_RATE_MAX", "5"))   # 0 = 关闭排队
# 渲染时插入的三个「分条标记」（HTML 注释，浏览器与微信端都不可见，不影响阅读）：
#   PART_BREAK_MARK   —— 每个栏目之前，拆分时优先切在这里，让每条消息尽量从完整栏目开始；
#   SECTION_BODY_MARK —— 栏目头与栏目正文之间，栏目被切开时续片据此重开栏目头（读者一眼看出在续哪一栏）；
#   DOC_FOOT_MARK     —— 页脚（免责声明）之前，它到文末的部分就是「页脚 + 全部闭合标签」。
# 有了这些标记，超长日报就能被切成 N 份「各自都是完整可渲染的 HTML 文档」：
# 每份 = 原文档头部外壳（含刊头）+ 条序横幅 + 若干完整栏目（可能含一栏的续片）+ 页脚 + 闭合标签，
# 微信端排版与单条推送完全一致，且全部内容按原顺序送达。
PART_BREAK_MARK = "<!--SPLIT-->"
SECTION_BODY_MARK = "<!--BODY-->"
DOC_FOOT_MARK = "<!--FOOT-->"
# 分条时的「栏目内续接」阈值：当前条剩余空间不足这么多字的正文时，不切开栏目，
# 整栏挪到下一条，避免出现「横幅 + 栏目头 + 一两行字」的碎片条。
PUSHPLUS_SPLIT_MIN_BODY = int(os.environ.get("PUSHPLUS_SPLIT_MIN_BODY", "1500"))
# 单份日报最多拆成多少条（防御性上限：正常 25 万字日报约 3 条）
PUSHPLUS_MAX_PARTS = int(os.environ.get("PUSHPLUS_MAX_PARTS", "12"))

# 推送路由（2026-10-23 按用户要求：由「一对一」改为「一对多」，见第 33 条）：
#   PUSHPLUS_MODE=one2many（默认）—— 带 topic 发到 PushPlus 群组（一对多）；
#                                    群组编码从 PUSHPLUS_TOPIC 读取，未配置时打印明确
#                                    告警并回退一对一，绝不静默降级、也不在代码里写死编码。
#   PUSHPLUS_MODE=one2one          —— 一对一 直发自己（历史口径），即使配了群组编码也不携带。
# 两个变量都支持「环境变量 / GitHub Secret 或 Variable」，改配置不需要改代码。
PUSH_MODE_ONE2MANY = "one2many"
PUSH_MODE_ONE2ONE = "one2one"
PUSH_MODES = (PUSH_MODE_ONE2MANY, PUSH_MODE_ONE2ONE)
PUSHPLUS_MODE = os.environ.get("PUSHPLUS_MODE", PUSH_MODE_ONE2MANY).strip().lower() or PUSH_MODE_ONE2MANY
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "").strip()

# ============================================================
# 推送主题（2026-08-21 起，一对一 / 一对多推送共用）
# ============================================================
# guizang —— 归藏主题：参考 guizang-ppt-skill 的 Style A「电子杂志 × 电子墨水」
#   （github.com/op7418/guizang-ppt-skill），改造成适合微信阅读的竖版长页面：
#   白色正文、黑底白字的紧凑标题、圆体字与 2px 实线分隔。微信优先：单列满宽；
#   行情 / 全景 / 情绪总览 / 政策冲击 / 数据审计等结构化数据用键值表整合。
#   图标在白底独立显示，正文与次要文字保持纯黑 / 深灰；不依赖颜色区分涨跌。
#   纯内联样式，不依赖 WebGL / JavaScript / 外部 CSS，兼容 PushPlus / 微信详情页。
# lime    —— 2026-10-10 起默认主题：白底圆角卡片 + 荧光绿强调风（与《整理-表格可视化.html》同款）：
#   白底画布 #FFFFFF + 浅灰圆角卡片 #F5F5F6 + 卡内白底 #FFFFFF / 浅灰 #ECECEF 交替块；
#   粗黑标题 #111111 + 荧光绿 #C8F03C 胶囊序号 / 章节小方块 / 信号条；全内联样式兼容微信。
# pixel   —— DOS 复古监视器 / Retro Pixel Market Quest v3（可切换）：
#   暗色街机终端底 #050711 + 霓虹青 / 电光蓝 / 像素黄 / 品红，直角像素块、硬描边与实色阴影；
#   等宽字栈、OCTOPUS_OS v3 标题栏、逐栏 LVL 关卡与 AI CORE 主控卡；全内联样式兼容微信。
# forum   —— 暗色社区仪表盘（Dark Mode Community Dashboard，可切换）：深灰画布 / 卡片、
#   柔和圆角与紫色点缀；dossier 为德国档案 + 包豪斯风，guizang 为克莱因蓝白底研报。
PUSH_THEMES = ("lime", "pixel", "forum", "dossier", "guizang")
DEFAULT_PUSH_THEME = "lime"


def _resolve_push_theme(name=None):
    """归一化推送主题：空 / 非法值一律回落到默认白底圆角卡片 + 荧光绿强调主题 lime。"""
    theme = name if name is not None else os.environ.get("OCTOPUS_PUSH_THEME", "")
    theme = str(theme or "").strip().lower()
    return theme if theme in PUSH_THEMES else DEFAULT_PUSH_THEME


# 当前默认主题（环境变量 OCTOPUS_PUSH_THEME 可覆盖；命令行 --theme 优先）
PUSH_THEME = _resolve_push_theme()

# 请求头
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ------------------------------------------------------------
# 港股名家频道（内容渠道配置，2026-08-02 起按用户指定列表）
# 每个频道可配置：
#   kind = "youtube"  → YouTube 频道，通过公开 RSS 抓取（无需 API Key），
#                       填 channel_id（最稳）或 handle（运行时自动解析，失败标记暂缺）
#   kind = "rss"      → 通用 RSS / Atom 源（如 Medium、Substack）
#   kind = "manual"   → 需登录 / 平台限制，暂无法自动抓取（页面标注「暂缺」及原因，不伪造内容）
# 每频道在日报中列出最新 CHANNEL_TOP_N 条内容。
# 需要增删频道或接入新平台时直接改这个列表即可。
# ------------------------------------------------------------
CHANNEL_TOP_N = 3

# 正文资讯栏目的展示条数（与 _collect_report_parts 的切片口径一致）。
# 风险引用去重依赖此口径：超出展示条数的风险标题正文不可见，风险提示保留全文。
GH_DISPLAY_N = 8    # 全球头条展示前 8 条
EM_DISPLAY_N = 5    # 东财快讯展示前 5 条

# ------------------------------------------------------------
# 「时间节点」栏目（原「未来 N 天影响经济时间点」）的数据口径
# （东方财富财经日历 RPT_CPH_FECALENDAR）
# 归入数据显示组，排在专业分析之后；用来核对未来 30 天可能影响市场的时点。
# 接口是东财数据中心公开报表（与 A股大盘全景的南北向资金同一台主机），无需密钥；
# START_DATE 为北京时间（形如 2026-10-28 20:30:00）。服务端只支持按日期过滤
# （按 CITY / FE_TYPE 过滤返回空），所以一次拉全窗口（翻页）再在本地按重要度筛选。
# 筛选口径全部写死在下面的常量里：确定性计算、可复现、不调大模型、不伪造内容；
# 读不到就在栏目与审计里如实标「暂缺」及原因。
# 前瞻性日程不属于「当天发布的内容」→ is_today=False + snapshot=True，
# 因此它永远不会单独把日报推过当天检验闸门（见 check_push_eligibility）。
# ------------------------------------------------------------
def _env_flag(name, default=False):
    """读布尔环境变量：1/true/yes/on/y 为真，其余为假；未设置取默认。"""
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "y")


def _env_int(name, default, lo, hi):
    """读整数环境变量：非法值回落 default，合法值夹在 [lo, hi]。"""
    try:
        value = int(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


# ============================================================
# 🔁 跨栏「同子栏」合并（2026-10-12 按用户要求：「核对内容重复率，重复就合并同子栏」）
# ------------------------------------------------------------
# 口径：同一批数据（同一个子栏）一份日报里只展开一次。后出现的栏目**保留子栏标题**，
# 只留一行指针「↳ 同子栏合并：… 见 XX 栏目」——数字不静默消失，读者仍知道去哪儿核对。
# 本版合并两处实测重复（核对脚本：tools/report_outline.py，可复现）：
#   ① 南北向资金（前一收盘）：【资金流动性分析】栏目更专业（环比 / z 值 / 分位 / 冲击成本 /
#      综合分），【及时秋刀鱼】AI 行情复盘 不再重复同一批成交总额（631.61 / 2,480.23 亿）；
#   ② 板块涨跌 + 主力净流入：AI 行情复盘的「板块热力」是行情口径（附领涨股），
#      【六眼飞鱼】量化 MACD 策略 的量化强度榜对已列出的板块只留趋势分 / 趋势 / 信号。
# 结论三栏（总结 / 今日预判 / 短线速查卡）**不参与合并**：它们的职责就是复述结论。
# 同源但口径不同的重复（社区样本计数、港股个股行情 vs 概率池、栏内概括行）不合并，
# 逐条理由写在《大纲-栏目重复率核对.md》，可用 --full 与 OCTOPUS_SUB_MERGE=0 对照。
# OCTOPUS_SUB_MERGE=0 → 回到 2026-10-12 之前：同一批数字多处重复（不推荐，仅用于对照）。
# ============================================================
SUB_MERGE_ENABLED = _env_flag("OCTOPUS_SUB_MERGE", True)
# 指针行统一文案（四套主题共用）：短前缀 + 数据所在栏目 + 口径说明。
SUB_MERGE_POINTER = "↳ 同子栏合并"
# 指针指到栏目名（不带栏目序号）：栏目序号按当日实际出场栏数动态编号，
# 写死序号会在缺栏的某天指向别的栏目 —— 用栏目名既稳又够reader定位。
SUB_MERGE_OWNER_MARKET_REVIEW = "【及时秋刀鱼】AI 行情复盘"
SUB_MERGE_OWNER_LIQUIDITY = "资金流动性分析"
SUB_MERGE_NOTE_FLOW = "南向 / 北向成交总额（成交总额口径）"
SUB_MERGE_NOTE_BOARD = "板块涨跌 / 主力净流入"


def _panorama_heat_selection(pan, theme=""):
    """12 栏「板块热力」本轮实际渲染的板块名集合（两个 panorama 渲染器同口径）。

    pixel 版不按版面预算切片（榜单 TOP 全出）；归藏 / lime / dossier / forum 版按
    LITE("sector_heat") 切。这里与渲染器读同一份 pan、用同一条切片规则，保证
    「01 栏指针指向的板块」在 12 栏里确实出现过，不会出现指向空气的死指针。
    """
    if not isinstance(pan, dict):
        return set()
    sec = pan.get("sectors") or {}
    limit = 0 if str(theme or "").strip().lower() == "pixel" else LITE("sector_heat")
    names = set()
    for key in ("leading", "lagging"):
        items = sec.get(key) or []
        for item in (items[:limit] if limit else items):
            name = str((item or {}).get("name") or "").strip()
            if name:
                names.add(name)
    return names


def sub_merge_pointer_text(text, owner=""):
    """指针行的值文案：`… ｜见 XX 栏目（同一批数据，不重复展示）`。"""
    if not owner:
        return text
    return f"{text}｜见 {owner}（同一批数据，不重复展示）"


# 「同一篇标题只展开一次」（2026-10-12 同子栏合并的**栏内**口径）：
# 一条快讯常常同时点名多只个股（行业 / 宏观类标题尤其如此），逐股证据行就会把同一篇
# 长标题重复贴 2~3 次。第一处照常展开，后面几处只留一行「↳ 同一篇：见 XX」——
# 标题不重复，但证据条数与因子计数一律照旧（不静默丢，只是不重复排版）。
SUB_MERGE_SAME_HEADLINE = "↳ 同一篇"
# 「同一只港股观察篮子」（07 板块轮动栏内）：多个概念共用同一批映射港股时，
# 名单只展开一次，后面的行只写「↳ 同一篮子：见 XX」+ 只数。
SUB_MERGE_SAME_BASKET = "↳ 同一篮子"


def senti_headline_owner(seen, title, stock_label):
    """同一篇标题的首次出现者：返回已登记过的个股标签；首次出现则登记并返回 ""。"""
    key = re.sub(r"\s+", "", str(title or ""))
    if not key:
        return ""
    owner = seen.get(key)
    if owner:
        return owner
    seen[key] = stock_label
    return ""


ECON_CALENDAR_ENABLED = str(os.environ.get("OCTOPUS_CALENDAR", "1")).strip().lower() not in ("0", "false", "no")
ECON_CALENDAR_DAYS = _env_int("OCTOPUS_CALENDAR_DAYS", 30, 1, 120)      # 前瞻窗口天数
ECON_CALENDAR_MAX_ROWS = _env_int("OCTOPUS_CALENDAR_ROWS", 60, 5, 300)  # 正文行数上限（版面保护）
ECON_CALENDAR_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
ECON_CALENDAR_REPORT = "RPT_CPH_FECALENDAR"
ECON_CALENDAR_COLUMNS = "START_DATE,END_DATE,FE_CODE,FE_NAME,FE_TYPE,STD_TYPE_CODE,CITY"
ECON_CALENDAR_PAGE = "https://data.eastmoney.com/cjrl/default.html"  # 溯源页（完整日历）


ECON_CALENDAR_SOURCE = "东方财富财经日历"
ECON_CALENDAR_PAGE_SIZE = 500   # 服务端单页上限
ECON_CALENDAR_MAX_PAGES = 8     # 30 天窗口实测 1 页足够，翻页只为窗口调大时兜底

# 保留地区：只留有定价权的市场，其余地区的读数不进正文（全窗口原始日程一月 300+ 条）。
CALENDAR_KEEP_CITY = (
    "中国", "美国", "欧元区", "欧盟", "日本", "英国", "中国香港",
    "加拿大", "澳大利亚", "韩国", "瑞士", "新西兰", "OPEC",
)
CALENDAR_CORE_CITY = ("中国", "美国")                     # 一级读数在这两个市场给 ★★★
CALENDAR_MAJOR_CITY = CALENDAR_CORE_CITY + ("欧元区", "欧盟", "日本", "英国")
# 事件类的最高重要度判定：① 中国宏观决策会议直接最高；② 主要央行 + 议息/决议动作。
# 注意：事件行的 CITY 字段常是城市名（如「华盛顿」「法兰克福」）而不是国家，
# 所以重要度只按名称里的「机构 + 动作」判定，不依赖地区字段。
CALENDAR_EVENT_TOP = (
    "国民经济运行情况发布会", "中国共产党中央全会", "中央全会", "中央经济工作会议",
    "政府工作报告", "全国人民代表大会", "政治局会议", "国务院常务会议",
)
CALENDAR_EVENT_ORG = (
    "美联储", "联邦储备", "欧洲央行", "欧央行", "日本央行", "英国央行", "瑞士央行",
    "加拿大央行", "澳洲联储", "新西兰联储", "韩国央行", "中国人民银行", "中国央行",
)
CALENDAR_EVENT_ACT = (
    "议息", "利率决议", "利率决定", "货币政策", "决议", "会议纪要", "发布会",
)
# 一级读数：真正驱动资产定价的宏观数据
CALENDAR_TIER3_KW = (
    "CPI", "PPI", "PCE", "GDP", "PMI", "非农", "失业率", "利率决议", "M2",
    "货币供应", "社融", "社会融资", "新增信贷", "LPR", "MLF", "工业增加值",
    "社会消费品零售", "固定资产投资", "进出口", "贸易帐", "贸易差额",
    "外汇储备", "工业企业利润", "货币政策会议纪要",
)
# 二级读数：重要但非核心（EIA 原油库存是每周真正推动油价的读数，显式保留）
CALENDAR_TIER2_KW = (
    "ISM", "初请", "ADP", "耐用品", "工业产出", "新屋", "成屋", "营建",
    "产能利用率", "零售销售", "消费者信心", "景气", "职位空缺", "时薪",
    "制造业", "服务业", "综合", "经济展望", "就业", "工业订单",
    "EIA原油库存", "EIA汽油库存", "EIA精炼油库存", "库欣原油库存",
    "出口", "进口", "利率", "汇率", "信贷", "贷款",
)
# 动态类（无 FE_TYPE：央行官员讲话 / 会议纪要 / 周报）里价值高的信号
CALENDAR_DYN_TIER2 = (
    "美联储主席", "美联储公布", "货币政策会议纪要", "利率决议", "主席鲍威尔",
    "非农", "议息", "CFTC", "OPEC", "月报",
)
# 个股事项：与「宏观时间点」无关，直接剔除（否则每只新股都是一条噪音）
CALENDAR_DROP_KW = (
    "新股申购", "新股上市", "限售解禁", "分红", "送转", "股东大会",
    "增持", "减持", "回购", "股权激励", "停牌", "复牌",
)
# 同名指标的冗余子序列（户籍口径失业率 / 现价 GDP / 汇率中间价…）
CALENDAR_DROP_NAME_KW = ("人口数", "现价", "折年数", "期末汇率", "人民币汇率", "战略储备", "预测年度")
CALENDAR_DROP_NAME_SFX = (":值",)   # 仅当名称以「:值」结尾才丢（否则会误杀「EIA原油库存:变动值」）
# 展会 / 论坛：对交易价值低，只给一星（正文触顶时最先被裁掉）
CALENDAR_LOW_KW = (
    "展览会", "博览会", "展会", "交易会", "糖酒会", "车展",
    "高峰论坛", "交流会议", "研讨会", "论坛",
)
CALENDAR_MAX_NAME_LEN = 40          # 超长条目（移仓换月提醒 / 停摆公告）既是噪音又占版面
CALENDAR_NOISE_TAG = ("[同传]", "（同传）", "(同传)", "【同传】")
CALENDAR_KIND_LABELS = {0: "数据", 1: "事件", 2: "动态"}
# 归一化时剥掉的修饰词：必须先归一化再判「是不是同一个指标」，
# 否则「CPI:当月同比」「CPI:累计同比」「CPI:季调:环比」会被当成三个指标，一天排出 6 行。
CALENDAR_CANON_DROP = ("季调", "非季调", "初值", "终值", "修正值", "预估值",
                       "折年率", "年化", "当月", "总计", "总值", "数据", "报告")
CALENDAR_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 趋势跟踪：多平台信息员（2026-09-28 起由单一 Reddit 扩为四平台）。
# 只读取公开热帖 feed / 公开 JSON，不登录、不绕过付费墙、不复制帖子正文；每个平台独立
# 采集、独立降级：单个平台访问失败只影响该平台，缺失平台在总结「数据覆盖」里点名。
# 平台顺序同时用于抓取、栏目渲染与审计展示，可用 OCTOPUS_TREND_PLATFORMS 单独关闭。
PUBLIC_SITE_NAMES = ("Reddit", "StockTwits", "TradingView", "Bogleheads")
PUBLIC_SITE_URLS = {
    "Reddit": "https://www.reddit.com/",
    "StockTwits": "https://stocktwits.com/",
    "TradingView": "https://www.tradingview.com/ideas/",
    "Bogleheads": "https://www.bogleheads.org/forum/",
}
PUBLIC_SITE_DESCRIPTIONS = {
    "Reddit": "散户论坛风向与热门标的：10 个财经/投资/金融/经济类板块各取热门帖子 5 条为样本",
    "StockTwits": "美股/加密散户情绪平台：趋势榜标的 + 平台多空讨论摘要 + 关注人数 + 消息情绪标签统计",
    "TradingView": "交易员公开观点平台：Ideas 最新观点标题（自带标的与技术面方向词）",
    "Bogleheads": "长期投资者论坛：Bogleheads 最新讨论主题（长期资金与配置视角）",
}
PUBLIC_SITE_WINDOW_HOURS = 72  # 各平台样本按发布时间过滤的窗口（小时）
REDDIT_POSTS_PER_BOARD = 5     # 每个板块的热门帖样本条数
STOCKTWITS_TRENDING_N = 8      # StockTwits 平台趋势榜取前 N 个标的
STOCKTWITS_STREAM_N = 3        # 取趋势榜前 N 个标的的最新消息做平台情绪标签统计
STOCKTWITS_MESSAGES_PER_STREAM = 30   # 每个标的最多读多少条公开消息（只统计标签，不复制正文）
TRADINGVIEW_IDEAS_N = 10       # TradingView 最新公开观点条数
BOGLEHEADS_TOPICS_N = 10       # Bogleheads 论坛最新主题条数

# ── 趋势跟踪 · 全网 36 个新闻源头（2026-09-28 新增）────────────
# 在 Reddit 板块热帖之外，固定跟踪全网 36 个新闻源头的公开 RSS/Atom 订阅，
# 按港股关键词挖掘与港股市场相关的信息，并用确定性规则合成分析（多空词概率 +
# 热点主题），随「趋势跟踪」栏目一起渲染。
# 设计约束（与 Reddit 源同一口径）：
#   · 只读公开订阅，不登录、不绕过付费墙；只保留标题、发布时间与原文链接，不复制正文；
#   · 每条链接按该源头自己的域名白名单校验（https + 主机名精确匹配），防止标题/链接注入；
#   · 只保留 72 小时窗口内、带可验证时区发布时间的条目；抓不到的源头如实标注暂缺与原因，
#     绝不用历史内容冒充更新；分析只做词表命中计数，不猜测、不编造。
# 源头分组：香港 7 / 内地 23 / 国际 6；顺序同时用于抓取、栏目与审计展示。
# 增删源头直接改 HK_NEWS_SOURCES；公共 RSSHub 实例被限流时用
# OCTOPUS_RSSHUB_BASE 换实例；OCTOPUS_HK_NEWS=0 可整体关闭本源。
HK_NEWS_SOURCE_NAME = "港股新闻源头"
RSSHUB_BASE = str(os.environ.get("OCTOPUS_RSSHUB_BASE", "https://rsshub.app")).rstrip("/")
HK_NEWS_ENABLED = str(os.environ.get("OCTOPUS_HK_NEWS", "1")).strip().lower() not in ("0", "false", "no")
HK_NEWS_PER_SOURCE = _env_int("OCTOPUS_HK_NEWS_PER_SOURCE", 3, 1, 8)  # 每源头最多保留的港股相关条数
HK_NEWS_MAX_ITEMS = _env_int("OCTOPUS_HK_NEWS_MAX", 24, 4, 60)        # 栏目正文港股相关条数总上限
HK_NEWS_SCAN_LIMIT = 12      # 每个源头先扫描的最新条目数（窗口过滤前）
HK_NEWS_WINDOW_HOURS = PUBLIC_SITE_WINDOW_HOURS  # 72 小时，与 Reddit 源同窗口

HK_NEWS_SOURCES = (
    # ── 香港本地（7）─────────────────────────────────────────────
    {"name": "RTHK 香港电台·财经", "region": "香港",
     "url": "https://news.rthk.hk/rthk/ch/index.shtml",
     "feed": "https://rthk.hk/rthk/news/rss/c_expressnews_cfinance.xml",
     "hosts": ("rthk.hk", "news.rthk.hk", "www.rthk.hk"),
     "desc": "香港电台中文财经新闻，本地利率、楼市与市况的一手消息"},
    {"name": "香港经济日报 HKET·财经", "region": "香港",
     "url": "https://www.hket.com/finance",
     "feed": "https://www.hket.com/rss/finance",
     "hosts": ("hket.com", "www.hket.com", "m.hket.com"),
     "desc": "香港经济日报财经频道，港股大市、新股与本地经济"},
    {"name": "南华早报 SCMP·Business", "region": "香港",
     "url": "https://www.scmp.com/business",
     "feed": "https://www.scmp.com/rss/92/feed",
     "hosts": ("scmp.com", "www.scmp.com"),
     "desc": "South China Morning Post 英文商业版，中国与香港市场视角"},
    {"name": "港交所·新闻稿", "region": "香港",
     "url": "https://www.hkex.com.hk/News/News-Release?sc_lang=en",
     "feed": "https://www.hkex.com.hk/Services/RSS-Feeds/News-Releases?sc_lang=en",
     "hosts": ("hkex.com.hk", "www.hkex.com.hk", "sc.hkex.com.hk"),
     "desc": "HKEX 官方新闻稿：上市规则、市场机制与交易安排改革"},
    {"name": "Now 新闻", "region": "香港",
     "url": "https://www.now.com/news",
     "feed": f"{RSSHUB_BASE}/now/news",
     "hosts": ("now.news", "www.now.com", "news.now.com", "www.nownews.com",
               "nowtv.com", "www.nowtv.com"),
     "desc": "Now 新闻本地要闻（经 RSSHub 公开订阅）"},
    {"name": "TVB 新闻", "region": "香港",
     "url": "https://news.tvb.com/tc/",
     "feed": f"{RSSHUB_BASE}/tvb/news",
     "hosts": ("news.tvb.com", "www.tvb.com", "tvb.com"),
     "desc": "无线新闻要闻与即时财经（经 RSSHub 公开订阅）"},
    {"name": "香港自由新闻 HKFP", "region": "香港",
     "url": "https://hongkongfp.com/",
     "feed": "https://hongkongfp.com/feed/",
     "hosts": ("hongkongfp.com", "www.hongkongfp.com"),
     "desc": "Hong Kong Free Press 英文独立媒体，香港政策与经济"},
    # ── 内地（7）───────────────────────────────────────────────
    {"name": "财联社·电报", "region": "内地",
     "url": "https://www.cls.cn/telegraph",
     "feed": f"{RSSHUB_BASE}/cls/telegraph",
     "hosts": ("cls.cn", "www.cls.cn", "m.cls.cn"),
     "desc": "财联社 7×24 电报快讯，盘中异动与政策信号（经 RSSHub）"},
    {"name": "格隆汇·实时快讯", "region": "内地",
     "url": "https://www.gelonghui.com/",
     "feed": f"{RSSHUB_BASE}/gelonghui/live",
     "hosts": ("gelonghui.com", "www.gelonghui.com"),
     "desc": "格隆汇 7×24 市场快讯，港股与美股中概动态（经 RSSHub）"},
    {"name": "智通财经·推荐", "region": "内地",
     "url": "https://www.zhitongcaijing.com/",
     "feed": f"{RSSHUB_BASE}/zhitongcaijing",
     "hosts": ("zhitongcaijing.com", "www.zhitongcaijing.com", "m.zhitongcaijing.com"),
     "desc": "智通财经港股美股资讯，大盘策略与个股解读（经 RSSHub）"},
    {"name": "证券时报·快讯", "region": "内地",
     "url": "https://www.stcn.com/",
     "feed": f"{RSSHUB_BASE}/stcn/article/list/kx",
     "hosts": ("stcn.com", "www.stcn.com", "finance.stcn.com", "news.stcn.com"),
     "desc": "证券时报网 7×24 快讯，监管与市场大事（经 RSSHub）"},
    {"name": "同花顺·7×24 要闻", "region": "内地",
     "url": "https://news.10jqka.com.cn/",
     "feed": f"{RSSHUB_BASE}/10jqka/realtimenews",
     "hosts": ("10jqka.com.cn", "www.10jqka.com.cn", "news.10jqka.com.cn",
               "stock.10jqka.com.cn", "finance.10jqka.com.cn"),
     "desc": "同花顺 7×24 全球财经直播，要闻与公告（经 RSSHub）"},
    {"name": "东方财富·策略研报", "region": "内地",
     "url": "https://data.eastmoney.com/report/strategyreport.html",
     "feed": f"{RSSHUB_BASE}/eastmoney/report/strategyreport",
     "hosts": ("eastmoney.com", "www.eastmoney.com", "data.eastmoney.com",
               "pdf.dfcfw.com", "reportapi.eastmoney.com"),
     "desc": "东财研究所策略研报，机构对大盘与港股的最新判断（经 RSSHub）"},
    {"name": "Google 新闻·中文港股聚合", "region": "内地",
     "url": "https://news.google.com/",
     "feed": ("https://news.google.com/rss/search?q="
              "%E6%B8%AF%E8%82%A1%20OR%20%E6%81%92%E7%94%9F%E6%8C%87%E6%95%B8"
              "&hl=zh-Hans&gl=CN&ceid=CN:zh-Hans"),
     "hosts": ("news.google.com",),
     "desc": "Google 新闻按「港股 OR 恒生指数」聚合的中文报道"},
    # ── 内地新增（2026-10-12 用户指定，16 家）────────────────────
    # 无公开 RSS 的媒体 feed 留空：直接走 Bing / Google 站内检索备用源（safe_request_with_fallback 自动跳过空地址）。
    {"name": "中证网", "region": "内地",
     "url": "https://www.cs.com.cn/", "feed": "",
     "hosts": ("cs.com.cn", "www.cs.com.cn", "news.cs.com.cn", "stock.cs.com.cn"),
     "desc": "中国证券报旗下财经证券网站，证券市场资讯与行情"},
    {"name": "证券日报网", "region": "内地",
     "url": "https://www.zqrb.cn/", "feed": "",
     "hosts": ("zqrb.cn", "www.zqrb.cn", "stock.zqrb.cn"),
     "desc": "证券日报官方网站，宏观经济、上市公司与资本市场动态"},
    {"name": "中国基金报", "region": "内地",
     "url": "https://www.chnfund.com/", "feed": "",
     "hosts": ("chnfund.com", "www.chnfund.com"),
     "desc": "基金行业媒体，公募、私募与 ETF 资讯"},
    {"name": "财闻网", "region": "内地",
     "url": "https://www.caiwennews.com/", "feed": "",
     "hosts": ("caiwennews.com", "www.caiwennews.com"),
     "desc": "财经、科技与法治综合资讯网站"},
    {"name": "经济参考网", "region": "内地",
     "url": "https://www.jjckb.cn/", "feed": "",
     "hosts": ("jjckb.cn", "www.jjckb.cn"),
     "desc": "新华社主管、经济参考报社主办的经济网站，政经与产经热点"},
    {"name": "IT之家", "region": "内地",
     "url": "https://www.ithome.com/", "feed": "https://www.ithome.com/rss/",
     "hosts": ("ithome.com", "www.ithome.com"),
     "desc": "科技媒体，科技企业与产业动态（港股相关条目经关键词筛选）"},
    {"name": "券商中国", "region": "内地",
     "url": "https://www.stcn.com/article/wx/qszg.html", "feed": "",
     "hosts": ("stcn.com", "www.stcn.com"),
     "desc": "证券时报旗下券商资讯栏目，券商研究与资本市场报道"},
    {"name": "每日经济新闻", "region": "内地",
     "url": "https://www.nbd.com.cn/", "feed": "",
     "hosts": ("nbd.com.cn", "www.nbd.com.cn"),
     "desc": "综合财经媒体，宏观、金融与上市公司报道"},
    {"name": "北京商报", "region": "内地",
     "url": "https://www.bbtnews.com.cn/", "feed": "",
     "hosts": ("bbtnews.com.cn", "www.bbtnews.com.cn"),
     "desc": "商业财经媒体，消费、金融与产业报道"},
    {"name": "21世纪经济报道", "region": "内地",
     "url": "https://www.21jingji.com/", "feed": "",
     "hosts": ("21jingji.com", "www.21jingji.com", "m.21jingji.com"),
     "desc": "财经深度媒体，宏观政策、产业与公司深度报道"},
    {"name": "证券之星", "region": "内地",
     "url": "https://www.stockstar.com/", "feed": "",
     "hosts": ("stockstar.com", "www.stockstar.com", "news.stockstar.com"),
     "desc": "证券资讯网站，股市行情、个股与基金资讯"},
    {"name": "和讯网", "region": "内地",
     "url": "https://www.hexun.com/", "feed": "",
     "hosts": ("hexun.com", "www.hexun.com", "finance.hexun.com", "news.hexun.com"),
     "desc": "财经门户，证券、基金与宏观资讯"},
    {"name": "金融投资报", "region": "内地",
     "url": "http://www.jrtzb.com.cn/", "feed": "",
     "hosts": ("jrtzb.com.cn", "www.jrtzb.com.cn"),
     "desc": "四川日报报业集团旗下财经报纸，证券与投资资讯"},
    {"name": "时代财经", "region": "内地",
     "url": "https://www.tfcaijing.com/", "feed": "",
     "hosts": ("tfcaijing.com", "www.tfcaijing.com"),
     "desc": "泛财经新闻平台，原创财经报道与企业动态"},
    {"name": "经济观察网", "region": "内地",
     "url": "https://www.eeo.com.cn/", "feed": "",
     "hosts": ("eeo.com.cn", "www.eeo.com.cn", "m.eeo.com.cn"),
     "desc": "经济观察报社网站，宏观经济、产业与公司观察"},
    {"name": "凤凰网财经", "region": "内地",
     "url": "https://finance.ifeng.com/", "feed": "",
     "hosts": ("finance.ifeng.com",),
     "desc": "凤凰网财经频道，宏观、股市与公司新闻"},
    # ── 国际（6）───────────────────────────────────────────────
    {"name": "Bloomberg·Markets", "region": "国际",
     "url": "https://www.bloomberg.com/markets",
     "feed": "https://feeds.bloomberg.com/markets/news.rss",
     "hosts": ("bloomberg.com", "www.bloomberg.com"),
     "desc": "彭博市场频道，全球风险偏好与利率主线"},
    {"name": "MarketWatch·头条", "region": "国际",
     "url": "https://www.marketwatch.com/",
     "feed": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
     "hosts": ("marketwatch.com", "www.marketwatch.com", "feeds.content.dowjones.io"),
     "desc": "MarketWatch 头条，美股与全球市场情绪"},
    {"name": "Investing.com·市场新闻", "region": "国际",
     "url": "https://www.investing.com/",
     "feed": "https://www.investing.com/rss/news_1.rss",
     "hosts": ("investing.com", "www.investing.com", "cn.investing.com", "m.investing.com"),
     "desc": "Investing.com 市场新闻，汇率、商品与股指联动"},
    {"name": "Financial Times·首页", "region": "国际",
     "url": "https://www.ft.com/",
     "feed": "https://www.ft.com/rss/home",
     "hosts": ("ft.com", "www.ft.com"),
     "desc": "金融时报全球头条，宏观与资本流动视角"},
    {"name": "BBC·Business", "region": "国际",
     "url": "https://www.bbc.com/news/business",
     "feed": "https://feeds.bbci.co.uk/news/business/rss.xml",
     "hosts": ("bbc.com", "www.bbc.com", "bbc.co.uk", "www.bbc.co.uk"),
     "desc": "BBC 商业新闻，英国与全球市场动态"},
    {"name": "Google 新闻·英文港股聚合", "region": "国际",
     "url": "https://news.google.com/",
     "feed": ("https://news.google.com/rss/search?q="
              "%22Hang%20Seng%22%20OR%20%22Hong%20Kong%20stocks%22"
              "&hl=en-US&gl=US&ceid=US:en"),
     "hosts": ("news.google.com",),
     "desc": "Google 新闻按「Hang Seng OR Hong Kong stocks」聚合的英文报道"},
)
HK_NEWS_TOTAL = len(HK_NEWS_SOURCES)  # 应为 36；测试会校验

# ── 内地财经媒体源头 · 18 家（2026-10-12 按用户指定新增）──────────────
# 与「港股新闻源头」同一套抓取口径（公开订阅、72h 窗口、可验证时区、来源域名白名单、
# 只留标题 / 发布时间 / 原文链接），区别只有两点：
#   ① 不做港股关键词过滤——这 18 家是内地财经 / 证券 / 科技媒体，其标题进
#      「标题池」供新闻情绪因子、政策因子、策略研判与逐栏 AI 研判共用；
#   ② 多数媒体 2022 年后已下线或从未提供官方 RSS，因此默认直接走
#      「站内检索 RSS（Bing → Google News）」按站点取公开标题（见 backup_sources
#      的 mainland_news_rss 数据线）；谁拿到官方订阅地址，把 feed 填上即自动优先走官方源。
# 只读公开信息，不登录、不绕付费墙、不复制正文；抓不到就如实标暂缺，绝不用历史内容兜底。
# OCTOPUS_MAINLAND_NEWS=0 整体关闭；OCTOPUS_MAINLAND_NEWS_PER_SOURCE / MAX 调版面预算。
MAINLAND_NEWS_SOURCE_NAME = "内地财经媒体源头"
MAINLAND_NEWS_ENABLED = _env_flag("OCTOPUS_MAINLAND_NEWS", True)
MAINLAND_NEWS_PER_SOURCE = _env_int("OCTOPUS_MAINLAND_NEWS_PER_SOURCE", 3, 1, 8)
MAINLAND_NEWS_MAX_ITEMS = _env_int("OCTOPUS_MAINLAND_NEWS_MAX", 48, 6, 120)
MAINLAND_NEWS_SCAN_LIMIT = 12                # 每个源头先扫描的最新条目数（窗口过滤前）
MAINLAND_NEWS_WINDOW_HOURS = PUBLIC_SITE_WINDOW_HOURS   # 72 小时，与其余新闻源同窗口
MAINLAND_NEWS_SECTION = "内地财经媒体"        # 标题池里的来源归属（新闻情绪 / 政策因子的「来源」列）

MAINLAND_NEWS_SOURCES = (
    {"name": "中证网（中国证券报）", "region": "内地",
     "url": "https://www.cs.com.cn/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("cs.com.cn", "www.cs.com.cn", "csnews.cs.com.cn"),
     "desc": "新华社《中国证券报》官网，资本市场权威披露与解读"},
    {"name": "证券日报网", "region": "内地",
     "url": "https://www.zqrb.cn/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("zqrb.cn", "www.zqrb.cn", "m.zqrb.cn"),
     "desc": "《证券日报》官网，证券市场信息披露与评论"},
    {"name": "证券日报之声", "region": "内地",
     "url": "https://www.zqrb.cn/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("zqrb.cn", "www.zqrb.cn", "m.zqrb.cn"),
     "desc": "证券日报社旗下新媒体品牌（与证券日报网同社同域名，跨源同题自动去重）"},
    {"name": "中国基金报", "region": "内地",
     "url": "https://www.chnfund.com/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("chnfund.com", "www.chnfund.com"),
     "desc": "资管 / 公募基金行业专业媒体（《中国基金报》社）"},
    {"name": "财闻", "region": "内地",
     "url": "https://www.caiwennews.com/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("caiwennews.com", "www.caiwennews.com"),
     "desc": "财闻网（持互联网新闻信息服务许可证），财经 / 科技 / 法治"},
    {"name": "经济参考网", "region": "内地",
     "url": "https://www.jjckb.cn/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("jjckb.cn", "www.jjckb.cn"),
     "desc": "新华社《经济参考报》官网，宏观政策与产业经济"},
    {"name": "IT之家", "region": "内地",
     "url": "https://www.ithome.com/",
     # 2026-10-13 实测官方订阅可用（https://www.ithome.com/rss/，最新条目比站内检索新约 11 小时）；
     # 官方源挂了才回退站内检索（记为备用源事件）。
     "feed": "https://www.ithome.com/rss/",
     "hosts": ("ithome.com", "www.ithome.com", "m.ithome.com"),
     "desc": "科技产业资讯（消费电子 / 半导体 / 互联网平台动态）"},
    {"name": "券商中国", "region": "内地",
     "url": "https://qzs.stcn.com/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("stcn.com", "qzs.stcn.com", "www.stcn.com", "quanzhongshe.com"),
     "desc": "证券时报社旗下新媒体「券商中国」（官方网址 qzs.stcn.com）"},
    {"name": "每日经济新闻", "region": "内地",
     "url": "https://www.nbd.com.cn/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("nbd.com.cn", "www.nbd.com.cn", "m.nbd.com.cn"),
     "desc": "《每日经济新闻》官网，公司 / 产业 / 资本市场报道"},
    {"name": "北京商报（北京商报网）", "region": "内地",
     "url": "https://www.bbtonline.com.cn/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("bbtonline.com.cn", "www.bbtonline.com.cn"),
     "desc": "《北京商报》官网，商业 / 消费 / 上市公司"},
    {"name": "21世纪经济报道", "region": "内地",
     "url": "https://www.21jingji.com/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("21jingji.com", "www.21jingji.com", "m.21jingji.com"),
     "desc": "南方财经全媒体集团旗下财经媒体，宏观与金融"},
    {"name": "证券之星", "region": "内地",
     "url": "https://www.stockstar.com/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     # 2026-10-13 实测：站内检索返回的多是 wap / hk 两个子域的原文链接，
     # 旧白名单不认这两个主机，条目会被整条剔掉，故补齐子域。
     "hosts": ("stockstar.com", "www.stockstar.com", "m.stockstar.com",
               "wap.stockstar.com", "hk.stockstar.com"),
     "desc": "证券之星，行情 / 基金 / 个股资讯与数据服务"},
    {"name": "证券时报网", "region": "内地",
     "url": "https://www.stcn.com/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("stcn.com", "www.stcn.com", "news.stcn.com", "finance.stcn.com"),
     "desc": "《证券时报》官网，7×24 快讯与监管 / 市场要闻"},
    {"name": "和讯网", "region": "内地",
     "url": "https://www.hexun.com/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     # 2026-10-13 实测：站内检索的原文链接分布在 bank / auto / futures 等频道子域，
     # 旧白名单只认 news / stock，故补齐频道子域。
     "hosts": ("hexun.com", "www.hexun.com", "news.hexun.com", "stock.hexun.com",
               "bank.hexun.com", "auto.hexun.com", "futures.hexun.com"),
     "desc": "和讯网，股票 / 基金 / 财经综合资讯"},
    {"name": "金融投资报", "region": "内地",
     "url": "https://www.jrtzb.com.cn/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("jrtzb.com.cn", "www.jrtzb.com.cn"),
     "desc": "四川《金融投资报》官网，证券市场与区域经济"},
    {"name": "时代财经", "region": "内地",
     "url": "https://www.tfcaijing.com/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("tfcaijing.com", "www.tfcaijing.com"),
     "desc": "南方传媒旗下深度财经媒体，企业与行业资本动态"},
    {"name": "经济观察网", "region": "内地",
     "url": "https://www.eeo.com.cn/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     "hosts": ("eeo.com.cn", "www.eeo.com.cn"),
     "desc": "《经济观察报》官网，宏观 / 产业 / 金融观察"},
    {"name": "凤凰网财经", "region": "内地",
     "url": "https://finance.ifeng.com/",
     "feed": "",          # 官方订阅地址（有就填这里；留空 = 走站内检索 RSS）
     # 2026-10-13 实测：site:ifeng.com 抓回来的 12 条里只有 1 条是财经（其余是资讯 /
     # 地方 / 汽车频道），改检索 finance.ifeng.com 后 12 条全为财经频道内容。
     "site": "finance.ifeng.com",
     "hosts": ("ifeng.com", "finance.ifeng.com", "www.ifeng.com"),
     "desc": "凤凰网财经频道，市场资讯与公司报道"},
)
MAINLAND_NEWS_TOTAL = len(MAINLAND_NEWS_SOURCES)   # 应为 18；测试会校验

HK_CHANNELS = [
    # ── 港股股评人 YouTube 频道（可自动抓取）─────────────────
    {"name": "郭思治（郭Sir）",
     "desc": "香港著名股評人，專注大盤技術走勢。",
     "kind": "youtube", "handle": "@KwokSirFinance"},

    # ── 需登录 / 暂未提供可抓取源（明确标注暂缺）────────────
    {"name": "曾廣標（股票分析）",
     "desc": "資深股評人，專注細價股與價值挖掘。",
     "kind": "manual",
     "note": "暂无官方可抓取频道；旧视频散见于「港股直播室 @hongkongstock」（2023 年后未更新）"},
    {"name": "陸羽仁（金融肉搏戰）",
     "desc": "老牌專欄，分析港股大局與政經關係。",
     "kind": "manual",
     "note": "信報專欄，非 YouTube；暂不支持自动抓取"},
    {"name": "青姐（胡孟青）",
     "desc": "風格辛辣，直擊港股市場痛點與散戶心態。",
     "kind": "manual",
     "note": "暂无官方频道；节目「胡孟青拆局」发布于 AASTOCKS 频道（@AASTOCKS_AATV）"},
    {"name": "智通財經App（微信公众号）",
     "desc": "每日推送港股早報與板塊機會。",
     "kind": "manual",
     "note": "微信公众号需登录，暂不支持自动抓取"},
    {"name": "港股那點事（格隆匯）（微信公众号）",
     "desc": "深度剖析港股上市公司實力。",
     "kind": "manual",
     "note": "微信公众号需登录，暂不支持自动抓取"},
    {"name": "球友大白（雪球 KOL）",
     "desc": "長線跟蹤港股高股息、藍籌股。",
     "kind": "manual",
     "note": "雪球需登录 / 反爬限制，暂不支持自动抓取"},
    {"name": "香港投資筆記（Medium）",
     "desc": "獨立分析師發表深度個股研究。",
     "kind": "rss", "feed_url": "",
     "note": "请提供 Medium 地址后接入 RSS"},
    {"name": "港股策略通訊（Substack）",
     "desc": "付費/免費的深度行業趨勢報告。",
     "kind": "rss", "feed_url": "",
     "note": "请提供 Substack 地址后接入 RSS"},
    {"name": "港股交易員（微博大V）",
     "desc": "實時更新盤中異動與傳聞。",
     "kind": "manual",
     "note": "微博需登录 / 反爬限制，暂不支持自动抓取"},

    # ── 第二批（2026-08-02 追加，用户指定）──────────────────
    {"name": "施凌部署",
     "desc": "結合宏觀經濟與技術分析的知名財經頻道；施凌部署為「我要做富翁」旗下品牌，於該官方頻道發布。",
     "kind": "youtube", "handle": "@Money-Tab"},
    {"name": "BofA Global Research（美銀研究）",
     "desc": "解讀大行對港股策略的官方影音；BofA Global Research 內容於 Bank of America 官方頻道發布（Must Read Research 系列）。",
     "kind": "youtube", "handle": "@BankofAmerica"},
    {"name": "秒投（ShareNews / StockViva）",
     "desc": "邀請多位香港股評人進行直播分析。",
     "kind": "youtube", "handle": "@StockViva"},
    {"name": "C基金 - 李浩德",
     "desc": "基金經理視角，分析港股大盤與科技股。",
     "kind": "youtube", "handle": "@CFund_Channel"},
    {"name": "Finance730",
     "desc": "探討香港財經、地產及股市走勢的專業網媒。",
     "kind": "youtube", "handle": "@Finance730hk"},
    {"name": "紅猴（Red Monkey）",
     "desc": "深度分析港股價值投資與公司基本面。",
     "kind": "manual",
     "note": "未找到独立官方频道；其视频散见于「成家網上投資課程」等第三方频道（多为 2022 年前旧内容）"},
    {"name": "米高（Michael）的財經頻道",
     "desc": "專注港股短線操作與期指分析。",
     "kind": "manual",
     "note": "未能在 YouTube 检索到明确的「米高 Michael 財經頻道」，请提供频道链接或 handle 后接入"},
    {"name": "小斯財經",
     "desc": "用深入淺出的方式講解港股與新股申購。",
     "kind": "manual",
     "note": "未能在 YouTube 检索到明确的「小斯財經」频道，请提供频道链接或 handle 后接入"},
    {"name": "智富同學會",
     "desc": "分享技術指標與港股實戰策略。",
     "kind": "manual",
     "note": "未检索到「智富同學會」独立频道；疑似相关频道「智富財經 Invest Smarter @investsmarter536」，如需接入请确认"},
    {"name": "港股研究社（Bilibili）",
     "desc": "面向內地投資者的港股解讀視頻（B站 UP 主，UID 613310838）。",
     "kind": "rss", "feed_url": "https://rsshub.app/bilibili/user/video/613310838",
     "note": "通过 RSSHub 抓取 Bilibili 投稿；如公共实例被限流，可更换其他 RSSHub 实例"},
]

YT_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}

# ============================================================
# 工具函数
# ============================================================
def _now():
    """返回当前北京时间字符串"""
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def _today_str():
    """返回今天日期字符串 YYYYMMDD"""
    return datetime.now(CST).strftime("%Y%m%d")


def _today_display():
    """返回今天的日期字符串 YYYY-MM-DD"""
    return datetime.now(CST).strftime("%Y-%m-%d")


def _date_display():
    """返回中文日期显示"""
    now = datetime.now(CST)
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{now.year}年{now.month}月{now.day}日 · {weekdays[now.weekday()]}"


def _esc(s):
    """HTML 转义"""
    if not s:
        return ""
    return (s.replace("&", "&amp;")
              .replace("<", "&lt;")
              .replace(">", "&gt;")
              .replace('"', "&quot;")
              .replace("'", "&#x27;"))


def _cst_from_iso(iso_str):
    """把 ISO8601 时间转为北京时间 datetime；失败返回 None。"""
    if not iso_str:
        return None
    try:
        iso = iso_str.replace("Z", "+00:00")
        return datetime.fromisoformat(iso).astimezone(CST)
    except Exception:
        return None


def _date_is_today(dt):
    """判断某个 datetime 是否属于今天（北京时间）。"""
    return bool(dt and dt.strftime("%Y%m%d") == _today_str())


def safe_request(url, headers=None, params=None, timeout=15, is_json=True):
    """安全请求，失败返回 None"""
    try:
        h = {**DEFAULT_HEADERS, **(headers or {})}
        resp = requests.get(url, headers=h, params=params, timeout=timeout)
        resp.raise_for_status()
        if is_json:
            return resp.json()
        return resp.text
    except Exception as e:
        print(f"  ⚠️ 请求失败 [{url[:60]}...]: {e}")
        return None


# 本次运行里「备用源顶上」的记录：[(数据线名, 备用源序号标签, 备用源说明)]，
# 采集结束写入 data["_backup_info"]["events"]，并在总结「数据覆盖」里点名，读者可知哪一路在供数。
BACKUP_EVENTS = []
_BACKUP_EVENTS_LOCK = threading.Lock()


def _note_backup_served(line, url, **fmt):
    """登记一次备用源命中（同一数据线同一路只记一次）。"""
    if not line or line not in _backup.DATA_LINES:
        return
    tag = _backup.label_for(line, url, **fmt)
    if tag == "主源":
        return
    label = next((lab for lab, u, _s in _backup.candidates(line, **fmt) if u == url), "")
    rec = (_backup.DATA_LINES[line]["name"], tag, label)
    with _BACKUP_EVENTS_LOCK:
        if rec not in BACKUP_EVENTS:
            BACKUP_EVENTS.append(rec)


def backup_events_text(events=None):
    """「数据覆盖」用：'实时行情 · Yahoo 日线快照→备用源1（Yahoo Finance query2）、…'。"""
    evs = BACKUP_EVENTS if events is None else events
    return "、".join(f"{name}→{tag}（{label.split('（')[0]}）" if label else f"{name}→{tag}"
                    for name, tag, label in evs)


def safe_request_with_fallback(urls, headers=None, params=None, timeout=15, is_json=True,
                               validate=None, line=None, fmt=None):
    """带备用源的安全请求：依次尝试 URL 列表（主源在前），任一 **有效** 即返回。

    validate —— 可选校验函数 validate(result) -> bool；镜像主机可能返回 200 但正文是
                {"data": null} / 空列表 / 错误页，这类响应视为失败并继续尝试下一路，
                否则备用源形同虚设（2026-09-29 重构前只判「非空 dict」）。
    line     —— backup_sources.DATA_LINES 的数据线 id；命中备用源时登记到 BACKUP_EVENTS。
    返回 (result, success_url, errors)。
    """
    if isinstance(urls, str):
        urls = [urls]
    urls = [u for u in urls if u]

    errors = []
    for url in urls:
        result = safe_request(url, headers=headers, params=params, timeout=timeout, is_json=is_json)
        if result is None:
            errors.append(f"{url[:60]}: 请求失败")
            continue
        if is_json and isinstance(result, dict) and not result:
            errors.append(f"{url[:60]}: 空字典")
            continue
        if not is_json and isinstance(result, str) and len(result.strip()) < 10:
            errors.append(f"{url[:60]}: 内容过短")
            continue
        if validate is not None:
            try:
                ok = bool(validate(result))
            except Exception:
                ok = False
            if not ok:
                errors.append(f"{url[:60]}: 返回内容无效")
                continue
        if url != urls[0]:
            print(f"  ✅ 备用源成功 [{url[:60]}...]")
            _note_backup_served(line, url, **(fmt or {}))
        return result, url, errors

    return None, None, errors


def _served_label(line, url, **fmt):
    """URL → 主源 / 备用源N（找不到数据线时返回空串）。"""
    if not line or not url or line not in _backup.DATA_LINES:
        return ""
    return _backup.label_for(line, url, **fmt)


# ============================================================
# 数据新鲜度与实时行情
# ============================================================
def _format_amount(val):
    """格式化成交额：显示亿/万，保留两位小数；负数保留负号（如主力净流出）。"""
    try:
        v = float(val)
        sign = "-" if v < 0 else ""
        a = abs(v)
        if a >= 1e8:
            return f"{sign}{a/1e8:.2f}亿"
        if a >= 1e4:
            return f"{sign}{a/1e4:.2f}万"
        return f"{v:.2f}"
    except (TypeError, ValueError):
        return str(val or "—")


def _source_result(source, status, is_today=False, content_date=None, **payload):
    """统一记录来源、抓取时间、当天标记和失败状态；绝不把历史文案伪装成实时数据。

    is_today      —— 该来源的内容是否属于「当天」（按北京时间判断）
    content_date  —— 该来源最新内容的日期（如最后收盘日 / 最新视频发布日），用于展示
    """
    return {
        "source": source, "status": status, "fetched_at": _now(),
        "is_today": bool(is_today), "content_date": content_date,
        **payload,
    }


def _source_note(item):
    """供 HTML 使用的数据来源状态（纯文字溯源行；状态以色块徽标另行表达）。"""
    if item.get("status") == "success":
        return f"{item.get('source', '数据源')} · 抓取于 {item.get('fetched_at', '—')}"
    detail = _esc(item.get("error", "暂时不可用"))
    return f"{item.get('source', '数据源')} 数据暂缺（{detail}）· 抓取于 {item.get('fetched_at', '—')}"


# 行情报价的品种分组：用于「按市场标注数据截至日」与「识别某个市场整体滞后」。
# 商品期货（WTI）周日晚间就开始下一交易日的电子盘，其 K 线日期天然领先股票指数，
# 因此不参与「整份快照属于哪一天」与「哪个市场滞后」的判断。
MARKET_QUOTE_GROUPS = (
    ("美股", ("道琼斯指数", "标普500", "纳斯达克", "微软 MSFT", "Meta META")),
    ("A股", ("上证指数", "深证成指", "创业板指", "科创50")),
    ("港股", ("恒生指数", "恒生科技")),
    ("商品", ("WTI 原油",)),
)
MARKET_LAG_EXEMPT_GROUPS = ("商品",)
# 东方财富独立时间基准（回补用）：港股指数 secid 代码 → 报价栏品种名
MARKET_HK_REFERENCE_CODES = {"HSI": "恒生指数", "HSTECH": "恒生科技"}


def _market_group_of(label):
    for group, labels in MARKET_QUOTE_GROUPS:
        if label in labels:
            return group
    return "其他"


def _market_group_dates(market):
    """{分组: 该组已取得报价里最新的 as_of 日期}（没有日期信息的品种不计）。"""
    out = {}
    for label, q in ((market or {}).get("quotes") or {}).items():
        if not isinstance(q, dict) or not q.get("as_of"):
            continue
        g = _market_group_of(label)
        if not out.get(g) or q["as_of"] > out[g]:
            out[g] = q["as_of"]
    return out


def _market_newest_session(market):
    """股票市场（美股 / A股 / 港股）里最新的一个数据日期；无日期信息返回 None。"""
    dates = [d for g, d in _market_group_dates(market).items()
             if g not in MARKET_LAG_EXEMPT_GROUPS]
    return max(dates) if dates else None


def _market_lagging(market):
    """返回 {品种: as_of}：数据日期落后于「股票市场最新日期」的品种（商品期货豁免）。

    典型场景：Yahoo 在交易所本地 0 点后暂时丢掉刚收盘日线且 meta / 东财回补都失败时，
    港股 / A股整组仍是上上个交易日，而美股是最新收盘 —— 这些品种不应再被当成最新行情
    参与「主要指数平均」，页面上也要写明日期。
    """
    newest = _market_newest_session(market)
    if not newest:
        return {}
    out = {}
    for label, q in ((market or {}).get("quotes") or {}).items():
        if not isinstance(q, dict) or not q.get("as_of"):
            continue
        if _market_group_of(label) in MARKET_LAG_EXEMPT_GROUPS:
            continue
        if q["as_of"] < newest:
            out[label] = q["as_of"]
    return out


def _refresh_market_dates(market):
    """按各品种 as_of 重算快照级日期字段（content_date / is_today / group_dates / lagging）。

    content_date 只看股票市场（美股 / A股 / 港股）的最新日期，不再被 WTI 电子盘或某一根
    「有时间戳但没有收盘价」的空 K 线拉成「当天」。
    """
    quotes = (market or {}).get("quotes") or {}
    if not quotes:
        return market
    newest = _market_newest_session(market)
    if not newest:
        dates = [q.get("as_of") for q in quotes.values() if isinstance(q, dict) and q.get("as_of")]
        newest = max(dates) if dates else None
    market["content_date"] = newest
    market["is_today"] = bool(newest) and newest == _today_display()
    market["group_dates"] = _market_group_dates(market)
    market["lagging"] = _market_lagging(market)
    return market


def _yahoo_quote_from_chart(data):
    """把一份 Yahoo Chart 响应解析成单品种报价：

    {price, change_pct, volume, currency, as_of, prev_date, via}
      · as_of    —— 「price」实际所属的交易日（取自有收盘价的那根 K 线，不是时间戳末尾的空 K 线）；
      · via      —— "bar"（日线）或 "meta"（Yahoo 暂缺刚收盘日线，用 meta 最新报价补出，见
                    octopus_quant.providers.session_bar_from_meta）。
    解析失败抛 ValueError（由调用方记入失败列表）。
    """
    result = data["chart"]["result"][0]
    bars = _quant.providers.parse_chart_result(result)
    if len(bars) < 2:
        raise ValueError("报价记录不足")
    last, prev = bars[-1], bars[-2]
    price, previous = float(last["close"]), float(prev["close"])
    if previous == 0:
        raise ZeroDivisionError("前收为 0")
    vol = last.get("volume")
    if vol in (None, ""):
        vols = [b.get("volume") for b in bars if b.get("volume") not in (None, "")]
        vol = vols[-1] if vols else 0
    return {"price": price, "change_pct": (price / previous - 1) * 100,
            "volume": vol or 0,
            "currency": (result.get("meta") or {}).get("currency", ""),
            "as_of": last["date"], "prev_date": prev["date"],
            "via": "meta" if last.get("from_meta") else "bar"}


def fetch_market_snapshot():
    """从 Yahoo Chart API 获取实际最新收盘/最新报价，不提供历史数字兜底。

    备用源（数据线 yahoo_chart）：query1 → query2（同格式）→ 东方财富行情快照（独立解析）；
    港股 / A股指数另有东方财富独立时间基准回补
    （见 _reconcile_market_snapshot，在 collect_all_data 里执行）。
    每个品种都记录自己的数据日期 as_of，页面按市场标注「截至 MM-DD」。
    """
    print("📡 正在抓取全球/A股实时行情...")
    specs = [
        ("道琼斯指数", "%5EDJI"), ("标普500", "%5EGSPC"), ("纳斯达克", "%5EIXIC"),
        ("WTI 原油", "CL=F"), ("微软 MSFT", "MSFT"), ("Meta META", "META"),
        ("上证指数", "000001.SS"), ("深证成指", "399001.SZ"),
        ("创业板指", "399006.SZ"), ("科创50", "000688.SS"),
        ("恒生指数", "%5EHSI"), ("恒生科技", "%5EHSTECH"),
    ]
    quotes, failures, meta_filled, served = {}, [], [], {}

    def _chart_ok(payload):
        try:
            _yahoo_quote_from_chart(payload)
            return True
        except (KeyError, TypeError, IndexError, ValueError, ZeroDivisionError):
            return False

    pending = []          # Yahoo 双主机都失败的品种 → 交给东方财富独立备用源
    for label, symbol in specs:
        # 数据线 yahoo_chart：主源 query1 → 备用源1 query2（同格式）→ 备用源2 东财（独立解析）
        yahoo_urls = [f"{url}?range=5d&interval=1d" for url in _backup.get_yahoo_urls(symbol)]
        data, success_url, errors = safe_request_with_fallback(
            yahoo_urls, validate=_chart_ok, line="yahoo_chart",
            fmt={"symbol": symbol})
        if not data:
            pending.append((label, symbol))
            continue
        try:
            quotes[label] = _yahoo_quote_from_chart(data)
        except (KeyError, TypeError, IndexError, ValueError, ZeroDivisionError) as exc:
            failures.append(f"{label}: {exc}")
            continue
        served[label] = "备用源1" if success_url != yahoo_urls[0] else "主源"
        if quotes[label]["via"] == "meta":
            meta_filled.append(f"{label}({quotes[label]['as_of'][5:]})")

    em_used = []
    if pending:
        em_quotes = _eastmoney_snapshot_quotes(pending)
        for label, symbol in pending:
            q = em_quotes.get(label)
            if q:
                quotes[label] = q
                served[label] = "备用源2"
                em_used.append(label)
            else:
                failures.append(f"{label}: Yahoo 主备与东财备用均失败")
        if em_used:
            print(f"  ✅ 备用源2（东方财富行情快照）顶上：{'、'.join(em_used)}")
            _note_backup_served("yahoo_chart", _backup.candidates("yahoo_chart", symbol="")[2][1])

    status = "success" if quotes else "unavailable"
    source_name = "Yahoo Finance Chart"
    if em_used:
        source_name += "（" + "、".join(em_used) + " 来自东方财富备用源）"
    market = _source_result(source_name, status,
                            quotes=quotes,
                            error="；".join(failures[:2]) or None,
                            partial=len(quotes) != len(specs))
    market["source_primary"] = "Yahoo Finance Chart"
    market["patched"] = []
    market["served_by"] = served
    _refresh_market_dates(market)
    if quotes:
        gd = market.get("group_dates") or {}
        span = " / ".join(f"{g} {gd[g]}" for g, _ in MARKET_QUOTE_GROUPS if gd.get(g))
        print(f"  ✅ 成功抓取 {len(quotes)}/{len(specs)} 个实时行情（数据日期 {span}）")
        if meta_filled:
            print("  ℹ️ Yahoo 日线暂缺刚收盘 K 线，已用 meta 最新报价补齐："
                  + "、".join(meta_filled))
        if market.get("lagging"):
            print("  ⚠️ 以下品种数据日期落后于最新交易日（页面将标注日期，不计入指数均值）："
                  + "、".join(f"{k}={v}" for k, v in market["lagging"].items()))
    else:
        print("  ⚠️ 实时行情暂不可用；日报将明确显示数据暂缺")
    return market


_EM_MARKET_CURRENCY = {"100": "", "105": "USD", "106": "USD", "107": "USD", "102": "USD",
                       "116": "HKD", "1": "CNY", "0": "CNY"}


def _eastmoney_snapshot_quotes(pairs, quote_urls=None):
    """行情报价的独立备用源（yahoo_chart 数据线的备用源2）：东方财富 ulist.np 一次批量取价。

    pairs —— [(品种名, Yahoo 代码)]；只处理能映射到东财 secid 的品种。
    返回 {品种名: quote}，quote 与 _yahoo_quote_from_chart 同结构（via="eastmoney"，
    as_of 取东财行情时间戳 f124 的北京日期，prev_date 未知记 None）。失败返回 {}。
    """
    secid_to_label = {}
    for label, symbol in pairs or []:
        secid = _backup.em_secid_for_yahoo(symbol)
        if secid:
            secid_to_label[secid] = label
    if not secid_to_label:
        return {}
    params = {"fltt": "2", "invt": "2", "secids": ",".join(secid_to_label),
              "fields": "f2,f3,f4,f12,f13,f14,f18,f124"}
    urls = quote_urls or _backup.get_eastmoney_ulist_urls()
    data, _, _ = safe_request_with_fallback(
        urls, params=params, timeout=12, line="em_ulist",
        validate=lambda d: bool(((d or {}).get("data") or {}).get("diff")))
    rows = ((data or {}).get("data") or {}).get("diff") or []
    out = {}
    for it in rows:
        secid = f"{it.get('f13')}.{it.get('f12')}"
        label = secid_to_label.get(secid)
        price, chg = _panorama_float(it.get("f2")), _panorama_float(it.get("f3"))
        if not label or price is None or chg is None or price <= 0:
            continue
        ts = _panorama_int(it.get("f124"))
        as_of = datetime.fromtimestamp(ts, CST).strftime("%Y-%m-%d") if ts else None
        currency = _EM_MARKET_CURRENCY.get(str(it.get("f13")), "")
        if str(it.get("f13")) == "100":
            code = str(it.get("f12") or "")
            currency = "HKD" if code.startswith("HS") else "USD"
        out[label] = {"price": price, "change_pct": chg, "volume": 0, "currency": currency,
                      "as_of": as_of, "prev_date": None, "via": "eastmoney",
                      "ref": "东方财富行情快照（备用源2）",
                      "quote_time": (datetime.fromtimestamp(ts, CST).strftime("%Y-%m-%d %H:%M:%S")
                                     if ts else None)}
    return out


def _fetch_hk_index_reference():
    """东方财富港股指数报价（含 f124 行情时间）——报价栏核对 / 回补港股行情的独立基准。"""
    try:
        return _quant.providers.fetch_hk_index_quotes(safe_request) or {}
    except Exception as exc:                      # 参考源失败只影响回补，不影响主流程
        print(f"  ⚠️ 东财港股指数参考报价失败：{exc}")
        return {}


def _reconcile_market_snapshot(market, pan=None, hk_ref=None):
    """用东方财富的独立时间基准核对 Yahoo 行情，回补「回退到上一个交易日」的港股 / A股指数。

    规则（只在东财数据日期**严格晚于** Yahoo 该品种 as_of 时替换；东财失败或日期相同不动）：
      · A股四指数：对照 A股大盘全景同一次抓取的东财指数（quote_time 为行情时间）；
      · 恒生指数 / 恒生科技：对照东财 100.HSI / 100.HSTECH（f124 行情时间）；
        Yahoo 完全没给港股报价时也用东财补上（港股是本日报的主市场）。
    替换后的品种 via="eastmoney"，记录 yahoo_as_of 供审计；快照级 content_date /
    is_today / lagging 重新计算；来源名追加「东方财富回补」。绝不回补成更旧的数字。
    """
    if not isinstance(market, dict) or market.get("status") != "success":
        return market
    quotes = market.setdefault("quotes", {})
    patched = list(market.get("patched") or [])

    def _apply(label, price, chg_pct, as_of, ref_name, quote_time=None):
        old = quotes.get(label) or {}
        if price is None or chg_pct is None or not as_of:
            return
        if old.get("as_of") and as_of <= old["as_of"]:
            return
        if old and not old.get("as_of"):
            return                           # 无法比较日期就不动 Yahoo 的值
        quotes[label] = {
            "price": float(price), "change_pct": float(chg_pct),
            "volume": old.get("volume") or 0, "currency": old.get("currency", ""),
            "as_of": as_of, "prev_date": None, "via": "eastmoney",
            "ref": ref_name, "quote_time": quote_time,
            "yahoo_as_of": old.get("as_of"),
        }
        patched.append(label)

    # ---- A股：对照全景复盘（东财 push2 ulist，f124 行情时间）----
    if isinstance(pan, dict) and pan.get("status") == "success":
        pan_date = str(pan.get("content_date") or "")[:10]
        pan_rows = {str(r.get("name")): r for r in (pan.get("indices") or []) if isinstance(r, dict)}
        if pan_date:
            for label in MARKET_QUOTE_GROUPS[1][1]:
                row = pan_rows.get(label)
                if row and label in quotes:          # A股只回补已有品种，不重复全景表
                    _apply(label, row.get("price"), row.get("chg_pct"), pan_date,
                           "东方财富·A股全景", pan.get("quote_time"))

    # ---- 港股：对照东财港股指数（100.HSI / 100.HSTECH）----
    for code, label in MARKET_HK_REFERENCE_CODES.items():
        ref = (hk_ref or {}).get(code) or {}
        if not ref or not ref.get("as_of"):
            continue
        _apply(label, ref.get("price"), ref.get("chg_pct"), ref["as_of"],
               "东方财富·港股指数", ref.get("quote_time"))

    market["patched"] = patched
    if patched:
        market["source"] = f"{market.get('source_primary') or 'Yahoo Finance Chart'} · 东方财富回补"
        print("  ✅ 东方财富回补（Yahoo 数据日期落后）："
              + "、".join(f"{k}→{quotes[k]['as_of']}" for k in patched))
    _refresh_market_dates(market)
    if market.get("lagging"):
        print("  ⚠️ 回补后仍滞后的品种："
              + "、".join(f"{k}={v}" for k, v in market["lagging"].items()))
    return market


def _quote_value(market, label, precision=2):
    quote = market.get("quotes", {}).get(label)
    if not quote:
        return f'<span style="color:{C_FAINT};">■ 数据暂缺</span>', C_FAINT
    price = quote["price"]
    pct = float(quote["change_pct"])
    color = C_GREEN if pct > 0 else (C_RED if pct < 0 else C_AMBER)
    # 数值用白色、涨跌用带箭头的高对比色块；即使用户存在色觉差异，也能靠 ▲/▼/■ 判断。
    # 这段数值只出现在账本表单元格里，因此跟随表格口径：缩小一号（13→12）且不加粗。
    value = (f'<span style="display:inline-block;color:{C_INK};font-size:{PIXEL_FS_LEDGER_NUM}px;'
             f'font-weight:{GZ_W_TABLE};font-family:{FONT_MONO};padding-right:6px;">'
             f'{price:,.{precision}f}</span>{_trend_badge(pct)}')
    return value, color


# 数据源 1：全球头条（Google News 中文版）
# ============================================================
GOOGLE_NEWS_RSS = {
    "zh": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
}


def _rfc2822_cst(pub_raw):
    """解析 RFC 2822 时间（如 Google News pubDate）为北京时间 datetime；失败返回 None。"""
    if not pub_raw:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(pub_raw).astimezone(CST)
    except Exception:
        return None


def fetch_google_news():
    """抓取 Google News 商业/财经头条（替换原 Yahoo Finance News 数据源）。

    直接抓 Google News 中文版，标题本身即中文，无需翻译；
    每条返回 {title, source, url, published_cst, is_today}。
    备用源：中文主站 → 香港中文 → 搜索兜底 → RSSHub
    """
    print("📡 正在抓取 Google News 全球头条...")
    # 数据线 google_news：主源 中文大陆版 → 备用源1 中文香港版 → 备用源2 搜索「财经」
    urls = _backup.get_google_news_urls("zh")
    xml_text, success_url, errors = safe_request_with_fallback(
        urls, is_json=False, timeout=15, line="google_news",
        validate=lambda t: "<item" in str(t))

    items = []
    if xml_text:
        try:
            root = ET.fromstring(xml_text)
            for item in root.findall("channel/item")[:12]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub = (item.findtext("pubDate") or "").strip()
                if not title:
                    continue
                # Google News 标题形如「原标题 - 来源名」，拆出来源
                src = ""
                m = re.search(r"\s+-\s+([^-]+)$", title)
                if m:
                    src = m.group(1).strip()
                    title = title[: m.start()].strip()
                pub_dt = _rfc2822_cst(pub)
                items.append({
                    "title": title,
                    "source": src,
                    "url": link,
                    "published": pub,
                    "published_cst": pub_dt.strftime("%Y-%m-%d %H:%M") if pub_dt else "—",
                    "is_today": _date_is_today(pub_dt),
                })
        except Exception as exc:
            print(f"  ⚠️ Google News RSS 解析失败: {exc}")

    if not items:
        print("  ⚠️ Google News 暂不可用，不显示历史兜底头条")
        return _source_result("Google News", "unavailable", headlines=[], error="未取得有效新闻")

    content_date = max((it["published_cst"][:10] for it in items if it["published_cst"] != "—"), default=None)
    is_today = any(it["is_today"] for it in items)
    print(f"  ✅ 成功抓取 {len(items)} 条全球头条（中文源，最新 {content_date}）")
    return _source_result("Google News", "success",
                          is_today=is_today, content_date=content_date,
                          headlines=items[:8])


# 数据源 1.x：AI趋势分析专题查询（Google News RSS 搜索）
# ============================================================
# 「【火爆大鱿鱼】美联储因子量化分析」「【巡回巨鲸】地缘政治因子量化分析」各自的专门抓取：
# 用 Google News RSS 搜索接口按主题查询，与「全球头条」（BUSINESS 头条流）互补。
# 词条口径写死、可复现；接口不可用时整栏缺席，绝不以旧闻或推算内容兜底。
GOOGLE_NEWS_SEARCH_RSS = ("https://news.google.com/rss/search?q={query}"
                          "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans")
FED_TREND_QUERY = "美联储 OR FOMC OR 鲍威尔"
GEO_TREND_QUERY = "地缘政治 OR 制裁 OR 冲突 OR 关税"
FED_TREND_KEY = "美联储趋势"
GEO_TREND_KEY = "地缘政治趋势"
FED_TREND_SOURCE = "Google News·美联储查询"
GEO_TREND_SOURCE = "Google News·地缘查询"


def _google_news_items(xml_text, limit=8):
    """Google News RSS（头条流 / 搜索流共用）条目解析：标题拆「原标题 - 来源」。"""
    items = []
    if not xml_text:
        return items
    try:
        root = ET.fromstring(xml_text)
        for item in root.findall("channel/item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            if not title:
                continue
            src = ""
            m = re.search(r"\s+-\s+([^-]+)$", title)
            if m:
                src = m.group(1).strip()
                title = title[: m.start()].strip()
            pub_dt = _rfc2822_cst(pub)
            items.append({
                "title": title,
                "source": src,
                "url": link,
                "published": pub,
                "published_cst": pub_dt.strftime("%Y-%m-%d %H:%M") if pub_dt else "—",
                "is_today": _date_is_today(pub_dt),
            })
    except Exception as exc:
        print(f"  ⚠️ Google News RSS 解析失败: {exc}")
    return items


def _fetch_news_search(query, source_name, limit=8):
    """Google News RSS 搜索查询抓取；失败如实标注 unavailable，不兜底旧内容。

    备用源：中文搜索 → 英文搜索 → RSSHub
    """
    # 数据线 google_news_search：主源 中文大陆版搜索 → 备用源1 中文香港版 → 备用源2 英文美国版
    primary_url = GOOGLE_NEWS_SEARCH_RSS.format(query=quote(query))
    backup_urls = _backup.get_google_news_urls("search", query=query)
    all_urls = [primary_url] + [u for u in backup_urls if u != primary_url]
    xml_text, success_url, errors = safe_request_with_fallback(
        all_urls, is_json=False, timeout=15, line="google_news_search",
        fmt={"query": quote(query)}, validate=lambda t: "<item" in str(t))
    items = _google_news_items(xml_text, limit=limit)
    if not items:
        print(f"  ⚠️ {source_name}暂不可用，不显示历史兜底")
        return _source_result(source_name, "unavailable", headlines=[],
                              error="未取得有效新闻", query=query)
    content_date = max((it["published_cst"][:10] for it in items
                        if it["published_cst"] != "—"), default=None)
    is_today = any(it["is_today"] for it in items)
    print(f"  ✅ 成功抓取 {len(items)} 条{source_name}（最新 {content_date}）")
    return _source_result(source_name, "success",
                          is_today=is_today, content_date=content_date,
                          headlines=items, query=query)


def fetch_fed_trend():
    """「【火爆大鱿鱼】美联储因子量化分析」专门抓取：Google News RSS 主题查询。"""
    print("📡 正在抓取美联储趋势专题（Google News 查询）...")
    return _fetch_news_search(FED_TREND_QUERY, FED_TREND_SOURCE)


def fetch_geo_trend():
    """「【巡回巨鲸】地缘政治因子量化分析」专门抓取：Google News RSS 主题查询。"""
    print("📡 正在抓取地缘政治趋势专题（Google News 查询）...")
    return _fetch_news_search(GEO_TREND_QUERY, GEO_TREND_SOURCE)


# 数据源 2：国家政策官方网站（中国政府网「最新政策」）
# ============================================================
# 中国政府网是国务院办公厅主办的中央人民政府门户网站。这里直接读取其「最新政策」
# 页面，不经过搜索引擎、转载媒体或 RSSHub；每条政策保留政府网原文链接与发布日期，
# 作为政策因子的独立输入。页面结构偶有调整，因此解析采用标准库正则，并只接受
# gov.cn/zhengce/ 下的政策正文链接，避免把导航、图片和第三方链接误计入因子。
GOV_POLICY_URL = "https://www.gov.cn/zhengce/zuixin/"
GOV_POLICY_FALLBACK_URL = "https://www.gov.cn/zhengce/"
GOV_POLICY_URLS = (GOV_POLICY_URL, GOV_POLICY_FALLBACK_URL)
GOV_POLICY_SOURCE_NAME = "中国政府网·最新政策"
NATIONAL_POLICY_TOP_N = int(os.environ.get("OCTOPUS_NATIONAL_POLICY_TOP_N", "30"))

_GOV_POLICY_ARTICLE_RE = re.compile(
    r"/zhengce/(?:content/)?20\d{2}(?:(?:\d{2})|(?:[-_/]\d{1,2}){1,2})/content_\d+\.html?$",
    re.I,
)
_GOV_POLICY_DATE_RE = re.compile(
    r"(?<!\d)(20\d{2})\s*(?:[-/.年－—])\s*(\d{1,2})\s*(?:[-/.月－—])\s*(\d{1,2})\s*(?:日|号)?",
)


def _strip_html_text(fragment):
    """去掉 HTML 标签并解码实体，供政府网列表标题/日期解析使用。"""
    fragment = fragment or ""
    fragment = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", fragment)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = _html_unescape(fragment).replace("\xa0", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", fragment).strip()


def _normalise_policy_date(value):
    """把政府网常见的 YYYY-MM-DD / YYYY/MM/DD / 中文日期归一化。"""
    if not value:
        return ""
    match = _GOV_POLICY_DATE_RE.search(str(value))
    if not match:
        return ""
    year, month, day = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _gov_policy_date_after_anchor(html_text, anchor_end, anchor_start):
    """从政策链接所在列表项提取发布日期；没有明确日期时返回空字符串。

    日期必须来自链接附近的可见列表文本，不从 URL 的月份或抓取日期推断，
    这样不会把未知发布日期伪装成当天政策。
    """
    lower = html_text.lower()
    item_end_match = re.search(r"</li\s*>", lower[anchor_end:anchor_end + 1200], re.I)
    if item_end_match:
        item_end = anchor_end + item_end_match.start()
    else:
        # 非 li 模板也常把每项写成连续的 div/a；避免把下一条政策的日期
        # 错配给当前标题，只在下一个链接前寻找当前项的尾部日期。
        next_anchor = re.search(r"<a\b", lower[anchor_end:], re.I)
        item_end = (anchor_end + next_anchor.start()
                    if next_anchor else anchor_end + 800)
    item_end = min(len(html_text), item_end)
    tail = _strip_html_text(html_text[anchor_end:item_end])
    date = _normalise_policy_date(tail)
    if date:
        return date

    # 少数模板把日期放在链接前的同一 <li> 中。
    item_start = lower.rfind("<li", 0, anchor_start)
    if item_start >= 0:
        prefix = _strip_html_text(html_text[item_start:anchor_start])
        date = _normalise_policy_date(prefix)
    return date


def _parse_gov_policy_html(html_text, limit=None):
    """解析中国政府网「最新政策」列表，返回带官方原文链接的政策条目。

    返回字段兼容新闻标题存档：title/source/url/date/published_cst/is_today/official。
    只有政策正文链接会被接受；没有日期的条目仍保留展示，但不会进入自然日政策窗口。
    """
    if isinstance(html_text, bytes):
        html_text = html_text.decode("utf-8", errors="replace")
    if not isinstance(html_text, str) or not html_text.strip():
        return []
    try:
        limit = max(1, int(NATIONAL_POLICY_TOP_N if limit is None else limit))
    except (TypeError, ValueError):
        limit = 30

    items, seen = [], set()
    anchor_re = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a\s*>", re.I | re.S)
    for match in anchor_re.finditer(html_text):
        attrs = match.group("attrs")
        href_match = re.search(r'\bhref\s*=\s*(["\'])(.*?)\1', attrs, re.I | re.S)
        if not href_match:
            continue
        href = _html_unescape(href_match.group(2).strip())
        url = urljoin(GOV_POLICY_URL, href)
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not (
                host == "gov.cn" or host.endswith(".gov.cn")):
            continue
        path = parsed.path or ""
        if not _GOV_POLICY_ARTICLE_RE.search(path):
            continue
        title = _strip_html_text(match.group("body"))
        if len(title) < 2:
            continue
        date = _gov_policy_date_after_anchor(html_text, match.end(), match.start())
        key = (url, title)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": title[:200],
            "source": "中国政府网",
            "url": url,
            "date": date,
            "time": date,
            "published_cst": date or "—",
            "is_today": bool(date and date == _today_display()),
            "official": True,
        })
        if len(items) >= limit:
            break
    return items


def fetch_gov_policy():
    """抓取中国政府网最新政策，作为政策因子的官方发布信息源。

    优先读取 ``/zhengce/zuixin/``，该页面失败或结构变化时再读取政策首页。
    不以历史存档兜底：抓不到官方页面就明确返回 unavailable。
    备用源：gov.cn 主站多路径 → 政策文库
    """
    print("📡 正在抓取中国政府网·最新政策（政策因子官方源）...")
    failures = []
    gov_urls = _backup.get_gov_policy_urls()
    # 去重并保留原有 GOV_POLICY_URLS 优先
    all_urls = list(dict.fromkeys(list(GOV_POLICY_URLS) + gov_urls))
    for url in all_urls:
        html_text, success_url, errors = safe_request_with_fallback([url], is_json=False, timeout=15)
        if not html_text:
            failures.append(f"{url}: {errors[0][1] if errors else '抓取失败'}")
            continue
        items = _parse_gov_policy_html(html_text)
        if not items:
            failures.append(f"{url}: 未解析到政策正文")
            continue
        dates = [it["date"] for it in items if it.get("date")]
        content_date = max(dates) if dates else None
        is_today = any(it.get("is_today") for it in items)
        if url != all_urls[0]:
            _note_backup_served("gov_policy", url)
        print(f"  ✅ 中国政府网抓取 {len(items)} 条最新政策（最新发布 {content_date or '日期暂缺'}）")
        return _source_result(
            GOV_POLICY_SOURCE_NAME, "success", is_today=is_today,
            content_date=content_date, headlines=items,
            official=True, page_url=url,
            error="；".join(failures[:1]) or None,
            partial=len(items) < min(5, NATIONAL_POLICY_TOP_N),
        )

    print("  ⚠️ 中国政府网最新政策暂不可用，不使用历史政策兜底")
    return _source_result(
        GOV_POLICY_SOURCE_NAME, "unavailable", headlines=[], official=True,
        page_url=GOV_POLICY_URL, error="；".join(failures[:2]) or "未取得官方政策信息",
    )


# 公开两个语义等价的入口，便于外部定时任务/测试按「国家政策」或「政府网」命名调用。
fetch_national_policy = fetch_gov_policy
fetch_national_policy_updates = fetch_gov_policy
fetch_national_policies = fetch_gov_policy


# 数据源 3：东方财富快讯（免费 API，5 条最新新闻）
# ============================================================
EASTMONEY_NEWS_URLS = [
    "https://np-weblist.eastmoney.com/comm/web/getNewsByColumns",
    "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns",
]


def fetch_eastmoney_news():
    """抓取东方财富最新财经新闻（免费接口，无 API Key，取 5 条）。

    备用源：np-listapi → np-weblist → panorama
    """
    print("📡 正在抓取东方财富快讯...")
    params = {
        "client": "web", "biz": "web_news_col", "column": "350",
        "order": "1", "needInteractData": "0",
        "page_index": "1", "page_size": "10",
    }
    news, content_dates = [], []
    # 数据线 em_news：主源 np-weblist → 备用源1 np-listapi（同格式）→ 备用源2 新浪 7×24（独立解析）
    all_urls = list(dict.fromkeys(list(EASTMONEY_NEWS_URLS) + _backup.get_eastmoney_news_urls()))

    def _news_list(payload):
        try:
            return ((payload.get("data") or {}).get("list")) or []
        except AttributeError:
            return []

    data, success_url, errors = safe_request_with_fallback(
        all_urls, params=params, timeout=12, line="em_news",
        validate=lambda d: bool(_news_list(d)))
    source_name = "东方财富"
    for it in _news_list(data)[:10] if data else []:
        title = re.sub(r"<[^>]+>", "", (it.get("title") or it.get("name") or "")).strip()
        if not title:
            continue
        raw_time = str(it.get("showTime") or it.get("createTime") or it.get("publishTime") or "")
        news.append({
            "title": title[:120],
            "url": it.get("url") or it.get("articleUrl") or "",
            "time": raw_time[:16],
            "summary": re.sub(r"<[^>]+>", "", (it.get("summary") or it.get("digest") or ""))[:80],
            "is_today": raw_time[:10] == _today_display(),
        })
        if raw_time[:10]:
            content_dates.append(raw_time[:10])
    if not news:
        news, content_dates = _sina_live_news_items()
        if news:
            source_name = "新浪财经 7×24（东方财富快讯备用源2）"
            print("  ✅ 备用源2（新浪财经 7×24）顶上：东财快讯接口不可用")
            _note_backup_served("em_news", _backup.candidates("em_news")[2][1])

    if not news:
        print("  ⚠️ 东方财富快讯暂不可用，不显示历史兜底资讯")
        return _source_result("东方财富", "unavailable", headlines=[], error="未取得有效资讯")
    content_date = max(content_dates) if content_dates else None
    is_today = any(n["is_today"] for n in news)
    print(f"  ✅ 成功抓取 {len(news)} 条{'东财快讯' if source_name == '东方财富' else '快讯（新浪备用）'}"
          f"（最新 {content_date or '—'}）")
    return _source_result(source_name, "success",
                          is_today=is_today, content_date=content_date,
                          headlines=news[:5])


def _sina_live_news_items(limit=10):
    """新浪财经 7×24 快讯（em_news 数据线的独立备用源2）。

    接口 zhibo.sina.com.cn/api/zhibo/feed（zhibo_id=152 财经）：
    result.data.feed.list[] → {rich_text, create_time, docurl}；
    返回 (与东财快讯同结构的列表, 内容日期列表)。取不到返回 ([], [])。
    """
    data, _, _ = safe_request_with_fallback(
        [_backup.SINA_LIVE_NEWS_URL], timeout=12,
        validate=lambda d: bool(((((d or {}).get("result") or {}).get("data") or {})
                                 .get("feed") or {}).get("list")))
    if not data:
        return [], []
    rows = (((data.get("result") or {}).get("data") or {}).get("feed") or {}).get("list") or []
    news, dates = [], []
    for it in rows:
        if not isinstance(it, dict):
            continue
        text = re.sub(r"<[^>]+>", "", str(it.get("rich_text") or "")).strip()
        if not text:
            continue
        raw_time = str(it.get("create_time") or "")
        title = text.split("。")[0][:120] if len(text) > 120 else text
        news.append({
            "title": title,
            "url": str(it.get("docurl") or "https://finance.sina.com.cn/7x24/"),
            "time": raw_time[:16],
            "summary": text[:80] if title != text else "",
            "is_today": raw_time[:10] == _today_display(),
        })
        if raw_time[:10]:
            dates.append(raw_time[:10])
        if len(news) >= limit:
            break
    return news, dates


# ============================================================
# 数据源 4：热门榜单（最近交易日收盘后 A股/港股/美股 成交量前五）
# ============================================================
HOT_STOCK_TOP_N = 5

HOT_STOCK_MARKETS = {
    "A股": {"fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "desc": "沪深京 A 股"},
    "港股": {"fs": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2", "desc": "港股主板"},
    "美股": {"fs": "m:105,m:106,m:107", "desc": "美股（纽交所/纳斯达克/美交所）"},
}


def fetch_hot_stocks():
    """抓取最近一个交易日收盘后的 A股/港股/美股成交量前五（东方财富 push2 免费接口）。

    返回 _source_result：markets={市场名: {"desc", "stocks":[{code,name,price,amount}]}}
    """
    print(f"📡 正在抓取 A股/港股/美股成交量前{HOT_STOCK_TOP_N}...")
    markets = {}
    any_stock = False
    for label, cfg in HOT_STOCK_MARKETS.items():
        params = {
            "pn": "1", "pz": str(HOT_STOCK_TOP_N), "po": "1", "np": "1", "fltt": "2", "invt": "2",
            "fid": "f6", "fs": cfg["fs"], "fields": "f2,f3,f4,f6,f12,f14",
        }
        # 数据线 em_clist：push2 → 82.push2 → 72.push2（同格式镜像）
        data, _, _ = safe_request_with_fallback(
            _backup.get_eastmoney_quote_urls(), params=params, timeout=12, line="em_clist",
            validate=lambda d: bool(((d or {}).get("data") or {}).get("diff")))
        stocks = []
        try:
            diff = ((data or {}).get("data") or {}).get("diff") or []
            for it in diff[:HOT_STOCK_TOP_N]:
                name = str(it.get("f14") or "").strip()
                if not name:
                    continue
                stocks.append({
                    "code": str(it.get("f12") or ""),
                    "name": name,
                    "price": it.get("f2"),
                    "change_pct": it.get("f3"),
                    "amount": it.get("f6"),
                })
        except Exception:
            stocks = []
        markets[label] = {"desc": cfg["desc"], "stocks": stocks}
        if stocks:
            any_stock = True
        print(f"  {'✅' if stocks else '⚠️'} {label}成交量前{HOT_STOCK_TOP_N}: {len(stocks)} 只")

    if not any_stock:
        print("  ⚠️ 热门榜单暂不可用，不显示历史兜底榜单")
        return _source_result("东方财富热门榜", "unavailable", markets=markets,
                              error="push2 接口未返回有效数据")

    # 榜单即最近交易日收盘数据；标注数据日期为最近交易日（无法从接口取得时用当天）
    content_date = _today_display()
    print("  ✅ 热门榜单抓取完成（数据为最近交易日收盘后）")
    return _source_result("东方财富热门榜", "success",
                          is_today=True, content_date=content_date,
                          markets=markets)


# ============================================================
# 数据源 5：A股大盘全景（东方财富）
# （指数表现 + 涨跌家数 + 成交额 + 北向资金 + 板块热力）
# 2026-09-30 起与 Yahoo 实时行情一起并入栏目【及时秋刀鱼】AI 行情复盘；
# 抓取逻辑、审计口径与数据源名称「A股大盘全景」均不变。
# ------------------------------------------------------------
# 使用东方财富 push2 / push2his 免费公开接口（与「热门榜单」同源）：
#   · 指数表现：ulist.np/get 一次返回八大宽基指数最新价、涨跌幅与成交额；
#   · 涨跌家数：指数行情附带的交易所统计字段 f104/f105/f106（沪市 = 上证指数、
#     深市 = 深证成指、京市 = 北证50）合计为沪深京市场宽度；
#   · 成交额：沪深京指数成分成交额（f6，元）合计；上一交易日成交额用
#     push2his 日 K（fields2=f51,f57）补齐，用于计算环比增减；
#   · 南北向资金：港交所自 2024-08-19 起停止披露南北向实时 / 每日净买入额，仅盘后
#     公布当日成交总额。本模块按东财数据中心历史报表 RPT_MUTUAL_DEAL_HISTORY 取
#     最近 N 条披露记录（MUTUAL_TYPE=005 北向合计 / 006 南向合计），按「前一收盘」
#     规则取最近一个完整交易日（最新行是今天则取前一日；否则取最后一日），
#     将 DEAL_AMT（百万元）换算为亿元；读取不到就明确标注暂缺——绝不编造净买入数字；
#   · 板块热力：clist/get 行业板块（fs=m:90+t:2）按涨跌幅排序，取领涨 / 领跌
#     各 PANORAMA_SECTOR_TOP_N 名，附主力净流入与领涨股。
# 任何一个子请求失败只影响对应子块；八大指数与市场宽度全失败才整体标记
# unavailable。规则合成（情绪定调等）确定性可复现，均为非投资建议。
# ============================================================
PANORAMA_INDEX_SPECS = [
    ("1.000001", "上证指数"), ("0.399001", "深证成指"),
    ("0.399006", "创业板指"), ("1.000688", "科创50"),
    ("0.899050", "北证50"), ("1.000300", "沪深300"),
    ("1.000016", "上证50"), ("1.000905", "中证500"),
]
# 各交易所「全市场涨跌家数」的载体指数（f104/f105/f106 为该交易所股票统计）
PANORAMA_BREADTH_SOURCES = [("1.000001", "沪"), ("0.399001", "深"), ("0.899050", "京")]
# 2026-09-30 起原全景首块「全球指数概览（Yahoo 报价）」已随两栏合并删除：它复用
# 「AI 行情复盘」报价块同一次抓取的 Yahoo 快照（道指 / 标普 / 纳指 / 恒指 / 恒科），
# 逐项数字与报价块完全相同，属于纯重复（原 PANORAMA_GLOBAL_INDEX_SPECS 已移除）。
PANORAMA_SECTOR_TOP_N = int(os.environ.get("OCTOPUS_PANORAMA_SECTOR_TOP_N", "5"))
PANORAMA_NORTH_POLICY_NOTE = (
    "港交所自 2024-08-19 起停止披露南北向资金实时 / 每日净买入额，仅盘后公布当日成交总额；"
    "本页按最近一个完整交易日（前一收盘）展示北向、南向成交总额，不再估算净买入。")


def _panorama_float(val):
    """把东财字段（可能为 "-" / None / ""）转成 float；不可解析返回 None。"""
    try:
        if val is None or val == "-" or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _panorama_int(val):
    """同 _panorama_float，但转成 int（涨跌家数等统计字段）。"""
    num = _panorama_float(val)
    return int(num) if num is not None else None


def _sina_index_rows(codes=None):
    """新浪 hq.sinajs 指数快照（sina_index 数据线的独立备用源2）。

    返回 ({6位代码: 行情行}, 报价时间字符串|None)；行结构与 _fetch_panorama_indices 一致，
    但新浪不提供涨跌家数（up/down/flat=None）。取不到返回 ({}, None)。
    响应形如 var hq_str_sh000001="上证指数,开盘,昨收,最新,最高,最低,,,成交量(股),成交额(元),…,日期,时间,";
    """
    mapping = codes or _backup.SINA_CODE_FOR_EM
    text, _, _ = safe_request_with_fallback(
        [_backup.SINA_HQ_URL.format(codes=",".join(mapping.values()))],
        headers=_backup.SINA_HQ_HEADERS, timeout=12, is_json=False,
        validate=lambda t: "hq_str_" in str(t))
    if not text:
        return {}, None
    sina_to_secid = {v: k for k, v in mapping.items()}
    out, stamps = {}, []
    for m in re.finditer(r'hq_str_([a-z]{2}\d{6})="([^"]*)"', str(text)):
        secid = sina_to_secid.get(m.group(1))
        parts = m.group(2).split(",")
        if not secid or len(parts) < 10:
            continue
        price = _panorama_float(parts[3])
        prev_close = _panorama_float(parts[2])
        if price is None or price <= 0 or not prev_close:
            continue
        code = secid.split(".", 1)[1]
        out[code] = {
            "code": code, "name": parts[0].strip() or code,
            "price": price, "chg_pct": (price / prev_close - 1) * 100,
            "chg": price - prev_close,
            "amount": _panorama_float(parts[9]),
            "open": _panorama_float(parts[1]), "high": _panorama_float(parts[4]),
            "low": _panorama_float(parts[5]), "prev_close": prev_close,
            "up": None, "down": None, "flat": None,
        }
        if len(parts) >= 32 and re.match(r"\d{4}-\d{2}-\d{2}$", parts[30].strip()):
            stamps.append(f"{parts[30].strip()} {parts[31].strip()[:8] or '00:00:00'}")
    return out, (max(stamps) if stamps else None)


def _fetch_panorama_indices():
    """一次请求拉取全部宽基指数行情；返回 (按 PANORAMA_INDEX_SPECS 排序的指数列表,
    {代码: 行情}, 报价时间字符串|None)。"""
    params = {
        "fltt": "2", "invt": "2",
        "secids": ",".join(secid for secid, _ in PANORAMA_INDEX_SPECS),
        "fields": "f2,f3,f4,f6,f12,f14,f15,f16,f17,f18,f104,f105,f106,f124",
    }
    # 数据线 sina_index：主源 push2 ulist.np → 备用源1 82.push2（同格式）→ 备用源2 新浪 hq（独立解析）
    urls = _backup.urls("sina_index")
    data, success_url, _ = safe_request_with_fallback(
        urls, params=params, timeout=12, line="sina_index",
        validate=lambda d: bool(((d or {}).get("data") or {}).get("diff")))
    rows = ((data or {}).get("data") or {}).get("diff") or []
    if not rows:
        sina_rows, sina_time = _sina_index_rows()
        if sina_rows:
            print("  ✅ 备用源2（新浪财经 hq）顶上：A股宽基指数快照（不含涨跌家数）")
            _note_backup_served("sina_index", _backup.candidates("sina_index")[2][1])
            indices = [dict(sina_rows[secid.split(".", 1)[1]], name=label)
                       for secid, label in PANORAMA_INDEX_SPECS
                       if secid.split(".", 1)[1] in sina_rows]
            return indices, sina_rows, sina_time
    by_code, quote_ts = {}, []
    for it in rows:
        code = str(it.get("f12") or "")
        price = _panorama_float(it.get("f2"))
        chg_pct = _panorama_float(it.get("f3"))
        if not code or price is None or chg_pct is None:
            continue
        by_code[code] = {
            "code": code,
            "name": str(it.get("f14") or "").strip() or code,
            "price": price, "chg_pct": chg_pct,
            "chg": _panorama_float(it.get("f4")),
            "amount": _panorama_float(it.get("f6")),
            "open": _panorama_float(it.get("f17")), "high": _panorama_float(it.get("f15")),
            "low": _panorama_float(it.get("f16")), "prev_close": _panorama_float(it.get("f18")),
            "up": _panorama_int(it.get("f104")), "down": _panorama_int(it.get("f105")),
            "flat": _panorama_int(it.get("f106")),
        }
        ts = _panorama_int(it.get("f124"))
        if ts:
            quote_ts.append(ts)
    indices = []
    for secid, label in PANORAMA_INDEX_SPECS:
        row = by_code.get(secid.split(".", 1)[1])
        if row:
            row["name"] = label  # 统一正式中文名，规避行情源简称差异
            indices.append(row)
    quote_time = (datetime.fromtimestamp(max(quote_ts), CST).strftime("%Y-%m-%d %H:%M:%S")
                  if quote_ts else None)
    return indices, by_code, quote_time


def _fetch_panorama_prev_amounts():
    """取沪 / 深 / 京载体指数最近两根日 K 的成交额（fields2=f51,f57，单位元）。

    返回 {secid: [(日期, 成交额), ...]}；单交易所失败只影响该交易所。
    """
    out = {}
    for secid, _ in PANORAMA_BREADTH_SOURCES:
        params = {"secid": secid, "klt": "101", "fqt": "0", "lmt": "2", "end": "20500101",
                  "fields1": "f1,f2,f3", "fields2": "f51,f57"}
        # 数据线 em_kline：push2his → 91.push2his → 63.push2his（同格式镜像）
        data, _, _ = safe_request_with_fallback(
            _backup.get_eastmoney_kline_urls(), params=params, timeout=12, line="em_kline",
            validate=lambda d: bool(((d or {}).get("data") or {}).get("klines")))
        pairs = []
        try:
            klines = (((data or {}).get("data") or {}).get("klines")) or []
            for line in klines[-2:]:
                parts = str(line).split(",")
                if len(parts) >= 2:
                    amt = _panorama_float(parts[1])
                    if amt is not None:
                        pairs.append((parts[0].strip(), amt))
        except Exception:
            pairs = []
        out[secid] = pairs
    return out


PANORAMA_HSGT_HISTORY_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _fetch_panorama_northbound():
    """南北向资金：2024-08-19 起不再披露净买入，读最近完整交易日（前一收盘）成交总额。

    数据源：东财数据中心历史报表 RPT_MUTUAL_DEAL_HISTORY。
    其中 MUTUAL_TYPE=005 为「北向合计」（沪股通+深股通）、006 为「南向合计」
    （港股通沪+港股通深）；DEAL_AMT 为该日成交总额（单位：百万元），
    披露口径调整后北向净买额列缺失，但成交总额仍更新。

    前一天收盘口径：若最新日期记录等于今天，则取它前一日（最近完整交易日）；
    否则取最后一日（盘前 / 非交易日 / 当日尚未收市场景下，最后一日即最近完整交易日）。
    读不到任何数值 → available=False / south_available=False 并给出原因。
    """
    params = {
        "reportName": "RPT_MUTUAL_DEAL_HISTORY",
        "columns": "ALL",
        "pageNumber": "1",
        "pageSize": "40",
        "sortColumns": "TRADE_DATE,MUTUAL_TYPE",
        "sortTypes": "-1,1",
        "source": "WEB",
        "client": "WEB",
    }
    # 数据线 em_datacenter：datacenter-web → datacenter → datacenter/securities（同格式镜像）
    north_urls = list(dict.fromkeys([PANORAMA_HSGT_HISTORY_URL] + _backup.get_eastmoney_datacenter_urls()))
    data, _, _ = safe_request_with_fallback(
        north_urls, params=params, timeout=12, line="em_datacenter",
        validate=lambda d: isinstance((d or {}).get("result"), dict)
        and bool(d["result"].get("data")))
    note = PANORAMA_NORTH_POLICY_NOTE
    today_date = _today_display()

    def _pick(rows):
        """按「前一收盘」规则从 成交总额记录 里取最近一个完整交易日数据。

        rows 为该方向（北向=005 / 南向=006）的逐日记录；
        DEAL_AMT 单位百万元，转换为亿元（÷100）。
        """
        parsed = []
        for it in rows or []:
            raw_date = str(it.get("TRADE_DATE") or "")[:10]
            deal_amt = _panorama_float(it.get("DEAL_AMT"))
            if not raw_date or deal_amt is None:
                continue
            parsed.append((raw_date, deal_amt))
        parsed.sort(key=lambda item: item[0])
        if not parsed:
            return {"available": False, "amount_yi": None, "date": None,
                    "error": "接口未返回有效记录"}
        # 最新行是今天 → 取前一行作为「前一收盘」；否则最后一行即最近完整交易日。
        idx_today = next((i for i, (d, _) in enumerate(parsed) if d == today_date), None)
        if idx_today is not None and idx_today > 0:
            date, deal_amt = parsed[idx_today - 1]
        else:
            date, deal_amt = parsed[-1]
        if deal_amt is None:
            return {"available": False, "amount_yi": None, "date": date,
                    "error": "披露口径内暂无成交总额数值"}
        return {"available": True, "amount_yi": deal_amt / 100.0,
                "date": date, "error": None}

    try:
        root = ((data or {}).get("result") or {}).get("data") or []
        north = _pick([it for it in root if str(it.get("MUTUAL_TYPE") or "") == "005"])
        south = _pick([it for it in root if str(it.get("MUTUAL_TYPE") or "") == "006"])
    except Exception as exc:
        north = {"available": False, "amount_yi": None, "date": None, "error": str(exc)}
        south = {"available": False, "amount_yi": None, "date": None, "error": str(exc)}

    return {
        "available": bool(north["available"]),
        "amount_yi": north["amount_yi"],
        "date": north["date"],
        "error": north.get("error"),
        "south_available": bool(south["available"]),
        "south_amount_yi": south["amount_yi"],
        "south_date": south["date"],
        "south_error": south.get("error"),
        "policy_note": note,
    }


def _fetch_panorama_sectors():
    """行业板块领涨 / 领跌各 PANORAMA_SECTOR_TOP_N 名（fs=m:90+t:2，按涨跌幅排序）。"""
    result = {"leading": [], "lagging": []}
    for key, po in (("leading", "1"), ("lagging", "0")):
        params = {"pn": "1", "pz": str(PANORAMA_SECTOR_TOP_N), "po": po, "np": "1",
                  "fltt": "2", "invt": "2", "fid": "f3", "fs": "m:90+t:2",
                  "fields": "f2,f3,f12,f14,f62,f104,f105,f128,f136"}
        # 数据线 em_clist：push2 → 82.push2 → 72.push2（同格式镜像）
        data, _, _ = safe_request_with_fallback(
            _backup.get_eastmoney_quote_urls(), params=params, timeout=12, line="em_clist",
            validate=lambda d: bool(((d or {}).get("data") or {}).get("diff")))
        rows = []
        try:
            diff = ((data or {}).get("data") or {}).get("diff") or []
            for it in diff[:PANORAMA_SECTOR_TOP_N]:
                name = str(it.get("f14") or "").strip()
                chg = _panorama_float(it.get("f3"))
                if not name or chg is None:
                    continue
                rows.append({
                    "code": str(it.get("f12") or ""), "name": name, "chg_pct": chg,
                    "main_inflow": _panorama_float(it.get("f62")),
                    "up": _panorama_int(it.get("f104")), "down": _panorama_int(it.get("f105")),
                    "lead_stock": str(it.get("f128") or "").strip(),
                    "lead_stock_pct": _panorama_float(it.get("f136")),
                })
        except Exception:
            rows = []
        result[key] = rows
    return result


def _panorama_breadth_mood(ratio):
    """由涨跌比给出确定性情绪定调（阈值规则，可复现，非投资建议）。"""
    if ratio is None:
        return "数据不足"
    if ratio >= 2.0:
        return "普涨强势"
    if ratio >= 1.2:
        return "偏多震荡"
    if ratio >= 0.8:
        return "多空均衡"
    if ratio >= 0.5:
        return "偏空承压"
    return "普跌弱势"


def fetch_market_panorama():
    """抓取 A股大盘全景：指数表现 / 涨跌家数 / 成交额 / 北向资金 / 板块热力。

    供栏目【及时秋刀鱼】AI 行情复盘使用（2026-09-30 起与实时行情合并展示）。
    """
    print("📡 正在抓取 A股大盘全景（指数/涨跌家数/成交额/北向/板块）...")
    errors = []

    indices, by_code, quote_time = _fetch_panorama_indices()

    # ---- 涨跌家数（沪深京合计）----
    breadth = None
    b_parts, b_missing = {}, []
    for secid, exch in PANORAMA_BREADTH_SOURCES:
        row = by_code.get(secid.split(".", 1)[1])
        if row and row.get("up") is not None and row.get("down") is not None:
            b_parts[exch] = {"up": row["up"], "down": row["down"], "flat": row.get("flat")}
        else:
            b_missing.append(exch)
    if b_parts:
        up = sum(p["up"] for p in b_parts.values())
        down = sum(p["down"] for p in b_parts.values())
        flat = sum((p.get("flat") or 0) for p in b_parts.values())
        ratio = round(up / down, 2) if down else None
        breadth = {"up": up, "down": down, "flat": flat, "ratio": ratio,
                   "mood": _panorama_breadth_mood(ratio),
                   "markets": b_parts, "partial": bool(b_missing)}

    # ---- 成交额（沪深京合计 + 较上一交易日环比）----
    turnover = None
    amount_by_exch = {}
    for secid, exch in PANORAMA_BREADTH_SOURCES:
        row = by_code.get(secid.split(".", 1)[1])
        if row and row.get("amount"):
            amount_by_exch[exch] = row["amount"]
    if amount_by_exch:
        prev_total = None
        try:
            klines = _fetch_panorama_prev_amounts()
            quote_date = (quote_time or "")[:10] or None
            prev_sum, prev_ok = 0.0, 0
            for secid, _ in PANORAMA_BREADTH_SOURCES:
                pairs = klines.get(secid) or []
                if not pairs:
                    continue
                # 最新一根 K 线日期 == 指数报价日 → 其前一根才是「上一交易日」；
                # 否则最新一根即最近完整交易日（盘前 / 盘中 / 非交易日场景）。
                if quote_date and len(pairs) >= 2 and pairs[-1][0] == quote_date:
                    prev_pair = pairs[-2]
                else:
                    prev_pair = pairs[-1]
                if prev_pair and prev_pair[1]:
                    prev_sum += prev_pair[1]
                    prev_ok += 1
            if prev_ok >= 2 and prev_sum > 0:  # 至少沪深两市齐备才给环比，避免口径误导
                prev_total = prev_sum
        except Exception as exc:
            errors.append(f"上日成交额: {exc}")
        cur_total = sum(amount_by_exch.values())
        turnover = {
            "total": cur_total,
            "sh_sz": amount_by_exch.get("沪", 0.0) + amount_by_exch.get("深", 0.0),
            "by_market": amount_by_exch,
            "prev_total": prev_total,
            "chg_pct": (cur_total / prev_total - 1) * 100 if prev_total else None,
            "partial": len(amount_by_exch) < 3,
        }

    # ---- 南北向资金（前一收盘成交总额启发式读取 + 披露政策说明）----
    north = _fetch_panorama_northbound()
    if not north.get("available"):
        errors.append(f"北向成交总额: {north.get('error') or '暂缺'}")
    if not north.get("south_available"):
        errors.append(f"南向成交总额: {north.get('south_error') or '暂缺'}")

    # ---- 板块热力（领涨 / 领跌行业板块）----
    sectors = _fetch_panorama_sectors()
    if not sectors["leading"] and not sectors["lagging"]:
        errors.append("板块热力: 行业板块接口未返回有效数据")

    if not indices and not breadth:
        print("  ⚠️ A股大盘全景暂不可用；日报将明确显示数据暂缺")
        return _source_result("东方财富·A股全景", "unavailable",
                              indices=[], breadth=None, turnover=None,
                              north=north, sectors=sectors, quote_time=quote_time,
                              error="；".join(errors[:3]) or "push2 接口未返回有效数据")

    content_date = (quote_time or "")[:10] or _today_display()
    is_today = content_date == _today_display()
    north_ok = "✓" if (north.get("available") and north.get("south_available")) else \
               ("部分" if (north.get("available") or north.get("south_available")) else "暂缺")
    print(f"  ✅ 全景复盘：指数 {len(indices)} 只 / "
          f"涨跌家数 {'齐' if breadth else '缺'} / "
          f"板块 {len(sectors['leading'])}+{len(sectors['lagging'])} / "
          f"南北向 {north_ok}")
    return _source_result("东方财富·A股全景", "success",
                          is_today=is_today, content_date=content_date,
                          indices=indices, breadth=breadth, turnover=turnover,
                          north=north, sectors=sectors, quote_time=quote_time,
                          error="；".join(errors[:3]) or None,
                          partial=bool(errors or (breadth or {}).get("partial")))


# ============================================================
# 数据源 6：港股名家频道（YouTube / 通用 RSS / 需登录平台）
# ============================================================
def resolve_channel_id(channel):
    """解析频道的 channel_id：优先使用配置的 channel_id，否则通过 handle 页面解析。"""
    cid = channel.get("channel_id")
    if cid:
        return cid
    handle = (channel.get("handle") or "").lstrip("@")
    if not handle:
        return None
    # handle → channelId：官方频道页 → 移动版频道页 → 频道视频页（三路都是 YouTube 页面，解析同一 JSON 字段）
    html, _, _ = safe_request_with_fallback(
        [f"https://www.youtube.com/@{handle}", f"https://m.youtube.com/@{handle}",
         f"https://www.youtube.com/@{handle}/videos"],
        is_json=False, timeout=12,
        validate=lambda t: bool(re.search(r'"(?:channelId|externalId)":"UC[0-9A-Za-z_-]{22}"', str(t))))
    if not html:
        return None
    m = re.search(r'"channelId":"(UC[0-9A-Za-z_-]{22})"', html)
    if m:
        return m.group(1)
    m = re.search(r'"externalId":"(UC[0-9A-Za-z_-]{22})"', html)
    return m.group(1) if m else None


def _channel_item(title, url, pub_raw):
    """把一条频道内容的标题/链接/发布时间整理成统一结构（北京时间 + 是否当天）。"""
    pub_cst = _cst_from_iso(pub_raw)
    if pub_cst is None:  # 兼容 RSS 2.0 的 RFC 2822 格式（如 Fri, 01 Aug 2026 12:00:00 +0800）
        try:
            from email.utils import parsedate_to_datetime
            pub_cst = parsedate_to_datetime(pub_raw).astimezone(CST)
        except Exception:
            pub_cst = None
    return {
        "title": title,
        "url": url,
        "published": pub_raw,
        "published_cst": pub_cst.strftime("%Y-%m-%d %H:%M") if pub_cst else "—",
        "is_today": _date_is_today(pub_cst),
    }


def _parse_rss_items(xml_text, limit=8):
    """解析通用 RSS 2.0 / Atom 源，保留标题、摘要、链接与发布时间。"""
    items = []
    try:
        root = ET.fromstring(xml_text or "")
    except Exception:
        return []
    # RSS 2.0
    if root.tag == "rss":
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub = (item.findtext("pubDate")
                       or item.findtext("dc:date", namespaces={"dc": "http://purl.org/dc/elements/1.1/"})
                       or "")
                summary = (item.findtext("description")
                           or item.findtext("content:encoded", namespaces={
                               "content": "http://purl.org/rss/1.0/modules/content/"})
                           or "")
                if title:
                    parsed = _channel_item(title, link, pub)
                    parsed["summary"] = summary
                    items.append(parsed)
                if len(items) >= limit:
                    break
    # Atom
    elif root.tag.endswith("feed"):
        for entry in root.findall("a:entry", YT_NS):
            title = (entry.findtext("a:title", "", YT_NS) or "").strip()
            link = ""
            for ln in entry.findall("a:link", YT_NS):
                if (ln.get("rel") or "alternate") == "alternate":
                    link = ln.get("href") or ""
                    break
            pub = (entry.findtext("a:published", "", YT_NS)
                   or entry.findtext("a:updated", "", YT_NS) or "")
            summary = (entry.findtext("a:summary", "", YT_NS)
                       or entry.findtext("a:content", "", YT_NS) or "")
            if title:
                parsed = _channel_item(title, link, pub)
                parsed["summary"] = summary
                items.append(parsed)
            if len(items) >= limit:
                break
    return items


def fetch_hk_channels():
    """抓取「港股名家频道」的最新内容。

    - kind="youtube"：YouTube 频道 RSS（无需 API Key），返回最新视频；
    - kind="rss"    ：通用 RSS / Atom 源（Medium、Substack 等）；
    - kind="manual" ：需登录 / 未配置来源，放入 unsupported（页面标注「暂缺」及原因，
                      绝不伪造内容）。

    返回 _source_result：channels=已抓取频道、unsupported=需登录/未配置频道。
    """
    print("📡 正在抓取港股名家频道...")
    channels, unsupported, failures = [], [], []
    for ch in HK_CHANNELS:
        name = ch.get("name", "?")
        kind = ch.get("kind", "youtube")

        if kind == "manual":
            unsupported.append({"name": name, "desc": ch.get("desc", ""),
                                "note": ch.get("note", "平台需登录，暂不支持自动抓取")})
            continue

        if kind == "rss":
            feed_url = (ch.get("feed_url") or "").strip()
            if not feed_url:
                unsupported.append({"name": name, "desc": ch.get("desc", ""),
                                    "note": ch.get("note", "未配置 feed 地址")})
                continue
            # 通用 RSS 频道：官方订阅地址 + RSSHub 多实例（仅当订阅本身就是 RSSHub 地址时才有镜像）
            xml_text, _, _ = safe_request_with_fallback(
                _backup.get_rsshub_fallbacks(feed_url), is_json=False, timeout=12,
                validate=lambda t: "<item" in str(t) or "<entry" in str(t))
            items = _parse_rss_items(xml_text, limit=8)
            if items:
                channels.append({
                    "name": name, "desc": ch.get("desc", ""), "source": "RSS",
                    "url": feed_url, "videos": items,
                    "is_today": any(v["is_today"] for v in items),
                    "newest_date": next((v["published_cst"] for v in items if v["is_today"]),
                                        items[0]["published_cst"]),
                })
            else:
                msg = "自动抓取失败（源可能需登录/被限流，或地址无效），暂缺"
                unsupported.append({"name": name, "desc": ch.get("desc", ""), "note": msg})
                failures.append(f"{name}: {msg}")
            continue

        # kind == "youtube"
        cid = resolve_channel_id(ch)
        if not cid:
            msg = "无法解析频道 ID（handle 可能不存在或页面结构变化），暂缺"
            unsupported.append({"name": name, "desc": ch.get("desc", ""), "note": msg})
            failures.append(f"{name}: {msg}")
            continue
        # 数据线 youtube_feed：主源 YouTube 官方 Atom → 备用源1 RSSHub → 备用源2 Invidious（同格式）
        yt_urls = _backup.get_youtube_urls(cid)
        primary_yt = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
        xml_text, _, _ = safe_request_with_fallback(
            list(dict.fromkeys([primary_yt] + yt_urls)), is_json=False, timeout=12,
            line="youtube_feed", fmt={"channel_id": cid},
            validate=lambda t: "<entry" in str(t))
        videos = []
        try:
            root = ET.fromstring(xml_text or "")
            for entry in root.findall("a:entry", YT_NS)[:8]:
                title = (entry.findtext("a:title", "", YT_NS) or "").strip()
                published = entry.findtext("a:published", "", YT_NS) or ""
                vid = entry.findtext("yt:videoId", "", YT_NS) or ""
                if not title:
                    continue
                pub_cst = _cst_from_iso(published)
                videos.append({
                    "title": title,
                    "video_id": vid,
                    "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
                    "published": published,
                    "published_cst": pub_cst.strftime("%Y-%m-%d %H:%M") if pub_cst else "—",
                    "is_today": _date_is_today(pub_cst),
                })
        except Exception as exc:
            failures.append(f"{name}: {exc}")

        if videos:
            handle = (ch.get("handle") or "").lstrip("@")
            channel_url = f"https://www.youtube.com/@{handle}" if handle else \
                          f"https://www.youtube.com/channel/{cid}"
            channels.append({
                "name": name, "desc": ch.get("desc", ""), "source": "YouTube",
                "url": channel_url, "videos": videos,
                "is_today": any(v["is_today"] for v in videos),
                "newest_date": next((v["published_cst"] for v in videos if v["is_today"]),
                                    videos[0]["published_cst"]),
            })
        else:
            msg = "自动抓取失败（RSS 暂无内容或网络异常），暂缺"
            unsupported.append({"name": name, "desc": ch.get("desc", ""), "note": msg})
            failures.append(f"{name}: {msg}")

    # 全部已抓取频道中最新内容的日期（用于当天检验）
    all_dates = [v["published_cst"][:10] for ch in channels for v in ch["videos"]]
    newest_date = max(all_dates) if all_dates else None
    is_today = any(ch["is_today"] for ch in channels)

    if channels:
        print(f"  ✅ 成功抓取 {len(channels)}/{len(HK_CHANNELS)} 个频道"
              + (f"（含当天内容）" if is_today else f"（最新内容日期 {newest_date}）"))
        if unsupported:
            print(f"  🕐 {len(unsupported)} 个频道需登录/未配置，标注暂缺："
                  + "、".join(u["name"] for u in unsupported))
        return _source_result("港股名家频道", "success",
                              is_today=is_today, content_date=newest_date,
                              channels=channels, unsupported=unsupported,
                              error="；".join(failures[:3]) or None,
                              partial=len(channels) + len(unsupported) != len(HK_CHANNELS))

    if unsupported:
        print("  ⚠️ 暂无可自动抓取的频道；需登录/未配置：" + "、".join(u["name"] for u in unsupported))
        return _source_result("港股名家频道", "unavailable", channels=[], unsupported=unsupported,
                              error="；".join(failures[:3]) or "全部频道需登录或未配置自动抓取源")

    print("  ⚠️ 港股名家频道暂不可用，不显示历史内容兜底")
    return _source_result("港股名家频道", "unavailable", channels=[], unsupported=[],
                          error="；".join(failures[:3]) or "未取得有效内容")


# ============================================================
# 趋势跟踪：多平台信息员（仅标题/热度/原始链接，不复制帖子正文）
# ------------------------------------------------------------
# 2026-09-28 起由「单一 Reddit 来源」升级为四个公开平台，各自独立采集、独立降级：
#   Reddit      —— 散户论坛：10 个财经/投资/金融/经济类板块各取热门帖 5 条样本；
#   StockTwits  —— 美股/加密散户情绪平台：公开趋势榜标的（含平台生成的多空讨论摘要、
#                  关注人数）+ 趋势榜前排标的最新消息里的平台 Bullish/Bearish 标签统计；
#   TradingView —— 交易员观点平台：公开 Ideas RSS 最新观点（标题自带标的与技术面方向）；
#   Bogleheads  —— 长期投资者论坛：公开 RSS 最新讨论主题（长期资金与配置视角）。
# 只读公开 feed / 公开 JSON，不登录、不绕过付费墙、不复制帖子正文；抓不到就整平台暂缺，
# 绝不伪造内容。OCTOPUS_TREND_PLATFORMS 可用逗号分隔平台名单独关闭（如 "Reddit,StockTwits"）。
# ============================================================
_PUBLIC_ALLOWED_HOSTS = {
    "reddit.com", "www.reddit.com", "old.reddit.com",
    "stocktwits.com", "www.stocktwits.com",
    "tradingview.com", "www.tradingview.com",
    "bogleheads.org", "www.bogleheads.org",
}


def _active_public_site_names():
    """启用的趋势跟踪平台：OCTOPUS_TREND_PLATFORMS 过滤后为空则回落全部平台。"""
    raw = str(os.environ.get("OCTOPUS_TREND_PLATFORMS", "")).strip()
    if not raw:
        return PUBLIC_SITE_NAMES
    wanted = {p.strip().lower() for p in raw.split(",") if p.strip()}
    picked = tuple(n for n in PUBLIC_SITE_NAMES if n.lower() in wanted)
    return picked or PUBLIC_SITE_NAMES


def _public_url(raw, base=""):
    """外链仅允许已列出的源站 HTTPS 主机，防止外部标题/链接注入日报。"""
    if not raw or any(c.isspace() or c in ('<', '>', '\\') for c in str(raw).strip()):
        return ""
    try:
        url = urljoin(base, str(raw).strip())
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname not in _PUBLIC_ALLOWED_HOSTS
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            return ""
    except ValueError:
        return ""
    return url


def _public_text(value, limit=160):
    """清理站点文本，限制每条摘录长度；HTML 转义在渲染时统一处理。"""
    text = re.sub(r"<[^>]*>", " ", _html_unescape(str(value or "")))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def _public_recent(dt, now=None, hours=PUBLIC_SITE_WINDOW_HOURS):
    if not dt or dt.tzinfo is None:
        return False
    age = (now or datetime.now(CST)) - dt.astimezone(CST)
    return -timedelta(minutes=5) <= age <= timedelta(hours=hours)


def _public_site_result(name, items, *, latest=None, snapshot=False, note="", error=None):
    """保留全部可核实样本（条数上限已由采集端按板块/条数控制）；
    快照的「当天」是当日采集，不冒充当日发文/实时价格。"""
    items = [item for item in (items or []) if isinstance(item, dict)]
    is_today = bool(items) and (snapshot or any(it.get("is_today") for it in items))
    return _source_result(
        name, "success" if items else "unavailable", is_today=is_today,
        content_date=latest, url=PUBLIC_SITE_URLS[name], items=items,
        snapshot=bool(snapshot and items), note=note,
        error=error or ("未取得可核实的公开内容" if not items else None),
    )


# 10 个财经 / 投资 / 金融 / 经济类板块：(板块名, 中文名)；顺序用于抓取、栏目与审计展示。
_REDDIT_BOARDS = (
    ("stocks", "个股讨论"),
    ("investing", "综合投资"),
    ("wallstreetbets", "散户投机风向"),
    ("ValueInvesting", "价值投资"),
    ("economics", "宏观经济"),
    ("wallstreet", "华尔街金融"),
    ("options", "期权交易"),
    ("Forex", "外汇市场"),
    ("pennystocks", "小盘热股"),
    ("personalfinance", "个人理财"),
)
_REDDIT_HEADERS = {"User-Agent": "octopus-daily/1.0 (+https://github.com/k-macao/02)"}
_REDDIT_HOSTS = ("reddit.com", "www.reddit.com", "old.reddit.com")
# RSS 公开正文片段里的「N points / M comments」热度写法（JSON 兜底用 score/num_comments 字段）。
_REDDIT_HEAT_RE = re.compile(
    r"(\d[\d,.]*\s*k?)\s*points?\s*(\d[\d,.]*\s*k?)\s*comments?", re.I)


def _reddit_heat_counts_from_html(fragment):
    """从 RSS 的 points / comments 文本提取结构化计数；缺字段保持 None。"""
    text = re.sub(r"<[^>]*>", " ", _html_unescape(str(fragment or "")))
    match = _REDDIT_HEAT_RE.search(text)
    if not match:
        return None, None

    def parse_count(raw):
        value = str(raw or "").strip().lower().replace(",", "")
        try:
            return int(round(float(value[:-1]) * 1000)) if value.endswith("k") else int(float(value))
        except (TypeError, ValueError, OverflowError):
            return None

    return parse_count(match.group(1)), parse_count(match.group(2))


def _reddit_heat_from_html(fragment):
    """从 RSS 公开帖子片段提取热度数据；无法核实时返回空串，不猜测。"""
    text = re.sub(r"<[^>]*>", " ", _html_unescape(str(fragment or "")))
    match = _REDDIT_HEAT_RE.search(text)
    if not match:
        return ""
    return f" · {match.group(1).strip()} 赞 · {match.group(2).strip()} 评论"


def _reddit_item(community, title, url, published, *, heat="", score=None,
                 comments=None, now=None):
    """组装单条热帖样本：community 供栏目分组，发布时间与可验证热度均结构化。"""
    now = now or datetime.now(CST)
    pub = published.strftime("%Y-%m-%d %H:%M")
    return {
        "title": title,
        "url": url,
        "detail": f"发布于 {pub}（北京时间）{heat}",
        "published_cst": pub,
        "community": community,
        "platform": "Reddit",
        "score": score,
        "comments": comments,
        "is_today": published.date() == now.date(),
    }


def _reddit_hot_items(xml_text, community, base, *, now=None):
    """解析板块公开热门（hot）feed，保留 feed 排序（即站点热度榜）。

    只接受带可验证发布时间的条目；超出 72 小时窗口的剔除；
    返回 (items, 最新日期)，每板块最多保留 REDDIT_POSTS_PER_BOARD 条。
    """
    parsed = _parse_rss_items(xml_text, limit=40)
    now = now or datetime.now(CST)
    items, latest, seen = [], None, set()
    for row in parsed:
        if len(items) >= REDDIT_POSTS_PER_BOARD:
            break
        raw_date = str(row.get("published") or "").strip()
        # 没有显式时区就不能确定自然日，拒绝用运行机器的本地时区猜测。
        if not re.search(r"(?:Z|[+-]\d{2}:?\d{2}|\bGMT|\bUTC)$", raw_date, re.I):
            continue
        pub = row.get("published_cst") or ""
        try:
            dt = datetime.strptime(pub, "%Y-%m-%d %H:%M").replace(tzinfo=CST)
        except ValueError:
            continue
        url = _public_url(row.get("url"), base)
        title = _public_text(row.get("title"), 125)
        if not (url and title and _public_recent(dt, now)):
            continue
        if url in seen:
            continue
        if not latest or dt > latest:
            latest = dt
        seen.add(url)
        score, comments = _reddit_heat_counts_from_html(row.get("summary"))
        items.append(_reddit_item(
            f"r/{community}", title, url, dt,
            heat=_reddit_heat_from_html(row.get("summary")),
            score=score, comments=comments, now=now))
    return items, (latest.strftime("%Y-%m-%d") if latest else None)


def _reddit_json_items(payload, community, *, now=None):
    """公开 feed 不可用时，仅读公开帖子 JSON 的标题/发帖时间/热度/永久链接。"""
    try:
        children = payload["data"]["children"]
    except (TypeError, KeyError):
        return [], None
    if not isinstance(children, list):
        return [], None
    now = now or datetime.now(CST)
    items, latest, seen = [], None, set()
    for child in children:
        if len(items) >= REDDIT_POSTS_PER_BOARD:
            break
        post = child.get("data", {}) if isinstance(child, dict) else {}
        if not isinstance(post, dict) or post.get("stickied") or post.get("over_18"):
            continue
        try:
            published = datetime.fromtimestamp(float(post["created_utc"]), timezone.utc).astimezone(CST)
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            continue
        url = _public_url(post.get("permalink"), "https://www.reddit.com/")
        title = _public_text(post.get("title"), 125)
        if not (url and title and _public_recent(published, now)):
            continue
        if url in seen:
            continue
        if not latest or published > latest:
            latest = published
        seen.add(url)
        score = comments = None
        try:
            if post.get("score") is not None:
                score = int(post["score"])
            if post.get("num_comments") is not None:
                comments = max(0, int(post["num_comments"]))
        except (TypeError, ValueError, OverflowError):
            score = comments = None
        heat = ""
        if score is not None and score > 0:
            heat = f" · {score:,} 赞"
            if comments:
                heat += f" · {comments:,} 评论"
        items.append(_reddit_item(f"r/{community}", title, url, published,
                                  heat=heat, score=score, comments=comments, now=now))
    return items, (latest.strftime("%Y-%m-%d") if latest else None)


def fetch_reddit():
    """逐板块并行读取公开热门（hot）feed；失败时试一次公开 JSON，再失败如实暂缺。

    每个板块取热门帖子前 5 条作为样本数据，栏目按板块顺序展示；
    社区观点未经核实，热度不等于事实或投资建议。
    """
    name = "Reddit"
    now = datetime.now(CST)

    def _fetch_board(board):
        community, _label = board
        base = f"https://www.reddit.com/r/{community}/"
        limit = REDDIT_POSTS_PER_BOARD * 2
        reddit_rss_urls = _backup.get_reddit_urls(community, "rss")
        xml, _, _ = safe_request_with_fallback(reddit_rss_urls,
                           headers={**_REDDIT_HEADERS, "Accept": "application/atom+xml,application/xml"},
                           is_json=False, timeout=8)
        items, latest = _reddit_hot_items(xml, community, base, now=now)
        if not items:
            reddit_json_urls = _backup.get_reddit_urls(community, "json")
            payload, _, _ = safe_request_with_fallback(reddit_json_urls,
                                   headers={**_REDDIT_HEADERS, "Accept": "application/json"},
                                   timeout=8)
            items, latest = _reddit_json_items(payload, community, now=now)
        return community, items, latest

    board_results = {}
    with ThreadPoolExecutor(max_workers=len(_REDDIT_BOARDS)) as executor:
        futures = {executor.submit(_fetch_board, board): board
                   for board in _REDDIT_BOARDS}
        for future in futures:
            board = futures[future]
            default_community = board[0] if isinstance(board, (list, tuple)) else str(board)
            try:
                _community, items, latest = future.result()
            except Exception:
                _community, items, latest = default_community, [], None
            board_results[_community] = (items, latest)

    items, unavailable, latest = [], [], None
    for community, _label in _REDDIT_BOARDS:
        board_items, board_latest = board_results[community]
        if board_latest and (not latest or board_latest > latest):
            latest = board_latest
        if board_items:
            items.extend(board_items)
        else:
            unavailable.append(f"r/{community}")
    note = ("只收录公开热帖的标题与热度作为趋势跟踪样本，供判断散户讨论风向与热门标的；"
            "社区观点未经核实，热度不等于事实或投资建议。")
    if unavailable:
        note += " 暂缺（访问受限或近72小时无新帖）：" + "、".join(unavailable) + "。"
    error = "十个板块的公开 feed / JSON 均不可用或近72小时无可验证的新帖"
    return _public_site_result(name, items, latest=latest, note=note, error=error)


STOCKTWITS_TRENDING_URL = "https://api.stocktwits.com/api/2/trending/symbols.json"
STOCKTWITS_STREAM_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
TRADINGVIEW_FEED_URL = "https://www.tradingview.com/feed/"
BOGLEHEADS_FEED_URL = "https://www.bogleheads.org/forum/feed"
_PLATFORM_HEADERS = {"User-Agent": "octopus-daily/1.0 (+https://github.com/k-macao/02)"}


def _platform_item(platform, community, title, url, published, *, detail="", symbol="",
                   rank=None, watchlist_count=None, trending_score=None,
                   sentiment_counts=None, now=None):
    """组装单条平台样本：社区通用字段加来源确实返回的结构化榜单/标签数据。"""
    now = now or datetime.now(CST)
    dt = published.astimezone(CST) if published else None
    pub = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
    item = {
        "title": title,
        "url": url,
        "detail": detail or (f"发布于 {pub}（北京时间）" if pub else ""),
        "published_cst": pub,
        "community": community,
        "platform": platform,
        "symbol": symbol,
        "is_today": bool(dt and dt.date() == now.date()),
    }
    for key, value in (("rank", rank), ("watchlist_count", watchlist_count),
                       ("trending_score", trending_score),
                       ("sentiment_counts", sentiment_counts)):
        if value is not None:
            item[key] = value
    return item


def _platform_rss_items(xml_text, platform, base, *, limit, now, community="", title_cleaner=None):
    """通用 RSS → 平台样本：只保留可核实链接 + 窗口内发布时间的条目。

    title_cleaner(raw_title, summary) 返回 (community, title)，缺省原样保留。
    返回 (items, 最新日期)。
    """
    items, latest = [], None
    for row in _parse_rss_items(xml_text, limit=limit * 3):
        if len(items) >= limit:
            break
        url = _public_url(row.get("url"), base)
        raw_title = _public_text(row.get("title"), 160)
        summary = row.get("summary") or ""
        pub = row.get("published_cst") or ""
        dt = None
        if pub and pub != "—":
            try:
                dt = datetime.strptime(pub, "%Y-%m-%d %H:%M").replace(tzinfo=CST)
            except ValueError:
                dt = None
        if not (url and raw_title and dt and _public_recent(dt, now)):
            continue
        group, title = community, raw_title
        if title_cleaner:
            group, title = title_cleaner(raw_title, summary)
        group, title = (group or community or platform), _public_text(title, 140)
        if not title:
            continue
        if not latest or dt > latest:
            latest = dt
        items.append(_platform_item(platform, group, title, url, dt,
                                    symbol="", now=now))
    return items, (latest.strftime("%Y-%m-%d") if latest else None)


def _stocktwits_symbols_from_stream(payload, limit=STOCKTWITS_TRENDING_N):
    """StockTwits streams/trending.json → 与 trending/symbols 同结构的标的榜（stocktwits 数据线备用源2）。

    按热门消息里标的出现次数排名（次数即 trending_score 的代用指标），
    watchlist_count / title 取自消息内的 symbol 对象；没有平台多空摘要（trends 缺省）。
    """
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        return []
    tally, meta = {}, {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        for sym in message.get("symbols") or []:
            if not isinstance(sym, dict) or not sym.get("symbol"):
                continue
            code = str(sym["symbol"]).strip()
            tally[code] = tally.get(code, 0) + 1
            meta.setdefault(code, {"title": sym.get("title") or code,
                                   "watchlist_count": sym.get("watchlist_count") or 0})
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [{"symbol": code, "rank": i, "title": meta[code]["title"],
             "watchlist_count": meta[code]["watchlist_count"], "trending_score": n}
            for i, (code, n) in enumerate(ranked, 1)]


def _stocktwits_sentiment_counts(symbol, *, now=None):
    """读某标的最新公开消息里的平台情绪标签（Bullish / Bearish），只计数不复制正文。"""
    payload, _, _ = safe_request_with_fallback(_backup.get_stocktwits_urls("stream", symbol=symbol),
                           headers=_PLATFORM_HEADERS, params={"limit": STOCKTWITS_MESSAGES_PER_STREAM},
                           timeout=8)
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        return None
    bull = bear = checked = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        checked += 1
        sentiment = (message.get("entities") or {}).get("sentiment") or {}
        basic = str(sentiment.get("basic") or "").strip().lower()
        if basic == "bullish":
            bull += 1
        elif basic == "bearish":
            bear += 1
    return {"checked": checked, "bull": bull, "bear": bear}


def fetch_stocktwits():
    """StockTwits 公开趋势榜：平台标的榜 + 平台多空摘要 + 消息情绪标签统计。

    只读公开 JSON：趋势榜给出 rank / trending_score / 关注人数与平台生成的多空讨论摘要
    （Bullish posts… / bears question…）；再对榜单前排标的取最新公开消息，统计平台自带的
    Bullish / Bearish 标签条数（只计数，不复制消息正文）。社区观点未经核实，非投资建议。
    """
    name = "StockTwits"
    now = datetime.now(CST)
    # 数据线 stocktwits：主源 trending/symbols → 备用源1 trending/symbols/equities（同格式）
    #                    → 备用源2 streams/trending（按消息聚合标的，独立解析）
    urls = _backup.get_stocktwits_urls("trending")
    payload, _, _ = safe_request_with_fallback(
        urls, headers=_PLATFORM_HEADERS, timeout=10, line="stocktwits",
        validate=lambda d: isinstance(d, dict) and isinstance(d.get("symbols"), list) and d["symbols"])
    symbols = payload.get("symbols") if isinstance(payload, dict) else None
    if not isinstance(symbols, list) or not symbols:
        stream_url = _backup.candidates("stocktwits")[2][1]
        stream, _, _ = safe_request_with_fallback(
            [stream_url], headers=_PLATFORM_HEADERS, timeout=10,
            validate=lambda d: isinstance(d, dict) and isinstance(d.get("messages"), list))
        symbols = _stocktwits_symbols_from_stream(stream)
        if symbols:
            print("  ✅ 备用源2（StockTwits streams/trending）顶上：按热门消息聚合标的")
            _note_backup_served("stocktwits", stream_url)
    if not isinstance(symbols, list) or not symbols:
        return _public_site_result(name, [], error="公开趋势榜接口未返回有效数据")

    ranked = []
    for source_position, row in enumerate(symbols, 1):
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        try:
            rank = int(row.get("rank")) if row.get("rank") is not None else source_position
            if rank <= 0:
                rank = source_position
        except (TypeError, ValueError, OverflowError):
            rank = source_position
        ranked.append((rank, row))
    ranked.sort(key=lambda pair: pair[0])

    # 榜单前排标的的情绪标签统计（并行，失败只影响该标的的附加信息）
    counts = {}
    stream_targets = [row.get("symbol") for _rank, row in ranked[:STOCKTWITS_STREAM_N]]
    if stream_targets:
        with ThreadPoolExecutor(max_workers=len(stream_targets)) as executor:
            futures = {executor.submit(_stocktwits_sentiment_counts, sym): sym
                       for sym in stream_targets}
            for future in futures:
                sym = futures[future]
                try:
                    counts[sym] = future.result()
                except Exception:
                    counts[sym] = None

    items, latest = [], None
    for rank, row in ranked:
        if len(items) >= STOCKTWITS_TRENDING_N:
            break
        symbol = str(row.get("symbol") or "").strip()
        title = _public_text(row.get("title") or symbol, 120)
        url = _public_url(f"/symbol/{symbol}", PUBLIC_SITE_URLS[name])
        if not (symbol and title and url):
            continue
        raw_watchers = row.get("watchlist_count")
        try:
            watchers = int(raw_watchers) if raw_watchers is not None else None
            if watchers is not None:
                watchers = max(0, watchers)
        except (TypeError, ValueError, OverflowError):
            watchers = None
        raw_trending_score = row.get("trending_score")
        try:
            trending_score = (int(raw_trending_score)
                              if raw_trending_score is not None else None)
        except (TypeError, ValueError, OverflowError):
            trending_score = None
        trends = row.get("trends") or {}
        published = _cst_from_iso(trends.get("summary_at"))
        if published is None:
            published = now
        if not latest or published > latest:
            latest = published
        bits = [f"平台趋势榜 #{rank}"]
        if watchers is not None:
            bits.append(f"关注 {watchers:,} 人")
        summary = _public_text(trends.get("summary"), 150)
        if summary:
            bits.append(f"平台多空摘要（{published.strftime('%m-%d %H:%M')} 北京时间）：{summary}")
        label = counts.get(symbol)
        if label and label.get("checked"):
            bits.append(f"近 {label['checked']} 条消息平台标签：看多 {label['bull']} / 看空 {label['bear']}")
        items.append(_platform_item(
            name, "平台趋势榜", f"{symbol} · {title}", url, published,
            detail=" · ".join(bits), symbol=symbol, rank=rank,
            watchlist_count=watchers, trending_score=trending_score,
            sentiment_counts=label if isinstance(label, dict) else None, now=now))
    note = ("StockTwits 为公开趋势榜与平台自带情绪标签，只计数不复制消息正文；"
            "散户情绪热度不等于事实或投资建议。")
    return _public_site_result(name, items,
                               latest=latest.strftime("%Y-%m-%d") if latest else None,
                               note=note,
                               error="公开趋势榜不可用或窗口内无可核实标的")


def fetch_tradingview():
    """TradingView 公开 Ideas RSS：交易员最新观点（标题自带标的与方向词）。"""
    name = "TradingView"
    now = datetime.now(CST)
    xml, _, _ = safe_request_with_fallback(_backup.get_tradingview_urls(), headers={**_PLATFORM_HEADERS,
                                                      "Accept": "application/rss+xml,application/xml"},
                       is_json=False, timeout=10, line="tradingview",
                       validate=lambda t: "<item" in str(t) or "<entry" in str(t))
    items, latest = _platform_rss_items(xml, name, PUBLIC_SITE_URLS[name],
                                        limit=TRADINGVIEW_IDEAS_N, now=now,
                                        community="交易员观点")
    note = ("TradingView 公开 Ideas 观点标题与链接；交易员观点未经核实，"
            "方向词仅供参考，非投资建议。")
    return _public_site_result(name, items, latest=latest, note=note,
                               error="公开 Ideas RSS 不可用或近72小时无新观点")


_BOGLEHEADS_BOARDS = {
    "Investing - Theory, News & General": "投资理论 · 新闻 · 综合",
    "Personal Investments": "个人投资组合",
    "Personal Finance (Not Investing)": "个人理财（非投资）",
    "Personal Consumer Issues": "个人消费",
    "Non-US Investing": "非美市场投资",
    "Local Chapters and Bogleheads Community": "本地分会与社区",
}


def _bogleheads_title(raw_title, _summary):
    """Bogleheads 标题形如「板块 • Re: 主题」，拆成中文板块名 + 主题。"""
    board, sep, topic = str(raw_title or "").partition("•")
    if not sep:
        return "论坛最新主题", raw_title
    board = board.strip()
    topic = re.sub(r"^Re:\s*", "", topic.strip())
    return _BOGLEHEADS_BOARDS.get(board, board or "论坛最新主题"), topic or board


def fetch_bogleheads():
    """Bogleheads.org 公开 RSS：长期投资者论坛最新讨论主题。"""
    name = "Bogleheads"
    now = datetime.now(CST)
    xml, _, _ = safe_request_with_fallback(_backup.get_bogleheads_urls(), headers={**_PLATFORM_HEADERS,
                                                     "Accept": "application/rss+xml,application/xml"},
                       is_json=False, timeout=10, line="bogleheads",
                       validate=lambda t: "<item" in str(t) or "<entry" in str(t))
    items, latest = _platform_rss_items(xml, name, PUBLIC_SITE_URLS[name],
                                        limit=BOGLEHEADS_TOPICS_N, now=now,
                                        community="论坛最新主题",
                                        title_cleaner=_bogleheads_title)
    note = ("Bogleheads 公开论坛新帖标题；长期投资者讨论偏配置与纪律，"
            "未经核实，非投资建议。")
    return _public_site_result(name, items, latest=latest, note=note,
                               error="公开论坛 RSS 不可用或近72小时无新主题")


def fetch_public_sites():
    """多平台信息员并行采集：单个平台失败不会拖垮其他平台或主日报；始终返回审计记录。"""
    fetchers = {
        "Reddit": fetch_reddit,
        "StockTwits": fetch_stocktwits,
        "TradingView": fetch_tradingview,
        "Bogleheads": fetch_bogleheads,
    }
    names = [n for n in _active_public_site_names() if n in fetchers]
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, len(names))) as executor:
        futures = [(name, executor.submit(fetchers[name])) for name in names]
        for name, future in futures:
            try:
                result = future.result()
                if (not isinstance(result, dict) or result.get("source") != name
                        or result.get("status") not in ("success", "unavailable")
                        or not isinstance(result.get("items"), list)):
                    raise ValueError("采集返回格式异常")
            except Exception as exc:
                print(f"  ⚠️ {name} 采集失败（{type(exc).__name__}）")
                result = _public_site_result(name, [], error="公开数据解析失败或暂时不可用")
            results[name] = result
            print(f"  {'✅' if result['status'] == 'success' else '⚠️'} {name}: "
                  f"{len(result.get('items') or [])} 条公开样本")
    return results


# ============================================================
# 趋势跟踪 · 全网 36 个新闻源头（港股挖掘 + 规则分析）
# ============================================================
# 港股相关判定：标题命中下列任一关键词（子串匹配，英文不区分大小写）。
# 覆盖指数/市场（港股、恒生、恒指、H股、南向…）、香港本地（香港、本港、港府、
# 金管局…）与英文同义（Hang Seng、Hong Kong、HKEX、Southbound…）；
# 未命中的标题只计入「扫描」条数，不进栏目正文，避免把无关国际新闻算成港股信息。
_HK_NEWS_KEYWORDS = (
    "港股", "恒生", "恒指", "恒科", "港交所", "联交所", "H股", "港股通", "南向",
    "沪深港通", "红筹", "紅籌", "窝轮", "窩輪", "牛熊证", "牛熊證", "国企指数", "大市",
    "香港", "本港", "全港", "港府", "金管局", "财政司", "港元",
    # 仅在香港上市的权重/明星股（用全称避免误伤 A 股同名概念；A+H 同名股不收，
    # 否则「中芯国际」「比亚迪」这类 A 股高频词会把大量 A 股新闻算成港股信息）
    "腾讯控股", "阿里巴巴", "美团", "快手", "泡泡玛特", "友邦保险", "汇丰控股",
    "香港交易所", "小米集团", "京东集团", "网易", "商汤",
    "Hang Seng", "Hong Kong", "HKEX", "HSCEI", "Southbound", "H-share", "Stock Connect",
)
_HK_NEWS_KW_RE = re.compile("|".join(re.escape(k) for k in _HK_NEWS_KEYWORDS), re.I)

# 热点主题词表（子串 / ASCII 单词边界命中）：分析只统计命中量排序，不推断因果。
HK_THEME_KEYWORDS = {
    "南向资金": ("南向", "港股通", "沪深港通", "南下", "净买入", "southbound", "stock connect"),
    "利率/美债": ("美联储", "加息", "降息", "利率", "美债", "收益率", "金管局", "fed", "treasury", "yield"),
    "AI/科技": ("AI", "人工智能", "大模型", "算力", "芯片", "半导体", "科技", "恒科",
                "腾讯", "阿里", "小米", "nvidia"),
    "IPO/上市": ("IPO", "上市", "招股", "新股", "分拆", "挂牌", "listing"),
    "政策/监管": ("政策", "监管", "证监会", "改革", "咨询", "意见稿", "sfc", "probe"),
    "地产/楼市": ("地产", "楼市", "内房", "物业", "property"),
    "医药/创新药": ("医药", "创新药", "生物", "biotech", "pharma"),
    "消费/零售": ("消费", "零售", "旅游", "retail", "消费券"),
    "资源/大宗": ("黄金", "原油", "油价", "铜价", "矿业", "gold", "oil"),
    "汇率/货币": ("港元", "汇率", "美元", "人民币", "currency", "devalu"),
}
_HK_THEME_TOP_N = 3


def _news_url(raw, hosts):
    """新闻源头外链白名单：仅允许 https + 该源头自己列出的主机名（精确匹配）。

    与 Reddit 源的 _public_url 同口径，防止外部标题/链接注入日报；
    相对链接（无主机名）、非 443 端口、带账号密码的 URL 一律拒绝。
    """
    if not raw or any(c.isspace() or c in ('<', '>', '\\') for c in str(raw).strip()):
        return ""
    try:
        parsed = urlparse(str(raw).strip())
        if (parsed.scheme != "https" or parsed.hostname not in set(hosts or ())
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            return ""
    except ValueError:
        return ""
    return str(raw).strip()


# 只提供 http 原文的站点：本仓库**逐站实测确认 https 版可访问**后才放进这里，
# 放行后链接从「平台跳转」升级为「原文直达」。没实测过的站一个都不放——
# 与其猜一个可能打不开的链接，不如退回平台跳转（或如实剔除）。
# 已实测：jjckb.cn（2026-10-13 打开 https 首页正常）；zqrb.cn 实测 https 打不开，故不列入。
_SEARCH_HTTP_UPGRADE_HOSTS = ("jjckb.cn", "www.jjckb.cn")


def _https_upgrade(raw, hosts):
    """http 原文链接 → https（仅限 ``_SEARCH_HTTP_UPGRADE_HOSTS`` 里实测过的主机）。"""
    u = str(raw or "").strip()
    if not u.lower().startswith("http://"):
        return ""
    try:
        host = (urlparse(u).hostname or "").lower()
    except ValueError:
        return ""
    if host not in _SEARCH_HTTP_UPGRADE_HOSTS:
        return ""
    return _news_url("https" + u[4:], hosts)


def _resolve_search_link(raw, hosts):
    """检索平台跳转链接 → 可渲染的外链（站内检索路径专用）。

    2026-10-13 修：Bing News 站内检索 RSS 的 <link> 是
    ``http://www.bing.com/news/apiclick.aspx?...&url=<原文链接>``——明文 http +
    跳转域名，直接交给 ``_news_url``（要求 https + 白名单主机）会被整条拒掉，
    于是**所有依赖站内检索的源头天天 0 条**（内地财经媒体 18 家即为此列队，
    自 2026-10-12 上线起每份日报都写成「暂缺」）。

    两步还原，任一步都保持「不猜、不降级放行」的旧口径：
      ① 解出跳转地址 ``url=`` 参数指向的原文链接（https + 媒体自己的域名）→ 直达原文；
      ② 解不出来、或原文链接不过白名单（例如该站只提供 http 原文）→ 把跳转链接
         自身升级为 https 再校验一次（Bing / Google News 均支持 https 跳转）；
      ③ 仍不过 → 返回空，该条目整条剔除（与 _news_url 完全同口径）。

    非跳转链接（官方订阅里的原文直链）第一步就原样返回，行为与旧版一致。
    """
    direct = _news_url(raw, hosts) or _https_upgrade(raw, hosts)
    if direct:
        return direct
    raw_s = str(raw or "").strip()
    try:
        parsed = urlparse(raw_s)
    except ValueError:
        return ""
    if not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    if host == "bing.com" or host.endswith(".bing.com") or host.endswith("news.google.com"):
        # ① Bing 把原文地址百分号编码在 url= 参数里（可能是 https，也可能是只提供
        #    http 原文的老站）——解出来过白名单就用它（直达原文，体验最好）。
        cand = (parse_qs(parsed.query or "").get("url") or [""])[0]
        if cand:
            cand = unquote(cand).strip()
            resolved = _news_url(cand, hosts) or _https_upgrade(cand, hosts)
            if resolved:
                return resolved
        # ② 原文链接不可用（如该站只提供 http 原文）→ 平台跳转链接自身升级为 https。
        if parsed.scheme == "http":
            return _news_url("https" + raw_s[4:], hosts)
    return ""


def _hk_theme_hits(word, text):
    """主题词命中计数：ASCII 词按字母边界（避免 rate 命中 generate），中文按子串。"""
    if all(ord(c) < 128 for c in word):
        return len(re.findall(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])",
                              str(text or ""), re.I))
    return str(text or "").count(word)


def _hk_news_themes(titles, top_n=_HK_THEME_TOP_N):
    """港股相关标题的热点主题 TOP：只按词表命中量排序，无命中返回空（不猜）。"""
    counts = {}
    for theme, words in HK_THEME_KEYWORDS.items():
        hits = sum(_hk_theme_hits(w, t) for t in titles for w in words)
        if hits:
            counts[theme] = hits
    return [name for name, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]]


def _hk_news_bull_bear(titles):
    """港股相关标题的多空证据：中文词表 + 英文多空词（与 Reddit 源同一套英文词表）。"""
    zh_bull, zh_bear = _zh_title_bull_bear(titles)
    en_bull = sum(len(_REDDIT_BULL_RE.findall(str(t or ""))) for t in titles)
    en_bear = sum(len(_REDDIT_BEAR_RE.findall(str(t or ""))) for t in titles)
    return zh_bull + en_bull, zh_bear + en_bear


def _hk_news_analysis(records):
    """36 个新闻源头的港股挖掘分析（确定性规则，可复现，不调大模型）。

    输入是 fetch 返回的逐源记录，输出：
      scanned/ok_n/hk_n —— 覆盖度；bull/bear/prob/label —— 多空词概率（5%~95%）；
      themes —— 热点主题 TOP；top_sources —— 命中最多源头；today_n/newest —— 新鲜度。
    """
    ok_n = empty_n = fail_n = 0
    scanned = hk_n = today_n = 0
    titles, top_sources, newest = [], [], None
    for rec in records if isinstance(records, (list, tuple)) else []:
        if not isinstance(rec, dict):
            continue
        status = rec.get("status")
        if status == "ok":
            ok_n += 1
        elif status == "empty":
            empty_n += 1
        else:
            fail_n += 1
        scanned += int(rec.get("scanned") or 0)
        today_n += int(rec.get("today") or 0)
        d = str(rec.get("newest") or "")[:10]
        if d and (not newest or d > newest):
            newest = d
        items = [it for it in (rec.get("items") or []) if isinstance(it, dict)]
        hk_titles = [str(t) for t in (rec.get("hk_titles") or [])
                     if isinstance(t, str) and t]
        if not hk_titles:
            hk_titles = [str(it.get("title") or "") for it in items]
        hk_n += int(rec.get("hk_n") or len(items))
        titles.extend(hk_titles)
        if hk_titles:
            top_sources.append((str(rec.get("name") or ""), int(rec.get("hk_n") or len(hk_titles))))
    bull, bear = _hk_news_bull_bear(titles)
    prob = _ai_judge_prob(bull, bear)
    mark, label = _ai_judge_label(prob)
    top_sources.sort(key=lambda kv: (-kv[1], kv[0]))
    return {
        "scanned": scanned, "hk_n": hk_n, "ok_n": ok_n, "empty_n": empty_n,
        "fail_n": fail_n, "today_n": today_n, "newest": newest,
        "bull": bull, "bear": bear, "prob": prob, "mark": mark, "label": label,
        "themes": _hk_news_themes(titles), "top_sources": top_sources[:3],
        "total": len(records) if isinstance(records, (list, tuple)) else 0,
    }


_HK_NEWS_BACKUP_LINK_HOSTS = ("www.bing.com", "bing.com", "news.google.com")


def _hk_news_site_host(cfg):
    """新闻源头用于 site: 检索的主域名：取 hosts 里最短的一个（如 hket.com）。

    2026-10-13 起支持 ``site`` 字段显式指定：凤凰网财经这类「财经频道挂在泛资讯
    大域下」的媒体，检索最短域（ifeng.com）抓回来的多是资讯 / 地方 / 汽车频道，
    财经条目的占比低到没法用；指定 finance.ifeng.com 才检索到财经频道本身。
    """
    override = str(cfg.get("site") or "").strip()
    if override:
        return override
    hosts = [h for h in (cfg.get("hosts") or ()) if h]
    if not hosts:
        try:
            return urlparse(cfg.get("url") or cfg.get("feed") or "").hostname or ""
        except ValueError:
            return ""
    return sorted(hosts, key=len)[0]


def fetch_hk_news_sources():
    """抓取全网 36 个新闻源头的公开 RSS/Atom 订阅，挖掘港股相关信息。

    逐源并行抓取 → 只保留 72 小时窗口内、带可验证时区发布时间的条目 →
    按港股关键词命中筛选（未命中只计扫描数）→ 每源至多 HK_NEWS_PER_SOURCE 条、
    全栏目至多 HK_NEWS_MAX_ITEMS 条 → 规则合成分析。
    单源失败不影响其余源；全部失败时整源 unavailable 并给出原因，绝不历史兜底。
    """
    if not HK_NEWS_ENABLED:
        print("⏭ 已关闭全网新闻源头采集（OCTOPUS_HK_NEWS=0）")
        return _source_result(HK_NEWS_SOURCE_NAME, "unavailable", sources=[], analysis=None,
                              note="", error="本次运行已关闭新闻源头采集（OCTOPUS_HK_NEWS=0）")

    print(f"📡 正在采集趋势跟踪 · 全网 {len(HK_NEWS_SOURCES)} 个新闻源头（港股挖掘）...")
    now = datetime.now(CST)

    def _fetch_one(cfg):
        # 数据线 hk_news_rss：主源 媒体官方订阅 → 备用源1 Bing 站内检索 RSS → 备用源2 Google News 站内检索 RSS
        # 2026-10-13 修：候选源逐个试到「有可用条目」为止（与内地财经媒体同口径）——
        # 旧版停在第一个「解析得出条目」的源，Bing 检索 RSS 的明文 http 跳转链接会被
        # 白名单整条拒掉，导致配了官方订阅却取不到的源头（24 家里的一大半）直接判空，
        # 后面能用的 Google News 备用源根本轮不到。
        site_host = _hk_news_site_host(cfg)
        hk_urls = [cfg["feed"]] + _backup.get_news_site_backup_urls(site_host)
        base_hosts = tuple(cfg.get("hosts") or ())
        rec = {"name": cfg.get("name", "?"), "region": cfg.get("region", ""),
               "url": cfg.get("url", ""), "hosts": base_hosts,
               "desc": cfg.get("desc", ""), "feed": cfg.get("feed", ""),
               "status": "fail", "scanned": 0, "today": 0, "newest": None,
               "items": [], "hk_titles": [], "hk_n": 0, "note": "", "served_by": "—"}
        tried, last_parsed_empty = 0, None
        for _url in hk_urls:
            xml_text, served_url, _ = safe_request_with_fallback(
                [_url], is_json=False, timeout=10,
                validate=lambda t: bool(_parse_rss_items(t, limit=HK_NEWS_SCAN_LIMIT)))
            parsed = _parse_rss_items(xml_text, limit=HK_NEWS_SCAN_LIMIT) if xml_text else []
            if not parsed:
                continue
            tried += 1
            via_backup = bool(served_url) and served_url != cfg["feed"]
            allowed_hosts = base_hosts
            if via_backup:
                # 备用源条目的链接经检索平台跳转：放行该平台主机名（仍要求 https）
                allowed_hosts = base_hosts + _HK_NEWS_BACKUP_LINK_HOSTS
            fresh, newest, fresh_today = [], None, 0
            for row in parsed:
                raw_date = str(row.get("published") or "").strip()
                # 没有显式时区就不能确定自然日，拒绝用运行机器的本地时区猜测（与 Reddit 源同口径）。
                if not re.search(r"(?:Z|[+-]\d{2}:?\d{2}|\bGMT|\bUTC)$", raw_date, re.I):
                    continue
                try:
                    dt = datetime.strptime(str(row.get("published_cst") or ""),
                                           "%Y-%m-%d %H:%M").replace(tzinfo=CST)
                except ValueError:
                    continue
                if not _public_recent(dt, now, HK_NEWS_WINDOW_HOURS):
                    continue
                url = (_news_url(row.get("url"), allowed_hosts) if not via_backup
                       else _resolve_search_link(row.get("url"), allowed_hosts))
                title = _public_text(row.get("title"), 160)
                if via_backup and " - " in title:
                    title = title.rsplit(" - ", 1)[0].strip() or title   # 检索平台附加的「 - 媒体名」
                if not (url and title):
                    continue
                fresh.append({"title": title, "url": url,
                              "published_cst": dt.strftime("%Y-%m-%d %H:%M"),
                              "is_today": dt.date() == now.date(),
                              "relevant": bool(_HK_NEWS_KW_RE.search(title))})
                if not newest or dt > newest:
                    newest = dt
                if dt.date() == now.date():
                    fresh_today += 1
            if not fresh:
                # 解析成功但 0 条可用（例如检索源链接全被拒）→ 换下一个候选源再试。
                last_parsed_empty = served_url or _url
                continue
            if via_backup:
                _note_backup_served("hk_news_rss", served_url, feed=cfg["feed"], host=site_host)
            hk_all = [it for it in fresh if it["relevant"]]
            hk_items = hk_all[:HK_NEWS_PER_SOURCE]
            for it in hk_items:
                it["detail"] = f"发布于 {it['published_cst']}（北京时间）"
            rec.update({
                "status": "ok", "scanned": len(fresh), "today": fresh_today,
                "newest": newest.strftime("%Y-%m-%d"), "items": hk_items,
                "hk_titles": [it["title"] for it in hk_all],
                "hk_n": len(hk_all),
                "served_by": ("备用源" if via_backup else "主源"),
            })
            if via_backup:
                rec["note"] = ("官方订阅不可用，本次经站内检索备用源"
                               f"（{'Bing' if 'bing.com' in served_url else 'Google News'}）取得")
            return rec
        rec["note"] = (f"近 {HK_NEWS_WINDOW_HOURS} 小时窗口内无可验证发布时间的新内容"
                       f"（已试 {tried} 路候选源" +
                       (f"，最后一路 {last_parsed_empty}）" if last_parsed_empty else "）")
                      if tried else
                      "自动抓取失败（源可能需登录/被限流，或订阅地址变化），暂缺")
        if tried:
            rec["status"] = "empty"
        return rec

    records = [None] * len(HK_NEWS_SOURCES)
    with ThreadPoolExecutor(max_workers=min(10, len(HK_NEWS_SOURCES))) as executor:
        futures = {executor.submit(_fetch_one, cfg): idx
                   for idx, cfg in enumerate(HK_NEWS_SOURCES)}
        for future, idx in futures.items():
            try:
                records[idx] = future.result()
            except Exception as exc:  # 单源异常只标记该源，不拖垮其余源头
                cfg = HK_NEWS_SOURCES[idx]
                records[idx] = {"name": cfg.get("name", "?"), "region": cfg.get("region", ""),
                                "url": cfg.get("url", ""), "hosts": tuple(cfg.get("hosts") or ()),
                                "desc": cfg.get("desc", ""), "feed": cfg.get("feed", ""),
                                "status": "fail", "scanned": 0, "today": 0, "newest": None,
                                "items": [], "hk_titles": [], "hk_n": 0,
                                "note": f"抓取异常（{type(exc).__name__}），暂缺"}
    records = [r for r in records if isinstance(r, dict)]

    analysis = _hk_news_analysis(records)
    missing = [r["name"] for r in records if r.get("status") != "ok"]
    note = ("只收录 36 个新闻源头公开订阅的标题、发布时间与原文链接（北京时间），"
            "港股相关按关键词命中筛选；分析为多空词表 + 主题词表的规则合成，"
            "社区与媒体观点未经核实，不构成投资建议。")
    if missing:
        note += f" 暂缺（{len(missing)} 家）：" + "、".join(missing) + "。"

    if analysis["scanned"] == 0:
        reason = (f"近 {HK_NEWS_WINDOW_HOURS} 小时窗口内 36 个源头均未取得"
                  "带可验证时区发布时间的新闻（网络受限或订阅地址变化）")
        print(f"  ⚠️ 全网新闻源头暂不可用：{reason}")
        return _source_result(HK_NEWS_SOURCE_NAME, "unavailable",
                              sources=records, analysis=analysis, note=note, error=reason)

    hk_n, ok_n = analysis["hk_n"], analysis["ok_n"]
    print(f"  ✅ {ok_n}/{len(HK_NEWS_SOURCES)} 个源头窗口内有更新 · 扫描 {analysis['scanned']} 条"
          f" · 港股相关 {hk_n} 条 · 多空 {analysis['bull']}/{analysis['bear']}"
          + (f" · 热点 {'、'.join(analysis['themes'])}" if analysis["themes"] else ""))
    if missing:
        print(f"  🕐 {len(missing)} 个源头暂缺：" + "、".join(missing))
    return _source_result(
        HK_NEWS_SOURCE_NAME, "success",
        is_today=analysis["today_n"] > 0, content_date=analysis["newest"],
        sources=records, analysis=analysis, note=note,
        partial=bool(missing), error=None)


# ============================================================
# 内地财经媒体源头 · 18 家（2026-10-12 新增；标题池供新闻情绪 / 政策因子共用）
# ============================================================
def fetch_mainland_news_sources():
    """抓取 18 家内地财经媒体的公开标题，供新闻情绪因子 / 政策因子 / 策略研判共用。

    与「港股新闻源头」同一套诚实口径：
      · 逐源并行；每源取数路径 = 官方订阅（若配了 feed）→ 站内检索 RSS（Bing → Google News）；
      · 只保留 72 小时窗口内、带可验证时区发布时间的条目；
      · 链接按该媒体自己的域名白名单校验（https + 主机名精确匹配），防标题 / 链接注入；
      · 不做港股关键词过滤（这 18 家是内地财经 / 证券 / 科技媒体，全量进标题池），
        但每源至多 MAINLAND_NEWS_PER_SOURCE 条、全栏目至多 MAINLAND_NEWS_MAX_ITEMS 条；
      · 同一个标题被两家媒体转出时只留首次出现的那条（并如实记 merged 条数）；
      · 单源失败只标该源暂缺；全部取不到时整源 unavailable 并给出原因，绝不历史兜底。
    说明：这些媒体多数已无官方 RSS，默认走站内检索按站点取公开标题——本条数据线的
    主源仍是「官方订阅（若有）」，站内检索同时充当备用源，归属见 backup_sources。
    """
    if not MAINLAND_NEWS_ENABLED:
        print("⏭ 已关闭内地财经媒体源头采集（OCTOPUS_MAINLAND_NEWS=0）")
        return _source_result(MAINLAND_NEWS_SOURCE_NAME, "unavailable", sources=[], headlines=[],
                              analysis=None, note="",
                              error="本次运行已关闭内地财经媒体源头采集（OCTOPUS_MAINLAND_NEWS=0）")

    print(f"📡 正在采集内地财经媒体源头 {MAINLAND_NEWS_TOTAL} 家"
          f"（官方订阅 / 站内检索 → 标题池：新闻情绪 + 政策因子）...")
    now = datetime.now(CST)

    def _fetch_one(cfg):
        site_host = _hk_news_site_host(cfg)
        official_feed = str(cfg.get("feed") or "").strip()
        search_urls = _backup.get_mainland_news_site_urls(site_host)
        urls = ([official_feed] + search_urls) if official_feed else search_urls
        base_hosts = tuple(cfg.get("hosts") or ())
        rec = {"name": cfg.get("name", "?"), "region": cfg.get("region", ""),
               "url": cfg.get("url", ""), "hosts": base_hosts,
               "desc": cfg.get("desc", ""), "feed": official_feed,
               "status": "fail", "scanned": 0, "today": 0, "newest": None,
               "items": [], "titles": [], "note": "", "served_by": "—",
               # 时效体检字段（2026-10-13 新增，供「情绪热点因子量化分析」的源头体检行使用）
               "newest_cst": None, "lag_hours": None, "state": "暂缺", "via": "—"}
        # 2026-10-13 修：候选源逐个试，直到拿到**可用条目**为止。
        # 旧版只试第一个「解析得出条目」的源——Bing 检索 RSS 解析没问题，但条目链接
        # 全是明文 http 跳转、会被白名单整条拒掉，于是停在 Bing 上永远 0 条，
        # 后面真正能用的 Google News 备用源根本轮不到。解析成功但 0 条可用 → 继续下一个。
        tried, last_parsed_empty = 0, None
        for _url in urls:
            xml_text, served_url, _ = safe_request_with_fallback(
                [_url], is_json=False, timeout=10,
                validate=lambda t: bool(_parse_rss_items(t, limit=MAINLAND_NEWS_SCAN_LIMIT)))
            parsed = _parse_rss_items(xml_text, limit=MAINLAND_NEWS_SCAN_LIMIT) if xml_text else []
            if not parsed:
                continue
            tried += 1
            via_official = bool(official_feed) and served_url == official_feed
            via_backup = bool(official_feed) and bool(served_url) and not via_official
            via_search = (not official_feed) and bool(served_url)
            allowed_hosts = base_hosts
            if via_backup or via_search:
                allowed_hosts = base_hosts + _HK_NEWS_BACKUP_LINK_HOSTS
            fresh, newest, fresh_today = [], None, 0
            for row in parsed:
                raw_date = str(row.get("published") or "").strip()
                # 没有显式时区就不确定自然日，拒绝用运行机器的本地时区猜测（与港股新闻源头同口径）。
                if not re.search(r"(?:Z|[+-]\d{2}:?\d{2}|\bGMT|\bUTC)$", raw_date, re.I):
                    continue
                try:
                    dt = datetime.strptime(str(row.get("published_cst") or ""),
                                           "%Y-%m-%d %H:%M").replace(tzinfo=CST)
                except ValueError:
                    continue
                if not _public_recent(dt, now, MAINLAND_NEWS_WINDOW_HOURS):
                    continue
                # 检索源的链接是平台跳转（Bing 还是明文 http），交给 _resolve_search_link 还原
                url = (_news_url(row.get("url"), allowed_hosts) if via_official
                       else _resolve_search_link(row.get("url"), allowed_hosts))
                title = _public_text(row.get("title"), 160)
                if not via_official and " - " in title:
                    title = title.rsplit(" - ", 1)[0].strip() or title   # 检索平台附加的「 - 媒体名」
                if not (url and title):
                    continue
                fresh.append({"title": title, "url": url,
                              "published_cst": dt.strftime("%Y-%m-%d %H:%M"),
                              "date": dt.strftime("%Y-%m-%d"),
                              "is_today": dt.date() == now.date()})
                if not newest or dt > newest:
                    newest = dt
                if dt.date() == now.date():
                    fresh_today += 1
            if not fresh:
                # 解析得出条目、但过滤后 0 条可用：记一笔，换下一个候选源再试。
                last_parsed_empty = served_url or _url
                continue
            if via_backup:
                # 只在该媒体「配了官方订阅却没取到」时记备用源事件；无官方订阅的站内检索是常规路径。
                _note_backup_served("mainland_news_rss", served_url,
                                    feed=official_feed, host=site_host)
            items = fresh[:MAINLAND_NEWS_PER_SOURCE]
            for it in items:
                it["detail"] = f"发布于 {it['published_cst']}（北京时间）"
            # 时钟抖动（抓取时刻略早于条目时间，偶发几秒）不允许出现负滞后。
            lag_hours = max(0.0, round((now - newest).total_seconds() / 3600.0, 1))
            rec.update({
                "status": "ok", "scanned": len(fresh), "today": fresh_today,
                "newest": newest.strftime("%Y-%m-%d"), "items": items,
                "titles": [it["title"] for it in fresh],
                "newest_cst": newest.strftime("%Y-%m-%d %H:%M"), "lag_hours": lag_hours,
                "state": ("当天" if newest.date() == now.date() else "窗口内滞后"),
                "via": ("官方订阅" if via_official else
                        ("Bing 站内检索" if "bing.com" in (served_url or "")
                         else "Google 站内检索")),
                "served_by": ("官方订阅" if via_official else
                              ("备用源（站内检索）" if via_backup else
                               ("站内检索" if via_search else "—")))})
            if via_backup:
                rec["note"] = ("官方订阅不可用，本次经站内检索备用源"
                               f"（{'Bing' if 'bing.com' in served_url else 'Google News'}）取得")
            elif via_search:
                rec["note"] = "该媒体无可用官方订阅，本次经站内检索 RSS 取得公开标题"
            return rec
        if tried:
            rec["status"] = "empty"
            rec["note"] = (f"近 {MAINLAND_NEWS_WINDOW_HOURS} 小时窗口内无可验证发布时间的新内容"
                           f"（已试 {tried} 路候选源" +
                           (f"，最后一路 {last_parsed_empty}）" if last_parsed_empty else "）"))
        else:
            rec["note"] = ("自动抓取失败（源可能被限流、订阅地址变化，或站内检索无结果），暂缺"
                           if official_feed else
                           "站内检索未返回结果（可能被限流或该站未被检索平台收录），暂缺")
        return rec

    records = [None] * MAINLAND_NEWS_TOTAL
    with ThreadPoolExecutor(max_workers=min(10, MAINLAND_NEWS_TOTAL)) as executor:
        futures = {executor.submit(_fetch_one, cfg): idx
                   for idx, cfg in enumerate(MAINLAND_NEWS_SOURCES)}
        for future, idx in futures.items():
            try:
                records[idx] = future.result()
            except Exception as exc:  # 单源异常只标记该源，不拖垮其余源头
                cfg = MAINLAND_NEWS_SOURCES[idx]
                records[idx] = {"name": cfg.get("name", "?"), "region": cfg.get("region", ""),
                                "url": cfg.get("url", ""), "hosts": tuple(cfg.get("hosts") or ()),
                                "desc": cfg.get("desc", ""), "feed": str(cfg.get("feed") or ""),
                                "status": "fail", "scanned": 0, "today": 0, "newest": None,
                                "items": [], "titles": [], "served_by": "—",
                                "note": f"抓取异常（{type(exc).__name__}），暂缺"}
    records = [r for r in records if isinstance(r, dict)]

    # 跨源同题去重（同一篇被两家转出只留一次），并汇总标题池
    headlines, merged = [], 0
    seen = set()
    for rec in records:
        for it in rec.get("items") or []:
            key = re.sub(r"\s+", "", str(it.get("title") or ""))
            if key and key in seen:
                merged += 1
                continue
            if key:
                seen.add(key)
            headlines.append({"title": it["title"], "source": rec["name"],
                              "section": MAINLAND_NEWS_SECTION, "url": it["url"],
                              "published_cst": it["published_cst"], "date": it["date"],
                              "is_today": it["is_today"]})
            if len(headlines) >= MAINLAND_NEWS_MAX_ITEMS:
                break
        if len(headlines) >= MAINLAND_NEWS_MAX_ITEMS:
            break

    ok_n = sum(1 for r in records if r.get("status") == "ok")
    scanned = sum(int(r.get("scanned") or 0) for r in records)
    today_n = sum(int(r.get("today") or 0) for r in records)
    newest = max((r["newest"] for r in records if r.get("newest")), default=None)
    missing = [r["name"] for r in records if r.get("status") != "ok"]
    # 时效体检（2026-10-13 新增）：逐源记「窗口内条数 / 最新条目北京时间 / 滞后小时数 /
    # 当天还是滞后」，供【沸腾花蛤】情绪热点因子量化分析的体检行与总结的数据覆盖共用。
    health = [{"name": r.get("name", "?"), "status": r.get("status", "fail"),
               "items": len([it for it in (r.get("items") or []) if isinstance(it, dict)]),
               "newest_cst": r.get("newest_cst"), "lag_hours": r.get("lag_hours"),
               "state": r.get("state") or "暂缺", "via": r.get("via") or "—"}
              for r in records]
    newest_cst = max((r["newest_cst"] for r in records if r.get("newest_cst")), default=None)
    lag_hours = None
    if newest_cst:
        try:
            lag_hours = max(0.0, round(
                (now - datetime.strptime(newest_cst, "%Y-%m-%d %H:%M")
                 .replace(tzinfo=CST)).total_seconds() / 3600.0, 1))
        except ValueError:
            lag_hours = None
    analysis = {"scanned": scanned, "ok_n": ok_n, "today_n": today_n,
                "newest": newest, "items_n": len(headlines), "merged": merged,
                "health": health, "newest_cst": newest_cst, "lag_hours": lag_hours}
    note = (f"只收录 {MAINLAND_NEWS_TOTAL} 家内地财经媒体公开信息源"
            "（官方订阅优先，无官方订阅的走站内检索 RSS）的标题、发布时间与原文链接（北京时间）；"
            "不做港股过滤，供新闻情绪因子 / 政策因子 / 策略研判共用标题池；"
            "媒体观点未经核实，不构成投资建议。")
    if missing:
        note += f" 暂缺（{len(missing)} 家）：" + "、".join(missing) + "。"

    if scanned == 0:
        reason = (f"近 {MAINLAND_NEWS_WINDOW_HOURS} 小时窗口内 {MAINLAND_NEWS_TOTAL} 家媒体"
                  "均未取得带可验证时区发布时间的公开标题（网络受限 / 检索平台限流）")
        print(f"  ⚠️ 内地财经媒体源头暂不可用：{reason}")
        return _source_result(MAINLAND_NEWS_SOURCE_NAME, "unavailable",
                              sources=records, headlines=[], analysis=analysis,
                              note=note, error=reason)

    print(f"  ✅ 内地财经媒体 {ok_n}/{MAINLAND_NEWS_TOTAL} 家窗口内有更新 · 扫描 {scanned} 条"
          f" · 进标题池 {len(headlines)} 条" + (f"（跨源同题合并 {merged} 条）" if merged else ""))
    if missing:
        print(f"  🕐 {len(missing)} 家暂缺：" + "、".join(missing))
    return _source_result(
        MAINLAND_NEWS_SOURCE_NAME, "success",
        is_today=today_n > 0, content_date=newest,
        sources=records, headlines=headlines, analysis=analysis, note=note,
        partial=bool(missing), error=None)


# ============================================================
# 【沸腾花蛤】情绪热点因子量化分析（2026-10-13 新增；2026-10-19 更名，原「内地财经热点榜」）
#   内地 18 家财经媒体的窗口内标题 → 按主题词表聚类成热点榜，并附每家的时效体检；
#   2026-10-19 起叠加本地「AI 分析」三件套（全部规则合成、只读标题）：
#     ⚖ 情绪总览（情绪词典折叠成偏多/中性/偏空 + 净情绪分）
#     🔥 热点聚合（跨媒体同题词汇簇，附情绪与风险标注；原「AI词汇分析」升级并入）
#     ⚠ 预警风险点（风险词表命中按类别聚合，等级 = 传播度：高/中/关注）
#   规则合成、确定性、可复现：同一批标题永远得到同一份榜；未命中的进「其他 / 未归类」，
#   绝不按热度猜、不复制正文、不给买卖建议。情绪分与风险等级是词典启发式，非校准概率。
#   更名口径与 2026-10-10「新闻情绪 → 新闻情绪因子量化分析」一致：
#   kicker（MAINLAND HOTLIST）、数据源键名、审计标签与环境变量 OCTOPUS_MAINLAND_HOTLIST 均不变。
# ============================================================
SECTION_TITLE_MAINLAND_HOTLIST = "【沸腾花蛤】情绪热点因子量化分析"
MAINLAND_HOTLIST_ENABLED = _env_flag("OCTOPUS_MAINLAND_HOTLIST", True)
MAINLAND_HOTLIST_THEME_MAX = 8          # 全量版最多列几个主题（按条数降序）
MAINLAND_HOTLIST_THEME_MAX_PLAIN = 5    # 入门版
MAINLAND_HOTLIST_ITEMS_PER_THEME = 3    # 每个主题列几条代表标题
MAINLAND_HOTLIST_ITEMS_PER_THEME_PLAIN = 1
MAINLAND_HOTLIST_VOCAB_MAX = 8          # 热点聚合：全量版展示前八个词汇簇
MAINLAND_HOTLIST_VOCAB_MAX_PLAIN = 5    # 入门版压缩展示
MAINLAND_HOTLIST_RISK_MAX = 5           # 预警风险点：全量版最多列几类
MAINLAND_HOTLIST_RISK_MAX_PLAIN = 3     # 入门版
MAINLAND_HOT_OTHER_LABEL = "其他 / 未归类"

# 主题词表：**按顺序**命中第一个就算归类（一词多家命中不重复计数）。
# 纯 ASCII 关键词走大小写敏感匹配（避免 AI 命中 said / chain 之类），中文走子串匹配。
MAINLAND_HOT_THEMES = (
    ("政策与监管", ("政策", "监管", "证监会", "央行", "国常会", "发改委", "财政部", "税务总局",
                  "工信部", "商务部", "金融监管总局", "新规", "征求意见", "管理办法", "条例",
                  "座谈会", "约谈", "处罚", "立案", "调查", "反垄断", "反内卷", "降准", "降息",
                  "退税", "补贴", "以旧换新", "试点", "整治", "合规", "问询", "自律")),
    ("宏观与数据", ("GDP", "CPI", "PPI", "PMI", "通胀", "进出口", "外贸", "社融", "信贷", "M2",
                  "经济", "增长", "失业", "人口", "统计局", "IMF", "世界银行", "诺贝尔",
                  "制造业", "景气", "逆回购", "公开市场")),
    ("A股盘面", ("A股", "沪指", "上证", "深成", "创业板", "科创", "北交所", "两市", "涨停", "跌停",
                "板块", "概念", "大盘", "收盘", "开盘", "午评", "收评", "主力", "北向", "沪深",
                "定增", "回购", "IPO", "新股", "退市", "个股", "异动", "成交额", "注册制")),
    ("港股与外围", ("港股", "恒生", "恒指", "恒科", "H股", "美股", "纳指", "道指", "标普", "日股",
                  "韩股", "欧股", "隔夜", "中概", "金龙指数", "KOSPI", "日经", "牛熊证")),
    ("半导体与算力", ("芯片", "半导体", "晶圆", "存储", "算力", "GPU", "CPU", "光刻", "封装",
                    "AI", "人工智能", "大模型", "数据中心", "光模块", "CPO", "PCB", "覆铜板",
                    "电子布", "服务器", "机器人", "具身智能", "液冷", "智能眼镜")),
    ("新能源与汽车", ("新能源", "汽车", "车企", "电动", "电池", "锂", "光伏", "硅料", "储能",
                    "充电", "智驾", "车展", "特斯拉", "比亚迪", "固态电池", "整车", "产销",
                    "轨道交通")),
    ("消费与医药", ("消费", "白酒", "食品", "饮料", "零售", "餐饮", "旅游", "免税", "医药",
                  "创新药", "医疗", "集采", "生物", "医美", "短剧", "潮玩", "宠物")),
    ("大宗与商品", ("黄金", "原油", "油价", "铜", "铝", "铁矿", "煤炭", "稀土", "商品", "期货",
                  "大宗", "天然气", "金价", "钢材")),
    ("地产与金融", ("地产", "房地产", "楼市", "房贷", "银行", "保险", "券商", "基金", "公募",
                  "私募", "信托", "理财", "存款", "利率", "LPR", "汇率", "贷款", "分红",
                  "金融街论坛")),
    ("公司动态", ("业绩", "预告", "净利", "增持", "减持", "收购", "并购", "重组", "中标", "订单",
                "公告", "分拆", "高管", "股权", "股东", "融资", "扩产", "投产", "涨价", "回应",
                "诉讼", "重整")),
)


def _mainland_theme_hit(keywords, title):
    """标题是否命中某主题（中文子串 / ASCII 大小写敏感）。"""
    text = str(title or "")
    up = text.upper()
    for kw in keywords:
        if kw.isascii():
            if kw.upper() in up:
                return True
        elif kw in text:
            return True
    return False


def build_mainland_hotlist(mainland, news_corpus=None, date_str=None):
    """内地财经媒体标题池 → 情绪热点因子量化分析（规则合成，确定性）。

    返回 None 表示该源头不可用 / 窗口内 0 条（栏目整栏缺席，不占位）。
    每条标题只归一个主题（按 MAINLAND_HOT_THEMES 的顺序命中第一个），
    因此各主题条数之和恒等于进榜总条数——榜单里不会出现「加起来对不上」。

    标题只读、不取正文；本地 jieba + 停用词表提取词汇，并按标题数 / 媒体数汇总。
    2026-10-19 起追加本地「AI 分析」（同样只读标题、规则合成）：
      sentiment_agg  = 情绪总览（偏多/中性/偏空 + 净情绪分）
      hotspots       = 热点聚合（跨媒体同题词汇簇 + 情绪/风险标注）
      risk_report    = 预警风险点（风险词表命中类别 + 传播度等级）
      每个主题桶另附 mood / pos_n / neu_n / neg_n / avg_score（主题级情绪折叠）。
    2026-10-20 起追加「平时也有功能」的每日风险分析（同一份词表，不新增取数口径）：
      risk_trend     = 预警趋势（news_history.json 存档近 7 个自然日逐日重算，
                       与最近存档日对比：新增 / 升级 / 持续 / 降级 / 解除；
                       存档缺失时 None，渲染层整行不出，不硬造变化）
      risk_posture   = 今日风险态势（零命中 / 低等级的平时日子也给出一行
                       确定性分析结论，只组合同源数字，不造方向或概率）
    分析结果不请求外部大模型；情绪分与风险等级是词典启发式，不产生校准的涨跌概率。
    """
    if not isinstance(mainland, dict) or mainland.get("status") != "success":
        return None
    # 复制条目后再附分析结果，避免渲染阶段改写采集层的原始标题池。
    headlines = [dict(h) for h in (mainland.get("headlines") or []) if isinstance(h, dict)]
    headlines = [h for h in headlines if str(h.get("title") or "").strip()
                 and str(h.get("url") or "").strip()]
    if not headlines:
        return None

    # 词汇提示只分析标题（抓取池本身不含正文）；覆盖旧缓存，避免任何来源的正文词条混入。
    for headline in headlines:
        title = headline.get("title", "")
        existing = headline.get("finance_analysis")
        if isinstance(existing, dict):
            existing = dict(existing)
        else:
            existing = _finance.analyze_finance_item(title, "")
        existing["vocabulary_terms"] = _finance.extract_finance_vocabulary(title)
        headline["finance_analysis"] = existing

    def _sort_key(h):
        return str(h.get("published_cst") or "")

    buckets, used = [], set()
    for order, (label, keywords) in enumerate(MAINLAND_HOT_THEMES):
        # 已归类过的不再参与后面的主题（保证「一条只算一次」）：少了这一步，
        # 一条同时命中两个词的标题会被数两次，各主题条数之和就会大于进榜总数。
        hits = [h for h in headlines
                if id(h) not in used and _mainland_theme_hit(keywords, h.get("title"))]
        if not hits:
            continue
        for h in hits:
            used.add(id(h))
        media = sorted({str(h.get("source") or "") for h in hits if h.get("source")})
        buckets.append({"label": label, "order": order, "count": len(hits),
                        "media": media, "media_n": len(media),
                        "items": sorted(hits, key=_sort_key, reverse=True),
                        "today_n": sum(1 for h in hits if h.get("is_today"))})
    rest = [h for h in headlines if id(h) not in used]
    if rest:
        media = sorted({str(h.get("source") or "") for h in rest if h.get("source")})
        buckets.append({"label": MAINLAND_HOT_OTHER_LABEL, "order": len(MAINLAND_HOT_THEMES),
                        "count": len(rest), "media": media, "media_n": len(media),
                        "items": sorted(rest, key=_sort_key, reverse=True),
                        "today_n": sum(1 for h in rest if h.get("is_today"))})
    if not buckets:
        return None
    buckets.sort(key=lambda b: (-b["count"], b["order"]))
    # 主题级情绪折叠（2026-10-19 新增）：桶内标题逐条过本地情绪词典，
    # 得到 偏多/中性/偏空 计数与净情绪分——只描述「这批标题的措辞倾向」。
    for b in buckets:
        mix = _finance.aggregate_titles_mood([h.get("title") for h in b["items"]])
        b["pos_n"], b["neu_n"], b["neg_n"] = mix["pos_n"], mix["neu_n"], mix["neg_n"]
        b["avg_score"], b["mood"] = mix["avg_score"], mix["label"]
    analysis = mainland.get("analysis") or {}
    health = [h for h in (analysis.get("health") or []) if isinstance(h, dict)]
    # 时效体检汇总：当天 / 窗口内滞后 / 暂缺 各几家（入门版也显示，压缩成一行）
    today_src = [h for h in health if h.get("state") == "当天"]
    lag_src = [h for h in health if h.get("state") == "窗口内滞后"]
    
    # 💰 新增：计算整体财经分析统计
    finance_summary = _calculate_finance_summary(headlines)
    # ⚖🔥⚠ 2026-10-19 新增：情绪总览 / 热点聚合 / 预警风险点（全部本地词表，确定性）。
    sentiment_agg = _finance.aggregate_hotlist_sentiment(headlines)
    hotspots = _finance.aggregate_hotlist_hotspots(headlines, top_n=MAINLAND_HOTLIST_VOCAB_MAX)
    risk_report = _finance.analyze_hotlist_risks(headlines, top_n=MAINLAND_HOTLIST_RISK_MAX)
    # 🔭 2026-10-20 新增：逐日预警趋势 + 今日风险态势（「平时也有功能」的每日风险分析）。
    #    趋势用同一份风险词表对存档里同一段「内地财经媒体」标题按自然日重算近 7 日画像，
    #    与最近存档日对比；存档缺失 / 参数缺省时 risk_trend=None，渲染层整行不出，不硬造变化。
    risk_trend = _hotlist_risk_trend(news_corpus, date_str)
    risk_posture = _finance.risk_posture(risk_report, sentiment_agg, risk_trend)
    
    return {
        # status / is_today 是为了让「🦑 AI帮你提鲜」的活鲜度判断与其他栏目同口径
        # （octopus_ren._garnish_available 读 status，读不到就当缺席，不加解读块）。
        "status": "success",
        "today_sources": len(today_src),
        "lag_sources": len(lag_src),
        "themes": buckets,
        "total": len(headlines),
        "theme_n": len(buckets),
        "max_count": max(b["count"] for b in buckets),
        "ok_n": int(analysis.get("ok_n") or 0),
        "total_sources": MAINLAND_NEWS_TOTAL,
        "scanned": int(analysis.get("scanned") or 0),
        "merged": int(analysis.get("merged") or 0),
        "newest_cst": analysis.get("newest_cst"),
        "lag_hours": analysis.get("lag_hours"),
        "today_n": int(analysis.get("today_n") or 0),
        "health": health,
        "missing": [h.get("name") for h in health if h.get("status") != "ok"],
        "is_today": bool(mainland.get("is_today")),
        # 💰 新增：财经分析统计
        "finance_summary": finance_summary,
        # ⚖🔥⚠ 2026-10-19 新增：情绪总览 / 热点聚合 / 预警风险点
        "sentiment_agg": sentiment_agg,
        "hotspots": hotspots,
        "risk_report": risk_report,
        # 🔭 2026-10-20 新增：预警趋势 / 今日风险态势（「平时也有功能」的每日风险分析）
        "risk_trend": risk_trend,
        "risk_posture": risk_posture,
    }


def _calculate_finance_summary(headlines: List[Dict]) -> Dict:
    """生成热点标题的本地词汇统计；单位为标题数 / 媒体数，不伪装成概率。"""
    return _finance.summarize_hotlist_vocabulary(headlines)


def _hotlist_risk_trend(news_corpus, date_str):
    """存档语料 → 近 7 日逐日预警趋势；参数缺失 / 冷启动返回 None（渲染层不出趋势行）。

    只认 section=MAINLAND_NEWS_SECTION 的条目（与热点榜同一批 18 家媒体标题——
    main() 每次运行把本次抓取并进 news_history.json 的同一份存档）；按 date 字段
    分日切片（标题级时间截断到日，无时间戳的条目按采集日兜底——与政策因子用
    存档同一口径）。date_str（YYYYMMDD）解析不出 → None，不猜今天。
    """
    if not isinstance(news_corpus, (list, tuple)) or not news_corpus:
        return None
    try:
        today_iso = datetime.strptime(str(date_str), "%Y%m%d").date().isoformat()
    except (TypeError, ValueError):
        return None
    items_by_day = {}
    for item in news_corpus:
        if not isinstance(item, dict):
            continue
        if str(item.get("section") or "") != MAINLAND_NEWS_SECTION:
            continue
        day = str(item.get("date") or "")
        if not day or not str(item.get("title") or "").strip():
            continue
        items_by_day.setdefault(day, []).append(
            {"title": item.get("title"), "source": item.get("source")})
    if not items_by_day:
        return None
    return _finance.analyze_risk_trend(items_by_day, today_iso,
                                       days=_finance.RISK_TREND_DAYS)


def _mainland_hotlist_block(res, kit):
    """情绪热点因子正文：情绪总览 + 源头时效体检行 + 主题榜 + 热点聚合 + 预警风险点
    + 预警趋势 + 今日风险态势。

    2026-10-19 升级（原「内地财经热点榜」版式）：主题榜每行附情绪折叠；
    原「AI词汇分析」升级为「🔥 热点聚合」（同一份词表与计数，附情绪 / 风险 / 同题聚合标记）；
    新增「⚠ 预警风险点」（风险词表命中按类别聚合，等级 = 传播度）。
    2026-10-20 新增「平时也有功能」的每日风险分析：「🔭 预警趋势」（存档近 7 日
    逐日重算，与最近存档日对比：新增 / 升级 / 持续 / 降级 / 解除；缺存档整行不出）
    与「⚠ 今日风险态势」（天天出，只组合同源定调与趋势对比，不造新数字）。
    所有分析都是本地词典启发式，页面上如实标注，不伪装成校准概率。
    """
    if not res or not res.get("themes"):
        return ""
    rows = []
    newest = str(res.get("newest_cst") or "")
    lag = res.get("lag_hours")
    head_bits = [f'<b>内地财经媒体 ×{res["total_sources"]}</b>',
                 f'{res["ok_n"]} 家窗口内有更新',
                 f'进榜 {res["total"]} 条']
    if newest:
        head_bits.append(f'最新 {_esc(newest[5:])}')
        if lag is not None:
            head_bits.append(f'滞后 {lag:g} 小时')
    head_bits.append(f'今日 {res["today_n"]} 条')
    rows.append(kit.item_row("", " · ".join(head_bits) + " " + kit.source_badge(
        {"status": "success", "is_today": res.get("is_today")}), ""))
    # ⚖ 情绪总览（2026-10-19 新增）：偏多/中性/偏空 条数 + 净情绪分 + 风险词命中数。
    agg = res.get("sentiment_agg") or {}
    if agg.get("has_data"):
        avg = agg.get("avg_score")
        left = (f'<b>情绪总览</b> 偏多 {int(agg.get("pos_n") or 0)} 条 · '
                f'中性 {int(agg.get("neu_n") or 0)} 条 · 偏空 {int(agg.get("neg_n") or 0)} 条'
                + (f' ｜ 净情绪分 {avg:+.2f}（{_esc(str(agg.get("label") or "—"))}）'
                   if avg is not None else ""))
        risk_hit = int((res.get("risk_report") or {}).get("hit_n") or 0)
        rows.append(kit.item_row(
            "⚖", left,
            _esc(f'风险词命中 {risk_hit}/{int(agg.get("total_titles") or 0)} 条 · '
                 f'{agg.get("method") or "本地情绪词典"}，非校准概率')))
    # 源头时效体检（非入门版）：每家「窗口内条数 + 最新时间（滞后小时）」压成一行，
    # 谁当天、谁滞后、谁暂缺一眼看全；入门版只报暂缺名单。
    if not PLAIN():
        cover = []
        for h in (res.get("health") or []):
            if h.get("status") != "ok":
                continue
            cell = f'{_esc(str(h.get("name") or ""))} {int(h.get("items") or 0)}'
            nw = str(h.get("newest_cst") or "")
            if nw:
                cell += f' · {_esc(nw[5:])}'
                if h.get("lag_hours") is not None:
                    cell += f'（滞后 {float(h["lag_hours"]):g}h）'
            cover.append(cell)
        if cover:
            rows.append(kit.item_row("▤", "<b>时效体检</b>（内地源头 · 窗口内条数 · 最新 / 滞后）",
                                     _esc(" ｜ ".join(cover))))
    else:
        # 入门版：逐家清单太长，压成一行「当天 / 滞后 / 暂缺 各几家」+ 最滞后的那家。
        bits = [f'当天 {res.get("today_sources", 0)} 家',
                f'窗口内滞后 {res.get("lag_sources", 0)} 家',
                f'暂缺 {len(res.get("missing") or [])} 家']
        worst = [h for h in (res.get("health") or [])
                 if h.get("status") == "ok" and h.get("lag_hours") is not None]
        if worst:
            w = max(worst, key=lambda h: float(h.get("lag_hours") or 0))
            bits.append(f'最滞后 {_esc(str(w.get("name") or ""))}'
                        f'（{float(w["lag_hours"]):g} 小时）')
        rows.append(kit.item_row("▤", "<b>时效体检</b>", _esc(" · ".join(bits))))
    if res.get("missing"):
        rows.append(kit.item_row("🕐", "<b>暂缺</b>",
                                 _esc(f'{len(res["missing"])} 家：' + "、".join(res["missing"]))))
    theme_max = MAINLAND_HOTLIST_THEME_MAX_PLAIN if PLAIN() else MAINLAND_HOTLIST_THEME_MAX
    per_theme = (MAINLAND_HOTLIST_ITEMS_PER_THEME_PLAIN if PLAIN()
                 else MAINLAND_HOTLIST_ITEMS_PER_THEME)
    shown_themes = res["themes"][:theme_max]
    shown_urls = set()      # 已渲染过的原文链接：预警风险点证据行不再重复同一条原文
    for i, b in enumerate(shown_themes, 1):
        pct = (b["count"] / res["total"] * 100) if res["total"] else 0.0
        left = (f'<b>{_esc(b["label"])}</b> {kit.meter(b["count"], res["max_count"])}'
                f' <span style="font-size:11px;">{b["count"]} 条 · {pct:.0f}%</span>')
        # 主题级情绪折叠（2026-10-19 新增）：入门版只给定调，全量版附三档计数。
        right_bits = [f'{b["media_n"]} 家' +
                      (f' · {"、".join(b["media"][:3])}'
                       + (" 等" if b["media_n"] > 3 else "") if b["media"] else "")]
        if b.get("mood"):
            right_bits.append(f'情绪{b["mood"]}' if PLAIN() else
                              f'情绪{b["mood"]}（多{b.get("pos_n", 0)}/中{b.get("neu_n", 0)}'
                              f'/空{b.get("neg_n", 0)}）')
        rows.append(kit.item_row(f"{i:02d}", left, _esc(" · ".join(right_bits))))
        for it in b["items"][:per_theme]:
            url = str(it.get("url") or "")
            if url:
                shown_urls.add(url)
            title = _public_text(it.get("title"), 120)
            link = (f'<a href="{_esc(url)}" style="color:{kit.ok_color}">{_esc(title)}</a>'
                    if url else _esc(title))
            stamp = str(it.get("published_cst") or "")
            bits = [str(it.get("source") or "")]
            if stamp:
                bits.append(stamp[5:])
                bits.append("今日" if it.get("is_today") else "昨日及更早")
            
            # 标题级词汇提示；不展示未校准的「利好 / 利空概率」。
            fa = it.get("finance_analysis", {})
            terms = fa.get("vocabulary_terms") or [] if isinstance(fa, dict) else []
            if terms:
                domain_terms = [term for term in terms
                                if term in _finance.FINANCE_VOCABULARY_PRIORITY]
                display_terms = (domain_terms or terms)[:3]
                bits.append("词汇：" + "、".join(str(term) for term in display_terms))
            
            rows.append(kit.item_row("↳", link, _esc(" · ".join(x for x in bits if x))))
    if len(res["themes"]) > theme_max:
        rows.append(kit.item_row("…", f'另有 {len(res["themes"]) - theme_max} 个主题未展开',
                                 _esc("按条数降序，完整的只在全量版（--full）显示")))
    
    # 🔥 热点聚合（2026-10-19 由「AI词汇分析」升级并入）：同一份 jieba 词频口径
    #    （标题级去重、提及该词的标题数 / 涉及媒体数，一个数字不加不减），每簇再附
    #    同题聚合标记、情绪折叠与风险类别；按词聚合，同一条标题可进多个热点簇。
    hotspots = res.get("hotspots") or {}
    clusters = [c for c in (hotspots.get("clusters") or []) if isinstance(c, dict)]
    if hotspots.get("has_data") and clusters:
        total_titles = int(hotspots.get("total_titles") or 0)
        agg_n = int(hotspots.get("aggregated_n") or 0)
        head_right = (_esc(f'扫描 {total_titles} 条标题 · 同题热点（≥2 条）{agg_n} 个')
                      if PLAIN() else
                      _esc(f'扫描 {total_titles} 条标题 · 标题级去重 · '
                           f'跨媒体同题（≥2 条）{agg_n} 个 · 不代表涨跌信号'))
        rows.append(kit.item_row(
            "🔥", f'<b>热点聚合</b> · {_esc(str(hotspots.get("method") or "jieba 本地分词"))}',
            head_right))
        cluster_limit = (MAINLAND_HOTLIST_VOCAB_MAX_PLAIN if PLAIN()
                         else MAINLAND_HOTLIST_VOCAB_MAX)
        cluster_max = max(1, max(int(c.get("title_count") or 0) for c in clusters))
        for i, c in enumerate(clusters[:cluster_limit], 1):
            count = int(c.get("title_count") or 0)
            media_n = int(c.get("media_count") or 0)
            coverage = (count / total_titles * 100) if total_titles else 0.0
            # 左列保持旧词汇榜同款计数尾（「N 条标题 · N 家媒体 · 覆盖 N%」），
            # 同题聚合 / 情绪 / 风险标注挪进右列与媒体名单同排——右列自带每行的区分信息，
            # 避免两行左列计数尾逐字相同（tools/report_outline.py 的栏内重复口径）。
            term_text = (f'<b>{_esc(str(c.get("term") or ""))}</b> '
                         f'{kit.meter(count, cluster_max)} '
                         f'<span style="font-size:11px;">{count} 条标题 · {media_n} 家媒体 · 覆盖 {coverage:.0f}%</span>')
            tag_bits = []
            if c.get("aggregated"):
                tag_bits.append("同题聚合")
            if c.get("label"):
                tag_bits.append(f'情绪{c["label"]}')
            risk_cats = [str(x) for x in (c.get("risk_categories") or []) if x]
            if risk_cats and not PLAIN():
                tag_bits.append("⚠" + "、".join(risk_cats[:2]))
            media_list = [str(m) for m in (c.get("media") or []) if m]
            if media_list:
                tag_bits.append("、".join(media_list[:3]) + (" 等" if media_n > 3 else ""))
            rows.append(kit.item_row(f"{i:02d}", term_text, _esc(" · ".join(tag_bits))))
        if len(clusters) > cluster_limit:
            rows.append(kit.item_row(
                "…", f'另有 {len(clusters) - cluster_limit} 个热点词汇未展开',
                _esc("入门版压缩展示；全量版只列前八项")
            ))
    
    # ⚠ 预警风险点（2026-10-19 新增）：风险词表命中的标题按类别聚合，等级 = 传播度
    #    （高 / 中 / 关注，只看几条几家在说，不预测发生概率）；证据标题带可点原文，
    #    与主题榜已展示过的同一条原文不重复出现（栏内同一原文只列一次）。
    risk = res.get("risk_report") or {}
    if int(risk.get("total_titles") or 0):
        points = [p for p in (risk.get("points") or []) if isinstance(p, dict)]
        risk_limit = MAINLAND_HOTLIST_RISK_MAX_PLAIN if PLAIN() else MAINLAND_HOTLIST_RISK_MAX
        if points:
            head_right = (_esc(f'{int(risk.get("hit_n") or 0)}/'
                               f'{int(risk.get("total_titles") or 0)} 条标题命中 · '
                               f'聚成 {int(risk.get("points_total") or len(points))} 类')
                          if PLAIN() else
                          _esc(f'{int(risk.get("hit_n") or 0)}/'
                               f'{int(risk.get("total_titles") or 0)} 条标题命中 · '
                               f'聚成 {int(risk.get("points_total") or len(points))} 类 · '
                               f'等级是传播度（{risk.get("level_rule") or "高/中/关注"}），不是发生概率'))
            rows.append(kit.item_row(
                "⚠", f'<b>预警风险点</b> · {_esc(str(risk.get("method") or "本地风险词表"))}',
                head_right))
            for i, p in enumerate(points[:risk_limit], 1):
                level = str(p.get("level") or "")
                lv_color = (kit.bad_color if level == "高"
                            else kit.warn_color if level == "中" else "")
                lv_html = (f'<b style="color:{lv_color};">【{_esc(level)}】</b>' if lv_color
                           else f'<b>【{_esc(level)}】</b>')
                kws = [str(k) for k in (p.get("keywords") or []) if k]
                left = (f'{lv_html} <b>{_esc(str(p.get("category") or ""))}</b> '
                        f'<span style="font-size:11px;">{int(p.get("count") or 0)} 条 · '
                        f'{int(p.get("media_n") or 0)} 家'
                        + (f' · 命中词：{_esc("、".join(kws[:4]))}' if kws else "")
                        + '</span>')
                media = [str(m) for m in (p.get("media") or []) if m]
                rows.append(kit.item_row(
                    f"{i:02d}", left,
                    # 右列带条数锚点：两个风险类别恰好同一批媒体时也不会逐字撞行
                    _esc(f'命中 {int(p.get("count") or 0)} 条：'
                         + "、".join(media[:3]) + (" 等" if len(media) > 3 else ""))
                    if media else ""))
                if not PLAIN():
                    for s in (p.get("samples") or [])[:2]:
                        if not isinstance(s, dict):
                            continue
                        url = str(s.get("url") or "")
                        if url and url in shown_urls:
                            continue            # 主题榜已展示过同一条原文，不再重复
                        title = _public_text(s.get("title"), 120)
                        link = (f'<a href="{_esc(url)}" style="color:{kit.ok_color}">{_esc(title)}</a>'
                                if url else _esc(title))
                        bits = [str(s.get("source") or "")]
                        stamp = str(s.get("published_cst") or "")
                        if stamp:
                            bits.append(stamp[5:])
                        matched = [str(w) for w in (s.get("matched") or []) if w]
                        if matched:
                            bits.append("命中：" + "、".join(matched))
                        rows.append(kit.item_row("↳", link, _esc(" · ".join(x for x in bits if x))))
                        if url:
                            shown_urls.add(url)
            if len(points) > risk_limit:
                rows.append(kit.item_row(
                    "…", f'另有 {len(points) - risk_limit} 类风险点未展开',
                    _esc("入门版压缩展示；全量版只列前五类")))
        else:
            # 0 命中日：头行照旧如实披露「未命中」（下方态势行只讲定调与趋势，不重复披露）。
            rows.append(kit.item_row(
                "⚠", "<b>预警风险点</b>",
                _esc(f'窗口内 {int(risk.get("total_titles") or 0)} 条标题未命中风险词表'
                     f'（词表启发式，未命中 ≠ 没有风险）')))
        # 🔭⚠ 2026-10-20 新增：预警趋势 + 今日风险态势（「平时也有功能」的每日风险分析）。
        #    趋势行只在有历史对比时出（不硬造变化）；态势行天天出——「命中 / 未命中」
        #    之后附一句情绪面定调与按日趋势对比的确定性分析结论（只组合同源数字，不造新数）。
        trend = res.get("risk_trend") or {}
        if trend.get("has_history"):
            days = [d for d in (trend.get("days") or []) if isinstance(d, dict)]
            spark = "·".join(str(int(d.get("hit_n") or 0)) for d in days)
            span = ""
            if days:
                span = (f'{str(days[0].get("date") or "")[5:]}'
                        f'→{str(days[-1].get("date") or "")[5:]}')
            if PLAIN():
                left = "<b>预警趋势</b>"
                right = _esc(str(trend.get("trend_phrase") or "")
                             + ("（样本尚少，仅作提示）" if trend.get("low_sample") else ""))
            else:
                left = f'<b>预警趋势</b> · {_esc(str(trend.get("method") or ""))}'
                change_bits = []
                for c in (trend.get("changes") or []):
                    if not isinstance(c, dict):
                        continue
                    status = str(c.get("status") or "")
                    cat = str(c.get("category") or "")
                    lv = str(c.get("level") or "")
                    blv = str(c.get("baseline_level") or "")
                    if status in ("新增", "持续"):
                        change_bits.append(f"{status}【{lv}】{cat}")
                    elif status in ("升级", "降级"):
                        change_bits.append(f"{status}【{blv}→{lv}】{cat}")
                    else:                                   # 解除
                        change_bits.append(f"解除 {cat}（前日【{blv}】）")
                head = f"逐日命中 {spark}" + (f"（{span}）" if span else "")
                right = _esc(head + " · "
                             + (" · ".join(change_bits) if change_bits else "无类别变化")
                             + (f' · 今日存档 {int(trend.get("today_n") or 0)} 条样本尚少，对比仅作提示'
                                if trend.get("low_sample") else ""))
            rows.append(kit.item_row("🔭", left, right))
        posture = res.get("risk_posture") or {}
        if posture.get("has_data"):
            rows.append(kit.item_row(
                "⚠", "<b>今日风险态势</b>",
                _esc(str(posture.get("plain_text") if PLAIN() else posture.get("text") or ""))))

    return kit.rows("".join(rows)) if rows else ""


# ============================================================
# 数据采集主函数
# ============================================================
def fetch_hk_quant():
    """数据源 7：港股量化引擎（概率预测 + 资金流动性 + 推进式校验）。

    跑通整条量化流水线：Yahoo 港股指數/个股日线 → 五因子 → 历史滚动重算 →
    分桶+保序+逻辑回归校准 → 推进式回测 → 沪深港通/成交/深度的流动性画像 →
    预测留痕。任一环节取不到数据就按「暂缺」降级，绝不用历史数字冒充实时。
    """
    print("📡 正在运行港股量化引擎（恒指/恒科日线 · 港股蓝筹 · 沪深港通 · 港股成交）...")
    if not HK_QUANT_ENABLED:
        print("  ⏭ 量化引擎已关闭（OCTOPUS_QUANT=0 / --no-quant）")
        return _source_result("港股量化引擎", "unavailable", result=None,
                              error="本次运行已关闭量化引擎")
    try:
        res = _quant.run_quant(
            safe_request,
            history_path=os.path.join(REPORT_DIR, QUANT_HISTORY_FILENAME),
            enable_stocks=HK_QUANT_STOCKS)
    except Exception as exc:                       # 引擎异常不影响日报其它栏目
        print(f"  ⚠️ 量化引擎异常：{exc}")
        return _source_result("港股量化引擎", "unavailable", result=None, error=str(exc))

    if not res.get("available"):
        print(f"  ⚠️ 量化引擎暂不可用：{res.get('reason')}")
        return _source_result("港股量化引擎", "unavailable", result=None,
                              error=str(res.get("reason") or "样本不足"))

    head = res.get("headline") or {}
    if head.get("available"):
        print(f"  ✅ 量化分析：{head['text']}")
    liq = res.get("liquidity") or {}
    if liq.get("score") is not None:
        print(f"  ✅ 流动性综合分 {liq['score']:.0f}/100（{liq['label']}）")

    # 量化分析的 is_today 判定：as_of 是上一个交易日收盘，运行在开盘前（09:00）时，
    # as_of == 昨天 是最新数据，应视为当天快照（snapshot），否则当天检验会永远不通过。
    # 这里用「4 天内都算新鲜」口径（周一跑，周五收盘滞后 3 天仍算新鲜），并配合引擎内部的回退检测。
    as_of = res.get("as_of")
    is_today = False
    try:
        if as_of:
            from datetime import datetime as _dt
            d_asof = _dt.strptime(as_of, "%Y-%m-%d").date()
            d_today = datetime.now(CST).date()
            lag = (d_today - d_asof).days
            # 4 天内算新鲜，且 as_of 必须 >= 历史最大 - 1（防止回退已在引擎层拦截）
            is_today = 0 <= lag <= 4
    except Exception:
        is_today = False

    return _source_result("港股量化引擎", "success",
                          is_today=is_today,
                          content_date=as_of,
                          result=res,
                          snapshot=True)


# ============================================================
# 策略研判 · MACD 日线策略（不另外增加正文栏目）
# ============================================================
def fetch_macd_strategy(data=None):
    """只在采集阶段取数；渲染 / build_daily_quant_strategy 不读库、不联网。"""
    if not MACD_ENABLED or not AI_ANALYSIS_ENABLED:
        return None                   # 关闭时不出正文，也不加入数据审计
    print("📡 正在计算 MACD 量化策略（市场库 → 已有日线 → Yahoo/东财免费源）...")
    quant_src = (data or {}).get("港股量化") or {}
    quant_res = quant_src.get("result") or {}
    existing = {}
    for row in list(quant_res.get("indices") or []) + list(quant_res.get("stocks") or []):
        if isinstance(row, dict) and row.get("code") and row.get("bars"):
            existing[row["code"]] = row["bars"]
    try:
        result = _quant.macd_strategy.run_macd(safe_request, existing=existing,
                                               include_bars=UZI_TREND_ENABLED)
    except Exception as exc:
        print(f"  ⚠️ MACD 策略异常：{type(exc).__name__}")
        return _source_result(MACD_SOURCE_NAME, "unavailable", result=None,
                              error=f"MACD 策略异常（{type(exc).__name__}）")
    if not result.get("available"):
        print(f"  ⚠️ MACD 策略暂不可用：{result.get('reason')}")
        return _source_result(MACD_SOURCE_NAME, "unavailable", result=result,
                              error=result.get("reason") or "日线样本不足")
    # 将真实命中的主备路由写进本次备用源审计；已有日线复用不虚构网络命中。
    for row in result["items"]:
        weekly = (row.get("derived") or {}).get("timeframe") or {}
        urls = [row.get("source_url"), weekly.get("source_url")]
        for url in dict.fromkeys(u for u in urls if u):
            if "eastmoney.com" in url:
                em_primary = _backup.DATA_LINES["yahoo_bars"]["backups"][1][1]
                _note_backup_served("yahoo_bars", em_primary, symbol=row["code"])
                _note_backup_served("em_kline", url)
            else:
                _note_backup_served("yahoo_bars", url, symbol=row["code"])
    cover = result["coverage"]
    print(f"  ✅ MACD：{cover['valid']}/{cover['total']} 只 · 收盘日 "
          f"{result['as_of']} ~ {result['latest_as_of']} · 金叉 {result['golden_n']} / 死叉 {result['death_n']}")
    # 已有库 / 已有日线不因今天计算过而冒充当天行情；不使用 snapshot 绕过日期检查。
    today = datetime.now(CST).strftime("%Y-%m-%d")
    source = _source_result(MACD_SOURCE_NAME, "success", result=result,
                            content_date=result["as_of"],
                            is_today=any(row["as_of"] == today for row in result["items"]))
    if UZI_TREND_ENABLED:
        # 私有键：本次选中的日线交给 fetch_uzi_trend()（同一批数据、同一次取数），
        # 由调用方弹出后立刻丢弃，不写进日报 / JSON 留痕。
        source["_bars_by_code"] = result.pop("bars_by_code", {})
    return source


# ============================================================
# 【游资剑鱼】多专家流派趋势分析（独立栏目，2026-10-11 新增）
# ------------------------------------------------------------
# 方法：vendored 的 UZI-Skill 规则引擎（tools/UZI-Skill，MIT）——Weinstein 四阶段 /
#       均线多头排列等指标按上游同式本地重算，打分直接调上游 evaluate()，不重写规则。
# 数据：bars_by_code 来自 fetch_macd_strategy() 取好的同一批已收盘日线（同来源、同复权口径），
#       本栏目零新增联网；MACD 关闭 / 日线不可用 → 整栏缺席。
# ============================================================
def fetch_uzi_trend(data=None, bars_by_code=None):
    """规则引擎缺席或没有可用日线时返回 unavailable（栏目自然缺席，不占位、不编数字）。"""
    if not UZI_TREND_ENABLED:
        return None                    # 关闭时不写 data 键：栏目与审计都不出现
    if not MACD_ENABLED or not AI_ANALYSIS_ENABLED:
        return _source_result(UZI_TREND_SOURCE_LABEL, "unavailable", result=None,
                              error="依赖 MACD 栏目的已收盘日线（该栏目已关闭）")
    bars_by_code = bars_by_code if bars_by_code is not None else \
        ((data or {}).get(MACD_SOURCE_NAME) or {}).pop("_bars_by_code", {})
    if not bars_by_code:
        return _source_result(UZI_TREND_SOURCE_LABEL, "unavailable", result=None,
                              error="MACD 栏目本次没有可用已收盘日线")
    print(f"📡 正在计算 多专家流派趋势分析（{len(bars_by_code)} 只标的 · "
          f"评委 {'/'.join(_uzi_trend.panel_ids() or []) or '未装载'}）...")
    try:
        result = _uzi_trend.run_trend(bars_by_code, now=datetime.now(CST))
    except Exception as exc:                     # 单栏失败绝不拖垮整份日报
        print(f"  ⚠️ UZI 趋势分析异常：{type(exc).__name__}")
        return _source_result(UZI_TREND_SOURCE_LABEL, "unavailable", result=None,
                              error=f"UZI 趋势分析异常（{type(exc).__name__}）")
    if not result.get("available"):
        print(f"  ⚠️ UZI 趋势分析栏目缺席：{result.get('reason')}")
        return _source_result(UZI_TREND_SOURCE_LABEL, "unavailable", result=result,
                              error=result.get("reason") or "日线样本不足")
    cover, panel = result["coverage"], result["panel"]
    tones = "、".join(f"{k}={v}" for k, v in (result.get("tones") or {}).items() if v)
    print(f"  ✅ UZI 趋势：{cover['valid']}/{cover['total']} 只 · 收盘日 "
          f"{result['as_of']}~{result['latest_as_of']} · {panel['investors']} 位评委 × "
          f"{result['rules_enabled']} 条规则 · 定调 {tones or '—'}"
          + (f" · 未取到 {','.join(row['label'] for row in result['missing'])}"
             if result.get("missing") else ""))
    today = datetime.now(CST).strftime("%Y-%m-%d")
    return _source_result(UZI_TREND_SOURCE_LABEL, "success", result=result,
                          content_date=result["latest_as_of"],
                          is_today=any(row["as_of"] == today for row in result["items"]))


# ============================================================
# 【滚滚翻车鱼】板块轮动量化策略
# ============================================================
def _sector_rotation_is_today(content_date, today=None):
    """近期交易日收盘可作为当前策略输入；日期缺失、未来或滞后超过 4 天均不算当天。"""
    try:
        as_of = datetime.strptime(str(content_date or "")[:10], "%Y-%m-%d").date()
        today = today or datetime.now(CST).date()
        if isinstance(today, datetime):
            today = today.date()
        lag = (today - as_of).days
        return 0 <= lag <= 4
    except (TypeError, ValueError):
        return False


def _sector_rotation_headlines(data):
    """整理已有公开标题；事件维度只接受可解析的原始内容日期，当天抓取标记不代替日期。"""
    records = []
    for key, label in (("全球头条", "全球头条"), ("东财快讯", "东方财富快讯"),
                       ("国家政策", "中国政府网")):
        source = (data or {}).get(key) or {}
        if source.get("status") != "success":
            continue
        for item in source.get("headlines") or []:
            if isinstance(item, str):
                item = {"title": item}
            if not isinstance(item, dict) or not str(item.get("title") or "").strip():
                continue
            records.append({
                "title": str(item.get("title") or ""),
                "source": str(item.get("source") or label),
                "published_cst": (item.get("published_cst") or item.get("time") or item.get("date")
                                   or item.get("published_at") or item.get("release_date")),
                "published": item.get("published"),
                "published_at": item.get("published_at"),
            })

    # 港股新闻源头已经只保留近 72 小时且带明确时区的标题，可补充主题事件证据。
    hk_news = (data or {}).get(HK_NEWS_SOURCE_NAME) or {}
    if hk_news.get("status") == "success":
        for source in hk_news.get("sources") or []:
            if not isinstance(source, dict) or source.get("status") != "ok":
                continue
            for item in source.get("items") or []:
                if not isinstance(item, dict):
                    continue
                records.append({
                    "title": str(item.get("title") or ""),
                    "source": str(source.get("name") or "港股新闻源头"),
                    "published_cst": item.get("published_cst"),
                })
    return records


def _sector_rotation_market_inputs(mapped_codes, data):
    """优先复用港股量化引擎已经抓到的 bars / 快照，缺项再按映射代码补取。"""
    wanted = set(mapped_codes or [])
    quant_src = (data or {}).get("港股量化") or {}
    quant_result = quant_src.get("result") or {}
    stock_data = {}
    for row in quant_result.get("stocks") or []:
        if not isinstance(row, dict):
            continue
        code = _sector_rotation.normalize_hk_code(row.get("code"))
        if code not in wanted:
            continue
        net_yi = row.get("main_net_yi")
        try:
            net = float(net_yi) * 1e8 if net_yi is not None else None
        except (TypeError, ValueError):
            net = None
        stock_data[code] = {
            "code": code,
            "name": row.get("label") or (_sector_rotation.HK_STOCKS.get(code) or {}).get("name"),
            "symbol": row.get("code"),
            "bars": row.get("bars") or [],
            "main_net": net,
            "main_pct": row.get("main_pct"),
            "amount": row.get("main_amount"),
            "pe_ttm": row.get("pe_ttm"),
            "pb": row.get("pb"),
            "quote_as_of": row.get("quote_as_of"),
        }

    # 日线仅补没有 61 根有效 bar 的映射股；不因单一数据源失败放弃其余维度。
    bar_specs = []
    for code in sorted(wanted):
        record = stock_data.get(code) or {}
        if len(record.get("bars") or []) >= 61:
            continue
        meta = _sector_rotation.HK_STOCKS.get(code)
        if meta:
            bar_specs.append((meta["name"], meta["symbol"]))
    if bar_specs:
        try:
            bars_by_symbol = _quant.providers.fetch_series_batch(
                safe_request, bar_specs, rng="1y", workers=6, timeout=12)
            for symbol, bars in (bars_by_symbol or {}).items():
                code = _sector_rotation.normalize_hk_code(symbol)
                record = stock_data.setdefault(code, {
                    "code": code,
                    "name": (_sector_rotation.HK_STOCKS.get(code) or {}).get("name", code),
                    "symbol": symbol,
                    "bars": [],
                })
                if len(bars or []) > len(record.get("bars") or []):
                    record["bars"] = bars
        except Exception as exc:
            print(f"  ⚠️ 板块轮动港股日线补取失败（保留可用快照）：{exc}")

    # 同一 ulist 快照同时带资金流、成交额、PE/PB；只请求缺少这两类输入的映射代码。
    quote_specs = []
    for code in sorted(wanted):
        record = stock_data.get(code) or {}
        net, amount = record.get("main_net"), record.get("amount")
        try:
            has_amount = amount is not None and float(amount) > 0
        except (TypeError, ValueError):
            has_amount = False
        has_flow = (record.get("main_pct") is not None or (net is not None and has_amount))
        has_valuation = record.get("pe_ttm") is not None or record.get("pb") is not None
        if has_flow and has_valuation:
            continue
        meta = _sector_rotation.HK_STOCKS.get(code)
        if meta:
            quote_specs.append((meta["name"], meta["symbol"]))
    if quote_specs:
        try:
            snapshots = _quant.providers.fetch_hk_fundflow(safe_request, quote_specs, timeout=12)
            for code, values in (snapshots or {}).items():
                code = _sector_rotation.normalize_hk_code(code)
                record = stock_data.setdefault(code, {
                    "code": code,
                    "name": (_sector_rotation.HK_STOCKS.get(code) or {}).get("name", code),
                    "bars": [],
                })
                for key in ("main_net", "main_pct", "amount", "pe_ttm", "pb", "quote_as_of"):
                    source_key = "as_of" if key == "quote_as_of" else key
                    if record.get(key) is None and values.get(source_key) is not None:
                        record[key] = values[source_key]
        except Exception as exc:
            print(f"  ⚠️ 板块轮动资金/估值快照不可用：{exc}")

    benchmark_bars = []
    primary = quant_result.get("primary") or {}
    if str(primary.get("code") or "").upper() == "^HSI":
        benchmark_bars = primary.get("bars") or []
    if not benchmark_bars:
        benchmark = next((row for row in (quant_result.get("indices") or [])
                          if str(row.get("code") or "").upper() == "^HSI"), None)
        if benchmark:
            benchmark_bars = benchmark.get("bars") or []
    if not benchmark_bars:
        try:
            benchmark_bars = _quant.providers.fetch_bars(safe_request, "^HSI", rng="1y", timeout=12)
        except Exception as exc:
            print(f"  ⚠️ 板块轮动恒指基准暂缺：{exc}")
    return stock_data, benchmark_bars


def fetch_sector_rotation(data=None):
    """采集 A 股概念库与映射港股输入，运行五维评分和三策略投票。

    概念名到港股证券的关联由 output/octopus_quant/sector_rotation.py 中的明确关键词表给出；
    不是官方跨市场成分关系。数据缺项保持缺失，总分与策略票按各自门槛降级。
    """
    source_label = "东方财富 A股概念库 + 港股日线/快照"
    if not SECTOR_ROTATION_ENABLED:
        return _source_result(source_label, "unavailable", result=None,
                              error="板块轮动已关闭（OCTOPUS_SECTOR_ROTATION=0）")
    print("📡 正在抓取 A股概念库并计算港股板块轮动（五维评分 + 三策略投票）...")
    try:
        catalog = _quant.providers.fetch_concept_boards(safe_request)
    except Exception as exc:
        catalog = {"items": [], "total": 0, "complete": False,
                   "served_urls": [], "errors": [str(exc)]}
    concepts = catalog.get("items") or []
    for url in catalog.get("served_urls") or []:
        _note_backup_served("em_clist", url)
    if not concepts:
        reason = "；".join((catalog.get("errors") or [])[:2]) or "东方财富概念板块接口未返回有效列表"
        print(f"  ⚠️ A股概念库暂不可用：{reason}")
        return _source_result(source_label, "unavailable", result={
            "concept_total": 0, "mapped_total": 0, "unmapped_total": 0,
            "items": [], "catalog_complete": False,
        }, error=reason)

    mapped_codes = _sector_rotation.mapped_stock_codes(concepts)
    stock_data, benchmark_bars = _sector_rotation_market_inputs(mapped_codes, data or {})
    result = _sector_rotation.build_rotation(
        concepts, stock_data=stock_data, benchmark_bars=benchmark_bars,
        headlines=_sector_rotation_headlines(data or {}),
        catalog_complete=bool(catalog.get("complete")), now=datetime.now(CST))
    result["catalog_reported_total"] = catalog.get("reported_total")
    result["catalog_served_urls"] = list(catalog.get("served_urls") or [])
    result["catalog_errors"] = list(catalog.get("errors") or [])
    result["source_names"] = ["东方财富 push2 概念列表（fs=m:90+t:3）",
                               "Yahoo Finance / 东方财富日线（映射港股与恒指）",
                               "东方财富 ulist 快照（主力净占比、成交额、PE/PB）",
                               "本次成功采集的全球头条、东财快讯、国家政策与港股新闻标题候选源（近 72 小时事件匹配）"]
    dates = result.get("data_dates") or {}
    content_date = dates.get("latest_seen")
    partial = bool(catalog.get("errors") or not catalog.get("complete")
                   or result.get("mapped_total", 0) == 0
                   or result.get("scored_total", 0) == 0)
    if result.get("mapped_total", 0) == 0:
        print(f"  ⚠️ 概念库 {len(concepts)} 项已取得，但本地关键词映射命中 0 项；不伪造港股关联")
    else:
        print(f"  ✅ 概念库 {len(concepts)} 项 · 关键词命中 {result['mapped_total']} 项 · "
              f"总分可用 {result['scored_total']} 项 · 港股行情样本 {result['coverage']['technical_symbols']}/"
              f"{result['coverage']['mapped_hk_symbols']}")
    return _source_result(
        source_label, "success", is_today=_sector_rotation_is_today(content_date),
        content_date=content_date, partial=partial, result=result,
        error="；".join((catalog.get("errors") or [])[:2]) or None)


# ============================================================
# 【巡游旗鱼】申万一级行业轮动（2026-10-04 移植 #84）
# ------------------------------------------------------------
# 与港股【滚滚翻车鱼】板块轮动（A股概念 → 港股观察篮子）的分工：
#   · 本条是 **A股自身** 的行业轮动——申万一级 31 个行业，周度胜率/赔率评分 + 月度纯多头组合；
#   · 股票池是固定表 octopus_quant.industry_rotation.SW_L1_SECTORS（801xxx ↔ 东财 BKxxxx），
#     主流程零 clist 调用（该大页列表在境外出口被 502 拒绝，且东财已改为三级混排）；
#   · 单行业在东财三主机都取不到日线时，逐行业走申万宏源官方指数发布接口兜底（不混源）；
#   · 可评分行业少于 max(5, 60%×31)=19 → 整栏缺席，并落盘诊断（news_history.json）。
# ============================================================
def fetch_industry_rotation():
    """独立 A股行业轮动数据源；失败不影响其它栏目。

    失败时把判死原因打到日志（日K 口径 / 覆盖 / 锚点日 / 评分 / 存档哪一环不过），
    并已由 industry_rotation 落盘诊断，便于隔日核查。
    """
    if not INDUSTRY_ROTATION_ENABLED:
        return _source_result(INDUSTRY_ROTATION_SOURCE_LABEL, "unavailable", result=None,
                              error="行业轮动已关闭（OCTOPUS_INDUSTRY_ROTATION=0）")
    print("📡 正在计算申万一级行业轮动（31 个行业 · 周度评分 + 月度纯多头组合）...")
    try:
        result = _industry_rotation.run(
            safe_request, state_path=os.path.join(REPORT_DIR, NEWS_HISTORY_FILENAME),
            now=datetime.now(CST))
    except Exception as exc:                     # 单栏失败绝不拖垮整份日报
        result = {"available": False, "reason": f"运行异常：{exc}", "diag": {}}
    if not result.get("available"):
        diag = result.get("diag") or {}
        detail = " · ".join(f"{k}={diag[k]}" for k in
                            ("universe", "fqt", "kline_series", "missing", "asof",
                             "scored", "required")
                            if diag.get(k) not in (None, [], {}))
        print(f"  ⚠️ 行业轮动栏目缺席：{result.get('reason')}"
              + (f"（{detail}）" if detail else ""))
        return _source_result(INDUSTRY_ROTATION_SOURCE_LABEL, "unavailable",
                              error=result.get("reason"), result=result)
    diag = result.get("diag") or {}
    sources = result.get("sources") or {}
    src_note = " / ".join(f"{k}={v}" for k, v in sorted(sources.items()))
    # 备用源命中登记（总结「数据覆盖」一行点名）：镜像 = 备用源1，申万官方 = 备用源2
    if diag.get("em_mirror"):
        _note_backup_served("sw_industry_index", _backup.candidates("sw_industry_index", sw_code="")[1][1])
    if diag.get("sw_fallback"):
        first_sw = next((sw for code, _n, sw in _industry_rotation.SW_L1_SECTORS
                         if code == diag["sw_fallback"][0]), "")
        _note_backup_served("sw_industry_index",
                            _backup.candidates("sw_industry_index", sw_code=first_sw)[2][1],
                            sw_code=first_sw)
    print(f"  ✅ 行业轮动：锚点 {result['asof']} · 有效 {result['scored_count']}/"
          f"{result['universe_count']} 个行业 · 月度持仓"
          f"{'沿用' if diag.get('state') == 'reused' else '新建'}"
          f"（复权口径 fqt={diag.get('fqt')}"
          + (f" · 日线来源 {src_note}" if src_note else "")
          + (f" · 未取到 {','.join(result['missing'])}" if result.get("missing") else "")
          + (f" · 名称漂移 {list(diag['renamed'])}" if diag.get("renamed") else "")
          + "）")
    return _source_result(INDUSTRY_ROTATION_SOURCE_LABEL, "success",
                          is_today=result["asof"] == _today_str(),
                          content_date=result["asof"], result=result)


# ============================================================
# 📊 策略大类量化（图中 4 大类 6 细分，2026-10-21 新增）
# ------------------------------------------------------------
# 对应图中：权益多头{主观多头/量化多头} / 纯债策略{纯债基金} /
#           CTA策略{主观CTA/量化CTA} / 套利策略{综合指数}
# 每个细分映射一个可验证基准指数，取近 1 年日线计算 5/20/60 日收益、
# 年化波动、夏普、最大回撤、胜率、MA 趋势与信号分；大类为细分均值。
# 取数失败用确定性合成兜底（不因行情暂缺整栏消失），内部衍生、
# 不新增联网口、不计入当天检验 / 总源数审计。
# ============================================================
def _index_page_enabled():
    """🔙 三地指数开关：2026-10-23 回滚为**纯港股日报**，默认关闭。

    关闭时（默认）：不联网采集 A股 / 美股 / 港股 9 指数、不写 ``index_checks`` 契约、
    全页不分流到 ``index_page``、【策略总览】也不出现三地指数表 —— 页面回到原港股口径
    （恒指七日预测 / 港股量化 / 个股与栏目照旧）。
    显式 ``OCTOPUS_INDEX_PAGE=1``（或 true / yes / on）才把三地指数全页开回来，代码与
    文档都保留，便于一键恢复。环境变量在**调用时**读取，测试与手工切换即时生效。
    """
    return os.environ.get("OCTOPUS_INDEX_PAGE", "0").strip().lower() in ("1", "true", "yes", "on")


def fetch_strategy_quant(date_str=None):
    """策略量化主入口：取数失败走合成兜底，始终可渲染（关闭时返回 None，栏目与审计都不出现）。"""
    if not STRATEGY_QUANT_ENABLED:
        return None
    if _strategy_quant is None:
        return _source_result(STRATEGY_QUANT_SOURCE, "unavailable", result=None,
                              error="strategy_quant 模块未加载")
    try:
        print("📡 正在计算策略大类量化（6 细分 · 4 大类 · 基准指数日线）...")
        ds = date_str or datetime.now(CST).strftime("%Y%m%d")
        res = _strategy_quant.run_strategy_quant(
            safe_request, date_str=ds, allow_synthetic=STRATEGY_QUANT_DEMO)
        # 三地指数单源采集（Yahoo 主源，失败自动切换备用源）：**默认不采集**。
        # 只有 OCTOPUS_INDEX_PAGE=1 才联网取 9 指数并写 index_checks 契约；关闭时
        # 快照里不出现该键，页面与【策略总览】都不会显示三地指数（回滚为纯港股日报）。
        if _index_page_enabled():
            import index_crosscheck
            res["index_checks"] = index_crosscheck.collect(safe_request)
            for row in res["index_checks"]:
                url = row.get("source_url")
                if url and row.get("is_backup"):
                    if "eastmoney.com" in url:
                        em_primary = _backup.DATA_LINES["yahoo_bars"]["backups"][1][1]
                        _note_backup_served("yahoo_bars", em_primary, symbol=row["symbol"])
                        _note_backup_served("em_kline", url)
                    else:
                        _note_backup_served("yahoo_bars", url, symbol=row["symbol"])
            if any(r.get("as_of") or r.get("date") or r.get("close") is not None for r in res["index_checks"]):
                res["available"] = True
        if not res.get("available"):
            print(f"  ⚠️ 策略量化暂不可用：{res.get('reason')}")
            return _source_result(STRATEGY_QUANT_SOURCE, "unavailable", result=res,
                                  error=str(res.get("reason") or "数据不足"))
        diag = res.get("diag") or {}
        syn_n = diag.get("synthetic_n", 0)
        print(f"  ✅ 策略量化：{len(res.get('strategies') or [])} 细分 · "
              f"{len(res.get('by_major') or [])} 大类 · {res.get('as_of')} 收盘"
              + (f" · 合成兜底 {syn_n} 项" if syn_n else ""))
        # 内部衍生：已收盘回看，不计入当天检验（snapshot），content_date 供页面显示。
        return _source_result(STRATEGY_QUANT_SOURCE, "success", result=res,
                              content_date=res.get("as_of"),
                              is_today=False, snapshot=True)
    except Exception as exc:
        print(f"  ⚠️ 策略量化异常：{type(exc).__name__}: {exc}")
        # 关闭三地指数时异常兜底也不写 index_checks（否则页面会被空的指数全页接管）。
        return _source_result(STRATEGY_QUANT_SOURCE, "unavailable",
                              result={"index_checks": []} if _index_page_enabled() else None,
                              error=f"策略量化异常（{type(exc).__name__}）")


# ============================================================
# 每周量化走势预测：未来 7 个交易日逐日表格（恒指升跌方向 / 概率 / 理由 / 分析 / AI 操作建议）
# ------------------------------------------------------------
# 方法来自 GitHub 无未来函数（look-ahead）量化工程实践调研：
#   · 输入闭合：只读本次抓取的日线快照（^HSI 2y 日线）；
#   · 目标日在严格之后：特征只用 ≤t 数据、相似样本标签必须已结算（s+5 ≤ t）、
#     运行时截断不变性自检（peekahead 式）不过则整栏降级；
#   · 先存档后结算：预测先落盘 output/weekly_forecast.json（settled=False），
#     满 5 个交易日再按真实收盘回填 hit / 实际涨跌（当次运行不可能结算当次预测）；
#   · 零写死叙事：不落任何具体日期/点位，规则合成，非投资建议。
# 数据取不到、样本不足或自检不过 → 整栏缺席，绝不用历史文案冒充预测。
# ============================================================
def _hk7_extra_context(data):
    """给「AI 七日港股走势分析概率」准备当日证据（只搬运本次已抓到的数据）。

    flows  —— 南向成交总额（A股大盘全景）+ 流动性综合分（港股量化引擎）；
    events —— 未来两周内 ★★★ 日程（财经日历，最多 6 条，含日期与名称）；
    news   —— 港股相关标题（全网新闻源头 → 港股名家频道 → 全球头条港股关键词命中）。
    任一来源缺失就不放进证据（绝不编造）；只做截断，不引入新数字。
    """
    extra = {"flows": {}, "global_quotes": {}, "events": [], "news": []}
    pan = (data or {}).get("A股大盘全景") or {}
    north = pan.get("north") or {}
    if north.get("south_available") and north.get("south_amount_yi") is not None:
        try:
            extra["flows"]["south_amount_yi"] = round(float(north["south_amount_yi"]), 2)
        except (TypeError, ValueError):
            pass
        if north.get("south_date"):
            extra["flows"]["south_date"] = str(north["south_date"])
    quant = ((data or {}).get("港股量化") or {}).get("result") or {}
    liq = quant.get("liq") or {}
    if liq.get("score") is not None:
        try:
            extra["flows"]["liquidity_score"] = round(float(liq["score"]), 1)
        except (TypeError, ValueError):
            pass

    # 美股隔夜行情（用于跨市场风险偏好联动 β 映射）
    market = (data or {}).get("实时行情") or {}
    quotes = market.get("quotes") or {}
    for name in ("标普500", "纳斯达克", "道琼斯指数"):
        q = quotes.get(name)
        if isinstance(q, dict) and q.get("change_pct") is not None:
            extra["global_quotes"][name] = {
                "change_pct": round(float(q["change_pct"]), 2),
                "as_of": str(q.get("as_of") or ""),
            }

    cal = (data or {}).get("财经日历") or {}
    if cal.get("status") == "success":
        base = datetime.now(CST).date()
        picked = []
        for it in cal.get("items") or []:
            day = _cal_date_obj(str(it.get("date") or ""))
            if not day or not (base <= day <= base + timedelta(days=14)):
                continue
            if int(it.get("imp") or 0) < 3:
                continue
            picked.append({"date": day.isoformat(), "name": str(it.get("name") or "")[:24]})
            if len(picked) >= 6:
                break
        extra["events"] = picked

    titles = []
    news_src = (data or {}).get(HK_NEWS_SOURCE_NAME) or {}
    for rec in news_src.get("sources") or []:
        for title in rec.get("hk_titles") or []:
            titles.append((str(title), str(rec.get("name") or "")))
    yt = (data or {}).get("港股名家频道") or {}
    for ch in yt.get("channels") or []:
        for v in (ch.get("videos") or [])[:1]:
            titles.append((str(v.get("title") or ""), str(ch.get("name") or "")))
    google = (data or {}).get("全球头条") or {}
    for h in google.get("headlines") or []:
        title = str((h or {}).get("title") or "") if isinstance(h, dict) else str(h)
        if title and _HK_NEWS_KW_RE.search(title):
            titles.append((title, "全球头条"))
    seen, picked = set(), []
    for title, source in titles:
        title = re.sub(r"\s+", " ", title).strip()
        if not title or title in seen:
            continue
        seen.add(title)
        picked.append({"title": title[:120], "source": source[:24] or "公开标题"})
        if len(picked) >= 12:
            break
    extra["news"] = picked
    return extra


def _hk7_jev_note(res):
    """Jev 端点状态一行（「数据覆盖」审计点名用，绝不静默；见 Jev 文档落地清单 P1）。

    覆盖四种状态：使用中（带模型名）/ 端点可用但本次未调用（大模型在用或数据不足）/
    探活或调用失败（带原因，已回退量化基准）/ 端点未配置。
    """
    jev = (res or {}).get("jev") or {}
    if jev.get("used"):
        return f"使用中（{jev.get('model') or '本地端点'}）"
    if not jev.get("enabled"):
        return "端点未配置（OCTOPUS_JEV_BASE_URL）"
    if not jev.get("tried"):
        return "端点可用，本次未调用（大模型在用）" if (res or {}).get("engine") == "llm" \
            else "端点可用，本次未调用"
    if not jev.get("ready"):
        return f"探活失败 → 回退量化基准（{jev.get('reason') or '端点不可达'}）"
    return f"调用失败 → 回退量化基准（{jev.get('reason') or '模型未返回可用概率'}）"


def fetch_hk_seven_day(data=None):
    """AI 七日港股走势分析概率（大模型 > Jev 类型化决策 > 量化基准，三路留痕），失败如实降级。

    取代原「每日量化策略（行业轮动）」栏目：三只港股指数、未来 7 个交易日升跌概率。
    研判引擎优先级：大模型（Key 已配置且调用成功）> Jev 本地模型（端点已配置且调用
    成功）> 量化基准兜底。Jev 端点未配置时行为与引入前完全一致。
    返回 ``None`` = 「本次没有这个栏目」：大模型 Key 与 Jev 端点都未配置（且未开启
    降级）或本次已关闭 → 上层不写 data 键，既不渲染也不进数据覆盖审计。已配置但研判
    引擎不可用时按 OCTOPUS_HK7_FALLBACK 决定：auto 降级为量化基准（栏内标注原因）、
    never 整栏缺席并按「暂缺」进审计（run_seven_day 返回 available=False，错误原因与
    Jev 状态透传给审计）。「数据覆盖」审计里会点名 Jev 端点状态（jev_note）。
    """
    print("📡 正在做 AI 七日港股走势分析概率（恒指 / 恒科 / 国企 · 未来 7 个交易日）...")
    if not HK7_ENABLED:
        print("  ⏭ 该栏目已关闭（OCTOPUS_HK7=0 / --no-hk7）：整栏缺席，不进审计")
        return None
    config = _hk7.llm_config()
    jev_cfg = _jev.jev_config()
    if not config.get("enabled") and not jev_cfg.get("enabled") \
            and config.get("fallback") != "always":
        print("  ⏭ 未配置大模型 API Key（OCTOPUS_LLM_API_KEY）且未配置 Jev 端点"
              "（OCTOPUS_JEV_BASE_URL）：本栏目整体缺席（不进审计）；如需都没有研判引擎"
              "也看量化基准：OCTOPUS_HK7_FALLBACK=1")
        return None
    if not config.get("enabled") and not jev_cfg.get("enabled"):
        print("  ⚠️ 大模型 API Key 与 Jev 端点都未配置 → OCTOPUS_HK7_FALLBACK=1："
              "降级为量化基准")
    elif not config.get("enabled"):
        print(f"  ℹ️ 未配置大模型 API Key → 启用 Jev 本地模型（{jev_cfg.get('base')}）")
    try:
        res = _hk7.run_seven_day(
            safe_request,
            history_path=os.path.join(REPORT_DIR, HK7_HISTORY_FILENAME),
            extra=_hk7_extra_context(data or {}), config=config, jev_config=jev_cfg)
    except Exception as exc:                  # 该栏目异常不影响日报其它栏目
        print(f"  ⚠️ AI 七日港股走势分析概率异常：{exc}")
        jev_note = ("端点已配置，本次执行异常中断" if jev_cfg.get("enabled")
                    else "端点未配置（OCTOPUS_JEV_BASE_URL）")
        return _source_result(HK7_SOURCE_NAME, "unavailable", result=None,
                              error=str(exc), jev_note=jev_note)

    if not res.get("available"):
        jev_note = _hk7_jev_note(res)
        print(f"  ⚠️ AI 七日港股走势分析概率暂不可用：{res.get('reason')} · Jev：{jev_note}")
        return _source_result(HK7_SOURCE_NAME, "unavailable", result=None,
                              error=f"{str(res.get('reason') or '数据不足')} · Jev：{jev_note}",
                              jev_note=jev_note)
    jev_note = _hk7_jev_note(res)
    print(f"  ✅ AI 七日港股：锚定 {res.get('asof')} 收盘 · {res.get('engine_label')}"
          + (f" · 数字溯源 {res.get('grounded')}" if res.get("engine") == "llm" else ""))
    for t in res.get("targets") or []:
        print(f"     · {t['name']} P(7日涨) {t['p_up'] * 100:.0f}%"
              f"（量化基准 {t['quant_p_up'] * 100:.0f}%"
              + ("，已收敛" if t.get("converged") else "") + "）")
    if res.get("missing"):
        print(f"  ⚠️ {res['missing']}")
    if res.get("engine") == "jev":
        print(f"  ℹ️ Jev 本地模型在用：{jev_note}")
    elif res.get("engine") != "llm":
        print(f"  ⚠️ 大模型降级原因：{res.get('llm_reason')} · Jev：{jev_note}")
        hint = _hk7.llm_error_hint(res.get("llm_reason"))
        if hint:
            print(f"  🛠 下一步：{hint}")
    return _source_result(
        HK7_SOURCE_NAME, "success", is_today=res.get("is_today", False),
        content_date=res.get("asof"), result=res,
        llm_error=(res.get("llm_reason") if res.get("engine") != "llm" else None),
        jev_note=jev_note)


def _calendar_events_for_weekly(cal_result):
    """把「时间节点」栏目抓到的财经日程压成逐日表格要用的事件提醒 [{date, name, imp}]。

    只取 ★★ 及以上（重要度 ≥2）、日期在锚定日之后的条目；日程只用于「事件日提醒」，
    绝不参与概率计算（日程本身不含方向信息）。日历缺席就返回空列表，逐日表格照常出。
    """
    if not isinstance(cal_result, dict) or cal_result.get("status") != "success":
        return []
    out = []
    for it in cal_result.get("items") or []:
        if not isinstance(it, dict):
            continue
        try:
            imp = int(it.get("imp") or 0)
        except (TypeError, ValueError):
            imp = 0
        date_str = str(it.get("date") or "")[:10]
        if imp >= 2 and date_str:
            out.append({"date": date_str, "name": str(it.get("name") or ""), "imp": imp})
    return out


def fetch_weekly_forecast(cal_result=None):
    """运行【嗜血大白鲨】逐日走势量化分析（恒指日线 · 未来 7 个交易日逐日表格 · 无未来函数）。

    cal_result: 可选，本次抓到的「时间节点」财经日历结果；用来给逐日表格标注事件日
    （★★★ 日程 → 「事件日波动可能放大」提醒），不参与任何概率计算。失败时如实降级。
    """
    print("📡 正在计算【嗜血大白鲨】逐日走势量化分析（恒生指数 · 未来 7 个交易日逐日 · 无未来函数）...")
    if not WEEKLY_ENABLED:
        print("  ⏭ 量化走势预测已关闭（OCTOPUS_WEEKLY=0 / --no-weekly）")
        return _source_result("每周量化走势预测", "unavailable", result=None,
                              error="本次运行已关闭每周预测")
    events = _calendar_events_for_weekly(cal_result)
    try:
        res = _weekly.run_weekly(
            safe_request,
            history_path=os.path.join(REPORT_DIR, WEEKLY_HISTORY_FILENAME),
            events=events)
    except Exception as exc:                       # 预测异常不影响日报其它栏目
        print(f"  ⚠️ 量化走势预测异常：{exc}")
        return _source_result("每周量化走势预测", "unavailable", result=None, error=str(exc))

    if not res.get("available"):
        print(f"  ⚠️ 量化走势预测暂不可用：{res.get('reason')}")
        return _source_result("每周量化走势预测", "unavailable", result=None,
                              error=str(res.get("reason") or "样本不足"))

    entry = res.get("entry") or {}
    daily = res.get("daily") or {}
    print(f"  ✅ 七日整段：{entry.get('label')}（锚定 {entry.get('base_date')} 收盘"
          f" → 未来 {entry.get('target_sessions')} 个交易日）")
    rows = daily.get("rows") or []
    if rows:
        ups = sum(1 for r in rows if r.get("direction") == "up")
        downs = sum(1 for r in rows if r.get("direction") == "down")
        print(f"  ✅ 逐日表格：{len(rows)} 行（{rows[0].get('date')} ~ {rows[-1].get('date')}）"
              f" · 看涨 {ups} / 看跌 {downs} / 中性 {len(rows) - ups - downs}"
              + (f" · 事件日提醒 {sum(1 for r in rows if r.get('events'))} 天" if events else ""))
    bt = res.get("backtest") or {}
    if bt.get("hit_rate") is not None:
        print(f"  ✅ 滚动样本外：{bt['n']} 期 · 命中 {bt['hit_rate'] * 100:.0f}%"
              f"（基准 {bt['base_rate'] * 100:.0f}%）· Brier {bt['brier']:.3f}")
    jr = res.get("journal") or {}
    if jr.get("n"):
        print(f"  ✅ 预测留痕：已结算 {jr['n']} 次"
              + (f" · 命中 {jr['hits']}" if jr.get("hit_rate") is not None else "（样本 <10，只报样本量）"))
    return _source_result("每周量化走势预测", "success",
                          is_today=res.get("is_today", False),
                          content_date=res.get("as_of"),
                          result=res)


# ============================================================
# 「时间节点」栏目（原「未来 N 天影响经济时间点」）：抓取 + 筛选（东方财富财经日历）
# ------------------------------------------------------------
# 三类内容（缺一不可）：
#   kind 0 经济数据 —— 中/美/欧/日/英等市场的宏观读数发布（CPI、非农、LPR…）
#   kind 1 事件     —— 各国央行议息会议、国民经济运行情况发布会、中央全会等
#   kind 2 动态     —— 央行官员讲话、货币政策会议纪要、EIA/CFTC 周度报告
# 重要度 imp：3 最高（央行议息 + 中美核心读数）/ 2 重要 / 1 一般（展会论坛等）。
# 全部为确定性规则，写死在上方常量里：可复现、不预测方向、不伪造任何日程；
# 接口读不到就如实降级为「暂缺 + 原因」，绝不用推算日期冒充数据源。
# ============================================================
def _cal_date_obj(date_str):
    """'YYYY-MM-DD' → date；非法返回 None。"""
    try:
        return datetime.strptime(str(date_str or "")[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _cal_clean_tags(name):
    """去掉名称里没有信息量的标注（同日可能同时存在带与不带标注的两条）。"""
    name = str(name or "")
    for tag in CALENDAR_NOISE_TAG:
        name = name.replace(tag, "")
    return name.strip()


def _cal_split_period(name):
    """拆出「(报告期:2026年09月)」→ (基础名, '2609')；无报告期时第二位为空串。"""
    name = str(name or "").strip()
    match = re.match(r"^(.*?)\s*[（(]报告期[:：]([^）)]*)[)）]\s*$", name)
    if not match:
        return name, ""
    base = match.group(1).strip()
    ym = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", match.group(2) or "")
    if ym:
        return base, ym.group(1)[2:] + ym.group(2).zfill(2)
    return base, (match.group(2) or "").strip()


def _cal_strip_country(name, city):
    """剥掉「美国:」「美国EIA…」这类地区前缀（地区已单独成列，前缀会重复显示）。

    只在后面跟冒号或 ASCII 字母数字时才剥：「美国EIA原油库存」能处理，
    而「中国银行间同业拆借」这种地区名本就是词一部分的不会被误伤。
    """
    name = str(name or "").strip()
    city = str(city or "").strip()
    if not city or not name.startswith(city) or len(name) <= len(city):
        return name
    rest = name[len(city):]
    for sep in (":", "："):
        if rest.startswith(sep):
            return rest[len(sep):].strip()
    if rest[0].isascii() and (rest[0].isalnum() or rest[0] in "._-"):
        return rest.strip()
    return name


def _cal_canon(name):
    """归一化指标名：统一冒号/括号并剥掉「季调/初值/当月」等修饰词。"""
    n = str(name or "").replace("：", ":").replace("（", "(").replace("）", ")")
    for word in CALENDAR_CANON_DROP:
        n = n.replace(word, "")
    while "::" in n:
        n = n.replace("::", ":")
    return n.strip(": ")


def _cal_kou(name):
    """取口径（同比 / 环比）；东财同一指标常同时排两行，偶尔还多一条裸名。"""
    n = _cal_canon(name)
    if n.endswith("同比"):
        return "同比"
    if n.endswith("环比"):
        return "环比"
    return ""


def _cal_base_of(name):
    """去掉口径后的基础指标名，用于判断「同一天同一指标排了几行」。"""
    n = _cal_canon(name)
    for suffix in (":同比", ":环比", "同比", "环比"):
        if n.endswith(suffix):
            return n[:-len(suffix)].strip(": ")
    return n


def _cal_period_ok(date_str, period):
    """报告期与发布日相差过远视为异常标注：正常经济数据报告期领先发布日 0~4 个月。

    实测东财部分行会给出「报告期:2027年07月」这种远期口径挂在 2026 年的日期上，
    原样展示会让人误读，因此只丢标注、不丢这条时间点。
    """
    if not period or len(period) != 4:
        return True
    day = _cal_date_obj(date_str)
    if not day:
        return False
    try:
        p_year, p_month = 2000 + int(period[:2]), int(period[2:])
    except (TypeError, ValueError):
        return False
    if not 1 <= p_month <= 12:
        return False
    return 0 <= (day.year * 12 + day.month) - (p_year * 12 + p_month) <= 4


def _cal_period_label(period, today=None):
    """'2609' → '9月'（同年）/ '2027年1月'（跨年）；无法解析时原样返回。"""
    period = str(period or "")
    if len(period) != 4 or not period.isdigit():
        return period
    year, month = 2000 + int(period[:2]), int(period[2:])
    if not 1 <= month <= 12:
        return period
    base = today or datetime.now(CST).date()
    return f"{month}月" if year == base.year else f"{year}年{month}月"


def _cal_item_text(item, today=None):
    """时间点正文（纯文本）：名称（含合并后的口径）+ 报告期 + 类型标签。

    如「CPI：同比/环比 · 9月 · 数据」「非农就业人数 · 9月 · 数据」。
    """
    item = item if isinstance(item, dict) else {}
    name = str(item.get("name") or "").strip()
    kous = [k for k in (item.get("kou") or []) if k]
    if kous:
        name = f"{_cal_base_of(name)}:{'/'.join(kous)}"
    parts = [name]
    period = _cal_period_label(item.get("period"), today)
    if period:
        parts.append(period)
    kind_label = CALENDAR_KIND_LABELS.get(item.get("kind"), "")
    if kind_label:
        parts.append(kind_label)
    return " · ".join(p for p in parts if p)


def _cal_event_imp(text, low=False):
    """事件类重要度：中国宏观决策会议 → ★★★；主要央行的议息/决议动作 → ★★★；
    其余事件（小国央行、行业会议）→ ★★；展会论坛 → ★。"""
    text = str(text or "")
    if any(k in text for k in CALENDAR_EVENT_TOP):
        return 3
    if (any(k in text for k in CALENDAR_EVENT_ORG)
            and any(k in text for k in CALENDAR_EVENT_ACT)):
        return 3
    return 1 if low else 2


def _cal_classify(row):
    """把一条东财日历原始记录判成结构化时间点；判定为噪音时返回 None。"""
    if not isinstance(row, dict):
        return None
    raw_name = _cal_clean_tags(row.get("FE_NAME"))
    start = str(row.get("START_DATE") or "")
    date_str = start[:10]
    if not raw_name or not _cal_date_obj(date_str):
        return None
    if len(raw_name) > CALENDAR_MAX_NAME_LEN:
        return None
    if any(k in raw_name for k in CALENDAR_DROP_KW):
        return None                       # 个股事项：与宏观时间点无关
    if any(k in raw_name for k in CALENDAR_DROP_NAME_KW):
        return None                       # 冗余子序列（户籍失业率 / 现价 GDP…）
    if any(raw_name.endswith(k) for k in CALENDAR_DROP_NAME_SFX):
        return None

    city = str(row.get("CITY") or "").strip()
    ftype = str(row.get("FE_TYPE") or "").strip()
    std = str(row.get("STD_TYPE_CODE") or "").strip()
    base, period = _cal_split_period(raw_name)
    low = any(k in base for k in CALENDAR_LOW_KW)
    # 地区已单独成列，名称里的「美国:」「美国EIA…」前缀会重复显示（事件行的 CITY
    # 常是城市名，此时前缀剥不掉、原样保留，不会误伤）。
    item = {"date": date_str, "time": start[11:16], "city": city,
            "name": _cal_strip_country(base, city), "period": period}

    # ① 事件类：FE_TYPE 直接给出事件名（美联储议息会议 / 国民经济运行情况发布会…）
    if ftype and ftype != "经济数据":
        item.update(kind=1, imp=_cal_event_imp(ftype + base, low), period="")
        return item
    # ② 事件类：无 FE_TYPE 但报表类型标记为事件
    if std in ("1", "3"):
        item.update(kind=1, imp=_cal_event_imp(base, low), period="")
        return item
    # ③ 动态类：无 FE_TYPE（央行官员讲话 / 会议纪要 / 周度报告）
    #    动态行没有确认的国家 + 指标结构，最高只给 ★★，不冒充 ★★★。
    if not ftype:
        if (any(k in base for k in CALENDAR_DYN_TIER2)
                or any(k in base for k in CALENDAR_TIER3_KW)
                or (any(k in base for k in CALENDAR_TIER2_KW) and city in CALENDAR_KEEP_CITY)):
            imp = 2
        else:
            imp = 1
        item.update(kind=2, imp=imp, period="")
        return item
    # ④ 经济数据：只保留有定价权的市场 + 一二级读数
    if city not in CALENDAR_KEEP_CITY:
        return None
    if any(k in base for k in CALENDAR_TIER3_KW):
        imp = 3 if city in CALENDAR_CORE_CITY else 2
    elif any(k in base for k in CALENDAR_TIER2_KW):
        imp = 2 if city in CALENDAR_MAJOR_CITY else 1
    else:
        return None
    item.update(kind=0, imp=imp,
                period=period if _cal_period_ok(date_str, period) else "")
    return item


def _cal_dedupe(items):
    """同一天同一指标的多口径行合并成一行：口径并进 kou 列表（如「CPI:同比/环比」）。

    东财常把同一指标按 同比 / 环比 / 初值 / 终值 排成多行，逐行列出会让同一天
    出现 3~6 条重复。本栏只回答「什么时候发」，所以合并为一行、口径全部保留：
    既不丢信息也不刷屏。事件 / 动态行按（日期, 时间, 归一化名称）去重。
    """
    merged, order = {}, []
    for it in items:
        if it.get("kind") == 0:
            key = (it.get("date"), it.get("city"), _cal_base_of(it.get("name")))
        else:
            key = (it.get("date"), it.get("time"), _cal_canon(it.get("name")))
        hit = merged.get(key)
        if hit is None:
            kou = _cal_kou(it.get("name"))
            merged[key] = dict(it, kou=[kou] if kou else [])
            order.append(key)
            continue
        kou = _cal_kou(it.get("name"))
        if kou and kou not in hit["kou"]:
            hit["kou"].append(kou)
        hit["imp"] = max(int(hit.get("imp") or 0), int(it.get("imp") or 0))
        if kou and not _cal_kou(hit.get("name")):
            hit["name"] = it.get("name")     # 有口径的行信息量更高，用它当代表名
        if it.get("period") and not hit.get("period"):
            hit["period"] = it.get("period")
        if str(it.get("time") or "99:99") < str(hit.get("time") or "99:99"):
            hit["time"] = it.get("time")     # 同指标多行取最早那个时点
    out = []
    for key in order:
        it = merged[key]
        it["kou"].sort(key=lambda k: (0 if k == "同比" else (1 if k == "环比" else 2)))
        out.append(it)
    return out


def _cal_sort_key(item):
    return (str(item.get("date") or ""), str(item.get("time") or "99:99"))


def _cal_cut_priority(item):
    """裁剪优先级：重要度高者优先；同级里「数据 / 事件」优先于「动态」（讲话、
    周报最容易刷屏）；再同级按时间先后。"""
    kind = int(item.get("kind") or 0)
    return (-(int(item.get("imp") or 0)), 1 if kind == 2 else 0) + _cal_sort_key(item)


def _cal_select(items, max_rows=None):
    """正文行数裁剪：按优先级保留到上限，返回 (kept, dropped)。

    kept 按（日期, 时间）排序；dropped 是被裁掉的条目列表，调用方据此如实披露
    各重要度被裁了多少条（绝不静默丢内容）。上限只是版面保护，正常月份
    ★★★ / ★★ 都能全部列出。
    """
    limit = int(max_rows or ECON_CALENDAR_MAX_ROWS)
    if limit <= 0 or len(items) <= limit:
        return sorted(items, key=_cal_sort_key), []
    ranked = sorted(items, key=_cal_cut_priority)[:limit]
    kept_ids = {id(it) for it in ranked}
    dropped = [it for it in items if id(it) not in kept_ids]
    ranked.sort(key=_cal_sort_key)
    return ranked, dropped


def _cal_imp_counts(items):
    """按重要度统计条数 → {"3": n, "2": n, "1": n}（摘要与裁剪披露共用）。"""
    counts = {"3": 0, "2": 0, "1": 0}
    for it in items or []:
        if isinstance(it, dict):
            counts[str(max(1, min(3, int(it.get("imp") or 1))))] += 1
    return counts


def _cal_imp_text(counts):
    """{"3":2,"2":5,"1":0} → '★★★ 2 / ★★ 5 / ★ 0'（零值档省略）。"""
    parts = [f"{'★' * int(level)} {counts.get(level) or 0}"
             for level in ("3", "2", "1") if counts.get(level)]
    return " / ".join(parts) or "—"


def _cal_day_label(date_str, today=None):
    """('10-28 周二', 30)：月日 + 星期 + 距今 T+n（今天为 0）。"""
    day = _cal_date_obj(date_str)
    if not day:
        return str(date_str or ""), None
    base = today or datetime.now(CST).date()
    return f"{day.month:02d}-{day.day:02d} {CALENDAR_WEEKDAYS[day.weekday()]}", (day - base).days


def _cal_countdown(t_plus):
    """T+n 的中文说法：0 → 今天，1 → 明天，其余 → T+n；非法值返回空串。"""
    if not isinstance(t_plus, int):
        return ""
    if t_plus == 0:
        return "今天"
    if t_plus == 1:
        return "明天"
    return f"T+{t_plus}" if t_plus > 0 else ""


def _cal_digest(res, today=None, plain=False):
    """把抓取结果整理成两主题共用的中性结构（纯文本，渲染端各自上色）。

    返回 {"pairs": [(标签, 值)], "days": [(日期, 日期标签, T+n, [时间点])]}。
    摘要里的每个数字都来自本次抓取结果：确定性合成、不引入新数据、不预测方向。

    plain=True（入门版；渲染端按 PLAIN() 传入，缺省 False 供研究模式 / 直接调用保留全文）：
    「筛选口径」整行不出，「时间点合计」的被裁分布与「最密集日」的口径括号不出——
    数字（合计 / 星级 / 未列条数 / 最密集日）一个不少。
    """
    res = res if isinstance(res, dict) else {}
    items = [it for it in (res.get("items") or []) if isinstance(it, dict)]
    base = today or datetime.now(CST).date()
    plain = bool(plain)
    pairs = []
    window = str(res.get("window") or "")
    if window:
        pairs.append(("时间窗口", window))
    if not items:
        pairs.append(("时间点合计", "0 个 · 窗口内未筛出影响经济的时间点"
                                    f"（原始日程 {int(res.get('raw_count') or 0)} 条）"))
        return {"pairs": pairs, "days": []}

    counts = _cal_imp_counts(items)
    n3 = counts.get("3") or 0
    total_txt = f"{len(items)} 个 · {_cal_imp_text(counts)}"
    dropped = int(res.get("dropped") or 0)
    if dropped > 0 and plain:
        total_txt += f" · 另 {dropped} 条一般级未列"
    elif dropped > 0:
        # 被版面裁掉的条目按重要度如实披露：读者能看出 ★★★ 是否已全部列出。
        total_txt += (f"（版面另有 {dropped} 条未列出："
                      f"{_cal_imp_text(res.get('dropped_imp') or {})}）")
    pairs.append(("时间点合计", total_txt))

    def _picked(pred, limit=4):
        """命中的时间点压成「10-29 名称」短标签，超出 limit 时如实给出总数。"""
        hit = [it for it in items if pred(it)]
        if not hit:
            return ""
        labels = []
        for it in hit[:limit]:
            label, _ = _cal_day_label(it.get("date"), base)
            name = str(it.get("name") or "")[:22]
            labels.append(f"{label.split(' ')[0]} {name}".strip())
        text = "、".join(labels)
        return f"{text} 等 {len(hit)} 项" if len(hit) > limit else text

    top_events = _picked(lambda it: it.get("kind") == 1 and (it.get("imp") or 0) >= 3)
    pairs.append(("央行议息 / 重要会议", top_events or "窗口内暂无"))
    pairs.append(("中国关键读数",
                  _picked(lambda it: it.get("kind") == 0 and it.get("city") == "中国"
                          and (it.get("imp") or 0) >= 2) or "窗口内暂无"))
    pairs.append(("美国关键读数",
                  _picked(lambda it: it.get("kind") == 0 and it.get("city") == "美国"
                          and (it.get("imp") or 0) >= 2) or "窗口内暂无"))

    by_day = {}
    for it in items:
        by_day.setdefault(str(it.get("date") or ""), []).append(it)
    hot_date = sorted(by_day, key=lambda d: (-len(by_day[d]), d))[0]
    hot_label, hot_t = _cal_day_label(hot_date, base)
    dense_days = sum(1 for group in by_day.values() if len(group) >= 3)
    if n3 >= 4 or dense_days >= 3:
        verdict = "事件密度偏高，注意窗口内的波动放大"
    elif n3:
        verdict = "事件分布相对均衡"
    else:
        verdict = "窗口内无最高级事件"
    hot_when = _cal_countdown(hot_t) if hot_t else ""
    pairs.append(("最密集日", f"{hot_label}（{len(by_day[hot_date])} 项"
                             f"{' · ' + hot_when if hot_when else ''}）· {verdict}"
                             + ("" if plain else "（规则合成，非方向判断）")))
    if not plain:
        pairs.append(("筛选口径",
                      f"东财全窗口 {int(res.get('raw_count') or 0)} 条 → 命中 "
                      f"{int(res.get('matched') or 0)} 条 → 正文 {len(items)} 条；"
                      "保留中美欧日英港宏观读数 / 央行议息与重要会议 / 央行动态，"
                      "剔除个股事项、展会论坛与同指标冗余口径"))

    days = []
    for date_str in sorted(by_day):
        label, t_plus = _cal_day_label(date_str, base)
        group = sorted(by_day[date_str], key=lambda it: (str(it.get("time") or "99:99"),
                                                         -(it.get("imp") or 0)))
        days.append((date_str, label, t_plus, group))
    return {"pairs": pairs, "days": days}


def _calendar_view_days(res, today=None, date_str=None):
    """精简模式的日程版面：只留「今明两天 + 近端 ★★★」，返回 (保留的天, 未列条数)。

    短线客只关心**今明会不会被数据砸盘**；30 天窗口的全貌仍由栏目「窗口摘要」
    如实给出（央行议息 / 中美关键读数 / 最密集日一条不少），因此这里裁的是
    **表格行数**，不是信息——未列条数必须写进披露行，绝不静默丢内容。
    全量模式（--full / OCTOPUS_LITE=0）返回 None = 不裁。
    """
    if not LITE_ENABLED:
        return None
    digest = _cal_digest(res, today)
    days = digest.get("days") or []
    if not days:
        return None
    base = today or datetime.now(CST).date()
    today_str = str(date_str or "")
    if len(today_str) == 8:
        try:
            base = datetime.strptime(today_str, "%Y%m%d").date()
        except ValueError:
            pass
    max_days = LITE("cal_days")
    max_rows = LITE("cal_rows")
    keep = []
    total_rows = 0
    near = []
    for date_str_day, label, t_plus, items in days:
        total_rows += len(items)
        if t_plus is not None and 0 <= t_plus < max_days:
            keep.append((date_str_day, label, t_plus, items))
        else:
            near.append((date_str_day, label, t_plus, items))
    if keep:
        # 今明有内容：近端只补 ★★★（重要度从高到低、时间从近到远），补到行数上限为止
        rows = sum(len(items) for *_x, items in keep)
        star3 = []
        for date_str_day, label, t_plus, items in near:
            hits = [it for it in items if int(it.get("imp") or 0) >= 3]
            if hits:
                star3.append((date_str_day, label, t_plus, hits))
        for group in star3:
            if rows + len(group[3]) > max_rows:
                break
            keep.append(group)
            rows += len(group[3])
        keep.sort(key=lambda g: str(g[0]))
    else:
        # 今明休市（周末 / 假期）：退化为「近端 ★★★ 优先、按时间从近到远」填满行数上限，
        # 绝不因为「今天没有」就整表空掉——那等于把日程栏目变成哑巴。
        ranked = sorted(near, key=lambda g: (-(max(int(it.get("imp") or 0) for it in g[3])),
                                             str(g[0])))
        rows = 0
        for group in ranked:
            if rows + len(group[3]) > max_rows:
                break
            keep.append(group)
            rows += len(group[3])
        keep.sort(key=lambda g: str(g[0]))
    shown = sum(len(items) for *_x, items in keep)
    return keep, max(0, total_rows - shown), base


def _calendar_table_rows(res, cell_builder, today=None, date_str=None):
    """两主题共用：摘要键值 + 逐日展平成表格行（cell_builder 决定各主题的配色）。

    返回 (digest, rows, disclosure)：disclosure 是精简模式下的版面披露文字
    （全量模式为 ""），由调用方渲染成一行脚注——裁了多少条必须如实说。
    """
    digest = _cal_digest(res, today, plain=PLAIN())
    view = _calendar_view_days(res, today, date_str)
    days = view[0] if view else (digest.get("days") or [])
    rows = []
    for _date, label, t_plus, items in days:
        for i, it in enumerate(items):
            rows.append(cell_builder(label, t_plus, it, first=(i == 0)))
    disclosure = ""
    if view and PLAIN():
        # 入门版：版面规则不解释；只在确有未列条目时给「另 N 条未列」四个字（挂在表格小标题后）。
        _keep, hidden, base = view
        disclosure = f"另 {hidden} 条未列" if hidden else ""
    elif view:
        _keep, hidden, base = view
        window_items = sum(len(items) for _d, _l, _t, items in digest.get("days") or [])
        if hidden:
            disclosure = (f'精简版面：表格只列今天（{base:%m-%d}）起 {LITE("cal_days")} 天'
                          f' + 近端 ★★★，最多 {LITE("cal_rows")} 行；'
                          f'窗口内另有 {hidden} 条未在表格列出（全窗口共 {window_items} 条，'
                          f'分布见上方「窗口摘要」；--full 看全表）')
        else:
            disclosure = (f'精简版面：窗口内 {window_items} 条已全部列出'
                          f'（今明 + 近端 ★★★，最多 {LITE("cal_rows")} 行）')
    return digest, rows, disclosure


def _calendar_table_label():
    """日历表小标题：精简模式说明只列近端，全量模式仍是「逐日时间点」。"""
    return ("今明 + 近端 ★★★ 时间点（北京时间）" if LITE_ENABLED
            else "逐日时间点（北京时间）")


def fetch_econ_calendar(days=None, today=None):
    """抓取未来 N 天影响经济的时间点（东方财富财经日历，公开接口无需密钥）。

    返回 _source_result：
      items     —— [{date, time, city, name, imp, kind, period}]，已排序并按上限裁剪；
      raw_count —— 窗口内原始日程条数；matched —— 命中筛选口径的条数；
      dropped   —— 因正文行数上限被裁掉的一般级条数；window —— 窗口文字。
    任何异常都如实降级为 status=failed + error 原因，绝不用推算日期冒充数据源。
    前瞻性日程 is_today=False + snapshot=True：只作「今日抓取」，不参与当天检验计数。
    """
    window_days = int(days or ECON_CALENDAR_DAYS)
    base = today or datetime.now(CST).date()
    end = base + timedelta(days=window_days)
    window = f"{base.isoformat()} ~ {end.isoformat()} · 未来 {window_days} 天"
    # 服务端只支持按日期过滤（按 CITY / FE_TYPE 过滤返回空），故拉全窗口后本地筛。
    flt = (f"(START_DATE>='{base.isoformat()}')"
           f"(START_DATE<'{(end + timedelta(days=1)).isoformat()}')")
    referer = {"Referer": "https://data.eastmoney.com/"}
    rows, page, error = [], 1, ""
    while page <= ECON_CALENDAR_MAX_PAGES:
        params = {
            "reportName": ECON_CALENDAR_REPORT,
            "columns": ECON_CALENDAR_COLUMNS,
            "filter": flt,
            "pageNumber": str(page),
            "pageSize": str(ECON_CALENDAR_PAGE_SIZE),
            "sortColumns": "START_DATE",
            "sortTypes": "1",
            "source": "WEB",
            "client": "WEB",
        }
        # 数据线 em_datacenter：datacenter-web → datacenter → datacenter/securities（同格式镜像）
        payload, _, _ = safe_request_with_fallback(
            _backup.get_calendar_urls(), headers=referer, params=params, timeout=15,
            line="em_datacenter",
            validate=lambda d: isinstance(d, dict) and "result" in d)
        if not isinstance(payload, dict):
            error = "接口无响应或非 JSON"
            break
        result = payload.get("result")
        result = result if isinstance(result, dict) else {}
        batch = [r for r in (result.get("data") or [])
                 if isinstance(r, dict) and r.get("FE_NAME") and r.get("START_DATE")]
        rows.extend(batch)
        try:
            count = int(result.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if not batch or (count and len(rows) >= count):
            break
        page += 1
        time.sleep(0.3)

    # 服务端过滤之外再本地夹一次窗口：栏目写的是「未来 N 天」，就绝不能出现 T+N 之外的行。
    in_window = []
    for r in rows:
        day = _cal_date_obj(str(r.get("START_DATE") or "")[:10])
        if day and base <= day <= end:
            in_window.append(r)
    rows = in_window

    if not rows:
        reason = error or "接口未返回窗口内日程"
        print(f"  ⚠️ 财经日历暂缺：{reason}")
        return _source_result(ECON_CALENDAR_SOURCE, "failed", is_today=False,
                              content_date=base.isoformat(), error=reason,
                              items=[], raw_count=0, matched=0, dropped=0,
                              window=window, days=window_days,
                              page=ECON_CALENDAR_PAGE)

    items = [it for it in (_cal_classify(r) for r in rows) if it]
    items = _cal_dedupe(items)
    kept, dropped = _cal_select(items)
    dropped_imp = _cal_imp_counts(dropped)
    print(f"  📅 财经日历：原始 {len(rows)} 条 → 命中 {len(items)} 条 → 正文 {len(kept)} 条"
          + (f"（版面裁掉 {len(dropped)} 条）" if dropped else "") + f"（{window}）")
    return _source_result(ECON_CALENDAR_SOURCE, "success", is_today=False,
                          content_date=base.isoformat(), snapshot=True,
                          items=kept, raw_count=len(rows), matched=len(items),
                          dropped=len(dropped), dropped_imp=dropped_imp,
                          window=window, days=window_days,
                          page=ECON_CALENDAR_PAGE)


def collect_all_data():
    with _BACKUP_EVENTS_LOCK:
        BACKUP_EVENTS.clear()
    """采集所有数据源"""
    print("\n" + "=" * 50)
    print("🔍 开始全网数据采集")
    print("=" * 50)

    data = {}
    if SHIQUAN_ENABLED and _shiquan.is_enabled():
        poem = _shiquan.fetch_random_poem(allow_network=True)
        if poem is not None:
            data[SHIQUAN_META_KEY] = poem
            print("\n" + _shiquan.format_cli_banner(poem))
    data["实时行情"] = fetch_market_snapshot()
    time.sleep(0.5)
    data["A股大盘全景"] = fetch_market_panorama()
    time.sleep(0.5)
    # Yahoo 在交易所本地 0 点后几小时内会暂时丢掉刚收盘的日线（2026-09-29 凌晨实测：
    # 恒指 / 上证回退到上周五）。这里用东方财富的行情时间做独立基准核对并回补，
    # 保证「今日预判」里的港股 / A股一句话是最近一个收盘，而不是上上个交易日。
    if data["实时行情"].get("status") == "success":
        _reconcile_market_snapshot(data["实时行情"], data["A股大盘全景"],
                                   hk_ref=_fetch_hk_index_reference())
    # 政策因子的独立官方输入：直接读取中国政府网最新政策，不以媒体转载替代。
    data["国家政策"] = fetch_gov_policy()
    time.sleep(0.5)
    data["港股名家频道"] = fetch_hk_channels()
    time.sleep(0.5)

    data["全球头条"] = fetch_google_news()
    time.sleep(0.5)

    # AI趋势分析两个专题：各自独立的 Google News 查询，独立降级
    data[FED_TREND_KEY] = fetch_fed_trend()
    time.sleep(0.5)
    data[GEO_TREND_KEY] = fetch_geo_trend()
    time.sleep(0.5)

    data["东财快讯"] = fetch_eastmoney_news()
    time.sleep(0.5)

    data["热门榜单"] = fetch_hot_stocks()
    time.sleep(0.5)

    data["港股量化"] = fetch_hk_quant()
    time.sleep(0.5)

    macd_src = fetch_macd_strategy(data)
    if macd_src is not None:
        # 日线只在这一刻交给 UZI 趋势栏目（私有键，用完即弹出，不进 data / 不入库）。
        uzi_bars = macd_src.pop("_bars_by_code", {})
        data[MACD_SOURCE_NAME] = macd_src
        uzi_src = fetch_uzi_trend(data, uzi_bars)
        if uzi_src is not None:
            data[UZI_TREND_SOURCE_NAME] = uzi_src

    # 「时间节点」财经日历先抓：逐日表格要用窗口内的 ★★★ 日程做「事件日提醒」
    # （日程不参与概率计算，缺席也只是少一行提醒，不影响预测）。
    if ECON_CALENDAR_ENABLED:
        print(f"\n📅 正在抓取「时间节点」· 未来 {ECON_CALENDAR_DAYS} 天影响经济时间点（东方财富财经日历）...")
        data["财经日历"] = fetch_econ_calendar()
        time.sleep(0.5)

    data["每周走势预测"] = fetch_weekly_forecast(data.get("财经日历"))
    time.sleep(0.5)

    print("\n📰 正在采集趋势跟踪（多平台信息员：" + " + ".join(_active_public_site_names())
          + f"；另有全网 {HK_NEWS_TOTAL} 个新闻源头港股挖掘"
          + f" + 内地财经媒体 {MAINLAND_NEWS_TOTAL} 家标题池）...")
    data.update(fetch_public_sites())
    if HK_NEWS_ENABLED:
        data[HK_NEWS_SOURCE_NAME] = fetch_hk_news_sources()
    # 内地财经媒体源头（18 家，2026-10-12 按用户指定新增）：与港股新闻源头并行采集，
    # 标题进同一标题池（新闻情绪因子 / 政策因子 / 策略研判）；关闭时不写 data 键。
    if MAINLAND_NEWS_ENABLED:
        data[MAINLAND_NEWS_SOURCE_NAME] = fetch_mainland_news_sources()
        time.sleep(0.5)

    # AI 七日港股走势分析概率：等当日证据（行情 / 日程 / 港股标题）齐了再研判。
    # 未配置 Key（且未开启降级）或本次关闭 → None：不写 data 键，栏目与审计都不出现。
    hk7_src = fetch_hk_seven_day(data)
    if hk7_src is not None:
        data[HK7_SOURCE_NAME] = hk7_src
    time.sleep(0.5)

    # A股全量概念库 → 明确关键词映射到港股观察篮子；失败 / 无映射不伪造信号。
    data[SECTOR_ROTATION_SOURCE_NAME] = fetch_sector_rotation(data)
    time.sleep(0.5)

    # 申万一级行业轮动（A股 31 个行业）：固定股票池 + 板块指数日线，失败整栏缺席。
    data[INDUSTRY_ROTATION_SOURCE_NAME] = fetch_industry_rotation()
    time.sleep(0.5)

    # 策略大类量化（图中 4 大类 6 细分）：内部衍生、可离线兜底，不计入当天检验 / 总源审计。
    if STRATEGY_QUANT_ENABLED:
        sq = fetch_strategy_quant(date_str=datetime.now(CST).strftime("%Y%m%d"))
        if sq is not None:
            data[STRATEGY_QUANT_SOURCE] = sq
            time.sleep(0.2)

    # === 新增：全栏目新鲜度检查 ===
    print("\n🕐 正在检查全栏目数据新鲜度...")
    try:
        freshness_result = _freshness.check_all_freshness(data)
        print(f"  {freshness_result['summary']}")
        report = _freshness.format_freshness_report(freshness_result)
        print(report)
        data["_freshness"] = freshness_result
    except Exception as exc:
        print(f"  ⚠️ 新鲜度检查失败: {exc}")
        data["_freshness"] = {"error": str(exc), "total": 0, "fresh": 0, "stale": 0, "unavailable": 0, "summary": f"检查失败: {exc}"}

    # === 新增：跨栏目 70% 相似度去重合并 ===
    print("\n🔍 正在执行跨栏目去重合并（相似度阈值 70%）...")
    try:
        dedup_result = _dedup.dedup_across_sections(data, threshold=0.7)
        summary = _dedup.get_dedup_summary(dedup_result)
        print(f"  {summary}")
        data["_dedup"] = dedup_result
        for section in ["全球头条", "东财快讯", "美联储趋势", "地缘政治趋势"]:
            src = data.get(section)
            if isinstance(src, dict) and src.get("headlines"):
                deduped, merged = _dedup.merge_similar_items(src["headlines"], threshold=0.7, key="title")
                if merged > 0:
                    print(f"  ✅ {section}: 内部去重 {len(src['headlines'])} → {len(deduped)} (合并 {merged} 条)")
                    src["headlines"] = deduped
                    src["_dedup_merged"] = merged
    except Exception as exc:
        print(f"  ⚠️ 去重合并失败: {exc}")
        data["_dedup"] = {"error": str(exc), "total_before": 0, "total_after": 0, "merged": 0}

    # === 备用源使用情况汇总 ===
    try:
        backup_summary = _backup.get_backup_summary()
        events = list(BACKUP_EVENTS)
        print(f"\n🔄 数据线主备：{len(_backup.DATA_LINES)} 条数据线，每条 1 主源 + 2 备用源"
              f"（python3 output/pipeline.py --sources 查看明细）")
        if events:
            print("  🔁 本次备用源顶上：" + backup_events_text(events))
        else:
            print("  ✅ 本次全部由主源供数，未启用备用源")
        data["_backup_info"] = {"summary": backup_summary, "sources": list(_backup.ALL_BACKUP_MAP.keys()),
                                "lines": len(_backup.DATA_LINES), "events": events}
    except Exception:
        data["_backup_info"] = {"summary": "备用源已启用", "events": list(BACKUP_EVENTS)}

    print("\n✅ 数据采集完成！")
    return data


# ============================================================
# HTML 组件（设计系统：复古像素游戏 · MARKET QUEST v3）
# ------------------------------------------------------------
# 版式语言：
#  · 暗色街机终端底 + 霓虹青 / 品红 / 电光蓝 / 像素黄
#  · 纯直角像素风：0 圆角、3px 硬描边 + 实色阴影，像 8-bit 卡带界面
#  · 等宽像素字体栈，中文回退苹方/雅黑；不依赖外部字体、图片或 SVG
#  · 纯 HTML 像素章鱼 + 每栏独立 44px 图标砖，图标始终先于文字建立层级
#  · 涨跌 = 高对比颜色底块 + ▲/▼/■ + 涨/跌/平，兼顾色觉差异
#  · AI = 主控卡 + 关键指标计分板 + 大字号主结论 + 四个独立面板
# 硬约束：仍全部内联样式 + 表格布局，兼容微信/PushPlus
# ============================================================
# 复古游戏像素调色板
C_BG = "#050711"
C_PAPER = "#101426"
C_INK = "#F4F7FF"
C_ACCENT = "#39FFB6"
C_ACCENT_DEEP = "#FFFFFF"
C_ACCENT_SOFT = "#303A60"
C_ACCENT_MAGENTA = "#FF3CAC"
C_CYAN = "#22DFFF"
C_VIOLET = "#A98CFF"
C_MUTED = "#A6AEC9"
C_FAINT = "#747D9F"
C_HAIR = "#29314E"
C_ZEBRA = "#181D34"
C_LEMON = "#FFE66D"
C_MINT = "#39FFB6"
# 涨跌色不仅靠文字色区分，还配合 ▲/▼、深色底块与硬描边，保证微信深色页面中一眼可辨。
C_RED = "#FF5576"
C_GREEN = "#35F29A"
C_AMBER = "#FFD166"
C_BLUE = "#22DFFF"
C_MAGENTA = "#FF3CAC"
C_UP_BG = "#082B22"
C_DOWN_BG = "#34131F"
C_FLAT_BG = "#302711"
C_AI_BG = "#17152F"
FONT = ("'Courier New', Courier, 'Lucida Console', monospace, "
        "PingFang SC, Microsoft YaHei, sans-serif")
FONT_MONO = "'Courier New', Courier, monospace"

# pixel（DOS 终端）表格字号阶梯：2026-10-23 按用户要求「表格内文字缩小一号 + 不加粗」，
# 每档各收 1px（数据表表身 11→10、表头 10→9；账本双列 12→11；资讯行 12→11、序号 11→10）。
# 字重统一走 GZ_W_TABLE（400）；颜色与等宽字形不变，终端观感保持。
PIXEL_FS_GRID = 10          # 数据表表身
PIXEL_FS_GRID_HEAD = 9      # 数据表表头
PIXEL_FS_LEDGER = 11        # 账本式双列表（行情 / KV）
PIXEL_FS_ITEM = 11          # 资讯行正文
PIXEL_FS_ITEM_ICON = 10     # 资讯行序号 / 图标
PIXEL_FS_LEDGER_NUM = 12    # 账本表内的关键数值（原 13px，随表格一起收一号）

# ============================================================
# 归藏简洁排版（Guizang Concise）× 克莱因蓝 + 深灰（2026-09-29）
# —— 一页推送优先：结构扁平、样式全内联、去掉装饰性包装，把全量内容压进单条微信消息
# —— 克莱因蓝 #002FA7：只用于栏目编号 / 小标题 / 强调数值，是页面上唯一的有色
# —— 灰阶承担全部层级：正文 #222、次要/辅助文字统一深灰 #333、细分隔线 #ddd/#eee
# —— 2026-09-29 强制全局灰色字体改深灰色：所有灰色文字（次要 GZ_META、辅助 GZ_FAINT、下跌 GZ_DOWN）统一为 #333
#    （白底对比度 ≥ 12.6:1，过 WCAG AA 4.5:1）；表头 / 脚注 / 时间戳同受此约束，
#    由 tests/test_pipeline.py 的 test_no_washy_text_colors 与 test_global_dark_gray_font_enforced 看守
# —— 白底、1px 细分隔、大留白；涨跌仍用 ▲ / ▼ / ■ 表达，不依赖红绿
# —— 纯内联样式：无 <style> / class / 外部 CSS / JS / 远程图片，兼容 PushPlus 与微信详情页
# ============================================================
GZ_PAPER = "#FFFFFF"        # 真白底：不是浅灰 #f8fafc，也不是米白 #fafaf9
GZ_PAPER_TINT = "#FFFFFF"   # 保持纯白，不用灰底
GZ_KLEIN = "#002FA7"        # 克莱因蓝（International Klein Blue）
GZ_KLEIN_DEEP = "#00227A"   # 克莱因蓝加深：链接按下 / 强调
GZ_KLEIN_WASH = "#F3F6FF"   # 极淡蓝：需要一点分量时的窄底纹
GZ_INK = "#222"          # 正文灰黑（纯灰，不带蓝紫）
GZ_INK_STRONG = "#111"   # 标题 / 最高强调
GZ_DARK_GRAY = "#333"    # 强制全局深灰色字体（所有灰色字体统一深灰 #333）
GZ_META = GZ_DARK_GRAY   # 次要文字（标签、来源、小标题）｜强制全局改深灰 #333
GZ_FAINT = GZ_DARK_GRAY  # 辅助文字（时间、脚注、表头、摘要）｜强制全局改深灰 #333
GZ_HAIR = "#ddd"         # 栏目分割线
GZ_HAIR_SOFT = "#eee"    # 行间细分隔线
GZ_ZEBRA = "#F2F2F2"     # 栏目内段落灰底：相邻内容块 纯白 ↔ 浅灰 交替（见 _gz_zebra_bands）
GZ_INK_TINT = "#FFFFFF"
GZ_HAIR_INK = GZ_HAIR
GZ_HAIR_W = 1               # 1px 细分隔线，不用 2px
GZ_CREAM = GZ_INK_STRONG
GZ_META_INK = GZ_META
GZ_NEON = GZ_KLEIN          # AI 徽标：克莱因蓝，不再引入第二种彩色
# 涨跌：克莱因蓝 / 深灰 + ▲▼■ 双编码，完全不依赖红绿
GZ_UP = GZ_KLEIN
GZ_DOWN = GZ_DARK_GRAY
GZ_FLAT = GZ_FAINT
GZ_UP_INK = GZ_UP
GZ_DOWN_INK = GZ_DOWN
GZ_FLAT_INK = GZ_FLAT
GZ_WARN = GZ_META           # 「非当天 / 样本不足」用灰，不喧宾夺主
GZ_WARN_INK = GZ_WARN
GZ_PRIMARY = GZ_KLEIN
GZ_PRIMARY_HOVER = GZ_KLEIN_DEEP
GZ_PRIMARY_LIGHT = GZ_KLEIN_WASH
REPORT_TITLE = "章鱼 AI · 上水日报"
# 说明（副标题）：刊头标题下方一行，页面 <meta name="description"> 与控制台同用
REPORT_TAGLINE = "每日上水，新鲜活泼"
# 微信推送标题前缀（2026-10-13 改版，见模块说明 28）：「[OCTOPUS] + 刊头同名」，
# 原为「🐙 + 刊头」。只用于 PushPlus 的 title 字段；页面刊头 / <title> / 归档文件名
# 仍是不带前缀的 REPORT_TITLE（emoji 在部分微信客户端与转发链路会被裁掉，方括号关键词
# 既能在消息列表里一眼认出、也能直接用作消息过滤规则）。
PUSH_TITLE_PREFIX = f"[OCTOPUS] {REPORT_TITLE}"
# 推送标题的时间戳格式：排在「- 」之后、分条 (i/N) 之前，同一天多次推送靠它区分
PUSH_TITLE_TIME_FMT = "%m/%d %H:%M"


def build_push_title(mode="", when=None):
    """拼装微信推送标题：``[OCTOPUS] 章鱼 AI · 上水日报(模式) - MM/DD HH:MM``。

    - mode 留空是常规日报；「(强制)」「(状态)」这类标记紧跟刊头，不与日期时间黏在一起，
      微信窄列表里先看到栏目名、后看到推送时刻；
    - 时间戳永远排在最后，超长分条追加的 (i/N) 接在其后仍读得出推送时刻；
    - 四条推送路径（--push-only / 常规 / 强制 / 状态）统一走这里，标题不会各写各的；
    - 「日报未推送提醒」「日报推送失败提醒」两条纯文本告警不经过本函数（仍带 🐙）：
      它们是提醒而非日报本体，不与 [OCTOPUS] 关键词混在一起；
    - when 仅供测试注入固定时刻，生产调用留空取北京时间当前时刻。
    """
    stamp = (when or datetime.now(CST)).strftime(PUSH_TITLE_TIME_FMT)
    return f"{PUSH_TITLE_PREFIX}{mode} - {stamp}"

# 字体：系统无衬线栈（不加载远程字体）；整页只在容器上写一次，其余元素继承
GZ_FONT = ("-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB',"
           "'Microsoft YaHei',sans-serif")
GZ_SERIF = GZ_FONT
GZ_SANS = GZ_FONT
GZ_MONO = "'SF Mono',Menlo,Consolas,monospace"
GZ_W_BODY = 400             # 正文常规
GZ_W_MEDIUM = 500
GZ_W_BOLD = 700             # 标题 / 数值 / 徽标
GZ_W_HERO = 700
GZ_W_TABLE = 400            # 表格内文字一律常规字重（2026-10-23 用户要求：表格不加粗）
# 字号阶梯：一页推送优先，整体比 SaaS 版收一档，保证单条消息装得下全量内容
GZ_FS_DISPLAY = 26    # 刊头标题
GZ_FS_SECTION = 18    # 栏目标题
GZ_FS_PRICE = 20      # 关键数字
GZ_FS_BODY = 14       # 正文（SaaS 版为 15，一页推送收一档）
GZ_FS_META = 12       # 次要文字
GZ_FS_METER = 12      # 信号格
GZ_FS_TABLE = 12      # 表格正文（2026-10-23 起再缩小一号：13 → 12，仍高于 GZ_FS_FLOOR）
DEFAULT_FONT_SCALE = 1.0
GZ_FS_FLOOR = 11      # 字号下限（任何情况下不低于 11px）


def _resolve_font_scale(value=None):
    """归一化字号缩放系数：归藏简洁固定 1.0（字号阶梯见 GZ_FS_*）。"""
    return 1.0


def _gz_fs(base, scale=None):
    """字号阶梯直接返回基准值（保留函数供旧调用与测试使用）。"""
    return int(base)


# 栏目编号：归藏式「01 · FORECAST」，用字型与留白区分层级，不用图标 / 图片
GZ_SECTION_MARKS = ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
                    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20")

def _sq(color=C_ACCENT, size=8):
    return f'<span style="color:{color};font-size:{size}px;line-height:1;font-family:{FONT_MONO};">■</span>'


def _star(color=C_ACCENT, size=10):
    return f'<span style="color:{color};font-size:{size}px;line-height:1;font-family:{FONT_MONO};">◆</span>'


def _heart(color=C_ACCENT_MAGENTA, size=10):
    return f'<span style="color:{color};font-size:{size}px;line-height:1;font-family:{FONT_MONO};">⚡</span>'


def _flower(color=C_CYAN, size=10):
    return f'<span style="color:{color};font-size:{size}px;line-height:1;font-family:{FONT_MONO};">✚</span>'


def _percent_number(value):
    """把数字 / ``+1.23%`` 文本转成 float；无法转换时返回 None。"""
    try:
        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()
        return float(value)
    except (TypeError, ValueError):
        return None


def _trend_badge(value, compact=False):
    """渲染高辨识度涨跌像素徽标：颜色、箭头和文字三重编码。"""
    pct = _percent_number(value)
    if pct is None:
        return (f'<span style="display:inline-block;border:1px solid {C_FAINT};background:{C_ZEBRA};'
                f'color:{C_FAINT};padding:1px 6px;font-size:10px;font-weight:900;'
                f'font-family:{FONT_MONO};box-shadow:2px 2px 0 #000;white-space:nowrap;">■ --</span>')
    if pct > 0:
        color, bg, arrow, word = C_GREEN, C_UP_BG, "▲", "涨"
    elif pct < 0:
        color, bg, arrow, word = C_RED, C_DOWN_BG, "▼", "跌"
    else:
        color, bg, arrow, word = C_AMBER, C_FLAT_BG, "■", "平"
    label = f"{arrow} {pct:+.2f}%" if compact else f"{arrow} {word} {pct:+.2f}%"
    if pct == 0:
        label = f"{arrow} 0.00%" if compact else f"{arrow} {word} 0.00%"
    return (f'<span style="display:inline-block;border:1px solid {color};background:{bg};'
            f'color:{color};padding:1px 6px;font-size:10px;font-weight:900;line-height:17px;'
            f'font-family:{FONT_MONO};box-shadow:2px 2px 0 #000;white-space:nowrap;">{label}</span>')


def _signal_meter(value, maximum, color=C_CYAN, cells=5):
    """用实体像素格显示信号强度，不依赖 CSS 渐变或外部图标。"""
    maximum = max(1, int(maximum or 1))
    lit = max(1, min(cells, round(float(value or 0) / maximum * cells))) if value else 0
    return (f'<span style="color:{color};font-family:{FONT_MONO};font-size:10px;letter-spacing:1px;">'
            f'{"■" * lit}</span><span style="color:{C_ACCENT_SOFT};font-family:{FONT_MONO};'
            f'font-size:10px;letter-spacing:1px;">{"□" * (cells - lit)}</span>')


def _pixel_octopus(pixel=4):
    """纯 HTML 8-bit 章鱼图标；无需图片资源，PushPlus/微信可直接渲染。"""
    pattern = (
        "00111100",
        "01111110",
        "11211211",
        "11111111",
        "01111110",
        "01011010",
        "11011011",
        "10000001",
    )
    cells = []
    for row in pattern:
        tds = []
        for bit in row:
            bg = C_ACCENT if bit == "1" else (C_BG if bit == "2" else "")
            # bgcolor / width / height 是邮件客户端兼容性最高的表格像素写法，也比重复长 style 更省推送字数。
            bg_attr = f' bgcolor="{bg}"' if bg else ""
            tds.append(f'<td width="{pixel}" height="{pixel}"{bg_attr}>&nbsp;</td>')
        cells.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<table role="img" aria-label="章鱼像素图标" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;margin:0 auto;font-size:0;line-height:0;">'
            f'{"".join(cells)}</table>')

def _badge(text, kind="ok"):
    styles = {
        "ok":   (C_GREEN, C_UP_BG, C_GREEN),
        "warn": (C_AMBER, C_FLAT_BG, C_AMBER),
        "bad":  (C_RED, C_DOWN_BG, C_RED),
        "ai":   (C_LEMON, C_AI_BG, C_VIOLET),
    }
    color, bg, border = styles.get(kind, styles["ok"])
    dot = "◆" if kind == "ai" else "●"
    return (f'<span style="display:inline-block;border:1px solid {border};color:{color};'
            f'background:{bg};padding:1px 7px;margin-left:6px;font-size:10px;font-weight:900;'
            f'font-family:{FONT_MONO};letter-spacing:1px;line-height:17px;'
            f'box-shadow:2px 2px 0 #000;vertical-align:middle;'
            f'white-space:nowrap;">[{dot} {_esc(text)}]</span>')


_SECTION_ICON_META = {
    # 短线速查卡（2026-09-30 新增）：闪电 = 快进快出，短标签用交易员黑话 TL;DR 的孪生
    "SHORT CARD": ("⚡", "ACT-NOW", C_LEMON, C_AI_BG),
    "ECON CALENDAR": ("▦", "30-DAY", C_LEMON, C_FLAT_BG),
    "STRATEGY READ": ("◆", "STRAT", C_LEMON, C_AI_BG),
    "POLICY SHOCK": ("§", "POLICY", C_AMBER, C_FLAT_BG),
    "FED TREND": ("$", "FED", C_LEMON, C_AI_BG),
    "GEO TREND": ("◎", "GEO", C_MAGENTA, "#301226"),
    "QUANT STRATEGY": ("◆", "QUANT", C_LEMON, C_AI_BG),
    "AI READ": ("◆", "AI", C_LEMON, C_AI_BG),
    "QUANT POLICY": ("◉", "QUANT", C_AMBER, C_FLAT_BG),
    "MARKET REVIEW": ("▲", "MKT", C_GREEN, C_UP_BG),
    "HK GURU CHANNELS": ("▶", "TV", C_MAGENTA, "#301226"),
    "GLOBAL HEADLINES": ("▤", "NEWS", C_CYAN, "#092836"),
    "EASTMONEY WIRE": ("!", "WIRE", C_AMBER, C_FLAT_BG),
    "NEWS SENTIMENT": ("◆", "SENTI", C_MAGENTA, "#301226"),
    "MEDIA RISK": ("!", "RISK", C_RED, C_DOWN_BG),
    "DATA AUDIT": ("✓", "LOG", C_GREEN, C_UP_BG),
    "FORECAST": ("★", "TL;DR", C_LEMON, C_AI_BG),
    "SUMMARY": ("✓", "RECAP", C_GREEN, C_UP_BG),
    "TREND TRACKING": ("◉", "TREND", C_MAGENTA, "#301226"),
    "HK PROBABILITY": ("◈", "HK-PROB", C_MAGENTA, "#301226"),
    "LIQUIDITY FLOW": ("≈", "FLOW", C_CYAN, "#092836"),
    "WEEKLY FORECAST": ("◆", "WEEK-FX", C_LEMON, C_AI_BG),
    "SECTOR ROTATION": ("↻", "ROTATE", C_CYAN, "#092836"),
    # 申万一级行业轮动（2026-10-04 移植）：与港股板块轮动的 ↻/ROTATE 区分开
    "INDUSTRY ROTATION": ("◑", "INDUST", C_LEMON, C_FLAT_BG),
    # 情绪热点因子量化分析（2026-10-13 新增，2026-10-19 由「内地财经热点榜」更名）：
    # 18 家内地财经媒体的主题热度 + 情绪/风险因子榜，✦ = 热度
    "MAINLAND HOTLIST": ("✦", "SENT-HOT", C_AMBER, C_FLAT_BG),
    # 策略大类量化（2026-10-21 新增，图中 4 大类 6 细分）
    "STRATEGY OVERVIEW": ("▣", "STRAT-MAP", C_LEMON, C_AI_BG),
    "STRATEGY EQUITY": ("▲", "EQT-LONG", C_LEMON, C_UP_BG),
    "STRATEGY BOND": ("▬", "BOND", C_GREEN, C_UP_BG),
    "STRATEGY CTA": ("↗", "CTA", C_AMBER, C_FLAT_BG),
    "STRATEGY ARBITRAGE": ("◇", "ARB", C_CYAN, "#092836"),
    "POETRY & SEA": ("✦", "VERSE", C_CYAN, "#092836"),
}


def _section_visual(kicker):
    """返回栏目像素图标、短标签与强调色。"""
    return _SECTION_ICON_META.get(kicker, ("■", "DATA", C_ACCENT, C_UP_BG))


def _pixel_icon(kicker, size=44):
    """大尺寸栏目图标砖；ASCII/几何符号在微信字体回退时仍清晰。"""
    glyph, label, color, bg = _section_visual(kicker)
    glyph_size = max(20, round(size * 0.43))
    return (f'<table width="{size}" height="{size}" cellpadding="0" cellspacing="0" '
            f'style="width:{size}px;height:{size}px;border-collapse:collapse;border:1px solid {color};'
            f'background:{bg};box-shadow:4px 4px 0 #000;">'
            f'<tr><td align="center" valign="middle" style="padding:2px;color:{color};'
            f'font-family:{FONT_MONO};font-weight:900;line-height:1;">'
            f'<div style="font-size:{glyph_size}px;line-height:{glyph_size}px;">{glyph}</div>'
            f'<div style="font-size:8px;line-height:10px;letter-spacing:.5px;">{label}</div>'
            f'</td></tr></table>')


def _stacked_cells(headers, row, *, label_style=""):
    """把一行多列数据拆成「字段：内容」的竖排小块（单列排版的公共实现）。

    首列当标题，其余列逐行堆叠；只有真正的空单元格不出行——占位短横「—」照常
    保留，缺数据要看得见，不能被排版吞掉。标签只包一层 <b>，样式越省越好：
    微信正文有字数上限，逐格写内联样式会把一页推送顶爆。
    """
    parts = []
    first = row[0] if row else ""
    if str(first).strip():
        parts.append(f"<b>{first}</b>")
    for i in range(1, len(headers or [])):
        value = row[i] if i < len(row) else ""
        if not str(value).strip():
            continue
        label = _esc(str(headers[i])).strip()
        style = f' style="{label_style}"' if label_style else ""
        label_html = f"<b{style}>{label}</b> " if label else ""
        parts.append(f"{label_html}{value}")
    # <br> 换行比逐行 <div> 省十来个字符：微信一页推送有字数上限，宁可省标签。
    return "<br>".join(parts)


def _pixel_table(headers, rows, aligns=None, widths=None):
    """pixel 主题的数据表：多行多列表格展示（含表头行与多列数据行）。"""
    rows = [list(r) for r in (rows or [])]
    if not rows:
        return ""
    n = len(headers) if headers else len(rows[0])
    if n <= 0:
        return ""
    aligns = list(aligns or (["left"] + ["right"] * (n - 1)))
    aligns = (aligns + ["left"] * n)[:n]
    widths = (list(widths) + [None] * n)[:n] if widths else [None] * n

    def _width_css(i):
        return f"width:{widths[i]};" if widths[i] else ""

    def _width_attr(i):
        return f' width="{widths[i]}"' if widths[i] else ""

    # 表格内文字：pixel 终端字号阶梯同样整体收一号（表头 10→9、表身 11→10），且一律不加粗。
    head = "".join(
        f'<td{_width_attr(i)} align="{aligns[i]}" style="{_width_css(i)}padding:3px 5px;'
        f'border-bottom:1px solid {C_ACCENT};'
        f'font-size:{PIXEL_FS_GRID_HEAD}px;font-weight:{GZ_W_TABLE};color:{C_CYAN};letter-spacing:.5px;'
        f'font-family:{FONT_MONO};text-align:{aligns[i]};">{_esc(h)}</td>'
        for i, h in enumerate(headers or []))
    body = []
    for row in rows:
        body.append("<tr>" + "".join(
            f'<td{_width_attr(i)} align="{aligns[i]}" valign="top" style="{_width_css(i)}padding:3px 5px;'
            f'border-bottom:1px solid {C_HAIR};font-size:{PIXEL_FS_GRID}px;color:{C_INK};'
            f'line-height:1.5;font-family:{FONT_MONO};text-align:{aligns[i]};">'
            f'{_table_text(row[i]) if i < len(row) else ""}</td>' for i in range(n)) + "</tr>")
    head_row = f"<tr>{head}</tr>" if headers else ""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="width:100%!important;border-collapse:collapse;table-layout:fixed;'
            f'font-weight:{GZ_W_TABLE};">'
            f'{head_row}{"".join(body)}</table>')


def _pixel_panel(title, body, color=C_CYAN, icon="■"):
    """AI 等重点内容使用的 8-bit 面板：高对比标题条 + 硬边框。"""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'margin-top:12px;border:1px solid {color};background:#0C1122;box-shadow:4px 4px 0 #000;">'
            f'<tr><td style="padding:5px 9px;background:{color};color:{C_BG};font-size:10px;'
            f'font-weight:900;font-family:{FONT_MONO};letter-spacing:1px;">{icon} {title}</td></tr>'
            f'<tr><td style="padding:8px 10px;">{body}</td></tr></table>')


def _alert(text, color=C_AMBER, bg=None):
    bg_color = bg or "#1A1E33"
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'margin-bottom:10px;border:1px solid {color};background:{bg_color};'
            f'box-shadow:4px 4px 0 #000;">'
            f'<tr><td style="padding:8px 10px;font-size:11px;color:{color};font-weight:900;'
            f'font-family:{FONT_MONO};line-height:1.6;letter-spacing:.5px;">'
            f'[ ! ALERT ]&nbsp;{text}</td></tr></table>')

def _ledger_table(rows, pad):
    # 账本式双列表（行情 / KV）：表格内文字缩小一号（12→11）并取消数值加粗，只留颜色区分。
    html = (f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;font-weight:{GZ_W_TABLE};">')
    for label, value, *color in rows:
        val_color = color[0] if color else C_INK
        html += (f'<tr><td style="padding:{pad} 0;border-bottom:1px solid {C_HAIR};'
                 f'font-size:{PIXEL_FS_LEDGER}px;color:{C_INK};vertical-align:top;line-height:1.5;'
                 f'font-family:{FONT_MONO};" '
                 f'width="46%">{_table_text(label)}</td>'
                 f'<td style="padding:{pad} 0;border-bottom:1px solid {C_HAIR};'
                 f'font-size:{PIXEL_FS_LEDGER}px;font-weight:{GZ_W_TABLE};color:{val_color};text-align:right;'
                 f'line-height:1.5;font-variant-numeric:tabular-nums;'
                 f'font-family:{FONT_MONO};" width="54%">{_table_text(value)}</td></tr>')
    return html + '</table>'

def _data_table(rows):
    return _ledger_table(rows, "5px")

def _mini_table(rows):
    return _ledger_table(rows, "4px")

def _note(text):
    """像素主题的口径脚注：精简排版（2026-09-27）起不再输出说明性文字。"""
    return ""

def _subsection(text):
    return (f'<div style="border-top:1px solid {C_ACCENT_SOFT};margin-top:12px;padding:8px 0 2px;'
            f'font-size:12px;font-weight:900;color:{C_CYAN};letter-spacing:1px;'
            f'font-family:{FONT_MONO};text-transform:uppercase;">'
            f'<span style="color:{C_ACCENT};">▶</span> {text}</div>')

def _source_badge(item):
    if item.get("status") != "success":
        return _badge("OFFLINE", "bad")
    if item.get("snapshot"):
        return _badge("TODAY'S SNAPSHOT", "ok")
    if item.get("is_today"):
        return _badge("LIVE", "ok")
    return _badge(f"LAG {item.get('content_date') or '-'}", "warn")

def _item_row(icon, text, sub="", icon_color=C_ACCENT, row_bg="transparent", anchor=None):
    # 资讯行也是表格：正文 12→11、序号 11→10，并取消加粗（颜色仍区分序号与正文）。
    sub_html = (f'<div style="font-size:10px;color:{C_MUTED};letter-spacing:.3px;'
                f'padding-top:3px;line-height:1.6;font-family:{FONT_MONO};">{_table_text(sub)}</div>' if sub else "")
    anchor_attr = f' id="{_esc(anchor)}"' if anchor else ""
    return (f'<table width="100%" cellpadding="0" cellspacing="0"{anchor_attr} style="border-collapse:collapse;'
            f'font-weight:{GZ_W_TABLE};background:{row_bg};">'
            f'<tr><td width="32" valign="top" style="padding:8px 4px 8px 0;border-bottom:1px solid {C_HAIR};'
            f'font-size:{PIXEL_FS_ITEM_ICON}px;font-weight:{GZ_W_TABLE};color:{icon_color};line-height:1.6;'
            f'font-family:{FONT_MONO};">{_table_text(icon)}</td>'
            f'<td style="padding:8px 0;border-bottom:1px solid {C_HAIR};font-size:{PIXEL_FS_ITEM}px;'
            f'color:{C_INK};line-height:1.7;font-family:{FONT_MONO};">{_table_text(text)}{sub_html}</td></tr></table>')

def _headline_row(it, index=None):
    marker = f"{index:02d}" if isinstance(index, int) else "--"
    display = it.get("title") if isinstance(it, dict) else it
    sub = ""
    if isinstance(it, dict):
        parts = []
        if it.get("source"):
            parts.append(it["source"])
        if it.get("published_cst") and it["published_cst"] != "—":
            parts.append(it["published_cst"])
        sub = " | ".join(parts)
    anchor = f"h-gh-{index:02d}" if isinstance(index, int) else None
    return _item_row(f"[{marker}]", _esc(display[:120]), _esc(sub[:140]), anchor=anchor)

def _em_news_row(it, index=None):
    marker = f"{index:02d}" if isinstance(index, int) else "--"
    anchor = f"h-em-{index:02d}" if isinstance(index, int) else None
    if isinstance(it, dict):
        title = it.get("title") or ""
        sub = " :: ".join(x for x in (it.get("time", ""), it.get("summary", "")) if x)
        return _item_row(f"[{marker}]", _esc(title[:120]), _esc(sub[:110]), anchor=anchor)
    return _item_row(f"[{marker}]", _esc(it[:120]), anchor=anchor)

def _channel_block(ch, ch_idx=None):
    """渲染单个港股频道；ch_idx 为正文展示序号（1-based），用于风险引用锚点。"""
    name = _esc(ch.get("name", "?"))
    desc = _esc(ch.get("desc", ""))
    url = _esc(ch.get("url", ""))
    videos = ch.get("videos") or []
    if not videos:
        note = _esc(ch.get("note") or "OFFLINE :: NO SIGNAL [暂缺]")
        return (f'<div style="margin:12px 0;border:1px solid {C_FAINT};background:{C_ZEBRA};'
                f'padding:10px 12px;box-shadow:4px 4px 0 #000;">'
                f'<div style="font-size:12px;font-weight:900;color:{C_FAINT};font-family:{FONT_MONO};">[X {name} {_badge("暂缺", "bad")}]</div>'
                f'<div style="font-size:10px;color:{C_MUTED};padding-top:3px;font-family:{FONT_MONO};">{desc}</div>'
                f'<div style="font-size:10px;color:{C_MUTED};line-height:1.6;font-family:{FONT_MONO};margin-top:4px;">> {note}</div></div>')
    badge = _badge("LIVE", "ok") if ch.get("is_today") else _badge("ARCHIVE", "warn")
    messages = []
    top_n = videos[:CHANNEL_TOP_N]
    for vi, v in enumerate(top_n):
        title = _esc(v.get("title", "")[:110])
        pub = _esc(v.get("published_cst", ""))
        link = f'<a href="{_esc(v.get("url", "#"))}" style="color:{C_INK};text-decoration:none;border-bottom:1px dotted {C_ACCENT};">{title}</a>'
        bubble_bg = "#15182B" if vi % 2 == 0 else "#1A1E33"
        border_c = C_ACCENT if vi % 2 == 0 else C_CYAN
        label = ">> FEED" if vi % 2 == 0 else ">> UPDATE"
        new_tag = f' <span style="color:{C_ACCENT_MAGENTA};font-weight:900;background:#2A1320;border:1px solid {C_ACCENT_MAGENTA};padding:0 3px;">[NEW]</span>' if v.get("is_today") else ""
        anchor_attr = f' id="h-hk-{ch_idx:02d}-{vi + 1:02d}"' if isinstance(ch_idx, int) else ""
        messages.append((f'<table width="100%" cellpadding="0" cellspacing="0"{anchor_attr} style="border-collapse:collapse;margin-top:6px;"><tr><td align="left">'
                         f'<div style="display:block;max-width:100%;text-align:left;background:{bubble_bg};border:1px solid {border_c};'
                         f'padding:6px 8px;box-shadow:3px 3px 0 #000;font-size:11px;color:{C_INK};line-height:1.6;font-family:{FONT_MONO};">'
                         f'<div style="font-size:9px;font-weight:900;color:{border_c};letter-spacing:1px;">{label} :: {pub}{new_tag}</div>'
                         f'<div style="padding-top:3px;">> {link}</div></div></td></tr></table>'))
    return (f'<div style="margin:12px 0;border:1px solid {C_ACCENT};background:#0F1222;padding:10px 12px;box-shadow:6px 6px 0 #000;">'
            f'<div style="font-size:12px;font-weight:900;color:{C_ACCENT_DEEP};font-family:{FONT_MONO};">'
            f'<span style="display:inline-block;background:{C_ACCENT};color:#000;padding:0 4px;margin-right:6px;">CH</span>'
            f'<a href="{url}" style="color:{C_INK};text-decoration:none;">{name}</a> {badge}</div>'
            f'<div style="font-size:10px;color:{C_MUTED};padding:4px 0 2px;font-family:{FONT_MONO};">{desc} :: <b style="color:{C_CYAN};">[8-BIT FEED]</b></div>'
            f'{"".join(messages)}</div>')

def _status_footer(sources):
    lines = []
    for name, s in sources:
        if s.get("status") == "success":
            lines.append((_sq(C_GREEN, 8),
                          f'<b style="color:{C_INK};font-family:{FONT_MONO};">{_esc(name)}</b> {_source_badge(s)}'
                          f' <span style="color:{C_MUTED};font-family:{FONT_MONO};">@ {_esc(s.get("fetched_at", "—"))}</span>'))
        else:
            detail = _esc(s.get("error", "暂时不可用"))
            lines.append((_sq(C_RED, 8),
                          f'<b style="color:{C_INK};font-family:{FONT_MONO};">{_esc(name)}</b> [x FAIL] '
                          f'<span style="color:{C_MUTED};font-family:{FONT_MONO};">({detail}) @ {_esc(s.get("fetched_at", "—"))}</span>'))
    rows = "".join(
        f'<tr><td width="22" valign="top" style="padding:5px 0;border-bottom:1px solid {C_HAIR};font-family:{FONT_MONO};">{marker}</td>'
        f'<td style="padding:5px 0;border-bottom:1px solid {C_HAIR};font-size:11px;'
        f'color:{C_MUTED};line-height:1.7;font-family:{FONT_MONO};">{line}</td></tr>'
        for marker, line in lines)
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{rows}</table>'

def _report_meta(html):
    def g(name):
        m = re.search(rf'name="octopus-{name}" content="([^\"]+)"', html)
        return m.group(1) if m else None
    try:
        today_sources = int(g("today-sources") or 0)
    except (TypeError, ValueError):
        today_sources = 0
    try:
        total_sources = int(g("total-sources") or 0)
    except (TypeError, ValueError):
        total_sources = 0
    return {
        "date": g("report-date"),
        "generated_at": g("generated-at"),
        "today_sources": today_sources,
        "total_sources": total_sources,
    }

def _masthead_cell(label, value, value_color=C_INK, first=False):
    border = "" if first else f"border-left:1px solid {C_HAIR};"
    padding = "0" if first else "12px"
    return (f'<td width="33%" valign="top" style="padding:8px 0;{border}">'
            f'<div style="padding-left:{padding};">'
            f'<div style="font-size:8px;font-weight:900;color:{C_ACCENT};letter-spacing:1px;font-family:{FONT_MONO};">{label}</div>'
            f'<div style="font-size:11px;font-weight:900;color:{value_color};padding-top:3px;'
            f'font-family:{FONT_MONO};font-variant-numeric:tabular-nums;">{value}</div></div></td>')

def _section(num, kicker_en, title, content, badge_html="", caption=""):
    """栏目头使用独立大图标砖；AI 栏目以黄色关卡色单独强调。"""
    _, _, section_color, _ = _section_visual(kicker_en)
    badge_cell = (f'<td align="right" valign="middle" '
                  f'style="padding-left:6px;color:{C_MUTED};font-size:10px;font-family:{FONT_MONO};">'
                  f'{badge_html}</td>'
                  if badge_html else "")
    caption_html = (f'<div style="font-size:10px;color:{C_MUTED};letter-spacing:.3px;'
                    f'padding:7px 0 8px 56px;line-height:1.6;font-family:{FONT_MONO};">'
                    f'<span style="color:{section_color};">└─</span> {caption}</div>'
                    if caption else '<div style="padding-bottom:7px;"></div>')
    return f'''
<div style="border-top:1px solid {section_color};margin-top:28px;padding-top:12px;">
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
<tr>
<td width="52" valign="middle" style="padding-right:10px;">{_pixel_icon(kicker_en)}</td>
<td valign="middle">
<div style="font-family:{FONT_MONO};font-size:9px;font-weight:900;color:{section_color};letter-spacing:1px;line-height:1.3;">LVL {num} // {kicker_en}</div>
<div style="font-size:17px;font-weight:900;color:{C_ACCENT_DEEP};letter-spacing:.5px;padding-top:4px;line-height:1.35;font-family:{FONT_MONO};">{title}<span style="color:{section_color};">_</span></div>
</td>
{badge_cell}
</tr>
</table>
{caption_html}
{SECTION_BODY_MARK}{content}
</div>'''


# ============================================================
# GUIZANG 主题排版（简洁研报 · 微信单列）
# —— 白底、克制标题与宽留白；纯内联样式与表格布局，保持 PushPlus 兼容。
# ============================================================

def _quote_parts(market, label, precision=2):
    """主题无关的行情取值：(价格字符串, 涨跌幅 float|None)；缺失返回 (None, None)。"""
    quote = (market.get("quotes", {}) or {}).get(label)
    if not quote:
        return None, None
    try:
        price_str = f"{float(quote['price']):,.{precision}f}"
    except (TypeError, ValueError, KeyError):
        return None, None
    return price_str, _percent_number(quote.get("change_pct", 0))



def gz_trend_badge(value, compact=False):
    """涨跌：克莱因蓝 / 深灰 / 浅灰 + ▲▼■ 双编码，颜色只是辅助，不依赖红绿。"""
    pct = _percent_number(value)
    if pct is None:
        return f'<span style="color:{GZ_FAINT}">■ 暂缺</span>'
    if pct > 0:
        color, arrow, word = GZ_UP, "▲", "涨"
    elif pct < 0:
        color, arrow, word = GZ_DOWN, "▼", "跌"
    else:
        color, arrow, word = GZ_FLAT, "■", "平"
    if compact:
        label = f"{arrow} {pct:+.2f}%"
    elif pct == 0:
        label = f"{arrow} {word} 0.00%"
    else:
        label = f"{arrow} {word} {pct:+.2f}%"
    return f'<b style="color:{color}">{label}</b>'



def gz_meter(value, maximum, cells=5, lit=GZ_KLEIN, off=GZ_FAINT, size=None):
    """信号格：实心 / 空心即可读数，颜色只作辅助（微信可能忽略 letter-spacing）。"""
    maximum = max(1, int(maximum or 1))
    n = max(1, min(cells, round(float(value or 0) / maximum * cells))) if value else 0
    return (f'<b style="color:{lit}">{"●" * n}</b>'
            f'<span style="color:{off}">{"○" * (cells - n)}</span>')



def gz_badge(text, kind="ok", on_ink=False):
    """纯文字状态：只用一个颜色字，不用胶囊 / 底色 / nowrap。"""
    ink = {"ok": GZ_UP_INK, "warn": GZ_WARN_INK, "bad": GZ_DOWN_INK, "ai": GZ_NEON}
    plain = {"ok": GZ_UP, "warn": GZ_WARN, "bad": GZ_DOWN, "ai": GZ_NEON}
    color = (ink if on_ink else plain).get(kind, GZ_META)
    return f'<span style="color:{color}">{_esc(text)}</span>'



def gz_source_badge(item, on_ink=False):
    """来源状态徽标：成功 / 当天 / 非当天 / 快照，色彩只用克莱因蓝与灰。"""
    if item.get("status") != "success":
        return gz_badge("暂缺", "bad", on_ink)
    if item.get("snapshot"):
        return gz_badge("今日抓取", "ok", on_ink)
    if item.get("is_today"):
        return gz_badge("当天", "ok", on_ink)
    return gz_badge(f"非当天 {item.get('content_date') or '-'}", "warn", on_ink)



def gz_shell(inner, bg=None, pad="20px 0", hair=False, anchor=None, border_css=""):
    """轻量分块包装：只输出 padding（+可选锚点 / 上边线）与显式正文色，不再套表格外壳。

    bg 仅为兼容旧调用保留（整页统一真白底 #FFFFFF，无需逐块再写背景色）。
    """
    attr = f' id="{_esc(anchor)}"' if anchor else ""
    hair_css = f"border-top:1px solid {GZ_HAIR};" if hair else ""
    if not pad and not hair_css and not border_css:
        return f'<div{attr} style="color:{GZ_INK}">{inner}</div>' if attr else inner
    return f'<div{attr} style="padding:{pad};color:{GZ_INK};{hair_css}{border_css}">{inner}</div>'



def _gz_missing(text="■ 数据暂缺"):
    return f'<span style="color:{GZ_FAINT}">{text}</span>'



def _gz_num(text):
    """关键数值：克莱因蓝加粗，是一眼能看到的重点。"""
    return f'<b style="color:{GZ_KLEIN}">{text}</b>'



# 表格内文字的「非加粗」归一（2026-10-23 用户要求：表格内文字缩小一号 + 不加粗）。
# 微信 / PushPlus 会清洗 <style> 块，只保留内联样式，所以不能用一条 CSS 规则统一处理，
# 只能在**表格单元格内容**这一层把粗体标记与粗体字重就地改写：
#   · <b> / <strong> → <span>（颜色、字号等其他内联样式原样保留）；
#   · font-weight:600/700/800/900/bold/bolder → font-weight:400（500 及以下视为常规，不动）。
# 只作用于数据表 / KV 表 / 资讯表 / AI 结论表的单元格，不动刊头、栏目标题、
# 徽标与正文段落（它们不在表格里，或属于版面装饰）。
_TABLE_BOLD_WEIGHT_RE = re.compile(r"font-weight:\s*(?:600|700|800|900|bold|bolder)")
_TABLE_BOLD_TAG_RE = re.compile(r"<(/?)(b|strong)(?=[\s>/])", re.IGNORECASE)


def _table_text(html):
    """表格单元格文字统一为常规字重（非加粗），其余内联样式保持不变。"""
    if not html:
        return html
    text = str(html)
    if "<" not in text:
        return text
    text = _TABLE_BOLD_TAG_RE.sub(lambda m: f"<{m.group(1)}span", text)
    return _TABLE_BOLD_WEIGHT_RE.sub(f"font-weight:{GZ_W_TABLE}", text)



def _gz_flow_rows(pairs, headers=None):
    """微信正文的多行双列表：左侧项目，右侧内容（仅 1 行或显式传表头时自动带表头行，确保多行多列）。"""
    pairs = list(pairs or [])
    if not pairs:
        return ""
    rows = []
    if headers or len(pairs) == 1:
        h0 = _esc(headers[0]) if headers and len(headers) >= 1 else "项目"
        h1 = _esc(headers[1]) if headers and len(headers) >= 2 else "内容"
        rows.append(f'<tr><td width="28%" valign="top" style="border-bottom:1px solid {GZ_HAIR};'
                    f'color:{GZ_FAINT}">{h0}</td>'
                    f'<td valign="top" style="border-bottom:1px solid {GZ_HAIR};'
                    f'color:{GZ_FAINT}">{h1}</td></tr>')
    for label, value in pairs:
        rows.append(f'<tr><td width="28%" valign="top" style="border-bottom:1px solid {GZ_HAIR};'
                    f'color:{GZ_META}">{_table_text(label or "")}</td>'
                    f'<td valign="top" style="border-bottom:1px solid {GZ_HAIR};'
                    f'color:{GZ_INK}">{_table_text(value)}</td></tr>')
    return (f'<table width="100%" cellpadding="3" cellspacing="0" '
            f'style="width:100%!important;font-size:{GZ_FS_TABLE}px;font-weight:{GZ_W_TABLE};'
            f'line-height:1.45;table-layout:fixed;word-break:break-word">'
            f'{"".join(rows)}</table>')


def gz_data_table(headers, rows, aligns=None, kv=False, row_anchors=None, widths=None):
    """归藏简洁表：多行多列表格展示；字号 / 颜色写一次在 <table> 上，单元格只写 padding 与对齐。"""
    rows = [list(r) for r in (rows or [])]
    if not rows:
        return ""
    n = len(headers) if headers else len(rows[0])
    if n <= 0:
        return ""
    if kv and n == 2:
        return _gz_flow_rows([(r[0] if r else "", r[1] if len(r) > 1 else "") for r in rows],
                             headers=headers)
    if aligns is None:
        aligns = ["left"] + ["right"] * (n - 1) if n > 1 else ["left"]
    aligns = (list(aligns) + ["left"] * n)[:n]
    widths = (list(widths) + [None] * n)[:n] if widths else [None] * n
    anchors = list(row_anchors or [])
    while len(anchors) < len(rows):
        anchors.append(None)
    # 表级默认对齐（左/右二选一）按「谁要写的单元格更少」定，表头固定左对齐也计入成本：
    # 多数表是「首列文字 + 其余数字右对齐」，选右默认只需给首列补 left，比逐行补 right 省一半。
    def _align_cost(default):
        cost = 0
        if default != "left" and headers:
            cost += len(headers) * 18                     # 表头固定左对齐，逐格补 text-align
        cost += sum(18 for a in aligns if a != default) * len(rows)   # 每行都要重复写
        if default == "right" and any(a != default for a in aligns):
            cost += 17                                    # 表级 text-align:right;
        return cost
    default_align = "right" if _align_cost("right") < _align_cost("left") else "left"

    def _cell(html, i, *, head=False, anchor=None):
        css = []
        if head:
            css.append(f"color:{GZ_FAINT}")
            if default_align != "left":
                css.append("text-align:left")
        elif aligns[i] != default_align:
            css.append(f"text-align:{aligns[i]}")
        attr = f' id="{_esc(anchor)}"' if anchor else ""
        style = f' style="{";".join(css)}"' if css else ""
        return f"<td{attr}{style}>{_table_text(html)}</td>"

    trs = []
    if headers:
        trs.append("<tr>" + "".join(
            _cell(_esc(h), i, head=True) for i, h in enumerate(headers)) + "</tr>")
    for ri, row in enumerate(rows):
        trs.append("<tr>" + "".join(
            _cell(row[i] if i < len(row) else "", i,
                  anchor=(anchors[ri] if i == 0 else None)) for i in range(n)) + "</tr>")
    align_css = f"text-align:{default_align};" if default_align == "right" else ""
    cols = ('<colgroup>' + "".join(
        f'<col style="width:{widths[i]}">' if widths[i] else "<col>"
        for i in range(n)) + "</colgroup>") if any(widths) else ""
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="width:100%!important;border-collapse:separate;'
        f'border-spacing:5px 2px;{align_css}font-size:{GZ_FS_TABLE}px;font-weight:{GZ_W_TABLE};'
        f'line-height:1.45;color:{GZ_INK}">'
        f'{cols}{"".join(trs)}</table>'
    )



def gz_kv_table(pairs):
    """多行键值：逐行「灰标签 · 值」，避免一条数据一张卡。"""
    pairs = [(a, b) for a, b in (pairs or [])]
    if not pairs:
        return ""
    return _gz_flow_rows(pairs)



def gz_note(text):
    """脚注：更小更浅，保持可读但不抢正文。

    入门版（PLAIN）不输出脚注：全仓脚注都是口径说明 / 数据来源 / 折叠披露这类
    「说明文字、过程文字」（与像素主题 2026-09-27 起的 _note 同一处理）；
    --notes / --full 时照常输出。
    """
    if PLAIN() or not text:
        return ""
    return (f'<div style="padding:4px 0;color:{GZ_FAINT};'
            f'font-size:{GZ_FS_META}px">{text}</div>')



def gz_subsection(text):
    """子标题：灰色小号大写 + 一条细分隔线，归藏式的「轻层级」。"""
    return f'<div style="margin-top:12px;color:{GZ_META};font-weight:700">{text}</div>'



def gz_rowline(label_html, right_html, pad="8px"):
    """兼容旧调用：单行键值并入行式键值排版。"""
    return gz_kv_table([(label_html, right_html)])



def gz_table(rows_html):
    """兼容旧调用：内容已是完整分块时原样拼接。"""
    return rows_html or ""



def gz_rows(rows_html):
    """每一行都已是独立分块，拼接即可。"""
    return rows_html or ""


def _gz_quote_row(label, price_str, pct):
    if price_str is None:
        miss = _gz_missing()
        return [_esc(label), miss, miss]
    badge = gz_trend_badge(pct) if pct is not None else _gz_missing()
    return [_esc(label), _gz_num(price_str), badge]


def gz_market_row(label, price_str, pct):
    """兼容旧调用：单行行情并入三列表。"""
    return gz_data_table(["名称", "最新价", "涨跌"], [_gz_quote_row(label, price_str, pct)])


def _market_block_caption(market, title, specs):
    """子块标题追加数据日期：「A股四指数 · 截至 09-28」；组内日期不一致写区间，滞后标出。"""
    note = _market_asof_note(market, [(label, label) for label, _ in specs])
    if not note:
        return title
    return f"{title} · {note.strip('（）')}"


def _market_block_date(market, specs):
    """子块标题所用的日期（YYYY-MM-DD，取股票品种最新一天）；无日期返回 None。"""
    quotes = (market or {}).get("quotes") or {}
    core = [quotes[l]["as_of"] for l, _ in specs
            if _market_group_of(l) not in MARKET_LAG_EXEMPT_GROUPS
            and isinstance(quotes.get(l), dict) and quotes[l].get("as_of")]
    return max(core) if core else None


def _market_row_label(market, label, block_date=None):
    """品种名后缀：落后于最新交易日的写日期；商品期货日期与子块不同也写日期；
    由东方财富回补的标「东财」。"""
    q = ((market or {}).get("quotes") or {}).get(label) or {}
    suffix = []
    if q.get("as_of") and (label in (market or {}).get("lagging", {})
                           or (block_date and _market_group_of(label) in MARKET_LAG_EXEMPT_GROUPS
                               and q["as_of"] != block_date)):
        suffix.append(_asof_short(q["as_of"]))
    if q.get("via") == "eastmoney":
        suffix.append("东财")
    return f"{label}（{'·'.join(suffix)}）" if suffix else label


# ------------------------------------------------------------
# 【及时秋刀鱼】AI 行情复盘（2026-09-30 按用户要求合并原「行情速览」+「全球大盘全景复盘」）
#   两栏重复的数字只保留一份：
#     · 原全景「全球指数概览（Yahoo 报价）」= 道指 / 标普 / 纳指 / 恒指 / 恒科，
#       与报价栏「全球与美股」「港股双指数」逐项完全相同（同一次 Yahoo 抓取的同一份
#       快照）→ 整块删除；
#     · 原全景「指数表现」（东财八大宽基）与报价栏「A股四指数」（Yahoo，含东财回补）
#       有四个指数重复 → 并成一张 A股指数表，同名指数只出一行。
#   合并不丢任何数据：成交额、东财独有宽基（北证50 / 沪深300 / 上证50 / 中证500）、
#   涨跌家数、成交额环比、南北向资金、板块热力全部保留；抓取 / 审计 / 推送门禁不变。
# ------------------------------------------------------------
MARKET_REVIEW_A_SHARE_SPECS = [("上证指数", 2), ("深证成指", 2), ("创业板指", 2), ("科创50", 2)]
MARKET_REVIEW_GLOBAL_SPECS = [("道琼斯指数", 0), ("标普500", 0), ("纳斯达克", 0),
                              ("WTI 原油", 2), ("微软 MSFT", 2), ("Meta META", 2)]
MARKET_REVIEW_HK_SPECS = [("恒生指数", 2), ("恒生科技", 2)]


def _market_review_pan_indices(pan):
    """东财全景的指数行按名称索引（缺名称 / 缺价的行忽略，不编造）。"""
    out = {}
    for row in (pan or {}).get("indices") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if name and row.get("price") is not None:
            out[name] = row
    return out


def _market_review_ashare_rows(market, pan):
    """A股指数合并行（主题无关）：同名指数只出一行，数字取更新的一方。

    返回 [{"label", "price_str", "pct", "amount", "via"}, ...]：
      · Yahoo 报价与东财「指数表现」都有的四个指数，按 _reconcile_market_snapshot 同一
        口径「日期新者胜」：东财行情日（content_date）比 Yahoo 的 as_of 新时用东财价并
        标「（东财）」，否则用 Yahoo 价（保留原「滞后 / 东财回补」后缀）；
      · Yahoo 缺某个指数时用东财同一次抓取的值补上，不出空行；
      · 东财独有的宽基（北证50 / 沪深300 / 上证50 / 中证500）按 spec 顺序补在后面；
      · 成交额只有东财有，取到就带上（两路都在时同一行里显示）。
    """
    pan_rows = _market_review_pan_indices(pan)
    pan_date = str((pan or {}).get("content_date") or "")[:10]
    block_date = _market_block_date(market, MARKET_REVIEW_A_SHARE_SPECS)
    rows, seen = [], set()
    for label, precision in MARKET_REVIEW_A_SHARE_SPECS:
        seen.add(label)
        quote = ((market or {}).get("quotes") or {}).get(label) or {}
        price_str, pct = _quote_parts(market or {}, label, precision)
        as_of = str(quote.get("as_of") or "")[:10]
        row = pan_rows.get(label)
        use_pan = bool(row) and (price_str is None or (pan_date and as_of and pan_date > as_of))
        if use_pan:
            rows.append({"label": f"{label}（东财）",
                         "price_str": f'{float(row["price"]):,.{precision}f}',
                         "pct": _percent_number(row.get("chg_pct")),
                         "amount": row.get("amount"), "via": "eastmoney"})
        elif price_str is not None:
            rows.append({"label": _market_row_label(market, label, block_date),
                         "price_str": price_str, "pct": pct,
                         "amount": (row or {}).get("amount"), "via": quote.get("via")})
        # 两路都没有 → 缺失品种不出「数据暂缺」行
    order = {name: i for i, (_, name) in enumerate(PANORAMA_INDEX_SPECS)}
    for name in sorted(set(pan_rows) - seen, key=lambda n: order.get(n, len(order))):
        seen.add(name)
        row = pan_rows[name]
        rows.append({"label": name, "price_str": f'{float(row["price"]):,.2f}',
                     "pct": _percent_number(row.get("chg_pct")),
                     "amount": row.get("amount"), "via": "eastmoney"})
    return rows


def _market_review_ashare_caption(market, pan):
    """A股指数子块标题：优先用报价侧的「截至 / 滞后」标注；整块都是东财口径时用东财行情日。

    两路口径混在一起、而报价侧又没有日期时，标题不写日期（各行自己标「（东财）」），
    绝不给读者一个对不上号的截止日期。
    """
    rows = _market_review_ashare_rows(market, pan)
    cap = _market_block_caption(market or {}, "A股指数", MARKET_REVIEW_A_SHARE_SPECS)
    if " · " in cap or not rows:
        return cap
    pan_date = str((pan or {}).get("content_date") or "")[:10]
    if pan_date and all(r.get("via") == "eastmoney" for r in rows):
        return f"A股指数 · 截至 {_asof_short(pan_date)}（东财）"
    return cap


def gz_market_section(market, pan=None):
    """guizang 版行情报价：全球与美股 / A股指数 / 港股双指数（缺失品种不出行）。

    pan（东财 A股全景，可选）：给了就把 A股指数与东财「指数表现」并成一张表——多出
    成交额一列与四个东财独有宽基，同名指数只出一行，不再有两栏数字互相打架。
    """
    def _block(title, specs):
        rows = []
        block_date = _market_block_date(market, specs)
        for label, precision in specs:
            price_str, pct = _quote_parts(market, label, precision)
            if price_str is None:
                continue          # 缺失品种不出「数据暂缺」行
            rows.append(_gz_quote_row(_market_row_label(market, label, block_date), price_str, pct))
        if not rows:
            return ""
        return (gz_subsection(_esc(_market_block_caption(market, title, specs)))
                + gz_data_table(["名称", "最新价", "涨跌"], rows))

    def _ashare_block():
        rows = _market_review_ashare_rows(market, pan)
        if not rows:
            return ""
        has_amount = any(r.get("amount") for r in rows)
        table = []
        for r in rows:
            badge = gz_trend_badge(r["pct"]) if r["pct"] is not None else _gz_missing()
            cells = [_esc(r["label"]), _gz_num(r["price_str"]), badge]
            if has_amount:
                cells.append(_format_amount(r["amount"]) if r.get("amount") else "—")
            table.append(cells)
        headers = ["指数", "最新价", "涨跌"] + (["成交额"] if has_amount else [])
        return (gz_subsection(_esc(_market_review_ashare_caption(market, pan)))
                + gz_data_table(headers, table))

    return (
        _block("全球与美股", MARKET_REVIEW_GLOBAL_SPECS)
        + _ashare_block()
        # 2026-09-09 补缺：恒生双指数早已在抓取（Yahoo），但从未在报价栏展示；
        # 动能明细表移除后，这里是它们唯一的展示位置。
        + _block("港股双指数", MARKET_REVIEW_HK_SPECS)
    )


def gz_panorama_block(pan, with_indices=True, merge_flow=""):
    """guizang 版 A股全景：指数表现 / 涨跌家数 / 成交额 / 南北向 / 板块热力，均用表格。

    with_indices=False（合并进「AI 行情复盘」时的用法）：指数表已由 gz_market_section
    并入 A股指数一块，这里不再重复出一份。

    merge_flow 非空（见 SUB_MERGE_ENABLED）：南北向成交总额已在该栏目展开，
    这里只留一行「↳ 同子栏合并」指针，不再重复同一批数字。
    """
    parts = []

    indices = pan.get("indices") or []
    if indices and with_indices:
        rows = []
        for idx in indices:
            pct = idx.get("chg_pct")
            badge = gz_trend_badge(pct) if pct is not None else _gz_missing()
            amt = _format_amount(idx["amount"]) if idx.get("amount") else "—"
            rows.append([_esc(idx["name"]), _gz_num(f'{idx["price"]:,.2f}'), badge, amt])
        parts.append(gz_subsection("指数表现") + gz_data_table(
            ["指数", "最新价", "涨跌", "成交额"], rows))

    b = pan.get("breadth")
    if b:
        b_rows = []
        for exch, p in (b.get("markets") or {}).items():
            b_rows.append([
                _esc(exch),
                f'{p["up"]:,} 家',
                f'{p["down"]:,} 家',
                f'{(p.get("flat") or 0):,} 家',
            ])
        b_rows.append([
            "沪深京合计",
            f'{b["up"]:,} 家',
            f'{b["down"]:,} 家',
            f'{b["flat"]:,} 家',
        ])
        parts.append(
            gz_subsection("涨跌家数")
            + gz_data_table(["市场", "上涨", "下跌", "平盘"], b_rows)
            + gz_kv_table([(
                "涨跌比 / 情绪定调",
                (f'{b["ratio"]:.2f}' if b.get("ratio") is not None else "—")
                + f' · {_esc(b.get("mood") or "—")}',
            )])
        )

    t = pan.get("turnover")
    if t:
        chg = t.get("chg_pct")
        chg_html = f' 较上一交易日 {gz_trend_badge(chg)}' if chg is not None else ""
        t_pairs = []
        # 沪 / 深 / 京市成交额就是上证指数 / 深证成指 / 北证50 的 f6 成交额：指数表已并入
        # 「AI 行情复盘」的 A股指数一列时，这三行是同一批数字，不再重复出一份（只留合计与环比）。
        if with_indices or not any(i.get("amount") for i in indices):
            for exch, amt in (t.get("by_market") or {}).items():
                t_pairs.append((f"{exch}市成交额", _format_amount(amt)))
        t_pairs.append(("沪深京成交额合计", _format_amount(t["total"]) + chg_html))
        if t.get("prev_total"):
            t_pairs.append(("上一交易日合计（沪深京）", _format_amount(t["prev_total"])))
        parts.append(gz_subsection("成交额") + gz_kv_table(t_pairs))

    north = pan.get("north") or {}
    if north:
        flow_pairs = []
        if north.get("available") and north.get("amount_yi") is not None:
            flow_pairs.append((f"北向成交总额（{north.get('date') or '—'}）",
                               _gz_num(f'{north["amount_yi"]:,.2f} 亿元')))
        if north.get("south_available") and north.get("south_amount_yi") is not None:
            flow_pairs.append((f"南向成交总额（{north.get('south_date') or north.get('date') or '—'}）",
                               _gz_num(f'{north["south_amount_yi"]:,.2f} 亿元')))
        if flow_pairs:
            if merge_flow and SUB_MERGE_ENABLED:
                # 同子栏合并：成交总额已在 merge_flow 栏目（资金流动性）展开 —— 这里只留指针。
                parts.append(gz_subsection("南北向资金（前一收盘）") + gz_kv_table(
                    [(SUB_MERGE_POINTER,
                      sub_merge_pointer_text(SUB_MERGE_NOTE_FLOW, merge_flow))]))
            else:
                parts.append(gz_subsection("南北向资金（前一收盘）") + gz_kv_table(flow_pairs))

    sec = pan.get("sectors") or {}
    heat_n = LITE("sector_heat")
    for title, key in (("板块热力 · 领涨行业 TOP", "leading"),
                       ("板块热力 · 领跌行业 TOP", "lagging")):
        all_items = sec.get(key) or []
        items = all_items[:heat_n] if heat_n else all_items
        if items:
            if len(all_items) > len(items):
                title = f"{title[:len(title) - 3]}{len(items)}"
            s_rows = []
            for it in items:
                badge = gz_trend_badge(it.get("chg_pct"))
                inflow = _format_amount(it["main_inflow"]) if it.get("main_inflow") is not None else "—"
                lead = _esc(it["lead_stock"]) if it.get("lead_stock") else "—"
                lead_pct = it.get("lead_stock_pct")
                if lead != "—" and lead_pct is not None:
                    lead = f"{lead} {lead_pct:+.2f}%"
                s_rows.append([_esc(it["name"]), badge, inflow, lead])
            parts.append(gz_subsection(title) + gz_data_table(
                ["板块", "涨跌", "主力净流入", "领涨股"], s_rows))

    return "".join(parts)


def gz_market_review(market, pan, merge_flow=""):
    """guizang 版【及时秋刀鱼】AI 行情复盘：逐项报价 + A股全景，重复数字只出一份。

    合并前「全球指数概览」与「A股四指数 / 指数表现」在两栏各出一遍；合并后全球与港股
    指数只在报价块出现一次，A股八大宽基（含成交额）只在 A股指数表出现一次。
    merge_flow 非空时，南北向资金也走同一套「同子栏合并」口径（见 SUB_MERGE_ENABLED）。
    """
    return (gz_market_section(market, pan)
            + gz_panorama_block(pan or {}, with_indices=False, merge_flow=merge_flow))


def _cal_gz_cells(day_label, t_plus, item, first=False):
    """guizang 日历表的一行：日期（当天首行附 T+n）/ 时间 / 星号 + 地区 + 时间点。

    墨水屏只有黑白：重要度用「星号数量 + 字重 + 灰阶」区分，不依赖颜色。
    """
    item = item if isinstance(item, dict) else {}
    imp = max(1, min(3, int(item.get("imp") or 1)))
    day_html = ""
    if first:
        day_html = f'<b style="color:{GZ_INK}">{_esc(day_label)}</b>'
        when = _cal_countdown(t_plus)
        if when:
            day_html += (f'<div style="color:{GZ_META};'
                         f'padding-top:2px">{_esc(when)}</div>')
    star_html = (f'<b style="color:{GZ_INK}">{"★" * imp}</b>' if imp >= 3
                 else f'<span style="color:{GZ_INK if imp == 2 else GZ_META}">{"★" * imp}</span>')
    city = str(item.get("city") or "").strip()
    city_html = f'<span style="color:{GZ_META}">{_esc(city)}</span> · ' if city else ""
    body = (f'{star_html} '
            f'{city_html}{_esc(_cal_item_text(item))}')
    return [day_html, _esc(str(item.get("time") or "—")), body]


def gz_calendar_block(res, date_str=None):
    """黑白研报版「时间节点」：窗口摘要表（全窗口口径，一条不删）+ 近端日历表。

    精简模式（默认）表格只列今明 + 近端 ★★★，被折叠的条数在表下如实披露；
    --full / OCTOPUS_LITE=0 回到全窗口逐日表。
    """
    digest, rows, disclosure = _calendar_table_rows(res, _cal_gz_cells, date_str=date_str)
    parts = []
    pairs = digest.get("pairs") or []
    if pairs:
        parts.append(gz_subsection("窗口摘要"))
        parts.append(gz_data_table(None, [[_esc(a), _esc(b)] for a, b in pairs],
                                   aligns=("left", "left"), kv=True,
                                   widths=("26%", "74%")))
    if rows:
        label = _calendar_table_label()
        if disclosure and PLAIN():
            label += f" · {disclosure}"
        parts.append(gz_subsection(_esc(label)))
        parts.append(gz_data_table(["日期", "时间", "影响经济的时间点"], rows,
                                   aligns=("left", "left", "left"),
                                   widths=("17%", "13%", "70%")))
    if disclosure and not PLAIN():
        parts.append(gz_note(_esc(disclosure)))
    return "".join(parts)



def _gz_news_card(marker, title, sub="", anchor=None):
    """资讯文字按序号、内容两列展示，适配微信单列屏幕。"""
    attr = f' id="{_esc(anchor)}"' if anchor else ""
    meta = f'<br><small style="color:{GZ_FAINT}">{sub}</small>' if sub else ""
    return (f'<table width="100%" cellpadding="0" cellspacing="0"{attr} '
            f'style="width:100%!important;border-collapse:collapse;'
            f'font-size:{GZ_FS_TABLE}px;font-weight:{GZ_W_TABLE};color:{GZ_INK};">'
            f'<tr><td width="32" valign="top" style="padding:6px 4px;'
            f'border-bottom:1px solid {GZ_HAIR_SOFT};color:{GZ_META};">{_table_text(marker)}</td>'
            f'<td valign="top" style="padding:6px 4px;border-bottom:1px solid {GZ_HAIR_SOFT};'
            f'word-break:break-word;line-height:1.55;">{_table_text(title)}{_table_text(meta)}</td></tr></table>')


def gz_headline_row(it, index=None):
    marker = f"{index:02d}" if isinstance(index, int) else "—"
    display = it.get("title") if isinstance(it, dict) else it
    parts = []
    if isinstance(it, dict):
        if it.get("source"):
            parts.append(it["source"])
        if it.get("published_cst") and it.get("published_cst") != "—":
            parts.append(it["published_cst"])
    anchor = f"h-gh-{index:02d}" if isinstance(index, int) else None
    return _gz_news_card(marker, _esc(display[:120]), " · ".join(parts), anchor=anchor)


def gz_em_news_row(it, index=None):
    marker = f"{index:02d}" if isinstance(index, int) else "—"
    anchor = f"h-em-{index:02d}" if isinstance(index, int) else None
    if isinstance(it, dict):
        title = it.get("title") or ""
        summary = it.get("summary", "") or ""
        cut = LITE("em_summary")
        if cut and len(summary) > cut:
            # 精简模式：快讯摘要只留开头（标题已经把要点说完了），截断处标省略号
            summary = summary[:cut].rstrip(" ·，；") + "…"
        sub = " · ".join(x for x in (it.get("time", ""), summary) if x)
    else:
        title, sub = it, ""
    return _gz_news_card(marker, _esc(title[:120]), sub, anchor=anchor)


def gz_item_row(icon, text, sub="", icon_color=None, row_bg=None, anchor=None):
    marker = icon if icon else "—"
    return _gz_news_card(marker, text, sub, anchor=anchor)



def gz_channel_block(ch, ch_idx=None):
    """渲染单个港股频道；ch_idx 为正文展示序号（1-based），用于风险引用锚点。"""
    name = _esc(ch.get("name", "?"))
    desc = _esc(ch.get("desc", ""))
    url = _esc(ch.get("url", ""))
    videos = ch.get("videos") or []
    if not videos:
        note = _esc(ch.get("note") or "暂缺")
        return (f'<div style="padding:8px 0;color:{GZ_FAINT}">'
                f'<span style="color:{GZ_FAINT};font-weight:700">{name} · 暂缺</span>'
                f'<div style="color:{GZ_FAINT};font-size:{GZ_FS_META}px;padding-top:2px;'
                f'line-height:1.6">{desc} · {note}</div></div>')
    badge = gz_source_badge({"status": "success", "is_today": True}) if ch.get("is_today") else ""
    name_link = f'<a href="{url}" style="color:{GZ_KLEIN}">{name}</a>' \
        if url else name
    cards = []
    for vi, v in enumerate(videos[:CHANNEL_TOP_N], 1):
        title = _esc(v.get("title", "")[:110])
        pub = _esc(v.get("published_cst", ""))
        link = (f'<a href="{_esc(v.get("url", "#"))}" '
                f'style="color:{GZ_KLEIN}">{title}</a>')
        new_tag = f' <span style="color:{GZ_UP}">当天</span>' if v.get("is_today") else ""
        anchor = f"h-hk-{ch_idx:02d}-{vi:02d}" if isinstance(ch_idx, int) else None
        cards.append(_gz_news_card("", link + new_tag, pub, anchor=anchor))
    head = (f'<div style="padding:10px 0 2px;font-weight:700;color:{GZ_INK_STRONG};'
            f'line-height:1.5">{name_link}{" · " + badge if badge else ""}</div>')
    return head + "".join(cards)



def gz_status_footer(sources):
    """数据审计：来源 / 状态 / 抓取时间三列，缺失项如实点名。"""
    rows = []
    for name, s in sources:
        if s.get("status") == "success":
            rows.append([_esc(name), gz_source_badge(s),
                         f'<span style="color:{GZ_FAINT}">{_esc(s.get("fetched_at", "—"))}</span>'])
        else:
            detail = _esc(s.get("error", "暂时不可用"))
            rows.append([_esc(name), gz_badge("暂缺", "bad"),
                         f'<span style="color:{GZ_FAINT}">{detail} · '
                         f'{_esc(s.get("fetched_at", "—"))}</span>'])
    return gz_data_table(["来源", "状态", "抓取"], rows, aligns=("left", "left", "right"))



def gz_alert(text, color=None):
    """提示块：一条克莱因蓝（或指定色）竖线，不用底色。"""
    c = color or GZ_KLEIN
    return (f'<div style="margin:8px 0;padding:2px 0 2px 12px;'
            f'border-left:2px solid {c};color:{GZ_INK};line-height:1.8">{text}</div>')


def gz_masthead_cell(label, value, value_color=GZ_CREAM, first=False):
    """兼容旧调用：刊头已改为单列，此函数不再用于页面。"""
    return (f'<div style="font-size:{GZ_FS_META}px;color:{GZ_META_INK};padding-top:6px;">'
            f'{label} · <span style="color:{value_color};font-weight:700;">{value}</span></div>')



# 顶层块识别器：用于把正文块包装成微信兼容表格，并将子标题与首个内容块归组。
_GZ_ZEBRA_TAG_RE = re.compile(
    r'<!--.*?-->|<(/?)([a-zA-Z][a-zA-Z0-9]*)((?:"[^"]*"|\'[^\']*\'|[^>"\'])*)(/?)>',
    re.S,
)
_GZ_ZEBRA_VOID = frozenset((
    "br", "img", "hr", "col", "meta", "link", "input",
    "area", "base", "embed", "source", "track", "wbr",
))


def _gz_top_level_spans(html):
    """把归藏栏目的内容串按「顶层元素」切块，返回 ``[(start, end)]`` 坐标。

    生成器自产 HTML 标签必然配对，用一个深度计数器即可：深度归零即收一块。
    注释（<!--BODY--> 等推进标记）与顶层散落的空白/孤立 void 标签不计块，
    折叠进相邻块的坐标区间，保证拼接后一个字符都不丢。
    """
    spans = []
    depth = 0
    start = 0
    pending = 0          # 尚未归属任何块的前缀长度（空白/注释/void）
    for m in _GZ_ZEBRA_TAG_RE.finditer(html):
        if m.group(0).startswith("<!--"):
            if depth == 0:
                pending = m.end()
            continue
        closing, tag = m.group(1) == "/", m.group(2).lower()
        if tag in _GZ_ZEBRA_VOID or m.group(4) == "/":
            if depth == 0:
                if spans:
                    spans[-1] = (spans[-1][0], m.end())
                else:
                    pending = m.end()
            continue
        if not closing:
            if depth == 0:
                start = m.start()
            depth += 1
        else:
            depth = max(0, depth - 1)
            if depth == 0:
                spans.append((min(start, pending), m.end()) if pending < start
                             else (start, m.end()))
                pending = m.end()
    return spans


def _gz_content_table(inner, band):
    """将一个非表格内容块装进微信兼容的全宽表格，并以单元格留白清楚分段。"""
    stripped = (inner or "").strip()
    # 行情/资讯等已经是完整表格时直接保留，避免不必要的嵌套和推送体积膨胀。
    if stripped.lower().startswith("<table") and len(_gz_top_level_spans(stripped)) == 1:
        return inner
    background = GZ_ZEBRA if band % 2 else GZ_PAPER
    return (
        f'<table width="100%" cellpadding="8" cellspacing="0" bgcolor="{background}" '
        f'style="width:100%!important;border-collapse:collapse;table-layout:fixed;'
        f'background:{background};color:{GZ_INK};font-size:{GZ_FS_BODY}px;line-height:1.75;'
        f'word-break:break-word;overflow-wrap:break-word;">'
        f'<tr><td valign="top" style="border-bottom:1px solid {GZ_HAIR_SOFT};">'
        f'{inner}</td></tr></table>'
    )


def _gz_zebra_bands(content):
    """将栏目正文拆成清晰的全宽表格块，交替铺底并保留子标题与正文的归属关系。

    - 每个顶层内容块（键值段 / 说明 / 提示）放入全宽单列表格；原生数据表 / 资讯表不再嵌套；
    - 表格统一提供内边距、1.75 行高与浅色分隔，提升微信窄屏阅读节奏；
    - 子节标题并入紧随其后的首块，避免「标题与对应数据」被拆开；
    - 表外文字块以白底与浅灰/档案纸底交替，底色写在 table 上，兼容 PushPlus 清洗。
    """
    if not content:
        return content
    spans = _gz_top_level_spans(content)
    if not spans:
        # 也覆盖测试、插件或未来栏目传入的纯文本 HTML 片段，避免正文游离在表格之外。
        return _gz_content_table(content, 0) if content.strip() else content

    # 分组：子节标题与其后首块同表；颜色检测按样式属性识别，兼容 dossier 动态色盘。
    groups = []
    i = 0
    while i < len(spans):
        s, e = spans[i]
        chunk = content[s:min(e, s + 240)]
        is_subsection = (
            chunk.startswith("<div")
            and re.search(r'\bmargin-top\s*:\s*12px', chunk, re.I)
            and re.search(r'\bfont-weight\s*:\s*700', chunk, re.I)
        )
        if is_subsection and i + 1 < len(spans):
            groups.append((s, spans[i + 1][1]))
            i += 2
        else:
            groups.append((s, e))
            i += 1

    out = []
    cursor = 0
    band = 0
    for s, e in groups:
        gap = content[cursor:s]
        if gap.strip():
            out.append(_gz_content_table(gap, band))
            band += 1
        else:
            out.append(gap)                    # 空白 / 隐形推进注释原样保留
        out.append(_gz_content_table(content[s:e], band))
        band += 1
        cursor = e
    tail = content[cursor:]
    if tail.strip():
        out.append(_gz_content_table(tail, band))
    else:
        out.append(tail)
    return "".join(out)


def gz_section(num, kicker_en, title, content, badge_html="", caption=""):
    """归藏简洁栏目头：编号 + kicker（克莱因蓝）→ 标题（深灰黑）→ 徽标 / 口径。

    编号取代图标：不依赖任何远程图片，也不给单条消息增加几十 KB 的 SVG。
    """
    content = content or ""
    if content.lstrip().startswith("<tr"):
        # 栏目正文本身就是表格行：套一层数据表外壳，沿用表格字号与常规字重。
        content = (f'<table width="100%" cellpadding="0" cellspacing="0" '
                   f'style="width:100%!important;border-collapse:collapse;'
                   f'font-size:{GZ_FS_TABLE}px;font-weight:{GZ_W_TABLE};color:{GZ_INK}">'
                   f'{_table_text(content)}</table>')
    # 微信正文逐内容块表格化；数据表保留原结构，文字说明也有稳定内边距与分段。
    content = _gz_zebra_bands(content)
    meta_bits = [x for x in (badge_html, caption) if x]
    meta = (f'<div style="color:{GZ_FAINT};font-size:{GZ_FS_META}px;'
            f'padding-top:4px">{" · ".join(meta_bits)}</div>') if meta_bits else ""
    head = (
        f'<div style="padding:28px 0 0;border-top:1px solid {GZ_HAIR};color:{GZ_INK};background:{GZ_PAPER}">'
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{GZ_PAPER}" '
        f'style="width:100%!important;border-collapse:collapse;background:{GZ_PAPER};color:{GZ_INK};">'
        f'<tr><td valign="top" style="padding:12px 0 0;color:{GZ_INK};">'
        f'<div style="color:{GZ_KLEIN};font-size:11px;'
        f'font-weight:700;letter-spacing:0.12em">{num} · {_esc(kicker_en)}</div>'
        f'<h2 style="margin:4px 0 0;font-size:{GZ_FS_SECTION}px;'
        f'color:{GZ_INK_STRONG}">{_esc(title)}</h2>{meta}'
        f'</td></tr></table>'
    )
    body = f'{content}</div>'
    # 栏目标记：栏目头与正文之间留一个不可见锚点，供「超长日报按栏目装箱合并推送」时
    # 在栏目内部续接（续片重开栏目头，读者一眼看出在续哪一栏）。
    return head + SECTION_BODY_MARK + body


def gz_ai_analysis_block(res, merge_boards=(), board_owner=""):
    """策略研判 · 依据展开：倾向与核心判断已置顶到「今日预判」，关注主题收在「总结」。

    merge_boards / board_owner：跨栏「同子栏合并」（见 SUB_MERGE_ENABLED）——
    这些板块的涨跌 / 主力净流入已在 board_owner 栏目（AI 行情复盘 · 板块热力）按行情
    口径展示，强度榜只留趋势分 / 趋势 / 信号，避免同一批数字在正文里出现两次。
    """
    out = []
    # 策略总览：量化信号与 regime
    regime = res.get("regime") or res.get("sentiment_label") or "中性"
    score = int(res.get("score") or 0)
    arrow = "▲" if score > 8 else ("▼" if score < -8 else "■")
    signal = res.get("quant_signal") or f"{regime} {arrow}"
    out.append(gz_subsection("量化信号 · 策略总览") + gz_kv_table([
        ("市场倾向", f'<b>{_esc(regime)} {arrow}</b> · 信号 {score:+d} · 置信度 {_esc(res.get("confidence") or "中")}'),
        ("策略信号", _esc(signal)),
        ("核心判断", _esc(res.get("reason") or "—")),
    ]))
    out.append(_quant.macd_strategy.render_strategy(res.get("macd"), GUIZANG_KIT,
                                                    limit=9 if LITE_ENABLED else 0,
                                                    plain=PLAIN()))
    # 板块趋势跟踪：量化趋势分榜（价格动量60% + 资金流30% + 舆情10%）
    sectors = res.get("quant_sectors") or []
    if sectors:
        rows = []
        merged_names = []
        for sec in sectors[:LITE("sector_rows")]:
            chg = sec.get("chg")
            badge = gz_trend_badge(chg, compact=True) if chg is not None else _gz_missing()
            inflow = sec.get("inflow")
            flow_txt = _format_amount(inflow) if inflow is not None else "—"
            trend = _esc(sec.get("trend") or "—")
            sig = _esc(sec.get("signal") or "—")
            score_txt = f'{sec.get("composite", 0):+.2f}'
            name = str(sec.get("name") or "")
            if (SUB_MERGE_ENABLED and board_owner and name
                    and name in set(merge_boards)):
                # 同子栏合并：该板块的涨跌 / 主力净流入已在 12 栏按行情口径展示。
                merged_names.append(name)
                badge = (f'<span style="color:{GZ_FAINT};">{SUB_MERGE_POINTER}</span>')
                flow_txt = "—"
            rows.append([_esc(name), score_txt, badge, flow_txt, trend, sig])
        out.append(gz_subsection("板块趋势跟踪 · 量化强度榜"
                                 + ("" if PLAIN() else "（价格60% + 资金30% + 舆情10%）")) + gz_data_table(
            ["板块", "趋势分", "涨跌", "主力净流入", "趋势", "信号"], rows))
        if merged_names:
            out.append(gz_kv_table([
                ("同子栏合并",
                 f'<span style="font-size:{GZ_FS_META}px;color:{GZ_FAINT};line-height:1.7;">'
                 f'{SUB_MERGE_POINTER} · {sub_merge_pointer_text(SUB_MERGE_NOTE_BOARD, board_owner)}'
                 f'（已合并：{"、".join(_esc(x) for x in merged_names)}）</span>')]))
        weak = [s for s in sectors if (s.get("composite") or 0) < -0.5][:2]
        if weak:
            out.append(gz_kv_table([
                (f'<span style="color:{GZ_DOWN};font-weight:700;">▼ 规避/弱势板块</span>',
                 f'<span style="color:{GZ_DOWN};font-weight:700;">'
                 f'{" / ".join(_esc(s.get("name") or "") for s in weak)}</span>')]))
    elif res.get("sectors_strong"):
        # 兼容：无全景板块数据时退化为舆情热度榜
        out.append(gz_subsection("板块热度（舆情）") + gz_data_table(
            ["板块", "提及"],
            [[_esc(sec), f"{cnt} 次"] for sec, cnt in res["sectors_strong"]]))
        if res.get("sectors_weak"):
            out.append(gz_kv_table([
                (f'<span style="color:{GZ_DOWN};font-weight:700;">▼ 承压板块</span>',
                 f'<span style="color:{GZ_DOWN};font-weight:700;">'
                 f'{" / ".join(_esc(s) for s in res["sectors_weak"])}</span>')]))
    tech_stats = res.get("tech_stats") or {}
    if tech_stats.get("count"):
        band_palette = {"强势": GZ_UP, "偏强": GZ_UP, "震荡": GZ_WARN,
                        "偏弱": GZ_DOWN, "弱势": GZ_DOWN}
        breadth = (
            f'<span style="color:{GZ_UP};font-weight:700;">▲ {tech_stats.get("ups", 0)}</span> / '
            f'<span style="color:{GZ_DOWN};font-weight:700;">▼ {tech_stats.get("downs", 0)}</span> / '
            f'<span style="color:{GZ_FAINT};font-weight:700">■ {tech_stats.get("flats", 0)}</span>'
            f' · 平均 {gz_trend_badge(tech_stats.get("avg"), compact=True)}')
        extremes = []
        for tag, info in (("最强", tech_stats.get("best") or {}),
                          ("最弱", tech_stats.get("worst") or {})):
            if info.get("label"):
                extremes.append(
                    f'{tag} {_esc(info["label"])} '
                    f'<span style="color:{band_palette.get(info.get("band"), GZ_INK)};">'
                    f'{_esc(info.get("band", ""))}</span>')
        tech_pairs = [(f'{tech_stats["count"]} 个指数', breadth)]
        if extremes:
            tech_pairs.append(("两极", " · ".join(extremes)))
        if res.get("tech_read"):
            tech_pairs.append(("解读", _esc(res["tech_read"])))
        out.append(gz_subsection("指数动能 · 趋势过滤") + gz_kv_table(tech_pairs))
    if res.get("risk_note"):
        out.append(gz_subsection("风险预算") + gz_kv_table([("风险预算", _esc(res["risk_note"]))]))
    if res["risks"]:
        risk_cards = []
        risk_limit = LITE("risk_cards")
        for risk in (res["risks"][:risk_limit] if risk_limit else res["risks"]):
            if risk.get("shown") and risk.get("anchor"):
                main = (f'<a href="#{_esc(risk["anchor"])}" '
                        f'style="color:{GZ_INK};font-weight:700;text-decoration:none;">'
                        f'→ {_esc(_risk_ref_label(risk))}</a>')
                sub = _risk_ref_detail(risk)
            else:
                sub_bits = [risk.get("source") or "", risk.get("time") or ""]
                if risk.get("keywords"):
                    sub_bits.append("命中：" + "/".join(risk["keywords"]))
                main = _esc((risk.get("title") or "")[:110])
                sub = " · ".join(x for x in sub_bits if x)
            risk_cards.append(gz_item_row("!", main, sub))
        out.append(gz_subsection("风险提示 · 趋势跟踪止损") + "".join(risk_cards))
    if res.get("themes"):
        out.append(gz_subsection("量化配置 · 趋势跟踪") + gz_kv_table([
            ("★ 趋势跟踪配置",
             f'<b>{_esc(res["themes"])}'
             + ("" if PLAIN() else " · 优选强势趋势板块，规避弱势/高风险板块")
             + "</b>")]))
    return "".join(out)


def gz_quant_strategy_block(res):
    """兼容别名：策略研判渲染（guizang）。"""
    return gz_ai_analysis_block(res)


def _gz_direction_prob(chg):
    if chg is None:
        return None
    return 50 + min(30, int(round(abs(chg) * 20)))


def _gz_factor_sentiment(text):
    bull = sum(text.count(w) for w in _AI_BULL_WORDS)
    bear = sum(text.count(w) for w in _AI_BEAR_WORDS)
    if bull > bear:
        return "▲", GZ_UP
    if bear > bull:
        return "▼", GZ_DOWN
    return "■", GZ_FLAT


def _gz_market_change(quotes, labels):
    chgs = []
    for lbl in labels:
        q = (quotes or {}).get(lbl)
        if isinstance(q, dict):
            p = _percent_number(q.get("change_pct", 0))
            if p is not None:
                chgs.append(p)
    return (sum(chgs) / len(chgs)) if chgs else None





# ============================================================
# 主题渲染套件：把 pixel / guizang 两套布局助手统一成栏目拼版接口
# ============================================================
class _RenderKit:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _pixel_market_section(market, pan=None):
    """pixel 版行情报价：全球与美股 / A股指数 / 港股双指数（缺失品种不出行）。

    pan（东财 A股全景，可选）：给了就把 A股指数与东财「指数表现」并成一块——成交额挂在
    指数名后面，同名指数只出一行，不再有两栏数字互相打架。
    """
    def _block(title, specs):
        rows = []
        block_date = _market_block_date(market, specs)
        for label, precision in specs:
            if _quote_parts(market, label, precision)[0] is None:
                continue          # 缺失品种不出「数据暂缺」行
            value, color = _quote_value(market, label, precision)
            rows.append((_market_row_label(market, label, block_date), value, color))
        return ((_subsection(_esc(_market_block_caption(market, title, specs)))
                 + _data_table(rows)) if rows else "")

    def _ashare_block():
        rows = []
        for r in _market_review_ashare_rows(market, pan):
            pct = r["pct"]
            color = C_GREEN if (pct or 0) > 0 else (C_RED if (pct or 0) < 0 else C_AMBER)
            amt = (f' <span style="color:{C_FAINT};font-size:10px;">'
                   f'成交额 {_format_amount(r["amount"])}</span>') if r.get("amount") else ""
            left = f'<b style="color:{C_INK};">{_esc(r["label"])}</b>{amt}'
            value = (f'<span style="display:inline-block;color:{C_INK};font-size:13px;'
                     f'font-weight:900;font-family:{FONT_MONO};padding-right:6px;">'
                     f'{_esc(r["price_str"])}</span>{_trend_badge(pct)}')
            rows.append((left, value, color))
        if not rows:
            return ""
        return (_subsection(_esc(_market_review_ashare_caption(market, pan)))
                + _data_table(rows))

    return (_block("全球与美股", MARKET_REVIEW_GLOBAL_SPECS)
            + _ashare_block()
            + _block("港股双指数", MARKET_REVIEW_HK_SPECS))


def _panorama_block(pan, with_indices=True, merge_flow=""):
    """pixel 版 A股全景：指数表现 / 涨跌家数 / 成交额 / 南北向 / 板块热力。

    with_indices=False（合并进「AI 行情复盘」时的用法）：指数表已并入 A股指数一块，
    这里不再重复出一份。merge_flow 非空 = 同子栏合并（成交总额见该栏目）。
    """
    parts = []

    # 1) 指数表现（A股宽基）
    indices = pan.get("indices") or []
    if indices and with_indices:
        rows = []
        for idx in indices:
            pct = idx.get("chg_pct")
            color = C_GREEN if (pct or 0) > 0 else (C_RED if (pct or 0) < 0 else C_AMBER)
            amt = (f' <span style="color:{C_FAINT};font-size:10px;">'
                   f'成交额 {_format_amount(idx["amount"])}</span>') if idx.get("amount") else ""
            left = f'<b style="color:{C_INK};">{_esc(idx["name"])}</b>{amt}'
            right = f'{idx["price"]:,.2f} {_trend_badge(pct)}'
            rows.append((left, right, color))
        parts.append(_subsection("指数表现") + _mini_table(rows))

    # 2) 涨跌家数（市场宽度）
    b = pan.get("breadth")
    if b:
        meter = _signal_meter(b["up"], max(1, b["up"] + b["down"]), color=C_CYAN, cells=5)
        breadth_line = (f'<span style="color:{C_GREEN};font-weight:900;">▲ 上涨 {b["up"]:,} 家</span>'
                        f' <span style="color:{C_MUTED};">/</span> '
                        f'<span style="color:{C_RED};font-weight:900;">▼ 下跌 {b["down"]:,} 家</span>'
                        f' <span style="color:{C_MUTED};">/</span> '
                        f'<span style="color:{C_AMBER};font-weight:900;">■ 平盘 {b["flat"]:,} 家</span>')
        ratio_txt = f'{b["ratio"]:.2f}' if b.get("ratio") is not None else "—"
        rows = [("沪深京市场宽度", breadth_line),
                ("涨跌比 / 情绪", f'{meter} <b style="color:{C_LEMON};">{ratio_txt}</b>'
                              f' · {_esc(b.get("mood") or "—")}')]
        blk = _subsection("涨跌家数") + _mini_table(rows)
        if b.get("partial"):
            blk += _note("部分交易所涨跌家数暂缺，本栏为已取得市场的合计。")
        parts.append(blk)

    # 3) 成交额
    t = pan.get("turnover")
    if t:
        chg = t.get("chg_pct")
        chg_html = (f' 较上一交易日 {_trend_badge(chg, compact=True)}' if chg is not None
                    else f' <span style="color:{C_FAINT};font-size:10px;">（环比暂缺）</span>')
        line = (f'<span style="color:{C_LEMON};font-size:15px;font-weight:900;">'
                f'{_format_amount(t["total"])}</span>{chg_html}')
        rows = [("沪深京成交额合计", line)]
        if t.get("prev_total"):
            rows.append(("上一交易日合计（沪深京）", _format_amount(t["prev_total"])))
        parts.append(_subsection("成交额") + _mini_table(rows))

    # 4) 南北向资金（前一收盘成交总额 + 披露口径说明）
    north = pan.get("north") or {}
    if north:
        north_val = (f'<span style="color:{C_CYAN};font-weight:900;">'
                     f'{north["amount_yi"]:,.2f} 亿元</span>') \
            if (north.get("available") and north.get("amount_yi") is not None) \
            else f'<span style="color:{C_FAINT};">■ 数据暂缺</span>'
        south_val = (f'<span style="color:{C_CYAN};font-weight:900;">'
                     f'{north["south_amount_yi"]:,.2f} 亿元</span>') \
            if (north.get("south_available") and north.get("south_amount_yi") is not None) \
            else f'<span style="color:{C_FAINT};">■ 数据暂缺</span>'
        if merge_flow and SUB_MERGE_ENABLED:
            # 同子栏合并：成交总额已在 merge_flow 栏目展开 —— 这里只留指针。
            parts.append(_subsection("南北向资金（前一收盘）")
                         + _mini_table([(SUB_MERGE_POINTER,
                                         sub_merge_pointer_text(SUB_MERGE_NOTE_FLOW, merge_flow))]))
        else:
            parts.append(_subsection("南北向资金（前一收盘）")
                         + _mini_table([
                             (f'北向成交总额（{_esc(north.get("date") or "—")}）', north_val),
                             (f'南向成交总额（{_esc(north.get("south_date") or north.get("date") or "—")}）', south_val),
                         ])
                         + _note(north.get("policy_note") or PANORAMA_NORTH_POLICY_NOTE))

    # 5) 板块热力
    sec = pan.get("sectors") or {}
    for title, key in (("板块热力 · 领涨行业 TOP", "leading"),
                       ("板块热力 · 领跌行业 TOP", "lagging")):
        items = sec.get(key) or []
        if not items:
            continue
        rows = []
        for it in items:
            sub_bits = []
            if it.get("main_inflow") is not None:
                sub_bits.append(f'主力{_format_amount(it["main_inflow"])}')
            if it.get("lead_stock"):
                lead_pct = it.get("lead_stock_pct")
                sub_bits.append(f'领涨 {_esc(it["lead_stock"])}'
                                + (f' {lead_pct:+.2f}%' if lead_pct is not None else ''))
            sub = (f' <span style="color:{C_FAINT};font-size:10px;">{" · ".join(sub_bits)}</span>'
                   if sub_bits else "")
            rows.append((f'{_esc(it["name"])}{sub}', _trend_badge(it.get("chg_pct"), compact=True)))
        parts.append(_subsection(title) + _mini_table(rows))

    if pan.get("quote_time"):
        parts.append(_note(
            f"数据截至 {_esc(pan['quote_time'])}（北京时间）；成交额「亿/万」为本地换算。"
            "板块按行业涨跌幅排序。规则合成，非投资建议。"))
    return "".join(parts)


def _pixel_market_review(market, pan, merge_flow=""):
    """pixel 版【及时秋刀鱼】AI 行情复盘：逐项报价 + A股全景，重复数字只出一份。

    merge_flow 非空时，南北向资金走「同子栏合并」口径（见 SUB_MERGE_ENABLED）。
    """
    return (_pixel_market_section(market, pan)
            + _panorama_block(pan or {}, with_indices=False, merge_flow=merge_flow))


def _cal_pixel_cells(day_label, t_plus, item, first=False):
    """pixel 日历表的一行：日期（当天首行附 T+n）/ 时间 / 星号 + 地区 + 时间点。"""
    item = item if isinstance(item, dict) else {}
    imp = max(1, min(3, int(item.get("imp") or 1)))
    color = C_LEMON if imp >= 3 else (C_CYAN if imp == 2 else C_MUTED)
    day_html = ""
    if first:
        day_html = f'<b style="color:{C_INK};">{_esc(day_label)}</b>'
        when = _cal_countdown(t_plus)
        if when:
            day_html += (f'<div style="font-size:9px;color:{C_FAINT};padding-top:2px;">'
                         f'{_esc(when)}</div>')
    city = str(item.get("city") or "").strip()
    city_html = f'<span style="color:{C_FAINT};">{_esc(city)}</span> ' if city else ""
    body = (f'<span style="color:{color};font-weight:900;">{"★" * imp}</span> '
            f'{city_html}{_esc(_cal_item_text(item))}')
    return [day_html, _esc(str(item.get("time") or "—")), body]


def _calendar_block(res, date_str=None):
    """pixel 版「时间节点」：窗口摘要（全窗口口径）+ 近端日历表（精简模式披露折叠条数）。"""
    digest, rows, disclosure = _calendar_table_rows(res, _cal_pixel_cells, date_str=date_str)
    parts = []
    pairs = digest.get("pairs") or []
    if pairs:
        parts.append(_subsection("窗口摘要"))
        parts.append(_pixel_table(None, [[_esc(a), _esc(b)] for a, b in pairs],
                                  aligns=("left", "left"), widths=("26%", "74%")))
    if rows:
        label = _calendar_table_label()
        if disclosure and PLAIN():
            label += f" · {disclosure}"
        parts.append(_subsection(_esc(label)))
        parts.append(_pixel_table(["日期", "时间", "影响经济的时间点"], rows,
                                  aligns=("left", "left", "left"),
                                  widths=("17%", "13%", "70%")))
    if disclosure and not PLAIN():
        parts.append(_note(_esc(disclosure)))
    return "".join(parts)


# ============================================================
# 精简排版：今日预判 → ①发生了什么 → ②传播得怎么样 → ③可能会怎样 → ④我们该怎么办 → 总结收尾
# ——正文不展示重复推导过程，不出现「数据暂缺」占位行、
#   抓取失败的来源与过期内容；来源状态只在「总结」里压成一行。
# ============================================================
REPORT_STALE_DAYS = 7          # 频道视频 / 全球头条超过 N 天视为过期，不进正文

# 详情字段里纯说明性质的片段（免责声明、口径提示），渲染时剔除。
_CONCISE_DROP_MARKERS = (
    "未经核实", "仅供", "不是交易信号", "不抓取", "非今日", "抓取快照", "不代表",
    "休市时", "官网公开榜单", "原站入口", "站点未标注",
)


def _concise_detail(text):
    """保留详情里的数据与时间，去掉免责 / 口径说明片段。"""
    parts = [p.strip() for p in re.split(r"\s*·\s*", str(text or "")) if p.strip()]
    kept = [p for p in parts if not any(m in p for m in _CONCISE_DROP_MARKERS)]
    return " · ".join(kept).replace("（北京时间）", "")


def _report_date_obj(date_str):
    try:
        return datetime.strptime(str(date_str), "%Y%m%d").date()
    except (TypeError, ValueError):
        return datetime.now(CST).date()


def _is_stale(stamp, anchor_date, days=REPORT_STALE_DAYS):
    """``YYYY-MM-DD…`` 早于报告日 ``days`` 天以上 → 过期；无法解析的时间不判过期。"""
    try:
        d = datetime.strptime(str(stamp)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return (anchor_date - d).days > days


def _prune_report_data(data, date_str=None):
    """渲染前剔除过期内容（不改动原始 data，存档 / 推送门禁不受影响）。

    - 港股名家频道：只留近 ``REPORT_STALE_DAYS`` 天的视频，全部过期的频道整体移除；
    - 全球头条：去掉发布超过 ``REPORT_STALE_DAYS`` 天的标题。
    策略研判 / 情绪因子与正文使用同一份裁剪数据，锚点序号保持一致。
    """
    anchor = _report_date_obj(date_str or _today_str())
    out = dict(data or {})
    yt = out.get("港股名家频道")
    if isinstance(yt, dict) and yt.get("channels"):
        channels = []
        for ch in yt.get("channels") or []:
            videos = [v for v in (ch.get("videos") or [])
                      if not _is_stale(v.get("published_cst"), anchor)]
            if videos:
                channels.append({**ch, "videos": videos})
        out["港股名家频道"] = {**yt, "channels": channels}
    google = out.get("全球头条")
    if isinstance(google, dict) and google.get("headlines"):
        heads = [h for h in google.get("headlines") or []
                 if not (isinstance(h, dict) and _is_stale(h.get("published_cst"), anchor))]
        out["全球头条"] = {**google, "headlines": heads}
    # AI趋势分析两个专题源与全球头条同口径裁剪过期标题
    for _tk in (FED_TREND_KEY, GEO_TREND_KEY):
        src = out.get(_tk)
        if isinstance(src, dict) and src.get("headlines"):
            heads = [h for h in src.get("headlines") or []
                     if not (isinstance(h, dict) and _is_stale(h.get("published_cst"), anchor))]
            out[_tk] = {**src, "headlines": heads}
    return out


def _short_source(item):
    """栏目副标题只留来源名，抓取时间 / 口径说明不再重复。"""
    return _esc(str((item or {}).get("source") or ""))


def _market_review_meta(kit, market, pan):
    """【及时秋刀鱼】AI 行情复盘的徽标与副标题：两路数据分别标状态。

    合并栏目由「实时行情（Yahoo / 东财回补）」与「A股大盘全景（东财）」两路数据合成，
    成功的各路出自己的状态徽标（并标明「报价 / A股全景」是哪一路）与来源名（「 ＋ 」
    相接）；失败 / 暂缺的一路在副标题写明，读者不会把一路的状态误当成整栏的状态。
    """
    present = [(tag, src) for tag, src in (("报价", market), ("A股全景", pan))
               if isinstance(src, dict) and src.get("status") == "success"]
    missing = [tag for tag, src in (("报价", market), ("A股全景", pan))
               if not (isinstance(src, dict) and src.get("status") == "success")]
    badges, names = [], []
    for tag, src in present:
        badge = kit.source_badge(src)
        if badge:
            badges.append(f"{tag} {badge}" if len(present) > 1 else badge)
        name = _short_source(src)
        if name:
            names.append(name)
    # 入门版：副标题不列供数来源名（Yahoo / 东财…），只保留「暂缺」提示；徽标里的
    # 「当天 / 非当天 日期」照常显示——数据新不新鲜是读者最该先看到的。
    caption = "" if PLAIN() else " ＋ ".join(names)
    if missing:
        note = "暂缺：" + "、".join(missing)
        caption = f"{caption} · {note}" if caption else note
    return " · ".join(badges), caption


def _weekly_merged_meta(kit, weekly_src, hk7_src, quant_src=None):
    """每日趋势量化推演栏的徽标与副标题：逐日表格、AI 七日走势、港股概率各自标状态。

    逐日表格（因果量化引擎）、恒指 / 恒科 / 国企三指数七日概率（大模型研判，失败降级量化基准）
    与港股指数及个股概率分析共用一个栏目头。一路可用即出栏目；来源徽标与来源名分别标注，
    避免把一路的状态误当成整栏状态。底层数据源键名 / 审计标签 / 留痕文件各自保留。
    """
    def _res(src):
        return (src.get("result") or {}) if isinstance(src, dict) else {}

    badges, names, missing = [], [], []
    wk_ok = bool(_res(weekly_src).get("available"))
    hk_ok = bool(_res(hk7_src).get("available"))
    quant_ok = bool(_res(quant_src).get("available"))
    if wk_ok:
        badges.append(kit.badge("七日预测", "ai"))
        nm = _short_source(weekly_src)
        if nm:
            names.append(nm)
    else:
        missing.append("逐日表格")
    if hk_ok:
        eng = _res(hk7_src).get("engine")
        eng_badge = {"llm": "大模型研判", "jev": "Jev 本地模型"}.get(eng, "量化降级")
        badges.append(kit.badge(eng_badge, "ai"))
        nm = _short_source(hk7_src)
        if nm:
            names.append(nm)
    else:
        missing.append("AI 七日港股")
    if quant_ok:
        badges.append(kit.badge("港股概率", "ai"))
        nm = _short_source(quant_src)
        if nm:
            names.append(nm)
    else:
        missing.append("港股概率分析")
    caption = "" if PLAIN() else " ＋ ".join(names)
    if missing and (wk_ok or hk_ok):
        note = "暂缺：" + "、".join(missing)
        caption = f"{caption} · {note}" if caption else note
    return " · ".join(b for b in badges if b), caption


def _trend_clue_item_row(item, pick_no, base, color, kit, title_limit=235):
    """单条平台样本行（链接 + 元信息），非法链接 / 空标题整体剔除。"""
    url = _public_url(item.get("url"), base)
    title = _public_text(item.get("title"), title_limit)
    if not (url and title):
        return ""
    link = (f'<a href="{_esc(url)}" style="color:{color}">'
            f'{_esc(title)}</a>')
    return kit.item_row(f"{pick_no:02d}", link,
                        _esc(_concise_detail(_public_text(item.get("detail"), 210))))


def _trend_clues_block(data, kit):
    """两主题共用：趋势跟踪——① 全网 36 个新闻源头 · 港股信息挖掘 + 分析；
    ② 多平台信息员（Reddit / StockTwits / TradingView / Bogleheads）社区样本。

    无数据的源头 / 平台不进正文；缺失来源只在总结的「数据覆盖」里点名。Reddit 按 10 个
    板块分组（每板块至多 5 条），其余平台按各自榜单 / 板块分组。

    精简模式（默认）：每个源头只列 1 条、社区每组只留 2 条样本、标题收到 80 字——
    **覆盖面一个字不少**（36 家源头的名字、条数、更新时间全在），砍掉的只是重复展开的
    样本正文；每个源头 / 分组行都写明「共 N 条」，读者知道折叠了多少。
    """
    color = GZ_KLEIN if _is_guizang_like(kit) else C_CYAN
    per_source = LITE("news_per_source")
    news_total = LITE("news_total")
    site_posts = LITE("site_posts")
    title_limit = 80 if LITE_ENABLED else 235
    detail_limit = 70 if LITE_ENABLED else 210
    rows = []

    # ① 全网 36 个新闻源头 · 港股挖掘（结论先行：覆盖度 + 港股相关条数）
    news = data.get(HK_NEWS_SOURCE_NAME) or {}
    if news.get("status") == "success":
        an = news.get("analysis") or {}
        records = [r for r in (news.get("sources") or []) if isinstance(r, dict)]
        total = int(an.get("total") or len(records) or len(HK_NEWS_SOURCES))
        latest = _public_text(news.get("content_date") or "", 30)
        if PLAIN():
            # 入门版：抓取过程（几家有更新 / 扫描多少条）不交代，只报港股相关条数。
            heading = (f'<b>全网新闻源头 ×{total}</b> · 港股相关 {int(an.get("hk_n") or 0)} 条'
                       f' {kit.source_badge(news)}')
        else:
            heading = (f'<b>全网新闻源头 ×{total}</b> · {int(an.get("ok_n") or 0)} 家窗口内有更新'
                       f' · 扫描 {int(an.get("scanned") or 0)} 条 · 港股相关 {int(an.get("hk_n") or 0)} 条'
                       f' {kit.source_badge(news)}')
        rows.append(kit.item_row("", heading, _esc(latest)))
        if LITE_ENABLED and not PLAIN():
            # 精简模式：36 家源头不再一家一行（光覆盖名单就占半屏），压成一行「覆盖面」
            # ——**名字与港股相关条数一个不删**（按抓取顺序，含因条数预算未列条目的源头），
            # 条目照常带链接逐条列出。
            cover = [f'{str(rec.get("name") or "")} '
                     f'{int(rec.get("hk_n") or len([it for it in (rec.get("items") or [])]))}'
                     for rec in records
                     if any(isinstance(it, dict) for it in (rec.get("items") or []))]
            if cover:
                rows.append(kit.item_row("▤", "<b>覆盖面</b>（源头 · 港股相关条数）",
                                         _esc(" · ".join(cover))))
        shown = 0
        for rec in records:
            if shown >= news_total:
                break
            items = [it for it in (rec.get("items") or []) if isinstance(it, dict)]
            if not items:
                continue
            hk_n = int(rec.get("hk_n") or len(items))
            if not LITE_ENABLED:
                name = str(rec.get("name") or "")
                home = _news_url(rec.get("url"), rec.get("hosts") or ())
                name_html = (f'<a href="{_esc(home)}" style="color:{color}">'
                             f'<b>{_esc(name)}</b></a>' if home else f"<b>{_esc(name)}</b>")
                rows.append(kit.item_row(
                    "▤", f'{_esc(str(rec.get("region") or ""))} · {name_html}',
                    f"港股相关 {hk_n} 条" + (f" · 列出 {min(len(items), per_source)} 条"
                                            if hk_n > min(len(items), per_source) else "")))
            for item in items[:per_source]:
                if shown >= news_total:
                    break
                url = _news_url(item.get("url"), rec.get("hosts") or ())
                title = _public_text(item.get("title"), title_limit)
                if not (url and title):
                    continue
                link = (f'<a href="{_esc(url)}" style="color:{color}">'
                        f'{_esc(title)}</a>')
                detail = _concise_detail(_public_text(item.get("detail"), detail_limit))
                if PLAIN():
                    # 入门版没有「覆盖面」清单：每条标题自己带上出处（像普通新闻流一样）
                    src_name = str(rec.get("name") or "")
                    detail = " · ".join(x for x in (src_name, detail) if x)
                rows.append(kit.item_row(f"{shown + 1:02d}", link, _esc(detail)))
                shown += 1

    # ①b 内地财经媒体（18 家，2026-10-12 按用户指定新增）：与「新闻源头」同一展示位，
    #     只报**源头级覆盖**（每家窗口内条数），标题不在这里重复列出——它们在被引用处
    #     （新闻情绪证据行 / 政策因子引用行）带媒体名出现，避免跨栏重复展示同一批标题。
    mainland = data.get(MAINLAND_NEWS_SOURCE_NAME) or {}
    if mainland.get("status") == "success":
        m_an = mainland.get("analysis") or {}
        m_recs = [r for r in (mainland.get("sources") or []) if isinstance(r, dict)]
        m_items_n = int(m_an.get("items_n") or 0)
        m_date = _public_text(mainland.get("content_date") or "", 30)
        if PLAIN():
            m_head = (f'<b>内地财经媒体 ×{MAINLAND_NEWS_TOTAL}</b> · 标题池 {m_items_n} 条'
                      f' {kit.source_badge(mainland)}')
        else:
            m_head = (f'<b>内地财经媒体 ×{MAINLAND_NEWS_TOTAL}</b>'
                      f' · {int(m_an.get("ok_n") or 0)} 家窗口内有更新'
                      f' · 扫描 {int(m_an.get("scanned") or 0)} 条 · 进标题池 {m_items_n} 条'
                      f' {kit.source_badge(mainland)}')
        rows.append(kit.item_row("", m_head, _esc(m_date)))
        if not PLAIN():
            m_cover = [f'{str(rec.get("name") or "")} '
                       f'{len([it for it in (rec.get("items") or []) if isinstance(it, dict)])}'
                       for rec in m_recs
                       if any(isinstance(it, dict) for it in (rec.get("items") or []))]
            if m_cover:
                rows.append(kit.item_row("▤", "<b>覆盖面</b>（内地源头 · 窗口内条数）",
                                         _esc(" · ".join(m_cover))))
            rows.append(kit.item_row("▤", "标题去向",
                                     "标题进同一标题池，供新闻情绪因子与政策因子逐条引用"))

    # ② 多平台信息员（Reddit / StockTwits / TradingView / Bogleheads）
    live = []
    for name in _active_public_site_names():
        source = data.get(name) or {}
        if source.get("status") == "success" and source.get("items"):
            live.append((name, source))
    if live:
        rows.append(kit.item_row("", f'<b>多平台信息员</b> · {_esc(" · ".join(n for n, _ in live))}',
                                 "" if PLAIN() else
                                 _esc(f"{len(live)} 个平台公开样本，各自独立采集；缺失平台见总结")))
    for name, source in live:
        homepage = _public_url(PUBLIC_SITE_URLS.get(name) or "")
        anchor_name = f'<a href="{_esc(homepage)}" style="color:{color}"><b>{_esc(name)}</b></a>' if homepage else f"<b>{_esc(name)}</b>"
        rows.append(kit.item_row("", f'{anchor_name} {kit.source_badge(source)}',
                                 _esc(_public_text(source.get("content_date") or "", 30))))
        # 只统计**能真正渲染出来**的样本（非法链接 / 空标题会被整条剔除）：
        # 否则「共 N 条」会比实际列出的多，等于在披露里写假数字。
        site_name = name
        valid = [it for it in (source.get("items") or [])
                 if isinstance(it, dict)
                 and _public_url(it.get("url"), PUBLIC_SITE_URLS.get(site_name) or "")
                 and _public_text(it.get("title"), 235)]
        if name == "Reddit":
            by_board = {}
            for item in valid:
                by_board.setdefault(str(item.get("community") or ""), []).append(item)
            for community, label in _REDDIT_BOARDS:
                board_all = [it for it in by_board.get(f"r/{community}", [])
                             if isinstance(it, dict)]
                board_items = board_all[:site_posts]
                if not board_items:
                    continue
                rows.append(kit.item_row("▤", f'<b>{_esc(f"r/{community}")}</b> · {_esc(label)}',
                                         f"热门帖样本 {len(board_items)} 条"
                                         + (f"（共 {len(board_all)} 条）"
                                            if len(board_all) > len(board_items) else "")))
                for pick_no, item in enumerate(board_items, 1):
                    rows.append(_trend_clue_item_row(item, pick_no, PUBLIC_SITE_URLS[name],
                                                     color, kit, title_limit=title_limit))
            continue
        grouped, order = {}, []
        for item in valid:
            community = str(item.get("community") or name)
            if community not in grouped:
                grouped[community] = []
                order.append(community)
            grouped[community].append(item)
        for community in order:
            picks = grouped[community][:site_posts]
            if not picks:
                continue
            rows.append(kit.item_row("▤", f'<b>{_esc(community)}</b>',
                                     f"公开样本 {len(picks)} 条"
                                     + (f"（共 {len(grouped[community])} 条）"
                                        if len(grouped[community]) > len(picks) else "")))
            for pick_no, item in enumerate(picks, 1):
                rows.append(_trend_clue_item_row(item, pick_no, PUBLIC_SITE_URLS[name],
                                                 color, kit, title_limit=title_limit))
    rows = [row for row in rows if row]
    return kit.rows("".join(rows)) if rows else ""


def _asof_short(date_str):
    """'2026-09-28' → '09-28'；空值返回 ''。"""
    d = str(date_str or "")
    return d[5:10] if len(d) >= 10 else d


def _market_asof_note(market, labels):
    """「（截至 09-28）」：这几个品种的数据日期；日期不一致写区间，落后于最新交易日标「滞后」。

    「今日预判」是开盘前推送的结论，行情只能是**上一个收盘**；把日期写出来，读者才能
    分辨「昨日收盘（正常）」与「回退到上上个交易日（数据滞后）」。
    """
    quotes = (market or {}).get("quotes") or {}
    # 商品期货（WTI）电子盘日期天然领先：同一子块里只要有股票品种，就按股票品种定日期，
    # 期货行自己在名称后标日期（见 _market_row_label），避免出现「截至 09-28~09-29」。
    core = [l for l, _ in labels if _market_group_of(l) not in MARKET_LAG_EXEMPT_GROUPS
            and isinstance(quotes.get(l), dict) and quotes[l].get("as_of")]
    use = core or [l for l, _ in labels]
    dates = sorted({str(quotes[l].get("as_of")) for l in use
                    if isinstance(quotes.get(l), dict) and quotes[l].get("as_of")})
    if not dates:
        return ""
    span = _asof_short(dates[0]) if len(dates) == 1 else f"{_asof_short(dates[0])}~{_asof_short(dates[-1])}"
    lagging = _market_lagging(market)
    if any(l in lagging for l, _ in labels):
        return f"（截至 {span} · 滞后）"
    return f"（截至 {span}）"


def _market_brief(market, labels, kit, with_date=False):
    """「道指 ▲+0.93% · 标普 ▲+0.51%」式一行行情摘要；缺失项直接略过。

    with_date=True 时末尾追加「（截至 MM-DD）」数据日期说明。
    """
    bits = []
    for label, short in labels:
        _, pct = _quote_parts(market or {}, label)
        if pct is not None:
            bits.append(f"{_esc(short)} {kit.trend(pct, compact=True)}")
    line = " · ".join(bits)
    if line and with_date:
        line += _esc(_market_asof_note(market, labels))
    return line


def _forecast_dir_text(label):
    """今日预判的方向文案：去掉七日预测 label 自带的「P(N日涨) xx%」。

    2026-10-23 用户要求【回游金枪鱼】今日预判不显示涨跌概率；octopus_weekly 的
    entry["label"]（如「■ 中性（略偏跌）· P(7日涨) 44%」）自带宽口径概率，
    这里只保留方向定调部分，概率数字仍在「每日趋势量化推演」正文如实展示。
    """
    text = str(label or "")
    text = re.sub(r"\s*[·,，]?\s*P\(\d*日涨\)\s*\d+(?:\.\d+)?%", "", text)
    text = re.sub(r"\s*\d+(?:\.\d+)?%\s*$", "", text)
    return text.strip()


def _conclusion_pairs(kit, ai_result, market, pan, policy, quant=None, weekly=None):
    """最终「今日预判」：量化与方向结论 → 核心判断 → 市场数据 → 政策定调。

    不显示涨跌概率（2026-10-23 用户要求）：量化只给方向定调、七日预测只给整段方向。
    """
    pairs = []
    # 量化分析置顶：只给方向定调与目标交易日，**不展示涨跌概率**
    # （2026-10-23 用户要求：【回游金枪鱼】今日预判不显示涨跌概率）。
    if quant and quant.get("available"):
        head = quant.get("headline") or {}
        if head.get("available"):
            pairs.append(("量化分析",
                          f'<b>{_esc(head.get("arrow", "■"))} '
                          f'{_esc(head.get("label", "中性"))}</b>'
                          f' · {_esc(quant.get("target_label") or "下一交易日")}'))
    # 七日预测：未来 7 个交易日港股整段方向（概率同样不在这里展示）
    if weekly and weekly.get("available"):
        wk_entry = weekly.get("entry") or {}
        wk_dir = _forecast_dir_text(wk_entry.get("label"))
        if wk_dir:
            pairs.append(("七日预测",
                          f'<b>{_esc(wk_dir)}</b>'
                          f' · 锚定 {_esc(str(wk_entry.get("base_date") or ""))} 收盘'
                          f' · 未来 {_esc(str(wk_entry.get("target_sessions") or _weekly.PATH_MAX))} 个交易日'))
    if ai_result and ai_result.get("available"):
        score = int(ai_result["score"])
        arrow = "▲" if score > 8 else ("▼" if score < -8 else "■")
        pairs.append(("市场倾向", f'<b>{_esc(ai_result["sentiment_label"])} {arrow}</b>'
                                 f' · 信号 {score:+d} · 置信度 {_esc(ai_result["confidence"])}'))
        if ai_result.get("reason"):
            pairs.append(("核心判断", _esc(ai_result["reason"])))
    if pan and pan.get("status") == "success":
        bits = []
        sh = next((i for i in (pan.get("indices") or []) if i.get("name") == "上证指数"), None)
        if sh and sh.get("price") is not None:
            bits.append(f'上证 {sh["price"]:,.2f} {kit.trend(sh.get("chg_pct"), compact=True)}')
        b = pan.get("breadth") or {}
        if b:
            bits.append(f'{_esc(b.get("mood") or "")}（涨 {b.get("up", 0):,} / 跌 {b.get("down", 0):,}）')
        t = pan.get("turnover") or {}
        if t.get("total"):
            chg = t.get("chg_pct")
            bits.append(f'成交 {_format_amount(t["total"])}'
                        + (f' {kit.trend(chg, compact=True)}' if chg is not None else ""))
        if bits:
            line = " · ".join(bits)
            # 数据日期：东财行情时间（开盘前推送 = 上一收盘；盘中运行 = 截至该时刻）
            pan_date = _asof_short(pan.get("content_date"))
            if pan_date:
                qt = str(pan.get("quote_time") or "")
                clock = qt[11:16] if len(qt) >= 16 else ""
                line += _esc(f"（截至 {pan_date}{' ' + clock if clock else ''}）")
            pairs.append(("A股", line))
    elif market and market.get("status") == "success":
        line = _market_brief(market, [("上证指数", "上证"), ("深证成指", "深成")], kit, with_date=True)
        if line:
            pairs.append(("A股", line))
    if market and market.get("status") == "success":
        us = _market_brief(market, [("道琼斯指数", "道指"), ("标普500", "标普"), ("纳斯达克", "纳指")],
                           kit, with_date=True)
        if us:
            pairs.append(("美股", us))
        hk = _market_brief(market, [("恒生指数", "恒指"), ("恒生科技", "恒科")], kit, with_date=True)
        if hk:
            pairs.append(("港股", hk))
        lag = _market_lagging(market)
        if lag:
            groups = sorted({_market_group_of(l) for l in lag})
            newest = _asof_short(_market_newest_session(market))
            if PLAIN():
                lag_dates = sorted({_asof_short(d) for d in lag.values()})
                pairs.append(("数据提示",
                              _esc(f"{'、'.join(groups)}行情截至 {'、'.join(lag_dates)}"
                                   f"（落后最新交易日 {newest}），未计入指数均值")))
            else:
                pairs.append(("数据提示",
                              _esc(f"{'、'.join(groups)}行情数据日期落后于最新交易日 {newest}"
                                   f"（{'、'.join(f'{l} {_asof_short(d)}' for l, d in sorted(lag.items()))}）"
                                   "，上游行情源尚未更新，已不计入核心判断的指数均值")))
    if policy and policy.get("available"):
        quant_info = f' · {policy.get("quant_trend") or ""} {policy.get("quant_composite"):+.2f}' if policy.get("quant_composite") is not None else ""
        line = f'PSI {policy["broad_score"]:+d}（{_esc(policy["broad_label"])}）{quant_info}'
        if policy.get("winners"):
            line += " · 受益 " + "、".join(_esc(w["name"]) for w in policy["winners"][:2])
        if policy.get("losers"):
            line += " · 承压 " + "、".join(_esc(w["name"]) for w in policy["losers"][:2])
        pairs.append(("政策", line))
    return pairs


def _conclusion_panel(kit, pairs):
    """把核心判断做成收尾重点多行多列表格；次级数字同表或按键值表显示。"""
    pairs = list(pairs or [])
    if not pairs:
        return ""
    primary_index = next((i for i, (label, _value) in enumerate(pairs)
                          if label == "核心判断"), None)
    if primary_index is None:
        primary_index = next((i for i, (label, _value) in enumerate(pairs)
                              if label in ("市场倾向", "量化分析", "七日预测")), 0)
    primary_label, primary_value = pairs[primary_index]
    secondary = [pair for i, pair in enumerate(pairs) if i != primary_index]
    if _is_guizang_like(kit):
        accent, background, ink = GZ_KLEIN, GZ_KLEIN_WASH, GZ_INK_STRONG
    else:
        accent, background, ink = C_LEMON, C_AI_BG, C_INK
    lead_label = (f'<span style="font-size:11px;font-weight:900;letter-spacing:.08em;color:{accent};">'
                  f'结论 · 重点</span>')
    if primary_label != "核心判断":
        lead_label += f'<br><span style="font-size:10px;color:{ink};">{_esc(primary_label)}</span>'
    lead_val = (f'<div style="font-size:17px;line-height:1.6;font-weight:900;color:{ink};">'
                f'{primary_value}</div>')
    body = (f'<div style="border-left:5px solid {accent};background:{background};'
            f'padding:10px 12px;margin:4px 0 8px;">'
            + kit.kv([(lead_label, lead_val), *secondary])
            + "</div>")
    return body


# 正文不展示的数据源（底层仍供量化用）：总结「数据覆盖」与AI帮你提鲜的
# 「配料表」都不点名它们，避免两处口径漂移。
_HIDDEN_REPORT_SOURCES = {"A股资讯"}


def _missing_source_names(source_items):
    """暂缺数据源清单（总结栏与AI帮你提鲜共用同一份，绝不各算各的）。"""
    return [name for name, s in source_items
            if name not in _HIDDEN_REPORT_SOURCES and s.get("status") != "success"]


def _summary_pairs(ai_result, pan, policy, source_items, today_n, total, quant=None,
                   backup_events=None, media_risk=None):
    """前置盘点：结论回顾 → 模型校准与预测追踪 → 明日关注 → 风险 → 数据覆盖。"""
    pairs = []
    if quant and quant.get("available"):
        v1 = (quant.get("validation") or {}).get(1) or {}
        if v1:
            sig = ""
            if v1.get("z") is not None:
                sig = ("（显著）" if abs(v1["z"]) >= 1.96 else
                       "（弱显著）" if abs(v1["z"]) >= 1.28 else "（不显著）")
            pairs.append(("模型校准",
                          (f'近 {v1.get("n", 0)} 日方向命中 '
                           f'{(v1.get("hit_rate") or 0) * 100:.0f}%（基准 '
                           f'{(v1.get("base_rate") or 0) * 100:.0f}%）') if PLAIN() else
                          f'推进式回测 {v1.get("n", 0)} 日 · 命中 '
                          f'{(v1.get("hit_rate") or 0) * 100:.0f}% · 基准 '
                          f'{(v1.get("base_rate") or 0) * 100:.0f}%{sig}'))
        jr = quant.get("journal") or {}
        if jr.get("n"):
            bits = [f'已结算 {jr["n"]} 次 · 方向命中 {(jr.get("hit_rate") or 0) * 100:.0f}%']
            if jr.get("band_hit_rate") is not None:
                bits.append(f'区间命中 {jr["band_hit_rate"] * 100:.0f}%')
            if jr.get("brier") is not None and not PLAIN():
                bits.append(f'Brier {jr["brier"]:.3f}')
            pairs.append(("预测追踪", _esc(" · ".join(bits))))
    recap = []
    if ai_result and ai_result.get("available"):
        recap.append(f'整体{ai_result["sentiment_label"]}')
    b = (pan or {}).get("breadth") or {}
    if (pan or {}).get("status") == "success" and b.get("mood"):
        recap.append(f'A股{b["mood"]}')
    if policy and policy.get("available"):
        recap.append(f'政策{policy["broad_label"]}')
    if recap:
        pairs.append(("今日盘点", _esc("｜".join(recap))))
    if ai_result and ai_result.get("themes"):
        pairs.append(("明日关注", _esc(ai_result["themes"])))
    risk_notes = []
    if isinstance(media_risk, dict) and media_risk:
        # 2026-10-21 起即使清洁态也给出监控中说明，避免总结里完全不提媒体风险
        if media_risk.get("available"):
            levels = media_risk.get("level_counts") or {}
            top = media_risk.get("top_stock") or {}
            alert_n = int(levels.get("red") or 0) + int(levels.get("orange") or 0)
            detail = (f'媒体舆情 结构化预警 {media_risk.get("risk_stock_n") or 0} 只（红/橙 {alert_n}）'
                      f' · 异常关注 {media_risk.get("abnormal_attention_n") or 0} 只')
            if top.get("name"):
                detail += (f' · 最高 {top["name"]} '
                           f'{(top.get("level") or {}).get("label") or "观察"} '
                           f'{int(top.get("risk_index") or 0)}/100')
            risk_notes.append(detail)
        elif MEDIA_RISK_ENABLED:
            headline_n = int(media_risk.get("headline_n") or 0)
            universe_n = int(media_risk.get("universe_n") or 0)
            if universe_n == 0:
                reason = str(media_risk.get("reason") or "监控范围暂空")
                risk_notes.append(f'媒体舆情 72h筛查中：{reason}（标题{headline_n}条）')
            else:
                risk_notes.append(f'媒体舆情 72h筛查：监控{universe_n}只 · 未检出预警（标题{headline_n}条）')
    if ai_result and ai_result.get("risks"):
        counts = {}
        for r in ai_result["risks"]:
            for kw in r.get("keywords") or []:
                counts[kw] = counts.get(kw, 0) + 1
        if counts:
            risk_notes.append("策略关键词 " + "、".join(
                f"{k}×{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
    if risk_notes:
        pairs.append(("风险关注", _esc("｜".join(risk_notes))))
    elif ai_result and ai_result.get("available"):
        pairs.append(("风险关注", "未检出显著风险舆情"))
    # A股资讯已从日报栏目中移除：底层数据仍供量化策略使用，不再作为正文的
    # 缺失项提示，避免版面继续点名已删除栏目。
    missing = _missing_source_names(source_items)
    cover = f"当天 {today_n}/{total} 源"
    if missing:
        cover += " · 暂缺：" + "、".join(missing)
    # Jev 端点名点（Jev 文档落地清单 P1）：栏内渲染时，端点是未配置 / 探活失败 /
    # 调用失败 / 使用中，读者在数据覆盖里一眼可见（与「AI 七日港股暂缺」并列口径）。
    _hk7_item = next((s for n, s in source_items if n == HK7_SOURCE_NAME), None)
    _jev_note = (_hk7_item or {}).get("jev_note") if isinstance(_hk7_item, dict) else ""
    if _jev_note:
        cover += f" · Jev：{_jev_note}"
    pairs.append(("数据覆盖", _esc(cover)))
    # 每条数据线 1 主源 + 2 备用源：本次哪几路由备用源顶上，读者需要知道数据来自哪一路。
    # 入门版也保留：只在备用源真被启用时出现一行，属于「数据从哪来」的底线披露，不算过程文字。
    if backup_events:
        pairs.append(("备用源", _esc("本次启用：" + backup_events_text(list(backup_events)))))
    return pairs


# ------------------------------------------------------------
# 栏目标题（guizang / pixel 两个主题共用同一份标题）。历史栏目更名只影响显示文字；
# 数据源键名（全球头条 / 国家政策 / 每周走势预测 …）、审计标签、抓取与门禁保持独立。
# ------------------------------------------------------------
SECTION_TITLE_RETAIL_SENTIMENT = _senti_strategy.SECTION_TITLE
# 2026-09-30 新增（用户要求「内容再精炼，适合短线操作，入门观看」）：
# 末尾「短线速查卡」——≤600 字归纳今日动作要点，末尾附【新手三句话】（从百句股票梗句库读取配对）。
# 纯规则合成（output/octopus_short.py），数字全部取自下文各栏同一批实参；
# OCTOPUS_LITE=0 / --full 关闭，日报回到全量长版。
SECTION_TITLE_SHORT_CARD = "【闪电飞鱼】短线速查卡"
SECTION_TITLE_STRATEGY = "【六眼飞鱼】量化 MACD 策略"
SECTION_TITLE_STRATEGY_READ = SECTION_TITLE_STRATEGY
SECTION_TITLE_FORECAST = "【回游金枪鱼】今日预判"
# 刊头后独立的卷首栏；不占行情栏目 00..N 编号，也不参与数据新鲜度审计。
SECTION_TITLE_POETRY_SEA = "诗与远方的海"
SECTION_TITLE_ECON_CALENDAR = "【探照安康鱼】时间节点量化分析"
# 2026-10-10 更名：原「【火爆大鱿鱼】美联储因子量化分析」「【巡回巨鲸】地缘政治因子量化分析」；数据源键名
# （美联储趋势 / 地缘政治趋势）、像素关卡名 FED TREND / GEO TREND 不变。
SECTION_TITLE_FED_TREND = "【火爆大鱿鱼】美联储因子量化分析"
SECTION_TITLE_GEO_TREND = "【巡回巨鲸】地缘政治因子量化分析"
# 2026-10-11 新增：独立栏目，方法来自 vendored 的 UZI-Skill 规则引擎（tools/UZI-Skill）。
SECTION_TITLE_UZI_TREND = "【游资剑鱼】多专家流派趋势分析"
# 2026-10-23 按用户要求下线「【蜉蝣天地水母】量化分析总览」整栏（标题常量一并移除）；
# 港股概率模型仍在「每日趋势量化推演 · 港股概率走势分析」与「资金流动性分析」呈现。
SECTION_TITLE_MARKET_REVIEW = "【及时秋刀鱼】AI 行情复盘"
SECTION_TITLE_WEEKLY_FORECAST = "每日趋势量化推演"
SECTION_TITLE_SECTOR_ROTATION = "【滚滚翻车鱼】板块轮动量化策略"
# 2026-10-04 新增：原「每日量化策略（行业轮动）」的申万一级 31 行业版本（PR #84 的移植版）
SECTION_TITLE_INDUSTRY_ROTATION = "【巡游旗鱼】申万一级行业轮动"
SECTION_TITLE_POLICY = "【深海肥蓝鲸】政策因子"
SECTION_TITLE_TREND = "【深海大鲨鱼】趋势跟踪"
SECTION_TITLE_GLOBAL_HEADLINES = "【无敌帝王蟹】全球头条"
# 2026-10-10 更名：原「新闻情绪」；数据源键名、审计标签与 kicker（NEWS SENTIMENT）不变。
SECTION_TITLE_NEWS_SENTIMENT = "【亮亮灯光鱿鱼】新闻情绪因子量化分析"
# 2026-10-20 新增：A/H 成交活跃标的的媒体风险事件、来源权重、热度异常与分级处置。
SECTION_TITLE_MEDIA_RISK = "【警戒爆炸豚】媒体舆情风险点量化分析"
# 2026-10-21 新增：策略量化分析（图中 4 大类 6 细分，见 /strategy_quant.py）。
# 1 个总览 + 4 个大类栏目，均基于基准指数日线量化计算，内部衍生、可离线兜底。
SECTION_TITLE_STRATEGY_OVERVIEW = "【策略总览】量化策略全景"
SECTION_TITLE_STRATEGY_EQUITY = "【权益多头】量化分析"
SECTION_TITLE_STRATEGY_BOND = "【纯债策略】量化分析"
SECTION_TITLE_STRATEGY_CTA = "【CTA策略】量化分析"
SECTION_TITLE_STRATEGY_ARBITRAGE = "【套利策略·综合指数】量化分析"
STRATEGY_QUANT_SOURCE = "策略量化"
STRATEGY_QUANT_ENABLED = os.environ.get("OCTOPUS_STRATEGY_QUANT", "1").strip().lower() not in ("0", "false", "no")
# 合成演示序列开关：**默认关闭**（取不到日线就如实标暂缺，绝不编造数字）；
# 只有离线演示 / 测试显式设置 OCTOPUS_STRATEGY_DEMO=1 才用确定性合成序列兜底。
STRATEGY_QUANT_DEMO = os.environ.get("OCTOPUS_STRATEGY_DEMO", "0").strip().lower() in ("1", "true", "yes")

# 每个实际渲染的数据栏目都先输出栏首结论。data 属性只供回归测试/下游解析定位，
# 页面不可见；不要用标题文字做结构判断（主题与栏名会变）。
SECTION_AI_CONCLUSION_MARKER = 'data-octopus-section-ai-conclusion="1"'

# 正文逻辑顺序（2026-10-14 按用户要求重排）：
#   今日预判（置顶，用户要求保留在最前）
#   → ① 发生了什么：核心事实、关键信息与背景脉络
#   → ② 传播得怎么样：舆情声量、情感倾向、传播路径与关键节点
#   → ③ 可能会怎样：走势预测、潜在风险与影响范围
#   → ④ 我们该怎么办：分级处置、响应时间窗口与资源调配
#   → 总结（末尾）
# 各组内部顺序沿用重排前的相对次序；社区情绪因子使用当次 Reddit / StockTwits 样本，
# 没有可用样本时该栏缺席。
REPORT_FACT_SECTIONS = (                       # ① 发生了什么
    "MARKET REVIEW", "ECON CALENDAR",
    "POLICY SHOCK", "FED TREND", "GEO TREND",  # 政策 / 美联储 / 地缘为背景脉络，置于行情与日程之后
)
REPORT_SPREAD_SECTIONS = (                     # ② 传播得怎么样
    "RETAIL SENTIMENT", "TREND TRACKING",
    # 【沸腾花蛤】情绪热点因子量化分析（2026-10-13 新增，2026-10-19 更名）紧跟趋势跟踪，
    # 「内地口径」与「港股口径」相邻。
    "MAINLAND HOTLIST",
    # 具体风险事实优先于模糊情绪：先看结构化事件预警，再看标题情绪分。
    "MEDIA RISK", "NEWS SENTIMENT",
)
REPORT_OUTLOOK_SECTIONS = (                    # ③ 可能会怎样
    # 2026-10-23 起「QUANT FORECAST」下线（量化分析总览整栏取消），
    # 资金流动性与每日趋势量化推演两栏保留。
    "LIQUIDITY FLOW", "WEEKLY FORECAST",
)
REPORT_STRATEGY_SECTIONS = (                   # ④' 策略量化（图中 4 大类 6 细分）
    "STRATEGY OVERVIEW", "STRATEGY EQUITY", "STRATEGY BOND", "STRATEGY CTA", "STRATEGY ARBITRAGE",
)
REPORT_ACTION_SECTIONS = (                     # ④ 我们该怎么办
    "STRATEGY READ", "UZI TREND", "SECTOR ROTATION", "INDUSTRY ROTATION",
    *REPORT_STRATEGY_SECTIONS,
)
# 2026-10-02 起 GLOBAL HEADLINES（【无敌帝王蟹】全球头条）与 HK GURU CHANNELS
# （港股名家频道）按用户要求从页面隐藏，与此前隐藏的 EASTMONEY WIRE（东方财富快讯）
# 同口径：kicker 不再进入正文顺序表，即使某处误建区块也不会渲染；
# 抓取、审计、政策因子 / 策略研判 / 新闻情绪 / 逐栏 AI 研判的输入一律不变。
# 「专业分析」= 四组正文栏目的合集（保留原名供既有测试与引用使用）。
REPORT_ANALYSIS_SECTIONS = (
    *REPORT_FACT_SECTIONS, *REPORT_SPREAD_SECTIONS,
    *REPORT_OUTLOOK_SECTIONS, *REPORT_ACTION_SECTIONS,
)
# 2026-10-13 起「今日预判」（FORECAST）按用户要求放在正文最开头；「总结」仍在末尾。
REPORT_HEAD_SECTIONS = ("FORECAST",)
REPORT_TAIL_SECTIONS = ("SUMMARY",)
REPORT_SECTION_ORDER = (
    *REPORT_HEAD_SECTIONS,
    *REPORT_ANALYSIS_SECTIONS,
    *REPORT_TAIL_SECTIONS,
)


# ============================================================
# 逐栏目 AI 研判（规则合成）：概率化多空判断 + 分析预测总结
# —— 每个有实际数据的栏目末尾追加一行「⌁ AI 研判」：
#    多头 xx% / 空头 xx%（概率夹在 5%~95%，绝不绝对化）+ 一句判断/预测。
#    证据全部来自该栏目自身数据（涨跌方向 / 热度 / 关键词命中 / 归因结果），
#    确定性计算、可复现、不调外部大模型、不伪造内容；定位参考，非投资建议。
# ============================================================
# 趋势跟踪（多平台）的英文多空词与 $TICKER 提取：
# 覆盖 Reddit 热帖标题、StockTwits 平台摘要 / 情绪标签文案、TradingView 观点标题。
_TREND_BULL_RE = re.compile(
    r"\b(rall(?:y|ied)|surge\w*|soar\w*|pump\w*|moon\w*|yolo|bullish|breakout|rebound|"
    r"recover\w*|upgrade\w*|record high|all-?time high|beat\w*|boom\w*)\b", re.I)
_TREND_BEAR_RE = re.compile(
    r"\b(crash\w*|dump\w*|tank\w*|plunge\w*|selloff|bearish|short\w*|fud|scam|"
    r"bankrupt\w*|layoff\w*|warn\w*|loss\w*|correction|decline\w*|tumble\w*|"
    r"slump\w*|sank|sink\w*)\b", re.I)
_TREND_TICKER_RE = re.compile(r"\$([A-Za-z]{1,5})\b")
# 兼容并行分支旧名（全网新闻源头多空词表复用社区多空词）
_REDDIT_BULL_RE = _TREND_BULL_RE
_REDDIT_BEAR_RE = _TREND_BEAR_RE


def _ai_judge_prob(bull, bear):
    """多空证据量 → 多头概率（5%~95%）；证据持平 50%，全偏一侧最高 95%（绝不绝对化）。"""
    total = bull + bear
    if total <= 0:
        return 50
    return int(max(5, min(95, round(50 + 45 * (bull - bear) / total))))


def _ai_judge_label(prob):
    """概率 → 方向标记与多空定调（60% 以上偏多 / 40% 以下偏空 / 其间中性）。"""
    if prob >= 60:
        return "▲", "偏多"
    if prob <= 40:
        return "▼", "偏空"
    return "■", "中性"


def _judge_note(prob, text):
    mark, label = _ai_judge_label(prob)
    return {"bull_pct": prob, "bear_pct": 100 - prob, "mark": mark,
            "label": label, "text": text}


def _zh_title_bull_bear(titles):
    """中文标题词表命中计数（复用策略研判多/空词表）。"""
    bull = bear = 0
    for t in titles:
        txt = str(t or "")
        bull += sum(txt.count(w) for w in _AI_BULL_WORDS)
        bear += sum(txt.count(w) for w in _AI_BEAR_WORDS)
    return bull, bear


def _top_themes(titles, top_n=2):
    """按板块关键词命中量取主题；无任何命中时返回空（不猜）。"""
    counts = {}
    for name, words in AI_SECTOR_KEYWORDS.items():
        for t in titles:
            txt = str(t or "")
            hits = sum(txt.count(w) for w in words)
            if hits:
                counts[name] = counts.get(name, 0) + hits
    if not counts:
        return []
    return [name for name, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]]


# ============================================================
# AI趋势分析（美联储 / 地缘政治）—— 两个专题的确定性规则研判
# ------------------------------------------------------------
# 各自由「专门抓取」（Google News RSS 主题查询）供给标题，规则词表判定方向定调，
# 逐条引用命中证据；美联储板附财经日程中的相关时间点。无大模型、可复现、不伪造；
# 抓取失败整栏缺席，绝不以旧闻兜底。宽松 / 缓和记多头，紧缩 / 升温记空头。
# ============================================================
# 美联储：鹰派（紧缩倾向）/ 鸽派（宽松倾向）触发词（子串命中、叠加计数）
_FED_HAWK_WORDS = ["加息", "升息", "缩表", "鹰派", "紧缩", "通胀高企", "利率上调",
                   "上调利率", "加息预期", "限制性"]
_FED_DOVE_WORDS = ["降息", "减息", "鸽派", "宽松", "扩表", "购债", "暂停加息",
                   "放缓加息", "降息预期", "下调利率"]
# 地缘政治：升温（对抗倾向）/ 缓和（降温倾向）触发词
_GEO_HEAT_WORDS = ["制裁", "冲突", "战争", "紧张", "摩擦", "争端", "封锁", "断交",
                   "威胁", "对抗", "袭击", "军事", "报复", "升级"]
_GEO_CALM_WORDS = ["缓和", "停火", "谈判", "对话", "协议", "会晤", "互访", "降温",
                   "合作", "达成", "解除制裁", "降级", "共识", "休战"]
# 美联储板「未来相关时间点」筛选（财经日程条目名命中即展示）
_FED_EVENT_RE = re.compile(r"美联储|FOMC|议息|利率决议|非农|CPI|PPI|PCE|联储")


def _trend_topic_scan(headlines, positive_words, negative_words, exclude_titles=()):
    """扫描标题并按词表计数：返回 (正面命中, 负面命中, 证据列表, 重复数)。

    证据列表只收命中方向词的标题（含命中词明细）；与正文其他栏目重复的标题
    不重复展示、仍计入分析；每条都保留来源与发布时间可溯源。
    """
    pos = neg = dup_n = 0
    evidence = []
    exclude = {t for t in (exclude_titles or []) if t}
    for it in headlines or []:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "")
        if not title:
            continue
        pos_hits = [w for w in positive_words if w in title]
        neg_hits = [w for w in negative_words if w in title]
        pos += len(pos_hits)
        neg += len(neg_hits)
        if not pos_hits and not neg_hits:
            continue
        if title in exclude:
            dup_n += 1
            continue
        evidence.append({
            "title": title,
            "source": it.get("source") or "",
            "time": it.get("published_cst") or "",
            "url": it.get("url") or "",
            "pos_hits": pos_hits,
            "neg_hits": neg_hits,
        })
    return pos, neg, evidence, dup_n


def _trend_topic_verdict(pos, neg, positive_label, negative_label, middle_label):
    """方向定调：正面词多→正面定调，负面词多→负面定调，持平/全零→中性定调。"""
    if pos > neg:
        return positive_label
    if neg > pos:
        return negative_label
    return middle_label


def build_fed_trend_analysis(data, exclude_titles=()):
    """「【火爆大鱿鱼】美联储因子量化分析」：鹰鸽词表定调 + 命中证据 + 财经日程相关时间点。

    available=False 时不渲染整栏（抓取失败 / 无标题）。确定性规则，非投资建议。
    """
    src = data.get(FED_TREND_KEY) or {}
    headlines = src.get("headlines") or []
    if src.get("status") != "success" or not headlines:
        return {"available": False}
    dove, hawk, evidence, dup_n = _trend_topic_scan(
        headlines, _FED_DOVE_WORDS, _FED_HAWK_WORDS, exclude_titles)
    verdict = _trend_topic_verdict(dove, hawk, "偏鸽（宽松倾向）", "偏鹰（紧缩倾向）", "观望")
    # 财经日程里的相关时间点（仅展示子集；日程缺失只隐藏该子块）
    events = []
    cal = data.get("财经日历") or {}
    for it in (cal.get("items") or []):
        name = str((isinstance(it, dict) and it.get("name")) or "")
        if name and _FED_EVENT_RE.search(name):
            events.append({
                "date": it.get("date") or "",
                "time": it.get("time") or "",
                "name": name,
                "imp": it.get("imp") or 0,
            })
    events = events[:5]
    return {
        "available": True,
        "topic": "美联储",
        "verdict": verdict,
        "positive_label": "鸽派（宽松）",
        "negative_label": "鹰派（紧缩）",
        "positive_n": dove,
        "negative_n": hawk,
        "total": len([h for h in headlines if isinstance(h, dict)]),
        "evidence": evidence,
        "dup_n": dup_n,
        "events": events,
        "source": src,
    }


def build_geo_trend_analysis(data, exclude_titles=()):
    """「【巡回巨鲸】地缘政治因子量化分析」：升温/缓和词表定调 + 命中证据逐条引用。

    available=False 时不渲染整栏。确定性规则，非投资建议。
    """
    src = data.get(GEO_TREND_KEY) or {}
    headlines = src.get("headlines") or []
    if src.get("status") != "success" or not headlines:
        return {"available": False}
    calm, heat, evidence, dup_n = _trend_topic_scan(
        headlines, _GEO_CALM_WORDS, _GEO_HEAT_WORDS, exclude_titles)
    verdict = _trend_topic_verdict(calm, heat, "缓和（降温）", "升温（对抗）", "平稳")
    return {
        "available": True,
        "topic": "地缘政治",
        "verdict": verdict,
        "positive_label": "缓和（降温）",
        "negative_label": "升温（对抗）",
        "positive_n": calm,
        "negative_n": heat,
        "total": len([h for h in headlines if isinstance(h, dict)]),
        "evidence": evidence,
        "dup_n": dup_n,
        "events": [],
        "source": src,
    }


def _trend_section_stats(data):
    """趋势跟踪栏目的共享统计（「⌁ AI 研判」行与「🦑 AI帮你提鲜」块用同一份数字）。

    返回 None 表示没有可用样本（两行都不出现）；否则返回：
      live_platforms [(平台名, 源字典)] / items 样本列表 / bull / bear 多空词计数 /
      news_an 全网 36 源的 analysis（可为 None）/ groups_n 有数据的组数 /
      top_tickers 热股 TOP3（"代码×次数"）。
    """
    live_platforms = []
    for name in _active_public_site_names():
        src = data.get(name) or {}
        if src.get("status") == "success" and src.get("items"):
            live_platforms.append((name, src))
    news_src = data.get(HK_NEWS_SOURCE_NAME) or {}
    news_an = news_src.get("analysis") if news_src.get("status") == "success" else None
    if not live_platforms and not (isinstance(news_an, dict) and news_an.get("scanned")):
        return None
    items = [it for _n, src in live_platforms for it in src["items"] if isinstance(it, dict)]
    bull = bear = 0
    tickers = {}
    for it in items:
        text = " ".join(str(it.get(key) or "") for key in ("title", "detail"))
        bull += len(_TREND_BULL_RE.findall(text))
        bear += len(_TREND_BEAR_RE.findall(text))
        symbol = str(it.get("symbol") or "").strip().upper()
        if symbol:
            tickers[symbol] = tickers.get(symbol, 0) + 1
        for sym in _TREND_TICKER_RE.findall(str(it.get("title") or "")):
            key = sym.upper()
            if key != symbol:
                tickers[key] = tickers.get(key, 0) + 1
    if isinstance(news_an, dict):
        bull += int(news_an.get("bull") or 0)
        bear += int(news_an.get("bear") or 0)
    groups_n = len({it.get("community") for it in items if it.get("community")})
    top = [f"{s}×{c}" for s, c in sorted(tickers.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
    return {
        "live_platforms": live_platforms,
        "items": items,
        "bull": bull,
        "bear": bear,
        "news_an": news_an if isinstance(news_an, dict) else None,
        "groups_n": groups_n,
        "top_tickers": top,
    }


def build_section_ai_notes(data, *, policy=None, senti=None, fed_trend=None, geo_trend=None,
                           hotlist=None):
    """为有内容的数据栏目生成逐栏 AI 研判元数据（概率多空 + 预测）。

    返回 {kicker: note}；仅真实有数据的栏目出研判。结论型栏目
    （今日预判 / 策略研判 / 总结）本身即结论，不另生成 note。渲染时，栏首大白话块
    读取 note 的方向 / 概率；后续「⌁ AI 研判」只显示箭头前数据依据，避免重复结论。
    注意：text 内数据片段必须已 _esc（渲染端不再二次转义）。
    """
    notes = {}

    # ① 报价面（实时行情；渲染在【及时秋刀鱼】AI 行情复盘）：涨跌家数 + 最强/最弱 → 方向定调
    market = data.get("实时行情") or {}
    if market.get("status") == "success":
        rows = []
        for label, q in (market.get("quotes") or {}).items():
            pct = _percent_number((q or {}).get("change_pct"))
            if pct is not None:
                rows.append((str(label), pct))
        if rows:
            bull = round(sum(max(p, 0) for _, p in rows), 4)
            bear = round(sum(max(-p, 0) for _, p in rows), 4)
            prob = _ai_judge_prob(bull, bear)
            up_n = sum(1 for _, p in rows if p > 0)
            down_n = sum(1 for _, p in rows if p < 0)
            strongest, weakest = max(rows, key=lambda r: r[1]), min(rows, key=lambda r: r[1])
            if down_n == 0 and up_n > 0:
                verdict = "普涨格局，关注量能延续性"
            elif up_n == 0 and down_n > 0:
                verdict = "普跌格局，防御为主"
            else:
                verdict = "结构分化，跟随强势方向"
            notes["MARKET SNAPSHOT"] = _judge_note(
                prob, f"{len(rows)} 项报价 涨{up_n} / 跌{down_n}（最强 {_esc(strongest[0])}、"
                      f"最弱 {_esc(weakest[0])}）→ 预测：{verdict}")

    # ② A股大盘全景：市场宽度 + 成交额环比 + 领涨板块 → 三票合成
    pan = data.get("A股大盘全景") or {}
    if pan.get("status") == "success":
        b = pan.get("breadth") or {}
        t = pan.get("turnover") or {}
        lead = ((pan.get("sectors") or {}).get("leading") or [{}])[0]
        bull = bear = 0
        up, down = b.get("up") or 0, b.get("down") or 0
        if up > down:
            bull += 2 if (b.get("ratio") or 0) >= 1.2 else 1
        elif down > up:
            bear += 2 if (b.get("ratio") or 0) <= 0.8 else 1
        chg = _percent_number(t.get("chg_pct"))
        if chg is not None:
            if chg > 1:
                bull += 1
            elif chg < -1:
                bear += 1
        lead_pct = _percent_number(lead.get("chg_pct"))
        if lead_pct is not None:
            if lead_pct >= 2:
                bull += 1
            elif lead_pct < 0:
                bear += 1
        prob = _ai_judge_prob(bull, bear)
        _mark, label = _ai_judge_label(prob)
        if label == "偏多":
            verdict = "宽度与情绪偏多，进攻略优"
        elif label == "偏空":
            verdict = "宽度与情绪偏空，防御优先"
        else:
            verdict = "震荡结构，等量能定方向"
        bits = [f"宽度 {_esc(str(b.get('mood') or '—'))}",
                f"成交{'放量' if (chg or 0) > 0 else '缩量'}"]
        if lead.get("name"):
            bits.append(f"领涨 {_esc(str(lead['name']))}")
        notes["GLOBAL PANORAMA"] = _judge_note(prob, "，".join(bits) + f" → 预测：{verdict}")

    # ③ 政策因子：PSI 方向 + 受益/承压行业 + 量化趋势分 → 实施节奏预测
    if isinstance(policy, dict) and policy.get("available"):
        score = int(policy.get("broad_score") or 0)
        prob = _ai_judge_prob(max(score, 0), max(-score, 0))
        _mark, label = _ai_judge_label(prob)
        if label == "偏多":
            verdict = "政策顺风，关注未来 15 日落地节奏"
        elif label == "偏空":
            verdict = "政策压力，关注受影响行业回撤"
        else:
            verdict = "政策中性，关注边际变化"
        detail = f"方向 {_esc(str(policy.get('broad_label') or '中性'))}"
        winners = policy.get("winners") or []
        losers = policy.get("losers") or []
        if winners:
            detail += "，受益 " + "、".join(_esc(str(w.get('name'))) for w in winners[:2])
        if losers:
            detail += "，承压 " + "、".join(_esc(str(l.get('name'))) for l in losers[:2])
        notes["POLICY SHOCK"] = _judge_note(prob, f"{detail} → 预测：{verdict}")

    # ③b AI趋势分析（美联储 / 地缘政治）：宽松·缓和记多头，紧缩·升温记空头
    for kick, res in (("FED TREND", fed_trend), ("GEO TREND", geo_trend)):
        if not (isinstance(res, dict) and res.get("available")):
            continue
        prob = _ai_judge_prob(res.get("positive_n") or 0, res.get("negative_n") or 0)
        _mark, label = _ai_judge_label(prob)
        topic = res.get("topic") or ""
        detail = (f'{_esc(topic)}定调 {_esc(str(res.get("verdict") or "—"))}，'
                  f'{_esc(str(res.get("positive_label") or ""))} {int(res.get("positive_n") or 0)} / '
                  f'{_esc(str(res.get("negative_label") or ""))} {int(res.get("negative_n") or 0)}'
                  f'（扫描 {int(res.get("total") or 0)} 条）')
        if topic == "美联储":
            outlook = {"偏鸽（宽松倾向）": "流动性预期转松，风险资产相对占优",
                       "偏鹰（紧缩倾向）": "利率预期承压，估值敏感资产相对受抑",
                       "观望": "信号混杂，等待议息与数据确认"}.get(str(res.get("verdict")), "等待更多信号")
        else:
            outlook = {"缓和（降温）": "风险偏好修复，避险资产边际回落",
                       "升温（对抗）": "避险情绪升温，黄金与能源相对占优",
                       "平稳": "地缘溢价平稳，市场按自身节奏定价"}.get(str(res.get("verdict")), "等待更多信号")
        notes[kick] = _judge_note(prob, f"{detail} → 预测：{outlook}")

    # ④ 趋势跟踪（多平台信息员）：多空词命中 + 热股提取 → 散户与交易员情绪判断
    #    统计走 _trend_section_stats 共享 helper：「⌁ AI 研判」行与「🦑 AI帮你提鲜」块
    #    引用同一批数字，不允许两处各算一套。
    trend_stats = _trend_section_stats(data)
    if trend_stats:
        live_platforms = trend_stats["live_platforms"]
        items = trend_stats["items"]
        bull = trend_stats["bull"]
        bear = trend_stats["bear"]
        news_an = trend_stats["news_an"]
        groups_n = trend_stats["groups_n"]
        top = trend_stats["top_tickers"]
        prob = _ai_judge_prob(bull, bear)
        _mark, label = _ai_judge_label(prob)
        names = "、".join(name for name, _src in live_platforms)
        if live_platforms:
            detail = f"多平台 {len(live_platforms)} 个信息员（{names}）扫描 {len(items)} 条样本（{groups_n} 组有数据）"
        else:
            detail = "社区样本缺席"
        if top:
            detail += "，热股 " + "、".join(_esc(t) for t in top)
        if isinstance(news_an, dict):
            detail += (f"；20 源扫描 {int(news_an.get('scanned') or 0)} 条 · 港股相关 "
                       f"{int(news_an.get('hk_n') or 0)} 条")
            themes = news_an.get("themes") or []
            if themes:
                detail += "，热点 " + "、".join(_esc(s) for s in themes)
        detail += f"，多空词 {bull} 多 / {bear} 空"
        notes["TREND TRACKING"] = _judge_note(
            prob, f"{detail} → 预测：散户与交易员情绪{label}，关注高热标的与基本面背离（观点非事实，非投资建议）")

    # ⑤ 资讯类栏目：全球头条 / 东财快讯（多空词 + 热门主题）
    for kick, source_key, noun in (("GLOBAL HEADLINES", "全球头条", "条头条"),
                                   ("EASTMONEY WIRE", "东财快讯", "条快讯")):
        src = data.get(source_key) or {}
        titles = []
        for h in (src.get("headlines") or []):
            t = h if isinstance(h, str) else str((h or {}).get("title") or "")
            if t:
                titles.append(t)
        if not titles:
            continue
        bull, bear = _zh_title_bull_bear(titles)
        prob = _ai_judge_prob(bull, bear)
        _mark, label = _ai_judge_label(prob)
        themes = _top_themes(titles)
        detail = f"{len(titles)} {noun}：多空词 {bull} 多 / {bear} 空"
        if themes:
            detail += "，热门主题 " + "、".join(_esc(t) for t in themes)
        watch = _esc(themes[0]) if themes else "后续进展"
        notes[kick] = _judge_note(prob, f"{detail} → 预测：头条情绪{label}，关注 {watch}")
        # 主题列表随研判行一并带出：「AI帮你提鲜」与 ⌁ AI 研判共用同一份，不另算一套。
        notes[kick]["themes"] = themes

    # ⑥ 港股名家频道：更新频道数 + 观点词命中 → 名家观点定调
    yt = data.get("港股名家频道") or {}
    yt_live = yt.get("channels") or []
    if yt_live:
        titles = [str(v.get("title") or "")
                  for ch in yt_live for v in (ch.get("videos") or [])]
        titles = [t for t in titles if t]
        bull, bear = _zh_title_bull_bear(titles)
        active_n = sum(1 for ch in yt_live if ch.get("is_today"))
        prob = _ai_judge_prob(bull, bear)
        _mark, label = _ai_judge_label(prob)
        themes = _top_themes(titles, top_n=1)
        focus = _esc(themes[0]) if themes else "大盘技术面"
        notes["HK GURU CHANNELS"] = _judge_note(
            prob, f"今日 {active_n} 频道有新内容，观点 {bull} 多 / {bear} 空"
                  f" → 预测：名家观点整体{label}，关注：{focus}")

    # ⑦ 新闻情绪：已归因个股的正负命中合计 → 整体新闻情绪
    if isinstance(senti, dict) and senti.get("total_matched"):
        stocks = [s for s in (senti.get("stocks") or []) if isinstance(s, dict)]
        if stocks:
            bull = sum(int(s.get("pos") or 0) for s in stocks)
            bear = sum(int(s.get("neg") or 0) for s in stocks)
            prob = _ai_judge_prob(bull, bear)
            _mark, label = _ai_judge_label(prob)
            best = max(stocks, key=lambda s: float(s.get("score") or 0))
            worst = min(stocks, key=lambda s: float(s.get("score") or 0))
            notes["NEWS SENTIMENT"] = _judge_note(
                prob, f"归因 {senti.get('total_matched')} 只（前 {len(stocks)} 只评分），"
                      f"最强 {_esc(str(best.get('name')))}、最弱 {_esc(str(worst.get('name')))}"
                      f" → 预测：新闻情绪{label}，关注情绪与价格背离")

    # ⑧ 情绪热点因子量化分析（原内地财经热点榜，2026-10-19 接入研判行）：
    #    情绪词典的多/空计数当证据量（与⑦新闻情绪同一合成规则），附热点聚合前两位
    #    与最高等级预警风险点。证据全部来自 build_mainland_hotlist() 的同一份结果，
    #    不另算一套；词典启发式，不是校准概率。
    if isinstance(hotlist, dict) and hotlist.get("status") == "success":
        agg = hotlist.get("sentiment_agg") or {}
        if agg.get("has_data"):
            risk = hotlist.get("risk_report") or {}
            bull = int(agg.get("pos_n") or 0)
            bear = int(agg.get("neg_n") or 0)
            prob = _ai_judge_prob(bull, bear)
            _mark, label = _ai_judge_label(prob)
            detail = (f'{int(hotlist.get("total") or 0)} 条标题：情绪 {bull} 多 / {bear} 空'
                      f'（中性 {int(agg.get("neu_n") or 0)}，词典启发式）')
            clusters = (hotlist.get("hotspots") or {}).get("clusters") or []
            hot_terms = [str(c.get("term")) for c in clusters[:2]
                         if isinstance(c, dict) and c.get("term")]
            if hot_terms:
                detail += "，热点聚合 " + "、".join(_esc(t) for t in hot_terms)
            points = [p for p in (risk.get("points") or []) if isinstance(p, dict)]
            if points:
                top = points[0]
                detail += (f'，预警风险点 {int(risk.get("points_total") or len(points))} 类'
                           f'（最高「{_esc(str(top.get("category") or ""))}」'
                           f'【{_esc(str(top.get("level") or ""))}】{int(top.get("count") or 0)} 条）')
                verdict = f'内地情绪面{label}，优先核对「{_esc(str(top.get("category") or ""))}」证据'
            else:
                verdict = f"内地情绪面{label}，风险词表未命中（未命中 ≠ 没有风险）"
            notes["MAINLAND HOTLIST"] = _judge_note(
                prob, f"{detail} → 预测：{verdict}（非校准概率，不构成投资建议）")

    return notes


# 合并栏目【及时秋刀鱼】AI 行情复盘保留原两栏各自的研判口径：
#   报价面   = 原「行情速览」证据（逐项涨跌方向 + 最强/最弱）；
#   A股全景面 = 原「全球大盘全景复盘」证据（涨跌家数 / 成交额 / 板块热力投票）。
# 两套口径的证据与算法不同，各出一行研判，不合成一个没有依据的概率；
# notes 的键名保持不变（MARKET SNAPSHOT / GLOBAL PANORAMA），只是渲染到同一栏。
MERGED_SECTION_NOTES = {
    "MARKET REVIEW": (("报价面", "MARKET SNAPSHOT"), ("A股全景面", "GLOBAL PANORAMA")),
}


def _section_note_keys(kicker):
    """栏目 → 需要展示的研判依据 [(标签, notes 键), ...]；未合并的栏目就是它自己。"""
    return MERGED_SECTION_NOTES.get(kicker) or (("", kicker),)


def _section_note_for_evidence(note):
    """栏首已有大白话结论时，把旧「AI 研判」降为量化依据，避免重复说结论。

    ``build_section_ai_notes`` 的 text 通常是「本栏数字 → 预测：方向」。大白话块已经承担
    方向结论，因此这里只保留箭头前的同源数字；概率与方向标签仍由 `_ai_judge_row`
    展示。无法识别旧格式时原样保留，宁可多披露证据，也不猜写新内容。
    """
    copied = dict(note or {})
    text = str(copied.get("text") or "")
    if "→ 预测：" in text:
        text = text.split("→ 预测：", 1)[0].rstrip(" ，；。")
        if text:
            text += "。"
    copied["text"] = text
    return copied


def _section_notes_html(kicker, notes, kit, *, evidence_only=False, date_str=""):
    """渲染某栏的同源量化研判；合并栏可保留多套互不相同的证据。"""
    rows = []
    for note_label, note_key in _section_note_keys(kicker):
        note = (notes or {}).get(note_key)
        if not note:
            continue
        shown = _section_note_for_evidence(note) if evidence_only else note
        rows.append(_ai_judge_row(
            shown, kit, aspect=note_label,
            seed=f"{date_str}|{kicker}|{note_key}|{note_label}",
            evidence_only=evidence_only,
        ))
    return "".join(rows)


def _rendered_section_fallback_conclusion(kicker):
    """已有正文但专用翻译器证据不足时的诚实栏首结论；不新增数字或方向。"""
    noun = {
        "FORECAST": "预判", "ECON CALENDAR": "日程",
        "HK PROBABILITY": "概率结果", "LIQUIDITY FLOW": "资金结果",
        "WEEKLY FORECAST": "逐日推演", "MARKET REVIEW": "行情复盘",
        "RETAIL SENTIMENT": "社区情绪", "MEDIA RISK": "媒体风险证据",
        "POLICY SHOCK": "政策信号", "FED TREND": "美联储信号", "GEO TREND": "地缘信号",
        "STRATEGY READ": "策略结果", "UZI TREND": "规则评分", "TREND TRACKING": "趋势样本",
        "SECTOR ROTATION": "板块评分", "INDUSTRY ROTATION": "行业评分",
        "GLOBAL HEADLINES": "头条", "EASTMONEY WIRE": "快讯", "HK GURU CHANNELS": "频道观点",
        "NEWS SENTIMENT": "新闻情绪", "MAINLAND HOTLIST": "媒体热度", "HK 7D PROB": "七日结果",
        "SUMMARY": "总结",
    }.get(kicker, "数据")
    return (f"本栏已有{noun}，但现有证据不足以支持更明确的单一方向，所以不硬判涨跌。"
            "小散户先看正文的核心数字、样本量和数据日期；看不懂就先观察，不把缺项或中性硬翻成买卖信号。")


def _ai_judge_row(note, kit, aspect="", seed="", evidence_only=False):
    """逐栏 AI 研判行（两主题共用）。

    默认保留历史完整样式：方向 + 多空概率 + 判断预测。``evidence_only=True`` 用于栏首
    已有「AI帮你提鲜」结论的页面：标题仍保留为「⌁ AI 研判（…）」供读者识别口径，
    但只写「数据依据」和箭头前的同源数字，不再重复方向、概率条或预测句。

    aspect：合并栏目（【及时秋刀鱼】AI 行情复盘）里标明这一行是哪一路证据
    （报价面 / A股全景面），两套口径各自独立，不混算成一个数。
    seed：🦐 活鲜点缀的确定性种子（含日期 + 栏目），同一天同一栏永远同一句比喻；
    点缀只加在完整研判文字上，note["text"] 本体不动，不影响原始研判数据。
    """
    bull_c, bear_c, flat_c = kit.ok_color, kit.bad_color, kit.warn_color
    lc = (bull_c if note["label"] == "偏多"
          else bear_c if note["label"] == "偏空" else flat_c)
    title = f"⌁ AI 研判（{aspect}）" if aspect else "⌁ AI 研判"
    if evidence_only:
        if _is_guizang_like(kit):
            head = (f'<b style="color:{GZ_KLEIN}">{title}</b>'
                    f' · <b style="color:{GZ_FAINT}">数据依据</b>')
        else:
            head = (f'<span style="color:{C_CYAN};font-weight:900;">{title}</span>'
                    f' · <span style="color:{C_MUTED};font-weight:900;">数据依据</span>')
        return kit.item_row("⌁", f"{head} — {note['text']}")
    if _is_guizang_like(kit):
        head = (f'<b style="color:{lc}">{title} {note["mark"]} {note["label"]}</b>'
                f' · <b style="color:{bull_c}">多头 {note["bull_pct"]}%</b>'
                f' / <b style="color:{bear_c}">空头 {note["bear_pct"]}%</b>')
    else:
        head = (f'<span style="color:{lc};font-weight:900;">{title} {note["mark"]} {note["label"]}</span>'
                f' · <span style="color:{bull_c};font-weight:900;">多头 {note["bull_pct"]}%</span>'
                f' / <span style="color:{bear_c};font-weight:900;">空头 {note["bear_pct"]}%</span>')
    try:
        tail = _lex.garnish_judgment(note.get("label"), note.get("bull_pct"),
                                     seed or f'{note.get("label")}|{aspect}')
    except Exception:
        tail = ""
    text = f"{note['text']}（{tail}）" if tail else note["text"]
    return kit.item_row("⌁", f"{head} — {text}")


def _ren_judgment_row(text, kit, meta=None):
    """逐栏「🦑 AI帮你提鲜」栏首结论区块（两主题共用）。

    2026-10-20 起从栏目末尾前置到正文开头：先给小散户大白话结论，再列量化依据
    与正文数据；旧「⌁ AI 研判」只保留同源数字依据，避免重复说同一个方向。

    更鲜明突出的版式（2026-10-06 改版）：
      · 整块独立描边成区（pixel：青色硬边框 + 实色阴影；guizang 系：克莱因蓝粗左线），
        在栏目里一眼可辨，是一块自己的内容区域；
      · 字符图：头部 █▓▒░ 渐变条 + 概率几率条 ▓▓▓▓▓░░░░░（每格 10%，双段上色）；
      · 概率 / 几率：meta.p_pct 与「⌁ AI 研判」行同源（_garnish_dir 同一套取数），
        这里只画图不算数；几率「涨 52 ： 48 跌」只是同一概率的另一种写法，不造新数字；
        栏目没有概率 → 几率条整条缺席，只出字符图头 + 大白话正文（缺数据不装样子）。
    text 由 octopus_ren 规则合成（纯文本，这里统一转义）；
    🦑 直接写进文字头（guizang 主题的行函数不渲染图标格，两主题都要能看到）；
    副行固定小字口径「规则合成 · 大白话翻译，非投资建议」，与整仓诚实文化一致
    （入门版不出副行，页脚统一保留「非投资建议」）。
    """
    gz = _is_guizang_like(kit)
    meta = meta if isinstance(meta, dict) else {}
    text = str(text or "")
    label = str(meta.get("label") or "")
    p_pct = meta.get("p_pct")
    meter = _ren.fresh_meter(p_pct)          # None（无概率 / 非法）→ 几率条整条缺席
    if gz:
        ink, muted = GZ_INK, GZ_FAINT
        up_c, dn_c, mid_c = kit.ok_color, kit.bad_color, kit.warn_color
        # 归藏系无红绿：▓ 用页面唯一的克莱因蓝（强调色）、░ 用深灰——两段一眼可辨，
        # 方向交给 ▲▼■ + label + 大数字，不靠颜色硬编涨跌。
        bar_fill_c, bar_empty_c = GZ_KLEIN, GZ_FAINT
        box = (f'border:1px solid {GZ_HAIR};border-left:4px solid {GZ_KLEIN};'
               f'background:{GZ_KLEIN_WASH};')
        head_row = (f'<tr><td width="28%" valign="top" style="padding:8px 10px 4px;font-size:12px;font-weight:400;'
                    f'color:{GZ_KLEIN};line-height:1.5;font-family:{FONT_MONO};border-bottom:1px solid {GZ_HAIR_SOFT};">'
                    f'█▓▒░ {_ren.REN_ICON} <span style="letter-spacing:1px;">{_esc(_ren.REN_TITLE)}</span> ░▒▓█</td>'
                    f'<td valign="top" style="padding:8px 10px 4px;font-size:9px;font-weight:400;color:{GZ_FAINT};'
                    f'line-height:1.5;font-family:{FONT_MONO};border-bottom:1px solid {GZ_HAIR_SOFT};">'
                    f'本栏 AI 结论 · 大白话 · 先结论后证据</td></tr>')
    else:
        ink, muted = C_INK, C_MUTED
        up_c, dn_c, mid_c = C_GREEN, C_RED, C_AMBER
        bar_empty_c = C_FAINT                # ░ 恒用暗灰；▓ 的颜色在方向分支里定
        box = f'border:1px solid {C_CYAN};background:#0A0E1D;box-shadow:5px 5px 0 #000;'
        head_row = (f'<tr><td width="28%" valign="top" style="padding:5px 10px;background:{C_CYAN};color:{C_BG};'
                    f'font-size:10px;font-weight:400;letter-spacing:1px;font-family:{FONT_MONO};">'
                    f'█▓▒░ {_ren.REN_ICON} {_esc(_ren.REN_TITLE)} ░▒▓█</td>'
                    f'<td valign="top" style="padding:5px 10px;background:{C_CYAN};color:{C_BG};'
                    f'font-size:8px;font-weight:400;letter-spacing:2px;font-family:{FONT_MONO};">'
                    f'// 本栏 AI 结论 · 大白话 · 先结论后证据</td></tr>')

    # 方向与上色：偏多 → 涨色 ▲、偏空 → 跌色 ▼、其余 → 中性色 ■（不只靠颜色区分）。
    if "偏多" in label:
        mark, dir_c = "▲", up_c
    elif "偏空" in label:
        mark, dir_c = "▼", dn_c
    else:
        mark, dir_c = "■", mid_c
    if not gz:
        bar_fill_c = dir_c            # pixel：▓ 跟方向色（绿 / 红 / 琥珀），░ 用暗灰

    meter_html = ""
    if meter:
        p_int = int(round(float(p_pct)))
        label_html = (f' <span style="font-size:10px;font-weight:400;color:{muted};">'
                      f'{_esc(label)}</span>') if label else ""
        bar = (f'<span style="color:{bar_fill_c};">{"▓" * meter["filled"]}</span>'
               f'<span style="color:{bar_empty_c};">{"░" * meter["empty"]}</span>')
        meter_html = (
            f'<tr><td width="28%" valign="top" style="padding:8px 10px 4px;font-size:8px;font-weight:400;'
            f'letter-spacing:1px;color:{muted};font-family:{FONT_MONO};border-bottom:1px dashed {GZ_HAIR_SOFT if gz else C_HAIR};">'
            f'涨跌概率 / 几率 ODDS METER</td>'
            f'<td valign="top" style="padding:8px 10px 4px;border-bottom:1px dashed {GZ_HAIR_SOFT if gz else C_HAIR};">'
            f'<div style="font-size:16px;font-weight:400;color:{dir_c};line-height:1.35;'
            f'font-family:{FONT_MONO};">{mark} 上涨概率 {p_int}%{label_html}</div>'
            f'<div style="font-size:12px;font-weight:400;line-height:1.5;font-family:{FONT_MONO};'
            f'letter-spacing:3px;padding-top:1px;">{bar}'
            f'<span style="font-size:9px;font-weight:400;letter-spacing:0;color:{muted};">'
            f' 几率 {_esc(meter["odds"])} · 每格 10% · 与研判行同源</span></div></td></tr>')

    sub_html = (f'<div style="font-size:9px;color:{muted};letter-spacing:.3px;'
                f'padding-top:6px;line-height:1.6;font-family:{FONT_MONO};">'
                f'{_esc(_ren.DISCLAIMER)}</div>') if not PLAIN() else ""
    # AI 结论表也是表格：整表字号收一号、字重统一常规（见 GZ_W_TABLE / 2026-10-23 用户要求）。
    return (f'<table {SECTION_AI_CONCLUSION_MARKER} width="100%" cellpadding="0" cellspacing="0"'
            f' style="width:100%!important;border-collapse:collapse;margin-top:10px;'
            f'font-weight:{GZ_W_TABLE};{box}">'
            f'{head_row}'
            f'{meter_html}'
            f'<tr><td width="28%" valign="top" style="padding:8px 10px 10px;font-size:10px;font-weight:400;'
            f'color:{muted};line-height:1.75;font-family:{FONT_MONO};">本栏结论</td>'
            f'<td valign="top" style="padding:8px 10px 10px;font-size:11px;color:{ink};line-height:1.75;'
            f'font-family:{FONT_MONO};">{_esc(text)}{sub_html}</td></tr></table>')


def _weekly_daily_table(daily, kit):
    """逐日表格（未来 7 个交易日）：一行一天，只放**扫一眼就能读**的预测数字。

    列 = 交易日 / 预测（方向 + 累计上涨概率）/ 当日环比 / 预期区间（80% 中心）/ 建议仓位；
    理由、分析、AI 操作建议的长文本放在下面的逐日卡里，数字不在两处重复出现。
    """
    rows = daily.get("rows") or []
    if not rows:
        return ""
    esc = kit.esc
    grid = []
    for r in rows:
        adv = r.get("advice") or {}
        day = f'T+{int(r.get("k") or 0)} · {esc(str(r.get("date") or "")[5:])} {esc(str(r.get("weekday") or ""))}'
        pred = esc(str(r.get("label") or ""))
        p_day = r.get("p_day")
        dod = "—" if p_day is None else f'{p_day * 100:.0f}%'
        lo, hi = r.get("band_lo"), r.get("band_hi")
        band = f'{lo:,.0f}–{hi:,.0f}' if (lo and hi) else "—"
        pos = adv.get("position")
        pos_txt = f'≤{int(pos)}%' if pos is not None else "—"
        grid.append([day, pred, dod, band, pos_txt])
    header = ["交易日", "预测（累计上涨概率）", "当日环比", "预期区间（80%）", "建议仓位"]
    aligns = ["left", "left", "right", "right", "right"]
    return kit.table(header, grid, aligns=aligns)


def _weekly_daily_cards(daily, kit):
    """逐日理由 · 分析 · AI 操作建议：一天一张卡，长文本在这里展开（不与表格重复数字）。

    精简模式（默认）：一天压成一行——只留**动手要用的三件事**（态度 / 止损 / 止盈）+
    事件日提醒；理由与分析的长文本折叠成一句「共同驱动」（7 天的动量 / 波动 / 基准率
    本来就是同一批数字，逐日复述等于刷屏），并如实写明「逐日理由已折叠，--full 看全文」。
    """
    rows = daily.get("rows") or []
    if not rows:
        return ""
    esc = kit.esc
    if LITE_ENABLED:
        plain = PLAIN()
        # 入门版：7 天同一句 ⚠ 提醒（如「低波动环境，止损从紧」）只在卡组末尾写一次，
        # 不逐日刷屏；各天不同的提醒仍逐日跟在当天行下。
        day_warns = [[str(x) for x in ((r.get("advice") or {}).get("notes") or [])[1:-1]][:1]
                     for r in rows]
        shared_warn = ""
        if plain:
            flat = [w[0] for w in day_warns if w]
            if flat and len(set(flat)) == 1 and len(flat) == len(rows):
                shared_warn = flat[0]
        cards = []
        for r, warns in zip(rows, day_warns):
            adv = r.get("advice") or {}
            icon = {"up": "▲", "down": "▼"}.get(r.get("direction"), "■")
            bits = []
            if adv.get("stop_pct") is not None:
                stop_price = adv.get("stop_price")
                bits.append(f'止损 {adv["stop_pct"] * 100:.1f}%'
                            + (f'（{stop_price:,.0f}）' if stop_price else ""))
            if adv.get("take_profit"):
                bits.append(f'止盈 {adv["take_profit"]:,.0f}')
            # 事件日提醒（adv.notes 里以 ⚠ 开头的那几条）：短线客最该看见的一行
            line = f'<b>{esc(str(adv.get("stance") or ""))}</b>'
            if bits:
                line += " · " + " · ".join(bits)
            if adv.get("entry_hint"):
                line += f'<br>建仓 · {esc(str(adv["entry_hint"]))}'
            if warns and not shared_warn:
                line += "<br>" + "<br>".join(f"⚠ {esc(w)}" for w in warns[:1])
            cards.append(kit.item_row(
                icon, f'T+{int(r.get("k") or 0)} {esc(str(r.get("date") or "")[5:])}', line))
        if shared_warn:
            cards.append(kit.item_row("⚠", f"<b>7 天共同提醒</b> · {esc(shared_warn)}"))
        if plain:
            # 入门版：「共同驱动 / 逐日理由已折叠 / --full 看全文」属于过程交代，不出。
            return kit.rows("".join(cards))
        driver = str((rows[0].get("reason") or ""))
        head = driver.split("·")[0].strip(" ·") if driver else ""
        tail = (f'共同驱动 · {esc(head[:70])}（7 天同一批因子，逐日理由已折叠；'
                "--full 看全文）") if head else "逐日理由已折叠（--full 看全文）"
        return kit.rows("".join(cards)) + kit.item_row("▤", "<b>为什么</b>", tail)
    cards = []
    for r in rows:
        adv = r.get("advice") or {}
        icon = {"up": "▲", "down": "▼"}.get(r.get("direction"), "■")
        head = (f'{icon} <b>{esc(str(adv.get("stance") or ""))}</b> · '
                f'T+{int(r.get("k") or 0)} {esc(str(r.get("date") or "")[5:])} '
                f'{esc(str(r.get("weekday") or ""))}')
        lines = []
        if r.get("reason"):
            lines.append(f'<b>理由</b> · {esc(str(r["reason"]))}')
        if r.get("analysis"):
            lines.append(f'<b>分析</b> · {esc(str(r["analysis"]))}')
        # AI 操作建议：仓位（表格已给）之外的止损 / 止盈 / 建仓区，都是建议专有数字
        adv_bits = []
        if adv.get("stop_pct") is not None:
            stop_price = adv.get("stop_price")
            stop_txt = f'止损 {adv["stop_pct"] * 100:.1f}%'
            if stop_price:
                stop_txt += f'（{stop_price:,.0f}）'
            adv_bits.append(stop_txt)
        if adv.get("take_profit"):
            adv_bits.append(f'止盈参考 {adv["take_profit"]:,.0f}')
        if adv_bits:
            lines.append(f'<b>AI 操作建议</b> · {" · ".join(adv_bits)}')
        if adv.get("entry_hint"):
            lines.append(f'建仓 · {esc(str(adv["entry_hint"]))}')
        # 提醒：跳过 notes[0]（= T+k 持有口径 · 仓位，已在表格）与末条（统一免责，栏末只写一次）
        for extra in (adv.get("notes") or [])[1:-1]:
            lines.append(f'⚠ {esc(str(extra))}')
        cards.append(kit.item_row(icon, head, "<br>".join(lines)))
    return kit.rows("".join(cards))


def _weekly_forecast_block(res, kit):
    """【嗜血大白鲨】逐日走势量化分析栏目内容（两主题共用；res 见 fetch_weekly_forecast 的 result）。

    2026-09-29 起升级为**未来 7 个交易日逐日表格**：① 逐日表格（预测数字，一行一天）
    → ② 逐日理由 / 分析 / AI 操作建议（长文本卡）→ ③ 七日整段结论（P(7日涨) + 因子 +
    回测 + 留痕）→ ④ 无未来函数口径披露。结论型栏目：全部数字来自本次因果扫描与留痕文件，
    零写死叙事；日程只做「事件日提醒」，不参与概率。
    """
    entry = res.get("entry") or {}
    daily = res.get("daily") or {}
    if not entry or entry.get("p_up") is None:
        return ""
    esc = kit.esc
    horizon = int(res.get("horizon") or entry.get("target_sessions") or _weekly.PATH_MAX)
    out = []

    # ── ① 逐日表格 + ② 逐日理由/分析/AI 操作建议（栏目的主体，用户要的「未来七天表格」）──
    drows = daily.get("rows") or []
    if drows:
        sym = esc(str(daily.get("symbol_label") or res.get("symbol_label")
                      or entry.get("symbol_label") or ""))
        plain = PLAIN()
        base_txt = (f'锚定 {esc(str(daily.get("base_date") or entry.get("base_date") or ""))}'
                    f' 收盘 {daily.get("base_close") or 0:,.0f}（{sym}）· '
                    f'未来 {horizon} 个交易日' + ("" if plain else " · 概率夹 5%~95%"))
        out.append(kit.sub(f"未来 {horizon} 个交易日 · 逐日走势预测（{sym}）"))
        out.append(kit.item_row("◧", f"<b>逐日表格</b>", base_txt))
        out.append(_weekly_daily_table(daily, kit))
        out.append(kit.sub("逐日操作建议" if plain else "逐日理由 · 分析 · AI 操作建议"))
        out.append(_weekly_daily_cards(daily, kit))

    # ── ③ 七日整段结论（= 逐日表格第 7 行的累计口径，同一批数字，不另算一套）──
    p_up = float(entry["p_up"])
    icon = {"up": "▲", "down": "▼"}.get(entry.get("direction"), "■")
    out.append(kit.sub(f"七日整段结论（{horizon} 个交易日累计）"))
    if PLAIN():
        # 入门版：结论 + 概率 + 因子数字 + 已结算的命中率；口径推导、样本合成、
        # 留痕状态与无未来函数披露属于说明文字 / 过程文字，不出。
        label_txt = str(entry.get("label") or "")
        concl = [kit.item_row(icon, f'<b>{esc(label_txt)}</b>',
                              "" if "P(" in label_txt else f'P({horizon}日涨) {p_up * 100:.0f}%')]
        f = entry.get("factors") or {}
        bits = [f'{label} {float(f[key]) * 100:+.1f}%'
                for key, label in (("ret5", "5日"), ("ret10", "10日"), ("ret20", "20日"))
                if f.get(key) is not None]
        sub_bits = []
        if f.get("vol20") is not None:
            sub_bits.append(f'20日波动 {float(f["vol20"]) * 100:.2f}%')
        if f.get("dd20") is not None:
            sub_bits.append(f'距20日高点 {float(f["dd20"]) * 100:+.1f}%')
        if bits:
            concl.append(kit.item_row("▤", " · ".join(bits), " · ".join(sub_bits)))
        bt = res.get("backtest") or {}
        if bt.get("hit_rate") is not None:
            concl.append(kit.item_row(
                "↺", f'历史回测 {int(bt.get("n") or 0)} 期 · 命中 {bt["hit_rate"] * 100:.0f}%'
                     f'（基准 {bt["base_rate"] * 100:.0f}%）'))
        jr = res.get("journal") or {}
        if jr.get("hit_rate") is not None:
            concl.append(kit.item_row(
                "✓", f'预测复盘 · 已结算 {int(jr.get("n") or 0)} 次 · 命中 '
                     f'{int(jr.get("hits") or 0)}（{jr["hit_rate"] * 100:.0f}%）'))
        out.append(kit.rows("".join(concl)))
        return "".join(out)
    concl = [kit.item_row(
        icon, f'<b>{esc(str(entry.get("label") or ""))}</b>',
        f'= 逐日表格第 {horizon} 行累计口径 · {esc(str(entry.get("target_note") or ""))}')]

    # 概率拆解：基准率 + 相似样本 + 合成规则（不足则如实退化）
    if entry.get("blended") and entry.get("p_sim") is not None:
        prob_sub = (f'历史基准 {float(entry.get("p_base") or 0.5) * 100:.0f}% · '
                    f'相似样本 {float(entry["p_sim"]) * 100:.0f}%'
                    f'（{int(entry.get("n_analog") or 0)} 个已结算近邻） · '
                    f'已结算 {int(entry.get("n_resolved") or 0)} 个 {horizon} 日样本为底 · '
                    f'50/50 合成夹 5%~95%')
    else:
        prob_sub = (f'相似样本不足 {_weekly.MIN_ANALOGS} 个，退化为历史基准 '
                    f'{float(entry.get("p_base") or 0.5) * 100:.0f}%'
                    f'（已结算 {int(entry.get("n_resolved") or 0)} 个样本）· 概率夹 5%~95%')
    concl.append(kit.item_row("P", f'P({horizon}日涨) {p_up * 100:.0f}%', prob_sub))

    # 关键因子（20 日窗口；全部 ≤t 数据，逐期扩张因果归一）
    f = entry.get("factors") or {}
    bits = [f'{label} {float(f[key]) * 100:+.1f}%'
            for key, label in (("ret5", "5日"), ("ret10", "10日"), ("ret20", "20日"))
            if f.get(key) is not None]
    sub_bits = []
    if f.get("vol20") is not None:
        vol_txt = f'20日波动 {float(f["vol20"]) * 100:.2f}%'
        if res.get("vol_pct") is not None:
            vol_txt += f'（扩张分位 {res["vol_pct"] * 100:.0f}%）'
        sub_bits.append(vol_txt)
    if f.get("dd20") is not None:
        sub_bits.append(f'距20日高点 {float(f["dd20"]) * 100:+.1f}%')
    if bits:
        concl.append(kit.item_row("▤", " · ".join(bits), " · ".join(sub_bits)))

    # 滚动样本外体检（walk-forward；样本 <10 只报样本量）
    bt = res.get("backtest") or {}
    if bt.get("hit_rate") is not None:
        concl.append(kit.item_row(
            "↺", f'{int(bt.get("n") or 0)} 期 · 命中 {bt["hit_rate"] * 100:.0f}%'
                 f'（恒定基准 {bt["base_rate"] * 100:.0f}%）· Brier {bt["brier"]:.3f}',
            f'滚动样本外（walk-forward）：每步只用 ≤t 数据打分 · 相邻窗口重叠 {horizon} 个交易日'))
    else:
        concl.append(kit.item_row(
            "↺", esc(str(bt.get("note") or "回测样本不足")),
            '滚动样本外（walk-forward）体检暂无结论'))

    # 预测留痕：先存档后结算；样本 <10 不下命中率结论；新旧视界分开记账
    jr = res.get("journal") or {}
    by_h = jr.get("by_horizon") or {}
    if jr.get("hit_rate") is not None:
        j_txt = (f'已结算 {int(jr.get("n") or 0)} 次 · 命中 {int(jr.get("hits") or 0)}'
                 f'（{jr["hit_rate"] * 100:.0f}%）')
    elif jr.get("n"):
        j_txt = f'已结算 {int(jr.get("n"))} 次（样本 <10，只报样本量）'
    else:
        j_txt = f'预测已存档（settled=False），待满 {horizon} 个交易日按真实收盘结算'
    if len(by_h) > 1:
        mix = "、".join(f'{h}日 {v["n"]} 次' + (f'（命中 {v["hit_rate"] * 100:.0f}%）'
                        if v.get("hit_rate") is not None else "")
                        for h, v in sorted(by_h.items()))
        j_txt += f' · 分视界：{mix}'
    recent = jr.get("recent") or []
    recent_txt = " · ".join(
        f'{esc(str(r.get("date") or ""))} '
        f'{"+" if float(r.get("ret") or 0) >= 0 else ""}{float(r.get("ret") or 0) * 100:.1f}% '
        f'{"✓" if r.get("hit") else "✗"}'
        for r in recent)
    concl.append(kit.item_row("✓", f'<b>预测留痕</b> · {j_txt}', recent_txt))
    out.append(kit.rows("".join(concl)))

    # ── ④ 无未来函数口径披露（截断不变性自检覆盖全部 7 个视界）──
    if LITE_ENABLED:
        # 精简模式：口径披露压成一行——**结论一句不删，细则指回全量版**（不静默丢披露）。
        out.append(kit.item_row(
            "⚖", f'<b>无未来函数口径</b> · 截断不变性自检通过'
                 f'（{esc(str(res.get("self_check") or ""))}）· 特征只用 ≤t 数据 · '
                 f'先存档后结算（weekly_forecast.json）· 仓位 / 止损为规则合成 · '
                 "非投资建议（方法细则 --full 看全文）"))
        return "".join(out)
    note = (f'<b>无未来函数口径</b> · 截断不变性自检通过（{esc(str(res.get("self_check") or ""))}）'
            f' · 逐日表格 {horizon} 行与整段结论出自同一次因果扫描（视界 1~{horizon} 各自独立记账）'
            f' · 特征只用 ≤t 数据（逐期扩张归一，绝无全样本统计量）'
            f' · 相似样本标签须已结算（s+h≤t，purged/embargo 依据）'
            f' · 预期区间为 80% 中心区间（z={_weekly.BAND_Z}，σ 取 20 日实测波动）'
            f' · AI 操作建议为规则合成（概率档位 → 仓位，波动分位 → 降杠杆，σ√k → 止损）'
            f' · 先存档后结算（weekly_forecast.json · settled 字段）'
            f' · 方法：{esc(str(res.get("method") or ""))} · 规则合成，非投资建议')
    out.append(kit.item_row("⚖", note))
    return "".join(out)


def _hk_seven_day_block(res, kit):
    """AI 七日港股走势分析概率栏目内容（两主题共用；res 见 fetch_hk_seven_day 的 result）。

    三只指数各一行（概率 / 依据 / 风险 / 量化基准偏离），加留痕与口径两行；
    引擎是大模型还是量化降级、有没有按基准收敛、数字溯源几条，都在栏内如实标出。
    """
    targets = res.get("targets") or []
    if not targets:
        return ""
    esc = kit.esc
    horizon = int(res.get("horizon") or _hk7.HORIZON)
    target_date = res.get("target_date")
    t_str = f' · 目标日 {esc(str(target_date))}' if target_date else ''
    rows = []
    plain = PLAIN()
    if plain:
        # 入门版：只交代锚定日 + 目标日；溯源条数 / 降级原因 / 概率夹等过程说明不出。
        head_sub = f'锚定 {esc(str(res.get("asof") or ""))} 收盘 · 未来 {horizon} 个交易日{t_str}'
    else:
        head_sub = (f'锚定 {esc(str(res.get("asof") or ""))} 收盘 · 未来 {horizon} 个交易日'
                    f'（按交易日计数，假期顺延{t_str}） · 概率夹 5%~95% · 非投资建议')
        if res.get("engine") == "llm":
            head_sub += f' · 文案数字溯源 {esc(str(res.get("grounded") or "—"))} 条'
        elif res.get("engine") == "jev":
            head_sub += (f' · Jev 类型化决策（{esc(str((res.get("jev") or {}).get("model") or "本地端点"))}）'
                         f' · 只出值与概率、不产文本 · 概率与基准同常量对账')
        else:
            head_sub += (f' · 大模型不可用（{esc(str(res.get("llm_reason") or "未配置 Key"))}）'
                         f'→ 量化基准')
    engine_label = esc(str(res.get("engine_label") or ""))
    head_row = kit.item_row(
        "◈", "<b>引擎</b>",
        f"{engine_label} · {head_sub}" if engine_label else head_sub,
    )
    for t in targets:
        icon = {"up": "▲", "down": "▼"}.get(t.get("direction"), "■")
        bits = []
        if t.get("close") is not None:
            bits.append(f'现价 {t["close"]:,.2f}')
        if t.get("ret5") is not None:
            bits.append(f'5日 {t["ret5"] * 100:+.1f}%')
        if t.get("ret20") is not None:
            bits.append(f'20日 {t["ret20"] * 100:+.1f}%')
        if t.get("rsi14") is not None:
            bits.append(f'RSI14 {t["rsi14"]:.1f}')
        if t.get("vol20") is not None:
            bits.append(f'年化波动 {t["vol20"] * 100:.1f}%')
        if t.get("vol_pct") is not None:
            bits.append(f'波动分位 {t["vol_pct"] * 100:.0f}%')
        if t.get("lo95") and t.get("hi95"):
            bits.append(f'95%区间 {t["lo95"]:,.0f}–{t["hi95"]:,.0f}'
                        + ("" if plain else
                           f'（历史 {horizon} 日 5%/95% 分位 n={int(t.get("var_n") or 0)}）'))
        fb_summary = t.get("factor_summary")
        driver_items = list(t.get("drivers") or [])[:2]
        risk_items = list(t.get("risks") or [])[:2]
        if plain:
            # 入门版：量化兜底文案里的方法论句（「扩张基准率 + 最近邻…」「统计口径不含…」）
            # 不出，只留数据驱动的那几句；大模型文案（engine=llm）原样保留。
            driver_items = [x for x in driver_items
                            if "最近邻" not in str(x) and "无未来函数" not in str(x)]
            risk_items = [x for x in risk_items if "统计口径不含" not in str(x)]
        drivers = "；".join(esc(str(x)) for x in driver_items)
        risks = "；".join(esc(str(x)) for x in risk_items)

        sub_layers = []
        if bits:
            sub_layers.append(" · ".join(bits))
        if fb_summary:
            sub_layers.append(f'因子：{esc(fb_summary)}')
        if drivers:
            sub_layers.append(f'依据：{drivers}')
        if risks:
            sub_layers.append(f'风险：{risks}')
        if res.get("engine") in ("llm", "jev") and not plain:
            q_info = f'量化基准 P {float(t.get("quant_p_up") or 0.5) * 100:.0f}%' + (
                '（已按基准收敛）' if t.get("converged")
                else f'（偏离 {float(t.get("deviation") or 0) * 100:+.0f}pp）')
            sub_layers.append(q_info)

        hair_color = GZ_HAIR_SOFT if _is_guizang_like(kit) else C_HAIR
        divider = f'<div style="border-top:1px solid {hair_color};margin:4px 0;"></div>'
        sub = divider.join(sub_layers)
        rows.append(kit.item_row(icon, f'{esc(str(t.get("name") or ""))} · '
                                       f'{esc(str(t.get("label") or ""))}', sub))

    rows.append(head_row)          # 三只指数的概率先读，再交代引擎与口径

    cross = str(res.get("cross_note") or "")
    if cross:
        rows.append(kit.item_row("◇", "<b>跨市场</b>", esc(cross)))

    jr = res.get("journal") or {}
    if plain:
        # 入门版：有已结算样本才报命中率；「已存档待结算 / 在途 N 条 / 七日口径」不出。
        if jr.get("hit_rate") is not None:
            rows.append(kit.item_row(
                "✓", "<b>预测复盘</b>",
                f'已结算 {int(jr.get("n") or 0)} 个样本 · 方向命中 {int(jr.get("hits") or 0)}'
                f'（{jr["hit_rate"] * 100:.0f}%）'))
        return kit.rows("".join(rows))
    if jr.get("hit_rate") is not None:
        j_txt = (f'已结算 {int(jr.get("n") or 0)} 个样本 · 方向命中 {int(jr.get("hits") or 0)}'
                 f'（{jr["hit_rate"] * 100:.0f}%）'
                 + (f' · Brier {jr["brier"]:.3f}' if jr.get("brier") is not None else ""))
    elif jr.get("n"):
        j_txt = f'已结算 {int(jr["n"])} 个样本（<10，只报样本量）'
    else:
        j_txt = "预测已存档（settled=False），待满 7 个交易日按真实收盘结算"
    if jr.get("standing"):
        j_txt += f' · 在途 {int(jr["standing"])} 条'
    recent_txt = " · ".join(
        f'{esc(str(r.get("date") or ""))} '
        f'{"+" if float(r.get("ret") or 0) >= 0 else ""}{float(r.get("ret") or 0) * 100:.1f}% '
        f'{"✓" if r.get("hit") else "✗"}'
        for r in (jr.get("recent") or []))
    rows.append(kit.item_row(
        "✓", "<b>预测留痕</b>",
        f"{j_txt}<br>{recent_txt}" if recent_txt else j_txt,
    ))

    self_check = next((str(t.get("self_check") or "") for t in targets
                       if t.get("self_check")), "")
    if res.get("engine") == "jev":
        guard_txt = (f' · Jev 概率偏离基准 >{int(_hk7.MAX_PROB_DEVIATION * 100)}pp 即收敛'
                     f'（同一份常量） · 模型只出值 + 概率、不产文本，没有编造数字的入口'
                     f' · 研究留痕 jev_forecast.json（同一套 T+7 结算口径）')
    else:
        guard_txt = (f' · 大模型概率偏离基准 >{int(_hk7.MAX_PROB_DEVIATION * 100)}pp 即收敛、'
                     f'文案数字须可溯源，否则回退量化口径')
    note_sub = (f'目标日 = 锚定日后第 {horizon} 个交易日（按交易日计数，'
                f'数据里没有那根 K 线就不结算） · 量化基准只用 ≤t 数据、相似样本标签须已结算'
                + (f' · 截断不变性自检通过（{esc(self_check)}）' if self_check else '')
                + f' · 预测因子体系（动量延展/均值回归 + 均线趋势 + RSI14超买超卖 + 美股隔夜联动β + 南向资金流 + 波动率收缩）'
                + guard_txt + ' · 非投资建议')
    rows.append(kit.item_row("⚖", "<b>七日口径</b>", note_sub))
    return kit.rows("".join(rows))


def _short_card_base_date(date_str):
    """报告日 YYYYMMDD → date 对象（速查卡「今明必看」的日基准）；非法值返回 None。"""
    text = str(date_str or "")
    if len(text) != 8:
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _beginner_tips_block(tips, kit):
    """🐣【新手三句话】独立排版块（2026-10-16 起渲染在卷首卦象之后）。

    文案与配对逻辑仍在 `octopus_short`（百句股票梗库 · 按当次盘面三槽位配对），
    这里只负责排版：主题 kit 的小标 + 键值表 + 一句免责（入门版不出脚注，与全篇同规）。
    卦象缺席时本块返回空串，三句话仍由速查卡末尾渲染——两边不会同时出，绝不重复。
    """
    if not tips:
        return ""
    plain = PLAIN()
    return (kit.sub(_esc(_short.TIPS_TITLE_PLAIN if plain else _short.TIPS_TITLE))
            + kit.kv([(_esc(label), _esc(text)) for label, text in tips])
            + kit.note(_esc(_short.DISCLAIMER)))


def _short_card_section(card_ctx, kit, today_n, total, tips=None, tips_in_card=True):
    """🎯【闪电飞鱼】短线速查卡（2026-09-30 新增；正文结论之后的行动要点收尾）。

    用户要求「内容再精炼，适合短线操作，入门观看」：把全天数据里**最能直接动手**的
    几件事压成 ≤600 字一张卡——今天什么风、明天怎么做（概率 / 区间 / 仓位 / 止损 / 止盈）、
    今明哪些时点别碰、板块强弱各 3、资金水位、舆情风声、当天数据底。

    【新手三句话】（读取 `output/stock_memes.json` 百句股票梗句库，按看方向 / 放止损 /
    别动手随时配对使用）2026-10-16 起默认**不再排在卡尾**：用户要求「放在卦象后」，
    三句话改由卷首「诗与远方的海」卦象之后渲染（见 `_beginner_tips_block`）；
    `tips_in_card=True`（卦象关闭 / 起卦失败时的回落路径）才继续排在卡尾。
    `tips` 由调用方按同一份 card_ctx 预先配对后传入，保证两处是同一组三句话。

    与整仓「防自欺」同规（细则见 output/octopus_short.py 与 tests/test_short_card.py）：
    纯规则合成、可复现；每个数字都取自下文各栏渲染用的同一批实参（不另算一套）；
    哪一路没数据那一行就缺席，全部缺数据整卡缺席；超字数预算按优先级**整行**撤下并留痕，
    绝不截断半句话。OCTOPUS_LITE=0 / --full 关闭。
    """
    card = _short.build_card(card_ctx, tips=tips, tips_in_card=tips_in_card)
    if not card:
        return None
    lead_color = GZ_INK_STRONG if _is_guizang_like(kit) else C_INK
    lead_size = GZ_FS_PRICE if _is_guizang_like(kit) else 15
    lead_val = (f'<span style="font-size:{lead_size}px;font-weight:700;color:{lead_color};'
                f'line-height:1.5;overflow-wrap:anywhere;">{_esc(card["lead"])}</span>')
    plain = PLAIN()
    pairs = card["pairs"]
    if plain:
        # 入门版：「数据底」只留当天源数字，去掉「数字与下文各栏同源」这类口径说明。
        pairs = [(label, (value.split(" · 数字与下文各栏同源")[0]
                          if isinstance(value, str) and "数据底" in str(label) else value))
                 for label, value in pairs]
    # 速查卡本身就是规则合成的行动摘要；第一行显式标成栏首 AI 结论，随后才列证据项。
    html = kit.kv([("本栏 AI 结论", lead_val),
                   *[(_esc(label), value) for label, value in pairs]])
    # marker 作为首张表的 data 属性，不额外制造一个会在邮件主题里变成空白行的 HTML 块。
    html = html.replace("<table ", f"<table {SECTION_AI_CONCLUSION_MARKER} ", 1)
    if tips_in_card:            # 卦象缺席时的回落：三句话仍排在卡尾，与卷首二选一
        html += _beginner_tips_block(card["tips"], kit)
    dropped = [d for d in (card.get("dropped") or [])]
    if dropped:                  # 被字数预算撤下的行如实点名，并指回正文对应栏目（入门版不出脚注）
        html += kit.note(_esc(f'字数预算内已收起：{"、".join(dropped)}（完整内容见下文对应栏目）'))
    html += kit.note(_esc(_short.DISCLAIMER))
    return ("SHORT CARD", SECTION_TITLE_SHORT_CARD, html, "",
            _short.CAPTION_PLAIN if plain else _short.CAPTION)



def _sector_rotation_rows(item, kit, rank_label=None, plain=None, basket_seen=None):
    """一条映射概念的窄屏渲染行：名称、可用总分、港股观察股、五维和三票。

    plain（入门版，缺省跟随 PLAIN()）：五维只给分数（不带 有效/总数 与可用权重），
    三策略只给各票方向与结论（不带 有效 n/3），映射命中词不出，事件证据只留标题。

    basket_seen（2026-10-12 同子栏合并）：同栏里多个概念常共用同一只港股观察篮子
    （例如 AI应用 / AIGC概念 / 互联网服务 都映射到同一批港股），名单会被逐行重复贴。
    传一个 dict 进来后，第二次起只写「与 XX 同一篮子」并给只数，名单不重复列——
    只数来自同一份映射数据，绝不改数字。
    """
    esc = kit.esc
    plain = PLAIN() if plain is None else bool(plain)
    score = item.get("overall_score")
    score_text = (f'{score:.1f}/100 · {_esc(str(item.get("score_label") or ""))}'
                  if score is not None else f'总分暂缺 · {_esc(str(item.get("score_reason") or ""))}')
    number = f"{rank_label:02d}" if isinstance(rank_label, int) else "◇"
    main = f'<b>{esc(str(item.get("name") or "未命名概念"))}</b> · {score_text}'

    mapped = []
    for stock in item.get("mapped_stocks") or []:
        label = str(stock.get("name") or "")
        code = str(stock.get("code") or "")
        if label:
            mapped.append(f"{label} {code}".strip())
    mapping_text = "、".join(mapped[:6]) or "映射港股无行情记录"
    if len(mapped) > 6:
        mapping_text += f" 等 {len(mapped)} 只"
    basket_note = ""
    if basket_seen is not None and len(mapped) >= 2:
        key = tuple(mapped)
        first = basket_seen.get(key)
        if first:
            # 同一篮子已在前面的概念行展开过 → 只留指针，不重复名单。
            basket_note = f"{SUB_MERGE_SAME_BASKET}：见 {first}（{len(mapped)} 只，同一批映射，不重复列名单）"
        else:
            basket_seen[key] = f"{number} {item.get('name') or '未命名概念'}"

    dim_labels = (("技术面", "技"), ("资金面", "资"), ("基本面", "基"),
                  ("行业板块", "板"), ("事件驱动", "事"))
    dim_bits = []
    for key, short in dim_labels:
        dim = (item.get("dimensions") or {}).get(key) or {}
        value = dim.get("score")
        if value is None:
            dim_bits.append(f"{short}—")
        elif plain:
            dim_bits.append(f"{short}{value:.0f}")
        else:
            dim_bits.append(f"{short}{value:.0f}({dim.get('valid', 0)}/{dim.get('total', 0)})")
    available_weight = float(item.get("available_weight") or 0) * 100
    dim_text = "五维 " + " / ".join(dim_bits) + (
        "" if plain else f" · 可用权重 {available_weight:.0f}%")

    vote_summary = item.get("strategy_summary") or {}
    vote_names = {"ma_trend": "MA", "multi_momentum": "动量", "relative_rotation": "相对轮动"}
    vote_bits = []
    for vote in item.get("strategy_votes") or []:
        vote_bits.append(f'{vote_names.get(vote.get("key"), vote.get("name", "策略"))}'
                         f' {vote.get("direction") or "数据不足"}')
    valid_n = int(vote_summary.get("available_n") or 0)
    consensus = str(vote_summary.get("consensus") or "数据不足")
    votes_text = ("三策 " + " / ".join(vote_bits)
                  + f" → {consensus}" + ("" if plain else f"（有效 {valid_n}/3）"))
    pieces = [f"港股观察篮子：{_esc(basket_note or mapping_text)}", _esc(dim_text), _esc(votes_text)]
    matched = "、".join(str(x) for x in (item.get("matched_terms") or [])[:5])
    if matched and not plain:
        pieces.append("映射命中词：" + _esc(matched))
    evidence = item.get("event_evidence") or []
    if evidence:
        ev = evidence[0]
        if plain:
            pieces.append(f'事件（{_esc(str(ev.get("sentiment") or "中性"))}）：'
                          f'{_esc(str(ev.get("title") or "")[:90])}')
        else:
            pieces.append(f'事件证据（{_esc(str(ev.get("source") or "公开标题"))} · '
                          f'{_esc(str(ev.get("sentiment") or "中性"))}）：'
                          f'{_esc(str(ev.get("title") or "")[:90])}')
    return kit.item_row(number, main, "<br>".join(pieces))


def _render_sector_rotation(source, kit):
    """两套主题共用：板块轮动评分、三策略投票、映射范围与缺项解释。"""
    result = (source or {}).get("result") or {}
    if not isinstance(result, dict):
        return ""
    concepts = int(result.get("concept_total") or 0)
    mapped_total = int(result.get("mapped_total") or 0)
    unmapped_total = int(result.get("unmapped_total") or 0)
    scored_total = int(result.get("scored_total") or 0)
    coverage = result.get("coverage") or {}
    dates = result.get("data_dates") or {}
    plain = PLAIN()
    rows = []
    date_bits = [f"A股概念 {dates.get('a_share_concepts') or '未返回日期'}",
                 f"港股日线 {dates.get('hk_stocks_latest') or '暂缺'}",
                 f"港股资金/估值快照 {dates.get('hk_quotes_latest') or '暂缺'}",
                 f"恒指基准 {dates.get('hsi_benchmark') or '暂缺'}"]
    if plain:
        # 入门版：覆盖面压成一行数字 + 行情日期；分页 / 接口核验、逐维覆盖、权重表不出。
        rows.append(("概念覆盖", f"A股概念 {concepts:,} 项 · 关联港股 {mapped_total} 项"
                                 f" · 可评分 {scored_total} 个"))
        rows.append(("行情日期", " · ".join(_esc(str(x)) for x in date_bits)))
    else:
        rows.append(("A股概念库", f'{concepts:,} 项'
                     + (" · 分页完整" if result.get("catalog_complete") else " · 分页/接口完整性未确认")))
        rows.append(("关键词映射", f"命中 {mapped_total} 项 · 未映射 {unmapped_total} 项不进入港股评分"))
        rows.append(("港股数据覆盖",
                     f"日线 {int(coverage.get('technical_symbols') or 0)}/{int(coverage.get('mapped_hk_symbols') or 0)}"
                     f" · 资金 {int(coverage.get('flow_symbols') or 0)}/{int(coverage.get('mapped_hk_symbols') or 0)}"
                     f" · PE/PB {int(coverage.get('fundamental_symbols') or 0)}/{int(coverage.get('mapped_hk_symbols') or 0)}"
                     f" · 可评分概念 {scored_total}"))
        rows.append(("行情日期", " · ".join(_esc(str(x)) for x in date_bits)))
        rows.append(("五维权重", "技术面 35% · 资金面 35% · 基本面 10% · 行业板块 10% · 事件驱动 10%"))
    out = [kit.kv(rows)]

    items = [row for row in result.get("items") or [] if isinstance(row, dict)]
    scored = [row for row in items if row.get("overall_score") is not None]
    # 同子栏合并（栏内）：同一只港股观察篮子只列一次名单（OCTOPUS_SUB_MERGE=0 时整栏照旧）
    basket_seen = {} if SUB_MERGE_ENABLED else None
    if scored:
        if len(scored) <= 8:
            leaders = scored
            laggards = []
        else:
            leaders = scored[:5]
            laggards = scored[-3:]
        hidden_n = max(0, len(scored) - len(leaders) - len(laggards))
        out.append(kit.sub("综合分靠前" + (f"（另 {hidden_n} 个未列）" if hidden_n and plain else "")))
        for index, item in enumerate(leaders, 1):
            out.append(_sector_rotation_rows(item, kit, rank_label=item.get("rank") or index,
                                             basket_seen=basket_seen))
        if laggards:
            out.append(kit.sub("综合分靠后（供风险对照）"))
            for item in laggards:
                out.append(_sector_rotation_rows(item, kit, rank_label=item.get("rank"),
                                                 basket_seen=basket_seen))
        out.append(kit.note(_esc(
            f"共有 {scored_total} 个概念满足总分门槛；版面展示前 5 与后 3（若候选不超过 8 个则全部列出）。")))
    else:
        out.append(kit.item_row("!", "没有概念满足综合评分门槛",
                                "" if plain else "保留板块行情与单项可用分；不会用缺失维度补 0 或 50 分。"))

    unscored = [row for row in items if row.get("overall_score") is None]
    if unscored and not plain:        # 入门版：数据不足的概念属于诊断信息，不进正文
        out.append(kit.sub("数据不足的映射概念（示例）"))
        for item in unscored[:3]:
            out.append(_sector_rotation_rows(item, kit, basket_seen=basket_seen))
        if len(unscored) > 3:
            out.append(kit.note(_esc(f"另有 {len(unscored) - 3} 个映射概念未达到综合评分门槛。")))
    if not items:
        out.append(kit.item_row("!", "当前概念库没有命中本地港股关键词观察篮子",
                                "" if plain else "不把名称相似或业务猜测当作官方跨市场关系。"))

    if plain:
        # 入门版：计算过程 / 映射限制 / GitHub 参考整段不出，只留一句防误读提示。
        out.append(kit.item_row("i", "<b>提示</b>",
                                "概念与港股的对应关系由仓库关键词表人工维护，不是官方成分；"
                                "评分仅供参考，非投资建议。"))
        return kit.rows("".join(out))

    refs = _sector_rotation.strategy_reference_links()
    ref_html = " · ".join(
        f'<a href="{_esc(url)}" style="color:inherit;text-decoration:underline;">{_esc(label)}</a>'
        for label, url in refs)
    methodology = (
        "总分：每维 0–100；技术为映射股 20/60 日收益与 MA20/60 趋势等权组合，资金将 A 股概念板块 f62/f6 与港股映射股主力净占比分组等权（港股组至少 2 只），"
        "基本面仅按全部映射港股观察篮子中的正 PE-TTM/PB 横截面分位做代理、非同行业比较且不代表盈利质量，行业板块用 A 股概念涨跌幅与涨跌宽度，"
        "事件只扫描近 72 小时已抓标题的固定词表。缺失维度不填 0/50；至少 3 维且原始权重覆盖 ≥70% 才按可用权重重新归一化。"
        "三策略独立投票：①MA20/60 多空排列达到映射股 60%；②20/60/120 日等权动量至少两周期同向；"
        "③相对恒指的 20/60 日超额收益（简化 RRG 象限代理，非标准 JdK RRG）。至少 2 套策略有效且至少 2 票同向，才给偏多/偏空；权重总分与策略票不混算。"
    )
    mapping_note = (
        "映射限制：A 股概念名称按仓库内白名单关键词连接至人工维护的港股公司观察篮子，"
        "并非东方财富/交易所官方成分或公司关联；单股/少数公司不能代表完整概念产业链。当前概念池为当下快照，无点时成分历史，"
        "因此不宣称历史回测收益或样本外有效性。东方财富接口参数、字段语义与分页尚未在线实测核验，页面值只代表当前解析结果。"
    )
    source_text = "数据：" + "；".join(result.get("source_names") or ["东方财富概念列表、港股日线与个股快照"])
    methodology_html = _esc(methodology) + "<br>" + _esc(mapping_note) + "<br>" + _esc(source_text)
    reference_html = ("GitHub 方法参考（仅借鉴规则思想；未复制第三方源码）：" + ref_html
                      + _esc("。MA 模板仓库提供 MIT LICENSE；另外两个仓库在检查时未找到 LICENSE 文件，仅作概念参考。"))
    if kit is PIXEL_KIT:
        # Pixel 的通用脚注为节省版面而隐藏；此栏的计算口径、A/H 映射限制与来源是
        # 防止误读所必需的信息，改用正文行输出，两个主题都必须保留。
        out.append(kit.item_row("i", "<b>计算过程与映射限制</b>", methodology_html))
        out.append(kit.item_row("↗", "<b>GitHub 方法参考</b>", reference_html))
    else:
        out.append(kit.note(methodology_html))
        out.append(kit.note(reference_html))
    return kit.rows("".join(out))


def _pct_text(value, digits=2, dash="—"):
    """带正负号的百分比文本（None → 占位符），不依赖颜色。"""
    try:
        return f"{float(value) * 100:+.{digits}f}%" if value is not None else dash
    except (TypeError, ValueError):
        return dash


def _industry_rotation_block(res, kit):
    """展示全行业评分与五行业纯多头月度持仓，两主题共用。

    栏目结构：口径行 → 行业宽度 → 全行业评分表（综合分排序，附动量 / MA20 背景因子）→
    月度持仓（含自执行日以来的组合表现与全行业等权基准）→ 规则行。
    全部数字来自本次抓取的日线与存档持仓，缺失项显示「—」，绝不补造。
    """
    if not res.get("available"):
        return ""
    state = res.get("state") or {}
    holdings = state.get("holdings") or []
    if len(holdings) != 5:
        return ""
    esc = kit.esc
    universe_label = str(res.get("universe_label") or "").strip()
    sources = res.get("sources") or {}
    source_bits = []
    em_total = int(sources.get("eastmoney") or 0) + int(sources.get("eastmoney_mirror") or 0)
    if em_total:
        source_bits.append(f'东方财富 {em_total}'
                           + (f'（镜像 {int(sources["eastmoney_mirror"])}）'
                              if sources.get("eastmoney_mirror") else ""))
    if sources.get("sw_official"):
        source_bits.append(f'申万官方 {int(sources["sw_official"])}')
    missing = res.get("missing") or []
    head_sub = "近一周=最近5个交易日；历史12个不重叠5日窗口（不含当前周）"
    if source_bits:
        head_sub += f' · 日线来源：{" / ".join(source_bits)}'
    if missing:
        head_sub += f' · 未取到日线：{esc("、".join(str(m) for m in missing[:8]))}'
        if len(missing) > 8:
            head_sub += f' 等 {len(missing)} 个'
    out = [kit.item_row("▤", f'截至 {esc(res["asof"])} 收盘 · '
                        + (f'{esc(universe_label)} · ' if universe_label else "")
                        + f'有效 {res["scored_count"]}/{res["universe_count"]} 个行业指数',
                        head_sub)]

    breadth = res.get("breadth") or {}
    if breadth.get("total"):
        total = int(breadth["total"])
        bits = [f'近5日上涨 {int(breadth.get("up_week") or 0)}/{total} 个行业']
        if breadth.get("above_ma20") is not None:
            bits.append(f'站上 MA20 {int(breadth["above_ma20"])}/{total} 个')
        if breadth.get("avg_week") is not None:
            bits.append(f'全行业等权近5日 {_pct_text(breadth["avg_week"])}')
        out.append(kit.item_row("◐", "行业宽度 · " + " · ".join(bits),
                                "上涨行业占比与均线上方占比越高，轮动越偏普涨；反之为少数行业抱团"))

    table_rows = []
    for rank, sec in enumerate(res["scores"], 1):
        # 名次并入行业列（8 列，与流动性表同宽度量级，手机上不挤）
        table_rows.append([
            f'{rank:02d} {esc(sec["name"])}<br><span style="font-size:11px;">{esc(sec["code"])}</span>',
            f'<b>{sec["score"]:.2f}</b>',
            _pct_text(sec.get("week_return")),
            f'{sec["win_rate"] * 100:.1f}%',
            f'{sec["odds"]:.2f}',
            _pct_text(sec.get("ret20"), 1),
            _pct_text(sec.get("ret60"), 1),
            _pct_text(sec.get("ma20_gap"), 1),
        ])
    out.append(kit.sub("全行业评分（综合分降序 · 名次在前）"))
    out.append(kit.table(["行业", "综合分", "近5日", "胜率", "赔率", "20日", "60日", "vs MA20"],
                         table_rows,
                         aligns=("left", "right", "right", "right", "right",
                                 "right", "right", "right")))

    tracking = res.get("tracking") or {}
    tracked = {r["code"]: r for r in (tracking.get("holdings") or [])}
    reb_sub = f'建仓/调仓锚点 {esc(state["rebalance_date"])} 收盘；当月不随每日评分换仓'
    if tracking.get("exec_date"):
        reb_sub += f' · 执行日 {esc(tracking["exec_date"])} 收盘起算表现'
    else:
        reb_sub += " · 待下一交易日执行"
    hold_rows = [kit.item_row("↺", f'纯多头组合 · {esc(state["month"])} 月度持仓', reb_sub)]
    for h in holdings:
        sub = f'目标权重 {h["weight"]:.2%} · 建仓时得分 {h["score"]:.2f}'
        tr = tracked.get(h["code"]) or {}
        if tr.get("since_exec") is not None:
            sub += f' · 执行日以来 {_pct_text(tr["since_exec"])}'
        hold_rows.append(kit.item_row("+", f'{esc(h["name"])} ({esc(h["code"])})', sub))
    if tracking.get("portfolio") is not None:
        perf = f'组合执行日以来 {_pct_text(tracking["portfolio"])}'
        if tracking.get("benchmark") is not None:
            excess = (tracking["portfolio"] - tracking["benchmark"]) * 100
            excess = 0.0 if abs(excess) < 0.005 else excess      # 避免 -0.00pp
            perf += (f' · 全行业等权 {_pct_text(tracking["benchmark"])}'
                     f'（{int(tracking.get("benchmark_n") or 0)} 个行业）· 超额 {excess:+.2f}pp')
        hold_rows.append(kit.item_row("Σ", perf,
                                      "权重固定为目标权重、不含调仓费用与滑点的持有期收益；"
                                      "样本仅一个月度周期，不代表策略长期表现"))
    elif tracking.get("pending"):
        hold_rows.append(kit.item_row("Σ", "组合表现待执行日收盘后起算",
                                      "信号在锚点收盘后产生，按下一交易日收盘执行，不把信号日涨跌计入组合"))
    hold_rows.append(kit.item_row("⚖", '规则：综合分=胜率×80% + [赔率/(1+赔率)]×20%（乘100）；'
                                  '胜率=正收益周占比，赔率=平均正收益/平均负收益绝对值。'
                                  '得分前五，权重=各自得分/前五总分。20日/60日/vs MA20 只作背景，不参与排序。',
                                  '每月首次成功采集后按收盘信号确定目标权重，下一交易日执行；'
                                  '不含滑点/费用，非投资建议；历史胜率不是未来成功概率。'))
    out.append(kit.rows("".join(hold_rows)))
    return "".join(out)


def _uzi_result(data):
    """【游资剑鱼】多专家流派趋势分析的结果字典（正文渲染与「🦑 AI帮你提鲜」共用同一份）。

    与 _trend_section_stats 同一口径：解读层引用的数字必须来自渲染正文用的同一批实参，
    不允许两处各算一套。数据源缺席 / status 非 success / result 不是字典 → 返回 {}，
    解读层读到空对象自然缺席（不硬编、不用旧数据充数）。
    """
    src = (data or {}).get(UZI_TREND_SOURCE_NAME)
    if not isinstance(src, dict) or src.get("status") != "success":
        return {}
    res = src.get("result")
    return res if isinstance(res, dict) else {}


def _render_uzi_trend(source, kit):
    """两套主题共用：【游资剑鱼】多专家流派趋势分析。

    内容来自 octopus_quant.uzi_trend.run_trend() 的结果字典：面板概览 → 逐标的
    （阶段 / 均线 / RSI·KDJ·WR / 区间收益·位置·波动 / 评委面板 / 趋势定调）→
    逐评委命中与未达 → 规则覆盖与被门禁撤下的评委 → 方法来源与口径。
    数据不足时 run_trend() 直接判定整栏缺席，这里只负责排版，绝不补造数字。
    """
    result = (source or {}).get("result") or {}
    if not isinstance(result, dict) or not result.get("available"):
        return ""
    return _uzi_trend.render_trend(result, kit,
                                   limit=6 if LITE_ENABLED else 0, plain=PLAIN())


def _render_industry_rotation(source, kit):
    """两套主题共用：【巡游旗鱼】申万一级行业轮动。

    内容来自 octopus_quant.industry_rotation.run() 的结果字典（res["result"]）：
    口径行 → 行业宽度 → 全行业评分表 → 月度持仓与执行日以来表现 → 规则行。
    数据不足时 run() 直接判定整栏缺席，这里只负责排版，绝不补造数字。
    """
    result = (source or {}).get("result") or {}
    if not isinstance(result, dict):
        return ""
    return _industry_rotation_block(result, kit)


def _bagua_report_day(date_str):
    """☯ 八卦起卦日：报告日字符串 → date。

    流水线实际传入的是 ``_today_str()`` 的 ``YYYYMMDD``（如 20261014），测试与手工
    调用常用 ISO ``YYYY-MM-DD``；两种都接受。2026-10-14 线上首发时只解析 ISO 口径，
    ``20261014`` 抛 ValueError 被吞掉 → 子栏整体缺席，故此处统一解析并在都不合法时
    回退到北京时间当天（起卦只依赖日期，回退不会算错卦）。
    """
    text = str(date_str or "").strip()[:10]
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return datetime.now(CST).date()


def _collect_report_parts(data, kit, sentiment_history=None, date_str=None,
                            policy_result=None, news_corpus=None):
    """提取逐栏目内容与当天检验统计（两主题共用；仅渲染套件不同）。

    sentiment_history: 跨日情绪基线（新闻情绪动量/新闻量窗口用）；
    date_str: 报告日期 YYYYMMDD（划分今日与历史的界线），缺省取当天；
    policy_result: main 1.6 阶段单独构建的政策因子结果，缺省时兜底构建；
    news_corpus: 跨运行标题存档（output/news_history.json），缺省时因子只用
    本次抓取标题（测试 / 冷启动路径）。
    """
    # 三地指数全页拼版：2026-10-23 已回滚，默认**不启用**（见 _index_page_enabled）。
    # 只有显式 OCTOPUS_INDEX_PAGE=1 且快照带 index_checks 契约时才分流到指数全页；
    # 默认路径回到原港股日报（恒指七日 / 港股量化 / 个股栏目与旧AI装饰器全部照旧）。
    index_result = (data.get(STRATEGY_QUANT_SOURCE) or {}).get("result") or {}
    if (_index_page_enabled() and "index_checks" in index_result):
        import index_page
        parts = index_page.build_parts(index_result["index_checks"], kit, REPORT_SECTION_ORDER,
                                       calendar=data.get("财经日历"), date_str=date_str)
        parts["poem"] = _shiquan.get_opening_poem(data, allow_network=False) if (SHIQUAN_ENABLED and _shiquan.is_enabled()) else None
        if _bagua.ENABLED:
            try:
                parts["bagua_html"] = _bagua.render_bagua_html(day=_bagua_report_day(date_str))
            except Exception:
                pass
        return parts
    # 审计口径（当天源 / 总源）基于原始抓取结果；正文渲染用裁剪掉过期内容的副本。
    raw_yt = data.get("港股名家频道", {})
    raw_google = data.get("全球头条", {})
    data = _prune_report_data(data, date_str)
    market = data.get("实时行情", {})
    pan = data.get("A股大盘全景", {}) or {}
    # 官方源作为政策因子输入；兼容外部调用仍使用旧的「中国政府网」键名。
    gov_policy = data.get("国家政策")
    if not isinstance(gov_policy, dict):
        gov_policy = data.get("中国政府网", {}) or {}
    yt = data.get("港股名家频道", {})
    google = data.get("全球头条", {})
    gh_headlines = google.get("headlines", [])
    em = data.get("东财快讯", {})
    em_headlines = em.get("headlines", [])
    hot = data.get("热门榜单", {}) or {}

    source_items = [
        ("实时行情", market),
        ("A股大盘全景", pan),
        ("国家政策（中国政府网）", gov_policy),
        ("港股名家频道", raw_yt),
        ("全球头条", raw_google),
        ("东财快讯", em),
        ("热门榜单", hot),
        ("港股量化引擎（概率/流动性）", data.get("港股量化") or {}),
    ]
    # 板块轮动是独立的 A股概念库 + 港股观察篮子来源；仅外部调用确实传入时计入审计。
    if isinstance(data.get(SECTOR_ROTATION_SOURCE_NAME), dict):
        source_items.append((SECTOR_ROTATION_SOURCE_NAME, data[SECTOR_ROTATION_SOURCE_NAME]))
    # 申万一级行业轮动：独立数据线（固定股票池 + 板块指数日K + 申万官方兜底），同样按需进审计。
    if isinstance(data.get(INDUSTRY_ROTATION_SOURCE_NAME), dict):
        source_items.append((INDUSTRY_ROTATION_SOURCE_NAME, data[INDUSTRY_ROTATION_SOURCE_NAME]))
    if isinstance(data.get(MACD_SOURCE_NAME), dict):
        source_items.append((MACD_SOURCE_NAME, data[MACD_SOURCE_NAME]))
    # 多专家流派趋势分析：独立栏目 + 独立来源行（关闭时不写 data 键，审计口径不变）。
    if isinstance(data.get(UZI_TREND_SOURCE_NAME), dict):
        source_items.append((UZI_TREND_SOURCE_NAME, data[UZI_TREND_SOURCE_NAME]))
    # 策略大类量化（图中 4 大类 6 细分）：内部衍生自基准指数日线；取不到时在「数据覆盖」点名。
    if isinstance(data.get(STRATEGY_QUANT_SOURCE), dict):
        source_items.append((STRATEGY_QUANT_SOURCE, data[STRATEGY_QUANT_SOURCE]))
    # 前瞻日程（「时间节点」栏目）：关掉采集时不进审计，总源数保持不变。
    # 它是「今日抓取的日程快照」而非当天发布的内容，因此不计入当天源（当天检验不受影响）。
    if isinstance(data.get("财经日历"), dict):
        source_items.append((f"财经日历（未来{ECON_CALENDAR_DAYS}天时间点）", data["财经日历"]))
    # AI趋势分析两个专题源：只在实际采集过（键存在）时进审计，缺失时在数据覆盖点名。
    for _tk in (FED_TREND_KEY, GEO_TREND_KEY):
        if isinstance(data.get(_tk), dict):
            source_items.append((_tk, data[_tk]))
    # 每周量化走势预测 / AI 七日港股走势分析概率：独立栏目，存在即按需进审计。
    if isinstance(data.get("每周走势预测"), dict):
        source_items.append(("每周量化走势预测（恒指·7交易日）", data["每周走势预测"]))
    if isinstance(data.get(HK7_SOURCE_NAME), dict):
        source_items.append((HK7_SOURCE_NAME, data[HK7_SOURCE_NAME]))
    # 全网 36 个新闻源头（港股挖掘）：与社区平台同为趋势跟踪，按需加入审计；
    # 外部旧调用若无该键仍维持原来的基础数据源数量。
    if isinstance(data.get(HK_NEWS_SOURCE_NAME), dict):
        source_items.append(("全网新闻源头（36家）", data[HK_NEWS_SOURCE_NAME]))
    # 内地财经媒体源头（18 家，2026-10-12 新增）：独立数据线，同样按需进审计
    # （外部旧调用没有该键时基础数据源数量不变），当天源计数随其窗口内是否有当天发布而计入。
    # 口径说明：与 36 源池中的同域媒体是两条独立采集线——那条按港股关键词挖掘，
    # 这条不做过滤、供新闻情绪 / 政策因子标题池使用，审计各按自己的源名计数。
    if isinstance(data.get(MAINLAND_NEWS_SOURCE_NAME), dict):
        source_items.append((f"内地财经媒体（{MAINLAND_NEWS_TOTAL}家）",
                             data[MAINLAND_NEWS_SOURCE_NAME]))
    # 趋势跟踪：每个平台单独计入审计（缺失平台在「数据覆盖」里点名）；
    # 未运行过多平台采集的旧调用自然不进审计，维持基础数据源数量。
    source_items.extend((name, data[name]) for name in _active_public_site_names() if name in data)

    total = len(source_items)
    today_n = sum(1 for _, s in source_items if s.get("is_today"))
    content_n = sum(1 for _, s in source_items if s.get("status") == "success")

    # ---- 栏目拼版：今日预判 → ①②③④ 逻辑分组 → 总结收尾（有内容才渲染）----
    blocks = {}  # kicker -> (kicker_en, title, content, badge_html, caption)
    # 栏首结论与正文严格复用同一个结构化结果，避免两边各算一套。
    retail_sentiment_result = _senti_strategy.calculate(data)
    retail_sentiment_section = _senti_strategy.build_section(
        kit, data, result=retail_sentiment_result)
    if retail_sentiment_section:
        blocks[retail_sentiment_section[0]] = retail_sentiment_section

    policy = {}
    ai_result = {}
    if AI_ANALYSIS_ENABLED:
        policy = policy_result if policy_result is not None else \
            build_policy_factor(data, date_str, news_corpus)
        ai_result = build_ai_analysis(data)

    # ---- 量化栏目：预测总览 → 资金流动性；港股概率分析并入每日趋势推演 ----
    quant = {}
    quant_src = data.get("港股量化") or {}
    hk_probability_html = ""
    if isinstance(quant_src, dict):
        quant = quant_src.get("result") or {}
    lq_html = ""          # 资金流动性正文（同子栏合并要用它判断 05 栏是否真的在场）
    if quant.get("available"):
        # 2026-10-23 按用户要求下线「【蜉蝣天地水母】量化分析总览」整栏：
        # 只去掉这一栏的正文，概率模型本身不改——港股概率走势分析仍并入
        # 「每日趋势量化推演」，资金流动性分析仍单独成栏；数据审计口径不变。
        hk_probability_html = _quant.render.render_hk_probability(quant, kit) or ""
        lq_html = _quant.render.render_liquidity(quant, kit)
        if lq_html:
            blocks["LIQUIDITY FLOW"] = (
                "LIQUIDITY FLOW", "资金流动性分析", lq_html,
                kit.source_badge(quant_src), _short_source(quant_src))

    # ---- 【嗜血大白鲨】逐日走势量化分析（2026-09-29 起：未来 7 个交易日逐日表格）----
    #      2026-09-30 合并原「AI 七日港股走势分析概率」为栏内子块：两路数据任一可用即出栏目，
    #      数据源键名 / 审计标签 / 留痕文件各自保留（与「行情速览 + 全景复盘」合并同一先例）。
    weekly_res = {}
    weekly_src = data.get("每周走势预测") or {}
    if isinstance(weekly_src, dict):
        weekly_res = weekly_src.get("result") or {}
    hk7_src = data.get(HK7_SOURCE_NAME) or {}
    hk7_res = hk7_src.get("result") or {}

    wk_html = ""
    if weekly_res.get("available") and isinstance(weekly_res.get("entry"), dict):
        wk_html = _weekly_forecast_block(weekly_res, kit) or ""
    hk7_html = _hk_seven_day_block(hk7_res, kit) if hk7_res.get("available") else ""
    if wk_html or hk7_html or hk_probability_html:
        merged_html = wk_html
        if hk7_html:
            merged_html += kit.item_row(
                "◧", "<b>AI 七日港股走势分析概率</b> · 恒指 / 恒科 / 国企",
                "" if PLAIN() else
                "三指数未来 7 个交易日概率、依据、风险与三道防线"
                "（大模型研判，失败降级量化基准；各自留痕，规则合成参考，非投资建议）。") + hk7_html
        if hk_probability_html:
            merged_html += kit.sub("港股概率走势分析") + hk_probability_html
        wk_badge, wk_caption = _weekly_merged_meta(
            kit, weekly_src if wk_html else None, hk7_src if hk7_html else None,
            quant_src if hk_probability_html else None)
        blocks["WEEKLY FORECAST"] = (
            "WEEKLY FORECAST", SECTION_TITLE_WEEKLY_FORECAST, merged_html,
            wk_badge, wk_caption)

    # ⑦ 【滚滚翻车鱼】A股概念库 → 港股观察篮子：权重分与三策略投票分别呈现。
    rotation_src = data.get(SECTOR_ROTATION_SOURCE_NAME) or {}
    if rotation_src.get("status") == "success":
        rotation_html = _render_sector_rotation(rotation_src, kit)
        if rotation_html:
            blocks["SECTOR ROTATION"] = (
                "SECTOR ROTATION", SECTION_TITLE_SECTOR_ROTATION, rotation_html,
                kit.source_badge(rotation_src), _short_source(rotation_src))

    # ⑦b 【巡游旗鱼】申万一级行业轮动（2026-10-04 移植 #84 上线）：
    #     股票池 = 申万一级 31 个行业固定表（不再依赖被 502 的 clist 大页列表）；
    #     口径行 → 行业宽度 → 全行业评分表（含 20/60 日与 vs MA20 背景因子）→ 月度持仓与
    #     自执行日以来表现（对照全行业等权）→ 规则行。数据不足则整栏缺席，不补造行情。
    industry_src = data.get(INDUSTRY_ROTATION_SOURCE_NAME) or {}
    if industry_src.get("status") == "success":
        industry_html = _render_industry_rotation(industry_src, kit)
        if industry_html:
            blocks["INDUSTRY ROTATION"] = (
                "INDUSTRY ROTATION", SECTION_TITLE_INDUSTRY_ROTATION, industry_html,
                kit.source_badge(industry_src), _short_source(industry_src))

    # 📊 策略大类量化（图中 4 大类 6 细分，2026-10-21 新增）：总览 + 4 大类。
    #     内部衍生、可离线兜底；只读基准指数日线，不计入当天检验 / 总源审计。
    #     任一栏渲染异常只影响该栏（整段 try），绝不拖垮整份日报。
    try:
        sq_src = data.get(STRATEGY_QUANT_SOURCE) or {}
        sq_res = sq_src.get("result") if isinstance(sq_src, dict) else None
        if _strategy_quant is not None and isinstance(sq_res, dict) and sq_res.get("available"):
            sq_badge = kit.badge("策略量化", "ai")
            ov_html = _strategy_quant.render_overview(sq_res, kit)
            if ov_html:
                blocks["STRATEGY OVERVIEW"] = (
                    "STRATEGY OVERVIEW", SECTION_TITLE_STRATEGY_OVERVIEW, ov_html, sq_badge,
                    "" if PLAIN() else
                    "图中 4 大类 6 细分 · 基准指数日线 · 20/60日收益 · 波动 · 夏普 · 回撤 · 胜率 · 趋势 · 信号（规则合成，非投资建议）")
            for major, kicker, title, note in (
                    ("权益多头", "STRATEGY EQUITY", SECTION_TITLE_STRATEGY_EQUITY,
                     "权益多头：主观多头（沪深300） vs 量化多头（中证500） · 收益 / 波动 / 趋势 / 信号对比"),
                    ("纯债策略", "STRATEGY BOND", SECTION_TITLE_STRATEGY_BOND,
                     "纯债策略：国债ETF / 中证全债基准 · 低波动稳定器特征"),
                    ("CTA策略", "STRATEGY CTA", SECTION_TITLE_STRATEGY_CTA,
                     "CTA 策略：主观CTA（GSG） vs 量化CTA（DBC） · 商品趋势双视角"),
                    ("套利策略", "STRATEGY ARBITRAGE", SECTION_TITLE_STRATEGY_ARBITRAGE,
                     "套利策略 · 综合指数：私募综合 / 上证指数代理 · 市场中性合成表现")):
                major_html = _strategy_quant.render_major(major, sq_res, kit)
                if major_html:
                    blocks[kicker] = (kicker, title, major_html, sq_badge,
                                      "" if PLAIN() else note)
    except Exception as _sq_exc:  # 单栏失败不拖垮整份日报
        print(f"  ⚠️ 策略量化渲染异常：{_sq_exc}")

    # ⓪ 时间节点（原「未来 N 天影响经济时间点」，2026-09-29 改名）：
    #    开头栏目——先看清日程窗口，再读今天的盘；窗口天数仍在栏目内「窗口摘要 · 时间窗口」显示。
    cal = data.get("财经日历") or {}
    if cal.get("status") == "success":
        cal_html = kit.calendar_block(cal, date_str=date_str)
        if cal_html:
            blocks["ECON CALENDAR"] = (
                "ECON CALENDAR", SECTION_TITLE_ECON_CALENDAR, cal_html,
                kit.source_badge(cal), _short_source(cal),
            )

    # ① 【及时秋刀鱼】AI 行情复盘（2026-09-30 合并原「行情速览」+「全球大盘全景复盘」）
    #    逐项报价（Yahoo / 东财回补）+ A股全景（东财）；重复数字只出一份，缺失品种不出行。
    #    两路数据任意一路成功即渲染，徽标与副标题分别标出各自状态。
    #    2026-10-12 起「同子栏合并」：05 资金流动性栏目在场时，南北向成交总额只在
    #    05 展开（更专业口径：环比 / z 值 / 分位 / 综合分），本栏只留指针（见 SUB_MERGE_*）。
    market_ok = market.get("status") == "success"
    pan_ok = pan.get("status") == "success"
    merge_flow_owner = SUB_MERGE_OWNER_LIQUIDITY if (SUB_MERGE_ENABLED and lq_html) else ""
    review_html = (kit.market_review(market if market_ok else {}, pan if pan_ok else {},
                                     merge_flow=merge_flow_owner)
                   if (market_ok or pan_ok) else "")
    if review_html:
        review_badge, review_caption = _market_review_meta(
            kit, market if market_ok else None, pan if pan_ok else None)
        blocks["MARKET REVIEW"] = (
            "MARKET REVIEW", SECTION_TITLE_MARKET_REVIEW, review_html,
            review_badge, review_caption,
        )

    # ③ 政策因子（PSI 量化趋势预判）
    if policy.get("available"):
        blocks["POLICY SHOCK"] = (
            "POLICY SHOCK", SECTION_TITLE_POLICY, kit.policy_block(policy),
            kit.badge("量化策略", "ai"), "",
        )
        blocks["QUANT POLICY"] = blocks["POLICY SHOCK"]

    # ③b AI趋势分析（美联储 / 地缘政治）：专门抓取 + 词表定调 + 证据引用
    fed_res = geo_res = {}
    if AI_ANALYSIS_ENABLED:
        # 全球头条标题一律不作为两个专题的证据重复引用：2026-10-02 前是为了不与
        # 正文「全球头条」栏目重列，栏目隐藏后继续排除，可保证被隐藏的头条内容
        # 不会换个栏目重新出现在页面上（专题定调仍照原样计入这些标题）。
        shown_titles = [str((h or {}).get("title") or "")
                        for h in (gh_headlines or [])[:GH_DISPLAY_N] if isinstance(h, dict)]
        fed_res = build_fed_trend_analysis(data, exclude_titles=shown_titles)
        geo_shown = shown_titles + [str((e or {}).get("title") or "")
                                    for e in (fed_res.get("evidence") or [])]
        geo_res = build_geo_trend_analysis(data, exclude_titles=geo_shown)
        if fed_res.get("available"):
            blocks["FED TREND"] = (
                "FED TREND", SECTION_TITLE_FED_TREND, kit.trend_topic_block(fed_res),
                kit.ai_badge(), "")
        if geo_res.get("available"):
            blocks["GEO TREND"] = (
                "GEO TREND", SECTION_TITLE_GEO_TREND, kit.trend_topic_block(geo_res),
                kit.ai_badge(), "")

    # ④ 策略研判（倾向 / 结论已置顶，此处只展开依据；MACD 是栏内子块）
    #    同子栏合并：12 栏「板块热力」已按行情口径展示的板块，强度榜不再重复其
    #    涨跌 / 主力净流入（与 12 栏同一份 pan 数据、同一条切片规则，见 _panorama_heat_selection）。
    merge_boards = (_panorama_heat_selection(pan, getattr(kit, "theme", ""))
                    if (SUB_MERGE_ENABLED and review_html) else set())
    board_owner = SUB_MERGE_OWNER_MARKET_REVIEW if merge_boards else ""
    strategy_html = kit.ai_block(ai_result, merge_boards=merge_boards,
                                 board_owner=board_owner) if ai_result.get("available") else \
        _quant.macd_strategy.render_strategy(ai_result.get("macd"), kit,
                                              limit=9 if LITE_ENABLED else 0,
                                              plain=PLAIN())
    if strategy_html:
        blocks["STRATEGY READ"] = (
            "STRATEGY READ", SECTION_TITLE_STRATEGY, strategy_html,
            kit.badge("量化策略", "ai"), "",
        )
        # 兼容旧 kicker 的锚点引用（如风险提示中的 AI READ 引用）
        blocks["AI READ"] = blocks["STRATEGY READ"]

    # ④b 【游资剑鱼】多专家流派趋势分析（独立栏目）：Weinstein 四阶段 / 均线排列 + 上游
    #     评委规则打分。日线复用 MACD 栏目同一批；规则引擎缺席或日线不足 → 整栏缺席。
    uzi_src = data.get(UZI_TREND_SOURCE_NAME) or {}
    uzi_res = _uzi_result(data)      # 正文与「🦑 AI帮你提鲜」共用同一份结果（不另算一套）
    if isinstance(uzi_src, dict) and uzi_src.get("status") == "success":
        uzi_html = _render_uzi_trend(uzi_src, kit)
        if uzi_html:
            uzi_panel = uzi_res.get("panel") or {}
            uzi_caption = ("" if PLAIN() else
                           f"{uzi_panel.get('investors', 0)} 位评委 × "
                           f"{uzi_res.get('rules_enabled', 0)} 条价格类规则 · "
                           f"收盘日 {_asof_short(uzi_res.get('latest_as_of'))}")
            blocks["UZI TREND"] = (
                "UZI TREND", SECTION_TITLE_UZI_TREND, uzi_html,
                kit.badge("量化策略", "ai"), uzi_caption)

    # ⑤ 趋势跟踪：全网 36 个新闻源头（港股挖掘）+ 内地财经媒体 18 家（标题池覆盖）
    #    + 多平台信息员（Reddit / StockTwits / TradingView / Bogleheads），
    #    任一来源抓取成功且有内容才渲染；全部缺席则整栏不进正文。
    if ((data.get("Reddit") or {}).get("status") == "success"
            or (data.get(HK_NEWS_SOURCE_NAME) or {}).get("status") == "success"
            or (data.get(MAINLAND_NEWS_SOURCE_NAME) or {}).get("status") == "success"
            or any((data.get(n) or {}).get("status") == "success"
                   for n in _active_public_site_names())):
        digest = _trend_clues_block(data, kit)
        if digest:
            blocks["TREND TRACKING"] = (
                "TREND TRACKING", SECTION_TITLE_TREND, digest, "", "")

    # ⑤b 【沸腾花蛤】情绪热点因子量化分析（2026-10-13 新增，2026-10-19 由「内地财经热点榜」
    #     更名）：18 家内地财经媒体窗口内标题按主题词表聚类（规则合成、确定性），并附每家的
    #     时效体检（条数 / 最新时间 / 滞后小时数 / 暂缺点名）；2026-10-19 起叠加本地 AI 分析
    #     三件套——⚖ 情绪总览、🔥 热点聚合、⚠ 预警风险点（全部标题级词典启发式，非校准概率）。
    #     源头整源不可用或窗口内 0 条 → 整栏缺席，不占位。
    hotlist_res = None      # 结果对象留存，供「⌁ AI 研判」与「🦑 AI帮你提鲜」复用同一份数字
    if MAINLAND_HOTLIST_ENABLED:
        mainland_src = data.get(MAINLAND_NEWS_SOURCE_NAME) or {}
        # news_corpus / date_str：2026-10-20 起供「🔭 预警趋势」按存档近 7 日逐日重算
        # （同一份风险词表）；缺存档时趋势行整行不出，其余分析不受影响。
        hotlist_res = build_mainland_hotlist(mainland_src, news_corpus=news_corpus,
                                             date_str=date_str)
        if hotlist_res:
            hot_html = _mainland_hotlist_block(hotlist_res, kit)
            if hot_html:
                caption = ""
                if not PLAIN():
                    bits = [f'{hotlist_res["total_sources"]} 家内地财经媒体 · 72 小时窗口 · '
                            f'扫描 {hotlist_res["scanned"]} 条 · 进榜 {hotlist_res["total"]} 条']
                    if hotlist_res.get("merged"):
                        bits.append(f'跨源同题合并 {hotlist_res["merged"]} 条')
                    bits.append("主题按固定词表命中（第一条命中的主题，不重复计数）")
                    bits.append("情绪 / 风险为本地词典启发式（标题级，非校准概率）")
                    bits.append("预警趋势按存档近 7 日逐日重算（同一份风险词表，缺存档不出）")
                    caption = " ｜ ".join(bits)
                blocks["MAINLAND HOTLIST"] = (
                    "MAINLAND HOTLIST", SECTION_TITLE_MAINLAND_HOTLIST, hot_html,
                    kit.badge("情绪因子", "ai"), caption)

    # ⑥ 资讯：三个资讯栏目（东方财富快讯 / 【无敌帝王蟹】全球头条 / 港股名家频道）
    #    自 2026-10-02 起全部在页面隐藏（用户要求），不再单独渲染为栏目；
    #    原始抓取数据照旧保留，仅作为 媒体风险 / 政策因子 / 策略研判 / 新闻情绪 /
    #    逐栏 AI 研判 / AI帮你提鲜 / 数据审计 的信号源（与「东方财富快讯」隐藏时的口径完全一致）。
    #    A股资讯已按用户要求移除，其数据不再采集。
    #    风险提示命中这些标题时 shown=False（见 build_daily_quant_strategy），
    #    因此保留完整标题、不生成指向已隐藏栏目的死链锚点。

    # ⑦ 媒体舆情风险点：A/H 成交活跃标的，具体事件事实优先于模糊情绪。
    #     复用同一 72h 标题池与 sentiment_history 新闻量基线；2026-10-21 起
    #     无风险时展示“监控中”占位，不再静默缺席（避免“栏目不见”误判）。
    media_risk_result = {}
    if MEDIA_RISK_ENABLED:
        media_risk_result = build_media_risk(
            data, date_str or _today_str(), sentiment_history,
            news_corpus=news_corpus)
        if media_risk_result.get("available"):
            red_orange = sum(int((media_risk_result.get("level_counts") or {}).get(k) or 0)
                             for k in ("red", "orange"))
            blocks["MEDIA RISK"] = (
                "MEDIA RISK", SECTION_TITLE_MEDIA_RISK,
                _media_risk_block(media_risk_result, kit),
                kit.badge(f"{red_orange} 项高等级" if red_orange else "风险观察",
                          "bad" if red_orange else "warn"),
                "" if PLAIN() else "A股＋港股 · 72 小时标题事件 · 风险指数非概率",
            )
        else:
            # 清洁态：仍展示占位（监控中），不静默缺席；监控范围为空时亦给出诊断
            badge_text = "监控范围待恢复" if not media_risk_result.get("universe_n") else "监控中"
            badge_kind = "warn" if not media_risk_result.get("universe_n") else "ok"
            blocks["MEDIA RISK"] = (
                "MEDIA RISK", SECTION_TITLE_MEDIA_RISK,
                _media_risk_block(media_risk_result, kit),
                kit.badge(badge_text, badge_kind),
                "" if PLAIN() else "A股＋港股 · 72 小时标题事件 · 持续监控",
            )

    # ⑧ 新闻情绪：只有真正归因到个股时才出现（样本不足不再占位）
    senti_result = {}
    if AI_ANALYSIS_ENABLED:
        senti_result = build_news_sentiment(data, date_str or _today_str(),
                                            sentiment_history,
                                            news_corpus=news_corpus)
        if senti_result.get("by_market") and senti_result.get("total_matched"):
            blocks["NEWS SENTIMENT"] = (
                "NEWS SENTIMENT", SECTION_TITLE_NEWS_SENTIMENT,
                kit.sentiment_block(senti_result), kit.ai_badge(), "",
            )

    # 最终结论 / 前置盘点：核心判断放大显示，关键市场数字保留在同一栏核对。
    conclusion = _conclusion_pairs(kit, ai_result, market, pan, policy,
                                   quant=quant, weekly=weekly_res)
    # ☯ 今日卦象已移到卷首「诗与远方的海」，不属于市场预判：此栏只保留真实数据结论。
    if conclusion:
        blocks["FORECAST"] = ("FORECAST", SECTION_TITLE_FORECAST,
                               _conclusion_panel(kit, conclusion), "", "")
    summary = _summary_pairs(ai_result, pan, policy, source_items, today_n, total,
                             quant=quant, media_risk=media_risk_result,
                             backup_events=(data.get("_backup_info") or {}).get("events"))
    blocks["SUMMARY"] = ("SUMMARY", "总结", kit.kv(summary), "", "")

    # 栏目顺序固定为：今日预判 → ①发生了什么 → ②传播得怎么样 → ③可能会怎样 → ④我们该怎么办 → 总结；
    # 没有采集到社区样本时情绪因子缺席。
    sections = [blocks[k] for k in REPORT_SECTION_ORDER if k in blocks]

    # ⑧+⑨ 栏首结论：把原来埋在栏目末尾的「AI帮你提鲜」前置；旧「⌁ AI 研判」
    # 降为结论后的同源量化依据（只保留箭头前数据），形成「大白话结论 → 数字依据 → 正文」。
    # 若关闭提鲜，则仍把完整 AI 研判前置；若专用生成器因数据形态返回空，但栏目确实已渲染，
    # 使用不带数字/方向的诚实后备结论，绝不为了全覆盖硬编结果。
    judge_notes = build_section_ai_notes(
        data, policy=policy if (isinstance(policy, dict) and policy.get("available")) else None,
        senti=senti_result if (isinstance(senti_result, dict) and senti_result.get("available")) else None,
        fed_trend=fed_res if (isinstance(fed_res, dict) and fed_res.get("available")) else None,
        geo_trend=geo_res if (isinstance(geo_res, dict) and geo_res.get("available")) else None,
        hotlist=hotlist_res if (isinstance(hotlist_res, dict)
                                and hotlist_res.get("status") == "success") else None)

    ren_ctx = None
    decorated = []
    garnish_used = []   # 同一份日报里同一句活鲜比喻只出现一次（见 octopus_ren._seafood_garnish_parts）
    if REN_ENABLED:
        ren_ctx = {
            # 以下对象与对应正文严格同源；任何生成器都只能读取这些结构化结果。
            # 【沸腾花蛤】情绪热点因子量化分析：与正文 blocks["MAINLAND HOTLIST"] 同一份结果
            "hotlist": hotlist_res,
            "date_str": date_str or _today_str(),
            "notes": judge_notes,
            "market": market, "pan": pan, "policy": policy, "ai": ai_result,
            "quant": quant, "weekly": weekly_res, "hk7": hk7_res,
            "fed": fed_res, "geo": geo_res, "senti": senti_result,
            "retail_sentiment": retail_sentiment_result,
            "media_risk": media_risk_result,
            "sector_rotation": (rotation_src.get("result") or {}) if isinstance(rotation_src, dict) else {},
            "industry_rotation": (industry_src.get("result") or {}) if isinstance(industry_src, dict) else {},
            "macd": ai_result.get("macd") if isinstance(ai_result, dict) else {},
            "cal": cal, "yt": yt, "google": google, "em": em,
            "trend": _trend_section_stats(data),
            # 【游资剑鱼】：与正文 blocks["UZI TREND"] 用的同一份 run_trend() 结果
            "uzi": uzi_res,
            "coverage": {
                "today": today_n, "total": total,
                "missing": _missing_source_names(source_items),
            },
        }

    for kick, title, content, badge, caption in sections:
        if ren_ctx is not None:
            ren_ctx["_garnish_avoid"] = tuple(garnish_used) if SUB_MERGE_ENABLED else ()
            ren_block = _ren.section_ren_block(kick, ren_ctx)
            if not ren_block:
                ren_block = {
                    "text": _rendered_section_fallback_conclusion(kick),
                    "label": None, "p_pct": None, "metaphor": None,
                }
            if ren_block.get("metaphor"):
                garnish_used.append(ren_block["metaphor"])
            conclusion_html = _ren_judgment_row(ren_block["text"], kit, meta=ren_block)
            evidence_html = _section_notes_html(
                kick, judge_notes, kit, evidence_only=True, date_str=date_str)
            content = conclusion_html + evidence_html + content
        else:
            # --no-ren 只关大白话翻译；已有研判仍放在正文前，不再埋在栏目末尾。
            content = _section_notes_html(
                kick, judge_notes, kit, evidence_only=False, date_str=date_str) + content
        decorated.append((kick, title, content, badge, caption))
    sections = decorated

    # 卷首内容各自独立开关；卦象按报告日起卦，与行情结论无关，也不计入当天源。
    poem = _shiquan.get_opening_poem(data, allow_network=False) if (SHIQUAN_ENABLED and _shiquan.is_enabled()) else None
    bagua_html = ""
    if _bagua.ENABLED:
        try:
            bagua_html = _bagua.render_bagua_html(day=_bagua_report_day(date_str))
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ 卷首卦象渲染失败（date_str={date_str!r}）：{type(e).__name__}: {e}")
    # 短线速查卡收尾呈现：正文按 ①→④ 与总结阅读后，再给行动要点。
    # 取材全部是上面渲染正文用的同一批对象，缺数据自动缺席（LITE=0 / --full 整卡不出）。
    beginner_tips_html = ""
    if LITE_ENABLED:
        card_ctx = {
            "date_str": date_str or _today_str(),
            # 「今明必看」的日基准：报告日（YYYYMMDD）→ date 对象；解析不出来就不猜今明。
            "today": _short_card_base_date(date_str),
            "weekly": weekly_res, "quant": quant, "ai": ai_result,
            "pan": pan if pan_ok else {}, "cal": cal, "senti": senti_result,
            "coverage": {"today": today_n, "total": total},
        }
        # 🐣【新手三句话】（2026-10-16 用户要求「放在卦象后」）：先按同一份 card_ctx
        # 配对一次，再看卦象在不在——卦象在卷首 → 三句话紧跟卦象；
        # 卦象被关掉（OCTOPUS_BAGUA=0）或起卦失败 → 仍留在速查卡末尾，内容不丢、不重复。
        tips = _short.pair_beginner_tips(card_ctx)
        card = _short_card_section(card_ctx, kit, today_n, total,
                                   tips=tips, tips_in_card=not bagua_html)
        if card:
            sections.append(card)
        if bagua_html:
            beginner_tips_html = _beginner_tips_block(tips, kit)
    return {
        "sections": sections,
        "total": total,
        "today_n": today_n,
        "content_n": content_n,
        "market": market,
        "poem": poem,
        "bagua_html": bagua_html,
        "beginner_tips_html": beginner_tips_html,
    }


def _poetry_sea_section(parts, kit):
    """刊头后的单一卷首栏目：诗泉诗选 + ☯ 今日卦象 + 🐣 新手三句话，同一栏目内分块展示。

    用主题自己的 section 渲染头部与 SECTION_BODY_MARK，分条时诗和卦先按一个
    栏目装箱；卷首编号「序」不挤占今日预判的 00 栏。三块都不可用时不出空栏目。

    🐣 新手三句话（2026-10-16 用户要求「放在卦象后」）：三句话紧跟卦象之后，
    让入门读者在翻到行情数字之前先拿到「看方向 / 放止损 / 别动手」三句人话；
    卦象缺席时 parts["beginner_tips_html"] 为空串，三句话仍由速查卡末尾渲染。
    """
    poem_html = _shiquan.render_opening_poem_html(
        (parts or {}).get("poem"), theme=kit.theme)
    bagua_html = (parts or {}).get("bagua_html") or ""
    tips_html = (parts or {}).get("beginner_tips_html") or ""
    content = poem_html + bagua_html + tips_html
    return kit.section("序", "POETRY & SEA", SECTION_TITLE_POETRY_SEA, content) if content else ""


# ============================================================
# 报告生成（RETRO PIXEL 排版：终端 + 关卡 + 审计 + COLOPHON）
# ——只渲染有内容的区块；每个区块带来源、抓取时间与「当天/非当天/无数据」徽标
# ============================================================
# ============================================================
    # 策略研判 · 规则 / 量化合成，无需大模型 API
# ------------------------------------------------------------
# 基于当日已抓取的多源信号（实时行情、A股行业板块热力、热门榜单、
# 全球/东财/A股头条、港股名家频道观点）做确定性量化合成，输出板块趋势跟踪策略：
#   量化信号（多/空/中性 + 趋势分 + 置信度）、板块趋势强度榜（动量+资金+舆情三因子）、
#   技术速读（多空宽度与动能）、风险控制、量化配置（趋势跟踪入场/持有/规避信号）。
# 全部由规则计算，可复现、不调外部大模型、不伪造内容；明确标注「非投资建议」。
# 板块趋势跟踪核心：行业板块领涨/领跌 TOP 的涨跌幅 + 主力净流入 + 舆情提及，
# 经 z-score 标准化后加权合成趋势分（价格动量60% + 资金流30% + 舆情10%），
# 结合市场宽度与成交额做 regime 过滤，输出可执行的趋势跟踪信号与风险预算。
# 2026-08-06 起 QUANT ALLOC // 量化配置 · 趋势跟踪 不再列出榜单个股，只保留主题行；
# 2026-09-28 起原「AI 盘研判」正式升级为「策略研判」，
# 保留原情绪定调与风险提示，新增量化趋势分与板块轮动信号。
# 如需接大模型，可在 build_ai_analysis 内增加 LLM 分支（保留本规则作兜底）。
# ============================================================
AI_ANALYSIS_ENABLED = True

# 板块关键词：从行情/榜单/头条文本中识别板块提及热度
AI_SECTOR_KEYWORDS = {
    "半导体/芯片": ["半导体", "芯片", "集成电路", "晶圆", "中芯", "寒武纪", "北方华创",
                   "韦尔", "兆易", "设备", "光刻"],
    "AI/算力": ["AI", "人工智能", "算力", "大模型", "英伟达", "NVIDIA", "GPU",
                "光模块", "CPO", "服务器", "数据中心"],
    "新能源/锂电": ["新能源", "锂电", "电池", "光伏", "储能", "宁德", "比亚迪",
                    "逆变器", "氢能"],
    "医药/生物": ["医药", "生物", "创新药", "疫苗", "CRO", "制药", "医疗", "器械"],
    "地产/基建": ["地产", "房地产", "物业", "基建", "建材", "水泥", "建筑", "新城"],
    "金融/银行": ["银行", "券商", "保险", "证券", "信托", "金控", "信贷"],
    "消费": ["消费", "白酒", "食品", "饮料", "零售", "家电", "免税", "餐饮"],
    "黄金/有色": ["黄金", "有色", "铜", "铝", "稀土", "金属", "矿业", "锂矿"],
    "军工": ["军工", "国防", "航空", "船舶", "卫星", "航天"],
    "汽车": ["汽车", "整车", "零部件", "特斯拉", "理想", "蔚来", "小鹏", "小米汽车"],
}

# 舆情多/空关键词（子串匹配，叠加计数）
_AI_BULL_WORDS = ["涨", "升", "新高", "利好", "反弹", "回暖", "走强", "突破",
                  "创新高", "提振", "超预期", "上扬", "收涨", "飘红", "乐观",
                  "复苏", "宽松", "加码", "扩容"]
_AI_BEAR_WORDS = ["跌", "崩", "暴跌", "下挫", "走弱", "回落", "风险", "危机",
                  "警告", "抛售", "利空", "制裁", "衰退", "违约", "加息",
                  "缩表", "监管", "承压", "亏损", "爆雷", "破位", "跳水", "低迷"]
# 风险/宏观风险关键词（用于风险舆情与承压板块识别）
_AI_RISK_KEYWORDS = ["风险", "危机", "警告", "崩", "暴跌", "制裁", "衰退", "违约",
                     "加息", "缩表", "监管", "爆雷", "破位", "跳水", "利空",
                     "承压", "亏损", "诉讼", "调查", "处罚", "关税", "地缘",
                     "降级", "做空", "冻结", "停牌"]
# 风险否定词：标题同时含这些词时，往往「利空出尽/风险偏好走强」，不计入风险项
_AI_RISK_NEGATION = ["利好", "走强", "回暖", "收涨", "飘红", "超预期", "出尽",
                     "消退", "缓解", "复苏", "反弹", "宽松", "加码"]


def _ai_is_risk_title(title):
    """标题含风险关键词但同时又含利好/走强等否定词时，视为非风险项。"""
    if not any(k in title for k in _AI_RISK_KEYWORDS):
        return False
    return not any(n in title for n in _AI_RISK_NEGATION)


def _risk_ref_label(risk):
    """风险引用定位（主题无关）：正文栏目 + 条目序号，与渲染锚点一一对应。"""
    section = risk.get("section") or ""
    if risk.get("channel"):
        section = f"{section} · {risk['channel']}"
    return f"「{section}」第{risk.get('index', 0):02d}条"


def _risk_ref_detail(risk):
    """引用辅助定位：正文可见的发布时间 + 命中关键词（后者为新增信息）。"""
    bits = []
    if risk.get("section") == SECTION_TITLE_GLOBAL_HEADLINES and risk.get("source"):
        bits.append(risk["source"])
    moment = risk.get("time") or ""
    if moment and moment != "—":
        bits.append(moment)
    kws = risk.get("keywords") or []
    if kws:
        bits.append("命中：" + "/".join(kws))
    return " · ".join(bits)


def _ai_label(points):
    """把信号分映射为情绪标签（中文 + 英文 kicker）。"""
    if points >= 25:
        return "偏多", "BULLISH-LEANING"
    if points > 8:
        return "温和偏多", "MILDLY BULLISH"
    if points >= -8:
        return "中性", "NEUTRAL"
    if points > -25:
        return "温和偏空", "MILDLY BEARISH"
    return "偏空", "BEARISH"


def _ai_band(pct):
    """把单指数涨跌幅映射到动能档位（中文 + 语义色）。"""
    if pct >= 2:
        return "强势", C_GREEN
    if pct >= 0.5:
        return "偏强", C_GREEN
    if pct > -0.5:
        return "震荡", C_AMBER
    if pct > -2:
        return "偏弱", C_RED
    return "弱势", C_RED


def build_daily_quant_strategy(data):
    """规则合成跨市场综合研判（A股 + 港股 + 美股）。

    返回 dict；available=False 时调用方不渲染该区块（避免空分析）。
    纯确定性计算：不调用任何大模型 API，可复现，不伪造内容。
    """
    market = data.get("实时行情", {}) or {}
    quotes = market.get("quotes", {}) or {}
    hot = data.get("热门榜单", {}) or {}
    hot_markets = hot.get("markets", {}) or {}
    google = data.get("全球头条", {}) or {}
    em = data.get("东财快讯", {}) or {}
    yt = data.get("港股名家频道", {}) or {}
    macd_src = data.get(MACD_SOURCE_NAME) or {}
    macd_result = (macd_src.get("result") or {}) if MACD_ENABLED and macd_src.get("status") == "success" else {}

    google_headlines = google.get("headlines", []) or []
    em_headlines = em.get("headlines", []) or []
    yt_channels = yt.get("channels", []) or []

    # —— 1. 文本与结构化信号汇总 ——
    texts = []
    for it in google_headlines:
        if isinstance(it, dict):
            texts.append(it.get("title", ""))
    for it in em_headlines:
        if isinstance(it, dict):
            texts.append(it.get("title", ""))
            texts.append(it.get("summary", ""))
    for ch in yt_channels:
        for v in ch.get("videos", []) or []:
            texts.append(v.get("title", ""))
    all_text = " ".join(t for t in texts if t)

    # 结构化头条（含正文出处定位），用于风险项展示。
    # 每个条目：title / source / section（正文栏目名）/ index（栏目内序号，1-based，
    # 与渲染侧展示顺序一致）/ anchor（正文锚点 id）/ shown（该标题是否已在正文
    # 栏目展示）/ time（发布时间，供无序号栏目定位）/ channel（港股频道名）。
    # 三个资讯栏目（东财快讯 / 全球头条 / 港股名家频道）自 2026-10-02 起全部在页面隐藏
    # 独立栏目，故一律 shown=False（命中风险时保留完整标题展示，且不生成指向
    # 已隐藏栏目的死链锚点 h-em-* / h-gh-* / h-hk-*）。数据本身照旧参与
    # 情绪打分、政策因子、新闻情绪与审计。
    headlines_struct = []
    for i, it in enumerate(google_headlines, 1):
        if isinstance(it, dict):
            headlines_struct.append({
                "title": it.get("title", ""), "source": it.get("source", ""),
                "section": SECTION_TITLE_GLOBAL_HEADLINES,
                "index": i, "anchor": f"h-gh-{i:02d}",
                "shown": False,
                "time": it.get("published_cst") or "", "channel": "",
            })
    for i, it in enumerate(em_headlines, 1):
        if isinstance(it, dict):
            headlines_struct.append({
                "title": it.get("title", ""), "source": "东方财富",
                "section": "东财快讯", "index": i, "anchor": f"h-em-{i:02d}",
                "shown": False,
                "time": it.get("time") or "", "channel": "",
            })
    for c, ch in enumerate(yt_channels, 1):
        for v, video in enumerate(ch.get("videos", []) or [], 1):
            headlines_struct.append({
                "title": video.get("title", ""), "source": ch.get("name", ""),
                "section": "港股名家频道", "index": v,
                "anchor": f"h-hk-{c:02d}-{v:02d}",
                "shown": False,
                "time": video.get("published_cst") or "", "channel": ch.get("name", ""),
            })

    # 热门榜单个股不再单独列入关注清单（2026-08-06 起 WATCH LIST 只保留主题行）；
    # 个股仍作为 策略研判输入：板块趋势识别与活跃标的提及。

    # —— 2. 情绪打分 ——
    # 数据日期落后于最新交易日的品种（如 Yahoo 凌晨回退到上上个交易日的港股 / A股）
    # 不计入「主要指数平均」：把上周五的涨跌和昨夜美股收盘平均在一起没有意义。
    lagging_quotes = _market_lagging(market)
    changes = []
    for label, q in quotes.items():
        if label in lagging_quotes:
            continue
        try:
            changes.append(float(q["change_pct"]))
        except (TypeError, ValueError, KeyError):
            pass
    quotes_asof = _market_newest_session(market)

    present = [m for m, md in hot_markets.items() if (md or {}).get("stocks")]

    bull = sum(all_text.count(w) for w in _AI_BULL_WORDS)
    bear = sum(all_text.count(w) for w in _AI_BEAR_WORDS)
    net = bull - bear

    points = 0.0
    signals = 0
    if changes:
        avg = sum(changes) / len(changes)
        points += max(-40, min(40, avg * 6))
        signals += 1
    if present:
        points += {3: 6, 2: 3, 1: 1}.get(len(present), 0)
        signals += 1
    if all_text:
        points += max(-20, min(20, net * 2))
        signals += 1
    points = max(-100, min(100, round(points)))

    has_data = bool(changes) or bool(present) or bool(all_text)
    if not AI_ANALYSIS_ENABLED:
        return {"available": False}
    if not has_data:
        # MACD 单独可用时仍渲染策略子块，但不把技术状态伪装成跨市场中性分 / 概率。
        return {"available": False, "macd": macd_result}

    sentiment_label, sentiment_en = _ai_label(points)
    sentiment_color = C_GREEN if points > 8 else (C_RED if points < -8 else C_AMBER)
    confidence = {3: "高", 2: "中", 1: "低"}.get(signals, "低")

    reason_parts = []
    if changes:
        part = f"主要指数平均{sum(changes) / len(changes):+.2f}%"
        if quotes_asof:
            part += f"（截至 {quotes_asof[5:]}"
            if lagging_quotes:
                part += f"，{'、'.join(sorted({_market_group_of(l) for l in lagging_quotes}))}行情滞后未计入"
            part += "）"
        reason_parts.append(part)
    if present:
        reason_parts.append(f"{len(present)} 个市场榜单活跃")
    if all_text:
        tone = "多" if net > 0 else ("空" if net < 0 else "平")
        reason_parts.append(f"舆情净{tone}（利好 {int(bull)} / 利空 {int(bear)}）")
    reason = "；".join(reason_parts) + "。" if reason_parts else "信号不足。"

    # —— 3. 板块热度 ——
    sector_counts = {}
    for sec, kws in AI_SECTOR_KEYWORDS.items():
        c = sum(all_text.count(k) for k in kws)
        if c:
            sector_counts[sec] = c
    sectors_strong = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)[:4]

    # 承压板块：出现在真正风险舆情中的板块
    risk_titles = [h["title"] for h in headlines_struct if _ai_is_risk_title(h["title"])]
    risk_joined = " ".join(risk_titles)
    sectors_weak = [sec for sec, kws in AI_SECTOR_KEYWORDS.items()
                   if any(k in risk_joined for k in kws)][:3]

    # —— 3.5 板块趋势跟踪量化评分（价格动量60% + 资金流30% + 舆情10%）——
    # 数据源：A股大盘全景的行业板块领涨/领跌（东财 push2 免费接口），含涨跌幅与主力净流入
    pan = data.get("A股大盘全景", {}) or {}
    pan_sectors = []
    try:
        pan_sectors = list(((pan.get("sectors") or {}).get("leading") or []) ) + list(((pan.get("sectors") or {}).get("lagging") or []))
    except Exception:
        pan_sectors = []
    quant_sectors = []
    if pan_sectors:
        # 收集价格与资金流用于标准化
        chgs = []
        flows = []
        for s in pan_sectors:
            try:
                chgs.append(float(s.get("chg_pct")))
            except Exception:
                pass
            try:
                f = s.get("main_inflow")
                if f is not None:
                    flows.append(float(f))
            except Exception:
                pass
        # 均值与标准差（防御：样本不足时退化为排名法）
        def _mean_std(vals):
            if not vals:
                return 0.0, 1.0
            m = sum(vals)/len(vals)
            var = sum((x-m)**2 for x in vals)/len(vals) if len(vals)>1 else 1.0
            std = var**0.5 if var>1e-9 else 1.0
            return m, std
        chg_m, chg_std = _mean_std(chgs)
        flow_m, flow_std = _mean_std(flows)
        max_sector_hits = max(sector_counts.values()) if sector_counts else 1
        for s in pan_sectors:
            name = str(s.get("name") or "").strip()
            if not name:
                continue
            chg = None
            try:
                chg = float(s.get("chg_pct"))
            except Exception:
                chg = None
            inflow = s.get("main_inflow")
            try:
                inflow_f = float(inflow) if inflow is not None else None
            except Exception:
                inflow_f = None
            # 舆情分：优先用板块名直接命中，其次用 AI 关键词映射
            news_hits = all_text.count(name) if name else 0
            if news_hits == 0:
                for sec_ai, kws in AI_SECTOR_KEYWORDS.items():
                    if any(kw in name or name in kw for kw in kws):
                        news_hits = max(news_hits, sector_counts.get(sec_ai, 0))
                        break
            # 标准化
            if chg is not None:
                price_z = (chg - chg_m)/chg_std if chg_std else 0
            else:
                price_z = 0
            price_z = max(-3, min(3, price_z))
            if inflow_f is not None:
                flow_z = (inflow_f - flow_m)/flow_std if flow_std else 0
            else:
                flow_z = 0
            flow_z = max(-3, min(3, flow_z))
            news_score = (news_hits/max_sector_hits*2) if max_sector_hits else 0
            news_score = max(0, min(2, news_score))
            composite = round(0.6*price_z + 0.3*flow_z + 0.1*news_score, 2)
            if composite >= 1.2:
                trend, signal = "强势趋势", "趋势跟踪·持有/加仓"
            elif composite >= 0.5:
                trend, signal = "偏强趋势", "趋势跟踪·逢低布局"
            elif composite >= -0.5:
                trend, signal = "震荡", "波段操作·高抛低吸"
            elif composite >= -1.2:
                trend, signal = "偏弱趋势", "谨慎观望·轻仓"
            else:
                trend, signal = "弱势趋势", "规避·止损为主"
            # 资金与价格背离修正：放量下跌或缩量上涨降档
            if chg is not None and inflow_f is not None:
                if chg > 0 and inflow_f < 0:
                    signal = "量价背离·谨慎追高"
                elif chg < 0 and inflow_f > 0:
                    signal = "资金托底·关注企稳"
            quant_sectors.append({
                "name": name, "chg": chg, "inflow": inflow_f, "news_hits": news_hits,
                "composite": composite, "trend": trend, "signal": signal,
                "code": str(s.get("code") or ""),
            })
        quant_sectors.sort(key=lambda x: x["composite"], reverse=True)
    # 量化信号与 regime（结合市场宽度与动能）
    regime = sentiment_label
    quant_signal = f"{regime}（信号{points:+d}）"
    if pan_sectors and quant_sectors:
        top = quant_sectors[0]
        bottom = quant_sectors[-1]
        if top["composite"] >= 0.8 and top["chg"] is not None and top["chg"] > 1:
            quant_signal = f"趋势跟踪·重点 {top['name']}（{top['trend']}）"
        elif bottom["composite"] <= -0.8:
            quant_signal = f"防御为主·规避 {bottom['name']}（{bottom['trend']}）"

    # —— 4. 技术速读（指数动能聚合；2026-09-09 起不再逐条复述行情数值）——
    # 行情明细数字的唯一展示位置是【及时秋刀鱼】AI 行情复盘；此处只保留聚合（涨跌家数、
    # 平均涨跌、最强/最弱点名）与 AI 解读，避免同一数字在页内出现三次
    # （旧版：行情报价 + 指数动能明细表 + 多因子矩阵雅虎明细行）。
    # tech_rows 保留（兼容既有调用），渲染侧改用 tech_stats。
    tech_rows = []
    tech_moves = []  # (label, pct, band)，供聚合与最强/最弱点名
    for label, q in quotes.items():
        try:
            pct = float(q["change_pct"])
        except (TypeError, ValueError, KeyError):
            continue
        band, bcolor = _ai_band(pct)
        tech_rows.append((label, f"{pct:+.2f}%", band, bcolor))
        tech_moves.append((label, pct, band))
    ups = sum(1 for p in changes if p > 0)
    downs = sum(1 for p in changes if p < 0)
    flats = sum(1 for p in changes if p == 0)
    tech_avg = (sum(changes) / len(changes)) if changes else None
    tech_best = max(tech_moves, key=lambda m: m[1]) if tech_moves else None
    tech_worst = min(tech_moves, key=lambda m: m[1]) if tech_moves else None
    tech_stats = {
        "count": len(tech_moves), "ups": ups, "downs": downs, "flats": flats,
        "avg": tech_avg,
        "best": {"label": tech_best[0], "band": tech_best[2]} if tech_best else None,
        "worst": {"label": tech_worst[0], "band": tech_worst[2]} if tech_worst else None,
    }
    if ups > downs:
        tech_read = "多数指数上行，动能偏强，留意上方整数关口与前高。"
    elif downs > ups:
        tech_read = "多数指数承压，短线偏弱，关注近期支撑与量能变化。"
    else:
        tech_read = "指数分化/震荡，方向待明朗，宜控制仓位、等待确认。"

    # —— 5. 风险提示（去重引用；2026-09-09 起不再复述正文已展示的标题全文）——
    # 同一标题只保留首次命中的出处（跨栏目重复标题不再重复列出）；
    # shown=True 的条目渲染为「栏目 + 序号 + 命中关键词」引用并锚点跳转，
    # 全文只在正文栏目出现一次；shown=False（正文截断未展示，如港股频道
    # 第 4 条及以后）的条目保留全文展示，以免信息丢失。
    risks = []
    _seen_risk_titles = set()
    for h in headlines_struct:
        title = h["title"]
        if not title or not _ai_is_risk_title(title) or title in _seen_risk_titles:
            continue
        _seen_risk_titles.add(title)
        risks.append({
            **h,
            "keywords": [k for k in _AI_RISK_KEYWORDS if k in title][:3],
        })
        if len(risks) >= 5:
            break

    # —— 5.5 风险预算（量化风控）——
    if risks:
        risk_note = f"趋势跟踪风险预算：检测到 {len(risks)} 项风险舆情，建议控制回撤，单板块止损±3%~5%，总仓位暴露≤60%。"
    else:
        risk_note = "趋势跟踪风险预算：未检出显著风险舆情，趋势策略可正常执行，注意量能与资金流背离止盈。"

    # —— 6. 明日关注 ——
    # 2026-08-06 起 QUANT ALLOC // 量化配置 · 趋势跟踪 不再列出榜单个股（原最多 8 只），
    # 只保留「主题关注」一行：主题来自板块热度前列，个股仅作为研判输入不单独展示。
    themes = "、".join(sec for sec, _ in sectors_strong[:3])

    return {
        "available": True,
        "score": int(points),
        "confidence": confidence,
        "sentiment_label": sentiment_label,
        "sentiment_en": sentiment_en,
        "sentiment_color": sentiment_color,
        "reason": reason,
        "sectors_strong": sectors_strong,
        "sectors_weak": sectors_weak,
        "quant_sectors": quant_sectors,
        "regime": regime,
        "quant_signal": quant_signal,
        "macd": macd_result,
        "risk_note": risk_note,
        "tech_rows": tech_rows,
        "tech_stats": tech_stats,
        "tech_read": tech_read,
        "risks": risks,
        "themes": themes,
    }

def build_ai_analysis(data):
    """兼容别名：原 AI 盘研判入口，现为策略研判。"""
    return build_daily_quant_strategy(data)

def _ai_analysis_block(res, merge_boards=(), board_owner=""):
    """渲染「策略研判」：量化信号优先、板块趋势榜分层、内容使用独立像素面板。

    merge_boards / board_owner：跨栏「同子栏合并」（见 SUB_MERGE_ENABLED）——
    这些板块的涨跌 / 主力净流入已在 AI 行情复盘 · 板块热力按行情口径展示，
    强度榜只留趋势分 / 趋势 / 信号，避免同一批数字在正文里出现两次。
    """
    color = res["sentiment_color"]
    score = int(res["score"])

    def metric_cell(label, value, value_color, first=False):
        border = "" if first else f"border-left:1px solid {C_ACCENT_SOFT};"
        return (f'<td width="33%" valign="top" style="padding:8px 6px;{border}text-align:center;">'
                f'<div style="font-size:8px;color:{C_MUTED};font-family:{FONT_MONO};font-weight:900;'
                f'letter-spacing:1px;">{label}</div>'
                f'<div style="font-size:15px;color:{value_color};font-family:{FONT_MONO};font-weight:900;'
                f'padding-top:3px;line-height:1.25;">{value}</div></td>')

    # 专业分析总览：方向信号与关键指标先列出，主结论在栏目末尾单独强调。
    hero = (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
        f'border:1px solid {C_VIOLET};background:{C_AI_BG};box-shadow:7px 7px 0 #000;">'
        f'<tr><td colspan="2" style="padding:5px 9px;background:{C_VIOLET};color:{C_BG};'
        f'font-size:10px;font-weight:900;font-family:{FONT_MONO};letter-spacing:1px;">'
        f'◆ QUANT CORE // 每日量化策略 · 板块趋势跟踪</td></tr>'
        f'<tr><td width="68" valign="middle" style="padding:12px 4px 10px 12px;">'
        f'{_pixel_icon("STRATEGY READ", 54)}</td>'
        f'<td valign="middle" style="padding:12px 12px 10px 8px;">'
        f'<div style="font-size:9px;color:{C_LEMON};font-family:{FONT_MONO};font-weight:900;'
        f'letter-spacing:2px;">QUANT SIGNAL // 量化信号</div>'
        f'<div style="font-size:28px;color:{color};font-family:{FONT_MONO};font-weight:900;'
        f'line-height:1.15;padding-top:4px;text-shadow:2px 2px 0 #000;">'
        f'{_esc(res["sentiment_label"])} <span style="font-size:14px;">{("▲" if score > 8 else ("▼" if score < -8 else "■"))}</span></div>'
        f'<div style="font-size:9px;color:{C_MUTED};font-family:{FONT_MONO};font-weight:900;'
        f'letter-spacing:1px;padding-top:4px;">{_esc(res["sentiment_en"])}</div>'
        f'</td></tr>'
        f'<tr><td colspan="2" style="padding:0 10px 11px;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
        f'border:1px solid {C_ACCENT_SOFT};background:#0A0E1D;"><tr>'
        f'{metric_cell("DIRECTION / 方向", _esc(res["sentiment_label"]), color, True)}'
        f'{metric_cell("SIGNAL / 信号分", f"{score:+d}", color)}'
        f'{metric_cell("CONF / 置信度", _esc(res["confidence"]), C_LEMON)}'
        f'</tr></table>'
        f'<div style="padding-top:8px;font-size:9px;color:{C_MUTED};font-family:{FONT_MONO};">'
        f'SIGNAL POWER&nbsp; {_signal_meter(abs(score), 100, color, 10)}</div>'
        f'</td></tr></table>'
    )

    # 栏目结尾用高亮黄框与更大字号突出最终结论。
    conclusion_body = (
        f'<div style="font-size:9px;color:{C_LEMON};font-weight:900;font-family:{FONT_MONO};'
        f'letter-spacing:1px;">FINAL TAKEAWAY // 核心结论</div>'
        f'<div style="font-size:14px;color:{C_INK};font-weight:900;line-height:1.9;'
        f'font-family:{FONT_MONO};padding-top:4px;">{_esc(res["reason"])}</div>'
    )
    conclusion_html = _pixel_panel("量化主结论 // QUANT THESIS", conclusion_body, C_LEMON, "◆")

    # 板块趋势跟踪：量化趋势分榜（价格动量60% + 资金流30% + 舆情10%）
    quant_sectors = res.get("quant_sectors") or []
    if quant_sectors:
        rows = []
        merged_names = []
        for sec in quant_sectors[:6]:
            chg = sec.get("chg")
            badge = _trend_badge(chg, compact=True) if chg is not None else '<span style="color:%s;">■ --</span>' % C_FAINT
            inflow = sec.get("inflow")
            flow_txt = _format_amount(inflow) if inflow is not None else "—"
            name = str(sec.get("name") or "")
            if (SUB_MERGE_ENABLED and board_owner and name
                    and name in set(merge_boards)):
                # 同子栏合并：该板块的涨跌 / 主力净流入已在 12 栏按行情口径展示。
                merged_names.append(name)
                badge = f'<span style="color:{C_FAINT};">{SUB_MERGE_POINTER}</span>'
                flow_txt = "—"
            trend = _esc(sec.get("trend") or "—")
            sig = _esc(sec.get("signal") or "—")
            score_txt = f'{sec.get("composite", 0):+.2f}'
            # 根据趋势分着色
            comp = sec.get("composite", 0)
            if comp >= 0.5:
                comp_color = C_GREEN
            elif comp <= -0.5:
                comp_color = C_RED
            else:
                comp_color = C_AMBER
            rows.append([
                f'<span style="color:{comp_color};font-weight:900;">{score_txt}</span>',
                f'<span style="color:{C_INK};font-weight:900;">{_esc(sec.get("name") or "")}</span>',
                badge,
                f'<span style="color:{C_CYAN};">{flow_txt}</span>',
                f'<span style="color:{comp_color};">{trend}</span>',
                f'<span style="color:{C_LEMON};">{sig}</span>',
            ])
        # 用 _pixel_table 展示多列
        sec_header = ["趋势分", "板块", "涨跌", "主力", "趋势", "信号"]
        sectors_body = _pixel_table(sec_header, rows, aligns=("right","left","center","right","center","left"))
        if merged_names:
            sectors_body += (f'<div style="font-size:10px;color:{C_FAINT};margin-top:6px;padding:4px 6px;'
                             f'line-height:1.7;font-family:{FONT_MONO};">'
                             f'{SUB_MERGE_POINTER} · {sub_merge_pointer_text(SUB_MERGE_NOTE_BOARD, board_owner)}'
                             f'（已合并：{"、".join(_esc(x) for x in merged_names)}）</div>')
        weak = [s for s in quant_sectors if (s.get("composite") or 0) < -0.5][:2]
        if weak:
            sectors_body += (f'<div style="font-size:11px;color:{C_RED};margin-top:8px;padding:6px 8px;'
                             f'line-height:1.7;font-family:{FONT_MONO};font-weight:900;border:1px solid {C_RED};'
                             f'background:{C_DOWN_BG};">▼ 规避/弱势板块 // '
                             f'{" / ".join(_esc(s.get("name") or "") for s in weak)}</div>')
        sectors_html = _pixel_panel("SECTOR TREND // 板块趋势跟踪 · 量化强度榜", sectors_body, C_CYAN, "✚")
    elif res["sectors_strong"]:
        max_hits = max(cnt for _, cnt in res["sectors_strong"])
        sec_rows = [
            (f'<span style="color:{C_CYAN};font-weight:900;">✚</span> {_esc(sec)}',
             f'{_signal_meter(cnt, max_hits, C_CYAN)} '
             f'<span style="color:{C_INK};font-size:10px;">{cnt} HIT</span>', C_INK)
            for sec, cnt in res["sectors_strong"]
        ]
        sectors_body = _mini_table(sec_rows)
        if res["sectors_weak"]:
            sectors_body += (f'<div style="font-size:11px;color:{C_RED};margin-top:8px;padding:6px 8px;'
                             f'line-height:1.7;font-family:{FONT_MONO};font-weight:900;border:1px solid {C_RED};'
                             f'background:{C_DOWN_BG};">▼ 承压板块 // '
                             f'{" / ".join(_esc(s) for s in res["sectors_weak"])}</div>')
        sectors_html = _pixel_panel("SECTOR TREND // 板块热度（舆情）", sectors_body, C_CYAN, "✚")
    else:
        sectors_body = (f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;'
                        f'font-family:{FONT_MONO};">■ NO SECTOR SIGNAL</div>')
        sectors_html = _pixel_panel("SECTOR TREND // 板块趋势跟踪", sectors_body, C_CYAN, "✚")

    # 指数动能聚合：明细数值只在【及时秋刀鱼】AI 行情复盘展示，此处仅保留聚合与解读（2026-09-09 去重）。
    tech_stats = res.get("tech_stats") or {}
    if tech_stats.get("count"):
        _band_color = {"强势": C_GREEN, "偏强": C_GREEN, "震荡": C_AMBER,
                       "偏弱": C_RED, "弱势": C_RED}
        ups_n, downs_n = tech_stats.get("ups", 0), tech_stats.get("downs", 0)
        flats_n = tech_stats.get("flats", 0)
        breadth_line = (f'<span style="color:{C_GREEN};font-weight:900;">▲ {ups_n}</span> / '
                        f'<span style="color:{C_RED};font-weight:900;">▼ {downs_n}</span> / '
                        f'<span style="color:{C_AMBER};font-weight:900;">■ {flats_n}</span>'
                        f' · 平均 {_trend_badge(tech_stats.get("avg"), compact=True)}')
        extremes = []
        for tag, info in (("最强", tech_stats.get("best") or {}),
                          ("最弱", tech_stats.get("worst") or {})):
            if info.get("label"):
                bcolor = _band_color.get(info.get("band"), C_INK)
                extremes.append(
                    f'{tag} <b style="color:{C_INK};">{_esc(info["label"])}</b> '
                    f'<span style="color:{bcolor};font-weight:900;">'
                    f'[{_esc(info.get("band", ""))}]</span>')
        tech_body = _mini_table([
            (f'指数动能聚合（{tech_stats["count"]} 个指数）', breadth_line),
            ("动能两极", " · ".join(extremes) if extremes else "—"),
        ])
    else:
        tech_body = (f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;'
                     f'font-family:{FONT_MONO};">■ NO MARKET DATA</div>')
    tech_body += (f'<div style="font-size:12px;color:{C_INK};padding:8px 8px 2px;'
                  f'line-height:1.8;font-family:{FONT_MONO};font-weight:700;">'
                  f'<span style="color:{C_VIOLET};font-weight:900;">◆ AI 解读：</span>'
                  f'{_esc(res["tech_read"])}</div>')
    tech_html = _pixel_panel("TECH READ // 指数动能 · 趋势过滤", tech_body, C_VIOLET, "▲")

    # 风险与关注分别用红色、黄色面板，视觉层级与语义一致。
    # 风险条目去重（2026-09-09）：正文已展示的标题仅引用定位，不再复述全文。
    if res["risks"]:
        risk_rows = []
        for i, risk in enumerate(res["risks"]):
            bg = C_DOWN_BG if i % 2 == 0 else "transparent"
            if risk.get("shown") and risk.get("anchor"):
                main = (f'<a href="#{_esc(risk["anchor"])}" '
                        f'style="color:{C_RED};font-weight:900;text-decoration:none;'
                        f'border-bottom:1px dotted {C_RED};">→ {_esc(_risk_ref_label(risk))}</a>')
                sub = _risk_ref_detail(risk)
            else:
                # 正文截断未展示（如港股频道第 4 条及以后）：保留全文以免信息丢失
                sub_bits = [risk.get("source") or "", risk.get("time") or ""]
                if risk.get("keywords"):
                    sub_bits.append("命中：" + "/".join(risk["keywords"]))
                main = _esc((risk.get("title") or "")[:110])
                sub = " | ".join(x for x in sub_bits if x)
            risk_rows.append(_item_row("!", main, _esc(sub[:140]),
                                      icon_color=C_RED, row_bg=bg))
        risk_rows.append(
            f'<div style="font-size:10px;color:{C_MUTED};padding:6px 0 2px;'
            f'line-height:1.7;font-family:{FONT_MONO};">'
            f'已在正文栏目展示的风险条目仅引用定位 // 全文见原栏目，不重复展示</div>')
        risk_body = "".join(risk_rows)
    else:
        risk_body = (f'<div style="font-size:11px;color:{C_GREEN};padding:4px 0;'
                     f'font-family:{FONT_MONO};font-weight:900;">✓ CLEAR // 未检出显著风险舆情</div>')
    risk_html = _pixel_panel("RISK CTRL // 风险控制 · 趋势止损", risk_body, C_RED, "!")

    # 明日关注：2026-08-06 起不再列出榜单个股，面板只保留主题行（THEME UNLOCKED）。
    if res["themes"]:
        watch_body = (f'<div style="font-size:12px;color:{C_BG};font-weight:900;line-height:1.7;'
                      f'font-family:{FONT_MONO};background:{C_LEMON};padding:7px 9px;'
                      f'box-shadow:3px 3px 0 #000;">★ THEME UNLOCKED // {_esc(res["themes"])}</div>')
    else:
        watch_body = (f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;'
                      f'font-family:{FONT_MONO};">■ NO WATCH THEME</div>')
    watch_html = _pixel_panel("QUANT ALLOC // 量化配置 · 趋势跟踪", watch_body, C_LEMON, "⌖")

    note_html = _note("仅供参考 · 非投资建议")
    macd_html = _quant.macd_strategy.render_strategy(res.get("macd"), PIXEL_KIT,
                                                    limit=9 if LITE_ENABLED else 0,
                                                    plain=PLAIN())
    return (hero + macd_html + sectors_html + tech_html + risk_html + watch_html
            + conclusion_html + note_html)


# 兼容并行分支旧名入口（每日量化策略渲染入口）
_quant_strategy_block = _ai_analysis_block


# ============================================================
# 新闻情绪（NEWS SENTIMENT FACTORS · 确定性词表规则）
# ------------------------------------------------------------
# 2026-09-09 起按用户要求改为「逐股」：对最近成交日 A股 / 港股 / 美股
# 成交量前五（热门榜单 HOT_STOCK_TOP_N），逐只输出 AI 新闻情绪分、总结评论
# 与原因（由命中标题、词表、MOM 动量、ANV 新闻量确定性规则生成）。
# 窗口内（近 SENTI_WINDOW_HOURS=72 小时，含历史存档）标题逐条词表评分
# （HeadlineSentiment），按热门榜单个股名归因，输出 4 个因子：
#   DNS 窗口新闻情绪 ＝ (正−负)/总数（近 72h 标题窗口口径）
#   MOM 情绪动量 SentimentMomentum ＝ 近3个有评分日均值 − 近20个有评分日均值
#   ANV 异常新闻量 AbnormalNewsVolume ＝ 今日条数 vs 近30天均值±σ（z 值；
#       今日条数 > 均值+2σ 标异常放量；MOM/ANV 为自然日口径）
#   S   标题情绪 HeadlineSentiment ＝ 每条标题的词表净情绪（+1/0/−1，附命中词）
# 跨日窗口依赖 output/sentiment_history.json（随日报由 Actions 提交回库；
# main 流程：采集后加载 → 渲染 → 保存报告后落盘；--dry-run 只读不写；
# 同日多次运行按日期键覆盖，保证幂等；零报道日记 total=0、score=None）。
# 标题窗口内容依赖 output/news_history.json（每次运行合并本次抓取标题，
# 报告保存后原子落盘，随日报一并提交回库）。
# 窗口内无相关新闻的上榜股显示「暂无评分」并给出原因，绝不凭价格涨跌反推；
# 热门榜单缺席时栏目缺席。如需接大模型做标题标注，只需替换
# _score_headline_sentiment（调用方只依赖返回结构 {"s","pos","neg"}，
# 保留本规则作兜底）。
# ============================================================
SENTI_DISPLAY_N = 15       # 情绪栏目最多展示的已归因个股（页面按三大市场成交量前五逐股展示）
SENTI_MOM_SHORT_N = 3      # 动量短期窗口（有评分日，含今日）
SENTI_MOM_LONG_N = 20      # 动量长期窗口（有评分日，含今日）
SENTI_MOM_MIN_SHORT = 2    # 动量短期最少样本
SENTI_MOM_MIN_LONG = 5     # 动量长期最少样本
SENTI_VOL_WINDOW_N = 30    # 新闻量历史窗口（天，含零报道日，不含今日）
SENTI_VOL_MIN_DAYS = 5     # 新闻量最少历史样本
SENTI_HISTORY_KEEP_DAYS = 45  # 历史文件每只个股保留天数
SENTIMENT_HISTORY_FILENAME = "sentiment_history.json"

# ---- 因子标题窗口（2026-09-09 起从「当天 / 24h」放宽）----
# 政策因子：近 POLICY_WINDOW_DAYS=15 天内的政策 / 宏观新闻（自然日，含当日）；
# 新闻情绪因子：近 SENTI_WINDOW_HOURS=72 小时内的新闻（标题窗口）。
# 单次运行能抓到的标题只有 1-2 天 → 多日窗口依赖跨运行存档
# output/news_history.json（与 sentiment_history.json 同模式：每次运行合并
# 本次抓取 → 渲染使用 → 报告保存后原子落盘；GitHub Actions 一并提交回库，
# 同日重复运行按 日期+标题 去重，幂等）。情绪因子中 MOM / ANV 与跨日基线
# 仍按自然日口径（每只个股「当日」= 报告日当天新闻的桶），不受 72h 窗口影响。
SENTI_WINDOW_HOURS = 72          # 情绪标题窗口（小时，截至锚定时刻）
POLICY_WINDOW_DAYS = 15          # 政策标题窗口（自然日，含锚定日）
NEWS_HISTORY_KEEP_DAYS = POLICY_WINDOW_DAYS + 3   # 存档保留天数（含窗口余量）
NEWS_HISTORY_FILENAME = "news_history.json"

# 情绪词表：以策略研判 bull/bear 词为底，增加财报/资金/事件类词汇与
# 繁体变体（港股标题多为繁体）。命中按非重叠最长优先计数。
_SENTI_POS_WORDS = sorted(set(_AI_BULL_WORDS + [
    "大涨", "暴涨", "飙升", "飙涨", "涨停", "一字涨停", "历史新高",
    "好于预期", "盈利", "获利", "扭亏", "扭亏为盈", "增长", "大增",
    "翻倍", "翻番", "分红", "派息", "回购", "增持", "举牌", "买入评级",
    "上调评级", "获批", "获准", "中标", "签约", "合作", "收购", "注资",
    "扩产", "投产", "订单", "放量", "净流入", "流入", "纳入", "利好兑现",
    "大漲", "暴漲", "飆升", "漲停", "歷史新高", "超預期", "扭虧",
    "增長", "分紅", "回購", "上調", "買入", "獲批", "中標", "簽約",
    "收購", "淨流入",
]))
_SENTI_NEG_WORDS = sorted(set(_AI_BEAR_WORDS + [
    "大跌", "重挫", "崩盘", "熔断", "跌停", "一字跌停", "历史新低",
    "创新低", "下跌", "下滑", "下降", "减少", "骤降", "腰斩", "巨亏",
    "预亏", "预减", "首亏", "裁员", "召回", "诉讼", "调查", "问询",
    "立案", "处罚", "违约", "破产", "退市", "停牌", "做空", "降级",
    "关税", "流出", "净流出", "减持", "套现", "解禁", "计提", "商誉减值",
    "爆仓", "断供", "地雷", "出逃", "冻结", "崩盤", "熔斷", "歷史新低",
    "減少", "虧損", "巨虧", "裁員", "訴訟", "調查", "處罰", "違約",
    "破產", "降級", "關稅", "淨流出", "減持", "套現", "爆倉",
]))
_SENTI_NEGATORS = set("不没未无非否莫勿毋别")

# ---- 个股别名 / 行业概念归因（2026-09-09 增强）----
# 别名词典：{别名 → (market, code)}，用于标题中出现的简称 / 英文名 / 俗称归因。
# 仅覆盖高频出现的通用别名，不依赖大模型；新别名可在此追加。
_STOCK_ALIASES = {
    # A 股
    "宁德时代": ("A股", "300750"), "宁德": ("A股", "300750"), "CATL": ("A股", "300750"),
    "中际旭创": ("A股", "300308"), "旭创": ("A股", "300308"),
    "东山精密": ("A股", "002384"),
    "新易盛": ("A股", "300502"),
    "亨通光电": ("A股", "600487"), "亨通": ("A股", "600487"),
    "比亚迪": ("A股", "002594"), "BYD": ("A股", "002594"),
    "中国平安": ("A股", "601318"), "平安": ("A股", "601318"),
    "贵州茅台": ("A股", "600519"), "茅台": ("A股", "600519"),
    "招商银行": ("A股", "600036"), "招行": ("A股", "600036"),
    "工商银行": ("A股", "601398"), "工行": ("A股", "601398"),
    "建设银行": ("A股", "601939"), "建行": ("A股", "601939"),
    "农业银行": ("A股", "601288"), "农行": ("A股", "601288"),
    "中国银行": ("A股", "601988"),
    "中信证券": ("A股", "600030"), "中信": ("A股", "600030"),
    "隆基绿能": ("A股", "601012"), "隆基": ("A股", "601012"),
    "紫金矿业": ("A股", "601899"), "紫金": ("A股", "601899"),
    "中芯国际": ("A股", "688981"), "中芯": ("A股", "688981"),
    "海康威视": ("A股", "002415"), "海康": ("A股", "002415"),
    "立讯精密": ("A股", "002475"), "立讯": ("A股", "002475"),
    "药明康德": ("A股", "603259"), "药明": ("A股", "603259"),
    "恒瑞医药": ("A股", "600276"), "恒瑞": ("A股", "600276"),
    "三一重工": ("A股", "600031"), "三一": ("A股", "600031"),
    "科大讯飞": ("A股", "002230"), "讯飞": ("A股", "002230"),
    "龙版传媒": ("A股", "605577"), "龙版": ("A股", "605577"),
    "江波龙": ("A股", "301308"),
    # 港股
    "腾讯": ("港股", "00700"), "腾讯控股": ("港股", "00700"),
    "Tencent": ("港股", "00700"), "Tencent Holdings": ("港股", "00700"),
    "美团": ("港股", "03690"), "Meituan": ("港股", "03690"),
    "阿里巴巴": ("港股", "09988"), "阿里": ("港股", "09988"),
    "Alibaba": ("港股", "09988"), "Alibaba Group": ("港股", "09988"),
    "小米": ("港股", "01810"), "小米集团": ("港股", "01810"),
    "Xiaomi": ("港股", "01810"),
    "快手": ("港股", "01024"), "Kuaishou": ("港股", "01024"),
    "京东": ("港股", "09618"), "京东集团": ("港股", "09618"),
    "JD.com": ("港股", "09618"),
    "百度": ("港股", "09888"), "百度集团": ("港股", "09888"),
    "Baidu": ("港股", "09888"),
    "网易": ("港股", "09999"), "NetEase": ("港股", "09999"),
    "友邦": ("港股", "01299"), "友邦保险": ("港股", "01299"), "AIA": ("港股", "01299"),
    "海底捞": ("港股", "06862"),
    "优地机器人": ("港股", "02549"),
    "稀美资源": ("港股", "01536"),
    "长和": ("港股", "00001"), "CK Hutchison": ("港股", "00001"),
    "长实": ("港股", "01113"), "CK Asset": ("港股", "01113"),
    "汇丰": ("港股", "00005"), "汇丰控股": ("港股", "00005"),
    "HSBC": ("港股", "00005"), "HSBC Holdings": ("港股", "00005"),
    "港交所": ("港股", "00388"), "HKEX": ("港股", "00388"),
    "Hong Kong Exchanges and Clearing": ("港股", "00388"),
    # 美股
    "英伟达": ("美股", "NVDA"), "NVIDIA": ("美股", "NVDA"),
    "苹果": ("美股", "AAPL"), "Apple": ("美股", "AAPL"),
    "特斯拉": ("美股", "TSLA"), "Tesla": ("美股", "TSLA"),
    "微软": ("美股", "MSFT"), "Microsoft": ("美股", "MSFT"),
    "谷歌": ("美股", "GOOGL"), "Google": ("美股", "GOOGL"), "Alphabet": ("美股", "GOOGL"),
    "亚马逊": ("美股", "AMZN"), "Amazon": ("美股", "AMZN"),
    "Meta": ("美股", "META"), "脸书": ("美股", "META"), "Facebook": ("美股", "META"),
    "博通": ("美股", "AVGO"), "Broadcom": ("美股", "AVGO"), "AVGO": ("美股", "AVGO"),
    "台积电": ("美股", "TSM"), "TSMC": ("美股", "TSM"),
    "AMD": ("美股", "AMD"),
    "Intel": ("美股", "INTC"), "英特尔": ("美股", "INTC"),
    "美光": ("美股", "MU"), "Micron": ("美股", "MU"),
    "OpenAI": ("美股", "NVDA"),  # OpenAI 新闻通常与 NVDA 高度相关
    "Anthropic": ("美股", "NVDA"),  # AI 安全公司，归入 AI 算力链
}

# 行业 / 概念板块关键词 → 关联个股（market, code）列表。
# 标题提到行业 / 概念时，关联相关上榜个股（弱归因，标记 tag="sector"）。
_SECTOR_KEYWORDS = {
    "AI": [("A股", "300308"), ("A股", "300502"), ("美股", "NVDA"), ("港股", "00700"), ("港股", "09888")],
    "人工智能": [("A股", "300308"), ("A股", "300502"), ("美股", "NVDA"), ("港股", "00700")],
    "机器人": [("A股", "300308"), ("港股", "02549")],
    "人形机器人": [("A股", "300308"), ("港股", "02549")],
    "光模块": [("A股", "300308"), ("A股", "300502")],
    "半导体": [("A股", "688981"), ("美股", "NVDA"), ("美股", "AMD"), ("美股", "INTC"), ("美股", "MU")],
    "芯片": [("A股", "688981"), ("美股", "NVDA"), ("美股", "AMD"), ("美股", "INTC"), ("美股", "MU")],
    "新能源": [("A股", "300750"), ("A股", "601012"), ("A股", "002594"), ("港股", "01810")],
    "锂电": [("A股", "300750")],
    "电池": [("A股", "300750")],
    "光伏": [("A股", "601012")],
    "消费": [("A股", "600519"), ("港股", "06862"), ("港股", "03690")],
    "白酒": [("A股", "600519")],
    "银行": [("A股", "601318"), ("A股", "600036"), ("A股", "601398"), ("A股", "601939")],
    "券商": [("A股", "600030")],
    "黄金": [("A股", "601899"), ("港股", "00388")],
    "石油": [("港股", "00857")],
    "天然气": [("港股", "00857")],
    "房地产": [("港股", "00001"), ("港股", "01113")],
    "恒指": [("港股", "02800"), ("港股", "02828")],
    "恒生": [("港股", "02800"), ("港股", "02828")],
    "恒生科技": [("港股", "03033")],
    "标普": [("美股", "SPY")],
    "纳斯达克": [("美股", "QQQ")],
    "纳指": [("美股", "QQQ")],
    "期权": [("美股", "SPY"), ("美股", "QQQ")],
    "CPI": [("A股", "601318"), ("A股", "600036")],
    "PPI": [("A股", "601899")],
}


def _match_words_non_overlap(title, words):
    """词表最长优先非重叠匹配，返回 [(词, 起始下标)]（按出现顺序）。"""
    spans = []
    occupied = [False] * len(title)
    for word in sorted(words, key=len, reverse=True):
        if not word:
            continue
        start = 0
        while True:
            idx = title.find(word, start)
            if idx < 0:
                break
            if not any(occupied[idx:idx + len(word)]):
                spans.append((word, idx))
                for j in range(idx, idx + len(word)):
                    occupied[j] = True
            start = idx + 1
    spans.sort(key=lambda item: item[1])
    return spans


def _score_headline_sentiment(title):
    """标题情绪评分：正负命中数之差取符号，S∈{+1,0,−1}。

    命中词紧邻的前一字为否定词（不/没/未/无/非/否…）时翻转极性。
    返回 {"s","pos","neg","pos_n","neg_n"}（pos/neg 为展示用命中词，各≤3）。
    """
    title = title or ""
    pos_hits, neg_hits = [], []
    for word, idx in _match_words_non_overlap(title, _SENTI_POS_WORDS):
        flipped = idx > 0 and title[idx - 1] in _SENTI_NEGATORS
        (neg_hits if flipped else pos_hits).append(word)
    for word, idx in _match_words_non_overlap(title, _SENTI_NEG_WORDS):
        flipped = idx > 0 and title[idx - 1] in _SENTI_NEGATORS
        (pos_hits if flipped else neg_hits).append(word)
    pos_n, neg_n = len(pos_hits), len(neg_hits)
    net = pos_n - neg_n
    return {"s": 1 if net > 0 else (-1 if net < 0 else 0),
            "pos": pos_hits[:3], "neg": neg_hits[:3],
            "pos_n": pos_n, "neg_n": neg_n}


def _extract_stock_universe(hot):
    """从热门榜单提取个股宇宙 [{market, code, name, key}]（按 key 去重）。"""
    universe = []
    seen = set()
    markets = (hot or {}).get("markets", {}) or {}
    for market, payload in markets.items():
        for s in (payload or {}).get("stocks", []) or []:
            name = (s.get("name") or "").strip().replace(" ", "").replace("\u3000", "")
            if len(name) < 2:
                continue
            code = str(s.get("code") or "").strip()
            key = f"{market}:{code or name}"
            if key in seen:
                continue
            seen.add(key)
            universe.append({"market": market, "code": code, "name": name, "key": key})
    universe.sort(key=lambda u: len(u["name"]), reverse=True)
    return universe


def _headline_has_entity_token(title, token):
    """中文按子串，英文 / 代码按不区分大小写的字母数字边界匹配。"""
    text = str(title or "")
    word = str(token or "")
    if not text or not word:
        return False
    if word.isascii():
        return bool(re.search(
            rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", text, re.IGNORECASE))
    return word in text


def _attribute_headline(title, universe):
    """标题归因到个股（增强版 2026-09-09）：

    三层归因：
    1. 精确全名匹配（标题含 universe 中个股全名）；
    2. 别名 / 代码匹配（标题含 _STOCK_ALIASES 中的别名，或含个股代码）；
    3. 行业 / 概念板块归因（标题含 _SECTOR_KEYWORDS 中的关键词，弱归因）。

    返回 [universe_item]，每个 universe_item 额外带 tag 字段：
    - "name"  = 精确全名匹配
    - "alias" = 别名 / 代码匹配
    - "sector" = 行业概念弱归因
    一条标题可归因多只。去重（同一 key 只归因一次，优先强归因）。
    """
    if not title:
        return []
    universe_by_key = {u["key"]: u for u in universe}
    matched = {}  # key → (universe_item, tag_priority)
    # 1) 精确全名（英文名大小写不敏感且要求字母数字边界）
    for u in universe:
        if _headline_has_entity_token(title, u["name"]):
            if u["key"] not in matched:
                item = dict(u)
                item["tag"] = "name"
                matched[u["key"]] = (item, 0)
    # 2) 别名 / 代码
    for alias, (mkt, code) in _STOCK_ALIASES.items():
        if not _headline_has_entity_token(title, alias):
            continue
        target_key = f"{mkt}:{code}"
        if target_key in universe_by_key and target_key not in matched:
            item = dict(universe_by_key[target_key])
            item["tag"] = "alias"
            matched[target_key] = (item, 1)
    # 代码直接匹配（如标题含 "300308"）
    for u in universe:
        if u["key"] in matched:
            continue
        code = u.get("code") or ""
        if code and len(code) >= 3 and code in title:
            item = dict(u)
            item["tag"] = "alias"
            matched[u["key"]] = (item, 1)
    # 3) 行业 / 概念（弱归因，只补充未被强归因的 key）
    for keyword, targets in _SECTOR_KEYWORDS.items():
        if not _headline_has_entity_token(title, keyword):
            continue
        for mkt, code in targets:
            target_key = f"{mkt}:{code}"
            if target_key in universe_by_key and target_key not in matched:
                item = dict(universe_by_key[target_key])
                item["tag"] = "sector"
                matched[target_key] = (item, 2)
    # 按优先级排序（name > alias > sector）
    result = [item for item, _ in sorted(matched.values(), key=lambda x: x[1])]
    return result


def _factor_anchor_dt(date_str):
    """因子窗口的锚定时刻（北京时间）。

    生产运行（报告日 == 系统今天）→ 锚定当前时刻，保证「近 72 小时」严格从
    此刻起算；固定日期调用（测试 / 历史演示，报告日 ≠ 今天）→ 锚定报告日
    23:59:59，让夹具数据可复现、窗口确定性可断言。
    """
    try:
        report_day = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=CST)
    except (TypeError, ValueError):
        return datetime.now(CST)
    now = datetime.now(CST)
    if now.strftime("%Y%m%d") == date_str:
        return now
    return report_day.replace(hour=23, minute=59, second=59)


def _norm_item_ts(value):
    """把标题级时间规范成 "YYYY-MM-DD HH:MM"（北京时间字符串）；无法解析 → ""。"""
    if not isinstance(value, str):
        return ""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})", value.strip())
    return f"{m.group(1)} {m.group(2)}" if m else ""


def _norm_item_date(value):
    """把标题级日期规范成 ``YYYY-MM-DD``；支持政府网的中文/斜杠日期。"""
    return _normalise_policy_date(value) if value else ""


def _collect_headline_items(data, default_date):
    """收集本次抓取的全部标题 → [{title, source, section, ts, date, ...}]。

    不再按「是否当天」过滤——是否进入窗口由 _filter_headlines_window 决定。
    ts = 标题级时间（有真实发布时间才给，如 Google News / 东财 / 港股频道），
    无发布时间的标题 ts=""、date=default_date（采集日）；
    中国政府网条目还保留 url/official 字段供政策因子溯源。
    """
    items = []

    def _add(title, source, section, ts_raw, *, date_raw=None, url="", official=False):
        title = (title or "").strip()
        if not title:
            return
        ts = _norm_item_ts(ts_raw)
        # date_raw=None 表示沿用旧来源的采集日兜底；官方政策源显式传入 date，
        # 缺失发布日期时保留空值，避免把未知日期误算为当天政策。
        date = (_norm_item_date(date_raw) if date_raw is not None
                else (ts[:10] if ts else default_date))
        item = {
            "title": title[:200], "source": (source or "").strip(),
            "section": (section or "").strip(), "ts": ts, "date": date,
        }
        if url:
            item["url"] = str(url).strip()
        if official:
            item["official"] = True
        items.append(item)

    google = data.get("全球头条", {}) or {}
    for h in google.get("headlines", []) or []:
        if isinstance(h, dict):
            _add(h.get("title"), h.get("source"), "全球头条", h.get("published_cst"),
                 url=h.get("url", ""))
    em = data.get("东财快讯", {}) or {}
    for h in em.get("headlines", []) or []:
        if isinstance(h, dict):
            _add(h.get("title"), h.get("source") or "东方财富", "东财快讯", h.get("time"),
                 url=h.get("url", ""))
    yt = data.get("港股名家频道", {}) or {}
    for ch in yt.get("channels", []) or []:
        ch_name = ch.get("name", "港股频道")
        for v in ch.get("videos", []) or []:
            _add(v.get("title"), ch_name, "港股名家频道", v.get("published_cst"),
                 url=v.get("url", ""))

    # 港股 36 源池：此前只用于趋势跟踪，2026-10-20 起同时进入 A/H 媒体风险标题池。
    # 仍只纳入采集端已通过「72h + 可验证时区 + 原文主机白名单」三道门的 items；
    # 每条保留真实媒体名、分钟时间与原文链接，不能把聚合栏目名冒充来源。
    hk_news = data.get(HK_NEWS_SOURCE_NAME) or {}
    if isinstance(hk_news, dict):
        for rec in hk_news.get("sources") or []:
            if not isinstance(rec, dict):
                continue
            source_name = str(rec.get("name") or "港股新闻源头")
            for h in rec.get("items") or []:
                if isinstance(h, dict):
                    _add(h.get("title"), source_name, HK_NEWS_SOURCE_NAME,
                         h.get("published_cst"), url=h.get("url", ""))

    # 内地财经媒体源头（2026-10-12 新增，18 家）：标题、来源与原文链接一并进标题池，
    # 供媒体风险 / 新闻情绪因子 / 政策因子 / 策略研判与逐栏 AI 研判共用；窗口仍由
    # _filter_headlines_window 按 ts 统一判定。
    mainland = data.get(MAINLAND_NEWS_SOURCE_NAME) or {}
    if isinstance(mainland, dict):
        for h in mainland.get("headlines") or []:
            if isinstance(h, dict):
                _add(h.get("title"), h.get("source"), MAINLAND_NEWS_SECTION,
                     h.get("published_cst"), date_raw=h.get("date"), url=h.get("url", ""))

    # 中国政府网官方政策单独进入标题存档；政策因子会在同一窗口内对其做矩阵映射。
    # 兼容手工调用传入的旧键名「中国政府网」。
    gov_policy = data.get("国家政策")
    if not isinstance(gov_policy, dict):
        gov_policy = data.get("中国政府网", {}) or {}
    for h in gov_policy.get("headlines", []) or []:
        if isinstance(h, dict):
            # 解析器会显式写入 date；兼容外部传入的只有 published_cst/time
            # 的官方记录，但仍不向缺失日期回填采集日。
            date_raw = (h["date"] if "date" in h
                        else (h.get("published_cst") or h.get("time", "")))
            _add(
                h.get("title"), h.get("source") or "中国政府网", "国家政策",
                h.get("published_cst") or h.get("time", ""),
                date_raw=date_raw, url=h.get("url", ""), official=True,
            )
    return items


def _filter_headlines_window(items, anchor_dt, days=None, hours=None):
    """按窗口过滤标题（保留原顺序）。

    - days（政策）：近 N 个自然日（含锚定日）。按标题 date 字段判断——存档中的
      无时间戳标题以其采集日归档，日归档即落在窗口内；ts 仅作 date 缺省补充；
    - hours（情绪）：近 N 小时，按标题 ts 精确判断；无时间戳的标题只有在
      采集日 == 锚定日时才计入（仅当天抓取可确认属于当天资讯，旧日无时间戳
      标题无法证明落点，宁可排除也不误纳入）。
    """
    anchor_date = anchor_dt.strftime("%Y-%m-%d")
    if days is not None:
        start_date = (anchor_dt - timedelta(days=max(1, int(days)) - 1)).strftime("%Y-%m-%d")
    out = []
    for it in items or []:
        ts = _norm_item_ts(it.get("ts"))
        if ts:
            try:
                dt = datetime.strptime(ts[:16], "%Y-%m-%d %H:%M").replace(tzinfo=CST)
            except (TypeError, ValueError):
                dt = None
        else:
            dt = None
        date = (it.get("date") or "")[:10]
        if not date and dt is not None:
            date = dt.strftime("%Y-%m-%d")
        if days is not None:
            if not (start_date <= date <= anchor_date):
                continue
        if hours is not None:
            if dt is not None:
                if not (anchor_dt - timedelta(hours=hours) <= dt <= anchor_dt):
                    continue
            else:
                if date != anchor_date:
                    continue
        out.append(it)
    return out


def _load_news_corpus(path):
    """读取新闻标题存档（缺失/损坏 → 空存档并告警，不中断日报）。"""
    fresh = {"version": 1, "items": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            corpus = json.load(f)
    except FileNotFoundError:
        print("  ℹ️ 无新闻标题存档，本次仅本次抓取标题可用（窗口随运行次数累积）")
        return fresh
    except (OSError, ValueError) as exc:
        print(f"  ⚠️ 新闻标题存档读取失败（{exc}），本次按空存档处理")
        return fresh
    if not isinstance(corpus, dict) or not isinstance(corpus.get("items"), list):
        print("  ⚠️ 新闻标题存档结构异常，本次按空存档处理")
        return fresh
    corpus.setdefault("version", 1)
    return corpus


def _save_news_corpus(path, corpus):
    """原子落盘新闻标题存档。"""
    corpus["updated_cst"] = _now()
    _atomic_write(path, json.dumps(corpus, ensure_ascii=False, indent=1))
    print(f"  💾 新闻标题存档已更新: {path}（{len(corpus.get('items', []))} 条在窗口内）")


def _merge_news_corpus(corpus, fresh_items):
    """把本次抓取并入存档：按 日期+标题 去重（同日重复运行幂等）。

    官方政策条目即使和媒体标题同名，也会为已有记录补上中国政府网原文链接、
    官方来源与发布日期；这样同一条政策不会因多个资讯源重复计权，同时保留官方溯源。
    """
    items = list(corpus.setdefault("items", []))
    positions = {
        (it.get("date", ""), it.get("title", "")): index
        for index, it in enumerate(items)
        if isinstance(it, dict)
    }
    added = 0
    for it in fresh_items or []:
        if not isinstance(it, dict):
            continue
        key = (it.get("date", ""), it.get("title", ""))
        if not key[1]:
            continue
        if key in positions:
            # 同标题优先采用官方来源；普通来源缺失 URL 时也可补入已有链接，
            # 但不会让媒体信息覆盖已经确认的中国政府网官方记录。
            existing = items[positions[key]]
            is_official = bool(it.get("official"))
            if is_official and not existing.get("official"):
                existing["source"] = it.get("source", existing.get("source", ""))
                existing["section"] = it.get("section", existing.get("section", ""))
                existing["official"] = True
            if it.get("url") and (is_official or not existing.get("url")):
                existing["url"] = it["url"]
            if it.get("ts") and (is_official or not existing.get("ts")):
                existing["ts"] = it["ts"]
            continue
        positions[key] = len(items)
        entry = {"title": it["title"], "source": it.get("source", ""),
                 "section": it.get("section", ""), "ts": it.get("ts", ""),
                 "date": it.get("date", "")}
        if it.get("url"):
            entry["url"] = it["url"]
        if it.get("official"):
            entry["official"] = True
        items.append(entry)
        added += 1
    corpus["items"] = items
    if added:
        print(f"  🗂 新闻标题存档 +{added} 条（累计 {len(items)} 条）")
    return corpus


def _prune_news_corpus(corpus, anchor_date):
    """剪掉早于存档窗口的旧标题（按 date 自然日）。"""
    try:
        base = datetime.strptime(anchor_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return corpus
    cutoff = (base - timedelta(days=max(1, NEWS_HISTORY_KEEP_DAYS) - 1)).strftime("%Y-%m-%d")
    items = [it for it in corpus.get("items", []) if (it.get("date") or "") >= cutoff]
    corpus["items"] = items
    return corpus


def _load_sentiment_history(path):
    """读取情绪历史（缺失/损坏 → 空历史并告警，不中断日报）。"""
    fresh = {"version": 1, "stocks": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            history = json.load(f)
    except FileNotFoundError:
        print("  ℹ️ 无情绪历史文件，本次冷启动（动量/新闻量标样本不足）")
        return fresh
    except (OSError, ValueError) as exc:
        print(f"  ⚠️ 情绪历史读取失败（{exc}），本次按冷启动处理")
        return fresh
    if not isinstance(history, dict) or not isinstance(history.get("stocks"), dict):
        print("  ⚠️ 情绪历史结构异常，本次按冷启动处理")
        return fresh
    history.setdefault("version", 1)
    return history


def _save_sentiment_history(path, history):
    """原子落盘情绪历史。"""
    history["updated_cst"] = _now()
    _atomic_write(path, json.dumps(history, ensure_ascii=False, indent=1))
    print(f"  💾 情绪历史已更新: {path}（{len(history.get('stocks', {}))} 只个股有基线）")


def _update_sentiment_history(history, date_str, universe, today_counts):
    """把今日计数并入历史（同日多次运行按日期键覆盖，保证幂等）。

    universe 中零报道个股记 total=0、score=None：无评分，不计情绪均值，
    计入新闻量基线。每只个股仅保留最近 SENTI_HISTORY_KEEP_DAYS 天。
    """
    stocks = history.setdefault("stocks", {})
    try:
        cutoff = (datetime.strptime(date_str, "%Y%m%d")
                  - timedelta(days=SENTI_HISTORY_KEEP_DAYS)).strftime("%Y%m%d")
    except ValueError:
        cutoff = ""
    for stock in universe:
        entry = stocks.get(stock["key"])
        if not isinstance(entry, dict):
            entry = {"market": stock["market"], "code": stock["code"],
                     "name": stock["name"], "days": {}}
            stocks[stock["key"]] = entry
        entry["market"] = stock["market"]
        entry["code"] = stock["code"]
        entry["name"] = stock["name"]
        if not isinstance(entry.get("days"), dict):
            entry["days"] = {}
        counts = today_counts.get(stock["key"]) or {}
        pos = counts.get("pos", 0) or 0
        neu = counts.get("neu", 0) or 0
        neg = counts.get("neg", 0) or 0
        total = counts.get("total", 0) or 0
        entry["days"][date_str] = {
            "pos": pos, "neu": neu, "neg": neg, "total": total,
            "score": round((pos - neg) / total, 4) if total else None,
        }
    for key in list(stocks):
        entry = stocks[key]
        if not isinstance(entry, dict) or not isinstance(entry.get("days"), dict):
            del stocks[key]
            continue
        for day in [d for d in entry["days"] if d < cutoff]:
            del entry["days"][day]
        if not entry["days"]:
            del stocks[key]
    return history


def _sentiment_momentum(day_scores):
    """情绪动量：近3个有评分日均值 − 近20个有评分日均值。

    day_scores: [(date, score)] 降序，首位为今日（调用方保证仅含已评分日）。
    样本不足（短期<2 或 长期<5）时 enough=False，渲染侧明确标注。
    """
    short = [s for _, s in day_scores[:SENTI_MOM_SHORT_N]]
    long = [s for _, s in day_scores[:SENTI_MOM_LONG_N]]
    short_n, long_n = len(short), len(long)
    if short_n < SENTI_MOM_MIN_SHORT or long_n < SENTI_MOM_MIN_LONG:
        return {"enough": False, "short_n": short_n, "long_n": long_n,
                "need": f"{SENTI_MOM_MIN_SHORT}/{SENTI_MOM_MIN_LONG}"}
    short_mean = sum(short) / short_n
    long_mean = sum(long) / long_n
    value = short_mean - long_mean
    label = "加速转暖" if value >= 0.15 else ("加速转冷" if value <= -0.15 else "平稳")
    return {"enough": True, "value": value, "short_mean": short_mean,
            "long_mean": long_mean, "short_n": short_n, "long_n": long_n,
            "label": label}


def _sentiment_volume(today_total, prior_totals):
    """异常新闻量：今日条数 vs 历史均值±σ（z 值；>均值+2σ 标异常）。

    prior_totals: 今日之前每日条数（含零报道日）。历史<5 天时
    enough=False，渲染侧明确标注。
    """
    prior_totals = [t for t in prior_totals if type(t) in (int, float)]
    n = len(prior_totals)
    if n < SENTI_VOL_MIN_DAYS:
        return {"enough": False, "n": n, "need": SENTI_VOL_MIN_DAYS,
                "today": today_total}
    mean = sum(prior_totals) / n
    var = sum((t - mean) ** 2 for t in prior_totals) / (n - 1)
    std = var ** 0.5
    if std <= 1e-9:
        z = 0.0 if today_total == mean else (9.99 if today_total > mean else -9.99)
        z_display = "σ=0"
    else:
        z = (today_total - mean) / std
        z_display = f"{z:+.1f}"
    abnormal = today_total > mean + 2 * std
    label = "异常放量" if abnormal else ("交投偏热" if z >= 1 else "正常")
    return {"enough": True, "today": today_total, "mean": mean, "std": std,
            "z": z, "z_display": z_display, "abnormal": abnormal, "n": n,
            "label": label}


def build_news_sentiment(data, date_str, history=None, display_n=SENTI_DISPLAY_N,
                         news_corpus=None):
    """构建新闻情绪结果（渲染与历史落盘共用同一口径）。

    - 标题窗口：近 SENTI_WINDOW_HOURS=72 小时（news_corpus 缺省时退化为只用
      本次抓取标题，仍按 72h 过滤）；
    - 个股归因 / 评分 / DNS 展示：基于窗口内全部标题；
    - MOM / ANV 与历史落盘：按自然日口径——「今日」= 窗口内标题中日期等于
      报告日的桶（today_counts 只含当日，供 sentiment_history 按日键写历史，
      与历史基线同量纲）。

    history: _load_sentiment_history 读到的跨日基线（可为 None/{}，冷启动时
    动量/新闻量标样本不足）。返回 available/stocks/universe/today_counts 等。
    """
    history = history if isinstance(history, dict) else {}
    past = history.get("stocks") or {}
    universe = _extract_stock_universe(data.get("热门榜单", {}) or {})
    anchor_dt = _factor_anchor_dt(date_str)
    anchor_date = anchor_dt.strftime("%Y-%m-%d")
    try:
        today_iso = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        today_iso = anchor_date
    if isinstance(news_corpus, dict) and isinstance(news_corpus.get("items"), list):
        raw = news_corpus["items"]
    else:
        raw = _collect_headline_items(data, anchor_date)
    headlines = _filter_headlines_window(raw, anchor_dt, hours=SENTI_WINDOW_HOURS)
    per_stock = {}
    unattributed = 0
    unattributed_headlines = []  # 未归因标题（用于"热门话题"子栏目）
    for order, head in enumerate(headlines):
        targets = _attribute_headline(head["title"], universe)
        scored = _score_headline_sentiment(head["title"])
        if not targets:
            unattributed += 1
            unattributed_headlines.append({
                "title": head["title"], "source": head["source"],
                "section": head["section"], "s": scored["s"],
                "pos_hits": scored["pos"], "neg_hits": scored["neg"],
                "date": (head.get("date") or "")[:10],
                "old": (head.get("date") or "")[:10] != today_iso and bool(head.get("date")),
                "order": order,
            })
            continue
        is_today_item = (head.get("date") or "")[:10] == today_iso
        for stock in targets:
            tag = stock.get("tag", "name")
            slot = per_stock.setdefault(stock["key"], {
                "info": stock, "pos": 0, "neu": 0, "neg": 0,
                "day_pos": 0, "day_neu": 0, "day_neg": 0, "headlines": [],
                "tags": set()})
            slot["tags"].add(tag)
            if scored["s"] > 0:
                slot["pos"] += 1
                if is_today_item:
                    slot["day_pos"] += 1
            elif scored["s"] < 0:
                slot["neg"] += 1
                if is_today_item:
                    slot["day_neg"] += 1
            else:
                slot["neu"] += 1
                if is_today_item:
                    slot["day_neu"] += 1
            slot["headlines"].append({
                "title": head["title"], "source": head["source"],
                "section": head["section"], "s": scored["s"],
                "pos_hits": scored["pos"], "neg_hits": scored["neg"],
                "date": (head.get("date") or "")[:10],
                "old": is_today_item is False and bool(head.get("date")),
                "order": order, "tag": tag,
            })
    all_stocks = []
    today_counts = {}
    for key, slot in per_stock.items():
        total = slot["pos"] + slot["neu"] + slot["neg"]
        if total < 1:
            continue
        score = (slot["pos"] - slot["neg"]) / total
        day_total = slot["day_pos"] + slot["day_neu"] + slot["day_neg"]
        if day_total >= 1:
            today_counts[key] = {"pos": slot["day_pos"], "neu": slot["day_neu"],
                                 "neg": slot["day_neg"], "total": day_total}
        days = (past.get(key) or {}).get("days", {}) or {}
        prior = sorted(((day, val) for day, val in days.items() if day < date_str),
                       reverse=True)
        scored_days = [(day, val["score"]) for day, val in prior
                       if isinstance(val, dict) and type(val.get("score")) in (int, float)]
        today_score = (round((slot["day_pos"] - slot["day_neg"]) / day_total, 4)
                       if day_total >= 1 else None)
        day_scores = ([(date_str, today_score)] if today_score is not None else []) + scored_days
        momentum = _sentiment_momentum(day_scores)
        raw_totals = [val.get("total", 0) for _, val in prior[:SENTI_VOL_WINDOW_N]
                      if isinstance(val, dict)]
        volume = _sentiment_volume(day_total, raw_totals)
        slot["headlines"].sort(key=lambda h: (-abs(h["s"]), h["order"]))
        info = slot["info"]
        tags = slot.get("tags", set())
        best_tag = "name" if "name" in tags else ("alias" if "alias" in tags else "sector")
        all_stocks.append({
            "market": info["market"], "code": info["code"], "name": info["name"],
            "key": info["key"],
            "total": total, "pos": slot["pos"], "neu": slot["neu"], "neg": slot["neg"],
            "score": score,
            "label": "偏多" if score > 0.2 else ("偏空" if score < -0.2 else "中性"),
            "momentum": momentum, "volume": volume,
            "headlines": slot["headlines"],
            "best_tag": best_tag,
        })
    all_stocks.sort(key=lambda s: (-s["total"], -abs(s["score"]), s["name"]))
    by_market = _build_senti_by_market(data, all_stocks)
    # 未归因标题情绪关键词频率（不重复展示标题本身，避免与正文重复）
    unattr_keyword_freq = {}
    for h in unattributed_headlines:
        for w in (h.get("pos_hits") or []):
            unattr_keyword_freq[w] = unattr_keyword_freq.get(w, 0) + 1
        for w in (h.get("neg_hits") or []):
            unattr_keyword_freq[w] = unattr_keyword_freq.get(w, 0) + 1
    unattr_pos_n = sum(1 for h in unattributed_headlines if h.get("s") and h["s"] > 0)
    unattr_neg_n = sum(1 for h in unattributed_headlines if h.get("s") and h["s"] < 0)
    unattr_neu_n = sum(1 for h in unattributed_headlines if h.get("s") == 0)
    # 跨市场情绪总览
    market_summary = _build_market_sentiment_summary(all_stocks, by_market)
    return {
        "available": bool(universe),
        "date": date_str,
        "stocks": all_stocks[:display_n],
        "by_market": by_market,
        "total_matched": len(all_stocks),
        "universe_n": len(universe),
        "scored_headlines": len(headlines) - unattributed,
        "unattributed_n": unattributed,
        "unattributed_pos_n": unattr_pos_n,
        "unattributed_neg_n": unattr_neg_n,
        "unattributed_neu_n": unattr_neu_n,
        "unattributed_keywords": sorted(unattr_keyword_freq.items(),
                                        key=lambda x: -x[1])[:10],
        "window_hours": SENTI_WINDOW_HOURS,
        "window_text": f"{anchor_dt:%m-%d %H:%M}",
        "corpus_n": len(headlines),
        "universe": universe,
        "today_counts": today_counts,
        "market_summary": market_summary,
    }


def _build_market_sentiment_summary(all_stocks, by_market):
    """构建跨市场情绪总览（渲染用）：整体 DNS、各市场情绪、最热/最冷个股。"""
    if not all_stocks:
        return {"available": False}
    total_pos = sum(s["pos"] for s in all_stocks)
    total_neg = sum(s["neg"] for s in all_stocks)
    total_neu = sum(s["neu"] for s in all_stocks)
    total_n = total_pos + total_neg + total_neu
    overall_dns = (total_pos - total_neg) / total_n if total_n else 0
    overall_label = "偏多" if overall_dns > 0.2 else ("偏空" if overall_dns < -0.2 else "中性")
    # 各市场情绪
    market_dns = {}
    for mb in by_market:
        mkt = mb["market"]
        mkt_stocks = [s for s in mb.get("stocks") or [] if s.get("matched")]
        if not mkt_stocks:
            market_dns[mkt] = {"matched": 0, "dns": None, "label": "暂无"}
            continue
        mkt_pos = sum(s["pos"] for s in mkt_stocks)
        mkt_neg = sum(s["neg"] for s in mkt_stocks)
        mkt_neu = sum(s["neu"] for s in mkt_stocks)
        mkt_n = mkt_pos + mkt_neg + mkt_neu
        mkt_dns = (mkt_pos - mkt_neg) / mkt_n if mkt_n else 0
        mkt_label = "偏多" if mkt_dns > 0.2 else ("偏空" if mkt_dns < -0.2 else "中性")
        market_dns[mkt] = {"matched": len(mkt_stocks), "total": mkt_n,
                           "dns": round(mkt_dns, 2), "label": mkt_label,
                           "pos": mkt_pos, "neg": mkt_neg, "neu": mkt_neu}
    # 最热 / 最冷个股（仅已匹配的）
    matched = [s for s in all_stocks if s["total"] >= 1]
    hottest = max(matched, key=lambda s: s["score"]) if matched else None
    coldest = min(matched, key=lambda s: s["score"]) if matched else None
    most_covered = max(matched, key=lambda s: s["total"]) if matched else None
    return {
        "available": True,
        "overall_dns": round(overall_dns, 2),
        "overall_label": overall_label,
        "total_n": total_n,
        "total_pos": total_pos,
        "total_neg": total_neg,
        "total_neu": total_neu,
        "market_dns": market_dns,
        "hottest": hottest,
        "coldest": coldest,
        "most_covered": most_covered,
    }


# ============================================================
# 媒体舆情风险点（A股＋港股 · 结构化事件预警）
# ------------------------------------------------------------
# 与新闻情绪的边界：新闻情绪回答「标题偏暖还是偏冷」；本栏回答「是否出现了
# 立案 / 审计非标 / 股权冻结 / 断供等具体风险事实，或可靠的新闻量异常」。风险指数 0~100 是用于排序的
# 确定性规则分，不是发生概率或涨跌概率；单一标题不会直接生成自动止损指令。
# ============================================================
def _media_risk_sentiment_scores(headlines, universe):
    """复用新闻情绪词表，为风险 Agent Schema 计算每只 A/H 标的的 [-1, 1] 标题分。"""
    slots = {}
    for item in headlines or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        risk_event = _media_risk.classify_title(title)
        if not risk_event and _media_risk._is_noise_title(title):
            continue
        scored = _score_headline_sentiment(title)
        value = float(scored.get("s") or 0)
        if risk_event and risk_event.get("disputed") and value < 0:
            value = 0.0
        elif risk_event and not risk_event.get("disputed") and value == 0:
            value = -1.0
        for target in _attribute_headline(title, universe) or []:
            if target.get("market") not in ("A股", "港股"):
                continue
            slot = slots.setdefault(target.get("key"), {"sum": 0.0, "n": 0,
                                                         "negative_n": 0, "positive_n": 0})
            slot["sum"] += value
            slot["n"] += 1
            slot["negative_n"] += int(value < 0)
            slot["positive_n"] += int(value > 0)
    return {
        key: {
            "score": (slot["sum"] / slot["n"]) if slot["n"] else None,
            "sample_n": slot["n"],
            "negative_n": slot["negative_n"],
            "positive_n": slot["positive_n"],
            "method": "existing_headline_sentiment_dictionary_with_risk_event_floor",
        }
        for key, slot in slots.items()
    }


def build_media_risk(data, date_str, history=None, news_corpus=None):
    """构建 A/H 成交活跃标的的媒体风险事件、热度异常与分级处置。

    标题严格复用新闻情绪的 72 小时时间窗：分钟时间晚于报告锚点的条目被排除；
    只有日期、没有分钟时间的当日条目可以进入日级观察，但渲染时明确标注
    「日级时间，禁用于日内回测」。美股不进入首期范围。

    2026-10-21 起即使热门榜单暂缺、或窗口内未检出风险，也返回可渲染的诊断
    结果（available=False 但带 headline_n / universe_n / window_text 等）与
    明确 reason，供占位渲染“监控中”而不静默消失；调用方不再以 available 为
    唯一渲染门禁。
    """
    anchor_dt = _factor_anchor_dt(date_str)
    anchor_date = anchor_dt.strftime("%Y-%m-%d")
    if isinstance(news_corpus, dict) and isinstance(news_corpus.get("items"), list):
        raw = news_corpus["items"]
    else:
        raw = _collect_headline_items(data or {}, anchor_date)
    headlines = _filter_headlines_window(raw, anchor_dt, hours=_media_risk.WINDOW_HOURS)
    # 预计算通用诊断（无论是否能建 universe 都需要，供占位渲染）
    headline_n = len(headlines)
    precise_ts_n = sum(1 for item in headlines if str(item.get("ts") or "").strip())
    # 热门榜单主宇宙
    universe = [stock for stock in _extract_stock_universe(
        (data or {}).get("热门榜单", {}) or {})
        if stock.get("market") in ("A股", "港股")]
    fallback_used = False
    fallback_reason = ""
    if not universe:
        # 热门榜单暂缺时，尝试用 sentiment_history 的已建档个股作兜底，避免
        # “热门榜一挂，风险监控整栏消失”的误判；兜底失败则仍返回诊断占位。
        if isinstance(history, dict) and isinstance(history.get("stocks"), dict):
            for key, val in history["stocks"].items():
                if not isinstance(val, dict):
                    continue
                market = str(val.get("market") or "")
                if market not in ("A股", "港股"):
                    continue
                code = str(val.get("code") or "").strip()
                name = str(val.get("name") or "").strip()
                if not name and not key:
                    continue
                # key 形如 "A股:600000" / "港股:00700"
                derived_key = key if ":" in str(key) else f"{market}:{code or name}"
                if not derived_key or ":" not in derived_key:
                    continue
                universe.append({
                    "market": market,
                    "code": code or derived_key.split(":", 1)[1],
                    "name": name or derived_key.split(":", 1)[1],
                    "key": derived_key,
                })
            if universe:
                # 去重并按名长排序，与 _extract_stock_universe 保持一致口径
                seen = set()
                deduped = []
                for item in universe:
                    key = item.get("key")
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(item)
                deduped.sort(key=lambda u: len(u.get("name") or ""), reverse=True)
                universe = deduped
                fallback_used = True
                fallback_reason = "热门榜单暂缺，已用近30日情绪基线个股兜底"
    if not universe:
        # 仍无法建立监控范围：返回可渲染的诊断占位，而非静默缺席
        reason = "热门榜单暂缺且情绪基线无可用个股，监控范围暂时为空"
        return {
            "available": False,
            "reason": reason,
            "scope": "A股＋港股成交活跃标的",
            "universe_n": 0,
            "stocks": [],
            "window_hours": int(_media_risk.WINDOW_HOURS),
            "window_text": f"{anchor_dt:%m-%d %H:%M}",
            "headline_n": headline_n,
            "precise_ts_n": precise_ts_n,
            "noise_filtered_n": 0,
            "level_counts": {},
            "top_categories": [],
            "risk_stock_n": 0,
            "risk_event_n": 0,
            "abnormal_attention_n": 0,
            "agent_schema_version": _media_risk.AGENT_SCHEMA_VERSION,
            "agent_records": [],
            "fallback_used": False,
        }
    prices = {}
    markets = (((data or {}).get("热门榜单") or {}).get("markets") or {})
    for market in ("A股", "港股"):
        for stock in ((markets.get(market) or {}).get("stocks") or []):
            code = str(stock.get("code") or "").strip()
            name = str(stock.get("name") or "").strip()
            if name:
                prices[f"{market}:{code or name}"] = stock.get("change_pct")
    result = _media_risk.analyze(
        headlines, universe, _attribute_headline,
        history if isinstance(history, dict) else {}, date_str,
        prices=prices,
        sentiment_scores=_media_risk_sentiment_scores(headlines, universe),
        as_of=anchor_dt.strftime("%Y-%m-%d %H:%M:%S"),
        window_hours=_media_risk.WINDOW_HOURS,
    )
    result["window_text"] = f"{anchor_dt:%m-%d %H:%M}"
    result["window_hours"] = int(_media_risk.WINDOW_HOURS)
    result["fallback_used"] = fallback_used
    if fallback_reason:
        result["fallback_reason"] = fallback_reason
    # available=False 时调用方仍需 headline_n 等诊断，已由 analyze 给出；补齐 window_text
    if not result.get("available"):
        result.setdefault("reason", "本期72小时窗口内未检出具体风险事件或可靠异常关注，系统持续监控中")
        result.setdefault("headline_n", headline_n)
        result.setdefault("precise_ts_n", precise_ts_n)
        result["window_text"] = f"{anchor_dt:%m-%d %H:%M}"
    return result


def _media_risk_href(value):
    """风险证据原文链接的最后一道输出校验（只接受无凭据的 HTTPS URL）。"""
    raw = str(value or "").strip()
    if not raw or any(c.isspace() or c in '<>\\"\'' for c in raw):
        return ""
    try:
        parsed = urlparse(raw)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in (None, 443)):
            return ""
    except ValueError:
        return ""
    return raw


def _media_risk_color(stock, kit):
    key = str(((stock or {}).get("level") or {}).get("key") or "")
    if key in ("red", "orange"):
        return kit.bad_color
    return kit.warn_color


def _media_risk_title_html(event, color):
    title = _esc(str((event or {}).get("title") or ""))
    href = _media_risk_href((event or {}).get("url"))
    if not href:
        return title
    return (f'<a href="{_esc(href)}" style="color:{color};font-weight:700;'
            f'text-decoration:none;">{title}</a>')


def _media_risk_attention_text(stock):
    attention = (stock or {}).get("attention") or {}
    if attention.get("enough"):
        multiple = attention.get("multiple")
        multiple_text = (f'{float(multiple):.1f}×'
                         if type(multiple) in (int, float) else "均值为0，倍数不可定义")
        return (f'今日 {int(attention.get("today") or 0)} 条 vs '
                f'近 {int(attention.get("n") or 0)} 日均 {float(attention.get("mean") or 0):.1f} 条 · '
                f'z={attention.get("z_display") or "—"} · {multiple_text} · '
                f'{attention.get("label") or "正常"}')
    return (f'今日 {int(attention.get("today") or 0)} 条 · 历史 n={int(attention.get("n") or 0)}'
            f'（需≥{int(attention.get("need") or _media_risk.MIN_BASELINE_DAYS)}日，暂不判异常）')


def _media_risk_block(res, kit):
    """五套主题共用的媒体风险栏目正文（只用 kit 原语，保持微信全内联表格）。

    2026-10-21 起有风险时展示详细预警；无风险或监控范围暂时为空时展示
    “监控中”占位（headline_n / universe_n / 诊断原因），不静默消失。
    """
    if not isinstance(res, dict):
        return ""
    # 有可用预警：走原有详细渲染
    if res.get("available") and res.get("stocks"):
        levels = res.get("level_counts") or {}
        level_line = (f'红 {int(levels.get("red") or 0)} · 橙 {int(levels.get("orange") or 0)} · '
                      f'黄 {int(levels.get("yellow") or 0)} · 蓝 {int(levels.get("blue") or 0)}')
        categories = "、".join(f"{name}×{count}" for name, count in res.get("top_categories") or []) or "—"
        head_pairs = [
            ("监控范围", f'{_esc(str(res.get("scope") or "A股＋港股"))} · {int(res.get("universe_n") or 0)} 只'),
            ("风险/异常命中", f'{int(res.get("risk_stock_n") or 0)} 只 · '
                              f'具体风险 {int(res.get("risk_event_n") or 0)} 个 · '
                              f'异常关注 {int(res.get("abnormal_attention_n") or 0)} 只 · {level_line}'),
            ("事件类型", _esc(categories)),
            ("时间窗口", f'近 {int(res.get("window_hours") or _media_risk.WINDOW_HOURS)} 小时 · 截至 {_esc(str(res.get("window_text") or "—"))}'),
        ]
        if not PLAIN():
            headline_n = int(res.get("headline_n") or 0)
            head_pairs.extend([
                ("时间戳覆盖", f'{int(res.get("precise_ts_n") or 0)}/{headline_n} 条标题有分钟级发布时间'),
                ("噪音剔除", f'{int(res.get("noise_filtered_n") or 0)} 条明确营销/导流标题'),
                ("Agent Schema", _esc(str(res.get("agent_schema_version") or "—")) + " · JSON 可解析"),
                ("风险指数", "0–100 规则排序分；JSON 的 0–1 值仅为归一化序数（不是发生概率、不是涨跌概率）"),
            ])
        if res.get("fallback_used"):
            head_pairs.append(("监控兜底", _esc(str(res.get("fallback_reason") or "已用情绪基线兜底"))))
        out = [kit.kv(head_pairs)]
    else:
        # 无风险 / 监控范围为空：渲染“监控中”占位，而非空白
        reason = str(res.get("reason") or "本期72小时窗口内未检出具体风险事件或可靠异常关注，系统持续监控中")
        head_pairs = [
            ("监控范围", f'{_esc(str(res.get("scope") or "A股＋港股成交活跃标的"))} · {int(res.get("universe_n") or 0)} 只'),
            ("时间窗口", f'近 {int(res.get("window_hours") or _media_risk.WINDOW_HOURS)} 小时 · 截至 {_esc(str(res.get("window_text") or "—"))}'),
            ("标题覆盖", f'{int(res.get("headline_n") or 0)} 条标题 · {int(res.get("precise_ts_n") or 0)} 条有分钟级时间 · {int(res.get("noise_filtered_n") or 0)} 条营销噪音已剔除'),
            ("监控状态", _esc(reason)),
        ]
        if res.get("fallback_used"):
            head_pairs.append(("监控兜底", _esc(str(res.get("fallback_reason") or "已用情绪基线兜底"))))
        if not PLAIN():
            head_pairs.extend([
                ("Agent Schema", _esc(str(res.get("agent_schema_version") or _media_risk.AGENT_SCHEMA_VERSION)) + " · JSON 可解析"),
                ("风险指数", "0–100 规则排序分；JSON 的 0–1 值仅为归一化序数（不是发生概率、不是涨跌概率）"),
            ])
        out = [kit.kv(head_pairs)]
        # 入门版也给一行明确提示，避免“栏目消失”的误判
        out.append(kit.note(
            "说明：本栏目为 A/H 成交活跃标的的 72 小时标题事件实时筛查（词表×来源权威×归因强度＋跨源确认＋近30日新闻量异常）；"
            "当前窗口内未触发红/橙/黄预警，不代表未来无风险，系统持续监控中。标题是线索而非事实定论，需回看监管/公司原文；"
            "风险指数仅用于排序与风控观察，不触发自动交易。"
        ))
        # 占位态提前返回，不再走标的明细渲染
        if not PLAIN():
            out.append(kit.note(
                "口径：具体风险事件词表 × 来源权威度 × 公司归因强度，叠加跨源确认与近30日新闻量异常；"
                "无事件词时仅在基线≥5日、（z≥2 或达到历史均值3倍）且当日≥3条时输出异常关注，"
                "并明确不代表负面事实。营销/导流噪音先剔除；行业链映射与澄清语境均降权。"
                "标题是线索而非事实定论，需回看监管/公司原文；"
                "下游 JSON 给出时态、标准动作与可审计判定摘要，不输出隐藏思维链。"
                "风险指数只用于排序与风控观察，不是概率，不触发自动交易。"))
        return "".join(out)

    cat_rows = []
    for name, count in (res.get("top_categories") or []):
        cat_rows.append([_esc(str(name)), str(int(count)), "标题信号归因次数"])
    if cat_rows and not PLAIN():
        out.append(kit.sub("风险类型分布") + kit.table(
            ["风险类型", "命中", "口径"], cat_rows,
            aligns=("left", "right", "left")))

    stocks = list(res.get("stocks") or [])
    stock_limit = LITE("media_risk_stocks")
    shown_stocks = stocks[:stock_limit] if stock_limit else stocks
    for stock in shown_stocks:
        level = stock.get("level") or {}
        color = _media_risk_color(stock, kit)
        name = _esc(str(stock.get("name") or ""))
        code = _esc(str(stock.get("code") or ""))
        market = _esc(str(stock.get("market") or ""))
        label = _esc(str(level.get("label") or "观察"))
        out.append(kit.sub(
            f'! {name} {code} · {market} · {label} · 风险指数 {int(stock.get("risk_index") or 0)}/100'))
        payload = stock.get("agent_payload") or {}
        metrics = payload.get("sentiment_metrics") or {}
        recommendation = payload.get("actionable_recommendation") or {}
        status_counts = stock.get("status_counts") or {}
        status_text = " · ".join(
            f"{key} {int(status_counts.get(key) or 0)}"
            for key in ("Current", "Emerging", "Historical") if status_counts.get(key)) or "—"
        sentiment_value = metrics.get("sentiment_score")
        sentiment_text = (f'{float(sentiment_value):+.2f}'
                          if type(sentiment_value) in (int, float) else "样本不足")
        pairs = [
            ("核心触发", _esc("、".join(stock.get("top_hits") or []) or "—")),
            ("事件时态", _esc(status_text)),
            ("标准动作", f'<b style="color:{color};">{_esc(str(recommendation.get("action") or "Watch"))}</b>'),
            ("证据覆盖", f'{int(stock.get("event_n") or 0)} 条归因 · '
                         f'{int(stock.get("source_n") or 0)} 个来源 · '
                         f'{int(stock.get("category_n") or 0)} 类信号'),
            ("舆情热度", _esc(_media_risk_attention_text(stock))),
            ("情绪/传播", _esc(
                f'{sentiment_text} · {metrics.get("media_authority_level") or "Unknown"} · '
                f'{metrics.get("propagation_stage") or "Single_Source"}'
                + (" · 空头背离" if metrics.get("bearish_divergence") else ""))),
        ]
        change = stock.get("change_pct")
        if type(change) in (int, float):
            pairs.append(("价格交叉核对",
                          f'{float(change):+.2f}% · {_esc(str(stock.get("divergence") or "—"))}'))
        flags = []
        if stock.get("attention_only"):
            flags.append("仅新闻量异常，未检出具体负面事件；最高黄色关注")
        if stock.get("sector_only"):
            flags.append("仅行业链弱归因，等级封顶黄色关注")
        if stock.get("disputed_only"):
            flags.append("全部证据处于澄清/否认/解除语境，已降权")
        if stock.get("commentary_only"):
            flags.append("仅评论/社区来源，主要视为传播与情绪风险，等级封顶黄色关注")
        if stock.get("historical_only"):
            flags.append("仅 Historical 历史事件，风险指数封顶49")
        elif stock.get("emerging_only") and not stock.get("attention_only"):
            flags.append("仅 Emerging 待确认事件，不进入 Level 4")
        if flags:
            pairs.append(("归因护栏", _esc("；".join(flags))))
        logic = list(payload.get("risk_logic_summary") or [])
        if logic:
            pairs.append(("判定依据", _esc("；".join(logic[:3] if PLAIN() else logic))))
        pairs.append(("处置建议", f'<b style="color:{color};">{_esc(str(stock.get("action") or ""))}</b>'))
        out.append(kit.kv(pairs))

        events = list(stock.get("events") or [])
        evidence_limit = LITE("media_risk_evidence")
        shown_events = events[:evidence_limit] if evidence_limit else events
        for event in shown_events:
            ts = str(event.get("ts") or "")
            if ts:
                when = ts
            else:
                when = f'{event.get("date") or "日期未知"}（日级时间，禁用于日内回测）'
            signal_label = ("热度异常证据" if event.get("signal_type") == "attention" else
                            f'{event.get("severity_label") or "关注"}风险')
            bits = [
                "/".join(str(c) for c in event.get("categories") or []),
                signal_label,
                f'时态：{event.get("status") or "Current"}',
                str(event.get("authority_tier") or ""),
                str(event.get("source") or ""),
                when,
                f'归因：{event.get("attribution_label") or "—"}',
            ]
            if event.get("hits"):
                bits.append("命中：" + "/".join(str(x) for x in event["hits"][:5]))
            if event.get("disputed"):
                bits.append("澄清/否认/解除语境，已降权")
            out.append(kit.item_row(
                "!", _media_risk_title_html(event, color),
                _esc(" · ".join(bit for bit in bits if bit))))
        hidden_events = max(0, int(stock.get("event_n") or 0) - len(shown_events))
        if hidden_events and not PLAIN():
            out.append(kit.note(f"其余 {hidden_events} 条证据已计入风险指数，正文按影响分仅展开前 {len(shown_events)} 条。"))

    hidden_stocks = max(0, len(stocks) - len(shown_stocks))
    if hidden_stocks and not PLAIN():
        out.append(kit.note(f"另 {hidden_stocks} 只风险标的已计入汇总；默认版按预警等级与风险指数只列前 {len(shown_stocks)} 只。"))
    if not PLAIN():
        out.append(kit.note(
            "口径：具体风险事件词表 × 来源权威度 × 公司归因强度，叠加跨源确认与近30日新闻量异常；"
            "无事件词时仅在基线≥5日、（z≥2 或达到历史均值3倍）且当日≥3条时输出异常关注，"
            "并明确不代表负面事实。营销/导流噪音先剔除；行业链映射与澄清语境均降权。"
            "标题是线索而非事实定论，需回看监管/公司原文；"
            "下游 JSON 给出时态、标准动作与可审计判定摘要，不输出隐藏思维链。"
            "风险指数只用于排序与风控观察，不是概率，不触发自动交易。"))
    return "".join(out)


SENTI_MARKET_ORDER = ("A股", "港股", "美股")


def _build_senti_stock_comment(s):
    """按确定性规则生成单只"AI 新闻情绪评分 + 总结评论 + 原因"（2026-09-09 丰富版）。

    只使用窗口内真实命中的标题数与词表命中词；无新闻就不评分不评级，
    绝不凭消息面或价格涨跌反推新闻情绪。
    """
    if not s.get("matched"):
        return ("近72小时无相关点名新闻，AI 暂不评分。",
                "窗口内标题未通过精确名/别名代码/行业概念归因到该股，无新闻证据时不评论其新闻情绪。")
    score = round(float(s.get("score") or 0.0), 2)
    total = int(s.get("total") or 0)
    pos = int(s.get("pos") or 0)
    neu = int(s.get("neu") or 0)
    neg = int(s.get("neg") or 0)
    label = s.get("label") or "中性"
    # 归因类型统计
    tag_counts = {}
    for h in s.get("headlines", []) or []:
        t = h.get("tag", "name")
        tag_counts[t] = tag_counts.get(t, 0) + 1
    tag_labels = {"name": "精确名", "alias": "别名/代码", "sector": "行业概念"}
    tag_order = ("name", "alias", "sector")
    tag_parts = [f'{tag_labels.get(t, t)}{n}条' for t, n in
                 sorted(tag_counts.items(), key=lambda x: tag_order.index(x[0])
                        if x[0] in tag_order else 99)]
    tag_note = f"（归因：{' / '.join(tag_parts)}）" if tag_parts else ""
    comment = (f"AI情绪分 {score:+.2f}（{label}）：近72小时命中 {total} 条相关新闻{tag_note}，"
               f"正面 {pos} 条 / 中性 {neu} 条 / 负面 {neg} 条。")
    parts = []
    hits = []
    for h in s.get("headlines", []) or []:
        hits.extend(h.get("pos_hits") or [])
        hits.extend(h.get("neg_hits") or [])
    hits = list(dict.fromkeys(hits))[:5]
    if hits:
        parts.append("命中情绪词：" + "、".join(hits))
    pos_heads = [h["title"] for h in s.get("headlines") if h.get("s") and h["s"] > 0]
    neg_heads = [h["title"] for h in s.get("headlines") if h.get("s") and h["s"] < 0]
    neu_heads = [h["title"] for h in s.get("headlines") if h.get("s") == 0]
    if pos_heads:
        parts.append("正面主要来自「" + pos_heads[0][:40] + "」" +
                     (f"等 {len(pos_heads)} 条" if len(pos_heads) > 1 else ""))
    if neg_heads:
        parts.append("负面主要来自「" + neg_heads[0][:40] + "」" +
                     (f"等 {len(neg_heads)} 条" if len(neg_heads) > 1 else ""))
    if neu_heads and not pos_heads and not neg_heads:
        parts.append("中性报道为主：「" + neu_heads[0][:40] + "」" +
                     (f"等 {len(neu_heads)} 条" if len(neu_heads) > 1 else ""))
    # 来源分布
    source_counts = {}
    for h in s.get("headlines", []) or []:
        sec = h.get("section", "")
        source_counts[sec] = source_counts.get(sec, 0) + 1
    if source_counts:
        src_parts = [f'{sec}{n}条' for sec, n in
                     sorted(source_counts.items(), key=lambda x: -x[1])]
        parts.append("来源：" + "、".join(src_parts))
    mom = s.get("momentum") or {}
    if mom.get("enough"):
        parts.append(f"情绪动量 {float(mom['value']):+.2f}（{mom['label']}）")
    else:
        parts.append("情绪动量样本不足")
    vol = s.get("volume") or {}
    if vol.get("enough"):
        parts.append(f"今日新闻量 {vol['today']} 条（{vol['label']}，z={vol['z_display']}）")
    else:
        parts.append("新闻量历史样本不足")
    reason = "；".join(parts) + "。" if parts else "基于窗口内命中标题的词表净情绪合成。"
    return comment, reason


def _build_senti_by_market(data, all_stocks):
    """把评过分 / 未评分的个股按「A股·港股·美股 成交前五」分组，补上总结评论与原因。

    榜单顺序优先；榜单缺失某市场时该市场不出现；所有上榜个股都会展示，
    包括窗口内没有相关新闻的股票（matched=False，明确说明无法评分的原因）。
    """
    hot = (data or {}).get("热门榜单", {}) or {}
    by_key = {(s.get("market"), s.get("code") or s.get("name")): s for s in all_stocks}
    result = []
    for market in SENTI_MARKET_ORDER:
        payload = (hot.get("markets") or {}).get(market) or {}
        rows = (payload.get("stocks") or [])[:HOT_STOCK_TOP_N]
        if not rows:
            continue
        market_stocks = []
        for it in rows:
            code = str(it.get("code") or "")
            name = (it.get("name") or "").strip()
            if not name:
                continue
            matched = by_key.get((market, code or name))
            if matched:
                item = dict(matched)
                item["matched"] = True
            else:
                item = {
                    "market": market, "code": code, "name": name,
                    "key": f"{market}:{code or name}",
                    "matched": False, "total": 0, "pos": 0, "neu": 0, "neg": 0,
                    "score": None, "label": "暂无评分",
                    "momentum": {"enough": False}, "volume": {"enough": False},
                    "headlines": [],
                }
            item["comment"], item["reason"] = _build_senti_stock_comment(item)
            market_stocks.append(item)
        result.append({"market": market, "stocks": market_stocks})
    return result


def _senti_factor_lines(s):
    """个股 3 因子的展示文案（双主题共用；返回 [(标签, 文案)]）。

    DNS 为近 SENTI_WINDOW_HOURS=72h 标题窗口口径；MOM/ANV 为自然日口径。
    """
    mom = s["momentum"]
    if mom["enough"]:
        mom_line = (f'MOM {mom["value"]:+.2f}（近{mom["short_n"]}日均'
                    f'{mom["short_mean"]:+.2f} vs 近{mom["long_n"]}日均'
                    f'{mom["long_mean"]:+.2f} · {mom["label"]}）')
    else:
        mom_line = (f'MOM 样本不足（n={mom["short_n"]}/{mom["long_n"]}，'
                    f'需≥{mom["need"]}，含今日）')
    vol = s["volume"]
    if vol["enough"]:
        flag = " · ⚠异常放量" if vol["abnormal"] else ""
        vol_line = (f'ANV 今日{vol["today"]}条（近{vol["n"]}天均{vol["mean"]:.1f}条 '
                    f'σ{vol["std"]:.1f} z={vol["z_display"]} · {vol["label"]}{flag}）')
    else:
        vol_line = f'ANV 样本不足（历史n={vol["n"]}，需≥{vol["need"]}天）'
    return [
        (f"{SENTI_WINDOW_HOURS}h 情绪",
         f'DNS {s["score"]:+.2f}（正{s["pos"]}/中{s["neu"]}/负{s["neg"]} · {s["label"]}）'),
        ("情绪动量", mom_line),
        ("新闻量", vol_line),
    ]


def _senti_comment_text(s):
    """个股情绪总结句；入门版去掉「（归因：精确名 2 条 / 别名 1 条）」这类匹配过程括号。"""
    text = str(s.get("comment") or "")
    if PLAIN():
        text = re.sub(r"（归因：[^）]*）", "", text)
    return text


def _senti_reason_text(s, heads=()):
    """个股「原因」文案：引用的标题若与下方证据行同篇，就不再重复长标题（同子栏合并）。

    全量版会同时展示「原因」与「证据标题」：原因里按设计引用最强标题的一段（前 40 字），
    证据行又把整条标题贴一遍。这里把重复引用的那一段换成「见下方证据」——结论与计数不变，
    只是同一条长标题不再连贴两次；「原因」的其余部分（命中词 / 来源 / 动量）原样保留。
    """
    text = str(s.get("reason") or "")
    if not text:
        return text
    for h in heads or ():
        title = str((h or {}).get("title") or "")
        if len(title) >= 12 and title[:40] in text:
            return text.replace(title[:40], "见下方证据", 1)
    return text


def _senti_headline_sub(h):
    """标题行副文案：栏目 · 来源 · 命中词（双主题共用）；72h 窗口内旧日标题前缀日期。"""
    hits = (h["pos_hits"] or []) + (h["neg_hits"] or [])
    hit_txt = f'命中：{"/".join(hits[:3])}' if hits else "无情绪词"
    base = f'{h["section"]} · {h["source"]} · {hit_txt}'
    date = (h.get("date") or "")[:10]
    if h.get("old") and date:
        return f'{date[5:]} · {base}'
    return base


def _pixel_sentiment_block(res):
    """像素主题：新闻情绪——按「A股/港股/美股 成交量前五」逐股评分 + 总结评论 + 原因（2026-09-09 丰富版）。"""
    by_market = res.get("by_market") or []
    total_stocks = sum(len(mb.get("stocks") or []) for mb in by_market)
    ms = res.get("market_summary") or {}
    overview_rows = [
        ("标的范围", f'A股/港股/美股 成交量前 {HOT_STOCK_TOP_N} · 共 {total_stocks} 只'),
        ("窗口内有点名", f'{res["total_matched"]} 只（精确名/别名代码/行业概念归因）'),
        ("标题窗口", f'近 {res.get("window_hours") or SENTI_WINDOW_HOURS} 小时（截至 {res.get("window_text") or "—"}）'),
        ("归因未命中", f'{res["unattributed_n"]} 条（已入下方「市场情绪关键词」）'),
    ]
    head = _mini_table(overview_rows)
    # 市场情绪全景
    summary_cards = []
    if ms.get("available"):
        arrow = "▲" if ms["overall_dns"] > 0.2 else ("▼" if ms["overall_dns"] < -0.2 else "■")
        if ms["overall_dns"] > 0.2:
            color = C_GREEN
        elif ms["overall_dns"] < -0.2:
            color = C_RED
        else:
            color = C_AMBER
        summary_rows = [
            ("整体 DNS", f'<span style="color:{color};font-weight:900;">{ms["overall_dns"]:+.2f}</span>'
                         f'（{ms["overall_label"]} · 正{ms["total_pos"]}/中{ms["total_neu"]}/负{ms["total_neg"]}）'),
        ]
        for mkt in SENTI_MARKET_ORDER:
            md = ms.get("market_dns", {}).get(mkt)
            if not md:
                continue
            if md.get("dns") is None:
                summary_rows.append((f"{mkt}", f'■ 窗口内无匹配'))
            else:
                mkt_color = C_GREEN if md["dns"] > 0.2 else (C_RED if md["dns"] < -0.2 else C_AMBER)
                summary_rows.append((
                    f"{mkt}",
                    f'<span style="color:{mkt_color};font-weight:900;">DNS {md["dns"]:+.2f}</span>'
                    f'（{md["label"]} · {md["matched"]}只）'))
        callouts = []
        if ms.get("hottest"):
            h = ms["hottest"]
            callouts.append(f'最暖：{h["name"]}（{h["score"]:+.2f}）')
        if ms.get("coldest") and ms["coldest"]["key"] != (ms.get("hottest") or {}).get("key"):
            c = ms["coldest"]
            callouts.append(f'最冷：{c["name"]}（{c["score"]:+.2f}）')
        if ms.get("most_covered"):
            m = ms["most_covered"]
            callouts.append(f'最多：{m["name"]}（{m["total"]}条）')
        if callouts:
            summary_rows.append(("关键信号", " · ".join(callouts)))
        summary_cards.append(_pixel_panel(
            f"MARKET OVERVIEW // {arrow} {ms['overall_label']}",
            _mini_table(summary_rows), color, arrow))
    # 逐市场逐股
    cards = []
    seen_heads, dup_heads = {}, 0
    for mb in by_market:
        cards.append(_subsection(f'{_esc(mb["market"])} · 成交量前{HOT_STOCK_TOP_N}'))
        for s in mb.get("stocks") or []:
            if not s.get("matched"):
                body = _mini_table([
                    ("AI 情绪分", "暂无评分"),
                    ("总结评论", _esc(s.get("comment") or "窗口内无相关新闻，AI 暂不评分。")),
                    ("原因", _esc(s.get("reason") or "窗口内标题未点名该股，无新闻证据时不评论。")),
                ])
                cards.append(_pixel_panel(
                    f"STOCK SENTI // {_esc(s['name'])} {_esc(s['code'])} · {s['market']} · ■ 暂无评分",
                    body, C_AMBER, "■"))
                continue
            if s["score"] > 0.2:
                color, icon = C_GREEN, "▲"
            elif s["score"] < -0.2:
                color, icon = C_RED, "▼"
            else:
                color, icon = C_AMBER, "■"
            heads = s["headlines"][:5]
            rows = [
                ("AI 情绪分", f'<span style="color:{color};font-weight:900;">{s["score"]:+.2f}</span>'
                              f'（正{s["pos"]}/中{s["neu"]}/负{s["neg"]} · {_esc(s["label"])}）'),
                ("总结评论", _esc(_senti_comment_text(s))),
                ("原因", _esc(_senti_reason_text(s, heads) if SUB_MERGE_ENABLED
                              else str(s.get("reason") or ""))),
            ]
            body = _mini_table(rows) + _mini_table(_senti_factor_lines(s))
            evidence = []
            stock_label = f'{s["name"]} {s["code"]}'.strip() + f' · {s["market"]}'
            for h in heads:
                badge, bcolor = {1: ("S+1", C_GREEN), -1: ("S−1", C_RED),
                                 0: ("S0", C_AMBER)}[h["s"]]
                tag_mark = ""
                if h.get("tag") == "alias":
                    tag_mark = ' <span style="font-size:10px;color:#888;">[别名]</span>'
                elif h.get("tag") == "sector":
                    tag_mark = ' <span style="font-size:10px;color:#888;">[行业]</span>'
                # 同子栏合并（栏内）：同一篇标题只展开一次，后出现的只留指针，不重复长标题。
                seen_owner = (senti_headline_owner(seen_heads, h["title"], stock_label)
                              if SUB_MERGE_ENABLED else "")
                if seen_owner and seen_owner != stock_label:
                    dup_heads += 1
                    evidence.append(_item_row(
                        "»", f'<b style="color:{bcolor};">[{badge}]</b> '
                             f'<span style="color:{C_MUTED};">{SUB_MERGE_SAME_HEADLINE}：'
                             f'见 {_esc(seen_owner)}（同一篇快讯，标题不重复展开）</span>',
                        _esc(_senti_headline_sub(h))))
                    continue
                evidence.append(_item_row(
                    "»", f'<b style="color:{bcolor};">[{badge}]</b> {_esc(h["title"][:70])}{tag_mark}',
                    _esc(_senti_headline_sub(h))))
            more = len(s["headlines"]) - 5
            if more > 0:
                evidence.append(
                    f'<div style="font-size:10px;color:{C_MUTED};padding:4px 0;'
                    f'line-height:1.7;font-family:{FONT_MONO};">'
                    f'＋其余 {more} 条已计入因子（按情绪强度仅展示前 5 条）</div>')
            body += "".join(evidence)
            cards.append(_pixel_panel(
                f"STOCK SENTI // {_esc(s['name'])} {_esc(s['code'])} · {s['market']} · {_esc(s['label'])}",
                body, color, icon))
    # 未归因市场级情绪关键词
    unattr_n = res.get("unattributed_n") or 0
    unattr_keywords = res.get("unattributed_keywords") or []
    topic_cards = []
    if unattr_n > 0 or dup_heads:
        topic_rows = []
        if unattr_n > 0:
            topic_rows.append(
                ("未归因", f'{unattr_n} 条（正{res.get("unattributed_pos_n") or 0}/'
                           f'中{res.get("unattributed_neu_n") or 0}/负{res.get("unattributed_neg_n") or 0}）'))
            if unattr_keywords:
                kw_parts = [f'{kw}×{n}' for kw, n in unattr_keywords[:8]]
                topic_rows.append(("高频情绪词", "、".join(kw_parts)))
            else:
                topic_rows.append(("高频情绪词", "无显著情绪词命中"))
        if dup_heads:
            topic_rows.append(("同题合并", f'{dup_heads} 条（同一篇标题在多只个股重复出现，'
                                           '标题只展开一次，计数照旧计入各股因子）'))
        topic_cards.append(_pixel_panel(
            f"MARKET MOOD // 未归因{unattr_n}条市场级情绪",
            _mini_table(topic_rows), C_AMBER, "■"))
    note = _note(f"AI 新闻情绪分按近{SENTI_WINDOW_HOURS}h 窗口标题词表评分逐股合成；"
                 "归因三层：精确名 → 别名/代码 → 行业/概念关键词（后两者标[别名]/[行业]）；"
                 "总结评论与原因由命中标题/词表、动量与新闻量确定性规则生成；无新闻的榜单个股明确标注「暂无评分」，"
                 "不凭价格涨跌反推新闻情绪；MOM/ANV 按自然日口径 // RULESET v3 // 非投资建议")
    return head + "".join(summary_cards) + "".join(cards) + "".join(topic_cards) + note

def _senti_empty_counts(res):
    """情绪因子占位用的统一计数（双主题共用）。返回 (n_window, universe_n)。"""
    n_today = (res.get("scored_headlines") or 0) + (res.get("unattributed_n") or 0)
    universe_n = res.get("universe_n") or 0
    return n_today, universe_n


def _pixel_sentiment_empty_block(res):
    """像素主题：新闻情绪「样本不足」占位（72h 窗口有标题但无归因时代替整栏消失）。"""
    n_today, universe_n = _senti_empty_counts(res)
    if universe_n:
        cover = f"0 / {universe_n} 只榜单个股被窗口内标题点名"
    else:
        cover = "热门榜单暂缺 → 无个股宇宙可归因"
    head = _mini_table([
        ("窗口标题", f"{n_today} 条（近 {SENTI_WINDOW_HOURS}h，全部尝试归因）"),
        ("个股宇宙", f"{universe_n} 只（来自热门榜单）" if universe_n else "0 只（热门榜单暂缺）"),
        ("归因结果", cover),
    ])
    body = (head
            + _note(f"DNS/MOM/ANV 需要「标题→榜单个股」的归因样本：近 {SENTI_WINDOW_HOURS}h 标题未点名榜单个股 → "
                    "无样本可出分，明确标注而非伪造。有榜单个股被点名报道时本栏目自动恢复。"))
    return (_alert(f"SAMPLE INSUFFICIENT // 样本不足：{n_today} 条标题（近{SENTI_WINDOW_HOURS}h）均未点名榜单个股", C_AMBER)
            + _pixel_panel("STOCK SENTI // 样本不足", body, C_AMBER, "■")
            + _note(f"因子口径：DNS=(正−负)/总数（近{SENTI_WINDOW_HOURS}h 窗口标题）；MOM=近3有评分日均−近20有评分日均；"
                    "ANV:今日条数>30天均值+2σ标异常（MOM/ANV 按自然日） // RULESET v3 // 非投资建议"))


def gz_sentiment_block(res):
    """谷藏主题：新闻情绪——按「A股/港股/美股 成交量前五」逐股评分 + 总结评论 + 原因（2026-09-09 丰富版）。"""
    by_market = res.get("by_market") or []
    total_stocks = sum(len(mb.get("stocks") or []) for mb in by_market)
    ms = res.get("market_summary") or {}
    out = []
    # ① 总览：一行覆盖面
    out.append(gz_kv_table([
        ("覆盖", f'三市成交量前 {HOT_STOCK_TOP_N} 共 {total_stocks} 只 · 有新闻 {res["total_matched"]} 只'
                 f' · 近 {res.get("window_hours") or SENTI_WINDOW_HOURS}h'),
    ]))
    # ② 市场情绪全景
    if ms.get("available"):
        arrow = "▲" if ms["overall_dns"] > 0.2 else ("▼" if ms["overall_dns"] < -0.2 else "■")
        out.append(gz_subsection(f'市场情绪全景 {arrow} {ms["overall_label"]}'))
        ms_pairs = [(
            "整体 DNS",
            f'{ms["overall_dns"]:+.2f}（{ms["overall_label"]} · '
            f'正{ms["total_pos"]}/中{ms["total_neu"]}/负{ms["total_neg"]} · '
            f'共{ms["total_n"]}条归因标题）')]
        for mkt in SENTI_MARKET_ORDER:
            md = ms.get("market_dns", {}).get(mkt)
            if not md:
                continue
            if md.get("dns") is None:
                continue          # 无匹配市场不占行
            else:
                mkt_arrow = "▲" if md["dns"] > 0.2 else ("▼" if md["dns"] < -0.2 else "■")
                ms_pairs.append((
                    f"{mkt} {mkt_arrow}",
                    f'DNS {md["dns"]:+.2f}（{md["label"]} · '
                    f'{md["matched"]}只 · 正{md["pos"]}/中{md["neu"]}/负{md["neg"]}）'))
        callouts = []
        if ms.get("hottest"):
            h = ms["hottest"]
            callouts.append(f'情绪最暖：{h["name"]}（DNS {h["score"]:+.2f} · {h["label"]}）')
        if ms.get("coldest") and ms["coldest"]["key"] != (ms.get("hottest") or {}).get("key"):
            c = ms["coldest"]
            callouts.append(f'情绪最冷：{c["name"]}（DNS {c["score"]:+.2f} · {c["label"]}）')
        if ms.get("most_covered"):
            m = ms["most_covered"]
            callouts.append(f'报道最多：{m["name"]}（{m["total"]}条）')
        if callouts:
            ms_pairs.append(("关键信号", _esc(" · ".join(callouts))))
        out.append(gz_kv_table(ms_pairs))
    # ③ 逐市场逐股
    #    精简模式（默认）：每市场只列**情绪最强 / 最弱各 1 只**，每只只留「情绪分 + 1 条
    #    最强证据」，原因段与动量 / 新闻量三行折叠（被折叠的只数如实写出）；
    #    全景总览（整体 DNS / 三市 DNS / 最暖最冷 / 报道最多）与关键词统计一行不少。
    per_market = LITE("senti_stocks")
    per_stock_heads = LITE("senti_headlines")
    seen_heads, dup_heads = {}, 0
    for mb in by_market:
        scored = [st for st in (mb.get("stocks") or []) if st.get("matched")]
        if not scored:
            continue              # 该市场无个股被点名 → 不出「暂无评分」占位
        shown = scored
        hidden_n = 0
        if LITE_ENABLED and len(scored) > per_market:
            ranked = sorted(scored, key=lambda st: -(st.get("score") or 0))
            shown = ranked[:max(1, per_market // 2)] + ranked[-max(1, per_market - per_market // 2):]
            hidden_n = len(scored) - len(shown)
        head_txt = f'{_esc(mb["market"])} · 成交量前{HOT_STOCK_TOP_N}'
        if hidden_n and PLAIN():
            head_txt += f'（情绪最强 / 最弱各 1 只，另 {hidden_n} 只未列）'
        elif hidden_n:
            head_txt += f'（只列情绪最强 / 最弱，另 {hidden_n} 只已折叠）'
        out.append(gz_subsection(head_txt))
        for s in shown:
            arrow = "▲" if s["score"] > 0.2 else ("▼" if s["score"] < -0.2 else "■")
            title = f'{s["name"]} {s["code"]}' if s["code"] else s["name"]
            tag_label = {"name": "精确名", "alias": "别名/代码", "sector": "行业概念"}.get(
                s.get("best_tag", "name"), "")
            # 入门版：「归因：精确名 / 别名」是匹配过程，不出；标题后的 [别名]/[行业] 角标同理
            out.append(gz_subsection(
                f'{_esc(title)} · {s["market"]} {arrow}'
                + ("" if PLAIN() else
                   f' <span style="color:{GZ_META};font-weight:{GZ_W_BODY};">归因：{tag_label}</span>')))
            heads = (sorted(s["headlines"], key=lambda h: -abs(h.get("s") or 0))
                     if LITE_ENABLED else s["headlines"])[:per_stock_heads]
            stock_pairs = [("AI 情绪分", _esc(_senti_comment_text(s)))]
            if not LITE_ENABLED:
                stock_pairs.append((
                    "原因", _esc(_senti_reason_text(s, heads) if SUB_MERGE_ENABLED
                                 else str(s.get("reason") or ""))))
                for label, line in _senti_factor_lines(s):
                    if "样本不足" in line:
                        continue  # 冷启动的动量 / 新闻量不出行
                    stock_pairs.append((label, _esc(line)))
            out.append(gz_kv_table(stock_pairs))
            for h in heads:
                badge = {1: "▲ S+1", -1: "▼ S−1", 0: "■ S0"}[h["s"]]
                tag_mark = ""
                if PLAIN():
                    pass
                elif h.get("tag") == "alias":
                    tag_mark = f' <span style="color:{GZ_META}">[别名]</span>'
                elif h.get("tag") == "sector":
                    tag_mark = f' <span style="color:{GZ_META}">[行业]</span>'
                # 同子栏合并（栏内）：同一篇标题只展开一次，后出现的只留指针，不重复长标题。
                stock_label = (f'{s["name"]} {s["code"]}'.strip() + f' · {s["market"]}')
                seen_owner = (senti_headline_owner(seen_heads, h["title"], stock_label)
                              if SUB_MERGE_ENABLED else "")
                if seen_owner and seen_owner != stock_label:
                    dup_heads += 1
                    out.append(gz_item_row(
                        "»",
                        f'<b>{badge}</b> <span style="color:{GZ_META};">'
                        f'{SUB_MERGE_SAME_HEADLINE}：见 {_esc(seen_owner)}（同一篇快讯，标题不重复展开）</span>',
                        _senti_headline_sub(h)))
                    continue
                out.append(gz_item_row(
                    "»",
                    f'<b>{badge}</b> {_esc(h["title"][:70])}{tag_mark}',
                    _senti_headline_sub(h)))
    # ④ 未归因市场级情绪关键词（避免重复展示已在正文出现的标题）
    unattr_n = res.get("unattributed_n") or 0
    unattr_keywords = res.get("unattributed_keywords") or []
    if unattr_n > 0 or dup_heads:
        mood_pairs = []
        if unattr_n > 0:
            mood_pairs.append(("未归因标题",
                               f'{unattr_n} 条 · 正{res.get("unattributed_pos_n") or 0} / '
                               f'中{res.get("unattributed_neu_n") or 0} / 负{res.get("unattributed_neg_n") or 0}'))
            if unattr_keywords:
                kw_parts = [f'{kw}×{n}' for kw, n in unattr_keywords[:8]]
                mood_pairs.append(("高频情绪词", _esc("、".join(kw_parts))))
        if dup_heads:
            mood_pairs.append(("同题合并", f'{dup_heads} 条（同一篇标题在多只个股重复出现，'
                                           '标题只展开一次，计数照旧计入各股因子）'))
        out.append(gz_subsection("市场情绪关键词") + gz_kv_table(mood_pairs))
    return "".join(out)


def gz_sentiment_empty_block(res):
    """谷藏主题：新闻情绪「样本不足」占位（72h 窗口有标题但无归因时代替整栏消失）。"""
    n_today, universe_n = _senti_empty_counts(res)
    if universe_n:
        cover = f"0 / {universe_n} 只榜单个股被窗口内标题点名"
    else:
        cover = "热门榜单暂缺 → 无个股宇宙可归因"
    out = [
        gz_kv_table([
            ("状态说明", f'<b>■ 样本不足：{n_today} 条标题（近{SENTI_WINDOW_HOURS}h）均未点名榜单个股</b>'),
            ("窗口标题", f"{n_today} 条（近 {SENTI_WINDOW_HOURS}h，全部尝试归因）"),
            ("个股宇宙", f"{universe_n} 只（来自热门榜单）" if universe_n
             else "0 只（热门榜单暂缺）"),
            ("归因结果", cover),
        ]),
    ]
    out.append(gz_note(
        f"DNS/MOM/ANV 需要「标题→榜单个股」的归因样本：近 {SENTI_WINDOW_HOURS}h 标题未点名榜单个股 → "
        "无样本可出分，明确标注而非伪造；有榜单个股被点名报道时本栏目自动恢复。因子口径："
        f"DNS=(正−负)/总数（近{SENTI_WINDOW_HOURS}h 窗口标题）；MOM=近3有评分日均−近20有评分日均；"
        "ANV:今日条数>30天均值+2σ标异常（MOM/ANV 按自然日）。非投资建议。"))
    return "".join(out)


# ============================================================
# 政策因子（POLICY SHOCK · 确定性关键词矩阵）
# ------------------------------------------------------------
# 抓取后、推送前单独构建（main 1.6 阶段），渲染到专业分析栏目组。
# 逻辑：识别政策类新闻（监管/扶持/货币/财政/地产/贸易/宏观数据等维度），经
# 关键词矩阵映射到行业受益/受损权重，汇总为 PolicyShockIndex：
#   行业 PSI ＝ 该行业在今日政策新闻中的权重之和（正=受益，负=承压）
#   大盘 PSI ＝ 宽基权重之和（>0 偏暖 / <0 偏冷 / =0 中性）
# 维度分两类：固定映射（货币/财政/地产/宏观数据，直接给行业权重）与
# 行业归因（扶持/监管/开放/贸易，按标题提及的行业落权重；无提及
# 落宽基小权重并标注宽基）。触发词被否定词修饰时跳过（如"暂不降准"）。
# 中国政府网条目额外带 official=True：即使标题没有方向性触发词，也按「政策发布」
# 中性维度纳入政策因子并保留官方原文链接，避免官方发布的条例/规划因标题措辞不同而漏检。
# 只统计近 POLICY_WINDOW_DAYS=15 日窗口内标题（复用标题收集器，含历史存档，
# 无 ts 的标题按 date 判断，当天标题自然在窗口内）；窗口内零政策/宏观新闻时
# 栏目缺席，不伪造。
# ============================================================
POLICY_DISPLAY_INDUSTRIES = 5   # 受益/承压榜单各展示的行业数
POLICY_DISPLAY_HEADLINES = 8    # 政策新闻逐条展示上限

# 政策维度矩阵：triggers 命中即该维度命中（同一维度每条只计一次，
# 权重只落一次）；weights 为固定行业映射，needs_industry 为行业归因。
_POLICY_DIMENSIONS = [
    {"id": "easing", "label": "货币宽松",
     "triggers": ["降准", "降息", "双降", "LPR", "MLF", "逆回购", "宽松",
                  "放水", "加大投放", "呵护流动性", "保持流动性",
                  "降準", "寬鬆"],
     "weights": {"银行": -1, "证券": +2, "地产链": +2, "消费": +1,
                 "科技成长": +1, "大盘": +1}},
    {"id": "tightening", "label": "货币收紧",
     "triggers": ["加息", "缩表", "收紧流动性", "回笼资金", "縮表", "收緊"],
     "weights": {"银行": +1, "证券": -2, "地产链": -2, "消费": -1,
                 "科技成长": -1, "大盘": -1}},
    {"id": "support", "label": "产业扶持",
     "triggers": ["产业政策", "新质生产力", "专项资金", "重大项目",
                  "大力发展", "政策支持", "培育壮大", "扶持", "补贴",
                  "国补", "補貼"],
     "needs_industry": True, "weight": +2, "broad_weight": +1},
    {"id": "regulation", "label": "监管收紧",
     "triggers": ["立案调查", "窗口指导", "反垄断", "约谈", "罚单",
                  "监管", "规范", "整顿", "严查", "重罚",
                  "監管", "約談", "罰單", "反壟斷", "整頓", "嚴查"],
     "needs_industry": True, "weight": -2, "broad_weight": -1},
    {"id": "fiscal", "label": "财政发力",
     "triggers": ["特别国债", "增发国债", "专项债", "化债", "减税",
                  "降费", "赤字", "财政", "財政", "專項債", "減稅"],
     "weights": {"基建链": +2, "消费": +1, "大盘": +1}},
    {"id": "property_ease", "label": "地产松绑",
     "triggers": ["认房不认贷", "下调首付", "降低首付", "城中村改造",
                  "白名单", "松绑", "收储", "鬆綁"],
     "weights": {"地产链": +2, "银行": +1, "大盘": +1}},
    {"id": "property_tight", "label": "地产收紧",
     "triggers": ["限购", "限贷", "限售", "限購", "限貸"],
     "weights": {"地产链": -2, "银行": -1, "大盘": -1}},
    {"id": "opening", "label": "开放准入",
     "triggers": ["负面清单", "对外开放", "扩大开放", "准入", "自贸",
                  "放开", "试点", "負面清單", "對外開放", "準入",
                  "自貿", "試點"],
     "needs_industry": True, "weight": +1, "broad_weight": +1},
    {"id": "trade_barrier", "label": "贸易壁垒",
     "triggers": ["实体清单", "出口管制", "加征", "关税", "制裁",
                  "断供", "關稅", "斷供", "實體清單"],
     "needs_industry": True, "weight": -2, "broad_weight": -1},
    # 宏观数据（2026-09-09 增补）：CPI / PPI / 社融 / 统计局等经济数据口径。
    # 规则启发式：按“数据温和向好”统一计中性偏暖（CPI 回升利多消费与再通胀链、
    # PPI 涨幅扩大利多上游资源），方向细分留给后续增强；触发词同样受否定修饰保护。
    {"id": "macro", "label": "宏观数据",
     "triggers": ["CPI", "PPI", "PMI", "社融", "M2", "GDP", "新增信贷",
                  "新增人民币贷款", "社会消费品零售总额", "工业增加值",
                  "统计局", "经济数据", "宏观数据", "通胀", "物价", "通脹"],
     "weights": {"大盘": +1, "消费": +1, "有色金属": +1,
                 "煤炭能源": +1, "钢铁化工": +1}},
]

# 官方列表里的条例、规划、办法等本身就是政策信息，但标题不一定含有「扶持」或
# 「监管」触发词。仅对 official=True 的政府网条目使用该中性兜底维度，避免普通
# 媒体标题中的「发布」被误判；权重为 0，表示已纳入政策信息但不擅自判断方向。
_OFFICIAL_POLICY_DIMENSION = {
    "id": "official_publication", "label": "政策发布",
    "weights": {"大盘": 0},
}

# 行业别名词表（归因维度用；匹配最长优先，如"锂电"优先于"锂"）。
_POLICY_INDUSTRIES = {
    "新能源": ["新能源", "光伏", "风电", "储能", "锂电池", "锂电",
              "充电桩", "新能源", "光伏"],
    "半导体": ["半导体", "集成电路", "芯片", "晶圆", "半導體", "芯片"],
    "医药": ["生物医药", "创新药", "医药", "医疗", "疫苗", "中药",
            "醫藥", "醫療"],
    "汽车": ["新能源车", "智能驾驶", "无人驾驶", "汽车", "汽車"],
    "军工": ["军工", "国防", "軍工"],
    "AI算力": ["人工智能", "大模型", "数据中心", "算力", "机器人", "AI"],
    "消费": ["食品饮料", "消费", "零售", "白酒", "餐饮", "旅游", "家电"],
    "地产链": ["房地产", "地产", "楼市", "建材", "水泥",
              "房地產", "地產"],
    "银行": ["银行"],
    "证券": ["证券", "券商", "期货", "證券"],
    "保险": ["保险", "保險"],
    "有色金属": ["有色", "稀土", "黄金", "铜", "铝", "锂", "钴",
                "镍", "鎳"],
    "煤炭能源": ["煤炭", "石油", "原油", "天然气", "电力", "火电",
                "水电", "核电"],
    "钢铁化工": ["钢铁", "化工", "化纤", "纯碱", "鋼鐵"],
    "农业": ["农业", "种业", "粮食", "猪肉", "养殖"],
    "传媒游戏": ["传媒", "游戏", "版号", "影视", "廣告", "遊戲"],
    "基建链": ["工程机械", "基建", "建筑", "高铁", "轨交"],
    "科技成长": ["平台经济", "互联网", "科技", "软件", "电子", "互聯網"],
    "出口链": ["跨境电商", "出口", "外贸", "航运", "港口"],
}
_POLICY_INDUSTRY_ALIASES = {}
for _ind_name, _ind_aliases in _POLICY_INDUSTRIES.items():
    for _alias in _ind_aliases:
        _POLICY_INDUSTRY_ALIASES.setdefault(_alias, _ind_name)
_POLICY_INDUSTRY_ALIAS_LIST = list(_POLICY_INDUSTRY_ALIASES)


def _match_policy_triggers(title, triggers):
    """维度触发词匹配：最长优先非重叠；前2字含否定词视为否定表述，跳过。"""
    hits = []
    for word, idx in _match_words_non_overlap(title, triggers):
        window = title[max(0, idx - 2):idx]
        if any(ch in _SENTI_NEGATORS for ch in window):
            continue
        hits.append(word)
    return hits


def _match_policy_industries(title):
    """标题提及的行业（别名最长优先非重叠匹配，按出现顺序去重）。"""
    found = []
    for alias, _ in _match_words_non_overlap(title, _POLICY_INDUSTRY_ALIAS_LIST):
        industry = _POLICY_INDUSTRY_ALIASES[alias]
        if industry not in found:
            found.append(industry)
    return found


def _policy_summary(policy_n, total_n, dim_counts, broad_score, broad_label,
                    winners, losers, official_n=0):
    """规则生成的政策总结（纯数据转述，无伪造）。"""
    if policy_n == 0:
        return "窗口内未检出显著政策新闻。"
    dims = "、".join(f"{k}×{v}" for k, v in
                     sorted(dim_counts.items(), key=lambda kv: (-kv[1], kv[0])))
    # 含「宏观数据」维度（CPI/PPI/统计局等）时，称谓用「政策及宏观数据类新闻」更贴切
    kind = "政策及宏观数据类新闻" if "宏观数据" in dim_counts else "政策类新闻"
    parts = [f"近{POLICY_WINDOW_DAYS}日窗口内检出{kind} {policy_n} 条（占窗口资讯 "
             f"{policy_n}/{total_n}），覆盖维度：{dims}；"
             f"大盘政策冲击指数 PSI {broad_score:+d}（{broad_label}）。"]
    if official_n:
        parts.append(f"其中中国政府网官方发布 {official_n} 条。")
    if winners:
        parts.append("受益居前：" + "、".join(
            f'{w["name"]}{w["score"]:+d}（{w["count"]}条）' for w in winners[:3]) + "。")
    if losers:
        parts.append("承压居前：" + "、".join(
            f'{w["name"]}{w["score"]:+d}（{w["count"]}条）' for w in losers[:3]) + "。")
    if not winners and not losers:
        if official_n and set(dim_counts).issubset({"政策发布"}):
            parts.append("已纳入中国政府网官方政策发布信息，但标题未给出明确方向；行业冲击暂不判定。")
        else:
            parts.append("各行业冲击相互抵消，无显著受益/承压方向。")
    return "".join(parts)


def build_policy_factor(data, date_str=None, news_corpus=None):
    """构建政策因子（抓取后、推送前单独构建；渲染在专业分析栏目组）。

    标题窗口：近 POLICY_WINDOW_DAYS=15 日（自然日，含锚定日；news_corpus 为
    跨运行标题存档，缺省时只用本次抓取标题，仍按 15 日窗口过滤）。中国政府网
    直接发布的条目带 official=True、官方原文 URL；即使没有方向性触发词也按
    「政策发布」中性维度纳入。窗口内零政策/宏观新闻时 available=False，栏目缺席。

    量化趋势预判（2026-09-29 升级）：在 PSI 基础上做量化复合分：
    PSI 归一 50% + 政策新闻量 30% + 维度覆盖 20%，输出趋势分、强度榜与预判信号。
    """
    anchor_dt = _factor_anchor_dt(date_str) if date_str else datetime.now(CST)
    anchor_date = anchor_dt.strftime("%Y-%m-%d")
    if isinstance(news_corpus, dict) and isinstance(news_corpus.get("items"), list):
        raw = news_corpus["items"]
    else:
        raw = _collect_headline_items(data, anchor_date)
    headlines = _filter_headlines_window(raw, anchor_dt, days=POLICY_WINDOW_DAYS)
    try:
        today_iso = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d") \
            if date_str else anchor_date
    except (TypeError, ValueError):
        today_iso = anchor_date
    industry_scores = {}
    broad_score = 0
    broad_count = 0
    dim_counts = {}
    official_n = 0
    policy_heads = []
    for head in headlines:
        title = head["title"]
        hit_dims = []
        for dim in _POLICY_DIMENSIONS:
            triggers = _match_policy_triggers(title, dim["triggers"])
            if triggers:
                hit_dims.append(dim)
        if not hit_dims and head.get("official"):
            hit_dims.append(_OFFICIAL_POLICY_DIMENSION)
        if not hit_dims:
            continue
        head_industries = []
        head_net = 0
        head_dims = []
        for dim in hit_dims:
            head_dims.append(dim["label"])
            dim_counts[dim["label"]] = dim_counts.get(dim["label"], 0) + 1
            if "weights" in dim:
                pairs = list(dim["weights"].items())
            else:
                mentioned = _match_policy_industries(title)
                if mentioned:
                    pairs = [(ind, dim["weight"]) for ind in mentioned]
                else:
                    pairs = [("大盘", dim["broad_weight"])]
            for ind, w in pairs:
                head_net += w
                if ind == "大盘":
                    broad_score += w
                    broad_count += 1
                else:
                    slot = industry_scores.setdefault(
                        ind, {"score": 0, "count": 0, "dims": set()})
                    slot["score"] += w
                    slot["count"] += 1
                    slot["dims"].add(dim["label"])
                    if ind not in head_industries:
                        head_industries.append(ind)
        item_date = (head.get("date") or "")[:10]
        is_official = bool(head.get("official"))
        if is_official:
            official_n += 1
        policy_heads.append({
            "title": title, "source": head.get("source", ""),
            "section": head.get("section", ""), "url": head.get("url", ""),
            "official": is_official,
            "dims": head_dims, "industries": head_industries,
            "direction": 1 if head_net > 0 else (-1 if head_net < 0 else 0),
            "net": head_net,
            "date": item_date,
            "old": item_date not in ("", today_iso),
        })
    industries = [{
        "name": name, "score": v["score"], "count": v["count"],
        "dims": sorted(v["dims"]),
        "direction": "受益" if v["score"] > 0 else ("承压" if v["score"] < 0 else "中性"),
    } for name, v in industry_scores.items()]
    industries.sort(key=lambda s: (-s["score"], s["name"]))
    winners = [s for s in industries if s["score"] > 0][:POLICY_DISPLAY_INDUSTRIES]
    losers = sorted((s for s in industries if s["score"] < 0),
                    key=lambda s: (s["score"], s["name"]))[:POLICY_DISPLAY_INDUSTRIES]
    broad_label = "偏暖" if broad_score > 0 else ("偏冷" if broad_score < 0 else "中性")
    summary = _policy_summary(len(policy_heads), len(headlines), dim_counts,
                              broad_score, broad_label, winners, losers, official_n)
    # —— 量化趋势预判：PSI归一50% + 新闻量30% + 维度覆盖20% ——
    psi_z = max(-3, min(3, broad_score / 2.0))
    news_score = min(2, len(policy_heads) / 3.0)
    dim_score = min(2, len(dim_counts) / 2.0)
    quant_composite = round(0.5 * psi_z + 0.3 * news_score + 0.2 * dim_score, 2)
    if quant_composite > 1.2:
        quant_trend = "强势趋暖"
        quant_signal = "趋势预判·积极布局"
    elif quant_composite > 0.5:
        quant_trend = "偏强趋暖"
        quant_signal = "趋势预判·逢低布局"
    elif quant_composite > -0.5:
        quant_trend = "中性震荡"
        quant_signal = "趋势预判·中性配置"
    elif quant_composite > -1.2:
        quant_trend = "偏弱趋冷"
        quant_signal = "趋势预判·防御为主"
    else:
        quant_trend = "弱势趋冷"
        quant_signal = "趋势预判·规避观望"
    if broad_score > 2 and len(policy_heads) < 2:
        quant_signal += "（量能背离·谨慎）"
    if broad_score < -2 and len(policy_heads) < 2:
        quant_signal += "（量能背离·谨慎）"
    quant_industries = []
    for s in industries:
        s_psi_z = max(-3, min(3, s["score"] / 2.0))
        s_news = min(2, s["count"] / 2.0)
        s_dim = min(2, len(s["dims"]) / 1.5)
        s_composite = round(0.6 * s_psi_z + 0.3 * s_news + 0.1 * s_dim, 2)
        if s_composite > 1.2:
            s_trend = "强势"
        elif s_composite > 0.5:
            s_trend = "偏强"
        elif s_composite > -0.5:
            s_trend = "中性"
        elif s_composite > -1.2:
            s_trend = "偏弱"
        else:
            s_trend = "弱势"
        quant_industries.append({
            "name": s["name"], "score": s["score"], "count": s["count"],
            "dims": s["dims"], "composite": s_composite, "trend": s_trend,
            "direction": s["direction"]
        })
    quant_industries.sort(key=lambda x: -x["composite"])
    if losers and broad_score < 0:
        quant_risk = f"趋势预判风险预算：PSI {broad_score:+d}偏冷，承压居前 {losers[0]['name']}（{losers[0]['score']:+d}），趋势策略宜防御，关注政策落地节奏。"
    elif losers:
        quant_risk = f"趋势预判风险预算：承压行业 {losers[0]['name']}（{losers[0]['score']:+d}），注意政策分化，趋势跟踪宜均衡配置。"
    elif broad_score < 0:
        quant_risk = "趋势预判风险预算：大盘PSI偏冷，政策边际收紧，趋势策略宜控制仓位，等待转暖信号。"
    else:
        quant_risk = "趋势预判风险预算：未检出显著政策利空，趋势预判可正常执行，注意维度覆盖与新闻量背离。"
    return {
        "available": bool(policy_heads),
        "policy_n": len(policy_heads),
        "official_n": official_n,
        "total_headlines": len(headlines),
        "dim_counts": dim_counts,
        "broad_score": broad_score,
        "broad_count": broad_count,
        "broad_label": broad_label,
        "industries": industries,
        "winners": winners,
        "losers": losers,
        "headlines": policy_heads,
        "summary": summary,
        "window_days": POLICY_WINDOW_DAYS,
        "corpus_n": len(headlines),
        "quant_composite": quant_composite,
        "quant_trend": quant_trend,
        "quant_signal": quant_signal,
        "quant_risk": quant_risk,
        "quant_industries": quant_industries,
    }

def build_daily_quant_policy(data, date_str=None, news_corpus=None):
    """兼容别名：政策因子入口。"""
    return build_policy_factor(data, date_str, news_corpus)


def _policy_headline_markup(headline, color=C_INK):
    """渲染政策标题，并为官方发布条目保留可点击的原文链接。

    标题来自外部页面，正文必须先转义；仅允许 http/https 链接进入 href，
    避免把存档中的异常值变成脚本属性。中国政府网解析器本身还会限制域名为
    ``*.gov.cn``，这里的通用校验用于兼容手工注入的测试/历史数据。
    """
    title = _esc((headline.get("title") or "")[:60])
    url = str(headline.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        title = (f'<a href="{_esc(url)}" style="color:{color};text-decoration:none;'
                 f'border-bottom:1px dotted {color};">{title}</a>')
        if headline.get("official"):
            title += (f' <span style="font-size:10px;color:{color};font-weight:900;">'
                      "[官方原文]</span>")
    return title


def _policy_source_text(headline):
    """政策条目的可读来源标签；官方条目明确标注发布主体。"""
    source = headline.get("source") or "政策资讯"
    return f"{source}（官方发布）" if headline.get("official") else source


def _pixel_policy_block(res):
    """像素主题：政策因子（量化预判 + PSI 行业榜 + 政策新闻逐条）。"""
    if res["broad_score"] > 0:
        color, icon = C_GREEN, "▲"
    elif res["broad_score"] < 0:
        color, icon = C_RED, "▼"
    else:
        color, icon = C_AMBER, "■"
    summary_html = (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
        f'margin-bottom:10px;border:1px solid {color};background:#0C1020;box-shadow:4px 4px 0 #000;">'
        f'<tr><td style="padding:10px 12px;">'
        f'<div style="font-size:9px;color:{color};font-weight:900;font-family:{FONT_MONO};'
        f'letter-spacing:1px;">QUANT POLICY // 每日量化策略·政策因子趋势预判</div>'
        f'<div style="font-size:12px;color:{C_INK};font-weight:700;line-height:1.8;'
        f'font-family:{FONT_MONO};padding-top:4px;">{_esc(res["summary"])}</div>'
        f'</td></tr></table>')
    dims_line = " · ".join(f"{k}×{v}" for k, v in sorted(
        res["dim_counts"].items(), key=lambda kv: (-kv[1], kv[0]))) or "—"
    head = _mini_table([
        ("政策新闻", f'{res["policy_n"]} 条（占近 {res.get("window_days") or POLICY_WINDOW_DAYS} 日窗口资讯 '
                     f'{res["policy_n"]}/{res["total_headlines"]}）'),
        ("大盘冲击", f'PSI <b style="color:{color};">{res["broad_score"]:+d}</b>'
                     f'（{res["broad_count"]}次映射 · {res["broad_label"]}）'),
        ("覆盖维度", _esc(dims_line)),
    ])
    if res.get("official_n"):
        head += _mini_table([("官方来源", f'中国政府网官方发布 {res["official_n"]} 条')])
    quant_composite = res.get("quant_composite")
    if quant_composite is not None:
        head += _mini_table([
            ("量化趋势分", f'<b style="color:{color};">{quant_composite:+.2f}</b> · {_esc(res.get("quant_trend") or "—")}'),
            ("趋势预判信号", f'<b style="color:{color};">{_esc(res.get("quant_signal") or "—")}</b>'),
        ])
        if res.get("quant_risk"):
            head += _mini_table([("风险预算", _esc(res["quant_risk"]))])
    board = []
    quant_inds = res.get("quant_industries") or []
    if quant_inds:
        for s in quant_inds[:5]:
            arrow = "▲" if s["composite"] > 0.5 else ("▼" if s["composite"] < -0.5 else "■")
            color_s = C_GREEN if s["composite"] > 0.5 else (C_RED if s["composite"] < -0.5 else C_AMBER)
            board.append((f'{arrow} {_esc(s["name"])} <span style="color:{color_s};">{s["composite"]:+.2f}</span>',
                          f'PSI <b style="color:{color_s};">{s["score"]:+d}</b>（{s["count"]}条 · {_esc("/".join(s["dims"]))} · {s["trend"]}）'))
    else:
        for s in res["winners"]:
            board.append((f'▲ {_esc(s["name"])}',
                          f'PSI <b style="color:{C_GREEN};">+{s["score"]}</b>'
                          f'（{s["count"]}条 · {_esc("/".join(s["dims"]))}）'))
        for s in res["losers"]:
            board.append((f'▼ {_esc(s["name"])}',
                          f'PSI <b style="color:{C_RED};">{s["score"]}</b>'
                          f'（{s["count"]}条 · {_esc("/".join(s["dims"]))}）'))
    rows = []
    for h in res["headlines"][:POLICY_DISPLAY_HEADLINES]:
        if h["direction"] > 0:
            arrow, bcolor = "▲", C_GREEN
        elif h["direction"] < 0:
            arrow, bcolor = "▼", C_RED
        else:
            arrow, bcolor = "■", C_AMBER
        inds = "、".join(h["industries"][:4]) if h["industries"] else "大盘（宽基）"
        sub = (f'{"/".join(h["dims"])} · 影响：{inds} · {h["section"]} · '
               f'{_policy_source_text(h)}')
        if h.get("old") and h.get("date"):
            sub = f'{h["date"][5:]} · {sub}'
        rows.append(_item_row(
            "◆", f'<b style="color:{bcolor};">[{arrow} {h["net"]:+d}]</b> '
            f'{_policy_headline_markup(h, C_INK)}', _esc(sub)))
    more = len(res["headlines"]) - POLICY_DISPLAY_HEADLINES
    if more > 0:
        rows.append(
            f'<div style="font-size:10px;color:{C_MUTED};padding:4px 0;'
            f'line-height:1.7;font-family:{FONT_MONO};">'
            f'＋其余 {more} 条已计入指数（仅展示前 {POLICY_DISPLAY_HEADLINES} 条）</div>')
    body = head + (_mini_table(board) if board else "") + "".join(rows)
    note = _note(f"政策因子口径：近 {res.get('window_days') or POLICY_WINDOW_DAYS} 日窗口标题 → 政策维度触发词命中 → "
                 "关键词矩阵映射行业权重 → 汇总PSI + 量化复合分(PSI50%+新闻量30%+维度20%)；触发词被否定修饰时跳过 // RULESET v3 // 非投资建议")
    return summary_html + _pixel_panel("QUANT POLICY // 政策因子趋势预判·量化强度", body, color, icon) + note


def gz_policy_block(res):
    """政策因子（黑白模式：方向只用 ▲▼■ 符号区分）。定调已置顶到「今日预判」。"""
    dims_sorted = sorted(res["dim_counts"].items(), key=lambda kv: (-kv[1], kv[0]))
    if PLAIN() and len(dims_sorted) > 4:
        # 入门版：维度计数只列前 4 类，其余按类数收口
        dims_line = (" · ".join(f"{k}×{v}" for k, v in dims_sorted[:4])
                     + f" 等 {len(dims_sorted)} 类")
    else:
        dims_line = " · ".join(f"{k}×{v}" for k, v in dims_sorted) or "—"
    window = res.get("window_days") or POLICY_WINDOW_DAYS
    pairs = [
        ("大盘冲击", f'PSI {res["broad_score"]:+d} · {_esc(res["broad_label"])}'),
        ("政策新闻", f'{res["policy_n"]} 条（近 {window} 日）'
                     + (f'，其中政府网官方 {res["official_n"]} 条' if res.get("official_n") else "")),
        ("覆盖维度", _esc(dims_line)),
    ]
    if res.get("quant_composite") is not None:
        pairs.append(("量化趋势分", f'{res["quant_composite"]:+.2f} · {_esc(res.get("quant_trend") or "—")}'))
        pairs.append(("趋势预判信号", _esc(res.get("quant_signal") or "—")))
        if res.get("quant_risk"):
            pairs.append(("风险预算", _esc(res["quant_risk"])))
    out = [gz_kv_table(pairs)]
    board = []
    quant_inds = res.get("quant_industries") or []
    if quant_inds:
        for s in quant_inds[:5]:
            arrow = "▲" if s["composite"] > 0.5 else ("▼" if s["composite"] < -0.5 else "■")
            board.append([f'{arrow} {_esc(s["name"])} {s["composite"]:+.2f}', f'{s["score"]:+d}', f'{s["count"]}条',
                          _esc("/".join(s["dims"])) + f' · {s["trend"]}'])
    else:
        for s in res["winners"]:
            board.append([f'▲ {_esc(s["name"])}', f'+{s["score"]}', f'{s["count"]}条',
                          _esc("/".join(s["dims"]))])
        for s in res["losers"]:
            board.append([f'▼ {_esc(s["name"])}', f'{s["score"]}', f'{s["count"]}条',
                          _esc("/".join(s["dims"]))])
    if board:
        out.append(gz_subsection("政策冲击强度榜 · 量化趋势")
                   + gz_data_table(["行业", "PSI", "条数", "维度"], board))
    # 政策新闻逐条不裁：条数已由 POLICY_DISPLAY_HEADLINES 封顶（8 条），而且旧闻
    # （报告日前一天）必须留在正文里，读者才看得见「08-01 ·」这个日期前缀披露。
    heads = res["headlines"][:POLICY_DISPLAY_HEADLINES]
    if heads:
        out.append(gz_subsection("重点政策新闻"))
    for h in heads:
        badge = "▲" if h["direction"] > 0 else ("▼" if h["direction"] < 0 else "■")
        inds = "、".join(h["industries"][:4]) if h["industries"] else "大盘"
        bits = [h["date"][5:] if h.get("date") else "", "/".join(h["dims"]),
                f"影响 {inds}", _policy_source_text(h)]
        sub = " · ".join(_esc(x) for x in bits if x)
        out.append(gz_item_row(
            "◆", f'<b>{badge} {h["net"]:+d}</b> '
            f'{_policy_headline_markup(h, GZ_INK)}', sub))
    return "".join(out)


def _scan_line(res):
    """标题扫描一行：命中条数 + 与正文重复不重列的条数（精简排版不输出脚注）。"""
    line = f'{int(res.get("total") or 0)} 条 · 命中 {len(res.get("evidence") or [])} 条'
    if res.get("dup_n"):
        line += f' · 另 {int(res["dup_n"])} 条重复不重列（已计入定调）'
    return line


def _pixel_trend_topic_block(res):
    """像素主题：AI趋势分析（美联储 / 地缘政治）——定调 + 命中证据 +（美联储）日程时间点。"""
    pos_n, neg_n = int(res.get("positive_n") or 0), int(res.get("negative_n") or 0)
    if pos_n > neg_n:
        color, icon = C_GREEN, "▲"
    elif neg_n > pos_n:
        color, icon = C_RED, "▼"
    else:
        color, icon = C_AMBER, "■"
    topic = _esc(str(res.get("topic") or ""))
    head = _mini_table([
        ("方向定调", f'<b style="color:{color};font-size:13px;">{icon} {_esc(str(res.get("verdict") or "—"))}</b>'),
        ("词表计数", f'{_esc(str(res.get("positive_label") or ""))} {pos_n} · '
                    f'{_esc(str(res.get("negative_label") or ""))} {neg_n}'),
        ("标题扫描", _scan_line(res)),
    ])
    rows = []
    for ev in res.get("evidence") or []:
        hits = "、".join((ev.get("pos_hits") or []) + (ev.get("neg_hits") or []))
        tag = "▲" if ev.get("pos_hits") and not ev.get("neg_hits") else (
            "▼" if ev.get("neg_hits") and not ev.get("pos_hits") else "■")
        tcolor = C_GREEN if tag == "▲" else (C_RED if tag == "▼" else C_AMBER)
        sub = " · ".join(x for x in (_esc(str(ev.get("source") or "")),
                                     _esc(str(ev.get("time") or "")),
                                     f"命中：{_esc(hits)}" if hits else "") if x)
        rows.append(_item_row("◆", f'<b style="color:{tcolor};">{tag}</b> '
                                   f'{_esc(str(ev.get("title") or ""))}', sub))
    body = head + "".join(rows)
    events = res.get("events") or []
    if events:
        erows = []
        for ev in events:
            imp = int(ev.get("imp") or 0)
            stars = "★" * imp if imp else "—"
            erows.append((f'{_esc(str(ev.get("date") or ""))} {_esc(str(ev.get("time") or ""))}',
                          f'{_esc(str(ev.get("name") or ""))} <b style="color:{C_LEMON};">{stars}</b>'))
        body += _subsection("未来相关时间点（财经日程）") + _mini_table(erows)
    return _pixel_trend_summary(topic, icon, color, res) + _pixel_panel(
        f"AI TREND // {topic}趋势研判", body, color, icon)


def _pixel_trend_summary(topic, icon, color, res):
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
        f'margin-bottom:10px;border:1px solid {color};background:#0C1020;box-shadow:4px 4px 0 #000;">'
        f'<tr><td style="padding:10px 12px;">'
        f'<div style="font-size:9px;color:{color};font-weight:900;font-family:{FONT_MONO};'
        f'letter-spacing:1px;">AI TREND READ // {topic}趋势定调</div>'
        f'<div style="font-size:12px;color:{C_INK};font-weight:700;line-height:1.8;'
        f'font-family:{FONT_MONO};padding-top:4px;">{icon} {_esc(str(res.get("verdict") or "—"))}'
        f' · {_esc(str(res.get("positive_label") or ""))} {int(res.get("positive_n") or 0)}'
        f' / {_esc(str(res.get("negative_label") or ""))} {int(res.get("negative_n") or 0)}</div>'
        f'</td></tr></table>')


# theme：跨栏「同子栏合并」按主题判定 12 栏板块热力的切片口径（见 _panorama_heat_selection）。
PIXEL_KIT = _RenderKit(
    theme="pixel",
    market_section=_pixel_market_section,
    market_review=_pixel_market_review,
    channel_block=_channel_block,
    headline_row=_headline_row,
    em_news_row=_em_news_row,
    item_row=_item_row,
    # pixel 的行函数每条已是独立 <table>，拼接后无需再包一层。
    rows=lambda html: html or "",
    note=_note,
    alert=_alert,
    status_footer=_status_footer,
    source_badge=_source_badge,
    ai_badge=lambda: _badge("AI 合成", "ai"),
    ai_block=_ai_analysis_block,
    sentiment_block=_pixel_sentiment_block,
    sentiment_empty_block=_pixel_sentiment_empty_block,
    senti_empty_badge=lambda: _badge("样本不足", "warn"),
    policy_block=_pixel_policy_block,
    panorama_block=_panorama_block,
    calendar_block=lambda res, date_str=None: _calendar_block(res, date_str=date_str),
    trend_topic_block=_pixel_trend_topic_block,
    # ---- 量化栏目需要的排版原语（注入给 octopus_quant.render）----
    esc=_esc,
    table=lambda headers, rows, aligns=None: _pixel_table(headers, rows, aligns),
    sub=_subsection,
    meter=lambda value, maximum: _signal_meter(value, maximum),
    badge=_badge,
    section=_section,
    kv=lambda pairs: _data_table([(label, value) for label, value in pairs]),
    trend=_trend_badge,
    ok_color=C_GREEN, warn_color=C_AMBER, bad_color=C_RED,
)

def gz_trend_topic_block(res):
    """AI趋势分析（美联储 / 地缘政治）（黑白模式：方向只用 ▲▼■ 符号区分）。"""
    pos_n, neg_n = int(res.get("positive_n") or 0), int(res.get("negative_n") or 0)
    topic = _esc(str(res.get("topic") or ""))
    pairs = [
        ("方向定调", f'{_esc(str(res.get("verdict") or "—"))}'),
        ("词表计数", f'{_esc(str(res.get("positive_label") or ""))} {pos_n} · '
                    f'{_esc(str(res.get("negative_label") or ""))} {neg_n}'),
    ]
    if not PLAIN():            # 入门版：扫描 / 命中 / 重复条数的过程行不出
        pairs.append(("标题扫描", _scan_line(res)))
    out = [gz_kv_table(pairs)]
    evid = res.get("evidence") or []
    evid_limit = LITE("trend_evidence")
    if evid:
        hidden = max(0, len(evid) - evid_limit) if evid_limit else 0
        out.append(gz_subsection("命中证据"
                                 + (f"（前 {evid_limit} 条，另 {hidden} 条已计入定调）"
                                    if hidden and not PLAIN() else "")))
        evid = evid[:evid_limit] if evid_limit else evid
    for ev in evid:
        hits = "、".join((ev.get("pos_hits") or []) + (ev.get("neg_hits") or []))
        tag = "▲" if ev.get("pos_hits") and not ev.get("neg_hits") else (
            "▼" if ev.get("neg_hits") and not ev.get("pos_hits") else "■")
        sub = " · ".join(x for x in (_esc(str(ev.get("source") or "")),
                                     _esc(str(ev.get("time") or "")),
                                     f"命中：{_esc(hits)}" if hits else "") if x)
        out.append(gz_item_row("◆", f'<b>{tag}</b> '
                                    f'{_esc(str(ev.get("title") or ""))}', sub))
    events = res.get("events") or []
    ev_limit = LITE("trend_events")
    if events:
        rows = []
        hidden = max(0, len(events) - ev_limit) if ev_limit else 0
        out.append(gz_subsection("未来相关时间点（财经日程）"
                                 + (f"（近端 {ev_limit} 条，另 {hidden} 条见时间节点栏目）"
                                    if hidden and not PLAIN() else "")))
        for ev in (events[:ev_limit] if ev_limit else events):
            imp = int(ev.get("imp") or 0)
            stars = "★" * imp if imp else "—"
            rows.append([_esc(str(ev.get("date") or "")), _esc(str(ev.get("time") or "")),
                         _esc(str(ev.get("name") or "")), stars])
        out.append(gz_data_table(["日期", "时间", "事件", "重要度"], rows))
    return "".join(out)


# theme：跨栏「同子栏合并」按主题判定 12 栏板块热力的切片口径（见 _panorama_heat_selection）。
GUIZANG_KIT = _RenderKit(
    theme="guizang",
    market_section=gz_market_section,
    market_review=gz_market_review,
    channel_block=gz_channel_block,
    headline_row=gz_headline_row,
    em_news_row=gz_em_news_row,
    item_row=gz_item_row,
    rows=gz_rows,
    note=gz_note,
    alert=gz_alert,
    status_footer=gz_status_footer,
    # 徽标置于标题黑条下方的白底区域，保留状态与来源信息。
    source_badge=lambda item: gz_source_badge(item),
    ai_badge=lambda: gz_badge("AI 合成", "ai"),
    ai_block=gz_ai_analysis_block,
    sentiment_block=gz_sentiment_block,
    sentiment_empty_block=gz_sentiment_empty_block,
    senti_empty_badge=lambda: gz_badge("样本不足", "warn"),
    policy_block=gz_policy_block,
    panorama_block=gz_panorama_block,
    calendar_block=lambda res, date_str=None: gz_calendar_block(res, date_str=date_str),
    trend_topic_block=gz_trend_topic_block,
    # ---- 量化栏目需要的排版原语（注入给 octopus_quant.render）----
    esc=_esc,
    table=lambda headers, rows, aligns=None: gz_data_table(headers, rows, aligns=aligns),
    sub=gz_subsection,
    meter=lambda value, maximum: gz_meter(value, maximum, cells=5),
    badge=lambda text, kind="ok": gz_badge(text, kind),
    section=gz_section,
    kv=gz_kv_table,
    trend=gz_trend_badge,
    ok_color=GZ_UP, warn_color=GZ_WARN, bad_color=GZ_DOWN,
)


# ============================================================
# Dossier 主题（2026-10-03 新增 · 德国文件 / 档案风 + 包豪斯几何）
# 2026-10-04 换色：浅黄牛皮纸 → 浅灰底 / 黑标题 / 深灰正文 / 荧光绿 + 鲜红
# ------------------------------------------------------------
#   · 页面设计「德国文件」：荧光绿高亮文件夹标签（AKTE 01 …）、2px 黑色粗线、
#     打字机等宽文件编号、档案元信息表（DATE / QUELLEN / SIGNATUR）、
#     鲜红 RESEARCH 印章、ENDE DER AKTE 档案尾注；
#   · 色盘（2026-10-04 定稿）：
#       ‑ 底：浅灰画布 #F1F1F1（斑马底 #E4E4E4、分隔线 #C9C9C9，全部中性灰，
#         不再有任何暖黄 / 牛皮纸色）；
#       ‑ 字：标题纯黑 #000000，正文深灰 #333333，次要信息 #4A4A4A（7.8:1）；
#       ‑ 突出色只有两支：荧光绿 #39FF14 与 鲜红 #FF1F1F。
#         两支都按「填充用原色、落字用深一档」分档使用：
#           · 填充 / 描边 / 图形 → 荧光绿 #39FF14（配黑字，对比度 15.5:1）、
#             鲜红 #FF1F1F（印章描边、警示描边）；
#           · 文字与几何字形 → 深绿 #0A6724、深红 #C01010；在画布、斑马灰、
#             荧光绿强调底上均 ≥4.6:1，覆盖嵌套底色后仍守 WCAG AA。
#   · 文字排版：DIN 风格系统字栈（不加载远程字体，中文回退系统 CJK 字）
#     + 等宽文件编号，字距拉开的等宽 kicker，强粗细对比；
#   · 图标设计「包豪斯」：圆 / 三角 / 方 / 菱 × 深绿 / 深红 / 黑字色的几何组合，
#     纯 Unicode 字形；荧光原色只用作填充和描边，保证浅灰底上清晰可辨。
#   · 实现：内容块复用 guizang 研报渲染器；_dossier_palette 上下文在渲染期间
#     临时换掉 GZ_* 全局色变量（渲染器在调用时读取全局，故整体换色生效），
#     栏目头 / 刊头 / 尾注为本主题专属。内容结构、栏目顺序、推送分条逻辑不变。
# ============================================================
# ---- 浅灰色阶（画布 / 斑马底 / 分隔线）----
D_PAPER = "#F1F1F1"        # 浅灰画布（页面底；黑条上的反白字同色，> #E8 不会被灰字强制改写）
D_TAB = "#39FF14"          # 文件夹标签底：荧光绿高亮块，配黑字（15.5:1）
D_TAB_HAIR = "#000000"     # 标签描边（黑）
D_HAIR = "#C9C9C9"         # 栏目分割线
D_HAIR_SOFT = "#DDDDDD"    # 行间细分隔线
D_ZEBRA = "#E4E4E4"        # 段落交替底（比画布深一档的浅灰）
# ---- 文字：黑标题 + 深灰正文 ----
D_INK = "#333333"          # 正文（深灰，浅灰底上 11.2:1）
D_INK_STRONG = "#000000"   # 标题 / 最高强调（纯黑）
D_GRAY = "#4A4A4A"         # 次要深灰（标签 / 表头 / 脚注，7.8:1）
D_BLACK = "#000000"        # 粗线 / 黑条（标题条与 2px 粗线）
# ---- 突出色：荧光绿 + 鲜红（各分「填充原色 / 落字深档」两档）----
D_GREEN = "#39FF14"        # 荧光绿：高亮块填充色（块内用黑字，15.5:1）；浅底不直接落字
D_GREEN_INK = "#0A6724"    # 落字深绿：在浅灰、斑马灰、荧光绿底均 ≥5.2:1
D_GREEN_DEEP = "#0A5C20"   # 更深一档绿（链接按下 / 需要更重时）
D_RED = "#FF1F1F"          # 鲜红：填充 / 描边；不直接作为浅底文字色
D_RED_INK = "#C01010"      # 落字深红：在浅灰、斑马灰、荧光绿底均 ≥4.6:1
# 字栈：DIN 风格系统字（不加载远程字体）；等宽用打字机 Courier 系（档案卷宗感）
D_FONT = ("'DIN Alternate','Bahnschrift','Avenir Next Condensed','Arial Narrow',"
          "-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB',"
          "'Microsoft YaHei',sans-serif")
D_MONO = "'Courier New',Courier,'SF Mono',Menlo,monospace"

# 渲染期间临时替换的 GZ_* 全局色变量（guizang 渲染器在调用时读全局 → 整体换色）
_DOSSIER_GZ_SWAP = {
    "GZ_PAPER": D_PAPER,
    "GZ_PAPER_TINT": D_PAPER,
    "GZ_KLEIN": D_GREEN_INK,
    "GZ_KLEIN_DEEP": D_GREEN_DEEP,
    # 结论 / AI 判定块底：荧光绿高亮块，深绿 / 深红落字版在该底上均过 AA。
    "GZ_KLEIN_WASH": D_GREEN,
    "GZ_INK": D_INK,
    "GZ_INK_STRONG": D_INK_STRONG,
    "GZ_DARK_GRAY": D_GRAY,
    "GZ_META": D_GRAY,
    "GZ_FAINT": D_GRAY,
    "GZ_HAIR": D_HAIR,
    "GZ_HAIR_SOFT": D_HAIR_SOFT,
    "GZ_HAIR_INK": D_HAIR,
    "GZ_ZEBRA": D_ZEBRA,
    "GZ_CREAM": D_PAPER,
    "GZ_INK_TINT": D_PAPER,
    "GZ_UP": D_GREEN_INK, "GZ_DOWN": D_RED_INK, "GZ_FLAT": D_GRAY,
    "GZ_UP_INK": D_GREEN_INK, "GZ_DOWN_INK": D_RED_INK, "GZ_FLAT_INK": D_GRAY,
    "GZ_WARN": D_GRAY, "GZ_WARN_INK": D_GRAY,
    "GZ_PRIMARY": D_GREEN_INK, "GZ_PRIMARY_HOVER": D_GREEN_DEEP,
    "GZ_PRIMARY_LIGHT": D_GREEN,
    "GZ_NEON": D_GREEN_INK,
    "GZ_FONT": D_FONT,
    "GZ_SERIF": D_FONT,
    "GZ_SANS": D_FONT,
    "GZ_MONO": D_MONO,
}


class _dossier_palette:
    """渲染 dossier 日报期间临时换 GZ_* 色变量；退出时逐位还原。

    同时临时覆盖 GUIZANG_KIT / DOSSIER_KIT 的 ok / warn / bad 三个色槽：
    行情复盘栏目里的 MACD 量化表是按 GUIZANG_KIT 渲染的（历史实现），
    色槽若不一起换，档案页里就会漏出克莱因蓝 —— 这一漏色在 2026-10-04 换色时
    由 tests/test_pipeline.py::test_dossier_palette_and_no_old_colors_leak 看守。
    """

    _KIT_SLOTS = ("ok_color", "warn_color", "bad_color")
    _KIT_COLORS = {"ok_color": D_GREEN_INK, "warn_color": D_GRAY, "bad_color": D_RED_INK}

    def __enter__(self):
        self._saved = {k: globals()[k] for k in _DOSSIER_GZ_SWAP}
        for k, v in _DOSSIER_GZ_SWAP.items():
            globals()[k] = v
        self._saved_kit = {}
        for kit in (GUIZANG_KIT, DOSSIER_KIT):
            self._saved_kit[id(kit)] = (kit, {s: getattr(kit, s) for s in self._KIT_SLOTS})
            for slot, value in self._KIT_COLORS.items():
                setattr(kit, slot, value)
        return self

    def __exit__(self, exc_type, exc, tb):
        for k, v in self._saved.items():
            globals()[k] = v
        for kit, slots in self._saved_kit.values():
            for slot, value in slots.items():
                setattr(kit, slot, value)
        return False


# 包豪斯图标：kicker → (主字形, 主色, 副字形, 副色)。
# 形状只用圆 ● / 三角 ▲▼▶ / 方 ■□ / 菱 ◆ / 半圆 ◐◍◎ 等几何字形；
# 颜色只用落字深绿 / 落字深红 / 黑；原色只作荧光填充与描边，确保几何字形在浅灰底上清晰。
DOSSIER_ICONS = {
    "POETRY & SEA": ("◆", D_GREEN_INK, "●", D_RED_INK),
    "RETAIL SENTIMENT": ("◉", D_RED_INK, "●", D_GREEN_INK),
    "FORECAST": ("▲", D_GREEN_INK, "●", D_RED_INK),
    "SUMMARY": ("■", D_BLACK, "▲", D_RED_INK),
    "MARKET REVIEW": ("▲", D_RED_INK, "■", D_BLACK),
    "WEEKLY FORECAST": ("■", D_GREEN_INK, "▲", D_RED_INK),
    "HK PROBABILITY": ("◍", D_GREEN_INK, "●", D_RED_INK),
    "LIQUIDITY FLOW": ("≈", D_GREEN_INK, "●", D_BLACK),
    "SECTOR ROTATION": ("◐", D_GREEN_INK, "▲", D_RED_INK),
    "INDUSTRY ROTATION": ("◆", D_RED_INK, "■", D_BLACK),
    "ECON CALENDAR": ("▦", D_GREEN_INK, "●", D_RED_INK),
    "POLICY SHOCK": ("§", D_RED_INK, "■", D_BLACK),
    "DATA AUDIT": ("✓", D_GREEN_INK, "■", D_RED_INK),
    "TREND TRACKING": ("◉", D_GREEN_INK, "▲", D_RED_INK),
    "SHORT CARD": ("▲", D_RED_INK, "●", D_GREEN_INK),
    "STRATEGY READ": ("◆", D_GREEN_INK, "■", D_RED_INK),
    "GLOBAL HEADLINES": ("▤", D_GREEN_INK, "▲", D_RED_INK),
    "EASTMONEY WIRE": ("!", D_RED_INK, "■", D_BLACK),
    "NEWS SENTIMENT": ("◆", D_RED_INK, "●", D_GREEN_INK),
    "MEDIA RISK": ("!", D_RED_INK, "▲", D_BLACK),
    "QUANT STRATEGY": ("◆", D_GREEN_INK, "■", D_RED_INK),
    "QUANT POLICY": ("◉", D_RED_INK, "■", D_BLACK),
    "FED TREND": ("$", D_GREEN_INK, "●", D_RED_INK),
    "GEO TREND": ("◎", D_RED_INK, "■", D_BLACK),
    "STRATEGY OVERVIEW": ("▣", D_GREEN_INK, "●", D_RED_INK),
    "STRATEGY EQUITY": ("▲", D_RED_INK, "●", D_GREEN_INK),
    "STRATEGY BOND": ("▬", D_GREEN_INK, "■", D_BLACK),
    "STRATEGY CTA": ("↗", D_RED_INK, "■", D_BLACK),
    "STRATEGY ARBITRAGE": ("◇", D_GREEN_INK, "▲", D_RED_INK),
    "AI READ": ("●", D_GREEN_INK, "▲", D_RED_INK),
    "HK GURU CHANNELS": ("▶", D_GREEN_INK, "■", D_RED_INK),
}


def dossier_icon(kicker_en):
    """栏目标题前的包豪斯几何图标（主字形 + 小副字形，两色）。"""
    g1, c1, g2, c2 = DOSSIER_ICONS.get(str(kicker_en or "").strip().upper(),
                                       ("●", D_GREEN_INK, "■", D_BLACK))
    return (f'<span style="color:{c1};font-size:13px;">{g1}</span>'
            f'<span style="color:{c2};font-size:9px;">{g2}</span>'
            f'<span style="padding-left:6px;"></span>')


def dossier_stamp(text="RESEARCH · 非投资建议"):
    """档案鲜红章：描边方章，等宽字距拉开（入门版不出过程性印章）。

    描边用鲜红原色 #FF1F1F，章面文字用落字深红 #C01010（浅灰 / 斑马 / 荧光底均过 AA）。
    """
    if PLAIN():
        return ""
    return (f'<span style="display:inline-block;border:1px solid {D_RED};'
            f'color:{D_RED_INK};font-family:{D_MONO};font-size:10px;letter-spacing:0.18em;'
            f'padding:1px 6px;margin-right:8px;">{_esc(text)}</span>')


def dossier_section(num, kicker_en, title, content, badge_html="", caption=""):
    """Dossier 栏目头：荧光绿高亮标签（AKTE 编号 + 等宽 kicker）→ 标题（含包豪斯图标）
    → 红章 / 徽标 / 口径。与 guizang 版同一套内容，只换卷宗式栏目头。

    保留 <h2> 标题结构：分条推送的「承接上条」横幅靠它取栏目名，不能省。
    """
    content = content or ""
    if content.lstrip().startswith("<tr"):
        content = (f'<table width="100%" cellpadding="0" cellspacing="0" '
                   f'style="width:100%!important;border-collapse:collapse;'
                   f'font-size:{GZ_FS_TABLE}px;color:{D_INK}">{content}</table>')
    content = _gz_zebra_bands(content)
    meta_bits = [x for x in (badge_html, caption) if x]
    meta = (f'<div style="color:{D_GRAY};font-size:{GZ_FS_META}px;'
            f'padding-top:4px">{" · ".join(meta_bits)}</div>') if meta_bits else ""
    head = (
        f'<div style="margin-top:26px;border-top:2px solid {D_BLACK};'
        f'color:{D_INK};background:{D_PAPER}">'
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{D_PAPER}" '
        f'style="width:100%!important;border-collapse:collapse;background:{D_PAPER};color:{D_INK};">'
        f'<tr><td valign="top" style="padding:0;color:{D_INK};">'
        # 文件夹标签：挂在粗线下的荧光绿高亮块，配黑字（15.5:1）
        f'<div style="display:inline-block;background:{D_TAB};'
        f'border:1px solid {D_TAB_HAIR};border-bottom:none;'
        f'padding:3px 10px 2px;margin-top:-1px;font-family:{D_MONO};font-size:10px;'
        f'letter-spacing:0.16em;color:{D_INK_STRONG};">'
        f'AKTE {num} · {_esc(kicker_en)}</div>'
        # 标题行：包豪斯图标 + DIN 标题
        f'<div style="padding:8px 0 0;">'
        f'<h2 style="margin:0;font-size:{GZ_FS_SECTION}px;font-weight:700;'
        f'color:{D_INK_STRONG};letter-spacing:0.01em;">'
        f'{dossier_icon(kicker_en)}{_esc(title)}</h2>'
        f'<div style="padding-top:3px;">{dossier_stamp()}{meta}</div>'
        f'</div></td></tr></table>'
    )
    body = f'{content}</div>'
    return head + SECTION_BODY_MARK + body


def _is_guizang_like(kit):
    """guizang / dossier / forum / lime 共用同一套研报渲染器与取色分支。

    dossier 是浅色档案版，forum 是暗色社区版，lime 是白底圆角卡片 + 荧光绿强调版：
    内容块都由 guizang 渲染器产出，只是渲染期间由各自的 palette 上下文换掉 GZ_* 全局色。
    """
    return (kit is GUIZANG_KIT or kit is DOSSIER_KIT
            or kit is FORUM_KIT or kit is LIME_KIT)


# theme：跨栏「同子栏合并」按主题判定 12 栏板块热力的切片口径（见 _panorama_heat_selection）。
DOSSIER_KIT = _RenderKit(
    theme="dossier",
    market_section=gz_market_section,
    market_review=gz_market_review,
    channel_block=gz_channel_block,
    headline_row=gz_headline_row,
    em_news_row=gz_em_news_row,
    item_row=gz_item_row,
    rows=gz_rows,
    note=gz_note,
    alert=gz_alert,
    status_footer=gz_status_footer,
    source_badge=lambda item: gz_source_badge(item),
    ai_badge=lambda: gz_badge("AI 合成", "ai"),
    ai_block=gz_ai_analysis_block,
    sentiment_block=gz_sentiment_block,
    sentiment_empty_block=gz_sentiment_empty_block,
    senti_empty_badge=lambda: gz_badge("样本不足", "warn"),
    policy_block=gz_policy_block,
    panorama_block=gz_panorama_block,
    calendar_block=lambda res, date_str=None: gz_calendar_block(res, date_str=date_str),
    trend_topic_block=gz_trend_topic_block,
    # ---- 量化栏目需要的排版原语（注入给 octopus_quant.render）----
    esc=_esc,
    table=lambda headers, rows, aligns=None: gz_data_table(headers, rows, aligns=aligns),
    sub=gz_subsection,
    # meter 的字色在调用时取当前（已换色的）全局，避免默认参数固化克莱因蓝
    meter=lambda value, maximum: gz_meter(value, maximum, cells=5,
                                          lit=GZ_KLEIN, off=GZ_FAINT),
    badge=lambda text, kind="ok": gz_badge(text, kind),
    section=dossier_section,
    kv=gz_kv_table,
    trend=gz_trend_badge,
    ok_color=GZ_UP, warn_color=GZ_WARN, bad_color=GZ_DOWN,
)


def _dossier_masthead(date_display, date_str, today_n, total, generated_at):
    """Dossier 刊头（卷宗封面）：黑条刊名 + 荧光绿档号 → 大标题（黑）+ 几何图标 → 档案元信息表 → 鲜红章。"""
    file_no = f"AKT-{date_str}"
    # 标题后的几何记号用落字色：原荧光绿方块在浅灰底上几乎不可辨。
    icon_block = (f'<span style="color:{D_GREEN_INK};font-size:15px;">■</span>'
                  f'<span style="color:{D_RED_INK};font-size:12px;padding-left:2px;">●</span>'
                  f'<span style="color:{D_BLACK};font-size:10px;padding-left:2px;">▲</span>')

    def _meta_cell(label, value, last=False):
        border_r = "" if last else f'border-right:1px solid {D_HAIR};'
        return (f'<td style="border-top:1px solid {D_BLACK};border-bottom:1px solid {D_BLACK};'
                f'{border_r}padding:5px 8px;vertical-align:bottom;">'
                f'<div style="font-family:{D_MONO};font-size:9px;letter-spacing:0.18em;'
                f'color:{D_GRAY};">{label}</div>'
                f'<div style="font-family:{D_MONO};font-size:12px;font-weight:700;'
                f'color:{D_INK_STRONG};padding-top:2px;">{value}</div></td>')

    meta_table = (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="width:100%!important;border-collapse:collapse;margin:10px 0 0;">'
        f'<tr>{_meta_cell("DATE · 日期", _esc(str(date_display)))}'
        f'{_meta_cell("QUELLEN · 当天源", f"{today_n}/{total}")}'
        f'{_meta_cell("SIGNATUR · 档号", _esc(file_no), last=True)}</tr></table>')
    # 印章是装饰性「研究副本」章（非免责文字本身）：入门版与栏目章一致不出
    stamp = "" if PLAIN() else (
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{D_PAPER}" '
        f'style="width:100%!important;border-collapse:collapse;background:{D_PAPER};color:{D_RED_INK};">'
        f'<tr><td align="right" style="padding-top:8px;color:{D_RED_INK};">'
        f'<span style="display:inline-block;border:2px solid {D_RED};color:{D_RED_INK};'
        f'font-family:{D_MONO};font-size:10px;font-weight:700;letter-spacing:0.22em;'
        f'padding:3px 8px;">内部资料 · 非投资建议</span></td></tr></table>')
    return (
        f'<div style="padding:4px 0 0;color:{D_INK};background:{D_PAPER}">'
        # 卷宗黑条刊名（table 布局：微信清洗链路上比 flex 稳）+ 荧光绿档号高亮块
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="width:100%!important;border-collapse:collapse;background:{D_BLACK};">'
        f'<tr><td style="padding:5px 8px;font-family:{D_MONO};font-size:11px;font-weight:700;'
        f'letter-spacing:0.22em;color:{D_PAPER};">OCTOPUS · Fresh-keeping</td>'
        f'<td align="right" style="padding:5px 8px;font-family:{D_MONO};font-size:10px;'
        f'letter-spacing:0.14em;color:{D_PAPER};">'
        f'<span style="background:{D_GREEN};color:{D_INK_STRONG};padding:1px 6px;">'
        f'{_esc(file_no)}</span></td></tr></table>'
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{D_PAPER}" '
        f'style="width:100%!important;border-collapse:collapse;background:{D_PAPER};color:{D_INK};">'
        f'<tr><td valign="top" style="padding-top:10px;color:{D_INK};">'
        f'<h1 style="margin:0;font-size:{GZ_FS_DISPLAY}px;font-weight:900;'
        f'color:{D_INK_STRONG};letter-spacing:0.01em;line-height:1.3;">'
        f'{_esc(REPORT_TITLE)} {icon_block}</h1>'
        f'<div style="color:{D_GRAY};font-size:{GZ_FS_META}px;line-height:1.7;'
        f'padding-top:6px;">{_esc(REPORT_TAGLINE)} · 更新于 {_esc(generated_at)}</div>'
        f'</td></tr></table>{meta_table}{stamp}</div>'
    )


def generate_report_dossier(data, date_display, date_str, sentiment_history=None,
                            policy_result=None, news_corpus=None):
    """Dossier 排版（德国文件 + 包豪斯）：卷宗封面 + 文件夹标签栏目 + 档案尾注。

    内容块与 guizang 同源（同一套研报渲染器），只在 _dossier_palette 渲染期间换成
    浅灰底 / 黑标题 / 深灰正文 / 荧光绿 + 鲜红突出色；栏目顺序、分条标记、推送门禁全部不变。
    整页拼装与灰字强制都在换色期间完成：_enforce_dark_gray_font 会为缺 color 的
    容器补前景色（取当前全局 GZ_INK*），并把浅灰文字统一为当前 GZ_DARK_GRAY。
    """
    with _dossier_palette():
        # ok / warn / bad 三个色槽由 _dossier_palette 统一换（含行情复盘里按
        # GUIZANG_KIT 渲染的量化表），退出时还原，不再在这里临时绑定、遗留全局态
        parts = _collect_report_parts(data, DOSSIER_KIT,
                                      sentiment_history=sentiment_history,
                                      date_str=date_str,
                                      policy_result=policy_result,
                                      news_corpus=news_corpus)
        sections = parts["sections"]
        # 栏目头也要在换色期间拼（斑马底等读的是当前全局色）
        content_html = "".join(
            PART_BREAK_MARK + DOSSIER_KIT.section(f"{i:02d}", kicker, title, content, badge, caption)
            for i, (kicker, title, content, badge, caption) in enumerate(sections[1:], 1))
        opening = _poetry_sea_section(parts, DOSSIER_KIT)
        first_section = (opening + PART_BREAK_MARK if opening else "") + DOSSIER_KIT.section("00", *sections[0])
        total = parts["total"]
        today_n = parts["today_n"]
        generated_at = _now()
        # 页脚：档案尾注（入门版只留免责一句）
        footer_text = (
            "仅供参考，非投资建议 · 数据来自公开来源，未抓到内容的栏目自动缺席。" if PLAIN() else
            f'德国档案排版（Dossier） · 浅灰底 + 黑标题 + 深灰正文 · 突出色 荧光绿 {D_GREEN} / 鲜红 {D_RED} · '
            '涨 ▲ / 跌 ▼ 同时给符号与正负号，不只靠颜色区分<br>\n'
            '数据来自公开来源，未抓到内容的栏目自动缺席，不以历史内容充数。')
        masthead = _dossier_masthead(date_display, date_str, today_n, total, generated_at)
        html = _dossier_html_frame(masthead, first_section, content_html, footer_text,
                                   date_str, generated_at, today_n, total)
        return _enforce_dark_gray_font(html, dark_gray=GZ_DARK_GRAY)


def _dossier_html_frame(masthead, first_section, content_html, footer_text,
                        date_str, generated_at, today_n, total):
    """Dossier 整页外壳（纯内联样式；卷宗封面 + 分条标记 + 档案尾注）。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<meta name="octopus-report-date" content="{date_str}">
<meta name="octopus-generated-at" content="{generated_at}">
<meta name="octopus-today-sources" content="{today_n}">
<meta name="octopus-total-sources" content="{total}">
<meta name="octopus-theme" content="dossier">
<meta name="description" content="{_esc(REPORT_TAGLINE)}">
<title>{REPORT_TITLE}</title>
</head>
<body bgcolor="{D_PAPER}" style="margin:0;padding:0;background:{D_PAPER};color:{D_INK};font-family:{D_FONT};font-size:{GZ_FS_BODY}px;line-height:1.75;color-scheme:light;-webkit-text-size-adjust:100%;word-break:break-word;overflow-wrap:break-word;">
<div style="max-width:980px;margin:0 auto;padding:16px 8px 0;background:{D_PAPER};color:{D_INK};font-family:{D_FONT};font-size:{GZ_FS_BODY}px;line-height:1.75;color-scheme:light;-webkit-text-size-adjust:100%;word-break:break-word;overflow-wrap:break-word;">

{masthead}

{PART_BREAK_MARK}{first_section}
<div id="report"></div>
{content_html}

{DOC_FOOT_MARK}
<div style="margin-top:26px;border-top:2px solid {D_BLACK};">
<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{D_PAPER}" style="width:100%!important;border-collapse:collapse;background:{D_PAPER};color:{D_INK};">
<tr><td valign="top" style="padding:12px 0 30px;color:{D_INK};">
<div style="font-family:{D_MONO};font-size:10px;letter-spacing:0.24em;color:{D_INK_STRONG};">ENDE DER AKTE · 档案结束</div>
<div style="color:{D_GRAY};font-size:11px;line-height:1.8;padding-top:6px;">
{footer_text}
</div>
</td></tr></table>
</div>

</div>
</body>
</html>"""


# ============================================================
# 论坛暗色主题 forum（可切换主题）
# ------------------------------------------------------------
# 设计语言（用户提供的暗色社区仪表盘参考稿）：
#  · 底色 #1C1C1E（页面画布）/ #2C2C2E（卡片容器）/ #232325（卡内条纹）
#    / #3A3A3C（控件与内嵌块）
#  · 1px rgba(255,255,255,0.08) 描边 + 8~14px 圆角，内容一律装进卡片
#  · 正文近白 #F2F2F7、标题纯白 #FFFFFF、次要信息中灰 #A1A1AA
#  · 彩色微型图标砖：紫 ⚡ / 红 🔥 / 红 📈 / 紫 🤖 / 橙 📄 / 青 📅
#  · 区块小标题「大写 + 拉开字距」（tracking-wider）；按钮 / 胶囊用
#    「顶亮渐变 + 浅色内描边 + 柔和投影」做出轻微立体按压感
#  · 所有可见文字在 #1C1C1E / #2C2C2E 上都 ≥ WCAG AA 4.5:1（tests 看守）
# 2026-10-06 换色（用户定稿）：
#  · 点缀文字色 闪电黄 #FFD60A → 落字紫 #D8B4FE（栏目编号 / 微标题 / 强调数值 /
#    图标砖 / 结论块左边条 / 分条横幅统一走这一支；深档 #C77DFF 用于按下与更重的强调）。
#    纯正克莱因蓝 #002FA7 在暗底只有 1.3:1（看不清）、荧光绿 #39FF14 会与跌色
#    #32D74B 撞色，两支均不落字；紫色是暗底上既够亮又不占涨跌语义的一支。
#  · 涨跌改 A 股口径：涨 ▲ = 落字红 #FF6B6B、跌 ▼ = 落字绿 #32D74B（原为绿涨红跌），
#    符号 ▲▼■ 与颜色双编码不变；点缀紫因此不再和任何涨跌语义色冲突。
# 实现：内容块复用 guizang 研报渲染器（同一套 _collect_report_parts），
#       渲染期间由 _forum_palette 上下文整体换色；刊头 / 栏目卡 / 尾注为本主题专属。
#       纯内联样式，无 <style> / class / 远程图片；推送分条与推送门禁逻辑完全不变。
# ============================================================
F_BG = "#1C1C1E"           # 页面画布（深灰，不是纯黑）
F_CARD = "#2C2C2E"         # 卡片容器
F_STRIPE = "#232325"       # 卡内条纹 / 顶栏（比卡片深一档）
F_CONTROL = "#3A3A3C"      # 控件块 / 顶亮渐变的高光端
F_HAIR_SOLID = "#3A3A3C"   # 1px 描边的纯色兜底（不支持 rgba 的客户端）
F_HAIR = "rgba(255,255,255,0.08)"   # 规范要求的 1px 细描边
F_INK = "#F2F2F7"          # 正文近白
F_INK_STRONG = "#FFFFFF"   # 标题纯白
F_MUTED = "#A1A1AA"        # 次要信息中灰（卡片上 5.4:1）
F_ON_FILL = "#1C1C1E"      # 亮色填充块上的深色字（配紫 / 绿 / 青底）
F_ACCENT = "#D8B4FE"       # 主强调（点缀文字色）：落字紫，卡片上 7.9:1
F_ACCENT_DEEP = "#C77DFF"  # 紫加深：链接按下 / 更重的强调，卡片上 5.2:1（仍过 AA）
F_RED = "#FF6B6B"          # 落字红（卡片上 5.0:1）｜2026-10-06 起＝涨 ▲（A 股红涨）
F_RED_FILL = "#FF453A"     # 填充红：图标 / 描边（只做填充，不落小字）
F_GREEN = "#32D74B"        # 落字绿（卡片上 7.3:1）｜2026-10-06 起＝跌 ▼（A 股绿跌）
F_PURPLE = "#D8B4FE"       # 落字紫：与点缀色 F_ACCENT 同值，AI / 预判图标与点缀合流
F_PURPLE_FILL = "#BF5AF2"  # 填充紫：图标（只做填充）
F_ORANGE = "#FF9F0A"
F_CYAN = "#64D2FF"
F_BLUE = "#409CFF"         # 链接 / 交互蓝
F_BLUE_DEEP = "#6FB4FF"
F_WASH = "#241A2E"         # 结论 / AI 块：深紫底（配紫强调，紫字在上 9.4:1）
# 暗色主题允许出现的文字色（其余一律由 _enforce_dark_mode_font 归一化）
# F_PURPLE 与点缀色 F_ACCENT 同值 #D8B4FE（白名单里去重后只有一支紫），两支都列出
# 只为读代码时看得清「点缀紫」与「AI 紫」是同一支色。
FORUM_TEXT_ALLOWED = (
    F_INK, F_INK_STRONG, F_MUTED, F_ON_FILL, F_ACCENT, F_ACCENT_DEEP,
    F_RED, F_GREEN, F_PURPLE, F_ORANGE, F_CYAN, F_BLUE, F_BLUE_DEEP,
)
# 字栈：系统无衬线栈（Inter / SF Pro / 苹方优先，不加载远程字体）；等宽用于编号与微标题
F_FONT = ("-apple-system,BlinkMacSystemFont,'Inter','SF Pro Text','PingFang SC',"
          "'Hiragino Sans GB','Microsoft YaHei',sans-serif")
F_MONO = "'SF Mono',Menlo,Consolas,'Courier New',monospace"

# 渲染期间临时替换的 GZ_* 全局色变量（guizang 渲染器在调用时读全局 → 整体换色）
_FORUM_GZ_SWAP = {
    "GZ_PAPER": F_CARD,
    "GZ_PAPER_TINT": F_CARD,
    "GZ_KLEIN": F_ACCENT,
    "GZ_KLEIN_DEEP": F_ACCENT_DEEP,
    "GZ_KLEIN_WASH": F_WASH,
    "GZ_INK": F_INK,
    "GZ_INK_STRONG": F_INK_STRONG,
    "GZ_DARK_GRAY": F_MUTED,
    "GZ_META": F_MUTED,
    "GZ_FAINT": F_MUTED,
    "GZ_HAIR": F_HAIR_SOLID,
    "GZ_HAIR_SOFT": "#323234",
    "GZ_HAIR_INK": F_HAIR_SOLID,
    "GZ_ZEBRA": F_STRIPE,
    "GZ_CREAM": F_INK,
    "GZ_INK_TINT": F_INK,
    # 涨跌走 A 股口径（2026-10-06 起）：涨 ▲ 落字红、跌 ▼ 落字绿
    "GZ_UP": F_RED, "GZ_DOWN": F_GREEN, "GZ_FLAT": F_MUTED,
    "GZ_UP_INK": F_RED, "GZ_DOWN_INK": F_GREEN, "GZ_FLAT_INK": F_MUTED,
    "GZ_WARN": F_ORANGE, "GZ_WARN_INK": F_ORANGE,
    "GZ_PRIMARY": F_BLUE, "GZ_PRIMARY_HOVER": F_BLUE_DEEP,
    "GZ_PRIMARY_LIGHT": F_CONTROL,
    "GZ_NEON": F_PURPLE,
    "GZ_FONT": F_FONT,
    "GZ_SERIF": F_FONT,
    "GZ_SANS": F_FONT,
    "GZ_MONO": F_MONO,
}


class _forum_palette:
    """渲染 forum 日报期间临时换 GZ_* 色变量（退出时逐位还原）。

    与 _dossier_palette 同构：MACD 量化表等历史实现按 GUIZANG_KIT 渲染，
    kit 的 ok / warn / bad 三个色槽必须一起换，否则浅色研报的克莱因蓝 /
    深灰会漏进暗色卡片。由 tests/test_pipeline.py::ForumThemeTests 看守。
    """

    _KIT_SLOTS = ("ok_color", "warn_color", "bad_color")
    # ok / bad 跟着涨跌口径走：ok（偏多 / 上行）＝红，bad（偏空 / 下行）＝绿
    _KIT_COLORS = {"ok_color": F_RED, "warn_color": F_ORANGE, "bad_color": F_GREEN}

    def __enter__(self):
        self._saved = {k: globals()[k] for k in _FORUM_GZ_SWAP}
        for k, v in _FORUM_GZ_SWAP.items():
            globals()[k] = v
        self._saved_kit = {}
        for kit in (GUIZANG_KIT, FORUM_KIT):
            self._saved_kit[id(kit)] = (kit, {s: getattr(kit, s) for s in self._KIT_SLOTS})
            for slot, value in self._KIT_COLORS.items():
                setattr(kit, slot, value)
        return self

    def __exit__(self, exc_type, exc, tb):
        for k, v in self._saved.items():
            globals()[k] = v
        for kit, slots in self._saved_kit.values():
            for slot, value in slots.items():
                setattr(kit, slot, value)
        return False


# 彩色微型图标：kicker → (字形, 颜色)。字形用系统 emoji / 几何符号，不用图片与 SVG。
# 2026-10-06 起：点缀色改紫，⚡ 速览类图标随点缀走紫；📈 行情改红（A 股红涨），
# 📊 趋势跟踪改青（避开「绿＝跌」的新语义），✅ 数据核对仍用绿（勾号＝通过，非涨跌）。
FORUM_ICONS = {
    "POETRY & SEA": ("📜", F_PURPLE),
    "RETAIL SENTIMENT": ("💬", F_CYAN),     # Reddit / StockTwits 社区样本
    "FORECAST": ("🔮", F_PURPLE),           # 紫色：预判 / AI
    "SUMMARY": ("📌", F_ORANGE),
    "SHORT CARD": ("⚡", F_ACCENT),
    "MARKET REVIEW": ("📈", F_RED),         # 红色：行情（红涨口径下的上升折线）
    "WEEKLY FORECAST": ("🗓", F_CYAN),
    "HK PROBABILITY": ("🎲", F_PURPLE),
    "LIQUIDITY FLOW": ("💧", F_CYAN),
    "SECTOR ROTATION": ("🌀", F_ORANGE),
    "INDUSTRY ROTATION": ("🧭", F_ORANGE),
    "ECON CALENDAR": ("📅", F_CYAN),
    "POLICY SHOCK": ("📄", F_ORANGE),       # 橙色文档：政策
    "DATA AUDIT": ("✅", F_GREEN),          # 绿色勾号：核对通过（与涨跌无关）
    "TREND TRACKING": ("📊", F_CYAN),       # 青色：趋势跟踪（绿已让给「跌」）
    "STRATEGY READ": ("🧮", F_PURPLE),
    "GLOBAL HEADLINES": ("🌏", F_CYAN),
    "EASTMONEY WIRE": ("📰", F_ORANGE),
    "NEWS SENTIMENT": ("🔥", F_RED),   # 红色火焰：热度
    "MEDIA RISK": ("🚨", F_ORANGE),    # 风险事实与分级处置
    "QUANT STRATEGY": ("🤖", F_PURPLE),
    "QUANT POLICY": ("📄", F_ORANGE),
    "FED TREND": ("💵", F_GREEN),
    "GEO TREND": ("🌏", F_CYAN),
    "STRATEGY OVERVIEW": ("📊", F_PURPLE),
    "STRATEGY EQUITY": ("📈", F_RED),
    "STRATEGY BOND": ("🏦", F_GREEN),
    "STRATEGY CTA": ("🌊", F_ORANGE),
    "STRATEGY ARBITRAGE": ("⚖️", F_CYAN),
    "AI READ": ("🤖", F_PURPLE),
    "HK GURU CHANNELS": ("📺", F_RED),
}
# 图标砖配色：主色 → (砖底, 砖描边)，深色低饱和，衬托高饱和字形
FORUM_TILE_TINT = {
    F_RED_FILL: ("#2E1B1C", "#5C2A2C"),
    F_RED: ("#2E1B1C", "#5C2A2C"),
    F_GREEN: ("#152A1B", "#22522F"),
    F_PURPLE_FILL: ("#291D33", "#4B2F61"),
    F_PURPLE: ("#291D33", "#4B2F61"),      # ＝点缀色 F_ACCENT 的图标砖
    F_ORANGE: ("#2E2413", "#5C3F12"),
    F_CYAN: ("#132A32", "#1F4C5C"),
}
# 认不出主色时的兜底砖：跟点缀色同族（深紫底 + 紫描边）
FORUM_TILE_FALLBACK = ("#291D33", "#4B2F61")


def forum_icon(kicker_en):
    """彩色微型图标砖：圆角小方块 + 高饱和字形（纯 Unicode，无图片 / SVG）。"""
    glyph, color = FORUM_ICONS.get(str(kicker_en or "").strip().upper(), ("●", F_ACCENT))
    wash, border = FORUM_TILE_TINT.get(color, FORUM_TILE_FALLBACK)
    return (f'<span style="display:inline-block;width:22px;height:22px;text-align:center;'
            f'border-radius:7px;background:{wash};border:1px solid {border};'
            f'color:{color};font-size:12px;vertical-align:middle;">{glyph}</span>')


def forum_stamp(text="非投资建议"):
    """暗色胶囊标签（入门版不出过程性标签）。"""
    if PLAIN():
        return ""
    return (f'<span style="display:inline-block;padding:1px 9px;border-radius:999px;'
            f'border:1px solid {F_HAIR};background:{F_STRIPE};color:{F_MUTED};'
            f'font-size:10px;line-height:17px;">{_esc(text)}</span>')


def forum_chip(label, value, accent=F_INK_STRONG):
    """顶亮渐变胶囊：左小写标签（拉开字距）+ 右高对比数值，轻微立体按压感。"""
    return (f'<span style="display:inline-block;margin:5px 6px 0 0;padding:3px 10px;'
            f'border-radius:9px;border:1px solid {F_HAIR};background:{F_STRIPE};'
            f'background:linear-gradient(180deg,{F_CONTROL} 0%,{F_STRIPE} 100%);'
            f'box-shadow:inset 0 1px 0 rgba(255,255,255,0.06),0 1px 2px rgba(0,0,0,0.45);'
            f'color:{F_MUTED};font-size:11px;line-height:18px;white-space:nowrap;">'
            f'<span style="color:{F_MUTED};font-family:{F_MONO};font-size:10px;'
            f'letter-spacing:0.1em;">{_esc(label)}</span> '
            f'<b style="color:{accent};">{_esc(value)}</b></span>')


def forum_section(num, kicker_en, title, content, badge_html="", caption=""):
    """Forum 栏目卡：彩色微图标 + 大写微标题（字距拉开）+ 纯白标题 → 暗色卡片正文。

    保留 <h2> 标题结构：分条推送的「承接上条」横幅靠它取栏目名，不能省。
    """
    content = content or ""
    if content.lstrip().startswith("<tr"):
        content = (f'<table width="100%" cellpadding="0" cellspacing="0" '
                   f'style="width:100%!important;border-collapse:collapse;'
                   f'font-size:{GZ_FS_TABLE}px;color:{F_INK}">{content}</table>')
    content = _gz_zebra_bands(content)
    meta_bits = [x for x in (badge_html, caption) if x]
    meta = (f'<div style="color:{F_MUTED};font-size:{GZ_FS_META}px;padding-top:5px">'
            f'{" · ".join(meta_bits)}</div>') if meta_bits else ""
    # 微标题行与标题同表不同行：图标砖 + 大写 kicker 居左，编号胶囊居右，
    # 标题行整行合并——既少一层表、也让 h2 始终落在表格内（微信排版稳定）。
    head = (
        f'<div style="margin-top:14px;border:1px solid {F_HAIR};border-radius:14px;'
        f'background:{F_CARD};color:{F_INK};overflow:hidden;">'
        f'<table width="100%" style="border-collapse:collapse;color:{F_INK};">'
        f'<tr><td style="padding:10px 0 0 10px;color:{F_MUTED};">'
        f'{forum_icon(kicker_en)}'
        f'<span style="padding-left:8px;font-family:{F_MONO};font-size:10px;'
        f'letter-spacing:0.18em;color:{F_MUTED};">{_esc(kicker_en)}</span>'
        + f'</td><td align="right" style="padding:10px 10px 0 0;color:{F_MUTED};">'
        f'<span style="font-family:{F_MONO};font-size:10px;color:{F_MUTED};'
        f'letter-spacing:0.08em;">#{num}</span>'
        f'</td></tr>'
        f'<tr><td colspan="2" style="padding:0 10px 11px;color:{F_INK};">'
        f'<h2 style="margin:8px 0 0;font-size:{GZ_FS_SECTION}px;font-weight:700;'
        f'color:{F_INK_STRONG};">{_esc(title)}</h2>'
        f'{meta}</td></tr></table>'
    )
    body = f'{content}</div>'
    return head + SECTION_BODY_MARK + body


def _forum_masthead(date_display, date_str, today_n, total, generated_at):
    """Forum 刊头（社区面板首页）：状态条（LIVE + 日期）+ 大标题 + 分段控件式元信息。"""
    top = (
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{F_STRIPE}" '
        f'style="width:100%!important;border-collapse:collapse;background:{F_STRIPE};'
        f'color:{F_MUTED};">'
        f'<tr><td style="padding:8px 14px;color:{F_MUTED};font-family:{F_MONO};font-size:10px;'
        f'font-weight:700;letter-spacing:0.22em;">OCTOPUS · MARKET QUEST</td>'
        f'<td align="right" style="padding:7px 12px 7px 0;color:{F_MUTED};">'
        f'<span style="display:inline-block;padding:1px 8px;border-radius:999px;'
        f'border:1px solid #4B2F61;background:#291D33;color:{F_ACCENT};'
        f'font-family:{F_MONO};font-size:10px;letter-spacing:0.1em;line-height:17px;">'
        f'● LIVE</span></td></tr></table>')
    # 标题后的三枚记号＝本页配色图例：⚡ 点缀紫 / ▲ 涨红 / ▼ 跌绿（A 股口径）
    icon_block = (f'<span style="color:{F_ACCENT};font-size:14px;">⚡</span>'
                  f'<span style="color:{F_RED};font-size:12px;padding-left:3px;">▲</span>'
                  f'<span style="color:{F_GREEN};font-size:12px;padding-left:3px;">▼</span>')
    stamp = forum_stamp()
    hero = (
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{F_CARD}" '
        f'style="width:100%!important;border-collapse:collapse;background:{F_CARD};'
        f'color:{F_INK};">'
        f'<tr><td valign="top" style="padding:14px 14px 13px;color:{F_INK};">'
        f'<h1 style="margin:0;font-size:{GZ_FS_DISPLAY}px;font-weight:800;'
        f'color:{F_INK_STRONG};letter-spacing:0.01em;line-height:1.3;">'
        f'{_esc(REPORT_TITLE)} {icon_block}</h1>'
        f'<div style="color:{F_MUTED};font-size:{GZ_FS_META}px;line-height:1.7;'
        f'padding-top:6px;">{_esc(REPORT_TAGLINE)} · 更新于 {_esc(generated_at)}'
        + (f' {stamp}' if stamp else '')
        + f'</div>'
        f'<div style="padding-top:6px;">'
        + forum_chip("DATE", str(date_display))
        + f'<span style="padding-left:4px;color:{F_MUTED};font-size:11px;">'
        f'SOURCES <b style="color:{F_ACCENT};">{today_n}/{total}</b></span>'
        + f'</div></td></tr></table>')
    return (
        f'<div style="border:1px solid {F_HAIR_SOLID};border:1px solid {F_HAIR};'
        f'border-radius:14px;background:{F_CARD};color:{F_INK};overflow:hidden;">'
        f'{top}{hero}</div>')


def _forum_footer(footer_text):
    """Forum 尾注：一行符号图例 + 免责 / 数据来源说明（收尾归档卡片）。"""
    def legend(text, color):
        return (f'<span style="display:inline-block;margin-right:10px;'
                f'color:{color};font-size:11px;white-space:nowrap;">{text}</span>')
    legend_html = (legend(f"▲ 涨", F_RED) + legend(f"▼ 跌", F_GREEN)
                   + legend(f"■ 平", F_MUTED) + legend("🤖 AI 合成", F_PURPLE))
    return (
        f'<div style="margin-top:14px;border:1px solid {F_HAIR_SOLID};'
        f'border:1px solid {F_HAIR};border-radius:14px;background:{F_CARD};'
        f'color:{F_INK};overflow:hidden;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{F_CARD}" '
        f'style="width:100%!important;border-collapse:collapse;background:{F_CARD};'
        f'color:{F_INK};">'
        f'<tr><td valign="top" style="padding:12px 14px 30px;color:{F_INK};">'
        f'<div style="font-family:{F_MONO};font-size:10px;font-weight:700;'
        f'letter-spacing:0.22em;color:{F_MUTED};">SESSION END · 归档结束</div>'
        f'<div style="padding-top:4px;">{legend_html}</div>'
        f'<div style="color:{F_MUTED};font-size:11px;line-height:1.8;padding-top:8px;">'
        f'{footer_text}</div>'
        f'</td></tr></table></div>')


def generate_report_forum(data, date_display, date_str, sentiment_history=None,
                          policy_result=None, news_corpus=None):
    """Forum 排版（暗色社区仪表盘）：状态条刊头 + 卡片栏目 + 分段控件尾注。

    内容块与 guizang / dossier 同源（同一套研报渲染器），只在 _forum_palette
    渲染期间换成 暗底 / 卡片 / 近白正文 / 彩色图标；栏目顺序、分条标记、
    推送门禁全部不变。整页拼装与暗色字色归一都在换色期间完成。
    """
    with _forum_palette():
        parts = _collect_report_parts(data, FORUM_KIT,
                                      sentiment_history=sentiment_history,
                                      date_str=date_str,
                                      policy_result=policy_result,
                                      news_corpus=news_corpus)
        sections = parts["sections"]
        content_html = "".join(
            PART_BREAK_MARK + FORUM_KIT.section(f"{i:02d}", kicker, title, content, badge, caption)
            for i, (kicker, title, content, badge, caption) in enumerate(sections[1:], 1))
        opening = _poetry_sea_section(parts, FORUM_KIT)
        first_section = (opening + PART_BREAK_MARK if opening else "") + FORUM_KIT.section("00", *sections[0])
        total = parts["total"]
        today_n = parts["today_n"]
        generated_at = _now()
        footer_text = (
            "仅供参考，非投资建议 · 数据来自公开来源，未抓到内容的栏目自动缺席。"
            if PLAIN() else
            f'暗色社区排版（Forum） · 画布 {F_BG} + 卡片 {F_CARD} + 1px {F_HAIR} 描边 · '
            f'正文 {F_INK} / 次要 {F_MUTED} / 点缀 {F_ACCENT} · '
            f'涨 ▲ 红、跌 ▼ 绿（A 股口径），符号与颜色双编码<br>\n'
            '数据来自公开来源，未抓到内容的栏目自动缺席，不以历史内容充数。')
        masthead = _forum_masthead(date_display, date_str, today_n, total, generated_at)
        html = _forum_html_frame(masthead, first_section, content_html, footer_text,
                                 date_str, generated_at, today_n, total)
        return _enforce_dark_mode_font(html, bg=F_BG, ink=F_INK, muted=F_MUTED)


def _forum_html_frame(masthead, first_section, content_html, footer_text,
                      date_str, generated_at, today_n, total):
    """Forum 整页外壳（纯内联样式；深灰画布 + 卡片 + 分条标记 + 尾注）。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark only">
<meta name="octopus-report-date" content="{date_str}">
<meta name="octopus-generated-at" content="{generated_at}">
<meta name="octopus-today-sources" content="{today_n}">
<meta name="octopus-total-sources" content="{total}">
<meta name="octopus-theme" content="forum">
<meta name="description" content="{_esc(REPORT_TAGLINE)}">
<title>{REPORT_TITLE}</title>
</head>
<body bgcolor="{F_BG}" style="margin:0;padding:0;background:{F_BG};color:{F_INK};font-family:{F_FONT};font-size:{GZ_FS_BODY}px;line-height:1.7;color-scheme:dark;-webkit-text-size-adjust:100%;word-break:break-word;overflow-wrap:break-word;">
<div style="max-width:980px;margin:0 auto;padding:14px 8px 0;background:{F_BG};color:{F_INK};font-family:{F_FONT};font-size:{GZ_FS_BODY}px;line-height:1.7;color-scheme:dark;-webkit-text-size-adjust:100%;word-break:break-word;overflow-wrap:break-word;">

{masthead}

{PART_BREAK_MARK}{first_section}
<div id="report"></div>
{content_html}

{DOC_FOOT_MARK}
{_forum_footer(footer_text)}

</div>
</body>
</html>"""


# theme：跨栏「同子栏合并」按主题判定 12 栏板块热力的切片口径（见 _panorama_heat_selection）。
FORUM_KIT = _RenderKit(
    theme="forum",
    market_section=gz_market_section,
    market_review=gz_market_review,
    channel_block=gz_channel_block,
    headline_row=gz_headline_row,
    em_news_row=gz_em_news_row,
    item_row=gz_item_row,
    rows=gz_rows,
    note=gz_note,
    alert=gz_alert,
    status_footer=gz_status_footer,
    source_badge=lambda item: gz_source_badge(item),
    ai_badge=lambda: gz_badge("AI 合成", "ai"),
    ai_block=gz_ai_analysis_block,
    sentiment_block=gz_sentiment_block,
    sentiment_empty_block=gz_sentiment_empty_block,
    senti_empty_badge=lambda: gz_badge("样本不足", "warn"),
    policy_block=gz_policy_block,
    panorama_block=gz_panorama_block,
    calendar_block=lambda res, date_str=None: gz_calendar_block(res, date_str=date_str),
    trend_topic_block=gz_trend_topic_block,
    # ---- 量化栏目需要的排版原语（注入给 octopus_quant.render）----
    esc=_esc,
    table=lambda headers, rows, aligns=None: gz_data_table(headers, rows, aligns=aligns),
    sub=gz_subsection,
    # meter 的字色在调用时取当前（已换色的）全局，避免默认参数固化旧色
    meter=lambda value, maximum: gz_meter(value, maximum, cells=5,
                                          lit=GZ_KLEIN, off=GZ_FAINT),
    badge=lambda text, kind="ok": gz_badge(text, kind),
    section=forum_section,
    kv=gz_kv_table,
    trend=gz_trend_badge,
    # ok / bad 与 _forum_palette._KIT_COLORS 同口径：涨红 / 跌绿（渲染期还会再覆盖一次）
    ok_color=F_RED, warn_color=F_ORANGE, bad_color=F_GREEN,
)


# ============================================================
# LIME 主题（2026-10-10 起默认主题 · 白底圆角卡片 + 荧光绿强调风）
# 与《整理-表格可视化.html》（PR #135）同款视觉语言：
#   - 画布：纯白 #FFFFFF
#   - 栏目卡：浅灰圆角卡片 #F5F5F6（border-radius: 22px），卡内内容块白底 #FFFFFF / 浅灰 #ECECEF 交替
#   - 标题：粗黑 #111111（font-weight: 900，紧凑字距）
#   - 荧光绿强调：#C8F03C 胶囊序号（配 #111111 粗黑字）、章节方形指示点与浅荧绿底 #F0F9C4
#   - 落字色：深黑 #111111 / 正文 #222222 / 次要深灰 #333333 / 深橄榄绿 #3D5200 / 深红 #B91C1C
#     （全部通过微信端深灰门禁且在白底、浅灰卡、斑马灰、浅荧绿底上 WCAG 对比度 ≥ 4.9:1）
# ============================================================
L_BG = "#FFFFFF"          # 白底画布（--paper: #ffffff）
L_CARD = "#F5F5F6"        # 浅灰圆角卡片底（--card: #f5f5f6）
L_STRIPE = "#FFFFFF"      # 卡内白底内容块（--white: #fff）
L_ZEBRA = "#ECECEF"       # 卡内交替浅灰块
L_INK = "#222222"         # 正文深黑灰
L_INK_STRONG = "#111111"  # 粗黑标题与重点文字（--ink: #111111）
L_MUTED = "#333333"       # 次要深灰字（兼顾微信 v-html 深灰门禁与 ≥ 9.6:1 对比度）
L_HAIR = "#E4E4E7"        # 分割线（--line: #e4e4e7）
L_HAIR_SOFT = "#ECECEF"   # 细分隔线
L_LIME = "#C8F03C"        # 荧光绿强调填充色（--lime: #c8f03c，配 #111111 粗黑字）
L_LIME_WASH = "#F0F9C4"   # 浅荧绿底色（--accent-soft: #f0f9c4）
L_LIME_INK = "#3D5200"    # 荧光绿落字深档（在所有底色上对比度 ≥ 6.65:1）
L_LIME_DEEP = "#2B3A00"   # 荧光绿落字更深档
L_RED_INK = "#B91C1C"     # 跌 / 警示落字深红（在所有底色上对比度 ≥ 4.92:1）
L_FONT = ("Inter,-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
          "'Hiragino Sans GB','Microsoft YaHei',sans-serif")
L_MONO = "'SF Mono',Menlo,Consolas,'Courier New',monospace"

_LIME_GZ_SWAP = {
    "GZ_PAPER": L_STRIPE,
    "GZ_PAPER_TINT": L_CARD,
    "GZ_KLEIN": L_LIME_INK,
    "GZ_KLEIN_DEEP": L_LIME_DEEP,
    "GZ_KLEIN_WASH": L_LIME_WASH,
    "GZ_INK": L_INK,
    "GZ_INK_STRONG": L_INK_STRONG,
    "GZ_DARK_GRAY": L_MUTED,
    "GZ_META": L_MUTED,
    "GZ_FAINT": L_MUTED,
    "GZ_HAIR": L_HAIR,
    "GZ_HAIR_SOFT": L_HAIR_SOFT,
    "GZ_HAIR_INK": L_INK_STRONG,
    "GZ_ZEBRA": L_ZEBRA,
    "GZ_CREAM": L_INK_STRONG,
    "GZ_INK_TINT": L_CARD,
    "GZ_UP": L_LIME_INK, "GZ_DOWN": L_RED_INK, "GZ_FLAT": L_MUTED,
    "GZ_UP_INK": L_LIME_INK, "GZ_DOWN_INK": L_RED_INK, "GZ_FLAT_INK": L_MUTED,
    "GZ_WARN": L_RED_INK, "GZ_WARN_INK": L_RED_INK,
    "GZ_PRIMARY": L_LIME_INK, "GZ_PRIMARY_HOVER": L_LIME_DEEP,
    "GZ_PRIMARY_LIGHT": L_LIME_WASH,
    "GZ_NEON": L_LIME_INK,
    "GZ_FONT": L_FONT,
    "GZ_SERIF": L_FONT,
    "GZ_SANS": L_FONT,
    "GZ_MONO": L_MONO,
}


class _lime_palette:
    """渲染 lime 日报期间临时替换 GZ_* 色变量与 kit 色槽，退出时逐位还原。"""

    _KIT_SLOTS = ("ok_color", "warn_color", "bad_color")
    _KIT_COLORS = {"ok_color": L_LIME_INK, "warn_color": L_RED_INK, "bad_color": L_RED_INK}

    def __enter__(self):
        self._saved = {k: globals()[k] for k in _LIME_GZ_SWAP}
        for k, v in _LIME_GZ_SWAP.items():
            globals()[k] = v
        self._saved_kit = {}
        for kit in (GUIZANG_KIT, LIME_KIT):
            self._saved_kit[id(kit)] = (kit, {s: getattr(kit, s) for s in self._KIT_SLOTS})
            for slot, value in self._KIT_COLORS.items():
                setattr(kit, slot, value)
        return self

    def __exit__(self, exc_type, exc, tb):
        for k, v in self._saved.items():
            globals()[k] = v
        for kit, slots in self._saved_kit.values():
            for slot, value in slots.items():
                setattr(kit, slot, value)
        return False


def lime_pill(text, lime=False):
    """圆角胶囊标签：lime=True 用荧光绿 #C8F03C 底 + #111111 粗黑字；否则用浅灰圆角胶囊。"""
    bg = L_LIME if lime else L_CARD
    weight = "800" if lime else "700"
    return (f'<span style="display:inline-block;margin:6px 6px 0 0;padding:4px 11px;'
            f'border-radius:999px;background:{bg};color:{L_INK_STRONG};'
            f'font-size:11px;font-weight:{weight};line-height:16px;white-space:nowrap;">'
            f'{_esc(text)}</span>')


def lime_section(num, kicker_en, title, content, badge_html="", caption=""):
    """Lime 栏目卡：浅灰圆角卡片 #F5F5F6 + 荧光绿胶囊序号 #C8F03C + 粗黑标题 #111111 → 白/灰交替内容块。"""
    content = content or ""
    if content.lstrip().startswith("<tr"):
        content = (f'<table width="100%" cellpadding="0" cellspacing="0" '
                   f'style="width:100%!important;border-collapse:collapse;'
                   f'font-size:{GZ_FS_TABLE}px;color:{L_INK}">{content}</table>')
    content = _gz_zebra_bands(content)
    meta_bits = [x for x in (badge_html, caption) if x]
    meta = (f'<div style="color:{L_MUTED};font-size:{GZ_FS_META}px;padding-top:6px;">'
            f'{" · ".join(meta_bits)}</div>') if meta_bits else ""
    head = (
        f'<div style="margin-top:14px;padding:14px 10px 12px;border-radius:22px;'
        f'background:{L_CARD};color:{L_INK};overflow:hidden;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{L_CARD}" '
        f'style="width:100%!important;border-collapse:collapse;background:{L_CARD};color:{L_INK};">'
        f'<tr><td valign="middle" style="padding:0;color:{L_MUTED};">'
        f'<span style="display:inline-block;min-width:22px;margin-right:7px;padding:0 6px;'
        f'border-radius:999px;background:{L_LIME};color:{L_INK_STRONG};'
        f'font-size:10px;font-weight:900;line-height:18px;text-align:center;">{_esc(num)}</span>'
        f'<span style="color:{L_LIME_INK};font-size:10px;padding-right:5px;">■</span>'
        f'<span style="font-size:11px;font-weight:700;letter-spacing:0.14em;'
        f'color:{L_MUTED};">SECTION {_esc(num)} · {_esc(kicker_en)}</span>'
        f'</td></tr>'
        f'<tr><td valign="top" style="padding:0 0 10px;color:{L_INK};">'
        f'<h2 style="margin:6px 0 0;padding:0 0 10px;border-bottom:1px solid {L_HAIR};'
        f'font-size:{GZ_FS_SECTION}px;font-weight:900;line-height:1.22;'
        f'letter-spacing:-0.02em;color:{L_INK_STRONG};">{_esc(title)}</h2>'
        f'{meta}</td></tr></table>'
    )
    body = f'{content}</div>'
    return head + SECTION_BODY_MARK + body


def _lime_masthead(date_display, date_str, today_n, total, generated_at):
    """Lime 刊头：OCTOPUS AI · FIELD GUIDE 眉标 + 粗黑大标题 + 圆角胶囊元信息 + 浅灰阅读说明条。"""
    pills = (
        lime_pill(f"当天源 {today_n}/{total}", lime=True)
        + lime_pill(str(date_display))
        + lime_pill("多行多列表格 · 圆角卡片")
    )
    hero = (
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{L_BG}" '
        f'style="width:100%!important;border-collapse:collapse;background:{L_BG};color:{L_INK};">'
        f'<tr><td valign="top" style="padding:4px 2px 14px;color:{L_INK};">'
        f'<div style="color:{L_MUTED};font-size:11px;font-weight:700;letter-spacing:0.12em;">'
        f'<span style="color:{L_LIME_INK};">■</span> OCTOPUS AI · FIELD GUIDE</div>'
        f'<h1 style="margin:6px 0 8px;font-size:{GZ_FS_DISPLAY}px;font-weight:900;'
        f'line-height:1.15;letter-spacing:-0.03em;color:{L_INK_STRONG};">'
        f'{_esc(REPORT_TITLE)}</h1>'
        f'<div style="color:{L_MUTED};font-size:{GZ_FS_META}px;line-height:1.6;">'
        f'{_esc(REPORT_TAGLINE)} · 更新于 {_esc(generated_at)}</div>'
        f'<div style="padding-top:6px;color:{L_INK};">{pills}</div>'
        f'</td></tr></table>'
    )
    legend = (
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{L_CARD}" '
        f'style="width:100%!important;border-collapse:collapse;background:{L_CARD};'
        f'border-radius:14px;color:{L_MUTED};">'
        f'<tr><td width="28%" style="padding:10px 14px;font-size:11px;color:{L_MUTED};line-height:1.6;">'
        f'<span style="display:inline-block;padding:0 6px;margin-right:6px;border-radius:999px;'
        f'background:{L_LIME};color:{L_INK_STRONG};font-size:10px;font-weight:900;">■</span>'
        f'多行多列表格</td>'
        f'<td style="padding:10px 14px;font-size:11px;color:{L_MUTED};line-height:1.6;">'
        f'条目底色交替 · 结构化分列排版 · 涨 <b style="color:{L_LIME_INK};">▲</b> / '
        f'跌 <b style="color:{L_RED_INK};">▼</b> / 平 <b style="color:{L_MUTED};">■</b>'
        f'</td></tr></table>'
    )
    return f'<div style="padding:0 0 4px;background:{L_BG};color:{L_INK};">{hero}{legend}</div>'


def _lime_footer(footer_text):
    """Lime 尾注：浅灰圆角卡片收尾。"""
    return (
        f'<div style="margin-top:18px;border-radius:16px;background:{L_CARD};'
        f'color:{L_MUTED};overflow:hidden;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{L_CARD}" '
        f'style="width:100%!important;border-collapse:collapse;background:{L_CARD};'
        f'color:{L_MUTED};">'
        f'<tr><td valign="top" style="padding:12px 16px 26px;color:{L_MUTED};'
        f'font-size:11px;line-height:1.75;">{footer_text}</td></tr></table></div>'
    )


def _lime_html_frame(masthead, first_section, content_html, footer_text,
                     date_str, generated_at, today_n, total):
    """Lime 整页外壳（纯内联样式；白底画布 + 浅灰圆角卡片 + 荧光绿胶囊强调）。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<meta name="octopus-report-date" content="{date_str}">
<meta name="octopus-generated-at" content="{generated_at}">
<meta name="octopus-today-sources" content="{today_n}">
<meta name="octopus-total-sources" content="{total}">
<meta name="octopus-theme" content="lime">
<meta name="description" content="{_esc(REPORT_TAGLINE)}">
<title>{REPORT_TITLE}</title>
</head>
<body bgcolor="{L_BG}" style="margin:0;padding:0;background:{L_BG};color:{L_INK};font-family:{L_FONT};font-size:{GZ_FS_BODY}px;line-height:1.68;color-scheme:light;-webkit-text-size-adjust:100%;word-break:break-word;overflow-wrap:break-word;">
<div style="max-width:980px;margin:0 auto;padding:16px 8px 0;background:{L_BG};color:{L_INK};font-family:{L_FONT};font-size:{GZ_FS_BODY}px;line-height:1.68;color-scheme:light;-webkit-text-size-adjust:100%;word-break:break-word;overflow-wrap:break-word;">

{masthead}

{PART_BREAK_MARK}{first_section}
<div id="report"></div>
{content_html}

{DOC_FOOT_MARK}
{_lime_footer(footer_text)}

</div>
</body>
</html>"""


def generate_report_lime(data, date_display, date_str, sentiment_history=None,
                         policy_result=None, news_corpus=None):
    """Lime 排版（白底圆角卡片 + 荧光绿强调风）：与《整理-表格可视化.html》同款。"""
    with _lime_palette():
        parts = _collect_report_parts(data, LIME_KIT,
                                      sentiment_history=sentiment_history,
                                      date_str=date_str,
                                      policy_result=policy_result,
                                      news_corpus=news_corpus)
        sections = parts["sections"]
        content_html = "".join(
            PART_BREAK_MARK + LIME_KIT.section(f"{i:02d}", kicker, title, content, badge, caption)
            for i, (kicker, title, content, badge, caption) in enumerate(sections[1:], 1))
        opening = _poetry_sea_section(parts, LIME_KIT)
        first_section = (opening + PART_BREAK_MARK if opening else "") + LIME_KIT.section("00", *sections[0])
        total = parts["total"]
        today_n = parts["today_n"]
        generated_at = _now()
        footer_text = (
            "仅供参考，非投资建议 · 数据来自公开来源，未抓到内容的栏目自动缺席。"
            if PLAIN() else
            f'白底圆角卡片排版（Lime） · 画布 {L_BG} + 圆角卡片 {L_CARD} + 荧光绿胶囊 {L_LIME} · '
            f'标题 {L_INK_STRONG} / 正文 {L_INK} / 次要 {L_MUTED} · '
            f'涨跌符号与颜色双编码<br>\n'
            '数据来自公开来源，未抓到内容的栏目自动缺席，不以历史内容充数。')
        masthead = _lime_masthead(date_display, date_str, today_n, total, generated_at)
        html = _lime_html_frame(masthead, first_section, content_html, footer_text,
                                date_str, generated_at, today_n, total)
        return _enforce_dark_gray_font(html, dark_gray=L_MUTED)


# theme：跨栏「同子栏合并」按主题判定 12 栏板块热力的切片口径（见 _panorama_heat_selection）。
LIME_KIT = _RenderKit(
    theme="lime",
    market_section=gz_market_section,
    market_review=gz_market_review,
    channel_block=gz_channel_block,
    headline_row=gz_headline_row,
    em_news_row=gz_em_news_row,
    item_row=gz_item_row,
    rows=gz_rows,
    note=gz_note,
    alert=gz_alert,
    status_footer=gz_status_footer,
    source_badge=lambda item: gz_source_badge(item),
    ai_badge=lambda: gz_badge("AI 合成", "ai"),
    ai_block=gz_ai_analysis_block,
    sentiment_block=gz_sentiment_block,
    sentiment_empty_block=gz_sentiment_empty_block,
    senti_empty_badge=lambda: gz_badge("样本不足", "warn"),
    policy_block=gz_policy_block,
    panorama_block=gz_panorama_block,
    calendar_block=lambda res, date_str=None: gz_calendar_block(res, date_str=date_str),
    trend_topic_block=gz_trend_topic_block,
    esc=_esc,
    table=lambda headers, rows, aligns=None: gz_data_table(headers, rows, aligns=aligns),
    sub=gz_subsection,
    meter=lambda value, maximum: gz_meter(value, maximum, cells=5,
                                          lit=GZ_KLEIN, off=GZ_FAINT),
    badge=lambda text, kind="ok": gz_badge(text, kind),
    section=lime_section,
    kv=gz_kv_table,
    trend=gz_trend_badge,
    ok_color=L_LIME_INK, warn_color=L_RED_INK, bad_color=L_RED_INK,
)


def _harden_wechat_table_widths(html):
    """把 ``width=100%`` 同步写进内联 style，防止微信把日报压成半屏。

    PushPlus/微信详情页的 HTML 清洗器会在部分客户端移除 ``table`` 的 ``width``
    属性，却保留内联 ``style``。旧版最外层表格只有 ``width=\"100%\"``，属性被
    清洗后便按内容固有宽度收缩，实际截图中整份日报只占约半个屏幕，标题和日期也
    被逐字折行。双写 HTML 属性和 CSS（并使用 ``!important``）可兼容两条渲染链路。
    """
    def patch(match):
        tag = match.group(0)
        if re.search(r'width\s*:\s*100%\s*!important', tag, re.I):
            return tag
        if re.search(r'\bstyle\s*=\s*(["\'])', tag, re.I):
            return re.sub(
                r'(\bstyle\s*=\s*["\'])',
                r'\1width:100%!important;',
                tag,
                count=1,
                flags=re.I,
            )
        return tag[:-1] + ' style="width:100%!important;">'

    return re.sub(
        r'<table\b[^>]*\bwidth\s*=\s*(["\'])100%\1[^>]*>',
        patch,
        html,
        flags=re.I,
    )


_CSS_COLOR_PROP_RE = re.compile(r'(?<![-\w])(color\s*:\s*)(#[0-9A-Fa-f]{3,6})\b')
_BLOCK_STYLE_TAG_RE = re.compile(
    r'(<(?P<tag>div|table|section|p|h1|h2|small)\b[^>]*?\bstyle\s*=\s*(?P<q>["\']))(?P<style>.*?)(?P=q)',
    re.I | re.S,
)


def _is_light_or_mid_gray_hex(hex_color):
    """判断色值是否为需强制加深的中/浅灰色（保留 #000/#111/#222/#333 与纯白 #fff/#ffffff 及彩色）。"""
    h = (hex_color or "").lstrip("#")
    if len(h) == 3:
        r, g, b = (int(c * 2, 16) for c in h)
        return r == g == b and 0x33 < r < 0xE8
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        if r == g == b:
            return 0x33 < r < 0xE8
        return (max(r, g, b) - min(r, g, b) <= 18) and (0x33 < max(r, g, b) <= 0xA8)
    return False


def _enforce_dark_gray_font(html, dark_gray=GZ_DARK_GRAY):
    """强制全局：
    1) 将白底/浅底 HTML 中的所有灰色字体（color:#444~#ddd 等）统一改写为深灰色（#333）；
    2) 为所有带内联 style 但未声明前景色 `color:` 的容器/表格标签（div/table/section/p/h1/h2/small）
       显式补齐内联 `color`，防止 PushPlus `v-html` 剥离 `<body>` 后文字回退为宿主页面浅灰/深色模式反色。

    仅改写或补齐文字前景色 `color:...`，不触碰 `background-color`、`border-color` 或 `border:1px solid #ddd` 分割线；
    对暗色像素主题（`octopus-theme="pixel"` 或深色底 `background:#050711`）原样返回。
    """
    if not html:
        return html
    if 'name="octopus-theme" content="pixel"' in html or "background:#050711" in html:
        return html
    html = _CSS_COLOR_PROP_RE.sub(
        lambda m: f"{m.group(1)}{dark_gray}" if _is_light_or_mid_gray_hex(m.group(2)) else m.group(0),
        html,
    )

    def _ensure_block_color(match):
        style = match.group("style")
        if re.search(r'(?<![-\w])color\s*:', style, re.I):
            return match.group(0)
        tag = match.group("tag").lower()
        fallback = GZ_INK_STRONG if tag in ("h1", "h2") else (dark_gray if tag == "small" else GZ_INK)
        sep = "" if (not style or style.rstrip().endswith(";")) else ";"
        return f"{match.group(1)}{style}{sep}color:{fallback}{match.group('q')}"

    return _BLOCK_STYLE_TAG_RE.sub(_ensure_block_color, html)


def _rel_lum(hex_color):
    """WCAG 相对亮度（支持 #rgb / #rrggbb；非法值按黑处理）。"""
    h = str(hex_color or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return 0.0
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return 0.0

    def _f(v):
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * _f(r) + 0.7152 * _f(g) + 0.0722 * _f(b)


def _contrast_ratio(hex_a, hex_b):
    """两色 WCAG 对比度（1.0 ~ 21.0）。"""
    la, lb = _rel_lum(hex_a), _rel_lum(hex_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# 色相吸附表：任意历史彩色字都归到这六支主题强调色里最接近的一支（色相距离最近）。
# 2026-10-06 起黄色锚点撤掉（点缀色改紫，紫与 F_PURPLE 同值同锚）：历史黄字
# （pixel 的 #FFE66D 等）按色相距离落到橙 #FF9F0A，仍是暖色、仍过 AA。
FORUM_HUE_SNAP = (
    (F_RED, 0.0),        # 红（＝涨 ▲）
    (F_ORANGE, 0.09),    # 橙（＝警示 / 暂缺）
    (F_GREEN, 0.375),    # 绿（＝跌 ▼）
    (F_CYAN, 0.533),     # 青
    (F_BLUE, 0.583),     # 蓝（＝链接）
    (F_PURPLE, 0.764),   # 紫（＝点缀色 F_ACCENT / AI）
)


def _hue_distance(a, b):
    """两色相的最短圆周距离（0 ~ 0.5）。"""
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def _dark_text_color_for(hex_color, bg=F_BG, ink=F_INK, muted=F_MUTED):
    """把任意字色归一到暗色主题色板：灰阶落到近白 / 中灰，彩色按色相吸附强调色。

    暗底上不存在「看不清」的余地：历史浅色主题的深灰 #222~#555、克莱因蓝
    #002FA7、荧光绿 #39FF14 等都会被收进主题色板（近白、中灰或七支强调色），
    保证整页只用一套颜色，且任何一支在 #1C1C1E 与 #2C2C2E 上都 ≥ 4.5:1。
    """
    h = str(hex_color or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return ink
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return ink
    if max(r, g, b) - min(r, g, b) <= 18:              # 灰阶
        lum = _rel_lum(hex_color)
        if lum >= 0.9:                                 # 纯白系：就是标题白
            return F_INK_STRONG
        return muted if lum >= 0.16 else ink           # 中亮 → 次要灰；偏暗 → 近白
    hue = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)[0]
    return min(FORUM_HUE_SNAP, key=lambda item: _hue_distance(hue, item[1]))[0]


def _enforce_dark_mode_font(html, bg=F_BG, ink=F_INK, strong=F_INK_STRONG,
                            muted=F_MUTED, allowed=None):
    """暗色主题版「字色保护」：把每个内联 `color:` 归一到暗色主题可用色板。

    1) 已在主题色板（allowed）里的字色原样保留；其余一律改写——灰阶按亮度落到
       近白 / 中灰，彩色保持色相提亮到暗底上 ≥ 4.5:1，避免历史浅色主题的深灰、
       克莱因蓝、浅灰小字落进暗色卡片后「消失」或「发糊」；
    2) 为带内联 style 却没写 `color:` 的块级标签（div/table/section/p/h1/h2/small）
       补齐前景色，保证 PushPlus `v-html` 剥离 <body> 后每个文本节点都有显式颜色。
    仅改写 / 补齐文字前景色，不触碰 background-color 与 border 颜色。
    """
    if not html:
        return html
    allowed_set = {str(c).upper() for c in (allowed or FORUM_TEXT_ALLOWED)}
    cache = {}

    def _fix(match):
        color = match.group(2)
        key = color.upper()
        if key in allowed_set:
            return match.group(0)
        rep = cache.get(key)
        if rep is None:
            rep = _dark_text_color_for(color, bg=bg, ink=ink, muted=muted)
            cache[key] = rep
        return f"{match.group(1)}{rep}"

    html = _CSS_COLOR_PROP_RE.sub(_fix, html)

    def _ensure_block_color(match):
        style = match.group("style")
        if re.search(r'(?<![-\w])color\s*:', style, re.I):
            return match.group(0)
        tag = match.group("tag").lower()
        fallback = strong if tag in ("h1", "h2") else (muted if tag == "small" else ink)
        sep = "" if (not style or style.rstrip().endswith(";")) else ";"
        return f"{match.group(1)}{style}{sep}color:{fallback}{match.group('q')}"

    return _BLOCK_STYLE_TAG_RE.sub(_ensure_block_color, html)


def generate_report(data, date_display, date_str, theme=None, sentiment_history=None,
                    policy_result=None, news_corpus=None):
    """生成完整的 HTML 日报（按推送主题分发排版）。

    theme: "lime"（默认 · 白底圆角卡片 + 荧光绿强调风）/ "pixel"（DOS 复古监视器）
    / "forum"（暗色社区仪表盘）/ "dossier"（德国文件档案风 + 包豪斯几何）/ "guizang"（简洁白底研报）。
    sentiment_history: 跨日情绪基线（新闻情绪用），缺省冷启动。
    policy_result: 政策因子结果（main 单独构建），缺省时渲染侧兜底构建。
    news_corpus: 跨运行标题存档（output/news_history.json），供 15 日/72h 窗口。
    """
    theme = _resolve_push_theme(theme)
    if theme == "lime":
        html = generate_report_lime(data, date_display, date_str,
                                    sentiment_history=sentiment_history,
                                    policy_result=policy_result,
                                    news_corpus=news_corpus)
    elif theme == "forum":
        html = generate_report_forum(data, date_display, date_str,
                                     sentiment_history=sentiment_history,
                                     policy_result=policy_result,
                                     news_corpus=news_corpus)
    elif theme == "dossier":
        html = generate_report_dossier(data, date_display, date_str,
                                       sentiment_history=sentiment_history,
                                       policy_result=policy_result,
                                       news_corpus=news_corpus)
    elif theme == "guizang":
        html = generate_report_guizang(data, date_display, date_str,
                                       sentiment_history=sentiment_history,
                                       policy_result=policy_result,
                                       news_corpus=news_corpus)
        html = _enforce_dark_gray_font(html)
    else:
        html = generate_report_pixel(data, date_display, date_str,
                                     sentiment_history=sentiment_history,
                                     policy_result=policy_result,
                                     news_corpus=news_corpus)
    return _harden_wechat_table_widths(html)



def generate_report_guizang(data, date_display, date_str, sentiment_history=None,
                            policy_result=None, news_corpus=None):
    """归藏简洁排版（克莱因蓝 + 灰）：一页推送优先，结构扁平、样式全内联。"""
    parts = _collect_report_parts(data, GUIZANG_KIT,
                                  sentiment_history=sentiment_history,
                                  date_str=date_str,
                                  policy_result=policy_result,
                                  news_corpus=news_corpus)
    sections = parts["sections"]
    total = parts["total"]
    today_n = parts["today_n"]
    opening = _poetry_sea_section(parts, GUIZANG_KIT)
    first_section = (opening + PART_BREAK_MARK if opening else "") + GUIZANG_KIT.section("00", *sections[0])
    content_html = "".join(
        PART_BREAK_MARK + GUIZANG_KIT.section(f"{i:02d}", kicker, title, content, badge, caption)
        for i, (kicker, title, content, badge, caption) in enumerate(sections[1:], 1))
    generated_at = _now()
    # 页脚：入门版只留一句免责 + 一句数据来源；排版 / 色板 / 涨跌符号的说明只在 --notes / --full 出。
    footer_text = (
        "仅供参考，非投资建议 · 数据来自公开来源，未抓到内容的栏目自动缺席。" if PLAIN() else
        "仅供参考，非投资建议 · 归藏简洁排版 · 克莱因蓝 #002FA7 + 灰 · 涨跌用 ▲▼■ 表达，不依赖红绿<br>\n"
        "数据来自公开来源，未抓到内容的栏目自动缺席，不以历史内容充数。")
    # 刊头：一行克莱因蓝刊名 → 标题 → 一行灰meta（日期 / 当天源 / 更新时间）
    masthead = (
        f'<div style="padding:4px 0 0;color:{GZ_INK};background:{GZ_PAPER}">'
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{GZ_PAPER}" '
        f'style="width:100%!important;border-collapse:collapse;background:{GZ_PAPER};color:{GZ_INK};">'
        f'<tr><td valign="top" style="padding:0;color:{GZ_INK};">'
        f'<div style="color:{GZ_KLEIN};font-size:11px;font-weight:700;'
        f'letter-spacing:0.18em;line-height:1.6">OCTOPUS QUANT</div>'
        f'<h1 style="margin:6px 0 0;font-size:{GZ_FS_DISPLAY}px;font-weight:700;'
        f'color:{GZ_INK_STRONG};letter-spacing:-0.02em;line-height:1.3;'
        f'background:{GZ_PAPER}">{_esc(REPORT_TITLE)}</h1>'
        f'<div style="color:{GZ_FAINT};font-size:{GZ_FS_META}px;line-height:1.7;'
        f'padding-top:8px">{_esc(REPORT_TAGLINE)} · {_esc(date_display)} · '
        f'当天源 {today_n}/{total} · 更新于 {_esc(generated_at)}</div>'
        f'</td></tr></table></div>')
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<meta name="octopus-report-date" content="{date_str}">
<meta name="octopus-generated-at" content="{generated_at}">
<meta name="octopus-today-sources" content="{today_n}">
<meta name="octopus-total-sources" content="{total}">
<meta name="octopus-theme" content="guizang">
<meta name="description" content="{_esc(REPORT_TAGLINE)}">
<title>{REPORT_TITLE}</title>
</head>
<body bgcolor="{GZ_PAPER}" style="margin:0;padding:0;background:{GZ_PAPER};color:{GZ_INK};font-family:{GZ_FONT};font-size:{GZ_FS_BODY}px;line-height:1.75;color-scheme:light;-webkit-text-size-adjust:100%;word-break:break-word;overflow-wrap:break-word;">
<div style="max-width:980px;margin:0 auto;padding:16px 8px 0;background:{GZ_PAPER};color:{GZ_INK};font-family:{GZ_FONT};font-size:{GZ_FS_BODY}px;line-height:1.75;color-scheme:light;-webkit-text-size-adjust:100%;word-break:break-word;overflow-wrap:break-word;">

{masthead}

{PART_BREAK_MARK}{first_section}
<div id="report"></div>
{content_html}

{DOC_FOOT_MARK}
<div style="margin-top:26px;border-top:1px solid {GZ_HAIR};">
<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{GZ_PAPER}" style="width:100%!important;border-collapse:collapse;background:{GZ_PAPER};color:{GZ_FAINT};font-size:11px;line-height:1.8;">
<tr><td valign="top" style="padding:12px 0 30px;color:{GZ_FAINT};">
{footer_text}
</td></tr></table>
</div>

</div>
</body>
</html>"""
    return _enforce_dark_gray_font(html)


def generate_report_pixel(data, date_display, date_str, sentiment_history=None,
                              policy_result=None, news_corpus=None):
    """生成完整 HTML 日报（旧版 RETRO PIXEL 排版：终端 + 关卡 + 审计 + COLOPHON）。

    - 每个区块都带来源、抓取时间与「当天/非当天/无数据」徽标；
    - 没有抓到内容的区块不出现在页面主体，仅在数据审计栏留痕；
    - 当天内容检验仍作为推送门禁，但不在页面顶部单独显示横幅。
    """
    parts = _collect_report_parts(data, PIXEL_KIT,
                                  sentiment_history=sentiment_history,
                                  date_str=date_str,
                                  policy_result=policy_result,
                                  news_corpus=news_corpus)
    sections = parts["sections"]
    total = parts["total"]
    today_n = parts["today_n"]
    content_n = parts["content_n"]

    # 6. 拼版：栏目编号按渲染顺序生成（只在场的栏目占用编号）
    # 每个栏目前都插入分条标记（含第一栏），供超长日报按完整栏目分条推送
    opening = _poetry_sea_section(parts, PIXEL_KIT)
    content_html = (PART_BREAK_MARK + opening if opening else "") + "".join(
        PART_BREAK_MARK + PIXEL_KIT.section(f"{i:02d}", kicker, title, content, badge, caption)
        for i, (kicker, title, content, badge, caption) in enumerate(sections, 0))

    # 7. 拼接完整 HTML（头部嵌入元信息，供 --push-only 二次当天检验）
    generated_at = _now()
    src_color = C_GREEN if today_n > 0 else (C_AMBER if content_n > 0 else C_RED)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="octopus-report-date" content="{date_str}">
<meta name="octopus-generated-at" content="{generated_at}">
<meta name="octopus-today-sources" content="{today_n}">
<meta name="octopus-total-sources" content="{total}">
<meta name="octopus-theme" content="pixel">
<meta name="description" content="{_esc(REPORT_TAGLINE)}">
<title>{REPORT_TITLE} | RETRO PIXEL EDITION</title>
</head>
<body style="margin:0;padding:0;background:{C_BG};font-family:{FONT};color:{C_INK};font-size:13px;line-height:1.7;-webkit-text-size-adjust:100%;">

<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;max-width:980px;margin:0 auto;background:{C_BG};">
<tr><td style="padding:8px 6px;">

<!-- 外框：像素终端窗口 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:{C_PAPER};border:1px solid {C_ACCENT};box-shadow:8px 8px 0 #000;">
<tr><td style="padding:0;">

<!-- 标题栏：像 8-bit 窗口 title bar -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:{C_ACCENT};"><tr>
<td style="padding:5px 8px;font-family:{FONT_MONO};font-size:10px;font-weight:900;color:#000;letter-spacing:1px;">OCTOPUS_OS v3.0 // PIXEL.MARKET.QUEST</td>
<td align="right" style="padding:5px 8px;font-family:{FONT_MONO};font-size:10px;font-weight:900;color:#000;">[−][□][×]</td>
</tr></table>

<div style="padding:14px 10px 16px;">

<!-- 刊头 masthead：纯 HTML 像素章鱼 + 游戏卡带标题 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
<tr>
<td width="56" valign="middle" style="padding-right:10px;">
<table width="48" height="48" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid {C_ACCENT};background:#080C18;box-shadow:5px 5px 0 #000;"><tr><td align="center" valign="middle">{_pixel_octopus(4)}</td></tr></table>
</td>
<td valign="middle"><div style="font-size:11px;color:{C_ACCENT};font-weight:900;letter-spacing:2px;font-family:{FONT_MONO};">OCTOPUS AI</div><div style="font-size:9px;color:{C_CYAN};letter-spacing:1px;font-family:{FONT_MONO};padding-top:3px;">[ RETRO FINANCE CARTRIDGE ]</div></td>
<td align="right" valign="middle"><span style="font-size:8px;font-weight:900;color:{C_ACCENT_MAGENTA};letter-spacing:2px;font-family:{FONT_MONO};border:1px solid {C_ACCENT_MAGENTA};padding:2px 5px;background:#301226;box-shadow:2px 2px 0 #000;">PLAYER 01</span></td>
</tr>
</table>

<div style="font-size:27px;font-weight:900;color:{C_ACCENT_DEEP};letter-spacing:.5px;line-height:1.3;padding-top:16px;font-family:{FONT_MONO};text-shadow:3px 3px 0 {C_ACCENT_SOFT};">{_esc(REPORT_TITLE)}<span style="color:{C_ACCENT};">_</span></div>
<div style="font-size:10px;font-weight:900;color:{C_CYAN};letter-spacing:2px;padding-top:5px;font-family:{FONT_MONO};">{_esc(REPORT_TAGLINE)} // SIGNAL · AI · FLOW · UTC+8</div>
<div style="margin-top:12px;border-top:1px solid {C_ACCENT};border-bottom:1px solid {C_ACCENT_MAGENTA};height:5px;font-size:0;line-height:0;"><span style="color:{C_ACCENT};">■■■■</span></div>

<!-- 导语：终端开机文字 -->
<div style="margin-top:14px;border:1px solid {C_CYAN};background:#091321;padding:10px 12px;font-size:11px;color:{C_INK};line-height:1.8;font-family:{FONT_MONO};box-shadow:5px 5px 0 #000;">
<span style="color:{C_ACCENT};font-weight:900;">▶ BOOT</span> MARKET DATA LOADED<br>
<span style="color:{C_LEMON};font-weight:900;">◆ AI</span> CORE ANALYSIS READY<br>
<span style="color:{C_ACCENT_MAGENTA};font-weight:900;">■ MODE</span> RETRO PIXEL // 仅渲染有效数据，无数据关卡自动隐藏
</div>

<!-- 视觉图例：颜色 + 方向符号双重编码 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:12px;border:1px solid {C_ACCENT_SOFT};background:#090D1A;box-shadow:3px 3px 0 #000;">
<tr>
<td width="33%" align="center" style="padding:7px 3px;border-right:1px solid {C_ACCENT_SOFT};font-family:{FONT_MONO};font-size:10px;font-weight:900;color:{C_GREEN};">▲ 涨 / UP</td>
<td width="33%" align="center" style="padding:7px 3px;border-right:1px solid {C_ACCENT_SOFT};font-family:{FONT_MONO};font-size:10px;font-weight:900;color:{C_RED};">▼ 跌 / DOWN</td>
<td width="34%" align="center" style="padding:7px 3px;font-family:{FONT_MONO};font-size:10px;font-weight:900;color:{C_LEMON};">◆ AI / CORE</td>
</tr>
</table>

<!-- 期号元信息栅格：像状态栏 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-top:1px solid {C_ACCENT_SOFT};border-bottom:1px solid {C_ACCENT_SOFT};margin-top:14px;background:#0F1222;">
<tr>
{_masthead_cell("DATE", _esc(date_display), first=True)}
{_masthead_cell("BOOT TIME", _esc(generated_at))}
{_masthead_cell("LIVE SRC", f"{today_n} / {total}", src_color)}
</tr>
</table>

<!-- 内容关卡列表 -->
{content_html}

{DOC_FOOT_MARK}
<!-- 版权页 colophon：像素终端关机界面 -->
<div style="border-top:1px solid {C_ACCENT};margin-top:26px;padding-top:12px;background:#0F1222;padding:12px;">
<div style="font-family:{FONT_MONO};font-size:10px;font-weight:900;color:{C_ACCENT};letter-spacing:2px;">{ _heart(C_ACCENT, 10) } OCTOPUS-CHAN // SYSTEM SHUTDOWN</div>
<div style="font-size:10px;color:{C_MUTED};line-height:1.8;padding-top:6px;font-family:{FONT_MONO};">
> 仅供投资参考，非投资建议。行情与榜单来自公开数据，未抓取到内容的栏目自动隐藏，不以历史内容充数。<br>
> RENDER MODE: RETRO PIXEL 8-BIT // 大图标关卡卡牌 // AI CORE 高亮<br>
> TREND KEY: [▲ 涨 / UP] [▼ 跌 / DOWN] [■ 平 / FLAT] [◆ AI CORE]
</div>
<div style="font-size:9px;color:{C_FAINT};letter-spacing:.5px;line-height:1.6;padding-top:6px;font-family:{FONT_MONO};">
DATA_SRC: China Gov Policy · HK GURU (YT/RSS) · Google News · EastMoney · Yahoo · AI_RULE<br>
SYS_TIME: {_esc(generated_at)} · LOG_DATE: {date_str} · BUILD: OCTO-PIXEL-QUEST v3<br>
<span style="color:{C_ACCENT};">█</span><span style="color:{C_CYAN};">▓</span><span style="color:{C_ACCENT_MAGENTA};">▒</span> PRESS START TO CONTINUE
</div>
</div>

</div>

</td></tr>
</table>

</td></tr>
</table>
</body>
</html>"""


    return html


# ============================================================
# PushPlus 推送
# ============================================================
# 可恢复错误的退避重试节奏：首次 + 3 次重试（共最多 4 次尝试）
PUSH_RETRY_BACKOFF = (10, 30, 60)

# 配额/凭证/内容类错误关键字：重试无意义，立即失败，避免浪费仅剩的额度。
_PUSH_FATAL_KEYWORDS = (
    "已达上限", "已用完", "超出今日", "超过今日", "今日已达", "发送次数",
    "token错误", "token 错误", "token 无效", "token无效", "用户不存在",
    "敏感", "违规",
)

# 频率/服务器类错误关键字：稍等重试通常可以恢复。
_PUSH_RETRYABLE_KEYWORDS = (
    "频繁", "太快", "频率", "稍后再试", "稍后重试", "请重试", "繁忙",
    "too many", "frequent", "rate limit", "busy", "retry", "timeout", "超时",
)


def _push_failure_kind(http_status=None, code=None, msg=""):
    """把一次推送失败分类：

    transient —— 频率/服务器/网络类，按 PUSH_RETRY_BACKOFF 重试；
    fatal     —— 配额/凭证/内容类，重试无意义，立即失败；
    unknown   —— 无法归类的业务错误，不重试，立即失败并把 code/msg 打进日志。
    """
    if isinstance(http_status, int) and (http_status == 429 or http_status >= 500):
        return "transient"
    if isinstance(http_status, int) and 400 <= http_status < 500:
        return "fatal"
    low = (msg or "").lower()
    # 先看致命关键字，避免「已达上限，请稍后再试」被误判成可重试
    if any(k in low for k in _PUSH_FATAL_KEYWORDS):
        return "fatal"
    if any(k in low for k in _PUSH_RETRYABLE_KEYWORDS):
        return "transient"
    return "unknown"


# ------------------------------------------------------------
# PushPlus 内容上限截断
# ------------------------------------------------------------
# 自闭合 / void 标签（不会消耗闭合标签）
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr",
              # SVG 线条图标：Lucide 风格，无填充，stroke 1.5，全部自闭合
              "rect", "line", "circle", "path", "polyline", "polygon", "ellipse"}
# 匹配完整标签（含属性中带引号的 > ），用于按标签边界安全截断
_TAG_RE = re.compile(r"<(?P<close>/)?(?P<tag>[a-zA-Z][a-zA-Z0-9]*)"
                     r"(?P<attrs>(?:\"[^\"]*\"|'[^']*'|[^>\"'])*)>")


def _build_truncate_notice(report_name=None):
    """生成截断提示条：说明推送被截断、磁盘完整版不受影响，并附完整版链接（如有）。"""
    link = ""
    if report_name:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if repo:
            url = (f"https://raw.githubusercontent.com/{repo}/main/output/"
                   f"{report_name}")
            link = (f'<div style="padding-top:6px;"><a href="{url}" '
                    f'style="color:{C_ACCENT};font-weight:700;text-decoration:none;">'
                    f"→ 查看完整日报（{report_name}）</a></div>")
    fname = f"（完整版文件：{report_name}）" if report_name else ""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;margin-top:8px;background:{C_ZEBRA};'
            f'border:1px solid {C_HAIR};border-left:1px solid {C_AMBER};"><tr><td '
            f'style="padding:8px 10px;font-size:11px;color:{C_AMBER};line-height:1.75;">'
            f"微信推送有内容长度上限，本消息已自动截断；仓库中的完整日报不受影响{fname}。"
            f"{link}</td></tr></table>")


def _truncate_html_for_push(html, limit=PUSHPLUS_MAX_CONTENT_CHARS, report_name=None):
    """把 HTML 截断到 PushPlus 内容上限以内：只切在完整标签边界，并逆序补全所有未闭合标签。

    返回 (截断后的 html, 是否发生了截断)。磁盘上的日报文件不会被改动——完整版始终保留，
    微信推送只发截断后的版本，末尾附完整版链接/文件名，避免平台截断导致整页排版崩坏。
    """
    if len(html) <= limit:
        return html, False

    notice = _build_truncate_notice(report_name)

    stack = []          # 未闭合标签栈
    candidates = []     # (完整标签结束位置, 该位置时的标签栈快照)
    for m in _TAG_RE.finditer(html):
        end = m.end()
        if end > limit:
            break
        tag, closing = m.group("tag").lower(), bool(m.group("close"))
        if tag not in _VOID_TAGS:
            if closing:
                if stack and stack[-1] == tag:
                    stack.pop()
                # 不匹配时保持栈不变：由下面的逆序补闭合保证结果合法
            else:
                stack.append(tag)
        candidates.append((end, stack.copy()))

    # 从最后一个候选点向前找：正文 + 截断提示 + 逆序闭合标签 的总长不超过上限。
    # 越靠前的候选点未闭合标签越少，闭合标签越短，因此总能找到可用点。
    for end, stack_at_cut in reversed(candidates):
        closers = "".join(f"</{t}>" for t in reversed(stack_at_cut))
        if len(html[:end]) + len(notice) + len(closers) <= limit:
            return html[:end] + notice + closers, True

    # 极端情况：任何截断点都放不下 → 只发截断提示，保证微信端仍能看到说明与完整版入口
    return notice, True


# ------------------------------------------------------------
# PushPlus 精简版正文：原始页面过长时去除装饰性 HTML，保留栏目、全部文字和链接
# ------------------------------------------------------------
class _PushTextExtractor(HTMLParser):
    """把一个 HTML 栏目转换成轻量文本；表格单元格、行和链接边界都会保留。"""

    _BLOCKS = {"div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.active_link = None
        self.skip_heading = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h2":
            self.skip_heading += 1
        if self.skip_heading:
            return
        href = attrs.get("href", "")
        if tag == "a" and (urlparse(href).scheme.lower() in {"http", "https"} or href.startswith("#")):
            self.active_link = [href, []]
        elif tag == "td" and self.parts and not self.parts[-1].endswith(("\n", " ", "|")):
            self.parts.append(" | ")
        elif tag == "br" or tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "h2" and self.skip_heading:
            self.skip_heading -= 1
        if self.skip_heading:
            return
        if tag == "a" and self.active_link:
            href, label = self.active_link
            marker = f"\x01{len(self.links)}\x02"
            self.links.append(("".join(label).strip(), href))
            self.parts.append(marker)
            self.active_link = None
        elif tag == "td":
            self.parts.append(" ")
        elif tag == "br" or tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_heading:
            return
        if self.active_link:
            self.active_link[1].append(data)
        else:
            self.parts.append(data)

    def text(self):
        text = "".join(self.parts)
        text = re.sub(r"[\t\f\v ]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        text = _html_escape(text, quote=False)
        for index, (label, href) in enumerate(self.links):
            marker = f"\x01{index}\x02"
            safe_href = _html_escape(href, quote=True)
            safe_label = _html_escape(label or href)
            text = text.replace(marker, f'<a href="{safe_href}" style="color:{GZ_KLEIN}">{safe_label}</a>')
        return text


def _compact_table_rows(text):
    """精简推送正文按段落生成表格行（由外层表格统一承担字号、颜色与行距）。"""
    paragraphs = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return "".join(f'<tr><td style="border-bottom:1px solid #ddd;">{line}</td></tr>'
                   for line in paragraphs)


def _compact_paragraph_table(text, *, color="#222"):
    """把刊头 / 页脚等精简版文字按段落装入独立表格。"""
    rows = _compact_table_rows(text)
    if not rows:
        return ""
    return (
        f'<table width="100%" cellpadding="6" cellspacing="0" bgcolor="#FFFFFF" '
        f'style="width:100%!important;border-collapse:collapse;background:#FFFFFF;'
        f'color:{color};font-size:14px;line-height:1.7;word-break:break-word;'
        f'overflow-wrap:anywhere;">{rows}</table>'
    )


def _compact_html_for_push(html):
    """生成轻量推送版，保留原文所有可见文字和超链接，移除重复装饰/复杂表格包装。

    完整、原样的精美 HTML 仍保存于磁盘与 GitHub；此版本只用于在平台单条字数限制下
    尽量减少微信消息条数。正文按段落重排成紧凑表格行，栏目仍可安全续拆。
    """
    first_break = html.find(PART_BREAK_MARK)
    foot_at = html.find(DOC_FOOT_MARK)
    if first_break < 0 or foot_at < first_break:
        return None

    body = html[first_break + len(PART_BREAK_MARK):foot_at]
    sections = [section for section in body.split(PART_BREAK_MARK) if section.strip()]
    if not sections:
        return None

    report_date = ""
    date_match = re.search(r'<meta name="octopus-report-date" content="([^"]+)"', html)
    if date_match:
        report_date = date_match.group(1)
    body_open = re.search(r"<body\b[^>]*>(.*)$", html[:first_break], re.I | re.S)
    intro_parser = _PushTextExtractor()
    if body_open:
        intro_parser.feed(body_open.group(1))
    intro = intro_parser.text()
    footer_parser = _PushTextExtractor()
    footer_parser.feed(html[foot_at + len(DOC_FOOT_MARK):])
    footer = footer_parser.text()
    shell = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light only">'
        '<title>章鱼 AI · 上水日报（精简版）</title></head>'
        '<body bgcolor="#FFFFFF" style="margin:0;padding:8px 6px;font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;'
        'font-size:15px;line-height:1.7;color:#111;background:#FFFFFF;color-scheme:light;">'
        '<div style="max-width:980px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;'
        'font-size:15px;line-height:1.7;color:#111;background:#FFFFFF;color-scheme:light;">'
        '<table width="100%" cellpadding="6" cellspacing="0" bgcolor="#FFFFFF" '
        'style="width:100%!important;border-collapse:collapse;background:#FFFFFF;color:#111;">'
        '<tr><td style="border-bottom:2px solid #111;">'
        '<h1 style="font-size:22px;line-height:1.4;margin:0;color:#111;background:#FFFFFF;">'
        '章鱼 AI · 上水日报</h1></td></tr></table>'
        f'<table width="100%" cellpadding="5" cellspacing="0" bgcolor="#FFFFFF" '
        f'style="width:100%!important;border-collapse:collapse;background:#FFFFFF;color:{GZ_DARK_GRAY};'
        f'font-size:12px;line-height:1.6;">'
        f'<tr><td>推送精简排版 · 保留全文文字与原文链接 · {_html_escape(report_date)}</td></tr></table>'
        f'{_compact_paragraph_table(intro, color=GZ_INK)}'
    )
    output = [shell]
    for number, section in enumerate(sections, 1):
        heading = re.search(r"<h2\b[^>]*>(.*?)</h2>", section, re.I | re.S)
        title = ""
        if heading:
            title_parser = _PushTextExtractor()
            title_parser.feed(heading.group(1))
            title = title_parser.text().strip()
        parser = _PushTextExtractor()
        parser.feed(section)
        content = parser.text()
        if title and content.startswith(title):
            content = content[len(title):].lstrip(" \n")
        if not title:
            title = f"日报栏目 {number}"
        section_table = (
            f'<table width="100%" cellpadding="6" cellspacing="0" bgcolor="#FFFFFF" '
            f'style="width:100%!important;border-collapse:collapse;table-layout:fixed;'
            f'background:#FFFFFF;color:{GZ_INK};font-size:14px;line-height:1.7;'
            f'word-break:break-word;overflow-wrap:anywhere;">'
            f'<tr><td style="border-bottom:2px solid #111;color:#111;">'
            f'<h2 style="font-size:18px;line-height:1.5;margin:0;font-weight:700;color:#111;">'
            f'{_html_escape(title)}</h2></td></tr>'
            f'{_compact_table_rows(content)}</table>'
        )
        output.append(
            f'{PART_BREAK_MARK}<section style="padding:10px 0 14px;border-top:1px solid #ddd;'
            f'color:{GZ_INK};background:#FFFFFF;">{section_table}</section>'
        )
    output.append(
        f'{DOC_FOOT_MARK}<table width="100%" cellpadding="6" cellspacing="0" bgcolor="#FFFFFF" '
        f'style="width:100%!important;border-collapse:collapse;border-top:1px solid #ddd;'
        f'background:#FFFFFF;color:{GZ_DARK_GRAY};font-size:12px;line-height:1.8;">'
        f'<tr><td>{footer}<br>推送精简排版；完整排版及日报文件请查看存档。</td></tr>'
        f'</table></div></body></html>'
    )
    return _enforce_dark_gray_font("".join(output))


# ------------------------------------------------------------
# PushPlus 分条完整推送（2026-09-28 起）
# ------------------------------------------------------------
# 日报（含港股量化引擎后）常有 15~25 万字，远超单条 10 万字上限；旧做法在 10 万字处
# 截断，等于每天有近六成内容根本没送到微信。改为「分条完整推送」：
#   渲染时在栏目前插入分条标记（PART_BREAK_MARK）、在页脚前插入 DOC_FOOT_MARK，
#   于是任意一份日报都能被切成 头部外壳 + 若干完整栏目 + 页脚外壳 三段；
#   拆分时按栏目边界装箱，每条消息都是「结构完整、标签自闭合、样式一致」的独立 HTML，
#   微信端读起来就是同一份日报的连续几页，一个字都不丢。
# 单个栏目自身就超预算时，再按完整标签边界切，并在续片里原样重开父标签（保留属性），
# 因此任何上限配置下都不会丢内容、也不会出现半截标签导致的整页排版崩坏。

def _opening_tag_name(open_tag):
    """从完整开标签原文里取标签名（小写）；解析失败返回空串。"""
    m = re.match(r"<\s*([a-zA-Z][a-zA-Z0-9]*)", open_tag or "")
    return m.group(1).lower() if m else ""


def _scan_cut_points(html, limit):
    """扫描 html 前 limit 字符内的完整标签，返回 (标签区间列表, 可切点列表)。

    标签区间元素为 (起, 止)，供「正文中间切点」判断某个位置是否落在标签里
    （含跨过 limit 的那半个标签，否则正文切点可能切进标签内部）；
    可切点元素为 (标签结束位置, 该位置之后的未闭合开标签原文列表)，
    开标签保留原始属性，续片据此原样重开父容器，样式不会丢。
    """
    stack = []
    spans = []
    candidates = []
    for m in _TAG_RE.finditer(html):
        if m.start() >= limit:
            break
        spans.append((m.start(), m.end()))
        if m.end() > limit:
            continue        # 跨过扫描边界的标签只用于「是否在标签里」，不作为切点
        tag, closing = m.group("tag").lower(), bool(m.group("close"))
        if tag not in _VOID_TAGS:
            if closing:
                if stack and _opening_tag_name(stack[-1]) == tag:
                    stack.pop()
                # 不匹配时保持栈不变：由逆序补闭合保证结果合法
            else:
                stack.append(m.group(0))
        candidates.append((m.end(), list(stack)))
    return spans, candidates


# 正文中间切点的优先落点：切在这些字符「之后」看起来像自然断行（空白与中英标点）。
_TEXT_CUT_AFTER = " \t\u3000，。、；：！？,.;:!?、）)】」》›…—·-"


def _inside_entity(text, position, lookback=34):
    """position 是否落在未结束的 HTML 实体（如 ``&amp;``）中间。"""
    return bool(re.search(r"&[#0-9a-zA-Z]*$", text[max(0, position - lookback):position]))


def _find_text_cut(fragment, floor, limit, spans):
    """在一段没有标签边界的正文里找切点：不在标签里、不在 HTML 实体里。

    优先切在空白 / 标点之后（读者看到的是自然断行），找不到就取预算内最后一个
    合法位置；返回切点下标，找不到返回 None。
    """
    limit = min(limit, len(fragment))
    if limit <= floor:
        return None
    # 标签区间之外的正文区间（从后往前找第一个可用的）。
    # 区间一律夹到 limit 以内：spans 可能含跨过扫描边界的标签，若按原始区间取位置，
    # 会切到 limit 之后，前面那一条就会超单条上限（被平台拒收）。
    gaps, previous = [], floor
    for start, end in spans:
        start, end = min(start, limit), min(end, limit)
        if start > previous:
            gaps.append((previous, start))
        previous = max(previous, end)
        if previous >= limit:
            break
    if limit > previous:
        gaps.append((previous, limit))
    fallback = None
    for start, end in reversed(gaps):
        for position in range(end, start, -1):
            if position <= floor:
                break
            if _inside_entity(fragment, position):
                continue
            if fragment[position - 1] in _TEXT_CUT_AFTER:
                return position
            if fallback is None:
                fallback = position
    return fallback


def _closers_for(stack):
    """按逆序为未闭合标签栈生成闭合标签串。"""
    return "".join(f"</{_opening_tag_name(t)}>" for t in reversed(stack))


def _reopened_stack(fragment, after, stack):
    """续片真正要重开的开标签：扣掉「调用方会重新带上的前缀」里已经开的那些。

    现行 guizang 栏目头自己就开着外层 ``<div>``（由正文末尾闭合）。栏目内续接时，
    调用方会在续片前面重新拼上整段栏目头，因此 rest 不能再把栏目头里的标签开一遍，
    否则外层 div 会叠成两层：前半段与续片都不平衡，样式也跟着错位。
    ``after`` 就是这段前缀的长度（栏目内续接时等于栏目头长度）。
    """
    if after <= 0:
        return stack
    prefix = _scan_cut_points(fragment, after)[1]
    base = list(prefix[-1][1]) if prefix else []
    if base and stack[:len(base)] == base:
        return stack[len(base):]
    return stack


def _split_fragment_once(fragment, budget, after=0):
    """把 fragment 切一刀：返回 (前半段, 续片)；切不动返回 None。

    前半段标签自闭合且长度 ≤ budget；续片原样重开被切断的父标签（保留原始属性），
    因此两段都能独立渲染，拼起来仍是原文。``after`` 是「不能切开的前缀长度」
    （栏目内续接时就是栏目头长度）：切点必须在它之后，且续片要比 after 之后的
    正文更短——否则这一刀没有实质进展（切在栏目头里），换刀只会原地打转。
    找不到合格切点时返回 None，由调用方决定整段挪到下一条，还是走截断兜底。
    """
    if budget <= 0 or len(fragment) <= budget:
        return None
    wanted = len(fragment) - after
    spans, candidates = _scan_cut_points(fragment, budget)
    # 1) 优先切在完整标签边界（最靠后的那个可用切点，条数最少）
    for end, stack in reversed(candidates):
        if end <= after:
            continue
        closers = _closers_for(stack)
        if end + len(closers) > budget:
            continue
        # 续片要原样重开的父标签（含原始属性）——不含调用方会重新带上的栏目头那部分
        reopened = "".join(_reopened_stack(fragment, after, stack))
        rest = reopened + fragment[end:]
        if len(rest) < wanted:
            return fragment[:end] + closers, rest
    # 2) 标签边界切不动（正文是一整段没有标签的长文本）→ 退一步切在正文中间，
    #    同样补全未闭合标签；两段拼起来仍是原文，一个字不丢。
    last_end, last_stack = candidates[-1] if candidates else (0, [])
    closers = _closers_for(last_stack)
    position = _find_text_cut(fragment, max(last_end, after), budget - len(closers), spans)
    if position is not None:
        rest = "".join(_reopened_stack(fragment, after, last_stack)) + fragment[position:]
        if len(rest) < wanted:
            return fragment[:position] + closers, rest
    return None


def _build_part_banner(index, total, theme=None, limit=None, tail_cut=False,
                       continuation="", unfinished=False):
    """分条推送的条序横幅：告诉读者这是第几条 / 共几条，以及为什么要分条。

    tail_cut=True 用于「条数已达 PUSHPLUS_MAX_PARTS 上限」的收尾条：
    此时后面还有内容没推完，横幅必须如实说明并指向完整日报，不能谎称已送达全文；
    continuation=栏目名 表示本条开头是上一栏的续片（栏目被切开了），
    unfinished=True 表示本条在栏目内没写完、下一条仍是同一栏的续片。
    """
    limit = limit or PUSHPLUS_MAX_CONTENT_CHARS
    if tail_cut:
        text = (f"📄 第 {index}/{total} 条 · 已达单次推送条数上限"
                f"（PUSHPLUS_MAX_PARTS={total}），本条之后的内容见文末完整日报链接")
    else:
        text = f"📄 第 {index}/{total} 条"
        if continuation:
            text += f" · 承接上条「{continuation}」（续）"
        text += (f" · 单条上限 {limit // 10000 or 1} 万字，已尽量合并推送"
                 f"（内容不缺失）")
        if index < total:
            text += " · 本条未完，接下条" if unfinished else f" · 接下条 {index + 1}/{total}"
    if theme == "lime":
        return (f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{L_CARD}" '
                f'style="width:100%!important;border-collapse:collapse;margin:12px 0;'
                f'background:{L_CARD};border:1px solid {L_HAIR};border-radius:14px;'
                f'color:{L_INK_STRONG};">'
                f'<tr><td style="padding:8px 12px;font-size:11px;font-weight:700;'
                f'color:{L_INK_STRONG};line-height:1.6;">'
                f'<span style="display:inline-block;padding:1px 7px;margin-right:6px;'
                f'border-radius:999px;background:{L_LIME};color:{L_INK_STRONG};'
                f'font-size:10px;font-weight:900;">{index}/{total}</span>'
                f'{text}</td></tr></table>')
    if theme == "pixel":
        return (f'<table width="100%" cellpadding="0" cellspacing="0" '
                f'style="border-collapse:collapse;margin:0 0 12px;background:{C_ACCENT};">'
                f'<tr><td style="padding:8px 10px;font-family:{FONT_MONO};font-size:11px;'
                f'font-weight:900;color:#000;line-height:1.6;">{text}</td></tr></table>')
    if theme == "forum":
        # 暗色分条横幅：卡内亮块 + 点缀紫字，圆角描边与卡片语言一致
        return (f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{F_STRIPE}" '
                f'style="width:100%!important;border-collapse:collapse;margin:12px 0;'
                f'background:{F_STRIPE};border:1px solid {F_HAIR_SOLID};'
                f'border:1px solid {F_HAIR};border-radius:10px;color:{F_INK};">'
                f'<tr><td style="padding:8px 12px;font-size:11px;line-height:1.6;'
                f'color:{F_ACCENT};">⚡ '
                f'{text[2:] if text.startswith("📄 ") else text}</td></tr></table>')
    if theme == "dossier":
        # 分条横幅与栏目标签同款：荧光绿高亮块 + 黑字（15.5:1）
        return (f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{D_TAB}" '
                f'style="width:100%!important;border-collapse:collapse;margin:12px 0;'
                f'background:{D_TAB};border-top:2px solid {D_BLACK};border-bottom:1px solid {D_HAIR};'
                f'color:{D_INK_STRONG};">'
                f'<tr><td style="padding:7px 10px;font-family:{D_MONO};font-size:11px;'
                f'font-weight:700;color:{D_INK_STRONG};line-height:1.6;">'
                f'<span style="color:{D_INK_STRONG};">■</span> AKTE · {text}</td></tr></table>')
    return (f'<table width="100%" border="0" cellpadding="0" cellspacing="0" '
            f'bgcolor="{GZ_INK}" style="width:100%!important;border-collapse:collapse;'
            f'table-layout:fixed;background:{GZ_INK};margin:0 0 8px;">'
            f'<tr><td align="left" valign="top" style="padding:10px 16px;">'
            f'<div style="font-size:{GZ_FS_META + 1}px;color:{GZ_PAPER};'
            f'font-weight:{GZ_W_BOLD};line-height:1.6;">'
            f'{text}</div></td></tr></table>')


def _report_theme(html):
    """从日报 HTML 里读出渲染主题（供分条横幅配色）；读不出来按默认 pixel 主题处理。"""
    m = re.search(r'name="octopus-theme"\s+content="([^"]+)"', html or "")
    theme = (m.group(1) if m else "").strip().lower()
    return theme if theme in PUSH_THEMES else DEFAULT_PUSH_THEME


def _section_title_text(header_html, max_len=28):
    """从栏目头 HTML 里取出栏目名，供「承接上条（续）」横幅使用；取不到返回空串。

    两个主题的栏目头结构固定：guizang 用 ``<h2>标题</h2>``，pixel 用带
    ``padding-top:4px;line-height:1.35`` 的标题 div。取到的文字已是 HTML 转义过的，
    直接放进横幅即可（不再二次转义，否则 ``&amp;`` 会变成 ``&amp;amp;``）。
    """
    for pattern in (r"<h2[^>]*>(.*?)</h2>",
                    r"padding-top:4px;line-height:1\.35[^>]*>(.*?)<span"):
        m = re.search(pattern, header_html or "", re.S)
        if not m:
            continue
        text = " ".join(re.sub(r"<[^>]+>", "", m.group(1)).split())
        if text:
            return text[:max_len] + ("…" if len(text) > max_len else "")
    return ""


def _split_section_units(sections):
    """把栏目 HTML 拆成 (栏目头, 栏目名, 正文)；没有栏目头锚点时整段算正文。"""
    units = []
    for section in sections:
        header, separator, content = section.partition(SECTION_BODY_MARK)
        if not separator:
            header, content = "", section
        units.append((header, _section_title_text(header), content))
    return units


def _pack_section_units(units, budget, min_split=None):
    """顺序装箱：把栏目装进「每条正文 ≤ budget 字」的消息里，条数取最小。

    规则（尽量合并，但绝不丢内容、绝不发出半截标签）：
      1. 整栏放得下 → 整栏装进当前条（读者看到的每条都尽量从完整栏目开始）；
      2. 整栏放不下、且当前条还能再放 min_split 字正文 → 在完整标签边界把该栏切开，
         用当前条的剩余空间装前半段（栏目头 + 正文前半 + 闭合标签），填满这一条；
      3. 剩余空间太小 → 整栏挪到下一条，当前条照样发出（不硬塞碎片）。
    续片在下一条开头重新带上栏目头（``SECTION_BODY_MARK`` 之前的部分），
    横幅标注「承接上条「栏目名」（续）」，因此切开栏目也不会让读者迷路。

    返回 (每条正文列表, 每条开头的「承接栏目名」列表)；两条列表一一对应，
    承接栏目名为空串表示该条从新栏目开始。
    """
    if min_split is None:
        min_split = PUSHPLUS_SPLIT_MIN_BODY
    pending = deque((header, title, content, False) for header, title, content in units)
    chunks, titles = [], []
    current, current_len, current_cont = [], 0, ""

    def flush():
        nonlocal current, current_len, current_cont
        if current:
            chunks.append("".join(current))
            titles.append(current_cont)
            current, current_len, current_cont = [], 0, ""

    while pending:
        header, title, content, is_continuation = pending.popleft()
        full = header + content
        room = budget - current_len
        if len(full) <= room:
            if is_continuation and not current:
                current_cont = title
            current.append(full)
            current_len += len(full)
            continue
        # 整栏（或整段续片）放不下：先把当前条填满，剩下的留到下一条
        # （room 是当前条还能装的字数；head_room 是切给正文的部分，栏目头必须另有位置）
        head_room = room - len(header)
        if head_room >= min_split:
            # after=栏目头长度：切点必须跨过栏目头，续片只装正文，不会原地打转
            cut = _split_fragment_once(full, room, after=len(header))
            if cut is not None:
                head_piece, rest = cut
                if is_continuation and not current:
                    current_cont = title
                current.append(head_piece)
                current_len += len(head_piece)
                flush()
                pending.appendleft((header, title, rest, True))
                continue
        if current:
            # 剩余空间太小（或这一栏切不开）：整栏挪到下一条，当前条不硬塞半截内容
            pending.appendleft((header, title, content, is_continuation))
            flush()
            continue
        # 当前条是空的却还放不下，且找不到任何合法切点（正文是一整段无标签长文本）：
        # 原样放入本条，交给上层做「装不进单条上限」的兜底处理
        current.append(full)
        current_len += len(full)
    flush()
    return chunks, titles


def _split_html_for_push(html, limit=None, report_name=None, max_parts=None):
    """把超过单条上限的日报 HTML 拆成 N 条「各自完整可渲染」的消息；返回 list[str]。

    每条 = 原文档头部外壳（含刊头）+ 条序横幅 + 若干完整栏目（末条可能是一栏的续片）
    + 原文档页脚与闭合标签，因此每条都是独立、标签平衡、样式一致的 HTML，
    微信端排版与单条推送完全相同。全部内容按原文顺序送达，不做任何删减。

    **尽量合并**：顺序装箱时把每条都填到单条上限为止——整栏放得下就整栏装，
    放不下就在完整标签边界把这栏切开、用剩余空间装前半段；只有剩余空间小到会
    产生碎片条时才整栏挪到下一条。因此条数就是「总字数 ÷ 单条可用字数」的理论下限，
    不会为了保持栏目完整而白白多推几条（旧版整栏为单位的装箱会浪费 30%+ 的空间）。

    返回 None 表示无法安全拆分（旧版文件没有分条标记 / 外壳本身就超上限 /
    正文存在切不开的超长无标签文本），调用方应回退到 _truncate_html_for_push。
    """
    # 上限与条数上限都在调用时解析（而不是写进默认参数），环境变量与测试都能覆盖
    limit = limit if limit is not None else PUSHPLUS_MAX_CONTENT_CHARS
    max_parts = max_parts if max_parts is not None else PUSHPLUS_MAX_PARTS
    if limit <= 0 or len(html) <= limit:
        return [html] if html else None

    first_break = html.find(PART_BREAK_MARK)
    foot_at = html.find(DOC_FOOT_MARK)
    if first_break < 0 or foot_at < 0 or foot_at <= first_break:
        print("  ⚠️ 该 HTML 没有分条锚点（旧版日报文件？），无法按栏目拆分")
        return None

    shell = html[:first_break]                   # doctype/head/body/刊头 + 未闭合的外层容器
    tail = html[foot_at + len(DOC_FOOT_MARK):]   # 页脚 + 全部闭合标签
    body = html[first_break + len(PART_BREAK_MARK):foot_at]
    sections = [s for s in body.split(PART_BREAK_MARK) if s.strip()]
    if not sections:
        return None

    theme = _report_theme(html)
    units = _split_section_units(sections)
    # 每条的固定开销：外壳 + 页脚 + 横幅（按最宽的条序数字与最长栏目名预留）+ 安全余量
    longest_title = max((unit[1] for unit in units), key=len, default="")
    cap = max(max_parts, len(units))
    banner_w = max(len(_build_part_banner(
                       index, cap, theme, limit, continuation=longest_title, unfinished=True))
                   for index in (1, cap))
    overhead = len(shell) + len(tail) + banner_w + 64
    budget = limit - overhead
    if budget < 2000:
        print(f"  ⚠️ 单条上限 {limit:,} 字太小：刊头+页脚+横幅已占 {overhead:,} 字，"
              f"正文只剩 {budget:,} 字，拆分没有意义")
        return None

    chunks, chunk_titles = _pack_section_units(units, budget)
    if not chunks:
        return None

    # 条数超过安全上限（只会在把单条上限调得极小时发生）：前 max_parts-1 条完整推送，
    # 最后一条装到上限为止并附「完整日报」链接——比退回单条截断多送达十几倍内容，
    # 且如实告知未推完，绝不假装全文已送达。
    tail_cut = len(chunks) > max_parts
    if tail_cut:
        keep = max(max_parts - 1, 1)
        print(f"  ⚠️ 完整推送需要 {len(chunks)} 条，超过 PUSHPLUS_MAX_PARTS={max_parts}："
              f"前 {keep} 条完整推送，其余内容压进第 {keep + 1} 条并附完整日报链接"
              f"（如需全部送达，请调高 PUSHPLUS_MAX_PARTS 或 PUSHPLUS_MAX_CONTENT_CHARS）")
        chunks = chunks[:keep] + ["".join(chunks[keep:])]
        chunk_titles = chunk_titles[:keep] + [chunk_titles[keep] if keep < len(chunk_titles) else ""]

    total = len(chunks)
    title_re = re.compile(r"(<title>)(.*?)(</title>)", re.S)
    parts = []
    for index, chunk in enumerate(chunks, 1):
        last_cut = tail_cut and index == total
        banner = _build_part_banner(
            index, total, theme, limit, tail_cut=last_cut,
            continuation=chunk_titles[index - 1],
            # 下一条是同一栏的续片 → 本条末尾如实提示「本条未完」
            unfinished=index < total and bool(chunk_titles[index]))
        head = shell
        if total > 1:
            # 让每条的浏览器/微信标题也带上条序，正文横幅之外再多一层提示
            head = title_re.sub(
                lambda m: f"{m.group(1)}{m.group(2)}（第 {index}/{total} 条）{m.group(3)}",
                shell, count=1)
        part = head + banner + chunk + tail
        if len(part) > limit:
            if not last_cut:
                # 只可能是「一整段没有标签边界的超长正文」切不开：宁可回退到截断，
                # 也绝不发出超过平台上限的内容（平台自己截断会切在标签中间，整页排版崩坏）
                print(f"  ⚠️ 第 {index}/{total} 条装不进 {limit:,} 字且无法在标签边界切开"
                      f"（正文存在超长无标签文本），本次不做分条")
                return None
            part, _ = _truncate_html_for_push(part, limit, report_name)
        parts.append(part)
    return parts


def push_to_wechat(title, content_html, token=None, template="html", report_name=None,
                   topic=None):
    """通过 PushPlus 推送消息到微信；返回 True/False，调用方必须据此决定退出码。

    - 默认「一对多」群组推送（2026-10-23 按用户要求）：群组编码从 PUSHPLUS_TOPIC 读取，
      未配置时打印告警并回退一对一；PUSHPLUS_MODE=one2one 可显式改回一对一直发自己。
      显式 topic 参数（含空串）优先级最高，见 resolve_push_route；
    - 日报 HTML 超过单条上限（默认 10 万字符）时，按栏目装箱合并成尽可能少的几条
      （每条都填到上限，必要时在栏目内断开并标注「承接上条（续）」），
      全部明细按原顺序送达；旧版 HTML 无拆分锚点或 PUSHPLUS_MULTIPART=0 时，
      回退到「按标签边界截断 + 完整版链接」；
    - 「发送频繁 / 稍后再试 / 服务器繁忙 / 网络异常 / HTTP 429·5xx」等可恢复错误
      按 PUSH_RETRY_BACKOFF 自动重试（最多 1+3=4 次），多条推送时每条各自享有重试；
      发请求前还会按 PUSHPLUS_RATE_MAX / PUSHPLUS_RATE_WINDOW（默认 1 分钟 5 次，
      与平台限制一致）排队，避免分条过多被平台直接丢弃；
    - token 失效、当日配额已达上限、内容违规等错误重试无意义，立即返回 False；
    - 每次失败都在日志里保留 PushPlus 返回的 code/msg，便于在 Actions 日志定位。
    """
    token = token or PUSHPLUS_TOKEN
    push_mode, topic = resolve_push_route(topic)

    if not token:
        print("⚠️ 未设置 PUSHPLUS_TOKEN，跳过推送")
        print("   请设置环境变量: export PUSHPLUS_TOKEN=你的token")
        print("   （在 GitHub Actions 中请确认仓库 Settings → Secrets → PUSHPLUS_TOKEN 已配置）")
        return False

    print(f"📤 正在推送到微信 (PushPlus, template={template}, "
          f"{push_route_text(push_mode, topic)})...")
    if template == "html":
        if _report_theme(content_html) == "lime":
            with _lime_palette():
                content_html = _enforce_dark_gray_font(content_html, dark_gray=L_MUTED)
        elif _report_theme(content_html) == "dossier":
            # 生成时在档案色板下做灰字保护；推送前再次保护也必须使用同一色板。
            # 否则档案深灰 #4A4A4A 会被改成归藏 #333，漏色容器也会补成 #222。
            with _dossier_palette():
                content_html = _enforce_dark_gray_font(content_html, dark_gray=D_GRAY)
        elif _report_theme(content_html) == "forum":
            # 暗色主题用「暗色字色保护」：深灰 / 浅灰一律重新落到近白或中灰，
            # 彩色提亮到暗底上 ≥ 4.5:1；绝不能套用浅色版的灰字强制（会把字改成 #333）。
            content_html = _enforce_dark_mode_font(content_html)
        else:
            content_html = _enforce_dark_gray_font(content_html)
    if template == "html" and len(content_html) <= PUSHPLUS_MAX_CONTENT_CHARS:
        # 归藏简洁排版的目标：全量内容压进单条消息（一页推）
        print(f"  📄 日报 {len(content_html):,} 字 ≤ 单条上限 "
              f"{PUSHPLUS_MAX_CONTENT_CHARS:,} 字 → 一页推（单条消息，全文不拆不删）")
    if template == "html" and len(content_html) > PUSHPLUS_MAX_CONTENT_CHARS:
        parts = _split_html_for_push(content_html, PUSHPLUS_MAX_CONTENT_CHARS,
                                     report_name) if PUSHPLUS_MULTIPART else None
        # 不再为了减少微信消息条数自动改用 _compact_html_for_push：该函数只保留
        # 纯文本/链接，丢掉 dossier、pixel 等主题的排版与颜色。超过单条上限时
        # 按原 HTML 分条，确保手机收到的版面与 latest.html 完全同款。
        if parts:
            print(f"  📚 日报 {len(content_html):,} 字 > 单条上限 "
                  f"{PUSHPLUS_MAX_CONTENT_CHARS:,} 字 → 已尽量合并为 {len(parts)} 条"
                  f"完整推送（微信会收到 {len(parts)} 条消息，磁盘上仍是一份完整日报）")
            print(f"     ℹ️ 单条上限按账号实际额度设置可减少条数"
                  f"（PushPlus：会员 10 万 / 实名 2 万字，PUSHPLUS_MAX_CONTENT_CHARS 覆盖）")
            return _push_html_parts(title, parts, token=token, topic=topic)
        if PUSHPLUS_MULTIPART:
            print("  ↩️ 已回退到旧的单条推送：按完整标签边界截断 + 末尾附完整日报链接")
        content_html, was_truncated = _truncate_html_for_push(
            content_html, PUSHPLUS_MAX_CONTENT_CHARS, report_name)
        if was_truncated:
            print(f"  ⚠️ 日报 HTML 超过 PushPlus 上限 {PUSHPLUS_MAX_CONTENT_CHARS} 字符，"
                  f"已按完整标签边界截断后推送（磁盘上的完整版不受影响）")
    return _push_one_message(title, content_html, token=token, template=template,
                             topic=topic)


# 已发出的推送请求时刻（time.monotonic），供 PushPlus「1 分钟 N 次请求」的频率限制排队
_PUSH_REQUEST_TIMES = []


def _push_rate_wait(history, now, window=None, limit=None):
    """还差多少秒才允许再发一次请求（保证 window 秒内的请求数 < limit）。

    history：已发出的请求时刻（升序，需已按 window 过滤）；now：当前时刻。
    返回 0 表示可以立刻发。limit <= 0 或 window <= 0 表示不排队。
    """
    window = PUSHPLUS_RATE_WINDOW if window is None else window
    limit = PUSHPLUS_RATE_MAX if limit is None else limit
    if window <= 0 or limit <= 0 or len(history) < limit:
        return 0.0
    return max(0.0, history[len(history) - limit] + window - now)


def _wait_push_rate_limit():
    """按 PushPlus 频率限制主动排队，再放行一次请求。

    PushPlus 对发送接口的限制是「1 分钟内接收 5 次请求，超出的请求将不再推送」。
    分条推送（每条 1 次请求 + 失败重试）容易在几秒内打满额度，被平台直接丢弃——
    旧做法只能等退避重试（10s→30s→60s）反复撞墙。这里改为发请求前先排队：
    窗口内已发满就先等到最早那次请求滑出窗口，既不被丢弃也不浪费重试次数。
    """
    while True:
        now = time.monotonic()
        _PUSH_REQUEST_TIMES[:] = [t for t in _PUSH_REQUEST_TIMES
                                  if now - t < PUSHPLUS_RATE_WINDOW]
        wait = _push_rate_wait(_PUSH_REQUEST_TIMES, now)
        if wait <= 0:
            _PUSH_REQUEST_TIMES.append(now)
            return
        print(f"  ⏳ PushPlus 频率限制（{PUSHPLUS_RATE_WINDOW:g}s 内最多 "
              f"{PUSHPLUS_RATE_MAX} 次请求）：等待 {wait:.0f}s 后再发下一条...")
        time.sleep(wait)


def resolve_push_route(topic=None, mode=None, *, warn=True):
    """解析本次 PushPlus 推送路由 → (mode, topic)。

    mode ∈ {one2many（一对多群组）, one2one（一对一 直发自己）}；topic 为空串表示一对一。
    优先级：显式 ``topic`` 参数 > ``PUSHPLUS_MODE`` + ``PUSHPLUS_TOPIC`` 环境配置。
    - ``topic`` 传非空串 → 一对多，用这个群组编码（手动指定最高优先）；
    - ``topic`` 传空串   → 一对一（显式关闭群组，即便环境里配了群组编码）；
    - 未传 ``topic``     → 按 PUSHPLUS_MODE：one2one 一律一对一；one2many（默认）读
      PUSHPLUS_TOPIC，缺失时 **告警并回退一对一**（不静默降级、不写死编码）。
    未知 PUSHPLUS_MODE 值按默认一对多处理并告警，避免配置写错后悄悄退回一对一。
    """
    mode = str(mode if mode is not None else PUSHPLUS_MODE or PUSH_MODE_ONE2MANY).strip().lower()
    if mode not in PUSH_MODES:
        if warn:
            print(f"  ⚠️ 未知 PUSHPLUS_MODE={mode!r}（可选 one2many / one2one），"
                  f"按默认一对多处理")
        mode = PUSH_MODE_ONE2MANY
    if topic is not None:
        group = str(topic).strip()
        return (PUSH_MODE_ONE2MANY, group) if group else (PUSH_MODE_ONE2ONE, "")
    if mode == PUSH_MODE_ONE2ONE:
        return (PUSH_MODE_ONE2ONE, "")
    group = (PUSHPLUS_TOPIC or "").strip()
    if not group:
        if warn:
            print("  ⚠️ 一对多群组推送需要群组编码：PUSHPLUS_TOPIC 未配置"
                  "（GitHub Secret / 环境变量）→ 本次回退一对一，只发给自己")
        return (PUSH_MODE_ONE2ONE, "")
    return (PUSH_MODE_ONE2MANY, group)


def push_route_text(mode, topic):
    """路由 → 日志文案（一对一 / 一对多群组 <编码>）。"""
    return f"一对多群组 {topic}" if mode == PUSH_MODE_ONE2MANY and topic else "一对一"


def _push_html_parts(title, parts, token=None, topic=None):
    """按顺序推送拆分后的多条正文；全部成功才返回 True。

    - 每条标题追加「(i/N)」，微信消息列表里一眼能看出条序，也避免标题完全重复被去重；
    - 条与条之间等待 PUSHPLUS_PART_DELAY 秒，降低触发「发送频繁」的概率；
    - 发请求前按 PUSHPLUS_RATE_MAX / PUSHPLUS_RATE_WINDOW 主动排队（默认 1 分钟 5 次，
      与 PushPlus 平台限制一致），多分条也能源源送达、不靠退避重试硬撞频率墙；
    - 任意一条最终失败即停止后续条并返回 False（调用方会发失败告警、以退出码 1 结束），
      日志里明确写出「已送达 i-1 条 / 共 N 条」，不掩盖部分送达的事实。
    """
    total = len(parts)
    for index, part in enumerate(parts, 1):
        if index > 1 and PUSHPLUS_PART_DELAY > 0:
            print(f"  ⏳ 等待 {PUSHPLUS_PART_DELAY:g}s 后推送第 {index}/{total} 条"
                  f"（避开 PushPlus 频率限制）...")
            time.sleep(PUSHPLUS_PART_DELAY)
        print(f"  📄 第 {index}/{total} 条（{len(part):,} 字）...")
        if not _push_one_message(f"{title} ({index}/{total})", part, token=token,
                                 template="html", topic=topic):
            print(f"  ❌ 第 {index}/{total} 条推送失败：已送达 {index - 1} 条，"
                  f"剩余 {total - index + 1} 条未发送（完整日报未全部送达）")
            return False
    print(f"  ✅ 完整日报已全部送达（共 {total} 条消息）")
    return True


def _push_one_message(title, content_html, token=None, template="html", topic=None):
    """发送单条 PushPlus 消息（含退避重试）；返回 True/False。

    topic 的路由规则与 push_to_wechat 同一份 resolve_push_route（默认一对多群组，
    缺群组编码时回退一对一）；这里不再重复打印告警，避免分条推送刷屏。
    """
    token = token or PUSHPLUS_TOKEN
    _mode, topic = resolve_push_route(topic, warn=False)
    payload = {
        "token": token,
        "title": title,
        "content": content_html,
        "template": template,
    }
    if topic:
        payload["topic"] = topic
    attempts = (0, *PUSH_RETRY_BACKOFF)
    last_error = "未知错误"

    for attempt, wait in enumerate(attempts, 1):
        if wait:
            print(f"  ⏳ 等待 {wait}s 后进行第 {attempt}/{len(attempts)} 次尝试...")
            time.sleep(wait)
        _wait_push_rate_limit()      # 发请求前按平台频率限制排队（重试同样计入额度）
        http_status = None
        try:
            resp = requests.post(PUSHPLUS_URL, json=payload, timeout=30)
            http_status = getattr(resp, "status_code", None)
            result = resp.json()
        except Exception as exc:
            last_error = f"网络/请求异常: {exc}"
            if http_status is not None:
                kind = _push_failure_kind(http_status, None, str(exc))
            elif isinstance(exc, (ConnectionError, TimeoutError, OSError)):
                # requests 的网络异常（含 SSL/超时/连接重置）都是 OSError 子类，可重试
                kind = "transient"
            else:
                # 编程错误等非网络异常：重试无意义，立即失败并暴露原因
                kind = "unknown"
        else:
            code = result.get("code") if isinstance(result, dict) else None
            msg = str(result.get("msg", "未知错误")) if isinstance(result, dict) else "返回数据格式错误"
            if code == 200:
                print("  ✅ 推送成功！" if attempt == 1 else f"  ✅ 推送成功！（第 {attempt} 次尝试）")
                return True
            last_error = f"PushPlus code={code} msg={msg}"
            kind = _push_failure_kind(http_status, code, msg)

        remaining = len(attempts) - attempt
        if kind == "transient" and remaining > 0:
            print(f"  ⚠️ 第 {attempt}/{len(attempts)} 次推送失败（可重试错误）: {last_error}")
            continue
        if kind == "fatal":
            print(f"  ❌ 推送失败（配额/凭证/内容类错误，重试无意义）: {last_error}")
        else:
            print(f"  ❌ 推送失败: {last_error}")
        return False

    print(f"  ❌ 推送最终失败（已重试 {len(attempts) - 1} 次）: {last_error}")
    return False


def build_no_push_alert_text(reason, data, report_path=None):
    """生成「当天检验未通过」纯文本告警正文（列出每个来源的当天/非当天/无数据状态）。"""
    items = [(k, v) for k, v in (data or {}).items() if isinstance(v, dict)]
    total = len(items)
    content_n = sum(1 for _, v in items if v.get("status") == "success")
    lines = [
        f"📅 当天内容检验未通过（{_now()} 北京时间）",
        f"原因：{reason}",
        f"数据：{content_n}/{total} 个来源抓到内容，且无来源判定为当天，"
        f"已按防旧内容规则不推送日报。",
        "",
        "各来源状态：",
    ]
    for name, s in items:
        if s.get("status") != "success":
            mark = "⚠️ 无数据"
        elif s.get("is_today"):
            mark = "✅ 当天"
        else:
            mark = "🕓 非当天"
        lines.append(f"· {name}：{mark}（数据日期 {s.get('content_date') or '—'}）")
    lines += [
        "",
        "处理建议：",
        "· 周末/休市/源站维护属预期情况，无需处理；",
        "· 确需强制推送：Actions 手动运行并勾选 force_push，"
        "或本地 ./output/manual_push.sh --force。",
        f"报告文件：{os.path.basename(report_path) if report_path else '—'}",
    ]
    return "\n".join(lines)


def push_no_push_alert(reason, data, report_path=None, token=None):
    """推送「当天检验未通过」纯文本告警。

    返回 True/False；返回 False 时调用方应以退出码 1 结束，
    确保 token 缺失 / 接口异常在 Actions 上显红而不是静默。
    """
    print("📣 正在推送「检验未通过」纯文本告警（避免彻底沉默）...")
    title = f"🐙 日报未推送提醒 {datetime.now(CST).strftime('%m/%d %H:%M')}"
    return push_to_wechat(title, build_no_push_alert_text(reason, data, report_path),
                          token=token, template="txt")


def build_push_failure_alert_text(reason, data=None, report_path=None):
    """生成「日报推送失败」兜底告警正文：日报已生成但被 PushPlus 拒绝时，
    让微信侧也能直接看到失败原因和处理建议，而不是只看到 Actions 变红。"""
    lines = [
        f"⚠️ 日报已生成，但推送到微信失败（{_now()} 北京时间）",
        f"原因：{reason}",
        "",
    ]
    if data:
        items = [v for v in data.values() if isinstance(v, dict)]
        today_n = sum(1 for v in items if v.get("is_today"))
        lines.append(f"数据状态：{today_n}/{len(items)} 个来源为当天内容，日报内容本身无问题。")
        lines.append("")
    lines += [
        "处理建议：",
        "· 若日志提示「发送频繁 / 稍后再试 / 服务器繁忙」：属 PushPlus 频率限制，"
        "稍等片刻后在 Actions 重跑一次即可；",
        "· 若提示「发送次数已达上限 / 已用完」：今日 PushPlus 额度已耗尽，次日零点恢复，"
        "或在 PushPlus 升级套餐后更新 Secrets；",
        "· 若提示 token 无效 / 已失效：到 pushplus.plus 重新获取，"
        "并更新仓库 Settings → Secrets → PUSHPLUS_TOKEN；",
        "· 若日报被拆成多条推送（标题带 1/N、2/N…）：任意一条失败就会停止后续条，"
        "微信里只有前几条；重跑一次即可重新完整推送（Actions 手动运行或 manual_push.sh）；",
        "· 手动重新推送：Actions → 🐙 章鱼AI · 手动抓取推送 → Run workflow，"
        "或本地 ./output/manual_push.sh --force。",
        f"报告文件：{os.path.basename(report_path) if report_path else '—'}",
    ]
    return "\n".join(lines)


def push_failure_alert(reason, data=None, report_path=None, token=None):
    """日报推送失败后的兜底告警（template=txt）。

    返回 True/False；本告警只负责「让微信侧感知失败」，不改变调用方的退出码——
    日报未送达，调用方仍应以退出码 1 结束（Actions 显红）。"""
    print("📣 正在发送「推送失败」兜底告警（让微信侧也能看到失败原因）...")
    title = f"🐙 日报推送失败提醒 {datetime.now(CST).strftime('%m/%d %H:%M')}"
    return push_to_wechat(title, build_push_failure_alert_text(reason, data, report_path),
                          token=token, template="txt")


# ============================================================
# 文件保存
# ============================================================
def _atomic_write(path, content):
    """原子替换文件，避免定时任务被中断后留下旧文件或半个 HTML。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _unique_report_path(requested_path):
    """返回不重复的 HTML 路径。

    自动和手动运行都可能在同一天执行多次；日报不能因同名而覆盖上一份。
    冲突时统一追加澳门日期（YYYYMMDD）和三位随机数，例如：
    ``daily_report_20260802_417.html``。循环检查可避免随机数碰撞。
    """
    if not os.path.exists(requested_path):
        return requested_path

    directory = os.path.dirname(os.path.abspath(requested_path))
    extension = os.path.splitext(requested_path)[1] or ".html"
    stem = os.path.splitext(os.path.basename(requested_path))[0]
    date = _today_str()
    for _ in range(1000):
        suffix = f"{random.SystemRandom().randint(0, 999):03d}"
        candidate = os.path.join(directory, f"{stem}_{date}_{suffix}{extension}")
        if not os.path.exists(candidate):
            return candidate

    raise RuntimeError(f"无法为 {requested_path} 找到不重复的日期随机文件名")


def _timestamped_report_path():
    """目标文件被锁定/不可覆盖时使用的全新日期随机文件名。"""
    directory = os.path.abspath(REPORT_DIR)
    date = _today_str()
    for _ in range(1000):
        suffix = f"{random.SystemRandom().randint(0, 999):03d}"
        candidate = os.path.join(directory, f"daily_report_{date}_{suffix}.html")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("无法为锁定的日报找到不重复的日期随机文件名")


def newest_report_path():
    """返回实际最后更新的一份日报，不依赖可能被锁住的 latest.html。"""
    reports = glob.glob(os.path.join(REPORT_DIR, "daily_report_*.html"))
    return max(reports, key=os.path.getmtime) if reports else None


def save_report(html, output_path=None, data=None):
    """保存本次报告；同名或无法覆盖时创建日期+三位随机数的新 HTML。"""
    requested_path = output_path or os.path.join(REPORT_DIR, f"daily_report_{_today_str()}.html")
    # 先检查文件名是否已存在，避免自动/手动重复运行覆盖既有日报。
    target_path = _unique_report_path(requested_path)
    if target_path != requested_path:
        print(f"⚠️ 输出文件已存在: {requested_path}")
        print(f"   本次改用不重复文件: {target_path}")

    try:
        _atomic_write(target_path, html)
        output_path = target_path
        print(f"💾 日报已原子保存: {output_path}")
    except OSError as exc:
        # 文件在检查后被其它进程锁定或抢先创建时，再生成一个日期随机文件。
        output_path = _timestamped_report_path()
        try:
            _atomic_write(output_path, html)
        except OSError as fallback_exc:
            raise RuntimeError(f"无法保存日报（原路径: {exc}；新日期文件: {fallback_exc}）") from fallback_exc
        print(f"⚠️ 无法写入 {target_path}: {exc}")
        print(f"💾 已改存为新的日期文件: {output_path}")

    latest_path = os.path.join(REPORT_DIR, "latest.html")
    try:
        _atomic_write(latest_path, html)
        print(f"💾 最新副本已同步: {latest_path}")
    except OSError as exc:
        # 推送时始终从 output_path 重读，latest 锁定不会导致推送昨天的内容。
        print(f"⚠️ 无法更新 {latest_path}: {exc}")
        print(f"   本次推送将直接使用最新生成文件: {output_path}")

    available = sum(1 for item in (data or {}).values()
                    if isinstance(item, dict) and item.get("status") == "success")
    total = sum(1 for item in (data or {}).values() if isinstance(item, dict))
    print(f"📊 数据源状态: {available}/{total} 可用（不可用项已在报告中标注）")
    return output_path


# ============================================================
# 列出日报
# ============================================================
def list_reports():
    """列出所有已生成的日报文件"""
    pattern = os.path.join(REPORT_DIR, "daily_report_*.html")
    files = sorted(glob.glob(pattern), reverse=True)

    if not files:
        print("暂无日报文件。")
        return 0

    print(f"\n共找到 {len(files)} 份日报：\n")
    for idx, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        size = os.path.getsize(filepath)
        mtime = datetime.fromtimestamp(os.path.getmtime(filepath), CST)
        print(f"  {idx:2d}. {filename}  ({size:,} 字节)  [{mtime.strftime('%Y-%m-%d %H:%M')}]")
    return 0


# ============================================================
# 清理旧的 HTML 报告
# ============================================================
def clean_old_html_reports(keep_latest=False, keep=()):
    """清理 output/ 目录下的旧 HTML 报告（daily_report_*.html + latest.html）。

    必须在新报告已成功保存之后调用（main() 第 4 步之后），确保推送的日报是"最新且唯一"的内容。
    若在生成之前清理，采集/生成一旦崩溃，工作区里就没有任何日报，workflow 的 git add
    会把空 glob 当作删除整批历史日报提交（2026-10-14 事故）。

    参数:
        keep_latest: True 时保留 latest.html（仅清 daily_report_*.html）；
                     默认 False：两个都清。
        keep: 需要保留的路径序列（如刚保存的本次日报），不会被删除。
    返回:
        (删除的 daily_report 数, 是否删了 latest.html)
    """
    deleted = 0
    latest_deleted = False
    keep_set = {os.path.abspath(p) for p in keep}

    # 1) 清理 daily_report_*.html
    pattern = os.path.join(REPORT_DIR, "daily_report_*.html")
    for filepath in glob.glob(pattern):
        if os.path.abspath(filepath) in keep_set:
            continue
        try:
            os.remove(filepath)
            deleted += 1
        except OSError as exc:
            print(f"⚠️ 清理失败: {filepath} ({exc})")

    # 2) 清理 latest.html（除非显式保留）
    latest_path = os.path.join(REPORT_DIR, "latest.html")
    if not keep_latest and os.path.isfile(latest_path):
        try:
            os.remove(latest_path)
            latest_deleted = True
        except OSError as exc:
            print(f"⚠️ 清理失败: {latest_path} ({exc})")

    if deleted or latest_deleted:
        parts = []
        if deleted:
            parts.append(f"{deleted} 份 daily_report_*.html")
        if latest_deleted:
            parts.append("latest.html")
        print(f"🧹 已清理历史 HTML 报告: {', '.join(parts)}")
    return deleted, latest_deleted


# ============================================================
# 推送前的当天内容检验
# ============================================================
def check_push_eligibility(data):
    """根据采集结果判断是否允许推送。

    返回 (can_push, reason)。
    规则：
      - 没有任何来源抓到内容 → 不推送；
      - 有内容但没有任何来源属于「当天」→ 不推送（防旧内容）；
      - 否则可推送。
    """
    items = [v for v in data.values() if isinstance(v, dict)]
    content_n = sum(1 for v in items if v.get("status") == "success")
    today_n = sum(1 for v in items if v.get("is_today"))
    total = len(items)

    if content_n == 0:
        return False, f"全部数据源均未抓到内容（0/{total}）"
    if today_n == 0:
        return False, f"抓到 {content_n}/{total} 个来源，但没有一个属于当天内容（当天检验未通过）"
    snapshots = sum(1 for v in items if v.get("snapshot"))
    suffix = f"（其中 {snapshots} 个仅为今日抓取快照，非当日发布）" if snapshots else ""
    return True, f"当天检验通过：{today_n}/{total} 个来源含当天内容或今日抓取快照{suffix}"


# ============================================================
# 主函数
# ============================================================
def quant_only_report(*, enable_stocks=True):
    """只跑港股量化引擎并打印结果（研究 / 排障用，不生成日报、不推送）。"""
    print("🐙 " + "=" * 48)
    print("   章鱼 AI · 港股量化引擎（研究模式）")
    print("🐙 " + "=" * 48)
    res = _quant.run_quant(
        safe_request,
        history_path=os.path.join(REPORT_DIR, QUANT_HISTORY_FILENAME),
        enable_stocks=enable_stocks)
    if not res.get("available"):
        print(f"❌ 量化引擎不可用：{res.get('reason')}")
        return 1

    head = res.get("headline") or {}
    print(f"\n【预测概括】{head.get('text', '—')}")
    print(f"【数据基准】{res.get('as_of')} → 目标 {res.get('target_label')}")

    print("\n【指数概率】")
    print(f"  {'标的':<8}{'现价':>12}{'1日':>8}{'5日':>8}{'20日':>8}{'样本':>7}{'趋势':>10}")
    for row in res["indices"]:
        p = row["probs"]
        fmt = lambda v: f"{v*100:5.1f}%" if v is not None else "    —"
        print(f"  {row['label']:<8}{row['feat']['close']:>12,.0f}"
              f"{fmt(p[1]['p_up']):>8}{fmt(p[5]['p_up']):>8}{fmt(p[20]['p_up']):>8}"
              f"{p[5]['samples']:>7}{row['trend']['label']:>10}")

    for h, row in sorted((res.get("validation") or {}).items()):
        if not row:
            continue
        z = row.get("z")
        print(f"\n【{h}日推进式回测】样本 {row['n']} · 命中 {row['hit_rate']*100:.1f}%"
              f" · 基准 {row['base_rate']*100:.1f}%"
              f" · z={z:+.2f}" if z is not None else "")
        if row.get("brier") is not None:
            print(f"  Brier {row['brier']:.3f} · 对数损失 {row.get('log_loss') or 0:.3f}")
        for c in row.get("reliability") or []:
            print(f"  预测 {c['lo']*100:5.1f}–{c['hi']*100:5.1f}%  n={c['n']:<4}"
                  f"  实际 {c['actual']*100:5.1f}%")

    liq = res.get("liquidity") or {}
    if liq.get("available"):
        print("\n【资金流动性】")
        print(f"  综合分 {liq.get('score') or 0:.0f}/100 · {liq.get('label')}")
        print(f"  {liq.get('summary')}")
        for key, label in (("south", "南向"), ("north", "北向")):
            st = liq.get(key) or {}
            if st.get("available"):
                print(f"  {label}：最新 {st['latest']:,.0f} 亿 · 环比 "
                      f"{(st.get('chg_pct') or 0):+.1f}% · 20日均 {st['ma20']:,.0f} 亿"
                      f" · z={(st.get('z20') or 0):+.2f} · {(st.get('date') or '')}")
        for name, comp in (liq.get("components") or {}).items():
            print(f"   · {name:<9} {comp['score']:5.1f} 分（权重 "
                  f"{comp.get('weight', 0)*100:.0f}%） {comp.get('note') or ''}")

    if res.get("stocks"):
        print("\n【个股概率（按 5 日排序）】")
        for row in sorted(res["stocks"], key=lambda r: -((r["probs"][5]["p_up"] or 0))):
            print(f"  {row['label']:<12}{row['probs'][5]['p_up']*100:6.1f}%"
                  f"  综合分 {row['score']:+.2f}  样本 {row['probs'][5]['samples']}")
    jr = res.get("journal") or {}
    if jr.get("n"):
        print(f"\n【预测留痕】已结算 {jr['n']} 次 · 方向命中 "
              f"{(jr.get('hit_rate') or 0)*100:.0f}%")
    print("\n✅ 量化引擎运行完成（研究模式不推送）")
    return 0


def weekly_only_report():
    """只跑【嗜血大白鲨】逐日走势量化分析并打印结果（研究 / 排障用，不生成日报、不推送）。"""
    print("🐙 " + "=" * 48)
    print("   章鱼 AI · 量化走势预测（未来 7 个交易日 · 研究模式）")
    print("🐙 " + "=" * 48)
    res = fetch_weekly_forecast()
    if res.get("status") != "success":
        print(f"❌ 量化走势预测不可用：{res.get('error')}")
        return 1
    r = res.get("result") or {}
    entry = r.get("entry") or {}
    daily = r.get("daily") or {}
    drows = daily.get("rows") or []
    if drows:
        print(f"\n【逐日表格】未来 {len(drows)} 个交易日"
              f"（锚定 {daily.get('base_date')} 收盘 {daily.get('base_close'):,.0f}"
              f" · {daily.get('symbol_label')}）")
        print(f"  {'交易日':<14}{'预测':<16}{'当日环比':>8}{'预期区间':>20}{'仓位':>7}")
        for row in drows:
            adv = row.get("advice") or {}
            p_day = row.get("p_day")
            dod = "—" if p_day is None else f"{p_day * 100:.0f}%"
            band = f'{row.get("band_lo"):,.0f}–{row.get("band_hi"):,.0f}'
            tag = f'T+{row.get("k")} {str(row.get("date"))[5:]} {row.get("weekday")}'
            print(f'  {tag:<14}{row.get("label"):<16}{dod:>8}{band:>20}'
                  f'{"≤" + str(adv.get("position")) + "%":>7}')
        print("\n【逐日理由 / 分析 / AI 操作建议】")
        for row in drows:
            adv = row.get("advice") or {}
            print(f'  T+{row.get("k")} {str(row.get("date"))[5:]} {row.get("weekday")}'
                  f' · {adv.get("stance")}')
            print(f'    理由：{row.get("reason")}')
            print(f'    分析：{row.get("analysis")}')
            print(f'    建议：仓位 ≤{adv.get("position")}% · '
                  f'止损 {adv.get("stop_pct") * 100:.1f}%'
                  f'（{adv.get("stop_price"):,.0f}）· 止盈参考 {adv.get("take_profit"):,.0f}'
                  f' · {adv.get("entry_hint")}')
    print(f"\n【七日整段结论】{entry.get('label')}")
    print(f"  锚定 {entry.get('base_date')} 收盘（{entry.get('symbol_label')}）"
          f" → 未来 {entry.get('target_sessions')} 个交易日")
    print(f"  概率拆解：P(7日涨)={entry.get('p_up'):.3f}"
          f" · 基准 {entry.get('p_base'):.3f}"
          f" · 相似样本 {entry.get('p_sim') if entry.get('p_sim') is not None else '—'}"
          f"（{entry.get('n_analog')} 近邻 / 已结算 {entry.get('n_resolved')} 个样本）")
    bt = r.get("backtest") or {}
    if bt.get("hit_rate") is not None:
        print(f"\n【滚动样本外】{bt['n']} 期 · 命中 {bt['hit_rate']*100:.1f}%"
              f" · 恒定基准 {bt['base_rate']*100:.1f}% · Brier {bt['brier']:.3f}")
    else:
        print(f"\n【滚动样本外】{bt.get('note')}")
    jr = r.get("journal") or {}
    if jr.get("n"):
        rate = (f"命中 {jr['hits']}（{jr['hit_rate']*100:.0f}%）"
                if jr.get("hit_rate") is not None else "样本 <10，只报样本量")
        print(f"【预测留痕】已结算 {jr['n']} 次 · {rate}")
        for item in jr.get("recent") or []:
            print(f"  {item.get('date')} {item.get('ret')*100:+.1f}%"
                  f" {'✓' if item.get('hit') else '✗'}")
    else:
        print("【预测留痕】暂无已结算样本")
    print(f"\n【未来函数自检】{r.get('self_check')}")
    print("✅ 量化走势预测运行完成（研究模式不推送）")
    return 0



def hk7_only_report():
    """只跑 AI 七日港股走势分析概率并打印结果（研究 / 排障用，不生成日报、不推送）。"""
    print("🐙 " + "=" * 48)
    print("   章鱼 AI · AI 七日港股走势分析概率（研究模式）")
    print("🐙 " + "=" * 48)
    res = fetch_hk_seven_day({})
    if res is None:
        print("⏭ 本栏目缺席：未配置大模型 API Key（OCTOPUS_LLM_API_KEY）或本次已关闭"
              "（OCTOPUS_HK7=0 / --no-hk7）。")
        print("   如需没有 Key 也看量化基准：OCTOPUS_HK7_FALLBACK=1")
        return 1
    if res.get("status") != "success":
        print(f"❌ 不可用：{res.get('error')}")
        return 1
    r = res.get("result") or {}
    target_dt_str = f"（至目标日 {r.get('target_date')}）" if r.get('target_date') else ""
    print(f"\n【锚定】{r.get('asof')} 收盘 · 未来 {r.get('horizon')} 个交易日{target_dt_str}"
          f" · 引擎：{r.get('engine_label')}")
    if r.get("engine") == "jev":
        print(f"  Jev 状态：{_hk7_jev_note(r)}")
    elif r.get("engine") != "llm":
        print(f"  大模型降级原因：{r.get('llm_reason')} · Jev：{_hk7_jev_note(r)}")
        hint = _hk7.llm_error_hint(r.get("llm_reason"))
        if hint:
            print(f"  🛠 下一步：{hint}")
    print("─" * 60)
    for t in r.get("targets") or []:
        print(f"\n  {t['name']}（{t['code']}） {t['label']}")
        print(f"    现价 {t['close']:,.2f} · 5日 {t['ret5'] * 100:+.1f}%"
              f" · 20日 {t['ret20'] * 100:+.1f}% · RSI14 {t['rsi14']:.1f}"
              f" · 年化波动 {t['vol20'] * 100:.1f}%")
        if t.get("factor_summary"):
            print(f"    核心因子：{t['factor_summary']}")
        print(f"    95% 区间 {t['lo95']:,.0f} – {t['hi95']:,.0f}（n={t['var_n']}）"
              f" · 量化基准 {t['quant_p_up'] * 100:.1f}%"
              f" · 偏离 {t['deviation'] * 100:+.1f}pp"
              + ("（已收敛）" if t.get("converged") else ""))
        for d in t.get("drivers") or []:
            print(f"    依据：{d}")
        for d in t.get("risks") or []:
            print(f"    风险：{d}")
        bt = t.get("backtest") or {}
        if bt.get("hit_rate") is not None:
            print(f"    滚动样本外：{bt['n']} 期 · 命中 {bt['hit_rate'] * 100:.1f}%"
                  f" · 恒定基准 {bt['base_rate'] * 100:.1f}% · Brier {bt['brier']:.3f}")
        elif bt.get("note"):
            print(f"    滚动样本外：{bt['note']}")
        print("─" * 60)
    jr = r.get("journal") or {}
    print(f"\n【预测留痕】已结算 {jr.get('n')} 个样本 · 在途 {jr.get('standing')}"
          + (f" · 方向命中 {jr.get('hits')}（{(jr.get('hit_rate') or 0) * 100:.0f}%）"
             if jr.get("hit_rate") is not None else "（样本 <10 只报样本量）"))
    print("─" * 60)
    print("\n✅ 研究模式不推送")
    return 0

def llm_check_report():
    """大模型 API 探活（研究 / 排障用：不抓行情、不生成日报、不推送、不写留痕）。

    回答的是「这台机器 / 这次运行里，AI 七日港股走势分析概率这一栏到底能不能出内容」：
      · 用的是哪个变量名提供的 Key（只报名字与长度，绝不回显 Key）；
      · 端点与模型：显式指定还是走候选链；
      · {base}/models 目录里到底有哪些模型可选（端点不支持就如实标注）；
      · 逐个候选模型发一次真实 JSON 请求，看鉴权、模型名、JSON 合同三层是否都通。
    """
    print("🐙 " + "=" * 48)
    print("   章鱼 AI · 大模型 API 探活（不生成日报、不推送）")
    print("🐙 " + "=" * 48)
    probe = _hk7.llm_probe()
    view = probe.get("config") or {}
    print("\n【配置】")
    if view.get("key_source"):
        print(f"  Key 来源：{view['key_source']}（长度 {view.get('key_len')}；只报来源，不回显）")
    else:
        print("  Key 来源：未配置（可用变量名：" + "、".join(_hk7.ENV_KEY_NAMES) + "）")
    print(f"  端点：{view.get('base')}"
          + (f"（来源 {view['base_source']}）" if view.get("base_source") else "（默认值，未设置变量）"))
    if view.get("model_explicit"):
        print(f"  模型：{view.get('model')}（显式指定，来源 {view.get('model_source')}）")
    else:
        print(f"  模型：未显式指定 → 默认 {view.get('model')}，候选链 "
              + " → ".join(_hk7.MODEL_FALLBACKS[: _hk7.MODEL_ATTEMPTS_MAX]))
    print(f"  超时：{view.get('timeout')} 秒 · max_tokens："
          f"{view.get('max_tokens') or '未设置（用服务端默认）'} · 降级口径：{view.get('fallback')}")
    cat = probe.get("catalog") or {}
    print(f"\n【模型目录 {str(view.get('base') or '').rstrip('/')}/models】")
    if cat.get("ok"):
        print("  可选模型：" + "、".join(cat.get("ids") or []))
    else:
        print(f"  读不到目录：{cat.get('reason') or '未尝试'}（不影响下面的逐个探活）")
    attempts = probe.get("attempts") or []
    print(f"\n【逐模型探活】共 {len(attempts)} 次请求")
    for row in attempts:
        mark = "✅" if row.get("ok") else "❌"
        extra = (" · targets " + "、".join(row.get("targets") or [])) if row.get("targets") else ""
        if row.get("field_ok"):
            extra += " · p_up 在 5%~95% 内"
        print(f"  {mark} {row.get('model')} · {row.get('ms')} ms{extra}")
        if row.get("error"):
            print(f"      错误：{row['error']}")
        if row.get("hint"):
            print(f"      提示：{row['hint']}")
    for p in probe.get("problems") or []:
        print(f"  ⚠️ {p}")
    print(f"\n{'✅' if probe.get('ok') else '❌'} 结论：{probe.get('verdict')}")
    if not probe.get("ok"):
        print("  → Key 可用但模型名对不上时：显式设置 OCTOPUS_LLM_MODEL 为目录里的名字，"
              "或留空让候选链自动挑。")
        print("  → Key 没配时：仓库 Settings → Secrets and variables → Actions 新增 "
              "DEEPSEEK_API_KEY（或 OCTOPUS_LLM_API_KEY）后重跑本探活。")
    print("\n（本探活不抓行情、不生成日报、不推送、不写留痕）")
    return 0 if probe.get("ok") else 1


def calendar_only_report(days=None):
    """只抓「时间节点」（原「未来 N 天影响经济时间点」）并打印（研究 / 排障用：不生成日报、不推送）。

    用途：本地或 Actions 里单独验证东财财经日历接口是否可读、筛选口径是否合适，
    不必跑完整条采集链路。
    """
    print("🐙 " + "=" * 48)
    print("   章鱼 AI · 时间节点（未来影响经济时间点 · 研究模式）")
    print("🐙 " + "=" * 48)
    res = fetch_econ_calendar(days=days)
    if res.get("status") != "success":
        print(f"❌ 财经日历暂缺：{res.get('error')}")
        return 1
    digest = _cal_digest(res)
    print(f"\n【窗口】{res.get('window')}")
    for label, value in digest.get("pairs") or []:
        print(f"【{label}】{value}")
    print(f"\n【逐日时间点】共 {len(res.get('items') or [])} 条（北京时间）")
    for _date, label, t_plus, items in digest.get("days") or []:
        when = _cal_countdown(t_plus)
        print(f"\n  {label}" + (f" · {when}" if when else ""))
        for it in items:
            city = str(it.get("city") or "")
            print(f"    {it.get('time') or '--:--'}  {'★' * int(it.get('imp') or 1):<3} "
                  f"{city:<6}{_cal_item_text(it)}")
    print("\n✅ 财经日历运行完成（研究模式不推送）")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="🐙 章鱼 AI · 上水日报 ——「每日上水，新鲜活泼」· 每日财经日报流水线（当天检验后推送）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 output/pipeline.py                        # 全流程（当天检验通过才推送）
  python3 output/pipeline.py --no-push              # 只生成，不推送
  python3 output/pipeline.py --dry-run              # 采集+预览，不推送
  python3 output/pipeline.py -o custom.html         # 指定输出路径
  python3 output/pipeline.py --manual               # 手动推送模式（重新抓取并推送）
  python3 output/pipeline.py --manual --force-push  # 手动强制推送（内容非当天也推，谨慎）
  python3 output/pipeline.py --push-only            # 推送实际最后更新的一份日报（再次当天检验）
  python3 output/pipeline.py --push-only path/to/report.html
  python3 output/pipeline.py --list                 # 列出日报
  python3 output/pipeline.py --no-quant             # 跳过港股量化引擎（运行更快）
  python3 output/pipeline.py --quant-only           # 只跑量化引擎并打印概率/流动性/回测
  python3 output/pipeline.py --no-weekly            # 跳过每周量化走势预测
  python3 output/pipeline.py --weekly-only          # 只跑每周预测并打印方向/概率/回测/留痕
  python3 output/pipeline.py --hk7-only             # 只跑 AI 七日港股走势分析概率并打印
  python3 output/pipeline.py --no-hk7               # 跳过 AI 七日港股走势分析概率
  python3 output/pipeline.py --llm-check            # 只探活大模型 API（Key/端点/模型名，不生成日报）
  python3 output/pipeline.py --calendar-only        # 只抓「时间节点」（未来30天影响经济时间点）并打印
  python3 output/pipeline.py --calendar-only 7      # 同上，窗口改成未来 7 天
  python3 output/pipeline.py --theme lime          # 默认：白底圆角卡片 + 荧光绿强调风
  python3 output/pipeline.py --theme pixel         # 改用 DOS 复古监视器 / Retro Pixel Market Quest
  python3 output/pipeline.py --theme forum         # 改用 forum 暗色社区仪表盘
  python3 output/pipeline.py --theme dossier       # 改用德国档案风 + 包豪斯几何
  python3 output/pipeline.py --theme guizang       # 改用归藏白底研报
  python3 output/pipeline.py --notes                # 精简版面里保留说明文字 / 过程文字（默认入门版不出）
  python3 output/pipeline.py --full                 # 全量长版：长文 / 表格 / 方法论注释全部回来
        """
    )

    parser.add_argument("--no-push", action="store_true",
                       help="只生成日报，不推送到微信")
    parser.add_argument("--dry-run", action="store_true",
                       help="采集数据并预览，不生成文件也不推送")
    parser.add_argument("-o", "--output", type=str, default=None,
                       help="指定输出文件路径")
    parser.add_argument("--manual", action="store_true",
                       help="手动推送模式：重新抓取→生成→当天检验→推送")
    parser.add_argument("--force-push", action="store_true",
                       help="当天检验未通过时仍强制推送（谨慎）")
    parser.add_argument("--push-only", nargs="?", const="__LATEST__", default=None,
                       help="推送实际最后更新的日报；也可指定带新鲜度标记的文件（再次执行当天检验）")
    parser.add_argument("--force-push-old", action="store_true",
                       help="允许 --push-only 推送未带新鲜度标记的旧版日报（不推荐）")
    parser.add_argument("--allow-incomplete-push", action="store_true",
                       help="当本次所有数据源均不可用时仍推送状态报告（默认不推送）")
    parser.add_argument("--theme", default=None, choices=list(PUSH_THEMES),
                       help="推送主题：lime（默认 · 白底圆角卡片+荧光绿）/ pixel（DOS 复古监视器）"
                         " / forum（暗色社区仪表盘）/ dossier（德国文件档案风+包豪斯）/ guizang（白底研报）")
    parser.add_argument("--list", action="store_true",
                       help="列出已生成的日报")
    parser.add_argument("--no-quant", action="store_true",
                       help="跳过港股量化引擎（只出常规栏目，运行更快）")
    parser.add_argument("--quant-only", action="store_true",
                       help="只跑港股量化引擎并打印结果（研究模式：不生成日报、不推送）")
    parser.add_argument("--no-weekly", action="store_true",
                       help="跳过每周量化走势预测（只出常规栏目，运行更快）")
    parser.add_argument("--no-ren", action="store_true",
                       help="关闭逐栏目「🦑 AI帮你提鲜」大白话翻译块（默认开启）")
    parser.add_argument("--full", action="store_true",
                       help="关闭精简模式：不出「【闪电飞鱼】短线速查卡」，各栏长文 / 表格 / "
                            "方法论注释回到全量长版（等价 OCTOPUS_LITE=0）")
    parser.add_argument("--notes", action="store_true",
                       help="精简版面里保留说明文字 / 过程文字（计算口径、数据来源、折叠披露等；"
                            "默认入门版不渲染，等价 OCTOPUS_NOTES=1）")
    parser.add_argument("--no-uzi-trend", action="store_true",
                        help="关闭【游资剑鱼】多专家流派趋势分析栏目（等价 OCTOPUS_UZI_TREND=0）")
    parser.add_argument("--no-hk7", action="store_true",
                       help="跳过 AI 七日港股走势分析概率（只出常规栏目，运行更快）")
    parser.add_argument("--hk7-only", action="store_true",
                       help="只跑 AI 七日港股走势分析概率并打印结果（研究模式：不生成日报、不推送）")
    parser.add_argument("--llm-check", action="store_true",
                       help="只探活大模型 API：读配置、列 /models 目录、逐个候选模型发一次 JSON "
                            "请求（研究模式：不抓行情、不生成日报、不推送、不写留痕）")
    parser.add_argument("--weekly-only", action="store_true",
                       help="只跑每周量化走势预测并打印结果（研究模式：不生成日报、不推送）")
    parser.add_argument("--sources", action="store_true",
                       help="打印全部数据线的主源 / 两个备用源清单（不联网、不生成日报）")
    parser.add_argument("--calendar-only", nargs="?", const=-1, default=None, type=int,
                       help="只抓「时间节点」（原「未来 N 天影响经济时间点」）并打印（研究模式：不生成日报、不推送；"
                            "不带数字时用 OCTOPUS_CALENDAR_DAYS，默认 30 天）")

    # 隐藏功能：市场数据库（2026-10-01）——供 AI 分析 / 预测 / 建模用的多源快照库。
    # 不进日报、不推送，所以 --help 里不显示（help=argparse.SUPPRESS），入口见 output/market_db.py。
    parser.add_argument("--stock-db", nargs="?", const="pull", default=None,
                       choices=["pull", "verify", "export", "stats", "ai-context", "prune"],
                       help=argparse.SUPPRESS)
    parser.add_argument("--stock-db-slot", default="auto", help=argparse.SUPPRESS)
    parser.add_argument("--stock-db-out", default="", help=argparse.SUPPRESS)
    parser.add_argument("--stock-db-format", default="jsonl", help=argparse.SUPPRESS)
    parser.add_argument("--stock-db-days", type=int, default=7, help=argparse.SUPPRESS)
    parser.add_argument("--stock-db-date", default="", help=argparse.SUPPRESS)
    parser.add_argument("--stock-db-symbols", default="", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.no_quant:
        global HK_QUANT_ENABLED
        HK_QUANT_ENABLED = False

    if args.no_weekly:
        global WEEKLY_ENABLED
        WEEKLY_ENABLED = False

    if args.no_ren:
        global REN_ENABLED
        REN_ENABLED = False

    if args.full:
        global LITE_ENABLED
        LITE_ENABLED = False
        _quant.render.LITE = False      # 量化呈现层同步回全量长版
    if args.notes:
        set_notes_requested(True)       # 精简版面 + 说明文字（入门版关闭）

    if args.no_uzi_trend:
        global UZI_TREND_ENABLED
        UZI_TREND_ENABLED = False

    if args.no_hk7:
        global HK7_ENABLED
        HK7_ENABLED = False

    # --stock-db 模式：隐藏功能「市场数据库」（不进日报、不推送；--help 不显示）
    if args.stock_db:
        if SCRIPT_DIR not in sys.path:
            sys.path.insert(0, SCRIPT_DIR)
        import importlib
        market_db = importlib.import_module("market_db")
        argv = [args.stock_db]
        if args.stock_db == "pull":
            argv += ["--slot", args.stock_db_slot]
            if args.stock_db_symbols:
                argv += ["--symbols", args.stock_db_symbols]
        elif args.stock_db == "export":
            if not args.stock_db_out:
                print("❌ --stock-db export 需要 --stock-db-out 指定输出文件")
                return 2
            argv += ["--out", args.stock_db_out, "--format", args.stock_db_format]
            if args.stock_db_symbols:
                argv += ["--symbols", args.stock_db_symbols]
        elif args.stock_db == "stats":
            argv += ["--days", str(args.stock_db_days)]
        elif args.stock_db == "prune":
            argv += ["--keep-days", str(args.stock_db_days)]
        elif args.stock_db == "verify":
            argv += (["--date", args.stock_db_date] if args.stock_db_date else ["--all"])
        elif args.stock_db == "ai-context":
            if args.stock_db_date:
                argv += ["--date", args.stock_db_date]
            if args.stock_db_symbols:
                argv += ["--symbols", args.stock_db_symbols]
        return market_db.main(argv)

    # --list 模式
    if args.list:
        return list_reports()

    # --sources 模式：数据线主备清单
    if args.sources:
        print(_backup.describe())
        return 0

    # --quant-only 模式：只跑量化引擎，把概率 / 流动性 / 回测打到控制台
    if args.quant_only:
        return quant_only_report(enable_stocks=HK_QUANT_STOCKS)

    # --weekly-only 模式：只跑每周量化走势预测，把方向 / 概率 / 回测 / 留痕打到控制台
    if args.weekly_only:
        return weekly_only_report()

    # --llm-check 模式：只探活大模型 API（Key 来源 / 端点 / 模型名 / JSON 合同）
    if args.llm_check:
        return llm_check_report()

    # --hk7-only 模式：只跑 AI 七日港股走势分析概率，把三只指数的概率 / 依据打到控制台
    if args.hk7_only:
        return hk7_only_report()

    # --calendar-only 模式：只抓「时间节点」栏目的未来 N 天影响经济时间点，验证接口与筛选口径
    if args.calendar_only is not None:
        return calendar_only_report(days=None if args.calendar_only < 1 else args.calendar_only)

    # --push-only 模式：推送已有文件，同样执行「当天检验」
    if args.push_only:
        if args.theme:
            print("⚠️ --push-only 只发送已有 HTML；--theme 不会给旧文件换肤。"
                  "请重新生成日报后再推送。")
        push_path = newest_report_path() if args.push_only == "__LATEST__" else args.push_only
        if not push_path or not os.path.isfile(push_path):
            print(f"❌ 文件不存在: {push_path or '没有可推送的日报'}")
            return 1
        print(f"📎 本次推送 HTML: {push_path}")
        with open(push_path, "r", encoding="utf-8") as f:
            html = f.read()

        meta = _report_meta(html)
        today = _today_str()
        forced = args.force_push or args.force_push_old
        if not meta.get("date") and not forced:
            # 旧版文件：没有「当天检验」元信息，无法确认是否当天 → 默认拒绝
            print("❌ 拒绝推送旧版日报：文件没有当天检验元信息（octopus-report-date）。")
            print("   请先运行 pipeline.py 重新生成，或在确认风险后添加 --force-push / --force-push-old。")
            return 1
        if meta["date"] != today and not forced:
            print(f"❌ 拒绝推送：报告日期 {meta['date']} ≠ 今天 {today}（当天检验未通过）")
            print("   请重新生成，或使用 --force-push 强制推送。")
            return 1
        if meta["today_sources"] < 1 and not forced:
            print(f"❌ 拒绝推送：该日报 {meta['today_sources']}/{meta['total_sources']} 个数据源为当天内容（当天检验未通过）")
            print("   请重新生成，或使用 --force-push 强制推送。")
            return 1

        title = build_push_title()
        if push_to_wechat(title, html, report_name=os.path.basename(push_path)):
            print("\n🎉 全部完成！")
            return 0
        push_failure_alert("通过 --push-only 推送日报被 PushPlus 拒绝（详见上方 code/msg）",
                           report_path=push_path)
        print("\n❌ 推送未成功（退出码 1；在 GitHub Actions 中将标红提醒）。")
        return 1

    # 正常流程
    mode = "🖐 手动推送模式" if args.manual else "每日自动模式"
    theme = _resolve_push_theme(args.theme)
    print("🐙 " + "=" * 48)
    print(f"   {REPORT_TITLE} ·「{REPORT_TAGLINE}」· 全网多模型协同 · 每日财经日报（{mode}）")
    print("🐙 " + "=" * 48)
    print(f"   运行时间: {_now()}")
    print(f"   推送主题: {theme}（OCTOPUS_PUSH_THEME / --theme 可切换）")
    print("   版面模式: " + (
        (f"入门版（精简 + 不出说明文字 / 过程文字；短线速查卡 ≤{_short.CARD_CHAR_BUDGET} 字；"
         "--notes 找回说明文字，--full 回全量长版）" if PLAIN() else
         f"精简 + 说明文字（短线速查卡 ≤{_short.CARD_CHAR_BUDGET} 字 + 全篇瘦身；--full 回全量长版）")
        if LITE_ENABLED else "全量长版（--full / OCTOPUS_LITE=0）"))

    # 注意：历史 HTML 清理放在第 4 步「新报告保存之后」（见下方），
    # 不能在采集/生成之前清理——否则中途崩溃会让工作区没有任何日报，
    # 导致 workflow 把整批历史日报当作删除提交（2026-10-14 事故）。

    # 1. 采集数据
    data = collect_all_data()

    # 1.5 情绪历史：加载跨日基线供新闻情绪用（只读；落盘在报告保存后，
    #     --dry-run 只读不写；缺失/损坏按冷启动处理，不中断日报）
    senti_history_path = os.path.join(REPORT_DIR, SENTIMENT_HISTORY_FILENAME)
    senti_history = _load_sentiment_history(senti_history_path)

    # 1.5b 新闻标题存档：加载并把本次抓取标题并入（多日窗口 15 日/72h 的内容基础；
    #     同日重复运行按 日期+标题 去重幂等；读取失败只告警。落盘在报告保存后；
    #     --dry-run 只读不写）
    news_history_path = os.path.join(REPORT_DIR, NEWS_HISTORY_FILENAME)
    date_str = _today_str()
    fresh_items = _collect_headline_items(data, _today_display())
    news_corpus = _merge_news_corpus(_load_news_corpus(news_history_path), fresh_items)

    # 1.6 政策因子：抓取后、推送前单独做政策冲击分析（归入专业分析栏目组；
    #     近 POLICY_WINDOW_DAYS=15 日窗口内无政策/宏观新闻时栏目缺席，不伪造）
    policy_result = build_policy_factor(data, date_str, news_corpus)
    if policy_result.get("available"):
        print(f"  📊 政策因子：{policy_result['summary']}")
    else:
        print(f"  📊 政策因子：近{POLICY_WINDOW_DAYS}日窗口内无显著政策新闻，栏目缺席")

    # 2. 生成报告
    print("\n📝 正在生成日报...")
    date_display = _date_display()
    html = generate_report(data, date_display, date_str, theme=theme,
                           sentiment_history=senti_history,
                           policy_result=policy_result,
                           news_corpus=news_corpus)
    print("  ✅ 日报生成完成")

    # 3. dry-run 模式
    if args.dry_run:
        print("\n🔍 预览模式（不推送、不保存）")
        print(f"   数据源: 港股名家频道({len(data.get('港股名家频道', {}).get('channels', []))}频道可抓取) | "
              f"全球头条({len(data.get('全球头条', {}).get('headlines', []))}条) | "
              f"东财快讯({len(data.get('东财快讯', {}).get('headlines', []))}条) | "
              f"热门榜({sum(len(m.get('stocks', [])) for m in data.get('热门榜单', {}).get('markets', {}).values())}只)")
        return 0

    # 4. 保存文件
    output_path = save_report(html, args.output, data)
    # 4.1 清理历史 HTML：新报告与 latest.html 已写好之后才清理，保留本次日报；
    #     --dry-run 已在上方返回，不会走到这里。
    #     latest.html 刚被 save_report 覆盖为新内容，故 keep_latest=True。
    clean_old_html_reports(keep_latest=True, keep=(output_path,))
    # 4.5 历史落盘：把今日个股情绪计数并入跨日基线、把本次标题并入标题存档
    #     （同日多次运行按日期键/日期+标题覆盖去重，幂等；失败只告警，不影响推送）
    try:
        senti_today = build_news_sentiment(data, date_str, senti_history,
                                           news_corpus=news_corpus)
        _save_sentiment_history(
            senti_history_path,
            _update_sentiment_history(senti_history, date_str,
                                      senti_today["universe"],
                                      senti_today["today_counts"]))
    except OSError as exc:
        print(f"  ⚠️ 情绪历史保存失败（{exc}），不影响本次日报与推送")
    try:
        anchor_date = _factor_anchor_dt(date_str).strftime("%Y-%m-%d")
        _save_news_corpus(news_history_path,
                          _prune_news_corpus(news_corpus, anchor_date))
    except OSError as exc:
        print(f"  ⚠️ 新闻标题存档保存失败（{exc}），不影响本次日报与推送")
    # 确保工作流 git add 列表中的可选留痕文件存在（如未配置大模型 Key 时 hk7_forecast.json 未创建，
    # 否则单条 git add 会因 pathspec 不匹配以退出码 128 中止，导致 latest.html 漏提交）。
    for opt_name in ("quant_history.json", "hk7_forecast.json", "weekly_forecast.json"):
        opt_path = os.path.join(REPORT_DIR, opt_name)
        if not os.path.exists(opt_path):
            try:
                _atomic_write(opt_path, '{"entries": [], "version": 1}\n')
            except OSError:
                pass
    # 必须从刚保存的路径读取，避免 latest.html 被锁定时推送到旧副本。
    with open(output_path, "r", encoding="utf-8") as f:
        push_html = f.read()

    # 5. 推送决策：先做「当天内容检验」，再决定是否推送。
    #    约定：任何「应当推送却失败」的情况都返回退出码 1（GitHub Actions 将标红），
    #    不再出现“推送失败但 workflow 显示成功”的静默问题。
    can_push, reason = check_push_eligibility(data)

    def _finish(ok, ok_msg="🎉 全部完成！",
                fail_msg="❌ 流程完成，但推送未成功（见上方原因；Actions 将标红提醒）"):
        print(f"\n{ok_msg if ok else fail_msg}")
        return 0 if ok else 1

    if args.no_push:
        print(f"\n⏭️ 已跳过推送（--no-push）。当天检验: {reason}")
        print(f"   日报已保存: {output_path}")
        return _finish(True)

    if can_push:
        print(f"\n📤 当天检验通过：{reason}")
        title = build_push_title()
        print(f"📎 正在推送本次生成的 HTML: {output_path}")
        if push_to_wechat(title, push_html, report_name=os.path.basename(output_path)):
            return _finish(True)
        # 日报推送失败：再发一条纯文本失败告警，微信侧能直接看到原因；退出码仍为 1。
        push_failure_alert("日报 HTML 多次推送均被 PushPlus 拒绝（详见上方 code/msg）",
                           data=data, report_path=output_path)
        return _finish(False)

    if args.force_push:
        print(f"\n⚠️ 当天检验未通过，但检测到 --force-push，强制推送！")
        print(f"   原因: {reason}")
        title = build_push_title("(强制)")
        if push_to_wechat(title, push_html, report_name=os.path.basename(output_path)):
            return _finish(True)
        push_failure_alert("强制推送的日报被 PushPlus 拒绝（详见上方 code/msg）",
                           data=data, report_path=output_path)
        return _finish(False)

    if args.allow_incomplete_push:
        print(f"\n⚠️ 全部数据源不可用，但检测到 --allow-incomplete-push，推送状态报告。")
        print(f"   原因: {reason}")
        title = build_push_title("(状态)")
        if push_to_wechat(title, push_html, report_name=os.path.basename(output_path)):
            return _finish(True)
        push_failure_alert("状态报告推送被 PushPlus 拒绝（详见上方 code/msg）",
                           data=data, report_path=output_path)
        return _finish(False)

    # 当天检验未通过且不强制：不推日报，但推一条纯文本告警，避免彻底沉默。
    print(f"\n⏸️ 当天检验未通过，本次不推送日报。")
    print(f"   原因: {reason}")
    print("   日报已保存（带状态标记），可在确认后使用:")
    print("     python3 output/pipeline.py --manual --force-push   # 强制手动推送")
    print("     python3 output/pipeline.py --push-only output/latest.html")
    if push_no_push_alert(reason, data, output_path):
        return _finish(True, ok_msg="🎉 全部完成（日报未推，已发出检验未通过告警）！")
    print("   ⚠️ 告警也发送失败。若是 token 未配置/失效，本次将以失败结束以便在 Actions 中发现。")
    return _finish(False)


if __name__ == "__main__":
    sys.exit(main())
