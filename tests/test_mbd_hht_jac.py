"""HHT 的分组差分雅可比（ADR-0098 E2）：与逐列差分一致；梁链只要几组。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from analysis.mbd.dae import hht as H
from analysis.mbd.dae import model as MD
from analysis.mbd.dae import solve as S

pytest.importorskip("scipy")
FIX = Path(__file__).parent / "fixtures" / "mbd-model" / "valid"


def beam_chain(n, seg=20.0, end=0.05, steps=50):
    """钢棒（φ10）分成 n 段刚体，相邻段用梁元件连，第一段铰在地上，重力下摆"""
    d = 10.0
    area, i2 = np.pi * d * d / 4, np.pi * d ** 4 / 64
    m = 7850 * area * seg * 1e-9
    ixx = 0.5 * m * (d / 2000) ** 2
    iyy = m * ((seg / 1000) ** 2 / 12 + (d / 2000) ** 2 / 4)
    bodies, forces = [], []
    for k in range(n):
        bodies.append({"id": f"s{k}", "mass_kg": m, "cm_mm": [seg * (k + 0.5), 0, 0],
                       "inertia_kg_m2": {"ixx": ixx, "iyy": iyy, "izz": iyy}})
        if k:
            forces.append({"id": f"b{k}", "type": "beam", "body_i": f"s{k - 1}", "point_i_mm": [seg * (k - 0.5), 0, 0],
                           "body_j": f"s{k}", "point_j_mm": [seg * (k + 0.5), 0, 0], "y_axis": [0, 1, 0],
                           "youngs_modulus_mpa": 206000, "shear_modulus_mpa": 79000, "area_mm2": area,
                           "iyy_mm4": i2, "izz_mm4": i2, "ixx_mm4": 2 * i2, "damping_ratio": 0.001})
    return {"format": "mbd-model/1", "name": "梁元件链", "gravity_mm_s2": [0, -9810, 0], "bodies": bodies, "forces": forces,
            "joints": [{"id": "pin", "type": "revolute", "body_i": "ground", "body_j": "s0", "point_mm": [0, 0, 0],
                        "axis": [0, 0, 1]}],
            "analysis": {"type": "dynamic", "end_time_s": end, "output_steps": steps, "integrator": "HHT"}}


def _state(sysm):
    q = sysm.q0()
    keep, _ = S.independent_rows(sysm, q, 0.0)
    rows = S._rows(sysm, keep)
    q = S.assemble(sysm, q, 0.0, rows)
    rng = np.random.default_rng(1)
    qd = S.initial_velocity(sysm, q, 0.0, rows) + 1e-2 * rng.standard_normal(sysm.n)   # 速度随便给，测导数
    a, lam = S.accel(sysm, q, qd, 0.0, rows)
    return q, qd, a, lam, rows


def _g(sysm, rows, a, lam):
    def g(q, qd):
        J = sysm.jac(q, 0.0, rows)
        return sysm.mass(q) @ a + J.T @ lam - sysm.Q(q, qd, 0.0)
    return g


@pytest.mark.parametrize("name", ["pendulum.json", "slider_crank_all_d1.json", "d2_force_elements.json", "d3_contacts.json",
                                  "d6_flex_pendulum.json", "universal_static_then_dynamic.json", "d7_pid_turntable.json"])
def test_grouped_equals_column_by_column(name):
    doc = json.loads((FIX / name).read_text(encoding="utf-8"))
    sysm = MD.build(doc.get("instance", doc), FIX)
    q, qd, a, lam, rows = _state(sysm)
    ctrl = sysm.ctrl if getattr(sysm, "ctrl", None) is not None and sysm.ctrl.any else None
    if ctrl is not None:
        sysm.act = ctrl.outputs(0.0, sysm.measures(q, qd), ctrl.x0)
    groups = H.color_groups(sysm, ctrl)
    assert groups is not None
    g = _g(sysm, rows, a, lam)
    gq0, gqd0 = H.grouped_fd(g, q, qd, None)
    gq1, gqd1 = H.grouped_fd(g, q, qd, groups)
    sc = max(np.abs(gq0).max(), 1.0)
    assert np.abs(gq1 - gq0).max() <= 1e-12 * sc
    assert np.abs(gqd1 - gqd0).max() <= 1e-12 * max(np.abs(gqd0).max(), 1.0)


def test_chain_needs_three_groups():
    sysm = MD.build(beam_chain(50))
    groups = H.color_groups(sysm)
    assert len(groups) == 3                                  # 链：隔两个才不相邻
    q, qd, a, lam, rows = _state(sysm)
    g = _g(sysm, rows, a, lam)
    calls = {"n": 0}

    def counted(qq, vv):
        calls["n"] += 1
        return g(qq, vv)

    gq, _ = H.grouped_fd(counted, q, qd, groups)
    assert calls["n"] == 1 + 2 * 3 * 7                       # 逐列要 1 + 2 × 350
    gq0, _ = H.grouped_fd(g, q, qd, None)
    assert np.abs(gq - gq0).max() <= 1e-12 * np.abs(gq0).max()


def test_unknown_force_falls_back():
    sysm = MD.build(beam_chain(3))
    sysm.forces.append(("mystery", {}))
    assert H.color_groups(sysm) is None


# ---------------------------------------------------------------- ADR-0097 补充二十一放弃的对比，E2 做出来
D_ROD, L_ROD, R_CRANK = 10.0, 300.0, 50.0
E_ROD, G_ROD, RHO_ROD = 206000, 79000, 7850
A_ROD, I_ROD = np.pi * D_ROD ** 2 / 4, np.pi * D_ROD ** 4 / 64
ZETA = 0.02
W1 = 2 * np.pi * 223.4      # 连杆一阶弯曲（两种模型线性化都在 223 Hz）
# 起动：转速 0.02 s 内按 (1 − cos) 升到 2000 rpm（12000 °/s），角度是它的积分
RAMP = "6000*(min(time,0.02) - 0.02/pi*sin(pi*min(time,0.02)/0.02)) + 12000*(time - min(time,0.02))"


def _crank_base(end, steps):
    return {"format": "mbd-model/1", "name": "柔性曲柄滑块", "gravity_mm_s2": [0, 0, 0],
            "bodies": [{"id": "crank", "mass_kg": 0.2, "cm_mm": [R_CRANK / 2, 0, 0],
                        "inertia_kg_m2": {"ixx": 1e-5, "iyy": 1e-4, "izz": 1e-4}},
                       {"id": "slider", "mass_kg": 0.2, "cm_mm": [R_CRANK + L_ROD, 0, 0],
                        "inertia_kg_m2": {"ixx": 1e-3, "iyy": 1e-3, "izz": 1e-3}}],
            "joints": [{"id": "j0", "type": "revolute", "body_i": "ground", "body_j": "crank", "point_mm": [0, 0, 0], "axis": [0, 0, 1]},
                       {"id": "js", "type": "translational", "body_i": "ground", "body_j": "slider",
                        "point_mm": [R_CRANK + L_ROD, 0, 0], "axis": [1, 0, 0]}],
            "motions": [{"id": "drive", "joint": "j0", "dof": "rotation", "function": RAMP}], "forces": [],
            "analysis": {"type": "dynamic", "end_time_s": end, "output_steps": steps, "integrator": "HHT",
                         "rtol": 1e-7, "atol": 1e-9}}


def crank_flex(end, steps):
    """连杆是一个柔性构件（梁有限元 20 单元，Craig-Bampton，模态阻尼比 0.02）"""
    m = _crank_base(end, steps)
    m["bodies"].append({"id": "rod", "flex": {"type": "beam", "from_mm": [R_CRANK, 0, 0], "to_mm": [R_CRANK + L_ROD, 0, 0],
                                              "y_axis": [0, 1, 0], "youngs_modulus_mpa": E_ROD, "shear_modulus_mpa": G_ROD,
                                              "density_kg_m3": RHO_ROD, "area_mm2": A_ROD, "iyy_mm4": I_ROD, "izz_mm4": I_ROD,
                                              "ixx_mm4": 2 * I_ROD, "elements": 20, "fixed_interface_modes": 6,
                                              "damping_ratio": ZETA}})
    m["joints"] += [{"id": "ja", "type": "revolute", "body_i": "crank", "body_j": "rod", "point_mm": [R_CRANK, 0, 0], "axis": [0, 0, 1]},
                    {"id": "jb", "type": "spherical", "body_i": "rod", "body_j": "slider", "point_mm": [R_CRANK + L_ROD, 0, 0]}]
    return m


def crank_chain(end, steps, nseg=20):
    """连杆是 20 段刚体 + 梁元件；梁的 damping_ratio 是刚度比例阻尼系数（s），按一阶弯曲取等效 ζ = 0.02"""
    m = _crank_base(end, steps)
    seg = L_ROD / nseg
    mass = RHO_ROD * A_ROD * seg * 1e-9
    ixx = 0.5 * mass * (D_ROD / 2000) ** 2
    iyy = mass * ((seg / 1000) ** 2 / 12 + (D_ROD / 2000) ** 2 / 4)
    for k in range(nseg):
        m["bodies"].append({"id": f"s{k}", "mass_kg": mass, "cm_mm": [R_CRANK + seg * (k + 0.5), 0, 0],
                            "inertia_kg_m2": {"ixx": ixx, "iyy": iyy, "izz": iyy}})
        if k:
            m["forces"].append({"id": f"b{k}", "type": "beam", "body_i": f"s{k - 1}", "point_i_mm": [R_CRANK + seg * (k - 0.5), 0, 0],
                                "body_j": f"s{k}", "point_j_mm": [R_CRANK + seg * (k + 0.5), 0, 0], "y_axis": [0, 1, 0],
                                "youngs_modulus_mpa": E_ROD, "shear_modulus_mpa": G_ROD, "area_mm2": A_ROD,
                                "iyy_mm4": I_ROD, "izz_mm4": I_ROD, "ixx_mm4": 2 * I_ROD, "damping_ratio": 2 * ZETA / W1})
    m["joints"] += [{"id": "ja", "type": "revolute", "body_i": "crank", "body_j": "s0", "point_mm": [R_CRANK, 0, 0], "axis": [0, 0, 1]},
                    {"id": "jb", "type": "spherical", "body_i": f"s{nseg - 1}", "body_j": "slider", "point_mm": [R_CRANK + L_ROD, 0, 0]}]
    return m


def test_flexible_crank_slider_flex_body_vs_beam_chain():
    """同一根柔性连杆两种建模：柔性构件 vs 20 段刚体 + 梁元件链。固有频率一致，曲柄力矩（起动后的 0.04–0.08 s）差 < 2%"""
    from analysis.mbd.dae.run import run_model

    out = {}
    for name, fn in (("flex", crank_flex), ("chain", crank_chain)):
        lin = fn(0.01, 10)
        lin["analysis"] = {"type": "linear"}
        d, _ = run_model(lin)
        out[name + "_f1"] = min(x["frequency_hz"] for x in d["linear"]["modes"] if x["frequency_hz"] > 1)
        d, _ = run_model(fn(0.08, 80))
        out[name] = np.array(d["motions"]["drive"]["effort"])
        assert all(v["status"] != "fail" for v in d["verification"])
    assert out["chain_f1"] == pytest.approx(out["flex_f1"], rel=5e-3)
    a, b = out["flex"][40:], out["chain"][40:]
    assert np.abs(a - b).max() <= 0.02 * np.abs(a).max()


def test_fifty_segment_beam_chain_in_reasonable_time():
    """50 段钢梁元件链摆 0.1 s：本机 15 s（目标 30 s；CI 机器慢，这里只卡 90 s）"""
    import time

    from analysis.mbd.dae.run import run_model

    t0 = time.time()
    d, _ = run_model(beam_chain(50, end=0.1, steps=100))
    assert time.time() - t0 < 90
    assert d["solver"]["jacobians"] < 40 and all(v["status"] != "fail" for v in d["verification"])
