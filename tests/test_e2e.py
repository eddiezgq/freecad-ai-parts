"""端到端演示（M5 #101，ADR-0037）：一句话 → … → BOM / URDF，可复现。"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
from pathlib import Path

import pytest

from engine import requirement_parse
from mcp_server import e2e

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "joint2-requirement.json"
STATEMENT = json.loads(EXAMPLE.read_text(encoding="utf-8"))["statement"]


@pytest.fixture(autouse=True)
def golden_library(monkeypatch):
    monkeypatch.delenv("FAP_LIBRARY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _files(d: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(d.iterdir()) if p.suffix != ".png"}


def test_statement_to_bom_without_freecad_is_reproducible(tmp_path, monkeypatch):
    monkeypatch.delenv("FAP_FREECAD", raising=False)
    assert e2e.main([STATEMENT, "--out", str(tmp_path / "a")]) == 2  # 未连接 FreeCAD
    assert e2e.main([STATEMENT, "--out", str(tmp_path / "b")]) == 2
    a, b = _files(tmp_path / "a"), _files(tmp_path / "b")
    assert a == b
    assert set(a) == {"README.md", "requirement.json", "bom.csv", "bom.json", "system.json", "candidate-1.urdf"}
    req = json.loads(a["requirement.json"])
    assert req["llm"]["simulated"] is False and req["basis"]["output_speed_rpm"] == "输出转速 30 rpm"
    assert req["requirement"]["supply"] == {"current_type": "ac", "voltage_v": 220.0, "phases": 1}
    rows = list(csv.DictReader(io.StringIO(a["bom.csv"].decode())))
    assert {r["component_id"] for r in rows} >= {"test.servo_motor.test-vendor.m200", "test.reducer.test-vendor.r25-100"}
    system = json.loads(a["system.json"])
    assert system["system"]["layout"]["poses"]["reducer"]["position_mm"] == [0.0, 0.0, 30.0]
    readme = a["README.md"].decode()
    assert "claude-sonnet-5-5 的录制响应" in readme and "没有做干涉检查" in readme and "可用" in readme


def test_structured_requirement_input(tmp_path, monkeypatch):
    monkeypatch.delenv("FAP_FREECAD", raising=False)
    assert e2e.main(["--requirement", str(EXAMPLE), "--out", str(tmp_path)]) == 2
    req = json.loads((tmp_path / "requirement.json").read_text(encoding="utf-8"))
    assert set(req) == {"requirement"} and "原话" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_needs_input_stops_before_selection(tmp_path, monkeypatch):
    def fake_parse(statement, client=None):
        return requirement_parse.interpret(statement, {"items": []}) | {
            "llm": {"model": "m", "prompt_version": "requirement/2", "response_id": None, "simulated": True}}

    monkeypatch.setattr(requirement_parse, "parse", fake_parse)
    assert e2e.main(["给第 2 关节选个电机", "--out", str(tmp_path)]) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["README.md", "requirement.json"]
    assert "需要追问" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_no_candidates(tmp_path, monkeypatch):
    monkeypatch.delenv("FAP_FREECAD", raising=False)
    req = tmp_path / "r.json"
    req.write_text(json.dumps({"output_torque_cont_nm": 10000, "output_speed_rpm": 1}), encoding="utf-8")
    assert e2e.main(["--requirement", str(req), "--out", str(tmp_path / "o")]) == 1
    assert "没有候选方案" in (tmp_path / "o" / "README.md").read_text(encoding="utf-8")


def test_argument_errors(tmp_path):
    with pytest.raises(SystemExit):
        e2e.main(["--out", str(tmp_path)])
    with pytest.raises(SystemExit):
        e2e.main([STATEMENT, "--requirement", str(EXAMPLE), "--out", str(tmp_path)])


@pytest.mark.freecad
def test_end_to_end_with_real_freecad(tmp_path, monkeypatch):
    if "FreeCAD" in sys.modules or os.environ.get("FAP_REQUIRE_FREECAD") == "1":
        monkeypatch.setenv("FAP_FREECAD_PYTHON", os.environ.get("FAP_FREECAD_PYTHON", sys.executable))
    monkeypatch.setenv("FAP_FREECAD", "headless")
    assert e2e.main([STATEMENT, "--out", str(tmp_path / "a")]) == 0
    assert e2e.main([STATEMENT, "--out", str(tmp_path / "b")]) == 0
    assert _files(tmp_path / "a") == _files(tmp_path / "b")
    png = (tmp_path / "a" / "layout-iso.png").read_bytes()
    assert png[:4] == b"\x89PNG" and len(png) > 5000
    readme = (tmp_path / "a" / "README.md").read_text(encoding="utf-8")
    assert "第 2 轮：通过" in readme and "需有通孔：plate" in readme
