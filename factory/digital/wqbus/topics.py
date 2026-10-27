# -*- coding: utf-8 -*-
"""主题命名：wq/<工厂>/<区域>/<单元>/<类别>（附录 A.1）。"""

ROOT = "wq/gearbox"
AREAS = ("office", "design", "machining", "quality", "warehouse", "logistics", "ai", "field")

# 单元代号 → (区域, 中文名, 英文名, 工厂数据里的工作中心名)
UNITS = {
    "saw-01":    ("machining", "带锯床", "Band saw", "带锯床 SAW-01"),
    "cnc-l01-a": ("machining", "数控车床 A", "CNC lathe A", "数控车床 CNC-L01"),
    "cnc-l01-b": ("machining", "数控车床 B", "CNC lathe B", "数控车床 CNC-L01"),
    "vmc-01":    ("machining", "立式加工中心", "Vertical machining centre", "立式加工中心 VMC-01"),
    "hmc-01":    ("machining", "卧式加工中心", "Horizontal machining centre", "卧式加工中心 HMC-01"),
    "key-01":    ("machining", "键槽铣床", "Keyway miller", "键槽铣床 KEY-01"),
    "hob-01":    ("machining", "滚齿机", "Gear hobber", "滚齿机 HOB-01"),
    "ht-01":     ("machining", "热处理炉", "Heat-treat furnace", "热处理炉 HT-01"),
    "grd-01":    ("machining", "外圆磨床", "Cylindrical grinder", "外圆磨床 GRD-01"),
    "asm-01":    ("machining", "装配工位", "Assembly station", "装配工位 ASM-01"),
    "test-01":   ("machining", "跑合试验台", "Run-in test rig", "跑合试验台 TEST-01"),
    "qc-01":     ("quality", "检验站", "Inspection station", "检验站 QC-01"),
    "agv-01":    ("logistics", "物流小车 1", "AGV 1", None),
    "agv-02":    ("logistics", "物流小车 2", "AGV 2", None),
    "store-01":  ("warehouse", "原料库", "Raw store", None),
    "store-02":  ("warehouse", "成品库", "Finished store", None),
    # 《PLC 原理及实践》（第 18 轮第 8 步）：由虚拟 PLC 控制的两台设备，学生的 PLC 程序在这里跑一个班次
    "press-01":  ("machining", "轴承压装工位", "Bearing press-fit station", None),
    "sort-01":   ("warehouse", "成品分拣线", "Finished-part sorting line", None),
}
# 虚拟 PLC 控制的设备 → 虚拟设备模型（学习平台 labkit/plants.js 里的名字）
PLC_UNITS = {"press-01": "press", "sort-01": "sorter"}
try:                                   # 工厂清单（第 30 轮；freecad-ai-parts ADR-0064）：有就用清单里的设备
    from factory import plant as _plant
    _P = _plant.active()
except ImportError:                    # 单独用总线库时（没有 factory 包）
    if __import__("os").environ.get("WQ_PLANT_FILE"):   # 指定了清单却找不到 factory 包：不能悄悄用演示工厂
        raise
    _P = None
if _P:
    UNITS = _P["UNITS"]
    PLC_UNITS = _P["PLC_UNITS"]
UNIT_AREA = {u: v[0] for u, v in UNITS.items()}
# 看板“车间实况”里显示的 12 台加工与检验设备（顺序即显示顺序）
MACHINES = ("saw-01", "cnc-l01-a", "cnc-l01-b", "vmc-01", "hmc-01", "key-01",
            "hob-01", "ht-01", "grd-01", "qc-01", "asm-01", "test-01")
if _P:
    MACHINES = _P["MACHINES"]

CATEGORIES = ("status", "event", "cmd", "cmd/ack", "measurement", "ncr", "release", "gcode",
              "alert", "briefing", "proposal", "torque", "telemetry", "snapshot", "energy")
RETAINED = ("status", "briefing")


def topic(*parts):
    """topic("machining", "grd-01", "status") → wq/gearbox/machining/grd-01/status"""
    return "/".join((ROOT,) + tuple(str(p) for p in parts if p not in (None, "")))


def unit_topic(unit, category):
    return topic(UNIT_AREA[unit], unit, category)


def split(t):
    """把主题拆成 dict：area / unit / category；ai 与 office/erp 这类两级、三级主题也能拆。"""
    if not t.startswith(ROOT + "/"):
        raise ValueError("不是本工厂的主题：" + t)
    rest = t[len(ROOT) + 1:].split("/")
    area = rest[0]
    if area == "ai":
        return {"area": "ai", "unit": None, "category": rest[1] if len(rest) > 1 else None}
    unit = rest[1] if len(rest) > 1 else None
    category = "/".join(rest[2:]) if len(rest) > 2 else None
    return {"area": area, "unit": unit, "category": category}


def qos_for(t):
    return 0 if "/logistics/" in t and t.endswith("/status") else 1


def is_retained(t):
    return any(t.endswith("/" + c) for c in RETAINED)
