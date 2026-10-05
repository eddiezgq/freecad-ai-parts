"""方案记录（ADR-0049 第 2、4 条）：随 .FCStd 保存的方案、由记录得出的重建调用、两个场景的差异。纯函数。

记录格式 fap-project/1：
- requirement：需求（可为 None）
- layout：{instances: [{instance, component, position_mm, rotation: {axis, angle_deg}}], connections: [{a, b, roll_deg, offset_mm}]}
- check：最近一次校验 {overall, mode, checks}
- components：所用组件数据的快照 {id: 组件}（只供查看，恢复时以组件库为准）
- library、saved_at
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

FORMAT = "fap-project/1"


class ProjectError(ValueError):
    pass


def _layout(layout: Mapping) -> dict:
    """只保留重建所需的字段（去掉包围盒、刚性组等派生量）。"""
    insts = [{"instance": i["instance"], "component": i["component"],
              "position_mm": list(i.get("position_mm", [0, 0, 0])),
              "rotation": {"axis": list((i.get("rotation") or {}).get("axis", [0, 0, 1])),
                           "angle_deg": (i.get("rotation") or {}).get("angle_deg", 0.0)}}
             for i in layout.get("instances", [])]
    conns = [{"a": c["a"], "b": c["b"], "roll_deg": c.get("roll_deg", 0.0), "offset_mm": c.get("offset_mm", 0.0)}
             for c in layout.get("connections", [])]
    return {"instances": insts, "connections": conns}


def record(layout: Mapping, requirement: Mapping | None, check: Mapping | None,
           lookup: Callable[[str], dict | None], library: str = "", saved_at: str = "") -> dict:
    lay = _layout(layout)
    comps = {}
    for i in lay["instances"]:
        comp = lookup(i["component"])
        if comp is not None:
            comps[i["component"]] = comp
    chk = None if check is None else {k: check.get(k) for k in ("overall", "mode", "checks", "notes")}
    return {"format": FORMAT, "requirement": dict(requirement) if requirement else None, "layout": lay,
            "check": chk, "components": comps, "library": library, "saved_at": saved_at}


def dumps(rec: Mapping) -> str:
    return json.dumps(rec, ensure_ascii=False, sort_keys=True)


def loads(text: str) -> dict:
    try:
        rec = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ProjectError(f"方案记录不是有效的 JSON：{exc}") from exc
    if not isinstance(rec, dict) or rec.get("format") != FORMAT:
        raise ProjectError(f"方案记录格式不是 {FORMAT}")
    if not isinstance(rec.get("layout"), dict):
        raise ProjectError("方案记录缺少 layout")
    return rec


def rebuild_calls(rec: Mapping, lookup: Callable[[str], dict | None]) -> tuple[list[tuple[str, dict]], list[str]]:
    """由记录得出重建场景的工具调用序列：先按记录的位姿放置每个实例，再按顺序连接。
    组件库中缺的组件报告在第二个返回值中，相关实例与连接跳过（不用快照替代）。"""
    calls, missing = [], []
    present = set()
    for i in rec["layout"].get("instances", []):
        if lookup(i["component"]) is None:
            missing.append(f"组件库中没有 {i['component']}（实例 {i['instance']}），未恢复")
            continue
        present.add(i["instance"])
        rot = i.get("rotation") or {}
        calls.append(("place_component", {"instance": i["instance"], "component_id": i["component"],
                                          "position_mm": i.get("position_mm", [0, 0, 0]),
                                          "rotation_axis": rot.get("axis", [0, 0, 1]),
                                          "rotation_deg": rot.get("angle_deg", 0.0)}))
    for c in rec["layout"].get("connections", []):
        if c["a"].split(".", 1)[0] in present and c["b"].split(".", 1)[0] in present:
            calls.append(("connect_ports", {"a": c["a"], "b": c["b"], "roll_deg": c.get("roll_deg", 0.0),
                                            "offset_mm": c.get("offset_mm", 0.0)}))
    return calls, missing


def clear_calls(layout: Mapping) -> list[tuple[str, dict]]:
    """删除当前场景全部实例的调用序列。"""
    return [("place_component", {"instance": i["instance"], "remove": True}) for i in layout.get("instances", [])]


def diff(before: Mapping, after: Mapping, tol_mm: float = 1e-6, tol_deg: float = 1e-6) -> dict:
    """两个布局的差异（ADR-0049 第 4 条）：增加、删除、移动的实例，新增、删除的连接。"""
    a, b = _layout(before), _layout(after)
    ia = {i["instance"]: i for i in a["instances"]}
    ib = {i["instance"]: i for i in b["instances"]}

    def moved(x: dict, y: dict) -> bool:
        if x["component"] != y["component"]:
            return True
        if any(abs(p - q) > tol_mm for p, q in zip(x["position_mm"], y["position_mm"], strict=True)):
            return True
        rx, ry = x["rotation"], y["rotation"]
        if abs(rx["angle_deg"] - ry["angle_deg"]) > tol_deg:
            return True
        return rx["angle_deg"] > tol_deg and any(abs(p - q) > 1e-9 for p, q in zip(rx["axis"], ry["axis"], strict=True))

    key = lambda c: (c["a"], c["b"])
    ca, cb = {key(c) for c in a["connections"]}, {key(c) for c in b["connections"]}
    out = {"added": sorted(set(ib) - set(ia)), "removed": sorted(set(ia) - set(ib)),
           "moved": sorted(n for n in set(ia) & set(ib) if moved(ia[n], ib[n])),
           "connected": sorted(f"{x} ↔ {y}" for x, y in cb - ca),
           "disconnected": sorted(f"{x} ↔ {y}" for x, y in ca - cb)}
    out["changed"] = any(out[k] for k in ("added", "removed", "moved", "connected", "disconnected"))
    return out


def describe(d: Mapping) -> list[str]:
    """场景差异的中文说明（提案中逐行列出）。"""
    out = []
    for key, label in (("added", "增加"), ("removed", "删除"), ("moved", "移动或更换"), ("connected", "新连接"),
                       ("disconnected", "断开")):
        if d.get(key):
            out.append(f"{label}：{'、'.join(d[key])}")
    return out or ["场景没有变化"]
