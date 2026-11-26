"""闭环机构的等效惯量按 J(θ) = 2T/θ̇² 在一转上统计。

《多体动力学》书第 42 章线索第 72 条（问渠 CAD 0.3.9 细则）：平缝机针杆机构（C-LNK-SLIDER，曲柄 17.5 mm、连杆 60 mm、宽 8 mm、
厚 5 mm）原来“最大等效惯量”取锁住其他关节的对角元，偏大 4.8 倍；书里 J 在 2.52e-6–1.86e-5、一转平均 1.01e-5 kg·m²。
"""
import pytest

import analysis

P = {"crank_m": 0.0175, "rod_m": 0.06, "link_width_m": 0.008, "link_thickness_m": 0.005}


def test_lockstitch_inertia_range():
    res = analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-LNK-SLIDER", "params": P}, "duration_s": 0.06,
                               "sample_hz": 5000, "drives": [{"joint": "crank", "kind": "speed", "value": 5000}]})
    d = res["data"]["drives"][0]
    assert d["inertia_min_kgm2"] == pytest.approx(2.52e-6, rel=0.01)
    assert d["inertia_max_kgm2"] == pytest.approx(1.86e-5, rel=0.01)
    assert d["inertia_mean_kgm2"] == pytest.approx(1.01e-5, rel=0.01)
    assert "J(θ)" in d["inertia_def"]


def test_open_chain_states_definition():
    res = analysis.run("mbd", {"model": {"kind": "arm", "base_height_mm": 100, "links": [{"length_mm": 300, "mass_kg": 2}]},
                               "duration_s": 0.2, "sample_hz": 100, "drives": [{"joint": "j1", "kind": "hold"}]})
    assert any("对角元" in x for x in res["limitations"])
