# -*- coding: utf-8 -*-
"""总线消息 → 本体对象和链接（第 17 轮 A 期）。

每种消息一个函数 f(B, mode, seq, ts, msg, ctx)；B 是 store.Batch，ctx 是同步器的运行时上下文
（当前刀具序号、未闭合的停机、零件开工记录……，重放时从零重建，所以实时同步和重放结果一致）。
只写本体定义里有的类型、属性、链接；写错会直接报错（测试覆盖）。"""
import datetime as dt
import re


def _date(v):
    return str(v)[:10] if v else None


def _wh(name):
    """ERPNext 仓库名带公司缩写后缀（“原材料库 Raw - WQ”），本体里统一去掉"""
    return re.sub(r" - [A-Z0-9]{1,8}$", "", name) if name else name


def _unit(topic):
    """wq/gearbox/<区域>/<设备>/<后缀> → 设备号"""
    p = topic.split("/")
    return p[3] if len(p) > 3 else None


class Ctx:
    """同步器的内存状态（按模式分开）"""

    def __init__(self):
        self.tool = {}            # (mode, unit) → 当前刀具序号
        self.tool_life = {}       # (mode, unit) → 最近的刀具剩余寿命（%）
        self.downtime = {}        # (mode, unit) → 未闭合停机记录的 key
        self.start = {}           # (mode, part, unit, op_index) → (ts, 刀具 key, 刀具寿命)
        self.op_index = {}        # (mode, 工单, 工序名) → 工序序号
        self.agv_task = {}        # (mode, agv) → 当前搬运任务签名
        self.last_state = {}      # (mode, unit) → 状态

    def reset(self, mode=None):
        for d in (self.tool, self.tool_life, self.downtime, self.start, self.op_index, self.agv_task, self.last_state):
            for k in [k for k in d if mode is None or k[0] == mode]:
                del d[k]


# ------------------------------------------------------------------ ERPNext 单据
def erp_doc(B, mode, seq, ts, msg, ctx):
    d = msg["data"]
    if d.get("action") == "failed" or not d.get("name") or d.get("name") == "-":
        return
    dt_, name, act = d.get("doctype"), d["name"], d.get("action") or "sync"
    ev = "erp." + act
    txt = "ERPNext {}：{}".format(dt_, act)
    if dt_ == "Sales Order":
        items = d.get("items") or []
        B.obj(mode, "SalesOrder", name, {
            "delivery_date": _date(d.get("delivery_date")), "transaction_date": _date(d.get("transaction_date")),
            "status": d.get("status"), "item": items[0]["item_code"] if items else None,
            "qty": sum(float(i.get("qty") or 0) for i in items) if items else d.get("qty"),
            "delivered_qty": sum(float(i.get("delivered_qty") or 0) for i in items) if items else None,
            "per_delivered": d.get("per_delivered"), "demo": True if d.get("demo") else None}, seq, ts, ev, txt)
        if d.get("customer"):
            B.obj(mode, "Customer", d["customer"], {"name": d["customer"]}, seq, ts)
            B.link(mode, "SalesOrder", name, "customer", d["customer"], seq=seq, ts=ts)
    elif dt_ == "Work Order":
        B.obj(mode, "WorkOrder", name, {
            "item": d.get("production_item"), "qty": d.get("qty"), "produced_qty": d.get("produced_qty"),
            "status": d.get("status"), "planned_start": _date(d.get("planned_start_date")),
            "expected_delivery": _date(d.get("expected_delivery_date")), "demo": True if d.get("demo") else None}, seq, ts, ev, txt)
        if d.get("production_item"):
            B.link(mode, "WorkOrder", name, "item", d["production_item"], seq=seq, ts=ts)
        so = d.get("sales_order")
        if so:
            B.link(mode, "WorkOrder", name, "sales_order", so, seq=seq, ts=ts)
    elif dt_ == "Material Request":
        lines = d.get("items") or []
        B.obj(mode, "MaterialRequest", name, {"status": d.get("status"), "schedule_date": _date(d.get("schedule_date")),
                                               "lines": lines or None}, seq, ts, ev, txt)
        for i in lines:
            B.link(mode, "MaterialRequest", name, "item", i["item_code"], {"qty": i.get("qty")}, seq, ts)
    elif dt_ == "Purchase Order":
        lines = d.get("items") or []
        B.obj(mode, "PurchaseOrder", name, {"status": d.get("status"), "lines": lines or None}, seq, ts, ev, txt)
        if d.get("supplier"):
            B.obj(mode, "Supplier", d["supplier"], {"name": d["supplier"]}, seq, ts)
            B.link(mode, "PurchaseOrder", name, "supplier", d["supplier"], seq=seq, ts=ts)
        for i in lines:
            B.link(mode, "PurchaseOrder", name, "item", i["item_code"], {"qty": i.get("qty"), "received_qty": i.get("received_qty")}, seq, ts)
    elif dt_ == "Purchase Receipt":
        B.obj(mode, "PurchaseReceipt", name, {"status": d.get("status")}, seq, ts, ev, txt)
    elif dt_ == "Delivery Note":
        B.obj(mode, "DeliveryNote", name, {"status": d.get("status"), "date": _date(ts)}, seq, ts, ev, txt)
    elif dt_ == "Stock Entry":
        B.obj(mode, "StockMove", name, {"purpose": d.get("purpose") or d.get("stock_entry_type"), "qty": d.get("fg_completed_qty")},
              seq, ts, ev, txt)
        if d.get("work_order"):
            B.link(mode, "StockMove", name, "work_order", d["work_order"], seq=seq, ts=ts)
    elif dt_ == "Item":
        code = d.get("item_code") or name
        B.obj(mode, "Item", code, {"name": d.get("item_name"), "revision": d.get("wq_revision")}, seq, ts, ev, txt)
    elif dt_ == "BOM":
        lines = d.get("items") or []
        B.obj(mode, "Bom", name, {"lines": lines or None, "active": d.get("is_active")}, seq, ts, ev, txt)
        if d.get("item"):
            B.link(mode, "Bom", name, "item", d["item"], seq=seq, ts=ts)
        for i in lines:
            B.link(mode, "Bom", name, "component", i["item_code"], {"qty": i.get("qty")}, seq, ts)
    elif dt_ == "Bin":
        item, wh = d.get("item_code"), _wh(d.get("warehouse"))
        if not item or not wh:
            return
        key = "{}@{}".format(item, wh)
        before = (B.st.get(mode, "StockLevel", key) or {}).get("actual_qty")
        B.obj(mode, "StockLevel", key, {"item": item, "warehouse": wh, "actual_qty": d.get("actual_qty"),
                                         "reserved_qty": d.get("reserved_qty"), "ordered_qty": d.get("ordered_qty"),
                                         "projected_qty": d.get("projected_qty")}, seq, ts, silent=True)
        if before is not None and before != d.get("actual_qty"):
            B.event(mode, "StockLevel", key, ts, "stock", "现存 {} → {}".format(before, d.get("actual_qty")), seq)
        B.link(mode, "StockLevel", key, "item", item, seq=seq, ts=ts)
        B.obj(mode, "Warehouse", wh, {}, seq, ts)
        B.alias(mode, d.get("warehouse"), "Warehouse", wh)
        B.link(mode, "StockLevel", key, "warehouse", wh, seq=seq, ts=ts)
    elif dt_ == "Issue":
        B.obj(mode, "ServiceOrder", name, {"subject": d.get("subject"), "status": d.get("status")}, seq, ts, ev, txt)
        serial = d.get("wq_serial") or d.get("serial")
        if serial:
            B.link(mode, "ServiceOrder", name, "unit", serial, seq=seq, ts=ts)
    elif dt_ == "Customer":
        B.obj(mode, "Customer", name, {"name": name}, seq, ts, ev, txt)
    elif dt_ == "Supplier":
        B.obj(mode, "Supplier", name, {"name": name}, seq, ts, ev, txt)
    elif dt_ in ("Job Card", "Quality Inspection"):
        wo = d.get("work_order") or (d.get("reference_name") if dt_ == "Job Card" else None)
        if wo:
            B.event(mode, "WorkOrder", wo, ts, "erp." + dt_.lower().replace(" ", "_"),
                    "ERPNext {} {}（{}）".format(dt_, name, d.get("operation") or d.get("status") or act), seq)


# ------------------------------------------------------------------ 车间
def _op_key(wo, idx):
    return "{}/{}".format(wo, idx)


def machine_cmd(B, mode, seq, ts, msg, ctx):
    d = msg["data"]
    if d.get("command") != "dispatch":
        return
    unit, wo, op = _unit(msg["_topic"]), d.get("work_order"), d.get("operation")
    routing = d.get("routing") or []
    idx = next((i for i, (name, _) in enumerate(routing) if name == op), None)
    if idx is None or not wo:
        return
    ctx.op_index[(mode, wo, op)] = idx
    key = _op_key(wo, idx)
    B.obj(mode, "OperationTask", key, {"work_order": wo, "op_index": idx, "operation": op, "std_min": d.get("std_min"),
                                       "qty": d.get("qty")}, seq, ts, "dispatched", "派工到 {}".format(unit.upper()))
    B.link(mode, "OperationTask", key, "work_order", wo, seq=seq, ts=ts)
    B.link(mode, "OperationTask", key, "machine", unit, seq=seq, ts=ts)
    B.obj(mode, "WorkOrder", wo, {"item": d.get("item"), "qty": d.get("qty"), "released": True}, seq, ts, silent=True)
    if d.get("gcode_ref"):
        B.obj(mode, "NcProgram", d["gcode_ref"], {"item": d.get("item"), "operation": op}, seq, ts)


def _tool(B, mode, unit, ts, seq, ctx):
    k = (mode, unit)
    if k not in ctx.tool:
        ctx.tool[k] = 1
        B.obj(mode, "Tool", "{}/1".format(unit), {"machine": unit, "seq": 1, "kind": "砂轮" if unit == "grd-01" else "刀具",
                                                  "installed_at": ts, "parts": 0}, seq, ts)
        B.link(mode, "Machine", unit, "tool", "{}/1".format(unit), seq=seq, ts=ts)
    return "{}/{}".format(unit, ctx.tool[k])


def machine_status(B, mode, seq, ts, msg, ctx):
    d = msg["data"]
    unit = _unit(msg["_topic"])
    if not unit:
        return
    life = d.get("tool_life_left")
    props = {"state": d.get("state"), "reason": d.get("reason") or "", "work_order": d.get("work_order") or "",
             "operation": d.get("operation") or "", "queue": d.get("queue"), "updated": ts,
             "tool_life": round(life * 100, 1) if life is not None else None}
    prev = ctx.last_state.get((mode, unit))
    st = d.get("state")
    B.obj(mode, "Machine", unit, dict(props, code=unit.upper()), seq, ts, silent=True)
    if st != prev:
        ctx.last_state[(mode, unit)] = st
        if prev is not None:
            B.event(mode, "Machine", unit, ts, "state", "状态 {} → {}{}".format(prev, st, "（{}）".format(d["reason"]) if d.get("reason") else ""), seq)
    if life is not None and unit in TOOL_UNITS:
        ctx.tool_life[(mode, unit)] = round(life * 100, 1)
        tk = _tool(B, mode, unit, ts, seq, ctx)
        B.obj(mode, "Tool", tk, {"life_left": round(life * 100, 1)}, seq, ts, silent=True)
    for j in d.get("dispatched") or []:
        idx = ctx.op_index.get((mode, j.get("work_order"), j.get("operation")))
        if idx is not None:
            B.obj(mode, "OperationTask", _op_key(j["work_order"], idx), {"done": j.get("done"), "started": j.get("started")},
                  seq, ts, silent=True)


TOOL_UNITS = {"saw-01", "cnc-l01-a", "cnc-l01-b", "key-01", "grd-01", "hob-01", "vmc-01", "hmc-01"}


def machine_event(B, mode, seq, ts, msg, ctx):
    d = msg["data"]
    unit = _unit(msg["_topic"])
    ev = d.get("event")
    if not unit:
        return
    if ev == "cycle_start":
        part, wo, idx = d.get("part_serial"), d.get("work_order"), d.get("op_index")
        if not part or idx is None:
            return
        ctx.op_index.setdefault((mode, wo, d.get("operation")), idx)
        B.obj(mode, "PartSerial", part, {"item": d.get("item"), "work_order": wo}, seq, ts, text="开始加工")
        B.link(mode, "PartSerial", part, "work_order", wo, seq=seq, ts=ts)
        tk = _tool(B, mode, unit, ts, seq, ctx) if unit in TOOL_UNITS else None
        ctx.start[(mode, part, unit, idx)] = (ts, tk, ctx.tool_life.get((mode, unit)))
        ok = _op_key(wo, idx)
        o = B.obj(mode, "OperationTask", ok, {"work_order": wo, "op_index": idx, "operation": d.get("operation"), "started": True},
                  seq, ts, silent=True)
        if not o.get("first_start"):
            B.obj(mode, "OperationTask", ok, {"first_start": ts}, seq, ts, "started", "开工（{}）".format(unit.upper()))
        B.link(mode, "OperationTask", ok, "work_order", wo, seq=seq, ts=ts)
        B.link(mode, "OperationTask", ok, "machine", unit, seq=seq, ts=ts)
    elif ev == "cycle_end":
        part, wo, idx = d.get("part_serial"), d.get("work_order"), d.get("op_index")
        if not part or idx is None:
            return
        st = ctx.start.pop((mode, part, unit, idx), None)
        start_ts, tk, life = st if st else (d.get("factory_start_ts"), None, None)
        ok = _op_key(wo, idx)
        B.link(mode, "PartSerial", part, "processed", ok,
               {"machine": unit, "operation": d.get("operation"), "start": start_ts, "end": ts, "cycle_time_s": d.get("cycle_time_s"),
                "tool": tk, "tool_life_pct": life, "good": d.get("good")}, seq, ts)
        B.obj(mode, "PartSerial", part, {"item": d.get("item"), "ops_done": idx + 1}, seq, ts, "processed",
              "{} 完成（{}，{} 秒{}）".format(d.get("operation", "").split(" ")[0], unit.upper(), d.get("cycle_time_s"),
                                          "，刀具剩 {}%".format(life) if life is not None else ""))
        B.obj(mode, "OperationTask", ok, {"done": d.get("qty_done")}, seq, ts, silent=True)
        if tk:
            t = B.st.get(mode, "Tool", tk) or {}
            B.obj(mode, "Tool", tk, {"parts": int(t.get("parts") or 0) + 1}, seq, ts, silent=True)
        if d.get("op_index") is not None and d.get("n_ops") and idx == d["n_ops"] - 1:
            B.obj(mode, "PartSerial", part, {"completed_at": ts}, seq, ts, silent=True)
    elif ev == "op_complete":
        wo, idx = d.get("work_order"), d.get("op_index")
        if idx is None:
            return
        B.obj(mode, "OperationTask", _op_key(wo, idx), {"done": d.get("qty"), "completed_at": ts, "time_s": d.get("time_s")},
              seq, ts, "completed", "完成 {} 件（合格 {}）".format(d.get("qty"), d.get("qty_good")))
    elif ev in ("alarm", "fault"):
        key = "{}/{}".format(unit, ts)
        ctx.downtime[(mode, unit)] = key
        exp = d.get("expected_duration_s")
        B.obj(mode, "Downtime", key, {"machine": unit, "reason": d.get("message"), "kind": "故障" if ev == "fault" else "停机",
                                      "start": ts, "expected_min": round(exp / 60, 1) if exp else None}, seq, ts, text="停机：" + str(d.get("message")))
        B.link(mode, "Downtime", key, "machine", unit, seq=seq, ts=ts)
        B.event(mode, "Machine", unit, ts, "down", "停机：{}".format(d.get("message")), seq)
    elif ev == "recover":
        key = ctx.downtime.pop((mode, unit), None)
        if key:
            mins = round((d.get("downtime_s") or 0) / 60, 1)
            B.obj(mode, "Downtime", key, {"end": ts, "minutes": mins}, seq, ts, "recovered", "恢复（{} 分钟）{}".format(mins, d.get("message") or ""))
        B.event(mode, "Machine", unit, ts, "recover", "恢复：{}".format(d.get("message") or ""), seq)
    elif ev == "tool_change":
        old = _tool(B, mode, unit, ts, seq, ctx)
        B.obj(mode, "Tool", old, {"removed_at": ts, "life_left": round((d.get("tool_life_before") or 0) * 100, 1)}, seq, ts,
              "removed", d.get("message") or "换刀")
        ctx.tool[(mode, unit)] += 1
        new = "{}/{}".format(unit, ctx.tool[(mode, unit)])
        B.obj(mode, "Tool", new, {"machine": unit, "seq": ctx.tool[(mode, unit)], "kind": "砂轮" if unit == "grd-01" else "刀具",
                                  "installed_at": ts, "parts": 0, "life_left": 100.0}, seq, ts, text="装上")
        B.link(mode, "Machine", unit, "tool", new, seq=seq, ts=ts)
        ctx.tool_life[(mode, unit)] = 100.0
        B.event(mode, "Machine", unit, ts, "tool_change", d.get("message") or "换刀", seq)


def quality_measurement(B, mode, seq, ts, msg, ctx):
    d = msg["data"]
    part, ch = d.get("part_serial"), d.get("characteristic")
    if not part or not ch:
        return
    key = "{}/{}".format(part, ch)
    B.obj(mode, "Measurement", key, {"part": part, "characteristic": ch, "name": d.get("name"), "value_mm": d.get("value_mm"),
                                     "lower_mm": d.get("lower_tol_mm"), "upper_mm": d.get("upper_tol_mm"), "result": d.get("result"),
                                     "at": ts}, seq, ts, text="{} = {}（{}）".format(d.get("name"), d.get("value_mm"), d.get("result")))
    B.link(mode, "Measurement", key, "part", part, seq=seq, ts=ts)
    p = B.st.get(mode, "PartSerial", part) or {}
    res = "fail" if d.get("result") == "fail" or p.get("result") == "fail" else "pass"
    B.obj(mode, "PartSerial", part, {"item": d.get("item"), "work_order": d.get("work_order"), "result": res}, seq, ts, silent=True)
    if res == "fail" and p.get("result") != "fail":
        B.event(mode, "PartSerial", part, ts, "nonconforming", "检验不合格：{} = {}".format(d.get("name"), d.get("value_mm")), seq)


def quality_ncr(B, mode, seq, ts, msg, ctx):
    d = msg["data"]
    nid = d.get("ncr_id")
    if not nid:
        return
    B.obj(mode, "Ncr", nid, {"part": d.get("part_serial"), "status": d.get("status"), "detail": d.get("detail")}, seq, ts,
          text="开不合格品单")
    if d.get("part_serial"):
        B.link(mode, "Ncr", nid, "part", d["part_serial"], seq=seq, ts=ts)
    if d.get("work_order"):
        B.link(mode, "Ncr", nid, "work_order", d["work_order"], seq=seq, ts=ts)


def logistics_status(B, mode, seq, ts, msg, ctx):
    d = msg["data"]
    agv = _unit(msg["_topic"])
    if not agv:
        return
    B.obj(mode, "Agv", agv, {"battery": round((d.get("battery") or 0) * 100, 1), "task": d.get("task") or "",
                             "x_m": d.get("x_m"), "y_m": d.get("y_m")}, seq, ts, silent=True)
    sig = (d.get("from"), d.get("to"), d.get("load")) if d.get("task") else None
    if sig and ctx.agv_task.get((mode, agv)) != sig:
        key = "{}/{}".format(agv, ts)
        B.obj(mode, "TransportTask", key, {"agv": agv, "from": d.get("from"), "to": d.get("to"), "part": d.get("load"), "start": ts},
              seq, ts, text="搬运 {} → {}".format(d.get("from"), d.get("to")))
        B.link(mode, "TransportTask", key, "agv", agv, seq=seq, ts=ts)
        if d.get("load"):
            B.link(mode, "TransportTask", key, "part", d["load"], seq=seq, ts=ts)
    ctx.agv_task[(mode, agv)] = sig


def test_torque(B, mode, seq, ts, msg, ctx):
    d = msg["data"]
    serial = d.get("part_serial")
    if not serial:
        return
    B.obj(mode, "PartSerial", serial, {"item": d.get("item"), "work_order": d.get("work_order")}, seq, ts, "runin",
          "跑合试验（{}）".format(d.get("program") or ""))
    if d.get("work_order"):
        B.link(mode, "PartSerial", serial, "work_order", d["work_order"], seq=seq, ts=ts)


def ai_proposal(B, mode, seq, ts, msg, ctx):
    d = msg["data"]
    pid = d.get("proposal_id")
    if not pid:
        return
    B.obj(mode, "Proposal", pid, {"title": d.get("title"), "action": d.get("action"), "status": d.get("status"),
                                  "requested_by": d.get("requested_by"), "confirmed_by": d.get("confirmed_by"), "created": ts},
          seq, ts, "proposal." + str(d.get("status")), "提议 {}".format(d.get("status")))


def design_release(B, mode, seq, ts, msg, ctx):
    d = msg["data"]
    item, rev = d.get("item"), d.get("revision")
    if not item or rev is None:
        return
    key = "{}-rev{}".format(item, rev)
    B.obj(mode, "DesignRevision", key, {"item": item, "revision": rev, "author": d.get("author"), "change_note": d.get("change_note"),
                                        "released_at": ts, "files": [{"kind": f.get("kind"), "name": f.get("name"), "url": f.get("url")}
                                                                    for f in d.get("files") or []] or None,
                                        "params": d.get("params")}, seq, ts, "released", "发布 rev {}".format(rev))
    B.link(mode, "DesignRevision", key, "item", item, seq=seq, ts=ts)
    cur = (B.st.get(mode, "Item", item) or {}).get("revision") or 0
    if rev >= cur:
        B.obj(mode, "Item", item, {"revision": rev}, seq, ts, "revision", "现行设计 rev {}".format(rev))
        B.link(mode, "Item", item, "revision_now", key, seq=seq, ts=ts)
    if d.get("submission"):
        B.link(mode, "DesignRevision", key, "submission", d["submission"], seq=seq, ts=ts)


def design_gcode(B, mode, seq, ts, msg, ctx):
    d = msg["data"]
    ref = d.get("gcode_ref")
    if not ref:
        return
    B.obj(mode, "NcProgram", ref, {"item": d.get("item"), "operation": d.get("operation"), "program": d.get("program") and str(d["program"])},
          seq, ts, text="数控程序发布")
    if d.get("item"):
        B.link(mode, "NcProgram", ref, "item", d["item"], seq=seq, ts=ts)


HANDLERS = {
    "erp.doc": erp_doc,
    "machine.cmd": machine_cmd,
    "machine.status": machine_status,
    "machine.event": machine_event,
    "quality.measurement": quality_measurement,
    "quality.ncr": quality_ncr,
    "logistics.status": logistics_status,
    "test.torque": test_torque,
    "ai.proposal": ai_proposal,
    "design.release": design_release,
    "design.gcode": design_gcode,
}


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()
