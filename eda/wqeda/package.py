# -*- coding: utf-8 -*-
"""生产资料：由设计描述导出物料清单和贴片坐标（第 112 轮 P5）。

    python3 -m wqeda.package <design.yaml | variant.yaml> --out <文件夹>

物料清单列名与 build.py 相同（物料编号、数值、封装、数量、位号、说明）；坐标列名与 KiCad 导出相同
（Ref、Val、Package、PosX、PosY、Rot、Side，坐标是 KiCad 的绝对坐标、y 向上）。光绘仍由 KiCad 导出。
不贴的件不进坐标：网络连接点、测试点、安装孔。没有物料编号的件不进物料清单（和 build.py 一样）——
所以“忘了填物料编号”会让坐标里多出一个物料清单里没有的位号，工厂端的 D1 能查出来。纯计算。"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re

from .schema import design as D

ORIGIN = (100.0, 100.0)
NO_PLACE = ("NetTie:", "Connector:TestPoint", "MountingHole:")


def _refkey(r):
    m = re.match(r"([A-Z]+)(\d+)", r)
    return (m.group(1), int(m.group(2))) if m else (r, 0)


def load(path):
    doc = D.read_yaml(path)
    if doc.get("format") == D.VARIANT_FORMAT:
        base, var = D.load_variant(path)
        return D.expand(base, var)
    return D.expand(D.load_design(path))


def bom_csv(x):
    rows = {}
    for p in x["parts"]:
        if not p["item"]:
            continue
        k = (p["item"], p["value"], p["fp"].split(":")[1])
        rows.setdefault(k, []).append(p["ref"])
    f = io.StringIO()
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["物料编号", "数值", "封装", "数量", "位号", "说明"])
    for (item, val, fp), refs in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        note = next(p["note"] for p in x["parts"] if p["ref"] == refs[0])
        w.writerow([item, val, fp, len(refs), " ".join(sorted(refs, key=_refkey)), note])
    return f.getvalue()


def cpl_csv(x):
    f = io.StringIO()
    w = csv.writer(f, lineterminator="\n", quoting=csv.QUOTE_NONNUMERIC)
    w.writerow(["Ref", "Val", "Package", "PosX", "PosY", "Rot", "Side"])
    for p in sorted(x["parts"], key=lambda p: _refkey(p["ref"])):
        if p["lib"].startswith(NO_PLACE) or p["fp"].startswith(NO_PLACE) or p["ref"] not in x["placement"]:
            continue
        px, py, rot, side = x["placement"][p["ref"]]
        rot = -rot if side == "B" else rot
        rot = rot % 360
        rot = rot - 360 if rot > 180 else rot  # KiCad 坐标文件的写法：(-180, 180]
        w.writerow(
            [
                p["ref"],
                p["value"],
                p["fp"].split(":")[1],
                round(ORIGIN[0] + px, 6),
                round(-(ORIGIN[1] + py), 6),
                float(rot),
                "top" if side == "F" else "bottom",
            ]
        )
    return f.getvalue()


def main(argv=None):
    ap = argparse.ArgumentParser(description="由设计描述导出物料清单和贴片坐标")
    ap.add_argument("design")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    x = load(a.design)
    os.makedirs(a.out, exist_ok=True)
    for name, text in (("bom.csv", bom_csv(x)), ("pos.csv", cpl_csv(x))):
        with open(os.path.join(a.out, name), "w", encoding="utf-8", newline="") as f:
            f.write(text)
    print("写好了：{}/bom.csv、pos.csv".format(a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
