# -*- coding: utf-8 -*-
"""由设计描述写 KiCad 7 原理图（根图 + 每个功能一页）：器件按网格摆放，每个引脚引一小段线接全局标签（同名标签即同一网络），
没用的引脚画不连接标记。UUID 由名字算出（uuid5），同一份设计每次生成逐字一致。"""
from __future__ import annotations

import os
import uuid

import sexp
from sexp import Sym, dump

NS = uuid.UUID("6f3c1c1e-6a49-4b0e-9d7e-8a2c6f0b7a11")
G = 2.54
FONT = [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]


def uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def snap(v):
    return round(round(v / G) * G, 2)


def _bbox(pins):
    xs = [p[3] for p in pins] or [0]
    ys = [p[4] for p in pins] or [0]
    return min(xs), max(xs), min(ys), max(ys)


def _out_dir(angle):
    """引脚连接点向外的方向（原理图坐标，y 向下）"""
    a = int(round(angle)) % 360
    return {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[a]


def _label_angle(d):
    return {(-1, 0): 180, (1, 0): 0, (0, 1): 270, (0, -1): 90}[d]


def sheet_file(design, project, sheet, title, title_en, page, root_uuid, nc_nets, note):
    parts = [p for p in design.PARTS if p["sheet"] == sheet]
    libs = {}
    for p in parts:
        libs.setdefault(p["lib"], sexp.symbol(p["lib"]))
    su = uid(project, "sheet", sheet)
    body = [Sym("kicad_sch"), [Sym("version"), 20230121], [Sym("generator"), Sym("eeschema")], [Sym("uuid"), uid(project, "file", sheet)],
            [Sym("paper"), "A3"],
            [Sym("title_block"), [Sym("title"), "DRV-JOINT · {} {}".format(title, title_en)], [Sym("date"), "2026-11-05"], [Sym("rev"), "示例 A"],
             [Sym("company"), "问渠数字工业园 · 电路板厂（示例设计，未经硬件验证，不能直接投产）"],
             [Sym("comment"), 1, note[:120]]],
            [Sym("lib_symbols")] + list(libs.values())]
    # 摆放：按行排，每格宽 = 符号宽 + 两侧标签位
    x0, y0, maxw = 30.0, 40.0, 380.0
    x, y, rowh = x0, y0, 0.0
    for p in parts:
        pins = sexp.pins(libs[p["lib"]])
        mnx, mxx, mny, mxy = _bbox(pins)
        w = (mxx - mnx) + 2 * 30
        h = (mxy - mny) + 2 * 14
        if x + w > maxw + x0:
            x, y = x0, y + rowh
            rowh = 0.0
        ox, oy = snap(x + 30 - mnx), snap(y + 14 + mxy)
        x += w
        rowh = max(rowh, h)
        sym = [Sym("symbol"), [Sym("lib_id"), p["lib"]], [Sym("at"), ox, oy, 0], [Sym("unit"), 1], [Sym("in_bom"), Sym("yes" if p["item"] else "no")],
               [Sym("on_board"), Sym("yes")], [Sym("dnp"), Sym("no")], [Sym("uuid"), uid(project, "sym", p["ref"])]]
        props = [("Reference", p["ref"], ox, snap(oy - mxy) - 2.54, False), ("Value", p["value"], ox, snap(oy - mny) + 2.54, False),
                 ("Footprint", p["fp"], ox, oy, True), ("Datasheet", "", ox, oy, True),
                 ("物料编号", p["item"] or "", ox, oy, True), ("说明", p["note"] or "", ox, oy, True)]
        for k, v, px, py, hide in props:
            eff = [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]] + ([Sym("hide")] if hide else [])
            sym.append([Sym("property"), k, v, [Sym("at"), px, py, 0], eff])
        for num in sorted({pp[0] for pp in pins}, key=lambda s: (len(s), s)):
            sym.append([Sym("pin"), num, [Sym("uuid"), uid(project, "pin", p["ref"], num)]])
        sym.append([Sym("instances"), [Sym("project"), project, [Sym("path"), "/{}/{}".format(root_uuid, su), [Sym("reference"), p["ref"]], [Sym("unit"), 1]]]])
        body.append(sym)
        seen = set()
        for num, name, typ, px, py, ang, ln, unit in pins:
            if num in seen and p["pins"].get(num) is None:
                continue
            cx, cy = round(ox + px, 2), round(oy - py, 2)
            if (cx, cy) in seen:
                continue
            seen.add((cx, cy))
            seen.add(num)
            net = p["pins"].get(num)
            if net is None or net in nc_nets:
                body.append([Sym("no_connect"), [Sym("at"), cx, cy], [Sym("uuid"), uid(project, "nc", p["ref"], num, cx, cy)]])
                continue
            d = _out_dir(ang)
            ex, ey = round(cx + d[0] * G, 2), round(cy + d[1] * G, 2)
            body.append([Sym("wire"), [Sym("pts"), [Sym("xy"), cx, cy], [Sym("xy"), ex, ey]],
                         [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("default")]], [Sym("uuid"), uid(project, "w", p["ref"], num, cx, cy)]])
            la = _label_angle(d)
            just = Sym("left") if la in (0, 90) else Sym("right")
            body.append([Sym("global_label"), net, [Sym("shape"), Sym("passive")], [Sym("at"), ex, ey, la], [Sym("fields_autoplaced")],
                         [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("justify"), just]],
                         [Sym("uuid"), uid(project, "gl", p["ref"], num, cx, cy)],
                         [Sym("property"), "Intersheetrefs", "${INTERSHEET_REFS}", [Sym("at"), ex, ey, 0],
                          [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], Sym("hide")]]])
    body.append([Sym("text"), note, [Sym("at"), 30, 22, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 2.0, 2.0]], [Sym("justify"), Sym("left")]],
                 [Sym("uuid"), uid(project, "note", sheet)]])
    return dump(body) + "\n"


def root_file(design, project, root_uuid, title):
    body = [Sym("kicad_sch"), [Sym("version"), 20230121], [Sym("generator"), Sym("eeschema")], [Sym("uuid"), root_uuid], [Sym("paper"), "A3"],
            [Sym("title_block"), [Sym("title"), title], [Sym("date"), "2026-11-05"], [Sym("rev"), "示例 A"],
             [Sym("company"), "问渠数字工业园 · 电路板厂（示例设计，未经硬件验证，不能直接投产）"]],
            [Sym("lib_symbols")]]
    for i, (key, name, name_en) in enumerate(design.SHEETS):
        x, y = 40 + (i % 4) * 90, 60 + (i // 4) * 60
        body.append([Sym("sheet"), [Sym("at"), x, y], [Sym("size"), 70, 30], [Sym("fields_autoplaced")],
                     [Sym("stroke"), [Sym("width"), 0.1524], [Sym("type"), Sym("solid")]], [Sym("fill"), [Sym("color"), 0, 0, 0, 0.0]],
                     [Sym("uuid"), uid(project, "sheet", key)],
                     [Sym("property"), "Sheetname", "{} {}".format(i + 1, name), [Sym("at"), x, round(y - 0.7, 2), 0],
                      [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("justify"), Sym("left"), Sym("bottom")]]],
                     [Sym("property"), "Sheetfile", key + ".kicad_sch", [Sym("at"), x, round(y + 30.6, 2), 0],
                      [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]], [Sym("justify"), Sym("left"), Sym("top")]]],
                     [Sym("instances"), [Sym("project"), project, [Sym("path"), "/" + root_uuid, [Sym("page"), str(i + 2)]]]]])
    body.append([Sym("text"), "关节伺服驱动板 DRV-JOINT：48 V、三相、相电流采样 + 编码器接口 + CAN。示例设计，未经硬件验证。",
                 [Sym("at"), 40, 35, 0], [Sym("effects"), [Sym("font"), [Sym("size"), 2.5, 2.5]], [Sym("justify"), Sym("left")]],
                 [Sym("uuid"), uid(project, "roottext")]])
    body.append([Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]])
    return dump(body) + "\n"


def write(design, outdir, project="drv-joint"):
    os.makedirs(outdir, exist_ok=True)
    root_uuid = uid(project, "root")
    notes = getattr(design, "SHEET_NOTES", {})
    files = {project + ".kicad_sch": root_file(design, project, root_uuid, getattr(design, "TITLE", "关节伺服驱动板 DRV-JOINT Joint servo drive board"))}
    for i, (key, name, name_en) in enumerate(design.SHEETS):
        files[key + ".kicad_sch"] = sheet_file(design, project, key, name, name_en, i + 2, root_uuid, design.NC_NETS, notes.get(key, name))
    for fn, txt in files.items():
        with open(os.path.join(outdir, fn), "w", encoding="utf-8") as f:
            f.write(txt)
    return list(files)
