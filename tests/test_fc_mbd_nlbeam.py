"""FreeCAD 里把细长零件设成大变形梁（ADR-0101 F3 验收）。需要 FreeCAD。

- 矩形截面杆 300 × 10 × 6 mm（任意摆放）：长度、截面积、两个惯性矩、外缘距离对解析值；梁轴、端点对
- 不够细长、不是等截面都报错
- 装配里一端有 φ4 孔挂转动副的摆：孔中心进 nodes_at_mm，能算；动画里节点折线跟着结果走，复位后删掉
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.freecad


@pytest.fixture
def doc():
    import FreeCAD as App

    d = App.newDocument("nlbeam")
    yield d
    App.closeDocument(d.Name)


def _bar(doc, place, hole=False):
    import FreeCAD as App
    import Part

    s = Part.makeBox(300, 10, 6)
    if hole:
        s = s.cut(Part.makeCylinder(2, 6, App.Vector(10, 5, 0)))
    o = doc.addObject("Part::Feature", "Bar")
    o.Shape = s
    o.Placement = place
    doc.recompute()
    return o


def test_section_from_part(doc):
    import FreeCAD as App

    from analysis.common import materials
    from freecad_addon.fc.mbd_flex import beam_from_part

    rot = App.Rotation(App.Vector(1, 2, 3), 37)
    place = App.Placement(App.Vector(5, -7, 11), rot)
    o = _bar(doc, place)
    flex, sec = beam_from_part(o.Shape, materials.get("45-QT"), [])
    assert sec["length_mm"] == pytest.approx(300, rel=1e-6)
    assert flex["area_mm2"] == pytest.approx(60, rel=1e-6)
    assert flex["izz_mm4"] == pytest.approx(10 * 6 ** 3 / 12, rel=1e-6)      # ∫y²：y 是薄的方向（6 mm）
    assert flex["iyy_mm4"] == pytest.approx(6 * 10 ** 3 / 12, rel=1e-6)
    assert flex["fiber_y_mm"] == pytest.approx(3, rel=1e-6) and flex["fiber_z_mm"] == pytest.approx(5, rel=1e-6)
    ends = {tuple(np.round(flex["from_mm"], 6)), tuple(np.round(flex["to_mm"], 6))}
    want = {tuple(np.round(tuple(place.multVec(App.Vector(x, 5, 3))), 6)) for x in (0, 300)}
    assert ends == want
    ey = place.Rotation.multVec(App.Vector(0, 0, 1))
    assert abs(abs(np.dot(flex["y_axis"], tuple(ey))) - 1) < 1e-9


def test_rejects_stubby_and_tapered(doc):
    import FreeCAD as App
    import Part

    from analysis.common import materials
    from freecad_addon.fc.mbd_flex import FlexSetupError, beam_from_part

    mat = materials.get("45-QT")
    with pytest.raises(FlexSetupError, match="细长"):
        beam_from_part(Part.makeBox(30, 10, 10), mat, [])
    with pytest.raises(FlexSetupError, match="等截面"):
        beam_from_part(Part.makeCone(8, 4, 300, App.Vector(0, 0, 0), App.Vector(1, 0, 0)), mat, [])


def test_pendulum_beam_runs_and_shows(doc):
    import FreeCAD as App

    from analysis.mbd.dae.run import run_model
    from freecad_addon.core import mbd_study as ST
    from freecad_addon.fc import mbd_flex as MF

    o = _bar(doc, App.Placement(), hole=True)
    model = {"format": "mbd-model/1", "name": "大变形摆", "gravity_mm_s2": [0, -9810, 0],
             "bodies": [{"id": "Bar", "mass_kg": 0.47, "cm_mm": [150, 5, 3], "inertia_kg_m2": {"ixx": 1e-5, "iyy": 3e-3, "izz": 3e-3},
                         "source": "FreeCAD Bar，测试"}],
             "joints": [{"id": "pin", "type": "revolute", "body_i": "ground", "body_j": "Bar", "point_mm": [10, 5, 3], "axis": [0, 0, 1]}],
             "analysis": {"type": "dynamic", "end_time_s": 0.02, "output_steps": 4}}
    notes = MF.make_flexible(model, {"Bar": o}, {"Bar": {"material": "45-QT", "kind": "nonlinear_beam", "elements": 10}})
    b = model["bodies"][0]
    assert b["flex"]["type"] == "nonlinear_beam" and b["flex"]["nodes_at_mm"] == [[10.0, 5.0, 3.0]]
    assert "大变形梁" in notes[0] and "实体" in notes[0]
    from analysis.mbd.dae import advise

    advise.apply(model)
    assert model["analysis"]["integrator"] == "HHT"
    data, _ = run_model(model)
    an = ST.Animator(model, data, doc)
    bs = an.flex["Bar"]
    k = an.frames - 1
    an.apply(k)
    got = np.array([[v.Point.x, v.Point.y, v.Point.z] for v in bs.obj.Shape.Vertexes])
    assert np.allclose(got, np.array(data["flex"]["Bar"]["nodes_mm"][k]), atol=1e-6)
    tip = np.array(data["flex"]["Bar"]["nodes_mm"])[:, -1]
    assert tip[-1][1] < tip[0][1] - 0.5                               # 摆在往下掉
    name = bs.obj.Name
    an.restore()
    assert doc.getObject(name) is None
