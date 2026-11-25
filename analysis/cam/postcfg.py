"""可配置后处理（ADR-0106 Q5a、ADR-0109 cam-post/1）：读配置、按家族补缺省，写好程序后按配置加工（顺序号、换刀前后动作、选择停、冷却、
程序号与结尾、子程序），回读前按同一套规则还原（子程序展开、顺序号去掉不影响）。

配置只是开关。安全底线（没仿真不出、回读一致才出、程序头的“首件空运行”“未经实机验证”）在 postproc.render 里，配置改不了：
注释选“不写”时，程序头的安全说明照样写。
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schema" / "cam-post.schema.json"
BUILTIN = Path(__file__).resolve().parent / "posts"
ISO = ("fanuc", "gsk", "hnc")          # ISO 代码家族：括号注释、O 程序号（华中用 %号）、M98 / M99 子程序

# 各家族的缺省（等于 ADR-0104 C1 的写法；配置里不写的项用这些）
DEFAULTS = {
    "fanuc": {"program": {"number_digits": 4, "percent": True, "end": "M30"}, "sequence": {"enabled": False, "start": 10, "step": 10},
              "decimals": {"coord": 3, "feed": None}, "comments": "ascii", "tool_change": {"before": [], "after": [], "optional_stop": False},
              "coolant": "flood", "cycles": {"drill": False, "turn": True}, "subprograms": False},
    "siemens": {"program": {"number_digits": 4, "percent": False, "end": "M30"}, "sequence": {"enabled": False, "start": 10, "step": 10},
                "decimals": {"coord": 3, "feed": None}, "comments": "utf8", "tool_change": {"before": [], "after": [], "optional_stop": False},
                "coolant": "flood", "cycles": {"drill": False, "turn": False}, "subprograms": False},
}
DEFAULTS["heidenhain"] = {"program": {"number_digits": 8, "percent": False, "end": "M30"}, "sequence": {"enabled": False, "start": 0, "step": 1},
                          "decimals": {"coord": 3, "feed": None}, "comments": "ascii",
                          "tool_change": {"before": [], "after": [], "optional_stop": False},
                          "coolant": "flood", "cycles": {"drill": False, "turn": False}, "subprograms": False}
DEFAULTS["gsk"] = DEFAULTS["fanuc"]
# 发格（ADR-0126）：按 FANUC 写好再换成发格写法；固定循环、子程序、冷却 M 代码不写（发格另有一套或由机床厂定）
DEFAULTS["fagor"] = {**DEFAULTS["fanuc"], "program": {"number_digits": 4, "percent": False, "end": "M30"}, "coolant": "off",
                     "cycles": {"drill": False, "turn": False}}
DEFAULTS["hnc"] = DEFAULTS["fanuc"]


class PostConfigError(ValueError):
    pass


@lru_cache(maxsize=1)
def _validator():
    from jsonschema import Draft202012Validator

    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def check(cfg: dict, where: str = "") -> dict:
    errs = sorted(_validator().iter_errors(cfg), key=lambda e: list(e.absolute_path))
    if errs:
        raise PostConfigError(f"{where + '：' if where else ''}后处理配置不符合 cam-post/1：" +
                              "；".join(f"{'/'.join(map(str, e.absolute_path)) or '（顶层）'}：{e.message}" for e in errs[:5]))
    fam = cfg["family"]
    if fam == "okuma":                         # ADR-0124：家族的基本写法要按厂商官方编程手册做（ADR-0106 E3 工业级标准）
        raise PostConfigError(f"{where + '：' if where else ''}{fam} 家族的基本写法要按厂商官方编程手册做，手册还没到，还不能用（ADR-0106 E3）")
    dl = cfg.get("dialect") or {}
    if fam == "fagor":                         # ADR-0126 第 4 条
        w = where + "：" if where else ""
        if dl:
            raise PostConfigError(f"{w}发格的写法已按官方编程手册固定（ADR-0126），不收 dialect")
        if (cfg.get("cycles") or {}).get("turn") or (cfg.get("cycles") or {}).get("drill"):
            raise PostConfigError(f"{w}发格的 G70 / G71 是英制 / 公制，固定循环的参数另有一套，请关掉 cycles（ADR-0126）")
        if cfg.get("subprograms"):
            raise PostConfigError(f"{w}发格的子程序（%L、#CALL）还没做，请关掉 subprograms（ADR-0126）")
        if cfg.get("coolant", "off") != "off":
            raise PostConfigError(f"{w}发格手册的 M 代码表里没有冷却，冷却的 M 代码由机床厂定：coolant 写 off，按机床说明书写进换刀后动作（ADR-0126）")
        if cfg.get("millturn") or cfg.get("twin") or cfg.get("channels"):
            raise PostConfigError(f"{w}发格车铣、双主轴、多通道还没做（ADR-0126）")
    if dl and fam not in ISO:
        raise PostConfigError(f"{where + '：' if where else ''}写法差别（dialect）只用于 ISO 家族（fanuc / gsk / hnc，ADR-0124）")
    if dl.get("turn_cycles") == "one_block":
        raise PostConfigError(f"{where + '：' if where else ''}复合循环的单段写法还没按官方手册做，请写 two_block 或 none（ADR-0124）")
    for key, v in dl.items():
        if key in ("sources", "turn_cycles", "codes"):
            continue
        for t in (v if isinstance(v, list) else [v]):
            bad = set(re.findall(r"\{([a-z]+)\}", t)) - set(_PH)
            if bad:
                raise PostConfigError(f"{where + '：' if where else ''}dialect.{key} 里有不认识的占位符 {', '.join(sorted(bad))}")
    if dl:
        have = {x["item"] for x in dl["sources"]}
        miss = [k for k in dl if k != "sources" and k not in have]
        if miss:
            raise PostConfigError(f"{where + '：' if where else ''}dialect 的 {'、'.join(miss)} 没写出处（sources，ADR-0124）")
    if fam == "heidenhain":
        from analysis.cam import klartext

        if "lathe" in cfg["kinds"]:
            raise PostConfigError(f"{where}：海德汉后处理只有铣（ADR-0106 Q5b）")
        if (cfg.get("sequence") or {}).get("enabled"):
            raise PostConfigError(f"{where}：海德汉对话格式每段都有段号（从 0 起步长 1），请关掉 sequence")
        if (cfg.get("program") or {}).get("percent"):
            raise PostConfigError(f"{where}：海德汉程序用 BEGIN PGM / END PGM，不写 %，请关掉 program.percent")
        if (cfg.get("cycles") or {}).get("turn"):
            raise PostConfigError(f"{where}：海德汉后处理只有铣，请关掉 cycles.turn")
        tc = cfg.get("tool_change") or {}
        for a in (tc.get("before") or []) + (tc.get("after") or []):
            try:
                klartext.action_iso(a)
            except klartext.KlartextError as exc:
                raise PostConfigError(f"{where}：{exc}") from exc
    if fam == "siemens":
        tc = cfg.get("tool_change") or {}
        if tc.get("before") or tc.get("after"):
            raise PostConfigError(f"{where}：西门子的换刀前后动作还没做（仿真按 ISO 写法读）；请先不写")
        if cfg.get("subprograms"):
            raise PostConfigError(f"{where}：西门子的子程序要单独存文件，还没做；请关掉 subprograms")
        if (cfg.get("cycles") or {}).get("drill") or (cfg.get("cycles") or {}).get("turn"):
            raise PostConfigError(f"{where}：西门子的固定循环（CYCLE81 / 95 等）还没做；请关掉 cycles")
    if cfg.get("coolant") == "through":
        raise PostConfigError(f"{where}：内冷的 M 代码各厂不同，请把它写进 tool_change 的换刀后动作，coolant 写 flood 或 off")
    if fam == "gsk" and "mill" in cfg["kinds"]:
        raise PostConfigError(f"{where}：广数后处理只有车床")
    if fam != "siemens":                          # ADR-0111：括号只给西门子的 SETMS(2)、SPOS[1]=0 用；FANUC 系里圆括号是注释
        for sec in ("millturn", "twin"):
            for k, lines in (cfg.get(sec) or {}).items():
                if any(ch in ln for ln in lines for ch in "()[],"):
                    raise PostConfigError(f"{where}：FANUC 写法的车铣程序行（{sec}.{k}）不该带括号或逗号（ADR-0111）")
        chc = cfg.get("channels") or {}
        if any(ch in ln for ln in [chc.get("wait", ""), *(x for h in chc.get("heads") or [] for x in h)] for ch in "()[],"):
            raise PostConfigError(f"{where}：FANUC 写法的多通道程序行（channels）不该带括号或逗号（ADR-0111、ADR-0123）")
    return cfg


def user_dir(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env["FAP_POSTS"]) if env.get("FAP_POSTS") else Path.home() / ".freecad-ai-parts" / "posts"


def load(path) -> dict:
    p = Path(path)
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PostConfigError(f"{p}：读不了后处理配置：{exc}") from exc
    return check(cfg, str(p))


def configs(env=None) -> dict:
    """{id: 配置}：内置在前，用户的同 id 覆盖内置。用户配置不合格的不列出（problems() 里写明哪个文件、哪一项）"""
    out = {}
    for p in sorted(BUILTIN.glob("*.json")):
        c = load(p)
        out[c["id"]] = {**c, "_builtin": True}
    for p, c, _err in _user(env):
        if c is not None:
            out[c["id"]] = {**c, "_builtin": False, "_path": str(p)}
    return out


def _user(env=None):
    d = user_dir(env)
    out = []
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            out.append((p, load(p), ""))
        except PostConfigError as exc:
            out.append((p, None, str(exc)))
    return out


def problems(env=None) -> list[str]:
    """用户后处理配置里不合格的（没列进可选后处理的原因）"""
    return [e for _p, c, e in _user(env) if c is None]


def resolved(cfg: dict) -> dict:
    """配置 + 家族缺省（逐项合并）；dialect.turn_cycles = none 时不用车削复合循环"""
    base = DEFAULTS[cfg["family"]]
    out = {**cfg}
    for k, v in base.items():
        if isinstance(v, dict):
            out[k] = {**v, **(cfg.get(k) or {})}
        else:
            out[k] = cfg.get(k, v)
    if (cfg.get("dialect") or {}).get("turn_cycles") == "none":
        out["cycles"] = {**out["cycles"], "turn": False}
    return out


# ---------------------------------------------------------------- 写法差别（ADR-0124）
_NUM = r"-?\d+(?:\.\d*)?"
_PH = {"n": r"\d+", "nn": r"\d{2}", "o": r"\d+", "oo": r"\d{2}", "s": r"\d+", "r": _NUM, "d": _NUM, "rpm": r"\d+", "number": r"\d+"}
_KEY = {"nn": "n", "oo": "o"}                # 两位写法与一位写法是同一个数


def _fill(t: str, v: dict) -> str:
    def one(m):
        k = m.group(1)
        if k in ("nn", "oo"):
            return f"{int(v[_KEY[k]]):02d}"
        if k in ("n", "o", "s", "rpm", "number"):
            return str(int(v[k]))
        return str(v[k])
    return re.sub(r"\{([a-z]+)\}", one, t)


def _tpl_re(t: str) -> re.Pattern:
    """模板 → 正则；同一个数出现两次（如 T{nn}{oo}{oo}）要相同"""
    seen, out, pos = set(), "", 0
    for m in re.finditer(r"\{([a-z]+)\}", t):
        out += re.escape(t[pos:m.start()])
        k = _KEY.get(m.group(1), m.group(1))
        out += f"(?P={k})" if k in seen else f"(?P<{k}>{_PH[m.group(1)]})"
        seen.add(k)
        pos = m.end()
    return re.compile("^" + out + re.escape(t[pos:]) + "$")


def _rules(dl: dict, lathe: bool) -> list:
    """FANUC 写法（问渠CAM 的基本写法）↔ 这家的写法：[(FANUC 正则, FANUC 模板, 这家的模板行)]"""
    from analysis.cam.post import num

    r = []
    if lathe and dl.get("tool_call_lathe"):
        r.append((re.compile(r"^T(?P<n>\d{2})(?P<o>\d{2})$"), "T{nn}{oo}", [dl["tool_call_lathe"]]))
    if not lathe and dl.get("tool_call_mill"):
        r.append((re.compile(r"^T(?P<n>\d+) M06$"), "T{n} M06", list(dl["tool_call_mill"])))
    if lathe and dl.get("spindle_limit"):
        r.append((re.compile(r"^G50 S(?P<s>\d+)$"), "G50 S{s}", [dl["spindle_limit"]]))
    if dl.get("polar"):
        r += [(re.compile(r"^G12\.1$"), "G12.1", [dl["polar"][0]]), (re.compile(r"^G13\.1$"), "G13.1", [dl["polar"][1]])]
    if dl.get("cylindrical"):
        r += [(re.compile(r"^G07\.1 C0$"), "G07.1 C0", [dl["cylindrical"][1]]),
              (re.compile(rf"^G07\.1 C(?P<r>{_NUM})$"), "G07.1 C{r}", [dl["cylindrical"][0]])]
    if "rigid_tap" in dl:                     # 刚性攻丝 G84 前面的行（ADR-0125）；[] = 不写
        r.append((re.compile(r"^M29 S(?P<s>\d+)$"), "M29 S{s}", list(dl["rigid_tap"])))
    del num
    return r


def _code_norm(c: str) -> str:
    a, _, b = c.partition(".")
    return str(int(a)) + (f".{b}" if b else "")


def check_codes(text: str, cfg: dict) -> None:
    """正式程序里的 G、M 代码都要在这家手册的代码表里（dialect.codes，ADR-0125），否则不出"""
    codes = (cfg.get("dialect") or {}).get("codes")
    if not codes:
        return
    body = "\n".join(re.sub(r"\([^)]*\)", "", ln) for ln in text.split("\n"))
    have_g = {_code_norm(x) for x in codes["g"]}
    have_m = {_code_norm(x) for x in codes["m"]}
    bad_g = sorted({_code_norm(g) for g in re.findall(r"\bG(\d+(?:\.\d)?)", body)} - have_g, key=float)
    bad_m = sorted({_code_norm(m) for m in re.findall(r"\bM(\d+)", body)} - have_m, key=float)
    if bad_g or bad_m:
        miss = "、".join([f"G{g}" for g in bad_g] + [f"M{m}" for m in bad_m])
        raise PostConfigError(f"{cfg['name']} 的手册代码表里没有 {miss}（ADR-0125），程序不出")


def _split_n(line: str):
    m = re.match(r"^(N\d+\s+)(.*)$", line)
    return (m.group(1), m.group(2)) if m else ("", line)


def apply_dialect(lines: list, cfg: dict, lathe: bool) -> list:
    """写好的 FANUC 写法逐行换成这家的写法（换刀、限速、车铣插补开关）"""
    from analysis.cam.post import num

    dl = cfg.get("dialect") or {}
    rules = _rules(dl, lathe)
    if not rules:
        return lines
    out = []
    for ln in lines:
        pre, body = _split_n(ln.strip())
        for rx, _f, tpl in rules:
            m = rx.match(body)
            if m:
                v = m.groupdict()
                if "r" in v:
                    v["d"] = num(2.0 * float(v["r"]))
                if tpl:                                     # 模板是空的（rigid_tap: []）：这一行不写
                    out += [pre + _fill(tpl[0], v)] + [_fill(t, v) for t in tpl[1:]]
                break
        else:
            out.append(ln)
    return out


def undo_dialect(text: str, cfg: dict, lathe: bool) -> str:
    """回读前：这家的写法换回 FANUC 写法（apply_dialect 的逆）"""
    from analysis.cam.post import num

    dl = cfg.get("dialect") or {}
    rules = _rules(dl, lathe)
    if not rules:
        return text
    lines = text.split("\n")
    if dl.get("rigid_tap") == []:              # 这家不写 M29：回读时在 G84 前补回 FANUC 的 M29 S（转速取前面最近的 S）
        fixed, s_last = [], None
        for ln in lines:
            body = _split_n(re.sub(r"\s*\(#L\d+\)$", "", ln.strip()))[1]
            mm = re.search(r"\bS(\d+)\b", body)
            if re.search(r"\bG84\b", body) and s_last is not None:
                fixed.append(f"M29 S{s_last}")
            if mm and not re.search(r"\bG84\b", body):
                s_last = mm.group(1)
            fixed.append(ln)
        lines = fixed
    out, i = [], 0
    while i < len(lines):
        raw = lines[i].strip()
        mt = re.search(r"\s*\(#L\d+\)$", raw)                  # 回读时记的原程序行号（postproc.tag）
        tail = mt.group(0) if mt else ""
        pre, body = _split_n(raw[: len(raw) - len(tail)])
        hit = False
        for _rx, fan, tpl in rules:
            if not tpl:
                continue
            m = _tpl_re(tpl[0]).match(body)
            if not m or not all(i + k < len(lines) and _tpl_re(t).match(_split_n(re.sub(r"\s*\(#L\d+\)$", "", lines[i + k].strip()))[1])
                                for k, t in enumerate(tpl[1:], 1)):
                continue
            v = m.groupdict()
            if "d" in v and "r" not in v:
                v["r"] = num(float(v["d"]) / 2.0)
            out.append(pre + _fill(fan, v) + tail)
            i += len(tpl)
            hit = True
            break
        if not hit:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


# ---------------------------------------------------------------- 写好以后按配置加工
_TOOL_CHANGE = {"iso_mill": re.compile(r"^T\d+ M0?6$"), "iso_lathe": re.compile(r"^T\d{4}$"),
                "sie_mill": re.compile(r"^T\d+ M6$"), "sie_lathe": re.compile(r"^T\d+ D1$")}


def _is_comment(line: str, family: str) -> bool:
    s = line.strip()
    return (s.startswith(";") if family == "siemens" else (s.startswith("(") and s.endswith(")")))


def finish(text: str, cfg: dict, lathe: bool, number: int) -> str:
    """按配置加工写好的程序（家族的基本写法已经在 postproc 里写好）"""
    fam = cfg["family"]
    lines = text.rstrip("\n").split("\n")
    # 程序头：程序头部分（安全说明）在第一个 G21 / G17 / G18 行之前，注释“不写”时也保留
    head_end = next(i for i, ln in enumerate(lines) if ln.startswith(("G21", "G17", "G18")))
    head, body = lines[:head_end + 1], lines[head_end + 1:]
    if fam in ISO:
        digits = cfg["program"]["number_digits"]
        if len(str(int(number))) > digits:
            raise PostConfigError(f"程序号 {number} 超过 {digits} 位")
        head = [ln for ln in head if ln != "%"]
        o = next(i for i, ln in enumerate(head) if re.match(r"^O\d+", ln))
        rest = head[o][len(re.match(r"^O\d+", head[o]).group(0)):]
        head[o] = (f"%{int(number):0{digits}d}" if fam == "hnc" else f"O{int(number):0{digits}d}") + rest
        body = [ln for ln in body if ln != "%"]
    if cfg["comments"] == "none":
        body = [ln for ln in body if not _is_comment(ln, fam)]
    # 冷却
    if cfg["coolant"] == "off":
        body = [re.sub(r"\s*\bM0?[89]\b", "", ln) for ln in body]
        body = [ln for ln in body if ln.strip()]
    elif cfg["coolant"] == "mist":
        body = [re.sub(r"\bM08\b", "M07", re.sub(r"\bM8\b", "M7", ln)) for ln in body]
    # 换刀前后动作、选择停（仿真用的程序里也加了同样的，见 tool_change_actions）
    key = ("iso_" if fam in ISO else "sie_") + ("lathe" if lathe else "mill")
    body = _actions(body, cfg, key)
    # 结尾
    if cfg["program"]["end"] == "M02":
        body = ["M02" if ln.strip() == "M30" else ln for ln in body]
    # 子程序（ISO 家族）：每道工序（从一次换刀前的注释或换刀起，到下一次之前）一个子程序，主程序按顺序 M98 调用
    if cfg["subprograms"] and fam in ISO:
        body = _subprograms(body, key, number, cfg)
    # 写法差别（ADR-0124）
    body = apply_dialect(body, cfg, lathe)
    # 顺序号
    if cfg["sequence"]["enabled"]:
        body = _sequence(body, cfg, fam)
    if fam in ISO and cfg["program"]["percent"]:
        head = ["%"] + head
        body = body + ["%"]
    return "\n".join(head + body) + "\n"


def _actions(lines, cfg, key):
    fam = cfg["family"]
    tc = cfg["tool_change"]
    out, k = [], 0
    for ln in lines:
        if _TOOL_CHANGE[key].match(ln.strip()):
            if k > 0 and tc["optional_stop"]:
                out.append("M01" if fam in ISO else "M1")
            out += list(tc["before"]) + [ln] + list(tc["after"])
            k += 1
        else:
            out.append(ln)
    return out


def tool_change_actions(gcode: str, cfg: dict, lathe: bool) -> str:
    """仿真用的程序（post.post 写的 FANUC 写法）里加上配置的换刀前后动作和选择停：这些动作会动机床（如 G91 G28 Z0），
    要和正式程序一样进整机仿真，回读才对得上（ADR-0106 Q5a）"""
    lines = gcode.rstrip("\n").split("\n")
    if cfg["family"] == "heidenhain":                # 对话格式的动作换成 ISO 再进仿真
        from analysis.cam import klartext

        tc = cfg["tool_change"]
        cfg = {**cfg, "family": "fanuc", "tool_change": {**tc, "before": [x for a in tc["before"] for x in klartext.action_iso(a)],
                                                         "after": [x for a in tc["after"] for x in klartext.action_iso(a)]}}
    return "\n".join(_actions(lines, cfg, "iso_" + ("lathe" if lathe else "mill"))) + "\n"


def _op_starts(body, key):
    starts = []
    for i, ln in enumerate(body):
        if _TOOL_CHANGE[key].match(ln.strip()):
            j = i
            while j > 0 and not body[j - 1].strip().startswith(("G", "M", "S", "T", "X", "Y", "Z", "N")):
                j -= 1                       # 换刀前的注释、换刀前动作归这道工序
            starts.append(j)
    return starts


def _subprograms(body, key, number, cfg):
    starts = _op_starts(body, key)
    if not starts:
        return body
    end_i = next(i for i in range(len(body) - 1, -1, -1) if body[i].strip() in ("M30", "M02"))
    pre = body[:starts[0]]
    chunks = [body[s:e] for s, e in zip(starts, starts[1:] + [end_i], strict=True)]
    digits = cfg["program"]["number_digits"]
    main, subs = list(pre), []
    for k, ch in enumerate(chunks, 1):
        sub_n = int(number) * 10 + k if len(str(int(number) * 10 + k)) <= digits else int(number) + k
        main.append(f"M98 P{sub_n:0{digits}d}")
        subs += ["", f"O{sub_n:0{digits}d}", *ch, "M99"]
    return main + body[end_i:] + subs


def _sequence(body, cfg, fam):
    """每个程序段前加 N（注释、空行、O / % 行不加）；G71 / G70 的 P、Q 改成新段号"""
    n, step = cfg["sequence"]["start"], cfg["sequence"]["step"]
    remap, out = {}, []
    for ln in body:
        s = ln.strip()
        if not s or _is_comment(s, fam) or re.match(r"^[O%]\d*", s):
            out.append(ln)
            continue
        m = re.match(r"^N(\d+)\s+(.*)$", s)
        if m:
            remap[int(m.group(1))] = n
            s = m.group(2)
        out.append(f"N{n} {s}")
        n += step
    if remap:
        def fix(m):
            return f"P{remap.get(int(m.group(1)), int(m.group(1)))} Q{remap.get(int(m.group(2)), int(m.group(2)))}"
        out = [re.sub(r"P(\d+) Q(\d+)", fix, ln) if re.search(r"\bG7[01]\b", ln) else ln for ln in out]
    return out


# ---------------------------------------------------------------- 回读前还原
def expand(text: str, cfg: dict) -> str:
    """回读前：子程序调用展开成子程序内容（ISO 家族 M98 P / M99），华中的 %号 程序头换成 O 号；顺序号 sim.parse 自己认"""
    fam = cfg["family"]
    lines = text.split("\n")
    if fam == "hnc":
        lines = [("O" + ln[1:]) if re.match(r"^%\d+", ln.strip()) else ln for ln in lines]
    if fam not in ISO or not any(re.search(r"\bM98\b", ln) for ln in lines):
        return "\n".join(lines)
    subs, cur, main = {}, None, []
    for ln in lines:
        s = re.sub(r"^N\d+\s+", "", ln.strip())
        m = re.match(r"^O(\d+)", s)
        if m and main and any(x.strip() in ("M30", "M02") or re.search(r"\bM(30|02)\b", x) for x in main):
            cur = int(m.group(1))
            subs[cur] = []
            continue
        if cur is not None:
            if re.search(r"\bM99\b", s):
                cur = None
            else:
                subs[cur].append(ln)
            continue
        main.append(ln)
    out = []
    for ln in main:
        m = re.search(r"\bM98\s+P(\d+)", ln)
        if m:
            if int(m.group(1)) not in subs:
                raise PostConfigError(f"子程序 O{m.group(1)} 找不到")
            out += subs[int(m.group(1))]
        else:
            out.append(ln)
    return "\n".join(out)
