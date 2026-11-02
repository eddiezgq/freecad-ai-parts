# -*- coding: utf-8 -*-
"""工艺规程（第 13 轮《机械制造技术》2.7 节）：一份工艺规程是零件的一个“工艺版本”，与设计版本并列，
走“提交 → AI 工艺评审员预审 → 老师批准 → 生效”。

生效时发总线消息 process.release：桥接在 ERPNext 里给零件建新版 BOM（物料不变，工序与工时换成新工艺），
车间执行（MES）下达工单时按最新生效的工艺规程派工。教学模式下工艺规程也先进待审（设计发布仍是提交即生效）。

工艺规程的数据（dict）：

    {"item": "SH-301", "material": "45", "blank": {"kind": "热轧圆钢", "spec": "Ø50", "length_mm": 262},
     "operations": [
        {"seq": 10, "operation": "下料 Sawing", "workstation": "带锯床 SAW-01", "content": "...", "datum": "外圆",
         "minutes": 3},
        {"seq": 20, "operation": "粗车 Rough turning", "workstation": "数控车床 CNC-L01", "content": "...",
         "datum": "外圆（粗基准）", "clamping": "三爪卡盘", "tools": "...",
         "cut": {"vc_m_min": 100, "f_mm_r": 0.3, "ap_mm": 2.0, "d_mm": 50, "length_mm": 250, "passes": 2},
         "features": [{"name": "轴承位", "size_mm": 36.0, "es_mm": 0, "ei_mm": -0.25, "Ra_um": 12.5}],
         "minutes": 18}, ...],
     "drawing": [{"name": "轴承位", "size_mm": 35, "es_mm": 0.018, "ei_mm": 0.002, "Ra_um": 0.8}],
     "attachments": [{"kind": "calc", "name": "SH-301 工艺计算书.docx", "missing": []}]}

工序尺寸 features 写直径（外圆）及其上下偏差；同名的特征在各道工序之间的差就是余量。
"""
import math
import os
import sys
import uuid

from factory import data as F

AI_REVIEWER = "AI 工艺评审员"

# 工作中心的主电机功率与传动效率（教学示意值，不是某台真实机床的参数；用于切削功率校核）
WORKCENTER_POWER = {
    "数控车床 CNC-L01": (11.0, 0.8),
    "立式加工中心 VMC-01": (15.0, 0.8),
    "卧式加工中心 HMC-01": (18.5, 0.8),
    "键槽铣床 KEY-01": (4.0, 0.75),
    "滚齿机 HOB-01": (7.5, 0.75),
    "外圆磨床 GRD-01": (7.5, 0.8),
}

# 工序 → 阶段（用于顺序检查）与经济精度表里的加工方法
STAGE = {
    "下料 Sawing": "blank",
    "粗车 Rough turning": "rough",
    "调质 Quench & temper": "qt",
    "精车 Finish turning": "finish",
    "铣键槽 Keyway milling": "keyway",
    "滚齿 Gear hobbing": "gear",
    "渗碳淬火 Carburizing": "harden",
    "磨外圆 Cylindrical grinding": "grind",
    "铣结合面 Face milling": "rough",
    "钻攻螺纹孔 Drilling & tapping": "finish",
    "合箱钻铰销孔 Pin-hole reaming": "finish",
    "镗轴承孔 Bearing-bore boring": "finish",
    "零件检验 Part inspection": "inspect",
    "出厂检验 Final inspection": "inspect",
}
from factory import plant as _plant  # noqa: E402  工厂清单（第 30 轮；freecad-ai-parts ADR-0064）：阶段、主电机功率取自清单
if _plant.active():
    STAGE = dict(_plant.active()["STAGE"])
    WORKCENTER_POWER = dict(_plant.active()["WORKCENTER_POWER"])
# 扩展（第 30 轮 H-8）：起草工艺规程时给自制件补粗基准与装夹，fn(item) → {datum?, clamping?}（写到第一道机加工工序上）。
# freecad-ai-parts 的新产品登记（hub/products.py）挂在这里；问渠这边为空
PLAN_HINTS = []
ECON_METHOD = {"粗车 Rough turning": "od_rough_turn", "精车 Finish turning": "od_finish_turn"}
MATERIAL_KIENZLE = {"45": "C45E", "45 钢": "C45E", "40Cr": "C45E", "20CrMnTi": "C45E"}


def _tables():
    """The book's digitized tables (textbook/mfgtech/std) through the shared reader."""
    p = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "std"))   # synced copy (std/sync.py)
    if p not in sys.path:
        sys.path.insert(0, p)
    import stdtab
    return stdtab


def it_grade(size_mm, tol_mm):
    """The coarsest IT grade whose standard tolerance does not exceed tol (公差带宽度对应的标准公差等级)."""
    st = _tables()
    t = st.table("it_grades")
    row = t.find(size_over_mm__lt=size_mm, size_to_mm__ge=size_mm)
    best = None
    for g in range(1, 19):
        if row[f"IT{g}_um"] / 1000.0 <= tol_mm + 1e-9:
            best = g
    return best


def cutting_power_kw(material, cut):
    """Kienzle: F_c = k_c1.1 · b · h^(1−m_c)，车削取主偏角 90°（h = f，b = a_p）；P_c = F_c · v_c / 60 000（kW）"""
    st = _tables()
    k = st.table("kienzle")
    row = k.row(MATERIAL_KIENZLE.get(str(material), "C45E"))
    Fc = row["kc11_MPa"] * cut["ap_mm"] * cut["f_mm_r"] ** (1 - row["mc"])
    return Fc * cut["vc_m_min"] / 60000.0, Fc, "按{}，{}：k_c1.1 = {} MPa、m_c = {}".format(k.label(), row["material"], row["kc11_MPa"], row["mc"])


def basic_time_min(cut):
    """车削基本时间 t_b = L · i / (n · f)，n = 1000 v_c / (π d)"""
    n = 1000.0 * cut["vc_m_min"] / (math.pi * cut["d_mm"])
    return cut["length_mm"] * cut.get("passes", 1) / (n * cut["f_mm_r"])


# ---------------------------------------------------------------- AI 工艺评审员（规则）
def review(plan):
    """逐条检查一份工艺规程，返回意见 [{rule, level: error|warning|info, seq, text}]。只提意见，不批准。"""
    out = []

    def say(rule, level, text, seq=None):
        out.append({"rule": rule, "level": level, "seq": seq, "text": text})

    ops = plan.get("operations") or []
    if not ops:
        say("完整", "error", "工序表是空的。")
        return out
    part = part_spec(plan.get("item"))
    if part:                      # 第 13 轮十二：有零件图要求文件的零件（SH-101），图纸以它为准，工艺规程里写的不算
        plan = dict(plan, drawing=part["drawing"])
        if plan.get("characteristics"):
            plan["characteristics"] = part["characteristics"]
    seqs = [o.get("seq") for o in ops]
    if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
        say("完整", "error", "工序号要从小到大、不重复（常用 10、20、30……，便于以后插工序）。")
    allowed_ws = {}
    from sim.engine import OP_UNITS
    from wqbus import UNITS
    for op, units in OP_UNITS.items():
        allowed_ws[op] = {UNITS[u][3] for u in units if UNITS[u][3]}
    for o in ops:
        s = o.get("seq")
        if o.get("operation") not in F.OPERATIONS:
            say("工序与设备", "error", "工序“{}”不在工厂的工序表里，车间无法派工。".format(o.get("operation")), s)
            continue
        if not o.get("workstation"):
            say("完整", "error", "没写工作中心。", s)
        elif o["workstation"] not in allowed_ws.get(o["operation"], {F.OPERATIONS[o["operation"]]}):
            say("工序与设备", "error", "{} 做不了“{}”。".format(o["workstation"], o["operation"].split(" ")[0]), s)
        if not (o.get("minutes") or 0) > 0:
            say("完整", "error", "单件工时要大于 0。", s)
        if STAGE.get(o["operation"]) not in ("blank", "inspect", "qt", "harden") and not o.get("content"):
            say("完整", "warning", "工序内容没写，操作工不知道这一道做什么。", s)

    # 顺序
    names = [o.get("operation") for o in ops]
    pos = {}
    for i, n in enumerate(names):
        pos.setdefault(STAGE.get(n), []).append(i)

    def first(st):
        return pos[st][0] if st in pos else None

    def last(st):
        return pos[st][-1] if st in pos else None
    r, fz, qt, hd, gr, kw = first("rough"), first("finish"), first("qt"), first("harden"), first("grind"), first("keyway")
    if r is not None and fz is not None and r > fz:
        say("顺序", "error", "精车排在粗车之前。应先粗后精：粗加工切除大部分余量，精加工保证精度。", ops[fz]["seq"])
    if qt is not None:
        if r is not None and qt < r:
            say("顺序", "warning", "调质排在粗车之前。轴类一般“粗车 → 调质 → 精车”：粗车后余量小，调质淬得透，变形也在精车时切掉。", ops[qt]["seq"])
        if fz is not None and qt > fz:
            say("顺序", "error", "调质排在精车之后。调质会变形和氧化，精车尺寸保不住；应放在粗车和精车之间。", ops[qt]["seq"])
    if gr is not None:
        for h in (qt, hd):
            if h is not None and gr < h:
                say("顺序", "error", "磨削排在热处理之前。热处理后的变形要靠磨削消除，磨削应在最后。", ops[gr]["seq"])
        if fz is not None and gr < fz:
            say("顺序", "error", "磨削排在精车之前。", ops[gr]["seq"])
    if kw is not None:
        if fz is not None and kw < fz:
            say("顺序", "warning", "铣键槽排在精车之前。键槽应在外圆精车之后铣，以精车后的外圆定位，保证对称度。", ops[kw]["seq"])
        if gr is not None and kw > gr:
            say("顺序", "warning", "铣键槽排在磨削之后。铣削的毛刺和变形会碰伤已磨好的轴颈，一般“精车 → 铣键槽 → 磨”。", ops[kw]["seq"])
    if "inspect" in pos and last("inspect") != len(ops) - 1:
        say("顺序", "warning", "检验后面还有加工工序，这些工序没人检验。", ops[last("inspect")]["seq"])
    if "inspect" not in pos:
        say("完整", "error", "没有检验工序。")

    # 基准
    mach = [o for o in ops if STAGE.get(o.get("operation")) in ("rough", "finish", "keyway", "gear", "grind")]
    if mach and not mach[0].get("datum"):
        say("基准", "error", "第一道机加工工序没写粗基准。", mach[0]["seq"])
    fin = [o for o in mach if STAGE.get(o["operation"]) in ("finish", "grind")]
    dat = {o.get("datum", "").replace("（精基准）", "") for o in fin if o.get("datum")}
    if len(dat) > 1:
        say("基准", "warning", "精加工工序的定位基准不统一（{}）。轴类精加工一般都用两端中心孔，基准统一可减少基准转换误差；"
            "确需换基准的，请在工序内容里说明并做尺寸链计算。".format("、".join(sorted(dat))))

    # 精度与余量
    try:
        st = _tables()
        econ = st.table("econ_accuracy")
    except Exception:  # noqa: BLE001
        econ = None
    seen = {}
    for o in ops:
        for f in o.get("features") or []:
            if "size_mm" not in f:
                continue
            T = f.get("es_mm", 0) - f.get("ei_mm", 0)
            g = it_grade(f["size_mm"], T) if T > 0 else None
            m = ECON_METHOD.get(o["operation"])
            if econ and m and g is not None:
                row = econ.row(m)
                if g < row["IT_min"]:
                    say("精度", "error", "“{}”在{}工序的公差 {:.3f} mm 约为 IT{}，超出{}的经济精度 IT{}–IT{}（见{}）。"
                        .format(f["name"], o["operation"].split(" ")[0], T, g, row["method_zh"], row["IT_min"], row["IT_max"],
                                econ.label()), o["seq"])
            prev = seen.get(f["name"])
            if prev:
                po, pf = prev
                zmin = (pf["size_mm"] + pf.get("ei_mm", 0)) - (f["size_mm"] + f.get("es_mm", 0))
                zmax = (pf["size_mm"] + pf.get("es_mm", 0)) - (f["size_mm"] + f.get("ei_mm", 0))
                if zmin <= 0:
                    say("余量", "error", "“{}”从工序 {} 到 {} 的最小余量（直径上）为 {:.3f} mm，不大于 0——上道尺寸偏小时这一道没东西可切。"
                        .format(f["name"], po["seq"], o["seq"], zmin), o["seq"])
                elif zmin < 0.05 and STAGE.get(o["operation"]) != "grind":
                    say("余量", "warning", "“{}”工序 {} 的最小余量（直径上）只有 {:.3f} mm，可能切不掉上道的表面缺陷层。"
                        .format(f["name"], o["seq"], zmin), o["seq"])
                f["_z"] = (round(zmin, 4), round(zmax, 4))
            seen[f["name"]] = (o, f)
    for d in plan.get("drawing") or []:
        got = seen.get(d["name"])
        if not got:
            say("精度", "warning", "图纸上的“{}”在工艺规程里没有对应的工序尺寸。".format(d["name"]))
            continue
        o, f = got
        lo, hi = f["size_mm"] + f.get("ei_mm", 0), f["size_mm"] + f.get("es_mm", 0)
        dlo, dhi = d["size_mm"] + d.get("ei_mm", 0), d["size_mm"] + d.get("es_mm", 0)
        if lo < dlo - 1e-9 or hi > dhi + 1e-9:
            say("精度", "error", "“{}”最后一道工序尺寸 {:.3f}–{:.3f} 不在图纸要求 {:.3f}–{:.3f} 内。"
                .format(d["name"], lo, hi, dlo, dhi), o["seq"])
        if d.get("Ra_um") and f.get("Ra_um") and f["Ra_um"] > d["Ra_um"]:
            say("精度", "error", "“{}”最后一道工序的粗糙度 Ra {} μm 达不到图纸 Ra {} μm。".format(d["name"], f["Ra_um"], d["Ra_um"]), o["seq"])

    # 切削用量
    for o in ops:
        c = o.get("cut")
        if not c or not all(k in c for k in ("vc_m_min", "f_mm_r", "ap_mm")):
            continue
        try:
            P, Fc, cite = cutting_power_kw(plan.get("material", "45"), c)
        except Exception:  # noqa: BLE001
            continue
        pw = WORKCENTER_POWER.get(o.get("workstation"))
        if pw and P / pw[1] > pw[0]:
            say("切削用量", "error", "切削功率约 {:.1f} kW（F_c ≈ {:.0f} N；{}），除以传动效率 {} 后超过{}的主电机功率 {} kW（教学示意值）。"
                "减小背吃刀量或进给量，或分两刀。".format(P, Fc, cite, pw[1], o["workstation"], pw[0]), o["seq"])
        if "d_mm" in c and "length_mm" in c:
            tb = basic_time_min(c)
            if o.get("minutes") and o["minutes"] < tb:
                say("工时", "error", "按切削用量算出的基本时间约 {:.1f} min，比填的单件工时 {} min 还长。".format(tb, o["minutes"]), o["seq"])

    # 数据格式 v2 的检查（第 13 轮 N5）：检验覆盖、定位误差、尺寸链、工序简图
    if plan.get("characteristics"):
        _review_v2(plan, say)

    if part:
        _review_route(plan, part, say)

    # 计算书
    calc = [a for a in plan.get("attachments") or [] if a.get("kind") == "calc"]
    if not calc:
        say("完整", "warning", "没有附工艺计算书（工序尺寸、余量、切削用量和工时的计算过程）。")
    for a in calc:
        if a.get("missing"):
            say("完整", "warning", "工艺计算书缺项：{}。".format("、".join(a["missing"])))
    return out


def part_spec(item):
    """零件图要求（std/<零件>_part.yaml，第 13 轮十二）：没有这个文件的零件返回 None。"""
    if not item:
        return None
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "std", "{}_part.yaml".format(item))
    if not os.path.exists(p):
        return None
    import yaml
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


# 工序 → 方案链里的加工方法（hub/route.py 的 route_methods 表）：精车、磨削按这一道的公差等级分半精/精、粗/精
def _method_of(op, it):
    """一道工序在某个表面上用的加工方法（方案链的一环或几环）。磨削工序登记了粗磨、精磨两个行程（grinding.passes），
    或工序内容写了“粗磨”“精磨”的，算两环。"""
    st = STAGE.get(op.get("operation"))
    if st == "rough":
        return ["od_rough_turn"]
    if st == "finish":
        return ["od_finish_turn" if it is not None and it <= 8 else "od_semi_turn"]
    if st == "grind":
        g = op.get("grinding") if isinstance(op.get("grinding"), dict) else {}
        two = len(g.get("passes") or []) >= 2 or ("粗磨" in str(op.get("content", "")) and "精磨" in str(op.get("content", "")))
        fine = "od_finish_grind" if it is not None and it <= 7 else "od_rough_grind"
        return ["od_rough_grind", fine] if two and fine == "od_finish_grind" else [fine]
    return []


def _review_route(plan, part, say):
    """工艺路线的检查（第 13 轮十二（2），《机械制造技术》第 56 章）：毛坯、热处理前后的工序、加工方案链、加工阶段、辅助工序。"""
    from . import route as RT
    ops = plan.get("operations") or []
    st = [STAGE.get(o.get("operation")) for o in ops]
    segs = (part.get("part") or {}).get("segments") or []
    dmax = max((d for d, _, _ in segs), default=0)
    # 毛坯
    b = plan.get("blank") or {}
    kind = str(b.get("kind", ""))
    if not kind:
        say("路线", "error", "没写毛坯（种类、规格）。")
    if "圆钢" in kind or "棒料" in kind:
        import re
        m = re.search(r"(\d+(?:\.\d+)?)", str(b.get("spec", "")))
        if m and float(m.group(1)) < dmax + 3:
            say("路线", "error", "棒料 {} 比零件最大直径 Ø{:g} 大不到 3 mm，粗车留不出余量（还要切掉轧制表面的缺陷层）。".format(b.get("spec"), dmax))
    if "锻" in kind and "正火" not in (str(b.get("heat", "")) + str(b.get("note", ""))):
        say("路线", "warning", "锻件毛坯没写正火：锻后组织粗大、硬度不匀，切削性差，渗碳淬火后变形也大；锻件一般正火后交货（写在 blank 的 heat 里）。")
    # 热处理前后
    ht = part.get("heat_treatment") or {}
    hd = next((i for i, x in enumerate(st) if x == "harden"), None)
    if ht.get("kind") == "carburize" and hd is None:
        say("路线", "error", "图纸要求渗碳淬火（{}），工艺路线里没有渗碳淬火工序。".format(ht.get("spec", "")))
    if hd is not None:
        first_cut = next((i for i, x in enumerate(st) if x in ("rough", "finish", "gear", "keyway")), None)
        if first_cut is not None and hd < first_cut:
            say("路线", "error", "渗碳淬火排在切削加工之前：淬硬后车、铣、滚都切不动，热处理应在半精加工之后、磨削之前。", ops[hd]["seq"])
        for i in range(hd + 1, len(ops)):
            if st[i] in ("rough", "finish", "gear", "keyway"):
                say("路线", "error", "{}排在渗碳淬火之后：表面 58–62 HRC，{}不动；这一道要移到热处理之前（淬硬后只能磨）。"
                    .format(ops[i]["operation"].split(" ")[0], "车" if st[i] in ("rough", "finish") else "铣、滚"), ops[i]["seq"])
        gr_after = [i for i in range(hd + 1, len(ops)) if st[i] == "grind"]
        if ht.get("ground_after") and not gr_after:
            say("路线", "error", "{}要在渗碳淬火后磨削（尺寸 IT6、Ra 0.8，热处理变形要磨掉），路线里热处理之后没有磨削。".format("、".join(ht["ground_after"])))
        for i in gr_after[:1]:
            txt = str(ops[i].get("content", "")) + " ".join(str(a) for a in ops[i].get("aux") or [])
            if "中心孔" not in txt:
                say("路线", "warning", "热处理后磨削之前没有修研中心孔：渗碳淬火后中心孔氧化、变形，以它定位磨出的轴承位跳动保不住"
                    "（写在磨削工序的内容或辅助工步 aux 里）。", ops[i]["seq"])
        for o in ops[hd + 1:]:
            if STAGE.get(o.get("operation")) != "grind":
                continue
            for f in o.get("features") or []:
                z = f.get("_z")
                if z and z[0] < 0.15:
                    say("路线", "warning", "“{}”渗碳淬火后的磨削余量（直径上）最小只有 {:.3f} mm：渗碳淬火的变形大，一般留 0.3–0.5 mm，"
                        "否则磨不圆、磨不掉跳动。".format(f["name"], z[0]), o["seq"])
    # 加工方案链：图纸上每个有公差的外圆
    for d in plan.get("drawing") or []:
        T = d.get("es_mm", 0) - d.get("ei_mm", 0)
        it = it_grade(d["size_mm"], T) if T > 0 else None
        keys, hf, grades = [], None, []
        for i, o in enumerate(ops):
            f = next((x for x in o.get("features") or [] if x.get("name") == d["name"]), None)
            if not f:
                continue
            Tf = f.get("es_mm", 0) - f.get("ei_mm", 0)
            gf = it_grade(f["size_mm"], Tf) if Tf > 0 else None
            m = _method_of(o, gf)
            if not m:
                continue
            if hd is not None and i > hd and hf is None:
                hf = len(keys)
            keys += m
            grades += [None] * (len(m) - 1) + [gf]        # 两环（粗磨、精磨）时，规定的公差是最后一环的
        if not keys or it is None:
            continue
        if hd is not None and hf is None and any(i < hd for i, o in enumerate(ops)
                                                 if any(x.get("name") == d["name"] for x in o.get("features") or [])):
            hf = len(keys)
        for prob in RT.check_chain(keys, it, d.get("Ra_um"), hf, kind or "热轧圆钢", grades):
            say("路线", "warning" if ("跳级" in prob or "不接在" in prob or ("经济精度 IT" in prob and "规定到" in prob)) else "error", "“{}”（IT{}{}）的加工方案链 {}：{}。".format(
                d["name"], it, "、Ra {}".format(d["Ra_um"]) if d.get("Ra_um") else "",
                " → ".join(RT.METHODS[k]["method_zh"] for k in keys), prob))
    gear = (part.get("part") or {}).get("gear")
    if gear:
        gi = [i for i, x in enumerate(st) if x == "gear"]
        if not gi:
            say("路线", "error", "零件有齿轮（m{} z{}），路线里没有切齿工序。".format(gear["m"], gear["z"]))
        else:
            import re
            g = int(re.match(r"\d+", str(gear.get("grade", "8"))).group(0))
            hfg = 1 if hd is not None and gi[-1] < hd else None
            for prob in RT.check_chain(["gear_hob"], g, None, hfg, kind or "热轧圆钢"):
                say("路线", "error", "齿轮（{} 级）：{}。".format(g, prob), ops[gi[0]]["seq"])
    if (part.get("part") or {}).get("keyway") and "keyway" not in st:
        k = part["part"]["keyway"]
        say("路线", "error", "零件图上有键槽（{} N9 × {}），路线里没有铣键槽工序。".format(k.get("b"), k.get("L")))
    # 加工阶段：粗加工不应夹在精加工中间
    fz = next((i for i, x in enumerate(st) if x in ("finish", "grind")), None)
    if fz is not None:
        for i in range(fz + 1, len(ops)):
            if st[i] == "rough":
                say("路线", "warning", "粗车排在精加工之后：粗加工的切削力和热变形会破坏已加工好的表面；粗、精加工要分开，先全部粗加工。", ops[i]["seq"])
    # 辅助工序（aux：去毛刺、清洗、退磁、防锈……写在工序里）
    aux_after = lambda i, word: any(word in str(a) for o in ops[i:] for a in (o.get("aux") or []))  # noqa: E731
    kw = [i for i, x in enumerate(st) if x in ("keyway", "gear")]
    if kw and not aux_after(kw[0], "去毛刺"):
        say("路线", "warning", "铣键槽、滚齿后没有安排去毛刺：毛刺会划伤定位面和轴承，渗碳时尖角也易过热开裂（写在工序的辅助工步 aux 里）。", ops[kw[0]]["seq"])
    ins = [i for i, x in enumerate(st) if x == "inspect"]
    if ins and not any("清洗" in str(a) for o in ops[:ins[-1] + 1] for a in (o.get("aux") or [])):
        say("路线", "warning", "终检之前没有清洗：磨屑、切削液残留会影响测量，也会带进减速器。", ops[ins[-1]]["seq"])
    if ins and not aux_after(ins[-1], "防锈"):
        say("路线", "info", "最后没有写防锈（检验合格后涂防锈油入库）。", ops[ins[-1]]["seq"])


def _review_v2(plan, say):
    from hub import cards, tolerance as TL
    # 1 图纸每个特性都有检验项目；刀具、量具都登记了
    for p in cards.check(plan):
        say("检验", "error" if "终检" in p or "没有检验项目" in p else "warning", p)
    chars = {c["id"]: c for c in plan.get("characteristics") or []}
    # 2 定位误差：工序登记的 locate_check（工序基准随定位面的尺寸变动而移动的量）与工序公差比较
    for o in plan.get("operations") or []:
        lc = o.get("locate_check")
        if not lc:
            continue
        m = lc.get("method")
        if m == "v_block":
            e = TL.v_block(lc["Td"], lc.get("alpha", 90), lc.get("measure", "center"))
        elif m == "pin":
            e = TL.pin_clearance(tuple(lc["hole"]), tuple(lc["pin"]), lc.get("contact", "any"))
        else:
            continue
        e += lc.get("dB", 0.0)
        tol = lc["tol"]
        if e > tol:
            say("定位误差", "error", "“{}”的定位误差约 {:.4f} mm，超过工序公差 {:.3f} mm，这样定位做不出合格品。".format(lc.get("what", ""), e, tol), o["seq"])
        elif not TL.ok_against(tol, e):
            say("定位误差", "warning", "“{}”的定位误差约 {:.4f} mm，超过工序公差 {:.3f} mm 的三分之一，留给加工和测量的余地太小。"
                .format(lc.get("what", ""), e, tol), o["seq"])
    # 2b 夹具：工序登记了夹具编号（fixture_id），且工序里写了夹具数据（fixture，学生自己的设计）或数字工厂有这套夹具的
    #    设计数据（std/<编号>_fixture.yaml）时，
    #    核算夹紧力够不够、夹具精度预算是否满足（第 52 章，hub/fixture.py）
    from hub import fixture as FX
    for o in plan.get("operations") or []:
        if o.get("fixture_id"):
            for level, text in FX.review(o["fixture_id"], o.get("fixture") if isinstance(o.get("fixture"), dict) else None):
                say("夹具", level, text, o["seq"])
    # 2c 加工精度预算（第 54 章，hub/accuracy.py）：工序登记了 accuracy（某个图纸特性的误差项）时，
    #    系统误差相加、随机误差平方和开方，合计不得超过公差；超过公差的四分之三提醒裕量不足
    from hub import accuracy as AC
    for o in plan.get("operations") or []:
        for ab in o.get("accuracy") or []:
            c = chars.get(ab.get("char"))
            T = ab.get("T")
            if c and "es" in c and T is None:
                T = c["es"] - c["ei"]
            if not T:
                say("精度", "warning", "精度预算没有对应到图纸特性（char），也没有给出公差 T。", o["seq"])
                continue
            if c and "es" in c and abs((c["es"] - c["ei"]) - T) > 1e-9:
                say("精度", "warning", "精度预算的公差 T = {:g} 与图纸特性 {} 的公差 {:g} 不一致。".format(T, ab["char"], c["es"] - c["ei"]), o["seq"])
            r = AC.budget(ab.get("items") or [], T)
            big = max(r["items"], key=lambda i: i["range"]) if r["items"] else None
            if not r["ok"]:
                say("精度", "error", "“{}”的精度预算合计 {:.4f} mm（系统误差 {:.4f} + 随机误差 {:.4f}），超过公差 {:g}，按这个方案会出废品；"
                    "最大的一项是“{}”。".format(c["name"] if c else ab.get("char"), r["total"], r["sys"], r["rand"], T, big["name"]), o["seq"])
            elif r["tight"]:
                say("精度", "warning", "“{}”的精度预算合计 {:.4f} mm，占公差 {:g} 的 {:.0%}，裕量不足（工序能力偏低）；最大的一项是“{}”。"
                    .format(c["name"] if c else ab.get("char"), r["total"], T, r["total"] / T, big["name"]), o["seq"])
    # 2d 磨削的表面完整性（第 55 章，hub/surface.py）：工序登记了磨削参数（grinding）时，按修整前砂轮最钝的状态
    #    （wear_flat_pct）核算每一行程的磨削温度：超过回火软化温度或 Ac1 会烧伤（必须改），离得很近要提醒；
    #    最后一次（ra_char）的粗糙度要达到图纸；淬硬件（低温回火）精磨没有烧伤检验要提醒
    from hub import surface as SF
    import re as _re
    for o in plan.get("operations") or []:
        g = o.get("grinding")
        if not isinstance(g, dict):
            continue
        mat = SF.STEELS.get(g.get("mat"))
        if not mat:
            say("表面", "warning", "磨削参数的材料“{}”不在表面完整性库里，没有核算烧伤。".format(g.get("mat")), o["seq"])
            continue
        de = SF.equivalent_diameter(g["dw"], g["ds"], g.get("internal", False))
        A = g.get("wear_flat_pct", 0.5)
        for ps in g.get("passes") or []:
            vw = ps["vw_m_min"] / 60
            t = SF.grinding_temperature(mat, g["vs"], vw, ps["ap"], de, A)
            b = SF.burn_state(mat, t["theta"], t["t_ms"], g.get("coolant", True))
            lim = min(b["onset"], b["Ac1"])
            if b["kind"] != "none":
                say("表面", "error", "{}（工件 {:g} m/min、切深 {:g} mm）：砂轮修整前磨削区最高温度约 {:.0f} ℃，超过{} {:.0f} ℃，会{}；"
                    "允许的最大切深约 {:.4f} mm。".format(ps.get("name", "磨削"), ps["vw_m_min"], ps["ap"], t["theta"],
                                                    "回火软化温度" if b["onset"] <= b["Ac1"] else " Ac1", lim, b["name"],
                                                    SF.max_infeed(mat, g["vs"], vw, de, A)), o["seq"])
            elif b["margin"] < 50:
                say("表面", "warning", "{}：磨削区最高温度约 {:.0f} ℃，离烧伤只差 {:.0f} ℃，砂轮稍钝就会烧伤；减小切深或缩短修整间隔。"
                    .format(ps.get("name", "磨削"), t["theta"], b["margin"]), o["seq"])
            c = chars.get(ps.get("ra_char")) if ps.get("ra_char") else None
            if c:
                m = _re.search(r"Ra\s*([\d.]+)", str(c.get("spec", "")))
                ra = SF.grinding_ra(t["heq"], ps.get("sparkout", 0), g.get("mesh", 60), A)
                if m and ra > float(m.group(1)):
                    say("表面", "error", "{}后粗糙度约 Ra {:.2f} μm，达不到 {}；增加光磨次数或减小切深。".format(ps.get("name", "精磨"), ra, c.get("spec")), o["seq"])
        if mat["temper_c"] < 300 and not any("烧伤" in str(i.get("char", "")) or "酸洗" in str(i.get("gauge", "")) for i in o.get("inspect") or []):
            say("表面", "warning", "淬硬件（低温回火）磨削后没有烧伤检验（酸洗、显微硬度或巴克豪森噪声）：烧伤从尺寸和粗糙度上看不出来。", o["seq"])
    # 3 尺寸链：工艺规程里登记的尺寸链，按极值法算出的封闭环要落在图纸特性之内
    for ch in plan.get("chains") or []:
        links = [TL.Link(l["name"], l["nominal"], l.get("es", 0), l.get("ei", 0), l.get("sense", 1)) for l in ch["links"]]
        r = TL.extreme(links)
        c = chars.get(ch.get("char"))
        if not c or "nominal" not in c:
            say("尺寸链", "warning", "尺寸链“{}”没有对应到图纸特性（char）。".format(ch.get("name")))
            continue
        lo, hi = c["nominal"] + c["ei"], c["nominal"] + c["es"]
        if r.min < lo - 1e-9 or r.max > hi + 1e-9:          # 只比较极限尺寸（名义值与偏差的写法可以不同）
            say("尺寸链", "error", "尺寸链“{}”算得 {}，即 {:.4f}–{:.4f}，不在图纸 {}的 {:.4f}–{:.4f} 之内。"
                .format(ch["name"], r.text(4), r.min, r.max, c["spec"], lo, hi))
    # 3b 工艺尺寸跟踪图（第 53 章）：图纸轴向尺寸能否保证，每次精加工端面、轴肩的余量是否够
    tc = plan.get("tolerance_chart")
    if tc:
        try:
            r = TL.chart_from_plan(tc)
        except (KeyError, ValueError) as e:
            say("尺寸链", "error", "工艺尺寸跟踪图有错：{}".format(e))
        else:
            names = tc.get("surfaces", {})
            cd = tc.get("cut_dir") or {}
            miss = sorted({c["surf"] for c in tc["cuts"]} - set(cd))
            if miss:
                say("尺寸链", "warning", "跟踪图没有给出{}的 cut_dir（加工方向），余量只能按名义值判断方向，车过头查不出来。".format(
                    "、".join(names.get(m, m) for m in miss)))
            for d in r["drawing"]:
                if not d["ok"]:
                    spec = TL.Result(d["nominal"], d["es"], d["ei"], "图纸").text(3)
                    say("尺寸链", "error", "跟踪图：{}–{} 的图纸尺寸 {} 保证不了，工艺上得到 {}（尺寸链：{}）。".format(
                        names.get(d["a"], d["a"]), names.get(d["b"], d["b"]), spec, d["result"].text(3), "、".join(d["links"])))
            for a in r["allowances"]:
                if not a["ok"]:
                    say("尺寸链", "error", "跟踪图：工步 {} 加工{}时余量最小只有 {} mm（要求不小于 {:g}），可能车不出来。".format(
                        a["seq"], names.get(a["surface"], a["surface"]), f"{a['min']:.3f}".replace("-", "−"), r["min_allowance"]))
    # 4 工序简图上的工序尺寸与工序尺寸表一致
    for o in plan.get("operations") or []:
        sk = o.get("sketch") or {}
        texts = " ".join(d.get("text", "") for d in sk.get("dims") or [])
        if not texts:
            continue
        for f in o.get("features") or []:
            if "size_mm" in f and "Ø{:g}".format(f["size_mm"]) not in texts:
                say("工序简图", "warning", "工序简图上没有标“{}”的工序尺寸 Ø{:g}。".format(f["name"], f["size_mm"]), o["seq"])


def suggested_score(findings):
    """建议分（老师可以不采纳）：100 起，每条 error 扣 10，warning 扣 3，最低 0。"""
    return max(0, 100 - 10 * sum(f["level"] == "error" for f in findings) - 3 * sum(f["level"] == "warning" for f in findings))


# ---------------------------------------------------------------- 提交、审批、生效
# 表 process_submission 在 hub/db.py 的建表语句里（与 design_submission 并列）。


def current_revision(db, mode, item):
    r = db.one("select max(revision) r from process_submission where mode=%s and item=%s and status='approved'", (mode, item))
    return (r and r["r"]) or 0


def get(db, sid):
    r = db.one("select * from process_submission where id=%s", (sid,))
    if not r:
        return None
    r = dict(r)
    r["comments"] = [dict(c) for c in db.q("select * from design_comment where sub_id=%s order by id", ("P" + sid,))]
    return r


def submit(db, emit, mode, author, author_uid, plan, note=""):
    """提交一份工艺规程：AI 工艺评审员先审，意见写成批注；教学和生产模式都进待审。"""
    from psycopg.types.json import Jsonb
    item = plan.get("item")
    if item not in F.ITEMS:
        raise ValueError("没有这个零件：{}".format(item))
    sid = uuid.uuid4().hex[:12]
    findings = review(plan)
    rev = {"findings": findings, "suggested_score": suggested_score(findings), "by": AI_REVIEWER}
    db.x("insert into process_submission (id, mode, item, status, author, author_uid, note, plan, review) "
         "values (%s,%s,%s,'pending',%s,%s,%s,%s,%s)", (sid, mode, item, author, author_uid, note, Jsonb(plan), Jsonb(rev)))
    for f in findings:
        if f["level"] == "info":
            continue
        body = "〔{}·{}〕{}{}".format(f["rule"], "必须改" if f["level"] == "error" else "建议",
                                     "工序 {}：".format(f["seq"]) if f["seq"] is not None else "", f["text"])
        db.x("insert into design_comment (sub_id, author, body) values (%s,%s,%s)", ("P" + sid, AI_REVIEWER, body))
    emit("wq/gearbox/design/{}/process".format(item.lower()), "process.submit",
         {"item": item, "submission": sid, "author": author, "findings": len(findings),
          "errors": sum(f["level"] == "error" for f in findings)})
    return get(db, sid)


def resolve(db, sid, cid, resolved=True):
    db.x("update design_comment set resolved=%s where id=%s and sub_id=%s", (resolved, cid, "P" + sid))
    return get(db, sid)


def approve(db, emit, sid, approver, note="", approver_uid=None):
    s = get(db, sid)
    if not s:
        raise KeyError("没有这次提交")
    if s["status"] != "pending":
        raise ValueError("这次提交已经处理过了")
    if (s["author_uid"] or s["author"]) == (approver_uid or approver):
        raise PermissionError("不能批准自己的工艺规程，请老师或另一位审批人批准")
    if any(not c["resolved"] for c in s["comments"]):
        raise ValueError("还有没处理的评审意见，先逐条标为“已处理”再批准")
    rev = current_revision(db, s["mode"], s["item"]) + 1
    db.x("update process_submission set status='approved', revision=%s, decided_by=%s, decided_at=now(), decision=%s where id=%s",
         (rev, approver, note, sid))
    p = s["plan"]
    ops = [{"seq": o["seq"], "operation": o["operation"], "workstation": o["workstation"], "minutes": o["minutes"]}
           for o in p["operations"]]
    emit("wq/gearbox/design/{}/process".format(s["item"].lower()), "process.release",
         {"item": s["item"], "revision": rev, "operations": ops, "submission": sid, "author": s["author"],
          "approved_by": approver, "total_minutes": round(sum(o["minutes"] for o in ops), 2), "note": s["note"] or ""})
    return get(db, sid)


def reject(db, emit, sid, who_, note):
    s = get(db, sid)
    if not s or s["status"] != "pending":
        raise ValueError("这次提交不在待审")
    if not note.strip():
        raise ValueError("退回要写明原因")
    db.x("update process_submission set status='rejected', decided_by=%s, decided_at=now(), decision=%s where id=%s", (who_, note, sid))
    emit("wq/gearbox/design/{}/process".format(s["item"].lower()), "process.review",
         {"item": s["item"], "submission": sid, "decision": "rejected", "by": who_, "note": note})
    return get(db, sid)


def active_routing(db, mode, item):
    """最新生效的工艺规程的 [(工序, 分钟)]；没有生效的工艺规程时返回 None（MES 改用工厂数据）。"""
    try:
        r = db.one("select plan from process_submission where mode=%s and item=%s and status='approved' "
                   "order by revision desc limit 1", (mode, item))
    except Exception:  # noqa: BLE001 —— 表还没建（旧库）时按工厂数据
        return None
    if not r:
        return None
    return [[o["operation"], o["minutes"]] for o in r["plan"]["operations"]]


def factory_plan(item):
    """工厂数据里的现行工艺（第 0 版），新建工艺规程时作为起点。"""
    rt = F.BOMS[item][0]
    ops = [{"seq": 10 * (i + 1), "operation": op, "workstation": F.OPERATIONS[op], "minutes": m, "content": ""}
           for i, (op, m) in enumerate(F.ROUTINGS[rt])]
    hint = {k: v for fn in PLAN_HINTS for k, v in (fn(item) or {}).items()}
    first = next((o for o in ops if STAGE.get(o["operation"]) in ("rough", "finish", "keyway", "gear", "grind")), None)
    if hint and first:
        first.update(hint)
    return {"item": item, "routing": rt, "operations": ops}
