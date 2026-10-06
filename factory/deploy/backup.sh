#!/usr/bin/env bash
# 数字工厂每日备份（D11）：历史库 + ERPNext 数据库与附件。由学习平台每天 03:30 的备份顺带调用，也可手动运行。
# 输出：/opt/wenquest/factory/backups/<时间>/；学习平台配了 Spaces 时同时传到 s3://<桶>/wenquest-factory/<时间>
. "$(dirname "$0")/lib.sh"
[ "$(envval FACTORY_INSTALLED)" = 1 ] || { log "数字工厂还没安装，跳过备份"; exit 0; }

TS=$(date +%Y%m%d-%H%M%S)
OUT="backups/$TS"
mkdir -p "$OUT"
log "数字工厂历史库..."
dc exec -T db pg_dump -U wq -d wq_factory -Fc > "$OUT/factory.dump"
log "ERPNext 数据库与附件..."
dc exec -T erp-backend bench --site frontend backup --with-files >/dev/null
dc exec -T erp-backend bash -c 'cd sites/frontend/private/backups && tar cf - $(ls -t | head -4)' > "$OUT/erpnext.tar"
dc exec -T erp-backend bash -c 'cd sites/frontend/private/backups && ls -t | tail -n +9 | xargs -r rm -f'
cp .env "$OUT/factory.env" && chmod 600 "$OUT/factory.env"
( cd "$OUT" && sha256sum factory.dump erpnext.tar > SHA256SUMS )
log "本机备份：$OUT（$(du -sh "$OUT" | cut -f1)）"

ENDPOINT=$(learnval BACKUP_S3_ENDPOINT); BUCKET=$(learnval BACKUP_S3_BUCKET)
if [ -n "$ENDPOINT" ] && [ -n "$BUCKET" ]; then
    docker run --rm -v "$FD/$OUT:/data:ro" \
        -e RCLONE_CONFIG_OFFSITE_TYPE=s3 -e RCLONE_CONFIG_OFFSITE_PROVIDER=Other \
        -e RCLONE_CONFIG_OFFSITE_ENDPOINT="$ENDPOINT" \
        -e RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID="$(learnval BACKUP_S3_ACCESS_KEY)" \
        -e RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY="$(learnval BACKUP_S3_SECRET_KEY)" \
        -e RCLONE_CONFIG_OFFSITE_ACL=private \
        rclone/rclone:1 copy /data "offsite:$BUCKET/wenquest-factory/$TS" --quiet
    log "已传到异地（Spaces）。"
fi
kd=$(learnval BACKUP_KEEP_DAYS); kd=${kd:-7}
find backups -mindepth 1 -maxdepth 1 -type d -mtime +"$kd" -exec rm -rf {} + 2>/dev/null || true
log "数字工厂备份完成。"
