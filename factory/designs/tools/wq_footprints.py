# -*- coding: utf-8 -*-
"""第 159 轮 159d2b：工程自带封装库 ../libs/wq.pretty——KiCad 官方库没有的两种封装（平缝机控制器 CTRL-LS 用）。

    python3 wq_footprints.py        # 产物入库，逐字可复现

- L_ETD59_Horizontal：升压电感（定制，磁芯 EPCOS ETD 59/31/22 + 骨架 B66398，计算书“按理论”选的）。
  骨架的钻孔图读不出数字，封装按理论定：外形按 KiCad 官方库 ETD29 卧式骨架封装（37.2 × 37.2 mm，磁芯 29 mm）同比例放大到 59 mm 磁芯
  （× 2.03 ≈ 75.5 × 75.5 mm），引出两根线（起、末），间距 50.8 mm、孔 2.0 mm（利兹线 2 mm² 加焊锡）。绕制厂按这个封装做引出线位置。
- Converter_SIP4_B0505S：1 W 隔离电源 SIP-4，规格书写“行业标准引脚”、图读不出：按单列直插 2.54 mm 间距，
  外形 11.6 × 6.0 mm（1 W SIP 常见尺寸），待核对。
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
            "Converter_SIP4_B0505S", "1 W isolated DC-DC converter, SIP-4, 2.54 mm (CTRL-LS, industry-standard pinout, to be checked)",
            [(str(i + 1), round(i * 2.54, 2), 0, 1.7, 1.0) for i in range(4)],
            (-2.0, -4.5, 9.6, 1.5), (-2.25, -4.75, 9.85, 1.75), (3.81, -6.0), (3.81, 3.0)),
    }
    for n, txt in fps.items():
        with open(os.path.join(OUT, n + ".kicad_mod"), "w", encoding="utf-8") as f:
            f.write(txt)
    print(OUT, len(fps))


if __name__ == "__main__":
    main()
