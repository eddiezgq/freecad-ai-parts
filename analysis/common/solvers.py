"""本机求解器查找与子进程（ADR-0056 第 2 条）。不联网。

CalculiX（ccx）的查找顺序：环境变量 FAP_CCX → FreeCAD FEM 设置里的 ccx 路径 → 与当前 Python 同目录（FreeCAD 自带，
Windows 为 bin/ccx.exe）→ PATH。
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


class SolverError(RuntimeError):
    """求解器不可用或计算失败；消息说明原因。"""


def missing_python(modules: list[str]) -> list[str]:
    """缺少的 Python 包。"""
    return [m for m in modules if importlib.util.find_spec(m) is None]


def _freecad_ccx() -> str | None:
    try:
        import FreeCAD

        prefs = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx")
        path = prefs.GetString("ccxBinaryPath", "")
        return path or None
    except Exception:  # noqa: BLE001 — 不在 FreeCAD 中
        return None


def find_ccx() -> str | None:
    exe = "ccx.exe" if os.name == "nt" else "ccx"
    for cand in (os.environ.get("FAP_CCX"), _freecad_ccx(), str(Path(sys.executable).parent / exe), shutil.which("ccx")):
        if cand and Path(cand).is_file():
            return str(cand)
    return None


def ccx_version(ccx: str) -> str | None:
    try:
        out = subprocess.run([ccx, "-v"], capture_output=True, text=True, timeout=20, input="", check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"Version\s+([0-9.]+)", out)
    return m.group(1) if m else None


def run(cmd: list[str], cwd: str | Path, timeout_s: float) -> subprocess.CompletedProcess:
    """运行求解器；超时或返回码非 0 时抛 SolverError（附输出末尾）。"""
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        raise SolverError(f"{Path(cmd[0]).name} 超过 {timeout_s:g} 秒未算完") from exc
    except OSError as exc:
        raise SolverError(f"不能启动 {cmd[0]}：{exc}") from exc
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr)[-800:]
        raise SolverError(f"{Path(cmd[0]).name} 返回 {proc.returncode}：{tail}")
    return proc
