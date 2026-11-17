"""多体动力学 D6a（ADR-0097 补充十三）：柔性构件（浮动参考系 + Craig-Bampton 模态）的标准题。不联网、不调用 LLM。

参考值（Blevins《Formulas for Natural Frequency and Mode Shape》、材料力学）：
- 欧拉梁 ω = (βL)²√(EI/(ρAL⁴))：自由–自由 βL = 4.7300、7.8532；铰支–自由 3.9266、7.0686；悬臂 1.8751、4.6941
- 悬臂梁自重下端部挠度 qL⁴/(8EI)
"""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from analysis.mbd.dae import flex as FX
from analysis.mbd.dae import model as M
from analysis.mbd.dae import run as R

G = 9.81
E_AL, G_AL, RHO_AL = 70000.0, 26000.0, 2700.0          # MPa、MPa、kg/m³


def rod(L=500.0, d=10.0, elements=30, fim=6, E=E_AL, **kw):
    I = d ** 4 / 12
    return {"type": "beam", "from_mm": [0, 0, 0], "to_mm": [L, 0, 0], "y_axis": [0, 1, 0], "youngs_modulus_mpa": E,
            "shear_modulus_mpa": G_AL, "density_kg_m3": RHO_AL, "area_mm2": d * d, "iyy_mm4": I, "izz_mm4": I,
            "ixx_mm4": 0.1406 * d ** 4, "elements": elements, "fixed_interface_modes": fim, **kw}


def c_beam(L=500.0, d=10.0, E=E_AL):
    I = d ** 4 / 12
    return math.sqrt(E * 1e6 * I * 1e-12 / (RHO_AL * d * d * 1e-6 * (L / 1000) ** 4))


def model(bodies, joints, analysis_, gravity=(0, 0, 0), **extra):
    return {"format": "mbd-model/1", "name": "t", "bodies": bodies, "joints": joints, "analysis": analysis_,
            "gravity_mm_s2": list(gravity), **extra}


def pin(point=(0, 0, 0), axis=(0, 1, 0), j="rod", jid="pin", typ="revolute"):
    jt = {"id": jid, "type": typ, "body_i": "ground", "body_j": j, "point_mm": list(point)}
    if typ != "fixed" and typ != "spherical":
        jt["axis"] = list(axis)
    return jt


def test_free_free_beam_modes_and_mass_orthogonality():
    L, d = 0.5, 0.01
    A, I = d * d, d ** 4 / 12
    X, K, Mm, m, Jn = FX.beam_fe([0, 0, 0], [L, 0, 0], [0, 1, 0], E_AL * 1e6, G_AL * 1e6, RHO_AL, A, I, I, 0.1406 * d ** 4, 40)
    N = len(X)
    sh, w = FX.craig_bampton(Mm * 0 + K, Mm, list(range(6)) + list(range(6 * (N - 1), 6 * N)), 6)
    lam = np.sort(w) / c_beam()
    assert lam[:4] == pytest.approx([4.7300 ** 2] * 2 + [7.8532 ** 2] * 2, rel=3e-3)
    fx = FX.from_full(X, m, Jn, sh, w, (m @ X) / m.sum(), 0.0, [0, N - 1])
    assert np.abs(fx.Psi).max() < 1e-9 * np.abs(fx.Phit).max() * fx.mass       # 与平动刚体运动质量正交
    assert np.allclose(fx.Mff, np.eye(fx.nm), atol=1e-9)                          # 质量归一


def test_pinned_beam_linearization_gives_pinned_free_and_clamped_free_frequencies():
    data, _ = R.run_model(model([{"id": "rod", "flex": rod()}], [pin()], {"type": "linear"}))
    fs = sorted(m["frequency_hz"] * 2 * math.pi / c_beam() for m in data["linear"]["modes"])
    assert fs[0] < 1e-2                                               # 绕销的刚体转动
    # 绕 y 的铰支–自由弯曲（xz 平面）；xy 平面里转动副把它夹住了，是悬臂
    assert fs[1] == pytest.approx(1.8751 ** 2, rel=3e-3)
    assert fs[2] == pytest.approx(3.9266 ** 2, rel=3e-3)
    assert fs[3] == pytest.approx(4.6941 ** 2, rel=3e-3)
    assert fs[4] == pytest.approx(7.0686 ** 2, rel=3e-3)


def test_cantilever_tip_deflection_under_own_weight():
    L, d = 500.0, 10.0
    data, _ = R.run_model(model([{"id": "rod", "flex": rod(fim=10)}], [pin(typ="fixed")], {"type": "static"},
                                gravity=(0, 0, -G * 1000),
                                requests=[{"id": "tip", "type": "point", "body": "rod", "point_mm": [L, 0, 0]}]))
    q = RHO_AL * d * d * 1e-6 * G
    I = (d / 1000) ** 4 / 12
    ref = q * (L / 1000) ** 4 / (8 * E_AL * 1e6 * I) * 1000
    assert -data["requests"]["tip"]["pos_mm"][0][2] == pytest.approx(ref, rel=5e-3)


def test_flexible_pendulum_conserves_energy():
    data, _ = R.run_model(model([{"id": "rod", "flex": rod(d=4.0, elements=12, fim=4, keep_modes=4)}], [pin()],
                                {"type": "dynamic", "end_time_s": 0.3, "output_steps": 20, "rtol": 1e-8, "atol": 1e-11},
                                gravity=(0, 0, -G * 1000)))
    v = next(x for x in data["verification"] if x["key"] == "energy_drift")
    assert v["status"] == "pass" and v["value"] < 1e-7
    assert max(data["flex"]["rod"]["elastic_energy_j"]) > 1e-6                    # 真的有弹性变形参与
    assert next(x for x in data["verification"] if x["key"] == "dof")["status"] == "pass"


def test_stiff_flexible_pendulum_matches_rigid_pendulum():
    flex = model([{"id": "rod", "flex": rod(elements=10, fim=2, E=E_AL * 30, keep_modes=2)}], [pin()],
                 {"type": "dynamic", "end_time_s": 0.15, "output_steps": 6, "rtol": 1e-8, "atol": 1e-11},
                 gravity=(0, 0, -G * 1000))
    sysm = M.build(flex)
    b = sysm.bodies[0]
    rigid = copy.deepcopy(flex)
    J = b.J
    rigid["bodies"] = [{"id": "rod", "mass_kg": b.mass, "cm_mm": (b.r0 * 1000).tolist(),
                        "inertia_kg_m2": {"ixx": J[0, 0], "iyy": J[1, 1], "izz": J[2, 2]}}]
    a, _ = R.run_model(flex)
    r, _ = R.run_model(rigid)
    pa, pr = np.array(a["bodies"]["rod"]["cm_mm"]), np.array(r["bodies"]["rod"]["cm_mm"])
    assert np.max(np.abs(pa - pr)) < 1e-3 * 250                      # 摆过 0.15 s，质心位置差 < 0.1 % 摆长


def test_pinned_pinned_rod_needs_interface_modes():
    """两端铰支（一端转动副、一端球副）的杆：面内一阶 ω = π²√(EI/(ρAL⁴))。全部 Craig-Bampton 正交模态都留着才对；
    只留最低两阶（自由–自由弯曲）就少了界面柔性，频率偏高——所以 keep_modes 缺省是全部"""
    L = 500.0
    joints = [pin(axis=(0, 0, 1)), {"id": "end", "type": "spherical", "body_i": "ground", "body_j": "rod", "point_mm": [L, 0, 0]}]
    data, _ = R.run_model(model([{"id": "rod", "flex": rod(fim=6)}], joints, {"type": "linear"}))
    fs = sorted(m["frequency_hz"] * 2 * math.pi / c_beam() for m in data["linear"]["modes"])
    assert fs[0] == pytest.approx(math.pi ** 2, rel=3e-3)
    cut, _ = R.run_model(model([{"id": "rod", "flex": rod(fim=6, keep_modes=2)}], joints, {"type": "linear"}))
    low = min(m["frequency_hz"] for m in cut["linear"]["modes"]) * 2 * math.pi / c_beam()
    assert low > 1.005 * fs[0]                    # 模态截断是里兹法上界：少了界面柔性，频率偏高（这里约 1.4 %）


def test_flexible_slider_crank_power_balance():
    """曲柄 100 mm（刚体，匀速 300 r/min），连杆 300 mm 柔性（6 mm 方钢），滑块，没有阻尼：驱动做的功 = 动能 + 弹性能的增量。
    检的是带约束、带驱动时柔性构件的能量一致性（只留两阶模态，为了测试快；精度要全部模态，见补充十四）"""
    Lc, Lr, d = 100.0, 300.0, 6.0
    I = d ** 4 / 12
    sec = {"youngs_modulus_mpa": 2e5, "shear_modulus_mpa": 8e4, "area_mm2": d * d, "iyy_mm4": I, "izz_mm4": I,
           "ixx_mm4": 0.1406 * d ** 4}
    crank = {"id": "crank", "mass_kg": 0.2, "cm_mm": [Lc / 2, 0, 0], "inertia_kg_m2": {"ixx": 1e-5, "iyy": 2e-4, "izz": 2e-4}}
    slider = {"id": "slider", "mass_kg": 0.5, "cm_mm": [Lc + Lr, 0, 0], "inertia_kg_m2": {"ixx": 1e-4, "iyy": 1e-4, "izz": 1e-4}}
    joints = [pin(axis=(0, 0, 1), j="crank", jid="J1"),
              {"id": "J2", "type": "revolute", "body_i": "crank", "body_j": "rod", "point_mm": [Lc, 0, 0], "axis": [0, 0, 1]},
              {"id": "J3", "type": "spherical", "body_i": "rod", "body_j": "slider", "point_mm": [Lc + Lr, 0, 0]},
              {"id": "J4", "type": "translational", "body_i": "ground", "body_j": "slider", "point_mm": [Lc + Lr, 0, 0],
               "axis": [1, 0, 0]}]
    flexm = model([crank, {"id": "rod", "flex": {"type": "beam", "from_mm": [Lc, 0, 0], "to_mm": [Lc + Lr, 0, 0],
                                                 "y_axis": [0, 1, 0], "density_kg_m3": 7850, "elements": 20,
                                                 "fixed_interface_modes": 4, "keep_modes": 2, **sec}}, slider],
                  joints, {"type": "dynamic", "end_time_s": 0.1, "output_steps": 1000, "rtol": 1e-8, "atol": 1e-11},
                  motions=[{"id": "m", "joint": "J1", "dof": "rotation", "speed": 300}])
    data, _ = R.run_model(flexm)
    t = np.array(data["times_s"])
    work = np.trapezoid(np.array(data["motions"]["m"]["effort"]) * 300 * 2 * math.pi / 60, t)
    tot = np.array(data["energy"]["kinetic_j"]) + np.array(data["flex"]["rod"]["elastic_energy_j"])
    assert max(data["flex"]["rod"]["elastic_energy_j"]) > 1e-4                   # 连杆确实在振
    # 驱动力矩随连杆振动高频起伏：1000 点梯形积分对到 1 %（200 点差 14 %、2000 点差 0.1 %，在收敛）
    assert work == pytest.approx(tot[-1] - tot[0], rel=1e-2)


def test_force_on_flexible_body_is_refused():
    m = model([{"id": "rod", "flex": rod(elements=4, fim=1)}], [pin()], {"type": "dynamic"},
              forces=[{"id": "f", "type": "force", "body": "rod", "point_mm": [500, 0, 0], "fz_n": 1}])
    with pytest.raises(M.ModelError, match="柔性构件"):
        M.build(m)
    m = model([{"id": "rod", "flex": rod(elements=4, fim=1)}], [pin(point=(100, 0, 0))], {"type": "dynamic"})
    with pytest.raises(M.ModelError, match="界面节点"):
        M.build(m)
