"""问渠CAM Q3b 2.5 轴铣与孔（ADR-0106）：外来刀路逐段核对切深 ap、切宽 ae；……"""

from __future__ import annotations

import math

import pytest

from analysis import cam
from analysis.cam import machines, sim
from tests.verification import record

VMC = machines.get("EX-VMC")
MSIM = {"work_offset_mm": [0, 0, 40], "tools": {"1": {"tool": "EM10", "length_mm": 120}}}


def _prog(moves, **tool):
    return {"number": 6001, "title": "手写", "ops": [{"tool": {"n": 1, "d": 10.0, "kind": "endmill", "name": "EM10", **tool},
                                                     "spindle": {"rpm": 4000}, "safe": 5.0, "moves": moves}]}


def _slot(depth):
    """Ø10 立铣刀一刀开 40 长的槽，深 depth"""
    return [{"t": "rapid", "x": 30, "y": 30, "z": 5}, {"t": "feed", "x": 30, "y": 30, "z": -depth, "f": 200},
            {"t": "feed", "x": 70, "y": 30, "z": -depth, "f": 600}, {"t": "rapid", "x": 70, "y": 30, "z": 5}]


def _run(prog):
    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": prog, "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": MSIM, "post": "fanuc"})
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"][0]


def test_depth_of_cut_over_catalogue_withholds_program():
    """外来刀路一刀切 8 mm，刀具样本 ap ≤ 5：报错误、不出正式程序；分两层（每层 4 mm）就出"""
    p = _run(_prog(_slot(8), ap_max=5.0, ae_max=2.5))
    err = [c["text"] for c in p["checks"] if c["level"] == "error"]
    assert any("切深 ap 最大 8.00" in e for e in err), err
    assert p["release"] is None
    two = _slot(4)[:3] + [{"t": "feed", "x": 70, "y": 30, "z": -8, "f": 200}, {"t": "feed", "x": 30, "y": 30, "z": -8, "f": 600},
                          {"t": "rapid", "x": 30, "y": 30, "z": 5}]
    p = _run(_prog(two, ap_max=5.0, ae_max=2.5))
    assert not [c for c in p["checks"] if c["level"] == "error" and "切深" in c["text"]]
    assert p["release"] is not None
    # 开槽切宽 = 刀径 10 > 样本 ae 2.5：这几段的切深样本没给，报未知（不当通过）
    assert any(c["level"] == "unknown" and "切宽 ae 超过样本" in c["text"] for c in p["checks"])


def test_no_catalogue_ap_is_unknown():
    p = _run(_prog(_slot(3)))
    assert any(c["level"] == "unknown" and "没给最大切深" in c["text"] for c in p["checks"])


@pytest.mark.parametrize("ae", [1.0, 2.5, 4.0])
def test_measured_width_of_cut(ae):
    """侧铣：先开出 Ø10 槽，再沿槽壁偏 ae 走一刀——仿真量出的切宽与设定值之差不超过一格"""
    side = [{"t": "rapid", "x": 30, "y": 30 + ae, "z": 5}, {"t": "feed", "x": 30, "y": 30 + ae, "z": -3, "f": 200},
            {"t": "feed", "x": 70, "y": 30 + ae, "z": -3, "f": 600}, {"t": "rapid", "x": 70, "y": 30 + ae, "z": 5}]
    prog = _prog(_slot(3) + side)
    parsed = sim.parse(cam.post.post(prog, VMC), VMC)
    s = sim.simulate_mill(parsed, {"box": [0, 0, 100, 60], "top": 0.0}, {1: {"kind": "endmill", "d": 10.0}}, h=0.05)
    cuts = [m for m in parsed["moves"] if m.get("ae") is not None]
    assert cuts[0]["ae"] == pytest.approx(10.0, abs=0.1)                # 开槽：满刀宽
    got = cuts[-1]["ae"]
    record((f"侧铣切宽 ae = {ae:g} mm 的仿真量值", f"side milling width of cut ae = {ae:g} mm, simulated"),
           got, ae, tol=0.1, rel=False, unit="mm", formula="ae（设定的刀心偏移）")
    assert got == pytest.approx(ae, abs=0.1)
    assert s["ap_max"] == pytest.approx(3.0, abs=1e-6)


def _tap_prog(drill_depth=20.0):
    holes = [(30, 30), (70, 30)]
    drill = [{"t": "drill", "x": x, "y": y, "z": -drill_depth, "r": 2.0, "f": 300, "safe": 5.0} for x, y in holes]
    tap = [{"t": "tap", "x": x, "y": y, "z": -15.0, "r": 3.0, "pitch": 1.5, "safe": 5.0} for x, y in holes]
    return {"number": 6001, "title": "钻孔攻丝", "ops": [
        {"tool": {"n": 4, "d": 8.5, "kind": "drill", "name": "DR8.5"}, "spindle": {"rpm": 2200}, "safe": 5.0, "moves": drill},
        {"tool": {"n": 5, "d": 10.0, "kind": "tap", "pitch": 1.5, "name": "TAP-M10"}, "spindle": {"rpm": 400}, "safe": 5.0, "moves": tap}]}


@pytest.mark.parametrize("post", ["fanuc", "siemens"])
def test_rigid_tapping_output_and_read_back(post):
    """M10×1.5 攻丝：FANUC 出 M29 + G84（F = 1.5 × 400 = 600），西门子出 G331 / G332（K1.5）；回读与仿真刀路一致才出；
    攻丝时间 = 2 孔 ×（进 + 退）×（R3 到 Z−15 共 18 mm）/ 600 mm/min"""
    msim = {"work_offset_mm": [0, 0, 40], "tools": {"4": {"tool": "DR8.5", "length_mm": 140}, "5": {"tool": "TAP-M10", "length_mm": 130}}}
    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": _tap_prog(), "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": msim, "post": post})
    p = r["data"]["programs"][0]
    assert not [c for c in p["checks"] if c["level"] == "error"], [c["text"] for c in p["checks"] if c["level"] == "error"]
    assert p["release"] is not None
    text = p["release"]["text"]
    assert ("M29 S400" in text and "G84" in text and "F600.0" in text) if post == "fanuc" else ("G331 Z-15.0 K1.5" in text and "G332" in text)
    parsed = sim.parse(p["gcode"], VMC)
    tap = [m for m in parsed["moves"] if m.get("tap") is not None]
    t = sum(math.dist(m["a"], m["b"]) / m["f"] * 60 for m in tap)
    if post == "fanuc":
        record(("刚性攻丝时间（2 孔 M10×1.5，400 r/min）", "rigid tapping time (2 holes M10×1.5, 400 rpm)"),
               t, 2 * 2 * 18 / 600 * 60, tol=1e-6, rel=True, unit="s", formula="t = 2·L / (P·n)")
    assert t == pytest.approx(2 * 2 * 18 / 600 * 60)


def test_tapping_without_drilled_hole_is_reported():
    """底孔只钻到 Z−10，攻丝到 Z−15：报错误；改了转速没改 F（F/S ≠ 螺距）也报"""
    prog = _tap_prog(drill_depth=10.0)
    s = sim.simulate_mill(sim.parse(cam.post.post(prog, VMC), VMC), {"box": [0, 0, 100, 60], "top": 0.0},
                          {4: {"kind": "drill", "d": 8.5}, 5: {"kind": "tap", "d": 10.0, "pitch": 1.5}})
    assert any("底孔没钻到位" in i["text"] for i in s["issues"])
    g = cam.post.post(_tap_prog(), VMC).replace("M29 S400", "M29 S500")
    s = sim.simulate_mill(sim.parse(g, VMC), {"box": [0, 0, 100, 60], "top": 0.0},
                          {4: {"kind": "drill", "d": 8.5}, 5: {"kind": "tap", "d": 10.0, "pitch": 1.5}})
    assert any("不等于丝锥螺距" in i["text"] for i in s["issues"])


def test_countersink_cone_matches_geometry():
    """90° 倒角刀（刀尖直径 0）在 Ø8.5 孔口锪到 Z−5：孔口直径 = 2·5·tan45° = 10；锥面上每一点 z = −(5 − ρ)"""
    import numpy as np

    prog = _tap_prog()
    prog["ops"] = prog["ops"][:1] + [{"tool": {"n": 6, "d": 16.0, "kind": "chamfer", "tip_d": 0.0, "angle": 90.0, "name": "CM90"},
                                      "spindle": {"rpm": 1500}, "safe": 5.0,
                                      "moves": [{"t": "drill", "x": 30, "y": 30, "z": -5.0, "r": 2.0, "f": 100, "safe": 5.0}]}]
    s = sim.simulate_mill(sim.parse(cam.post.post(prog, VMC), VMC), {"box": [0, 0, 100, 60], "top": 0.0},
                          {4: {"kind": "drill", "d": 8.5}, 6: {"kind": "chamfer", "d": 16.0, "tip_d": 0.0, "angle": 90.0}}, h=0.05)
    X, Y = np.meshgrid(s["x"], s["y"], indexing="ij")
    rho = np.hypot(X - 30, Y - 30)
    ring = (rho > 4.4) & (rho < 4.9)
    err = float(np.abs(s["H"][ring] - (-(5 - rho[ring]))).max())
    record(("90° 倒角刀锪孔口：锥面高度与 z = −(5 − ρ) 之差（最大）", "90° countersink: max deviation of cone from z = −(5 − ρ)"),
           err, 0.0, tol=0.05, rel=False, unit="mm", formula="z = −(h − ρ / tan(α/2))")
    assert err <= 0.05
    assert float(s["H"][(rho > 5.1) & (rho < 6)].min()) == pytest.approx(0.0)       # 孔口直径 10 以外没动
