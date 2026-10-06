"""换件建议（ADR-0052）：把一个实例换成同品类的其他组件，连接不变，按校验窗口的同一规则整体重算。纯函数。

- suggest：候选（不通过的不列）、排序、与当前相比结论变化的校验项
- swap_calls：换上的工具调用序列（删除、原位姿放入、按原顺序重建相关连接）
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from engine.values import capacity
from freecad_addon.core.live_check import CHECK_NAMES, STATUS_TEXT, check

_RANK = {"pass": 0, "warn": 1, "unknown": 2, "not_applicable": 2, "fail": 3}


@dataclass
class Suggestion:
    component_id: str
    model: str
    overall: str
    unknown_count: int
    mass_kg: float | None
    changes: list[str] = field(default_factory=list)  # 如“C2 圆柱配合：不通过 → 通过”

    def to_dict(self) -> dict:
        return {"component_id": self.component_id, "model": self.model, "overall": self.overall,
                "overall_text": STATUS_TEXT.get(self.overall, self.overall), "unknown_count": self.unknown_count,
                "mass_kg": self.mass_kg, "changes": self.changes}


def _replaced(layout: Mapping, instance: str, component_id: str) -> dict:
    return {"instances": [{**i, "component": component_id} if i["instance"] == instance else dict(i)
                          for i in layout.get("instances", [])],
            "connections": [dict(c) for c in layout.get("connections", [])]}


def _label(c: Mapping) -> str:
    name = CHECK_NAMES.get(c["check"], "")
    return f"{c['check']} {name}".strip()


def suggest(layout: Mapping, instance: str, lookup: Callable[[str], dict | None],
            candidates: list[dict], requirement: Mapping | None = None, top_n: int = 5) -> dict:
    """返回 {instance, current: {component_id, overall}, suggestions: [...], total}。
    candidates 为组件库中同品类的组件（调用方给出，便于在库变大时先筛选）。"""
    current_item = next((i for i in layout.get("instances", []) if i["instance"] == instance), None)
    if current_item is None:
        raise ValueError(f"场景中没有实例 {instance}")
    current = lookup(current_item["component"])
    if current is None:
        raise ValueError(f"组件库中没有 {current_item['component']}")
    base = check(layout, lookup, requirement)
    before = {c["check"]: c["status"] for c in base["checks"]}
    out = []
    for comp in candidates:
        if comp["id"] == current["id"] or comp.get("category") != current.get("category"):
            continue
        r = check(_replaced(layout, instance, comp["id"]), lookup, requirement)
        if r["overall"] == "fail":
            continue
        changes = [f"{_label(c)}：{STATUS_TEXT.get(before.get(c['check']), before.get(c['check']))} → "
                   f"{STATUS_TEXT.get(c['status'], c['status'])}"
                   for c in r["checks"] if before.get(c["check"]) != c["status"]]
        unknown = sum(1 for c in r["checks"] if c["status"] == "unknown")
        mass = capacity(comp.get("params", {}).get("mass_kg"))
        out.append(Suggestion(comp["id"], f"{comp.get('vendor', '')} {comp.get('model', comp['id'])}".strip(),
                              r["overall"], unknown, mass, changes))
    out.sort(key=lambda s: (_RANK.get(s.overall, 9), s.unknown_count,
                            float("inf") if s.mass_kg is None else s.mass_kg, s.component_id))
    return {"instance": instance, "current": {"component_id": current["id"], "overall": base["overall"]},
            "suggestions": [s.to_dict() for s in out[:top_n]], "total": len(out)}


def swap_calls(layout: Mapping, instance: str, component_id: str) -> list[tuple[str, dict]]:
    """换上的调用序列：删除实例、在原位姿放入新组件，再按原顺序重建与它相关的连接（保留 roll 与 offset）。"""
    item = next((i for i in layout.get("instances", []) if i["instance"] == instance), None)
    if item is None:
        raise ValueError(f"场景中没有实例 {instance}")
    rot = item.get("rotation") or {}
    calls: list[tuple[str, dict]] = [
        ("place_component", {"instance": instance, "remove": True}),
        ("place_component", {"instance": instance, "component_id": component_id,
                             "position_mm": list(item.get("position_mm", [0.0, 0.0, 0.0])),
                             "rotation_axis": list(rot.get("axis", [0.0, 0.0, 1.0])),
                             "rotation_deg": rot.get("angle_deg", 0.0)}),
    ]
    for c in layout.get("connections", []):
        if instance in (c["a"].split(".", 1)[0], c["b"].split(".", 1)[0]):
            calls.append(("connect_ports", {"a": c["a"], "b": c["b"], "roll_deg": c.get("roll_deg", 0.0),
                                            "offset_mm": c.get("offset_mm", 0.0)}))
    return calls
