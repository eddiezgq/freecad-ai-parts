"""校验窗口（ADR-0048 第 5 条）：场景每次改动（人或 AI）后组成系统并校验，逐项列出结论，并给接口标记与零件着色。

- 布局取自 place_component / connect_ports 的返回；需求取自 AI 调用 compose_chain / verify_system 时给出的，
  或用户在本窗口中填的
- 校验逻辑在 core/live_check.py（纯函数）；着色在 FreeCAD 主线程中进行
"""

from __future__ import annotations

import html

from PySide import QtCore, QtWidgets

from freecad_addon.core import live_check, requirement_form
from freecad_addon.gui.host import ToolsHost, get_host

REQ_FIELDS = requirement_form.FIELDS  # 与选型面板共用（ADR-0051）


class CheckPanel(QtWidgets.QDockWidget):
    changed = QtCore.Signal()  # 后台线程中布局或需求变化后，排队回到界面线程重新校验
    proposal_changed = QtCore.Signal()  # 有新提案或提案被结算后，排队回到界面线程更新提案框

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
        # AI 改动提案（ADR-0049 第 4 条）
        self.proposal_box = QtWidgets.QGroupBox("AI 改动提案")
        pl = QtWidgets.QVBoxLayout(self.proposal_box)
        self.proposal_text = QtWidgets.QLabel("")
        self.proposal_text.setWordWrap(True)
        self.accept_button = QtWidgets.QPushButton("接受")
        self.reject_button = QtWidgets.QPushButton("拒绝（恢复原状）")
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(self.accept_button)
        prow.addWidget(self.reject_button)
        pl.addWidget(self.proposal_text)
        pl.addLayout(prow)
        self.proposal_box.setVisible(False)
        self.proposal_note = ""
        lay.addWidget(self.proposal_box)
        lay.addLayout(form)
        lay.addWidget(self.req_note)
        lay.addLayout(row)
        lay.addWidget(self.overall)
        lay.addWidget(self.report, 1)
        from freecad_addon.gui.swap_box import SwapBox

        self.swap = SwapBox(self)  # 换件建议（ADR-0052）
        lay.addWidget(self.swap)
        self.setWidget(body)

        self.apply_button.clicked.connect(lambda *_: self.apply_form())
        self.clear_button.clicked.connect(lambda *_: self.set_requirement(None))
        self.changed.connect(self.recheck, QtCore.Qt.QueuedConnection)
        self.proposal_changed.connect(self._show_proposal, QtCore.Qt.QueuedConnection)
        self.accept_button.clicked.connect(lambda *_: self.host.settle("accepted"))
        self.reject_button.clicked.connect(lambda *_: self.reject())
        self.host.proposal_handlers.append(self._on_proposal)
        self.host.settle_handlers.append(self._on_settle)
        self.drag = None
        try:  # 拖动回写（ADR-0049 第 3 条）：在 FreeCAD 界面中才有
            import FreeCAD

            if FreeCAD.GuiUp:
                from freecad_addon.fc.drag_observer import DragWriter

                self.drag = DragWriter(self.host, lambda: self.layout_state)
        except ImportError:
            pass
        self.recheck()

    # ------------------------------------------------------------ 输入

    def _on_tool(self, name: str, info: dict) -> None:
        """工具调用成功后（调用线程中）：记下布局或 AI 给出的需求，排队重新校验。"""
        result, args = info.get("result") or {}, info.get("args") or {}
        if info.get("source") == "user" and "layout" in result and self.host.pending is not None:
            self.host.settle("accepted")  # 提案未处理时的手动改动视为接受
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
        req, err = requirement_form.from_texts({k: e.text() for k, e in self.inputs.items()})
        if err:
            self.req_note.setText(err)
            return False
        self.set_requirement(req)
        return True

    def set_requirement(self, req: dict | None) -> None:
        self.requirement = req
        self.recheck()

    def _show_requirement(self) -> None:
        req = self.requirement or {}
        for key, text in requirement_form.to_texts(req).items():
            if text and self.inputs[key].text().strip() == "":
                self.inputs[key].setText(text)
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
        self.swap.refresh_instances(self.layout_state, r)
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

    # ------------------------------------------------------------ 提案

    def _on_proposal(self, p: dict) -> None:
        self.proposal_changed.emit()

    def _on_settle(self, p: dict, decision: str) -> None:
        self.proposal_note = "已接受 AI 的改动" if decision == "accepted" else "已拒绝 AI 的改动，正在恢复原状"
        try:
            from freecad_addon.gui import recording

            rec = recording.recorder()
            if rec.active:
                rec.event("proposal", decision=decision, diff=p.get("diff"), request=p.get("request"))
        except ImportError:
            pass
        self.proposal_changed.emit()

    def _show_proposal(self) -> None:
        from freecad_addon.core import project

        p = self.host.pending
        if p is None:
            self.proposal_box.setVisible(bool(self.proposal_note))
            self.proposal_text.setText(self.proposal_note)
            self.accept_button.setVisible(False)
            self.reject_button.setVisible(False)
            return
        lines = project.describe(p["diff"])
        expl = p.get("explanation", "").strip()
        text = "<br>".join(html.escape(x) for x in lines)
        if expl:
            text += f"<br><span style='color:#555'>AI 说明：{html.escape(expl[:400])}</span>"
        text += "<br>结论见下方校验。接受才保留；拒绝就恢复到这一轮之前。"
        self.proposal_text.setText(text)
        self.accept_button.setVisible(True)
        self.reject_button.setVisible(True)
        self.proposal_box.setVisible(True)

    def reject(self, done=None) -> bool:
        """拒绝提案：清空场景，按这一轮之前的快照重建（后台线程），完成后调用 done(说明列表)。"""
        from freecad_addon.core import project

        p = self.host.settle("rejected")
        if p is None:
            return False
        calls, missing = project.rebuild_calls({"layout": p["before"]}, self.host.library().get)
        seq = project.clear_calls(self.host.layout) + calls

        def work() -> None:
            notes = list(missing)
            for name, args in seq:
                out = self.host.call(name, args, source="restore")
                if out.is_error:
                    notes.append(f"{name} {args.get('instance') or args.get('a')}：{'；'.join(out.texts)}")
            self.proposal_note = "已拒绝 AI 的改动，已恢复原状" + (f"（{'；'.join(notes)}）" if notes else "")
            self.proposal_changed.emit()
            if done:
                done(notes)

        import threading

        threading.Thread(target=work, name="fap-reject", daemon=True).start()
        return True

    def closeEvent(self, event) -> None:
        for lst, fn in ((self.host.proposal_handlers, self._on_proposal),
                        (self.host.settle_handlers, self._on_settle)):
            if fn in lst:
                lst.remove(fn)
        if self._on_tool in self.host.listeners:
            self.host.listeners.remove(self._on_tool)
        if self.drag is not None:
            self.drag.close()
            self.drag = None
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

