"""重陀螺模型（《多体动力学》书第 3 章 ex3_3_wq 的参数：m = 1 kg、质心距支点 40 mm、I1 = 8e-4、I3 = 4e-4 kg·m²、自转 200 rad/s）"""
import math

import numpy as np

M, L, I1, I3, G, W3 = 1.0, 0.04, 8e-4, 4e-4, 9.81, 200.0


def _Rz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def _Rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def top_model(name, steps, integ="DOP853"):
    if name == "tilt30":
        th0 = math.radians(30.0)
        a, b, c = (I1 + M * L * L) * math.cos(th0), -I3 * W3, M * G * L
        Om = (-b - math.sqrt(b * b - 4 * a * c)) / (2 * a)
    else:
        th0 = math.radians(90.0)
        Om = M * G * L / (I3 * W3)
    A0 = _Rx(th0)
    r = A0 @ np.array([0, 0, L])
    J = A0 @ np.diag([I1, I1, I3]) @ A0.T
    wg = A0 @ np.array([0.0, Om * math.sin(th0), W3])
    return {"format": "mbd-model/1", "name": f"重陀螺 {name}", "gravity_mm_s2": [0, 0, -G * 1000],
            "bodies": [{"id": "top", "mass_kg": M, "cm_mm": (r * 1000).tolist(),
                        "inertia_kg_m2": {"ixx": J[0, 0], "iyy": J[1, 1], "izz": J[2, 2], "ixy": J[0, 1], "ixz": J[0, 2], "iyz": J[1, 2]},
                        "w0_deg_s": np.degrees(wg).tolist(), "v0_mm_s": (np.cross(wg, r) * 1000).tolist()}],
            "joints": [{"id": "tip", "type": "spherical", "body_i": "ground", "body_j": "top", "point_mm": [0, 0, 0]}],
            "analysis": {"type": "dynamic", "end_time_s": 1.0, "output_steps": steps, "integrator": integ}}
