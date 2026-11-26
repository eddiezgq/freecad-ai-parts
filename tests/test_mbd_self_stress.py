"""冗余反力：按全部约束的左零空间判每个运动副的反力是否唯一，报自平衡力系；衬套、弹簧力元的力输出。

《多体动力学》书第 19 章线索第 26 条（问渠 CAD 0.3.9 细则）：平行四边形（支点间距 100 mm、曲柄 80 mm 转到 60°、连杆 2 kg、
曲柄 1 端点 50 N 水平力、曲柄 1 转角驱动 "0"，平面机构按三维转动副建模）删 7 行，都在支点 O1–O3，曲柄—连杆铰 A1–A3
原来标“完整”；自平衡力系 (e, −2, 1) 正作用在 A1–A3。衬套力原来不输出。
"""
import math

import numpy as np
import pytest

from analysis.mbd.dae.run import run_model

D, L, TH = 100.0, 80.0, math.radians(60.0)
E = np.array([math.cos(TH), math.sin(TH)])
O = [np.array([k * D, 0.0]) for k in range(3)]
A = [o + L * E for o in O]
TINY = {"ixx": 1e-9, "iyy": 1e-9, "izz": 1e-9}


def _para():
    bodies = [{"id": f"c{k + 1}", "mass_kg": 1e-6, "cm_mm": [*((O[k] + A[k]) / 2).tolist(), 0.0], "inertia_kg_m2": TINY} for k in range(3)]
    bodies.append({"id": "cp", "mass_kg": 2.0, "cm_mm": [*A[1].tolist(), 0.0], "inertia_kg_m2": {"ixx": 0.01, "iyy": 0.01, "izz": 0.01}})
    joints = []
    for k in range(3):
        joints.append({"id": f"O{k + 1}", "type": "revolute", "body_i": "ground", "body_j": f"c{k + 1}",
                       "point_mm": [*O[k].tolist(), 0.0], "axis": [0, 0, 1]})
        joints.append({"id": f"A{k + 1}", "type": "revolute", "body_i": f"c{k + 1}", "body_j": "cp",
                       "point_mm": [*A[k].tolist(), 0.0], "axis": [0, 0, 1]})
    return {"format": "mbd-model/1", "name": "平行四边形", "gravity_mm_s2": [0, -9810, 0], "bodies": bodies, "joints": joints,
            "motions": [{"id": "m1", "joint": "O1", "dof": "rotation", "function": "0"}],
            "forces": [{"id": "P", "type": "force", "body": "cp", "point_mm": [*A[0].tolist(), 0.0], "frame": "ground", "fx_n": 50.0}],
            "analysis": {"type": "kinematic", "end_time_s": 0.01, "output_steps": 1}}


def test_parallelogram_coupler_hinges_not_unique():
    d, msgs = run_model(_para())
    for k in (1, 2, 3):
        assert d["joints"][f"A{k}"]["complete"] is False              # 原来标“完整”
    # 自平衡力系里有平面内的 (e, −2e, e)：A1–A3 作用在连杆上的力
    rows = [np.r_[[s[f"A{k}"]["force"][:2] for k in (1, 2, 3)]].ravel() for s in d["self_stress"] if all(f"A{k}" in s for k in (1, 2, 3))]
    target = np.r_[E, -2 * E, E]
    M = np.array(rows)
    coef = np.linalg.lstsq(M.T, target, rcond=None)[0]
    assert np.linalg.norm(M.T @ coef - target) < 1e-6 * np.linalg.norm(target)
    assert any("反力不唯一" in m for m in msgs)


def test_bushing_force_output_and_rigid_note():
    m = {"format": "mbd-model/1", "name": "摆加衬套", "gravity_mm_s2": [0, 0, -9810],
         "bodies": [{"id": "b", "mass_kg": 1.0, "cm_mm": [100, 0, 0], "inertia_kg_m2": {"ixx": 1e-3, "iyy": 1e-3, "izz": 1e-3}}],
         "joints": [], "forces": [{"id": "B1", "type": "bushing", "body_i": "ground", "body_j": "b", "point_mm": [100, 0, 0],
                                    "stiffness_n_per_mm": [1e3, 1e3, 1e3], "rot_stiffness_n_m_per_deg": [10, 10, 10]}],
         "analysis": {"type": "static", "end_time_s": 0.01, "output_steps": 1}}
    d, _ = run_model(m)
    fe = d["force_elements"]["B1"]
    assert fe["type"] == "bushing" and fe["on"] == "b"
    assert fe["force_n"][-1][2] == pytest.approx(9.81, rel=1e-3)        # 衬套托住 1 kg


def test_rigid_joint_with_bushing_noted():
    m = {"format": "mbd-model/1", "name": "门", "gravity_mm_s2": [0, 0, -9810],
         "bodies": [{"id": "door", "mass_kg": 10.0, "cm_mm": [300, 0, 500], "inertia_kg_m2": {"ixx": 1.0, "iyy": 1.0, "izz": 1.0}}],
         "joints": [{"id": "H1", "type": "revolute", "body_i": "ground", "body_j": "door", "point_mm": [0, 0, 0], "axis": [0, 0, 1]}],
         "motions": [{"id": "m1", "joint": "H1", "dof": "rotation", "function": "0"}],
         "forces": [{"id": "B2", "type": "bushing", "body_i": "ground", "body_j": "door", "point_mm": [0, 0, 1000],
                     "stiffness_n_per_mm": [2e4, 2e4, 2e4], "rot_stiffness_n_m_per_deg": [175, 175, 175]}],
         "analysis": {"type": "kinematic", "end_time_s": 0.01, "output_steps": 1}}
    d, msgs = run_model(m)
    assert any("刚性运动副" in x and "B2" in x for x in msgs)
    assert "B2" in d["force_elements"]
