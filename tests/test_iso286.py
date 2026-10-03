"""ISO 286 公差带反查（ADR-0044）。数值取自 ISO 286-2 表格。"""

import pytest

from ingest import iso286


@pytest.mark.parametrize(("d", "u", "lo", "hole", "zone"), [
    (8, 0, -0.009, False, "h6"),      # 安川 SGM7J-01A 轴径 8
    (14, 0, -0.011, False, "h6"),
    (19, 0, -0.013, False, "h6"),     # SGM7J-08A 轴径 19
    (30, 0, -0.021, False, "h7"),     # 止口 30 0 -0.021
    (25, 0.015, 0.002, False, "k6"),
    (40, -0.009, -0.025, False, "g6"),
    (10, 0.007, -0.002, False, "j6"),
    (20, 0.0065, -0.0065, False, "js6"),
    (20, 0.021, 0, True, "H7"),
    (12, 0.027, 0, True, "H8"),
])
def test_match(d, u, lo, hole, zone):
    assert iso286.match(d, u, lo, hole=hole) == zone


@pytest.mark.parametrize(("d", "u", "lo"), [(8, 0, -0.010), (2, 0, -0.006), (120, 0, -0.022), (8, 0.0004, -0.009)])
def test_no_match(d, u, lo):
    assert iso286.match(d, u, lo, hole=False) is None
