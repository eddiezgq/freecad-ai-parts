"""阶梯轴设计方案的确定性校核（ADR-0100 42.2 的代码一半）：AI 提议结构与自由尺寸，这里全部由代码核对与计算。

方案（AI 提议，代码先核对格式）：
  {"segments": [{"role": "...", "length_mm": L, "diameter_mm": d（自由段）, "bearing": "组件 id"（轴承位）,
                 "fillet_mm": r（与下一段之间的过渡圆角）}], "reason": "..."}
  轴承位的直径、长度不由 AI 给：直径 = 库里轴承内径，长度缺省 = 轴承宽度（AI 可以给更长）。

条件（从需求原话来，已由调用方核对过原文）：
  speeds_rpm、bearing_centers_mm（两个轴承中心的 z）、loads（同 analysis.shaft）、drive_z_mm、masses、material、surface、
  required_safety、critical_ratio、bearing_life_h（可缺）

校核项（每项 pass / fail / unknown，unknown 不算通过）：
  位置：轴承位中心与要求的轴承中心一致（±0.5 mm）；载荷、集中质量的位置在轴上
  装配：每个轴承都能从某一端套进去（途经的轴段直径都不大于轴承内径）；轴承靠轴肩定位（相邻一段更粗）
  轴肩高度、圆角与轴承倒角：库里没有轴承安装尺寸（da、r_s）时为 unknown，不估
  强度：每个台阶截面的无限寿命安全系数（理论应力集中系数用有限元算，analysis.shaft.kt），各转速
  临界转速：一阶 / 最高转速 ≥ 要求
  轴承寿命：L10h = 10⁶/(60n)·(C/P)³，P 取一转之内支反力的立方平均

纯计算：不联网、不调用 AI。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from itertools import pairwise

import numpy as np

POS_TOL_MM = 0.5
ROLES = ("journal", "bearing_seat", "shoulder", "body", "crank_seat", "pulley_seat", "cam_seat", "gear_seat", "end")


class ProposalInvalid(ValueError):
    pass


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def check_proposal(p, get: Callable[[str], dict | None]) -> tuple[list[dict], list[str]]:
    """核对方案格式并补上轴承位的尺寸：返回（轴段 [{role, d, L, bearing?, r?}], 退回的说明）"""
    if not isinstance(p, dict) or not isinstance(p.get("segments"), list) or not p["segments"]:
        raise ProposalInvalid("方案里没有轴段")
    out, notes = [], []
    for i, s in enumerate(p["segments"], 1):
        if not isinstance(s, dict):
            raise ProposalInvalid(f"第 {i} 段不是对象")
        role = s.get("role")
        if role not in ROLES:
            raise ProposalInvalid(f"第 {i} 段的用途 {role!r} 不在清单里：{'、'.join(ROLES)}")
        seg = {"role": role}
        r = _num(s.get("fillet_mm"))
        if r is not None:
            if r <= 0:
                raise ProposalInvalid(f"第 {i} 段的圆角要大于 0")
            seg["r"] = r
        if role == "bearing_seat":
            bid = s.get("bearing")
            comp = get(bid) if isinstance(bid, str) else None
            if comp is None or comp.get("category") != "bearing":
                raise ProposalInvalid(f"第 {i} 段（轴承位）的轴承 {bid!r} 不在零件库里")
            inner = next((p_ for p_ in comp["ports"] if p_["id"] == "inner"), {})
            d = _num(((inner.get("spec") or {}).get("diameter_mm") or {}).get("value"))
            b = _num((comp["params"].get("width_mm") or {}).get("value"))
            if d is None or b is None:
                raise ProposalInvalid(f"轴承 {bid} 缺内径或宽度，排不了轴承位")
            if _num(s.get("diameter_mm")) not in (None, d):
                notes.append(f"第 {i} 段轴承位直径按轴承内径取 {d:g} mm（方案给的 {s['diameter_mm']} 不用）")
            length = _num(s.get("length_mm"))
            if length is None or length < b:
                if length is not None:
                    notes.append(f"第 {i} 段轴承位长度 {length:g} 短于轴承宽度，按宽度 {b:g} mm 取")
                length = b
            seg.update(d=d, L=length, bearing=bid)
        else:
            d, length = _num(s.get("diameter_mm")), _num(s.get("length_mm"))
            if d is None or length is None or d <= 0 or length <= 0:
                raise ProposalInvalid(f"第 {i} 段要给直径和长度（大于 0）")
            seg.update(d=d, L=length)
        out.append(seg)
    return out, notes


def _item(name, status, value=None, limit=None, note="", **kw):
    return {"item": name, "status": status, **({"value": value} if value is not None else {}),
            **({"limit": limit} if limit is not None else {}), **({"note": note} if note else {}), **kw}


def layout(segs):
    z, out = 0.0, []
    for s in segs:
        out.append({**s, "z0": z, "z1": z + s["L"]})
        z += s["L"]
    return out


def geometry_checks(segs: list[dict], cond: dict, get) -> list[dict]:
    lay = layout(segs)
    length = lay[-1]["z1"]
    items = []
    seats = [s for s in lay if s["role"] == "bearing_seat"]
    want = sorted(float(z) for z in cond.get("bearing_centers_mm") or [])
    have = sorted((s["z0"] + s["z1"]) / 2 for s in seats)
    if len(want) != len(have):
        items.append(_item("轴承位数量", "fail", len(have), len(want), "与要求的轴承中心个数不同"))
    else:
        for w, h in zip(want, have, strict=True):
            ok = abs(w - h) <= POS_TOL_MM
            items.append(_item(f"轴承中心 z = {w:g} mm", "pass" if ok else "fail", round(h, 3), w,
                               "" if ok else f"差 {h - w:+.2f} mm"))
    for name, z in [(f"载荷 {ld.get('type')}", ld["z_mm"]) for ld in cond.get("loads") or []] + \
                   [(f"集中质量 {m.get('name', '')}", m["z_mm"]) for m in cond.get("masses") or []]:
        if not 0 <= float(z) <= length:
            items.append(_item(f"{name} 的位置", "fail", float(z), None, f"不在轴上（轴长 {length:g} mm）"))
    for k, s in enumerate(lay):
        if s["role"] != "bearing_seat":
            continue
        d = s["d"]
        left_ok = all(x["d"] <= d + 1e-9 for x in lay[:k])
        right_ok = all(x["d"] <= d + 1e-9 for x in lay[k + 1:])
        items.append(_item(f"轴承 {s['bearing'].split('.')[-1]}（z {s['z0']:g}–{s['z1']:g}）能套进去",
                           "pass" if left_ok or right_ok else "fail", note="" if left_ok or right_ok else
                           "两端途经的轴段都比轴承内径粗"))
        nb = [lay[j]["d"] for j in (k - 1, k + 1) if 0 <= j < len(lay)]
        located = any(x > d + 1e-9 for x in nb)
        items.append(_item(f"轴承 {s['bearing'].split('.')[-1]} 有轴肩定位", "pass" if located else "fail",
                           note="" if located else "相邻两段都不比轴承位粗"))
        items += shoulder_checks(lay, k, get(s["bearing"]) or {})
    return items


def _param(comp: dict, name: str) -> float | None:
    return _num((comp.get("params", {}).get(name) or {}).get("value"))


def shoulder_checks(lay: list[dict], k: int, comp: dict) -> list[dict]:
    """定位轴肩（比轴承位粗的相邻段）：直径在 da min–da max 之内，过渡圆角不大于 ra max（ADR-0103）；库里没有就待确认"""
    seat, tag = lay[k], comp.get("id", "?").split(".")[-1]
    out = []
    for j, r_owner in ((k - 1, k - 1), (k + 1, k)):
        if not 0 <= j < len(lay) or lay[j]["d"] <= seat["d"] + 1e-9:
            continue
        side = "左" if j < k else "右"
        dmin, dmax, rmax = _param(comp, "abutment_shaft_min_mm"), _param(comp, "abutment_shaft_max_mm"), _param(comp, "fillet_max_mm")
        big = lay[j]["d"]
        if dmin is None:
            out.append(_item(f"轴承 {tag} {side}侧轴肩高度", "unknown", big, None,
                             "零件库没有这个轴承的安装尺寸（da min），轴肩高度查不了"))
        else:
            ok = big >= dmin - 1e-9 and (dmax is None or big <= dmax + 1e-9)
            lim = f"{dmin:g}–{dmax:g}" if dmax is not None else f"≥ {dmin:g}"
            out.append(_item(f"轴承 {tag} {side}侧轴肩直径", "pass" if ok else "fail", big, lim,
                             "" if ok else ("轴肩太低，挡不住内圈" if big < dmin else "轴肩太高，碰保持架或密封、不好拆")))
        r = lay[r_owner].get("r")
        if rmax is None or r is None:
            out.append(_item(f"轴承 {tag} {side}侧轴肩圆角", "unknown", r, rmax,
                             "零件库没有这个轴承的安装尺寸（ra max），圆角查不了" if rmax is None else "方案没给这个台阶的圆角"))
        else:
            out.append(_item(f"轴承 {tag} {side}侧轴肩圆角", "pass" if r <= rmax + 1e-9 else "fail", r, f"≤ {rmax:g}",
                             "" if r <= rmax + 1e-9 else "圆角大于 ra max，内圈靠不上轴肩"))
    return out


def steps(segs: list[dict]) -> list[dict]:
    """台阶截面：相邻两段直径不同处，截面取小径、圆角取方案给的（没给为 None）"""
    lay = layout(segs)
    out = []
    for a, b in pairwise(lay):
        if abs(a["d"] - b["d"]) < 1e-9:
            continue
        small, big = (a, b) if a["d"] < b["d"] else (b, a)
        out.append({"z_mm": a["z1"], "d": small["d"], "D": big["d"], "r": a.get("r")})
    return out


def bearing_life(cr_n: float, loads_n: np.ndarray, n_rpm: float) -> tuple[float, float]:
    """球轴承：P = 一转之内径向载荷的立方平均；L10h = 10⁶/(60n)·(C/P)³。返回（P, L10h）"""
    p = float(np.cbrt(np.mean(np.abs(loads_n) ** 3)))
    return p, (1e6 / (60 * n_rpm)) * (cr_n / p) ** 3 if p > 0 else math.inf


def evaluate(proposal, cond: dict, get: Callable[[str], dict | None], *, kt: Callable | None = None) -> dict:
    """全部校核。kt(d, D, r) → {"kt_bending", "kt_torsion", "method"}；缺省用有限元（analysis.shaft.kt）"""
    from analysis import shaft

    segs, notes = check_proposal(proposal, get)
    items = geometry_checks(segs, cond, get)
    sections, unknown_steps = [], []
    if kt is None:
        from analysis.shaft.kt import stepped_bar as kt
    for st in steps(segs):
        if st["r"] is None:
            unknown_steps.append(st)
            items.append(_item(f"台阶 Ø{st['d']:g}→Ø{st['D']:g}（z {st['z_mm']:g}）强度", "unknown",
                               note="方案没给过渡圆角，算不了应力集中"))
            continue
        if st["r"] >= (st["D"] - st["d"]) / 2 - 1e-9:
            items.append(_item(f"台阶 Ø{st['d']:g}→Ø{st['D']:g}（z {st['z_mm']:g}）圆角", "fail", st["r"],
                               f"< {(st['D'] - st['d']) / 2:g}", "圆角不小于台阶高度，台阶端面没有平面，做不出来"))
            continue
        try:
            k = kt(st["d"], st["D"], st["r"])
        except Exception as ex:  # noqa: BLE001 — 有限元算不出：这一台阶记为待确认，说明原因
            items.append(_item(f"台阶 Ø{st['d']:g}→Ø{st['D']:g}（z {st['z_mm']:g}）强度", "unknown",
                               note=f"应力集中系数没算出来：{ex}"))
            continue
        sections.append({"name": f"台阶 Ø{st['d']:g}→Ø{st['D']:g}（z {st['z_mm']:g}）", "z_mm": st["z_mm"], "diameter_mm": st["d"],
                         "fillet_mm": st["r"], "kt_bending": k["kt_bending"], "kt_torsion": k["kt_torsion"],
                         "kt_source": k.get("method", ""), "surface": cond.get("surface", "machined")})
    centers = sorted(float(z) for z in cond.get("bearing_centers_mm") or [])
    setup = {"material": cond["material"], "segments": [{"diameter_mm": s["d"], "length_mm": s["L"]} for s in segs],
             "supports": centers, "speeds_rpm": cond["speeds_rpm"], "drive_z_mm": cond.get("drive_z_mm"),
             "masses": cond.get("masses") or [], "loads": cond.get("loads") or [], "sections": sections}
    if setup["drive_z_mm"] is None:
        setup.pop("drive_z_mm")
    res = shaft.run(setup)
    if res["status"] != "ok":
        items.append(_item("轴的计算", "fail", note="；".join(res["messages"])))
        return {"segments": layout(segs), "items": items, "notes": notes, "analysis": res, "overall": "fail"}
    data = res["data"]
    req = cond.get("required_safety")
    for sp in data["speeds"]:
        for s in sp["sections"]:
            if s["S"] is None:
                items.append(_item(f"{s['name']} {sp['speed_rpm']:g} r/min 安全系数", "pass", note="截面上没有交变应力"))
                continue
            st = "unknown" if req is None else ("pass" if s["S"] >= float(req) else "fail")
            fmt = lambda v: "∞" if v is None else f"{v:.2f}"
            items.append(_item(f"{s['name']} {sp['speed_rpm']:g} r/min 安全系数", st, round(s["S"], 3), req,
                               f"Sσ {fmt(s['S_sigma'])}、Sτ {fmt(s['S_tau'])}"))
    cr = cond.get("critical_ratio")
    items.append(_item("一阶临界转速 / 最高转速", "unknown" if cr is None else ("pass" if data["critical_ratio"] >= float(cr) else "fail"),
                       round(data["critical_ratio"], 3), cr, f"一阶 {data['critical_speeds_rpm'][0]:.0f} r/min"))
    life_req = cond.get("bearing_life_h")
    th = np.linspace(0, 2 * np.pi, shaft.N_THETA + 1)[:-1]
    for sp in data["speeds"]:
        forces = shaft.point_forces(cond.get("loads") or [], th, sp["speed_rpm"])
        for k, zs in enumerate(centers):
            seat = next((s for s in layout(segs) if s["role"] == "bearing_seat" and abs((s["z0"] + s["z1"]) / 2 - zs) <= POS_TOL_MM), None)
            if seat is None or not forces:
                continue
            za, zb = centers
            rx = -sum(f[1] * (f[0] - za) for f in forces) / (zb - za)
            ry = -sum(f[2] * (f[0] - za) for f in forces) / (zb - za)
            if k == 0:
                rx, ry = -sum(f[1] for f in forces) - rx, -sum(f[2] for f in forces) - ry
            comp = get(seat["bearing"]) or {}
            c = _num((comp.get("params", {}).get("dynamic_load_rating_n") or {}).get("value"))
            name = f"轴承 {seat['bearing'].split('.')[-1]}（z {zs:g}）{sp['speed_rpm']:g} r/min 寿命"
            if c is None:
                items.append(_item(name, "unknown", note="零件库没有额定动载荷"))
                continue
            p, life = bearing_life(c, np.hypot(rx, ry), sp["speed_rpm"])
            st = "unknown" if life_req is None else ("pass" if life >= float(life_req) else "fail")
            items.append(_item(name, st, round(life, 0), life_req, f"当量载荷 P = {p:.0f} N（一转立方平均），C = {c:.0f} N"))
    status = [i["status"] for i in items]
    overall = "fail" if "fail" in status else ("unknown" if "unknown" in status else "pass")
    return {"segments": layout(segs), "items": items, "notes": notes, "analysis": res, "overall": overall,
            "mass_kg": data["mass_kg"]}


def feedback(report: dict) -> str:
    """给 AI 看的校核结论（下一轮改方案用）：只列没通过和待确认的项，带数字与要求"""
    lines = []
    for it in report["items"]:
        if it["status"] == "pass":
            continue
        v = f"：{it['value']}" if "value" in it else ""
        lim = f"（要求 {it['limit']}）" if it.get("limit") is not None else ""
        lines.append(f"- [{'不通过' if it['status'] == 'fail' else '待确认'}] {it['item']}{v}{lim}{('；' + it['note']) if it.get('note') else ''}")
    lines += [f"- 说明：{n}" for n in report.get("notes", [])]
    return "\n".join(lines) or "全部通过"
