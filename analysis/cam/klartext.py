"""海德汉 TNC 对话格式（ADR-0106 Q5b）：写好的程序按配置加工（冷却、选择停、换刀前后动作、子程序 LBL、结尾、段号、BEGIN / END PGM），
回读前换回 ISO 写法（交给 sim.parse，与整机仿真刀路逐段比），换刀前后动作检查与换成 ISO（进整机仿真）。

只做铣。对话格式要点：每段有段号（从 0 起步长 1）；`L X+.. Y+.. Z+.. R0 F..` 直线，`FMAX` 快移只管本段，F 一直有效；
`TOOL CALL 号 Z S转速` 换刀（刀长补偿自动生效）；`CYCL DEF 200` 钻孔、`CYCL DEF 207` 刚性攻丝，`M99` 在本段终点调用；
`LBL 号` … `LBL 0` 子程序，`CALL LBL 号` 调用；`M140 MB MAX` 沿刀具轴退到行程尽头。
"""

from __future__ import annotations

import re

TOOL_CALL = re.compile(r"^TOOL CALL (\d+) Z(?: S([\d.]+))?$")
_NUM = r"[+-]?\d+(?:\.\d*)?"
_L = re.compile(rf"^L((?: [XYZABC]{_NUM})*) R0(?: (FMAX|F({_NUM})))?((?: M\d+)*)$")
_LAX = re.compile(rf"([XYZABC])({_NUM})")
_Q = re.compile(rf"^Q(\d+)=({_NUM})")


class KlartextError(ValueError):
    pass


def _f(v: float) -> str:
    s = f"{float(v):.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def hnum(s: str) -> str:
    """postproc.num 写好的数字加上海德汉要的正号"""
    return s if s.startswith("-") else "+" + s


# ---------------------------------------------------------------- 换刀前后动作
def action_iso(action: str) -> list[str]:
    """配置里的一条换刀前后动作 → ISO 写法（进整机仿真）。只认回读认得的写法，其余拒收"""
    s = " ".join(action.split())
    if s == "M140 MB MAX":
        return ["G91 G28 Z0.0", "G90"]
    if re.fullmatch(r"M\d+", s):
        return [f"M{int(s[1:]):02d}"]
    m = _L.match(s)
    if m and m.group(2) == "FMAX" and m.group(1):
        return [_l_iso(m)]
    raise KlartextError(f"海德汉换刀前后动作 {action!r} 读不懂：只能写 M140 MB MAX、单独的 M 代码、或 L X/Y/Z… R0 FMAX 直线")


def _l_iso(m) -> str:
    ax = " ".join(f"{a}{_f(float(v))}" for a, v in _LAX.findall(m.group(1)))
    g = "G00" if m.group(2) == "FMAX" else "G01"
    f = f" F{_f(float(m.group(3)))}" if m.group(3) else ""
    ms = "".join(f" M{int(x):02d}" for x in re.findall(r"M(\d+)", m.group(4) or ""))
    return (f"{g} {ax}{f}{ms}").replace("  ", " ").strip()


# ---------------------------------------------------------------- 写好以后按配置加工
def finish(head: list[str], body: list[str], cfg: dict, number: int) -> str:
    """head：程序头注释（安全说明，注释“不写”时也保留）；body：程序段（不带段号）"""
    if cfg["comments"] == "none":
        body = [ln for ln in body if not ln.startswith(";")]
    if cfg["coolant"] == "off":
        body = [re.sub(r"\s*\bM[89]\b", "", ln) if not ln.startswith(";") else ln for ln in body]
        body = [ln for ln in body if ln.strip()]
    elif cfg["coolant"] == "mist":
        body = [re.sub(r"\bM8\b", "M7", ln) if not ln.startswith(";") else ln for ln in body]
    tc = cfg["tool_change"]
    out, k = [], 0
    for ln in body:
        if TOOL_CALL.match(ln):
            if k > 0 and tc["optional_stop"]:
                out.append("M1")
            out += [" ".join(a.split()) for a in tc["before"]] + [ln] + [" ".join(a.split()) for a in tc["after"]]
            k += 1
        else:
            out.append(ln)
    body = out
    end = "M2" if cfg["program"]["end"] == "M02" else "M30"
    body = [end if ln == "M30" else ln for ln in body]
    if cfg["subprograms"]:
        body = _labels(body, end)
    lines = [f"BEGIN PGM {int(number)} MM", *head, *body, f"END PGM {int(number)} MM"]
    out, n = [], 0
    for ln in lines:
        if ln.startswith(" "):                 # 循环参数续行（上一段末尾 ~）不编段号
            out.append(ln)
        else:
            out.append(f"{n} {ln}")
            n += 1
    return "\n".join(out) + "\n"


def _labels(body, end):
    """每道工序（从换刀前的注释、换刀前动作起，到下一道之前）一个 LBL，主程序按顺序 CALL LBL；标签放在程序结束之后"""
    starts = []
    for i, ln in enumerate(body):
        if TOOL_CALL.match(ln):
            j = i
            while j > 0 and body[j - 1].startswith(";"):
                j -= 1
            starts.append(j)
    if not starts:
        return body
    end_i = max(i for i, ln in enumerate(body) if ln == end)
    tail = end_i - 1 if body[end_i - 1] == "M140 MB MAX" else end_i      # 程序结束前的退刀留在主程序
    main = body[:starts[0]]
    subs = []
    for k, (s, e) in enumerate(zip(starts, starts[1:] + [tail], strict=True), 1):
        main.append(f"CALL LBL {k}")
        subs += [f"LBL {k}", *body[s:e], "LBL 0"]
    return main + body[tail:end_i + 1] + subs + body[end_i + 1:]


# ---------------------------------------------------------------- 回读：换回 ISO
def _blocks(text: str) -> list[tuple[int, str]]:
    """去掉段号、注释，续行（~）并成一段 → [(原程序行号, 程序段)]"""
    out, cur, at = [], None, 0
    for i, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s:
            continue
        if cur is not None:                      # 续行：Q 参数，分号后是说明
            cur += " " + s.split(";")[0].strip().rstrip("~").strip()
            if not s.rstrip().endswith("~"):
                out.append((at, cur))
                cur = None
            continue
        s = re.sub(r"^\d+\s+", "", s)
        if s.startswith(";"):
            continue
        if s.endswith("~"):
            cur, at = s.rstrip("~").strip(), i
            continue
        out.append((i, s.split(";")[0].strip()))
    if cur is not None:
        out.append((at, cur))
    return out


def to_iso(text: str, *, tags: bool = False) -> str:
    """对话格式 → FANUC 写法（回读用）。子程序展开；钻孔、攻丝循环按 G98 G81 / G83 / G84 写（与 sim.parse 的展开规则相同）。
    tags：每行末尾记原程序行号 (#L行号)"""
    blocks = _blocks(text)
    main, labels, cur = [], {}, None
    for ib in blocks:
        b = ib[1]
        if b.startswith(("BEGIN PGM", "END PGM")):
            continue
        m = re.fullmatch(r"LBL (\d+)", b)
        if m:
            k = int(m.group(1))
            if k == 0:
                cur = None
            else:
                cur = k
                labels[k] = []
            continue
        (labels[cur] if cur is not None else main).append(ib)
    flat = []

    def put(bs, depth=0):
        if depth > 8:
            raise KlartextError("子程序调用层数太多")
        for ib in bs:
            m = re.fullmatch(r"CALL LBL (\d+)", ib[1])
            if m:
                if int(m.group(1)) not in labels:
                    raise KlartextError(f"LBL {m.group(1)} 找不到")
                put(labels[int(m.group(1))], depth + 1)
            else:
                flat.append(ib)
    put(main)
    out = ["%", "O0001"]
    st = {"z": None, "rpm": 0.0, "cyc": None, "datum": [0.0, 0.0, 0.0]}
    mark, prev = len(out), 0
    for ln, b in flat:
        if tags:                                 # 上一段换出来的行记上它的原行号
            out[mark:] = [f"{x} (#L{prev})" for x in out[mark:]]
            mark, prev = len(out), ln

        if b in ("M30", "M2"):
            out.append("M30")
            break
        tm = TOOL_CALL.match(b)
        if tm:
            st["tool"] = int(tm.group(1))
            out.append(f"T{int(tm.group(1))} M06")
            if tm.group(2):
                st["rpm"] = float(tm.group(2))
                out.append(f"S{_f(float(tm.group(2)))}")
            continue
        m7 = re.fullmatch(rf"CYCL DEF 7\.([0-3])(?: DATUM SHIFT| ([XYZ])({_NUM}))", b)
        if m7:                                       # 零点平移（倾斜面的平面原点）
            if m7.group(2):
                st["datum"]["XYZ".index(m7.group(2))] = float(m7.group(3))
            continue
        mp = re.fullmatch(rf"PLANE SPATIAL SPA({_NUM}) SPB({_NUM}) SPC({_NUM})(?: TURN)?(?: MB MAX)?(?: FMAX)?", b)
        if mp:                                       # PLANE SPATIAL → G68.2（同一个旋转换成 Z-X-Z 欧拉角）+ G53.1
            from analysis.cam import tilt

            i, j, k = tilt.euler_zxz(tilt.from_spatial(*(float(x) for x in mp.groups())))
            d = st["datum"]
            out += [f"G68.2 X{_f(d[0])} Y{_f(d[1])} Z{_f(d[2])} I{_f(i)} J{_f(j)} K{_f(k)}", "G53.1"]
            continue
        if b in ("PLANE RESET STAY", "PLANE RESET TURN", "PLANE RESET"):
            out.append("G69")
            continue
        if b.startswith("CYCL DEF"):
            q = {int(k): float(v) for k, v in (_Q.match(w).groups() for w in b.split() if _Q.match(w))}
            num = int(b.split()[2])
            if num not in (200, 207):
                raise KlartextError(f"CYCL DEF {num} 回读不认")
            st["cyc"] = (num, q)
            continue
        if b == "M140 MB MAX":
            out += ["G91 G28 Z0.0", "G90"]
            continue
        if b in ("FUNCTION TCPM F TCP AXIS POS PATHCTRL AXIS", "M128"):   # 刀尖跟随（ADR-0106 C3a）→ G43.4
            out.append(f"G43.4 H{st.get('tool', 0):02d}")
            continue
        if b in ("FUNCTION RESET TCPM", "M129"):
            out.append("G49")
            continue
        if re.fullmatch(r"M\d+", b):
            out.append(f"M{int(b[1:]):02d}")
            continue
        m = _L.match(b)
        if not m:
            raise KlartextError(f"程序段 {b!r} 回读不认")
        ms = [int(x) for x in re.findall(r"M(\d+)", m.group(4) or "")]
        call = 99 in ms
        if call:
            m2 = _L.match(b.replace(" M99", ""))
            out.append(_l_iso(m2))
            if not m2.group(1) and not m2.group(4):
                out.pop()
            out += _cycle(st)
        else:
            out.append(_l_iso(m))
        for a, v in _LAX.findall(m.group(1)):
            if a == "Z":
                st["z"] = float(v)
    if tags:
        out[mark:] = [f"{x} (#L{prev})" for x in out[mark:]]
    out.append("%")
    return "\n".join(x for x in out if x) + "\n"


def _cycle(st) -> list[str]:
    if not st["cyc"]:
        raise KlartextError("M99 前没有 CYCL DEF")
    num, q = st["cyc"]
    try:
        top, r, z = q[203], q[203] + q[200], q[203] + q[201]
        back = q[203] + max(q[200], q[204])
    except KeyError as exc:
        raise KlartextError(f"CYCL DEF {num} 缺参数 Q{exc.args[0]}") from exc
    del top
    init = st["z"]
    g98 = init is not None and abs(back - init) < 5e-4      # 退回到循环开始的高度：同 G98；否则 G99 退到 R 再快移
    if num == 200:
        depth = -q[201]
        peck = q[202]
        w = ["G98" if g98 else "G99", "G81" if peck >= depth - 1e-9 else "G83", f"Z{_f(z)}", f"R{_f(r)}"]
        if peck < depth - 1e-9:
            w.append(f"Q{_f(peck)}")
        w.append(f"F{_f(q[206])}")
        out = [" ".join(w), "G80"]
    else:
        if st["rpm"] <= 0:
            raise KlartextError("CYCL DEF 207 没有主轴转速")
        out = [f"M29 S{_f(st['rpm'])}", f"{'G98' if g98 else 'G99'} G84 Z{_f(z)} R{_f(r)} F{_f(q[239] * st['rpm'])}", "G80"]
    if not g98:
        out.append(f"G00 Z{_f(back)}")
    st["z"] = back
    return out
