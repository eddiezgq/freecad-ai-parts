"""问渠CAM C3c-1 刀轴控制（ADR-0106 C3c）：奇异点让开、之字形固定方向前倾、刀杆刀柄碰零件时自动加大倾角。"""

from __future__ import annotations

import math

import numpy as np

from analysis import cam
from analysis.cam import dexel as DX
from analysis.cam import fiveaxis as FA
from analysis.cam import machines, post, sim
from tests.verification import record_verdict

RS, RB = 60.0, 3.0
AC = machines.get("EX-5AX-AC")


def _rows(cap, nrow=9, npt=31):
    rows = []
    for phi in np.radians(np.linspace(-cap / 2, cap / 2, nrow)):
        pts, nrm = [], []
        for th in np.radians(np.linspace(-cap / 2, cap / 2, npt)):
            n = np.array([math.sin(th) * math.cos(phi), math.sin(phi), math.cos(th) * math.cos(phi)])
            pts.append(np.array([0, 0, -RS]) + RS * n)
            nrm.append(n)
        rows.append((np.array(pts), np.array(nrm)))
    return rows


def _run(segs, link="lift", box=30):
    mv = FA.link_moves(segs, 800.0, link=link, clear_z=5.0)
    prog = {"number": 7301, "title": "球冠", "ops": [{"tool": {"n": 2, "d": 2 * RB, "kind": "ballend"}, "spindle": {"rpm": 8000},
                                                   "safe": 10.0, "title": "球冠多轴精加工", "simul5": True, "moves": mv}]}
    st = {"mode": "program", "machine": "EX-5AX-AC", "program": prog, "stock": {"box": [-box, -box, box, box], "height": 20}, "post": "fanuc",
          "machine_sim": {"work_offset_mm": [0, 0, 100], "tools": {"2": {"tool": "BN6", "length_mm": 110}}}}
    r = cam.run(st)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"][0], prog


def _no_overcut(prog, half):
    parsed = sim.parse(post.post_mill(prog, AC), AC)
    dx = DX.Dexel.box([-30, -30, -20], [30, 30, 0], 0.25, pad=8)
    DX.simulate(parsed, dx, {2: {"kind": "ballend", "d": 2 * RB}})
    worst = 0.0
    for i in range(0, len(dx.c[0]), 4):
        for j in range(0, len(dx.c[1]), 4):
            x, y = dx.c[0][i], dx.c[1][j]
            if abs(x) > RS * math.sin(math.radians(half)) or abs(y) > RS * math.sin(math.radians(half)):
                continue
            e = dx.E[2][i, j]
            top = float(np.nanmax(e)) if np.isfinite(e).any() else -1e9
            worst = max(worst, (-RS + math.sqrt(RS * RS - x * x - y * y)) - top)
    return worst


def test_pole_is_c_axis():
    assert np.allclose(FA.pole(AC["model"]), [0, 0, 1]) and np.allclose(FA.pole(machines.get("EX-5AX-BC")["model"]), [0, 0, 1])


def test_near_pole_branch_choice_and_avoidance():
    """C3b 记的那个：球冠离顶 ±20°、前倾 10°。原来一步甩 180° 的真正原因是起步挑错了一组解（A 走到 +30° 行程头只好换组）；
    现在每段起步整段看过再挑，不甩了，出程序，只剩“离 C 轴 0.67°（奇异点附近）”的提示。
    再让开奇异点（离 C 轴至少 3°）：提示没了，C 在那一段里慢慢转过去，出程序，dexel 不过切"""
    rows = _rows(20.0 * 2)
    raw = [FA.ball_surface(p, n, RB, 10.0, 0.0) for p, n in rows]
    p0, _ = _run(raw)
    assert p0["release"] is not None and not any("一步转了" in c["text"] for c in p0["checks"])
    assert any("奇异点附近" in c["text"] for c in p0["checks"])
    fixed = []
    for t, a in raw:
        na, _runs = FA.avoid_pole(a, FA.pole(AC["model"]), 3.0)
        assert min(FA.angle_deg(x, [0, 0, 1]) for x in na) >= 3.0 - 1e-9
        fixed.append((FA.ball_reaxis(t, a, na, RB), na))
    p1, prog = _run(fixed)
    assert p1["release"] is not None, [c["text"] for c in p1["checks"] if c["level"] == "error"]
    assert not any("一步转了" in c["text"] or "奇异点附近" in c["text"] for c in p1["checks"])
    assert _no_overcut(prog, 19.0) < 0.25 + 1e-6
    record_verdict(("五轴联动：起步挑对解、让开奇异点后不突变、不过切", "5-axis: branch choice and pole avoidance, no flip, no overcut"), "pass", "pass")


def test_zigzag_with_fixed_lead_direction():
    """之字形 + 固定方向前倾（往 +X 倒 15°）：来回走刀轴不变向，直连换行也不突变，出程序"""
    rows = FA.zigzag(_rows(20.0))
    segs = [FA.ball_surface(p, n, RB, 15.0, 0.0, lead_dir=[1.0, 0.0, 0.0]) for p, n in rows]
    for t, a in segs:
        assert all(x[0] > 0 for x in a)                                        # 都往 +X 倒
    p, prog = _run(segs, link="direct")
    assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
    assert _no_overcut(prog, 9.0) < 0.25 + 1e-6


def _pocket_dist(W=26.0, top=30.0):
    """方腔四壁（|x|、|y| ≥ W，高到 Z top）与球面（球心 (0,0,−RS)）的距离"""
    def d(P):
        P = np.atleast_2d(P)
        out = np.abs(np.linalg.norm(P - [0, 0, -RS], axis=1) - RS)
        dz = np.maximum(0.0, P[:, 2] - top)
        for k in (0, 1):
            dx = W - np.abs(P[:, k])
            out = np.minimum(out, np.hypot(np.maximum(dx, 0.0), dz))
        return out
    return d


def test_holder_hits_wall_and_tilts_away():
    """方腔（壁在 ±28、高到 Z30）底的球冠：竖着的刀柄（Ø20，离球心 40–90）在球冠边上碰壁；按碰撞加大倾角后刀杆、刀柄离壁都 ≥ 1 mm，
    倾角相邻点差不超过 2°，出程序"""
    parts = [(12.0, 40.0, 3.0), (40.0, 90.0, 10.0)]
    dist = _pocket_dist(W=28.0)
    rows = _rows(40.0, nrow=7, npt=21)
    segs, any_hit = [], False
    for p, n in rows:
        t, a = FA.ball_surface(p, n, RB, 0.0, 0.0)
        r = FA.avoid_collision(t, a, RB, parts, dist, clearance=1.0)
        assert not r["issues"]
        any_hit |= bool(np.any(r["tilt"] > 0))
        C = r["tips"] + RB * r["axes"]
        assert all(FA.shank_clear(C[k], r["axes"][k], parts, dist, 1.0) >= -1e-6 for k in range(len(C)))
        assert max(abs(x - y) for x, y in zip(r["tilt"], r["tilt"][1:])) <= 2.0 + 1e-9
        na, _ = FA.avoid_pole(r["axes"], [0, 0, 1], 5.0)               # 点距 2°：离极轴 5° 以上 C 每步转不到 30°
        segs.append((FA.ball_reaxis(r["tips"], r["axes"], na, RB), na))
    assert any_hit
    p, _prog = _run(segs)
    assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
    record_verdict(("五轴联动：刀柄碰壁时自动加大倾角、留够间隙", "5-axis: holder hitting a wall tilts away with clearance"), "pass", "pass")


def test_tilt_limit_reported():
    """壁太近（±12）、刀柄太粗：倒到 45° 还碰，报错"""
    parts = [(12.0, 40.0, 3.0), (40.0, 90.0, 20.0)]
    t, a = FA.ball_surface(*_rows(20.0, nrow=1, npt=5)[0], RB)
    r = FA.avoid_collision(t, a, RB, parts, _pocket_dist(W=12.0), max_tilt=45.0)
    assert r["issues"] and "倒到 45°" in r["issues"][0]["text"]
