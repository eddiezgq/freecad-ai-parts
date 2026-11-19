"""问渠 CAD「AI 设计零件」面板（ADR-0100 42.4）：模型、工程图、BOM 放进文档；面板显示与入企业库。需要 FreeCAD（工程图要界面）。

AI 部分用录制的真实模型结果（examples/ai-design/ls-upper-shaft/out/result.json），不重跑 AI 与有限元。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.freecad

ROOT = Path(__file__).resolve().parent.parent
RESULT = ROOT / "examples" / "ai-design" / "ls-upper-shaft" / "out" / "result.json"


@pytest.fixture
def gui():
    if not os.environ.get("DISPLAY"):
        pytest.skip("工程图要界面（xvfb）")
    import FreeCADGui

    FreeCADGui.showMainWindow()
    return FreeCADGui


@pytest.fixture
def lib():
    from kb.library import JsonLibrary

    return JsonLibrary(ROOT / "data" / "library")


@pytest.fixture
def run_out(tmp_path, lib):
    from assist import shaft_model

    res = json.loads(RESULT.read_text(encoding="utf-8"))
    (tmp_path / "design-record.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return {"result": res, "model": shaft_model.generate(res, tmp_path, lib.get), "out_dir": str(tmp_path), "replay": False}


@pytest.fixture
def doc():
    import FreeCAD

    d = FreeCAD.newDocument("ai_design_test")
    name = d.Name
    yield d
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)


def test_place_model_drawing_bom(gui, doc, run_out, lib):
    from freecad_addon.core import ai_design as C
    from freecad_addon.fc import ai_design_doc as D

    segs = C.segments(run_out["result"], lib.get)
    out = D.place(doc, run_out, segs, name="上轴", drawing_no="AI-101")
    assert abs(out["part"].Shape.Volume - run_out["model"]["volume_mm3"]) < 1.0
    checks = out["dimension_checks"]
    assert len(checks) == 5 + 5 + 1                                           # 5 个直径、5 段长度、总长
    assert all(abs(c["design"] - c["drawing"]) <= D.DIM_TOL_MM for c in checks)
    assert {c["design"] for c in checks} >= {12.0, 16.5, 20.0, 292.0}
    texts = dict(out["page"].Template.EditableTexts)
    assert texts.get("title") == "上轴" and texts.get("identification_number") == "AI-101" and texts.get("approval_person") == ""
    sheet = out["sheet"]
    assert sheet.get("C3") == "bearing.nsk-ltd.6201" and str(sheet.get("E3")) in ("2", "2.0")


def test_place_refuses_unread_model(gui, doc, run_out, lib):
    from freecad_addon.core import ai_design as C
    from freecad_addon.fc import ai_design_doc as D

    bad = {**run_out, "model": {**run_out["model"], "readback": "fail"}}
    with pytest.raises(D.DrawingError):
        D.place(doc, bad, C.segments(run_out["result"], lib.get), name="上轴")


def test_panel_shows_rounds_places_and_confirms(gui, doc, run_out, lib, tmp_path):
    from freecad_addon.gui.ai_design_panel import AiDesignPanel
    from kb.enterprise import EnterpriseLibrary

    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    p = AiDesignPanel(lib, ent, client_factory=lambda: None)
    p.load_example()
    assert "5000 r/min" in p.text.toPlainText()
    p.done(run_out)
    assert "曲柄半径" in p.views["conditions"].toPlainText()
    assert "第 2 轮" in p.views["rounds"].toPlainText() and p.placed is not None
    assert p.ok.isEnabled()
    p.drawing_no.setText("AI-101")
    p.vendor.setText("示范缝纫机有限公司（虚构）")
    p.by.setText("张工")
    p.confirm()
    assert [c["model"] for c in ent.all()] == ["AI-101"]
    assert dict(p.placed["page"].Template.EditableTexts)["approval_person"] == "张工"
    assert not p.ok.isEnabled()


def test_command_in_workbench(gui):
    from freecad_addon.gui.ai_design_panel import AiDesignCommand

    r = AiDesignCommand().GetResources()
    assert r["MenuText"] and r["ToolTip"]


def test_open_panel_is_a_visible_dock_not_a_task_dialog(gui, lib):
    """任务面板在有的布局里是隐藏的：面板看不见、菜单被锁（2026-11-18 问渠 CAD）。改成右侧停靠面板，再点只调到前面"""
    from PySide import QtWidgets

    from freecad_addon.gui import ai_design_panel as P

    P._LAST_PANEL = P._DOCK = None
    p = P.open_panel(lib, None)
    dock = FreeCADGui_main().findChild(QtWidgets.QDockWidget, "FapAiDesignPanel")
    assert dock is not None and dock.isVisible() and P._DOCK is dock
    assert gui.Control.activeDialog() is False
    assert P.open_panel(lib, None) is p                                          # 只建一个


def FreeCADGui_main():
    import FreeCADGui

    return FreeCADGui.getMainWindow()
