# -*- coding: utf-8 -*-
"""问渠工作台的命令和工作台本身（InitGui.py 只负责找到本文件夹并调 register()）。

按钮按文件夹里有哪些宏出现：数字工厂宏包带“提交到问渠工厂”“插入零件库标准件”（wq_submit.py、wq_library.py）；
问渠凸轮的 FreeCAD 包带“凸轮”（wq_cam.py，学习平台第 39 轮第 5 步）。两个包可以解压到同一个文件夹。
"""
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

CMDS = [("WQ_Submit", "wq_submit", "提交到问渠工厂", "把选中的零件（STEP + 图纸）提交到问渠数字工厂：企业模式进审批"),
        ("WQ_Library", "wq_library", "插入零件库标准件", "从问渠零件与机器人库搜索并插入标准件"),
        ("WQ_Cam", "wq_cam", "凸轮", "打开问渠凸轮的项目：重算校核，建实体（含弧面凸轮精确实体），凸轮系统装配，出工作图")]


def available():
    return [c for c in CMDS if os.path.exists(os.path.join(HERE, c[1] + ".py"))]


class Command:
    def __init__(self, module, text, tip):
        self.module, self.text, self.tip = module, text, tip

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip}

    def Activated(self):
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        importlib.import_module(self.module).run_dialog()

    def IsActive(self):
        return True


def register():
    import FreeCADGui

    names = []
    for name, module, text, tip in available():
        FreeCADGui.addCommand(name, Command(module, text, tip))
        names.append(name)

    class WenQuestWorkbench(FreeCADGui.Workbench):
        MenuText = "问渠"
        ToolTip = "问渠：提交设计、插入零件库标准件、凸轮设计"

        def Initialize(self):
            self.appendToolbar("问渠", names)
            self.appendMenu("问渠", names)

        def GetClassName(self):
            return "Gui::PythonWorkbench"

    FreeCADGui.addWorkbench(WenQuestWorkbench())
