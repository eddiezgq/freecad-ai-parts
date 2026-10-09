"""机器指纹（ADR-0066 第 5 项）：系统机器编号、系统盘卷序列号、第一块网卡地址，各取所能取到的，做 SHA-256。

只用于单机授权；任何一项取不到就不算进来。换主板、重装系统、换网卡会改变指纹，按解绑流程重新签发。
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path


def _windows_parts() -> list[str]:
    parts = []
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
            parts.append("machine:" + winreg.QueryValueEx(k, "MachineGuid")[0])
    except OSError:
        pass
    try:
        out = subprocess.run(["cmd", "/c", "vol", os.environ.get("SystemDrive", "C:")], capture_output=True,
                             text=True, timeout=10, check=False).stdout
        m = re.search(r"([0-9A-F]{4}-[0-9A-F]{4})", out)
        if m:
            parts.append("volume:" + m.group(1))
    except (OSError, subprocess.SubprocessError):
        pass
    return parts


def _linux_parts() -> list[str]:
    parts = []
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            parts.append("machine:" + Path(p).read_text().strip())
            break
        except OSError:
            continue
    return parts


def components() -> list[str]:
    parts = _windows_parts() if sys.platform.startswith("win") else _linux_parts()
    mac = uuid.getnode()
    if not (mac >> 40) & 1:                       # 第 41 位为 1 表示是随机生成的，不算
        parts.append(f"mac:{mac:012x}")
    return sorted(parts)


def fingerprint(parts: list[str] | None = None) -> str:
    parts = components() if parts is None else sorted(parts)
    if not parts:
        raise RuntimeError("取不到这台电脑的任何标识，不能做单机授权")
    h = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:24].upper()
    return "-".join(h[i:i + 4] for i in range(0, 24, 4))


def activation_code(fp: str | None = None) -> str:
    """离线激活码：客户把它发给我们，我们按它签发单机授权。末尾 4 位校验，抄错能发现。"""
    fp = fp or fingerprint()
    check = hashlib.sha256(("FAP1" + fp).encode()).hexdigest()[:4].upper()
    return f"FAP1-{fp}-{check}"


def parse_activation(code: str) -> str:
    """激活码 → 机器指纹；格式或校验不对时抛 ValueError。"""
    parts = code.strip().upper().split("-")
    if len(parts) != 8 or parts[0] != "FAP1":
        raise ValueError("激活码格式不对（应为 FAP1- 开头、8 段）")
    fp = "-".join(parts[1:7])
    if activation_code(fp) != "-".join(parts):
        raise ValueError("激活码校验不对：可能抄错了")
    return fp
