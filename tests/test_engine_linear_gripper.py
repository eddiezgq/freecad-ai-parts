"""直线模组与抓手的校验和选件（engine/linear_module.py、engine/gripper.py，ADR-0129 129.3，ADR-0115 44.5.4）。

标准题按手算核对；案例 B 一题用零件库里的费斯托与施迈茨。不联网、不调用 AI。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import gripper as GR
from engine import linear_module as LM

ROOT = Path(__file__).parents[1]


def _pv(v, condition=None):
    out = {"value": v, "source": {"doc": "src-test-fixture", "page": 1}, "method": "extracted", "confidence": 1.0, "reviewed": False}
    if condition:
        out["condition"] = condition
    return out


def axis(**params):
    base = {"drive_type": "belt", "max_stroke_mm": 2000, "max_speed_m_s": 5, "max_accel_m_s2": 50, "max_thrust_n": 350,
            "mass_kg": 3.0, "mass_per_10mm_stroke_kg": 0.062, "force_lateral_n": 3050, "force_normal_n": 3050,
            "moment_roll_nm": 36, "moment_pitch_nm": 97, "moment_yaw_nm": 97, "repeatability_mm": 0.08}
    base.update(params)
    return {"id": "test.linear_module.synth.ax", "category": "linear_module",
            "params": {k: _pv(v) for k, v in base.items() if v is not None}}


REQ = {"stroke_mm": 1600, "speed_m_s": 2.5, "accel_m_s2": 12.5, "thrust_n": 100, "safety_factor": 1.2,
       "force_normal_n": 30, "moment_pitch_nm": 9.7, "moment_roll_nm": 0}


def _st(r):
    return {c["check"]: c["status"] for c in r["checks"]}


def test_axis_checks_by_hand():
    r = LM.check(REQ, axis())
    assert _st(r) == {"L1": "pass", "L2": "pass", "L3": "pass", "L4": "pass", "L5": "pass", "L6": "not_applicable"}
    l5 = next(c for c in r["checks"] if c["check"] == "L5")
    # fv = 30×1.2/3050 + 9.7×1.2/97 = 0.011803 + 0.12 = 0.131803
    assert l5["measured"] == pytest.approx(30 * 1.2 / 3050 + 9.7 * 1.2 / 97)
    l4 = next(c for c in r["checks"] if c["check"] == "L4")
    assert l4["measured"] == pytest.approx(120) and l4["limit"] == 350
    assert r["mass_kg"] == pytest.approx(3.0 + 0.062 * 160)                 # 选定行程 1600 mm：3.0 + 0.062 × 160 = 12.92 kg


def test_axis_failures_and_unknowns():
    assert _st(LM.check(REQ, axis(max_stroke_mm=1500)))["L1"] == "fail"
    assert _st(LM.check(REQ, axis(max_speed_m_s=2)))["L2"] == "fail"
    assert _st(LM.check(REQ, axis(max_thrust_n=100)))["L4"] == "fail"       # 100 × 1.2 = 120 > 100
    assert _st(LM.check(dict(REQ, moment_pitch_nm=97), axis()))["L5"] == "fail"   # 97×1.2/97 > 1
    st = _st(LM.check(REQ, axis(max_accel_m_s2=None, moment_pitch_nm=None)))
    assert st["L3"] == "unknown" and st["L5"] == "unknown"                    # 厂商没给的不判通过
    r = LM.check(REQ, axis(mass_per_10mm_stroke_kg=None))
    assert r["mass_kg"] is None
    fixed = axis(max_stroke_mm=None, stroke_mm=1600, mass_per_10mm_stroke_kg=None, mass_kg=9.0)
    r = LM.check(REQ, fixed)
    assert _st(r)["L1"] == "pass" and r["mass_kg"] == 9.0


def test_candidates_lightest_passing_first():
    light = axis(mass_kg=1.0)
    light["id"] = "test.linear_module.synth.light"
    slow = axis(mass_kg=0.5, max_speed_m_s=1)
    slow["id"] = "test.linear_module.synth.slow"
    cs = LM.candidates(REQ, [axis(), light, slow])
    assert [c["component"] for c in cs] == ["test.linear_module.synth.light", "test.linear_module.synth.ax"]
    assert [r["component"] for r in LM.rejected(REQ, [axis(), light, slow])] == ["test.linear_module.synth.slow"]


def grip(gid, **params):
    return {"id": f"test.gripper.synth.{gid}", "category": "gripper", "params": {k: _pv(*v) if isinstance(v, tuple) else _pv(v)
                                                                                  for k, v in params.items()}}


def test_gripping_force_by_hand():
    req = {"part_mass_kg": 0.1, "accel_m_s2": 12.5, "material": "布料"}
    need = 0.1 * (9.80665 + 12.5) * 2                                     # = 4.46133 N
    assert GR.required_force(req) == pytest.approx(need)
    assert GR.required_force(dict(req, count=4)) == pytest.approx(need / 4)
    r = GR.check(req, grip("cup", gripper_type="suction_cup", holding_force_n=(4.41, "光滑表面理论值")))
    assert _st(r)["G1"] == "fail"
    r = GR.check(req, grip("cup2", gripper_type="suction_cup", holding_force_n=(9.81, "光滑表面理论值")))
    assert _st(r)["G1"] == "pass" and "光滑表面理论值" in r["checks"][0]["message"] and r["overall"] == "unknown"
    r = GR.check(req, grip("needle", gripper_type="needle", needle_count=4))
    assert _st(r)["G1"] == "unknown" and "针刺抓手" in r["checks"][0]["message"]       # 不按针数估
    r = GR.check(req, grip("n2", gripper_type="needle", suitable_materials=["布料", "纤维毡"]))
    assert _st(r)["G2"] == "pass"
    assert _st(r)["G3"] == "unknown"                                     # 分层没有公开数据


def test_case_b_selection_from_the_library():
    """案例 B：X 轴 1600 mm、2.5 m/s、12.5 m/s²——丝杠型全不过（最高 2 m/s），同步带型里最轻的通过；
    抓手按类型各列一个：针刺抓手（保持力待确认）与平吸盘（够 4.46 N 的最小一种）"""
    comps = [json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "data" / "library").glob("*/*.json")]
    cs = LM.candidates(REQ, comps)
    assert cs and all("-tb-" in c["component"] for c in cs)
    assert cs[0]["component"] == "linear_module.festo-se-co-kg.egc-80-tb-kf-gk"     # 50、70 的推力 50、100 N < 100 × 1.2 N
    assert all(_st(r)["L2"] == "fail" for r in LM.rejected(REQ, comps) if "-bs-" in r["component"])
    table = {r["type"]: r for r in GR.compare({"part_mass_kg": 0.1, "accel_m_s2": 12.5, "material": "布料"}, comps)}
    assert table["needle"]["component"] == "gripper.j-schmalz-gmbh.sng-m-4-0.8" and table["needle"]["overall"] == "unknown"
    assert table["suction_cup"]["component"] == "gripper.j-schmalz-gmbh.spf-15"     # SPF 10 只有 4.41 N
