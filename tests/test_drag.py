"""拖动回写的位姿换算（ADR-0049 第 3 条）。"""

from __future__ import annotations

import math

import pytest

from freecad_addon.core.drag import place_args

CUR = {"instance": "motor", "position_mm": [0, 0, 0], "rotation": {"axis": [0, 0, 1], "angle_deg": 0.0}}


def test_unchanged_pose_is_not_written_back():
    assert place_args("motor", (0, 0, 0), (0, 0, 1), 0.0, CUR) is None
    assert place_args("motor", (0, 0, 1e-6), (1, 0, 0), 0.0, CUR) is None  # 零转角时轴向无关


def test_moved_and_rotated_pose():
    out = place_args("motor", (10, 0, 5), (0, 0, 1), math.pi / 2, CUR)
    assert out == {"instance": "motor", "position_mm": [10.0, 0.0, 5.0], "rotation_axis": [0.0, 0.0, 1.0],
                   "rotation_deg": pytest.approx(90.0)}
    neg = place_args("motor", (0, 0, 0), (0, 0, 1), -math.pi / 2, CUR)
    assert neg["rotation_deg"] == pytest.approx(90.0) and neg["rotation_axis"] == [-0.0, -0.0, -1.0]
    assert place_args("motor", (0, 0, 0), (0, 0, 1), 0.1, None)["rotation_deg"] == pytest.approx(math.degrees(0.1))
