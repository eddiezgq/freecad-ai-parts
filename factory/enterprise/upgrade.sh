#!/usr/bin/env bash
# 升级（ADR-0063）：先备份，再拉新镜像、重启。
#   ./upgrade.sh [镜像标签，缺省 latest] [--plant 新的工厂清单.yaml] [--license 授权.json]
# 换工厂清单（ADR-0064）：先校验，有错不换；换好后补建 ERPNext 里新的工作站、工序（已有的不动），再重启。
# 公司（名称、币种、时区）在首次安装时定下，换清单不改；清单里改了公司要另行处理。
. "$(dirname "$0")/lib.sh"
tag=latest PLANT="" LICENSE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --plant) PLANT=$(abspath "$2"); shift 2 ;;
        --license) LICENSE=$(abspath "$2"); shift 2 ;;
        -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
        *) tag=$1; shift ;;
    esac
done
[ -z "$PLANT" ] || [ -f "$PLANT" ] || die "找不到工厂清单 $PLANT"
[ -z "$LICENSE" ] || [ -f "$LICENSE" ] || die "找不到授权文件 $LICENSE"
"$FD/backup.sh" >/dev/null && log "升级前已备份"
envset FAP_FACTORY_IMAGE "ghcr.io/eddiezgq/fap-factory:$tag"
envset FAP_BRIDGE_IMAGE "ghcr.io/eddiezgq/fap-bridge:$tag"
[ "${FAP_NO_PULL:-0}" = 1 ] || dc pull --quiet hub bridge
mkdir -p plant
[ -z "$LICENSE" ] || license_put "$LICENSE"      # 换授权（ADR-0066）：工厂服务改了文件会自己重读
if [ -n "$PLANT" ]; then
    old=$(plant_company)
    plant_put "$PLANT"
    new=$(plant_company)
    [ "$old" = "$new" ] || log "提醒：清单里的公司变了（$old → $new）；ERPNext 的公司不随之改"
    log "换了工厂清单，补建 ERPNext 的工作站与工序..."
    dc run --rm seed
fi
dc up -d
if [ -n "$PLANT" ]; then        # 清单路径不变、内容变了，up 不会重建容器：重启读新清单
    dc restart hub
    [ -z "$(dc ps -q sim 2>/dev/null)" ] || dc restart sim
fi
log "升级完成（$tag）"
"$FD/status.sh"
