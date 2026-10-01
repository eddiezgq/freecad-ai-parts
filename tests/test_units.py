"""单位归一化测试（issue #26）。换算系数取自定义：1 kgf = 9.80665 N，1 in = 25.4 mm，1 lbf = 4.4482216152605 N。"""

import math

import pytest

from ingest.units import UnitError, normalize_param, standard_unit, to_standard


@pytest.mark.parametrize("value,unit,field,expected", [
    # 转动惯量
    (0.26, "kg·cm²", "rotor_inertia_kgm2", 0.26e-4),
    (0.26, "kg*cm^2", "rotor_inertia_kgm2", 0.26e-4),
    (0.26, "10^-4 kg·m²", "rotor_inertia_kgm2", 0.26e-4),
    (0.26, "×10⁻⁴ kg·m²", "rotor_inertia_kgm2", 0.26e-4),
    (2.6e-5, "kg·m²", "rotor_inertia_kgm2", 2.6e-5),
    (260, "g·cm²", "rotor_inertia_kgm2", 2.6e-5),
    # 扭矩
    (13, "kgf·cm", "rated_torque_nm", 13 * 0.0980665),
    (1300, "gf·cm", "rated_torque_nm", 1.3 * 0.0980665),
    (1270, "mN·m", "rated_torque_nm", 1.27),
    (127, "N·cm", "rated_torque_nm", 1.27),
    (1.27, "Nm", "rated_torque_nm", 1.27),
    (1.27, "N.m", "rated_torque_nm", 1.27),
    (10, "lbf·in", "rated_torque_nm", 10 * 4.4482216152605 * 0.0254),
    (0.5, "Nm/A", "torque_constant_nm_per_a", 0.5),
    # 转速
    (3000, "r/min", "rated_speed_rpm", 3000),
    (3000, "min⁻¹", "rated_speed_rpm", 3000),
    (3000, "min^-1", "rated_speed_rpm", 3000),
    (50, "r/s", "rated_speed_rpm", 3000),
    # 长度、质量、力、功率
    (1.0, "in", "diameter_mm", 25.4),
    (0.014, "m", "diameter_mm", 14),
    (900, "g", "mass_kg", 0.9),
    (1, "kgf", "dynamic_load_rating_n", 9.80665),
    (0.4, "kW", "rated_power_w", 400),
    # 角度、效率
    (60, "arcsec", "backlash_arcmin", 1),
    (1, "'", "lost_motion_arcmin", 1),
    (0.5, "°", "lost_motion_arcmin", 30),
    (70, "%", "efficiency_ratio", 0.7),
    (0.7, "", "efficiency_ratio", 0.7),
    # 电流：有效值不变，幅值除以 √2
    (2.8, "A", "rated_current_a", 2.8),
    (2.8, "Arms", "rated_current_a", 2.8),
    (12.0, "A(0-p)", "peak_current_a", 12 / math.sqrt(2)),
    (12.0, "Apk", "peak_current_a", 12 / math.sqrt(2)),
])
def test_conversions(value, unit, field, expected):
    assert to_standard(value, unit, field) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("unit,field", [
    ("foo", "mass_kg"),                 # 认不出
    ("kg", "diameter_mm"),              # 量纲不符
    ("%", "backlash_arcmin"),           # 无量纲但不是角度
    ("arcmin", "efficiency_ratio"),     # 角度不是比值
    ("Hz", "rated_speed_rpm"),          # 1/时间 但不是转速
    ("1/s", "rated_speed_rpm"),
    ("rpm", "frequency_hz"),
    ("A(0-p)", "rated_power_w"),        # 幅值写法只用于电流
])
def test_rejections(unit, field):
    with pytest.raises(UnitError):
        to_standard(1.0, unit, field)


def test_nm_means_nanometre_in_length_field_and_newton_metre_in_torque_field():
    assert to_standard(14_000_000, "nm", "diameter_mm") == pytest.approx(14)
    assert to_standard(1.27, "nm", "rated_torque_nm") == pytest.approx(1.27)


@pytest.mark.parametrize("field", ["mass", "rated_torque", "foo_xyz"])
def test_field_without_suffix_rejected(field):
    with pytest.raises(UnitError):
        standard_unit(field)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "3"])
def test_non_numeric_value_rejected(value):
    with pytest.raises(UnitError):
        to_standard(value, "kg", "mass_kg")


def test_suffix_longest_match():
    assert standard_unit("torsional_stiffness_nm_per_arcmin")[0] == "_nm_per_arcmin"
    assert standard_unit("rated_torque_nm")[0] == "_nm"
    assert standard_unit("dynamic_load_rating_n")[0] == "_n"


def _pv(**kw):
    base = {"source": {"doc": "src-test-fixture", "page": 3}, "method": "extracted", "confidence": 0.9,
            "reviewed": False}
    base.update(kw)
    return base


def test_normalize_param_converts_all_numbers_and_notes_original():
    pv = _pv(nominal=13, tol_upper=0.5, tol_lower=-0.5, condition="25 °C")
    out = normalize_param(pv, "kgf·cm", "rated_torque_nm")
    assert out["nominal"] == pytest.approx(13 * 0.0980665)
    assert out["tol_upper"] == pytest.approx(0.5 * 0.0980665)
    assert out["tol_lower"] == pytest.approx(-0.5 * 0.0980665)
    assert out["condition"] == "25 °C"
    assert "原单位 kgf·cm" in out["source"]["note"] and "nominal=13" in out["source"]["note"]
    assert pv["nominal"] == 13  # 不修改输入


def test_normalize_param_range_and_existing_note():
    pv = _pv(min=200, max=240)
    pv["source"]["note"] = "表 2"
    out = normalize_param(pv, "kV", "voltage_v")
    assert (out["min"], out["max"]) == (pytest.approx(200_000), pytest.approx(240_000))
    assert out["source"]["note"].startswith("表 2；原单位 kV")


def test_normalize_param_standard_unit_unchanged():
    pv = _pv(value=1.27)
    assert normalize_param(pv, "N·m", "rated_torque_nm") == pv


def test_normalize_param_leaves_strings_alone():
    pv = _pv(value="biss_c")
    assert normalize_param(pv, "", "efficiency_ratio") == pv
