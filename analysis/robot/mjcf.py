"""整机方案（robot-concept/1）→ 多体动力学模型（MuJoCo MJCF，ADR-0115 第 44.3 步）。

质量只用算得出来的：
  杆件：截面 × 长度（length_mm）× 材料密度（analysis/common/materials.yaml）；按形状算截面积：
        tube π/4·(od² − id²)、box w·h − (w − 2t)(h − 2t)（没写壁厚按实心）、plate w·t；
        profile（型材）截面积要看型材样本，这里算不出 → 不给质量（mass_problems 里列出）。
        质量沿杆件坐标系原点到下一关节（叶子杆件到工具点）均布；没有这段长度的按集中在原点。
  关节模组（电机 + 减速器）：由调用者按所选零件的样本质量给，集中在关节处、算在父件上（定子装在父件上；转子的质量与惯量不计）。
  末端负载：集中在工具点。夹爪等末端执行器本身的质量方案里没有，不计（调用者要计就并进负载）。
坐标与转角方向同 kinematics（关节绕 axis 右手转）。世界坐标 z 朝上、重力 −z（analysis.mbd 固定 g = 9.81）：
安装面朝上（floor、table）基座坐标与世界同向；吊装（ceiling）基座绕 x 翻转 180°（基座坐标的 +z 朝下）；
墙装时基座朝哪个方向方案里没写，判不了；移动底盘不在这里建模。
纯计算：不联网、不调用 AI。
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np

from analysis.robot import kinematics as K

BASE_QUAT = {"floor": "1 0 0 0", "table": "1 0 0 0", "ceiling": "0 1 0 0"}   # 基座相对世界的姿态（w x y z）


def section_area_mm2(link: Mapping) -> float | None:
    """截面积（mm²）；算不出返回 None"""
    s = link.get("section") or {}
    shape = link.get("shape")
    if shape == "tube" and s.get("od_mm"):
        di = s.get("id_mm") or 0.0
        return math.pi / 4 * (s["od_mm"] ** 2 - di ** 2) if di < s["od_mm"] else None
    if shape == "box" and s.get("width_mm") and s.get("height_mm"):
        w, h, t = s["width_mm"], s["height_mm"], s.get("wall_mm")
        if not t:
            return w * h
        return w * h - max(w - 2 * t, 0) * max(h - 2 * t, 0)
    if shape == "plate" and s.get("width_mm") and s.get("thickness_mm"):
        return s["width_mm"] * s["thickness_mm"]
    return None


def link_mass_kg(link: Mapping) -> float | None:
    """杆件质量（kg）：截面积 × 长度 × 密度；截面、长度或材料缺任何一项返回 None（不估）"""
    from analysis.common import materials

    a = section_area_mm2(link)
    mat = link.get("material")
    if a is None or not mat or not link.get("length_mm"):
        return None
    try:
        rho = materials.get(mat).get("density_kg_m3")
    except materials.MissingData:
        return None
    if not rho:
        return None
    return a * float(link["length_mm"]) * rho * 1e-9


def link_masses(concept: Mapping) -> tuple[dict[str, float], list[str]]:
    """{杆件: 质量 kg} 与算不出质量的杆件说明"""
    out, probs = {}, []
    for lk in concept["links"]:
        m = link_mass_kg(lk)
        if m is None:
            probs.append(f"杆件 {lk['id']}（{lk.get('shape')}）的质量算不出：截面、长度或材料缺数据")
        else:
            out[lk["id"]] = m
    return out, probs


def _segment(m: K.Model, link: str) -> np.ndarray:
    """杆件质量分布的另一端（杆件坐标系，mm）：下一关节的原点（有几个取平均）；叶子杆件取工具点"""
    kids = [j.origin for j in m.joints if j.parent == link]
    if kids:
        return np.mean(kids, axis=0)
    if link == m.tool_link:
        return m.tool_offset
    return np.zeros(3)


def _radius_m(link: Mapping) -> float:
    s = link.get("section") or {}
    r = (s.get("od_mm") or max(s.get("width_mm") or 0, s.get("height_mm") or 0) or 20.0) / 2
    return r / 1000


def _f(v) -> str:
    return " ".join(f"{float(x):.6g}" for x in v)


def mjcf(concept: Mapping, *, module_masses_kg: Mapping[str, float] | None = None, payload_kg: float = 0.0) -> str:
    """生成 MJCF（米、千克）。关节名同方案里的关节 id；工具点 site 名 tool。
    module_masses_kg：{关节 id: 电机 + 减速器质量}；没给的关节不计模组质量。杆件质量算不出时报错（不估）。"""
    m = K.build(concept)
    kind = concept["kind"]
    mount = concept["base"]["mount"]
    if kind == "mobile_base" or mount not in BASE_QUAT:
        raise K.ConceptError(f"{kind} / 安装方式 {mount}：重力方向或整车质量判不了，这一步不建动力学模型")
    lm, probs = link_masses(concept)
    if probs:
        raise K.ConceptError("；".join(probs))
    mods = dict(module_masses_kg or {})
    for k, v in mods.items():
        if k not in {j.id for j in m.joints} or not isinstance(v, (int, float)) or v < 0:
            raise K.ConceptError(f"模组质量 {k} = {v!r} 不对：关节要存在、质量非负")

    def body(j: K.Joint) -> str:
        link = m.links[j.child]
        end = _segment(m, j.child) / 1000
        mass = lm[j.child]
        r = _radius_m(link)
        if float(np.linalg.norm(end)) > 1e-6:
            geom = f'<geom type="capsule" fromto="0 0 0 {_f(end)}" size="{r:.4f}" mass="{mass:.6g}" rgba="0.24 0.47 0.67 1"/>'
        else:
            geom = f'<geom type="sphere" size="{r:.4f}" mass="{mass:.6g}" rgba="0.24 0.47 0.67 1"/>'
        if j.type == "prismatic":
            jt = f'<joint name="{j.id}" type="slide" axis="{_f(j.axis)}"/>'
        else:
            jt = f'<joint name="{j.id}" type="hinge" axis="{_f(j.axis)}"/>'
        inner = "".join(body(c) for c in m.joints if c.parent == j.child)
        if j.child == m.tool_link:
            tp = m.tool_offset / 1000
            inner += f'<site name="tool" pos="{_f(tp)}"/>'
            if payload_kg > 0:
                inner += (f'<body name="payload" pos="{_f(tp)}"><inertial pos="0 0 0" mass="{payload_kg:.6g}" '
                          'diaginertia="1e-6 1e-6 1e-6"/></body>')
        return f'<body name="{j.child}" pos="{_f(j.origin / 1000)}">{jt}{geom}{modules(j.child)}{inner}</body>'

    def modules(parent: str) -> str:
        """装在 parent 上的关节模组（集中质量，在关节原点）"""
        out = ""
        for c in m.joints:
            if c.parent == parent and mods.get(c.id, 0) > 0:
                out += (f'<body name="{c.id}_module" pos="{_f(c.origin / 1000)}"><inertial pos="0 0 0" '
                        f'mass="{mods[c.id]:.6g}" diaginertia="1e-6 1e-6 1e-6"/></body>')
        return out

    roots = "".join(body(j) for j in m.joints if j.parent == "base")
    return ('<mujoco model="robot-concept"><compiler angle="radian" autolimits="true"/>'
            f'<option timestep="0.0005"/><worldbody><body name="base" quat="{BASE_QUAT[mount]}">'
            f'<geom type="cylinder" size="0.04 0.01" mass="0" rgba="0.3 0.3 0.3 1"/>{modules("base")}{roots}'
            '</body></worldbody></mujoco>')
