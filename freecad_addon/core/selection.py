"""选型面板的整理与放入布局（ADR-0051 第 1 条）。纯函数。

- candidate_rows：compose_chain 的返回 → 候选列表的行
- place_calls：把选中的系统放进场景的工具调用序列（先清空，再放置，再按规范顺序连接机械端口）
- side_calls：放置后，把没有机械连接的实例（如驱动器）挪到已配合组件的包围盒旁边
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from freecad_addon.core.project import clear_calls
from freecad_addon.core.system_layout import mechanical_connections

STATUS_TEXT = {"pass": "通过", "warn": "通过（有提醒）", "fail": "不通过", "unknown": "待确认",
               "not_applicable": "不适用"}
ROLES = (("servo_motor", "电机"), ("reducer", "减速器"), ("drive", "驱动器"), ("adapter", "转接件"))
GAP_MM = 50.0  # 未配合实例与已配合组件包围盒之间的间隙


@dataclass
class CandidateRow:
    rank: int
    overall: str
    status: str
    parts: dict[str, list[str]]  # 品类 → 型号
    mass_kg: float | None
    min_margin: float | None
    explanation: str
    system: dict = field(repr=False)


def _model(cid: str, lookup: Callable[[str], dict | None]) -> tuple[str, str]:
    comp = lookup(cid)
    if comp is None:
        return "", cid
    return comp.get("category", ""), f"{comp.get('vendor', '')} {comp.get('model', cid)}".strip()


def candidate_rows(result: Mapping, lookup: Callable[[str], dict | None]) -> list[CandidateRow]:
    rows = []
    for n, c in enumerate(result.get("candidates", []), start=1):
        parts: dict[str, list[str]] = {}
        for item in c["system"].get("components", []):
            cat, name = _model(item["component"], lookup)
            parts.setdefault(cat, []).append(name)
        rows.append(CandidateRow(n, c.get("overall", ""), STATUS_TEXT.get(c.get("overall", ""), c.get("overall", "")),
                                 parts, c.get("mass_kg"), c.get("min_margin"), c.get("explanation", ""),
                                 c["system"]))
    return rows


def cells(row: CandidateRow) -> list[str]:
    """表格各栏文字：序号、结论、电机、减速器、驱动器、转接件、质量、最小裕度。缺失的质量与裕度显示“未知”。"""
    names = ["、".join(row.parts.get(cat, [])) or "—" for cat, _ in ROLES]
    mass = "未知" if row.mass_kg is None else f"{row.mass_kg:.2f} kg"
    margin = "未知" if row.min_margin is None else f"{row.min_margin:.2f}"
    return [str(row.rank), row.status, *names, mass, margin]


HEADERS = ["#", "结论", *[label for _, label in ROLES], "质量", "最小裕度"]


def place_calls(system: Mapping, current_layout: Mapping,
                lookup: Callable[[str], dict | None]) -> tuple[list[tuple[str, dict]], list[str]]:
    """把系统放进场景的调用序列，及没有机械连接的实例（放置后由 side_calls 挪开）。
    先删除当前场景的全部实例；各实例放在原点，再按 system_layout 的规范顺序连接机械端口（被连接的一方整组移动）。"""
    ordered, _ = mechanical_connections(dict(system), lookup)
    calls = clear_calls(current_layout)
    for item in system.get("components", []):
        calls.append(("place_component", {"instance": item["instance"], "component_id": item["component"]}))
    mated: set[str] = set()
    for c in ordered:
        calls.append(("connect_ports", {"a": c["a"], "b": c["b"]}))
        mated |= {c["a"].split(".", 1)[0], c["b"].split(".", 1)[0]}
    unmated = [i["instance"] for i in system.get("components", []) if i["instance"] not in mated]
    return calls, unmated


def side_calls(layout: Mapping, unmated: list[str], gap_mm: float = GAP_MM) -> list[tuple[str, dict]]:
    """把未配合的实例沿 x 方向依次排在已配合组件包围盒的右侧（各留 gap_mm）。包络缺尺寸的实例不挪。"""
    boxes = {i["instance"]: i.get("bbox_mm") for i in layout.get("instances", [])}
    poses = {i["instance"]: i for i in layout.get("instances", [])}
    placed = [b for n, b in boxes.items() if n not in unmated and b]
    edge = max((b["max_mm"][0] for b in placed), default=0.0)
    calls = []
    for name in unmated:
        box = boxes.get(name)
        if not box:
            continue
        shift = edge + gap_mm - box["min_mm"][0]
        pos = list(poses[name].get("position_mm", [0.0, 0.0, 0.0]))
        pos[0] += shift
        rot = poses[name].get("rotation") or {}
        calls.append(("place_component", {"instance": name, "position_mm": pos,
                                          "rotation_axis": list(rot.get("axis", [0.0, 0.0, 1.0])),
                                          "rotation_deg": rot.get("angle_deg", 0.0)}))
        edge += gap_mm + (box["max_mm"][0] - box["min_mm"][0])
    return calls
