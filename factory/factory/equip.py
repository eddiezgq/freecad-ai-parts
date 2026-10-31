# -*- coding: utf-8 -*-
"""设备的维护、能耗数据（第 59 轮）：清单里写了产品的厂（机器人厂等）打开“设备维护、能源、经营财务”时，每台设备的
原值、保养、可靠性（威布尔）、功率从这里来。

- 每台设备先按**类别**取缺省值（示例值，不对应任何真实设备）：类别按设备编号的前缀认（saw 锯床、cnc 车床、vmc/hmc 加工中心、grd 磨床……），
  认不出的按“通用设备”；
- 清单里这台设备写了 `maint`（原值、购入年、保养内容和时长、修理费、停机每小时损失、威布尔参数）或 `power_kw`（运行、空转、待机）就用清单的；
- 演示工厂（减速器厂）不走这里：它的数在 sim/reliability.py、sim/energy.py、hub/maint.py、hub/energy.py 里原样不动。
只做查表，不联网、不读数据库。"""

# 类别：编号前缀 → 类别名（先长后短，按顺序认）
PREFIX = (("saw", "saw"), ("cnc", "lathe"), ("vmc", "mc"), ("hmc", "mc"), ("grd", "grinder"), ("cmm", "cmm"), ("qc", "cmm"),
          ("ja", "assembly"), ("asm", "assembly"), ("ra", "assembly"), ("aa", "assembly"), ("jt", "bench"), ("test", "bench"),
          ("cal", "calib"), ("run", "runin"), ("at", "agvtest"))

# 类别缺省（示例值）：原值 $、购入年、保养内容、保养分钟、一次修理费 $、停机每小时损失 $、
# 威布尔 β、η 运行小时、平均修复分钟、保养周期 运行小时、开始时已运行小时、故障模式 [(代码, 名称)]、功率 (运行, 空转, 待机) kW、
# 用压缩空气、湿式加工（出油雾）、噪声 dB(A)、自动设备（不按班次关机）
KIND = {
    "saw": dict(name="锯床", value=18000, bought=2021, pm_text="换液压油、查锯条张紧", pm_min=120, repair_usd=400, lost_per_h=60,
                beta=2.0, eta_h=1600, mttr_min=120, pm_h=800, init_h=300, modes=[("blade", "锯条断裂"), ("hyd", "液压进给漏油")],
                power=(7.5, 2.0, 0.3), air=False, wet=False, noise=80, auto=False, check=["锯条张紧适当"]),
    "lathe": dict(name="数控车床", value=65000, bought=2022, pm_text="换主轴润滑脂、查刀塔定位、清冷却箱", pm_min=120, repair_usd=700,
                  lost_per_h=80, beta=2.5, eta_h=1400, mttr_min=240, pm_h=600, init_h=380,
                  modes=[("spindle", "主轴轴承异响"), ("turret", "刀塔定位失准")], power=(15.0, 5.0, 0.6), air=True, wet=True, noise=74,
                  auto=False, check=["卡盘夹紧可靠"]),
    "mc": dict(name="加工中心", value=110000, bought=2023, pm_text="换主轴润滑脂、查导轨", pm_min=120, repair_usd=800, lost_per_h=100,
               beta=2.5, eta_h=1500, mttr_min=240, pm_h=600, init_h=250, modes=[("spindle", "主轴轴承异响"), ("atc", "换刀机构卡刀")],
               power=(15.0, 5.0, 0.6), air=True, wet=True, noise=74, auto=False, check=["刀库、换刀动作正常"]),
    "grinder": dict(name="磨床", value=120000, bought=2021, pm_text="换液压油、查主轴轴承、校砂轮平衡", pm_min=180, repair_usd=1200,
                    lost_per_h=150, beta=3.0, eta_h=900, mttr_min=480, pm_h=500, init_h=420,
                    modes=[("spindle", "主轴轴承异响"), ("hyd", "液压系统漏油"), ("balance", "砂轮不平衡、振纹")],
                    power=(11.0, 4.0, 0.5), air=True, wet=True, noise=78, auto=False, check=["砂轮无裂纹、防护罩紧固", "液压油位、油温正常"]),
    "cmm": dict(name="测量设备", value=90000, bought=2023, pm_text="校测头、查气浮导轨", pm_min=120, repair_usd=600, lost_per_h=60,
                beta=2.0, eta_h=3000, mttr_min=120, pm_h=1000, init_h=350, modes=[("probe", "测头失准")],
                power=(2.0, 1.0, 0.2), air=True, wet=False, noise=60, auto=True, check=["测头标定在有效期内", "室温 20 ± 1 ℃"]),
    "assembly": dict(name="装配工位", value=25000, bought=2023, pm_text="校电动扳手扭矩、查压装机", pm_min=90, repair_usd=400, lost_per_h=80,
                     beta=2.0, eta_h=3000, mttr_min=90, pm_h=1000, init_h=400, modes=[("tool", "电动扳手扭矩超差")],
                     power=(3.0, 1.0, 0.2), air=True, wet=False, noise=68, auto=False, check=["扭矩扳手校准在有效期内"]),
    "bench": dict(name="测试台", value=60000, bought=2023, pm_text="校扭矩、编码器和电流传感器", pm_min=120, repair_usd=600, lost_per_h=80,
                  beta=2.0, eta_h=2500, mttr_min=150, pm_h=1000, init_h=500, modes=[("sensor", "扭矩传感器漂移")],
                  power=(8.0, 1.5, 0.3), air=False, wet=False, noise=70, auto=True, check=["传感器校准在有效期内"]),
    "calib": dict(name="标定工位", value=150000, bought=2024, pm_text="激光跟踪仪自检、校靶球", pm_min=120, repair_usd=900, lost_per_h=100,
                  beta=2.0, eta_h=3000, mttr_min=180, pm_h=1000, init_h=300, modes=[("tracker", "激光跟踪仪测距超差")],
                  power=(2.5, 1.0, 0.2), air=False, wet=False, noise=62, auto=True, check=["跟踪仪自检通过", "靶球清洁"]),
    "runin": dict(name="跑合台", value=50000, bought=2023, pm_text="查负载加载机构、校电流采集", pm_min=120, repair_usd=600, lost_per_h=80,
                  beta=2.0, eta_h=2500, mttr_min=150, pm_h=1000, init_h=450, modes=[("load", "负载加载机构卡滞")],
                  power=(12.0, 1.5, 0.3), air=False, wet=False, noise=72, auto=True, check=["负载夹具紧固"]),
    "agvtest": dict(name="调试场地", value=20000, bought=2023, pm_text="查充电桩、校定位标签", pm_min=60, repair_usd=300, lost_per_h=50,
                    beta=2.0, eta_h=3000, mttr_min=90, pm_h=1000, init_h=300, modes=[("charger", "充电桩故障")],
                    power=(4.0, 0.8, 0.2), air=False, wet=False, noise=62, auto=True, check=["场地标签完好"]),
    "general": dict(name="通用设备", value=20000, bought=2022, pm_text="例行保养", pm_min=120, repair_usd=400, lost_per_h=60,
                    beta=2.0, eta_h=2000, mttr_min=120, pm_h=800, init_h=300, modes=[("general", "设备故障")],
                    power=(5.0, 1.5, 0.3), air=False, wet=False, noise=70, auto=False, check=[]),
}
MAINT_KEYS = ("value", "bought", "pm_text", "pm_min", "repair_usd", "lost_per_h", "beta", "eta_h", "mttr_min", "pm_h", "init_h")


def kind_of(uid):
    for pre, k in PREFIX:
        if uid.startswith(pre) and (len(uid) == len(pre) or not uid[len(pre)].isalpha()):
            return k
    return "general"


def validate_unit(at, u):
    """清单里一台设备的 maint、power_kw（可选）"""
    errs = []
    m = u.get("maint")
    if m is not None:
        if not isinstance(m, dict):
            return ["{}.maint：要是 {{原值 value, 购入年 bought, …}}".format(at)]
        for k, v in m.items():
            if k not in MAINT_KEYS:
                errs.append("{}.maint.{}：不认识的字段（可写 {}）".format(at, k, "、".join(MAINT_KEYS)))
            elif k == "pm_text":
                if not (isinstance(v, str) and v):
                    errs.append("{}.maint.pm_text：保养内容要写文字".format(at))
            elif not (isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0):
                errs.append("{}.maint.{}：要是正数".format(at, k))
    pw = u.get("power_kw")
    if pw is not None and not (isinstance(pw, list) and len(pw) == 3 and all(isinstance(x, (int, float)) and x >= 0 for x in pw)):
        errs.append("{}.power_kw：[运行, 空转, 待机] kW".format(at))
    return errs


def profiles(units):
    """清单的 units 列表 → {设备编号: 合并后的数据}；只取车间里的设备（有工作站的）"""
    out = {}
    for u in units:
        if not u.get("workstation"):
            continue
        k = kind_of(u["id"])
        d = dict(KIND[k], kind=k, name=u["name"])
        d.update(u.get("maint") or {})
        if u.get("power_kw"):
            d["power"] = tuple(u["power_kw"])
        d["modes"] = [tuple(x) for x in d["modes"]]
        d["check"] = list(d["check"])
        out[u["id"]] = d
    return out


def active():
    """当前工厂（清单里写了产品、又不是演示工厂）的设备数据；演示工厂或没有清单时 None"""
    try:
        from factory import plant
    except ImportError:
        return None
    p = plant.active()
    if not p or p["DEMO_DATA"] or not p.get("ITEMS"):
        return None
    return p.get("EQUIP")
