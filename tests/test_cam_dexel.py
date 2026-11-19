"""三向 dexel 材料去除（ADR-0106 Q2 第 1 步）：与解析值、独立的逐点判断、高度图仿真对照。"""

import math

import numpy as np
import pytest

from analysis.cam import dexel as D
from analysis.cam import machines
from analysis.cam import paths as P
from analysis.cam import sim as S
from tests.verification import record

VMC = machines.get("EX-VMC")


def _box(h=0.25):
    return D.Dexel.box([0, 0, -20], [60, 40, 0], h, pad=8)


def test_box_volume_is_exact():
    assert _box().volume() == pytest.approx(60 * 40 * 20, abs=1e-9)


@pytest.mark.parametrize("h", [0.5, 0.25])
def test_flat_endmill_slot_volume_converges(h):
    """平底刀 Ø10 铣直槽 40 长、5 深：体积 = (40·10 + π·5²)·5"""
    st = _box(h)
    r = st.cut(D.Tool.from_spec({"kind": "endmill", "d": 10, "L": 30}), [10, 20, -5], [50, 20, -5])
    exact = (40 * 10 + math.pi * 25) * 5
    record((f"平底刀直槽去除体积（网格 {h:g}）", f"flat end mill slot volume (grid {h:g})"), r["volume"], exact,
           tol=0.01 * h / 0.25, unit="mm³", formula="V = (L·D + π·R²)·ap")
    assert r["volume"] == pytest.approx(exact, rel=0.01 * h / 0.25)
    assert r["depth"] == pytest.approx(5.0, abs=1e-9)
    assert 60 * 40 * 20 - st.volume() == pytest.approx(r["volume"], rel=1e-9)


def test_ball_endmill_slot_volume():
    """球头 Ø10 刀尖在 Z−5（球心正好在顶面）：半圆柱槽 + 两个四分之一球 = 半圆柱 + 半球"""
    st = _box()
    r = st.cut(D.Tool.from_spec({"kind": "ballend", "d": 10, "L": 30}), [10, 20, -5], [50, 20, -5])
    exact = 40 * math.pi * 25 / 2 + 2 / 3 * math.pi * 125
    record(("球头刀直槽去除体积", "ball end mill slot volume"), r["volume"], exact, tol=0.005, unit="mm³",
           formula="V = L·πR²/2 + 2πR³/3")
    assert r["volume"] == pytest.approx(exact, rel=0.005)


def test_drill_volume_with_cone_tip():
    """钻头 Ø8、118° 顶角，钻到刀尖 Z−10：圆柱 + 圆锥"""
    st = _box()
    r = st.cut(D.Tool.from_spec({"kind": "drill", "d": 8, "L": 40}), [30, 20, 5], [30, 20, -10])
    hc = 4 / math.tan(math.radians(59))
    exact = math.pi * 16 * (10 - hc) + math.pi * 16 * hc / 3
    record(("钻头（118° 顶角）去除体积", "drill (118° point) volume"), r["volume"], exact, tol=0.01, unit="mm³",
           formula="V = πR²(h − hc) + πR²hc/3")
    assert r["volume"] == pytest.approx(exact, rel=0.01)


def test_bullnose_between_flat_and_ball():
    """牛鼻刀（圆角 2）切掉的体积在同直径平底刀与球头之间"""
    vols = {}
    for kind in ("endmill", "bullnose", "ballend"):
        st = _box()
        vols[kind] = st.cut(D.Tool.from_spec({"kind": kind, "d": 10, "L": 30, "corner_r": 2}),
                            [10, 20, -5], [50, 20, -5])["volume"]
    assert vols["ballend"] < vols["bullnose"] < vols["endmill"]
    # 牛鼻解析值：直段截面 = 矩形 10×5 减两个圆角缺口 A = rc²(1 − π/4)；两端合起来是一整个刀具回转体，
    # 缺的圆环体积按古尔丁定理 2π·r̄·A，缺口形心离刀轴 r̄ = R − rc + rc³ / (6A)
    R, rc = 5.0, 2.0
    A = rc * rc * (1 - math.pi / 4)
    rbar = R - rc + rc ** 3 / (6 * A)
    exact = (2 * R * 5 - 2 * A) * 40 + (math.pi * R * R * 5 - 2 * math.pi * rbar * A)
    record(("牛鼻刀直槽去除体积", "bull nose end mill slot volume"), vols["bullnose"], exact, tol=0.005, unit="mm³",
           formula="截面减圆角缺口；两端按古尔丁定理 / cross-section minus corner gaps; ends by Pappus")
    assert vols["bullnose"] == pytest.approx(exact, rel=0.005)


def _in_tilted_sweep(p, a, b, w, R, L, n=400):
    """独立判断：点 p 是否在倾斜平底刀（刀尖 a→b，刀轴 w）扫过的范围里——逐个刀位判点在圆柱里"""
    for s in np.linspace(0, 1, n):
        tip = a + (b - a) * s
        rel = p - tip
        z = rel @ w
        if 0 <= z <= L and np.linalg.norm(rel - z * w) <= R:
            return True
    return False


def test_tilted_tool_matches_pointwise_check():
    """3+2：平底刀 Ø10 刀轴倾 30°，沿 X 走 20，刀尖 Z−2。dexel 的去除体积与在毛坯里随机撒点逐点判断的体积一致"""
    w = np.array([math.sin(math.radians(30)), 0, math.cos(math.radians(30))])
    a, b = np.array([20.0, 20, -2]), np.array([40.0, 20, -2])
    st = _box()
    r = st.cut(D.Tool.from_spec({"kind": "endmill", "d": 10, "L": 30}), a, b, w=w)
    rng = np.random.default_rng(1)
    lo, hi = np.array([10.0, 12, -8]), np.array([50.0, 28, 0])
    pts = lo + (hi - lo) * rng.random((4000, 3))
    frac = np.mean([_in_tilted_sweep(p, a, b, w, 5.0, 30.0, n=200) for p in pts])
    mc = frac * np.prod(hi - lo)
    se = np.prod(hi - lo) * math.sqrt(frac * (1 - frac) / len(pts))
    record(("3+2 斜刀轴（30°）去除体积与逐点判断", "3+2 tilted axis (30°) volume vs point sampling"), r["volume"], mc,
           tol=(4 * se + 0.01 * mc) / mc, unit="mm³", formula="4000 个随机点逐个刀位判断 / 4000 random points tested pose by pose")
    assert abs(r["volume"] - mc) < 4 * se + 0.01 * mc


def test_five_axis_rotation_is_split():
    """五轴联动：刀轴在一段走刀里转 20°（刀尖走直线），拆成小段算；与逐个刀位判点（刀轴同样插值）撒点得到的体积一致"""
    tool = D.Tool.from_spec({"kind": "endmill", "d": 10, "L": 30})
    w0 = np.array([0.0, 0, 1])
    w1 = np.array([math.sin(math.radians(20)), 0, math.cos(math.radians(20))])
    a, b = np.array([20.0, 20, -3]), np.array([40.0, 20, -3])
    st = _box()
    r = st.cut(tool, a, b, w=w0, w_end=w1)
    rng = np.random.default_rng(2)
    lo, hi = np.array([12.0, 12, -6]), np.array([48.0, 28, 0])
    pts = lo + (hi - lo) * rng.random((3000, 3))
    ss = np.linspace(0, 1, 200)
    tips = a + (b - a) * ss[:, None]
    ws = np.array([D._slerp(w0, w1, x) for x in ss])

    def inside(p):
        rel = p - tips
        z = np.einsum("ik,ik->i", rel, ws)
        rad = np.linalg.norm(rel - z[:, None] * ws, axis=1)
        return bool(((z >= 0) & (z <= 30) & (rad <= 5)).any())

    frac = np.mean([inside(p) for p in pts])
    mc = frac * np.prod(hi - lo)
    se = np.prod(hi - lo) * math.sqrt(frac * (1 - frac) / len(pts))
    assert abs(r["volume"] - mc) < 4 * se + 0.01 * mc


def test_matches_heightmap_for_three_axis_pocket():
    """三轴竖直刀具：dexel 的 Z 组射线顶面与现有高度图仿真一致（网格精度内）"""
    mv = P.mill_pocket((10, 10, 50, 30), 6.0, 4.0, 10.0, 0.5, 2.0, 600, 200)
    gc = [f"{'G0' if m['t'] == 'rapid' else 'G1'} X{m['x']:.4f} Y{m['y']:.4f} Z{m['z']:.4f}" + (f" F{m['f']:g}" if "f" in m else "")
          for m in mv if m["t"] != "comment"]
    text = "\n".join(["G90 G21 G17", "T1 M6", "S3000 M3", *gc, "M30"])
    parsed = S.parse(text, VMC)
    h = 0.25
    hm = S.simulate_mill(parsed, {"box": (0, 0, 60, 40), "top": 0}, {1: {"kind": "endmill", "d": 10}}, h=h)
    st = D.Dexel(np.array([hm["x"][0] - h / 2, hm["y"][0] - h / 2, -10]),
                 np.array([hm["x"][-1] + h / 2, hm["y"][-1] + h / 2, 0]), h)
    st.fill(lambda k, U, V: D._box_interval(k, U, V, np.array([0, 0, -10.0]), np.array([60, 40, 0.0])))
    D.simulate(parsed, st, {1: {"kind": "endmill", "d": 10, "L": 30}})
    top = np.fmax.reduce(np.nan_to_num(st.E[2], nan=-np.inf), -1)
    inside = hm["inside"]
    diff = np.abs(np.where(inside, top - hm["H"], 0.0))
    record(("三轴型腔：dexel 与高度图的最大差", "3-axis pocket: max difference dexel vs height map"), float(diff.max()), 0.0,
           tol=0.01, rel=False, unit="mm", formula="同一程序两种算法 / same program, two algorithms")
    assert diff.max() < 0.01
    # 型腔体积（圆角矩形 40×20、R6、深 4）
    exact = (40 * 20 - (4 - math.pi) * 36) * 4
    assert 60 * 40 * 10 - st.volume() == pytest.approx(exact, rel=0.01)


def _box_tris(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return v[np.array(f)]


def test_from_triangles_box():
    dx = D.Dexel.from_triangles(_box_tris([0, 0, -20], [60, 40, 0]), 0.25,
                                lo=np.array([-8.0, -8, -28]), hi=np.array([68.0, 48, 8]))
    assert dx.volume() == pytest.approx(48000, rel=1e-9)


def test_known_overcut_is_found():
    """零件是 60×40×20 的块、上面开 5 深的槽（目标）；程序把槽铣到 5.30 深：三维比对查出过切 0.30（± 网格）"""
    h = 0.25
    lo, hi = np.array([-8.0, -8, -28]), np.array([68.0, 48, 8])
    st = D.Dexel(lo, hi, h)
    st.fill(lambda k, U, V: D._box_interval(k, U, V, np.array([0, 0, -20.0]), np.array([60, 40, 0.0])))
    part = st.copy()
    tool = D.Tool.from_spec({"kind": "endmill", "d": 10, "L": 30})
    part.cut(tool, [10, 20, -5], [50, 20, -5])                     # 目标：5 深
    st.cut(tool, [10, 20, -5.3], [50, 20, -5.3])                   # 程序：5.3 深
    c = D.compare(st, part)
    record(("已知过切 0.30 mm 的三维比对", "3D comparison of a known 0.30 mm overcut"), c["over_max"], 0.30, tol=h / 2,
           rel=False, unit="mm", formula="程序比目标深 0.30 / program 0.30 deeper than target")
    assert c["over"] and c["over_max"] == pytest.approx(0.30, abs=h / 2)
    x, y, z = c["at"]
    assert 5 <= x <= 55 and 15 <= y <= 25 and z == pytest.approx(-5.3, abs=h)
    # 程序只铣到 4.8 深：没有过切，残留 0.2
    st2 = D.Dexel(lo, hi, h)
    st2.fill(lambda k, U, V: D._box_interval(k, U, V, np.array([0, 0, -20.0]), np.array([60, 40, 0.0])))
    st2.cut(tool, [10, 20, -4.8], [50, 20, -4.8])
    c2 = D.compare(st2, part)
    assert not c2["over"] and c2["under_max"] == pytest.approx(0.2, abs=h / 2)


def test_rapid_into_stock_is_reported():
    text = "G90 G21 G17\nT1 M6\nS3000 M3\nG0 X30 Y20 Z5\nG0 Z-3\nM30"
    parsed = S.parse(text, VMC)
    st = _box()
    r = D.simulate(parsed, st, {1: {"kind": "endmill", "d": 10, "L": 30}})
    assert any("快移撞到工件" in i["text"] for i in r["issues"])


def test_z_mesh_is_closed_for_box():
    st = D.Dexel.box([0, 0, -5], [3, 2, 0], 1.0)
    v, t = st.z_mesh()
    # 6 个方柱：顶 6 + 底 6 + 外侧面 10 个，每个 2 个三角形
    assert len(t) == 2 * (6 + 6 + 10)
    assert v[:, 2].min() == -5 and v[:, 2].max() == 0
