"""三铰共线的结构做动力学：开算前做有限可动检验，报“只能瞬时可动”，不抛求根的原始异常。

《多体动力学》书第 44 章线索第 79 条（问渠 CAD 0.3.9 细则）：两根 100 mm 杆，A(0,0)、B(100,0)、C(200,0) 三个转动副，
重力 −y，动力学 1 s。原来抛“f(a) and f(b) must have different signs”（后来改成算到 0.18 s 报被删约束拉开）；
书里沿运动模态走一小步再投影，被拉回原处——瞬时可动、不能有限运动。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_mbd_dead_point import _body, _fourbar, _rev

from analysis.mbd.dae.run import run_model
from analysis.mbd.dae.solve import SolveError


def _three_hinges(by=0.0):
    return {"format": "mbd-model/1", "name": "三铰", "gravity_mm_s2": [0, -9810, 0],
            "bodies": [_body("L1", (0.05, by / 2)), _body("L2", (0.15, by / 2))],
            "joints": [_rev("A", "ground", "L1", (0, 0)), _rev("B", "L1", "L2", (0.1, by)),
                       _rev("C", "L2", "ground", (0.2, 0))],
            "motions": [], "analysis": {"type": "dynamic", "end_time_s": 1.0, "output_steps": 100}}


def test_collinear_structure_reported_before_integration():
    with pytest.raises(SolveError) as e:
        run_model(_three_hinges())
    msg = str(e.value)
    assert "只能瞬时可动、不能有限运动" in msg and "运动副“A”、“B”、“C”" in msg and "结构自由度是 0" in msg
    assert "different signs" not in msg and "欧拉参数" not in msg


def test_mechanism_with_real_dof_passes():
    m = _fourbar(50)                                      # 曲柄摇杆去掉驱动，重力下摆：真有 1 个自由度
    m["motions"] = []
    m["gravity_mm_s2"] = [0, -9810, 0]
    m["analysis"] = {"type": "dynamic", "end_time_s": 0.05, "output_steps": 10}
    d, _ = run_model(m)
    assert d["times_s"][-1] == pytest.approx(0.05)
