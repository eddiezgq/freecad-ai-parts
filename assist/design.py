"""零件库 + AI 自主设计（ADR-0100 42.2）：从需求原话到通过校核的阶梯轴方案。

流程：
1. AI 读原话，列设计条件，每个数附原话引用；代码核对（引用在原话里、数在引用里且紧跟单位，pint 换算到标准单位；
   材料要在材料库、原话里有；方向只认“向下 / 向上”这类原话）。原话没有的条件不补，AI 写成问题。
2. AI 按条件和库里的轴承提方案（轴段用途、自由段尺寸、选哪个轴承、圆角）；代码核对并校核（assist.shaft_design）。
3. 没通过的项（带数字和要求）交回 AI 改，最多 4 轮。全部通过，或只剩库里缺数据造成的“待确认”就停；4 轮还不通过就停，列出卡住的项。

每一轮的提议原文、校核结论都留下。AI 不给载荷、不给轴承位尺寸；校核全由代码做。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from assist import shaft_design as SD
from assist.fea_draft import _in_statement, _material_ok, _value_with_unit

PROMPT_VERSION = "shaft-design/1"
DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_ROUNDS = 4
ROOT = Path(__file__).resolve().parents[1]
RECORDINGS_DIR = ROOT / "tests" / "recordings" / "design"

_V = {"type": "object", "properties": {"value": {"type": "number"}, "unit": {"type": "string"}, "quote": {"type": "string"}},
      "required": ["value", "quote"]}
CONDITIONS_TOOL = {"name": "list_conditions", "description": "列出设计条件（每个数附原话引用）", "input_schema": {
    "type": "object", "properties": {
        "speeds": {"type": "array", "items": _V, "description": "要校核的转速（最高转速、提速评估转速）"},
        "bearing_centers": {"type": "array", "items": _V, "description": "轴承中心的轴向位置 z"},
        "crank_slider": {"type": "object", "properties": {
            "z": _V, "crank_radius": _V, "rod_length": _V, "reciprocating_mass": _V, "balance_ratio": _V}},
        "process_power": {"type": "object", "properties": {"power": _V, "z": _V}},
        "forces": {"type": "array", "items": {"type": "object", "properties": {
            "z": _V, "magnitude": _V, "direction": {"enum": ["+y", "-y", "+x", "-x"]}, "direction_quote": {"type": "string"}},
            "required": ["z", "magnitude", "direction", "direction_quote"]}},
        "drive_z": _V,
        "masses": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "z": _V, "mass": _V},
                                              "required": ["name", "z", "mass"]}},
        "material": {"type": "object", "properties": {"id": {"type": "string"}, "quote": {"type": "string"}}},
        "surface": {"type": "object", "properties": {"finish": {"enum": ["ground", "machined"]}, "quote": {"type": "string"}}},
        "required_safety": _V, "critical_ratio": _V, "bearing_life": _V, "max_length": _V,
        "questions": {"type": "array", "items": {"type": "string"}}},
    "required": ["speeds", "bearing_centers"]}}
PROPOSAL_TOOL = {"name": "propose_shaft", "description": "提交阶梯轴方案", "input_schema": {
    "type": "object", "properties": {
        "segments": {"type": "array", "items": {"type": "object", "properties": {
            "role": {"enum": list(SD.ROLES)}, "diameter_mm": {"type": "number"}, "length_mm": {"type": "number"},
            "bearing": {"type": "string"}, "fillet_mm": {"type": "number"}}, "required": ["role"]}},
        "reason": {"type": "string", "description": "为什么这样排、改了什么（中文）"}},
    "required": ["segments", "reason"]}}

SYSTEM_CONDITIONS = """你在帮机械工程师设计一根阶梯轴。先把工程师原话里的设计条件列出来，程序会逐项核对。
1. 每个数都要附 quote：从原话里逐字摘一段（不改字、不翻译），数和单位都要在这段里；unit 照原话写。
2. 原话没有的条件不要补、不要估，写进 questions。
3. 坐标：z 沿轴线；y 沿针杆铅垂向上；x 水平。力的方向写 +y / -y / +x / -x，并给出原话里说方向的那段 direction_quote。
4. 材料 id 从清单里选，并给出原话里说材料的那段 quote；表面状态 ground（磨削）或 machined（车削）并附 quote。
必须调用一次工具 list_conditions。"""
SYSTEM_PROPOSAL = """你在设计一根阶梯轴。给你已核对的设计条件、零件库里可用的轴承，以及上一轮程序校核的结论（如果有）。
1. 你只排结构、选轴承、给自由段的直径和长度、给每个台阶的过渡圆角；轴承位的直径和长度由程序按所选轴承取，不用你给。
2. 轴段从 z = 0 起首尾相接；轴承位中心要正好在要求的轴承中心；装在轴上的零件、载荷的位置都要落在轴上。
3. 轴承要能从某一端套进去（途经的轴段不比轴承内径粗），并靠一段更粗的轴肩定位。
4. 强度、临界转速、轴承寿命由程序算；上一轮没通过的项，按给出的数字和要求改，说清改了什么。
5. 直径、长度取整到 0.5 mm 或常用尺寸；不要编造条件里没有的东西。
必须调用一次工具 propose_shaft。"""


# ---------------------------------------------------------------- 条件


def conditions_request(statement: str, *, model: str = DEFAULT_MODEL) -> dict:
    from analysis.common import materials

    mats = "\n".join(f"- {m['id']}：{m['name']}" for m in materials.all_materials())
    return {"model": model, "prompt_version": PROMPT_VERSION, "system": SYSTEM_CONDITIONS,
            "user": f"材料清单：\n{mats}\n\n工程师原话：\n{statement}", "tool": CONDITIONS_TOOL}


def _val(v, statement, field, rejected, what):
    x, why = _value_with_unit(v, statement, field)
    if why:
        rejected.append(f"{what}：{why}")
    return x


def check_conditions(ti: Any, statement: str) -> tuple[dict, list[str], list[str]]:
    """核对 AI 列的条件 → (shaft_design 用的条件, 退回的项, 要问工程师的)"""
    from analysis.common import materials

    rej: list[str] = []
    if not isinstance(ti, dict):
        return {}, ["AI 的输出不是对象"], []
    c: dict = {}
    c["speeds_rpm"] = [x for x in (_val(v, statement, "speed_rpm", rej, "转速") for v in ti.get("speeds") or []) if x]
    c["bearing_centers_mm"] = sorted(x for x in (_val(v, statement, "z_mm", rej, "轴承中心") for v in ti.get("bearing_centers") or [])
                                     if x is not None)
    loads, masses = [], []
    cs = ti.get("crank_slider")
    if isinstance(cs, dict) and cs:
        f = {k: _val(cs.get(k), statement, fld, rej, f"曲柄滑块 {k}") for k, fld in (
            ("z", "z_mm"), ("crank_radius", "r_mm"), ("rod_length", "l_mm"), ("reciprocating_mass", "mass_kg"))}
        bal = _val(cs.get("balance_ratio"), statement, None, rej, "平衡率") if cs.get("balance_ratio") else 0.0
        if None not in f.values() and bal is not None:
            loads.append({"type": "crank_slider", "z_mm": f["z"], "crank_radius_mm": f["crank_radius"], "rod_length_mm": f["rod_length"],
                          "reciprocating_mass_kg": f["reciprocating_mass"], "balance_ratio": bal})
    pp = ti.get("process_power")
    if isinstance(pp, dict) and pp:
        p, z = _val(pp.get("power"), statement, "power_w", rej, "功率"), _val(pp.get("z"), statement, "z_mm", rej, "功率作用位置")
        if p is not None and z is not None:
            loads.append({"type": "torque_load", "z_mm": z, "power_w": p})
    for f in ti.get("forces") or []:
        if not isinstance(f, dict):
            continue
        z, mag = _val(f.get("z"), statement, "z_mm", rej, "力的位置"), _val(f.get("magnitude"), statement, "force_n", rej, "力的大小")
        dq, d = f.get("direction_quote"), f.get("direction")
        word_ok = _in_statement(dq, statement) and (
            (d == "-y" and re.search(r"向下|下|down", dq or "", re.IGNORECASE)) or (d == "+y" and re.search(r"向上|上|up", dq or "", re.IGNORECASE)))
        if not word_ok:
            rej.append(f"力的方向 {d!r}：原话“{dq}”里没有说清（只认向上 / 向下）")
            continue
        if z is not None and mag is not None:
            sign = -1 if d.startswith("-") else 1
            loads.append({"type": "force", "z_mm": z, "fx_n": 0.0, "fy_n": sign * mag} if d.endswith("y")
                         else {"type": "force", "z_mm": z, "fx_n": sign * mag, "fy_n": 0.0})
    for m in ti.get("masses") or []:
        if not isinstance(m, dict):
            continue
        z, kg = _val(m.get("z"), statement, "z_mm", rej, f"质量 {m.get('name')} 的位置"), _val(m.get("mass"), statement, "mass_kg", rej, f"质量 {m.get('name')}")
        if z is not None and kg is not None:
            masses.append({"name": str(m.get("name") or "")[:40], "z_mm": z, "mass_kg": kg})
    c["loads"], c["masses"] = loads, masses
    dz = ti.get("drive_z")
    if dz:
        x = _val(dz, statement, "z_mm", rej, "动力输入位置")
        if x is not None:
            c["drive_z_mm"] = x
    mat = ti.get("material") or {}
    if isinstance(mat, dict) and mat.get("id"):
        try:
            m = materials.get(mat["id"])
        except materials.MissingData:
            rej.append(f"材料 {mat['id']!r} 不在材料库")
        else:
            if _in_statement(mat.get("quote"), statement) and _material_ok(m["id"], m["name"], mat["quote"]):
                c["material"] = m["id"]
            else:
                rej.append(f"材料 {mat['id']}：原话“{mat.get('quote')}”里没有这个材料")
    sf = ti.get("surface") or {}
    if isinstance(sf, dict) and sf.get("finish") in ("ground", "machined"):
        words = {"ground": r"磨|ground|grind", "machined": r"车|铣|machin|turned"}[sf["finish"]]
        if _in_statement(sf.get("quote"), statement) and re.search(words, sf["quote"], re.IGNORECASE):
            c["surface"] = sf["finish"]
        else:
            rej.append(f"表面状态 {sf['finish']}：原话“{sf.get('quote')}”里没有")
    for key, field, name in (("required_safety", None, "安全系数要求"), ("critical_ratio", None, "临界转速倍数"),
                             ("bearing_life", "life_h", "轴承寿命要求"), ("max_length", "length_mm", "轴长上限")):
        if ti.get(key):
            x = _val(ti[key], statement, field, rej, name)
            if x is not None:
                c[{"bearing_life": "bearing_life_h", "max_length": "max_length_mm"}.get(key, key)] = x
    missing = []
    for need, what in (("material", "材料"), ("speeds_rpm", "转速")):
        if not c.get(need):
            missing.append(f"原话里没有核对得上的{what}")
    if len(c["bearing_centers_mm"]) != 2:
        missing.append("要两个轴承中心的位置")
    return c, rej, missing


def ai_questions(ti: Any) -> list[str]:
    """AI 提的问题：交给工程师，但不挡设计（缺了算不了的条件由代码判断，见 check_conditions）"""
    return [q.strip() for q in (ti.get("questions") if isinstance(ti, dict) else None) or [] if isinstance(q, str) and q.strip()]


ASSUMPTIONS = ["轴承寿命按基本额定寿命 L10（可靠度 90 %）、载荷系数 1、当量载荷取一转之内径向支反力的立方平均",
               "原话没有给的载荷（如凸轮、偏心轮的工作力）不计；挑线、送布机构的力要另给",
               "强度按无限寿命安全系数，不计起停冲击"]


# ---------------------------------------------------------------- 方案


def bearing_table(bearings: list[dict]) -> str:
    rows = ["| 组件 id | 内径 d | 外径 D | 宽 B | 额定动载荷 C (N) | da min | ra max |", "|---|---|---|---|---|---|---|"]
    for b in bearings:
        def pv(k, src=b["params"]):
            v = (src.get(k) or {}).get("value")
            return "—" if v is None else f"{v:g}"
        ports = {p["id"]: p for p in b["ports"]}
        d = ports["inner"]["spec"]["diameter_mm"]["value"]
        big = ports["outer"]["spec"]["diameter_mm"]["value"]
        rows.append(f"| {b['id']} | {d:g} | {big:g} | {pv('width_mm')} | {pv('dynamic_load_rating_n')} | "
                    f"{pv('abutment_shaft_min_mm')} | {pv('fillet_max_mm')} |")
    return "\n".join(rows)


def _cond_text(c: dict) -> str:
    return json.dumps(c, ensure_ascii=False, indent=1)


def proposal_request(cond: dict, bearings: list[dict], history: list[dict], *, model: str = DEFAULT_MODEL) -> dict:
    prev = ""
    if history:
        last = history[-1]
        prev = (f"\n\n第 {len(history)} 轮你的方案：\n{json.dumps(last['proposal'], ensure_ascii=False, sort_keys=True)}\n"
                f"程序校核的结论（没通过和待确认的项）：\n{last['feedback']}")
    user = (f"设计条件（已核对，标准单位：mm、N、kg、r/min、W、h）：\n{_cond_text(cond)}\n\n"
            f"零件库里可用的轴承：\n{bearing_table(bearings)}{prev}")
    return {"model": model, "prompt_version": PROMPT_VERSION, "system": SYSTEM_PROPOSAL, "user": user, "tool": PROPOSAL_TOOL}


def _done(report: dict) -> bool:
    """全部通过，或只剩库里缺数据造成的待确认（这些要人补数据，再改方案也没用）"""
    st = [i for i in report["items"] if i["status"] != "pass"]
    return not any(i["status"] == "fail" for i in st) and all("零件库" in i.get("note", "") for i in st)


def extra_checks(report: dict, cond: dict) -> None:
    """条件里的轴长上限"""
    lim = cond.get("max_length_mm")
    if lim is not None:
        length = report["segments"][-1]["z1"]
        report["items"].append(SD._item("轴的总长", "pass" if length <= lim + 1e-9 else "fail", round(length, 3), lim))
        if length > lim + 1e-9:
            report["overall"] = "fail"


def design(statement: str, client, bearings: list[dict], get: Callable[[str], dict | None], *, model: str = DEFAULT_MODEL,
           kt: Callable | None = None, max_rounds: int = MAX_ROUNDS) -> dict:
    """原话 → 条件 → 最多 max_rounds 轮方案与校核。返回全部记录"""
    r = client.complete(conditions_request(statement, model=model))
    cond, rejected, missing = check_conditions(r["tool_input"], statement)
    out: dict = {"statement": statement, "conditions": cond, "rejected": rejected, "missing": missing,
                 "questions": ai_questions(r["tool_input"]), "assumptions": ASSUMPTIONS, "rounds": [],
                 "ai": [{k: r[k] for k in ("id", "provider", "model", "simulated") if k in r}]}
    if missing:
        out["status"] = "needs_input"
        return out
    for _k in range(max_rounds):
        req = proposal_request(cond, bearings, out["rounds"], model=model)
        r = client.complete(req)
        out["ai"].append({k: r[k] for k in ("id", "provider", "model", "simulated") if k in r})
        prop = r["tool_input"]
        try:
            rep = SD.evaluate(prop, cond, get, kt=kt)
        except SD.ProposalInvalid as ex:
            rep = {"items": [SD._item("方案格式", "fail", note=str(ex))], "notes": [], "overall": "fail", "segments": []}
        else:
            extra_checks(rep, cond)
        fb = SD.feedback(rep)
        out["rounds"].append({"proposal": prop, "overall": rep["overall"], "feedback": fb,
                              "items": rep["items"], "segments": rep.get("segments"), "mass_kg": rep.get("mass_kg")})
        if rep.get("segments") and _done(rep):
            out["status"] = "pass" if rep["overall"] == "pass" else "pass_pending_data"
            return out
    out["status"] = "stuck"
    return out


# ---------------------------------------------------------------- 命令行


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m assist.design", description="AI 设计阶梯轴、代码校核（ADR-0100）")
    ap.add_argument("statement", type=Path, help="需求原话（文本文件）")
    ap.add_argument("-o", "--out", type=Path)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path)
    mode.add_argument("--record", action="store_true")
    ap.add_argument("--provider", choices=("claude", "deepseek"))
    ap.add_argument("--model-dir", type=Path, help="通过后生成三维模型、回读核对、二维图与 BOM 的目录（42.3）")
    a = ap.parse_args(argv)
    from kb.library import JsonLibrary

    lib = JsonLibrary(ROOT / "data" / "library")
    bearings = [c for c in lib.all() if c["category"] == "bearing"]
    if a.record:
        from assist.llm import GatewayClient

        client = GatewayClient(a.provider, record_dir=RECORDINGS_DIR)
        model = client.model
    else:
        from ingest.llm_extract import RecordedClient

        client, model = RecordedClient(a.replay or RECORDINGS_DIR), DEFAULT_MODEL
    res = design(a.statement.read_text(encoding="utf-8"), client, bearings, lib.get, model=model)
    text = json.dumps(res, ensure_ascii=False, indent=1, default=lambda x: None if isinstance(x, float) and not math.isfinite(x) else str(x))
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    print(f"结论：{res['status']}；{len(res['rounds'])} 轮", file=sys.stderr)
    for q in res.get("missing", []) + res.get("rejected", []):
        print(f"  缺 / 退回：{q}", file=sys.stderr)
    for q in res.get("questions", []):
        print(f"  AI 的问题（待工程师答，不挡设计）：{q}", file=sys.stderr)
    for k, rd in enumerate(res["rounds"], 1):
        segs = "、".join(f"Ø{s['d']:g}×{s['L']:g}" for s in rd.get("segments") or [])
        print(f"第 {k} 轮：{rd['overall']}  {segs}\n{rd['feedback']}", file=sys.stderr)
    if a.model_dir and res.get("status", "").startswith("pass"):
        from assist import shaft_model

        g = shaft_model.generate(res, a.model_dir, lib.get)
        print(f"模型回读：{g['readback']}" + ("；" + "；".join(g["problems"]) if g["problems"] else "")
              + (f"；质量 {g['mass_kg']} kg；已出 {a.model_dir}/shaft.step、drawing.svg、bom.json" if g.get("delivered") else "；不交付"),
              file=sys.stderr)
        if not g.get("delivered"):
            return 1
    return 0 if res.get("status", "").startswith("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
