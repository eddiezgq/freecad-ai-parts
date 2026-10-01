"""引擎测试共用：golden 用例与组件。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

GOLDEN = Path(__file__).resolve().parent / "golden"
FIXTURES = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (GOLDEN / "fixtures").glob("*.json")}
CASES = sorted(GOLDEN.glob("*/*.yaml"))


def case(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def case_by_id(cid: str) -> dict:
    return case(GOLDEN / f"{cid}.yaml")


def resolver(overrides: dict | None = None):
    """组件解析：先查 overrides（测试中改过的组件），再查 golden fixtures。"""
    comps = {**FIXTURES, **(overrides or {})}
    return comps.get


def edited(cid: str, fn) -> dict:
    """复制一个组件并用 fn 修改，返回 {id: 组件}。"""
    comp = copy.deepcopy(FIXTURES[cid])
    fn(comp)
    return {cid: comp}


def port(comp: dict, pid: str) -> dict:
    return next(p for p in comp["ports"] if p["id"] == pid)


def assert_golden(path: Path, results: dict[str, str]) -> None:
    """按 golden 用例的 expected 断言已实现的各项（results：检查编号 → 状态）。"""
    exp = dict(case(path)["expected"]["checks"])
    others = exp.pop("others", None)
    for check, status in results.items():
        if check in exp:
            if exp[check] != "any":
                assert status == exp[check], f"{check}: 实际 {status}，预期 {exp[check]}"
        elif others == "not_fail":
            assert status != "fail", f"{check}: 不得为 fail"
