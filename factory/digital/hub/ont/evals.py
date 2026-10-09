# -*- coding: utf-8 -*-
"""AI 代理评测集（第 17 轮 D 期 D4）：读 digital/ontology/evals/*.yaml，逐题问代理、逐项核对、存档。

规则版每次推送在测试里跑（要求全过）；模型版在服务器上手动跑（目标 ≥ 90%），结果存进 ai_eval_run。"""
import glob
import json
import os
import re
import subprocess

import yaml
from psycopg.types.json import Jsonb

from hub.ont import schema as S

SCHEMA = """
create table if not exists ai_eval_run (
    id         bigserial primary key,
    mode       text not null,
    engine     text not null,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    passed     integer,
    total      integer,
    results    jsonb,
    git_sha    text,
    started_by text
);
"""
EVAL_DIR = os.path.join(S.DIR, "evals")
AS = {"teacher": {"name": "评测·老师", "role": "manager", "teacher": True, "mode": "teach"},
      "student": {"name": "评测·学生", "role": "planner", "teacher": False, "mode": "teach"},
      "prod_manager": {"name": "评测·厂长", "role": "manager", "teacher": False, "mode": "prod"}}


def init(db):
    db.x(SCHEMA)


def load(path=EVAL_DIR):
    out = []
    for f in sorted(glob.glob(os.path.join(path, "*.yaml"))):
        doc = yaml.safe_load(open(f, encoding="utf-8")) or {}
        for it in doc.get("items") or []:
            out.append(dict(it, domain=doc.get("domain"), file=os.path.basename(f)))
    ids = [x["id"] for x in out]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ValueError("评测题号重复：" + "、".join(sorted(dup)))
    return out


def slots(db, mode="teach"):
    """占位符：按当时的数据填（停机的设备、它的异常、延期风险订单、缺料、最近有完工记录的工单、瓶颈）"""
    from hub import kpi
    ov = kpi.overview(db, None, mode)
    s = {"grd": "GRD-01"}
    a = db.one("select id from anomaly where mode=%s and rule='P1' and subject_key='grd-01' and status in ('open','ack','doing') "
               "order by id desc limit 1", (mode,))
    s["grd_anomaly"] = "A-{:05d}".format(a["id"]) if a else "A-?????"
    w = db.one("select id, subject_key from anomaly where mode=%s and rule in ('W1','W2') and status in ('open','ack','doing') "
               "order by (subject_key='BRG-6207') desc, id limit 1", (mode,))
    s["low_anomaly"] = "A-{:05d}".format(w["id"]) if w else "A-?????"
    low = [m["code"] for m in ov["materials"] if m["tone"] == "bad"]
    s["low_item"] = low[0] if low else "—"
    risky = [o["name"] for o in ov["orders"] if o["tone"] in ("bad", "warn")] or [o["name"] for o in ov["orders"]]
    s["late_so"] = risky[0] if risky else "—"
    b = ov["week"]["bottleneck"]
    s["bottleneck"] = b.upper() if b else "—"
    r = db.one("select corr from bus_message where type='machine.event' and mode=%s and corr like 'MFG-WO-%%' "
               "and payload->'data'->>'event'='op_complete' order by ts desc limit 1", (mode,))
    s["wo"] = r["corr"] if r else "—"
    # 第 18 轮 E1：投诉、它的异常、投诉的设备和客户（简称）
    try:
        c = db.one("select id, serial, customer from complaint where mode=%s order by id limit 1", (mode,))
    except Exception:  # noqa: BLE001  （老库没有投诉表）
        c = None
    s["complaint"] = "CP-{:05d}".format(c["id"]) if c else "CP-?????"
    s["complaint_serial"] = (c or {}).get("serial") or "—"
    s["complaint_customer"] = ((c or {}).get("customer") or "—").split(" ")[0]
    a = db.one("select id from anomaly where mode=%s and rule='C1' and detail->'values'->>'complaint'=%s order by id desc limit 1",
               (mode, s["complaint"]))
    s["complaint_anomaly"] = "A-{:05d}".format(a["id"]) if a else "A-?????"
    # 第 18 轮 E2：重大隐患和它的异常
    try:
        si = db.one("select id from safety_issue where mode=%s and level='major' order by id limit 1", (mode,))
    except Exception:  # noqa: BLE001
        si = None
    s["si_major"] = "SI-{:05d}".format(si["id"]) if si else "SI-?????"
    a = db.one("select id from anomaly where mode=%s and rule='E1' and fkey=%s order by id desc limit 1", (mode, s["si_major"]))
    s["si_anomaly"] = "A-{:05d}".format(a["id"]) if a else "A-?????"
    a = db.one("select id from anomaly where mode=%s and rule='M2' and subject_key='grd-01' order by id desc limit 1", (mode,))
    s["pm_anomaly"] = "A-{:05d}".format(a["id"]) if a else "A-?????"
    a = db.one("select id from anomaly where mode=%s and rule='H2' and status in ('open','ack','doing') order by id limit 1", (mode,))
    s["gap_anomaly"] = "A-{:05d}".format(a["id"]) if a else "A-?????"
    try:
        x = db.one("select lot from lot where mode=%s and status='rejected' order by id limit 1", (mode,))
    except Exception:  # noqa: BLE001
        x = None
    s["bad_lot"] = x["lot"] if x else "L??????-????"
    a = db.one("select id from anomaly where mode=%s and rule='W3' and status in ('open','ack','doing') order by id limit 1", (mode,))
    s["lot_anomaly"] = "A-{:05d}".format(a["id"]) if a else "A-?????"
    a = db.one("select id from anomaly where mode=%s and rule='N2' and status in ('open','ack','doing') order by id limit 1", (mode,))
    s["idle_anomaly"] = "A-{:05d}".format(a["id"]) if a else "A-?????"
    a = db.one("select id from anomaly where mode=%s and rule='F2' and status in ('open','ack','doing') order by id limit 1", (mode,))
    s["overdue_anomaly"] = "A-{:05d}".format(a["id"]) if a else "A-?????"
    try:
        x = db.one("select sales_order from order_margin where mode=%s order by sales_order limit 1", (mode,))
    except Exception:  # noqa: BLE001
        x = None
    s["margin_so"] = x["sales_order"] if x else "SAL-ORD-2026-?????"
    return s


def _fill(x, sl):
    return re.sub(r"\{(\w+)\}", lambda m: str(sl.get(m.group(1), m.group(0))), x)


def grade(item, r, sl):
    """一题的核对：返回失败原因列表（空 = 通过）"""
    why = []
    ans = r.get("answer") or ""
    for t in item.get("tools") or []:
        if t not in (r.get("tools") or []):
            why.append("没有调用 {}".format(t))
    for c in item.get("contains") or []:
        c = _fill(c, sl)
        if c not in ans:
            why.append("回答里没有“{}”".format(c))
    anyof = [_fill(c, sl) for c in item.get("any_of") or []]
    if anyof and not any(c in ans for c in anyof):
        why.append("回答里没有“{}”中的任何一个".format("、".join(anyof)))
    for c in item.get("not_contains") or []:
        c = _fill(c, sl)
        if c and c in ans:
            why.append("不该说出“{}”".format(c))
    drafted = bool(r.get("actions"))
    if item.get("drafts") and not drafted:
        why.append("应该起草动作草稿")
    if not item.get("drafts") and drafted:
        why.append("不该起草动作")
    chk = r.get("check") or {}
    if item.get("cite", True):
        if not re.search(r"\[\d{1,3}\]", ans):
            why.append("没有引用 [n]")
    if chk.get("bad_refs"):
        why.append("引用编号无效：{}".format(chk["bad_refs"]))
    if item.get("verified", True) and chk.get("unverified"):
        why.append("数字未经核实：{}".format("、".join(n for u in chk["unverified"] for n in u["numbers"])[:80]))
    return why


def run(agent, db, items=None, mode="teach", engine=None, started_by=None, record_db=None):
    """逐题问代理。agent：hub.ont.agent.Agent（它的数据就是 db）；record_db：存档用的库（默认 db）。返回 {passed, total, results}"""
    items = items if items is not None else load()
    sl = slots(db, mode)
    rec = record_db or db
    init(rec)
    rid = rec.one("insert into ai_eval_run (mode, engine, git_sha, started_by) values (%s,%s,%s,%s) returning id",
                (mode, engine or "rules", _sha(), started_by))["id"]
    results = []
    for it in items:
        u = dict(AS[it.get("as", "teacher")])
        if u["mode"] != mode and it.get("as") != "prod_manager":
            u["mode"] = mode
        q = _fill(it["q"], sl)
        try:
            r = agent.ask(u, [{"role": "user", "content": q}], kind="eval")
            why = grade(it, r, sl)
        except Exception as e:  # noqa: BLE001
            r, why = {"answer": "", "tools": []}, ["出错：{}".format(type(e).__name__)]
        results.append({"id": it["id"], "domain": it["domain"], "q": q, "as": it.get("as", "teacher"), "ok": not why, "why": why,
                        "answer": (r.get("answer") or "")[:800], "tools": r.get("tools"), "run_id": r.get("run_id")})
    passed = sum(1 for x in results if x["ok"])
    rec.x("update ai_eval_run set finished_at=now(), passed=%s, total=%s, results=%s where id=%s",
          (passed, len(results), Jsonb(results), rid))
    return {"id": rid, "passed": passed, "total": len(results), "results": results, "slots": sl}


class EngineSnaps:
    """评测沙盒里的“快照”：直接从内存里的仿真引擎拍精确快照"""

    def __init__(self, db, eng):
        self.db, self.eng = db, eng

    def take(self, mode, timeout=5.0):
        st = json.loads(json.dumps(self.eng.snapshot()))
        r = self.db.one("insert into sim_snapshot (mode, ts, exact, state) values (%s, now(), true, %s) returning id", (mode, Jsonb(st)))
        return r["id"], st, True


def sandbox(dsn, name="wq_eval_sandbox", llm=None, now=None):
    """在一个临时数据库里载入实验 7 情景（与测试同一套），返回 (H, 引擎)。评测不碰正在用的工厂数据。"""
    import datetime as dt
    import types

    import psycopg

    import wqbus
    from hub.ai import Assistant
    from hub.db import DB
    from hub.historian import Historian
    from hub.ont import actions as AC
    from hub.ont import agent as AG
    from hub.ont import plan as P
    from hub.ont.store import Store
    from hub.ont.sync import Sync
    from sim import scenario
    from sim.engine import Engine
    base = dsn.rsplit("/", 1)[0]
    with psycopg.connect(base + "/postgres", autocommit=True) as c:
        c.execute("drop database if exists {} with (force)".format(name))
        c.execute("create database {}".format(name))
    db = DB(base + "/" + name)
    db.init()
    P.init(db)
    AC.init(db)
    AG.init(db)
    init(db)
    h = Historian(db)

    class _Clock:
        t = 0.0

        def now(self):
            return self.t
    clock = _Clock()
    eng = Engine(lambda *a: None, clock, mode="teach", auto_start=False, seed=1, status_every_s=1e9)
    now = now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    clock.t = scenario.load(eng, lambda tp, ty, src, data, corr, ts: h.handle(tp, wqbus.make(ty, src, data, corr=corr, ts=ts)), now=now)
    s = Sync(db, Store(db))
    s.init()
    s.replay()
    ai = Assistant(db, lambda *a: None, llm)
    H = types.SimpleNamespace(db=db, ai=ai, plan_snaps=EngineSnaps(db, eng), mes=None)
    H.twin = field_scene(H, h)
    ehs_scene(H)
    from hub import maint as MT                 # 第 18 轮 E3：点检表（磨床保养逾期来自情景里的运行小时）
    MT.seed(db, "teach")
    from hub import people as PE                 # 第 18 轮 E4：30 人、技能矩阵、固定岗位
    PE.seed(db, "teach")
    PE.leave_next_shift(H, "teach", "P01", "评测·情景")    # 王强下一个班请假：磨床那一班没人（H2）
    supply_scene(H)                              # 第 18 轮 E5：一批不合格的轴承（W3）
    from hub import energy as EG                 # 第 18 轮 E6：过去 24 小时的计量读数（忘关、峰时开炉、磨床劣化、漏气）
    EG.energy_scene(H, eng)
    from hub import finance as FN                # 第 18 轮 E7：目标、预算、信用、期初应收（峰顶搅拌机那笔逾期 5 天）
    FN.seed(db, "teach", now)
    s.reconcile()
    ai.detector().run("teach", now)
    return H, eng


def supply_scene(H, mode="teach"):
    """第 18 轮 E5：向五大湖轴承下一批 BRG-6207 × 40，到货抽检不合格（沙盘里没有桥接：采购单号直接填）"""
    from factory import data as F
    from hub import supply as SP
    SP.seed(H.db, mode)
    if H.db.one("select 1 as x from lot where mode=%s limit 1", (mode,)):
        return
    r = SP.place_po(H, mode, F.SUPPLIERS["bearings"]["name"], [{"item_code": "BRG-6207", "qty": 40}], "评测·情景")
    lid = r["lots"][0]
    H.db.x("update lot set po='PUR-ORD-EVAL-0001', lot=%s, status='transit', truth_bad=true, due_at=now() where id=%s", ("L261001-{:04d}".format(lid), lid))
    SP.arrive(H.db, mode, lid, "评测·情景")
    SP.inspect(H, mode, lid, False, "评测·情景")


def ehs_scene(H, mode="teach"):
    """第 18 轮 E2：员工、培训、危险源；磨床一条重大隐患；孙磊（受限空间培训已过期）申请热处理炉受限空间作业"""
    from hub import ehs as EH
    EH.seed(H.db, mode)
    if not H.db.one("select 1 as x from safety_issue where mode=%s limit 1", (mode,)):
        EH.inject_major(H, mode, "grd-01", "guard", "评测·情景")
        EH.request_permit(H.db, mode, {"kind": "confined", "unit": "ht-01", "holder_id": "P07", "reason": "炉膛检修"}, "评测·情景")


def field_scene(H, hist, mode="teach"):
    """第 18 轮 E1：客户现场的 12 台情景设备，加一条投诉（轴承报警那台），客户与服务的评测题用"""
    import wqbus
    from hub import service as SV
    from hub import twin as TW
    tw = TW.TwinService(H.db, lambda tp, ty, src, data, corr=None, mode=None: hist.handle(tp, wqbus.make(ty, src, data, mode=mode or "teach", corr=corr)))
    tw.init()
    tw.seed(mode)
    SV.init(H.db)
    SV.seed_engineers(H.db, mode)
    us = SV.units(H.db, mode)
    bad = sorted(us.values(), key=lambda x: (-x["risk"], x["serial"]))
    bad = next((x for x in bad if "bearing" in (x.get("alert_kinds") or [])), bad[0] if bad else None)
    if bad and not H.db.one("select 1 as x from complaint where mode=%s limit 1", (mode,)):
        SV.create_complaint(H, mode, {"serial": bad["serial"], "subject": "运转时有异响，轴承位置发热", "severity": "serious", "channel": "电话"},
                            "评测·情景")
    return tw



def history(db, limit=20):
    init(db)
    rows = db.q("select id, mode, engine, started_at, finished_at, passed, total, git_sha, started_by from ai_eval_run order by id desc limit %s",
                (limit,))
    return [dict(r, started_at=r["started_at"].isoformat(), finished_at=r["finished_at"].isoformat() if r["finished_at"] else None)
            for r in rows]


def _sha():
    sha = os.environ.get("WQ_GIT_SHA")
    if sha:
        return sha[:12]
    try:
        return subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=3,
                              cwd=os.path.dirname(__file__)).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def summary(res):
    by = {}
    for x in res["results"]:
        d = by.setdefault(x["domain"], [0, 0])
        d[0] += 1 if x["ok"] else 0
        d[1] += 1
    return {k: "{}/{}".format(*v) for k, v in by.items()}


def to_json(res):
    return json.dumps(res, ensure_ascii=False, default=str)

