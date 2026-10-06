# -*- coding: utf-8 -*-
"""G 代码读取、加工时间、仿真与检查（第 13 轮 C6）。

不只读本平台生成的程序，也读学生 / 桌面 FreeCAD 写的 FANUC 风格程序：G00/G01/G02/G03、G90/G91、G17/G18、
G20/G21、G28、G50（限速）、G96/G97、G94/G95（铣）、G98/G99（车：每分 / 每转进给；铣：钻孔循环返回平面）、
G80/G81/G83、T、M03/M04/M05/M06/M08/M09/M30、S、F。

仿真：
  车削——沿轴线的半径网格（每 0.02 mm 一格）。外圆车刀按“刀尖在左下角，刀体朝右上”处理：刀尖到过的地方，右边、外面的材料都去掉；
          切槽刀刀宽 w，刀尖在右刀尖，去掉 [z−w, z] 范围内刀尖以外的材料。刀尖圆弧按 0 处理（教学简化）。
  铣削——高度图（XY 网格，每格记录剩下材料的顶面高度）。平底立铣刀按圆柱扫过；钻头按平底处理（不画 118° 钻尖）。
检查：快移碰到材料、和目标（设计或本工序尺寸）比对过切 / 残留、超程、转速超限、G96 没有 G50 限速。
"""
import math
import re

import numpy as np

from cae.cam_post import MACHINES

WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")


# ---------------------------------------------------------------- 读程序
def _strip(line):
    line = re.sub(r"\([^)]*\)", " ", line)
    return line.split(";")[0].strip().upper()


def parse(text, machine):
    """→ {"moves": [...], "tools": [...], "warnings": [...], "rpm_max": ..}
    move：{"t": "rapid"|"feed", "a": (x, y, z), "b": (x, y, z), "line": 行号, "tool": 刀号, "f": 进给, "per_rev": bool,
           "css": 恒线速 m/min 或 None, "rpm": 转速, "smax": G50 限速, "home": 回参考点, "cycle": 钻孔循环}
    车床的 x 是直径，y 恒为 0。"""
    m = MACHINES[machine]
    lathe = m["kind"] == "lathe"
    st = {"pos": [0.0, 0.0, 0.0], "abs": True, "motion": 0, "f": 0.0, "per_rev": lathe, "css": None, "rpm": 0.0,
          "smax": None, "tool": 0, "scale": 1.0, "ret98": True, "plane": 18 if lathe else 17, "spin": False, "pending_tool": 0}
    hx, hz = m.get("home", (m["x"][1], m["z"][1]))
    if lathe:
        st["pos"] = [hx, 0.0, hz]
    else:
        st["pos"] = [0.0, 0.0, m["z"][1]]
    moves, warns, tools, tool_changes = [], [], [], []
    rpm_req = 0.0
    cyc = None

    def emit(t, b, line, **kw):
        a = tuple(st["pos"])
        b = tuple(float(v) for v in b)
        if max(abs(b[i] - a[i]) for i in range(3)) > 1e-9:
            moves.append(dict(t=t, a=a, b=b, line=line, tool=st["tool"], f=st["f"], per_rev=st["per_rev"], css=st["css"],
                              rpm=st["rpm"], smax=st["smax"], spin=st["spin"], **kw))
        st["pos"] = list(b)

    for ln, raw in enumerate(text.splitlines(), 1):
        line = _strip(raw)
        if not line or line in ("%",) or line.startswith("O"):
            continue
        words = WORD.findall(line)
        if not words:
            continue
        g = [round(float(v), 1) for k, v in words if k == "G"]
        mc = [int(float(v)) for k, v in words if k == "M"]
        w = {}
        for k, v in words:
            if k not in "GMN":
                w[k] = float(v)
        for gg in g:
            if gg == 20:
                st["scale"] = 25.4
                warns.append({"line": ln, "level": "warn", "text": "G20 英制：已按 1 in = 25.4 mm 换算"})
            elif gg == 21:
                st["scale"] = 1.0
            elif gg == 90:
                st["abs"] = True
            elif gg == 91:
                st["abs"] = False
            elif gg in (17, 18, 19):
                st["plane"] = int(gg)
            elif gg == 96:
                st["css"] = w.get("S", st["css"])
            elif gg == 97:
                st["css"] = None
                if "S" in w:
                    st["rpm"] = w["S"]
            elif gg == 94:
                st["per_rev"] = False
            elif gg == 95:
                st["per_rev"] = True
            elif gg == 98:
                if lathe:
                    st["per_rev"] = False
                else:
                    st["ret98"] = True
            elif gg == 99:
                if lathe:
                    st["per_rev"] = True
                else:
                    st["ret98"] = False
            elif gg in (0, 1, 2, 3):
                st["motion"] = int(gg)
                cyc = None
            elif gg in (81, 83):
                st["motion"] = int(gg)
            elif gg == 80:
                cyc = None
                st["motion"] = 0
        sc = st["scale"]
        if "F" in w:
            st["f"] = w["F"] * sc
        if "S" in w and 50 not in g and 96 not in g:
            if st["css"] is not None:
                st["css"] = w["S"]
            else:
                st["rpm"] = w["S"]
                rpm_req = max(rpm_req, w["S"])
        if 50 in g:
            if "S" in w:
                st["smax"] = w["S"]
            if "X" in w or "Z" in w:
                warns.append({"line": ln, "level": "warn", "text": "G50 X/Z 设定坐标系：本仿真不处理，请用 G54 或刀补"})
            continue
        if 96 in g and "S" in w:
            st["css"] = w["S"]
        # 换刀
        if "T" in w:
            tv = int(w["T"])
            n = tv // 100 if lathe and tv >= 100 else tv
            if lathe:
                if n != st["tool"]:
                    tool_changes.append(ln)
                st["tool"] = n
                tools.append(n)
            else:
                st["pending_tool"] = n
        if 6 in mc:
            if st["pending_tool"] != st["tool"]:
                tool_changes.append(ln)
            st["tool"] = st["pending_tool"]
            tools.append(st["tool"])
        if 3 in mc or 4 in mc:
            st["spin"] = True
        if 5 in mc:
            st["spin"] = False
        if 28 in g:
            if lathe:
                st["pos"] = [hx, 0.0, hz]
            else:
                emit("rapid", (st["pos"][0], st["pos"][1], m["z"][1]), ln, home=True)
            continue
        if any(k in w for k in "XYZUW") and not (lathe and 28 in g):
            tgt = list(st["pos"])
            for i, a in enumerate("XYZ"):
                if a in w:
                    v = w[a] * sc
                    tgt[i] = v if st["abs"] else tgt[i] + v
            if lathe:
                if "U" in w:
                    tgt[0] += w["U"] * sc
                if "W" in w:
                    tgt[2] += w["W"] * sc
            mo = st["motion"]
            if mo in (81, 83):
                old = cyc or {}
                cyc = {"z": w["Z"] * sc if "Z" in w else old.get("z", 0.0), "r": w["R"] * sc if "R" in w else old.get("r", 2.0),
                       "q": w["Q"] * sc if "Q" in w else old.get("q", 0.0), "init": old.get("init", st["pos"][2])}
                tgt[2] = st["pos"][2]
                x, y = tgt[0], tgt[1]
                z0 = cyc["init"]
                emit("rapid", (x, y, z0), ln, cycle=True)
                emit("rapid", (x, y, cyc["r"]), ln, cycle=True)
                if mo == 83 and cyc["q"] > 0:
                    depth, first = cyc["r"], True
                    while depth > cyc["z"] + 1e-9:            # 每次钻 Q 深，退回 R 平面排屑，再快移到上次深度上方 0.5 mm 继续
                        nd = max(depth - cyc["q"], cyc["z"])
                        if not first:
                            emit("rapid", (x, y, depth + 0.5), ln, cycle=True)
                        emit("feed", (x, y, nd), ln, cycle=True)
                        emit("rapid", (x, y, cyc["r"]), ln, cycle=True)
                        depth, first = nd, False
                else:
                    emit("feed", (x, y, cyc["z"]), ln, cycle=True)
                emit("rapid", (x, y, z0 if st["ret98"] else cyc["r"]), ln, cycle=True)
            elif mo in (2, 3):
                for p in _arc(st, tgt, w, mo, lathe, sc):
                    emit("feed", p, ln, arc=True)
            else:
                emit("rapid" if mo == 0 else "feed", tgt, ln)
                if mo == 1 and st["f"] <= 0:
                    warns.append({"line": ln, "level": "error", "text": "G01 没有进给速度 F"})
        if 30 in mc or 2 in mc:
            break
    return {"moves": moves, "tools": sorted(set(tools)), "tool_changes": tool_changes, "warnings": warns, "rpm_req": rpm_req,
            "lathe": lathe}


def _arc(st, tgt, w, mo, lathe, sc):
    """圆弧插补拆成小直线段（每段 ≤ 3°）"""
    a = st["pos"]
    if lathe:                                   # (u, v) = (z, 半径)
        ua, va, ub, vb = a[2], a[0] / 2, tgt[2], tgt[0] / 2
        ci, cj = w.get("K", 0.0) * sc, w.get("I", 0.0) * sc
    else:
        ua, va, ub, vb = a[0], a[1], tgt[0], tgt[1]
        ci, cj = w.get("I", 0.0) * sc, w.get("J", 0.0) * sc
    cw = mo == 2
    if "R" in w:
        r = w["R"] * sc
        dx, dy = ub - ua, vb - va
        q = math.hypot(dx, dy)
        h = math.sqrt(max(r * r - (q / 2) ** 2, 0.0))
        mx, my = (ua + ub) / 2, (va + vb) / 2
        nx, ny = -dy / max(q, 1e-12), dx / max(q, 1e-12)
        sgn = (-1 if cw else 1) * (1 if r > 0 else -1)
        cu, cv = mx + sgn * h * nx, my + sgn * h * ny
    else:
        cu, cv = ua + ci, va + cj
    t0 = math.atan2(va - cv, ua - cu)
    t1 = math.atan2(vb - cv, ub - cu)
    rad = math.hypot(ua - cu, va - cv)
    if cw:
        while t1 >= t0 - 1e-12:
            t1 -= 2 * math.pi
    else:
        while t1 <= t0 + 1e-12:
            t1 += 2 * math.pi
    if math.hypot(ub - ua, vb - va) < 1e-9:       # 整圆
        t1 = t0 + (-2 * math.pi if cw else 2 * math.pi)
    n = max(2, int(abs(t1 - t0) / math.radians(3)) + 1)
    out = []
    for k in range(1, n + 1):
        t = t0 + (t1 - t0) * k / n
        u, v = cu + rad * math.cos(t), cv + rad * math.sin(t)
        if lathe:
            out.append((2 * v, 0.0, u))
        else:
            out.append((u, v, a[2] + (tgt[2] - a[2]) * k / n))
    out[-1] = tuple(tgt)
    return out


# ---------------------------------------------------------------- 加工时间
def _rpm(mv, x_diam, machine):
    m = MACHINES[machine]
    cap = min(mv["smax"] or m["max_rpm"], m["max_rpm"])
    if mv["css"]:
        return min(1000.0 * mv["css"] / (math.pi * max(abs(x_diam), 1e-3)), cap)
    return min(mv["rpm"], m["max_rpm"])


def move_time(mv, machine, lathe):
    """一段的时间（秒）。快移各轴同时走，取最慢的轴；切削按进给速度，每转进给按当时转速（G96 时随直径变）分段积分"""
    m = MACHINES[machine]
    a, b = mv["a"], mv["b"]
    if lathe:
        d = (abs(b[0] - a[0]) / 2, 0.0, abs(b[2] - a[2]))
    else:
        d = tuple(abs(b[i] - a[i]) for i in range(3))
    if mv["t"] == "rapid":
        rr = m["rapid"]
        return 60.0 * max(d[0] / rr["x"], d[1] / rr.get("y", rr["x"]), d[2] / rr["z"])
    L = math.sqrt(sum(v * v for v in d))
    if not mv["per_rev"]:
        return 60.0 * L / max(mv["f"], 1e-9)
    n = max(1, int(L / 0.5))
    t = 0.0
    for k in range(n):
        x = a[0] + (b[0] - a[0]) * (k + 0.5) / n
        rpm = _rpm(mv, x, machine)
        t += 60.0 * (L / n) / max(mv["f"] * rpm, 1e-9)
    return t


def timing(parsed, machine):
    lathe = parsed["lathe"]
    cut = rap = 0.0
    Lc = Lr = 0.0
    for mv in parsed["moves"]:
        t = move_time(mv, machine, lathe)
        a, b = mv["a"], mv["b"]
        L = math.dist((a[0] / 2, a[2]), (b[0] / 2, b[2])) if lathe else math.dist(a, b)
        if mv["t"] == "rapid":
            rap += t
            Lr += L
        else:
            cut += t
            Lc += L
        mv["dt"] = t
    tc = len(parsed["tool_changes"]) * MACHINES[machine]["tool_change_s"]
    return {"cut_s": cut, "rapid_s": rap, "tool_s": tc, "total_s": cut + rap + tc, "cut_len_mm": Lc, "rapid_len_mm": Lr,
            "tool_changes": len(parsed["tool_changes"])}


# ---------------------------------------------------------------- 检查（机床）
def machine_checks(parsed, machine):
    m = MACHINES[machine]
    out = list(parsed["warnings"])
    lathe = parsed["lathe"]
    axes = (("X", 0, m["x"]), ("Z", 2, m["z"])) if lathe else (("X", 0, m["x"]), ("Y", 1, m["y"]), ("Z", 2, m["z"]))
    seen = set()
    for mv in parsed["moves"]:
        if mv.get("home"):
            continue
        for name, i, (lo, hi) in axes:
            v = mv["b"][i]
            if (v < lo - 1e-6 or v > hi + 1e-6) and (name, mv["line"]) not in seen:
                seen.add((name, mv["line"]))
                out.append({"line": mv["line"], "level": "error",
                            "text": "{} 超程：{}{:.3f}，{} 行程 {:g} ~ {:g}".format(name, name, v, m["name"], lo, hi)})
        if mv["t"] == "feed" and not mv["spin"]:
            if ("spin", 0) not in seen:
                seen.add(("spin", 0))
                out.append({"line": mv["line"], "level": "error", "text": "主轴没有转（缺 M03）就开始切削"})
    if parsed["rpm_req"] > m["max_rpm"]:
        out.append({"line": None, "level": "error", "text": "转速 S{:g} 超过机床最高转速 {}".format(parsed["rpm_req"], m["max_rpm"])})
    if lathe and any(mv["css"] and not mv["smax"] for mv in parsed["moves"]):
        out.append({"line": None, "level": "warn", "text": "用了 G96 恒线速却没有 G50 限速：车到小直径时转速会冲到机床最高转速"})
    for mv in parsed["moves"]:
        if mv["css"] and mv["smax"] and mv["smax"] > m["max_rpm"]:
            out.append({"line": mv["line"], "level": "error", "text": "G50 限速 S{:g} 超过机床最高转速 {}".format(mv["smax"], m["max_rpm"])})
            break
    return out


# ---------------------------------------------------------------- 车削仿真
def _seg_points(a, b, step):
    n = max(1, int(math.ceil(math.dist(a, b) / step)))
    t = np.linspace(0.0, 1.0, n + 1)
    return np.outer(1 - t, a) + np.outer(t, b)


def simulate_turn(parsed, stock, tools, target=None, h=0.02, tol=0.01):
    """stock：{"d": 毛坯直径, "z_right": 毛坯右端（端面余量）, "z_left": 毛坯左端（卡盘处，负数）}
    tools：{刀号: {"kind": "turn"} 或 {"kind": "groove", "w": 刀宽}}
    target：比对用轮廓 [(z, d), …]（成品或本工序尺寸）。返回最终半径网格、碰撞、过切 / 残留"""
    z0, z1 = float(stock["z_left"]), float(stock["z_right"])
    n = int(round((z1 - z0) / h))
    zc = z0 + (np.arange(n) + 0.5) * h
    r = np.full(n, stock["d"] / 2.0)
    if stock.get("profile"):                     # 上一道工序留下的轮廓作毛坯（例如精车用粗车后的形状），z 超出轮廓右端是空的
        from cae.cam import d_at
        zmax = max(z for z, _ in stock["profile"])
        r = np.array([d_at(stock["profile"], z) / 2 if z <= zmax + 1e-9 else 0.0 for z in zc])
    issues, ap_max = [], 0.0
    for k, mv in enumerate(parsed["moves"]):
        tl = tools.get(mv["tool"], {"kind": "turn"})
        a = np.array([mv["a"][2], mv["a"][0] / 2])
        b = np.array([mv["b"][2], mv["b"][0] / 2])
        pts = _seg_points(a, b, h / 4)
        cut = np.full(n, np.inf)
        if tl.get("kind") == "groove":
            w = tl.get("w", 3.0)
            for zp, rp in pts:
                i0 = max(0, int(math.ceil((zp - w - z0) / h - 0.5)))
                i1 = min(n, int(math.floor((zp - z0) / h - 0.5)) + 1)
                if i1 > i0:
                    np.minimum(cut[i0:i1], rp, out=cut[i0:i1])
        else:
            idx = np.ceil((pts[:, 0] - z0) / h - 0.5).astype(int)
            ok = idx < n
            idx = np.clip(idx[ok], 0, n - 1)
            np.minimum.at(cut, idx, pts[ok, 1])
            cut = np.minimum.accumulate(cut)
        new = np.minimum(r, cut)
        removed = r - new
        if removed.max() > 0.005:
            if mv["t"] == "rapid":
                i = int(removed.argmax())
                issues.append({"line": mv["line"], "level": "error",
                               "text": "快移撞到工件：Z{:.2f} 处切进 {:.2f} mm（快移不能切削）".format(zc[i], removed[i])})
            else:
                # 切深：纵向走刀（沿 Z）看半径方向平均切掉多厚（车到轴肩时顺带切掉的轴肩余量不算成切深）；
                #       横向走刀（端面、切槽，沿 X）看轴向切掉多宽
                axial = abs(mv["b"][2] - mv["a"][2]) >= abs(mv["b"][0] - mv["a"][0]) / 2
                hit = removed > 0.005
                ap = float(removed[hit].mean()) if axial else float(hit.sum() * h)
                ap_max = max(ap_max, ap)
                mv["ap"] = ap
        r = new
    res = {"z": zc, "r": r, "issues": issues, "ap_max": ap_max}
    if target:
        from cae.cam import d_at
        zt = min(z for z, _ in target)
        sel = (zc <= 0.0) & (zc >= zt)
        rt = np.array([d_at(target, z) / 2 for z in zc[sel]])
        dev = r[sel] - rt
        res["dev_min"] = float(dev.min()) if dev.size else 0.0
        res["dev_max"] = float(dev.max()) if dev.size else 0.0
        over = np.nonzero(dev < -tol)[0]
        if len(over):
            zs = zc[sel][over]
            res["issues"].append({"line": None, "level": "error",
                                  "text": "过切：Z{:.2f} ~ Z{:.2f}，最多切多了 {:.3f} mm（半径）".format(zs.max(), zs.min(), -dev.min())})
        under = np.nonzero(dev > tol)[0]
        res["under_mm"] = float(dev[under].max()) if len(under) else 0.0
        res["under_z"] = [float(zc[sel][under].max()), float(zc[sel][under].min())] if len(under) else None
        # 端面（Z0 右边）应全部车掉
        right = zc > 1e-9
        res["face_left"] = max(0.0, float(r[right].max())) if right.any() else 0.0
    return res


# ---------------------------------------------------------------- 铣削仿真
def simulate_mill(parsed, stock, tools, target=None, h=None, tol=0.01):
    """stock：{"box": (xmin, ymin, xmax, ymax), "top": 0, "bottom": -厚度} 或 {"polygon": [...], …}
    tools：{刀号: {"kind": "endmill" | "drill", "d": 直径}}
    target(x, y 网格) → 目标高度数组（None 表示不比对）。返回高度图、碰撞、过切 / 残留"""
    from shapely import contains_xy
    from shapely.geometry import Polygon, box as sbox
    poly = Polygon(stock["polygon"]) if stock.get("polygon") else sbox(*stock["box"])
    xmin, ymin, xmax, ymax = poly.bounds
    pad = max(t.get("d", 10) for t in tools.values()) if tools else 10.0
    xmin, ymin, xmax, ymax = xmin - pad, ymin - pad, xmax + pad, ymax + pad
    h = h or max(0.1, max(xmax - xmin, ymax - ymin) / 500.0)
    nx, ny = int(math.ceil((xmax - xmin) / h)), int(math.ceil((ymax - ymin) / h))
    xs = xmin + (np.arange(nx) + 0.5) * h
    ys = ymin + (np.arange(ny) + 0.5) * h
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    inside = contains_xy(poly, X, Y)
    top = float(stock.get("top", 0.0))
    AIR = -1e6
    H = np.where(inside, top, AIR)
    if stock.get("cyl_r"):                       # 轴类零件铣键槽：毛坯顶面是圆柱面（轴线沿 X，最高点 Z0）
        R0 = float(stock["cyl_r"])
        H = np.where(inside & (np.abs(Y) < R0), np.sqrt(np.clip(R0 ** 2 - Y ** 2, 0, None)) - R0, AIR)
    issues, ap_max = [], 0.0
    for mv in parsed["moves"]:
        tl = tools.get(mv["tool"])
        if not tl:
            continue
        R = tl["d"] / 2
        k = int(math.ceil(R / h)) + 1
        pts = _seg_points(np.array(mv["a"]), np.array(mv["b"]), h / 2)
        worst = 0.0
        for x, y, z in pts:
            ix, iy = int((x - xmin) / h), int((y - ymin) / h)
            a0, a1 = max(ix - k, 0), min(ix + k + 1, nx)
            b0, b1 = max(iy - k, 0), min(iy + k + 1, ny)
            if a1 <= a0 or b1 <= b0:
                continue
            sub = H[a0:a1, b0:b1]
            msk = ((xs[a0:a1, None] - x) ** 2 + (ys[None, b0:b1] - y) ** 2) <= R * R      # 刀具圆盘盖住的格（按格中心）
            hit = msk & (sub > z)
            if hit.any():
                worst = max(worst, float((sub[hit] - z).max()))
                sub[hit] = z
        if worst > 0.005:
            if mv["t"] == "rapid":
                issues.append({"line": mv["line"], "level": "error", "text": "快移撞到工件：切进 {:.2f} mm（快移不能切削）".format(worst)})
            else:
                ap_max = max(ap_max, worst)
                mv["ap"] = worst
    res = {"x": xs, "y": ys, "H": H, "inside": inside, "issues": issues, "ap_max": ap_max, "h": h}
    if target is not None:
        T = target(X, Y)
        m = inside & ~np.isnan(T)
        dev = np.where(m & np.isfinite(T), H - T, 0.0)
        res["dev_min"] = float(dev.min())
        res["dev_max"] = float(dev.max())
        res["over"] = int((dev < -tol).sum())
        res["under_mask"] = dev > tol
        if res["over"]:
            res["issues"].append({"line": None, "level": "error", "text": "过切：{} 格比目标低，最多 {:.3f} mm".format(res["over"], -dev.min())})
    return res


def run(text, machine, stock, tools, target=None):
    """读程序 → 机床检查 → 时间 → 仿真，一次做完"""
    p = parse(text, machine)
    checks = machine_checks(p, machine)
    tm = timing(p, machine)
    sim = simulate_turn(p, stock, tools, target) if p["lathe"] else simulate_mill(p, stock, tools, target)
    return {"parsed": p, "checks": checks + sim["issues"], "time": tm, "sim": sim}
