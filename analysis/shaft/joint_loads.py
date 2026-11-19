"""关节输出轴的载荷：由机器人动力学算一个搬运节拍（ADR-0100 42.5 第 4 步，做法同《机械设计》33.10）。

机械臂用 `analysis.mbd` 的参数化串联臂（MuJoCo；底座竖直轴 j1，其后 j2、j3 绕水平轴，各杆沿 +X）。
一个节拍：姿态 A → B（梯形速度，加减速各占 25 %），停，B → A，停。记录：
  T(t)  j2 的驱动力矩（N·m）；F(t) 大臂（link1）从 j2 受到的力的大小（N，MuJoCo cfrc_int 换算，与书中 rf.upper_arm_link.abs 同）；
  W(t)  j2 的角速度（rad/s）。
结论：T_peak / T_min（一个节拍内驱动力矩绝对值的最大 / 最小）、F_peak、F_series、输出轴平均转速（含停顿）。

质量、长度全部由调用方给（需求原话里核对过的数）；不估。纯计算：不联网、不调用 AI。
"""

from __future__ import annotations

import math

import numpy as np

RPM = 60 / (2 * math.pi)


def _move(arm: dict, start: dict, target: dict, move_s: float, dwell_s: float, hz: float):
    from analysis import mbd
    from analysis.mbd import core

    spec, _ = mbd._spec({"kind": "arm", **arm})
    drives = [{"joint": j, "kind": "move", "to": target[j], "t0_s": 0.0, "t1_s": move_s, "accel_ratio": 0.25}
              for j in target] + [{"joint": "j1", "kind": "hold"}]
    setup = {"duration_s": move_s + dwell_s, "sample_hz": hz, "initial": start, "drives": drives}
    internal = mbd._internal(setup, mbd._slide_joints(spec))
    _, ch, _ = core.simulate(spec, internal)
    return ch


def cycle(arm: dict, pose_a: dict, pose_b: dict, move_s: float, dwell_s: float, hz: float = 200.0) -> dict:
    """arm：{"base_height_mm", "links": [{"length_mm", "mass_kg"}], "joint_masses_kg", "payload_kg"}；
    姿态：{"j2": 角度（度）, "j3": ...}。返回 {"t_s", "T_nm", "F_n", "W_rad_s"}（numpy 数组）"""
    a = _move(arm, pose_a, pose_b, move_s, dwell_s, hz)
    b = _move(arm, pose_b, pose_a, move_s, dwell_s, hz)
    t = np.concatenate([a["t"], b["t"] + a["t"][-1] + (a["t"][1] - a["t"][0])])
    return {"t_s": t, "T_nm": np.concatenate([a["drive.j2"], b["drive.j2"]]),
            "F_n": np.concatenate([a["rf.link1.abs"], b["rf.link1.abs"]]),
            "W_rad_s": np.concatenate([a["qd.j2"], b["qd.j2"]])}


def conditions(c: dict) -> dict:
    """一个节拍 → 输出轴校核用的载荷条件"""
    tabs = np.abs(c["T_nm"])
    f = np.abs(c["F_n"])
    return {"T_peak_nm": float(tabs.max()), "T_min_nm": float(tabs.min()), "T_rms_nm": float(np.sqrt(np.mean(c["T_nm"] ** 2))),
            "F_peak_n": float(f.max()), "F_series_n": [float(x) for x in f[:: max(1, len(f) // 400)]],
            "speed_avg_rpm": float(np.mean(np.abs(c["W_rad_s"]))) * RPM, "speed_max_rpm": float(np.max(np.abs(c["W_rad_s"]))) * RPM}
