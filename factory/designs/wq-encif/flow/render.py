# -*- coding: utf-8 -*-
"""GDS → 网页用的版图图片（KLayout）：整颗芯片按层组各出一张（黑底，网页里叠加显示），再出一张放大看单元的局部图。
用法：python3 render.py GDS LYP OUTDIR（在 IIC-OSIC-TOOLS 镜像里用 KLayout 的 Python 模块；也可本机 pip install klayout）"""
import json
import os
import sys

try:
    import klayout.db as kdb
    import klayout.lay as klay
except ImportError:  # KLayout 自带的解释器
    import pya as kdb
    klay = kdb

# SKY130 层号（GDS 层 / 类型）。按“器件 → 各层金属”分组，网页逐组开关。
GROUPS = [
    ("devices", "器件层（阱、有源区、多晶硅、局部互连）", [(64, 20), (65, 20), (65, 44), (66, 20), (66, 44), (67, 20), (93, 44), (94, 20), (95, 20)]),
    ("met1", "金属 1", [(67, 44), (68, 20)]),
    ("met2", "金属 2", [(68, 44), (69, 20)]),
    ("met3", "金属 3", [(69, 44), (70, 20)]),
    ("met4", "金属 4", [(70, 44), (71, 20)]),
    ("met5", "金属 5", [(71, 44), (72, 20)]),
]
BOUNDARY = [(235, 4)]
W = 1600


def view_for(gds, lyp):
    v = klay.LayoutView()
    v.set_config("background-color", "#000000")
    v.set_config("grid-visible", "false")
    v.set_config("text-visible", "false")
    v.load_layout(gds, True)
    if lyp and os.path.exists(lyp):
        v.load_layer_props(lyp)
    v.max_hier()
    return v


def show_only(v, keep):
    it = v.begin_layers()
    while not it.at_end():
        n = it.current()
        if not n.has_children():
            n.visible = (n.source_layer, n.source_datatype) in keep
        it.next()


def main():
    gds, lyp, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    v = view_for(gds, lyp)
    ly = v.cellview(0).layout()
    top = v.cellview(0).cell
    box = top.dbbox()
    h = round(W * box.height() / box.width())
    meta = {"die_um": [round(box.width(), 2), round(box.height(), 2)], "px": [W, h], "layers": []}
    present = {(li.layer, li.datatype) for li in ly.layer_infos()}
    for key, name, lays in GROUPS:
        show_only(v, set(lays) | set(BOUNDARY))
        v.zoom_box(box)
        fn = "layout-{}.png".format(key)
        v.save_image(os.path.join(out, fn), W, h)
        meta["layers"].append({"key": key, "name": name, "png": fn, "present": any(x in present for x in lays)})
    # 局部放大：芯片中心 30 × 30 μm，全部层
    show_only(v, set(x for _, _, ls in GROUPS for x in ls) | set(BOUNDARY))
    c = box.center()
    d = kdb.DBox(c.x - 15, c.y - 15, c.x + 15, c.y + 15)
    v.zoom_box(d)
    v.save_image(os.path.join(out, "layout-detail.png"), 1200, 1200)
    meta["detail"] = {"png": "layout-detail.png", "box_um": [round(d.left, 2), round(d.bottom, 2), round(d.right, 2), round(d.top, 2)]}
    v.zoom_box(box)
    v.save_image(os.path.join(out, "layout-all.png"), W, h)
    meta["all"] = "layout-all.png"
    meta["top"] = top.name
    with open(os.path.join(out, "layout.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
