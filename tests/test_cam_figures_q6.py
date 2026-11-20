"""问渠CAM Q6a 工艺卡的图（ADR-0106 Q6a）：零件图、装夹图、刀具图插进工艺卡；图上的数都记进出处账、与来源一致；
缺的尺寸不画不标、写明缺什么。"""

from __future__ import annotations

import json
import zipfile

import pytest

from analysis import cam
from assist import cam_card as CC
from assist import cam_process as CP
from assist.fea_report import _ptr_get, fmt
from tests.test_cam_card import TURN
from tests.test_cam_post_q5 import MSIM_MILL, _mill_prog


def _images(docx):
    with zipfile.ZipFile(docx) as z:
        return [n for n in z.namelist() if n.startswith("word/media/")]


def _text(docx):
    from docx import Document

    return "\n".join(p.text for p in Document(str(docx)).paragraphs)


def _figure_entries(o, src):
    led = json.loads(o["ledger"].read_text(encoding="utf-8"))
    figs = [e for e in led["numbers"] if e.get("in") == "figure"]
    for e in figs:
        if e["source"] in src:
            assert fmt(_ptr_get(src[e["source"]], e["pointer"])) == e["text"], e
    return figs


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_turn_card_has_three_kinds_of_drawings(tmp_path, lang):
    d = CP.draft(TURN, "P")
    d["setup"]["machine_sim"]["chuck"] = {"jaw_len": 25.0, "jaw_d": 110.0}
    r = cam.run({**d["setup"], "post": "fanuc"})
    o = CC.build_docx(d, r, tmp_path / "card.docx", lang=lang)
    assert len(_images(o["docx"])) == 1 + 2 + 1            # 零件图、两次装夹、刀具图
    t = _text(o["docx"])
    assert ("零件图" in t and "装夹图" in t and "刀具图" in t) if lang == "zh" else ("Part drawing" in t and "Setup drawing" in t)
    figs = _figure_entries(o, {"draft": d, "result": r["data"]})
    texts = {e["text"] for e in figs}
    assert {"30", "40", "35", "24", "155"} <= texts and "40" in texts and "100" in texts and "125" in texts
    # 伸出长度 = 0 − (卡爪起点 + 夹持长度)，与计算结果的 clamp 一致
    for p in r["data"]["programs"]:
        c = p["clamp"]
        assert fmt(-(c["z_left"] + c["jaw_len"])) in texts
    assert any(e["source"] == "library" and e["pointer"].endswith("/insert/nose_radius_mm") for e in figs)

def test_mill_card_without_model_says_so_and_with_views_draws_part(tmp_path):
    prog = _mill_prog()
    ms = {**MSIM_MILL, "fixtures": [{"id": "vise", "name": "虎钳钳口", "box_mm": [-5, -12, -40, 105, -2, -10]}]}
    setup = {"mode": "program", "machine": "EX-VMC", "program": prog, "stock": {"box": [0, 0, 100, 60], "height": 40}, "machine_sim": ms,
             "item": "块", "kienzle": "C45E"}
    r = cam.run({**setup, "post": "fanuc"})
    d = {"setup": setup, "card": [], "notes": [], "by": "测试", "explanation": "", "iso_group": "P"}
    o = CC.build_docx(d, r, tmp_path / "a.docx", lang="zh")
    assert "没有零件模型，零件图没出" in _text(o["docx"]) and len(_images(o["docx"])) == 2
    views = {"bbox": [0, 0, -30, 100, 60, 0], "top": [[[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]],
             "front": [[[0, -30], [100, -30], [100, 0], [0, 0], [0, -30]]], "left": [[[-60, -30], [0, -30], [0, 0], [-60, 0], [-60, -30]]]}
    d2 = {**d, "figures": {"part_views": views}}
    o2 = CC.build_docx(d2, r, tmp_path / "b.docx", lang="zh")
    assert len(_images(o2["docx"])) == 3
    figs = _figure_entries(o2, {"draft": d2, "result": r["data"]})
    der = {(e["text"], e["formula"].split(" =")[0]) for e in figs if e["source"] == "derived"}
    assert {("100", "总长"), ("60", "总宽"), ("30", "总高"), ("100", "毛坯长"), ("60", "毛坯宽")} <= der
    assert any(e["pointer"] == "/programs/0/replay_in/stock/height" for e in figs)


def test_missing_tool_dimensions_are_listed(tmp_path):
    """刀具库没写刃长、伸出长的：图上不标，工艺卡写明缺什么"""
    prog = _mill_prog()
    setup = {"mode": "program", "machine": "EX-VMC", "program": prog, "stock": {"box": [0, 0, 100, 60], "height": 40}, "machine_sim": MSIM_MILL}
    r = cam.run({**setup, "post": "fanuc"})
    d = {"setup": setup, "card": [], "notes": [], "by": "测试", "explanation": "", "iso_group": "P"}
    t = _text(CC.build_docx(d, r, tmp_path / "c.docx", lang="zh")["docx"])
    assert "T04：没写伸出长" in t and "T05：没写刃长" in t
    t_en = _text(CC.build_docx(d, r, tmp_path / "c_en.docx", lang="en")["docx"])
    assert "T05: no flute length given" in t_en
