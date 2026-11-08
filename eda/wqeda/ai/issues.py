# -*- coding: utf-8 -*-
"""AI 起草工程问题单（第 112 轮 P5）：模型只拿到没通过的检查结果（不拿客户文件），每条问题必须引用结果编号；
引用、位号、检查项由代码核对和补上（wqeda.issues.build）。模型通过参数传进来，测试里换成替身。"""

from __future__ import annotations

from .. import issues as I

KEYS = ("id", "key", "name", "status", "value", "limit", "unit", "detail", "refs")


def for_model(results):
    """交给模型的内容：只有没通过的检查结果的这几项"""
    return [{k: r.get(k) for k in KEYS} for r in results if r.get("status") in I.OPEN]


def run(results, model, factory="", package="", lang="zh"):
    """model(结果, 工厂名, 语言) → (回答, 运行编号)。→ {issues: 问题单, rejected, run}"""
    open_ = for_model(results)
    if not open_:
        doc, _ = I.build(results, [], factory, package)
        return {"issues": doc, "rejected": [], "run": None}
    answer, rid = model(open_, factory, lang)
    drafted = (answer or {}).get("issues") if isinstance(answer, dict) else None
    doc, rejected = I.build(results, drafted if isinstance(drafted, list) else [], factory, package)
    return {"issues": doc, "rejected": rejected, "run": rid}
