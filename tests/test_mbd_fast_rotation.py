"""高速转动的自由刚体：积分每段转角受限，能量不再悄悄流失；能量核查不通过时提示结果不可信。

《多体动力学》书第 7 章线索第 16 条（问渠 CAD 0.3.8 细则）。主惯量 (2, 3, 4) g·m²、1 kg，无重力，初始构件系角速度
10·(10⁻³, 1, 10⁻³) rad/s（绕中间轴，Dzhanibekov 翻转），100 s。原来积分固定分 50 段（每段转 20 rad），缺省容差下报
“积分失败”或能量从 0.32 s 起流失，100 s 末能量只剩 5e-7、只翻转 1 次，结果仍标“完成”。翻转精确时刻来自书第 7 章（椭圆函数）。
"""
import numpy as np

from analysis.mbd.dae.run import run_model

IV = (0.002, 0.003, 0.004)
W0_DEG = list(np.degrees(10.0 * np.array([1e-3, 1.0, 1e-3])))
FLIPS = [2.5545150667159477, 7.164965239626054, 11.775415412560044, 16.385865585514566, 20.996315758483437,
         25.60676593146047, 30.217216104439483, 34.827666277414295, 39.4381164503787, 44.04856662332653]


def _A(p):
    e0, e1, e2, e3 = p / np.linalg.norm(p)
    return np.array([[e0 * e0 + e1 * e1 - e2 * e2 - e3 * e3, 2 * (e1 * e2 - e0 * e3), 2 * (e1 * e3 + e0 * e2)],
                     [2 * (e1 * e2 + e0 * e3), e0 * e0 - e1 * e1 + e2 * e2 - e3 * e3, 2 * (e2 * e3 - e0 * e1)],
                     [2 * (e1 * e3 - e0 * e2), 2 * (e2 * e3 + e0 * e1), e0 * e0 - e1 * e1 - e2 * e2 + e3 * e3]])


def test_dzhanibekov_100s_default_tolerance():
    m = {"format": "mbd-model/1", "name": "自由刚体（Dzhanibekov）", "gravity_mm_s2": [0, 0, 0],
         "bodies": [{"id": "b", "mass_kg": 1.0, "cm_mm": [0, 0, 0], "inertia_kg_m2": {"ixx": IV[0], "iyy": IV[1], "izz": IV[2]},
                     "w0_deg_s": W0_DEG}],
         "joints": [], "analysis": {"type": "dynamic", "end_time_s": 100.0, "output_steps": 10000}}
    d, msgs = run_model(m)
    t = np.array(d["times_s"])
    ps = np.array(d["bodies"]["b"]["euler_parameters"], float)
    wg = np.radians(np.array(d["bodies"]["b"]["w_deg_s"], float))
    wb = np.array([_A(p).T @ w for p, w in zip(ps, wg, strict=True)])
    E = 0.5 * np.einsum("ij,j,ij->i", wb, np.array(IV), wb)
    assert np.max(np.abs(E / E[0] - 1)) <= 1e-6               # 原来末了只剩 5e-7 的能量
    w2 = wb[:, 1]
    idx = np.where(np.sign(w2[1:]) * np.sign(w2[:-1]) < 0)[0]
    fl = [t[i] - w2[i] * (t[i + 1] - t[i]) / (w2[i + 1] - w2[i]) for i in idx]
    assert len(fl) == 22                                        # 原来 1 次
    assert max(abs(a - b) for a, b in zip(fl[:10], FLIPS, strict=True)) <= 1e-4
    assert next(v for v in d["verification"] if v["key"] == "energy_drift")["status"] == "pass"
    assert not any("能量核查不通过" in x for x in msgs)


def test_energy_failure_is_reported():
    # 很松的容差：能量核查不通过时提示结果不可信
    m = {"format": "mbd-model/1", "name": "摆", "gravity_mm_s2": [0, -9810, 0],
         "bodies": [{"id": "b", "mass_kg": 1.0, "cm_mm": [1000, 0, 0], "inertia_kg_m2": {"ixx": 1e-4, "iyy": 1e-4, "izz": 1e-4}}],
         "joints": [{"id": "O", "type": "revolute", "body_i": "ground", "body_j": "b", "point_mm": [0, 0, 0], "axis": [0, 0, 1]}],
         "analysis": {"type": "dynamic", "end_time_s": 5.0, "output_steps": 50, "rtol": 1e-3, "atol": 1e-3}}
    d, msgs = run_model(m)
    assert next(v for v in d["verification"] if v["key"] == "energy_drift")["status"] == "fail"
    assert any("能量核查不通过" in x for x in msgs)
