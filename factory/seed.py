# -*- coding: utf-8 -*-
"""
把问渠虚拟工厂（二级圆柱齿轮减速器）的主数据导入 ERPNext v16。

先在浏览器里完成 ERPNext 的初始设置向导（建好公司），然后运行：
    py seed.py
    py seed.py --opening-stock          # 同时放入小五金和油品的期初库存
    py seed.py --url http://localhost:8090 --user Administrator --password admin

可以重复运行：已经存在的记录会跳过，不会重复创建。
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse

from factory import data as D


class ERPError(Exception):
    pass


# ---------------------------------------------------------------- 接口客户端
class Client:
    """ERPNext / Frappe REST 接口的最小封装。"""

    def __init__(self, url, user, password, session=None):
        import requests
        self.base = url.rstrip("/")
        self.s = session or requests.Session()
        r = self.s.post(self.base + "/api/method/login", data={"usr": user, "pwd": password}, timeout=30)
        if r.status_code != 200:
            raise ERPError("登录失败（{}）：请检查地址、用户名和密码".format(r.status_code))

    @staticmethod
    def _q(name):
        return urllib.parse.quote(name, safe="")

    def _check(self, r):
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400:
            msg = body.get("exception") or body.get("exc_type") or r.text[:300]
            server = body.get("_server_messages")
            if server:
                try:
                    msg = " / ".join(json.loads(m).get("message", "") for m in json.loads(server))
                except (ValueError, AttributeError):
                    pass
            raise ERPError("{} {}：{}".format(r.request.method, urllib.parse.unquote(r.url), msg))
        return body.get("data", body.get("message"))

    def get(self, doctype, name):
        r = self.s.get("{}/api/resource/{}/{}".format(self.base, self._q(doctype), self._q(name)), timeout=30)
        if r.status_code == 404:
            return None
        return self._check(r)

    def find(self, doctype, filters, fields=("name",)):
        params = {"filters": json.dumps(filters), "fields": json.dumps(list(fields)), "limit_page_length": 0}
        r = self.s.get("{}/api/resource/{}".format(self.base, self._q(doctype)), params=params, timeout=30)
        return self._check(r)

    def create(self, doctype, doc):
        r = self.s.post("{}/api/resource/{}".format(self.base, self._q(doctype)), json=doc, timeout=60)
        return self._check(r)

    def call(self, method, **kwargs):
        r = self.s.post("{}/api/method/{}".format(self.base, method), data=kwargs, timeout=60)
        return self._check(r)

    def update(self, doctype, name, values):
        r = self.s.put("{}/api/resource/{}/{}".format(self.base, self._q(doctype), self._q(name)),
                       json=values, timeout=60)
        return self._check(r)


# ---------------------------------------------------------------- 导入步骤
class Seeder:
    def __init__(self, client, company=None, log=print):
        self.c = client
        self.log = log
        self.created = 0
        self.skipped = 0
        companies = [x["name"] for x in self.c.find("Company", [], ["name"])]
        if not companies:
            raise ERPError("还没有公司：请先在浏览器里完成 ERPNext 的初始设置向导")
        if company:
            if company not in companies:
                raise ERPError("找不到公司 {}，现有：{}".format(company, "、".join(companies)))
            self.company = company
        elif len(companies) == 1:
            self.company = companies[0]
        else:
            raise ERPError("有多家公司，请用 --company 指定：{}".format("、".join(companies)))
        info = self.c.get("Company", self.company)
        self.abbr = info["abbr"]
        self.currency = info["default_currency"]
        self.bom_names = {}
        self.supplier_names = {}

    # ---- 通用
    def ensure(self, doctype, name, doc, key=None):
        """按名称（或 key 过滤条件）查找，不存在就创建。返回记录名称。"""
        if key:
            found = self.c.find(doctype, key)
            if found:
                self.skipped += 1
                return found[0]["name"]
        elif self.c.get(doctype, name):
            self.skipped += 1
            return name
        res = self.c.create(doctype, doc)
        self.created += 1
        return res["name"]

    def root(self, doctype, parent_field, extra=None):
        filters = [[parent_field, "is", "not set"], ["is_group", "=", 1]] + (extra or [])
        found = self.c.find(doctype, filters)
        if not found:
            raise ERPError("找不到 {} 的根节点，初始设置向导是否已完成？".format(doctype))
        return found[0]["name"]

    def wh(self, label):
        return "{} - {}".format(label, self.abbr)

    # ---- 1 基础
    def basics(self):
        self.log("基础数据：单位、成本项、工作日历、分组、仓库")
        for uom in ("Nos", "Kg", "Litre"):
            if not self.c.get("UOM", uom):
                raise ERPError("系统里没有计量单位 {}".format(uom))
        for comp in D.COST_COMPONENTS:
            self.ensure("Workstation Operating Component", comp, {"component_name": comp})

        hl = "WQ 工作日历 2026-2027"
        if not self.c.get("Holiday List", hl):
            self.c.create("Holiday List", {
                "holiday_list_name": hl, "from_date": "2026-01-01", "to_date": "2027-12-31",
                "holidays": holidays(2026, 2027)})
            self.created += 1
        comp = self.c.get("Company", self.company)
        if not comp.get("default_holiday_list"):
            self.c.update("Company", self.company, {"default_holiday_list": hl})
        self.holiday_list = hl
        # 完工入库时，工序的加工费记入“默认加工费科目”；新建的公司没设这一项，入库记账会报“Account is required”。
        # 用公司自己的“计入存货价值的费用”科目（ERPNext 一向把制造加工费记在这里）（第 3 轮真 ERPNext 演练发现）
        if not comp.get("default_operating_cost_account"):
            acc = comp.get("expenses_included_in_valuation") or comp.get("default_expense_account")
            if acc:
                self.c.update("Company", self.company, {"default_operating_cost_account": acc})
            else:
                self.log("提醒：公司没有“计入存货价值的费用”科目，请在 ERPNext 公司设置里手动填“默认加工费科目”")

        ig_root = self.root("Item Group", "parent_item_group")
        for g in D.ITEM_GROUPS:
            self.ensure("Item Group", g, {"item_group_name": g, "parent_item_group": ig_root})
        sg_root = self.root("Supplier Group", "parent_supplier_group")
        self.ensure("Supplier Group", D.SUPPLIER_GROUP,
                    {"supplier_group_name": D.SUPPLIER_GROUP, "parent_supplier_group": sg_root})
        cg_root = self.root("Customer Group", "parent_customer_group")
        self.ensure("Customer Group", D.CUSTOMER_GROUP,
                    {"customer_group_name": D.CUSTOMER_GROUP, "parent_customer_group": cg_root})
        wh_root = self.root("Warehouse", "parent_warehouse", [["company", "=", self.company]])
        for w in D.WAREHOUSES:
            self.ensure("Warehouse", self.wh(w),
                        {"warehouse_name": w, "company": self.company, "parent_warehouse": wh_root})

    # ---- 2 往来单位
    def parties(self):
        self.log("供应商与客户")
        for key, s in D.SUPPLIERS.items():
            self.supplier_names[key] = self.ensure(
                "Supplier", None,
                {"supplier_name": s["name"], "supplier_type": "Company", "supplier_group": D.SUPPLIER_GROUP},
                key=[["supplier_name", "=", s["name"]]])
        territory = self.root("Territory", "parent_territory")
        for name in D.CUSTOMERS:
            self.ensure("Customer", None,
                        {"customer_name": name, "customer_type": "Company",
                         "customer_group": D.CUSTOMER_GROUP, "territory": territory},
                        key=[["customer_name", "=", name]])

    # ---- 3 质量检验模板
    def quality(self):
        self.log("质量检验参数与模板")
        for tname, params in D.inspection_templates().items():
            for p in params:
                self.ensure("Quality Inspection Parameter", p["parameter"], {"parameter": p["parameter"]})
            rows = []
            for p in params:
                row = {"specification": p["parameter"], "numeric": p["numeric"]}
                if p["numeric"]:
                    row.update({"min_value": p["min"], "max_value": p["max"]})
                else:
                    row["value"] = p["value"]
                rows.append(row)
            self.ensure("Quality Inspection Template", tname,
                        {"quality_inspection_template_name": tname,
                         "item_quality_inspection_parameter": rows})

    # ---- 4 物料与价格
    def items(self):
        self.log("物料与价格")
        buying = self.c.find("Price List", [["buying", "=", 1], ["enabled", "=", 1]])
        selling = self.c.find("Price List", [["selling", "=", 1], ["enabled", "=", 1]])
        if not buying or not selling:
            raise ERPError("找不到采购或销售价格表")
        buying, selling = buying[0]["name"], selling[0]["name"]
        for code, (name, kind, uom, price, sup, qit, note) in D.ITEMS.items():
            doc = item_doc(code, name, kind, uom, price, qit, note, self.company, self.wh(D.KIND_WAREHOUSE[kind]),
                           self.supplier_names.get(sup), D.SUPPLIERS.get(sup, {}).get("lead"))
            self.ensure("Item", code, doc)
            if price is not None:
                self.ensure("Item Price", None,
                            {"item_code": code, "uom": uom, "price_list": buying, "price_list_rate": price},
                            key=[["item_code", "=", code], ["price_list", "=", buying]])
        self.ensure("Item Price", None,
                    {"item_code": "WQR-105", "uom": "Nos", "price_list": selling,
                     "price_list_rate": D.FG_SELLING_PRICE},
                    key=[["item_code", "=", "WQR-105"], ["price_list", "=", selling]])

    # ---- 4′ 教材案例件（第 11 轮）：可单独重复运行，每次部署都补建
    def case_items(self):
        self.log("教材案例件")
        for code, (name, kind, uom, price, sup, qit, note) in D.CASE_ITEMS.items():
            self.ensure("Item", code, item_doc(code, name, kind, uom, price, qit, note, self.company,
                                               self.wh(D.KIND_WAREHOUSE[kind]), None, None))

    # ---- 5 工位、工序、工艺路线
    def routing(self):
        self.log("工作中心、工序与工艺路线")
        for ws, (capacity, costs) in D.WORKSTATIONS.items():
            self.ensure("Workstation", ws, {
                "workstation_name": ws, "production_capacity": capacity,
                "holiday_list": self.holiday_list,
                "working_hours": [{"start_time": a, "end_time": b} for a, b in D.SHIFT],
                "workstation_costs": [{"operating_component": comp, "operating_cost": cost}
                                      for comp, cost in zip(D.COST_COMPONENTS, costs)],
            })
        for op, ws in D.OPERATIONS.items():
            self.ensure("Operation", op, {"name": op, "workstation": ws})
        for rname, ops in D.ROUTINGS.items():
            self.ensure("Routing", rname, {"routing_name": rname, "operations": operation_rows(ops)})

    # ---- 6 物料清单
    def boms(self):
        self.log("物料清单（从零件到成品）")
        for parent, (routing, lines) in D.BOMS.items():
            existing = self.c.find("BOM", [["item", "=", parent], ["is_default", "=", 1], ["docstatus", "=", 1]])
            if existing:
                self.bom_names[parent] = existing[0]["name"]
                self.skipped += 1
                continue
            draft = self.c.find("BOM", [["item", "=", parent], ["docstatus", "=", 0]])
            if draft:   # 上次导入时建好但没提交成功的草稿，直接提交
                self.c.update("BOM", draft[0]["name"], {"docstatus": 1})
                self.bom_names[parent] = draft[0]["name"]
                self.created += 1
                continue
            items = []
            for code, qty in lines:
                row = {"item_code": code, "qty": qty, "uom": D.ITEMS[code][2], "rate": D.ITEMS[code][3] or 0}
                if code in self.bom_names:
                    row["bom_no"] = self.bom_names[code]
                items.append(row)
            qit = D.ITEMS[parent][5]
            doc = {"item": parent, "quantity": 1, "company": self.company, "currency": self.currency,
                   "conversion_rate": 1, "is_active": 1, "is_default": 1, "with_operations": 1,
                   "rm_cost_as_per": "Valuation Rate", "routing": routing,
                   "operations": operation_rows(D.ROUTINGS[routing], quality_gate=bool(qit)), "items": items}
            if qit:
                # 质检门：BOM 要求检验，且检验工序标记为必检，工序卡才会要求先提交质量检验单
                doc["inspection_required"] = 1
                doc["quality_inspection_template"] = qit
            res = self.c.create("BOM", doc)
            self.c.update("BOM", res["name"], {"docstatus": 1})   # 提交，使 BOM 生效
            self.bom_names[parent] = res["name"]
            self.created += 1

    # ---- 7 期初库存（可选）
    def opening_stock(self):
        self.log("期初库存：小五金与油品")
        tag = "WQ 虚拟工厂期初库存 opening stock"
        if self.c.find("Stock Entry", [["remarks", "=", tag], ["docstatus", "=", 1]]):
            self.skipped += 1
            return
        types = self.c.find("Stock Entry Type", [["purpose", "=", "Material Receipt"]])
        if not types:
            raise ERPError("找不到“物料入库”类型的库存凭证")
        items = [{"item_code": code, "qty": qty, "uom": D.ITEMS[code][2], "stock_uom": D.ITEMS[code][2],
                  "conversion_factor": 1, "transfer_qty": qty,
                  "t_warehouse": self.wh(D.WAREHOUSES[1]), "basic_rate": D.ITEMS[code][3]}
                 for code, qty in D.OPENING_STOCK.items()]
        res = self.c.create("Stock Entry", {"stock_entry_type": types[0]["name"], "purpose": "Material Receipt",
                                            "company": self.company, "remarks": tag, "items": items})
        self.c.update("Stock Entry", res["name"], {"docstatus": 1})
        self.created += 1

    # ---- 8 教学情景库存（线上安装用，第 3 轮 D13）
    def teach_stock(self):
        """放入实验 7 开始时的关键物料库存，并允许负库存：公共工厂里很多学生反复做实验，扣料不能卡住。"""
        self.log("教学情景库存：关键物料 + 允许负库存")
        self.c.update("Stock Settings", "Stock Settings", {"allow_negative_stock": 1})
        tag = "WQ 教学情景库存 teaching scenario stock"
        if self.c.find("Stock Entry", [["remarks", "=", tag], ["docstatus", "=", 1]]):
            self.skipped += 1
            return
        types = self.c.find("Stock Entry Type", [["purpose", "=", "Material Receipt"]])
        if not types:
            raise ERPError("找不到“物料入库”类型的库存凭证")
        items = [{"item_code": code, "qty": qty, "uom": D.ITEMS[code][2], "stock_uom": D.ITEMS[code][2],
                  "conversion_factor": 1, "transfer_qty": qty,
                  "t_warehouse": self.wh(D.KIND_WAREHOUSE[D.ITEMS[code][1]]), "basic_rate": D.ITEMS[code][3]}
                 for code, qty in D.TEACH_STOCK.items()]
        res = self.c.create("Stock Entry", {"stock_entry_type": types[0]["name"], "purpose": "Material Receipt",
                                            "company": self.company, "remarks": tag, "items": items})
        self.c.update("Stock Entry", res["name"], {"docstatus": 1})
        self.created += 1

    # ---- 零件库编号（第 5 轮 P10②）：可单独重复运行，已安装的服务器每次部署都跑一遍
    def library_refs(self, factory_url=""):
        self.log("零件库编号")
        fields = [("wq_library_ref", {"label": "零件库编号 Library ref", "fieldtype": "Data", "insert_after": "item_name",
                                      "read_only": 1}),
                  ("wq_library_url", {"label": "零件库页面 Library page", "fieldtype": "Data", "options": "URL",
                                      "insert_after": "wq_library_ref", "read_only": 1})]
        for fn, spec in fields:
            if not self.c.find("Custom Field", [["dt", "=", "Item"], ["fieldname", "=", fn]]):
                self.c.create("Custom Field", dict(spec, dt="Item", fieldname=fn))
                self.created += 1
        base = factory_url.rstrip("/")
        n = 0
        for code, ref in D.LIBRARY_REFS.items():
            if code not in D.ITEMS or not self.c.get("Item", code):
                continue
            want = {"wq_library_ref": ref}
            if base:
                want["wq_library_url"] = "{}/library?ref={}".format(base, ref)
            cur = self.c.get("Item", code) or {}
            if any(cur.get(k) != v for k, v in want.items()):
                self.c.update("Item", code, want)
                n += 1
        self.log("  更新 {} 个物料".format(n))

    def erp_sso(self, factory_url, secret, hub_internal="http://wqf-hub:8100"):
        """第 7 轮：问渠单点登录——只读角色与查看权限、社交登录“WenQuest”、登录页自动跳转脚本（可重复执行）"""
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "digital"))
        from hub import erp_sso as E
        c = self.c
        if not c.get("Role", E.STUDENT_ROLE):
            c.create("Role", {"role_name": E.STUDENT_ROLE, "desk_access": 1})
            self.log("新建角色：" + E.STUDENT_ROLE)
        have = {(p["parent"]) for p in c.find("Custom DocPerm", [["role", "=", E.STUDENT_ROLE]], ("parent",))}
        for dt in E.STUDENT_READ_DOCTYPES:
            if dt not in have:     # add() 会先把标准权限复制成自定义权限，再加这一条只读，不影响其他角色
                c.call("frappe.core.page.permission_manager.permission_manager.add", parent=dt, role=E.STUDENT_ROLE, permlevel=0)
        self.log("只读角色可查看 {} 种单据".format(len(E.STUDENT_READ_DOCTYPES)))
        key = {"provider_name": "WenQuest", "social_login_provider": "Custom", "enable_social_login": 1,
               "client_id": E.CLIENT_ID, "client_secret": secret, "base_url": factory_url.rstrip("/"), "custom_base_url": 1,
               "authorize_url": "/api/oauth/authorize", "access_token_url": hub_internal + "/api/oauth/token",
               "api_endpoint": hub_internal + "/api/oauth/userinfo", "redirect_url": E.CALLBACK_PATH,
               "user_id_property": "sub", "sign_ups": "Deny"}
        if c.get("Social Login Key", E.PROVIDER):
            c.update("Social Login Key", E.PROVIDER, key)
        else:
            c.create("Social Login Key", key)
        ws = c.get("Website Script", "Website Script") or {}
        js = ws.get("javascript") or ""
        a, b = "// >>> wenquest-sso", "// <<< wenquest-sso"
        block = "{}\n{}\n{}".format(a, E.AUTO_LOGIN_JS, b)
        js = (js[:js.index(a)] + block + js[js.index(b) + len(b):]) if a in js and b in js else (js + "\n" + block).strip()
        c.update("Website Script", "Website Script", {"javascript": js})
        self.log("问渠单点登录已配置：{} → ERPNext".format(factory_url))

    def run(self, opening_stock=False, teach_stock=False, factory_url=""):
        self.log("公司：{}（{}），币种 {}".format(self.company, self.abbr, self.currency))
        self.basics()
        self.parties()
        self.quality()
        self.items()
        self.case_items()
        self.routing()
        self.boms()
        if opening_stock:
            self.opening_stock()
        if teach_stock:
            self.teach_stock()
        self.library_refs(factory_url)
        self.log("完成：新建 {} 条，已存在跳过 {} 条".format(self.created, self.skipped))


# ---------------------------------------------------------------- 纯函数（可单独测试）
def holidays(y0, y1):
    fixed = {  # 美国主要节假日（教学用）
        "2026-11-26": "感恩节 Thanksgiving", "2026-12-25": "圣诞节 Christmas",
        "2027-01-01": "元旦 New Year", "2027-05-31": "阵亡将士纪念日 Memorial Day",
        "2027-07-05": "独立日（补休）Independence Day", "2027-09-06": "劳动节 Labor Day",
        "2027-11-25": "感恩节 Thanksgiving", "2027-12-24": "圣诞节（补休）Christmas",
    }
    out = []
    d = dt.date(y0, 1, 1)
    while d <= dt.date(y1, 12, 31):
        iso = d.isoformat()
        if d.weekday() >= 5:
            out.append({"holiday_date": iso, "description": "周末 Weekend", "weekly_off": 1})
        elif iso in fixed:
            out.append({"holiday_date": iso, "description": fixed[iso], "weekly_off": 0})
        d += dt.timedelta(days=1)
    return out


def operation_rows(ops, quality_gate=False):
    rows = []
    for seq, (op, minutes) in enumerate(ops, start=1):
        ws = D.OPERATIONS[op]
        row = {"operation": op, "workstation": ws, "time_in_mins": minutes, "sequence_id": seq,
               "hour_rate": sum(D.WORKSTATIONS[ws][1])}
        if quality_gate and op in D.INSPECTION_OPS:
            row["quality_inspection_required"] = 1
        rows.append(row)
    return rows


def item_doc(code, name, kind, uom, price, qit, note, company, warehouse, supplier, lead):
    doc = {
        "item_code": code, "item_name": name, "item_group": D.KIND_GROUP[kind], "stock_uom": uom,
        "is_stock_item": 1, "include_item_in_manufacturing": 1, "description": note or name,
        "is_purchase_item": 1 if kind in ("raw", "buy") else 0,
        "is_sales_item": 1 if kind == "fg" else 0,
        "default_material_request_type": "Purchase" if kind in ("raw", "buy") else "Manufacture",
        "item_defaults": [{"company": company, "default_warehouse": warehouse}],
    }
    if price is not None:
        doc["valuation_rate"] = price   # 不设 standard_rate，否则 ERPNext 会顺带生成一条同价的销售价
    if supplier:
        doc["item_defaults"][0]["default_supplier"] = supplier
        doc["supplier_items"] = [{"supplier": supplier}]
    if lead:
        doc["lead_time_days"] = lead
    if code in D.SAFETY_STOCK:
        doc["safety_stock"] = D.SAFETY_STOCK[code]
    if qit:
        doc["quality_inspection_template"] = qit
        if kind in ("raw", "buy"):
            doc["inspection_required_before_purchase"] = 1
        if kind == "fg":
            doc["inspection_required_before_delivery"] = 1
    if kind == "fg":
        doc["has_serial_no"] = 1
        doc["serial_no_series"] = "WQR105-.#####"
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description="导入问渠虚拟工厂主数据到 ERPNext")
    ap.add_argument("--url", default="http://localhost:8090")
    ap.add_argument("--user", default="Administrator")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--company", default=None)
    ap.add_argument("--opening-stock", action="store_true")
    ap.add_argument("--teach-stock", action="store_true", help="线上教学工厂：放入实验 7 的关键物料库存并允许负库存")
    ap.add_argument("--factory-url", default="", help="数字工厂网址，物料上的“零件库页面”链接用，如 https://factory.example.com")
    ap.add_argument("--library-refs-only", action="store_true", help="只补零件库编号（已安装的服务器更新时用）")
    ap.add_argument("--erp-sso-only", action="store_true", help="只配置问渠单点登录（第 7 轮；每次部署时执行）")
    ap.add_argument("--hub-internal", default="http://wqf-hub:8100", help="ERPNext 服务器访问枢纽的内部地址（演示工厂用 wqf-hub-demo）")
    ap.add_argument("--sso-secret", default=os.environ.get("WQ_ERP_OAUTH_SECRET", ""), help="单点登录密钥（与枢纽相同）")
    args = ap.parse_args(argv)
    try:
        sd = Seeder(Client(args.url, args.user, args.password), args.company)
        if args.erp_sso_only:
            if not (args.factory_url and args.sso_secret):
                print("出错：--erp-sso-only 需要 --factory-url 和 --sso-secret", file=sys.stderr)
                return 1
            sd.erp_sso(args.factory_url, args.sso_secret, args.hub_internal)
            try:
                sd.case_items()                       # 第 11 轮：每次部署补建教材案例件（失败不影响单点登录）
            except ERPError as e:
                print("教材案例件没有建成：{}".format(e), file=sys.stderr)
        elif args.library_refs_only:
            sd.library_refs(args.factory_url)
        else:
            sd.run(args.opening_stock, args.teach_stock, args.factory_url)
    except ERPError as e:
        print("出错：{}".format(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
