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

学生在质量异常单上做 8D：原因分析后选择纠正措施；措施经老师批准下发后（apply_fix），只有对症的措施能让问题消失，
后续零件的数据随之恢复——这就是 8D 第 6 步“验证措施有效”的数据来源。
"""
from __future__ import annotations

import math
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
]

# 轴向位置（mm，从左端面）：左轴承位中点、齿轮位中点、右轴承位中点；总长 L
Z_LEFT, Z_GEAR, Z_RIGHT, LENGTH = 46.0, 82.0, 124.5, 167.0

PROBLEMS = {
    "tailstock_offset": {"name": "磨床尾座偏移（锥度）", "unit": "grd-01", "fix": "align_tailstock", "default": 0.008},
    "dressing_interval": {"name": "砂轮修整间隔过长（尺寸漂移加快）", "unit": "grd-01", "fix": "shorten_dressing", "default": 2.5},
    "thermal_warmup": {"name": "磨床未预热（开机后尺寸逐件变小）", "unit": "grd-01", "fix": "warm_up", "default": 0.010},
    "locator_worn": {"name": "键槽夹具定位元件磨损（对称度超差）", "unit": "key-01", "fix": "replace_locator", "default": 0.012},
    "center_hole": {"name": "中心孔质量差（圆跳动超差）", "unit": "grd-01", "fix": "lap_center_holes", "default": 0.006},
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
})
LOT_SIZE = 8                 # 谐波减速器每批 8 台（示例）：关节按装配顺序依次用掉。第 51 轮：仓库有真实到货批次时用到货批次（add_lot）

# 8D 第 5 步可选的纠正措施（含几项“看起来有道理但不对症”的措施）
FIXES = {
    "align_tailstock": "校正磨床尾座，使两顶尖连线与导轨平行（用标准检验棒和千分表）",
    "shorten_dressing": "缩短砂轮修整间隔（每 5 件修整一次）",
    "warm_up": "开机空运转预热 20 min，首件合格后再批量磨削",
    "replace_locator": "更换键槽铣夹具的 V 形块与轴向挡板，并重新对刀",
    "lap_center_holes": "磨前修研中心孔、检查并更换磨损的顶尖",
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
}
ROBOT_FIXES = ("recalibrate_torque", "quarantine_lot", "recalibrate_bench", "add_grease", "tighten_test", "retrain", "change_gauge")


def problems_for(plant_id):
    """这座厂能注入的问题情景：演示工厂（plant_id 为空或 wenquest-gearbox）是输出轴的五种，机器人厂是关节的三种"""
    robot = plant_id == ROBOT
    return {k: v for k, v in PROBLEMS.items() if (v.get("plant") == ROBOT) == robot}


def fixes_for(plant_id):
    if plant_id == ROBOT:
        return {k: FIXES[k] for k in ROBOT_FIXES}
    return {k: v for k, v in FIXES.items() if k not in ROBOT_FIXES or k in ("retrain", "change_gauge")}


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
        self.history = []         # (事件, 问题或措施, 结果)

    def add_lot(self, item: str, lot: str, qty: float):
        """仓库收下一批（来料检验合格）：装关节时先进先出用掉。同一批号只记一次"""
        q = self.lots.setdefault(str(item), [])
        if not any(x[0] == lot for x in q) and not any(lot in v for v in self.lot_order.values()):
            q.append([str(lot), float(qty)])

    def lot_state(self):
        return {"lot_used": dict(self.lot_used), "lots": {k: [list(x) for x in v] for k, v in self.lots.items()},
                "lot_order": {k: list(v) for k, v in self.lot_order.items()}}

    def load_lot_state(self, s):
        s = s or {}
        self.lot_used = dict(s.get("lot_used") or {})
        self.lots = {k: [list(x) for x in v] for k, v in (s.get("lots") or {}).items()}
        self.lot_order = {k: list(v) for k, v in (s.get("lot_order") or {}).items()}

    def _current(self, size):
        o = self.lot_order.get(size) or []
        return len(o) - 1 if o else 0

    # -------------------------------------------------------------- 老师注入、措施下发
    def inject(self, problem: str, magnitude=None):
        if problem not in PROBLEMS:
            raise KeyError(problem)
        self.active[problem] = {"magnitude": float(magnitude if magnitude is not None else PROBLEMS[problem]["default"]), "count": 0}
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
        for p, a in self.active.items():
            u = PROBLEMS[p]["unit"]
            if u == unit or (u == "ja-*" and unit.startswith("ja-")):
                if p == "hd_lot":
                    size, no = st.get("_lot_no", (None, -1))
                    if no < a["from_lot"].get(size, 0):
                        continue
                a["count"] += 1
                st[p] = (a["magnitude"], a["count"])
        if unit == "grd-01":
            st["_wear"] = wear

    def plant_offset(self, part, code: str) -> float:
        """机器人厂的关节测量值上叠加的偏差（第 47 轮实验 25）：只在装配工位、批次、测试台对上的那几台上出现"""
        st = getattr(part, "err", None) or {}
        off = 0.0
        if code == "joint_backlash":
            for p in ("ja_torque", "hd_lot"):
                if p in st:
                    off += st[p][0]
        if code == "joint_zero" and "bench_zero" in st:
            mag, k = st["bench_zero"]
            off += min(mag * k, 30.0)
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
        v1 = main_rng.gauss(base_d35, 0.0012 * ch_sd)
        v2 = main_rng.gauss(40.010 + thermal + taper * (Z_GEAR - Z_LEFT), (40.018 - 40.002) / 10 * ch_sd)
        v3 = main_rng.gauss(11.9785, (12.000 - 11.957) / 10)
        v4 = self.rng.gauss(base_d35 + taper * (Z_RIGHT - Z_LEFT), 0.0012 * ch_sd)
        v5 = abs(self.rng.gauss(runout_mean, runout_sd))
        v6 = abs(self.rng.gauss(sym_mean, sym_sd))
        for (code, name, nom, lo, hi), v in zip(CHARS, (v1, v2, v3, v4, v5, v6)):
            out.append((code, name, nom, lo, hi, round(v, 4)))
        return out

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
