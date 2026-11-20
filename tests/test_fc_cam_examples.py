"""问渠CAM 的入门例子（ADR-0104 产品化第 3 步）：重算与样张（results.json）一致。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.freecad
EX = Path(__file__).resolve().parents[1] / "examples" / "wenquest-cam"


def _builder():
    sys.path.insert(0, str(EX))
    import build_examples as B

    return B


@pytest.mark.parametrize("n", [1, 2])
def test_examples_reproduce(n):
    pytest.importorskip("FreeCAD")
    B = _builder()
    _, _d, r = B.example1() if n == 1 else B.example2()
    sample = json.loads((EX / B.DIRS[n] / "results.json").read_text(encoding="utf-8"))
    got = B._summary(r)
    assert got["total_time_s"] == pytest.approx(sample["total_time_s"], abs=0.05)
    for a, b in zip(got["programs"], sample["programs"], strict=True):
        assert a["released"] and b["released"] and not a["errors"]
        assert a["machine_sim"]["fingerprint"] == b["machine_sim"]["fingerprint"]
        nc = EX / B.DIRS[n] / f"O{a['number']:04d}_fanuc.nc"
        assert a["machine_sim"]["fingerprint"] in nc.read_text(encoding="utf-8")


def test_example2_card_has_part_and_setup_drawings(tmp_path):
    """Q6a：铣的例子——零件三视图（TechDraw 投影，看不见的线另列）、装夹图、刀具图都进工艺卡；总长、总宽、总高 = 零件包围盒"""
    pytest.importorskip("FreeCAD")
    import zipfile

    from assist import cam_card
    from freecad_addon.fc import cam_figures_fc as FF

    B = _builder()
    _, d, r = B.example2()
    shape = B.block()
    v = FF.part_views(shape, -shape.BoundBox.ZMax)
    bb = shape.BoundBox
    assert v["bbox"][5] == pytest.approx(0.0) and v["bbox"][2] == pytest.approx(-bb.ZLength)
    assert v["top"] and v["front"] and v["left"] and v["front_hidden"]      # 型腔、孔在主视里是虚线
    us = [p[0] for pl in v["front"] for p in pl]
    assert min(us) == pytest.approx(bb.XMin, abs=1e-3) and max(us) == pytest.approx(bb.XMax, abs=1e-3)
    o = cam_card.build_docx({**d, "figures": {"part_views": v}}, r, tmp_path / "card.docx", lang="zh")
    with zipfile.ZipFile(o["docx"]) as z:
        assert sum(n.startswith("word/media/") for n in z.namelist()) == 3
    led = json.loads(o["ledger"].read_text(encoding="utf-8"))
    der = {(e["text"], e["formula"].split(" =")[0]) for e in led["numbers"] if e["source"] == "derived" and e.get("in") == "figure"}
    from assist.fea_report import fmt

    assert {(fmt(bb.XLength), "总长"), (fmt(bb.YLength), "总宽"), (fmt(bb.ZLength), "总高")} <= der
