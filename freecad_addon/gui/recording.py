"""工作台中的操作录制（ADR-0042，issue #146）：开始 / 停止、状态栏标记、停止时评价，对话面板事件写入录制。

录制器只有一个（本 FreeCAD 进程内）；会话包存到 FAP_SESSIONS_DIR，缺省 ~/.freecad-ai-parts/sessions/。
"""

from __future__ import annotations

import os
from pathlib import Path

from freecad_addon.core.session_log import DEFAULT_ROOT, SessionRecorder
from freecad_addon.gui.chat import Event, summarize

# 停止时记进结果的工具：最后一次的结论就是这次会话的方案与校验结论
OUTCOME_TOOLS = ("compose_chain", "verify_system", "export_system", "check_interference")

_recorder: SessionRecorder | None = None
_attachment = None
_indicator = None
_video = None  # (VideoRecorder, 文件名) 或 None
_video_note = ""


def recorder() -> SessionRecorder:
    global _recorder
    if _recorder is None:
        _recorder = SessionRecorder(Path(os.environ.get("FAP_SESSIONS_DIR") or DEFAULT_ROOT))
    return _recorder


def chat_event(e: Event) -> None:
    """对话面板的每个事件（在对话线程中调用，早于界面显示）：写入录制，并标出 AI 工具调用的时间段。"""
    rec = recorder()
    if not rec.active:
        return
    if e.kind == "tool_call":
        rec.chat("tool_call", name=e.name, data=e.data)
        rec.begin_ai()
    elif e.kind == "tool_result":
        rec.end_ai()
        brief = summarize(e.name or "", e.text, bool(e.data))
        rec.chat("tool_result", name=e.name, text=brief, is_error=bool(e.data))
        if e.name in OUTCOME_TOOLS and not e.data:
            rec.note_result(e.name, brief)
    elif e.kind in ("user", "assistant", "error"):
        rec.chat(e.kind, text=e.text)


def _meta() -> dict:
    import FreeCAD

    from freecad_addon.gui.panel import library_note

    return {"app": "freecad-ai-parts", "freecad_version": ".".join(FreeCAD.Version()[:3]),
            "library": library_note()}


def _show_indicator(on: bool) -> None:
    global _indicator
    import FreeCADGui
    from PySide import QtWidgets

    bar = FreeCADGui.getMainWindow().statusBar()
    if on and _indicator is None:
        _indicator = QtWidgets.QLabel("● 录制中")
        _indicator.setStyleSheet("color:#c00; font-weight:bold; padding:0 8px")
        bar.addPermanentWidget(_indicator)
    elif not on and _indicator is not None:
        bar.removeWidget(_indicator)
        _indicator.deleteLater()
        _indicator = None


def _window_region():
    import FreeCADGui

    from freecad_addon.core.video import Region

    mw = FreeCADGui.getMainWindow()
    g = mw.frameGeometry()
    ratio = mw.devicePixelRatioF() if hasattr(mw, "devicePixelRatioF") else 1.0
    return Region(round(g.x() * ratio), round(g.y() * ratio), round(g.width() * ratio), round(g.height() * ratio))


def _start_video(directory: Path) -> str:
    """开始录视频；返回说明（成功为空）。录不了时不影响其他内容的录制。"""
    global _video
    from freecad_addon.core.video import VideoRecorder, VideoUnavailable, command, find_ffmpeg

    out = directory / "video.mp4"
    try:
        video = VideoRecorder(command(find_ffmpeg(), _window_region(), out), out)
        video.start()
    except (VideoUnavailable, OSError) as exc:
        return str(exc)
    _video = (video, out.name)
    return ""


def start(video: bool = False) -> Path:
    """开始录制。video 为真时同时用 ffmpeg 录 FreeCAD 主窗口（ADR-0042，可选）。"""
    global _attachment, _video_note
    from freecad_addon.fc.session_observers import Attachment

    rec = recorder()
    path = rec.start({**_meta(), "video": video})
    _video_note = _start_video(path) if video else ""
    if _video_note:
        rec.event("note", what="video_unavailable", reason=_video_note)
    _attachment = Attachment(rec)
    _attachment.attach()
    _show_indicator(True)
    return path


def ask_rating() -> tuple[str | None, str]:
    """停止时请用户评价这次结果；可以不评。"""
    import FreeCADGui
    from PySide import QtWidgets

    mw = FreeCADGui.getMainWindow()
    box = QtWidgets.QMessageBox(mw)
    box.setWindowTitle("录制结束")
    box.setText("这次的结果怎样？（用于 AI 学习，可以不评）")
    buttons = {box.addButton(label, QtWidgets.QMessageBox.AcceptRole): value
               for label, value in (("采纳", "accepted"), ("修改后采纳", "modified"), ("未采纳", "rejected"))}
    skip = box.addButton("不评价", QtWidgets.QMessageBox.RejectRole)
    box.exec_() if hasattr(box, "exec_") else box.exec()
    rating = buttons.get(box.clickedButton())
    if rating is None or box.clickedButton() is skip:
        return None, ""
    note, ok = QtWidgets.QInputDialog.getText(mw, "录制结束", "补充说明（可留空）：")
    return rating, (note.strip() if ok else "")


def stop(rating: str | None = None, note: str = "") -> Path:
    global _attachment, _video, _video_note
    if _attachment is not None:
        _attachment.detach()
        _attachment = None
    extra: dict = {}
    if _video is not None:
        video, name = _video
        ok, err = video.stop()
        extra["video"] = name if ok else None
        if err or not ok:
            extra["video_error"] = err or "没有生成视频文件"
        _video = None
    elif _video_note:
        extra.update(video=None, video_error=_video_note)
    _video_note = ""
    _show_indicator(False)
    return recorder().stop(rating=rating, note=note, extra=extra)

