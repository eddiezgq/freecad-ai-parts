#!/usr/bin/env bash
# 状态（ADR-0063）：各服务是否在跑、工作台与 ERPNext 是否能打开、证书、磁盘、最近一次备份。
. "$(dirname "$0")/lib.sh"
dc ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'
d=$(envval FAP_DOMAIN); e=$(envval FAP_ERP_DOMAIN)
ok() { if curl -fsk -o /dev/null --max-time 10 --resolve "$1:443:127.0.0.1" "https://$1$2"; then echo 正常; else echo 打不开; fi; }
echo "工作台 https://$d：$(ok "$d" /api/health)"
echo "ERPNext https://$e：$(ok "$e" /api/method/ping)"
echo "磁盘剩余：$(df -Ph "$FD" | awk 'NR==2 {print $4}')"
echo "最近备份：$(ls -1t backups/fap-*.tar.gz 2>/dev/null | head -n 1 || echo 没有)"
