"""问渠多体动力学用户手册（ADR-0102 第 5 步）：在 FreeCAD 里自动截图，再把 Markdown 转成 Word 和 PDF。

    python scripts/mbd_help.py --freecad <FreeCAD 的 python> [--no-shots]

- 先跑 examples/wenquest-mbd/build_examples.py --samples（例子 1 的 FreeCAD 文件、例子 3 的模型文件要在例子目录里）。
- 截图：每种语言起一个 FreeCAD（xvfb 下），按问渠多体动力学版（FAP_EDITION=mbd）注册工作台，截四张：
  导入机械臂 STEP、AI 挑运动副（录制回放，不联网）；曲柄滑块的结果（曲线、动画）；打开推杆模型文件算模态；授权窗口。
  存到 docs/wenquest-mbd/help/img/<zh|en>-*.png。截图进程里没有授权：只在这个进程里把专业版功能打开。
  顺带把例子 1、2 的 FreeCAD 文件补上显示状态再存回（不开界面存的文件打开后零件看不见）。
- 手册：help/zh.md、help/en.md → pandoc → Word（临时）→ LibreOffice → PDF，输出 docs/wenquest-mbd/help/ 下的
  问渠多体动力学用户手册.pdf、WenQuest-MBD-User-Guide.pdf（随安装包放进 docs\\）。
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
HELP = ROOT / "docs/wenquest-mbd/help"
EX = ROOT / "examples/wenquest-mbd"
PDF_NAME = {"zh": "问渠多体动力学用户手册", "en": "WenQuest-MBD-User-Guide"}
SHOTS = ("step", "results", "file", "license")


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


def _fit() -> None:
    import FreeCADGui

    FreeCADGui.activeDocument().activeView().viewIsometric()
    FreeCADGui.SendMsgToActiveView("ViewFit")


def _show_parts(doc) -> None:
    """不开界面存的文件没有显示状态：零件和装起它们的装配体都要设成可见"""
    for o in doc.Objects:
        if o.ViewObject and (o.TypeId.startswith("Part::Feature") or o.TypeId == "Assembly::AssemblyObject"):
            o.ViewObject.Visibility = True
            if o.TypeId.startswith("Part::Feature"):
                o.ViewObject.ShapeColor = (0.62, 0.66, 0.72)


def shots(lang: str, out: Path) -> None:
    import warnings

    import FreeCAD
    import FreeCADGui

    warnings.filterwarnings("ignore")                  # matplotlib 的提示会在 FreeCAD 里弹通知，挡住截图
    FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").SetString(
        "Language", "Chinese Simplified" if lang == "zh" else "English")
    FreeCADGui.showMainWindow()
    from assist import mbd_edition
    from freecad_addon.gui import fea_brand, mbd_brand, workbench

    mbd_brand._start_here = lambda: None
    mbd_brand.register()
    mbd_edition.pro_allowed = lambda: True
    mw = FreeCADGui.getMainWindow()
    mw.setGeometry(0, 0, 1600, 1000)
    mw.show()
    FreeCADGui.activateWorkbench(mbd_brand.WORKBENCH)
    _pump(1.0)

    FreeCADGui.runCommand("FAP_MbdAssembly")
    panel = workbench._state["mbd_asm"]
    panel.setMinimumWidth(640)
    panel.cands.setMinimumHeight(110)
    _pump(0.5)

    # 1. 导入机械臂 STEP，AI 挑运动副（录制回放）
    doc2 = FreeCAD.newDocument("Arm")
    panel.use_ai.setChecked(True)
    panel.load_step(str(EX / "02-arm-ai/arm.step"), doc2)
    panel.cands.resizeColumnsToContents()
    _fit()
    _save(mw, out / f"{lang}-step.png")
    panel.use_ai.setChecked(False)
    for d in list(FreeCAD.listDocuments().values()):
        FreeCAD.closeDocument(d.Name)

    # 2. 曲柄滑块的结果：例子 1 的 FreeCAD 文件（装配体建好、材料给好）
    doc = FreeCAD.openDocument(str(EX / "01-slider-crank-free/slider-crank.FCStd"))
    _pump(1.0)
    _show_parts(doc)
    doc.save()
    panel.load_document(doc)
    lab = {o.Name: o.Label for o in doc.Objects}
    drive = next(j["id"] for j in panel.model["joints"] if j["body_i"] == "ground" and lab.get(j["body_j"]) == "曲柄")
    panel.set_drive(drive, "speed", 1200)
    panel.kind.setCurrentIndex(panel.kind.findData("kinematic"))
    panel.end.setText("0.05")
    panel.steps.setText("200")
    panel.compute()
    _wait(lambda: not panel.busy)
    k = next(i for i in range(panel.curve.count()) if str(panel.curve.itemData(i)).startswith("驱动"))
    panel.curve.setCurrentIndex(k)
    panel.slider.setValue(60)
    _fit()
    _save(mw, out / f"{lang}-results.png")
    panel.restore()

    # 3. 打开推杆模型文件，先静平衡再线性化
    for d in list(FreeCAD.listDocuments().values()):
        FreeCAD.closeDocument(d.Name)
    panel.load_model_file(str(EX / "03-pushrod-buckling/pushrod-push60.json"))
    panel.compute()
    _wait(lambda: not panel.busy)
    _save(mw, out / f"{lang}-file.png")

    # 4. 授权窗口
    lic = fea_brand.LicenseDialog(mw, mbd_brand.Product)
    lic.dlg.show()
    _save(lic.dlg, out / f"{lang}-license.png")
    lic.dlg.close()

    if lang == "zh":                     # 例子 2 的 FreeCAD 文件也补上显示状态
        p2 = EX / "02-arm-ai/arm.FCStd"
        if p2.is_file():
            d2 = FreeCAD.openDocument(str(p2))
            _pump(0.5)
            _show_parts(d2)
            d2.save()


def build_docs(out_dir: Path) -> list[Path]:
    got = []
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    for lang in ("zh", "en"):
        src = HELP / f"{lang}.md"
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td) / f"{PDF_NAME[lang]}.docx"
            # 不加目录：pandoc 生成的目录是 Word 域，LibreOffice 转 PDF 时不更新，会是空的
            subprocess.run(["pandoc", str(src), "-o", str(docx), "--resource-path", str(HELP)], check=True)
            if soffice:
                subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx)],
                               check=True, capture_output=True, timeout=300)
                got.append(out_dir / f"{PDF_NAME[lang]}.pdf")
    return got


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="问渠多体动力学用户手册：截图与 Word / PDF")
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
            home = Path(tempfile.mkdtemp(prefix="wq-mbd-help-home-"))     # 不改本机 FreeCAD 的设置
            env = dict(os.environ, HOME=str(home), FAP_EDITION="mbd", FAP_LANG=lang,
                       FAP_LLM_REPLAY=str(ROOT / "tests/recordings/mbd_mates"), FAP_AI_PROVIDER="claude",
                       PYTHONPATH=os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]),
                       FAP_LICENSE_FILE=str(Path(tempfile.gettempdir()) / "wq-mbd-help-no-license.json"))
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
