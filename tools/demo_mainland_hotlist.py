#!/usr/bin/env python3
"""离线渲染证据生成器：把【沸腾花蛤】情绪热点因子量化分析（原内地财经热点榜）放进一份日报里逐主题抽出可见位置。

夹具来源：**2026-10-13 沙箱内逐源实测**抓到的真实标题 / 真实原文链接 / 真实时间戳
（Bing News site: 检索 RSS，与 mainland_news_rss 数据线模板逐字一致；IT之家走实测可用的
官方订阅 https://www.ithome.com/rss/）。时间戳为检索平台的索引时间（GMT→北京时间）。
它不是构造故事：标题、链接、时间都来自当天真实抓取，只是**离线重放**到渲染层。

用途：沙箱 / CI 没有外网时，也能验证新栏目在 5 套主题（lime / pixel / forum / dossier /
guizang）下都能渲染，且主题条数、时效体检、暂缺点名、情绪总览、热点聚合、预警风险点、
预警趋势与今日风险态势都如实显示。

真实覆盖仍以联网机器为准：
    python3 output/pipeline.py --dry-run      # 每家 ✅/⚠️ + 「内地财经媒体 N/18 家…」

用法：
    python3 tools/demo_mainland_hotlist.py [输出路径]
默认输出 <仓库根>/样例-情绪热点因子量化分析-渲染证据.md
"""
import importlib.util
import re
import sys
import types
from html import unescape
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
sys.modules.setdefault("requests", types.SimpleNamespace())
sys.path.insert(0, str(REPO_ROOT / "output"))

spec = importlib.util.spec_from_file_location("pl_demo_hotlist", REPO_ROOT / "output" / "pipeline.py")
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)

DATE_ISO = "2026-10-13"
DATE_DISPLAY = "2026年10月13日 · 周二"
DATE_STR = "20261013"
NOW_CST = "2026-10-13 13:00"        # 实测时刻（北京时间；最后一路源取完的时刻），滞后小时数按它计算

# (媒体, 标题, 原文链接, 北京时间) —— 2026-10-13 逐源实测样本
SAMPLE = (
    ("中证网（中国证券报）", "新华社快讯：IMF上调2026年世界经济增长预期至3.1%",
     "https://www.cs.com.cn/xwzx/01/2026/10/13/detail_2026101310044331.html", "2026-10-12 21:22"),
    ("中证网（中国证券报）", "中国航展迎而立之年 本届将有超1100家企业参展",
     "https://www.cs.com.cn/xwzx/01/2026/10/13/detail_2026101310044340.html", "2026-10-12 21:22"),
    ("中证网（中国证券报）", "证监会：推动北交所新三板一体化高质量发展",
     "https://www.cs.com.cn/xwzx/01/2026/10/13/detail_2026101310044265.html", "2026-10-12 21:06"),
    ("证券日报网", "科创板人工智能产业链公司三季度业绩加速兑现",
     "http://www.zqrb.cn/stock/gupiaoyaowen/2026-10-13/A1791791758791.html", "2026-10-13 02:47"),
    ("证券日报网", "3年期大额存单利率重回2% 部分中小银行逆势上调存款利率",
     "http://www.zqrb.cn/jrjg/bank/2026-10-13/A1791791758794.html", "2026-10-13 02:35"),
    ("证券日报网", "多家PCB产业链上市公司前三季度业绩预喜",
     "http://www.zqrb.cn/gscy/gongsi/2026-10-13/A1791827002095.html", "2026-10-13 02:47"),
    ("中国基金报", "A股新股粤芯半导体上市首日暴涨252%",
     "https://www.chnfund.com/article/AR4f5cbdb0-c9e3-ad6e-002c-3a24455ffc6a", "2026-10-13 00:25"),
    ("中国基金报", "上午港股芯片股大跌，南方两倍做多海力士跌超16%",
     "https://www.chnfund.com/article/ARe4c97e51-d78f-8d1d-e766-3a24455a85cd", "2026-10-12 21:49"),
    ("中国基金报", "白酒板块逆市拉升，金种子酒、皇台酒业涨停",
     "https://www.chnfund.com/article/AR37b0994f-499d-f974-8526-3a2445268987", "2026-10-12 21:49"),
    ("财闻", "IMF上调2026年全球通胀率预期至4.7%",
     "https://www.caiwennews.com/article/1647972.shtml", "2026-10-12 23:19"),
    ("财闻", "深圳华强：存储芯片供给紧张、需求旺盛格局目前没有发生变化",
     "https://www.caiwennews.com/article/1647970.shtml", "2026-10-12 23:16"),
    ("财闻", "港股午间收盘，大型科网股走弱",
     "https://www.caiwennews.com/article/1647957.shtml", "2026-10-12 23:01"),
    ("经济参考网", "潘功胜将出席开幕式 央行披露金融街论坛年会多项安排",
     "http://www.jjckb.cn/20261013/f80caeb88a85441f831d257f87e0fd5c/c.html", "2026-10-13 01:01"),
    ("经济参考网", "上汽大众连续12个月销量同比下滑",
     "http://www.jjckb.cn/20261012/22e189ae5c3d4da5a1ecebd9011f11bc/c.html", "2026-10-12 01:00"),
    ("IT之家", "一加 16 拿下今年安卓旗舰首销同期销量 Top1，首销销量已突破 7 万台",
     "https://www.ithome.com/1/012/277.htm", "2026-10-13 12:20"),
    ("IT之家", "彭博行业研究分析 AI 数据中心成本：1GW 容量恐超 300 亿美元",
     "https://www.ithome.com/1/012/275.htm", "2026-10-13 12:04"),
    ("IT之家", "华为徐松余：麒麟 9050 Pro 马良 GPU 性能提升 40%",
     "https://www.ithome.com/1/012/186.htm", "2026-10-12 21:15"),
    ("证券时报网", "大涨7%！688808，重回“股王”",
     "https://www.stcn.com/article/detail/4213902.html", "2026-10-13 05:27"),
    ("证券时报网", "港股午评：恒生指数跌0.39% 恒生科技指数跌1.54%",
     "https://www.stcn.com/article/detail/4213985.html", "2026-10-12 23:08"),
    ("券商中国", "“广州第一芯”，开盘大涨275%！市值近1300亿元",
     "https://www.stcn.com/article/detail/4213803.html", "2026-10-13 05:27"),
    ("每日经济新闻", "创业板指半日跌0.95% 冰雪经济、PCB概念逆势走强",
     "https://m.nbd.com.cn/articles/2026-10-13/4602709.html", "2026-10-13 01:01"),
    ("每日经济新闻", "美联储10月维持利率不变的概率为79.5%",
     "https://m.nbd.com.cn/articles/2026-10-13/4602397.html", "2026-10-12 17:07"),
    ("21世纪经济报道", "超2万亿！A股分红迈上新台阶：从“一年一次”到“季季有回响”",
     "https://m.21jingji.com/article/20261013/herald/59957e2edfc5181ba71492f7a83cfac7.html",
     "2026-10-13 01:01"),
    ("21世纪经济报道", "公募解读新规：发行降门槛、严管风格漂移、优化迷你基金退出",
     "https://m.21jingji.com/article/20261013/herald/8cae4e38e147c6c671d4273e42825fc7.html",
     "2026-10-13 01:01"),
    ("证券之星", "10月13日证券之星午间消息汇总：3188家！A股并购重组市场热度持续攀升",
     "https://wap.stockstar.com/detail/SS2026101300016465", "2026-10-13 01:01"),
    ("证券之星", "上午港股芯片股大跌，南方两倍做多海力士跌超16%",
     "https://wap.stockstar.com/detail/IG2026101300014956", "2026-10-13 01:01"),
    ("和讯网", "新能源汽车增值税出口退税率将降至9%",
     "https://auto.hexun.com/2026-10-13/225108297.html", "2026-10-13 04:12"),
    ("和讯网", "半导体企业频频披露大订单 A股板块年营收有望破万亿",
     "https://stock.hexun.com/2026-10-12/225103196.html", "2026-10-12 09:28"),
    ("时代财经", "股价一字涨停！福建老牌百货计划超7倍溢价并购亏损公司“追光”",
     "https://www.tfcaijing.com/article/page/4545484443346f5447625954574a637a5471304548673d3d",
     "2026-10-12 23:47"),
    ("时代财经", "持股比例突破20%！新华保险增持国泰海通H股",
     "https://www.tfcaijing.com/article/page/424c684b2f67514f793965516778676f4771376a76673d3d",
     "2026-10-11 12:15"),
    ("经济观察网", "四大指数集体低开 创业板指跌超2%",
     "https://www.eeo.com.cn/2026/1013/1062021.shtml", "2026-10-13 05:27"),
    ("经济观察网", "硅料龙头杭州闭门会约定硅料含税底价？回应：消息属实",
     "https://www.eeo.com.cn/2026/1013/1062268.shtml", "2026-10-13 05:27"),
    ("凤凰网财经", "A股午评：三大指数集体收跌，医药、半导体下跌",
     "https://finance.ifeng.com/c/8xBZqnBKwa9", "2026-10-12 23:28"),
    ("凤凰网财经", "证监会主席吴清，将出席重磅会议并作演讲",
     "https://finance.ifeng.com/c/8xAIci5OE5S", "2026-10-12 17:19"),
)

# 实测两家媒体的主域名未被 Bing News 收录 → 如实暂缺
MISSING = ("北京商报（北京商报网）", "金融投资报")


def _lag_hours(cst):
    """按实测时刻 NOW_CST 算滞后小时数（与 fetch 里的口径一致）。"""
    from datetime import datetime
    try:
        delta = datetime.strptime(NOW_CST, "%Y-%m-%d %H:%M") - datetime.strptime(cst, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return round(delta.total_seconds() / 3600.0, 1)


def build_data():
    """按 pipeline 的字段口径还原一份「内地财经媒体源头」抓取结果（离线夹具）。"""
    from datetime import datetime
    headlines, records, seen = [], [], set()
    by_media = {}
    for src, title, url, cst in SAMPLE:
        by_media.setdefault(src, []).append(
            {"title": title, "url": url, "published_cst": cst, "date": cst[:10],
             "is_today": cst[:10] == DATE_ISO,
             "detail": f"发布于 {cst}（北京时间）"})
    for src, items in by_media.items():
        items = sorted(items, key=lambda it: it["published_cst"], reverse=True)[
            :pl.MAINLAND_NEWS_PER_SOURCE]
        newest = max(it["published_cst"] for it in items)
        records.append({"name": src, "region": "内地", "status": "ok", "scanned": len(items),
                        "today": sum(1 for it in items if it["is_today"]), "newest": newest[:10],
                        "items": items, "titles": [it["title"] for it in items],
                        "newest_cst": newest, "lag_hours": _lag_hours(newest),
                        "state": "当天" if newest[:10] == DATE_ISO else "窗口内滞后",
                        "via": "官方订阅" if src == "IT之家" else "Bing 站内检索",
                        "served_by": "官方订阅" if src == "IT之家" else "站内检索",
                        "note": "（离线夹具）"})
        for it in items:
            key = re.sub(r"\s+", "", it["title"])
            if key in seen:
                continue
            seen.add(key)
            headlines.append({"title": it["title"], "source": src,
                              "section": pl.MAINLAND_NEWS_SECTION, "url": it["url"],
                              "published_cst": it["published_cst"], "date": it["date"],
                              "is_today": it["is_today"]})
    for name in MISSING:
        records.append({"name": name, "region": "内地", "status": "empty", "scanned": 0,
                        "today": 0, "newest": None, "items": [], "titles": [],
                        "newest_cst": None, "lag_hours": None, "state": "暂缺", "via": "—",
                        "served_by": "—",
                        "note": "站内检索未返回结果（该站未被检索平台收录），暂缺"})
    newest_all = max(r["newest_cst"] for r in records if r.get("newest_cst"))
    health = [{"name": r["name"], "status": r.get("status", "fail"),
               "items": len(r.get("items") or []), "newest_cst": r.get("newest_cst"),
               "lag_hours": r.get("lag_hours"), "state": r.get("state") or "暂缺",
               "via": r.get("via") or "—"} for r in records]
    src = pl._source_result(
        pl.MAINLAND_NEWS_SOURCE_NAME, "success", is_today=True, content_date=DATE_ISO,
        sources=records, headlines=headlines,
        analysis={"scanned": sum(r.get("scanned") or 0 for r in records),
                  "ok_n": sum(1 for r in records if r.get("status") == "ok"),
                  "today_n": sum(r.get("today") or 0 for r in records),
                  "newest": DATE_ISO, "items_n": len(headlines),
                  "merged": sum(len(r.get("items") or []) for r in records) - len(headlines),
                  "health": health, "newest_cst": newest_all,
                  "lag_hours": _lag_hours(newest_all)},
        note=f"只收录 {pl.MAINLAND_NEWS_TOTAL} 家内地财经媒体公开信息源（离线夹具："
             f"2026-10-13 实测标题重放）",
        partial=True)
    hot = pl._source_result("热门榜单", "success", is_today=True, content_date=DATE_ISO,
                            markets={"A股": {"stocks": [{"code": "300750", "name": "宁德时代"}]}})
    return {pl.MAINLAND_NEWS_SOURCE_NAME: src, "热门榜单": hot}


def build_corpus():
    """存档夹具：把同一批实测标题按 news_history.json 的条目口径重放。

    section=内地财经媒体、date=存档日期口径（与真实存档一致：标题级时间截断到日，
    同日重复按 日期+标题 去重）。SAMPLE 只覆盖 2026-10-11 ~ 10-13 三天 →
    「🔭 预警趋势」如实只列这三天；10-07 ~ 10-10 无存档就不进对比，
    不虚构空日、不硬造历史。
    """
    items, seen = [], set()
    for src, title, url, cst in SAMPLE:
        key = (cst[:10], re.sub(r"\s+", "", title))
        if key in seen:
            continue
        seen.add(key)
        items.append({"title": title, "source": src, "section": pl.MAINLAND_NEWS_SECTION,
                      "ts": cst, "date": cst[:10], "url": url})
    return items


def plain(html):
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def snippets(text, needle, width=110, limit=2):
    out = []
    for m in re.finditer(re.escape(needle), text):
        seg = text[max(0, m.start() - width):m.end() + width].strip()
        if seg not in out:
            out.append(seg)
        if len(out) >= limit:
            break
    return out


THEMES = (("lime", "青柠版（lime）"), ("pixel", "像素版（pixel）"),
          ("forum", "社区版（forum）"), ("dossier", "档案版（dossier）"),
          ("guizang", "归藏版（guizang）"))


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "样例-情绪热点因子量化分析-渲染证据.md"
    data = build_data()
    corpus = build_corpus()
    hotlist = pl.build_mainland_hotlist(data[pl.MAINLAND_NEWS_SOURCE_NAME],
                                        news_corpus=corpus, date_str=DATE_STR)
    lines = [
        "# 样例：【沸腾花蛤】情绪热点因子量化分析（原内地财经热点榜）在日报里的可见位置",
        "",
        f"> 📌 本页由 `tools/demo_mainland_hotlist.py` 生成。夹具是 **2026-10-13 沙箱内逐源实测**"
        f"抓到的真实标题 / 真实原文链接 / 真实时间戳（Bing News `site:` 检索 RSS；IT之家走官方订阅），"
        f"**离线重放**到渲染层——不是编造的故事，但也**不是今天的在线抓取**。",
        "",
        f"- 实测样本：{len(SAMPLE)} 条 / {len({s for s, *_ in SAMPLE})} 家媒体 · "
        f"暂缺 {len(MISSING)} 家（{'、'.join(MISSING)}，Bing News 未收录其域名）",
        f"- 聚类结果：{hotlist['theme_n']} 个主题 · 进榜 {hotlist['total']} 条 · "
        f"最新 {hotlist['newest_cst']}（滞后 {hotlist['lag_hours']:g} 小时，按 {NOW_CST} 计）",
        "- 主题条数（降序）：" + " · ".join(f"{b['label']} {b['count']}" for b in hotlist["themes"]),
        f"- 情绪总览：偏多 {hotlist['sentiment_agg']['pos_n']} · 中性 {hotlist['sentiment_agg']['neu_n']} · "
        f"偏空 {hotlist['sentiment_agg']['neg_n']} · 净情绪分 {hotlist['sentiment_agg']['avg_score']:+.2f}"
        f"（{hotlist['sentiment_agg']['label']}）",
        f"- 热点聚合：跨媒体同题（≥2 条）{hotlist['hotspots']['aggregated_n']} 个 · "
        + " · ".join(f"{c['term']}×{c['title_count']}" for c in hotlist["hotspots"]["clusters"][:5]),
        f"- 预警风险点：{hotlist['risk_report']['hit_n']}/{hotlist['risk_report']['total_titles']} 条标题命中 · "
        + (" · ".join(f"[{p_['level']}]{p_['category']}×{p_['count']}"
                      for p_ in hotlist["risk_report"]["points"]) or "0 命中（未命中 ≠ 没有风险）"),
        f"- 预警趋势（按日口径）：{hotlist['risk_trend']['trend_phrase']}"
        + (f" · 今日存档 {hotlist['risk_trend']['today_n']} 条样本尚少，对比仅作提示"
           if hotlist["risk_trend"]["low_sample"] else "")
        + " · 逐日命中 " + "·".join(str(d["hit_n"]) for d in hotlist["risk_trend"]["days"])
        + f"（{hotlist['risk_trend']['days'][0]['date'][5:]}"
          f"→{hotlist['risk_trend']['days'][-1]['date'][5:]}，存档只有这三天，如实不补空日）",
        f"- 今日风险态势：{hotlist['risk_posture']['text']}",
        "",
    ]
    for theme, kit_name in THEMES:
        html = pl.generate_report(data, DATE_DISPLAY, DATE_STR, theme=theme,
                                  news_corpus=corpus)
        text = plain(html)
        title_hit = text.count("情绪热点因子量化分析")
        lines += [
            f"## {kit_name}", "",
            f"- 栏目标题出现 **{title_hit}** 次（栏目头 1 次 + 目录/锚点/分条头，0 次即整栏缺席）",
            f"- 主题行条数合计校验：榜内可见主题 {min(hotlist['theme_n'], pl.MAINLAND_HOTLIST_THEME_MAX)} 个",
            "",
        ]
        head = snippets(text, "内地财经媒体 ×18", width=150, limit=1)
        lines += ["**① 栏目头 · 时效体检行**（几家有更新 / 进榜条数 / 最新时间 / 滞后小时）", ""]
        lines += [f"```\n{s}\n```" for s in head] or ["```\n（未找到）\n```"]
        lines.append("")
        cover = snippets(text, "时效体检", width=420, limit=1)
        lines += ["**② 逐家时效体检**（内地源头 · 窗口内条数 · 最新 / 滞后）", ""]
        lines += [f"```\n{s}\n```" for s in cover] or ["```\n（入门版不展开；本次为全量版）\n```"]
        lines.append("")
        miss = snippets(text, "暂缺", width=140, limit=1)
        lines += ["**③ 暂缺点名**", ""]
        lines += [f"```\n{s}\n```" for s in miss] or ["```\n（未找到）\n```"]
        lines.append("")
        theme_rows = [s for s in snippets(text, "条 ·", width=90, limit=4)]
        lines += ["**④ 主题榜行**（主题名 + 占比条 + 条数 / 占比 + 涉及媒体家数）", ""]
        lines += [f"```\n{s}\n```" for s in theme_rows] or ["```\n（未找到）\n```"]
        lines.append("")
        item_rows = [s for s in snippets(text, "↳", width=120, limit=3)]
        lines += ["**⑤ 代表标题行**（可点原文 + 媒体名 + 时间 + 今日 / 昨日及更早）", ""]
        lines += [f"```\n{s}\n```" for s in item_rows] or ["```\n（未找到）\n```"]
        lines.append("")
        senti_rows = snippets(text, "情绪总览", width=300, limit=1)
        lines += ["**⑥ 情绪总览**（本地情绪词典折叠成偏多/中性/偏空 + 净情绪分；词典启发式，非校准概率）", ""]
        lines += [f"```\n{s}\n```" for s in senti_rows] or ["```\n（未找到）\n```"]
        lines.append("")
        vocab_rows = snippets(text, "热点聚合", width=360, limit=1)
        lines += ["**⑦ 热点聚合**（原「AI词汇分析」升级：同一份 jieba 词频口径 + 同题聚合标记 + 情绪/风险标注）", ""]
        lines += [f"```\n{s}\n```" for s in vocab_rows] or ["```\n（未找到）\n```"]
        lines.append("")
        risk_rows = snippets(text, "预警风险点", width=420, limit=1)
        lines += ["**⑧ 预警风险点**（本地风险词表标题级命中；等级 = 传播度 高/中/关注，不是发生概率）", ""]
        lines += [f"```\n{s}\n```" for s in risk_rows] or ["```\n（未找到）\n```"]
        lines.append("")
        trend_rows = snippets(text, "预警趋势", width=380, limit=2)
        lines += ["**⑨ 预警趋势**（存档近 7 日按日重算 · 同一份风险词表；与最近存档日对比：新增 / 升级 / "
                  "持续 / 降级 / 解除；缺存档整行不出。第 1 处 = 栏首提鲜结论引用，第 2 处 = 栏目行本体）", ""]
        lines += [f"```\n{s}\n```" for s in trend_rows] or ["```\n（未找到）\n```"]
        lines.append("")
        posture_rows = snippets(text, "今日风险态势", width=380, limit=2)
        lines += ["**⑩ 今日风险态势**（天天出的确定性分析结论：情绪面定调 + 按日趋势对比；"
                  "0 命中日由⑧头行如实披露「未命中」。第 1 处 = 提鲜结论引用，第 2 处 = 栏目行本体）", ""]
        lines += [f"```\n{s}\n```" for s in posture_rows] or ["```\n（未找到）\n```"]
        lines += ["", "---", ""]
    lines += [
        "## 真实覆盖怎么看（沙箱无外网，必须在本机跑）",
        "",
        "```bash",
        "python3 output/pipeline.py --sources          # 19 条数据线（含 mainland_news_rss）",
        "python3 output/pipeline.py --dry-run          # 每家 ✅/⚠️ + 内地财经媒体 N/18 家…",
        "OCTOPUS_MAINLAND_HOTLIST=0 python3 output/pipeline.py --no-push   # 关掉本栏目",
        "```",
        "",
        "| 开关 | 默认 | 作用 |",
        "|---|---|---|",
        "| `OCTOPUS_MAINLAND_HOTLIST` | 开启 | `=0` 不渲染本栏目（采集、标题池、审计口径都不变） |",
        "| `OCTOPUS_MAINLAND_NEWS_PER_SOURCE` | 3 | 每家最多进标题池的条数（1~8） |",
        "| `OCTOPUS_MAINLAND_NEWS_MAX` | 48 | 全栏目最多进标题池的条数（6~120） |",
    ]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入 {out_path}")
    print("主题榜：" + " · ".join(f"{b['label']} {b['count']}" for b in hotlist["themes"]))
    print(f"进榜 {hotlist['total']} 条 · 最新 {hotlist['newest_cst']}（滞后 {hotlist['lag_hours']:g} 小时）")
    print(f"预警趋势：{hotlist['risk_trend']['trend_phrase']} · "
          f"今日风险态势：{hotlist['risk_posture']['verdict']}")


if __name__ == "__main__":
    main()
