"""问渠CAM 后处理（ADR-0104 第 2、4 节；C1：FANUC 车 / 铣、西门子车 / 铣、广州数控车）。

输入是刀路的中间格式（`paths.py` 的动作表：工序 ops，每道工序 tool、spindle、moves），按数控系统写成程序。
安全底线（ADR-0104 第 4 节，写死在这里）：
1. 没有整机仿真结果、或整机仿真不通过，`render` 拒绝输出（ReleaseError）。
2. 程序头写：机床、后处理名称与版本、仿真指纹、仿真结论，以及“首件须空运行、单段试切确认”。
3. 没在实机上验证过的后处理（`POSTS[...]["verified"]` 为 False，现在全部是），程序头写“未经实机验证”，结果里 verified = False，界面标黄。

注释：FANUC、广数的注释只用英文 ASCII（不少系统遇到中文报警或乱码）；西门子用中文。
钻孔一律展开成 G00 / G01（不用各家不同的钻孔循环），啄钻每次退到 R 平面。
广数：恒线速限速各型号做法不同（参数或 G50 S），未经实机核实前一律用 G97 恒转速，按本道工序最大直径算转速（偏慢、安全）。
"""

from __future__ import annotations

import math

from analysis.cam.post import num

VERSION = "c1.1"
FIRST_PART_CN = "首件须空运行、单段试切确认"
FIRST_PART_EN = "FIRST PART: DRY RUN AND SINGLE BLOCK REQUIRED"


class ReleaseError(ValueError):
    """不满足安全底线，不输出程序"""


def _ascii(text: str) -> str:
    s = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in str(text))
    return " ".join(s.replace("(", "[").replace(")", "]").replace("%", " pct").split())


def _paren(text: str) -> str:
    t = _ascii(text)
    return f"({t})" if t else ""


def _semi(text: str) -> str:
    return "; " + str(text).replace("\n", " ")


def _header_items(prog, machine, sim_res, post):
    m = machine.get("model") or machine
    items = [("MACHINE", "机床", f"{m['id']} {m['name']}"),
             ("POST", "后处理", f"{post['name']} {VERSION}"),
             ("SIM FINGERPRINT", "整机仿真指纹", sim_res["fingerprint"]),
             ("SIM RESULT", "整机仿真结论", {"pass": "PASS", "unknown": "PASS WITH UNKNOWN ITEMS"}[sim_res["status"]]),
             ("", "", FIRST_PART_EN)]
    if not post["verified"]:
        items.append(("", "", "POST NOT VERIFIED ON A REAL MACHINE"))
    if machine.get("example") or m.get("example"):
        items.append(("", "", "EXAMPLE MACHINE - FICTIONAL DATA"))
    return items


def _op_dmax(op):
    xs = [mv["x"] for mv in op["moves"] if mv.get("t") in ("feed", "thread") and "x" in mv]
    return max(xs) if xs else 0.0


def _lathe_moves(op):
    return [mv for mv in op["moves"] if mv["t"] in ("rapid", "feed", "thread")]


# ---------------------------------------------------------------- 车
def _lathe(prog, machine, sim_res, post, dialect):
    m = machine.get("model") or machine
    home = machine.get("home") or m.get("lathe_home_mm")
    if not home:
        raise ReleaseError("机床文件没写车床换刀点 lathe_home_mm")
    hx, hz = home
    max_rpm = float(machine["max_rpm"])
    L: list[str] = []
    sie = dialect == "siemens"
    use_cycles = bool(prog.get("cycles")) and dialect in ("fanuc", "gsk")     # 西门子的 CYCLE95 / 97 还没做：照样出展开的直线段
    g71_blocks: dict = {}
    nblock = [100]
    if sie:
        L.append(_semi(f"程序 {prog.get('number', 1)} {prog.get('title', '')}"))
        for en, cn, v in _header_items(prog, machine, sim_res, post):
            L.append(_semi(f"{cn}：{v}" if cn else (FIRST_PART_CN if v == FIRST_PART_EN else
                                                     "后处理未经实机验证" if v.startswith("POST NOT") else "示例机床，参数虚构")))
        L.append("G18 G90 G95 DIAMON G40")
    else:
        L += ["%", f"O{int(prog.get('number', 1)):04d} {_paren(prog.get('title_en') or 'WENQUEST CAM')}".rstrip()]
        for en, _cn, v in _header_items(prog, machine, sim_res, post):
            L.append(_paren(f"{en} {v}" if en else v))
        L.append("G21 G18 G40 G97 G99")
    for k, op in enumerate(prog["ops"], 1):
        t, sp = op["tool"], op["spindle"]
        L.append(_semi(f"工序 {k}：{op.get('title', '')}") if sie else _paren(f"OP{k} T{t['n']:02d}"))
        L.append(f"G0 X{num(hx)} Z{num(hz)}" if sie else f"G00 X{num(hx)} Z{num(hz)}")
        L.append(f"T{t['n']} D1" if sie else f"T{t['n']:02d}{t.get('offset', t['n']):02d}")
        threading = any(mv["t"] == "thread" for mv in op["moves"])
        css = sp.get("css") if not threading else None
        if css and dialect == "gsk":            # 广数：用 G97，按本工序最大直径算转速
            rpm = min(1000.0 * css / (math.pi * max(_op_dmax(op), 1.0)), float(sp.get("max_rpm", max_rpm)), max_rpm)
            css = None
        else:
            rpm = sp.get("rpm")
        if css:
            lim = int(min(float(sp.get("max_rpm", max_rpm)), max_rpm))
            L += [f"G96 S{round(css)} LIMS={lim} M3"] if sie else [f"G50 S{lim}", f"G96 S{round(css)} M03"]
        else:
            if rpm is None:
                raise ReleaseError(f"工序 {k} 没有转速")
            if rpm > max_rpm + 1e-9:
                raise ReleaseError(f"工序 {k} 转速 {rpm:.0f} 超过机床最高转速 {max_rpm:g}")
            L.append(f"G97 S{round(rpm)} M3" if sie else f"G97 S{round(rpm)} M03")
        pos = {"x": hx, "z": hz}
        mode, last_f, first = None, None, True
        segs = {c["i0"]: c for c in op.get("cycles") or []} if use_cycles else {}
        moves = op["moves"]
        i = 0
        while i < len(moves):
            if i in segs and (segs[i]["type"] != "G70" or _blocks_key(segs[i]) in g71_blocks):
                seg = segs[i]
                if first:
                    L.append("M08")
                    first = False
                L += _cycle_lines(seg, g71_blocks, nblock)
                if seg["type"] == "G71":
                    nblock[0] += len(seg["blocks"]) + 10
                last = next(m for m in reversed(moves[seg["i0"]:seg["i1"]]) if m["t"] in ("rapid", "feed", "thread"))
                pos = {"x": last["x"], "z": last["z"]}
                mode, last_f = None, None
                i = seg["i1"]
                continue
            mv = moves[i]
            i += 1
            if mv["t"] not in ("rapid", "feed", "thread"):
                continue
            g = {"rapid": "G0" if sie else "G00", "feed": "G1" if sie else "G01", "thread": "G33" if sie else "G32"}[mv["t"]]
            ax = []
            for a in ("x", "z"):
                if abs(pos[a] - mv[a]) > 5e-4:
                    ax.append(a.upper() + num(mv[a]))
                    pos[a] = mv[a]
            if not ax:
                continue
            w = [g] if g != mode else []
            mode = g
            w += ax
            if mv["t"] == "thread":
                w.append(("K" if sie else "F") + num(mv["pitch"], 4))
                last_f = None
            elif mv["t"] == "feed" and mv.get("f") != last_f:
                w.append("F" + num(mv["f"], 3))
                last_f = mv["f"]
            if first:
                w.append("M8" if sie else "M08")
                first = False
            L.append(" ".join(w))
        L += [f"G0 X{num(hx)} Z{num(hz)} M9", "M5"] if sie else [f"G00 X{num(hx)} Z{num(hz)} M09", "M05"]
    L += ["M30"] if sie else ["M30", "%"]
    return "\n".join(x for x in L if x) + "\n"


def _blocks_key(seg):
    return tuple((round(x, 4), round(z, 4)) for x, z in seg["blocks"])


def _cycle_lines(seg, g71_blocks, nblock):
    """一段固定循环的程序行（FANUC / 广数写法）。G71 后面紧跟轮廓段 N ns ~ N nf，G70 引用同一组段号"""
    t = seg["type"]
    if t == "G71":
        ns = nblock[0]
        nf = ns + len(seg["blocks"]) - 1
        g71_blocks[_blocks_key(seg)] = (ns, nf)
        out = [f"G71 U{num(seg['d'])} R{num(seg['e'])}",
               f"G71 P{ns} Q{nf} U{num(seg['u'])} W{num(seg['w'])} F{num(seg['f'], 3)}"]
        x0, _z0 = seg["blocks"][0]
        out.append(f"N{ns} G00 X{num(x0)}")
        for j, (x, z) in enumerate(seg["blocks"][1:], 1):
            out.append(f"N{ns + j} G01 X{num(x)} Z{num(z)}" + (f" F{num(seg['f_fin'], 3)}" if j == 1 else ""))
        return out
    if t == "G70":
        ns, nf = g71_blocks[_blocks_key(seg)]
        return [f"G70 P{ns} Q{nf}"]
    # G76：P(m 精车次数)(r 倒角)(a 刀尖角 0 = 径向进刀) Q(最小切深 μm) R(精车余量)；X Z R(锥度 i) P(牙高 μm) Q(第一刀 μm) F(导程)
    second = f"G76 X{num(seg['x'])} Z{num(seg['z'])}" + (f" R{num(seg['i'])}" if abs(seg["i"]) > 5e-4 else "") + \
        f" P{int(seg['k_um'])} Q{int(seg['dd_um'])} F{num(seg['lead'], 4)}"
    return [f"G76 P{int(seg['m']):02d}0000 Q1 R0", second]


# ---------------------------------------------------------------- 铣
def _mill_moves(op):
    """钻孔展开成 G00 / G01（安全高度 → R 平面 → 逐次钻到底，每次退到 R → 回安全高度）"""
    out = []
    for mv in op["moves"]:
        if mv["t"] == "drill":
            safe = mv.get("safe", 5.0)
            x, y, r, zb = mv["x"], mv["y"], mv["r"], mv["z"]
            out += [{"t": "rapid", "x": x, "y": y, "z": safe}, {"t": "rapid", "x": x, "y": y, "z": r}]
            depth, first = r, True
            q = mv.get("q") or 0.0
            if q <= 0:                               # 一次钻到底（同 G81）：钻到底直接快退到安全高度
                out += [{"t": "feed", "x": x, "y": y, "z": zb, "f": mv["f"]}, {"t": "rapid", "x": x, "y": y, "z": safe}]
                continue
            while depth > zb + 1e-9:
                nd = max(depth - q, zb) if q > 0 else zb
                if not first:
                    out.append({"t": "rapid", "x": x, "y": y, "z": depth + 0.5})
                out += [{"t": "feed", "x": x, "y": y, "z": nd, "f": mv["f"]}, {"t": "rapid", "x": x, "y": y, "z": r}]
                depth, first = nd, False
            out.append({"t": "rapid", "x": x, "y": y, "z": safe})
        elif mv["t"] in ("rapid", "feed"):
            out.append(mv)
    return out


def _mill(prog, machine, sim_res, post, dialect):
    sie = dialect == "siemens"
    max_rpm = float(machine["max_rpm"])
    L: list[str] = []
    if sie:
        L.append(_semi(f"程序 {prog.get('number', 1)} {prog.get('title', '')}"))
        for en, cn, v in _header_items(prog, machine, sim_res, post):
            L.append(_semi(f"{cn}：{v}" if cn else (FIRST_PART_CN if v == FIRST_PART_EN else
                                                     "后处理未经实机验证" if v.startswith("POST NOT") else "示例机床，参数虚构")))
        L.append("G17 G90 G94 G40 G71")
    else:
        L += ["%", f"O{int(prog.get('number', 1)):04d} {_paren(prog.get('title_en') or 'WENQUEST CAM')}".rstrip()]
        for en, _cn, v in _header_items(prog, machine, sim_res, post):
            L.append(_paren(f"{en} {v}" if en else v))
        L.append("G21 G17 G40 G49 G80 G90 G94")
    for k, op in enumerate(prog["ops"], 1):
        t, sp = op["tool"], op["spindle"]
        safe = op.get("safe", 50.0)
        rpm = float(sp["rpm"])
        if rpm > max_rpm + 1e-9:
            raise ReleaseError(f"工序 {k} 转速 {rpm:.0f} 超过机床最高转速 {max_rpm:g}")
        mvs = _mill_moves(op)
        x0 = next((mv for mv in mvs if "x" in mv), {"x": 0.0, "y": 0.0})
        if sie:
            L += [_semi(f"工序 {k}：{op.get('title', '')}"), f"T{t['n']} M6", "D1", "G54", f"S{round(rpm)} M3",
                  f"G0 X{num(x0['x'])} Y{num(x0['y'])}", f"G0 Z{num(safe)} M8"]
        else:
            L += [_paren(f"OP{k} T{t['n']:02d}" + (f" D{num(t['d'])}" if t.get("d") else "")), f"T{t['n']} M06", "G54",
                  f"S{round(rpm)} M03", f"G00 X{num(x0['x'])} Y{num(x0['y'])}", f"G43 Z{num(safe)} H{t.get('offset', t['n']):02d} M08"]
        pos = {"x": x0["x"], "y": x0["y"], "z": safe}
        mode, last_f = None, None
        for mv in mvs:
            g = ("G0" if sie else "G00") if mv["t"] == "rapid" else ("G1" if sie else "G01")
            ax = []
            for a in ("x", "y", "z"):
                if a in mv and abs(pos[a] - mv[a]) > 5e-4:
                    ax.append(a.upper() + num(mv[a]))
                    pos[a] = mv[a]
            if not ax:
                continue
            w = [g] if g != mode else []
            mode = g
            w += ax
            if mv["t"] == "feed" and mv.get("f") != last_f:
                w.append("F" + num(mv["f"], 1))
                last_f = mv["f"]
            L.append(" ".join(w))
        L += [f"G0 Z{num(safe)} M9", "M5"] if sie else [f"G00 Z{num(safe)} M09", "M05"]
    L += ["G0 SUPA Z0 D0", "M30"] if sie else ["G91 G28 Z0.0", "G90", "M30", "%"]
    return "\n".join(x for x in L if x) + "\n"


POSTS = {
    "fanuc": {"name": "FANUC 0i-TF / 0i-MF", "lathe": True, "mill": True, "verified": False},
    "siemens": {"name": "SINUMERIK 828D / 840D sl", "lathe": True, "mill": True, "verified": False},
    "gsk": {"name": "GSK 980TDc / 980TDi", "lathe": True, "mill": False, "verified": False},
}


def available(kind: str) -> list[str]:
    return [k for k, v in POSTS.items() if v["lathe" if kind == "lathe" else "mill"]]


def render(prog: dict, machine: dict, controller: str, sim_res: dict | None) -> dict:
    """按数控系统写程序。machine 是旧字段视图（machines.get），带 model；sim_res 是 machine_sim.run 的结果"""
    post = POSTS.get(controller)
    kind = "lathe" if machine["kind"] == "lathe" else "mill"
    if post is None or not post[kind]:
        raise ReleaseError(f"没有 {controller!r} 的{'车床' if kind == 'lathe' else '铣床'}后处理；可选：{', '.join(available(kind))}")
    if not sim_res:
        raise ReleaseError("没有跑整机仿真，不输出程序（ADR-0104 安全底线第 1 条）")
    if sim_res.get("status") == "error":
        raise ReleaseError("整机仿真不通过，不输出程序（ADR-0104 安全底线第 1 条）")
    fn = _lathe if kind == "lathe" else _mill
    text = fn(prog, machine, sim_res, post, controller)
    return {"controller": controller, "post": post["name"], "version": VERSION, "verified": post["verified"],
            "fingerprint": sim_res["fingerprint"], "text": text}


# ---------------------------------------------------------------- 回读（验证用）
def to_fanuc(text: str, controller: str, lathe: bool) -> str:
    """把西门子的程序换回 FANUC 写法，交给 sim.parse 回读（验证后处理与中间格式一致）；FANUC、广数原样返回"""
    if controller in ("fanuc", "gsk"):
        return text
    out = ["%", "O0001"]
    lims = None
    for raw in text.splitlines():
        line = raw.split(";")[0].strip()
        if not line:
            continue
        if "SUPA" in line:                       # 回机床 Z 零点
            out += ["G91 G28 Z0.0", "G90"]
            continue
        conv = []
        for w in line.split():
            if w.startswith("LIMS="):
                lims = w[5:]
                continue
            if w in ("DIAMON", "G71") or (w.startswith("D") and w[1:].isdigit()):
                continue
            if w in ("G0", "G1", "G2", "G3"):
                w = "G0" + w[1]
            elif w == "G33":
                w = "G32"
            elif w.startswith("K"):
                w = "F" + w[1:]
            elif w.startswith("T") and w[1:].isdigit() and lathe:
                w = f"T{int(w[1:]):02d}{int(w[1:]):02d}"
            elif w in ("M3", "M5", "M6", "M8", "M9"):
                w = "M0" + w[1]
            conv.append(w)
        if lims and any(c == "G96" for c in conv):
            out.append(f"G50 S{lims}")
            lims = None
        if conv:
            out.append(" ".join(conv))
    out.append("%")
    return "\n".join(out) + "\n"
