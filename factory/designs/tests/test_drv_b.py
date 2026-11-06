# -*- coding: utf-8 -*-
"""第 98 轮：关节驱动板 B 版（放上编码器接口芯片 WQ-ENCIF，设计对照，不投产）。
B 版比 A 版只多细则 B-2 那几项、MCU 只改那几只引脚；A 版一字不动；B 版产物 DRC / DFM 干净；电路板厂不生产 B 版。"""
import json
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DES = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(DES, "tools"))
import drv_joint as A  # noqa: E402
import drv_joint_b as B  # noqa: E402

NEW = {"U14", "Y2", "U15", "C57", "C58", "C59", "C60", "C61"}


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
                    "16": ("ENC_Z_F", None), "17": (None, "ENC_RST_N")}
    u14 = b["U14"]["pins"]
    assert [u14[k] for k in ("1", "2", "3")] == ["ENC_A_F", "ENC_B_F", "ENC_Z_F"]               # 滤波后的 A/B/Z 进芯片
    assert {u14[k] for k in ("9", "10", "11", "12")} == {"ENC_CS_N", "ENC_SCK", "ENC_MOSI", "ENC_MISO"}
    assert u14["7"] == "+1V8" and u14["13"] == "+3V3" and b["U15"]["pins"]["5"] == "+1V8" and b["Y2"]["pins"]["3"] == "ENC_CLK"
    # 每个新网络都有测试点（ICT）
    tps = {p["pins"]["1"] for p in B.PARTS if p["ref"].startswith("TP")}
    assert {"+1V8", "ENC_CLK", "ENC_CS_N", "ENC_SCK", "ENC_MOSI", "ENC_MISO", "ENC_RST_N"} <= tps


def test_b_outputs_clean():
    out = os.path.join(DES, "drv-joint-b", "out")
    dr = json.load(open(os.path.join(out, "drc.json"), encoding="utf-8"))
    df = json.load(open(os.path.join(out, "dfm.json"), encoding="utf-8"))
    d = json.load(open(os.path.join(out, "design.json"), encoding="utf-8"))
    assert dr["errors"] == 0 and dr["unconnected"] == 0 and df["pass"] and len(df["checks"]) == 10
    assert d["bom_delta"] == {"CAP-0402": 5, "IC-ENCIF": 1, "IC-LDO18": 1, "OSC-50M": 1}
    assert "不投产" in d["disclaimer"] and len(d["mcu_pins"]) == 6
    assert any(p["ref"] == "U14" and p["side"] == "B" for p in d["parts"])
    kp = os.path.join(DES, "drv-joint-b", "kicad")
    assert os.path.exists(os.path.join(kp, "wq.kicad_sym")) and os.path.exists(os.path.join(kp, "sym-lib-table"))


def test_a_untouched_and_b_not_produced():
    a = json.load(open(os.path.join(DES, "drv-joint", "out", "design.json"), encoding="utf-8"))
    assert "changes" not in a and a["rev"] == "示例 A"
    plant = yaml.safe_load(open(os.path.join(os.path.dirname(DES), "plants", "wenquest-pcb.yaml"), encoding="utf-8"))
    text = json.dumps(plant, ensure_ascii=False)
    assert "IC-ENCIF" not in text and "OSC-50M" not in text and "IC-LDO18" not in text
