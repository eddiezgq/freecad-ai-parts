"""设计优化（轴）对话框（ADR-0056，M10 第四步）：阶梯轴各段直径在范围内自动寻优——安全系数与疲劳要求下最轻；
结果可在 FreeCAD 中生成新的轴实体。计算在 analysis/optimize（Optuna 驱动有限元），后台线程中进行。
"""

from __future__ import annotations

import threading

from PySide import QtCore, QtWidgets


def parse_segments(text: str) -> list[list[float]]:
    """“30x40, 35x12, 40x60” → [[30, 40], [35, 12], [40, 60]]（直径 x 长度，mm）。"""
    out = []
    for part in text.replace("，", ",").split(","):
        part = part.strip().lower().replace("×", "x")
        if not part:
            continue
        d, length = (float(x) for x in part.split("x"))
        if d <= 0 or length <= 0:
            raise ValueError
        out.append([d, length])
    if not out:
        raise ValueError
    return out


def parse_groups(text: str) -> list[list[int]]:
    """“0+4, 2” → [[0, 4], [2]]：同一组的段一起变。"""
    groups = []
    for part in text.replace("，", ",").split(","):
        part = part.strip()
        if part:
            groups.append([int(x) for x in part.split("+")])
    if not groups:
        raise ValueError
    return groups


class OptimizeDialog(QtWidgets.QDialog):
    done = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设计优化：阶梯轴（本机计算）")
        self.resize(720, 560)
        self.result: dict | None = None
        self.busy = False
        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.segments = QtWidgets.QLineEdit()
        self.segments.setPlaceholderText("各段 直径x长度 mm，从左到右，如 30x40, 35x12, 40x60, 35x25, 30x30")
        self.torque = QtWidgets.QLineEdit()
        self.torque.setPlaceholderText("传递扭矩 N·m（左端固定，右端加扭矩）")
        self.groups = QtWidgets.QLineEdit()
        self.groups.setPlaceholderText("要优化的段号（从 0 起），一起变的用 +，如 0+4, 2")
        self.low, self.high = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.low.setPlaceholderText("直径下限 mm")
        self.high.setPlaceholderText("直径上限 mm")
        self.material = QtWidgets.QComboBox()
        from analysis.common import materials

        for m in materials.all_materials():
            self.material.addItem(m["name"], m["id"])
        self.sf = QtWidgets.QLineEdit("1.3")
        self.fatigue = QtWidgets.QCheckBox("要求起停载荷下无限寿命")
        self.beta, self.eps = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.beta.setPlaceholderText("表面系数 β（查教材图表）")
        self.eps.setPlaceholderText("尺寸系数 ε（查教材图表）")
        self.trials = QtWidgets.QSpinBox()
        self.trials.setRange(4, 60)
        self.trials.setValue(20)
        for label, w in (("轴段", self.segments), ("扭矩", self.torque), ("优化的段", self.groups), ("下限", self.low),
                         ("上限", self.high), ("材料", self.material), ("安全系数 ≥", self.sf), ("", self.fatigue),
                         ("β", self.beta), ("ε", self.eps), ("计算次数", self.trials)):
            form.addRow(label, w)
        lay.addLayout(form)
        self.run_button = QtWidgets.QPushButton("开始优化")
        lay.addWidget(self.run_button)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["尺寸", "质量 kg", "安全系数", "说明"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        self.make_button = QtWidgets.QPushButton("在 FreeCAD 中生成最优的轴")
        self.make_button.setEnabled(False)
        lay.addWidget(self.make_button)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.run_button.clicked.connect(lambda *_: self.start())
        self.make_button.clicked.connect(lambda *_: self.make_shaft())
        self.done.connect(self._done, QtCore.Qt.QueuedConnection)

    def setup(self) -> dict:
        segs = parse_segments(self.segments.text())
        groups = parse_groups(self.groups.text())
        lo, hi = float(self.low.text()), float(self.high.text())
        s = {"problem": "shaft", "shaft": {"segments": segs, "torque_nm": float(self.torque.text())},
             "vars": [{"name": f"d{g[0]}", "segments": g, "low": lo, "high": hi, "step": 0.5} for g in groups],
             "material": self.material.currentData(), "n_trials": self.trials.value(), "seed": 1,
             "constraints": {"sf_min": float(self.sf.text())}}
        if self.fatigue.isChecked():
            s["constraints"]["fatigue"] = {"surface_factor": float(self.beta.text()), "size_factor": float(self.eps.text()),
                                           "load_series": [0, float(self.torque.text())], "life": "infinite"}
        return s

    def start(self) -> bool:
        if self.busy:
            return False
        try:
            setup = self.setup()
        except (ValueError, IndexError):
            self.status.setText("请按提示填写：轴段“直径x长度”、扭矩、段号、上下限（与疲劳的 β、ε）")
            return False
        import analysis

        st = next((m for m in analysis.modules() if m["id"] == "optimize"), None)
        if st is None or not st["available"]:
            self.status.setText("设计优化不可用：" + "、".join((st or {}).get("missing", [])) + "。" + (st or {}).get("install", ""))
            return False
        self.busy = True
        self.run_button.setEnabled(False)
        self.status.setText(f"正在优化：{setup['n_trials']} 次有限元，每次几秒 …")

        def work() -> None:
            try:
                out = analysis.run("optimize", setup)
            except Exception as exc:  # noqa: BLE001
                out = {"status": "failed", "messages": [str(exc)]}
            self.done.emit(out)

        threading.Thread(target=work, name="fap-opt", daemon=True).start()
        return True

    def _done(self, out: dict) -> None:
        self.busy = False
        self.run_button.setEnabled(True)
        if out.get("status") != "ok":
            self.status.setText("没有算出：" + "；".join(out.get("messages", [])))
            return
        self.result = out
        d = out["data"]
        rows = ([("现行", d["base"])] if d["base"] else []) + [(f"第 {i + 1} 好", r) for i, r in enumerate(d["best"])]
        self.table.setRowCount(len(rows))
        for i, (tag, r) in enumerate(rows):
            size = "，".join(f"{k} = {v:g}" for k, v in r["x"].items())
            note = tag + ("" if r["ok"] else "：" + "；".join(r["violation"]))
            for j, text in enumerate((size, f"{r['mass_kg']:.3f}", f"{r['sf']:.2f}" if r.get("sf") else "—", note)):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.make_button.setEnabled(bool(d["best"]))
        if d["best"] and d["base"]:
            saved = 1 - d["best"][0]["mass_kg"] / d["base"]["mass_kg"]
            self.status.setText(f"最优比现行轻 {saved:.1%}（{len(d['trials'])} 次计算，{out.get('elapsed_s', 0):.0f} s）")
        else:
            self.status.setText("；".join(out["messages"]) or "算完")

    def best_segments(self) -> list[list[float]] | None:
        if not self.result or not self.result["data"]["best"]:
            return None
        segs = [list(s) for s in self.result["setup"]["shaft"]["segments"]]
        for v in self.result["setup"]["vars"]:
            for i in v["segments"]:
                segs[i][0] = self.result["data"]["best"][0]["x"][v["name"]]
        return segs

    def make_shaft(self):
        """在活动文档中按最优尺寸生成轴（沿 z 轴，左端在原点）。"""
        segs = self.best_segments()
        if segs is None:
            return None
        import FreeCAD
        import Part

        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("Optimized")
        z, shape = 0.0, None
        for d, length in segs:
            c = Part.makeCylinder(d / 2, length, FreeCAD.Vector(0, 0, z))
            shape = c if shape is None else shape.fuse(c)
            z += length
        obj = doc.addObject("Part::Feature", "OptimizedShaft")
        obj.Shape = shape.removeSplitter()
        doc.recompute()
        self.status.setText(f"已在 {doc.Label} 中生成 {obj.Label}：" + "，".join(f"Ø{d:g}×{length:g}" for d, length in segs))
        return obj
