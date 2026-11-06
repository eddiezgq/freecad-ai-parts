# -*- coding: utf-8 -*-
"""同一块驱动板，从 KiCad 板子文件、从光绘 + 物料清单 + 坐标两条路读，六项检查结论和数值一致；
线宽、孔径、孔环和第 88 轮 dfm.py 的结果（out/dfm.json）一致。读 KiCad 文件要 KiCad 7 的 pcbnew，没有就跳过。"""

import json
import os

import pytest
from conftest import DESIGNS, EXAMPLE_CAP

from wqeda.checks import basic
from wqeda.readers import gerber
from wqeda.schema import capability

BOARDS = [("drv-joint", "drv-joint"), ("drv-joint-b", "drv-joint-b")]


def _gerber_path(proj):
    out = os.path.join(DESIGNS, proj, "out")
    return gerber.read(os.path.join(out, "gerber.zip"), os.path.join(out, "bom.csv"), os.path.join(out, "pos.csv"))


def _summary(res):
    return {c["key"]: (c["status"], c["value"], c["count"]) for c in res["checks"]}


@pytest.mark.parametrize("proj, name", BOARDS)
def test_gerber_path_matches_dfm(proj, name):
    cap = capability.load(EXAMPLE_CAP)
    r = {c["key"]: c for c in basic.run(_gerber_path(proj), cap)["checks"]}
    with open(os.path.join(DESIGNS, proj, "out", "dfm.json"), encoding="utf-8") as f:
        dfm = {c["key"]: c for c in json.load(f)["checks"]}
    assert r["F1"]["value"] == dfm["track_width"]["value"]
    assert r["F3-drill"]["value"] == dfm["drill"]["value"]
    assert r["F3-ring"]["value"] == dfm["annular"]["value"]
    assert all(c["status"] == "pass" for c in r.values())


@pytest.mark.parametrize("proj, name", BOARDS)
def test_two_paths_agree(proj, name):
    pytest.importorskip("pcbnew")
    from wqeda.readers import kicad

    cap = capability.load(EXAMPLE_CAP)
    k = kicad.read(os.path.join(DESIGNS, proj, "kicad", name + ".kicad_pcb"))
    g = _gerber_path(proj)
    assert k.outline == g.outline and k.copper_layers == g.copper_layers
    assert len(k.tracks) == len(g.tracks) and len(k.holes) == len(g.holes)
    assert sorted(c.ref for c in k.components) == sorted(c.ref for c in g.components)
    assert _summary(basic.run(k, cap)) == _summary(basic.run(g, cap))
