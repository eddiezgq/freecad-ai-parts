"""MuJoCo 路线的闭环机构：软约束时间常数按转速选，报告闭环实际拉开。

《多体动力学》书第 17 章线索第 23 条（问渠 CAD 0.3.8 细则）。常用机构库四杆机构 C-LNK-4BAR（缺省参数）匀速驱动：
原来闭环 τ 固定 2 ms，600 rpm 闭合点拉开 1.10 mm，驱动力矩逐点最大误差为精确峰值的 12 %，状态 ok、无提示。
精确解用 DAE 内核（运动学分析 = 运动学 + 逆动力学，同样的钢杆质量、惯量）。
"""
import math

import numpy as np

import analysis
from analysis.common import materials
from analysis.mbd import mechanisms
from analysis.mbd.dae.run import run_model

RHO = materials.get("45-QT")["density_kg_m3"]


def _bar(bid, L, w, t, p0, ang):
    m = RHO * L * w * t
    c = (p0[0] + L / 2 * math.cos(ang), p0[1] + L / 2 * math.sin(ang))
    # 构件系：杆沿 x、宽 w 沿 z、厚 t 沿 y；装配角绕 −y 转
    Ixx, Iyy, Izz = m * (t * t + w * w) / 12, m * (L * L + w * w) / 12, m * (L * L + t * t) / 12
    ca, sa = math.cos(ang), math.sin(ang)
    R = np.array([[ca, 0, -sa], [0, 1, 0], [sa, 0, ca]])
    I = R @ np.diag([Ixx, Iyy, Izz]) @ R.T
    return {"id": bid, "mass_kg": m, "cm_mm": [c[0] * 1000, 0.0, c[1] * 1000],
            "inertia_kg_m2": {"ixx": I[0, 0], "iyy": I[1, 1], "izz": I[2, 2], "ixy": I[0, 1], "ixz": I[0, 2], "iyz": I[1, 2]}}


def _exact(rpm, T, steps):
    p = mechanisms.params("C-LNK-4BAR")
    a, b, c, d, w, t = (p[k] for k in ("crank_m", "coupler_m", "rocker_m", "ground_m", "link_width_m", "link_thickness_m"))
    A, B, th3, th4 = mechanisms.four_bar_solve(p, 0.0)
    ax = [0, -1, 0]
    m = {"format": "mbd-model/1", "name": "四杆", "gravity_mm_s2": [0, 0, -9810],
         "bodies": [_bar("crank", a, w, t, (0, 0), 0.0), _bar("coupler", b, w, t, A, th3), _bar("rocker", c, w, t, (d, 0), th4)],
         "joints": [{"id": "O", "type": "revolute", "body_i": "ground", "body_j": "crank", "point_mm": [0, 0, 0], "axis": ax},
                    {"id": "A", "type": "revolute", "body_i": "crank", "body_j": "coupler", "point_mm": [A[0] * 1000, 0, A[1] * 1000], "axis": ax},
                    {"id": "B", "type": "revolute", "body_i": "coupler", "body_j": "rocker", "point_mm": [B[0] * 1000, 0, B[1] * 1000], "axis": ax},
                    {"id": "D", "type": "revolute", "body_i": "ground", "body_j": "rocker", "point_mm": [d * 1000, 0, 0], "axis": ax}],
         "motions": [{"id": "mo", "joint": "O", "dof": "rotation", "function": f"{rpm * 6.0!r}*time"}],
         "analysis": {"type": "kinematic", "end_time_s": T, "output_steps": steps}}
    dd, _ = run_model(m)
    return np.asarray(dd["times_s"]), np.asarray(dd["motions"]["mo"]["effort"], float)


def _run(rpm, T):
    return analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-LNK-4BAR"}, "duration_s": T, "gravity": True,
                                "sample_hz": 8000, "drives": [{"joint": "crank", "kind": "speed", "value": rpm}]})


def _torque_err(res, rpm, T):
    """驱动力矩与精确解在同一曲柄转角上比（驱动是理想伺服，有零点几度的跟踪滞后，按时间比会把相位差算成误差）"""
    t = np.asarray(res["data"]["series"]["t_s"])
    th = np.radians(np.asarray(res["data"]["series"]["crank"]["q"], float))
    tau = np.asarray(res["data"]["series"]["crank"]["drive"], float)
    te, tx = _exact(rpm, T, 2500)
    ex = np.interp(th, 2 * math.pi * rpm / 60 * te, tx)
    sel = t > 0.03                                   # 去掉起步的过渡
    return float(np.max(np.abs(tau[sel] - ex[sel])) / np.max(np.abs(ex[sel])))


def test_four_bar_600rpm_torque_within_one_percent():
    res = _run(600, 0.25)
    assert res["status"] == "ok"
    assert _torque_err(res, 600, 0.25) <= 0.01
    loop = res["data"]["loop"]
    assert loop["max_gap_mm"] <= 0.05 and loop["tau_s"] < 0.002     # τ 按转速收紧（缺省 2 ms 时拉开 0.12 mm）
    assert any("软约束" in x for x in res["limitations"])


def test_fast_four_bar_gap_is_reported(monkeypatch):
    # 2400 rpm：闭环拉开 0.39 mm（最短构件 40 mm 的 0.1 % 是 0.04 mm），驱动力矩误差约 10 %——原来状态 ok、什么都不说。
    # 问渠 CAD 0.3.9（线索第 71 条）查出 0.3.8 选的步长 h 没有生效（core.simulate 把步长改回 0.2 ms，τ 被 MuJoCo 限在 2 步长），
    # 修好后 2400 rpm 只拉开 0.007 mm，见下一个测试；这里把 τ、步长固定回 0.3.8 实际用的值，核“拉开超限要报”这条路仍然有效
    monkeypatch.setattr(mechanisms, "loop_tau", lambda mid, given, w: (mechanisms.LOOP_TAU_MAX, mechanisms.DT_MAX))
    monkeypatch.setattr(mechanisms, "DAE_RATIO", 0.0)
    res = _run(2400, 0.06)
    loop = res["data"]["loop"]
    assert loop["max_gap_mm"] > loop["limit_mm"]
    assert any("闭环拉开" in m for m in res["messages"])


def test_fast_four_bar_step_honoured_and_torque_exact():
    # 线索第 71 条：步长按 τ 取（不再被改回 0.2 ms），闭环拉开在限内；2400 rpm 一转只有约束时间常数的 25 倍，驱动力矩改由 DAE 算
    res = _run(2400, 0.06)
    loop = res["data"]["loop"]
    assert loop["max_gap_mm"] <= loop["limit_mm"]
    assert res["data"]["timestep_s"] <= loop["tau_s"] / 2 + 1e-15
    assert res["data"]["force_solver"]["name"] == "DAE"
    assert _torque_err(res, 2400, 0.06) <= 0.01
