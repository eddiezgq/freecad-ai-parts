# -*- coding: utf-8 -*-
"""第 13 轮 数控编程：刀路、后处理、读程序、加工时间、仿真与检查。
验收（实施细则 三）：车削仿真与本工序尺寸差 ≤ 0.01 mm、不过切；铣削过切为 0、残留在刀具半径以内；
G 代码能被独立的开源解析器（pygcode）读通；超程、转速超限查得出；加工时间与手算差 < 2%。"""
import math

import numpy as np
import pytest

shapely = pytest.importorskip("shapely")
from shapely import contains_xy, distance, points  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402

from cae import cam, cam_post, cam_sim  # noqa: E402

SEGS = [(30, 40), (35, 12), (40, 60), (35, 25), (30, 30)]          # SH-301（设计台默认参数）
ROUGH = {30: 31.5, 35: 36.5, 40: 41.5}                               # 粗车工序尺寸（工艺规程 20：单边留 0.75）
FINISH = {30: 30.0, 35: 35.3, 40: 40.3}                              # 精车工序尺寸（工艺规程 40：留磨量 0.3）
TURN = {1: {"kind": "turn"}, 2: {"kind": "turn"}, 3: {"kind": "groove", "w": 3.0}}


def lathe_prog(ops, number=1301):
    return {"machine": "CNC-L01", "number": number, "title": "SH-301 测试", "header": {"item": "SH-301", "revision": "A"}, "ops": ops}


def rough_finish():
    pr, L, _ = cam.shaft_profile([(ROUGH[d], l) for d, l in SEGS], 0, "right")
    pf, _, _ = cam.shaft_profile([(FINISH[d], l) for d, l in SEGS], 1.5, "right")
    return pr, pf, L


# ---------------------------------------------------------------- 车削
def test_shaft_profile_sides():
    pr, L, tot = cam.shaft_profile(SEGS, 1.5, "right")
    assert tot == 167 and L == 115                        # 右边一次车到最大直径那段（含）
    assert pr[0] == (0.0, 27.0) and pr[1] == (-1.5, 30)  # 倒角
    pl, L2, _ = cam.shaft_profile(SEGS, 1.5, "left")
    assert L2 == 52 and pl[-2:] == [(-52, 35), (-52, 40)]      # 调头：车到 Ø40 轴肩为止


def test_rough_turning_matches_operation_size():
    pr, _, L = rough_finish()
    mv = cam.turn_face(50, 2, 1.0, 0.2) + cam.turn_rough(pr, 50, 2.5, 0.3, 0.0, 0.0)
    g = cam_post.post(lathe_prog([{"tool": {"n": 1, "name": "外圆车刀"}, "spindle": {"css": 120, "max_rpm": 3000}, "moves": mv}]))
    r = cam_sim.run(g, "CNC-L01", {"d": 50, "z_right": 2, "z_left": -125}, TURN, target=pr)
    assert not [c for c in r["checks"] if c["level"] == "error"], r["checks"]
    s = r["sim"]
    assert s["dev_min"] > -0.01 and s["dev_max"] <= 0.01          # 与粗车工序尺寸差 ≤ 0.01
    assert s["face_left"] == 0                                     # 端面余量车干净
    assert s["ap_max"] <= 2.5 + 1e-6                               # 每刀不超过工艺规程的 ap


def test_rough_with_allowance_then_finish():
    pr, pf, L = rough_finish()
    # 粗车留 径向 0.3、轴向 0.1，再精车到精车工序尺寸
    mv1 = cam.turn_rough(pf, 50, 2.5, 0.3, 0.3, 0.1)
    mv2 = cam.turn_finish(pf, 50, 0.15)
    g = cam_post.post(lathe_prog([
        {"tool": {"n": 1, "name": "外圆粗车刀"}, "spindle": {"css": 120, "max_rpm": 3000}, "moves": mv1},
        {"tool": {"n": 2, "name": "外圆精车刀"}, "spindle": {"css": 150, "max_rpm": 3500}, "moves": mv2}]))
    p = cam_sim.parse(g, "CNC-L01")
    half = [m for m in p["moves"] if m["tool"] == 1]
    s1 = cam_sim.simulate_turn({"moves": half}, {"d": 50, "z_right": 0, "z_left": -125}, TURN,
                               target=cam.with_allowance(pf, 0.3, 0.1))
    assert s1["dev_min"] > -0.01 and s1["dev_max"] <= 0.01 and not s1["issues"]
    s2 = cam_sim.simulate_turn(p, {"d": 50, "z_right": 0, "z_left": -125}, TURN, target=pf)
    assert s2["dev_min"] > -0.01 and s2["dev_max"] <= 0.01, (s2["dev_min"], s2["dev_max"], s2["under_z"])
    assert not s2["issues"]
    assert len(p["tool_changes"]) == 2


def test_overcut_and_rapid_collision_detected():
    pr, pf, L = rough_finish()
    bad = [dict(m) for m in cam.turn_finish(pf, 50, 0.15)]
    for m in bad:                                     # 把一段轮廓故意往里多车 0.2
        if m["t"] == "feed" and abs(m.get("x", 0) - 35.3) < 1e-9:
            m["x"] = 34.9
    g = cam_post.post(lathe_prog([{"tool": {"n": 2}, "spindle": {"rpm": 1000}, "moves": bad}]))
    r = cam_sim.run(g, "CNC-L01", {"profile": pf, "d": 50, "z_right": 0, "z_left": -125}, TURN, target=pf)
    assert any("过切" in c["text"] for c in r["checks"])
    g2 = "G21 G18 G99\nT0101\nG97 S800 M03\nG00 X30.0 Z2.0\nG00 X30.0 Z-20.0\nM30\n"     # 快移直接扎进 Ø50 毛坯
    r2 = cam_sim.run(g2, "CNC-L01", {"d": 50, "z_right": 0, "z_left": -100}, TURN)
    assert any("快移撞到工件" in c["text"] for c in r2["checks"])


def test_groove():
    mv = cam.turn_groove(-40, 26, 7.0, 30, 0.05, 3.0)
    g = cam_post.post(lathe_prog([{"tool": {"n": 3, "name": "切槽刀 3mm"}, "spindle": {"rpm": 600}, "moves": mv}]))
    s = cam_sim.run(g, "CNC-L01", {"d": 30, "z_right": 0, "z_left": -80}, TURN)["sim"]
    groove = (s["z"] <= -40) & (s["z"] >= -47)
    assert np.allclose(s["r"][groove][1:-1], 13.0)
    assert np.allclose(s["r"][(s["z"] > -39.9) | (s["z"] < -47.1)], 15.0)


# ---------------------------------------------------------------- 铣削
POCKET = box(-30, -20, 30, 20).buffer(-5).buffer(5).difference(Point(0, 0).buffer(6, quad_segs=32))   # R5 圆角型腔，中间 Ø12 岛
OUTLINE = box(-50, -40, 50, 40)
HOLES = [(-40, -30), (40, -30), (40, 30), (-40, 30)]
MILL = {1: {"kind": "endmill", "d": 10}, 2: {"kind": "endmill", "d": 8}, 3: {"kind": "drill", "d": 8.5}}


def plate_program(pocket=POCKET):
    ops = [{"tool": {"n": 1, "name": "立铣刀", "d": 10}, "spindle": {"rpm": 2400}, "moves": cam.mill_contour(OUTLINE, 10, 10, 5, 480)},
           {"tool": {"n": 2, "name": "立铣刀", "d": 8}, "spindle": {"rpm": 3000}, "moves": cam.mill_pocket(pocket, 8, 8, 0.45, 2, 450, 150)},
           {"tool": {"n": 3, "name": "钻头", "d": 8.5}, "spindle": {"rpm": 1200}, "moves": cam.drill(HOLES, 15, 5, 120)}]
    return cam_post.post({"machine": "VMC-01", "number": 5001, "title": "测试板", "ops": ops})


def plate_target(pocket):
    def T(X, Y):
        t = np.where(contains_xy(OUTLINE, X, Y), 0.0, -10.0)
        t[contains_xy(pocket, X, Y)] = -8.0
        for x, y in HOLES:
            t[(X - x) ** 2 + (Y - y) ** 2 < 4.25 ** 2] = -15.0
        return t
    return T


@pytest.mark.parametrize("pocket", [POCKET, box(-30, -20, 30, 20)], ids=["圆角带岛", "尖角"])
def test_plate_no_overcut_residual_within_radius(pocket):
    g = plate_program(pocket)
    r = cam_sim.run(g, "VMC-01", {"box": (-52, -42, 52, 42)}, MILL, plate_target(pocket))
    assert not [c for c in r["checks"] if c["level"] == "error"], r["checks"][:3]
    s = r["sim"]
    assert s["over"] == 0
    X, Y = np.meshgrid(s["x"], s["y"], indexing="ij")
    um = s["under_mask"] & contains_xy(pocket, X, Y)
    if um.any():                                       # 残留只在型腔角上，离壁不超过刀具半径
        d = distance(pocket.boundary, points(X[um], Y[um]))
        assert d.max() <= 4.0 + s["h"]
    assert not (s["under_mask"] & ~contains_xy(pocket, X, Y)).any()


def test_keyway_on_shaft():
    """SH-301 键槽 12×45：精车后 Ø40.3，槽底到下母线 35.15 → 从顶点往下 5.15；Ø12 键槽铣刀一刀宽，分 5 层"""
    depth = 40.3 - 35.15
    mv = cam.mill_slot((-16.5, 0), (16.5, 0), 12, depth, 12, depth / 5, 120, 60)
    g = cam_post.post({"machine": "KEY-01", "number": 5050, "title": "键槽", "ops": [
        {"tool": {"n": 1, "name": "键槽铣刀", "d": 12}, "spindle": {"rpm": 800}, "moves": mv}]})
    slot = box(-16.5, -6, 16.5, 6).union(Point(-16.5, 0).buffer(6, quad_segs=64)).union(Point(16.5, 0).buffer(6, quad_segs=64))

    def T(X, Y):
        t = np.sqrt(np.clip(20.15 ** 2 - Y ** 2, 0, None)) - 20.15
        t[contains_xy(slot.buffer(-0.05), X, Y)] = -depth
        t[~contains_xy(slot.buffer(0.05), X, Y) & ~(np.abs(Y) < 20.15)] = np.nan
        edge = contains_xy(slot.buffer(0.05), X, Y) & ~contains_xy(slot.buffer(-0.05), X, Y)
        t[edge] = np.nan                                 # 槽边上一格不比
        return t
    r = cam_sim.run(g, "KEY-01", {"box": (-30, -20.15, 30, 20.15), "cyl_r": 20.15}, {1: {"kind": "endmill", "d": 12}}, T)
    s = r["sim"]
    assert not [c for c in r["checks"] if c["level"] == "error"], r["checks"]
    assert s["over"] == 0 and not s["under_mask"].any()
    assert s["ap_max"] == pytest.approx(depth / 5, abs=0.01)       # 每层切深 = 槽深 / 5


# ---------------------------------------------------------------- G 代码：独立解析、检查、时间
def test_independent_parser_reads_both_posts():
    pygcode = pytest.importorskip("pygcode")
    pr, pf, L = rough_finish()
    progs = [cam_post.post(lathe_prog([{"tool": {"n": 1}, "spindle": {"css": 120, "max_rpm": 3000},
                                        "moves": cam.turn_rough(pf, 50, 2.5, 0.3)}])), plate_program()]
    for g in progs:
        mine = cam_sim.parse(g, "CNC-L01" if "G18" in g else "VMC-01")
        n_motion = 0
        for raw in g.splitlines():
            if raw.strip() in ("%", "") or raw.startswith("O"):
                continue
            line = pygcode.Line(raw)                      # 读不通会抛异常
            n_motion += sum(1 for c in line.block.gcodes if c.word_key and str(c.word_key) in ("G00", "G01"))
            n_motion += 1 if (not line.block.gcodes and any(str(w)[0] in "XYZ" for w in line.block.modal_params)) else 0
        assert n_motion > 10
        assert len(mine["moves"]) >= n_motion * 0.9


def test_fanuc_numbers_have_decimal_point():
    assert cam_post.num(200) == "200.0" and cam_post.num(35.3) == "35.3" and cam_post.num(-0.0001) == "0.0"


def test_limits_and_spindle_checks():
    g = "G21 G17 G90 G94\nT1 M06\nG54\nS9000 M03\nG00 X500.0 Y0.0\nG43 Z50.0 H01\nG01 Z-5.0 F100.0\nM30\n"
    ch = cam_sim.machine_checks(cam_sim.parse(g, "VMC-01"), "VMC-01")
    txt = " ".join(c["text"] for c in ch)
    assert "X 超程" in txt and "超过机床最高转速" in txt
    g2 = "G21 G18 G99\nT0101\nG96 S200 M03\nG00 X40.0 Z2.0\nG01 X0.0 F0.1\nM30\n"
    txt2 = " ".join(c["text"] for c in cam_sim.machine_checks(cam_sim.parse(g2, "CNC-L01"), "CNC-L01"))
    assert "G50" in txt2
    g3 = "G21 G17 G90 G94\nT1 M06\nG00 X0.0 Y0.0 Z5.0\nG01 Z-1.0 F100.0\nM30\n"
    assert any("M03" in c["text"] for c in cam_sim.machine_checks(cam_sim.parse(g3, "VMC-01"), "VMC-01"))


def test_time_matches_hand_calculation():
    # 车：G97 恒转速 800 r/min，f 0.2 mm/r，车外圆 100 mm → 100 / (0.2×800) min
    g = "G21 G18 G99\nT0101\nG97 S800 M03\nG00 X40.0 Z2.0\nG01 Z-98.0 F0.2\nM30\n"
    p = cam_sim.parse(g, "CNC-L01")
    t = cam_sim.timing(p, "CNC-L01")
    assert abs(t["cut_s"] - 60 * 100 / (0.2 * 800)) / t["cut_s"] < 0.02
    # 车：G96 恒线速 150 m/min，从 Ø40 车端面到 Ø10，G50 限速 3000。
    #   t = ∫ dr / (f·n)，n = 1000·vc/(π·D)：D ≥ D* 时 t = π(D₁² − D*²)/(4000·vc·f)；D* = 1000·vc/(π·3000) 以下转速被限在 3000，t = (D* − D₀)/2/(f·3000)
    g = "G21 G18 G99\nT0101\nG50 S3000\nG96 S150 M03\nG00 X40.0 Z0.0\nG01 X10.0 F0.1\nM30\n"
    t = cam_sim.timing(cam_sim.parse(g, "CNC-L01"), "CNC-L01")
    Ds = 1000 * 150 / (math.pi * 3000)
    hand = 60 * (math.pi * (40 ** 2 - Ds ** 2) / (4000 * 150 * 0.1) + (Ds - 10) / 2 / (0.1 * 3000))
    assert abs(t["cut_s"] - hand) / hand < 0.02
    # 铣：G94 F300 走 3 段共 150 mm → 30 s；快移 Z 50 mm
    g = "G21 G17 G90 G94\nT1 M06\nS2000 M03\nG00 X0.0 Y0.0 Z5.0\nG01 Z-5.0 F300.0\nX50.0\nY40.0\nM30\n"
    t = cam_sim.timing(cam_sim.parse(g, "VMC-01"), "VMC-01")
    assert abs(t["cut_s"] - 60 * 100 / 300) < 1e-6
    assert t["tool_changes"] == 1


def test_peck_drill_expands():
    g = "G21 G17 G90 G94\nT3 M06\nS1200 M03\nG00 X0.0 Y0.0 Z5.0\nG98 G83 X10.0 Y0.0 Z-15.0 R2.0 Q5.0 F120.0\nX20.0\nG80\nM30\n"
    p = cam_sim.parse(g, "VMC-01")
    feeds = [m for m in p["moves"] if m["t"] == "feed"]
    assert len(feeds) == 2 * 4                                           # 17 mm 每次 5 → 4 次，两个孔
    assert min(m["b"][2] for m in feeds) == -15.0
    assert p["moves"][-1]["b"][2] == 5.0                                 # G98 回初始平面


def test_arc_interpolation():
    """G03 逆时针、G02 顺时针（从 +Z 往下看）；圆心用 I、J 或半径 R 给"""
    g = ("G21 G17 G90 G94\nT1 M06\nS1000 M03\nG00 X10.0 Y0.0 Z-1.0\n"
         "G03 X-10.0 Y0.0 I-10.0 J0.0 F200.0\n"      # 第 5 行：(10,0) 逆时针到 (-10,0)，走上半圆
         "G03 X10.0 Y0.0 R10.0\n"                     # 第 6 行：(-10,0) 逆时针回 (10,0)，走下半圆
         "G02 X-10.0 Y0.0 I-10.0 J0.0\n"              # 第 7 行：(10,0) 顺时针到 (-10,0)，走下半圆
         "M30\n")
    p = cam_sim.parse(g, "VMC-01")
    arcs = {}
    for m in p["moves"]:
        if m.get("arc"):
            arcs.setdefault(m["line"], []).append(m["b"])
    assert all(abs(math.hypot(x, y) - 10) < 1e-6 for pts in arcs.values() for x, y, _ in pts)
    assert max(y for _, y, _ in arcs[5]) == pytest.approx(10, abs=0.02)
    assert min(y for _, y, _ in arcs[6]) == pytest.approx(-10, abs=0.02)
    assert min(y for _, y, _ in arcs[7]) == pytest.approx(-10, abs=0.02)


def test_rpm_and_feed_formulas():
    assert cam.spindle_rpm(120, 50, 4000) == pytest.approx(763.94, rel=1e-4)
    assert cam.spindle_rpm(120, 5, 3000) == 3000
    assert cam.mill_feed(0.05, 4, 2000) == pytest.approx(400)


# ---------------------------------------------------------------- 第 2 步：几何识别、从工艺规程编程
gmsh = pytest.importorskip("gmsh")
bd = pytest.importorskip("build123d")
from cae import cam_geom as CG, cam_job as J  # noqa: E402

DIG = __import__("pathlib").Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def plan():
    import yaml
    return yaml.safe_load(open(DIG / "std" / "SH-301_process.yaml", encoding="utf-8"))


@pytest.fixture(scope="module")
def shaft():
    from hub import design as D
    p = D.normalize(D.defaults())
    return p, D.step_bytes(p)


@pytest.fixture(scope="module")
def plate_step(tmp_path_factory):
    with bd.BuildPart() as p:
        bd.Box(100, 80, 20, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MAX))
        with bd.BuildSketch(bd.Plane.XY):
            bd.RectangleRounded(60, 40, 5)
            bd.Circle(6, mode=bd.Mode.SUBTRACT)
        bd.extrude(amount=-8, mode=bd.Mode.SUBTRACT)
        with bd.Locations(*[(x, y, 0) for x in (-40, 40) for y in (-30, 30)]):
            bd.Hole(4.25)
    f = tmp_path_factory.mktemp("cam") / "plate.step"
    bd.export_step(p.part, str(f))
    return f.read_bytes()


def test_turn_profile_from_step(shaft):
    params, step = shaft
    r = CG.turn_profile(step)
    want = cam.design_profile(params["segments"], params["chamfer"])
    assert r["axis"] == "z" and r["length"] == pytest.approx(167, abs=1e-3)
    assert len(r["profile"]) == len(want)
    for (t, d), (tw, dw) in zip(r["profile"], want):
        assert t == pytest.approx(tw, abs=0.01) and d == pytest.approx(dw, abs=0.01)
    assert r["ignored_faces"]                                   # 键槽的面不算回转面


def test_mill_features_from_step(plate_step):
    f = CG.mill_features(plate_step)
    assert f["top"] == pytest.approx(0, abs=1e-4) and f["bottom"] == pytest.approx(-20, abs=1e-4)
    assert len(f["holes"]) == 4 and all(h["through"] and h["d"] == pytest.approx(8.5, abs=0.01) for h in f["holes"])
    assert len(f["pockets"]) == 1
    from shapely.geometry import shape
    g = shape(f["pockets"][0]["polygon"])
    assert f["pockets"][0]["depth"] == pytest.approx(8, abs=1e-3) and len(g.interiors) == 1      # 带一个岛
    assert g.area == pytest.approx(60 * 40 - (4 - math.pi) * 25 - math.pi * 36, rel=2e-3)


def test_plan_turn_from_process_plan(plan, shaft):
    params, step = shaft
    design = CG.turn_profile(step)["profile"]
    rough = J.plan_turn(plan, 20, design, "A")
    assert rough["mode"] == "rough" and rough["length"] == 168 and rough["stock"]["d"] == 50
    assert rough["cut"]["vc"] == 120 and rough["cut"]["ap"] == 2.5 and "工艺规程" in rough["sources"]["cut.vc"]
    names = {f["name"] for f in plan["drawing"]}

    def want(seq):          # 工序里列出（且图纸上有）的部位都按公差带中间编
        op = next(o for o in plan["operations"] if o["seq"] == seq)
        return {f["name"]: J.mid(f["size_mm"], f.get("es_mm"), f.get("ei_mm")) for f in op.get("features", []) if f["name"] in names}
    got = {s["name"]: s["op"] for s in rough["sizes"]}
    assert got == want(20) and got["轴承位"] == 36.375 and got["齿轮位"] == 41.375          # 36.5 0/−0.25 编 36.375
    assert rough["unmapped"] == ([] if "轴端" in got else [30.0])                          # 轴端没列在工序里时按车削余量加
    fin = J.plan_turn(plan, 40, design, "A")
    assert fin["mode"] == "finish" and fin["length"] == 167 and fin["stock"]["from_seq"] == 20
    got = {s["name"]: s["op"] for s in fin["sizes"]}
    assert got == want(40) and got["轴承位"] == 35.2805 and got["齿轮位"] == 40.2805
    for spec in (rough, fin):
        progs = J.generate(spec)
        assert [p["setup"] for p in progs] == ["right", "left"]
        for p in progs:
            assert not [c for c in p["checks"] if c["level"] == "error"], p["checks"]
            assert p["sim"]["dev_min"] > -0.01 and p["sim"]["dev_max"] <= 0.01
            assert p["sim"]["face_left"] == 0
        assert spec["compare"]["plan_minutes"] and spec["compare"]["program_minutes"] > 0
    assert rough["compare"]["program_minutes"] == pytest.approx(rough["compare"]["basic_minutes"], rel=0.25)


def test_plan_slot_keyway(plan, shaft):
    params, _ = shaft
    s = J.plan_slot(plan, 50, params, "A")
    assert s["depth"] == pytest.approx(40.2805 - 35.035, abs=1e-4)          # Ø40.3 0/−0.039、H 35.15 −0.03/−0.20，都取中间
    assert s["x0_from_left"] == 82
    p = J.generate(s)[0]
    assert not [c for c in p["checks"] if c["level"] == "error"]
    assert p["sim"]["over"] == 0 and p["sim"]["under"] == 0


def test_plan_mill_plate(plate_step):
    f = CG.mill_features(plate_step)
    s = J.plan_mill(f, "VMC-01", "6061", 2.0, "WQ-PLATE")
    assert [o["type"] for o in s["ops"]] == ["contour", "pocket", "drill"]
    assert s["ops"][1]["tool"]["d"] == 10                                     # R5 转角 → Ø10 刚好铣干净
    p = J.generate(s)[0]
    assert not [c for c in p["checks"] if c["level"] == "error"], p["checks"][:3]
    assert p["sim"]["over"] == 0 and p["sim"]["under"] == 0


def test_service_cam_jobs(tmp_path, monkeypatch, plan, shaft, plate_step):
    from fastapi.testclient import TestClient
    from cae import service
    monkeypatch.setattr(service, "DATA", str(tmp_path))
    with TestClient(service.app) as c:
        assert "CNC-L01" in c.get("/cam/machines").json()["machines"]
        g = c.post("/geometry", content=plate_step).json()
        r = c.post("/cam/recognize", json={"sha": g["sha"]}).json()
        assert r["turn"].get("error") and len(r["mill"]["holes"]) == 4
        spec = J.plan_mill(r["mill"], "VMC-01", "6061", 2.0, "WQ-PLATE")
        j = c.post("/cam/jobs", json={"spec": spec, "owner": "7", "factory": "wq_test", "title": "平板"}).json()
        assert j["status"] == "done" and j["kind"] == "cam" and j["stats"]["errors"] == 0, j.get("error")
        p = j["programs"][0]
        assert p["sim"]["over"] == 0 and p["path"][-1][5] == pytest.approx(p["time"]["cut_s"] + p["time"]["rapid_s"], rel=1e-3)
        nc = c.get("/cam/jobs/{}/0.nc".format(j["id"])).text
        assert nc.startswith("%\nO5001") and "G83" not in nc and "G81" in nc          # 8.5 通孔深 22.6 < 3d 不用啄钻
        assert len(c.get("/cam/jobs/{}/h0.bin".format(j["id"])).content) == 4 * p["sim"]["nx"] * p["sim"]["ny"]
        assert [x["id"] for x in c.get("/jobs", params={"factory": "wq_test", "kind": "cam"}).json()["jobs"]] == [j["id"]]
        assert c.post("/cam/jobs", json={"spec": {"kind": "x"}}).status_code == 400
        # SH-301 精车：两个程序（右端、调头左端）
        design = cam.design_profile(shaft[0]["segments"], shaft[0]["chamfer"])
        j = c.post("/cam/jobs", json={"spec": J.plan_turn(plan, 40, design, 1), "factory": "wq_test"}).json()
        assert j["status"] == "done" and [p["setup"] for p in j["programs"]] == ["right", "left"]
        assert j["compare"]["plan_minutes"] == 15


class _NoDB:
    """没有数据库时的枢纽：没有生效的工艺规程、没有发布记录（按教材样例工艺规程、设计台默认参数）"""
    def one(self, *a, **k):
        return None

    def q(self, *a, **k):
        return []

    def messages(self, *a, **k):
        return []


def test_hub_cam_api(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    from cae import service
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_SECRET", "test-secret")
    monkeypatch.setattr(service, "DATA", str(tmp_path))
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    from hub import cae_api
    monkeypatch.setattr(app_mod.H, "db", _NoDB())
    with TestClient(service.app) as svc:
        monkeypatch.setattr(cae_api, "CLIENT", svc)
        c = TestClient(app_mod.app)
        tok = app_mod._sign({"name": "小李", "role": "engineer", "mode": "teach", "teacher": False, "exp": 4e9})
        hd = {"x-wq-token": tok}
        assert c.get("/api/cam/ops?item=SH-301").status_code == 401
        ops = c.get("/api/cam/ops?item=SH-301", headers=hd).json()
        assert "教材样例" in ops["plan_source"] and [o["seq"] for o in ops["ops"] if o["cam"]] == [20, 40, 50]
        parts = c.get("/api/cam/parts", headers=hd).json()
        assert parts["items"][0]["item"] == "SH-301" and parts["examples"][0]["id"] == "WQ-PLATE"
        spec = c.post("/api/cam/spec", json={"item": "SH-301", "seq": 50}, headers=hd).json()
        assert spec["kind"] == "slot" and spec["depth"] == pytest.approx(5.2455)
        j = c.post("/api/cam/jobs", json={"spec": spec, "title": "键槽"}, headers=hd).json()
        assert j["status"] == "done" and j["owner_name"] == "小李"
        nc = c.get("/api/cam/jobs/{}/0.nc".format(j["id"]), headers=hd)
        assert nc.status_code == 200 and "O1501" in nc.text and "SH-301" in nc.text
        assert [x["id"] for x in c.get("/api/cam/jobs", headers=hd).json()["jobs"]] == [j["id"]]
        other = app_mod._sign({"name": "小王", "role": "engineer", "mode": "teach", "teacher": False, "exp": 4e9})
        assert c.get("/api/cam/jobs/" + j["id"], headers={"x-wq-token": other}).status_code == 403
        ex = c.post("/api/cam/examples/WQ-PLATE", headers=hd).json()
        sp = c.post("/api/cam/spec/geometry", json={"sha": ex["sha"]}, headers=hd).json()
        assert sp["kind"] == "mill25" and sp["recognized"] == {"turn": False, "mill": True}
        assert c.post("/api/cam/spec", json={"item": "SH-301", "seq": 30}, headers=hd).status_code == 400   # 调质不用编程
        r = c.post("/api/cam/ai-setup", json={"text": "分 5 层，每齿 0.04", "spec": spec}, headers=hd).json()
        assert r["engine"] == "rules" and [p["path"] for p in r["patch"]] == ["cut.ap", "cut.fz"]
        e = c.post("/api/cam/jobs/{}/explain".format(j["id"]), json={"k": 0}, headers=hd).json()
        assert e["blocks"][0]["from"] == 1 and e["blocks"][-1]["to"] == len(nc.text.rstrip("\n").split("\n"))


# ---------------------------------------------------------------- 第 4 步：挂到工艺规程、审批生效、下发
@pytest.fixture()
def camdb():
    import os
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0] + "/wq_cam_test"
    try:
        with psycopg.connect(dsn.rsplit("/", 1)[0] + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_cam_test with (force)")
            c.execute("create database wq_cam_test")
    except psycopg.OperationalError:
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    d = DB(dsn)
    d.init()
    return d


def test_programs_ride_on_process_approval(camdb, plan, shaft):
    import wqbus
    from hub import cam_api, plm, process
    from hub.mes import MES
    db = camdb
    out = []

    def emit(tp, type_, data):
        msg = wqbus.make(type_, "plm", data, mode="teach")            # 按总线规范校验
        db.insert_message(tp, msg)
        out.append(msg)

    design = cam.design_profile(shaft[0]["segments"], shaft[0]["chamfer"])
    spec = J.plan_turn(plan, 20, design, 1)
    spec["cut"]["vc"] = 130.0                                          # 编程时把切削速度从 120 改成 130
    progs = J.generate(spec)
    texts = [p.pop("gcode") for p in progs]
    for p in progs:
        p["sim"].pop("_H", None)
    job = {"id": "20261002-cam-test", "spec": spec, "programs": progs, "compare": spec["compare"]}
    newplan, note = cam_api.attach_to_plan(db, plm.store, "teach", job, texts)
    rough = next(o for o in newplan["operations"] if o["seq"] == 20)
    assert [p["number"] for p in rough["programs"]] == [1201, 1202] and rough["cut"]["vc_m_min"] == 130
    assert "vc_m_min 120 → 130" in note and "O1201、O1202" in note
    assert plm.load_file(db, rough["programs"][0]["url"]).decode("utf-8") == texts[0]
    s = process.submit(db, emit, "teach", "学生甲", "u1", newplan, note)
    assert s["status"] == "pending"
    assert cam_api.release_programs(db, emit, s) == 0                  # 没批准不下发
    for c in s["comments"]:
        process.resolve(db, s["id"], c["id"])
    a = process.approve(db, emit, s["id"], "老师", "同意", approver_uid="t1")
    assert cam_api.release_programs(db, emit, a) == 2
    g = [m["data"] for m in out if m["type"] == "design.gcode"]
    assert [x["program"] for x in g] == [1201, 1202] and g[0]["machine"] == "cnc-l01-a" and g[0]["process_revision"] == 1
    # MES 派工：粗车两个程序随工序发给机床；铣键槽没有程序
    sent = []
    mes = MES(db, lambda tp, t, src, data, corr, mode: sent.append(data))
    db.insert_message("wq/gearbox/office/erp/doc", wqbus.make("erp.doc", "bridge", {
        "doctype": "Work Order", "name": "MFG-WO-C1", "action": "submitted", "production_item": "SH-301", "qty": 5,
        "docstatus": 1, "status": "Not Started"}, mode="teach"))
    mes.release("MFG-WO-C1", "teach", "老师")
    d20 = next(d for d in sent if d["operation"].startswith("粗车"))
    assert d20["gcode_ref"] == g[0]["gcode_ref"] and d20["gcode_refs"] == [x["gcode_ref"] for x in g]
    assert next(d for d in sent if d["operation"].startswith("铣键槽"))["gcode_ref"] is None


# ---------------------------------------------------------------- 第 5 步：一句话编程、AI 讲解（规则兜底）
def test_one_sentence_rules(plan, shaft):
    from hub import cam_ai as A
    design = cam.design_profile(shaft[0]["segments"], shaft[0]["chamfer"])
    s = J.plan_turn(plan, 20, design, 1)
    r = A.setup(None, "粗车外圆，每刀 2.5，留 0.3 精车余量", s)
    assert r["engine"] == "rules" and not r["unmatched"]
    assert {(p["path"], p["value"]) for p in r["patch"]} == {("cut.ap", 2.5), ("cut.radial_allow", 0.3)}
    s["cut"]["radial_allow"] = 0.3                                  # 网页按修改清单写回后生成：粗车目标多留 0.3
    p = J.generate(s)[0]
    assert p["sim"]["dev_max"] <= 0.01 and abs(p["sim"]["target"][0][1] - (s["profile"][-1][1] + 0.6)) < 1e-6
    r = A.setup(None, "线速度 150，进给 0.12，限速 2500，只车右端，加点冷却", s)
    assert {(p["path"], str(p["value"])) for p in r["patch"]} == {("cut.vc", "150.0"), ("cut.f", "0.12"), ("cut.max_rpm", "2500.0"),
                                                                 ("setups", "['right']")}
    assert r["unmatched"] == ["加点冷却"]
    k = J.plan_slot(plan, 50, shaft[0], 1)
    r = A.setup(None, "铣键槽，分 5 层", k)
    assert r["patch"][0]["path"] == "cut.ap" and r["patch"][0]["value"] * 5 >= k["depth"] - 1e-9
    with pytest.raises(ValueError):
        A.setup(None, "  ", k)


def test_explain_covers_every_line(plan, shaft, plate_step):
    from hub import cam_ai as A
    design = cam.design_profile(shaft[0]["segments"], shaft[0]["chamfer"])
    f = CG.mill_features(plate_step)
    for spec in (J.plan_turn(plan, 20, design, 1), J.plan_turn(plan, 40, design, 1), J.plan_slot(plan, 50, shaft[0], 1),
                 J.plan_mill(f, "VMC-01", "6061", 2.0, "WQ-PLATE")):
        progs = J.generate(spec)
        nc = progs[0]["gcode"]
        e = A.explain(None, {"spec": spec, "programs": progs}, 0, nc)
        n = len(nc.rstrip("\n").split("\n"))
        got = [ln for b in e["blocks"] for ln in range(b["from"], b["to"] + 1)]
        assert got == list(range(1, n + 1)), spec["kind"]               # 每一行都讲到、不重复
        assert all(b["text"] for b in e["blocks"]) and e["risks"]
        kinds = " ".join(b["text"] for b in e["blocks"])
        assert "程序头" in kinds and ("M30" in kinds)


def test_cutting_power_check(plan, shaft):
    """与工艺规程同一张 Kienzle 表：45 钢 kc1.1 = 2220 MPa、mc = 0.14；ap 2.5、f 0.3、vc 120 → 约 3.94 kW"""
    design = cam.design_profile(shaft[0]["segments"], shaft[0]["chamfer"])
    s = J.plan_turn(plan, 20, design, 1)
    p = J.generate(s)[0]
    hand = 2220 * 2.5 * 0.3 ** 0.86 * 120 / 60000
    assert p["power"]["items"][0]["P_kw"] == pytest.approx(hand, rel=1e-3) and not p["checks"]
    from hub import process
    assert process.cutting_power_kw("45", {"ap_mm": 2.5, "f_mm_r": 0.3, "vc_m_min": 120})[0] == pytest.approx(hand, rel=1e-3)
    s["cut"].update(ap=6.0, f=0.5)                                    # 每刀 6、进给 0.5：超过 11 kW
    assert any("超过" in c["text"] and c["level"] == "error" for c in J.generate(s)[0]["checks"])


def test_lab10_documents():
    import io
    import docx
    from cae import labdoc
    g = docx.Document(io.BytesIO(labdoc.guide_docx("lab10")))
    text = "\n".join(p.text for p in g.paragraphs)
    assert "实验 10" in text and "公差带中间" in text and len(g.tables) >= 2
    t = docx.Document(io.BytesIO(labdoc.report_template_docx("lab10")))
    cells = " ".join(c.text for tb in t.tables for r in tb.rows for c in r.cells)
    assert "编程直径" in cells and "槽深" in cells and "P_c" in cells
