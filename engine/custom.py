"""可配置接口的定制要求（ADR-0053）：一侧端口按配套件定制（configurable）时，照录对接另一侧端口的规格与出处。纯函数。

只照录对方已有的数据（值、出处页码），不推导本侧的孔径、螺纹或公差，不补缺失值；缺失项列为待确认。
不改变任何校验结论。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

# 各端口类型要照录的规格：(字段, 名称)
FIELDS = {
    "mechanical.flange": (("pcd_mm", "分度圆直径"), ("hole_count", "孔数"), ("hole_kind", "孔的形式"),
                          ("hole_diameter_mm", "通孔直径"), ("thread", "螺纹"), ("hole_angle_offset_deg", "孔位角度偏置"),
                          ("pilot_diameter_mm", "止口直径"), ("pilot_kind", "止口形式"), ("pilot_fit", "止口公差带"),
                          ("square_size_mm", "方形法兰边长")),
    "mechanical.mount_face": (("pattern", "孔位形式"), ("pitch_x_mm", "孔距 x"), ("pitch_y_mm", "孔距 y"),
                              ("hole_count", "孔数"), ("hole_diameter_mm", "通孔直径"), ("thread", "螺纹"),
                              ("face_size_mm", "安装面尺寸")),
}
# 法兰上只在孔的形式为某值时才需要的字段
CONDITIONAL = {"hole_diameter_mm": ("hole_kind", "through"), "thread": ("hole_kind", "threaded")}
# 缺了要列为待确认的
REQUIRED = {"mechanical.flange": {"pcd_mm", "hole_count", "hole_kind", "pilot_diameter_mm"},
            "mechanical.mount_face": {"pattern", "hole_count"}}
KIND_TEXT = {"through": "通孔", "threaded": "螺纹孔", "male": "凸", "female": "凹"}


def _value_text(pv: Mapping) -> str | None:
    if "value" in pv and pv["value"] is not None:
        v = pv["value"]
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return f"{v:g}"
        if isinstance(v, str):
            return KIND_TEXT.get(v, v)
        return str(v)
    if pv.get("nominal") is not None:
        lo, hi = pv.get("tol_lower"), pv.get("tol_upper")
        tol = f"（{hi:+g} / {lo:+g}）" if lo is not None and hi is not None else ""
        return f"{pv['nominal']:g}{tol}"
    if pv.get("min") is not None or pv.get("max") is not None:
        return f"{pv.get('min', '')}–{pv.get('max', '')}"
    return None


def _source(pv: Mapping) -> str:
    src = pv.get("source") or {}
    if src.get("doc"):
        return f"{src['doc']} 第 {src['page']} 页" if src.get("page") is not None else src["doc"]
    return "（无出处）"


def _port(comp: Mapping, pid: str) -> dict | None:
    return next((p for p in comp.get("ports", []) if p["id"] == pid), None)


def _name(comp: Mapping) -> str:
    return f"{comp.get('vendor', '')} {comp.get('model', comp.get('id', ''))}".strip()


def requirement_for(target_comp: Mapping, target_port: Mapping, mate_comp: Mapping, mate_port: Mapping) -> dict:
    """target 端口按 mate 端口定制的要求。"""
    spec = mate_port.get("spec") or {}
    ptype = mate_port.get("type", "")
    fields = FIELDS.get(ptype, ())
    has_kind = any(k == "hole_kind" for k, _ in fields)
    items, missing = [], []
    for key, label in fields:
        cond = CONDITIONAL.get(key) if has_kind else None
        if cond and (spec.get(cond[0]) or {}).get("value") != cond[1]:
            continue
        pv = spec.get(key)
        value = _value_text(pv) if isinstance(pv, Mapping) else None
        if value is None:
            if key in REQUIRED.get(ptype, set()) or cond:
                missing.append(label)
            continue
        items.append({"field": key, "name": label, "value": value, "source": _source(pv)})
    head = (f"{_name(target_comp)} 的 {target_port['id']} 须按 {_name(mate_comp)} 的 {mate_port['id']} 定制")
    lines = [head] + [f"· {i['name']}：{i['value']}（{i['source']}）" for i in items]
    if missing:
        lines.append(f"· 对方数据缺：{'、'.join(missing)}，订货前须与厂商确认")
    return {"component_id": target_comp["id"], "model": _name(target_comp), "port": target_port["id"],
            "mate": {"component_id": mate_comp["id"], "model": _name(mate_comp), "port": mate_port["id"]},
            "items": items, "missing": missing, "text": "\n".join(lines)}


def custom_requirements(system: Mapping, resolve: Callable[[str], dict | None]) -> list[dict]:
    """系统中每个“一侧 configurable、另一侧不是”的连接一条定制要求；按连接顺序，去重。"""
    comps = {}
    for item in system.get("components", []):
        comp = resolve(item["component"])
        if comp is not None:
            comps[item["instance"]] = comp
    out, seen = [], set()
    for c in system.get("connections", []):
        ends = []
        for ref in (c["a"], c["b"]):
            inst, _, pid = ref.partition(".")
            comp = comps.get(inst)
            port = _port(comp, pid) if comp else None
            ends.append((inst, comp, port))
        if any(e[2] is None for e in ends):
            continue
        for (ti, tc, tp), (_mi, mc, mp) in (ends, ends[::-1]):
            if tp.get("configurable") and not mp.get("configurable") and tp["type"] in FIELDS:
                key = (ti, tp["id"], mc["id"], mp["id"])
                if key not in seen:
                    seen.add(key)
                    out.append({"instance": ti, **requirement_for(tc, tp, mc, mp)})
    return out
