#!/usr/bin/env bash
# 问渠数字工厂 · 本地版（ADR-0058）：在本机用 Docker 启动整座工厂。
# 用法：factory/local/start.sh [--prod] [--erpnext URL]
#   缺省：演示模式（仿真车间在跑，看板有数据）+ 模拟 ERPNext
#   --prod：生产模式（只显示接入的真实设备）
#   --erpnext URL：接你自己的 ERPNext（同时在 factory/digital/.env 填 API 密钥）
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dig="$here/../digital"
mode=teach
erp=""
while [ $# -gt 0 ]; do
  case "$1" in
    --prod) mode=prod ;;
    --erpnext) erp="$2"; shift ;;
    *) echo "不认识的参数：$1" >&2; exit 2 ;;
  esac
  shift
done
command -v docker >/dev/null || { echo "没有找到 docker：请先安装 Docker（Windows / macOS 用 Docker Desktop）" >&2; exit 1; }
env="$dig/.env"
if [ ! -f "$env" ]; then
  cp "$dig/.env.example" "$env"
  secret="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 || true)"
  sed -i.bak -e "s/^WQ_SECRET=.*/WQ_SECRET=$secret/" "$env" && rm -f "$env.bak"
  echo "已生成 $env（登录签名密钥随机生成；AI 助手的密钥可在里面填）"
fi
set_env() {  # 改写或追加一行 KEY=VALUE
  if grep -q "^$1=" "$env"; then sed -i.bak -e "s|^$1=.*|$1=$2|" "$env" && rm -f "$env.bak"; else echo "$1=$2" >> "$env"; fi
}
set_env WQ_MODE "$mode"
set_env WQ_EDITION local
set_env WQ_LOCAL_ROLES 0          # 企业工程师自己的电脑：不分老师学生（问渠那边学校机房的本地版才分，ADR-0068）
# 企业库（ADR-0055 / 0058）：与 FreeCAD 同一个文件夹——环境变量 FAP_ENTERPRISE_LIBRARY，或 FreeCAD 设置里选的
ent="${FAP_ENTERPRISE_LIBRARY:-}"
settings="$HOME/.freecad-ai-parts/settings.json"
if [ -z "$ent" ] && [ -f "$settings" ]; then
  ent="$(sed -n 's/.*"enterprise_library"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$settings" | head -n 1)"
fi
if [ -n "$ent" ] && [ -d "$ent" ]; then
  set_env FAP_ENTERPRISE_LIBRARY "$ent"
  echo "企业库：$ent"
elif grep -q "^FAP_ENTERPRISE_LIBRARY=" "$env"; then
  sed -i.bak -e "/^FAP_ENTERPRISE_LIBRARY=/d" "$env" && rm -f "$env.bak"
fi
profile=()
if [ -n "$erp" ]; then
  set_env WQ_ERPNEXT_API "$erp"
  set_env WQ_ERPNEXT_URL "$erp"
else
  set_env WQ_ERPNEXT_API http://mock-erpnext:8091
  set_env WQ_ERPNEXT_URL http://localhost:8091
  profile=(--profile mock)
fi
cd "$dig"
docker compose "${profile[@]}" up -d --build
echo "等工厂枢纽启动 …"
for _ in $(seq 1 120); do
  if curl -fsS http://localhost:8100/api/health >/dev/null 2>&1; then
    echo "已启动：打开 http://localhost:8100 （停止：factory/local/stop.sh）"
    exit 0
  fi
  sleep 2
done
echo "枢纽 4 分钟内没有就绪，看日志：cd factory/digital && docker compose logs hub" >&2
exit 1
