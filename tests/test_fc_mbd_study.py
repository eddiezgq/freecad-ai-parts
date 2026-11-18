"""装配体多体动力学的流程与窗口（ADR-0097 D5c 验收）。需要 FreeCAD；窗口测试要显示环境（CI 用 xvfb）。

验收件同 D5b：平缝机挑线机构 STEP。流程：导入 → 规则草稿 → 确认建装配 → 驱动上轴 → 运动学 → 核查通过、曲线齐全；
动画第 k 帧把零件摆到结果位姿（挑线杆上 M 点的位置与结果一致到 1e-6 mm），复位回到原位；窗口里同样走一遍，并能算模态。
"""

from __future__ import annotations

import os
import time

import numpy as np
import pytest

pytestmark = pytest.mark.freecad

STEEL = "06ae5c92-de7b-46c9-984d-4dd87964bc5c"


@pytest.fixture
def step(tmp_path):
    import FreeCAD as App
    import Import

    from tests.test_fc_mbd_mates import build_parts

    src = App.newDocument("takeup_src2")
    objs = build_parts(src)
    path = tmp_path / "takeup.step"
    Import.export(objs, str(path))
    App.closeDocument(src.Name)
    return path


def _steel(objs):
    import Materials

    mat = Materials.MaterialManager().getMaterial(STEEL)
    for o in objs:
        o.ShapeMaterial = mat


def test_study_flow_and_animation(step):
    import FreeCAD as App

    from analysis.mbd.assembly import AssemblyError
    from freecad_addon.core import mbd_study as ST
    from tests.test_fc_mbd_mates import geometry

    doc = App.newDocument("study")
    try:
        objs, _, found, draft = ST.draft_from_step(str(step), doc)
        asm = ST.build(doc, objs, found, draft["accept"], draft["ground"])
        with pytest.raises(AssemblyError, match="材料"):          # STEP 不带材料：不估，报出来
            ST.make_model(asm, [], {"type": "kinematic"})
        _steel(objs)
        doc.recompute()
        lab = {o.Name: o.Label for o in objs}
        model0, _ = ST.make_model(asm, [], {"type": "kinematic"})
        drive = next(j["id"] for j in model0["joints"] if j["body_i"] == "ground"
                     and lab.get(j["body_j"]) == "上轴挑线曲柄")
        model, _ = ST.make_model(asm, [{"joint": drive, "kind": "speed", "value": 600}],
                                 {"type": "kinematic", "end_time_s": 0.1, "output_steps": 20})
        lever = next(o for o in objs if o.Label == "挑线杆")
        M = geometry()[2]
        model["requests"] = [{"id": "M", "type": "point", "body": lever.Name, "point_mm": M.tolist()}]
        data, _ = ST.run(model)
        assert all(v["status"] == "pass" for v in data["verification"] if v["key"] == "constraint_residual")
        names = ST.curves(data)
        assert any(n.startswith("驱动 drive_") for n in names) and any("反力大小" in n for n in names)
        assert ST.verdict(data)[0].startswith("约束残差")
        an = ST.Animator(model, data, doc)
        assert set(an.objs) == {b["id"] for b in model["bodies"]}
        orig = App.Placement(lever.Placement)
        for k in (0, 7, 20):
            an.apply(k)
            pos = lever.Placement.multVec(orig.inverse().multVec(App.Vector(*M)))
            assert np.allclose([pos.x, pos.y, pos.z], data["requests"]["M"]["pos_mm"][k], atol=1e-6)
        an.restore()
        assert lever.Placement.isSame(orig, 1e-12)
    finally:
        App.closeDocument(doc.Name)


@pytest.fixture(scope="module")
def gui():
    import FreeCAD  # noqa: F401
    import FreeCADGui

    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    FreeCADGui.showMainWindow()
    import importlib
    import sys

    # 同一进程里前面的测试在没有界面时导入过 Assembly 的 Python 模块（它们按导入时有没有界面决定加载哪些部分）；
    # 真实使用时界面总是先起来，这里重新加载以模拟真实情况
    for name in ("UtilsAssembly", "JointObject"):
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    from PySide import QtWidgets

    return QtWidgets.QApplication.instance()


def _pump(app, cond, timeout=120):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.005)
    assert cond(), "超时"


def test_panel_imports_confirms_runs_and_animates(gui, step, tmp_path):
    import FreeCAD as App
    from PySide import QtCore

    from freecad_addon.gui.mbd_assembly_panel import MbdAssemblyPanel

    doc = App.newDocument("panel")
    panel = MbdAssemblyPanel()
    try:
        assert panel.load_step(str(step), doc) is True
        assert panel.cands.rowCount() == 4 and panel.ground.currentText() == "机壳"
        assert all(panel.cands.item(i, 0).checkState() == QtCore.Qt.Checked for i in range(4))
        assert panel.confirm() is False and "材料" in panel.status.text()      # 还没材料：说清楚为什么不能算
        _steel(panel.objs)
        doc.recompute()
        assert panel.refresh_model() is True and panel.run_btn.isEnabled()
        lab = {o.Name: o.Label for o in panel.objs}
        drive = next(j["id"] for j in panel.model["joints"] if j["body_i"] == "ground" and lab.get(j["body_j"]) == "上轴挑线曲柄")
        assert panel.set_drive(drive, "speed", 600)
        panel.kind.setCurrentIndex(panel.kind.findData("kinematic"))
        panel.end.setText("0.1")
        panel.steps.setText("20")
        assert panel.compute() is True
        _pump(gui, lambda: not panel.busy)
        assert panel.data is not None, panel.status.text()
        assert "积分器" not in panel.status.text()                            # 运动学不用积分器，不给建议（ADR-0098 E3）
        panel.integ.setCurrentIndex(panel.integ.findData("HHT"))
        assert panel.settings()[1]["integrator"] == "HHT"
        panel.integ.setCurrentIndex(panel.integ.findData("auto"))
        assert "integrator" not in panel.settings()[1]
        assert "通过" in panel.verdict.text() and panel.curve.count() > 5 and panel.slider.isEnabled()
        lever = next(o for o in panel.objs if o.Label == "挑线杆")
        orig = App.Placement(lever.Placement)
        panel.slider.setValue(10)
        assert not lever.Placement.isSame(orig, 1e-9) and panel.time.text().startswith("t = 0.05")
        panel.restore()
        assert lever.Placement.isSame(orig, 1e-12)
        # D8b：柔性零件表列出全部零件、默认刚性；报告写出来（不用 AI）
        assert panel.flexparts.rowCount() == len(panel.model["bodies"]) and panel.flex_settings() == {}
        assert panel.set_flex(lever.Name, "45-QT") and panel.flex_settings() == {lever.Name: {"material": "45-QT"}}
        assert panel.set_flex(lever.Name, "45-QT", "nonlinear_beam")                 # ADR-0101 F3
        assert panel.flex_settings() == {lever.Name: {"material": "45-QT", "kind": "nonlinear_beam"}}
        assert panel.set_flex(lever.Name, None) and panel.flex_settings() == {}
        got = panel.write_report(tmp_path / "rep", use_ai=False)
        assert got is not None and got["docx"].is_file() and (tmp_path / "rep" / "result.json").is_file()
        assert "草稿" in panel.status.text()
        # 模态：不驱动，先静平衡再线性化（单自由度：一阶）
        panel.set_drive(drive, "none", "")
        panel.kind.setCurrentIndex(panel.kind.findData("static_then_linear"))
        assert panel.compute() is True
        _pump(gui, lambda: not panel.busy)
        assert panel.modes.isVisible() or panel.modes.rowCount() >= 1, panel.status.text()
        # 动力学（不驱动，自由摆）、积分器自动：普通机构建议 DOP853，状态栏写明理由（ADR-0098 E3）
        panel.kind.setCurrentIndex(panel.kind.findData("dynamic"))
        panel.end.setText("0.02")
        panel.steps.setText("4")
        assert panel.compute() is True
        _pump(gui, lambda: not panel.busy)
        assert "积分器 DOP853：" in panel.status.text(), panel.status.text()
        assert panel.modes.rowCount() >= 1
    finally:
        panel.close()
        App.closeDocument(doc.Name)
