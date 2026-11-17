"""算例 ↔ FreeCAD FEM 工作台对象（ADR-0093 补充十二第 1 步）。需要 FreeCAD。

验收：真实零件（RJ-201、LS-101、整臂大臂）的算例往返一致；各种条目类型往返一致；人手建的 FEM 分析能转成算例；
在 FreeCAD 里改过的以 FreeCAD 为准、依据记“人工”、AI 起草的要重新确认；对不上的面、不支持的对象被拒绝并说明。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.freecad

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "fea-report"


def _plain(note):
    return {k: v for k, v in note.items() if k != "objects"}


@pytest.fixture
def doc(monkeypatch):
    import FreeCAD

    monkeypatch.chdir(ROOT)
    d = FreeCAD.newDocument("fem_bridge_test")
    name = d.Name
    yield d
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)


@pytest.mark.parametrize("name", ["rj201-torque", "ls101-shaft-modal", "arm-upper-combination"])
def test_real_part_studies_round_trip(doc, name):
    from freecad_addon.fc import fem_bridge as B

    study = json.loads((FIX / f"{name}.study.json").read_text(encoding="utf-8"))
    a = B.study_to_fem(doc, study, base_dir=ROOT)
    labels = {o.TypeId for o in a.Group}
    assert "Fem::ConstraintFixed" in labels or "Fem::ConstraintDisplacement" in labels
    back, note = B.fem_to_study(a)
    assert _plain(note) == {"changed": [], "added": [], "unsupported": []}
    assert back == study


def _two_blocks(tmp_path):
    from tests.test_fea_bench import _write

    a = _write(tmp_path / "a.step", lambda o: o.addBox(0, 0, 0, 100, 20, 20))
    b = _write(tmp_path / "b.step", lambda o: o.addBox(100, 0, 0, 50, 20, 20))
    c = _write(tmp_path / "c.step", lambda o: o.addCylinder(0, 0, 0, 0, 0, 80, 15))
    return a, b, c


def _faces(step):
    from freecad_addon.fc.fem_bridge import face_table

    return face_table(step)


def _face_at(step, pred):
    return next(f["id"] for f in _faces(step) if pred(f))


def test_every_item_type_round_trips(doc, tmp_path):
    from freecad_addon.fc import fem_bridge as B

    a, b, c = _two_blocks(tmp_path)
    xa0 = _face_at(a, lambda f: abs(f["center"][0]) < 1e-6)
    xa1 = _face_at(a, lambda f: abs(f["center"][0] - 100) < 1e-6)
    xb0 = _face_at(b, lambda f: abs(f["center"][0] - 100) < 1e-6)
    xb1 = _face_at(b, lambda f: abs(f["center"][0] - 150) < 1e-6)
    top = _face_at(a, lambda f: abs(f["center"][2] - 20) < 1e-6)
    cyl = _face_at(c, lambda f: f["kind"] == "cylinder")
    cend = _face_at(c, lambda f: abs(f["center"][2]) < 1e-6 and f["kind"] == "plane")
    ax = {"origin_mm": [0.0, 0.0, 0.0], "dir": [0.0, 0.0, 1.0]}
    study = {
        "format": "fea-study/1", "name": "all-types",
        "bodies": [{"id": "a", "step_path": a, "material": "45-QT"}, {"id": "b", "step_path": b, "material": "6061-T6"},
                   {"id": "c", "step_path": c, "material": "45-QT"}],
        "load_cases": [{"id": "W", "name": "工作", "kind": "operating"}],
        "combinations": [{"id": "C1", "name": "1.5W", "factors": {"W": 1.5}}],
        "supports": [{"type": "fixed", "body": "a", "faces": [xa0]},
                     {"type": "displacement", "body": "b", "faces": [xb1], "uy_mm": 0.0, "uz_mm": -0.05},
                     {"type": "cyl_support", "body": "c", "faces": [cyl], "axis": ax, "dofs": ["radial", "tangential"]},
                     {"type": "symmetry", "body": "a", "faces": [top]},
                     {"type": "elastic_support", "body": "c", "faces": [cend], "stiffness_n_per_mm3": 5.0}],
        "loads": [{"type": "force", "body": "a", "faces": [top], "vector_n": [0.0, 300.0, -400.0], "case": "W"},
                  {"type": "pressure", "body": "b", "faces": [xb1], "value_mpa": -0.25, "case": "W"},
                  {"type": "torque", "body": "c", "faces": [cyl], "value_nm": 12.5, "axis": ax, "case": "W"},
                  {"type": "bearing_load", "body": "c", "faces": [cyl], "force_n": [100.0, 0.0, 0.0], "axis": ax, "case": "W"},
                  {"type": "gravity", "body": "a", "acceleration_m_s2": [0.0, 0.0, -9.80665], "case": "W"},
                  {"type": "centrifugal", "body": "c", "speed_rpm": 3000.0, "axis": ax, "case": "W"},
                  {"type": "moment", "body": "a", "faces": [top], "vector_nm": [0.0, 0.0, 5.0], "case": "W"},
                  {"type": "mass", "body": "b", "faces": [xb1], "mass_kg": 2.5, "label": "电机（样本质量）"}],
        "connections": [{"type": "bonded", "a": {"body": "a", "faces": [xa1]}, "b": {"body": "b", "faces": [xb0]}},
                        {"type": "contact", "id": "k1", "a": {"body": "a", "faces": [xa1]}, "b": {"body": "b", "faces": [xb0]},
                         "friction_coefficient": 0.15}],
        "steps": [{"id": "s_C1", "type": "static", "combination": "C1"}],
    }
    an = B.study_to_fem(doc, study)
    types = sorted(o.TypeId for o in an.Group)
    for t in ("Fem::ConstraintFixed", "Fem::ConstraintDisplacement", "Fem::ConstraintTransform", "Fem::ConstraintForce",
              "Fem::ConstraintPressure", "Fem::ConstraintContact"):
        assert t in types, (t, types)
    f = next(o for o in an.Group if o.TypeId == "Fem::ConstraintForce")
    assert f.Force.getValueAs("N").Value == pytest.approx(500.0)
    d = f.DirectionVector
    assert (d.x, d.y, d.z) == pytest.approx((0.0, 0.6, -0.8))
    back, note = B.fem_to_study(an)
    assert _plain(note) == {"changed": [], "added": [], "unsupported": []}
    assert back == study


def test_edit_in_freecad_wins_and_ai_draft_needs_reconfirm(doc):
    import FreeCAD

    from freecad_addon.fc import fem_bridge as B

    study = json.loads((FIX / "rj201-torque.study.json").read_text(encoding="utf-8"))
    study["loads"] = [{"type": "pressure", "body": "b1", "faces": [8], "value_mpa": 2.0}] + study["loads"]
    an = B.study_to_fem(doc, study, base_dir=ROOT)
    p = next(o for o in an.Group if o.TypeId == "Fem::ConstraintPressure")
    p.Pressure = FreeCAD.Units.Quantity("3 MPa")
    back, note = B.fem_to_study(an)
    assert note["changed"] == ["loads/0"]
    assert back["loads"][0]["value_mpa"] == pytest.approx(3.0)
    pv = back["provenance"]
    assert pv["confirmed_by_human"] is False and "confirmed_by" not in pv
    assert {"target": "/loads/0", "source": "human", "note": "在 FreeCAD 里改过"} in pv["basis"]
    from analysis.fea.study import StudyInvalid, validate

    with pytest.raises(StudyInvalid, match="确认"):
        validate(back)


def test_hand_made_fem_analysis_converts(doc, tmp_path):
    """人在 FEM 工作台里手工建的：零件 + 固定 + 力（方向参照一条棱）→ 算例；不支持的对象列出来"""
    import ObjectsFem

    from freecad_addon.fc import fem_bridge as B

    a, _b, _c = _two_blocks(tmp_path)
    base = {"format": "fea-study/1", "name": "hand", "bodies": [{"id": "a", "step_path": a, "material": "45-QT"}],
            "supports": [], "loads": [], "steps": [{"id": "s1", "type": "static"}]}
    an = B.study_to_fem(doc, base)
    part = next(o for o in doc.Objects if o.Name == "Fap_a")
    fm = B.face_map(part.Shape, _faces(a))
    rev = {v: k for k, v in fm.items()}
    i0 = next(i for i, f in enumerate(part.Shape.Faces, 1) if abs(f.CenterOfMass.x) < 1e-6)
    i1 = next(i for i, f in enumerate(part.Shape.Faces, 1) if abs(f.CenterOfMass.x - 100) < 1e-6)
    fx = ObjectsFem.makeConstraintFixed(doc, "HandFixed")
    fx.References = [(part, f"Face{i0}")]
    an.addObject(fx)
    fo = ObjectsFem.makeConstraintForce(doc, "HandForce")
    fo.References = [(part, f"Face{i1}")]
    fo.Force = "250 N"
    edge = next(i for i, e in enumerate(part.Shape.Edges, 1) if abs(abs(e.tangentAt(e.FirstParameter).z) - 1) < 1e-9)
    fo.Direction = (part, [f"Edge{edge}"])
    fo.Reversed = True
    an.addObject(fo)
    es = ObjectsFem.makeConstraintElectrostaticPotential(doc, "HandEs")
    an.addObject(es)
    doc.recompute()
    back, note = B.fem_to_study(an)
    assert back["supports"] == [{"type": "fixed", "body": "a", "faces": [rev[i0]]}]
    f = back["loads"][0]
    assert f["faces"] == [rev[i1]] and abs(abs(f["vector_n"][2]) - 250) < 1e-9 and f["vector_n"][:2] == pytest.approx([0, 0])
    assert len(note["added"]) == 2 and any("HandEs" in x or "Electrostatic" in x for x in note["unsupported"])


def test_faces_that_do_not_match_are_refused(doc, tmp_path):
    from freecad_addon.fc import fem_bridge as B

    a, b, _c = _two_blocks(tmp_path)
    import Part

    s = Part.Shape()
    s.read(a)
    with pytest.raises(B.BridgeError, match="不能一一对应"):
        B.face_map(s, _faces(b))
    study = {"format": "fea-study/1", "name": "x", "bodies": [{"id": "a", "step_path": a, "material": "45-QT"}],
             "supports": [{"type": "fixed", "body": "a", "faces": [99]}], "loads": [], "steps": [{"id": "s1", "type": "static"}]}
    with pytest.raises(B.BridgeError, match="没有 STEP 面"):
        B.study_to_fem(doc, copy.deepcopy(study))


def test_saved_document_round_trips(doc, tmp_path):
    """存成 FCStd 再打开，算例照样读回（原始条目随文件保存）"""
    import FreeCAD

    from freecad_addon.fc import fem_bridge as B

    study = json.loads((FIX / "arm-upper-combination.study.json").read_text(encoding="utf-8"))
    B.study_to_fem(doc, study, base_dir=ROOT)
    path = str(tmp_path / "arm.FCStd")
    doc.saveAs(path)
    FreeCAD.closeDocument(doc.Name)
    d2 = FreeCAD.openDocument(path)
    try:
        an = next(o for o in d2.Objects if o.Name == "FapAnalysis")
        back, note = B.fem_to_study(an)
        assert back == study and _plain(note) == {"changed": [], "added": [], "unsupported": []}
    finally:
        FreeCAD.closeDocument(d2.Name)
