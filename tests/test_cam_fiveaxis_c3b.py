"""问渠CAM C3b 五轴联动刀路（ADR-0106 C3b）：球头刀曲面多轴精加工（前倾、侧倾）、沿曲线加工、刀位连成走刀；FreeCAD 面上取点。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from analysis import cam
from analysis.cam import dexel as DX
from analysis.cam import fiveaxis as FA
from analysis.cam import machines, post, sim
from tests.verification import record_verdict

RS, RB = 60.0, 3.0          # 球面半径、球头刀半径


def _sphere_rows(nrow=9, npt=31, cap=40.0):
    """球冠（球心 (0,0,−RS)、顶在 Z0）上沿 X 方向一行一行的接触点和外法向，取到离顶 cap 度"""
    rows = []
    for phi in np.radians(np.linspace(-cap / 2, cap / 2, nrow)):
        pts, nrm = [], []
        for th in np.radians(np.linspace(-cap / 2, cap / 2, npt)):
            n = np.array([math.sin(th) * math.cos(phi), math.sin(phi), math.cos(th) * math.cos(phi)])
            pts.append(np.array([0, 0, -RS]) + RS * n)
            nrm.append(n)
        rows.append((np.array(pts), np.array(nrm)))
    return rows


def test_tilt_axis_lead_and_tilt():
    n, f = [0, 0, 1], [1, 0, 0]
    assert np.allclose(FA.tilt_axis(n, f, 0, 0), [0, 0, 1])
    w = FA.tilt_axis(n, f, 10, 0)                                            # 前倾：往走刀方向 +X 倒
    assert FA.angle_deg(w, [0, 0, 1]) == pytest.approx(10) and w[0] > 0 and abs(w[1]) < 1e-12
    w = FA.tilt_axis(n, f, 0, 5)                                             # 侧倾：往左侧 n × t = +Y 倒
    assert FA.angle_deg(w, [0, 0, 1]) == pytest.approx(5) and w[1] > 0 and abs(w[0]) < 1e-12


@pytest.mark.parametrize("lead,tilt", [(0, 0), (10, 0), (15, 5)])
def test_ball_surface_keeps_contact(lead, tilt):
    """球头刀倒多少都一样：球心离球面球心 RS + RB（与球面相切于接触点），刀尖 = 球心 − RB·刀轴；误差 < 1e-9"""
    for pts, nrm in _sphere_rows():
        tips, axes = FA.ball_surface(pts, nrm, RB, lead, tilt)
        ctr = tips + RB * axes
        assert np.allclose(np.linalg.norm(ctr - [0, 0, -RS], axis=1), RS + RB, atol=1e-9)
        assert max(FA.angle_deg(a, n) for a, n in zip(axes, nrm)) == pytest.approx(math.hypot(lead, tilt) if not (lead and tilt)
                                                                                      else FA.angle_deg(axes[0], nrm[0]), abs=1e-6)
    record_verdict(("五轴联动：球头刀曲面精加工刀位与球面相切", "5-axis: ball-end surface finishing tool positions tangent to the sphere"),
                   "pass", "pass")


def test_sphere_cap_finish_dexel_no_overcut():
    """球冠精加工（离顶 ±10°、前倾 15°，刀轴离竖直的 C 轴至少 5°，不过奇异点）：AC 机床刀尖跟随程序算通、出程序；
    dexel 去料后球冠范围里没有一处比球面低一个网格以上（不过切）。擦过奇异点（前倾 10°、±20°）时 C 会突变，那是 C3c 的事"""
    rows = _sphere_rows(cap=20.0)                       # 单向走（之字形时前倾跟着走刀方向反过来，换行时刀轴要甩过竖直）
    segs = [FA.ball_surface(p, n, RB, 15.0, 0.0) for p, n in rows]
    mv = FA.link_moves(segs, 800.0, link="lift", clear_z=5.0)
    prog = {"number": 7201, "title": "球冠精加工", "ops": [{"tool": {"n": 2, "d": 2 * RB, "kind": "ballend"}, "spindle": {"rpm": 8000},
                                                       "safe": 10.0, "title": "球冠多轴精加工", "simul5": True, "moves": mv}]}
    st = {"mode": "program", "machine": "EX-5AX-AC", "program": prog, "stock": {"box": [-30, -30, 30, 30], "height": 20}, "post": "fanuc",
          "machine_sim": {"work_offset_mm": [0, 0, 100], "tools": {"2": {"tool": "BN6", "length_mm": 110}}}}
    r = cam.run(st)
    assert r["status"] == "ok", r["messages"]
    p = r["data"]["programs"][0]
    assert p["release"] is not None and "G43.4" in p["release"]["text"], [c["text"] for c in p["checks"]]
    mach = machines.get("EX-5AX-AC")
    parsed = sim.parse(post.post_mill(prog, mach), mach)
    dx = DX.Dexel.box([-30, -30, -20], [30, 30, 0], 0.25, pad=8)
    DX.simulate(parsed, dx, {2: {"kind": "ballend", "d": 2 * RB}})
    xs, ys = dx.c[0], dx.c[1]
    worst_over = 0.0
    for i in range(0, len(xs), 4):
        for j in range(0, len(ys), 4):
            x, y = xs[i], ys[j]
            if abs(x) > RS * math.sin(math.radians(9)) or abs(y) > RS * math.sin(math.radians(9)):
                continue
            zs = -RS + math.sqrt(RS * RS - x * x - y * y)
            e = dx.E[2][i, j]
            top = float(np.nanmax(e)) if np.isfinite(e).any() else -1e9
            worst_over = max(worst_over, zs - top)
    assert worst_over < 0.25 + 1e-6                                     # 不比球面低一个网格以上
    record_verdict(("五轴联动：球冠多轴精加工 dexel 不过切", "5-axis: sphere cap multi-axis finishing dexel no overcut"), "pass", "pass")


def test_curve_follow_axis_is_normal():
    th = np.radians(np.linspace(0, 90, 19))
    pts = np.c_[40 * np.cos(th), 40 * np.sin(th), np.full(len(th), 10.0)]          # 圆柱 R40 顶边
    nrm = np.c_[np.cos(th), np.sin(th), np.zeros(len(th))]                           # 圆柱面外法向
    tips, axes = FA.curve_follow(pts, nrm, depth=0.5)
    assert np.allclose(axes, nrm) and np.allclose(np.linalg.norm(tips[:, :2], axis=1), 39.5)


def test_link_moves_lift_and_direct():
    segs = [(np.array([[0, 0, 0], [10, 0, 0]], float), np.array([[0, 0, 1], [0, 0, 1]], float)),
            (np.array([[10, 2, 0], [0, 2, 0]], float), np.array([[0, 0, 1], [0, 0, 1]], float))]
    lift = FA.link_moves(segs, 500.0, safe_dist=5.0)
    assert [m["t"] for m in lift] == ["rapid", "feed", "feed", "rapid"] * 2 and lift[0]["z"] == 5.0
    direct = FA.link_moves(segs, 500.0, link="direct")
    assert [m["t"] for m in direct] == ["rapid", "feed", "feed", "feed", "feed", "rapid"]
