"""案例 B2 的选件与节拍（ADR-0115 44.5.6.2）：三轴龙门加末端 C 轴。不联网、不调用 AI。

手算对照：
- C 轴：去放料点那段 0.92 s 里转 90°（梯形，加减速各占 25%）：最高 90 / (0.92 × 0.75) °/s，角加速度再除以 0.92 × 0.25 s；
  力矩 = 工件薄板的转动惯量 m(a² + b²)/12 × 角加速度（转动头与抓手集中在轴线上，惯量可忽略）；
- 各直线轴推力 = 该轴及其后各轴的运动质量 × 该轴加速度（竖直轴再加 g）。
"""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path

import pytest

if os.environ.get("CI"):
    import mujoco  # noqa: F401
else:
    pytest.importorskip("mujoco")

from assist import gantry_build as GB

ROOT = Path(__file__).resolve().parent.parent
CASE = ROOT / "examples" / "robots" / "sewing-loader-xyz" / "out"
G = 9.80665


def _cr():
    return json.loads((CASE / "concept-result.json").read_text(encoding="utf-8"))


def test_wrist_is_found_and_checked():
    c = _cr()["chosen"]
    w = GB.wrist(c)
    assert w["joint"] == "j4_c" and w["link"] == "c_head" and (w["lo"], w["hi"]) == (-100, 100)
    assert [a["joint"] for a in GB.axes(c)] == ["j1_x", "j2_y", "j3_z"]
    b = json.loads((ROOT / "examples" / "robots" / "sewing-loader" / "out" / "concept-result.json").read_text(encoding="utf-8"))
    assert GB.wrist(b["chosen"]) is None                                  # 案例 B 没有 C 轴
    tilt = copy.deepcopy(c)
    tilt["joints"][3]["axis"] = [1, 0, 0]
    with pytest.raises(GB.BuildError, match="不竖直"):
        GB.wrist(tilt)
    off = copy.deepcopy(c)
    off["end_effector"]["offset_mm"] = [30, 0, -50]
    with pytest.raises(GB.BuildError, match="不在 j4_c 的轴线上"):
        GB.wrist(off)


def test_rotation_rides_on_the_two_longest_horizontal_moves():
    cyc = GB.cycle(_cr()["chosen"], 90)
    w = cyc["wrist"]
    assert w["segments"] == ["carry_and_rotate_90", "return"] and w["move_s"] == pytest.approx(0.92)
    v = 90 / (0.92 * 0.75)
    assert w["speed_rpm"] == pytest.approx(v / 6, rel=1e-4) and w["accel_deg_s2"] == pytest.approx(v / (0.92 * 0.25), rel=1e-4)
    dr = next(d for d in cyc["drives"] if d["joint"] == "j4_c")
    assert [s["to"] for s in dr["segments"]] == [90, 0.0] and cyc["initial"]["j4_c"] == 0.0
    with pytest.raises(GB.BuildError, match="超出行程"):
        GB.cycle(_cr()["chosen"], 120)


def test_case_b2_build_matches_hand_calc_and_the_saved_result():
    cr = _cr()
    out = GB.build(cr["chosen"], cr["conditions"])
    assert out["status"] == "pass", out.get("note")
    models = {j: p["model"] for j, p in out["picks"].items()}
    assert models == {"j1_x": "EGC-120-TB-KF-GK", "j2_y": "EGC-70-TB-KF-GK", "j3_z": "EGC-50-TB-KF-GK", "j4_c": "XM540-W270"}
    wr = out["wrist"]
    I = 0.1 * (0.6 ** 2 + 0.4 ** 2) / 12
    alpha = math.radians(wr["accel_deg_s2"])
    assert wr["inertia_max_kgm2"] == pytest.approx(I, rel=0.01)
    assert wr["torque_peak_settled_nm"] == pytest.approx(I * alpha, rel=0.01)
    assert wr["speed_max_rpm"] == pytest.approx(wr["speed_rpm"], rel=0.01)
    mm = {j: sum(k for _n, k in rows) for j, rows in out["moving_masses"].items()}
    assert any(n == "XM540-W270 转动模组" for n, _k in out["moving_masses"]["j3_z"])            # 模组本体压在 Z 上
    ax = out["cycle"]["axes"]
    for j, after in (("j1_x", ("j1_x", "j2_y", "j3_z", "j4_c")), ("j2_y", ("j2_y", "j3_z", "j4_c"))):
        assert out["loads"][j]["thrust_n"] == pytest.approx(sum(mm[k] for k in after) * ax[j]["accel_m_s2"], rel=0.01), j
    assert out["loads"]["j3_z"]["thrust_n"] == pytest.approx((mm["j3_z"] + mm["j4_c"]) * (G + ax["j3_z"]["accel_m_s2"]), rel=0.01)
    assert out["repeatability"]["status"] == "pass" and "C 轴" in out["repeatability"]["note"]
    assert [r["role"] for r in out["bom"]["purchased"]] == ["linear_module"] * 3 + ["rotary_actuator", "gripper"]
    assert any("S2" in x for x in out["open_items"]) and any("y_beam" in x for x in out["open_items"])
    saved = json.loads((CASE / "build-result.json").read_text(encoding="utf-8"))
    assert {j: p["component"] for j, p in saved["picks"].items()} == {j: p["component"] for j, p in out["picks"].items()}
    for j, ld in out["loads"].items():
        for k, v in ld.items():
            assert saved["loads"][j][k] == pytest.approx(v, rel=1e-6), (j, k)
    assert saved["wrist"] == out["wrist"]


def test_a_wrist_needs_the_rotation_angle():
    cr = _cr()
    cond = {k: v for k, v in cr["conditions"].items() if k != "max_rotation"}
    with pytest.raises(GB.BuildError, match="最大转角"):
        GB.build(cr["chosen"], cond)
