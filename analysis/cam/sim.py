"""G 代码读取、加工时间、仿真与检查（ADR-0059，M11 第二步）。搬自问渠数字工厂第 13 轮 cae/cam_sim.py，机床参数改为传入，
铣削毛坯为矩形或多边形（不依赖 shapely）。

读 FANUC 风格程序（本模块生成的、FreeCAD CAM 工作台等输出的）：G00/G01/G02/G03、G32（车螺纹，西门子 G33 同样处理）、G90/G91、G17/G18、G20/G21、G28、G50（限速）、
G96/G97、G94/G95、G98/G99（车：每分 / 每转进给；铣：钻孔循环返回平面）、G80/G81/G83、G84（刚性攻丝，M29）、T、M03/M04/M05/M06/M08/M09/M30、S、F。

仿真：
  车削——沿轴线的半径网格（每 0.02 mm 一格）。外圆车刀按“刀尖在左下角，刀体朝右上”处理；切槽刀刀宽 w，刀尖在右刀尖。外圆刀、镗刀的刀尖圆弧按 rε 扫过（ADR-0106 Q2）。
  铣削——高度图（XY 网格，每格记录剩下材料的顶面高度）。平底立铣刀按圆柱扫过；钻头按平底处理。
检查：快移碰到材料、与目标比对过切 / 残留、超程、转速超限、G96 没有 G50 限速、没开主轴就切削、G01 没有 F。
"""

from __future__ import annotations

import itertools
import math
import re

import numpy as np

from analysis.cam import paths as _P
from analysis.cam.paths import d_at

WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")


# ---------------------------------------------------------------- 读程序
def _strip(line):
    line = re.sub(r"\([^)]*\)", " ", line)
    return line.split(";")[0].strip().upper()


def parse(text, m):
    """→ {"moves": [...], "tools": [...], "warnings": [...], "rpm_max": ..}
    move：{"t": "rapid"|"feed", "a": (x, y, z), "b": (x, y, z), "line": 行号, "tool": 刀号, "f": 进给, "per_rev": bool,
           "css": 恒线速 m/min 或 None, "rpm": 转速, "smax": G50 限速, "home": 回参考点, "cycle": 钻孔循环}
    车床的 x 是直径，y 恒为 0。"""
    lathe = m["kind"] in ("lathe", "mill_turn")          # 车铣中心：车削按车床读，铣削（G12.1 / G7.1）另记工件坐标（ADR-0106 C2b）
    st = {"pos": [0.0, 0.0, 0.0], "abs": True, "motion": 0, "f": 0.0, "per_rev": lathe, "css": None, "rpm": 0.0,
          "smax": None, "tool": 0, "scale": 1.0, "ret98": True, "plane": 18 if lathe else 17, "spin": False, "pending_tool": 0,
          "frame": None, "mt": None}
    hx, hz = m.get("home", (m["x"][1], m["z"][1]))
    if lathe:
        st["pos"] = [hx, 0.0, hz]
    else:
        st["pos"] = [0.0, 0.0, m["z"][1]]
    moves, warns, tools, tool_changes = [], [], [], []
    rpm_req = 0.0
    cyc = None
    lines = text.splitlines()
    nmap = {}                                       # 程序段号 N → 行号（G71 / G70 的 P、Q 找轮廓用）
    for ln, raw in enumerate(lines, 1):
        mm = re.match(r"N(\d+)", _strip(raw))
        if mm:
            nmap[int(mm.group(1))] = ln
    skip = set()
    g71p = g76p = None

    def blocks(ns, nf, z_start):
        """N ns ~ N nf 的轮廓段 → [(x, z), …] 与段里的 F（绝对坐标；第一段没写 Z 就是起点的 Z）"""
        if ns not in nmap or nf not in nmap:
            raise ValueError(f"固定循环的 P{ns} / Q{nf} 程序段找不到")
        pts, x, z, f = [], None, z_start, None
        for k in range(nmap[ns], nmap[nf] + 1):
            ww = {kk: float(v) for kk, v in WORD.findall(_strip(lines[k - 1])) if kk in "XZF"}
            x = ww.get("X", x)
            z = ww.get("Z", z)
            f = ww.get("F", f)
            if "X" in ww or "Z" in ww:
                pts.append((x, z))
            skip.add(k)
        return pts, f

    def emit(t, b, line, **kw):
        if st["mt"] is not None and not kw.get("home"):   # 车铣：程序坐标（极坐标插补 X C Z / 圆柱插补 X C° Z）→ 工件坐标小段
            from analysis.cam import millturn as _MT

            a0, b0 = tuple(st["pos"]), tuple(float(v) for v in b)
            if max(abs(b0[i] - a0[i]) for i in range(3)) <= 1e-9:
                return
            if st["mt"] == "polar":
                pa, pb = _MT.polar_to_work(*a0), _MT.polar_to_work(*b0)
                pieces = [(pa, pb, (0.0, 0.0, 1.0))]
                da, db = 2 * math.hypot(pa[0], pa[1]), 2 * math.hypot(pb[0], pb[1])
            elif st["mt"][0] == "index":
                th = st["mt"][1]
                pa, pb = _MT.index_to_work(a0, th), _MT.index_to_work(b0, th)
                pieces = [(pa, pb, _MT.index_axis(th))]
                da, db = 2 * math.hypot(pa[0], pa[1]), 2 * math.hypot(pb[0], pb[1])
            else:
                pts = [_MT.cyl_to_work(*a0)] + _MT.cyl_segment(a0, b0)
                pieces = []
                for p0, p1 in itertools.pairwise(pts):
                    r = math.hypot(p1[0], p1[1]) or 1.0
                    pieces.append((p0, p1, (p1[0] / r, p1[1] / r, 0.0)))
                da, db = a0[0], b0[0]
            moves.append(dict(t=t, a=(da, 0.0, a0[2]), b=(db, 0.0, b0[2]), line=line, tool=st["tool"], f=st["f"], per_rev=st["per_rev"],
                              css=None, rpm=st["rpm"], smax=st["smax"], spin=st["spin"], mill=_mill_kind(st["mt"]),
                              pieces=pieces, **kw))
            st["pos"] = list(b0)
            return
        if not kw.get("home"):
            st["homed"] = False
        if st.get("approach"):
            kw = {**kw, "approach": True}
            if abs(float(b[2]) - st["pos"][2]) > 1e-9:
                st["approach"] = False
        a = tuple(st["pos"])
        b = tuple(float(v) for v in b)
        if max(abs(b[i] - a[i]) for i in range(3)) > 1e-9:
            if st["frame"] is not None:              # 倾斜面（G68.2）：程序坐标是平面坐标，刀路记工件坐标和刀轴方向
                o, R = st["frame"]
                kw = {**kw, "axis": tuple(float(v) for v in R[:, 2])}
                aw, bw = tuple(float(v) for v in o + R @ np.array(a)), tuple(float(v) for v in o + R @ np.array(b))
            else:
                aw, bw = a, b
            moves.append(dict(t=t, a=aw, b=bw, line=line, tool=st["tool"], f=st["f"], per_rev=st["per_rev"], css=st["css"],
                              rpm=st["rpm"], smax=st["smax"], spin=st["spin"], **kw))
        st["pos"] = list(b)

    for ln, raw in enumerate(lines, 1):
        if ln in skip:
            continue
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
        tilt_line = False
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
                if m["kind"] == "mill_turn" and (st["mt"] is None or st["mt"][0] == "index"):
                    # 车铣中心：G19 = C 轴分度后 Y 轴铣（ADR-0106 C2b），程序 X 直径、Y、Z，C 锁在分度角；G18 回车削
                    st["mt"] = ("index", st.get("c", 0.0)) if gg == 19 else None
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
            elif gg in (0, 1, 2, 3, 32, 33):
                st["motion"] = 32 if gg in (32, 33) else int(gg)
                cyc = None
            elif gg in (81, 83, 84):
                st["motion"] = int(gg)
            elif gg == 80:
                cyc = None
                st["motion"] = 0
            elif gg == 68.2 and not lathe:            # 倾斜面：X Y Z 是平面原点（当前坐标），I J K 是 Z-X-Z 欧拉角（ADR-0106 C2a）
                from analysis.cam import tilt as _TT

                o0, R0 = st["frame"] if st["frame"] is not None else (np.zeros(3), np.eye(3))
                pw = o0 + R0 @ np.array(st["pos"])
                org = o0 + R0 @ np.array([w.get("X", 0.0), w.get("Y", 0.0), w.get("Z", 0.0)])
                R = R0 @ _TT.from_zxz(w.get("I", 0.0), w.get("J", 0.0), w.get("K", 0.0))
                st["frame"] = (org, R)
                st["pos"] = [float(v) for v in R.T @ (pw - org)]
                tilt_line = True
            elif gg == 69 and not lathe:
                if st["frame"] is not None:
                    o0, R0 = st["frame"]
                    st["pos"] = [float(v) for v in o0 + R0 @ np.array(st["pos"])]
                st["frame"] = None
            elif gg == 12.1 and lathe:               # 极坐标插补开：程序 X 直径、C 毫米（虚拟轴）
                st["mt"] = "polar"
                st["pos"] = [st["pos"][0], 0.0, st["pos"][2]]
            elif gg == 13.1 and lathe:
                if st["mt"] == "polar":
                    st["pos"] = [2 * math.hypot(st["pos"][0] / 2, st["pos"][1]), 0.0, st["pos"][2]]
                st["mt"] = None
            elif gg == 7.1 and lathe:                # 圆柱插补：G7.1 C 半径 开，G7.1 C0 关；程序 C 是角度（度）
                if w.get("C", 0.0) > 0:
                    st["mt"] = ("cyl", w["C"])
                    st["pos"] = [st["pos"][0], 0.0, st["pos"][2]]
                else:
                    st["mt"] = None
                    st["pos"] = [st["pos"][0], 0.0, st["pos"][2]]
                tilt_line = True
            elif gg == 53.1:                         # 刀轴转到平面法向：刀具在机床 Z 原点（G28 退过）时，转完仍在刀轴方向的最高处
                if st["frame"] is not None and st.get("homed"):
                    st["pos"][2] = max(st["pos"][2], float(m["z"][1]))
                    st["approach"] = True                # 到第一次 Z 下刀为止：机床 Z 在原点，实际位置由数控系统的倾斜面功能定
                tilt_line = True
        if tilt_line:                                # G68.2 / G53.1 这一行的 X Y Z I J K 不是移动
            continue
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
        if lathe and any(x in g for x in (70, 71, 76)):     # 车削固定循环：按 paths 里的展开规则展开（与出刀路同一套）
            P_ = int(w.get("P", 0))
            x0, z0 = st["pos"][0], st["pos"][2]
            try:
                if 71 in g and "P" not in w:
                    g71p = {"d": w.get("U", 1.0), "e": w.get("R", 0.5)}
                    continue
                if 71 in g:
                    pts, f_fin = blocks(P_, int(w["Q"]), z0)
                    exp = _P.g71_expand(pts, x0, z0, (g71p or {}).get("d", 1.0), (g71p or {}).get("e", 0.5),
                                        w.get("U", 0.0), w.get("W", 0.0), w.get("F", st["f"]))
                elif 70 in g:
                    pts, f_fin = blocks(P_, int(w["Q"]), z0)
                    exp = _P.g70_expand(pts, x0, z0, f_fin or st["f"])
                elif "X" not in w and "Z" not in w:
                    pp = f"{P_:06d}"
                    g76p = {"m": int(pp[:2]), "a": int(pp[4:])}
                    continue
                else:
                    xr, ze, lead = w["X"], w["Z"], w["F"]
                    k, dd, ii = w.get("P", 0) / 1000.0, w.get("Q", 0) / 1000.0, w.get("R", 0.0)
                    if (g76p or {}).get("a", 0):
                        warns.append({"line": ln, "level": "unknown", "text": "G76 斜进（刀尖角 a ≠ 0）：仿真按径向进刀展开"})
                    exp = []
                    for a in _P.g76_depths(k, dd, (g76p or {}).get("m", 1)):
                        xe = xr + 2 * (k - a) if xr < x0 else xr - 2 * (k - a)
                        exp += [{"t": "rapid", "x": xe + 2 * ii, "z": z0}, {"t": "thread", "x": xe, "z": ze, "pitch": lead},
                                {"t": "rapid", "x": x0, "z": ze}, {"t": "rapid", "x": x0, "z": z0}]
            except (ValueError, KeyError) as exc:
                warns.append({"line": ln, "level": "error", "text": f"固定循环读不懂：{exc}"})
                continue
            for e in exp:
                if e["t"] == "thread":
                    st["f"] = e["pitch"]
                    n0 = len(moves)
                    emit("thread", (e["x"], 0.0, e["z"]), ln, pitch=e["pitch"])
                    if len(moves) > n0:
                        moves[-1]["per_rev"] = True
                else:
                    if "f" in e:
                        st["f"] = e["f"]
                    emit(e["t"], (e["x"], 0.0, e["z"]), ln)
            st["motion"] = 0
            continue
        if 28 in g:
            if lathe:
                st["pos"] = [hx, 0.0, hz]
            elif st["frame"] is not None:            # 倾斜面里回参考点：机床 Z 退到顶（按工件坐标算终点）
                o0, R0 = st["frame"]
                pw = o0 + R0 @ np.array(st["pos"])
                st["frame"], st["pos"] = None, list(pw)
                emit("rapid", (pw[0], pw[1], m["z"][1]), ln, home=True)
                st["frame"] = (o0, R0)
                st["pos"] = list(R0.T @ (np.array(st["pos"]) - o0))
            else:
                emit("rapid", (st["pos"][0], st["pos"][1], m["z"][1]), ln, home=True)
            st["homed"] = True
            continue
        if m["kind"] == "mill_turn" and "C" in w and (st["mt"] is None or st["mt"][0] == "index"):
            st["c"] = w.pop("C")                    # C 轴分度（不在插补里）：记下角度，分度铣按它换工件坐标
            if st["mt"] is not None:
                st["mt"] = ("index", st["c"])
        if st["mt"] is not None and "C" in w and not any(k in w for k in "XYZUW"):
            w["Y"] = w["C"]                         # 车铣插补里只写 C 的段：C 是第二个坐标
        if st["mt"] is not None and "C" in w:
            w["Y"] = w["C"]
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
            if mo == 84:                                     # 刚性攻丝：进到底、主轴反转按同样螺距退回 R 平面（ADR-0106 Q3b）
                old = cyc or {}
                cyc = {"z": w["Z"] * sc if "Z" in w else old.get("z", 0.0), "r": w["R"] * sc if "R" in w else old.get("r", 2.0),
                       "init": old.get("init", st["pos"][2])}
                x, y = tgt[0], tgt[1]
                z0 = cyc["init"]
                pitch = st["f"] / st["rpm"] if st["rpm"] > 0 else 0.0
                emit("rapid", (x, y, z0), ln, cycle=True)
                emit("rapid", (x, y, cyc["r"]), ln, cycle=True)
                emit("feed", (x, y, cyc["z"]), ln, cycle=True, tap=pitch)
                emit("feed", (x, y, cyc["r"]), ln, cycle=True, tap=pitch)
                emit("rapid", (x, y, z0 if st["ret98"] else cyc["r"]), ln, cycle=True)
            elif mo in (81, 83):
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
            elif mo in (2, 3) and st["mt"] is not None:
                warns.append({"line": ln, "level": "error", "text": "车铣插补（G12.1 / G7.1）里的圆弧还读不了（ADR-0106 C2b）"})
                st["pos"] = list(tgt)
            elif mo in (2, 3):
                for p in _arc(st, tgt, w, mo, lathe, sc):
                    emit("feed", p, ln, arc=True)
            elif mo == 32:                                   # 车螺纹：F 是螺距（每转走一个螺距），与 G98 / G99 无关
                n0 = len(moves)
                emit("thread", tgt, ln, pitch=st["f"])
                if len(moves) > n0:
                    moves[-1]["per_rev"] = True
            else:
                emit("rapid" if mo == 0 else "feed", tgt, ln)
                if mo == 1 and st["f"] <= 0:
                    warns.append({"line": ln, "level": "error", "text": "G01 没有进给速度 F"})
        if 30 in mc or 2 in mc:
            break
    return {"moves": moves, "tools": sorted(set(tools)), "tool_changes": tool_changes, "warnings": warns, "rpm_req": rpm_req,
            "lathe": lathe}


def _mill_kind(mt) -> str:
    """车铣铣削段的种类：polar（极坐标插补）、cyl（圆柱插补）、index（C 轴分度 + Y 轴铣）"""
    return "polar" if mt == "polar" else "index" if mt[0] == "index" else "cyl"


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
def _rpm(mv, x_diam, m):
    cap = min(mv["smax"] or m["max_rpm"], m["max_rpm"])
    if mv["css"]:
        return min(1000.0 * mv["css"] / (math.pi * max(abs(x_diam), 1e-3)), cap)
    return min(mv["rpm"], m["max_rpm"])


def move_time(mv, m, lathe):
    """一段的时间（秒）。快移各轴同时走，取最慢的轴；切削按进给速度，每转进给按当时转速（G96 时随直径变）分段积分。
    车铣的铣削段（极坐标、圆柱插补）按工件坐标里的路程算：快移取最慢的直线轴，切削按每分进给（每转进给时乘主轴转速）"""
    if mv.get("pieces"):
        L = sum(math.dist(p0, p1) for p0, p1, _w in mv["pieces"])
        if mv["t"] == "rapid":
            return 60.0 * L / min(m["rapid"].values())
        f = mv["f"] * (mv["rpm"] if mv["per_rev"] else 1.0)
        return 60.0 * L / max(f, 1e-9)
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
        rpm = _rpm(mv, x, m)
        t += 60.0 * (L / n) / max(mv["f"] * rpm, 1e-9)
    return t


def timing(parsed, m):
    lathe = parsed["lathe"]
    cut = rap = 0.0
    Lc = Lr = 0.0
    for mv in parsed["moves"]:
        t = move_time(mv, m, lathe)
        a, b = mv["a"], mv["b"]
        L = math.dist((a[0] / 2, a[2]), (b[0] / 2, b[2])) if lathe else math.dist(a, b)
        if mv["t"] == "rapid":
            rap += t
            Lr += L
        else:
            cut += t
            Lc += L
        mv["dt"] = t
    tc = len(parsed["tool_changes"]) * m["tool_change_s"]
    return {"cut_s": cut, "rapid_s": rap, "tool_s": tc, "total_s": cut + rap + tc, "cut_len_mm": Lc, "rapid_len_mm": Lr,
            "tool_changes": len(parsed["tool_changes"])}


# ---------------------------------------------------------------- 检查（机床）
def machine_checks(parsed, m):
    out = list(parsed["warnings"])
    lathe = parsed["lathe"]
    axes = (("X", 0, m["x"]), ("Z", 2, m["z"])) if lathe else (("X", 0, m["x"]), ("Y", 1, m["y"]), ("Z", 2, m["z"]))
    seen = set()
    tilted = False
    for mv in parsed["moves"]:
        if mv.get("home"):
            continue
        if mv.get("axis") is not None and abs(mv["axis"][2] - 1.0) > 1e-9:
            if not m.get("rotary") and ("tilt", 0) not in seen:      # 三轴机床转不了刀轴
                seen.add(("tilt", 0))
                out.append({"line": mv["line"], "level": "error", "text": f"{m['name']} 没有回转轴，做不了倾斜面加工（G68.2）"})
            tilted = True
            continue                                     # 倾斜面上的移动：直线轴超程由整机仿真按回转后的机床坐标查
        for name, i, (lo, hi) in axes:
            v = mv["b"][i]
            if (v < lo - 1e-6 or v > hi + 1e-6) and (name, mv["line"]) not in seen:
                seen.add((name, mv["line"]))
                out.append({"line": mv["line"], "level": "error",
                            "text": "{} 超程：{}{:.3f}，{} 行程 {:g} ~ {:g}".format(name, name, v, m["name"], lo, hi)})
        if mv["t"] == "feed" and not mv["spin"] and ("spin", 0) not in seen:
            seen.add(("spin", 0))
            out.append({"line": mv["line"], "level": "error", "text": "主轴没有转（缺 M03）就开始切削"})
    parsed["tilted"] = tilted
    if parsed["rpm_req"] > m["max_rpm"]:
        out.append({"line": None, "level": "error", "text": "转速 S{:g} 超过机床最高转速 {}".format(parsed["rpm_req"], m["max_rpm"])})
    th = next((mv for mv in parsed["moves"] if mv["t"] == "thread" and mv["css"]), None)
    if th:
        out.append({"line": th["line"], "level": "error", "text": "车螺纹时还是 G96 恒线速：转速会变、乱牙，车螺纹前要 G97 恒转速"})
    if lathe and any(mv["css"] and not mv["smax"] for mv in parsed["moves"]):
        out.append({"line": None, "level": "warn", "text": "用了 G96 恒线速却没有 G50 限速：车到小直径时转速会冲到机床最高转速"})
    for mv in parsed["moves"]:
        if mv["css"] and mv["smax"] and mv["smax"] > m["max_rpm"]:
            out.append({"line": mv["line"], "level": "error", "text": "G50 限速 S{:g} 超过机床最高转速 {}".format(mv["smax"], m["max_rpm"])})
            break
    return out


# ---------------------------------------------------------------- 车削仿真
def _seg_points(a, b, step):
    n = max(1, math.ceil(math.dist(a, b) / step))
    t = np.linspace(0.0, 1.0, n + 1)
    return np.outer(1 - t, a) + np.outer(t, b)


def simulate_turn(parsed, stock, tools, target=None, h=0.02, tol=0.01, history=None):
    """stock：{"d": 毛坯直径, "z_right": 毛坯右端（端面余量）, "z_left": 毛坯左端（卡盘处，负数）}，可另给 "bore_d"（毛坯已有的内孔）
    tools：{刀号: {"kind": "turn"} | {"kind": "groove", "w": 刀宽} | {"kind": "thread"} | {"kind": "thread_in"} | {"kind": "drill", "d": 直径}
           | {"kind": "bore"} | {"kind": "face_groove", "w": 刀宽（半径方向）}}
           外圆刀、镗刀可带 "nose_r"（刀尖圆弧半径）：程序点是假想刀尖（外圆刀方位 3、镗刀方位 2），按半径 nose_r 的圆扫过去切（ADR-0106 Q2）
    target：比对用轮廓 [(z, d), …]（成品或本工序尺寸），或 {"outer": 轮廓, "grooves": [(z 右边, 宽, 槽底直径)], "threads": [(z 起, z 止, 牙底直径)],
            "inner": 内轮廓 [(z, d), …]}。返回最终半径网格（外 r、内 ri）、碰撞、过切 / 残留。
    材料在 ri < 半径 < r 之间。螺纹按整圈切（不计螺旋线），比对时螺纹段看牙底直径；钻头按平底。"""
    z0, z1 = float(stock["z_left"]), float(stock["z_right"])
    n = round((z1 - z0) / h)
    zc = z0 + (np.arange(n) + 0.5) * h
    r = np.full(n, stock["d"] / 2.0)
    ri = np.full(n, float(stock.get("bore_d", 0.0)) / 2.0)
    if stock.get("profile"):                     # 上一道工序留下的轮廓作毛坯（例如精车用粗车后的形状），z 超出轮廓右端是空的
        zmax = max(z for z, _ in stock["profile"])
        r = np.array([d_at(stock["profile"], z) / 2 if z <= zmax + 1e-9 else 0.0 for z in zc])
    issues, ap_max = [], 0.0
    void = np.full((n, 2), np.nan)                # 端面槽切出的环形空腔 [内半径, 外半径]（每个 Z 一个）
    if history is not None:                       # 回放用：开始时和每段走完的 (z, r, ri)
        history.append((zc, r.copy(), ri.copy()))

    def idx_of(zs):
        k = np.ceil((np.asarray(zs) - z0) / h - 0.5).astype(int)
        return k

    for mv in parsed["moves"]:
        if mv.get("mill"):                         # 车铣的铣削段（动力刀）不是车削：车削仿真不算它（ADR-0106 C2b）
            if history is not None:                 # 回放的帧与历史一一对应：铣削段记一份没变的
                history.append((zc, r.copy(), ri.copy()))
            continue
        tl = tools.get(mv["tool"], {"kind": "turn"})
        kind = tl.get("kind", "turn")
        a = np.array([mv["a"][2], mv["a"][0] / 2])
        b = np.array([mv["b"][2], mv["b"][0] / 2])
        rn = float(tl.get("nose_r") or 0.0) if kind in ("turn", "bore") else 0.0
        pts = _seg_points(a, b, h / 4 if rn <= 0 else h)
        solid = r > ri + 1e-12
        new_r, new_ri = r.copy(), ri.copy()
        if kind == "face_groove":                     # 端面槽：刀位点在外侧刀尖，刀宽沿半径往里，刀从这点往 +Z 一侧都占着
            w = float(tl.get("w", 3.0))
            for zp, rp in pts:
                k0 = max(0, math.ceil((zp - z0) / h - 0.5))
                if k0 >= n:
                    continue
                lo, hi = rp - w, rp
                cur = void[k0:]
                fresh = np.isnan(cur[:, 0])
                touch = ~fresh & (lo <= cur[:, 1] + h) & (hi >= cur[:, 0] - h)
                apart = ~fresh & ~touch & (r[k0:] > ri[k0:] + 1e-12)
                if apart.any() and not any("每个 Z 只算一个端面槽" in i["text"] for i in issues):
                    issues.append({"line": mv["line"], "level": "unknown",
                                   "text": "两个端面槽在同一段 Z 上：仿真每个 Z 只算一个端面槽，这一段的比对没做"})
                cur[fresh] = [lo, hi]
                cur[touch, 0] = np.minimum(cur[touch, 0], lo)
                cur[touch, 1] = np.maximum(cur[touch, 1], hi)
            if history is not None:
                history.append((zc, r.copy(), ri.copy()))
            continue
        if kind in ("bore", "drill", "thread_in"):
            grow = np.full(n, -np.inf)
            if kind == "drill":
                on_axis = np.abs(pts[:, 1]) < 1e-6
                if on_axis.any():
                    zmin = pts[on_axis, 0].min()
                    zmax_p = pts[on_axis, 0].max()
                    sel = (zc >= zmin) & (zc <= max(zmax_p, z1))
                    grow[sel] = tl["d"] / 2
            elif rn > 0:                                  # 镗刀刀尖圆弧：圆心 = 假想刀尖 + (rε, −rε)，切到圆的上半边
                k, rr = _nose_envelope(pts[:, 0] + rn, pts[:, 1] - rn, rn, z0, h, n, upper=True)
                np.maximum.at(grow, k, rr)
            else:
                k = idx_of(pts[:, 0])
                ok = (k >= 0) & (k < n)
                np.maximum.at(grow, k[ok], pts[ok, 1])
            new_ri = np.where(solid, np.maximum(ri, np.minimum(grow, r)), ri)
            removed = np.where(solid, new_ri - ri, 0.0)
        else:
            cut = np.full(n, np.inf)
            if kind == "groove":
                w = tl.get("w", 3.0)
                for zp, rp in pts:
                    i0 = max(0, math.ceil((zp - w - z0) / h - 0.5))
                    i1 = min(n, math.floor((zp - z0) / h - 0.5) + 1)
                    if i1 > i0:
                        np.minimum(cut[i0:i1], rp, out=cut[i0:i1])
            elif rn > 0:                                  # 外圆刀刀尖圆弧：圆心 = 假想刀尖 + (rε, rε)，切到圆的下半边
                k, rr = _nose_envelope(pts[:, 0] + rn, pts[:, 1] + rn, rn, z0, h, n, upper=False)
                np.minimum.at(cut, k, rr)
                cut = np.minimum.accumulate(cut)
            else:
                k = idx_of(pts[:, 0])
                ok = (k >= 0) & (k < n)
                np.minimum.at(cut, k[ok], pts[ok, 1])
                if kind == "turn":
                    cut = np.minimum.accumulate(cut)
            new_r = np.where(solid, np.maximum(np.minimum(r, cut), ri), r)
            removed = np.where(solid, r - new_r, 0.0)
        if removed.max() > 0.005:
            if mv["t"] == "rapid":
                i = int(removed.argmax())
                issues.append({"line": mv["line"], "level": "error",
                               "text": f"快移撞到工件：Z{zc[i]:.2f} 处切进 {removed[i]:.2f} mm（快移不能切削）"})
            else:
                # 切深：纵向走刀（沿 Z）看半径方向平均切掉多厚（车到轴肩时顺带切掉的轴肩余量不算成切深）；
                #       横向走刀（端面、切槽，沿 X）看轴向切掉多宽
                axial = abs(mv["b"][2] - mv["a"][2]) >= abs(mv["b"][0] - mv["a"][0]) / 2
                hit = removed > 0.005
                ap = float(removed[hit].mean()) if axial else float(hit.sum() * h)
                ap_max = max(ap_max, ap)
                mv["ap"] = ap
        r, ri = new_r, new_ri
        if history is not None:
            history.append((zc, r.copy(), ri.copy()))
    res = {"z": zc, "r": r, "ri": ri, "issues": issues, "ap_max": ap_max, "void": void}
    if target:
        tg = target if isinstance(target, dict) else {"outer": target}
        outer = tg.get("outer")
        if outer:
            zt = min(z for z, _ in outer)
            sel = (zc <= 0.0) & (zc >= zt)
            rt = np.array([d_at(outer, z) / 2 for z in zc])
            ra = rt                                   # 残留按“做得到的轮廓”比，过切按设计轮廓比
            rn = float(tg.get("nose_outer") or 0.0)
            if rn > 0:                                # 刀尖圆弧做得到的轮廓：凹拐角补成 R rε 圆角
                d_end = max(d for z, d in outer if abs(z - zt) < 1e-9)      # 轮廓左端以外是最后那个轴肩的大直径
                ext = np.where(zc < zt, d_end / 2, np.where(zc > 1e-9, 0.0, rt))   # 端面右边是空的
                ra = np.where(zc > 1e-9, rt, achievable(zc, ext, rn, h))
                if ((ra - rt)[sel] > tol).any():
                    res["fillet_outer"] = rn
            skip = np.zeros(n, bool)
            for zr, w, db in tg.get("grooves") or []:
                g = (zc <= zr + 1e-9) & (zc >= zr - w - 1e-9)
                rt = np.where(g, db / 2, rt)
                ra = np.where(g, db / 2, ra)
            for t in tg.get("threads") or []:
                t = _thread_entry(t)
                th = (zc <= t["za"]) & (zc >= t["zb"])
                if t["internal"]:
                    continue                          # 内螺纹在内孔那边比
                skip |= th
                root = t["root_a"] + (t["root_b"] - t["root_a"]) * (t["za"] - zc) / max(t["za"] - t["zb"], 1e-12)
                left = th & (r > root / 2 + tol)
                if left.any():
                    k = int(np.argmax(np.where(left, r - root / 2, -np.inf)))
                    res["issues"].append({"line": None, "level": "error",
                                          "text": f"螺纹没车到牙底：Z{zc[k]:.2f} 处直径 {2 * r[k]:.3f}，牙底应为 {root[k]:.3f}"})
            sel &= ~skip
            dev = r[sel] - rt[sel]
            dev_a = np.where(dev < 0, dev, np.maximum(r[sel] - ra[sel], 0.0))
            res["dev_min"] = float(dev.min()) if dev.size else 0.0
            res["dev_max"] = float(dev_a.max()) if dev.size else 0.0
            over = np.nonzero(dev < -tol)[0]
            if len(over):
                zs = zc[sel][over]
                res["issues"].append({"line": None, "level": "error",
                                      "text": f"过切：Z{zs.max():.2f} ~ Z{zs.min():.2f}，最多切多了 {-dev.min():.3f} mm（半径）"})
            dev = dev_a
            under = np.nonzero(dev > tol)[0]
            res["under_mm"] = float(dev[under].max()) if len(under) else 0.0
            res["under_z"] = [float(zc[sel][under].max()), float(zc[sel][under].min())] if len(under) else None
            # 端面（Z0 右边）应全部车掉
            right = zc > 1e-9
            res["face_left"] = max(0.0, float((r[right] - ri[right]).max())) if right.any() else 0.0
        for zp in tg.get("parted") or []:          # 切断：零件左端面以左到中心都要切开
            cut_zone = (zc < zp - h) & (zc > zp - h * 3)
            if cut_zone.any() and (r[cut_zone] - ri[cut_zone] > tol).any():
                res["issues"].append({"line": None, "level": "error", "text": f"没切断：Z{zp:g} 处还连着（切断刀没走到中心）"})
        for zp, ch, dp in tg.get("part_chamfer") or []:   # 切断前倒角：零件左端 Z zp ~ zp + ch，外径从 dp − 2ch 斜到 dp
            zone = (zc > zp + h) & (zc < zp + ch - h)
            if zone.any():
                want = (dp / 2 - ch) + (zc[zone] - zp)
                dv = r[zone] - want
                if (dv < -tol).any():
                    res["issues"].append({"line": None, "level": "error", "text": f"切断前倒角切多了：C{ch:g} 处最多 {-dv.min():.3f} mm"})
                elif (dv > tol).any():
                    res["issues"].append({"line": None, "level": "error", "text": f"切断前倒角没倒到位：C{ch:g} 处最多留了 {dv.max():.3f} mm"})
        for fg in tg.get("face_grooves") or []:     # 端面槽：Z −深 ~ 0 之间，空腔要盖住 [内径, 外径]，不能更宽更深
            a_in, a_out, dp = fg["d_in"] / 2, fg["d_out"] / 2, fg["depth"]
            zone = (zc <= 0.0) & (zc >= -dp + h / 2)
            v = void[zone]
            miss = np.isnan(v[:, 0]) | (v[:, 0] > a_in + tol) | (v[:, 1] < a_out - tol)
            if miss.any():
                res["issues"].append({"line": None, "level": "error",
                                      "text": f"端面槽没切到位：Ø{fg['d_in']:g} ~ Ø{fg['d_out']:g}、深 {dp:g} 里有没切的地方"})
            wide = ~np.isnan(v[:, 0]) & ((v[:, 0] < a_in - tol) | (v[:, 1] > a_out + tol))
            deep = (zc < -dp - tol) & ~np.isnan(void[:, 0]) & (zc > -dp - 5)
            if wide.any() or deep.any():
                res["issues"].append({"line": None, "level": "error",
                                      "text": f"端面槽切多了：Ø{fg['d_in']:g} ~ Ø{fg['d_out']:g}、深 {dp:g} 以外也切了"})
        inner = tg.get("inner")
        if inner:
            zt = min(z for z, _ in inner)
            sel = (zc <= 0.0) & (zc >= zt)
            rt = np.array([d_at(inner, z) / 2 for z in zc[sel]])
            rn = float(tg.get("nose_inner") or 0.0)
            ra = rt
            if rn > 0:
                ra = -achievable(zc[sel], -rt, rn, h)        # 内孔：把半径取负，同一套算法
                if (rt - ra > tol).any():
                    res["fillet_inner"] = rn
            dev = np.where(rt - ri[sel] < 0, rt - ri[sel], np.maximum(ra - ri[sel], 0.0))   # 镗大了按设计比，残留按做得到的比
            zs_in = zc[sel]
            for t in tg.get("threads") or []:
                t = _thread_entry(t)
                if not t["internal"]:
                    continue
                th = (zs_in <= t["za"]) & (zs_in >= t["zb"])
                dev = np.where(th, 0.0, dev)              # 内螺纹段：小径按底孔比不适用，看是否车到大径
                root = t["root_a"] + (t["root_b"] - t["root_a"]) * (t["za"] - zs_in) / max(t["za"] - t["zb"], 1e-12)
                short = th & (ri[sel] < root / 2 - tol)
                if short.any():
                    k = int(np.argmax(np.where(short, root / 2 - ri[sel], -np.inf)))
                    res["issues"].append({"line": None, "level": "error",
                                          "text": f"内螺纹没车到大径：Z{zs_in[k]:.2f} 处直径 {2 * ri[sel][k]:.3f}，大径应为 {root[k]:.3f}"})
            res["inner_dev_min"] = float(dev.min()) if dev.size else 0.0
            res["inner_dev_max"] = float(dev.max()) if dev.size else 0.0
            if dev.size and dev.min() < -tol:
                res["issues"].append({"line": None, "level": "error", "text": f"内孔镗大了：最多 {-dev.min():.3f} mm（半径）"})
            if dev.size and dev.max() > tol:
                zz = zc[sel][dev > tol]
                res["issues"].append({"line": None, "level": "error",
                                      "text": f"内孔残留：Z{zz.max():.2f} ~ Z{zz.min():.2f}，最多 {dev.max():.3f} mm（半径）"})
    return res


def _thread_entry(t):
    """比对用的螺纹：旧格式 (z 起, z 止, 牙底直径) 或 {"za", "zb", "root_a", "root_b", "internal"}"""
    if isinstance(t, dict):
        return {"za": float(t["za"]), "zb": float(t["zb"]), "root_a": float(t["root_a"]),
                "root_b": float(t.get("root_b", t["root_a"])), "internal": bool(t.get("internal"))}
    za, zb, droot = t
    return {"za": float(za), "zb": float(zb), "root_a": float(droot), "root_b": float(droot), "internal": False}


def achievable(zc, rt, rn, h):
    """外圆目标轮廓 rt(z)（网格 zc）→ 半径 rn 的刀尖圆弧从外面车得到的轮廓：圆心能到的最低位置
    c(z) = max(rt(z′) + √(rn² − (z′ − z)²))，车出来的表面 = min(c(z′) − √(rn² − (z′ − z)²))（形态学开运算）。
    凸的地方不变，凹拐角（轴肩根部）补成 R rn 的圆角。"""
    m = max(1, math.ceil(rn / h))
    dz = np.arange(-m, m + 1)
    w = np.sqrt(np.clip(rn * rn - (dz * h) ** 2, 0.0, None))
    n = len(rt)
    pad = np.concatenate([np.full(m, rt[0]), rt, np.full(m, rt[-1])])
    c = np.max(np.stack([pad[m + k: m + k + n] + w[i] for i, k in enumerate(dz)]), 0)
    cp = np.concatenate([np.full(m, c[0]), c, np.full(m, c[-1])])
    return np.min(np.stack([cp[m + k: m + k + n] - w[i] for i, k in enumerate(dz)]), 0)


def _nose_envelope(cz, cr, rn, z0, h, n, upper):
    """一串刀尖圆弧圆心 (cz, cr) → 圆在网格格心上的最低点（外圆，upper=False）或最高点（内孔）：(格号, r)。
    按格心的 z 精确算（不能先在圆上取点再四舍五入到格：圆边上坡很陡，差半格就差好几丝）。"""
    m = math.ceil(rn / h) + 1
    kc = np.floor((cz - z0) / h).astype(int)
    kk = kc[:, None] + np.arange(-m, m + 1)[None, :]
    dz = z0 + (kk + 0.5) * h - cz[:, None]
    ok = (np.abs(dz) <= rn) & (kk >= 0) & (kk < n)
    dr = np.sqrt(np.clip(rn * rn - dz * dz, 0.0, None))
    rr = cr[:, None] + (dr if upper else -dr)
    return kk[ok], rr[ok]


# ---------------------------------------------------------------- 铣削仿真
def _in_polygon(X, Y, poly):
    """点是否在多边形内（射线法，向量化）。"""
    inside = np.zeros(X.shape, bool)
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if y0 == y1:
            continue
        cross = ((y0 > Y) != (y1 > Y)) & (X < x0 + (Y - y0) * (x1 - x0) / (y1 - y0))
        inside ^= cross
    return inside


def simulate_mill(parsed, stock, tools, target=None, h=None, tol=0.01, on_move=None):
    """stock：{"box": (xmin, ymin, xmax, ymax), "top": 0} 或 {"polygon": [[x, y], ..], "top": 0}（轴上铣键槽另给 "cyl_r"）
    tools：{刀号: {"kind": "endmill" | "ballend" | "drill" | "tap" | "chamfer" | "thread_mill", "d": 直径, "pitch": 丝锥螺距, "tip_d": 倒角刀刀尖直径,
           "angle": 倒角刀锥角, "core_d": 螺纹铣刀齿根直径}}
    target(x, y 网格) → 目标高度数组（None 表示不比对）。返回高度图、碰撞、过切 / 残留
    on_move(mv, H, xs, ys)：每段走刀切削之前调用（整机仿真查刀杆、刀柄碰剩下的材料，machine_sim.heightmap_hook）"""
    poly = np.asarray(stock["polygon"], float) if stock.get("polygon") else None
    if poly is not None:
        bx0, by0 = poly.min(0)
        bx1, by1 = poly.max(0)
    else:
        bx0, by0, bx1, by1 = (float(v) for v in stock["box"])
    xmin, ymin, xmax, ymax = bx0, by0, bx1, by1
    pad = max(t.get("d", 10) for t in tools.values()) if tools else 10.0
    xmin, ymin, xmax, ymax = xmin - pad, ymin - pad, xmax + pad, ymax + pad
    h = h or max(0.1, max(xmax - xmin, ymax - ymin) / 500.0)
    nx, ny = math.ceil((xmax - xmin) / h), math.ceil((ymax - ymin) / h)
    xs = xmin + (np.arange(nx) + 0.5) * h
    ys = ymin + (np.arange(ny) + 0.5) * h
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    inside = _in_polygon(X, Y, poly) if poly is not None else (X >= bx0) & (X <= bx1) & (Y >= by0) & (Y <= by1)
    top = float(stock.get("top", 0.0))
    AIR = -1e6
    H = np.where(inside, top, AIR)
    if stock.get("cyl_r"):                       # 轴类零件铣键槽：毛坯顶面是圆柱面（轴线沿 X，最高点 Z0）
        R0 = float(stock["cyl_r"])
        H = np.where(inside & (np.abs(Y) < R0), np.sqrt(np.clip(R0 ** 2 - Y ** 2, 0, None)) - R0, AIR)
    issues, ap_max = [], 0.0
    for mv in parsed["moves"]:
        if on_move is not None:
            on_move(mv, H, xs, ys)
        tl = tools.get(mv["tool"])
        if not tl:
            continue
        R = (tl["core_d"] if tl.get("kind") == "thread_mill" else tl["d"]) / 2   # 螺纹铣刀：牙不画，按齿根圆柱去料（到小径）
        k = math.ceil(R / h) + 1
        if mv.get("tap") is not None or tl.get("kind") == "tap":   # 丝锥：不按切削去料；查底孔钻到位、螺距与丝锥一致（ADR-0106 Q3b）
            if mv["t"] != "rapid" and mv["b"][2] < mv["a"][2]:
                pt = float(tl.get("pitch") or 0.0)
                if pt and abs((mv.get("tap") or 0.0) - pt) > 1e-3:
                    issues.append({"line": mv["line"], "level": "error",
                                   "text": f"攻丝进给 F 与转速 S 之比 {mv.get('tap') or 0:.3f} mm 不等于丝锥螺距 {pt:g}（会乱牙、断丝锥）"})
                r1 = (tl["d"] - 1.0825 * pt) / 2 - h if pt else R * 0.8
                x, y, z = mv["b"]
                ix, iy = int((x - xmin) / h), int((y - ymin) / h)
                a0, a1, b0, b1 = max(ix - k, 0), min(ix + k + 1, nx), max(iy - k, 0), min(iy + k + 1, ny)
                sub = H[a0:a1, b0:b1]
                msk = ((xs[a0:a1, None] - x) ** 2 + (ys[None, b0:b1] - y) ** 2) <= r1 * r1
                bottom = top - float(stock["height"]) if stock.get("height") else -math.inf   # 毛坯底面以下是空的
                if (msk & (sub > max(z, bottom) + 0.05)).any():
                    issues.append({"line": mv["line"], "level": "error",
                                   "text": f"攻丝前底孔没钻到位：丝锥 M{tl['d']:g} 到 Z{z:.2f} 处还有材料（底孔至少要到小径、到攻丝深度）"})
            continue
        ball = tl.get("kind") == "ballend"            # 球头刀（ADR-0106 Q3c 曲面评估）
        cone = None                                   # 倒角刀（锥形）：刀尖小端半径、tan(半锥角)
        if tl.get("kind") == "chamfer":
            cone = (float(tl.get("tip_d", 0.0)) / 2, math.tan(math.radians(float(tl.get("angle", 90.0)) / 2)))
        pts = _seg_points(np.array(mv["a"]), np.array(mv["b"]), h / 2)
        worst = 0.0
        # 切宽 ae：这段切掉的格在走刀方向的垂直方向上铺多宽（只算 XY 有走动的段；ADR-0106 Q3b）
        dxy = np.array(mv["b"][:2], float) - np.array(mv["a"][:2], float)
        lxy = float(np.hypot(*dxy))
        nrm = np.array([-dxy[1], dxy[0]]) / lxy if lxy >= h else None
        widths = []
        for x, y, z in pts:
            ix, iy = int((x - xmin) / h), int((y - ymin) / h)
            a0, a1 = max(ix - k, 0), min(ix + k + 1, nx)
            b0, b1 = max(iy - k, 0), min(iy + k + 1, ny)
            if a1 <= a0 or b1 <= b0:
                continue
            sub = H[a0:a1, b0:b1]
            rho2 = (xs[a0:a1, None] - x) ** 2 + (ys[None, b0:b1] - y) ** 2
            msk = rho2 <= R * R                                                          # 刀具圆盘盖住的格（按格中心）
            if ball:                                                                     # 球头刀：刀尖在球的最低点
                zt = z + R - np.sqrt(np.clip(R * R - rho2, 0.0, None))
            else:
                zt = z if cone is None else z + np.maximum(np.sqrt(rho2) - cone[0], 0.0) / cone[1]   # 倒角刀：锥面
            hit = msk & (sub > zt)
            if hit.any():
                worst = max(worst, float((sub[hit] - zt[hit] if (cone is not None or ball) else sub[hit] - z).max()))
                if nrm is not None:
                    ii, jj = np.nonzero(hit & (sub - z > 0.005))
                    if ii.size:
                        off = (xs[a0 + ii] - mv["a"][0]) * nrm[0] + (ys[b0 + jj] - mv["a"][1]) * nrm[1]
                        widths.append(float(off.max() - off.min()) + h)
                sub[hit] = zt[hit] if (cone is not None or ball) else z
        if worst > 0.005:
            if mv["t"] == "rapid":
                issues.append({"line": mv["line"], "level": "error", "text": f"快移撞到工件：切进 {worst:.2f} mm（快移不能切削）"})
            else:
                ap_max = max(ap_max, worst)
                mv["ap"] = worst
                if widths:                            # 每个刀位新切掉的那一弯月牙在垂直方向的宽度，取中位数（进出刀处的尖峰不算）
                    mv["ae"] = min(float(np.median(widths)), 2 * R)
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
