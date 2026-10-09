"""Windows 单机安装版的验收（ADR-0066 第 4 项）：用装好的 FreeCAD 自带 Python 运行。

    <安装目录>\\bin\\python.exe installer\\windows\\acceptance.py <安装目录>

1. 打开 FreeCAD 界面，工作台由安装目录 Mod 里的 InitGui 加载（代码来自安装目录，不来自仓库）
2. 选型校验：全部 golden 用例与预期一致
3. 有限元标准题：悬臂梁端部挠度与 PL³/3EI 相差 < 3%（自带的 CalculiX）
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


def main(app: Path) -> int:
    results: dict[str, object] = {}
    import FreeCAD
    import FreeCADGui

    FreeCADGui.showMainWindow()
    import freecad_addon

    lib = app / "Mod" / "FreeCADAIParts" / "lib"
    results["workbench"] = "AiPartsWorkbench" in FreeCADGui.listWorkbenches()
    results["from_install_dir"] = Path(freecad_addon.__file__).resolve().is_relative_to(lib.resolve())
    results["freecad"] = ".".join(FreeCAD.Version()[:3])

    from engine import golden

    runs = golden.run()
    results["golden"] = f"{sum(r['ok'] for r in runs)}/{len(runs)}"
    golden_ok = bool(runs) and all(r["ok"] for r in runs)

    import gmsh

    import analysis
    from analysis.common import materials
    from analysis.common.solvers import find_ccx

    results["ccx"] = find_ccx()
    step = Path(tempfile.mkdtemp(prefix="fap-acc-")) / "box.step"
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("box")
    gmsh.model.occ.addBox(0, 0, 0, 100, 10, 10)
    gmsh.model.occ.synchronize()
    gmsh.write(str(step))
    gmsh.finalize()
    faces = analysis.run("fea", {"analysis": "faces", "step_path": str(step)})["data"]["faces"]

    def face(x):
        return next(f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][0] - x) < 1e-6)

    r = analysis.run("fea", {"step_path": str(step), "material": "45-QT", "mesh": {"size_mm": 2.5},
                             "loads": [{"type": "fixed", "faces": [face(0)]},
                                       {"type": "force", "faces": [face(100)], "vector_n": [0, 0, -100]}]})
    e = materials.get("45-QT")["elastic_modulus_mpa"]
    theory = 100 * 100 ** 3 / (3 * e * 10 * 10 ** 3 / 12)
    fea_ok = r["status"] == "ok" and abs(r["data"]["u_max_mm"] / theory - 1) < 0.03
    results["fea"] = {"status": r["status"], "u_max_mm": r["data"].get("u_max_mm") if r["status"] == "ok" else None,
                      "theory_mm": round(theory, 5), "messages": r.get("messages")}

    ok = results["workbench"] and results["from_install_dir"] and golden_ok and fea_ok
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print("验收通过" if ok else "验收不通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
