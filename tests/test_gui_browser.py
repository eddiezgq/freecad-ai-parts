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
