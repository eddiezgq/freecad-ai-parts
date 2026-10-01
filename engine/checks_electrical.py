"""电气、信号与包络校验 C9–C11（实施细则第七节；ADR-0014、ADR-0016、ADR-0020、ADR-0027）。纯函数。"""

from __future__ import annotations

import math

from engine.checks_interface import _pair_ok
from engine.result import FAIL, NA, PASS, UNKNOWN, WARN, CheckResult, Finding, not_applicable
from engine.system import PortRef, System
from engine.values import capacity, items, nominal, span, text


def _link(system: System, a: PortRef, b: PortRef) -> bool:
    """a 与 b 之间有一条通过 C1 的直接连接。"""
    return system.partner(a) == b and _pair_ok(system.port(a), system.port(b))[0]


def _motor_drive(system: System) -> tuple[str | None, str | None]:
    return system.one("servo_motor"), system.one("drive")


# ---------------------------------------------------------------- C9


def c9(system: System) -> CheckResult:
    """电气匹配：动力连接；供电电压、电流类型、相数；电压等级；额定电流（fail）；峰值电流（warn）。"""
    motor, drive = _motor_drive(system)
    if motor is None or drive is None:
        return not_applicable("C9", "系统中没有同时包含电机和驱动器")
    out, pin, supply = PortRef(drive, "motor_out"), PortRef(motor, "power_in"), PortRef(drive, "power_in")
    ports = [str(out), str(pin)]
    if not _link(system, out, pin):
        return CheckResult("C9", [Finding(FAIL, f"缺少动力连接：{out} 与 {pin} 之间没有正确的连接", ports)])
    res = CheckResult("C9")
    req = system.requirement.get("supply")
    if req:
        sp = [str(supply)]
        ct = text(system.spec(supply, "current_type"))
        if ct is None:
            res.findings.append(Finding(UNKNOWN, "驱动器缺少供电类型", sp))
        elif ct != req["current_type"]:
            res.findings.append(Finding(FAIL, f"供电类型不符：可用 {req['current_type']}，驱动器要求 {ct}", sp))
        else:
            res.findings.append(Finding(PASS, f"供电类型 {ct} 一致", sp))
        rng = span(system.spec(supply, "voltage_v"))
        v = req["voltage_v"]
        if rng is None:
            res.findings.append(Finding(UNKNOWN, "驱动器缺少输入电压范围", sp))
        elif rng[0] - 1e-9 <= v <= rng[1] + 1e-9:
            res.findings.append(Finding(PASS, f"供电 {v:g} V 在驱动器输入范围 {rng[0]:g}–{rng[1]:g} V 内", sp))
        else:
            res.findings.append(Finding(FAIL, f"供电 {v:g} V 不在驱动器输入范围 {rng[0]:g}–{rng[1]:g} V 内", sp))
        ph = nominal(system.spec(supply, "phases"))
        if ph is None:
            res.findings.append(Finding(UNKNOWN, "驱动器缺少输入相数", sp))
        elif ph != req["phases"]:
            res.findings.append(Finding(FAIL, f"相数不符：可用 {req['phases']}，驱动器要求 {ph:g}", sp))
        else:
            res.findings.append(Finding(PASS, f"相数 {ph:g} 一致", sp))
    vd, vm = nominal(system.spec(out, "voltage_class_v")), nominal(system.spec(pin, "voltage_class_v"))
    if vd is None or vm is None:
        res.findings.append(Finding(UNKNOWN, "缺少电压等级", ports))
    elif abs(vd - vm) > 1e-9:
        res.findings.append(Finding(FAIL, f"电压等级不符：驱动器 {vd:g} V，电机 {vm:g} V", ports))
    else:
        res.findings.append(Finding(PASS, f"电压等级 {vd:g} V 一致", ports))
    for key, name, status in (("rated_current_a", "额定电流", FAIL), ("peak_current_a", "峰值电流", WARN)):
        need, have = capacity(system.spec(pin, key)), capacity(system.spec(out, key))
        if need is None or have is None:
            res.findings.append(Finding(UNKNOWN, f"缺少{name}", ports))
        elif have + 1e-12 >= need:
            res.findings.append(Finding(PASS, f"驱动器{name} {have:g} A ≥ 电机 {need:g} A", ports, need, have, "A"))
        else:
            tail = "（峰值扭矩受限）" if status == WARN else ""
            res.findings.append(Finding(status, f"驱动器{name} {have:g} A < 电机 {need:g} A{tail}", ports,
                                        need, have, "A"))
    return res


# ---------------------------------------------------------------- C10


def _same_vendor(a: str | None, b: str | None) -> bool:
    norm = lambda s: "".join(ch for ch in s.casefold() if ch.isalnum())
    return a is not None and b is not None and norm(a) == norm(b)


def c10(system: System) -> CheckResult:
    """信号匹配：编码器连接；电机编码器协议在驱动器支持列表内（私有协议须同一厂商）；总线协议与需求一致。"""
    motor, drive = _motor_drive(system)
    res = CheckResult("C10")
    if motor is not None and drive is not None:
        enc, ein = PortRef(motor, "encoder"), PortRef(drive, "encoder_in")
        ports = [str(enc), str(ein)]
        if not _link(system, enc, ein):
            res.findings.append(Finding(FAIL, f"缺少编码器连接：{enc} 与 {ein} 之间没有正确的连接", ports))
        else:
            proto = text(system.spec(enc, "protocol"))
            supported = items(system.spec(ein, "protocol"))
            if proto is None or supported is None:
                res.findings.append(Finding(UNKNOWN, "缺少编码器协议", ports))
            elif proto not in supported:
                res.findings.append(Finding(FAIL, f"电机编码器协议 {proto} 不在驱动器支持列表 {supported} 内", ports))
            elif proto == "vendor_proprietary":
                mv, dv = text(system.spec(enc, "vendor")), text(system.spec(ein, "vendor"))
                if mv is None or dv is None:
                    res.findings.append(Finding(UNKNOWN, "私有编码器协议缺少厂商信息", ports))
                elif _same_vendor(mv, dv):
                    res.findings.append(Finding(PASS, f"私有编码器协议，厂商一致（{mv}）", ports))
                else:
                    res.findings.append(Finding(FAIL, f"私有编码器协议厂商不同：电机 {mv}，驱动器 {dv}", ports))
            else:
                res.findings.append(Finding(PASS, f"编码器协议 {proto} 受驱动器支持", ports))
    want = system.requirement.get("fieldbus_protocol")
    if want and drive is not None:
        bus = PortRef(drive, "bus")
        have = items(system.spec(bus, "protocol")) if system.has_port(bus) else None
        if have is None:
            res.findings.append(Finding(UNKNOWN, "驱动器缺少总线协议", [str(bus)]))
        elif want in have:
            res.findings.append(Finding(PASS, f"总线 {want} 一致", [str(bus)]))
        else:
            res.findings.append(Finding(FAIL, f"需求总线 {want}，驱动器为 {have}", [str(bus)]))
    if not res.findings:
        return not_applicable("C10", "系统中没有电机与驱动器，需求也未指定总线")
    return res


# ---------------------------------------------------------------- C11


def _part_diameter(part: dict) -> float | None:
    """包络段的外接圆直径：圆柱取直径，长方体取截面对角线（ADR-0020）。"""
    if part["shape"] == "cylinder":
        return nominal(part.get("diameter_mm"))
    w, h = nominal(part.get("width_mm")), nominal(part.get("height_mm"))
    return math.hypot(w, h) if w is not None and h is not None else None


def c11(system: System) -> CheckResult:
    """轴承与包络：轴承转速（取输出转速）≤ 极限转速；系统外径 ≤ 需求限值；长度 M3 不判（ADR-0020）。"""
    req = system.requirement
    res = CheckResult("C11")
    notes = []
    n_out = req["output_speed_rpm"]
    for name in system.of_category("bearing"):
        limit = capacity(system.instances[name]["params"].get("limiting_speed_rpm"))
        ports = [f"{name}.inner"]
        if limit is None:
            res.findings.append(Finding(UNKNOWN, f"{name} 缺少极限转速", ports))
        elif n_out <= limit + 1e-12:
            res.findings.append(Finding(PASS, f"{name} 转速 {n_out:g} ≤ 极限转速 {limit:g} rpm", ports,
                                        n_out, limit, "rpm"))
        else:
            res.findings.append(Finding(FAIL, f"{name} 转速 {n_out:g} > 极限转速 {limit:g} rpm", ports,
                                        n_out, limit, "rpm"))
    d_max = req.get("max_envelope_diameter_mm")
    if d_max is not None:
        worst_d, where, missing = 0.0, None, []
        for name, comp in system.instances.items():
            if comp["category"] == "drive":
                continue  # 驱动器装在电控柜中，不计入关节包络（ADR-0027）
            for part in comp["envelope"]["parts"]:
                d = _part_diameter(part)
                if d is None:
                    missing.append(name)
                elif d > worst_d:
                    worst_d, where = d, name
        if missing:
            res.findings.append(Finding(UNKNOWN, f"{', '.join(sorted(set(missing)))} 的包络缺少尺寸", []))
        if where is not None:
            ok = worst_d <= d_max + 1e-9
            msg = f"系统外径（外接圆）{worst_d:.4g} mm {'≤' if ok else '>'} 限值 {d_max:g} mm（最大处：{where}）"
            res.findings.append(Finding(PASS if ok else FAIL, msg, [], worst_d, d_max, "mm"))
    if req.get("max_envelope_length_mm") is not None:
        notes.append("包络长度须 FreeCAD 布局后计算，M3 不判（ADR-0020）")
    if not res.findings:
        reason = "；".join(notes) or "系统中没有轴承，需求也未给包络外径限值"
        return not_applicable("C11", reason)
    if notes:
        res.findings.append(Finding(NA, notes[0], []))
    return res
