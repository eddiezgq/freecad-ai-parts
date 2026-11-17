"""问渠有限元用户手册（ADR-0096 第 6 步）：在 FreeCAD 里自动截图，再把 Markdown 转成 Word 和 PDF。

    python scripts/fea_help.py --freecad <FreeCAD 的 python> [--examples /tmp/WenQuest-FEA-examples] [--no-shots]

- 截图：每种语言起一个 FreeCAD（xvfb 下），按问渠有限元版（FAP_EDITION=fea）注册按钮，截 FEM 工作台、材料选择、一句话起草、
  计算结果、授权窗口，存到 docs/wenquest-fea/help/img/<zh|en>-*.png。结果图用 examples/wenquest-fea/build_examples.py
  算好的例子 1（--examples 指它的输出目录）。一句话起草用仓库里的录制回放（不联网）。
- 手册：help/zh.md、help/en.md → pandoc → Word（临时）→ LibreOffice → PDF，输出 docs/wenquest-fea/help/ 下的
  问渠有限元用户手册.pdf、WenQuest-FEA-User-Guide.pdf（随安装包放进 docs\\）。
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
HELP = ROOT / "docs/wenquest-fea/help"
EX = ROOT / "examples/wenquest-fea"
PDF_NAME = {"zh": "问渠有限元用户手册", "en": "WenQuest-FEA-User-Guide"}
SHOTS = ("buttons", "adopt", "draft", "results", "license")


# ------------------------------------------------------------------ 截图（在 FreeCAD 进程里跑）


def _pump(sec: float) -> None:
    from PySide import QtWidgets

    app = QtWidgets.QApplication.instance()
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _save(widget, path: Path) -> None:
    """从屏幕截（xvfb）：widget.grab() 截不到三维视图（OpenGL）"""
    from PySide import QtCore, QtGui

    _pump(1.0)
    top = widget.mapToGlobal(QtCore.QPoint(0, 0))
    pix = QtGui.QGuiApplication.primaryScreen().grabWindow(0, top.x(), top.y(), widget.width(), widget.height())
    pix.save(str(path))
    print("截图", path, flush=True)


def _model_tab() -> None:
    """左边组合视图切到“模型”页（显示模型树）"""
    import FreeCADGui
    from PySide import QtWidgets

    tw = FreeCADGui.getMainWindow().findChild(QtWidgets.QTabWidget, "combiTab")
    if tw is not None:
        tw.setCurrentIndex(0)


def shots(lang: str, out: Path, examples: Path) -> None:
    import FreeCAD
    import FreeCADGui

    FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").SetString(
        "Language", "Chinese Simplified" if lang == "zh" else "English")
    FreeCADGui.showMainWindow()
    from PySide import QtWidgets

    from assist.i18n import tr as T
    from freecad_addon.gui import fea_brand, fem_commands

    fea_brand._start_in_fem = lambda: None
    fea_brand.register()
    mw = FreeCADGui.getMainWindow()
    mw.setGeometry(0, 0, 1600, 1000)
    mw.show()
    FreeCADGui.activateWorkbench("FemWorkbench")
    _pump(1.0)
    solve = next(tb for tb in mw.findChildren(QtWidgets.QToolBar)          # “求解”工具栏单独一行，截图里看得到三个按钮
                 if any(a.text() in (T("一句话起草（AI）"),) for a in tb.actions()))
    mw.addToolBarBreak()
    mw.addToolBar(solve)
    _pump(0.5)

    # 1. FEM 工作台里的按钮：打开例子 1（分析已建好），菜单栏、工具栏、模型树都在
    bdoc = FreeCAD.openDocument(str(EX / "01-j2-housing-free/J2-HSG.FCStd"))
    _pump(1.0)
    for o in bdoc.Objects:          # build_examples.py 不开界面存的文件没有显示状态：在这里补上并存回例子目录
        if o.TypeId.startswith(("Part::Feature", "Fem::Constraint")) and o.ViewObject:
            o.ViewObject.Visibility = True
    bdoc.save()
    _pump(0.5)
    FreeCADGui.SendMsgToActiveView("ViewFit")
    FreeCADGui.activeDocument().activeView().viewIsometric()
    FreeCADGui.SendMsgToActiveView("ViewFit")
    _model_tab()
    _save(mw, out / f"{lang}-buttons.png")

    # 2. 接管手建分析时选材料
    from analysis.common import materials
    from assist import i18n

    dlg = QtWidgets.QInputDialog(mw)
    dlg.setWindowTitle(T("计算并核查"))
    dlg.setLabelText(T("这个分析是用 FEM 工具手建的。选零件的材料（材料库，数值有出处，报告里列明；FEM 自己的材料卡不用）："))
    items = [f"{m['id']} — {i18n.tr(m['name'])}" for m in materials.all_materials()]
    dlg.setComboBoxItems(items)
    dlg.setTextValue(next(x for x in items if x.startswith("6061-T6")))
    dlg.show()
    _save(dlg, out / f"{lang}-adopt.png")
    dlg.close()

    # 3. 一句话起草（录制回放）：RJ-201。截图进程里没有授权：只在这个进程里把专业版功能打开
    from assist import fea_edition

    fea_edition.pro_allowed = lambda: True
    doc = FreeCAD.newDocument("draft_shot")
    import Part

    step = EX / "02-rj201-shaft-sentence/RJ-201.step"
    s = Part.Shape()
    s.read(str(step))
    p = doc.addObject("Part::Feature", "RJ_201")
    p.Shape = s
    p.addProperty("App::PropertyString", "FapStepPath", "Fap", "")
    p.FapStepPath = str(step)
    doc.recompute()
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(p)
    FreeCADGui.runCommand("FAP_FemDraft")
    panel = fem_commands._LAST_PANEL
    panel.text.setPlainText("肩关节空心轴 RJ-201，45 钢调质。Ø70 法兰那一端的端面固定，在 Ø42.75 花键段上加峰值扭矩 92.5 N·m。")
    panel.draft()
    for _ in range(600):
        _pump(0.2)
        if panel.analysis is not None:
            break
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.SendMsgToActiveView("ViewFit")
    FreeCADGui.activeDocument().activeView().viewIsometric()
    FreeCADGui.SendMsgToActiveView("ViewFit")
    _save(mw, out / f"{lang}-draft.png")
    FreeCADGui.Control.closeDialog()
    FreeCAD.closeDocument(doc.Name)

    # 4. 计算结果：例子 1 算好的文件；结果在这个（开着界面的）进程里重新放进 FEM 后处理
    from freecad_addon.fc import fem_flow as F

    rdoc = FreeCAD.openDocument(str(examples / "01-j2-housing-free/J2-HSG.FCStd"))
    _pump(1.0)
    an = next(o for o in rdoc.Objects if o.TypeId == "Fem::FemAnalysis")
    _study, res, wd = F.last_run(an, "截图")
    F.finish_run(an, res, wd)
    rdoc.recompute()
    _pump(1.0)
    for o in rdoc.Objects:
        if not o.ViewObject:
            continue
        if o.TypeId == "Fem::FemPostPipeline":
            o.ViewObject.Visibility = True
            fields = o.ViewObject.getEnumerationsOfProperty("Field") or []
            vm = next((f for f in fields if "mises" in f.lower()), None)
            if vm:
                o.ViewObject.Field = vm
        elif o.TypeId.startswith(("Part::", "Fem::FemMesh", "Fem::Constraint")):
            o.ViewObject.Visibility = False
    FreeCADGui.activeDocument().activeView().viewIsometric()
    FreeCADGui.SendMsgToActiveView("ViewFit")
    _model_tab()
    _save(mw, out / f"{lang}-results.png")

    # 5. 授权窗口
    lic = fea_brand.LicenseDialog(mw)
    lic.dlg.show()
    _save(lic.dlg, out / f"{lang}-license.png")


# ------------------------------------------------------------------ 手册


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
    ap = argparse.ArgumentParser(description="问渠有限元用户手册：截图与 Word / PDF")
    ap.add_argument("--freecad", help="FreeCAD 自带的 python（截图用）")
    ap.add_argument("--examples", type=Path, default=Path("/tmp/WenQuest-FEA-examples"),
                    help="build_examples.py 的输出目录（结果截图用例子 1 算好的文件）")
    ap.add_argument("--no-shots", action="store_true")
    ap.add_argument("--shots", nargs=3, metavar=("LANG", "OUT", "EXAMPLES"), help=argparse.SUPPRESS)  # 子进程用
    a = ap.parse_args(argv)
    if a.shots:
        lang, out, ex = a.shots
        shots(lang, Path(out), Path(ex))
        return 0
    if not a.no_shots:
        if not a.freecad:
            ap.error("截图要 --freecad")
        (HELP / "img").mkdir(parents=True, exist_ok=True)
        for lang in ("zh", "en"):
            home = Path(tempfile.mkdtemp(prefix="wq-help-home-"))     # 不改本机 FreeCAD 的设置
            env = dict(os.environ, HOME=str(home), FAP_EDITION="fea", FAP_LANG=lang, FAP_LLM_REPLAY=str(ROOT / "tests/recordings/fea_draft"),
                       FAP_AI_PROVIDER="claude", PYTHONPATH=os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]),
                       FAP_LICENSE_FILE=str(Path(tempfile.gettempdir()) / "wq-help-no-license.json"))
            r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24", a.freecad, str(Path(__file__).resolve()),
                                "--shots", lang, str(HELP / "img"), str(a.examples)], env=env, timeout=1800, check=False)
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
