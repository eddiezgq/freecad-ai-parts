"""装配体多体动力学窗口（ADR-0097 D5c，补充十二；D8b 补充二十二）：STEP 导入与运动副草稿确认、驱动与分析设置、
柔性零件、计算、核查结论、曲线、动画（柔性零件画变形与应力云图）、计算报告。

流程逻辑在 freecad_addon/core/mbd_study.py；这里只管界面。计算在后台线程，不卡界面。
"""

from __future__ import annotations

import threading

import FreeCAD as App
from PySide import QtCore, QtWidgets

from assist.i18n import tr as T
from freecad_addon.core import mbd_study as ST


class _TrLabel(QtWidgets.QLabel):
    """显示前按界面语言翻的标签（状态栏、核查结论；ADR-0102 第 2 步）"""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setText(text)

    def setText(self, text):
        super().setText(T(text))


def _localize(root):
    """窗口建好以后把固定文字按界面语言翻一遍：标题、按钮、勾选框、分组、标签、提示、表头、下拉项（数据不变）"""
    if hasattr(root, "windowTitle"):
        root.setWindowTitle(T(root.windowTitle()))
    for w in root.findChildren(QtWidgets.QWidget):
        if isinstance(w, QtWidgets.QGroupBox):
            w.setTitle(T(w.title()))
        elif isinstance(w, (QtWidgets.QPushButton, QtWidgets.QCheckBox)) or isinstance(w, QtWidgets.QLabel) and not isinstance(w, _TrLabel):
            w.setText(T(w.text()))
        elif isinstance(w, QtWidgets.QTableWidget):
            w.setHorizontalHeaderLabels([T(w.horizontalHeaderItem(c).text()) for c in range(w.columnCount())
                                         if w.horizontalHeaderItem(c) is not None])
        elif isinstance(w, QtWidgets.QComboBox):
            for k in range(w.count()):
                w.setItemText(k, T(w.itemText(k)))
        if w.toolTip():
            w.setToolTip(T(w.toolTip()))


class MbdAssemblyPanel(QtWidgets.QDockWidget):
    done = QtCore.Signal(object)

    def __init__(self, parent=None, client_factory=None):
        super().__init__("装配体多体动力学", parent)
        self.setObjectName("FapMbdAssemblyPanel")
        self.client_factory = client_factory          # 返回 LLM 客户端；None 时只用规则草稿
        self.doc = None
        self.assembly = None
        self.objs, self.found, self.draft = [], None, None
        self.model, self.data, self.animator = None, None, None
        self.model_file, self.model_dir = None, None         # 打开的模型文件（ADR-0102 第 5 步）
        self.busy = False
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)

        # 1 装配体
        box1 = QtWidgets.QGroupBox("1 装配体")
        l1 = QtWidgets.QVBoxLayout(box1)
        row = QtWidgets.QHBoxLayout()
        self.use_doc = QtWidgets.QPushButton("用当前文档的装配体")
        self.import_step = QtWidgets.QPushButton("导入 STEP 并起草运动副…")
        self.open_model = QtWidgets.QPushButton("打开模型文件…")
        self.open_model.setToolTip("mbd-model/1 的 JSON 模型文件：控制器、接触、大变形梁等窗口里没有入口的功能写在模型文件里，打开就能算、出报告")
        self.use_ai = QtWidgets.QCheckBox("用 AI 起草")
        row.addWidget(self.use_doc)
        row.addWidget(self.import_step)
        row.addWidget(self.open_model)
        row.addWidget(self.use_ai)
        l1.addLayout(row)
        self.cands = QtWidgets.QTableWidget(0, 5)
        self.cands.setHorizontalHeaderLabels(["收", "名称", "类型", "零件", "几何证据"])
        self.cands.verticalHeader().setVisible(False)
        l1.addWidget(self.cands)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("机架"))
        self.ground = QtWidgets.QComboBox()
        row.addWidget(self.ground, 1)
        self.build_btn = QtWidgets.QPushButton("确认，建成装配体")
        self.build_btn.setEnabled(False)
        row.addWidget(self.build_btn)
        l1.addLayout(row)
        lay.addWidget(box1)

        # 2 驱动与分析
        box2 = QtWidgets.QGroupBox("2 驱动与分析")
        l2 = QtWidgets.QVBoxLayout(box2)
        self.drives = QtWidgets.QTableWidget(0, 3)
        self.drives.setHorizontalHeaderLabels(["运动副", "驱动", "值"])
        self.drives.verticalHeader().setVisible(False)
        l2.addWidget(self.drives)
        form = QtWidgets.QFormLayout()
        self.kind = QtWidgets.QComboBox()
        for k, label in ST.ANALYSES:
            self.kind.addItem(label, k)
        self.end = QtWidgets.QLineEdit("1")
        self.steps = QtWidgets.QLineEdit("100")
        self.integ = QtWidgets.QComboBox()
        for k, label in (("auto", "自动（按模型建议）"), ("DOP853", "DOP853 显式"), ("HHT", "HHT 隐式（硬系统）")):
            self.integ.addItem(label, k)
        self.integ.setToolTip("有柔性零件、梁元件的硬系统用 HHT；一般机构、冲击接触用 DOP853。自动时按模型建议（ADR-0098）")
        form.addRow("分析", self.kind)
        form.addRow("积分器", self.integ)
        form.addRow("时长 s", self.end)
        form.addRow("输出点数", self.steps)
        l2.addLayout(form)
        self.flexparts = QtWidgets.QTableWidget(0, 2)
        self.flexparts.setHorizontalHeaderLabels(["零件", "按柔性体算（选材料）"])
        self.flexparts.verticalHeader().setVisible(False)
        self.flexparts.setToolTip("选材料：零件用 gmsh + CalculiX 缩减成实体柔性体（小变形，要几十秒），能看应力云图；"
                                  "选“大变形梁：材料”：细长等截面直杆按大变形梁算（大挠度、屈曲、旋转刚化，ADR-0101）")
        l2.addWidget(self.flexparts)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("变形放大倍数"))
        self.flex_scale = QtWidgets.QLineEdit("1")
        row.addWidget(self.flex_scale)
        l2.addLayout(row)
        self.run_btn = QtWidgets.QPushButton("计算")
        self.run_btn.setEnabled(False)
        l2.addWidget(self.run_btn)
        lay.addWidget(box2)

        # 3 结果
        box3 = QtWidgets.QGroupBox("3 结果")
        l3 = QtWidgets.QVBoxLayout(box3)
        self.verdict = _TrLabel("")
        self.verdict.setWordWrap(True)
        l3.addWidget(self.verdict)
        self.curve = QtWidgets.QComboBox()
        l3.addWidget(self.curve)
        self.plot = self._make_plot()
        if self.plot is not None:
            l3.addWidget(self.plot, 1)
        self.modes = QtWidgets.QTableWidget(0, 3)
        self.modes.setHorizontalHeaderLabels(["阶", "固有频率 Hz", "阻尼比"])
        self.modes.verticalHeader().setVisible(False)
        self.modes.setVisible(False)
        l3.addWidget(self.modes)
        row = QtWidgets.QHBoxLayout()
        self.play = QtWidgets.QPushButton("播放")
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.time = QtWidgets.QLabel("t = —")
        self.reset = QtWidgets.QPushButton("复位")
        for x in (self.play, self.slider, self.time, self.reset):
            row.addWidget(x, 1 if x is self.slider else 0)
        l3.addLayout(row)
        self.report_btn = QtWidgets.QPushButton("写计算报告…")
        self.report_btn.setEnabled(False)
        l3.addWidget(self.report_btn)
        lay.addWidget(box3)
        self.status = _TrLabel("先选装配体：用当前文档的，或导入 STEP。")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.setWidget(w)
        self._set_anim(False)
        _localize(self)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        self.use_doc.clicked.connect(lambda *_: self.load_document())
        self.import_step.clicked.connect(lambda *_: self._pick_step())
        self.open_model.clicked.connect(lambda *_: self._pick_model())
        self.build_btn.clicked.connect(lambda *_: self.confirm())
        self.run_btn.clicked.connect(lambda *_: self.compute())
        self.curve.currentIndexChanged.connect(lambda *_: self._draw())
        self.slider.valueChanged.connect(lambda v: self.show_frame(v))
        self.play.clicked.connect(lambda *_: self.toggle_play())
        self.reset.clicked.connect(lambda *_: self.restore())
        self.report_btn.clicked.connect(lambda *_: self._pick_report_dir())
        self.done.connect(self._done, QtCore.Qt.QueuedConnection)

    def _make_plot(self):
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure
        except Exception:  # noqa: BLE001 — 没有 matplotlib 时不画图
            return None
        self.figure = Figure(figsize=(4, 2.4), tight_layout=True)
        return FigureCanvasQTAgg(self.figure)

    def _set_anim(self, on):
        for x in (self.play, self.slider, self.reset):
            x.setEnabled(on)

    # ------------------------------------------------------------ 1 装配体

    def load_document(self, doc=None) -> bool:
        from freecad_addon.fc import mbd_assembly as MA

        doc = doc or App.ActiveDocument
        asm = MA.find_assembly(doc) if doc else None
        if asm is None:
            self.status.setText("当前文档里没有 Assembly 工作台的装配体；可以导入 STEP 让程序起草运动副。")
            return False
        self.doc, self.assembly, self.model_file = doc, asm, None
        self.cands.setRowCount(0)                         # 上一次导入 STEP 的候选表、机架不再适用
        self.ground.clear()
        self.build_btn.setEnabled(False)
        return self.refresh_model()

    def _pick_model(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, T("打开模型文件"), "", T("模型文件 (*.json)"))
        if path:
            self.load_model_file(path)

    def load_model_file(self, path) -> bool:
        """打开 mbd-model/1 模型文件（ADR-0102 第 5 步）：模型里的构件、运动副、力、控制器原样用；窗口里的分析类型、时长、输出点数、
        积分器照模型文件填好，可以改。模型文件里相对路径（FMU 等）按文件所在目录找。没有 FreeCAD 零件，所以没有动画"""
        import json
        from pathlib import Path

        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.status.setText(f"打不开模型文件：{exc}")
            return False
        model = doc.get("instance", doc) if isinstance(doc, dict) else None
        if not isinstance(model, dict) or model.get("format") != "mbd-model/1":
            self.status.setText("这不是多体动力学模型文件（format 要是 mbd-model/1）")
            return False
        self.restore()
        self.doc, self.assembly, self.animator, self.data = None, None, None, None
        self.model_file, self.model_dir = model, Path(path).parent
        self.model = model
        an = model.get("analysis") or {}
        self.kind.setCurrentIndex(max(self.kind.findData(an.get("type", "dynamic")), 0))
        self.end.setText(f"{an.get('end_time_s', 1.0):g}")
        self.steps.setText(str(an.get("output_steps", 100)))
        self.integ.setCurrentIndex(max(self.integ.findData(an.get("integrator", "auto")), 0))
        self.cands.setRowCount(0)
        self.drives.setRowCount(0)
        self.flexparts.setRowCount(0)
        self.build_btn.setEnabled(False)
        self.run_btn.setEnabled(True)
        self.report_btn.setEnabled(False)
        self._set_anim(False)
        self.status.setText(f"已打开模型文件 {model.get('name', '')}：{len(model.get('bodies', []))} 个构件、"
                            f"{len(model.get('joints', []))} 个运动副。分析设置可以改，点“计算”。")
        return True

    def _pick_step(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, T("导入 STEP 装配"), "", "STEP (*.step *.stp)")
        if path:
            self.load_step(path)

    def load_step(self, path, doc=None) -> bool:
        from assist import mbd_edition

        self.model_file = None

        if self.use_ai.isChecked() and self.client_factory:
            try:                                          # 免费版：先说明，不导入（ADR-0102 第 4 步）
                mbd_edition.gate(feature="AI 帮着挑运动副")
            except mbd_edition.NeedsPro as exc:
                self.status.setText(str(exc))
                return False
        self.doc = doc or App.newDocument("MbdAssembly")
        client = self.client_factory() if (self.use_ai.isChecked() and self.client_factory) else None
        try:
            self.objs, _parts, self.found, self.draft = ST.draft_from_step(path, self.doc, client)
        except Exception as exc:  # noqa: BLE001 — AI 或导入出错都显示给人
            self.status.setText(f"导入或起草失败：{exc}")
            return False
        labels = {o.Name: o.Label for o in self.objs}
        accepted = {a["id"]: a for a in self.draft["accept"]}
        self.cands.setRowCount(len(self.found["candidates"]))
        for i, c in enumerate(self.found["candidates"]):
            chk = QtWidgets.QTableWidgetItem()
            chk.setFlags(chk.flags() | QtCore.Qt.ItemIsUserCheckable)
            chk.setCheckState(QtCore.Qt.Checked if c["id"] in accepted else QtCore.Qt.Unchecked)
            chk.setData(QtCore.Qt.UserRole, c["id"])
            self.cands.setItem(i, 0, chk)
            self.cands.setItem(i, 1, QtWidgets.QTableWidgetItem(accepted.get(c["id"], {}).get("name", c["id"])))
            typ = QtWidgets.QComboBox()
            for t in [c["type"], *c["alternatives"]]:
                typ.addItem(t)
            typ.setCurrentText(accepted.get(c["id"], {}).get("type", c["type"]))
            self.cands.setCellWidget(i, 2, typ)
            self.cands.setItem(i, 3, QtWidgets.QTableWidgetItem(f"{labels[c['part1']]} – {labels[c['part2']]}"))
            self.cands.setItem(i, 4, QtWidgets.QTableWidgetItem(c["evidence"]))
        self.cands.resizeColumnsToContents()
        self.ground.clear()
        for o in self.objs:
            self.ground.addItem(o.Label, o.Name)
        if self.draft["ground"]:
            self.ground.setCurrentIndex(self.ground.findData(self.draft["ground"]))
        self.build_btn.setEnabled(True)
        extra = "；".join(self.draft["notes"])
        miss = "、".join(labels[p] for p in self.found["unconnected"])
        self.status.setText(f"{self.draft['by']}起草了 {len(self.draft['accept'])} 个运动副，请逐条核对后点“确认”。"
                            + (f"没连上的零件：{miss}。" if miss else "") + (f"注意：{extra}" if extra else ""))
        return True

    def accepted(self) -> list[dict]:
        out = []
        for i in range(self.cands.rowCount()):
            it = self.cands.item(i, 0)
            if it.checkState() == QtCore.Qt.Checked:
                out.append({"id": it.data(QtCore.Qt.UserRole), "name": self.cands.item(i, 1).text(),
                            "type": self.cands.cellWidget(i, 2).currentText()})
        return out

    def confirm(self) -> bool:
        try:
            self.assembly = ST.build(self.doc, self.objs, self.found, self.accepted(), self.ground.currentData())
        except ValueError as exc:
            self.status.setText(str(exc))
            return False
        self.build_btn.setEnabled(False)
        return self.refresh_model()

    def refresh_model(self) -> bool:
        """装配体 → 模型（检查材料、运动副），列出可加驱动的运动副"""
        from analysis.mbd.assembly import AssemblyError

        try:
            self.model, msgs = ST.make_model(self.assembly, [], {"type": "dynamic", "end_time_s": 1.0})
        except AssemblyError as exc:
            self.model = None
            self.run_btn.setEnabled(False)
            self.status.setText("还不能计算：\n" + "\n".join(f"· {p}" for p in exc.problems))
            return False
        joints = [j for j in self.model["joints"] if j["type"] in ("revolute", "translational", "cylindrical")]
        self.drives.setRowCount(len(joints))
        for i, j in enumerate(joints):
            self.drives.setItem(i, 0, QtWidgets.QTableWidgetItem(j["id"]))
            kind = QtWidgets.QComboBox()
            for k, label in ST.DRIVE_KINDS:
                kind.addItem(T(label), k)
            self.drives.setCellWidget(i, 1, kind)
            self.drives.setItem(i, 2, QtWidgets.QTableWidgetItem(""))
        self.drives.resizeColumnsToContents()
        self._fill_flexparts()
        self.run_btn.setEnabled(True)
        self.status.setText(f"装配体有 {len(self.model['bodies'])} 个运动零件、{len(self.model['joints'])} 个运动副。"
                            + " ".join(msgs) + " 设好驱动和分析后点“计算”。")
        return True

    # ------------------------------------------------------------ 2 计算

    def set_drive(self, joint_id, kind, value):
        for i in range(self.drives.rowCount()):
            if self.drives.item(i, 0).text() == joint_id:
                w = self.drives.cellWidget(i, 1)
                w.setCurrentIndex(w.findData(kind))
                self.drives.item(i, 2).setText(str(value))
                return True
        return False

    def settings(self):
        drives = []
        for i in range(self.drives.rowCount()):
            kind = self.drives.cellWidget(i, 1).currentData()
            if kind == "none":
                continue
            val = self.drives.item(i, 2).text().strip()
            if not val:
                raise ValueError(f"运动副 {self.drives.item(i, 0).text()} 的驱动没填值")
            drives.append({"joint": self.drives.item(i, 0).text(), "kind": kind,
                           "value": float(val) if kind == "speed" else val})
        try:
            end, steps = float(self.end.text()), int(self.steps.text())
        except ValueError as exc:
            raise ValueError("时长、输出点数要是数字") from exc
        an = {"type": self.kind.currentData(), "end_time_s": end, "output_steps": steps}
        if self.integ.currentData() != "auto":
            an["integrator"] = self.integ.currentData()
        return drives, an

    def _fill_flexparts(self):
        from analysis.common import materials

        need = ("elastic_modulus_mpa", "poisson_ratio", "density_kg_m3")
        mats = [m for m in materials.all_materials() if all(k in m for k in need)]
        self.flexparts.setRowCount(len(self.model["bodies"]))
        for i, b in enumerate(self.model["bodies"]):
            self.flexparts.setItem(i, 0, QtWidgets.QTableWidgetItem(b["id"]))
            box = QtWidgets.QComboBox()
            box.addItem(T("刚性"), None)
            for m in mats:
                box.addItem(T(m["name"]), m["id"])
            for m in mats:                                    # ADR-0101 F3：细长等截面直杆可按大变形梁
                box.addItem(T(f"大变形梁：{m['name']}"), "beam:" + m["id"])
            self.flexparts.setCellWidget(i, 1, box)
        self.flexparts.resizeColumnsToContents()

    def set_flex(self, body_id, material_id, kind="modal") -> bool:
        key = ("beam:" + material_id) if kind == "nonlinear_beam" and material_id else material_id
        for i in range(self.flexparts.rowCount()):
            if self.flexparts.item(i, 0).text() == body_id:
                w = self.flexparts.cellWidget(i, 1)
                k = w.findData(key)
                if k < 0:
                    return False
                w.setCurrentIndex(k)
                return True
        return False

    def flex_settings(self) -> dict:
        out = {}
        for i in range(self.flexparts.rowCount()):
            mid = self.flexparts.cellWidget(i, 1).currentData()
            if mid and mid.startswith("beam:"):
                out[self.flexparts.item(i, 0).text()] = {"material": mid[5:], "kind": "nonlinear_beam"}
            elif mid:
                out[self.flexparts.item(i, 0).text()] = {"material": mid}
        return out

    def compute(self) -> bool:
        if self.busy or (self.assembly is None and self.model_file is None):
            return False
        if self.model_file is not None:
            return self._compute_file()
        from analysis.mbd.assembly import AssemblyError
        from assist import mbd_edition

        try:
            drives, an = self.settings()
            flex = self.flex_settings()
            scale = float(self.flex_scale.text())
            model, _ = ST.make_model(self.assembly, drives, an)
            mbd_edition.gate(model, flex_parts=flex)      # 免费版用了专业版功能：先说明，不算（ADR-0102 第 4 步）
        except (ValueError, AssemblyError, mbd_edition.NeedsPro) as exc:
            self.status.setText(str(exc))
            return False
        self.restore()
        self.busy = True
        self.run_btn.setEnabled(False)
        self.status.setText("正在缩减柔性零件、计算 …" if flex else "正在计算 …")
        self.scale = scale
        objs = ST.body_objects(model, self.doc)

        def work():
            try:
                if flex:
                    from freecad_addon.fc import mbd_flex as MF

                    MF.make_flexible(model, objs, flex)
                from analysis.mbd.dae import advise

                why = advise.apply(model)                  # 柔性零件定下来以后再建议积分器
                data, msgs = ST.run(model)
                integ = model["analysis"].get("integrator")
                note = [f"积分器 {integ}：{why}。"] if why else ([f"积分器 {integ}。"] if integ else [])
                out = {"ok": True, "model": model, "data": data, "messages": note + list(msgs)}
            except Exception as exc:  # noqa: BLE001 — 交给界面显示
                out = {"ok": False, "messages": [str(exc)]}
            self.done.emit(out)

        threading.Thread(target=work, name="fap-mbd-asm", daemon=True).start()
        return True

    def _compute_file(self) -> bool:
        """模型文件：窗口里的分析设置盖到模型的 analysis 上（其他键如 load_steps、modes 保留），后台计算"""
        import copy

        from assist import mbd_edition

        try:
            _drives, an = self.settings()
            model = copy.deepcopy(self.model_file)
            model["analysis"] = {**(model.get("analysis") or {}), **an}
            if "integrator" not in an:
                model["analysis"].pop("integrator", None)
            mbd_edition.gate(model)
        except (ValueError, mbd_edition.NeedsPro) as exc:
            self.status.setText(str(exc))
            return False
        self.busy = True
        self.run_btn.setEnabled(False)
        self.status.setText("正在计算 …")
        base = self.model_dir

        def work():
            try:
                from analysis.mbd.dae import advise

                why = advise.apply(model)
                data, msgs = ST.run(model, base)
                integ = model["analysis"].get("integrator")
                note = [f"积分器 {integ}：{why}。"] if why else ([f"积分器 {integ}。"] if integ else [])
                out = {"ok": True, "model": model, "data": data, "messages": note + list(msgs)}
            except Exception as exc:  # noqa: BLE001 — 交给界面显示
                out = {"ok": False, "messages": [str(exc)]}
            self.done.emit(out)

        threading.Thread(target=work, name="fap-mbd-file", daemon=True).start()
        return True

    def _done(self, out):
        self.busy = False
        self.run_btn.setEnabled(True)
        if not out["ok"]:
            self.status.setText("没有算出：" + "；".join(out["messages"]))
            return
        self.model, self.data = out["model"], out["data"]
        self.verdict.setText("\n".join(ST.verdict(self.data)))
        self.curve.blockSignals(True)
        self.curve.clear()
        for name in ST.curves(self.data):
            self.curve.addItem(T(name), name)
        self.curve.blockSignals(False)
        lin = self.data.get("linear")
        self.modes.setVisible(bool(lin))
        if lin:
            self.modes.setRowCount(len(lin["modes"]))
            for i, m in enumerate(lin["modes"]):
                for j, text in enumerate([str(i + 1), f"{m['frequency_hz']:.4g}",
                                          "—" if m["damping_ratio"] is None else f"{m['damping_ratio']:.3g}"]):
                    self.modes.setItem(i, j, QtWidgets.QTableWidgetItem(text))
        self.report_btn.setEnabled(True)
        if self.doc is None:                               # 模型文件：没有 FreeCAD 零件，不放动画
            self.animator = None
            self._set_anim(False)
        else:
            self.animator = ST.Animator(self.model, self.data, self.doc, flex_scale=getattr(self, "scale", 1.0))
            self.slider.setRange(0, self.animator.frames - 1)
            self._set_anim(self.animator.frames > 1)
        self._draw()
        anim = self.animator is not None and self.animator.frames > 1
        self.status.setText("\n".join(["算完。", *out["messages"], *(["可以播放动画、换曲线看。"] if anim else [])]))

    # ------------------------------------------------------------ 3 结果

    def _draw(self):
        if self.plot is None or self.data is None or not self.curve.currentData():
            return
        unit, ys = ST.curves(self.data)[self.curve.currentData()]
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.plot(self.data["times_s"], ys)
        ax.set_xlabel("t / s")
        ax.set_ylabel(unit)
        ax.grid(True, alpha=0.3)
        self.plot.draw_idle()

    def show_frame(self, k):
        if self.animator is None:
            return None
        t = self.animator.apply(k)
        self.time.setText(f"t = {t:.3f} s")
        return t

    def toggle_play(self):
        if self.timer.isActive():
            self.timer.stop()
            self.play.setText(T("播放"))
        else:
            self.timer.start()
            self.play.setText(T("暂停"))

    def _tick(self):
        k = self.slider.value() + 1
        self.slider.setValue(0 if k >= self.animator.frames else k)

    def restore(self):
        if self.timer.isActive():
            self.toggle_play()
        if self.animator is not None:
            try:
                self.animator.restore()
            except ReferenceError:                        # 文档已经关了：零件不在了，不用复位
                self.animator = None
            self.time.setText("t = —")

    def _pick_report_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, T("报告存到哪个文件夹"))
        if d:
            self.write_report(d)

    def write_report(self, out_dir, use_ai=None, lang=None):
        """结果 → 正式报告（Word，有 LibreOffice 时另出 PDF）与出处账、改版记录（ADR-0102 第 1 步）；
        勾了“用 AI 起草”就让 AI 写解释段落（数字仍由程序填，不合规的段落退回）"""
        if self.data is None:
            return None
        from assist import mbd_edition

        try:
            mbd_edition.gate(feature="正式报告")
        except mbd_edition.NeedsPro as exc:
            self.status.setText(str(exc))
            return None
        ai = self.use_ai.isChecked() if use_ai is None else use_ai
        client = self.client_factory() if ai and self.client_factory else None
        try:
            got = ST.write_report(self.model, self.data, out_dir, client=client, lang=lang)
        except Exception as exc:  # noqa: BLE001 — 交给界面显示
            self.status.setText(f"报告没写成：{exc}")
            return None
        rej = got["explanation"]["rejected"]
        self.status.setText(f"报告写到 {got['pdf'] or got['docx']}（草稿，须工程师审核）"
                            + (f"；AI 有 {len(rej)} 段不合规，已退回" if rej else ""))
        return got

    def closeEvent(self, ev):
        self.restore()
        super().closeEvent(ev)
