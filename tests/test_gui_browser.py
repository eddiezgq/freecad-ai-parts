"""库浏览器窗口（ADR-0048 第 3 条）：在 FreeCAD 界面中筛选、看详情、放入布局，与对话面板共用场景。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from kb.library import JsonLibrary

ROOT = Path(__file__).resolve().parent.parent
REAL = JsonLibrary(ROOT / "data" / "library")


@pytest.fixture(scope="module")
def gui():
    import FreeCAD  # noqa: F401
    import FreeCADGui

    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    FreeCADGui.showMainWindow()
    from PySide import QtWidgets

    return QtWidgets.QApplication.instance()


def _pump_until(app, cond, timeout=120):
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert cond(), "超时"


@pytest.mark.freecad
def test_browse_filter_detail_and_place(gui):
    import FreeCAD

    from freecad_addon.gui.browser import LibraryBrowser
    from freecad_addon.gui.host import ToolsHost

    host = ToolsHost(lambda: REAL, note="组件库：真实厂商组件（测试）")
    dock = LibraryBrowser(host=host)
    try:
        dock.category.setCurrentIndex(dock.category.findData("reducer"))
        dock.text.setText("csf 25")
        assert [r.model for r in dock._rows] == ["CSF-25-100-2UH"]
        dock.table.selectRow(0)
        html = dock.detail.toHtml()
        assert "CSF-25-100-2UH" in html and "src-hd-csg-csf-gear-units" in html and "曲线 24 点" in html
        assert dock.place_selected() == "reducer"
        _pump_until(gui, lambda: "已放入" in dock.status.text() or "没有放入" in dock.status.text())
        assert "已放入 reducer" in dock.status.text()
        doc = FreeCAD.getDocument("FapLayout")
        assert any(o.Name.startswith("reducer") for o in doc.Objects)
        # 第二次放入同品类时自动编号；AI 经同一宿主放入的实例也计入
        box = []  # 界面线程不能直接调工具（会与主线程执行器互等），AI 也是在后台线程调用
        host.call_in_background("place_component", {"instance": "motor", "component_id":
                                "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"}, box.append, source="ai")
        _pump_until(gui, lambda: box)
        assert not box[0].is_error and dock.instances == {"reducer", "motor"}
        assert dock.place_selected() == "reducer2"
        _pump_until(gui, lambda: "reducer2" in dock.status.text() and "正在" not in dock.status.text())
    finally:
        dock.close()
        host.tools.close()


@pytest.mark.freecad
def test_document_groups_instances_with_port_markers_on_their_frames(gui):
    import FreeCAD

    from freecad_addon.core.scene import Scene
    from freecad_addon.fc import snapshot

    s = Scene()
    s.place("motor", REAL.get("servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"))
    s.place("reducer", REAL.get("reducer.harmonic-drive-llc.csf-25-100-2uh"))
    s.connect("motor.shaft", "reducer.input_bore")
    doc = snapshot.build_document(s)
    group = doc.getObject("reducer_group")
    names = {o.Name for o in group.Group}
    assert {"reducer", "reducer__input_bore", "reducer__output_flange", "reducer__motor_flange"} <= names
    part = doc.getObject("reducer")
    assert part.FapComponent == "reducer.harmonic-drive-llc.csf-25-100-2uh" and part.FapCategory == "reducer"
    mk = doc.getObject("reducer__output_flange")
    assert mk.Label == "reducer.output_flange" and mk.FapPortType == "mechanical.flange"
    assert doc.getObject("motor__shaft").FapConnected == "是" and mk.FapConnected == "否"
    # 标记圆盘中心在端口坐标系原点
    _, origin, _ = s.port_world("reducer.output_flange")
    c = mk.Shape.Solids[0].CenterOfMass  # 圆盘
    assert (c.x, c.y) == pytest.approx(tuple(origin[:2]), abs=1e-6) and abs(c.z - origin[2]) < 1.0
    FreeCAD.closeDocument(doc.Name)


@pytest.mark.freecad
def test_manual_assembly_connect_and_live_check(gui):
    """ADR-0048 第 5 条：人选两个接口标记连接，校验窗口自动校验并着色；与 AI 用同一场景与工具。"""
    import FreeCAD
    import FreeCADGui

    from freecad_addon.core import live_check
    from freecad_addon.gui.check_panel import CheckPanel, PortConnector
    from freecad_addon.gui.host import ToolsHost

    host = ToolsHost(lambda: REAL, note="组件库：真实厂商组件（测试）")
    panel, conn = CheckPanel(host=host), PortConnector(host)
    try:
        assert panel.result["mode"] == "empty"
        box = []
        for n, (inst, cid) in enumerate((("motor", "servo_motor.yaskawa-electric-corporation.sgm7j-02a"),
                                         ("reducer", "reducer.harmonic-drive-llc.csf-25-100-2uh")), start=1):
            host.call_in_background("place_component", {"instance": inst, "component_id": cid}, box.append)
            _pump_until(gui, lambda n=n: len(box) == n)
        _pump_until(gui, lambda: len(panel.layout_state["instances"]) == 2 and panel.result["mode"] == "interface")
        FreeCADGui.Selection.clearSelection()
        assert conn.connect_selected() is False and "选两个接口标记" in conn.last  # 没选就提示
        doc = FreeCAD.getDocument("FapLayout")
        FreeCADGui.Selection.addSelection(doc.getObject("motor__shaft"))
        FreeCADGui.Selection.addSelection(doc.getObject("reducer__input_bore"))
        assert conn.selected_refs() == ["motor.shaft", "reducer.input_bore"]
        assert conn.connect_selected() is True
        _pump_until(gui, lambda: conn.last.startswith("已连接") or conn.last.startswith("没有连接"))
        assert conn.last == "已连接 motor.shaft ↔ reducer.input_bore"
        _pump_until(gui, lambda: panel.layout_state["connections"])
        r = panel.result
        assert r["mode"] == "interface" and r["overall"] == "fail"  # 光轴配键槽孔
        assert r["ports"]["motor.shaft"] == "fail"
        gdoc = FreeCADGui.getDocument("FapLayout")
        assert tuple(gdoc.getObject("motor__shaft").ShapeColor[:3]) == pytest.approx(live_check.STATUS_COLORS["fail"], abs=0.01)
        assert "C2 圆柱配合：不通过" in panel.report.toPlainText()
        # 填需求后按需求校验全部 11 项
        panel.inputs["output_torque_cont_nm"].setText("25")
        panel.inputs["output_speed_rpm"].setText("30")
        assert panel.apply_form() and panel.result["mode"] == "full"
    finally:
        panel.close()
        host.tools.close()
