# -*- coding: utf-8 -*-
"""模拟 ERPNext（HTTP 版）：给桥接和完整闭环测试用，不需要装真正的 ERPNext。

- 接口与 Frappe REST 一致：/api/resource/<DocType>[/<name>]、/api/method/...；
- 字段名按 ERPNext v16 的 DocType 定义（schemas/*.json，取自 frappe/erpnext 的 version-16 分支）检查，
  写错字段名、漏必填项、链接到不存在的记录都会记进 /api/mock/errors（测试断言它为空）；
- 模仿与闭环有关的业务规则：工单提交生成作业卡、作业卡工时重叠检查（按工位台数）、
  检验工序的作业卡必须关联质量检验单才能提交、完工入库扣原材料加成品并更新工单完工数、库存不许为负。
它不做会计、定价、权限等，所以不能代替在真 ERPNext 上的实测（第 9 步）。

运行：uvicorn mock_erpnext.server:app --port 8091
"""
import datetime as dt
import glob
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE))]

from fastapi import Body, FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from factory import data as F  # noqa: E402

COMPANY = "问渠减速器厂 WenQuest Gearbox (Demo)"
ABBR = "WQ"
META = {"name", "doctype", "docstatus", "modified", "creation", "owner", "idx", "parent", "parenttype", "parentfield",
        "modified_by", "__islocal", "__unsaved"}
NO_VALUE = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading", "Fold"}
INSPECTION_OP = "零件检验 Part inspection"
SCENARIO_STOCK = dict(F.TEACH_STOCK)
REQUIRED = {
    "Sales Order": ["customer", "company", "transaction_date", "delivery_date", "items"],
    "Sales Order Item": ["item_code", "qty", "delivery_date"],
    "Work Order": ["production_item", "bom_no", "company", "qty", "planned_start_date", "fg_warehouse"],
    "Material Request": ["material_request_type", "company", "transaction_date", "items"],
    "Material Request Item": ["item_code", "qty", "schedule_date", "warehouse"],
    "Quality Inspection": ["report_date", "inspection_type", "reference_type", "reference_name", "item_code",
                           "sample_size", "inspected_by", "status"],
    "Quality Inspection Reading": ["specification"],
    "Stock Entry": ["stock_entry_type", "company", "items"],
    "Job Card Time Log": ["from_time", "to_time", "completed_qty"],
}
SERIES = {"Sales Order": "SAL-ORD-{y}-{n:05d}", "Work Order": "MFG-WO-{y}-{n:05d}", "Job Card": "PO-JOB{n:05d}",
          "Material Request": "MAT-MR-{y}-{n:05d}", "Quality Inspection": "MAT-QA-{y}-{n:05d}",
          "Stock Entry": "MAT-STE-{y}-{n:05d}", "Purchase Order": "PUR-ORD-{y}-{n:05d}"}


def now_str():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def parse_dt(s):
    s = str(s).replace("T", " ").replace("Z", "")
    return dt.datetime.fromisoformat(s[:19]) if len(s) > 10 else dt.datetime.fromisoformat(s + " 00:00:00")


class Mock:
    def __init__(self):
        self.schemas = {}
        for f in glob.glob(os.path.join(HERE, "schemas", "*.json")):
            d = json.load(open(f, encoding="utf-8"))
            self.schemas[d["name"]] = d
        self.reset()

    # ------------------------------------------------------------ 数据
    def reset(self):
        self.db, self.errors, self.counters, self.log = {}, [], {}, []
        wh = lambda w: "{} - {}".format(w, ABBR)  # noqa: E731
        self.put("Company", {"name": COMPANY, "company_name": COMPANY, "abbr": ABBR, "default_currency": "USD"})
        for w in F.WAREHOUSES:
            self.put("Warehouse", {"name": wh(w), "warehouse_name": w, "company": COMPANY})
        for c in F.CUSTOMERS:
            self.put("Customer", {"name": c, "customer_name": c})
        for s in F.SUPPLIERS.values():
            self.put("Supplier", {"name": s["name"], "supplier_name": s["name"]})
        for code, (name, kind, uom, rate, sup, qit, note) in F.ITEMS.items():
            self.put("Item", {"name": code, "item_code": code, "item_name": name, "stock_uom": uom,
                              "quality_inspection_template": qit, "description": note})
        for ws, (cap, costs) in F.WORKSTATIONS.items():
            self.put("Workstation", {"name": ws, "workstation_name": ws, "production_capacity": cap,
                                     "hour_rate": float(sum(costs))})
        for op, ws in F.OPERATIONS.items():
            self.put("Operation", {"name": op, "workstation": ws})
        for tname, params in F.inspection_templates().items():
            self.put("Quality Inspection Template", {"name": tname})
            for p in params:
                self.put("Quality Inspection Parameter", {"name": p["parameter"], "parameter": p["parameter"]})
        self.put("User", {"name": "Administrator"})
        self.put("UOM", {"name": "Nos"})
        for u in ("Kg", "Litre"):
            self.put("UOM", {"name": u})
        for parent, (rt, comps) in F.BOMS.items():
            ops = [{"operation": op, "workstation": F.OPERATIONS[op], "time_in_mins": m, "idx": i + 1}
                   for i, (op, m) in enumerate(F.ROUTINGS[rt])]
            self.put("BOM", {"name": "BOM-{}-001".format(parent), "item": parent, "quantity": 1, "is_default": 1,
                             "is_active": 1, "with_operations": 1, "docstatus": 1, "company": COMPANY,
                             "inspection_required": 1 if F.ITEMS[parent][5] else 0,
                             "items": [{"item_code": c, "qty": q, "stock_uom": F.ITEMS[c][2]} for c, q in comps],
                             "operations": ops})
        for code, qty in SCENARIO_STOCK.items():
            self.bin_add(code, wh(F.KIND_WAREHOUSE[F.ITEMS[code][1]]), qty)

    def put(self, dt_, doc):
        doc = dict(doc)
        doc.setdefault("docstatus", 0)
        doc.setdefault("modified", now_str())
        doc.setdefault("creation", doc["modified"])
        self.db.setdefault(dt_, {})[doc["name"]] = doc
        return doc

    def bin_add(self, item, wh, qty):
        name = "{}@{}".format(item, wh)
        b = self.db.setdefault("Bin", {}).get(name)
        if b is None:
            b = self.put("Bin", {"name": name, "item_code": item, "warehouse": wh, "actual_qty": 0.0, "ordered_qty": 0.0,
                                 "reserved_qty": 0.0, "projected_qty": 0.0, "stock_uom": F.ITEMS[item][2]})
        if b["actual_qty"] + qty < -1e-9:
            raise Err(417, "InsufficientStock", "{} 在 {} 库存不足：现有 {:g}，需要 {:g}".format(
                item, wh, b["actual_qty"], -qty))
        b["actual_qty"] = round(b["actual_qty"] + qty, 6)
        b["projected_qty"] = round(b["actual_qty"] + b["ordered_qty"] - b["reserved_qty"], 6)
        b["modified"] = now_str()

    def name_for(self, dt_, doc):
        y = dt.date.today().year
        if dt_ in SERIES:
            self.counters[dt_] = self.counters.get(dt_, 0) + 1
            return SERIES[dt_].format(y=y, n=self.counters[dt_])
        if dt_ == "BOM":
            n = sum(1 for d in self.db.get("BOM", {}).values() if d.get("item") == doc.get("item")) + 1
            return "BOM-{}-{:03d}".format(doc.get("item"), n)
        if dt_ == "Custom Field":
            return "{}-{}".format(doc.get("dt"), doc.get("fieldname"))
        return doc.get("name") or uuid.uuid4().hex[:10]

    # ------------------------------------------------------------ 校验
    def validate(self, dt_, doc, where, partial=False):
        sch = self.schemas.get(dt_)
        if sch:
            fields = {f["fieldname"]: f for f in sch["fields"] if f["fieldtype"] not in NO_VALUE}
            if dt_ == "Item":
                fields["wq_revision"] = {"fieldname": "wq_revision", "fieldtype": "Int"}
            if dt_ == "Work Order":
                fields["wq_sales_order"] = {"fieldname": "wq_sales_order", "fieldtype": "Link"}
            for k, v in doc.items():
                if k in META:
                    continue
                f = fields.get(k)
                if not f:
                    self.errors.append("{}：{} 没有字段 {}".format(where, dt_, k))
                    continue
                if f["fieldtype"] in ("Table", "Table MultiSelect") and isinstance(v, list):
                    for i, row in enumerate(v):
                        self.validate(f["options"], row, "{}.{}[{}]".format(where, k, i), partial)
                elif f["fieldtype"] == "Select" and v not in (None, "") and f.get("options"):
                    opts = f["options"].split("\n")
                    if str(v) not in opts:
                        self.errors.append("{}：{}.{} = {!r} 不在选项里".format(where, dt_, k, v))
                elif f["fieldtype"] == "Link" and v not in (None, "") and f.get("options") in self.db:
                    if v not in self.db[f["options"]]:
                        self.errors.append("{}：{}.{} 链接的 {} {!r} 不存在".format(where, dt_, k, f["options"], v))
        if not partial:
            for k in REQUIRED.get(dt_, []):
                if doc.get(k) in (None, "", []):
                    self.errors.append("{}：{} 缺少必填字段 {}".format(where, dt_, k))

    # ------------------------------------------------------------ 业务规则
    def on_submit(self, dt_, doc):
        if dt_ == "Sales Order":
            doc.update(status="To Deliver and Bill", per_delivered=0)
            for it in doc.get("items", []):
                it.setdefault("delivered_qty", 0)
        elif dt_ == "Material Request":
            doc["status"] = "Pending"
        elif dt_ == "Work Order":
            if doc.get("sales_order"):
                # 真 ERPNext（work_order.validate_sales_order）：订单必须已提交，且订单行里有这个生产物料
                so = self.db.get("Sales Order", {}).get(doc["sales_order"])
                if not so or so.get("docstatus") != 1 or not any(
                        i.get("item_code") == doc["production_item"] for i in so.get("items", [])):
                    raise Err(417, "ValidationError", "Sales Order {} is not valid".format(doc["sales_order"]))
            bom = self.db["BOM"].get(doc["bom_no"])
            if not bom:
                raise Err(417, "ValidationError", "BOM {} 不存在".format(doc["bom_no"]))
            if not doc.get("skip_transfer") and not doc.get("wip_warehouse"):
                raise Err(417, "ValidationError", "需要在制品仓库 wip_warehouse")
            doc.update(status="Not Started", produced_qty=0)
            # 与真 ERPNext 一样：只按工单里的工序生成作业卡；工单没带工序（没先从 BOM 带出）就没有作业卡
            ops = doc.get("operations") or []
            if ops and not any(o.get("sequence_id") for o in ops):     # validate_operations_sequence：全空按行号编
                for i, o in enumerate(ops):
                    o["sequence_id"] = i + 1
            for i, op in enumerate(ops):
                jc = self.put("Job Card", {"name": self.name_for("Job Card", {}), "work_order": doc["name"],
                                           "operation": op["operation"], "workstation": op["workstation"],
                                           "company": doc["company"], "for_quantity": float(doc["qty"]),
                                           "production_item": doc["production_item"], "status": "Open",
                                           "time_logs": [], "total_completed_qty": 0, "total_time_in_mins": 0,
                                           "sequence_id": op.get("sequence_id") or 0})
                self.log.append(("create", "Job Card", jc["name"]))

        elif dt_ == "Job Card":
            if doc["total_completed_qty"] <= 0:
                raise Err(417, "ValidationError", "作业卡 {} 完成数量为 0，不能提交".format(doc["name"]))
            wo = self.db["Work Order"][doc["work_order"]]
            bom = self.db["BOM"][wo["bom_no"]]
            if doc["operation"] == INSPECTION_OP and bom.get("inspection_required") and not doc.get("quality_inspection"):
                raise Err(417, "ValidationError", "作业卡 {} 需要先关联质量检验单".format(doc["name"]))
            qi = self.db.get("Quality Inspection", {}).get(doc.get("quality_inspection") or "")
            if qi and qi.get("status") == "Rejected":     # ERPNext 默认：检验单不合格时停止（Stock Settings）
                raise Err(417, "QualityInspectionRejectedError", "Quality Inspection {} is rejected".format(qi["name"]))
            doc["status"] = "Completed"
            for op in wo["operations"]:
                if op["operation"] == doc["operation"]:
                    op["completed_qty"] = doc["total_completed_qty"]
                    op["status"] = "Completed"
            wo["status"] = "In Process" if wo["status"] == "Not Started" else wo["status"]
            wo["modified"] = now_str()
        elif dt_ == "Stock Entry":
            # ERPNext StockController.validate_inspection：单据要求检验时，入库行必须挂检验单
            if doc.get("inspection_required"):
                for i, it in enumerate(doc["items"]):
                    if it.get("t_warehouse") and not it.get("quality_inspection"):
                        raise Err(417, "QualityInspectionRequiredError",
                                  "Row #{}: Quality Inspection is required for Item {}".format(i + 1, it["item_code"]))
            for it in doc["items"]:
                q = float(it["qty"])
                if it.get("s_warehouse"):
                    self.bin_add(it["item_code"], it["s_warehouse"], -q)
            for it in doc["items"]:
                if it.get("t_warehouse"):
                    self.bin_add(it["item_code"], it["t_warehouse"], float(it["qty"]))
            if doc.get("purpose") == "Manufacture" and doc.get("work_order"):
                wo = self.db["Work Order"][doc["work_order"]]
                wo["produced_qty"] = float(wo.get("produced_qty", 0)) + float(doc["fg_completed_qty"])
                wo["status"] = "Completed" if wo["produced_qty"] >= float(wo["qty"]) else "In Process"
                wo["modified"] = now_str()
        elif dt_ == "BOM" and doc.get("is_default"):
            for b in self.db["BOM"].values():
                if b["item"] == doc["item"] and b["name"] != doc["name"]:
                    b["is_default"] = 0

    def job_card_update(self, doc):
        tot_q = tot_t = 0.0
        for lg in doc.get("time_logs", []):
            a, b = parse_dt(lg["from_time"]), parse_dt(lg["to_time"])
            if b < a:
                raise Err(417, "ValidationError", "工时记录结束时间早于开始时间")
            lg["time_in_mins"] = round((b - a).total_seconds() / 60, 3)
            tot_q += float(lg.get("completed_qty", 0))
            tot_t += lg["time_in_mins"]
        if tot_q > float(doc["for_quantity"]) + 1e-9:
            raise Err(417, "ValidationError", "作业卡 {} 完成数量 {:g} 超过工单数量 {:g}".format(
                doc["name"], tot_q, doc["for_quantity"]))
        # 工序顺序（ERPNext v16 job_card.validate_sequence_id）：作业卡带顺序号时，前面工序在工单里的完工数
        # （作业卡提交后才更新）不能少于本工序的完成数
        if doc.get("sequence_id"):
            wo = self.db["Work Order"][doc["work_order"]]
            for op in wo.get("operations", []):
                if op.get("sequence_id") and op["sequence_id"] < doc["sequence_id"]:
                    done = float(op.get("completed_qty") or 0)
                    if not done or done < tot_q:
                        raise Err(417, "OperationSequenceError", "Job Card {}: As per the sequence of the operations "
                                  "in the work order {}, complete the operation {} before the operation {}.".format(
                                      doc["name"], wo["name"], op["operation"], doc["operation"]))
        # 工位台数检查：照搬 ERPNext v16 job_card.py 的 get_overlap_for / has_overlap——
        # 找出本工位其他作业卡与这条工时重叠的记录，按时间排成“车道”，车道数达到台数就报重叠
        cap = int(self.db["Workstation"][doc["workstation"]]["production_capacity"] or 1)
        for lg in doc.get("time_logs", []):
            a, b = parse_dt(lg["from_time"]), parse_dt(lg["to_time"])
            others = sorted([(parse_dt(x["from_time"]), parse_dt(x["to_time"]))
                             for jc in self.db["Job Card"].values()
                             if jc["name"] != doc["name"] and jc["workstation"] == doc["workstation"]
                             for x in jc.get("time_logs", [])
                             if parse_dt(x["from_time"]) < b and a < parse_dt(x["to_time"])])
            if others and _has_overlap(cap, others):
                raise Err(417, "OverlapError", "Row: From Time and To Time of {} is overlapping with other job cards "
                          "（工位 {} 台数 {}）".format(doc["workstation"], lg["from_time"], cap))
        doc["total_completed_qty"] = tot_q
        doc["total_time_in_mins"] = round(tot_t, 3)
        if doc.get("docstatus", 0) == 0 and tot_q > 0:
            doc["status"] = "Work In Progress"

    def bom_operations(self, doc):
        """get_items_and_operations_from_bom：按 BOM 填工单的工序（与 ERPNext 同名字段）。"""
        bom = self.db["BOM"].get(doc.get("bom_no"))
        if not bom:
            raise Err(417, "ValidationError", "BOM {} 不存在".format(doc.get("bom_no")))
        doc["operations"] = [{"operation": op["operation"], "workstation": op["workstation"], "bom": bom["name"],
                              "time_in_mins": op["time_in_mins"] * float(doc.get("qty") or 1), "status": "Pending",
                              "completed_qty": 0, "sequence_id": op.get("idx") or i + 1,
                              "quality_inspection_required": op.get("quality_inspection_required", 0)}
                             for i, op in enumerate(bom["operations"])]
        return doc

    def make_stock_entry(self, work_order_id, purpose, qty):
        wo = self.db["Work Order"].get(work_order_id)
        if not wo:
            raise Err(404, "DoesNotExistError", "工单 {} 不存在".format(work_order_id))
        bom = self.db["BOM"][wo["bom_no"]]
        qty = float(qty)
        items = [{"item_code": b["item_code"], "qty": round(b["qty"] * qty, 6), "s_warehouse": wo.get("source_warehouse")
                  or "{} - {}".format(F.WAREHOUSES[0], ABBR), "uom": b["stock_uom"], "stock_uom": b["stock_uom"],
                  "conversion_factor": 1} for b in bom["items"]]
        items.append({"item_code": wo["production_item"], "qty": qty, "t_warehouse": wo["fg_warehouse"],
                      "is_finished_item": 1, "uom": "Nos", "stock_uom": "Nos", "conversion_factor": 1})
        return {"doctype": "Stock Entry", "stock_entry_type": "Manufacture", "purpose": purpose, "company": wo["company"],
                "work_order": work_order_id, "fg_completed_qty": qty, "from_bom": 1, "bom_no": wo["bom_no"],
                "use_multi_level_bom": 0, "items": items,
                # 与 ERPNext 一样：从 BOM 继承“需要检验”
                "inspection_required": 1 if bom.get("inspection_required") else 0}


def _has_overlap(capacity, logs):
    """ERPNext JobCard.has_overlap 的同一算法。logs 已按开始时间排序。"""
    if capacity == 1 and logs:
        return True
    lanes = {1: logs[0][1]}
    for f, t in logs[1:]:
        for k in list(lanes):
            if lanes[k] <= f:
                lanes[k] = t
                break
        else:
            lanes[max(lanes) + 1] = t
    return len(lanes) >= capacity


class Err(Exception):
    def __init__(self, status, exc_type, message):
        super().__init__(message)
        self.status, self.exc_type, self.message = status, exc_type, message


M = Mock()
app = FastAPI(title="模拟 ERPNext")


@app.exception_handler(Err)
def _err(req, e):
    return JSONResponse({"exc_type": e.exc_type, "exception": "frappe.exceptions.{}: {}".format(e.exc_type, e.message),
                         "_server_messages": json.dumps([json.dumps({"message": e.message})])}, e.status)


def _filters(raw):
    if not raw:
        return []
    f = json.loads(raw)
    if isinstance(f, dict):
        return [[k, "=", v] for k, v in f.items()]
    return [x[-3:] if len(x) == 4 else x for x in f]


def _match(doc, flt):
    for field, op, val in flt:
        v = doc.get(field)
        if op == "=" and str(v) != str(val):
            return False
        if op == "!=" and str(v) == str(val):
            return False
        if op == ">" and not (v is not None and str(v) > str(val)):
            return False
        if op == "in" and v not in val:
            return False
        if op == "like" and str(val).strip("%") not in str(v):
            return False
    return True


@app.post("/api/method/login")
def login():
    return {"message": "Logged In"}


@app.get("/api/method/frappe.auth.get_logged_user")
def logged():
    return {"message": "Administrator"}


@app.post("/api/method/run_doc_method")
def run_doc_method(body: dict = Body(...)):
    doc = json.loads(body["docs"]) if isinstance(body.get("docs"), str) else body.get("docs")
    if body.get("method") != "get_items_and_operations_from_bom" or doc.get("doctype") != "Work Order":
        raise Err(417, "ValidationError", "模拟 ERPNext 不支持 {}".format(body.get("method")))
    return {"docs": [M.bom_operations(doc)], "message": None}


@app.post("/api/method/erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry")
def mse(body: dict = Body(...)):
    return {"message": M.make_stock_entry(body["work_order_id"], body.get("purpose", "Manufacture"), body.get("qty"))}


@app.get("/api/resource/{doctype}")
def list_docs(doctype: str, request: Request):
    p = request.query_params
    flt = _filters(p.get("filters"))
    fields = json.loads(p.get("fields", '["name"]'))
    rows = [d for d in M.db.get(doctype, {}).values() if _match(d, flt)]
    if p.get("order_by", "").startswith("modified"):
        rows.sort(key=lambda d: d.get("modified", ""), reverse="desc" in p.get("order_by"))
    rows = rows[: int(p.get("limit_page_length", 20) or 10 ** 6)]
    if fields == ["*"]:
        return {"data": [{k: v for k, v in d.items() if not isinstance(v, list)} for d in rows]}
    return {"data": [{f: d.get(f) for f in fields} for d in rows]}


@app.get("/api/resource/{doctype}/{name}")
def get_doc(doctype: str, name: str):
    d = M.db.get(doctype, {}).get(name)
    if d is None:
        raise Err(404, "DoesNotExistError", "{} {} 不存在".format(doctype, name))
    return {"data": dict(d, doctype=doctype)}


@app.post("/api/resource/{doctype}")
def create(doctype: str, body: dict = Body(...)):
    doc = {k: v for k, v in body.items() if k != "doctype"}
    M.validate(doctype, doc, "新建 " + doctype)
    doc["name"] = M.name_for(doctype, doc)
    submit = int(doc.get("docstatus", 0)) == 1
    doc["docstatus"] = 0
    if doctype == "Sales Order":
        for it in doc.get("items", []):
            it.setdefault("delivery_date", doc.get("delivery_date"))
    if doctype == "Job Card":
        raise Err(417, "ValidationError", "作业卡由工单提交时自动生成")
    M.put(doctype, doc)
    doc = M.db[doctype][doc["name"]]
    if submit:
        try:
            M.on_submit(doctype, doc)
        except Err:
            del M.db[doctype][doc["name"]]
            raise
        doc["docstatus"] = 1
    M.log.append(("create", doctype, doc["name"]))
    return {"data": dict(doc, doctype=doctype)}


@app.put("/api/resource/{doctype}/{name}")
def update(doctype: str, name: str, body: dict = Body(...)):
    doc = M.db.get(doctype, {}).get(name)
    if doc is None:
        raise Err(404, "DoesNotExistError", "{} {} 不存在".format(doctype, name))
    body = {k: v for k, v in body.items() if k != "doctype"}
    M.validate(doctype, body, "修改 {} {}".format(doctype, name), partial=True)
    if doc.get("docstatus") == 1 and any(k not in ("docstatus",) for k in body) and doctype not in ("Item",):
        raise Err(417, "UpdateAfterSubmitError", "{} {} 已提交，不能修改".format(doctype, name))
    submit = int(body.get("docstatus", doc.get("docstatus", 0))) == 1 and doc.get("docstatus", 0) == 0
    new = dict(doc)
    new.update({k: v for k, v in body.items() if k != "docstatus"})
    if doctype == "Job Card":
        M.job_card_update(new)
    if submit:
        M.on_submit(doctype, new)
        new["docstatus"] = 1
    new["modified"] = now_str()
    M.db[doctype][name] = new
    M.log.append(("update", doctype, name))
    return {"data": dict(new, doctype=doctype)}


@app.get("/api/mock/errors")
def errors():
    return {"errors": M.errors, "log": M.log[-200:]}


@app.post("/api/mock/reset")
def reset():
    M.reset()
    return {"ok": True}


@app.get("/api/mock/db/{doctype}")
def dump(doctype: str):
    return list(M.db.get(doctype, {}).values())
