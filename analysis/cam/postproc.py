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

import contextvars
import math
import re

from analysis.cam import klartext, postcfg
from analysis.cam.post import num as _num

# 按后处理配置的小数位、注释写法（ADR-0106 Q5a）：render 时设，写法函数里读
_FMT_DEFAULT = {"coord": 3, "feed": None, "utf8": False, "turn_cycles": True, "drill_cycles": False}
_FMT: contextvars.ContextVar = contextvars.ContextVar("fmt", default=None)


def _fmt() -> dict:
    return _FMT.get() or _FMT_DEFAULT


def num(v, nd=None):
    """坐标按配置的小数位（缺省 3）；明确给了位数的（螺距等）照给的"""
    return _num(v, _fmt()["coord"] if nd is None else nd)


def fnum(v, nd):
    """进给：配置给了进给小数位就用配置的，否则用写法里的缺省（车 3 位、铣 1 位）"""
    f = _fmt()["feed"]
    return _num(v, nd if f is None else f)

VERSION = "c1.1"
FIRST_PART_CN = "首件须空运行、单段试切确认"
FIRST_PART_EN = "FIRST PART: DRY RUN AND SINGLE BLOCK REQUIRED"


class ReleaseError(ValueError):
    """不满足安全底线，不输出程序"""


def _ascii(text: str) -> str:
    s = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in str(text))
    return " ".join(s.replace("(", "[").replace(")", "]").replace("%", " pct").split())


def _paren(text: str) -> str:
    if _fmt()["utf8"]:                       # 配置要中文注释（ISO 家族）：只去掉括号和 %
        t = " ".join(str(text).replace("(", "[").replace(")", "]").replace("（", "[").replace("）", "]").replace("%", " pct").split())
    else:
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
    use_cycles = bool(prog.get("cycles")) and dialect in ("fanuc", "gsk") and _fmt()["turn_cycles"]   # 西门子 CYCLE95 / 97 还没做
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
        if op.get("interp"):                        # 车铣的铣削工序（ADR-0106 C2b、ADR-0110）：开 / 关动力刀、C 轴的程序行按后处理配置
            if sie:
                raise ReleaseError("西门子的车铣（TRANSMIT / TRACYL）还没做（ADR-0106 C2b）；车铣程序先用 FANUC 写法的后处理")
            mt = _fmt().get("millturn")
            if not mt:
                raise ReleaseError("后处理配置没写动力刀、C 轴的 M 代码（millturn，按机床说明书填，ADR-0110），带铣削段的车铣程序不出")
            from analysis.cam import post as _post

            L += _post.millturn_lines(op, (hx, hz), mt, nd=_fmt()["coord"], fnd=_fmt()["feed"] if _fmt()["feed"] is not None else 1,
                                      cm=_paren)
            continue
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
                w.append("F" + fnum(mv["f"], 3))
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
               f"G71 P{ns} Q{nf} U{num(seg['u'])} W{num(seg['w'])} F{fnum(seg['f'], 3)}"]
        x0, _z0 = seg["blocks"][0]
        out.append(f"N{ns} G00 X{num(x0)}")
        for j, (x, z) in enumerate(seg["blocks"][1:], 1):
            out.append(f"N{ns + j} G01 X{num(x)} Z{num(z)}" + (f" F{fnum(seg['f_fin'], 3)}" if j == 1 else ""))
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
    """钻孔展开成 G00 / G01（安全高度 → R 平面 → 逐次钻到底，每次退到 R → 回安全高度）；配置要钻孔循环时原样留着（写 G81 / G83）"""
    out = []
    keep = _fmt()["drill_cycles"]
    for mv in op["moves"]:
        if mv["t"] == "drill" and keep:
            out.append(mv)
        elif mv["t"] == "drill":
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
        elif mv["t"] in ("rapid", "feed", "tap"):    # 攻丝不能拆成 G01（主轴要与进给同步），照样写攻丝指令
            out.append(mv)
    return out


def _tilt(op) -> list[str]:
    """倾斜面（ADR-0106 C2a）：FANUC 写法 G68.2 + G53.1，坐标位数按配置"""
    fr = op.get("frame")
    if not fr:
        return []
    from analysis.cam import tilt

    i, j, k = tilt.euler_zxz(tilt.matrix(fr))
    o = fr["origin"]
    # 转工作台前先把 Z 退到机床原点（刀具离开工件），再定倾斜面、转回转轴
    return ["G91 G28 Z0.0", "G90", f"G68.2 X{num(o[0])} Y{num(o[1])} Z{num(o[2])} I{num(i, 4)} J{num(j, 4)} K{num(k, 4)}", "G53.1"]


def _sie_tilt(op) -> list[str]:
    """西门子倾斜面（ADR-0106 C2a）：CYCLE800(_FR, _TC, _ST, _MODE, _X0, _Y0, _Z0, _A, _B, _C, _X1, _Y1, _Z1, _DIR, _FR_I, _DMODE)。
    _FR = 1 先退 Z；_TC = "" 用机床当前的回转数据组；_ST = 0 新平面；_MODE = 57 逐轴旋转、顺序 X、Y、Z（内旋）；
    _X0 _Y0 _Z0 平面原点；_DIR = −1 回转轴取较小的解。取消：CYCLE800()"""
    fr = op.get("frame")
    if not fr:
        return []
    from analysis.cam import tilt

    a, b, c = tilt.axis_xyz(tilt.matrix(fr))
    o = fr["origin"]
    return [f'CYCLE800(1,"",0,57,{num(o[0])},{num(o[1])},{num(o[2])},{num(a, 4)},{num(b, 4)},{num(c, 4)},0,0,0,-1,0,0)']


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
            L += [_semi(f"工序 {k}：{op.get('title', '')}"), f"T{t['n']} M6", "D1", "G54", f"S{round(rpm)} M3", *_sie_tilt(op),
                  f"G0 X{num(x0['x'])} Y{num(x0['y'])}", f"G0 Z{num(safe)} M8"]
        else:
            L += [_paren(f"OP{k} T{t['n']:02d}" + (f" D{num(t['d'])}" if t.get("d") else "")), f"T{t['n']} M06", "G54",
                  f"S{round(rpm)} M03", *_tilt(op), f"G00 X{num(x0['x'])} Y{num(x0['y'])}", f"G43 Z{num(safe)} H{t.get('offset', t['n']):02d} M08"]
        pos = {"x": x0["x"], "y": x0["y"], "z": safe}
        mode, last_f = None, None
        for mv in mvs:
            if mv["t"] == "drill":                    # 钻孔循环（配置打开，ISO 家族）：G98 回初始平面，一孔一段，G80 取消
                sf = mv.get("safe", 5.0)
                if abs(pos["z"] - sf) > 5e-4:
                    L.append(f"G00 Z{num(sf)}")
                q = mv.get("q") or 0.0
                w = ["G98", "G83" if q else "G81", f"X{num(mv['x'])}", f"Y{num(mv['y'])}", f"Z{num(mv['z'])}", f"R{num(mv['r'])}"]
                if q:
                    w.append(f"Q{num(q)}")
                L += [" ".join(w + [f"F{fnum(mv['f'], 1)}"]), "G80"]
                pos = {"x": mv["x"], "y": mv["y"], "z": sf}
                mode, last_f = None, None
                continue
            if mv["t"] == "tap":                      # 刚性攻丝：FANUC M29 + G84（F = 螺距 × 转速），西门子 G331 / G332（K = 螺距）
                sf = mv.get("safe", 5.0)
                x, y = mv["x"], mv["y"]
                if sie:
                    L += [f"G0 Z{num(sf)}" if abs(pos["z"] - sf) > 5e-4 else "", f"G0 X{num(x)} Y{num(y)}", f"G0 Z{num(mv['r'])}", "SPOS=0",
                          f"G331 Z{num(mv['z'])} K{num(mv['pitch'], 4)} S{round(rpm)}", f"G332 Z{num(mv['r'])} K{num(mv['pitch'], 4)}",
                          f"G0 Z{num(sf)}", f"S{round(rpm)} M3"]
                else:
                    L += [f"G00 Z{num(sf)}" if abs(pos["z"] - sf) > 5e-4 else "", f"M29 S{round(rpm)}",
                          f"G98 G84 X{num(x)} Y{num(y)} Z{num(mv['z'])} R{num(mv['r'])} F{fnum(mv['pitch'] * rpm, 1)}", "G80"]
                pos = {"x": x, "y": y, "z": sf}
                mode, last_f = None, None
                continue
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
                w.append("F" + fnum(mv["f"], 1))
                last_f = mv["f"]
            L.append(" ".join(w))
        L += [f"G0 Z{num(safe)} M9", "M5"] if sie else [f"G00 Z{num(safe)} M09", "M05"]
        if op.get("frame"):
            L.append("CYCLE800()" if sie else "G69")
    L += ["G0 SUPA Z0 D0", "M30"] if sie else ["G91 G28 Z0.0", "G90", "M30", "%"]
    return "\n".join(x for x in L if x) + "\n"


def _kl_comment(text: str) -> str:
    t = " ".join(str(text).split()) if _fmt()["utf8"] else " ".join(_ascii(text).split())
    return f"; {t}" if t else ""


def _kl_tilt(op) -> list[str]:
    """海德汉倾斜面（ADR-0106 C2a）：先沿刀轴退到行程尽头，零点平移到平面原点（CYCL DEF 7），再 PLANE SPATIAL（外旋 A、B、C）转回转轴"""
    fr = op.get("frame")
    if not fr:
        return []
    from analysis.cam import tilt

    a, b, c = tilt.spatial_abc(tilt.matrix(fr))
    o = fr["origin"]
    h = klartext.hnum
    return ["M140 MB MAX", "CYCL DEF 7.0 DATUM SHIFT", f"CYCL DEF 7.1 X{h(num(o[0]))}", f"CYCL DEF 7.2 Y{h(num(o[1]))}",
            f"CYCL DEF 7.3 Z{h(num(o[2]))}", f"PLANE SPATIAL SPA{h(num(a, 4))} SPB{h(num(b, 4))} SPC{h(num(c, 4))} TURN MB MAX FMAX"]


def _heidenhain_mill(prog, machine, sim_res, post):
    """海德汉 TNC 对话格式（ADR-0106 Q5b）→ (程序头注释, 程序段)；段号、BEGIN / END PGM、配置开关由 klartext.finish 加"""
    max_rpm = float(machine["max_rpm"])
    h = klartext.hnum
    head = [_kl_comment(f"WENQUEST CAM {prog.get('title_en') or ''}")]
    for en, _cn, v in _header_items(prog, machine, sim_res, post):
        head.append(_kl_comment(f"{en} {v}" if en else v))
    body: list[str] = []
    for k, op in enumerate(prog["ops"], 1):
        t, sp = op["tool"], op["spindle"]
        safe = op.get("safe", 50.0)
        rpm = float(sp["rpm"])
        if rpm > max_rpm + 1e-9:
            raise ReleaseError(f"工序 {k} 转速 {rpm:.0f} 超过机床最高转速 {max_rpm:g}")
        mvs = _mill_moves(op)
        x0 = next((mv for mv in mvs if "x" in mv), {"x": 0.0, "y": 0.0})
        body += [_kl_comment(f"OP{k} T{t['n']:02d}" + (f" D{num(t['d'])}" if t.get("d") else "")), f"TOOL CALL {t['n']} Z S{round(rpm)}",
                 *_kl_tilt(op), f"L X{h(num(x0['x']))} Y{h(num(x0['y']))} R0 FMAX M3", f"L Z{h(num(safe))} R0 FMAX M8"]
        pos = {"x": x0["x"], "y": x0["y"], "z": safe}
        last_f, last_def = None, None
        for mv in mvs:
            if mv["t"] in ("drill", "tap"):           # CYCL DEF 200 / 207：表面 = R 平面 − 2，第二安全距离回到安全高度
                sf = mv.get("safe", 5.0)
                if sf < mv["r"] - 1e-9:
                    raise ReleaseError(f"工序 {k}：安全高度 Z{sf:g} 低于 R 平面 Z{mv['r']:g}")
                if abs(pos["z"] - sf) > 5e-4:
                    body.append(f"L Z{h(num(sf))} R0 FMAX")
                top = mv["r"] - 2.0
                if mv["t"] == "drill":
                    depth = top - mv["z"]
                    q = mv.get("q") or 0.0
                    qs = [("200", 2.0, "SET-UP CLEARANCE"), ("201", mv["z"] - top, "DEPTH"), ("206", mv["f"], "FEED RATE FOR PLNGNG"),
                          ("202", q if q > 0 else depth, "PLUNGING DEPTH"), ("210", 0.0, "DWELL TIME AT TOP"),
                          ("203", top, "SURFACE COORDINATE"), ("204", sf - top, "2ND SET-UP CLEARANCE"), ("211", 0.0, "DWELL TIME AT DEPTH")]
                    title = "200 DRILLING"
                else:
                    qs = [("200", 2.0, "SET-UP CLEARANCE"), ("201", mv["z"] - top, "DEPTH OF THREAD"), ("239", mv["pitch"], "THREAD PITCH"),
                          ("203", top, "SURFACE COORDINATE"), ("204", sf - top, "2ND SET-UP CLEARANCE")]
                    title = "207 RIGID TAPPING"
                vals = tuple((n, num(v) if n != "206" else fnum(v, 1)) for n, v, _d in qs)
                if (title, vals) != last_def:
                    body.append(f"CYCL DEF {title} ~")
                    for j, ((n, v), (_n, _v, d)) in enumerate(zip(vals, qs, strict=True)):
                        body.append(f"  Q{n}={h(v)} ;{d}" + (" ~" if j < len(qs) - 1 else ""))
                    last_def = (title, vals)
                body.append(f"L X{h(num(mv['x']))} Y{h(num(mv['y']))} R0 FMAX M99")
                pos = {"x": mv["x"], "y": mv["y"], "z": sf}
                last_f = None
                continue
            ax = []
            for a in ("x", "y", "z"):
                if a in mv and abs(pos[a] - mv[a]) > 5e-4:
                    ax.append(a.upper() + h(num(mv[a])))
                    pos[a] = mv[a]
            if not ax:
                continue
            if mv["t"] == "rapid":
                body.append(f"L {' '.join(ax)} R0 FMAX")
            else:
                fw = ""
                if mv.get("f") != last_f:
                    fw = " F" + fnum(mv["f"], 1)
                    last_f = mv["f"]
                body.append(f"L {' '.join(ax)} R0{fw}")
        body += [f"L Z{h(num(safe))} R0 FMAX M9", "M5"]
        if op.get("frame"):                        # 取消倾斜面与零点平移（回转轴留在原处：STAY）
            body += ["PLANE RESET STAY", "CYCL DEF 7.0 DATUM SHIFT", "CYCL DEF 7.1 X+0", "CYCL DEF 7.2 Y+0", "CYCL DEF 7.3 Z+0"]
    body += ["M140 MB MAX", "M30"]
    return [x for x in head if x], [x for x in body if x]


def posts() -> dict:
    """可选的后处理：{id: {"name", "lathe", "mill", "verified", "family", "cfg"}}（内置配置 + 用户配置，ADR-0109）"""
    out = {}
    for k, c in postcfg.configs().items():
        out[k] = {"name": c["name"], "lathe": "lathe" in c["kinds"], "mill": "mill" in c["kinds"], "verified": bool(c.get("verified")),
                  "family": c["family"], "cfg": c}
    return out


POSTS = {k: {kk: vv for kk, vv in v.items() if kk != "cfg"} for k, v in posts().items()}   # 内置的（兼容以前的调用）


def available(kind: str) -> list[str]:
    return [k for k, v in posts().items() if v["lathe" if kind == "lathe" else "mill"]]


def render(prog: dict, machine: dict, controller: str, sim_res: dict | None) -> dict:
    """按后处理配置写程序。machine 是旧字段视图（machines.get），带 model；sim_res 是 machine_sim.run 的结果"""
    try:
        post = posts().get(controller)
    except postcfg.PostConfigError as exc:
        raise ReleaseError(str(exc)) from exc
    kind = "lathe" if machine["kind"] in ("lathe", "mill_turn") else "mill"
    if post is None or not post[kind]:
        raise ReleaseError(f"没有 {controller!r} 的{'车床' if kind == 'lathe' else '铣床'}后处理；可选：{', '.join(available(kind))}")
    if not sim_res:
        raise ReleaseError("没有跑整机仿真，不输出程序（ADR-0104 安全底线第 1 条）")
    if sim_res.get("status") == "error":
        raise ReleaseError("整机仿真不通过，不输出程序（ADR-0104 安全底线第 1 条）")
    cfg = postcfg.resolved(post["cfg"])
    fam = cfg["family"]
    dialect = "fanuc" if fam == "hnc" else fam                  # 华中按 FANUC 写法，程序头另改
    tok = _FMT.set({"coord": cfg["decimals"]["coord"], "feed": cfg["decimals"]["feed"],
                    "utf8": cfg["comments"] == "utf8" and fam != "siemens",
                    "turn_cycles": cfg["cycles"]["turn"], "drill_cycles": cfg["cycles"]["drill"] and fam != "siemens",
                    "millturn": cfg.get("millturn")})
    try:
        if fam == "heidenhain":
            text = klartext.finish(*_heidenhain_mill(prog, machine, sim_res, post), cfg, int(prog.get("number", 1)))
            return {"controller": controller, "post": post["name"], "version": VERSION, "verified": post["verified"],
                    "fingerprint": sim_res["fingerprint"], "text": text}
        fn = _lathe if kind == "lathe" else _mill
        text = fn(prog, machine, sim_res, post, dialect)
        text = postcfg.finish(text, cfg, kind == "lathe", int(prog.get("number", 1)))
    except (postcfg.PostConfigError, klartext.KlartextError) as exc:
        raise ReleaseError(str(exc)) from exc
    finally:
        _FMT.reset(tok)
    return {"controller": controller, "post": post["name"], "version": VERSION, "verified": post["verified"],
            "fingerprint": sim_res["fingerprint"], "text": text}


# ---------------------------------------------------------------- 回读（验证用）
def tag(i: int) -> str:
    """回读后的程序行末尾记原程序的行号（括号注释，sim.parse 不读），程序对比用它找回原来的行"""
    return f"(#L{i})"


def to_fanuc(text: str, controller: str, lathe: bool, *, tags: bool = False) -> str:
    """把程序换回 FANUC 写法，交给 sim.parse 回读（验证后处理与中间格式一致）：先按配置还原（子程序展开、华中程序头），
    西门子再换写法；ISO 家族其余原样。tags：每行末尾记原程序行号（tag）"""
    post = posts().get(controller)
    fam = post["family"] if post else controller
    if fam == "heidenhain":
        try:
            return klartext.to_iso(text, tags=tags)
        except klartext.KlartextError as exc:
            raise ReleaseError(f"海德汉程序回读不了：{exc}") from exc
    if tags and fam in postcfg.ISO:
        text = "\n".join(f"{ln} {tag(i)}" if ln.strip() else ln for i, ln in enumerate(text.split("\n"), 1))
    if post:
        text = postcfg.expand(text, postcfg.resolved(post["cfg"]))
    elif fam in postcfg.ISO:
        text = postcfg.expand(text, postcfg.resolved({"family": fam}))
    if fam in postcfg.ISO:
        return text
    out = ["%", "O0001"]
    lims = None
    spd = 0.0
    mark, prev = len(out), 0
    for i, raw in enumerate(text.splitlines(), 1):
        if tags:
            out[mark:] = [f"{x} {tag(prev)}" for x in out[mark:]]
            mark, prev = len(out), i
        line = raw.split(";")[0].strip()
        if not line or line.startswith("SPOS"):
            continue
        ws = line.split()
        spd = next((float(w[1:]) for w in ws if w.startswith("S") and w[1:].replace(".", "").isdigit()), spd)
        if ws[0] in ("G331", "G332"):             # 西门子刚性攻丝 → 进给直线（回读只比路径；进给 = 螺距 × 转速）
            kk = next(float(w[1:]) for w in ws if w.startswith("K"))
            out.append(" ".join(["G01"] + [w for w in ws[1:] if w[0] in "XYZ"] + [f"F{kk * spd:g}"]))
            continue
        if line.startswith("CYCLE800("):         # 倾斜面：退 Z、平面原点 + 逐轴 X-Y-Z 角 → G68.2（Z-X-Z 欧拉角）+ G53.1；空参数是取消
            args = [x.strip() for x in line[len("CYCLE800("):-1].split(",")] if line.endswith(")") else []
            if not args or args == [""]:
                out.append("G69")
                continue
            from analysis.cam import tilt

            v = [float(x) if re.fullmatch(r"[-+]?\d+(?:\.\d*)?", x) else None for x in args]
            if args[3] != "57" or any(v[i] is None for i in (4, 5, 6, 7, 8, 9)):
                raise ReleaseError(f"CYCLE800 回读只认 _MODE = 57：{line}")
            i, j, k = tilt.euler_zxz(tilt.from_axis_xyz(v[7], v[8], v[9]))
            if args[0] == "1":
                out += ["G91 G28 Z0.0", "G90"]
            out += [f"G68.2 X{v[4]:g} Y{v[5]:g} Z{v[6]:g} I{i:.9f} J{j:.9f} K{k:.9f}", "G53.1"]
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
    if tags:
        out[mark:] = [f"{x} {tag(prev)}" for x in out[mark:]]
    out.append("%")
    return "\n".join(out) + "\n"
