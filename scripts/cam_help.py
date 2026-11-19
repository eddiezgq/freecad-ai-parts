"""问渠CAM 用户手册（ADR-0104 产品化第 3 步）：在 FreeCAD 里自动截图，再把 Markdown 转成 Word 和 PDF。

    python scripts/cam_help.py --freecad <FreeCAD 的 python> [--no-shots]

- 截图：每种语言起一个 FreeCAD（xvfb 下），按问渠CAM 版（FAP_EDITION=cam）注册工作台，用加工树界面（ADR-0106 Q1）截七张：
  车削例子算完（作业面板 + 视图里的刀路）；工序面板 vc 超范围变红；铣削例子算完（加工树）；
  铣削例子新建“铣外轮廓”、撞平口钳（检查清单）；回放跳到撞钳口的那一段；去掉外轮廓后的色差图；授权窗口。
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
SHOTS = ("turn", "op", "mill", "clash", "replay", "deviation", "license")


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


def _confirm_all(CO, job) -> None:
    for s in CO.setups(job):
        for o in CO.ops(s):
            if o.Status != "已确认":
                CO.confirm(o)


def _hide_report(mw) -> None:
    """截图时关掉报告视图，回放窗口占满下方"""
    from PySide import QtWidgets

    for d in mw.findChildren(QtWidgets.QDockWidget):
        if d.windowTitle().replace("&", "") in ("Report view", "报告视图"):
            d.hide()


def _expand_tree(mw) -> None:
    import FreeCADGui
    from PySide import QtCore, QtWidgets

    FreeCADGui.Selection.clearSelection()
    for tw in mw.findChildren(QtWidgets.QTabWidget):                # 组合视图切到“模型”页
        for i in range(tw.count()):
            if tw.tabText(i).replace("&", "") in ("Model", "模型"):
                tw.setCurrentIndex(i)
    _pump(0.3)
    for t in mw.findChildren(QtWidgets.QTreeWidget):
        t.expandAll()
        t.resizeColumnToContents(0)
    for d in mw.findChildren(QtWidgets.QDockWidget):             # FreeCAD 1.0：“模型”“任务”是并排成页签的两个停靠窗
        if d.windowTitle().replace("&", "") in ("Model", "模型") and d.isVisible() or d.windowTitle() == "Model":
            d.raise_()
            mw.resizeDocks([d], [420], QtCore.Qt.Horizontal)
    _pump(0.3)


def shots(lang: str, out: Path) -> None:
    """加工树界面（ADR-0106 Q1）：新建作业 → 作业面板起草 → 模型树里确认工序 → 计算并检查"""
    import FreeCAD
    import FreeCADGui
    from PySide import QtCore

    FreeCADGui.showMainWindow()
    mw = FreeCADGui.getMainWindow()
    mw.resize(1600, 1000)
    mw.show()
    from freecad_addon.fc import cam_objects as CO
    from freecad_addon.gui import cam_brand
    from freecad_addon.gui import cam_tree_panels as P

    cam_brand._start_here = lambda: None
    cam_brand.register()
    FreeCADGui.activateWorkbench(cam_brand.WORKBENCH)
    _pump(1.0)
    # 1 车削：新建车削作业 → 起草 → 确认 → 计算
    doc, _o = _open(EX / "01-shaft-turning/shaft.step", "Shaft")
    P.NewJobCommand("turn").Activated()
    jp = P._LAST
    jp.threads.setPlainText("0, -26, 24, 1.5")
    jp.do_draft(False)
    job = jp.job
    _confirm_all(CO, job)
    jp.do_calculate()
    FreeCADGui.Selection.clearSelection()
    _fit()
    _save(mw, out / f"{lang}-turn.png")
    # 2 工序面板：vc 超出刀具样本范围，变红、不能确认
    P._close()
    op_panel = P.edit(CO.ops(CO.setups(job)[0])[0])
    op_panel.tabs.setCurrentIndex(op_panel.tabs.count() - 1)
    op_panel.vc.setValue(400)
    FreeCADGui.Selection.clearSelection()
    _pump(0.5)
    _save(mw, out / f"{lang}-op.png")
    P._close()
    FreeCAD.closeDocument(doc.Name)
    # 3 铣削
    doc, _o = _open(EX / "02-block-milling/block.step", "Block")
    P.NewJobCommand("mill").Activated()
    jp = P._LAST
    jp.lengths.setText("EM10=120, DR8.5=140")
    jp.offset.setValue(40)
    jp.fixture.setText("10")
    jp.do_draft(False)
    job = jp.job
    _confirm_all(CO, job)
    jp.do_calculate()
    P._close()                                                     # 关掉面板：截加工树（作业 → 装夹 → 工序）
    _pump(0.5)
    _expand_tree(mw)
    _fit()
    _save(mw, out / f"{lang}-mill.png")
    # 4 新建工序“铣外轮廓”：铣到底撞平口钳，不出程序
    CO.add_op(CO.setups(job)[0], "profile")
    _confirm_all(CO, job)
    jp = P.edit(job)
    jp.do_calculate()
    _pump(0.5)
    _save(mw, out / f"{lang}-clash.png")
    # 5 回放：跳到撞钳口的那一段（程序窗口高亮那一行，视图里刀具在撞的位置）
    from freecad_addon.gui import cam_replay

    P._close()
    _hide_report(mw)
    dock = cam_replay.open_for(job)
    mw.resizeDocks([dock.dock], [300], QtCore.Qt.Vertical)
    ev = next((e for e in dock.rp.events if e["level"] == "error"), None)
    if ev is not None:
        dock.goto_frame(ev["i"])
    job.Model.ViewObject.Visibility = False          # 看在制毛坯
    _expand_tree(mw)
    _fit()
    _save(mw, out / f"{lang}-replay.png")
    dock.close()
    # 6 色差：去掉外轮廓，算完的铣削件与零件模型比
    prof = [o for o in CO.ops(CO.setups(job)[0]) if o.OpKind == "profile"]
    for o in prof:
        doc.removeObject(o.Name)
    CO.calculate(job)
    job.Model.ViewObject.Visibility = True
    dock = cam_replay.open_for(job)
    mw.resizeDocks([dock.dock], [300], QtCore.Qt.Vertical)
    dock.dev.setChecked(True)
    _pump(0.5)
    job.Model.ViewObject.Visibility = False
    for s_ in CO.setups(job):
        for o in CO.ops(s_):
            o.ViewObject.Visibility = False
    _fit()
    _save(mw, out / f"{lang}-deviation.png")
    dock.close()
    FreeCAD.closeDocument(doc.Name)
    # 7 授权
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
