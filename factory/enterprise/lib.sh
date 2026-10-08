# shellcheck shell=bash
# 企业安装版脚本的公共部分（ADR-0063）。只供 source，不单独运行。
# 安装目录默认就是脚本所在目录（远程部署时是 /opt/fap）。
set -euo pipefail

FD="${FAP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
cd "$FD"
mkdir -p library backups

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "出错：$*" >&2; exit 1; }

# 从 .env 读一项（不 source，值里可能有空格）
envval() {
    local line
    line=$(grep -E "^$1=" "${2:-.env}" 2>/dev/null | tail -n 1 || true)
    printf '%s' "${line#*=}"
}

envset() {
    touch .env && chmod 600 .env
    local v=${2//|/\\|}
    if grep -qE "^$1=" .env; then
        sed -i "s|^$1=.*|$1=$v|" .env
    else
        printf '%s=%s\n' "$1" "$2" >> .env
    fi
}

rand() { tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "${1:-24}" || true; }

dc() { docker compose -p fap --env-file .env -f docker-compose.yml "$@"; }

# 在 ERPNext 里执行一个 Python 函数（bench execute），输出其返回值
bench_exec() { dc exec -T erp-backend bench --site frontend execute "$@"; }

# 等某个地址返回 200（最多 $2 秒）
wait_http() {
    local url=$1 limit=${2:-300} t=0
    until curl -fsk -o /dev/null "$url"; do
        t=$((t + 5)); [ "$t" -lt "$limit" ] || return 1
        sleep 5
    done
}
