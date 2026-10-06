# -*- coding: utf-8 -*-
"""热分析的参数化示例零件（第 14 轮 H3）：WQR-105 简化箱体（热平衡）、电脑 CPU 散热片（生活例子）。
build123d 现做 STEP；读入后按几何位置把面分组（箱内壁、外表面、底面、散热片……），自动填好热载荷，并给出教材公式的估算值作对比。"""
import math
import os
import tempfile

# WQR-105：输出 350 N·m、输入 1450 r/min、总传动比 (72/24)·(70/20) = 10.5；
# 效率按濮良贵《机械设计》常用机械传动效率概略值：闭式圆柱齿轮（8 级）0.97 / 级，滚动轴承 0.99 / 对，三对轴承
WQR105 = {"T_out_nm": 350.0, "n_in_rpm": 1450.0, "ratio": 10.5, "eta_gear": 0.97, "eta_bearing": 0.99, "stages": 2, "bearing_pairs": 3}

DEFAULTS = {
    "housing": {"L": 410.0, "W": 150.0, "H": 300.0, "wall": 10.0, "fins": 0, "fin_h": 25.0, "fin_t": 6.0, "load_pct": 100.0},
    "heatsink": {"base": 60.0, "base_t": 6.0, "fins": 9, "fin_h": 30.0, "fin_t": 1.5, "pad": 30.0, "power_w": 65.0},
    "agv_box": {"L": 400.0, "W": 300.0, "H": 220.0, "wall": 6.0, "vent_w": 180.0, "vent_h": 50.0, "layout": 1, "p_drive": 60.0, "p_pc": 30.0},
}
LABELS = {"housing": "WQR-105 简化箱体（减速器热平衡）", "heatsink": "电脑 CPU 散热片（生活例子）",
          "agv_box": "AGV 小车电控箱通风（机器人例子）"}
AGV_LAYOUTS = {1: "前下进、后上出", 2: "前上进、后上出", 3: "前下进、后下出"}
PARAM_NAMES = {
    "housing": {"L": "外形长 mm", "W": "外形宽 mm", "H": "外形高 mm", "wall": "壁厚 mm", "fins": "每个长侧面的散热筋数",
                "fin_h": "散热筋高 mm", "fin_t": "散热筋厚 mm", "load_pct": "负载率 %（额定 350 N·m = 100）"},
    "heatsink": {"base": "底板边长 mm", "base_t": "底板厚 mm", "fins": "散热片数", "fin_h": "片高 mm", "fin_t": "片厚 mm",
                 "pad": "CPU 接触面边长 mm", "power_w": "CPU 发热功率 W"},
    "agv_box": {"L": "箱长 mm（沿行驶方向）", "W": "箱宽 mm", "H": "箱高 mm", "wall": "壁厚 mm", "vent_w": "风口宽 mm", "vent_h": "风口高 mm",
                "layout": "风口布置：1 前下进后上出 / 2 前上进后上出 / 3 前下进后下出", "p_drive": "电机驱动器发热 W", "p_pc": "工控机发热 W"},
}
AGV_PARTS = {"drive": (150.0, 100.0, 70.0, -0.18, -0.12), "pc": (120.0, 110.0, 45.0, 0.20, 0.12)}   # 长、宽、高，箱内位置（占内长 / 内宽的比例）


def params_of(key, p=None):
    out = dict(DEFAULTS[key])
    for k, v in (p or {}).items():
        if k in out:
            out[k] = float(v)
    if key == "housing":
        if out["wall"] < 4 or out["wall"] > min(out["W"], out["H"]) / 4:
            raise ValueError("壁厚要在 4 mm 到外形的 1/4 之间")
        out["fins"] = int(max(0, min(out["fins"], 20)))
    elif key == "agv_box":
        out["layout"] = int(out["layout"]) if int(out["layout"]) in AGV_LAYOUTS else 1
        if not 4 <= out["wall"] <= 12:
            raise ValueError("壁厚要在 4–12 mm（网格要分得开）")
        if out["L"] < 300 or out["W"] < 240 or out["H"] < 140:
            raise ValueError("箱子太小，放不下驱动器和工控机（至少 300 × 240 × 140 mm）")
        if out["vent_w"] > out["W"] - 2 * out["wall"] - 20 or out["vent_h"] > out["H"] / 2 - out["wall"] - 10 or out["vent_h"] < 15:
            raise ValueError("风口尺寸不合适：宽不超过箱内宽，高 15 mm 到箱高的一半")
    else:
        out["fins"] = int(max(2, min(out["fins"], 30)))
        gap = (out["base"] - out["fins"] * out["fin_t"]) / (out["fins"] - 1)
        if gap < 1.0:
            raise ValueError("散热片太密：片间距只有 {:.1f} mm".format(gap))
        if out["pad"] > out["base"]:
            raise ValueError("CPU 接触面不能比底板大")
    return out


def loss_w(p):
    """箱体内的发热 = 输入功率 × (1 − η)"""
    d = WQR105
    eta = d["eta_gear"] ** d["stages"] * d["eta_bearing"] ** d["bearing_pairs"]
    n_out = d["n_in_rpm"] / d["ratio"]
    P_out = d["T_out_nm"] * p["load_pct"] / 100 * n_out * 2 * math.pi / 60
    P_in = P_out / eta
    return P_in * (1 - eta), {"eta": eta, "P_out_w": P_out, "P_in_w": P_in, "n_out_rpm": n_out}


def tempfile_step(shape):
    import build123d as bd
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "part.step")
        bd.export_step(shape, f)
        return open(f, "rb").read()


def build(key, p):
    import build123d as bd
    if key == "housing":
        L, W, H, t = p["L"], p["W"], p["H"], p["wall"]
        with bd.BuildPart() as part:
            bd.Box(L, W, H, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
            with bd.Locations((0, 0, t)):
                bd.Box(L - 2 * t, W - 2 * t, H - 2 * t, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN), mode=bd.Mode.SUBTRACT)
            n = int(p["fins"])
            if n:
                pitch = (L - 2 * t) / n
                hz = H - 2 * t
                for side in (-1, 1):
                    locs = [(-(L - 2 * t) / 2 + pitch * (i + 0.5), side * (W / 2 + p["fin_h"] / 2), t + hz / 2) for i in range(n)]
                    with bd.Locations(*locs):
                        bd.Box(p["fin_t"], p["fin_h"], hz)
        shape = part.part
    elif key == "agv_box":
        shape = _agv_box(p)
    else:
        b, bt, n, fh, ft, pad = p["base"], p["base_t"], int(p["fins"]), p["fin_h"], p["fin_t"], p["pad"]
        with bd.BuildPart() as part:
            bd.Box(b, b, bt, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
            pitch = (b - ft) / (n - 1)
            with bd.Locations(*[(-(b - ft) / 2 + i * pitch, 0, bt + fh / 2) for i in range(n)]):
                bd.Box(ft, b, fh)
            with bd.Locations((0, 0, 0)):                     # CPU 贴合的凸台（0.5 mm），底面就是发热面
                bd.Box(pad, pad, 0.5, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MAX))
        shape = part.part
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, key + ".step")
        bd.export_step(shape, f)
        return open(f, "rb").read()


def _vent_z(p, where):
    t, vh = p["wall"], p["vent_h"]
    return t + 10 + vh / 2 if where == "low" else p["H"] - t - 10 - vh / 2


def _agv_vents(p):
    """(进风口 z, 出风口 z)：进风在前面（−X，迎风），出风在后面（+X）"""
    return {1: ("low", "high"), 2: ("high", "high"), 3: ("low", "low")}[int(p["layout"])]


def _agv_box(p):
    """电控箱：铝板箱体，前面一个进风口、后面一个出风口；箱底上放电机驱动器和工控机（简化成实心块，和箱底连成一体）"""
    import build123d as bd
    L, W, H, t = p["L"], p["W"], p["H"], p["wall"]
    vin, vout = _agv_vents(p)
    with bd.BuildPart() as part:
        bd.Box(L, W, H, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
        with bd.Locations((0, 0, t)):
            bd.Box(L - 2 * t, W - 2 * t, H - 2 * t, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN), mode=bd.Mode.SUBTRACT)
        for x, where in ((-L / 2 + t / 2, vin), (L / 2 - t / 2, vout)):
            with bd.Locations((x, 0, _vent_z(p, where))):
                bd.Box(t * 3, p["vent_w"], p["vent_h"], mode=bd.Mode.SUBTRACT)
        for (l, w, h, fx, fy) in AGV_PARTS.values():
            with bd.Locations((fx * (L - 2 * t), fy * (W - 2 * t), t)):
                bd.Box(l, w, h, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    return part.part


def groups(key, p, faces):
    """按位置把面分组：返回 {组名: [面号]}"""
    out = {}
    if key == "housing":
        L, W, H, t = p["L"], p["W"], p["H"], p["wall"]
        inner, outer, bottom = [], [], []
        for f in faces:
            c = f["center"]
            if f["kind"] == "plane" and abs(c[2]) < 1e-6 and (f.get("normal") or [0, 0, 0])[2] < -0.5:
                bottom.append(f["id"])
            elif abs(c[0]) <= L / 2 - t + 1e-3 and abs(c[1]) <= W / 2 - t + 1e-3 and t - 1e-3 <= c[2] <= H - t + 1e-3:
                inner.append(f["id"])
            else:
                outer.append(f["id"])
        out = {"inner": inner, "outer": outer, "bottom": bottom}
    elif key == "agv_box":
        L, W, H, t = p["L"], p["W"], p["H"], p["wall"]
        out = {"drive": [], "pc": [], "inner": [], "outer": [], "bottom": []}
        boxes = {k: (fx * (L - 2 * t), fy * (W - 2 * t), l, w, h) for k, (l, w, h, fx, fy) in AGV_PARTS.items()}
        for f in faces:
            c = f["center"]
            if f["kind"] == "plane" and abs(c[2]) < 1e-6:
                out["bottom"].append(f["id"]); continue
            hit = None
            for k, (cx, cy, l, w, h) in boxes.items():
                if abs(c[0] - cx) <= l / 2 + 1e-3 and abs(c[1] - cy) <= w / 2 + 1e-3 and t + 1e-3 < c[2] <= t + h + 1e-3:
                    hit = k
            if hit:
                out[hit].append(f["id"])
            elif abs(c[0]) < L / 2 - t + 1e-3 and abs(c[1]) < W / 2 - t + 1e-3 and t - 1e-3 <= c[2] <= H - t + 1e-3:
                out["inner"].append(f["id"])
            else:
                out["outer"].append(f["id"])                         # 外表面和风口的侧壁
    else:
        pad_face = [f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][2] + 0.5) < 1e-6]
        out = {"pad": pad_face, "rest": [f["id"] for f in faces if f["id"] not in pad_face]}
    return out


def example(key, p, faces):
    """自动填好的热载荷（网页“填入示范题”）与教材公式估算"""
    g = groups(key, p, faces)
    if key == "housing":
        q, info = loss_w(p)
        K = 17.45
        A_txt = (2 * p["L"] * p["H"] + 2 * p["W"] * p["H"] + p["L"] * p["W"]) * 1e-6           # 外表面（不计底面、不计散热筋）
        n = int(p["fins"])
        A_fin = 2 * n * (2 * p["fin_h"] * (p["H"] - 2 * p["wall"]) + p["fin_t"] * p["fin_h"]) * 1e-6 if n else 0.0
        t_oil = 20 + q / (K * (A_txt + 0.5 * A_fin))                    # 教材：散热筋面积按约一半计
        thermal = [{"type": "heat_flux", "faces": g["inner"], "power_w": round(q, 1)},
                   {"type": "convection", "faces": g["outer"], "h_w_m2k": K, "t_inf_c": 20}]
        formula = {"name": "减速器热平衡（濮良贵《机械设计》）：t_油 = t₀ + 1000·P·(1−η)/(K_s·A)",
                   "P_in_kw": round(info["P_in_w"] / 1000, 3), "eta": round(info["eta"], 4), "loss_w": round(q, 1),
                   "K_s": K, "A_m2": round(A_txt + 0.5 * A_fin, 4), "A_fin_m2": round(A_fin, 4), "t0_c": 20, "t_oil_c": round(t_oil, 1),
                   "limit_c": 80, "note": "箱体底面装在机座上不计散热；散热筋面积按一半计（筋间空气流动差）；油温一般不超过 70–80 ℃"}
        return {"material_id": "HT200", "thermal": thermal, "groups": g, "formula": formula,
                "title": "WQR-105 箱体热平衡（{}）".format("{} 条散热筋 / 侧".format(n) if n else "无散热筋"),
                "mesh_mm": round(max(6.0, 1.2 * p["wall"]), 1)}
    if key == "agv_box":
        P = p["p_drive"] + p["p_pc"]
        A_v = p["vent_w"] * p["vent_h"] * 1e-6
        thermal = [{"type": "heat_flux", "faces": g["drive"], "power_w": p["p_drive"]},
                   {"type": "heat_flux", "faces": g["pc"], "power_w": p["p_pc"]},
                   {"type": "convection", "faces": "rest", "h_w_m2k": 5.0, "t_inf_c": 25}]
        formula = {"name": "通风量估算：Q = μ·A·v（流量系数 μ 取 0.3），出风温升 Δt = P/(ρ·c_p·Q)",
                   "loss_w": P, "A_vent_m2": round(A_v, 5), "v_ms": 1.5, "Q_m3s": round(0.3 * A_v * 1.5, 5),
                   "dt_air_c": round(P / (1.18 * 1007 * 0.3 * A_v * 1.5), 1), "t0_c": 25, "limit_c": 60,
                   "note": "小车以 1.5 m/s 行驶，风从前面的风口灌进箱子；μ 是粗估（风口进出的损失、箱内绕流都算进去），实际通风量看流体分析；"
                           "驱动器、工控机一般要求环境温度不超过 50–60 ℃。默认的“其余所有面 h = 5”是箱内几乎不通风时的值，流体分析后换成算出的 h"}
        return {"material_id": "6061-T6", "thermal": thermal, "groups": g, "formula": formula,
                "title": "AGV 电控箱 {}（{:g} W）".format(AGV_LAYOUTS[int(p["layout"])], P), "mesh_mm": round(max(4.0, p["wall"]), 1)}
    h = 50.0
    A = (p["base"] ** 2 * 2 - p["pad"] ** 2 + 4 * p["base"] * p["base_t"]
         + int(p["fins"]) * (2 * p["fin_h"] * p["base"] + 2 * p["fin_h"] * p["fin_t"] + p["fin_t"] * p["base"])) * 1e-6
    thermal = [{"type": "heat_flux", "faces": g["pad"], "power_w": p["power_w"]},
               {"type": "convection", "faces": "rest", "h_w_m2k": h, "t_inf_c": 25}]
    formula = {"name": "粗估（散热片效率按 1）：t = t₀ + P/(h·A)", "loss_w": p["power_w"], "h": h, "A_m2": round(A, 5),
               "t0_c": 25, "t_est_c": round(25 + p["power_w"] / (h * A), 1), "limit_c": 95,
               "note": "h = 50 W/(m²·K) 相当于风扇直吹；不装风扇（自然对流）改成 8 左右再算；CPU 一般限温约 95–100 ℃"}
    return {"material_id": "6061-T6", "thermal": thermal, "groups": g, "formula": formula,
            "title": "CPU 散热片 {} 片 · {:g} W".format(int(p["fins"]), p["power_w"]), "mesh_mm": round(max(1.0, 1.5 * p["fin_t"]), 2)}
