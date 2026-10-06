# -*- coding: utf-8 -*-
# 问渠工作台（数字工厂企业版第一期，第 8 轮 Q5）：FreeCAD 工具栏上的“提交到问渠工厂”“插入零件库标准件”。
# 安装：把宏包里的 Mod/WenQuest 文件夹复制到 FreeCAD 的用户 Mod 目录（宏包“使用说明.txt”有步骤），重启 FreeCAD，
# 在工作台列表里选“问渠”。宏文件就在本文件夹里，地址和登录凭证已由宏包填好。
import os
import sys

import FreeCAD
import FreeCADGui


def _here():
    for base in (FreeCAD.getUserAppDataDir(), getattr(FreeCAD, "getUserModDir", lambda: "")()):
        for p in (os.path.join(base, "Mod", "WenQuest"), os.path.join(base, "WenQuest")):
            if os.path.exists(os.path.join(p, "wq_submit.py")):
                return p
    return os.path.dirname(os.path.abspath(globals().get("__file__", "."))) if "__file__" in globals() else "."


class _Cmd:
    def __init__(self, module, text, tip):
        self.module, self.text, self.tip = module, text, tip

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip}

    def Activated(self):
        d = _here()
        if d not in sys.path:
            sys.path.insert(0, d)
        import importlib
        importlib.import_module(self.module).run_dialog()

    def IsActive(self):
        return True


FreeCADGui.addCommand("WQ_Submit", _Cmd("wq_submit", "提交到问渠工厂", "把选中的零件（STEP + 图纸）提交到问渠数字工厂：企业模式进审批"))
FreeCADGui.addCommand("WQ_Library", _Cmd("wq_library", "插入零件库标准件", "从问渠零件与机器人库搜索并插入标准件"))


class WenQuestWorkbench(FreeCADGui.Workbench):
    MenuText = "问渠"
    ToolTip = "问渠数字工厂：提交设计、插入零件库标准件"

    def Initialize(self):
        self.appendToolbar("问渠", ["WQ_Submit", "WQ_Library"])
        self.appendMenu("问渠", ["WQ_Submit", "WQ_Library"])

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(WenQuestWorkbench())
