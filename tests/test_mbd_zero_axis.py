"""运动副的轴是零向量时指名报错。

《多体动力学》书线索第 58 条（问渠 CAD 0.3.9 细则）：revolute 的 axis = [0, 0, 0] 原来抛 ValueError
“array must not contain infs or NaNs”，不指名运动副。
"""
import pytest

from analysis.mbd.dae.model import ModelError
from analysis.mbd.dae.run import run_model


def test_zero_axis_names_the_joint():
    m = {"format": "mbd-model/1", "name": "摆", "gravity_mm_s2": [0, -9810, 0],
         "bodies": [{"id": "b", "mass_kg": 1.0, "cm_mm": [100, 0, 0], "inertia_kg_m2": {"ixx": 1e-3, "iyy": 1e-3, "izz": 1e-3}}],
         "joints": [{"id": "j1", "type": "revolute", "body_i": "ground", "body_j": "b", "point_mm": [0, 0, 0], "axis": [0, 0, 0]}],
         "analysis": {"type": "dynamic", "end_time_s": 0.1, "output_steps": 10}}
    with pytest.raises(ModelError, match="运动副 j1 的轴 不能是零向量"):
        run_model(m)
