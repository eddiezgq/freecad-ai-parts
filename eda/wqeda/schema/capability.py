# -*- coding: utf-8 -*-
"""工厂工艺能力表（第 102 轮 P1）：每家工厂一份，由工厂自己填，存成 YAML。检查的门槛全部从这里取，代码里不写数值。
没填的项是“未知”：用到它的检查判 unknown，不判通过。"""

from __future__ import annotations

from .design import DesignError, read_yaml

FORMAT = "wqeda.capability/1"
# 认识的项：键 → (中文名, 单位)。新项先加在这里，检查才能用
ITEMS = {
    "track_min_mm": ("最小线宽", "mm"),
    "space_min_mm": ("最小线距", "mm"),
    "drill_min_mm": ("最小孔径", "mm"),
    "annular_min_mm": ("最小孔环", "mm"),
    "mask_bridge_min_mm": ("最小阻焊桥", "mm"),
    "copper_edge_min_mm": ("铜到板边最小距离", "mm"),
    "component_edge_min_mm": ("元件到板边最小距离", "mm"),
    "board_max_mm": ("能贴的最大板子 [长, 宽]", "mm"),
    "board_min_mm": ("能贴的最小板子 [长, 宽]", "mm"),
}


def validate(doc):
    p = []
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        return ["format 应为 {}".format(FORMAT)]
    if not isinstance(doc.get("factory"), str) or not doc["factory"]:
        p.append("缺 factory（工厂名）")
    for k, v in (doc.get("pcb") or {}).items():
        if k not in ITEMS:
            p.append("不认识的工艺能力项 {}".format(k))
        elif v is None:
            continue
        elif k.startswith("board_"):
            if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) and x > 0 for x in v)):
                p.append("{} 应是 [长, 宽]".format(k))
        elif not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            p.append("{} 应是正数".format(k))
    return p


def load(path):
    doc = read_yaml(path)
    probs = validate(doc)
    if probs:
        raise DesignError(probs)
    return doc


def value(cap, key):
    """取一项能力值；没填返回 None（= 未知）"""
    if key not in ITEMS:
        raise KeyError(key)
    return (cap.get("pcb") or {}).get(key)
