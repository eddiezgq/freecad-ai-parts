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


def b_turn_note(op) -> str:
    bt = op["b_turn"]
    return f"B-AXIS TURNING T{op['tool']['n']} L{bt['L']:.3f} B{bt['deg']:g} NO TOOL OFFSET X Z = MACHINE AXES"


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
        if op.get("b_turn"):                       # B 轴车削（ADR-0106 C4a）：B 定位，走刀写 B 轴回转中心的位置
            lines += [comment(b_turn_note(op)), f"G00 B{num(op['b_turn']['deg'])}"]
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


def live_on_lines(cfg_mt, rpm) -> list[str]:
    """开动力刀的程序行：行里写了 {rpm} 的（如哈斯 M133 P{rpm}）把转速填进去、不再另写 S；没写的照旧随后写 S 转速（ADR-0124）"""
    lines = cfg_mt.get("live_on", [])
    if any("{rpm}" in ln for ln in lines):
        return [ln.replace("{rpm}", str(rpm)) for ln in lines]
    return [*lines, f"S{rpm}"]


def millturn_lines(op, home, cfg_mt, nd=3, fnd=1, cm=comment) -> list[str]:
    """车铣的铣削工序：极坐标插补 interp = "polar"（G12.1 … G13.1，程序 X 直径、C 毫米）或圆柱插补 interp = {"cyl": 半径}
    （G7.1 C 半径 … G7.1 C0，程序 C 角度）；每分进给 G98，完了回 G99。
    cfg_mt：后处理配置的 millturn（开 / 关动力刀、C 轴的程序行）；None 时是仿真用的程序：主轴写 G97 S M03 代替动力刀（仿真只认“主轴在转”）"""
    hx, hz = home
    t, sp = op["tool"], op["spindle"]
    rpm = round(float(sp["rpm"]))
    out = [cm(op.get("title", "")), f"G00 X{num(hx, nd)} Z{num(hz, nd)}", f"T{t['n']:02d}{t.get('offset', t['n']):02d}"]
    if op.get("b_mill") is not None:          # B 轴车铣中心（ADR-0106 C4a）：轴向 B90、径向 B0 定位；正式程序随后开沿刀轴的刀长补偿（ADR-0120）
        out.append(f"G00 B{num(op['b_mill'], nd)}")
        if cfg_mt is not None:
            out += cfg_mt.get("b_tool_comp", [])
    if cfg_mt is None:
        out += ["G98", f"G97 S{rpm} M03"]
    else:
        out += ["G98", "M05", *cfg_mt.get("c_on", []), *live_on_lines(cfg_mt, rpm)]
    cyl = op["interp"].get("cyl") if isinstance(op["interp"], dict) else None
    idx = op["interp"].get("index") if isinstance(op["interp"], dict) else None
    if idx is not None:                       # C 轴分度 + Y 轴铣（G19，ADR-0106 C2b）
        out += [f"G00 C{num(idx, nd)}", "G19"]
    else:
        out.append(f"G07.1 C{num(cyl, nd)}" if cyl else "G12.1")
    pos, mode, last_f = {}, None, None
    for mv in op["moves"]:
        if mv["t"] == "comment":
            out.append(cm(mv["text"]))
            continue
        g = "G00" if mv["t"] == "rapid" else "G01"
        ax = []
        for a in (("x", "y", "z") if idx is not None else ("x", "c", "z")):
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
    out += ["G00 Y0.0", "G18"] if idx is not None else ["G07.1 C0" if cyl else "G13.1"]
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
    idx = op["interp"].get("index") if isinstance(op["interp"], dict) else None
    d = 2.0 * float(cyl) if cyl else None
    out = [cm(op.get("title", "")), f"G0 X{num(hx, nd)} Z{num(hz, nd)}", f"T{t['n']} D1",
           *([f"G0 B{num(op['b_mill'], nd)}", *cfg_mt.get("b_tool_comp", [])] if op.get("b_mill") is not None else []), "M5",
           *cfg_mt.get("c_on", []), *live_on_lines(cfg_mt, rpm), "G94"]
    if idx is not None:                       # C 轴分度 + Y 轴铣：直径编程照旧，G19 平面
        out += [f"G0 C{num(idx, nd)}", "G19"]
    else:
        out += ["DIAMOF", *([f"TRACYL({num(d, nd)})", "G19"] if cyl else ["TRANSMIT", "G17"])]
    pos, mode, last_f = {}, None, None
    for mv in op["moves"]:
        if mv["t"] == "comment":
            out.append(cm(mv["text"]))
            continue
        g = "G0" if mv["t"] == "rapid" else "G1"
        v = ({"X": mv["x"], "Y": mv["y"], "Z": mv["z"]} if idx is not None else
             {"X": mv["x"] / 2.0, "Y": (mv["c"] * math.pi * d / 360.0) if cyl else mv["c"], "Z": mv["z"]})
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
    out += ["G0 Y0.0", "G18"] if idx is not None else ["TRAFOOF", "DIAMON", "G18"]
    out += [*cfg_mt.get("live_off", []), *cfg_mt.get("c_off", []), "G95", f"G0 X{num(hx, nd)} Z{num(hz, nd)}"]
    return out


def simul5_lines(op, machine, safe) -> list[str]:
    """五轴联动（刀尖跟随 RTCP，ADR-0106 C3a）：FANUC 写法。先退 Z 到机床原点、转回转轴到第一个刀轴，再 G43.4 开刀尖跟随，
    每段写刀尖工件坐标 + 回转轴角度；完了 G49 关、退 Z。走刀点都要带刀轴 axis"""
    from analysis.cam import fiveaxis as FA

    model = machine.get("model") or {}
    mvs = [mv for mv in op["moves"] if mv["t"] in ("rapid", "feed")]
    if not mvs or any(mv.get("axis") is None for mv in mvs):
        raise ValueError("五轴联动工序的每个走刀点都要带刀轴 axis")
    rots = FA.rotary_path(model, [mv["axis"] for mv in mvs], breaks=[i for i, mv in enumerate(mvs) if mv["t"] == "rapid"])
    t = op["tool"]
    if op.get("_nonrtcp"):
        return nonrtcp_lines(op, machine, mvs, rots, "fanuc")
    L = ["G91 G28 Z0.0", "G90", "G00 " + " ".join(f"{k}{num(v)}" for k, v in FA.rotary_words(model, rots[0])),
         f"G43.4 H{t.get('offset', t['n']):02d}"]
    pos, rprev, mode, last_f = {}, {}, None, None
    for k, (mv, q) in enumerate(zip(mvs, rots)):
        g = "G00" if mv["t"] == "rapid" else "G01"
        w = []
        for a in ("x", "y", "z"):
            if a in mv and (a not in pos or abs(pos[a] - mv[a]) > 5e-4):
                w.append(a.upper() + num(mv[a]))
                pos[a] = mv[a]
        for a, v in FA.rotary_words(model, q):
            if a not in rprev or abs(rprev[a] - v) > 5e-4:
                w.append(a + num(v))
                rprev[a] = v
        if not w:
            continue
        line = ([g] if g != mode else []) + w
        mode = g
        if g == "G01" and mv.get("f") != last_f:
            line.append("F" + num(mv["f"], 1))
            last_f = mv["f"]
        if k == 0:
            line.append("M08")
        lines_ok = " ".join(line)
        L.append(lines_ok)
    L += ["G49", "G91 G28 Z0.0", "G90", "M09", "M05"]
    return L


def nonrtcp_lines(op, machine, mvs, rots, dialect, h=None, fmt=None, ffmt=None) -> list[str]:
    """五轴联动、机床没开刀尖跟随（ADR-0106 C3c-2）：写机床各轴位置（按刀长、工件零点在机床坐标里的位置逐点逆解；
    机床直线插补时刀尖走弯超过 0.01 mm 就插点）。不加长度补偿，G54 要设为 0；换刀长、换装夹要重出程序（程序头写明）。
    dialect：fanuc / siemens / heidenhain（h 是海德汉的数字写法）"""
    from analysis.cam import fiveaxis as FA

    model = machine.get("model") or {}
    nr = op["_nonrtcp"]
    L0, off = float(nr["L"]), [float(v) for v in nr["off"]]
    pts = FA.machine_points(model, [[mv["x"], mv["y"], mv["z"]] for mv in mvs], [mv["axis"] for mv in mvs], rots, L0, off)
    h = h or (lambda v: v)
    nm = fmt or num
    kl, sie = dialect == "heidenhain", dialect == "siemens"
    note = f"NON-RTCP T{op['tool']['n']} L{L0:.3f} WORK ZERO X{off[0]:g} Y{off[1]:g} Z{off[2]:g} G54=0 NO LENGTH OFFSET"
    order = [a["id"] for a in model["axes"]]
    first = pts[0][0]
    rot0 = " ".join(f"{a}{h(nm(first[a]))}" for a in order if a in first and any(x["id"] == a and x["type"] == "rotary" for x in model["axes"]))
    if kl:
        L = [f"; {note}", "M140 MB MAX", f"L {rot0} R0 FMAX"]
    elif sie:
        L = [f"; {note}", "G0 SUPA Z0", f"G0 {rot0}"]
    else:
        L = [f"({note})", "G49", "G91 G28 Z0.0", "G90", f"G00 {rot0}"]
    prev, mode, last_f = {}, None, None
    for k, (q, _tip, _w, i) in enumerate(pts):
        mv = mvs[i]
        w = []
        for a in order:
            if a in q and (a not in prev or abs(prev[a] - q[a]) > 5e-4):
                w.append(a + h(nm(q[a])))
                prev[a] = q[a]
        if not w:
            continue
        fw = ""
        if mv["t"] == "feed" and mv.get("f") != last_f:
            fw = ffmt(mv["f"], 1) if ffmt else num(mv["f"], 1)
            last_f = mv["f"]
        if kl:
            L.append(" ".join(f"L {' '.join(w)} R0 {'FMAX' if mv['t'] == 'rapid' else (f'F{fw}' if fw else '')}".split()))
            continue
        g = ("G0" if sie else "G00") if mv["t"] == "rapid" else ("G1" if sie else "G01")
        L.append(" ".join(([g] if g != mode else []) + w + ([f"F{fw}"] if fw else [])))
        mode = g
    if kl:
        L += ["M140 MB MAX", "M9", "M5"]
    elif sie:
        L += ["G0 SUPA Z0", "M9", "M5"]
    else:
        L += ["G91 G28 Z0.0", "G90", "M09", "M05"]
    return L


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
        if op.get("simul5"):
            lines += simul5_lines(op, machine, safe)
            continue
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
