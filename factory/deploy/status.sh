#!/usr/bin/env bash
# 数字工厂运行状态：各容器、内存、历史库大小、两个网址是否能打开。
. "$(dirname "$0")/lib.sh"

dc ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'
echo
free -m | awk 'NR<=2 || /Swap/'
echo
dc exec -T db psql -U wq -d wq_factory -tAc \
    "select '历史库消息 ' || count(*) || ' 条，最早 ' || coalesce(to_char(min(ts), 'YYYY-MM-DD'), '-') from bus_message" 2>/dev/null || true
domain=$(envval SITE_DOMAIN)
for u in "https://factory.$domain/api/health" "https://erp.$domain/api/method/ping"; do
    printf '%-50s %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$u" || echo 失败)"
done
