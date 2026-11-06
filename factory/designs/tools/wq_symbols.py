# -*- coding: utf-8 -*-
"""第 98 轮：工程自带符号库 ../libs/wq.kicad_sym——编码器接口芯片 WQ-ENCIF（第 92 轮）的原理图符号，引脚按细则 B-3。
封装用 KiCad 官方库的 QFN-16 3×3 mm。用法：python3 wq_symbols.py（产物入库，逐字可复现）。示例设计，未流片。"""
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
    lib = [Sym("kicad_symbol_lib"), [Sym("version"), 20220914], [Sym("generator"), Sym("kicad_symbol_editor")], sym]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(dump(lib) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
