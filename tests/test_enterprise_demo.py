"""示范缝纫机企业（ADR-0099 41.6）：三条通道建企业库并重跑主轴选型。这里用模拟 AI；真实模型的录制回放在
有录制时另测（tests/recordings/bom、part_kind，由 .github/workflows/enterprise-demo.yml 生成）。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from ingest import bom

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "examples" / "enterprise-lockstitch"
BOOK_33_11 = [(10, 22), (12, 10), (16, 215), (12, 10), (10, 40)]


def _module():
    spec = importlib.util.spec_from_file_location("enterprise_demo_build", HERE / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _kind(name: str) -> str:
    for words, cat in ((("电机",), "servo_motor"), (("驱动器",), "drive"), (("轴承",), "bearing"),
                       (("螺钉", "垫圈", "销", "挡圈"), "fastener"),
                       (("机壳", "上轴", "曲柄", "凸轮", "偏心轮", "针杆", "连杆", "下轴", "旋梭轴", "压脚杆", "送布牙", "散热器"),
                        "custom_part"),
                       (("同步带", "带轮", "电磁铁", "旋梭", "机针", "油泵", "开关", "控制板", "风扇", "包装箱"), "purchased_part")):
        if any(w in name for w in words):
            return cat
    return bom.UNCLASSIFIED


class FakeAI:
    """模拟 AI：认列按表头原文；分类按名称里的词（只用来走通流程，不是评测）"""

    def __init__(self):
        self.table = bom.read_table(HERE / "bom.csv")

    def complete(self, request):
        name = request["tool"]["name"]
        if name == "map_columns":
            cols = {"code": "物料号", "name": "品名", "model": "规格型号", "vendor": "品牌/厂家", "quantity": "单台用量", "unit": "单位"}
            return {"id": "fake", "tool_input": {"columns": cols}, "simulated": True}
        if name == "classify_rows":
            rows = []
            for r in self.table["rows"]:
                if f"{r['row']}：" in request["user"]:
                    cat = _kind(r["cells"]["品名"])
                    rows.append({"row": r["row"], "category": cat, **({"reason": "名称看不出是什么"} if cat == "unclassified" else {})})
            return {"id": "fake", "tool_input": {"rows": rows}, "simulated": True}
        if name == "propose_part_kind":
            return {"id": "fake", "tool_input": {"part_kind": "shaft" if "上轴" in request["user"] else "other",
                                                 "reason": "模拟"}, "simulated": True}
        raise AssertionError(name)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    mod = _module()
    fake = FakeAI()
    mod._clients = lambda record, provider: (fake, fake, bom.DEFAULT_MODEL)
    d = tmp_path_factory.mktemp("demo")
    summary = mod.build(d / "library", d / "out")
    return summary, d


def test_custom_parts_measured_from_models(built):
    s, d = built
    ls101 = next(c for c in s["custom_parts"] if c["drawing"] == "LS-101")
    assert [(x["diameter_mm"], x["length_mm"]) for x in ls101["segments"]] == BOOK_33_11
    assert ls101["mass_kg"] and ls101["confirmed_part_kind"] == "shaft"
    comp = json.loads((d / "library" / "components" / "custom_part" / "custom_part.demo-sewing.ls-101.json").read_text("utf-8"))
    assert comp["license"] == "enterprise" and comp["params"]["segment_3_diameter_mm"]["value"] == 16
    hs = next(c for c in s["custom_parts"] if c["drawing"] == "LS-HS")
    assert hs["mass_kg"] is None and hs["volume_mm3"] > 0                       # 没给材料就只给体积


def test_bom_channel(built):
    _, d = built
    r = json.loads((d / "out" / "bom-result.json").read_text("utf-8"))
    by = {it["code"]: it for it in r["items"]}
    assert r["summary"]["rows"] == 41
    assert by["A-SM-04"]["component"] == "servo_motor.yaskawa-electric-corporation.sgm7j-04a" and len(by["A-SM-04"]["rows"]) == 2
    assert by["A-SD-2R8"]["component"] == "drive.yaskawa-america-inc.sgd7s-2r8a"
    assert by["B-6201"]["component"] == "bearing.nsk-ltd.6201" and len(by["B-6201"]["rows"]) == 2
    assert by["LS-101"]["component"] == "custom_part.demo-sewing.ls-101"           # 自制件按图号对上企业库
    assert "component" not in by["B-6000"]                                          # 6000ZZ（带防尘盖）库里只有开式 6000
    assert by["X-002"]["category"] == "unclassified" and by["X-002"]["confirm"]
    news = {t.get("model") or t.get("component") for t in r["to_fill"]}
    assert "6202" in news and "6000ZZ" in news
    assert "单价" not in json.dumps(r, ensure_ascii=False)                         # 价格列没进结果


def test_completeness_and_selection(built):
    s, d = built
    assert s["completeness"]["count"] >= 6
    assert s["selection"]["motor"].endswith("sgm7j-04a") and s["selection"]["drive"].endswith("sgd7s-2r8a")
    assert s["selection"]["overall"] in ("pass", "warn")                           # 与 examples/apps/lockstitch 的下限选型一致
    assert (d / "out" / "completeness.xlsx").is_file() and (d / "out" / "bom-result.xlsx").is_file()


def test_replay_real_model_recordings(tmp_path):
    """真实模型（Claude）的录制回放：物料表每行都有结论，只有“杂项”未能分类；上轴的类型 AI 提议与人确认一致"""
    mod = _module()
    s = mod.build(tmp_path / "library", tmp_path / "out")
    r = json.loads((tmp_path / "out" / "bom-result.json").read_text("utf-8"))
    unc = [i["code"] for i in r["items"] if i["category"] == "unclassified"]
    assert unc == ["X-002"] and r["summary"]["classified"] == 40
    by = {i["code"]: i for i in r["items"]}
    assert by["B-6201"]["category"] == "bearing" and by["F-007"]["category"] == "fastener"
    assert by["P-HOOK"]["category"] == "purchased_part" and by["LS-104"]["category"] == "custom_part"
    ls101 = next(c for c in s["custom_parts"] if c["drawing"] == "LS-101")
    assert ls101["ai_part_kind"] == "shaft" == ls101["confirmed_part_kind"]
    assert s["selection"]["overall"] == "pass"
    # NSK 轴承带安装尺寸入库后，只剩手轮缺质量（材料没人确认，不估）
    rep = json.loads((tmp_path / "out" / "completeness.json").read_text("utf-8"))
    assert (rep["complete"], rep["count"]) == (6, 7)
    bad = [c for c in rep["components"] if not c["complete"]]
    assert [c["model"] for c in bad] == ["LS-HS"] and [m["field"] for m in bad[0]["missing"]] == ["params.mass_kg"]
