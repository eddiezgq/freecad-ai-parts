"""校验引擎：框架与接口校验 C1–C3（issue #49，ADR-0025）。"""

from __future__ import annotations

import copy

import pytest
from engine_helpers import CASES, FIXTURES, assert_golden, case, case_by_id, edited, port, resolver

from engine.checks_interface import c1, c2, c3
from engine.result import FAIL, NA, PASS, UNKNOWN, WARN, CheckResult, Finding, overall, worst
from engine.system import PortRef, SystemError_, load_system
from engine.values import capacity, nominal, span

M400 = "test.servo_motor.test-vendor.m400"
R20 = "test.reducer.test-vendor.r20-100"


def _sys(cid="valid/m400-r20-d400", overrides=None, edit=None):
    s = copy.deepcopy(case_by_id(cid)["system"])
    if edit:
        edit(s)
    return load_system(s, resolver(overrides))


def _statuses(sys_):
    return {r.check: r.status for r in (c1(sys_), c2(sys_), c3(sys_))}


# ---------------------------------------------------------------- 框架


def test_worst_and_overall():
    assert worst([PASS, WARN, UNKNOWN]) == UNKNOWN
    assert worst([PASS, FAIL, UNKNOWN]) == FAIL
    assert worst([NA, NA]) == NA and worst([]) == NA
    rs = [CheckResult("C1", [Finding(PASS, "")]), CheckResult("C8")]
    assert overall(rs) == PASS
    rs.append(CheckResult("C6", [Finding(WARN, "")]))
    assert overall(rs) == WARN


def test_result_dict_format():
    r = CheckResult("C4", [Finding(PASS, "ok", ["motor.shaft"], 0.92, 1.27, "N*m")])
    d = r.to_dict()
    assert d["check"] == "C4" and d["status"] == "pass" and d["unit"] == "N*m"
    assert d["margin_ratio"] == pytest.approx((1.27 - 0.92) / 1.27)
    assert "findings" not in d
    na = CheckResult("C8", [], "需求未给负载惯量").to_dict()
    assert na == {"check": "C8", "status": "not_applicable", "message": "需求未给负载惯量"}
    multi = CheckResult("C2", [Finding(PASS, "a"), Finding(FAIL, "b")]).to_dict()
    assert multi["message"] == "b" and len(multi["findings"]) == 2


def test_values():
    assert capacity({"value": 3}) == 3 and capacity({"min": 2, "max": 5}) == 2 and capacity({"nominal": 4}) == 4
    assert capacity(None) is None and capacity({"value": "x"}) is None and capacity({"value": True}) is None
    assert nominal({"min": 1, "max": 2}) is None and nominal({"nominal": 14}) == 14
    assert span({"min": 200, "max": 240}) == (200, 240) and span({"value": 48}) == (48, 48)
    assert span({"min": 200}) is None


def test_load_system_errors():
    s = copy.deepcopy(case_by_id("valid/m400-r20-d400")["system"])
    with pytest.raises(SystemError_, match="找不到组件"):
        load_system({**s, "components": [*s["components"], {"instance": "x", "component": "test.drive.none.x"}]},
                    resolver())
    with pytest.raises(SystemError_, match="实例名重复"):
        load_system({**s, "components": [*s["components"], s["components"][0]]}, resolver())
    with pytest.raises(SystemError_, match="端口不存在"):
        load_system({**s, "connections": [{"a": "motor.nope", "b": "reducer.input_bore"}]}, resolver())
    with pytest.raises(SystemError_, match="重复连接"):
        load_system({**s, "connections": [*s["connections"], s["connections"][0]]}, resolver())


# ---------------------------------------------------------------- golden


@pytest.mark.parametrize("path", CASES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_golden_c1_c3(path):
    sys_ = load_system(case(path)["system"], resolver())
    assert_golden(path, _statuses(sys_))


# ---------------------------------------------------------------- C1


def test_c1_direction_and_motion():
    over = edited(R20, lambda c: port(c, "input_bore").update(dir="out"))
    r = c1(_sys(overrides=over))
    assert r.status == FAIL and "方向" in r.to_dict()["message"]
    over = edited(R20, lambda c: port(c, "input_bore").update(motion="stationary"))
    assert "运动方式" in c1(_sys(overrides=over)).to_dict()["message"]


def test_c1_no_connections():
    assert c1(_sys(edit=lambda s: s.update(connections=[]))).status == NA


# ---------------------------------------------------------------- C2


def test_c2_missing_connection_fails():
    def drop(s):
        s["connections"] = [c for c in s["connections"] if c["a"] != "motor.shaft"]
    r = c2(_sys(edit=drop))
    assert r.status == FAIL and "缺少电机轴" in r.to_dict()["message"]


def test_c2_missing_connection_through_adapter_ok_and_broken():
    assert c2(_sys("valid/m200-adapters-r25-d400")).status == PASS

    def drop(s):
        s["connections"] = [c for c in s["connections"] if c["a"] != "sleeve.outer"]
    assert c2(_sys("valid/m200-adapters-r25-d400", edit=drop)).status == FAIL


def test_c2_not_applicable_without_motor_and_reducer():
    def only_drive(s):
        s["components"] = [c for c in s["components"] if c["instance"] == "drive"]
        s["connections"] = []
    assert c2(_sys(edit=only_drive)).status == NA


def test_c2_fit_not_in_table_warns():
    over = edited(R20, lambda c: port(c, "input_bore")["spec"]["fit"].update(value="F8"))
    r = c2(_sys(overrides=over))
    assert r.status == WARN and "不在配合表内" in r.to_dict()["message"]


def test_c2_missing_fit_unknown():
    over = edited(M400, lambda c: port(c, "shaft")["spec"].pop("fit"))
    assert c2(_sys(overrides=over)).status == UNKNOWN


def test_c2_clamping_matrix_fail():
    over = edited(M400, lambda c: port(c, "shaft")["spec"]["feature"].update(value="plain"))
    r = c2(_sys(overrides=over))
    assert r.status == FAIL


def _bearing(kind="deep_groove", inner_d=14, with_clamping=False, inner_motion="rotating"):
    pv = lambda v: {"value": v, "source": {"doc": "src-test-fixture", "page": 1}, "method": "manual",
                    "confidence": 1, "reviewed": True}
    inner = {"diameter_mm": pv(inner_d), "fit_system": pv("bearing"), "fit": pv("P0"), "feature": pv("plain")}
    if with_clamping:
        inner["clamping"] = pv("press_fit")
    return {
        "id": "test.bearing.test-vendor.b1", "category": "bearing", "vendor": "Test Vendor", "model": "B1",
        "status": "active", "license": "params-only",
        "params": {"bearing_kind": pv(kind), "width_mm": pv(8)},
        "ports": [
            {"id": "inner", "type": "mechanical.cyl_female", "dir": "bidir", "motion": inner_motion,
             "frame": {"origin_mm": [0, 0, 0], "axis": [0, 0, 1]}, "spec": inner},
            {"id": "outer", "type": "mechanical.cyl_male", "dir": "bidir", "motion": "stationary",
             "frame": {"origin_mm": [0, 0, 0], "axis": [0, 0, 1]},
             "spec": {"diameter_mm": pv(35), "fit_system": pv("bearing"), "fit": pv("P0"), "feature": pv("plain")}},
        ],
        "envelope": {"parts": [{"shape": "cylinder", "z_start_mm": 0, "length_mm": pv(8), "diameter_mm": pv(35)}]},
    }


def _shaft_bearing_system(bearing, shaft_fit="h5"):
    def edit(c):
        port(c, "shaft")["spec"]["fit"]["value"] = shaft_fit
        port(c, "shaft")["motion"] = port(bearing, "inner")["motion"]  # 轴与内圈同转或同静止
    over = edited(M400, edit)
    over["test.bearing.test-vendor.b1"] = bearing
    s = {"id": "x", "requirement": {"output_torque_cont_nm": 1, "output_speed_rpm": 1},
         "components": [{"instance": "motor", "component": M400},
                        {"instance": "bearing", "component": "test.bearing.test-vendor.b1"}],
         "connections": [{"a": "motor.shaft", "b": "bearing.inner"}]}
    return load_system(s, resolver(over))


def test_c2_bearing_fit_table():
    # 内圈旋转、深沟球轴承、14 mm：轻载推荐 h5，正常载荷推荐 js5 → h5 与 js5 均 pass
    assert c2(_shaft_bearing_system(_bearing(), "h5")).findings[1].status == PASS
    assert c2(_shaft_bearing_system(_bearing(), "js5")).findings[1].status == PASS
    assert c2(_shaft_bearing_system(_bearing(), "g6")).findings[1].status == WARN
    # 交叉滚子轴承不在表内 → unknown
    assert c2(_shaft_bearing_system(_bearing("cross_roller"), "h5")).findings[1].status == UNKNOWN
    # 内圈静止：推荐 g6、h6
    assert c2(_shaft_bearing_system(_bearing(inner_motion="stationary"), "g6")).findings[1].status == PASS


def test_c2_bearing_without_clamping_skips_matrix():
    r = c2(_shaft_bearing_system(_bearing(), "h5"))
    assert not any("紧固" in f.message for f in r.findings)
    r = c2(_shaft_bearing_system(_bearing(with_clamping=True), "h5"))
    assert any("紧固" in f.message for f in r.findings)


# ---------------------------------------------------------------- C3


def test_c3_pcd_tolerance_boundary():
    for delta, want in ((0.05, PASS), (0.06, FAIL)):
        over = edited(R20, lambda c, d=delta: port(c, "motor_flange")["spec"]["pcd_mm"].update(value=70 + d))
        assert c3(_sys(overrides=over)).findings[0].status == want, delta


def test_c3_hole_count_and_clearance():
    over = edited(R20, lambda c: port(c, "motor_flange")["spec"]["hole_count"].update(value=6))
    assert c3(_sys(overrides=over)).status == FAIL
    # M5 中等系列间隙孔 5.5：5.5 刚好通过，5.4 不通过
    for hole, want in ((5.5, PASS), (5.4, FAIL)):
        over = edited(M400, lambda c, h=hole: port(c, "mount_flange")["spec"]["hole_diameter_mm"].update(value=h))
        assert c3(_sys(overrides=over)).findings[2].status == want, hole


def test_c3_both_threaded_warns():
    def threaded(c):
        spec = port(c, "mount_flange")["spec"]
        spec["hole_kind"]["value"] = "threaded"
        spec["thread"] = copy.deepcopy(spec.pop("hole_diameter_mm"))
        spec["thread"]["value"] = "M5"
    assert c3(_sys(overrides=edited(M400, threaded))).findings[2].status == WARN


def test_c3_pilot_rules():
    over = edited(M400, lambda c: port(c, "mount_flange")["spec"]["pilot_kind"].update(value="female"))
    assert c3(_sys(overrides=over)).findings[3].status == FAIL
    over = edited(M400, lambda c: port(c, "mount_flange")["spec"].pop("pilot_diameter_mm"))
    assert c3(_sys(overrides=over)).findings[3].status == WARN
    over = edited(M400, lambda c: port(c, "mount_flange")["spec"]["pilot_diameter_mm"].update(value=49))
    assert c3(_sys(overrides=over)).findings[3].status == FAIL


def test_c3_missing_flange_connection():
    def drop(s):
        s["connections"] = [c for c in s["connections"] if c["a"] != "motor.mount_flange"]
    r = c3(_sys(edit=drop))
    assert r.status == FAIL and "缺少电机法兰" in r.to_dict()["message"]


def test_portref():
    assert str(PortRef.parse("motor.shaft")) == "motor.shaft"
    assert set(FIXTURES)  # golden 组件已加载
