"""问渠CAM 用户手册（ADR-0104 产品化第 3 步）：在 FreeCAD 里自动截图，再把 Markdown 转成 Word 和 PDF。

    python scripts/cam_help.py --freecad <FreeCAD 的 python> [--no-shots]

- 截图：每种语言起一个 FreeCAD（xvfb 下），按问渠CAM 版（FAP_EDITION=cam）注册工作台，截四张：
  车削例子算完（面板 + 视图里的刀路与仿真结果）；铣削例子算完（网格）；铣削例子勾上外轮廓、撞平口钳（检查清单）；授权窗口。
  存到 docs/wenquest-cam/help/img/<zh|en>-*.png。截图进程里没有授权：免费版就能做这些。
- 手册：help/zh.md、help/en.md → pandoc → Word（临时）→ LibreOffice → PDF，输出 docs/wenquest-cam/help/ 下的
  问渠CAM用户手册.pdf、WenQuest-CAM-User-Guide.pdf（随安装包放进 docs\\）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELP = ROOT / "docs/wenquest-cam/help"
EX = ROOT / "examples/wenquest-cam"
PDF_NAME = {"zh": "问渠CAM用户手册", "en": "WenQuest-CAM-User-Guide"}
SHOTS = ("turn", "mill", "clash", "license")


def _pump(sec: float) -> None:
    from PySide import QtWidgets

    app = QtWidgets.QApplication.instance()
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _wait(cond, timeout=600) -> None:
    end = time.time() + timeout
    while not cond() and time.time() < end:
        _pump(0.1)


def _save(widget, path: Path) -> None:
    """从屏幕截（xvfb）：widget.grab() 截不到三维视图（OpenGL）"""
    from PySide import QtCore, QtGui

    _pump(1.0)
    top = widget.mapToGlobal(QtCore.QPoint(0, 0))
    pix = QtGui.QGuiApplication.primaryScreen().grabWindow(0, top.x(), top.y(), widget.width(), widget.height())
    pix.save(str(path))
    print("截图", path, flush=True)


def _open(path: Path, label: str):
    import FreeCAD
    import FreeCADGui
    import Part

    doc = FreeCAD.newDocument(label)
    o = doc.addObject("Part::Feature", label)
    o.Shape = Part.read(str(path))
    doc.recompute()
    o.ViewObject.ShapeColor = (0.62, 0.66, 0.72)
    o.ViewObject.Transparency = 60
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(o)
    return doc, o


def _fit() -> None:
    import FreeCADGui

    FreeCADGui.activeDocument().activeView().viewIsometric()
    FreeCADGui.SendMsgToActiveView("ViewFit")


def shots(lang: str, out: Path) -> None:
    import FreeCAD
    import FreeCADGui

    FreeCADGui.showMainWindow()
    mw = FreeCADGui.getMainWindow()
    mw.resize(1600, 1000)
    mw.show()
    from freecad_addon.gui import cam_brand, cam_panel

    cam_brand._start_here = lambda: None
    cam_brand.register()
    FreeCADGui.activateWorkbench(cam_brand.WORKBENCH)
    _pump(1.0)
    # 1 车削
    doc, _o = _open(EX / "01-shaft-turning/shaft.step", "Shaft")
    p = cam_panel.open_panel()
    cam_panel._DOCK.setMinimumWidth(500)
    p.client_factory = lambda: None
    p.read_selection()
    p.threads.setPlainText("0, -26, 24, 1.5")
    p.start_draft(False)
    _wait(lambda: p.draft is not None)
    p.start_run()
    _wait(lambda: p.result is not None)
    _fit()
    _save(mw, out / f"{lang}-turn.png")
    FreeCAD.closeDocument(doc.Name)
    # 2 铣削
    doc, _o = _open(EX / "02-block-milling/block.step", "Block")
    p.kind.setCurrentIndex(1)
    p.read_selection()
    p.mill_ops["profile"].setChecked(False)
    p.lengths.setText("EM10=120, DR8.5=140")
    p.offset.setText("40")
    p.fixture.setText("10")
    p.start_draft(False)
    _wait(lambda: p.draft is not None)
    p.start_run()
    _wait(lambda: p.result is not None)
    _fit()
    _save(mw, out / f"{lang}-mill.png")
    # 3 勾上外轮廓：撞钳口
    p.mill_ops["profile"].setChecked(True)
    p.draft = p.result = None
    p.start_draft(False)
    _wait(lambda: p.draft is not None)
    p.start_run()
    _wait(lambda: p.result is not None)
    sb = cam_panel._DOCK.widget().verticalScrollBar()
    sb.setValue(sb.maximum())
    _pump(0.5)
    _save(cam_panel._DOCK, out / f"{lang}-clash.png")
    FreeCAD.closeDocument(doc.Name)
    # 4 授权
    from PySide import QtCore

    from freecad_addon.gui import fea_brand

    dlg = fea_brand.LicenseDialog(mw, cam_brand.Product).dlg
    dlg.show()
    QtCore.QTimer.singleShot(1500, lambda: (_save(dlg, out / f"{lang}-license.png"), dlg.close()))
    _pump(3.0)


def build_docs(out_dir: Path) -> list[Path]:
    got = []
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    for lang in ("zh", "en"):
        src = HELP / f"{lang}.md"
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td) / f"{PDF_NAME[lang]}.docx"
            subprocess.run(["pandoc", str(src), "-o", str(docx), "--resource-path", str(HELP)], check=True)
            if soffice:
                subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx)],
                               check=True, capture_output=True, timeout=300)
                got.append(out_dir / f"{PDF_NAME[lang]}.pdf")
    return got


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="问渠CAM 用户手册：截图与 Word / PDF")
    ap.add_argument("--freecad", help="FreeCAD 自带的 python（截图用）")
    ap.add_argument("--no-shots", action="store_true")
    ap.add_argument("--shots", nargs=2, metavar=("LANG", "OUT"), help=argparse.SUPPRESS)  # 子进程用
    a = ap.parse_args(argv)
    if a.shots:
        shots(a.shots[0], Path(a.shots[1]))
        return 0
    if not a.no_shots:
        if not a.freecad:
            ap.error("截图要 --freecad")
        (HELP / "img").mkdir(parents=True, exist_ok=True)
        for lang in ("zh", "en"):
            home = Path(tempfile.mkdtemp(prefix="wq-cam-help-home-"))     # 不改本机 FreeCAD 的设置
            env = dict(os.environ, HOME=str(home), FAP_EDITION="cam", FAP_LANG=lang,
                       PYTHONPATH=os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]),
                       FAP_LICENSE_FILE=str(Path(tempfile.gettempdir()) / "wq-cam-help-no-license.json"))
            r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24", a.freecad, str(Path(__file__).resolve()),
                                "--shots", lang, str(HELP / "img")], env=env, timeout=1800, check=False)
            missing = [s for s in SHOTS if not (HELP / "img" / f"{lang}-{s}.png").is_file()]
            if missing:
                print(f"{lang} 截图没出来：{missing}（退出码 {r.returncode}）")
                return 1
    for p in build_docs(HELP):
        print("手册", p)
    return 0


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)
