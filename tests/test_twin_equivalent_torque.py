"""数字孪生运行记录的 output_torque_avg_nm 是当量扭矩（按转速、时间加权的三次方平均）。

《多体动力学》书第 48 章线索第 87 条（问渠 CAD 0.3.9 细则）：写算术平均时寿命多算 1.6 倍。
"""
import pytest

from analysis.twin import equivalent_load


def test_half_20_half_40():
    eq = equivalent_load([20.0, 40.0], [100.0, 100.0])
    assert eq["output_torque_avg_nm"] == pytest.approx(33.02, abs=0.01)
    assert eq["output_speed_rpm"] == pytest.approx(100.0)


def test_friction_sign_counts():
    # 摩擦力矩正负各半：算术平均看不出，当量扭矩看得出
    a = equivalent_load([10.0, -10.0], [50.0, -50.0])
    b = equivalent_load([12.0, -8.0], [50.0, -50.0])
    assert b["output_torque_avg_nm"] > a["output_torque_avg_nm"]


def test_standstill():
    assert equivalent_load([5.0, 5.0], [0.0, 0.0])["output_torque_avg_nm"] is None
