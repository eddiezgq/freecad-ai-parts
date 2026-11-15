# -*- coding: utf-8 -*-
"""第 171 轮：3D 车间的“厂区 → 车间 → 工位 → 工艺文件”数据（/api/plantmap）。

全部取自工厂清单（演示工厂取代码里的同一份数据）：车间分区、设备、工序、工艺路线、工时、物料清单、测量特性、计量室抽检。
缝纫机厂另有从《缝纫机厂工艺方案》拆出的工序规程（plants/procdocs/<清单名>.json，白板图脚本生成），有就带上。不编参数。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from factory import data as F
from sim import engine as E
from sim import errors as ERR
from wqbus import layout as L
from wqbus import topics as T


AREA_ZH = {"machining": "生产", "quality": "检验", "warehouse": "库房", "logistics": "物流", "design": "研发"}


def _zone_of(zones, lay):
    x, y, w, d = lay
    for cx, cy in ((x, y), (x + w / 2, y + d / 2)):        # 清单的位置有的按中心写、有的按角写，两种都试
        for z in zones:
            x0, y0, x1, y1 = z["rect"]
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                return z["id"]
    return None


def _procdocs():
    f = os.environ.get("WQ_PLANT_FILE", "").strip()
    if not f:
        return None
    p = Path(f).parent / "procdocs" / (Path(f).stem + ".json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def build():
    act = __import__("factory.plant", fromlist=["active"]).active()
    fw, fd = L.FLOOR
    zones = [dict(z) for z in ((act or {}).get("ZONES") or [])]
    if not zones:          # 清单没写车间：整个厂算一个车间（设备按区域交错摆，按区域画框会互相压）
        zones = [{"id": "all", "name": "车间", "name_en": "Shop floor", "rect": [0, 0, fw, fd], "auto": True}]
    units = {}
    for u, lay in L.LAYOUT.items():
        meta = T.UNITS.get(u) or ("", u, u)
        area = (act["UNITS"][u][0] if act and u in act["UNITS"] else ("warehouse" if u.startswith("store") else "machining"))
        ws = act["UNITS"][u][3] if act and u in act["UNITS"] else None
        units[u] = {"name": meta[1], "name_en": meta[2], "area": area, "area_zh": AREA_ZH.get(area, area), "workstation": ws,
                    "zone": _zone_of(zones, lay) or zones[0]["id"]}
    for a in L.AGV_HOME:
        meta = T.UNITS.get(a) or ("", a, a)
        units[a] = {"name": meta[1], "name_en": meta[2], "area": "logistics", "area_zh": AREA_ZH["logistics"], "workstation": None,
                    "zone": _zone_of(zones, (*L.AGV_HOME[a], 0, 0)) or zones[0]["id"], "agv": True}
    for z in zones:
        z["units"] = [u for u, v in units.items() if v["zone"] == z["id"]]
    zones = [z for z in zones if z["units"]]

    op_units = {op: list(us) for op, us in E.OP_UNITS.items()}
    ops = {op: {"workstation": F.OPERATIONS.get(op), "units": op_units.get(op, []), "inspection": op in F.INSPECTION_OPS,
                "stage": (act or {}).get("STAGE", {}).get(op)} for op in F.OPERATIONS}
    routings = {r: [[op, m] for op, m in steps] for r, steps in F.ROUTINGS.items()}
    items = {k: {"name": v[0], "kind": v[1], "uom": v[2]} for k, v in F.ITEMS.items()}
    boms = {it: {"routing": rt, "components": [[c, items.get(c, {}).get("name", c), q, items.get(c, {}).get("uom", "")] for c, q in comps]}
            for it, (rt, comps) in F.BOMS.items()}
    used_in = {}
    for it, b in boms.items():
        for c in b["components"]:
            used_in.setdefault(c[0], []).append(it)
    meas = {f"{it}|{op}": chars for (it, op), chars in F.MEASURE.items()}
    if not meas and not act:            # 演示工厂：输出轴三坐标检验特性在仿真代码里（sim/errors.py CHARS）
        meas["SH-301|零件检验 Part inspection"] = [{"code": c, "name": n, "nominal": nom, "lo": lo, "hi": hi, "unit": "mm" if "Ra" not in n and "烧伤" not in n else ""}
                                               for c, n, nom, lo, hi in ERR.CHARS]
    sampling = {f"{it}|{op}": v for (it, op), v in (F.SAMPLING or {}).items()}
    jobs = {}
    for it, b in boms.items():
        for i, (op, _m) in enumerate(routings.get(b["routing"], [])):
            for u in op_units.get(op, []):
                jobs.setdefault(u, []).append([it, op, i])
    return {"floor": [fw, fd], "zones": zones, "units": units, "ops": ops, "routings": routings, "items": items,
            "boms": boms, "used_in": used_in, "meas": meas, "sampling": sampling, "jobs": jobs, "procdocs": _procdocs()}
