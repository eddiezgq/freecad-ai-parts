"""回放（ADR-0106 Q2 第 5 步）：帧与程序行对得上、时间与程序时间一致、事件落在撞的那一帧、在制毛坯与整段仿真一致。"""

import re

import numpy as np
import pytest

from analysis import cam
from analysis.cam import dexel as DX
from analysis.cam import machines
from analysis.cam import replay as R
from analysis.cam import sim as S

VMC = machines.get("EX-VMC")
LATHE = machines.get("EX-LATHE")
MILL = {"mode": "mill", "machine": "EX-VMC", "stock": {"box": [0, 0, 100, 60], "height": 40},
        "features": [{"type": "pocket", "rect": [20, 15, 80, 45], "corner_r": 6, "depth": 8, "tool_d": 10},
                     {"type": "holes", "points": [[10, 10], [90, 50]], "d": 8.5, "depth": 15}]}
MSIM = {"work_offset_mm": [0, 0, 40], "tools": {"1": {"tool": "EM10", "length_mm": 120}, "2": {"tool": "DR8.5", "length_mm": 140}}}


def _prog(setup):
    r = cam.run(setup)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"]


def _replay(p, mach):
    return R.Replay(p["gcode"], mach, p["replay_in"], p["checks"])


def _words(line):
    return {m[0]: float(m[1]) for m in re.findall(r"([XYZ])(-?\d+(?:\.\d+)?)", line.split("(")[0])}


@pytest.mark.parametrize("which", ["mill", "turn"])
def test_frames_match_program_lines_and_time(which):
    if which == "mill":
        p, mach = _prog({**MILL, "machine_sim": MSIM})[0], VMC
    else:
        p, mach = _prog({"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60]], "chamfer_mm": 1})[0], LATHE
    rp = _replay(p, mach)
    assert rp.duration == pytest.approx(p["time"]["total_s"], rel=1e-9)
    assert rp.frames and all(f["t1"] >= f["t0"] for f in rp.frames)
    # 每一帧的终点就是那一行写的坐标（这一行写了的轴）
    for f in rp.frames:
        if f["home"] or rp.parsed["moves"][f["i"]].get("cycle"):
            continue
        w = _words(rp.lines[f["line"] - 1])
        for ax, k in (("X", 0), ("Y", 1), ("Z", 2)):
            if ax in w:
                assert f["b"][k] == pytest.approx(w[ax], abs=1e-6), (f["line"], rp.lines[f["line"] - 1])
    # 时间 → 帧，帧 → 行
    i, s = rp.at(rp.frames[5]["t0"] + 1e-9)
    assert i == 5 and s == pytest.approx(0.0, abs=1e-6)
    assert 5 in rp.frames_of_line(rp.frames[5]["line"])


def test_clash_event_sits_on_the_clashing_frame():
    """压板挡在型腔上方：撞的事件挂在第一处撞的那一行，拖到那一帧时刀尖就在压板范围里"""
    clamp = {"id": "clamp", "name": "压板", "box_mm": [40, 25, 0, 60, 35, 15]}
    p = _prog({**MILL, "machine_sim": {**MSIM, "fixtures": [clamp]}})[0]
    rp = _replay(p, VMC)
    ev = [e for e in rp.events if "压板" in e["text"]]
    assert ev
    f = rp.frames[ev[0]["i"]]
    assert f["line"] == ev[0]["line"]
    # 这一帧扫过的线段与压板（含 10 mm 的刀具半径 + 1 mm 间隙）相交
    a, b = np.array(f["a"]), np.array(f["b"])
    lo, hi = np.array([40, 25, 0.0]) - 6, np.array([60, 35, 15.0]) + 6
    ts = np.linspace(0, 1, 200)
    pts = a + (b - a) * ts[:, None]
    assert (((pts >= lo) & (pts <= hi)).all(1)).any()


def test_mill_stock_checkpoints_match_full_simulation():
    p = _prog({**MILL, "machine_sim": MSIM})[0]
    rp = R.Replay(p["gcode"], VMC, p["replay_in"], h=0.5, keep_every=7)
    n = len(rp.frames)
    vols = [rp.removed_volume(k) for k in range(n + 1)]
    assert all(b >= a - 1e-9 for a, b in zip(vols, vols[1:], strict=False))
    mid = n // 2 + 3                                   # 不在检查点上：从最近的检查点补切
    d_mid = rp.stock_after(mid)
    v0 = rp.stock_after(0).volume()
    assert v0 - d_mid.volume() == pytest.approx(vols[mid], rel=1e-6)
    final = rp.stock_after(n)
    # 与直接按程序整段切一遍一致
    st = rp.stock_after(0).copy()
    DX.simulate(rp.parsed, st, {k: {**v, "L": 3 * v["d"]} for k, v in rp.tools.items()})
    assert np.allclose(np.nan_to_num(st.E[2]), np.nan_to_num(final.E[2]))
    v, t = R.height_mesh(final, stride=2)
    assert len(v) and len(t) and t.max() < len(v)


def test_turn_stock_history_matches_simulation():
    p = _prog({"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60]], "chamfer_mm": 1})[0]
    rp = _replay(p, LATHE)
    z, r, ri = rp.stock_after(len(rp.frames))
    st = {k: float(v) for k, v in p["replay_in"]["stock"].items()}
    s = S.simulate_turn(S.parse(p["gcode"], LATHE), st, {int(k): v for k, v in p["replay_in"]["tools"].items()}, h=0.05)
    assert np.allclose(r, s["r"])
    z0, r0, _ = rp.stock_after(0)
    assert r0.max() == pytest.approx(st["d"] / 2)
    v, t = R.lathe_mesh(z, r, ri)
    assert len(v) and t.max() < len(v)


def test_nearest_frame():
    p = _prog({**MILL, "machine_sim": MSIM})[0]
    rp = _replay(p, VMC)
    f = next(f for f in rp.frames if not f["rapid"] and np.linalg.norm(np.subtract(f["b"], f["a"])) > 5)
    mid = (np.array(f["a"]) + np.array(f["b"])) / 2
    j = rp.nearest_frame(mid + [0, 0, 0.01])
    assert np.linalg.norm(np.subtract(rp.tip(j, 0.5), mid)) < np.linalg.norm(np.subtract(f["b"], f["a"]))
    assert rp.nearest_frame([1e4, 0, 0], max_dist=5) is None
