"""有限元 · 疲劳窗口（ADR-0056，M10 第三步）：选零件 → 在三维视图中选面加约束与载荷 → 本机计算 → 应力云图着色 →
安全系数、固有频率 → 用载荷谱（恒幅或多体动力学的关节力矩记录）算疲劳寿命。

计算在 analysis/fea、analysis/fatigue，后台线程中进行。零件按所选对象的形状导出 STEP；FreeCAD 中选的面按中心与面积对应到
分析模块的面编号。表面、尺寸系数须按教材图表填写，不给缺省值。
"""

from __future__ import annotations

import itertools
import math
import tempfile
import threading
from pathlib import Path

from PySide import QtCore, QtWidgets

LOAD_KINDS = (("fixed", "固定"), ("force", "力 N（x, y, z）"), ("torque", "扭矩 N·m（绕面的轴线）"), ("pressure", "压力 MPa"),
              ("temperature", "定温 ℃"), ("convection", "对流 h W/(m²·K), 环境 ℃"), ("heat_flux", "发热 W"))
THERMAL_KINDS = ("temperature", "convection", "heat_flux")


def match_face(faces: list[dict], center, area: float, tol: float = 1e-3) -> int | None:
    """FreeCAD 的面（中心、面积）→ 分析模块的面编号。"""
    best, err = None, math.inf
    for f in faces:
        d = math.dist(f["center"], center) + abs(f["area_mm2"] - area) / max(area, 1e-9)
        if d < err:
            best, err = f["id"], d
    return best if err < max(tol * 100, 1e-2) else None


def colors(values, lo=None, hi=None):
    """应力 → 颜色（蓝 → 青 → 绿 → 黄 → 红）。"""
    lo = min(values) if lo is None else lo
    hi = max(values) if hi is None else hi
    stops = [(0, (0.17, 0.36, 0.84)), (0.3, (0.18, 0.77, 0.71)), (0.55, (0.61, 0.88, 0.36)), (0.78, (0.95, 0.72, 0.02)),
             (1, (1.0, 0.36, 0.42))]
    out = []
    for v in values:
        t = 0.0 if hi <= lo else min(max((v - lo) / (hi - lo), 0.0), 1.0)
        for (a, ca), (b, cb) in itertools.pairwise(stops):
            if t <= b:
                f = (t - a) / (b - a)
                out.append(tuple(ca[i] + (cb[i] - ca[i]) * f for i in range(3)))
                break
    return out


class FeaPanel(QtWidgets.QDockWidget):
    done = QtCore.Signal(object)

    def __init__(self, parent=None, mbd_result=None):
        super().__init__("有限元 · 疲劳", parent)
        self.setObjectName("FapFeaPanel")
        self.mbd_result = mbd_result  # 可调用：返回多体动力学的最新结果（疲劳载荷谱用）
        self.step_path: str | None = None
        self.obj = None
        self.faces: list[dict] = []
        self.loads: list[dict] = []
        self.result: dict | None = None
        self.fatigue: dict | None = None
        self.node = None
        self.busy = False
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        self.part_label = QtWidgets.QLabel("（未选零件）")
        self.pick_button = QtWidgets.QPushButton("用选中的零件")
        row.addWidget(self.part_label, 1)
        row.addWidget(self.pick_button)
        lay.addLayout(row)
        form = QtWidgets.QFormLayout()
        self.material = QtWidgets.QComboBox()
        from analysis.common import materials

        for m in materials.all_materials():
            self.material.addItem(m["name"], m["id"])
        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("强度（静力）", "static")
        self.kind.addItem("固有频率", "modal")
        self.kind.addItem("温度场", "thermal")
        self.kind.addItem("热应力（温度 + 结构）", "thermo_mech")
        self.mesh = QtWidgets.QLineEdit()
        self.mesh.setPlaceholderText("网格尺寸 mm（空 = 自动）")
        form.addRow("材料", self.material)
        form.addRow("分析", self.kind)
        form.addRow("网格", self.mesh)
        lay.addLayout(form)
        box = QtWidgets.QGroupBox("约束与载荷（先在三维视图中选面）")
        bl = QtWidgets.QVBoxLayout(box)
        r2 = QtWidgets.QHBoxLayout()
        self.load_kind = QtWidgets.QComboBox()
        for k, label in LOAD_KINDS:
            self.load_kind.addItem(label, k)
        self.load_value = QtWidgets.QLineEdit()
        self.load_value.setPlaceholderText("值（力写 x, y, z）")
        self.add_button = QtWidgets.QPushButton("加到所选面")
        for x in (self.load_kind, self.load_value, self.add_button):
            r2.addWidget(x)
        bl.addLayout(r2)
        self.load_list = QtWidgets.QListWidget()
        self.load_list.setMaximumHeight(90)
        bl.addWidget(self.load_list)
        self.clear_button = QtWidgets.QPushButton("清空")
        bl.addWidget(self.clear_button)
        lay.addWidget(box)
        self.run_button = QtWidgets.QPushButton("计算")
        lay.addWidget(self.run_button)
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        fbox = QtWidgets.QGroupBox("疲劳寿命（用强度结果的最大应力）")
        ff = QtWidgets.QFormLayout(fbox)
        self.series_kind = QtWidgets.QComboBox()
        self.series_kind.addItem("起停：0 → 所加载荷 → 0", "startstop")
        self.series_kind.addItem("对称：−载荷 → +载荷", "reversed")
        self.series_kind.addItem("多体动力学的关节力矩记录", "mbd")
        self.mbd_joint = QtWidgets.QLineEdit()
        self.mbd_joint.setPlaceholderText("关节名，如 j2")
        self.surface = QtWidgets.QLineEdit()
        self.surface.setPlaceholderText("表面状态系数 β（查教材图表，如磨削）")
        self.size = QtWidgets.QLineEdit()
        self.size.setPlaceholderText("尺寸系数 ε（查教材图表）")
        self.block = QtWidgets.QLineEdit("1")
        ff.addRow("载荷谱", self.series_kind)
        ff.addRow("关节", self.mbd_joint)
        ff.addRow("β", self.surface)
        ff.addRow("ε", self.size)
        ff.addRow("一块时长 s", self.block)
        self.fatigue_button = QtWidgets.QPushButton("算疲劳寿命")
        ff.addRow("", self.fatigue_button)
        self.fatigue_label = QtWidgets.QLabel("")
        self.fatigue_label.setWordWrap(True)
        ff.addRow("", self.fatigue_label)
        lay.addWidget(fbox)
        self.status = QtWidgets.QLabel("选一个零件，点“用选中的零件”。")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addStretch(1)
        self.setWidget(w)
        self.pick_button.clicked.connect(lambda *_: self.pick())
        self.add_button.clicked.connect(lambda *_: self.add_from_selection())
        self.clear_button.clicked.connect(lambda *_: self.clear_loads())
        self.run_button.clicked.connect(lambda *_: self.compute())
        self.fatigue_button.clicked.connect(lambda *_: self.compute_fatigue())
        self.done.connect(self._done, QtCore.Qt.QueuedConnection)

    # ------------------------------------------------------------ 零件与面

    def set_part(self, obj) -> bool:
        """导出所选对象的形状为 STEP，列出面。"""
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull() or not shape.Solids:
            self.status.setText("所选对象没有实体形状")
            return False
        tmp = Path(tempfile.mkdtemp(prefix="fap-fea-")) / f"{obj.Name}.step"
        shape.exportStep(str(tmp))
        import analysis

        out = analysis.run("fea", {"analysis": "faces", "step_path": str(tmp)})
        if out["status"] != "ok":
            self.status.setText("；".join(out["messages"]))
            return False
        self.obj, self.step_path, self.faces = obj, str(tmp), out["data"]["faces"]
        self.part_label.setText(f"{obj.Label}（{len(self.faces)} 个面）")
        self.clear_loads()
        self.status.setText("在三维视图中选面，选载荷类型、填值，点“加到所选面”。")
        return True

    def pick(self) -> bool:
        import FreeCADGui

        sel = FreeCADGui.Selection.getSelection()
        if not sel:
            self.status.setText("请先在三维视图或树中选一个零件")
            return False
        return self.set_part(sel[0])

    def face_ids(self, names) -> list[int]:
        """FreeCAD 面名（Face3）→ 分析模块的面编号。"""
        out = []
        for n in names:
            f = self.obj.Shape.getElement(n)
            fid = match_face(self.faces, list(f.CenterOfMass), f.Area)
            if fid is None:
                raise ValueError(f"{n} 对不上分析模块的面")
            out.append(fid)
        return out

    def add_from_selection(self) -> bool:
        import FreeCADGui

        names = [s for x in FreeCADGui.Selection.getSelectionEx() for s in x.SubElementNames if s.startswith("Face")]
        if self.obj is None or not names:
            self.status.setText("请先选零件，再在三维视图中选面")
            return False
        try:
            return self.add_load(self.load_kind.currentData(), self.face_ids(names), self.load_value.text())
        except ValueError as exc:
            self.status.setText(str(exc))
            return False

    def add_load(self, kind: str, faces: list[int], value: str = "") -> bool:
        ld: dict = {"type": kind, "faces": faces}
        try:
            if kind == "force":
                v = [float(x) for x in value.replace("，", ",").split(",")]
                if len(v) != 3:
                    raise ValueError
                ld["vector_n"] = v
            elif kind == "pressure":
                ld["value_mpa"] = float(value)
            elif kind == "temperature":
                ld["value_c"] = float(value)
            elif kind == "heat_flux":
                ld["power_w"] = float(value)
            elif kind == "convection":
                h, t = (float(x) for x in value.replace("，", ",").split(","))
                ld.update(h_w_m2k=h, t_inf_c=t)
            elif kind == "torque":
                ld["value_nm"] = float(value)
                f = next(x for x in self.faces if x["id"] == faces[0])
                axis = f.get("axis") or f.get("normal")
                origin = f.get("axis_origin") or f["center"]
                if axis is None:
                    raise ValueError
                ld["axis"] = {"origin": origin, "dir": axis}
        except (ValueError, StopIteration):
            self.status.setText("值填写有误（力写 x, y, z；对流写 h, 环境温度；扭矩要加在有轴线或法向的面上）")
            return False
        self.loads.append(ld)
        label = dict(LOAD_KINDS)[kind].split(" ")[0]
        self.load_list.addItem(f"{label} 面 {faces}" + (f"：{value}" if value and kind != "fixed" else ""))
        return True

    def clear_loads(self) -> None:
        self.loads = []
        self.load_list.clear()

    # ------------------------------------------------------------ 计算

    def setup(self) -> dict:
        s = {"analysis": self.kind.currentData(), "step_path": self.step_path, "material": self.material.currentData(),
             "loads": [ld for ld in self.loads if ld["type"] not in THERMAL_KINDS]}
        if self.module() == "thermal":
            s["thermal"] = [ld for ld in self.loads if ld["type"] in THERMAL_KINDS]
        if self.mesh.text().strip():
            s["mesh"] = {"size_mm": float(self.mesh.text())}
        return s

    def module(self) -> str:
        return "thermal" if self.kind.currentData() in ("thermal", "thermo_mech") else "fea"

    def compute(self) -> bool:
        if self.busy or self.step_path is None:
            self.status.setText("请先选零件" if self.step_path is None else "正在计算")
            return False
        import analysis

        module = self.module()
        st = next((m for m in analysis.modules() if m["id"] == module), None)
        if st is None or not st["available"]:
            self.status.setText("分析模块不可用：" + "、".join((st or {}).get("missing", [])) + "。" + (st or {}).get("install", ""))
            return False
        try:
            setup = self.setup()
        except ValueError:
            self.status.setText("网格尺寸须为数字")
            return False
        self.busy = True
        self.run_button.setEnabled(False)
        self.status.setText("正在划网格、求解 …")

        def work() -> None:
            try:
                out = analysis.run(module, setup)
            except Exception as exc:  # noqa: BLE001 — 交给界面
                out = {"status": "failed", "messages": [str(exc)]}
            self.done.emit(out)

        threading.Thread(target=work, name="fap-fea", daemon=True).start()
        return True

    def _done(self, out: dict) -> None:
        self.busy = False
        self.run_button.setEnabled(True)
        if out.get("status") != "ok":
            self.status.setText("没有算出：" + "；".join(out.get("messages", [])))
            return
        self.result = out
        d = out["data"]
        kind = out["setup"].get("analysis")
        if kind == "thermal":
            self.summary.setText(f"最高 {d['t_max_c']:.1f} ℃、最低 {d['t_min_c']:.1f} ℃、表面平均 {d['t_surface_mean_c']:.1f} ℃；"
                                 f"输入 {d['heat_in_w']:g} W，对流散走 {d['heat_out_convection_w']:g} W")
        elif kind == "thermo_mech":
            self.summary.setText(f"最高 {d['t_max_c']:.1f} ℃；热应力最大 {d['vm_max_mpa']:.1f} MPa，"
                                 f"安全系数 {d['safety_factor']:.2f}，最大热变形 {d['u_max_mm']:.4f} mm")
        elif kind == "modal":
            self.summary.setText("固有频率：" + "，".join(f"{f['hz']:.1f} Hz" for f in d["freqs"]) +
                                 f"（{d['elements']} 个单元）")
        else:
            self.summary.setText(f"最大 Von Mises 应力 {d['vm_max_mpa']:.1f} MPa（面 {d.get('vm_max_faces')}），"
                                 f"安全系数 {d['safety_factor']:.2f}（按{d['strength_kind']} {d['strength_mpa']:g} MPa），"
                                 f"最大位移 {d['u_max_mm']:.4f} mm；{d['elements']} 个单元、网格 {d['mesh_size_mm']} mm")
        self.show_surface(d["surface"], "temp" if kind == "thermal" else "vm")
        self.status.setText(f"算完（{out.get('elapsed_s', 0):.1f} s，CalculiX {out['solver']['version']}）。"
                            + "；".join(out["limitations"][:1]))

    def show_surface(self, surface: dict, field: str = "vm") -> None:
        """在三维视图中按应力（或振型幅值）着色显示表面。"""
        try:
            import FreeCADGui
            from pivy import coin
        except ImportError:
            return
        view = getattr(FreeCADGui.ActiveDocument, "ActiveView", None) if FreeCADGui.ActiveDocument else None
        if view is None:
            return
        root = view.getSceneGraph()
        if self.node is not None:
            root.removeChild(self.node)
        sep = coin.SoSeparator()
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(surface["positions"]), [tuple(p) for p in surface["positions"]])
        mat = coin.SoMaterial()
        cols = colors(surface[field])
        mat.diffuseColor.setValues(0, len(cols), cols)
        bind = coin.SoMaterialBinding()
        bind.value = coin.SoMaterialBinding.PER_VERTEX_INDEXED
        faces = coin.SoIndexedFaceSet()
        idx = []
        for t in surface["triangles"]:
            idx += [int(t[0]), int(t[1]), int(t[2]), -1]
        faces.coordIndex.setValues(0, len(idx), idx)
        faces.materialIndex.setValues(0, len(idx), idx)
        for n in (coords, mat, bind, faces):
            sep.addChild(n)
        root.addChild(sep)
        self.node = sep
        if self.obj is not None and getattr(self.obj, "ViewObject", None) is not None:
            self.obj.ViewObject.Visibility = False

    # ------------------------------------------------------------ 疲劳

    def load_ref(self) -> float | None:
        """强度计算中唯一一个非约束载荷的大小（扭矩 N·m、力 N、压力 MPa）。"""
        active = [ld for ld in (self.result or {}).get("setup", {}).get("loads", []) if ld["type"] in ("force", "torque",
                                                                                                         "pressure")]
        if len(active) != 1:
            return None
        ld = active[0]
        if ld["type"] == "force":
            return math.sqrt(sum(x * x for x in ld["vector_n"]))
        return abs(ld.get("value_nm", ld.get("value_mpa", 0)))

    def compute_fatigue(self) -> bool:
        if not self.result or self.result["setup"].get("analysis") != "static":
            self.fatigue_label.setText("请先做强度计算")
            return False
        ref = self.load_ref()
        if not ref:
            self.fatigue_label.setText("强度计算中须只有一个载荷（作为参考载荷）")
            return False
        kind = self.series_kind.currentData()
        if kind == "startstop":
            series = [0.0, ref]
        elif kind == "reversed":
            series = [-ref, ref]
        else:
            mbd = self.mbd_result() if self.mbd_result else None
            joint = self.mbd_joint.text().strip()
            s = ((mbd or {}).get("data", {}).get("series") or {}).get(joint)
            if not s:
                self.fatigue_label.setText("没有这个关节的多体动力学结果（先在多体动力学窗口算一次）")
                return False
            series = s["drive"]
        try:
            setup = {"material": self.material.currentData(), "stress_ref_mpa": self.result["data"]["vm_max_mpa"],
                     "load_ref": ref, "load_series": series, "block_seconds": float(self.block.text() or 0),
                     "surface_factor": float(self.surface.text()), "size_factor": float(self.size.text())}
        except ValueError:
            self.fatigue_label.setText("请填写 β、ε 与一块时长（数字）")
            return False
        import analysis

        out = analysis.run("fatigue", setup)
        if out["status"] != "ok":
            self.fatigue_label.setText("；".join(out["messages"]))
            return False
        self.fatigue = out
        d = out["data"]
        if d["infinite"]:
            text = "无限寿命（所有循环都低于修正后的疲劳极限）"
        else:
            hours = f"，约 {d['life_hours']:.4g} 小时" if d["life_hours"] else ""
            text = f"寿命 {d['life_blocks']:.4g} 块{hours}"
        self.fatigue_label.setText(f"{text}；修正后疲劳极限 {d['fatigue_strength_mpa']:.1f} MPa，每块 {d['cycles_per_block']} 个循环")
        return True
