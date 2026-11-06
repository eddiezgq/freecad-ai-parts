# -*- coding: utf-8 -*-
"""整理 LibreLane 的结果：final/metrics.json 的要点、门级网表里各类标准单元个数、工具版本 → result.json（网页与验收用）。
用法：python3 collect.py RUNDIR OUTDIR [--check COMMITTED_RESULT_JSON]"""
import argparse
import collections
import glob
import json
import os
import re
import sys

KEYS = {
    "setup_ws_ns": ["timing__setup__ws", "timing__setup__ws__corner:nom_tt_025C_1v80"],
    "hold_ws_ns": ["timing__hold__ws", "timing__hold__ws__corner:nom_tt_025C_1v80"],
    "setup_tns_ns": ["timing__setup__tns"],
    "route_drc_errors": ["route__drc_errors"],
    "magic_drc_errors": ["magic__drc_error__count"],
    "klayout_drc_errors": ["klayout__drc_error__count"],
    "lvs_errors": ["design__lvs_error__count"],
    "antenna_violations": ["antenna__violating__nets", "route__antenna_violation__count"],
    "max_slew_violations": ["design__max_slew_violation__count"],
    "max_cap_violations": ["design__max_cap_violation__count"],
    "instances": ["design__instance__count"],
    "stdcells": ["design__instance__count__stdcell"],
    "die_area_um2": ["design__die__area"],
    "core_area_um2": ["design__core__area"],
    "stdcell_area_um2": ["design__instance__area__stdcell", "design__instance__area"],
    "utilization": ["design__instance__utilization"],
    "power_total_w": ["power__total"],
    "power_internal_w": ["power__internal__total"],
    "power_switching_w": ["power__switching__total"],
    "power_leakage_w": ["power__leakage__total"],
    "wire_length_um": ["route__wirelength"],
    "vias": ["route__vias"],
}
# 网表里的单元名 → 中文类别
KIND = [("dfrtp|dfstp|dfxtp|dfrbp|dfbbp|edfxtp|sdf", "触发器"), ("dlx|dlrtp", "锁存器"), ("fa_|ha_|maj3", "加法器单元"),
        ("xor|xnor", "异或"), ("mux", "选择器"), ("nand|nor|and|or|a2|a3|o2|o3|a21|o21|a22|o22|a31|o31|a32|o32|a41|o41|a211|o211|a221|o221|a311|o311|a2bb|o2bb", "与或门"),
        ("inv|clkinv", "反相器"), ("buf|clkbuf|dlygate|dlymetal", "缓冲器"), ("conb", "常数"),
        ("tapvpwrvgnd|tap_", "衬底接触"), ("decap", "去耦电容"), ("fill", "填充"), ("diode", "天线二极管")]


def metric(m, names):
    for n in names:
        if n in m:
            return m[n]
    return None


def kind_of(cell):
    base = cell.replace("sky130_fd_sc_hd__", "")
    for pat, k in KIND:
        if re.match(r"^(" + pat + ")", base):
            return k
    return "其他"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("out")
    ap.add_argument("--check")
    a = ap.parse_args()
    fin = os.path.join(a.run, "final")
    m = json.load(open(os.path.join(fin, "metrics.json")))
    res = {k: metric(m, v) for k, v in KEYS.items()}
    nl = (glob.glob(os.path.join(fin, "nl", "*.nl.v")) or [None])[0]
    cells = collections.Counter()
    if nl:
        for ln in open(nl):
            mm = re.match(r"\s*(sky130_fd_sc_hd__\w+)\s+\S+\s*\(", ln)
            if mm:
                cells[mm.group(1)] += 1
    kinds = collections.Counter()
    for c, n in cells.items():
        kinds[kind_of(c)] += n
    res["cells_by_kind"] = dict(sorted(kinds.items(), key=lambda x: -x[1]))
    res["cells_top"] = [[c.replace("sky130_fd_sc_hd__", ""), n] for c, n in cells.most_common(15)]
    res["flipflops"] = kinds.get("触发器", 0)
    logic = sum(n for k, n in kinds.items() if k not in ("衬底接触", "去耦电容", "填充", "天线二极管"))
    res["logic_cells"] = logic

    def zero(x):
        return x is not None and float(x) == 0
    res["clean"] = {
        "drc": zero(res["magic_drc_errors"]) and (res["klayout_drc_errors"] is None or zero(res["klayout_drc_errors"])),
        "lvs": zero(res["lvs_errors"]),
        "setup": res["setup_ws_ns"] is not None and float(res["setup_ws_ns"]) >= 0,
        "hold": res["hold_ws_ns"] is not None and float(res["hold_ws_ns"]) >= 0,
        "antenna": res["antenna_violations"] is None or zero(res["antenna_violations"]),
    }
    res["pass"] = all(res["clean"].values())
    res["clock_mhz"] = 50
    res["pdk"] = "sky130A / sky130_fd_sc_hd"
    res["image"] = os.environ.get("WQ_IMAGE", "")
    res["librelane"] = os.environ.get("WQ_LIBRELANE", "")
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False))
    if a.check:
        old = json.load(open(a.check, encoding="utf-8"))
        diff = [k for k in ("pass", "clean", "logic_cells", "flipflops", "cells_by_kind") if old.get(k) != res.get(k)]
        if diff:
            print("::error title=芯片版图与提交的不一致::" + "、".join(diff))
            return 1
    return 0 if res["pass"] else 2


if __name__ == "__main__":
    sys.exit(main())
