"""录屏演示（ADR-0093 补充十二第 3 步验收）：在 FreeCAD 里从一句话走到 Word 报告。

用法（Linux，需要 xvfb 与 ffmpeg；在 FreeCAD 自带的 Python 里跑）：
    FONTCONFIG_FILE=/etc/fonts/fonts.conf FAP_LLM_REPLAY=tests/recordings/fea_draft \\
    xvfb-run -a -s "-screen 0 1600x1000x24" $FC/usr/bin/python scripts/demo_fem_flow.py docs/videos/f7-fem-flow.mp4

AI 的回复用 tests/recordings/fea_draft 里真实模型的录制回放（这台机器没有密钥），画面上标明“回放”。
其余都是真的：FEM 工作台的按钮、核对、确认、CalculiX 计算与三层网格核查、FreeCAD 原生后处理、Word / PDF 报告。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STATEMENT = "肩关节空心轴 RJ-201，45 钢调质。Ø70 法兰那一端的端面固定，在 Ø42.75 花键段上加峰值扭矩 92.5 N·m。"


def main(out: str) -> int:
    import FreeCAD
    import FreeCADGui
    from PySide import QtCore, QtGui, QtWidgets

    FreeCADGui.showMainWindow()
    app = QtWidgets.QApplication.instance()
    mw = FreeCADGui.getMainWindow()
    mw.setGeometry(0, 0, 1600, 1000)
    mw.show()

    def pump(sec=0.5):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    cap = QtWidgets.QLabel(mw)
    cap.setStyleSheet("background: rgba(20,40,80,220); color: white; font-size: 22px; padding: 10px;")
    cap.setGeometry(380, 70, 900, 56)

    def say(text, sec=2.5):
        cap.setText(text)
        cap.raise_()
        cap.show()
        pump(sec)

    from freecad_addon.gui import fem_commands

    fem_commands.register()
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", "12", "-video_size", "1600x1000",
                           "-i", os.environ.get("DISPLAY", ":99"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                           out], stdin=subprocess.PIPE)
    try:
        import Part

        tmp = Path(FreeCAD.getUserAppDataDir()) / "fap_demo"
        tmp.mkdir(parents=True, exist_ok=True)
        doc = FreeCAD.newDocument("RJ201_demo")
        doc.saveAs(str(tmp / "RJ201_demo.FCStd"))
        step = ROOT / "examples/apps/out/cobot_joint/RJ-201.step"
        s = Part.Shape()
        s.read(str(step))
        part = doc.addObject("Part::Feature", "RJ201")
        part.Shape = s
        part.Label = "RJ-201 肩关节空心轴"
        part.addProperty("App::PropertyString", "FapStepPath", "Fap", "")
        part.FapStepPath = str(step)
        doc.recompute()
        FreeCADGui.activateWorkbench("FemWorkbench")
        v = FreeCADGui.activeDocument().activeView()
        v.viewIsometric()
        v.fitAll()
        say("FreeCAD 自带的 FEM 工作台；“一句话起草”“计算并核查”“出报告”三个按钮在“运行求解器”前面", 4)

        FreeCADGui.Selection.addSelection(part)
        FreeCADGui.runCommand("FAP_FemDraft")
        pump(1)
        panel = FreeCADGui.Control.activeDialog() and fem_commands._LAST_PANEL
        say("选中零件，写一句话（AI 回复为真实模型的录制回放）", 2)
        for i in range(0, len(STATEMENT) + 1, 3):
            panel.text.setPlainText(STATEMENT[:i])
            pump(0.08)
        panel.text.setPlainText(STATEMENT)
        pump(1)
        panel.go.click()
        t0 = time.time()
        while panel.analysis is None and time.time() - t0 < 120:
            pump(0.2)
        say("AI 起草、程序逐项核对：固定是 FEM 自带的约束，扭矩是零件库的对象；追问与未采用的提议列在面板里", 5)
        panel.by.setText("演示工程师")
        pump(0.8)
        panel.ok.click()
        say("工程师确认后才能算（不代签）", 3)
        FreeCADGui.Control.closeDialog()
        pump(0.5)

        an = panel.analysis
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(an)
        boxes: list = []

        def close_boxes():
            for w in app.topLevelWidgets():
                if isinstance(w, QtWidgets.QMessageBox) and w.isVisible():
                    boxes.append(w.text())
                    QtCore.QTimer.singleShot(3500, w.accept)

        timer = QtCore.QTimer()
        timer.timeout.connect(close_boxes)
        timer.start(500)
        say("计算并核查：CalculiX 计算，三层网格收敛、反力平衡、网格质量、奇异点核查（约一分钟）", 2)
        FreeCADGui.runCommand("FAP_FemRun")
        t0 = time.time()
        while not boxes and time.time() - t0 < 600:
            pump(0.3)
        pump(4)
        timer.stop()
        for o in doc.Objects:
            if o.TypeId == "Part::Feature" and o.ViewObject:
                o.ViewObject.Visibility = False
        pipe = next(o for o in doc.Objects if o.TypeId == "Fem::FemPostPipeline")
        pipe.ViewObject.Field = "von Mises Stress"
        pipe.ViewObject.DisplayMode = "Surface"
        v.viewIsometric()
        v.fitAll()
        say("结果在 FreeCAD 原生后处理里：结果名写明“可信度不通过”（轴肩处疑似奇异点，安全系数不给）", 5)
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(pipe)
        FreeCADGui.runCommand("FEM_PostFilterClipRegion")
        pump(1)
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(pipe)
        FreeCADGui.runCommand("FEM_PostCreateFunctions", 0)
        pump(1)
        plane = next(o for o in doc.Objects if o.TypeId == "Fem::FemPostPlaneFunction")
        plane.Normal = FreeCAD.Vector(1, 0, 0)
        clip = next(o for o in doc.Objects if o.TypeId == "Fem::FemPostClipFilter")
        clip.Function = plane
        doc.recompute()
        pump(1)
        clip.ViewObject.Field = "von Mises Stress"
        clip.ViewObject.DisplayMode = "Surface"
        pipe.ViewObject.Visibility = False
        if plane.ViewObject:
            plane.ViewObject.Visibility = False
        doc.recompute()
        say("用 FEM 工作台自带的“剖切”看内部", 4)

        answers = iter(["QR-FEA-DEMO-001", "A", "首次出稿"])
        QtWidgets.QInputDialog.getText = staticmethod(lambda *a, **k: (next(answers), True))
        QtWidgets.QMessageBox.question = staticmethod(lambda *a, **k: QtWidgets.QMessageBox.No)
        boxes.clear()
        timer.start(500)
        say("出报告：报告编号 QR-FEA-DEMO-001、版次 A", 2)
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(an)
        FreeCADGui.runCommand("FAP_FemReport")
        t0 = time.time()
        while not boxes and time.time() - t0 < 300:
            pump(0.3)
        pump(4)
        timer.stop()
        pdf = next(Path(an.FapWorkDir).glob("*.pdf"), None)
        if pdf:
            import pymupdf

            d = pymupdf.open(str(pdf))
            win = QtWidgets.QLabel()
            win.setWindowTitle(pdf.name)
            img = QtGui.QImage.fromData(d[0].get_pixmap(dpi=80).tobytes("png"))
            win.setPixmap(QtGui.QPixmap.fromImage(img))
            win.setGeometry(500, 40, img.width(), min(img.height(), 950))
            win.show()
            pump(6)
            win.setPixmap(QtGui.QPixmap.fromImage(QtGui.QImage.fromData(d[min(5, d.page_count - 1)].get_pixmap(dpi=80).tobytes("png"))))
            pump(6)
            win.close()
        say("报告：结论、算例与依据、核查、云图、审核清单、可追溯信息；页眉“草稿，须工程师审核”", 4)
        print("消息框：", boxes)
    finally:
        ff.communicate(b"q", timeout=60)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "f7-fem-flow.mp4"))
