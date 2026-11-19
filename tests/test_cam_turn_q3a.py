"""问渠CAM Q3a 车削刀路（ADR-0106）：余量与分层、高度与进退刀；内孔仿形、端面槽、切断、内螺纹、锥螺纹、多头螺纹、固定循环。"""

import itertools
import math

import numpy as np
import pytest

from analysis import cam
from analysis.cam import machines
from analysis.cam import paths as P
from analysis.cam import sim as S
from tests.verification import record

LATHE = machines.get("EX-LATHE")
BASE = {"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60]], "chamfer_mm": 1}


def _moves(prog, title):
    return next(o for o in prog["ops"] if o["title"] == title)["moves"]


def test_clearance_retract_and_allowance_reach_the_path():
    """工序参数：安全距离 5、退刀 1、径向余量 0.8 → 快移到 Z5；粗车每层斜退 1；粗车最后一刀离成品 0.8"""
    ctx = cam.turn_context(BASE, LATHE)
    sc = ctx["sides"][1]                                   # 调头车 Ø30 段：毛坯 Ø44，要分层
    c = {**cam.turn_default_cut(BASE, sc, {"kind": "rough"}), "clear": 5.0, "retract": 1.0, "allow_r": 0.8}
    mv = cam.turn_build_op(ctx, sc, {"kind": "rough"}, c)["op"]["moves"]
    zs = [m["z"] for m in mv if m["t"] == "rapid"]
    assert max(zs) == pytest.approx(5.0)
    feeds = [m for m in mv if m["t"] == "feed"]
    assert any(abs(b["x"] - a["x"] - 2.0) < 1e-9 and abs(b["z"] - a["z"] - 1.0) < 1e-9 for a, b in itertools.pairwise(feeds))
    # 沿留余量轮廓的那一刀：Ø30 段车到 Ø31.6
    assert any(m["t"] == "feed" and m["x"] == pytest.approx(31.6) for m in mv)
    # 缺省时与以前一样
    c0 = cam.turn_default_cut(BASE, sc, {"kind": "rough"})
    mv0 = cam.turn_build_op(ctx, sc, {"kind": "rough"}, c0)["op"]["moves"]
    assert max(m["z"] for m in mv0 if m["t"] == "rapid") == pytest.approx(P.CLEAR)


def _run(setup):
    r = cam.run(setup)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"]


def _errors(p):
    return [c["text"] for c in p["checks"] if c["level"] == "error"]


def _threads(p):
    return [m for m in S.parse(p["gcode"], LATHE)["moves"] if m["t"] == "thread"]


D1 = 24 - P.ISO_D1 * 1.5                     # M24×1.5 内螺纹底孔（小径）


def test_internal_thread_reaches_major_diameter():
    """M24×1.5 内螺纹：底孔镗到 D1 = 22.376，从小径往外车到大径 24；最后一刀 X24；内孔与螺纹都不报错"""
    setup = {**BASE, "segments": [[40, 40], [50, 60]], "bore": {"segments": [[D1, 25]], "drill_d": 18},
             "threads": [{"z_start": 0, "z_end": -20, "d": 24, "pitch": 1.5, "internal": True}]}
    p = _run(setup)[0]
    assert not _errors(p), _errors(p)
    th = _threads(p)
    assert max(m["b"][0] for m in th) == pytest.approx(24.0) and min(m["b"][0] for m in th) > D1
    # 没有内孔：不能车内螺纹
    bad = {k: v for k, v in setup.items() if k != "bore"}
    r = cam.run(bad)
    assert r["status"] != "ok" and "没有内孔" in " ".join(r["messages"])


def test_taper_thread_follows_1_to_16():
    """锥螺纹 1:16（直径），右端大径 Ø24、往左变大：每一刀的终点直径 = 起点直径 + (z 起 − z 止)/16"""
    setup = {**BASE, "segments": [[30, 40], [26, 60]], "grooves": [{"z": -18, "width": 4, "d": 21}],
             "threads": [{"z_start": 0, "z_end": -16, "d": 24, "pitch": 1.814, "taper": 1 / 16}]}
    p = _run(setup)[0]
    th = _threads(p)
    for m in th:
        assert m["b"][0] - m["a"][0] == pytest.approx((m["a"][2] - m["b"][2]) / 16, abs=1e-3)
    assert not [e for e in _errors(p) if "螺纹" in e]


def test_two_start_thread_lead_and_time():
    """双头 M24×1.5（导程 3）：G32 的 F = 3，两个头的起刀点差一个螺距；车螺纹时间 = 刀数 × 头数 × L / (导程 × n)"""
    setup = {**BASE, "segments": [[30, 40], [24, 60]], "grooves": [{"z": -26, "width": 4, "d": 20}],
             "threads": [{"z_start": 0, "z_end": -24, "d": 24, "pitch": 1.5, "starts": 2}]}
    p = _run(setup)[0]
    th = _threads(p)
    assert {m["f"] for m in th} == {3.0}
    starts = sorted({round(m["a"][2], 6) for m in th})
    assert len(starts) == 2 and starts[1] - starts[0] == pytest.approx(1.5)
    n_pass = len(P.thread_infeeds(P.ISO_D3 * 1.5 / 2))
    assert len(th) == 2 * n_pass
    rpm = th[0]["rpm"]
    t = sum(S.move_time(m, LATHE, True) for m in th)
    hand = sum(60 * (m["a"][2] - m["b"][2]) / (3.0 * rpm) for m in th)       # 第二个头起刀点多一个螺距，那几刀长 1.5
    assert t == pytest.approx(hand, rel=1e-6)
    record(("双头螺纹车削时间", "two-start threading time"), t, hand, tol=1e-6, unit="s", formula="t = Σ L/(导程·n)")


FLANGE = {**BASE, "segments": [[30, 20], [60, 10]], "chamfer_mm": 0.5}


def test_face_groove_cut_to_size_and_removed_volume():
    """法兰右端面 Ø36 ~ Ø48、深 3 的端面槽（刀宽 3，分 3 刀）：仿真空腔正好盖住，不宽不深；去除体积 = π(R²−r²)·深"""
    setup = {**FLANGE, "segments": [[60, 10], [30, 20]], "face_grooves": [{"d_in": 36, "d_out": 48, "depth": 3, "tool_w": 3}]}
    p = _run(setup)[0]
    assert not [e for e in _errors(p) if "端面槽" in e], _errors(p)
    st = {k: float(v) for k, v in p["replay_in"]["stock"].items()}
    s = S.simulate_turn(S.parse(p["gcode"], LATHE), st, {int(k): v for k, v in p["replay_in"]["tools"].items()}, h=0.01)
    v = s["void"]
    zc = s["z"]
    zone = (zc <= 0) & (zc >= -3)
    vol = float(np.nansum(np.where(zone, np.pi * (v[:, 1] ** 2 - v[:, 0] ** 2), 0.0)) * 0.01)
    exact = math.pi * (24 ** 2 - 18 ** 2) * 3
    record(("端面槽去除体积", "face groove removed volume"), vol, exact, tol=0.01, unit="mm³", formula="V = π(R² − r²)·深 / π(R² − r²)·depth")
    assert vol == pytest.approx(exact, rel=0.01)
    # 刀宽 3、槽宽 6：两刀；刀宽比槽宽还大不能做
    mv = P.turn_face_groove(36, 48, 3, 0.05, 3)
    assert sum(1 for m in mv if m["t"] == "feed") == 3
    with pytest.raises(P.CamError):
        P.turn_face_groove(36, 40, 3, 0.05, 3)


def test_face_groove_too_shallow_is_reported():
    setup = {**FLANGE, "segments": [[60, 10], [30, 20]], "face_grooves": [{"d_in": 36, "d_out": 48, "depth": 3, "tool_w": 3}]}
    ctx = cam.turn_context(setup, LATHE)
    sc = ctx["sides"][0]
    b = cam.turn_build_op(ctx, sc, {"kind": "face_groove", "i": 0}, cam.turn_default_cut(setup, sc, {"kind": "face_groove", "i": 0}))
    mv = [dict(m, z=-2.5) if m["t"] == "feed" else m for m in b["op"]["moves"]]
    prog = {"number": 1, "title": "t", "header": {}, "ops": [{**b["op"], "moves": mv}]}
    from analysis.cam import post

    s = S.simulate_turn(S.parse(post.post(prog, LATHE), LATHE), {"d": 64, "z_right": 0, "z_left": -40}, b["tools"],
                        target=b["target"])
    assert any("端面槽没切到位" in i["text"] for i in s["issues"])


def test_parting_off():
    """棒料上车完切断：切断刀走到中心以下，零件掉下来；不切断（刀没到中心）要报"""
    setup = {**BASE, "segments": [[30, 40], [40, 20]], "parting": {"tool_w": 3}}
    progs = _run(setup)
    p = progs[0]
    assert "切断" in p["gcode"]
    assert not [e for e in _errors(p) if "切断" in e], _errors(p)
    ctx = cam.turn_context(setup, LATHE)
    sc = ctx["sides"][0]
    b = cam.turn_build_op(ctx, sc, {"kind": "part"}, cam.turn_default_cut(setup, sc, {"kind": "part"}))
    assert min(m["x"] for m in b["op"]["moves"] if m["t"] == "feed") < 0
    mv = [dict(m, x=6.0) if m["t"] == "feed" else m for m in b["op"]["moves"]]
    from analysis.cam import post

    prog = {"number": 1, "title": "t", "header": {}, "ops": [{**b["op"], "moves": mv}]}
    s = S.simulate_turn(S.parse(post.post(prog, LATHE), LATHE), {"d": 44, "z_right": 0, "z_left": -80}, b["tools"], target=b["target"])
    assert any("没切断" in i["text"] for i in s["issues"])
