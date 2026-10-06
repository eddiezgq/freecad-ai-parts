# -*- coding: utf-8 -*-
"""从工艺规程的一道工序出发编程（第 13 轮 C3、C4）：
  plan_turn / plan_slot / plan_mill  →  “编程单” spec（参数表，每个值注明出处：工艺规程、设计、默认）
  generate(spec)                       →  每次装夹一个程序：G 代码、加工时间、仿真比对、检查

编程单是普通的 dict，网页上显示成表格，可以改；改了的值出处变成“手改”，并提示与工艺规程不一致。
尺寸一律按公差带中间编程（例如 Ø35.3 0/−0.039 编 Ø35.2805）。"""
import math
import re

import numpy as np

from cae import cam, cam_post, cam_power, cam_sim

MODE_CN = {"rough": "粗车", "finish": "精车"}

# 工艺规程没给切削参数时用的默认值（教学示意值：45 钢调质，硬质合金车刀 / 高速钢键槽铣刀、麻花钻 / 硬质合金立铣刀）
DEFAULTS = {
    "turn_rough": {"vc": 120.0, "f": 0.3, "ap": 2.5, "tool": "外圆车刀（硬质合金）"},
    "turn_finish": {"vc": 150.0, "f": 0.15, "ap": 0.5, "tool": "外圆精车刀（硬质合金）"},
    "slot": {"vc": 25.0, "fz": 0.03, "z": 2, "ap": 1.0, "tool": "键槽铣刀（高速钢）"},
    "endmill": {"vc": 100.0, "fz": 0.04, "z": 4, "ap_d": 0.5, "stepover": 0.45, "tool": "立铣刀（硬质合金）"},
    "drill": {"vc": 20.0, "f": 0.12, "tool": "麻花钻（高速钢）"},
}
ALU = ("6061", "7075", "铝")
ENDMILLS = [20.0, 16.0, 12.0, 10.0, 8.0, 6.0, 5.0, 4.0, 3.0]
AXIAL_ALLOW = 0.2          # 粗车时轴肩留的轴向余量（工艺规程没写，默认）
MAX_RPM_DEFAULT = 3000     # 卡盘工件的限速（G50）


def mid(size, es=0.0, ei=0.0):
    """公差带中间值"""
    return round(float(size) + (float(es or 0) + float(ei or 0)) / 2, 4)


def _src(d, k, text):
    d.setdefault("sources", {})[k] = text


# ---------------------------------------------------------------- 工艺规程
def turning_ops(plan):
    return [o for o in plan["operations"] if cam_post.MACHINES.get(cam_post.machine_of(o.get("workstation")) or "", {}).get("kind") == "lathe"]


def op_by_seq(plan, seq):
    for o in plan["operations"]:
        if int(o["seq"]) == int(seq):
            return o
    raise ValueError("工艺规程里没有工序 {}".format(seq))


def op_length(op, default):
    m = re.findall(r"总长\s*(\d+(?:\.\d+)?)", op.get("content", ""))
    return float(m[-1]) if m else float(default)


def size_map(plan, op):
    """本工序各外圆的编程直径：图纸公称尺寸 → 本工序尺寸（公差带中间）；
    没列在工序里的直径按“同一工序的车削余量”加：本工序尺寸 − 最后一道车削工序尺寸（磨削余量不算）"""
    nominal = {f["name"]: float(f["size_mm"]) for f in plan.get("drawing", [])}
    tops = [o for o in turning_ops(plan) if o.get("features")]
    last = max(tops, key=lambda o: int(o["seq"])) if tops else op
    lastf = {f["name"]: mid(f["size_mm"], f.get("es_mm"), f.get("ei_mm")) for f in last.get("features", [])}
    out, extra = {}, 0.0
    for f in op.get("features", []):
        if f["name"] in nominal:
            out[round(nominal[f["name"]], 3)] = (mid(f["size_mm"], f.get("es_mm"), f.get("ei_mm")), f["name"])
            if f["name"] in lastf:
                extra = max(extra, mid(f["size_mm"], f.get("es_mm"), f.get("ei_mm")) - lastf[f["name"]])
    return out, round(extra, 4), int(last["seq"]) == int(op["seq"])


def runs_of(prof):
    """轮廓里的圆柱段（水平段）[(t0, t1, d)]"""
    out = []
    for (t0, d0), (t1, d1) in zip(prof, prof[1:]):
        if abs(d1 - d0) < 1e-9 and t1 - t0 > 1e-6:
            out.append((t0, t1, d0))
    return out


def op_profile(design, sizes, extra, keep_chamfer, L_op, axial=0.0):
    """设计轮廓 → 本工序轮廓：直径换成本工序尺寸；两端各加 (L_op − L)/2；
    轴肩向小直径一侧让出轴向余量 axial；粗车（keep_chamfer=False）不车倒角"""
    L = design[-1][0]
    e = (L_op - L) / 2
    runs = runs_of(design)
    if not runs:
        raise ValueError("轮廓里没有圆柱段")
    t_first, t_last = runs[0][0], runs[-1][1]

    def new_d(d):
        hit = sizes.get(round(d, 3))
        return hit[0] if hit else round(d + extra, 4)

    def run_at(t, d):
        cand = [r for r in runs if (abs(t - r[0]) < 1e-6 or abs(t - r[1]) < 1e-6 or r[0] < t < r[1]) and abs(r[2] - d) < 1e-9]
        if cand:
            return cand[0]
        return min(runs, key=lambda r: min(abs(t - r[0]), abs(t - r[1])))

    pts = []
    for t, d in design:
        r = run_at(t, d)
        on_run = abs(r[2] - d) < 1e-9
        if not keep_chamfer and not on_run:
            continue
        dd = new_d(r[2]) + (d - r[2])
        if t <= t_first + 1e-9:
            tt = t
        elif t >= t_last - 1e-9:
            tt = t + 2 * e
        else:
            tt = t + e
        # 轴肩：同一 t 上另一个圆柱段，大直径一侧向小直径一侧让出 axial
        other = [q for q in runs if q is not r and (abs(q[0] - t) < 1e-6 or abs(q[1] - t) < 1e-6) and abs(q[2] - r[2]) > 1e-9]
        if other and axial:
            o = other[0]
            big_left = r[2] > o[2] if abs(r[1] - t) < 1e-6 else o[2] > r[2]     # 大直径段在轴肩左边？
            tt += axial if big_left else -axial
        pts.append((round(tt, 4), round(dd, 4)))
    if not keep_chamfer:
        pts[0] = (0.0, pts[0][1])
        pts[-1] = (round(L_op, 4), pts[-1][1])
    return cam.simplify(pts)


def plan_turn(plan, seq, design, revision=None, chamfer=None):
    """数控车工序 → 编程单。design：设计轮廓 [(t, d)]（从 STEP 识别，或由设计参数生成）"""
    op = op_by_seq(plan, seq)
    m = cam_post.machine_of(op.get("workstation"))
    tops = sorted(turning_ops(plan), key=lambda o: int(o["seq"]))
    prev = [o for o in tops if int(o["seq"]) < int(seq)]
    sizes, extra, is_last = size_map(plan, op)
    L = design[-1][0]
    L_op = op_length(op, L)
    mode = "finish" if is_last else "rough"
    dflt = DEFAULTS["turn_" + mode]
    cut = dict(op.get("cut") or {})
    spec = {"kind": "turn", "mode": mode, "machine": m or "CNC-L01", "item": plan.get("item"), "revision": revision,
            "material": plan.get("material"),
            "op": {"seq": int(op["seq"]), "name": op["operation"], "minutes": op.get("minutes"), "content": op.get("content", "")},
            "length": L_op, "setups": ["right", "left"],
            "cut": {"vc": float(cut.get("vc_m_min", dflt["vc"])), "f": float(cut.get("f_mm_r", dflt["f"])),
                    "ap": float(cut.get("ap_mm", dflt["ap"])), "max_rpm": MAX_RPM_DEFAULT,
                    "axial_allow": 0.0 if is_last else AXIAL_ALLOW, "radial_allow": 0.0},
            "tool": {"n": 2 if is_last else 1, "name": (op.get("tools") or dflt["tool"]).split("，")[0]}}
    for k, key in (("vc", "vc_m_min"), ("f", "f_mm_r"), ("ap", "ap_mm")):
        _src(spec, "cut." + k, "工艺规程 {} 工序 cut.{}".format(op["seq"], key) if key in cut else "默认（工艺规程没给）")
    _src(spec, "cut.max_rpm", "默认：卡盘夹持限速 {} r/min".format(MAX_RPM_DEFAULT))
    _src(spec, "cut.axial_allow", "精车不留" if is_last else "默认：粗车轴肩留 {} mm 给精车".format(AXIAL_ALLOW))
    _src(spec, "cut.radial_allow", "默认 0：本工序尺寸里已经含了下一道工序的余量")
    _src(spec, "length", "工艺规程 {} 工序内容“总长”".format(op["seq"]) if re.search(r"总长", op.get("content", "")) else "设计总长")
    _src(spec, "tool", "工艺规程 {} 工序 tools".format(op["seq"]) if op.get("tools") else "默认")
    spec["profile"] = op_profile(design, sizes, extra, is_last, L_op, spec["cut"]["axial_allow"])
    spec["sizes"] = [{"name": n, "design": k, "op": v} for k, (v, n) in sorted(sizes.items())]
    spec["extra"] = extra
    spec["unmapped"] = sorted({round(d, 3) for _, _, d in runs_of(design)} - set(sizes))      # 工序里没列出的直径（按 extra 加）
    _src(spec, "profile", "设计轮廓；直径按工艺规程 {} 工序尺寸（公差带中间），其余直径加 {} mm".format(op["seq"], extra))
    if prev:
        p = prev[-1]
        psz, pex, _ = size_map(plan, p)
        pl = op_length(p, L)
        spec["stock"] = {"kind": "profile", "length": pl, "from_seq": int(p["seq"]),
                         "profile": op_profile(design, psz, pex, False, pl, AXIAL_ALLOW)}
        _src(spec, "stock", "上一道车削工序 {} 的尺寸".format(p["seq"]))
    else:
        b = plan.get("blank") or {}
        dd = float(re.sub(r"[^\d.]", "", str(b.get("spec", "50"))) or 50)
        spec["stock"] = {"kind": "bar", "d": dd, "length": float(b.get("length_mm", L_op + 4))}
        _src(spec, "stock", "工艺规程毛坯 {} {}×{}".format(b.get("kind", ""), b.get("spec", ""), b.get("length_mm", "")))
    return spec


def generic_turn_plan(design, item="零件", stock_d=None, finish_allow=0.5, machine="数控车床 CNC-L01"):
    """没有工艺规程的回转零件（上传的 STEP）：按“粗车（单边留 finish_allow）→ 精车”两道工序编，毛坯是比最大直径大 4 mm 的圆钢"""
    ds = sorted({round(d, 3) for _, _, d in runs_of(design)})
    L = design[-1][0]
    stock_d = stock_d or math.ceil(max(ds) + 4)
    feats = lambda a: [{"name": "Ø{:g}".format(d), "size_mm": round(d + 2 * a, 4), "es_mm": 0, "ei_mm": 0} for d in ds]   # noqa: E731
    return {"item": item, "material": "45", "blank": {"kind": "圆钢", "spec": "Ø{:g}".format(stock_d), "length_mm": L + 4},
            "drawing": feats(0),
            "operations": [
                {"seq": 10, "operation": "粗车 Rough turning", "workstation": machine, "features": feats(finish_allow),
                 "content": "车端面、粗车各外圆，单边留 {:g}，总长 {:g}".format(finish_allow, L + 1),
                 "cut": {"vc_m_min": DEFAULTS["turn_rough"]["vc"], "f_mm_r": DEFAULTS["turn_rough"]["f"], "ap_mm": DEFAULTS["turn_rough"]["ap"]}},
                {"seq": 20, "operation": "精车 Finish turning", "workstation": machine, "features": feats(0),
                 "content": "精车各外圆、轴肩与倒角，总长 {:g}".format(L),
                 "cut": {"vc_m_min": DEFAULTS["turn_finish"]["vc"], "f_mm_r": DEFAULTS["turn_finish"]["f"], "ap_mm": finish_allow}}]}


def plan_slot(plan, seq, design_params, revision=None):
    """铣键槽工序 → 编程单。design_params：设计台参数（segments、keyway）"""
    op = op_by_seq(plan, seq)
    kw = design_params.get("keyway")
    if not kw:
        raise ValueError("设计里没有键槽")
    segs = design_params["segments"]
    t0 = sum(l for _, l in segs[:kw["segment"]])
    d_nom = float(segs[kw["segment"]][0])
    # 键槽所在外圆：最后一道车削工序的尺寸（公差带中间）
    tops = [o for o in turning_ops(plan) if o.get("features") and int(o["seq"]) < int(seq)]
    D = d_nom
    for o in sorted(tops, key=lambda o: int(o["seq"])):
        sz, ex, _ = size_map(plan, o)
        D = sz.get(round(d_nom, 3), (round(d_nom + ex, 4), ""))[0]
    m = re.search(r"H\s*=\s*([\d.]+)\s*[（(]\s*([−\-+]?[\d.]+)\s*/\s*([−\-+]?[\d.]+)", op.get("content", ""))
    spec = {"kind": "slot", "machine": cam_post.machine_of(op.get("workstation")) or "KEY-01", "item": plan.get("item"),
            "revision": revision, "material": plan.get("material"),
            "op": {"seq": int(op["seq"]), "name": op["operation"], "minutes": op.get("minutes"), "content": op.get("content", "")}}
    if m:
        H = mid(float(m.group(1)), float(m.group(2).replace("−", "-")), float(m.group(3).replace("−", "-")))
        depth = round(D - H, 4)
        _src(spec, "depth", "工艺规程 {} 工序：H = {}（公差带中间 {}），槽深 = Ø{} − H".format(op["seq"], m.group(1), H, D))
    else:
        depth = float(kw["t"])
        _src(spec, "depth", "设计槽深 t（工艺规程没给 H）")
    b, Lk = float(kw["b"]), float(kw["L"])
    dflt = DEFAULTS["slot"]
    tool_d = b
    spec.update({"width": b, "length": Lk, "depth": depth, "a": [-(Lk - b) / 2, 0.0], "b": [(Lk - b) / 2, 0.0],
                 "stock": {"cyl_r": D / 2, "box": [-(Lk / 2 + 15), -D / 2, Lk / 2 + 15, D / 2]},
                 "x0_from_left": t0 + float(segs[kw["segment"]][1]) / 2,
                 "tool": {"n": 1, "name": "{} Ø{:g}".format((op.get("tools") or dflt["tool"]).split(" Ø")[0], tool_d), "d": tool_d},
                 "cut": {"vc": dflt["vc"], "fz": dflt["fz"], "z": dflt["z"], "ap": dflt["ap"]}})
    _src(spec, "width", "设计键宽 b")
    _src(spec, "length", "设计槽长 L")
    _src(spec, "stock", "精车后的外圆 Ø{}".format(D))
    for k in ("vc", "fz", "z", "ap"):
        _src(spec, "cut." + k, "默认（工艺规程这道工序没给切削参数）")
    _src(spec, "x0_from_left", "工件坐标系 X0 在键槽中心（距左端面），Y0 在轴线，Z0 在外圆最高点")
    return spec


def pick_endmill(poly, max_d=20.0):
    """型腔用多大的刀：先找能把型腔铣干净（转角圆角不小于刀具半径）的最大标准刀；
    型腔有尖角、怎么都铣不干净时，取转角残留面积不超过 2% 的最大刀（尖角留给线切割、电火花或改设计）"""
    for need in (0.999, 0.98):
        for d in ENDMILLS:
            if d > max_d:
                continue
            inner = poly.buffer(-d / 2, join_style=1)
            if not inner.is_empty and inner.buffer(d / 2, join_style=1).area >= need * poly.area:
                return d
    return ENDMILLS[-1]


def plan_mill(features, machine="VMC-01", material="45", stock_margin=2.0, item=None):
    """2.5 轴铣削件（从 STEP 识别的特征）→ 编程单：外轮廓（毛坯比外轮廓大时）、各型腔、钻孔"""
    from shapely.geometry import shape
    alu = any(a in str(material) for a in ALU)
    k = 3.0 if alu else 1.0
    ops = []
    outline = shape(features["outline"]) if features.get("outline") else None
    H = features["top"] - features["bottom"]
    em = DEFAULTS["endmill"]
    n = 1
    if outline is not None and stock_margin > 0:
        d = 10.0
        ops.append({"type": "contour", "depth": round(H + 0.5, 3), "tool": {"n": n, "name": "立铣刀 Ø{:g}".format(d), "d": d},
                    "cut": {"vc": em["vc"] * k, "fz": em["fz"], "z": em["z"], "ap": d * em["ap_d"]}})
        n += 1
    for i, p in enumerate(features["pockets"]):
        d = pick_endmill(shape(p["polygon"]))
        ops.append({"type": "pocket", "index": i, "depth": p["depth"], "tool": {"n": n, "name": "立铣刀 Ø{:g}".format(d), "d": d},
                    "cut": {"vc": em["vc"] * k, "fz": em["fz"], "z": em["z"], "ap": d * em["ap_d"], "stepover": em["stepover"]}})
        n += 1
    groups = {}
    for h in features["holes"]:
        groups.setdefault(round(h["d"], 3), []).append(h)
    dr = DEFAULTS["drill"]
    for d, hs in sorted(groups.items()):
        depth = max(h["depth"] for h in hs) + (0.3 * d if any(h["through"] for h in hs) else 0)   # 通孔多钻出钻尖长度
        ops.append({"type": "drill", "holes": [[h["x"], h["y"]] for h in hs], "depth": round(depth, 3),
                    "peck": round(d, 3) if depth > 3 * d else 0.0, "tool": {"n": n, "name": "麻花钻 Ø{:g}".format(d), "d": d},
                    "cut": {"vc": dr["vc"] * k, "f": dr["f"]}})
        n += 1
    bx = features["bbox"]
    spec = {"kind": "mill25", "machine": machine, "item": item, "material": material, "features": features, "ops": ops,
            "stock": {"box": [bx[0] - stock_margin, bx[1] - stock_margin, bx[3] + stock_margin, bx[4] + stock_margin],
                      "top": features["top"]}}
    _src(spec, "ops", "按识别出的特征自动排：外轮廓 → 型腔 → 钻孔；型腔刀具取放得进、转角残留 ≤ 2% 的最大标准立铣刀；"
                      "切削参数为默认值（{}）".format("铝合金：线速度 ×3" if alu else "钢"))
    return spec


# ---------------------------------------------------------------- 生成
def _prog(spec, number, title, ops, extra_header=None):
    h = {"item": spec.get("item"), "revision": spec.get("revision"),
         "operation": "{} {}".format(spec["op"]["seq"], spec["op"]["name"]) if spec.get("op") else None}
    h.update(extra_header or {})
    return {"machine": spec["machine"], "number": number, "title": title, "header": h, "ops": ops}


def _turn_setup(spec, side):
    c = spec["cut"]
    L_op = spec["length"]
    tgt, Lreg = cam.setup_profile(spec["profile"], side)
    if not tgt:
        return None
    ra = float(c.get("radial_allow") or 0) if spec["mode"] == "rough" else 0.0      # “再留 0.3 余量”：在本工序尺寸外再留（单边）
    st = spec["stock"]
    if st["kind"] == "bar":
        e = (st["length"] - L_op) / 2
        stock_sim = {"d": st["d"], "z_right": e, "z_left": -(L_op + e)}
        stock_d = st["d"]
    else:
        e = (st["length"] - L_op) / 2
        sp = st["profile"]
        Lp = sp[-1][0]
        if side == "right":
            zp = [(t - e - L_op, d) for t, d in reversed(sp)]
        else:
            zp = [(-(t - e), d) for t, d in sp]
        stock_sim = {"profile": cam.simplify(zp), "d": max(d for _, d in sp), "z_right": e, "z_left": -(Lp + 1)}
        stock_d = max(d for z, d in zp if -Lreg - 1 <= z <= e + 1e-9)
    mv = []
    if e > 1e-3:
        mv += cam.turn_face(stock_d, e, max(min(c["ap"], 2.0), 0.2), c["f"])
    if spec["mode"] == "rough":
        mv += cam.turn_rough(tgt, stock_d, c["ap"], c["f"], ra, 0.0)
    else:
        mv += cam.turn_finish(tgt, stock_d, c["f"])
    side_cn = "右端（第一次装夹）" if side == "right" else "左端（调头装夹）"
    ops = [{"tool": spec["tool"], "spindle": {"css": c["vc"], "max_rpm": c["max_rpm"]}, "moves": mv, "title": side_cn}]
    if ra > 0:
        tgt = cam.with_allowance(tgt, ra, 0.0)
    return {"side": side, "title": side_cn, "target": tgt, "region_mm": Lreg, "face_mm": e, "stock_sim": stock_sim, "ops": ops}


def basic_time_min(L, i, vc, d, f):
    """工艺规程的基本时间公式 t_b = L·i / (n·f)，n = 1000·vc / (π·d)"""
    n = 1000.0 * vc / (math.pi * d)
    return L * i / (n * f)


def _path(parsed):
    """回放用的刀位：[快移 0 / 切削 1, x, y, z, 行号, 到这一段结束的累计时间 s, 刀号]；车床的 x 是直径"""
    out, t = [], 0.0
    if parsed["moves"]:
        a = parsed["moves"][0]["a"]
        out.append([0, round(a[0], 3), round(a[1], 3), round(a[2], 3), parsed["moves"][0]["line"], 0.0, parsed["moves"][0]["tool"]])
    for m in parsed["moves"]:
        t += m.get("dt", 0.0)
        b = m["b"]
        out.append([0 if m["t"] == "rapid" else 1, round(b[0], 3), round(b[1], 3), round(b[2], 3), m["line"], round(t, 3), m["tool"]])
    return out


def _summ_turn(sim, target):
    z, r = sim["z"], sim["r"]
    step = max(1, len(z) // 1500)
    return {"z": [round(float(x), 3) for x in z[::step]], "r": [round(float(x), 4) for x in r[::step]],
            "target": [[float(a), float(b)] for a, b in target],
            "dev_min": round(sim.get("dev_min", 0.0), 4), "dev_max": round(sim.get("dev_max", 0.0), 4),
            "under_z": sim.get("under_z"), "ap_max": round(sim["ap_max"], 3), "face_left": round(sim.get("face_left", 0.0), 4)}


def _summ_mill(sim):
    H = sim["H"].copy()
    H[~sim["inside"]] = np.nan
    return {"x0": float(sim["x"][0]), "y0": float(sim["y"][0]), "h": float(sim["h"]), "nx": int(H.shape[0]), "ny": int(H.shape[1]),
            "dev_min": round(sim.get("dev_min", 0.0), 4), "dev_max": round(sim.get("dev_max", 0.0), 4), "over": sim.get("over", 0),
            "under": int(sim["under_mask"].sum()) if "under_mask" in sim else None, "ap_max": round(sim["ap_max"], 3),
            "_H": H}


def generate(spec, number=None):
    """编程单 → 程序列表（每次装夹一个）。每个：G 代码、时间、检查、仿真摘要"""
    out = []
    if spec["kind"] == "turn":
        base = number or 1000 + 10 * int(spec["op"]["seq"])
        for k, side in enumerate(spec.get("setups", ["right", "left"])):
            su = _turn_setup(spec, side)
            if not su:
                continue
            prog = _prog(spec, base + k + 1, "{} {} {}".format(spec.get("item") or "", spec["op"]["name"], su["title"]), su["ops"],
                         {"stock": "Ø{:g}".format(su["stock_sim"]["d"])})
            g = cam_post.post(prog)
            tools = {spec["tool"]["n"]: {"kind": "turn"}}
            r = cam_sim.run(g, spec["machine"], su["stock_sim"], tools, target=su["target"])
            pw, pdet = cam_power.check("turn", spec.get("material"), spec["machine"], [(
                "{} {}".format(MODE_CN[spec["mode"]], su["title"][:2]), {"vc": spec["cut"]["vc"], "f": spec["cut"]["f"],
                                                                        "ap": max(r["sim"]["ap_max"], 1e-3)})])
            r["checks"] += pw
            out.append({"setup": side, "title": su["title"], "number": prog["number"], "gcode": g, "time": r["time"], "path": _path(r["parsed"]),
                        "stock": su["stock_sim"],
                        "checks": r["checks"], "sim": _summ_turn(r["sim"], su["target"]), "region_mm": su["region_mm"],
                        "face_mm": su["face_mm"], "lines": len(g.splitlines()), "power": pdet})
        c = spec["cut"]
        dmax = max(d for _, d in spec["profile"])
        st = spec["stock"]
        d0 = st.get("d") or max(d for _, d in st["profile"])
        passes = max(1, math.ceil((d0 - min(d for _, d in spec["profile"])) / 2 / max(c["ap"], 1e-6) - 1e-9)) if spec["mode"] == "rough" else 1
        spec["compare"] = {"plan_minutes": spec["op"].get("minutes"),
                           "program_minutes": round(sum(p["time"]["total_s"] for p in out) / 60, 2),
                           "basic_minutes": round(basic_time_min(spec["length"] + 4, passes, c["vc"], d0 if spec["mode"] == "rough" else dmax, c["f"]), 2)}
    elif spec["kind"] == "slot":
        c = spec["cut"]
        rpm = cam.spindle_rpm(c["vc"], spec["tool"]["d"], cam_post.MACHINES[spec["machine"]]["max_rpm"])
        F = round(cam.mill_feed(c["fz"], c["z"], rpm), 1)
        mv = cam.mill_slot(spec["a"], spec["b"], spec["width"], spec["depth"], spec["tool"]["d"], c["ap"], F, F)    # 斜线下刀很缓（每层 1 mm 走 30 多 mm），用同一进给
        prog = _prog(spec, number or 1000 + 10 * int(spec["op"]["seq"]) + 1, "{} 铣键槽".format(spec.get("item") or ""),
                     [{"tool": spec["tool"], "spindle": {"rpm": round(rpm)}, "moves": mv, "title": "键槽", "safe": 30.0}])
        g = cam_post.post(prog)
        from shapely import contains_xy
        from shapely.geometry import LineString
        slot = LineString([tuple(spec["a"]), tuple(spec["b"])]).buffer(spec["width"] / 2, quad_segs=64)
        R0 = spec["stock"]["cyl_r"]
        dep = spec["depth"]

        def T(X, Y):
            t = np.sqrt(np.clip(R0 ** 2 - Y ** 2, 0, None)) - R0
            t[contains_xy(slot.buffer(-0.05), X, Y)] = -dep
            t[contains_xy(slot.buffer(0.05), X, Y) & ~contains_xy(slot.buffer(-0.05), X, Y)] = np.nan
            return t
        r = cam_sim.run(g, spec["machine"], spec["stock"], {1: {"kind": "endmill", "d": spec["tool"]["d"]}}, T)
        pw, pdet = cam_power.check("slot", spec.get("material"), spec["machine"], [("铣键槽", {
            "fz": c["fz"], "ap": max(r["sim"]["ap_max"], 1e-3), "ae": spec["width"], "D": spec["tool"]["d"], "vf": F})])
        r["checks"] += pw
        out.append({"setup": "slot", "title": "键槽", "number": prog["number"], "gcode": g, "time": r["time"], "checks": r["checks"],
                    "path": _path(r["parsed"]), "tools": {"1": {"kind": "endmill", "d": spec["tool"]["d"]}},
                    "sim": _summ_mill(r["sim"]), "rpm": round(rpm), "feed": F, "lines": len(g.splitlines()), "power": pdet})
        spec["compare"] = {"plan_minutes": spec["op"].get("minutes"), "program_minutes": round(r["time"]["total_s"] / 60, 2)}
    elif spec["kind"] == "mill25":
        from shapely.geometry import shape
        from cae import cam_geom
        feat = spec["features"]
        m = cam_post.MACHINES[spec["machine"]]
        ops, tools = [], {}
        for o in spec["ops"]:
            c, t = o["cut"], o["tool"]
            rpm = cam.spindle_rpm(c["vc"], t["d"], m["max_rpm"])
            if o["type"] == "drill":
                F = round(c["f"] * rpm, 1)
                mv = cam.drill([tuple(h) for h in o["holes"]], o["depth"], o.get("peck", 0), F)
                tools[t["n"]] = {"kind": "drill", "d": t["d"]}
            else:
                F = round(cam.mill_feed(c["fz"], c["z"], rpm), 1)
                tools[t["n"]] = {"kind": "endmill", "d": t["d"]}
                if o["type"] == "contour":
                    mv = cam.mill_contour(shape(feat["outline"]), o["depth"], t["d"], c["ap"], F)
                else:
                    p = feat["pockets"][o["index"]]
                    mv = cam.mill_pocket(shape(p["polygon"]), o["depth"], t["d"], c.get("stepover", 0.45), c["ap"], F, round(F / 3, 1))
            o["rpm"], o["feed"] = round(rpm), F
            ops.append({"tool": t, "spindle": {"rpm": round(rpm)}, "moves": mv, "title": {"contour": "外轮廓", "pocket": "型腔",
                                                                                         "drill": "钻孔"}[o["type"]]})
        prog = {"machine": spec["machine"], "number": number or 5001, "title": "{} 铣削".format(spec.get("item") or "零件"),
                "header": {"item": spec.get("item")}, "ops": ops}
        g = cam_post.post(prog)
        r = cam_sim.run(g, spec["machine"], spec["stock"], tools, cam_geom.target_fn(feat))
        margin = max(0.5, min(spec["stock"]["box"][2] - feat["bbox"][3], feat["bbox"][0] - spec["stock"]["box"][0]))
        items = []
        for o in spec["ops"]:
            c, t = o["cut"], o["tool"]
            nm = {"contour": "外轮廓", "pocket": "型腔", "drill": "钻孔"}[o["type"]]
            if o["type"] == "drill":
                items.append((nm, {"type": "drill", "vc": c["vc"], "f": c["f"], "D": t["d"]}))
            else:
                items.append((nm, {"fz": c["fz"], "ap": min(c["ap"], o["depth"]), "D": t["d"], "vf": o["feed"],
                                   "ae": t["d"] if o["type"] == "pocket" else margin}))
        pw, pdet = cam_power.check("mill", spec.get("material"), spec["machine"], items)
        r["checks"] += pw
        out.append({"setup": "mill", "title": "铣削", "number": prog["number"], "gcode": g, "time": r["time"], "checks": r["checks"],
                    "path": _path(r["parsed"]), "tools": {str(k): v for k, v in tools.items()},
                    "sim": _summ_mill(r["sim"]), "lines": len(g.splitlines()), "power": pdet})
        spec["compare"] = {"program_minutes": round(r["time"]["total_s"] / 60, 2)}
    else:
        raise ValueError("未知的编程单类型 {}".format(spec.get("kind")))
    return out
