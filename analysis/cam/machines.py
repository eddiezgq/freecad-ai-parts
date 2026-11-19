"""机床（ADR-0059、ADR-0105）：示例机床（虚构，analysis/cam/machines/*.json）+ 企业自己的机床。

企业的机床放在 ~/.freecad-ai-parts/machines.yaml（或环境变量 FAP_MACHINES 指定的文件或文件夹）：
- 文件夹：里面每个 *.json 是一台 cam-machine/1 机床；
- machines.yaml：`machines:` 列表，每项可以是旧格式（ADR-0059：kind、max_rpm、power_kw、eff、x/y/z、rapid、home、tool_change_s），
  也可以是写了 `format: cam-machine/1` 的新格式。旧格式照常能用（读进来自动转换），企业已填的文件不作废。
同 id 时企业的覆盖示例。

- `models(env)`：全部机床的 cam-machine/1 模型（含五轴、车铣中心）；`model(id, env)` 取一台。
- `all_machines(env)` / `get(id, env)`：给现有车削、2.5 轴铣、程序检查用的旧字段视图，只列两轴车床、三轴加工中心。
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from analysis.cam import machine_model as MM
from analysis.cam.machine_model import MachineError

__all__ = ["EXAMPLE", "MachineError", "all_machines", "copy_model", "get", "model", "models", "save_model", "user_dir", "user_file"]

EXAMPLE = Path(__file__).resolve().parent / "machines"
NEED = {"lathe": ("max_rpm", "power_kw", "eff", "x", "z", "rapid", "home", "tool_change_s"),
        "mill": ("max_rpm", "power_kw", "eff", "x", "y", "z", "rapid", "tool_change_s")}
# 旧视图里这几项必须有（仿真和时间要用）；功率、效率缺了只让功率检查报“未知”
VIEW_NEED = {"lathe": ("x", "z", "rapid", "home", "tool_change_s"), "mill": ("x", "y", "z", "rapid", "tool_change_s")}


def user_file(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env["FAP_MACHINES"]) if env.get("FAP_MACHINES") else Path.home() / ".freecad-ai-parts" / "machines.yaml"


def user_dir(env=None) -> Path:
    """用户机床文件夹（每台一个 cam-machine/1 JSON；机床窗口存在这里，ADR-0106 Q4a）：~/.freecad-ai-parts/machines/，
    环境变量 FAP_MACHINES_DIR 可改"""
    env = os.environ if env is None else env
    return Path(env["FAP_MACHINES_DIR"]) if env.get("FAP_MACHINES_DIR") else Path.home() / ".freecad-ai-parts" / "machines"


def copy_model(machine_id: str, new_id: str, name: str, env=None) -> dict:
    """复制一台机床（示例或已有的）做成自己的：改 id、名称，去掉“示例”标记，来源写“由 X 复制，待按实机改”"""
    import copy as _copy

    m = _copy.deepcopy(model(machine_id, env))
    m.pop("_dir", None)
    m.update({"id": new_id, "name": name, "example": False, "source": f"由 {machine_id} 复制，参数待按实机改"})
    return m


def save_model(m: dict, env=None) -> Path:
    """核对后存到用户机床文件夹（不合格不存，MachineError 写明哪一项）"""
    import json

    m = {k: v for k, v in m.items() if k != "_dir"}
    MM.check(m, m.get("id", ""))
    for a in m.get("axes") or []:
        if "min" in a and "max" in a and a["min"] >= a["max"]:
            raise MachineError(f"{a['id']} 轴行程下限 {a['min']:g} 不小于上限 {a['max']:g}")
    d = user_dir(env)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{m['id']}.json"
    p.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p


def _legacy_entry(path: Path, m: dict) -> dict:
    kind = m.get("kind")
    if kind not in NEED or not m.get("id") or not m.get("name"):
        raise MachineError(f"{path}：机床要有 id、name，kind 为 lathe 或 mill：{m}")
    miss = [k for k in NEED[kind] if k not in m]
    if miss:
        raise MachineError(f"{path}：机床 {m['id']} 缺 {', '.join(miss)}")
    return MM.check(MM.from_legacy(m), str(path))


def _read_models(path: Path) -> list[dict]:
    if path.is_dir():
        return [MM.load(p) for p in sorted(path.glob("*.json"))]
    if not path.is_file():
        return []
    if path.suffix.lower() == ".json":
        return [MM.load(path)]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for m in data.get("machines") or []:
        out.append(MM.with_dir(MM.check(dict(m), str(path)), path.parent) if m.get("format") == MM.FORMAT
                   else _legacy_entry(path, m))
    return out


def _read(path: Path) -> list[dict]:
    """旧视图（兼容以前的调用）"""
    return [v for v in map(MM.legacy_view, _read_models(path)) if _view_ok(v)]


def models(env=None) -> list[dict]:
    """示例在前；企业的同 id 覆盖示例"""
    by_id = {m["id"]: m for m in _read_models(EXAMPLE)}
    for m in _read_models(user_file(env)) + _read_models(user_dir(env)):
        by_id[m["id"]] = {**m, "example": False}
    return list(by_id.values())


def model(machine_id: str, env=None) -> dict:
    for m in models(env):
        if m["id"] == machine_id:
            return m
    raise MachineError(f"没有机床 {machine_id!r}；可选：{', '.join(m['id'] for m in models(env))}")


def _view_ok(v: dict) -> bool:
    return MM.is_three_axis(v["model"]) and all(k in v for k in VIEW_NEED[v["kind"]])


def all_machines(env=None) -> list[dict]:
    """两轴车床、三轴加工中心的旧字段视图（现有车削、2.5 轴铣、程序检查用）"""
    out = []
    for m in models(env):
        v = MM.legacy_view(m)
        if _view_ok(v):
            out.append(v)
    return out


def get(machine_id: str, env=None) -> dict:
    for m in all_machines(env):
        if m["id"] == machine_id:
            return m
    if any(m["id"] == machine_id for m in models(env)):
        raise MachineError(f"机床 {machine_id!r} 不是两轴车床或三轴加工中心（或机床文件缺行程、快移、换刀点），"
                           "现有的车削、2.5 轴铣编程和程序检查用不了它")
    raise MachineError(f"没有机床 {machine_id!r}；可选：{', '.join(m['id'] for m in all_machines(env))}")
