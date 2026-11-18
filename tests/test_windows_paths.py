"""仓库里的文件名在 Windows 上都能取出来（2026-11-17 问渠 CAD 安装时发现 aux.kicad_sch 让整库 git clone 失败，ADR-0099 41.0）。

Windows 不允许：保留设备名（CON、PRN、AUX、NUL、COM1–9、LPT1–9，不论扩展名）；< > : " | ? * 与控制字符；以空格或点结尾。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def problems(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        for part in p.split("/"):
            if part.split(".")[0].lower() in RESERVED:
                out.append(f"{p}：{part} 是 Windows 保留名")
            elif BAD_CHARS.search(part):
                out.append(f"{p}：{part} 含 Windows 不允许的字符")
            elif part.endswith((" ", ".")):
                out.append(f"{p}：{part} 以空格或点结尾")
    return out


def test_rules():
    assert problems(["a/aux.kicad_sch", "COM1.txt", "x/nul", "a:b", "dir./f"]) and len(problems(["a/aux.kicad_sch"])) == 1
    assert not problems(["factory/designs/drv-joint/kicad/aux-sheet.kicad_sch", "auxiliary.py", "conf.yaml", "docs/中文 名.md"])


def test_tracked_files_are_windows_safe():
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True, timeout=60).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("不是 git 仓库")
    paths = [p for p in out.decode("utf-8").split("\0") if p]
    bad = problems(paths)
    assert not bad, "这些文件名在 Windows 上取不出来：\n" + "\n".join(bad[:50])


def test_kicad_generator_avoids_reserved_names():
    import sys

    sys.path.insert(0, str(ROOT / "factory/designs/tools"))
    import sch

    assert sch.sheet_filename("aux") == "aux-sheet.kicad_sch" and sch.sheet_filename("power") == "power.kicad_sch"
