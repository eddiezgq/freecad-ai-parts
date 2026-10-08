#!/usr/bin/env bash
# 备份（ADR-0063）：数字工厂历史库、ERPNext（数据库 + 附件）、配置与证书，打成 backups/fap-<时间>.tar.gz；保留最近 FAP_KEEP 份（缺省 14）。
# 建议每天定时运行：echo "30 2 * * * root /opt/fap/backup.sh" > /etc/cron.d/fap-backup
# 给了 FAP_BACKUP_COPY_TO（如另一块盘、挂载的对象存储目录），备份包再复制一份过去。
. "$(dirname "$0")/lib.sh"
ts=$(date +%Y%m%d-%H%M%S)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
log "备份数字工厂历史库..."
dc exec -T db pg_dump -U wq -d wq_factory -Fc > "$work/wq_factory.dump"
log "备份 ERPNext..."
dc exec -T erp-backend bench --site frontend backup --with-files >/dev/null
dc exec -T erp-backend bash -c 'cd sites/frontend/private/backups && tar -cf - $(ls -t | head -n 4)' > "$work/erpnext.tar"
cp .env "$work/env"
tar -cf "$work/config.tar" pki gateway-bundle plant Caddyfile docker-compose.yml 2>/dev/null || true
tar -czf "backups/fap-$ts.tar.gz" -C "$work" .
chmod 600 "backups/fap-$ts.tar.gz"
ls -1t backups/fap-*.tar.gz | tail -n +"$(( ${FAP_KEEP:-14} + 1 ))" | xargs -r rm -f
[ -z "${FAP_BACKUP_COPY_TO:-}" ] || cp "backups/fap-$ts.tar.gz" "$FAP_BACKUP_COPY_TO/"
log "备份完成：backups/fap-$ts.tar.gz"
echo "backups/fap-$ts.tar.gz"
