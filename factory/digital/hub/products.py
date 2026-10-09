# -*- coding: utf-8 -*-
"""工厂接收新产品（本仓库 ADR-0061）：FreeCAD 发布来的方案经人确认后成为生产物料。

工厂主数据原来只有代码里的演示产品（factory/factory/data.py：ITEMS、BOMS、ROUTINGS、SUPPLIERS）。这里：
- build()：由方案（cad_design 的 BOM + 自制件 + 总装工艺）与工程师补的采购信息，组成“生产物料规格”（纯函数）：
  要建的供应商、物料（成品、外购件、自制件、新原材料）、工艺路线、BOM（自下而上）；
- 规格就是“转为生产物料”提议的预览内容，人确认后由桥接在 ERPNext 建供应商、物料、BOM（与其他提议同一条路）；
- 桥接报告执行完成后 register() 记进产品登记表（fap_product），并 merge() 并入工厂主数据——MRP、MES、看板、
  厂情中枢照原样使用；枢纽启动时 load_all() 把登记表并回来。

规则：工序只能用工厂现有的（F.OPERATIONS）；原材料可引用现有的，也可新建（要写供应商）；采购件交期、单价由工程师填，
没填的为空（MRP 标“交期待确认”），不估。
"""
import json
import re

from factory import data as F
from factory import plant as _plant
from hub import ai as _ai
from hub import process as _process

SCHEMA = """
create table if not exists fap_product (
    code          text primary key,
    mode          text not null,
    revision      integer not null,
    spec          jsonb not null,
    registered_at timestamptz not null default now()
);
"""
CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
_REGISTERED = set()
_PROCESS = {}      # 登记产品的自制件给出的粗基准与装夹（ADR-0062）：工厂起草工艺规程时用
_RAW = {}          # 登记产品带来的新原材料（物料编号 → 物料定义）：再次转为生产物料时一并发给 ERP，ERP 换过库也能补建


class ProductError(ValueError):
    pass


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s[:40] or "vendor"


def buy_code(component_id):
    """零件库组件 id → ERP 物料编号（取 id 最后一段，大写）：servo_motor.yaskawa-….sgm7j-04a → SGM7J-04A"""
    return re.sub(r"[^A-Z0-9.-]", "-", str(component_id).split(".")[-1].upper())[:40]


def _routing(rows, what):
    out = []
    for r in rows or []:
        if not isinstance(r, (list, tuple)) or len(r) != 2:
            raise ProductError("{} 的工序须为 [工序, 分钟]".format(what))
        op, mins = str(r[0]), float(r[1])
        if op not in F.OPERATIONS:
            raise ProductError("{} 的工序“{}”不是工厂现有工序（可用：{}）".format(what, op, "、".join(F.OPERATIONS)))
        if mins <= 0:
            raise ProductError("{} 的工序“{}”工时须大于 0".format(what, op))
        out.append([op, mins])
    if not out:
        raise ProductError("{} 没有工艺路线".format(what))
    return out


def build(design, extra=None):
    """design：cad_link.design() 的结果（含 bom、made_parts、assembly_routing）；extra：工程师补的
    {"purchase": {组件 id: {"lead_days", "price"}}, "price": 成品单价, "made_parts"/"assembly_routing"（覆盖方案里的）}"""
    extra = extra or {}
    code = str(design["code"]).upper()
    if not CODE.match(code):
        raise ProductError("方案编号不能用作物料编号：{}".format(code))
    if code in F.ITEMS and code not in _REGISTERED:
        raise ProductError("物料 {} 已是工厂原有物料，请换方案编号".format(code))
    made = extra.get("made_parts", design.get("made_parts")) or []
    assy = _routing(extra.get("assembly_routing", design.get("assembly_routing")), "成品 {}".format(code))
    purchase = extra.get("purchase") or {}
    suppliers, items, routings, boms, process = {}, {}, {}, [], {}
    children = []
    for r in design["bom"]:
        cid = r["component_id"]
        ic = buy_code(cid)
        vendor = r.get("vendor") or "未知厂商"
        key = "lib:" + slug(vendor)
        p = purchase.get(cid) or {}
        lead = p.get("lead_days")
        old = suppliers.get(key) or {"name": vendor, "lead": None}
        suppliers[key] = {"name": vendor, "lead": int(lead) if lead not in (None, "") else old["lead"]}
        items[ic] = {"item_code": ic, "item_name": "{} {}".format(vendor, r.get("model") or ic)[:140], "kind": "buy",
                     "uom": "Nos", "price": float(p["price"]) if p.get("price") not in (None, "") else None,
                     "supplier": key, "component_id": cid,
                     "description": "零件库 {}；资料：{}".format(cid, "、".join(r.get("source_docs") or []) or "—")}
        children.append([ic, int(r.get("quantity") or 1)])
    for m in made:
        mc = str(m.get("code") or "").upper()
        if not CODE.match(mc):
            raise ProductError("自制件编号不合规：{}".format(m.get("code")))
        if mc in F.ITEMS and mc not in _REGISTERED and F.ITEMS[mc][1] != "make":
            raise ProductError("自制件 {} 与工厂原有物料重名".format(mc))
        raw = m.get("raw") or {}
        rc = str(raw.get("item_code") or "").upper()
        if not rc:
            raise ProductError("自制件 {} 没写毛坯 / 原材料".format(mc))
        if rc not in F.ITEMS:
            if not raw.get("name") or raw.get("supplier") not in F.SUPPLIERS:
                raise ProductError("新原材料 {} 要写名称与工厂现有的供应商（{}）".format(rc, "、".join(F.SUPPLIERS)))
            items[rc] = {"item_code": rc, "item_name": raw["name"], "kind": "raw", "uom": raw.get("uom") or "Kg",
                         "price": raw.get("price"), "supplier": raw["supplier"], "description": raw.get("note") or ""}
        elif rc in _RAW:
            items[rc] = dict(_RAW[rc])
        elif not _plant.is_demo() and F.ITEMS[rc][1] == "raw":
            # 企业工厂（ADR-0064）的 ERPNext 没有演示物料：引用到的原材料一并建；单价是演示工厂的，不带过去
            name, _kind, uom, _price, sup, _qit, note = F.ITEMS[rc]
            items[rc] = {"item_code": rc, "item_name": name, "kind": "raw", "uom": uom, "price": None, "supplier": sup,
                         "description": note or ""}
        rq = float(m.get("raw_qty") or 0)
        if rq <= 0:
            raise ProductError("自制件 {} 的毛坯用量须大于 0".format(mc))
        rt = "RT-" + mc
        routings[rt] = _routing(m.get("routing"), "自制件 {}".format(mc))
        items[mc] = {"item_code": mc, "item_name": str(m.get("name") or mc)[:140], "kind": "make", "uom": "Nos",
                     "price": None, "supplier": None, "description": str(m.get("material") or "")}
        boms.append({"item": mc, "routing": rt, "items": [[rc, rq]]})
        hint = {k: str(m[k]).strip()[:120] for k in ("datum", "clamping") if m.get(k)}
        if hint:
            process[mc] = hint
        children.append([mc, int(m.get("qty") or 1)])
    rt = "RT-" + code
    routings[rt] = assy
    items[code] = {"item_code": code, "item_name": str(design.get("name") or code)[:140], "kind": "fg", "uom": "Nos",
                   "price": float(extra["price"]) if extra.get("price") not in (None, "") else None, "supplier": None,
                   "description": "FreeCAD AI Parts 方案 {} 第 {} 版".format(design["code"], design.get("revision"))}
    boms.append({"item": code, "routing": rt, "items": children})
    return {"code": code, "design": design["code"], "revision": design.get("revision"), "name": design.get("name"),
            "suppliers": [{"key": k, "supplier_group": F.SUPPLIER_GROUP, **v} for k, v in suppliers.items()],
            "items": [{**it, "item_group": F.KIND_GROUP[it["kind"]]} for it in items.values()],
            "routings": routings, "boms": boms, "process": process,
            "operations": {op: F.OPERATIONS[op] for rows in routings.values() for op, _ in rows},
            "warnings": ["{} 交期待确认（没填采购提前期）".format(s["name"]) for s in suppliers.values() if s["lead"] is None]}


def merge(spec):
    """并入工厂主数据（同一进程里的 MRP、MES、看板、厂情中枢都从这里读）。"""
    for s in spec["suppliers"]:
        F.SUPPLIERS[s["key"]] = {"name": s["name"], "lead": s["lead"]}
    for it in spec["items"]:
        if it["kind"] == "raw":
            _RAW.setdefault(it["item_code"], {k: v for k, v in it.items() if k != "item_group"})
            if it["item_code"] in F.ITEMS:
                continue
        F.ITEMS[it["item_code"]] = (it["item_name"], it["kind"], it["uom"], it.get("price"), it.get("supplier"), None,
                                    it.get("description") or "")
    for rt, rows in spec["routings"].items():
        F.ROUTINGS[rt] = [tuple(r) for r in rows]
    for b in spec["boms"]:
        F.BOMS[b["item"]] = (b["routing"], [tuple(c) for c in b["items"]])
    _PROCESS.update(spec.get("process") or {})
    _REGISTERED.update(it["item_code"] for it in spec["items"] if it["kind"] in ("fg", "make"))
    _REGISTERED.add(spec["code"])


def process_hint(item):
    """登记产品的自制件给出的粗基准与装夹 {datum?, clamping?}（ADR-0062），没有时 {}。"""
    return dict(_PROCESS.get(item) or {})


def is_product(code):
    return code in _REGISTERED and code in F.ITEMS and F.ITEMS[code][1] == "fg"


def init(db):
    db.x(SCHEMA)
    load_all(db)


def load_all(db):
    for r in db.q("select spec from fap_product order by registered_at"):
        merge(r["spec"])


def register(db, spec, mode):
    db.x("insert into fap_product (code, mode, revision, spec) values (%s,%s,%s,%s) on conflict (code) do update "
         "set revision=excluded.revision, spec=excluded.spec, registered_at=now()",
         (spec["code"], mode, spec.get("revision") or 1, json.dumps(spec, ensure_ascii=False)))
    merge(spec)


def products(db):
    return [{"code": r["code"], "mode": r["mode"], "revision": r["revision"], "name": r["spec"].get("name"),
             "registered_at": r["registered_at"].isoformat(), "items": len(r["spec"]["items"])}
            for r in db.q("select * from fap_product order by registered_at desc")]


def _on_proposal_done(db, action, preview, mode):
    """“转为生产物料”的提议在 ERPNext 建好物料与 BOM 后，登记进工厂主数据（ADR-0061）。"""
    if action == "cad_to_erp":
        register(db, preview, mode)


# 挂到共有代码留的口子上（ADR-0067）：提议执行完 → 登记产品；起草工艺规程 → 自制件的粗基准与装夹
if _on_proposal_done not in _ai.ON_PROPOSAL_DONE:
    _ai.ON_PROPOSAL_DONE.append(_on_proposal_done)
if process_hint not in _process.PLAN_HINTS:
    _process.PLAN_HINTS.append(process_hint)
