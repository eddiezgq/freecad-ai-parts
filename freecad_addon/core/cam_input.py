"""数控编程窗口的输入解析（ADR-0059，M11 第二步）：纯函数，便于测试。

铣削特征每行一项（数字用空格或逗号分隔，单位 mm）：
  外轮廓 x0 y0 x1 y1 圆角 深      型腔 x0 y0 x1 y1 圆角 深
  槽 ax ay bx by 宽 深             孔 直径 深 x1 y1 x2 y2 …
"""

from __future__ import annotations

import re

KINDS = {"外轮廓": "contour", "contour": "contour", "型腔": "pocket", "pocket": "pocket", "槽": "slot", "键槽": "slot",
         "slot": "slot", "孔": "holes", "holes": "holes"}


class InputError(ValueError):
    pass


def _nums(text: str) -> list[float]:
    try:
        return [float(x) for x in re.split(r"[\s,，;；]+", text.strip()) if x]
    except ValueError as exc:
        raise InputError(f"不是数字：{text}") from exc


def parse_features(text: str) -> list[dict]:
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        word, _, rest = line.partition(" ")
        kind = KINDS.get(word.strip().lower())
        if kind is None:
            raise InputError(f"第 {n} 行：开头要是 外轮廓、型腔、槽 或 孔")
        v = _nums(rest)
        if kind in ("contour", "pocket"):
            if len(v) != 6:
                raise InputError(f"第 {n} 行：{word} 要 6 个数：x0 y0 x1 y1 圆角 深")
            out.append({"type": kind, "rect": v[:4], "corner_r": v[4], "depth": v[5]})
        elif kind == "slot":
            if len(v) != 6:
                raise InputError(f"第 {n} 行：槽要 6 个数：ax ay bx by 宽 深")
            out.append({"type": "slot", "a": v[:2], "b": v[2:4], "width": v[4], "depth": v[5]})
        else:
            if len(v) < 4 or len(v) % 2:
                raise InputError(f"第 {n} 行：孔要 直径 深 再加成对的 x y")
            out.append({"type": "holes", "d": v[0], "depth": v[1], "points": [v[i:i + 2] for i in range(2, len(v), 2)]})
    if not out:
        raise InputError("没有特征")
    return out


def parse_box(text: str) -> list[float]:
    v = _nums(text)
    if len(v) != 4 or v[2] <= v[0] or v[3] <= v[1]:
        raise InputError("毛坯要 4 个数：x0 y0 x1 y1（x1 > x0、y1 > y0）")
    return v


def summary(out: dict) -> str:
    """结果一行摘要。"""
    if out.get("status") != "ok":
        return "没有算出：" + "；".join(out.get("messages", []))
    d = out["data"]
    verdict = {"ok": "检查通过", "warn": "有提醒", "unknown": "部分待确认", "error": "有错误"}[d["verdict"]]
    t = d["total_time_s"]
    return f"{verdict}；{len(d['programs'])} 个程序，加工时间约 {t / 60:.1f} min（{t:.0f} s）"
