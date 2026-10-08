#!/usr/bin/env bash
# 升级（ADR-0063）：先备份，再拉新镜像、重启。./upgrade.sh [镜像标签，缺省 latest]
. "$(dirname "$0")/lib.sh"
tag=${1:-latest}
"$FD/backup.sh" >/dev/null && log "升级前已备份"
envset FAP_FACTORY_IMAGE "ghcr.io/eddiezgq/fap-factory:$tag"
envset FAP_BRIDGE_IMAGE "ghcr.io/eddiezgq/fap-bridge:$tag"
dc pull --quiet hub bridge
dc up -d
log "升级完成（$tag）"
"$FD/status.sh"
