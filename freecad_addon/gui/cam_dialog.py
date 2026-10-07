"""数控编程对话框（ADR-0059，M11 第二步）：车削（阶梯轴）、铣削（矩形毛坯上的外轮廓、型腔、槽、孔）生成 G 代码；或打开任意
FANUC 风格程序（包括 FreeCAD CAM 工作台输出的）检查：时间、撞料、过切 / 残留、超程、转速、切削功率。

计算在 analysis/cam，后台线程中进行。机床在 ~/.freecad-ai-parts/machines.yaml 填；示例机床是虚构的。
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide import QtCore, QtWidgets

from freecad_addon.core import cam_input


class CamDialog(QtWidgets.QDialog):
    done = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数控编程（本机计算）")
        self.resize(820, 680)
        self.result: dict | None = None
        self.busy = False
        from analysis.cam import machines, power

        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QFormLayout()
        self.kienzle = QtWidgets.QComboBox()
        self.kienzle.addItem("（不选：切削功率待确认）", None)
        for r in power.rows():
            self.kienzle.addItem(f"{r['key']} · {r['material_cn'] or r['material']}（kc1.1 {r['kc11_mpa']:g}）", r["key"])
        top.addRow("工件材料（Kienzle 表）", self.kienzle)
        lay.addLayout(top)
        self.tabs = QtWidgets.QTabWidget()
        lay.addWidget(self.tabs)
        try:
            ms = machines.all_machines()
            self.machine_note = ""
        except machines.MachineError as exc:
            ms = [m for m in machines._read(machines.EXAMPLE)]
            self.machine_note = f"机床文件有误，只列示例机床：{exc}"

        def combo(kinds):
            c = QtWidgets.QComboBox()
            for m in ms:
                if m["kind"] in kinds:
                    c.addItem(m["name"] + ("（示例）" if m.get("example") else ""), m["id"])
            return c

        # 车削
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.turn_machine = combo(("lathe",))
        self.segments = QtWidgets.QLineEdit()
        self.segments.setPlaceholderText("各段 直径x长度 mm，从左到右，如 30x40, 40x60, 35x25, 30x30")
        self.chamfer = QtWidgets.QLineEdit("1")
        self.stock_d = QtWidgets.QLineEdit()
        self.stock_d.setPlaceholderText("毛坯直径 mm（空 = 最大直径 + 4 向上取整）")
        for label, x in (("机床", self.turn_machine), ("阶梯轴", self.segments), ("两端倒角 mm", self.chamfer), ("毛坯", self.stock_d)):
            f.addRow(label, x)
        self.tabs.addTab(w, "车削（阶梯轴）")
        # 铣削
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.mill_machine = combo(("mill",))
        self.box = QtWidgets.QLineEdit()
        self.box.setPlaceholderText("矩形毛坯 x0 y0 x1 y1（上表面 Z0），如 -5 -5 105 65")
        self.features = QtWidgets.QPlainTextEdit()
        self.features.setPlaceholderText("每行一项：\n外轮廓 x0 y0 x1 y1 圆角 深\n型腔 x0 y0 x1 y1 圆角 深\n槽 ax ay bx by 宽 深\n孔 直径 深 x1 y1 x2 y2 …")
        for label, x in (("机床", self.mill_machine), ("毛坯", self.box), ("特征", self.features)):
            f.addRow(label, x)
        self.tabs.addTab(w, "铣削（2.5 轴）")
        # 检查
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        self.check_machine = combo(("lathe", "mill"))
        self.open_button = QtWidgets.QPushButton("打开程序文件 …")
        row.addWidget(QtWidgets.QLabel("机床"))
        row.addWidget(self.check_machine, 1)
        row.addWidget(self.open_button)
        v.addLayout(row)
        self.source = QtWidgets.QPlainTextEdit()
        self.source.setPlaceholderText("粘贴或打开 G 代码（FANUC 风格；FreeCAD CAM 工作台用 linuxcnc / fanuc 后处理输出的也可以）")
        v.addWidget(self.source)
        self.tabs.addTab(w, "检查 G 代码")
        self.run_button = QtWidgets.QPushButton("生成 / 检查")
        lay.addWidget(self.run_button)
        self.status = QtWidgets.QLabel(self.machine_note)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.checks = QtWidgets.QListWidget()
        self.gcode = QtWidgets.QPlainTextEdit()
        self.gcode.setReadOnly(True)
        split.addWidget(self.checks)
        split.addWidget(self.gcode)
        lay.addWidget(split, 1)
        self.save_button = QtWidgets.QPushButton("保存 G 代码 …")
        self.save_button.setEnabled(False)
        lay.addWidget(self.save_button)
        self.run_button.clicked.connect(lambda *_: self.start())
        self.open_button.clicked.connect(lambda *_: self.open_file())
        self.save_button.clicked.connect(lambda *_: self.save())
        self.done.connect(self._done, QtCore.Qt.QueuedConnection)

    def setup(self) -> dict:
        from freecad_addon.gui.optimize_dialog import parse_segments

        mode = ("turn", "mill", "check")[self.tabs.currentIndex()]
        s: dict = {"mode": mode}
        if self.kienzle.currentData():
            s["kienzle"] = self.kienzle.currentData()
        if mode == "turn":
            try:
                s["segments"] = parse_segments(self.segments.text())
            except (ValueError, IndexError) as exc:
                raise cam_input.InputError("阶梯轴请按“直径x长度, …”填") from exc
            s["machine"] = self.turn_machine.currentData()
            s["chamfer_mm"] = float(self.chamfer.text() or 0)
            if self.stock_d.text().strip():
                s["stock_d_mm"] = float(self.stock_d.text())
        elif mode == "mill":
            s["machine"] = self.mill_machine.currentData()
            s["stock"] = {"box": cam_input.parse_box(self.box.text())}
            s["features"] = cam_input.parse_features(self.features.toPlainText())
        else:
            s["machine"] = self.check_machine.currentData()
            s["gcode"] = self.source.toPlainText()
        return s

    def open_file(self, path: str | None = None) -> bool:
        if path is None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "打开 G 代码", "", "G 代码 (*.nc *.ngc *.gcode *.tap *.cnc *.txt);;所有文件 (*)")
        if not path:
            return False
        self.source.setPlainText(Path(path).read_text(encoding="utf-8", errors="replace"))
        self.tabs.setCurrentIndex(2)
        return True

    def start(self) -> bool:
        if self.busy:
            return False
        try:
            setup = self.setup()
        except (cam_input.InputError, ValueError) as exc:
            self.status.setText(str(exc) if isinstance(exc, cam_input.InputError) else "请填数字")
            return False
        if not setup.get("machine"):
            self.status.setText("没有这类机床：在 ~/.freecad-ai-parts/machines.yaml 里加")
            return False
        import analysis

        self.busy = True
        self.run_button.setEnabled(False)
        self.status.setText("正在计算 …")

        def work() -> None:
            try:
                out = analysis.run("cam", setup)
            except Exception as exc:  # noqa: BLE001
                out = {"status": "failed", "messages": [str(exc)]}
            self.done.emit(out)

        threading.Thread(target=work, name="fap-cam", daemon=True).start()
        return True

    def _done(self, out: dict) -> None:
        self.busy = False
        self.run_button.setEnabled(True)
        self.status.setText("；".join([cam_input.summary(out), *out.get("messages", [])]) if out.get("status") == "ok"
                            else cam_input.summary(out))
        self.checks.clear()
        if out.get("status") != "ok":
            self.save_button.setEnabled(False)
            return
        self.result = out
        mark = {"error": "✖", "warn": "⚠", "unknown": "？"}
        for p in out["data"]["programs"]:
            tm = p["time"]
            self.checks.addItem(f"【{p['title']}】切削 {tm['cut_s']:.0f} s，快移 {tm['rapid_s']:.0f} s，换刀 {tm['tool_s']:.0f} s")
            for c in p["checks"]:
                where = f"第 {c['line']} 行：" if c.get("line") else ""
                self.checks.addItem(f"  {mark.get(c['level'], '·')} {where}{c['text']}")
            if not p["checks"]:
                self.checks.addItem("  ✔ 没有发现问题")
        self.gcode.setPlainText("\n".join(p["gcode"] for p in out["data"]["programs"]))
        self.save_button.setEnabled(out["data"]["mode"] != "check")

    def save(self, folder: str | None = None) -> list[str]:
        if not self.result:
            return []
        if folder is None:
            folder = QtWidgets.QFileDialog.getExistingDirectory(self, "保存到文件夹")
        if not folder:
            return []
        paths = []
        for p in self.result["data"]["programs"]:
            path = Path(folder) / f"O{p['number']:04d}.nc"
            path.write_text(p["gcode"], encoding="utf-8")
            paths.append(str(path))
        self.status.setText("已保存：" + "、".join(paths))
        return paths
