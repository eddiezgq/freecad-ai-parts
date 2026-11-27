"""cobot_joint 选出肘部 j3 后，把它的电机 + 减速器按样本质量挂在大臂末端，再算肩关节 j2。

《多体动力学》书第 40 章线索第 6 条（问渠 CAD 0.3.9 细则）：两杆模板没挂肘部模组（SGM7J-02A-6 + CSF-25-100-2UH，2.3 kg），
肩关节连续扭矩少算 9.8 %（往上抬工况）。
"""
import pytest

import analysis
from examples.apps import common as C
from examples.apps.cobot_arm import module_mass

ARM = {"kind": "arm", "base_height_mm": 89, "links": [{"length_mm": 425, "mass_kg": 8.393}, {"length_mm": 392.25, "mass_kg": 2.275}],
       "payload_kg": 5 + 1.219 + 1.219 + 0.1879}


def _mv(j, to):
    return {"joint": j, "kind": "move", "to": to, "t0_s": 0.2, "t1_s": 1.2, "accel_ratio": 0.25}


def _rms_j2(arm):
    r = analysis.run("mbd", {"model": arm, "duration_s": 1.4, "sample_hz": 100,
                             "drives": [_mv("j2", 90), _mv("j3", -90), {"joint": "j1", "kind": "hold"}]})
    return next(x for x in r["data"]["drives"] if x["joint"] == "j2")["rms"]


def test_elbow_module_mass_and_effect():
    ids = [c["id"] for c in C.library().all()]
    system = {"components": [{"instance": "motor", "component": "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"},
                             {"instance": "reducer", "component": "reducer.harmonic-drive-llc.csf-25-100-2uh"}]}
    assert all(c["component"] in ids for c in system["components"])
    m3 = module_mass(system)
    assert m3 == pytest.approx(2.3)
    ratio = _rms_j2(dict(ARM, joint_masses_kg=[0.0, m3])) / _rms_j2(ARM) - 1
    assert ratio == pytest.approx(0.098, abs=0.003)
