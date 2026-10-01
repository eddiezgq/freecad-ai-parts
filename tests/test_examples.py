"""样例输出 examples/joint2（M5 #102，ADR-0037）与当前代码一致。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from engine import export
from engine.validate import validate
from kb.library import JsonLibrary
from mcp_server import e2e

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "examples" / "joint2"
LIB = JsonLibrary(ROOT / "tests" / "golden" / "fixtures")
SYSTEM_JSON = json.loads((SAMPLE / "system.json").read_text(encoding="utf-8"))


def test_sample_report_matches_engine():
    """system.json 自带的报告，与引擎对其中的系统重新校验的结果相同。"""
    assert validate(SYSTEM_JSON["system"], LIB.get) == SYSTEM_JSON["report"]
    assert SYSTEM_JSON["report"]["overall"] in ("pass", "warn")
    for cid, comp in SYSTEM_JSON["components"].items():
        assert comp == LIB.get(cid)


def test_sample_bom_and_urdf_match_export():
    system = SYSTEM_JSON["system"]
    assert (SAMPLE / "bom.csv").read_text(encoding="utf-8") == export.bom_csv(system, LIB.get)
    bom = json.loads((SAMPLE / "bom.json").read_text(encoding="utf-8"))
    assert bom == json.loads(json.dumps(export.bom_json(system, LIB.get)))
    assert (SAMPLE / f"{system['id']}.urdf").read_text(encoding="utf-8") == export.urdf(system, LIB.get)


def test_sample_requirement_is_example():
    req = json.loads((SAMPLE / "requirement.json").read_text(encoding="utf-8"))["requirement"]
    assert req == json.loads((ROOT / "examples" / "joint2-requirement.json").read_text(encoding="utf-8"))
    assert SYSTEM_JSON["system"]["requirement"] == req


@pytest.mark.freecad
def test_regenerated_sample_is_identical(tmp_path, monkeypatch):
    if "FreeCAD" in sys.modules or os.environ.get("FAP_REQUIRE_FREECAD") == "1":
        monkeypatch.setenv("FAP_FREECAD_PYTHON", os.environ.get("FAP_FREECAD_PYTHON", sys.executable))
    monkeypatch.setenv("FAP_FREECAD", "headless")
    monkeypatch.delenv("FAP_LIBRARY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert e2e.main(["--requirement", str(ROOT / "examples" / "joint2-requirement.json"), "--out", str(tmp_path)]) == 0
    want = {p.name: p.read_bytes() for p in SAMPLE.iterdir() if p.suffix != ".png"}
    got = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.suffix != ".png"}
    assert got.keys() == want.keys()
    for name, content in want.items():
        assert got[name] == content, f"examples/joint2/{name} 与当前代码的输出不一致，请重新生成"
