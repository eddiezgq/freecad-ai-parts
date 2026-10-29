# -*- coding: utf-8 -*-
"""问渠数字工业园：两厂互发订单（第 51 轮）。

两座厂是两套独立部署（第 45 轮 R-5），各自一个枢纽、一个 ERPNext。这里只传两类消息：
- 下单：买方厂（机器人厂）向工业园兄弟厂（减速器厂）下的采购单 → POST 对方 /api/park/orders，对方记成一张“工业园订单”。
- 发货：卖方厂订单做完 → POST 买方 /api/park/shipments，带批号、出厂编号；买方那一批货变成“在途”，到货后照常来料检验。

卖方：工业园订单进“订单与计划”的待接列表，计划员接单（算料、写进 ERPNext、下达）；老师可开“自动接单”（缺省开），
没人接时 AUTO_S 秒后平台代接、下达车间、开工。订单的工单都做完 = 发货（与“订单做完开票”同一个判据）。
买方：对方连不上、或不接这种物料时，这张采购单按普通外部供应商处理（supply.py 的 _ship），页面写明原因。

只连教学模式（S-6）。两边用服务器上的共享密钥 WQ_PARK_KEY 认证；对方地址在 WQ_PARK_PEERS（“清单id=网址”，空格分开）。
对方的库存、成本、客户资料互不可见（规则 3）。"""
import datetime as dt
import hmac
import json
import logging
import os
import urllib.error
import urllib.request

from psycopg.types.json import Jsonb

from factory import data as F
from factory import plant as PL

log = logging.getLogger("park")

SCHEMA = """
create table if not exists park_order (
    id          bigserial primary key,
    mode        text not null,
    from_plant  text not null,                    -- 买方厂的清单 id，如 wenquest-robot
    from_name   text not null,                    -- 买方公司名（在本厂 ERPNext 里是客户）
    ref         text not null,                    -- 买方的批次行号（回传发货时用）
    po          text,                             -- 买方 ERPNext 的采购单号（备注）
    item        text not null,
    qty         numeric not null,
    need_by     date,
    status      text not null default 'pending',  -- pending 待接 / accepted 已接单 / released 订单和工单已进 ERPNext（生产中） / shipped 已发货 / failed 写 ERPNext 失败
    proposal_id text,
    so          text,
    work_orders jsonb,
    accepted_by text,
    created_at  timestamptz not null default now(),
    accepted_at timestamptz,
    shipped_at  timestamptz,
    shipment    jsonb,
    note        text,
    unique (from_plant, ref)
);
create table if not exists park_state (
    mode  text primary key,
    state jsonb not null default '{}'
);
alter table lot add column if not exists park jsonb;
"""
AUTO_S = int(os.environ.get("WQ_PARK_AUTO_S", "180"))   # 待接 3 分钟没人接：计划员（教学模拟器）代接（CI 演练调短）
TIMEOUT_S = 6
STATUS = {"pending": "待接单", "accepted": "已接单", "released": "生产中", "shipped": "已发货", "failed": "没写进 ERPNext"}
ACCEPT_ROLES = ("planner", "manager")


def init(db):
    if getattr(db, "_park_ready", False):
        return
    from hub import supply as SP
    SP.init(db)                                    # lot 表先建好（加 park 列）
    db.x(SCHEMA)
    try:
        db._park_ready = True
    except AttributeError:
        pass


# ---------------------------------------------------------------- 配置
def key():
    return os.environ.get("WQ_PARK_KEY", "")


def peers():
    """{清单 id: 枢纽网址}"""
    out = {}
    for x in os.environ.get("WQ_PARK_PEERS", "").split():
        k, _, v = x.partition("=")
        if k and v:
            out[k.strip()] = v.strip().rstrip("/")
    return out


def me():
    """本厂在工业园里的编号：班级工厂用班级编号（同一份清单可以起几座厂），公共工厂用清单 id"""
    return os.environ.get("WQ_PARK_ME") or PL.plant_id()


def my_name():
    return PL.company()["name"]


def check_key(k):
    return bool(key()) and hmac.compare_digest(str(k or ""), key())


def park_of(supplier_cat):
    """这个物料类别的供应商是工业园里的哪座厂（清单供应商一节的 park），不是就 None"""
    return (F.SUPPLIERS.get(supplier_cat) or {}).get("park")


def _post(plant, path, body):
    url = peers().get(plant)
    if not url:
        raise ConnectionError("没有配置 {} 的地址".format(plant))
    if not key():
        raise ConnectionError("没有配置工业园密钥")
    req = urllib.request.Request(url + path, data=json.dumps(body, ensure_ascii=False, default=str).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-WQ-Park-Key": key()})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("detail")
        except Exception:  # noqa: BLE001
            detail = None
        if 400 <= e.code < 500 and e.code not in (401, 403, 404):
            raise ValueError(detail or "对方不接这张单（{}）".format(e.code))
        raise ConnectionError(detail or "对方返回 {}".format(e.code))
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise ConnectionError(str(getattr(e, "reason", e)))


def _state(db, mode):
    init(db)
    r = db.one("select state from park_state where mode=%s", (mode,))
    return (r or {}).get("state") or {}


def set_auto(db, mode, on):
    st = dict(_state(db, mode), auto=bool(on))
    db.x("insert into park_state (mode, state) values (%s,%s) on conflict (mode) do update set state=excluded.state", (mode, Jsonb(st)))
    return {"auto": bool(on)}


def auto(db, mode):
    return bool(_state(db, mode).get("auto", True))


# ---------------------------------------------------------------- 买方（机器人厂）：采购单送到兄弟厂
def send_order(db, mode, x, plant):
    """一行批次（已下单、采购单已进 ERPNext）送到兄弟厂。成功返回对方的订单号；连不上抛 ConnectionError，对方不接抛 ValueError"""
    from hub import kpi
    lead = int((F.SUPPLIERS.get(_cat_of(x["item"])) or {}).get("lead") or 10)
    need = x["promised"] or kpi.add_working_days(dt.datetime.now(kpi.TZ).date(), lead)
    r = _post(plant, "/api/park/orders", {"from_plant": me(), "from_name": my_name(), "ref": str(x["id"]), "po": x["po"],
                                          "item": x["item"], "qty": float(x["qty"]), "need_by": str(need), "mode": mode})
    return r


def _cat_of(item):
    return (F.ITEMS.get(item) or [None] * 5)[4]


def receive_shipment(db, body):
    """兄弟厂发货回传：这一批变成在途（运输 1 天），批号、出厂编号记下；晚于承诺的天数按教学时间算"""
    from hub import supply as SP
    init(db)
    mode = body.get("mode") or "teach"
    x = db.one("select * from lot where mode=%s and id=%s", (mode, int(body["ref"])))
    if x is None:
        raise KeyError(body["ref"])
    if x["status"] not in ("ordered",):
        return {"ok": True, "already": x["status"]}
    now = dt.datetime.now(dt.timezone.utc)
    prof = db.one("select lead_days from supplier_profile where mode=%s and supplier=%s", (mode, x["supplier"])) or {"lead_days": 10}
    deadline = x["ordered_at"] + dt.timedelta(seconds=int(prof["lead_days"]) * SP.DAY_S)
    late = max(0, -(-int((now - deadline).total_seconds()) // SP.DAY_S)) if now > deadline else 0
    lot = str(body.get("lot") or "")[:40] or "L{}-{:04d}".format(now.strftime("%y%m%d"), x["id"])
    park = dict(x["park"] or {}, state="shipped", so=body.get("so"), serials=list(body.get("serials") or [])[:200], shipped_at=now.isoformat())
    db.x("update lot set status='transit', lot=%s, due_at=%s, late_days=%s, park=%s, note=coalesce(note,'') || %s where id=%s",
         (lot, now + dt.timedelta(seconds=SP.DAY_S), late, Jsonb(park), "；{} 发货（订单 {}）".format(x["supplier"].split(" ")[0], body.get("so") or "—"),
          x["id"]))
    return {"ok": True, "lot": lot}


def ship_or_send(H, mode, x, now, rng, sim):
    """supply.tick 对“已下单”的一行调用：兄弟厂的单送过去（之后等发货回传）；连不上或对方不接，按外部供应商发货。
    返回 True 表示这一行已经处理（送到对方或已在等），False 表示交回 supply 按外部供应商处理"""
    from hub import supply as SP
    db = H.db
    plant = park_of(_cat_of(x["item"]))
    if not plant:
        return False
    p = x.get("park") or {}
    if p.get("state") in ("sent", "shipped"):
        return True
    if p.get("state") == "fallback":
        return False
    try:
        r = send_order(db, mode, x, plant)
        db.x("update lot set park=%s, note=coalesce(note,'') || %s where id=%s",
             (Jsonb({"plant": plant, "state": "sent", "order": r.get("id"), "sent_at": now.isoformat()}),
              "；采购单已送到{}（工业园订单 {}）".format(_peer_name(x), r.get("id")), x["id"]))
        return True
    except (ConnectionError, ValueError) as e:
        why = "{}未连通".format(_peer_name(x)) if isinstance(e, ConnectionError) else "{}不接：{}".format(_peer_name(x), e)
        log.warning("工业园下单没送到 %s：%s", plant, e)
        db.x("update lot set park=%s, note=coalesce(note,'') || %s where id=%s",
             (Jsonb({"plant": plant, "state": "fallback", "why": str(e)[:200]}), "；{}，按外部供应商处理".format(why), x["id"]))
        SP._ship(db, mode, dict(x), now, rng, sim)
        return True


def _peer_name(x):
    return x["supplier"].split(" ")[0]


# ---------------------------------------------------------------- 卖方（减速器厂）：接单、下达、发货
def receive_order(db, body):
    init(db)
    mode = body.get("mode") or "teach"
    if mode != "teach":
        raise ValueError("工业园只连教学模式")
    item = str(body.get("item") or "")
    if item not in F.PRODUCTS:
        raise ValueError("本厂不接 {}（可接单的成品：{}）".format(item, "、".join(F.PRODUCTS)))
    qty = float(body.get("qty") or 0)
    if qty <= 0 or qty > 1000:
        raise ValueError("数量不对：{}".format(qty))
    need = dt.date.fromisoformat(str(body.get("need_by"))[:10]) if body.get("need_by") else None
    r = db.one("insert into park_order (mode, from_plant, from_name, ref, po, item, qty, need_by) values (%s,%s,%s,%s,%s,%s,%s,%s) "
               "on conflict (from_plant, ref) do update set po=coalesce(excluded.po, park_order.po) returning id, status",
               (mode, str(body["from_plant"])[:60], str(body.get("from_name") or body["from_plant"])[:140], str(body["ref"])[:40],
                body.get("po"), item, qty, need))
    return {"id": r["id"], "status": r["status"]}


def accept(H, mode, oid, who):
    """接单：按这张订单算料，订单、工单、请购单写进 ERPNext（与计划员在“订单与计划”提交的一样）"""
    from hub import mrp
    from hub.ai import _order_title
    db = H.db
    init(db)
    o = db.one("select * from park_order where id=%s and mode=%s", (oid, mode))
    if o is None:
        raise KeyError(oid)
    if o["status"] != "pending":
        raise ValueError("这张单已经{}".format(STATUS.get(o["status"], o["status"])))
    from hub import kpi
    today = dt.datetime.now(kpi.TZ).date()
    due = max(o["need_by"] or today, kpi.add_working_days(today, 1))
    pv = mrp.plan_order(db, o["from_name"], o["item"], int(o["qty"]), due.isoformat(), mode)
    pv["sales_order"]["new_customer"] = True
    pv["park"] = {"order": o["id"], "from_plant": o["from_plant"], "po": o["po"]}
    pid = H.ai.propose("create_order_and_plan", pv, mode, who, "工业园：" + _order_title(pv), source="park", role="planner")
    H.ai.decide(pid, who, True, role="planner")
    db.x("update park_order set status='accepted', proposal_id=%s, accepted_by=%s, accepted_at=now() where id=%s", (pid, who, oid))
    return {"id": oid, "proposal_id": pid, "work_orders": len(pv["work_orders"]), "material_requests": len(pv["material_requests"])}


def _created(db, pid):
    from hub import finance as FN
    p = FN._proposal(db, pid)
    if not p:
        return None, []
    return p, [c for c in (p.get("result") or {}).get("created", [])]


def _progress(H, mode, o, auto_mode):
    """接了单：等 ERPNext 建好订单和工单；自动接单的由平台下达车间、开工（学生接的单由学生自己下达）"""
    db = H.db
    p, created = _created(db, o["proposal_id"])
    if not p or p["status"] in ("pending", "confirmed"):
        return
    if p["status"] != "executed":
        db.x("update park_order set status='failed', note=%s where id=%s", (json.dumps(p.get("result"), ensure_ascii=False)[:300], o["id"]))
        return
    so = next((c[1] for c in created if c[0] == "Sales Order"), None)
    wos = [c[1] for c in created if c[0] == "Work Order"]
    sent = 0
    if auto_mode and o["accepted_by"] and "模拟器" in o["accepted_by"]:
        import time
        for wo in wos:
            try:
                ds = H.mes.release(wo, mode, "计划员（教学模拟器）")
                time.sleep(0.3)
                for d in ds:
                    H.mes.command(d["unit"], "start", mode, "计划员（教学模拟器）", wo, d["operation"])
                sent += 1
            except (KeyError, ValueError):
                return                                    # 工单快照还没回来：下一轮再下达
    db.x("update park_order set status='released', so=%s, work_orders=%s, note=%s where id=%s",
         (so, Jsonb(wos), "平台下达 {} 张工单".format(sent) if sent else None, o["id"]))


def _ship(H, mode, o, now):
    """订单的工单都做完了：发货回传买方"""
    from hub import finance as FN
    db = H.db
    if o["work_orders"]:
        done = {so["data"]["name"] for so, _ in FN.ready_orders(db, mode, real_only=True)}
        if o["so"] not in done:
            return False
    n = int(float(o["qty"]))
    tag = (o["so"] or "PK{}".format(o["id"])).split("-")[-1]
    code = "".join(ch for ch in o["item"] if ch.isalnum())
    ship = {"ref": o["ref"], "mode": mode, "so": o["so"], "lot": "{}-{}".format(code, tag), "qty": n,
            "serials": ["{}-{}-{:02d}".format(code, tag, i + 1) for i in range(min(n, 200))], "from_plant": me()}
    try:
        _post(o["from_plant"], "/api/park/shipments", ship)
    except (ConnectionError, ValueError) as e:
        db.x("update park_order set note=%s where id=%s", ("发货回传没送到：{}（下一轮再试）".format(e)[:300], o["id"]))
        return False
    db.x("update park_order set status='shipped', shipped_at=%s, shipment=%s, note=null where id=%s", (now, Jsonb(ship), o["id"]))
    return True


def tick(H, mode, now=None):
    db = H.db
    init(db)
    now = now or dt.datetime.now(dt.timezone.utc)
    out = {"accepted": [], "released": [], "shipped": []}
    rows = db.q("select * from park_order where mode=%s and status in ('pending','accepted','released') order by id", (mode,))
    if not rows:
        return out
    on = auto(db, mode)
    for o in rows:
        try:
            if o["status"] == "pending" and on and (now - o["created_at"]).total_seconds() >= AUTO_S:
                accept(H, mode, o["id"], "计划员（教学模拟器）")
                out["accepted"].append(o["id"])
            elif o["status"] == "accepted":
                _progress(H, mode, o, on)
                out["released"].append(o["id"])
            elif o["status"] == "released" and _ship(H, mode, o, now):
                out["shipped"].append(o["id"])
        except Exception:  # noqa: BLE001
            log.exception("工业园订单 %s", o["id"])
    return out


def orders(db, mode, limit=100):
    init(db)
    return [_row(o) for o in db.q("select * from park_order where mode=%s order by id desc limit %s", (mode, int(limit)))]


def _row(o):
    return {"id": o["id"], "from_plant": o["from_plant"], "from_name": o["from_name"], "po": o["po"], "item": o["item"],
            "qty": float(o["qty"]), "need_by": str(o["need_by"]) if o["need_by"] else None, "status": o["status"],
            "status_label": STATUS.get(o["status"], o["status"]), "so": o["so"], "work_orders": o["work_orders"] or [],
            "accepted_by": o["accepted_by"], "created_at": o["created_at"].isoformat(),
            "shipped_at": o["shipped_at"].isoformat() if o["shipped_at"] else None, "shipment": o["shipment"], "note": o["note"]}


def summary(db, mode):
    """“订单与计划”页：本厂在工业园里的上下游"""
    init(db)
    ps = peers()
    buy = {k: v["name"] for k, v in F.SUPPLIERS.items() if v.get("park")}
    return {"me": me(), "peers": sorted(ps), "key": bool(key()), "auto": auto(db, mode), "suppliers": buy,
            "orders": orders(db, mode, 30)}


# ---------------------------------------------------------------- 接口
def mount(app, H, user_of, who):
    from fastapi import Body, Depends, Header, HTTPException

    def machine(k):
        if not check_key(k):
            raise HTTPException(403, "工业园密钥不对")

    @app.post("/api/park/orders")
    def new_order(body: dict = Body(...), x_wq_park_key: str = Header(default="")):
        machine(x_wq_park_key)
        try:
            return receive_order(H.db, body)
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))

    @app.post("/api/park/shipments")
    def shipment(body: dict = Body(...), x_wq_park_key: str = Header(default="")):
        machine(x_wq_park_key)
        try:
            return receive_shipment(H.db, body)
        except KeyError as e:
            raise HTTPException(404, "没有这一批：{}".format(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/park")
    def park_summary(u=Depends(user_of)):
        out = summary(H.db, u["mode"])
        out["can_accept"] = bool(u.get("teacher")) or u.get("role") in ACCEPT_ROLES
        out["teacher"] = bool(u.get("teacher")) and u["mode"] == "teach"
        return out

    @app.post("/api/park/orders/{oid}/accept")
    def accept_order(oid: int, u=Depends(user_of)):
        if u["mode"] != "teach":
            raise HTTPException(400, "工业园只连教学模式")
        if not (u.get("teacher") or u.get("role") in ACCEPT_ROLES):
            raise HTTPException(403, "接单由计划员或厂长操作")
        try:
            return accept(H, u["mode"], oid, who(u))
        except KeyError:
            raise HTTPException(404, "没有这张单")
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/park/auto")
    def set_auto_accept(body: dict = Body(...), u=Depends(user_of)):
        if not (u.get("teacher") and u["mode"] == "teach"):
            raise HTTPException(403, "只有教学模式的老师能开关自动接单")
        return set_auto(H.db, "teach", bool(body.get("on")))
