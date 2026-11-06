# -*- coding: utf-8 -*-
"""板子模型（第 102 轮 P1）：统一检查引擎的中间数据。KiCad 板子文件和光绘文件（加物料清单、坐标）都读成它，
检查只看它，所以设计端、工厂端查的是同一批项、用的是同一套程序。

坐标：mm，用光绘文件的方向（x 向右、y 向上）；KiCad 的 y 向下，读的时候取反。只放数据，不做计算。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Track:
    layer: str  # 铜层：F、B、In1、In2……
    width: float  # 线宽 mm
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class Hole:
    x: float
    y: float
    drill: float  # 孔径 mm
    plated: bool  # 金属化孔
    ring: float | None  # 孔环 mm（外层焊盘最窄处减孔径的一半）；找不到焊盘为 None
    kind: str = ""  # via / pad（光绘里分不出时留空）
    ref: str = ""  # 焊盘所属位号（光绘里没有就留空）


@dataclass(frozen=True)
class Copper:
    layer: str
    x0: float  # 外接框
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class Pad:
    side: str  # F / B / FB（通孔两面都有）
    x: float
    y: float


@dataclass(frozen=True)
class Component:
    ref: str
    x: float
    y: float
    rot: float
    side: str  # F / B


@dataclass(frozen=True)
class BomRow:
    refs: tuple
    qty: int | None  # 物料清单里写的数量；没写为 None
    value: str = ""
    package: str = ""
    item: str = ""


@dataclass
class Board:
    source: str  # kicad / gerber
    outline: tuple  # 板框（中心线）外接框 (x0, y0, x1, y1)
    copper_layers: int
    tracks: list = field(default_factory=list)
    holes: list = field(default_factory=list)
    copper: list = field(default_factory=list)  # 所有铜（走线、焊盘、过孔、铺铜）的外接框，查铜到板边
    pads: list = field(default_factory=list)
    components: list = field(default_factory=list)
    bom: list = field(default_factory=list)
    notes: list = field(default_factory=list)  # 读的时候发现的情况（例如没有物料清单），检查里显示
