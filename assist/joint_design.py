"""AI 设计机器人关节输出空心轴（ADR-0100 42.5 第 5 步）：原话 → 条件（AI 列、代码核对）→ 载荷（代码由动力学算）→
方案（AI 选轴承、内孔、法兰圆角）→ 校核（analysis.shaft.joint）→ 没通过交回 AI 改；全部通过后再给 AI 一轮“减重”。

与平缝机上轴（assist/design.py）同一套分工与录制：AI 不给载荷数字、不给轴承尺寸；每个条件的数都要在原话里有引用。
“越轻越好”：通过后把质量和每项的余量交回 AI，AI 可以提一个更轻的方案；代码校核也全部通过、且确实更轻才采用，否则保留原方案。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from assist.fea_draft import _in_statement, _material_ok, _value_with_unit

PROMPT_VERSION = "joint-shaft/1"
DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_ROUNDS = 4                     # 改到合格最多 4 轮
LIGHTER_ROUNDS = 3                 # 通过之后减重另给最多 3 轮（ADR-0100 42.2 之五，与阶梯轴同一规则）
ROOT = Path(__file__).resolve().parents[1]
RECORDINGS_DIR = ROOT / "tests" / "recordings" / "joint_design"
EXAMPLE = ROOT / "examples" / "ai-design" / "cobot-j2" / "requirement.txt"

_V = {"type": "object", "properties": {"value": {"type": "number"}, "unit": {"type": "string"}, "quote": {"type": "string"}},
      "required": ["value", "quote"]}
_POSE = {"type": "object", "properties": {"j2": _V, "j3": _V}, "required": ["j2", "j3"]}
CONDITIONS_TOOL = {"name": "list_conditions", "description": "列出关节轴的设计条件（每个数附原话引用）", "input_schema": {
    "type": "object", "properties": {
        "reducer_model": {"type": "object", "properties": {"model": {"type": "string"}, "quote": {"type": "string"}}},
        "links": {"type": "array", "items": {"type": "object", "properties": {"length": _V, "mass": _V}, "required": ["length", "mass"]},
                  "description": "大臂、小臂（按顺序）"},
        "tip_masses": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "mass": _V}},
                       "description": "挂在小臂末端的质量（负载、腕部模组）"},
        "pose_a": _POSE, "pose_b": _POSE, "move_time": _V, "dwell_time": _V,
        "reach": _V, "displacement_budget": _V,
        "material": {"type": "object", "properties": {"id": {"type": "string"}, "quote": {"type": "string"}}},
        "surface": {"type": "object", "properties": {"finish": {"enum": ["ground", "machined"]}, "quote": {"type": "string"}}},
        "required_safety": _V, "bearing_life": _V,
        "questions": {"type": "array", "items": {"type": "string"}}},
    "required": ["links", "pose_a", "pose_b", "move_time"]}}
PROPOSAL_TOOL = {"name": "propose_joint_shaft", "description": "提交关节空心轴方案", "input_schema": {
    "type": "object", "properties": {
        "bearing": {"type": "string", "description": "零件库里的深沟球轴承组件 id（一对，同型号）"},
        "bore_mm": {"type": "number", "description": "贯通内孔直径"},
        "fillet_mm": {"type": "number", "description": "减速器法兰与轴承位之间台阶的圆角"},
        "reason": {"type": "string", "description": "为什么这样选、改了什么（中文）"}},
    "required": ["bearing", "bore_mm", "fillet_mm", "reason"]}}

SYSTEM_CONDITIONS = """你在帮机械工程师设计机器人肩关节 J2 的输出空心轴。先把工程师原话里的设计条件列出来，程序会逐项核对。
1. 每个数都要附 quote：从原话里逐字摘一段（不改字、不翻译），数和单位都要在这段里；unit 照原话写。
2. 原话没有的条件不要补、不要估，写进 questions。力矩、力由程序按机械臂的长度、质量和节拍算，你不用给。
3. 姿态的角度按原话的正负写；材料 id 从清单里选，并给出原话里说材料的那段 quote；表面状态 ground（磨削）或 machined（车削）并附 quote。
必须调用一次工具 list_conditions。"""
SYSTEM_PROPOSAL = """你在设计机器人肩关节 J2 的输出空心轴。结构已定：减速器法兰（比轴承位大 20 mm）— 两个同型号深沟球轴承装在连续的轴承位上、
中间隔套 — 外端花键传转矩给大臂 — 最外端圆螺母压紧；两个轴承都从大臂一端装入；内孔贯通。
1. 你只选三样：轴承（零件库里的组件 id，轴承位直径和宽度程序按它取）、内孔直径、法兰台阶的圆角；其余尺寸程序按规则算。
2. 这根轴按刚度设计：扭转使末端偏移，要不超过预算；强度通常富余很多。轴承位越大、内孔越小越刚，但越重。
3. 刚度、强度、花键挤压、疲劳、轴承寿命都由程序算；上一轮没通过的项，按给出的数字和要求改，说清改了什么。
4. 内孔取整到 1 mm，圆角取 0.5 或 1 mm 这样的常用值；不要编造条件里没有的东西。
必须调用一次工具 propose_joint_shaft。"""
LIGHTER = """全部校核已通过。原话要求“在满足要求的前提下越轻越好”。现在的质量 {mass:.3f} kg；各项余量如下（数值取两位有效数字 / 要求）：
{margins}
如果你认为还能更轻（例如换小一号的轴承或加大内孔）而仍全部满足，就提一个更轻的方案；如果认为已经是最轻的，原样交回现在的方案并说明理由。"""


def _bearings_text(bearings: list[dict]) -> str:
    rows = ["| 组件 id | 内径 d | 外径 D | 宽 B | 额定动载荷 C (N) |", "|---|---|---|---|---|"]
    for b in bearings:
        ports = {p["id"]: p for p in b["ports"]}

        def pv(k, src=b["params"]):
            v = (src.get(k) or {}).get("value")
            return "—" if v is None else f"{v:g}"
        rows.append(f"| {b['id']} | {ports['inner']['spec']['diameter_mm']['value']:g} | "
                    f"{ports['outer']['spec']['diameter_mm']['value']:g} | {pv('width_mm')} | {pv('dynamic_load_rating_n')} |")
    return "\n".join(rows)


def conditions_request(statement: str, *, model: str = DEFAULT_MODEL) -> dict:
    from analysis.common import materials

    mats = "\n".join(f"- {m['id']}：{m['name']}" for m in materials.all_materials())
    return {"model": model, "prompt_version": PROMPT_VERSION, "system": SYSTEM_CONDITIONS,
            "user": f"材料清单：\n{mats}\n\n工程师原话：\n{statement}", "tool": CONDITIONS_TOOL}


def check_conditions(ti: Any, statement: str, get: Callable[[str], dict | None], reducers: list[dict]) -> tuple[dict, list[str], list[str]]:
    """核对 AI 列的条件 → (条件, 退回的项, 缺的)"""
    from analysis.common import materials

    rej: list[str] = []
    if not isinstance(ti, dict):
        return {}, ["AI 的输出不是对象"], []

    def val(v, field, what):
        x, why = _value_with_unit(v, statement, field)
        if why:
            rej.append(f"{what}：{why}")
        return x

    c: dict = {}
    links = []
    for i, lk in enumerate(ti.get("links") or []):
        if isinstance(lk, dict):
            length, mass = val(lk.get("length"), "length_mm", f"第 {i + 1} 根杆的长度"), val(lk.get("mass"), "mass_kg", f"第 {i + 1} 根杆的质量")
            if length is not None and mass is not None:
                links.append({"length_mm": length, "mass_kg": mass})
    tip = 0.0
    for m in ti.get("tip_masses") or []:
        if isinstance(m, dict):
            x = val(m.get("mass"), "mass_kg", f"末端质量 {m.get('name')}")
            tip += x or 0.0
    poses = {}
    for key in ("pose_a", "pose_b"):
        p = ti.get(key) or {}
        pj = {j: val(p.get(j), "pose_deg", f"{key} {j}") for j in ("j2", "j3")} if isinstance(p, dict) else {}
        if pj and None not in pj.values():
            poses[key] = pj
    for key, field, name in (("move_time", "move_s", "运动时间"), ("dwell_time", "dwell_s", "停顿时间"), ("reach", "reach_mm", "工作半径"),
                             ("displacement_budget", "budget_mm", "末端偏移预算"), ("required_safety", None, "安全系数要求"),
                             ("bearing_life", "bearing_life_h", "轴承寿命要求")):
        if ti.get(key):
            x = val(ti[key], field, name)
            if x is not None:
                c[{"move_time": "move_s", "dwell_time": "dwell_s", "reach": "reach_mm", "displacement_budget": "budget_mm",
                   "bearing_life": "bearing_life_h"}.get(key, key)] = x
    c.setdefault("dwell_s", 0.0)
    c["arm"] = {"base_height_mm": 0.0, "links": links, "payload_kg": tip}
    c.update(poses)
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
        import re

        words = {"ground": r"磨|ground|grind", "machined": r"车|铣|machin|turned"}[sf["finish"]]
        if _in_statement(sf.get("quote"), statement) and re.search(words, sf["quote"], re.IGNORECASE):
            c["surface"] = sf["finish"]
        else:
            rej.append(f"表面状态 {sf['finish']}：原话“{sf.get('quote')}”里没有")
    rm = ti.get("reducer_model") or {}
    if isinstance(rm, dict) and rm.get("model"):
        hit = next((r for r in reducers if str(r.get("model", "")).upper() == str(rm["model"]).upper()), None)
        if hit is None:
            rej.append(f"减速器 {rm['model']} 不在零件库")
        elif not _in_statement(rm.get("quote"), statement) or str(rm["model"]).upper() not in str(rm.get("quote", "")).upper():
            rej.append(f"减速器 {rm['model']}：原话“{rm.get('quote')}”里没有这个型号")
        else:
            c["reducer"] = hit["id"]
            t_stop = ((hit.get("params") or {}).get("momentary_max_torque_nm") or {}).get("value")
            if t_stop is not None:
                c["T_stop_nm"] = float(t_stop)
    missing = []
    if len(links) != 2:
        missing.append("要大臂、小臂两根杆的长度和质量")
    for k, what in (("pose_a", "姿态 A"), ("pose_b", "姿态 B"), ("move_s", "运动时间"), ("material", "材料")):
        if k not in c:
            missing.append(f"原话里没有核对得上的{what}")
    return c, rej, missing


def loads(cond: dict) -> dict:
    """由动力学算 J2 的载荷条件（代码算，不让 AI 给）"""
    from analysis.shaft import joint_loads

    cyc = joint_loads.cycle(cond["arm"], cond["pose_a"], cond["pose_b"], cond["move_s"], cond.get("dwell_s", 0.0))
    return joint_loads.conditions(cyc)


def proposal_request(cond: dict, bearings: list[dict], history: list[dict], *, model: str = DEFAULT_MODEL,
                     lighter: str | None = None) -> dict:
    shown = {k: v for k, v in cond.items() if k != "F_series_n"}
    prev = ""
    if history:
        last = history[-1]
        prev = (f"\n\n第 {len(history)} 轮你的方案：\n{json.dumps(last['proposal'], ensure_ascii=False, sort_keys=True)}\n"
                f"程序校核的结论（没通过和待确认的项）：\n{last['feedback']}")
    if lighter:
        prev += "\n\n" + lighter
    user = (f"设计条件（已核对；力矩、力、转速由程序从动力学算出；标准单位 mm、N、N·m、kg、r/min、h）：\n"
            f"{json.dumps(shown, ensure_ascii=False, indent=1, sort_keys=True)}\n\n零件库里可用的深沟球轴承：\n{_bearings_text(bearings)}{prev}")
    return {"model": model, "prompt_version": PROMPT_VERSION, "system": SYSTEM_PROPOSAL, "user": user, "tool": PROPOSAL_TOOL}


def _margins(rep: dict) -> str:
    from assist.design import _approx

    return "\n".join(f"- {i['item']}：约 {_approx(i.get('value'))} / {i.get('limit')}" for i in rep["items"] if i.get("limit") is not None)


def _same(a: dict, b: dict) -> bool:
    """同一个方案（说明文字不算）"""
    return {k: v for k, v in a.items() if k != "reason"} == {k: v for k, v in b.items() if k != "reason"}


def design(statement: str, client, bearings: list[dict], reducers: list[dict], get: Callable[[str], dict | None], *,
           model: str = DEFAULT_MODEL, kt: Callable | None = None, max_rounds: int = MAX_ROUNDS,
           lighter_rounds: int = LIGHTER_ROUNDS, progress: Callable[[str, int | None, int | None], None] | None = None) -> dict:
    from analysis.shaft import joint as J
    from assist import shaft_design as SD

    say = progress or (lambda *_: None)
    say("AI 列设计条件", None, None)
    r = client.complete(conditions_request(statement, model=model))
    cond, rejected, missing = check_conditions(r["tool_input"], statement, get, reducers)
    questions = [q for q in (r["tool_input"].get("questions") if isinstance(r["tool_input"], dict) else []) or [] if isinstance(q, str)]
    out: dict = {"part_type": "joint_shaft", "statement": statement, "conditions": cond, "rejected": rejected, "missing": missing,
                 "questions": questions, "rounds": [], "ai": [{k: r[k] for k in ("id", "provider", "model", "simulated") if k in r}]}
    if missing:
        out["status"] = "needs_input"
        return out
    say("动力学算一个搬运节拍的载荷", None, None)
    cond.update(loads(cond))
    best = None
    lighter_text = None
    fix_left, light_left, k = max_rounds, lighter_rounds, 0
    while True:
        if best is None:
            if fix_left == 0:
                break
            fix_left -= 1
        else:
            if light_left == 0:
                break
            light_left -= 1
        k += 1
        head = f"第 {k} 轮：AI 试更轻的方案（减重最多 {lighter_rounds} 轮）" if lighter_text else f"第 {k} 轮（最多 {max_rounds} 轮）：AI 提方案"
        say(head, None, None)
        req = proposal_request(cond, bearings, out["rounds"], model=model, lighter=lighter_text)
        r = client.complete(req)
        out["ai"].append({k_: r[k_] for k_ in ("id", "provider", "model", "simulated") if k_ in r})
        prop = r["tool_input"]
        last = out["rounds"][-1]["proposal"] if out["rounds"] else None
        if isinstance(prop, dict) and isinstance(last, dict) and _same(prop, last):
            out["rounds"].append({**out["rounds"][-1], "proposal": prop, "unchanged": True})
            break                                                # AI 不再改方案
        say(f"第 {k} 轮：校核（刚度、强度、花键、疲劳、轴承）", None, None)
        try:
            rep = J.evaluate(prop, cond, get, kt=kt)
        except J.JointProposalInvalid as ex:
            rep = {"items": [SD._item("方案格式", "fail", note=str(ex))], "overall": "fail", "segments": []}
        rd = {"proposal": prop, "overall": rep["overall"], "feedback": SD.feedback(rep), "items": rep["items"],
              "segments": rep.get("segments"), "mass_kg": rep.get("mass_kg"), "theta_rad": rep.get("theta_rad"),
              "delta_mm": rep.get("delta_mm"), "lighter_round": lighter_text is not None}
        out["rounds"].append(rd)
        if rep["overall"] == "pass":
            if best is None or (rd["mass_kg"] or 1e9) < (best["mass_kg"] or 1e9) - 1e-6:
                best = rd
                lighter_text = LIGHTER.format(mass=rd["mass_kg"] or 0.0, margins=_margins(rep))
                continue                                         # 通过且更轻：接着要更轻
            break                                                # 通过但没更轻：保留更轻的那轮
        # 没通过：按校核结论再改（减重阶段算在减重轮数里）
    if best is not None:
        out["status"] = "pass"
        out["chosen_round"] = out["rounds"].index(best) + 1
    else:
        out["status"] = "stuck"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m assist.joint_design", description="AI 设计机器人关节空心轴、代码校核（ADR-0100 42.5）")
    ap.add_argument("statement", type=Path, nargs="?", default=EXAMPLE)
    ap.add_argument("-o", "--out", type=Path)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path)
    mode.add_argument("--record", action="store_true")
    ap.add_argument("--provider", choices=("claude", "deepseek"))
    a = ap.parse_args(argv)
    from kb.library import JsonLibrary

    lib = JsonLibrary(ROOT / "data" / "library")
    bearings, reducers = lib.all("bearing"), lib.all("reducer")
    if a.record:
        from assist.llm import GatewayClient

        client = GatewayClient(a.provider, record_dir=RECORDINGS_DIR)
        model = client.model
    else:
        from ingest.llm_extract import RecordedClient

        client, model = RecordedClient(a.replay or RECORDINGS_DIR), DEFAULT_MODEL
    res = design(a.statement.read_text(encoding="utf-8"), client, bearings, reducers, lib.get, model=model)
    text = json.dumps(res, ensure_ascii=False, indent=1, default=lambda x: None)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    print(f"结论：{res['status']}；{len(res['rounds'])} 轮" + (f"；采用第 {res['chosen_round']} 轮" if res.get("chosen_round") else ""),
          file=sys.stderr)
    for q in res.get("missing", []) + res.get("rejected", []):
        print(f"  缺 / 退回：{q}", file=sys.stderr)
    for k, rd in enumerate(res["rounds"], 1):
        p = rd["proposal"] if isinstance(rd["proposal"], dict) else {}
        print(f"第 {k} 轮：{rd['overall']}  {p.get('bearing')} 内孔 {p.get('bore_mm')} 圆角 {p.get('fillet_mm')}  质量 {rd.get('mass_kg')}"
              f"  偏移 {rd.get('delta_mm')}\n{rd['feedback']}", file=sys.stderr)
    return 0 if res.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
