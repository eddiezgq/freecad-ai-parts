"""应力集中系数（有限元）的录制与回放（ADR-0100 42.2 之五，2026-11-19）。

AI 设计循环的录制按提示词全文取键。提示词里带校核数字，而有限元算的 kt 在 CI 与本机末几位不同，
回放时提示词对不上。录制时把每次 kt 的输入和结果记进 `kt.json`，回放时先查这里、查不到才现算；
回放测试另外用本机有限元复算采用方案的 kt，与录制值比对（差 ≤ 2 %），确认录下的数不是凭空的。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path


class KtReplayError(RuntimeError):
    pass


def _key(args: tuple) -> str:
    return json.dumps([float(a) for a in args])


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    return {_key(tuple(e["args"])): e for e in json.loads(path.read_text(encoding="utf-8"))}


def _save(path: Path, table: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(table.values(), key=lambda e: e["args"])
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")


def recording(path: Path, kt: Callable | None = None) -> Callable:
    """现算并记下（异常也记下，回放时照样抛出同样的说明）"""
    if kt is None:
        from analysis.shaft.kt import stepped_bar as kt
    table = _load(path)

    def f(*args):
        key = _key(args)
        try:
            res = kt(*args)
        except Exception as ex:
            table[key] = {"args": [float(a) for a in args], "error": str(ex)}
            _save(path, table)
            raise
        table[key] = {"args": [float(a) for a in args], "result": res}
        _save(path, table)
        return res

    return f


def replaying(path: Path, kt: Callable | None = None) -> Callable:
    """先查录制；查不到才现算（kt 缺省用有限元）"""
    table = _load(path)

    def f(*args):
        e = table.get(_key(args))
        if e is None:
            g = kt
            if g is None:
                from analysis.shaft.kt import stepped_bar as g
            return g(*args)
        if "error" in e:
            raise KtReplayError(e["error"])
        return dict(e["result"])

    return f
