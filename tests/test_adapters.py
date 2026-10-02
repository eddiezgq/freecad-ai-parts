"""按端口尺寸生成转接件（ADR-0041，issue #129）。纯函数测试，用虚构测试组件改尺寸构造输入。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from engine import adapters as ad
from engine.adapters import AdapterError
from engine.compose import compose_chain
from engine.validate import validate
from kb.validation import errors

FIX = Path(__file__).parent / "golden" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _pv(v):
    return {"value": v, "source": {"doc": "src-test-fixture", "page": 1}, "method": "manual", "confidence": 1,
            "reviewed": True}


def _set(comp: dict, port: str, **spec):
    p = next(p for p in comp["ports"] if p["id"] == port)
    for k, v in spec.items():
        if v is None:
            p["spec"].pop(k, None)
        else:
            p["spec"][k] = _pv(v)
    return comp


@pytest.fixture
def motor():
    return _set(_load("test.servo_motor.test-vendor.m400"), "shaft", diameter_mm=11, key_width_mm=4,
                usable_length_mm=25)


@pytest.fixture
def reducer():
    return _set(_load("test.reducer.test-vendor.r25-100"), "input_bore", diameter_mm=24, key_width_mm=8, depth_mm=30)


def _system(motor, reducer, sleeve=None, plate=None):
    parts = [("motor", motor), ("reducer", reducer)] + ([("sleeve", sleeve)] if sleeve else []) + \
        ([("plate", plate)] if plate else [])
    links = ([{"a": "motor.shaft", "b": "sleeve.inner"}, {"a": "sleeve.outer", "b": "reducer.input_bore"}]
             if sleeve else [{"a": "motor.shaft", "b": "reducer.input_bore"}])
    links += ([{"a": "motor.mount_flange", "b": "plate.motor_side"}, {"a": "plate.reducer_side", "b": "reducer.motor_flange"}]
              if plate else [{"a": "motor.mount_flange", "b": "reducer.motor_flange"}])
    lookup = {c["id"]: c for _, c in parts}
    req = {"statement": "t", "output_torque_cont_nm": 10, "output_speed_rpm": 20, "safety_factor": 1.2}
    return {"id": "s", "requirement": req, "components": [{"instance": n, "component": c["id"]} for n, c in parts],
            "connections": links}, lookup


def _check(report, cid):
    return next(c for c in report["checks"] if c["check"] == cid)


# ---------------------------------------------------------------- 轴套


def test_sleeve_is_valid_and_passes_c2(motor, reducer):
    s = ad.sleeve(motor, reducer)
    assert errors("component.schema.json", s) == []
    assert s["id"] == "adapter.fap-generated.sl-11-24-25-k4-k8" and s["license"] == "open"
    spec = {p["id"]: {k: v["value"] for k, v in p["spec"].items()} for p in s["ports"]}
    assert spec["inner"] == {"diameter_mm": 11, "fit": "H7", "feature": "keyed", "clamping": "key", "depth_mm": 25,
                             "key_width_mm": 4}
    assert spec["outer"] == {"diameter_mm": 24, "fit": "h6", "feature": "keyed", "usable_length_mm": 25,
                             "key_width_mm": 8}
    assert all(v["method"] == "computed" and v["source"]["formula"] for v in s["params"].values())
    assert s["params"]["mass_kg"]["value"] == pytest.approx(7850 * 3.14159265 / 4 * (24**2 - 11**2) * 25e-9, rel=1e-3)
    system, lookup = _system(motor, reducer, sleeve=s)
    c2 = _check(validate(system, lookup.get), "C2")
    assert c2["status"] == "pass", c2


def test_sleeve_plain_shaft_uses_clamp_ring(motor, reducer):
    _set(motor, "shaft", feature="plain", key_width_mm=None)
    s = ad.sleeve(motor, reducer)
    inner = next(p for p in s["ports"] if p["id"] == "inner")["spec"]
    assert inner["clamping"]["value"] == "clamp_ring" and "key_width_mm" not in inner
    system, lookup = _system(motor, reducer, sleeve=s)
    assert _check(validate(system, lookup.get), "C2")["status"] == "pass"


def test_sleeve_press_fit_bore_gets_transition_fit(motor, reducer):
    _set(reducer, "input_bore", clamping="press_fit", feature="plain", key_width_mm=None)
    s = ad.sleeve(motor, reducer)
    assert next(p for p in s["ports"] if p["id"] == "outer")["spec"]["fit"]["value"] == "k6"
    system, lookup = _system(motor, reducer, sleeve=s)
    assert _check(validate(system, lookup.get), "C2")["status"] == "pass"


def test_sleeve_length_from_whichever_is_known(motor, reducer):
    _set(motor, "shaft", usable_length_mm=None)
    assert ad.sleeve(motor, reducer)["params"]["length_mm"]["value"] == 30


@pytest.mark.parametrize(("motor_spec", "bore_spec", "msg"), [
    ({"diameter_mm": 24}, {}, "不小于孔径"),
    ({"diameter_mm": 30}, {}, "不小于孔径"),
    ({"diameter_mm": 20}, {}, "壁厚"),  # 壁厚 2 mm < 1.5 + 0.6 × 8
    ({"feature": "spline"}, {}, "只支持"),
    ({"usable_length_mm": None}, {"depth_mm": None}, "长度"),
    ({"key_width_mm": None}, {}, "键宽"),
    ({"diameter_mm": None}, {}, "缺少"),
])
def test_sleeve_refusals(motor, reducer, motor_spec, bore_spec, msg):
    _set(motor, "shaft", **motor_spec)
    _set(reducer, "input_bore", **bore_spec)
    with pytest.raises(AdapterError, match=msg):
        ad.sleeve(motor, reducer)


# ---------------------------------------------------------------- 转接板


def test_plate_is_valid_and_passes_c3(motor, reducer):
    p = ad.plate(motor, reducer)
    assert errors("component.schema.json", p) == []
    spec = {x["id"]: {k: v["value"] for k, v in x["spec"].items()} for x in p["ports"]}
    assert spec["motor_side"] == {"pcd_mm": 70, "hole_count": 4, "hole_kind": "threaded", "thread": "M5",
                                  "pilot_kind": "female", "pilot_diameter_mm": 50, "pilot_fit": "H7"}
    assert spec["reducer_side"]["hole_kind"] == "through" and spec["reducer_side"]["hole_diameter_mm"] == 6.6
    assert spec["reducer_side"]["pilot_kind"] == "male" and spec["reducer_side"]["pilot_fit"] == "h7"
    assert p["params"]["length_mm"]["value"] == 10  # max(8, 1.5 × 5 + 2) 向上取整
    width = p["envelope"]["parts"][0]["width_mm"]["value"]
    assert width % 2 == 0 and width >= 90 + 6.6 + 6
    system, lookup = _system(motor, reducer, plate=p)
    c3 = _check(validate(system, lookup.get), "C3")
    assert c3["status"] == "pass", c3


def test_plate_rotates_colliding_holes(motor, reducer):
    _set(reducer, "motor_flange", pcd_mm=72)  # 与电机侧 70 mm 的孔几乎重合
    p = ad.plate(motor, reducer)
    r = next(x for x in p["ports"] if p and x["id"] == "reducer_side")["spec"]
    assert r["hole_angle_offset_deg"]["value"] == 45


def test_plate_refuses_unresolvable_collision(motor, reducer):
    _set(motor, "mount_flange", hole_count=16)  # 孔距约 13.7 mm，转半个孔距后仍不够净距
    _set(reducer, "motor_flange", pcd_mm=72, hole_count=16)
    with pytest.raises(AdapterError, match="碰撞"):
        ad.plate(motor, reducer)


@pytest.mark.parametrize(("side", "spec", "msg"), [
    ("mount_flange", {"hole_diameter_mm": None}, "缺少孔径"),
    ("mount_flange", {"hole_diameter_mm": 1.0}, "太小"),
    ("motor_flange", {"thread": "M7"}, "不在 ISO 273"),
    ("motor_flange", {"pcd_mm": None}, "缺少分度圆"),
    ("motor_flange", {"pilot_diameter_mm": None}, "止口数据不全"),
])
def test_plate_refusals(motor, reducer, side, spec, msg):
    _set(motor if side == "mount_flange" else reducer, side, **spec)
    with pytest.raises(AdapterError, match=msg):
        ad.plate(motor, reducer)


def test_plate_without_pilots(motor, reducer):
    _set(motor, "mount_flange", pilot_kind=None, pilot_diameter_mm=None)
    _set(reducer, "motor_flange", pilot_kind=None, pilot_diameter_mm=None)
    p = ad.plate(motor, reducer)
    assert all("pilot_kind" not in x["spec"] for x in p["ports"])


def test_generation_is_deterministic(motor, reducer):
    assert ad.sleeve(motor, reducer) == ad.sleeve(copy.deepcopy(motor), copy.deepcopy(reducer))
    assert ad.plate(motor, reducer) == ad.plate(copy.deepcopy(motor), copy.deepcopy(reducer))


# ---------------------------------------------------------------- 求解


def test_compose_uses_generated_adapters_only_when_asked(motor, reducer):
    drive = _load("test.drive.test-vendor.d400")
    req = {"statement": "t", "output_torque_cont_nm": 10, "output_speed_rpm": 20, "safety_factor": 1.2}
    library = [motor, reducer, drive]
    assert compose_chain(req, library, include_unknown=True) == []
    cands = compose_chain(req, library, include_unknown=True, generate_adapters=True)
    assert cands
    first = cands[0].to_dict()
    gen = {c["id"] for c in first["generated_components"]}
    assert gen == {ad.sleeve(motor, reducer)["id"], ad.plate(motor, reducer)["id"]}
    used = {c["component"] for c in first["system"]["components"]}
    assert gen <= used and cands[0].adapters == 2
    for cid in ("C2", "C3"):
        assert _check(first["report"], cid)["status"] == "pass"
    again = compose_chain(req, library, include_unknown=True, generate_adapters=True)
    assert [c.to_dict() for c in again] == [c.to_dict() for c in cands]


def test_library_adapter_preferred_over_generated():
    motor, reducer = _load("test.servo_motor.test-vendor.m200"), _load("test.reducer.test-vendor.r25-100")
    library = [motor, reducer, _load("test.drive.test-vendor.d200"), _load("test.adapter.test-vendor.sleeve-11-19"),
               _load("test.adapter.test-vendor.plate-70-90")]
    req = {"statement": "t", "output_torque_cont_nm": 10, "output_speed_rpm": 20, "safety_factor": 1.2}
    plain = compose_chain(req, library, include_unknown=True)
    gen = compose_chain(req, library, include_unknown=True, generate_adapters=True)
    assert [c.to_dict() for c in gen] == [c.to_dict() for c in plain]
    assert all("generated_components" not in c.to_dict() for c in gen)
