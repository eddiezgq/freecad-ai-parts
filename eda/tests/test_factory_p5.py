# -*- coding: utf-8 -*-
"""第 112 轮 P5：工厂端（问渠贴片）——新检查 P1–P3、列映射、数量统计、生产资料导出、
问题单与设计端闭环、AI 起草问题单。"""

import csv
import os
import warnings

import pytest
from conftest import DESIGNS, EDA, EXAMPLE_CAP

from wqeda import factory, issues, package, quantity
from wqeda.ai import issues as ai_issues
from wqeda.checks import assembly
from wqeda.readers import gerber
from wqeda.schema import capability
from wqeda.schema import design as D

A = os.path.join(DESIGNS, "drv-joint", "design.yaml")
B = os.path.join(DESIGNS, "drv-joint-b", "variant.yaml")
OUT = os.path.join(DESIGNS, "drv-joint", "out")
GERBER = os.path.join(OUT, "gerber.zip")
DEMO = os.path.join(EDA, "examples", "pcba-demo")
ECONOMY = os.path.join(EDA, "examples", "factories", "example-smt-economy.yaml")


@pytest.fixture(scope="module")
def cap():
    return capability.load(EXAMPLE_CAP)


@pytest.fixture(scope="module")
def eco():
    return capability.load(ECONOMY)


def _read(bom=None, cpl=None):
    bom, cpl = bom or os.path.join(OUT, "bom.csv"), cpl or os.path.join(OUT, "pos.csv")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return gerber.read(GERBER, bom, cpl)


def test_assembly_checks_two_factories(cap, eco):
    b = _read()
    st = {r["key"]: r for r in assembly.run(b, cap)}
    assert st["P1"]["status"] == "unknown"  # 第一家没填板子尺寸：未知，不判通过
    assert st["P2"]["status"] == st["P3"]["status"] == "pass" and "U10 0.50" in st["P2"]["detail"]
    st = {r["key"]: r for r in assembly.run(b, eco)}
    assert st["P1"]["status"] == "fail" and st["P1"]["value"] == "100 × 70"
    assert st["P2"]["status"] == "fail" and [a[2] for a in st["P2"]["at"]] == ["U10"]
    assert st["P3"]["status"] == "fail" and st["P3"]["value"] == pytest.approx(0.3, abs=0.01)
    empty = {"format": "wqeda.capability/1", "factory": "x", "pcb": {}}
    assert {r["status"] for r in assembly.run(b, empty)} == {"unknown"}


def test_assembly_two_paths_agree(cap, eco):
    from wqeda import model_io

    k = model_io.load(os.path.join(DESIGNS, "drv-joint", "report", "board-model.json.gz"))
    g = _read()
    for c in (cap, eco):
        assert [r["status"] for r in assembly.run(k, c)] == [r["status"] for r in assembly.run(g, c)]


def test_column_guessing():
    m, miss = gerber.guess_map(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"], "cpl")
    assert m == {"ref": "Designator", "x": "Mid X", "y": "Mid Y", "rot": "Rotation", "side": "Layer"} and not miss
    m, miss = gerber.guess_map(["Comment", "Designator", "Footprint", "Quantity", "MPN"], "bom")
    assert m["refs"] == "Designator" and m["item"] == "MPN" and not miss
    _, miss = gerber.guess_map(["foo", "bar"], "cpl")
    assert set(miss) == {"ref", "x", "y", "rot", "side"}


def test_other_column_names_read_the_same(tmp_path):
    rows = list(csv.DictReader(open(os.path.join(OUT, "pos.csv"), encoding="utf-8")))
    p = tmp_path / "cpl.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Layer", "Designator", "Rotation", "Mid X", "Mid Y"])
        for r in rows:
            w.writerow([r["Side"], r["Ref"], r["Rot"], r["PosX"] + "mm", r["PosY"] + "mm"])
    a = {c.ref: c for c in gerber.read_cpl(os.path.join(OUT, "pos.csv"))}
    b = {c.ref: c for c in gerber.read_cpl(str(p))}
    assert a == b


def test_quantity_matches_files(cap):
    q = {r["name"]: r["value"] for r in quantity.count(_read(), cap)["rows"]}
    pos = list(csv.DictReader(open(os.path.join(OUT, "pos.csv"), encoding="utf-8")))
    assert q["贴片元件"] + q["通孔元件"] == len(pos) == 89
    assert q["通孔元件"] == 5 and q["物料种类"] == 39 and q["元件总数"] == 89 and q["细间距器件"] == 1


@pytest.mark.parametrize("design,out", [(A, "drv-joint"), (B, "drv-joint-b")])
def test_package_export_matches_kicad(design, out):
    """由设计描述导出的物料清单与 KiCad 产物一字不差（排序后）；坐标的位置、角度、面一致"""
    x = package.load(design)
    folder = os.path.join(DESIGNS, out, "out")
    assert sorted(package.bom_csv(x).splitlines()) == sorted(
        open(os.path.join(folder, "bom.csv"), encoding="utf-8").read().splitlines()
    )
    import io

    mine = {r["Ref"]: r for r in csv.DictReader(io.StringIO(package.cpl_csv(x)))}
    kicad = {r["Ref"]: r for r in csv.DictReader(open(os.path.join(folder, "pos.csv"), encoding="utf-8"))}
    assert set(mine) == set(kicad)
    for k, r in kicad.items():
        assert (
            all(float(mine[k][c]) == pytest.approx(float(r[c])) for c in ("PosX", "PosY", "Rot"))
            and mine[k]["Side"] == r["Side"]
        )


def test_item_changes_variant():
    base, var = D.load_variant(os.path.join(DEMO, "variant.yaml"))
    x = D.expand(base, var)
    assert next(q for q in x["parts"] if q["ref"] == "C47")["item"] is None
    assert any(c[0] == "C47" and "物料编号" in c[1] for c in x["changes"])
    bad = dict(var, item_changes={"C999": None})
    assert any("C999" in p for p in D.validate_variant(bad, base))


def test_demo_files_are_current():
    x = package.load(os.path.join(DEMO, "variant.yaml"))
    assert open(os.path.join(DEMO, "bom.csv"), encoding="utf-8").read() == package.bom_csv(x)
    assert open(os.path.join(DEMO, "pos.csv"), encoding="utf-8").read() == package.cpl_csv(x)


def test_closed_loop(cap):
    """工厂查出 → 问题单（编造的引用退回）→ 设计端对上（C47 没物料编号）→ 改设计、重新导出 → 再查：已解决"""
    out = factory.check_package(GERBER, cap, os.path.join(DEMO, "bom.csv"), os.path.join(DEMO, "pos.csv"))
    d1 = next(r for r in out["results"] if r["key"] == "D1")
    assert d1["status"] == "fail" and d1["refs"] == ["C47"] and d1["marks"]
    doc, rej = issues.build(
        out["results"],
        [
            {"cites": [d1["id"]], "question": "C47 要不要贴？", "options": ["贴", "不贴"]},
            {"cites": ["R2"], "question": "引用了通过的项"},
            {"cites": ["R404"], "question": "引用了不存在的项"},
            {"cites": [], "question": "没引用"},
        ],
        "示例贴片厂",
        "demo",
    )
    assert len(doc["issues"]) == 1 and len(rej) == 3 and issues.validate(doc) == []
    assert doc["issues"][0]["refs"] == ["C47"] and doc["results"][0]["id"] == d1["id"]
    rows = issues.match(doc, os.path.join(DEMO, "variant.yaml"))
    assert (
        rows[0]["found"] == ["C47"]
        and any("没有物料编号" in h for h in rows[0]["hints"])
        and rows[0]["state"] == "未复查"
    )
    still = factory.check_package(GERBER, cap, os.path.join(DEMO, "bom.csv"), os.path.join(DEMO, "pos.csv"))["results"]
    assert issues.match(doc, os.path.join(DEMO, "variant.yaml"), still)[0]["state"].startswith("还在")
    fixed = factory.check_package(GERBER, cap, os.path.join(OUT, "bom.csv"), os.path.join(OUT, "pos.csv"))["results"]
    assert issues.match(doc, A, fixed)[0]["state"] == "已解决"
    md = issues.to_markdown(doc)
    assert "C47 要不要贴？" in md and "A. 贴" in md


def test_ai_issue_draft_sends_only_open_results(cap):
    out = factory.check_package(GERBER, cap, os.path.join(DEMO, "bom.csv"), os.path.join(DEMO, "pos.csv"))
    seen = []

    def model(results, fac, lang):
        seen.append(results)
        return {
            "issues": [
                {"cites": ["R1"], "question": "C47？", "options": []},
                {"cites": ["R3"], "question": "R3 已通过"},
            ]
        }, 11

    r = ai_issues.run(out["results"], model, "示例贴片厂", "demo")
    assert r["run"] == 11 and len(r["issues"]["issues"]) == 1 and len(r["rejected"]) == 1
    assert all(x["status"] != "pass" for x in seen[0]) and all("marks" not in x for x in seen[0])
    clean = [dict(x, status="pass") for x in out["results"]]
    assert ai_issues.run(clean, lambda *a: pytest.fail("no open results: model must not be called"))["run"] is None
