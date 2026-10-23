#!/usr/bin/env python3
"""
🐙 章鱼 AI · 一键推送
每次运行都先清理历史 HTML 报告 → 抓取最新数据 → 分析 → 生成 → 当天检验 → 推送。

常用:
  python3 output/push.py                        # 全流程（当天检验通过才推送）
  python3 output/push.py --manual               # 手动推送模式
  python3 output/push.py --manual --force-push  # 手动强制推送（内容非当天也推）
  python3 output/push.py --push-only            # 推送实际最后更新的日报（不清理）
  python3 output/push.py --list                 # 列出已生成的日报（不清理）

页面风格（一对一 / 一对多推送共用同一份日报 HTML）:
  默认主题 lime（白底圆角卡片 + 荧光绿强调风：白底画布 #FFFFFF、浅灰圆角卡片 #F5F5F6、
  粗黑标题 #111111 与荧光绿 #C8F03C 胶囊序号 / 指示小方块；全内联样式，无 JS / 外部 CSS，
  兼容 PushPlus / 微信详情页）。
  切换 pixel DOS 复古监视器: python3 output/push.py --theme pixel
  切换 forum 暗色社区仪表盘: python3 output/push.py --theme forum
  切换 dossier 德国档案风: python3 output/push.py --theme dossier
  切换 guizang 白底研报: python3 output/push.py --theme guizang
  或环境变量: OCTOPUS_PUSH_THEME=lime|pixel|forum|dossier|guizang

推送方式（2026-10-23 起默认一对多）:
  默认 PushPlus「一对多」群组推送：群组编码从 PUSHPLUS_TOPIC 读取（GitHub Secret /
  环境变量），发到该群组；Actions 工作流里 Secret 缺省时兜底为仓库群组 oai.1。
  本地跑没配 PUSHPLUS_TOPIC 时打印明确告警并回退一对一（只发给自己）。
  PUSHPLUS_MODE=one2one 可显式改回一对一直发自己（此时不携带 topic，即使配了群组编码）。

超长日报（> 单条 10 万字上限）:
  自动按栏目边界拆成多条消息完整推送（标题带 1/N、2/N…），内容一个字不丢；
  磁盘上的日报始终是一份完整文件。PUSHPLUS_MULTIPART=0 可回退到旧的截断推送。
"""
import os
import sys
import subprocess
import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(SCRIPT_DIR, "pipeline.py")
# 日报输出目录与pipeline保持一致：pipeline.py所在的目录
REPORT_DIR = os.path.dirname(PIPELINE)


def list_reports():
    """列出所有已生成的日报文件"""
    pattern = os.path.join(REPORT_DIR, "daily_report_*.html")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        print("暂无日报文件。")
        return 0

    print(f"共找到 {len(files)} 份日报：\n")
    for idx, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        size = os.path.getsize(filepath)
        print(f"  {idx:2d}. {filename}  ({size:,} 字节)")
    return 0


def main():
    # --list 模式
    if "--list" in sys.argv:
        sys.exit(list_reports())

    # 前置校验：pipeline.py 是否存在
    if not os.path.isfile(PIPELINE):
        print(f"❌ 错误：找不到流水线脚本 {PIPELINE}")
        print(f"   请检查脚本路径是否正确，当前脚本目录：{SCRIPT_DIR}")
        sys.exit(1)

    # 透传参数执行pipeline
    cmd = [sys.executable, PIPELINE] + sys.argv[1:]
    returncode = subprocess.call(cmd)

    # 退出码归一化：负数（信号终止）统一转为正数
    if returncode < 0:
        print(f"\n⚠️  进程被信号终止，信号码：{-returncode}")
        sys.exit(1)

    sys.exit(returncode)


if __name__ == "__main__":
    main()
