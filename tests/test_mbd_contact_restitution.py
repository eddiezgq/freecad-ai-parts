"""接触按恢复系数算阻尼：各速度、质量下实际恢复系数一致，弹跳球能停住。

《多体动力学》书第 21 章线索第 31 条（问渠 CAD 0.3.8 细则，ADR-0130）。钢球 R 10 mm（K 1.538e10 N/m^1.5、指数 1.5）落钢板：
原来常值阻尼（0.1 m 落下 e = 0.8 的那个值）在 0.01 m/s 时 e = 0.998、10 m/s 时 0.842，1 kg 撞 1 kg 时 0.948；
弹跳球过了 Zeno 时刻 1.285 s 还在跳。
"""
import math

import numpy as np
import pytest

from analysis.mbd.dae.run import run_model

R = 10.0
K = 1.538e10 * 1e-3 ** 1.5                     # N/mm^1.5
MB = 7850 * 4 / 3 * math.pi * 0.01 ** 3


def _ball(bid, m, z, vz=0.0, x=0.0):
    i = 0.4 * m * 1e-4
    b = {"id": bid, "mass_kg": m, "cm_mm": [x, 0, z], "inertia_kg_m2": {"ixx": i, "iyy": i, "izz": i}}
    if vz:
        b["v0_mm_s"] = [0, 0, vz]
    return b


def _contact(gi, gj):
    return {"id": f"c_{gj}", "geometry_i": gi, "geometry_j": gj, "stiffness_n_per_mm": K, "exponent": 1.5, "restitution": 0.8}


FLOOR = {"id": "floor", "body": "ground", "type": "plane", "point_mm": [0, 0, 0], "normal": [0, 0, 1]}


def _floor_e(v, m=MB):
    gap = 0.2
    mod = {"format": "mbd-model/1", "name": "落球", "gravity_mm_s2": [0, 0, 0], "bodies": [_ball("b", m, R + gap, -v * 1000)],
           "geometries": [FLOOR, {"id": "s", "body": "b", "type": "sphere", "center_mm": [0, 0, R + gap], "radius_mm": R}],
           "contacts": [_contact("floor", "s")],
           "analysis": {"type": "dynamic", "end_time_s": gap / (v * 1000) + 0.01, "output_steps": 50, "rtol": 1e-10, "atol": 1e-12}}
    d, _ = run_model(mod)
    return d["bodies"]["b"]["v_mm_s"][-1][2] / (v * 1000)


@pytest.mark.parametrize("v", [0.01, 0.1, 1.0, 10.0])
def test_restitution_independent_of_speed(v):
    assert _floor_e(v) == pytest.approx(0.8, abs=0.005)            # 原来 0.998 … 0.842


@pytest.mark.parametrize("m2", [1.0, 2.0])
def test_two_bodies(m2):
    # 1 kg 球以 1 m/s 撞静止的 1 kg / 2 kg 球（无重力）：分离速度 / 接近速度 = 0.8（原来 1 kg 撞 1 kg 时 0.948）
    gap = 0.2
    mod = {"format": "mbd-model/1", "name": "两球", "gravity_mm_s2": [0, 0, 0],
           "bodies": [_ball("a", 1.0, 0.0, 0.0), _ball("b", m2, 2 * R + gap)],
           "geometries": [{"id": "sa", "body": "a", "type": "sphere", "center_mm": [0, 0, 0], "radius_mm": R},
                          {"id": "sb", "body": "b", "type": "sphere", "center_mm": [0, 0, 2 * R + gap], "radius_mm": R}],
           "contacts": [_contact("sa", "sb")],
           "analysis": {"type": "dynamic", "end_time_s": 0.01, "output_steps": 20, "rtol": 1e-10, "atol": 1e-12}}
    mod["bodies"][0]["v0_mm_s"] = [0, 0, 1000.0]
    d, _ = run_model(mod)
    va, vb = d["bodies"]["a"]["v_mm_s"][-1][2], d["bodies"]["b"]["v_mm_s"][-1][2]
    assert (vb - va) / 1000.0 == pytest.approx(0.8, abs=0.005)


def test_bouncing_ball_comes_to_rest():
    # 0.1 m 落下、e = 0.8：Zeno 时刻 t∞ = √(2h/g)·(1 + e)/(1 − e) ≈ 1.285 s；t∞ + 0.01 s 后应已停住
    h, g = 100.0, 9810.0
    t_inf = math.sqrt(2 * h / g) * 1.8 / 0.2
    mod = {"format": "mbd-model/1", "name": "弹跳球", "gravity_mm_s2": [0, 0, -g], "bodies": [_ball("b", MB, R + h)],
           "geometries": [FLOOR, {"id": "s", "body": "b", "type": "sphere", "center_mm": [0, 0, R + h], "radius_mm": R}],
           "contacts": [_contact("floor", "s")],
           "analysis": {"type": "dynamic", "end_time_s": t_inf + 0.05, "output_steps": 400}}
    d, _ = run_model(mod)
    t = np.asarray(d["times_s"])
    z = np.asarray(d["bodies"]["b"]["cm_mm"])[:, 2]
    after = t >= t_inf + 0.01
    assert np.max(z[after]) - R < 0.01                       # 原来 2 s 时还弹起约 0.27 mm
