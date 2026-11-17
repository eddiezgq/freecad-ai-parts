"""有限元附加质量（ADR-0093 补充十）：外购件的质量分到面上，随重力受力、在模态里计入惯性。不联网、不调用 LLM。

参考值：
- 静力：悬臂梁端部集中质量 M 与自重 q：端部挠度 = MgL³/(3EI) + qL⁴/(8EI)（材料力学）。
- 模态：端部质量的悬臂梁一阶频率（Rayleigh 法，梁的等效质量 33/140·m_梁）：f = (1/2π)·√(3EI/L³ / (M + 33/140·m_梁))
  （Thomson《Theory of Vibration with Applications》第 2 章）。
"""

from __future__ import annotations

import math

import pytest

import analysis
from analysis.fea import study as S
from tests.test_fea_bench import _faces, _need_fea, _plane, _write
from tests.verification import record

E, RHO = 210000.0, 7850e-12                 # 45-QT：MPa、t/mm³


def test_tip_mass_static_and_modal(tmp_path):
    _need_fea()
    L, b, M = 200.0, 10.0, 2.0
    step = _write(tmp_path / "cm.step", lambda o: o.addBox(0, 0, 0, L, b, b))
    f = _faces(step)
    st = {"format": "fea-study/1", "name": "m", "bodies": [{"id": "b", "step_path": step, "material": "45-QT"}],
          "supports": [{"type": "fixed", "body": "b", "faces": [_plane(f, 0, 0)]}],
          "loads": [{"type": "mass", "body": "b", "faces": [_plane(f, 0, L)], "mass_kg": M, "label": "端部质量"},
                    {"type": "gravity", "body": "b", "acceleration_m_s2": [0, 0, -9.81]}],
          "steps": [{"id": "s", "type": "static"}, {"id": "m", "type": "modal", "n_modes": 2}], "mesh": {"size_mm": 4.0},
          "checks": {"convergence": False}, "probes": [{"id": "tip", "point_mm": [L, b / 2, b / 2]}]}
    r = analysis.run("fea", st)
    assert r["status"] == "ok", r["messages"]
    s, m = r["data"]["steps"]
    I = b ** 4 / 12
    mb = RHO * b * b * L                                                        # t
    assert s["balance"]["applied_n"][2] == pytest.approx(-(M + mb * 1000) * 9.81, rel=1e-4)   # 附加质量的重量计入外载
    assert s["balance"]["force_error_ratio"] < 1e-4
    q = RHO * b * b * 9810                                                       # N/mm
    tip = M * 9.81 * L ** 3 / (3 * E * I) + q * L ** 4 / (8 * E * I)
    record(("端部挠度（端部质量 + 自重）", "tip deflection (tip mass + self-weight)"), -s["probes"][0]["u_mm"][2], tip, tol=0.01,
           unit="mm", formula="MgL³/(3EI) + qL⁴/(8EI)")
    assert -s["probes"][0]["u_mm"][2] == pytest.approx(tip, rel=0.01)
    f_r = math.sqrt(3 * E * I / L ** 3 / (M / 1000 + 33 / 140 * mb)) / (2 * math.pi)
    record(("一阶固有频率（端部质量）", "first natural frequency (tip mass)"), m["freqs"][0]["hz"], f_r, tol=0.01, unit="Hz",
           formula="(1/2π)·√(3EI/L³/(M + 33/140·m_beam)) (Rayleigh)")
    assert m["freqs"][0]["hz"] == pytest.approx(f_r, rel=0.01)
    st["loads"] = st["loads"][1:]                                                # 去掉附加质量：频率明显升高
    m0 = analysis.run("fea", dict(st, steps=[st["steps"][1]]))["data"]["steps"][0]
    assert m0["freqs"][0]["hz"] > 3 * m["freqs"][0]["hz"]


def test_mass_validation():
    base = {"format": "fea-study/1", "name": "x", "bodies": [{"id": "b", "step_path": "x.step", "material": "45-QT"}],
            "supports": [{"type": "fixed", "body": "b", "faces": [1]}], "steps": [{"id": "s", "type": "static"}]}
    with pytest.raises(S.StudyInvalid, match="还没有加载荷"):                  # 只有附加质量、没有重力：不是载荷
        S.validate(dict(base, loads=[{"type": "mass", "body": "b", "faces": [2], "mass_kg": 1}]))
    with pytest.raises(S.StudyInvalid, match="离心"):
        S.validate(dict(base, loads=[{"type": "mass", "body": "b", "faces": [2], "mass_kg": 1},
                                     {"type": "centrifugal", "body": "b", "speed_rpm": 100,
                                      "axis": {"origin_mm": [0, 0, 0], "dir": [0, 0, 1]}}]))
