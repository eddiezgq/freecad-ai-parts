"""问渠CAM 面板与工作台（ADR-0104 产品化第 2 步）：在 FreeCAD 里从回转体读轮廓、起草、计算、画结果、保存；铣削件走 FreeCAD CAM。"""

from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.freecad


@pytest.fixture(scope="module")
def gui():
    import FreeCAD  # noqa: F401
    import FreeCADGui

    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    FreeCADGui.showMainWindow()
    from PySide import QtWidgets

    return QtWidgets.QApplication.instance()


def _pump(app, cond, timeout=180):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.005)
    assert cond(), "超时"


def _shaft():
    """阶梯轴（轴线沿 Z，右端 Z 最大）：Ø30×40、Ø40×60、Ø35×25、Ø24×30，Ø24 段左边一个 3 宽、底径 20 的槽，右端 Ø16×20 + Ø12×15 内孔"""
    import FreeCAD as App
    import Part

    z = 0.0
    s = None
    for d, L in ((30, 40), (40, 60), (35, 25), (24, 30)):
        c = Part.makeCylinder(d / 2, L, App.Vector(0, 0, z))
        s = c if s is None else s.fuse(c)
        z += L
    ring = Part.makeCylinder(12, 3, App.Vector(0, 0, z - 30)).cut(Part.makeCylinder(10, 3, App.Vector(0, 0, z - 30)))
    s = s.cut(ring)
    s = s.cut(Part.makeCylinder(8, 20, App.Vector(0, 0, z - 20))).cut(Part.makeCylinder(6, 15, App.Vector(0, 0, z - 35)))
    return s.removeSplitter()


def test_turn_features_from_solid():
    from freecad_addon.fc import cam_doc

    ft = cam_doc.turn_features(_shaft())
    assert ft["segments"] == [[30, 40], [40, 60], [35, 25], [24, 30]]
    assert ft["grooves"] == [{"z": -27.0, "width": 3.0, "d": 20.0}]
    assert ft["bore"] == [[16, 20], [12, 15]] and ft["chamfer_mm"] == 0


def test_turning_panel_end_to_end(gui, tmp_path):
    import FreeCAD as App
    import FreeCADGui

    from freecad_addon.gui.cam_panel import CamPanel

    doc = App.newDocument("camturn")
    try:
        o = doc.addObject("Part::Feature", "Shaft")
        o.Shape = _shaft()
        doc.recompute()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(o)
        p = CamPanel(client_factory=lambda: None)
        p.read_selection()
        assert p.segments.text() == "30x40, 40x60, 35x25, 24x30" and p.grooves.toPlainText() == "-27, 3, 20"
        p.threads.setPlainText("0, -26, 24, 1.5")
        p.start_draft(False)
        _pump(gui, lambda: p.draft is not None)
        assert p.table.rowCount() == 6
        p.start_run()
        _pump(gui, lambda: p.result is not None or "失败" in p.status.text())
        assert p.result is not None, p.status.text()
        assert p.save_btn.isEnabled() and p.checks.count() > 0
        names = {x.Label for x in doc.Objects}
        assert "仿真后的形状" in names and any("刀路" in n for n in names)
        files = p.save_to(tmp_path)
        assert any(f.suffix == ".nc" for f in files) and any(f.suffix == ".docx" for f in files)
    finally:
        App.closeDocument(doc.Name)


def test_milling_panel_with_freecad_cam(gui, tmp_path):
    import FreeCAD as App
    import FreeCADGui
    import Part

    from freecad_addon.gui.cam_panel import CamPanel

    doc = App.newDocument("cammill")
    try:
        blk = Part.makeBox(100, 60, 30)
        shape = blk.cut(Part.makeBox(40, 20, 8, App.Vector(30, 20, 22))).cut(Part.makeCylinder(4.25, 30, App.Vector(10, 10, 0)))
        o = doc.addObject("Part::Feature", "Block")
        o.Shape = shape
        doc.recompute()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(o)
        p = CamPanel(client_factory=lambda: None)
        p.kind.setCurrentIndex(1)
        p.read_selection()
        p.lengths.setText("EM10=120, DR8.5=140")
        p.offset.setText("40")
        p.fixture.setText("")
        p.start_draft(False)
        _pump(gui, lambda: p.draft is not None or "刀" in p.status.text())
        assert p.draft is not None, p.status.text()
        assert [c["tool"] for c in p.draft["card"]] == ["EM10", "EM10", "DR8.5"]
        p.start_run()
        _pump(gui, lambda: p.result is not None or "失败" in p.status.text())
        assert p.result is not None, p.status.text()
        rel = p.result["data"]["programs"][0]["release"]
        assert rel is not None and "G21 G17" in rel["text"]
        assert any(x.TypeId == "Mesh::Feature" for x in doc.Objects)
    finally:
        App.closeDocument(doc.Name)


def test_cam_workbench_menu(gui, monkeypatch):
    import FreeCADGui

    from freecad_addon.gui import cam_brand

    monkeypatch.setattr(cam_brand, "_start_here", lambda: None)
    cam_brand.register()
    try:
        assert cam_brand.WORKBENCH in FreeCADGui.listWorkbenches()
        FreeCADGui.activateWorkbench(cam_brand.WORKBENCH)

        def menus():
            return {a.text(): [x.text() for x in a.menu().actions()] for a in FreeCADGui.getMainWindow().menuBar().actions()
                    if a.menu()}
        _pump(gui, lambda: "问渠CAM" in menus(), 10)
        menus = menus()
        got = set(menus.get("问渠CAM") or [])
        assert {"数控编程", "检查 G 代码…", "授权…", "设置 AI 密钥…", "关于问渠CAM"} <= got, menus
        assert "免费版" in cam_brand.about_text()
    finally:
        FreeCADGui.activateWorkbench("NoneWorkbench")
