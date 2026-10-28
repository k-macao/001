#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""低频小因子栏目的离线版面预览（渲染证据）。

用途：沙箱 / CI **没有外网**时，也能看到【慢游小丑鱼】低频小因子量化策略在 5 套主题
（lime / pixel / forum / dossier / guizang）下长什么样，以及口径、因子镜子、推荐名单、
组合画像、剔除与风险披露是否都在。

数据来自 ``lowfreq_factors.synthetic_inputs()``：**确定性合成序列**，页面顶部与栏目内都会
明确写「合成演示序列」，数字不代表任何真实港股，不可据此交易。真实名单要联网跑：

    python3 output/pipeline.py --dry-run      # 日志里会有「✅ 低频小因子：… 推荐 20 只」

用法：
    python3 tools/demo_lowfreq_factors.py [输出路径]
默认输出 <仓库根>/output/低频小因子_预览.html（预览页按 .gitignore 不入库）。
"""
import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
sys.modules.setdefault("requests", types.SimpleNamespace())
sys.path.insert(0, str(REPO_ROOT / "output"))

spec = importlib.util.spec_from_file_location("pl_demo_lowfreq", REPO_ROOT / "output" / "pipeline.py")
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)

lf = pl._lowfreq
DATE_STR = "20261028"

THEMES = (
    ("lime", pl.LIME_KIT),
    ("pixel", pl.PIXEL_KIT),
    ("forum", pl.FORUM_KIT),
    ("dossier", pl.DOSSIER_KIT),
    ("guizang", pl.GUIZANG_KIT),
)


def build(theme="lime"):
    kit = dict(THEMES)[theme]
    res = lf.run_lowfreq_factors(None, date_str=DATE_STR, allow_synthetic_flag=True)
    body = lf.render(res, kit, plain=False)
    conclusion = pl._ren._ren_lowfreq_factors({"lowfreq": res})
    section = kit.section(
        "17", lf.KICKER, lf.SECTION_TITLE,
        pl._ren_judgment_row(conclusion, kit, meta={"label": None, "p_pct": None}) + body,
        kit.source_badge({"source": lf.SOURCE_NAME, "status": "success",
                          "fetched_at": "2026-10-28 09:00", "is_today": False}),
        "港股五因子横截面：小市值（先剥壳价值）/ 短期反转（当镜子）/ 12-1 动量 / 低换手 / 同行业 EP → 推荐 20 只")
    return res, section


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "output" / "低频小因子_预览.html"
    res, section = build("lime")
    banner = (
        '<div style="margin:0 0 12px;padding:12px 14px;border-radius:14px;background:#FFF3E0;'
        'color:#8D4E00;font-size:13px;line-height:1.5;">'
        '<b>版面预览 · 数据为合成演示序列</b><br>'
        '本页由 <code>tools/demo_lowfreq_factors.py</code> 生成：股票名称、价格、市值、日线全部来自'
        '确定性合成夹具（OCTOPUS_LOWFREQ_DEMO 同款），只用于检查版面与口径，<b>不代表任何真实港股</b>。'
        '真实名单请在联网机器上运行 <code>python3 output/pipeline.py --dry-run</code>。</div>')
    html = (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>【慢游小丑鱼】低频小因子量化策略 · 版面预览</title></head>'
        '<body style="margin:0;padding:16px;background:#FFFFFF;font-family:-apple-system,'
        'BlinkMacSystemFont,\'Segoe UI\',Roboto,\'Helvetica Neue\',Arial,\'PingFang SC\','
        '\'Hiragino Sans GB\',\'Microsoft YaHei\',sans-serif;">'
        f'<div style="max-width:980px;margin:0 auto;">{banner}{section}'
        '<div style="margin:18px 0 0;padding:12px 14px;border-radius:14px;background:#F5F5F6;'
        'color:#555;font-size:12px;line-height:1.6;">'
        '五主题渲染自检：' + "、".join(
            f"{name} {len(build(name)[1])} 字符" for name, _ in THEMES) +
        '。任何主题渲染失败会直接抛错，本页不会生成。</div>'
        '</div></body></html>'
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    top = res.get("top") or []
    print(f"已写入 {out_path}")
    print(f"合成演示：可排序 {res['universe']['ranked']} 只 → 推荐 {len(top)} 只")
    print(f"因子镜子：21 日反转中位数 {res['mirrors']['reversal_median']:+.2f}% / "
          f"上涨占比 {res['mirrors']['reversal_up_share']:.0f}%")
    for row in top[:5]:
        print(f"  {row['rank']:>2}. {row['code']} {row['name']} 综合分 {row['composite']:.1f} · {row['reason']}")
    print("（以上全部为合成数据，仅验证版面）")


if __name__ == "__main__":
    main()
