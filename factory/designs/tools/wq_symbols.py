# -*- coding: utf-8 -*-
"""第 98 轮：工程自带符号库 ../libs/wq.kicad_sym——编码器接口芯片 WQ-ENCIF（第 92 轮）的原理图符号，引脚按细则 B-3。
封装用 KiCad 官方库的 QFN-16 3×3 mm。用法：python3 wq_symbols.py（产物入库，逐字可复现）。示例设计，未流片。
第 159 轮 159d1 加平缝机控制器 CTRL-LS 用的三个：升压电感 L_PFC、反激变压器 Transformer_FLY3（一初级三次级，共地）、
隔离电源 B0505S（KiCad 官方库没有这几样；磁性元件是定制件，封装 159d2 定）。"""
import os

from sexp import Sym, dump

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "libs", "wq.kicad_sym")
FP = "Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm"
G = 2.54
# (编号, 名字, 类型, 边, 位置序号)
PINS = [("1", "ENC_A", "input", "L", 0), ("2", "ENC_B", "input", "L", 1), ("3", "ENC_Z", "input", "L", 2),
        ("5", "CLK", "input", "L", 4), ("6", "RST_N", "input", "L", 5),
        ("9", "CS_N", "input", "R", 0), ("10", "SCLK", "input", "R", 1), ("11", "MOSI", "input", "R", 2), ("12", "MISO", "output", "R", 3),
        ("15", "NC", "no_connect", "R", 5), ("16", "NC", "no_connect", "R", 6),
        ("7", "VCCD", "power_in", "T", -1), ("13", "VDDIO", "power_in", "T", 1),
        ("4", "GND", "power_in", "B", -2), ("8", "GND", "power_in", "B", -1), ("14", "GND", "power_in", "B", 0), ("17", "EP", "power_in", "B", 1)]


def eff(hide=False):
    return [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]] + ([Sym("hide")] if hide else [])


def pin(num, name, typ, side, k):
    x, y, a = {"L": (-12.7, 7.62 - k * G, 0), "R": (12.7, 7.62 - k * G, 180), "T": (k * G, 12.7, 270), "B": (k * G, -12.7, 90)}[side]
    return [Sym("pin"), Sym(typ), Sym("line"), [Sym("at"), round(x, 2), round(y, 2), a], [Sym("length"), 2.54],
            [Sym("name"), name, eff()], [Sym("number"), num, eff()]]


def box(name, ref, value, fp, desc, pins, w=7.62, h=None):
    """简单方框符号：pins = [(编号, 名字, 类型, 边 L/R, 第几格)]"""
    n = max([k for *_, k in pins] + [0]) + 1
    h = h or (n * G / 2 + G)
    body = [Sym("rectangle"), [Sym("start"), -w, round(h, 2)], [Sym("end"), w, round(-h, 2)],
            [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("default")]], [Sym("fill"), [Sym("type"), Sym("background")]]]
    pl = []
    for num, nm, typ, side, k in pins:
        x, a = (-(w + G), 0) if side == "L" else (w + G, 180)
        y = round(h - G - k * G, 2)
        pl.append([Sym("pin"), Sym(typ), Sym("line"), [Sym("at"), round(x, 2), y, a], [Sym("length"), 2.54],
                   [Sym("name"), nm, eff()], [Sym("number"), num, eff()]])
    return [Sym("symbol"), name, [Sym("pin_names"), [Sym("offset"), 1.016]], [Sym("in_bom"), Sym("yes")], [Sym("on_board"), Sym("yes")],
            [Sym("property"), "Reference", ref, [Sym("at"), 0, round(h + 1.27, 2), 0], eff()],
            [Sym("property"), "Value", value, [Sym("at"), 0, round(-h - 1.27, 2), 0], eff()],
            [Sym("property"), "Footprint", fp, [Sym("at"), 0, round(-h - 3.81, 2), 0], eff(True)],
            [Sym("property"), "Datasheet", "", [Sym("at"), 0, 0, 0], eff(True)],
            [Sym("property"), "ki_description", desc, [Sym("at"), 0, 0, 0], eff(True)],
            [Sym("symbol"), name + "_0_1", body], [Sym("symbol"), name + "_1_1"] + pl]


CTRL_LS = [
    box("L_PFC", "L", "L_PFC", "wq:Magnetics_TBD", "升压电感（平缝机控制器 CTRL-LS，定制件；磁芯 159d2 定）",
        [("1", "1", "passive", "L", 0), ("2", "2", "passive", "R", 0)], w=5.08, h=2.54),
    box("Transformer_FLY3", "T", "FLY3", "wq:Magnetics_TBD", "反激变压器：一初级（1 起、2 末）三次级（3/4、5/6、7/8），定制件",
        [("1", "P+", "passive", "L", 0), ("2", "P-", "passive", "L", 2), ("3", "S1+", "passive", "R", 0), ("4", "S1-", "passive", "R", 1),
         ("5", "S2+", "passive", "R", 2), ("6", "S2-", "passive", "R", 3), ("7", "S3+", "passive", "R", 4), ("8", "S3-", "passive", "R", 5)]),
    box("B0505S", "U", "B0505S", "wq:Converter_SIP4_B0505S", "隔离电源模块 5 V → 5 V 1 W（SIP-4：1 GND、2 Vin、3 0V、4 +Vo，待核对规格书）",
        [("2", "Vin", "power_in", "L", 0), ("1", "GND", "power_in", "L", 1), ("4", "+Vo", "power_out", "R", 0), ("3", "0V", "power_out", "R", 1)]),
]


def main():
    sym = [Sym("symbol"), "WQ-ENCIF", [Sym("pin_names"), [Sym("offset"), 1.016]], [Sym("in_bom"), Sym("yes")], [Sym("on_board"), Sym("yes")],
           [Sym("property"), "Reference", "U", [Sym("at"), 0, 15.24, 0], eff()],
           [Sym("property"), "Value", "WQ-ENCIF", [Sym("at"), 0, -15.24, 0], eff()],
           [Sym("property"), "Footprint", FP, [Sym("at"), 0, -17.78, 0], eff(True)],
           [Sym("property"), "Datasheet", "", [Sym("at"), 0, 0, 0], eff(True)],
           [Sym("property"), "ki_description", "编码器接口芯片（问渠第 92 轮示例设计，未流片）：A/B/Z 滤波、4 倍频计数、SPI 从机", [Sym("at"), 0, 0, 0], eff(True)],
           [Sym("symbol"), "WQ-ENCIF_0_1", [Sym("rectangle"), [Sym("start"), -10.16, 10.16], [Sym("end"), 10.16, -10.16],
                                          [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("default")]], [Sym("fill"), [Sym("type"), Sym("background")]]]],
           [Sym("symbol"), "WQ-ENCIF_1_1"] + [pin(*p) for p in PINS]]
    lib = [Sym("kicad_symbol_lib"), [Sym("version"), 20220914], [Sym("generator"), Sym("kicad_symbol_editor")], sym] + CTRL_LS
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(dump(lib) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
