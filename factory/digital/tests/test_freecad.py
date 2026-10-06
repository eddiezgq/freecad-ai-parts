# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "freecad"))

import wq_cam_keyway  # noqa: E402
import wq_drawing  # noqa: E402
import wq_publish  # noqa: E402
import wq_shaft  # noqa: E402


def test_default_shaft_blank_matches_factory_bom():
    from factory import data as F
    assert wq_publish.blank_kg(wq_shaft.PARAMS) == dict(F.BOMS["SH-301"][1])["RM-45-D50"]


def test_keyway_gcode_stays_inside_slot_and_reaches_depth():
    g, info = wq_cam_keyway.generate(wq_shaft.PARAMS)
    pts = wq_cam_keyway.parse(g)
    cut = [p for p in pts if not p[3]]
    kw = wq_shaft.PARAMS["keyway"]
    assert min(p[2] for p in cut) == -kw["t"]
    xs = [p[0] for p in cut]
    # 刀心在槽两端各内缩半个刀径
    assert min(xs) - kw["b"] / 2 >= info["slot"]["x_from"] - 1e-9
    assert max(xs) + kw["b"] / 2 <= info["slot"]["x_to"] + 1e-9
    assert info["slot"]["x_to"] - info["slot"]["x_from"] == kw["L"]
    assert g.startswith("%") and "M30" in g


def test_shorter_keyway_changes_gcode_not_bom():
    p = {**wq_shaft.PARAMS, "keyway": dict(wq_shaft.PARAMS["keyway"], L=42.0)}
    _, info = wq_cam_keyway.generate(p)
    assert info["slot"]["x_to"] - info["slot"]["x_from"] == 42.0
    assert wq_publish.bom(p) == wq_publish.bom(wq_shaft.PARAMS)


def test_longer_shaft_needs_more_steel():
    p = dict(wq_shaft.PARAMS, segments=[(30, 60)] + list(wq_shaft.PARAMS["segments"][1:]))
    assert wq_publish.blank_kg(p) > wq_publish.blank_kg(wq_shaft.PARAMS)


def test_drawing_is_valid_svg_with_title_block():
    import xml.dom.minidom
    s = wq_drawing.svg(wq_shaft.PARAMS, revision=3, author="王小明")
    doc = xml.dom.minidom.parseString(s.encode("utf-8"))
    text = s
    assert doc.documentElement.tagName == "svg"
    assert "rev 3" in text and "王小明" in text and "总长 167" in text
