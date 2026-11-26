"""过孔不当运动副；螺栓穿两件过孔、两件端面贴合 → 螺栓连接（固定）；按候选算整体自由度。

《多体动力学》书第 39 章线索第 66 条（问渠 CAD 0.3.9 细则）：半径差上限 Ø20 以下恒为 0.5 mm，M8 螺栓在 Ø9 过孔里与两块板
各成转动副、两板之间无候选，两颗螺栓时整体 2 个自由度、冗余 4；轴穿过 Ø20.6 盖板过孔也成转动副。
"""
from analysis.mbd import mates as MT


def cyl(p, a, r, t, convex):
    return {"kind": "cylinder", "point": list(p), "axis": list(a), "radius": r, "t": list(t), "convex": convex}


def plane(p, n):
    return {"kind": "plane", "point": list(p), "normal": list(n), "area": 400.0}


def part(pid, faces, vol=1000.0):
    return {"id": pid, "label": pid, "volume_mm3": vol, "faces": faces}


def _plates(xs):
    # 两块 10 mm 厚的板沿 z 叠放，在 z = 10 贴合；每个螺栓位置一个 Ø9 过孔
    a = part("plateA", [plane((50, 0, 10), (0, 0, 1))] + [cyl((x, 0, 0), (0, 0, 1), 4.5, (0, 10), False) for x in xs], 20000)
    b = part("plateB", [plane((50, 0, 10), (0, 0, -1))] + [cyl((x, 0, 10), (0, 0, 1), 4.5, (0, 10), False) for x in xs], 18000)
    bolts = [part(f"bolt{k + 1}", [cyl((x, 0, -2), (0, 0, 1), 4.0, (0, 30), True)], 50) for k, x in enumerate(xs)]
    return [a, b, *bolts]


def test_two_bolts_rigid():
    parts = _plates([20, 80])
    found = MT.find_candidates(parts)
    types = {(c["part1"], c["part2"]): c["type"] for c in found["candidates"]}
    assert "revolute" not in types.values()
    assert types[("plateA", "plateB")] == "fixed"
    assert MT.mobility(parts, found)["dof"] == 0


def test_clearance_hole_alone_is_not_a_joint():
    cover = part("cover", [cyl((0, 0, 0), (1, 0, 0), 10.3, (0, 8), False)], 3000)     # Ø20.6 过孔
    shaft = part("shaft", [cyl((-50, 0, 0), (1, 0, 0), 10.0, (0, 120), True)])
    assert MT.find_candidates([cover, shaft])["candidates"] == []
    fit = part("hub", [cyl((0, 0, 0), (1, 0, 0), 10.01, (0, 8), False)], 3000)         # Ø20.02 配合
    assert [c["type"] for c in MT.find_candidates([fit, shaft])["candidates"]] == ["revolute"]


def test_local_dof_reported():
    frame = part("frame", [cyl((0, 0, 0), (0, 0, 1), 2.01, (0, 10), False)], 9000)
    pin = part("pin", [cyl((0, 0, 0), (0, 0, 1), 2.0, (0, 10), True)])
    found = MT.find_candidates([frame, pin])
    m = MT.mobility([frame, pin], found)
    assert m["dof"] == 1 and m["local"] == ["pin"]
