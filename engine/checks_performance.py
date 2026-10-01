"""性能链校验 C4–C8（实施细则第七节公式 (1)–(6)；ADR-0008、ADR-0016、ADR-0026）。纯函数。

记号：T 扭矩（N·m），i 减速比，η 效率，SF 安全系数，J 转动惯量（kg·m²），n 转速（rpm）。
- 系统没有减速器时按直驱处理：i = 1、η = 1，只校验电机侧
- 系统没有电机时只校验减速器侧
- 效率取范围时：折算到电机侧（公式 (1)(3)）用下限，过载保护（公式 (5)）用上限，均按保守处理
"""

from __future__ import annotations

from engine.result import FAIL, PASS, UNKNOWN, WARN, CheckResult, Finding, not_applicable
from engine.system import System
from engine.values import capacity, span

DEFAULT_SF = 1.2  # ADR-0008
DEFAULT_INERTIA_LIMIT = 10.0  # ADR-0008


def _param(system: System, inst: str | None, name: str):
    return None if inst is None else system.instances[inst]["params"].get(name)


class _Chain:
    """电机、减速器与需求中参与性能链计算的数值。"""

    def __init__(self, system: System):
        self.req = system.requirement
        self.motor = system.one("servo_motor")
        self.reducer = system.one("reducer")
        self.m = lambda n: capacity(_param(system, self.motor, n))
        self.r = lambda n: capacity(_param(system, self.reducer, n))
        if self.reducer is None:
            self.i, self.eta_lo, self.eta_hi = 1.0, 1.0, 1.0
        else:
            self.i = self.r("ratio")
            eta = span(_param(system, self.reducer, "efficiency_ratio"))
            self.eta_lo, self.eta_hi = eta if eta else (None, None)
        self.motor_port = f"{self.motor}.shaft" if self.motor else None
        self.reducer_port = f"{self.reducer}.input_bore" if self.reducer else None

    @property
    def ports(self) -> list[str]:
        return [p for p in (self.motor_port, self.reducer_port) if p]


def _le(name: str, measured: float | None, limit: float | None, unit: str, ports: list[str], what: str,
        missing: str, fail_status: str = FAIL) -> Finding:
    """measured ≤ limit 为 pass；任一缺失为 unknown。"""
    if measured is None or limit is None:
        return Finding(UNKNOWN, f"{what}：缺少{missing}", ports)
    ok = measured <= limit * (1 + 1e-12)
    sign = "≤" if ok else ">"
    shown = {"N*m": " N·m", "rpm": " rpm", "1": ""}.get(unit, f" {unit}")
    return Finding(PASS if ok else fail_status, f"{what} {measured:.4g} {sign} {name} {limit:.4g}{shown}",
                   ports, measured, limit, unit)


def c4(system: System) -> CheckResult:
    """连续扭矩：(1) SF·T_cont/(i·η) ≤ T_motor,rated；(2) SF·T_cont ≤ T_reducer,rated。"""
    ch = _Chain(system)
    if ch.motor is None and ch.reducer is None:
        return not_applicable("C4", "系统中没有电机和减速器")
    t = ch.req["output_torque_cont_nm"] * ch.req.get("safety_factor", DEFAULT_SF)
    res = CheckResult("C4")
    if ch.motor:
        motor_side = t / (ch.i * ch.eta_lo) if ch.i and ch.eta_lo else None
        missing = "减速比或效率" if motor_side is None else "电机额定扭矩"
        res.findings.append(_le("电机额定扭矩", motor_side, ch.m("rated_torque_nm"), "N*m", ch.ports,
                                "连续扭矩折算到电机侧", missing))
    if ch.reducer:
        res.findings.append(_le("减速器额定扭矩", t, ch.r("rated_torque_nm"), "N*m", ch.ports,
                                "含安全系数的连续扭矩", "减速器额定扭矩"))
    return res


def c5(system: System) -> CheckResult:
    """峰值扭矩：(3) T_peak/(i·η) ≤ T_motor,peak；(4) T_peak ≤ T_reducer,repeated_peak。"""
    ch = _Chain(system)
    if "output_torque_peak_nm" not in ch.req:
        return not_applicable("C5", "需求未给峰值扭矩")
    if ch.motor is None and ch.reducer is None:
        return not_applicable("C5", "系统中没有电机和减速器")
    t = ch.req["output_torque_peak_nm"]
    res = CheckResult("C5")
    if ch.motor:
        motor_side = t / (ch.i * ch.eta_lo) if ch.i and ch.eta_lo else None
        missing = "减速比或效率" if motor_side is None else "电机峰值扭矩"
        res.findings.append(_le("电机峰值扭矩", motor_side, ch.m("peak_torque_nm"), "N*m", ch.ports,
                                "峰值扭矩折算到电机侧", missing))
    if ch.reducer:
        res.findings.append(_le("减速器启停允许峰值扭矩", t, ch.r("repeated_peak_torque_nm"), "N*m", ch.ports,
                                "峰值扭矩", "减速器启停允许峰值扭矩"))
    return res


def c6(system: System) -> CheckResult:
    """减速器过载保护：(5) T_motor,peak·i·η > T_reducer,momentary_max ⇒ warn（须在驱动器设扭矩限幅）。"""
    ch = _Chain(system)
    if ch.motor is None or ch.reducer is None:
        return not_applicable("C6", "系统中没有同时包含电机和减速器")
    peak, limit = ch.m("peak_torque_nm"), ch.r("momentary_max_torque_nm")
    if peak is None or limit is None or not ch.i or ch.eta_hi is None:
        return CheckResult("C6", [Finding(UNKNOWN, "过载保护：缺少电机峰值扭矩、减速比、效率或减速器瞬间最大扭矩",
                                          ch.ports)])
    out = peak * ch.i * ch.eta_hi
    if out > limit * (1 + 1e-12):
        msg = (f"电机峰值扭矩经减速后 {out:.4g} N·m > 减速器瞬间允许最大 {limit:.4g} N·m，"
               "须在驱动器设置扭矩限幅")
        return CheckResult("C6", [Finding(WARN, msg, ch.ports, out, limit, "N*m")])
    return CheckResult("C6", [Finding(PASS, f"电机峰值扭矩经减速后 {out:.4g} N·m ≤ 减速器瞬间允许最大 {limit:.4g} N·m",
                                      ch.ports, out, limit, "N*m")])


def c7(system: System) -> CheckResult:
    """转速：n_out·i ≤ 电机最高转速、≤ 减速器最高输入转速（fail）；超过平均输入转速限制 warn。"""
    ch = _Chain(system)
    if ch.motor is None and ch.reducer is None:
        return not_applicable("C7", "系统中没有电机和减速器")
    n_in = ch.req["output_speed_rpm"] * ch.i if ch.i else None
    res = CheckResult("C7")
    if ch.motor:
        res.findings.append(_le("电机最高转速", n_in, ch.m("max_speed_rpm"), "rpm", ch.ports, "所需电机转速",
                                "减速比" if n_in is None else "电机最高转速"))
    if ch.reducer:
        res.findings.append(_le("减速器最高输入转速", n_in, ch.r("max_input_speed_rpm"), "rpm", ch.ports,
                                "所需输入转速", "减速比" if n_in is None else "减速器最高输入转速"))
        avg = ch.r("avg_input_speed_limit_rpm")
        if avg is not None and n_in is not None:  # 选填参数：缺失时不判
            res.findings.append(_le("减速器平均输入转速限制", n_in, avg, "rpm", ch.ports, "所需输入转速",
                                    "", fail_status=WARN))
    return res


def c8(system: System) -> CheckResult:
    """惯量比：(6) (J_load/i² + J_reducer,in)/J_motor ≤ 阈值（默认 10），超过 warn。只在需求给出负载惯量时计算。"""
    ch = _Chain(system)
    j_load = ch.req.get("load_inertia_kgm2")
    if j_load is None:
        return not_applicable("C8", "需求未给负载惯量")
    if ch.motor is None:
        return not_applicable("C8", "系统中没有电机")
    limit = ch.req.get("inertia_ratio_limit", DEFAULT_INERTIA_LIMIT)
    j_motor = ch.m("rotor_inertia_kgm2")
    j_red = ch.r("input_inertia_kgm2") if ch.reducer else 0.0
    if j_motor is None or j_red is None or not ch.i:
        missing = "电机转子惯量" if j_motor is None else ("减速器输入侧惯量" if j_red is None else "减速比")
        return CheckResult("C8", [Finding(UNKNOWN, f"惯量比：缺少{missing}", ch.ports)])
    ratio = (j_load / ch.i ** 2 + j_red) / j_motor
    return CheckResult("C8", [_le("阈值", ratio, limit, "1", ch.ports, "惯量比", "", fail_status=WARN)])
