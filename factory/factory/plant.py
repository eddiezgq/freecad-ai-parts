# -*- coding: utf-8 -*-
"""工厂清单（第 30 轮；freecad-ai-parts ADR-0064）：一份 plant.yaml 描述一座工厂——公司、工作站、设备单元、工序、车间平面、班次、指标。

环境变量 WQ_PLANT_FILE 指定清单时，factory/data.py、wqbus/topics.py、wqbus/layout.py、sim/engine.py、sim/calendar.py、
hub/kpi.py、hub/process.py 在导入时从清单取值；没指定时用代码里的演示工厂（问渠减速器厂），行为与以前完全一样。
演示工厂导出的清单在 factory/plants/wenquest-gearbox.yaml（测试核对导出与代码逐项一致）。

命令：python -m factory.plant export-demo 输出.yaml | check 清单.yaml | template 输出.xlsx | import 填好的.xlsx 输出.yaml
"""
import os

SCHEMA_VERSION = 1
AREAS = ("office", "design", "machining", "quality", "warehouse", "logistics", "ai", "field")
STAGES = ("blank", "rough", "qt", "finish", "keyway", "gear", "harden", "grind", "inspect", "assembly", "other")
ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


class PlantError(ValueError):
    """清单有错：errors 是 [“位置：说明”]。"""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("工厂清单有 {} 处错：\n".format(len(self.errors)) + "\n".join("  - " + e for e in self.errors))


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(p):
    """逐项核对，返回错误清单（空 = 没问题）。位置用“units[3].layout”这种写法，Excel 导入时换成表名与行号。"""
    errs = []

    def need(cond, where, msg):
        if not cond:
            errs.append("{}：{}".format(where, msg))
        return cond

    if not isinstance(p, dict):
        return ["清单：不是一个对象"]
    need(p.get("version") == SCHEMA_VERSION, "version", "要写 {}".format(SCHEMA_VERSION))
    c = p.get("company") or {}
    for k in ("name", "abbr", "country", "currency", "timezone"):
        need(isinstance(c.get(k), str) and c.get(k).strip(), "company.{}".format(k), "必填")
    if isinstance(c.get("abbr"), str):
        need(c["abbr"].isalnum() and len(c["abbr"]) <= 6, "company.abbr", "公司缩写只用字母数字、不超过 6 位")
    if isinstance(c.get("timezone"), str):
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(c["timezone"])
        except Exception:  # noqa: BLE001
            errs.append("company.timezone：不认识的时区 {}（例如 Asia/Shanghai）".format(c["timezone"]))

    ws = p.get("workstations") or []
    wnames = set()
    need(ws, "workstations", "至少一个工作站")
    for i, w in enumerate(ws):
        at = "workstations[{}]".format(i)
        if not need(isinstance(w, dict) and w.get("name"), at, "要有名称"):
            continue
        need(w["name"] not in wnames, at, "工作站重名：{}".format(w["name"]))
        wnames.add(w["name"])
        need(isinstance(w.get("count"), int) and w["count"] >= 1, at + ".count", "台数是正整数")
        cost = w.get("cost")
        need(isinstance(cost, list) and len(cost) == 3 and all(_num(x) and x >= 0 for x in cost), at + ".cost",
             "费率三项（折旧、人工、能耗，元或美元/小时）")
        if w.get("power") is not None:
            pw = w["power"]
            need(isinstance(pw, list) and len(pw) == 2 and _num(pw[0]) and pw[0] > 0 and _num(pw[1]) and 0 < pw[1] <= 1,
                 at + ".power", "[主电机 kW, 传动效率 0–1]")

    us = p.get("units") or []
    uids = set()
    need(us, "units", "至少一台设备")
    for i, u in enumerate(us):
        at = "units[{}]".format(i)
        if not need(isinstance(u, dict) and u.get("id"), at, "要有编号"):
            continue
        uid = str(u["id"])
        need(set(uid) <= ID_CHARS and uid[0].isalpha(), at + ".id", "编号只用小写字母、数字和 -，字母开头：{}".format(uid))
        need(uid not in uids, at + ".id", "设备编号重复：{}".format(uid))
        uids.add(uid)
        need(u.get("area") in AREAS, at + ".area", "区域是 {} 之一".format("、".join(AREAS)))
        need(isinstance(u.get("name"), str) and u["name"], at + ".name", "要有中文名")
        if u.get("workstation") is not None:
            need(u["workstation"] in wnames, at + ".workstation", "没有这个工作站：{}".format(u["workstation"]))
        lay = u.get("layout")
        if u.get("workstation") or uid in (p.get("dashboard") or []):
            need(isinstance(lay, list) and len(lay) == 4 and all(_num(x) for x in lay) and lay[2] > 0 and lay[3] > 0,
                 at + ".layout", "车间里的设备要有平面位置 [x, y, 宽, 深]（米）")
        if u.get("area") == "logistics":
            need(isinstance(u.get("home"), list) and len(u["home"]) == 2, at + ".home", "物流小车要有停靠点 [x, y]")
        if u.get("dock") is not None:
            need(isinstance(u["dock"], list) and len(u["dock"]) == 2 and all(_num(x) for x in u["dock"]), at + ".dock",
                 "上下料点 [x, y]（米）；不写时取设备靠最近主通道一侧")
        for k in ("capacity", "setup_min", "tool_change_min"):
            if u.get(k) is not None:
                need(_num(u[k]) and u[k] >= 0, "{}.{}".format(at, k), "要是非负数")
        if u.get("wear_per_part") is not None:
            need(_num(u["wear_per_part"]) and 0 <= u["wear_per_part"] <= 1, at + ".wear_per_part", "每件刀具磨损比例 0–1")
        if u.get("spindle") is not None:
            sp = u["spindle"]
            need(isinstance(sp, list) and len(sp) == 2 and all(_num(x) and x > 0 for x in sp), at + ".spindle", "[转速, 负载]")
    for w in wnames:
        need(any(isinstance(u, dict) and u.get("workstation") == w for u in us), "workstations：" + w, "没有设备属于这个工作站")
    for i, d in enumerate(p.get("dashboard") or []):
        need(d in uids, "dashboard[{}]".format(i), "没有这台设备：{}".format(d))
    st = p.get("stores") or {}
    with_layout = {u["id"] for u in us if isinstance(u, dict) and u.get("id") and u.get("layout")}
    for k in ("raw", "finished"):
        need(st.get(k) in with_layout, "stores." + k,
             "{}要填一台有平面位置的设备编号（物流小车从这里取料或送达）".format("原材料库" if k == "raw" else "成品库"))
    need(any(isinstance(u, dict) and u.get("area") == "logistics" for u in us), "units", "至少一台物流小车（区域：物流）")

    ops = p.get("operations") or []
    onames = set()
    need(ops, "operations", "至少一道工序")
    for i, o in enumerate(ops):
        at = "operations[{}]".format(i)
        if not need(isinstance(o, dict) and o.get("name"), at, "要有工序名"):
            continue
        need(o["name"] not in onames, at, "工序重名：{}".format(o["name"]))
        onames.add(o["name"])
        need(o.get("workstation") in wnames, at + ".workstation", "没有这个工作站：{}".format(o.get("workstation")))
        units = o.get("units") or []
        if need(units, at + ".units", "至少一台能做这道工序的设备"):
            for uid in units:
                need(uid in uids, at + ".units", "没有这台设备：{}".format(uid))
        if o.get("stage") is not None:
            need(o["stage"] in STAGES, at + ".stage", "阶段是 {} 之一".format("、".join(STAGES)))

    f = p.get("floor") or {}
    need(_num(f.get("length_m")) and _num(f.get("width_m")), "floor", "车间长、宽（米）")
    need(isinstance(f.get("aisles_y"), list) and f["aisles_y"] and all(_num(x) for x in f["aisles_y"]), "floor.aisles_y",
         "横向主通道的 y 坐标（至少一条）")
    need(_num(f.get("cross_x")), "floor.cross_x", "纵向通道的 x 坐标")
    if _num(f.get("length_m")) and _num(f.get("width_m")):
        for i, u in enumerate(us):
            lay = isinstance(u, dict) and u.get("layout")
            if isinstance(lay, list) and len(lay) == 4 and all(_num(x) for x in lay):
                need(0 <= lay[0] <= f["length_m"] and 0 <= lay[1] <= f["width_m"], "units[{}].layout".format(i),
                     "位置在车间外（车间 {} × {} 米）".format(f["length_m"], f["width_m"]))

    s = p.get("shift") or {}
    per = s.get("periods")
    need(isinstance(per, list) and per and all(isinstance(x, list) and len(x) == 2 for x in per), "shift.periods",
         "班次时段 [[开始, 结束], …]，如 [[\"08:00:00\", \"12:00:00\"]]")
    if isinstance(per, list):
        import re
        ok = all(isinstance(x, list) and len(x) == 2 and all(isinstance(t, str) and re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", t)
                                                               for t in x) for x in per)
        if need(ok, "shift.periods", "时间要写成带引号的 \"08:00:00\"（不加引号 YAML 会当成数字）"):
            need(all(_minutes(a) < _minutes(b) for a, b in per) and all(_minutes(per[i][1]) <= _minutes(per[i + 1][0])
                                                                      for i in range(len(per) - 1)),
                 "shift.periods", "时段要从早到晚、不重叠")
    need(isinstance(s.get("workdays"), list) and s["workdays"] and all(d in range(7) for d in s["workdays"]),
         "shift.workdays", "工作日 0–6（0 是周一）")
    need(_num(s.get("max_overtime_min")) and 0 <= s["max_overtime_min"] <= 480, "shift.max_overtime_min", "每天加班上限 0–480 分钟")
    k = p.get("kpi") or {}
    for key in ("on_time", "oee", "fpy"):
        need(_num(k.get(key)) and 0 < k[key] <= 1, "kpi." + key, "目标是 0–1 的小数")
    if p.get("suppliers") is not None:
        need(isinstance(p["suppliers"], dict) and all(isinstance(v, dict) and v.get("name") for v in p["suppliers"].values()),
             "suppliers", "{代号: {name, lead}}")
    if p.get("customers") is not None:
        need(isinstance(p["customers"], list) and all(isinstance(x, str) and x for x in p["customers"]), "customers", "客户名称的列表")
    return errs


def _minutes(t):
    h, m, *rest = (int(x) for x in str(t).split(":"))
    return h * 60 + m + (rest[0] / 60 if rest else 0)


def derive(p):
    """清单 → 各模块用的常量（与代码里演示工厂常量同样的形状）。"""
    units = p["units"]
    ws = p["workstations"]
    ops = p["operations"]
    f, s = p["floor"], p["shift"]
    per = [tuple(x) for x in s["periods"]]
    return {
        "COMPANY": dict(p["company"]),
        "DEMO_DATA": bool(p.get("demo_data", False)),
        "WORKSTATIONS": {w["name"]: (w["count"], tuple(w["cost"])) for w in ws},
        "WORKCENTER_POWER": {w["name"]: tuple(w["power"]) for w in ws if w.get("power")},
        "OPERATIONS": {o["name"]: o["workstation"] for o in ops},
        "INSPECTION_OPS": {o["name"] for o in ops if o.get("inspection")},
        "STAGE": {o["name"]: o["stage"] for o in ops if o.get("stage")},
        "OP_UNITS": {o["name"]: list(o["units"]) for o in ops},
        "UNITS": {u["id"]: (u["area"], u["name"], u.get("name_en") or u["name"], u.get("workstation")) for u in units},
        "MACHINES": tuple(p.get("dashboard") or [u["id"] for u in units if u["area"] in ("machining", "quality")]),
        "PLC_UNITS": {u["id"]: u["plc"] for u in units if u.get("plc")},
        "LAYOUT": {u["id"]: tuple(u["layout"]) for u in units if u.get("layout")},
        "HEIGHT": {u["id"]: u["height_m"] for u in units if u.get("height_m") is not None},
        "AGV_HOME": {u["id"]: tuple(u["home"]) for u in units if u.get("home")},
        "DOCK": {u["id"]: tuple(u["dock"]) for u in units if u.get("dock")},
        "STORES": dict(p["stores"]),
        "FLOOR": (f["length_m"], f["width_m"]),
        "AISLES": tuple(f["aisles_y"]),
        "CROSS_X": f["cross_x"],
        "CAPACITY": {u["id"]: u["capacity"] for u in units if u.get("capacity") not in (None, 1)},
        "SETUP_MIN": {u["id"]: u["setup_min"] for u in units if u.get("setup_min") is not None},
        "WEAR_PER_PART": {u["id"]: u["wear_per_part"] for u in units if u.get("wear_per_part") is not None},
        "SPINDLE": {u["id"]: tuple(u["spindle"]) for u in units if u.get("spindle")},
        "TOOL_CHANGE_MIN": {u["id"]: u["tool_change_min"] for u in units if u.get("tool_change_min") is not None},
        "SHIFT": per,
        "SHIFT_MIN": int(round(sum(_minutes(b) - _minutes(a) for a, b in per))),
        "CAL_START": str(per[0][0])[:5], "CAL_END": str(per[-1][1])[:5],
        "WORKDAYS": tuple(s["workdays"]), "MAX_OT_MIN": int(s["max_overtime_min"]),
        "TARGET": {k: p["kpi"][k] for k in ("on_time", "oee", "fpy")},
        "SUPPLIERS": p.get("suppliers"),
        "CUSTOMERS": p.get("customers"),
    }


def load(path):
    """读清单并校验，返回 derive() 的结果；有错抛 PlantError。"""
    import yaml
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    errs = validate(raw)
    if errs:
        raise PlantError(errs)
    out = derive(raw)
    out["SOURCE"] = os.path.abspath(path)
    out["ID"] = raw.get("id") or os.path.splitext(os.path.basename(path))[0]
    return out


_ACTIVE = []


def active():
    """WQ_PLANT_FILE 指定的清单（只读一次）；没指定时 None（用代码里的演示工厂）。"""
    if not _ACTIVE:
        path = os.environ.get("WQ_PLANT_FILE", "").strip()
        _ACTIVE.append(load(path) if path else None)
    return _ACTIVE[0]


def company():
    """当前工厂的公司（清单里的，或演示工厂的）。"""
    p = active()
    if p:
        return p["COMPANY"]
    return dict(DEMO_COMPANY)


def is_demo():
    p = active()
    return p is None or p["DEMO_DATA"]


DEMO_SHORT = "问渠减速器厂"


def display_name():
    """页面、AI 提示词里的厂名：演示工厂用简称，企业工厂用清单里的公司名。"""
    return DEMO_SHORT if is_demo() else company()["name"]


def brief():
    """企业工厂的概况（AI 提示词用）：工作站、工序、客户。演示工厂的提示词另有一段，不用它。"""
    p = active() or {}
    ws = "、".join("{}（{} 台）".format(k, v[0]) for k, v in (p.get("WORKSTATIONS") or {}).items())
    ops = "、".join(p.get("OPERATIONS") or {})
    cus = "、".join(p.get("CUSTOMERS") or []) or "（清单里没有登记）"
    return ("工厂数据：工作站 {}；工序 {}。产品从设计经“转为生产物料”进来，物料、BOM、工艺路线以 ERPNext 为准。"
            "客户：{}。").format(ws, ops, cus)


DEMO_COMPANY = {"name": "问渠减速器厂 WenQuest Gearbox (Demo)", "abbr": "WQ", "country": "United States",
                "currency": "USD", "timezone": "America/New_York"}


# ---------------------------------------------------------------- 演示工厂导出（只在命令行、测试里用）
def export_demo():
    """把代码里的演示工厂常量导出成清单（dict）。要能导入 factory/digital 下的模块。"""
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    dig = os.path.join(os.path.dirname(here), "digital")
    if dig not in sys.path:
        sys.path.insert(0, dig)
    from factory import data as F
    from wqbus import layout as L
    from wqbus import topics as T
    from sim import calendar as CAL
    from sim import engine as E
    from hub import kpi as K
    from hub import process as P
    ws = []
    for name, (count, cost) in F.WORKSTATIONS.items():
        w = {"name": name, "count": count, "cost": list(cost)}
        if name in P.WORKCENTER_POWER:
            w["power"] = list(P.WORKCENTER_POWER[name])
        ws.append(w)
    units = []
    for uid, (area, name, en, wsn) in T.UNITS.items():
        u = {"id": uid, "area": area, "name": name, "name_en": en}
        if wsn:
            u["workstation"] = wsn
        if uid in L.LAYOUT:
            u["layout"] = list(L.LAYOUT[uid])
            u["dock"] = list(L.dock(uid))
        if uid in L.AGV_HOME:
            u["home"] = list(L.AGV_HOME[uid])
        if uid in DEMO_HEIGHT:
            u["height_m"] = DEMO_HEIGHT[uid]
        if uid in E.CAPACITY:
            u["capacity"] = E.CAPACITY[uid]
        for k, src in (("setup_min", E.SETUP_MIN), ("wear_per_part", E.WEAR_PER_PART), ("tool_change_min", E.TOOL_CHANGE_MIN)):
            if uid in src:
                u[k] = src[uid]
        if uid in E.SPINDLE:
            u["spindle"] = list(E.SPINDLE[uid])
        if uid in T.PLC_UNITS:
            u["plc"] = T.PLC_UNITS[uid]
        units.append(u)
    stage = P.STAGE
    ops = []
    for name, wsn in F.OPERATIONS.items():
        o = {"name": name, "workstation": wsn, "units": list(E.OP_UNITS[name])}
        if name in stage:
            o["stage"] = stage[name]
        if name in F.INSPECTION_OPS:
            o["inspection"] = True
        ops.append(o)
    cal = CAL.Calendar()
    return {
        "version": SCHEMA_VERSION, "id": "wenquest-gearbox", "demo_data": True,
        "company": dict(DEMO_COMPANY),
        "workstations": ws, "units": units, "dashboard": list(T.MACHINES), "operations": ops,
        "stores": {"raw": E.RAW_STORE, "finished": E.FG_STORE},
        "floor": {"length_m": L.FLOOR[0], "width_m": L.FLOOR[1], "aisles_y": list(L.AISLES), "cross_x": L.CROSS_X},
        "shift": {"periods": [list(x) for x in F.SHIFT], "workdays": list(cal.workdays), "max_overtime_min": CAL.MAX_OT_MIN},
        "kpi": dict(K.TARGET),
        "suppliers": {k: dict(v) for k, v in F.SUPPLIERS.items()},
        "customers": list(F.CUSTOMERS),
    }


# 3D 车间里的设备高度（米）：原在网页 workshop3d.js，现由清单给出、经 /api/layout 送到网页
DEMO_HEIGHT = {"ht-01": 2.6, "store-01": 3, "store-02": 3, "hmc-01": 2.4, "vmc-01": 2.3, "cnc-l01-a": 1.8, "cnc-l01-b": 1.8,
               "grd-01": 1.7, "hob-01": 2, "key-01": 1.6, "saw-01": 1.2, "qc-01": 1.5, "asm-01": 1.0, "test-01": 1.3}


def _write_yaml(d, path):
    import yaml
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# 工厂清单（ADR-0064）。改完用 python -m factory.plant check 本文件 校验。\n")
        fh.write("# 字段说明见 docs/enterprise-onboarding.md。\n")
        yaml.safe_dump(d, fh, allow_unicode=True, sort_keys=False, width=200)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m factory.plant", description="工厂清单：导出演示工厂、校验")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export-demo", help="把演示工厂导出成清单").add_argument("out")
    sub.add_parser("check", help="校验清单").add_argument("plant")
    t = sub.add_parser("template", help="生成 Excel 模板（演示工厂填好作样例；给了 --from 就用那份清单填）")
    t.add_argument("out")
    t.add_argument("--from", dest="src")
    i = sub.add_parser("import", help="Excel → 清单（并校验）")
    i.add_argument("xlsx")
    i.add_argument("out")
    a = ap.parse_args(argv)
    if a.cmd == "template":
        from . import plant_xlsx as X
        src = None
        if a.src:
            import yaml
            with open(a.src, encoding="utf-8") as fh:
                src = yaml.safe_load(fh)
        X.write_template(a.out, src)
        print("已生成模板：" + a.out)
        return 0
    if a.cmd == "import":
        from . import plant_xlsx as X
        try:
            p = X.import_workbook(a.xlsx)
        except PlantError as e:
            print(e)
            return 1
        _write_yaml(p, a.out)
        print("已导入：{} → {}（{} 个工作站、{} 台设备、{} 道工序）".format(
            a.xlsx, a.out, len(p["workstations"]), len(p["units"]), len(p["operations"])))
        return 0
    if a.cmd == "export-demo":
        _write_yaml(export_demo(), a.out)
        print("已导出：" + a.out)
        return 0
    try:
        p = load(a.plant)
    except PlantError as e:
        print(e)
        return 1
    print("清单无误：{}，{} 个工作站、{} 台设备、{} 道工序".format(
        p["COMPANY"]["name"], len(p["WORKSTATIONS"]), len(p["UNITS"]), len(p["OPERATIONS"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
