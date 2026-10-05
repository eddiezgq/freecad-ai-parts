"""接口标记（ADR-0048 第 4 条）：纯函数，用真实库组件测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from freecad_addon.core.port_markers import markers, object_name, ref_of
from freecad_addon.core.scene import Scene
from kb.library import JsonLibrary

LIB = JsonLibrary(Path(__file__).resolve().parent.parent / "data" / "library")
MOTOR = LIB.get("servo_motor.yaskawa-electric-corporation.sgm7j-02a-6")
REDUCER = LIB.get("reducer.harmonic-drive-llc.csf-25-100-2uh")
DRIVE = LIB.get("drive.yaskawa-america-inc.sgd7s-1r6a")


def test_only_mechanical_ports_get_markers_at_their_world_frames():
    s = Scene()
    s.place("motor", MOTOR)
    s.place("reducer", REDUCER)
    s.place("drive", DRIVE)
    ms = {m.ref: m for m in markers(s)}
    assert set(ms) == {"motor.shaft", "motor.mount_flange", "reducer.input_bore", "reducer.motor_flange",
                       "reducer.output_flange", "reducer.housing_mount", "drive.mount"}
    assert "drive.power_in" not in ms  # 电源、信号端口没有坐标系，不画
    shaft = ms["motor.shaft"]
    assert shaft.origin == pytest.approx((0, 0, 30)) and shaft.axis == pytest.approx((0, 0, 1))
    assert shaft.diameter == 14 and shaft.object_name == "motor__shaft"
    assert ms["reducer.motor_flange"].diameter == 20  # 可配置法兰没有分度圆：取缺省大小
    assert not any(m.connected for m in ms.values())


def test_connected_flags_and_positions_follow_the_scene():
    s = Scene()
    s.place("motor", MOTOR)
    s.place("reducer", REDUCER)
    s.connect("motor.shaft", "reducer.input_bore")
    ms = {m.ref: m for m in markers(s)}
    assert ms["motor.shaft"].connected and ms["reducer.input_bore"].connected
    assert not ms["reducer.output_flange"].connected
    # 减速器随连接移动，标记跟着它的端口走
    _, origin, _ = s.port_world("reducer.output_flange")
    assert ms["reducer.output_flange"].origin == pytest.approx(tuple(origin))


def test_object_names_round_trip():
    assert object_name("motor.mount_flange") == "motor__mount_flange"
    assert ref_of("motor__mount_flange") == "motor.mount_flange"
    assert ref_of("motor") is None and ref_of("__x") is None
