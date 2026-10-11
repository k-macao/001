#!/usr/bin/env bash
# 安装 / 更新上游 UZI-Skill（游资 Skills · 个股深度分析引擎）到本仓库工作区。
#
# 为什么要这个脚本
#   本仓库的日报流水线只借用上游的「方法」（规则引擎裁决 / 数据不足即 skip /
#   流派锁定 / 完整性闸门 / Great Divide / 禁用空泛话术 / 8 信号风险扫描），
#   已把需要的部分确定性移植进 output/octopus_quant/trend_jury.py（见
#   UZISkill-安装与趋势分析栏目.md）。上游本体是一个独立 CLI / 插件，
#   默认**不进本仓库版本库**，只在需要跑上游完整流程（估值建模、龙虎榜、
#   杀猪盘扫描等）时按本脚本装到 vendor/ 下。
#
# 用法
#   bash tools/install_uzi_skill.sh                    # clone / 更新到 vendor/UZI-Skill
#   bash tools/install_uzi_skill.sh --ref main         # 指定分支 / 标签 / 提交
#   bash tools/install_uzi_skill.sh --dest ~/UZI-Skill # 装到仓库外（默认就是这样跑的沙箱）
#   bash tools/install_uzi_skill.sh --deps             # 顺带 pip install -r requirements.txt
#   bash tools/install_uzi_skill.sh --verify           # 装完跑一次 run.py --help 自检
#
# 网络口径：只访问 github.com / pypi.org；取不到就报错退出，绝不伪造「已安装」。
set -euo pipefail

UPSTREAM="https://github.com/wbh604/UZI-Skill.git"
REF="main"
DEPS=0
VERIFY=0
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/vendor/UZI-Skill"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)   REF="${2:?--ref 需要分支 / 标签 / 提交}"; shift 2 ;;
    --dest)  DEST="${2:?--dest 需要目录}"; shift 2 ;;
    --deps)  DEPS=1; shift ;;
    --verify) VERIFY=1; shift ;;
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "未知参数：$1（-h 看用法）" >&2; exit 2 ;;
  esac
done

echo "▶ 上游：${UPSTREAM}（ref=${REF}）"
echo "▶ 目标：${DEST}"

if command -v git >/dev/null 2>&1 && git -C "${DEST}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "▶ 已存在本地镜像，执行 fetch + checkout"
  git -C "${DEST}" fetch --depth 1 origin "${REF}"
  git -C "${DEST}" checkout -q FETCH_HEAD
else
  mkdir -p "$(dirname "${DEST}")"
  if [[ -e "${DEST}" && -n "$(ls -A "${DEST}" 2>/dev/null || true)" ]]; then
    echo "❌ ${DEST} 已存在但不是 git 仓库；为避免覆盖手工改动，请先自行处理" >&2
    exit 1
  fi
  git clone --depth 1 --branch "$( [[ "${REF}" =~ ^[0-9a-f]{40}$ ]] && echo main || echo "${REF}" )" \
      "${UPSTREAM}" "${DEST}"
  if [[ "${REF}" =~ ^[0-9a-f]{40}$ ]]; then
    git -C "${DEST}" fetch --depth 1 origin "${REF}" && git -C "${DEST}" checkout -q FETCH_HEAD
  fi
fi

COMMIT="$(git -C "${DEST}" rev-parse HEAD)"
DATE="$(git -C "${DEST}" log -1 --format=%ad --date=short)"
VERSION=""
if [[ -f "${DEST}/SKILL.md" ]]; then
  VERSION="$(sed -n 's/^version:[[:space:]]*//p' "${DEST}/SKILL.md" | head -1)"
fi
LICENSE="MIT"
[[ -f "${DEST}/LICENSE" ]] && LICENSE="$(head -2 "${DEST}/LICENSE" | tr '\n' ' ' | sed 's/  */ /g')"

if [[ "${DEPS}" == "1" ]]; then
  echo "▶ 安装上游 Python 依赖（akshare / yfinance / baostock / playwright …）"
  python3 -m pip install -r "${DEST}/requirements.txt"
fi

if [[ "${VERIFY}" == "1" ]]; then
  echo "▶ 自检：跑一次上游 CLI 帮助（缺依赖时这里会报 ModuleNotFoundError，属正常，按需 --deps）"
  (cd "${DEST}" && python3 run.py --help >/dev/null && echo "  ✅ run.py --help 通过")
fi

echo
echo "✅ 安装完成"
echo "   提交  ${COMMIT}（${DATE}）"
echo "   版本  ${VERSION:-未知} · License ${LICENSE}"
echo "   路径  ${DEST}"
echo
echo "本仓库只依赖移植后的确定性模块（output/octopus_quant/trend_jury.py），"
echo "不需要 vendor/ 也能出日报；vendor/ 已写进 .gitignore，不进版本库。"
echo "要跑上游完整深度分析：cd ${DEST} && python3 run.py <代码> --no-browser"
