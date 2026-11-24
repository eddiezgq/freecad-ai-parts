"""问渠CAM Q4a 刀具库窗口、机床窗口（ADR-0106）：新建刀具库与刀具、坏数据拒存、作业里选到并算通；复制机床改行程、画外形。"""

from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.freecad


@pytest.fixture(scope="module")
def gui():
    import FreeCADGui

    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    FreeCADGui.showMainWindow()
    from PySide import QtWidgets

    return QtWidgets.QApplication.instance()


@pytest.fixture()
def homes(tmp_path, monkeypatch):
    monkeypatch.setenv("FAP_TOOLS", str(tmp_path / "tools"))
    monkeypatch.setenv("FAP_MACHINES_DIR", str(tmp_path / "machines"))
    return tmp_path


def test_tool_library_window(gui, homes):
    import FreeCAD as App
    import Part

    from freecad_addon.fc import cam_objects as CO
    from freecad_addon.gui import cam_library as L

    dlg = L.ToolLibraryDialog()
    assert dlg.readonly and not dlg.btn_save.isEnabled()              # 示例库只读
    assert dlg.new_lib("车间刀具") and not dlg.readonly
    t = dlg.new_tool("flat_endmill")
    dlg.f_id.setText("EM8")
    dlg.f_name.setText("Ø8 立铣刀")
    assert dlg.save() is False and "diameter_mm" in dlg.status.text()  # 没写直径：不存，写明哪一项
    dlg.f_basic["diameter_mm"].setText("8")
    dlg.f_basic["flutes"].setText("3")
    dlg.f_basic["flute_length_mm"].setText("")                           # 空 = 不写
    dlg.cut.setRowCount(1)
    from PySide import QtWidgets

    for col, v in enumerate(("P", "90", "150", "0.03", "0.05", "", "", "8", "2")):
        dlg.cut.setItem(0, col, QtWidgets.QTableWidgetItem(v))
    assert dlg.save(), dlg.status.text()
    lib = json.loads((homes / "tools" / "车间刀具.json").read_text(encoding="utf-8"))
    em = next(x for x in lib["tools"] if x["id"] == "EM8")
    assert em["diameter_mm"] == 8 and "flute_length_mm" not in em and em["cutting"][0]["ap_max_mm"] == 8
    assert t["kind"] == "flat_endmill" and em["source"]["kind"] == "enterprise"
    # 作业里选到这个刀具库，起草、算通
    doc = App.newDocument("camlib")
    try:
        m = doc.addObject("Part::Feature", "Block")
        m.Shape = Part.makeBox(100, 60, 30).cut(Part.makeBox(40, 20, 8, App.Vector(30, 20, 22)))
        doc.recompute()
        job = CO.new_job(doc, m, "mill", post="fanuc")
        choices = {p: n for n, p in L.library_choices()}
        path = str(homes / "tools" / "车间刀具.json")
        assert path in choices
        job.ToolLibrary = path
        job.ToolLengths = json.dumps({"EM8": 110})
        CO.draft(job)
        s = CO.setups(job)[0]
        assert [o.ToolId for o in CO.ops(s)] == ["EM8"]
        for o in CO.ops(s):
            CO.confirm(o)
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        assert not [c for c in p["checks"] if c["level"] == "error"] and p["release"] is not None
    finally:
        App.closeDocument(doc.Name)


def test_machine_window(gui, homes):
    import FreeCAD as App

    from analysis.cam import machines as M
    from freecad_addon.gui import cam_library as L

    dlg = L.MachineDialog()
    i = next(k for k, m in enumerate(dlg.models) if m["id"] == "EX-VMC")
    dlg.list.setCurrentRow(i)
    assert not dlg.btn_save.isEnabled() and "虚构" in dlg.info.toPlainText()
    assert dlg.copy("MY-VMC", "车间立加")
    assert dlg.cur["id"] == "MY-VMC" and dlg.btn_save.isEnabled()
    dlg.fields["axis.X.max"].setText("abc")
    with pytest.raises(ValueError):
        dlg.form_model()
    dlg.fields["axis.X.max"].setText("300")
    dlg.fields["source"].setText("车间实测 2026-11-19")
    assert dlg.save(), dlg.status.text()
    mm = M.model("MY-VMC")
    assert next(a for a in mm["axes"] if a["id"] == "X")["max"] == 300 and mm["source"] == "车间实测 2026-11-19"
    doc = App.newDocument("machdraw")
    try:
        objs = L.draw_machine(mm, doc)
        assert {o.Label for o in objs} >= {"工作台", "主轴头"}
    finally:
        App.closeDocument(doc.Name)


def test_real_machine_fill_home_and_tool_change(gui, homes):
    """真实机床（ADR-0106 E2，HAAS-ST-10Y）：规格页没公开换刀点、换刀时间，编程前报出来；机床窗口里按实机填好保存，就能编程"""
    from analysis.cam import machines as M
    from freecad_addon.gui import cam_library as L

    with pytest.raises(M.MachineError, match="换刀点、换刀时间"):
        M.get("HAAS-ST-10Y")
    dlg = L.MachineDialog()
    dlg.list.setCurrentRow(next(k for k, m in enumerate(dlg.models) if m["id"] == "HAAS-ST-10Y"))
    assert dlg.btn_save.isEnabled() and "换刀点：X—" in dlg.info.toPlainText()
    dlg.fields["home.x"].setText("250")
    dlg.fields["home.z"].setText("-50")
    dlg.fields["tool_change_s"].setText("0.5")
    assert dlg.save(), dlg.status.text()
    v = M.get("HAAS-ST-10Y")
    assert v["home"] == [250.0, -50.0] and v["tool_change_s"] == 0.5 and v["max_rpm"] == 6000
