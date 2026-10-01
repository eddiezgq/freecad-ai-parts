"""FreeCAD worker（ADR-0032）：在 FreeCAD 中运行，按 JSON 行协议处理请求。

启动：用 FreeCAD 内带的 Python 运行 `python -m freecad_addon.fc.worker`，PYTHONPATH 含 FreeCAD 模块目录与本仓库
（由 freecad_addon.fc.client 负责；freecadcmd 运行脚本时会占用标准输入，不能用）。headless 截图需在 Xvfb 下。
请求一行一个 JSON：{"id": 1, "method": "ping" | "interference" | "snapshot", "params": {...}}
回复一行一个 JSON，前缀 PREFIX：FreeCAD 会向标准输出打印启动信息，客户端只认带前缀的行。
"""

from __future__ import annotations

import json
import sys
import traceback

PREFIX = "@@FAP@@ "

def handle(req: dict) -> dict:
    import FreeCAD  # 须先于 Part 等模块导入

    from freecad_addon.core.geometry import LayoutError
    from freecad_addon.core.scene import Scene

    rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
    try:
        if method == "ping":
            return {"id": rid, "result": {"freecad": ".".join(FreeCAD.Version()[:3])}}
        if method == "interference":
            from freecad_addon.fc.interference import DEFAULT_THRESHOLD_MM3, check

            scene = Scene.from_dict(params["scene"])
            return {"id": rid, "result": check(scene, float(params.get("threshold_mm3", DEFAULT_THRESHOLD_MM3)))}
        if method == "snapshot":
            from freecad_addon.fc.snapshot import snapshot

            scene = Scene.from_dict(params["scene"])
            return {"id": rid, "result": snapshot(scene, params.get("view", "iso"), int(params.get("width", 800)),
                                                  int(params.get("height", 600)))}
        return {"id": rid, "error": {"kind": "input", "message": f"未知方法 {method}"}}
    except (LayoutError, KeyError, ValueError, TypeError) as exc:
        return {"id": rid, "error": {"kind": "input", "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001 — worker 不能因单个请求崩溃
        kind = "snapshot" if type(exc).__name__ == "SnapshotError" else "internal"
        return {"id": rid, "error": {"kind": kind, "message": str(exc), "trace": traceback.format_exc(limit=5)}}


def main() -> None:
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            resp = {"id": None, "error": {"kind": "input", "message": f"请求不是合法 JSON：{exc}"}}
        else:
            if req.get("method") == "shutdown":
                out.write(PREFIX + json.dumps({"id": req.get("id"), "result": "bye"}) + "\n")
                out.flush()
                break
            resp = handle(req)
        out.write(PREFIX + json.dumps(resp, ensure_ascii=False) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
