"""加工误差模型与问题情景（第 13 轮 7.3（4）N6；教材第 54、58 章）。

仿真车间的三坐标测量值不是随手加的噪声，而是由误差源合成的：
- 正常状态：随机误差（重复性）+ 砂轮磨损引起的尺寸逐件上移（换砂轮后回落）——这是原有的模型，数值不变；
- 问题情景：老师在教学模式下注入一个“隐藏的问题”，它按真实的机理改变某几个特性的测量值，学生只能从数据里找原因：

  | 情景 | 机理 | 数据上的表现 |
  |---|---|---|
  | 磨床尾座偏移 | 两顶尖连线与工作台导轨不平行，工件轴线偏斜 e（mm，在尾座端） | 右轴承位比左轴承位系统性偏大（锥度），齿轮位居中 |
  | 砂轮修整间隔过长 | 砂轮钝化后磨削力增大、让刀增加 | 轴承位直径逐件上移的斜率变为约 2.5 倍，修整前出界 |
  | 磨床未预热 | 砂轮架热伸长，开机后数十分钟内向工件方向移动 | 开机后直径逐件变小，约 15 件后稳定在偏小处 |
  | 键槽夹具定位元件磨损 | V 形块与轴向挡板磨损，工件轴线偏离铣刀中心 | 键槽对称度均值上升、分散变大，部分超 0.02 |
  | 中心孔质量差 | 中心孔有毛刺、圆度差，磨削时回转中心跳动 | 轴承位径向圆跳动增大，部分超 0.012；直径分散略增 |
  | 砂轮修整不锋利（第 55 章） | 金刚石笔磨钝，砂轮磨粒磨平面积大，比磨削能与磨削温度升高 | 每个修整周期的后几件轴承位烧伤（酸洗检出）；Ra 略增但仍合格 |

学生在质量异常单上做 8D：原因分析后选择纠正措施；措施经老师批准下发后（apply_fix），只有对症的措施能让问题消失，
后续零件的数据随之恢复——这就是 8D 第 6 步“验证措施有效”的数据来源。
"""
from __future__ import annotations

import math
import zlib
import random

# 输出轴 SH-301 的三坐标检验特性：(代号, 名称, 名义, 下限, 上限)
# 前三项与工厂数据检验模板“零件检验-输出轴”相同（进 ERPNext 质量检验单）；后三项是第 13 轮补的图纸特性（C1 右轴承位、C7、C6），只进质量系统
CHARS = [
    ("bearing_seat_d35", "轴承位直径 Ø35 k6（左）", 35.010, 35.002, 35.018),
    ("gear_seat_d40", "齿轮位直径 Ø40 k6", 40.010, 40.002, 40.018),
    ("keyway_width_12", "键槽宽 12 N9", 11.9785, 11.957, 12.000),
    ("bearing_seat_d35_r", "轴承位直径 Ø35 k6（右）", 35.010, 35.002, 35.018),
    ("runout_bearing", "轴承位径向圆跳动（A–B）", 0.004, 0.0, 0.012),
    ("keyway_sym", "键槽对称度", 0.006, 0.0, 0.020),
    # 第 13 轮十一（第 55 章）：工序 60 的表面质量——粗糙度（µm，检验卡 C10）和酸洗检查磨削烧伤（0 无、1 有）
    ("ra_bearing", "轴承位表面粗糙度 Ra（µm）", 0.5, 0.0, 0.8),
    ("burn_bearing", "轴承位磨削烧伤（酸洗：0 无、1 有）", 0.0, 0.0, 0.0),
]
# 工序 60 精磨的参数（工艺规程第 263 行：砂轮 35 m/s、工件 20 m/min、横进给 0.005 mm/行程、光磨 2 次；工件 Ø35、砂轮 Ø400）
GRIND = {"vs": 35.0, "vw": 20 / 60, "ap": 0.005, "sparkout": 2, "dw": 35.0, "ds": 400.0, "mat": "45-QT"}

# 轴向位置（mm，从左端面）：左轴承位中点、齿轮位中点、右轴承位中点；总长 L
Z_LEFT, Z_GEAR, Z_RIGHT, LENGTH = 46.0, 82.0, 124.5, 167.0

PROBLEMS = {
    "tailstock_offset": {"name": "磨床尾座偏移（锥度）", "unit": "grd-01", "fix": "align_tailstock", "default": 0.008},
    "dressing_interval": {"name": "砂轮磨损加快（砂轮偏软或修整不良，尺寸漂移加快）", "unit": "grd-01", "fix": "shorten_dressing", "default": 2.5},
    "thermal_warmup": {"name": "磨床未预热（开机后尺寸逐件变小）", "unit": "grd-01", "fix": "warm_up", "default": 0.010},
    "locator_worn": {"name": "键槽夹具定位元件磨损（对称度超差）", "unit": "key-01", "fix": "replace_locator", "default": 0.012},
    "center_hole": {"name": "中心孔质量差（圆跳动超差）", "unit": "grd-01", "fix": "lap_center_holes", "default": 0.006},
    # 第 55 章：金刚石笔磨钝，修整后砂轮仍不锋利、磨粒磨平面积大（hub/surface.py：比磨削能和磨削温度升高）
    "wheel_dull": {"name": "砂轮修整不锋利（金刚石笔磨钝：磨削温度升高，轴承位烧伤）", "unit": "grd-01", "fix": "sharp_dressing", "default": 2.5},
}

# 机器人厂（清单 wenquest-robot，第 47 轮实验 25）：关节测试台的数据。“plant” 标出属于哪座厂，质量页、8D 只列本厂的
# 偏差量、批次大小都是示例值
ROBOT = "wenquest-robot"
PROBLEMS.update({
    "ja_torque": {"name": "关节装配工位 JA-2 预紧扭矩偏低（这个工位装的关节背隙偏大）", "unit": "ja-2", "fix": "recalibrate_torque",
                  "default": 0.35, "plant": ROBOT},
    "hd_lot": {"name": "谐波减速器来料批次背隙偏大（从注入时的批次起）", "unit": "ja-*", "fix": "quarantine_lot",
               "default": 0.40, "plant": ROBOT},
    "bench_zero": {"name": "关节测试台零位标定程序漂移（零位残差逐台偏移）", "unit": "jt-1", "fix": "recalibrate_bench",
                   "default": 1.5, "plant": ROBOT},
    # 第 120 轮：B 版驱动板带来的两项测量（抱闸保持力矩、双编码器互检差）各配一个问题（偏差量都是示例值）
    "enc_mount": {"name": "关节装配工位 JA-1 编码器定位工装磨损（这个工位装的关节输出端编码器偏心，双编码器互检差偏大）", "unit": "ja-1",
                  "fix": "recenter_encoder", "default": 4.0, "plant": ROBOT},
    "brake_bench": {"name": "关节测试台抱闸扭矩传感器漂移（保持力矩读数一台比一台低，抱闸其实是好的）", "unit": "jt-1",
                    "fix": "recalibrate_brake_bench", "default": 2.0, "plant": ROBOT},
})
BRAKE_NOMINAL = {"L": 220.0, "M": 110.0, "S": 55.0}      # 关节测试的抱闸保持力矩名义值 N·m（与清单一致，第 118 轮）
# 电路板厂（清单 wenquest-pcb，第 85 轮）：SMT 线和功能测试的数据。机理与表现（偏差量、批次大小都是示例值）：
#   钢网堵孔：印刷次数多了开孔被锡膏糊住 → 锡膏体积逐块下降（约 20 块后接近下限）→ AOI 少锡缺陷增多
#   回流炉温漂：加热器老化、热电偶漂移 → 峰值温度、液相线以上时间逐渐下降 → 冷焊风险（峰值低于 235 ℃）
#   多功能贴片机 PP-2 吸嘴磨损：吸取偏心 → 只有 PP-2 贴的 IC 与 MOSFET 偏移变大（片式元件正常）→ AOI 偏移缺陷
#   采样电阻来料批次超差：从注入时正在用的那一卷起阻值偏大 → ICT 阻值、FCT 相电流采样误差偏大（只在驱动板上）
PCB = "wenquest-pcb"
PROBLEMS.update({
    "stencil_clog": {"name": "钢网堵孔（锡膏体积逐块下降、少锡）", "unit": "sp-1", "fix": "wipe_stencil", "default": 35.0, "plant": PCB},
    "reflow_drift": {"name": "回流炉温漂（峰值温度逐渐下降、冷焊风险）", "unit": "rf-1", "fix": "profile_oven", "default": 14.0, "plant": PCB},
    "nozzle_wear": {"name": "多功能贴片机 PP-2 吸嘴磨损（只有它贴的 IC 偏移变大）", "unit": "pp-2", "fix": "replace_nozzle", "default": 40.0, "plant": PCB},
    "shunt_lot": {"name": "采样电阻来料批次阻值偏大（从注入时的那一卷起）", "unit": "ict-1", "fix": "quarantine_shunt", "default": 2.5, "plant": PCB},
})
# 芯片封测厂（清单 wenquest-chip，第 103 轮）：机理与表现（偏差量都是示例值，按“晶圆批”计数）：
#   探针卡磨损：探针台 prb-1 的 8 个测试位里第 6 位（示例）的探针接触电阻逐片升高 → 这个测试位扎到的芯片被误判开路（晶圆图上一格一格规律地红）
#     → CP 良率下降；芯片本身是好的，FT 不受影响（误判的好芯片在 CP 就被打掉了，白白损失）
#   划片刀磨损：划片机 dc-1 崩边逐批增大 → 抽检崩边超 25 µm、FT 良率略降
#   劈刀磨损：只有键合机 wb-2 键合的批次拉力、推力逐批下降（wb-1 正常）→ 拉力低于 3 gf
#   塑封料受潮：从注入起塑封机 mld-1 用的塑封料吸潮 → 塑封空洞率升高
CHIP = "wenquest-chip"
PROBLEMS.update({
    "probe_wear": {"name": "探针卡磨损（第 6 个测试位接触电阻逐片升高、误判开路）", "unit": "prb-1", "fix": "clean_probe", "default": 2.5, "plant": CHIP},
    "blade_wear": {"name": "划片刀磨损（崩边逐批增大）", "unit": "dc-1", "fix": "replace_blade", "default": 18.0, "plant": CHIP},
    "capillary_wear": {"name": "键合机 wb-2 劈刀磨损（只有它键合的批次拉力下降）", "unit": "wb-2", "fix": "replace_capillary", "default": 3.5, "plant": CHIP},
    "emc_moisture": {"name": "塑封料受潮（空洞率升高）", "unit": "mld-1", "fix": "emc_handling", "default": 3.0, "plant": CHIP},
})
# 传感器厂（清单 wenquest-sensor，第 125 轮）：机理与表现（偏差量都是示例值，按“台”计数）：
#   对心夹具磨损：只有粘接对心机 cb-2 粘的码盘偏心逐台变大 → 一次谐波（每圈一个起伏）变大、精度超差（cb-1 正常）
#   间隙塞规磨损：读头装调台 hm-1 用磨薄的塞规调间隙 → 间隙偏大、信号幅值下降、细分误差变大
#   洁净间过滤器堵塞：码盘清洗台 dcl-1 那一段洁净度下降 → 码盘上落污点 → 误差曲线某处尖峰、幅值掉坑
#   固化炉温度偏低：固化炉 cur-1 → 应变胶没固化透 → 扭矩传感器蠕变、滞后、零点温漂变大
SENSOR = "wenquest-sensor"
PROBLEMS.update({
    "fixture_wear": {"name": "粘接对心机 cb-2 对心夹具磨损（只有它粘的码盘偏心变大）", "unit": "cb-2", "fix": "replace_fixture", "default": 2.5, "plant": SENSOR},
    "gap_gauge": {"name": "读头装调台间隙塞规磨损（间隙偏大、信号幅值下降）", "unit": "hm-1", "fix": "replace_gap_gauge", "default": 30.0, "plant": SENSOR},
    "ffu_clog": {"name": "洁净间过滤器堵塞（码盘落污点）", "unit": "dcl-1", "fix": "replace_ffu", "default": 3.0, "plant": SENSOR},
    "cure_low": {"name": "应变胶固化炉温度偏低（扭矩传感器蠕变、滞后变大）", "unit": "cur-1", "fix": "profile_cure", "default": 1.0, "plant": SENSOR},
})
PROBE_SITE = 5               # 磨损的测试位（0 起数，页面上显示第 6 位；示例）
SHUNT_LOT = 30               # 采样电阻每卷用于 30 块驱动板（示例）：按测试顺序依次用掉；仓库有到货批次时用到货批次
LOT_SIZE = 8                 # 谐波减速器每批 8 台（示例）：关节按装配顺序依次用掉。第 51 轮：仓库有真实到货批次时用到货批次（add_lot）

# 8D 第 5 步可选的纠正措施（含几项“看起来有道理但不对症”的措施）
FIXES = {
    "align_tailstock": "校正磨床尾座，使两顶尖连线与导轨平行（用标准检验棒和千分表）",
    "shorten_dressing": "缩短砂轮修整间隔（每 5 件修整一次）",
    "warm_up": "开机空运转预热 20 min，首件合格后再批量磨削",
    "replace_locator": "更换键槽铣夹具的 V 形块与轴向挡板，并重新对刀",
    "lap_center_holes": "磨前修研中心孔、检查并更换磨损的顶尖",
    "sharp_dressing": "更换磨钝的金刚石笔，按工艺卡的修整用量锋利修整砂轮",
    "change_wheel": "更换砂轮牌号（改用更软的砂轮）",
    "reduce_feed": "减小磨削横向进给量",
    "retrain": "培训操作工，加强自检",
    "change_gauge": "更换并重新校准检验量具",
    # 机器人厂（第 47 轮）
    "recalibrate_torque": "校准关节装配工位 JA-2 的电动扭力扳手，按工艺文件复核预紧扭矩",
    "quarantine_lot": "隔离问题批次的谐波减速器、退回供应商，改用复检合格的批次",
    "recalibrate_bench": "用标准关节重新标定测试台的零位基准，修正标定程序",
    "add_grease": "关节加注润滑脂",
    "tighten_test": "出厂检验收紧，关节 100% 复测",
    # 第 120 轮
    "recenter_encoder": "更换关节装配工位 JA-1 磨损的编码器定位工装，按工艺复核输出端编码器同心度",
    "recalibrate_brake_bench": "用标准扭矩扳手重新标定关节测试台的抱闸扭矩传感器，每班点检",
}
FIXES.update({                # 电路板厂（第 85 轮）
    "wipe_stencil": "清洗钢网、把自动擦网改为每印 5 块擦一次（干擦 + 真空擦）",
    "profile_oven": "用炉温测试板测炉温曲线，校正回流炉各温区设定与热电偶",
    "replace_nozzle": "更换多功能贴片机 PP-2 磨损的吸嘴，做吸嘴中心校正",
    "quarantine_shunt": "隔离这一卷采样电阻、退回供应商，换复检合格的一卷",
    "raise_peak": "把回流炉峰值温度设定提高 5 ℃",
    "replace_squeegee": "更换印刷刮刀、加大刮刀压力",
    "tighten_aoi": "AOI 判定加严，偏移门限收紧",
})
FIXES.update({                # 芯片封测厂（第 103 轮）
    "clean_probe": "清洁探针、量各测试位接触电阻，超出寿命的探针卡换新",
    "replace_blade": "更换划片刀、修刀后首件检查崩边",
    "replace_capillary": "更换键合机 wb-2 的劈刀，首件做拉力、推力试验",
    "emc_handling": "隔离受潮的塑封料批次；按规程回温 ≥ 16 h、开封后 24 h 内用完",
    "retest_cp": "CP 失效的芯片全部复测一遍",
    "raise_bond_power": "加大键合超声功率和压力",
    "tighten_ft": "FT 判定加严",
})
FIXES.update({                # 传感器厂（第 125 轮）
    "replace_fixture": "更换粘接对心机 cb-2 的对心夹具，用标准盘复测对心 ≤ 1 µm",
    "replace_gap_gauge": "更换并校准读头间隙塞规，已装的按信号幅值复查",
    "replace_ffu": "更换洁净间风机过滤单元、测粒子计数，码盘重新清洗",
    "profile_cure": "测固化炉炉温曲线、校温控，没固化透的传感器补固化",
    "redo_comp": "重做精度补偿表（把整圈误差补平）",
    "raise_gain": "加大读头信号增益",
    "tighten_eft": "编码器终检判定加严",
})
ROBOT_FIXES = ("recalibrate_torque", "quarantine_lot", "recalibrate_bench", "add_grease", "tighten_test", "retrain", "change_gauge",
               "recenter_encoder", "recalibrate_brake_bench")
PCB_FIXES = ("wipe_stencil", "profile_oven", "replace_nozzle", "quarantine_shunt", "raise_peak", "replace_squeegee", "tighten_aoi",
             "retrain", "change_gauge")
CHIP_FIXES = ("clean_probe", "replace_blade", "replace_capillary", "emc_handling", "retest_cp", "raise_bond_power", "tighten_ft",
              "retrain", "change_gauge")
SENSOR_FIXES = ("replace_fixture", "replace_gap_gauge", "replace_ffu", "profile_cure", "redo_comp", "raise_gain", "tighten_eft",
                "retrain", "change_gauge")
PLANT_FIXES = {ROBOT: ROBOT_FIXES, PCB: PCB_FIXES, CHIP: CHIP_FIXES, SENSOR: SENSOR_FIXES}


def problems_for(plant_id):
    """这座厂能注入的问题情景：演示工厂（plant_id 为空或 wenquest-gearbox）是输出轴的五种，机器人厂是关节的三种，电路板厂是 SMT 与测试的四种，
    芯片厂是封测的四种"""
    mine = plant_id if plant_id in PLANT_FIXES else None
    return {k: v for k, v in PROBLEMS.items() if v.get("plant") == mine}


def fixes_for(plant_id):
    if plant_id in PLANT_FIXES:
        return {k: FIXES[k] for k in PLANT_FIXES[plant_id]}
    special = {k for v in PLANT_FIXES.values() for k in v} - {"retrain", "change_gauge"}
    return {k: v for k, v in FIXES.items() if k not in special}


SHUNT_ITEM = "RES-SHUNT"
ENC_CODES = ("enc_acc", "enc_h1", "enc_interp", "enc_amp", "enc_amp_min")      # 第 125 轮：由整圈误差曲线算出
TS_CODES = ("ts_nonlin", "ts_hyst", "ts_creep", "ts_tczero")
CHIP_CODES = ("cp_yield", "cp_contact", "chipping", "bond_pull", "ball_shear", "mold_void", "ft_yield")
PCB_CODES = ("spi_volume", "spi_height", "reflow_peak", "reflow_tal", "offset_ic", "aoi_defects", "ict_shunt", "fct_isense")


def _bom_qty(item, code):
    """item 的物料清单里（含下一层的贴片板）用多少 code；没有清单时 0"""
    try:
        from factory import data as F
    except ImportError:
        return 0
    total = 0.0
    for c, q in (F.BOMS.get(item) or ("", []))[1]:
        if c == code:
            total += float(q)
        elif c in F.BOMS:
            total += float(q) * sum(float(q2) for c2, q2 in F.BOMS[c][1] if c2 == code)
    return total


def _uses_shunt(item):
    return _bom_qty(item, SHUNT_ITEM) > 0


def _shunt_per_board(item):
    return _bom_qty(item, SHUNT_ITEM) or 1


def _poisson(rng, lam):
    k, p, L = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def _harmonic_of(item):
    """关节模组用的谐波减速器（物料清单里 HD- 开头的子件）；不是关节或没有清单时 None"""
    try:
        from factory import data as F
    except ImportError:
        return None
    return next((c for c, _ in (F.BOMS.get(item) or ("", []))[1] if str(c).startswith("HD-")), None)


class ErrorModel:
    def __init__(self, seed=None):
        self.rng = random.Random(None if seed is None else seed + 7919)   # 与引擎主随机数分开：不改变原有加工节拍的随机序列
        self.active = {}          # 问题 → {"magnitude": x, "since_part": n, "count": 0}
        self.lot_used = {}        # 机器人厂：每种关节已装了几台（没有到货批次时按顺序用谐波减速器，每 LOT_SIZE 台一批）
        self.lots = {}            # 第 51 轮：仓库里来料检验合格的谐波减速器批次 {物料: [[批号, 剩余数量], …]}，先进先出
        self.lot_order = {}       # 每种规格按开始使用的先后排的批号（判断“从注入时的批次起”）
        self.zero_fifo = {}       # 第 55 轮：关节测试台测得的零位残差（角秒），按规格先进先出装进整机（整机标定的零位偏差从这里来）
        self.fric_fifo = {}       # 第 58 轮：关节测试台测得的空载摩擦力矩（N·m），同样先进先出装进整机（负载跑合台的“实测”力矩从这里来）
        self.history = []         # (事件, 问题或措施, 结果)

    def add_lot(self, item: str, lot: str, qty: float):
        """仓库收下一批（来料检验合格）：装关节时先进先出用掉。同一批号只记一次"""
        q = self.lots.setdefault(str(item), [])
        if not any(x[0] == lot for x in q) and not any(lot in v for v in self.lot_order.values()):
            q.append([str(lot), float(qty)])

    def lot_state(self):
        return {"lot_used": dict(self.lot_used), "lots": {k: [list(x) for x in v] for k, v in self.lots.items()},
                "lot_order": {k: list(v) for k, v in self.lot_order.items()}, "zero_fifo": {k: list(v) for k, v in self.zero_fifo.items()},
                "fric_fifo": {k: list(v) for k, v in self.fric_fifo.items()}}

    def load_lot_state(self, s):
        s = s or {}
        self.lot_used = dict(s.get("lot_used") or {})
        self.lots = {k: [list(x) for x in v] for k, v in (s.get("lots") or {}).items()}
        self.lot_order = {k: list(v) for k, v in (s.get("lot_order") or {}).items()}
        self.zero_fifo = {k: list(v) for k, v in (s.get("zero_fifo") or {}).items()}
        self.fric_fifo = {k: list(v) for k, v in (s.get("fric_fifo") or {}).items()}

    def note_joint_zero(self, item: str, value: float):
        """关节测试台测完一台关节的零位残差：记下，装整机时按规格先进先出取用（第 55 轮）"""
        q = self.zero_fifo.setdefault(str(item)[-1:], [])
        q.append(float(value))
        del q[:-200]

    def note_joint_friction(self, item: str, value: float):
        """关节测试台测完一台关节的空载摩擦力矩：记下，装整机时与零位一起按规格先进先出取用（第 58 轮）"""
        q = self.fric_fifo.setdefault(str(item)[-1:], [])
        q.append(float(value))
        del q[:-200]

    def robot_friction(self, part):
        """装一台协作机器人：J1–J6 的空载摩擦力矩（关节测试台实测）；队列空了的记 None（负载跑合时按名义值与散布补）"""
        from sim import calib
        st = part.err if getattr(part, "err", None) is not None else {}
        if "_fric" not in st:
            st["_fric"] = [(self.fric_fifo.get(sz) or [None]).pop(0) if self.fric_fifo.get(sz) else None for sz in calib.JOINT_SIZE]
            part.err = st
        return st["_fric"]

    def robot_zeros(self, part):
        """装一台协作机器人：按 J1–J6 用的关节规格从先进先出队列里取零位残差；队列空了的那一个记 None（标定时随机补）"""
        from sim import calib
        st = part.err if getattr(part, "err", None) is not None else {}
        if "_zero" not in st:
            st["_zero"] = [(self.zero_fifo.get(sz) or [None]).pop(0) if self.zero_fifo.get(sz) else None for sz in calib.JOINT_SIZE]
            part.err = st
        return st["_zero"]

    def _current(self, size):
        o = self.lot_order.get(size) or []
        return len(o) - 1 if o else 0

    # -------------------------------------------------------------- 老师注入、措施下发
    def inject(self, problem: str, magnitude=None):
        if problem not in PROBLEMS:
            raise KeyError(problem)
        self.active[problem] = {"magnitude": float(magnitude if magnitude is not None else PROBLEMS[problem]["default"]), "count": 0}
        if problem == "shunt_lot":          # 从注入时正在用的那一卷采样电阻起
            o = self.lot_order.get("SH") or []
            self.active[problem]["from_lot"] = {"SH": len(o) - 1 if o else 0}
        if problem == "hd_lot":             # 从注入时正在用的批次起（每种规格各自的批次）都是问题批次，直到隔离
            self.active[problem]["from_lot"] = {k: self._current(k) for k in set(self.lot_order) | set(self.lot_used)}
        self.history.append(("inject", problem, True))

    def clear(self):
        self.active.clear()
        self.history.append(("clear", None, True))

    def apply_fix(self, fix: str) -> list[str]:
        """下发一项纠正措施：对症的问题被消除，返回被消除的问题列表（可能为空——措施不对症）。"""
        if fix not in FIXES:
            raise KeyError(fix)
        gone = [p for p in list(self.active) if PROBLEMS[p]["fix"] == fix]
        for p in gone:
            del self.active[p]
        if fix == "quarantine_lot":         # 隔离问题批次：剩下的这批不用了（到货批次退回供应商），下一台起换新批次
            self.lot_used = {k: -(-n // LOT_SIZE) * LOT_SIZE for k, n in self.lot_used.items()}
            for size, order in self.lot_order.items():
                cur = order[-1] if order else None
                for q in self.lots.values():
                    if q and q[0][0] == cur:
                        q.pop(0)
        if fix == "quarantine_shunt":       # 隔离这一卷：剩下的不用了，下一块起换新的一卷
            self.lot_used["SH"] = -(-self.lot_used.get("SH", 0) // SHUNT_LOT) * SHUNT_LOT
            o = self.lot_order.get("SH") or []
            q = self.lots.get(SHUNT_ITEM)
            if q and o and q[0][0] == o[-1]:
                q.pop(0)
        self.history.append(("fix", fix, bool(gone)))
        return gone

    # -------------------------------------------------------------- 零件经过某台设备时记下当时的状态
    def on_process(self, unit: str, part, wear: float):
        st = getattr(part, "err", None)
        if st is None:
            st = {}
            part.err = st
        if unit.startswith("ja-") and "_ja" not in st:      # 机器人厂关节装配：记下工位和谐波减速器批次（第 47 轮）
            item = str(getattr(getattr(part, "wo", None), "item", "") or "")
            size = item[-1:] or "X"
            hd = _harmonic_of(item)
            q = self.lots.get(hd) if hd else None
            if q:                           # 第 51 轮：仓库里有到货批次，先进先出
                lot = q[0][0]
                q[0][1] -= 1
                if q[0][1] <= 0:
                    q.pop(0)
                part.lots = {hd: lot}
            else:
                n = self.lot_used.get(size, 0)
                self.lot_used[size] = n + 1
                lot = "HD-{}-{:03d}".format(size, n // LOT_SIZE + 1)
            order = self.lot_order.setdefault(size, [])
            if lot not in order:
                order.append(lot)
            st["_ja"] = unit
            st["_lot_no"] = (size, order.index(lot))
            part.hd_lot = lot
        if unit.startswith("wb-") or unit.startswith("cb-"):  # 芯片封测厂（第 103 轮）：哪台键合机；传感器厂（第 125 轮）：哪台粘接对心机（分层用）
            st["_ja"] = unit
        if unit == "ict-1" and "_shunt" not in st and _uses_shunt(str(getattr(getattr(part, "wo", None), "item", "") or "")):
            self._take_shunt(part, st)       # 电路板厂（第 85 轮）：在线测试时认出这块驱动板用的是哪一卷采样电阻
        for p, a in self.active.items():
            u = PROBLEMS[p]["unit"]
            if u == unit or (u == "ja-*" and unit.startswith("ja-")):
                if p == "hd_lot":
                    size, no = st.get("_lot_no", (None, -1))
                    if no < a["from_lot"].get(size, 0):
                        continue
                if p == "shunt_lot":
                    if "_shunt" not in st or st["_shunt"][1] < a["from_lot"].get("SH", 0):
                        continue
                a["count"] += 1
                st[p] = (a["magnitude"], a["count"])
        if unit == "grd-01":
            st["_wear"] = wear
        if str(getattr(getattr(part, "wo", None), "item", "")) == "WQ-CR5" and "_zero" not in st:   # 整机装配：记下装进去的 6 台关节的零位（第 55 轮）
            self.robot_zeros(part)
            self.robot_friction(part)                                       # 和空载摩擦力矩（第 58 轮）

    def _take_shunt(self, part, st):
        """这块驱动板用的采样电阻卷号：仓库里有到货批次时先进先出，没有时按测试顺序每 SHUNT_LOT 块一卷"""
        q = self.lots.get(SHUNT_ITEM)
        if q:
            lot = q[0][0]
            q[0][1] -= _shunt_per_board(str(getattr(getattr(part, "wo", None), "item", "") or ""))
            if q[0][1] <= 0:
                q.pop(0)
        else:
            n = self.lot_used.get("SH", 0)
            self.lot_used["SH"] = n + 1
            lot = "SH-{:03d}".format(n // SHUNT_LOT + 1)
        order = self.lot_order.setdefault("SH", [])
        if lot not in order:
            order.append(lot)
        st["_shunt"] = (lot, order.index(lot))
        part.hd_lot = lot                   # 测量记录的“批次”（分层用，与机器人厂的谐波减速器批次同一个字段）
        part.lots = {SHUNT_ITEM: lot}

    def _pcb_offset(self, st, code):
        """电路板厂（第 85 轮）：贴片板、成品板的测量值上叠加的偏差"""
        def ramp(p, tau):
            mag, k = st[p]
            return mag * (1 - math.exp(-k / tau))
        if code == "spi_volume" and "stencil_clog" in st:
            return -ramp("stencil_clog", 15.0)
        if code == "spi_height" and "stencil_clog" in st:
            return -0.4 * ramp("stencil_clog", 15.0)
        if code == "reflow_peak" and "reflow_drift" in st:
            return -ramp("reflow_drift", 20.0)
        if code == "reflow_tal" and "reflow_drift" in st:
            return -1.6 * ramp("reflow_drift", 20.0)
        if code == "offset_ic" and "nozzle_wear" in st:
            return st["nozzle_wear"][0] * (1 if self.rng.random() < 0.85 else -1) * self.rng.uniform(0.7, 1.15)
        if code == "aoi_defects":           # 计数型：每块板的缺陷数（泊松），正常约 2%；少锡、偏移随问题增多
            lam = 0.02
            if "stencil_clog" in st:
                lam += 0.6 * max(0.0, ramp("stencil_clog", 15.0) - 15.0) / 15.0
            if "nozzle_wear" in st:
                lam += 0.25 * st["nozzle_wear"][0] / 40.0
            if "reflow_drift" in st:
                lam += 0.05 * ramp("reflow_drift", 20.0) / 14.0
            return float(_poisson(self.rng, lam))
        if code in ("ict_shunt", "fct_isense") and "shunt_lot" in st:
            pct = st["shunt_lot"][0]
            return 2.0 * pct / 100 if code == "ict_shunt" else pct
        return 0.0

    def _chip_offset(self, st, code):
        """芯片封测厂（第 103 轮）：成品批测量值上叠加的偏差（CP 良率、接触电阻由晶圆图给，见 override）"""
        def ramp(p, tau):
            mag, k = st[p]
            return mag * (1 - math.exp(-k / tau))
        if code == "chipping" and "blade_wear" in st:
            return ramp("blade_wear", 5.0)
        if code == "ft_yield" and "blade_wear" in st:
            return -0.08 * max(0.0, ramp("blade_wear", 5.0) - 5.0)
        if code == "bond_pull" and "capillary_wear" in st:
            return -ramp("capillary_wear", 3.0)
        if code == "ball_shear" and "capillary_wear" in st:
            return -2.5 * ramp("capillary_wear", 3.0)
        if code == "mold_void" and "emc_moisture" in st:
            return ramp("emc_moisture", 2.5)
        return 0.0

    def _cp(self, part):
        """这片晶圆的 CP 结果（算一次记在零件上）：各测试位接触电阻 → 晶圆图 → 良率"""
        from sim import wafermap
        st = getattr(part, "err", None)
        if st is None:
            st = {}
            part.err = st
        if "_cp" not in st:
            rc = [round(1.0 + self.rng.gauss(0, 0.08), 3) for _ in range(wafermap.SITES)]
            if "probe_wear" in st:
                mag, k = st["probe_wear"]
                w = mag * (1 - math.exp(-k / 4.0))
                rc = [round(x + (w if i == PROBE_SITE else 0.08 * w), 3) for i, x in enumerate(rc)]
            seed = zlib.crc32(str(getattr(part, "serial", "")).encode()) ^ self.rng.getrandbits(16)
            desc = {"seed": seed, "site_rc": rc, "d0": round(0.07 * self.rng.lognormvariate(0, 0.15), 4), "edge": 0.03, "clusters": 3.0}
            g = wafermap.generate(desc["seed"], rc, desc["d0"], desc["edge"], desc["clusters"])
            st["_cp"] = {"desc": desc, "yield": g["yield_pct"], "contact": round(sum(rc) / len(rc), 4), "site_fail_pct": g["site_fail_pct"],
                         "by_bin": g["by_bin"], "total": g["total"]}
        return st["_cp"]

    def _enc(self, part):
        """传感器厂（第 125 轮）：这台编码器的整圈误差曲线（算一次记在零件上）"""
        from sim import enccurve
        st = getattr(part, "err", None)
        if st is None:
            st = {}
            part.err = st
        if "_enc" not in st:
            def ramp(p, tau):
                if p not in st:
                    return 0.0
                mag, k = st[p]
                return mag * (1 - math.exp(-k / tau))
            desc = enccurve.params(self.rng, str(getattr(part, "serial", "")), ecc_extra=ramp("fixture_wear", 4.0),
                                   amp_drop=ramp("gap_gauge", 4.0), spots_lam=ramp("ffu_clog", 3.0))
            g = enccurve.generate(desc)
            st["_enc"] = {"desc": desc, **{k: g[k] for k in ("acc", "h1", "interp", "amp", "amp_min")}}
        return st["_enc"]

    def override(self, part, code: str):
        """有些测量值不是“名义 + 散布”而是算出来的：芯片厂 CP 良率与接触电阻由晶圆图给，传感器厂编码器的精度等由整圈误差曲线给，
        返回 (值, 附加数据) 或 None"""
        if code in ENC_CODES:
            e = self._enc(part)
            key = code[4:]
            st = getattr(part, "err", None) or {}
            return e[key], ({"enc": {**e["desc"], "station": st.get("_ja")}} if code == "enc_acc" else {})
        if code not in ("cp_yield", "cp_contact"):
            return None
        cp = self._cp(part)
        if code == "cp_yield":
            return cp["yield"], {"wafer": {**cp["desc"], "total": cp["total"], "by_bin": cp["by_bin"], "site_fail_pct": cp["site_fail_pct"]}}
        return cp["contact"], {}

    def plant_offset(self, part, code: str) -> float:
        """机器人厂的关节测量值上叠加的偏差（第 47 轮实验 25）：只在装配工位、批次、测试台对上的那几台上出现；
        电路板厂（第 85 轮）见 _pcb_offset"""
        st = getattr(part, "err", None) or {}
        if code in PCB_CODES:
            return self._pcb_offset(st, code)
        if code in CHIP_CODES:
            return self._chip_offset(st, code)
        if code in TS_CODES:                                 # 传感器厂（第 125 轮）：胶没固化透
            if "cure_low" not in st:
                return 0.0
            mag, k = st["cure_low"]
            r = mag * (1 - math.exp(-k / 4.0))
            return r * {"ts_nonlin": 0.08, "ts_hyst": 0.20, "ts_creep": 0.12, "ts_tczero": 0.15}[code]
        off = 0.0
        if code == "joint_backlash":
            for p in ("ja_torque", "hd_lot"):
                if p in st:
                    off += st[p][0]
        if code == "joint_zero" and "bench_zero" in st:
            mag, k = st["bench_zero"]
            off += min(mag * k, 30.0)
        if code == "enc_cross" and "enc_mount" in st:          # 第 120 轮
            off += st["enc_mount"][0]
        if code == "brake_hold" and "brake_bench" in st:       # 第 120 轮：读数按名义值的百分比逐台下降，最多 40%
            mag, k = st["brake_bench"]
            size = (st.get("_lot_no") or ("L", 0))[0]
            off -= BRAKE_NOMINAL.get(size, 220.0) * min(mag * k, 40.0) / 100.0
        return off

    # -------------------------------------------------------------- 测量
    def measure(self, part, main_rng) -> list[tuple]:
        """返回 [(代号, 名称, 名义, 下限, 上限, 测得值)]。前三项的随机数仍取自引擎主随机数（与原模型一致）。"""
        st = getattr(part, "err", None) or {}
        wear = getattr(part, "grind_wear", st.get("_wear", 0.0))
        slope = 0.0125
        if "dressing_interval" in st:
            slope *= st["dressing_interval"][0]
        thermal = 0.0
        if "thermal_warmup" in st:
            mag, k = st["thermal_warmup"]
            thermal = -mag * (1 - math.exp(-k / 6.0))
        taper = 0.0
        if "tailstock_offset" in st:
            taper = 2 * st["tailstock_offset"][0] / LENGTH          # 直径随 z 的变化率
        ch_sd = 1.0
        runout_mean, runout_sd = 0.004, 0.0012
        if "center_hole" in st:
            runout_mean += st["center_hole"][0]
            runout_sd = 0.003
            ch_sd = 1.3
        sym_mean, sym_sd = 0.006, 0.002
        if "locator_worn" in st:
            sym_mean += st["locator_worn"][0]
            sym_sd = 0.004
        out = []
        base_d35 = 35.0065 + slope * wear + thermal
        # 原有三项：随机数顺序与原模型相同
        # 尾座偏移：工件绕头架顶尖偏斜，直径变化与到头架的距离成正比（第 54 章式 (54.3.2)，头架端为零）
        v1 = main_rng.gauss(base_d35 + taper * Z_LEFT, 0.0012 * ch_sd)
        v2 = main_rng.gauss(40.010 + thermal + taper * Z_GEAR, (40.018 - 40.002) / 10 * ch_sd)
        v3 = main_rng.gauss(11.9785, (12.000 - 11.957) / 10)
        v4 = self.rng.gauss(base_d35 + taper * Z_RIGHT, 0.0012 * ch_sd)
        v5 = abs(self.rng.gauss(runout_mean, runout_sd))
        v6 = abs(self.rng.gauss(sym_mean, sym_sd))
        v7, v8 = self.surface(wear, st)
        for (code, name, nom, lo, hi), v in zip(CHARS, (v1, v2, v3, v4, v5, v6, v7, v8)):
            out.append((code, name, nom, lo, hi, round(v, 4)))
        return out

    def surface(self, wear: float, st: dict) -> tuple[float, int]:
        """轴承位的粗糙度 Ra（µm）与是否烧伤（第 55 章，hub/surface.py）：砂轮磨粒的磨平面积 A（%）刚修整约 0.5，
        随砂轮磨损 wear（0–1）增大（A = 0.5 + 3·wear）；“修整不锋利”时修整后也只恢复到 0.5 + m，且长得快（A = 0.5 + m(1 + 3·wear)）。"""
        from hub import surface as S
        g = GRIND
        if "wheel_dull" in st:
            m = st["wheel_dull"][0]
            A = 0.5 + m * (1 + 3 * wear)
        else:
            A = 0.5 + 3 * wear
        mat = S.STEELS[g["mat"]]
        de = S.equivalent_diameter(g["dw"], g["ds"])
        h = S.heq(g["vw"], g["ap"], g["vs"])
        ra = S.grinding_ra(h, g["sparkout"], wear_flat_pct=A) * self.rng.lognormvariate(0, 0.06)
        t = S.grinding_temperature(mat, g["vs"], g["vw"], g["ap"], de, A)
        burn = S.burn_state(mat, t["theta"], t["t_ms"])["kind"] != "none"
        return ra, int(burn)

    def state(self, teacher=False) -> dict:
        d = {"fixes": FIXES, "problems_catalog": {k: v["name"] for k, v in PROBLEMS.items()} if teacher else None}
        if teacher:
            d["active"] = {k: {"name": PROBLEMS[k]["name"], **v} for k, v in self.active.items()}
            d["history"] = self.history[-20:]
        return d


def simulate(n: int, problem: str | None = None, magnitude=None, seed: int = 54, dress_every: int | None = None,
             wear_per_part: float = 1 / 30, dress_below: float = 0.08) -> dict:
    """不开整个仿真车间，按引擎的磨削节拍连续“磨”n 件 SH-301 并测量（第 54 章的算例与实验用）：
    砂轮每磨一件寿命减 wear_per_part，剩余寿命低于 dress_below 时修整（与 sim/engine.py 的 WEAR_PER_PART、换刀规则相同，约每 28 件一次）；
    给出 dress_every 时改为每磨这么多件修整一次（工艺规程 T05 的“每 10 件修整一次”）。problem 为注入的问题情景（从第 1 件起）。
    返回 {"chars": CHARS, "values": {代号: [n 个测得值]}, "dress_after": [修整前最后一件的序号（从 0 起）]}。"""
    class _P:
        pass

    model = ErrorModel(seed)
    if problem:
        model.inject(problem, magnitude)
    rng = random.Random(seed)
    life, done = 1.0, 0
    vals = {c[0]: [] for c in CHARS}
    dress = []
    for i in range(n):
        p = _P()
        wear = 1 - life
        p.grind_wear = wear
        model.on_process("grd-01", p, wear)
        model.on_process("key-01", p, 0.0)
        for code, *_rest, v in model.measure(p, rng):
            vals[code].append(v)
        life = max(0.0, life - wear_per_part)
        done += 1
        if (dress_every and done >= dress_every) or (not dress_every and life < dress_below):
            dress.append(i)
            life, done = 1.0, 0
    return {"chars": CHARS, "values": vals, "dress_after": dress}
