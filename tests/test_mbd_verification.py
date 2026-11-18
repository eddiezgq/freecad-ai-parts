"""多体动力学验证手册（ADR-0102 第 3 步）：题目清单与多体标准题测试对得上；中英两版都出得来。不真算（真算由手册命令跑全部标准题）。"""

from __future__ import annotations

import ast
from pathlib import Path

from assist import fea_verification as FV
from assist import i18n
from assist import mbd_verification as V

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
    # 反过来：每个记了对照数的多体标准题测试都在清单里（新加的标准题不会漏进手册）
    for path in sorted(p for p in ROOT.glob("tests/test_mbd_*.py") if p.name != "test_mbd_verification.py"):
        for name, fn in _functions(path).items():
            src = ast.unparse(fn)
            if name.startswith("test_") and ("record(" in src or "record_verdict(" in src):
                assert (str(path.relative_to(ROOT)), name) in listed, f"{path.name}::{name} 记了对照数，却不在验证手册清单里"


def test_manual_in_both_languages(tmp_path):
    from docx import Document

    cases = [{"id": "MB-01", "test": "t.py::a", "category": "rigid", "title": {"zh": "单摆", "en": "Pendulum"},
              "source": "第一类完全椭圆积分 / Complete elliptic integral of the first kind"},
             {"id": "MB-02", "test": "t.py::b", "category": "flex", "title": {"zh": "梁", "en": "Beam"}, "source": "S"}]
    rows = [{"case": "t.py::a", "kind": "value", "quantity": ["周期", "period"], "computed": 2.0001, "reference": 2.0, "tol": 1e-3,
             "rel": True, "error": 5e-5, "unit": "s", "formula": "T = 4√(L/g)K", "ok": True}]
    s = FV.summarize(cases, rows, {"t.py::a": "pass"})
    env = {"code": "abc123", "date": "2026-11-18", "numerics": "NumPy 2 / SciPy 1.14", "fe": "CalculiX 2.21 / Gmsh 4.13",
           "python": "Python 3.13 / Linux"}
    for lang, words in (("zh", ["问渠多体动力学验证手册", "共 2 题：通过 1 题，未通过 0 题，未运行 1 题", "刚体机构", "旋转梁升速",
                                "第一类完全椭圆积分", "SciPy 1.14"]),
                        ("en", ["WenQuest MBD Verification Manual", "2 problems: 1 passed, 0 failed, 1 not run", "Rigid mechanisms",
                                "spin-up beam", "Complete elliptic integral"])):
        d = Document(V.build(s, env, tmp_path / f"{lang}.docx", lang))
        text = "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])
        for w in words:
            assert w in text, (lang, w)
        if lang == "en":
            left = [ln for ln in text.splitlines() if i18n.has_cjk(ln) and "单摆" not in ln and "周期" not in ln]
            assert not left, left[:3]
