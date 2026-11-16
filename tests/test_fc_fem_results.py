"""结果进 FreeCAD 原生后处理（ADR-0093 补充十二第 2 步）。需要 FreeCAD（与它自带的 CalculiX）。

验收：FEM 结果对象里的最大位移、在本仓库报告的最大应力位置处的 von Mises，与结果文件一致；VTK 结果管线建好、能加剖切；
模态的振型都读进来；多实体（绑定 + 附加质量）也能读；可信度没通过的结果名字上写明；没留结果文件时说明原因。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.freecad

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "fea-report"


@pytest.fixture
def doc(monkeypatch):
    import os

    import FreeCAD

    if os.environ.get("DISPLAY"):                     # 先开界面，文档才有界面一侧（后处理按钮要用）
        import FreeCADGui

        FreeCADGui.showMainWindow()
    monkeypatch.chdir(ROOT)
    d = FreeCAD.newDocument("fem_results_test")
    name = d.Name
    yield d
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)


def _nodes(o):
    m = o.Mesh.FemMesh
    return np.array([[m.getNodeById(n).x, m.getNodeById(n).y, m.getNodeById(n).z] for n in o.NodeNumbers])


def _run(study, tmp_path):
    from analysis.fea import run_study

    res = run_study(study, keep_dir=str(tmp_path / "keep"))
    assert res["status"] == "ok", res["messages"]
    return res


def test_rj201_static_result_in_native_postprocessing(doc, tmp_path):
    from freecad_addon.fc import fem_bridge as B
    from freecad_addon.fc import fem_results as R

    study = json.loads((FIX / "rj201-torque.study.json").read_text(encoding="utf-8"))
    study["checks"] = {"convergence": False}                 # 这里验读结果，不验收敛（省时间）
    res = _run(study, tmp_path)
    an = B.study_to_fem(doc, study)
    out = R.results_to_fem(an, res, tmp_path / "keep")
    assert len(out["results"]) == 1 and len(out["pipelines"]) == 1 and not out["skipped"]
    o = doc.getObject(out["results"][0])
    st = res["data"]["steps"][0]
    assert max(o.DisplacementLengths) == pytest.approx(st["u_max_mm"], rel=1e-3)
    P = _nodes(o)
    k = int(np.argmin(np.linalg.norm(P - np.array(st["vm_max_at"]), axis=1)))
    assert np.linalg.norm(P[k] - np.array(st["vm_max_at"])) < 1e-2
    assert o.vonMises[k] == pytest.approx(st["vm_max_mpa"], rel=1e-3)
    assert o.Label.endswith("（可信度未知）") and o.FapSafetyFactor.startswith("不给")
    assert json.loads(o.FapVmMaxMpa)["value"] == st["vm_max_mpa"]
    _gui_filters_work(doc, doc.getObject(out["pipelines"][0]))


def _gui_filters_work(doc, pipe):
    """用 FEM 工作台自带的按钮加剖切与变形放大，确认它们拿得到我们的结果场（没有显示环境就跳过这一段）"""
    import os

    if not os.environ.get("DISPLAY"):
        return
    import time

    import FreeCAD
    import FreeCADGui
    from PySide import QtWidgets

    FreeCADGui.showMainWindow()
    app = QtWidgets.QApplication.instance()

    def pump(n=60):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.005)

    FreeCADGui.activateWorkbench("FemWorkbench")
    FreeCAD.setActiveDocument(doc.Name)
    for cmd, typ in (("FEM_PostFilterWarp", "Fem::FemPostWarpVectorFilter"), ("FEM_PostFilterClipRegion", "Fem::FemPostClipFilter")):
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(pipe)
        FreeCADGui.runCommand(cmd)
        pump()
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        f = next(o for o in doc.Objects if o.TypeId == typ)
        if typ == "Fem::FemPostClipFilter":
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(pipe)
            FreeCADGui.runCommand("FEM_PostCreateFunctions", 0)
            pump()
            plane = next(o for o in doc.Objects if o.TypeId == "Fem::FemPostPlaneFunction")
            plane.Normal = FreeCAD.Vector(1, 0, 0)
            f.Function = plane
            doc.recompute()
            pump()
        assert "von Mises Stress" in f.ViewObject.getEnumerationsOfProperty("Field"), typ


def _bar(tmp_path):
    from tests.test_fea_bench import _write

    return _write(tmp_path / "bar.step", lambda o: o.addBox(0, 0, 0, 200, 20, 10))


def _face(step, pred):
    from freecad_addon.fc.fem_bridge import face_table

    return next(f["id"] for f in face_table(step) if pred(f))


def test_modal_shapes_and_multibody_with_mass(doc, tmp_path):
    from freecad_addon.fc import fem_bridge as B
    from freecad_addon.fc import fem_results as R
    from tests.test_fea_bench import _write

    a = _bar(tmp_path)
    b = _write(tmp_path / "blk.step", lambda o: o.addBox(200, 0, 0, 20, 20, 10))
    x0 = _face(a, lambda f: abs(f["center"][0]) < 1e-6)
    xa1 = _face(a, lambda f: abs(f["center"][0] - 200) < 1e-6)
    xb0 = _face(b, lambda f: abs(f["center"][0] - 200) < 1e-6)
    xb1 = _face(b, lambda f: abs(f["center"][0] - 220) < 1e-6)
    study = {"format": "fea-study/1", "name": "bar",
             "bodies": [{"id": "a", "step_path": a, "material": "45-QT"}, {"id": "b", "step_path": b, "material": "6061-T6"}],
             "supports": [{"type": "fixed", "body": "a", "faces": [x0]}],
             "loads": [{"type": "force", "body": "b", "faces": [xb1], "vector_n": [0, 0, -200.0]},
                       {"type": "mass", "body": "b", "faces": [xb1], "mass_kg": 1.0, "label": "测试质量"}],
             "connections": [{"type": "bonded", "a": {"body": "a", "faces": [xa1]}, "b": {"body": "b", "faces": [xb0]}}],
             "mesh": {"size_mm": 5}, "checks": {"convergence": False},
             "steps": [{"id": "s1", "type": "static"}, {"id": "m1", "type": "modal", "n_modes": 3}]}
    res = _run(study, tmp_path)
    an = B.study_to_fem(doc, study)
    out = R.results_to_fem(an, res, tmp_path / "keep")
    names = [doc.getObject(n).Label for n in out["results"]]
    assert any(x.startswith("s1_Results") for x in names)
    modal = next(s for s in res["data"]["steps"] if s["type"] == "modal")
    eig = [x for x in names if x.startswith("m1_EigenMode_")]
    assert len(eig) == len(modal["freqs"]) == 3, names
    o = doc.getObject(next(n for n in out["results"] if doc.getObject(n).Label.startswith("s1_")))
    st = res["data"]["steps"][0]
    assert max(o.DisplacementLengths) == pytest.approx(st["u_max_mm"], rel=1e-3)


def test_missing_files_and_failed_result_are_explained(doc, tmp_path):
    from freecad_addon.fc import fem_bridge as B
    from freecad_addon.fc import fem_results as R

    study = json.loads((FIX / "rj201-torque.study.json").read_text(encoding="utf-8"))
    an = B.study_to_fem(doc, study)
    fake = {"status": "ok", "data": {"steps": [{"id": "s1", "type": "static"}, {"id": "h1", "type": "harmonic"}]}}
    out = R.results_to_fem(an, fake, tmp_path / "none")
    assert not out["results"] and any("没有留下结果文件" in x for x in out["skipped"]) and any("h1" in x for x in out["skipped"])
    assert R.results_to_fem(an, {"status": "failed"}, tmp_path)["skipped"] == ["结果没算成，不读"]
