"""链路模板与候选求解（issue #53，ADR-0029）。纯函数：组件库由调用方给出。

模板：电机 →（轴套）→ 减速器，电机 →（适配法兰板）→ 减速器；驱动器接电机动力与编码器。
轴径或分度圆不一致时，从组件库中找能补上的转接件；找不到的组合直接跳过。
每个组合都过全部 11 项校验；默认只返回整体为 pass 或 warn 的方案，按 ADR-0029 的规则排序。
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from engine import adapters as adapters_mod
from engine.adapters import AdapterError
from engine.result import FAIL, PASS, UNKNOWN, WARN
from engine.validate import validate
from engine.values import capacity, nominal, text

PCD_TOL_MM = 0.05
_RANK = {PASS: 0, WARN: 1, UNKNOWN: 2, FAIL: 3}


@dataclass
class Candidate:
    system: dict
    report: dict
    adapters: int
    mass_kg: float | None
    min_margin: float | None
    generated: list[dict] = field(default_factory=list)  # 本方案中按端口尺寸生成的转接件（ADR-0041）

    @property
    def overall(self) -> str:
        return self.report["overall"]

    def sort_key(self) -> tuple:
        warns = sum(1 for c in self.report["checks"] if c["status"] == WARN)
        mass = self.mass_kg if self.mass_kg is not None else math.inf
        margin = -(self.min_margin if self.min_margin is not None else -math.inf)
        ids = tuple(c["component"] for c in self.system["components"])
        return (_RANK[self.overall], self.adapters, warns, mass, margin, ids)

    def to_dict(self) -> dict:
        out = {"system": self.system, "report": self.report, "adapters": self.adapters,
               "mass_kg": self.mass_kg, "min_margin": self.min_margin}
        if self.generated:  # 只在有生成件时出现，已有输出保持不变
            out["generated_components"] = self.generated
        return out


def _port(comp: dict, pid: str) -> dict | None:
    return next((p for p in comp["ports"] if p["id"] == pid), None)


def _spec(comp: dict, pid: str, name: str):
    p = _port(comp, pid)
    return None if p is None else p["spec"].get(name)


def _ports_of(comp: dict, ptype: str) -> list[dict]:
    return [p for p in comp["ports"] if p["type"] == ptype]


def _same(a: float | None, b: float | None, tol: float) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol + 1e-9


def _shaft_options(motor: dict, reducer: dict, adapters: list[dict]) -> list[tuple[dict | None, list[dict]]]:
    """电机轴 → 减速器输入孔：直连，或经一个轴套。返回 [(轴套, 连接)]。"""
    d_shaft = nominal(_spec(motor, "shaft", "diameter_mm"))
    d_bore = nominal(_spec(reducer, "input_bore", "diameter_mm"))
    if _same(d_shaft, d_bore, 1e-6):
        return [(None, [{"a": "motor.shaft", "b": "reducer.input_bore"}])]
    out = []
    for a in adapters:
        if text(a["params"].get("adapter_kind")) != "sleeve":
            continue
        inner, outer = _ports_of(a, "mechanical.cyl_female"), _ports_of(a, "mechanical.cyl_male")
        if len(inner) != 1 or len(outer) != 1:
            continue
        if _same(nominal(inner[0]["spec"].get("diameter_mm")), d_shaft, 1e-6) and \
                _same(nominal(outer[0]["spec"].get("diameter_mm")), d_bore, 1e-6):
            out.append((a, [{"a": "motor.shaft", "b": f"sleeve.{inner[0]['id']}"},
                            {"a": f"sleeve.{outer[0]['id']}", "b": "reducer.input_bore"}]))
    return out


def _flange_options(motor: dict, reducer: dict, adapters: list[dict]) -> list[tuple[dict | None, list[dict]]]:
    """电机法兰 → 减速器电机法兰：直连，或经一块适配法兰板（两种朝向都试）。"""
    pm = nominal(_spec(motor, "mount_flange", "pcd_mm"))
    pr = nominal(_spec(reducer, "motor_flange", "pcd_mm"))
    if _same(pm, pr, PCD_TOL_MM):
        return [(None, [{"a": "motor.mount_flange", "b": "reducer.motor_flange"}])]
    out = []
    for a in adapters:
        if text(a["params"].get("adapter_kind")) != "flange_plate":
            continue
        flanges = _ports_of(a, "mechanical.flange")
        if len(flanges) != 2:
            continue
        for x, y in (flanges, flanges[::-1]):
            if _same(nominal(x["spec"].get("pcd_mm")), pm, PCD_TOL_MM) and \
                    _same(nominal(y["spec"].get("pcd_mm")), pr, PCD_TOL_MM):
                out.append((a, [{"a": "motor.mount_flange", "b": f"plate.{x['id']}"},
                                {"a": f"plate.{y['id']}", "b": "reducer.motor_flange"}]))
                break
    return out


def _quick_reject(req: dict, motor: dict, reducer: dict) -> bool:
    """明显不可能的组合先剔除（只用能确定判 fail 的条件：减速器侧扭矩与转速）。"""
    sf = req.get("safety_factor", 1.2)
    rated = capacity(reducer["params"].get("rated_torque_nm"))
    if rated is not None and req["output_torque_cont_nm"] * sf > rated * (1 + 1e-12):
        return True
    ratio = reducer["params"].get("ratio")
    hi = ratio.get("value", ratio.get("max")) if ratio else None
    vmax = capacity(motor["params"].get("max_speed_rpm"))
    return isinstance(hi, (int, float)) and vmax is not None and req["output_speed_rpm"] * hi > vmax * (1 + 1e-12)


def _mass(components: Iterable[dict]) -> float | None:
    total = 0.0
    for c in components:
        m = capacity(c["params"].get("mass_kg"))
        if m is None:
            return None
        total += m
    return total


def _min_margin(report: dict) -> float | None:
    """C4、C5、C7 中“不大于限值”类判定的最小余量。"""
    margins = []
    for c in report["checks"]:
        if c["check"] in ("C4", "C5", "C7"):
            for f in c.get("findings", [c]):
                if f.get("margin_ratio") is not None:
                    margins.append(f["margin_ratio"])
    return min(margins) if margins else None


def _generated(make, motor: dict, reducer: dict, links, lookup: dict) -> list[tuple[dict | None, list[dict]]]:
    """库中没有合适的转接件时，按两侧端口尺寸生成一个（ADR-0041）；生成不了就没有这条路。"""
    try:
        comp = make(motor, reducer)
    except AdapterError:
        return []
    lookup.setdefault(comp["id"], comp)
    return [(lookup[comp["id"]], links)]


def compose_chain(requirement: dict, library: Iterable[dict], *, top_n: int = 5,
                  include_unknown: bool = False, generate_adapters: bool = False) -> list[Candidate]:
    """按需求从组件库中组合“电机 →（转接件）→ 减速器 + 驱动器”，校验后排序，返回前 top_n 个。

    include_unknown 为真时，也返回整体为 unknown（数据缺失、待确认）的方案，排在 pass、warn 之后。
    generate_adapters 为真时，库中没有合适的轴套或转接板，就按两侧端口尺寸生成（ADR-0041）。
    """
    comps = list(library)
    by_cat: dict[str, list[dict]] = {}
    for c in comps:
        by_cat.setdefault(c["category"], []).append(c)
    for v in by_cat.values():
        v.sort(key=lambda c: c["id"])
    adapters = by_cat.get("adapter", [])
    lookup = {c["id"]: c for c in comps}
    found: list[Candidate] = []
    for motor in by_cat.get("servo_motor", []):
        for reducer in by_cat.get("reducer", []):
            if _quick_reject(requirement, motor, reducer):
                continue
            shafts = _shaft_options(motor, reducer, adapters)
            flanges = _flange_options(motor, reducer, adapters)
            if generate_adapters and not shafts:
                shafts = _generated(adapters_mod.sleeve, motor, reducer,
                                    [{"a": "motor.shaft", "b": "sleeve.inner"},
                                     {"a": "sleeve.outer", "b": "reducer.input_bore"}], lookup)
            if generate_adapters and not flanges:
                flanges = _generated(adapters_mod.plate, motor, reducer,
                                     [{"a": "motor.mount_flange", "b": "plate.motor_side"},
                                      {"a": "plate.reducer_side", "b": "reducer.motor_flange"}], lookup)
            for drive in by_cat.get("drive", []):
                for sleeve, shaft_links in shafts:
                    for plate, flange_links in flanges:
                        parts = [("motor", motor), ("reducer", reducer), ("drive", drive)]
                        parts += [("sleeve", sleeve)] if sleeve else []
                        parts += [("plate", plate)] if plate else []
                        system = {
                            "id": "candidate",
                            "requirement": requirement,
                            "components": [{"instance": n, "component": c["id"]} for n, c in parts],
                            "connections": shaft_links + flange_links + [
                                {"a": "drive.motor_out", "b": "motor.power_in"},
                                {"a": "motor.encoder", "b": "drive.encoder_in"},
                            ],
                        }
                        report = validate(system, lookup.get)
                        allowed = {PASS, WARN} | ({UNKNOWN} if include_unknown else set())
                        if report["overall"] not in allowed:
                            continue
                        found.append(Candidate(system, report, len(parts) - 3, _mass(c for _, c in parts),
                                               _min_margin(report),
                                               [c for _, c in parts if c.get("vendor") == adapters_mod.VENDOR]))
    found.sort(key=Candidate.sort_key)
    # 同一机械链（电机、减速器、转接件相同）只保留排序最前的驱动器，让前 N 个方案更有区别
    seen: set[tuple] = set()
    unique = []
    for cand in found:
        key = tuple(c["component"] for c in cand.system["components"] if c["instance"] != "drive")
        if key not in seen:
            seen.add(key)
            unique.append(cand)
    found = unique
    for n, cand in enumerate(found[:top_n], start=1):
        cand.system["id"] = f"candidate-{n}"
        cand.report["system"] = cand.system["id"]
    return found[:top_n]
