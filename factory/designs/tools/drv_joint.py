# -*- coding: utf-8 -*-
"""关节伺服驱动板 DRV-JOINT 的设计数据（第 88 轮，电子 E4；第 102 轮起从设计描述读）。

设计本身在 `factory/designs/drv-joint/design.yaml`（问渠电子的四层设计描述：规格、功能块、电路、板子），
B 版是它上面的改动清单 `factory/designs/drv-joint-b/variant.yaml`。本模块读它们、展开（变体、ICT 测试点、测试点网格），
把结果放成原来的名字（PARTS、PLACEMENT、POURS……），build.py、sch.py、pcb.py、dfm.py 照旧用。改设计请改 YAML。
示例设计，未经硬件验证，不能直接投产。"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DESIGNS = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_DESIGNS)), "eda"))

from wqeda.schema import design as _wq  # noqa: E402

# 第 98 轮：drv_joint_b.py 以 REV = "B" 执行本文件；直接 import 本模块就是 A 版
REV = globals().get("REV", "A")

if REV == "B":
    _base, _var = _wq.load_variant(os.path.join(_DESIGNS, "drv-joint-b", "variant.yaml"))
else:
    _base, _var = _wq.load_design(os.path.join(_DESIGNS, "drv-joint", "design.yaml")), None
_X = _wq.expand(_base, _var)

if _X["title"]:
    TITLE = _X["title"]
globals().update(_X["params"])                 # RS_MOHM、GAIN、RG_OHM、VDRV、C_BUS_UF、ENC_R_OHM、ENC_C_PF（各功能块的参数）
globals().update(_X["footprints"])             # FP_R、FP_C、FP_C1206、FP_SOIC8、FP_TP
BOARD_MM = _X["board_mm"]
LAYERS = _X["layers"]
SHEETS = _X["sheets"]                          # 原理图每页 = 一个功能块
PARTS = [{"ref": q["ref"], "lib": q["lib"], "value": q["value"], "fp": q["fp"], "sheet": q["block"], "pins": q["pins"],
          "item": q["item"], "note": q["note"]} for q in _X["parts"]]
B_CHANGES = _X["changes"]                      # (位号, 改了什么) —— 页面“A→B 改了什么”用
ICT_NETS = _X["ict_nets"]
NC_NETS = _X["nc_nets"]
POWER_NETS = _X["power_nets"]
HIGH_CURRENT = _X["high_current"]              # 连续电流 A（示例）
BACK_END_ITEMS = _X["back_end_items"]          # 电路板厂清单里后段（成品板）用的物料
PLACEMENT = _X["placement"]                    # 板子左上角为原点，x 向右、y 向下，mm；角度逆时针；面 F 顶 / B 底
HOLES = _X["holes"]                            # M3 安装孔，焊盘接地
POWER_PADS = _X["power_pads"]                  # 大电流路径上的焊盘（DFM 查这些焊盘之间有一条足够宽的铜路径）
POURS = _X["pours"]                            # 功率铺铜（顶层）


def nets():
    out = {}
    for p in PARTS:
        for pin, n in p["pins"].items():
            out.setdefault(n, []).append((p["ref"], pin))
    return out


def bom_by_item():
    out = {}
    for p in PARTS:
        if p["item"]:
            out[p["item"]] = out.get(p["item"], 0) + 1
    return out
