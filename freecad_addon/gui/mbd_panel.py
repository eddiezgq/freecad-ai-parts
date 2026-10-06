"""多体动力学窗口（ADR-0056，M10 第二步）：机械臂或常用机构 → 设置运动 → 本机计算 → 关节力矩表与曲线 → 送去选型。

计算在 analysis/mbd（MuJoCo），后台线程中进行，不卡界面。质量全由使用者填（可取所选零件的样本质量），不估。
"""

from __future__ import annotations

import threading

from PySide import QtCore, QtWidgets

ARM_FIELDS = (("base_height_mm", "底座高度 mm"), ("l1_mm", "大臂长 mm"), ("m1_kg", "大臂质量 kg"),
              ("l2_mm", "小臂长 mm"), ("m2_kg", "小臂质量 kg"), ("elbow_kg", "肘关节模组质量 kg"),
              ("payload_kg", "末端负载 kg"))
MOVE_FIELDS = (("j1_deg", "底座转 °"), ("j2_deg", "大臂抬 °"), ("j3_deg", "小臂转 °"), ("move_s", "运动时间 s"),
               ("duration_s", "计算时长 s"))
HEADERS = ["关节", "峰值", "均方根", "最高转速", "峰值功率 W"]


def _num(text: str, name: str, *, required: bool = True, positive: bool = False) -> float | None:
    t = text.strip()
    if not t:
        if required:
            raise ValueError(f"请填写{name}")
        return None
    try:
        v = float(t)
    except ValueError as exc:
        raise ValueError(f"{name}须为数字") from exc
    if positive and v <= 0:
        raise ValueError(f"{name}须大于 0")
    return v


class MbdPanel(QtWidgets.QDockWidget):
    done = QtCore.Signal(object)  # 后台计算完成：结果

    def __init__(self, parent=None, selection=None, host=None):
        super().__init__("多体动力学", parent)
        self.setObjectName("FapMbdPanel")
        self.selection = selection  # 可调用：返回选型面板（送去选型用）
        self._host = host
        self.result: dict | None = None
        self.busy = False
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        self.model = QtWidgets.QComboBox()
        self.model.addItem("机械臂（参数化，三关节）", "arm")
        from analysis.mbd import mechanisms

        for mid, name in mechanisms.NAMES.items():
            self.model.addItem(f"机构：{name}", mid)
        lay.addWidget(self.model)
        self.arm_box = QtWidgets.QGroupBox("机械臂（质量请按实物填写）")
        form = QtWidgets.QFormLayout(self.arm_box)
        self.inputs: dict[str, QtWidgets.QLineEdit] = {}
        for key, label in ARM_FIELDS + MOVE_FIELDS:
            e = QtWidgets.QLineEdit()
            self.inputs[key] = e
            form.addRow(label, e)
        self.use_parts = QtWidgets.QPushButton("肘关节模组质量取布局中的电机 + 减速器")
        form.addRow("", self.use_parts)
        lay.addWidget(self.arm_box)
        self.mech_box = QtWidgets.QGroupBox("机构（示例几何，主动件匀速）")
        mform = QtWidgets.QFormLayout(self.mech_box)
        self.speed = QtWidgets.QLineEdit("60")
        self.mech_duration = QtWidgets.QLineEdit("1")
        mform.addRow("主动件转速 rpm", self.speed)
        mform.addRow("计算时长 s", self.mech_duration)
        lay.addWidget(self.mech_box)
        self.run_button = QtWidgets.QPushButton("计算")
        lay.addWidget(self.run_button)
        self.table = QtWidgets.QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setMaximumHeight(150)
        lay.addWidget(self.table)
        self.plot = self._make_plot()
        if self.plot is not None:
            lay.addWidget(self.plot, 1)
        row = QtWidgets.QHBoxLayout()
        self.joint = QtWidgets.QComboBox()
        self.send_button = QtWidgets.QPushButton("送去选型")
        self.send_button.setToolTip("按这个关节的峰值、均方根力矩、最高转速和等效惯量填选型需求")
        self.send_button.setEnabled(False)
        row.addWidget(QtWidgets.QLabel("关节"))
        row.addWidget(self.joint, 1)
        row.addWidget(self.send_button)
        lay.addLayout(row)
        self.status = QtWidgets.QLabel("选模型、填参数后点“计算”。")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.setWidget(w)
        self.model.currentIndexChanged.connect(lambda *_: self._model_changed())
        self.run_button.clicked.connect(lambda *_: self.compute())
        self.send_button.clicked.connect(lambda *_: self.send_to_selection())
        self.use_parts.clicked.connect(lambda *_: self.fill_part_masses())
        self.done.connect(self._done, QtCore.Qt.QueuedConnection)
        self._model_changed()

    def _make_plot(self):
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure
        except Exception:  # noqa: BLE001 — 没有 matplotlib 时只显示表格
            return None
        self.figure = Figure(figsize=(4, 2.4), tight_layout=True)
        return FigureCanvasQTAgg(self.figure)

    def _model_changed(self) -> None:
        arm = self.model.currentData() == "arm"
        self.arm_box.setVisible(arm)
        self.mech_box.setVisible(not arm)

    # ------------------------------------------------------------ 设置

    def setup(self) -> dict:
        """界面 → 模块设置；填写有误时抛 ValueError。"""
        if self.model.currentData() != "arm":
            rpm = _num(self.speed.text(), "主动件转速", positive=True)
            from analysis.mbd import mechanisms

            mid = self.model.currentData()
            return {"model": {"kind": "mechanism", "id": mid}, "duration_s": _num(self.mech_duration.text(), "计算时长",
                                                                                   positive=True),
                    "drives": [{"joint": mechanisms.DRIVER[mid], "kind": "speed", "value": rpm}]}
        v = {k: e.text() for k, e in self.inputs.items()}
        names = dict(ARM_FIELDS + MOVE_FIELDS)
        arm = {"kind": "arm", "base_height_mm": _num(v["base_height_mm"], names["base_height_mm"], required=False) or 0,
               "links": [{"length_mm": _num(v["l1_mm"], names["l1_mm"], positive=True),
                          "mass_kg": _num(v["m1_kg"], names["m1_kg"], positive=True)},
                         {"length_mm": _num(v["l2_mm"], names["l2_mm"], positive=True),
                          "mass_kg": _num(v["m2_kg"], names["m2_kg"], positive=True)}],
               "joint_masses_kg": [0, _num(v["elbow_kg"], names["elbow_kg"], required=False) or 0],
               "payload_kg": _num(v["payload_kg"], names["payload_kg"], required=False) or 0}
        move = _num(v["move_s"], names["move_s"], positive=True)
        duration = _num(v["duration_s"], names["duration_s"], required=False) or move + 0.3
        drives = []
        for j in ("j1", "j2", "j3"):
            to = _num(v[f"{j}_deg"], names[f"{j}_deg"], required=False)
            drives.append({"joint": j, "kind": "move", "to": to, "t1_s": move} if to else {"joint": j, "kind": "hold"})
        return {"model": arm, "duration_s": duration, "drives": drives}

    def fill_part_masses(self) -> bool:
        """肘关节模组质量 = 布局中电机与减速器的样本质量之和（缺质量时不填，说明缺哪个）。"""
        from freecad_addon.gui.host import get_host

        host = self._host or get_host()
        lib = host.library()
        insts = host.layout.get("instances", [])
        total, missing = 0.0, []
        for inst in insts:
            comp = lib.get(inst["component"])
            if comp and comp["category"] in ("servo_motor", "reducer"):
                mass = (comp.get("params", {}).get("mass_kg") or {}).get("value")
                if mass is None:
                    missing.append(comp["model"])
                else:
                    total += mass
        if missing or not total:
            self.status.setText("缺样本质量：" + "、".join(missing) if missing else "布局中没有电机与减速器")
            return False
        self.inputs["elbow_kg"].setText(f"{total:g}")
        self.status.setText(f"肘关节模组质量取布局中电机 + 减速器的样本质量：{total:g} kg")
        return True

    # ------------------------------------------------------------ 计算

    def compute(self) -> bool:
        if self.busy:
            return False
        try:
            setup = self.setup()
        except ValueError as exc:
            self.status.setText(str(exc))
            return False
        import analysis

        st = next((m for m in analysis.modules() if m["id"] == "mbd"), None)
        if st is None or not st["available"]:
            self.status.setText("多体动力学模块不可用：" + "、".join((st or {}).get("missing", [])) + "。" +
                                (st or {}).get("install", ""))
            return False
        self.busy = True
        self.run_button.setEnabled(False)
        self.status.setText("正在计算 …")

        def work() -> None:
            try:
                out = analysis.run("mbd", setup)
            except Exception as exc:  # noqa: BLE001 — 交给界面显示
                out = {"status": "failed", "messages": [str(exc)]}
            self.done.emit(out)

        threading.Thread(target=work, name="fap-mbd", daemon=True).start()
        return True

    def _done(self, out: dict) -> None:
        self.busy = False
        self.run_button.setEnabled(True)
        if out.get("status") != "ok":
            self.status.setText("没有算出：" + "；".join(out.get("messages", [])))
            return
        self.result = out
        drives = out["data"]["drives"]
        self.table.setRowCount(len(drives))
        for i, d in enumerate(drives):
            cells = [d["joint"], f"{d['peak']:.2f} {d['unit_force']}", f"{d['rms']:.2f} {d['unit_force']}",
                     f"{d['speed_max']:.2f} {d['unit_speed']}", f"{d['power_peak_w']:.1f}"]
            for j, text in enumerate(cells):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.joint.clear()
        for d in drives:
            if d["unit_force"] == "N·m":
                self.joint.addItem(d["joint"])
        worst = max(drives, key=lambda d: d["peak"]) if drives else None
        if worst is not None:
            self.joint.setCurrentText(worst["joint"])
        self.send_button.setEnabled(self.joint.count() > 0)
        self._draw(out)
        self.status.setText(f"算完（{out.get('elapsed_s', 0):.1f} s，MuJoCo {out['solver']['version']}）。"
                            + (f"最吃力的是 {worst['joint']}。" if worst else "") + "可选一个关节“送去选型”。")

    def _draw(self, out: dict) -> None:
        if self.plot is None:
            return
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        s = out["data"]["series"]
        for d in out["data"]["drives"]:
            ax.plot(s["t_s"], s[d["joint"]]["drive"], label=f"{d['joint']} ({d['unit_force']})")
        ax.set_xlabel("t / s")
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)
        self.plot.draw_idle()

    # ------------------------------------------------------------ 送去选型

    def requirement(self) -> dict | None:
        if self.result is None or not self.joint.currentText():
            return None
        from analysis import mbd

        return mbd.requirement(self.result, self.joint.currentText())

    def send_to_selection(self) -> bool:
        req = self.requirement()
        panel = self.selection() if self.selection else None
        if req is None or panel is None:
            return False
        panel.load_requirement(req, f"来自多体动力学：关节 {self.joint.currentText()}")
        panel.show()
        panel.raise_()
        self.status.setText(f"已把关节 {self.joint.currentText()} 的需求填进选型窗口；补上供电等后点“查找方案”。")
        return True
