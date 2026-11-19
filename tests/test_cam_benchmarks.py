"""问渠CAM 验证手册的标准题（ADR-0104 第 6 节；C1）：每题在断言之外用 tests.verification.record 记下算出来的值、参考值和容差。

参考值都是解析解或手算公式；“必须报出来”的题用 record_verdict 记结论。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from analysis import cam
from analysis.cam import collide as CL
from analysis.cam import kinematics as K
from analysis.cam import machines, postproc, power, sim
from analysis.cam import paths as P
from tests.verification import record, record_verdict

LATHE = machines.get("EX-LATHE")
VMC = machines.get("EX-VMC")
AC = machines.model("EX-5AX-AC")


# ---------------- 时间与功率 ----------------

def test_turning_time_g97_and_g96():
    """一刀纵车 L = 100 mm、f = 0.2 mm/r、n = 1000 r/min：t = L/(f·n) = 30 s；G96 时 d = 40、vc = π·40 m/min 同样 1000 r/min"""
    hand = 100 / (0.2 * 1000) * 60
    for name, sp in (("G97", "G97 S1000 M03"), ("G96", f"G50 S3000\nG96 S{math.pi * 40:.9f} M03")):
        g = f"G21 G18 G99\nT0101\n{sp}\nG00 X40.0 Z2.0\nG01 Z0.0 F0.2\nZ-100.0\nG00 X50.0\nM30\n"
        p = sim.parse(g, LATHE)
        t = sum(sim.move_time(m, LATHE, True) for m in p["moves"] if m["t"] == "feed" and m["a"][2] == 0.0)
        record((f"纵车时间（{name}）", f"turning time ({name})"), t, hand, tol=1e-3, unit="s", formula="t = L/(f·n)")
        assert t == pytest.approx(hand, rel=1e-3)


def test_kienzle_turning_power():
    """P = kc1.1·ap·f^(1−mc)·vc/60000（κr = 90°，h = f）：C45E kc1.1 = 2220、mc = 0.14，ap 2、f 0.3、vc 120"""
    kc = 2220 * 0.3 ** -0.14
    hand = kc * 2.0 * 0.3 * 120 / 60000
    got = power.turning_kw(2220, 0.14, 2.0, 0.3, 120)
    record(("车削切削功率", "turning cutting power"), got, hand, tol=1e-9, unit="kW", formula="Fc = kc·ap·f; kc = kc1.1·h^−mc; P = Fc·vc")
    assert got == pytest.approx(hand, rel=1e-12)


def test_milling_feed_time():
    """直线铣削 120 mm，F = 600 mm/min：t = 12 s"""
    g = "G21 G17 G90 G94\nT1 M06\nS3000 M03\nG00 X0 Y0 Z5\nG01 Z-2 F600\nX120.\nG00 Z5\nM30\n"
    p = sim.parse(g, VMC)
    t = sum(sim.move_time(m, VMC, False) for m in p["moves"] if m["t"] == "feed" and m["a"][2] == -2.0)
    record(("铣削进给时间", "milling feed time"), t, 120 / 600 * 60, tol=1e-9, unit="s", formula="t = L/vf")
    assert t == pytest.approx(12.0)


def test_thread_time():
    """M24×1.5，每刀 29 mm，n = 796 r/min：每刀 t = 29/(1.5·796)·60"""
    g = cam.run({"mode": "turn", "machine": "EX-LATHE", "segments": [[40, 40], [24, 30]], "chamfer_mm": 1,
                 "grooves": [{"z": -27, "width": 3, "d": 20}],
                 "threads": [{"z_start": 0, "z_end": -26, "d": 24, "pitch": 1.5}]})["data"]["programs"][0]["gcode"]
    p = sim.parse(g, LATHE)
    sim.timing(p, LATHE)
    th = [m for m in p["moves"] if m["t"] == "thread"]
    hand = len(th) * 29 / (1.5 * 796) * 60
    got = sum(m["dt"] for m in th)
    record(("车螺纹时间", "threading time"), got, hand, tol=1e-6, unit="s", formula="t = N·L/(P·n)")
    assert got == pytest.approx(hand, rel=1e-6)


# ---------------- 运动学 ----------------

def _bc():
    return {"format": "cam-machine/1", "id": "T-BC", "name": "摆头 BC（虚构）", "source": "测试", "kind": "mill",
            "controller": {"family": "heidenhain"}, "spindle": {"max_rpm": 18000},
            "axes": [{"id": "X", "type": "linear", "carrier": "tool", "direction": [1, 0, 0], "min": -800, "max": 800},
                     {"id": "Y", "type": "linear", "carrier": "tool", "direction": [0, 1, 0], "min": -600, "max": 600},
                     {"id": "Z", "type": "linear", "carrier": "tool", "direction": [0, 0, 1], "min": -600, "max": 400},
                     {"id": "C", "type": "rotary", "carrier": "tool", "direction": [0, 0, 1], "point_mm": [0, 0, 0], "min": -360, "max": 360},
                     {"id": "B", "type": "rotary", "carrier": "tool", "direction": [0, 1, 0], "point_mm": [0, 0, 450], "min": -110, "max": 110}],
            "tool": {"direction": [0, 0, 1], "gauge_point_mm": [0, 0, 300]}}


def _ht():
    return {"format": "cam-machine/1", "id": "T-HT", "name": "摆头 B + 转台 C（虚构）", "source": "测试", "kind": "mill",
            "controller": {"family": "fanuc"}, "spindle": {"max_rpm": 12000},
            "axes": [{"id": "X", "type": "linear", "carrier": "tool", "direction": [1, 0, 0], "min": -800, "max": 800},
                     {"id": "Y", "type": "linear", "carrier": "workpiece", "direction": [0, -1, 0], "min": -600, "max": 600},
                     {"id": "Z", "type": "linear", "carrier": "tool", "direction": [0, 0, 1], "min": -600, "max": 400},
                     {"id": "B", "type": "rotary", "carrier": "tool", "direction": [0, 1, 0], "point_mm": [0, 0, 380], "min": -95, "max": 95},
                     {"id": "C", "type": "rotary", "carrier": "workpiece", "direction": [0, 0, 1], "point_mm": [20, -10, 0], "continuous": True}],
            "tool": {"direction": [0, 0, 1], "gauge_point_mm": [0, 0, 250]}}


@pytest.mark.parametrize("name", ["cradle-AC", "head-BC", "head-table"])
def test_inverse_round_trip(name):
    """随机 500 个位姿：正解 → 逆解 → 正解，刀尖最大误差（参考值 0，容差 1e-9 mm）"""
    m = {"cradle-AC": AC, "head-BC": _bc(), "head-table": _ht()}[name]
    rng = np.random.default_rng(104)
    worst = 0.0
    for _ in range(500):
        q = {}
        for a in m["axes"]:
            if a.get("continuous"):
                q[a["id"]] = float(rng.uniform(-170, 170))
            else:
                lo, hi = float(a["min"]), float(a["max"])
                q[a["id"]] = float(rng.uniform(lo + 0.05 * (hi - lo), hi - 0.05 * (hi - lo)))
        tip, d = K.forward(m, q, 80.0)
        back = K.inverse(m, tip, d, 80.0, prefer=q)
        t2, d2 = K.forward(m, back, 80.0)
        worst = max(worst, float(np.linalg.norm(t2 - tip)), float(np.linalg.norm(d2 - d)) * 100)
    label = {"cradle-AC": "摇篮 AC", "head-BC": "摆头 BC", "head-table": "摆头 B + 转台 C"}[name]
    record((f"逆解往返刀尖误差（{label}）", f"inverse round-trip tip error ({name})"), worst, 0.0, tol=1e-9, rel=False, unit="mm",
           formula="FK(IK(p, v)) = (p, v)")
    assert worst < 1e-9


def test_forward_kinematics_by_hand():
    """摇篮 AC，A = −90°：竖直刀轴在工件坐标里是 rot(X, 90°)·Z = −Y；A 轴过 z = −100，机床 (0,0,50) 的刀尖 → 工件 (0, −150, −100)"""
    tip, d = K.forward(AC, {"A": -90, "Z": -350}, 0.0)
    err = float(np.linalg.norm(tip - [0, -150, -100]) + np.linalg.norm(d - [0, -1, 0]))
    record(("正解与手算之差", "forward kinematics vs hand calculation"), err, 0.0, tol=1e-12, rel=False, unit="mm",
           formula="p' = R(p − c) + c")
    assert err < 1e-12


# ---------------- 碰撞判断 ----------------

def test_gjk_vs_separating_axis():
    """随机 5000 对斜放长方体，GJK 与分离轴定理（精确判据）结论不一致的对数（参考值 0）"""
    rng = np.random.default_rng(1104)
    bad = 0
    for _ in range(5000):
        a = CL.Box(rng.uniform(-2, 2, 3), K.rot(rng.normal(size=3), rng.uniform(0, 360)), rng.uniform(0.2, 1, 3))
        b = CL.Box(rng.uniform(-2, 2, 3), K.rot(rng.normal(size=3), rng.uniform(0, 360)), rng.uniform(0.2, 1, 3))
        axes = [a.R[:, i] for i in range(3)] + [b.R[:, i] for i in range(3)] + \
            [np.cross(a.R[:, i], b.R[:, j]) for i in range(3) for j in range(3)]
        sep = False
        for L in axes:
            n = np.linalg.norm(L)
            if n > 1e-9 and abs((b.c - a.c) @ (L / n)) > np.abs(a.R.T @ (L / n)) @ a.h + np.abs(b.R.T @ (L / n)) @ b.h:
                sep = True
                break
        bad += CL.hit(a, b) == sep
    record(("GJK 与分离轴定理不一致的对数", "GJK vs separating-axis disagreements"), bad, 0, tol=0, rel=False, unit="",
           formula="SAT, 15 axes")
    assert bad == 0


# ---------------- 材料去除与几何 ----------------

def test_pocket_removed_volume():
    """矩形型腔 60×30、转角 R6、深 8：V = (60·30 − (4 − π)·6²)·8"""
    r = cam.run({"mode": "mill", "machine": "EX-VMC", "stock": {"box": [0, 0, 100, 60]},
                 "features": [{"type": "pocket", "rect": [20, 15, 80, 45], "corner_r": 6, "depth": 8, "tool_d": 10}]})
    g = r["data"]["programs"][0]["gcode"]
    s = sim.simulate_mill(sim.parse(g, VMC), {"box": [0, 0, 100, 60], "top": 0.0}, {1: {"kind": "endmill", "d": 10.0}})
    vol = float(np.sum(np.where(s["inside"], 0.0 - s["H"], 0.0)) * s["h"] ** 2)
    hand = (60 * 30 - (4 - math.pi) * 36) * 8
    record(("型腔去除体积", "pocket removed volume"), vol, hand, tol=1e-3, unit="mm³", formula="V = (ab − (4 − π)r²)·h")
    assert vol == pytest.approx(hand, rel=1e-3)


def test_turned_volume_matches_design():
    """阶梯轴车完（右端一次装夹）：仿真得到的体积与设计轮廓 π∫r²dz 相比"""
    r = cam.run({"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60], [35, 25], [24, 30]], "chamfer_mm": 1})
    p0 = r["data"]["programs"][0]
    tgt = p0["target"]
    s = sim.simulate_turn(sim.parse(p0["gcode"], LATHE), {"d": 44.0, "z_right": 1.0, "z_left": -156.0},
                          {1: {"kind": "turn"}, 2: {"kind": "turn"}})
    zmin = min(z for z, _ in tgt)
    sel = (s["z"] <= 0) & (s["z"] >= zmin)
    h = s["z"][1] - s["z"][0]
    vol = float(np.pi * np.sum(s["r"][sel] ** 2) * h)
    zz = np.linspace(zmin, 0, 200001)
    rr = np.array([P.d_at(tgt, z) / 2 for z in zz])
    hand = float(np.pi * np.trapezoid(rr ** 2, zz))
    record(("车削后体积", "turned volume"), vol, hand, tol=1e-3, unit="mm³", formula="V = π∫r²dz")
    assert vol == pytest.approx(hand, rel=1e-3)


def test_thread_root_and_bore_diameters():
    """M24×1.5 牙底 d3 = 24 − 1.22687·1.5（ISO 965-1）；内孔 Ø16、Ø12"""
    r = cam.run({"mode": "turn", "machine": "EX-LATHE", "segments": [[40, 60], [24, 30]], "chamfer_mm": 1,
                 "grooves": [{"z": -27, "width": 3, "d": 20}], "threads": [{"z_start": 0, "z_end": -26, "d": 24, "pitch": 1.5}],
                 "bore": {"segments": [[16, 20], [12, 15]], "drill_d": 10}})
    g = r["data"]["programs"][0]["gcode"]
    s = sim.simulate_turn(sim.parse(g, LATHE), {"d": 44.0, "z_right": 1.0, "z_left": -92.0},
                          {1: {"kind": "turn"}, 2: {"kind": "turn"}, 3: {"kind": "groove", "w": 3.0}, 4: {"kind": "thread"},
                           5: {"kind": "drill", "d": 10.0}, 6: {"kind": "bore"}})

    def at(arr, z):
        return float(arr[int(np.argmin(np.abs(s["z"] - z)))])
    d3 = 24 - 1.22687 * 1.5
    record(("螺纹牙底直径", "thread root diameter"), 2 * at(s["r"], -10), d3, tol=0.02, rel=False, unit="mm", formula="ISO 965-1: d3 = d − 1.22687P")
    record(("内孔直径 Ø16", "bore diameter Ø16"), 2 * at(s["ri"], -10), 16.0, tol=0.02, rel=False, unit="mm", formula="d = 16")
    record(("内孔直径 Ø12", "bore diameter Ø12"), 2 * at(s["ri"], -27), 12.0, tol=0.02, rel=False, unit="mm", formula="d = 12")
    assert 2 * at(s["r"], -10) == pytest.approx(d3, abs=0.02)
    assert 2 * at(s["ri"], -10) == pytest.approx(16.0, abs=0.02) and 2 * at(s["ri"], -27) == pytest.approx(12.0, abs=0.02)


# ---------------- 必须报出来的 ----------------

OK = {"work_offset_mm": [0, 0, 40], "tools": {"1": {"tool": "EM10", "length_mm": 120}}}
MILL = {"mode": "mill", "machine": "EX-VMC", "stock": {"box": [0, 0, 100, 60], "height": 40},
        "features": [{"type": "pocket", "rect": [20, 15, 80, 45], "corner_r": 6, "depth": 8, "tool_d": 10}]}


def _verdict(setup, frag):
    p = cam.run(setup)["data"]["programs"][0]
    hit = any(frag in c["text"] for c in p["checks"] if c["level"] == "error")
    return "fail" if hit else "pass", p


def test_known_collisions_are_reported():
    v, p = _verdict({**MILL, "machine_sim": {**OK, "fixtures": [{"id": "c", "name": "压板", "box_mm": [25, 10, 0, 35, 25, 12]}]}},
                    "压板")
    record_verdict(("刀具碰压板必须报出且不出程序", "cutter into clamp is reported and program withheld"),
                   "fail" if v == "fail" and p["gcode"] is None else "pass", "fail")
    v2, _ = _verdict({**MILL, "machine_sim": {**OK, "work_offset_mm": [0, 0, 5]}}, "工作台")
    record_verdict(("刀具切进工作台必须报出", "cutter into the table is reported"), v2, "fail")
    deep = {**MILL, "features": [dict(MILL["features"][0], depth=38)]}
    v3, _ = _verdict({**deep, "machine_sim": OK}, "刀柄碰到工件")
    record_verdict(("深型腔刀柄碰侧壁必须报出", "holder hitting the pocket wall is reported"), v3, "fail")
    v4, _ = _verdict({**MILL, "machine_sim": {**OK, "work_offset_mm": [0, 0, 0], "tools": {"1": {"tool": "EM10", "length_mm": 50}}}},
                     "超程")
    record_verdict(("刀太短 Z 轴超程必须报出", "Z overtravel with a short tool is reported"), v4, "fail")
    assert v == v2 == v3 == v4 == "fail"


def test_known_overcut_and_rapid_into_stock_are_reported():
    g = "%\nO1\nG21 G17 G90 G94\nT1 M06\nS3000 M03\nG00 X50 Y30 Z5\nG01 Z-9 F200\nG00 Z5\nX10 Y10\nZ-2.\nM30\n%\n"
    p = sim.parse(g, VMC)
    s = sim.simulate_mill(p, {"box": [0, 0, 100, 60], "top": 0.0}, {1: {"kind": "endmill", "d": 10.0}},
                          target=lambda X, Y: np.where((X - 50) ** 2 + (Y - 30) ** 2 <= 36, -8.0, 0.0))
    over = any("过切" in i["text"] for i in s["issues"])
    rapid = any("快移撞到工件" in i["text"] for i in s["issues"])
    record_verdict(("比目标深 1 mm 必须报过切", "1 mm too deep is reported as overcut"), "fail" if over else "pass", "fail")
    record_verdict(("快移进材料必须报出", "rapid into stock is reported"), "fail" if rapid else "pass", "fail")
    assert over and rapid


# ---------------- 后处理 ----------------

@pytest.mark.parametrize("ctl", ["fanuc", "siemens", "gsk"])
def test_post_reproduces_simulated_path(ctl):
    """正式程序回读后，与整机仿真用的刀路逐段比：最大坐标差（参考值 0，容差 1e-3 mm）"""
    setup = {"mode": "turn", "machine": "EX-LATHE", "segments": [[40, 60], [24, 30]], "chamfer_mm": 1,
             "grooves": [{"z": -27, "width": 3, "d": 20}], "threads": [{"z_start": 0, "z_end": -26, "d": 24, "pitch": 1.5}],
             "bore": {"segments": [[16, 20], [12, 15]], "drill_d": 10},
             "machine_sim": {"tools": {str(i): {"tool": "TR-CNMG"} for i in range(1, 7)}}, "post": ctl}
    p = cam.run(setup)["data"]["programs"][0]
    a = [m for m in sim.parse(p["gcode"], LATHE)["moves"] if not m.get("home")]
    b = [m for m in sim.parse(postproc.to_fanuc(p["release"]["text"], ctl, True), LATHE)["moves"] if not m.get("home")]
    assert len(a) == len(b)
    worst = max(max(abs(u - v) for u, v in zip(x["b"], y["b"], strict=True)) for x, y in zip(a, b, strict=True))
    record((f"后处理回读刀路差（{ctl}）", f"post read-back path difference ({ctl})"), worst, 0.0, tol=1e-3, rel=False, unit="mm",
           formula="max |Δ| of end points")
    assert worst <= 1e-3
