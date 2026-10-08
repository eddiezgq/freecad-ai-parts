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

# ---------------------------------------------------------------- 工厂清单（ADR-0064）
# 清单放在安装目录的 plant/plant.yaml，只读挂进容器的 /plant；WQ_PLANT_FILE 指向它。没有清单时用演示工厂
plant_check() { dc run --rm --no-deps -T seed python -m factory.plant check "/plant/${1:-plant.yaml}"; }
plant_company() {
    dc run --rm --no-deps -T seed python -c \
        "import json; from factory import plant; print(json.dumps(plant.company(), ensure_ascii=False))" | tail -n 1
}
# 把清单放进来并校验（$1 = 企业给的清单文件）；有错不替换现有的
plant_put() {
    mkdir -p "$FD/plant"
    cp "$1" "$FD/plant/plant.new.yaml" && chmod 644 "$FD/plant/plant.new.yaml"
    if ! plant_check plant.new.yaml; then
        rm -f "$FD/plant/plant.new.yaml"
        die "工厂清单有错（见上），改好再来；本机校验：python -m factory.plant check 清单.yaml"
    fi
    mv "$FD/plant/plant.new.yaml" "$FD/plant/plant.yaml"
    envset WQ_PLANT_FILE /plant/plant.yaml
}
