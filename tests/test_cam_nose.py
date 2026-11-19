"""刀尖圆弧（ADR-0106 Q2 第 4 步）：补偿后的刀路几何、不补偿时倒角的残留量与解析值、轴肩根部圆角、端面车过中心。"""

import math

import numpy as np
import pytest

from analysis import cam
from analysis.cam import machines, post
from analysis.cam import paths as P
from analysis.cam import sim as S

LATHE = machines.get("EX-LATHE")


def test_comp_keeps_cylinders_and_faces():
    prof = [(0.0, 30.0), (-20.0, 30.0), (-20.0, 40.0), (-50.0, 40.0)]
    out = P.nose_comp(prof, 0.8)
    # 外圆、端面上假想刀尖就是接触点：Ø30 段、Ø40 段的点不变；轴肩根部（内凹）是两条偏置线的交点 → 原拐角
    assert out[0] == pytest.approx((-0.8, 30.0))
    assert out[-1] == pytest.approx((-50.8, 40.0))
    assert any(z == pytest.approx(-20.0) and d == pytest.approx(30.0) for z, d in out)


def test_comp_shifts_45deg_chamfer_by_analytic_amount():
    """45° 倒角 r + z = c：补偿后假想刀尖走在 r + z = c − rε(2 − √2) 上（圆心离倒角线 rε，假想刀尖 = 圆心 − (rε, rε)）"""
    re = 0.8
    prof = [(0.0, 36.0), (-2.0, 40.0), (-30.0, 40.0)]           # 倒角 2×45°：r + z = 18
    out = P.nose_comp(prof, re)
    z0, d0 = out[0]
    z1, d1 = out[1]
    for z, d in ((z0, d0), (z1, d1)):
        assert d / 2 + z == pytest.approx(18 - re * (2 - math.sqrt(2)), abs=1e-9)


def _finish_gcode(prof, nose):
    prog = {"number": 1, "title": "t", "header": {}, "ops": [
        {"tool": {"n": 2, "name": "精车"}, "spindle": {"css": 200, "max_rpm": 3000}, "moves": P.turn_finish(prof, 44, 0.1, nose_r=nose),
         "title": "精车"}]}
    return post.post(prog, LATHE)


@pytest.mark.parametrize("comp,expect", [(False, 0.8 * (2 - math.sqrt(2))), (True, 0.0)])
def test_chamfer_residual_without_comp_matches_analytic(comp, expect):
    """刀尖圆弧 R0.8 精车 2×45° 倒角：不补偿时倒角上残留（半径方向）= rε(2 − √2) ≈ 0.469；补偿后为零"""
    prof = [(0.0, 36.0), (-2.0, 40.0), (-30.0, 40.0)]
    g = _finish_gcode(prof, 0.8 if comp else 0.0)
    parsed = S.parse(g, LATHE)
    stock = {"d": 40.6, "z_right": 0.0, "z_left": -40.0}       # 精车余量 0.3（半径）
    s = S.simulate_turn(parsed, stock, {2: {"kind": "turn", "nose_r": 0.8}}, target={"outer": prof, "nose_outer": 0.8}, h=0.01)
    assert s.get("under_mm", 0.0) == pytest.approx(expect, abs=0.015)
    assert not [i for i in s["issues"] if "过切" in i["text"]]


def test_shoulder_root_fillet_is_a_note_not_residual():
    setup = {"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60]], "chamfer_mm": 1,
             "machine_sim": {"tools": {"1": {"tool": "TR-CNMG"}, "2": {"tool": "TR-VNMG"}}}}
    r = cam.run(setup)
    p = r["data"]["programs"][1]                               # 调头车左端：Ø30 到 Ø40 的轴肩
    texts = [c["text"] for c in p["checks"] if c["level"] in ("error", "warn")]
    assert any("轴肩根部车出来是 R0.4 的圆角" in t for t in texts)
    assert not any(t.startswith("残留") or "过切" in t for t in texts)
    assert "刀尖圆弧 R0.4 已补偿" in p["gcode"]


def test_face_reaches_past_centre():
    mv = P.turn_face(44, 1.0, 1.0, 0.25, nose_r=0.8)
    assert min(m["x"] for m in mv if m["t"] == "feed") == pytest.approx(-1.8)
    prog = {"number": 1, "title": "t", "header": {}, "ops": [
        {"tool": {"n": 1, "name": "粗车"}, "spindle": {"css": 200, "max_rpm": 3000}, "moves": mv, "title": "端面"}]}
    parsed = S.parse(post.post(prog, LATHE), LATHE)
    s = S.simulate_turn(parsed, {"d": 44, "z_right": 1.0, "z_left": -20}, {1: {"kind": "turn", "nose_r": 0.8}},
                        target={"outer": [(0.0, 44.0), (-20.0, 44.0)]})
    assert s["face_left"] == pytest.approx(0.0, abs=1e-9)
    # 只车到 X−1（以前的做法）时中心留一个小凸台
    mv1 = [dict(m, x=-1.0) if m.get("x") == pytest.approx(-1.8) else m for m in mv]
    prog["ops"][0]["moves"] = mv1
    s1 = S.simulate_turn(S.parse(post.post(prog, LATHE), LATHE), {"d": 44, "z_right": 1.0, "z_left": -20},
                         {1: {"kind": "turn", "nose_r": 0.8}}, target={"outer": [(0.0, 44.0), (-20.0, 44.0)]})
    assert s1["face_left"] > 0.1


def test_achievable_fills_concave_corner_with_radius():
    h, rn = 0.01, 0.5
    zc = -10 + (np.arange(1000) + 0.5) * h
    rt = np.where(zc < -5, 20.0, 15.0)                         # 轴肩：左边大
    ra = S.achievable(zc, rt, rn, h)
    j = int(np.argmin(abs(zc - (-5 + rn))))
    assert ra[j] == pytest.approx(15.0, abs=h)                 # 离轴肩 rε 处已回到 15
    k = int(np.argmin(abs(zc - (-5 + rn * (1 - 1 / math.sqrt(2))))))
    assert ra[k] == pytest.approx(15 + rn * (1 - 1 / math.sqrt(2)), abs=2 * h)   # 圆角 45° 处
    assert np.all(ra >= rt - 1e-12)
