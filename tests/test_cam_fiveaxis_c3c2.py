"""问渠CAM C3c-2 非 RTCP 五轴联动（ADR-0106 C3c）：机床没开刀尖跟随时程序写机床各轴位置（按刀长、工件零点逐点逆解，刀尖走弯超过 0.01 mm 插点），
回读按正解换回工件坐标与刀位一致。机床用示例 AC 复制一台、关掉刀尖跟随（用户机床文件夹）。"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from analysis import cam
from analysis.cam import fiveaxis as FA
from analysis.cam import machines, postproc, sim
from tests.test_cam_fiveaxis_c3a import _prog
from tests.verification import record_verdict

OFF, L = [0.0, 0.0, 100.0], 120.0


@pytest.fixture()
def nr_machine(tmp_path, monkeypatch):
    monkeypatch.setenv("FAP_MACHINES_DIR", str(tmp_path))
    m = machines.copy_model("EX-5AX-AC", "MY-5AX-NR", "老五轴（没开刀尖跟随）")
    m["features"] = {"rtcp": False, "tilted_plane": True}
    machines.save_model(m)
    return "MY-5AX-NR"


def _setup(mid, ctl, prog, msim=True):
    st = {"mode": "program", "machine": mid, "program": prog, "stock": {"box": [-90, -90, 90, 90], "height": 30}, "post": ctl}
    if msim:
        st["machine_sim"] = {"work_offset_mm": OFF, "tools": {"1": {"tool": "EM10", "length_mm": L}}}
    return st


def _on_arc(q):
    ang = math.degrees(math.atan2(q[1], q[0]))
    return np.linalg.norm(np.asarray(q)[:2]) > 70 and 0.5 < ang < 89.5


def _seg_dist(p, a, b):
    d = b - a
    t = 0.0 if float(d @ d) < 1e-18 else min(1.0, max(0.0, float((p - a) @ d) / float(d @ d)))
    return float(np.linalg.norm(p - (a + t * d)))


@pytest.mark.parametrize("ctl", ["fanuc", "siemens", "heidenhain"])
def test_nonrtcp_release_and_readback(nr_machine, ctl):
    """锥面侧刃一圈（C 每段转 3°）：程序写机床 X Y Z A C、没有 G43.4 / TRAORI / TCPM，程序头写刀长和工件零点；
    回读按正解换回工件坐标：每个刀位都在回读刀路上（< 0.01 mm），回读刀路上每一点离刀位折线 ≤ 0.011 mm（弦差 0.01 插过点）"""
    prog, tips, axes = _prog(a1=90.0, n=30)
    r = cam.run(_setup(nr_machine, ctl, prog))
    assert r["status"] == "ok", r["messages"]
    p = r["data"]["programs"][0]
    assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
    t = p["release"]["text"]
    assert "G43.4" not in t and "TRAORI" not in t and "TCPM" not in t
    assert "NON-RTCP T1 L120.000 WORK ZERO X0 Y0 Z100" in t
    mach = {**machines.get(nr_machine), "nonrtcp": {1: {"L": L, "off": OFF}}}
    back = sim.parse(postproc.to_fanuc(t, ctl, False), mach)
    fm = [m for m in back["moves"] if m["t"] == "feed"]
    pts = np.array([m["b"] for m in fm])
    for tp in tips:
        assert float(np.min(np.linalg.norm(pts - tp, axis=1))) < 0.01
    poly = np.vstack([tips])
    worst = max(min(_seg_dist(np.asarray(q), poly[i], poly[i + 1]) for i in range(len(poly) - 1))
                for q in pts if _on_arc(q))                                          # 锥面上那几段（径向切入、切出不算）
    assert worst <= 0.011
    for m in fm:
        if _on_arc(m["b"]):
            k = int(np.argmin(np.linalg.norm(tips - np.asarray(m["b"]), axis=1)))
            assert FA.angle_deg(m["axis_b"], axes[k]) < 3.01                          # 刀轴在相邻两个刀位之间
    record_verdict((f"五轴联动：非 RTCP {ctl} 程序回读与刀位一致（弦差 0.01）", f"5-axis: non-RTCP {ctl} program reads back to the tool positions (chord 0.01)"),
                   "pass", "pass")


def test_nonrtcp_needs_length_and_offset(nr_machine):
    prog, _t, _a = _prog(a1=30.0, n=10)
    r = cam.run(_setup(nr_machine, "fanuc", prog, msim=False))
    assert r["status"] != "ok" and any("length_mm" in m for m in r["messages"])


def test_chord_subdivision_inserts_points():
    """刀轴一段转 20°（A −15 → 绕 C 转 20°）时机床直线插补刀尖走弯：插点后中点偏差 ≤ 0.01"""
    model = machines.get("EX-5AX-AC")["model"]
    w0 = [math.sin(math.radians(15)), 0.0, math.cos(math.radians(15))]
    w1 = [math.sin(math.radians(15)) * math.cos(math.radians(20)), math.sin(math.radians(15)) * math.sin(math.radians(20)), math.cos(math.radians(15))]
    tips = [[80.0, 0.0, -10.0], [80 * math.cos(math.radians(20)), 80 * math.sin(math.radians(20)), -10.0]]
    rots = FA.rotary_path(model, [w0, w1])
    pts = FA.machine_points(model, tips, [w0, w1], rots, L, OFF)
    assert len(pts) > 2
    from analysis.cam import kinematics as K

    for (qa, *_), (qb, *_) in itertools.pairwise(pts):
        qm = {k: 0.5 * (qa[k] + qb[k]) for k in qa}
        tm = K.forward(model, qm, L)[0] - OFF
        ta, tb = K.forward(model, qa, L)[0] - OFF, K.forward(model, qb, L)[0] - OFF
        assert np.linalg.norm(tm - 0.5 * (ta + tb)) <= 0.01 + 1e-9
