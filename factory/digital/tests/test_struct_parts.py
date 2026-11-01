# -*- coding: utf-8 -*-
"""第 66 轮：结构的受力与“WQ-CR5 大臂”示例零件。
- wqcr5.py 的静力学（截面内力、关节载荷）与 MuJoCo 的逆动力学一致；截面内力沿管长连续、端部等于关节力矩。
- 有限元新载荷“力矩”（任意方向，绕面形心）：悬臂杆端部加弯矩，端部挠度与 ML²/(2EI) 一致，合力矩等于所加的力矩。
- 示例零件：预设载荷取自 wqcr5.py；有限元的端部位移、一阶固有频率与梁理论（计入法兰质量）相差在几个百分点内。"""
import math
import os
import shutil
import tempfile

import numpy as np
import pytest

from cae import wqcr5 as W

mujoco = pytest.importorskip("mujoco")


def test_statics_match_inverse_dynamics():
    m = mujoco.MjModel.from_xml_string(W.mjcf(friction=False, payload_kg=5.0))
    m.opt.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_LIMIT)
    d = mujoco.MjData(m)
    rng = np.random.default_rng(66)
    for q in [np.radians(W.OUTSTRETCHED_DEG)] + [rng.uniform(-3, 3, 6) for _ in range(5)]:
        d.qpos[:6], d.qvel[:], d.qacc[:] = q, 0, 0
        mujoco.mj_inverse(m, d)
        tau = [W.joint_loads(q, j, 5.0)["tau"] for j in range(6)]
        assert np.allclose(tau, -d.qfrc_inverse[:6], atol=1e-6)
    q = np.radians(W.OUTSTRETCHED_DEG)
    # 伸直时：大臂根部截面的弯矩 = J2 的力矩（扭矩是腕部横向偏置 d4 造成的，= J2 的倾覆力矩），J3 端 = J3 的力矩
    s0, s1 = W.section(q, 1, 0.0), W.section(q, 1, 1.0)
    j2, j3 = W.joint_loads(q, 1), W.joint_loads(q, 2)
    assert s0["Mb"] == pytest.approx(abs(j2["tau"]), rel=1e-9) and abs(s0["T"]) == pytest.approx(j2["tilt"], rel=1e-9)
    assert s1["Mb"] == pytest.approx(abs(j3["tau"]), rel=1e-9)
    Mb = [W.section(q, 1, s)["Mb"] for s in np.linspace(0, 1, 21)]
    assert all(a > b for a, b in zip(Mb, Mb[1:]))                                          # 弯矩从根部往外单调减小
    ld = W.upper_arm_end_loads()
    assert ld["force_n"][1] < 0 and ld["moment_nm"][0] == pytest.approx(abs(j3["tau"]), rel=1e-9)
    assert ld["moment_root_nm"] == pytest.approx(abs(j2["tau"]), rel=1e-9)


def test_material_constants_match_cae_table():
    from cae import materials as MT
    m = MT.get("6061-T6")
    assert (W.E_AL, W.NU_AL, W.YIELD_AL) == (m["E_mpa"] * 1e6, m["nu"], m["yield_mpa"] * 1e6)


fem = pytest.mark.skipif(not shutil.which(os.environ.get("WQ_CCX", "ccx")), reason="没有 CalculiX（ccx）")


@fem
def test_moment_load_on_cantilever():
    pytest.importorskip("gmsh")
    bd = pytest.importorskip("build123d")
    from cae import geometry as G, materials as MT, solve as S
    L, a = 200.0, 20.0
    f = tempfile.mktemp(suffix=".step")
    bd.export_step(bd.Box(a, a, L, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)), f)
    step = open(f, "rb").read()
    os.remove(f)
    F = G.faces(step)[0]
    root = [x["id"] for x in F if x["kind"] == "plane" and abs(x["center"][2]) < 1e-6]
    tip = [x["id"] for x in F if x["kind"] == "plane" and abs(x["center"][2] - L) < 1e-6]
    mat = MT.get("6061-T6")
    M = 50e3                                                     # N·mm，绕 x：端部向 −y 弯
    st, surf, _ = S.solve(step, {"material": mat, "mesh": {"size_mm": 5.0},
                                 "loads": [{"type": "fixed", "faces": root}, {"type": "moment", "faces": tip, "vector_nmm": [M, 0, 0]}]})
    I = a ** 4 / 12
    pos, U = surf["positions"], surf["u"]
    end = np.abs(pos[:, 2] - L) < 1e-6
    uy = float(np.mean(U[end, 1]))
    assert uy == pytest.approx(-M * L ** 2 / (2 * mat["E_mpa"] * I), rel=0.03)
    assert np.allclose(st["applied_force_n"], 0, atol=1e-6)
    mid = (np.abs(pos[:, 2] - L / 2) < 6) & (np.abs(pos[:, 1]) > a / 2 - 1e-6)
    assert float(np.max(surf["vm"][mid])) == pytest.approx(M * (a / 2) / I, rel=0.06)
    with pytest.raises(ValueError):
        S.solve(step, {"material": mat, "loads": [{"type": "fixed", "faces": root}, {"type": "moment", "faces": tip, "vector_nmm": [0, 0, 0]}]})


@fem
def test_wqcr5_upper_arm_example_matches_beam_theory():
    pytest.importorskip("gmsh")
    pytest.importorskip("build123d")
    from cae import geometry as G, materials as MT, modal as MO, solve as S, struct_parts as SP
    p = SP.params_of("wqcr5_upper")
    step = SP.build("wqcr5_upper", p)
    F, _, solid = G.faces(step)
    assert solid["solids"] == 1 and solid["bbox_mm"][5] == pytest.approx(p["L"])
    ex = SP.example("wqcr5_upper", p, F)
    kinds = [r["kind"] for r in ex["rows"]]
    assert kinds == ["fixed", "force", "moment"] and all(len(r["faces"]) == 1 for r in ex["rows"])
    ld = W.upper_arm_end_loads()
    assert ex["rows"][1]["fy"] == pytest.approx(ld["force_n"][1], abs=0.01) and ex["rows"][2]["mx"] == pytest.approx(ld["moment_nm"][0], abs=1e-3)
    fm = ex["formula"]
    assert fm["M_root_nm"] == pytest.approx(ld["moment_root_nm"], rel=0.05)              # 不含这根管自己的重量，差几个百分点
    assert fm["sf"] > 20                                                                   # 强度绰绰有余：管子是按刚度定的
    loads = [{"type": "fixed", "faces": ex["rows"][0]["faces"]},
             {"type": "force", "faces": ex["rows"][1]["faces"], "vector_n": [ex["rows"][1][k] for k in ("fx", "fy", "fz")]},
             {"type": "moment", "faces": ex["rows"][2]["faces"], "vector_nmm": [ex["rows"][2][k] * 1e3 for k in ("mx", "my", "mz")]}]
    setup = {"material": MT.get(ex["material_id"]), "loads": loads, "mesh": {"size_mm": 10.0}}
    st, surf, _ = S.solve(step, setup)
    end = np.abs(surf["positions"][:, 2] - p["L"]) < 1e-6
    uy = -float(np.mean(surf["u"][end, 1]))
    assert uy == pytest.approx(fm["delta_mm"], rel=0.05)           # 有限元多了剪切变形，两端的法兰又比管子硬：大体抵消
    f1 = MO.solve(step, setup)[0]["freqs"][0]["hz"]
    assert f1 == pytest.approx(fm["f1_tip_hz"], rel=0.06) and f1 < fm["f1_hz"]              # 法兰的质量让频率下降
