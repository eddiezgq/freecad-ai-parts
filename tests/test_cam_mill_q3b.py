"""问渠CAM Q3b 2.5 轴铣与孔（ADR-0106）：外来刀路逐段核对切深 ap、切宽 ae；……"""

from __future__ import annotations

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
