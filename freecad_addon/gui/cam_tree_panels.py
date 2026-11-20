"""问渠CAM 加工树的任务面板与命令（ADR-0106 Q1）。逻辑在 freecad_addon/fc/cam_objects.py；这里只管输入、显示与命令。

- 双击作业：机床、数控系统、材料、刀具库、夹具、刀长、螺纹；规则 / AI 起草；计算并检查（检查清单按颜色）；保存程序与工艺卡。
- 双击工序：几何（铣：用视图里选中的面 / 清空自动找；车：本工序对应的轮廓、槽、螺纹、内孔）、刀具（只列能用的）、
  切削参数（旁边写刀具样本范围，超出变红）；“应用”重算刀路，“确定”核对后记为已确认（超出范围不能确认）。
- 右键工序：编辑、重算刀路、确认、上移、下移。
"""

from __future__ import annotations

import json

import FreeCAD
import FreeCADGui

from assist.i18n import tr as T
from freecad_addon.fc import cam_objects as CO

COLORS = {"error": "#c62828", "warn": "#b26a00", "unknown": "#6b6b6b", "pass": "#2e7d32"}
TOOL_KINDS = {"rough": ("turn",), "finish": ("turn",), "groove": ("groove",), "thread": ("thread_turn",), "bore": ("bore",),
              "drill": ("drill",), "pocket": ("flat_endmill", "bull_endmill"), "profile": ("flat_endmill", "bull_endmill")}
_LAST = None                  # 最近打开的面板（测试用）


def _close():
    FreeCADGui.Control.closeDialog()


def edit(obj):
    global _LAST
    if CO.is_op(obj):
        _LAST = OpPanel(obj)
    elif CO.is_job(obj):
        _LAST = JobPanel(obj)
    else:
        return None
    if FreeCADGui.Control.activeDialog():
        _close()
    FreeCADGui.Control.showDialog(_LAST)
    return _LAST


# ---------------------------------------------------------------- 作业
class JobPanel:
    def __init__(self, job):
        from PySide import QtWidgets

        from analysis.cam import machines, postproc, power

        self.job = job
        self.result = None
        self.draft_doc = None
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(T("问渠CAM 作业"))
        lay = QtWidgets.QVBoxLayout(self.form)
        f = QtWidgets.QFormLayout()
        self.machine = QtWidgets.QComboBox()
        kind = "lathe" if job.Kind == "turn" else "mill"
        for m in machines.models():
            if m["kind"] == kind and all(a["type"] == "linear" for a in m["axes"]):
                self.machine.addItem(m["name"], m["id"])
        self.machine.setCurrentIndex(max(self.machine.findData(job.Machine), 0))
        f.addRow(T("机床"), self.machine)
        self.post = QtWidgets.QComboBox()
        posts = postproc.posts()                   # 内置 + 用户后处理配置（ADR-0109）
        for c in postproc.available(kind):
            self.post.addItem(posts[c]["name"] + ("" if posts[c]["verified"] else T("（未经实机验证）")), c)
        from analysis.cam import postcfg

        bad = postcfg.problems()
        if bad:                                     # 不合格的用户配置：不列进来，提示写明哪个文件、哪一项
            self.post.setToolTip(T("这些后处理配置没列进来：") + "\n" + "\n".join(bad))
        self.post.setCurrentIndex(max(self.post.findData(job.Post), 0))
        f.addRow(T("数控系统"), self.post)
        self.kienzle = QtWidgets.QComboBox()
        for r in power.rows():
            self.kienzle.addItem(f"{r['key']} · {r['material_cn'] or r['material']}（ISO {r['iso_group'] or '—'}）", r["key"])
        self.kienzle.setCurrentIndex(max(self.kienzle.findData(job.Kienzle), 0))
        f.addRow(T("工件材料"), self.kienzle)
        self.library = QtWidgets.QComboBox()            # 示例库 + 用户刀具库（刀具库窗口建的）；也可以直接填别处的文件路径
        self.library.setEditable(True)
        from freecad_addon.gui import cam_library

        for name, path in cam_library.library_choices():
            self.library.addItem(name, path)
        i = self.library.findData(job.ToolLibrary)
        if i >= 0:
            self.library.setCurrentIndex(i)
        else:
            self.library.setEditText(job.ToolLibrary)
        self.library.setToolTip(T("刀具库：示例刀具库（虚构）或“刀具库…”窗口里建的；也可以填刀具库文件的路径"))
        f.addRow(T("刀具库"), self.library)
        self.fixture = QtWidgets.QLineEdit(job.Fixture)
        self.fixture.setPlaceholderText(T("卡爪：夹持长度, 外径 mm") if job.Kind == "turn" else T("平口钳：夹持高度 mm（空 = 不画钳口）"))
        f.addRow(T("夹具"), self.fixture)
        self.threads = QtWidgets.QPlainTextEdit()
        self.threads.setMaximumHeight(48)
        self.lengths = QtWidgets.QLineEdit()
        self.offset = QtWidgets.QDoubleSpinBox()
        if job.Kind == "turn":
            th = CO._js(job, "PartData", {}).get("threads") or []
            self.threads.setPlainText("\n".join(CO.thread_text(t) for t in th))
            self.threads.setPlaceholderText(T("每行：Z 起, Z 止, 大径, 螺距[, 内][, 1:16][, 2 头][, R | NPT]（起刀处要在端面或退刀槽）"))
            f.addRow(T("螺纹"), self.threads)
            self.parting = QtWidgets.QDoubleSpinBox()
            self.parting.setRange(0, 10)
            self.parting.setDecimals(1)
            self.parting.setValue(float((CO._js(job, "PartData", {}).get("parting") or {}).get("tool_w", 0.0)))
            self.parting.setToolTip(T("棒料上车完切下来：切断刀宽 mm；0 = 不切断（毛坯是单件料）"))
            f.addRow(T("切断刀宽 mm（0 = 不切断）"), self.parting)
            self.cycles = QtWidgets.QCheckBox(T("正式程序用固定循环（G71 / G70 / G76）"))
            self.cycles.setToolTip(T("FANUC、广数：粗精车、车螺纹写成循环，程序短；仿真按同样的展开规则走。西门子照样出直线段"))
            self.cycles.setChecked(bool(getattr(job, "Cycles", False)))
            f.addRow("", self.cycles)
        else:
            self.lengths.setText(", ".join(f"{k}={v:g}" for k, v in CO._js(job, "ToolLengths", {}).items()))
            self.lengths.setPlaceholderText(T("铣刀刀长：刀具 id=长度, …，如 EM10=120, DR8.5=140"))
            f.addRow(T("刀长 mm"), self.lengths)
            self.offset.setRange(-1000, 2000)
            self.offset.setValue(job.WorkOffsetZ)
            f.addRow(T("工件顶面离工作台 mm"), self.offset)
            self.stock_top = QtWidgets.QDoubleSpinBox()
            self.stock_top.setRange(0, 50)
            self.stock_top.setDecimals(2)
            self.stock_top.setValue(float(getattr(job, "StockTop", 0.0)))
            self.stock_top.setToolTip(T("毛坯顶面高出零件顶面多少；大于 0 时规则起草第一道是面铣"))
            f.addRow(T("面铣余量 mm（0 = 不面铣）"), self.stock_top)
        lay.addLayout(f)
        row = QtWidgets.QHBoxLayout()
        self.rule = QtWidgets.QPushButton(T("规则起草"))
        self.rule.clicked.connect(lambda: self.do_draft(False))
        self.ai = QtWidgets.QPushButton(T("AI 起草"))
        self.ai.clicked.connect(lambda: self.do_draft(True))
        self.calc = QtWidgets.QPushButton(T("计算并检查"))
        self.calc.clicked.connect(self.do_calculate)
        self.save = QtWidgets.QPushButton(T("保存程序与工艺卡…"))
        self.save.clicked.connect(self.save_dialog)
        self.replay = QtWidgets.QPushButton(T("回放…"))
        self.replay.setToolTip(T("按程序回放：刀具怎么走、在哪一行撞；程序窗口与刀路联动；算完看色差"))
        self.replay.clicked.connect(self.open_replay)
        self.diff = QtWidgets.QPushButton(T("程序对比…"))
        self.diff.setToolTip(T("两版程序差在哪：刀具、转速、进给、哪几行刀路不同、时间差（顺序号、注释、写法不同不算差别）"))
        self.diff.clicked.connect(self.compare_dialog)
        for b in (self.rule, self.ai, self.calc, self.replay, self.diff, self.save):
            row.addWidget(b)
        lay.addLayout(row)
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.checks = QtWidgets.QListWidget()
        self.checks.setMinimumHeight(160)
        lay.addWidget(self.checks)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.show_result()

    def apply(self):

        j = self.job
        j.Machine, j.Post, j.Kienzle = self.machine.currentData(), self.post.currentData(), self.kienzle.currentData()
        i = self.library.findText(self.library.currentText())
        j.ToolLibrary = self.library.itemData(i) if i >= 0 else self.library.currentText().strip()
        j.Fixture = self.fixture.text().strip()
        if j.Kind == "turn":
            d = CO._js(j, "PartData", {})
            d["threads"] = CO.parse_threads(self.threads.toPlainText())
            if self.parting.value() > 0:
                d["parting"] = {"tool_w": self.parting.value()}
            else:
                d.pop("parting", None)
            j.PartData = json.dumps(d, ensure_ascii=False)
            if not hasattr(j, "Cycles"):
                j.Proxy.setup(j)
            j.Cycles = self.cycles.isChecked()
        else:
            lengths = {}
            for piece in self.lengths.text().replace("，", ",").split(","):
                if "=" in piece:
                    k, v = piece.split("=", 1)
                    lengths[k.strip()] = float(v)
            j.ToolLengths = json.dumps(lengths)
            j.WorkOffsetZ = self.offset.value()
            if not hasattr(j, "StockTop"):           # Q3a 以前存的文档
                j.Proxy.setup(j)
            j.StockTop = self.stock_top.value()

    def do_draft(self, use_ai: bool):
        try:
            self.apply()
            client = None
            if use_ai:
                from freecad_addon.fc import fem_flow

                if self.job.Kind != "turn":
                    raise CO.CamObjError("铣削件的 AI 起草还没有（C1 先做车削件），请用规则起草")
                client = fem_flow.llm_client()
            self.draft_doc = CO.draft(self.job, client)
            n = sum(len(CO.ops(s)) for s in CO.setups(self.job))
            notes = self.draft_doc.get("notes") or []
            self.status.setText(T("起草了 {} 道工序（草稿）：在模型树里双击逐个确认").format(n)
                                + ("\n" + "\n".join(T(x) for x in notes) if notes else ""))
        except Exception as exc:  # noqa: BLE001 — 显示给用户
            self.status.setText(T(str(exc)))

    def do_calculate(self):
        try:
            self.apply()
            self.result = CO.calculate(self.job)
            self.job.Document.recompute()
            self.show_result()
            self.status.setText(T("算完；可以保存程序") if json.loads(self.job.Programs or "{}") else T("没有正式程序：看上面的检查项"))
        except Exception as exc:  # noqa: BLE001
            self.status.setText(T(str(exc)))

    def show_result(self):
        from PySide import QtGui, QtWidgets

        res = CO._js(self.job, "Result", {})
        self.summary.setText("\n".join(T(x) for x in res.get("summary") or []))
        self.checks.clear()
        for c in res.get("checks") or []:
            it = QtWidgets.QListWidgetItem(T(c["text"]))
            it.setForeground(QtGui.QColor(COLORS.get(c["level"], "#000000")))
            self.checks.addItem(it)
        self.save.setEnabled(bool(json.loads(self.job.Programs or "{}")))
        self.replay.setEnabled(bool(json.loads(getattr(self.job, "Replay", "") or "[]")))

    def open_replay(self):
        from freecad_addon.gui import cam_replay

        cam_replay.install_observer()
        return cam_replay.open_for(self.job)

    def save_to(self, folder, *, card: bool = True, lang: str = "zh"):
        from pathlib import Path

        from freecad_addon.core import cam_study as S

        progs = json.loads(self.job.Programs or "{}")
        if not progs:
            raise CO.CamObjError("没有可以保存的正式程序（工序还有草稿、整机仿真没通过，或没算）")
        out = Path(folder)
        out.mkdir(parents=True, exist_ok=True)
        files = []
        for name, text in progs.items():
            (out / name).write_text(text, encoding="utf-8")
            files.append(out / name)
        if card and self.result is not None:
            files += [f for f in S.save(self.result, out, draft_doc=CO.card_doc(self.job), lang=lang) if f.suffix != ".nc"]
        return files

    def compare_files(self, path_a, path_b) -> str:
        """两版程序（按本作业的机床读）→ 对比报告（Markdown，界面语言）"""
        from pathlib import Path

        from analysis.cam import machines, progdiff
        from assist import i18n

        self.apply()
        mach = machines.get(self.job.Machine)
        res = progdiff.compare(Path(path_a).read_text(encoding="utf-8"), Path(path_b).read_text(encoding="utf-8"), mach)
        self.diff_result = res
        return progdiff.report(res, "en" if i18n.lang() == "en" else "zh")

    def compare_dialog(self):
        from PySide import QtWidgets

        a, _ = QtWidgets.QFileDialog.getOpenFileName(self.form, T("旧版程序"), "", T("数控程序 (*.nc *.txt *.h *.mpf *.tap);;所有文件 (*)"))
        if not a:
            return None
        b, _ = QtWidgets.QFileDialog.getOpenFileName(self.form, T("新版程序"), "", T("数控程序 (*.nc *.txt *.h *.mpf *.tap);;所有文件 (*)"))
        if not b:
            return None
        try:
            text = self.compare_files(a, b)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(T("程序对比没做成：{}").format(T(str(exc))))
            return None
        return show_report(self.form, T("程序对比"), text)

    def save_dialog(self):
        from PySide import QtWidgets

        folder = QtWidgets.QFileDialog.getExistingDirectory(self.form, T("保存到哪个文件夹"))
        if not folder:
            return
        try:
            files = self.save_to(folder)
            self.status.setText(T("已保存 {} 个文件到 {}").format(len(files), folder))
        except Exception as exc:  # noqa: BLE001
            self.status.setText(T(str(exc)))

    def accept(self):
        try:
            self.apply()
        except Exception as exc:  # noqa: BLE001
            self.status.setText(T(str(exc)))
            return False
        self.job.Document.recompute()
        _close()
        return True

    def reject(self):
        _close()
        return True

    def getStandardButtons(self):
        from PySide import QtWidgets

        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


# ---------------------------------------------------------------- 工序
class OpPanel:
    def __init__(self, op):
        from PySide import QtWidgets


        self.op = op
        self.job = CO.job_of(op)
        self.lib = CO._lib(self.job)
        turn = self.job.Kind == "turn"
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(T("工序：{}").format(op.Label))
        lay = QtWidgets.QVBoxLayout(self.form)
        head = QtWidgets.QLabel(T("{}（{}）").format(T(op.Label), T(op.Status)))
        lay.addWidget(head)
        self.tabs = QtWidgets.QTabWidget()
        lay.addWidget(self.tabs)
        # 几何
        g = QtWidgets.QWidget()
        gl = QtWidgets.QVBoxLayout(g)
        self.geo = QtWidgets.QLabel("")
        self.geo.setWordWrap(True)
        gl.addWidget(self.geo)
        if not turn:
            row = QtWidgets.QHBoxLayout()
            self.pick = QtWidgets.QPushButton(T("用视图里选中的面"))
            self.pick.clicked.connect(self.use_selection)
            self.auto = QtWidgets.QPushButton(T("清空（自动找）"))
            self.auto.clicked.connect(self.clear_geometry)
            row.addWidget(self.pick)
            row.addWidget(self.auto)
            gl.addLayout(row)
        gl.addStretch(1)
        self.tabs.addTab(g, T("几何"))
        # 刀具
        t = QtWidgets.QWidget()
        tf = QtWidgets.QFormLayout(t)
        self.tool = QtWidgets.QComboBox()
        for x in self.lib["tools"]:
            if x["kind"] in TOOL_KINDS.get(op.OpKind, ()):
                self.tool.addItem(f"{x['id']} · {x.get('name', x['kind'])}", x["id"])
        self.tool.setCurrentIndex(max(self.tool.findData(op.ToolId), 0))
        self.tool.currentIndexChanged.connect(self.refresh)
        tf.addRow(T("刀具"), self.tool)
        self.tno = QtWidgets.QSpinBox()
        self.tno.setRange(1, 99)
        self.tno.setValue(op.ToolNumber)
        tf.addRow(T("刀号 T"), self.tno)
        self.tool_info = QtWidgets.QLabel("")
        self.tool_info.setWordWrap(True)
        tf.addRow("", self.tool_info)
        self.tabs.addTab(t, T("刀具"))
        # 切削参数
        c = QtWidgets.QWidget()
        cf = QtWidgets.QFormLayout(c)

        def spin(v, lo, hi, dec):
            s = QtWidgets.QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(dec)
            s.setValue(v)
            s.valueChanged.connect(self.refresh)
            return s
        self.vc = spin(op.Vc, 0, 2000, 1)
        cf.addRow(T("切削速度 vc m/min"), self.vc)
        self.feed = spin(op.Feed, 0, 50, 4)
        feed_label = T("每转进给 f mm/r") if (turn or op.OpKind == "drill") else T("每齿进给 fz mm")
        if op.OpKind != "thread":
            cf.addRow(feed_label, self.feed)
        self.ap = spin(op.Ap, 0, 100, 3)
        if op.OpKind in ("rough", "bore", "pocket", "profile"):
            cf.addRow(T("切深 ap mm") if turn else T("每层切深 mm"), self.ap)
        self.stepover = spin(op.StepOver, 0, 1, 3)
        if op.OpKind == "pocket":
            cf.addRow(T("行距（占刀径）"), self.stepover)
        self.range = QtWidgets.QLabel("")
        self.range.setWordWrap(True)
        cf.addRow("", self.range)
        self.tabs.addTab(c, T("切削参数"))
        # 余量与分层、高度与进退刀（0 = 缺省值）
        self.allow_r = spin(getattr(op, "AllowRadial", 0.0), 0, 10, 3)
        self.allow_z = spin(getattr(op, "AllowAxial", 0.0), 0, 10, 3)
        self.clear = spin(getattr(op, "Clearance", 0.0), 0, 100, 2)
        self.retract = spin(getattr(op, "Retract", 0.0), 0, 20, 2)
        if turn and op.OpKind in ("rough", "bore"):
            a = QtWidgets.QWidget()
            af = QtWidgets.QFormLayout(a)
            af.addRow(T("径向余量 mm（0 = 缺省）"), self.allow_r)
            if op.OpKind == "rough":
                af.addRow(T("轴向余量 mm（0 = 缺省）"), self.allow_z)
            af.addRow("", QtWidgets.QLabel(T("每层切深在“切削参数”页；精车按设计轮廓、不留余量")))
            self.tabs.addTab(a, T("余量与分层"))
        if turn and op.OpKind in ("rough", "finish", "groove", "bore"):
            h = QtWidgets.QWidget()
            hf = QtWidgets.QFormLayout(h)
            hf.addRow(T("安全距离 mm（0 = 缺省 2）"), self.clear)
            if op.OpKind in ("rough", "bore"):
                hf.addRow(T("退刀量 mm（0 = 缺省 0.5）"), self.retract)
            self.tabs.addTab(h, T("高度与进退刀"))
        if not turn and op.OpKind in CO.MILL_ALLOW_KINDS:      # 铣：侧壁 / 底面余量（ADR-0106 Q3b）
            a = QtWidgets.QWidget()
            af = QtWidgets.QFormLayout(a)
            af.addRow(T("侧壁余量 mm（0 = 不留）"), self.allow_r)
            af.addRow(T("底面余量 mm（0 = 不留）"), self.allow_z)
            af.addRow("", QtWidgets.QLabel(T("每层切深在“切削参数”页；留了余量要再加一道精铣")))
            self.tabs.addTab(a, T("余量与分层"))
        if not turn and op.OpKind in CO.MILL_FC_KINDS:
            h = QtWidgets.QWidget()
            hf = QtWidgets.QFormLayout(h)
            hf.addRow(T("安全高度：毛坯顶面以上 mm（0 = FreeCAD 缺省）"), self.clear)
            hf.addRow(T("快移高度：毛坯顶面以上 mm（0 = FreeCAD 缺省）"), self.retract)
            self.tabs.addTab(h, T("高度与进退刀"))
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QtWidgets.QHBoxLayout()
        self.apply_btn = QtWidgets.QPushButton(T("应用（重算刀路）"))
        self.apply_btn.clicked.connect(self.apply)
        row.addWidget(self.apply_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.refresh()

    def _geometry_text(self):
        op, job = self.op, self.job
        if job.Kind == "turn":
            d = CO._js(job, "PartData", {})
            k = op.OpKind
            if k in CO.FEATURE_KINDS:
                x = d.get({"groove": "grooves", "thread": "threads", "face_groove": "face_grooves"}[k])[op.FeatureIndex]
                return T("本工序：{}").format(", ".join(f"{a}={v:g}" for a, v in x.items() if isinstance(v, (int, float))))
            if k in ("drill", "bore"):
                return T("内孔：{}").format(", ".join(f"Ø{a:g}×{b:g}" for a, b in d.get("bore") or []))
            return T("外圆各段：{}").format(", ".join(f"Ø{a:g}×{b:g}" for a, b in d.get("segments") or []))
        subs = [s for (_o, ss) in op.Geometry for s in ss] if op.Geometry else []
        return T("选中的面：{}").format(", ".join(subs)) if subs else T("没有点选：自动找（型腔底面 / 直径相同的孔）")

    def refresh(self, *_):
        from analysis.cam import tools as TL
        from freecad_addon.core import cam_study as S

        self.geo.setText(self._geometry_text())
        tid = self.tool.currentData()
        if not tid:
            self.tool_info.setText(T("刀具库里没有这道工序能用的刀"))
            return
        t = TL.get(self.lib, tid)
        ins = t.get("insert") or {}
        bits = [f"Ø{t['diameter_mm']:g}" if "diameter_mm" in t else "", ins.get("iso", ""),
                f"r{ins['nose_radius_mm']:g}" if "nose_radius_mm" in ins else "",
                T("刃长 {}").format(f"{t['flute_length_mm']:g}") if "flute_length_mm" in t else ""]
        self.tool_info.setText(" · ".join(b for b in bits if b) + "\n" + T(t["source"]["ref"]))
        try:
            iso = S.iso_group(self.job.Kienzle)
        except S.StudyError as exc:
            self.range.setText(T(str(exc)))
            return
        turn = self.job.Kind == "turn"
        kw = {"vc": self.vc.value()}
        if self.op.OpKind != "thread":
            kw["f" if (turn or self.op.OpKind == "drill") else "fz"] = self.feed.value()
        if self.ap.value() > 0 and self.op.OpKind in ("rough", "bore", "pocket", "profile"):
            kw["ap"] = self.ap.value()
        res = TL.check_cutting(t, iso, **kw)
        lines = [f"<span style='color:{COLORS.get(r['level'], '#000')}'>{T(r['text'])}</span>" for r in res]
        self.range.setText("<br>".join(lines))
        self.ok = TL.verdict(res) != "error"

    def use_selection(self):
        sel = FreeCADGui.Selection.getSelectionEx()
        subs = [(s.Object, list(s.SubElementNames)) for s in sel if s.Object == self.job.Model and s.SubElementNames]
        if not subs:
            self.status.setText(T("先在视图里点选零件上的面"))
            return
        self.op.Geometry = subs
        self.refresh()

    def clear_geometry(self):
        self.op.Geometry = []
        self.refresh()

    def _write(self):
        op = self.op
        op.ToolId, op.ToolNumber = self.tool.currentData() or "", self.tno.value()
        op.Vc, op.Feed, op.Ap, op.StepOver = self.vc.value(), self.feed.value(), self.ap.value(), self.stepover.value()
        if not hasattr(op, "AllowRadial"):        # Q1、Q2 存的文档
            op.Proxy.setup(op)
        op.AllowRadial, op.AllowAxial = self.allow_r.value(), self.allow_z.value()
        op.Clearance, op.Retract = self.clear.value(), self.retract.value()
        if op.Status == "已确认":
            op.Status = "草稿"                      # 改了就要重新确认

    def apply(self):
        try:
            self._write()
            CO.regenerate(self.op)
            self.status.setText(T("刀路已重算"))
            return True
        except Exception as exc:  # noqa: BLE001
            self.status.setText(T(str(exc)))
            return False

    def accept(self):
        if not self.apply():
            return False
        try:
            CO.confirm(self.op)
        except CO.CamObjError as exc:
            self.status.setText(T(str(exc)))
            return False
        self.op.Document.recompute()
        _close()
        return True

    def reject(self):
        _close()
        return True

    def getStandardButtons(self):
        from PySide import QtWidgets

        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


# ---------------------------------------------------------------- 命令
def _selected(test):
    return [o for o in FreeCADGui.Selection.getSelection() if test(o)]


class NewJobCommand:
    def __init__(self, kind):
        self.kind = kind

    def GetResources(self):
        if self.kind == "turn":
            return {"MenuText": T("新建车削作业"), "ToolTip": T("选中回转体零件（轴线沿 Z），建作业：读出外圆、槽、内孔，建两次装夹")}
        return {"MenuText": T("新建铣削作业"), "ToolTip": T("选中零件，建作业：零件包围盒当毛坯，一次装夹")}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from PySide import QtWidgets

        sel = [o for o in FreeCADGui.Selection.getSelection() if hasattr(o, "Shape") and not CO.is_op(o)]
        if not sel:
            QtWidgets.QMessageBox.information(None, T("问渠CAM"), T("先在模型树或三维视图里选中一个零件"))
            return
        try:
            job = CO.new_job(FreeCAD.ActiveDocument, sel[0], self.kind)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(None, T("问渠CAM"), T(str(exc)))
            return
        edit(job)


class OpCommand:
    """对选中的工序：重算刀路 / 确认 / 上移 / 下移"""

    def __init__(self, action):
        self.action = action

    def GetResources(self):
        text = {"regen": ("重算刀路", "按工序现在的刀具和参数重算刀路"), "confirm": ("确认工序", "参数在刀具样本范围内就记为已确认"),
                "up": ("上移", "在本装夹里往前挪一道"), "down": ("下移", "在本装夹里往后挪一道")}[self.action]
        return {"MenuText": T(text[0]), "ToolTip": T(text[1])}

    def IsActive(self):
        return bool(_selected(CO.is_op))

    def Activated(self):
        from PySide import QtWidgets

        for op in _selected(CO.is_op):
            try:
                if self.action == "regen":
                    CO.regenerate(op)
                elif self.action == "confirm":
                    CO.confirm(op)
                else:
                    CO.move(op, -1 if self.action == "up" else 1)
            except Exception as exc:  # noqa: BLE001
                QtWidgets.QMessageBox.warning(None, T("问渠CAM"), T(str(exc)))
                return
        FreeCAD.ActiveDocument.recompute()


class JobActionCommand:
    def __init__(self, action):
        self.action = action

    def GetResources(self):
        text = {"edit": ("作业设置与计算…", "机床、数控系统、材料、夹具；起草、计算并检查、保存程序")}[self.action]
        return {"MenuText": T(text[0]), "ToolTip": T(text[1])}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and any(CO.is_job(o) for o in FreeCAD.ActiveDocument.Objects)

    def Activated(self):
        sel = _selected(CO.is_job)
        job = sel[0] if sel else next(o for o in FreeCAD.ActiveDocument.Objects if CO.is_job(o))
        edit(job)


def _target_setup():
    """新工序加到哪个装夹：选中的装夹 / 选中工序所在的装夹 / 选中（或唯一）作业的第一个装夹"""
    for o in FreeCADGui.Selection.getSelection():
        if CO.is_setup(o):
            return o
        if CO.is_op(o):
            return CO.setup_of(o)
        if CO.is_job(o):
            return CO.setups(o)[0]
    doc = FreeCAD.ActiveDocument
    jobs = [o for o in doc.Objects if CO.is_job(o)] if doc else []
    return CO.setups(jobs[-1])[0] if jobs else None


class AddOpCommand:
    def __init__(self, kind, turn):
        self.kind, self.turn = kind, turn

    def GetResources(self):
        name = (CO.TURN_KINDS if self.turn else CO.MILL_KINDS)[self.kind]
        return {"MenuText": T(name), "ToolTip": T("在选中的装夹里加一道工序（草稿）：刀和参数按规则定，改好后确认")}

    def IsActive(self):
        s = _target_setup()
        return s is not None and (CO.job_of(s).Kind == "turn") == self.turn

    def Activated(self):
        from PySide import QtWidgets

        s = _target_setup()
        try:
            op = CO.add_op(s, self.kind)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(None, T("问渠CAM"), T(str(exc)))
            return
        FreeCAD.ActiveDocument.recompute()
        edit(op)


class AddOpGroup:
    """工具栏上的“新建工序”下拉：车、铣各自的工序类型（只有当前作业那一类可用）"""

    def GetCommands(self):
        return tuple(ADD_OPS)

    def GetDefaultCommand(self):
        return 0

    def GetResources(self):
        return {"MenuText": T("新建工序"), "ToolTip": T("在选中的装夹里加一道工序")}

    def IsActive(self):
        return _target_setup() is not None


class OpEditCommand:
    """复制 / 隐藏或显示刀路"""

    def __init__(self, action):
        self.action = action

    def GetResources(self):
        text = {"copy": ("复制工序", "复制选中的工序，放在它后面（草稿）"),
                "hide": ("隐藏 / 显示刀路", "切换选中工序的刀路线框")}[self.action]
        return {"MenuText": T(text[0]), "ToolTip": T(text[1])}

    def IsActive(self):
        return bool(_selected(CO.is_op))

    def Activated(self):
        for op in _selected(CO.is_op):
            if self.action == "copy":
                CO.copy_op(op)
            else:
                op.ViewObject.Visibility = not op.ViewObject.Visibility
        FreeCAD.ActiveDocument.recompute()


def _replay_cmd():
    from freecad_addon.gui import cam_replay

    return cam_replay.ReplayCommand()


ADD_OPS = {**{f"FAP_CamAddTurn_{k}": AddOpCommand(k, True) for k in CO.TURN_KINDS},
           **{f"FAP_CamAddMill_{k}": AddOpCommand(k, False) for k in CO.MILL_KINDS}}

COMMANDS = {"FAP_CamNewTurnJob": NewJobCommand("turn"), "FAP_CamNewMillJob": NewJobCommand("mill"),
            "FAP_CamJob": JobActionCommand("edit"), "FAP_CamOpRegen": OpCommand("regen"), "FAP_CamOpConfirm": OpCommand("confirm"),
            "FAP_CamOpUp": OpCommand("up"), "FAP_CamOpDown": OpCommand("down"), "FAP_CamOpCopy": OpEditCommand("copy"),
            "FAP_CamOpHide": OpEditCommand("hide"), **ADD_OPS, "FAP_CamNewOp": AddOpGroup(), "FAP_CamReplay": _replay_cmd()}



def register():
    for name, cmd in COMMANDS.items():
        FreeCADGui.addCommand(name, cmd)


def show_report(parent, title, markdown):
    """Markdown 报告窗口：看、存成文件"""
    from PySide import QtWidgets

    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QtWidgets.QVBoxLayout(dlg)
    view = QtWidgets.QTextBrowser()
    view.setMarkdown(markdown)
    lay.addWidget(view)
    row = QtWidgets.QHBoxLayout()
    save = QtWidgets.QPushButton(T("存成文件…"))

    def do_save():
        path, _ = QtWidgets.QFileDialog.getSaveFileName(dlg, T("存成文件"), "program-diff.md", "Markdown (*.md)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(markdown)
    save.clicked.connect(do_save)
    close = QtWidgets.QPushButton(T("关闭"))
    close.clicked.connect(dlg.accept)
    row.addStretch(1)
    row.addWidget(save)
    row.addWidget(close)
    lay.addLayout(row)
    dlg.resize(760, 560)
    dlg.show()
    dlg.view = view
    return dlg
