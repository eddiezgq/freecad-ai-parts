"""问渠CAM Q6b 程序对比（ADR-0106 Q6b）：只改写法（顺序号、注释、子程序、换后处理）报“刀路相同”；
改一个坐标、改进给、改转速、换一把刀、加一道工序都准确报出在哪一行。"""

from __future__ import annotations

import copy

import pytest

from analysis import cam
from analysis.cam import machines, progdiff
from tests.test_cam_post_q5 import (  # noqa: F401  （fixture）
    MSIM_MILL,
    TURN,
    _mill,
    _mill_prog,
    _turn,
    posts_dir,
)

VMC = machines.get("EX-VMC")
LATHE = machines.get("EX-LATHE")


def _line(text, needle):
    return next(i for i, ln in enumerate(text.splitlines(), 1) if needle in ln)


@pytest.mark.parametrize("post", ["siemens", "heidenhain", "hnc", "style"])
def test_same_path_different_writing(post, posts_dir):  # noqa: F811
    """同一个程序换后处理、换写法（顺序号、不写注释、子程序）：刀路相同"""
    if post == "style":
        post = posts_dir("style", sequence={"enabled": True, "start": 5, "step": 5}, comments="none", subprograms=True)
    a = _mill("fanuc")["release"]["text"]
    b = _mill(post)["release"]["text"]
    r = progdiff.compare(a, b, VMC)
    assert r["same"], progdiff.report(r)
    assert "刀路相同" in progdiff.report(r) and "identical" in progdiff.report(r, "en")

def test_lathe_same_path_with_cycles_and_sequence(posts_dir):  # noqa: F811
    """车：固定循环、顺序号（G71 P / Q 改号）换成展开写法，刀路相同"""
    cid = posts_dir("tseq", sequence={"enabled": True}, cycles={"turn": True})
    for pa, pb in zip(_turn("fanuc"), _turn(cid), strict=True):
        r = progdiff.compare(pa["release"]["text"], pb["release"]["text"], LATHE)
        assert r["same"], progdiff.report(r)


def test_changed_coordinate_reported_at_line():
    a = _mill("fanuc")["release"]["text"]
    b = a.replace("X70.123", "X70.5")
    r = progdiff.compare(a, b, VMC)
    ln = _line(a, "X70.123")
    assert not r["same"] and len(r["hunks"]) >= 1
    h = r["hunks"][0]
    assert h["kind"] == "changed" and h["first"]["line_a"] == ln and h["first"]["line_b"] == ln
    assert h["max_dev_mm"] == pytest.approx(0.377, abs=1e-6)
    assert f"行 {ln}" in progdiff.report(r)


def test_feed_and_spindle_change():
    a = _mill("fanuc")["release"]["text"]
    b = a.replace("F600.1", "F650.0").replace("S2200", "S2500")
    r = progdiff.compare(a, b, VMC)
    assert not r["hunks"]
    feeds = [s for s in r["speeds"] if s["what"] == "feed"]
    spins = [s for s in r["speeds"] if s["what"] == "spindle"]
    assert feeds and feeds[0]["tool"] == 1 and feeds[0]["a"] == pytest.approx(600.1) and feeds[0]["b"] == 650.0
    assert feeds[0]["lines_a"][0] == _line(a, "F600.1")
    assert spins and all(s["tool"] == 4 for s in spins) and spins[0]["a"] == ("rpm", 2200.0) and spins[0]["b"] == ("rpm", 2500.0)
    assert r["time"]["cut_s"]["diff"] < 0
    t = progdiff.report(r)
    assert "F600.1 → F650" in t and "S2200 → S2500" in t


def test_tool_swapped_and_op_added():
    """换一把刀（T4 → T6）、加一道工序（再开一条槽）"""
    prog = _mill_prog()
    a = cam.run({"mode": "program", "machine": "EX-VMC", "program": prog, "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": MSIM_MILL, "post": "fanuc"})["data"]["programs"][0]["release"]["text"]
    p2 = copy.deepcopy(prog)
    p2["ops"][1]["tool"]["n"] = 6
    extra = copy.deepcopy(p2["ops"][0])
    for mv in extra["moves"]:
        mv["y"] = 15
    p2["ops"].append(extra)
    ms = copy.deepcopy(MSIM_MILL)
    ms["tools"]["6"] = {"tool": "DR8.5", "length_mm": 140}
    b = cam.run({"mode": "program", "machine": "EX-VMC", "program": p2, "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": ms, "post": "fanuc"})["data"]["programs"][0]["release"]["text"]
    r = progdiff.compare(a, b, VMC)
    assert r["tools"]["added"] == [6] and r["tools"]["removed"] == [4]
    added = [h for h in r["hunks"] if h["kind"] == "added"]
    assert any(1 in h["tools"] and h["lines_b"][0] > _line(b, "T5 M06") for h in added)
    assert r["time"]["total_s"]["diff"] > 0
    t = progdiff.report(r)
    assert "新版加了：T6" in t and "新版去了：T4" in t and "同样的刀路换了刀 T4 → T6" in t
    assert r["tools"]["a"] == [1, 4, 5] and r["tools"]["b"] == [1, 6, 5, 1]

def test_detect_and_cli(tmp_path):
    a = _mill("fanuc")["release"]["text"]
    h = _mill("heidenhain")["release"]["text"]
    s = _mill("siemens")["release"]["text"]
    assert progdiff.detect(a) == "fanuc" and progdiff.detect(h) == "heidenhain" and progdiff.detect(s) == "siemens"
    (tmp_path / "a.nc").write_text(a, encoding="utf-8")
    (tmp_path / "b.nc").write_text(h, encoding="utf-8")
    assert progdiff.main([str(tmp_path / "a.nc"), str(tmp_path / "b.nc"), "--machine", "EX-VMC"]) == 0
