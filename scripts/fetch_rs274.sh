#!/usr/bin/env bash
# 下载并解包 LinuxCNC 的 RS274NGC 解释器 rs274（ADR-0106 E1：独立解释器核对正式程序），锁定 Debian 13 的包与 SHA-256。
# rs274 是 GPL 的外部程序，只在测试时调用，不进仓库、不随问渠CAM 分发。
# 用法：scripts/fetch_rs274.sh [目标目录，缺省 ~/.freecad-ai-parts/rs274]
# 结束时打印 rs274 可执行文件的路径（设到环境变量 FAP_RS274）。
set -euo pipefail

BASE="https://snapshot.debian.org/archive/debian/20261101T000000Z/pool/main"
PKGS=(
  "l/linuxcnc/linuxcnc-uspace_2.9.4-2%2Bdeb13u1_amd64.deb b4b8bbefab20e7d3cc797cd3285091eb15a63e0982cca3135d1d4325ce0f8c88"
  "b/boost1.83/libboost-python1.83.0_1.83.0-4.2_amd64.deb 97043d6b48d768cf01e35cfe1db4df1b2d7be2d961e365ef2a318e75e3993d33"
  "p/python3.13/libpython3.13_3.13.5-2%2Bdeb13u5_amd64.deb aa4cdb7e15f5f445ab268160d428518a4daf2a086ee3e6ea30f6082785236dea"
)
DEST="${1:-$HOME/.freecad-ai-parts/rs274}"

mkdir -p "$DEST/debs"
cd "$DEST"
for p in "${PKGS[@]}"; do
  path="${p% *}"; sha="${p#* }"; file="debs/$(basename "${path//%2B/+}")"
  if ! { [ -f "$file" ] && echo "${sha}  ${file}" | sha256sum -c --quiet - 2>/dev/null; }; then
    echo "下载 $(basename "$file") ..." >&2
    curl -fsSL --retry 3 -o "$file" "$BASE/$path"
    echo "${sha}  ${file}" | sha256sum -c --quiet -
  fi
  dpkg-deb -x "$file" root
done
echo "$PWD/root/usr/bin/rs274"
