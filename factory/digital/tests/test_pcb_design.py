# -*- coding: utf-8 -*-
"""第 88 轮（电子 E4）：关节驱动板 DRV-JOINT 的 KiCad 设计与电路板厂清单、电路分析例题一致；提交的产物齐全、检查通过。
（产物由 factory/designs/tools/build.py 用 KiCad 生成；这里只读产物和设计描述，不需要 KiCad。）"""
import hashlib
import json
import os
import sys

import yaml

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
TOOLS = os.path.join(FAC, "designs", "tools")
OUT = os.path.join(FAC, "designs", "drv-joint", "out")
sys.path[:0] = [TOOLS, DIG]

import drv_joint as D  # noqa: E402


def _manifest():
    with open(os.path.join(FAC, "plants", "wenquest-pcb.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _bom(m, item):
    b = next(x for x in m["boms"] if x["item"] == item)
    return {c: q for c, q in b["components"]}


def test_bom_matches_plant_manifest():
    m = _manifest()
    design = D.bom_by_item()
    smt = {k: v for k, v in design.items() if k not in D.BACK_END_ITEMS}
    back = {k: v for k, v in design.items() if k in D.BACK_END_ITEMS}
    s = _bom(m, "SMT-DRV")
    assert {k: v for k, v in s.items() if k not in ("PCB-DRV", "PASTE-SAC305")} == smt
    assert s["PCB-DRV"] == 1
    fg = _bom(m, "DRV-JOINT")
    assert {k: v for k, v in fg.items() if k.startswith("CONN-")} == back and fg["SMT-DRV"] == 1
    codes = {i["code"]: i for i in m["items"]}
    for k in design:                                   # 设计用到的物料都在清单里；示例选型的芯片写了型号和“未经硬件验证”
        assert k in codes, k
    for k in ("IC-MCU-MC", "IC-GDRV", "IC-AMP", "IC-CAN", "IC-BUCK", "IC-LDO", "IC-RS485", "MOS-80V"):
        assert "示例选型" in codes[k]["name"] and "未经硬件验证" in codes[k]["name"], k


def test_values_match_circuit_examples():
    from cae import circuit as C
    p = {k: {x[0]: x[2] for x in C.EXAMPLES[k]["params"]} for k in ("sense", "gate", "bus", "encoder")}
    assert p["sense"]["rs_mohm"] == D.RS_MOHM and p["sense"]["gain"] == D.GAIN
    assert p["gate"]["rg_ohm"] == D.RG_OHM and p["gate"]["vdrv"] == D.VDRV
    assert p["bus"]["c_uf"] == D.C_BUS_UF
    assert p["encoder"]["r_ohm"] == D.ENC_R_OHM and p["encoder"]["c_pf"] == D.ENC_C_PF
    parts = {x["ref"]: x for x in D.PARTS}
    assert all(parts["R2{}".format(i)]["value"].startswith("2m") for i in (1, 2, 3))          # 2 mΩ
    assert all(parts["U{}".format(i)]["value"] == "INA240A1D" for i in (7, 8, 9))               # 增益 20 的型号
    assert all(parts["R{}".format(i)]["value"] == "10" for i in range(10, 16))                  # 栅极电阻 10 Ω
    assert parts["C1"]["value"].startswith("470u")
    assert all(parts["R3{}".format(i)]["value"] == "1k" for i in (1, 2, 3)) and all(parts["C5{}".format(i)]["value"] == "220p" for i in (0, 1, 2))


def test_design_connectivity():
    nets = D.nets()
    assert all(len(v) >= 2 for n, v in nets.items() if n not in D.NC_NETS)       # 每个网络至少连两个引脚
    assert len({p["ref"] for p in D.PARTS}) == len(D.PARTS)
    assert set(D.PLACEMENT) >= {p["ref"] for p in D.PARTS}
    # 开尔文采样：放大器输入经网络连接点接到采样电阻两端，不和大电流走同一根线
    for i, ph in enumerate("ABC"):
        assert ("U{}".format(7 + i), "8") in nets["SNSP_" + ph] and ("U{}".format(7 + i), "1") in nets["SNSN_" + ph]


def test_outputs_present_and_checks_pass():
    d = json.load(open(os.path.join(OUT, "design.json"), encoding="utf-8"))
    assert d["disclaimer"].startswith("示例设计")
    assert d["drc"]["errors"] == 0 and d["drc"]["unconnected"] == 0
    dfm = json.load(open(os.path.join(OUT, "dfm.json"), encoding="utf-8"))
    assert dfm["pass"] and {c["key"] for c in dfm["checks"]} >= {"track_width", "track_space", "drill", "annular", "mask_bridge", "edge",
                                                                  "spacing", "polarity", "ict", "current"}
    assert len(d["sheets"]) == 7 and all(s["svg"] for s in d["sheets"])
    for rel, h in d["files"].items():                  # 产物之间对得上（design.json 记的摘要 = 实际文件）
        with open(os.path.join(OUT, rel), "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest()[:16] == h, rel
    for f in ("gerber.zip", "kicad-project.zip", "bom.csv", "pos.csv", "drv-joint.step", "drv-joint.glb", "pcb/F_Cu.svg"):
        assert os.path.getsize(os.path.join(OUT, f)) > 100, f


def test_bom_csv_items():
    import csv
    rows = list(csv.DictReader(open(os.path.join(OUT, "bom.csv"), encoding="utf-8")))
    tot = {}
    for r in rows:
        tot[r["物料编号"]] = tot.get(r["物料编号"], 0) + int(r["数量"])
    assert tot == D.bom_by_item()
