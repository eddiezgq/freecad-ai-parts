# -*- coding: utf-8 -*-
"""问渠数字工厂 · 统一数据总线库（规范见《实施细则 第 1 轮》附录 A）。

所有 Python 组件（仿真车间、历史库、AI 助手、FreeCAD 发布宏的命令行版）都用它来
拼主题、打信封、校验消息，保证大家发出的消息格式一致。
"""
from .envelope import SPEC_VERSION, make, now_iso, parse, validate, ValidationError  # noqa: F401
from .topics import (  # noqa: F401
    ROOT, AREAS, UNITS, MACHINES, PLC_UNITS, UNIT_AREA, topic, split, unit_topic, RETAINED, qos_for,
)
