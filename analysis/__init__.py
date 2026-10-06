"""分析模块（ADR-0056）：每个功能一个子包，本机运行，不联网、不调用 LLM；结果不写入零件参数。

每个模块（子包）提供：
- MODULE：{"id", "name", "description", "python": [依赖的 Python 包], "solvers": ["ccx", ...], "install": 安装方法}
- run(setup: dict) -> dict：符合 schema/analysis-result.schema.json 的结果
模块之间只通过结果字典衔接。
"""

from __future__ import annotations

import importlib
from types import ModuleType

from analysis.common import result
from analysis.common.solvers import find_ccx, missing_python

# 已实现的模块（按 M10 顺序逐个加入）
MODULE_PATHS: tuple[str, ...] = ("analysis.mbd", "analysis.fea", "analysis.fatigue")


class UnknownModule(LookupError):
    pass


def _load(path: str) -> ModuleType:
    return importlib.import_module(path)


def _ids() -> dict[str, str]:
    return {_load(p).MODULE["id"]: p for p in MODULE_PATHS}


def status(mod: ModuleType) -> dict:
    """模块是否可用、缺什么、怎么装。"""
    info = dict(mod.MODULE)
    missing = [f"Python 包 {m}" for m in missing_python(info.get("python", []))]
    if "ccx" in info.get("solvers", []) and find_ccx() is None:
        missing.append("CalculiX 求解器 ccx（FreeCAD 自带；或设置环境变量 FAP_CCX）")
    return {"id": info["id"], "name": info["name"], "description": info.get("description", ""),
            "available": not missing, "missing": missing, "install": info.get("install", "")}


def modules() -> list[dict]:
    return [status(_load(p)) for p in MODULE_PATHS]


def get(module_id: str) -> ModuleType:
    path = _ids().get(module_id)
    if path is None:
        raise UnknownModule(f"没有分析模块 {module_id!r}；可用：{', '.join(_ids()) or '（无）'}")
    return _load(path)


def run(module_id: str, setup: dict) -> dict:
    """运行一个模块；依赖缺失时返回 failed 结果并说明缺什么。"""
    mod = get(module_id)
    st = status(mod)
    if not st["available"]:
        return result.failed(module_id, mod.MODULE.get("version", "1"), setup,
                             f"{st['name']} 不可用：缺 {'、'.join(st['missing'])}。{st['install']}")
    return mod.run(setup)
