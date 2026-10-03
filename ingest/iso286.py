"""ISO 286-1/-2 公差带查表（ADR-0044）：由名义直径与上、下偏差反查轴或孔的公差带。纯函数、只用标准库。

只收常用的公差带，尺寸 3–80 mm；查不到时返回 None，不猜。偏差单位 µm，按 ISO 286-2 表格。
"""

from __future__ import annotations

# 名义尺寸分段：大于下限、不大于上限（mm）
_RANGES = ((3, 6), (6, 10), (10, 18), (18, 30), (30, 50), (50, 80))
_IT = {  # 标准公差（µm）
    5: (5, 6, 8, 9, 11, 13),
    6: (8, 9, 11, 13, 16, 19),
    7: (12, 15, 18, 21, 25, 30),
    8: (18, 22, 27, 33, 39, 46),
}
# 轴：基本偏差（µm），g、h 为上偏差 es，k、m 为下偏差 ei
_SHAFT_ES = {"g": (-4, -5, -6, -7, -9, -10), "h": (0, 0, 0, 0, 0, 0)}
_SHAFT_EI = {"k": (1, 1, 1, 2, 2, 2), "m": (4, 6, 7, 8, 9, 11)}
_J6 = ((6, -2), (7, -2), (8, -3), (9, -4), (11, -5), (12, -7))  # j6 的 (es, ei)
SHAFT_ZONES = ("g6", "h5", "h6", "h7", "js6", "j6", "k6", "m6")
HOLE_ZONES = ("H6", "H7", "H8", "JS7")


def _range_index(d_mm: float) -> int | None:
    for i, (lo, hi) in enumerate(_RANGES):
        if lo < d_mm <= hi:
            return i
    return None


def deviations(zone: str, d_mm: float) -> tuple[float, float] | None:
    """公差带在名义直径处的（上偏差, 下偏差），µm；不支持时返回 None。"""
    i = _range_index(d_mm)
    if i is None:
        return None
    letter, grade = zone.rstrip("0123456789"), int(zone[len(zone.rstrip("0123456789")):])
    it = _IT.get(grade)
    if it is None:
        return None
    t = it[i]
    if letter in _SHAFT_ES:
        es = _SHAFT_ES[letter][i]
        return es, es - t
    if letter in _SHAFT_EI:
        ei = _SHAFT_EI[letter][i]
        return ei + t, ei
    if letter == "j" and grade == 6:
        return _J6[i]
    if letter in ("js", "JS"):
        return t / 2, -t / 2
    if letter == "H":
        return t, 0
    return None


def match(d_mm: float, upper_mm: float, lower_mm: float, *, hole: bool) -> str | None:
    """上、下偏差（mm）恰好对应一个常用公差带时返回它（如 8、0、-0.009 → h6）；对应不上或不止一个时返回 None。"""
    got = (upper_mm * 1000, lower_mm * 1000)

    def same(dev):
        return dev is not None and abs(dev[0] - got[0]) < 0.05 and abs(dev[1] - got[1]) < 0.05

    hits = [z for z in (HOLE_ZONES if hole else SHAFT_ZONES) if same(deviations(z, d_mm))]
    return hits[0] if len(hits) == 1 else None
