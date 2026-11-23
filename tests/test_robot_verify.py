"""整机复核（analysis/robot/mjcf.mjcf_parts、assist/robot_verify.py，ADR-0115 44.3 之二第 5 步）。

标准题：零件按点质量挂在杆件上，水平伸直时肩部静重力矩 = Σ mᵢ·g·xᵢ（手算）；装在基座上的零件不进模型。
"""

from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import mujoco  # noqa: F401
else:
    pytest.importorskip("mujoco")

import analysis
from analysis.robot import mjcf
from tests.test_robot_build import two_link

G = 9.81


def test_point_mass_parts_give_hand_calculated_gravity_torque():
    c = two_link()
    # 零位竖直：上臂沿 z 从 50 到 350，前臂 350 到 550；零件重心给在零位的世界坐标
    parts = [{"name": "上臂支架", "body": "upper", "mass_kg": 0.2, "cog_mm": [0, 0, 150]},
             {"name": "肘模组", "body": "upper", "mass_kg": 0.5, "cog_mm": [0, 0, 350]},
             {"name": "前臂管", "body": "fore", "mass_kg": 0.1, "cog_mm": [0, 0, 450]},
             {"name": "底座", "body": "base", "mass_kg": 5.0, "cog_mm": [0, 0, 0]}]
    xml = mjcf.mjcf_parts(c, parts, payload_kg=0.3)
    drives = [{"joint": j, "kind": "hold"} for j in ("j1", "j2", "j3")]
    r = analysis.run("mbd", {"model": {"kind": "mjcf", "xml": xml}, "duration_s": 0.01, "initial": {"j2": 90},
                             "drives": drives})
    assert r["status"] == "ok", r.get("error")
    g = r["data"]["static"]["gravity_torque_nm"]
    # 转 90° 后，离肩（z = 50）的距离变成水平力臂：100、300、400，负载在 500
    hand = G * (0.2 * 0.100 + 0.5 * 0.300 + 0.1 * 0.400 + 0.3 * 0.500)
    assert abs(g["j2"]) == pytest.approx(hand, rel=1e-6)
    assert abs(g["j3"]) == pytest.approx(G * (0.1 * 0.100 + 0.3 * 0.200), rel=1e-6)


def test_unknown_body_is_an_error():
    with pytest.raises(Exception, match="不存在的杆件"):
        mjcf.mjcf_parts(two_link(), [{"name": "x", "body": "nope", "mass_kg": 1.0, "cog_mm": [0, 0, 0]}])


def test_verify_on_an_assembled_arm(tmp_path):
    pytest.importorskip("gmsh")
    from analysis.robot import fit
    from assist import robot_build as RB
    from assist import robot_cad as RC
    from assist import robot_verify as RV
    from tests.test_robot_cad import _ok_arm
    from tests.test_robot_fit import _comp

    c, comp = _ok_arm(), _comp()
    fr = fit.check(c, {j["id"]: comp for j in c["joints"]}, min_spare_mm=RC.min_spare_mm())
    cad = RC.build(c, fr, comp)
    for j in c["joints"]:
        j["module_group"] = "g"
    out = RB.build(c, 0.5, move_s=2.0)
    v = RV.verify(c, out, cad, 0.5)
    assert v["status"] in ("pass", "fail", "unknown") and len(v["compare"]) == 5
    assert v["moving_mass_kg"] < cad["mass_kg"]                      # 基座不动
    shoulder = next(x for x in v["compare"] if x["joint"] == "j2")
    assert shoulder["peak_nm"] > shoulder["peak_est_nm"]            # 支架、套管算进去，肩部更吃力
