"""问渠CAM：AI 起草工艺（ADR-0104 第 2 节“AI 起草”、第 7 节数据规则；C1：车削、2.5 轴铣）。

分工：
- 程序定工序：按零件（阶梯轴的段、槽、螺纹、内孔；铣削的型腔、外轮廓、槽、孔）列出要做的工序，每道工序按几何条件从企业刀具库里筛出能用的刀
  （种类对、尺寸合适：型腔刀径不大于转角圆角的两倍、槽刀不宽于槽、螺纹刀螺距相同、钻头直径等于孔径……）。
- AI 只在候选里挑刀、在刀具样本给的范围里定切削参数、说明理由。
- 程序逐项核对 AI 的回答：不是候选的刀、超出样本范围的参数、样本没给范围的参数，一律不采用，改用规则值并写进 notes。
- 规则值：每道工序取候选里最合适的刀（铣刀取允许的最大直径），参数取样本范围的中间值，切深取样本最大切深与教学缺省值中小的那个；
  样本没有这个材料组的参数时用教学示意值，标“待确认”。
结果是一份可直接交给 `analysis.cam.run` 的设置，加上工艺卡要的工序表（每道工序：刀、参数、理由、核对结论）。
"""

from __future__ import annotations

import copy
import json

from analysis.cam import tools as TL

PROMPT_VERSION = "cam-process/1"
DEFAULT_MODEL = "claude-sonnet-5-5"
TOOL_NAME = "draft_process"
SYSTEM_PROMPT = (
    "你是数控工艺员，帮人给一个零件起草加工工艺。程序已经列出了工序，并且按几何条件从企业刀具库里筛好了每道工序能用的刀，"
    "每把刀附有刀具样本给的切削参数范围。你只能：给每道工序从候选里挑一把刀；在这把刀的样本范围内定切削速度 vc、进给（车削每转进给 f，"
    "铣削每齿进给 fz）、切深 ap（不超过样本最大切深）；铣型腔还要给切宽占刀径的比例 stepover（不超过样本最大切宽 ÷ 刀径）；说明理由。"
    "不能用候选以外的刀，不能超出样本范围。粗加工偏效率、精加工偏质量；拿不准的写进理由请人核对。"
)
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "ops": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "tool": {"type": "string"},
            "vc": {"type": "number"}, "f": {"type": "number"}, "fz": {"type": "number"}, "ap": {"type": "number"},
            "stepover": {"type": "number"}, "reason": {"type": "string"}}, "required": ["id", "tool", "vc"]}},
        "explanation": {"type": "string"},
    },
    "required": ["ops", "explanation"],
}
# 教学示意值（同 analysis.cam.DEFAULT_CUT；样本没有该材料组时才用，标“待确认”）
TEACH = {"rough": {"vc": 120.0, "f": 0.3, "ap": 2.5}, "finish": {"vc": 150.0, "f": 0.15},
         "groove": {"vc": 80.0, "f": 0.05}, "thread": {"vc": 60.0}, "drill": {"vc": 20.0, "f": 0.12},
         "bore": {"vc": 100.0, "f": 0.15, "ap": 1.0}, "pocket": {"vc": 100.0, "fz": 0.04, "ap": 5.0, "stepover": 0.45},
         "contour": {"vc": 100.0, "fz": 0.04, "ap": 5.0}, "slot": {"vc": 25.0, "fz": 0.03, "ap": 1.0},
         "holes": {"vc": 20.0, "f": 0.12}, "face_groove": {"vc": 80.0, "f": 0.04}, "part": {"vc": 80.0, "f": 0.05},
         "cbore": {"vc": 100.0, "fz": 0.03, "ap": 2.0}, "csink": {"vc": 60.0, "f": 0.05}, "tap": {"vc": 10.0}}
FEED = {"rough": "f", "finish": "f", "groove": "f", "thread": None, "drill": "f", "bore": "f",
        "pocket": "fz", "contour": "fz", "slot": "fz", "holes": "f", "face_groove": "f", "part": "f",
        "cbore": "fz", "csink": "f", "tap": None}
HAS_AP = {"rough", "bore", "pocket", "contour", "slot", "cbore"}
TEACH_Z = {"pocket": 4, "contour": 4, "slot": 2}   # 刀具库没写刃数时的教学示意值（标“待确认”）


class ProcessError(ValueError):
    pass


# ---------------- 工序与候选刀 ----------------

def _cands(lib, kinds, ok=lambda t: True):
    return [t for t in lib["tools"] if t["kind"] in kinds and ok(t)]


def operations(part: dict, lib: dict) -> list[dict]:
    """part：analysis.cam.run 的 turn 或 mill 设置（不含切削参数）。→ [{id, kind, title, cands: [刀具], geom}]"""
    ops = []
    if part["mode"] == "turn":
        ops += [{"id": "rough", "kind": "rough", "title": "粗车外圆", "cands": _cands(lib, {"turn"})},
                {"id": "finish", "kind": "finish", "title": "精车外圆", "cands": _cands(lib, {"turn"})}]
        for i, g in enumerate(part.get("grooves") or [], 1):
            w = float(g["width"])
            ops.append({"id": f"groove{i}", "kind": "groove", "title": f"切槽 宽 {w:g}", "geom": {"width": w},
                        "cands": _cands(lib, {"groove"}, lambda t, w=w: (t.get("insert") or {}).get("width_mm", 1e9) <= w + 1e-9)})
        for i, th in enumerate(part.get("threads") or [], 1):
            p = float(th["pitch"])
            ops.append({"id": f"thread{i}", "kind": "thread", "title": f"车螺纹 M{float(th['d']):g}×{p:g}", "geom": {"pitch": p},
                        "cands": _cands(lib, {"thread_turn"}, lambda t, p=p: abs(t.get("pitch_mm", -1) - p) < 1e-9)})
        for i, fg in enumerate(part.get("face_grooves") or [], 1):
            w = (float(fg["d_out"]) - float(fg["d_in"])) / 2
            ops.append({"id": f"face_groove{i}", "kind": "face_groove", "title": f"端面槽 宽 {w:g}", "geom": {"width": w},
                        "cands": _cands(lib, {"groove"}, lambda t, w=w: (t.get("insert") or {}).get("width_mm", 1e9) <= w + 1e-9)})
        if part.get("parting"):
            ops.append({"id": "part", "kind": "part", "title": "切断", "cands": _cands(lib, {"groove"})})
        b = part.get("bore")
        if b:
            dmin = min(float(d) for d, _ in b["segments"])
            ops.append({"id": "drill", "kind": "drill", "title": "钻孔", "geom": {"max_d": dmin},
                        "cands": _cands(lib, {"drill"}, lambda t, dmin=dmin: t.get("diameter_mm", 1e9) <= dmin - 1.0)})
            ops.append({"id": "bore", "kind": "bore", "title": "镗孔", "cands": _cands(lib, {"bore"})})
    elif part["mode"] == "mill":
        for i, f in enumerate(part.get("features") or [], 1):
            k = f["type"]
            if k == "pocket":
                x0, y0, x1, y1 = f["rect"]
                lim = min(x1 - x0, y1 - y0) / 2
                cr = float(f.get("corner_r", 0))
                if cr > 0:
                    lim = min(lim, 2 * cr)
                ops.append({"id": f"f{i}", "kind": "pocket", "title": "铣型腔", "geom": {"max_d": lim, "feature": i - 1},
                            "cands": _cands(lib, {"flat_endmill", "bull_endmill"}, lambda t, lim=lim: t.get("diameter_mm", 1e9) <= lim + 1e-9)})
            elif k == "contour":
                ops.append({"id": f"f{i}", "kind": "contour", "title": "铣外轮廓", "geom": {"feature": i - 1},
                            "cands": _cands(lib, {"flat_endmill", "bull_endmill"}, lambda t: "diameter_mm" in t)})
            elif k == "slot":
                w = float(f["width"])
                ops.append({"id": f"f{i}", "kind": "slot", "title": f"铣槽 宽 {w:g}", "geom": {"width": w, "feature": i - 1},
                            "cands": _cands(lib, {"flat_endmill"}, lambda t, w=w: abs(t.get("diameter_mm", -1) - w) < 1e-9)})
            elif k == "holes":
                d = float(f["d"])
                ops.append({"id": f"f{i}", "kind": "holes", "title": f"钻孔 Ø{d:g}", "geom": {"d": d, "feature": i - 1},
                            "cands": _cands(lib, {"drill"}, lambda t, d=d: abs(t.get("diameter_mm", -1) - d) < 1e-9)})
            else:
                raise ProcessError(f"第 {i} 个特征类型 {k!r} 不认识")
    else:
        raise ProcessError("AI 起草工艺只做车削（turn）和铣削（mill）")
    return ops


def _mid(rng):
    if not rng:
        return None
    lo, hi = rng.get("min"), rng.get("max")
    if lo is None or hi is None:
        return lo if hi is None else hi
    return round((lo + hi) / 2, 4)


def _nose(t):
    return (t.get("insert") or {}).get("nose_radius_mm", 0.0)


def _rule_pick(op):
    """铣刀、钻头取允许的最大直径；粗车取刀尖圆角最大的（刀尖强），精车取最小的（表面好、让刀小）"""
    c = op["cands"]
    if not c:
        return None
    if op["kind"] in ("pocket", "contour", "drill"):
        return max(c, key=lambda t: t.get("diameter_mm", 0))
    if op["kind"] == "rough":
        return max(c, key=_nose)
    if op["kind"] == "finish":
        return min(c, key=_nose)
    return c[0]


def _rule_params(op, tool, iso):
    """规则值：样本中间值；切深取样本最大与教学缺省的小者；样本没有这个材料组时用教学示意值（unknown）"""
    teach = dict(TEACH[op["kind"]])
    c = TL.cutting_for(tool, iso) if tool else None
    if c is None:
        return teach, "unknown"
    out = {"vc": _mid(c.get("vc_m_min"))}
    fk = FEED[op["kind"]]
    if fk:
        out[fk] = _mid(c.get("fz_mm" if fk == "fz" else "f_mm_rev"))
        if out[fk] is None:
            out[fk] = teach[fk]
    if op["kind"] in HAS_AP:
        ap_t = teach["ap"]
        out["ap"] = min(ap_t, c["ap_max_mm"]) if "ap_max_mm" in c else ap_t
    if op["kind"] == "pocket":
        d = tool["diameter_mm"]
        out["stepover"] = min(teach["stepover"], c["ae_max_mm"] / d) if "ae_max_mm" in c else teach["stepover"]
    return out, "pass"


def _check(op, tool, iso, p):
    """AI 给的参数逐项核对；返回 (采用的参数, notes)"""
    rule, _ = _rule_params(op, tool, iso)
    fk = FEED[op["kind"]]
    keep, notes = {}, []
    items = {"vc": p.get("vc")}
    if fk:
        items[fk] = p.get(fk)
    if op["kind"] in HAS_AP:
        items["ap"] = p.get("ap")
    for k, v in items.items():
        if v is None:
            keep[k] = rule[k]
            continue
        kw = {"vc": "vc", "f": "f", "fz": "fz", "ap": "ap"}[k]
        res = TL.check_cutting(tool, iso, **{kw: float(v)})
        verdict = TL.verdict(res)
        if verdict == "pass":
            keep[k] = float(v)
        else:
            keep[k] = rule[k]
            why = res[0]["text"] if res else "样本没给范围"
            notes.append(f"{op['title']}：AI 给的 {k}={v:g} 不采用（{why}），用规则值 {rule[k]:g}")
    if op["kind"] == "pocket":
        so = p.get("stepover")
        c = TL.cutting_for(tool, iso) or {}
        cap = c["ae_max_mm"] / tool["diameter_mm"] if "ae_max_mm" in c else None
        if so is None or cap is None or so <= 0 or so > cap + 1e-12:
            keep["stepover"] = rule["stepover"]
            if so is not None:
                notes.append(f"{op['title']}：AI 给的 stepover={so:g} 不采用（样本最大切宽 ÷ 刀径 = {cap if cap is None else round(cap, 4)}），"
                             f"用 {rule['stepover']:g}")
        else:
            keep["stepover"] = float(so)
    return keep, notes


# ---------------- 起草 ----------------

def build_request(part, ops, iso, *, model=DEFAULT_MODEL, note=""):
    def rng(c, k):
        r = c.get(k)
        return f"{r.get('min', '')}–{r.get('max', '')}" if r else "—"

    lines = []
    for op in ops:
        lines.append(f"工序 {op['id']}：{op['title']}")
        for t in op["cands"]:
            c = TL.cutting_for(t, iso)
            spec = (f"vc {rng(c, 'vc_m_min')} m/min，f {rng(c, 'f_mm_rev')} mm/r，fz {rng(c, 'fz_mm')} mm，"
                    f"ap ≤ {c.get('ap_max_mm', '—')} mm，ae ≤ {c.get('ae_max_mm', '—')} mm") if c else f"样本没有 {iso} 组参数"
            dia = f" Ø{t['diameter_mm']:g}" if "diameter_mm" in t else ""
            lines.append(f"  - 刀 {t['id']}（{t.get('name', t['kind'])}{dia}）：{spec}")
        if not op["cands"]:
            lines.append("  - （刀具库里没有能用的刀）")
    user = (f"零件：{part.get('item') or '零件'}，加工方式 {part['mode']}，材料组 ISO {iso}"
            + (f"（{part.get('kienzle')}）" if part.get("kienzle") else "") + "\n\n" + "\n".join(lines)
            + (f"\n\n使用者说明：{note.strip()}" if note.strip() else ""))
    return {"model": model, "prompt_version": PROMPT_VERSION, "system": SYSTEM_PROMPT, "user": user,
            "tool": {"name": TOOL_NAME, "description": "提交工艺草稿", "input_schema": TOOL_SCHEMA}}


class FakeClient:
    """测试用：返回给定的工具输入（模拟 LLM）"""

    def __init__(self, tool_input: dict):
        self.tool_input = tool_input

    def complete(self, request: dict) -> dict:
        self.request = request
        return {"id": "fake", "tool_input": copy.deepcopy(self.tool_input), "simulated": True}


def draft(part: dict, iso: str, lib: dict | None = None, client=None, *, note: str = "", model: str = DEFAULT_MODEL,
          tool_lengths: dict | None = None) -> dict:
    """→ {"setup": 交给 analysis.cam.run 的设置, "card": [工序表], "notes": [...], "by", "explanation"}"""
    lib = lib or TL.load()
    ops = operations(part, lib)
    missing = [op["title"] for op in ops if not op["cands"]]
    if missing:
        raise ProcessError("刀具库里没有能用的刀：" + "、".join(missing) + "——先在刀具库里加刀")
    by_op = {}
    notes: list[str] = []
    ai = {}
    by = "规则（没有用 AI）"
    explanation = "每道工序取候选里最合适的刀，参数取刀具样本范围的中间值"
    if client is not None:
        model = getattr(client, "model", None) or model
        resp = client.complete(build_request(part, ops, iso, model=model, note=note))
        ti = resp.get("tool_input") or {}
        ai = {o.get("id"): o for o in ti.get("ops") or []}
        explanation = ti.get("explanation", "")
        by = (f"AI（{resp.get('provider', '模拟' if resp.get('simulated') else '')} {resp.get('model', '')}，"
              f"提示词 {PROMPT_VERSION}，响应 {resp.get('id', '')}）")
        for k in set(ai) - {op["id"] for op in ops}:
            notes.append(f"AI 回答里的工序 {k} 不存在，不采用")
    for op in ops:
        a = ai.get(op["id"])
        cand = {t["id"]: t for t in op["cands"]}
        tool, reason = None, ""
        if a is not None:
            tool = cand.get(a.get("tool"))
            if tool is None:
                notes.append(f"{op['title']}：AI 选的刀 {a.get('tool')} 不在候选里（{', '.join(cand)}），按规则选")
            reason = str(a.get("reason") or "")[:200]
        elif client is not None:
            notes.append(f"{op['title']}：AI 没给，按规则起草")
        tool = tool or _rule_pick(op)
        params, status = _rule_params(op, tool, iso)
        if a is not None and status == "pass":
            params, n2 = _check(op, tool, iso, a)
            notes += n2
        elif status == "unknown":
            notes.append(f"{op['title']}：刀 {tool['id']} 的样本没有 {iso} 组的参数，用教学示意值，待确认")
        by_op[op["id"]] = {"op": op, "tool": tool, "params": params, "status": status, "reason": reason}
    setup = _setup(part, by_op, tool_lengths or {}, notes)
    card = [{"id": v["op"]["id"], "title": v["op"]["title"], "tool": v["tool"]["id"], "tool_name": v["tool"].get("name", ""),
             "params": v["params"], "status": v["status"], "reason": v["reason"]} for v in by_op.values()]
    return {"setup": setup, "card": card, "notes": notes, "by": by, "explanation": explanation, "iso_group": iso}


def _setup(part, by_op, lengths, notes):
    s = copy.deepcopy(part)
    ms = s.setdefault("machine_sim", {})
    mtools = ms.setdefault("tools", {})

    def T(n, tool):
        e = {"tool": tool["id"]}
        if tool["id"] in lengths:
            e["length_mm"] = float(lengths[tool["id"]])
        mtools[str(n)] = e

    if part["mode"] == "turn":
        r, f = by_op["rough"], by_op["finish"]
        s["cut"] = {"rough": {k: r["params"][k] for k in ("vc", "f", "ap")}, "finish": {k: f["params"][k] for k in ("vc", "f")}}
        T(1, r["tool"])
        T(2, f["tool"])
        for i, g in enumerate(s.get("grooves") or [], 1):
            v = by_op[f"groove{i}"]
            g["cut"] = {k: v["params"][k] for k in ("vc", "f")}
            g["tool_w"] = float((v["tool"].get("insert") or {}).get("width_mm", g["width"]))
            T(3, v["tool"])
        for i, th in enumerate(s.get("threads") or [], 1):
            v = by_op[f"thread{i}"]
            th["cut"] = {"vc": v["params"]["vc"]}
            T(7 if th.get("internal") else 4, v["tool"])
        for i, fg in enumerate(s.get("face_grooves") or [], 1):
            v = by_op[f"face_groove{i}"]
            fg["cut"] = {k: v["params"][k] for k in ("vc", "f")}
            fg["tool_w"] = float((v["tool"].get("insert") or {}).get("width_mm", (fg["d_out"] - fg["d_in"]) / 2))
            T(9, v["tool"])
        if s.get("parting"):
            v = by_op["part"]
            s["parting"]["cut"] = {k: v["params"][k] for k in ("vc", "f")}
            s["parting"].setdefault("tool_w", float((v["tool"].get("insert") or {}).get("width_mm", 3.0)))
            T(8, v["tool"])
        if s.get("bore"):
            d, b = by_op["drill"], by_op["bore"]
            s["bore"]["drill_d"] = float(d["tool"]["diameter_mm"])
            s["bore"]["drill_cut"] = {"vc": d["params"]["vc"], "f": d["params"]["f"], "peck": 0.0}
            s["bore"]["cut"] = {"vc": b["params"]["vc"], "f": b["params"]["f"], "ap": b["params"]["ap"], "f_finish": b["params"]["f"]}
            T(5, d["tool"])
            T(6, b["tool"])
    else:
        for i, f in enumerate(s["features"], 1):
            v = by_op[f"f{i}"]
            t = v["tool"]
            f["tool_d"] = float(t["diameter_mm"])
            p = v["params"]
            if f["type"] == "holes":
                f["cut"] = {"vc": p["vc"], "f": p["f"]}
            else:
                z = t.get("flutes")
                if z is None:
                    z = TEACH_Z[f["type"]]
                    notes.append(f"{v['op']['title']}：刀 {t['id']} 没写刃数，按教学示意值 {z} 刃算进给，待确认")
                c = {"vc": p["vc"], "fz": p["fz"], "z": int(z), "ap": p["ap"]}
                if f["type"] == "pocket":
                    c["stepover"] = p["stepover"]
                f["cut"] = c
            T(i, t)
    return s


def as_json(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, indent=1)
