"""问渠CAM 加工树（ADR-0106 Q1）：作业 → 装夹 → 工序是文档对象；起草、核对、确认、调顺序、计算、存盘再打开。不开界面。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.freecad
EX = Path(__file__).resolve().parents[1] / "examples" / "wenquest-cam"


def _ex():
    sys.path.insert(0, str(EX))
    import build_examples as B

    return B


def _turn_job(doc):
    from freecad_addon.fc import cam_objects as CO

    B = _ex()
    m = doc.addObject("Part::Feature", "Shaft")
    m.Shape = B.shaft()
    doc.recompute()
    return CO.new_job(doc, m, "turn", threads="0, -26, 24, 1.5")


def test_turn_features_from_solid():
    from freecad_addon.fc import cam_doc

    ft = cam_doc.turn_features(_ex().shaft())
    assert ft["segments"] == [[30, 40], [40, 60], [35, 25], [24, 30]]
    assert ft["grooves"] == [{"z": -27.0, "width": 3.0, "d": 20.0}]
    assert ft["bore"] == [[16, 20], [12, 15]] and ft["chamfer_mm"] == 0


def test_turn_tree_draft_confirm_calculate_and_reload(tmp_path):
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO

    doc = App.newDocument("camtree")
    try:
        job = _turn_job(doc)
        right, left = CO.setups(job)
        assert (right.Side, left.Side) == ("right", "left")
        CO.draft(job)
        assert [o.OpKind for o in CO.ops(right)] == ["rough", "finish", "groove", "thread", "drill", "bore"]
        assert [o.OpKind for o in CO.ops(left)] == ["rough", "finish"]
        assert all(o.Status == "草稿" and o.Shape.Edges for s in CO.setups(job) for o in CO.ops(s))
        # 还有草稿：只仿真，不出正式程序
        r = CO.calculate(job)
        assert not any(p.get("release") for p in r["data"]["programs"])
        assert any("确认后才出正式程序" in c["text"] for c in json.loads(job.Result)["checks"])
        # 全部确认 → 出程序；与例子 1（同样的零件和参数）的仿真指纹一致
        for s in CO.setups(job):
            for o in CO.ops(s):
                CO.confirm(o)
        job.Fixture = "15, 80"
        job.Item = "带螺纹的阶梯轴（示例）"                       # 程序头里有零件名：与例子 1 同名才能比指纹
        r = CO.calculate(job)
        fps = [p["machine_sim"]["fingerprint"] for p in r["data"]["programs"]]
        sample = json.loads((EX / "01-shaft-turning/results.json").read_text(encoding="utf-8"))
        assert fps == [p["machine_sim"]["fingerprint"] for p in sample["programs"]]
        assert sorted(json.loads(job.Programs)) == ["O1001_fanuc.nc", "O1002_fanuc.nc"]
        # 存盘再打开：树、刀路、结果都在
        f = tmp_path / "shaft-cam.FCStd"
        doc.saveAs(str(f))
        App.closeDocument(doc.Name)
        doc = App.openDocument(str(f))
        job = next(o for o in doc.Objects if CO.is_job(o))
        right = CO.setups(job)[0]
        assert [o.OpKind for o in CO.ops(right)][:2] == ["rough", "finish"]
        assert all(o.Shape.Edges for o in CO.ops(right))
        r2 = CO.calculate(job)
        assert [p["machine_sim"]["fingerprint"] for p in r2["data"]["programs"]] == fps
    finally:
        App.closeDocument(doc.Name)


def test_out_of_range_cannot_be_confirmed_and_reorder():
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO

    doc = App.newDocument("camtree2")
    try:
        job = _turn_job(doc)
        CO.draft(job)
        right = CO.setups(job)[0]
        rough = CO.ops(right)[0]
        rough.Vc = 400.0                                       # 样本范围 150–250
        with pytest.raises(CO.CamObjError, match="超出刀具样本范围"):
            CO.confirm(rough)
        assert rough.Status == "草稿"
        rough.Vc = 220.0
        CO.regenerate(rough)
        CO.confirm(rough)
        assert rough.Status == "已确认"
        CO.move(CO.ops(right)[3], -1)                          # 车螺纹移到切槽前面
        assert [o.OpKind for o in CO.ops(right)][2:4] == ["thread", "groove"]
        setup = CO.build_setup(job)
        assert [s["kind"] for s in setup["ops"]["right"]][2:4] == ["thread", "groove"]
        assert setup["ops"]["right"][0]["cut"]["vc"] == 220.0
    finally:
        App.closeDocument(doc.Name)


def test_mill_tree_with_picked_faces():
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO

    B = _ex()
    doc = App.newDocument("cammill")
    try:
        m = doc.addObject("Part::Feature", "Block")
        m.Shape = B.block()
        doc.recompute()
        job = CO.new_job(doc, m, "mill")
        job.ToolLengths = json.dumps({"EM10": 120, "DR8.5": 140})
        CO.draft(job)
        s = CO.setups(job)[0]
        assert [o.OpKind for o in CO.ops(s)] == ["pocket", "drill"]
        for o in CO.ops(s):
            CO.confirm(o)
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        sample = json.loads((EX / "02-block-milling/results.json").read_text(encoding="utf-8"))
        assert p["release"] is not None and abs(p["time"]["total_s"] - sample["total_time_s"]) < 0.05
        # 点选孔的圆柱面：只钻选中的孔
        hole = next(f"Face{i + 1}" for i, f in enumerate(m.Shape.Faces) if type(f.Surface).__name__ == "Cylinder")
        drill = CO.ops(s)[1]
        drill.Geometry = [(m, [hole])]
        CO.regenerate(drill)
        assert sum(1 for x in json.loads(drill.Moves) if x["t"] == "drill") == 1
    finally:
        App.closeDocument(doc.Name)


def test_add_and_copy_ops():
    """新建工序（铣外轮廓）：铣到底撞平口钳，整机仿真不通过、不出程序；复制工序放在原工序后面；车削新建切槽取第一个槽"""
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO

    B = _ex()
    doc = App.newDocument("camadd")
    try:
        m = doc.addObject("Part::Feature", "Block")
        m.Shape = B.block()
        doc.recompute()
        job = CO.new_job(doc, m, "mill")
        job.ToolLengths = json.dumps({"EM10": 120, "DR8.5": 140})
        CO.draft(job)
        s = CO.setups(job)[0]
        prof = CO.add_op(s, "profile")
        assert prof.Status == "草稿" and prof.Shape.Edges and CO.ops(s)[-1] is prof
        with pytest.raises(CO.CamObjError, match="铣削没有这种工序"):
            CO.add_op(s, "thread")
        for o in CO.ops(s):
            CO.confirm(o)
        r = CO.calculate(job)
        assert not any(p.get("release") for p in r["data"]["programs"])
        assert any(c["level"] == "error" for c in json.loads(job.Result)["checks"])
        c = CO.copy_op(CO.ops(s)[0])
        assert CO.ops(s)[1] is c and c.Status == "草稿" and c.Moves == CO.ops(s)[0].Moves
    finally:
        App.closeDocument(doc.Name)
    doc = App.newDocument("camaddturn")
    try:
        job = _turn_job(doc)
        right = CO.setups(job)[0]
        g = CO.add_op(right, "groove")
        assert g.FeatureIndex == 0 and g.Shape.Edges and g.ToolId
        with pytest.raises(CO.CamObjError, match="没有能切槽"):
            CO.add_op(CO.setups(job)[1], "groove")
    finally:
        App.closeDocument(doc.Name)


@pytest.fixture(scope="module")
def gui():
    import os

    import FreeCADGui

    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    FreeCADGui.showMainWindow()
    from PySide import QtWidgets

    return QtWidgets.QApplication.instance()


def test_panels_edit_confirm_calculate_save(gui, tmp_path):
    """界面：新建车削作业（命令）→ 作业面板起草 → 工序面板改 vc 超范围变红、不能确认 → 改回、确认全部 → 计算 → 保存程序与工艺卡"""
    import FreeCAD as App
    import FreeCADGui

    from freecad_addon.fc import cam_objects as CO
    from freecad_addon.gui import cam_tree_panels as P

    B = _ex()
    doc = App.newDocument("campanels")
    try:
        m = doc.addObject("Part::Feature", "Shaft")
        m.Shape = B.shaft()
        doc.recompute()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(m)
        P.NewJobCommand("turn").Activated()
        jp = P._LAST
        assert isinstance(jp, P.JobPanel)
        jp.threads.setPlainText("0, -26, 24, 1.5")
        jp.do_draft(False)
        assert "起草了 8 道工序" in jp.status.text()
        job = jp.job
        P._close()
        rough = CO.ops(CO.setups(job)[0])[0]
        op_panel = P.edit(rough)
        op_panel.vc.setValue(400)
        assert "超出刀具样本范围" in op_panel.range.text() and "#c62828" in op_panel.range.text()
        assert op_panel.accept() is False and rough.Status == "草稿"
        op_panel.vc.setValue(200)
        assert op_panel.accept() is True and rough.Status == "已确认"
        for s in CO.setups(job):
            for o in CO.ops(s):
                if o.Status != "已确认":
                    CO.confirm(o)
        jp = P.edit(job)
        jp.do_calculate()
        assert jp.save.isEnabled(), jp.status.text()
        assert jp.checks.count() > 0
        files = jp.save_to(tmp_path)
        names = {f.name for f in files}
        assert {"O1001_fanuc.nc", "O1002_fanuc.nc", "工艺卡与程序单.docx"} <= names
        # 程序对比（Q6b）：同一个程序报“刀路相同”；改一个进给报出来，报告窗口能打开
        a = tmp_path / "O1001_fanuc.nc"
        assert "刀路相同" in jp.compare_files(a, a)
        txt = a.read_text(encoding="utf-8")
        import re as _re

        f0 = _re.search(r"F(\d+\.\d+)", txt).group(0)
        (tmp_path / "b.nc").write_text(txt.replace(f0, "F0.123", 1), encoding="utf-8")
        rep = jp.compare_files(a, tmp_path / "b.nc")
        assert "两版程序有差别" in rep and "F0.123" in rep
        dlg = P.show_report(jp.form, "程序对比", rep)
        assert "F0.123" in dlg.view.toPlainText()
        dlg.close()
        P._close()
    finally:
        App.closeDocument(doc.Name)


def test_cam_workbench_has_tree_commands(gui, monkeypatch):
    import FreeCADGui

    from freecad_addon.gui import cam_brand

    monkeypatch.setattr(cam_brand, "_start_here", lambda: None)
    if cam_brand.WORKBENCH not in FreeCADGui.listWorkbenches():
        cam_brand.register()
    FreeCADGui.activateWorkbench(cam_brand.WORKBENCH)
    try:
        from PySide import QtWidgets

        app = QtWidgets.QApplication.instance()

        def menus():
            return {a.text(): [x.text() for x in a.menu().actions()] for a in FreeCADGui.getMainWindow().menuBar().actions()
                    if a.menu()}
        import time

        end = time.time() + 10
        while "问渠CAM" not in menus() and time.time() < end:
            app.processEvents()
            time.sleep(0.01)
        got = set(menus().get("问渠CAM") or [])
        assert {"新建车削作业", "新建铣削作业", "作业设置与计算…", "重算刀路", "确认工序", "复制工序", "上移", "下移",
                "隐藏 / 显示刀路", "新建工序"} <= got, got
    finally:
        FreeCADGui.activateWorkbench("NoneWorkbench")
