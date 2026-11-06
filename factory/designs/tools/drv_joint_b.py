# -*- coding: utf-8 -*-
"""关节驱动板 DRV-JOINT B 版（第 98 轮）：以 REV = "B" 执行 drv_joint.py（A 版上打补丁：编码器经 WQ-ENCIF 计数，MCU 用 SPI1 读）。
设计对照，不投产；芯片未流片。"""
import importlib.util
import os
import sys

_spec = importlib.util.spec_from_file_location("drv_joint_b_impl", os.path.join(os.path.dirname(os.path.abspath(__file__)), "drv_joint.py"))
_mod = importlib.util.module_from_spec(_spec)
_mod.REV = "B"
_spec.loader.exec_module(_mod)
sys.modules[__name__].__dict__.update({k: v for k, v in _mod.__dict__.items() if not k.startswith("__")})
