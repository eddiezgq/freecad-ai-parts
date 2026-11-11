# -*- coding: utf-8 -*-
"""实验 37“驱动板质量异常的追因与 8D”（第 148 轮，电路板厂）：通用实现见 hub/labq.py。
四种隐藏问题（sim/errors.py）：钢网堵孔 stencil_clog → 锡膏体积、回流炉温漂 reflow_drift → 峰值温度、
多功能贴片机 PP-2 吸嘴磨损 nozzle_wear → IC 偏移（IC 都由 PP-2 贴，属于一道工序的设备）、
采样电阻来料批次 shunt_lot → ICT 采样电阻阻值（按卷号分层，从某一卷起偏）。任务编号前缀 l37_。"""
from hub import labq

CFG = {
    "title": "驱动板质量异常的追因与 8D",
    "no": 37, "items": ("SMT-", "DRV-", "CTRL-", "ENC-RD"),
    "problems": {"stencil_clog": ("spi_volume", "shared"), "reflow_drift": ("reflow_peak", "shared"),
                 "nozzle_wear": ("offset_ic", "shared"), "shunt_lot": ("ict_shunt", "lot")},
    "layers": ("shared", "lot"),
    "lot": "按采样电阻卷号", "lot_layer": "从某一批来料起偏（来料批次）",
    "t1_desc": "老师注入问题后，车间接着做驱动板（老师或计划员接几张 DRV-JOINT 的单，贴片板 SMT-DRV 跟着做）。在“质量”页逐个看 AOI 和功能测试的特性，找出数据出了问题的那一个，说出触发的是哪条判异规则。",
    "t2_desc": "电路板厂一条 SMT 线：印刷、贴片、回流每道工序各一台设备，所有板子都过；功能测试的记录里还记着每块驱动板用的是哪一卷采样电阻。问题出在某一道工序的设备上（所有板子一起偏），还是从某一批来料起才偏？再说出是哪台设备，或者是哪一卷。",
    "t2_hint": "按卷号分组：只有某几卷偏 → 来料批次；不分卷都偏、偏的是印刷 / 贴片 / 回流后的特性 → 那道工序的设备（如 sp-1、pp-2、rf-1，见“设备”页）。",
    "t4_hint": "只有对症的措施能让数据恢复。提高峰值温度设定、换刮刀、AOI 判定加严这类措施，治不了根本原因。",
    "t5_desc": "写 D7 预防再发生：改了哪些工艺文件、加了什么防错（比如钢网按印刷次数自动擦网、回流炉每班测炉温曲线、吸嘴按贴装次数更换并做中心校正、采样电阻来料按卷抽检阻值），然后关闭 8D。",
}
globals().update(labq.build(CFG))
