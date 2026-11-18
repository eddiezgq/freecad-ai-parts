"""阶梯轴设计 → 三维模型 → 测量回读 → 二维图、BOM（ADR-0100 42.3）。"""

from __future__ import annotations

import os

import pytest

from assist import shaft_model as M
from tests.test_shaft_design import B6201, get

# 书中 LS-101 的轴段（已补轴承位尺寸的形式），台阶圆角 0.5
LS101 = [{"role": "crank_seat", "d": 10, "L": 22, "r": 0.5}, {"role": "bearing_seat", "d": 12, "L": 10, "r": 0.5, "bearing": B6201},
         {"role": "body", "d": 16, "L": 215, "r": 0.5}, {"role": "bearing_seat", "d": 12, "L": 10, "r": 0.5, "bearing": B6201},
         {"role": "pulley_seat", "d": 10, "L": 40}]


def _need_gmsh():
    if os.environ.get("CI"):
        import gmsh  # noqa: F401
        return
    pytest.importorskip("gmsh")


def test_runs_merge_same_diameter_and_place_fillets():
    segs = [{"d": 12, "L": 22, "r": 0.5}, {"d": 12, "L": 10, "r": 0.5}, {"d": 16, "L": 100, "r": 1.0}, {"d": 12, "L": 20}]
    rs = M.runs(segs)
    assert [(r["d"], r["z0"], r["z1"]) for r in rs] == [(12, 0, 32), (16, 32, 132), (12, 132, 152)]
    assert (rs[0]["r_right"], rs[2]["r_left"], rs[1]["r_left"], rs[1]["r_right"]) == (0.5, 1.0, 0.0, 0.0)
    exp = M.expected_faces(segs)
    assert exp[0]["length_mm"] == 31.5 and exp[2]["start_mm"] == 133.0 and exp[2]["length_mm"] == 19.0


def test_runs_refuse_missing_or_oversized_fillet():
    with pytest.raises(M.ModelError, match="没有圆角"):
        M.runs([{"d": 10, "L": 5}, {"d": 12, "L": 5}])
    with pytest.raises(M.ModelError, match="不小于台阶高度"):
        M.runs([{"d": 10, "L": 5, "r": 1.0}, {"d": 12, "L": 5}])


def test_compare_flags_each_difference():
    exp = [{"diameter_mm": 12.0, "start_mm": 0.0, "length_mm": 31.5}, {"diameter_mm": 16.0, "start_mm": 32.0, "length_mm": 100.0}]
    ok = M.compare(exp, [dict(e) for e in exp])
    assert ok["overall"] == "pass" and not ok["problems"]
    bad = M.compare(exp, [dict(exp[0]), {**exp[1], "diameter_mm": 16.02}])
    assert bad["overall"] == "fail" and "第 2 段" in bad["problems"][0]
    assert M.compare(exp, exp[:1])["overall"] == "fail"                  # 少一段也不通过


def test_ls101_model_reads_back_exactly(tmp_path):
    """书中 LS-101 加 R0.5 台阶圆角建模，回读逐段一致，质量 = 体积 × 45 钢密度"""
    _need_gmsh()
    step = M.build_step(LS101, tmp_path / "ls101.step")
    rb = M.readback(LS101, step, "45-QT")
    assert rb["overall"] == "pass", rb["problems"]
    assert len(rb["rows"]) == 5 and all(r["ok"] for r in rb["rows"])
    m = rb["measurement"]
    plain = sum(3.141592653589793 * s["d"] ** 2 / 4 * s["L"] for s in LS101)
    assert abs(m["volume_mm3"] - plain) / plain < 0.002                    # 圆角只添一点体积
    assert abs(m["mass_kg"] - m["volume_mm3"] * 1e-9 * m["density_kg_m3"]) < 1e-3


def test_drawing_and_bom(tmp_path):
    _need_gmsh()
    step = M.build_step(LS101, tmp_path / "ls101.step")
    rb = M.readback(LS101, step, "45-QT")
    svg = M.drawing_svg(LS101, title="上轴", drawing_no="T-1", material="45-QT")
    for t in ("Ø10", "Ø12", "Ø16", ">22<", ">215<", ">40<", ">297<", "z 22 R0.5"):
        assert t in svg
    rows = M.bom(LS101, rb, drawing_no="T-1", name="上轴", get=get)
    assert rows[0]["kind"] == "custom_part" and rows[0]["mass_kg"] == rb["measurement"]["mass_kg"]
    assert rows[1]["component"] == B6201 and rows[1]["qty"] == 2


def test_generate_refuses_unpassed_design(tmp_path):
    with pytest.raises(M.ModelError, match="没有通过"):
        M.generate({"status": "stuck", "rounds": []}, tmp_path, get)
