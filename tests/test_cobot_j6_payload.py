"""整臂演练 j6 的负载模型与假设一致：5 kg 质点在半径 50 mm 处。

《多体动力学》书第 41 章线索第 69 条（问渠 CAD 0.3.9 细则）：原来是 50 mm 长、5 kg 的均布杆，峰值需求 0.041、连续 0.024 N·m；
按质点应为 0.105、0.062 N·m。
"""
import pytest

import analysis
from analysis import mbd
from examples.apps.cobot_arm import J6_SETUP


def test_j6_point_mass_requirement():
    req = mbd.requirement(analysis.run("mbd", J6_SETUP), "j1")
    assert req["output_torque_peak_nm"] == pytest.approx(0.105, abs=0.002)
    assert req["output_torque_cont_nm"] == pytest.approx(0.062, abs=0.002)
