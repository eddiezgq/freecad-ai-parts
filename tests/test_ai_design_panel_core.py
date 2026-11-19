"""问渠 CAD「AI 设计零件」面板背后的逻辑（ADR-0100 42.4）：页签内容、生成、入企业库的规则。不联网、不调用 AI。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from freecad_addon.core import ai_design as C
from kb.enterprise import EnterpriseLibrary
from kb.library import JsonLibrary

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "examples" / "ai-design" / "ls-upper-shaft" / "out" / "result.json"


def _need_gmsh():
    if os.environ.get("CI"):
        import gmsh  # noqa: F401
        return
    pytest.importorskip("gmsh")


@pytest.fixture(scope="module")
def lib():
    return JsonLibrary(ROOT / "data" / "library")


@pytest.fixture(scope="module")
def result():
    return json.loads(RESULT.read_text(encoding="utf-8"))


@pytest.fixture
def run_out(tmp_path, result, lib):
    """录制的真实模型设计结果 → 生成模型（与面板 run 后半段相同，不重跑 AI 与有限元）"""
    _need_gmsh()
    from assist import shaft_model

    (tmp_path / "design-record.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    gen = shaft_model.generate(result, tmp_path, lib.get)
    return {"result": result, "model": gen, "out_dir": str(tmp_path), "replay": False}


def test_example_and_tabs(result):
    assert "5000 r/min" in C.example_text()
    cond = C.conditions_html(result)
    assert "曲柄半径 15.5 mm" in cond and "45-QT" in cond                     # 每个数带原话引用
    rounds = C.rounds_html(result)
    assert rounds.count("<h3>") == len(result["rounds"]) and "全部通过" in rounds
    assert all(C.COLORS[r["overall"]] in rounds for r in result["rounds"])  # 每轮按结论着色
    assert rounds.count("（采用）") == 1 and "质量" in rounds                 # 标出采用的那一轮和每轮质量
    assert "bearing.nsk-ltd.6201" in rounds
    q = C.questions_html(result)
    assert all(a in q for a in result["assumptions"])


def test_result_carries_quotes(result):
    whats = [q["what"] for q in result["quotes"]]
    assert "材料" in whats and whats.count("轴承中心 z") == 2
    assert all(q["quote"] in result["statement"] for q in result["quotes"])


def test_confirm_writes_component_with_records(run_out, tmp_path):
    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    with pytest.raises(C.ConfirmError, match="都要填"):
        C.confirm(ent, run_out, drawing_no="", name="上轴", enterprise="示范（虚构）", actor="张工")
    comp = C.confirm(ent, run_out, drawing_no="AI-101", name="上轴", enterprise="示范（虚构）", actor="张工")
    assert comp["id"] == ent.get(comp["id"])["id"] and comp["params"]["part_kind"]["value"] == "shaft"
    assert comp["params"]["mass_kg"]["value"] == run_out["model"]["mass_kg"]
    docs = {d["id"]: d for d in ent.documents()}
    assert len(docs) == 2 and any(d["file"].endswith(".json") for d in docs.values())
    assert any(k in comp["note"] for k in docs)                              # 设计记录作为出处
    hist = (tmp_path / "ent" / "history.jsonl").read_text(encoding="utf-8")
    assert "张工" in hist
    with pytest.raises(C.ConfirmError, match="已有"):
        C.confirm(ent, run_out, drawing_no="AI-101", name="上轴", enterprise="示范（虚构）", actor="张工")


def test_confirm_refuses_replay_and_bad_model(run_out, tmp_path):
    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    with pytest.raises(C.ConfirmError, match="录制回放"):
        C.confirm(ent, {**run_out, "replay": True}, drawing_no="X", name="n", enterprise="e", actor="a")
    with pytest.raises(C.ConfirmError, match="回读"):
        C.confirm(ent, {**run_out, "model": {**run_out["model"], "readback": "fail"}}, drawing_no="X", name="n", enterprise="e",
                  actor="a")
    assert ent.all() == []


def test_example_text_has_unix_newlines(tmp_path, monkeypatch):
    """Windows 检出的 \\r\\n 不能进提示词，否则录制回放对不上"""
    f = tmp_path / "req.txt"
    f.write_bytes(C.EXAMPLE.read_bytes().replace(b"\n", b"\r\n"))
    monkeypatch.setattr(C, "EXAMPLE", f)
    assert "\r" not in C.example_text() and C.example_text() == C.EXAMPLE.read_text(encoding="utf-8").replace("\r\n", "\n")
