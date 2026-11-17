"""装配体多体动力学窗口（ADR-0097 D5c，补充十二）：STEP 导入与运动副草稿确认、驱动与分析设置、计算、核查结论、曲线、动画。

流程逻辑在 freecad_addon/core/mbd_study.py；这里只管界面。计算在后台线程，不卡界面。
"""

from __future__ import annotations

import threading

import FreeCAD as App
from PySide import QtCore, QtWidgets

from freecad_addon.core import mbd_study as ST


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
        self.busy = False
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)

        # 1 装配体
        box1 = QtWidgets.QGroupBox("1 装配体")
        l1 = QtWidgets.QVBoxLayout(box1)
        row = QtWidgets.QHBoxLayout()
        self.use_doc = QtWidgets.QPushButton("用当前文档的装配体")
        self.import_step = QtWidgets.QPushButton("导入 STEP 并起草运动副…")
        self.use_ai = QtWidgets.QCheckBox("用 AI 起草")
        row.addWidget(self.use_doc)
        row.addWidget(self.import_step)
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
        form.addRow("分析", self.kind)
        form.addRow("时长 s", self.end)
        form.addRow("输出点数", self.steps)
        l2.addLayout(form)
        self.run_btn = QtWidgets.QPushButton("计算")
        self.run_btn.setEnabled(False)
        l2.addWidget(self.run_btn)
        lay.addWidget(box2)

        # 3 结果
        box3 = QtWidgets.QGroupBox("3 结果")
        l3 = QtWidgets.QVBoxLayout(box3)
        self.verdict = QtWidgets.QLabel("")
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
        lay.addWidget(box3)
        self.status = QtWidgets.QLabel("先选装配体：用当前文档的，或导入 STEP。")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.setWidget(w)
        self._set_anim(False)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        self.use_doc.clicked.connect(lambda *_: self.load_document())
        self.import_step.clicked.connect(lambda *_: self._pick_step())
        self.build_btn.clicked.connect(lambda *_: self.confirm())
        self.run_btn.clicked.connect(lambda *_: self.compute())
        self.curve.currentIndexChanged.connect(lambda *_: self._draw())
        self.slider.valueChanged.connect(lambda v: self.show_frame(v))
        self.play.clicked.connect(lambda *_: self.toggle_play())
        self.reset.clicked.connect(lambda *_: self.restore())
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
        self.doc, self.assembly = doc, asm
        return self.refresh_model()

    def _pick_step(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "导入 STEP 装配", "", "STEP (*.step *.stp)")
        if path:
            self.load_step(path)

    def load_step(self, path, doc=None) -> bool:
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
                kind.addItem(label, k)
            self.drives.setCellWidget(i, 1, kind)
            self.drives.setItem(i, 2, QtWidgets.QTableWidgetItem(""))
        self.drives.resizeColumnsToContents()
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
        return drives, an

    def compute(self) -> bool:
        if self.busy or self.assembly is None:
            return False
        from analysis.mbd.assembly import AssemblyError

        try:
            drives, an = self.settings()
            model, _ = ST.make_model(self.assembly, drives, an)
        except (ValueError, AssemblyError) as exc:
            self.status.setText(str(exc))
            return False
        self.restore()
        self.busy = True
        self.run_btn.setEnabled(False)
        self.status.setText("正在计算 …")

        def work():
            try:
                data, msgs = ST.run(model)
                out = {"ok": True, "model": model, "data": data, "messages": msgs}
            except Exception as exc:  # noqa: BLE001 — 交给界面显示
                out = {"ok": False, "messages": [str(exc)]}
            self.done.emit(out)

        threading.Thread(target=work, name="fap-mbd-asm", daemon=True).start()
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
            self.curve.addItem(name)
        self.curve.blockSignals(False)
        lin = self.data.get("linear")
        self.modes.setVisible(bool(lin))
        if lin:
            self.modes.setRowCount(len(lin["modes"]))
            for i, m in enumerate(lin["modes"]):
                for j, text in enumerate([str(i + 1), f"{m['frequency_hz']:.4g}",
                                          "—" if m["damping_ratio"] is None else f"{m['damping_ratio']:.3g}"]):
                    self.modes.setItem(i, j, QtWidgets.QTableWidgetItem(text))
        self.animator = ST.Animator(self.model, self.data, self.doc)
        self.slider.setRange(0, self.animator.frames - 1)
        self._set_anim(self.animator.frames > 1)
        self._draw()
        self.status.setText("算完。" + " ".join(out["messages"]) + (" 可以播放动画、换曲线看。" if self.animator.frames > 1 else ""))

    # ------------------------------------------------------------ 3 结果

    def _draw(self):
        if self.plot is None or self.data is None or not self.curve.currentText():
            return
        unit, ys = ST.curves(self.data)[self.curve.currentText()]
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
            self.play.setText("播放")
        else:
            self.timer.start()
            self.play.setText("暂停")

    def _tick(self):
        k = self.slider.value() + 1
        self.slider.setValue(0 if k >= self.animator.frames else k)

    def restore(self):
        if self.timer.isActive():
            self.toggle_play()
        if self.animator is not None:
            self.animator.restore()
            self.time.setText("t = —")

    def closeEvent(self, ev):
        self.restore()
        super().closeEvent(ev)
