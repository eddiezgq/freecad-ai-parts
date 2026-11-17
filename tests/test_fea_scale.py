"""大模型（ADR-0093 补充十二第 5 步）：算前估内存、自动选求解器、放不下就算前报；迭代法与直接法结果一致。"""

from __future__ import annotations

import pytest

from analysis.fea import solve as S
from tests.test_fea_bench import _need_fea, _write


def test_memory_estimate_matches_calibration():
    """标定点（本机实测，CalculiX 2.21、二阶四面体）：估计值不低于实测、也不过分高估（≤ 1.6 倍）"""
    for solver, nodes, measured_mb in (("SPOOLES", 14518, 341), ("SPOOLES", 42683, 1360), ("SPOOLES", 73092, 2834),
                                       (S.ITERATIVE, 42683, 188), (S.ITERATIVE, 148902, 625), (S.ITERATIVE, 328322, 1396)):
        est = S.estimate_mb(solver, nodes)
        assert measured_mb * 0.95 <= est <= measured_mb * 1.6, (solver, nodes, est, measured_mb)


def test_pick_solver(monkeypatch):
    monkeypatch.delenv("FAP_CCX_SOLVER", raising=False)
    assert S.pick_solver(20000, True, avail=7000) == ("SPOOLES", "")
    solver, note = S.pick_solver(300000, True, avail=7000)
    assert solver == S.ITERATIVE and "迭代法" in note
    with pytest.raises(S.TooBig, match="内存"):
        S.pick_solver(300000, False, avail=7000)          # 模态、接触等要直接法：放不下就算前报
    with pytest.raises(S.TooBig, match="内存"):
        S.pick_solver(3_000_000, True, avail=7000)
    assert S.pick_solver(10 ** 7, True, avail=None)[0] == "SPOOLES"   # 不知道可用内存时不估、照常
    monkeypatch.setenv("FAP_CCX_SOLVER", "PARDISO")
    assert S.pick_solver(10, True, avail=7000)[0] == "PARDISO"


def test_iterative_and_direct_agree(tmp_path, monkeypatch):
    """同一个算例，迭代法与直接法的位移、应力相差 < 0.1 %"""
    _need_fea()
    from analysis.fea import run_study
    from analysis.fea.geometry import faces

    step = _write(tmp_path / "blk.step", lambda o: o.addBox(0, 0, 0, 200, 60, 40))
    fs = faces(step)[0]
    x0 = next(f["id"] for f in fs if abs(f["center"][0]) < 1e-6)
    x1 = next(f["id"] for f in fs if abs(f["center"][0] - 200) < 1e-6)
    study = {"format": "fea-study/1", "name": "blk", "bodies": [{"id": "b", "step_path": step, "material": "45-QT"}],
             "supports": [{"type": "fixed", "body": "b", "faces": [x0]}],
             "loads": [{"type": "force", "body": "b", "faces": [x1], "vector_n": [0, 0, -1000]}],
             "steps": [{"id": "s1", "type": "static"}], "mesh": {"size_mm": 8}, "checks": {"convergence": False}}
    out = {}
    for solver in ("SPOOLES", S.ITERATIVE):
        monkeypatch.setenv("FAP_CCX_SOLVER", solver)
        r = run_study(study)
        assert r["status"] == "ok", r["messages"]
        out[solver] = r["data"]["steps"][0]
        assert out[solver]["solver"] == solver
    a, b = out["SPOOLES"], out[S.ITERATIVE]
    assert b["u_max_mm"] == pytest.approx(a["u_max_mm"], rel=1e-3)
    assert b["vm_max_mpa"] == pytest.approx(a["vm_max_mpa"], rel=1e-3)
