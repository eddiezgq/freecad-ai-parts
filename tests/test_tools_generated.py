"""MCP 工具与端到端流程中的生成转接件（ADR-0041，issue #130）。不联网，不需要 FreeCAD。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb.library import JsonLibrary, WithGenerated
from mcp_server import tools
from mcp_server.tools import ToolInputError

FIX = Path(__file__).parent / "golden" / "fixtures"
REQ = {"statement": "t", "output_torque_cont_nm": 10, "output_speed_rpm": 20, "safety_factor": 1.2}


def _pv(v):
    return {"value": v, "source": {"doc": "src-test-fixture", "page": 1}, "method": "manual", "confidence": 1,
            "reviewed": True}


def _write_library(tmp_path: Path, with_adapters: bool = False) -> Path:
    """电机轴 11 mm、减速器孔 24 mm、法兰也不一致：没有库存转接件就组不成方案。"""
    motor = json.loads((FIX / "test.servo_motor.test-vendor.m400.json").read_text(encoding="utf-8"))
    shaft = next(p for p in motor["ports"] if p["id"] == "shaft")
    shaft["spec"].update(diameter_mm=_pv(11), key_width_mm=_pv(4), usable_length_mm=_pv(25))
    reducer = json.loads((FIX / "test.reducer.test-vendor.r25-100.json").read_text(encoding="utf-8"))
    bore = next(p for p in reducer["ports"] if p["id"] == "input_bore")
    bore["spec"].update(diameter_mm=_pv(24), key_width_mm=_pv(8), depth_mm=_pv(30))
    lib = tmp_path / "lib"
    lib.mkdir(parents=True)
    comps = [motor, reducer, json.loads((FIX / "test.drive.test-vendor.d400.json").read_text(encoding="utf-8"))]
    if with_adapters:
        comps.append(json.loads((FIX / "test.adapter.test-vendor.sleeve-11-19.json").read_text(encoding="utf-8")))
    for c in comps:
        (lib / f"{c['id']}.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    return lib


def test_compose_generates_and_registers(tmp_path):
    lib = WithGenerated(JsonLibrary(_write_library(tmp_path)))
    out = tools.compose_chain(lib, REQ, include_unknown=True)
    assert out["count"] >= 1
    cand = out["candidates"][0]
    gen = [c["id"] for c in cand["generated_components"]]
    assert len(gen) == 2 and all(lib.get(g) is not None for g in gen)
    assert all(c["category"] != "adapter" for c in lib.all())  # all 不列生成件
    verified = tools.verify_system(lib, cand["system"])
    assert verified["report"]["overall"] == cand["overall"]
    bom = tools.export_system(lib, cand["system"], format="bom_json")["content"]
    assert {r["vendor"] for r in bom["rows"]} >= {"freecad-ai-parts (generated)"}


def test_auto_off_when_library_has_adapters(tmp_path):
    lib = WithGenerated(JsonLibrary(_write_library(tmp_path, with_adapters=True)))
    out = tools.compose_chain(lib, REQ, include_unknown=True)
    assert all("generated_components" not in c for c in out["candidates"])
    forced = tools.compose_chain(lib, REQ, include_unknown=True, generate_adapters=True)
    assert forced["count"] >= 1 and "generated_components" in forced["candidates"][0]


def test_library_without_register_refused(tmp_path):
    with pytest.raises(ToolInputError, match="不能登记"):
        tools.compose_chain(JsonLibrary(_write_library(tmp_path)), REQ, include_unknown=True)
    with pytest.raises(ToolInputError, match="generate_adapters"):
        tools.compose_chain(JsonLibrary(_write_library(tmp_path / "x")), REQ, generate_adapters="yes")


def test_overlay_register_rules(tmp_path):
    lib = WithGenerated(JsonLibrary(_write_library(tmp_path)))
    with pytest.raises(ValueError, match="只能登记"):
        lib.register({"id": "adapter.acme.x"})
    lib.register({"id": "adapter.fap-generated.x", "a": 1})
    lib.register({"id": "adapter.fap-generated.x", "a": 1})
    with pytest.raises(ValueError, match="不同"):
        lib.register({"id": "adapter.fap-generated.x", "a": 2})


def test_e2e_with_library_without_adapters(tmp_path, monkeypatch):
    from mcp_server import e2e

    monkeypatch.setenv("FAP_LIBRARY", str(_write_library(tmp_path)))
    code = e2e.run(requirement=REQ, out_dir=tmp_path / "out", backend_factory=lambda: None)
    assert code in (1, 2), (tmp_path / "out" / "README.md").read_text(encoding="utf-8")
    bom = (tmp_path / "out" / "bom.csv").read_text(encoding="utf-8")
    assert "freecad-ai-parts (generated)" in bom
    system = json.loads((tmp_path / "out" / "system.json").read_text(encoding="utf-8"))
    assert any(cid.startswith("adapter.fap-generated.") for cid in system["components"])


def test_e2e_readme_shows_provenance(tmp_path, monkeypatch):
    from mcp_server import e2e

    lib = _write_library(tmp_path)
    monkeypatch.setenv("FAP_LIBRARY", "unused")  # main 会改写 FAP_LIBRARY；由 monkeypatch 在测试结束后还原
    req = tmp_path / "req.json"
    req.write_text(json.dumps(REQ), encoding="utf-8")
    e2e.main(["--requirement", str(req), "--out", str(tmp_path / "out"), "--library", str(lib)])
    text = (tmp_path / "out" / "README.md").read_text(encoding="utf-8")
    assert "按两侧端口尺寸生成（ADR-0041），须加工" in text and "虚构测试组件（ADR-0015）" in text
    with pytest.raises(SystemExit):
        e2e.main(["--requirement", str(req), "--out", str(tmp_path / "o2"), "--library", str(tmp_path / "nope")])


def test_provenance_marks_ai_review():
    from mcp_server.e2e import _provenance

    pv = {"value": 1, "source": {"doc": "src-hd-csg-csf-gear-units", "page": 8, "note": "claude（AI 复核）：一致"},
          "method": "extracted", "confidence": 0.9, "reviewed": True}
    comp = {"vendor": "Harmonic Drive LLC", "model": "CSF-14-50-2UH", "params": {"ratio": pv}, "ports": []}
    out = {"system": {"components": [{"instance": "reducer", "component": "reducer.harmonic-drive-llc.csf-14"}]},
           "system_json": {"content": {"components": {"reducer.harmonic-drive-llc.csf-14": comp}}}}
    row = _provenance(out)[2]
    assert "`src-hd-csg-csf-gear-units`" in row and "AI 复核" in row
    comp["params"]["ratio"] = {**pv, "reviewed": False}
    assert "部分未复核" in _provenance(out)[2]
