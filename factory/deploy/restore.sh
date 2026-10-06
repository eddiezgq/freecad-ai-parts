#!/usr/bin/env bash
# 从备份恢复数字工厂：deploy/restore.sh backups/<时间>
# 会覆盖当前的历史库和 ERPNext 数据；恢复前先自动再做一次备份。
. "$(dirname "$0")/lib.sh"
SRC="${1:?用法：deploy/restore.sh backups/<时间>}"
[ -f "$SRC/factory.dump" ] && [ -f "$SRC/erpnext.tar" ] || { echo "$SRC 里没有完整备份" >&2; exit 1; }
( cd "$SRC" && sha256sum -c SHA256SUMS )
log "恢复前先备份当前数据..."
"$(dirname "$0")/backup.sh"
dc stop hub sim bridge
log "恢复历史库..."
dc exec -T db pg_restore -U wq -d wq_factory --clean --if-exists < "$SRC/factory.dump"
log "恢复 ERPNext..."
dc exec -T erp-backend bash -c 'mkdir -p /tmp/restore && cd /tmp/restore && rm -f ./* && tar xf -' < "$SRC/erpnext.tar"
db=$(dc exec -T erp-backend bash -c 'ls -t /tmp/restore/*-database.sql.gz | head -1')
pub=$(dc exec -T erp-backend bash -c 'ls -t /tmp/restore/*-files.tar 2>/dev/null | grep -v private | head -1' || true)
pri=$(dc exec -T erp-backend bash -c 'ls -t /tmp/restore/*-private-files.tar 2>/dev/null | head -1' || true)
dc exec -T erp-backend bench --site frontend restore "$db" ${pub:+--with-public-files "$pub"} ${pri:+--with-private-files "$pri"} \
    --db-root-username root --db-root-password "$(envval ERP_DB_ROOT_PASSWORD)" --force
dc up -d
log "恢复完成。"
