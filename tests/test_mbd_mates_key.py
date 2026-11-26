"""轴孔配合加键侧平面：转不动——有止推面为固定，否则为移动副。

《多体动力学》书第 39 章线索第 63 条（问渠 CAD 0.3.9 细则）：Ø20 轴、Ø20.02 毂孔，键侧两平面（法向 ±y）贴合，
原来给转动副（备选圆柱副），移动副不在选项里。
"""
import pytest

from analysis.mbd import mates as MT


def cyl(p, a, r, t, convex):
    return {"kind": "cylinder", "point": list(p), "axis": list(a), "radius": r, "t": list(t), "convex": convex}


def plane(p, n):
    return {"kind": "plane", "point": list(p), "normal": list(n), "area": 30.0}


def part(pid, faces, vol=1000.0):
    return {"id": pid, "label": pid, "volume_mm3": vol, "faces": faces}


def _shaft_hub(thrust=False):
    # 轴沿 x；键宽 6 mm：轴上键的两侧面在 y = ±3（法向朝外 ±y），毂键槽两侧面同位置、法向相反
    shaft = part("shaft", [cyl((0, 0, 0), (1, 0, 0), 10.0, (0, 100), True), plane((50, 3, 10), (0, 1, 0)),
                           plane((50, -3, 10), (0, -1, 0))] + ([plane((40, 0, 0), (1, 0, 0))] if thrust else []), 5000)
    hub = part("hub", [cyl((40, 0, 0), (1, 0, 0), 10.01, (0, 30), False), plane((60, 3, 10), (0, -1, 0)),
                       plane((60, -3, 10), (0, 1, 0))] + ([plane((40, 5, 5), (-1, 0, 0))] if thrust else []))
    return shaft, hub


def test_sliding_key_is_translational():
    (c,) = MT.find_candidates(list(_shaft_hub()))["candidates"]
    assert c["type"] == "translational" and abs(c["axis"][0]) == pytest.approx(1)
    assert "键" in c["evidence"]


def test_key_with_thrust_face_is_fixed():
    (c,) = MT.find_candidates(list(_shaft_hub(thrust=True)))["candidates"]
    assert c["type"] == "fixed"


def test_plain_pin_still_revolute():
    A = part("frame", [cyl((0, 0, 0), (1, 0, 0), 10.01, (0, 30), False)], 5000)
    B = part("pin", [cyl((0, 0, 0), (1, 0, 0), 10.0, (0, 30), True)])
    (c,) = MT.find_candidates([A, B])["candidates"]
    assert c["type"] == "revolute"
