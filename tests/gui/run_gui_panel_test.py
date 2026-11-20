# AI part design panel GUI check (plan 0.3d). Run inside the WenQuest CAD GUI, with the user's own settings and layout:
#   set WQCAD_OUT=...\logs\gui-panel.json
#   FreeCAD.exe run_gui_panel_test.py
# Activates the AI Parts workbench (library and check panels), clicks "AI part design", keeps the event loop running for
# a few seconds and checks that the panel window is visible, inside the screen and the main window still responds.
# If the UI freezes, this script never writes its result and tests-wqcad.ps1 stops the process after the time limit
# and reports NOT OK (2026-11-19: the docked panel froze WenQuest CAD 1.1.4).
import json
import os
import time
import traceback

import FreeCADGui
from PySide import QtCore, QtWidgets

out = os.environ["WQCAD_OUT"]
res = {"steps": []}


def finish(ok):
    res["ok"] = ok
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("WQCAD-GUI-PANEL", "panel", res.get("panel"), "inside_screen", res.get("inside_screen"),
          "responsive_ms", res.get("responsive_ms"), "OK" if ok else "NOT OK", flush=True)
    os._exit(0 if ok else 1)


def pump(seconds):
    t = time.time()
    while time.time() - t < seconds:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.02)


def run():
    try:
        FreeCADGui.activateWorkbench("AiPartsWorkbench")
        res["steps"].append("workbench")
        pump(2)
        mw = FreeCADGui.getMainWindow()
        if os.environ.get("WQCAD_WIDE"):                 # 主窗口比屏幕宽（2026-11-19 卡死时的布局）；用 os._exit 结束，不存这个尺寸
            area = QtWidgets.QApplication.primaryScreen().availableGeometry()
            mw.showNormal()
            mw.setGeometry(area.left() - 10, area.top(), area.width() + 400, area.height())
            pump(1)
        res["main_window"] = [mw.width(), mw.height()]
        FreeCADGui.runCommand("FAP_AiDesign")
        res["steps"].append("command")
        pump(3)
        win = mw.findChild(QtWidgets.QWidget, "FapAiDesignPanel")
        res["panel"] = bool(win is not None and win.isVisible())
        area = (win.screen() if win is not None and hasattr(win, "screen") else QtWidgets.QApplication.primaryScreen()).availableGeometry()
        res["inside_screen"] = bool(win is not None and area.contains(win.frameGeometry().topLeft()) and win.width() <= area.width())
        t = time.time()
        QtWidgets.QApplication.processEvents()        # 主窗口还在处理事件
        res["responsive_ms"] = round((time.time() - t) * 1000)
        finish(res["panel"] and res["inside_screen"])
    except Exception:
        res["error"] = traceback.format_exc()
        finish(False)


QtCore.QTimer.singleShot(3000, run)
