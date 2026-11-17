"""FEM 工作台里的三步（ADR-0093 补充十二第 3 步）：一句话起草 → 确认 → 计算并核查 → 出报告。需要 FreeCAD。

AI 用假客户端（给出“正确的 AI 会给的提议”，见 tests/test_assist_fea_draft.py）；真实 LLM 的回放在录屏演示里用。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.freecad

ROOT = Path(__file__).resolve().parent.parent
RJ = ROOT / "examples/apps/out/cobot_joint/RJ-201.step"
J2 = ROOT / "examples/apps/out/cobot_joint/J2-HSG.step"


@pytest.fixture
def doc(monkeypatch, tmp_path):
    import FreeCAD

    if os.environ.get("DISPLAY"):
        import FreeCADGui

        FreeCADGui.showMainWindow()
    monkeypatch.chdir(ROOT)
    d = FreeCAD.newDocument("fem_flow_test")
    d.saveAs(str(tmp_path / "flow.FCStd"))             # 存过盘：工作目录放在文档旁
    name = d.Name
    yield d
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)


def _part(doc, step: Path):
    import Part

    s = Part.Shape()
    s.read(str(step))
    o = doc.addObject("Part::Feature", step.stem.replace("-", "_"))
    o.Shape = s
    o.addProperty("App::PropertyString", "FapStepPath", "Fap", "")
    o.FapStepPath = str(step)
    doc.recompute()
    return o


def _samples():
    from assist import fea_draft as D

    return {s["id"]: s for s in json.loads(D.SAMPLES.read_text(encoding="utf-8"))["samples"]}


def test_sentence_to_report(doc):
    from assist import fea_draft as D
    from freecad_addon.fc import fem_flow as F
    from tests.test_assist_fea_draft import GOOD

    s = _samples()["S1-RJ201-torque"]
    part = _part(doc, RJ)
    out = F.draft_into(doc, s["statement"], [part], D.FakeClient(GOOD["S1-RJ201-torque"]))
    an = out["analysis"]
    assert not out["questions"] and not out["rejected"] and not out["errors"]
    types = sorted(o.TypeId for o in an.Group)
    assert "Fem::ConstraintFixed" in types and "Fem::ConstraintPython" in types          # 固定是 FEM 自带的；扭矩是本仓库的
    assert not [o for o in doc.Objects if o.Name.startswith("Fap_b")]                   # 用的是选中的零件，没有另导入一份
    with pytest.raises(F.FlowError, match="确认"):
        F.prepare_run(an)                                                                # AI 起草的，没确认不能算
    st = F.confirm_analysis(an, "测试工程师", False)
    assert st["provenance"]["confirmed_by"] == "测试工程师"
    study, wd = F.prepare_run(an)
    assert wd.parent.name == "flow_fea"
    res = F.compute(study, wd)
    assert res["status"] == "ok", res.get("messages")
    got = F.finish_run(an, res, wd)
    assert got["results"] and got["pipelines"]
    rep = F.make_report(an, number="QR-T-1", revision="A", reason="首次出稿")
    assert Path(rep["docx"]).is_file() and Path(rep["ledger"]).is_file()
    # 疲劳（ADR-0096 第 1 步）：RJ-201 的可信度没判“通过”（轴肩疑似奇异点），与安全系数同一规则——不给疲劳寿命
    with pytest.raises(F.FlowError, match="可信度核查没有判“通过”"):
        F.fatigue_inputs(an)
    # 计算后又改了算例：拒绝出报告
    import FreeCAD

    fx = next(o for o in an.Group if o.TypeId == "Fem::ConstraintFixed")
    fx.References = [(part, ("Face1",))]
    doc.recompute()
    with pytest.raises(F.FlowError, match="改过"):
        F.make_report(an, number="QR-T-1", revision="B", reason="x")
    with pytest.raises(F.FlowError, match="改过.*疲劳"):
        F.fatigue_inputs(an)
    assert FreeCAD.ActiveDocument is not None


def _shaft_study(tmp_path: Path, loads_extra=()) -> dict:
    """Ø35 × 100 的 45 钢轴：底面固定、顶面扭矩 350 N·m（τ = 16T / πd³ = 41.6 MPa，von Mises = √3 τ = 72.0 MPa）"""
    import Part

    from analysis.fea.geometry import faces

    step = tmp_path / "shaft.step"
    Part.makeCylinder(17.5, 100).exportStep(str(step))
    fs = faces(str(step))[0]
    bot = next(f["id"] for f in fs if abs(f["center"][2]) < 1e-6)
    top = next(f["id"] for f in fs if abs(f["center"][2] - 100) < 1e-6)
    return {"format": "fea-study/1", "name": "shaft", "bodies": [{"id": "s", "step_path": str(step), "material": "45-QT"}],
            "supports": [{"type": "fixed", "body": "s", "faces": [bot]}],
            "loads": [{"type": "torque", "body": "s", "faces": [top], "value_nm": 350,
                       "axis": {"origin_mm": [0, 0, 100], "dir": [0, 0, 1]}}, *loads_extra],
            "steps": [{"id": "s1", "type": "static"}], "mesh": {"size_mm": 4}}


def _fake_result(wd: Path, verdict: str) -> None:
    (wd / "result.json").write_text(json.dumps({"status": "ok", "data": {"steps": [
        {"id": "s1", "type": "static", "vm_max_mpa": 72.0, "trust": {"verdict": verdict, "items": []}}]}}), encoding="utf-8")


def test_fatigue_inputs_rules(doc, tmp_path):
    """疲劳的参考应力取自 FEM 的计算结果：没算过、可信度没通过、不止一个载荷，都说明原因、不给（不真算，结果用写好的文件）"""
    from freecad_addon.fc import fem_bridge as B
    from freecad_addon.fc import fem_flow as F

    an = B.study_to_fem(doc, _shaft_study(tmp_path), base_dir=tmp_path)
    with pytest.raises(F.FlowError, match="还没有计算结果"):
        F.fatigue_inputs(an)
    study, wd = F.prepare_run(an)
    (wd / "study.json").write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
    B._prop(an, "FapWorkDir", str(wd))
    for verdict, word in (("unknown", "未知"), ("fail", "不通过")):
        _fake_result(wd, verdict)
        with pytest.raises(F.FlowError, match=f"结论：{word}"):
            F.fatigue_inputs(an)
    _fake_result(wd, "pass")
    ref = F.fatigue_inputs(an)
    assert ref == {**ref, "stress_ref_mpa": 72.0, "load_ref": 350, "load_unit": "N·m", "material": "45-QT", "step": "s1"}
    # 另加重力：应力不再与扭矩成正比，不能按载荷谱换算
    an2 = B.study_to_fem(doc, _shaft_study(tmp_path, [{"type": "gravity", "body": "s", "acceleration_m_s2": [0, 0, -9.81]}]),
                         base_dir=tmp_path)
    study2, wd2 = F.prepare_run(an2)
    (wd2 / "study.json").write_text(json.dumps(study2, ensure_ascii=False), encoding="utf-8")
    B._prop(an2, "FapWorkDir", str(wd2))
    _fake_result(wd2, "pass")
    with pytest.raises(F.FlowError, match="只有一个载荷.*gravity"):
        F.fatigue_inputs(an2)


def test_questions_block_confirmation(doc):
    from assist import fea_draft as D
    from freecad_addon.fc import fem_flow as F
    from tests.test_assist_fea_draft import GOOD

    s = _samples()["S5-J2HSG-missing-load"]
    part = _part(doc, J2)
    out = F.draft_into(doc, s["statement"], [part], D.FakeClient(GOOD["S5-J2HSG-missing-load"]))
    assert any("大小" in q for q in out["questions"])
    with pytest.raises(F.FlowError, match="追问"):
        F.confirm_analysis(out["analysis"], "测试工程师", False)
    with pytest.raises(F.FlowError, match="不能算"):                                     # 声明处理了，但载荷、分析步还没补
        F.confirm_analysis(out["analysis"], "测试工程师", True)


def test_bad_input_is_explained(doc):
    from freecad_addon.fc import fem_flow as F

    with pytest.raises(F.FlowError, match="一句话"):
        F.draft_into(doc, "  ", [_part(doc, RJ)], None)
    with pytest.raises(F.FlowError, match="选中"):
        F.draft_into(doc, "随便", [], None)


def test_buttons_appear_in_fem_workbench():
    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    import time

    import FreeCADGui
    from PySide import QtWidgets

    from freecad_addon.gui import fem_commands

    FreeCADGui.showMainWindow()
    fem_commands.register()
    FreeCADGui.activateWorkbench("FemWorkbench")
    app = QtWidgets.QApplication.instance()
    for _ in range(50):
        app.processEvents()
        time.sleep(0.01)
    texts = {a.text() for tb in FreeCADGui.getMainWindow().findChildren(QtWidgets.QToolBar) for a in tb.actions()}
    for c in fem_commands.CMDS:
        assert FreeCADGui.Command.get(c) is not None
    try:
        assert {"一句话起草（AI）", "计算并核查（零件库）", "出报告（零件库）"} <= texts, sorted(t for t in texts if t)[:60]
    finally:                                   # 测试进程退出时 Qt 先拆：先把改界面的对象撤掉，免得退出时崩
        FreeCADGui.removeWorkbenchManipulator(FreeCADGui._fap_fem_manipulator)
        del FreeCADGui._fap_fem_manipulator
        FreeCADGui.activateWorkbench("NoneWorkbench")
