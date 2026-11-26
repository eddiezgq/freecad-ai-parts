"""MuJoCo 路线的驱动侧惯量 armature（ADR-0134）。

《多体动力学》书第 40 章线索第 4 条（问渠 CAD 0.3.9 细则）：协作臂肩关节（SGM7J-04A-6 + CSF-32-100-2UH）
J_d = (J_m + J_in)·i² = 2.176 kg·m²；“往上抬”工况计入后均方根 81.99、峰值 142.30 N·m（mini-mbd 解析），原来只进 C8。
"""
import pytest

import analysis

ARM = {"kind": "arm", "base_height_mm": 89, "links": [{"length_mm": 425, "mass_kg": 8.393}, {"length_mm": 392.25, "mass_kg": 2.275}],
       "payload_kg": 5 + 1.219 + 1.219 + 0.1879}


def _mv(j, to):
    return {"joint": j, "kind": "move", "to": to, "t0_s": 0.2, "t1_s": 1.2, "accel_ratio": 0.25}


def _run(armature):
    return analysis.run("mbd", {"model": ARM, "duration_s": 1.4, "sample_hz": 100, "armature": armature,
                                "drives": [_mv("j2", 90), _mv("j3", -90), {"joint": "j1", "kind": "hold"}]})


def test_shoulder_raise_with_drive_inertia():
    d = next(x for x in _run({"j2": 2.176})["data"]["drives"] if x["joint"] == "j2")
    assert d["rms"] == pytest.approx(81.99, rel=0.01)
    assert d["peak"] == pytest.approx(142.30, rel=0.01)


def test_bad_joint_name():
    res = _run({"j9": 1.0})
    assert res["status"] == "failed" and "j9" in res["messages"][0]
