"""通道 A：产品目录整张型号表成批抽取（ADR-0099 41.5）。模拟目录（虚构产品）+ 模拟 AI，全部型号全对。"""

from __future__ import annotations

import copy

import pytest

from ingest import catalog_batch as CB
from ingest.llm_extract import extract_document
from ingest.llm_simulate import simulated_response
from ingest.pdf_extract import Document, Page, Table, extract
from ingest.synthetic_multi import catalogs

DOC_ID = "src-test-catalog"


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    d = tmp_path_factory.mktemp("cat")
    return [(c, extract(c.render(d / f"{c.id}.pdf"))) for v in (0, 1) for c in catalogs(v)]


class ByModel:
    """按请求里的目标型号返回那个型号的“全读对”模拟响应；可指定某型号出错（模拟 AI）"""

    def __init__(self, cat, broken=(), wrong_model=()):
        self.cat, self.broken, self.wrong = cat, set(broken), set(wrong_model)
        self.requests: list[dict] = []

    def complete(self, request):
        self.requests.append(request)
        model = next(m for m in self.cat.models if f"“{m}”" in request["user"] or f'"{m}"' in request["user"]
                     or m in request["user"].split("规格书")[0])
        if model in self.broken:
            raise RuntimeError("模型服务暂时不可用")
        r = simulated_response(self.cat.answers[model])
        if model in self.wrong:
            r = copy.deepcopy(r)
            for it in r["tool_input"]["items"]:
                it["printed_text"] = "999999"
        return r


def test_find_models_in_every_catalog(rendered):
    for cat, doc in rendered:
        found = CB.find_models(doc)
        assert [m["model"] for m in found["models"]] == cat.models, cat.id
        assert all(m["pages"] == [2, 3] or set(m["pages"]) <= {2, 3} for m in found["models"])


def test_batch_extracts_every_model_correctly(rendered):
    for cat, doc in rendered:
        client = ByModel(cat)
        r = CB.extract_catalog(doc, cat.category, DOC_ID, client)
        assert r["summary"]["ok"] == len(cat.models) and r["summary"]["failed"] == 0, cat.id
        for e in r["models"]:
            single = extract_document(doc, cat.category, DOC_ID, ByModel(cat), pages=e["pages"], target_model=e["model"])
            assert e["result"]["items"] == single["items"]                # 与单型号抽取同一套核对
            assert e["result"]["model"] == e["model"] and not e["result"]["rejected"]
        assert len(client.requests) == len(cat.models)                    # 每个型号一次调用


def test_one_failed_model_does_not_stop_others(rendered):
    cat, doc = rendered[0]
    bad, wrong = cat.models[1], cat.models[2]
    r = CB.extract_catalog(doc, cat.category, DOC_ID, ByModel(cat, broken=[bad], wrong_model=[wrong]))
    by = {e["model"]: e for e in r["models"]}
    assert by[bad]["status"] == "failed" and "暂时不可用" in by[bad]["reason"]
    assert by[wrong]["status"] == "ok" and by[wrong]["accepted"] == 0 and by[wrong]["rejected"] > 0   # 读错的值被核对拒掉
    assert by[cat.models[0]]["accepted"] > 0 and r["summary"]["failed"] == 1


def test_chosen_models_only(rendered):
    cat, doc = rendered[0]
    client = ByModel(cat)
    r = CB.extract_catalog(doc, cat.category, DOC_ID, client, models=cat.models[:2])
    assert [e["model"] for e in r["models"]] == cat.models[:2] and len(client.requests) == 2


def _doc(rows):
    return Document("x", "0" * 64, [Page(1, "", [Table(1, 0, rows, (0, 0, 1, 1))])])


def test_yaskawa_prefix_header():
    rows = [["Voltage", "", "200 V", ""], ["Model SGM7J-", "", "A5A", "02A"], ["Rated torque", "N·m", "0.159", "0.637"]]
    assert [m["model"] for m in CB.find_models(_doc(rows))["models"]] == ["SGM7J-A5A", "SGM7J-02A"]


@pytest.mark.parametrize("row", [
    ["Item", "Unit", "Value"],                                  # 只有一列值
    ["Size", "", "14", "17", "20"],                             # 尺寸号是纯数字，不当型号
    ["Moment of Inertia", "I×10−4kgm2", "J×10−5kgfms2"],
    ["Rated torque", "N·m", "0.159", "0.637"],
])
def test_not_a_model_header(row):
    assert CB.header_models(row) == []


def test_no_model_table_says_so():
    rows = [["CSF-2UH Size", "Ratio", "Rated Torque"], ["14", "30", "4.0"], ["17", "50", "16"]]
    with pytest.raises(CB.CatalogError, match="没找到型号表"):
        CB.extract_catalog(_doc(rows), "reducer", DOC_ID, ByModel(None))


def test_cli_list(rendered, tmp_path, capsys):
    cat, _ = rendered[0]
    pdf = cat.render(tmp_path / "c.pdf")
    assert CB.main([str(pdf), "--category", cat.category, "--list"]) == 0
    out = capsys.readouterr().out
    assert all(m in out for m in cat.models)
