#!/usr/bin/env bash
# 下载并解包锁定版本的 FreeCAD（ADR-0032），供 FreeCAD 相关测试与 headless worker 使用。
# 用法：scripts/fetch_freecad.sh [目标目录，缺省 .freecad]
# 结束时打印解包目录；FreeCAD 内带 Python 为 <解包目录>/usr/bin/python，模块在 <解包目录>/usr/lib。
set -euo pipefail

VERSION=1.0.2
FILE="FreeCAD_${VERSION}-conda-Linux-x86_64-py311.AppImage"
SHA256=e00be00ad9fdb12b05c5002bfd1aa2ea8126f2c1d4e2fb603eb7423b72904f61
URL="https://github.com/FreeCAD/FreeCAD/releases/download/${VERSION}/${FILE}"
DEST="${1:-.freecad}"

mkdir -p "$DEST"
cd "$DEST"
if ! { [ -f "$FILE" ] && echo "${SHA256}  ${FILE}" | sha256sum -c --quiet - 2>/dev/null; }; then
  echo "下载 ${FILE} ..." >&2
  curl -fsSL --retry 3 -o "$FILE" "$URL"
  echo "${SHA256}  ${FILE}" | sha256sum -c --quiet -
fi
if [ ! -x squashfs-root/usr/bin/freecadcmd ]; then
  chmod +x "$FILE"
  ./"$FILE" --appimage-extract >/dev/null
fi
echo "$PWD/squashfs-root"
