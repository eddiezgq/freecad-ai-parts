#!/usr/bin/env bash
# 停止本地工厂（数据保留在 Docker 卷里，下次启动接着用）。加 --reset 连数据一起删。
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)/../digital"
if [ "${1:-}" = "--reset" ]; then docker compose --profile mock down -v; else docker compose --profile mock down; fi
