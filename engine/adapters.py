"""按两侧端口尺寸生成转接件：轴套与转接板（ADR-0041，issue #129）。

纯函数：只读给定的电机与减速器组件，不联网、不读数据库。生成件的每个参数都是 method: computed，
source.formula 写明设计规则；同一输入结果相同。生成不了时返回原因，不猜尺寸。
"""

from __future__ import annotations

import math

from engine import rules
from engine.values import nominal, text

VENDOR = "freecad-ai-parts (generated)"
NOTE = "按两侧端口尺寸生成的设计件（ADR-0041），须加工；加工前按图纸复核尺寸与键槽"
STEEL_KG_M3 = 7850.0
ALUMINUM_KG_M3 = 2700.0
MIN_WALL_MM = 1.5
HUB_KEYWAY = 0.45  # 内孔键槽深度约为键宽的 0.45 倍（近似 DIN 6885 轮毂槽深）
SHAFT_KEYWAY = 0.6  # 外圆键槽深度约为键宽的 0.6 倍（近似 DIN 6885 轴槽深）
MIN_PLATE_MM = 8.0
EDGE_MM = 3.0  # 孔边到板边的最小距离
HOLE_GAP_MM = 2.0  # 两侧孔之间的最小净距


class AdapterError(ValueError):
    """生成不了转接件；消息说明原因。"""


def _pv(value, formula: str) -> dict:
    return {"value": value, "source": {"formula": formula}, "method": "computed", "confidence": 1.0,
            "reviewed": False}


def _port(comp: dict, pid: str) -> dict | None:
    return next((p for p in comp.get("ports", []) if p["id"] == pid), None)


def _num(spec: dict, name: str) -> float | None:
    return nominal(spec.get(name))


def _fmt(x: float) -> str:
    return f"{x:g}".replace(".", "p")


def _round_up(x: float, step: float) -> float:
    return math.ceil(x / step - 1e-9) * step


# ---------------------------------------------------------------- 轴套


def sleeve(motor: dict, reducer: dict) -> dict:
    """电机轴 → 减速器输入孔的轴套；生成不了时抛出 AdapterError。"""
    shaft, bore = _port(motor, "shaft"), _port(reducer, "input_bore")
    if shaft is None or bore is None:
        raise AdapterError("电机没有输出轴端口或减速器没有输入孔端口")
    s, b = shaft["spec"], bore["spec"]
    ds, db = _num(s, "diameter_mm"), _num(b, "diameter_mm")
    if ds is None or db is None:
        raise AdapterError("缺少轴径或孔径")
    if ds >= db - 1e-9:
        raise AdapterError(f"轴径 {ds:g} mm 不小于孔径 {db:g} mm，轴套装不进")
    sf, bf = text(s.get("feature")), text(b.get("feature"))
    if sf not in ("plain", "keyed") or bf not in ("plain", "keyed"):
        raise AdapterError(f"不为 {sf} 轴或 {bf} 孔生成轴套（只支持光轴、键槽）")
    kin = _num(s, "key_width_mm") if sf == "keyed" else 0.0
    kout = _num(b, "key_width_mm") if bf == "keyed" else 0.0
    if kin is None or kout is None:
        raise AdapterError("有键槽但缺少键宽")
    wall = (db - ds) / 2
    need = MIN_WALL_MM + max(HUB_KEYWAY * kin, SHAFT_KEYWAY * kout)  # 内外键槽错开 180°，取较深的一个
    if wall + 1e-9 < need:
        raise AdapterError(f"壁厚 {wall:g} mm 小于所需 {need:g} mm（最小壁厚加键槽深度）")
    lengths = [x for x in (_num(s, "usable_length_mm"), _num(b, "depth_mm")) if x is not None and x > 0]
    if not lengths:
        raise AdapterError("电机轴可用长度和减速器孔深都没有，定不了轴套长度")
    length = min(lengths)

    inner: dict = {
        "diameter_mm": _pv(ds, "= 电机轴名义直径"),
        "fit": _pv("H7", "内孔公差 H7（ADR-0041）"),
        "feature": _pv(sf, "= 电机轴形式"),
        "clamping": _pv("key" if sf == "keyed" else "clamp_ring", "有键用键连接，光轴用夹紧环（ADR-0041）"),
        "depth_mm": _pv(length, "= 轴套长度"),
    }
    if sf == "keyed":
        inner["key_width_mm"] = _pv(kin, "= 电机轴键宽")
    press = text(b.get("clamping")) == "press_fit"
    outer: dict = {
        "diameter_mm": _pv(db, "= 减速器输入孔名义直径"),
        "fit": _pv("k6" if press else "h6", "外圆公差 h6；减速器孔要求压装时用 k6（ADR-0041）"),
        "feature": _pv(bf, "= 减速器输入孔形式"),
        "usable_length_mm": _pv(length, "= 轴套长度"),
    }
    if bf == "keyed":
        outer["key_width_mm"] = _pv(kout, "= 减速器输入孔键宽")
    mass = STEEL_KG_M3 * math.pi / 4 * (db**2 - ds**2) * length * 1e-9
    model = f"SL-{_fmt(ds)}-{_fmt(db)}-{_fmt(length)}" + (f"-K{_fmt(kin)}" if kin else "") + \
        (f"-K{_fmt(kout)}" if kout else "")
    frame = {"origin_mm": [0, 0, 0], "axis": [0, 0, 1]}
    return {
        "id": f"adapter.fap-generated.{model.lower()}",
        "category": "adapter", "vendor": VENDOR, "model": model, "status": "active", "license": "open",
        "params": {
            "adapter_kind": _pv("sleeve", "轴径 ≠ 孔径，生成轴套（ADR-0041）"),
            "length_mm": _pv(length, "= min(电机轴可用长度, 减速器孔深)"),
            "mass_kg": _pv(round(mass, 4), "钢 7850 kg/m³ × π/4 × (外径² − 内径²) × 长度"),
        },
        "ports": [
            {"id": "inner", "type": "mechanical.cyl_female", "dir": "in", "motion": "rotating", "frame": frame,
             "spec": inner},
            {"id": "outer", "type": "mechanical.cyl_male", "dir": "out", "motion": "rotating", "frame": frame,
             "spec": outer},
        ],
        "envelope": {"parts": [{"shape": "cylinder", "z_start_mm": 0,
                                "length_mm": _pv(length, "= 轴套长度"), "diameter_mm": _pv(db, "= 外径")}]},
        "note": NOTE,
    }


# ---------------------------------------------------------------- 转接板


def _thread_for_hole(hole_mm: float) -> str | None:
    """ISO 273 中等系列间隙孔不大于该通孔的最大螺纹。"""
    table = rules.iso273_medium()
    fits = [(need, m) for m, need in table.items() if need <= hole_mm + 1e-9]
    return max(fits)[1] if fits else None


def _thread_d(thread: str) -> float:
    return float(thread[1:].split("x")[0])


def _plate_side(other: dict, side: str) -> tuple[dict, float, float]:
    """转接板一侧的法兰规格，返回（spec, 该侧孔的直径, 螺纹直径或 0）。"""
    pcd, n = _num(other, "pcd_mm"), _num(other, "hole_count")
    kind = text(other.get("hole_kind"))
    if pcd is None or n is None or kind is None:
        raise AdapterError(f"{side}法兰缺少分度圆、孔数或孔的形式")
    spec: dict = {"pcd_mm": _pv(pcd, f"= {side}法兰分度圆"), "hole_count": _pv(int(n), f"= {side}法兰孔数")}
    if (off := _num(other, "hole_angle_offset_deg")) is not None:
        spec["hole_angle_offset_deg"] = _pv(off, f"= {side}法兰第一个孔的角度")
    if kind == "through":
        hole = _num(other, "hole_diameter_mm")
        if hole is None:
            raise AdapterError(f"{side}法兰是通孔但缺少孔径")
        thread = _thread_for_hole(hole)
        if thread is None:
            raise AdapterError(f"{side}法兰通孔 {hole:g} mm 太小，ISO 273 表中没有合适的螺纹")
        spec["hole_kind"] = _pv("threaded", f"{side}为通孔，板上攻螺纹（ADR-0041）")
        spec["thread"] = _pv(thread, f"ISO 273 中等系列间隙孔 ≤ {hole:g} mm 的最大螺纹")
        return spec, _thread_d(thread), _thread_d(thread)
    thread = text(other.get("thread"))
    need = rules.iso273_medium().get((thread or "").split("x")[0])
    if need is None:
        raise AdapterError(f"{side}法兰螺纹 {thread} 不在 ISO 273 表中")
    spec["hole_kind"] = _pv("through", f"{side}为螺纹孔，板上开间隙孔（ADR-0041）")
    spec["hole_diameter_mm"] = _pv(need, f"{thread} 的 ISO 273 中等系列间隙孔")
    return spec, need, 0.0


def _pilot(other: dict, spec: dict, side: str) -> float:
    kind, d = text(other.get("pilot_kind")), _num(other, "pilot_diameter_mm")
    if kind is None and d is None:
        return 0.0
    if kind not in ("male", "female") or d is None:
        raise AdapterError(f"{side}法兰止口数据不全")
    mine = "female" if kind == "male" else "male"
    spec["pilot_kind"] = _pv(mine, f"{side}为{'凸' if kind == 'male' else '凹'}止口，板上做{'凹' if mine == 'female' else '凸'}止口")
    spec["pilot_diameter_mm"] = _pv(d, f"= {side}止口直径")
    spec["pilot_fit"] = _pv("H7" if mine == "female" else "h7", "凹止口 H7，凸止口 h7（ADR-0041）")
    return d


def _holes(pcd: float, n: int, offset: float) -> list[tuple[float, float]]:
    return [(pcd / 2 * math.cos(math.radians(offset + 360 * i / n)),
             pcd / 2 * math.sin(math.radians(offset + 360 * i / n))) for i in range(n)]


def _collide(a: list, da: float, b: list, db: float) -> bool:
    gap = (da + db) / 2 + HOLE_GAP_MM
    return any(math.dist(p, q) < gap for p in a for q in b)


def plate(motor: dict, reducer: dict) -> dict:
    """电机法兰 → 减速器电机安装面的转接板；生成不了时抛出 AdapterError。"""
    mf, rf = _port(motor, "mount_flange"), _port(reducer, "motor_flange")
    if mf is None or rf is None:
        raise AdapterError("电机没有安装法兰端口或减速器没有电机安装面端口")
    ms, rs = mf["spec"], rf["spec"]
    m_spec, m_hole, m_thread = _plate_side(ms, "电机侧")
    r_spec, r_hole, r_thread = _plate_side(rs, "减速器侧")
    m_pilot, r_pilot = _pilot(ms, m_spec, "电机侧"), _pilot(rs, r_spec, "减速器侧")

    m_n, r_n = int(_num(ms, "hole_count")), int(_num(rs, "hole_count"))
    m_off = _num(ms, "hole_angle_offset_deg") or 0.0
    r_off = _num(rs, "hole_angle_offset_deg") or 0.0
    m_holes = _holes(_num(ms, "pcd_mm"), m_n, m_off)
    if _collide(m_holes, m_hole, _holes(_num(rs, "pcd_mm"), r_n, r_off), r_hole):
        r_off += 180 / r_n
        if _collide(m_holes, m_hole, _holes(_num(rs, "pcd_mm"), r_n, r_off), r_hole):
            raise AdapterError("两侧孔位互相碰撞，转半个孔距后仍碰撞")
        r_spec["hole_angle_offset_deg"] = _pv(r_off, "两侧孔位碰撞，减速器侧转半个孔距（ADR-0041）")

    thick = _round_up(max(MIN_PLATE_MM, 1.5 * max(m_thread, r_thread) + 2), 1.0)
    side = max(_num(ms, "square_size_mm") or 0.0,
               _num(ms, "pcd_mm") + m_hole + 2 * EDGE_MM,
               _num(rs, "pcd_mm") + r_hole + 2 * EDGE_MM,
               max(m_pilot, r_pilot) + 6)
    side = _round_up(side, 2.0)
    mass = ALUMINUM_KG_M3 * side * side * thick * 1e-9
    model = f"PL-{_fmt(_num(ms, 'pcd_mm'))}-{_fmt(_num(rs, 'pcd_mm'))}-{_fmt(thick)}"
    return {
        "id": f"adapter.fap-generated.{model.lower()}",
        "category": "adapter", "vendor": VENDOR, "model": model, "status": "active", "license": "open",
        "params": {
            "adapter_kind": _pv("flange_plate", "两侧法兰不一致，生成转接板（ADR-0041）"),
            "length_mm": _pv(thick, "max(8, 1.5 × 螺纹直径 + 2) mm，向上取整"),
            "mass_kg": _pv(round(mass, 4), "铝合金 2700 kg/m³ × 边长² × 板厚（未扣孔，偏保守）"),
        },
        "ports": [
            {"id": "motor_side", "type": "mechanical.flange", "dir": "bidir", "motion": "stationary",
             "frame": {"origin_mm": [0, 0, 0], "axis": [0, 0, 1]}, "spec": m_spec},
            {"id": "reducer_side", "type": "mechanical.flange", "dir": "bidir", "motion": "stationary",
             "frame": {"origin_mm": [0, 0, thick], "axis": [0, 0, 1]}, "spec": r_spec},
        ],
        "envelope": {"parts": [{"shape": "box", "z_start_mm": 0, "length_mm": _pv(thick, "= 板厚"),
                                "width_mm": _pv(side, "外形边长（ADR-0041）"),
                                "height_mm": _pv(side, "外形边长（ADR-0041）")}]},
        "note": NOTE,
    }
