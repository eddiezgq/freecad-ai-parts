# -*- coding: utf-8 -*-
"""第 159 轮 159d2b：工程自带封装库 ../libs/wq.pretty——KiCad 官方库没有的两种封装（平缝机控制器 CTRL-LS 用）。

    python3 wq_footprints.py        # 产物入库，逐字可复现

- L_ETD59_Horizontal：升压电感（定制，磁芯 EPCOS ETD 59/31/22 + 骨架 B66398，计算书“按理论”选的）。
  骨架的钻孔图读不出数字，封装按理论定：外形按 KiCad 官方库 ETD29 卧式骨架封装（37.2 × 37.2 mm，磁芯 29 mm）同比例放大到 59 mm 磁芯
  （× 2.03 ≈ 75.5 × 75.5 mm），引出两根线（起、末），间距 50.8 mm、孔 2.0 mm（利兹线 2 mm² 加焊锡）。绕制厂按这个封装做引出线位置。
- Converter_SIP4_B0505S：1 W 隔离电源 SIP-4，单列直插 2.54 mm 间距，外形 11.6 × 6.0 mm。
  159h 对照 YLPTEC B_S-1WR2 系列规格书 p.5 封装图核对：本体 11.50 × 6.00 mm、1 脚离边 1.94 mm、间距 2.54 mm，相符。
159h（打样准备，对照厂家规格书尺寸图，核对记录见 ../ctrl-ls/order/核对表.md）新加四种：
- Fuseholder_Clip-5x20_XC-C3130_Pair：两个 5×20 保险丝夹（旭程 C3130）。每个夹两只脚，脚截面 1.10 × 0.35 mm（对角 1.15 mm），
  两脚外沿 4.80 mm → 中心距 4.45 mm，孔 1.4 mm；两夹中心距 14.9 mm = 保险管长 20 mm − 帽长 5.1 mm（Littelfuse 215 系列 p.2 尺寸图），
  夹子落在两端帽的正中。
- RV_Disc_D15.5mm_W5.0mm_P7.5mm_TDK_S14：TDK SIOV S14K275 压敏电阻。e = 7.5 mm、两脚前后错开 a = 1.8 mm（典型）、脚径 0.8 mm → 孔 1.1 mm；
  本体 15.5 × 5.0 mm（StandarD 系列 p.14）。KiCad 官方 RV_Disc_D15.5mm_W4.9mm 的孔 0.8 mm 插不进 0.8 mm 的脚、错开 2.2 mm 也不对。
- NTC_Disc_D21.0mm_W7.0mm_P7.5mm_TDK_S364：TDK S364 浪涌热敏电阻。脚距 7.5 mm、两脚同一直线、脚径 1.0 mm → 孔 1.4 mm；
  本体 21.0 × 7.0 mm（p.3 尺寸图）。原先借压敏电阻的 15.5 mm 封装，本体画小了、孔 0.8 mm 插不进。
- Diode_Bridge_GBU_D1.8mm：GBU 整流桥，同 KiCad 官方 Diode_Bridge_Vishay_GBU，孔由 1.6 改 1.8 mm：
  LGE GBU1006 规格书 p.1 的脚宽 1.02–1.27 mm、厚 0.76–1.02 mm，对角最大 1.63 mm，1.6 mm 孔插不进。
示例设计，未经硬件验证。"""
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "libs", "wq.pretty")


def rect(x0, y0, x1, y1, layer, w):
    return "".join('  (fp_line (start {} {}) (end {} {}) (layer "{}") (width {}))\n'.format(a, b, c, d, layer, w)
                   for a, b, c, d in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)))


def footprint(name, descr, pads, body, court, ref_at, val_at, smd=False):
    s = '(footprint "{}" (version 20211014) (generator pcbnew)\n  (layer "F.Cu")\n'.format(name)
    s += '  (descr "{}")\n  (attr through_hole)\n'.format(descr)
    s += '  (fp_text reference "REF**" (at {} {}) (layer "F.SilkS")\n    (effects (font (size 1 1) (thickness 0.15)))\n  )\n'.format(*ref_at)
    s += '  (fp_text value "{}" (at {} {}) (layer "F.Fab")\n    (effects (font (size 1 1) (thickness 0.15)))\n  )\n'.format(name, *val_at)
    s += rect(*body, "F.SilkS", 0.12) + rect(*body, "F.Fab", 0.1) + rect(*court, "F.CrtYd", 0.05)
    for num, x, y, size, drill in pads:
        shape = "rect" if num == "1" else "circle"
        s += '  (pad "{}" thru_hole {} (at {} {}) (size {} {}) (drill {}) (layers "*.Cu" "*.Mask"))\n'.format(num, shape, x, y, size, size, drill)
    return s + ")\n"


def main():
    os.makedirs(OUT, exist_ok=True)
    fps = {
        "L_ETD59_Horizontal": footprint(
            "L_ETD59_Horizontal", "PFC inductor, ETD59 horizontal coil former, 2 leads (CTRL-LS, dimensions by theory)",
            [("1", 0, 0, 3.5, 2.0), ("2", 50.8, 0, 3.5, 2.0)],
            (-12.35, -70.5, 63.15, 5.0), (-12.6, -70.75, 63.4, 5.25), (25.4, -72.5), (25.4, 7.0)),
        "Converter_SIP4_B0505S": footprint(
            "Converter_SIP4_B0505S", "1 W isolated DC-DC converter, SIP-4, 2.54 mm (CTRL-LS; checked against YLPTEC B_S-1WR2 p.5 in 159h)",
            [(str(i + 1), round(i * 2.54, 2), 0, 1.7, 1.0) for i in range(4)],
            (-2.0, -4.5, 9.6, 1.5), (-2.25, -4.75, 9.85, 1.75), (3.81, -6.0), (3.81, 3.0)),
        "Fuseholder_Clip-5x20_XC-C3130_Pair": footprint(
            "Fuseholder_Clip-5x20_XC-C3130_Pair", "Two 5x20 mm fuse clips XC C3130, clip centres 14.9 mm, 2 pins each (CTRL-LS 159h)",
            [("1", -2.225, 0, 2.4, 1.4), ("1", 2.225, 0, 2.4, 1.4), ("2", 12.675, 0, 2.4, 1.4), ("2", 17.125, 0, 2.4, 1.4)],
            (-2.55, -3.6, 17.45, 3.6), (-3.8, -3.85, 18.7, 3.85), (7.45, -5.0), (7.45, 5.0)),
        "RV_Disc_D15.5mm_W5.0mm_P7.5mm_TDK_S14": footprint(
            "RV_Disc_D15.5mm_W5.0mm_P7.5mm_TDK_S14", "Varistor TDK SIOV S14, e 7.5 mm, lead offset a 1.8 mm, lead 0.8 mm (CTRL-LS 159h)",
            [("1", 0, 0, 2.0, 1.1), ("2", 7.5, 1.8, 2.0, 1.1)],
            (-4.0, -1.6, 11.5, 3.4), (-4.25, -1.85, 11.75, 3.65), (3.75, -3.0), (3.75, 4.8)),
        "NTC_Disc_D21.0mm_W7.0mm_P7.5mm_TDK_S364": footprint(
            "NTC_Disc_D21.0mm_W7.0mm_P7.5mm_TDK_S364", "Inrush NTC TDK S364, LS 7.5 mm in line, lead 1.0 mm (CTRL-LS 159h)",
            [("1", 0, 0, 2.4, 1.4), ("2", 7.5, 0, 2.4, 1.4)],
            (-6.75, -3.5, 14.25, 3.5), (-7.0, -3.75, 14.5, 3.75), (3.75, -4.8), (3.75, 4.8)),
        "Diode_Bridge_GBU_D1.8mm": footprint(
            "Diode_Bridge_GBU_D1.8mm", "GBU bridge rectifier, 5.08 mm pitch, drill 1.8 mm for 1.27 x 1.02 mm leads (LGE GBU1006, CTRL-LS 159h)",
            [("1", 0, 0, 3.2, 1.8), ("2", 5.08, 0, 3.2, 1.8), ("3", 10.16, 0, 3.2, 1.8), ("4", 15.24, 0, 3.2, 1.8)],
            (-3.5, -1.2, 18.8, 2.4), (-3.65, -1.85, 18.95, 2.55), (7.7, 3.3), (7.1, -2.5)),
    }
    for n, txt in fps.items():
        with open(os.path.join(OUT, n + ".kicad_mod"), "w", encoding="utf-8") as f:
            f.write(txt)
    print(OUT, len(fps))


if __name__ == "__main__":
    main()
