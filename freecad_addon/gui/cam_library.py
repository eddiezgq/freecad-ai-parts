"""问渠CAM 刀具库窗口、机床窗口（ADR-0106 Q4a）。

- 刀具库：选库（示例库只读 + 用户文件夹里的库）；左边刀具表（按种类筛、按 id / 名称搜），右边分页编辑 cam-tool/1 的字段；
  新建（按种类给空模板）、复制、删除、导入 FreeCAD 刀具表（.fctl）；保存前核对（analysis.cam.tools.save），不合格不存、写明哪一项。
  空的格子不写进文件（不写 0）。
- 机床：列出示例与用户机床，看参数，在三维视图里画部件外形（各轴在 0 位）；“复制为我的机床”后改名称、来源、行程、快移、转速、功率、
  换刀时间，保存前核对（analysis.cam.machines.save_model）。
"""

from __future__ import annotations

import copy
from pathlib import Path

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtWidgets

from analysis.cam import machines as M
from analysis.cam import tools as TL
from assist.i18n import tr as T

KIND_CN = {"flat_endmill": "平底立铣刀", "ball_endmill": "球头刀", "bull_endmill": "牛鼻刀", "drill": "钻头", "center_drill": "中心钻",
           "chamfer_mill": "倒角刀", "face_mill": "面铣刀", "tap": "丝锥", "reamer": "铰刀", "thread_mill": "螺纹铣刀",
           "turn": "车刀", "groove": "切槽刀", "thread_turn": "螺纹车刀", "bore": "镗刀"}
# 基本页：(字段, 中文名, 小数位)；空 = 不写
BASIC = (("diameter_mm", "直径 mm", 3), ("corner_radius_mm", "圆角半径 mm", 3), ("flutes", "刃数", 0), ("flute_length_mm", "刃长 mm", 2),
         ("overall_length_mm", "总长 mm", 2), ("stickout_mm", "伸出长 mm", 2), ("shank_diameter_mm", "柄径 mm", 3),
         ("tip_angle_deg", "刀尖角 / 锥角 °", 2), ("tip_diameter_mm", "刀尖直径 mm", 3), ("pitch_mm", "螺距 mm", 4),
         ("thread_angle_deg", "牙型角 °", 2))
INSERT = (("nose_radius_mm", "刀尖圆弧 rε mm", 3), ("width_mm", "刃宽 mm", 3))
CUT_COLS = (("iso_group", "材料组"), ("vc_m_min.min", "vc 下限"), ("vc_m_min.max", "vc 上限"), ("fz_mm.min", "fz 下限"), ("fz_mm.max", "fz 上限"),
            ("f_mm_rev.min", "f 下限"), ("f_mm_rev.max", "f 上限"), ("ap_max_mm", "ap 上限"), ("ae_max_mm", "ae 上限"))


def _mw():
    return FreeCADGui.getMainWindow()


def _num(text: str):
    t = text.strip().replace("，", ".")
    if not t:
        return None
    v = float(t)
    return int(v) if v.is_integer() and "." not in t else v


def _fmt(v) -> str:
    return "" if v is None else f"{v:g}"


class ToolLibraryDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or _mw())
        self.setWindowTitle(T("刀具库"))
        self.resize(1100, 640)
        self.lib, self.path, self.readonly, self.cur = None, None, True, None
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.libs = QtWidgets.QComboBox()
        self.libs.currentIndexChanged.connect(self._open_lib)
        top.addWidget(QtWidgets.QLabel(T("刀具库")))
        top.addWidget(self.libs, 1)
        for text, fn in ((T("新建刀具库…"), self.new_lib), (T("另存为…"), self.save_as), (T("导入 FreeCAD 刀具表…"), self.import_fctl)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            top.addWidget(b)
        lay.addLayout(top)
        split = QtWidgets.QSplitter()
        left = QtWidgets.QWidget()
        ll = QtWidgets.QVBoxLayout(left)
        fl = QtWidgets.QHBoxLayout()
        self.kind_filter = QtWidgets.QComboBox()
        self.kind_filter.addItem(T("全部种类"), "")
        for k in TL.TOOL_KINDS:
            self.kind_filter.addItem(T(KIND_CN[k]), k)
        self.kind_filter.currentIndexChanged.connect(self._fill_table)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(T("按 id、名称搜"))
        self.search.textChanged.connect(self._fill_table)
        fl.addWidget(self.kind_filter)
        fl.addWidget(self.search, 1)
        ll.addLayout(fl)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([T("刀号"), "id", T("种类"), T("直径 / 刀片"), T("名称"), T("来源")])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._select)
        ll.addWidget(self.table, 1)
        bl = QtWidgets.QHBoxLayout()
        self.new_kind = QtWidgets.QComboBox()
        for k in TL.TOOL_KINDS:
            self.new_kind.addItem(T(KIND_CN[k]), k)
        self.btn_new = QtWidgets.QPushButton(T("新建刀具"))
        self.btn_new.clicked.connect(self.new_tool)
        self.btn_copy = QtWidgets.QPushButton(T("复制"))
        self.btn_copy.clicked.connect(self.copy_tool)
        self.btn_del = QtWidgets.QPushButton(T("删除"))
        self.btn_del.clicked.connect(self.delete_tool)
        for w in (self.new_kind, self.btn_new, self.btn_copy, self.btn_del):
            bl.addWidget(w)
        ll.addLayout(bl)
        split.addWidget(left)
        self.tabs = QtWidgets.QTabWidget()
        self._build_form()
        split.addWidget(self.tabs)
        split.setSizes([480, 620])
        lay.addWidget(split, 1)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bot = QtWidgets.QHBoxLayout()
        bot.addStretch(1)
        self.btn_save = QtWidgets.QPushButton(T("保存刀具库"))
        self.btn_save.clicked.connect(self.save)
        close = QtWidgets.QPushButton(T("关闭"))
        close.clicked.connect(self.accept)
        bot.addWidget(self.btn_save)
        bot.addWidget(close)
        lay.addLayout(bot)
        self._reload_libs()

    # ---- 表单
    def _build_form(self):
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.f_id, self.f_name, self.f_number = QtWidgets.QLineEdit(), QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.f_kind = QtWidgets.QComboBox()
        for k in TL.TOOL_KINDS:
            self.f_kind.addItem(T(KIND_CN[k]), k)
        f.addRow("id", self.f_id)
        f.addRow(T("刀号"), self.f_number)
        f.addRow(T("名称"), self.f_name)
        f.addRow(T("种类"), self.f_kind)
        self.f_basic = {}
        for key, cn, _nd in BASIC:
            e = QtWidgets.QLineEdit()
            e.setPlaceholderText(T("空 = 不写"))
            f.addRow(T(cn), e)
            self.f_basic[key] = e
        self.tabs.addTab(w, T("基本"))
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.f_insert = {}
        for key, cn, _nd in INSERT:
            e = QtWidgets.QLineEdit()
            f.addRow(T(cn), e)
            self.f_insert[key] = e
        self.f_iso5608 = QtWidgets.QLineEdit()
        self.f_iso5608.setPlaceholderText("PCLNR 2525 M 12")
        self.f_f = QtWidgets.QLineEdit()
        f.addRow(T("车刀刀杆 ISO 5608 代号"), self.f_iso5608)
        f.addRow(T("刀尖偏距 f mm（厂家样本）"), self.f_f)
        self.tabs.addTab(w, T("刀片与刀杆"))
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.cut = QtWidgets.QTableWidget(0, len(CUT_COLS))
        self.cut.setHorizontalHeaderLabels([T(c) for _k, c in CUT_COLS])
        v.addWidget(QtWidgets.QLabel(T("每个材料组（ISO P / M / K / N / S / H）一行，按刀具样本填；空的格子不写")))
        v.addWidget(self.cut, 1)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton(T("加一行"))
        add.clicked.connect(lambda: self.cut.insertRow(self.cut.rowCount()))
        rm = QtWidgets.QPushButton(T("删所选行"))
        rm.clicked.connect(lambda: [self.cut.removeRow(r) for r in sorted({i.row() for i in self.cut.selectedIndexes()}, reverse=True)])
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch(1)
        v.addLayout(row)
        self.tabs.addTab(w, T("切削参数"))
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.f_src_kind = QtWidgets.QComboBox()
        for k, cn in (("catalog", "厂家样本"), ("enterprise", "企业自己的刀具表"), ("measured", "实测"), ("example", "虚构示例")):
            self.f_src_kind.addItem(T(cn), k)
        self.f_src_ref, self.f_src_page = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.f_src_ref.setPlaceholderText(T("样本名称、版本，或企业刀具表编号"))
        f.addRow(T("来源"), self.f_src_kind)
        f.addRow(T("出处"), self.f_src_ref)
        f.addRow(T("页码"), self.f_src_page)
        self.tabs.addTab(w, T("来源"))

    def _show(self, t: dict | None):
        self.cur = t
        t = t or {}
        self.f_id.setText(t.get("id", ""))
        self.f_name.setText(t.get("name", ""))
        self.f_number.setText(_fmt(t.get("number")))
        self.f_kind.setCurrentIndex(max(self.f_kind.findData(t.get("kind", "flat_endmill")), 0))
        for key, e in self.f_basic.items():
            e.setText(_fmt(t.get(key)))
        ins = t.get("insert") or {}
        for key, e in self.f_insert.items():
            e.setText(_fmt(ins.get(key)))
        h = t.get("holder") or {}
        self.f_iso5608.setText(h.get("iso5608", ""))
        self.f_f.setText(_fmt(h.get("f_mm")))
        rows = t.get("cutting") or []
        self.cut.setRowCount(len(rows))
        for r, c in enumerate(rows):
            for col, (key, _cn) in enumerate(CUT_COLS):
                a, _, b = key.partition(".")
                v = c.get(a)
                v = (v or {}).get(b) if b else v
                self.cut.setItem(r, col, QtWidgets.QTableWidgetItem(v if isinstance(v, str) else _fmt(v)))
        src = t.get("source") or {}
        self.f_src_kind.setCurrentIndex(max(self.f_src_kind.findData(src.get("kind", "enterprise")), 0))
        self.f_src_ref.setText(src.get("ref", ""))
        self.f_src_page.setText(str(src.get("page", "")))
        for w in (self.tabs,):
            w.setEnabled(bool(self.cur) and not self.readonly)

    def form_tool(self) -> dict:
        """表单 → 一把刀（空的不写）；表单里没有的字段（刀柄外形等）沿用原来的"""
        t = copy.deepcopy(self.cur or {})
        t["id"] = self.f_id.text().strip()
        t["kind"] = self.f_kind.currentData()
        for key, val in (("name", self.f_name.text().strip()), ("number", _num(self.f_number.text()))):
            if val in (None, ""):
                t.pop(key, None)
            else:
                t[key] = val
        for key, e in self.f_basic.items():
            v = _num(e.text())
            if v is None:
                t.pop(key, None)
            else:
                t[key] = v
        ins = dict(t.get("insert") or {})
        for k, e in self.f_insert.items():
            v = _num(e.text())
            if v is None:
                ins.pop(k, None)
            else:
                ins[k] = v
        if ins or t["kind"] in TL.TURNING:
            t["insert"] = ins
        else:
            t.pop("insert", None)
        h = dict(t.get("holder") or {})
        for key, val in (("iso5608", self.f_iso5608.text().strip()), ("f_mm", _num(self.f_f.text()))):
            if val in (None, ""):
                h.pop(key, None)
            else:
                h[key] = val
        if h:
            t["holder"] = h
        else:
            t.pop("holder", None)
        rows = []
        for r in range(self.cut.rowCount()):
            c: dict = {}
            for col, (key, _cn) in enumerate(CUT_COLS):
                it = self.cut.item(r, col)
                txt = it.text().strip() if it else ""
                if not txt:
                    continue
                a, _, b = key.partition(".")
                if not b:
                    c[a] = txt if a == "iso_group" else _num(txt)
                else:
                    c.setdefault(a, {})[b] = _num(txt)
            if c:
                rows.append(c)
        if rows:
            t["cutting"] = rows
        else:
            t.pop("cutting", None)
        src = {"kind": self.f_src_kind.currentData(), "ref": self.f_src_ref.text().strip()}
        if self.f_src_page.text().strip():
            p = self.f_src_page.text().strip()
            src["page"] = int(p) if p.isdigit() else p
        t["source"] = src
        return t

    # ---- 库与表
    def _reload_libs(self, select: str | None = None):
        self.libs.blockSignals(True)
        self.libs.clear()
        for x in TL.libraries():
            self.libs.addItem(x["name"] + (T("（只读）") if x["readonly"] else "") + (T("（读不了）") if x["error"] else ""), x["path"])
        self.libs.blockSignals(False)
        i = self.libs.findData(select) if select else 0
        self.libs.setCurrentIndex(max(i, 0))
        self._open_lib()

    def _open_lib(self):
        path = self.libs.currentData()
        self.path = path
        self.readonly = TL.readonly(path)
        try:
            self.lib = TL.load(path)
            self.status.setText((T("示例刀具库是虚构的、只读：要改先“另存为”") if Path(path).resolve() == TL.EXAMPLE.resolve()
                                 else T("厂商样本刀具库只读：要改先“另存为”")) if self.readonly else "")
        except TL.ToolError as exc:
            self.lib = {"format": TL.FORMAT, "name": Path(path).stem, "tools": []}
            self.status.setText(str(exc))
        for b in (self.btn_new, self.btn_copy, self.btn_del, self.btn_save):
            b.setEnabled(not self.readonly)
        self._fill_table()
        self._show(None)

    def _fill_table(self):
        if self.lib is None:
            return
        kind, q = self.kind_filter.currentData(), self.search.text().strip().lower()
        rows = [t for t in self.lib["tools"] if (not kind or t["kind"] == kind)
                and (not q or q in t["id"].lower() or q in t.get("name", "").lower())]
        self.table.setRowCount(len(rows))
        for r, t in enumerate(rows):
            size = _fmt(t.get("diameter_mm")) or (t.get("holder") or {}).get("iso5608", "") or \
                (f"rε{_fmt((t.get('insert') or {}).get('nose_radius_mm'))}" if t.get("insert") else "")
            src = t.get("source") or {}
            vals = [_fmt(t.get("number")), t["id"], T(KIND_CN.get(t["kind"], t["kind"])), size, t.get("name", ""),
                    f"{src.get('ref', '')}" + (f" p.{src['page']}" if src.get("page") else "")]
            for c, v in enumerate(vals):
                it = QtWidgets.QTableWidgetItem(v)
                it.setData(QtCore.Qt.UserRole, t["id"])
                self.table.setItem(r, c, it)

    def _select(self):
        items = self.table.selectedItems()
        if not items:
            return
        if self.cur is not None and not self.readonly:
            self._commit()
        tid = items[0].data(QtCore.Qt.UserRole)
        self._show(next((t for t in self.lib["tools"] if t["id"] == tid), None))

    def _commit(self):
        """把表单写回当前刀具（在库里替换）"""
        if self.cur is None:
            return
        new = self.form_tool()
        for i, t in enumerate(self.lib["tools"]):
            if t is self.cur or t["id"] == self.cur.get("id"):
                self.lib["tools"][i] = new
                self.cur = new
                return

    def _next(self):
        nums = [t.get("number", 0) for t in self.lib["tools"]]
        ids = {t["id"] for t in self.lib["tools"]}
        return max(nums, default=0) + 1, ids

    def new_tool(self, kind: str | None = None):
        self._commit()
        n, ids = self._next()
        kind = kind or self.new_kind.currentData()
        tid = next(f"{kind.upper()}-{k}" for k in range(1, 10000) if f"{kind.upper()}-{k}" not in ids)
        t = TL.template(kind, tid, n)
        self.lib["tools"].append(t)
        self._fill_table()
        self._show(t)
        return t

    def copy_tool(self):
        if self.cur is None:
            return None
        self._commit()
        n, ids = self._next()
        t = copy.deepcopy(self.cur)
        t["id"] = next(f"{t['id']}-{k}" for k in range(2, 10000) if f"{t['id']}-{k}" not in ids)
        t["number"] = n
        self.lib["tools"].append(t)
        self._fill_table()
        self._show(t)
        return t

    def delete_tool(self):
        if self.cur is None:
            return
        self.lib["tools"] = [t for t in self.lib["tools"] if t["id"] != self.cur.get("id")]
        self.cur = None
        self._fill_table()
        self._show(None)

    def save(self, path: str | None = None) -> bool:
        if self.readonly and not path:
            self.status.setText(T("示例刀具库是只读的：另存为自己的刀具库"))
            return False
        self._commit()
        try:
            p = TL.save(self.lib, path or self.path)
        except TL.ToolError as exc:
            self.status.setText(str(exc))
            return False
        self.status.setText(T("已保存：{}").format(p))
        self._reload_libs(str(p))
        return True

    def save_as(self, name: str | None = None) -> bool:
        if name is None:
            name, ok = QtWidgets.QInputDialog.getText(self, T("另存为"), T("刀具库名称"))
            if not ok or not name.strip():
                return False
        self._commit()
        self.lib = {**copy.deepcopy(self.lib), "name": name.strip()}
        self.lib.pop("example", None)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.strip()) or "tools"
        self.readonly = False
        return self.save(str(TL.user_dir() / f"{safe}.json"))

    def new_lib(self, name: str | None = None) -> bool:
        if name is None:
            name, ok = QtWidgets.QInputDialog.getText(self, T("新建刀具库"), T("刀具库名称"))
            if not ok or not name.strip():
                return False
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.strip()) or "tools"
        self.lib = {"format": TL.FORMAT, "name": name.strip(), "tools": []}      # 空库先不存（至少要有一把刀），加了刀再保存
        self.path, self.readonly = str(TL.user_dir() / f"{safe}.json"), False
        for b in (self.btn_new, self.btn_copy, self.btn_del, self.btn_save):
            b.setEnabled(True)
        self._fill_table()
        self._show(None)
        self.status.setText(T("新刀具库“{}”：加了刀再保存").format(name.strip()))
        return True

    def import_fctl(self, path: str | None = None) -> int:
        if self.readonly:
            self.status.setText(T("示例刀具库是只读的：先另存为自己的刀具库再导入"))
            return 0
        if path is None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, T("FreeCAD 刀具表"), "", "FreeCAD tool table (*.fctl *.fctb)")
            if not path:
                return 0
        lib2, skipped = TL.from_freecad(path)
        n, ids = self._next()
        added = 0
        for t in lib2["tools"]:
            if t["id"] in ids:
                continue
            t["number"] = n + added
            self.lib["tools"].append(t)
            added += 1
        self._fill_table()
        self.status.setText(T("导入 {} 把刀；跳过：{}").format(added, "、".join(skipped) or T("无")))
        return added


# ---------------------------------------------------------------- 机床
MACHINE_EDIT = (("spindle.max_rpm", "最高转速 r/min"), ("spindle.power_kw", "主电机功率 kW"), ("spindle.efficiency", "传动效率"),
                ("tool_change_s", "换刀时间 s"))


def machine_text(m: dict) -> str:
    """机床参数的文字说明（窗口里看）"""
    sp = m.get("spindle") or {}
    lines = [f"{m['name']}（{m['id']}）" + (T("——虚构示例") if m.get("example") else ""),
             T("种类：{}；数控系统：{} {}").format({"lathe": T("数控车床"), "mill": T("加工中心"), "mill_turn": T("车铣中心")}[m["kind"]],
                                              (m.get("controller") or {}).get("family", "—"), (m.get("controller") or {}).get("model", "")),
             T("主轴：最高 {} r/min，功率 {} kW").format(_fmt(sp.get("max_rpm")) or "—", _fmt(sp.get("power_kw")) or "—"),
             T("换刀时间：{} s").format(_fmt(m.get("tool_change_s")) or "—")]
    if m["kind"] in ("lathe", "mill_turn"):
        hm = m.get("lathe_home_mm") or [None, None]
        lines.append(T("换刀点：X{}（直径）Z{}").format(_fmt(hm[0]) or "—", _fmt(hm[1]) or "—"))
    for a in m.get("axes") or []:
        unit = "°" if a["type"] == "rotary" else "mm"
        lines.append(T("{} 轴（{}，{}）：{} ~ {} {}，快移 {}").format(
            a["id"], T("直线轴") if a["type"] == "linear" else T("回转轴"), T("带刀具动") if a.get("carrier") == "tool" else T("带工件动"),
            _fmt(a.get("min")) or "—", _fmt(a.get("max")) or "—", unit, _fmt(a.get("rapid")) or "—"))
    lines.append(T("来源：{}").format(m.get("source", "—")))
    return "\n".join(lines)


def draw_machine(m: dict, doc=None) -> list:
    """在三维视图里画出机床部件的外形（各轴在 0 位）：盒、圆柱、网格；返回画出的对象"""
    import Mesh
    import Part

    doc = doc or FreeCAD.ActiveDocument or FreeCAD.newDocument("Machine")
    V = FreeCAD.Vector
    out = []
    for c in m.get("components") or []:
        name = f"M_{m['id']}_{c['id']}".replace("-", "_")
        if "box_mm" in c:
            x0, y0, z0, x1, y1, z1 = c["box_mm"]
            o = doc.addObject("Part::Feature", name)
            o.Shape = Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))
        elif "cylinder_mm" in c:
            cy = c["cylinder_mm"]
            p0, p1 = V(*cy["p0"]), V(*cy["p1"])
            o = doc.addObject("Part::Feature", name)
            o.Shape = Part.makeCylinder(cy["r"], (p1 - p0).Length, p0, p1 - p0)
        elif "mesh" in c:
            p = Path(m.get("_dir") or ".") / c["mesh"]
            if not p.is_file():
                continue
            o = doc.addObject("Mesh::Feature", name)
            o.Mesh = Mesh.Mesh(str(p))
        else:
            continue
        o.Label = c.get("name", c["id"])
        out.append(o)
    doc.recompute()
    return out


class MachineDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or _mw())
        self.setWindowTitle(T("机床"))
        self.resize(900, 560)
        self.cur = None
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        self.list = QtWidgets.QListWidget()
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list, 1)
        for text, fn in ((T("在视图里画出来"), self.draw), (T("复制为我的机床…"), self.copy)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            left.addWidget(b)
        lay.addLayout(left, 1)
        right = QtWidgets.QVBoxLayout()
        self.info = QtWidgets.QPlainTextEdit()
        self.info.setReadOnly(True)
        right.addWidget(self.info, 1)
        self.form_box = QtWidgets.QGroupBox(T("改参数（只有自己的机床能改）"))
        self.form = QtWidgets.QFormLayout(self.form_box)
        right.addWidget(self.form_box, 1)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.btn_save = QtWidgets.QPushButton(T("保存"))
        self.btn_save.clicked.connect(self.save)
        close = QtWidgets.QPushButton(T("关闭"))
        close.clicked.connect(self.accept)
        row.addWidget(self.btn_save)
        row.addWidget(close)
        right.addLayout(row)
        lay.addLayout(right, 2)
        self.fields: dict = {}
        self._reload()

    def _reload(self, select: str | None = None):
        self.models = M.models()
        self.list.blockSignals(True)
        self.list.clear()
        for m in self.models:
            self.list.addItem(m["name"] + (T("（示例）") if m.get("example") else ""))
        self.list.blockSignals(False)
        i = next((k for k, m in enumerate(self.models) if m["id"] == select), 0)
        self.list.setCurrentRow(i)
        self._select(i)

    def _select(self, i: int):
        if i < 0 or i >= len(self.models):
            return
        self.cur = copy.deepcopy(self.models[i])
        self.info.setPlainText(machine_text(self.cur))
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = {}
        mine = not self.cur.get("example")
        if mine:
            self._add("name", T("名称"), self.cur.get("name", ""))
            self._add("source", T("来源（厂家资料页码 / 谁哪天测的）"), self.cur.get("source", ""))
            for key, cn in MACHINE_EDIT:
                a, _, b = key.partition(".")
                v = (self.cur.get(a) or {}).get(b) if b else self.cur.get(a)
                self._add(key, T(cn), _fmt(v))
            if self.cur["kind"] in ("lathe", "mill_turn"):      # 换刀点（规格页一般不写，按实机填，ADR-0106 E2）
                hm = self.cur.get("lathe_home_mm") or [None, None]
                self._add("home.x", T("换刀点 X（直径）mm"), _fmt(hm[0]))
                self._add("home.z", T("换刀点 Z mm"), _fmt(hm[1]))
            for ax in self.cur.get("axes") or []:
                for k in ("min", "max", "rapid"):
                    self._add(f"axis.{ax['id']}.{k}", f"{ax['id']} " + {"min": T("行程下限"), "max": T("行程上限"), "rapid": T("快移")}[k],
                              _fmt(ax.get(k)))
        self.form_box.setEnabled(mine)
        self.btn_save.setEnabled(mine)
        self.status.setText("" if mine else T("示例机床是虚构的：要改先“复制为我的机床”"))

    def _add(self, key, label, value):
        e = QtWidgets.QLineEdit(value)
        self.form.addRow(label, e)
        self.fields[key] = e

    def form_model(self) -> dict:
        m = copy.deepcopy(self.cur)
        for key, e in self.fields.items():
            txt = e.text().strip()
            if key in ("name", "source"):
                if txt:
                    m[key] = txt
                continue
            if key in ("home.x", "home.z"):
                continue
            if key.startswith("axis."):
                _, aid, k = key.split(".")
                ax = next(a for a in m["axes"] if a["id"] == aid)
                v = _num(txt)
                if v is None:
                    ax.pop(k, None)
                else:
                    ax[k] = float(v)
                continue
            a, _, b = key.partition(".")
            v = _num(txt)
            if b:
                d = m.setdefault(a, {})
                if v is None:
                    d.pop(b, None)
                else:
                    d[b] = float(v)
            elif v is None:
                m.pop(a, None)
            else:
                m[a] = float(v)
        if "home.x" in self.fields:
            hx, hz = _num(self.fields["home.x"].text().strip()), _num(self.fields["home.z"].text().strip())
            if hx is None or hz is None:
                m.pop("lathe_home_mm", None)
            else:
                m["lathe_home_mm"] = [float(hx), float(hz)]
        return m

    def save(self) -> bool:
        try:
            p = M.save_model(self.form_model())
        except M.MachineError as exc:
            self.status.setText(str(exc))
            return False
        self.status.setText(T("已保存：{}").format(p))
        self._reload(self.cur["id"])
        return True

    def copy(self, new_id: str | None = None, name: str | None = None) -> bool:
        if self.cur is None:
            return False
        if new_id is None:
            new_id, ok = QtWidgets.QInputDialog.getText(self, T("复制为我的机床"), T("机床编号（字母、数字、- _）"))
            if not ok or not new_id.strip():
                return False
            name, ok = QtWidgets.QInputDialog.getText(self, T("复制为我的机床"), T("机床名称"))
            if not ok:
                return False
        try:
            p = M.save_model(M.copy_model(self.cur["id"], new_id.strip(), (name or new_id).strip()))
        except M.MachineError as exc:
            self.status.setText(str(exc))
            return False
        self._reload(new_id.strip())
        self.status.setText(T("已复制到 {}：按实机改好行程、转速后保存").format(p))
        return True

    def draw(self):
        if self.cur is not None:
            draw_machine(self.cur)
            FreeCADGui.SendMsgToActiveView("ViewFit")


class ToolLibraryCommand:
    def GetResources(self):
        return {"MenuText": T("刀具库…"), "ToolTip": T("看、改刀具库：新建、复制、删除刀具，导入 FreeCAD 刀具表；保存前按刀具库格式核对")}

    def Activated(self):
        ToolLibraryDialog().exec_()

    def IsActive(self):
        return True


class MachineCommand:
    def GetResources(self):
        return {"MenuText": T("机床…"), "ToolTip": T("看机床参数、画机床外形；复制为自己的机床后改行程、转速")}

    def Activated(self):
        MachineDialog().exec_()

    def IsActive(self):
        return True


def register() -> None:
    FreeCADGui.addCommand("FAP_CamTools", ToolLibraryCommand())
    FreeCADGui.addCommand("FAP_CamMachines", MachineCommand())


def library_choices() -> list[tuple[str, str]]:
    """作业面板“刀具库”下拉的选项：(显示名, 路径)；示例库的路径记为空（与以前一样）"""
    out = []
    for x in TL.libraries():
        out.append((x["name"] + (T("（只读）") if x["readonly"] else ""), "" if x["readonly"] else x["path"]))
    return out

