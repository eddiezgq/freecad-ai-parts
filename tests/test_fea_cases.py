"""有限元工况与组合（ADR-0093 补充十一）：按组合系数一起求解；线弹性时与各工况单独求解后按系数叠加一致；多组合出包络。
不联网、不调用 LLM。参考：线弹性叠加原理（材料力学）。"""

from __future__ import annotations

import pytest

import analysis
from analysis.fea import study as S
from tests.test_fea_bench import _faces, _need_fea, _plane, _write


def _cantilever(tmp_path):
    step = _write(tmp_path / "c.step", lambda o: o.addBox(0, 0, 0, 200, 10, 10))
    f = _faces(step)
    return {"format": "fea-study/1", "name": "cases", "bodies": [{"id": "b", "step_path": step, "material": "45-QT"}],
            "supports": [{"type": "fixed", "body": "b", "faces": [_plane(f, 0, 0)]}],
            "load_cases": [{"id": "G", "name": "自重", "kind": "dead"}, {"id": "W", "name": "工作载荷", "kind": "operating"},
                           {"id": "E", "name": "急停", "kind": "accidental"}],
            "loads": [{"type": "gravity", "body": "b", "acceleration_m_s2": [0, 0, -9.81], "case": "G"},
                      {"type": "mass", "body": "b", "faces": [_plane(f, 0, 200)], "mass_kg": 2.0},
                      {"type": "force", "body": "b", "faces": [_plane(f, 0, 200)], "vector_n": [0, 0, -50], "case": "W"},
                      {"type": "force", "body": "b", "faces": [_plane(f, 0, 200)], "vector_n": [0, 80, 0], "case": "E"}],
            "combinations": [{"id": "g", "factors": {"G": 1}}, {"id": "w", "factors": {"W": 1}}, {"id": "e", "factors": {"E": 1}},
                             {"id": "C1", "name": "1.35G + 1.5W", "factors": {"G": 1.35, "W": 1.5}, "basis": "测试用"},
                             {"id": "C2", "name": "G + W + E", "factors": {"G": 1, "W": 1, "E": 1}, "basis": "测试用"}],
            "mesh": {"size_mm": 5.0}, "checks": {"convergence": False}, "probes": [{"id": "tip", "point_mm": [200, 5, 5]}]}


def test_combination_equals_superposition(tmp_path):
    _need_fea()
    st = _cantilever(tmp_path)
    st["steps"] = [{"id": k, "type": "static", "combination": k} for k in ("g", "w", "e", "C1", "C2")]
    r = analysis.run("fea", st)
    assert r["status"] == "ok", r["messages"]
    s = {x["id"]: x for x in r["data"]["steps"]}
    u = {k: s[k]["probes"][0]["u_mm"] for k in s}
    for i in range(3):
        assert u["C1"][i] == pytest.approx(1.35 * u["g"][i] + 1.5 * u["w"][i], rel=1e-4, abs=1e-9)
        assert u["C2"][i] == pytest.approx(u["g"][i] + u["w"][i] + u["e"][i], rel=1e-4, abs=1e-9)
    assert abs(u["e"][2]) < 1e-4 * abs(u["e"][1]) and abs(u["g"][1]) < 1e-4 * abs(u["g"][2])   # 组合外的工况不加（只剩网格不对称的微小耦合）
    # 附加质量的重量随重力工况的系数：C1 的外载 z = 1.35 × (梁重 + 2 kg) × g + 1.5 × 50
    beam = 7850e-9 * 200 * 10 * 10
    assert s["C1"]["balance"]["applied_n"][2] == pytest.approx(-(1.35 * (beam + 2.0) * 9.81 + 1.5 * 50), rel=1e-4)
    env = r["data"]["envelope"]
    assert env["vm_governing"] in ("C1", "C2") and env["vm_max_mpa"] == max(x["vm_max_mpa"] for x in s.values())
    assert len(env["surface_vm_envelope"]) == len(s["C1"]["surface"]["vm"])
    assert all(e >= v - 1e-9 for e, v in zip(env["surface_vm_envelope"], s["C2"]["surface"]["vm"]))
    assert env["safety_factor"] is None                                        # 没做收敛核查：可信度未知，包络不给安全系数


def test_case_validation(tmp_path):
    st = _cantilever(tmp_path)
    st["steps"] = [{"id": "s", "type": "static", "combination": "C1"}]
    S.validate(st)
    bad = dict(st, loads=[dict(st["loads"][2], case="X")])
    with pytest.raises(S.StudyInvalid, match="工况 X 不存在"):
        S.validate(bad)
    no_case = dict(st, loads=[{k: v for k, v in st["loads"][2].items() if k != "case"}])
    with pytest.raises(S.StudyInvalid, match="每个载荷都要写 case"):
        S.validate(no_case)
    with pytest.raises(S.StudyInvalid, match="组合 Z 不存在"):
        S.validate(dict(st, steps=[{"id": "s", "type": "static", "combination": "Z"}]))
    with pytest.raises(S.StudyInvalid, match="引用的工况不存在"):
        S.validate(dict(st, combinations=[{"id": "C1", "factors": {"Q": 1}}]))
