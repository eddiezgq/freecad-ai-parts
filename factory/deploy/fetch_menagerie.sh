#!/bin/sh
# 动力学用的机器人模型（第 12 轮 D3）：按零件库同一个固定提交，只取用到的几个文件夹（镜像构建、CI 测试都用它）
# 用法：deploy/fetch_menagerie.sh <目标目录>
set -e
DEST=${1:-/opt/menagerie}
COMMIT=4d038b3feae26ec82b46a4d586379114012a8ac7          # 与 library/vendor/menagerie.yaml、cae/mbd_models.py 一致
DIRS="franka_fr3 universal_robots_ur10e universal_robots_ur5e"
mkdir -p "$DEST" && cd "$DEST"
git init -q
git remote add origin https://github.com/google-deepmind/mujoco_menagerie.git 2>/dev/null || true
git sparse-checkout set --no-cone $(for d in $DIRS; do printf '/%s/ ' "$d"; done)
git fetch -q --depth 1 --filter=blob:none origin "$COMMIT"
git checkout -q FETCH_HEAD
rm -rf .git
for d in $DIRS; do test -d "$d" || { echo "缺少 $d"; exit 1; }; done
echo "Menagerie $COMMIT：$DIRS"
