#!/usr/bin/env bash
# 把数字工厂换到新镜像并重启（由 GitHub Actions“数字工厂部署”调用，也可在服务器上手动运行）。
# 用法：deploy/update.sh [工厂镜像] [桥接镜像] [OpenPLC 镜像]      不带参数：用现有镜像重启（例如改了 .env 之后）
# 第一次运行会先检查内存，再自动执行 deploy/install.sh。
. "$(dirname "$0")/lib.sh"

APP="${1:-}"; BRIDGE="${2:-}"; OPENPLC="${3:-}"
[ -n "$APP" ] && envset FACTORY_APP_IMAGE "$APP"
[ -n "$BRIDGE" ] && envset FACTORY_BRIDGE_IMAGE "$BRIDGE"
[ -n "$OPENPLC" ] && envset FACTORY_OPENPLC_IMAGE "$OPENPLC"          # OpenPLC 运行时（第 18 轮第 8 步）
[ -n "$(envval FACTORY_APP_IMAGE)" ] || { echo "还没有镜像：请通过 GitHub Actions 部署" >&2; exit 1; }

# 课程接口只读钥匙（第 4 轮 C2）：没有就生成；学习平台的 deploy/update.sh 从这里读去用
[ -n "$(envval WQ_FACTORY_READ_KEY)" ] || envset WQ_FACTORY_READ_KEY "$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 40 || true)"
# 工程任务单钥匙（第 11 轮 2.7（5））：学习平台下达任务单、读进度和分数；公共工厂和班级工厂共用，学习平台部署时复制过去
[ -n "$(envval WQ_FACTORY_TASK_KEY)" ] || envset WQ_FACTORY_TASK_KEY "$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 40 || true)"
# 数字孪生真设备接入钥匙（第 15 轮）：现场采集器 POST /api/twin/telemetry 时用
[ -n "$(envval WQ_TWIN_DEVICE_KEY)" ] || envset WQ_TWIN_DEVICE_KEY "$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 40 || true)"
# ERPNext 单点登录密钥（第 7 轮 E5）：枢纽与 ERPNext 社交登录共用；没有就生成
[ -n "$(envval WQ_ERP_OAUTH_SECRET)" ] || envset WQ_ERP_OAUTH_SECRET "$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 40 || true)"
# 企业版演示工厂（第 9 轮）的工作台密钥：启动前要有
[ -n "$(envval WQ_DEMO_SECRET)" ] || envset WQ_DEMO_SECRET "$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32 || true)"
# AI 代理的模型、厂情提醒的发信（第 17 轮 D 期）：工厂 .env 里没填的，沿用学习平台已有的配置（Claude / DeepSeek 密钥、SMTP）
[ -n "$(envval WQ_CLAUDE_KEY)" ] || [ -z "$(learnval ANTHROPIC_API_KEY)" ] || envset WQ_CLAUDE_KEY "$(learnval ANTHROPIC_API_KEY)"
[ -n "$(envval WQ_DEEPSEEK_KEY)" ] || [ -z "$(learnval DEEPSEEK_API_KEY)" ] || envset WQ_DEEPSEEK_KEY "$(learnval DEEPSEEK_API_KEY)"
for k in HOST PORT SECURE USER PASSWORD; do
    [ -n "$(envval "WQ_SMTP_$k")" ] || [ -z "$(learnval "SMTP_$k")" ] || envset "WQ_SMTP_$k" "$(learnval "SMTP_$k")"
done
[ -n "$(envval WQ_MAIL_FROM)" ] || [ -z "$(learnval MOODLE_NOREPLY_EMAIL)" ] || envset WQ_MAIL_FROM "$(learnval MOODLE_NOREPLY_EMAIL)"
for id in $(class_ids); do                 # 班级工厂（第 10 轮）的工作台密钥
    k="WQ_C_$(printf '%s' "$id" | tr '[:lower:]' '[:upper:]')_SECRET"
    [ -n "$(envval "$k")" ] || envset "$k" "$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32 || true)"
done

if [ "$(envval FACTORY_INSTALLED)" != 1 ]; then
    # D1：ERPNext 加数字工厂约需 3 GB 内存。不够就停下，提示升级服务器，免得拖垮学习平台
    avail=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
    swap=$(awk '/SwapFree/ {print int($2/1024)}' /proc/meminfo)
    need="${FACTORY_MIN_MEM_MB:-3000}"
    log "可用内存 ${avail} MB，交换空间 ${swap} MB（需要至少 ${need} MB 可用内存）"
    if [ "$avail" -lt "$need" ]; then
        echo "::error::服务器可用内存只有 ${avail} MB，装数字工厂需要 ${need} MB。请在 DigitalOcean 控制台把这台服务器升到 16 GB（Resize），完成后重新运行“数字工厂部署”。学习平台未受影响。"
        exit 3
    fi
    log "第一次部署：执行安装（先生成密码和配置，再拉镜像、启动）..."
    "$(dirname "$0")/install.sh"
fi

log "拉取镜像..."
dc pull --quiet
log "启动数字工厂..."
dc up -d --remove-orphans

log "等待枢纽就绪..."
for _ in $(seq 1 40); do
    st=$(docker inspect -f '{{.State.Health.Status}}' "$(dc ps -q hub)" 2>/dev/null || echo unknown)
    if [ "$st" = healthy ]; then
        log "数字工厂已就绪。"
        # 零件库编号（第 5 轮 P10②）：每次部署补到 ERPNext 物料上；失败不影响运行，下次部署再试
        if [ "$(envval FACTORY_INSTALLED)" = 1 ]; then
            if dc run --rm seed python seed.py --url http://erp-frontend:8080 --user Administrator \
                    --password "$(envval ERP_ADMIN_PASSWORD)" --library-refs-only \
                    --factory-url "https://factory.$(envval SITE_DOMAIN)" > /tmp/wq-libref.log 2>&1; then
                log "零件库编号已同步到 ERPNext。"
            else
                log "警告：零件库编号没有同步到 ERPNext（不影响运行，下次部署再试）："
                tail -5 /tmp/wq-libref.log
            fi
            # 问渠单点登录（第 7 轮 E5）：每次部署检查并补齐 ERPNext 侧设置
            if dc run --rm seed python seed.py --url http://erp-frontend:8080 --user Administrator \
                    --password "$(envval ERP_ADMIN_PASSWORD)" --erp-sso-only --sso-secret "$(envval WQ_ERP_OAUTH_SECRET)" \
                    --factory-url "https://factory.$(envval SITE_DOMAIN)" > /tmp/wq-sso.log 2>&1; then
                log "ERPNext 单点登录已配置。"
            else
                log "警告：ERPNext 单点登录没有配置成功（下次部署再试）："
                tail -5 /tmp/wq-sso.log
            fi
            # 企业版演示工厂（第 9 轮）：可用内存够才建；失败不影响教学工厂，下次部署再试
            avail=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
            if [ "$avail" -lt "${DEMO_MIN_MEM_MB:-1200}" ] && ! dc exec -T erp-backend test -d sites/demo; then
                log "警告：可用内存只有 ${avail} MB，演示工厂暂不建（需要约 1.2 GB）。请把服务器升到 16 GB 后重新部署。"
            elif bash -c ". '$(dirname "$0")/lib.sh'; demo_setup"; then
                log "演示工厂已就绪：https://demo.$(envval SITE_DOMAIN)"
            else
                log "警告：演示工厂没有配置完成（不影响教学工厂，下次部署再试）"
            fi
            # 班级（小组）工厂（第 10 轮）：按 classes.yaml 逐个建好；新建的要可用内存够
            for id in $(class_ids); do
                avail=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
                if [ "$avail" -lt "${CLASS_MIN_MEM_MB:-900}" ] && ! dc exec -T erp-backend test -d "sites/c-$id"; then
                    log "警告：可用内存只有 ${avail} MB，班级工厂 $id 暂不建（需要约 0.9 GB）。请把服务器升到 16 GB 后重新部署。"
                elif bash -c ". '$(dirname "$0")/lib.sh'; class_setup '$id'"; then
                    log "班级工厂 $id 已就绪：https://$id.factory.$(envval SITE_DOMAIN)"
                else
                    log "警告：班级工厂 $id 没有配置完成（不影响其他工厂，下次部署再试）"
                fi
            done
        fi
        docker image prune -f >/dev/null
        "$(dirname "$0")/status.sh" || true
        exit 0
    fi
    sleep 6
done
log "枢纽 4 分钟内没有就绪，最近日志："
dc logs --tail 60 hub bridge sim bus
exit 1
