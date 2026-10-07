# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：运动与动力分析（MuJoCo 多体动力学）的核心只留一份，在 analysis/mbd/core.py。
设置与结果的格式同工厂原来的（内部 SI 单位）。"""
from analysis.mbd.core import *  # noqa: F401,F403
from analysis.mbd.core import (  # noqa: F401
    ANIM_HZ, MAX_DURATION_S, MAX_SAMPLE_HZ, Recorder, SetupError, _bid, _ids, _initial, _is_descendant, _jid, _run,
    _visual_group, build, drive_force, eq_force, gravity_torques, info, load_spec, profile, simulate,
)
