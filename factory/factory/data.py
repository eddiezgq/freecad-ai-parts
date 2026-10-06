# -*- coding: utf-8 -*-
"""
问渠虚拟工厂 · 二级圆柱齿轮减速器 WQR-105 的全部主数据。

这是唯一的数据源：seed.py 把这里的内容导入 ERPNext，tests/ 检查它前后一致，
工厂设计.md 里的表格也以这里为准。改工厂就改这个文件。

所有供应商、客户都是虚构的示例单位（名称里带“示例/Demo”）。
单价为教学用的示意数值（美元）。
"""
import math

# ---------------------------------------------------------------- 齿轮与传动计算
ALPHA = math.radians(20.0)


def inv(a):
    return math.tan(a) - a


def center_distance(m, z1, z2):
    return m * (z1 + z2) / 2


def span_teeth(z):
    """公法线跨齿数（α = 20°）：z = 9–18 取 2，19–27 取 3……即 k = ⌊(z − 1)/9⌋ + 1，与常用表格一致。"""
    return max(2, (z - 1) // 9 + 1)


def base_tangent_length(m, z):
    """公法线长度 W_k = m·cosα·[π(k − 0.5) + z·inv α]（标准齿轮，mm）。"""
    k = span_teeth(z)
    return k, m * math.cos(ALPHA) * (math.pi * (k - 0.5) + z * inv(ALPHA))


GEARS = {
    # 代号: 模数, 齿数, 所在轴
    "SH-101": {"m": 2, "z": 24},   # 输入齿轮轴（齿轮与轴一体）
    "GR-202": {"m": 2, "z": 72},   # 第一级大齿轮
    "GR-203": {"m": 3, "z": 20},   # 第二级小齿轮
    "GR-302": {"m": 3, "z": 70},   # 第二级大齿轮
}
STAGES = [("SH-101", "GR-202"), ("GR-203", "GR-302")]
INPUT_SPEED_RPM = 1450          # 输入转速（4 极电机）


def ratio():
    i = 1.0
    for a, b in STAGES:
        i *= GEARS[b]["z"] / GEARS[a]["z"]
    return i


def gear_w(code, upper_dev, lower_dev):
    """公法线长度检验范围：名义值加上下偏差（mm，偏差为负值）。"""
    g = GEARS[code]
    k, w = base_tangent_length(g["m"], g["z"])
    return k, round(w + lower_dev, 3), round(w + upper_dev, 3)


# ---------------------------------------------------------------- 分组与仓库
ITEM_GROUPS = ["原材料 Raw Materials", "外购件 Purchased Parts", "自制零件 Made Parts",
               "部件 Sub-assemblies", "成品 Finished Goods"]
WAREHOUSES = ["原材料库 Raw", "外购件库 Purchased", "半成品库 Semi-finished",
              "在制品库 WIP", "成品库 Finished", "不合格品库 Rejected"]
SUPPLIER_GROUP = "减速器供应商 Gearbox Suppliers"
CUSTOMER_GROUP = "减速器客户 Gearbox Customers"

SUPPLIERS = {
    "castings":  {"name": "示例·东岳铸造 Dongyue Castings (Demo)", "lead": 21},
    "forgings":  {"name": "示例·基石锻造 Keystone Forging (Demo)", "lead": 14},
    "steel":     {"name": "示例·中西部钢材 Midwest Steel (Demo)", "lead": 5},
    "bearings":  {"name": "示例·五大湖轴承 Great Lakes Bearing (Demo)", "lead": 7},
    "hardware":  {"name": "示例·先锋工业品 Pioneer Industrial Supply (Demo)", "lead": 3},
    "lubricant": {"name": "示例·海湾润滑油 Gulf Coast Lubricants (Demo)", "lead": 3},
}
CUSTOMERS = [
    "示例·绿谷输送设备 GreenValley Conveyor (Demo)",
    "示例·峰顶搅拌机 Summit Mixer Works (Demo)",
    "示例·海港起重 Harbor Crane Systems (Demo)",
]

# ---------------------------------------------------------------- 物料
# kind: raw 原材料 / buy 外购件 / make 自制零件 / sub 部件 / fg 成品
# 字段：代号: (名称, 类别, 单位, 单价或 None, 供应商键, 检验模板, 备注)
ITEMS = {
    # 原材料
    "RM-45-D50":     ("45钢圆棒 Ø50 Steel bar 1045 Ø50", "raw", "Kg", 1.60, "steel", None, "中间轴、输出轴用料"),
    "RM-20CR-D60":   ("20CrMnTi圆钢 Ø60 Steel bar 20CrMnTi Ø60", "raw", "Kg", 2.40, "steel", None, "输入齿轮轴用料，渗碳钢"),
    "RM-20CR-D70":   ("20CrMnTi圆钢 Ø70 Steel bar 20CrMnTi Ø70", "raw", "Kg", 2.40, "steel", None, "第二级小齿轮用料"),
    "RM-40CR-F155":  ("40Cr锻坯 Ø155×32 Forging blank 40Cr", "raw", "Nos", 28.00, "forgings", "进货检验-锻坯", "第一级大齿轮毛坯"),
    "RM-40CR-F225":  ("40Cr锻坯 Ø225×45 Forging blank 40Cr", "raw", "Nos", 62.00, "forgings", "进货检验-锻坯", "第二级大齿轮毛坯"),
    "RM-HT200-BASE": ("箱座铸件 HT200 Housing base casting", "raw", "Nos", 180.00, "castings", "进货检验-铸件", "灰铸铁"),
    "RM-HT200-COVER": ("箱盖铸件 HT200 Housing cover casting", "raw", "Nos", 120.00, "castings", "进货检验-铸件", "灰铸铁"),
    # 外购件
    "BRG-6205":   ("深沟球轴承 6205-2RS Ball bearing 25×52×15", "buy", "Nos", 5.20, "bearings", "进货检验-轴承", "输入轴"),
    "BRG-6206":   ("深沟球轴承 6206-2RS Ball bearing 30×62×16", "buy", "Nos", 6.50, "bearings", "进货检验-轴承", "中间轴"),
    "BRG-6207":   ("深沟球轴承 6207-2RS Ball bearing 35×72×17", "buy", "Nos", 8.00, "bearings", "进货检验-轴承", "输出轴"),
    "SEAL-20":    ("骨架油封 20×35×7 Oil seal", "buy", "Nos", 1.80, "hardware", None, "输入轴伸"),
    "SEAL-30":    ("骨架油封 30×47×7 Oil seal", "buy", "Nos", 2.20, "hardware", None, "输出轴伸"),
    "KEY-6x6x25": ("平键 6×6×25 Parallel key", "buy", "Nos", 0.20, "hardware", None, "输入轴伸，GB/T 1096"),
    "KEY-8x7x36": ("平键 8×7×36 Parallel key", "buy", "Nos", 0.30, "hardware", None, "输出轴伸"),
    "KEY-10x8x28": ("平键 10×8×28 Parallel key", "buy", "Nos", 0.40, "hardware", None, "中间轴齿轮"),
    "KEY-12x8x45": ("平键 12×8×45 Parallel key", "buy", "Nos", 0.60, "hardware", None, "输出轴齿轮"),
    "CAP-52-T":   ("轴承透盖 Ø52 Through cap", "buy", "Nos", 7.50, "hardware", None, "输入轴，带油封孔"),
    "CAP-52-B":   ("轴承闷盖 Ø52 Blind cap", "buy", "Nos", 6.00, "hardware", None, "输入轴"),
    "CAP-62-B":   ("轴承闷盖 Ø62 Blind cap", "buy", "Nos", 6.50, "hardware", None, "中间轴两端"),
    "CAP-72-T":   ("轴承透盖 Ø72 Through cap", "buy", "Nos", 9.00, "hardware", None, "输出轴，带油封孔"),
    "CAP-72-B":   ("轴承闷盖 Ø72 Blind cap", "buy", "Nos", 7.50, "hardware", None, "输出轴"),
    "BOLT-M12x110": ("六角头螺栓 M12×110 Hex bolt 8.8", "buy", "Nos", 0.80, "hardware", None, "箱体联接"),
    "NUT-M12":    ("六角螺母 M12 Hex nut", "buy", "Nos", 0.10, "hardware", None, ""),
    "WASHER-12":  ("弹簧垫圈 12 Spring washer", "buy", "Nos", 0.05, "hardware", None, ""),
    "BOLT-M8x25": ("内六角螺钉 M8×25 Socket screw", "buy", "Nos", 0.12, "hardware", None, "端盖紧固"),
    "PIN-8x35":   ("圆锥销 8×35 Taper pin", "buy", "Nos", 0.30, "hardware", None, "箱体定位"),
    "PLUG-M16":   ("放油螺塞 M16×1.5 Drain plug", "buy", "Nos", 1.20, "hardware", None, ""),
    "VENT-M16":   ("通气器 M16×1.5 Breather", "buy", "Nos", 2.50, "hardware", None, ""),
    "GAUGE-M12":  ("杆式油标 M12 Oil dipstick", "buy", "Nos", 3.00, "hardware", None, ""),
    "OIL-CKC220": ("工业齿轮油 L-CKC 220 Gear oil", "buy", "Litre", 6.00, "lubricant", None, ""),
    "SEALANT":    ("平面密封胶 Flange sealant", "buy", "Kg", 60.00, "lubricant", None, "箱体结合面"),
    # 自制零件
    "SH-101": ("输入齿轮轴 m2 z24 Input pinion shaft", "make", "Nos", None, None, "零件检验-输入齿轮轴", "20CrMnTi 渗碳淬火"),
    "SH-201": ("中间轴 Intermediate shaft", "make", "Nos", None, None, "零件检验-中间轴", "45钢 调质"),
    "SH-301": ("输出轴 Output shaft", "make", "Nos", None, None, "零件检验-输出轴", "45钢 调质；即 FreeCAD 宏 wq_shaft.py 的默认轴"),
    "GR-202": ("大齿轮 m2 z72 Gear", "make", "Nos", None, None, "零件检验-大齿轮z72", "40Cr 调质"),
    "GR-203": ("小齿轮 m3 z20 Pinion", "make", "Nos", None, None, "零件检验-小齿轮z20", "20CrMnTi 渗碳淬火"),
    "GR-302": ("大齿轮 m3 z70 Gear", "make", "Nos", None, None, "零件检验-大齿轮z70", "40Cr 调质"),
    "HSG-001": ("箱座 Housing base", "make", "Nos", None, None, None, ""),
    "HSG-002": ("箱盖 Housing cover", "make", "Nos", None, None, None, ""),
    # 部件
    "SA-000": ("箱体组件（合镗） Housing assembly", "sub", "Nos", None, None, "零件检验-箱体", "箱座箱盖合箱后镗轴承孔"),
    "SA-100": ("输入轴组件 Input shaft assembly", "sub", "Nos", None, None, None, ""),
    "SA-200": ("中间轴组件 Intermediate shaft assembly", "sub", "Nos", None, None, None, ""),
    "SA-300": ("输出轴组件 Output shaft assembly", "sub", "Nos", None, None, None, ""),
    # 成品
    "WQR-105": ("二级圆柱齿轮减速器 i=10.5 Two-stage gear reducer", "fg", "Nos", None, None, "出厂检验-减速器", "输入 1450 r/min，输出约 138 r/min"),
}

# 教材案例件（第 11 轮《机械设计》第 33 章 33.9、33.10）：不是减速器厂的产品，不进 BOM、不备料，只在 ERPNext 里建物料，
# 学生才能把这两根轴的模型读入“仿真与分析”、提交“设计发布与审批”。每次部署都补建（seed.py case_items）。
CASE_ITEMS = {
    "RJ-201": ("机器人关节空心轴 Robot joint hollow shaft", "make", "Nos", None, None, None, "教材案例件：协作机器人肩关节（谐波减速器输出侧）"),
    "LS-101": ("平缝机上轴 Lockstitch machine upper shaft", "make", "Nos", None, None, None, "教材案例件：工业平缝机 WQ-LS 主轴（伺服直驱）"),
}
FG_SELLING_PRICE = 1650.00

# 标准外购件（及成品 WQR-105）在问渠零件库里的编号（第 5 轮 P10②）；与零件库各条目的 factory.erp_items 一致（library/tests 核对）
LIBRARY_REFS = {
    "BRG-6205": "A-BRG-DG/6205", "BRG-6206": "A-BRG-DG/6206", "BRG-6207": "A-BRG-DG/6207",
    "KEY-6x6x25": "A-KEY-FLAT/6x6x25", "KEY-8x7x36": "A-KEY-FLAT/8x7x36", "KEY-10x8x28": "A-KEY-FLAT/10x8x28",
    "KEY-12x8x45": "A-KEY-FLAT/12x8x45", "BOLT-M12x110": "A-BLT-HEX/M12x110", "NUT-M12": "A-NUT-HEX/M12",
    "BOLT-M8x25": "A-SCR-SHC/M8x25", "WASHER-12": "A-WSH-SPR/12", "PIN-8x35": "A-PIN-TAPER/8x35",
    "SEAL-20": "A-SEL-LIP/20x35x7", "SEAL-30": "A-SEL-LIP/30x47x7", "PLUG-M16": "A-PLG-HEX/M16x1.5",
    "WQR-105": "C-RED-WQR105/default",   # 成品 ↔ 零件库 C 部分的减速器传动机构（第 5 轮第 6 步）
}

KIND_GROUP = {"raw": ITEM_GROUPS[0], "buy": ITEM_GROUPS[1], "make": ITEM_GROUPS[2],
              "sub": ITEM_GROUPS[3], "fg": ITEM_GROUPS[4]}
KIND_WAREHOUSE = {"raw": WAREHOUSES[0], "buy": WAREHOUSES[1], "make": WAREHOUSES[2],
                  "sub": WAREHOUSES[2], "fg": WAREHOUSES[4]}
SAFETY_STOCK = {"BRG-6205": 10, "BRG-6206": 10, "BRG-6207": 10, "SEAL-20": 10, "SEAL-30": 10}

# ---------------------------------------------------------------- 工作中心（工位）
# 名称: (台数, {成本项: 美元/小时})
COST_COMPONENTS = ["设备折旧 Depreciation", "人工 Labour", "能耗 Energy"]
WORKSTATIONS = {
    "带锯床 SAW-01":        (1, (8, 14, 3)),
    "数控车床 CNC-L01":     (2, (18, 24, 6)),
    "立式加工中心 VMC-01":  (1, (28, 26, 8)),
    "卧式加工中心 HMC-01":  (1, (38, 30, 10)),
    "键槽铣床 KEY-01":      (1, (10, 22, 4)),
    "滚齿机 HOB-01":        (1, (22, 26, 7)),
    "热处理炉 HT-01":       (20, (10, 12, 12)),   # 一炉可装 20 件
    "外圆磨床 GRD-01":      (1, (20, 26, 6)),
    "检验站 QC-01":         (1, (8, 30, 2)),
    "装配工位 ASM-01":      (2, (4, 28, 2)),
    "跑合试验台 TEST-01":   (1, (8, 16, 6)),
}
SHIFT = [("08:00:00", "12:00:00"), ("13:00:00", "17:00:00")]   # 单班 8 小时

# 工序名: 默认工位
OPERATIONS = {
    "下料 Sawing": "带锯床 SAW-01",
    "粗车 Rough turning": "数控车床 CNC-L01",
    "精车 Finish turning": "数控车床 CNC-L01",
    "铣键槽 Keyway milling": "键槽铣床 KEY-01",
    "滚齿 Gear hobbing": "滚齿机 HOB-01",
    "调质 Quench & temper": "热处理炉 HT-01",
    "渗碳淬火 Carburizing": "热处理炉 HT-01",
    "磨外圆 Cylindrical grinding": "外圆磨床 GRD-01",
    "铣结合面 Face milling": "立式加工中心 VMC-01",
    "钻攻螺纹孔 Drilling & tapping": "立式加工中心 VMC-01",
    "合箱钻铰销孔 Pin-hole reaming": "卧式加工中心 HMC-01",
    "镗轴承孔 Bearing-bore boring": "卧式加工中心 HMC-01",
    "零件检验 Part inspection": "检验站 QC-01",
    "部件装配 Sub-assembly": "装配工位 ASM-01",
    "总装 Final assembly": "装配工位 ASM-01",
    "跑合试验 Run-in test": "跑合试验台 TEST-01",
    "出厂检验 Final inspection": "检验站 QC-01",
    "清洗包装 Cleaning & packing": "装配工位 ASM-01",
}
INSPECTION_OPS = {"零件检验 Part inspection", "出厂检验 Final inspection"}

# 工艺路线：名称: [(工序, 每件分钟)]
ROUTINGS = {
    "RT-轴 Shaft (45 steel)": [
        ("下料 Sawing", 3), ("粗车 Rough turning", 18), ("调质 Quench & temper", 12),
        ("精车 Finish turning", 15), ("铣键槽 Keyway milling", 10),
        ("磨外圆 Cylindrical grinding", 12), ("零件检验 Part inspection", 6)],
    "RT-齿轮轴 Pinion shaft": [
        ("下料 Sawing", 3), ("粗车 Rough turning", 20), ("精车 Finish turning", 15),
        ("滚齿 Gear hobbing", 25), ("渗碳淬火 Carburizing", 20),
        ("磨外圆 Cylindrical grinding", 15), ("零件检验 Part inspection", 8)],
    "RT-锻坯齿轮 Forged gear": [
        ("粗车 Rough turning", 20), ("调质 Quench & temper", 15), ("精车 Finish turning", 18),
        ("铣键槽 Keyway milling", 12), ("滚齿 Gear hobbing", 35), ("零件检验 Part inspection", 8)],
    "RT-棒料齿轮 Bar-stock pinion": [
        ("下料 Sawing", 3), ("粗车 Rough turning", 12), ("精车 Finish turning", 10),
        ("铣键槽 Keyway milling", 10), ("滚齿 Gear hobbing", 20), ("渗碳淬火 Carburizing", 15),
        ("零件检验 Part inspection", 6)],
    "RT-箱体零件 Housing part": [
        ("铣结合面 Face milling", 25), ("钻攻螺纹孔 Drilling & tapping", 20),
        ("零件检验 Part inspection", 5)],
    "RT-箱体合镗 Housing line-boring": [
        ("合箱钻铰销孔 Pin-hole reaming", 15), ("镗轴承孔 Bearing-bore boring", 45),
        ("零件检验 Part inspection", 20)],
    "RT-部件装配 Shaft sub-assembly": [
        ("部件装配 Sub-assembly", 15), ("零件检验 Part inspection", 5)],
    "RT-总装 Final assembly": [
        ("总装 Final assembly", 45), ("跑合试验 Run-in test", 30),
        ("出厂检验 Final inspection", 10), ("清洗包装 Cleaning & packing", 10)],
}

# 物料清单：父项: (工艺路线, [(子项, 用量)])，按从下到上的顺序排列
BOMS = {
    "SH-101": ("RT-齿轮轴 Pinion shaft", [("RM-20CR-D60", 5.2)]),
    "SH-201": ("RT-轴 Shaft (45 steel)", [("RM-45-D50", 3.3)]),
    "SH-301": ("RT-轴 Shaft (45 steel)", [("RM-45-D50", 2.8)]),
    "GR-202": ("RT-锻坯齿轮 Forged gear", [("RM-40CR-F155", 1)]),
    "GR-203": ("RT-棒料齿轮 Bar-stock pinion", [("RM-20CR-D70", 1.8)]),
    "GR-302": ("RT-锻坯齿轮 Forged gear", [("RM-40CR-F225", 1)]),
    "HSG-001": ("RT-箱体零件 Housing part", [("RM-HT200-BASE", 1)]),
    "HSG-002": ("RT-箱体零件 Housing part", [("RM-HT200-COVER", 1)]),
    "SA-000": ("RT-箱体合镗 Housing line-boring", [
        ("HSG-001", 1), ("HSG-002", 1), ("PIN-8x35", 2),
        ("BOLT-M12x110", 6), ("NUT-M12", 6), ("WASHER-12", 6)]),
    "SA-100": ("RT-部件装配 Shaft sub-assembly", [
        ("SH-101", 1), ("BRG-6205", 2), ("KEY-6x6x25", 1)]),
    "SA-200": ("RT-部件装配 Shaft sub-assembly", [
        ("SH-201", 1), ("GR-202", 1), ("GR-203", 1), ("KEY-10x8x28", 2), ("BRG-6206", 2)]),
    "SA-300": ("RT-部件装配 Shaft sub-assembly", [
        ("SH-301", 1), ("GR-302", 1), ("KEY-12x8x45", 1), ("KEY-8x7x36", 1), ("BRG-6207", 2)]),
    "WQR-105": ("RT-总装 Final assembly", [
        ("SA-000", 1), ("SA-100", 1), ("SA-200", 1), ("SA-300", 1),
        ("CAP-52-T", 1), ("CAP-52-B", 1), ("CAP-62-B", 2), ("CAP-72-T", 1), ("CAP-72-B", 1),
        ("SEAL-20", 1), ("SEAL-30", 1), ("BOLT-M8x25", 24), ("SEALANT", 0.05),
        ("OIL-CKC220", 2.5), ("PLUG-M16", 1), ("VENT-M16", 1), ("GAUGE-M12", 1)]),
}


# ---------------------------------------------------------------- 质量检验
def _num(name, lo, hi):
    return {"parameter": name, "numeric": 1, "min": lo, "max": hi}


def _text(name, value):
    return {"parameter": name, "numeric": 0, "value": value}


def inspection_templates():
    k1, w1lo, w1hi = gear_w("SH-101", -0.05, -0.10)
    k2, w2lo, w2hi = gear_w("GR-202", -0.05, -0.12)
    k3, w3lo, w3hi = gear_w("GR-203", -0.05, -0.12)
    k4, w4lo, w4hi = gear_w("GR-302", -0.06, -0.14)
    a1 = center_distance(2, 24, 72)
    a2 = center_distance(3, 20, 70)
    n_out = INPUT_SPEED_RPM / ratio()
    return {
        "进货检验-轴承": [
            _text("轴承外观与转动 Bearing appearance", "无锈蚀、转动灵活无卡滞"),
            _num("轴承内径偏差 Bore deviation (μm)", -10, 0)],
        "进货检验-铸件": [
            _text("铸件外观 Casting appearance", "无砂眼、气孔、裂纹"),
            _num("铸件硬度 Casting hardness (HB)", 170, 240)],
        "进货检验-锻坯": [
            _text("锻坯外观 Forging appearance", "无折叠、裂纹"),
            _num("锻坯硬度 Forging hardness (HB)", 179, 229)],
        "零件检验-输入齿轮轴": [
            _num("轴承位直径 Bearing seat Ø25 k6 (mm)", 25.002, 25.015),
            _num("公法线长度 W{} Span measurement (mm)".format(k1), w1lo, w1hi),
            _num("齿面硬度 Tooth hardness (HRC)", 58, 62)],
        "零件检验-中间轴": [
            _num("轴承位直径 Bearing seat Ø30 k6 (mm)", 30.002, 30.015),
            _num("齿轮位直径 Gear seat Ø35 k6 (mm)", 35.002, 35.018),
            _num("键槽宽 Keyway 10 N9 (mm)", 9.964, 10.000),
            _num("轴承位粗糙度 Roughness Ra (μm)", 0, 0.8),
            _num("调质硬度 Hardness (HB)", 217, 255)],
        "零件检验-输出轴": [
            _num("轴承位直径 Bearing seat Ø35 k6 (mm)", 35.002, 35.018),
            _num("齿轮位直径 Gear seat Ø40 k6 (mm)", 40.002, 40.018),
            _num("键槽宽 Keyway 12 N9 (mm)", 11.957, 12.000),
            _num("轴承位粗糙度 Roughness Ra (μm)", 0, 0.8),
            _num("调质硬度 Hardness (HB)", 217, 255)],
        "零件检验-大齿轮z72": [
            _num("齿轮孔径 Bore Ø35 H7 (mm)", 35.000, 35.025),
            _num("公法线长度 W{} Span measurement (mm)".format(k2), w2lo, w2hi),
            _num("齿面硬度 Tooth hardness (HB)", 241, 286)],
        "零件检验-小齿轮z20": [
            _num("齿轮孔径 Bore Ø35 H7 (mm)", 35.000, 35.025),
            _num("公法线长度 W{} Span measurement (mm)".format(k3), w3lo, w3hi),
            _num("齿面硬度 Tooth hardness (HRC)", 58, 62)],
        "零件检验-大齿轮z70": [
            _num("齿轮孔径 Bore Ø40 H7 (mm)", 40.000, 40.025),
            _num("公法线长度 W{} Span measurement (mm)".format(k4), w4lo, w4hi),
            _num("齿面硬度 Tooth hardness (HB)", 241, 286)],
        "零件检验-箱体": [
            _num("输入轴承孔 Bore Ø52 H7 (mm)", 52.000, 52.030),
            _num("第一级中心距 Centre distance a1 (mm)", round(a1 - 0.027, 3), round(a1 + 0.027, 3)),
            _num("第二级中心距 Centre distance a2 (mm)", round(a2 - 0.032, 3), round(a2 + 0.032, 3)),
            _num("轴承孔平行度 Bore parallelism (mm)", 0, 0.02)],
        "出厂检验-减速器": [
            _text("空载运转 No-load running", "平稳无冲击、无异响"),
            _num("空载噪声 Noise dB(A)", 0, 75),
            _num("油温温升 Oil temperature rise (K)", 0, 40),
            _num("输出转速 Output speed at 1450 r/min in (r/min)",
                 round(n_out * 0.98, 1), round(n_out * 1.02, 1)),
            _text("渗漏检查 Leak check", "各结合面及油封无渗漏")],
    }


# 教学情景（实验 7）开始时的关键物料库存：仿真器的库存快照、模拟 ERPNext 的重置，以及线上真 ERPNext 安装时
# （seed.py --teach-stock）都用这一份，三处一致
TEACH_STOCK = {"RM-45-D50": 60, "BRG-6205": 14, "BRG-6206": 16, "BRG-6207": 8, "SEAL-20": 12, "SEAL-30": 11,
               "RM-40CR-F225": 4, "RM-40CR-F155": 6, "OIL-CKC220": 46, "RM-20CR-D60": 40, "RM-20CR-D70": 30}

# 期初库存（可选，seed.py --opening-stock）：只放小五金和油品，关键物料留给 MRP 去采购
OPENING_STOCK = {
    "BOLT-M12x110": 60, "NUT-M12": 60, "WASHER-12": 60, "BOLT-M8x25": 240, "PIN-8x35": 20,
    "KEY-6x6x25": 10, "KEY-8x7x36": 10, "KEY-10x8x28": 20, "KEY-12x8x45": 10,
    "PLUG-M16": 10, "VENT-M16": 10, "GAUGE-M12": 10, "OIL-CKC220": 25, "SEALANT": 0.5,
}
