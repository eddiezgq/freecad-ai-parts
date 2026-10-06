# -*- coding: utf-8 -*-
"""
问渠数字工厂 · 把 FreeCAD 里的零件提交到工厂（企业版第一期，第 8 轮 Q5）

在 FreeCAD 里：先在模型树里选中要提交的零件（实体），再执行本宏（或点“问渠”工具栏的“提交到问渠工厂”）。
对话框里填物料编号和改动说明；有 TechDraw 图纸页的会一并导出 PDF；可选附上 G 代码并选工序。
生产（企业）模式：进“设计发布与审批”待审，审批人批准后才进 ERPNext 和车间；教学模式：提交即生效。

不开 FreeCAD 也能用（便于测试、批量提交）：
  python wq_submit.py <物料编号> <STEP 文件> [改动说明]
地址和登录凭证读 wq_publish.py 的 CONFIG（“设计与工艺”页下载的宏包里已填好）。
"""
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import wq_publish  # noqa: E402

CFG = wq_publish.CONFIG


def _token():
    return CFG.get("token") or wq_publish.login(CFG["hub"].rstrip("/"), CFG["name"], CFG["mode"])


def item_info(item, token=None):
    req = urllib.request.Request("{}/api/plm/item/{}".format(CFG["hub"].rstrip("/"), urllib.parse.quote(item)),
                                 headers={"x-wq-token": token or _token()})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ValueError(json.loads(e.read() or b"{}").get("detail") or "物料 {} 不存在".format(item)) from None


def multipart(fields, files):
    """fields: {名: 值}；files: {名: (文件名, 字节, 类型)} → (body, content-type)"""
    b = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append("--{}\r\nContent-Disposition: form-data; name=\"{}\"\r\n\r\n{}\r\n".format(b, k, v).encode("utf-8"))
    for k, (fn, data, mime) in files.items():
        out.append("--{}\r\nContent-Disposition: form-data; name=\"{}\"; filename=\"{}\"\r\nContent-Type: {}\r\n\r\n"
                   .format(b, k, fn, mime).encode("utf-8") + data + b"\r\n")
    out.append("--{}--\r\n".format(b).encode())
    return b"".join(out), "multipart/form-data; boundary=" + b


def submit(item, step_bytes, note="", drawing=None, gcode=None, operation="", token=None):
    files = {"step": (item + ".step", step_bytes, "application/step")}
    if drawing:
        files["drawing"] = (item + "-drawing.pdf", drawing, "application/pdf")
    if gcode:
        files["gcode"] = (item + ".nc", gcode, "text/plain")
    body, ctype = multipart({"item": item, "note": note, "operation": operation}, files)
    req = urllib.request.Request(CFG["hub"].rstrip("/") + "/api/plm/submit", data=body, method="POST",
                                 headers={"Content-Type": ctype, "x-wq-token": token or _token()})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ValueError(json.loads(e.read() or b"{}").get("detail") or "提交失败（{}）".format(e.code)) from None


def page_url(res):
    return "{}/design/{}".format(CFG["hub"].rstrip("/"), res["id"])


# ---------------------------------------------------------------- FreeCAD 界面
def _export(obj):
    """选中的零件 → STEP 字节；文档里有 TechDraw 图纸页的，导出第一页为 PDF"""
    import FreeCAD as App
    import Import
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "part.step")
    Import.export([obj], p)
    step = open(p, "rb").read()
    pdf = None
    pages = [o for o in App.ActiveDocument.Objects if o.TypeId == "TechDraw::DrawPage"]
    if pages:
        try:
            import TechDrawGui
            q = os.path.join(tmp, "drawing.pdf")
            TechDrawGui.exportPageAsPdf(pages[0], q)
            pdf = open(q, "rb").read()
        except Exception:  # noqa: BLE001 —— 图纸导不出来不影响提交模型
            pdf = None
    return step, pdf, bool(pages)


def run_dialog():
    import FreeCADGui as Gui
    from PySide import QtGui
    sel = [o for o in Gui.Selection.getSelection() if hasattr(o, "Shape") and o.Shape.Solids]
    if not sel:
        QtGui.QMessageBox.information(None, "问渠工厂", "请先在模型树里选中要提交的零件（实体）。")
        return
    obj = sel[0]
    dlg = QtGui.QDialog()
    dlg.setWindowTitle("提交到问渠工厂 · " + obj.Label)
    lay = QtGui.QFormLayout(dlg)
    item = QtGui.QLineEdit(getattr(obj, "WQ_Item", "") or "")
    info = QtGui.QLabel("")
    note = QtGui.QPlainTextEdit()
    gfile = QtGui.QLineEdit()
    gbtn = QtGui.QPushButton("选 G 代码文件…")
    op = QtGui.QComboBox()
    ok = QtGui.QPushButton("提交")
    for label, w in (("物料编号", item), ("", info), ("改动说明", note), ("加工程序（可选）", gfile), ("", gbtn), ("工序", op), ("", ok)):
        lay.addRow(label, w)
    state = {}

    def check():
        try:
            state["info"] = item_info(item.text().strip())
            info.setText("{} · 现行 rev {}".format(state["info"]["name"], state["info"]["revision"]))
            op.clear()
            op.addItems(state["info"]["operations"])
        except Exception as e:  # noqa: BLE001
            state.pop("info", None)
            info.setText(str(e))

    def pick():
        f, _ = QtGui.QFileDialog.getOpenFileName(dlg, "选 G 代码", "", "G 代码 (*.nc *.gcode *.ngc *.tap *.txt)")
        if f:
            gfile.setText(f)

    def go():
        if "info" not in state:
            check()
            if "info" not in state:
                return
        step, pdf, had_page = _export(obj)
        g = open(gfile.text(), "rb").read() if gfile.text() else None
        try:
            res = submit(item.text().strip(), step, note.toPlainText(), pdf, g, op.currentText() if g else "")
        except Exception as e:  # noqa: BLE001
            QtGui.QMessageBox.warning(dlg, "提交失败", str(e))
            return
        if not hasattr(obj, "WQ_Item"):
            obj.addProperty("App::PropertyString", "WQ_Item", "WenQuest", "问渠工厂物料编号")
        obj.WQ_Item = item.text().strip()
        msg = "已发布 rev {}".format(res["revision"]) if res["status"] == "approved" else "已提交审批"
        if had_page and not pdf:
            msg += "（图纸页没导出成 PDF，只提交了模型）"
        QtGui.QMessageBox.information(dlg, "问渠工厂", "{}。\n在网页上查看：{}".format(msg, page_url(res)))
        dlg.accept()
    item.editingFinished.connect(check)
    gbtn.clicked.connect(pick)
    ok.clicked.connect(go)
    if item.text():
        check()
    dlg.exec_()


def main(argv):
    if len(argv) >= 2:
        r = submit(argv[0], open(argv[1], "rb").read(), " ".join(argv[2:]))
        print("{}：{}".format("已发布 rev {}".format(r["revision"]) if r["status"] == "approved" else "已提交审批", page_url(r)))
        return 0
    print(__doc__)
    return 1


try:
    import FreeCADGui  # noqa: F401
    _GUI = True
except ImportError:
    _GUI = False

if __name__ == "__main__":
    if _GUI:
        run_dialog()
    else:
        sys.exit(main(sys.argv[1:]))
