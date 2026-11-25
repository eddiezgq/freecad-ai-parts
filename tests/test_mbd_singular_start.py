"""开始位形奇异、按冗余删掉的约束在运动中拉开：停下报锁死，不给结果。

《多体动力学》书第 35 章线索第 52 条（问渠 CAD 0.3.8 细则）。两根 0.5 m、1 kg 方杆的双摆水平静止释放，再在构件 2 的末端
x = 1000 mm 处加一个接地转动副——三个铰点共线，本应锁死。原来：删掉 4 条“冗余”约束（j1 x、j3 z、j3 f_i·h_j、j3 g_i·h_j），
积分照常完成，约束残差 2.0 判 fail；0.3.6 修第 11 条后自由度核查已不再判 pass（起始 1、结束 0，判 unknown）。
"""
import pytest

from analysis.mbd.dae.run import run_model
from analysis.mbd.dae.solve import SolveError

L, H, M = 0.5, 0.02, 1.0
IT, IA = M * (L * L + H * H) / 12, M * H * H / 6


def _bar(i, x0):
    return {"id": f"b{i}", "mass_kg": M, "cm_mm": [1000 * (x0 + L / 2), 0, 0], "inertia_kg_m2": {"ixx": IA, "iyy": IT, "izz": IT}}


def _model(extra_joint):
    j = [{"id": "j1", "type": "revolute", "body_i": "ground", "body_j": "b1", "point_mm": [0, 0, 0], "axis": [0, 0, 1]},
         {"id": "j2", "type": "revolute", "body_i": "b1", "body_j": "b2", "point_mm": [1000 * L, 0, 0], "axis": [0, 0, 1]}]
    if extra_joint:
        j.append({"id": "j3", "type": "revolute", "body_i": "ground", "body_j": "b2", "point_mm": [1000, 0, 0], "axis": [0, 0, 1]})
    return {"format": "mbd-model/1", "name": "双摆", "gravity_mm_s2": [0, -9810, 0], "bodies": [_bar(1, 0), _bar(2, L)],
            "joints": j, "analysis": {"type": "dynamic", "end_time_s": 0.5, "output_steps": 200}}


def test_locked_from_singular_start_stops():
    with pytest.raises(SolveError, match="机构锁死或开始时在奇异位形") as e:
        run_model(_model(True))
    msg = str(e.value)
    assert "结构自由度是 0" in msg
    assert "运动副“" in msg


def test_ordinary_double_pendulum_unaffected():
    d, _ = run_model(_model(False))
    res = next(v for v in d["verification"] if v["key"] == "constraint_residual")
    assert res["status"] == "pass"
