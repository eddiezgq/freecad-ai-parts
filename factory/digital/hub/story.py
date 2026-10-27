# -*- coding: utf-8 -*-
"""全厂联调情景（第 19 轮 J-1 ~ J-5）：读剧本（ontology/scenarios/*.yaml），按幕执行注入，核对厂情中枢该出的异常有没有出来。

- 剧本日只是标签（J-2）：点“下一幕”立即注入；车间按设定的倍速照常跑，账期照旧。
- 注入复用各领域现成的函数（下单与算料、采购、来料检验、请假、隐患、保养逾期、能源问题、财务）。
- 后果连上（J-4）：情景的订单只有一张；每一幕的异常记在 story_beat.seen 里，经营与财务算毛利时，
  因这些异常采纳的动作费用记到这张订单上（finance.margin 调 anomalies_for_so）；第 8 幕逾期的就是这张订单的发票。
- 只在教学模式；只有老师能开始、执行、自动演示。后台每 20 秒 tick 一次：推进要等 ERPNext 的步骤、核对异常、自动演示。"""
import datetime as dt
import glob
import json
import logging
import os
import time

import yaml
from psycopg.types.json import Jsonb

log = logging.getLogger("story")
MODE = "teach"
HERE = os.path.dirname(os.path.abspath(__file__))
SCEN_DIR = os.path.join(os.path.dirname(HERE), "ontology", "scenarios")

SCHEMA = """
create table if not exists story_run (
    id          bigserial primary key,
    mode        text not null,
    scenario    text not null,
    started_by  text,
    started_at  timestamptz not null default now(),
    auto        boolean not null default false,
    beat_no     int not null default 0,
    status      text not null default 'loading',      -- loading 载入情景 / ready 可以演 / ended 结束
    so          text,
    ended_at    timestamptz,
    state       jsonb not null default '{}'::jsonb
);
create table if not exists story_beat (
    run_id      bigint not null,
    beat_no     int not null,
    executed_at timestamptz not null default now(),
    by          text,
    injected    jsonb not null default '{}'::jsonb,
    expect      jsonb not null default '[]'::jsonb,
    seen        jsonb not null default '[]'::jsonb,
    ok          boolean not null default false,
    pending     jsonb not null default '[]'::jsonb,
    note        text,
    primary key (run_id, beat_no)
);
"""

STEP_NAME = {"order": "下急单", "purchase": "下采购单", "arrive_reject": "到货检验不合格", "leave": "请假", "hazard": "重大隐患",
             "overdue": "保养逾期", "energy": "空转与峰时", "overdue_invoice": "发票逾期"}
DOMAIN_NAME = {"customer": "客户与服务", "supply": "采购与来料", "people": "人员", "ehs": "安全环保", "maintenance": "设备维护",
               "energy": "能源与环境", "finance": "经营与财务", "production": "生产"}


def init(db):
    db.x(SCHEMA)


# ---------------------------------------------------------------- 剧本
def scenarios():
    out = {}
    for f in sorted(glob.glob(os.path.join(SCEN_DIR, "*.yaml"))):
        with open(f, encoding="utf-8") as fh:
            d = yaml.safe_load(fh)
        out[d["code"]] = d
    return out


def scenario(code="two_weeks"):
    s = scenarios().get(code)
    if s is None:
        raise KeyError("没有这个剧本：{}".format(code))
    return s


def beat_of(sc, n):
    return next((b for b in sc["beats"] if b["n"] == n), None)


# ---------------------------------------------------------------- 运行记录
def run(db, mode=MODE, run_id=None):
    if run_id:
        return db.one("select * from story_run where id=%s", (run_id,))
    return db.one("select * from story_run where mode=%s and status <> 'ended' order by id desc limit 1", (mode,))


def last_run(db, mode=MODE):
    return db.one("select * from story_run where mode=%s order by id desc limit 1", (mode,))


def beats(db, run_id):
    return {r["beat_no"]: r for r in db.q("select * from story_beat where run_id=%s order by beat_no", (run_id,))}


def _patch(db, run_id, d):
    db.x("update story_run set state = state || %s where id=%s", (Jsonb(d), run_id))


def anomalies_for_so(db, mode, so):
    """这张订单是哪次情景的主线：那次情景各幕等到的异常编号（经营与财务算毛利时，因这些异常采纳的动作费用记到这张订单上）"""
    try:
        if not db.one("select to_regclass('story_run') is not null as ok")["ok"]:
            return set()
        out = set()
        for r in db.q("select b.seen from story_beat b join story_run r on r.id=b.run_id where r.mode=%s and r.so=%s", (mode, so)):
            for x in r["seen"] or []:
                out.add(int(x["id"]))
        return out
    except Exception:  # noqa: BLE001
        return set()


def story_anomalies(db, mode):
    """所有情景各幕等到的异常 → 那次情景的主线订单（经营与财务：这些异常采纳的动作，费用全记主线订单）"""
    try:
        if not db.one("select to_regclass('story_run') is not null as ok")["ok"]:
            return {}
        out = {}
        for r in db.q("select r.so, b.seen from story_beat b join story_run r on r.id=b.run_id where r.mode=%s and r.so is not null order by r.id", (mode,)):
            for x in r["seen"] or []:
                if x.get("id"):
                    out[int(x["id"])] = r["so"]
        return out
    except Exception:  # noqa: BLE001
        return {}


def so_of_anomaly(db, mode, anomaly_id):
    """反过来：这个异常是哪次情景、哪一幕等到的，主线订单是哪张"""
    try:
        if not db.one("select to_regclass('story_run') is not null as ok")["ok"]:
            return None
        for r in db.q("select r.so, b.beat_no, b.seen from story_beat b join story_run r on r.id=b.run_id where r.mode=%s and r.so is not null "
                      "order by r.id desc", (mode,)):
            if any(int(x["id"]) == int(anomaly_id) for x in r["seen"] or []):
                return {"so": r["so"], "beat": r["beat_no"]}
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------- 开始、执行、自动
def start(H, who, code="two_weeks", speed=None, auto=False, reset=None, wrapup=True):
    """重置到实验 7 起点，建一条运行记录。reset：app 里的 reset_teach（测试可以不给）"""
    db = H.db
    init(db)
    sc = scenario(code)
    db.x("update story_run set status='ended', ended_at=now() where mode=%s and status <> 'ended'", (MODE,))
    sp = float(speed or sc.get("speed") or 30)
    if reset is not None:
        reset(who, 1.0, False)
    r = db.one("insert into story_run (mode, scenario, started_by, auto, status, state) values (%s,%s,%s,%s,%s,%s) returning id",
               (MODE, code, who, bool(auto), "loading" if reset is not None else "ready", Jsonb({"speed": sp, "dwell_s": sc.get("dwell_s", 90), "wrapup": bool(wrapup)})))
    if reset is None:
        _ready(H, r["id"], sp)
    return state(db)


def _ready(H, run_id, speed):
    db = H.db
    db.x("update story_run set status='ready' where id=%s", (run_id,))
    _patch(db, run_id, {"ready_at": _now().isoformat()})
    mes = getattr(H, "mes", None)
    if mes is not None:
        mes.command("sim", "set_speed", MODE, "情景导演", speed=float(speed))
        mes.command("grd-01", "reset", MODE, "情景导演")          # 实验 7 情景里磨床在换砂轮：两周情景从开着的车间开始


def set_auto(db, on, dwell_s=None):
    r = run(db)
    if r is None:
        raise ValueError("还没有开始情景")
    db.x("update story_run set auto=%s where id=%s", (bool(on), r["id"]))
    if dwell_s:
        _patch(db, r["id"], {"dwell_s": max(10, int(dwell_s))})
    return state(db)


def fast_forward(H, on=True, speed=None):
    """快进到这张订单做完（第 8 幕要等它）：车间临时提到 speed 倍，做完自动回到原来的倍速"""
    db = H.db
    r = run(db)
    if r is None:
        raise ValueError("还没有开始情景")
    st = r["state"] or {}
    base = float(st.get("speed") or 30)
    sp = float(speed or st.get("ff_speed") or 300)
    mes = getattr(H, "mes", None)
    if on:
        _patch(db, r["id"], {"ff": True, "ff_speed": sp})
        if mes is not None:
            mes.command("sim", "set_speed", MODE, "情景导演", speed=sp)
    else:
        _patch(db, r["id"], {"ff": False})
        if mes is not None:
            mes.command("sim", "set_speed", MODE, "情景导演", speed=base)
    return state(db)


def end(db, who, mes=None):
    r = run(db)
    if r is None:
        raise ValueError("还没有开始情景")
    db.x("update story_run set status='ended', ended_at=now(), auto=false where id=%s", (r["id"],))
    _patch(db, r["id"], {"ended_by": who})
    return state(db)


def can_next(H, r, sc):
    """下一幕能不能演：返回 (能, 为什么不能)"""
    if r["status"] == "loading":
        return False, "车间正在载入实验 7 情景"
    n = r["beat_no"] + 1
    b = beat_of(sc, n)
    if b is None:
        return False, "八幕都演完了，可以复盘"
    if r["beat_no"] >= 1 and not r["so"]:
        return False, "等订单写进 ERPNext"
    if b.get("wait") == "order_done":
        p = order_progress(H.db, r)
        if not p.get("done"):
            return False, "等车间做完这张订单（{} / {} 根）".format(p.get("parts", 0), p.get("qty", "?"))
    return True, ""


def next_beat(H, who, n=None):
    db = H.db
    r = run(db)
    if r is None:
        raise ValueError("还没有开始情景")
    sc = scenario(r["scenario"])
    if n is not None and int(n) != r["beat_no"] + 1:
        if int(n) <= r["beat_no"]:
            raise ValueError("第 {} 幕已经演过了".format(n))
        raise ValueError("一幕一幕来：下一幕是第 {} 幕".format(r["beat_no"] + 1))
    ok, why = can_next(H, r, sc)
    if not ok:
        raise ValueError(why)
    n = r["beat_no"] + 1
    b = beat_of(sc, n)
    injected, pending, notes = {}, [], []
    for st in b.get("do") or []:
        fn = STEPS.get(st["step"])
        if fn is None:
            raise ValueError("剧本里有不认识的步骤：{}".format(st["step"]))
        res = fn(H, r, sc, st, who) or {}
        injected[st["step"]] = res
        if res.get("pending"):
            pending.append(dict(step=st["step"], **res["pending"]))
        if res.get("text"):
            notes.append(res["text"])
    db.x("insert into story_beat (run_id, beat_no, by, injected, expect, pending, note) values (%s,%s,%s,%s,%s,%s,%s) "
         "on conflict (run_id, beat_no) do update set executed_at=now(), by=excluded.by, injected=excluded.injected, expect=excluded.expect, "
         "pending=excluded.pending, note=excluded.note, seen='[]'::jsonb, ok=false",
         (r["id"], n, who, Jsonb(injected), Jsonb(b.get("expect") or []), Jsonb(pending), "；".join(notes)[:900]))
    db.x("update story_run set beat_no=%s where id=%s", (n, r["id"]))
    _patch(db, r["id"], {"last_beat_at": _now().isoformat()})
    try:
        tick(H)
    except Exception:  # noqa: BLE001
        log.exception("情景推进")
    return state(db)


# ---------------------------------------------------------------- 各步骤
def _now():
    return dt.datetime.now(dt.timezone.utc)


def _step_order(H, r, sc, st, who):
    """第 1 幕：计划员接单算料 → 提议（教学模式自动确认）→ 桥接写 ERPNext；订单回来以后 tick 下达车间"""
    from hub import mrp
    from hub.ai import _order_title
    db = H.db
    due = (dt.date.today() + dt.timedelta(days=int(sc.get("due_days") or 12))).isoformat()
    pv = mrp.plan_order(db, sc["customer"], sc["item"], int(sc["qty"]), due, MODE)
    pv["story"] = {"run_id": r["id"], "scenario": sc["code"]}
    title = "情景：" + _order_title(pv)
    pid = H.ai.propose("create_order_and_plan", pv, MODE, who, title, source="story", role="planner")
    H.ai.decide(pid, who, True, role="planner")
    _patch(db, r["id"], {"order_pid": pid, "qty": int(sc["qty"]), "due": due})
    need = next((x for x in pv["mrp"] if x["item_code"] == "BRG-6207"), None)
    text = "{} 下单 {} × {}，交期 {}".format(sc["customer"].split(" ")[0], sc["item"], sc["qty"], due)
    if need:
        text += "；轴承 BRG-6207 要 {:g} 个，库存 {:g}".format(need["gross"], need["stock"])
    return {"proposal_id": pid, "text": text, "pending": {"what": "等 ERPNext 建好订单和工单，再下达车间", "pid": pid}}


def _progress_order(H, r, p):
    from hub import finance as FN
    db = H.db
    pid = p["pid"]
    pr = FN._proposal(db, pid)
    if not pr or pr["status"] in ("pending", "confirmed"):
        return None
    if pr["status"] != "executed":
        return {"failed": "订单没写进 ERPNext：{}".format(json.dumps(pr.get("result"), ensure_ascii=False)[:200])}
    so = FN._erp_name(db, pid, "Sales Order")
    wo = FN._erp_name(db, pid, "Work Order")
    if not so or not wo:
        return {"failed": "ERPNext 没返回订单或工单"}
    db.x("update story_run set so=%s where id=%s", (so, r["id"]))
    _patch(db, r["id"], {"wo": wo})
    sent = H.mes.release(wo, MODE, "情景导演")
    time.sleep(0.5)
    for d in sent:
        H.mes.command(d["unit"], "start", MODE, "情景导演", wo, d["operation"])
    return {"done": "订单 {}，工单 {} 已下达车间（{} 道工序）".format(so, wo, len(sent))}


def _step_purchase(H, r, sc, st, who):
    """第 2 幕：向常用供应商下采购单（这一批到货时不合格，第 3 幕揭晓）"""
    from factory import data as F
    from hub import supply as SP
    db = H.db
    sup = F.SUPPLIERS[st.get("supplier") or "bearings"]["name"]
    SP.set_enabled(db, MODE, True)
    res = SP.inject(H, MODE, sup, who, bad=bool(st.get("bad", True)), item=st.get("item") or "BRG-6207", qty=st.get("qty") or 50)
    lid = res.get("lot_id")
    _patch(db, r["id"], {"lot_id": lid})
    return {"lot_id": lid, "text": "向 {} 下采购单 {} × {:g}".format(sup.split(" ")[0], st.get("item") or "BRG-6207", float(st.get("qty") or 50)),
            "pending": {"what": "等采购单进 ERPNext、供应商发货", "lot_id": lid}}


def _progress_purchase(H, r, p):
    db = H.db
    x = db.one("select status, po from lot where id=%s", (p["lot_id"],))
    if not x:
        return {"failed": "找不到这一批"}
    if x["status"] in ("transit", "arrived", "rejected", "accepted", "returned"):
        return {"done": "采购单 {} 已进 ERPNext，在途".format(x["po"] or "")}
    return None


def _step_arrive_reject(H, r, sc, st, who):
    """第 3 幕：这一批到货、来料检验判不合格（抽样里有超差件）"""
    from hub import supply as SP
    db = H.db
    lid = (r["state"] or {}).get("lot_id")
    if not lid:
        raise ValueError("第 2 幕的采购单还没下")
    x = db.one("select status from lot where id=%s", (lid,))
    if x["status"] == "ordered":
        raise ValueError("采购单还没进 ERPNext（稍等十几秒再演这一幕）")
    if x["status"] == "transit":
        SP.arrive(db, MODE, lid, "仓管员（情景）")
    x = db.one("select status from lot where id=%s", (lid,))
    if x["status"] == "arrived":
        sm = SP.sample(db, MODE, lid)
        bad = SP.judge(sm)
        res = SP.inspect(H, MODE, lid, False, "来料检验员（情景）", "抽样 {} 件，{} 处超差".format(sm["sample_size"], len(bad)))
        return {"lot_id": lid, "proposal_id": res.get("proposal_id"), "text": "到货抽检 {} 件，{} 处超差，整批判不合格".format(sm["sample_size"], len(bad))}
    return {"lot_id": lid, "text": "这一批现在：{}".format(x["status"])}


def _step_leave(H, r, sc, st, who):
    """第 4 幕：这台设备下个班的人请假（打开“要有人”）。
    从下一个班开始找（不用现在这一班）：情景里车间倍速运行，现在这一班可能真实时间几秒后就结束，
    厂情中枢每 20 秒才检测一次，缺口还没被看到就过去了，这一幕就等不到（2026-10-18 部署演练夜里跑时卡在这里）"""
    from hub import people as PE
    from sim import staffing as STF
    db = H.db
    unit = st.get("unit") or "grd-01"
    PE.set_enabled(H, MODE, True, who)
    d, sh = PE.now_shift(db=db, mode=MODE)
    emp = None
    for _ in range(3):
        d, sh = STF.shift_of(STF.next_change(STF.shift_start(d, sh, PE.tz())))
        ro = PE.roster_for(db, MODE, d, sh)
        emp = (ro.get(unit) or {}).get("emp_id")
        if emp:
            break
    if not emp:
        raise ValueError("{} 最近没有排班".format(unit.upper()))
    p = PE.person(db, MODE, emp)
    d, sh, units = PE.leave_next_shift(H, MODE, emp, who, now=STF.shift_start(d, sh, PE.tz()) + dt.timedelta(minutes=1))
    return {"emp_id": emp, "text": "{} {} {} 请假（{} 这一班没人）".format(p["name"], d.isoformat(), PE.SHIFT_NAME[sh], "、".join(u.upper() for u in units))}


def _step_hazard(H, r, sc, st, who):
    from hub import ehs as EH
    iid = EH.inject_major(H, MODE, st.get("unit") or "grd-01", st.get("kind") or "guard", who)
    return {"issue_id": iid, "text": "巡检报重大隐患 SI-{:05d}：{} 防护门联锁被短接".format(iid, (st.get("unit") or "grd-01").upper())}


def _step_overdue(H, r, sc, st, who):
    from sim import reliability as REL
    from hub import maint as MT
    unit = st.get("unit") or "grd-01"
    rp = REL.params(unit)
    hours = round(rp["pm_h"] * float(st.get("over") or 1.4))
    res = MT.inject_overdue(H, MODE, unit, hours, who)
    return {"hours": hours, "text": res.get("text")}


def _step_energy(H, r, sc, st, who):
    from hub import energy as EN
    db = H.db
    unit = st.get("unit") or "grd-01"
    EN.set_sim(db, MODE, True)
    out = [EN.inject(H, MODE, "forgot", who, unit=unit, hours=float(st.get("hours") or 24))["text"]]
    keys = ["forgot:" + unit]
    if st.get("peak"):
        out.append(EN.inject(H, MODE, "ht_peak", who)["text"])
        keys.append("ht_peak")
    s = EN._state(db, MODE)
    for k in keys:
        if k in (s.get("faults") or {}):
            EN._patch_in(db, MODE, "faults", k, dict(s["faults"][k], lab=True))       # 情景里的问题不让模拟器自动“修好”
    return {"text": "；".join(out)}


def _step_overdue_invoice(H, r, sc, st, who):
    """第 8 幕：这张订单的发票（订单做完时已开出）逾期 N 天，不催就不付"""
    from hub import finance as FN
    db = H.db
    so = r["so"]
    x = db.one("select * from invoice where mode=%s and kind='ar' and ref=%s and status <> 'failed' order by id desc limit 1", (MODE, so))
    if x is None:
        FN.tick(H, MODE)                            # 订单刚做完，还没轮到开票：现在开
        x = db.one("select * from invoice where mode=%s and kind='ar' and ref=%s and status <> 'failed' order by id desc limit 1", (MODE, so))
    if x is None:
        raise ValueError("订单 {} 还没开票（客户被信用冻结时要厂长放行）".format(so))
    FN.set_sim(db, MODE, True)
    res = FN.make_overdue(H, MODE, x["id"], float(st.get("days") or 15), who)
    _patch(db, r["id"], {"invoice_id": x["id"]})
    return dict(res, pending={"what": "等 ERPNext 销售发票", "invoice_id": x["id"]})


def _progress_overdue_invoice(H, r, p):
    x = H.db.one("select doc, status from invoice where id=%s", (p["invoice_id"],))
    if x and x["doc"]:
        return {"done": "ERPNext 销售发票 {}".format(x["doc"])}
    if x and x["status"] == "failed":
        return {"failed": "开票没写进 ERPNext"}
    return None


STEPS = {"order": _step_order, "purchase": _step_purchase, "arrive_reject": _step_arrive_reject, "leave": _step_leave,
         "hazard": _step_hazard, "overdue": _step_overdue, "energy": _step_energy, "overdue_invoice": _step_overdue_invoice}
PROGRESS = {"order": _progress_order, "purchase": _progress_purchase, "overdue_invoice": _progress_overdue_invoice}


# ---------------------------------------------------------------- 核对异常
def _match(a, about, sc):
    if not about:
        return True
    if about == "customer":
        about = sc["customer"]
    v = json.dumps(a.get("detail") or {}, ensure_ascii=False)
    hay = " ".join(str(x or "") for x in (a["fkey"], a["subject_key"], a["title"], v)).lower()
    return str(about).lower() in hay


def _seen(db, r, sc, b, row):
    """这一幕预计的异常：情景开始以后出现过的（开着或已处理的都算）。
    同一件事（同一规则、同一键，例如“10-18 晚班 GRD-01 没人”）情景开始前就开着、或 24 小时内关过又被重新打开时，
    first_seen 是以前的；只要情景开始后规则又看到了它（last_seen 在情景开始后）也算——不然这一幕会一直等不到
    （2026-10-18 数字工厂部署演练：前面的“人员与排班”实验刚让同一个人同一班请过假，第 4 幕随钟点时过时不过）"""
    out = []
    since = r["started_at"]
    for e in b.get("expect") or []:
        if e.get("rule"):
            cands = db.q("select id, rule, fkey, subject_key, title, detail, status, first_seen, last_seen, severity from anomaly "
                         "where mode=%s and rule=%s and (first_seen >= %s or last_seen >= %s) order by id", (MODE, e["rule"], since, since))
            hit = next((a for a in cands if _match(a, e.get("about"), sc)), None)
            if hit:
                t = hit["first_seen"] if hit["first_seen"] >= since else hit["last_seen"]
                out.append({"id": hit["id"], "rule": hit["rule"], "title": hit["title"], "status": hit["status"], "severity": hit["severity"],
                            "first_seen": t.isoformat(), "after_s": round((t - row["executed_at"]).total_seconds())})
        elif e.get("check") == "order_released":
            if r["so"] and (r["state"] or {}).get("wo"):
                out.append({"check": "order_released", "title": "订单 {} 已写进 ERPNext，工单 {} 已下达车间".format(r["so"], r["state"]["wo"])})
    return out


def tick(H, mode=MODE):
    """后台每 20 秒：载入完成 → 设倍速；推进要等的步骤；核对异常；自动演示"""
    if mode != MODE:
        return None
    db = H.db
    init(db)
    r = run(db)
    if r is None:
        return None
    sc = scenario(r["scenario"])
    if r["status"] == "loading":
        loaded = db.one("select 1 as x from bus_message where mode=%s and type='erp.doc' and received_at >= %s limit 1", (MODE, r["started_at"]))
        if not loaded:
            return None
        _ready(H, r["id"], (r["state"] or {}).get("speed") or sc.get("speed") or 30)
        r = run(db)
    for n, row in beats(db, r["id"]).items():
        pend = list(row["pending"] or [])
        changed = False
        for p in list(pend):
            fn = PROGRESS.get(p["step"])
            if fn is None:
                pend.remove(p)
                changed = True
                continue
            res = fn(H, r, p)
            if res:
                pend.remove(p)
                changed = True
                note = (row["note"] or "") + "；" + (res.get("done") or "失败：" + res.get("failed", ""))
                db.x("update story_beat set note=%s where run_id=%s and beat_no=%s", (note.strip("；")[:900], r["id"], n))
                r = run(db, run_id=r["id"])
        if changed:
            db.x("update story_beat set pending=%s where run_id=%s and beat_no=%s", (Jsonb(pend), r["id"], n))
        b = beat_of(sc, n)
        seen = _seen(db, r, sc, b, row)
        ok = len(seen) >= len(b.get("expect") or []) and not pend
        if seen != (row["seen"] or []) or ok != row["ok"]:
            db.x("update story_beat set seen=%s, ok=%s where run_id=%s and beat_no=%s", (Jsonb(seen), ok, r["id"], n))
    r = run(db, run_id=r["id"])
    try:
        _wrapup(H, r)
    except Exception:  # noqa: BLE001
        log.exception("情景收尾")
    r = run(db, run_id=r["id"])
    st = r["state"] or {}
    if st.get("ff") and order_progress(db, r).get("done"):          # 快进到做完了：回到原来的倍速
        fast_forward(H, False)
        r = run(db, run_id=r["id"])
    if r["auto"] and r["status"] == "ready":
        nb = beat_of(sc, r["beat_no"] + 1)
        if nb and nb.get("wait") == "order_done" and not st.get("ff") and not order_progress(db, r).get("done") \
                and (beats(db, r["id"]).get(r["beat_no"]) or {}).get("ok"):
            fast_forward(H, True)                                    # 自动演示：下一幕要等订单做完，就快进
            r = run(db, run_id=r["id"])
        bs = beats(db, r["id"])
        cur = bs.get(r["beat_no"])
        dwell = float((r["state"] or {}).get("dwell_s") or sc.get("dwell_s") or 90)
        timeout = float(sc.get("timeout_s") or 240)
        ready = cur is None or (cur["ok"] and (_now() - cur["executed_at"]).total_seconds() >= dwell) or \
            (_now() - cur["executed_at"]).total_seconds() >= timeout + dwell
        if ready and can_next(H, r, sc)[0]:
            try:
                next_beat(H, "自动演示")
            except ValueError as e:
                log.info("自动演示等待：%s", e)
    return state(db)


# ---------------------------------------------------------------- 收尾（演示用：替学生把整改验收、保养完工做了，设备才会解锁）
WRAP_WHO = {"fix": "维修工（情景）", "verify": "安全员（情景）", "pm": "维修工（情景）", "pm_verify": "班组长（情景）"}


def _wrapup(H, r):
    """停机挂牌整改、保养到了预计时长（工厂时间）还没人收尾，就由“情景里的人”整改验收 / 保养完工验收，设备解锁。
    课堂上想让学生自己收尾，开始情景时把“自动收尾”关掉（state.wrapup = false）"""
    from hub import ehs as EH
    from hub import maint as MT
    from hub import people as PE
    db = H.db
    st = r["state"] or {}
    if st.get("wrapup") is False:
        return []
    seen = dict(st.get("wrap_seen") or {})
    now_f = PE.factory_now(db, MODE)
    done = []

    def due(key, minutes):
        if key not in seen:
            seen[key] = now_f.isoformat()
            return False
        return (now_f - dt.datetime.fromisoformat(seen[key])).total_seconds() >= float(minutes or 0) * 60

    for p in db.q("select * from work_permit where mode=%s and kind='loto' and status='active' and created_at >= %s", (MODE, r["started_at"])):
        key = "permit:{}".format(p["id"])
        if not due(key, (p["minutes"] or 60) + (p["delay_minutes"] or 0)):
            continue
        try:
            if p["issue_id"]:
                iss = db.one("select status from safety_issue where id=%s", (p["issue_id"],))
                if iss and iss["status"] not in ("fixed", "closed"):
                    EH.fix(db, p["issue_id"], WRAP_WHO["fix"], "装回防护门、恢复联锁（情景收尾）")
                EH.verify(H, MODE, p["issue_id"], WRAP_WHO["verify"])
                done.append("隐患 SI-{:05d} 整改验收，{} 解锁".format(p["issue_id"], (p["unit"] or "").upper()))
                continue
            pm = db.one("select * from maint_pm where mode=%s and permit_id=%s", (MODE, p["id"]))
            if pm:
                if pm["status"] not in ("fixed", "closed"):
                    MT.finish_pm(H, MODE, pm["id"], WRAP_WHO["pm"], "情景收尾")
                MT.verify_pm(H, MODE, pm["id"], WRAP_WHO["pm_verify"])
                done.append("保养 PM-{:05d} 完工验收，{} 解锁".format(pm["id"], (p["unit"] or "").upper()))
        except (ValueError, PermissionError, KeyError) as e:
            log.info("情景收尾 %s：%s", key, e)
    if seen != (st.get("wrap_seen") or {}):
        _patch(db, r["id"], {"wrap_seen": seen})
    if done:
        _patch(db, r["id"], {"wrap_log": (st.get("wrap_log") or []) + done})
    return done


# ---------------------------------------------------------------- 订单进度
def order_progress(db, r):
    st = r["state"] or {}
    wo = st.get("wo")
    qty = st.get("qty")
    if not wo:
        return {"qty": qty, "parts": 0, "done": False}
    n = db.one("select count(*) as n from bus_message where mode=%s and type='machine.event' and corr=%s "
               "and payload->'data'->>'event'='op_complete' and (payload->'data'->>'last_op')::boolean", (MODE, wo))["n"]
    parts = db.one("select count(*) as n from bus_message where mode=%s and type='machine.event' and corr=%s and payload->'data'->>'event'='cycle_end' "
                   "and (payload->'data'->>'op_index')::int = (payload->'data'->>'n_ops')::int - 1", (MODE, wo))["n"]
    return {"wo": wo, "qty": qty, "parts": int(parts), "done": n > 0}


# ---------------------------------------------------------------- 时间线
def state(db, mode=MODE):
    init(db)
    sc_all = scenarios()
    r = run(db, mode) or last_run(db, mode)
    if r is None:
        sc = sc_all.get("two_weeks") or next(iter(sc_all.values()))
        return {"run": None, "scenario": _sc_head(sc), "beats": [_beat_view(b, None, None) for b in sc["beats"]],
                "scenarios": [_sc_head(s) for s in sc_all.values()]}
    sc = sc_all[r["scenario"]]
    bs = beats(db, r["id"])
    out_beats = []
    for b in sc["beats"]:
        out_beats.append(_beat_view(b, bs.get(b["n"]), r))
    nxt = None
    if r["status"] != "ended":
        from types import SimpleNamespace
        ok, why = can_next(SimpleNamespace(db=db), r, sc)
        nxt = {"n": r["beat_no"] + 1, "ok": ok, "why": why}
    return {"run": {"id": r["id"], "status": r["status"], "beat_no": r["beat_no"], "auto": r["auto"], "so": r["so"],
                    "started_at": r["started_at"].isoformat(), "started_by": r["started_by"], "speed": (r["state"] or {}).get("speed"),
                    "dwell_s": (r["state"] or {}).get("dwell_s"), "ff": bool((r["state"] or {}).get("ff")), "ff_speed": (r["state"] or {}).get("ff_speed"),
                    "wrapup": (r["state"] or {}).get("wrapup") is not False, "wrap_log": (r["state"] or {}).get("wrap_log") or [],
                    "ended_at": r["ended_at"].isoformat() if r["ended_at"] else None},
            "scenario": _sc_head(sc), "beats": out_beats, "next": nxt, "order": order_progress(db, r),
            "scenarios": [_sc_head(s) for s in sc_all.values()]}


def _sc_head(sc):
    return {k: sc.get(k) for k in ("code", "name", "short", "customer", "item", "qty", "due_days", "speed", "dwell_s")} | {"beats": len(sc["beats"])}


def _beat_view(b, row, r):
    v = {"n": b["n"], "day": b["day"], "domain": b["domain"], "domain_name": DOMAIN_NAME.get(b["domain"], b["domain"]), "title": b["title"],
         "story": b["story"], "talk": b.get("talk") or [], "look": b.get("look") or [], "link": b.get("link"), "roles": b.get("roles") or [],
         "expect": [e.get("rule") or e.get("check") for e in b.get("expect") or []], "wait": b.get("wait")}
    if row is None:
        v["status"] = "todo"
        return v
    elapsed = (_now() - row["executed_at"]).total_seconds()
    v.update({"executed_at": row["executed_at"].isoformat(), "by": row["by"], "note": row["note"], "seen": row["seen"] or [],
              "pending": [p.get("what") for p in row["pending"] or []], "elapsed_s": round(elapsed)})
    v["status"] = "ok" if row["ok"] else ("timeout" if elapsed > 240 else "waiting")
    return v


# ---------------------------------------------------------------- 复盘
def review(H, mode=MODE, make_report=False):
    """这张订单的毛利分解（每一项能追到哪一幕）、跨领域因果链、两周的周报"""
    from hub import finance as FN
    db = H.db
    r = run(db, mode) or last_run(db, mode)
    if r is None or not r["so"]:
        raise ValueError("情景还没有订单")
    sc = scenario(r["scenario"])
    bs = beats(db, r["id"])
    try:
        m = FN.margin(db, mode, r["so"], store=False)
    except KeyError:
        m = None
    seen = {}
    for n, row in bs.items():
        for x in row["seen"] or []:
            if x.get("id"):
                seen[int(x["id"])] = n
    acts = []
    if seen:
        for a in db.q("select id, type, title, status, anomaly_id, trial, initiator, approver from action where mode=%s and anomaly_id = any(%s) order by id",
                      (mode, list(seen))):
            acts.append({"id": a["id"], "type": a["type"], "title": a["title"], "status": a["status"], "beat": seen[a["anomaly_id"]],
                         "anomaly_id": a["anomaly_id"], "cost": float((a["trial"] or {}).get("cost_total") or 0), "initiator": a["initiator"],
                         "approver": a["approver"]})
    per_beat = []
    for b in sc["beats"]:
        row = bs.get(b["n"])
        mine = [a for a in acts if a["beat"] == b["n"]]
        per_beat.append({"n": b["n"], "title": b["title"], "domain_name": DOMAIN_NAME.get(b["domain"], b["domain"]),
                         "anomalies": (row["seen"] if row else []) or [], "actions": mine,
                         "cost": round(sum(a["cost"] for a in mine if a["status"] in ("done", "executing")), 2)})
    idle = next((x for x in (m or {}).get("lines", []) if x["key"] == "idle"), None)
    if idle:
        b7 = next((x for x in per_beat if x["n"] == 7), None)
        if b7:
            b7["idle_usd"] = idle["usd"]
    inv = db.one("select * from invoice where mode=%s and kind='ar' and ref=%s and status <> 'failed' order by id desc limit 1", (mode, r["so"]))
    chain = money_chain(db, mode, r["so"], m, per_beat)
    rep = None
    try:                                     # 两周的周报：第一次复盘时生成一份，以后沿用
        from hub.ont import report as RP
        rid = (r["state"] or {}).get("report_id")
        if not rid and make_report:
            g = RP.generate(db, mode, "weekly", by="情景复盘", llm=getattr(getattr(H, "ai", None), "llm", None), notify=False)
            rid = g
            if rid:
                _patch(db, r["id"], {"report_id": rid})
        if rid:
            rep = db.one("select id, kind, text, created_at from report where id=%s", (rid,))
    except Exception:  # noqa: BLE001
        log.exception("情景复盘的周报")
    top = max(per_beat, key=lambda x: x["cost"] + x.get("idle_usd", 0)) if per_beat else None
    return {"run_id": r["id"], "sales_order": r["so"], "customer": sc["customer"], "margin": m, "beats": per_beat, "chain": chain,
            "top_beat": top["n"] if top and (top["cost"] + top.get("idle_usd", 0)) > 0 else None,
            "invoice": {"id": inv["id"], "doc": inv["doc"], "status": inv["status"], "status_name": FN.STATUS.get(inv["status"]), "amount": inv["amount"],
                        "dunned_n": inv.get("dunned_n")} if inv else None,
            "order": order_progress(db, r), "report": {"id": rep["id"], "text": rep["text"], "at": rep["created_at"].isoformat()} if rep else None}


def money_chain(db, mode, so, m, per_beat):
    """跨领域因果链：订单毛利 ← 各项成本 ← 动作 ← 异常（哪一幕）"""
    nodes, edges, summary = [], [], []
    son = "SalesOrder|" + so
    nodes.append({"id": son, "type": "SalesOrder", "key": so, "display": so, "label": "销售订单", "role": "subject",
                  "values": {"毛利率": m and m.get("margin_pct"), "毛利": m and m.get("margin")}})
    for b in per_beat:
        for x in b["anomalies"]:
            if not x.get("id"):
                continue
            an = "Anomaly|A-{:05d}".format(x["id"])
            nodes.append({"id": an, "type": "Anomaly", "key": "A-{:05d}".format(x["id"]), "display": x["title"], "label": "异常",
                          "role": "cause", "domain": b["domain_name"], "values": {"第几幕": b["n"], "规则": x.get("rule")}})
            mine = [a for a in b["actions"] if a["anomaly_id"] == x["id"]]
            for a in mine:
                acn = "Action|{}".format(a["id"])
                nodes.append({"id": acn, "type": "Action", "key": str(a["id"]), "display": a["title"], "label": "动作", "role": "cause",
                              "values": {"费用（$）": a["cost"], "状态": a["status"]}})
                edges.append({"from": an, "to": acn, "label": "采纳", "basis": {"how": "动作的来源异常", "seq": None, "text": None}})
                edges.append({"from": acn, "to": son, "label": "费用记到订单" if a["cost"] else "处理",
                              "basis": {"how": "经营与财务：订单毛利“急单、加班、外协、加急”" if a["cost"] else "这个动作不花钱", "seq": None, "text": None}})
            if not mine:
                edges.append({"from": an, "to": son, "label": "影响", "basis": {"how": "情景第 {} 幕".format(b["n"]), "seq": None, "text": None}})
        if b.get("idle_usd"):
            nodes.append({"id": "CostLine|idle", "type": "CostLine", "key": "idle", "display": "空转电（分摊）", "label": "成本", "role": "cause",
                          "values": {"$": b["idle_usd"]}})
            edges.append({"from": "CostLine|idle", "to": son, "label": "多花", "basis": {"how": "经营与财务：订单毛利“空转电（分摊）”", "seq": None, "text": None}})
    if m:
        summary.append("{} 毛利率 {:.1%}，按标准应是 {:.1%}".format(so, m["margin_pct"] or 0, m["std_margin_pct"] or 0))
        extra = [x for x in m["lines"] if x["key"] in ("actions", "idle", "scrap") and x["usd"] > 0]
        if extra:
            summary.append("多花在：" + "、".join("{} ${:,.0f}".format(x["label"], x["usd"]) for x in extra))
    first = next((b for b in per_beat if any(x.get("id") for x in b["anomalies"])), None)
    if first:
        summary.append("最早的源头：第 {} 幕“{}”".format(first["n"], first["title"]))
    return {"kind": "money", "nodes": nodes, "edges": edges, "summary": summary}
