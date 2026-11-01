# -*- coding: utf-8 -*-
"""参数配置器（数字工厂第 8 轮 Q6）：把产品做成“参数模板”——参数与范围、校核、三维、图纸、报价、下单。

模板（这座厂的清单里有那个物料、不是外购件才显示）：
  SH-301  输出轴（备件、改尺寸），复用网页设计台的校核、建模、零件图；
  WQR-105 二级圆柱齿轮减速器：选传动比（两级中心距不变、换齿数组合）、输入功率与转速、工况系数，
          校核输出转矩、轴承寿命（零件库 6207）、输出轴平键挤压强度；三维为布置示意。
  WQ-CR5  协作臂定制（第 63 轮，机器人厂）：填负载、臂展、动作快慢，按《机器人学》30.3 节定连杆长度和关节模组，校核力矩，
          三维由同一个 MJCF 生成；订单仍是 WQ-CR5，定制参数随订单提议记录。
报价 = 标准成本（材料 + 工时 × 工位费率）× (1 + 毛利率)；下单走现有“提议—确认”（桥接写入 ERPNext）。
"""
import hashlib
import json
import math
from itertools import product

from factory import data as F

MARGIN = 0.30                     # 毛利率（报价 = 成本 × 1.3）；WQR-105 标准型号用工厂定价


# ---------------------------------------------------------------- 输出轴 SH-301
def _sh301():
    from hub import design as D
    d = D.defaults()
    segs = [{"key": "d{}".format(i + 1), "zh": "第 {} 段直径".format(i + 1), "unit": "mm", "min": 5, "max": 48, "step": 0.5,
             "default": s[0], "group": "轴段"} for i, s in enumerate(d["segments"])]
    lens = [{"key": "l{}".format(i + 1), "zh": "第 {} 段长度".format(i + 1), "unit": "mm", "min": 2, "max": 300, "step": 1,
             "default": s[1], "group": "轴段"} for i, s in enumerate(d["segments"])]
    kw = d["keyway"]
    return {
        "id": "SH-301", "item": "SH-301", "name": "输出轴（备件 / 改尺寸）",
        "summary": "五段阶梯轴，带平键槽；按客户图纸改轴段尺寸和键槽",
        "params": [x for pair in zip(segs, lens) for x in pair] + [
            {"key": "chamfer", "zh": "两端倒角", "unit": "mm", "min": 0, "max": 5, "step": 0.5, "default": d["chamfer"], "group": "倒角与键槽"},
            {"key": "kw_b", "zh": "键宽 b", "unit": "mm", "min": 2, "max": 22, "step": 1, "default": kw["b"], "group": "倒角与键槽"},
            {"key": "kw_t", "zh": "槽深 t", "unit": "mm", "min": 1, "max": 9, "step": 0.5, "default": kw["t"], "group": "倒角与键槽"},
            {"key": "kw_l", "zh": "槽长 L", "unit": "mm", "min": 5, "max": 120, "step": 1, "default": kw["L"], "group": "倒角与键槽"},
        ],
    }


def _sh301_params(v):
    return {"segments": [(float(v["d%d" % i]), float(v["l%d" % i])) for i in range(1, 6)], "chamfer": float(v["chamfer"]),
            "keyway": {"segment": 2, "b": float(v["kw_b"]), "t": float(v["kw_t"]), "L": float(v["kw_l"])}}


def _sh301_eval(v, qty):
    from hub import design as D
    from hub import mrp
    p = _sh301_params(v)
    chk = D.check(p)
    kg = D.wq_publish.blank_kg(p)
    steel = F.ITEMS["RM-45-D50"][3]
    _, ops = mrp.std_unit_cost("SH-301")
    cost = round(kg * steel + ops, 2)
    price = round(cost * (1 + MARGIN), 2)
    figures = [("总长", "{:g} mm".format(chk["total_length_mm"])), ("下料（45 钢 Ø50）", "{} kg".format(kg)),
               ("键槽推荐（GB/T 1095）", "b={b}、t={t}".format(**chk["recommended"]) if chk["recommended"] else "—")]
    lines = [{"desc": "材料：45 钢圆棒 Ø50", "qty": kg, "unit": "kg", "price": steel, "amount": round(kg * steel, 2)},
             {"desc": "加工：下料、车、调质、铣键槽、磨、检验（标准工时 × 工位费率）", "qty": 1, "unit": "件", "price": ops, "amount": ops}]
    return {"ok": chk["ok"], "errors": chk["errors"], "warnings": chk["warnings"], "figures": figures,
            "quote": _quote(lines, cost, price, qty, "SH-301"), "item": "SH-301"}


def _sh301_model(v):
    from hub import design as D
    from hub import plm
    p = _sh301_params(v)
    glb, info = plm.step_to_glb(D.step_bytes(p))
    svg = D.wq_drawing.svg(p, "SH-301", D.wq_publish.CONFIG["title"], 0, "配置器").encode("utf-8")
    return glb, svg


# ---------------------------------------------------------------- 减速器 WQR-105
M1, M2, A1, A2 = 2.0, 3.0, 96.0, 135.0             # 两级模数与中心距（壳体不变）
STAGE1 = [(24, 72), (21, 75), (27, 69), (32, 64)]    # z1+z2 = 96
STAGE2 = [(20, 70), (18, 72), (23, 67), (25, 65)]    # z3+z4 = 90
ETA = 0.97 * 0.97 * 0.99 ** 3                      # 两级齿轮 + 三对轴承
T_RATED = 350.0                                    # 输出轴额定转矩 N·m：受输出轴平键限制（135 × 40 × 8 × 33 / 4 ≈ 356）
BRG_C = 25.5e3                                     # 6207 基本额定动载荷 N（GB/T 276，零件库 A-BRG-DG/6207）
# 输出轴平键 12×8×45（零件库 A-KEY-FLAT/12x8x45）；许用挤压应力取钢制轮毂静联接 120～150 MPa 的中值
# （冲击已由工况系数 KA 计入）
KEY = {"b": 12, "h": 8, "l": 45, "d": 40, "sigma": 135.0}


def ratios():
    out = []
    for (a, b), (c, d) in product(STAGE1, STAGE2):
        out.append({"key": "{}-{}-{}-{}".format(a, b, c, d), "i": round(b / a * d / c, 2), "z": [a, b, c, d]})
    return sorted(out, key=lambda r: r["i"])


def _wqr():
    rs = ratios()
    std = next(r for r in rs if r["z"] == [24, 72, 20, 70])
    return {
        "id": "WQR-105", "item": "WQR-105", "name": "二级圆柱齿轮减速器 WQR-105",
        "summary": "两级中心距 {:g} / {:g} mm 不变，换齿数组合得到不同传动比；按输入功率校核转矩、轴承寿命、键".format(A1, A2),
        "params": [
            {"key": "ratio", "zh": "传动比", "choices": [{"value": r["key"], "label": "i = {:g}（{}/{} × {}/{}）{}".format(
                r["i"], r["z"][1], r["z"][0], r["z"][3], r["z"][2], " 标准" if r is std else "")} for r in rs],
             "default": std["key"], "group": "传动"},
            {"key": "power_kw", "zh": "输入功率", "unit": "kW", "min": 0.37, "max": 11, "step": 0.01, "default": 4.0, "group": "工况"},
            {"key": "n1", "zh": "输入转速", "unit": "r/min", "choices": [{"value": n, "label": "{} r/min".format(n)} for n in (750, 1000, 1450, 2900)],
             "default": 1450, "group": "工况"},
            {"key": "ka", "zh": "工况系数 KA", "unit": "", "min": 1.0, "max": 2.0, "step": 0.05, "default": 1.25, "group": "工况",
             "hint": "均匀载荷 1.0；中等冲击 1.25～1.5；强冲击 1.75～2.0"},
            {"key": "life_h", "zh": "要求轴承寿命", "unit": "h", "min": 2000, "max": 50000, "step": 1000, "default": 10000, "group": "工况"},
        ],
    }


def _wqr_eval(v, qty):
    from hub import mrp
    r = next((x for x in ratios() if x["key"] == v["ratio"]), None)
    if not r:
        return {"ok": False, "errors": ["没有这个传动比组合"], "warnings": [], "figures": [], "quote": None, "item": "WQR-105"}
    z1, z2, z3, z4 = r["z"]
    p, n1, ka, life = float(v["power_kw"]), float(v["n1"]), float(v["ka"]), float(v["life_h"])
    i = z2 / z1 * z4 / z3
    n2 = n1 / i
    t2 = 9550 * p / n2 * ETA                       # 输出转矩 N·m
    t2k = t2 * ka
    d4 = M2 * z4                                   # 大齿轮分度圆 mm
    ft = 2000 * t2k / d4                           # 圆周力 N
    fr = ft * math.tan(math.radians(20)) / math.cos(0)
    load = math.hypot(ft, fr) / 2                  # 两个轴承平分（齿轮居中）
    l10h = (BRG_C / load) ** 3 * 1e6 / (60 * n2)
    sigma = 4000 * t2k / (KEY["d"] * KEY["h"] * (KEY["l"] - KEY["b"]))   # 平键挤压应力 MPa（A 型键工作长度 l-b）
    errors, warnings = [], []
    if t2k > T_RATED:
        errors.append("计入工况系数的输出转矩 {:.0f} N·m 超过额定 {:.0f} N·m：减小功率或选更小的传动比".format(t2k, T_RATED))
    elif sigma > KEY["sigma"]:
        errors.append("输出轴平键 12×8×45 挤压应力 {:.0f} MPa 超过许用 {:.0f} MPa".format(sigma, KEY["sigma"]))
    if l10h < life:
        warnings.append("轴承 6207 计算寿命 {:,.0f} h，低于要求的 {:,.0f} h".format(l10h, life))
    if n1 == 2900:
        warnings.append("输入 2900 r/min：齿轮线速度高，需确认润滑（CKC220 油浴）与噪声要求")
    std = r["z"] == [24, 72, 20, 70]
    mat, ops = mrp.std_unit_cost("SH-301")
    base = F.FG_SELLING_PRICE
    extra = 0 if std else round(base * 0.08, 2)    # 非标传动比：换两对齿轮，工装与小批量加价 8%
    price = round(base + extra, 2)
    lines = [{"desc": "WQR-105 标准型（i = 10.5，含全部外购件）", "qty": 1, "unit": "台", "price": base, "amount": base}]
    if extra:
        lines.append({"desc": "非标传动比：两对齿轮改齿数（{}/{}、{}/{}）".format(z2, z1, z4, z3), "qty": 1, "unit": "台", "price": extra, "amount": extra})
    figures = [("传动比", "{:.2f}".format(i)), ("输出转速", "{:.1f} r/min".format(n2)),
               ("输出转矩（× KA）", "{:.0f} N·m（额定 {:.0f}）".format(t2k, T_RATED)),
               ("轴承 6207 寿命 L10h", "{:,.0f} h".format(l10h)), ("输出轴键挤压应力", "{:.0f} MPa（许用 {:.0f}）".format(sigma, KEY["sigma"])),
               ("齿数", "{}/{} × {}/{}（m = {:g} / {:g}）".format(z2, z1, z4, z3, M1, M2))]
    return {"ok": not errors, "errors": errors, "warnings": warnings, "figures": figures,
            "parts": [{"ref": F.LIBRARY_REFS["BRG-6207"], "item": "BRG-6207", "zh": "输出轴轴承（深沟球 6207）"},
                      {"ref": F.LIBRARY_REFS["KEY-12x8x45"], "item": "KEY-12x8x45", "zh": "输出轴平键 12×8×45"}],
            "quote": _quote(lines, None, price, qty, "WQR-105"), "item": "WQR-105"}


def _wqr_model(v):
    """布置示意：壳体（半透明另算）+ 三根轴 + 四个齿轮毛坯（分度圆直径、齿宽）"""
    import os
    import tempfile
    import build123d as bd
    r = next(x for x in ratios() if x["key"] == v["ratio"])
    z1, z2, z3, z4 = r["z"]
    xs = [0.0, A1, A1 + A2]
    parts = []
    gears = [(xs[0], M1 * z1, 30, 0), (xs[1], M1 * z2, 30, 0), (xs[1], M2 * z3, 40, 45), (xs[2], M2 * z4, 40, 45)]
    for x, dia, b, zoff in gears:
        parts.append(bd.Pos(x, 0, zoff) * bd.Cylinder(dia / 2, b))
    for x, d in zip(xs, (25, 30, 40)):
        parts.append(bd.Pos(x, 0, 25) * bd.Cylinder(d / 2, 180))
    top = max(M1 * z2, M2 * z4) / 2 + 15
    shell = bd.Pos((xs[0] + xs[2]) / 2, 0, 25) * bd.Box(xs[2] + 2 * top, 2 * top, 120)
    shell = shell - bd.Pos((xs[0] + xs[2]) / 2, 0, 25) * bd.Box(xs[2] + 2 * top - 16, 2 * top - 16, 104)
    shell = shell.split(bd.Plane.XZ, keep=bd.Keep.BOTTOM)            # 剖开一半，能看见里面的齿轮
    comp = bd.Compound(children=parts + [shell])
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "m.glb")
        bd.export_gltf(comp, f, binary=True, linear_deflection=0.2, angular_deflection=0.3)
        glb = open(f, "rb").read()
    return glb, _wqr_svg(r)


def _wqr_svg(r):
    z1, z2, z3, z4 = r["z"]
    s = 1.4
    cx = [60, 60 + A1 * s, 60 + (A1 + A2) * s]
    cy = 170
    circ = [(cx[0], M1 * z1), (cx[1], M1 * z2), (cx[1], M2 * z3), (cx[2], M2 * z4)]
    el = ['<circle cx="{:.1f}" cy="{}" r="{:.1f}" fill="none" stroke="#1F2A33" stroke-width="1.2" {}/>'.format(
        x, cy, d / 2 * s, 'stroke-dasharray="6 3"' if k >= 2 else "") for k, (x, d) in enumerate(circ)]
    el += ['<text x="{:.1f}" y="{}" font-size="11" text-anchor="middle">Ø{:g}</text>'.format(x, cy - d / 2 * s - 6 + (k % 2) * 0, d)
           for k, (x, d) in enumerate(circ)]
    el += ['<line x1="{:.1f}" y1="320" x2="{:.1f}" y2="320" stroke="#1F2A33"/><text x="{:.1f}" y="314" font-size="11" text-anchor="middle">a = {:g}</text>'
           .format(cx[k], cx[k + 1], (cx[k] + cx[k + 1]) / 2, a) for k, a in enumerate((A1, A2))]
    i = z2 / z1 * z4 / z3
    title = ('<rect x="430" y="300" width="300" height="70" fill="none" stroke="#1F2A33"/>'
             '<text x="440" y="320" font-size="12">二级圆柱齿轮减速器 WQR-105 · 布置示意</text>'
             '<text x="440" y="340" font-size="12">i = {:.2f} = {}/{} × {}/{}　m = {:g} / {:g}</text>'
             '<text x="440" y="360" font-size="11">实线：第一级；虚线：第二级。单位 mm</text>').format(i, z2, z1, z4, z3, M1, M2)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 390" font-family="sans-serif">'
            '<rect width="760" height="390" fill="#fff"/>' + "".join(el) + title + "</svg>").encode("utf-8")


# ---------------------------------------------------------------- 协作臂定制 WQ-CR5（第 63 轮，机器人厂）
# 教材《机器人学》30.3 节的尺寸综合与模组选择：cae/wqcr5.py 的 design()（与教材程序 ex30_3.py 同一段代码）。
# 默认参数（5 kg、860 mm、标准）得到的就是标准 WQ-CR5。订单仍是 WQ-CR5（不新增 ERP 物料），定制参数随订单提议记录。
CR_SPEED = [("standard", "标准（关节 180°/s、360°/s²）"), ("fast", "快速（关节 180°/s、540°/s²）")]
CR_STD = ("L", "L", "M", "S", "S", "S")
CR_MOD_ITEM = {"L": "WQJ-L", "M": "WQJ-M", "S": "WQJ-S"}


def _cr5():
    return {
        "id": "WQ-CR5", "item": "WQ-CR5", "name": "协作臂定制（WQ-CR5 系列）",
        "summary": "填负载、臂展和动作快慢：按《机器人学》30.3 节定大臂、小臂和每个关节的模组，校核力矩，出三维和报价",
        "params": [
            {"key": "payload_kg", "zh": "额定负载（含夹爪）", "unit": "kg", "min": 1, "max": 10, "step": 0.5, "default": 5.0, "group": "需求"},
            {"key": "reach_mm", "zh": "臂展", "unit": "mm", "min": 600, "max": 1100, "step": 10, "default": 860, "group": "需求",
             "hint": "臂展 = 大臂 + 小臂 + 腕部偏距 d5（0.1 m）；工具朝下时 J1 轴周围 0.12 m 够不着"},
            {"key": "speed", "zh": "动作快慢", "choices": [{"value": k, "label": v} for k, v in CR_SPEED], "default": "standard", "group": "需求"},
        ],
    }


def _cr5_design(v):
    from cae import wqcr5 as W
    return W, W.design(float(v["payload_kg"]), float(v["reach_mm"]), str(v["speed"]))


def _cr5_eval(v, qty):
    W, d = _cr5_design(v)
    errors, warnings = [], []
    if not d["ok"]:
        bad = [j["joint"] for j in d["joints"] if j["module"] is None] or ["某个关节"]
        errors.append("负载 {:g} kg、臂展 {:g} mm：本厂最大的关节模组（谐波 32 号 + 400 W）也不够用。减小负载或臂展".format(
            float(v["payload_kg"]), float(v["reach_mm"])))
        return {"ok": False, "errors": errors, "warnings": warnings, "figures": [("大臂 / 小臂", "{:.3f} / {:.3f} m".format(d["a2"], d["a3"]))],
                "quote": None, "item": "WQ-CR5"}
    mods = d["modules"]
    tight = max(d["joints"], key=lambda j: max(j["use_peak"], j["use_rms"]))
    use = max(tight["use_peak"], tight["use_rms"])
    if use > 0.95:
        warnings.append("{} 的力矩用到 {:.0f}%（含 1.2 倍安全系数）：负载再大一点就要换大一号的模组".format(tight["joint"], use * 100))
    if d["reach_m"] > 0.95:
        warnings.append("臂展超过 0.95 m：铝管仍按标准尺寸，末端的刚度、精度下降，需另作刚度校核（教材第 31 章）")
    own = [j for j in d["joints"] if j["own"] and j["own"] != j["module"]]
    std = bool(d["standard"])
    prices = F.PRODUCTS
    base = float(prices["WQ-CR5"])
    diff = sum(float(prices[CR_MOD_ITEM[m]]) - float(prices[CR_MOD_ITEM[s]]) for m, s in zip(mods, CR_STD))
    extra = 0.0 if std else round((base + diff) * 0.08, 2)      # 非标：大臂、小臂另做、工装与小批量加价 8%（与减速器模板相同）
    price = round(base + diff + extra, 2)
    lines = [{"desc": "WQ-CR5 标准型（5 kg、臂展 860 mm，含控制柜）", "qty": 1, "unit": "台", "price": base, "amount": base}]
    if diff:
        lines.append({"desc": "关节模组改为 {}（与标准 {} 的差价）".format(" ".join(mods), " ".join(CR_STD)), "qty": 1, "unit": "台",
                      "price": round(diff, 2), "amount": round(diff, 2)})
    if extra:
        lines.append({"desc": "非标：大臂 {:.0f} mm、小臂 {:.0f} mm 另做，工装与小批量".format(d["a2"] * 1000, d["a3"] * 1000), "qty": 1,
                      "unit": "台", "price": extra, "amount": extra})
    names = {"L": "大", "M": "中", "S": "小"}
    figures = [("大臂 / 小臂", "{:.0f} / {:.0f} mm（肩部死区 {:.0f} mm）".format(d["a2"] * 1000, d["a3"] * 1000, d["dead_zone_m"] * 1000)),
               ("关节模组 J1–J6", "、".join(names[m] for m in mods) + ("（标准）" if tuple(mods) == CR_STD else "")),
               ("整机质量", "{:.1f} kg（负载与自重之比 {:.2f}）".format(d["mass_kg"], float(v["payload_kg"]) / d["mass_kg"])),
               ("最紧的关节", "{}：峰值 {:.0f}%、连续 {:.0f}%".format(tight["joint"], tight["use_peak"] * 100, tight["use_rms"] * 100)),
               ("J2 / J3 最大重力矩", "{:.0f} / {:.0f} N·m".format(d["joints"][1]["g_max"], d["joints"][2]["g_max"]))]
    if own:
        zh = {"WQJ-L": "大模组", "WQJ-M": "中模组", "WQJ-S": "小模组"}
        figures.append(("按“通用”规则加大", "、".join("{}（自己只要{}）".format(j["joint"], zh[j["own"]]) for j in own)))
    return {"ok": True, "errors": errors, "warnings": warnings, "figures": figures,
            "parts": [{"ref": "B-ARM-WQCR5/default", "item": "WQ-CR5", "zh": "零件库：问渠 WQ-CR5（标准型的模型）"}],
            "design": {"a2": d["a2"], "a3": d["a3"], "modules": mods, "standard": std},
            "quote": _quote(lines, None, price, qty, "WQ-CR5"), "item": "WQ-CR5"}


def _cr5_model(v):
    """三维：按设计的尺寸和模组生成 MJCF，在初始位姿下把每个几何体摆好，导出 glb；图纸：侧视的尺寸简图"""
    import mujoco
    import numpy as np
    import trimesh
    from cae import mbd_models
    W, d = _cr5_design(v)
    mods = d["modules"] or ["L"] * 6
    with W.geometry(d["a2"], d["a3"], mods):
        m = mujoco.MjModel.from_xml_string(W.mjcf())
    dd = mujoco.MjData(m)
    mujoco.mj_resetDataKeyframe(m, dd, 0)
    mujoco.mj_forward(m, dd)
    scene = trimesh.Scene()
    for g in range(m.ngeom):
        mesh = mbd_models._geom_mesh(m, g, trimesh)
        if mesh is None:
            continue
        T = np.eye(4)
        T[:3, :3] = dd.geom_xmat[g].reshape(3, 3)
        T[:3, 3] = dd.geom_xpos[g]
        mesh.apply_transform(T)
        mesh.visual.face_colors = (np.clip(m.geom_rgba[g], 0, 1) * 255).astype(np.uint8)
        scene.add_geometry(mesh)
    return scene.export(file_type="glb"), _cr5_svg(d, mods)


def _cr5_svg(d, mods):
    s = 400.0                                                 # 1 m = 400 px
    x0, y0 = 120, 330
    a2, a3, d1, d5 = d["a2"], d["a3"], 0.15, 0.10
    j2 = (x0, y0 - d1 * s)
    el = (x0, j2[1] - a2 * s)                                 # 初始位姿：大臂竖直向上，小臂水平
    wr = (el[0] + a3 * s, el[1])
    names = {"L": "大", "M": "中", "S": "小"}
    parts = ['<rect x="{}" y="{}" width="60" height="{}" fill="#e8ecef" stroke="#1F2A33"/>'.format(x0 - 30, y0 - 38, 38),
             '<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="#3a70b0" stroke-width="14" stroke-linecap="round"/>'.format(*j2, *el),
             '<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="#3a70b0" stroke-width="11" stroke-linecap="round"/>'.format(*el, *wr),
             '<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="#d98a2b" stroke-width="8"/>'.format(wr[0], wr[1], wr[0], wr[1] + d5 * s)]
    for (x, y), j in ((j2, 1), (el, 2), (wr, 3)):
        parts.append('<circle cx="{:.1f}" cy="{:.1f}" r="10" fill="#fff" stroke="#1F2A33" stroke-width="2"/>'.format(x, y))
        parts.append('<text x="{:.1f}" y="{:.1f}" font-size="12">J{}（{}）</text>'.format(x + 14, y - 10, j + 1, names[mods[j]]))
    parts.append('<text x="{:.1f}" y="{:.1f}" font-size="13">a2 = {:.0f} mm</text>'.format(x0 - 110, (j2[1] + el[1]) / 2, a2 * 1000))
    parts.append('<text x="{:.1f}" y="{:.1f}" font-size="13" text-anchor="middle">a3 = {:.0f} mm</text>'.format((el[0] + wr[0]) / 2, el[1] + 26, a3 * 1000))
    title = ('<rect x="430" y="300" width="300" height="70" fill="none" stroke="#1F2A33"/>'
             '<text x="440" y="320" font-size="12">协作臂定制 · WQ-CR5 系列 · 尺寸简图</text>'
             '<text x="440" y="340" font-size="12">负载 {:g} kg　臂展 {:.0f} mm　模组 {}</text>'
             '<text x="440" y="360" font-size="11">初始位姿；腕部 J4–J6 为{}模组。示例值</text>').format(
        d["payload_kg"], d["reach_m"] * 1000, " ".join(mods), names[mods[3]])
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 390" font-family="sans-serif">'
            '<rect width="760" height="390" fill="#fff"/>' + "".join(parts) + title + "</svg>").encode("utf-8")


# ---------------------------------------------------------------- 公共
def _quote(lines, cost, unit_price, qty, item):
    qty = max(1, int(qty))
    return {"item": item, "lines": lines, "unit_cost": cost, "margin": MARGIN if cost else None,
            "unit_price": unit_price, "qty": qty, "total": round(unit_price * qty, 2), "currency": "USD"}


TEMPLATES = {"SH-301": (_sh301, _sh301_eval, _sh301_model), "WQR-105": (_wqr, _wqr_eval, _wqr_model),
             "WQ-CR5": (_cr5, _cr5_eval, _cr5_model)}


def available(tid):
    """这座厂卖得出的模板：物料在这座厂的清单里，而且不是外购件（减速器厂有输出轴、减速器；机器人厂有协作臂）"""
    it = F.ITEMS.get(TEMPLATES[tid][0]()["item"]) if tid in TEMPLATES else None
    return bool(it) and it[1] != "buy"


def templates():
    return [TEMPLATES[k][0]() for k in TEMPLATES if available(k)]


def values(tid, given):
    """补默认值、转数值、夹到范围内"""
    spec = TEMPLATES[tid][0]()
    out = {}
    for p in spec["params"]:
        v = (given or {}).get(p["key"], p["default"])
        if "choices" in p:
            ok = [c["value"] for c in p["choices"]]
            v = type(p["default"])(v) if not isinstance(p["default"], str) else str(v)
            out[p["key"]] = v if v in ok else p["default"]
        else:
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = p["default"]
            out[p["key"]] = min(max(v, p["min"]), p["max"])
    return out


def evaluate(tid, given, qty=1):
    if tid not in TEMPLATES or not available(tid):
        raise KeyError("没有这个模板")
    v = values(tid, given)
    return dict(TEMPLATES[tid][1](v, qty), values=v)


def model_key(tid, given):
    return hashlib.sha256(json.dumps([tid, values(tid, given)], sort_keys=True).encode()).hexdigest()[:24]


def model(tid, given):
    return TEMPLATES[tid][2](values(tid, given))
