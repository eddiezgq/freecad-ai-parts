"""问渠CAM C2b 车铣复合插补换算（ADR-0106 C2b 第 1 步）：极坐标插补、圆柱插补，程序坐标 ↔ 工件坐标往返 < 1e-9。"""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import pytest

from analysis.cam import machine_model as MM
from analysis.cam import millturn as MT
from analysis.cam import sim
from tests.verification import record_verdict


def test_polar_round_trip_and_machine_radius():
    worst = 0.0
    for x, c, z in itertools.product([-40.0, -3.0, 0.0, 12.5, 60.0], [-25.0, 0.0, 7.5, 30.0], [-10.0, 0.0, 2.5]):
        back = MT.work_to_polar(*MT.polar_to_work(x, c, z))
        worst = max(worst, *(abs(u - v) for u, v in zip(back, (x, c, z), strict=True)))
    assert worst < 1e-9
    d, ang = MT.polar_machine(30.0, 15.0)                  # 虚拟平面 (15, 15)：半径 15√2，极角 45°
    assert d == pytest.approx(30 * math.sqrt(2)) and ang == pytest.approx(45.0)


def test_cylindrical_round_trip_and_arc_length():
    worst = 0.0
    for x, c, z in itertools.product([20.0, 40.0, 80.0], [-179.0, -30.0, 0.0, 45.0, 170.0], [-50.0, 0.0]):
        back = MT.work_to_cyl(*MT.cyl_to_work(x, c, z))
        worst = max(worst, *(abs(u - v) for u, v in zip(back, (x, c, z), strict=True)))
    assert worst < 1e-9
    assert MT.arc_length(90.0, 20.0) == pytest.approx(10 * math.pi)


def test_cylindrical_segment_is_split_and_stays_on_cylinder():
    pts = MT.cyl_segment((40.0, 0.0, 0.0), (40.0, 90.0, -30.0))   # Ø40 圆柱上转 90°、同时走 30 mm：螺旋线
    assert len(pts) == 45
    assert all(math.hypot(p[0], p[1]) == pytest.approx(20.0) for p in pts)
    assert pts[-1] == pytest.approx((0.0, 20.0, -30.0), abs=1e-12)


# ---------------------------------------------------------------- 第 2 步：仿真读车铣程序
MT_MACH = MM.legacy_view(json.loads((Path(MM.__file__).parent / "machines" / "EX-MT-CY.json").read_text(encoding="utf-8")))

PROG = """%
O0001
G21 G18 G40 G97 G99
T0101
G97 S1000 M03
G00 X60.0 Z2.0
G01 X50.0 F0.2
G01 Z-40.0
G00 X60.0
G98
T0505
G12.1
G00 X20.0 C-10.0 Z2.0
G01 Z-3.0 F100.0
G01 C10.0 F200.0
G00 Z2.0
G13.1
G07.1 C25.0
G00 X60.0 C0.0 Z-10.0
G01 X44.0 F100.0
G01 C90.0 Z-30.0 F300.0
G00 X60.0
G07.1 C0
M30
%"""


def test_parse_polar_and_cylindrical_moves():
    p = sim.parse(PROG, MT_MACH)
    mills = [mv for mv in p["moves"] if mv.get("mill")]
    assert {mv["mill"] for mv in mills} == {"polar", "cyl"}
    face = [mv for mv in mills if mv["mill"] == "polar" and mv["t"] == "feed"]
    slot = face[1]                                       # 端面槽：工件坐标 (10, −10, −3) → (10, 10, −3)，刀轴沿 +Z
    (p0, p1, w), = slot["pieces"]
    assert p0 == pytest.approx((10.0, -10.0, -3.0)) and p1 == pytest.approx((10.0, 10.0, -3.0)) and w == (0.0, 0.0, 1.0)
    cyl = [mv for mv in mills if mv["mill"] == "cyl" and mv["t"] == "feed"][-1]   # Ø44 圆柱面上 0° → 90°、Z −10 → −30
    assert len(cyl["pieces"]) == 45 and all(math.hypot(q[0], q[1]) == pytest.approx(22.0) for _a, q, _w in cyl["pieces"])
    assert cyl["pieces"][-1][1] == pytest.approx((0.0, 22.0, -30.0), abs=1e-9)
    assert cyl["pieces"][-1][2] == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)          # 刀轴沿径向
    # 车削段照常（Ø50 外圆）
    turn = [mv for mv in p["moves"] if not mv.get("mill") and mv["t"] == "feed"]
    assert turn[0]["b"] == pytest.approx((50.0, 0.0, 2.0)) and turn[1]["b"] == pytest.approx((50.0, 0.0, -40.0))


def test_millturn_cutting_time():
    """端面槽 20 mm @ F200、下刀 5 mm @ F100；圆柱面螺旋线长 √((22·π/2)² + 20²) @ F300（弦长，2° 一段）"""
    p = sim.parse(PROG, MT_MACH)
    sim.timing(p, MT_MACH)
    mills = [mv for mv in p["moves"] if mv.get("mill") and mv["t"] == "feed"]
    assert mills[0]["dt"] == pytest.approx(60 * 5 / 100) and mills[1]["dt"] == pytest.approx(60 * 20 / 200)
    helix = math.hypot(22 * math.pi / 2, 20)
    assert mills[-1]["dt"] == pytest.approx(60 * helix / 300, rel=2e-4)
    record_verdict(("车铣：端面槽、圆柱面螺旋槽的切削时间", "mill-turn: face slot and cylindrical helix cutting time"), "pass", "pass")


# ---------------------------------------------------------------- 第 3 步：车完的外形上铣
def _axial_slot_volume(R=25.0, depth=3.0, w=3.0, L=20.0, n=4000):
    """径向立铣刀（半径 w）在 Ø2R 圆柱上铣轴向槽，刀底到轴线 R − depth：∫∫ (√(R² − y²) − (R − depth)) dy dz（数值积分）"""
    import numpy as np

    ys = np.linspace(-w, w, n)
    hgt = np.clip(np.sqrt(R * R - ys * ys) - (R - depth), 0, None)
    dy = ys[1] - ys[0]
    rect = float(hgt.sum() * dy * L)
    ends = float(sum(hgt[i] * 2 * math.sqrt(max(w * w - y * y, 0.0)) for i, y in enumerate(ys)) * dy)   # 两头半圆合起来一个整圆
    return rect + ends


def test_face_slot_and_cylinder_slot_volume_on_turned_part():
    """Ø50 × 40 车完的轴：端面槽（Ø6 平底刀，深 3、长 20）= 3·(20·6 + π·3²)；圆柱面轴向槽（Ø6 径向刀，Ø50 → Ø44、长 20）按截面积分"""
    prog = """%
O0001
G21 G18 G98
T0505
G97 S2000 M03
G12.1
G00 X20.0 C-10.0 Z2.0
G01 Z-3.0 F100.0
G01 C10.0 F200.0
G00 Z2.0
G13.1
M30
%"""
    p = sim.parse(prog, MT_MACH)
    r = MT.mill_on_turned(p, [(0.0, 25.0), (-40.0, 25.0)], {5: {"kind": "endmill", "d": 6.0}})
    assert r["removed_mm3"] == pytest.approx(3 * (20 * 6 + math.pi * 9), rel=0.01) and not r["issues"]
    prog2 = """%
O0002
G21 G18 G98
T0606
G97 S2000 M03
G07.1 C25.0
G00 X60.0 C0.0 Z-10.0
G01 X44.0 F100.0
G01 Z-30.0 F200.0
G00 X60.0
G07.1 C0
M30
%"""
    p2 = sim.parse(prog2, MT_MACH)
    r2 = MT.mill_on_turned(p2, [(0.0, 25.0), (-40.0, 25.0)], {6: {"kind": "endmill", "d": 6.0}})
    assert r2["removed_mm3"] == pytest.approx(_axial_slot_volume(), rel=0.02) and not r2["issues"]
    record_verdict(("车铣：端面槽、圆柱面槽的去除体积", "mill-turn: face slot and cylinder slot removed volume"), "pass", "pass")


# ---------------------------------------------------------------- 第 4 步：车铣程序进计算、后处理（ADR-0110）
from analysis import cam


def _mt_prog():
    turn = [{"t": "rapid", "x": 60, "z": 2}, {"t": "rapid", "x": 50, "z": 2}, {"t": "feed", "x": 50, "z": -40, "f": 0.2},
            {"t": "rapid", "x": 60, "z": -40}, {"t": "rapid", "x": 60, "z": 2}]
    face = [{"t": "rapid", "x": 20, "c": -10, "z": 2}, {"t": "feed", "x": 20, "c": -10, "z": -3, "f": 100},
            {"t": "feed", "x": 20, "c": 10, "z": -3, "f": 200}, {"t": "rapid", "x": 20, "c": 10, "z": 2}]
    cyl = [{"t": "rapid", "x": 60, "c": 0, "z": -10}, {"t": "feed", "x": 44, "c": 0, "z": -10, "f": 100},
           {"t": "feed", "x": 44, "c": 0, "z": -30, "f": 200}, {"t": "rapid", "x": 60, "c": 0, "z": -30}]
    return {"number": 3001, "title": "车铣", "ops": [
        {"tool": {"n": 1, "kind": "turn"}, "spindle": {"rpm": 1000}, "title": "车外圆", "moves": turn},
        {"tool": {"n": 5, "d": 6.0}, "spindle": {"rpm": 2000}, "title": "端面槽", "interp": "polar", "moves": face},
        {"tool": {"n": 6, "d": 6.0}, "spindle": {"rpm": 2000}, "title": "圆柱面槽", "interp": {"cyl": 25.0}, "moves": cyl}]}


def _run_mt(post):
    r = cam.run({"mode": "millturn", "machine": "EX-MT-CY", "program": _mt_prog(), "stock": {"d": 52, "z_right": 0.5, "z_left": -60},
                 "post": post, "machine_sim": {"tools": {}}})
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"][0]


def test_millturn_program_release_with_post_config(tmp_path, monkeypatch):
    """后处理配置写了动力刀、C 轴的 M 代码：正式程序按它写（G98、M18 C 轴、M13 动力刀、S、G12.1 … G13.1、G7.1 C25 … G7.1 C0），
    回读与仿真刀路一致才出；车完 Ø50 后铣掉的体积 = 端面槽 + 圆柱面槽"""
    import json as _json

    d = tmp_path / "posts"
    d.mkdir()
    (d / "mt.json").write_text(_json.dumps({"format": "cam-post/1", "id": "mt", "name": "FANUC mill-turn", "family": "fanuc", "kinds": ["lathe"],
                                            "source": "测试", "millturn": {"live_on": ["M13"], "live_off": ["M15"], "c_on": ["M18"],
                                                                         "c_off": ["M19"]}}), encoding="utf-8")
    monkeypatch.setenv("FAP_POSTS", str(d))
    p = _run_mt("mt")
    assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
    t = p["release"]["text"]
    for frag in ("G98\nM05\nM18\nM13\nS2000\nG12.1", "G13.1\nM15\nM19\nG99", "G07.1 C25.0", "G07.1 C0"):
        assert frag in t, frag
    exact = 3.5 * (20 * 6 + math.pi * 9) + _axial_slot_volume()       # 毛坯端面在 Z0.5（没车端面），端面槽深 3.5
    assert p["sim"]["mill_removed_mm3"] == pytest.approx(exact, rel=0.02)
    assert any("C 轴、动力刀的整机仿真还没做" in c["text"] for c in p["checks"])


def test_millturn_without_post_config_is_withheld():
    """内置 FANUC 配置没写车铣 M 代码：带铣削段的车铣程序不出，写明原因（不猜 M 代码）"""
    p = _run_mt("fanuc")
    assert p["release"] is None and any("millturn" in c["text"] and c["level"] == "error" for c in p["checks"])


# ---------------------------------------------------------------- 第 5 步：动力刀的整机仿真（ADR-0106 C2b）
def test_live_tool_inverse_matches_hand_values():
    """轴向动力刀在 (10, −10, −3)、刀长 40：C 转 45° 把点转到 +X，X = 2·√200 = 28.284（直径值），Y = 0，Z = −3 + 40；
    径向动力刀在 (0, 22, −10)、刀轴 +Y：C = −90°，X = 2·(22 + 40) = 124"""
    from analysis.cam import kinematics as K
    from analysis.cam import machines

    m = machines.get("EX-MT-CY")["model"]
    q = K.inverse({**m, "tool": m["live_tools"]["axial"]}, [10, -10, -3], (0, 0, 1), 40, prefer={"C": 45})
    assert (q["C"], q["X"], q["Y"], q["Z"]) == pytest.approx((45.0, 2 * math.sqrt(200), 0.0, 37.0), abs=1e-9)
    q = K.inverse({**m, "tool": m["live_tools"]["radial"]}, [0, 22, -10], (0, 1, 0), 40)
    assert (q["C"], q["X"], q["Y"], q["Z"]) == pytest.approx((-90.0, 124.0, 0.0, -10.0), abs=1e-9)


def _run_live(ms):
    r = cam.run({"mode": "millturn", "machine": "EX-MT-CY", "program": _mt_prog(), "stock": {"d": 52, "z_right": 0.5, "z_left": -60},
                 "post": "fanuc", "machine_sim": ms})
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"][0]


def test_live_tool_machine_sim_checks_milling_moves():
    """机床文件写了 live_tools：铣削段按动力刀朝向逆解、查碰撞，不再报“还没做”；
    工件零点放在卡盘端面（work_offset 0）时，端面槽下到 Z−3 就是刀伸进卡盘，要报错"""
    tools = {"1": {"tool": "TR-CNMG"}, "5": {"tool": "EM6", "length_mm": 40}, "6": {"tool": "EM6", "length_mm": 40}}
    p = _run_live({"work_offset_mm": [0, 0, 70], "tools": tools})
    texts = [c["text"] for c in p["checks"]]
    assert not any("还没做" in t for t in texts) and not any("碰到" in t or "走不到" in t for t in texts), texts
    assert p["machine_sim"]["samples"] > 200
    bad = _run_live({"work_offset_mm": [0, 0, 0], "tools": {k: tools[k] for k in ("5", "6")}})
    hit = [c for c in bad["checks"] if c["level"] == "error" and "T5" in c["text"] and "卡盘" in c["text"]]
    assert hit and hit[0]["line"] == 27, [c["text"] for c in bad["checks"]]


# ---------------------------------------------------------------- 西门子 TRANSMIT / TRACYL（ADR-0106 C2b）
def test_siemens_transmit_tracyl_release(tmp_path, monkeypatch):
    """西门子后处理：端面 TRANSMIT（DIAMOF 半径：X = 20/2、Y = C）、圆柱面 TRACYL(50)（Y = 30°·π·50/360 = 13.09 mm 弧长），
    TRAFOOF、DIAMON 收尾；回读换回 G12.1 / G7.1 与仿真程序一致才出"""
    import json as _json

    d = tmp_path / "posts"
    d.mkdir()
    (d / "smt.json").write_text(_json.dumps({"format": "cam-post/1", "id": "smt", "name": "SINUMERIK mill-turn", "family": "siemens",
                                             "kinds": ["lathe"], "source": "测试", "millturn": {"live_on": ["SETMS(2)", "M3"],
                                                                                              "live_off": ["M5", "SETMS"],
                                                                                              "c_on": ["SPOS[1]=0"], "c_off": ["M15"]}}),
                                encoding="utf-8")
    monkeypatch.setenv("FAP_POSTS", str(d))
    prog = _mt_prog()
    prog["ops"][2]["moves"].insert(3, {"t": "feed", "x": 44, "c": 30, "z": -30, "f": 200})
    r = cam.run({"mode": "millturn", "machine": "EX-MT-CY", "program": prog, "stock": {"d": 52, "z_right": 0.5, "z_left": -60},
                 "post": "smt", "machine_sim": {"tools": {}}})
    p = r["data"]["programs"][0]
    assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
    t = p["release"]["text"]
    y = 30 * math.pi * 50 / 360
    for frag in ("G94\nDIAMOF\nTRANSMIT\nG17\nG0 X10.0 Y-10.0 Z2.0", "Y10.0 F200.0", "TRACYL(50.0)\nG19\nG0 X30.0 Y0.0 Z-10.0",
                 f"Y{y:.3f}".rstrip("0"), "SPOS[1]=0\nSETMS(2)\nM3\nS2000", "TRAFOOF\nDIAMON\nG18\nM5\nSETMS\nM15\nG95"):
        assert frag in t, frag
    assert "G12.1" not in t and "G07.1" not in t


def test_fanuc_millturn_lines_reject_brackets():
    """ADR-0111：括号只给西门子用；FANUC 系的车铣程序行带括号（FANUC 里是注释）报错"""
    from analysis.cam import postcfg

    cfg = {"format": "cam-post/1", "id": "f", "name": "F", "family": "fanuc", "kinds": ["lathe"], "source": "测试",
           "millturn": {"live_on": ["M13 (LIVE)"]}}
    with pytest.raises(postcfg.PostConfigError, match="ADR-0111"):
        postcfg.check(cfg, "f.json")
    postcfg.check({**cfg, "family": "siemens", "millturn": {"live_on": ["SETMS(2)"]}}, "s.json")


# ---------------------------------------------------------------- 车铣作业（ADR-0106 C2b 界面）：动力刀工序接在车削后面
def _keyway_volume(r=25.0, r_bot=22.0, w=6.0, L=20.0, n=4000):
    """平底键槽（宽 w、两端圆心距 L，底面离轴 r_bot）从 R r 的圆柱上去掉的体积：中点法积分 ∫(√(r² − x²) − r_bot)·长度(x) dx"""
    h = w / n
    s = 0.0
    for i in range(n):
        x = -w / 2 + (i + 0.5) * h
        s += (math.sqrt(r * r - x * x) - r_bot) * (L + 2 * math.sqrt(w * w / 4 - x * x)) * h
    return s


def test_classify_end_face_feature():
    st = MT.classify_face((20 - 6) * 6 + math.pi * 9, -10, -3, 10, 3)       # 长圆：包围盒 20×6
    assert st == {"type": "slot", "a": [-7.0, 0.0], "b": [7.0, 0.0], "width": 6}
    pk = MT.classify_face(30 * 20 - (4 - math.pi) * 16, 0, 0, 30, 20)       # R4 圆角矩形
    assert pk["type"] == "pocket" and pk["corner_r"] == pytest.approx(4.0)
    assert MT.classify_face(30 * 20 * 0.5, 0, 0, 30, 20) is None              # L 形之类：面积对不上


def test_turn_job_with_live_ops_removes_slot_and_keyway():
    """车削作业（车铣中心）：右端车完 Ø50 后接端面长圆槽（宽 6、圆心距 20、深 3）与 90° 方向的键槽（宽 6、深 3、z −10 ~ −30）；
    铣掉的体积 = 3·(20·6 + π·3²) + 键槽积分（< 1%）；动力刀整机仿真无碰撞、无超程"""
    face = MT.face_moves({"type": "slot", "a": [-10, 0], "b": [10, 0], "width": 6, "depth": 3, "z0": 0.0}, 6, 3, 200, 100)
    key = MT.keyway_moves(90.0, 25.0, 3.0, -10.0, -30.0, 6, 3, 200, 100)
    assert key[2] == {"t": "feed", "x": 44.0, "c": 90.0, "z": -10.0, "f": 100}
    live = {"right": [{"tool": {"n": 10, "d": 6.0}, "spindle": {"rpm": 3000}, "title": "端面槽", "interp": "polar", "moves": face},
                      {"tool": {"n": 10, "d": 6.0}, "spindle": {"rpm": 3000}, "title": "键槽", "interp": {"cyl": 25.0}, "moves": key}]}
    r = cam.run({"mode": "turn", "machine": "EX-MT-CY", "segments": [[40, 30], [50, 40]], "live_ops": live,
                 "machine_sim": {"tools": {"10": {"tool": "EM6", "length_mm": 40}}, "chuck": {"jaw_len": 15, "jaw_d": 80}}})
    assert r["status"] == "ok", r["messages"]
    right, left = r["data"]["programs"]
    exact = 3 * (20 * 6 + math.pi * 9) + _keyway_volume()
    assert right["sim"]["mill_removed_mm3"] == pytest.approx(exact, rel=0.01)
    texts = [c["text"] for c in right["checks"]]
    assert not any("碰到" in t or "走不到" in t or "还没做" in t for t in texts), texts
    assert "G12.1" in right["gcode"] and "G07.1 C25.0" in right["gcode"] and "G12.1" not in left["gcode"]
    bad = cam.run({"mode": "turn", "machine": "EX-LATHE", "segments": [[40, 30], [50, 40]], "live_ops": live})
    assert bad["status"] == "failed" and "不是车铣中心" in bad["messages"][0]
