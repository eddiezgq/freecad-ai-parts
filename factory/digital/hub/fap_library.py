# -*- coding: utf-8 -*-
"""选型零件库（本仓库 ADR-0058 第 4 条、M10 第 6d 项）：工厂直接读 FreeCAD AI Parts 的零件库——公共库（data/library）
叠加企业库（企业自选的文件夹，同 id 以企业库为准），与 FreeCAD 里选型用的是同一份数据、同样带资料出处。

只读组件 JSON，不改；参数照原样给出（值、条件、来源），不换算、不补缺。
"""
import json
import os
from pathlib import Path

CATEGORIES = {"servo_motor": "伺服电机", "reducer": "减速器", "drive": "驱动器", "bearing": "轴承", "adapter": "转接件"}
# 列表里显示的关键参数（有就显示，没有就空）
KEY = {"servo_motor": ("rated_power_w", "rated_torque_nm", "peak_torque_nm", "rated_speed_rpm", "mass_kg"),
       "reducer": ("ratio", "rated_torque_nm", "repeated_peak_torque_nm", "max_input_speed_rpm", "mass_kg"),
       "drive": ("rated_output_power_w", "rated_current_a", "peak_current_a", "mass_kg"),
       "bearing": ("dynamic_load_rating_n", "static_load_rating_n", "limiting_speed_rpm", "mass_kg"),
       "adapter": ("mass_kg",)}


def _dirs():
    out = []
    pub = os.environ.get("FAP_LIBRARY_DIR", "/fap/library")
    ent = os.environ.get("FAP_ENTERPRISE_DIR", "/fap/enterprise")
    if Path(pub).is_dir():
        out.append(("public", Path(pub)))
    if Path(ent, "components").is_dir():
        out.append(("enterprise", Path(ent, "components")))
    return out


def load():
    """{id: (层, 组件)}：企业库覆盖公共库。"""
    comps = {}
    for layer, root in _dirs():
        for p in sorted(root.rglob("*.json")):
            try:
                c = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(c, dict) and c.get("id") and c.get("category"):
                comps[c["id"]] = (layer, c)
    return comps


def _value(pv):
    if not isinstance(pv, dict):
        return None
    for k in ("value", "nominal"):
        if k in pv:
            return pv[k]
    if "min" in pv or "max" in pv:
        return "{}–{}".format(pv.get("min", ""), pv.get("max", ""))
    return None


def summary(layer, c):
    params = c.get("params") or {}
    return {"id": c["id"], "category": c["category"], "category_name": CATEGORIES.get(c["category"], c["category"]),
            "vendor": c.get("vendor"), "model": c.get("model"), "library": layer,
            "params": {k: _value(params.get(k)) for k in KEY.get(c["category"], ()) if k in params}}


def search(category="", q=""):
    q = q.strip().lower()
    out = []
    for cid, (layer, c) in sorted(load().items()):
        if category and c["category"] != category:
            continue
        text = " ".join(str(c.get(k, "")) for k in ("id", "vendor", "model")).lower()
        if q and not all(w in text for w in q.split()):
            continue
        out.append(summary(layer, c))
    return out


def get(cid):
    hit = load().get(cid)
    if hit is None:
        return None
    layer, c = hit
    return dict(c, library=layer)
