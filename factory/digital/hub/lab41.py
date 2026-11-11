# -*- coding: utf-8 -*-
"""实验 41“输出轴质量异常的追因与 8D”（第 152 轮，减速器厂 = 演示工厂）：通用实现见 hub/labq.py。
六种隐藏问题（sim/errors.py 原有）：磨床尾座偏移 tailstock_offset、砂轮磨损加快 dressing_interval、磨床未预热 thermal_warmup、
中心孔质量差 center_hole、砂轮修整不锋利 wheel_dull（都在磨床 grd-01）；键槽夹具定位元件磨损 locator_worn（键槽铣 key-01）。
本厂每道工序一台设备，分层只有“共用的工序或设备”一层；难点在同一台磨床上分清是哪种原因、选对措施。判异按“质量”页的均值–极差图。任务编号前缀 l41_。"""
from hub import labq

CFG = {
    "title": "输出轴质量异常的追因与 8D",
    "no": 41, "items": ("SH-301",), "chart": "xbar", "layers": ("shared",),
    "problems": {"tailstock_offset": (("gear_seat_d40", "bearing_seat_d35_r", "bearing_seat_d35"), "shared"),
                 "dressing_interval": (("bearing_seat_d35", "bearing_seat_d35_r"), "shared"),
                 "thermal_warmup": (("gear_seat_d40", "bearing_seat_d35", "bearing_seat_d35_r"), "shared"),
                 "center_hole": ("runout_bearing", "shared"),
                 "wheel_dull": ("ra_bearing", "shared"),
                 "locator_worn": ("keyway_sym", "shared")},
    "t1_desc": "老师注入问题后，车间接着做减速器（老师或计划员接几张 WQR-105 的单）。在“质量”页逐个看输出轴 SH-301 三坐标检验的特性"
               "（均值–极差图），找出数据出了问题的那一个，说出触发的是哪条判异规则。",
    "t2_desc": "本厂每道工序只有一台设备，输出轴的尺寸、跳动、粗糙度在磨床 grd-01 上磨出来，键槽在键槽铣 key-01 上铣出来。"
               "看偏了的是哪一类特性，说出是哪台设备。",
    "t2_hint": "直径、跳动、粗糙度 → 磨床 grd-01；键槽宽、对称度 → 键槽铣 key-01。设备编号在“设备”页能查。",
    "t4_hint": "同一台磨床有五种可能的原因，看数据的样子分：右轴承位比左边大得多（锥度）→ 尾座；一个修整周期里涨得比平时快 → 修整间隔；"
               "开机后逐件变小 → 预热；跳动大 → 中心孔；粗糙度变大、出现烧伤 → 修整不锋利。放宽公差、加强自检治不了根本原因。",
    "t5_desc": "写 D7 预防再发生：改了哪些工艺文件、加了什么防错（比如尾座每周用检验棒校一次、修整间隔写进工艺卡、开机预热和首件检验、"
               "磨前修研中心孔、金刚石笔按次数更换、键槽夹具定位元件定期检定），然后关闭 8D。",
}
globals().update(labq.build(CFG))
