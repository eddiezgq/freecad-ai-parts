#!/usr/bin/env bash
# 现场网关启动（ADR-0063，用 root 或 docker 组的用户运行）：把云端安装时生成的连接包（gateway-bundle/ 里的 ca.crt、gateway.env）放到本目录，运行 ./start.sh
#   FAP_LOCAL_USER / FAP_LOCAL_PASSWORD：给车间设备、采集器连本机用的账号（不给时本机 1883 只允许工厂内网匿名连接）
#   FAP_CLOUD_IP：只在测试时用（云端在同一台机器上），正式部署不要设
set -euo pipefail
cd "$(dirname "$0")"
[ -f gateway.env ] && [ -f ca.crt ] || { echo "缺连接包：把云端的 gateway-bundle/ca.crt、gateway.env 复制到这里" >&2; exit 1; }
set -a; . ./gateway.env; set +a
: "${FAP_CLOUD_HOST:?gateway.env 里没有 FAP_CLOUD_HOST}" "${FAP_GATEWAY_PASSWORD:?gateway.env 里没有 FAP_GATEWAY_PASSWORD}"
mkdir -p conf
cp ca.crt conf/ca.crt
{
cat <<CONF
# 由 start.sh 生成，不要手改
persistence true
persistence_location /mosquitto/data/
autosave_interval 60
max_queued_messages 200000
queue_qos0_messages true
log_dest stdout
log_type error
log_type warning
log_type notice

listener 1883
CONF
if [ -n "${FAP_LOCAL_USER:-}" ]; then
    echo "allow_anonymous false"
    echo "password_file /mosquitto/config/passwd"
else
    echo "allow_anonymous true"
fi
cat <<CONF

connection fap-cloud
address ${FAP_CLOUD_HOST}:${FAP_CLOUD_PORT:-8883}
remote_clientid fap-gateway-$(hostname | tr -cd 'A-Za-z0-9-' | head -c 30)
remote_username ${FAP_GATEWAY_USER:-gateway}
remote_password ${FAP_GATEWAY_PASSWORD}
bridge_cafile /mosquitto/config/ca.crt
bridge_tls_version tlsv1.2
bridge_insecure false
cleansession false
try_private true
start_type automatic
restart_timeout 5 60
notifications false
# 送上去：车间各区域设备的状态、事件、测量
topic wq/gearbox/machining/# out 1
topic wq/gearbox/quality/# out 1
topic wq/gearbox/logistics/# out 1
topic wq/gearbox/warehouse/# out 1
topic wq/gearbox/field/# out 1
# 带回来：下发给设备的指令、数控程序与工艺下达
topic wq/gearbox/+/+/cmd in 1
topic wq/gearbox/+/+/gcode in 1
topic wq/gearbox/+/+/release in 1
CONF
} > conf/mosquitto.conf
chmod 600 conf/mosquitto.conf
if [ -n "${FAP_LOCAL_USER:-}" ]; then
    docker run --rm -v "$PWD/conf:/c" eclipse-mosquitto:2.0.20 \
        mosquitto_passwd -c -b /c/passwd "$FAP_LOCAL_USER" "${FAP_LOCAL_PASSWORD:?要给 FAP_LOCAL_PASSWORD}"
fi
docker run --rm -v "$PWD/conf:/c" eclipse-mosquitto:2.0.20 sh -c "chown -R 1883:1883 /c && chmod 0700 /c"
files=(-f docker-compose.yml)
if [ -n "${FAP_CLOUD_IP:-}" ]; then            # 测试：云端域名指到给定地址（host-gateway = 本机）
    printf 'services:\n  broker:\n    extra_hosts: ["%s:%s"]\n' "$FAP_CLOUD_HOST" "$FAP_CLOUD_IP" > docker-compose.test.yml
    files+=(-f docker-compose.test.yml)
fi
docker compose -p fap-gateway "${files[@]}" up -d
echo "现场网关已启动：车间设备连本机 1883，数据经 TLS 送到 ${FAP_CLOUD_HOST}:${FAP_CLOUD_PORT:-8883}"
