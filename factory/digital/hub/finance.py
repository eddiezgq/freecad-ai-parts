# -*- coding: utf-8 -*-
"""经营与财务（第 18 轮 E7）：发票与收付款（ERPNext）、应收应付与账龄、信用、现金流预测、订单毛利、经营目标指标树、预算；
催款、信用冻结 / 放行、付款（或推迟）、调整预算；教学模拟器（客户会晚付）。

- 销售发票、采购发票、收付款以 ERPNext 为准（Sales Invoice、Purchase Invoice、Payment Entry），平台经提议 → 桥接写入；
  invoice 表记平台这边的跟踪（到期、催款、模拟器抽的晚付天数）。
- 订单做完（这张订单的工单全部完工）就开票：教学模式自动确认；生产模式只起草提议，由会计确认。
- 账期按“账期日”算：教学模式 1 天 = 真实 2 分钟（和供应链一样），生产模式就是 1 天。
- 毛利：收入（订单单价）− 料（BOM 标准用量 × 单价）− 工（输出轴用车间实测的工时 × 折旧和人工费率，其余零件、装配按标准）
  − 电（输出轴按实测运行时间 × 运行功率 × 电价，其余按标准）− 废品 − 采纳过的动作费用（急单、加班、外协、加急）− 保修。
- 指标树里的指标直接取态势卡已经记下的数（ont_metric_daily），不另算。预算按工厂时间的月份。"""
import datetime as dt
import logging
import random

from psycopg.types.json import Jsonb

from factory import data as F
from wqbus import UNITS

log = logging.getLogger("finance")

SCHEMA = """
create table if not exists objective (
    mode      text not null,
    code      text not null,
    name      text not null,
    domain    text not null,
    metric    text not null,
    target    double precision not null,
    direction text not null,                -- ge 不低于 / le 不高于
    unit      text,
    owner     text,
    primary key (mode, code)
);
create table if not exists budget (
    mode    text not null,
    month   text not null,
    center  text not null,
    amount  double precision not null,
    set_by  text,
    set_at  timestamptz not null default now(),
    primary key (mode, month, center)
);
create table if not exists order_margin (
    mode        text not null,
    sales_order text not null,
    customer    text,
    item        text,
    qty         double precision,
    revenue     double precision,
    cost        jsonb,
    margin      double precision,
    at          timestamptz not null default now(),
    primary key (mode, sales_order)
);
create table if not exists credit (
    mode      text not null,
    customer  text not null,
    limit_amt double precision not null,
    hold      boolean not null default false,
    hold_by   text,
    hold_at   timestamptz,
    primary key (mode, customer)
);
create table if not exists invoice (
    id          bigserial primary key,
    mode        text not null,
    kind        text not null,                -- ar 应收（销售发票）/ ap 应付（采购发票）
    doc         text,                         -- ERPNext 发票号（期初的没有）
    party       text not null,
    ref         text,                         -- 销售订单 / 收货单
    lot_id      bigint,
    amount      double precision not null,
    outstanding double precision not null,
    issued_at   timestamptz not null default now(),
    due_at      timestamptz not null,
    pay_at      timestamptz,                  -- 教学模拟器：客户打算哪天付
    paid_at     timestamptz,
    status      text not null default 'draft', -- draft 待开票 / open 未付 / paying 付款中 / paid 已付 / failed 开票失败 / held 冻结待放行
    proposal_id text,
    pay_pid     text,
    opening     boolean not null default false,
    dunned_at   timestamptz,
    dunned_n    integer not null default 0,
    no_pay      boolean not null default false,
    note        text
);
create index if not exists invoice_mode on invoice (mode, kind, status);
create table if not exists finance_sim (
    mode    text primary key,
    state   jsonb not null default '{}'::jsonb
);
"""

TERMS_DAYS = 30                  # 客户付款条件、供应商付款条件（天）
DAY_S_TEACH = 120                # 教学模式：账期的 1 天 = 真实 2 分钟
LATE = {F.DEMO_CUSTOMERS[0]: (0, 3), F.DEMO_CUSTOMERS[1]: (3, 12), F.DEMO_CUSTOMERS[2]: (10, 30)}      # 客户付款习惯：晚付天数范围（教学模拟器）
CREDIT = {F.DEMO_CUSTOMERS[0]: 40000.0, F.DEMO_CUSTOMERS[1]: 30000.0, F.DEMO_CUSTOMERS[2]: 25000.0}
DEFAULT_CREDIT = 30000.0
DUN_PAY_DAYS = 3                 # 催款后几天内付
OBJECTIVES = [
    # code, 名称, 领域, 指标, 目标, 方向, 单位
    ("O1", "准时交付", "sales", "on_time", 0.95, "ge", "pct"),
    ("O2", "毛利率", "finance", "gross_margin", 0.25, "ge", "pct"),
    ("O3", "一次合格率", "quality", "fpy", 0.97, "ge", "pct"),
    ("O4", "设备综合效率 OEE", "production", "oee", 0.75, "ge", "pct"),
    ("O5", "空转电量占比", "energy", "idle_share", 0.20, "le", "pct"),
    ("O6", "重大隐患", "ehs", "major_open", 0, "le", "int"),
    ("O7", "应收周转天数 DSO", "finance", "dso", 45, "le", "num"),
]
CENTERS = {"labor": "生产人工与折旧", "material": "采购料", "energy": "能源", "maintenance": "维修保养", "quality": "质量损失", "service": "售后服务",
           "admin": "管理费用"}
BUDGET = {"labor": 30000.0, "material": 60000.0, "energy": 6000.0, "maintenance": 3000.0, "quality": 2000.0, "service": 4000.0, "admin": 8000.0}
PARAMS = {"opening_cash": 60000.0, "weekly_expense": 8000.0}
STATUS = {"draft": "待开票", "open": "未付", "paying": "付款中", "paid": "已付", "failed": "开票失败", "held": "冻结待放行"}
ACT_TYPES = ("overtime", "expedite", "outsource", "urgent_purchase", "overtime_assign", "purchase_order", "alt_supplier")


def init(db):
    db.x(SCHEMA)


def _state(db, mode):
    init(db)
    r = db.one("select state from finance_sim where mode=%s", (mode,))
    return (r or {}).get("state") or {}


def _patch(db, mode, d):
    init(db)
    db.x("insert into finance_sim (mode, state) values (%s,%s) on conflict (mode) do update set state=finance_sim.state || excluded.state", (mode, Jsonb(d)))


def day_s(mode):
    return DAY_S_TEACH if mode == "teach" else 86400


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def days_between(mode, a, b):
    return (b - a).total_seconds() / day_s(mode)


def factory_now(db, mode):
    from hub import people as PE
    return PE.factory_now(db, mode)


def sim_on(db, mode):
    """教学模拟器（客户会晚付）：教学模式默认开；情景重载后关；生产模式不模拟"""
    if mode != "teach":
        return False
    st = _state(db, mode)
    return bool(st["sim"]) if "sim" in st else True


def set_sim(db, mode, on):
    _patch(db, mode, {"sim": bool(on)})
    return {"sim": bool(on)}


def params(db, mode):
    st = _state(db, mode)
    return dict(PARAMS, **{k: float(v) for k, v in (st.get("params") or {}).items() if k in PARAMS})


# ---------------------------------------------------------------- 初始化
def month_of(t):
    from hub import kpi
    return t.astimezone(kpi.TZ).strftime("%Y-%m")


def seed(db, mode, now=None):
    init(db)
    now = now or now_utc()
    if not db.one("select 1 as x from objective where mode=%s limit 1", (mode,)):
        for code, name, dom, met, tgt, d, u in OBJECTIVES:
            db.x("insert into objective (mode, code, name, domain, metric, target, direction, unit, owner) values (%s,%s,%s,%s,%s,%s,%s,%s,'厂长') "
                 "on conflict do nothing", (mode, code, name, dom, met, tgt, d, u))
    m = month_of(factory_now(db, mode))
    if not db.one("select 1 as x from budget where mode=%s and month=%s limit 1", (mode, m)):
        for c, a in BUDGET.items():
            db.x("insert into budget (mode, month, center, amount, set_by) values (%s,%s,%s,%s,'系统') on conflict do nothing", (mode, m, c, a))
    if not db.one("select 1 as x from credit where mode=%s limit 1", (mode,)):
        for c in F.DEMO_CUSTOMERS:
            db.x("insert into credit (mode, customer, limit_amt) values (%s,%s,%s) on conflict do nothing", (mode, c, CREDIT.get(c, DEFAULT_CREDIT)))
    st = _state(db, mode)
    if "since" not in st:
        _patch(db, mode, {"since": now.isoformat()})
        if mode == "teach":
            opening(db, mode, now)
    return True


def opening(db, mode, now=None):
    """教学模式的期初应收（平台里的，ERPNext 没有）：三个客户各有一笔，峰顶搅拌机那笔已经逾期 5 天"""
    now = now or now_utc()
    if db.one("select 1 as x from invoice where mode=%s and opening limit 1", (mode,)):
        return
    for c, qty, age in ((F.DEMO_CUSTOMERS[0], 6, 10), (F.DEMO_CUSTOMERS[1], 4, TERMS_DAYS + 5), (F.DEMO_CUSTOMERS[2], 8, 20)):
        issued = now - dt.timedelta(seconds=age * day_s(mode))
        amt = qty * F.FG_SELLING_PRICE
        db.x("insert into invoice (mode, kind, party, ref, amount, outstanding, issued_at, due_at, status, opening, note) "
             "values (%s,'ar',%s,'期初',%s,%s,%s,%s,'open',true,'期初应收（教学情景）')",
             (mode, c, amt, amt, issued, issued + dt.timedelta(seconds=TERMS_DAYS * day_s(mode))))


def reset(db, mode):
    """情景重置：发票、毛利清空，期初应收重建；预算、目标、信用回到默认；模拟器关闭（老师开始实验后打开）"""
    init(db)
    for t in ("invoice", "order_margin", "credit", "budget", "objective", "finance_sim"):
        db.x("delete from {} where mode=%s".format(t), (mode,))
    _patch(db, mode, {"sim": False})
    seed(db, mode)


# ---------------------------------------------------------------- 订单、工单
def _so_amount(d):
    return round(sum(float(i.get("qty") or 0) * float(i.get("rate") or (F.FG_SELLING_PRICE if i.get("item_code") == "WQR-105" else 0))
                     for i in d.get("items") or []), 2)


def sales_orders(db, mode):
    return {m["data"]["name"]: m for m in db.erp_docs("Sales Order", mode) if m["data"].get("docstatus") == 1}


def wo_by_so(db, mode):
    out = {}
    for m in db.erp_docs("Work Order", mode):
        d = m["data"]
        if d.get("sales_order") and d.get("docstatus", 1) != 2:
            out.setdefault(d["sales_order"], []).append(m)
    return out


def _ts(m):
    t = m.get("ts")
    if isinstance(t, str):
        return dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    return t


def _pseudo_so(name, ws):
    """订单本身不在 ERPNext 快照里（情景里早先的订单）：按它的工单估一张（成品 WQR-105，件数 = 工单件数，标准售价）"""
    qty = sum(float(w["data"].get("qty") or 0) for w in ws)
    return {"data": {"name": name, "customer": None, "items": [{"item_code": "WQR-105", "qty": qty, "rate": F.FG_SELLING_PRICE}], "pseudo": True},
            "ts": max(_ts(w) for w in ws)}


def so_doc(db, mode, name):
    so = sales_orders(db, mode).get(name)
    if so is None:
        ws = wo_by_so(db, mode).get(name)
        if ws:
            return _pseudo_so(name, ws)
    return so


def _shop_done(db, mode):
    """车间里最后一道工序做完的工单 → 时刻（以车间为准：ERPNext 里有不合格件时工单可能一直是“进行中”）"""
    return {r["corr"]: r["ts"] for r in db.q(
        "select corr, max(ts) as ts from bus_message where mode=%s and type='machine.event' and payload->'data'->>'event'='op_complete' "
        "and (payload->'data'->>'last_op')::boolean group by corr", (mode,)) if r["corr"]}


def ready_orders(db, mode, real_only=False):
    """工单全部完工的订单：[(订单, 完工时刻)]；real_only：只要 ERPNext 里有的订单（开票用）。
    完工 = ERPNext 里工单已完成，或者车间最后一道工序已经做完"""
    sos, wos = sales_orders(db, mode), wo_by_so(db, mode)
    shop = _shop_done(db, mode)
    out = []
    for name, ws in wos.items():
        if not ws or not all(w["data"].get("status") == "Completed" or w["data"]["name"] in shop for w in ws):
            continue
        for w in ws:
            if w["data"]["name"] in shop and (w["data"].get("status") != "Completed" or _ts(w) < shop[w["data"]["name"]]):
                w["ts"] = shop[w["data"]["name"]]
        if name in sos and real_only and str(sos[name].get("source") or "").startswith("demo"):
            continue                                  # 情景里的演示订单不在 ERPNext 里，不开票（第 19 轮：之前会开票失败）
        if name in sos:
            out.append((sos[name], max(_ts(w) for w in ws)))
        elif not real_only:
            out.append((_pseudo_so(name, ws), max(_ts(w) for w in ws)))
    return out


# ---------------------------------------------------------------- 发票
def _erp_name(db, pid, doctype):
    from hub import supply as SP
    return SP._erp_name(db, pid, doctype)


def _proposal(db, pid):
    import json
    p = db.one("select status, result from ai_proposal where proposal_id=%s", (pid,)) if pid else None
    if p and isinstance(p.get("result"), str):
        try:
            p = dict(p, result=json.loads(p["result"]))
        except ValueError:
            p = dict(p, result={"error": p["result"]})
    return p


def invoices(db, mode, kind=None, status=None):
    w, a = ["mode=%s"], [mode]
    if kind:
        w.append("kind=%s")
        a.append(kind)
    if status:
        w.append("status = any(%s)")
        a.append(list(status))
    return db.q("select * from invoice where {} order by id".format(" and ".join(w)), a)


def held(db, mode, customer):
    r = db.one("select hold from credit where mode=%s and customer=%s", (mode, customer))
    return bool(r and r["hold"])


def _late_days(mode, customer, rng):
    a, b = LATE.get(customer, (0, 2))
    return rng.uniform(a, b)


def make_sales_invoice(H, mode, so_msg, who="系统", rng=None, now=None):
    db = H.db
    d = so_msg["data"]
    now = now or now_utc()
    rng = rng or random.Random()
    if db.one("select 1 as x from invoice where mode=%s and kind='ar' and ref=%s and status <> 'failed'", (mode, d["name"])):
        return None
    amt = _so_amount(d)
    due = now + dt.timedelta(seconds=TERMS_DAYS * day_s(mode))
    late = _late_days(mode, d.get("customer"), rng) if sim_on(db, mode) else 0
    if held(db, mode, d.get("customer")):
        r = db.one("insert into invoice (mode, kind, party, ref, amount, outstanding, issued_at, due_at, status, note) values (%s,'ar',%s,%s,%s,%s,%s,%s,'held',%s) "
                   "returning id", (mode, d.get("customer"), d["name"], amt, amt, now, due, "客户信用冻结中：发货开票要厂长放行"))
        return r["id"]
    erp_due = (dt.date.today() + dt.timedelta(days=TERMS_DAYS)).isoformat()
    pid = H.ai.propose("sales_invoice", {"sales_order": d["name"], "due_date": erp_due, "customer": d.get("customer"), "amount": amt},
                       mode, who, "开票：{} {} ${:,.0f}".format(d["name"], str(d.get("customer") or "").split(" ")[0], amt), source="finance")
    if mode == "teach":
        H.ai.decide(pid, who, True)                     # 教学模式自动确认；生产模式等会计在“提议”里确认
    r = db.one("insert into invoice (mode, kind, party, ref, amount, outstanding, issued_at, due_at, pay_at, status, proposal_id) "
               "values (%s,'ar',%s,%s,%s,%s,%s,%s,%s,'draft',%s) returning id",
               (mode, d.get("customer"), d["name"], amt, amt, now, due, due + dt.timedelta(seconds=late * day_s(mode)), pid))
    return r["id"]


def make_purchase_invoice(H, mode, lot, pr, who="系统", now=None):
    db = H.db
    now = now or now_utc()
    if db.one("select 1 as x from invoice where mode=%s and kind='ap' and ref=%s and status <> 'failed'", (mode, pr)):
        return None
    from hub import supply as SP
    qty = float(lot.get("qty_ok") or lot["qty"])
    amt = round(qty * float(lot.get("rate") or SP.price_of(lot["item"])), 2)
    due = now + dt.timedelta(seconds=TERMS_DAYS * day_s(mode))
    pid = H.ai.propose("purchase_invoice", {"purchase_receipt": pr, "lot": lot.get("lot"), "supplier": lot["supplier"], "amount": amt,
                                            "due_date": (dt.date.today() + dt.timedelta(days=TERMS_DAYS)).isoformat()},
                       mode, who, "采购发票：{} {} ${:,.0f}".format(pr, lot["supplier"].split(" ")[0], amt), source="finance")
    if mode == "teach":
        H.ai.decide(pid, who, True)
    r = db.one("insert into invoice (mode, kind, party, ref, lot_id, amount, outstanding, issued_at, due_at, pay_at, status, proposal_id) "
               "values (%s,'ap',%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s) returning id",
               (mode, lot["supplier"], pr, lot["id"], amt, amt, now, due, due, pid))
    return r["id"]


def pay(H, mode, inv_id, who="系统", now=None):
    """收款（客户付了）或付款（付给供应商）：有 ERPNext 发票的走提议，期初的直接记"""
    db = H.db
    now = now or now_utc()
    x = db.one("select * from invoice where id=%s and mode=%s", (inv_id, mode))
    if x is None:
        raise KeyError(inv_id)
    if x["status"] not in ("open",):
        raise ValueError("这张发票{}，不能{}".format(STATUS.get(x["status"]), "收款" if x["kind"] == "ar" else "付款"))
    if not x["doc"]:
        db.x("update invoice set status='paid', outstanding=0, paid_at=%s where id=%s", (now, inv_id))
        return {"id": inv_id, "status": "paid"}
    dtp = "Sales Invoice" if x["kind"] == "ar" else "Purchase Invoice"
    pid = H.ai.propose("payment", {"doctype": dtp, "invoice": x["doc"], "amount": x["outstanding"]}, mode, who,
                       "{} {} ${:,.0f}".format("收款" if x["kind"] == "ar" else "付款", x["doc"], x["outstanding"]), source="finance")
    if mode == "teach" or who != "系统":
        H.ai.decide(pid, who, True)
    db.x("update invoice set status='paying', pay_pid=%s where id=%s", (pid, inv_id))
    return {"id": inv_id, "status": "paying", "proposal_id": pid}


def sync(db, mode, now=None):
    """提议执行了：发票号、已付；ERPNext 发票的未付金额以 ERPNext 为准"""
    now = now or now_utc()
    for x in db.q("select * from invoice where mode=%s and status in ('draft','paying')", (mode,)):
        if x["status"] == "draft":
            p = _proposal(db, x["proposal_id"])
            if p and p["status"] == "executed":
                name = _erp_name(db, x["proposal_id"], "Sales Invoice" if x["kind"] == "ar" else "Purchase Invoice")
                db.x("update invoice set status='open', doc=%s where id=%s", (name, x["id"]))
            elif p and p["status"] in ("failed", "rejected"):
                db.x("update invoice set status='failed', note=%s where id=%s", (str((p.get("result") or {}).get("error") or p["status"])[:300], x["id"]))
        else:
            p = _proposal(db, x["pay_pid"])
            if p and p["status"] == "executed":
                db.x("update invoice set status='paid', outstanding=0, paid_at=%s where id=%s", (now, x["id"]))
            elif p and p["status"] in ("failed", "rejected"):
                db.x("update invoice set status='open', pay_pid=null, note=%s where id=%s", (("付款没成功：" + str((p.get("result") or {}).get("error") or p["status"]))[:300], x["id"]))
    # 生产模式：ERPNext 里会计自己开的发票也收进来；两种模式都按 ERPNext 的未付金额更新
    for dtp, kind, party in (("Sales Invoice", "ar", "customer"), ("Purchase Invoice", "ap", "supplier")):
        known = {r["doc"]: r for r in db.q("select id, doc, status from invoice where mode=%s and kind=%s and doc is not null", (mode, kind))}
        for m in db.erp_docs(dtp, mode):
            d = m["data"]
            if d.get("docstatus") != 1:
                continue
            out = float(d.get("outstanding_amount") if d.get("outstanding_amount") is not None else d.get("grand_total") or 0)
            if d["name"] in known:
                if out <= 0.005 and known[d["name"]]["status"] != "paid":
                    db.x("update invoice set status='paid', outstanding=0, paid_at=coalesce(paid_at, %s) where id=%s", (now, known[d["name"]]["id"]))
                elif out > 0.005:
                    db.x("update invoice set outstanding=%s where id=%s and status in ('open','paying')", (out, known[d["name"]]["id"]))
            elif mode != "teach":
                due = dt.datetime.fromisoformat(str(d.get("due_date") or d.get("posting_date"))[:10]).replace(tzinfo=dt.timezone.utc)
                ref = (d.get("sales_orders") or d.get("purchase_receipts") or [None])[0]
                db.x("insert into invoice (mode, kind, doc, party, ref, amount, outstanding, issued_at, due_at, status) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (mode, kind, d["name"], d.get(party), ref, float(d.get("grand_total") or 0), out, _ts(m), due, "paid" if out <= 0.005 else "open"))


def tick(H, mode, now=None, rng=None):
    """订单做完开票、收货开采购发票、同步 ERPNext；教学模拟器：客户按习惯付款（催过的几天内付）、应付到期由出纳（模拟器）付"""
    db = H.db
    now = now or now_utc()
    rng = rng or random.Random()
    seed(db, mode, now)
    out = {"ar": [], "ap": [], "paid": [], "pay": []}
    st = _state(db, mode)
    since = dt.datetime.fromisoformat(st["since"]) if st.get("since") else now
    for so, done_at in ready_orders(db, mode, real_only=True):
        if done_at and done_at >= since:
            r = make_sales_invoice(H, mode, so, "开票员（教学模拟器）" if mode == "teach" else "系统", rng, now)
            if r:
                out["ar"].append(r)
    # 冻结的客户放行了：补开票
    for x in db.q("select * from invoice where mode=%s and status='held'", (mode,)):
        if not held(db, mode, x["party"]):
            db.x("delete from invoice where id=%s", (x["id"],))
            so = sales_orders(db, mode).get(x["ref"])
            if so:
                out["ar"].append(make_sales_invoice(H, mode, so, "开票员（教学模拟器）" if mode == "teach" else "系统", rng, now))
    try:
        for lot in db.q("select * from lot where mode=%s and status='accepted' and receipt_pid is not null and received_at >= %s", (mode, since)):
            pr = _erp_name(db, lot["receipt_pid"], "Purchase Receipt")
            if pr:
                r = make_purchase_invoice(H, mode, lot, pr, "会计（教学模拟器）" if mode == "teach" else "系统", now)
                if r:
                    out["ap"].append(r)
    except Exception:  # noqa: BLE001
        log.exception("采购发票")
    sync(db, mode, now)
    if mode != "teach":
        return out
    sim = sim_on(db, mode)
    for x in invoices(db, mode, "ar", ("open",)):
        if x["no_pay"] and not x["dunned_at"]:
            continue
        when = x["pay_at"] or x["due_at"]
        if not sim:
            when = x["due_at"]
        if x["dunned_at"]:
            when = min(when, x["dunned_at"] + dt.timedelta(seconds=DUN_PAY_DAYS * day_s(mode)))
        if now >= when:
            try:
                out["paid"].append(pay(H, mode, x["id"], "客户（教学模拟器）", now))
            except (ValueError, KeyError):
                pass
    for x in invoices(db, mode, "ap", ("open",)):
        if now >= (x["pay_at"] or x["due_at"]):
            try:
                out["pay"].append(pay(H, mode, x["id"], "出纳（教学模拟器）", now))
            except (ValueError, KeyError):
                pass
    return out


# ---------------------------------------------------------------- 应收应付、信用、现金流
BUCKETS = [("current", "未到期"), ("d30", "逾期 1–30 天"), ("d60", "逾期 31–60 天"), ("d60p", "逾期 60 天以上")]


def overdue_days(mode, x, now=None):
    now = now or now_utc()
    return max(0.0, days_between(mode, x["due_at"], now))


def _bucket(d):
    return "current" if d <= 0 else ("d30" if d <= 30 else ("d60" if d <= 60 else "d60p"))


def ar(db, mode, now=None):
    now = now or now_utc()
    seed(db, mode, now)
    rows = []
    aging = {k: 0.0 for k, _ in BUCKETS}
    for x in invoices(db, mode, "ar", ("open", "paying", "draft", "held")):
        od = overdue_days(mode, x, now)
        aging[_bucket(od)] += float(x["outstanding"])
        rows.append({"id": x["id"], "doc": x["doc"], "party": x["party"], "ref": x["ref"], "amount": x["amount"], "outstanding": x["outstanding"],
                     "issued_at": x["issued_at"].isoformat(), "due_at": x["due_at"].isoformat(), "overdue_days": round(od, 1),
                     "status": x["status"], "status_label": STATUS[x["status"]], "opening": x["opening"],
                     "dunned_n": x["dunned_n"], "dunned_at": x["dunned_at"].isoformat() if x["dunned_at"] else None})
    return {"invoices": rows, "aging": {k: round(v, 2) for k, v in aging.items()}, "buckets": dict(BUCKETS),
            "total": round(sum(aging.values()), 2), "overdue": round(sum(v for k, v in aging.items() if k != "current"), 2)}


def ap(db, mode, now=None):
    now = now or now_utc()
    rows = []
    for x in invoices(db, mode, "ap", ("open", "paying", "draft")):
        rows.append({"id": x["id"], "doc": x["doc"], "party": x["party"], "ref": x["ref"], "amount": x["amount"], "outstanding": x["outstanding"],
                     "due_at": x["due_at"].isoformat(), "days_left": round(-days_between(mode, x["due_at"], now) if x["due_at"] > now else
                                                                          -overdue_days(mode, x, now), 1),
                     "pay_at": (x["pay_at"] or x["due_at"]).isoformat(), "status": x["status"], "status_label": STATUS[x["status"]]})
    return {"invoices": rows, "total": round(sum(float(r["outstanding"]) for r in rows), 2)}


def open_orders(db, mode):
    """在做、还没开票的订单金额（按客户）"""
    billed = {r["ref"] for r in db.q("select ref from invoice where mode=%s and kind='ar' and status <> 'failed'", (mode,))}
    out = {}
    for name, m in sales_orders(db, mode).items():
        d = m["data"]
        if name in billed or float(d.get("per_delivered") or 0) >= 100 or float(d.get("per_billed") or 0) >= 100:
            continue
        if d.get("status") in ("Completed", "Closed", "Cancelled"):
            continue
        out.setdefault(d.get("customer"), []).append({"sales_order": name, "amount": _so_amount(d)})
    return out


def credit(db, mode, now=None):
    seed(db, mode, now)
    a = ar(db, mode, now)
    oo = open_orders(db, mode)
    out = []
    custs = {r["customer"]: r for r in db.q("select * from credit where mode=%s", (mode,))}
    for c in sorted(set(custs) | {x["party"] for x in a["invoices"]} | {k for k in oo if k}):
        bal = sum(float(x["outstanding"]) for x in a["invoices"] if x["party"] == c)
        od = [x for x in a["invoices"] if x["party"] == c and x["overdue_days"] > 0]
        orders = sum(o["amount"] for o in oo.get(c, []))
        lim = float(custs[c]["limit_amt"]) if c in custs else DEFAULT_CREDIT
        out.append({"customer": c, "limit": lim, "balance": round(bal, 2), "open_orders": round(orders, 2), "exposure": round(bal + orders, 2),
                    "used": round((bal + orders) / lim, 3) if lim else None, "hold": bool(custs.get(c, {}).get("hold")),
                    "overdue": round(sum(float(x["outstanding"]) for x in od), 2), "max_overdue_days": max([x["overdue_days"] for x in od] or [0]),
                    "orders": oo.get(c, [])})
    return out


def cash_now(db, mode):
    p = params(db, mode)
    got = db.one("select coalesce(sum(amount),0) as s from invoice where mode=%s and kind='ar' and status='paid' and not opening", (mode,))["s"]
    got_open = db.one("select coalesce(sum(amount),0) as s from invoice where mode=%s and kind='ar' and status='paid' and opening", (mode,))["s"]
    paid = db.one("select coalesce(sum(amount),0) as s from invoice where mode=%s and kind='ap' and status='paid'", (mode,))["s"]
    return round(float(p["opening_cash"]) + float(got) + float(got_open) - float(paid), 2)


def cashflow(db, mode, weeks=8, now=None, assume=None):
    """未来 weeks 周（账期周）：期初现金 + 预计收款（按到期日 + 这个客户平时晚几天；逾期的按下周）− 应付到期 − 每周固定开支。
    assume：{发票 id: 预计收款时刻}（方案推演用）"""
    now = now or now_utc()
    p = params(db, mode)
    w = 7 * day_s(mode)
    cash = cash_now(db, mode)
    rows = []
    inflow = [0.0] * weeks
    outflow = [0.0] * weeks
    for x in invoices(db, mode, "ar", ("open", "paying", "draft")):
        when = (assume or {}).get(x["id"])
        if when is None:
            if x["no_pay"] and not x["dunned_at"]:
                continue                                          # 不催就不付
            lo, hi = LATE.get(x["party"], (0, 2))
            when = x["due_at"] + dt.timedelta(seconds=(lo + hi) / 2 * day_s(mode))
            if x["dunned_at"]:
                when = min(when, x["dunned_at"] + dt.timedelta(seconds=DUN_PAY_DAYS * day_s(mode)))
        if when is False:
            continue
        k = max(0, int((when - now).total_seconds() // w))
        if k < weeks:
            inflow[k] += float(x["outstanding"])
    for x in invoices(db, mode, "ap", ("open", "paying", "draft")):
        k = max(0, int(((x["pay_at"] or x["due_at"]) - now).total_seconds() // w))
        if k < weeks:
            outflow[k] += float(x["outstanding"])
    bal = cash
    for i in range(weeks):
        bal = bal + inflow[i] - outflow[i] - float(p["weekly_expense"])
        rows.append({"week": i + 1, "in": round(inflow[i], 2), "out": round(outflow[i] + float(p["weekly_expense"]), 2), "balance": round(bal, 2)})
    low = min(rows, key=lambda r: r["balance"]) if rows else None
    return {"cash": cash, "weeks": rows, "low": low, "weekly_expense": float(p["weekly_expense"]), "day_s": day_s(mode)}


def dso(db, mode, days=30, now=None):
    """应收周转天数 = 应收余额 ÷ 近 days 天日均开票额"""
    now = now or now_utc()
    bal = ar(db, mode, now)["total"]
    since = now - dt.timedelta(seconds=days * day_s(mode))
    sales = db.one("select coalesce(sum(amount),0) as s from invoice where mode=%s and kind='ar' and issued_at >= %s and status <> 'failed'", (mode, since))["s"]
    per_day = float(sales) / days
    return round(bal / per_day, 1) if per_day > 0 else None


# ---------------------------------------------------------------- 订单毛利
def _std(item, memo=None):
    """标准成本（每件）：料（外购件、原材料单价）与加工（各工序标准工时 × 费率：折旧 + 人工、能耗分开）"""
    memo = memo if memo is not None else {}
    if item in memo:
        return memo[item]
    it = F.ITEMS[item]
    if item not in F.BOMS:
        memo[item] = {"material": float(it[3] or 0), "labor": 0.0, "energy": 0.0}
        return memo[item]
    rt, comps = F.BOMS[item]
    out = {"material": 0.0, "labor": 0.0, "energy": 0.0}
    for c, q in comps:
        s = _std(c, memo)
        for k in out:
            out[k] += s[k] * q
    for op, mins in F.ROUTINGS.get(rt, []):
        cap, (dep, lab, en) = F.WORKSTATIONS[F.OPERATIONS[op]]
        div = cap if F.OPERATIONS[op].startswith("热处理") else 1
        out["labor"] += mins / 60 * (dep + lab) / div
        out["energy"] += mins / 60 * en / div
    memo[item] = out
    return out


def _wo_actual(db, mode, wo):
    """输出轴工单的实测：工时 × 折旧和人工费率（含调整、换刀）、运行时间 × 运行功率 × 平价电费；做坏的件数"""
    from hub import mrp
    from sim import energy as SE
    c = mrp.wo_cost(db, wo, mode)
    if not c:
        return None
    labor = energy = 0.0
    price = 0.10
    try:
        from hub import energy as EN
        price = float(EN.params(db, mode)["price"]["flat"])
    except Exception:  # noqa: BLE001
        pass
    for line in c["lines"]:
        ws = F.WORKSTATIONS.get((UNITS.get(line["unit"]) or [None] * 4)[3])
        dep, lab, en = ws[1] if ws else (0, 0, 0)
        labor += (line["cycle_s"] + line["setup_s"] + line["tool_change_s"]) / 3600 * (dep + lab)
        run_kw = SE.POWER.get(line["unit"], (0,))[0]
        energy += line["cycle_s"] / 3600 * run_kw * price / (20 if line["unit"] == "ht-01" else 1)
    bad = db.one("select count(*) as n from ncr where work_order=%s", (wo,))["n"]
    return {"labor": labor, "energy": energy, "parts": c["parts_finished"], "bad": bad, "std_labor": c["std_cost"]}


def margin(db, mode, so_name, store=True):
    so = so_doc(db, mode, so_name)
    if so is None:
        raise KeyError(so_name)
    d = so["data"]
    qty = sum(float(i.get("qty") or 0) for i in d.get("items") or [])
    item = (d.get("items") or [{}])[0].get("item_code") or "WQR-105"
    revenue = _so_amount(d)
    std = _std(item)
    sh = _std("SH-301")
    wos = [w["data"]["name"] for w in wo_by_so(db, mode).get(so_name, [])]
    act = [x for x in (_wo_actual(db, mode, w) for w in wos) if x]
    n_act = sum(x["parts"] for x in act)
    lines = []
    mat = std["material"] * qty
    lines.append({"key": "material", "label": "料", "usd": round(mat, 2), "how": "BOM 标准用量 × 单价"})
    if act and item == "WQR-105":
        labor = (std["labor"] - sh["labor"]) * qty + sum(x["labor"] for x in act) + sh["labor"] * max(0, qty - n_act)
        energy = (std["energy"] - sh["energy"]) * qty + sum(x["energy"] for x in act) + sh["energy"] * max(0, qty - n_act)
        how = "输出轴 {} 件用车间实测（工时、调整、换刀；运行电量），其余零件、装配、跑合按标准".format(n_act)
    else:
        labor, energy = std["labor"] * qty, std["energy"] * qty
        how = "按标准工时"
    lines.append({"key": "labor", "label": "工（折旧 + 人工）", "usd": round(labor, 2), "how": how})
    lines.append({"key": "energy", "label": "电", "usd": round(energy, 2), "how": how})
    bad = sum(x["bad"] for x in act)
    scrap = bad * (sh["material"] + sh["labor"] + sh["energy"])
    lines.append({"key": "scrap", "label": "废品返工", "usd": round(scrap, 2), "how": "不合格输出轴 {} 件 × 标准成本".format(bad)})
    idle, idle_how = _idle(db, mode, wos)
    lines.append({"key": "idle", "label": "空转电（分摊）", "usd": round(idle, 2), "how": idle_how})
    acts = 0.0
    used = []
    from hub import story as ST            # 第 19 轮：情景主线订单——因情景各幕异常采纳的动作，费用全部记到主线订单上（不再分给别的订单）
    story_of = ST.story_anomalies(db, mode)
    since = _state(db, mode).get("since")   # 第 19 轮：只算这次情景（重置以后）的动作——情景里的演示订单每次重置都是同一个单号
    for a in db.q("select id, type, title, trial, params, anomaly_id from action where mode=%s and status in ('done','executing') and type = any(%s) "
                  "and (%s::timestamptz is null or created_at >= %s::timestamptz)", (mode, list(ACT_TYPES), since, since)):
        tr = a["trial"] or {}
        sos = [s["name"] for s in tr.get("sales_orders") or []]
        owner = story_of.get(int(a["anomaly_id"])) if a["anomaly_id"] is not None else None
        if owner:
            hit, share = owner == so_name, float(tr.get("cost_total") or 0)
        else:
            hit = so_name in sos or any(str(v) in wos for v in (a["params"] or {}).values() if isinstance(v, str))
            share = float(tr.get("cost_total") or 0) / max(1, len(sos) or 1)
        if hit:
            acts += share
            used.append({"id": a["id"], "title": a["title"], "usd": round(share, 2)})
    lines.append({"key": "actions", "label": "急单、加班、外协、加急", "usd": round(acts, 2), "how": "采纳并执行的动作费用，按受影响的订单分摊", "actions": used})
    warranty = 0.0
    if wos:                     # 这张订单的轴 → 装进了哪些现场设备 → 保修期内的服务工单
        shafts = [r["s"] for r in db.q("select distinct payload->'data'->>'part_serial' as s from bus_message where mode=%s and type='machine.event' "
                                        "and corr = any(%s) and payload->'data'->>'event'='cycle_end'", (mode, wos)) if r["s"]]
        if shafts and db.one("select to_regclass('service_job') is not null as ok")["ok"] and db.one("select to_regclass('twin') is not null as ok")["ok"]:
            for r in db.q("select j.cost from service_job j join twin t on t.serial=j.serial and t.mode=j.mode where j.mode=%s and j.warranty "
                          "and j.status <> 'cancelled' and t.as_built->'shaft'->>'serial' = any(%s)", (mode, shafts)):
                c = r["cost"] or {}
                warranty += float(c.get("labor") or 0) + float(c.get("travel") or 0) + float(c.get("parts_usd") or 0)
    lines.append({"key": "warranty", "label": "保修", "usd": round(warranty, 2), "how": "这张订单的设备在保修期内的服务费用"})
    cost = sum(x["usd"] for x in lines)
    m = revenue - cost
    out = {"sales_order": so_name, "customer": d.get("customer"), "item": item, "pseudo": bool(d.get("pseudo")), "qty": qty, "revenue": revenue, "lines": lines,
           "cost": round(cost, 2), "margin": round(m, 2), "margin_pct": round(m / revenue, 4) if revenue else None, "work_orders": wos,
           "std_margin_pct": round(1 - (std["material"] + std["labor"] + std["energy"]) / (revenue / qty), 4) if revenue and qty else None}
    if store:
        db.x("insert into order_margin (mode, sales_order, customer, item, qty, revenue, cost, margin) values (%s,%s,%s,%s,%s,%s,%s,%s) "
             "on conflict (mode, sales_order) do update set revenue=excluded.revenue, cost=excluded.cost, margin=excluded.margin, at=now()",
             (mode, so_name, d.get("customer"), item, qty, revenue, Jsonb(out), m))
    return out


def _idle(db, mode, wos):
    """空转电分摊（第 19 轮 J-4）：订单在做期间（工厂时间，第一件开工到最后一件做完），加工过它的设备的空转电量 × 电价，
    按这台设备同期加工的件数分给这张订单（热处理炉保温不算空转）"""
    if not wos:
        return 0.0, "没有工单"
    try:
        from hub import energy as EN
        rows = db.q("select topic, count(*) as n, min(payload->'data'->>'factory_ts') as a, max(payload->'data'->>'factory_ts') as b from bus_message "
                    "where mode=%s and type='machine.event' and corr = any(%s) and payload->'data'->>'event'='cycle_end' group by topic", (mode, list(wos)))
        if not rows:
            return 0.0, "还没开工"
        a, b = min(r["a"] for r in rows), max(r["b"] for r in rows)
        price = EN.params(db, mode)["price"]
        usd, kwh, units = 0.0, 0.0, []
        for r in rows:
            unit = r["topic"].split("/")[3]
            if unit == "ht-01":
                continue
            tot = db.one("select count(*) as n from bus_message where mode=%s and type='machine.event' and topic=%s and payload->'data'->>'event'='cycle_end' "
                         "and payload->'data'->>'factory_ts' between %s and %s", (mode, r["topic"], a, b))["n"] or r["n"]
            share = min(1.0, float(r["n"]) / float(tot))
            for e in db.q("select bucket, sum(coalesce((k->>'idle')::float, 0)) as v from energy_read where mode=%s and meter=%s and ts >= %s and ts < %s "
                          "group by bucket", (mode, "E-" + unit.upper(), a, b)):
                k = float(e["v"] or 0) * share
                kwh += k
                usd += k * float(price.get(e["bucket"] or "flat", price["flat"]))
            units.append(unit)
        return usd, "订单在做期间（工厂时间）{} 台设备的空转电 {:.1f} 度，按件数分摊".format(len(units), kwh)
    except Exception:  # noqa: BLE001
        log.exception("空转电分摊")
        return 0.0, "没有计量数据"


def make_overdue(H, mode, inv_id, days, who="老师"):
    """第 19 轮 J-4：指定的这张发票逾期 days 天（账期日），不催就不付——情景第 8 幕用，逾期的就是主线订单自己的发票"""
    if mode != "teach":
        raise PermissionError("生产模式不模拟")
    db = H.db
    x = db.one("select * from invoice where id=%s and mode=%s", (inv_id, mode))
    if x is None:
        raise KeyError(inv_id)
    if x["status"] in ("paid", "held", "failed"):
        raise ValueError("这张发票现在{}，不能设为逾期".format(STATUS.get(x["status"])))
    now = now_utc()
    due = now - dt.timedelta(seconds=float(days) * day_s(mode))
    db.x("update invoice set issued_at=%s, due_at=%s, pay_at=null, no_pay=true, note=coalesce(note,'') || %s where id=%s",
         (due - dt.timedelta(seconds=TERMS_DAYS * day_s(mode)), due, "；{}：客户压着不付".format(who), inv_id))
    return {"text": "{} 的发票（订单 {}，${:,.0f}）逾期 {:g} 天，不催就不付".format(x["party"].split(" ")[0], x["ref"], x["amount"], float(days)),
            "invoice_id": inv_id}


def margins(db, mode):
    """做完的订单（工单全部完工）的毛利"""
    out = []
    for so, _ in ready_orders(db, mode):
        try:
            out.append(margin(db, mode, so["data"]["name"]))
        except Exception:  # noqa: BLE001
            log.exception("毛利 %s", so["data"].get("name"))
    out.sort(key=lambda x: x["margin_pct"] if x["margin_pct"] is not None else 9)
    return out


def gross_margin(db, mode):
    ms = margins(db, mode)
    rev = sum(m["revenue"] for m in ms)
    return round(sum(m["margin"] for m in ms) / rev, 4) if rev else None


# ---------------------------------------------------------------- 预算
def month_progress(db, mode):
    from hub import kpi
    t = factory_now(db, mode).astimezone(kpi.TZ)
    d0 = t.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    d1 = (d0 + dt.timedelta(days=32)).replace(day=1)
    return t.strftime("%Y-%m"), (t - d0).total_seconds() / (d1 - d0).total_seconds(), d0.astimezone(dt.timezone.utc), d1.astimezone(dt.timezone.utc)


def actuals(db, mode):
    """本月（工厂时间）各成本中心的实际"""
    month, prog, t0, t1 = month_progress(db, mode)
    out = {k: 0.0 for k in CENTERS}
    for r in db.q("select topic, sum((payload->'data'->>'cycle_time_s')::float) as s from bus_message where mode=%s and type='machine.event' "
                  "and payload->'data'->>'event'='cycle_end' and payload->'data'->>'factory_ts' >= %s and payload->'data'->>'factory_ts' < %s group by topic",
                  (mode, t0.isoformat().replace("+00:00", "Z"), t1.isoformat().replace("+00:00", "Z"))):
        unit = r["topic"].split("/")[3]
        ws = F.WORKSTATIONS.get((UNITS.get(unit) or [None] * 4)[3])
        if ws:
            out["labor"] += float(r["s"] or 0) / 3600 * (ws[1][0] + ws[1][1]) / (ws[0] if unit == "ht-01" else 1)
    out["material"] = float(db.one("select coalesce(sum(amount),0) as s from invoice where mode=%s and kind='ap' and status <> 'failed'", (mode,))["s"])
    try:
        from hub import energy as EN
        p = EN.params(db, mode)["price"]
        r = db.q("select bucket, sum(value) as v from energy_read where mode=%s and meter='E-TOTAL' and ts >= %s and ts < %s group by bucket", (mode, t0, t1))
        out["energy"] = sum(float(x["v"]) * float(p.get(x["bucket"] or "flat", p["flat"])) for x in r)
    except Exception:  # noqa: BLE001
        pass
    for kind, types in (("maintenance", ("pm_order", "repair_order", "expedite")), ("service", ("service_batch", "spare_ship"))):
        r = db.one("select coalesce(sum((trial->>'cost_total')::float),0) as s from action where mode=%s and status in ('done','executing') "
                   "and type = any(%s)", (mode, list(types)))
        out[kind] = float(r["s"] or 0)
    try:
        sh = _std("SH-301")
        n = db.one("select count(*) as n from ncr where mode=%s", (mode,))["n"]
        out["quality"] = n * (sh["material"] + sh["labor"] + sh["energy"])
    except Exception:  # noqa: BLE001
        pass
    b = budgets(db, mode, month)
    out["admin"] = b.get("admin", 0) * prog
    return {k: round(v, 2) for k, v in out.items()}


def budgets(db, mode, month=None):
    seed(db, mode)
    month = month or month_progress(db, mode)[0]
    rows = db.q("select center, amount from budget where mode=%s and month=%s", (mode, month))
    if not rows:
        for c, a in BUDGET.items():
            db.x("insert into budget (mode, month, center, amount, set_by) values (%s,%s,%s,%s,'系统') on conflict do nothing", (mode, month, c, a))
        rows = db.q("select center, amount from budget where mode=%s and month=%s", (mode, month))
    return {r["center"]: float(r["amount"]) for r in rows}


def budget_view(db, mode):
    month, prog, _, _ = month_progress(db, mode)
    b = budgets(db, mode, month)
    a = actuals(db, mode)
    rows = []
    for c, name in CENTERS.items():
        should = b.get(c, 0) * prog
        rows.append({"center": c, "name": name, "budget": b.get(c, 0), "actual": a.get(c, 0), "should": round(should, 2),
                     "over": round(a.get(c, 0) - should, 2), "ratio": round(a.get(c, 0) / should, 3) if should > 0 else None})
    return {"month": month, "progress": round(prog, 3), "rows": rows, "total_budget": round(sum(b.values()), 2), "total_actual": round(sum(a.values()), 2)}


# ---------------------------------------------------------------- 经营目标
def objectives(db, mode):
    """指标树：目标 → 指标（取态势卡记下的数）；本月实际 vs 目标、红黄绿、近 7 天"""
    seed(db, mode)
    rows = db.q("select * from objective where mode=%s order by code", (mode,))
    has = db.one("select to_regclass('ont_metric_daily') is not null as ok")["ok"]
    out = []
    for o in rows:
        hist = [(r["day"].isoformat(), float(r["value"])) for r in db.q(
            "select day, value from ont_metric_daily where mode=%s and domain=%s and metric=%s order by day desc limit 7", (mode, o["domain"], o["metric"]))] if has else []
        v = hist[0][1] if hist else None
        out.append(dict(o, value=v, tone=_tone(o, v), history=list(reversed(hist)), red_days=sum(1 for _, x in hist if _tone(o, x) == "bad")))
    return out


def _tone(o, v):
    if v is None:
        return "mute"
    t = float(o["target"])
    if o["direction"] == "ge":
        return "good" if v >= t else ("warn" if v >= t * 0.95 else "bad")
    if t == 0:
        return "good" if v <= 0 else "bad"
    return "good" if v <= t else ("warn" if v <= t * 1.1 else "bad")


def set_objective(db, mode, code, target, who):
    r = db.one("select * from objective where mode=%s and code=%s", (mode, code))
    if r is None:
        raise KeyError(code)
    db.x("update objective set target=%s, owner=%s where mode=%s and code=%s", (float(target), who, mode, code))
    return objectives(db, mode)


def kpis(db, mode, now=None):
    seed(db, mode, now)
    a = ar(db, mode, now)
    bv = budget_view(db, mode)
    over = [r for r in bv["rows"] if r["ratio"] and r["ratio"] > 1.1]
    return {"gross_margin": gross_margin(db, mode), "ar_total": a["total"], "ar_overdue": a["overdue"], "dso": dso(db, mode, now=now),
            "budget_used": round(bv["total_actual"] / bv["total_budget"], 3) if bv["total_budget"] else None, "progress": bv["progress"],
            "over_centers": [r["center"] for r in over], "cash": cash_now(db, mode), "sim": sim_on(db, mode)}


# ---------------------------------------------------------------- 方案
def _res(cost=0.0, costs=None, checks=None, cash=None):
    return {"sales_orders": [], "cost_total": round(cost, 2), "costs": costs or [], "overtime_min": 0, "checks": checks or [], "ok": True, "cash": cash}


def options(db, mode, a, now=None):
    now = now or now_utc()
    v = (a.get("detail") or {}).get("values") or {}
    rule = a["rule"]
    if rule == "F2":
        x = db.one("select * from invoice where id=%s and mode=%s", (v.get("invoice_id"), mode))
        if x is None:
            return {"options": [], "affected": [], "reason": "这张发票已经没有了", "recommended": None}
        lo, hi = LATE.get(x["party"], (0, 2))
        late_pay = now + dt.timedelta(seconds=max(1, (lo + hi) / 2 - overdue_days(mode, x, now)) * day_s(mode)) if not x["no_pay"] else False
        plans = [("none", "不处理（对照）", late_pay, [], "客户按自己的习惯付；{}".format("这一笔客户压着不付" if x["no_pay"] else "平时晚 {:g}–{:g} 天".format(lo, hi))),
                 ("dunning", "发催款函", min(late_pay, now + dt.timedelta(seconds=DUN_PAY_DAYS * day_s(mode))) if late_pay else now + dt.timedelta(seconds=DUN_PAY_DAYS * day_s(mode)),
                  [{"type": "dunning", "invoice_id": x["id"]}], "通常 {} 天内付；不伤和气".format(DUN_PAY_DAYS)),
                 ("hold", "信用冻结（新发货要厂长放行）", min(late_pay, now + dt.timedelta(seconds=DUN_PAY_DAYS * day_s(mode))) if late_pay else now + dt.timedelta(seconds=DUN_PAY_DAYS * day_s(mode)),
                  [{"type": "credit_hold", "customer": x["party"], "hold": True}, {"type": "dunning", "invoice_id": x["id"]}],
                  "催款同时冻结；这个客户在做的订单做完先不发货，可能影响关系")]
    elif rule == "F3":
        c = v.get("customer")
        plans = [("none", "不处理（对照）", None, [], "继续给他发货，欠款可能越来越多"),
                 ("hold", "信用冻结", None, [{"type": "credit_hold", "customer": c, "hold": True}], "新发货要厂长放行"),
                 ("raise", "临时提额 20%", None, [{"type": "credit_hold", "customer": c, "hold": False, "limit": round(float(v.get("limit") or DEFAULT_CREDIT) * 1.2, 2)}],
                  "老客户、订单在做，先提额；要厂长批")]
    elif rule == "F4":
        inv = db.one("select * from invoice where mode=%s and kind='ap' and status='open' order by due_at limit 1", (mode,))
        od = db.one("select id from invoice where mode=%s and kind='ar' and status='open' and due_at < %s order by due_at limit 1", (mode, now))
        plans = [("none", "不处理（对照）", None, [], "按到期日付，现金可能见底"),
                 ("delay", "和供应商商量推迟 7 天付款", None, [{"type": "payment", "invoice_id": inv["id"], "delay_days": 7}] if inv else [],
                  "影响这家供应商对我们的评价，下次可能不给账期"),
                 ("collect", "加快催收逾期应收", None, [{"type": "dunning", "invoice_id": od["id"]}] if od else [], "催最早逾期的一笔")]
    elif rule == "F6":
        c = v.get("center")
        over = float(v.get("over") or 0)
        plans = [("none", "不处理（对照）", None, [], "月底可能超支"),
                 ("budget", "调整预算（+${:,.0f}）".format(over / max(0.05, float(v.get("progress") or 0.5))), None,
                  [{"type": "budget_change", "center": c, "amount": round(float(v.get("budget") or 0) + over / max(0.05, float(v.get("progress") or 0.5)), 2)}],
                  "按现在的进度推到月底；要厂长批")]
        if c == "energy":
            plans[0] = ("none", "不处理（对照）", None, [], "月底可能超支；可以先去处理“空转能耗高”“峰时用电”的异常")
    else:
        return analysis(db, mode, a)
    out = []
    for i, (kind, label, when, changes, note) in enumerate(plans):
        cash = None
        if rule == "F2":
            cf = cashflow(db, mode, now=now, assume={x["id"]: when})
            cash = {"low": cf["low"], "expect": when.isoformat() if when else None, "weeks": cf["weeks"]}
            note = "{}；{}；现金流预测 8 周内最低第 {} 周 ${:,.0f}".format(
                note, "预计 {:.0f} 天后收到 ${:,.0f}".format(max(0, days_between(mode, now, when)), x["outstanding"]) if when else "不催就收不到",
                cf["low"]["week"], cf["low"]["balance"])
        out.append({"key": chr(ord("A") + i), "kind": kind, "label": label, "note": note, "changes": changes, "result": _res(cash=cash),
                    "recommended": False})
    best = {"F2": "dunning", "F3": "hold", "F4": "collect", "F6": "budget"}.get(rule)
    if rule == "F2" and float(v.get("days") or 0) > 30:
        best = "hold"
    for o in out:
        o["recommended"] = o["kind"] == best
    if not any(o["recommended"] for o in out):
        out[0]["recommended"] = True
    rec = next(o for o in out if o["recommended"])
    _patch(db, mode, {"recommended": dict(_state(db, mode).get("recommended") or {}, **{str(a["id"]): rec["kind"]})}) if a.get("id") else None
    reason = {"dunning": "建议 {} 发催款函：逾期不长，先催，通常几天内就付，不影响关系", "hold": "建议 {} 冻结信用：逾期太久或欠得太多，先停发货再谈",
              "collect": "建议 {} 加快催收：先把该收的钱收回来，不动供应商的账期", "budget": "建议 {} 调整预算：按现在的进度推到月底，同时找超支的原因"}.get(
        rec["kind"], "建议 {}").format(rec["key"])
    return {"options": out, "affected": [], "reason": reason, "recommended": rec["key"]}


def analysis(db, mode, a):
    """F5 毛利低、F7 指标偏离：给分解，不推演"""
    v = (a.get("detail") or {}).get("values") or {}
    if a["rule"] == "F5":
        m = margin(db, mode, v.get("sales_order"), store=False)
        top = sorted([x for x in m["lines"] if x["key"] != "material"], key=lambda x: -x["usd"])[:2]
        reason = "毛利率 {:.1%}（标准 {:.1%}）：比标准多花的主要在 {}。改进：报价按实际成本复核；工艺和供应商对症处理".format(
            m["margin_pct"] or 0, m["std_margin_pct"] or 0, "、".join("{} ${:,.0f}".format(x["label"], x["usd"]) for x in top))
    else:
        reason = "指标“{}”连续偏离目标：打开对应领域的异常和推演找原因".format(v.get("name"))
    return {"options": [], "affected": [], "reason": reason, "recommended": None}


# ---------------------------------------------------------------- 动作执行
def exec_dunning(H, mode, p, u):
    db = H.db
    x = db.one("select * from invoice where id=%s and mode=%s", (int(p["invoice_id"]), mode))
    if x is None:
        raise ValueError("没有这张发票")
    if x["kind"] != "ar" or x["status"] not in ("open", "paying"):
        raise ValueError("这张发票{}，不用催".format(STATUS.get(x["status"])))
    db.x("update invoice set dunned_at=now(), dunned_n=dunned_n+1 where id=%s", (x["id"],))
    text = "已催款：{} {} ${:,.0f}，逾期 {:.0f} 天".format(x["party"].split(" ")[0], x["doc"] or "期初", x["outstanding"], overdue_days(mode, x))
    if x["doc"] and H.ai is not None:
        content = "催款：发票 {} 未付 ${:,.2f}，已逾期，请尽快安排付款。（问渠厂情中枢 · {}）".format(x["doc"], x["outstanding"], u.get("name"))
        pid = H.ai.propose("dunning_note", {"invoice": x["doc"], "content": content}, mode, u.get("name"), "催款 " + x["doc"], source="finance")
        H.ai.decide(pid, u.get("name"), True)
        return {"text": text + "（ERPNext 发票上留了催款记录{}）".format("，教学模式不发邮件" if mode == "teach" else ""), "proposal_id": pid}
    return {"text": text + "（{}）".format("教学模式只记录，不发出" if mode == "teach" else "期初应收，请人工联系")}


def exec_credit(H, mode, p, u):
    db = H.db
    c = p["customer"]
    seed(db, mode)
    db.x("insert into credit (mode, customer, limit_amt) values (%s,%s,%s) on conflict do nothing", (mode, c, CREDIT.get(c, DEFAULT_CREDIT)))
    if p.get("limit"):
        db.x("update credit set limit_amt=%s where mode=%s and customer=%s", (float(p["limit"]), mode, c))
    h = bool(p.get("hold"))
    db.x("update credit set hold=%s, hold_by=%s, hold_at=now() where mode=%s and customer=%s", (h, u.get("name"), mode, c))
    return {"text": "{}：{}{}".format(c.split(" ")[0], "信用冻结，新发货要厂长放行" if h else "放行", "；额度改为 ${:,.0f}".format(float(p["limit"])) if p.get("limit") else "")}


def exec_payment(H, mode, p, u):
    db = H.db
    x = db.one("select * from invoice where id=%s and mode=%s", (int(p["invoice_id"]), mode))
    if x is None:
        raise ValueError("没有这张发票")
    if p.get("delay_days"):
        d = float(p["delay_days"])
        db.x("update invoice set pay_at=coalesce(pay_at, due_at) + make_interval(secs => %s), note=%s where id=%s",
             (d * day_s(mode), "和供应商商量推迟 {:g} 天付款".format(d), x["id"]))
        return {"text": "{} 推迟 {:g} 天付款".format(x["doc"] or x["id"], d)}
    r = pay(H, mode, x["id"], u.get("name"))
    return {"text": "付款 {} ${:,.0f}（提议 {}）".format(x["doc"], x["outstanding"], r.get("proposal_id")), "proposal_id": r.get("proposal_id")}


def exec_budget(H, mode, p, u):
    db = H.db
    month = p.get("month") or month_progress(db, mode)[0]
    if p.get("center") not in CENTERS:
        raise ValueError("没有这个成本中心")
    amt = float(p["amount"])
    if amt <= 0:
        raise ValueError("预算要大于 0")
    db.x("insert into budget (mode, month, center, amount, set_by) values (%s,%s,%s,%s,%s) on conflict (mode, month, center) do update set "
         "amount=excluded.amount, set_by=excluded.set_by, set_at=now()", (mode, month, p["center"], amt, u.get("name")))
    return {"text": "{} {} 预算改为 ${:,.0f}".format(month, CENTERS[p["center"]], amt)}


# ---------------------------------------------------------------- 教学：注入
def inject(H, mode, customer=None, who="老师", days=15, qty=8):
    """老师：某客户一笔发票不付（逾期 days 天，不催就不付）"""
    if mode != "teach":
        raise PermissionError("生产模式不模拟")
    db = H.db
    seed(db, mode)
    customer = customer or F.DEMO_CUSTOMERS[2]
    now = now_utc()
    issued = now - dt.timedelta(seconds=(TERMS_DAYS + float(days)) * day_s(mode))
    amt = int(qty) * F.FG_SELLING_PRICE
    r = db.one("insert into invoice (mode, kind, party, ref, amount, outstanding, issued_at, due_at, status, opening, no_pay, note) "
               "values (%s,'ar',%s,'期初',%s,%s,%s,%s,'open',true,true,%s) returning id",
               (mode, customer, amt, amt, issued, issued + dt.timedelta(seconds=TERMS_DAYS * day_s(mode)), "老师注入：这笔客户压着不付"))
    _patch(db, mode, {"lab22": {"invoice_id": r["id"], "customer": customer}})
    return {"text": "已注入：{} 一笔 ${:,.0f} 的发票逾期 {:g} 天，不催就不付".format(customer.split(" ")[0], amt, float(days)), "invoice_id": r["id"]}
