"""问渠CAM 的两个入门例子（ADR-0104 产品化第 3 步）。不开界面，可在测试和 CI 里跑。

    <FreeCAD 的 python> examples/wenquest-cam/build_examples.py [--samples]

1. 免费版 · 带螺纹的阶梯轴（车削）：从回转体读出外圆 4 段、退刀槽、两级内孔，手填 M24×1.5 外螺纹；规则起草（刀具样本中间值），
   卡爪夹左端 15 mm；切削仿真与整机仿真，出 FANUC 程序（两次装夹各一个）。
2. 免费版 · 带型腔和孔的块（2.5 轴铣）：型腔、Ø8.5 通孔由 FreeCAD CAM 算刀路，平口钳夹 10 mm；出 FANUC 程序。
   不铣外轮廓：毛坯就是零件外形，而且平口钳夹着两侧，铣到底的外轮廓会撞钳口（勾上外轮廓再算，整机仿真会拦下来）。
示例机床、示例刀具库都是虚构的，只用来演示。
--samples：把零件 STEP、正式程序（.nc）、结果摘要（results.json）、工艺卡样张（中英 PDF，专业版功能）存进例子目录。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DIRS = {1: "01-shaft-turning", 2: "02-block-milling"}


def shaft():
    """阶梯轴（轴线沿 Z，右端 Z 最大）：Ø30×40、Ø40×60、Ø35×25、Ø24×30；Ø24 段左端 3 宽、底径 20 的退刀槽；右端 Ø16×20 + Ø12×15 内孔"""
    import FreeCAD as App
    import Part

    z, s = 0.0, None
    for d, L in ((30, 40), (40, 60), (35, 25), (24, 30)):
        c = Part.makeCylinder(d / 2, L, App.Vector(0, 0, z))
        s = c if s is None else s.fuse(c)
        z += L
    s = s.cut(Part.makeCylinder(12, 3, App.Vector(0, 0, z - 30)).cut(Part.makeCylinder(10, 3, App.Vector(0, 0, z - 30))))
    s = s.cut(Part.makeCylinder(8, 20, App.Vector(0, 0, z - 20))).cut(Part.makeCylinder(6, 15, App.Vector(0, 0, z - 35)))
    return s.removeSplitter()


def block():
    """100×60×30 的块：顶面 40×20×8 的型腔，Ø8.5 通孔一个"""
    import FreeCAD as App
    import Part

    b = Part.makeBox(100, 60, 30)
    return b.cut(Part.makeBox(40, 20, 8, App.Vector(30, 20, 22))).cut(Part.makeCylinder(4.25, 30, App.Vector(10, 10, 0)))


def example1():
    from freecad_addon.core import cam_study as S
    from freecad_addon.fc import cam_doc

    ft = cam_doc.turn_features(shaft())
    part = S.turn_part(item="带螺纹的阶梯轴（示例）", segments=", ".join(f"{d:g}x{L:g}" for d, L in ft["segments"]),
                       chamfer=ft["chamfer_mm"], grooves="\n".join(f"{g['z']:g}, {g['width']:g}, {g['d']:g}" for g in ft["grooves"]),
                       threads="0, -26, 24, 1.5", bore=", ".join(f"{d:g}x{L:g}" for d, L in ft["bore"]), kienzle="C45E")
    d = S.draft(part)
    d["setup"]["machine_sim"]["fixtures"] = S.lathe_jaws(part, 15, 80)
    d["setup"]["post"] = "fanuc"
    return ft, d, S.run(d["setup"])


def example2():
    from analysis.cam import machines
    from analysis.cam import tools as TL
    from freecad_addon.core import cam_study as S
    from freecad_addon.fc import cam_doc, cam_fc

    shape = block()
    lib = TL.load()
    # 毛坯就是零件外形，不铣外轮廓（平口钳夹着两侧：铣到底的外轮廓会撞钳口，整机仿真会拦下来）
    plan = cam_doc.mill_plan(shape, lib, "P", profile=False, max_rpm=float(machines.get("EX-VMC")["max_rpm"]))
    prog, stock = cam_fc.program(shape, plan["ops"])
    lengths = {"EM10": 120.0, "DR8.5": 140.0}
    ms = {"work_offset_mm": [0.0, 0.0, 40.0], "fixtures": S.vise_jaws(stock, 10),
          "tools": {str(o["number"]): {"tool": o["tool"]["id"], "length_mm": lengths[o["tool"]["id"]]} for o in plan["ops"]}}
    setup = {"mode": "program", "machine": "EX-VMC", "item": "带型腔和孔的块（示例）", "kienzle": "C45E", "program": prog,
             "stock": stock, "machine_sim": ms, "post": "fanuc"}
    d = {"setup": setup, "card": plan["card"], "notes": plan["notes"], "by": "规则（没有用 AI）", "explanation": "", "iso_group": "P"}
    return plan, d, S.run(setup)


def _summary(r) -> dict:
    data = r["data"]
    return {"machine": data["machine"], "total_time_s": round(data["total_time_s"], 2),
            "programs": [{"title": p.get("title"), "number": p.get("number"), "time_s": {k: round(v, 2) for k, v in p["time"].items()
                                                                                       if k.endswith("_s")},
                          "machine_sim": p.get("machine_sim"), "released": bool(p.get("release")),
                          "errors": [c["text"] for c in p["checks"] if c["level"] == "error"]} for p in data["programs"]]}


def save_samples(n, part_shape, d, r) -> list[Path]:
    from assist import cam_card
    from assist.fea_report import to_pdf
    from freecad_addon.core import cam_study as S

    out = HERE / DIRS[n]
    out.mkdir(parents=True, exist_ok=True)
    step = out / ("shaft.step" if n == 1 else "block.step")
    part_shape.exportStep(str(step))
    files = [step, *S.save(r, out, draft_doc=None)]
    (out / "results.json").write_text(json.dumps(_summary(r), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files.append(out / "results.json")
    for lang in ("zh", "en"):
        o = cam_card.build_docx(d, r, out / f"sample-card.{lang}.docx", lang=lang, number=f"EX-{n:02d}")
        p = to_pdf(o["docx"])
        o["docx"].unlink()
        o["ledger"].unlink()
        if p:
            files.append(p)
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="问渠CAM 入门例子")
    ap.add_argument("--samples", action="store_true")
    a = ap.parse_args(argv)
    _ft, d1, r1 = example1()
    _plan, d2, r2 = example2()
    for name, r in (("例子 1", r1), ("例子 2", r2)):
        print(name, json.dumps(_summary(r), ensure_ascii=False)[:400])
    if a.samples:
        for f in save_samples(1, shaft(), d1, r1) + save_samples(2, block(), d2, r2):
            print(f.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
