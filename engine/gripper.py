"""抓手（gripper）的末端比较（ADR-0129 129.3，ADR-0115 44.5.4）。纯函数：不联网、不调用 AI、不读数据库。

需求：工件质量 part_mass_kg、末端最大加速度 accel_m_s2（取放节拍里梯形速度曲线的最大值）、安全系数 safety_factor（默认 2）、
同时用几个抓手 count（默认 1，载荷平均分）、工件材料 material（原话，如“布料”“裁片”）。
  G1 保持力：工件质量 ×（g + 最大加速度）× 安全系数 / 个数 ≤ 厂商给的保持力；厂商没给保持力 → unknown（不按针数、吸盘面积估）。
     厂商的保持力带条件（如“光滑干燥表面的理论吸力”）时，条件原话附在结论里
  G2 适用材料：厂商写了适用材料（suitable_materials）的，原话摘给人看；代码不据此判伤不伤工件、漏不漏气——
     只有原话里出现工件材料的词才判通过，否则 unknown（ADR-0115 第 4 节：不做布料的物理仿真）
  G3 一次只取一片（分层）：没有公开数据，一律 unknown
抓手质量计入末端负载（由整机代码加，不在这里）。
"""

from __future__ import annotations

from collections.abc import Mapping

from engine.result import PASS, UNKNOWN, CheckResult, Finding, overall
from engine.values import nominal

G = 9.80665
DEFAULT_SF = 2.0
TYPE_NAMES = {"suction_cup": "真空吸盘", "area_vacuum": "面状真空", "needle": "针刺抓手", "finger": "夹爪", "other": "抓手"}


def _p(comp: Mapping, name: str):
    return (comp.get("params") or {}).get(name) or {}


def required_force(req: Mapping) -> float | None:
    """抓取力下限（N）：m ×（g + a）× 安全系数 / 个数"""
    m, a = req.get("part_mass_kg"), req.get("accel_m_s2")
    if m is None or a is None:
        return None
    sf = float(req.get("safety_factor") or DEFAULT_SF)
    return m * (G + abs(a)) * sf / max(int(req.get("count") or 1), 1)


def check(req: Mapping, comp: Mapping) -> dict:
    need = required_force(req)
    hf = _p(comp, "holding_force_n")
    cap = nominal(hf)
    gtype = _p(comp, "gripper_type").get("value")
    if need is None:
        g1 = CheckResult("G1", [Finding(UNKNOWN, "工件质量或末端加速度缺数据")])
    elif cap is None:
        g1 = CheckResult("G1", [Finding(UNKNOWN, f"厂商没给保持力（{TYPE_NAMES.get(gtype, '抓手')}），抓取力判待确认；至少要 {need:.3g} N")])
    else:
        cond = f"（厂商：{hf['condition']}）" if hf.get("condition") else ""
        st = PASS if need <= cap + 1e-12 else "fail"
        g1 = CheckResult("G1", [Finding(st, f"保持力：需要 m(g+a)×安全系数/个数 = {need:.3g} N，厂商给 {cap:.3g} N{cond}",
                                        measured=need, limit=cap, unit="N")])
    mats = _p(comp, "suitable_materials").get("value")
    material = (req.get("material") or "").strip()
    if not mats:
        g2 = CheckResult("G2", [Finding(UNKNOWN, "厂商没写适用材料，伤不伤工件、透气工件漏不漏气判待确认")])
    else:
        text = "、".join(mats) if isinstance(mats, list) else str(mats)
        hit = bool(material) and any(material in t or t in material for t in (mats if isinstance(mats, list) else [text]))
        g2 = CheckResult("G2", [Finding(PASS if hit else UNKNOWN, f"厂商写的适用材料：{text}"
                                        + ("" if hit else f"；没写到“{material or '工件材料'}”，判待确认"))])
    g3 = CheckResult("G3", [Finding(UNKNOWN, "一次只取一片（分层）可靠不可靠，没有公开数据，判待确认")])
    res = [g1, g2, g3]
    return {"component": comp["id"], "type": gtype, "overall": overall(res), "checks": [r.to_dict() for r in res],
            "mass_kg": nominal(_p(comp, "mass_kg")), "required_force_n": need}


def compare(req: Mapping, comps) -> list[dict]:
    """库里的抓手逐个比：每种类型（针刺、吸盘……）里保持力判通过的取最轻（没有质量的按保持力最小），
    厂商没给保持力的类型各列一个代表；不通过的不列。返回按类型排好的比较表，供报告与人决定"""
    by_type: dict[str, list[dict]] = {}
    for c in comps:
        if c.get("category") != "gripper":
            continue
        r = check(req, c)
        g1 = r["checks"][0]
        if g1["status"] == "fail":
            continue
        r["holding_force_n"] = g1.get("limit")
        by_type.setdefault(r["type"] or "other", []).append(r)
    out = []
    for gtype in sorted(by_type):
        rs = by_type[gtype]
        rs.sort(key=lambda r: (r["checks"][0]["status"] != PASS, r["mass_kg"] is None, r["mass_kg"] or 0.0,
                               r["holding_force_n"] or 0.0, r["component"]))
        out.append(rs[0])
    return out
