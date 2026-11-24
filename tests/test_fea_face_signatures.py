"""Face references survive geometry edits (ADR-0125) — analysis.fea.facesig.

Source of the finding: the FEM book (fem-ai-textbook), chapter 47, clue 40: a study names faces only by their number; after
a common geometry edit the numbers can change and loads land on other faces without any warning. The book's prototype
re-identified the root and end faces of a cantilever after five edits (5 / 5 correct). WenQuest CAD 0.3.6 plan, item B3.
No network, no LLM.
"""

from __future__ import annotations

import pytest

import analysis
from analysis.fea import facesig
from tests.test_fea_bench import _faces, _need_fea

B = H = 10.0
EDITS = {"G1": "cross hole in the middle", "G2": "chamfered end edges", "G3": "lengthened to 120 mm", "G4": "slot in the top",
         "G5": "filleted root edges"}


def _beam(tmp_path, name):
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    o = gmsh.model.occ
    L = 120.0 if name == "G3" else 100.0
    box = o.addBox(0, 0, 0, L, B, H)
    if name == "G1":
        o.cut([(3, box)], [(3, o.addCylinder(50, -1, 5, 0, B + 2, 0, 2))])
    elif name == "G4":
        o.cut([(3, box)], [(3, o.addBox(30, 3, 7, 40, 4, 4))])
    o.synchronize()
    if name in ("G2", "G5"):
        x = L if name == "G2" else 0.0
        es = [t for _, t in gmsh.model.getEntities(1) if abs(o.getCenterOfMass(1, t)[0] - x) < 1e-6]
        vol = gmsh.model.getEntities(3)[0][1]
        if name == "G5":
            o.fillet([vol], es, [1.0], True)
        else:
            fe = next(t for _, t in gmsh.model.getEntities(2) if abs(o.getCenterOfMass(2, t)[0] - x) < 1e-6)
            o.chamfer([vol], es, [fe] * len(es), [1.0], True)
        o.synchronize()
    p = str(tmp_path / f"{name}.step")
    gmsh.write(p)
    gmsh.finalize()
    return p, L


@pytest.fixture(scope="module")
def beams(tmp_path_factory):
    """all six geometries are written before any analysis call (gmsh is shared with analysis.fea, as in the book)"""
    pytest.importorskip("gmsh")
    d = tmp_path_factory.mktemp("beams")
    return {g: _beam(d, g) for g in ["G0", *EDITS]}


def _plane_at_x(faces, x):
    return [f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][0] - x) < 1e-6]


def _study(step, root, end):
    return {"format": "fea-study/1", "name": "beam", "bodies": [{"id": "b1", "step_path": step, "material": "45-QT"}],
            "supports": [{"type": "fixed", "body": "b1", "faces": root}],
            "loads": [{"type": "force", "body": "b1", "faces": end, "vector_n": [0, 0, -100.0]}],
            "steps": [{"id": "s1", "type": "static"}], "checks": {"convergence": False}}


@pytest.mark.parametrize("edit", list(EDITS))
def test_faces_reidentified_after_edit(beams, edit):
    p0, L0 = beams["G0"]
    f0 = _faces(p0)
    signed = facesig.sign(_study(p0, _plane_at_x(f0, 0.0), _plane_at_x(f0, L0)))
    p1, L1 = beams[edit]
    # the study now points at the edited file (same path a user would overwrite)
    signed["bodies"][0]["step_path"] = p1
    used, rep = facesig.reconcile(signed)
    f1 = _faces(p1)
    assert used["supports"][0]["faces"] == _plane_at_x(f1, 0.0), rep
    assert used["loads"][0]["faces"] == _plane_at_x(f1, L1), rep
    assert rep["b1"]["status"] == "remapped"


def test_unchanged_file_keeps_numbers(beams):
    p0, L0 = beams["G0"]
    f0 = _faces(p0)
    st = facesig.sign(_study(p0, _plane_at_x(f0, 0.0), _plane_at_x(f0, L0)))
    used, rep = facesig.reconcile(st)
    assert used["supports"] == st["supports"] and rep["b1"]["status"] == "same"


def test_unsigned_study_is_marked_unchecked(beams):
    p0, L0 = beams["G0"]
    f0 = _faces(p0)
    _used, rep = facesig.reconcile(_study(p0, _plane_at_x(f0, 0.0), _plane_at_x(f0, L0)))
    assert rep["b1"]["status"] == "unchecked" and "未核对" in rep["b1"]["note"]


def test_unidentifiable_face_refuses(beams):
    """Root face signature made unrecognisable (area far off): the run must refuse, not guess."""
    p0, L0 = beams["G0"]
    f0 = _faces(p0)
    st = facesig.sign(_study(p0, _plane_at_x(f0, 0.0), _plane_at_x(f0, L0)))
    st["bodies"][0]["step_sha256"] = "0" * 64                       # pretend the file changed
    k = str(_plane_at_x(f0, 0.0)[0])
    st["bodies"][0]["face_signatures"][k]["area_mm2"] *= 10
    with pytest.raises(facesig.FaceRefError, match="认不准"):
        facesig.reconcile(st)


def test_run_study_refuses_and_reports(beams):
    _need_fea()
    p0, L0 = beams["G0"]
    f0 = _faces(p0)
    st = facesig.sign(_study(p0, _plane_at_x(f0, 0.0), _plane_at_x(f0, L0)))
    st["bodies"][0]["step_sha256"] = "0" * 64
    st["bodies"][0]["face_signatures"][str(_plane_at_x(f0, 0.0)[0])]["area_mm2"] *= 10
    r = analysis.run("fea", st)
    assert r["status"] == "failed" and "认不准" in r["messages"][0]
    ok = analysis.run("fea", facesig.sign(_study(p0, _plane_at_x(f0, 0.0), _plane_at_x(f0, L0))))
    assert ok["status"] == "ok" and ok["data"]["face_references"]["b1"]["status"] == "same"
