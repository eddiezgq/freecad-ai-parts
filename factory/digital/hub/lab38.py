# -*- coding: utf-8 -*-
"""实验 38“芯片封测质量异常的追因与 8D”（第 148 轮，芯片封测厂）：通用实现见 hub/labq.py。
四种隐藏问题（sim/errors.py）：探针卡磨损 probe_wear → CP 接触电阻、划片刀磨损 blade_wear → 崩边、
键合机 wb-2 劈刀磨损 capillary_wear → 键合拉力（只在 wb-2 键合的批次上）、塑封料受潮 emc_moisture → 塑封空洞率。任务编号前缀 l38_。"""
from hub import labq

CFG = {
    "title": "芯片封测质量异常的追因与 8D",
    "no": 38, "items": ("WAF-", "WQ-ENCIF"),
    "problems": {"probe_wear": ("cp_contact", "shared"), "blade_wear": ("chipping", "shared"),
                 "capillary_wear": ("bond_pull", "station"), "emc_moisture": ("mold_void", "shared")},
    "station": "按键合机", "station_layer": "只在某一台键合机键合的批次上",
    "t1_desc": "老师注入问题后，车间接着封测（老师或计划员接几张 WQ-ENCIF 的单）。在“质量”页逐个看晶圆测试（CP）和成品测试（FT）的特性，找出数据出了问题的那一个，说出触发的是哪条判异规则。",
    "t2_desc": "成品测试的记录里记着每批是哪台键合机键合的，可以按键合机分组看均值。问题只出在某一台键合的批次上，还是所有批一起偏（原因在大家共用的工序或设备上：探针台、划片机、塑封机）？再说出是哪台设备。",
    "t2_hint": "只在一组里偏 → 原因在那一台；所有组一起偏 → 原因在共用的工序。设备编号在“设备”页能查（如 prb-1、dc-1、wb-2、mld-1）。",
    "t4_hint": "只有对症的措施能让数据恢复。CP 失效全部复测、加大键合功率、FT 判定加严这类措施，治不了根本原因。",
    "t5_desc": "写 D7 预防再发生：改了哪些工艺文件、加了什么防错（比如探针卡按扎针次数清洁并量各测试位接触电阻、划片刀按切割长度换刀、劈刀按键合次数更换并首件拉力试验、塑封料回温和开封时限记录），然后关闭 8D。",
}
globals().update(labq.build(CFG))
