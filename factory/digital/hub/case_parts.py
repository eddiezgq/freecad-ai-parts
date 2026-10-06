# -*- coding: utf-8 -*-
"""教材案例件的第 1 版三维模型（第 11 轮《机械设计》第 33 章 F3）：RJ-201 协作机器人肩关节空心轴、LS-101 平缝机上轴。

还没有人发布新版本时，“仿真与分析”读入的就是这一版（与 SH-301 的第 1 版来自在线设计台默认参数同理）。
尺寸与教材 textbook/mechdesign/ch33/code/_rj.py、_ls.py 一致（33.10、33.11 节）；改尺寸要两边一起改。
"""
import functools
import os
import tempfile

# RJ-201：(外径, 长度, 名称)，内孔 Ø30 贯通；台阶内角 r 1。2026-10-04 按第 33.10 节修改后的结构：两个轴承装在连续的 Ø50 上
# （中间是隔套，不在本零件上），外端是花键（按小径 Ø42.75 简化成圆柱）和 M42×1.5 螺纹（按大径简化成圆柱）；
# 大臂法兰 RJ-202 是单独零件，靠花键传转矩。“仿真与分析”里扭矩加在花键段外圆上。
RJ_SEGS = [(70, 10, "减速器法兰"), (50, 16, "轴承位（内侧）"), (50, 24, "隔套段"), (50, 16, "轴承位（外侧）"),
           (42.75, 20, "花键段（按小径）"), (42, 10, "螺纹段 M42×1.5")]
RJ_BORE, RJ_FILLET = 30.0, 1.0
# LS-101：(直径, 长度, 名称)；台阶内角 r 0.5
LS_SEGS = [(10, 22, "针杆曲柄座"), (12, 10, "前轴承位"), (16, 215, "轴身"), (12, 10, "后轴承位"), (10, 40, "同步带轮、手轮、电机转子")]
LS_FILLET = 0.5
CASES = {"RJ-201": (RJ_SEGS, RJ_BORE, RJ_FILLET), "LS-101": (LS_SEGS, None, LS_FILLET)}


def _shaft(segs, bore, fillet):
    import build123d as bd
    z, s, steps = 0.0, None, []
    for k, (D, L, _) in enumerate(segs):
        c = bd.Pos(0, 0, z) * bd.Cylinder(D / 2, L, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
        s = c if s is None else s + c
        z += L
        if k + 1 < len(segs) and abs(segs[k + 1][0] - D) / 2 > 1.5 * (fillet or 0):   # 台阶够高才倒圆
            steps.append(z)
    s = s.clean()
    sel = []
    for zz in steps:
        es = [e for e in s.edges() if e.geom_type == bd.GeomType.CIRCLE and abs(e.center().Z - zz) < 1e-6]
        if len(es) == 2:
            sel.append(min(es, key=lambda e: e.radius))
    if fillet and sel:
        s = s.fillet(fillet, sel)
    if bore:
        s = s - bd.Pos(0, 0, -1) * bd.Cylinder(bore / 2, z + 2, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    p = os.path.join(tempfile.mkdtemp(), "part.step")
    bd.export_step(s, p)
    with open(p, "rb") as f:
        return f.read()


@functools.lru_cache(maxsize=4)
def step_bytes(item):
    """案例件第 1 版的 STEP；不是案例件返回 None"""
    if item not in CASES:
        return None
    return _shaft(*CASES[item])
