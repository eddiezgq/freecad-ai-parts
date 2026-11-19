"""问渠CAM Q3c 三维曲面（ADR-0106）：高度图仿真支持球头刀；残留高度对理论值。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from analysis import cam
from analysis.cam import machines, sim
from tests.verification import record

VMC = machines.get("EX-VMC")


def _run(moves, d=6.0, h=0.02, box=(0, 0, 30, 20)):
    prog = {"number": 1, "title": "t", "ops": [{"tool": {"n": 1, "d": d}, "spindle": {"rpm": 8000}, "safe": 5.0, "moves": moves}]}
    return sim.simulate_mill(sim.parse(cam.post.post(prog, VMC), VMC), {"box": list(box), "top": 0.0},
                             {1: {"kind": "ballend", "d": d}}, h=h)


def test_ball_scallop_height_on_flat():
    """球头刀 R3 平面上平行走刀、行距 2：两行之间的残留高度 h = R − √(R² − (s/2)²) = 0.172"""
    mv = []
    for k, y in enumerate(np.arange(5.0, 15.0 + 1e-9, 2.0)):
        xs = (5.0, 25.0) if k % 2 == 0 else (25.0, 5.0)
        mv += [{"t": "rapid", "x": xs[0], "y": float(y), "z": 2.0}, {"t": "feed", "x": xs[0], "y": float(y), "z": -1.0, "f": 300.0},
               {"t": "feed", "x": xs[1], "y": float(y), "z": -1.0, "f": 1000.0}, {"t": "rapid", "x": xs[1], "y": float(y), "z": 2.0}]
    s = _run(mv)
    H, xs, ys = s["H"], s["x"], s["y"]
    band = (ys > 7) & (ys < 13)
    col = H[np.argmin(np.abs(xs - 15)), band]
    got = float(col.max() - (-1.0))
    want = 3 - math.sqrt(9 - 1)
    record(("球头刀 R3 行距 2 的残留高度（平面）", "ball R3, stepover 2: scallop height on a flat"), got, want, tol=0.005, rel=False, unit="mm",
           formula="h = R − √(R² − (s/2)²)")
    assert got == pytest.approx(want, abs=0.005)
    assert float(col.min()) == pytest.approx(-1.0, abs=1e-4)
