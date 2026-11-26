"""龙门三维装配与复核（ADR-0115 44.5.5 第二步，assist/gantry_cad）：布置的尺寸链、干涉与取放区避让、按真实质量复核的推力与力矩、
门架公式校核，与保存的 examples/robots/sewing-loader/out/cad-result.json 一致。不联网、不调用 LLM。

参考值（手算）：
- 布置：X 滑台面高 = 一叠最高 100 + 离叠 20 + Z 模组长（L1 196 + 行程 200）+ 上端让开 8 + 上板 10 = 534 mm；
  Z 滑台中心零位 = 534 − 10 − 8 − 100 − 196/2 = 318 mm；立柱中心 = 取放点 ∓（600/2 + 50 + 100/2）。
- 复核：X 推力 = X 运动部分总质量 × 12.5 m/s²；X 滑台俯仰力矩 = Σ mᵢ·a·(滑台面到 mᵢ 重心的高度差)（牛顿第二定律，对随滑台走的参考点取矩）。
- 门架公式：简支梁 5qL⁴/(384EI) + PL³/(48EI)，矩形管 I = (bh³ − b'h'³)/12。
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from assist import gantry_build as GB
from assist import gantry_cad as C

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples" / "robots" / "sewing-loader" / "out"


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
    assert L["slide_x_mm"] == pytest.approx(100 + 20 + 196 + 200 + 8 + 10)
    assert L["zc0_mm"] == pytest.approx(534 - 10 - 8 - 100 - 98)
    assert L["col_x_mm"] == pytest.approx([0 - 300 - 50 - 50, 1500 + 300 + 50 + 50])
    assert L["span_mm"] == pytest.approx(2300)
    assert L["modules"]["j1_x"]["box"][0][0] == pytest.approx(-50 - 143)        # 滑台中心行程两端各加 L1/2
    assert L["modules"]["j1_x"]["box"][1][0] == pytest.approx(1550 + 143)
    assert L["modules"]["j1_x"]["length_mm"] == pytest.approx(286 + 1600)
    assert L["tool0_mm"] == pytest.approx([0, 0, 100])                         # 方案：关节原点 500 + 末端偏置 −400
    assert L["cup"]["z0"] == pytest.approx(100)                                # 吸盘口就在末端点
    assert L["tube"]["z1"] - L["tube"]["z0"] == pytest.approx(318 + 30 - (100 + 10 + 20))
    assert L["x_ref_mm"] == pytest.approx([0, 0, 534])
    assert L["z_ref_mm"] == pytest.approx([0, -25 - 20, 318])
    bad = copy.deepcopy(cr["chosen"])
    bad["joints"][1]["axis"] = [0, 1, 0]
    with pytest.raises(C.CadError, match="X（水平"):
        C.layout(bad, cr["conditions"], picks, lib)
    with pytest.raises(C.CadError, match="裁片尺寸"):
        C.layout(cr["chosen"], {}, picks, lib)


def test_assembly_masses_interference_and_keepouts(monkeypatch):
    _need()
    cr, br = _inputs()
    lib, picks = _picks(br)
    cad = C.assemble(cr["chosen"], cr["conditions"], picks, lib)
    assert cad["status"] == "pass", (cad["interferences"], cad["keepout_hits"])
    by = {p["name"].split("（")[0]: p for p in cad["parts"]}
    tube = next(p for p in cad["parts"] if p["name"].startswith("竖管"))
    L = cad["layout"]
    v = math.pi * (25 ** 2 - 21 ** 2) * (L["tube"]["z1"] - L["tube"]["z0"])
    assert tube["volume_mm3"] == pytest.approx(v, rel=1e-4)
    assert tube["mass_kg"] == pytest.approx(v * 2.7e-6, rel=1e-3)
    b, h, t, span = 80, 160, 6, 2300 + 100
    assert by["横梁"]["volume_mm3"] == pytest.approx((b * h - (b - 2 * t) * (h - 2 * t)) * span, rel=1e-6)
    # 方向反了的设计值：立柱挪进取料区、Z 模组伸进一叠裁片——都要查出来
    monkeypatch.setitem(C.DESIGN, "keepout_clear_mm", -120.0)
    monkeypatch.setitem(C.DESIGN, "stack_clear_mm", -30.0)
    bad = C.assemble(cr["chosen"], cr["conditions"], picks, lib)
    hit = {(k["part"].split("（")[0], k["zone"]) for k in bad["keepout_hits"]}
    assert ("立柱与地脚板 左", "取料区（一叠裁片）") in hit and ("立柱与地脚板 右", "放料区") in hit
    assert any(k["part"].startswith("j2_z 直线模组") for k in bad["keepout_hits"])
    assert bad["status"] == "fail"
    monkeypatch.setitem(C.DESIGN, "keepout_clear_mm", 50.0)
    monkeypatch.setitem(C.DESIGN, "stack_clear_mm", 20.0)
    monkeypatch.setitem(C.DESIGN, "z_top_gap_mm", 0.0)                     # Z 模组顶到上板：内角圆角压进模组
    bad = C.assemble(cr["chosen"], cr["conditions"], picks, lib)
    assert any({x["a"].split(" ")[0], x["b"].split("（")[0]} == {"j2_z", "Z 轴连接板"} for x in bad["interferences"])


def test_reverify_thrust_and_pitch_match_hand_calc():
    """真实质量与偏置下的推力、俯仰力矩对牛顿第二定律；选件与第一步相同"""
    _need()
    cr, br = _inputs()
    lib, picks = _picks(br)
    cad = C.assemble(cr["chosen"], cr["conditions"], picks, lib)
    b = C.bodies(cad, br["picks"], 0.1, None)
    assert b["missing"] == ["抓手质量厂商没给（未计入运动质量）"]
    assert b["origins"]["j1_x"] == pytest.approx([0, 0, 534])
    assert b["origins"]["j2_z"] == pytest.approx([0, -45, 318 - 534])
    out = GB.build(cr["chosen"], cr["conditions"], layout=lambda p, g, m: C.bodies(cad, p, m, g), start=br["picks"])
    assert out["status"] == "pass"
    assert {j: p["component"] for j, p in out["picks"].items()} == {j: p["component"] for j, p in br["picks"].items()}
    ax = 12.5
    mx = sum(k for _n, k, _p in b["bodies"]["j1_x"]) + sum(k for _n, k, _p in b["bodies"]["j2_z"])
    assert out["loads"]["j1_x"]["thrust_n"] == pytest.approx(mx * ax, rel=0.01)
    # 俯仰力矩：对 X 滑台面中心，Σ mᵢ·a·Δzᵢ；X 加速时 Z 停在提起的位置（零位 −100 + 提 130 = +30 mm）
    zq = 30.0
    arm = sum(k * p[2] for _n, k, p in b["bodies"]["j1_x"]) + sum(k * (p[2] + b["origins"]["j2_z"][2] + zq)
                                                                   for _n, k, p in b["bodies"]["j2_z"])
    my = abs(arm) * ax / 1000
    assert out["loads"]["j1_x"]["moment_pitch_nm"] == pytest.approx(my, rel=0.02)
    assert out["loads"]["j1_x"]["moment_pitch_nm"] > 5 * br["loads"]["j1_x"]["moment_pitch_nm"]  # Z 模组挂在滑台下面：力臂比第一步的约定大


def test_frame_formula_hand_calc():
    _need()
    cr, br = _inputs()
    lib, picks = _picks(br)
    cad = C.assemble(cr["chosen"], cr["conditions"], picks, lib)
    fl = {"x_module_static_kg": 12.3, "moving_kg": 8.0, "thrust_x_n": 100.0, "inertia_z_n": 20.0}
    f = C.frame_formula(cad, fl)
    I = (80 * 160 ** 3 - 68 * 148 ** 3) / 12
    beam = (80 * 160 - 68 * 148) * 2400 * 2.7e-6
    L, E = 2300.0, 68900.0
    q = (beam + 12.3) * 9.81 / L
    P = 8.0 * 9.81 + 20.0
    assert f["beam_I_mm4"] == pytest.approx(I, abs=1)
    assert f["sag_mm"] == pytest.approx(5 * q * L ** 4 / (384 * E * I) + P * L ** 3 / (48 * E * I), rel=1e-3)
    Ic = (100 ** 4 - 88 ** 4) / 12
    hc = cad["layout"]["beam_bottom_mm"]
    assert hc == pytest.approx(534 + 76.5)
    assert f["sway_mm"] == pytest.approx(100.0 * hc ** 3 / (6 * E * Ic), rel=1e-3)


def test_saved_result_consistent():
    """保存的结果：装配通过、复核选件与第一步相同；门架有限元的变形不超过偏保守的公式、两层网格差别小"""
    res = json.loads((EX / "cad-result.json").read_text(encoding="utf-8"))
    assert res["format"] == C.FORMAT and res["status"] == "pass"
    assert res["cad"]["status"] == "pass" and not res["cad"]["interferences"] and not res["cad"]["keepout_hits"]
    assert all(res["reverify"]["same_as_step1"].values())
    fe, fo = res["frame_fea"], res["frame_formula"]
    assert fe["result"]["u_pad_abs_mm"] <= fo["deflection_mm"]
    assert fe["mesh_change"]["u_pad"] < 0.05 and fe["mesh_change"]["f1"] < 0.05
    assert abs(fe["result"]["balance"]["force_error_ratio"]) < 1e-3
    assert res["judge"]["deflection"]["status"] == "pass"
    _need()
    cr, br = _inputs()
    lib, picks = _picks(br)
    cad = C.assemble(cr["chosen"], cr["conditions"], picks, lib)
    assert [p.get("mass_kg") for p in cad["parts"]] == [p.get("mass_kg") for p in res["cad"]["parts"]]
    assert cad["layout"] == res["cad"]["layout"]
