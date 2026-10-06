# -*- coding: utf-8 -*-
"""零件库第 5 轮 P10③：AI 选型——只从库里挑、例题答出 6207、编号逐个核对（库里没有的不出现）、没配模型时规则回答。"""
import json

import pytest

from hub import select as S

BRG = [("6007", 35, 62, 14), ("6207", 35, 72, 17), ("6307", 35, 80, 21), ("6407", 35, 100, 25), ("6206", 30, 62, 16)]


@pytest.fixture()
def lib(tmp_path):
    ver = "2026.10.9"
    root = tmp_path / "library"
    (root / ver / "A-BRG-DG").mkdir(parents=True)
    (root / ver / "A-KEY-FLAT").mkdir(parents=True)
    items = []
    for size, d, D, B in BRG:
        items.append({"ref": "A-BRG-DG/" + size, "id": "A-BRG-DG", "size": size, "part": "A", "kind": "family", "category": "BRG",
                      "name": {"zh": "深沟球轴承 " + size}, "family": {"zh": "深沟球轴承", "en": "Deep groove ball bearing"},
                      "tags": ["滚动轴承", "ball bearing"], "standards": ["GB/T 276-2013"], "params": {"d_mm": d, "D_mm": D, "B_mm": B}})
    for size in ("4x4x10", "10x8x28"):
        items.append({"ref": "A-KEY-FLAT/" + size, "id": "A-KEY-FLAT", "size": size, "part": "A", "kind": "family", "category": "KEY",
                      "name": {"zh": "普通平键"}, "family": {"zh": "普通平键"}, "tags": ["键"], "standards": ["GB/T 1096"],
                      "params": {"b_mm": int(size.split("x")[0])}})
    (root / ver / "index.json").write_text(json.dumps({"version": ver, "items": items,
                                                       "categories": {"A": {"BRG": {"zh": "滚动轴承"}, "KEY": {"zh": "键"}}}}), encoding="utf-8")
    (root / "latest.json").write_text(json.dumps({"version": ver, "index": "library/{}/index.json".format(ver)}), encoding="utf-8")
    entry = {"id": "A-BRG-DG", "kind": "family", "name": {"zh": "深沟球轴承", "en": "Deep groove ball bearing"},
             "params": [{"key": "d_mm", "zh": "内径", "role": "key", "unit": "mm"}, {"key": "D_mm", "zh": "外径", "role": "key", "unit": "mm"},
                        {"key": "B_mm", "zh": "宽度", "role": "key", "unit": "mm"}],
             "standards": [{"code": "GB/T 276-2013"}], "teaching": {"principle": "主要承受径向载荷，也能承受一定轴向载荷。"},
             "source": {"data_sources": [{"title": "GB/T 276-2013 滚动轴承 深沟球轴承 外形尺寸", "url": "https://example.org/gbt276"}]},
             "sizes": [{"size": s, "params": {"d_mm": d, "D_mm": D, "B_mm": B}} for s, d, D, B in BRG]}
    (root / ver / "A-BRG-DG" / "entry.json").write_text(json.dumps(entry), encoding="utf-8")
    key = {"id": "A-KEY-FLAT", "kind": "family", "name": {"zh": "普通平键", "en": "Parallel key"},
           "params": [{"key": "b_mm", "zh": "键宽", "role": "key", "unit": "mm"}], "source": {},
           "sizes": [{"size": "4x4x10", "params": {"b_mm": 4, "h_mm": 4, "l_mm": 10, "shaft_min_mm": 10, "shaft_max_mm": 12}},
                     {"size": "10x8x28", "params": {"b_mm": 10, "h_mm": 8, "l_mm": 28, "shaft_min_mm": 30, "shaft_max_mm": 38}}]}
    (root / ver / "A-KEY-FLAT" / "entry.json").write_text(json.dumps(key), encoding="utf-8")
    return S.Catalog(str(root))


EXAMPLE = "35 mm 轴、1450 r/min、径向载荷为主用什么轴承"


def test_rules_answer_example(lib):
    r = S.answer(lib, None, EXAMPLE)
    assert r["engine"] == "rules" and r["invalid_refs"] == []
    assert r["refs"][0]["ref"] == "A-BRG-DG/6207"                        # 轻系列优先
    row = {x["key"]: x["value"] for x in r["refs"][0]["row"]}
    assert row == {"d_mm": 35, "D_mm": 72, "B_mm": 17}                     # 注明规格表行
    assert r["refs"][0]["sources"][0]["url"] == "https://example.org/gbt276"
    assert all(x["entry"] == "A-BRG-DG" and x["row"][0]["value"] == 35 for x in r["refs"])


def test_nothing_in_library(lib):
    r = S.answer(lib, None, "500 mm 轴用什么轴承")
    assert r["refs"] == [] and "没有" in r["answer"]
    r = S.answer(lib, None, "我要一台液压挖掘机")
    assert r["refs"] == [] and "没有" in r["answer"]


class FakeLLM:
    """模拟模型：按工具查到 6207，答案里再编一个库里没有的编号"""
    name = "deepseek:test"

    def available(self):
        return True

    def run(self, system, messages, tools, call_tool, max_turns=6):
        assert "只能推荐零件库里有的" in system and {t["name"] for t in tools} == {"search_library", "find_sizes", "get_entry"}
        hits = call_tool("search_library", {"query": "轴承"})
        assert hits[0]["id"] == "A-BRG-DG"
        rows = call_tool("find_sizes", {"entry": "A-BRG-DG", "where": [{"key": "d_mm", "op": "=", "value": 35}]})
        assert {r["size"] for r in rows["rows"]} == {"6007", "6207", "6307", "6407"}
        assert call_tool("find_sizes", {"entry": "A-BRG-XX"})["error"]
        return "推荐 A-BRG-DG/6207（内径 35、外径 72、宽 17）；也可以用 A-BRG-DG/6907 或 A-BRG-ZZ/1。", [{"tool": "find_sizes"}]


def test_llm_refs_are_checked(lib):
    r = S.answer(lib, FakeLLM(), EXAMPLE)
    assert r["engine"] == "deepseek:test"
    assert [x["ref"] for x in r["refs"]] == ["A-BRG-DG/6207"]
    assert set(r["invalid_refs"]) == {"A-BRG-DG/6907", "A-BRG-ZZ/1"} and "不在零件库里" in r["answer"]


def test_no_library_published(tmp_path):
    r = S.answer(S.Catalog(str(tmp_path / "none")), None, EXAMPLE)
    assert r["refs"] == [] and "还没有发布" in r["answer"]


def test_rules_use_the_right_dimension(lib):
    """键按适用轴径区间选（不是按键宽）：12 mm 轴 → 4x4（轴径 10～12）"""
    r = S.answer(lib, None, "直径 12 的轴用多宽的平键")
    assert [x["ref"] for x in r["refs"]] == ["A-KEY-FLAT/4x4x10"]
    r = S.answer(lib, None, "直径 20 的轴用多宽的平键")                    # 20 不在任何区间
    assert r["refs"] == [] and "没有" in r["answer"]

