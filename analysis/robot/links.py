"""整机方案的杆件校核（ADR-0115 44.3 之二第 1 步）：强度与末端下垂。纯计算：不联网、不调用 AI。

做法（材料力学，梁按细长悬臂）：
  1 姿态：给定关节角（一般取水平伸直，重力力臂最大）。
  2 静载：每根杆件根部（带动它的关节处）承受下游全部重量对根部的力矩 M = Σ (rᵢ − o) × mᵢ·g。
    下游重量：本杆与后面各杆的质量（截面 × 长度 × 密度，均布在本关节到下一关节之间）、装在这些杆上的关节模组（集中在关节处）、末端负载。
    M 沿杆轴的分量是扭矩 T，垂直杆轴的是弯矩 M_b。
  3 动载：静载乘动载系数 k（由多体动力学的峰值力矩 / 同一关节静重力矩得来，取各关节的最大值；调用者给）。
  4 应力：管 Z = π(D⁴ − d⁴)/(32D)，σ = M_b/Z，τ = T/(2Z)；箱形与板按矩形截面的抗弯截面系数；当量应力 σ_eq = √(σ² + 3τ²)。
    对屈服强度、弯曲疲劳极限的安全系数 = 强度 / (k·σ_eq)，与要求的安全系数比。
  5 末端下垂（只报数）：每根杆按悬臂、端部集中力 P = M_b / l 估算端部挠度 P·l³/(3EI) 与转角 P·l²/(2EI)，
    转角再乘以杆端到工具点的距离，逐杆相加。关节（模组）本身的刚度厂商没给，不计——所以这是只算杆件的下限。
型材（profile）截面积与截面系数要看样本，判 unknown。
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np

from analysis.robot import kinematics as K
from analysis.robot import mjcf

G = 9.81                                       # 与 analysis.mbd 一致


def section_modulus_mm3(link: Mapping) -> float | None:
    """抗弯截面系数 Z（mm³）"""
    s = link.get("section") or {}
    shape = link.get("shape")
    if shape == "tube" and s.get("od_mm"):
        D, d = s["od_mm"], s.get("id_mm") or 0.0
        return math.pi * (D ** 4 - d ** 4) / (32 * D) if d < D else None
    if shape == "box" and s.get("width_mm") and s.get("height_mm"):
        b, h, t = s["width_mm"], s["height_mm"], s.get("wall_mm")
        bi, hi = (max(b - 2 * t, 0), max(h - 2 * t, 0)) if t else (0, 0)
        zb = (b * h ** 3 - bi * hi ** 3) / (6 * h)
        zh = (h * b ** 3 - hi * bi ** 3) / (6 * b)
        return min(zb, zh)                                   # 弯曲方向随姿态变：取弱的那个方向（偏保守）
    if shape == "plate" and s.get("width_mm") and s.get("thickness_mm"):
        b, t = s["width_mm"], s["thickness_mm"]
        return b * t ** 2 / 6                              # 绕弱轴（偏保守）
    return None


def check(concept: Mapping, q: Mapping[str, float], *, module_masses_kg: Mapping[str, float] | None = None,
          payload_kg: float = 0.0, dynamic_factor: float = 1.0, required_safety: float | None = None) -> dict:
    """返回 {"items": [...], "overall", "tool_sag_mm", "dynamic_factor"}"""
    from analysis.common import materials

    m = K.build(concept)
    T = K.fk(m, q)
    tip = K.tool_point(m, q)
    modules = dict(module_masses_kg or {})
    lm, probs = mjcf.link_masses(concept)
    # 质量点：(所在杆件, 位置, 质量)
    pts = []
    for j in m.joints:
        if j.child in lm:
            end = mjcf._segment(m, j.child)
            pts.append((j.child, (T[j.child] @ np.append(end / 2, 1.0))[:3], lm[j.child]))
        if modules.get(j.id):
            pts.append((j.parent, (T[j.parent] @ np.append(j.origin, 1.0))[:3], float(modules[j.id])))
    if payload_kg and m.tool_link:
        pts.append((m.tool_link, tip, float(payload_kg)))
    below: dict[str, set[str]] = {lk: {lk} for lk in m.links}
    for j in reversed(m.joints):                       # 子在后：倒序把子树并进父件
        if j.parent in below:
            below[j.parent] |= below[j.child]
    items, sag = [], 0.0
    for j in m.joints:
        lk = m.links[j.child]
        end_local = mjcf._segment(m, j.child)
        length = float(np.linalg.norm(end_local))
        if length < 1e-6:
            continue                                    # 没有长度的杆（末端法兰等）不按梁算
        o = (T[j.parent] @ np.append(j.origin, 1.0))[:3]
        u = T[j.child][:3, :3] @ (end_local / length)
        Mv = np.zeros(3)
        for owner, r, mass in pts:
            if owner in below[j.child]:
                Mv += np.cross((r - o) / 1000.0, np.array([0.0, 0.0, -mass * G]))
        Tq = abs(float(Mv @ u))
        Mb = float(np.linalg.norm(Mv - (Mv @ u) * u))
        name = f"杆件 {j.child}"
        Z = section_modulus_mm3(lk)
        try:
            mat = materials.get(lk.get("material") or "")
        except materials.MissingData:
            mat = None
        if Z is None or mat is None:
            items.append({"item": name, "status": "unknown", "note": "截面或材料缺数据（型材截面要看样本）"})
            continue
        sigma = Mb * 1000.0 / Z
        tau = Tq * 1000.0 / (2 * Z)
        seq = math.hypot(sigma, math.sqrt(3) * tau) * dynamic_factor
        sy, se = mat.get("yield_strength_mpa"), mat.get("fatigue_limit_bending_mpa")
        sf_y = sy / seq if sy and seq > 0 else None
        sf_f = se / seq if se and seq > 0 else None
        row = {"item": name, "bending_nm": round(Mb, 4), "torsion_nm": round(Tq, 4), "sigma_eq_mpa": round(seq, 3),
               "safety_yield": None if sf_y is None else round(sf_y, 2),
               "safety_fatigue": None if sf_f is None else round(sf_f, 2)}
        if required_safety is None or sf_y is None or sf_f is None:
            row["status"] = "unknown"
            row["note"] = "需求没给安全系数要求" if required_safety is None else "材料缺屈服强度或疲劳极限"
        else:
            worst = min(sf_y, sf_f)
            row["status"] = "pass" if worst >= required_safety else "fail"
            row["note"] = (f"当量应力 {seq:.2f} MPa（含动载系数 {dynamic_factor:.2f}）；对屈服 {sf_y:.1f}、对弯曲疲劳 {sf_f:.1f}，"
                           f"要求 ≥ {required_safety:g}")
        items.append(row)
        # 末端下垂（静载，不乘动载系数）：悬臂端部集中力 P = M_b / l
        E = mat.get("elastic_modulus_mpa")
        s = lk.get("section") or {}
        if E and lk.get("shape") == "tube":
            D, d = s["od_mm"], s.get("id_mm") or 0.0
            inertia = math.pi * (D ** 4 - d ** 4) / 64                   # mm⁴
            P = Mb * 1000.0 / length                                      # N
            defl = P * length ** 3 / (3 * E * inertia)                    # mm
            theta = P * length ** 2 / (2 * E * inertia)                   # rad
            end_world = (T[j.child] @ np.append(end_local, 1.0))[:3]
            sag += defl + theta * float(np.linalg.norm(tip - end_world))
    st = {i["status"] for i in items}
    overall = "fail" if "fail" in st else "unknown" if "unknown" in st or probs else "pass"
    return {"items": items, "overall": overall, "tool_sag_mm": round(sag, 4), "dynamic_factor": round(dynamic_factor, 3),
            "notes": probs + ["末端下垂只算杆件弯曲；关节模组的刚度厂商没给，不计"]}
