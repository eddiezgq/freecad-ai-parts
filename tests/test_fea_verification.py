"""验证手册（ADR-0096 第 4 步）：题目清单与标准题测试对得上；记录、汇总、出 Word 的规则。不真算（真算由手册命令跑全部标准题）。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from assist import fea_verification as V
from tests import verification

ROOT = Path(__file__).resolve().parents[1]


def _functions(path: Path) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def test_catalog_matches_benchmark_tests():
    cat = V.load_cases()
    ids = [c["id"] for c in cat["cases"]]
    assert len(ids) == len(set(ids)) and len({c["test"] for c in cat["cases"]}) == len(ids)
    listed = set()
    for c in cat["cases"]:
        assert c["category"] in cat["categories"] and c["title"]["zh"] and c["title"]["en"] and c["source"], c
        path, name = c["test"].split("::")
        fn = name.split("[")[0]
        assert fn in _functions(ROOT / path), c["test"]
        listed.add((path, fn))
    # 反过来：每个记了对照数的标准题测试都在清单里（新加的标准题不会漏进手册）
    for path in sorted(p for p in ROOT.glob("tests/test_fea_*.py") if p.name != "test_fea_verification.py"):
        for name, fn in _functions(path).items():
            src = ast.unparse(fn)
            if name.startswith("test_") and ("record(" in src or "record_verdict(" in src):
                assert (str(path.relative_to(ROOT)), name) in listed, f"{path.name}::{name} 记了对照数，却不在验证手册清单里"


def test_record_is_silent_without_output(monkeypatch, tmp_path):
    monkeypatch.delenv("FAP_VERIFICATION_OUT", raising=False)
    verification.record(("a", "a"), 1.0, 1.0, tol=0.01)                     # 不设输出：什么都不做
    out = tmp_path / "r.jsonl"
    monkeypatch.setenv("FAP_VERIFICATION_OUT", str(out))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_x.py::test_y (call)")
    verification.record(("应力", "stress"), 101.0, 100.0, tol=0.02, unit="MPa", formula="σ = F/A")
    verification.record(("应力", "stress"), 103.0, 100.0, tol=0.02, unit="MPa")
    verification.record_verdict(("核查", "check"), "fail", "fail")
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert [r["ok"] for r in rows] == [True, False, True] and rows[0]["case"] == "tests/test_x.py::test_y"
    assert abs(rows[0]["error"] - 0.01) < 1e-12


def _fake():
    cases = [{"id": "VM-01", "test": "t.py::a", "category": "static", "title": {"zh": "甲", "en": "A"}, "source": "S"},
             {"id": "VM-02", "test": "t.py::b", "category": "modal", "title": {"zh": "乙", "en": "B"}, "source": "S"},
             {"id": "VM-03", "test": "t.py::c", "category": "trust", "title": {"zh": "丙", "en": "C"}, "source": "S"},
             {"id": "VM-04", "test": "t.py::d", "category": "static", "title": {"zh": "丁", "en": "D"}, "source": "S"}]
    rows = [{"case": "t.py::a", "kind": "value", "quantity": ["应力", "stress"], "computed": 100.5, "reference": 100.0, "tol": 0.02,
             "rel": True, "error": 0.005, "unit": "MPa", "formula": "σ = F/A", "ok": True},
            {"case": "t.py::b", "kind": "value", "quantity": ["频率", "frequency"], "computed": 110.0, "reference": 100.0, "tol": 0.02,
             "rel": True, "error": 0.1, "unit": "Hz", "formula": "", "ok": False},
            {"case": "t.py::c", "kind": "verdict", "quantity": ["收敛", "convergence"], "computed": "fail", "reference": "fail",
             "ok": True}]
    return cases, rows, {"t.py::a": "pass", "t.py::b": "pass", "t.py::c": "pass"}


def test_summary_rules():
    cases, rows, outcome = _fake()
    s = V.summarize(cases, rows, outcome)
    assert [c["result"] for c in s["cases"]] == ["pass", "fail", "pass", "skipped"]   # 超出容差算未通过；没运行的写明
    assert (s["n"], s["ok"], s["bad"], s["skip"], s["rows"], s["rows_ok"]) == (4, 2, 1, 1, 3, 2)


def test_manual_in_both_languages(tmp_path):
    from docx import Document

    cases, rows, outcome = _fake()
    s = V.summarize(cases, rows, outcome)
    env = {"code": "abc123", "date": "2026-11-17", "solver": "CalculiX 2.21", "gmsh": "4.13.1", "python": "Python 3.13 / Linux"}
    for lang, words in (("zh", ["问渠有限元验证手册", "共 4 题：通过 2 题，未通过 1 题，未运行 1 题", "+0.500 %", "± 2 %", "未通过"]),
                        ("en", ["WenQuest FEA Verification Manual", "4 problems: 2 passed, 1 failed, 1 not run", "+0.500 %", "fail"])):
        d = Document(V.build(s, env, tmp_path / f"{lang}.docx", lang))
        text = "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])
        for w in words:
            assert w in text, (lang, w)


def test_source_by_language():
    assert V._source("材料力学 / strength of materials: σ = Eδ/L", "zh") == "材料力学：σ = Eδ/L"
    assert V._source("材料力学 / strength of materials: σ = Eδ/L", "en") == "strength of materials: σ = Eδ/L"
    assert V._source("Timoshenko & Goodier, Theory of Elasticity（旋转圆盘 / rotating disc）", "en") == \
        "Timoshenko & Goodier, Theory of Elasticity (rotating disc)"
    assert V._source("Johnson, Contact Mechanics (1985), ch. 4", "zh") == "Johnson, Contact Mechanics (1985), ch. 4"
