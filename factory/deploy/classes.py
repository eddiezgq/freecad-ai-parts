# -*- coding: utf-8 -*-
"""班级（小组）工厂（数字工厂第 10 轮 K1–K3）：按 classes.yaml 生成每个班的服务配置 docker-compose.classes.yml。

每个班一座独立的教学工厂：总线、枢纽、仿真车间、桥接、ERPNext 站点入口；历史库 wq_c_<编号>，ERPNext 站点 c-<编号>。
网址：<编号>.factory.<域名>（工作台）、<编号>.erp.<域名>（ERPNext），由学习平台的 Caddy 按需申请证书。

用法：python3 classes.py classes.yaml docker-compose.classes.yml [--ci-ports]
      python3 classes.py classes.yaml --ids        # 只打印编号（空格分隔），部署脚本用
"""
import re
import sys

import yaml

ID = re.compile(r"^[a-z][a-z0-9]{1,19}$")


def load(path):
    data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    out = []
    for c in data.get("classes") or []:
        cid = str(c.get("id", ""))
        if not ID.match(cid):
            raise SystemExit("班级编号 {!r} 不合规：小写字母开头，只用小写字母和数字，2～20 位".format(cid))
        if cid in ("demo", "www", "learn", "classic", "factory", "erp"):
            raise SystemExit("班级编号 {} 是保留名".format(cid))
        out.append({"id": cid, "name": str(c.get("name") or cid), "teachers": [str(t) for t in c.get("teachers") or []],
                    "course": str(c.get("course") or "")})
    if len({c["id"] for c in out}) != len(out):
        raise SystemExit("班级编号有重复")
    return out


def env_key(cid, what):
    return "WQ_C_{}_{}".format(cid.upper(), what)


def services(c, ci_ports=None):
    cid, up = c["id"], c["id"].upper()
    log = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}
    base_env = {"WQ_DB": "postgresql://wq:${WQ_DB_PASSWORD:?}@db:5432/wq_c_" + cid, "WQ_MQTT_HOST": "bus-c-" + cid,
                "WQ_MQTT_PORT": "1883", "WQ_MODE": "teach", "WQ_TZ": "${WQ_TZ:-America/New_York}"}
    app = {"image": "${FACTORY_APP_IMAGE:?FACTORY_APP_IMAGE}", "restart": "unless-stopped", "logging": log}
    s = {}
    s["bus-c-" + cid] = {"image": "eclipse-mosquitto:2.0.20", "restart": "unless-stopped", "logging": log,
                         "volumes": ["./mosquitto:/mosquitto/config:ro"],
                         "networks": {"default": {}, "edge": {"aliases": ["wqf-bus-c-" + cid]}}}
    s["hub-c-" + cid] = dict(app, environment=dict(
        base_env, WQ_MQTT_USER="hub", WQ_MQTT_PASSWORD="${WQ_MQTT_HUB_PASSWORD:?}",
        WQ_SECRET="${%s:?}" % env_key(cid, "SECRET"), WQ_AUTH="${WQ_AUTH:-wenquest}",
        WQ_SSO_URL="https://learn.${SITE_DOMAIN:?}/api/v1/auth/sso", WQ_LOGIN_URL="https://learn.${SITE_DOMAIN}/pages/login/login",
        WQ_MQTT_WS="wss://%s.factory.${SITE_DOMAIN}/mqtt" % cid, WQ_ERPNEXT_URL="https://%s.erp.${SITE_DOMAIN}" % cid,
        WQ_NODERED_URL="", WQ_ERPNEXT_API="http://erp-frontend-c-%s:8080" % cid,
        WQ_ERP_API_KEY="${%s:-}" % env_key(cid, "ERP_API_KEY"), WQ_ERP_API_SECRET="${%s:-}" % env_key(cid, "ERP_API_SECRET"),
        WQ_ERP_OAUTH_SECRET="${%s:-}" % env_key(cid, "ERP_OAUTH_SECRET"),
        WQ_AI_PER_HOUR="${WQ_AI_PER_HOUR:-30}", WQ_HISTORY_DAYS="${WQ_HISTORY_DAYS:-30}", WQ_LIBRARY_DIR="/library",
        WQ_LIBRARY_ORIGINS="https://%s.factory.${SITE_DOMAIN}" % cid, WQ_PUBLIC_URL="https://%s.factory.${SITE_DOMAIN}" % cid,
        WQ_CLAUDE_KEY="${WQ_CLAUDE_KEY:-}", WQ_CLAUDE_MODEL="${WQ_CLAUDE_MODEL:-claude-sonnet-5}",
        WQ_DEEPSEEK_KEY="${WQ_DEEPSEEK_KEY:-}", WQ_DEEPSEEK_MODEL="${WQ_DEEPSEEK_MODEL:-deepseek-chat}",
        WQ_SMTP_HOST="${WQ_SMTP_HOST:-}", WQ_SMTP_PORT="${WQ_SMTP_PORT:-2525}", WQ_SMTP_SECURE="${WQ_SMTP_SECURE:-tls}",
        WQ_SMTP_USER="${WQ_SMTP_USER:-}", WQ_SMTP_PASSWORD="${WQ_SMTP_PASSWORD:-}", WQ_MAIL_FROM="${WQ_MAIL_FROM:-}",
        WQ_FACTORY_NAME=c["name"], WQ_CLASS_TEACHERS=",".join(c["teachers"]),
        WQ_FACTORY_TASK_KEY="${WQ_FACTORY_TASK_KEY:-}"),          # 工程任务单钥匙（第 11 轮 2.7（5））：学习平台下达、读进度
        volumes=["./library:/library:ro"],
        depends_on={"db": {"condition": "service_healthy"}, "bus-c-" + cid: {"condition": "service_started"}},
        healthcheck={"test": ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen("
                              "'http://localhost:8100/api/health', timeout=5).status == 200 else 1)\""],
                     "interval": "15s", "timeout": "8s", "retries": 5, "start_period": "30s"},
        networks={"default": {}, "edge": {"aliases": ["wqf-hub-c-" + cid]}, "erp": {"aliases": ["wqf-hub-c-" + cid]}})
    s["sim-c-" + cid] = dict(app, command=["python", "sim/main.py"], depends_on=["bus-c-" + cid], environment=dict(
        base_env, WQ_MQTT_USER="sim", WQ_MQTT_PASSWORD="${WQ_MQTT_SIM_PASSWORD:?}", WQ_SIM_SPEED="${WQ_SIM_SPEED:-20}",
        WQ_OPENPLC_CHECK_URL="http://openplc:8300"))
    s["bridge-c-" + cid] = {"image": "${FACTORY_BRIDGE_IMAGE:?FACTORY_BRIDGE_IMAGE}", "restart": "unless-stopped", "logging": log,
                            "depends_on": ["bus-c-" + cid], "networks": ["default", "erp"],
                            "environment": {"WQ_MQTT_HOST": "bus-c-" + cid, "WQ_MQTT_PORT": "1883", "WQ_MQTT_USER": "bridge",
                                            "WQ_MQTT_PASSWORD": "${WQ_MQTT_BRIDGE_PASSWORD:?}", "WQ_MODE": "teach",
                                            "WQ_TZ": "${WQ_TZ:-America/New_York}", "WQ_ERPNEXT_API": "http://erp-frontend-c-%s:8080" % cid,
                                            "WQ_ERP_API_KEY": "${%s:-}" % env_key(cid, "ERP_API_KEY"),
                                            "WQ_ERP_API_SECRET": "${%s:-}" % env_key(cid, "ERP_API_SECRET"),
                                            "WQ_ERP_ABBR": "WQ", "WQ_HUB_PUBLIC_URL": "https://%s.factory.${SITE_DOMAIN}" % cid}}
    s["erp-frontend-c-" + cid] = {"image": "frappe/erpnext:v16.34.1", "restart": "unless-stopped", "logging": log,
                                  "command": ["nginx-entrypoint.sh"],
                                  "volumes": ["erp-sites:/home/frappe/frappe-bench/sites", "erp-logs:/home/frappe/frappe-bench/logs"],
                                  "environment": {"BACKEND": "erp-backend:8000", "FRAPPE_SITE_NAME_HEADER": "c-" + cid,
                                                  "SOCKETIO": "erp-websocket:9000", "UPSTREAM_REAL_IP_ADDRESS": "0.0.0.0/0",
                                                  "UPSTREAM_REAL_IP_HEADER": "X-Forwarded-For", "UPSTREAM_REAL_IP_RECURSIVE": "off",
                                                  "PROXY_READ_TIMEOUT": 120, "CLIENT_MAX_BODY_SIZE": "50m"},
                                  "depends_on": ["erp-backend", "erp-websocket"],
                                  "networks": {"erp": {}, "edge": {"aliases": ["wqf-erp-c-" + cid]}}}
    if ci_ports:
        s["hub-c-" + cid]["ports"] = ["{}:8100".format(ci_ports[0])]
        s["erp-frontend-c-" + cid]["ports"] = ["{}:8080".format(ci_ports[1])]
    return s


def compose(classes, ci_ports=False):
    svc = {}
    for i, c in enumerate(classes):
        svc.update(services(c, (8102 + i, 8093 + i) if ci_ports else None))
    # 公共工厂的枢纽回答 Caddy“这个网址能不能发证书”（按需申请证书）
    svc["hub"] = {"environment": {"WQ_CLASS_IDS": " ".join(c["id"] for c in classes)}}
    return {"services": svc}


if __name__ == "__main__":
    cls = load(sys.argv[1])
    if "--ids" in sys.argv:
        print(" ".join(c["id"] for c in cls))
        sys.exit(0)
    if "--names" in sys.argv:                 # 学习平台下达任务单时选班级工厂用（第 11 轮 2.7（5））：编号:名称,编号:名称
        print(",".join("{}:{}".format(c["id"], str(c["name"]).replace(",", "，").replace(":", "：")) for c in cls))
        sys.exit(0)
    head = "# 由 deploy/classes.py 按 classes.yaml 生成（第 10 轮），不要手改\n"
    open(sys.argv[2], "w", encoding="utf-8").write(head + yaml.safe_dump(compose(cls, "--ci-ports" in sys.argv),
                                                                         allow_unicode=True, sort_keys=False))
    print("班级工厂 {} 个：{}".format(len(cls), "、".join("{}（{}）".format(c["id"], c["name"]) for c in cls)))
