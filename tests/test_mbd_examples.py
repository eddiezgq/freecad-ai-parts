"""问渠多体动力学的入门例子（ADR-0102 第 5 步）：例子目录里的文件齐全，结果摘要就是程序算出来的。

例子 3（模型文件）不需要 FreeCAD；例子 1、2（导入 STEP、建装配体）需要 FreeCAD。
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
from pathlib import Path

import pytest

EX = Path(__file__).resolve().parents[1] / "examples" / "wenquest-mbd"


def _builder():
    spec = importlib.util.spec_from_file_location("wq_mbd_examples", EX / "build_examples.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _results(n):
    B = _builder()
    return json.loads((EX / B.DIRS[n] / "results.json").read_text(encoding="utf-8"))


def test_example_folders_complete():
    B = _builder()
    for n, d in B.DIRS.items():
        names = {p.name for p in (EX / d).iterdir()}
        assert {"README.md", "results.json", "sample-report.zh.pdf", "sample-report.en.pdf"} <= names, (n, names)
    assert {"slider-crank.step", "slider-crank.FCStd"} <= {p.name for p in (EX / B.DIRS[1]).iterdir()}
    assert {"arm.step"} <= {p.name for p in (EX / B.DIRS[2]).iterdir()}
    for frac in B.FRACTIONS:                                      # 模型文件就是生成器写出来的
        got = json.loads((EX / B.DIRS[3] / B.pushrod_name(frac)).read_text(encoding="utf-8"))
        assert got == B.pushrod(round(frac * B.PCR, 1))


def test_example3_pushrod_numbers_reproduce():
    """零轴力那一个重算：一阶频率与摘要一致，与公式 π/(2L²)·√(EI/ρA) 相差 < 0.1 %；外推的屈曲载荷与欧拉公式相差 < 2 %"""
    pytest.importorskip("scipy")
    from analysis.mbd.dae.run import run_model

    B = _builder()
    r = _results(3)
    data, _ = run_model(copy.deepcopy(B.pushrod(0.0)))
    f1 = min(m["frequency_hz"] for m in data["linear"]["modes"] if m["frequency_hz"] > 1)
    row = next(x for x in r["rows"] if x["force_n"] == 0.0)
    assert f1 == pytest.approx(row["f1_hz"], rel=1e-6)
    assert f1 == pytest.approx(r["f0_formula_hz"], rel=1e-3)
    assert r["buckling_load_n"] == pytest.approx(B.PCR, rel=2e-2) and abs(r["error"]) < 0.02
    assert r["euler_load_n"] == pytest.approx(math.pi ** 2 * B.EI / (B.L * 1e-3) ** 2)


@pytest.mark.freecad
def test_examples_1_and_2_reproduce(tmp_path, monkeypatch):
    """例子 1（规则起草、运动学）与例子 2（AI 录制回放、两个关节驱动）重算，峰值与摘要一致"""
    pytest.importorskip("FreeCAD")
    root = EX.parents[1]
    monkeypatch.setenv("FAP_LLM_REPLAY", str(root / "tests/recordings/mbd_mates"))
    monkeypatch.setenv("FAP_AI_PROVIDER", "claude")
    B = _builder()
    _doc, _m, _d, s1 = B.example1(tmp_path)
    r1 = _results(1)
    assert s1["drive_torque_peak_n_m"] == pytest.approx(r1["drive_torque_peak_n_m"], rel=1e-6)
    assert s1["reaction_peak_n"] == pytest.approx(r1["reaction_peak_n"], rel=1e-6)
    assert [j["type"] for j in s1["joints"]].count("revolute") == 3 and s1["verification"]["constraint_residual"] == "pass"
    _doc, _m, _d, s2 = B.example2(tmp_path)
    r2 = _results(2)
    assert s2["draft_by"].startswith("AI") and not s2["notes"] and len(s2["joints"]) == 2
    for k in ("shoulder_torque_peak_n_m", "elbow_torque_peak_n_m"):
        assert s2[k] == pytest.approx(r2[k], rel=1e-6)
