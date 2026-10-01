"""接口校验 C1–C3（实施细则第七节；ADR-0017、ADR-0020、ADR-0024、ADR-0025）。纯函数。"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from engine import rules
from engine.result import FAIL, PASS, UNKNOWN, WARN, CheckResult, Finding, not_applicable
from engine.system import PortRef, System
from engine.values import nominal, text

_PORT_TYPES = Path(__file__).resolve().parent.parent / "schema" / "port-types"
CYL = {"mechanical.cyl_male", "mechanical.cyl_female"}
FLANGE = {"mechanical.flange"}
DIAMETER_TOL_MM = 1e-6  # 名义直径“相等”
PCD_TOL_MM = 0.05  # 分度圆直径允许偏差（实施细则 C3）


@cache
def connects_to(port_type: str) -> frozenset[str]:
    data = json.loads((_PORT_TYPES / f"{port_type}.schema.json").read_text(encoding="utf-8"))
    return frozenset(data.get("x-connects-to", []))


def _pair_ok(a: dict, b: dict) -> tuple[bool, str]:
    if b["type"] not in connects_to(a["type"]):
        return False, f"端口类型 {a['type']} 不能连接 {b['type']}"
    dirs = {a["dir"], b["dir"]}
    if "bidir" not in dirs and dirs != {"in", "out"}:
        return False, f"方向不匹配（{a['dir']} 与 {b['dir']}）"
    if a.get("motion") != b.get("motion"):
        return False, f"运动方式不同（{a.get('motion')} 与 {b.get('motion')}）"
    return True, "类型、方向、运动方式匹配"


def c1(system: System) -> CheckResult:
    """端口兼容：类型在可连接列表内；方向为 out→in 或含 bidir；motion 相同。"""
    if not system.connections:
        return not_applicable("C1", "系统中没有连接")
    res = CheckResult("C1")
    for a, b in system.connections:
        ok, msg = _pair_ok(system.port(a), system.port(b))
        res.findings.append(Finding(PASS if ok else FAIL, f"{a} — {b}：{msg}", [str(a), str(b)]))
    return res


def _compatible_links(system: System, types: set[str]) -> list[tuple[PortRef, PortRef]]:
    """类型属于 types 且通过 C1 的连接（C1 不通过的连接由 C1 报告，这里不重复判定）。"""
    out = []
    for a, b in system.connections:
        pa, pb = system.port(a), system.port(b)
        if pa["type"] in types and pb["type"] in types and _pair_ok(pa, pb)[0]:
            out.append((a, b))
    return out


def _missing_link(system: System, start: tuple[str, str], goal: tuple[str, str],
                  types: set[str], what: str) -> Finding | None:
    """电机与减速器同在时，必须有 start → goal 的连接路径（可经转接件，ADR-0020）。"""
    motor, reducer = system.one("servo_motor"), system.one("reducer")
    if motor is None or reducer is None:
        return None
    s, g = PortRef(motor, start[1]), PortRef(reducer, goal[1])
    if system.connected(s, g, types):
        return None
    return Finding(FAIL, f"缺少{what}：{s} 与 {g} 之间没有连接（可经转接件）", [str(s), str(g)])


# ---------------------------------------------------------------- C2


def _fit_finding(system: System, shaft: PortRef, bore: PortRef) -> Finding:
    """公差配合：一侧为轴承时查轴承配合推荐表（ADR-0017），否则查 ISO 286 配合表。"""
    ports = [str(shaft), str(bore)]
    s_sys = text(system.spec(shaft, "fit_system")) or "iso286"
    b_sys = text(system.spec(bore, "fit_system")) or "iso286"
    s_fit, b_fit = text(system.spec(shaft, "fit")), text(system.spec(bore, "fit"))
    if s_sys == "bearing" and b_sys == "bearing":
        return Finding(WARN, "轴承圈与轴承圈直接配合，配合表不适用，须人工确认", ports)
    if "bearing" in (s_sys, b_sys):
        ring_ref, mate_fit = (bore, s_fit) if b_sys == "bearing" else (shaft, b_fit)
        ring = "inner" if system.port(ring_ref)["type"] == "mechanical.cyl_female" else "outer"
        load = "rotating" if system.port(ring_ref).get("motion") == "rotating" else "stationary"
        kind = text(system.instances[ring_ref.instance]["params"].get("bearing_kind"))
        d = nominal(system.spec(ring_ref, "diameter_mm"))
        if mate_fit is None or kind is None or d is None:
            return Finding(UNKNOWN, "轴承配合缺少数据（配合件公差带、轴承类型或直径）", ports)
        classes = rules.bearing_fit_classes(ring, load, kind, d)
        if classes is None:
            return Finding(UNKNOWN, f"轴承配合推荐表未覆盖 {kind}、直径 {d:g} mm", ports)
        mate = "轴" if ring == "inner" else "轴承座"
        if mate_fit in classes:
            return Finding(PASS, f"{mate}公差带 {mate_fit} 在推荐范围 {sorted(classes)} 内（草稿规则表）", ports)
        return Finding(WARN, f"{mate}公差带 {mate_fit} 不在推荐范围 {sorted(classes)} 内（草稿规则表）", ports)
    if s_fit is None or b_fit is None:
        return Finding(UNKNOWN, "缺少公差带", ports)
    fit_class = rules.iso286_pairs().get((b_fit, s_fit))
    if fit_class:
        return Finding(PASS, f"{b_fit}/{s_fit} 为 {fit_class} 配合（草稿规则表）", ports)
    return Finding(WARN, f"{b_fit}/{s_fit} 不在配合表内，须人工确认（草稿规则表）", ports)


def _shaft_and_bore(system: System, a: PortRef, b: PortRef) -> tuple[PortRef, PortRef]:
    return (a, b) if system.port(a)["type"] == "mechanical.cyl_male" else (b, a)


def c2(system: System) -> CheckResult:
    """圆柱配合：直径相等；公差配对；形式与紧固方式兼容；有键时键宽相等。"""
    res = CheckResult("C2")
    links = _compatible_links(system, CYL)
    for a, b in links:
        shaft, bore = _shaft_and_bore(system, a, b)
        ports = [str(shaft), str(bore)]
        ds, db = nominal(system.spec(shaft, "diameter_mm")), nominal(system.spec(bore, "diameter_mm"))
        if ds is None or db is None:
            res.findings.append(Finding(UNKNOWN, f"{shaft} — {bore}：缺少名义直径", ports))
        elif abs(ds - db) > DIAMETER_TOL_MM:
            res.findings.append(Finding(FAIL, f"轴径 {ds:g} mm ≠ 孔径 {db:g} mm", ports, ds, db, "mm"))
        else:
            res.findings.append(Finding(PASS, f"直径 {ds:g} mm 相等", ports))
        res.findings.append(_fit_finding(system, shaft, bore))
        sf, bf = text(system.spec(shaft, "feature")), text(system.spec(bore, "feature"))
        clamping = text(system.spec(bore, "clamping"))
        bearing_bore = text(system.spec(bore, "fit_system")) == "bearing"
        if clamping is None and bearing_bore:
            pass  # 轴承内圈的紧固方式由装配设计决定，此项不适用（ADR-0024）
        elif sf is None or bf is None or clamping is None:
            res.findings.append(Finding(UNKNOWN, "缺少轴、孔形式或紧固方式", ports))
        else:
            result, reason = rules.clamping_matrix().get((sf, bf, clamping), (UNKNOWN, "兼容矩阵未覆盖"))
            msg = f"轴 {sf} / 孔 {bf} / 紧固 {clamping}" + (f"：{reason}" if reason else "：兼容")
            res.findings.append(Finding(result, msg + "（草稿规则表）", ports))
        if "keyed" in (sf, bf) or clamping == "key":
            ks, kb = nominal(system.spec(shaft, "key_width_mm")), nominal(system.spec(bore, "key_width_mm"))
            if sf == "keyed" and bf == "keyed":
                if ks is None or kb is None:
                    res.findings.append(Finding(UNKNOWN, "缺少键宽", ports))
                elif abs(ks - kb) > DIAMETER_TOL_MM:
                    res.findings.append(Finding(FAIL, f"键宽 {ks:g} mm ≠ {kb:g} mm", ports, ks, kb, "mm"))
                else:
                    res.findings.append(Finding(PASS, f"键宽 {ks:g} mm 相等", ports))
    missing = _missing_link(system, ("motor", "shaft"), ("reducer", "input_bore"), CYL, "电机轴到减速器输入孔的连接")
    if missing:
        res.findings.append(missing)
    if not res.findings:
        return not_applicable("C2", "系统中没有圆柱配合连接")
    return res


# ---------------------------------------------------------------- C3


def c3(system: System) -> CheckResult:
    """法兰配合：分度圆、孔数、孔径（ISO 273 中等系列）、止口。"""
    res = CheckResult("C3")
    for a, b in _compatible_links(system, FLANGE):
        ports = [str(a), str(b)]
        pa, pb = system.port(a)["spec"], system.port(b)["spec"]
        da, db = nominal(pa.get("pcd_mm")), nominal(pb.get("pcd_mm"))
        if da is None or db is None:
            res.findings.append(Finding(UNKNOWN, "缺少分度圆直径", ports))
        elif abs(da - db) > PCD_TOL_MM:
            res.findings.append(Finding(FAIL, f"分度圆 {da:g} mm 与 {db:g} mm 相差超过 {PCD_TOL_MM} mm",
                                        ports, abs(da - db), PCD_TOL_MM, "mm"))
        else:
            res.findings.append(Finding(PASS, f"分度圆 {da:g} mm 一致", ports))
        na, nb = nominal(pa.get("hole_count")), nominal(pb.get("hole_count"))
        if na is None or nb is None:
            res.findings.append(Finding(UNKNOWN, "缺少孔数", ports))
        elif na != nb:
            res.findings.append(Finding(FAIL, f"孔数 {na:g} ≠ {nb:g}", ports))
        else:
            res.findings.append(Finding(PASS, f"孔数 {na:g} 相等", ports))
        res.findings.append(_holes(a, pa, b, pb))
        res.findings.append(_pilot(a, pa, b, pb))
    missing = _missing_link(system, ("motor", "mount_flange"), ("reducer", "motor_flange"), FLANGE,
                            "电机法兰到减速器电机法兰的连接")
    if missing:
        res.findings.append(missing)
    if not res.findings:
        return not_applicable("C3", "系统中没有法兰连接")
    return res


def _holes(a: PortRef, pa: dict, b: PortRef, pb: dict) -> Finding:
    ports = [str(a), str(b)]
    ka, kb = text(pa.get("hole_kind")), text(pb.get("hole_kind"))
    if ka is None or kb is None:
        return Finding(UNKNOWN, "缺少孔的形式（通孔 / 螺纹孔）", ports)
    if ka == kb == "through":
        return Finding(PASS, "两侧均为通孔，用螺栓螺母连接", ports)
    if ka == kb == "threaded":
        return Finding(WARN, "两侧都是螺纹孔，须用双头螺柱或改为通孔（ADR-0025）", ports)
    thread_side, hole_side = (pa, pb) if ka == "threaded" else (pb, pa)
    thread, hole = text(thread_side.get("thread")), nominal(hole_side.get("hole_diameter_mm"))
    if thread is None or hole is None:
        return Finding(UNKNOWN, "缺少螺纹规格或通孔直径", ports)
    base = thread.split("x")[0]
    need = rules.iso273_medium().get(base)
    if need is None:
        return Finding(UNKNOWN, f"ISO 273 表中没有 {base}", ports)
    if hole + 1e-9 >= need:
        return Finding(PASS, f"通孔 {hole:g} mm ≥ {base} 中等系列间隙孔 {need:g} mm（草稿规则表）", ports)
    return Finding(FAIL, f"通孔 {hole:g} mm < {base} 中等系列间隙孔 {need:g} mm（草稿规则表）", ports,
                   need, hole, "mm")


def _pilot(a: PortRef, pa: dict, b: PortRef, pb: dict) -> Finding:
    ports = [str(a), str(b)]
    ha, hb = "pilot_diameter_mm" in pa, "pilot_diameter_mm" in pb
    if not ha and not hb:
        return Finding(WARN, "两侧都没有止口，定位靠螺栓，须确认同轴度", ports)
    if ha != hb:
        return Finding(WARN, "只有一侧有止口，无法止口定位", ports)
    ka, kb = text(pa.get("pilot_kind")), text(pb.get("pilot_kind"))
    da, db = nominal(pa["pilot_diameter_mm"]), nominal(pb["pilot_diameter_mm"])
    if ka is None or kb is None or da is None or db is None:
        return Finding(UNKNOWN, "缺少止口形式或直径", ports)
    if {ka, kb} != {"male", "female"}:
        return Finding(FAIL, f"止口须一凸一凹（现为 {ka} 与 {kb}）", ports)
    if abs(da - db) > DIAMETER_TOL_MM:
        return Finding(FAIL, f"止口直径 {da:g} mm ≠ {db:g} mm", ports, da, db, "mm")
    return Finding(PASS, f"止口一凸一凹，直径 {da:g} mm 相等", ports)

