# -*- coding: utf-8 -*-
"""第 13 轮 N1–N3：工艺数据格式 v2、工艺文件生成器（过程卡、工序卡、检验卡、刀具卡）、回转体工序简图。"""
import copy
import math
import re
from pathlib import Path

import yaml

from hub import cards, sketch

HERE = Path(__file__).resolve().parents[1]
PLAN = yaml.safe_load((HERE / "std" / "SH-301_process.yaml").read_text(encoding="utf-8"))


def plan():
    return copy.deepcopy(PLAN)


def op(p, name):
    return next(o for o in p["operations"] if o["operation"].startswith(name))


def test_reference_plan_is_complete():
    assert PLAN["version"] == 2
    assert cards.check(plan()) == []


def test_every_drawing_characteristic_is_inspected_and_the_checker_notices_a_gap():
    p = plan()
    fin = op(p, "零件检验")
    fin["inspect"] = [i for i in fin["inspect"] if i["char"] != "C7"]
    assert any("C7" in x for x in cards.check(p))
    p = plan()
    op(p, "粗车")["steps"][0]["tool"] = "T99"
    assert any("T99" in x for x in cards.check(p))


def test_step_values_are_computed_from_cutting_data():
    st = op(plan(), "粗车")["steps"][0]                  # 车端面 Ø50，v_c = 120，f = 0.2，4 刀
    v = cards.step_values(st)
    n = 1000 * 120 / (math.pi * 50)
    assert abs(v["n"] - n) < 1e-9
    assert abs(v["tb"] - 4 * (25 + 2) / (n * 0.2)) < 1e-9            # 车端面分 4 刀
    kw = cards.step_values(op(plan(), "铣键槽")["steps"][2])
    assert abs(kw["tb"] - 5 * 33 / (0.03 * 2 * 1000 * 25 / (math.pi * 12))) < 1e-9


def test_machining_time_never_exceeds_the_time_standard():
    for o in PLAN["operations"]:
        assert cards.op_basic_time(o) <= o["minutes"]


def test_html_has_all_cards_and_every_characteristic():
    h = cards.html(plan())
    assert h.count("<section class='card'>") == 1 + len(cards.machining_ops(PLAN)) + 3
    for k in ("机械加工工艺过程卡片", "机械加工工序卡片", "检验卡片", "刀具卡片", "Machining Operation Sheet"):
        assert k in h
    for c in PLAN["characteristics"]:
        assert c["spec"] in h
    assert h.count("<svg") == len(cards.machining_ops(PLAN))


def test_sketch_marks_machined_surfaces_and_shows_keyway_only_after_milling():
    rough = sketch.shaft_sketch(PLAN["part"], op(plan(), "粗车"), keyway_done=False)
    milled = sketch.shaft_sketch(PLAN["part"], op(plan(), "铣键槽"), keyway_done=True)
    assert 'stroke-width="2.4"' in rough                 # 粗实线 = 本工序加工面
    assert "键槽宽" not in rough and "键槽宽" in milled
    assert "Ø41.5 0/−0.25" in rough
    assert re.search(r"<polyline[^>]+stroke=\"#b5443b\"", rough)    # 定位符号


def test_word_version_is_written(tmp_path):
    path = cards.docx(plan(), tmp_path / "c.docx")
    import docx
    d = docx.Document(str(path))
    text = "\n".join(c.text for t in d.tables for r in t.rows for c in r.cells)
    assert "工序号" in text and "Ø35 k6" in text
