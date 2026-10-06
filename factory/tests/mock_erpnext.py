# -*- coding: utf-8 -*-
"""
一个模拟的 ERPNext REST 接口，用 ERPNext v16 的 DocType 定义（tests/schemas/*.json，取自
github.com/frappe/erpnext 的 version-16 分支）检查 seed.py 发出的每一条数据：
字段名是否存在、必填项是否齐全、下拉选项是否合法、链接的记录是否已经存在。

它不能代替真实 ERPNext（不执行业务校验和成本计算），但能在没有 ERPNext 的环境里
抓住字段名写错、链接顺序错这一类最常见的问题。
"""
import glob
import json
import os
import urllib.parse

HERE = os.path.dirname(__file__)
META_KEYS = {"docstatus", "doctype", "name"}
NO_VALUE = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}


def load_schemas():
    out = {}
    for f in glob.glob(os.path.join(HERE, "schemas", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        out[d["name"]] = d
    return out


class Resp:
    def __init__(self, status, body, method, url):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body, ensure_ascii=False)
        self.url = url
        self.request = type("R", (), {"method": method})()

    def json(self):
        return self._body


class MockERPNext:
    """实现 requests.Session 里 seed.py 用到的 get/post/put。"""

    def __init__(self, company="问渠减速器厂 WenQuest Gearbox (Demo)", abbr="WQ"):
        self.schemas = load_schemas()
        self.db = {}
        self.errors = []
        self.counter = 0
        self.abbr = abbr
        seed = {
            "Company": [{"name": company, "company_name": company, "abbr": abbr, "default_currency": "USD",
                         "country": "United States",
                         "expenses_included_in_valuation": "Expenses Included In Valuation - " + abbr}],
            "Currency": [{"name": "USD"}],
            "Country": [{"name": "United States"}],
            "UOM": [{"name": u} for u in ("Nos", "Kg", "Litre", "Unit", "Meter")],
            "Item Group": [{"name": "All Item Groups", "is_group": 1, "parent_item_group": ""}],
            "Supplier Group": [{"name": "All Supplier Groups", "is_group": 1, "parent_supplier_group": ""}],
            "Customer Group": [{"name": "All Customer Groups", "is_group": 1, "parent_customer_group": ""}],
            "Territory": [{"name": "All Territories", "is_group": 1, "parent_territory": ""}],
            "Warehouse": [{"name": "All Warehouses - " + abbr, "is_group": 1, "parent_warehouse": "",
                           "company": company}],
            "Price List": [{"name": "Standard Buying", "buying": 1, "selling": 0, "enabled": 1},
                           {"name": "Standard Selling", "buying": 0, "selling": 1, "enabled": 1}],
            "Stock Entry Type": [{"name": "Material Receipt", "purpose": "Material Receipt"}],
            "User": [{"name": "Administrator"}],
            "Stock Settings": [{"name": "Stock Settings", "allow_negative_stock": 0}],
        }
        for dt, rows in seed.items():
            for r in rows:
                self.db.setdefault(dt, {})[r["name"]] = dict(r)

    # ---- helpers
    def _path(self, url):
        path = urllib.parse.urlparse(url).path
        parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
        return parts

    def _exists(self, doctype, name):
        return name in self.db.get(doctype, {})

    def _validate(self, doctype, doc, where, partial=False):
        schema = self.schemas.get(doctype)
        if not schema:
            self.errors.append("{}: 没有 {} 的定义，无法校验".format(where, doctype))
            return
        fields = {f["fieldname"]: f for f in schema["fields"] if f["fieldtype"] not in NO_VALUE}
        for key, value in doc.items():
            if key in META_KEYS:
                continue
            f = fields.get(key)
            if not f:
                self.errors.append("{}: {} 没有字段 {}".format(where, doctype, key))
                continue
            ft = f["fieldtype"]
            if ft in ("Table", "Table MultiSelect"):
                for i, row in enumerate(value):
                    self._validate(f["options"], row, "{}.{}[{}]".format(where, key, i))
            elif ft == "Select" and value not in (None, ""):
                opts = (f.get("options") or "").split("\n")
                if str(value) not in opts:
                    self.errors.append("{}: {}.{} = {!r} 不在选项 {}".format(where, doctype, key, value, opts))
            elif ft == "Link" and value not in (None, ""):
                target = f["options"]
                if target in self.db and not self._exists(target, value):
                    self.errors.append("{}: {}.{} 链接的 {} {!r} 不存在".format(where, doctype, key, target, value))
        for f in fields.values():
            if partial:
                break
            if f["fieldtype"] == "Select" and f.get("options"):
                continue   # 必填下拉框默认取第一个选项（如 naming_series）
            if f.get("reqd") and f["fieldname"] not in doc and f.get("default") in (None, ""):
                # 这几个必填项由 ERPNext 在保存时自动计算或带出
                auto = {("BOM Item", "rate"), ("BOM Item", "uom"), ("Stock Entry Detail", "conversion_factor")}
                if (doctype, f["fieldname"]) in auto:
                    continue
                self.errors.append("{}: {} 缺少必填字段 {}".format(where, doctype, f["fieldname"]))

    def _name_for(self, doctype, doc):
        auto = (self.schemas[doctype].get("autoname") or "").strip()
        if doctype == "Warehouse":
            return "{} - {}".format(doc["warehouse_name"], self.abbr)
        if doctype == "BOM":
            n = sum(1 for d in self.db.get("BOM", {}).values() if d.get("item") == doc["item"]) + 1
            return "BOM-{}-{:03d}".format(doc["item"], n)
        if auto.startswith("field:"):
            return doc[auto.split(":", 1)[1]]
        if auto.lower() == "prompt":
            if not doc.get("name"):
                self.errors.append("{}: 需要在数据里给出 name".format(doctype))
            return doc.get("name")
        self.counter += 1
        return "{}-{:05d}".format(doctype.upper().replace(" ", "-"), self.counter)

    @staticmethod
    def _match(doc, filters):
        for field, op, *rest in filters:
            val = doc.get(field)
            if op == "=" and val != rest[0]:
                return False
            if op == "is" and rest[0] == "not set" and val not in (None, ""):
                return False
        return True

    # ---- requests.Session 接口
    def post(self, url, data=None, json=None, timeout=None):
        parts = self._path(url)
        if parts[:3] == ["api", "method", "login"]:
            return Resp(200, {"message": "Logged In"}, "POST", url)
        doctype = parts[2]
        doc = dict(json)
        if doctype == "Custom Field":                  # 自定义字段：检查必填，把字段加进目标单据的定义
            miss = [k for k in ("dt", "fieldname", "fieldtype", "label") if not doc.get(k)]
            if miss or doc.get("dt") not in self.schemas:
                self.errors.append("新建 Custom Field：缺 {} 或单据 {} 不存在".format(miss, doc.get("dt")))
            else:
                self.schemas[doc["dt"]]["fields"].append({"fieldname": doc["fieldname"], "fieldtype": doc["fieldtype"],
                                                          "options": doc.get("options")})
            name = "{}-{}".format(doc.get("dt"), doc.get("fieldname"))
            doc.update(name=name, docstatus=0)
            self.db.setdefault(doctype, {})[name] = doc
            return Resp(200, {"data": doc}, "POST", url)
        self._validate(doctype, doc, "新建 " + doctype)
        name = self._name_for(doctype, doc)
        if self._exists(doctype, name):
            self.errors.append("重复新建 {} {}".format(doctype, name))
        doc["name"] = name
        doc.setdefault("docstatus", 0)
        self.db.setdefault(doctype, {})[name] = doc
        return Resp(200, {"data": doc}, "POST", url)

    def get(self, url, params=None, timeout=None):
        parts = self._path(url)
        doctype = parts[2]
        if len(parts) == 4:
            doc = self.db.get(doctype, {}).get(parts[3])
            return Resp(200, {"data": doc}, "GET", url) if doc else Resp(404, {}, "GET", url)
        filters = __import__("json").loads(params.get("filters", "[]"))
        rows = [d for d in self.db.get(doctype, {}).values() if self._match(d, filters)]
        return Resp(200, {"data": [{"name": d["name"]} for d in rows]}, "GET", url)

    def put(self, url, json=None, timeout=None):
        parts = self._path(url)
        doctype, name = parts[2], parts[3]
        doc = self.db[doctype][name]
        self._validate(doctype, dict(json), "修改 " + doctype, partial=True)
        doc.update(json)
        return Resp(200, {"data": doc}, "PUT", url)
