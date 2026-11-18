"""验证手册的记录（ADR-0096 第 4 步）：标准题测试在断言之外，把“算出来的值、参考值、容差”记下来。

平时不记（不影响测试）；设了环境变量 FAP_VERIFICATION_OUT（一个 .jsonl 文件）时，每调用一次追加一行。
验证手册（`python -m assist.fea_verification`）就是跑这些测试、读这些行生成的——手册里的数字就是测试算出来的。
"""

from __future__ import annotations

import json
import os


def _out():
    return os.environ.get("FAP_VERIFICATION_OUT")


def _case() -> str:
    return (os.environ.get("PYTEST_CURRENT_TEST") or "").split(" ")[0]


def record(quantity: tuple[str, str], computed: float, reference: float, *, tol: float, rel: bool = True,
           unit: str = "", formula: str = "") -> None:
    """一个数：quantity 是（中文, 英文）名称；tol 是容差（rel=True 时为相对值）；formula 是参考值的公式或出处要点"""
    out = _out()
    if not out:
        return
    err = (computed - reference) / reference if rel and reference else computed - reference
    row = {"case": _case(), "kind": "value", "quantity": list(quantity), "computed": float(computed),
           "reference": float(reference), "tol": float(tol), "rel": rel, "error": float(err), "unit": unit,
           "formula": formula, "ok": bool(abs(err) <= tol)}
    with open(out, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def record_verdict(quantity: tuple[str, str], computed: str, expected: str) -> None:
    """一个结论（如“奇异点必须判不收敛”）：computed 与 expected 是 pass / fail / unknown"""
    out = _out()
    if not out:
        return
    row = {"case": _case(), "kind": "verdict", "quantity": list(quantity), "computed": computed, "reference": expected,
           "ok": computed == expected}
    with open(out, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
