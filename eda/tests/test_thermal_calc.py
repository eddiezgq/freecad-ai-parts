# -*- coding: utf-8 -*-
"""第 159 轮 159d2c：板级热分析的 calc 发热模型（损耗取计算书的结果）和设计描述里的写法校验。纯计算，不用 KiCad。"""

import copy
import os

from conftest import DESIGNS

from wqeda.blocks import common as c
from wqeda.schema import design as D
from wqeda.thermal import board as tb

CTRL = os.path.join(DESIGNS, "ctrl-ls", "design.yaml")

BOOK = {"units": [{"block": "pfc", "items": [{"key": "p_shunt", "name": "采样电阻损耗", "value": 0.444}]},
                  {"block": "aux", "items": [{"key": "p_clamp", "name": "钳位电阻功耗", "value": 1.722},
                                             {"key": "note", "name": "不是数", "value": "—"}]}]}


def test_calc_items_only_numbers():
    it = tb.calc_items(BOOK)
    assert it["pfc.p_shunt"] == (0.444, "采样电阻损耗")
    assert "aux.note" not in it


def test_calc_losses_share_and_missing():
    x = {"thermal": {"heat": [{"model": "calc", "refs": ["R1"], "item": "pfc.p_shunt"},
                              {"model": "calc", "refs": ["R2", "R3"], "item": "aux.p_clamp", "share": 2},
                              {"model": "calc", "refs": ["R4"], "item": "pfc.no_such"}]}}
    rows = {r["ref"]: r for r in tb.losses({"spec": {}, "blocks": []}, x, None, BOOK)}
    assert abs(rows["R1"]["p_w"] - 0.444) < 1e-9
    assert abs(rows["R2"]["p_w"] - 0.861) < 1e-9 and abs(rows["R3"]["p_w"] - 0.861) < 1e-9
    assert "2 只分摊" in rows["R2"]["parts"][0][0]
    # 计算书里没有这一条：判未知，不当 0 W 算通过
    assert rows["R4"]["status"] == c.UNKNOWN and rows["R4"]["p_w"] == 0


def test_ctrl_ls_thermal_entries_valid_and_bad_ones_caught():
    doc = D.load_design(CTRL)
    assert D.validate_design(doc) == []
    bad = copy.deepcopy(doc)
    bad["board"]["thermal"]["heat"].append({"model": "calc", "refs": ["R203"], "item": "no_dot"})
    bad["board"]["thermal"]["heat"].append({"model": "calc", "refs": ["R203"], "item": "pfc.p_shunt", "share": 0})
    bad["board"]["thermal"]["board_max_c"] = "热"
    p = D.validate_design(bad)
    assert sum("calc 要写 item" in m for m in p) == 2
    assert any("board_max_c" in m for m in p)
