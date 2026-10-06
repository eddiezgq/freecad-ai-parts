"""就地补数据（M9 第二步）：可补字段、参数值组成、写入企业库后校验结论随之变化。只用临时目录。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from freecad_addon.core import fill
from freecad_addon.core.live_check import check
from kb.enterprise import EnterpriseLibrary
from kb.library import JsonLibrary, LayeredLibrary

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = JsonLibrary(ROOT / "data" / "library")
M = "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"
R = "reducer.harmonic-drive-llc.csf-25-100-2uh"
REQ = json.loads((ROOT / "examples" / "joint-real-requirement.json").read_text(encoding="utf-8"))
LAYOUT = {"instances": [{"instance": "motor", "component": M}, {"instance": "reducer", "component": R}],
          "connections": [{"a": "motor.mount_flange", "b": "reducer.motor_flange"},
                          {"a": "motor.shaft", "b": "reducer.input_bore"}]}


def row(comp, target):
    return next(r for r in fill.fields(comp) if r.target == target)


def test_fields_put_focus_port_and_missing_first():
    rows = fill.fields(PUBLIC.get(R), {"motor_flange"})
    first = [r.target for r in rows[:6]]
    assert all(t.startswith("ports/motor_flange/") for t in first)
    assert rows[0].missing and rows[0].configurable_port
    assert "params/efficiency_ratio" not in {r.target for r in rows}  # 有效率曲线
    assert not any(r.target.startswith("dims/") for r in rows)
    present = [r for r in rows if not r.missing]
    assert present and rows.index(present[0]) > max(rows.index(r) for r in rows if r.missing)
    pcd = row(PUBLIC.get(M), "ports/mount_flange/pcd_mm")
    assert pcd.current == "70" and pcd.title() == "mount_flange · 分度圆直径（mm）"


def test_build_pv_forms_and_errors():
    comp = PUBLIC.get(R)
    pcd = row(comp, "ports/motor_flange/pcd_mm")
    kw = {"doc": "src-ent-a", "page": 3, "quote": "PCD 70", "actor": "张工", "today": "2026-10-06"}
    pv = fill.build_pv(pcd, "70", **kw)
    assert pv == {"value": 70.0, "method": "manual", "confidence": 1, "reviewed": True,
                  "source": {"doc": "src-ent-a", "page": 3, "note": "原文“PCD 70”；录入人：张工（2026-10-06）"}}
    pilot = row(comp, "ports/motor_flange/pilot_diameter_mm")
    pv = fill.build_pv(pilot, "50", tol_upper="0.025", tol_lower="0", **kw)
    assert (pv["nominal"], pv["tol_upper"], pv["tol_lower"]) == (50.0, 0.025, 0.0)
    kind = row(comp, "ports/motor_flange/hole_kind")
    assert fill.build_pv(kind, "threaded", **kw)["value"] == "threaded"
    with pytest.raises(ValueError, match="只能是"):
        fill.build_pv(kind, "螺纹", **kw)
    with pytest.raises(ValueError, match="整数"):
        fill.build_pv(row(comp, "ports/motor_flange/hole_count"), "4.5", **kw)
    with pytest.raises(ValueError, match="下偏差"):
        fill.build_pv(pilot, "50", tol_upper="0", tol_lower="0.1", **kw)
    with pytest.raises(ValueError, match="资料、页码、原文与录入人"):
        fill.build_pv(pcd, "70", **{**kw, "quote": " "})
    with pytest.raises(ValueError, match="请填写值"):
        fill.build_pv(pcd, "", **kw)


def test_filling_the_custom_flange_resolves_c3(tmp_path):
    """企业按订货确定了 CSF-2UH 的电机法兰（与 SGM7J-02A 相配）：补入企业库后 C3 不再待确认。"""
    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    spec = tmp_path / "order.pdf"
    spec.write_bytes(b"%PDF order confirmation")
    doc = ent.register_document(spec, "HD 订货确认单", "张工")["id"]
    lib = LayeredLibrary(ent, PUBLIC)
    before = {c["check"]: c["status"] for c in check(LAYOUT, lib.get, REQ)["checks"]}
    assert before["C3"] == "unknown"
    kw = {"doc": doc, "page": 1, "actor": "张工"}
    for target, value, extra in (("pcd_mm", "70", {}), ("hole_count", "4", {}), ("thread", "M5", {}),
                                 ("hole_kind", "threaded", {}), ("pilot_diameter_mm", "50", {"tol_upper": "0.025"}),
                                 ("pilot_kind", "female", {})):
        r = row(lib.get(R), f"ports/motor_flange/{target}")
        ent.set_value(R, r.target, fill.build_pv(r, value, quote=f"{target} {value}", **kw, **extra), "张工",
                      PUBLIC.get)
    after = {c["check"]: c["status"] for c in check(LAYOUT, lib.get, REQ)["checks"]}
    assert after["C3"] in ("pass", "warn") and after["C3"] != before["C3"]
    # 有依赖的字段要按顺序补：先写螺纹孔却没写螺纹规格时，schema 不通过，不写
    ent2 = EnterpriseLibrary(tmp_path / "ent2", create=True)
    doc2 = ent2.register_document(spec, "HD 订货确认单", "张工")["id"]
    r = row(PUBLIC.get(R), "ports/motor_flange/hole_kind")
    with pytest.raises(ValueError, match="thread"):
        ent2.set_value(R, r.target, fill.build_pv(r, "threaded", quote="x", **{**kw, "doc": doc2}), "张工", PUBLIC.get)
    assert ent2.get(R) is None
    assert lib.origin(R) == "enterprise" and PUBLIC.get(R)["ports"][1]["spec"] == {}
    assert len([h for h in ent.history() if h["action"] == "set_value"]) == 6
