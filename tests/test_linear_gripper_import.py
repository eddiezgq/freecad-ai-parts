"""直线模组与抓手的导入（ADR-0127 127.2）：抽取字段、包络、组装。不联网、不调用真实 AI。"""

from __future__ import annotations

from ingest.assemble import assemble, envelope
from ingest.llm_extract import CATEGORIES, targets


def _pv(value):
    return {"value": value, "source": {"doc": "src-test-fixture", "page": 1}, "method": "extracted", "confidence": 1.0,
         "reviewed": False}


def test_both_categories_are_extractable_with_standard_units():
    assert "linear_module" in CATEGORIES and "gripper" in CATEGORIES
    lm = {t.target: t for t, _ in targets("linear_module").values()}
    assert lm["params/max_speed_m_s"].unit == "m/s" and lm["params/max_accel_m_s2"].unit == "m/s**2"
    assert lm["params/mass_per_10mm_stroke_kg"].unit == "kg" and lm["params/drive_type"].enum
    assert "dims/base_length_mm" in lm and lm["params/max_speed_m_s"].key
    gr = {t.target: t for t, _ in targets("gripper").values()}
    assert gr["params/operating_pressure_mpa"].unit == "MPa" and gr["params/needle_count"].kind == "integer"
    assert "dims/base_length_mm" not in gr


def test_linear_module_envelope_any_stroke_is_labelled():
    parts, miss = envelope("linear_module", {"dims/base_length_mm": _pv(286), "dims/width_mm": _pv(82),
                                             "dims/height_mm": _pv(76.5)})
    assert not miss and parts[0]["length_mm"]["value"] == 286 and "选定行程后长度加行程" in parts[0]["label"]
    parts, _ = envelope("linear_module", {"dims/overall_length_mm": _pv(1900), "dims/base_length_mm": _pv(286),
                                          "dims/width_mm": _pv(82), "dims/height_mm": _pv(76.5)})
    assert parts[0]["length_mm"]["value"] == 1900 and parts[0]["label"] == "body"
    parts, miss = envelope("linear_module", {"dims/width_mm": _pv(82)})
    assert parts is None and "dims/height_mm" in miss and any("base_length_mm" in m for m in miss)


def test_gripper_envelope_cylinder_or_box():
    parts, _ = envelope("gripper", {"dims/overall_length_mm": _pv(70), "dims/outer_diameter_mm": _pv(30)})
    assert parts[0]["shape"] == "cylinder"
    parts, _ = envelope("gripper", {"dims/overall_length_mm": _pv(70), "dims/width_mm": _pv(30), "dims/height_mm": _pv(20)})
    assert parts[0]["shape"] == "box"
    parts, miss = envelope("gripper", {"dims/width_mm": _pv(30)})
    assert parts is None and miss == ["dims/overall_length_mm"]


def test_assemble_a_free_stroke_belt_axis_without_ports():
    values = {"params/drive_type": _pv("belt"), "params/max_stroke_mm": _pv(8500), "params/max_speed_m_s": _pv(5),
              "params/max_thrust_n": _pv(350), "params/mass_kg": _pv(3.0), "params/mass_per_10mm_stroke_kg": _pv(0.062),
              "dims/base_length_mm": _pv(286), "dims/width_mm": _pv(82), "dims/height_mm": _pv(76.5)}
    comp, problems, notes = assemble("linear_module", "Synth Motion", "TB-80", values, test=True)
    assert not problems, problems
    assert comp["id"] == "test.linear_module.synth-motion.tb-80" and comp["ports"] == []
    assert comp["params"]["max_stroke_mm"]["value"] == 8500 and not any("未用于包络" in n for n in notes)


def test_assemble_a_needle_gripper():
    values = {"params/gripper_type": _pv("needle"), "params/needle_count": _pv(4), "params/needle_diameter_mm": _pv(0.8),
              "params/mass_kg": _pv(0.08), "dims/overall_length_mm": _pv(60), "dims/outer_diameter_mm": _pv(30)}
    comp, problems, _ = assemble("gripper", "Synth Vac", "N-4", values, test=True)
    assert not problems, problems
    assert comp["category"] == "gripper" and "holding_force_n" not in comp["params"]
