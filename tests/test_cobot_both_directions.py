"""协作臂肩、肘关节两个方向都算，选型需求取包络。

《多体动力学》书第 40 章线索第 5 条（问渠 CAD 0.3.9 细则）：cobot_joint、cobot_arm 原来只算“从水平往下放”，肩关节峰值即
静重力矩 92.5 N·m；“往上抬”峰值 124.1 N·m（+34 %）。
"""
import pytest

import analysis
from analysis import mbd
from examples.apps import common as C

ARM = {"kind": "arm", "base_height_mm": 89, "links": [{"length_mm": 425, "mass_kg": 8.393}, {"length_mm": 392.25, "mass_kg": 2.275}],
       "payload_kg": 5 + 1.219 + 1.219 + 0.1879}


def _mv(j, to):
    return {"joint": j, "kind": "move", "to": to, "t0_s": 0.2, "t1_s": 1.2, "accel_ratio": 0.25}


def _run(a, b):
    return analysis.run("mbd", {"model": ARM, "duration_s": 1.4, "sample_hz": 100,
                                "drives": [_mv("j2", a), _mv("j3", b), {"joint": "j1", "kind": "hold"}]})


def test_shoulder_envelope_takes_raise():
    down, up = _run(-90, 90), _run(90, -90)
    rd, ru = mbd.requirement(down, "j2"), mbd.requirement(up, "j2")
    assert rd["output_torque_peak_nm"] == pytest.approx(92.5, rel=0.01)
    env = C.envelope({"往下放": rd, "往上抬": ru})
    assert env["output_torque_peak_nm"] == pytest.approx(124.1, rel=0.01)
    assert env["output_torque_cont_nm"] == max(rd["output_torque_cont_nm"], ru["output_torque_cont_nm"])
    assert "往上抬" in env["statement"] and "往下放" in env["statement"]
