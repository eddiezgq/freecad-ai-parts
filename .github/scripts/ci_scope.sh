#!/usr/bin/env bash
# CI 跑哪些作业（ADR-0067）：按触发方式与改动的目录决定，结果写到 $GITHUB_OUTPUT。
#   light   单元测试、FreeCAD 测试（有任何改动就跑；规则要求数据库测试在 CI 里跑）
#   factory 数字工厂测试
#   deploy  本地版启动、企业版安装、录帮助视频（较重）
#   windows Windows 安装包与验收（按 2 倍计费）
# 手动触发、PR 带 full-ci 标签：全部跑。每晚定时：main 自上次成功的定时运行以来有新提交才全部跑，否则都不跑。
# 环境变量：WF（工作流文件名）、BASE（PR 的 base 提交或 push 前的提交）、LABELS（PR 标签，逗号分隔）、GH_TOKEN
set -euo pipefail
out() { echo "light=$1"; echo "factory=$2"; echo "deploy=$3"; echo "windows=$4"; }
emit() { out "$@" | tee -a "$GITHUB_OUTPUT"; }

case "$GITHUB_EVENT_NAME" in
  workflow_dispatch) emit true true true true; exit 0 ;;
  schedule)
    last=$(gh api "repos/$GITHUB_REPOSITORY/actions/workflows/$WF/runs?event=schedule&status=success&per_page=1" \
           --jq '.workflow_runs[0].head_sha // ""' 2>/dev/null || echo "")
    if [ "$last" = "$GITHUB_SHA" ]; then echo "自上次成功的定时运行以来 main 没有新提交，跳过"; emit false false false false
    else emit true true true true; fi
    exit 0 ;;
esac

case ",${LABELS:-}," in *,full-ci,*) echo "PR 带 full-ci 标签：全部跑"; emit true true true true; exit 0 ;; esac
if [ -z "${BASE:-}" ] || [ "$BASE" = "0000000000000000000000000000000000000000" ] || ! git cat-file -e "$BASE^{commit}" 2>/dev/null; then
  echo "找不到对比的提交，全部跑"; emit true true true true; exit 0
fi
files=$(git diff --name-only "$BASE" "$GITHUB_SHA")
echo "改动的文件："; echo "$files" | head -50
has() { echo "$files" | grep -qE "$1" && echo true || echo false; }
factory=$(has '^(factory/|analysis/|kb/|schema/|licensing/|\.github/workflows/ci\.yml|\.github/scripts/)')
deploy=$(has '^(factory/|licensing/|\.github/workflows/ci\.yml|\.github/scripts/)')
windows=$(has '^(installer/|freecad_addon/(install|bundle)\.py|pyproject\.toml|\.github/workflows/windows\.yml|\.github/scripts/)')
emit true "$factory" "$deploy" "$windows"
