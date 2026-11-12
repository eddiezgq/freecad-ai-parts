# -*- coding: utf-8 -*-
"""平缝机控制器 CTRL-LS：从设计描述生成 KiCad 原理图和产物（第 159 轮 159d1；PCB 在 159d2 接上）。

    python3 ctrl_ls_build.py        # 原理图（每个功能块一页）、各页 SVG、网表核对、物料清单

要：KiCad 7.0.11 的 kicad-cli。产物写到 ../ctrl-ls/：kicad/（KiCad 工程，可以用 KiCad 打开继续改）、out/（网页和工厂用）。
网表核对：KiCad 从原理图导出网表，逐个网络、逐个引脚和设计描述对照（KiCad 7 的命令行没有电气规则检查，用这个代替：
接错、漏接、多接都会查出来）。示例设计，未经硬件验证，不能直接投产。"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
NAME = "ctrl-ls"
PROJ = os.path.join(ROOT, NAME)
KDIR = os.path.join(PROJ, "kicad")
OUT = os.path.join(PROJ, "out")
TMP = os.path.join(PROJ, ".route")  # 中间文件（不入库）
DATE = "2026-11-12"

import ctrl_ls as D  # noqa: E402
import sch  # noqa: E402
import sexp  # noqa: E402


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("{} 失败：{}{}".format(" ".join(cmd[:4]), r.stdout[-1500:], r.stderr[-1500:]))
    return r


def schematic():
    os.makedirs(KDIR, exist_ok=True)
    shutil.copy(os.path.join(ROOT, "libs", "wq.kicad_sym"), os.path.join(KDIR, "wq.kicad_sym"))
    with open(os.path.join(KDIR, "sym-lib-table"), "w", encoding="utf-8") as f:
        f.write('(sym_lib_table\n  (lib (name "wq")(type "KiCad")(uri "${KIPRJMOD}/wq.kicad_sym")(options "")'
                '(descr "问渠：定制磁性元件、隔离电源等官方库没有的符号"))\n)\n')
    return sch.write(D, KDIR, NAME)


def _norm(path, pats):
    with open(path, encoding="utf-8", errors="replace") as f:
        t = f.read()
    for a, b in pats:
        t = re.sub(a, b, t)
    with open(path, "w", encoding="utf-8") as f:
        f.write(t)


def exports():
    root = os.path.join(KDIR, NAME + ".kicad_sch")
    os.makedirs(TMP, exist_ok=True)
    sdir = os.path.join(OUT, "schematic")
    if os.path.isdir(sdir):
        shutil.rmtree(sdir)
    os.makedirs(sdir)
    run(["kicad-cli", "sch", "export", "svg", "-o", sdir, root])
    for fn in os.listdir(sdir):
        _norm(os.path.join(sdir, fn), [(r"(<title>SVG Image created as [^<]*?) date [^<]*</title>", r"\1 date {}</title>".format(DATE))])
    net = os.path.join(TMP, "sch.net")
    run(["kicad-cli", "sch", "export", "netlist", "-o", net, root])
    return net


def netcheck(net_path):
    """KiCad 导出的网表 ↔ 设计描述，逐网络逐引脚对照"""
    with open(net_path, encoding="utf-8") as f:
        doc = sexp.parse(f.read())
    got = {}
    for n in sexp.find(sexp.first(doc, "nets"), "net"):
        name = sexp.first(n, "name")[1].lstrip("/")
        nodes = {(sexp.first(x, "ref")[1], sexp.first(x, "pin")[1]) for x in sexp.find(n, "node")}
        if name.startswith("unconnected-") or name.startswith("Net-("):
            for node in nodes:
                got.setdefault("（未连接）", set()).add(node)
            continue
        got[name] = nodes
    want = {k: set(v) for k, v in D.nets().items() if k not in D.NC_NETS}
    problems = []
    for name in sorted(set(want) | set(got) - {"（未连接）"}):
        a, b = want.get(name, set()), got.get(name, set())
        if a != b:
            problems.append({"net": name, "missing": sorted(a - b), "extra": sorted(b - a)})
    comps = {sexp.first(c_, "ref")[1] for c_ in sexp.find(sexp.first(doc, "components"), "comp")}
    refs = {p["ref"] for p in D.PARTS}
    return {"nets_design": len(want), "nets_schematic": len([k for k in got if k != "（未连接）"]), "parts_design": len(refs),
            "parts_schematic": len(comps), "missing_parts": sorted(refs - comps), "extra_parts": sorted(comps - refs),
            "problems": problems, "pass": not problems and refs == comps}


def _parts_catalog():
    """器件表 parts.yaml：物料编号 → 型号、厂家、立创编号（阻容等通用件不在表里，物料清单只写数值和封装）"""
    import yaml

    with open(os.path.join(PROJ, "parts.yaml"), encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return {p["item"]: p for p in doc["parts"] if p.get("item")}


def bom(path):
    cat = _parts_catalog()
    rows = {}
    for p in D.PARTS:
        if not p["item"]:
            continue
        rows.setdefault((p["item"], p["value"], p["fp"].split(":")[1]), []).append(p["ref"])
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["物料编号", "数值", "封装", "数量", "位号", "型号", "厂家", "立创编号", "说明"])
        for (item, val, fp), refs in sorted(rows.items()):
            note = next(p["note"] for p in D.PARTS if p["ref"] == refs[0])
            q = cat.get(item, {})
            w.writerow([item, val, fp, len(refs), " ".join(sorted(refs, key=_refkey)), q.get("mpn", ""), q.get("maker", ""), q.get("lcsc", ""),
                        note])
    return len(rows)


def _refkey(r):
    m = re.match(r"([A-Z]+)(\d+)", r)
    return (m.group(1), int(m.group(2))) if m else (r, 0)


def summary(nc, n_bom):
    sheets = sorted(os.listdir(os.path.join(OUT, "schematic")))
    files = {}
    for i, (key, _, _) in enumerate(D.SHEETS):
        files[key] = next((s for s in sheets if s.startswith("{}-{} ".format(NAME, i + 1))), None)
    d = {
        "name": "平缝机控制器 CTRL-LS", "item": "CTRL-LS", "rev": "示例 A", "date": DATE, "stage": "159d1 原理图（PCB 在 159d2）",
        "disclaimer": "示例设计，未经硬件验证，不能直接投产",
        "tool": "KiCad 7.0.11", "board_mm": list(D.X["board_mm"]), "layers": D.X["layers"],
        "sheets": [{"key": k, "name": n, "name_en": e, "svg": files.get(k), "note": D.SHEET_NOTES.get(k, "")} for k, n, e in D.SHEETS],
        "root_svg": next((s for s in sheets if s == NAME + ".svg"), None),
        "parts": [{"ref": p["ref"], "value": p["value"], "fp": p["fp"], "sheet": p["sheet"], "item": p["item"], "note": p["note"],
                   "lib": p["lib"]} for p in D.PARTS],
        "nets": len([n for n in D.nets() if n not in D.NC_NETS]),
        "bom_by_item": D.bom_by_item(), "bom_rows": n_bom,
        "netcheck": {k: nc[k] for k in ("pass", "nets_design", "nets_schematic", "parts_design", "parts_schematic")},
        "files": {},
    }
    for root, _, fs in os.walk(OUT):
        for fn in sorted(fs):
            if fn == "design.json":
                continue
            p = os.path.join(root, fn)
            with open(p, "rb") as f:
                d["files"][os.path.relpath(p, OUT)] = hashlib.sha256(f.read()).hexdigest()[:16]
    with open(os.path.join(OUT, "design.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    return d


def main():
    schematic()
    net = exports()
    nc = netcheck(net)
    with open(os.path.join(OUT, "netcheck.json"), "w", encoding="utf-8") as f:
        json.dump(nc, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    n_bom = bom(os.path.join(OUT, "bom.csv"))
    s = summary(nc, n_bom)
    print("原理图 {} 页、器件 {}、网络 {}；网表核对 {}（问题 {} 处）；物料清单 {} 行".format(
        len(D.SHEETS), len(D.PARTS), s["nets"], "通过" if nc["pass"] else "不通过", len(nc["problems"]), n_bom))
    return 0 if nc["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
