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
    "Opportunity": ["opportunity_from", "party_name", "company", "transaction_date"],     # 第 18 轮 E1
    "Quotation": ["quotation_to", "party_name", "company", "transaction_date", "items"],
    "Quotation Item": ["item_code", "qty"],
    "Contract": ["party_type", "party_name", "contract_terms"],
    "Issue": ["subject"],
    # 第 18 轮 E3：资产维护模块（必填与真 ERPNext v16 一致）
    "Asset": ["asset_name", "item_code", "company", "location", "purchase_date", "asset_category", "available_for_use_date", "net_purchase_amount"],
    "Asset Category": ["asset_category_name", "accounts"],
    "Asset Category Account": ["company_name", "fixed_asset_account"],
    "Asset Maintenance": ["asset_name", "company", "maintenance_team", "asset_maintenance_tasks"],
    "Asset Maintenance Task": ["maintenance_task", "maintenance_status", "start_date", "periodicity"],
    "Asset Maintenance Team": ["maintenance_team_name", "company", "maintenance_team_members"],
    "Maintenance Team Member": ["team_member", "maintenance_role"],
    "Asset Maintenance Log": ["maintenance_status", "due_date", "description", "task_name", "task_assignee_email"],
    "Asset Repair": ["failure_date", "asset"],
    "Location": ["location_name"],
    # 第 18 轮 E4：员工、部门、岗位（ERPNext 自带，不需要人力资源模块）
    "Employee": ["first_name", "company", "status", "gender", "date_of_birth", "date_of_joining"],
    "Department": ["department_name", "company"],
    "Designation": ["designation_name"],
    # 第 18 轮 E5：采购单、收货、供应商
    "Purchase Order": ["supplier", "company", "transaction_date", "schedule_date", "items"],
    "Purchase Order Item": ["item_code", "qty", "schedule_date"],
    "Purchase Receipt": ["supplier", "company", "posting_date", "items"],
    "Purchase Receipt Item": ["item_code", "qty"],
    "Supplier": ["supplier_name"],
    # 第 18 轮 E7：销售发票、采购发票、收付款（客户端给的；科目、币种等由按单生成的方法带出）
    "Sales Invoice": ["customer", "company", "posting_date", "due_date", "items", "debit_to"],
    "Sales Invoice Item": ["item_code", "qty", "rate", "income_account"],
    "Purchase Invoice": ["supplier", "company", "posting_date", "due_date", "items", "credit_to"],
    "Purchase Invoice Item": ["item_code", "qty", "rate"],
    "Payment Entry": ["payment_type", "party_type", "party", "posting_date", "company", "paid_from", "paid_to", "paid_amount", "received_amount"],
    "Payment Entry Reference": ["reference_doctype", "reference_name", "allocated_amount"],
}
SERIES = {"Sales Order": "SAL-ORD-{y}-{n:05d}", "Work Order": "MFG-WO-{y}-{n:05d}", "Job Card": "PO-JOB{n:05d}",
          "Material Request": "MAT-MR-{y}-{n:05d}", "Quality Inspection": "MAT-QA-{y}-{n:05d}",
          "Stock Entry": "MAT-STE-{y}-{n:05d}", "Purchase Order": "PUR-ORD-{y}-{n:05d}",
          "Lead": "CRM-LEAD-{y}-{n:05d}", "Opportunity": "CRM-OPP-{y}-{n:05d}", "Quotation": "SAL-QTN-{y}-{n:05d}",
          "Contract": "CON-{y}-{n:05d}", "Issue": "ISS-{y}-{n:05d}",
          "Asset": "ACC-ASS-{y}-{n:05d}", "Asset Maintenance Log": "ACC-AML-{y}-{n:05d}", "Asset Repair": "ACC-ASR-{y}-{n:05d}",
          "Employee": "HR-EMP-{n:05d}", "Purchase Receipt": "MAT-PRE-{y}-{n:05d}",
          "Sales Invoice": "ACC-SINV-{y}-{n:05d}", "Purchase Invoice": "ACC-PINV-{y}-{n:05d}", "Payment Entry": "ACC-PAY-{y}-{n:05d}"}
BY_FIELD = {"Asset Maintenance": "asset_name", "Asset Category": "asset_category_name", "Asset Maintenance Team": "maintenance_team_name",
            "Location": "location_name", "User": "email", "Designation": "designation_name", "Supplier": "supplier_name",
            "Item": "item_code"}                                  # 真 ERPNext：物料按物料编号命名


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
                              "quality_inspection_template": qit, "description": note, "valuation_rate": rate,
                              # 与 seed.py 一样：原材料、外购件有进货检验模板的，收货前要检验
                              "inspection_required_before_purchase": 1 if qit and kind in ("raw", "buy") else 0})
        for ws, (cap, costs) in F.WORKSTATIONS.items():
            self.put("Workstation", {"name": ws, "workstation_name": ws, "production_capacity": cap,
                                     "hour_rate": float(sum(costs))})
        for op, ws in F.OPERATIONS.items():
            self.put("Operation", {"name": op, "workstation": ws})
        for tname, params in F.inspection_templates().items():
            self.put("Quality Inspection Template", {"name": tname})
            for p in params:
                self.put("Quality Inspection Parameter", {"name": p["parameter"], "parameter": p["parameter"]})
        self.put("User", {"name": "Administrator", "email": "admin@example.com"})
        for g in ("Male", "Female"):                     # 第 18 轮 E4：真 ERPNext 安装时就有
            self.put("Gender", {"name": g})
        self.put("Department", {"name": "All Departments", "department_name": "All Departments", "is_group": 1})
        # 第 18 轮 E3：资产要用的科目、角色（真 ERPNext 的标准科目表里有）
        self.put("Account", {"name": "Plants and Machineries - " + ABBR, "account_type": "Fixed Asset", "is_group": 0, "company": COMPANY})
        # 第 18 轮 E7 开票、收付款用的标准科目与成本中心（真 ERPNext 建公司时自带；下面 make_*_invoice 带出的就是这几个）
        for name, typ in (("Debtors", "Receivable"), ("Creditors", "Payable"), ("Sales", "Income Account"), ("Cash", "Cash"),
                          ("Stock Received But Not Billed", "Stock Received But Not Billed")):
            self.put("Account", {"name": "{} - {}".format(name, ABBR), "account_type": typ, "is_group": 0, "company": COMPANY})
        self.put("Cost Center", {"name": "Main - " + ABBR, "is_group": 0, "company": COMPANY})
        for r in ("Maintenance Manager", "Maintenance User", "System Manager"):
            self.put("Role", {"name": r})
        self.put("Item Group", {"name": "Products", "is_group": 0})
        for g in F.ITEM_GROUPS:                          # 导入脚本在真 ERPNext 里建的物料组（新物料按它们挂：freecad-ai-parts 的新产品）
            self.put("Item Group", {"name": g, "is_group": 0})
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

    def _uom(self, item):
        """物料的库存单位：先看物料主数据（新建的物料，如 freecad-ai-parts 的新产品），再看工厂代码数据"""
        it = self.db.get("Item", {}).get(item)
        if it and it.get("stock_uom"):
            return it["stock_uom"]
        return F.ITEMS[item][2]

    def bin_add(self, item, wh, qty):
        name = "{}@{}".format(item, wh)
        b = self.db.setdefault("Bin", {}).get(name)
        if b is None:
            b = self.put("Bin", {"name": name, "item_code": item, "warehouse": wh, "actual_qty": 0.0, "ordered_qty": 0.0,
                                 "reserved_qty": 0.0, "projected_qty": 0.0, "stock_uom": self._uom(item)})
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
        if dt_ == "Customer" and doc.get("customer_name"):       # 真 ERPNext 默认按客户名命名
            return doc["customer_name"]
        if dt_ == "Custom Field":
            return "{}-{}".format(doc.get("dt"), doc.get("fieldname"))
        if dt_ == "Department" and doc.get("department_name"):    # 真 ERPNext：部门名 - 公司缩写
            return "{} - {}".format(doc["department_name"], ABBR) if doc.get("company") else doc["department_name"]
        if dt_ in BY_FIELD and doc.get(BY_FIELD[dt_]):
            return doc[BY_FIELD[dt_]]
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
            for cf in self.db.get("Custom Field", {}).values():          # 桥接加的自定义字段（第 18 轮 E1）
                if cf.get("dt") == dt_:
                    fields[cf["fieldname"]] = {"fieldname": cf["fieldname"], "fieldtype": cf.get("fieldtype", "Data")}
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
        elif dt_ == "Purchase Order":                  # 第 18 轮 E5
            doc.update(status="To Receive and Bill", per_received=0)
            for it in doc.get("items", []):
                it.setdefault("received_qty", 0)
                it.setdefault("warehouse", doc.get("set_warehouse"))
        elif dt_ == "Purchase Receipt":
            # 真 ERPNext StockController.validate_inspection：要求收货前检验的物料，每行要挂检验单；检验单不合格就不许提交
            for i, it in enumerate(doc["items"]):
                item = self.db["Item"].get(it["item_code"]) or {}
                qi = self.db.get("Quality Inspection", {}).get(it.get("quality_inspection") or "")
                if item.get("inspection_required_before_purchase") and not qi:
                    raise Err(417, "QualityInspectionRequiredError", "Row #{}: Quality Inspection is required for Item {}".format(i + 1, it["item_code"]))
                if qi and (qi.get("status") == "Rejected" or qi.get("docstatus") != 1):
                    raise Err(417, "QualityInspectionRejectedError", "Row #{}: Quality Inspection {} is rejected".format(i + 1, qi["name"]))
            for it in doc["items"]:
                self.bin_add(it["item_code"], it.get("warehouse") or doc.get("set_warehouse"), float(it["qty"]))
                po = self.db.get("Purchase Order", {}).get(it.get("purchase_order") or "")
                if po:
                    row = next((r for r in po["items"] if r.get("name") == it.get("purchase_order_item")), None)
                    if row:
                        row["received_qty"] = float(row.get("received_qty", 0)) + float(it["qty"])
                    tot = sum(float(r["qty"]) for r in po["items"])
                    got = sum(min(float(r["qty"]), float(r.get("received_qty", 0))) for r in po["items"])
                    po.update(per_received=round(100 * got / tot, 2) if tot else 100, modified=now_str(),
                              status="To Bill" if got >= tot else "To Receive and Bill")
            doc["status"] = "To Bill"
        elif dt_ in ("Sales Invoice", "Purchase Invoice"):     # 第 18 轮 E7：发票提交后挂账；到期日不能早于过账日
            if str(doc.get("due_date") or "") < str(doc.get("posting_date") or ""):
                raise Err(417, "ValidationError", "Due Date cannot be before Posting Date")
            tot = round(sum(float(i["qty"]) * float(i["rate"]) for i in doc["items"]), 2)
            for i in doc["items"]:
                i["amount"] = round(float(i["qty"]) * float(i["rate"]), 2)
            doc.update(total=tot, net_total=tot, grand_total=tot, rounded_total=tot, outstanding_amount=tot, status="Unpaid")
            if dt_ == "Sales Invoice":
                for so_name in {i.get("sales_order") for i in doc["items"] if i.get("sales_order")}:
                    so = self.db.get("Sales Order", {}).get(so_name)
                    if so:
                        billed = sum(float(i["amount"]) for si in self.db.get("Sales Invoice", {}).values() if si.get("docstatus") == 1
                                     for i in si["items"] if i.get("sales_order") == so_name) + sum(i["amount"] for i in doc["items"] if i.get("sales_order") == so_name)
                        tot_so = sum(float(r["qty"]) * float(r.get("rate") or 0) for r in so["items"]) or billed
                        so.update(per_billed=round(min(100, 100 * billed / tot_so), 2) if tot_so else 100, modified=now_str())
            else:
                for pr_name in {i.get("purchase_receipt") for i in doc["items"] if i.get("purchase_receipt")}:
                    pr = self.db.get("Purchase Receipt", {}).get(pr_name)
                    if pr:
                        pr.update(status="Completed", per_billed=100, modified=now_str())
        elif dt_ == "Payment Entry":                   # 第 18 轮 E7：收付款冲减发票的未付金额
            for r in doc.get("references") or []:
                inv = self.db.get(r["reference_doctype"], {}).get(r["reference_name"])
                if inv is None or inv.get("docstatus") != 1:
                    raise Err(417, "ValidationError", "{} {} 不存在或没提交".format(r["reference_doctype"], r["reference_name"]))
                if float(r["allocated_amount"]) > float(inv["outstanding_amount"]) + 0.01:
                    raise Err(417, "ValidationError", "Allocated Amount cannot be greater than outstanding amount")
                inv["outstanding_amount"] = round(float(inv["outstanding_amount"]) - float(r["allocated_amount"]), 2)
                inv["status"] = "Paid" if inv["outstanding_amount"] <= 0.005 else "Partly Paid"
                inv["modified"] = now_str()
        elif dt_ == "Quotation":                       # 真 ERPNext：报价提交后状态 Open，关联的商机改为 Quotation
            doc["status"] = "Open"
            opp = self.db.get("Opportunity", {}).get(doc.get("opportunity") or "")
            if opp:
                opp.update(status="Quotation", modified=now_str())
        elif dt_ == "Contract":
            doc["status"] = "Active" if doc.get("is_signed") else "Unsigned"
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
        # 与 ERPNext 一样带出所需物料（每行可另指领料仓库）
        doc["required_items"] = [{"item_code": b["item_code"], "required_qty": round(b["qty"] * float(doc.get("qty") or 1), 6),
                                  "source_warehouse": doc.get("source_warehouse"), "stock_uom": b.get("stock_uom")}
                                 for b in bom["items"]]
        return doc

    def make_stock_entry(self, work_order_id, purpose, qty):
        wo = self.db["Work Order"].get(work_order_id)
        if not wo:
            raise Err(404, "DoesNotExistError", "工单 {} 不存在".format(work_order_id))
        bom = self.db["BOM"][wo["bom_no"]]
        qty = float(qty)
        per_item = {r["item_code"]: r.get("source_warehouse") for r in wo.get("required_items") or []}
        items = [{"item_code": b["item_code"], "qty": round(b["qty"] * qty, 6),
                  "s_warehouse": per_item.get(b["item_code"]) or wo.get("source_warehouse") or "{} - {}".format(F.WAREHOUSES[0], ABBR),
                  "uom": b.get("stock_uom") or self._uom(b["item_code"]), "stock_uom": b.get("stock_uom") or self._uom(b["item_code"]),
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
    return [(x[0],) + tuple(x[1:]) if len(x) == 4 else tuple(x) for x in f]


def _match(doc, flt):
    for x in flt:
        if len(x) == 4:                  # [子表 DocType, 字段, 运算, 值]：任一子表行满足（第 18 轮 E7：按订单找发票）
            child, field, op, val = x
            rows = [r for v in doc.values() if isinstance(v, list) for r in v if isinstance(r, dict)]
            if not any(_match(r, [(field, op, val)]) for r in rows) and not _match(doc, [(field, op, val)]):
                return False
            continue
        field, op, val = x
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


@app.post("/api/method/erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt")
def mpr(body: dict = Body(...)):
    """第 18 轮 E5：按采购单生成收货单（未保存），和真 ERPNext 一样只带没收齐的数量"""
    po = M.db.get("Purchase Order", {}).get(body.get("source_name") or "")
    if po is None or po.get("docstatus") != 1:
        raise Err(417, "ValidationError", "采购单 {} 不存在或没提交".format(body.get("source_name")))
    items = [{"item_code": r["item_code"], "qty": float(r["qty"]) - float(r.get("received_qty", 0)), "received_qty": float(r["qty"]) - float(r.get("received_qty", 0)),
              "rate": r.get("rate"), "warehouse": r.get("warehouse") or po.get("set_warehouse"), "purchase_order": po["name"],
              "purchase_order_item": r["name"], "uom": r.get("uom"), "stock_uom": r.get("stock_uom"), "conversion_factor": 1}
             for r in po["items"] if float(r["qty"]) > float(r.get("received_qty", 0))]
    return {"message": {"doctype": "Purchase Receipt", "supplier": po["supplier"], "company": po["company"],
                        "posting_date": dt.date.today().isoformat(), "set_warehouse": po.get("set_warehouse"), "items": items, "__islocal": 1}}


@app.post("/api/method/erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice")
def msi(body: dict = Body(...)):
    """第 18 轮 E7：按销售订单生成销售发票（未保存）：带出没开票的数量、单价、收入科目、应收科目"""
    so = M.db.get("Sales Order", {}).get(body.get("source_name") or "")
    if so is None or so.get("docstatus") != 1:
        raise Err(417, "ValidationError", "销售订单 {} 不存在或没提交".format(body.get("source_name")))
    billed = {}
    for si in M.db.get("Sales Invoice", {}).values():
        if si.get("docstatus") == 1:
            for i in si["items"]:
                if i.get("so_detail"):
                    billed[i["so_detail"]] = billed.get(i["so_detail"], 0) + float(i["qty"])
    items = [{"item_code": r["item_code"], "qty": float(r["qty"]) - billed.get(r["name"], 0), "rate": float(r.get("rate") or 0),
              "uom": r.get("uom") or "Nos", "conversion_factor": 1, "sales_order": so["name"], "so_detail": r["name"],
              "income_account": "Sales - " + ABBR, "cost_center": "Main - " + ABBR}
             for r in so["items"] if float(r["qty"]) > billed.get(r["name"], 0)]
    today = dt.date.today().isoformat()
    return {"message": {"doctype": "Sales Invoice", "customer": so["customer"], "company": so["company"], "posting_date": today, "due_date": today,
                        "currency": "USD", "conversion_rate": 1, "debit_to": "Debtors - " + ABBR, "items": items, "__islocal": 1}}


@app.post("/api/method/erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice")
def mpi(body: dict = Body(...)):
    """第 18 轮 E7：按收货单生成采购发票（未保存）"""
    pr = M.db.get("Purchase Receipt", {}).get(body.get("source_name") or "")
    if pr is None or pr.get("docstatus") != 1:
        raise Err(417, "ValidationError", "收货单 {} 不存在或没提交".format(body.get("source_name")))
    items = [{"item_code": r["item_code"], "qty": float(r["qty"]), "rate": float(r.get("rate") or (M.db["Item"].get(r["item_code"]) or {}).get("valuation_rate") or 0),
              "uom": r.get("uom") or "Nos", "conversion_factor": 1, "purchase_receipt": pr["name"], "pr_detail": r.get("name"),
              "purchase_order": r.get("purchase_order"), "expense_account": "Stock Received But Not Billed - " + ABBR}
             for r in pr["items"]]
    today = dt.date.today().isoformat()
    return {"message": {"doctype": "Purchase Invoice", "supplier": pr["supplier"], "company": pr["company"], "posting_date": today, "due_date": today,
                        "currency": "USD", "conversion_rate": 1, "credit_to": "Creditors - " + ABBR, "items": items, "__islocal": 1}}


@app.get("/api/method/erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry")
@app.post("/api/method/erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry")
async def gpe(request: Request):
    """第 18 轮 E7：按发票生成收款 / 付款单（未保存），金额 = 未付金额"""
    q = dict(request.query_params)
    if request.method == "POST":
        try:
            q.update(await request.json())
        except Exception:  # noqa: BLE001
            pass
    inv = M.db.get(q.get("dt") or "", {}).get(q.get("dn") or "")
    if inv is None or inv.get("docstatus") != 1:
        raise Err(417, "ValidationError", "{} {} 不存在或没提交".format(q.get("dt"), q.get("dn")))
    sale = q["dt"] == "Sales Invoice"
    amt = float(inv["outstanding_amount"])
    return {"message": {"doctype": "Payment Entry", "payment_type": "Receive" if sale else "Pay", "company": inv["company"],
                        "posting_date": dt.date.today().isoformat(), "party_type": "Customer" if sale else "Supplier",
                        "party": inv["customer"] if sale else inv["supplier"],
                        "paid_from": inv["debit_to"] if sale else "Cash - " + ABBR, "paid_to": "Cash - " + ABBR if sale else inv["credit_to"],
                        "paid_amount": amt, "received_amount": amt, "source_exchange_rate": 1, "target_exchange_rate": 1,
                        "references": [{"reference_doctype": q["dt"], "reference_name": q["dn"], "total_amount": float(inv["grand_total"]),
                                        "outstanding_amount": amt, "allocated_amount": amt}], "__islocal": 1}}


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
    for v in doc.values():                     # 子表的每一行有自己的 name（真 ERPNext 一样）
        if isinstance(v, list):
            for row in v:
                if isinstance(row, dict):
                    row.setdefault("name", uuid.uuid4().hex[:10])
    submit = int(doc.get("docstatus", 0)) == 1
    doc["docstatus"] = 0
    if doctype == "Sales Order":
        for it in doc.get("items", []):
            it.setdefault("delivery_date", doc.get("delivery_date"))
    if doctype == "Job Card":
        raise Err(417, "ValidationError", "作业卡由工单提交时自动生成")
    if doctype == "Asset Maintenance":          # 真 ERPNext：保养任务按“被指派用户的邮箱”找用户建待办
        for t in doc.get("asset_maintenance_tasks") or []:
            u = M.db.get("User", {}).get(t.get("assign_to") or "")
            if t.get("assign_to") and (u is None or u.get("email") not in M.db.get("User", {})):
                raise Err(417, "LinkValidationError", "Could not find Allocated To: {}".format((u or {}).get("email") or t.get("assign_to")))
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
    on_submit_ok = {cf["fieldname"] for cf in M.db.get("Custom Field", {}).values() if cf.get("dt") == doctype and cf.get("allow_on_submit")}
    if doc.get("docstatus") == 1 and any(k not in ("docstatus",) and k not in on_submit_ok for k in body) and doctype not in ("Item",):
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
