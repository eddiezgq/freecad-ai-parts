"""车刀刀杆 ISO 5608（ADR-0106 Q2 第 3 步、ADR-0107）：代号解析、刀杆外形、整机仿真里刀杆撞卡爪。"""

import pytest

from analysis import cam
from analysis.cam import holders as HD
from tests.verification import record_verdict


def test_parse_iso5608():
    p = HD.parse("PCLNR 2525 M 12")
    assert (p["clamp"], p["insert_shape"], p["style"], p["clearance"], p["hand"]) == ("P", "C", "L", "N", "R")
    assert (p["h_mm"], p["b_mm"], p["l1_mm"], p["edge_mm"]) == (25, 25, 150, 12)
    q = HD.parse("svjbl2020k16-x")
    assert (q["hand"], q["h_mm"], q["b_mm"], q["l1_mm"], q["edge_mm"], q["extra"]) == ("L", 20, 20, 125, 16, "-X")


@pytest.mark.parametrize("bad", ["PCLN 2525 M 12", "PCLNR 25 M 12", "刀杆", "PCLNR 2525 X 12"])
def test_parse_rejects(bad):
    with pytest.raises(HD.HolderError):
        HD.parse(bad)


def test_boxes_by_hand():
    bx, notes = HD.boxes({"iso5608": "PCLNR 2525 M 12", "f_mm": 32})
    assert bx == [[12.0, -25.0, 7.0, 150.0, 0.0, 32.0]]          # 右手刀：刀杆在刀尖 +Z 一侧 [f − b, f]
    assert "刀头" in notes[0]
    bx, _ = HD.boxes({"iso5608": "PCLNL 2525 M 12", "f_mm": 32})
    assert bx == [[12.0, -25.0, -32.0, 150.0, 0.0, -7.0]]
    bx, notes = HD.boxes({"iso5608": "PCLNR 2525 M 12"})
    assert bx == [] and "没写刀尖偏距 f" in notes[0]


def _lathe(fixtures, tool="TR-CNMG"):
    setup = {"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60]], "chamfer_mm": 1,
             "machine_sim": {"tools": {"1": {"tool": tool}, "2": {"tool": tool}}, "fixtures": fixtures}}
    r = cam.run(setup)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"]


def _quill(z0):
    return [{"id": "quill", "name": "尾座套筒", "cylinder_mm": {"p0": [0, 0, z0], "p1": [0, 0, 300], "r": 20}}]


def test_shank_hits_tailstock_quill():
    """右手刀 PCLNR 2525 M 12、f = 32：刀杆在刀尖 +Z 一侧 7 ~ 32 mm、离轴至少（刀尖半径 + 12）。
    尾座套筒 Ø40 从 Z15 起：车端面车到中心时刀尖碰不到套筒，刀杆碰；套筒退到 Z45 就碰不到。"""
    errs = [c["text"] for c in _lathe(_quill(15))[0]["checks"] if c["level"] == "error"]       # 右端（第一次装夹）
    record_verdict(("车刀刀杆撞尾座套筒必须报出", "turning holder into tailstock quill must be reported"),
                   "fail" if any("刀杆碰到夹具“尾座套筒”" in e for e in errs) else "pass", "fail")
    assert any("刀杆碰到夹具“尾座套筒”" in e for e in errs), errs
    assert not any("刀具刃部碰到夹具“尾座套筒”" in e for e in errs)
    progs = _lathe(_quill(45))
    assert not [c for p in progs for c in p["checks"] if c["level"] == "error"]
    unk = [c["text"] for p in progs for c in p["checks"] if c["level"] == "unknown"]
    assert any("刀头外形各家不同" in u for u in unk)


def test_missing_f_is_unknown():
    unk = [c["text"] for p in _lathe(_quill(45), "TR-VNMG") for c in p["checks"] if c["level"] == "unknown"]
    assert any("没写刀尖偏距 f" in u for u in unk)
