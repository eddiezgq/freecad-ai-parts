"""发格（Fagor）8060 / 8065 的基本写法（ADR-0126，ADR-0106 E3）：问渠CAM 先按 FANUC 写法写好，再按固定对照表逐行换成发格写法；
回读时按同一张表换回 FANUC 写法，交给 sim.parse 与仿真比。换不回来的写法一律报错。

依据：《CNCelite 8058/8060/8065/8070 Programming manual》（发格官网资料门户，man_elite_58_60_65_70_prg.pdf；下面的 § 是这本手册的章节）。

- `to_fagor(text, lathe)`：FANUC 写法 → 发格写法（`postproc.render` 里 `postcfg.finish` 之后）。
- `to_fanuc(text, lathe)`：发格写法 → FANUC 写法（回读前；行尾的 `(#Ln)` 行号标记跟着走）。
- `check_codes(text, lathe, extra_m)`：发格程序里每个 G、M 代码都要在手册 §1.5、§1.6 的表里且是本表用到的，否则不出；
  坐标最多 4 位小数（§1.3.1，毫米 ±5.4）。

车铣（ADR-0129）：FANUC `G12.1` … `G13.1` ↔ `G152` `#CAX` `#FACE [X,C,Q0]` … `#FACE OFF` `#CAX OFF` `G151`（X 半径、C mm）；
`G07.1 C半径` … `G07.1 C0` ↔ `G152` `#CAX` `#CYL [Z,C,X半径,Q0]` … `#CYL OFF` `#CAX OFF` `G151`（X 半径、C = 角度 × π ÷ 180 × 半径）。
"""

from __future__ import annotations

import math
import re

# 手册 §1.5（G）、§1.6（M）里有、问渠CAM 会写的代码：代码 → 章节
CODES_G = {"0": "8.1", "1": "8.2", "2": "8.3", "3": "8.3", "17": "4.2", "18": "4.2", "33": "10.1", "40": "13.1", "54": "5.5",
           "63": "10.3", "71": "3.1", "80": "1.5", "90": "3.2", "94": "6.2", "95": "6.2", "96": "7.2.2", "97": "7.2.2", "151": "3.4", "152": "3.4",
           "192": "7.2.1"}
CODES_M = {"0": "14.2", "1": "14.3", "2": "1.2.1", "3": "7.3", "4": "7.3", "5": "7.3", "6": "6.14", "19": "7.5", "30": "1.2.1"}
MANUAL = "CNCelite 8058/8060/8065/8070 Programming manual"


class FagorError(ValueError):
    pass


_TAG = re.compile(r"\s*\(#L\d+\)$")


def _split(line: str):
    """→ (顺序号前缀, 程序段, 行尾行号标记)"""
    s = line.strip()
    mt = _TAG.search(s)
    tail = mt.group(0) if mt else ""
    s = s[: len(s) - len(tail)]
    m = re.match(r"^(N\d+\s+)(.*)$", s)
    return (m.group(1), m.group(2), tail) if m else ("", s, tail)


def _z(body: str):
    m = re.search(r"\bZ(-?\d+(?:\.\d*)?)", re.sub(r"\([^)]*\)", "", body))
    return m.group(1) if m else None


def _sub(tokens: list, old: str, new: str | None) -> list:
    out = []
    for t in tokens:
        if t == old:
            if new:
                out.append(new)
        else:
            out.append(t)
    return out


_NUM = r"-?\d+(?:\.\d*)?"
_ON = {"polar": "#FACE [X,C,Q0]"}
_OFF = {"polar": "#FACE OFF", "cyl": "#CYL OFF"}


def _f4(v: float) -> str:
    """发格毫米坐标：4 位小数（§1.3.1）"""
    s = f"{v:.4f}".rstrip("0")
    s = s + "0" if s.endswith(".") else s
    return "0.0" if s == "-0.0" else s


def _mt_line(body: str, trafo: list, to_fg: bool) -> str:
    """车铣块里的一段：FANUC（X 直径、C）↔ 发格（X 半径、C mm）；只换 G00 / G01、X、Z、C、F"""
    tok = body.split()
    if any(not (t in ("G00", "G01") or (t[:1] in "XZCF" and re.fullmatch(_NUM, t[1:]))) for t in tok):
        raise FagorError(f"发格车铣块里只换 G00 / G01、X、Z、C、F：{body}")
    out = []
    for t in tok:
        if t[0] == "X":
            v = float(t[1:])
            t = f"X{_f4(v / 2)}" if to_fg else f"X{_f4(v * 2)}"
        elif t[0] == "C" and trafo[0] == "cyl":                  # §18.1.5：C 按 mm（给定半径上的展开长度）
            v, r = float(t[1:]), trafo[1]
            t = f"C{_f4(math.radians(v) * r)}" if to_fg else f"C{_f4(math.degrees(v / r))}"
        out.append(t)
    return " ".join(out)


def to_fagor(text: str, lathe: bool) -> str:
    lines = text.rstrip("\n").split("\n")
    out, i, head_done, gline_done, tool, want_h, z_now = [], 0, False, False, None, False, None
    trafo = None                                                # 车铣块（ADR-0129）
    while i < len(lines):
        pre, body, tail = _split(lines[i])
        if lathe and body and not body.startswith("("):
            m7 = re.fullmatch(rf"G07\.1 C({_NUM})", body)
            handled = True
            if body == "G12.1":                                # §3.4 G152、§18.1.1 #CAX、§18.1.3 #FACE
                trafo = ["polar"]
                out += [f"{pre}G152{tail}", f"#CAX{tail}", f"{_ON['polar']}{tail}"]
            elif m7 and float(m7.group(1)) != 0:               # §18.1.5 #CYL [Z,C,X半径,Q0]
                trafo = ["cyl", float(m7.group(1))]
                out += [f"{pre}G152{tail}", f"#CAX{tail}", f"#CYL [Z,C,X{m7.group(1)},Q0]{tail}"]
            elif trafo and (body == "G13.1" or (m7 and float(m7.group(1)) == 0)):
                out += [f"{pre}{_OFF[trafo[0]]}{tail}", f"#CAX OFF{tail}", f"G151{tail}"]
                trafo = None
            elif trafo:
                out.append(pre + _mt_line(body, trafo, True) + tail)
            else:
                handled = False
            if handled:
                i += 1
                continue
        if body == "%":
            i += 1
            continue
        m = re.match(r"^O(\d+)\s*(.*)$", body)
        if m and not head_done:                                  # §1.2.1：% 加程序名；原来的注释另起一行
            out.append(f"%{m.group(1)}")
            if m.group(2):
                out.append(m.group(2))
            head_done = True
            i += 1
            continue
        if not body or (body.startswith("(") and body.endswith(")")):
            out.append(lines[i])
            i += 1
            continue
        tok = body.split()
        if not gline_done and tok[0] == "G21":                  # 第一行模态：公制 G71（§3.1），车床直径编程 G151（§3.4）
            tok = _sub(tok, "G21", "G71")
            tok = _sub(tok, "G49", None)
            if lathe:
                tok = _sub(_sub(tok, "G99", "G95"), "G98", "G94")
                k = tok.index("G18") + 1 if "G18" in tok else 1
                tok = tok[:k] + ["G151"] + tok[k:]
            out.append(pre + " ".join(tok))
            gline_done = True
            i += 1
            continue
        # 铣：刚性攻丝 M29 S / G98 G84 / G80 → G63 攻进、反转退出（§10.3）
        mt = re.fullmatch(r"M29 S(\d+)", body)
        if mt and not lathe:
            nxt = [_split(lines[i + k]) if i + k < len(lines) else ("", "", "") for k in (1, 2)]
            m84 = re.fullmatch(r"G98 G84 X(\S+) Y(\S+) Z(\S+) R(\S+) F(\S+)", nxt[0][1])
            if not m84 or nxt[1][1] != "G80" or z_now is None:
                raise FagorError(f"发格攻丝只认 M29 S / G98 G84 X Y Z R F / G80 这一组：{body}")
            s = mt.group(1)
            x, y, z, r, f = m84.groups()
            out += [f"{pre}G00 X{x} Y{y}{tail}", f"G00 Z{r}{tail}", f"{nxt[0][0]}G63 Z{z} F{f} S{s}{nxt[0][2]}",
                    f"G63 Z{r} S-{s}{nxt[0][2]}", f"{nxt[1][0]}G00 Z{z_now}{nxt[1][2]}", f"S{s} M03{nxt[1][2]}"]
            i += 3
            continue
        if body == "G91 G28 Z0.0":                              # 回机床 Z 零点（§5.1；与西门子 G0 SUPA Z0 同一约定）
            out.append(f"{pre}#MCS Z0{tail}")
            i += 1
            continue
        if lathe:
            mt = re.fullmatch(r"T(\d{2})(\d{2})", body)
            if mt:                                              # §6.13、§6.15：T 选刀、D 选这把刀的刀补；转塔换刀不写 M06
                if mt.group(1) != mt.group(2):
                    raise FagorError(f"发格的刀补号是每把刀自己的 D1 ~ D8，{body} 的刀补号与刀号不同，换不了")
                body = f"T{int(mt.group(1))} D1"
            body = re.sub(r"^G50 S(\d+)$", r"G192 S\1", body)  # §7.2.1
            tok = _sub(_sub(body.split(), "G99", "G95"), "G98", "G94")
            if "G32" in tok:                                    # §10.1：G33 终点 K 螺距
                if not any(t.startswith("F") for t in tok):
                    raise FagorError(f"车螺纹这一段没有螺距：{body}")
                tok = ["G33" if t == "G32" else ("K" + t[1:] if t.startswith("F") else t) for t in tok]
            body = " ".join(tok)
        else:
            mt = re.fullmatch(r"T(\d+) M06", body)
            if mt:                                              # §6.13 例 T7 D1 M6
                tool, want_h = int(mt.group(1)), True
                body = f"T{tool} D1 M6"
            elif want_h and _z(body) is not None:               # 换刀后第一次 Z 移动：FANUC 的 G43 … H 在这里；发格由 D1 生效（§13.2）
                tok = body.split()
                hs = [t for t in tok if re.fullmatch(r"H\d+", t)]
                if "G43" not in tok or len(hs) != 1 or int(hs[0][1:]) != tool:
                    raise FagorError(f"发格的长度补偿随 D1 生效，换刀后第一次 Z 移动要是 G43 … H{tool:02d}：{body}")
                body = " ".join(t for t in tok if t not in ("G43", hs[0]))
                want_h = False
        z = _z(body)
        if z is not None:
            z_now = z
        out.append(pre + body + tail)
        i += 1
    return "\n".join(out) + "\n"


def to_fanuc(text: str, lathe: bool) -> str:
    """回读前：发格写法 → FANUC 写法（to_fagor 的逆）"""
    lines = text.rstrip("\n").split("\n")
    out, i, gline_done, want_h = [], 0, False, None
    trafo = None
    while i < len(lines):
        pre, body, tail = _split(lines[i])
        if lathe and gline_done and body == "G152" and i + 2 < len(lines):
            b1, b2 = _split(lines[i + 1])[1], _split(lines[i + 2])[1]
            mc = re.fullmatch(rf"#CYL \[Z,C,X({_NUM}),Q0\]", b2)
            if b1 == "#CAX" and (b2 == _ON["polar"] or mc):
                trafo = ["cyl", float(mc.group(1))] if mc else ["polar"]
                out.append(pre + (f"G07.1 C{mc.group(1)}" if mc else "G12.1") + tail)
                i += 3
                continue
        if trafo and body == _OFF[trafo[0]] and i + 2 < len(lines):
            if _split(lines[i + 1])[1] != "#CAX OFF" or _split(lines[i + 2])[1] != "G151":
                raise FagorError(f"发格车铣块的结尾要是 {body} / #CAX OFF / G151")
            out.append(pre + ("G13.1" if trafo[0] == "polar" else "G07.1 C0") + tail)
            trafo = None
            i += 3
            continue
        if trafo and body and not body.startswith("("):
            out.append(pre + _mt_line(body, trafo, False) + tail)
            i += 1
            continue
        m = re.fullmatch(r"%(\d+)", body)
        if m and not out:
            nb = _split(lines[i + 1])[1] if i + 1 < len(lines) else ""
            if nb.startswith("(") and nb.endswith(")"):
                out.append(f"O{m.group(1)} {nb}{tail}")
                i += 2
            else:
                out.append(f"O{m.group(1)}{tail}")
                i += 1
            continue
        if not body or (body.startswith("(") and body.endswith(")")):
            out.append(lines[i])
            i += 1
            continue
        tok = body.split()
        if not gline_done and tok[0] == "G71":
            tok = _sub(_sub(tok, "G71", "G21"), "G151", None)
            if lathe:
                tok = _sub(_sub(tok, "G95", "G99"), "G94", "G98")
            elif "G40" in tok:
                k = tok.index("G40") + 1
                tok = tok[:k] + ["G49"] + tok[k:]
            out.append(pre + " ".join(tok) + tail)
            gline_done = True
            i += 1
            continue
        mx = re.fullmatch(r"G00 X(\S+) Y(\S+)", body)
        if mx and not lathe and i + 5 < len(lines):
            b = [_split(lines[i + k]) for k in range(1, 6)]
            m1 = re.fullmatch(r"G00 Z(\S+)", b[0][1])
            m2 = re.fullmatch(r"G63 Z(\S+) F(\S+) S(\d+)", b[1][1])
            m3 = re.fullmatch(r"G63 Z(\S+) S-(\d+)", b[2][1])
            m4 = re.fullmatch(r"G00 Z(\S+)", b[3][1])
            m5 = re.fullmatch(r"S(\d+) M03", b[4][1])
            if m1 and m2 and m3 and m4 and m5:
                r, (z, f, s) = m1.group(1), m2.groups()
                if m3.group(1) != r or m3.group(2) != s or m5.group(1) != s:
                    raise FagorError(f"发格攻丝这一组前后对不上（R、转速）：{body}")
                x, y = mx.groups()
                out += [f"{pre}M29 S{s}{tail}", f"{b[1][0]}G98 G84 X{x} Y{y} Z{z} R{r} F{f}{b[1][2]}", f"{b[3][0]}G80{b[3][2]}"]
                i += 6
                continue
        if body == "#MCS Z0":
            out.append(f"{pre}G91 G28 Z0.0{tail}")
            i += 1
            continue
        if lathe:
            mt = re.fullmatch(r"T(\d+) D1", body)
            if mt:
                n = int(mt.group(1))
                body = f"T{n:02d}{n:02d}"
            body = re.sub(r"^G192 S(\d+)$", r"G50 S\1", body)
            tok = _sub(_sub(body.split(), "G95", "G99"), "G94", "G98")
            if "G33" in tok:
                tok = ["G32" if t == "G33" else ("F" + t[1:] if t.startswith("K") else t) for t in tok]
            body = " ".join(tok)
        else:
            mt = re.fullmatch(r"T(\d+) D1 M6", body)
            if mt:
                want_h = int(mt.group(1))
                body = f"T{want_h} M06"
            elif want_h is not None and _z(body) is not None:
                tok = body.split()
                k = next(j for j, t in enumerate(tok) if t.startswith("Z"))
                tok = ["G43"] + tok[: k + 1] + [f"H{want_h:02d}"] + tok[k + 1:]
                body = " ".join(tok)
                want_h = None
        left = re.search(r"#|\bG15[12]\b|\bG192\b|\bG63\b|\bD\d", body)
        if left:
            raise FagorError(f"发格程序这一行换不回 FANUC 写法：{body}")
        out.append(pre + body + tail)
        i += 1
    return "\n".join(out) + "\n"


def check_codes(text: str, lathe: bool, extra_m=()) -> None:
    """发格程序里的 G、M 代码都要在手册表里（CODES_G、CODES_M；配置换刀前后动作里的 M 代码也认），否则不出"""
    body = "\n".join(re.sub(r"\([^)]*\)", "", ln) for ln in text.split("\n"))
    def norm(c: str) -> str:
        a, _, b = c.partition(".")
        return str(int(a)) + (f".{b}" if b else "")

    have_m = set(CODES_M) | {norm(m) for m in extra_m}
    bad_g = sorted({norm(g) for g in re.findall(r"\bG(\d+(?:\.\d)?)", body)
                    if norm(g) not in CODES_G or (lathe and norm(g) in ("2", "3"))}, key=float)
    bad_m = sorted({norm(m) for m in re.findall(r"\bM(\d+)", body)} - have_m, key=float)
    if bad_g or bad_m:
        miss = "、".join([f"G{g}" for g in bad_g] + [f"M{m}" for m in bad_m])
        mt = (" 发格的 C 分度 + Y 轴铣还没做（ADR-0129）。" if "19" in bad_g else
              " 发格车铣只按 ADR-0129 换端面、圆柱面。" if any(g in ("12.1", "13.1", "7.1") for g in bad_g) else "")
        raise FagorError(f"发格程序里有手册代码表外（或还没按手册做）的 {miss}，程序不出。{mt}")
    sharp = sorted({ln.strip() for ln in body.split("\n") if ln.strip().startswith("#")} - {"#CAX", "#CAX OFF", _ON["polar"], *_OFF.values()}
                   - {ln.strip() for ln in body.split("\n") if re.fullmatch(rf"#CYL \[Z,C,X{_NUM},Q0\]|#MCS Z0", ln.strip())})
    if sharp:
        raise FagorError(f"发格程序里有本表没收的 # 指令 {'、'.join(sharp[:3])}，程序不出（ADR-0129）")
    long_ = sorted({w for w in re.findall(r"\b([XYZCIJKR]-?\d+\.\d{5,})", body)})
    if long_:
        raise FagorError(f"发格毫米坐标最多 4 位小数（§1.3.1），{'、'.join(long_[:5])} 超了，程序不出")
