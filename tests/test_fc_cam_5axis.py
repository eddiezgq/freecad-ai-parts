"""问渠CAM C3b 五轴联动刀路的几何（ADR-0106 C3b）：从 FreeCAD 的面、边取直纹线、曲面接触点、边上的点和法向。"""

from __future__ import annotations

import math

import numpy as np
import pytest

pytestmark = pytest.mark.freecad


def _frustum():
    """NAS 979 圆锥台（简化）：底 Ø150 在 Z −15、顶在 Z0、半锥角 15°，加一块底座"""
    import FreeCAD as App
    import Part

    rt = 75.0 - 15.0 * math.tan(math.radians(15))
    cone = Part.makeCone(75.0, rt, 15.0, App.Vector(0, 0, -15))
    return cone.fuse(Part.makeBox(200, 200, 10, App.Vector(-100, -100, -25))).removeSplitter()


def test_cone_face_rails_and_swarf():
    """圆锥面是直纹面：导轨两端在 Z −15 / Z0；swarf 刀位到直纹线的距离 = 刀具半径、在锥面外侧（按面外法向）"""
    from analysis.cam import fiveaxis as FA
    from freecad_addon.fc import cam_5axis as C5

    s = _frustum()
    face = next(f for f in s.Faces if f.Surface.__class__.__name__ == "Cone")
    bot, top, nrm = C5.ruled_rails(face, 72)
    assert np.allclose(bot[:, 2], -15.0, atol=1e-6) and np.allclose(top[:, 2], 0.0, atol=1e-6)
    tips, axes = FA.swarf(bot, top, 5.0, normals=nrm)
    for p, a, b in zip(tips, axes, bot):
        assert np.linalg.norm(np.cross(p - b, a)) == pytest.approx(5.0, abs=1e-6)
        assert math.hypot(p[0], p[1]) > math.hypot(b[0], b[1])
        assert FA.angle_deg(a, [0, 0, 1]) == pytest.approx(15.0, abs=1e-6)


def test_non_ruled_face_refused():
    import Part

    from freecad_addon.fc import cam_5axis as C5

    sph = Part.makeSphere(30.0)
    with pytest.raises(C5.Cam5AxisError, match="不是直纹面"):
        C5.ruled_rails(sph.Faces[0])


def test_sphere_rows_contacts_and_normals():
    """球冠面：接触点都在球面上、法向沿半径朝外；行距、点距按弧长取"""
    import FreeCAD as App
    import Part

    from freecad_addon.fc import cam_5axis as C5

    sph = Part.makeSphere(60.0, App.Vector(0, 0, -60), App.Vector(0, 0, 1), 70, 90, 360)
    face = sph.Faces[0]
    rows = C5.surface_rows(face, stepover=2.0, step=1.0)
    assert len(rows) >= 10
    for pts, nrm in rows:
        r = pts - [0, 0, -60]
        assert np.allclose(np.linalg.norm(r, axis=1), 60.0, atol=1e-6)
        assert np.allclose(nrm, r / 60.0, atol=1e-6)
        assert float(np.max(np.linalg.norm(np.diff(pts, axis=0), axis=1))) <= 1.0 + 0.05


def test_edge_points_on_cylinder():
    """圆柱顶边：点在 R40 圆上，法向取圆柱面外法向（沿半径）"""
    import Part

    from freecad_addon.fc import cam_5axis as C5

    cyl = Part.makeCylinder(40.0, 20.0)
    face = next(f for f in cyl.Faces if f.Surface.__class__.__name__ == "Cylinder")
    edge = next(e for e in face.Edges if e.Curve.__class__.__name__ == "Circle" and abs(e.Vertexes[0].Point.z - 20.0) < 1e-9)
    pts, nrm = C5.edge_points(edge, face, 2.0)
    assert np.allclose(np.linalg.norm(pts[:, :2], axis=1), 40.0, atol=1e-6)
    assert np.allclose(nrm[:, :2] * 40.0, pts[:, :2], atol=1e-6) and np.allclose(nrm[:, 2], 0.0, atol=1e-9)
