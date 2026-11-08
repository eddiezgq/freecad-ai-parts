# -*- coding: utf-8 -*-
"""第 98 轮：关节驱动板 B 版（放上编码器接口芯片 WQ-ENCIF，设计对照，不投产）；第 110 轮加抱闸驱动。
B 版比 A 版只多细则 B-2 那几项、MCU 只改那几只引脚；A 版一字不动；B 版产物 DRC / DFM 干净；
第 106 轮起电路板厂在工业园（仿真）里试产 B 版：物料清单与设计的物料差一致。"""
import json
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DES = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(DES, "tools"))
import drv_joint as A  # noqa: E402
import drv_joint_b as B  # noqa: E402

NEW = {"U14", "Y2", "U15", "C57", "C58", "C59", "C60", "C61",
       "U16", "Q7", "D5", "R36", "R37", "R38", "C62", "J6",      # 第 110 轮：抱闸驱动
       "R39", "R40", "C63"}                                      # 第 114 轮：抱闸电流采样


def test_b_is_a_plus_chip():
    a = {p["ref"]: p for p in A.PARTS if not p["ref"].startswith("TP")}
    b = {p["ref"]: p for p in B.PARTS if not p["ref"].startswith("TP")}
    assert A.REV == "A" and B.REV == "B" and not A.B_CHANGES
    assert set(b) - set(a) == NEW and not set(a) - set(b)
    changed = {r for r in a if a[r] != b[r]}
    assert changed == {"U10"}                                    # 其余器件一字不动
    pa, pb = a["U10"]["pins"], b["U10"]["pins"]
    diff = {k: (pa.get(k), pb.get(k)) for k in set(pa) | set(pb) if pa.get(k) != pb.get(k)}
    assert diff == {"12": (None, "ENC_CS_N"), "13": (None, "ENC_SCK"), "14": ("ENC_A_F", "ENC_MISO"), "15": ("ENC_B_F", "ENC_MOSI"),
                    "16": ("ENC_Z_F", "BRK_ISEN"), "17": (None, "ENC_RST_N"), "43": (None, "BRK_PWM")}   # 第 110 轮：PB6 = TIM4_CH1
    u14 = b["U14"]["pins"]
    assert [u14[k] for k in ("1", "2", "3")] == ["ENC_A_F", "ENC_B_F", "ENC_Z_F"]               # 滤波后的 A/B/Z 进芯片
    assert {u14[k] for k in ("9", "10", "11", "12")} == {"ENC_CS_N", "ENC_SCK", "ENC_MOSI", "ENC_MISO"}
    assert u14["7"] == "+1V8" and u14["13"] == "+3V3" and b["U15"]["pins"]["5"] == "+1V8" and b["Y2"]["pins"]["3"] == "ENC_CLK"
    # 每个新网络都有测试点（ICT）
    tps = {p["pins"]["1"] for p in B.PARTS if p["ref"].startswith("TP")}
    assert {"+1V8", "ENC_CLK", "ENC_CS_N", "ENC_SCK", "ENC_MOSI", "ENC_MISO", "ENC_RST_N"} <= tps
    # 第 110 轮抱闸：MCU 没输出时线圈断电（下拉）；线圈接母线与 Q7 漏极，D5 反接在线圈两端续流
    assert b["R38"]["pins"] == {"1": "BRK_PWM", "2": "GND"} and b["U16"]["pins"]["6"] == "BRK_PWM"
    assert b["J6"]["pins"] == {"1": "VBUS", "2": "BRK_N"} and b["Q7"]["pins"]["5"] == "BRK_N" and b["D5"]["pins"] == {"1": "VBUS", "2": "BRK_N"}
    assert {"BRK_PWM", "BRK_G", "BRK_GD"} <= tps        # BRK_N 在接插件 J6 的通孔焊盘上就能扎
    # 第 114 轮：Q7 源极经 R39 0.5 Ω 接地，采样经 R40/C63 滤波进 PB0（16 脚）
    assert b["Q7"]["pins"]["1"] == "BRK_S" and b["R39"]["pins"] == {"1": "BRK_S", "2": "GND"} and b["U10"]["pins"]["16"] == "BRK_ISEN"


def test_b_outputs_clean():
    out = os.path.join(DES, "drv-joint-b", "out")
    dr = json.load(open(os.path.join(out, "drc.json"), encoding="utf-8"))
    df = json.load(open(os.path.join(out, "dfm.json"), encoding="utf-8"))
    d = json.load(open(os.path.join(out, "design.json"), encoding="utf-8"))
    assert dr["errors"] == 0 and dr["unconnected"] == 0 and df["pass"] and len(df["checks"]) == 10
    assert d["bom_delta"] == {"CAP-0402": 7, "CONN-SIG": 1, "DIO-SMD-100": 1, "IC-ENCIF": 1, "IC-GDRV-LS": 1, "IC-LDO18": 1,
                              "MOS-80V": 1, "OSC-50M": 1, "RES-0402": 4, "RES-0805": 1}   # 第 110 轮抱闸驱动、第 114 轮电流采样
    assert "不投产" in d["disclaimer"] and len(d["mcu_pins"]) == 7
    assert any(p["ref"] == "U14" and p["side"] == "B" for p in d["parts"])
    kp = os.path.join(DES, "drv-joint-b", "kicad")
    assert os.path.exists(os.path.join(kp, "wq.kicad_sym")) and os.path.exists(os.path.join(kp, "sym-lib-table"))


def test_a_untouched_and_b_bom_matches_design():
    """第 106 轮改：电路板厂在工业园（仿真）里试产 B 版。原来核对“清单里没有 B 版物料”（第 98 轮“不投产”的决定），
    现在核对 B 版贴片板的物料清单 = A 版 + B 版设计的物料差。"""
    a = json.load(open(os.path.join(DES, "drv-joint", "out", "design.json"), encoding="utf-8"))
    assert "changes" not in a and a["rev"] == "示例 A"
    plant = yaml.safe_load(open(os.path.join(os.path.dirname(DES), "plants", "wenquest-pcb.yaml"), encoding="utf-8"))
    boms = {x["item"]: dict((c, q) for c, q in x["components"]) for x in plant["boms"]}
    # 贴片板 + 后段（接插件在后段选择焊）合起来的物料差
    ga = dict(boms["SMT-DRV"]); gb = dict(boms["SMT-DRV-B"])
    for c, q in boms["DRV-JOINT"].items():
        ga[c] = ga.get(c, 0) + q
    for c, q in boms["DRV-JOINT-B"].items():
        gb[c] = gb.get(c, 0) + q
    delta = {k: gb.get(k, 0) - ga.get(k, 0) for k in set(ga) | set(gb) if gb.get(k, 0) != ga.get(k, 0) and k not in ("SMT-DRV", "SMT-DRV-B")}
    d = json.load(open(os.path.join(DES, "drv-joint-b", "out", "design.json"), encoding="utf-8"))
    assert delta == d["bom_delta"]
    items = {x["code"]: x for x in plant["items"]}
    assert items["IC-ENCIF"]["park_item"] == "WQ-ENCIF" and items["IC-ENCIF"]["pack"] == 34000
    assert plant["suppliers"][items["IC-ENCIF"]["supplier"]]["park"] == "wenquest-chip"
    assert boms["DRV-JOINT-B"]["SMT-DRV-B"] == 1
