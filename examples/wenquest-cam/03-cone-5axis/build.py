"""问渠CAM 例子 3：五轴联动侧刃铣圆锥台（ADR-0106 C3a）。不用 FreeCAD，可直接用普通 python 跑：

    python examples/wenquest-cam/03-cone-5axis/build.py [--save]

NAS 979 圆锥台（简化）：半锥角 15°、底 Ø150（Z −15）、顶在 Z0，Ø10 平底刀侧刃贴锥面绕一圈（刀尖再往下伸 1 mm）。
刀位由直纹面侧刃铣算（analysis/cam/fiveaxis.swarf），示例摇篮式五轴 EX-5AX-AC（虚构）上算去料、整机仿真，
出刀尖跟随（RTCP）程序：西门子 TRAORI、FANUC G43.4。--save：把计算设置（setup.json）、正式程序、结果摘要存进本目录。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RB, H, HALF, R_TOOL = 75.0, 15.0, 15.0, 5.0


def program(n: int = 120, f: float = 600.0) -> dict:
    import numpy as np

    from analysis.cam import fiveaxis as FA

    rt = RB - H * math.tan(math.radians(HALF))
    th = np.radians(np.linspace(0.0, 360.0, n + 1))
    bot = np.c_[RB * np.cos(th), RB * np.sin(th), np.full(n + 1, -H)]
    top = np.c_[rt * np.cos(th), rt * np.sin(th), np.zeros(n + 1)]
    tips, axes = FA.swarf(bot, top, R_TOOL, below=1.0)
    r = lambda v: [round(float(x), 6) for x in v]
    p0, pe = tips[0], tips[-1]
    mv = [{"t": "rapid", "x": p0[0] + 30, "y": p0[1], "z": 10.0, "axis": r(axes[0])},
          {"t": "rapid", "x": p0[0] + 30, "y": p0[1], "z": p0[2], "axis": r(axes[0])},
          {"t": "feed", "x": p0[0], "y": p0[1], "z": p0[2], "axis": r(axes[0]), "f": f}]
    mv += [{"t": "feed", "x": p[0], "y": p[1], "z": p[2], "axis": r(a), "f": f} for p, a in zip(tips[1:], axes[1:])]
    mv += [{"t": "feed", "x": pe[0] + 30, "y": pe[1], "z": pe[2], "axis": r(axes[-1]), "f": f},
           {"t": "rapid", "x": pe[0] + 30, "y": pe[1], "z": 10.0, "axis": r(axes[-1])}]
    for m in mv:
        for k in ("x", "y", "z"):
            m[k] = round(float(m[k]), 6)
    return {"number": 7101, "title": "NAS 979 圆锥台（五轴联动侧刃）", "title_en": "NAS 979 CONE 5-AXIS SWARF",
            "ops": [{"tool": {"n": 1, "d": 2 * R_TOOL, "kind": "endmill"}, "spindle": {"rpm": 6000}, "safe": 10.0,
                     "title": "锥面侧刃一圈", "simul5": True, "moves": mv}]}


def setup(post: str) -> dict:
    return {"mode": "program", "machine": "EX-5AX-AC", "program": program(), "post": post,
            "stock": {"box": [-90, -90, 90, 90], "height": 30},
            "machine_sim": {"work_offset_mm": [0, 0, 100], "tools": {"1": {"tool": "EM10", "length_mm": 120}}}}


def main(argv=None) -> int:
    from analysis import cam

    ap = argparse.ArgumentParser(description="问渠CAM 例子 3：五轴联动圆锥台")
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    summary = {}
    for post, ext in (("siemens", "mpf"), ("fanuc", "nc")):
        st = setup(post)
        r = cam.run(st)
        p = r["data"]["programs"][0]
        if p["release"] is None:
            print("\n".join(c["text"] for c in p["checks"]), file=sys.stderr)
            return 1
        summary[post] = {"machine_sim": p["machine_sim"]["status"], "removed_mm3": p["sim"]["removed_mm3"],
                         "cut_s": round(p["time"]["cut_s"], 1), "checks": [f"{c['level']}: {c['text']}" for c in p["checks"]]}
        if a.save:
            (HERE / f"O7101-{post}.{ext}").write_text(p["release"]["text"], encoding="utf-8")
            if post == "siemens":
                (HERE / "setup.json").write_text(json.dumps(st, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if a.save:
        (HERE / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: {kk: v[kk] for kk in ("machine_sim", "removed_mm3", "cut_s")} for k, v in summary.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
