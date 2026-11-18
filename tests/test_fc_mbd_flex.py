"""装配体零件设成柔性、变形与应力云图显示（ADR-0097 D8b 验收）。需要 FreeCAD、gmsh、CalculiX。

验收件：6061-T6 铝杆 200×10×10 mm，一端 φ6 孔挂转动副（摆）。设成柔性后：界面放在孔中心、半径 = 1.5 × 孔半径；
质量与刚体算的一致；摆动计算能跑；云图网格的点数、颜色数对得上，第 k 帧的表面点与 analysis/mbd/flexview 一致，
复位后网格删掉、原零件回来。
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.freecad

L, H, R = 200.0, 10.0, 3.0


@pytest.fixture
def bar():
    import FreeCAD as App
    import Part

    from analysis.common.solvers import find_ccx

    pytest.importorskip("gmsh")
    if find_ccx() is None:
        pytest.skip("没有 CalculiX")
    doc = App.newDocument("flexbar")
    s = Part.makeBox(L, H, H, App.Vector(-10, -H / 2, -H / 2)).cut(Part.makeCylinder(R, H, App.Vector(0, 0, -H / 2)))
    o = doc.addObject("Part::Feature", "Bar")
    o.Shape = s
    doc.recompute()
    yield doc, o
    App.closeDocument(doc.Name)


def test_make_flexible_run_and_show(bar):
    from analysis.common import materials
    from analysis.mbd.dae import run as RUN
    from analysis.mbd.flexview import FlexView
    from freecad_addon.core import mbd_study as ST
    from freecad_addon.fc import mbd_flex as MF

    doc, o = bar
    mat = materials.get("6061-T6")
    vol = o.Shape.Volume
    model = {"format": "mbd-model/1", "name": "摆", "gravity_mm_s2": [0, -9810, 0],
             "analysis": {"type": "dynamic", "end_time_s": 0.01, "output_steps": 10},
             "bodies": [{"id": "Bar", "mass_kg": 1.0, "cm_mm": [90, 0, 0], "inertia_kg_m2": [[1e-4, 0, 0], [0, 1e-3, 0], [0, 0, 1e-3]],
                         "source": "FreeCAD Bar，测试"}],
             "joints": [{"id": "pin", "type": "revolute", "body_i": "ground", "body_j": "Bar", "point_mm": [0, 0, 0],
                         "axis": [0, 0, 1]}]}
    notes = MF.make_flexible(model, {"Bar": o}, {"Bar": {"material": "6061-T6", "size_mm": 5}})
    b = model["bodies"][0]
    assert "mass_kg" not in b and b["flex"]["type"] == "modal" and "Bar" in notes[0]
    assert sum(b["flex"]["node_mass_kg"]) == pytest.approx(vol * 1e-9 * mat["density_kg_m3"], rel=2e-2)
    with pytest.raises(MF.FlexSetupError, match="没有运动副"):
        MF.make_flexible({**model, "joints": []}, {"Bar": o}, {"Bar": {"material": "6061-T6"}})
    itf = MF._interfaces(model, "Bar", o.Shape, 5.0)
    assert itf[0]["radius_mm"] == pytest.approx(1.5 * R, rel=1e-6)

    data, _ = RUN.run_model(model)
    assert data["flex"]["Bar"]["stress"]["peak_mpa"] > 0
    an = ST.Animator(model, data, doc, flex_scale=50.0)
    fs = an.flex["Bar"]
    v = FlexView(b["flex"], data, "Bar")
    assert fs.obj.Mesh.CountPoints == len(v.used) and len(fs.obj.VertexColors) == len(v.used)
    assert fs.obj.Mesh.CountFacets == len(b["flex"]["surface_triangles"])
    k = an.frames - 1
    an.apply(k)
    got = np.array([[p.x, p.y, p.z] for p in fs.obj.Mesh.Points])
    assert np.allclose(got, v.points(k, 50.0), atol=1e-6)
    p0, pk = v.points(0, 1.0), v.points(k, 1.0)
    i = int(np.argmax(p0[:, 0]))
    assert pk[i][1] < p0[i][1] - 0.3                          # 杆端同一个点在往下掉（不放大的真实位置）
    name = fs.obj.Name
    an.restore()
    assert doc.getObject(name) is None and not an.flex
