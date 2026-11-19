"""问渠CAM Q3a 车削刀路（ADR-0106）：余量与分层、高度与进退刀；内孔仿形、端面槽、切断、内螺纹、锥螺纹、多头螺纹、固定循环。"""

import pytest

from analysis import cam
from analysis.cam import machines
from analysis.cam import paths as P
from analysis.cam import sim as S

LATHE = machines.get("EX-LATHE")
BASE = {"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60]], "chamfer_mm": 1}


def _moves(prog, title):
    return next(o for o in prog["ops"] if o["title"] == title)["moves"]


def test_clearance_retract_and_allowance_reach_the_path():
    """工序参数：安全距离 5、退刀 1、径向余量 0.8 → 快移到 Z5；粗车每层斜退 1；粗车最后一刀离成品 0.8"""
    ctx = cam.turn_context(BASE, LATHE)
    sc = ctx["sides"][1]                                   # 调头车 Ø30 段：毛坯 Ø44，要分层
    c = {**cam.turn_default_cut(BASE, sc, {"kind": "rough"}), "clear": 5.0, "retract": 1.0, "allow_r": 0.8}
    mv = cam.turn_build_op(ctx, sc, {"kind": "rough"}, c)["op"]["moves"]
    zs = [m["z"] for m in mv if m["t"] == "rapid"]
    assert max(zs) == pytest.approx(5.0)
    feeds = [m for m in mv if m["t"] == "feed"]
    assert any(abs(b["x"] - a["x"] - 2.0) < 1e-9 and abs(b["z"] - a["z"] - 1.0) < 1e-9 for a, b in zip(feeds, feeds[1:], strict=False))
    # 沿留余量轮廓的那一刀：Ø30 段车到 Ø31.6
    assert any(m["t"] == "feed" and m["x"] == pytest.approx(31.6) for m in mv)
    # 缺省时与以前一样
    c0 = cam.turn_default_cut(BASE, sc, {"kind": "rough"})
    mv0 = cam.turn_build_op(ctx, sc, {"kind": "rough"}, c0)["op"]["moves"]
    assert max(m["z"] for m in mv0 if m["t"] == "rapid") == pytest.approx(P.CLEAR)
