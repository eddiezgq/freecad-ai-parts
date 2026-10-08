#!/usr/bin/env bash
# 问渠数字工厂 · 企业安装版：首次安装（ADR-0063）。可重复运行：做过的步骤会跳过。
#
# 用法（在服务器上，安装包目录里，用 root 或 docker 组的用户）：
#   ./install.sh --domain factory.example.com --email it@example.com --admin admin
#   ./install.sh --domain factory.local --tls-internal --admin admin           # 内网 / 测试：自签证书
# 选项：
#   --domain 域名         工作台地址（必填）；ERPNext 默认在 erp.<域名>（--erp-domain 可改）。两个域名都要解析到本机
#   --email 邮箱          自动申请 HTTPS 证书（Let's Encrypt）用；或 --tls-internal 用自签证书
#   --admin 用户名        第一个管理员；密码从环境变量 FAP_ADMIN_PASSWORD 读，没有时提示输入
#   --region cn|intl      AI 模型地区：cn 用 DeepSeek，intl 用 Claude；不给时按本机时区推断（中国时区算 cn）
#   --claude-key / --deepseek-key   AI 密钥（可以以后在 .env 里补）
#   --demo                演示模式：启动仿真车间（生产模式只显示接入的真实设备）
#   --plant 清单.yaml     企业自己的工厂清单（ADR-0064；Excel 用 python -m factory.plant import 转成）。
#                         ERPNext 的公司、国家、币种、时区，工作站、工序、车间平面都按它建；不给时装演示工厂
#   --images 标签         镜像标签（缺省 latest）；--no-pull 用本机已有镜像（离线安装、CI）
#   --registry-token 令牌 拉取私有镜像用的 GitHub 只读令牌（也可用环境变量 FAP_REGISTRY_TOKEN）
. "$(dirname "$0")/lib.sh"

DOMAIN="" ERP_DOMAIN="" EMAIL="" TLS_INTERNAL=0 ADMIN="" REGION="" DEMO=0 TAG="latest" PULL=1
CLAUDE_KEY="" DEEPSEEK_KEY="" REG_TOKEN="${FAP_REGISTRY_TOKEN:-}" PLANT=""
while [ $# -gt 0 ]; do
    case "$1" in
        --domain) DOMAIN=$2; shift 2 ;;
        --erp-domain) ERP_DOMAIN=$2; shift 2 ;;
        --email) EMAIL=$2; shift 2 ;;
        --tls-internal) TLS_INTERNAL=1; shift ;;
        --admin) ADMIN=$2; shift 2 ;;
        --region) REGION=$2; shift 2 ;;
        --claude-key) CLAUDE_KEY=$2; shift 2 ;;
        --deepseek-key) DEEPSEEK_KEY=$2; shift 2 ;;
        --demo) DEMO=1; shift ;;
        --plant) PLANT=$(abspath "$2"); shift 2 ;;
        --images) TAG=$2; shift 2 ;;
        --no-pull) PULL=0; shift ;;
        --registry-token) REG_TOKEN=$2; shift 2 ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) die "不认识的选项：$1（--help 看用法）" ;;
    esac
done

# ---------------------------------------------------------------- 1 检查环境
log "检查环境..."
[ -z "$PLANT" ] || [ -f "$PLANT" ] || die "找不到工厂清单 $PLANT"
command -v docker >/dev/null || die "没有 Docker：Ubuntu 上运行 curl -fsSL https://get.docker.com | sh"
docker compose version >/dev/null 2>&1 || die "没有 docker compose 插件"
command -v openssl >/dev/null || die "没有 openssl"
command -v curl >/dev/null || die "没有 curl"
mem_gb=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 0)
[ "$mem_gb" -ge "${FAP_MIN_MEM_GB:-7}" ] || die "内存 ${mem_gb} GB，至少要 8 GB（建议 16 GB）"
[ "$mem_gb" -ge 15 ] || log "提醒：内存 ${mem_gb} GB，建议 16 GB（有限元、流体计算要内存）"
disk_gb=$(df -Pk "$FD" | awk 'NR==2 {printf "%d", $4/1024/1024}')
[ "$disk_gb" -ge "${FAP_MIN_DISK_GB:-40}" ] || die "磁盘剩余 ${disk_gb} GB，至少要 40 GB（建议 100 GB）"

# ---------------------------------------------------------------- 2 配置与密码（只生成一次）
[ -n "$DOMAIN" ] || DOMAIN=$(envval FAP_DOMAIN)
[ -n "$DOMAIN" ] || die "要给 --domain（工作台域名）"
[ -n "$ERP_DOMAIN" ] || ERP_DOMAIN=$(envval FAP_ERP_DOMAIN)
[ -n "$ERP_DOMAIN" ] || ERP_DOMAIN="erp.$DOMAIN"
envset FAP_DOMAIN "$DOMAIN"
envset FAP_ERP_DOMAIN "$ERP_DOMAIN"
if [ "$TLS_INTERNAL" = 1 ]; then envset FAP_TLS internal
elif [ -n "$EMAIL" ]; then envset FAP_TLS "$EMAIL"
elif [ -z "$(envval FAP_TLS)" ]; then die "要给 --email（申请 HTTPS 证书）或 --tls-internal（自签证书）"
fi
[ -n "$(envval WQ_AI_PROVIDER)" ] || envset WQ_AI_PROVIDER auto
[ -z "$CLAUDE_KEY" ] || envset WQ_CLAUDE_KEY "$CLAUDE_KEY"
[ -z "$DEEPSEEK_KEY" ] || envset WQ_DEEPSEEK_KEY "$DEEPSEEK_KEY"
if [ "$DEMO" = 1 ]; then envset FAP_MODE teach; envset COMPOSE_PROFILES demo; fi
[ -n "$(envval FAP_MODE)" ] || envset FAP_MODE prod
envset FAP_FACTORY_IMAGE "${FAP_FACTORY_IMAGE:-ghcr.io/eddiezgq/fap-factory:$TAG}"
envset FAP_BRIDGE_IMAGE "${FAP_BRIDGE_IMAGE:-ghcr.io/eddiezgq/fap-bridge:$TAG}"
for k in WQ_DB_PASSWORD WQ_MQTT_HUB_PASSWORD WQ_MQTT_SIM_PASSWORD WQ_MQTT_BRIDGE_PASSWORD WQ_MQTT_GATEWAY_PASSWORD \
         WQ_SECRET WQ_TWIN_DEVICE_KEY ERP_DB_ROOT_PASSWORD; do
    [ -n "$(envval "$k")" ] || envset "$k" "$(rand 32)"
done
[ -n "$(envval ERP_ADMIN_PASSWORD)" ] || envset ERP_ADMIN_PASSWORD "$(rand 20)"

# ---------------------------------------------------------------- 3 总线账号与现场网关证书
log "总线账号..."
docker run --rm -v "$FD/mosquitto:/c" eclipse-mosquitto:2.0.20 sh -c "
    rm -f /c/passwd &&
    mosquitto_passwd -c -b /c/passwd hub '$(envval WQ_MQTT_HUB_PASSWORD)' &&
    mosquitto_passwd -b /c/passwd sim '$(envval WQ_MQTT_SIM_PASSWORD)' &&
    mosquitto_passwd -b /c/passwd bridge '$(envval WQ_MQTT_BRIDGE_PASSWORD)' &&
    mosquitto_passwd -b /c/passwd gateway '$(envval WQ_MQTT_GATEWAY_PASSWORD)'"
mkdir -p mosquitto/certs pki && chmod 700 pki
if [ ! -f mosquitto/certs/server.crt ]; then
    log "生成现场网关用的证书（工厂自有 CA，10 年；CA 私钥只留在 pki/，不交给总线）..."
    openssl req -x509 -newkey rsa:3072 -nodes -days 3650 -subj "/CN=FAP Factory CA" \
        -keyout pki/ca.key -out pki/ca.crt 2>/dev/null
    openssl req -newkey rsa:2048 -nodes -subj "/CN=$DOMAIN" -keyout pki/server.key -out pki/server.csr 2>/dev/null
    printf 'subjectAltName=DNS:%s\n' "$DOMAIN" > pki/san.ext
    openssl x509 -req -in pki/server.csr -CA pki/ca.crt -CAkey pki/ca.key -CAcreateserial -days 3650 \
        -extfile pki/san.ext -out pki/server.crt 2>/dev/null
    rm -f pki/server.csr pki/san.ext
    chmod 600 pki/*.key
    cp pki/ca.crt pki/server.crt pki/server.key mosquitto/certs/
fi
docker run --rm -v "$FD/mosquitto:/c" eclipse-mosquitto:2.0.20 sh -c \
    "chown -R 1883:1883 /c/passwd /c/certs && chmod 0700 /c/passwd && chmod 0755 /c/certs && chmod 0644 /c/certs/ca.crt /c/certs/server.crt && chmod 0600 /c/certs/server.key"

# ---------------------------------------------------------------- 4 镜像
if [ "$PULL" = 1 ]; then
    if [ -n "$REG_TOKEN" ]; then
        printf '%s' "$REG_TOKEN" | docker login ghcr.io -u "${FAP_REGISTRY_USER:-fap}" --password-stdin >/dev/null
    fi
    log "拉取镜像（第一次约 5–10 分钟）..."
    dc pull --ignore-buildable --quiet
fi

# ---------------------------------------------------------------- 4b 工厂清单（ADR-0064）与时区、AI 地区
mkdir -p plant
COMPANY_JSON=""
if [ -n "$PLANT" ]; then log "校验工厂清单 $PLANT ..."; plant_put "$PLANT"; fi
if [ -n "$(envval WQ_PLANT_FILE)" ]; then
    COMPANY_JSON=$(plant_company)
    [ -n "$COMPANY_JSON" ] || die "读不出工厂清单里的公司"
    cj() { printf '%s' "$COMPANY_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }
    envset WQ_TZ "$(cj timezone)"
    envset FAP_ERP_ABBR "$(cj abbr)"          # 桥接按它拼仓库名（“原材料库 Raw - 缩写”）
fi
tz=$(cat /etc/timezone 2>/dev/null || timedatectl show -p Timezone --value 2>/dev/null || echo UTC)
[ -n "$(envval WQ_TZ)" ] || envset WQ_TZ "$tz"
if [ -n "$REGION" ]; then envset WQ_AI_REGION "$REGION"
elif [ -z "$(envval WQ_AI_REGION)" ]; then
    case "$(envval WQ_TZ)" in Asia/Shanghai|Asia/Chongqing|Asia/Harbin|Asia/Urumqi|PRC) envset WQ_AI_REGION cn ;; *) envset WQ_AI_REGION intl ;; esac
fi
log "域名 $DOMAIN、ERPNext $ERP_DOMAIN、证书 $(envval FAP_TLS)、AI 地区 $(envval WQ_AI_REGION)、模式 $(envval FAP_MODE)、工厂 ${COMPANY_JSON:-演示工厂}"

# ---------------------------------------------------------------- 5 ERPNext
log "启动 ERPNext..."
dc up -d erp-db erp-redis-cache erp-redis-queue
dc up -d erp-configurator
dc up -d erp-backend erp-websocket erp-queue-short erp-queue-long erp-scheduler erp-frontend
for i in $(seq 1 60); do dc exec -T erp-backend true 2>/dev/null && break; sleep 3; done
if ! dc exec -T erp-backend test -d sites/frontend; then
    log "新建 ERPNext 站点（约 3–5 分钟）..."
    dc exec -T erp-backend bench new-site --mariadb-user-host-login-scope='%' \
        --admin-password="$(envval ERP_ADMIN_PASSWORD)" \
        --db-root-username=root --db-root-password="$(envval ERP_DB_ROOT_PASSWORD)" \
        --install-app erpnext --set-default frontend
fi
setup=$(bench_exec frappe.is_setup_complete 2>/dev/null | tail -n 1 || true)
if [ "$setup" != "true" ] && [ "$setup" != "True" ] && [ "$setup" != "1" ]; then
    log "完成 ERPNext 设置向导..."
    # 公司按工厂清单（没有清单时是演示公司）；参数用 Python 字面量生成，公司名里有引号也不会出错
    wiz=$(COMPANY_JSON="$COMPANY_JSON" TZV="$(envval WQ_TZ)" YEAR="$(date +%Y)" python3 - <<'PY'
import json, os
c = json.loads(os.environ["COMPANY_JSON"] or "null") or {
    "name": "问渠减速器厂 WenQuest Gearbox", "abbr": "WQ", "country": "United States", "currency": "USD"}
tz, y = os.environ["TZV"], os.environ["YEAR"]
print(repr({"system_settings_data": {"language": "en", "country": c["country"], "currency": c["currency"], "time_zone": tz},
            "user_data": {}}))
print(repr({"args": {"language": "English", "country": c["country"], "timezone": tz, "currency": c["currency"],
                     "company_name": c["name"], "company_abbr": c["abbr"], "chart_of_accounts": "Standard",
                     "fy_start_date": y + "-01-01", "fy_end_date": y + "-12-31", "setup_demo": 0, "enable_telemetry": 0}}))
PY
)
    bench_exec frappe.desk.page.setup_wizard.setup_wizard.initialize_system_settings_and_user --kwargs "$(printf '%s\n' "$wiz" | sed -n 1p)"
    bench_exec frappe.desk.page.setup_wizard.setup_wizard.setup_complete --kwargs "$(printf '%s\n' "$wiz" | sed -n 2p)"
fi
dc exec -T erp-backend bench --site frontend set-config host_name "https://$ERP_DOMAIN" >/dev/null
if [ -z "$(envval WQ_ERP_API_KEY)" ]; then
    log "生成桥接用的 ERPNext API 钥匙..."
    keys=$(bench_exec frappe.core.doctype.user.user.generate_keys --args "['Administrator']" | tail -n 1)
    envset WQ_ERP_API_KEY "$(printf '%s' "$keys" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')"
    envset WQ_ERP_API_SECRET "$(printf '%s' "$keys" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_secret"])')"
fi

# ---------------------------------------------------------------- 6 数字工厂
log "启动数字工厂..."
dc up -d db bus cae
dc up -d hub bridge caddy
[ "$(envval FAP_MODE)" = teach ] && dc up -d sim
for i in $(seq 1 60); do
    dc exec -T hub python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/api/health', timeout=5)" \
        >/dev/null 2>&1 && break
    sleep 5
done

if [ -z "$(envval FAP_SEEDED)" ]; then
    log "把工厂主数据导入 ERPNext..."
    ok=0
    for i in 1 2 3 4 5 6; do
        if dc run --rm seed; then ok=1; break; fi
        log "导入没成功，20 秒后重试（第 $i 次）..."
        sleep 20
    done
    [ "$ok" = 1 ] || die "导入工厂主数据失败，见上面的出错信息"
    envset FAP_SEEDED 1
fi

# ---------------------------------------------------------------- 7 第一个管理员
if [ -n "$ADMIN" ]; then
    pw="${FAP_ADMIN_PASSWORD:-}"
    if [ -z "$pw" ]; then
        read -r -s -p "给管理员 $ADMIN 设密码（至少 10 位，字母加数字）：" pw; echo
    fi
    if printf '%s\n' "$pw" | dc exec -T hub python -m hub.accounts create-admin "$ADMIN" 2>/tmp/fap-admin.err; then
        log "管理员 $ADMIN 已建好"
    elif grep -q "已存在" /tmp/fap-admin.err; then
        log "管理员 $ADMIN 已经有了，跳过"
    else
        cat /tmp/fap-admin.err >&2; die "建管理员没成功"
    fi
    rm -f /tmp/fap-admin.err
fi

# ---------------------------------------------------------------- 8 现场网关的连接包、首次备份
mkdir -p gateway-bundle
cp pki/ca.crt gateway-bundle/ca.crt
cat > gateway-bundle/gateway.env <<EOF
# 现场网关连云端用（factory/gateway，ADR-0063）。这份文件里有密码，只交给工厂的网关管理员
FAP_CLOUD_HOST=$DOMAIN
FAP_CLOUD_PORT=8883
FAP_GATEWAY_USER=gateway
FAP_GATEWAY_PASSWORD=$(envval WQ_MQTT_GATEWAY_PASSWORD)
EOF
chmod 600 gateway-bundle/gateway.env
"$FD/backup.sh" >/dev/null && log "首次备份完成（backups/）"

envset FAP_INSTALLED "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "安装完成："
log "  工作台  https://$DOMAIN    （管理员 ${ADMIN:-未建：重新运行加 --admin}）"
log "  ERPNext https://$ERP_DOMAIN （Administrator，密码见 $FD/.env 的 ERP_ADMIN_PASSWORD）"
log "  现场网关的连接包：$FD/gateway-bundle/（ca.crt、gateway.env）"
log "  AI：$(envval WQ_AI_REGION) 地区，密钥 Claude $( [ -n "$(envval WQ_CLAUDE_KEY)" ] && echo 已配 || echo 未配)、DeepSeek $( [ -n "$(envval WQ_DEEPSEEK_KEY)" ] && echo 已配 || echo 未配)"
