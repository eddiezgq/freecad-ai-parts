"""NAFEMS 自由振动标准题（ADR-0096 第 4 步，补模态类的题）。不联网、不调用 LLM。

FV52 简支的“厚”方板：10 m × 10 m × 1 m，E = 200 GPa、ν = 0.3、ρ = 8000 kg/m³。NAFEMS 参考频率（第 4–10 阶，前 3 阶为刚体运动）：
45.897、109.44、109.44、167.89、193.59、206.19、206.19 Hz（闭式解）。
出处：NAFEMS《The Standard NAFEMS Benchmarks》TNSB Rev. 3（1990）FV52；题目与参考值按 Ansys 验证手册 Benchmark C5
（Hlp_V_VMC5）与 Altair OptiStruct 验证题 OS-V: 0455。

支承分两种算（2026-11-17 本机实算查明）：
- 弯曲模态（第 4、5、6、7、9、10 阶）：侧面“硬”简支（Navier 条件：x = 0、a 两侧面 uy = uz = 0，y = 0、a 两侧面 ux = uz = 0），
  与参考值相差 < 1 %（网格 500 mm 时 +0.1 % ～ +0.8 %，300 mm 时 +0.2 % ～ +0.6 %）。
  NAFEMS 文本给的底面四条边 uz = 0 的模型，网格加密后弯曲模态收敛到比参考值低约 7 %（底边支承比闭式解的支承软），
  所以不用它比弯曲模态。
- 面内模态（第 8 阶 193.59 Hz）：用 NAFEMS 文本的底面四条边 uz = 0（面内不限，程序去掉 3 个面内刚体运动），与参考值一致。
侧面硬简支时多出的面内、厚度方向模态（如约 155 Hz 的一对）不在参考表里：按参考值找最近的计算值对照。

材料用材料库的 45-QT（E = 210 GPa、ν = 0.3、ρ = 7850）：ν 相同时线弹性的固有频率与 √(E/ρ) 成正比（量纲分析），
参考频率按 √((210/7850)/(200/8000)) 换算后再比，换算系数写在手册里。
"""

from __future__ import annotations

import math

import pytest

from tests.test_fea_bench import _faces, _need_fea, _plane, _write
from tests.verification import record

FLEX = [(4, 45.897), (5, 109.44), (6, 109.44), (7, 167.89), (9, 206.19), (10, 206.19)]
INPLANE = (8, 193.59)


def _scale():
    from analysis.common import materials

    m = materials.get("45-QT")
    assert m["poisson_ratio"] == pytest.approx(0.3)
    return math.sqrt((m["elastic_modulus_mpa"] / m["density_kg_m3"]) / (200e3 / 8000))


def _modal(step, supports, n):
    from analysis.fea import run_study

    st = {"format": "fea-study/1", "name": "fv52", "bodies": [{"id": "p", "step_path": step, "material": "45-QT"}],
          "supports": supports, "loads": [], "steps": [{"id": "m", "type": "modal", "n_modes": n}], "mesh": {"size_mm": 500.0}}
    r = run_study(st)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["steps"][0]


def test_nafems_fv52_flexural_modes(tmp_path):
    _need_fea()
    sc, a, t = _scale(), 10000.0, 1000.0
    step = _write(tmp_path / "fv52.step", lambda o: o.addBox(0, 0, 0, a, a, t))
    f = _faces(step)
    s = _modal(step, [{"type": "displacement", "body": "p", "faces": [_plane(f, 0, 0), _plane(f, 0, a)], "uy_mm": 0, "uz_mm": 0},
                      {"type": "displacement", "body": "p", "faces": [_plane(f, 1, 0), _plane(f, 1, a)], "ux_mm": 0, "uz_mm": 0}], 10)
    assert s["rigid_modes"] == 0
    left = [x["hz"] for x in s["freqs"]]
    for mode, ref in FLEX:
        got = min(left, key=lambda x: abs(x - ref * sc))
        left.remove(got)
        record((f"第 {mode} 阶（弯曲）固有频率", f"natural frequency, mode {mode} (flexural)"), got, ref * sc, tol=0.01, unit="Hz",
               formula=f"NAFEMS FV52 {ref} Hz × {sc:.5f}")
        assert got == pytest.approx(ref * sc, rel=0.01), (mode, got, ref * sc)


def test_nafems_fv52_inplane_mode(tmp_path):
    _need_fea()
    from analysis.fea.geometry import faces

    sc, a, t = _scale(), 10000.0, 1000.0
    step = _write(tmp_path / "fv52.step", lambda o: o.addBox(0, 0, 0, a, a, t))
    edges = [e["id"] for e in faces(step)[1]["edge_list"] if abs(e["center"][2]) < 1e-6]
    assert len(edges) == 4
    s = _modal(step, [{"type": "displacement", "body": "p", "edges": edges, "uz_mm": 0}], 10)
    assert s["rigid_modes"] == 3
    mode, ref = INPLANE
    got = min((x["hz"] for x in s["freqs"]), key=lambda x: abs(x - ref * sc))
    record((f"第 {mode} 阶（面内）固有频率", f"natural frequency, mode {mode} (in-plane)"), got, ref * sc, tol=0.005, unit="Hz",
           formula=f"NAFEMS FV52 {ref} Hz × {sc:.5f}")
    assert got == pytest.approx(ref * sc, rel=0.005)
