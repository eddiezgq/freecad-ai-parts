"""演示驱动（M5 #105）：在 FreeCAD 界面中打开 AI 对话面板，输入示例需求，跑完一轮对话后退出；供录屏使用。

由 scripts/record_demo.sh 在 FreeCAD 内带的 Python 中运行（需要显示环境）：
    python -m freecad_addon.gui.demo_driver [--live] [--statement "…"] [--hold 5]

- 缺省为回放：LLM 的回复按 SCRIPT 预先写好，工具调用、校验与 FreeCAD 布局都是真实执行的；面板顶部注明“回放”
- --live：真实调用 LLM（需要 ANTHROPIC_API_KEY），用于录制正式演示视频
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATEMENT = ("六轴机械臂第 2 关节：输出连续扭矩 25 N·m、峰值 50 N·m，输出转速 30 rpm，220 V 单相供电，EtherCAT 总线。"
             "请选型，并在 FreeCAD 里布局、消除干涉。")


def _use(i: int, name: str, args: dict) -> dict:
    return {"type": "tool_use", "id": f"demo{i}", "name": name, "input": args}


def _say(text: str, *uses: dict, stop: str = "tool_use") -> dict:
    return {"stop_reason": stop, "content": [{"type": "text", "text": text}, *uses]}


def scripted_responses() -> list[dict]:
    """回放用的 LLM 回复：与 joint_selection、joint_layout 提示的流程一致，系统取自 examples/joint2。"""
    req = json.loads((ROOT / "examples" / "joint2-requirement.json").read_text(encoding="utf-8"))
    system = {k: v for k, v in json.loads((ROOT / "examples" / "joint2" / "system.json").read_text(encoding="utf-8"))
              ["system"].items() if k != "layout"}
    comps = system["components"]
    mech = [("motor.mount_flange", "plate.motor_side"), ("plate.reducer_side", "reducer.motor_flange"),
            ("motor.shaft", "sleeve.inner"), ("sleeve.outer", "reducer.input_bore")]
    n = iter(range(1, 100))
    return [
        _say("我把需求整理为：连续 25 N·m、峰值 50 N·m、30 rpm、220 V 单相、EtherCAT，安全系数按默认 1.2。先求候选方案。",
             _use(next(n), "compose_chain", {"requirement": req, "top_n": 3})),
        _say("排第一的方案全部校验通过：200 W 电机经轴套与转接板接 r25 减速器，配 d200 驱动器。开始在 FreeCAD 里摆放。",
             *[_use(next(n), "place_component", {"instance": c["instance"], "component_id": c["component"]})
               for c in comps]),
        _say("按端口配合：先法兰，再轴与孔。",
             *[_use(next(n), "connect_ports", {"a": a, "b": b}) for a, b in mech]),
        _say("检查干涉。", _use(next(n), "check_interference", {})),
        _say("驱动器与其他零件重叠（它不在传动链上）。按包围盒把它沿 x 移到 90 mm，留 20 mm 间隙。",
             _use(next(n), "place_component", {"instance": "drive", "position_mm": [90, 0, 0]}),
             _use(next(n), "check_interference", {})),
        _say("没有干涉了。截图自查。", _use(next(n), "snapshot", {"view": "iso", "width": 480, "height": 360})),
        _say("最后按布局复核。", _use(next(n), "verify_system", {"system": system, "use_layout": True})),
        _say("完成：方案可用，布局无干涉。请核对转接板中间有供电机轴穿过的孔；轴套的插入深度数据缺失，"
             "按轴端对齐放置。需要的话可以导出 BOM 与 URDF。", stop="end_turn"),
    ]


class _PacedLLM:
    """回放时每步停顿，便于观看。"""

    def __init__(self, responses: list[dict], pause_s: float):
        from freecad_addon.gui.chat import ScriptedLLM

        self._inner = ScriptedLLM(responses)
        self.pause_s = pause_s

    def create(self, **kw):
        time.sleep(self.pause_s)
        return self._inner.create(**kw)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="FreeCAD 对话面板演示驱动（录屏用）")
    p.add_argument("--live", action="store_true", help="真实调用 LLM（需要 ANTHROPIC_API_KEY）")
    p.add_argument("--statement", default=STATEMENT)
    p.add_argument("--pause", type=float, default=1.5, help="回放时每步停顿秒数")
    p.add_argument("--hold", type=float, default=5.0, help="结束后停留秒数")
    p.add_argument("--timeout", type=float, default=600.0)
    args = p.parse_args(argv)

    import FreeCAD  # noqa: F401  须先于 FreeCADGui 等模块导入
    import FreeCADGui

    FreeCADGui.showMainWindow()
    from PySide import QtCore, QtWidgets

    app = QtWidgets.QApplication.instance()
    mw = FreeCADGui.getMainWindow()
    mw.showMaximized()

    from freecad_addon.gui.chat import AnthropicChat
    from freecad_addon.gui.panel import ChatPanel
    from freecad_addon.gui.workbench import register

    register()
    FreeCADGui.activateWorkbench("AiPartsWorkbench")
    factory = AnthropicChat if args.live else (lambda: _PacedLLM(scripted_responses(), args.pause))
    panel = ChatPanel(llm_factory=factory, parent=mw)
    if not args.live:
        panel.header.setText(panel.header.text() + "｜回放：LLM 回复为预先写好的脚本，工具调用与布局真实执行")
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, panel)
    mw.resizeDocks([panel], [620], QtCore.Qt.Horizontal)

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    pump(2)
    for ch in args.statement:  # 逐字输入，便于观看
        panel.input.insertPlainText(ch)
        pump(0.03)
    pump(0.5)
    if not panel.send():
        pump(args.hold)
        return 1
    start = time.time()
    while panel.busy and time.time() - start < args.timeout:  # 布局由面板的同步实时显示（等轴测）
        pump(0.1)
    pump(args.hold)
    ok = not panel.busy
    panel.close()
    return 0 if ok else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    import os

    os._exit(code)  # FreeCAD 的 Qt 退出流程较慢，录屏结束后直接退出
