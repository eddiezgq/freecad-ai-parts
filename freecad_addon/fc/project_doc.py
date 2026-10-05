"""方案记录对象（ADR-0049 第 2 条）：布局文档中的隐藏对象 FapProject，以 JSON 字符串保存方案，随 .FCStd 一起保存。

只在 FreeCAD 中导入。记录的内容与读写校验在 core/project.py。
"""

from __future__ import annotations

import FreeCAD

OBJECT = "FapProject"


def write(doc, text: str) -> None:
    obj = doc.getObject(OBJECT)
    if obj is None:
        obj = doc.addObject("App::FeaturePython", OBJECT)
        obj.Label = "AI Parts 方案记录"
        obj.addProperty("App::PropertyString", "Record", "AI Parts", "方案记录 fap-project/1（JSON）")
        obj.setEditorMode("Record", 1)
        if FreeCAD.GuiUp and getattr(obj, "ViewObject", None) is not None:
            obj.ViewObject.Visibility = False
    if obj.Record != text:
        obj.Record = text


def read(doc) -> str | None:
    obj = doc.getObject(OBJECT)
    return getattr(obj, "Record", None) if obj is not None else None
