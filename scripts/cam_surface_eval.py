"""ADR-0106 Q3c 曲面评估报告：FreeCAD 3D Surface、Waterline 在斜面、球冠、自由曲面上的残留高度与过切，写 JSON。
用法（要 FreeCAD 的 Python）：xvfb-run -a <FreeCAD>/usr/bin/python scripts/cam_surface_eval.py docs/verification/cam/surface-eval.json"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freecad_addon.fc import cam_surface_eval as E


def main(out: str) -> None:
    rows = []
    cases = [("平面 / flat", E.slope_part(0.0), "surface", {}, E.theory_parallel(3, 2, 0)),
             ("斜面 20° / slope 20°", E.slope_part(20.0), "surface", {}, E.theory_parallel(3, 2, 20)),
             ("斜面 20° / slope 20°", E.slope_part(20.0), "waterline", {"sample": 0.25}, E.theory_waterline(3, 0.5, 20)),
             ("斜面 20° / slope 20°", E.slope_part(20.0), "waterline", {"sample": 0.1}, E.theory_waterline(3, 0.5, 20)),
             ("斜面 20° / slope 20°", E.slope_part(20.0), "waterline", {"sample": 0.05}, E.theory_waterline(3, 0.5, 20)),
             ("球冠顶部 / dome top", E.dome_part(), "surface", {"win": 6.0}, E.theory_parallel(3, 2, math.degrees(math.asin(6 / 60)))),
             ("球冠侧面 / dome side", E.dome_part(), "waterline", {"center": (40.0, 67.0), "win": 4.0},
              E.theory_waterline(3, 0.5, math.degrees(math.asin(23 / 60)))),
             ("自由曲面 / free-form", E.free_part(), "surface", {}, None),
             ("自由曲面 / free-form", E.free_part(), "waterline", {}, None)]
    for name, shape, kind, kw, theory in cases:
        r = E.run_case(shape, kind, **kw)
        r.update({"part": name, "theory_mm": None if theory is None else round(theory, 4)})
        print(json.dumps(r, ensure_ascii=False), flush=True)
        rows.append(r)
    Path(out).write_text(json.dumps({"tool": "ball R3", "stepover_mm": 2.0, "waterline_dz_mm": 0.5, "rows": rows}, ensure_ascii=False, indent=1)
                         + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
