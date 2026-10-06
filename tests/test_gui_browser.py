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


@pytest.mark.freecad
def test_project_is_saved_in_fcstd_and_restored(gui, tmp_path):
    """ADR-0049 第 1、2 条：布局文档就地更新；方案记录随 .FCStd 保存；打开后恢复方案，场景一致。"""
    import FreeCAD

    from freecad_addon.core import project
    from freecad_addon.fc import project_doc, snapshot
    from freecad_addon.gui.check_panel import CheckPanel
    from freecad_addon.gui.host import ToolsHost

    host = ToolsHost(lambda: REAL, note="组件库：真实厂商组件（测试）")
    panel = CheckPanel(host=host)
    try:
        box = []
        for n, (name, args) in enumerate((
                ("place_component", {"instance": "motor",
                                     "component_id": "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"}),
                ("place_component", {"instance": "reducer", "component_id": "reducer.harmonic-drive-llc.csf-25-100-2uh",
                                     "position_mm": [0, 0, 200]}),
                ("connect_ports", {"a": "motor.shaft", "b": "reducer.input_bore"})), start=1):
            host.call_in_background(name, args, box.append)
            _pump_until(gui, lambda n=n: len(box) == n)
        _pump_until(gui, lambda: panel.layout_state["connections"])
        doc = FreeCAD.getDocument(snapshot._target["name"])
        user_box = doc.addObject("Part::Box", "UserBox")  # 用户自己的对象：就地更新时保留
        host.call_in_background("place_component", {"instance": "drive", "component_id":
                                "drive.yaskawa-america-inc.sgd7s-1r6a", "position_mm": [150, 0, 0]}, box.append)
        _pump_until(gui, lambda: len(box) == 4 and len(panel.layout_state["instances"]) == 3)
        assert doc.getObject("UserBox") is user_box
        panel.set_requirement({"output_torque_cont_nm": 25, "output_speed_rpm": 30})
        rec = project.loads(project_doc.read(doc))
        assert rec["requirement"]["output_speed_rpm"] == 30 and len(rec["layout"]["instances"]) == 3
        before = panel.layout_state
        path = str(tmp_path / "joint.FCStd")
        doc.saveAs(path)
        FreeCAD.closeDocument(doc.Name)
        # 场景被清空后，打开文件恢复
        for k, inst in enumerate(("motor", "reducer", "drive"), start=len(box) + 1):
            host.call_in_background("place_component", {"instance": inst, "remove": True}, box.append)
            _pump_until(gui, lambda k=k: len(box) == k)
        opened = FreeCAD.openDocument(path)
        FreeCAD.setActiveDocument(opened.Name)
        notes = []
        assert panel.restore(notes.append) is None
        _pump_until(gui, lambda: notes)
        _pump_until(gui, lambda: len(panel.layout_state["instances"]) == 3)
        assert notes == [[]] and not project.diff(before, panel.layout_state)["changed"]
        assert snapshot._target["name"] == opened.Name and opened.getObject("motor").FapCategory == "servo_motor"
        assert panel.requirement["output_speed_rpm"] == 30
        FreeCAD.closeDocument(opened.Name)
    finally:
        snapshot.set_target(snapshot.DOC_NAME)
        panel.close()
        host.tools.close()


@pytest.mark.freecad
def test_dragging_a_part_writes_back_to_the_scene(gui):
    """ADR-0049 第 3 条：用户移动零件后场景随之改变，已连接的刚性组一起动；同步造成的改动不回写。"""
    import FreeCAD

    from freecad_addon.fc import snapshot
    from freecad_addon.gui.check_panel import CheckPanel
    from freecad_addon.gui.host import ToolsHost

    host = ToolsHost(lambda: REAL, note="组件库：真实厂商组件（测试）")
    panel = CheckPanel(host=host)
    try:
        box = []
        for n, (name, args) in enumerate((
                ("place_component", {"instance": "motor",
                                     "component_id": "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"}),
                ("place_component", {"instance": "reducer", "component_id": "reducer.harmonic-drive-llc.csf-25-100-2uh",
                                     "position_mm": [0, 0, 200]}),
                ("connect_ports", {"a": "motor.shaft", "b": "reducer.input_bore"}),
                ("place_component", {"instance": "drive", "component_id": "drive.yaskawa-america-inc.sgd7s-1r6a",
                                     "position_mm": [150, 0, 0]})), start=1):
            host.call_in_background(name, args, box.append)
            _pump_until(gui, lambda n=n: len(box) == n)
        _pump_until(gui, lambda: len(panel.layout_state["instances"]) == 3)
        gui.processEvents()
        assert panel.drag is not None and not panel.drag.pending  # 同步造成的改动没有排队
        pos = {i["instance"]: i["position_mm"] for i in panel.layout_state["instances"]}
        doc = FreeCAD.getDocument(snapshot._target["name"])
        # 用户把电机挪到 x=50：减速器与它是一个刚性组，一起挪；驱动器不动
        pl = doc.getObject("motor").Placement
        pl.Base = FreeCAD.Vector(50, 0, 0)
        doc.getObject("motor").Placement = pl
        assert "motor" in panel.drag.pending
        _pump_until(gui, lambda: {i["instance"]: i["position_mm"] for i in panel.layout_state["instances"]}["motor"]
                    == pytest.approx([50, 0, 0]))
        new = {i["instance"]: i["position_mm"] for i in panel.layout_state["instances"]}
        assert new["reducer"] == pytest.approx([pos["reducer"][0] + 50, pos["reducer"][1], pos["reducer"][2]])
        assert new["drive"] == pytest.approx(pos["drive"])
        # 拖动接口标记不回写
        mk = doc.getObject("drive__mount")
        mpl = mk.Placement
        mpl.Base = FreeCAD.Vector(999, 0, 0)
        mk.Placement = mpl
        assert not panel.drag.pending
    finally:
        panel.close()
        host.tools.close()


@pytest.mark.freecad
def test_ai_changes_become_a_proposal_to_accept_or_reject(gui):
    """ADR-0049 第 4 条：AI 一轮改动后列为提案；拒绝恢复原状，接受保留；未处理时手动改动视为接受。"""
    import sys

    sys.path.insert(0, str(ROOT / "tests"))
    from test_chat_panel import ScriptedLLM, reply, use

    from freecad_addon.gui.check_panel import CheckPanel
    from freecad_addon.gui.host import ToolsHost
    from freecad_addon.gui.panel import ChatPanel

    M = "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"
    R = "reducer.harmonic-drive-llc.csf-25-100-2uh"

    def script():
        return [reply(use(1, "place_component", {"instance": "motor", "component_id": M}),
                      use(2, "place_component", {"instance": "reducer", "component_id": R,
                                                 "position_mm": [0, 0, 200]})),
                reply(use(3, "connect_ports", {"a": "motor.shaft", "b": "reducer.input_bore"})),
                reply({"type": "text", "text": "电机与减速器已对接。"}, stop="end_turn")]

    host = ToolsHost(lambda: REAL, note="组件库：真实厂商组件（测试）")
    checks = CheckPanel(host=host)
    chat = ChatPanel(llm_factory=lambda: ScriptedLLM(script() + script() + [
        reply(use(4, "place_component", {"instance": "drive", "component_id": "drive.yaskawa-america-inc.sgd7s-1r6a",
                                         "position_mm": [150, 0, 0]})),
        reply({"type": "text", "text": "加了驱动器。"}, stop="end_turn")]), host=host)
    try:
        assert chat.review.isChecked()
        # 第一轮：拒绝 → 恢复为空
        assert chat.send("装配电机与减速器")
        _pump_until(gui, lambda: not chat.busy and host.pending is not None)
        _pump_until(gui, lambda: not checks.proposal_box.isHidden() and not checks.reject_button.isHidden())
        text = checks.proposal_text.text()
        assert "增加：motor、reducer" in text and "新连接：motor.shaft ↔ reducer.input_bore" in text
        assert "电机与减速器已对接" in text
        notes = []
        assert checks.reject(notes.append)
        _pump_until(gui, lambda: notes)
        assert notes == [[]] and host.pending is None and host.layout["instances"] == []
        _pump_until(gui, lambda: "已恢复原状" in checks.proposal_text.text())
        # 第二轮：接受 → 保留
        assert chat.send("再装一次")
        _pump_until(gui, lambda: not chat.busy and host.pending is not None)
        checks.accept_button.click()
        assert host.pending is None and len(host.layout["instances"]) == 2
        # 第三轮：提案未处理时手动改动视为接受
        assert chat.send("加一个驱动器")
        _pump_until(gui, lambda: not chat.busy and host.pending is not None)
        box = []
        host.call_in_background("place_component", {"instance": "drive", "position_mm": [180, 0, 0]}, box.append)
        _pump_until(gui, lambda: box)
        assert host.pending is None and len(host.layout["instances"]) == 3
    finally:
        chat.close()
        checks.close()
        host.tools.close()


@pytest.mark.freecad
def test_selection_panel_finds_and_places_a_candidate(gui):
    """ADR-0051 第 1 条：不经对话，在选型面板填需求、查找、放入布局；校验窗口按全部 11 项校验。"""
    import json

    from freecad_addon.core import selection
    from freecad_addon.core.system_layout import mechanical_connections
    from freecad_addon.gui.check_panel import CheckPanel
    from freecad_addon.gui.host import ToolsHost
    from freecad_addon.gui.selection_panel import SelectionPanel

    req = json.loads((ROOT / "examples" / "joint-real-requirement.json").read_text(encoding="utf-8"))
    host = ToolsHost(lambda: REAL, note="组件库：真实厂商组件（测试）")
    checks, panel = CheckPanel(host=host), SelectionPanel(host=host)
    try:
        assert panel.find() is False and "至少要填" in panel.status.text()  # 空表单
        panel.set_requirement(req)
        assert panel.find() is True
        _pump_until(gui, lambda: panel.find_button.isEnabled())
        assert panel.rows and panel.table.rowCount() == len(panel.rows)
        row = panel.selected()
        assert row is not None and row.rank == 1
        assert "SGM7J-02A" in selection.cells(row)[2]
        _pump_until(gui, lambda: checks.requirement is not None)  # 查找时的需求同步到校验窗口
        # 先放一个无关零件，放入方案时应被清掉
        box = []
        host.call_in_background("place_component", {"instance": "stray", "component_id":
                                                    "reducer.harmonic-drive-llc.csf-14-50-2uh"}, box.append)
        _pump_until(gui, lambda: box)
        assert panel.place_selected(confirm=False) is True
        _pump_until(gui, lambda: panel.find_button.isEnabled())
        assert panel.status.text().startswith("已放入布局"), panel.status.text()
        lay = host.layout
        assert sorted(i["instance"] for i in lay["instances"]) == sorted(c["instance"] for c in row.system["components"])
        ordered, _ = mechanical_connections(row.system, REAL.get)
        assert {(c["a"], c["b"]) for c in lay["connections"]} == {(c["a"], c["b"]) for c in ordered}
        boxes = {i["instance"]: i["bbox_mm"] for i in lay["instances"]}
        cats = {c["instance"]: REAL.get(c["component"])["category"] for c in row.system["components"]}
        drive = next(n for n, c in cats.items() if c == "drive")
        others = max(b["max_mm"][0] for n, b in boxes.items() if n != drive)
        assert boxes[drive]["min_mm"][0] == pytest.approx(others + selection.GAP_MM, abs=1e-6)
        _pump_until(gui, lambda: len(checks.layout_state["instances"]) == len(lay["instances"]))
        r = checks.recheck()
        assert r["mode"] == "full" and r["overall"] == "unknown"  # 只有 C3（可配置法兰）待确认
        assert not [c for c in r["checks"] if c["status"] == "fail"]
    finally:
        panel.close()
        checks.close()
        host.tools.close()


@pytest.mark.freecad
def test_bom_panel_follows_the_scene_and_exports(gui, tmp_path):
    """ADR-0051 第 2 条：BOM 面板随场景刷新；导出的 CSV 与 export_system 一致。"""
    from freecad_addon.core.live_check import system_from_layout
    from freecad_addon.gui.bom_panel import BomPanel
    from freecad_addon.gui.host import ToolsHost
    from mcp_server import tools

    host = ToolsHost(lambda: REAL, note="组件库：真实厂商组件（测试）")
    dock = BomPanel(host=host)
    try:
        assert dock.result["rows"] == [] and not dock.csv_button.isEnabled()
        assert dock.export("csv", str(tmp_path / "x.csv")) is None and "还没有零件" in dock.status.text()
        box = []
        for n, (inst, cid) in enumerate((("motor", "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"),
                                         ("reducer", "reducer.harmonic-drive-llc.csf-25-100-2uh"),
                                         ("drive", "drive.yaskawa-america-inc.sgd7s-1r6a")), start=1):
            host.call_in_background("place_component", {"instance": inst, "component_id": cid}, box.append)
            _pump_until(gui, lambda n=n: len(box) == n)
        _pump_until(gui, lambda: dock.table.rowCount() == 3)
        assert dock.csv_button.isEnabled() and dock.total.text().startswith("共 3 种、3 件")
        assert dock.custom.isHidden()  # 还没连接，没有定制要求
        host.call_in_background("connect_ports", {"a": "motor.mount_flange", "b": "reducer.motor_flange"},
                                box.append)
        _pump_until(gui, lambda: not dock.custom.isHidden())
        assert "须按" in dock.custom.toPlainText() and "第 65 页" in dock.custom.toPlainText()
        path = dock.export("csv", str(tmp_path / "bom.csv"))
        system, _ = system_from_layout(dock.layout_state, REAL.get)
        want = tools.export_system(REAL, system, format="bom_csv")["content"]
        assert Path(path).read_text(encoding="utf-8") == want
        host.call_in_background("place_component", {"instance": "drive", "remove": True}, box.append)
        _pump_until(gui, lambda: dock.table.rowCount() == 2)
        assert not dock.custom.isHidden()
    finally:
        dock.close()
        host.tools.close()


@pytest.mark.freecad
def test_swap_suggestion_fixes_a_failed_shaft_fit(gui):
    """ADR-0052：光轴电机配键槽孔减速器 C2 不通过；换件建议给出带键电机，换上后 C2 通过。"""
    from freecad_addon.gui.check_panel import CheckPanel
    from freecad_addon.gui.host import ToolsHost

    plain = "servo_motor.yaskawa-electric-corporation.sgm7j-02a"
    keyed = "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"
    host = ToolsHost(lambda: REAL, note="组件库：真实厂商组件（测试）")
    panel = CheckPanel(host=host)
    try:
        box = []
        steps = [("place_component", {"instance": "motor", "component_id": plain}),
                 ("place_component", {"instance": "reducer", "component_id": "reducer.harmonic-drive-llc.csf-25-100-2uh"}),
                 ("connect_ports", {"a": "motor.mount_flange", "b": "reducer.motor_flange"}),
                 ("connect_ports", {"a": "motor.shaft", "b": "reducer.input_bore"})]
        for n, (name, args) in enumerate(steps, start=1):
            host.call_in_background(name, args, box.append)
            _pump_until(gui, lambda n=n: len(box) == n)
        _pump_until(gui, lambda: len(panel.layout_state["connections"]) == 2)
        r = panel.recheck()
        assert {c["check"]: c["status"] for c in r["checks"]}["C2"] == "fail"
        sb = panel.swap
        assert sb.instance.currentText() == "motor"  # 默认选结论最差的
        assert sb.find() is True
        _pump_until(gui, lambda: not sb.busy)
        assert sb.suggestions and sb.suggestions[0]["component_id"] == keyed
        assert "C2 圆柱配合：不通过 → 通过" in sb.detail.text()
        assert sb.swap_selected() is True
        _pump_until(gui, lambda: not sb.busy)
        assert sb.status.text().startswith("已换上"), sb.status.text()
        _pump_until(gui, lambda: any(i["component"] == keyed for i in panel.layout_state["instances"])
                    and len(panel.layout_state["connections"]) == 2)
        r = panel.recheck()
        assert {c["check"]: c["status"] for c in r["checks"]}["C2"] == "pass"
    finally:
        panel.close()
        host.tools.close()


@pytest.mark.freecad
def test_sentence_is_parsed_into_the_form_without_searching(gui):
    """ADR-0054：一句话需求经解析（录制回放）只填表单，不自动查找；缺密钥时提示可直接填表。"""
    import json

    from engine import requirement_parse as rp
    from freecad_addon.gui.host import ToolsHost
    from freecad_addon.gui.selection_panel import SelectionPanel
    from ingest.llm_extract import RecordedClient

    joint2 = json.loads((ROOT / "examples" / "joint2-requirement.json").read_text(encoding="utf-8"))
    host = ToolsHost(lambda: REAL, note="组件库：真实厂商组件（测试）")
    panel = SelectionPanel(host=host, client_factory=lambda: RecordedClient(rp.RECORDINGS_DIR))
    try:
        panel.sentence.setPlainText(joint2["statement"])
        assert panel.parse() is True
        _pump_until(gui, lambda: not panel.parsing)
        assert panel.parse_note.text().startswith("解析完成"), panel.parse_note.text()
        req, err = panel.requirement()
        assert err is None and req == {k: v for k, v in joint2.items() if k != "id"}
        assert panel.rows == [] and panel.table.rowCount() == 0  # 没有自动查找
        panel.clear()
        assert panel.extra == {} and panel.inputs["output_torque_cont_nm"].text() == ""

        def no_key():
            raise RuntimeError("未设置 ANTHROPIC_API_KEY")

        panel._client_factory = no_key
        panel.sentence.setPlainText("随便一句")
        assert panel.parse() is False and "可以直接在下表填数" in panel.parse_note.text()
    finally:
        panel.close()
        host.tools.close()


@pytest.mark.freecad
def test_enterprise_component_is_marked_in_browser_and_bom(gui, tmp_path):
    """ADR-0055：企业库叠加在公共库上，企业补过的组件在浏览器与 BOM 中标为企业库。"""
    from freecad_addon.gui.bom_panel import BomPanel
    from freecad_addon.gui.browser import LibraryBrowser
    from freecad_addon.gui.host import ToolsHost
    from kb.enterprise import EnterpriseLibrary
    from kb.library import LayeredLibrary

    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    spec = tmp_path / "spec.pdf"
    spec.write_bytes(b"%PDF fake")
    doc = ent.register_document(spec, "供应商规格书", "张工")["id"]
    cid = "reducer.harmonic-drive-llc.csf-25-100-2uh"
    ent.set_value(cid, "params/backlash_arcmin", {"value": 1, "method": "manual", "confidence": 1, "reviewed": True,
                                                  "source": {"doc": doc, "page": 2, "note": "原文“1 arcmin”；录入人：张工"}},
                  "张工", REAL.get)
    lib = LayeredLibrary(ent, REAL)
    host = ToolsHost(lambda: lib, note="企业库（测试）")
    browser, bom = LibraryBrowser(host=host), BomPanel(host=host)
    try:
        browser.text.setText("csf 25-100")
        rows = [r.id for r in browser._rows]
        browser.table.selectRow(rows.index(cid))
        assert "来自企业库" in browser.detail.toHtml()
        box = []
        host.call_in_background("place_component", {"instance": "reducer", "component_id": cid}, box.append)
        _pump_until(gui, lambda: bom.table.rowCount() == 1)
        assert bom.table.item(0, len(bom_view_headers()) - 1).text() == "企业"
    finally:
        browser.close()
        bom.close()
        host.tools.close()


def bom_view_headers():
    from freecad_addon.core import bom_view

    return bom_view.HEADERS
