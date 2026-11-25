"""Symmetry planes and sliding supports do not shrink the stress evaluation region — analysis.fea.

Source of the finding: the FEM book (fem-ai-textbook), chapter 41, clue 35. One-eighth of a thick plate with a central hole
(100 x 100 x 10 mm, hole radius 5 mm, three symmetry planes, 10 MPa tension at x = 100): the peak stress sits on the hole
edge at x = 0, which is a symmetry plane. Symmetry planes counted as "supports", so the evaluation dropped everything within
1.5 h of them and reported 13.4 MPa (peak over all nodes 30.1 MPa). WenQuest CAD 0.3.6 plan, item B2.

Reference: thin plate with a small central hole, stress concentration about 3.03 x nominal (book chapter 40, CalculiX
convergence: 30.3 MPa here); the thick plate varies through the thickness by a few percent. No network, no LLM.
"""

from __future__ import annotations

import pytest

import analysis
from tests.test_fea_bench import _faces, _need_fea

W, R, T, SIG = 100.0, 5.0, 10.0, 10.0
REF = 30.3


def _plate(tmp_path):
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("plate")                 # a fresh model: an earlier test may have left entities in the current one
    o = gmsh.model.occ
    box = o.addBox(0, 0, 0, W, W, T)
    cyl = o.addCylinder(0, 0, -1, 0, 0, T + 2, R)
    o.cut([(3, box)], [(3, cyl)])
    o.synchronize()
    step = str(tmp_path / "plate.step")
    gmsh.write(step)
    gmsh.finalize()
    fs = _faces(step)                       # face ids as the analysis reads them back from the STEP file
    faces = {k: [x["id"] for x in fs if x["kind"] == "plane" and abs(x["center"][i] - v) < 1e-6] for k, (i, v) in
             {"x0": (0, 0), "y0": (1, 0), "z0": (2, 0), "xw": (0, W)}.items()}
    return step, faces


def _run(step, faces, supports):
    st = {"format": "fea-study/1", "name": "plate", "bodies": [{"id": "b1", "step_path": step, "material": "45-QT"}],
          "supports": supports, "loads": [{"type": "force", "body": "b1", "faces": faces["xw"], "vector_n": [SIG * W * T, 0, 0]}],
          "steps": [{"id": "s1", "type": "static"}], "mesh": {"size_mm": 2.5}, "checks": {"convergence": False}}
    r = analysis.run("fea", st)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["steps"][0]


@pytest.mark.parametrize("kind", ["symmetry", "displacement"])
def test_hole_edge_on_symmetry_plane_is_evaluated(tmp_path, kind):
    _need_fea()
    step, f = _plate(tmp_path)
    if kind == "symmetry":
        sup = [{"type": "symmetry", "body": "b1", "faces": f[k]} for k in ("x0", "y0", "z0")]
    else:   # sliding supports: only the normal component held, plane faces — mechanically the same as symmetry
        sup = [{"type": "displacement", "body": "b1", "faces": f["x0"], "ux_mm": 0.0},
               {"type": "displacement", "body": "b1", "faces": f["y0"], "uy_mm": 0.0},
               {"type": "displacement", "body": "b1", "faces": f["z0"], "uz_mm": 0.0}]
    s = _run(step, f, sup)
    assert abs(s["vm_max_mpa"] - REF) / REF < 0.05, s["vm_max_mpa"]          # was 13.4 MPa
    x, y, _ = s["vm_max_at"]
    assert x < 1.0 and abs(y - R) < 1.0                                       # on the hole edge at x = 0
    assert "vm_peak_excluded_note" not in s


def test_fixed_support_still_excluded_and_noted(tmp_path):
    _need_fea()
    step, f = _plate(tmp_path)
    sup = [{"type": "fixed", "body": "b1", "faces": f["x0"]}]
    s = _run(step, f, sup)
    assert s["vm_peak_all_mpa"] >= s["vm_max_mpa"]
    if s["vm_peak_all_mpa"] > 1.1 * s["vm_max_mpa"]:
        assert "支承面附近" in s["vm_peak_excluded_note"]
