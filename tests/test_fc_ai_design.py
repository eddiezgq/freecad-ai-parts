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
    merged = [s["d"] for i, s in enumerate(segs) if i == 0 or abs(s["d"] - segs[i - 1]["d"]) > 1e-9]   # 相邻同径段合成一段
    assert len(checks) == 2 * len(merged) + 1                                  # 每段直径、每段长度、总长
    assert all(abs(c["design"] - c["drawing"]) <= D.DIM_TOL_MM for c in checks)
    assert {c["design"] for c in checks} >= {*merged, sum(s["L"] for s in segs)}
    texts = dict(out["page"].Template.EditableTexts)
    assert texts.get("title") == "上轴" and texts.get("identification_number") == "AI-101" and texts.get("approval_person") == ""
    sheet = out["sheet"]
    for row, item in enumerate(run_out["model"]["bom"][1:], 3):              # 第 2 行是自制件，之后是轴承（型号、数量按设计）
        assert sheet.get(f"C{row}") == item["component"] and float(sheet.get(f"E{row}")) == item["qty"]


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


def test_open_panel_is_a_tool_window_not_a_dock_or_task_dialog(gui, lib):
    """任务面板在有的布局里是隐藏的：面板看不见、菜单被锁（2026-11-18）；放进右侧停靠区在问渠 CAD 1.1.4 里卡死（2026-11-19）。
    改成挂在主窗口上的单独工具窗口：在屏幕内、不进主窗口的停靠区，再点只调到前面"""
    from PySide import QtCore, QtWidgets

    from freecad_addon.gui import ai_design_panel as P

    P._LAST_PANEL = P._DOCK = None
    mw = FreeCADGui_main()
    p = P.open_panel(lib, None)
    win = P._DOCK
    assert win.isVisible() and win.objectName() == "FapAiDesignPanel" and win.parent() is mw
    assert win.windowFlags() & QtCore.Qt.Tool and not isinstance(win, QtWidgets.QDockWidget)
    assert mw.findChild(QtWidgets.QDockWidget, "FapAiDesignPanel") is None
    area = QtWidgets.QApplication.primaryScreen().availableGeometry()
    assert area.contains(win.frameGeometry().topLeft()) and win.width() <= area.width()   # 整个在屏幕里
    assert gui.Control.activeDialog() is False
    assert P.open_panel(lib, None) is p                                          # 只建一个


def FreeCADGui_main():
    import FreeCADGui

    return FreeCADGui.getMainWindow()


def test_start_replays_example_without_recording_miss(gui, lib, monkeypatch):
    """“载入示例”后直接“开始设计”要能回放：面板里的文字去掉了末尾换行，回放要用示例原文（2026-11-18 问渠 CAD）"""
    from freecad_addon.core import ai_design as C
    from freecad_addon.gui import ai_design_panel as P

    seen = {}
    monkeypatch.setattr(P, "_in_background", lambda work, done: seen.setdefault("work", work))
    p = P.AiDesignPanel(lib, None, client_factory=lambda: None)
    p.load_example()
    p.start()
    req = {}

    def fake_run(statement, client, library, kind=None, replay=False, progress=None):
        req.update(statement=statement, replay=replay, kind=kind)
        return statement

    monkeypatch.setattr(C, "run", fake_run)
    seen["work"]()
    assert req["replay"] and req["statement"] == C.example_text() and req["kind"] == "阶梯轴"


def test_progress_bar_and_elapsed_time(gui, lib, monkeypatch):
    """进度：后台写（说明, 已做, 总数），界面每半秒显示当前一步、第几个台阶、已用时间；结束后写总用时"""
    from freecad_addon.gui import ai_design_panel as P

    monkeypatch.setattr(P, "_in_background", lambda work, done: None)
    p = P.AiDesignPanel(lib, None, client_factory=lambda: None)
    p.load_example()
    p.start()
    assert p.bar.isVisibleTo(p.form) and p.ticker.isActive()
    p._status = ("第 1 轮（最多 4 轮）：校核台阶强度（有限元）", 1, 4)
    p._tick()
    assert "2 / 4" in p.progress.text() or "2 of 4" in p.progress.text()
    assert (p.bar.minimum(), p.bar.maximum(), p.bar.value()) == (0, 4, 1)
    p._status = ("AI 列设计条件", None, None)
    p._tick()
    assert p.bar.maximum() == 0                                                   # 步数不定：忙
    p.done(RuntimeError("测试中断"))
    assert not p.ticker.isActive() and not p.bar.isVisibleTo(p.form)


def test_confirm_refreshes_library_browser(gui, doc, run_out, lib, tmp_path):
    """入库后零件库浏览器立刻刷新，标题里的企业库组件数跟着变（2026-11-18：入了库却在浏览器里看不到）"""
    from PySide import QtWidgets

    from freecad_addon.gui.ai_design_panel import AiDesignPanel
    from kb.enterprise import EnterpriseLibrary

    class FakeBrowser(QtWidgets.QDockWidget):
        refreshed = 0

        def refresh(self):
            FakeBrowser.refreshed += 1

    mw = gui.getMainWindow()
    fake = FakeBrowser("AI Parts 零件库", mw)
    fake.setObjectName("FapLibraryBrowser")
    fake.header = QtWidgets.QLabel("企业库 0 个组件（X）叠加在 组件库")
    try:
        ent = EnterpriseLibrary(tmp_path / "ent", create=True)
        p = AiDesignPanel(lib, ent, client_factory=lambda: None)
        p.done(run_out)
        p.drawing_no.setText("AI-102")
        p.vendor.setText("示范（虚构）")
        p.by.setText("张工")
        p.confirm()
        assert FakeBrowser.refreshed == 1 and fake.header.text().startswith("企业库 1 个组件")
    finally:
        fake.setObjectName("")
        fake.deleteLater()


def test_custom_parts_have_a_category_name():
    from freecad_addon.core import browser as core

    assert core.CATEGORIES["custom_part"] == "自制件"


# ---------------------------------------------------------------- 关节空心轴（ADR-0100 42.5 第 7 步）

JOINT = ROOT / "examples" / "ai-design" / "cobot-j2" / "out" / "result.json"


@pytest.fixture
def joint_out(tmp_path, lib):
    from assist import joint_model

    res = json.loads(JOINT.read_text(encoding="utf-8"))
    (tmp_path / "design-record.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return {"result": res, "model": joint_model.generate(res, tmp_path, lib.get), "out_dir": str(tmp_path), "replay": False,
            "kind": "关节空心轴"}


def test_place_joint_shaft_with_bore_and_notes(gui, doc, joint_out, lib):
    from freecad_addon.core import ai_design as C
    from freecad_addon.fc import ai_design_doc as D

    res = joint_out["result"]
    segs = C.segments(res, lib.get)
    out = D.place(doc, joint_out, segs, name="关节输出轴", drawing_no="AI-J2-01", **C.drawing_extras(res))
    assert abs(out["part"].Shape.Volume - joint_out["model"]["volume_mm3"]) < 1.0
    checks = out["dimension_checks"]
    bore = res["rounds"][res["chosen_round"] - 1]["proposal"]["bore_mm"]
    assert any(c["design"] == bore and "Ø" in c["what"] for c in checks)                    # 端视图上标了内孔
    assert all(abs(c["design"] - c["drawing"]) <= D.DIM_TOL_MM for c in checks)
    note = "\n".join(doc.getObject("AiShaftNotes").Text)
    assert "GB/T 3478.1" in note and "M45" in note
    # 每行不超出图框，否则 TechDraw 把整段注释缩小（2026-11-22 问渠 CAD 英文界面报“AiShaftNotes is larger than page”）
    assert max(D.text_width_mm(x) for x in doc.getObject("AiShaftNotes").Text) <= D.NOTE_MAX_MM
    sheet = out["sheet"]
    assert sheet.get("C3") == "bearing.nsk-ltd.6011" and float(sheet.get("E3")) == 2


def test_wrap_note_breaks_long_lines_at_word_boundaries():
    from freecad_addon.fc import ai_design_doc as D

    t = "2. Dimensions placed by the program from the design data; the model was checked by read-back"
    lines = D.wrap_note(t, max_mm=120)
    assert len(lines) > 1 and all(D.text_width_mm(x) <= 120 for x in lines)
    assert " ".join(x.strip() for x in lines) == t                      # 只断行，不丢字
    assert D.wrap_note("短的一行") == ["短的一行"]
    assert all(D.text_width_mm(x) <= 40 for x in D.wrap_note("没有空格也没有逗号的很长很长很长的一行中文字", max_mm=40))


def test_panel_switches_part_type_and_example(gui, lib, monkeypatch):
    from freecad_addon.core import ai_design as C
    from freecad_addon.gui import ai_design_panel as P

    seen = {}
    monkeypatch.setattr(P, "_in_background", lambda work, done: seen.setdefault("work", work))
    p = P.AiDesignPanel(lib, None, client_factory=lambda: None)
    p.load_example()
    p.kind.setCurrentIndex(1)
    assert p.part_type() == "关节空心轴" and p.text.toPlainText() == ""                     # 换类型：上一类型的示例清掉
    assert "J2" in p.example.text() and p.name.text() in ("关节输出轴", "Joint output shaft")
    p.load_example()
    assert "CSF-25-100-2UH" in p.text.toPlainText()
    p.start()
    req = {}
    monkeypatch.setattr(C, "run", lambda statement, client, library, kind=None, replay=False, progress=None:
                        req.update(kind=kind, replay=replay, statement=statement))
    seen["work"]()
    assert req == {"kind": "关节空心轴", "replay": True, "statement": C.example_text("关节空心轴")}
