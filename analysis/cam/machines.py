"""机床（ADR-0059）：示例机床（虚构，machines_example.yaml）+ 企业自己的机床（~/.freecad-ai-parts/machines.yaml 或 FAP_MACHINES）。"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

EXAMPLE = Path(__file__).resolve().parent / "machines_example.yaml"
NEED = {"lathe": ("max_rpm", "power_kw", "eff", "x", "z", "rapid", "home", "tool_change_s"),
        "mill": ("max_rpm", "power_kw", "eff", "x", "y", "z", "rapid", "tool_change_s")}


class MachineError(ValueError):
    pass


def user_file(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env["FAP_MACHINES"]) if env.get("FAP_MACHINES") else Path.home() / ".freecad-ai-parts" / "machines.yaml"


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for m in data.get("machines") or []:
        kind = m.get("kind")
        if kind not in NEED or not m.get("id") or not m.get("name"):
            raise MachineError(f"{path}：机床要有 id、name，kind 为 lathe 或 mill：{m}")
        miss = [k for k in NEED[kind] if k not in m]
        if miss:
            raise MachineError(f"{path}：机床 {m['id']} 缺 {', '.join(miss)}")
        out.append(dict(m))
    return out


def all_machines(env=None) -> list[dict]:
    """示例在前；企业的同 id 覆盖示例。"""
    by_id = {m["id"]: m for m in _read(EXAMPLE)}
    for m in _read(user_file(env)):
        by_id[m["id"]] = {**m, "example": False}
    return list(by_id.values())


def get(machine_id: str, env=None) -> dict:
    for m in all_machines(env):
        if m["id"] == machine_id:
            return m
    raise MachineError(f"没有机床 {machine_id!r}；可选：{', '.join(m['id'] for m in all_machines(env))}")
