#!/usr/bin/env bash
# 数字工厂首次安装（第 3 轮 D6）：生成密码 → 总线账号 → ERPNext 建站、完成设置向导、生成桥接钥匙 → 导入减速器厂数据。
# 可重复运行：已经做过的步骤会跳过。由 deploy/update.sh 在第一次部署时自动调用。
# 需要 .env 里已有 FACTORY_APP_IMAGE、FACTORY_BRIDGE_IMAGE（update.sh 会先写好）。
. "$(dirname "$0")/lib.sh"

rand() { tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "${1:-24}" || true; }

# ---------------------------------------------------------------- 1 配置与密码（只生成一次）
touch .env && chmod 600 .env
domain="${SITE_DOMAIN:-$(envval SITE_DOMAIN)}"
[ -n "$domain" ] || domain=$(learnval SITE_DOMAIN)
[ -n "$domain" ] || { echo "找不到域名：学习平台的 $LEARN_DIR/.env 里没有 SITE_DOMAIN" >&2; exit 1; }
envset SITE_DOMAIN "$domain"
for k in WQ_DB_PASSWORD WQ_MQTT_HUB_PASSWORD WQ_MQTT_SIM_PASSWORD WQ_MQTT_BRIDGE_PASSWORD WQ_SECRET WQ_DEMO_SECRET ERP_DB_ROOT_PASSWORD; do
    [ -n "$(envval "$k")" ] || envset "$k" "$(rand 32)"
done
[ -n "$(envval ERP_ADMIN_PASSWORD)" ] || envset ERP_ADMIN_PASSWORD "$(rand 20)"
# AI 工厂助手沿用学习平台的 Claude 密钥（D7）
if [ -z "$(envval WQ_CLAUDE_KEY)" ] && [ -n "$(learnval ANTHROPIC_API_KEY)" ]; then
    envset WQ_CLAUDE_KEY "$(learnval ANTHROPIC_API_KEY)"
fi

# ---------------------------------------------------------------- 2 总线账号（D5）
log "总线账号与授权..."
docker run --rm -v "$FD/mosquitto:/c" eclipse-mosquitto:2.0.20 sh -c "
    rm -f /c/passwd &&
    mosquitto_passwd -c -b /c/passwd hub '$(envval WQ_MQTT_HUB_PASSWORD)' &&
    mosquitto_passwd -b /c/passwd sim '$(envval WQ_MQTT_SIM_PASSWORD)' &&
    mosquitto_passwd -b /c/passwd bridge '$(envval WQ_MQTT_BRIDGE_PASSWORD)' &&
    chown 1883:1883 /c/passwd /c/acl /c/acl_web && chmod 0700 /c/passwd /c/acl /c/acl_web"

docker network inspect factory-edge >/dev/null 2>&1 || docker network create factory-edge >/dev/null 2>&1 || true

# ---------------------------------------------------------------- 3 ERPNext
log "启动 ERPNext..."
dc up -d erp-db erp-redis-cache erp-redis-queue
dc up -d erp-configurator
dc up -d erp-backend erp-websocket erp-queue-short erp-queue-long erp-scheduler erp-frontend

if ! dc exec -T erp-backend test -d sites/frontend; then
    log "新建 ERPNext 站点（约 3–5 分钟）..."
    dc exec -T erp-backend bench new-site --mariadb-user-host-login-scope='%' \
        --admin-password="$(envval ERP_ADMIN_PASSWORD)" \
        --db-root-username=root --db-root-password="$(envval ERP_DB_ROOT_PASSWORD)" \
        --install-app erpnext --set-default frontend
fi

setup=$(bench_exec frappe.is_setup_complete 2>/dev/null | tail -n 1 || true)
if [ "$setup" != "true" ] && [ "$setup" != "True" ] && [ "$setup" != "1" ]; then
    log "完成 ERPNext 设置向导（公司：问渠减速器厂 WenQuest Gearbox，缩写 WQ）..."
    year=$(date +%Y)
    bench_exec frappe.desk.page.setup_wizard.setup_wizard.initialize_system_settings_and_user --kwargs \
        "{'system_settings_data': {'language': 'en', 'country': 'United States', 'currency': 'USD', 'time_zone': 'America/New_York'}, 'user_data': {}}"
    bench_exec frappe.desk.page.setup_wizard.setup_wizard.setup_complete --kwargs \
        "{'args': {'language': 'English', 'country': 'United States', 'timezone': 'America/New_York', 'currency': 'USD',
          'company_name': '问渠减速器厂 WenQuest Gearbox', 'company_abbr': 'WQ', 'chart_of_accounts': 'Standard',
          'fy_start_date': '$year-01-01', 'fy_end_date': '$year-12-31', 'setup_demo': 0, 'enable_telemetry': 0}}"
fi
dc exec -T erp-backend bench --site frontend set-config host_name "https://erp.$domain" >/dev/null

if [ -z "$(envval WQ_ERP_API_KEY)" ]; then
    log "生成桥接用的 ERPNext API 钥匙..."
    keys=$(bench_exec frappe.core.doctype.user.user.generate_keys --args "['Administrator']" | tail -n 1)
    envset WQ_ERP_API_KEY "$(printf '%s' "$keys" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')"
    envset WQ_ERP_API_SECRET "$(printf '%s' "$keys" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_secret"])')"
fi

# ---------------------------------------------------------------- 4 导入减速器厂数据
log "导入减速器厂数据（物料、BOM、工艺路线、客户供应商、期初与教学库存）..."
ok=0
for i in 1 2 3 4 5 6; do              # ERPNext 网页刚启动时可能还没就绪，失败就等一会儿再试
    if dc run --rm seed; then ok=1; break; fi
    log "导入没成功，20 秒后重试（第 $i 次）..."
    sleep 20
done
[ "$ok" = 1 ] || { log "导入减速器厂数据失败，见上面的出错信息"; exit 1; }

envset FACTORY_INSTALLED 1
log "安装完成。ERPNext 管理员：Administrator，密码见服务器 $FD/.env 里的 ERP_ADMIN_PASSWORD"
