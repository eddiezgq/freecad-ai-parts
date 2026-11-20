"""问渠CAM 回放条与程序窗口（ADR-0106 Q2 第 5、6 步）。

视图下方停靠一个窗口：左边是程序（当前行高亮，点一行跳到那一段），右边是回放控制——播放 / 暂停、单步前后、速度、
时间轴（检查清单里带行号的问题在时间轴上标红，点一下跳过去）、事件列表。视图里画：刀具（铣刀圆柱 / 车刀刀尖小球）、
当前这一段（红线）、在制毛坯（铣：高度场网格；车：回转面）。算完以后还能切到“色差”：在制毛坯按与零件的偏差上色（过切红、
合格绿、残留蓝），旁边一条色标。点视图里工序的刀路，程序窗口跳到最近的那一行。
"""

from __future__ import annotations

import json

import FreeCAD
import FreeCADGui
import numpy as np

from assist.i18n import tr as T
from freecad_addon.fc import cam_objects as CO

_DOCK = None
SPEEDS = (1, 5, 20, 100)


def _coin():
    from pivy import coin

    return coin


class Timeline:
    """时间轴：一条横条，红色竖线是事件，蓝色三角是当前时间；点哪里跳到哪里"""

    def __init__(self, owner):
        from PySide import QtCore, QtGui, QtWidgets

        outer = self

        class W(QtWidgets.QWidget):
            def paintEvent(self, _e):
                p = QtGui.QPainter(self)
                w, h = self.width(), self.height()
                p.fillRect(4, h // 2 - 3, w - 8, 6, QtGui.QColor("#cfd8dc"))
                dur = max(owner.rp.duration, 1e-9) if owner.rp else 1.0
                if owner.rp:
                    for e in owner.rp.events:
                        x = 4 + (w - 8) * owner.rp.frames[e["i"]]["t0"] / dur
                        p.setPen(QtGui.QPen(QtGui.QColor("#c62828" if e["level"] == "error" else "#ef6c00"), 2))
                        p.drawLine(int(x), 2, int(x), h - 2)
                x = 4 + (w - 8) * owner.t / dur
                p.setBrush(QtGui.QColor("#1565c0"))
                p.setPen(QtCore.Qt.NoPen)
                p.drawPolygon(QtGui.QPolygon([QtCore.QPoint(int(x) - 6, 0), QtCore.QPoint(int(x) + 6, 0), QtCore.QPoint(int(x), 10)]))
                p.end()

            def mousePressEvent(self, e):
                outer._click(e.pos().x())

            def mouseMoveEvent(self, e):
                outer._click(e.pos().x())

        self.owner = owner
        self.w = W()
        self.w.setMinimumHeight(22)

    def _click(self, x):
        if not self.owner.rp:
            return
        w = max(self.w.width() - 8, 1)
        self.owner.seek(max(0.0, min(1.0, (x - 4) / w)) * self.owner.rp.duration)


class ReplayDock:
    def __init__(self, job):
        from PySide import QtCore, QtWidgets

        self.job = job
        self.items = json.loads(job.Replay or "[]") if hasattr(job, "Replay") else []
        self.rp = None
        self.t = 0.0
        self.speed = 1
        self.frame = -1
        self.mode = "stock"                         # stock / deviation
        self._root = None
        self._last_mesh = None
        self.dock = QtWidgets.QDockWidget(T("回放与程序"))
        self.dock.setObjectName("WqCamReplay")
        body = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(body)
        self.code = QtWidgets.QPlainTextEdit()
        self.code.setReadOnly(True)
        self.code.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.code.cursorPositionChanged.connect(self._code_clicked)
        lay.addWidget(self.code, 3)
        right = QtWidgets.QVBoxLayout()
        row = QtWidgets.QHBoxLayout()
        self.prog = QtWidgets.QComboBox()
        self.prog.addItems([it["title"] for it in self.items])
        self.prog.currentIndexChanged.connect(self.load)
        row.addWidget(self.prog, 2)
        self.btn_prev = QtWidgets.QPushButton("⏮")
        self.btn_play = QtWidgets.QPushButton("▶")
        self.btn_next = QtWidgets.QPushButton("⏭")
        for b, tip in ((self.btn_prev, "上一段"), (self.btn_play, "播放 / 暂停"), (self.btn_next, "下一段")):
            b.setToolTip(T(tip))
            b.setFixedWidth(36)
            row.addWidget(b)
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.btn_play.clicked.connect(self.toggle)
        self.spd = QtWidgets.QComboBox()
        self.spd.addItems([f"{s}×" for s in SPEEDS])
        self.spd.currentIndexChanged.connect(lambda i: setattr(self, "speed", SPEEDS[i]))
        row.addWidget(self.spd)
        self.dev = QtWidgets.QCheckBox(T("色差"))
        self.dev.setToolTip(T("在制毛坯按与零件的偏差上色：过切红、合格绿、残留蓝"))
        self.dev.toggled.connect(self._toggle_dev)
        row.addWidget(self.dev)
        right.addLayout(row)
        self.timeline = Timeline(self)
        right.addWidget(self.timeline.w)
        self.time_label = QtWidgets.QLabel()
        right.addWidget(self.time_label)
        self.legend = QtWidgets.QLabel()
        self.legend.setVisible(False)
        right.addWidget(self.legend)
        self.events = QtWidgets.QListWidget()
        self.events.itemClicked.connect(self._event_clicked)
        right.addWidget(self.events, 1)
        lay.addLayout(right, 2)
        self.dock.setWidget(body)
        self.timer = QtCore.QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)
        self.load(0)

    # ---- 数据
    def load(self, idx):
        from analysis.cam import machines
        from analysis.cam import replay as R

        self.pause()
        if not self.items:
            self.code.setPlainText(T("还没有回放数据：先在作业面板里“计算并检查”"))
            return
        it = self.items[max(0, idx)]
        mach = machines.get(self.job.Machine)
        self.side = it.get("side", "")
        self.rp = R.Replay(it.get("gcode"), mach, it["replay_in"], it.get("checks"))
        self.code.setPlainText(self.rp.gcode)
        self.events.clear()
        for e in self.rp.events:
            self.events.addItem(f"{T('第 {} 行').format(e['line'])}  {T(e['text'])}")
        self._dev_cache = None
        self.frame = -1
        self.seek(0.0)

    # ---- 控制
    def toggle(self):
        if self.timer.isActive():
            self.pause()
        else:
            if self.rp and self.t >= self.rp.duration:
                self.seek(0.0)
            self.timer.start()
            self.btn_play.setText("⏸")

    def pause(self):
        self.timer.stop()
        self.btn_play.setText("▶")

    def _tick(self):
        if not self.rp:
            return
        t = self.t + 0.05 * self.speed
        if t >= self.rp.duration:
            t = self.rp.duration
            self.pause()
        self.seek(t)

    def step(self, d):
        if not self.rp or not self.rp.frames:
            return
        i = self.rp.frame_at(self.t)
        j = max(0, min(len(self.rp.frames) - 1, i + d))
        self.goto_frame(j, end=d > 0)

    def goto_frame(self, i, end=True):
        """跳到第 i 段（走完 / 刚开始）。按段号跳，不按时间：时间为零的段（换刀、同点）也能停上去"""
        if self.rp:
            f = self.rp.frames[i]
            self.seek(f["t1"] if end else f["t0"], at=(i, 1.0 if end else 0.0))

    def seek(self, t, at=None):
        if not self.rp or not self.rp.frames:
            return
        self.t = max(0.0, min(t, self.rp.duration))
        i, s = at if at is not None else self.rp.at(self.t)
        self.time_label.setText(f"{self.t:6.1f} / {self.rp.duration:.1f} s    "
                                + T("第 {} 段 / 共 {} 段，程序第 {} 行").format(i + 1, len(self.rp.frames), self.rp.frames[i]["line"]))
        self._highlight(self.rp.frames[i]["line"])
        self._draw(i, s)
        self.timeline.w.update()

    # ---- 程序窗口
    def _highlight(self, line):
        from PySide import QtGui, QtWidgets

        self._busy = True
        try:
            block = self.code.document().findBlockByNumber(line - 1)
            sel = QtWidgets.QTextEdit.ExtraSelection()
            sel.format.setBackground(QtGui.QColor("#fff59d"))
            sel.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
            cur = QtGui.QTextCursor(block)
            sel.cursor = cur
            self.code.setExtraSelections([sel])
            self.code.setTextCursor(cur)
            self.code.ensureCursorVisible()
            self.current_line = line
        finally:
            self._busy = False

    def _code_clicked(self):
        if getattr(self, "_busy", False) or not self.rp:
            return
        line = self.code.textCursor().blockNumber() + 1
        fr = self.rp.frames_of_line(line)
        if fr:
            self.pause()
            self.goto_frame(fr[0])

    def _event_clicked(self, item):
        e = self.rp.events[self.events.row(item)]
        self.pause()
        self.goto_frame(e["i"])

    def pick(self, p_model):
        """视图里点到刀路上的一点（零件模型坐标）→ 跳到最近的那一段"""
        if not self.rp:
            return None
        q = self._to_prog(p_model)
        i = self.rp.nearest_frame(q, max_dist=5.0)
        if i is not None:
            self.pause()
            self.goto_frame(i)
        return i

    # ---- 坐标
    def _to_model(self, x, y, z):
        """回放的刀尖（铣：工件坐标；车：(半径, 0, z)）→ 零件模型坐标"""
        if self.job.Kind == "turn":
            return CO.to_model(self.job, self.side, 2 * x, 0.0, z)
        return CO.to_model(self.job, self.side, x, y, z)

    def _to_prog(self, p):
        x, y, z = (float(v) for v in p)
        if self.job.Kind == "turn":
            r = (x * x + y * y) ** 0.5
            zm = CO.to_model(self.job, self.side, 0.0, 0.0, 0.0)[2]
            return (r, 0.0, (zm - z) if self.side == "left" else (z - zm))
        zm = CO.to_model(self.job, self.side, 0.0, 0.0, 0.0)[2]
        return (x, y, z - zm)

    # ---- 画
    def _scene(self):
        coin = _coin()
        if self._root is not None:
            return self._root
        view = FreeCADGui.ActiveDocument.ActiveView if FreeCADGui.ActiveDocument else None
        if view is None:
            return None
        self._view = view
        root = coin.SoSeparator()
        root.setName("WqCamReplay")
        # 在制毛坯
        self._stock_sep = coin.SoSeparator()
        self._stock_mat = coin.SoMaterial()
        self._stock_mat.diffuseColor = (0.55, 0.62, 0.70)
        self._stock_bind = coin.SoMaterialBinding()
        self._stock_bind.value = coin.SoMaterialBinding.OVERALL
        self._stock_coords = coin.SoCoordinate3()
        self._stock_faces = coin.SoIndexedFaceSet()
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        hints.creaseAngle = 0.5
        self._light = coin.SoLightModel()
        self._light.model = coin.SoLightModel.PHONG
        for n in (hints, self._light, self._stock_mat, self._stock_bind, self._stock_coords, self._stock_faces):
            self._stock_sep.addChild(n)
        root.addChild(self._stock_sep)
        # 当前这一段、刀具（看色差时不画）
        self._moving = coin.SoSwitch()
        self._moving.whichChild = coin.SO_SWITCH_ALL
        root.addChild(self._moving)
        seg = coin.SoSeparator()
        m = coin.SoMaterial()
        m.diffuseColor = (0.9, 0.1, 0.1)
        m.emissiveColor = (0.9, 0.1, 0.1)
        st = coin.SoDrawStyle()
        st.lineWidth = 3
        self._seg_coords = coin.SoCoordinate3()
        self._seg_line = coin.SoLineSet()
        for n in (m, st, self._seg_coords, self._seg_line):
            seg.addChild(n)
        self._moving.addChild(seg)
        # 刀具
        tool = coin.SoSeparator()
        self._tool_xf = coin.SoTransform()
        tm = coin.SoMaterial()
        tm.diffuseColor = (0.95, 0.75, 0.2)
        self._tool_shape_xf = coin.SoTransform()
        self._tool_cyl = coin.SoCylinder()
        for n in (self._tool_xf, tm, self._tool_shape_xf, self._tool_cyl):
            tool.addChild(n)
        self._moving.addChild(tool)
        view.getSceneGraph().addChild(root)
        self._root = root
        return root

    def tool_position(self):
        """刀尖在模型坐标里的位置（测试、截图用）"""
        v = self._tool_xf.translation.getValue()
        return (v[0], v[1], v[2])

    def _draw(self, i, s):
        coin = _coin()
        if self._scene() is None:
            return
        conv = (lambda x, y, z: CO.to_model_3d(self.job, self.side, x, y, z)) if self.rp.is_mill(i) else self._to_model
        tip = conv(*self.rp.tip(i, s))
        f = self.rp.frames[i]
        a = conv(*self.rp.tip(i, 0.0))
        b = conv(*self.rp.tip(i, 1.0))
        self._seg_coords.point.setValues(0, 2, [a, b])
        self._seg_line.numVertices.setValue(2)
        self._tool_xf.translation.setValue(*tip)
        spec = self.rp.tools.get(f["tool"]) or {}
        if self.rp.is_mill(i):                     # 车铣的动力刀：圆柱沿这一小段的刀轴（ADR-0106 C2b）
            mspec = self.rp.mill_tools.get(f["tool"]) or {}
            d = float(mspec.get("d") or 6.0)
            L = 3 * d
            w = np.asarray(f["pieces"][0][2], float)
            if self.side == "left":
                w = np.array([-w[0], w[1], -w[2]])
            self._tool_cyl.radius = d / 2
            self._tool_cyl.height = L
            self._tool_shape_xf.rotation.setValue(coin.SbRotation(coin.SbVec3f(0, 1, 0), coin.SbVec3f(*map(float, w))))
            self._tool_shape_xf.translation.setValue(*map(float, w * L / 2))
        elif self.job.Kind == "turn":
            r = max(float(spec.get("nose_r") or 0.4), 0.4)
            self._tool_cyl.radius = r
            self._tool_cyl.height = 2 * r
            self._tool_shape_xf.rotation.setValue(coin.SbVec3f(1, 0, 0), 0.0)
            self._tool_shape_xf.translation.setValue(r, 0, r)
        else:
            d = float(spec.get("d") or 10.0)
            L = 3 * d
            self._tool_cyl.radius = d / 2
            self._tool_cyl.height = L
            self._tool_shape_xf.rotation.setValue(coin.SbVec3f(1, 0, 0), 1.5707963267948966)   # 圆柱默认沿 Y，转到沿 Z
            self._tool_shape_xf.translation.setValue(0, 0, L / 2)
        n = f["i"] + (1 if s >= 1.0 - 1e-9 else 0)
        if n != self.frame:
            self.frame = n
            self._draw_stock(n)

    def _draw_stock(self, n):
        from analysis.cam import replay as R

        coin = _coin()
        if self.mode == "deviation" and n == len(self.rp.frames):
            self._draw_deviation()
            return
        self._stock_bind.value = coin.SoMaterialBinding.OVERALL
        self._stock_mat.diffuseColor.setValue(0.55, 0.62, 0.70)
        self._light.model = coin.SoLightModel.PHONG
        st = self.rp.stock_after(n)
        if self.rp.lathe and not isinstance(st, tuple):   # 车铣：铣削段以后是 dexel（Z 组方柱网格）
            v, t = st.z_mesh()
            v = np.array([CO.to_model_3d(self.job, self.side, *p) for p in v]) if len(v) else v
        elif self.rp.lathe:
            z, r, ri = st
            v, t = R.lathe_mesh(z, r, ri, stride=max(1, len(z) // 400))
            v = np.array([self._to_model_lathe(p) for p in v]) if len(v) else v
        else:
            dx = st
            stride = max(1, int(max(dx.n[0], dx.n[1]) // 160))
            v, t = R.height_mesh(dx, stride=stride)
            if len(v):
                v = v + np.array(self._to_model(0.0, 0.0, 0.0))
        self._set_mesh(v, t)

    def _to_model_lathe(self, p):
        # lathe_mesh 的点是 (r cos, r sin, z)：z 按装夹换到模型
        zm = self._to_model(0.0, 0.0, p[2])[2]
        return (p[0], p[1], zm)

    def _set_mesh(self, v, t):
        self._stock_coords.point.setNum(len(v))
        if len(v):
            self._stock_coords.point.setValues(0, len(v), [tuple(map(float, p)) for p in v])
        idx = np.full((len(t), 4), -1, int)
        idx[:, :3] = t
        self._stock_faces.coordIndex.setNum(idx.size)
        if idx.size:
            self._stock_faces.coordIndex.setValues(0, idx.size, [int(x) for x in idx.ravel()])
        self._last_mesh = (len(v), len(t))

    # ---- 色差
    def _toggle_dev(self, on):
        coin = _coin()
        self.mode = "deviation" if on else "stock"
        self.legend.setVisible(on)
        if self._scene() is not None:
            self._moving.whichChild = coin.SO_SWITCH_NONE if on else coin.SO_SWITCH_ALL
        if on and self.rp:
            self.seek(self.rp.duration)
        elif self.rp:
            self.frame = -1
            self.seek(self.t)

    def deviation(self):
        """加工完的毛坯与零件模型的偏差（铣：dexel 比对；车：半径网格比对）。返回 {"over_max", "under_max", "points", "dev"}"""
        if self._dev_cache is not None:
            return self._dev_cache
        from freecad_addon.fc import cam_deviation as CD

        self._dev_cache = CD.for_job(self.job, self.rp, self.side)
        return self._dev_cache

    def _draw_deviation(self):
        coin = _coin()
        res = self.deviation()
        if res is None:
            self.legend.setText(T("这个程序没有零件模型可比（外来刀路或没有模型）"))
            return
        v, t, dev = res["mesh"]
        if len(v):
            v = np.asarray(v) + (np.array(self._to_model(0.0, 0.0, 0.0)) if not self.rp.lathe else 0.0)
            if self.rp.lathe:
                v = np.array([self._to_model_lathe(p) for p in v])
        self._set_mesh(v, t)
        # 颜色里直接带上明暗（固定光源方向），看色差时不用场景灯光：每个面的颜色一定是它偏差的颜色，深浅只表示朝向
        tri = np.asarray(v)[np.asarray(t)] if len(t) else np.zeros((0, 3, 3))
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]) if len(tri) else np.zeros((0, 3))
        nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
        light = np.array([0.35, -0.55, 0.76])
        shade = 0.45 + 0.55 * np.abs(nrm @ light)
        cols = [tuple(float(c) * float(k) for c in _dev_color(d, res["tol"])) for d, k in zip(dev, shade, strict=True)]
        self._light.model = coin.SoLightModel.BASE_COLOR
        self._stock_bind.value = coin.SoMaterialBinding.PER_FACE
        self._stock_mat.diffuseColor.setNum(len(cols))
        if cols:
            self._stock_mat.diffuseColor.setValues(0, len(cols), cols)
        self.legend.setText(T("色差：红 = 过切（最多 {:.3f} mm），绿 = 公差 ±{:g} mm 内，蓝 = 残留（最多 {:.3f} mm）")
                            .format(res["over_max"], res["tol"], res["under_max"]))

    def close(self):
        self.pause()
        if self._root is not None:
            try:
                self._view.getSceneGraph().removeChild(self._root)
            except Exception as exc:  # noqa: BLE001  视图已经关了
                FreeCAD.Console.PrintLog(f"问渠CAM 回放：清理视图 {exc}\n")
            self._root = None
        self.dock.close()


def _dev_color(d, tol):
    """偏差 → 颜色：过切红、合格绿、残留蓝（越深越浓，满色在 10 倍公差）"""
    if d < -tol:
        k = min(1.0, (-d) / (10 * tol))
        return (0.85, 0.35 * (1 - k), 0.3 * (1 - k))
    if d > tol:
        k = min(1.0, d / (10 * tol))
        return (0.35 * (1 - k), 0.45 * (1 - k) + 0.2, 0.95)
    return (0.25, 0.75, 0.3)


def open_for(job) -> ReplayDock:
    """打开（或换成）这个作业的回放窗口"""
    from PySide import QtCore

    global _DOCK
    if _DOCK is not None:
        _DOCK.close()
    _DOCK = ReplayDock(job)
    FreeCADGui.getMainWindow().addDockWidget(QtCore.Qt.BottomDockWidgetArea, _DOCK.dock)
    _DOCK.dock.show()
    return _DOCK


class _Observer:
    """点视图里工序的刀路：回放窗口开着时跳到最近的那一段"""

    def addSelection(self, doc, obj, sub, pnt):
        if _DOCK is None or not pnt:
            return
        o = FreeCAD.getDocument(doc).getObject(obj) if doc else None
        if o is not None and CO.is_op(o) and CO.job_of(o) is _DOCK.job:
            _DOCK.pick(pnt)


_OBS = None


def install_observer():
    global _OBS
    if _OBS is None:
        _OBS = _Observer()
        FreeCADGui.Selection.addObserver(_OBS)


class ReplayCommand:
    def GetResources(self):
        return {"MenuText": T("回放与程序…"), "ToolTip": T("按程序回放：刀具怎么走、在哪一行撞；程序窗口与刀路联动；算完看色差")}

    def IsActive(self):
        return _selected_job() is not None

    def Activated(self):
        job = _selected_job()
        if job is not None:
            install_observer()
            open_for(job)


def _selected_job():
    for o in FreeCADGui.Selection.getSelection():
        j = o if CO.is_job(o) else CO.job_of(o)
        if j is not None:
            return j
    doc = FreeCAD.ActiveDocument
    jobs = [o for o in doc.Objects if CO.is_job(o)] if doc else []
    return jobs[-1] if len(jobs) == 1 else None
