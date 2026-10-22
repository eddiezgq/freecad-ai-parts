# -*- coding: utf-8 -*-
# 问渠工作台（数字工厂企业版第一期，第 8 轮 Q5；学习平台第 39 轮第 5 步加“凸轮”）。
# 安装：把宏包里的 Mod/WenQuest 文件夹复制到 FreeCAD 的用户 Mod 目录（宏包“使用说明.txt”有步骤），重启 FreeCAD，
# 在工作台列表里选“问渠”。工作台的代码在本文件夹的 wq_workbench.py 里。
# 本文件只用顶层语句（不写函数、类、推导式）：FreeCAD 可能用分开的 globals / locals 执行它，Windows 上还没有 __file__
# （freecad-ai-parts 2026-10-09 验收发现；学习平台第 39 轮在 FreeCAD 1.1.3 上复现：函数里看不到同文件的函数）。
import os
import sys

_wq_dir = ""
try:
    _wq_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    pass
for _p in list(sys.path):
    if not _wq_dir and os.path.basename(str(_p).rstrip("/\\")) == "WenQuest":
        _wq_dir = str(_p)
if _wq_dir and _wq_dir not in sys.path:
    sys.path.insert(0, _wq_dir)

import wq_workbench  # noqa: E402

wq_workbench.register()
