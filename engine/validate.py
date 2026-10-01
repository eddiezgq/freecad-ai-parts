"""运行全部 11 项校验，给出整体结论（实施细则第七节）。纯函数：组件由调用方解析。"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from engine.checks_electrical import c9, c10, c11
from engine.checks_interface import c1, c2, c3
from engine.checks_performance import c4, c5, c6, c7, c8
from engine.result import CheckResult, overall
from engine.system import System, load_system

CHECKS: tuple[Callable[[System], CheckResult], ...] = (c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11)


def run_checks(system: System) -> list[CheckResult]:
    return [check(system) for check in CHECKS]


def validate(system: Mapping, resolve: Callable[[str], dict | None]) -> dict:
    """校验一个系统对象（schema/system.schema.json），返回 {system, overall, checks: [...]}。"""
    loaded = load_system(system, resolve)
    results = run_checks(loaded)
    return {
        "system": loaded.id,
        "overall": overall(results),
        "checks": [r.to_dict() for r in results],
    }
