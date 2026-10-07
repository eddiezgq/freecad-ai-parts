# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：机构的动力学模型（MJCF 生成、耦合函数、默认参数）只留一份，在 analysis/mbd/mechanisms.py。
这里另有工厂才用的：连杆构件的 STEP（送去有限元，第 12 轮 D6）。"""
import math  # noqa: F401

from analysis.mbd.mechanisms import *  # noqa: F401,F403
from analysis.mbd.mechanisms import (  # noqa: F401
    DEFAULTS, DRIVER, LABELS, NAMES, cam_lift, coupling_fn, four_bar_solve, geneva_wheel_angle, initial, mjcf, params,
    prepare_setup, ratchet_state, ratio, slider_crank_x,
)


# ---------------------------------------------------------------- 构件 STEP（送去有限元，第 12 轮 D6）
STEP_MEMBERS = {"C-LNK-4BAR": {"crank": "crank_m", "coupler": "coupler_m", "rocker": "rocker_m"},
                "C-LNK-SLIDER": {"crank": "crank_m", "rod": "rod_m"}}


def member_step(mid, member, given=None):
    """连杆类构件：两端半圆头的扁杆，两端销孔（孔径 = 0.5 倍杆宽）。构件坐标：A 销孔在原点、B 销孔在 +X（米 → STEP 用毫米），
    厚度沿 Y——与动力学模型的构件坐标一致，铰点受力可以直接加到孔面上"""
    import os
    import tempfile
    import build123d as bd
    p = params(mid, given)
    if member not in STEP_MEMBERS.get(mid, {}):
        raise ValueError("“{}”的“{}”不是杆件，不能送去有限元".format(NAMES.get(mid, mid), member))
    L = p[STEP_MEMBERS[mid][member]] * 1000
    w, t = p["link_width_m"] * 1000, p["link_thickness_m"] * 1000
    with bd.BuildPart() as part:
        with bd.BuildSketch(bd.Plane.XZ):                 # XZ 平面：草图 x → 世界 X，草图 y → 世界 Z
            with bd.Locations((L / 2, 0)):
                bd.SlotCenterToCenter(L, w)
            with bd.Locations((0, 0), (L, 0)):
                bd.Circle(w * 0.25, mode=bd.Mode.SUBTRACT)
        bd.extrude(amount=t / 2, both=True)
    shape = part.part
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "m.step")
        bd.export_step(shape, f)
        return open(f, "rb").read()


def member_force_channel(mid, member):
    """杆件 B 端（远端销孔）受的力取自哪个反力通道、取正还是取反：
    主动的曲柄 B 端带着下一根杆，受力 = −（下一根杆从曲柄受的力）；其他杆 B 端受力 ≈ −A 端受力（二力杆，略去惯性和自重）"""
    if member not in STEP_MEMBERS.get(mid, {}):
        raise ValueError("“{}”的“{}”不是杆件，不能送去有限元".format(NAMES.get(mid, mid), member))
    if member == "crank":
        return {"C-LNK-4BAR": "coupler", "C-LNK-SLIDER": "rod"}[mid]
    return member
