# -*- coding: utf-8 -*-
"""KiCad 手工改动读回（第 111 轮 P4）：人在 KiCad 里挪了器件、改了安装孔或铺铜，读回成设计描述板子层的变化。

    python3 -m wqeda.readback <板子.kicad_pcb> <design.yaml> [--write <新的 design.yaml>]

比对：摆放（位置、角度、正反面）、安装孔、功率铺铜的顶点。写新文件时只改板子层的这几处，其余原样保留（注释也在）。
原理图和网络的改动这一期不读回：查到焊盘上的网络和设计描述不一致，就列成“不一致”，请人回到设计描述里改。
布线不写进设计描述，留在 KiCad 文件里；只算一个指纹（走线和过孔的摘要），说明“设计描述对应的是哪一版布线”。
测试点网格上的点是按规则排的，挪了没法写回网格，列出来请人放回去或改网格。"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys

from .schema import design as D

ORIGIN = (100.0, 100.0)  # 与 gen/board.py 相同：板子左上角在 KiCad 坐标里的位置
TOL = 0.005  # mm、度


def _num(v):
    v = round(v, 3)
    return int(v) if abs(v - round(v)) < 1e-9 else v


def read_kicad(path):
    """KiCad 板子 → {placement, holes, pours, pins, routing}（板子坐标：左上角为原点，x 向右、y 向下）"""
    import pcbnew

    b = pcbnew.LoadBoard(path)
    mm = pcbnew.ToMM
    place, holes, pins = {}, [], {}
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        x, y = mm(fp.GetPosition().x) - ORIGIN[0], mm(fp.GetPosition().y) - ORIGIN[1]
        if re.fullmatch(r"H\d+", ref) and str(fp.GetFPID().GetLibItemName()).startswith("MountingHole"):
            holes.append((int(ref[1:]), (_num(x), _num(y))))
            continue
        side = "B" if fp.GetLayer() == pcbnew.B_Cu else "F"
        rot = fp.GetOrientationDegrees()
        if side == "B":  # 生成器先按设计的角度转、再上下翻到底面，翻面让角度变号
            rot = -rot
        place[ref] = (_num(x), _num(y), _num(rot % 360), side)
        pins[ref] = {p.GetNumber(): p.GetNetname() for p in fp.Pads() if p.GetNumber()}
    pours = []
    for z in b.Zones():
        if z.GetAssignedPriority() < 2:  # 地平面（优先级 0）由生成器按板框铺，不是设计描述里的铺铜
            continue
        ol = z.Outline().Outline(0)
        pts = [
            (_num(mm(ol.CPoint(k).x) - ORIGIN[0]), _num(mm(ol.CPoint(k).y) - ORIGIN[1])) for k in range(ol.PointCount())
        ]
        pours.append({"net": z.GetNetname(), "layer": b.GetLayerName(z.GetLayer()), "points": pts})
    h = hashlib.sha256()
    for t in sorted(
        (
            t.GetClass(),
            t.GetNetname(),
            t.GetLayer(),
            t.GetStart().x,
            t.GetStart().y,
            t.GetEnd().x,
            t.GetEnd().y,
            t.GetWidth(),
        )
        for t in b.GetTracks()
    ):
        h.update(repr(t).encode())
    return {
        "placement": place,
        "holes": [xy for _, xy in sorted(holes)],
        "pours": pours,
        "pins": pins,
        "routing": h.hexdigest()[:16],
        "tracks": len(list(b.GetTracks())),
    }


def _same(a, b):
    return all(abs(float(p) - float(q)) <= TOL for p, q in zip(a[:3], b[:3], strict=True)) and a[3] == b[3]


def compare(kb, doc, var=None):
    """kb = read_kicad() 的结果；doc / var = 设计描述（和变体）。返回变化清单"""
    x = D.expand(doc, var)
    base_place = (doc["board"].get("placement") or {}) if var is None else None
    grid = set((doc["board"].get("test_point_grid") or {}).get("first") or [])
    tp_refs = {q["ref"] for q in x["parts"] if q["ref"].startswith("TP")}
    moved, grid_moved, missing, extra = [], [], [], []
    for ref, want in sorted(x["placement"].items()):
        have = kb["placement"].get(ref)
        if have is None:
            missing.append(ref)
        elif not _same(want, have):
            row = {"ref": ref, "from": list(want), "to": list(have)}
            (grid_moved if (ref in grid or ref in tp_refs) else moved).append(row)
    for ref in sorted(set(kb["placement"]) - set(x["placement"])):
        extra.append(ref)
    holes_changed = [list(h) for h in kb["holes"]] != [list(h) for h in x["holes"]]
    want_pours = [
        {"net": n, "layer": lay, "points": [tuple(_num(v) for v in p) for p in pts]} for n, lay, pts in x["pours"]
    ]
    pours_changed = _pour_key(kb["pours"]) != _pour_key(want_pours)
    nets = []
    for q in x["parts"]:
        have = kb["pins"].get(q["ref"])
        if have is None:
            continue
        for pin, net in q["pins"].items():
            if net in x["nc_nets"]:
                continue
            if have.get(pin, "") != net:
                nets.append({"ref": q["ref"], "pin": pin, "design": net, "board": have.get(pin) or "（没接）"})
    return {
        "moved": moved,
        "grid_moved": grid_moved,
        "missing": missing,
        "extra": extra,
        "holes": {"changed": holes_changed, "board": [list(h) for h in kb["holes"]]},
        "pours": {"changed": pours_changed, "board": kb["pours"]},
        "nets": nets,
        "routing": kb["routing"],
        "tracks": kb["tracks"],
        "writable": var is None and base_place is not None,
        "none": not (moved or grid_moved or missing or extra or holes_changed or pours_changed or nets),
    }


def _pour_key(pours):
    """铺铜比顶点：去掉连着重复的顶点（KiCad 存的时候会合并）"""
    out = []
    for p in pours:
        pts = [tuple(_num(float(v)) for v in xy) for xy in p["points"]]
        pts = [q for k, q in enumerate(pts) if k == 0 or q != pts[k - 1]]
        out.append((p["net"], p["layer"], tuple(pts)))
    return sorted(out)


def _fmt(v):
    return "{:g}".format(v) if isinstance(v, float) else str(v)


def patch(text, ch):
    """把读回的摆放、孔、铺铜写进设计描述的文本（只改这几处，别的原样保留）"""
    for m in ch["moved"]:
        x, y, rot, side = m["to"]
        new = "    {}: [{}, {}, {}, {}]".format(m["ref"], _fmt(x), _fmt(y), _fmt(rot), side)
        text, n = re.subn(r"(?m)^    {}: \[[^\]]*\]".format(re.escape(m["ref"])), new, text)
        if n != 1:
            raise ValueError("设计描述里找不到 {} 的摆放".format(m["ref"]))
    if ch["holes"]["changed"]:
        body = "".join("  - [{}, {}]\n".format(_fmt(a), _fmt(b)) for a, b in ch["holes"]["board"])
        text = _replace_block(text, "  holes:\n", body)
    if ch["pours"]["changed"]:
        body = ""
        for p in ch["pours"]["board"]:
            body += "  - net: {}\n    layer: {}\n    points:\n".format(p["net"], p["layer"])
            body += "".join("    - [{}, {}]\n".format(_fmt(a), _fmt(b)) for a, b in p["points"])
        text = _replace_block(text, "  pours:\n", body)
    return text


def _replace_block(text, head, body):
    i = text.index(head) + len(head)
    m = re.compile(r"(?m)^(?:  [a-z_]+:|[a-z_]+:|# )").search(text, i)
    j = m.start() if m else len(text)
    return text[:i] + body + text[j:]


def describe(ch):
    out = []
    if ch["none"]:
        return ["板子和设计描述一致，无变化。布线指纹 {}（{} 段走线和过孔）".format(ch["routing"], ch["tracks"])]
    for m in ch["moved"]:
        f, t = m["from"], m["to"]
        what = []
        if abs(f[0] - t[0]) > TOL or abs(f[1] - t[1]) > TOL:
            what.append("从 ({}, {}) 挪到 ({}, {})".format(_fmt(f[0]), _fmt(f[1]), _fmt(t[0]), _fmt(t[1])))
        if abs(f[2] - t[2]) > TOL:
            what.append("从 {}° 转到 {}°".format(_fmt(f[2]), _fmt(t[2])))
        if f[3] != t[3]:
            what.append("从{}面翻到{}面".format("顶" if f[3] == "F" else "底", "顶" if t[3] == "F" else "底"))
        out.append("{} {}".format(m["ref"], "，".join(what)))
    for m in ch["grid_moved"]:
        out.append("测试点 {} 被挪了（网格上的点没法写回，请放回或改测试点网格）".format(m["ref"]))
    out += ["{} 在设计描述里有、板子上没有".format(r) for r in ch["missing"]]
    out += ["{} 在板子上有、设计描述里没有（请先加进电路）".format(r) for r in ch["extra"]]
    if ch["holes"]["changed"]:
        out.append("安装孔改了")
    if ch["pours"]["changed"]:
        out.append("功率铺铜改了")
    out += [
        "不一致：{} 第 {} 脚，设计描述接 {}，板子上接 {}".format(n["ref"], n["pin"], n["design"], n["board"])
        for n in ch["nets"]
    ]
    out.append("布线指纹 {}（{} 段走线和过孔）".format(ch["routing"], ch["tracks"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="KiCad 手工改动读回成设计描述的变化")
    ap.add_argument("board")
    ap.add_argument("design")
    ap.add_argument("--write", help="写一份新的设计描述（板子层换成板子上的值）")
    a = ap.parse_args(argv)
    doc = D.read_yaml(a.design)
    var = None
    if doc.get("format") == D.VARIANT_FORMAT:
        doc, var = D.load_variant(a.design)
    ch = compare(read_kicad(a.board), doc, var)
    print("\n".join(describe(ch)))
    if a.write:
        if not ch["writable"]:
            print("变体文件不能直接写回：请改基础设计描述或变体的 add_placement", file=sys.stderr)
            return 2
        with open(a.design, encoding="utf-8") as f:
            text = patch(f.read(), ch)
        D.validate_design(D.read_yaml_text(text))
        with open(a.write, "w", encoding="utf-8") as f:
            f.write(text)
        print("写好了：" + a.write)
    return 1 if ch["nets"] else 0


if __name__ == "__main__":
    sys.exit(main())
