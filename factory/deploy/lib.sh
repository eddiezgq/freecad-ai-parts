# shellcheck shell=bash
# 数字工厂服务器脚本的公共部分。只供 source，不单独运行。
# 服务器目录默认 /opt/wenquest/factory（学习平台在上一级 /opt/wenquest）。
set -euo pipefail

FD="${FACTORY_DIR:-/opt/wenquest/factory}"
LEARN_DIR="${LEARN_DIR:-$(dirname "$FD")}"
cd "$FD"
mkdir -p library        # 零件库文件；先建好，免得 docker 以 root 身份建目录

# 从 .env 读一项（不 source，值里可能有空格）
envval() {
    local f="${2:-.env}" line
    line=$(grep -E "^$1=" "$f" 2>/dev/null | tail -n 1 || true)
    printf '%s' "${line#*=}"
}

envset() {
    touch .env
    if grep -qE "^$1=" .env; then
        sed -i "s|^$1=.*|$1=$2|" .env
    else
        printf '%s=%s\n' "$1" "$2" >> .env
    fi
}

learnval() { envval "$1" "$LEARN_DIR/.env"; }

dc() {
    local args=() f
    local def="docker-compose.yml"
    [ -f docker-compose.classes.yml ] && def="$def docker-compose.classes.yml"     # 班级工厂（第 10 轮）
    for f in ${FACTORY_COMPOSE:-$def}; do args+=(-f "$f"); done
    docker compose -p wq-factory "${args[@]}" "$@"
}

class_ids() { cat classes.ids 2>/dev/null || true; }      # 班级工厂编号（部署时由 classes.yaml 生成）

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# 在 ERPNext 里执行一个 Python 函数（bench execute），输出其返回值
bench_exec() {
    dc exec -T erp-backend bench --site "${ERP_SITE:-frontend}" execute "$@"
}

# 另建一座工厂（演示工厂第 9 轮、班级工厂第 10 轮共用）：历史库、ERPNext 站点、设置向导、钥匙、导数据、单点登录。可重复执行
# 用法：site_setup <显示名> <ERPNext 站点> <历史库> <站点入口服务> <枢纽内部地址> <工作台网址> <ERPNext 网址> <.env 前缀> <导数据参数> <服务…>
site_setup() {
    local label=$1 site=$2 db=$3 front=$4 hubint=$5 pub=$6 erppub=$7 pre=$8 seedopt=$9
    shift 9
    local year keys setup i
    [ -n "$(envval "${pre}_SECRET")" ] || envset "${pre}_SECRET" "$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32 || true)"
    [ -n "$(envval "${pre}_ERP_OAUTH_SECRET")" ] || envset "${pre}_ERP_OAUTH_SECRET" "$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 40 || true)"
    dc exec -T db psql -U wq -d wq_factory -tAc "select 1 from pg_database where datname='$db'" | grep -q 1 \
        || { log "$label：新建历史库 $db..."; dc exec -T db psql -U wq -d wq_factory -c "create database $db" >/dev/null; }
    if ! dc exec -T erp-backend test -d "sites/$site"; then
        log "$label：新建 ERPNext 站点 $site（约 3–5 分钟）..."
        dc exec -T erp-backend bench new-site --mariadb-user-host-login-scope='%' \
            --admin-password="$(envval ERP_ADMIN_PASSWORD)" \
            --db-root-username=root --db-root-password="$(envval ERP_DB_ROOT_PASSWORD)" \
            --install-app erpnext "$site"
    fi
    setup=$(ERP_SITE=$site bench_exec frappe.is_setup_complete 2>/dev/null | tail -n 1 || true)
    if [ "$setup" != "true" ] && [ "$setup" != "True" ] && [ "$setup" != "1" ]; then
        log "$label：完成 ERPNext 设置向导..."
        year=$(date +%Y)
        ERP_SITE=$site bench_exec frappe.desk.page.setup_wizard.setup_wizard.initialize_system_settings_and_user --kwargs \
            "{'system_settings_data': {'language': 'en', 'country': 'United States', 'currency': 'USD', 'time_zone': 'America/New_York'}, 'user_data': {}}"
        ERP_SITE=$site bench_exec frappe.desk.page.setup_wizard.setup_wizard.setup_complete --kwargs \
            "{'args': {'language': 'English', 'country': 'United States', 'timezone': 'America/New_York', 'currency': 'USD',
              'company_name': '问渠减速器厂 WenQuest Gearbox', 'company_abbr': 'WQ', 'chart_of_accounts': 'Standard',
              'fy_start_date': '$year-01-01', 'fy_end_date': '$year-12-31', 'setup_demo': 0, 'enable_telemetry': 0}}"
    fi
    dc exec -T erp-backend bench --site "$site" set-config host_name "$erppub" >/dev/null
    if [ -z "$(envval "${pre}_ERP_API_KEY")" ]; then
        log "$label：生成 ERPNext 钥匙..."
        keys=$(ERP_SITE=$site bench_exec frappe.core.doctype.user.user.generate_keys --args "['Administrator']" | tail -n 1)
        envset "${pre}_ERP_API_KEY" "$(printf '%s' "$keys" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')"
        envset "${pre}_ERP_API_SECRET" "$(printf '%s' "$keys" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_secret"])')"
    fi
    dc up -d "$front"
    local seedargs=(python seed.py --url "http://$front:8080" --user Administrator --password "$(envval ERP_ADMIN_PASSWORD)"
                    --factory-url "$pub")
    if [ "$(envval "${pre}_SEEDED")" != 1 ]; then
        log "$label：导入减速器厂数据..."
        for i in 1 2 3 4 5 6; do
            # shellcheck disable=SC2086
            if dc run --rm seed "${seedargs[@]}" $seedopt; then envset "${pre}_SEEDED" 1; break; fi
            log "导入没成功，20 秒后重试（第 $i 次）..."; sleep 20
        done
    fi
    dc run --rm seed "${seedargs[@]}" --erp-sso-only --sso-secret "$(envval "${pre}_ERP_OAUTH_SECRET")" \
        --hub-internal "$hubint" > "/tmp/wq-sso-$site.log" 2>&1 \
        && log "$label：单点登录已配置。" || { log "警告：$label 单点登录没配置成功："; tail -5 "/tmp/wq-sso-$site.log"; }
    dc up -d "$@"                 # 钥匙刚生成时让它们带上新配置
}

# 企业版演示工厂（第 9 轮）
demo_setup() {
    local domain
    domain=$(envval SITE_DOMAIN)
    # 第 9 轮用的 .env 名字（WQ_DEMO_*，DEMO_SEEDED）沿用
    [ "$(envval DEMO_SEEDED)" = 1 ] && envset WQ_DEMO_SEEDED 1
    site_setup 演示工厂 demo wq_demo erp-frontend-demo http://wqf-hub-demo:8100 "https://demo.$domain" \
        "https://demo-erp.$domain" WQ_DEMO "--opening-stock --teach-stock" hub-demo sim-demo bridge-demo bus-demo
}

# 班级（小组）工厂（第 10 轮）：class_setup <编号>
class_setup() {
    local id=$1 up domain
    up=$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')
    domain=$(envval SITE_DOMAIN)
    site_setup "班级工厂 $id" "c-$id" "wq_c_$id" "erp-frontend-c-$id" "http://wqf-hub-c-$id:8100" "https://$id.factory.$domain" \
        "https://$id.erp.$domain" "WQ_C_$up" "--opening-stock --teach-stock" "hub-c-$id" "sim-c-$id" "bridge-c-$id" "bus-c-$id"
}
