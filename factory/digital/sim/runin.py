# -*- coding: utf-8 -*-
"""负载跑合台：仿真与实测对比（第 58 轮，实验 28）。教材对照：《机器人学》29.4 节（仿真与现实）、26.4 节（摩擦辨识）。

一台 WQ-CR5 在负载跑合台上带标准负载（钢块约 5 kg）做标准动作（cae/wqcr5.py 的 runin_ref：三段关节空间五次多项式，共 4.8 s），
驱动器按电流记下每个关节的力矩（100 Hz）。“实测”的力矩由仿真车间合成：

    τ_实测 = 刚体逆动力学（零件库的 WQ-CR5 + 标准负载，含转子惯量）+ f_c tanh(θ̇/0.01) + f_v θ̇ + 测量噪声

其中 f_c 是**这台机器人装的 6 台关节在关节测试台上测得的空载摩擦力矩**（仿真车间装整机时按规格先进先出记下，随整机标定的测量一起发出）；
没有记录的按测试台的名义值和 σ、由出厂编号确定地补上。f_v 是名义值的 0.6～1.6 倍（按出厂编号定；润滑脂、温度的影响，测试台不测）。
噪声 σ（示例）：大关节 0.1、中 0.08、小 0.02 N·m。
“仿真”的力矩就是零件库模型（名义摩擦）算出的同一段动作——问渠“运动与动力分析”用的是同一个模型。
辨识：τ_实测 − 刚体逆动力学 = f_c tanh(θ̇/0.01) + f_v θ̇，每个关节两个未知数，用 |θ̇| > 0.05 rad/s 的采样点做最小二乘（26.4 节）。
力矩裕量：均方根 ≤ 谐波减速器的额定力矩、峰值 ≤ 关节的力矩上限（电机峰值 × 减速比 × 效率与减速器重复峰值取小）为合格。
纯计算，确定性（同一出厂编号、同样的摩擦，结果一样）。"""
from __future__ import annotations

import math
import zlib

import numpy as np

from cae import wqcr5 as W

HZ = 100
NOISE = {"L": 0.1, "M": 0.08, "S": 0.02}                     # 力矩测量噪声 σ，N·m（示例）
FRIC_SIGMA = {"L": 0.15, "M": 0.10, "S": 0.08}               # 关节测试台空载摩擦力矩的 σ（与 plants/wenquest-robot.yaml 相同，测试核对）
VEL_MIN = 0.05                                               # 辨识只用 |θ̇| > 0.05 rad/s 的点
_MODEL = {}


def _seed(*parts):
    return zlib.crc32("|".join(str(x) for x in parts).encode())


def _rigid():
    """刚体逆动力学用的模型：零件库 WQ-CR5 + 标准负载，关掉摩擦（frictionloss、damping）与接触"""
    if "m" not in _MODEL:
        import mujoco
        xml = W.mjcf(friction=False).replace("<!--TOOL-->", W.runin_load_xml())
        m = mujoco.MjModel.from_xml_string(xml)
        m.opt.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_CONTACT) | int(mujoco.mjtDisableBit.mjDSBL_LIMIT)
        _MODEL.update(m=m, d=mujoco.MjData(m), mj=mujoco)
    return _MODEL["mj"], _MODEL["m"], _MODEL["d"]


def nominal_friction():
    fc = np.array([W.MODULES[s]["frictionloss"] for s in W.JOINT_MODULE])
    fv = np.array([W.MODULES[s]["damping"] for s in W.JOINT_MODULE])
    return fc, fv


def robot_friction(serial, friction_nm=None):
    """这台机器人的“真实”摩擦：库仑摩擦取关节测试台的实测（缺的按名义值和 σ 由出厂编号补），黏性摩擦为名义的 0.6～1.6 倍"""
    rng = np.random.default_rng(_seed("runin-fric", serial))
    fc0, fv0 = nominal_friction()
    fc = []
    for i, s in enumerate(W.JOINT_MODULE):
        given = friction_nm[i] if friction_nm is not None and i < len(friction_nm) else None
        g = rng.normal(fc0[i], FRIC_SIGMA[s])
        fc.append(float(given) if given is not None else float(max(0.0, g)))
    fv = fv0 * rng.uniform(0.6, 1.6, 6)                    # 黏性摩擦随润滑脂、温度变化大，关节测试台不测它
    return np.array(fc), fv


def _rigid_torque(q, qd, qdd):
    mj, m, d = _rigid()
    d.qpos[:6], d.qvel[:6], d.qacc[:6] = q, qd, qdd
    mj.mj_inverse(m, d)
    return d.qfrc_inverse[:6].copy()


def motion():
    """标准动作的采样（100 Hz）：t、θ、θ̇、θ̈"""
    n = int(round(W.runin_duration() * HZ)) + 1
    t = np.arange(n) / HZ
    Q, QD, QDD = zip(*(W.runin_ref(x) for x in t))
    return t, np.array(Q), np.array(QD), np.array(QDD)


def case(serial, friction_nm=None, detail=True):
    """一台机器人在负载跑合台上的标准动作：实测与仿真的力矩、各关节的峰值和均方根、辨识出的摩擦、力矩裕量"""
    t, Q, QD, QDD = motion()
    rigid = np.array([_rigid_torque(q, qd, qdd) for q, qd, qdd in zip(Q, QD, QDD)])
    fc, fv = robot_friction(serial, friction_nm)
    fc0, fv0 = nominal_friction()
    sgn = np.tanh(QD / 0.01)
    rng = np.random.default_rng(_seed("runin-noise", serial))
    noise = np.array([NOISE[s] for s in W.JOINT_MODULE])
    meas = rigid + sgn * fc + QD * fv + rng.normal(0, 1, rigid.shape) * noise
    sim = rigid + sgn * fc0 + QD * fv0
    rated = np.array([W.MODULES[s]["gear"][1] for s in W.JOINT_MODULE])
    limit = np.array(W.torque_limit())
    joints = []
    for i, nm in enumerate(W.JOINTS):
        use = np.abs(QD[:, i]) > VEL_MIN
        A = np.column_stack([sgn[use, i], QD[use, i]])
        x, *_ = np.linalg.lstsq(A, meas[use, i] - rigid[use, i], rcond=None)
        upd = rigid[:, i] + sgn[:, i] * x[0] + QD[:, i] * x[1]
        rms = float(np.sqrt(np.mean(meas[:, i] ** 2)))
        peak = float(np.max(np.abs(meas[:, i])))
        joints.append({"joint": nm, "module": W.MODULES[W.JOINT_MODULE[i]]["code"],
                       "peak_meas": round(peak, 3), "rms_meas": round(rms, 3),
                       "peak_sim": round(float(np.max(np.abs(sim[:, i]))), 3), "rms_sim": round(float(np.sqrt(np.mean(sim[:, i] ** 2))), 3),
                       "rms_diff": round(float(np.sqrt(np.mean((meas[:, i] - sim[:, i]) ** 2))), 4),
                       "rms_diff_updated": round(float(np.sqrt(np.mean((meas[:, i] - upd) ** 2))), 4),
                       "fc_nominal": float(fc0[i]), "fv_nominal": float(fv0[i]), "fc_bench": round(float(fc[i]), 4),
                       "fc_hat": round(float(x[0]), 4), "fv_hat": round(float(x[1]), 4), "noise_sigma": float(noise[i]),
                       "rated": float(rated[i]), "limit": round(float(limit[i]), 2),
                       "pass": bool(rms <= rated[i] and peak <= limit[i])})
    out = {"serial": serial, "hz": HZ, "duration_s": float(t[-1]), "load_kg": W.RUNIN_LOAD["mass"],
           "poses_deg": [list(p) for p in W.RUNIN_POSES_DEG], "seg_s": W.RUNIN_SEG_S, "dwell_s": W.RUNIN_DWELL_S,
           "joints": joints, "pass": all(j["pass"] for j in joints),
           "bench_known": friction_nm is not None and all(v is not None for v in (friction_nm or [])[:6])}
    if detail:
        k = 2                                                    # 网页曲线 50 Hz
        out["series"] = {"t": [round(float(x), 3) for x in t[::k]],
                         "meas": [[round(float(v), 3) for v in meas[::k, i]] for i in range(6)],
                         "sim": [[round(float(v), 3) for v in sim[::k, i]] for i in range(6)],
                         "qd": [[round(float(v), 4) for v in QD[::k, i]] for i in range(6)]}
        out["_truth"] = {"fc": [round(float(v), 4) for v in fc], "fv": [round(float(v), 4) for v in fv]}
    return out
