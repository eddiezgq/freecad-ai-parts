"""NUM Flexium / Flexium+ 的基本写法（ADR-0127，ADR-0106 E3）：问渠CAM 先按 FANUC 写法写好，再按固定对照表逐行换成 NUM 写法；
回读时按同一张表换回 FANUC 写法，交给 sim.parse 与仿真比。换不回来的写法一律报错。

依据：NUM 官网《Flexium Programming Manual》M00018EN-03（num.com/fileadmin/documents/Manuals/Flexium/
M00018EN-03_Flexium_Programming_manual.pdf；下面的 § 是这本手册的章节）。

- `to_num(text, lathe)`：FANUC 写法 → NUM 写法（`postproc.render` 里 `postcfg.finish` 之后）。
- `to_fanuc(text, lathe)`：NUM 写法 → FANUC 写法（回读前；行尾的 `(#Ln)` 行号标记跟着走）。
- `check_codes(text, lathe, extra_m)`：NUM 程序里每个 G、M 代码都要在手册 §5.1.1、§5.1.2 的表里且是本表用到的，否则不出。
"""

from __future__ import annotations

import math
import re

# 手册 §5.1.1（G）、§5.1.2（M）里有、问渠CAM 会写的代码：代码 → 章节
CODES_G = {"0": "5.6", "1": "5.7.1", "17": "5.4", "18": "5.4", "38": "5.13.2", "40": "5.11.4", "52": "5.16", "54": "5.16",
           "71": "5.1.1", "80": "5.12.2", "84": "5.12.7", "90": "5.3", "92": "5.5.4", "94": "5.10", "95": "5.10", "96": "5.5.3",
           "97": "5.5.2"}
CODES_M = {"0": "5.1.2", "1": "5.1.2", "2": "3.3.1", "3": "5.5.1", "4": "5.5.1", "5": "5.5.1", "6": "5.11.1", "7": "5.1.2",
           "8": "5.1.2", "9": "5.1.2", "19": "5.5.6"}
MANUAL = "NUM Flexium Programming Manual M00018EN-03"
LATHE_NOTE = "(NUM: X IN DIAMETER, MANUAL 5.2.1)"


class NumError(ValueError):
    pass


_TAG = re.compile(r"\s*\(#L\d+\)$")
_NUM = r"-?\d+(?:\.\d*)?"


def _split(line: str):
    """→ (顺序号前缀, 程序段, 行尾行号标记)"""
    s = line.strip()
    mt = _TAG.search(s)
    tail = mt.group(0) if mt else ""
    s = s[: len(s) - len(tail)]
    m = re.match(r"^(N\d+\s+)(.*)$", s)
    return (m.group(1), m.group(2), tail) if m else ("", s, tail)


def _word(body: str, a: str):
    m = re.search(rf"\b{a}({_NUM})", re.sub(r"\([^)]*\)", "", body))
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


def _is_comment(body: str) -> bool:
    return not body or (body.startswith("(") and body.endswith(")"))


def css_rpm(v: float, d: float, limit: float | None) -> int:
    """恒线速 v（m/min）在直径 d（mm）上的转速，受 G92 限速"""
    if d <= 0:
        raise NumError(f"恒线速要一个大于 0 的当前直径（§5.5.3），这里是 X{d:g}")
    n = v * 1000.0 / (math.pi * d)
    return round(min(n, limit) if limit else n)


def _fmt(v: float) -> str:
    s = f"{v:.6f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def to_num(text: str, lathe: bool) -> str:
    lines = text.rstrip("\n").split("\n")
    out, i, head_done, gline_done, tool, want_h, z_now, limit = [], 0, False, False, None, False, None, None
    while i < len(lines):
        pre, body, tail = _split(lines[i])
        if body == "%":
            i += 1
            continue
        m = re.match(r"^O(\d+)\s*(.*)$", body)
        if m and not head_done:                                  # §3.3.3：% 加程序号，注释同一行；9000 以上留给 NUM / 机床厂
            if int(m.group(1)) >= 9000:
                raise NumError(f"NUM 的 %9000 以上程序号可能被 NUM 或机床厂占用（§3.3.3），程序号 {m.group(1)} 不能用")
            out.append(f"%{int(m.group(1))}" + (f" {m.group(2)}" if m.group(2) else ""))
            if lathe:
                out.append(LATHE_NOTE)
            head_done = True
            i += 1
            continue
        if _is_comment(body):
            out.append(lines[i])
            i += 1
            continue
        tok = body.split()
        if not gline_done and tok[0] == "G21":                  # 第一行模态：公制 G71（NUM 的 G21 是直角坐标）；G49 在 NUM 是删样条
            tok = _sub(_sub(tok, "G21", "G71"), "G49", None)
            if lathe:
                tok = _sub(_sub(tok, "G99", "G95"), "G98", "G94")
            out.append(pre + " ".join(tok) + tail)
            gline_done = True
            i += 1
            continue
        # 铣：刚性攻丝 M29 S / G98 G84 / G80 → G00 到孔上、G00 到 R、S G84 Z K、G80、G00 回初始平面（§5.12.1、§5.12.7）
        mt = re.fullmatch(r"M29 S(\d+)", body)
        if mt and not lathe:
            nxt = [_split(lines[i + k]) if i + k < len(lines) else ("", "", "") for k in (1, 2)]
            m84 = re.fullmatch(r"G98 G84 X(\S+) Y(\S+) Z(\S+) R(\S+) F(\S+)", nxt[0][1])
            if not m84 or nxt[1][1] != "G80" or z_now is None:
                raise NumError(f"NUM 攻丝只认 M29 S / G98 G84 X Y Z R F / G80 这一组：{body}")
            s = mt.group(1)
            x, y, z, r, f = m84.groups()
            k = _fmt(float(f) / int(s))
            if f"{float(k) * int(s):.1f}" != f"{float(f):.1f}":
                raise NumError(f"攻丝螺距 F{f} ÷ S{s} 写成 K 后换不回原来的 F，不出：{nxt[0][1]}")
            out += [f"{pre}G00 X{x} Y{y}{tail}", f"G00 Z{r}{tail}", f"{nxt[0][0]}S{s} G84 Z{z} K{k}{nxt[0][2]}",
                    f"{nxt[1][0]}G80{nxt[1][2]}", f"G00 Z{z_now}{nxt[1][2]}"]
            i += 3
            continue
        if body == "G91 G28 Z0.0":                              # 按测量原点回 Z 零点（与西门子 SUPA Z0、发格 #MCS Z0 同一约定）
            out.append(f"{pre}G00 G52 Z0{tail}")
            i += 1
            continue
        if body == "M30":                                      # NUM 程序结束 M02（§3.3.1）；配置 program.end 已经换过，这里兜底
            out.append(f"{pre}M02{tail}")
            i += 1
            continue
        if lathe:
            mt = re.fullmatch(r"T(\d{2})(\d{2})", body)
            if mt:                                              # §3.2.1.1 T01 D01 M06；§5.11.1 车床例 T05 M06
                out.append(f"{pre}T{int(mt.group(1))} D{int(mt.group(2))} M06{tail}")
                i += 1
                continue
            mt = re.fullmatch(r"G50 S(\d+)", body)
            if mt:                                              # §5.5.4 限速
                limit = float(mt.group(1))
                out.append(f"{pre}G92 S{mt.group(1)}{tail}")
                i += 1
                continue
            mt = re.fullmatch(r"G96 S(\d+) (M0[34])", body)
            if mt:                                              # §5.5.3：主轴先转（G97 S M03），再 G96 X 当前直径 S 线速
                j = i + 1
                while j < len(lines) and _is_comment(_split(lines[j])[1]):
                    j += 1
                x = _word(_split(lines[j])[1], "X") if j < len(lines) else None
                if x is None:
                    raise NumError(f"NUM 的 G96 要当前直径 X（§5.5.3），{body} 后面那一段没有 X")
                n = css_rpm(float(mt.group(1)), float(x), limit)
                out += [f"{pre}G97 S{n} {mt.group(2)}{tail}", f"G96 X{x} S{mt.group(1)}{tail}"]
                i += 1
                continue
            if re.search(r"\bG96\b", body):
                raise NumError(f"NUM 的 G96 只按 “G96 S 线速 M03 / M04” 这一种写法换（§5.5.3）：{body}")
            tok = _sub(_sub(body.split(), "G99", "G95"), "G98", "G94")
            if "G32" in tok:                                    # §5.13.2：G38 终点 K 螺距，段里不许有 M
                if not any(t.startswith("F") for t in tok):
                    raise NumError(f"车螺纹这一段没有螺距：{body}")
                if any(t.startswith("M") for t in tok):
                    raise NumError(f"NUM 的 G38 段里不许有 M 代码（§5.13.2）：{body}")
                tok = ["G38" if t == "G32" else ("K" + t[1:] if t.startswith("F") else t) for t in tok]
            body = " ".join(tok)
        else:
            mt = re.fullmatch(r"T(\d+) M06", body)
            if mt:                                              # §3.2.1.1 例 N20 T01 D01 M06
                tool, want_h = int(mt.group(1)), True
                body = f"T{tool} D{tool} M06"
            elif want_h and _word(body, "Z") is not None:       # 换刀后第一次 Z 移动：长度补偿随 D 生效（§5.11.3.1）
                tok = body.split()
                hs = [t for t in tok if re.fullmatch(r"H\d+", t)]
                if "G43" not in tok or len(hs) != 1 or int(hs[0][1:]) != tool:
                    raise NumError(f"NUM 的长度补偿随 D{tool} 生效，换刀后第一次 Z 移动要是 G43 … H{tool:02d}：{body}")
                body = " ".join(t for t in tok if t not in ("G43", hs[0]))
                want_h = False
        z = _word(body, "Z")
        if z is not None:
            z_now = z
        out.append(pre + body + tail)
        i += 1
    return "\n".join(out) + "\n"


def to_fanuc(text: str, lathe: bool) -> str:
    """回读前：NUM 写法 → FANUC 写法（to_num 的逆）"""
    lines = text.rstrip("\n").split("\n")
    out, i, gline_done, want_h, limit = [], 0, False, None, None
    while i < len(lines):
        pre, body, tail = _split(lines[i])
        m = re.fullmatch(r"%(\d+)\s*(.*)", body)
        if m and not out:
            out.append(f"O{int(m.group(1)):04d}" + (f" {m.group(2)}" if m.group(2) else "") + tail)
            i += 1
            if lathe and i < len(lines) and _split(lines[i])[1] == LATHE_NOTE:
                i += 1
            continue
        if _is_comment(body):
            out.append(lines[i])
            i += 1
            continue
        tok = body.split()
        if not gline_done and tok[0] == "G71":
            tok = _sub(tok, "G71", "G21")
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
        if mx and not lathe and i + 4 < len(lines):
            b = [_split(lines[i + k]) for k in range(1, 5)]
            m1 = re.fullmatch(r"G00 Z(\S+)", b[0][1])
            m2 = re.fullmatch(r"S(\d+) G84 Z(\S+) K(\S+)", b[1][1])
            m4 = re.fullmatch(r"G00 Z(\S+)", b[3][1])
            if m1 and m2 and b[2][1] == "G80" and m4:
                r, (s, z, k) = m1.group(1), m2.groups()
                x, y = mx.groups()
                out += [f"{pre}M29 S{s}{tail}", f"{b[1][0]}G98 G84 X{x} Y{y} Z{z} R{r} F{float(k) * int(s):.1f}{b[1][2]}",
                        f"{b[2][0]}G80{b[2][2]}"]
                i += 5
                continue
        if body == "G00 G52 Z0":
            out.append(f"{pre}G91 G28 Z0.0{tail}")
            i += 1
            continue
        if body == "M02":
            out.append(f"{pre}M30{tail}")
            i += 1
            continue
        if lathe:
            mt = re.fullmatch(r"T(\d+) D(\d+) M06", body)
            if mt:
                out.append(f"{pre}T{int(mt.group(1)):02d}{int(mt.group(2)):02d}{tail}")
                i += 1
                continue
            mt = re.fullmatch(r"G92 S(\d+)", body)
            if mt:
                limit = float(mt.group(1))
                out.append(f"{pre}G50 S{mt.group(1)}{tail}")
                i += 1
                continue
            mt = re.fullmatch(r"G97 S(\d+) (M0[34])", body)
            nb = _split(lines[i + 1]) if i + 1 < len(lines) else ("", "", "")
            m96 = re.fullmatch(rf"G96 X({_NUM}) S(\d+)", nb[1])
            if mt and m96:
                if int(mt.group(1)) != css_rpm(float(m96.group(2)), float(m96.group(1)), limit):
                    raise NumError(f"G97 S{mt.group(1)} 不是 G96 X{m96.group(1)} S{m96.group(2)} 算出来的转速，换不回去")
                out.append(f"{pre}G96 S{m96.group(2)} {mt.group(2)}{tail}")
                i += 2
                continue
            tok = _sub(_sub(body.split(), "G95", "G99"), "G94", "G98")
            if "G38" in tok:
                tok = ["G32" if t == "G38" else ("F" + t[1:] if t.startswith("K") else t) for t in tok]
            body = " ".join(tok)
        else:
            mt = re.fullmatch(r"T(\d+) D(\d+) M06", body)
            if mt:
                if mt.group(1) != mt.group(2):
                    raise NumError(f"NUM 铣床的刀补号要等于刀号才换得回 FANUC 的 H：{body}")
                want_h = int(mt.group(1))
                body = f"T{want_h} M06"
            elif want_h is not None and _word(body, "Z") is not None:
                tok = body.split()
                k = next(j for j, t in enumerate(tok) if t.startswith("Z"))
                tok = ["G43"] + tok[: k + 1] + [f"H{want_h:02d}"] + tok[k + 1:]
                body = " ".join(tok)
                want_h = None
        if re.search(r"\bG(38|52|71|84|92)\b|\bG96 X|\bD\d|\bK\d", body):
            raise NumError(f"NUM 程序这一行换不回 FANUC 写法：{body}")
        out.append(pre + body + tail)
        i += 1
    return "\n".join(out) + "\n"


def check_codes(text: str, lathe: bool, extra_m=()) -> None:
    """NUM 程序里的 G、M 代码都要在手册表里（CODES_G、CODES_M；配置换刀前后动作里的 M 代码也认），否则不出"""
    body = "\n".join(re.sub(r"\([^)]*\)", "", ln) for ln in text.split("\n"))

    def norm(c: str) -> str:
        a, _, b = c.partition(".")
        return str(int(a)) + (f".{b}" if b else "")

    have_m = set(CODES_M) | {norm(m) for m in extra_m}
    bad_g = sorted({norm(g) for g in re.findall(r"\bG(\d+(?:\.\d)?)", body) if norm(g) not in CODES_G}, key=float)
    bad_m = sorted({norm(m) for m in re.findall(r"\bM(\d+)", body)} - have_m, key=float)
    if re.search(r"\bG92\b(?! S\d)", body):
        bad_g = sorted(set(bad_g) | {"92"}, key=float)
    if bad_g or bad_m:
        miss = "、".join([f"G{g}" for g in bad_g] + [f"M{m}" for m in bad_m])
        mt = " NUM 车铣还没做（ADR-0127）。" if any(g in ("12.1", "13.1", "7.1") for g in bad_g) else ""
        raise NumError(f"NUM 程序里有手册代码表外（或还没按手册做）的 {miss}，程序不出。{mt}")
