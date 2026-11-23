"""X540 壳体的机械接口与外形（ingest/robotis_x540.py，ADR-0115 44.3 之二第 2 步）。

不需要 FreeCAD 的部分：端口、包络合 schema，8 个 X540 型号都带上了；与图纸标注一致（数值写在测试里，是看图纸核对的结果）。
需要 FreeCAD 且有 STEP（data/raw/robotis/，不入库）时：重新量一遍，与 MEASURED 比。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ingest import robotis_x540 as X
from kb.validation import errors

ROOT = Path(__file__).parents[1]
STEP = ROOT / "data" / "raw" / "robotis" / "XM_H_D-540.N101.I101.STP"


def test_matches_drawing_annotations():
    m = X.MEASURED
    assert m["body_x"][1] - m["body_x"][0] == 33.5 and m["body_y"][1] - m["body_y"][0] == 58.5
    assert m["body_z"][1] - m["body_z"][0] == 44 and m["body_y"][1] == 13.75
    assert m["horn_hole_pcd"] == 22 and m["horn_hole_count"] == 8 and m["horn_diameter"] == 26
    sh = m["side_holes"]
    assert abs(sh["y"][0] - sh["y"][1]) == 32 and abs(sh["z"][0] - sh["z"][1]) == 16
    bh = m["bottom_holes"]
    assert abs(bh["x"][0] - bh["x"][1]) == 20 and abs(bh["z"][0] - bh["z"][1]) == 16


def test_ports_and_envelope_in_component_frame():
    ports = {p["id"]: p for p in X.ports()}
    assert ports["output_flange"]["frame"]["origin_mm"] == [0.0, 0.0, 0.0]          # 原点在输出舵盘端面中心
    assert ports["idler_flange"]["frame"]["origin_mm"][2] == pytest.approx(-49.0)
    assert ports["mount_side_r"]["frame"]["origin_mm"] == [16.75, -22.0, -24.5]
    env = X.envelope()["parts"]
    body = next(p for p in env if p["label"] == "body")
    assert body["z_start_mm"] == -46.5 and body["length_mm"]["value"] == 44
    assert body["height_mm"]["value"] == 89.5 and body["height_mm"]["method"] == "computed"


def test_library_x540_models_carry_the_interfaces():
    for ref in X.MODELS:
        c = json.loads((ROOT / "data" / "library" / "smart_actuator" / f"smart_actuator.robotis.{ref}.json").read_text(encoding="utf-8"))
        assert not errors("component.schema.json", c), ref
        ids = {p["id"] for p in c["ports"]}
        assert {"output_flange", "idler_flange", "mount_side_r", "mount_side_l", "mount_bottom", "power_in", "bus"} <= ids
    other = json.loads((ROOT / "data" / "library" / "smart_actuator" / "smart_actuator.robotis.xm430-w350.json").read_text(encoding="utf-8"))
    assert "output_flange" not in {p["id"] for p in other["ports"]}                # 430 没有图纸：不写


@pytest.mark.freecad
@pytest.mark.skipif(not STEP.exists(), reason="STEP 不入库：本地放到 data/raw/robotis/ 才复核")
def test_measured_values_reproduce_from_step():
    pytest.importorskip("Part")
    got = X.measure_step(STEP)
    m = X.MEASURED
    bb = got["bbox"]
    assert bb[0] == pytest.approx(m["body_x"][0], abs=0.01) and bb[1] == pytest.approx(m["body_x"][1], abs=0.01)
    assert bb[2] == pytest.approx(m["body_y"][0], abs=0.01) and bb[3] == pytest.approx(m["body_y"][1], abs=0.01)
    assert bb[5] == pytest.approx(m["boss_front_z"], abs=0.01) and bb[4] == pytest.approx(-m["horn_face_z"], abs=0.01)
    front = [c for c, a in got["holes"] if a == (0.0, 0.0, 1.0) and abs(math.hypot(c[0], c[1]) - 11.0) < 0.01]
    assert len(front) == m["horn_hole_count"]
    side = {(c[1], c[2]) for c, a in got["holes"] if abs(a[0]) == 1.0 and c[0] > 0}
    assert side == {(y, z) for y in m["side_holes"]["y"] for z in m["side_holes"]["z"]}
    bottom = {(c[0], c[2]) for c, a in got["holes"] if a == (0.0, -1.0, 0.0) and c[1] < -40}
    assert bottom == {(x, z) for x in m["bottom_holes"]["x"] for z in m["bottom_holes"]["z"]}
    assert min(got["horn_faces"]) == pytest.approx(-m["horn_face_z"]) and max(got["horn_faces"]) == pytest.approx(m["horn_face_z"])
