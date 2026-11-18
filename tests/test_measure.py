"""通道 C：从三维模型量自制件（ADR-0099 41.4）。LS-101 的轴段要与《机械设计》33.11 一致。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from assist import measure as M
from kb.validation import errors

ROOT = Path(__file__).resolve().parents[1]
LS101 = ROOT / "examples" / "apps" / "out" / "lockstitch" / "LS-101.step"
BOOK_33_11 = [(10, 22), (12, 10), (16, 215), (12, 10), (10, 40)]       # 上轴各段 Ø×长，《机械设计》33.11


@pytest.fixture(scope="module")
def ls101():
    return M.measure(LS101, material="45-QT")


def test_ls101_segments_match_book(ls101):
    segs = ls101["segments"]
    assert len(segs) == len(BOOK_33_11)
    start = 0.0
    for s, (d, length) in zip(segs, BOOK_33_11, strict=True):
        assert abs(s["diameter_mm"] - d) <= 0.01 and abs(s["length_mm"] - length) <= 0.05
        assert abs(s["start_mm"] - start) <= 0.05
        start += length
    assert ls101["envelope_mm"]["length"] == pytest.approx(297, abs=0.05)
    assert ls101["max_diameter_mm"] == 16


def test_ls101_mass_from_volume_and_density(ls101):
    vol = sum(math.pi * d * d / 4 * length for d, length in BOOK_33_11)
    assert ls101["volume_mm3"] == pytest.approx(vol, rel=1e-3)               # 模型就是这五段圆柱（无倒角）
    assert ls101["mass_kg"] == pytest.approx(ls101["volume_mm3"] * 1e-9 * 7850, abs=1e-4)


def test_component_is_schema_valid_and_traceable(ls101):
    comp = M.to_component(ls101, enterprise="示范缝纫机有限公司", drawing_no="LS-101", doc="src-demo-ls-101-step",
                          part_kind="shaft", vendor_slug="demo-sewing")
    assert comp["id"] == "custom_part.demo-sewing.ls-101" and comp["ports"] == []
    assert errors("component.schema.json", comp) == []
    p = comp["params"]
    assert p["segment_3_diameter_mm"]["value"] == 16 and p["segment_3_length_mm"]["value"] == 215
    assert p["segment_3_diameter_mm"]["method"] == "measured" and p["segment_3_diameter_mm"]["source"]["doc"] == "src-demo-ls-101-step"
    assert "舍入" in p["segment_3_diameter_mm"]["source"]["note"]
    assert p["mass_kg"]["method"] == "computed" and "density" in p["mass_kg"]["source"]["formula"]
    assert not any(v.get("reviewed") for v in p.values())                    # 量出来的也要人复核后才算数
    assert [x["shape"] for x in comp["envelope"]["parts"]] == ["cylinder"] * 5


def test_no_material_no_mass():
    m = M.measure(LS101)
    assert "mass_kg" not in m and "volume_mm3" in m
    comp = M.to_component(m, enterprise="示范", drawing_no="LS-101", doc="src-demo-ls-101-step")
    assert "mass_kg" not in comp["params"] and "part_kind" not in comp["params"]
    assert errors("component.schema.json", comp) == []


def test_unknown_part_kind_refused(ls101):
    with pytest.raises(ValueError, match="不在清单"):
        M.to_component(ls101, enterprise="示范", drawing_no="LS-101", doc="src-x", part_kind="spindle")


@pytest.fixture(scope="module")
def flange(tmp_path_factory):
    """盘：Ø100 × 12，中心孔 Ø30，6 × Ø9 均布在 Ø70 上（用 gmsh 现做，不入库）"""
    from analysis.fea.geometry import _LOCK, _gmsh

    p = tmp_path_factory.mktemp("flange") / "FL-1.step"
    with _LOCK:
        g = _gmsh()
        g.clear()
        g.model.add("fl")
        disk = g.model.occ.addCylinder(0, 0, 0, 0, 0, 12, 50)
        cuts = [(3, g.model.occ.addCylinder(0, 0, -1, 0, 0, 14, 15))]
        for i in range(6):
            a = 2 * math.pi * i / 6
            cuts.append((3, g.model.occ.addCylinder(35 * math.cos(a), 35 * math.sin(a), -1, 0, 0, 14, 4.5)))
        g.model.occ.cut([(3, disk)], cuts)
        g.model.occ.synchronize()
        g.write(str(p))
        g.clear()
    return p


def test_hole_pattern(flange):
    m = M.measure(flange)
    assert m["hole_patterns"] == [{"count": 6, "diameter_mm": 9.0, "pcd_mm": pytest.approx(70, abs=0.01)}]
    comp = M.to_component(m, enterprise="示范", drawing_no="FL-1", doc="src-demo-fl-1-step", part_kind="plate")
    assert comp["params"]["holes_1_count"]["value"] == 6 and errors("component.schema.json", comp) == []
    assert comp["params"]["segment_1_diameter_mm"]["value"] == 100


def test_invalid_model_is_not_measured(tmp_path):
    bad = tmp_path / "bad.step"
    bad.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n", encoding="utf-8")
    with pytest.raises(M.GeometryInvalid):
        M.measure(bad)


@pytest.mark.freecad
def test_freecad_geometry_check():
    c = M.check_geometry(LS101)
    assert c["checked"] and c["valid"], c


def test_kind_proposal_is_checked(ls101):
    ok = M.check_kind({"part_kind": "shaft", "reason": "细长回转体",
                       "ports": [{"id": "bearing_left", "feature": "外圆 / 轴段 Ø12，长 10.0"},
                                 {"id": "bad", "feature": "Ø13 轴段"}]}, ls101)
    assert ok["part_kind"] == "shaft" and [p["id"] for p in ok["ports"]] == ["bearing_left"] and ok["rejected"]
    assert M.check_kind({"part_kind": "spindle"}, ls101)["part_kind"] is None
    req = M.kind_request(ls101, "上轴", model="m")
    assert "Ø16" in req["user"] and req["tool"]["name"] == "propose_part_kind"
