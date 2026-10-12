#!/usr/bin/env python3
"""离线渲染证据生成器：把「内地财经媒体源头（18 家）」放进一份**合成夹具**日报里，
逐处抽出它在页面上的可见位置，写成 markdown 证据文件。

用途：沙箱 / CI 没有外网时，也能不依赖真实抓取，验证「18 家标题进标题池」后
日报里到底能看到什么（数据覆盖、新闻情绪证据行、政策因子引用行、审计计数）。

注意：夹具里的标题与抓取结果都是**构造数据**（不是真实抓取），文件与输出里都会标注；
真实覆盖请在联网机器上跑 `python3 output/pipeline.py --dry-run` 查看每家的 ✅/⚠️。

用法：
    python3 tools/demo_mainland_news_render.py [输出路径]
默认输出 /home/user/02/样例-内地财经媒体-渲染证据.md
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

spec = importlib.util.spec_from_file_location("pl_demo_mainland", REPO_ROOT / "output" / "pipeline.py")
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)

DATE_ISO = "2026-10-12"
DATE_DISPLAY = "2026年10月12日 · 周一"
DATE_STR = "20261012"

# 三家媒体各一条 72h 内标题（构造数据），覆盖「政策→政策因子」「个股→新闻情绪」两条通道
FIXTURE = (
    ("中证网（中国证券报）", "国常会部署稳增长举措 央行宣布降准0.5个百分点释放长期资金",
     "https://www.cs.com.cn/a/1.html"),
    ("证券时报网", "宁德时代获机构上调目标价，主力资金净流入明显",
     "https://www.stcn.com/a/2.html"),
    ("凤凰网财经", "半导体设备板块领涨，北向资金单日净买入超百亿",
     "https://finance.ifeng.com/a/3.html"),
)


def build_data():
    items = [{"title": t, "source": src, "section": pl.MAINLAND_NEWS_SECTION, "url": url,
              "published_cst": f"{DATE_ISO} 10:0{i}", "date": DATE_ISO, "is_today": True,
              "detail": f"发布于 {DATE_ISO} 10:0{i}（北京时间）"}
             for i, (src, t, url) in enumerate(FIXTURE)]
    records = [{"name": src, "status": "ok", "served_by": "站内检索", "scanned": 1,
                "today": 1, "newest": DATE_ISO, "items": [it],
                "note": "该媒体无可用官方订阅，本次经站内检索 RSS 取得公开标题"}
               for (src, _t, _u), it in zip(FIXTURE, items)]
    src = pl._source_result(
        pl.MAINLAND_NEWS_SOURCE_NAME, "success", is_today=True, content_date=DATE_ISO,
        sources=records, headlines=items,
        analysis={"scanned": len(items), "ok_n": len(records), "today_n": len(items),
                  "newest": DATE_ISO, "items_n": len(items), "merged": 0},
        note=f"只收录 {pl.MAINLAND_NEWS_TOTAL} 家内地财经媒体公开信息源（合成夹具：非真实抓取）",
        partial=True)
    hot = pl._source_result(
        "热门榜单", "success", is_today=True, content_date=DATE_ISO,
        markets={"A股": {"stocks": [{"code": "300750", "name": "宁德时代"}]}})
    return {pl.MAINLAND_NEWS_SOURCE_NAME: src, "热门榜单": hot}


def plain(html):
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def snippets(text, needle, width=90, limit=3):
    out = []
    for m in re.finditer(re.escape(needle), text):
        seg = text[max(0, m.start() - width):m.end() + width]
        if seg not in out:
            out.append(seg)
        if len(out) >= limit:
            break
    return out


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "样例-内地财经媒体-渲染证据.md"
    data = build_data()
    lines = [
        "# 样例：内地财经媒体源头（18 家）在日报里的可见位置",
        "",
        "> ⚠️ 本页由 `tools/demo_mainland_news_render.py` 生成，夹具数据是**构造的**"
        "（不是真实抓取）；作用是证明「18 家标题进标题池」之后，日报里确实能看到它们。",
        "",
        f"- 夹具标题 3 条：{'、'.join(src for src, _t, _u in FIXTURE)}",
        f"- 生成日期：{DATE_DISPLAY}",
        "",
    ]
    for theme in ("lime", "pixel"):
        kit_name = "青柠版（lime）" if theme == "lime" else "像素版（pixel）"
        html = pl.generate_report(data, DATE_DISPLAY, DATE_STR, theme=theme)
        meta = pl._report_meta(html)
        text = plain(html)
        lines += [
            f"## {kit_name}", "",
            f"- 审计计数：总源 {meta['total_sources']} · 当天源 {meta['today_sources']}"
            "（夹具里只有内地财经媒体源头 + 热门榜单两个数据源有内容，其余 7 路占位）",
            f"- 页面出现「内地财经媒体」字样 {text.count('内地财经媒体')} 次、"
            f"出现媒体名次数：中证网 {text.count('中证网')}、证券时报网 {text.count('证券时报网')}、"
            f"凤凰网财经 {text.count('凤凰网财经')}",
            "",
        ]
        cover = re.search(r"数据覆盖(.{0,160})", text)
        lines += ["**① 总结 · 数据覆盖行**（审计口径，点名缺失源）", "",
                  f"```\n{cover.group(1).strip() if cover else '（未找到）'}\n```", ""]
        senti = snippets(text, "内地财经媒体 ·", width=70, limit=2)
        lines += ["**② 新闻情绪 · 证据行**（标题 + 内地区属 + 媒体名 + 命中词）", ""]
        lines += [f"```\n{s}\n```" for s in senti] or ["```\n（本次夹具没有命中个股，无证据行；命中时格式如上）\n```"]
        lines.append("")
        policy = [s for s in snippets(text, "央行宣布降准", width=70, limit=2)]
        lines += ["**③ 政策因子 · 引用行**（标题 + 可点击原文链接 + 媒体名）", ""]
        lines += [f"```\n{s}\n```" for s in policy] or ["```\n（未找到）\n```"]
        lines.append("")
        trend = [s for s in snippets(text, "内地财经媒体 ×", width=80, limit=2)]
        lines += ["**④ 趋势跟踪栏目 · 内地财经媒体源头行**（源头级覆盖；标题不在这里重复列出）", ""]
        lines += [f"```\n{s}\n```" for s in trend] or ["```\n（未找到：该源头本次无内容，栏目按缺席处理）\n```"]
        lines.append("")
        lines.append(f"**⑤ 标题是否进正文**：降准标题出现 {text.count('降准')} 次；"
                     "18 家是标题池，只在被引用处（新闻情绪 / 政策因子）出现，"
                     "趋势跟踪里只报源头覆盖、不重复列标题——"
                     "夹具里「半导体设备板块领涨」这条没有命中个股、也没落到政策维度，"
                     "因此不在页面上单列（仍进标题池：计入审计与 15 日政策窗口，供后续引用）。")
        lines += ["", "---", ""]
    lines += [
        "## 真实覆盖怎么看（沙箱无外网，必须在本机跑）", "",
        "```bash",
        "python3 output/pipeline.py --sources      # 19 条数据线（含 mainland_news_rss）",
        "python3 output/pipeline.py --dry-run      # 抓取日志：每家 ✅/⚠️，结尾给出",
        "                                          # 「内地财经媒体 N/18 家窗口内有更新 · 扫描 M 条 · 进标题池 K 条」",
        "                                          # 与「暂缺（X 家）：…」名单",
        "```",
    ]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入 {out_path}")
    print(f"总源/当天：{pl._report_meta(pl.generate_report(data, DATE_DISPLAY, DATE_STR, theme='lime'))['total_sources']}"
          f" / {pl._report_meta(pl.generate_report(data, DATE_DISPLAY, DATE_STR, theme='lime'))['today_sources']}")


if __name__ == "__main__":
    main()
