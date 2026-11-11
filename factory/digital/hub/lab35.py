# -*- coding: utf-8 -*-
"""实验 35“电机质量异常的追因与 8D”（第 147 轮，电机厂）：通用实现见 hub/labq.py。
四种隐藏问题（sim/errors.py）：磁钢定位工装 mag_fixture → 齿槽转矩、充磁电压 magnetizer_low → 反电势常数、
绕线机 wd-2 张力 wind_tension → 三相电阻不平衡（只在 wd-2 绕的定子上）、浸漆炉温 varnish_low → 耐压漏电流。任务编号前缀 l35_。"""
from hub import labq

CFG = {
    "title": "电机质量异常的追因与 8D",
    "no": 35, "items": ("WQ-SM", "WQ-AM"),
    "problems": {"mag_fixture": ("mt_cog", "shared"), "magnetizer_low": ("mt_ke", "shared"),
                 "wind_tension": ("st_r_unbal", "station"), "varnish_low": ("st_leak", "shared")},
    "station": "按绕线机", "station_layer": "只在某一台绕线机绕的定子上",
    "t1_desc": "老师注入问题后，车间接着做电机（老师或计划员接几张 WQ-SM100 / 200 / 400、WQ-AM750 的单）。在“质量”页逐个看电机终检的特性，找出数据出了问题的那一个，说出触发的是哪条判异规则。",
    "t2_desc": "电机的测量记着定子是哪台绕线机绕的，可以按绕线机分组看均值。问题只出在某一台绕线机绕的定子上，还是所有电机一起偏（原因在大家共用的工序或设备上：浸漆烘箱、磁钢粘贴、充磁）？再说出是哪台设备。",
    "t2_hint": "只在一组里偏 → 原因在那一台；所有组一起偏 → 原因在共用的工序。设备编号在“设备”页能查（如 wd-2、vo-1、mg-1、mz-1）。",
    "t4_hint": "只有对症的措施能让数据恢复。放宽终检公差、驱动器里补偿、返烘这类措施，治不了根本原因。",
    "t5_desc": "写 D7 预防再发生：改了哪些工艺文件、加了什么防错（比如粘贴工装定期检定、充磁机电容按次数更换并每班测标准转子、绕线张力在线监测、烘箱多点测温），然后关闭 8D。",
}
globals().update(labq.build(CFG))
