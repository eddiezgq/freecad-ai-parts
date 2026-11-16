"""零件特征识别（ADR-0093 补充十一第 3 步）：在本仓库真实设计过的零件上，与人工标注的答案逐项核对；螺纹孔组用一块合成板。
不联网、不调用 LLM。"""

from __future__ import annotations

from pathlib import Path

import pytest

from assist.features import recognize
from examples.apps import common as C
from tests.test_fea_bench import _need_fea, _write

OUT = Path(__file__).resolve().parents[1] / "examples" / "apps" / "out"


def _lib():
    return list(C.library().all())


def _of(r, t):
    return [x for x in r["features"] if x["type"] == t]


def test_shoulder_hollow_shaft_rj201():
    """肩关节空心轴 RJ-201（《机械设计》33.10）：轴段 Ø70/Ø50/Ø42.75/Ø42，贯通内孔 Ø30，两端面，三处轴肩"""
    _need_fea()
    r = recognize(str(OUT / "cobot_joint" / "RJ-201.step"), _lib())
    assert sorted(x["diameter_mm"] for x in _of(r, "shaft_segment")) == [42.0, 42.75, 50.0, 70.0]
    bore = _of(r, "bore")
    assert [b["diameter_mm"] for b in bore] == [30.0] and bore[0]["length_mm"] == pytest.approx(96.0)
    assert len(_of(r, "end_face")) == 2 and len(_of(r, "shoulder")) == 3
    assert not _of(r, "keyway_or_flat") and not _of(r, "hole_pattern")


def test_lockstitch_shaft_two_bearing_seats_stay_separate():
    """平缝机上轴 LS-101：两处 Ø12 轴承位不连着，要分成两段"""
    _need_fea()
    r = recognize(str(OUT / "lockstitch" / "LS-101.step"), _lib())
    seg = sorted((x["diameter_mm"], x["length_mm"]) for x in _of(r, "shaft_segment"))
    assert seg == [(10.0, 22.0), (10.0, 40.0), (12.0, 10.0), (12.0, 10.0), (16.0, 215.0)]


def test_arm_upper_link_reducer_seats_match_library():
    """整臂大臂：两个减速器座的直径与零件库 CSF-32、CSF-25 的外形对上；铝管内孔 Ø82 不配任何外购件"""
    _need_fea()
    r = recognize(str(OUT / "cobot_arm" / "ARM-UPPER.step"), _lib())
    bores = {b["diameter_mm"]: b for b in _of(r, "bore")}
    assert set(bores) == {138.0, 107.0, 82.0}
    assert any("CSF-32-100-2UH" in m for m in bores[138.0]["fits"])
    assert any("CSF-25-100-2UH" in m for m in bores[107.0]["fits"])
    assert "fits" not in bores[82.0]
    assert {x["diameter_mm"] for x in _of(r, "shaft_segment")} == {150.0, 119.0, 90.0}


def test_bolt_circle_with_tapped_holes(tmp_path):
    """合成法兰板：8 × Ø5（M6 粗牙底孔 D − P = 5）在分布圆 Ø100 上，中心孔 Ø40；应认出孔组、分布圆、疑似 M6，中心孔不算螺纹"""
    _need_fea()
    import math

    def plate(o):
        p = o.addCylinder(0, 0, 0, 0, 0, 12, 70)
        tools = [(3, o.addCylinder(0, 0, -1, 0, 0, 14, 20))]
        tools += [(3, o.addCylinder(50 * math.cos(k * math.pi / 4), 50 * math.sin(k * math.pi / 4), -1, 0, 0, 14, 2.5))
                  for k in range(8)]
        o.cut([(3, p)], tools)
    r = recognize(_write(tmp_path / "flange.step", plate), _lib())
    pat = _of(r, "hole_pattern")
    assert len(pat) == 1 and pat[0]["count"] == 8 and pat[0]["pcd_mm"] == pytest.approx(100.0, abs=0.05)
    assert "M6" in pat[0]["text"] and "须人确认" in pat[0]["text"]
    center = next(b for b in _of(r, "bore") if b["diameter_mm"] == 40.0)
    assert "thread_suspect" not in center
