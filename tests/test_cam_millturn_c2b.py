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
