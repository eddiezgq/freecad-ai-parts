"""拓扑优化对话框（ADR-0059，M11 第一步）：选算例（MBB 梁、悬臂、简支、支架）、网格、材料用量、板长与板厚 → 本机计算 →
密度图与柔度 → 按密度 0.5 取轮廓拉伸成板件放进 FreeCAD，再用“有限元 · 疲劳”选中它校核。

计算在 analysis/topo，后台线程中进行。
"""

from __future__ import annotations

import threading

from PySide import QtCore, QtGui, QtWidgets


def density_image(density, scale: int = 6) -> QtGui.QImage:
    """密度（[行][列]，0–1）→ 灰度图：1 为黑（有材料），0 为白。"""
    ny, nx = len(density), len(density[0])
    img = QtGui.QImage(nx, ny, QtGui.QImage.Format_RGB32)
    for j, row in enumerate(density):
        for i, v in enumerate(row):
            g = round(255 * (1 - min(max(float(v), 0.0), 1.0)))
            img.setPixel(i, j, QtGui.qRgb(g, g, g))
    return img.scaled(nx * scale, ny * scale)


def plate_shape(outline: list[dict], thickness_mm: float):
    """轮廓（mm）→ FreeCAD 板件（z 向拉伸）。"""
    import FreeCAD
    import Part

    def wire(pts):
        vs = [FreeCAD.Vector(x, y, 0) for x, y in pts]
        return Part.makePolygon([*vs, vs[0]])

    shape = None
    for p in outline:
        face = Part.Face(wire(p["outer"]))
        for h in p["holes"]:
            face = face.cut(Part.Face(wire(h)))
        solid = face.extrude(FreeCAD.Vector(0, 0, thickness_mm))
        shape = solid if shape is None else shape.fuse(solid)
    return shape.removeSplitter()


class TopoDialog(QtWidgets.QDialog):
    done = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("拓扑优化：平面件（本机计算）")
        self.resize(720, 600)
        self.result: dict | None = None
        self.busy = False
        from analysis import topo

        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.preset = QtWidgets.QComboBox()
        for key, p in topo.PRESETS.items():
            self.preset.addItem(p["label"], key)
        self.nelx, self.nely = QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
        self.nelx.setRange(8, 150)
        self.nely.setRange(4, 100)
        self.volfrac = QtWidgets.QDoubleSpinBox()
        self.volfrac.setRange(0.1, 0.9)
        self.volfrac.setSingleStep(0.05)
        self.volfrac.setValue(0.5)
        self.length = QtWidgets.QLineEdit()
        self.length.setPlaceholderText("板长 mm（横向），单元边长 = 板长 / 横向单元数")
        self.thickness = QtWidgets.QLineEdit()
        self.thickness.setPlaceholderText("板厚 mm")
        for label, w in (("算例", self.preset), ("横向单元", self.nelx), ("纵向单元", self.nely), ("材料用量（体积比）", self.volfrac),
                         ("板长", self.length), ("板厚", self.thickness)):
            form.addRow(label, w)
        lay.addLayout(form)
        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.run_button = QtWidgets.QPushButton("开始计算")
        lay.addWidget(self.run_button)
        self.image = QtWidgets.QLabel()
        self.image.setAlignment(QtCore.Qt.AlignCenter)
        self.image.setMinimumHeight(200)
        lay.addWidget(self.image, 1)
        self.make_button = QtWidgets.QPushButton("在 FreeCAD 中生成板件")
        self.make_button.setEnabled(False)
        lay.addWidget(self.make_button)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.preset.currentIndexChanged.connect(lambda *_: self._preset_changed())
        self.run_button.clicked.connect(lambda *_: self.start())
        self.make_button.clicked.connect(lambda *_: self.make_plate())
        self.done.connect(self._done, QtCore.Qt.QueuedConnection)
        self._preset_changed()

    def _preset_changed(self) -> None:
        from analysis import topo

        p = topo.PRESETS[self.preset.currentData()]
        self.nelx.setValue(p["nelx"])
        self.nely.setValue(p["nely"])
        self.note.setText("支承与载荷按算例：" + p["label"] + "。结果是构形建议，生成板件后用“有限元 · 疲劳”按实际载荷校核。")

    def setup(self) -> dict:
        s = {"preset": self.preset.currentData(), "nelx": self.nelx.value(), "nely": self.nely.value(),
             "volfrac": round(self.volfrac.value(), 3)}
        if self.length.text().strip():
            s["length_mm"] = float(self.length.text())
        if self.thickness.text().strip():
            s["thickness_mm"] = float(self.thickness.text())
        return s

    def start(self) -> bool:
        if self.busy:
            return False
        try:
            setup = self.setup()
        except ValueError:
            self.status.setText("板长、板厚请填数字（mm）")
            return False
        import analysis

        self.busy = True
        self.run_button.setEnabled(False)
        self.make_button.setEnabled(False)
        self.status.setText(f"正在计算 {setup['nelx']}×{setup['nely']} 个单元 …")

        def work() -> None:
            try:
                out = analysis.run("topo", setup)
            except Exception as exc:  # noqa: BLE001
                out = {"status": "failed", "messages": [str(exc)]}
            self.done.emit(out)

        threading.Thread(target=work, name="fap-topo", daemon=True).start()
        return True

    def _done(self, out: dict) -> None:
        self.busy = False
        self.run_button.setEnabled(True)
        if out.get("status") != "ok":
            self.status.setText("没有算出：" + "；".join(out.get("messages", [])))
            return
        self.result = out
        d = out["data"]
        self.image.setPixmap(QtGui.QPixmap.fromImage(density_image(d["density"], max(2, 480 // d["nelx"]))))
        can_make = bool(d.get("outline")) and "thickness_mm" in out["setup"]
        self.make_button.setEnabled(can_make)
        text = (f"柔度 {d['history'][0][1]:g} → {d['compliance']:g}（{d['iterations']} 次迭代，"
                f"{'已收敛' if d['converged'] else '未收敛'}），体积比 {d['history'][-1][2]:g}")
        if d.get("area_mm2") is not None:
            text += f"；板面积 {d['area_mm2']:.0f} mm²"
        if not can_make:
            text += "。填板长、板厚后可生成板件"
        self.status.setText("；".join([text, *out["messages"]]))

    def make_plate(self):
        if not self.result or not self.result["data"].get("outline") or "thickness_mm" not in self.result["setup"]:
            return None
        import FreeCAD

        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("Topology")
        obj = doc.addObject("Part::Feature", "TopoPlate")
        obj.Label = "拓扑优化板件"
        obj.Shape = plate_shape(self.result["data"]["outline"], self.result["setup"]["thickness_mm"])
        doc.recompute()
        self.status.setText(f"已在 {doc.Label} 中生成 {obj.Label}：选中它，用“有限元 · 疲劳”加约束与载荷校核")
        return obj
