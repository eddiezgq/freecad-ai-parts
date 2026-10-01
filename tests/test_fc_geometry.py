"""FreeCAD 中的包络实体、干涉检查、worker 与截图（ADR-0032、ADR-0033）。需要 FreeCAD。"""

from __future__ import annotations

import base64
import copy
import math
import os
import struct
import sys
from pathlib import Path

import pytest
import yaml

from freecad_addon.core.pose import Pose
from freecad_addon.core.scene import Scene
from freecad_addon.core.system_layout import layout_system
from kb.library import JsonLibrary

pytestmark = pytest.mark.freecad

ROOT = Path(__file__).resolve().parent.parent
LIB = JsonLibrary(ROOT / "tests/golden/fixtures")
VALID = sorted((ROOT / "tests/golden/valid").glob("*.yaml"))
MOTOR = LIB.get("test.servo_motor.test-vendor.m400")
REDUCER = LIB.get("test.reducer.test-vendor.r20-100")


@pytest.fixture(scope="module")
def fc():
    import FreeCAD  # noqa: F401  须先于 Part 导入

    from freecad_addon.fc import interference, shapes

    return shapes, interference


def _layout(path: Path) -> Scene:
    system = yaml.safe_load(path.read_text(encoding="utf-8"))["system"]
    scene, report = layout_system(system, LIB.get)
    for i, name in enumerate(report["unmated"]):  # 未配合的实例沿 x 摆开
        scene.place(name, pose=Pose(translation=(300.0 * (i + 1), 0.0, 0.0)))
    return scene


def test_component_volumes(fc):
    shapes, _ = fc
    # 减速器：Φ70×65 圆柱减去贯穿的 Φ14 孔
    assert shapes.component_shape(REDUCER).Volume == pytest.approx(math.pi * (35**2 - 7**2) * 65, rel=1e-6)
    # 电机：法兰 60×60×10 + 机身 60×60×100 + 轴伸 Φ14×30
    assert shapes.component_shape(MOTOR).Volume == pytest.approx(
        60 * 60 * 10 + 60 * 60 * 100 + math.pi * 7**2 * 30, rel=1e-6)


def test_bore_with_known_depth(fc):
    shapes, _ = fc
    r = copy.deepcopy(REDUCER)
    bore = next(p for p in r["ports"] if p["id"] == "input_bore")
    bore["spec"]["depth_mm"] = {**bore["spec"]["diameter_mm"], "value": 20}
    assert shapes.component_shape(r).Volume == pytest.approx(math.pi * (35**2 * 65 - 7**2 * 20), rel=1e-6)


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_golden_valid_layouts_have_no_interference(fc, path):
    _, interference = fc
    result = interference.check(_layout(path))
    assert result["ok"], result["interferences"]
    if "adapters" in path.stem:
        assert [p["instance"] for p in result["pass_through"]] == ["plate"]
        assert result["pass_through"][0]["volume_mm3"] == pytest.approx(math.pi * 5.5**2 * 10, rel=1e-3)
    else:
        assert result["pass_through"] == []


def test_unplaced_drive_interferes(fc):
    _, interference = fc
    system = yaml.safe_load((ROOT / "tests/golden/valid/m400-r20-d400.yaml").read_text(encoding="utf-8"))["system"]
    scene, _ = layout_system(system, LIB.get)
    result = interference.check(scene)
    assert not result["ok"]
    pairs = {(i["a"], i["b"]): i for i in result["interferences"]}
    assert ("drive", "motor") in pairs and pairs[("drive", "motor")]["connected"] is False
    assert pairs[("drive", "motor")]["same_group"] is False


def test_shaft_bottoming_in_bore_is_reported(fc):
    """孔深 20 而轴插入 30：轴端多出的 10 mm 与减速器重叠，配合孔所在实例不享受穿过通道的例外。"""
    _, interference = fc
    r = copy.deepcopy(REDUCER)
    bore = next(p for p in r["ports"] if p["id"] == "input_bore")
    bore["spec"]["depth_mm"] = {**bore["spec"]["diameter_mm"], "value": 20}
    s = Scene()
    s.place("motor", MOTOR)
    s.place("reducer", r)
    s.connect("motor.mount_flange", "reducer.motor_flange")
    result = interference.check(s)
    (hit,) = result["interferences"]
    assert (hit["a"], hit["b"], hit["connected"]) == ("motor", "reducer", True)
    assert hit["volume_mm3"] == pytest.approx(math.pi * 7**2 * 10, rel=1e-3)


def test_lateral_offset_is_reported_and_threshold_applies(fc):
    _, interference = fc
    s = Scene()
    s.place("motor", MOTOR)
    s.place("reducer", REDUCER, Pose(translation=(2.0, 0.0, 20.0)))  # 未配合，偏 2 mm
    result = interference.check(s)
    assert not result["ok"] and result["interferences"][0]["connected"] is False
    vol = result["interferences"][0]["volume_mm3"]
    assert interference.check(s, threshold_mm3=vol + 1)["ok"]


def test_touching_faces_are_not_interference(fc):
    _, interference = fc
    s = Scene()
    s.place("motor", MOTOR)
    s.place("reducer", REDUCER)
    s.connect("motor.mount_flange", "reducer.motor_flange")
    assert interference.check(s, threshold_mm3=1e-3)["ok"]


# ------------------------------------------------------------------ worker


@pytest.fixture(scope="module")
def worker():
    from freecad_addon.fc.client import HeadlessWorker

    if "FreeCAD" in sys.modules or os.environ.get("FAP_REQUIRE_FREECAD") == "1":
        os.environ.setdefault("FAP_FREECAD_PYTHON", sys.executable)
    w = HeadlessWorker(timeout_s=180)
    yield w
    w.close()


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_worker_matches_in_process(fc, worker):
    _, interference = fc
    assert worker.call("ping") == {"freecad": "1.0.2"}
    for path in (VALID[0], ROOT / "tests/golden/valid/m200-adapters-r25-d400.yaml"):
        scene = _layout(path)
        assert worker.call("interference", {"scene": scene.to_dict()}) == interference.check(
            Scene.from_dict(scene.to_dict()))


def test_worker_snapshot_and_errors(worker):
    from freecad_addon.fc.client import WorkerError

    if not os.environ.get("DISPLAY") and not os.environ.get("FAP_REQUIRE_FREECAD"):
        pytest.skip("没有显示环境")
    scene = _layout(ROOT / "tests/golden/valid/m750-r25-d750.yaml")
    snap = worker.call("snapshot", {"scene": scene.to_dict(), "view": "iso", "width": 320, "height": 240})
    data = base64.b64decode(snap["png_base64"])
    assert _png_size(data) == (320, 240) and len(data) > 2000  # 不是空白图
    with pytest.raises(WorkerError) as exc:
        worker.call("snapshot", {"scene": scene.to_dict(), "view": "diagonal"})
    assert exc.value.kind == "snapshot"
    with pytest.raises(WorkerError) as exc:
        worker.call("interference", {})
    assert exc.value.kind == "input"
    with pytest.raises(WorkerError, match="未知方法"):
        worker.call("explode")
    worker.close()
    assert worker.call("ping") == {"freecad": "1.0.2"}  # 关闭后再次调用会重启
