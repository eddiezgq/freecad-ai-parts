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


def test_beam_sentence_to_result(doc):
    """壳、梁的一句话起草（ADR-0096 第 1 步）：悬臂梁 CANT-500 → 截面成为 FEM 的梁截面对象、固定与力作用在顶点上 →
    确认 → 计算：端部挠度与 PL³/(3EI) 相差 < 2.5 %"""
    from analysis.common import materials
    from assist import fea_draft as D
    from freecad_addon.fc import fem_flow as F
    from tests.test_assist_fea_draft import GOOD

    s = _samples()["S10-CANT-rect"]
    part = _part(doc, ROOT / "tests/fixtures/fea-draft/CANT-500.step")
    out = F.draft_into(doc, s["statement"], [part], D.FakeClient(GOOD["S10-CANT-rect"]))
    an = out["analysis"]
    assert not out["questions"] and not out["rejected"] and not out["errors"]
    assert any(o.Name.startswith("FapBeam_") for o in an.Group)                     # 截面是 FEM 的 ElementGeometry1D
    F.confirm_analysis(an, "测试工程师", False)
    study, wd = F.prepare_run(an)
    b = study["bodies"][0]
    assert b["kind"] == "beam" and b["section"]["width_mm"] == 20 and b["section"]["orientation"] == [0.0, 1.0, 0.0]
    assert study["supports"][0]["vertices"] == [1] and study["loads"][0]["vertices"] == [2]
    res = F.compute(study, wd)
    assert res["status"] == "ok", res.get("messages")
    E = materials.get("45-QT")["elastic_modulus_mpa"]
    assert res["data"]["steps"][0]["u_max_mm"] == pytest.approx(1000 * 500 ** 3 / (3 * E * 20 * 40 ** 3 / 12), rel=0.025)


FREE_RJ = {"format": "fea-study/1", "name": "RJ-201-free",
           "bodies": [{"id": "b1", "step_path": str(RJ), "material": "45-QT"}],
           "supports": [{"type": "fixed", "body": "b1", "faces": [3]}],
           "loads": [{"type": "torque", "body": "b1", "faces": [8], "value_nm": 92.5,
                      "axis": {"origin_mm": [0.0, 0.0, 76.453], "dir": [0.0, 0.0, 1.0]}}],
           "steps": [{"id": "s1", "type": "static"}]}


def test_free_tier_gates(doc, monkeypatch, tmp_path):
    """问渠有限元免费版（ADR-0096 第 5 步）：手建的单实体静力能进计算；AI 起草、正式报告、专业版算例拒绝并说明"""
    import copy

    from assist import fea_edition
    from freecad_addon.fc import fem_bridge as B
    from freecad_addon.fc import fem_flow as F
    from licensing import runtime

    monkeypatch.setenv("FAP_EDITION", "fea")
    monkeypatch.setenv("FAP_LICENSE_FILE", str(tmp_path / "none.json"))
    monkeypatch.setattr(fea_edition, "EDITION_FILE", tmp_path / "none-edition.json")
    monkeypatch.setattr(runtime, "EDITION_FILE", tmp_path / "none-edition.json")
    part = _part(doc, RJ)
    with pytest.raises(F.FlowError, match="专业版的功能：AI 一句话起草"):
        F.draft_steps(doc, "随便一句话", [part])
    an = B.study_to_fem(doc, copy.deepcopy(FREE_RJ), parts={"b1": part})
    study, _ = F.prepare_run(an)                                    # 免费版能算
    assert study["bodies"][0]["material"] == "45-QT"
    with pytest.raises(F.FlowError, match="正式报告"):
        F.make_report(an, number=None, revision="A", reason="首次出稿")
    pro = copy.deepcopy(FREE_RJ)
    pro["steps"] = [{"id": "s1", "type": "static", "large_deformation": True}]
    an2 = B.study_to_fem(doc, pro, parts={"b1": part})
    with pytest.raises(F.FlowError, match="大变形"):
        F.prepare_run(an2)
    with pytest.raises(F.FlowError, match="大变形"):
        F.compute(pro, tmp_path)


def test_fea_edition_menus_and_license(monkeypatch, tmp_path):
    """问渠有限元版的界面：FEM 的“求解”菜单有三个按钮和热分析 · 疲劳，“帮助”菜单有授权、设置、关于；导入测试授权后变专业版"""
    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    import time

    import FreeCADGui
    from PySide import QtWidgets

    from assist import fea_edition
    from freecad_addon.gui import fea_brand
    from licensing import runtime
    from tests.test_fea_edition import _edition_file, _license

    ed = _edition_file(tmp_path / "edition.json", True)
    monkeypatch.setenv("FAP_EDITION", "fea")
    monkeypatch.setattr(fea_edition, "EDITION_FILE", ed)
    monkeypatch.setattr(runtime, "EDITION_FILE", ed)
    monkeypatch.setenv("FAP_LICENSE_FILE", str(tmp_path / "installed" / "license.json"))
    monkeypatch.setattr(fea_brand, "_start_in_fem", lambda: None)          # 不改本机 FreeCAD 的启动工作台
    FreeCADGui.showMainWindow()
    fea_brand.register()
    try:
        FreeCADGui.activateWorkbench("FemWorkbench")
        app = QtWidgets.QApplication.instance()
        for _ in range(50):
            app.processEvents()
            time.sleep(0.01)
        menus = {a.text(): [x.text() for x in a.menu().actions()] for a in FreeCADGui.getMainWindow().menuBar().actions() if a.menu()}
        solve = [x.replace("（零件库）", "") for x in menus["&Solve"]]      # 同一进程里先注册过全功能版的按钮名
        assert {"一句话起草（AI）", "计算并核查", "出报告", "热分析 · 疲劳"} <= set(solve), menus["&Solve"]
        assert {"问渠有限元：授权…", "问渠有限元：设置 AI 密钥…", "关于问渠有限元"} <= set(menus["&Help"]), menus["&Help"]
        assert "免费版" in fea_brand.tier_text() and "还没有导入" in fea_brand.tier_text()
        lic, key = _license(tmp_path, [fea_edition.PRO])
        monkeypatch.setenv("FAP_LICENSE_TEST_KEY", key)
        dlg = fea_brand.LicenseDialog()
        assert dlg.import_file(str(lic))
        assert runtime.license_path().is_file() and fea_edition.pro_allowed()
        assert fea_brand.tier_text().startswith("专业版：CI 验收")
        assert "专业版" in fea_brand.about_text()
    finally:
        for name in ("_fap_fea_help", "_fap_fem_manipulator"):
            if hasattr(FreeCADGui, name):
                FreeCADGui.removeWorkbenchManipulator(getattr(FreeCADGui, name))
                delattr(FreeCADGui, name)
        FreeCADGui.activateWorkbench("NoneWorkbench")


def _hand_built_cantilever(doc, tmp_path, solver_type="static"):
    """像用户那样只用 FEM 工作台的工具建分析：悬臂方梁 100×10×10，x = 0 面固定，x = 100 面受 100 N 的力（-z）"""
    import FreeCAD
    import ObjectsFem
    import Part

    box = doc.addObject("Part::Feature", "Beam")
    box.Shape = Part.makeBox(100, 10, 10)
    doc.recompute()
    faces = {round(f.CenterOfMass.x, 3): i + 1 for i, f in enumerate(box.Shape.Faces) if abs(f.normalAt(0, 0).x) > 0.99}
    an = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc) if hasattr(ObjectsFem, "makeSolverCalculiXCcxTools") \
        else ObjectsFem.makeSolverCalculiX(doc)
    solver.AnalysisType = solver_type
    an.addObject(solver)
    mat = ObjectsFem.makeMaterialSolid(doc, "SolidMaterial")      # FEM 自己的材料卡：接管时不用
    mat.Material = {"Name": "Steel-Generic", "YoungsModulus": "200000 MPa", "PoissonRatio": "0.3", "Density": "7900 kg/m^3"}
    an.addObject(mat)
    fix = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fix.References = [(box, f"Face{faces[0.0]}")]
    an.addObject(fix)
    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [(box, f"Face{faces[100.0]}")]
    force.Force = FreeCAD.Units.Quantity("100 N")
    line = doc.addObject("Part::Line", "Dir")
    line.X1, line.Y1, line.Z1, line.X2, line.Y2, line.Z2 = 0, 0, 0, 0, 0, -10
    doc.recompute()
    force.Direction = (line, ["Edge1"])
    force.Reversed = False
    an.addObject(force)
    doc.recompute()
    return an


def test_hand_built_analysis_is_adopted_and_solved(doc, monkeypatch, tmp_path):
    """免费版的主路径（ADR-0096）：用户用 FEM 工具手建分析 → 选材料库材料接管 → 计算并核查 → 挠度对上 PL³/3EI"""
    from analysis.common import materials
    from assist import fea_edition
    from freecad_addon.fc import fem_flow as F
    from licensing import runtime

    monkeypatch.setenv("FAP_EDITION", "fea")                          # 免费版也能走这条路
    monkeypatch.setenv("FAP_LICENSE_FILE", str(tmp_path / "none.json"))
    monkeypatch.setattr(fea_edition, "EDITION_FILE", tmp_path / "none-edition.json")
    monkeypatch.setattr(runtime, "EDITION_FILE", tmp_path / "none-edition.json")
    an = _hand_built_cantilever(doc, tmp_path)
    assert not F.adopted(an)
    with pytest.raises(F.FlowError, match="材料库"):
        F.adopt(an, "no-such-steel")
    study = F.adopt(an, "45-QT", tmp_path / "parts")
    assert F.adopted(an) and study["steps"] == [{"id": "s1", "type": "static"}]
    with pytest.raises(F.FlowError, match="接管过"):
        F.adopt(an, "45-QT")
    st, wd = F.prepare_run(an)
    assert st["bodies"][0]["material"] == "45-QT"
    assert [x["type"] for x in st["supports"]] == ["fixed"] and [x["type"] for x in st["loads"]] == ["force"]
    assert st["loads"][0]["vector_n"] == pytest.approx([0, 0, -100], abs=1e-9)
    st["mesh"] = {"size_mm": 2.5}
    res = F.compute(st, wd)
    assert res["status"] == "ok", res.get("messages")
    e = materials.get("45-QT")["elastic_modulus_mpa"]
    theory = 100 * 100 ** 3 / (3 * e * 10 * 10 ** 3 / 12)
    assert res["data"]["steps"][0]["u_max_mm"] == pytest.approx(theory, rel=0.03)


def test_hand_built_centrifugal_and_gravity_are_adopted(doc, tmp_path):
    """FEM 工作台手加的离心载荷（引用实体、给转轴）和重力（不引用实体）：分析里只有一个零件，就算在它上面"""
    import FreeCAD
    import ObjectsFem

    from freecad_addon.fc import fem_flow as F

    an = _hand_built_cantilever(doc, tmp_path)
    beam = doc.getObject("Beam")
    axis = doc.addObject("Part::Line", "Axis")
    axis.X1, axis.Y1, axis.Z1, axis.X2, axis.Y2, axis.Z2 = 0, 5, 5, 10, 5, 5
    doc.recompute()
    c = ObjectsFem.makeConstraintCentrif(doc, "Centrif")
    c.References = [(beam, "Solid1")]
    c.RotationAxis = [(axis, "Edge1")]
    c.RotationFrequency = FreeCAD.Units.Quantity("50 1/s")
    an.addObject(c)
    an.addObject(ObjectsFem.makeConstraintSelfWeight(doc, "Gravity"))
    doc.recompute()
    F.adopt(an, "45-QT", tmp_path / "parts")
    study, _wd = F.prepare_run(an)
    loads = {x["type"]: x for x in study["loads"]}
    body = study["bodies"][0]["id"]
    assert loads["centrifugal"]["body"] == body and loads["centrifugal"]["speed_rpm"] == pytest.approx(3000)
    assert loads["centrifugal"]["axis"]["dir"] == pytest.approx([1, 0, 0])
    assert loads["gravity"]["body"] == body


def test_hand_built_modal_and_unsupported_types(doc, tmp_path):
    from freecad_addon.fc import fem_flow as F

    an = _hand_built_cantilever(doc, tmp_path, "frequency")
    next(o for o in an.Group if hasattr(o, "AnalysisType")).EigenmodesCount = 4
    assert F.adopt(an, "45-QT", tmp_path / "p1")["steps"] == [{"id": "m1", "type": "modal", "n_modes": 4}]
    an2 = _hand_built_cantilever(doc, tmp_path, "thermomech")
    with pytest.raises(F.FlowError, match="thermomech"):
        F.adopt(an2, "45-QT", tmp_path / "p2")
    empty = __import__("ObjectsFem").makeAnalysis(doc, "Empty")
    with pytest.raises(F.FlowError, match="约束或载荷"):
        F.adopt(empty, "45-QT")
