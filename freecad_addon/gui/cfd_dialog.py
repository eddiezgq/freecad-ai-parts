"""流体分析对话框（ADR-0059，M11 第三步）：选零件 → 来流方向、风速、空气温度（可选表面温度）→ 本机 OpenFOAM 虚拟风洞 →
阻力、阻力系数、散热量与平均散热系数、各面结果，按散热系数或压力给零件各面着色；“标准题核对”跑两道教材题。

OpenFOAM 不随 FreeCAD 安装；没装时窗口说明安装方法。计算在 analysis/cfd，后台线程中进行。零件按所选对象的形状导出 STEP，
各面按中心与面积对应到分析模块的面编号（与有限元相同）。
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from PySide import QtCore, QtWidgets

from freecad_addon.gui.fea_panel import colors, match_face

DIRECTIONS = (("+x", "沿 +X 吹"), ("-x", "沿 −X 吹"), ("+y", "沿 +Y 吹"), ("-y", "沿 −Y 吹"), ("+z", "沿 +Z 吹"), ("-z", "沿 −Z 吹"))


class CfdDialog(QtWidgets.QDialog):
    done = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("流体分析：虚拟风洞（本机 OpenFOAM）")
        self.resize(760, 640)
        self.obj = None
        self.step_path: str | None = None
        self.faces: list[dict] = []
        self.result: dict | None = None
        self.busy = False
        lay = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.part_label = QtWidgets.QLabel("（未选零件）")
        self.pick_button = QtWidgets.QPushButton("用选中的零件")
        row.addWidget(self.part_label, 1)
        row.addWidget(self.pick_button)
        lay.addLayout(row)
        form = QtWidgets.QFormLayout()
        self.direction = QtWidgets.QComboBox()
        for key, label in DIRECTIONS:
            self.direction.addItem(label, key)
        self.velocity = QtWidgets.QLineEdit("2")
        self.air_t = QtWidgets.QLineEdit("25")
        self.heat = QtWidgets.QCheckBox("算散热：零件表面定温")
        self.wall_t = QtWidgets.QLineEdit()
        self.wall_t.setPlaceholderText("表面温度 ℃")
        self.ground = QtWidgets.QCheckBox("零件放在地面上（−Z 面贴地）")
        self.cells = QtWidgets.QSpinBox()
        self.cells.setRange(10000, 300000)
        self.cells.setSingleStep(10000)
        self.cells.setValue(60000)
        self.level = QtWidgets.QSpinBox()
        self.level.setRange(1, 5)
        self.level.setValue(2)
        self.iterations = QtWidgets.QSpinBox()
        self.iterations.setRange(100, 5000)
        self.iterations.setSingleStep(100)
        self.iterations.setValue(600)
        for label, w in (("来流", self.direction), ("风速 m/s", self.velocity), ("空气温度 ℃", self.air_t), ("", self.heat),
                         ("表面温度", self.wall_t), ("", self.ground), ("目标单元数", self.cells), ("表面加密级别", self.level),
                         ("迭代步数", self.iterations)):
            form.addRow(label, w)
        lay.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        self.run_button = QtWidgets.QPushButton("计算")
        self.bench_button = QtWidgets.QPushButton("标准题核对")
        self.color_kind = QtWidgets.QComboBox()
        self.color_kind.addItem("按散热系数着色", "h_w_m2k")
        self.color_kind.addItem("按压力着色", "p_pa")
        row.addWidget(self.run_button)
        row.addWidget(self.bench_button)
        row.addWidget(self.color_kind)
        lay.addLayout(row)
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["面", "面积 mm²", "平均压力 Pa", "散热 W", "散热系数 W/(m²·K)"])
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.pick_button.clicked.connect(lambda *_: self.pick())
        self.run_button.clicked.connect(lambda *_: self.compute())
        self.bench_button.clicked.connect(lambda *_: self.compute(bench=True))
        self.color_kind.currentIndexChanged.connect(lambda *_: self.paint())
        self.done.connect(self._done, QtCore.Qt.QueuedConnection)
        self.available = self._check_available()

    def _check_available(self) -> bool:
        import analysis

        st = next(m for m in analysis.modules() if m["id"] == "cfd")
        if not st["available"]:
            self.status.setText("流体分析不可用：缺 " + "、".join(st["missing"]) + "。" + st["install"])
            for b in (self.run_button, self.bench_button):
                b.setEnabled(False)
        return st["available"]

    def set_part(self, obj) -> bool:
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull() or not shape.Solids:
            self.status.setText("所选对象没有实体形状")
            return False
        tmp = Path(tempfile.mkdtemp(prefix="fap-cfd-")) / f"{obj.Name}.step"
        shape.exportStep(str(tmp))
        import analysis

        out = analysis.run("fea", {"analysis": "faces", "step_path": str(tmp)})
        if out["status"] != "ok":
            self.status.setText("；".join(out["messages"]))
            return False
        self.obj, self.step_path, self.faces = obj, str(tmp), out["data"]["faces"]
        self.part_label.setText(f"{obj.Label}（{len(self.faces)} 个面）")
        return True

    def pick(self) -> bool:
        import FreeCADGui

        sel = FreeCADGui.Selection.getSelection()
        if not sel:
            self.status.setText("请先在三维视图或树中选一个零件")
            return False
        return self.set_part(sel[0])

    def setup(self) -> dict:
        s = {"step_path": self.step_path, "flow": {"velocity_ms": float(self.velocity.text()), "direction": self.direction.currentData(),
                                                   "air_t_c": float(self.air_t.text())},
             "mesh": {"cells_target": self.cells.value(), "level": self.level.value()}, "solver": {"iterations": self.iterations.value()}}
        if self.heat.isChecked():
            s["heat"] = {"wall_t_c": float(self.wall_t.text())}
        if self.ground.isChecked():
            s["domain"] = {"ground": True}
        return s

    def compute(self, bench: bool = False) -> bool:
        if self.busy or not self.available:
            return False
        if bench:
            setup = {"analysis": "bench"}
        else:
            if not self.step_path:
                self.status.setText("请先选零件")
                return False
            try:
                setup = self.setup()
            except ValueError:
                self.status.setText("风速、温度请填数字（算散热时要填表面温度）")
                return False
        import analysis

        self.busy = True
        self.run_button.setEnabled(False)
        self.bench_button.setEnabled(False)
        self.status.setText("正在计算（网格、流场" + ("" if bench or "heat" not in setup else "、温度场") + "），可能要几分钟 …")

        def work() -> None:
            try:
                out = analysis.run("cfd", setup)
            except Exception as exc:  # noqa: BLE001
                out = {"status": "failed", "messages": [str(exc)], "setup": setup}
            self.done.emit(out)

        threading.Thread(target=work, name="fap-cfd", daemon=True).start()
        return True

    def _done(self, out: dict) -> None:
        self.busy = False
        self.run_button.setEnabled(True)
        self.bench_button.setEnabled(True)
        if out.get("status") != "ok":
            self.status.setText("没有算出：" + "；".join(out.get("messages", [])))
            return
        if out["setup"].get("analysis") == "bench":
            self.summary.setText("标准题核对：" + "；".join(
                f"{c['name']} {c['computed']:.4g}，公式 {c['reference']:.4g}（{c['formula']}），差 {c['relative_error_ratio']:.1%}"
                for c in out["checks"]))
            self.status.setText("")
            return
        self.result = out
        d = out["data"]
        text = (f"阻力 {d['drag_n']:.4g} N（压差 {d['drag_pressure_n']:.3g}、摩擦 {d['drag_friction_n']:.3g}），"
                f"阻力系数 {d['Cd']:.3g}；Re = {d['Re']:.3g}（{'层流' if d['turbulence'] == 'laminar' else 'k-ω SST 湍流'}），"
                f"{d['cells']} 个单元")
        if d.get("heat_w") is not None:
            text += f"；散热 {d['heat_w']:.3g} W，平均散热系数 {d['h_mean']:.3g} W/(m²·K)"
        self.summary.setText(text)
        self.status.setText("；".join(out["messages"]))
        self.table.setRowCount(len(d["faces"]))
        for i, f in enumerate(d["faces"]):
            vals = (str(f["id"]), f"{f['area_mm2']:.1f}", f"{f['p_pa']:.3g}", f"{f['heat_w']:.3g}" if "heat_w" in f else "—",
                    f"{f['h_w_m2k']:.3g}" if "h_w_m2k" in f else "—")
            for j, v in enumerate(vals):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(v))
        self.paint()

    def face_values(self, key: str) -> list[float | None]:
        """零件各面（FreeCAD 的面顺序）的结果值；对不上的面为 None。"""
        if not self.result or self.obj is None:
            return []
        by_id = {f["id"]: f.get(key) for f in self.result["data"]["faces"]}
        out = []
        for face in self.obj.Shape.Faces:
            fid = match_face(self.faces, list(face.CenterOfMass), face.Area)
            out.append(by_id.get(fid))
        return out

    def paint(self) -> bool:
        key = self.color_kind.currentData()
        vals = self.face_values(key)
        if not vals or all(v is None for v in vals) or getattr(self.obj, "ViewObject", None) is None:
            return False
        known = [v for v in vals if v is not None]
        cs = colors(known)
        it = iter(cs)
        self.obj.ViewObject.DiffuseColor = [(*next(it), 0.0) if v is not None else (0.8, 0.8, 0.8, 0.0) for v in vals]
        return True
