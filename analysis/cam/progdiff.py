"""问渠CAM 程序对比（ADR-0106 Q6b）：两版程序差在哪。

两版程序各自按回读规则换成 FANUC 写法（子程序展开、西门子 / 海德汉换写法，每行记着原程序的行号），用 sim.parse 读成刀路，
再按“类型、刀号、终点”逐段对齐。只比刀路和工艺（刀具、转速、进给、刀路、时间）；顺序号、注释、小数位写法不同不算差别。

结果：{"same", "tools", "speeds", "hunks", "time", "lines"}，`report(结果, lang)` 写成中英文 Markdown。
命令行：python -m analysis.cam.progdiff 旧.nc 新.nc --machine EX-VMC
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

from analysis.cam import postproc, sim

TOL = 1e-3          # 终点差小于这个（mm）算同一点
_TAG = re.compile(r"\(#L(\d+)\)")


def detect(text: str) -> str:
    """认数控系统家族：BEGIN PGM → 海德汉；西门子特有的字（DIAMON、SUPA、G331、LIMS=、分号注释开头）→ 西门子；发格特有的写法（#MCS、G151、G192、T 刀号 D 刀补 M6，ADR-0126）→ 发格；%号开头 → 华中；其余 FANUC"""
    if re.search(r"^\s*\d*\s*BEGIN PGM", text, re.MULTILINE):
        return "heidenhain"
    if re.search(r"\b(DIAMON|SUPA|G331|LIMS=)", text) or re.search(r"^\s*;", text, re.MULTILINE):
        return "siemens"
    if re.search(r"#MCS\b|\bG151\b|\bG192\b|\bT\d+ D\d+ M6\b", text):
        return "fagor"
    if re.search(r"^%\d+", text, re.MULTILINE):
        return "hnc"
    return "fanuc"


def load(text: str, mach: dict, controller: str | None = None) -> dict:
    """程序 → {"moves", "parsed", "controller"}：每段刀路带原程序行号 src"""
    ctl = controller or detect(text)
    lathe = mach["kind"] in ("lathe", "mill_turn")
    iso = postproc.to_fanuc(text, ctl, lathe, tags=True)
    lines = iso.splitlines()
    parsed = sim.parse(iso, mach)
    moves = []
    for mv in parsed["moves"]:
        m = _TAG.search(lines[mv["line"] - 1]) if 0 < mv["line"] <= len(lines) else None
        moves.append({**mv, "src": int(m.group(1)) if m else None})
    return {"moves": moves, "parsed": parsed, "controller": ctl, "time": sim.timing(parsed, mach)}


def _key(mv):
    return (mv["t"], *(round(v / TOL) for v in mv["b"]))


def _order(moves):
    """用刀顺序（按刀路里出现的先后）"""
    out = []
    for m in moves:
        if m["tool"] and (not out or out[-1] != m["tool"]):
            out.append(m["tool"])
    return out


def _speed(mv):
    return ("css", round(mv["css"], 3)) if mv.get("css") else ("rpm", round(mv["rpm"], 3))


def compare(text_a: str, text_b: str, mach: dict, *, controller_a: str | None = None, controller_b: str | None = None) -> dict:
    A, B = load(text_a, mach, controller_a), load(text_b, mach, controller_b)
    ma = [m for m in A["moves"] if not m.get("home")]          # 回参考点是机床自己走的，不比（与回读比对同一规则）
    mb = [m for m in B["moves"] if not m.get("home")]
    ta, tb = _order(ma), _order(mb)
    tools = {"added": sorted(set(tb) - set(ta)), "removed": sorted(set(ta) - set(tb)), "a": ta, "b": tb}
    sm = difflib.SequenceMatcher(a=[_key(m) for m in ma], b=[_key(m) for m in mb], autojunk=False)
    hunks, speeds = [], {}
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for x, y in zip(ma[i1:i2], mb[j1:j2], strict=True):        # 刀路一样：比刀号、转速、进给
                if x["tool"] != y["tool"]:
                    k = ("tool", x["tool"], x["tool"], y["tool"])
                    speeds.setdefault(k, {"lines_a": [], "lines_b": [], "n": 0})
                    speeds[k]["n"] += 1
                    speeds[k]["lines_a"].append(x["src"])
                    speeds[k]["lines_b"].append(y["src"])
                    continue
                if x["t"] != "rapid" and abs(x["f"] - y["f"]) > 1e-9:
                    k = ("feed", x["tool"], round(x["f"], 4), round(y["f"], 4))
                    speeds.setdefault(k, {"lines_a": [], "lines_b": [], "n": 0})
                    speeds[k]["n"] += 1
                    speeds[k]["lines_a"].append(x["src"])
                    speeds[k]["lines_b"].append(y["src"])
                if _speed(x) != _speed(y):
                    k = ("spindle", x["tool"], _speed(x), _speed(y))
                    speeds.setdefault(k, {"lines_a": [], "lines_b": [], "n": 0})
                    speeds[k]["n"] += 1
                    speeds[k]["lines_a"].append(x["src"])
                    speeds[k]["lines_b"].append(y["src"])
            continue
        xa, xb = ma[i1:i2], mb[j1:j2]
        h = {"kind": {"replace": "changed", "delete": "removed", "insert": "added"}[op],
             "lines_a": _span(xa), "lines_b": _span(xb), "moves_a": len(xa), "moves_b": len(xb),
             "tools": sorted({m["tool"] for m in xa + xb})}
        if op == "replace" and len(xa) == len(xb) and all(x["t"] == y["t"] for x, y in zip(xa, xb, strict=True)):
            h["max_dev_mm"] = max(max(abs(u - v) for u, v in zip(x["b"], y["b"], strict=True)) for x, y in zip(xa, xb, strict=True))
            k0 = next(i for i, (x, y) in enumerate(zip(xa, xb, strict=True)) if _key(x) != _key(y))
            h["first"] = {"a": list(xa[k0]["b"]), "b": list(xb[k0]["b"]), "line_a": xa[k0]["src"], "line_b": xb[k0]["src"]}
            fp = sorted({(round(x["f"], 4), round(y["f"], 4)) for x, y in zip(xa, xb, strict=True)
                         if x["t"] != "rapid" and abs(x["f"] - y["f"]) > 1e-9})
            if fp:
                h["feeds"] = [list(f) for f in fp]
        hunks.append(h)
    sp = [{"what": k[0], "tool": k[1], "a": k[2], "b": k[3], "moves": v["n"], "lines_a": _span_n(v["lines_a"]),
           "lines_b": _span_n(v["lines_b"])} for k, v in speeds.items()]
    ka = ("cut_s", "rapid_s", "tool_s", "total_s")
    time = {k: {"a": A["time"][k], "b": B["time"][k], "diff": B["time"][k] - A["time"][k]} for k in ka}
    same = not hunks and not sp and not tools["added"] and not tools["removed"] and ta == tb
    return {"same": same, "controllers": [A["controller"], B["controller"]], "moves": [len(ma), len(mb)], "tools": tools,
            "speeds": sp, "hunks": hunks, "time": time}


def _span(mvs):
    return _span_n([m["src"] for m in mvs])


def _span_n(lines):
    ls = sorted({x for x in lines if x is not None})
    return [ls[0], ls[-1]] if ls else None


# ---------------------------------------------------------------- 报告
TXT = {
    "title": ("程序对比", "Program comparison"),
    "same": ("刀路相同：刀具、转速、进给、每一段刀路都一样（顺序号、注释、小数位写法不同不算差别）。",
             "Tool paths are identical: tools, speeds, feeds and every move are the same (sequence numbers, comments and number formatting are ignored)."),
    "diff": ("两版程序有差别：", "The programs differ:"),
    "ctl": ("数控系统", "Control"), "moves": ("刀路段数", "Moves"),
    "tools": ("刀具", "Tools"), "added": ("新版加了", "added in B"), "removed": ("新版去了", "removed in B"),
    "order": ("用刀顺序", "tool order"),
    "speeds": ("刀号、转速、进给", "Tools, speeds and feeds"),
    "feed": ("进给", "feed"), "spindle": ("转速", "spindle"), "tool": ("同样的刀路换了刀", "same path, other tool"),
    "path": ("刀路", "Tool path"),
    "changed": ("改了", "changed"), "added_h": ("新版多了", "added in B"), "removed_h": ("新版少了", "removed in B"),
    "time": ("时间（秒）", "Time (s)"),
    "cut_s": ("切削", "cutting"), "rapid_s": ("快移", "rapid"), "tool_s": ("换刀", "tool change"), "total_s": ("合计", "total"),
    "line": ("行", "line"), "a": ("旧版", "A"), "b": ("新版", "B"), "dev": ("最大偏差", "max deviation"),
    "seg": ("段", "moves"), "first": ("第一处", "first at"),
}


def _t(k, lang):
    return TXT[k][0 if lang == "zh" else 1]


def _lines(span, lang):
    if not span:
        return "—"
    return f"{_t('line', lang)} {span[0]}" + (f"–{span[1]}" if span[1] != span[0] else "")


def _sv(v):
    kind, x = v
    return f"S{x:g}" if kind == "rpm" else f"G96 S{x:g}"


def report(res: dict, lang: str = "zh") -> str:
    L = [f"# {_t('title', lang)}", ""]
    L.append(_t("same", lang) if res["same"] else _t("diff", lang))
    L += ["", f"- {_t('ctl', lang)}：{res['controllers'][0]} / {res['controllers'][1]}" if lang == "zh" else
          f"- {_t('ctl', lang)}: {res['controllers'][0]} / {res['controllers'][1]}",
          f"- {_t('moves', lang)}：{res['moves'][0]} / {res['moves'][1]}" if lang == "zh" else
          f"- {_t('moves', lang)}: {res['moves'][0]} / {res['moves'][1]}"]
    sep = "：" if lang == "zh" else ": "
    tl = res["tools"]
    if tl["added"] or tl["removed"] or tl["a"] != tl["b"]:
        L += ["", f"## {_t('tools', lang)}", ""]
        if tl["added"]:
            L.append(f"- {_t('added', lang)}{sep}" + ", ".join(f"T{t}" for t in tl["added"]))
        if tl["removed"]:
            L.append(f"- {_t('removed', lang)}{sep}" + ", ".join(f"T{t}" for t in tl["removed"]))
        L.append(f"- {_t('order', lang)}{sep}" + " ".join(f"T{t}" for t in tl["a"]) + " → " + " ".join(f"T{t}" for t in tl["b"]))
    if res["speeds"]:
        L += ["", f"## {_t('speeds', lang)}", ""]
        for s in res["speeds"]:
            if s["what"] == "tool":
                ch = f"T{s['a']} → T{s['b']}"
            elif s["what"] == "feed":
                ch = f"F{s['a']:g} → F{s['b']:g}"
            else:
                ch = f"{_sv(s['a'])} → {_sv(s['b'])}"
            who = "" if s["what"] == "tool" else f"T{s['tool']} "
            L.append(f"- {who}{_t(s['what'], lang)} {ch}（{s['moves']} {_t('seg', lang)}；{_t('a', lang)} {_lines(s['lines_a'], lang)}，"
                     f"{_t('b', lang)} {_lines(s['lines_b'], lang)}）" if lang == "zh" else
                     f"- {who}{_t(s['what'], lang)} {ch} ({s['moves']} {_t('seg', lang)}; {_t('a', lang)} {_lines(s['lines_a'], lang)}, "
                     f"{_t('b', lang)} {_lines(s['lines_b'], lang)})")
    if res["hunks"]:
        L += ["", f"## {_t('path', lang)}", ""]
        for h in res["hunks"]:
            k = {"changed": "changed", "added": "added_h", "removed": "removed_h"}[h["kind"]]
            tools = " ".join(f"T{t}" for t in h["tools"])
            extra = ""
            if "max_dev_mm" in h:
                fa, fb = (" ".join(f"{a}{v:g}" for a, v in zip("XYZ", h["first"][w], strict=True)) for w in ("a", "b"))
                extra = (f"，{_t('dev', lang)} {h['max_dev_mm']:.3f} mm；{_t('first', lang)} {fa} → {fb}" if lang == "zh" else
                         f", {_t('dev', lang)} {h['max_dev_mm']:.3f} mm; {_t('first', lang)} {fa} → {fb}")
                if h.get("feeds"):
                    extra += ("；" if lang == "zh" else "; ") + _t("feed", lang) + " " + ", ".join(f"F{a:g} → F{b:g}" for a, b in h["feeds"])
            if lang == "zh":
                L.append(f"- {tools} {_t(k, lang)}：{_t('a', lang)} {_lines(h['lines_a'], lang)}（{h['moves_a']} 段） → "
                         f"{_t('b', lang)} {_lines(h['lines_b'], lang)}（{h['moves_b']} 段）{extra}")
            else:
                L.append(f"- {tools} {_t(k, lang)}: {_t('a', lang)} {_lines(h['lines_a'], lang)} ({h['moves_a']} moves) → "
                         f"{_t('b', lang)} {_lines(h['lines_b'], lang)} ({h['moves_b']} moves){extra}")
    L += ["", f"## {_t('time', lang)}", "", f"| | {_t('a', lang)} | {_t('b', lang)} | Δ |", "| --- | ---: | ---: | ---: |"]
    for k, v in res["time"].items():
        L.append(f"| {_t(k, lang)} | {v['a']:.1f} | {v['b']:.1f} | {v['diff']:+.1f} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    from analysis.cam import machines

    ap = argparse.ArgumentParser(description="问渠CAM 程序对比（两版程序差在哪）")
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--machine", required=True)
    ap.add_argument("--lang", default="zh", choices=("zh", "en"))
    a = ap.parse_args(argv)
    res = compare(Path(a.a).read_text(encoding="utf-8"), Path(a.b).read_text(encoding="utf-8"), machines.get(a.machine))
    sys.stdout.write(report(res, a.lang))
    return 0 if res["same"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
