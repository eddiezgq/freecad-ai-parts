"""问渠CAM C1 第 4 步：后处理 FANUC / 西门子 / 广数与安全底线（ADR-0104 第 2、4 节）。"""

from __future__ import annotations

import pytest

from analysis import cam
from analysis.cam import machines, postproc

LT = {"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60], [35, 25], [24, 30]], "chamfer_mm": 1,
      "grooves": [{"z": -27, "width": 3, "d": 20}], "threads": [{"z_start": 0, "z_end": -26, "d": 24, "pitch": 1.5}],
      "bore": {"segments": [[16, 20], [12, 15]], "drill_d": 10},
      "machine_sim": {"tools": {str(i): {"tool": "TR-CNMG"} for i in range(1, 7)}}}
ML = {"mode": "mill", "machine": "EX-VMC", "stock": {"box": [0, 0, 100, 60], "height": 40},
      "features": [{"type": "pocket", "rect": [20, 15, 80, 45], "corner_r": 6, "depth": 8, "tool_d": 10},
                   {"type": "holes", "d": 8.5, "points": [[10, 10], [90, 10], [90, 50]], "depth": 30, "tool_d": 8.5}],
      "machine_sim": {"work_offset_mm": [0, 0, 40], "tools": {"1": {"tool": "EM10", "length_mm": 120},
                                                              "2": {"tool": "DR8.5", "length_mm": 140}}}}


def _progs(setup):
    r = cam.run(setup)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"]


@pytest.mark.parametrize("ctl", ["fanuc", "siemens", "gsk"])
def test_lathe_posts_reproduce_simulated_path(ctl):
    """每种系统的程序回读后，与整机仿真用的刀路逐段一致（不一致 release 就是 None）"""
    for p in _progs({**LT, "post": ctl}):
        rel = p["release"]
        assert rel and rel["controller"] == ctl and rel["verified"] is False
        back = postproc.to_fanuc(rel["text"], ctl, True)
        assert cam._same_path(p["gcode"], back, machines.get("EX-LATHE"))
        t = rel["text"]
        assert rel["fingerprint"] == p["machine_sim"]["fingerprint"] and rel["fingerprint"] in t
        right = p["side"] == "right"                                   # 螺纹在第一次装夹
        if ctl == "siemens":
            assert "首件须空运行、单段试切确认" in t and "后处理未经实机验证" in t and "LIMS=" in t
            assert ("G33 Z-26.0 K1.5" in t) == right
        else:
            assert t.isascii() and postproc.FIRST_PART_EN in t and "NOT VERIFIED" in t
            assert ("G32 Z-26.0 F1.5" in t) == right
        if ctl == "gsk":
            assert "G96" not in t and "G50" not in t           # 广数一律 G97
        assert any("还没在实机上验证过" in c["text"] for c in p["checks"] if c["level"] == "warn")


@pytest.mark.parametrize("ctl", ["fanuc", "siemens"])
@pytest.mark.parametrize("depth", [30, 20], ids=["peck-G83", "single-G81"])
def test_mill_posts_reproduce_simulated_path_with_expanded_drilling(ctl, depth):
    feats = [ML["features"][0], {**ML["features"][1], "depth": depth}]   # 深 30 > 3d 啄钻；深 20 一次钻到底
    p = _progs({**ML, "features": feats, "post": ctl})[0]
    rel = p["release"]
    assert rel, [c["text"] for c in p["checks"]]
    assert "G81" not in rel["text"] and "G83" not in rel["text"]       # 钻孔展开成 G00 / G01
    assert cam._same_path(p["gcode"], postproc.to_fanuc(rel["text"], ctl, False), machines.get("EX-VMC"))


def test_no_release_without_or_with_failed_machine_sim():
    p = _progs({**{k: v for k, v in LT.items() if k != "machine_sim"}, "post": "fanuc"})[0]
    assert p["release"] is None and any("没有跑整机仿真" in c["text"] for c in p["checks"])
    bad = {**ML, "post": "fanuc", "machine_sim": {**ML["machine_sim"],
                                                  "fixtures": [{"id": "c", "name": "压板", "box_mm": [25, 10, 0, 35, 25, 12]}]}}
    p = _progs(bad)[0]
    assert p["release"] is None and p["gcode"] is None
    p = _progs({**ML, "post": "gsk"})[0]                                 # 广数没有铣床后处理
    assert p["release"] is None and any("没有 'gsk' 的铣床后处理" in c["text"] for c in p["checks"])


def test_render_guards():
    m = machines.get("EX-LATHE")
    prog = {"number": 1, "ops": [{"tool": {"n": 1}, "spindle": {"rpm": 9000},
                                  "moves": [{"t": "rapid", "x": 30.0, "z": 2.0}, {"t": "feed", "x": 30.0, "z": -10.0, "f": 0.2}]}]}
    ok = {"status": "pass", "fingerprint": "0" * 16}
    with pytest.raises(postproc.ReleaseError, match="超过机床最高转速"):
        postproc.render(prog, m, "fanuc", ok)
    with pytest.raises(postproc.ReleaseError, match="没有跑整机仿真"):
        postproc.render(prog, m, "fanuc", None)
    with pytest.raises(postproc.ReleaseError, match="不通过"):
        postproc.render(prog, m, "fanuc", {"status": "error", "fingerprint": "x"})
    prog["ops"][0]["spindle"]["rpm"] = 1000
    text = postproc.render(prog, m, "fanuc", ok)["text"]
    # 改动一个坐标，回读比对就对不上
    assert not cam._same_path(text, text.replace("Z-10.0", "Z-10.5"), m)
    assert cam._same_path(text, text, m)
