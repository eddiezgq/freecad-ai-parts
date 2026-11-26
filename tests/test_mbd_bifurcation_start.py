"""运动学 t = 0 在奇异位形（分岔）：报“t = 0 是奇异位形，请换初始位形”，不建议改用动力学分析。

《多体动力学》书第 44 章线索第 80 条（问渠 CAD 0.3.9 细则）：平行四边形（机架、连杆 100 mm，曲柄 80 mm）在四杆共线
位形开始、曲柄加 10 rpm 驱动，原来报“还剩 1 个自由度；有自由度的用动力学分析”。共线位形上瞬时 2 个自由度，离开就 1 个。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_mbd_dead_point import _body, _rev

from analysis.mbd.dae.run import run_model
from analysis.mbd.dae.solve import SolveError

DRIVE = [{"id": "m1", "joint": "R1", "dof": "rotation", "function": "60.0*time"}]
KIN = {"type": "kinematic", "end_time_s": 1.0, "output_steps": 100}


def test_parallelogram_collinear_start():
    m = {"format": "mbd-model/1", "name": "平行四边形", "gravity_mm_s2": [0, 0, 0],
         "bodies": [_body("crank", (0.04, 0)), _body("coupler", (0.13, 0)), _body("rocker", (0.14, 0))],
         "joints": [_rev("R1", "ground", "crank", (0, 0)), _rev("R2", "crank", "coupler", (0.08, 0)),
                    _rev("R3", "coupler", "rocker", (0.18, 0)), _rev("R4", "ground", "rocker", (0.1, 0))],
         "motions": DRIVE, "analysis": KIN}
    with pytest.raises(SolveError) as e:
        run_model(m)
    msg = str(e.value)
    assert "t = 0 是奇异位形" in msg and "瞬时有 2 个自由度" in msg and "只剩 1 个" in msg
    assert "有自由度的用动力学分析" not in msg


def test_really_missing_drive_keeps_old_advice():
    m = {"format": "mbd-model/1", "name": "双摆", "gravity_mm_s2": [0, 0, 0],
         "bodies": [_body("L1", (0.05, 0)), _body("L2", (0.15, 0))],
         "joints": [_rev("R1", "ground", "L1", (0, 0)), _rev("R2", "L1", "L2", (0.1, 0))],
         "motions": DRIVE, "analysis": KIN}
    with pytest.raises(SolveError, match="还剩 1 个自由度）；有自由度的用动力学分析"):
        run_model(m)
