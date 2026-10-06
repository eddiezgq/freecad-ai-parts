# -*- coding: utf-8 -*-
"""车间平面布置（米）。仿真车间算 AGV 路程、3D 车间摆设备、看板画平面图都用这一份。"""

# 单元: (x_m, y_m, 宽_m, 深_m)
LAYOUT = {
    "store-01":  (3, 4, 4, 5),
    "saw-01":    (10, 4, 4, 2.5),
    "cnc-l01-a": (17, 4, 4, 2.2),
    "cnc-l01-b": (24, 4, 4, 2.2),
    "key-01":    (31, 4, 3, 2.2),
    "ht-01":     (17, 13, 5, 4),
    "grd-01":    (31, 13, 4.5, 2.2),
    "qc-01":     (38, 13, 4, 3),
    "vmc-01":    (10, 22, 3.5, 3),
    "hmc-01":    (17, 22, 4.5, 3.5),
    "hob-01":    (24, 22, 3.5, 2.5),
    "asm-01":    (31, 22, 5, 3),
    "test-01":   (38, 22, 3.5, 2.5),
    "store-02":  (45, 22, 4, 5),
}
FLOOR = (50, 28)        # 车间长、宽
AGV_HOME = {"agv-01": (7, 9), "agv-02": (7, 18.5)}
AISLES = (9.0, 18.5)    # 两条横向主通道；左侧 x=7 有一条纵向通道把它们连起来
CROSS_X = 7.0


def dock(unit):
    """设备的上下料点：设备靠通道一侧。"""
    x, y, _, d = LAYOUT[unit]
    return (x, y + d / 2 + 1.0) if y < AISLES[0] or AISLES[0] < y < AISLES[1] and y < 13.5 else (x, y - d / 2 - 1.0)


def _aisle(p):
    return min(AISLES, key=lambda a: abs(a - p[1]))


def route(a, b):
    """从点 a 到点 b 的折线：先进最近的通道，沿通道（必要时经左侧纵向通道换道）走到目标，再进站。"""
    a0, a1 = _aisle(a), _aisle(b)
    pts = [a, (a[0], a0)]
    if a0 != a1:
        pts += [(CROSS_X, a0), (CROSS_X, a1)]
    pts += [(b[0], a1), b]
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) > 1e-6 or abs(p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    return out


def length(path):
    return sum(((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5 for p, q in zip(path, path[1:]))


def point_at(path, dist):
    """沿折线走 dist 米后的位置和朝向（度）。"""
    import math
    for p, q in zip(path, path[1:]):
        seg = ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5
        heading = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
        if dist <= seg or q == path[-1]:
            f = 0 if seg == 0 else min(1.0, dist / seg)
            return (p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f), heading
        dist -= seg
    return path[-1], 0.0
