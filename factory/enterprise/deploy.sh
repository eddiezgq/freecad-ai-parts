#!/usr/bin/env bash
# 远程部署到企业的服务器（ADR-0063）：在我们这边（仓库根目录）运行，经 SSH 把安装包传过去并安装。
#   factory/enterprise/deploy.sh 用户@服务器 --domain factory.example.com --email it@example.com --admin admin [其他 install.sh 选项]
#   factory/enterprise/deploy.sh 用户@服务器 --upgrade [镜像标签]      升级（先备份）
#   factory/enterprise/deploy.sh 用户@服务器 --status                  看状态
#   factory/enterprise/deploy.sh 用户@服务器 --backup                  立即备份
# 需要：能用 SSH 密钥登录服务器，该用户能 sudo；服务器装好 Docker（install.sh 会检查）。安装目录 FAP_REMOTE_DIR（缺省 /opt/fap）。
# 密码、密钥只在服务器上生成，不经过这里；管理员密码在安装时于终端里输入（或用 FAP_ADMIN_PASSWORD 环境变量传过去）。
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
host=${1:?用法见脚本开头}
shift
dir=${FAP_REMOTE_DIR:-/opt/fap}
ssh_t() { ssh -t -o ServerAliveInterval=30 "$host" "$@"; }

case "${1:-}" in
    --upgrade) ssh_t "cd $dir && sudo ./upgrade.sh ${2:-latest}"; exit 0 ;;
    --status) ssh_t "cd $dir && sudo ./status.sh"; exit 0 ;;
    --backup) ssh_t "cd $dir && sudo ./backup.sh"; exit 0 ;;
esac

echo "传安装包到 $host:$dir ..."
ssh "$host" "sudo mkdir -p $dir && sudo chown \$(id -u):\$(id -g) $dir"
# 只传安装包与公共零件库；服务器上已有的 .env、证书、账号、备份不动
rsync -az --delete \
    --exclude .env --exclude backups/ --exclude gateway-bundle/ --exclude mosquitto/certs/ --exclude mosquitto/passwd \
    --exclude library/ "$here/" "$host:$dir/"
rsync -az --delete "$root/data/library/" "$host:$dir/library/"
args=$(printf ' %q' "$@")
ssh_t "cd $dir && sudo FAP_ADMIN_PASSWORD=${FAP_ADMIN_PASSWORD:+$(printf %q "$FAP_ADMIN_PASSWORD")} FAP_REGISTRY_TOKEN=${FAP_REGISTRY_TOKEN:-} ./install.sh$args"
