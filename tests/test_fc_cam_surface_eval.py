"""问渠CAM Q3c 曲面评估的标准题（ADR-0106）：FreeCAD 3D Surface、Waterline 出的球头刀刀路，仿真量出的残留高度对理论值，不过切。
网格 0.05：残留顶点可能落在两个格心之间，量出来比理论小一点，容差取 0.015；过切容差 0.005（三角化与网格）。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.freecad


@pytest.mark.parametrize("theta", [0.0, 20.0])
def test_parallel_scallop_matches_theory(theta):
    from freecad_addon.fc import cam_surface_eval as E

    r = E.run_case(E.slope_part(theta), "surface")
    want = E.theory_parallel(3.0, 2.0, theta)
    assert r["over_mm"] <= 0.005, r
    assert r["scallop_max_mm"] == pytest.approx(want, abs=0.015), (r, want)


def test_waterline_scallop_matches_theory_with_fine_sampling():
    """等高线位置按采样间距取整：采样 0.05 时残留 ≤ 理论 + 采样·tan θ，且不过切"""
    import math

    from freecad_addon.fc import cam_surface_eval as E

    r = E.run_case(E.slope_part(20.0), "waterline", sample=0.05)
    want = E.theory_waterline(3.0, 0.5, 20.0)
    assert r["over_mm"] <= 0.005, r
    assert want - 0.015 <= r["scallop_max_mm"] <= want + 0.05 * math.tan(math.radians(20)) + 0.015, (r, want)
