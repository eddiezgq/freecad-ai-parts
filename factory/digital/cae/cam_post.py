# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：FANUC 风格后处理只留一份，在 analysis/cam/post.py（机床参数按字典传入）。
这里保留工厂的机床表（教学示意值，不是某台真实机床的参数；功率、效率与工艺规程 hub/process.py 一致）。"""
import datetime

from analysis.cam import post as _P
from analysis.cam.post import comment as _comment  # noqa: F401
from analysis.cam.post import num  # noqa: F401

MACHINES = {
    "CNC-L01": {"kind": "lathe", "name": "数控车床 CNC-L01", "max_rpm": 4000, "power_kw": 11.0, "eff": 0.8,
                "x": (-2.0, 320.0), "z": (-600.0, 250.0), "rapid": {"x": 12000.0, "z": 15000.0},
                "home": (200.0, 150.0), "tools": 8, "tool_change_s": 1.5},
    "KEY-01": {"kind": "mill", "name": "键槽铣床 KEY-01", "max_rpm": 3000, "power_kw": 4.0, "eff": 0.75,
               "x": (-250.0, 250.0), "y": (-100.0, 100.0), "z": (-150.0, 150.0),
               "rapid": {"x": 6000.0, "y": 6000.0, "z": 4000.0}, "tools": 1, "tool_change_s": 60.0},
    "VMC-01": {"kind": "mill", "name": "立式加工中心 VMC-01", "max_rpm": 8000, "power_kw": 15.0, "eff": 0.8,
               "x": (-400.0, 400.0), "y": (-250.0, 250.0), "z": (-400.0, 150.0),
               "rapid": {"x": 24000.0, "y": 24000.0, "z": 20000.0}, "tools": 24, "tool_change_s": 4.0},
    "HMC-01": {"kind": "mill", "name": "卧式加工中心 HMC-01", "max_rpm": 6000, "power_kw": 18.5, "eff": 0.8,
               "x": (-400.0, 400.0), "y": (-300.0, 300.0), "z": (-400.0, 200.0),
               "rapid": {"x": 30000.0, "y": 30000.0, "z": 30000.0}, "tools": 40, "tool_change_s": 5.0},
}


def machine_of(workstation):
    """“数控车床 CNC-L01” 或 “CNC-L01” → 机床编号"""
    for k in MACHINES:
        if workstation and k in workstation:
            return k
    return None


def _prog(prog):
    h = prog.get("header", {})
    return {**prog, "generator": "生成 问渠数控编程 {}".format(h.get("date") or datetime.date.today().isoformat())}


def header(prog, lines):
    _P._header(_prog(prog), MACHINES[prog["machine"]], lines)


def post_lathe(prog):
    """数控车：G18（ZX 平面）、X 直径编程、G99 每转进给、G96 恒线速 + G50 限速"""
    return _P.post_lathe(_prog(prog), MACHINES[prog["machine"]])


def post_mill(prog):
    """2.5 轴铣：G17、G90 绝对、G94 每分进给、G54、M06 换刀、G43 长度补偿、G81 / G83 钻孔循环"""
    return _P.post_mill(_prog(prog), MACHINES[prog["machine"]])


def post(prog):
    return post_lathe(prog) if MACHINES[prog["machine"]]["kind"] == "lathe" else post_mill(prog)
