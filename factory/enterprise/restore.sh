#!/usr/bin/env bash
# 从备份恢复（ADR-0063）：./restore.sh backups/fap-<时间>.tar.gz
# 恢复数字工厂历史库与 ERPNext 数据；配置（.env、证书）只解到 backups/restore-<时间>/ 供核对，不覆盖现有的。
. "$(dirname "$0")/lib.sh"
f=${1:?用法：./restore.sh backups/fap-<时间>.tar.gz}
[ -f "$f" ] || die "没有这个备份：$f"
work="backups/restore-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$work" && tar -xzf "$f" -C "$work"
read -r -p "恢复会覆盖现在的数据（历史库与 ERPNext），确定吗？输入 yes：" ok
[ "$ok" = yes ] || die "没有恢复"
log "恢复数字工厂历史库..."
dc stop hub bridge
dc exec -T db pg_restore -U wq -d wq_factory --clean --if-exists < "$work/wq_factory.dump" || true
log "恢复 ERPNext..."
dc exec -T erp-backend bash -c 'mkdir -p /tmp/rs' && dc exec -T erp-backend bash -c 'cd /tmp/rs && tar -xf -' < "$work/erpnext.tar"
db=$(dc exec -T erp-backend bash -c 'ls -t /tmp/rs/*-database.sql.gz | head -n 1')
pub=$(dc exec -T erp-backend bash -c 'ls -t /tmp/rs/*-files.tar 2>/dev/null | head -n 1' || true)
priv=$(dc exec -T erp-backend bash -c 'ls -t /tmp/rs/*-private-files.tar 2>/dev/null | head -n 1' || true)
dc exec -T erp-backend bench --site frontend restore "$db" --db-root-username root \
    --db-root-password "$(envval ERP_DB_ROOT_PASSWORD)" ${pub:+--with-public-files "$pub"} ${priv:+--with-private-files "$priv"}
dc up -d hub bridge
log "恢复完成；备份里的配置在 $work/（env、config.tar），需要时对照修改"
