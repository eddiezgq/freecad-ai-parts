"""问渠CAM C2b 车铣复合插补换算（ADR-0106 C2b 第 1 步）：极坐标插补、圆柱插补，程序坐标 ↔ 工件坐标往返 < 1e-9。"""

from __future__ import annotations

import itertools
import math

import pytest

from analysis.cam import millturn as MT


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
