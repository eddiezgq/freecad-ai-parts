"""分析模块框架（ADR-0056，M10 第一步）：结果外壳、材料库、求解器查找与子进程、模块登记。不联网。"""

from __future__ import annotations

import os
import sys
import types

import pytest

import analysis
from analysis.common import materials, result, solvers
from kb.validation import errors


def test_materials_have_sources_and_no_estimates():
    ms = materials.all_materials()
    assert len(ms) >= 10
    for m in ms:
        assert errors("material.schema.json", m) == []
        assert m["sources"] and all(s.strip() for s in m["sources"])
    # 原表中的估算值不收：Q345 的疲劳极限、HT200 的弹性模量、铝的 S-N 斜率
    assert "fatigue_limit_bending_mpa" not in materials.get("Q345")
    assert "elastic_modulus_mpa" not in materials.get("HT200")
    assert "sn_exponent" not in materials.get("6061-T6")
    assert materials.get("45-QT")["yield_strength_mpa"] == 355


def test_missing_data_is_reported_not_estimated():
    with pytest.raises(materials.MissingData, match="弹性模量|elastic_modulus_mpa"):
        materials.require(materials.get("HT200"), ["elastic_modulus_mpa"], "有限元")
    with pytest.raises(materials.MissingData):
        materials.get("unobtainium")
    assert materials.strength_mpa(materials.get("45-QT")) == (355, "屈服强度")
    assert materials.strength_mpa(materials.get("HT200")) == (200, "抗拉强度")


def test_result_envelope():
    c = result.check("扭转应力", 72.4, 72.0, "√3·16T/(πd³)")
    assert c["relative_error_ratio"] == pytest.approx(0.4 / 72.0)
    r = result.make("fea", "1", {"material": "45-QT"}, {"max_mpa": 72.4}, checks=[c], limitations=["线弹性"],
                    solver={"name": "CalculiX", "version": "2.21"}, elapsed_s=1.23456)
    assert r["status"] == "ok" and r["elapsed_s"] == 1.235
    f = result.failed("fea", "1", {}, "没有 ccx")
    assert f["status"] == "failed" and f["messages"] == ["没有 ccx"]
    with pytest.raises(result.ResultInvalid):
        result.make("fea", "1", {}, {"x": float("nan")})
    with pytest.raises(result.ResultInvalid):
        result.make("Bad Id", "1", {}, {})


def test_find_ccx_env_and_run(tmp_path, monkeypatch):
    fake = tmp_path / "ccx"
    fake.write_text("")
    monkeypatch.setenv("FAP_CCX", str(fake))
    assert solvers.find_ccx() == str(fake)
    monkeypatch.setenv("FAP_CCX", str(tmp_path / "nope"))
    assert solvers.find_ccx() != str(tmp_path / "nope")
    ok = solvers.run([sys.executable, "-c", "print('hi')"], tmp_path, 30)
    assert ok.stdout.strip() == "hi"
    with pytest.raises(solvers.SolverError, match="返回 3"):
        solvers.run([sys.executable, "-c", "import sys; sys.exit(3)"], tmp_path, 30)
    with pytest.raises(solvers.SolverError, match="秒未算完"):
        solvers.run([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, 0.5)
    assert solvers.missing_python(["json", "no_such_pkg_xyz"]) == ["no_such_pkg_xyz"]


def test_ccx_found_in_ci():
    """CI 必须装好 CalculiX（ADR-0056 后果一节）；本地没有时跳过。"""
    ccx = solvers.find_ccx()
    if ccx is None:
        if os.environ.get("CI"):
            raise AssertionError("CI 中没有找到 ccx")
        pytest.skip("本机没有 CalculiX")
    assert solvers.ccx_version(ccx)


def _fake(mid="demo", deps=()):
    mod = types.ModuleType(f"fake_{mid}")
    mod.MODULE = {"id": mid, "name": "演示", "python": list(deps), "install": "pip install x"}
    mod.run = lambda setup: result.make(mid, "1", setup, {"echo": setup.get("x")})
    return mod


def test_registry(monkeypatch):
    fakes = {"m.ok": _fake("demo"), "m.missing": _fake("needs", ["no_such_pkg_xyz"])}
    monkeypatch.setattr(analysis, "MODULE_PATHS", tuple(fakes))
    monkeypatch.setattr(analysis, "_load", lambda p: fakes[p])
    st = {m["id"]: m for m in analysis.modules()}
    assert st["demo"]["available"] and not st["needs"]["available"]
    assert "no_such_pkg_xyz" in st["needs"]["missing"][0]
    assert analysis.run("demo", {"x": 3})["data"] == {"echo": 3}
    out = analysis.run("needs", {})
    assert out["status"] == "failed" and "pip install x" in out["messages"][0]
    with pytest.raises(analysis.UnknownModule):
        analysis.run("nope", {})


def test_mcp_tools():
    from mcp_server import tools

    assert tools.list_analyses() == {"modules": analysis.modules()}
    with pytest.raises(tools.ToolInputError):
        tools.run_analysis("nope", {})
