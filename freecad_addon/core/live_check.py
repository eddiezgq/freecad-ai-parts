"""装配即校验（ADR-0048 第 5 条）：由当前布局组成系统并校验，汇总每个端口与实例的结论。纯函数。

- 布局取自 place_component / connect_ports 的返回（instances、connections）
- 场景中恰有一个电机和一个驱动器时，电机动力与编码器按惯例接到驱动器（与 compose_chain 相同），并在说明中写明
- 有需求时跑全部 11 项；没有需求时只跑接口类 C1、C2、C3、C10，其余写“需求未给出”
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from engine.result import FAIL, NA, PASS, UNKNOWN, worst
from engine.validate import validate

INTERFACE_CHECKS = ("C1", "C2", "C3", "C10")
CHECK_NAMES = {"C1": "接口类型", "C2": "圆柱配合", "C3": "法兰配合", "C4": "连续扭矩", "C5": "峰值扭矩",
               "C6": "减速器过载保护", "C7": "转速", "C8": "惯量比", "C9": "供电", "C10": "编码器与总线",
               "C11": "轴承与包络"}
_PLACEHOLDER = {"output_torque_cont_nm": 1, "output_speed_rpm": 1}  # 只为组成系统；不报告依赖需求的检查


def system_from_layout(layout: Mapping, lookup: Callable[[str], dict | None],
                       requirement: Mapping | None = None) -> tuple[dict, list[str]]:
    """返回 (系统, 说明)。"""
    comps = [{"instance": i["instance"], "component": i["component"]} for i in layout.get("instances", [])]
    conns = [{"a": c["a"], "b": c["b"]} for c in layout.get("connections", [])]
    notes = []
    cats: dict[str, list[str]] = {}
    for c in comps:
        comp = lookup(c["component"]) or {}
        cats.setdefault(comp.get("category", ""), []).append(c["instance"])
    motors, drives = cats.get("servo_motor", []), cats.get("drive", [])
    if len(motors) == 1 and len(drives) == 1:
        m, d = motors[0], drives[0]
        conns += [{"a": f"{d}.motor_out", "b": f"{m}.power_in"}, {"a": f"{m}.encoder", "b": f"{d}.encoder_in"}]
        notes.append(f"电机动力与编码器按惯例接到驱动器：{d}.motor_out → {m}.power_in，{m}.encoder → {d}.encoder_in")
    system = {"id": "live", "requirement": dict(requirement or _PLACEHOLDER), "components": comps,
              "connections": conns}
    return system, notes


def check(layout: Mapping, lookup: Callable[[str], dict | None], requirement: Mapping | None = None) -> dict:
    """返回 {mode, overall, checks, notes, ports: {端口引用: 结论}, instances: {实例: 结论}}；场景为空时 checks 为空。"""
    if not layout.get("instances"):
        return {"mode": "empty", "overall": NA, "checks": [], "notes": ["场景中还没有零件"], "ports": {},
                "instances": {}}
    system, notes = system_from_layout(layout, lookup, requirement)
    report = validate(system, lookup)
    checks = report["checks"]
    mode = "full" if requirement else "interface"
    if not requirement:
        checks = [c if c["check"] in INTERFACE_CHECKS else
                  {"check": c["check"], "status": NA, "message": "需求未给出，只校验接口（C1、C2、C3、C10）"}
                  for c in checks]
        notes.append("没有需求：只校验接口类 C1、C2、C3、C10")
    ports: dict[str, list[str]] = {}
    for c in checks:
        for f in c.get("findings", []) or ([c] if c.get("ports") else []):
            for ref in f.get("ports", []) or []:
                ports.setdefault(ref, []).append(f["status"])
    port_status = {ref: worst(sts) for ref, sts in ports.items()}
    inst_status: dict[str, list[str]] = {}
    for ref, st in port_status.items():
        inst_status.setdefault(ref.split(".", 1)[0], []).append(st)
    statuses = [c["status"] for c in checks]
    overall = worst(statuses)
    if overall == NA or (overall == PASS and UNKNOWN in statuses):
        overall = UNKNOWN  # 没有可判定的项不呈现为通过（ADR-0028）
    return {"mode": mode, "overall": overall, "checks": checks, "notes": notes, "ports": port_status,
            "instances": {i: worst(s) for i, s in inst_status.items()}}


STATUS_TEXT = {PASS: "通过", "warn": "注意", UNKNOWN: "待确认", FAIL: "不通过", NA: "不适用"}
STATUS_COLORS = {PASS: (0.20, 0.70, 0.25), "warn": (0.95, 0.75, 0.10), UNKNOWN: (0.95, 0.85, 0.15),
                 FAIL: (0.90, 0.15, 0.15)}
