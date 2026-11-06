# -*- coding: utf-8 -*-
"""仿真核对（第 104 轮）：有现成仿真例题的功能块，用数字工厂 cae/circuit.py 的网表和读数（.meas）跑 ngspice，
仿真读数和公式值对照，超出例题规定的容差判不通过。本机没有 ngspice 时判“未知”。

会启动 ngspice 子进程，所以不在纯函数的范围里（test_purity.py 不查本文件）；不联网、不调 AI。"""

from __future__ import annotations

import os
import shutil
import sys

from .blocks import SIM
from .blocks import common as c

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIGITAL = os.path.join(REPO, "factory", "digital")
VBUS_DEPENDENT = {"bus_input", "gate_drive"}  # 例题里母线电压写死的


def _circuit():
    if DIGITAL not in sys.path:
        sys.path.insert(0, DIGITAL)
    from cae import circuit

    return circuit


def params_for(btype, unit, spec):
    p = unit["params"]
    if btype == "current_sense":
        return {"rs_mohm": p["RS_MOHM"], "gain": p["GAIN"], "gbw_mhz": p["gbw_mhz"]}
    if btype == "gate_drive":
        return {"rg_ohm": p["RG_OHM"], "vdrv": p["VDRV"]}
    if btype == "bus_input":
        return {"c_uf": p["C_BUS_UF"]}
    if btype == "encoder":
        return {"r_ohm": p["ENC_R_OHM"], "c_pf": p["ENC_C_PF"], "rpm": p["rpm_max"]}
    return {}


def run(doc):
    """{单元类型: {"example": 例题名, "params": …, "rows": [判定], "note": …}}"""
    out = {}
    have = shutil.which("ngspice") is not None
    circuit = _circuit() if have else None
    for u in design_units(doc):
        key = SIM.get(u["type"])
        if not key:
            continue
        prm = params_for(u["type"], u, doc["spec"])
        entry = {"example": key, "params": prm, "rows": [], "note": ""}
        if not have:
            entry["note"] = "本机没有 ngspice，仿真核对判未知"
            entry["rows"] = [c.judge("sim", "仿真核对", None, None, status=c.UNKNOWN, note=entry["note"])]
        elif u["type"] in VBUS_DEPENDENT and circuit.BOARD["vbus"] != doc["spec"]["bus_voltage_v"]:
            entry["note"] = "例题按 {:g} V 母线写死，与本设计 {:g} V 不同，不拿来核对".format(
                circuit.BOARD["vbus"], doc["spec"]["bus_voltage_v"]
            )
            entry["rows"] = [c.judge("sim", "仿真核对", None, None, status=c.UNKNOWN, note=entry["note"])]
        else:
            r = circuit.simulate(key, prm)
            for row in r["compare"]:
                st = c.PASS if row["ok"] else (c.UNKNOWN if row["diff"] is None else c.FAIL)
                entry["rows"].append(
                    c.judge(
                        row["name"],
                        "仿真：" + row["label"],
                        row["formula"],
                        row["sim"],
                        row["unit"],
                        "要求列是公式值、实有列是仿真值，相差 ≤ {:g}%".format(100 * row["allow"]),
                        status=st,
                        note="" if row["diff"] is None else "相差 {:.2f}%".format(100 * row["diff"]),
                    )
                )
        out[u["type"]] = entry
    return out


def design_units(doc):
    from . import blocks

    return blocks.units(doc)
