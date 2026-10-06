# -*- coding: utf-8 -*-
"""后处理（第 13 轮 C5）：把 cam.py 的动作表写成 FANUC 风格 G 代码。

机床表是教学示意值（行程按工件坐标系给，假定 G54 设在常用位置），不是某台真实机床的参数；功率、效率与工艺规程（hub/process.py WORKCENTER_POWER）一致。
"""
import datetime

MACHINES = {
    "CNC-L01": {"kind": "lathe", "name": "数控车床 CNC-L01", "max_rpm": 4000, "power_kw": 11.0, "eff": 0.8,
                "x": (-2.0, 320.0), "z": (-600.0, 250.0), "rapid": {"x": 12000.0, "z": 15000.0},
                "home": (200.0, 150.0), "tools": 8, "tool_change_s": 1.5},
    "KEY-01": {"kind": "mill", "name": "键槽铣床 KEY-01", "max_rpm": 3000, "power_kw": 4.0, "eff": 0.75,
               "x": (-250.0, 250.0), "y": (-100.0, 100.0), "z": (-150.0, 150.0),
               "rapid": {"x": 6000.0, "y": 6000.0, "z": 4000.0}, "tools": 1, "tool_change_s": 60.0},
    "VMC-01": {"kind": "mill", "name": "立式加工中心 VMC-01", "max_rpm": 8000, "power_kw": 15.0, "eff": 0.8,
               "x": (-400.0, 400.0), "y": (-250.0, 250.0), "z": (-400.0, 150.0),
               "rapid": {"x": 24000.0, "y": 24000.0, "z": 20000.0}, "tools": 24, "tool_change_s": 4.0},
    "HMC-01": {"kind": "mill", "name": "卧式加工中心 HMC-01", "max_rpm": 6000, "power_kw": 18.5, "eff": 0.8,
               "x": (-400.0, 400.0), "y": (-300.0, 300.0), "z": (-400.0, 200.0),
               "rapid": {"x": 30000.0, "y": 30000.0, "z": 30000.0}, "tools": 40, "tool_change_s": 5.0},
}


def machine_of(workstation):
    """“数控车床 CNC-L01” 或 “CNC-L01” → 机床编号"""
    for k in MACHINES:
        if workstation and k in workstation:
            return k
    return None


def num(v, nd=3):
    """FANUC 数字：一定带小数点（不带小数点的 X200 在很多 FANUC 系统里是 0.2 mm），去掉多余的 0，至少保留一位小数（35.0）"""
    s = "{:.{}f}".format(float(v), nd).rstrip("0")
    if s.endswith("."):
        s += "0"
    return "0.0" if s == "-0.0" else s


def _comment(text):
    # 注释里不能有括号和 %（% 在 FANUC 里是程序开始 / 结束符）
    return "(" + str(text).replace("(", "[").replace(")", "]").replace("（", "[").replace("）", "]").replace("%", " pct") + ")"


def header(prog, lines):
    h = prog.get("header", {})
    m = MACHINES[prog["machine"]]
    lines += ["%", "O{:04d} {}".format(int(prog.get("number", 1)), _comment(prog.get("title", "")))]
    for k, lab in (("item", "零件"), ("revision", "版本"), ("operation", "工序"), ("stock", "毛坯"), ("author", "编程")):
        if h.get(k):
            lines.append(_comment("{} {}".format(lab, h[k])))
    lines.append(_comment("机床 " + m["name"]))
    lines.append(_comment("生成 问渠数控编程 {}".format(h.get("date") or datetime.date.today().isoformat())))
    for op in prog["ops"]:
        t = op["tool"]
        lines.append(_comment("T{:02d} {}{}".format(t["n"], t.get("name", ""), " D{}".format(num(t["d"])) if t.get("d") else "")))


def post_lathe(prog):
    """数控车：G18（ZX 平面）、X 直径编程、G99 每转进给、G96 恒线速 + G50 限速"""
    m = MACHINES[prog["machine"]]
    lines = []
    header(prog, lines)
    lines.append("G21 G18 G40 G97 G99")
    hx, hz = m["home"]
    for op in prog["ops"]:
        t, sp = op["tool"], op["spindle"]
        lines.append(_comment(op.get("title", "")))
        lines.append("G00 X{} Z{}".format(num(hx), num(hz)))
        lines.append("T{:02d}{:02d}".format(t["n"], t.get("offset", t["n"])))
        if sp.get("css"):
            lines.append("G50 S{}".format(int(min(sp.get("max_rpm", m["max_rpm"]), m["max_rpm"]))))
            lines.append("G96 S{} M03".format(int(round(sp["css"]))))
        else:
            lines.append("G97 S{} M03".format(int(round(sp["rpm"]))))
        first, last_f, mode = True, None, None
        pos = {"x": hx, "z": hz}
        for mv in op["moves"]:
            if mv["t"] == "comment":
                lines.append(_comment(mv["text"]))
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
        lines += ["G00 X{} Z{} M09".format(num(hx), num(hz)), "M05"]
    lines += ["M30", "%"]
    return "\n".join(lines) + "\n"


def post_mill(prog):
    """2.5 轴铣：G17、G90 绝对、G94 每分进给、G54、M06 换刀、G43 长度补偿、G81 / G83 钻孔循环"""
    m = MACHINES[prog["machine"]]
    lines = []
    header(prog, lines)
    lines.append("G21 G17 G40 G49 G80 G90 G94")
    for op in prog["ops"]:
        t, sp = op["tool"], op["spindle"]
        safe = op.get("safe", 50.0)
        lines.append(_comment(op.get("title", "")))
        lines += ["T{} M06".format(t["n"]), "G54", "S{} M03".format(int(round(sp["rpm"])))]
        mvs = [mv for mv in op["moves"] if mv["t"] != "comment"]
        x0 = next((mv for mv in mvs if "x" in mv), {"x": 0, "y": 0})
        lines.append("G00 X{} Y{}".format(num(x0["x"]), num(x0["y"])))
        lines.append("G43 Z{} H{:02d} M08".format(num(safe), t.get("offset", t["n"])))
        last_f, mode, cyc = None, None, None
        pos = {"x": x0["x"], "y": x0["y"], "z": safe}
        for mv in op["moves"]:
            if mv["t"] == "comment":
                lines.append(_comment(mv["text"]))
                continue
            if mv["t"] == "drill":
                key = (mv["z"], mv["r"], mv.get("q") or 0, mv["f"])
                if cyc != key:
                    if cyc is not None:
                        lines.append("G80")
                    lines.append("G00 Z{}".format(num(mv.get("safe", 5.0))))
                    g = "G83" if mv.get("q") else "G81"
                    w = ["G98", g, "X" + num(mv["x"]), "Y" + num(mv["y"]), "Z" + num(mv["z"]), "R" + num(mv["r"])]
                    if mv.get("q"):
                        w.append("Q" + num(mv["q"]))
                    w.append("F" + num(mv["f"], 1))
                    lines.append(" ".join(w))
                    cyc, mode, last_f = key, None, mv["f"]
                else:
                    lines.append("X{} Y{}".format(num(mv["x"]), num(mv["y"])))
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
        lines += ["G00 Z{} M09".format(num(safe)), "M05"]
    lines += ["G91 G28 Z0.0", "G90", "M30", "%"]
    return "\n".join(lines) + "\n"


def post(prog):
    return post_lathe(prog) if MACHINES[prog["machine"]]["kind"] == "lathe" else post_mill(prog)
