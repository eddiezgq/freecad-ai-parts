"""问渠CAM 验证手册（ADR-0104 第 6 节）：题目清单与 CAM 标准题测试对得上；中英两版都出得来。不真算。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from assist import cam_verification as V
from assist import fea_verification as FV
from assist import i18n

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
        assert not i18n.has_cjk(c["title"]["en"]) and not i18n.has_cjk(FV._source(c["source"], "en")), c
        path, name = c["test"].split("::")
        fn = name.split("[")[0]
        assert fn in _functions(ROOT / path), c["test"]
        listed.add((path, fn))
    for path in sorted(p for p in ROOT.glob("tests/test_cam_*.py") if p.name != "test_cam_verification.py"):
        for name, fn in _functions(path).items():
            src = ast.unparse(fn)
            if name.startswith("test_") and ("record(" in src or "record_verdict(" in src):
                assert (str(path.relative_to(ROOT)), name) in listed, f"{path.name}::{name} 记了对照数，却不在验证手册清单里"


def test_manual_in_both_languages(tmp_path):
    pytest.importorskip("docx")
    from docx import Document

    cases = [{"id": "CAM-01", "test": "t.py::a", "category": "time", "title": {"zh": "车削时间", "en": "Turning time"},
              "source": "t = L/(f·n) / t = L/(f·n)"},
             {"id": "CAM-02", "test": "t.py::b", "category": "kin", "title": {"zh": "逆解", "en": "Inverse"}, "source": "S"}]
    rows = [{"case": "t.py::a", "kind": "value", "quantity": ["时间", "time"], "computed": 30.0, "reference": 30.0, "tol": 1e-3,
             "rel": True, "error": 0.0, "unit": "s", "formula": "t = L/(f·n)", "ok": True}]
    s = FV.summarize(cases, rows, {"t.py::a": "pass"})
    env = {"code": "abc123", "date": "2026-11-19", "numerics": "NumPy 2", "python": "Python 3.13 / Linux"}
    for lang, words in (("zh", ["问渠CAM 验证手册", "共 2 题：通过 1 题，未通过 0 题，未运行 1 题", "加工时间与切削功率", "示例（虚构）"]),
                        ("en", ["WenQuest CAM Verification Manual", "2 problems: 1 passed, 0 failed, 1 not run",
                                "Machining time and cutting power", "fictional examples"])):
        d = Document(V.build(s, env, tmp_path / f"{lang}.docx", lang))
        text = "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])
        for w in words:
            assert w in text, (lang, w)
        if lang == "en":
            left = [ln for ln in text.splitlines() if i18n.has_cjk(ln) and "车削时间" not in ln and "时间" not in ln and "逆解" not in ln]
            assert not left, left[:3]
