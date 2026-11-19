"""问渠CAM「数控编程」面板（ADR-0104 产品化第 2 步）：右侧停靠，从上到下 零件 → 机床与材料 → 工艺 → 计算并检查 → 输出。

逻辑在 `freecad_addon/core/cam_study.py`（输入、起草、计算、保存）与 `freecad_addon/fc/cam_doc.py`、`cam_fc.py`（读模型、FreeCAD CAM 刀路、画结果）；
这里只管输入、后台线程与显示。所有显示文字经 T() 中英切换。
"""

from __future__ import annotations

import FreeCAD
import FreeCADGui

from assist.i18n import tr as T
from freecad_addon.core import cam_study as S
from freecad_addon.gui.fem_commands import _in_background

_LAST_PANEL = None
_DOCK = None
COLORS = {"error": "#c62828", "warn": "#b26a00", "unknown": "#6b6b6b"}


def _client():
    from freecad_addon.fc import fem_flow

    return fem_flow.llm_client()


class CamPanel:
    def __init__(self, client_factory=_client):
        from PySide import QtWidgets

        from analysis.cam import machines, postproc, power

        self.client_factory = client_factory
        self.draft: dict | None = None
        self.result: dict | None = None
        self.shape = None
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(T("问渠CAM：数控编程"))
        lay = QtWidgets.QVBoxLayout(self.form)

        # 1. 零件
        box = QtWidgets.QGroupBox(T("1 零件"))
        f = QtWidgets.QFormLayout(box)
        self.kind = QtWidgets.QComboBox()
        self.kind.addItem(T("车削（回转体，轴线沿 Z）"), "turn")
        self.kind.addItem(T("铣削（2.5 轴：型腔、外轮廓、钻孔）"), "mill")
        self.kind.currentIndexChanged.connect(self._kind_changed)
        f.addRow(T("加工方式"), self.kind)
        self.read = QtWidgets.QPushButton(T("从选中零件读取"))
        self.read.clicked.connect(self.read_selection)
        f.addRow("", self.read)
        self.item = QtWidgets.QLineEdit()
        f.addRow(T("零件名"), self.item)
        self.segments = QtWidgets.QLineEdit()
        self.segments.setPlaceholderText(T("各段 直径x长度，从左到右，如 30x40, 40x60"))
        f.addRow(T("外圆各段"), self.segments)
        self.chamfer = QtWidgets.QLineEdit("1")
        f.addRow(T("两端倒角 mm"), self.chamfer)
        self.grooves = QtWidgets.QPlainTextEdit()
        self.grooves.setPlaceholderText(T("每行：槽右边 Z, 槽宽, 槽底直径（Z0 在右端面，向左为负）"))
        self.grooves.setMaximumHeight(48)
        f.addRow(T("槽"), self.grooves)
        self.threads = QtWidgets.QPlainTextEdit()
        self.threads.setPlaceholderText(T("每行：Z 起, Z 止, 大径, 螺距（外螺纹，起刀处要在端面或退刀槽）"))
        self.threads.setMaximumHeight(48)
        f.addRow(T("螺纹"), self.threads)
        self.bore = QtWidgets.QLineEdit()
        self.bore.setPlaceholderText(T("从右端孔口往里：直径x深度, …（没有就空着）"))
        f.addRow(T("内孔"), self.bore)
        self.mill_ops = {k: QtWidgets.QCheckBox(T(t)) for k, t in (("pocket", "型腔"), ("profile", "外轮廓"), ("drill", "钻孔"))}
        row = QtWidgets.QHBoxLayout()
        for c in self.mill_ops.values():
            c.setChecked(True)
            row.addWidget(c)
        self.mill_row = QtWidgets.QWidget()
        self.mill_row.setLayout(row)
        f.addRow(T("铣削工序"), self.mill_row)
        self.part_rows = (self.segments, self.chamfer, self.grooves, self.threads, self.bore)
        lay.addWidget(box)

        # 2. 机床与材料
        box = QtWidgets.QGroupBox(T("2 机床与材料"))
        f = QtWidgets.QFormLayout(box)
        self.machine = QtWidgets.QComboBox()
        try:
            self.models = machines.models()
            self.machine_note = ""
        except machines.MachineError as exc:
            self.models = machines._read_models(machines.EXAMPLE)
            self.machine_note = T("机床文件有误，只列示例机床：{}").format(exc)
        f.addRow(T("机床"), self.machine)
        self.post = QtWidgets.QComboBox()
        f.addRow(T("数控系统"), self.post)
        self.kienzle = QtWidgets.QComboBox()
        for r in power.rows():
            self.kienzle.addItem(f"{r['key']} · {r['material_cn'] or r['material']}（ISO {r['iso_group'] or '—'}）", r["key"])
        i = self.kienzle.findData("C45E")
        self.kienzle.setCurrentIndex(max(i, 0))
        f.addRow(T("工件材料"), self.kienzle)
        self.library = QtWidgets.QLineEdit()
        self.library.setPlaceholderText(T("刀具库文件（空 = 示例刀具库，虚构）"))
        f.addRow(T("刀具库"), self.library)
        self.lengths = QtWidgets.QLineEdit()
        self.lengths.setPlaceholderText(T("铣刀刀长：刀具 id=长度, …，如 EM10=120, DR8.5=140"))
        f.addRow(T("刀长 mm"), self.lengths)
        self.offset = QtWidgets.QLineEdit("40")
        f.addRow(T("工件顶面离工作台 mm"), self.offset)
        self.fixture = QtWidgets.QLineEdit("15, 80")
        f.addRow(T("夹具"), self.fixture)
        self.fixture_label = f.labelForField(self.fixture)
        self._post_items = postproc
        lay.addWidget(box)

        # 3. 工艺
        box = QtWidgets.QGroupBox(T("3 工艺"))
        v = QtWidgets.QVBoxLayout(box)
        row = QtWidgets.QHBoxLayout()
        self.rule = QtWidgets.QPushButton(T("规则起草"))
        self.rule.clicked.connect(lambda: self.start_draft(False))
        self.ai = QtWidgets.QPushButton(T("AI 起草"))
        self.ai.clicked.connect(lambda: self.start_draft(True))
        row.addWidget(self.rule)
        row.addWidget(self.ai)
        row.addStretch(1)
        v.addLayout(row)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([T("工序"), T("刀具"), "vc", "f / fz", "ap", T("核对")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(140)
        v.addWidget(self.table)
        self.notes = QtWidgets.QLabel("")
        self.notes.setWordWrap(True)
        v.addWidget(self.notes)
        lay.addWidget(box)

        # 4. 计算并检查
        box = QtWidgets.QGroupBox(T("4 计算并检查"))
        v = QtWidgets.QVBoxLayout(box)
        self.go = QtWidgets.QPushButton(T("计算并检查（切削仿真、整机仿真、出程序）"))
        self.go.clicked.connect(self.start_run)
        v.addWidget(self.go)
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.checks = QtWidgets.QListWidget()
        self.checks.setMinimumHeight(120)
        v.addWidget(self.checks)
        lay.addWidget(box)

        # 5. 输出
        box = QtWidgets.QGroupBox(T("5 输出"))
        row = QtWidgets.QHBoxLayout(box)
        self.save_btn = QtWidgets.QPushButton(T("保存程序与工艺卡…"))
        self.save_btn.clicked.connect(self.save_dialog)
        self.card = QtWidgets.QCheckBox(T("同时出工艺卡（专业版）"))
        self.card.setChecked(True)
        row.addWidget(self.save_btn)
        row.addWidget(self.card)
        row.addStretch(1)
        lay.addWidget(box)
        self.status = QtWidgets.QLabel(self.machine_note)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addStretch(1)
        # 停靠面板窄：下拉框按 14 个字算宽、输入框不撑宽，表格列按内容（2026-11-19）
        for cb in self.form.findChildren(QtWidgets.QComboBox):
            cb.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(14)
        for le in self.form.findChildren(QtWidgets.QLineEdit):
            le.setMinimumWidth(80)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self._kind_changed()

    # ---------------- 输入 ----------------
    def kind_key(self) -> str:
        return self.kind.currentData()

    def _kind_changed(self):
        k = self.kind_key()
        self.machine.clear()
        for m in self.models:
            ok = m["kind"] == ("lathe" if k == "turn" else "mill") and all(a["type"] == "linear" for a in m["axes"])
            if ok:
                self.machine.addItem(m["name"], m["id"])
        self.post.clear()
        for c in self._post_items.available("lathe" if k == "turn" else "mill"):
            self.post.addItem(self._post_items.POSTS[c]["name"], c)
        for w in self.part_rows:
            w.setEnabled(k == "turn")
        self.mill_row.setEnabled(k == "mill")
        self.offset.setEnabled(k == "mill")
        self.lengths.setEnabled(k == "mill")
        self.fixture.setPlaceholderText(T("卡爪：夹持长度, 外径 mm") if k == "turn" else T("平口钳：夹持高度 mm（空 = 不画钳口）"))
        self.fixture.setText("15, 80" if k == "turn" else "10")
        self.draft = self.result = None
        self.table.setRowCount(0)

    def _selected_shape(self):
        sel = FreeCADGui.Selection.getSelection()
        if not sel or not hasattr(sel[0], "Shape") or sel[0].Shape.isNull():
            raise S.StudyError("先在模型树或三维视图里选中一个零件")
        return sel[0]

    def read_selection(self):
        from freecad_addon.fc import cam_doc

        try:
            obj = self._selected_shape()
            self.shape = obj.Shape.copy()
            self.item.setText(obj.Label)
            if self.kind_key() == "turn":
                ft = cam_doc.turn_features(self.shape)
                self.segments.setText(", ".join(f"{d:g}x{L:g}" for d, L in ft["segments"]))
                self.chamfer.setText(f"{ft['chamfer_mm']:g}")
                self.grooves.setPlainText("\n".join(f"{g['z']:g}, {g['width']:g}, {g['d']:g}" for g in ft["grooves"]))
                self.bore.setText(", ".join(f"{d:g}x{L:g}" for d, L in ft["bore"]))
                self.status.setText(T("已读出外圆 {} 段、槽 {} 个、内孔 {} 段；螺纹在模型上通常不画，请手填").format(
                    len(ft["segments"]), len(ft["grooves"]), len(ft["bore"])))
            else:
                bb = self.shape.BoundBox
                self.status.setText(T("已选零件：{} × {} × {} mm").format(f"{bb.XLength:g}", f"{bb.YLength:g}", f"{bb.ZLength:g}"))
        except (S.StudyError, cam_doc.CamDocError) as exc:
            self.status.setText(T(str(exc)))

    def _lengths(self) -> dict:
        out = {}
        for piece in self.lengths.text().replace("，", ",").split(","):
            if "=" in piece:
                k, v = piece.split("=", 1)
                out[k.strip()] = float(v)
        return out

    def _fixture_nums(self) -> list[float]:
        return [float(x) for x in self.fixture.text().replace("，", ",").split(",") if x.strip()]

    def turn_part(self) -> dict:
        return S.turn_part(item=self.item.text() or "零件", segments=self.segments.text(), chamfer=float(self.chamfer.text() or 0),
                           grooves=self.grooves.toPlainText(), threads=self.threads.toPlainText(), bore=self.bore.text(),
                           machine=self.machine.currentData(), kienzle=self.kienzle.currentData())

    # ---------------- 起草 ----------------
    def start_draft(self, use_ai: bool):
        try:
            work = self._draft_work(use_ai)
        except Exception as exc:  # noqa: BLE001 — 输入错误显示给用户
            self.status.setText(T(str(exc)))
            return
        self.status.setText(T("AI 起草中……") if use_ai else T("起草中……"))
        if self.kind_key() == "mill":
            # FreeCAD CAM 建作业、算刀路要动文档，只能在界面线程里做（后台线程里做会让 FreeCAD 崩溃）
            try:
                out = work()
            except Exception as exc:  # noqa: BLE001
                out = exc
            self.draft_done(out)
            return
        _in_background(work, self.draft_done)

    def _draft_work(self, use_ai: bool):
        lib = self.library.text().strip() or None
        if self.kind_key() == "turn":
            part = self.turn_part()
            client = self.client_factory() if use_ai else None
            if use_ai:
                from assist import cam_edition

                cam_edition.gate(feature="ai")
            return lambda: S.draft(part, client=client, tool_library=lib)
        if use_ai:
            raise S.StudyError("铣削件的 AI 起草还没有（C1 先做车削件），请用规则起草")
        if self.shape is None:
            raise S.StudyError("先选中零件，按“从选中零件读取”")
        shape, mid, iso = self.shape, self.machine.currentData(), S.iso_group(self.kienzle.currentData())
        flags = {k: c.isChecked() for k, c in self.mill_ops.items()}
        lengths = self._lengths()

        def work():
            from analysis.cam import machines
            from analysis.cam import tools as TL
            from freecad_addon.fc import cam_doc, cam_fc

            libd = TL.load(lib) if lib else TL.load()
            plan = cam_doc.mill_plan(shape, libd, iso, max_rpm=float(machines.get(mid)["max_rpm"]), **flags)
            prog, stock = cam_fc.program(shape, plan["ops"])
            ms = {"tools": {str(o["number"]): {"tool": o["tool"]["id"], **({"length_mm": lengths[o["tool"]["id"]]}
                                                                          if o["tool"]["id"] in lengths else {})}
                            for o in plan["ops"]}}
            if lib:
                ms["tool_library"] = lib
            setup = {"mode": "program", "machine": mid, "item": self.item.text() or "零件", "kienzle": self.kienzle.currentData(),
                     "program": prog, "stock": stock, "machine_sim": ms}
            return {"setup": setup, "card": plan["card"], "notes": plan["notes"], "by": "规则（没有用 AI）", "explanation": "",
                    "iso_group": iso}
        return work

    def draft_done(self, out):
        if isinstance(out, Exception):
            self.status.setText(T(str(out)))
            return
        from PySide import QtWidgets

        self.draft, self.result = out, None
        self.table.setRowCount(len(out["card"]))
        for i, c in enumerate(out["card"]):
            p = c["params"]
            feed = p.get("f", p.get("fz"))
            vals = [T(c["title"]), c["tool"], f"{p['vc']:g}", "—" if feed is None else f"{feed:g}",
                    f"{p['ap']:g}" if "ap" in p else "—", T("在样本范围内") if c["status"] == "pass" else T("待确认")]
            for j, v in enumerate(vals):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(v))
        self.notes.setText("\n".join(T(n) for n in out["notes"]) or T("参数都在刀具样本范围内"))
        self.status.setText(T("起草完成：{}").format(T(out["by"])))

    # ---------------- 计算 ----------------
    def setup(self) -> dict:
        if self.draft is None:
            raise S.StudyError("先起草工艺")
        s = dict(self.draft["setup"])
        s["post"] = self.post.currentData()
        ms = dict(s.get("machine_sim") or {})
        nums = self._fixture_nums()
        if s["mode"] == "turn":
            if len(nums) == 2:
                ms["fixtures"] = S.lathe_jaws(s, nums[0], nums[1])
        else:
            ms["work_offset_mm"] = [0.0, 0.0, float(self.offset.text() or 0)]
            if nums:
                ms["fixtures"] = S.vise_jaws(s["stock"], nums[0])
        s["machine_sim"] = ms
        return s

    def start_run(self):
        try:
            setup = self.setup()
        except Exception as exc:  # noqa: BLE001
            self.status.setText(T(str(exc)))
            return
        self.status.setText(T("计算中……"))
        _in_background(lambda: S.run(setup), self.run_done)

    def run_done(self, out):
        from PySide import QtGui, QtWidgets

        if isinstance(out, Exception):
            self.status.setText(T(str(out)))
            return
        self.result = out
        self.summary.setText("\n".join(T(x) for x in S.summary(out)))
        self.checks.clear()
        for c in S.checks(out):
            it = QtWidgets.QListWidgetItem(T(c["text"]))
            it.setForeground(QtGui.QColor(COLORS[c["level"]]))
            self.checks.addItem(it)
        ok = any(p.get("release") for p in out["data"]["programs"])
        self.save_btn.setEnabled(ok)
        self.status.setText(T("算完；可以保存程序") if ok else T("没有正式程序：看上面的红色检查项"))
        try:
            self.show_in_view()
        except Exception as exc:  # noqa: BLE001 — 画图失败不影响结果
            self.status.setText(self.status.text() + "；" + T("视图里没画出来：{}").format(exc))

    def show_in_view(self):
        from analysis.cam import machines, sim
        from freecad_addon.fc import cam_doc

        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("WenQuestCAM")
        cam_doc.clear(doc)
        p = self.result["data"]["programs"][0]
        if not p.get("gcode"):
            return
        m = machines.get(self.result["data"]["machine"]["id"])
        parsed = sim.parse(p["gcode"], m)
        if m["kind"] == "lathe":
            zr = self.shape.BoundBox.ZMax if self.shape is not None else 0.0
            cam_doc.draw_toolpath(doc, parsed, lathe=True, offset=(0, 0, zr))
            s = self.draft["setup"]
            total = sum(L for _, L in s["segments"])
            import math

            gw = float(((s.get("grooves") or [{}])[0]).get("tool_w", 3.0))
            res = sim.simulate_turn(parsed, {"d": float(s.get("stock_d_mm") or math.ceil(max(d for d, _ in s["segments"]) + 4)),
                                             "z_right": 1.0, "z_left": -(total + 1.0)},
                                    {1: {"kind": "turn"}, 2: {"kind": "turn"}, 3: {"kind": "groove", "w": gw}, 4: {"kind": "thread"},
                                     5: {"kind": "drill", "d": float((s.get("bore") or {}).get("drill_d") or 0)}, 6: {"kind": "bore"}})
            cam_doc.draw_turned(doc, res, z_offset=zr)
        else:
            top = self.shape.BoundBox.ZMax if self.shape is not None else 0.0
            cam_doc.draw_toolpath(doc, parsed, lathe=False, offset=(0, 0, top))
            st = self.draft["setup"]["stock"]
            tools = {int(k): v for k, v in p["tools"].items()}
            res = sim.simulate_mill(parsed, {"box": st["box"], "top": 0.0}, tools)
            cam_doc.draw_milled(doc, res, offset=(0, 0, top))
        if FreeCADGui.ActiveDocument is not None:
            FreeCADGui.SendMsgToActiveView("ViewFit")

    # ---------------- 输出 ----------------
    def save_to(self, folder, lang: str = "zh"):
        return S.save(self.result, folder, draft_doc=self.draft if self.card.isChecked() else None, lang=lang)

    def save_dialog(self):
        from PySide import QtWidgets

        if self.result is None:
            self.status.setText(T("先计算并检查"))
            return
        folder = QtWidgets.QFileDialog.getExistingDirectory(self.form, T("保存到哪个文件夹"))
        if not folder:
            return
        try:
            files = self.save_to(folder)
            self.status.setText(T("已保存 {} 个文件到 {}").format(len(files), folder))
        except Exception as exc:  # noqa: BLE001
            self.status.setText(T(str(exc)))


def open_panel() -> CamPanel:
    from PySide import QtCore, QtWidgets

    global _LAST_PANEL, _DOCK
    mw = FreeCADGui.getMainWindow()
    if _DOCK is not None:
        _DOCK.show()
        _DOCK.raise_()
        return _LAST_PANEL
    panel = CamPanel()
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(panel.form)
    dock = QtWidgets.QDockWidget(T("问渠CAM：数控编程"), mw)
    dock.setObjectName("WenQuestCamPanel")
    dock.setWidget(scroll)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    _LAST_PANEL, _DOCK = panel, dock
    return panel


class CamPanelCommand:
    def GetResources(self):
        return {"MenuText": T("数控编程"), "ToolTip": T("车削、2.5 轴铣：起草工艺、切削仿真与整机仿真、出程序与工艺卡")}

    def IsActive(self):
        return True

    def Activated(self):
        open_panel()
