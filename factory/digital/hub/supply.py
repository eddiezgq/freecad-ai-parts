# -*- coding: utf-8 -*-
"""供应链深化（第 18 轮 E5）：采购单 → 供应商发货 → 到货 → 收货与来料检验 → 批次 → 用到哪些零件 → 供应商评分。

- 采购单、收货单、来料检验以 ERPNext 为准（Purchase Order、Purchase Receipt、Quality Inspection Incoming，E5-1），经桥接写入。
  批号记在收货单的自定义字段 wq_lot 和检验单的备注里；物料不启用 ERPNext 的批次管理（启用后完工入库要逐批指定，牵动已有流程）。
- 平台里一行“批次”（lot）就是一次到货：在途 → 到货 → 合格入库 / 不合格（退货、让步接收）；车间每做一件按先进先出记下用了哪个批次（E5-5）。
- 供应商档案（默认与备选、价格指数、提前期）和教学模拟器的“准时率、合格率”在平台（E5-3、E5-4）。
- 教学模式时间压缩：供应商的 1 天 = 真实 2 分钟（DAY_S），一节课里能看到下单、到货、检验。"""
import datetime as dt
import logging
import random
import zlib

from psycopg.types.json import Jsonb

from factory import data as F

log = logging.getLogger("supply")

SCHEMA = """
create table if not exists supplier_profile (
    mode        text not null,
    supplier    text not null,
    cat         text not null,                    -- 物料类别：castings / forgings / steel / bearings / hardware / lubricant
    role        text not null,                    -- default 默认 / alt 备选
    active      boolean not null default true,
    price_index numeric not null default 1,
    lead_days   integer not null,
    on_time_p   numeric not null,                 -- 教学模拟器：准时的概率
    pass_p      numeric not null,                 -- 教学模拟器：一批来料合格的概率
    primary key (mode, supplier)
);
create table if not exists lot (
    id          bigserial primary key,
    mode        text not null,
    lot         text,
    po          text,
    mr          text,
    proposal_id text,
    supplier    text not null,
    item        text not null,
    qty         numeric not null,
    qty_ok      numeric,
    qty_left    numeric not null default 0,
    rate        numeric,
    status      text not null default 'ordered',  -- ordered 已下单 / transit 在途 / arrived 到货待检 / accepted 合格入库 / rejected 不合格 / returned 已退货 / suspect 可疑（事后发现）
    ordered_at  timestamptz not null default now(),
    promised    date,
    due_at      timestamptz,
    arrived_at  timestamptz,
    received_at timestamptz,
    inspected_by text,
    inspection  jsonb,
    truth_bad   boolean not null default false,   -- 教学模拟器：这批其实有问题（学生看不到）
    late_days   numeric not null default 0,
    concession  boolean not null default false,
    receipt_pid text,
    action_id   bigint,
    note        text
);
create index if not exists lot_mode on lot (mode, status);
create table if not exists batch_use (
    mode        text not null,
    lot         text not null,
    item        text not null,
    part_serial text not null,
    work_order  text,
    unit        text,
    qty         numeric,
    at          timestamptz not null default now()
);
create index if not exists batch_use_lot on batch_use (mode, lot);
create index if not exists batch_use_part on batch_use (mode, part_serial);
create table if not exists supply_sim (
    mode  text primary key,
    state jsonb not null default '{}'
);
"""

# 备选供应商（E5-3）：贵 10–25%、提前期短；油封、润滑油等留单一来源
ALT = {"bearings": ("示例·北方精密轴承 Northern Precision Bearing (Demo)", 1.20, 3),
       "castings": ("示例·华美铸业 Huamei Foundry (Demo)", 1.25, 10),
       "forgings": ("示例·长河锻压 Changhe Forging (Demo)", 1.15, 7),
       "steel": ("示例·湖畔特钢 Lakeside Special Steel (Demo)", 1.10, 3)}
# 教学模拟器：各家默认供应商的准时率、合格率（东岳铸造老是晚；五大湖轴承偶尔有一批不合格）
SIM_P = {"castings": (0.45, 0.97), "forgings": (0.85, 0.97), "steel": (0.95, 1.0), "bearings": (0.9, 0.85), "hardware": (0.95, 0.99),
         "lubricant": (0.95, 1.0)}
ALT_P = (0.95, 0.98)
ALT_ACTIVE = ("bearings", "steel")
CAT_NAME = {"castings": "铸件", "forgings": "锻坯", "steel": "钢材", "bearings": "轴承", "hardware": "标准件与油封", "lubricant": "润滑油"}
DAY_S = 120                # 教学模式：供应商的 1 天 = 真实 2 分钟
ARRIVE_AUTO_S = 180        # 到货 3 分钟没人检验，质检员（模拟器）检验
RETURN_AUTO_S = 600        # 不合格 10 分钟没人处理，采购员（模拟器）退货
MR_AUTO_S = 180            # 请购单 3 分钟没人转，采购员（模拟器）转采购单
CONCESSION_H = 0.05        # 让步接收全检：每件 3 分钟
INSPECT_RATE = 40.0        # 检验工时 $/小时
REJECT_COST = 4.0          # 总拥有成本：每件不合格的处理成本（退货运费、检验、等料）$
LATE_COST = 3.0            # 总拥有成本：每件晚到的损失 $


def tco(price, price_index, on_time, pass_rate):
    """每件的总拥有成本 = 单价 × 价格指数 + (1 − 合格率) × 不合格处理成本 + (1 − 准时率) × 晚到损失"""
    return round(price * price_index + (1 - pass_rate) * REJECT_COST + (1 - on_time) * LATE_COST, 3)
STATUS = {"ordered": "已下单", "transit": "在途", "arrived": "到货待检", "accepted": "合格入库", "rejected": "不合格", "returned": "已退货",
          "suspect": "可疑"}


def init(db):
    if getattr(db, "_supply_ready", False):
        return
    db.x(SCHEMA)
    try:
        db._supply_ready = True
    except AttributeError:
        pass


def cat_of(item):
    return (F.ITEMS.get(item) or [None] * 5)[4]


def template_of(item):
    return (F.ITEMS.get(item) or [None] * 6)[5]


def price_of(item):
    return float((F.ITEMS.get(item) or [None, None, None, 0])[3] or 0)


def seed(db, mode):
    init(db)
    if db.one("select 1 as x from supplier_profile where mode=%s limit 1", (mode,)):
        return False
    for k, s in F.SUPPLIERS.items():
        ot, pp = SIM_P.get(k, (0.95, 0.99))
        db.x("insert into supplier_profile (mode, supplier, cat, role, active, price_index, lead_days, on_time_p, pass_p) values (%s,%s,%s,'default',true,1,%s,%s,%s) "
             "on conflict do nothing", (mode, s["name"], k, s["lead"], ot, pp))
    for k, (name, pi, lead) in ALT.items():                        # 轴承、钢材的备选已经在用；铸件、锻坯的备选还要“开发”
        db.x("insert into supplier_profile (mode, supplier, cat, role, active, price_index, lead_days, on_time_p, pass_p) values (%s,%s,%s,'alt',%s,%s,%s,%s,%s) "
             "on conflict do nothing", (mode, name, k, k in ALT_ACTIVE, pi, lead, ALT_P[0], ALT_P[1]))
    return True


def reset(db, mode):
    """情景重置：批次、用料记录清空；备选供应商回到初始；模拟器关闭（老师开始实验后打开）"""
    init(db)
    keep = {k: v for k, v in _state(db, mode).items() if k in ("setup_pid", "setup_at")}
    for t in ("lot", "batch_use", "supplier_profile", "supply_sim"):
        db.x("delete from {} where mode=%s".format(t), (mode,))
    _save_state(db, mode, dict(keep, enabled=False, use_seq=_last_seq(db, mode), mr_done=[m["data"]["name"] for m in db.erp_docs("Material Request", mode)]))
    seed(db, mode)


def _last_seq(db, mode):
    try:
        r = db.one("select max(seq) as s from bus_message where mode=%s", (mode,))
        return int((r or {}).get("s") or 0)
    except Exception:  # noqa: BLE001
        return 0


def _state(db, mode):
    init(db)
    r = db.one("select state from supply_sim where mode=%s", (mode,))
    return (r or {}).get("state") or {}


def _save_state(db, mode, st):
    db.x("insert into supply_sim (mode, state) values (%s,%s) on conflict (mode) do update set state=excluded.state", (mode, Jsonb(st)))


def enabled(db, mode):
    """供应商会出问题（教学模拟器）：教学模式默认开，情景重载后关；生产模式不模拟"""
    if mode != "teach":
        return False
    return bool(_state(db, mode).get("enabled", True))


def set_enabled(db, mode, on):
    st = _state(db, mode)
    st["enabled"] = bool(on)
    _save_state(db, mode, st)
    return {"enabled": bool(on)}


# ---------------------------------------------------------------- 供应商
def profiles(db, mode, cat=None):
    seed(db, mode)
    w, a = "mode=%s", [mode]
    if cat:
        w += " and cat=%s"
        a.append(cat)
    return db.q("select * from supplier_profile where {} order by cat, role desc".format(w), a)


def supplier_for(db, mode, item, role="default"):
    c = cat_of(item)
    return next((p for p in profiles(db, mode, c) if p["role"] == role and p["active"]), None)


def scorecard(db, mode, days=30):
    """每家供应商：准时率（到货不晚于承诺日）、合格率（检验过的批次）、价格指数、在途"""
    seed(db, mode)
    out = []
    for p in profiles(db, mode):
        lots = db.q("select * from lot where mode=%s and supplier=%s and ordered_at > now() - make_interval(days => %s)", (mode, p["supplier"], days))
        due = [x for x in lots if x["arrived_at"] or (x["due_at"] and x["status"] in ("transit", "ordered") and x["late_days"] > 0)]
        arrived = [x for x in lots if x["arrived_at"]]
        on_time = [x for x in arrived if float(x["late_days"] or 0) <= 0]
        insp = [x for x in lots if x["status"] in ("accepted", "rejected", "returned", "suspect") and x["inspection"]]
        ok = [x for x in insp if (x["inspection"] or {}).get("status") == "Accepted" and not x["concession"]]
        out.append({"supplier": p["supplier"], "cat": p["cat"], "cat_name": CAT_NAME.get(p["cat"], p["cat"]), "role": p["role"], "active": p["active"],
                    "price_index": float(p["price_index"]), "lead_days": p["lead_days"],
                    "hist_on_time": float(p["on_time_p"]), "hist_pass": float(p["pass_p"]),        # 过去一年的历史（评分卡上显示，实验 20 算总拥有成本用） "lots": len(lots), "due": len(due),
                    "on_time": round(len(on_time) / len(arrived), 3) if arrived else None, "arrived": len(arrived),
                    "pass_rate": round(len(ok) / len(insp), 3) if insp else None, "inspected": len(insp),
                    "in_transit": sum(1 for x in lots if x["status"] in ("ordered", "transit"))})
    return out


def single_source(db, mode):
    """只有一家在用供应商的物料类别（有备选但没启用的也算）"""
    seed(db, mode)
    out = []
    for c in F.SUPPLIERS:
        act = [p for p in profiles(db, mode, c) if p["active"]]
        if len(act) <= 1:
            items = [k for k, v in F.ITEMS.items() if v[4] == c]
            out.append({"cat": c, "cat_name": CAT_NAME.get(c, c), "supplier": act[0]["supplier"] if act else None, "items": items,
                        "has_alt": any(p["role"] == "alt" for p in profiles(db, mode, c))})
    return out


# ---------------------------------------------------------------- 下单、发货、到货
def place_po(H, mode, supplier, items, who, mr=None, action_id=None, rush=False):
    """下采购单：每个物料一行批次（已下单）；提议交桥接写 ERPNext。items：[{item_code, qty}]"""
    db = H.db
    seed(db, mode)
    prof = db.one("select * from supplier_profile where mode=%s and supplier=%s", (mode, supplier))
    if prof is None:
        raise ValueError("没有这家供应商：{}".format(supplier))
    if not prof["active"]:
        raise ValueError("{} 还没启用（先开发备选供应商）".format(supplier))
    lead = int(prof["lead_days"])
    from hub import kpi
    promised = kpi.add_working_days(dt.datetime.now(kpi.TZ).date(), lead)
    rows = []
    for i in items:
        if cat_of(i["item_code"]) != prof["cat"]:
            raise ValueError("{} 不供应 {}".format(supplier, i["item_code"]))
        rows.append({"item_code": i["item_code"], "qty": float(i["qty"]), "rate": round(price_of(i["item_code"]) * float(prof["price_index"]), 2),
                     **({"material_request": i["material_request"], "material_request_item": i.get("material_request_item")} if i.get("material_request") else {})})
    pid = None
    if H.ai is not None:
        pid = H.ai.propose("purchase_order", {"supplier": supplier, "schedule_date": promised.isoformat(), "items": rows}, mode, who,
                           "采购单：{} {}".format(supplier.split(" ")[0], "、".join("{} × {:g}".format(r["item_code"], r["qty"]) for r in rows)), source="supply")
        H.ai.decide(pid, who, True)
    ids = []
    for r in rows:
        x = db.one("insert into lot (mode, proposal_id, supplier, item, qty, rate, status, promised, action_id, note, mr) values (%s,%s,%s,%s,%s,%s,'ordered',%s,%s,%s,%s) "
                   "returning id", (mode, pid, supplier, r["item_code"], r["qty"], r["rate"], promised, action_id, "加急" if rush else None,
                                    r.get("material_request") or mr))
        ids.append(x["id"])
    return {"proposal_id": pid, "lots": ids, "promised": promised.isoformat(), "rows": rows}


def _erp_name(db, pid, doctype):
    if not pid:
        return None
    import json
    p = db.one("select status, result from ai_proposal where proposal_id=%s", (pid,))
    res = (p or {}).get("result") or {}
    if isinstance(res, str):
        res = json.loads(res)
    return next((c[1] for c in res.get("created", []) if c[0] == doctype), None)


def _ship(db, mode, x, now, rng, sim):
    """采购单进了 ERPNext：供应商发货（在途），按提前期定到货时刻；模拟器打开时按准时率决定晚几天"""
    prof = db.one("select * from supplier_profile where mode=%s and supplier=%s", (mode, x["supplier"])) or {"lead_days": 7, "on_time_p": 1, "pass_p": 1}
    st = _state(db, mode)
    inj = (st.get("inject") or {}).get(x["supplier"]) or {}
    late = 0
    bad = False
    if sim:
        if inj.get("late_days") is not None:
            late = float(inj["late_days"])
        elif rng.random() > float(prof["on_time_p"]):
            late = rng.choice((1, 2, 3, 5))
        if inj.get("bad") is not None:
            bad = bool(inj["bad"])
        elif template_of(x["item"]) and rng.random() > float(prof["pass_p"]):
            bad = True
        if inj:
            st.setdefault("inject", {}).pop(x["supplier"], None)
            _save_state(db, mode, st)
    days = int(prof["lead_days"]) + late
    lot = "L{}-{:04d}".format(now.strftime("%y%m%d"), x["id"])
    db.x("update lot set status='transit', lot=%s, due_at=%s, late_days=%s, truth_bad=%s where id=%s",
         (lot, now + dt.timedelta(seconds=days * DAY_S), late, bad, x["id"]))


def arrive(db, mode, lid, who="仓管员", short=None, at=None):
    x = db.one("select * from lot where id=%s and mode=%s", (lid, mode))
    if x is None:
        raise KeyError(lid)
    if x["status"] not in ("transit", "ordered"):
        raise ValueError("这一批已经{}".format(STATUS[x["status"]]))
    qty = float(x["qty"]) if short is None else float(short)
    if not x["lot"]:
        db.x("update lot set lot=%s where id=%s", ("L{}-{:04d}".format(dt.datetime.now().strftime("%y%m%d"), x["id"]), lid))
    late = x["late_days"]
    if x["promised"] and mode != "teach":
        from hub import kpi
        late = max(0, (dt.datetime.now(kpi.TZ).date() - x["promised"]).days)
    db.x("update lot set status='arrived', arrived_at=coalesce(%s, now()), qty=%s, late_days=%s, note=coalesce(note,'') || %s where id=%s",
         (at, qty, late, "；{} 登记到货".format(who) if who else "", lid))
    return {"id": lid, "status": "arrived"}


def sample(db, mode, lid, n=None):
    """来料检验的抽样数据（量具读数）：按批次固定生成，有问题的批次里有超差的件"""
    x = db.one("select * from lot where id=%s and mode=%s", (lid, mode))
    if x is None:
        raise KeyError(lid)
    tpl = template_of(x["item"])
    if not tpl:
        return {"lot": x["lot"], "item": x["item"], "template": None, "sample_size": 0, "rows": []}
    params = F.inspection_templates()[tpl]
    n = n or min(8, max(3, int(float(x["qty"]) // 5)))
    rng = random.Random(zlib.crc32((x["lot"] or str(lid)).encode()))
    bad_idx = set(rng.sample(range(n), 2)) if x["truth_bad"] else set()
    rows = []
    for i in range(n):
        vals = {}
        for p in params:
            if p["numeric"]:
                lo, hi = float(p["min"]), float(p["max"])
                span = hi - lo
                v = rng.uniform(lo + span * 0.25, hi - span * 0.25)
                if i in bad_idx:
                    v = hi + span * rng.uniform(0.1, 0.3) if p["max"] <= 0 or rng.random() < 0.5 else lo - span * rng.uniform(0.1, 0.3)
                vals[p["parameter"]] = round(v, 1)
            else:
                vals[p["parameter"]] = p["value"]
        rows.append(vals)
    return {"lot": x["lot"], "item": x["item"], "template": tpl, "sample_size": n, "rows": rows,
            "params": [{"specification": p["parameter"], "numeric": bool(p["numeric"]), "min": p.get("min"), "max": p.get("max"), "value": p.get("value")}
                       for p in params]}


def judge(sm):
    """按模板判定：任何一件、任何一项超差就不合格"""
    bad = []
    for i, r in enumerate(sm["rows"]):
        for p in sm["params"]:
            v = r.get(p["specification"])
            if p["numeric"] and not (float(p["min"]) <= float(v) <= float(p["max"])):
                bad.append({"n": i + 1, "spec": p["specification"], "value": v})
    return bad


def inspect(H, mode, lid, accept, who, note=""):
    """来料检验与收货：合格 → 收货单提交入库；不合格 → 收货单留草稿、检验单判不合格（等退货或让步接收）。
    没有检验模板的物料（钢材、标准件）直接收货"""
    db = H.db
    x = db.one("select * from lot where id=%s and mode=%s", (lid, mode))
    if x is None:
        raise KeyError(lid)
    if x["status"] != "arrived":
        raise ValueError("只有到货待检的批次能检验（现在：{}）".format(STATUS[x["status"]]))
    sm = sample(db, mode, lid)
    bad = judge(sm) if sm["template"] else []
    accept = bool(accept) if sm["template"] else True
    readings = []
    for p in sm["params"] if sm["template"] else []:
        worst = None
        for r in sm["rows"]:
            v = r[p["specification"]]
            if p["numeric"] and (worst is None or not (float(p["min"]) <= float(v) <= float(p["max"]))):
                worst = v
        readings.append({"specification": p["specification"], "numeric": p["numeric"], "min": p.get("min"), "max": p.get("max"),
                         "value": worst if p["numeric"] else p["value"],
                         "ok": True if not p["numeric"] else (float(p["min"]) <= float(worst) <= float(p["max"]))})
    res = {"status": "Accepted" if accept else "Rejected", "sample_size": sm["sample_size"], "bad": bad, "by": who, "note": note[:300]}
    qty = float(x["qty"])
    db.x("update lot set status=%s, inspected_by=%s, inspection=%s, qty_ok=%s, qty_left=%s, received_at=case when %s then now() else null end where id=%s",
         ("accepted" if accept else "rejected", who, Jsonb(res), qty if accept else 0, qty if accept else 0, accept, lid))
    pid = _receipt(H, mode, x, sm, readings, accept, qty, who, note)
    db.x("update lot set receipt_pid=%s where id=%s", (pid, lid))
    return {"id": lid, "status": "accepted" if accept else "rejected", "bad": bad, "proposal_id": pid, "matches_sample": (not bad) == accept}


def _receipt(H, mode, x, sm, readings, accept, qty, who, note, remarks=None):
    db = H.db
    po = x["po"] or _erp_name(db, x["proposal_id"], "Purchase Order")
    if not po or H.ai is None:
        return None
    pid = H.ai.propose("incoming_receipt", {"purchase_order": po, "item_code": x["item"], "qty": float(x["qty"]), "lot": x["lot"],
                                            "inspect": bool(sm["template"]), "template": sm["template"], "sample_size": sm["sample_size"] or 1,
                                            "status": "Accepted" if accept else "Rejected", "readings": readings, "accept": accept,
                                            "accept_qty": qty, "remarks": remarks or ("{}：{}".format(who, note) if note else who)},
                       mode, who, "{} {} 批 {}".format("收货入库" if accept else "来料不合格", x["item"], x["lot"]), source="supply")
    H.ai.decide(pid, who, True)
    return pid


def return_lot(H, mode, lid, who, action_id=None):
    """退货：这一批退回，供应商补发（新的一批，按提前期）"""
    db = H.db
    x = db.one("select * from lot where id=%s and mode=%s", (lid, mode))
    if x is None:
        raise KeyError(lid)
    if x["status"] != "rejected":
        raise ValueError("只有不合格的批次能退货")
    db.x("update lot set status='returned', note=coalesce(note,'') || %s where id=%s", ("；{} 退货".format(who), lid))
    prof = db.one("select * from supplier_profile where mode=%s and supplier=%s", (mode, x["supplier"])) or {"lead_days": 7}
    from hub import kpi
    promised = kpi.add_working_days(dt.datetime.now(kpi.TZ).date(), int(prof["lead_days"]))
    r = db.one("insert into lot (mode, po, proposal_id, supplier, item, qty, rate, status, promised, action_id, note) values "
               "(%s,%s,%s,%s,%s,%s,%s,'ordered',%s,%s,%s) returning id",
               (mode, x["po"] or _erp_name(db, x["proposal_id"], "Purchase Order"), x["proposal_id"], x["supplier"], x["item"], x["qty"], x["rate"], promised,
                action_id, "补发（退货 {}）".format(x["lot"])))
    return {"text": "批 {} 退货，{} 补发（约 {} 天到）".format(x["lot"], x["supplier"].split(" ")[0], prof["lead_days"]), "new_lot": r["id"]}


def concession(H, mode, lid, who, action_id=None):
    """让步接收：全检挑出能用的件入库（全检工时），不合格的退回"""
    db = H.db
    x = db.one("select * from lot where id=%s and mode=%s", (lid, mode))
    if x is None:
        raise KeyError(lid)
    if x["status"] != "rejected":
        raise ValueError("只有不合格的批次能让步接收")
    rng = random.Random(zlib.crc32(("c" + (x["lot"] or "")).encode()))
    bad_frac = rng.uniform(0.1, 0.25) if x["truth_bad"] else rng.uniform(0.0, 0.05)
    qty = float(x["qty"])
    ok = float(int(round(qty * (1 - bad_frac))))
    hours = round(qty * CONCESSION_H, 1)
    db.x("update lot set status='accepted', concession=true, qty_ok=%s, qty_left=%s, received_at=now(), note=coalesce(note,'') || %s where id=%s",
         (ok, ok, "；{} 让步接收，全检 {:g} 件挑出 {:g} 件可用".format(who, qty, ok), lid))
    sm = sample(db, mode, lid)
    readings = [{"specification": p["specification"], "numeric": p["numeric"], "min": p.get("min"), "max": p.get("max"),
                 "value": (float(p["min"]) + float(p["max"])) / 2 if p["numeric"] else p["value"], "ok": True} for p in sm.get("params") or []]
    pid = _receipt(H, mode, dict(x, qty=ok), sm, readings, True, ok, who, "", remarks="让步接收：全检 {:g} 件，合格 {:g} 件入库".format(qty, ok))
    return {"text": "批 {} 让步接收：全检 {:g} 件，{:g} 件可用入库（检验 {:g} 小时）".format(x["lot"], qty, ok, hours), "qty_ok": ok, "proposal_id": pid,
            "hours": hours}


def mark_suspect(db, mode, lid, who, why):
    db.x("update lot set status='suspect', note=coalesce(note,'') || %s where id=%s and mode=%s", ("；{}：{}".format(who, why), lid, mode))


def activate_alt(H, mode, cat, who):
    """开发备选供应商：启用这一类的备选，在 ERPNext 建供应商"""
    db = H.db
    seed(db, mode)
    p = next((x for x in profiles(db, mode, cat) if x["role"] == "alt"), None)
    if p is None:
        raise ValueError("{} 没有可开发的备选供应商".format(CAT_NAME.get(cat, cat)))
    db.x("update supplier_profile set active=true where mode=%s and supplier=%s", (mode, p["supplier"]))
    pid = None
    if H.ai is not None:
        pid = H.ai.propose("supply_setup", {"suppliers": [{"name": p["supplier"], "group": F.SUPPLIER_GROUP}]}, mode, who, "备选供应商 " + p["supplier"], source="supply")
        H.ai.decide(pid, who, True)
    return {"text": "{}：启用备选供应商 {}（贵 {:.0%}，{} 天到）".format(CAT_NAME.get(cat, cat), p["supplier"], float(p["price_index"]) - 1, p["lead_days"]),
            "proposal_id": pid}


def ensure_setup(H, mode, who="系统"):
    """教学模式：在 ERPNext 建好备选供应商（开发备选时才启用）。和台账一样：没执行就重发，桥接按名称跳过已建的"""
    import time as _t
    db = H.db
    if H.ai is None or mode != "teach":
        return None
    seed(db, mode)
    st = _state(db, mode)
    pid = st.get("setup_pid")
    if pid:
        p = db.one("select status from ai_proposal where proposal_id=%s", (pid,))
        age = _t.time() - float(st.get("setup_at") or 0)
        if p and (p["status"] == "executed" or age < 180 or (p["status"] == "failed" and age < 3600)):
            return pid
    pid = H.ai.propose("supply_setup", {"suppliers": [{"name": v[0], "group": F.SUPPLIER_GROUP} for v in ALT.values()]}, mode, who,
                       "备选供应商 {} 家".format(len(ALT)), source="supply")
    H.ai.decide(pid, who, True)
    st = _state(db, mode)
    st["setup_pid"], st["setup_at"] = pid, _t.time()
    _save_state(db, mode, st)
    return pid


# ---------------------------------------------------------------- 批次用料（E5-5）
def scan_use(db, mode):
    """车间每开工一件（第一道工序），按先进先出记下它用了哪个批次的料"""
    init(db)
    st = _state(db, mode)
    last = int(st.get("use_seq") or 0)
    rows = db.q("select seq, ts, topic, payload from bus_message where type='machine.event' and mode=%s and seq > %s "
                "and payload->'data'->>'event'='cycle_start' and (payload->'data'->>'op_index')::int = 0 order by seq limit 500", (mode, last))
    n = 0
    for r in rows:
        d = r["payload"]["data"]
        st["use_seq"] = r["seq"]
        item = d.get("item")
        unit = r["topic"].split("/")[3]
        for code, q in (F.BOMS.get(item) or ("", []))[1]:
            if (F.ITEMS.get(code) or [None, None])[1] not in ("raw", "buy"):
                continue
            x = db.one("select id, lot from lot where mode=%s and item=%s and status in ('accepted','suspect') and qty_left >= %s order by received_at, id limit 1",
                       (mode, code, q))
            if x:
                db.x("update lot set qty_left = qty_left - %s where id=%s", (q, x["id"]))
                name = x["lot"]
            else:
                name = "期初-" + code                            # 情景开始时库里的料
            db.x("insert into batch_use (mode, lot, item, part_serial, work_order, unit, qty, at) values (%s,%s,%s,%s,%s,%s,%s,%s)",
                 (mode, name, code, d.get("part_serial"), d.get("work_order"), unit, q, r["ts"]))
            n += 1
    if rows:
        _save_state(db, mode, dict(_state(db, mode), use_seq=st["use_seq"]))
    return n


def trace(db, mode, lot=None, serial=None):
    """批次追溯：批次 → 零件、工单、现场设备；或零件 / 设备序列号 → 批次 → 供应商"""
    init(db)
    from hub import twin as TW
    if serial:
        parts = {serial}
        try:
            for r in db.q("select serial, as_built from twin where mode=%s and serial=%s", (mode, serial)):
                parts |= {str(v) for v in (r["as_built"] or {}).values() if isinstance(v, str)}
        except Exception:  # noqa: BLE001
            pass
        uses = db.q("select * from batch_use where mode=%s and part_serial = any(%s) order by at", (mode, list(parts)))
        lots = {u["lot"] for u in uses}
        rows = db.q("select * from lot where mode=%s and lot = any(%s)", (mode, list(lots)))
        return {"serial": serial, "parts": sorted(parts), "uses": [dict(u, at=u["at"].isoformat(), qty=float(u["qty"] or 0)) for u in uses],
                "lots": [_lot_row(x) for x in rows]}
    x = db.one("select * from lot where mode=%s and lot=%s", (mode, lot))
    uses = db.q("select * from batch_use where mode=%s and lot=%s order by at", (mode, lot))
    serials = sorted({u["part_serial"] for u in uses if u["part_serial"]})
    units = []
    try:
        for f in TW.fleet(db, mode):
            ab = {str(v) for v in (f.get("as_built") or {}).values()} if isinstance(f.get("as_built"), dict) else set()
            if f["serial"] in serials or ab & set(serials):
                units.append({"serial": f["serial"], "customer": f.get("customer")})
    except Exception:  # noqa: BLE001
        pass
    if not units:
        try:
            for r in db.q("select serial, as_built from twin where mode=%s", (mode,)):
                vals = {str(v) for v in (r["as_built"] or {}).values()}
                if vals & set(serials):
                    units.append({"serial": r["serial"], "customer": None})
        except Exception:  # noqa: BLE001
            pass
    return {"lot": lot, "row": _lot_row(x) if x else None, "parts": serials, "work_orders": sorted({u["work_order"] for u in uses if u["work_order"]}),
            "units": units, "uses": len(uses)}


def _lot_row(x):
    return {"id": x["id"], "lot": x["lot"], "po": x["po"], "supplier": x["supplier"], "item": x["item"], "qty": float(x["qty"]),
            "qty_ok": float(x["qty_ok"]) if x["qty_ok"] is not None else None, "qty_left": float(x["qty_left"] or 0), "status": x["status"],
            "status_label": STATUS.get(x["status"], x["status"]), "promised": str(x["promised"]) if x["promised"] else None,
            "due_at": x["due_at"].isoformat() if x["due_at"] else None, "arrived_at": x["arrived_at"].isoformat() if x["arrived_at"] else None,
            "received_at": x["received_at"].isoformat() if x["received_at"] else None, "late_days": float(x["late_days"] or 0),
            "inspection": x["inspection"], "concession": x["concession"], "note": x["note"], "ordered_at": x["ordered_at"].isoformat()}


def lots(db, mode, status=None, limit=200):
    seed(db, mode)
    w, a = "mode=%s", [mode]
    if status:
        w += " and status = any(%s)"
        a.append(list(status))
    return [_lot_row(x) for x in db.q("select * from lot where {} order by id desc limit {}".format(w, int(limit)), a)]


# ---------------------------------------------------------------- 教学模拟器
def tick(H, mode, now=None, rng=None):
    db = H.db
    seed(db, mode)
    now = now or dt.datetime.now(dt.timezone.utc)
    rng = rng or random.Random()
    out = {"pos": [], "shipped": [], "arrived": [], "inspected": [], "returned": [], "used": scan_use(db, mode)}
    sim = enabled(db, mode)
    # 采购单进了 ERPNext → 发货（在途）
    for x in db.q("select * from lot where mode=%s and status='ordered'", (mode,)):
        po = x["po"] or _erp_name(db, x["proposal_id"], "Purchase Order")
        if po is None and H.ai is not None and x["proposal_id"]:
            continue
        if po and not x["po"]:
            db.x("update lot set po=%s where id=%s", (po, x["id"]))
        if mode == "teach":
            _ship(db, mode, x, now, rng, sim)
            out["shipped"].append(x["id"])
        else:
            db.x("update lot set status='transit', lot=coalesce(lot, %s) where id=%s", ("L{}-{:04d}".format(now.strftime("%y%m%d"), x["id"]), x["id"]))
    if mode != "teach":
        return out
    # 到时间到货
    for x in db.q("select * from lot where mode=%s and status='transit' and due_at <= %s", (mode, now)):
        short = float(x["qty"]) * 0.9 if sim and rng.random() < 0.05 else None
        arrive(db, mode, x["id"], "供应商送货", short=int(short) if short else None, at=now)
        out["arrived"].append(x["id"])
    st = _state(db, mode)
    hold = set(st.get("hold") or [])                                # 实验 20：老师注入的这一批留给学生检验
    if sim:
        # 请购单 3 分钟没人转：采购员（模拟器）按默认供应商下单
        mrs = db.erp_docs("Material Request", mode)
        if "mr_done" not in st:                                     # 第一次打开：以前的请购单不补下单
            st["mr_done"] = [m["data"]["name"] for m in mrs]
        done = set(st.get("mr_done") or [])
        for m in mrs:
            d = m["data"]
            if d["name"] in done or d.get("docstatus") != 1 or d.get("status") not in ("Pending", "Partially Ordered", None):
                continue
            age = (now - dt.datetime.fromisoformat(str(m["ts"]).replace("Z", "+00:00"))).total_seconds() if m.get("ts") else 1e9
            if age < MR_AUTO_S:
                continue
            done.add(d["name"])
            by_sup = {}
            for it in d.get("items") or []:
                p = supplier_for(db, mode, it["item_code"])
                if p:
                    by_sup.setdefault(p["supplier"], []).append({"item_code": it["item_code"], "qty": float(it["qty"]), "material_request": d["name"],
                                                                 "material_request_item": it.get("name")})
            for sup, items in by_sup.items():
                try:
                    out["pos"].append(place_po(H, mode, sup, items, "采购员（教学模拟器）", mr=d["name"])["proposal_id"])
                except ValueError:
                    log.exception("自动下单失败")
        _save_state(db, mode, dict(_state(db, mode), mr_done=sorted(done)))
        # 到货 3 分钟没人检验：质检员（模拟器）按抽样判定
        for x in db.q("select * from lot where mode=%s and status='arrived' and arrived_at < %s", (mode, now - dt.timedelta(seconds=ARRIVE_AUTO_S))):
            if x["id"] in hold:
                continue
            sm = sample(db, mode, x["id"])
            inspect(H, mode, x["id"], not judge(sm), "质检员（教学模拟器）")
            out["inspected"].append(x["id"])
        # 不合格 10 分钟没人处理：采购员（模拟器）退货
        for x in db.q("select * from lot where mode=%s and status='rejected' and arrived_at < %s", (mode, now - dt.timedelta(seconds=RETURN_AUTO_S))):
            if x["id"] in hold:
                continue
            return_lot(H, mode, x["id"], "采购员（教学模拟器）")
            out["returned"].append(x["id"])
    return out


def inject(H, mode, supplier, who, late_days=None, bad=None, item=None, qty=None):
    """老师：这家供应商下一批晚 N 天 / 不合格；给了物料就马上下一张单（实验 20：这一批留给学生检验）"""
    db = H.db
    seed(db, mode)
    if not db.one("select 1 as x from supplier_profile where mode=%s and supplier=%s", (mode, supplier)):
        raise ValueError("没有这家供应商")
    st = _state(db, mode)
    st.setdefault("inject", {})[supplier] = {k: v for k, v in (("late_days", late_days), ("bad", bad)) if v is not None}
    _save_state(db, mode, st)
    out = {"text": "{} 下一批：{}".format(supplier.split(" ")[0], "、".join(x for x in ("晚 {:g} 天".format(late_days) if late_days else "",
                                                                              "不合格" if bad else "") if x) or "正常")}
    if item:
        r = place_po(H, mode, supplier, [{"item_code": item, "qty": float(qty or 40)}], who)
        st = _state(db, mode)
        st["hold"] = sorted(set(st.get("hold") or []) | set(r["lots"]))
        st["lab20"] = {"lot_id": r["lots"][0], "item": item, "supplier": supplier}
        _save_state(db, mode, st)
        out["lot_id"] = r["lots"][0]
        out["text"] += "；已下采购单 {} × {:g}，到货后留给学生检验".format(item, float(qty or 40))
    return out


# ---------------------------------------------------------------- 处理方案（E5-7）
def options(db, mode, a, snap, ctx):
    """W3 来料不合格：退货等补发 / 备选供应商急单 / 让步接收全检 / 不处理（对照）。推演里按每个方案的到料日下达等料的工单"""
    from hub import kpi
    from hub.ont import plan as P
    v = (a.get("detail") or {}).get("values") or {}
    x = db.one("select * from lot where mode=%s and id=%s", (mode, v.get("lot_id"))) if v.get("lot_id") else None
    if x is None:
        return {"options": [], "affected": [], "reason": "找不到这一批", "recommended": None}
    today = dt.datetime.now(kpi.TZ).date()
    prof = db.one("select * from supplier_profile where mode=%s and supplier=%s", (mode, x["supplier"])) or {"lead_days": 7}
    alt = supplier_for(db, mode, x["item"], "alt")
    qty, value = float(x["qty"]), float(x["qty"]) * price_of(x["item"])
    names = sorted({r["sales_order"] for r in ctx.get("releases") or [] if x["item"] in (r.get("short") or [])})
    plans = [("none", "不处理（对照）", today + dt.timedelta(days=30), [], "这批料不能用，等料的订单一直等")]
    plans.append(("return", "退货，等 {} 补发".format(x["supplier"].split(" ")[0]), kpi.add_working_days(today, int(prof["lead_days"])), [],
                  "补发约 {} 个工作日到；不花钱（运费由供应商出）".format(prof["lead_days"])))
    if alt:
        prem = round(value * (float(alt["price_index"]) - 1), 2)
        plans.append(("alt", "向备选 {} 下急单".format(alt["supplier"].split(" ")[0]), kpi.add_working_days(today, int(alt["lead_days"])),
                      [{"what": "备选供应商加价 {:.0%}".format(float(alt["price_index"]) - 1), "usd": prem}]
                      + ([] if alt["active"] else [{"what": "开发备选供应商（资质审核、样品）", "usd": 300.0}]),
                      "{} 个工作日到；这一批退货{}".format(alt["lead_days"], "" if alt["active"] else "；备选还没启用，要先开发")))
    hours = round(qty * CONCESSION_H, 1)
    plans.append(("concession", "让步接收，全检挑用", kpi.add_working_days(today, 1), [{"what": "全检 {:g} 小时".format(hours), "usd": round(hours * INSPECT_RATE, 2)}],
                  "全检一天，能用的件（约八成）先入库，不能用的退回；要质量批"))
    out = []
    for i, (kind, label, arrive_d, costs, note) in enumerate(plans):
        sim = [{"type": "material_arrival", "item": x["item"], "arrive": arrive_d.isoformat()}]
        r = P.simulate(snap, sim, ctx)
        rows = [s for s in r["sales_orders"] if s["name"] in names]
        lates = [s["late_days"] for s in rows if s["late_days"] is not None]
        cs = list(r["costs"]) + costs
        res = {"sales_orders": rows, "cost_total": round(sum(c["usd"] for c in cs), 2), "costs": cs, "overtime_min": r["overtime_min"],
               "overtime_units": r["overtime_units"], "checks": r["checks"], "ok": r["ok"] and kind != "none"}
        changes = {"none": [], "return": [{"type": "supplier_return", "lot_id": x["id"]}],
                   "alt": [{"type": "supplier_return", "lot_id": x["id"]}] + ([] if alt is None or alt["active"] else [{"type": "alt_supplier", "cat": alt["cat"]}])
                   + ([{"type": "purchase_order", "supplier": alt["supplier"], "items": [{"item_code": x["item"], "qty": qty}], "rush": True}] if alt else []),
                   "concession": [{"type": "concession", "lot_id": x["id"]}]}[kind]
        out.append({"key": chr(ord("A") + i), "kind": kind, "label": label, "note": note, "arrive": arrive_d.isoformat(), "changes": changes,
                    "result": res, "worst_late": max(lates) if lates else None, "undetermined": len(lates) < len(rows)})

    def score(o):                                   # 交期保得住的方案里花钱最少的；一样时先到的
        wl = o["worst_late"] if o["worst_late"] is not None else 0
        return (1 if o["kind"] == "none" else 0, max(wl, 0), o["result"]["cost_total"], o["arrive"])
    best = min(out, key=score)
    for o in out:
        o["recommended"] = o is best
    st = _state(db, mode)                           # 实验 20 评分用：中枢对这一批推荐了哪个
    st.setdefault("recommended", {})[str(x["id"])] = best["kind"]
    _save_state(db, mode, st)
    reason = "建议 {} {}：{} 到料；{}；多花 ${:,.0f}。".format(best["key"], best["label"], best["arrive"], "；".join(
        "{} {}".format(s["name"], "按时" if (s["late_days"] or 0) <= 0 else "晚 {} 天".format(s["late_days"])) for s in best["result"]["sales_orders"])
        or "现在没有在等这种料的订单（先到的料先补安全库存）", best["result"]["cost_total"])
    return {"options": out, "affected": names, "reason": reason, "recommended": best["key"], "lot": _lot_row(x)}


def alt_options(db, mode, a):
    """W6 单一来源 / W4 准时率低：开发备选供应商 / 暂不处理"""
    v = (a.get("detail") or {}).get("values") or {}
    cat = v.get("cat")
    alt = next((p for p in profiles(db, mode, cat) if p["role"] == "alt"), None) if cat else None
    out = []
    if alt and not alt["active"]:
        out.append({"key": "A", "kind": "alt", "label": "开发备选供应商 {}".format(alt["supplier"].split(" ")[0]),
                    "note": "贵 {:.0%}，{} 天到；平时仍向默认供应商下单，出问题时有退路".format(float(alt["price_index"]) - 1, alt["lead_days"]),
                    "changes": [{"type": "alt_supplier", "cat": cat}],
                    "result": {"sales_orders": [], "cost_total": 300.0, "costs": [{"what": "资质审核、样品", "usd": 300.0}], "overtime_min": 0, "checks": [], "ok": True},
                    "recommended": True})
    out.append({"key": chr(ord("A") + len(out)), "kind": "none", "label": "暂不处理", "note": "这家出问题时没有别的选择",
                "changes": [], "result": {"sales_orders": [], "cost_total": 0, "costs": [], "overtime_min": 0, "checks": [], "ok": True}, "recommended": not out})
    return {"options": out, "affected": [], "recommended": out[0]["key"],
            "reason": "建议 A：开发一家备选，出问题时能换供应商；平时不改默认供应商" if out[0]["kind"] == "alt" else "这一类没有可开发的备选供应商（以后可以在平台里加）"}


# ---------------------------------------------------------------- 态势
def kpis(db, mode, days=30):
    seed(db, mode)
    sc = scorecard(db, mode, days)
    arrived = sum(x["arrived"] for x in sc)
    on_time = sum(round((x["on_time"] or 0) * x["arrived"]) for x in sc)
    insp = sum(x["inspected"] for x in sc)
    ok = sum(round((x["pass_rate"] or 0) * x["inspected"]) for x in sc)
    return {"in_transit": db.one("select count(*) as n from lot where mode=%s and status in ('ordered','transit')", (mode,))["n"],
            "waiting_inspection": db.one("select count(*) as n from lot where mode=%s and status='arrived'", (mode,))["n"],
            "rejected_open": db.one("select count(*) as n from lot where mode=%s and status='rejected'", (mode,))["n"],
            # 检验过的批次累计（帮助“带我检验一批来料”的做完打勾看它变多）
            "inspected_n": db.one("select count(*) as n from lot where mode=%s and inspected_by is not null", (mode,))["n"],
            "on_time": round(on_time / arrived, 3) if arrived else None, "pass_rate": round(ok / insp, 3) if insp else None,
            "single_source": len(single_source(db, mode)), "enabled": enabled(db, mode)}
