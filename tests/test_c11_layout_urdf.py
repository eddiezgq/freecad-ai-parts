"""M4b #87：系统布局（ADR-0034）下的 C11 包络长度、系统 JSON 与 URDF 导出（ADR-0035）。"""

from __future__ import annotations

import asyncio
import copy
import math
import xml.etree.ElementTree as ET

import pytest
import yaml
from fastmcp import Client
from fastmcp.exceptions import ToolError

from engine.export import urdf
from engine.geometry import Pose, quat_axis_angle, rotate, rpy
from engine.golden import GOLDEN
from engine.system import SystemError_, load_system
from engine.validate import validate
from freecad_addon.core.system_layout import layout_system
from kb.library import JsonLibrary
from mcp_server import tools
from mcp_server.server import create_server

LIB = JsonLibrary(GOLDEN / "fixtures")
BASE = yaml.safe_load((GOLDEN / "valid" / "m750-r25-d750.yaml").read_text(encoding="utf-8"))["system"]


def with_layout(system: dict, poses: dict | None = None, length: float | None = None) -> dict:
    s = copy.deepcopy(system)
    if poses is None:
        scene, _ = layout_system(s, LIB.get)
        poses = {n: scene.pose(n).to_dict() for n in scene.instances}
    s["layout"] = {"poses": poses}
    if length is not None:
        s["requirement"]["max_envelope_length_mm"] = length
    return s


def c11(system: dict) -> dict:
    return next(c for c in validate(system, LIB.get)["checks"] if c["check"] == "C11")


def length_finding(system: dict) -> dict:
    res = c11(system)
    findings = res.get("findings", [res])  # 只有一条判定时，结果即该判定（实施细则第七节）
    return next(f for f in findings if "长度" in f["message"])


# ------------------------------------------------------------------ C11 长度

def test_length_boundary():
    # m750 机身后端 z=-120，r25 减速器（原点在 z=20，延伸到其 z=55）输出端 z=75：长 195 mm
    equal = length_finding(with_layout(BASE, length=195))
    assert equal["status"] == "pass" and equal["measured"] == pytest.approx(195)
    assert length_finding(with_layout(BASE, length=194.99))["status"] == "fail"
    assert c11(with_layout(BASE, length=194.99))["status"] == "fail"


def test_length_is_rotation_invariant_and_ignores_drive():
    s = with_layout(BASE, length=195)
    rot = Pose(quat_axis_angle((1, 1, 0), 73), (40, -10, 5))
    s["layout"]["poses"] = {n: rot.compose(Pose.from_dict(p)).to_dict() for n, p in s["layout"]["poses"].items()}
    # 驱动器摆得再远也不计入（ADR-0027）
    s["layout"]["poses"]["drive"] = Pose(translation=(0, 0, 5000)).to_dict()
    f = length_finding(s)
    assert f["status"] == "pass" and f["measured"] == pytest.approx(195, abs=1e-6)


def test_length_unknown_cases():
    s = with_layout(BASE, length=300)
    del s["layout"]["poses"]["reducer"]
    f = length_finding(s)
    assert f["status"] == "unknown" and "reducer 未布局" in f["message"]
    s = with_layout(BASE, length=300)
    s["layout"]["poses"] = {"drive": s["layout"]["poses"]["drive"], "motor": s["layout"]["poses"]["motor"]}
    assert "reducer 未布局" in length_finding(s)["message"]
    # 没有减速器：无法确定输出轴
    no_red = copy.deepcopy(BASE)
    no_red["components"] = [c for c in no_red["components"] if c["instance"] != "reducer"]
    no_red["connections"] = [c for c in no_red["connections"] if "reducer" not in c["a"] + c["b"]]
    f = length_finding(with_layout(no_red, {"motor": Pose().to_dict()}, length=300))
    assert f["status"] == "unknown" and "输出轴" in f["message"]


def test_without_layout_length_stays_not_applicable():
    s = copy.deepcopy(BASE)
    s["requirement"]["max_envelope_length_mm"] = 10
    res = c11(s)
    assert res["status"] == "not_applicable" and "FreeCAD" in res["message"]


def test_layout_relation_errors():
    s = with_layout(BASE)
    s["layout"]["poses"]["ghost"] = Pose().to_dict()
    with pytest.raises(SystemError_, match="ghost 不在 components"):
        load_system(s, LIB.get)
    s = with_layout(BASE)
    s["layout"]["poses"]["motor"] = {"position_mm": [0, 0, 0], "rotation": {"axis": [0, 0, 0], "angle_deg": 10}}
    with pytest.raises(SystemError_, match="位姿不合法"):
        load_system(s, LIB.get)
    with pytest.raises(tools.ToolInputError, match="不在 components"):
        tools.verify_system(LIB, {**with_layout(BASE), "layout": {"poses": {"ghost": Pose().to_dict()}}})


# ------------------------------------------------------------------ URDF


def _rot_from_rpy(r, p, y):
    qx, qy, qz = (quat_axis_angle(a, math.degrees(v)) for a, v in (((1, 0, 0), r), ((0, 1, 0), p), ((0, 0, 1), y)))
    return Pose(qz).compose(Pose(qy)).compose(Pose(qx))


def test_rpy_roundtrip():
    import random

    rng = random.Random(7)
    for _ in range(100):
        q = quat_axis_angle(tuple(rng.uniform(-1, 1) for _ in range(3)), rng.uniform(-180, 180))
        back = _rot_from_rpy(*rpy(q))
        for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            assert back.apply_dir(v) == pytest.approx(rotate(q, v), abs=1e-9)


def test_urdf_structure_and_traceability():
    s = with_layout(BASE)
    s["layout"]["poses"]["motor"] = Pose(quat_axis_angle((0, 1, 0), 90), (10, 20, 30)).to_dict()
    text = urdf(s, LIB.get)
    assert text == urdf(s, LIB.get)  # 确定性
    root = ET.fromstring(text.split("\n", 1)[1])
    assert root.tag == "robot" and root.get("name") == "m750-r25-d750"
    links = [link.get("name") for link in root.findall("link")]
    assert links == ["base", "motor", "reducer", "output"]  # 驱动器不计入
    joints = {j.get("name"): j for j in root.findall("joint")}
    assert set(joints) == {"motor_mount", "reducer_mount", "output_joint"}
    assert joints["output_joint"].get("type") == "continuous"
    assert joints["output_joint"].find("parent").get("link") == "reducer"
    # 输出法兰在 r25 坐标系 z=55 → 0.055 m
    assert joints["output_joint"].find("origin").get("xyz") == "0.0 0.0 0.055"
    m = joints["motor_mount"].find("origin")
    assert [float(x) for x in m.get("xyz").split()] == pytest.approx([0.01, 0.02, 0.03])
    back = _rot_from_rpy(*[float(x) for x in m.get("rpy").split()])
    assert back.apply_dir((0, 0, 1)) == pytest.approx(rotate(quat_axis_angle((0, 1, 0), 90), (0, 0, 1)), abs=1e-9)
    assert "test.servo_motor.test-vendor.m750" in text and "inertial" not in text.replace("未写 inertial", "")
    motor = root.findall("link")[1]
    assert len(motor.findall("visual")) == len(motor.findall("collision")) == 3
    assert motor.findall("visual")[2].find("geometry/cylinder").get("radius") == "0.0095"


def test_urdf_errors():
    with pytest.raises(ValueError, match="需要系统带 layout"):
        urdf(copy.deepcopy(BASE), LIB.get)
    s = with_layout(BASE)
    del s["layout"]["poses"]["reducer"]
    with pytest.raises(ValueError, match="reducer"):
        urdf(s, LIB.get)
    no_red = copy.deepcopy(BASE)
    no_red["components"] = [c for c in no_red["components"] if c["instance"] != "reducer"]
    no_red["connections"] = [c for c in no_red["connections"] if "reducer" not in c["a"] + c["b"]]
    with pytest.raises(ValueError, match="output_flange"):
        urdf(with_layout(no_red, {"motor": Pose().to_dict()}), LIB.get)


def test_export_tool_urdf_and_system_json_keep_layout():
    s = with_layout(BASE)
    out = tools.export_system(LIB, s, format="urdf")
    assert out["filename"] == "m750-r25-d750.urdf" and out["media_type"] == "application/xml"
    sj = tools.export_system(LIB, s, format="system_json")["content"]
    assert sj["system"]["layout"] == s["layout"]
    with pytest.raises(tools.ToolInputError, match="layout"):
        tools.export_system(LIB, copy.deepcopy(BASE), format="urdf")


# ------------------------------------------------------------------ MCP：use_layout


def test_use_layout_via_mcp():
    sys_ = copy.deepcopy(BASE)
    sys_["requirement"]["max_envelope_length_mm"] = 195

    async def run():
        async with Client(create_server(lambda: LIB, lambda: None)) as c:
            out = {}
            try:
                await c.call_tool("verify_system", {"system": sys_, "use_layout": True})
            except ToolError as exc:
                out["empty"] = str(exc)
            for i in sys_["components"]:
                await c.call_tool("place_component", {"instance": i["instance"], "component_id": i["component"]})
            await c.call_tool("connect_ports", {"a": "motor.mount_flange", "b": "reducer.motor_flange"})
            out["verify"] = (await c.call_tool("verify_system", {"system": sys_, "use_layout": True})).data
            out["urdf"] = (await c.call_tool("export_system", {"system": sys_, "format": "urdf",
                                                                "use_layout": True})).data
            await c.call_tool("place_component", {"instance": "motor", "remove": True})
            await c.call_tool("place_component", {"instance": "motor",
                                                  "component_id": "test.servo_motor.test-vendor.m400"})
            try:
                await c.call_tool("verify_system", {"system": sys_, "use_layout": True})
            except ToolError as exc:
                out["mismatch"] = str(exc)
            return out

    out = asyncio.run(run())
    assert "场景中没有该系统的实例" in out["empty"]
    c11_ = next(c for c in out["verify"]["report"]["checks"] if c["check"] == "C11")
    assert c11_["status"] == "pass" and "195" in c11_["message"]
    assert out["urdf"]["content"].startswith("<?xml")
    assert "不一致" in out["mismatch"]
