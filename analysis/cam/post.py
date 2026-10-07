"""后处理（ADR-0059）：把刀路动作表写成 FANUC 风格 G 代码。搬自问渠数字工厂第 13 轮 cae/cam_post.py，机床参数改为传入。"""

from __future__ import annotations


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
            g = "G00" if mv["t"] == "rapid" else "G01"
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
            if g == "G01" and mv.get("f") != last_f:
                w.append("F" + num(mv["f"], 3))
                last_f = mv["f"]
            if first:
                w.append("M08")
                first = False
            lines.append(" ".join(w))
        lines += [f"G00 X{num(hx)} Z{num(hz)} M09", "M05"]
    lines += ["M30", "%"]
    return "\n".join(lines) + "\n"


def post_mill(prog, machine):
    """2.5 轴铣：G17、G90 绝对、G94 每分进给、G54、M06 换刀、G43 长度补偿、G81 / G83 钻孔循环。"""
    lines: list[str] = []
    _header(prog, machine, lines)
    lines.append("G21 G17 G40 G49 G80 G90 G94")
    for op in prog["ops"]:
        t, sp = op["tool"], op["spindle"]
        safe = op.get("safe", 50.0)
        lines.append(comment(op.get("title", "")))
        lines += [f"T{t['n']} M06", "G54", f"S{round(sp['rpm'])} M03"]
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
    lines += ["G91 G28 Z0.0", "G90", "M30", "%"]
    return "\n".join(lines) + "\n"


def post(prog, machine):
    return post_lathe(prog, machine) if machine["kind"] == "lathe" else post_mill(prog, machine)
