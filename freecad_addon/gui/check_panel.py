"""校验窗口（ADR-0048 第 5 条）：场景每次改动（人或 AI）后组成系统并校验，逐项列出结论，并给接口标记与零件着色。

- 布局取自 place_component / connect_ports 的返回；需求取自 AI 调用 compose_chain / verify_system 时给出的，
  或用户在本窗口中填的
- 校验逻辑在 core/live_check.py（纯函数）；着色在 FreeCAD 主线程中进行
"""

from __future__ import annotations

import html

from PySide import QtCore, QtWidgets

from freecad_addon.core import live_check
from freecad_addon.gui.host import ToolsHost, get_host

REQ_FIELDS = (("output_torque_cont_nm", "连续扭矩 N·m"), ("output_torque_peak_nm", "峰值扭矩 N·m"),
              ("output_speed_rpm", "输出转速 rpm"), ("ambient_temp_c", "环境温度 °C"),
              ("voltage_v", "供电电压 V"), ("phases", "相数"))


class CheckPanel(QtWidgets.QDockWidget):
    changed = QtCore.Signal()  # 后台线程中布局或需求变化后，排队回到界面线程重新校验

    def __init__(self, parent: QtWidgets.QWidget | None = None, host: ToolsHost | None = None):
        super().__init__("AI Parts 校验", parent)
        self.setObjectName("FapCheckPanel")
        self.host = host or get_host()
        self.layout_state: dict = {"instances": [], "connections": []}
        self.requirement: dict | None = None
        self.result: dict | None = None
        self.host.listeners.append(self._on_tool)

        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        form = QtWidgets.QFormLayout()
        self.inputs: dict[str, QtWidgets.QLineEdit] = {}
        for key, label in REQ_FIELDS:
            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText("可空")
            form.addRow(label, edit)
            self.inputs[key] = edit
        self.req_note = QtWidgets.QLabel("没有需求：只校验接口（C1、C2、C3、C10）。填连续扭矩与输出转速后点“按需求校验”。")
        self.req_note.setWordWrap(True)
        self.apply_button = QtWidgets.QPushButton("按需求校验")
        self.clear_button = QtWidgets.QPushButton("清除需求")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.apply_button)
        row.addWidget(self.clear_button)
        self.overall = QtWidgets.QLabel("")
        self.report = QtWidgets.QTextBrowser()
        lay.addLayout(form)
        lay.addWidget(self.req_note)
        lay.addLayout(row)
        lay.addWidget(self.overall)
        lay.addWidget(self.report, 1)
        self.setWidget(body)

        self.apply_button.clicked.connect(lambda *_: self.apply_form())
        self.clear_button.clicked.connect(lambda *_: self.set_requirement(None))
        self.changed.connect(self.recheck, QtCore.Qt.QueuedConnection)
        self.recheck()

    # ------------------------------------------------------------ 输入

    def _on_tool(self, name: str, info: dict) -> None:
        """工具调用成功后（调用线程中）：记下布局或 AI 给出的需求，排队重新校验。"""
        result, args = info.get("result") or {}, info.get("args") or {}
        hit = False
        if isinstance(result.get("layout"), dict):
            self.layout_state = result["layout"]
            hit = True
        req = args.get("requirement") if name == "compose_chain" else (
            (args.get("system") or {}).get("requirement") if name in ("verify_system", "export_system") else None)
        if isinstance(req, dict):
            self.requirement = dict(req)
            hit = True
        if hit:
            self.changed.emit()

    def apply_form(self) -> bool:
        vals = {}
        for key, edit in self.inputs.items():
            text = edit.text().strip()
            if text:
                try:
                    vals[key] = float(text)
                except ValueError:
                    self.req_note.setText(f"{key} 须为数字")
                    return False
        if "output_torque_cont_nm" not in vals or "output_speed_rpm" not in vals:
            self.req_note.setText("按需求校验至少要填连续扭矩和输出转速")
            return False
        req = {k: v for k, v in vals.items() if k not in ("voltage_v", "phases")}
        if "voltage_v" in vals:
            req["supply"] = {"current_type": "ac", "voltage_v": vals["voltage_v"],
                             "phases": int(vals.get("phases", 3))}
        self.set_requirement(req)
        return True

    def set_requirement(self, req: dict | None) -> None:
        self.requirement = req
        self.recheck()

    def _show_requirement(self) -> None:
        req = self.requirement or {}
        flat = {**req, **{k: v for k, v in (req.get("supply") or {}).items() if k in ("voltage_v", "phases")}}
        for key, edit in self.inputs.items():
            if key in flat and edit.text().strip() == "":
                edit.setText(f"{flat[key]:g}" if isinstance(flat[key], (int, float)) else str(flat[key]))
        self.req_note.setText("按需求校验全部 11 项" if req else
                              "没有需求：只校验接口（C1、C2、C3、C10）。填连续扭矩与输出转速后点“按需求校验”。")

    # ------------------------------------------------------------ 校验与显示

    def recheck(self) -> dict:
        self._show_requirement()
        try:
            self.result = live_check.check(self.layout_state, self.host.library().get, self.requirement)
        except Exception as exc:  # noqa: BLE001 — 数据不全时如实显示，不中断界面
            self.result = {"mode": "error", "overall": "unknown", "checks": [], "notes": [f"无法校验：{exc}"],
                           "ports": {}, "instances": {}}
        r = self.result
        self.overall.setText(f"<b>结论：{live_check.STATUS_TEXT.get(r['overall'], r['overall'])}</b>"
                             if r["mode"] != "empty" else "场景中还没有零件")
        self.report.setHtml(render(r))
        colorize(r)
        self.save_record()
        return r

    def save_record(self) -> bool:
        """把方案写进布局文档的 FapProject（ADR-0049 第 2 条）；场景为空且文档中没有记录时不写。"""
        try:
            import FreeCAD

            from freecad_addon.core import project
            from freecad_addon.fc import project_doc
            from freecad_addon.fc.snapshot import _target
        except ImportError:
            return False
        if _target["name"] not in FreeCAD.listDocuments():
            return False
        doc = FreeCAD.getDocument(_target["name"])
        if not self.layout_state.get("instances") and project_doc.read(doc) is None:
            return False
        import datetime

        rec = project.record(self.layout_state, self.requirement, self.result, self.host.library().get,
                             self.host.note, datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
        project_doc.write(doc, project.dumps(rec))
        return True

    def restore(self, done=None) -> str | None:
        """从当前活动文档的方案记录恢复场景：清空场景，按记录依次放置、连接（与 AI 用同一工具）。
        返回错误说明；开始恢复时返回 None，完成后调用 done(说明列表)。"""
        import FreeCAD

        from freecad_addon.core import project
        from freecad_addon.fc import project_doc, snapshot

        doc = FreeCAD.ActiveDocument
        text = project_doc.read(doc) if doc is not None else None
        if not text:
            return "当前文档中没有 AI Parts 方案记录"
        try:
            rec = project.loads(text)
        except project.ProjectError as exc:
            return str(exc)
        calls, missing = project.rebuild_calls(rec, self.host.library().get)
        snapshot.set_target(doc.Name)
        seq = project.clear_calls(self.layout_state) + calls
        self.requirement = rec.get("requirement")

        def work() -> None:
            notes = list(missing)
            for name, args in seq:
                out = self.host.call(name, args)
                if out.is_error:
                    notes.append(f"{name} {args.get('instance') or args.get('a')}：{'；'.join(out.texts)}")
            if done:
                done(notes)
            self.changed.emit()

        import threading

        threading.Thread(target=work, name="fap-restore", daemon=True).start()
        return None

    def closeEvent(self, event) -> None:
        if self._on_tool in self.host.listeners:
            self.host.listeners.remove(self._on_tool)
        super().closeEvent(event)


def render(r: dict) -> str:
    esc = html.escape
    color = {"pass": "#2a2", "warn": "#c90", "unknown": "#b90", "fail": "#c22", "not_applicable": "#888"}
    parts = [f"<p style='color:#666'>{esc(n)}</p>" for n in r.get("notes", [])]
    for c in r.get("checks", []):
        st = c["status"]
        name = live_check.CHECK_NAMES.get(c["check"], "")
        parts.append(f"<p><b style='color:{color.get(st, '#000')}'>{esc(c['check'])} {esc(name)}："
                     f"{esc(live_check.STATUS_TEXT.get(st, st))}</b><br>")
        finds = c.get("findings") or []
        if finds:
            parts.append("<br>".join(f"&nbsp;&nbsp;· {esc(f['message'])}" for f in finds))
        else:
            parts.append(f"&nbsp;&nbsp;{esc(c.get('message', ''))}")
        parts.append("</p>")
    return "".join(parts)


def colorize(r: dict) -> None:
    """给 FapLayout 中的接口标记按端口结论着色，零件的边线按实例结论着色；没有文档时什么也不做。"""
    try:
        import FreeCAD
        import FreeCADGui
    except ImportError:
        return
    from freecad_addon.core.port_markers import TYPE_COLORS
    from freecad_addon.fc.snapshot import _target

    name = _target["name"]
    if name not in FreeCAD.listDocuments() or not FreeCAD.GuiUp:
        return
    doc, gdoc = FreeCAD.getDocument(name), FreeCADGui.getDocument(name)
    for obj in doc.Objects:
        vo = gdoc.getObject(obj.Name)
        if vo is None:
            continue
        if getattr(obj, "FapPort", None):
            st = r["ports"].get(f"{obj.FapInstance}.{obj.FapPort}")
            vo.ShapeColor = live_check.STATUS_COLORS.get(st, TYPE_COLORS.get(obj.FapPortType, (0.7, 0.7, 0.7)))
        elif getattr(obj, "FapComponent", None):
            st = r["instances"].get(obj.FapInstance)
            vo.LineColor = live_check.STATUS_COLORS.get(st, (0.1, 0.1, 0.1))
            vo.LineWidth = 3.0 if st in live_check.STATUS_COLORS else 1.0


class PortConnector(QtCore.QObject):
    """“连接接口”：选中的两个接口标记 → connect_ports（与 AI 走同一工具）；第一个选中的为基准，不动。"""

    finished = QtCore.Signal(object)

    def __init__(self, host: ToolsHost | None = None):
        super().__init__()
        self.host = host or get_host()
        self.finished.connect(self._report, QtCore.Qt.QueuedConnection)
        self.last: str = ""

    @staticmethod
    def selected_refs() -> list[str]:
        import FreeCADGui

        return [f"{o.FapInstance}.{o.FapPort}" for o in FreeCADGui.Selection.getSelection()
                if getattr(o, "FapPort", None)]

    def connect_selected(self, refs: list[str] | None = None) -> bool:
        refs = self.selected_refs() if refs is None else refs
        if len(refs) != 2:
            self._report(ValueError("请在 3D 视图中按住 Ctrl 选两个接口标记（先选的不动），再点“连接接口”"))
            return False
        a, b = refs
        self.host.call_in_background("connect_ports", {"a": a, "b": b}, lambda out: self.finished.emit((a, b, out)))
        return True

    def _report(self, item) -> None:
        import FreeCAD

        if isinstance(item, Exception):
            self.last = str(item)
        else:
            a, b, out = item
            if isinstance(out, Exception) or out.is_error:
                text = str(out) if isinstance(out, Exception) else "；".join(out.texts)
                self.last = f"没有连接 {a} ↔ {b}：{text}"
            else:
                self.last = f"已连接 {a} ↔ {b}"
        FreeCAD.Console.PrintMessage(f"AI Parts：{self.last}\n")

