# -*- coding: utf-8 -*-
"""
问渠零件库 · FreeCAD 插入宏（零件库第 5 轮 P10①）

在 FreeCAD 里：宏 → 宏… → 选中本文件 → 执行。弹出“问渠零件库”对话框：
  1. 输入编号、名称、标准号或尺寸（如 6207、GB/T 1096、M8x25）搜索；
  2. 选中一个族、再选规格，点“插入”——下载该族的 STEP 压缩包（缓存在 ~/.wenquest/library），把这个规格插入当前文档；
  3. 改规格：先在模型树里选中插入过的零件，再执行本宏，对话框直接打开这个族，选新规格点“替换”，位置保持不变。
插入的零件带两个属性：WQ_LibraryRef（编号/规格）、WQ_LibraryVersion（零件库版本），ERPNext 物料上的“零件库编号”就是这个编号。
标准件（A 部分）和机器人零部件（D 部分，外形示意）有 STEP；机器人（B）、机构（C）只有网页模型，宏会提示到网页上看。

不开 FreeCAD 也能用（便于测试、批量下载）：
  python wq_library.py search 6207
  python wq_library.py fetch A-BRG-DG/6207          # 打印 STEP 文件路径
"""
import json
import os
import re
import sys
import urllib.request
import zipfile

CONFIG = {
    "library": os.environ.get("WQ_LIBRARY_URL", "https://factory.wenquestrobotics.com"),   # 零件库地址（latest.json 所在的站点）
    "cache": os.path.join(os.path.expanduser("~"), ".wenquest", "library"),
    "timeout": 60,
}


def _get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": "wq-library-freecad/1"})
    with urllib.request.urlopen(req, timeout=CONFIG["timeout"]) as r:
        data = r.read()
    return data if binary else json.loads(data.decode("utf-8"))


class Library:
    def __init__(self, base=None, cache=None):
        self.base = (base or CONFIG["library"]).rstrip("/")
        self.cache = cache or CONFIG["cache"]
        self.latest = _get(self.base + "/library/latest.json")
        self.version = self.latest["version"]
        self.index = _get(self.base + "/" + self.latest["index"])
        self._entries = {}

    # ---- 查找
    def families(self):
        out = {}
        for it in self.index.get("items", []):
            f = out.setdefault(it["id"], {"id": it["id"], "part": it["part"], "kind": it.get("kind"),
                                          "name": (it.get("family") or it["name"]).get("zh"), "standards": it.get("standards") or [],
                                          "sizes": [], "erp": []})
            f["sizes"].append(str(it.get("size", "default")))
            f["erp"] += it.get("erp_items") or []
        return out

    def search(self, text, limit=40):
        """编号、名称、标准号、规格、工厂物料号；多个词都要命中。返回 [(族, 命中的规格或 None)]"""
        words = [w for w in re.split(r"\s+", (text or "").strip().lower()) if w]
        out = []
        for f in self.families().values():
            hay = " ".join([f["id"], f["name"] or ""] + f["standards"] + f["erp"]).lower()
            sizes = [s for s in f["sizes"] if all(w in hay or w in s.lower() for w in words) and any(w in s.lower() for w in words)]
            if words and sizes:                                # 有规格命中（如 6207）就直接定到规格
                exact = [s for s in sizes if s.lower() in words]
                out.append((f, (exact or sizes)[0]))
            elif words and all(w in hay for w in words):
                out.append((f, None))
        out.sort(key=lambda x: (x[1] is None, x[0]["part"], x[0]["id"]))
        return out[:limit]

    def entry(self, eid):
        if eid not in self._entries:
            self._entries[eid] = _get("{}/library/{}/{}/entry.json".format(self.base, self.version, eid))
        return self._entries[eid]

    def has_step(self, eid):
        e = self.entry(eid)
        return "step" in (e.get("model") or {}).get("formats", []) and str(e.get("package", "")).endswith(".zip")

    # ---- STEP
    def step(self, ref):
        """编号/规格 → 本地 STEP 文件路径（下载并缓存该族的压缩包）"""
        eid, _, size = ref.partition("/")
        e = self.entry(eid)
        if not self.has_step(eid):
            raise ValueError("{} 没有 STEP（机器人、机构请到网页上看或下载 glTF/URDF）".format(eid))
        size = size or str(e.get("default"))
        row = next((s for s in e.get("sizes") or [] if str(s["size"]) == size), None)
        if row is None:
            raise KeyError("{} 没有规格 {}".format(eid, size))
        code = os.path.splitext(os.path.basename(row["files"]["glb"]))[0]
        folder = os.path.join(self.cache, self.version)
        os.makedirs(folder, exist_ok=True)
        zpath = os.path.join(folder, eid + ".zip")
        if not os.path.exists(zpath):
            data = _get(e["package"], binary=True)
            tmp = zpath + ".part"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, zpath)
        out = os.path.join(folder, eid, code + ".step")
        if not os.path.exists(out):
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with zipfile.ZipFile(zpath) as z:
                with z.open(code + ".step") as src, open(out, "wb") as dst:
                    dst.write(src.read())
        return out


# ---------------------------------------------------------------- FreeCAD 界面
def _insert(lib, ref, replace=None):
    import FreeCAD as App
    import Part
    doc = App.ActiveDocument or App.newDocument("WenQuest")
    shape = Part.read(lib.step(ref))
    if replace is not None:
        replace.Shape = shape
        obj = replace
    else:
        obj = doc.addObject("Part::Feature", re.sub(r"[^A-Za-z0-9_]", "_", ref))
        obj.Shape = shape
        for prop in ("WQ_LibraryRef", "WQ_LibraryVersion"):
            obj.addProperty("App::PropertyString", prop, "WenQuest", "问渠零件库")
    obj.WQ_LibraryRef, obj.WQ_LibraryVersion = ref, lib.version
    obj.Label = "{} {}".format(lib.entry(ref.split("/")[0])["name"]["zh"], ref.split("/")[1] if "/" in ref else "")
    doc.recompute()
    return obj


def run_dialog():
    import FreeCADGui as Gui
    from PySide import QtGui
    lib = Library()
    sel = [o for o in Gui.Selection.getSelection() if hasattr(o, "WQ_LibraryRef")]
    target = sel[0] if sel else None

    dlg = QtGui.QDialog()
    dlg.setWindowTitle("问渠零件库 v" + lib.version)
    lay = QtGui.QVBoxLayout(dlg)
    box = QtGui.QLineEdit()
    box.setPlaceholderText("编号、名称、标准号、规格，如 6207、GB/T 1096、M8x25")
    fams = QtGui.QListWidget()
    sizes = QtGui.QComboBox()
    note = QtGui.QLabel("")
    btn = QtGui.QPushButton("替换为这个规格" if target else "插入")
    for w in (box, fams, QtGui.QLabel("规格"), sizes, note, btn):
        lay.addWidget(w)
    found = []

    def refresh():
        fams.clear()
        found[:] = lib.search(box.text())
        for f, s in found:
            fams.addItem("{}  {}{}".format(f["id"], f["name"], "  ·  " + s if s else ""))
        if found:
            fams.setCurrentRow(0)

    def pick():
        i = fams.currentRow()
        if i < 0 or i >= len(found):
            return
        f, s = found[i]
        sizes.clear()
        sizes.addItems(f["sizes"])
        if s:
            sizes.setCurrentIndex(f["sizes"].index(s))
        ok = lib.has_step(f["id"])
        note.setText("" if ok else "这个条目没有 STEP（机器人、机构请到网页上看）")
        btn.setEnabled(ok)

    def go():
        i = fams.currentRow()
        if i < 0:
            return
        ref = "{}/{}".format(found[i][0]["id"], sizes.currentText())
        _insert(lib, ref, replace=target)
        dlg.accept()
    box.textChanged.connect(refresh)
    fams.currentRowChanged.connect(lambda _: pick())
    btn.clicked.connect(go)
    if target:                                            # 改规格：直接打开这个族
        box.setText(target.WQ_LibraryRef.split("/")[0])
        refresh()
        pick()
        size = target.WQ_LibraryRef.split("/")[1] if "/" in target.WQ_LibraryRef else ""
        if size in [sizes.itemText(k) for k in range(sizes.count())]:
            sizes.setCurrentIndex([sizes.itemText(k) for k in range(sizes.count())].index(size))
    dlg.exec_()


def main(argv):
    if len(argv) >= 2 and argv[0] == "search":
        lib = Library()
        for f, s in lib.search(" ".join(argv[1:])):
            print("{}\t{}\t{}".format(f["id"] if not s else "{}/{}".format(f["id"], s), f["name"], len(f["sizes"])))
        return 0
    if len(argv) == 2 and argv[0] == "fetch":
        print(Library().step(argv[1]))
        return 0
    print(__doc__)
    return 1


try:                                                       # 在 FreeCAD 界面里执行时弹对话框
    import FreeCADGui  # noqa: F401
    _GUI = True
except ImportError:
    _GUI = False

if __name__ == "__main__":
    if _GUI:
        run_dialog()
    else:
        sys.exit(main(sys.argv[1:]))
