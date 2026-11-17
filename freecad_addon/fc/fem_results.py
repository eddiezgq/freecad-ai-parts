"""结果进 FreeCAD 原生后处理（ADR-0093 补充十二第 2 步）。需要 FreeCAD。

本仓库算完（`analysis.fea.run_study(study, keep_dir=…)`）会把各静力 / 模态步最终那次求解的 CalculiX 结果文件留在
`keep_dir/<分析步 id>/job.frd`。这里用 FreeCAD 自带的读取器（`feminout.importCcxFrdResults.importFrd`）读进来：
网格、力学结果对象、VTK 结果管线都是 FEM 工作台的原生对象，剖切、截面、变形放大、等值线、动画、探针直接能用。

结果对象上另记本仓库的结论：可信度、安全系数（或不给的原因）、避开约束面的最大应力及其位置；
可信度不通过 / 未知的，名字上写明。FreeCAD 的“最大 von Mises”是全场最大（含约束面附近的奇异点），
本仓库报告用的是避开约束面的值——两者不同是正常的，任务面板里两个都显示。
"""

from __future__ import annotations

import json
from pathlib import Path

from assist.i18n import tr as T

VERDICT = {"pass": "通过", "fail": "不通过", "unknown": "未知", None: "未知"}


def _prop(obj, name: str, value: str) -> None:
    if name not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", name, T("零件库结论"), T("零件库 / 有限元的结论（只读）"))
        obj.setEditorMode(name, 1)
    setattr(obj, name, value)


def results_to_fem(analysis, result: dict, keep_dir: str | Path) -> dict:
    """把结果读进分析节点。返回 {"results": [对象名…], "pipelines": [对象名…], "skipped": [原因…]}"""
    from feminout import importCcxFrdResults

    doc = analysis.Document
    out: dict[str, list] = {"results": [], "pipelines": [], "skipped": []}
    if result.get("status") != "ok":
        out["skipped"].append("结果没算成，不读")
        return out
    for st in result["data"].get("steps") or []:
        frd = Path(keep_dir) / st["id"] / "job.frd"
        if st["type"] not in ("static", "modal"):
            out["skipped"].append(f"分析步 {st['id']}（{st['type']}）：结果没有逐点场数据可读，看报告里的数值")
            continue
        if not frd.is_file():
            out["skipped"].append(f"分析步 {st['id']}：没有留下结果文件（计算时要给 keep_dir）")
            continue
        before = {o.Name for o in doc.Objects}
        importCcxFrdResults.importFrd(str(frd), analysis, f"{st['id']}_", "frequency" if st["type"] == "modal" else "")
        new = [o for o in doc.Objects if o.Name not in before]
        for o in new:
            if o.TypeId == "Fem::FemResultObjectPython":
                _annotate(o, st)
                out["results"].append(o.Name)
            elif o.TypeId == "Fem::FemPostPipeline":
                out["pipelines"].append(o.Name)
    doc.recompute()
    return out


def _annotate(o, st: dict) -> None:
    tr = st.get("trust") or {}
    v = tr.get("verdict")
    _prop(o, "FapStep", st["id"])
    if st["type"] == "static":
        _prop(o, "FapTrust", T(VERDICT.get(v)) + T("：") + T("；").join(f"{T(i['name'])}{T('：')}{T(VERDICT.get(i['verdict']))}"
                                                                    for i in tr.get("items") or []))
        _prop(o, "FapVmMaxMpa", json.dumps({"value": st.get("vm_max_mpa"), "at_mm": st.get("vm_max_at"),
                                            "note": "避开约束面的最大 von Mises 应力（本仓库报告用这个值）"}, ensure_ascii=False))
        if st.get("safety_factor") is not None:
            _prop(o, "FapSafetyFactor", T(f"{st['safety_factor']}（按{st.get('strength_kind', '')} {st.get('strength_mpa')} MPa）"))
        else:
            _prop(o, "FapSafetyFactor", T("不给：") + T(str(st.get("safety_factor_withheld") or "没有算出")))
        if v != "pass":
            o.Label = T(o.Label + f"（可信度{VERDICT.get(v)}）")
    else:
        _prop(o, "FapTrust", T("模态：频率见报告；振型可在此查看"))
