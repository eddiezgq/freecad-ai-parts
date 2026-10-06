# -*- coding: utf-8 -*-
"""线上车间检查（数字工厂第 6 轮 W7①）：部署后像浏览器一样连接统一数据总线，看设备有没有在发数据。

用法：python3 online_check.py <域名> [秒数=30]
输出 GitHub 注释（notice / warning），通过 GitHub 接口就能读到结果；不让部署失败。
"""
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import paho.mqtt.client as mqtt

domain = sys.argv[1]
secs = int(sys.argv[2]) if len(sys.argv) > 2 else 30
# 第 9 轮：演示工厂用 `online_check.py <域名> 30 demo demo-erp prod`
FAC = sys.argv[3] if len(sys.argv) > 3 else "factory"
ERP = sys.argv[4] if len(sys.argv) > 4 else "erp"
MODE = sys.argv[5] if len(sys.argv) > 5 else "teach"
lines, ok = [], True


def say(text):
    lines.append(text)
    print(text)


# 1. 网关配置：浏览器拿到的总线地址
try:
    with urllib.request.urlopen("https://{}.{}/api/config".format(FAC, domain), timeout=20) as r:
        cfg = json.loads(r.read().decode("utf-8"))
    say("网关配置 mqtt_ws = {}，default_mode = {}".format(cfg.get("mqtt_ws"), cfg.get("default_mode")))
except Exception as e:  # noqa: BLE001
    cfg = {}
    say("读不到 /api/config：{}".format(e))

# 2. 连接总线（WebSocket，匿名只读，同浏览器）
url = cfg.get("mqtt_ws") or "wss://{}.{}/mqtt".format(FAC, domain)
u = urllib.parse.urlsplit(url)
host, path = u.hostname, u.path or "/"
port = u.port or (443 if u.scheme == "wss" else 80)
state = {"connected": None, "n": 0, "units": {}, "types": {}}


def on_connect(c, u, flags, rc, props=None):
    state["connected"] = str(rc)
    c.subscribe("wq/gearbox/#")


def on_message(c, u, m):
    state["n"] += 1
    try:
        d = json.loads(m.payload.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return
    key = "{}:{}".format(d.get("mode"), d.get("type"))
    state["types"][key] = state["types"].get(key, 0) + 1
    if d.get("type") == "machine.status":
        state["units"].setdefault(d.get("mode"), {})[m.topic.split("/")[3]] = (d.get("data") or {}).get("state")


c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="wq-online-check", transport="websockets")
c.ws_set_options(path=path)
if url.startswith("wss"):
    c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
c.on_connect, c.on_message = on_connect, on_message
try:
    c.connect(host, port, keepalive=30)
    c.loop_start()
    time.sleep(secs)
    c.loop_stop()
    c.disconnect()
except Exception as e:  # noqa: BLE001
    say("连接总线 {} 失败：{}".format(url, e))
    ok = False

say("总线连接结果：{}；{} 秒收到 {} 条消息".format(state["connected"], secs, state["n"]))
for mode, units in sorted(state["units"].items()):
    say("  {} 模式设备 {} 台：{}".format(mode, len(units), "，".join("{}={}".format(k, v) for k, v in sorted(units.items()))))
say("  消息种类：" + "，".join("{} {}".format(k, v) for k, v in sorted(state["types"].items())))
if state["connected"] != "Success" or not state["units"].get(MODE):
    ok = False

# 3. ERPNext 登录页：问渠单点登录按钮和自动跳转脚本（第 7 轮）
try:
    with urllib.request.urlopen("https://{}.{}/login".format(ERP, domain), timeout=30) as r:
        page = r.read().decode("utf-8", "replace")
    with urllib.request.urlopen("https://{}.{}/website_script.js".format(ERP, domain), timeout=30) as r:
        js = r.read().decode("utf-8", "replace")
    btn, auto = "btn-wenquest" in page, "wenquest-sso" in js
    import re
    m = re.search(r'href="([^"]+)"\s+class="[^"]*btn-wenquest', page)
    if m:
        href = m.group(1).replace("&amp;", "&")
        say("  登录按钮指向：" + href.split("&state=")[0])

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            urllib.request.build_opener(NoRedirect).open(href, timeout=30)
            say("  授权接口（没带问渠登录）：没有跳转")
        except urllib.error.HTTPError as e:
            say("  授权接口（没带问渠登录）：{} → {}".format(e.code, (e.headers.get("location") or e.read().decode("utf-8", "replace"))[:160]))
    say("ERPNext 单点登录：登录按钮{}，自动跳转脚本{}".format("有" if btn else "没有", "有" if auto else "没有"))
    ok = ok and btn and auto
except Exception as e:  # noqa: BLE001
    say("读不到 ERPNext 登录页：{}".format(e))
    ok = False

# 4. 有限元计算服务（第 11 轮）：经本厂枢纽转交
try:
    with urllib.request.urlopen("https://{}.{}/api/cae/health".format(FAC, domain), timeout=30) as r:
        h = json.loads(r.read().decode())
    say("有限元计算服务：在线（正在算 {}，排队 {}）".format(h.get("running") or "无", h.get("queued")))
    ok = ok and bool(h.get("ok"))
except Exception as e:  # noqa: BLE001
    say("有限元计算服务连不上：{}".format(e))
    ok = False

msg = "%0A".join(x.replace("%", "%25") for x in lines)
print("::{} title=线上{}检查（{}）::{}".format("notice" if ok else "warning", "演示工厂" if FAC == "demo" else ("班级工厂 " + FAC.split(".")[0] if "." in FAC else "车间"), "正常" if ok else "有问题", msg))
