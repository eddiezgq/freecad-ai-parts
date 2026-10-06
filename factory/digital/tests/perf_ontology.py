# -*- coding: utf-8 -*-
"""第 17 轮 A 期 A13 性能压测：合成约 100 万条总线消息，测从头重放、增量同步延迟、搜索、360 页、三跳关系图。

用法（本地 PostgreSQL）：python tests/perf_ontology.py [消息条数，默认 1000000]
做法：仿真器真跑一张 SH-301 工单（10 根轴，全部工序、检验、搬运），把这批消息改名复制成很多张工单，
时间往后错开，用 COPY 直接写进 bus_message（不经过 MQTT，压测的是本体，不是总线）。"""
import io
import json
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE)), HERE]

import psycopg  # noqa: E402

import wqbus  # noqa: E402
from sim.engine import Engine  # noqa: E402
from test_sim import FakeClock, dispatch_all, run_to_end  # noqa: E402

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0] + "/wq_ont_perf"


def template():
    out = []
    clock = FakeClock()
    eng = Engine(lambda tp, ty, src, data, corr: out.append((clock.t, tp, wqbus.make(ty, src, data, mode="teach", corr=corr))),
                 clock, mode="teach", auto_start=True, seed=5, status_every_s=60)
    dispatch_all(eng, wo="WO-TPL", qty=10)
    run_to_end(eng, clock)
    return out


def main(target, reuse=False):
    if reuse:
        return measure()
    with psycopg.connect(DSN.rsplit("/", 1)[0] + "/postgres", autocommit=True) as c:
        c.execute("drop database if exists wq_ont_perf with (force)")
        c.execute("create database wq_ont_perf")
    from hub.db import DB
    db = DB(DSN)
    db.init()
    tpl = template()
    span = max(t for t, _, _ in tpl) + 600
    copies = max(1, target // len(tpl))
    print("模板：一张工单 {} 条消息，仿真时长 {:.1f} 小时；复制 {} 份 → {} 条".format(len(tpl), span / 3600, copies, copies * len(tpl)))
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    serials = sorted({m["data"].get("part_serial") for _, _, m in tpl if m["data"].get("part_serial")} - {None},
                     key=len, reverse=True)
    tw = time.time()
    conn = psycopg.connect(DSN)
    for k in range(copies):
        buf = io.StringIO()
        wo = "WO-P{:05d}".format(k)
        for t, tp, m in tpl:
            s = json.dumps(m, ensure_ascii=False).replace("WO-TPL", wo)
            for sn in serials:
                if isinstance(sn, str) and sn in s:
                    s = s.replace(sn, "{}-{:05d}".format(sn, k))
            mm = json.loads(s)
            ts = t0 + timedelta(seconds=k * span + t)
            mm["ts"] = ts.isoformat()
            mm["id"] = str(uuid.uuid4())
            row = [mm["id"], ts.isoformat(), tp, mm["type"], mm["source"], "teach", mm.get("corr") or "", json.dumps(mm, ensure_ascii=False)]
            buf.write("\t".join(x.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n") for x in row) + "\n")
        buf.seek(0)
        with conn.cursor() as cur, cur.copy("copy bus_message (id, ts, topic, type, source, mode, corr, payload) from stdin") as cp:
            cp.write(buf.read())
        conn.commit()
        if k % 50 == 0:
            print("  写入 {}/{} 份".format(k + 1, copies), flush=True)
    conn.close()
    total = db.one("select count(*) as n from bus_message")["n"]
    print("合成消息 {} 条，用时 {:.0f} 秒".format(total, time.time() - tw))

    from hub.ont.store import Store
    from hub.ont.sync import Sync
    s = Sync(db, Store(db))
    s.init()
    t1 = time.time()
    n = s.replay()
    rep = time.time() - t1
    objs = db.one("select count(*) as n from ont_object")["n"]
    links = db.one("select count(*) as n from ont_link")["n"]
    print("从头重放：{} 条消息 → {} 个对象、{} 个链接，用时 {:.0f} 秒（目标 < 600），错误 {}".format(n, objs, links, rep, s.errors))

    # 增量：再写 1 份新工单，测从写入到本体出现的时间（后台线程 2 秒一轮、读 2 秒前的消息）
    import threading
    th = threading.Thread(target=s.run, kwargs={"every_s": 2, "reconcile_s": 1e9}, daemon=True)
    th.start()
    msg = wqbus.make("quality.measurement", "sim/qc-01", {"part_serial": "SH301-LAT-1", "item": "SH-301", "work_order": "WO-LAT",
                     "characteristic": "D1", "name": "Ø35 轴承位", "nominal_mm": 35.0, "lower_tol_mm": 34.99, "upper_tol_mm": 35.01,
                     "value_mm": 35.0, "result": "pass"}, mode="teach")
    from hub.historian import Historian
    Historian(db, lambda *a: None).handle("wq/gearbox/quality/qc-01/measurement", msg)
    tl = time.time()
    while not db.one("select 1 as x from ont_object where type='PartSerial' and key='SH301-LAT-1'"):
        time.sleep(0.1)
        if time.time() - tl > 30:
            break
    lat = time.time() - tl
    s.stop.set()
    print("增量同步延迟：{:.1f} 秒（目标 < 5）".format(lat))
    return measure(s, ok=rep < 600 and lat < 5)


def measure(s=None, ok=True):
    """只测接口耗时（--reuse：沿用上次合成的库）"""
    from hub.db import DB
    from hub.ont.store import Store
    from hub.ont.sync import Sync
    db = DB(DSN)
    if s is None:
        s = Sync(db, Store(db))
        s.init()

    # 接口耗时
    from fastapi.testclient import TestClient
    import hub.app as app_mod
    app_mod.H.db = db
    app_mod.H.ont = s
    c = TestClient(app_mod.app)
    h = {"X-WQ-Token": app_mod._sign({"name": "t", "role": "manager", "mode": "teach", "teacher": True, "exp": 9e12})}
    shaft = db.one("select src_key from ont_link where type='PartSerial.processed' and props->>'machine'='grd-01' "
                   "order by src_key desc limit 1")["src_key"]

    def timeit(f, k=7):
        xs = []
        for _ in range(k):
            a = time.time()
            r = f()
            assert r.status_code == 200, r.text
            xs.append((time.time() - a) * 1000)
        return statistics.median(xs)
    res = {
        "搜索（宽泛 SH301）": (timeit(lambda: c.get("/api/ont/search", params={"q": "SH301"}, headers=h)), 300),
        "搜索（编号片段）": (timeit(lambda: c.get("/api/ont/search", params={"q": shaft[-9:]}, headers=h)), 300),
        "搜索（别名 6207）": (timeit(lambda: c.get("/api/ont/search", params={"q": "6207"}, headers=h)), 300),
        "360 页（零件）": (timeit(lambda: c.get("/api/ont/obj/PartSerial/" + shaft, headers=h)), 500),
        "360 页（磨床）": (timeit(lambda: c.get("/api/ont/obj/Machine/grd-01", headers=h)), 500),
        "三跳关系图（零件）": (timeit(lambda: c.get("/api/ont/obj/PartSerial/{}/graph".format(shaft), params={"depth": 3}, headers=h)), 1000),
        "时间线（磨床）": (timeit(lambda: c.get("/api/ont/obj/Machine/grd-01/timeline", headers=h)), 500),
        "全貌地图": (timeit(lambda: c.get("/api/ont/types", headers=h)), 1000),
    }
    for k_, (ms, goal) in res.items():
        print("{}：{:.0f} 毫秒（目标 < {}）".format(k_, ms, goal))
        ok = ok and ms < goal
    print("结论：", "全部达标" if ok else "有未达标项")
    return 0 if ok else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(main(int(args[0]) if args else 1_000_000, reuse="--reuse" in sys.argv))
