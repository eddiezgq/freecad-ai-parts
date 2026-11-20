"""问渠CAM C2a 倾斜工作平面（ADR-0106 C2a）：工作平面 ↔ 旋转矩阵 ↔ G68.2 欧拉角 / PLANE SPATIAL / CYCLE800 逐轴角，往返误差 < 1e-9。"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from analysis.cam import tilt as TT
from tests.verification import record_verdict

ANGLES = [-170.0, -90.0, -45.0, -12.5, 0.0, 30.0, 90.0, 135.0, 180.0]


@pytest.mark.parametrize(("dec", "rec"), [(TT.euler_zxz, TT.from_zxz), (TT.spatial_abc, TT.from_spatial), (TT.axis_xyz, TT.from_axis_xyz)])
def test_round_trip(dec, rec):
    worst = 0.0
    for a, b, c in itertools.product(ANGLES, repeat=3):
        R = rec(a, b, c)
        R2 = rec(*dec(R))
        worst = max(worst, float(np.abs(R - R2).max()))
        assert np.allclose(R.T @ R, np.eye(3), atol=1e-12)
    assert worst < 1e-9
    record_verdict((f"倾斜面角度往返（{dec.__name__}）", f"tilted plane angle round trip ({dec.__name__})"), "pass", "pass")


def test_known_angles():
    """45° 斜面（绕 X 转 45°，法向朝 −Y 上方）：G68.2 I0 J45 K0；PLANE SPATIAL SPA45；CYCLE800 A45"""
    fr = {"origin": [10, 0, 0], "x": [1, 0, 0], "z": [0, -np.sqrt(0.5), np.sqrt(0.5)]}
    R = TT.matrix(fr)
    assert TT.euler_zxz(R) == pytest.approx((0.0, 45.0, 0.0))
    assert TT.spatial_abc(R) == pytest.approx((45.0, 0.0, 0.0))
    assert TT.axis_xyz(R) == pytest.approx((45.0, 0.0, 0.0))
    # 平面坐标 (0, 10, 0) 在工件里：沿斜面向上 10 mm
    assert TT.to_work(fr, [0, 10, 0]) == pytest.approx([10, 10 * np.sqrt(0.5), 10 * np.sqrt(0.5)])
    assert TT.to_plane(fr, TT.to_work(fr, [3, 4, 5])) == pytest.approx([3, 4, 5])
    # 绕 Y 转 90°（侧面，法向 +X）：G68.2 I90 J90 K-90 这一组与 PLANE SPATIAL SPB90 是同一个平面
    fr2 = {"origin": [0, 0, 0], "z": [1, 0, 0], "x": [0, 0, -1]}
    R2 = TT.matrix(fr2)
    assert np.allclose(TT.from_zxz(*TT.euler_zxz(R2)), R2) and TT.spatial_abc(R2) == pytest.approx((0.0, 90.0, 0.0))


def test_bad_frames():
    with pytest.raises(TT.TiltError):
        TT.matrix({"origin": [0, 0, 0], "z": [0, 0, 0]})
    with pytest.raises(TT.TiltError):
        TT.matrix({"origin": [0, 0, 0], "z": [0, 0, 1], "x": [0, 0, 2]})
    assert np.allclose(TT.matrix({"origin": [0, 0, 0], "z": [1, 0, 0]})[:, 0], [0, 1, 0])   # 法向 +X：X 方向取工件 Y


# ---------------------------------------------------------------- 倾斜面程序：仿真、整机仿真、G68.2 后处理与回读
import math

from analysis import cam

SIDE = {"origin": [100, 0, -20], "x": [0, 1, 0], "z": [1, 0, 0]}       # 毛坯右侧面（法向 +X），平面原点在侧面中间高度


def _side_prog():
    slot = [{"t": "rapid", "x": 10, "y": 0, "z": 5}, {"t": "feed", "x": 10, "y": 0, "z": -3, "f": 200.0},
            {"t": "feed", "x": 40, "y": 0, "z": -3, "f": 400.0}, {"t": "rapid", "x": 40, "y": 0, "z": 5}]
    return {"number": 7002, "title": "侧面槽", "ops": [{"tool": {"n": 1, "d": 10.0, "kind": "endmill"}, "spindle": {"rpm": 4000},
                                                       "safe": 5.0, "title": "侧面槽", "moves": slot, "frame": SIDE}]}


def _run(machine="EX-5AX-AC", z_off=100.0, msim=True):
    st = {"mode": "program", "machine": machine, "program": _side_prog(), "stock": {"box": [0, 0, 100, 60], "height": 40}, "post": "fanuc"}
    if msim:
        st["machine_sim"] = {"work_offset_mm": [-50, -30, z_off], "tools": {"1": {"tool": "EM10", "length_mm": 120}}}
    r = cam.run(st)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"][0]


def test_side_slot_volume_and_time():
    """侧面槽：深 3、长 30、Ø10 平底刀——去除体积 = 3 ×（30 × 10 + π·5²），dexel 误差 < 0.5%；切削时间 = 8/200 + 30/400 分"""
    p = _run(msim=False)
    exact = 3 * (30 * 10 + math.pi * 25)
    assert p["sim"]["removed_mm3"] == pytest.approx(exact, rel=5e-3)
    assert p["time"]["cut_s"] == pytest.approx(60 * (8 / 200 + 30 / 400))
    assert p["release"] is None and any("没跑整机仿真就没查" in c["text"] for c in p["checks"])
    record_verdict(("3+2 侧面槽去除体积（dexel）与解析值", "3+2 side slot removed volume (dexel) vs analytic"), "pass", "pass")


def test_g68_2_release_and_readback():
    """整机仿真通过：正式程序写 G28 退 Z、G68.2（平面原点 + 欧拉角）、G53.1、平面坐标、G69；回读与仿真刀路一致才出"""
    p = _run()
    assert p["machine_sim"]["status"] in ("pass", "unknown") and p["release"] is not None
    t = p["release"]["text"]
    i, j, k = TT.euler_zxz(TT.matrix(SIDE))
    assert f"G68.2 X100.0 Y0.0 Z-20.0 I{i:.1f} J{j:.1f} K{k:.1f}" in t.replace(".0000", ".0")
    assert t.index("G91 G28 Z0.0") < t.index("G68.2") < t.index("G53.1") < t.index("G69")
    assert "Z-3.0" in t and "X40.0" in t                                   # 平面坐标
    assert any("倾斜面：转回转轴后" in c["text"] for c in p["checks"])
    record_verdict(("3+2 倾斜面 G68.2 后处理回读一致", "3+2 tilted plane G68.2 post read-back matches"), "pass", "pass")


def test_holder_hits_table_when_part_is_low():
    """零件离工作台太近：侧面槽时刀柄碰到回转工作台，整机仿真报错、不出程序"""
    p = _run(z_off=40.0)
    assert p["release"] is None and any("刀柄碰到机床的回转工作台" in c["text"] for c in p["checks"])


def test_three_axis_machine_cannot_tilt():
    p = _run(machine="EX-VMC", msim=False)
    assert any("没有回转轴" in c["text"] and c["level"] == "error" for c in p["checks"])
