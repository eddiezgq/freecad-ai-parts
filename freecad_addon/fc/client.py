"""FreeCAD worker 客户端（ADR-0032）：在 MCP 服务端进程中运行，不导入 FreeCAD。

headless 后端用 FreeCAD 内带的 Python 启动 `python -m freecad_addon.fc.worker` 子进程，按 JSON 行协议通信。
配置（环境变量）：
- FAP_FREECAD_PYTHON：FreeCAD 内带 Python 的路径；缺省为本仓库 .freecad/squashfs-root/usr/bin/python
  （scripts/fetch_freecad.sh 的解包位置）
- FAP_FREECAD_LIB：FreeCAD 模块目录；缺省按安装布局推断（AppImage 为 usr/lib，Windows 安装包为 bin）
Linux 下没有 DISPLAY 时，若有 xvfb-run 则在 Xvfb 下启动，以便截图。
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

PREFIX = "@@FAP@@ "
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PYTHON = REPO_ROOT / ".freecad/squashfs-root/usr/bin/python"


class WorkerError(RuntimeError):
    """worker 不可用或执行失败。kind：unavailable / input / snapshot / internal / timeout。"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _module_dir(python: Path) -> Path | None:
    for cand in (python.parent.parent / "lib", python.parent):
        if any((cand / n).exists() for n in ("FreeCAD.so", "FreeCAD.pyd")):
            return cand
    return None


def worker_command() -> tuple[list[str], dict]:
    """启动 worker 的命令与环境；找不到 FreeCAD 时抛出 WorkerError("unavailable")。"""
    python = Path(os.environ.get("FAP_FREECAD_PYTHON") or DEFAULT_PYTHON)
    if not python.exists():
        raise WorkerError("unavailable", f"找不到 FreeCAD 内带的 Python：{python}。请运行 scripts/fetch_freecad.sh，"
                                         "或设置 FAP_FREECAD_PYTHON")
    lib = Path(os.environ["FAP_FREECAD_LIB"]) if os.environ.get("FAP_FREECAD_LIB") else _module_dir(python)
    if lib is None or not lib.exists():
        raise WorkerError("unavailable", f"找不到 FreeCAD 模块目录（{python} 旁）；请设置 FAP_FREECAD_LIB")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(lib), str(REPO_ROOT)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("LANG", "C.UTF-8")
    cmd = [str(python), "-m", "freecad_addon.fc.worker"]
    if sys.platform.startswith("linux") and not env.get("DISPLAY") and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1280x1024x24", *cmd]
    return cmd, env


class HeadlessWorker:
    """按需启动的 FreeCAD 子进程；一次一个请求（调用方负责串行）。"""

    def __init__(self, timeout_s: float = 120.0):
        self.timeout_s = timeout_s
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()
        self._next_id = 0
        self._lock = threading.Lock()

    def _start(self) -> None:
        cmd, env = worker_command()
        self._proc = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
        threading.Thread(target=self._pump, args=(self._proc,), daemon=True).start()

    def _pump(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            if line.startswith(PREFIX):
                self._lines.put(line[len(PREFIX):])
        self._lines.put(None)  # 进程结束

    def call(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._lines = queue.Queue()
                self._start()
            self._next_id += 1
            rid = self._next_id
            try:
                self._proc.stdin.write(json.dumps({"id": rid, "method": method, "params": params or {}},  # type: ignore[union-attr]
                                                  ensure_ascii=False) + "\n")
                self._proc.stdin.flush()  # type: ignore[union-attr]
            except (BrokenPipeError, OSError) as exc:
                self.close()
                raise WorkerError("unavailable", f"FreeCAD worker 已退出：{exc}") from exc
            while True:
                try:
                    line = self._lines.get(timeout=self.timeout_s)
                except queue.Empty:
                    self.close()
                    raise WorkerError("timeout", f"FreeCAD worker {self.timeout_s:.0f} 秒内未响应，已终止") from None
                if line is None:
                    self.close()
                    raise WorkerError("unavailable", "FreeCAD worker 意外退出")
                resp = json.loads(line)
                if resp.get("id") != rid:
                    continue
                if "error" in resp:
                    err = resp["error"]
                    raise WorkerError(err.get("kind", "internal"), err.get("message", "未知错误"))
                return resp["result"]

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.stdin.write(json.dumps({"id": 0, "method": "shutdown"}) + "\n")  # type: ignore[union-attr]
                proc.stdin.flush()  # type: ignore[union-attr]
                proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait()
