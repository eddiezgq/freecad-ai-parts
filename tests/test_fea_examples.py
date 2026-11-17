"""问渠有限元的入门例子（ADR-0096 第 6 步）：仓库里的例子文件打得开、走得通。需要 FreeCAD。

例子 2、3 从一句话走到中英报告（录制回放，不联网）；例子 1 只查给用户打开的 FreeCAD 文件：零件与约束看得见、能接管、能进计算
（整套计算在 build_examples.py 里，生成样张时跑）。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.freecad

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples/wenquest-fea"


def _build():
    spec = importlib.util.spec_from_file_location("build_examples", EX / "build_examples.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_example_files_are_complete():
    for d, step in (("01-j2-housing-free", "J2-HSG.step"), ("02-rj201-shaft-sentence", "RJ-201.step"),
                    ("03-arm-upper-sentence", "ARM-UPPER.step")):
        for name in (step, "README.md", "sample-report.zh.pdf", "sample-report.en.pdf"):
            assert (EX / d / name).is_file(), (d, name)
    assert (EX / "01-j2-housing-free/J2-HSG.FCStd").is_file()


def test_example1_file_opens_and_is_adopted(tmp_path):
    import shutil

    import FreeCAD

    from freecad_addon.fc import fem_flow as F

    f = tmp_path / "J2-HSG.FCStd"
    shutil.copyfile(EX / "01-j2-housing-free/J2-HSG.FCStd", f)
    doc = FreeCAD.openDocument(str(f))
    try:
        an = next(o for o in doc.Objects if o.TypeId == "Fem::FemAnalysis")
        assert not F.adopted(an)
        part = doc.getObject("J2_HSG")
        assert part.Visibility and all(o.Visibility for o in doc.Objects if o.TypeId.startswith("Fem::Constraint"))
        F.adopt(an, "6061-T6")
        study, _ = F.prepare_run(an)
        assert [x["type"] for x in study["supports"]] == ["fixed"] and [x["type"] for x in study["loads"]] == ["force"]
        assert study["loads"][0]["vector_n"] == pytest.approx([2000.0, 0, 0], abs=1e-6)
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_sentence_examples_reach_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("FAP_LLM_REPLAY", str(ROOT / "tests/recordings/fea_draft"))
    monkeypatch.setenv("FAP_AI_PROVIDER", "claude")
    b = _build()
    for n in (2, 3):
        got = b.run(n, tmp_path, samples=False)
        assert got["status"] == "ok", got.get("messages")
        assert got["replay"] and not got["errors"] and not got["rejected"]
        assert got["questions"]                                      # 两个例子都有追问（写在例子说明里）
        assert set(got["reports"]) == {"zh", "en"} and all(Path(p).is_file() for p in got["reports"].values())
        assert got["u_max_mm"] > 0
    assert os.environ["FAP_LLM_REPLAY"]
