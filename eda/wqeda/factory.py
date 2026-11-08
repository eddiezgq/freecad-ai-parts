# -*- coding: utf-8 -*-
"""工厂端检查（第 112 轮 P5，问渠贴片）：客户的资料包（光绘 + 钻孔 + 物料清单 + 坐标）→ 检查结果 + 数量统计。

用和设计端同一个检查引擎（光绘那条路）；工厂端没有设计描述，极性元件按物料清单和位号列出来请人确认。
每条结果编号 R1、R2……，问题单引用这些编号。纯计算：不联网、不调 AI、不存文件（文件由调用方用完删掉）。"""

from __future__ import annotations

import re
import warnings

from . import quantity
from .checks import assembly, basic, process
from .checks.basic import UNKNOWN, _r
from .readers import gerber

POLAR_HINT = re.compile(r"(CP_|Polarized|Elec|^D_|LED|Diode|SOD|SMA|SMB|SMC|Tantal)", re.I)
NEEDS_DESIGN = {"F6": "器件外框", "F8": "器件外框", "T1": "网络", "C1": "网络"}
REF = re.compile(r"^[A-Z]{1,4}\d{1,4}$")


def polarity_list(board):
    """极性元件请确认（判未知）：位号 D、LED 开头，或封装像二极管、电解电容、钽电容的"""
    pkg = {r: row.package for row in board.bom for r in row.refs}
    refs = sorted(
        c.ref for c in board.components if re.match(r"^(D|LED)\d", c.ref) or POLAR_HINT.search(pkg.get(c.ref, ""))
    )
    at = [
        [round(c.x, 2), round(c.y, 2), "{} {}°".format(c.ref, round(c.rot) % 360)]
        for c in board.components
        if c.ref in refs
    ]
    return _r(
        "F7",
        "极性元件方向（请确认）",
        UNKNOWN,
        "polarity",
        len(refs),
        None,
        "个",
        at,
        "光绘里没有“第 1 脚在哪”，下面这些可能有极性的元件请对照客户的装配图确认方向：" + ("、".join(refs) or "没找到"),
    )


def refs_of(result):
    out = []
    for a in result.get("at") or []:
        for v in a if isinstance(a, list) else [a]:
            if isinstance(v, str):
                out += [t for t in re.split(r"[\s/、,]+", v) if REF.match(t)]
    return sorted(set(out), key=lambda r: (re.sub(r"\d", "", r), int(re.sub(r"\D", "", r) or 0)))


def check_package(gerbers, cap, bom=None, cpl=None, layers=None, bom_map=None, cpl_map=None):
    """→ {results: [{id, key, …}], quantity, notes, outline}"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        board = gerber.read(gerbers, bom, cpl, bom_map, cpl_map, layers=layers)
    res = basic.run(board, cap)["checks"]
    for r in process.run(board, cap, None):
        if r["key"] == "F7":
            r = polarity_list(board)
        elif r["key"] in NEEDS_DESIGN and r["status"] == UNKNOWN:
            r["detail"] = "资料包里没有{}，查不了：要客户给网表或设计文件".format(NEEDS_DESIGN[r["key"]])
        res.append(r)
    res += assembly.run(board, cap)
    cpl = {c.ref: c for c in board.components}
    for i, r in enumerate(res, 1):
        r["id"] = "R{}".format(i)
        r["refs"] = refs_of(r)
        # 板图上标的点：结果里带的坐标；没有坐标的按位号从坐标文件里找
        marks = [
            [a[0], a[1], " ".join(str(v) for v in a[2:])]
            for a in r.get("at") or []
            if isinstance(a, list) and len(a) >= 2 and all(isinstance(v, (int, float)) for v in a[:2])
        ]
        if not marks:
            marks = [[round(cpl[x].x, 2), round(cpl[x].y, 2), x] for x in r["refs"] if x in cpl]
        r["marks"] = marks[:50]
    st = getattr(board, "stack", None)
    return {
        "results": res,
        "quantity": quantity.count(board, cap),
        "notes": list(board.notes),
        "outline": list(board.outline) if board.outline else None,
        "board": board,
        "layers": gerber.layer_map(st) if st is not None else {},
    }
