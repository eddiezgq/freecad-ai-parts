# -*- coding: utf-8 -*-
"""设计描述与工艺能力表的格式：驱动板 A / B 合格；常见错误能报出来；展开是确定的；没填的能力是“未知”。"""

import copy
import os

import pytest
from conftest import DESIGNS, EXAMPLE_CAP

from wqeda.schema import capability, design

A_PATH = os.path.join(DESIGNS, "drv-joint", "design.yaml")
B_PATH = os.path.join(DESIGNS, "drv-joint-b", "variant.yaml")


def flat():
    """把功能块展开成手写器件清单（测试改坏某个器件用）"""
    d = copy.deepcopy(design.load_design(A_PATH))
    d["circuit"]["parts"] = design.all_parts(d)
    d["circuit"]["generate"] = []
    return d


def test_drive_board_descriptions_are_valid():
    a = design.load_design(A_PATH)
    assert a["name"] == "DRV-JOINT" and len(a["blocks"]) == 7
    base, var = design.load_variant(B_PATH)
    assert base == a and var["rev"] == "B"


def test_expand_is_deterministic_and_complete():
    a = design.load_design(A_PATH)
    x1, x2 = design.expand(a), design.expand(copy.deepcopy(a))
    assert x1 == x2
    assert len(x1["parts"]) == 155 and set(x1["placement"]) == {q["ref"] for q in x1["parts"]}
    assert x1["changes"] == [] and x1["rev"] == "A"
    base, var = design.load_variant(B_PATH)
    xb = design.expand(base, var)
    assert len(xb["parts"]) == 170 and set(xb["placement"]) == {q["ref"] for q in xb["parts"]}
    assert len(xb["changes"]) == 14 and xb["changes"][0] == ("U10", "引脚 12：未用 → ENC_CS_N")
    assert base == design.load_design(A_PATH)  # 打补丁不动底稿


def test_ict_test_points_cover_every_unprobed_net():
    a = design.load_design(A_PATH)
    x = design.expand(a)
    tps = {q["pins"]["1"] for q in x["parts"] if q["ref"].startswith("TP")}
    assert set(x["ict_nets"]) <= tps
    assert not set(x["ict_nets"]) & {"NC_U11", "SW_A", "SW_B", "SW_C"}


@pytest.mark.parametrize(
    "break_it, expect",
    [
        (lambda d: d["circuit"]["parts"].append(dict(d["circuit"]["parts"][0])), "位号重复"),
        (lambda d: d["circuit"]["parts"][0].update(block="nope"), "不在 blocks 里"),
        (lambda d: d["board"]["placement"].update(X99=[1, 2, 0, "F"]), "X99 不在器件清单里"),
        (lambda d: d["board"]["placement"].update(J1=[1, 2, 0, "top"]), "摆放 J1 应是"),
        (lambda d: d["circuit"]["parts"][0]["pins"].update({"9": 5}), "应是 '引脚号': 网络名"),
        (lambda d: d.update(format="x"), "format 应为"),
        (lambda d: d["board"].update(outline_mm=[100]), "outline_mm"),
    ],
)
def test_errors_are_reported(break_it, expect):
    d = flat()
    break_it(d)
    assert any(expect in p for p in design.validate_design(d))


def test_variant_errors_are_reported():
    base = flat()
    var = {
        "format": design.VARIANT_FORMAT,
        "rev": "C",
        "pin_changes": {"U99": []},
        "add_parts": [dict(base["circuit"]["parts"][0])],
    }
    probs = design.validate_variant(var, base)
    assert any("U99" in p for p in probs) and any("位号重复" in p for p in probs)


def test_capability_example_and_unknown():
    cap = capability.load(EXAMPLE_CAP)
    assert cap["fictional"] is True and cap["example_values"] is True
    assert capability.value(cap, "track_min_mm") == 0.127
    assert capability.value(cap, "board_max_mm") is None  # 没填 = 未知
    assert capability.value({"pcb": {}}, "drill_min_mm") is None
    with pytest.raises(KeyError):
        capability.value(cap, "made_up_item")
    assert capability.validate({"format": capability.FORMAT, "factory": "x", "pcb": {"track_min_mm": -1}})
    assert capability.validate({"format": capability.FORMAT, "factory": "x", "pcb": {"nonsense": 1}})
