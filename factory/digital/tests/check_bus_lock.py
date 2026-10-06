# -*- coding: utf-8 -*-
"""第 3 轮 D5 验收：服务器版总线加锁。

1. 匿名连 1883（服务用的端口）被拒；
2. 浏览器（匿名，WebSocket 9001）能收到消息，但发出的消息不会到达任何人；
3. 仿真账号不能写 AI 主题，桥接账号不能给设备发指令。

用法：python3 tests/check_bus_lock.py --host localhost --hub-password ... --sim-password ... --bridge-password ...
"""
import argparse
import sys
import time
import uuid

import paho.mqtt.client as mqtt

P = argparse.ArgumentParser()
P.add_argument("--host", default="localhost")
P.add_argument("--port", type=int, default=1883)
P.add_argument("--ws-port", type=int, default=9001)
P.add_argument("--hub-password", required=True)
P.add_argument("--sim-password", required=True)
P.add_argument("--bridge-password", required=True)
A = P.parse_args()
FAILS = []


def check(ok, what):
    print(("  ✓ " if ok else "  ✗ ") + what)
    if not ok:
        FAILS.append(what)


def client(user=None, pw=None, ws=False):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="lockcheck-" + uuid.uuid4().hex[:6],
                    transport="websockets" if ws else "tcp")
    if ws:
        c.ws_set_options(path="/mqtt")
    if user:
        c.username_pw_set(user, pw)
    return c


def connect(c, port):
    res = {}
    c.on_connect = lambda cl, u, f, rc, p=None: res.setdefault("rc", rc)
    try:
        c.connect(A.host, port, 10)
    except OSError as e:
        return str(e)
    c.loop_start()
    for _ in range(50):
        if "rc" in res:
            break
        time.sleep(0.1)
    return res.get("rc")


anon = client()
rc = connect(anon, A.port)
check(rc is not None and rc != 0, "匿名连服务端口被拒（{}）".format(rc))
anon.loop_stop()

hub = client("hub", A.hub_password)
check(connect(hub, A.port) == 0, "枢纽账号能连")
seen = []
hub.on_message = lambda c, u, m: seen.append((m.topic, m.payload.decode()))
hub.subscribe("wq/lockcheck/#")
hub.subscribe("wq/gearbox/ai/lockcheck")
hub.subscribe("wq/gearbox/machining/lockcheck/cmd")
web = client(ws=True)
check(connect(web, A.ws_port) == 0, "浏览器（匿名 WebSocket /mqtt）能连")
web_seen = []
web.on_message = lambda c, u, m: web_seen.append(m.payload.decode())
web.subscribe("wq/lockcheck/#")
sim = client("sim", A.sim_password)
connect(sim, A.port)
bridge = client("bridge", A.bridge_password)
connect(bridge, A.port)
time.sleep(1)

web.publish("wq/lockcheck/x", "from-web")
sim.publish("wq/gearbox/ai/lockcheck", "from-sim")
bridge.publish("wq/gearbox/machining/lockcheck/cmd", "from-bridge")
hub.publish("wq/lockcheck/x", "from-hub")
time.sleep(2)

payloads = [p for _, p in seen]
check("from-hub" in web_seen, "浏览器能收到总线消息")
check("from-web" not in payloads, "浏览器发出的消息被丢弃")
check("from-sim" not in payloads, "仿真账号不能写 AI 主题")
check("from-bridge" not in payloads, "桥接账号不能给设备发指令")
for c in (hub, web, sim, bridge):
    c.loop_stop()
if FAILS:
    sys.exit(1)
print("总线加锁检查通过。")
