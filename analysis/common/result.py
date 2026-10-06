"""分析结果外壳（schema/analysis-result.schema.json）。"""

from __future__ import annotations

import copy
import math
from collections.abc import Iterable, Mapping

from kb.validation import errors

FORMAT = "analysis-result/1"


class ResultInvalid(RuntimeError):
    """结果不符合 schema：属于代码缺陷。"""


def check(name: str, computed: float, reference: float, formula: str) -> dict:
    """与手算 / 解析解的一项核对；相对误差按参考值算（参考值为 0 时按绝对差）。"""
    ref = abs(reference) if reference else 1.0
    return {"name": name, "computed": float(computed), "reference": float(reference), "formula": formula,
            "relative_error_ratio": abs(computed - reference) / ref}


def _clean(x):
    """转成 JSON 可序列化的普通类型（numpy 标量、元组等）。"""
    if isinstance(x, Mapping):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if hasattr(x, "tolist"):
        return _clean(x.tolist())
    if isinstance(x, float) and not math.isfinite(x):
        raise ResultInvalid(f"结果中有非有限数：{x}")
    return x


def make(module: str, version: str, setup: Mapping, data: Mapping, *, checks: Iterable[dict] = (),
         limitations: Iterable[str] = (), messages: Iterable[str] = (), solver: Mapping | None = None,
         elapsed_s: float | None = None) -> dict:
    out = {"format": FORMAT, "module": module, "module_version": version, "status": "ok",
           "setup": _clean(copy.deepcopy(dict(setup))), "data": _clean(dict(data)), "limitations": list(limitations),
           "messages": list(messages)}
    checks = list(checks)
    if checks:
        out["checks"] = _clean(checks)
    if solver:
        out["solver"] = dict(solver)
    if elapsed_s is not None:
        out["elapsed_s"] = round(float(elapsed_s), 3)
    return validate(out)


def failed(module: str, version: str, setup: Mapping, reason: str) -> dict:
    return validate({"format": FORMAT, "module": module, "module_version": version, "status": "failed",
                     "setup": _clean(copy.deepcopy(dict(setup))), "data": {}, "limitations": [], "messages": [reason]})


def validate(result: dict) -> dict:
    errs = errors("analysis-result.schema.json", result)
    if errs:
        raise ResultInvalid("；".join(errs[:5]))
    return result
