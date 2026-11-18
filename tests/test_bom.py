"""通道 B：物料表分类、查重、对应（ADR-0099 41.3）。AI 用假客户端（模拟，不是录制），核对与查重是确定性代码。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ingest import bom
from kb import completeness
from kb.library import JsonLibrary

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "tests" / "fixtures" / "bom" / "demo-bom.csv"

COLUMNS = {"columns": {"code": "物料编码", "name": "物料名称", "model": "规格型号", "vendor": "供应商",
                       "quantity": "用量", "unit": "单位"}}
CLASSES = {3: "servo_motor", 4: "drive", 5: "bearing", 6: "bearing", 7: "bearing", 8: "custom_part", 9: "custom_part",
           10: "purchased_part", 11: "purchased_part", 12: "fastener", 13: "fastener", 14: "unclassified", 15: "reducer"}


class Fake:
    """按工具名回答：认列给 COLUMNS，分类给 classes（模拟 AI）"""

    def __init__(self, columns=COLUMNS, classes=CLASSES, extra=()):
        self.columns, self.classes, self.extra = columns, classes, list(extra)
        self.requests: list[dict] = []

    def complete(self, request):
        self.requests.append(request)
        if request["tool"]["name"] == "map_columns":
            return {"id": "fake", "tool_input": copy.deepcopy(self.columns), "simulated": True}
        rows = [{"row": n, "category": c, **({"reason": "名称和型号都看不出是什么"} if c == "unclassified" else {})}
                for n, c in self.classes.items()]
        return {"id": "fake", "tool_input": {"rows": rows + self.extra}, "simulated": True}


@pytest.fixture(scope="module")
def library():
    return JsonLibrary(ROOT / "data" / "library").all()


def test_read_table_finds_header_and_row_numbers():
    t = bom.read_table(DEMO)
    assert t["headers"][:4] == ["物料编码", "物料名称", "规格型号", "供应商"]
    assert t["rows"][0]["row"] == 3 and t["rows"][0]["cells"]["规格型号"] == "SGM7J-02A"
    assert len(t["rows"]) == 13 and len(t["sha256"]) == 64


def test_read_xlsx(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["编码", "名称", "型号", "厂商"])
    ws.append(["X1", "轴承", "6201", None])
    ws.append([None, None, None, None])
    ws.append([2.0, "螺钉", "M4X10", "示范"])
    p = tmp_path / "b.xlsx"
    wb.save(p)
    t = bom.read_table(p)
    assert [r["row"] for r in t["rows"]] == [2, 4] and t["rows"][1]["cells"]["编码"] == "2"


def test_normalize():
    assert bom.norm_model("ＳＧＤ７Ｓ－２Ｒ８Ａ") == bom.norm_model("sgd7s-2r8a") == "SGD7S-2R8A"
    assert bom.norm_model("6201 - 2RS") == "6201-2RS"
    assert bom.norm_vendor("Yaskawa America, Inc.") == bom.norm_vendor("YASKAWA") == "yaskawa"
    assert bom.norm_vendor("Yaskawa Electric Corporation") == "yaskawa"
    assert bom.norm_vendor("示范轴承有限公司") == bom.norm_vendor("示范轴承")


@pytest.mark.parametrize("model,cat", [("6201-2RS", "bearing"), ("6000ZZ", "bearing"), ("NU205", "bearing"),
                                       ("M5X12", "fastener"), ("GB/T 70.1 M5x12", "fastener")])
def test_model_feature_hits(model, cat):
    assert bom.model_feature(model)[0] == cat


@pytest.mark.parametrize("model", ["SGM7J-02A", "CSF-14-100-2UH", "LS-101", "100XL037", "SGD7S-2R8A", ""])
def test_model_feature_quiet(model):
    assert bom.model_feature(model) is None


def test_run_classifies_dedupes_and_matches(library):
    fake = Fake()
    r = bom.run(DEMO, fake, library, gaps=completeness.component_gaps)
    items = {it["code"]: it for it in r["items"]}
    # 每行都有分类结论（进了品类，或未能分类 + 原因）
    assert r["summary"]["rows"] == 13 and sum(len(i["rows"]) for i in r["items"]) == 13
    assert all(i["category"] in (*bom.CATEGORIES, bom.UNCLASSIFIED) for i in r["items"])
    assert items["F-900"]["category"] == "unclassified" and "看不出" in items["F-900"]["confirm"][0]
    # 查重：两行 B-010 合并
    assert items["B-010"]["rows"] == [5, 6] and "合并" in items["B-010"]["duplicates"]
    # 对应：厂商写法不同、全角型号也对上
    assert items["A-001"]["component"] == "servo_motor.yaskawa-electric-corporation.sgm7j-02a"
    assert items["A-002"]["component"] == "drive.yaskawa-america-inc.sgd7s-2r8a"
    # 只有型号对上（代理商名）→ 候选，待人确认
    assert items["G-001"]["candidates"] == ["reducer.harmonic-drive-llc.csf-14-100-2uh"]
    assert "component" not in items["G-001"] and items["G-001"]["confirm"]
    # 待补：库里没有的新建；对上的按完整度报告列缺项
    fill = {tuple(t["rows"]): t for t in r["to_fill"]}
    assert "新建" in fill[(8,)]["missing"]
    assert (14,) not in fill                                   # 未能分类的不进待补
    assert not r["confirmed"] and r["source"]["sha256"] == bom.sha256_file(DEMO)


def test_category_conflicts_go_to_confirm(library):
    classes = {**CLASSES, 5: "servo_motor", 6: "bearing", 3: "drive"}
    r = bom.run(DEMO, Fake(classes=classes), library)
    items = {it["code"]: it for it in r["items"]}
    b = " ".join(items["B-010"]["confirm"])
    assert "不同品类" in b and "轴承代号" in b                   # 两行分得不一样，且型号像轴承
    assert any("库里对上的组件是 servo_motor" in c for c in items["A-001"]["confirm"])


def test_bad_ai_output_is_not_adopted(library):
    cols = {"columns": {"model": "规格型号", "name": "名称（不存在）", "vendor": "规格型号", "price": "单价"}}
    extra = [{"row": 99, "category": "bearing"}, {"row": 3, "category": "servo_motor"}, {"row": "x"}]
    classes = dict(CLASSES)
    classes[10] = "belt"
    del classes[11]
    r = bom.run(DEMO, Fake(columns=cols, classes=classes, extra=extra), library)
    notes = " ".join(r["notes"])
    assert "不在表头" in notes and "已对应" in notes and "price" in notes
    assert "第 99 行不在表里" in notes and "两次" in notes and "格式不对" in notes
    assert r["columns"] == {"model": "规格型号"}
    by_row = {i["rows"][0]: i for i in r["items"]}
    assert by_row[10]["category"] == "unclassified" and "不在清单" in by_row[10]["reason"]
    assert by_row[11]["category"] == "unclassified" and "没给" in by_row[11]["reason"]


def test_no_name_or_model_column_stops():
    with pytest.raises(bom.BomError, match="认不出"):
        bom.check_columns({"columns": {"code": "物料编码"}}, ["物料编码", "物料名称"])


def test_what_is_sent_to_ai():
    """认列只发表头和前 3 行；分类不发价格、数量等其余列"""
    fake = Fake()
    bom.run(DEMO, fake, [])
    cols, cls = fake.requests
    assert "第 6 行" not in cols["user"] and "第 5 行" in cols["user"]
    assert cls["tool"]["name"] == "classify_rows"
    assert "单价" not in cls["user"] and "用量" not in cls["user"] and "数量" not in cls["user"]
    assert "示范轴承厂" in cls["user"]


def test_batches_large_tables(tmp_path):
    p = tmp_path / "big.csv"
    p.write_text("编码,名称,型号\n" + "".join(f"P{i},轴承,62{i:02d}\n" for i in range(130)), encoding="utf-8")
    t = bom.read_table(p)
    reqs = bom.classify_requests(t, {"code": "编码", "name": "名称", "model": "型号"})
    assert len(reqs) == 3 and all(r["prompt_version"] == bom.PROMPT_VERSION for r in reqs)


def test_given_columns_skip_ai(library):
    fake = Fake()
    bom.run(DEMO, fake, library, columns=COLUMNS["columns"])
    assert [q["tool"]["name"] for q in fake.requests] == ["classify_rows"]


def test_excel_and_cli(tmp_path, library, monkeypatch):
    r = bom.run(DEMO, Fake(), library, gaps=completeness.component_gaps)
    p = bom.to_excel(r, tmp_path / "r.xlsx")
    from openpyxl import load_workbook

    wb = load_workbook(p)
    assert wb.sheetnames == ["分类", "待补"] and wb["分类"].max_row == len(r["items"]) + 1
    # 命令行：回放目录里没有录制 → 明确报错，不联网
    from ingest.llm_extract import RecordingMissing

    with pytest.raises(RecordingMissing):
        bom.main([str(DEMO), "--replay", str(tmp_path / "none")])


def test_result_is_json_serializable(library):
    r = bom.run(DEMO, Fake(), library, gaps=completeness.component_gaps)
    json.dumps(r, ensure_ascii=False)
