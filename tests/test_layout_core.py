"""布局核心（freecad_addon/core，ADR-0032）的测试：位姿、配合、刚性组、场景序列化、按系统布局、包络投影。"""

from __future__ import annotations

import copy
import glob
import json
import math
import random
from pathlib import Path

import pytest
import yaml

from freecad_addon.core.geometry import LayoutError, bores, part_extent, parts
from freecad_addon.core.pose import (
    Pose,
    angle_deg,
    norm,
    quat_axis_angle,
    rotate,
    shortest_arc,
    sub,
)
from freecad_addon.core.scene import Connection, Scene, mate_kind
from freecad_addon.core.system_layout import layout_system
from kb.library import JsonLibrary

ROOT = Path(__file__).resolve().parent.parent
LIB = JsonLibrary(ROOT / "tests/golden/fixtures")
MOTOR = LIB.get("test.servo_motor.test-vendor.m400")
REDUCER = LIB.get("test.reducer.test-vendor.r20-100")
PLATE = LIB.get("test.adapter.test-vendor.plate-70-90")
SLEEVE = LIB.get("test.adapter.test-vendor.sleeve-11-19")
DRIVE = LIB.get("test.drive.test-vendor.d400")
VALID = sorted(glob.glob(str(ROOT / "tests/golden/valid/*.yaml")))


def close(a, b, tol=1e-9):
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def random_pose(rng: random.Random) -> Pose:
    axis = (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
    return Pose(quat_axis_angle(axis, rng.uniform(0, 360)), tuple(rng.uniform(-200, 200) for _ in range(3)))


def aligned(scene: Scene, a: str, b: str, kind: str) -> bool:
    _, oa, aa = scene.port_world(a)
    _, ob, ab = scene.port_world(b)
    if angle_deg(aa, ab) > 1e-6:
        return False
    if kind == "face":
        return norm(sub(oa, ob)) < 1e-6
    v = sub(ob, oa)
    t = sum(x * y for x, y in zip(v, aa, strict=True))
    return norm(tuple(v[i] - t * aa[i] for i in range(3))) < 1e-6


# ------------------------------------------------------------------ 位姿


def test_pose_compose_inverse_and_roundtrip():
    rng = random.Random(1)
    for _ in range(50):
        p, q = random_pose(rng), random_pose(rng)
        x = tuple(rng.uniform(-50, 50) for _ in range(3))
        assert close(p.compose(q).apply(x), p.apply(q.apply(x)), 1e-9)
        assert close(p.inverse().apply(p.apply(x)), x, 1e-9)
        back = Pose.from_dict(json.loads(json.dumps(p.to_dict())))
        assert close(back.apply(x), p.apply(x), 1e-6)


def test_shortest_arc_including_opposite():
    rng = random.Random(2)
    for _ in range(50):
        u = tuple(rng.uniform(-1, 1) for _ in range(3))
        v = tuple(rng.uniform(-1, 1) for _ in range(3))
        r = rotate(shortest_arc(u, v), u)
        assert angle_deg(r, v) < 1e-6
    for u in ((0, 0, 1), (1, 0, 0), (0.3, -0.2, 0.9)):
        opp = tuple(-c for c in u)
        assert angle_deg(rotate(shortest_arc(u, opp), u), opp) < 1e-6
    assert shortest_arc((0, 0, 1), (0, 0, 2)) == (1.0, 0.0, 0.0, 0.0)


def test_pose_dict_is_clean():
    d = Pose(quat_axis_angle((0, 0, 1), 90), (1e-15, -0.0, 3)).to_dict()
    assert d == {"position_mm": [0.0, 0.0, 3.0], "rotation": {"axis": [0.0, 0.0, 1.0], "angle_deg": 90.0}}
    assert Pose().to_dict()["rotation"] == {"axis": [0.0, 0.0, 1.0], "angle_deg": 0.0}


# ------------------------------------------------------------------ 配合规则


def test_mate_kinds_match_schema_connects_to():
    types = ["mechanical.cyl_male", "mechanical.cyl_female", "mechanical.flange", "mechanical.mount_face"]
    for ta in types:
        schema = json.loads((ROOT / f"schema/port-types/{ta}.schema.json").read_text(encoding="utf-8"))
        for tb in types:
            if tb in schema["x-connects-to"]:
                assert mate_kind(ta, tb) in ("face", "cylinder")
            else:
                with pytest.raises(LayoutError):
                    mate_kind(ta, tb)


def _motor_reducer(**reducer_pose) -> Scene:
    s = Scene()
    s.place("motor", MOTOR)
    s.place("reducer", REDUCER, Pose(**reducer_pose))
    return s


def test_face_mate_places_reducer_on_motor_flange():
    s = _motor_reducer(translation=(100, -40, 7))
    out = s.connect("motor.mount_flange", "reducer.motor_flange")
    assert out["moved"] == ["reducer"] and out["kind"] == "face"
    assert close(s.pose("reducer").translation, (0, 0, 20)) and close(s.pose("reducer").rotation, (1, 0, 0, 0))
    assert aligned(s, "motor.mount_flange", "reducer.motor_flange", "face")


def test_face_mate_from_arbitrary_poses_and_roll():
    rng = random.Random(3)
    for _ in range(30):
        s = Scene()
        s.place("motor", MOTOR, random_pose(rng))
        s.place("reducer", REDUCER, random_pose(rng))
        roll = rng.uniform(-180, 180)
        s.connect("motor.mount_flange", "reducer.motor_flange", roll_deg=roll)
        assert aligned(s, "motor.mount_flange", "reducer.motor_flange", "face")
    s = _motor_reducer()
    s.connect("motor.mount_flange", "reducer.motor_flange", roll_deg=90)
    assert close(s.pose("reducer").apply_dir((1, 0, 0)), (0, 1, 0))


def test_cylinder_only_uses_known_engagement():
    s = _motor_reducer()
    out = s.connect("motor.shaft", "reducer.input_bore")
    # 两侧都没有插入深度：孔口对齐轴端，并提示
    assert out["engagement_mm"] == 0 and "offset_mm" in out["note"]
    assert close(s.pose("reducer").translation, (0, 0, 50))
    r = copy.deepcopy(REDUCER)
    bore = next(p for p in r["ports"] if p["id"] == "input_bore")
    bore["spec"]["depth_mm"] = {**bore["spec"]["diameter_mm"], "value": 25}
    m = copy.deepcopy(MOTOR)
    shaft = next(p for p in m["ports"] if p["id"] == "shaft")
    shaft["spec"]["usable_length_mm"] = {**shaft["spec"]["diameter_mm"], "value": 28}
    s = Scene()
    s.place("motor", m)
    s.place("reducer", r)
    out = s.connect("motor.shaft", "reducer.input_bore")
    assert out["engagement_mm"] == 25 and "note" not in out
    # 孔口在轴端（z=30）后退 25 → z=5；孔口在减速器 z=-20 → 减速器原点 z=25
    assert close(s.pose("reducer").translation, (0, 0, 25))


def test_cylinder_offset_and_female_side_reference():
    s = _motor_reducer()
    s.connect("motor.shaft", "reducer.input_bore", offset_mm=-30)
    assert close(s.pose("reducer").translation, (0, 0, 20))
    # 以孔为基准移动电机：轴端在孔口前进插入深度（此处为 0）
    s = Scene()
    s.place("reducer", REDUCER)
    s.place("motor", MOTOR, Pose(translation=(9, 9, 9)))
    s.connect("reducer.input_bore", "motor.shaft", offset_mm=30)
    # 轴端 z=30 应在孔口 z=-20 前进 30 处 → z=10，故电机原点 z=-20
    assert close(s.pose("motor").translation, (0, 0, -20))
    assert aligned(s, "reducer.input_bore", "motor.shaft", "cylinder")


def test_face_after_cylinder_reanchors_axially():
    s = _motor_reducer()
    s.connect("motor.shaft", "reducer.input_bore")
    out = s.connect("motor.mount_flange", "reducer.motor_flange")
    assert "重定轴向位置" in out["note"]
    assert out["rechecked"][0]["engagement_mm"] == 30
    assert close(s.pose("reducer").translation, (0, 0, 20))


def test_cylinder_after_face_only_checks():
    s = _motor_reducer()
    s.connect("motor.mount_flange", "reducer.motor_flange")
    out = s.connect("motor.shaft", "reducer.input_bore")
    assert out["moved"] == [] and out["check"] == {
        "position_deviation_mm": 0.0, "angle_deviation_deg": 0.0, "engagement_mm": 30.0}
    with pytest.raises(LayoutError, match="同一刚性组"):
        Scene.from_dict(s.to_dict()).connect("motor.mount_flange", "reducer.housing_mount", roll_deg=5)


def _offset_bore_reducer(dx: float) -> dict:
    r = copy.deepcopy(REDUCER)
    r["id"] = "test.reducer.test-vendor.offset-bore"
    next(p for p in r["ports"] if p["id"] == "input_bore")["frame"]["origin_mm"] = [dx, 0, -20]
    return r


def test_misaligned_cylinder_in_group_is_rejected():
    s = Scene()
    s.place("motor", MOTOR)
    s.place("reducer", _offset_bore_reducer(1.0))
    s.connect("motor.mount_flange", "reducer.motor_flange")
    with pytest.raises(LayoutError, match="同轴偏差 1.0000 mm"):
        s.connect("motor.shaft", "reducer.input_bore")
    assert len(s.connections) == 1  # 失败的连接不记录


def test_failed_reanchor_rolls_back():
    s = Scene()
    s.place("motor", MOTOR)
    s.place("reducer", _offset_bore_reducer(1.0))
    s.connect("motor.shaft", "reducer.input_bore")
    before = s.pose("reducer")
    with pytest.raises(LayoutError, match="未对齐"):
        s.connect("motor.mount_flange", "reducer.motor_flange")
    assert s.pose("reducer") == before and len(s.connections) == 1


def test_tolerance_allows_tiny_deviation():
    s = Scene()
    s.place("motor", MOTOR)
    s.place("reducer", _offset_bore_reducer(0.005))
    s.connect("motor.mount_flange", "reducer.motor_flange")
    assert s.connect("motor.shaft", "reducer.input_bore")["check"]["position_deviation_mm"] == 0.005


def test_adapters_chain_and_group_moves_together():
    s = Scene()
    s.place("motor", LIB.get("test.servo_motor.test-vendor.m200"))
    s.place("plate", PLATE)
    s.place("sleeve", SLEEVE)
    s.place("reducer", LIB.get("test.reducer.test-vendor.r25-100"))
    s.connect("plate.reducer_side", "reducer.motor_flange")  # 先把减速器挂到转接板上
    out = s.connect("motor.mount_flange", "plate.motor_side")  # 再把整组挂到电机上
    assert out["moved"] == ["plate", "reducer"]
    assert close(s.pose("plate").translation, (0, 0, 0)) and close(s.pose("reducer").translation, (0, 0, 30))
    s.connect("motor.shaft", "sleeve.inner")
    assert aligned(s, "motor.shaft", "sleeve.inner", "cylinder")
    # 套筒外圆与减速器孔已在同一组（套筒随电机组）：只核对同轴
    assert s.connect("sleeve.outer", "reducer.input_bore")["moved"] == []
    moved = s.place("motor", pose=Pose(quat_axis_angle((1, 0, 0), 90), (10, 20, 30)))["moved"]
    assert moved == ["motor", "plate", "reducer", "sleeve"]
    for a, b, k in (("motor.mount_flange", "plate.motor_side", "face"),
                    ("plate.reducer_side", "reducer.motor_flange", "face"),
                    ("sleeve.outer", "reducer.input_bore", "cylinder")):
        assert aligned(s, a, b, k)


@pytest.mark.parametrize(("a", "b", "msg"), [
    ("motor.mount_flange", "motor.shaft", "同一实例"),
    ("motor.shaft", "reducer.motor_flange", "不能配合"),
    ("motor.power_in", "drive.motor_out", "不是机械端口"),
    ("motor.nope", "reducer.motor_flange", "没有端口"),
    ("ghost.x", "reducer.motor_flange", "没有实例"),
    ("motor", "reducer.motor_flange", "实例.端口"),
])
def test_connect_errors(a, b, msg):
    s = _motor_reducer()
    s.place("drive", DRIVE)
    with pytest.raises(LayoutError, match=msg):
        s.connect(a, b)


def test_other_scene_errors():
    s = _motor_reducer()
    s.connect("motor.mount_flange", "reducer.motor_flange")
    with pytest.raises(LayoutError, match="已经连接"):
        s.connect("reducer.motor_flange", "motor.mount_flange")
    with pytest.raises(LayoutError, match="小写字母"):
        s.place("Motor2", MOTOR)
    with pytest.raises(LayoutError, match="须给出组件"):
        s.place("new")
    with pytest.raises(LayoutError, match="须先删除"):
        s.place("motor", REDUCER)
    out = s.remove("reducer")
    assert out["dropped_connections"][0]["kind"] == "face" and s.connections == []


def test_face_offset_rejected():
    s = _motor_reducer()
    with pytest.raises(LayoutError, match="面配合不支持 offset_mm"):
        s.connect("motor.mount_flange", "reducer.motor_flange", offset_mm=1)


def test_scene_roundtrip_is_deterministic():
    s = _motor_reducer(translation=(1, 2, 3))
    s.connect("motor.mount_flange", "reducer.motor_flange", roll_deg=30)
    d = s.to_dict()
    again = Scene.from_dict(json.loads(json.dumps(d))).to_dict()
    assert json.dumps(d, sort_keys=True) == json.dumps(again, sort_keys=True)


# ------------------------------------------------------------------ 按系统布局


@pytest.mark.parametrize("path", VALID, ids=lambda p: Path(p).stem)
def test_golden_valid_systems_layout_aligned(path):
    system = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["system"]
    scene, report = layout_system(system, LIB.get)
    mech = 0
    for c in scene.connections:
        assert aligned(scene, c.a, c.b, c.kind), (c.a, c.b)
        mech += 1
    assert mech == len(system["connections"]) - len(report["non_mechanical_connections"])
    # 每组最先列出的成员在原点；交换连接两端的书写方向，结果不变
    for g in report["groups"]:
        assert scene.pose(g[0]) == Pose()
    flipped = copy.deepcopy(system)
    flipped["connections"] = [{**c, "a": c["b"], "b": c["a"]} for c in reversed(flipped["connections"])]
    scene2, _ = layout_system(flipped, LIB.get)
    for name in scene.instances:
        assert close(scene.pose(name).apply((1, 2, 3)), scene2.pose(name).apply((1, 2, 3)), 1e-9), name


def test_layout_system_reports_unmated_and_electrical():
    system = yaml.safe_load((ROOT / "tests/golden/valid/m750-r25-d750.yaml").read_text(encoding="utf-8"))["system"]
    scene, report = layout_system(system, LIB.get)
    assert report["groups"] == [["motor", "reducer"], ["drive"]] and report["unmated"] == ["drive"]
    assert len(report["non_mechanical_connections"]) == 2
    assert close(scene.pose("reducer").translation, (0, 0, 20))
    with pytest.raises(LayoutError, match="组件库中没有"):
        layout_system({**system, "components": [{"instance": "x", "component": "test.drive.none.x"}]}, LIB.get)


# ------------------------------------------------------------------ 包络几何


def test_parts_and_bores():
    ps = parts(MOTOR)
    assert [p.shape for p in ps] == ["box", "box", "cylinder"] and ps[2].diameter == 14
    b = bores(REDUCER)
    assert [(x.port, x.diameter, x.depth) for x in b] == [("input_bore", 14, None)]
    bad = copy.deepcopy(MOTOR)
    del bad["envelope"]["parts"][0]["width_mm"]
    with pytest.raises(LayoutError, match="width_mm"):
        parts(bad)
    ranged = copy.deepcopy(MOTOR)
    pv = ranged["envelope"]["parts"][2]["diameter_mm"]
    pv.pop("value")
    pv.update(min=13, max=15)
    with pytest.raises(LayoutError, match="diameter_mm"):
        parts(ranged)


def _brute_extent(part, pose, d, n=720):
    pts = []
    z0, z1 = part.z_start, part.z_start + part.length
    if part.shape == "box":
        for x in (-part.width / 2, part.width / 2):
            for y in (-part.height / 2, part.height / 2):
                pts += [(x, y, z0), (x, y, z1)]
    else:
        r = part.diameter / 2
        for i in range(n):
            t = 2 * math.pi * i / n
            pts += [(r * math.cos(t), r * math.sin(t), z0), (r * math.cos(t), r * math.sin(t), z1)]
    vals = [sum(a * b for a, b in zip(pose.apply(p), d, strict=True)) for p in pts]
    return min(vals), max(vals)


def test_part_extent_matches_brute_force():
    rng = random.Random(4)
    for part in parts(MOTOR) + parts(DRIVE):
        for _ in range(20):
            pose = random_pose(rng)
            d = tuple(rng.uniform(-1, 1) for _ in range(3))
            n = norm(d)
            d = tuple(c / n for c in d)
            lo, hi = part_extent(part, pose, d)
            blo, bhi = _brute_extent(part, pose, d)
            tol = 1e-9 if part.shape == "box" else part.diameter * 1e-4
            assert lo <= blo + 1e-9 and hi >= bhi - 1e-9
            assert abs(lo - blo) <= tol and abs(hi - bhi) <= tol


def test_part_extent_axis_aligned():
    cyl = parts(MOTOR)[2]  # 轴伸：z 0–30，直径 14
    assert part_extent(cyl, Pose(), (0, 0, 1)) == (0.0, 30.0)
    assert part_extent(cyl, Pose(), (1, 0, 0)) == (-7.0, 7.0)
    box = parts(DRIVE)[0]
    rot = Pose(quat_axis_angle((0, 0, 1), 90))
    lo, hi = part_extent(box, rot, (1, 0, 0))  # 转 90° 后 x 方向是原来的 height
    assert abs(lo + box.height / 2) < 1e-9 and abs(hi - box.height / 2) < 1e-9


def test_connection_dataclass_dict():
    assert Connection("a.x", "b.y", "face").to_dict() == {
        "a": "a.x", "b": "b.y", "kind": "face", "roll_deg": 0.0, "offset_mm": 0.0}
