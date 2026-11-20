"""后处理（ADR-0059）：把刀路动作表写成 FANUC 风格 G 代码。搬自问渠数字工厂第 13 轮 cae/cam_post.py，机床参数改为传入。"""

from __future__ import annotations

import math


def num(v, nd=3):
    """FANUC 数字：一定带小数点（不带小数点的 X200 在很多 FANUC 系统里是 0.2 mm），去掉多余的 0。"""
    s = f"{float(v):.{nd}f}".rstrip("0")
    if s.endswith("."):
        s += "0"
    return "0.0" if s == "-0.0" else s


def comment(text):
    """注释里不能有括号和 %（% 在 FANUC 里是程序开始 / 结束符）。"""
    return "(" + str(text).replace("(", "[").replace(")", "]").replace("（", "[").replace("）", "]").replace("%", " pct") + ")"


def _header(prog, machine, lines):
    h = prog.get("header", {})
    lines += ["%", f"O{int(prog.get('number', 1)):04d} {comment(prog.get('title', ''))}"]
    for k, lab in (("item", "零件"), ("revision", "版本"), ("operation", "工序"), ("stock", "毛坯"), ("material", "材料"),
                   ("author", "编程")):
        if h.get(k):
            lines.append(comment(f"{lab} {h[k]}"))
    lines.append(comment("机床 " + machine["name"]))
    lines.append(comment(prog.get("generator") or "FreeCAD AI Parts 数控编程"))
    for op in prog["ops"]:
        t = op["tool"]
        lines.append(comment(f"T{t['n']:02d} {t.get('name', '')}" + (f" D{num(t['d'])}" if t.get("d") else "")))


def post_lathe(prog, machine):
    """数控车：G18（ZX 平面）、X 直径编程、G99 每转进给、G96 恒线速 + G50 限速。"""
    lines: list[str] = []
    _header(prog, machine, lines)
    lines.append("G21 G18 G40 G97 G99")
    hx, hz = machine["home"]
    for op in prog["ops"]:
        t, sp = op["tool"], op["spindle"]
        if op.get("interp"):                       # 车铣：动力刀铣削工序（ADR-0106 C2b），仿真用的写法
            lines += millturn_lines(op, (hx, hz), None)
            continue
        lines.append(comment(op.get("title", "")))
        lines.append(f"G00 X{num(hx)} Z{num(hz)}")
        lines.append(f"T{t['n']:02d}{t.get('offset', t['n']):02d}")
        if sp.get("css"):
            lines.append(f"G50 S{int(min(sp.get('max_rpm', machine['max_rpm']), machine['max_rpm']))}")
            lines.append(f"G96 S{round(sp['css'])} M03")
        else:
            lines.append(f"G97 S{round(sp['rpm'])} M03")
        first, last_f, mode = True, None, None
        pos = {"x": hx, "z": hz}
        for mv in op["moves"]:
            if mv["t"] == "comment":
                lines.append(comment(mv["text"]))
                continue
            g = {"rapid": "G00", "thread": "G32"}.get(mv["t"], "G01")
            ax = []
            for a in ("x", "z"):
                if a not in pos or abs(pos[a] - mv[a]) > 5e-4:
                    ax.append(a.upper() + num(mv[a]))
                    pos[a] = mv[a]
            if not ax:
                continue
            w = [g] if g != mode else []
            mode = g
            w += ax
            if g == "G32":
                w.append("F" + num(mv["pitch"], 4))
                last_f = None
            elif g == "G01" and mv.get("f") != last_f:
                w.append("F" + num(mv["f"], 3))
                last_f = mv["f"]
            if first:
                w.append("M08")
                first = False
            lines.append(" ".join(w))
        lines += [f"G00 X{num(hx)} Z{num(hz)} M09", "M05"]
    lines += ["M30", "%"]
    return "\n".join(lines) + "\n"


def tilt_lines(op) -> list[str]:
    """3+2 倾斜面（ADR-0106 C2a）：工序带 frame 时写 G68.2（平面原点 + Z-X-Z 欧拉角）和 G53.1（刀轴转到平面法向）；
    这道工序的坐标都是平面坐标，工序结束 G69 取消"""
    fr = op.get("frame")
    if not fr:
        return []
    from analysis.cam import tilt

    i, j, k = tilt.euler_zxz(tilt.matrix(fr))
    o = fr["origin"]
    # 转工作台前先把 Z 退到机床原点（刀具离开工件），再定倾斜面、转回转轴
    return ["G91 G28 Z0.0", "G90", f"G68.2 X{num(o[0])} Y{num(o[1])} Z{num(o[2])} I{num(i, 4)} J{num(j, 4)} K{num(k, 4)}", "G53.1"]


def millturn_lines(op, home, cfg_mt, nd=3, fnd=1, cm=comment) -> list[str]:
    """车铣的铣削工序：极坐标插补 interp = "polar"（G12.1 … G13.1，程序 X 直径、C 毫米）或圆柱插补 interp = {"cyl": 半径}
    （G7.1 C 半径 … G7.1 C0，程序 C 角度）；每分进给 G98，完了回 G99。
    cfg_mt：后处理配置的 millturn（开 / 关动力刀、C 轴的程序行）；None 时是仿真用的程序：主轴写 G97 S M03 代替动力刀（仿真只认“主轴在转”）"""
    hx, hz = home
    t, sp = op["tool"], op["spindle"]
    rpm = round(float(sp["rpm"]))
    out = [cm(op.get("title", "")), f"G00 X{num(hx, nd)} Z{num(hz, nd)}", f"T{t['n']:02d}{t.get('offset', t['n']):02d}"]
    if cfg_mt is None:
        out += ["G98", f"G97 S{rpm} M03"]
    else:
        out += ["G98", "M05", *cfg_mt.get("c_on", []), *cfg_mt.get("live_on", []), f"S{rpm}"]
    cyl = op["interp"].get("cyl") if isinstance(op["interp"], dict) else None
    out.append(f"G07.1 C{num(cyl, nd)}" if cyl else "G12.1")
    pos, mode, last_f = {}, None, None
    for mv in op["moves"]:
        if mv["t"] == "comment":
            out.append(cm(mv["text"]))
            continue
        g = "G00" if mv["t"] == "rapid" else "G01"
        ax = []
        for a in ("x", "c", "z"):
            if a in mv and (a not in pos or abs(pos[a] - mv[a]) > 5e-4):
                ax.append(a.upper() + num(mv[a], nd))
                pos[a] = mv[a]
        if not ax:
            continue
        w = [g] if g != mode else []
        mode = g
        w += ax
        if g == "G01" and mv.get("f") != last_f:
            w.append("F" + num(mv["f"], fnd))
            last_f = mv["f"]
        out.append(" ".join(w))
    out.append("G07.1 C0" if cyl else "G13.1")
    if cfg_mt is None:
        out += ["M05", "G99", f"G00 X{num(hx, nd)} Z{num(hz, nd)}"]
    else:
        out += [*cfg_mt.get("live_off", []), *cfg_mt.get("c_off", []), "G99", f"G00 X{num(hx, nd)} Z{num(hz, nd)}"]
    return out


def millturn_lines_siemens(op, home, cfg_mt, nd=3, fnd=1, cm=comment) -> list[str]:
    """西门子的车铣铣削工序（ADR-0106 C2b）：端面 TRANSMIT、圆柱面 TRACYL(d)，都在半径编程 DIAMOF 下写，完了 TRAFOOF、DIAMON。
    中间格式与 FANUC 写法相同（极坐标：x 直径、c 毫米；圆柱：x 直径、c 度），这里换成：
    TRANSMIT：X = x/2、Y = c（端面上的直角坐标，mm）；TRACYL(d)：X = x/2（半径，下刀深度）、Y = c·π·d/360（工作直径 d 上展开的弧长 mm）。
    每分进给 G94，完了回 G95。开 / 关动力刀、C 轴的程序行按后处理配置（例如切主主轴 SETMS(2) 由配置写）。"""
    hx, hz = home
    t, sp = op["tool"], op["spindle"]
    rpm = round(float(sp["rpm"]))
    cyl = op["interp"].get("cyl") if isinstance(op["interp"], dict) else None
    d = 2.0 * float(cyl) if cyl else None
    out = [cm(op.get("title", "")), f"G0 X{num(hx, nd)} Z{num(hz, nd)}", f"T{t['n']} D1", "M5",
           *cfg_mt.get("c_on", []), *cfg_mt.get("live_on", []), f"S{rpm}", "G94", "DIAMOF"]
    out += [f"TRACYL({num(d, nd)})", "G19"] if cyl else ["TRANSMIT", "G17"]
    pos, mode, last_f = {}, None, None
    for mv in op["moves"]:
        if mv["t"] == "comment":
            out.append(cm(mv["text"]))
            continue
        g = "G0" if mv["t"] == "rapid" else "G1"
        v = {"X": mv["x"] / 2.0, "Y": (mv["c"] * math.pi * d / 360.0) if cyl else mv["c"], "Z": mv["z"]}
        ax = []
        for a in ("X", "Y", "Z"):
            if a not in pos or abs(pos[a] - v[a]) > 5e-4:
                ax.append(a + num(v[a], nd))
                pos[a] = v[a]
        if not ax:
            continue
        w = [g] if g != mode else []
        mode = g
        w += ax
        if g == "G1" and mv.get("f") != last_f:
            w.append("F" + num(mv["f"], fnd))
            last_f = mv["f"]
        out.append(" ".join(w))
    out += ["TRAFOOF", "DIAMON", "G18", *cfg_mt.get("live_off", []), *cfg_mt.get("c_off", []), "G95", f"G0 X{num(hx, nd)} Z{num(hz, nd)}"]
    return out


def post_mill(prog, machine):
    """2.5 轴铣：G17、G90 绝对、G94 每分进给、G54、M06 换刀、G43 长度补偿、G81 / G83 钻孔循环。"""
    lines: list[str] = []
    _header(prog, machine, lines)
    lines.append("G21 G17 G40 G49 G80 G90 G94")
    for op in prog["ops"]:
        t, sp = op["tool"], op["spindle"]
        safe = op.get("safe", 50.0)
        op["_line"] = len(lines) + 1             # 这道工序从程序第几行起（仿真后按工序统计用，如自适应开粗的切宽）
        lines.append(comment(op.get("title", "")))
        lines += [f"T{t['n']} M06", "G54", f"S{round(sp['rpm'])} M03"]
        lines += tilt_lines(op)
        mvs = [mv for mv in op["moves"] if mv["t"] != "comment"]
        x0 = next((mv for mv in mvs if "x" in mv), {"x": 0, "y": 0})
        lines.append(f"G00 X{num(x0['x'])} Y{num(x0['y'])}")
        lines.append(f"G43 Z{num(safe)} H{t.get('offset', t['n']):02d} M08")
        last_f, mode, cyc = None, None, None
        pos = {"x": x0["x"], "y": x0["y"], "z": safe}
        for mv in op["moves"]:
            if mv["t"] == "comment":
                lines.append(comment(mv["text"]))
                continue
            if mv["t"] == "tap":                          # 刚性攻丝 G84：F = 螺距 × 转速（G94）
                f = mv["pitch"] * float(sp["rpm"])
                key = ("tap", mv["z"], mv["r"], mv["pitch"])
                if cyc != key:
                    if cyc is not None:
                        lines.append("G80")
                    lines += [f"G00 Z{num(mv.get('safe', 5.0))}", f"M29 S{round(sp['rpm'])}",
                              f"G98 G84 X{num(mv['x'])} Y{num(mv['y'])} Z{num(mv['z'])} R{num(mv['r'])} F{num(f, 1)}"]
                    cyc, mode, last_f = key, None, f
                else:
                    lines.append(f"X{num(mv['x'])} Y{num(mv['y'])}")
                pos = {"x": mv["x"], "y": mv["y"], "z": mv.get("safe", 5.0)}
                continue
            if mv["t"] == "drill":
                key = (mv["z"], mv["r"], mv.get("q") or 0, mv["f"])
                if cyc != key:
                    if cyc is not None:
                        lines.append("G80")
                    lines.append(f"G00 Z{num(mv.get('safe', 5.0))}")
                    g = "G83" if mv.get("q") else "G81"
                    w = ["G98", g, "X" + num(mv["x"]), "Y" + num(mv["y"]), "Z" + num(mv["z"]), "R" + num(mv["r"])]
                    if mv.get("q"):
                        w.append("Q" + num(mv["q"]))
                    w.append("F" + num(mv["f"], 1))
                    lines.append(" ".join(w))
                    cyc, mode, last_f = key, None, mv["f"]
                else:
                    lines.append(f"X{num(mv['x'])} Y{num(mv['y'])}")
                pos = {"x": mv["x"], "y": mv["y"], "z": mv.get("safe", 5.0)}
                continue
            if cyc is not None:
                lines.append("G80")
                cyc = None
            g = "G00" if mv["t"] == "rapid" else "G01"
            ax = []
            for a in ("x", "y", "z"):
                if a in mv and (a not in pos or abs(pos[a] - mv[a]) > 5e-4):
                    ax.append(a.upper() + num(mv[a]))
                    pos[a] = mv[a]
            if not ax:
                continue
            w = [g] if g != mode else []
            mode = g
            w += ax
            if g == "G01" and mv.get("f") != last_f:
                w.append("F" + num(mv["f"], 1))
                last_f = mv["f"]
            lines.append(" ".join(w))
        if cyc is not None:
            lines.append("G80")
        lines += [f"G00 Z{num(safe)} M09", "M05"]
        if op.get("frame"):
            lines.append("G69")
    lines += ["G91 G28 Z0.0", "G90", "M30", "%"]
    return "\n".join(lines) + "\n"


def post(prog, machine):
    return post_lathe(prog, machine) if machine["kind"] in ("lathe", "mill_turn") else post_mill(prog, machine)
