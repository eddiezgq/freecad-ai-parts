"""案例 B2 的三维装配与复核（ADR-0115 44.5.6.3，assist/gantry_cad 的三轴加 C 轴）：布置的尺寸链、干涉（含 C 轴转动）、
真实质量的构件原点、扭转公式、由测点位移得末端位移。不联网、不调用 LLM。

参考值（手算）：
- 末端：吸盘口 = 末端点（方案零位 z = 750 − 650 − 50 = 50）；转动头板厚 10 → 输出舵盘面 zh = 50 + 吸盘高 + 10；
- Z 模组：Y 滑台面高 = 一叠最高 100 + 离叠 20 + Z 模组长（L1 + 行程 300）+ 上端让开 8 + 上板 10（同案例 B）；
- 转动头板 100 × 120 转一圈的外圆半径 √(50² + 60²) = 78.10 mm，加间隙 10：C 轴离 Z 滑台面 88.10 mm；竖杆（沿 y 60）
  贴着管夹（后面 20），竖杆中心离 Z 滑台面 50，所以竖杆在 C 轴后面 38.10 mm；
- 扭转：闭口薄壁矩形管 J = 2t(b−t)²(h−t)²/(b+h−2t)（布雷特），θ = T·L/(4GJ)，G = E/2(1+ν)。
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from assist import gantry_build as GB
from assist import gantry_cad as C

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples" / "robots" / "sewing-loader-xyz" / "out"


def _need():
    pytest.importorskip("gmsh")
    pytest.importorskip("mujoco")


def _inputs():
    cr = json.loads((EX / "concept-result.json").read_text(encoding="utf-8"))
    br = json.loads((EX / "build-result.json").read_text(encoding="utf-8"))
    return cr, br


def _picks(br):
    lib = GB._library()
    genv = C._env(lib.get(br["gripper"]["component"]))
    return lib, dict(br["picks"], _gripper={"envelope": genv})


def test_layout_dimension_chain():
    cr, br = _inputs()
    lib, picks = _picks(br)
    L = C.layout(cr["chosen"], cr["conditions"], picks, lib)
    e = {j: C._env(lib.get(picks[j]["component"])) for j in ("j1_x", "j2_y", "j3_z")}
    cup = C._env(lib.get(br["gripper"]["component"]))["length_mm"]
    assert L["kind"] == "xyz" and L["tool0_mm"] == pytest.approx([0, 0, 50])
    zh = 50 + cup + 10
    assert L["refs_mm"]["j4_c"] == pytest.approx([0, 0, zh])
    assert L["cup"]["z0"] == pytest.approx(50)
    lz = e["j3_z"]["length_mm"] + 300
    assert L["slide_y_mm"] == pytest.approx(100 + 20 + lz + 8 + 10)
    assert L["slide_x_mm"] == pytest.approx(L["slide_y_mm"] + e["j2_y"]["height_mm"] + 10)
    assert L["c_sweep_r_mm"] == pytest.approx(math.hypot(50, 60))
    assert L["arm_offset_mm"] == pytest.approx(math.hypot(50, 60) + 10 - 30 - 20)
    assert L["refs_mm"]["j3_z"][1] == pytest.approx(-(math.hypot(50, 60) + 10))        # Z 滑台面在 C 轴后面
    mx, my = L["modules"]["j1_x"]["box"], L["modules"]["j2_y"]["box"]
    assert my[0][1] == pytest.approx(mx[0][1])                                              # Y 模组后端与 X 模组后沿齐平
    assert my[1][1] - my[0][1] == pytest.approx(e["j2_y"]["length_mm"] + 1000)
    assert L["refs_mm"]["j1_x"][1] == pytest.approx((mx[0][1] + mx[1][1]) / 2)
    pick, place = L["keepouts"]
    assert pick["box"][0][:2] == pytest.approx([-300, -300]) and pick["box"][1][:2] == pytest.approx([1500, 1100])
    assert place["box"][0][:2] == pytest.approx([1800, 600])
    xl, xr = L["col_x_mm"]
    assert xl == pytest.approx(-300 - 50 - 50)                                             # 取料区左边让开
    assert xr == pytest.approx(max(2400 + 50, mx[1][0]) + 50)                             # X 模组右端或放料区，取远的
    bad = copy.deepcopy(cr["conditions"])
    bad.pop("area_length")
    with pytest.raises(C.CadError, match="取料区"):
        C.layout(cr["chosen"], bad, picks, lib)


def test_assembly_passes_and_c_rotation_is_swept(monkeypatch):
    _need()
    cr, br = _inputs()
    lib, picks = _picks(br)
    cad = C.assemble(cr["chosen"], cr["conditions"], picks, lib)
    assert cad["status"] == "pass", (cad["interferences"], cad["keepout_hits"])
    names = [p["name"] for p in cad["parts"]]
    assert any(n.startswith("j4_c 转动模组") for n in names) and "转动头板" in names and "Y 模组连接板" in names
    head = next(p for p in cad["parts"] if p["name"] == "转动头板")
    assert head["body"] == "c" and head["material"] == "7075-T6"
    assert head["mass_kg"] == pytest.approx(head["volume_mm3"] * 2.81e-6, rel=1e-3)
    assert head["volume_mm3"] < 100 * 120 * 10                                              # 舵盘孔、凸台让位孔掏掉了
    # 间隙取负：转动头板转一圈会扫到 Z 模组，要查出来
    monkeypatch.setitem(C.DESIGN_XYZ, "c_sweep_clear_mm", -40.0)
    bad = C.assemble(cr["chosen"], cr["conditions"], picks, lib)
    assert any("转动头板" in (h["a"] + h["b"]) and "C 轴" in h["how"] for h in bad["interferences"])


def test_rotation_overlap_steps_through_the_range():
    """同轴的零件按转角逐步求交：偏心的块转到另一个块的位置就相交，不转时不相交"""
    _need()
    from analysis.fea.geometry import _LOCK, _gmsh

    with _LOCK:
        gm = _gmsh()
        gm.clear()
        gm.model.add("t")
        fix = C._box([20, -5, 0], [30, 5, 10])
        mov = C._box([-5, 20, 0], [5, 30, 10])                  # 在 +y，绕 z 转 −90° 到 +x
        C._occ().synchronize()
        v_all = C._rot_overlap(fix, mov, [0, 0], {"lo": -100, "hi": 100})
        v_none = C._rot_overlap(fix, mov, [0, 0], {"lo": 0, "hi": 40})
        gm.clear()
    assert v_all == pytest.approx(1000, rel=1e-3)
    assert v_none == 0.0


def test_bodies_origins_and_workpiece_plate():
    _need()
    cr, br = _inputs()
    lib, picks = _picks(br)
    cad = C.assemble(cr["chosen"], cr["conditions"], picks, lib)
    b = C.bodies(cad, br["picks"], 0.1, None)
    L = cad["layout"]
    acc = np.zeros(3)
    for c in L["chain"]:
        acc = acc + np.asarray(b["origins"][c["joint"]])
        assert acc == pytest.approx(L["refs_mm"][c["joint"]])                               # 各构件原点逐级相加 = 参考点
    wp = next(r for r in b["bodies"]["j4_c"] if r[0] == "工件（单片）")
    assert wp[3] == (600.0, 400.0)                                                          # 薄板：C 轴转动惯量用
    assert wp[2] == pytest.approx([0, 0, 50 - L["refs_mm"]["j4_c"][2]])
    assert any(r[0].startswith("XM540-W270") for r in b["bodies"]["j3_z"])                  # 转动模组本体在 Z 构件上
    assert b["missing"] == ["抓手质量厂商没给（未计入运动质量）"]
    mv = C.moving(cad, b)
    assert mv["all"]["mass_kg"] == pytest.approx(sum(mv[c["joint"]]["mass_kg"] for c in L["chain"]))


def test_torsion_formula_hand_calc():
    _need()
    cr, br = _inputs()
    lib, picks = _picks(br)
    cad = C.assemble(cr["chosen"], cr["conditions"], picks, lib)
    L = cad["layout"]
    yc = L["x_ref_mm"][1]
    zc = L["beam_bottom_mm"] + 80
    fl = {"x_module_static_kg": 20.0, "moving_kg": 10.0, "thrust_x_n": 100.0, "thrust_y_n": 30.0, "inertia_z_n": 15.0,
          "cog_all_worst_mm": [0, yc + 400, 500], "cog_y_worst_mm": [0, yc + 800, zc - 300], "cog_z_worst_mm": [0, yc + 900, 100],
          "tool_worst_mm": [0, yc + 1000, zc - 700]}
    f = C.frame_formula(cad, fl)
    b, h, t = 80, 160, 6
    J = 2 * t * (b - t) ** 2 * (h - t) ** 2 / (b + h - 2 * t)
    E = 68900.0
    Gm = E / (2 * 1.33)
    T = (10 * 9.81 + 15) * 400 + 30 * 300
    span, hc = L["span_mm"], L["beam_bottom_mm"]
    Ic = (100 ** 4 - 88 ** 4) / 12
    assert f["beam_J_mm4"] == pytest.approx(J, abs=1)
    assert f["torque_nm"] == pytest.approx(T / 1000, rel=1e-4)
    assert f["twist_beam_rad"] == pytest.approx(T * span / (4 * Gm * J), rel=1e-3)
    assert f["twist_columns_rad"] == pytest.approx(T / 2 * hc / (E * Ic), rel=1e-3)
    assert f["tool_lever_mm"] == pytest.approx(math.hypot(1000, 700), abs=0.01)
    assert f["tool_frame_mm"] == pytest.approx(f["sag_mm"] + f["sway_mm"] + f["sway_y_mm"] + f["twist_tool_mm"], abs=1e-3)


def test_tool_displacement_from_probe_rotation():
    """横梁截面绕 x 转 θ（前低后高）：末端点在前面 1 m、下面 0.5 m，位移 = 垫块位移 + θ × 力臂"""
    L = {"x_ref_mm": [0, 0, 0]}
    geo = {"x_mid": 0.0, "pad": [[0, 0, -2], [0, 0, 0]]}
    th = 1e-4
    d = C.PROBE_OFFSET_MM
    u0 = np.array([0.01, 0.0, -0.3])

    def u(p):
        return (u0 + np.cross([th, 0, 0], np.asarray(p) - [0, 0, -2])).tolist()
    pts = {"pad": [0, 0, -2], "yp": [0, d, 0], "ym": [0, -d, 0], "xp": [2 * d, 0, 0], "xm": [-2 * d, 0, 0]}
    probes = [{"id": k, "u_mm": u(p)} for k, p in pts.items()]
    out = C._tool_from_probes(L, {"tool_worst_mm": [0, 1000, -500]}, geo, probes, 0.0)
    assert out["rotation_rad"] == pytest.approx([th, 0, 0], abs=1e-12)
    assert out["u_tool_frame_mm"] == pytest.approx(u([0, 1000, -500]), abs=1e-9)
