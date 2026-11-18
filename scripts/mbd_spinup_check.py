"""旋转梁升速验证（ADR-0101 F2）：Kane、Ryan、Banerjee 1987 的经典题，单次要几分钟，不放进测试。

梁 L = 10 m，EI = 14000 N·m²，ρA = 1.2 kg/m，EA = 2.8e7 N；15 s 内转速按 Ωs/T[t − T/2π·sin(2πt/T)] 升到 6 rad/s，再匀速。
用法：python scripts/mbd_spinup_check.py 20 40 nl lin   （仿真时长 s、输出点数、nl = 大变形梁、lin = 线性模态柔性体）
环境变量：NE 单元数（缺省 10），RT 容差（缺省 1e-6）。输出旋转坐标系里梁端的横向挠度（m）。
"""

import math
import os
import sys
import time

import numpy as np

from analysis.mbd.dae.run import run_model

L, EI, RHOA, EA = 10.0, 14000.0, 1.2, 2.8e7
A_MM2 = 400.0
I_MM4 = EI / 7e10 * 1e12
RHO = RHOA / (A_MM2 * 1e-6)
WS, T = 6.0, 15.0
RT = float(os.environ.get("RT", "1e-6"))
# 转角（度）：t < T 时 Ωs/T [t²/2 + (T/2π)²(cos(2πt/T) − 1)]，之后 Ωs(t − T/2)
TH = (f"57.29577951308232*({WS}/{T}*(min(time,{T})^2/2 + ({T}/(2*pi))^2*(cos(2*pi*min(time,{T})/{T}) - 1))"
      f" + {WS}*(time - min(time,{T})))")


NE = int(os.environ.get("NE", "10"))


def model(kind, end, steps, ne=NE):
    beam = {"from_mm": [0, 0, 0], "to_mm": [L * 1000, 0, 0], "y_axis": [0, 1, 0], "youngs_modulus_mpa": 7e4,
            "shear_modulus_mpa": 2.6e4, "density_kg_m3": RHO, "area_mm2": A_MM2, "iyy_mm4": I_MM4, "izz_mm4": I_MM4,
            "ixx_mm4": 2 * I_MM4, "elements": ne}
    if kind == "nl":
        flex = {"type": "nonlinear_beam", **beam}
    else:
        flex = {"type": "beam", **beam, "fixed_interface_modes": 6}
    return {"format": "mbd-model/1", "name": "旋转梁升速", "gravity_mm_s2": [0, 0, 0],
            "bodies": [{"id": "hub", "mass_kg": 1.0, "cm_mm": [0, 0, 0], "inertia_kg_m2": {"ixx": 1.0, "iyy": 1.0, "izz": 1.0}},
                       {"id": "beam", "flex": flex}],
            "joints": [{"id": "axle", "type": "revolute", "body_i": "ground", "body_j": "hub", "point_mm": [0, 0, 0], "axis": [0, 0, 1]},
                       {"id": "clamp", "type": "fixed", "body_i": "hub", "body_j": "beam", "point_mm": [0, 0, 0]}],
            "motions": [{"id": "spin", "joint": "axle", "dof": "rotation", "function": TH}],
            "requests": [{"id": "tip", "type": "point", "body": "beam", "point_mm": [L * 1000, 0, 0]}],
            "analysis": {"type": "dynamic", "end_time_s": end, "output_steps": steps, "integrator": "HHT", "rtol": RT, "atol": RT * 1e-2}}


def theta(t):
    tt = min(t, T)
    return WS / T * (tt ** 2 / 2 + (T / (2 * math.pi)) ** 2 * (math.cos(2 * math.pi * tt / T) - 1)) + WS * (t - tt)


def deflection(d):
    p = np.array(d["requests"]["tip"]["pos_mm"]) / 1000
    th = np.array([theta(t) for t in d["times_s"]])
    return -np.sin(th) * p[:, 0] + np.cos(th) * p[:, 1]


if __name__ == "__main__":
    end, steps = float(sys.argv[1]), int(sys.argv[2])
    for kind in sys.argv[3:]:
        t0 = time.time()
        d, _ = run_model(model(kind, end, steps))
        v = deflection(d)
        print(kind, round(time.time() - t0, 1), d["solver"].get("steps"), "defl m:", np.round(v[:: max(1, steps // 20)], 4))
