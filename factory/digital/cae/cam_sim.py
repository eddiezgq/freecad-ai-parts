# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：G 代码读取、加工时间、仿真与检查只留一份，在 analysis/cam/sim.py（机床参数按字典传入）。
工厂按机床编号（cae/cam_post.py 的 MACHINES）调用，这里查表后转交。"""
from analysis.cam import sim as _S
from analysis.cam.sim import WORD, _arc, _seg_points, _strip, simulate_mill, simulate_turn  # noqa: F401
from cae.cam_post import MACHINES


def _m(machine):
    return MACHINES[machine] if isinstance(machine, str) else machine


def parse(text, machine):
    return _S.parse(text, _m(machine))


def _rpm(mv, x_diam, machine):
    return _S._rpm(mv, x_diam, _m(machine))


def move_time(mv, machine, lathe):
    return _S.move_time(mv, _m(machine), lathe)


def timing(parsed, machine):
    return _S.timing(parsed, _m(machine))


def machine_checks(parsed, machine):
    return _S.machine_checks(parsed, _m(machine))


def run(text, machine, stock, tools, target=None):
    """读程序 → 机床检查 → 时间 → 仿真，一次做完"""
    p = parse(text, machine)
    checks = machine_checks(p, machine)
    tm = timing(p, machine)
    sim = simulate_turn(p, stock, tools, target) if p["lathe"] else simulate_mill(p, stock, tools, target)
    return {"parsed": p, "checks": checks + sim["issues"], "time": tm, "sim": sim}
