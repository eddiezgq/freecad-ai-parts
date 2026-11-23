"""AI 提整机构型、代码初筛（ADR-0115 第 44.2 步）：从需求原话到通过初筛的整机方案（robot-concept/1，ADR-0116）。

流程（与 ADR-0100 的零件设计循环同一套做法）：
1. AI 读原话，列条件，每个数附原话引用；代码核对（引用在原话里、数在引用里且紧跟单位，pint 换算到标准单位）。原话没有的不补，AI 写成问题。
2. AI 提 1–3 个构型（robot-concept/1），说明理由并推荐一个；代码逐个初筛（analysis.robot）并按需求核对：
   自由度、安装方式、臂展（安装面上 r = 臂展的点要够得着且不在奇异位置）、关节模组复用；重复定位精度这时判不了（选件后按编码器与回差算），记待确认。
3. 一个都没通过，把每个构型没通过的项交回 AI 改，最多 4 轮。有通过的就停：采用 AI 推荐的那个（推荐的没通过就采用第一个通过的）。

“能在普通数控车铣上加工”“成本尽量低”这类要求代码判不了，记进“交给人看的要求”，不影响通过与否。
每一轮的提议原文、初筛结论都留下。AI 不给零件数据与质量；校核全由代码做。纯函数部分不联网；调用 AI 的客户端由调用方给。
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from analysis.robot import kinematics as K
from analysis.robot import screen
from assist.fea_draft import _in_statement, _value_with_unit

PROMPT_VERSION = "robot-design/2"            # /2：提示里给出一体化模组的装配要点（ADR-0115 44.3 之二）
DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_ROUNDS = 6                                  # 初筛与选件、装配、复核共用（ADR-0115 44.3 之二）
MAX_CANDIDATES = 3
ROOT = Path(__file__).resolve().parents[1]
RECORDINGS_DIR = ROOT / "tests" / "recordings" / "robot_design"
MOUNTS = {"桌面": "table", "台面": "table", "地面": "floor", "地上": "floor", "吊装": "ceiling", "顶装": "ceiling", "墙面": "wall",
          "壁装": "wall", "移动": "mobile"}

_V = {"type": "object", "properties": {"value": {"type": "number"}, "unit": {"type": "string"}, "quote": {"type": "string"}},
      "required": ["value", "quote"]}
_Q = {"type": "object", "properties": {"quote": {"type": "string"}}, "required": ["quote"]}
CONDITIONS_TOOL = {"name": "list_conditions", "description": "列出整机的设计条件（每个数附原话引用）", "input_schema": {
    "type": "object", "properties": {
        "kind": {"enum": ["serial_arm", "gantry", "mobile_base", "other"], "description": "需求说的是哪类机器人"},
        "kind_quote": {"type": "string"},
        "dof": {**_V, "description": "自由度（轴数），无单位"},
        "payload": {**_V, "description": "末端负载（kg）"},
        "reach": {**_V, "description": "臂展：工具点在安装面高度上能到的最远水平距离（mm）"},
        "repeatability": {**_V, "description": "重复定位精度（mm，写 ± 后面的数）"},
        "joint_speed": {**_V, "description": "关节最高角速度（原话的单位，如 °/s）"},
        "mount": {"type": "object", "properties": {"where": {"type": "string", "description": "原话里的安装位置词，如 桌面、地面、吊装"},
                                                   "quote": {"type": "string"}}, "required": ["where", "quote"]},
        "module_reuse": {**_Q, "description": "原话要求同一种关节模组重复使用时，给出引用"},
        "for_people": {"type": "array", "items": _Q, "description": "代码判不了、要交给人看的要求（如可加工、低成本、能自己装拆），各给原话引用"},
        "questions": {"type": "array", "items": {"type": "string"}, "description": "原话没说清、要问工程师的（不挡设计）"}},
    "required": ["kind", "kind_quote"]}}
PROPOSAL_TOOL = {"name": "propose_robots", "description": "提交 1–3 个整机构型并推荐一个", "input_schema": {
    "type": "object", "properties": {
        "candidates": {"type": "array", "minItems": 1, "maxItems": MAX_CANDIDATES,
                       "items": {"type": "object", "description": "robot-concept/1 格式的整机方案（字段见说明）"}},
        "recommend": {"type": "integer", "minimum": 0, "description": "推荐第几个（从 0 数）"},
        "reason": {"type": "string", "description": "推荐的理由；对比各构型的取舍"}},
    "required": ["candidates", "recommend", "reason"]}}

SYSTEM_CONDITIONS = """你在帮机器人工程师设计一台机器人。先把工程师原话里的设计条件列出来，程序会逐项核对。
规则：
1. 每个数都要给原话里的引用（照抄原话里连续的一段），数值和单位照原话写；原话没有的数不要补、不要估。
2. 代码判不了的要求（能不能加工、成本、好不好装拆）放进 for_people，各给引用。
3. 原话没说清的写进 questions。
必须调用一次工具 list_conditions。"""

SYSTEM_PROPOSAL = """你在为一台机器人提整机构型。给你已核对的设计条件，以及上一轮程序初筛的结论（如果有）。
请提 1–3 个不同思路的构型（不要照抄某个现有产品），每个写成 robot-concept/1 格式，推荐其中一个并说明取舍。

robot-concept/1 格式（单位 mm、°、s、kg；右手坐标系、z 向上）：
每个构型都是一个完整对象，必须有 format、name、kind、base、links、joints。
- format: "robot-concept/1"（每个构型都要写）；name；kind: serial_arm | gantry | mobile_base | other；reason：这个构型的理由
- base: {mount: table | floor | ceiling | wall | mobile, height_mm}
- links: [{id, length_mm, shape: tube | box | plate | profile | custom, section: {...}, material}]——不写质量（质量由程序在选件后算）
  section 按外形写：tube {od_mm 外径, id_mm 内径（空心时写，不是壁厚）}；box {width_mm, height_mm, wall_mm（空心时写壁厚）}；
  plate {width_mm, thickness_mm}；profile {width_mm, height_mm}
- joints: [{id, type: revolute | prismatic | wheel, parent: "base" 或杆件 id, child: 杆件 id, origin_mm: [x,y,z], axis: [x,y,z],
           range_deg（转动） | range_mm（移动） | radius_mm（轮子）, transmission: direct | reducer | belt | ballscrew | rack_pinion | belt_linear,
           ratio（reducer、belt）, lead_mm（ballscrew、rack_pinion、belt_linear）, module_group（同组的关节用同一种关节模组）}]
  id 一律用小写字母开头，只含小写字母、数字、下划线（如 j1、upper_arm）。每根杆件由一个关节带动；杆件坐标系原点在带动它的关节处、零位时与父件同向；origin_mm、axis 写零位时在父件坐标系里的值。
- end_effector: {type: gripper | vacuum | needle | tray | none | custom, parent: 杆件 id, offset_mm: 工具点在该杆件坐标系里的位置}
- tasks（可选）: [{type: "joint_move", name, from: {关节 id: 值}, to: {...}, move_s, dwell_s}
                 或 {type: "cartesian_move", name, from_mm: [x,y,z], to_mm: [x,y,z], move_s}]——type 必须写
- workspace（可选）: {points_mm: [[x,y,z], ...]}——基座坐标系，原点在安装面上、底座转轴处
程序会检查：格式；结构（树、引用）；自由度、安装方式与条件一致；臂展点（安装面上 x = 臂展、y = 0、z = 0）在关节行程内够得着且不在奇异位置；
工作空间点、直线动作沿途不在奇异位置（关节动作的起点终点不判）；
要求模组复用时至少两个关节同一个 module_group；末端负载的静力矩（只作参考）。
关节行程、传动方式、减速比是你的设计取值；不要编造零件型号与零件参数。
必须调用一次工具 propose_robots。"""


def conditions_request(statement: str, *, model: str = DEFAULT_MODEL) -> dict:
    return {"model": model, "prompt_version": PROMPT_VERSION, "system": SYSTEM_CONDITIONS,
            "user": f"工程师原话：\n{statement}", "tool": CONDITIONS_TOOL}


def check_conditions(ti: Any, statement: str) -> tuple[dict, list[str], list[str], list[dict]]:
    """核对 AI 列的条件 → (条件, 退回的项, 缺的项, 核对通过的引用)"""
    rej: list[str] = []
    miss: list[str] = []
    quotes: list[dict] = []
    cond: dict = {}
    if not isinstance(ti, dict):
        return cond, ["条件不是一个对象"], ["全部条件"], quotes
    if ti.get("kind") not in ("serial_arm", "gantry", "mobile_base", "other") or not _in_statement(ti.get("kind_quote"), statement):
        rej.append("机器人类型：没有原话依据")
    else:
        cond["kind"] = ti["kind"]
        quotes.append({"what": "机器人类型", "value": ti["kind"], "unit": "", "quote": ti["kind_quote"]})
    for key, field, what, unit in (("dof", None, "自由度", ""), ("payload", "mass_kg", "末端负载", "kg"),
                                   ("reach", "length_mm", "臂展", "mm"), ("repeatability", "length_mm", "重复定位精度", "mm"),
                                   ("joint_speed", "speed_rpm", "关节最高角速度", "rpm")):
        v = ti.get(key)
        if v is None:
            continue
        x, why = _value_with_unit(v, statement, field)
        if why:
            rej.append(f"{what}：{why}")
        else:
            cond[key] = x
            quotes.append({"what": what, "value": x, "unit": unit, "quote": v.get("quote")})
    m = ti.get("mount")
    if isinstance(m, dict):
        where = m.get("where") or ""
        hit = next((v for k, v in MOUNTS.items() if k in where), None)
        if hit is None or not _in_statement(m.get("quote"), statement) or where not in (m.get("quote") or ""):
            rej.append(f"安装位置“{where}”：引用不在原话里或不认识")
        else:
            cond["mount"] = hit
            quotes.append({"what": "安装位置", "value": where, "unit": "", "quote": m["quote"]})
    mr = ti.get("module_reuse")
    if isinstance(mr, dict):
        if _in_statement(mr.get("quote"), statement):
            cond["module_reuse"] = True
            quotes.append({"what": "关节模组复用", "value": "是", "unit": "", "quote": mr["quote"]})
        else:
            rej.append("关节模组复用：引用不在原话里")
    cond["for_people"] = [q["quote"] for q in ti.get("for_people") or [] if isinstance(q, dict) and _in_statement(q.get("quote"), statement)]
    if cond.get("kind") == "serial_arm":
        for key, what in (("dof", "自由度"), ("payload", "末端负载"), ("reach", "臂展")):
            if key not in cond:
                miss.append(what)
    return cond, rej, miss, quotes


def _cond_text(c: dict) -> str:
    names = {"kind": "机器人类型", "dof": "自由度", "payload": "末端负载 kg", "reach": "臂展 mm", "repeatability": "重复定位精度 ± mm", "joint_speed": "关节最高角速度 rpm",
             "mount": "安装", "module_reuse": "同一种关节模组重复使用", "for_people": "交给人看的要求（代码不判）"}
    return "\n".join(f"- {names.get(k, k)}：{v if not isinstance(v, list) else '；'.join(v)}" for k, v in c.items())


def _materials() -> str:
    from analysis.common import materials

    return "\n".join(f"- {m['id']}：{m['name']}" for m in materials.all_materials())


def proposal_request(cond: dict, history: list[dict], *, model: str = DEFAULT_MODEL) -> dict:
    prev = ""
    if history:
        last = history[-1]
        prev = (f"\n\n第 {len(history)} 轮你的构型：\n{json.dumps(last['proposal'], ensure_ascii=False, sort_keys=True)}\n"
                f"程序初筛的结论（每个构型没通过和待确认的项）：\n{last['feedback']}")
    return {"model": model, "prompt_version": PROMPT_VERSION, "system": SYSTEM_PROPOSAL,
            "user": (f"设计条件（已核对，标准单位）：\n{_cond_text(cond)}\n\n杆件材料只能从材料库里选（写 id）：\n{_materials()}"
                     f"\n\n{actuator_notes()}{prev}"),
            "tool": PROPOSAL_TOOL}


def actuator_notes() -> str:
    """零件库里有安装接口数据的一体化关节模组的装配要点（由库里的数据生成，给 AI 在第一轮就避开装不上的构型）"""
    from analysis.robot import fit
    from assist.robot_cad import min_spare_mm
    from engine.values import nominal
    from kb.library import JsonLibrary

    lib = JsonLibrary(Path(__file__).resolve().parents[1] / "data" / "library")
    comps = [c for c in lib.all() if c.get("category") == "smart_actuator" and fit.housing_geometry(c) is not None]
    if not comps:
        return "零件库里没有带安装接口数据的一体化关节模组。"
    g = fit.housing_geometry(comps[0])
    back = -min(pt["z_start_mm"] for pt in comps[0]["envelope"]["parts"])
    corner = (g["half_width"] ** 2 + g["axis_to_bottom"] ** 2) ** 0.5            # 壳体离轴线最远的角
    reach = fit.clevis_reach(fit.D_MAX_MM, 2 * g["half_width"], g, 2 * g["half_width"])
    rows = []
    for c in sorted(comps, key=lambda c: c["id"]):
        pp = c["params"]
        ts, n0, m = (nominal(pp.get(k)) for k in ("stall_torque_nm", "no_load_speed_rpm", "mass_kg"))
        rows.append(f"{c['model']}（堵转 {ts:g} N·m、空载 {n0:g} rpm、{m:g} kg）")
    return ("选件之后程序还会：按所选模组校核装不装得下、生成三维装配查干涉、按真实零件质量重算力矩与转速；不通过的项会交回给你。\n"
            f"零件库里有安装接口数据的一体化关节模组：{'；'.join(rows)}。力矩越大转速越低（直线关系），校核按安全系数 1.2。\n"
            f"它们外形相同：宽 {2 * g['half_width']:g} mm，输出轴离壳体底面 {g['axis_to_bottom']:g} mm；只有输出舵盘（和背面同轴的惰轮舵盘）会转，"
            "能固定的面（底面、两侧面）都与输出轴平行。所以：\n"
            f"1. 装在基座上的关节：输出舵盘在关节原点，壳体在它后面 {back:g} mm，原点要离安装面至少这么高（再加底座板厚）。\n"
            "2. 子杆沿关节轴转（轴转）时，父杆不能也沿这个轴（共线装不上）；要让壳体底面装在父杆上，轴线偏开。\n"
            f"3. 子杆垂直于关节轴（侧摆）时，子杆由跨在前后舵盘上的 U 形支架带动：U 底板离轴线至少 {corner:.0f} mm（行程越大越远），"
            f"杆件在 U 底板和下一壳体之间至少要留 {min_spare_mm():g} mm 放支架板、套管与管子。\n"
            "4. 杆件都做直管：下一关节的轴线要垂直于“本关节到它壳体中心”的连线。侧摆关节的原点就是壳体中心（前后两舵盘中间），"
            "子杆上下一关节的原点要在垂直于本关节轴线、过本关节原点的平面里（沿本关节轴线不要偏）；"
            "轴转关节的原点在输出舵盘端面，壳体中心在它后面 24.5 mm（只有轴转关节有这个偏移）。\n"
            f"5. 侧摆关节零位时子杆最好顺着父杆伸直；转角按“相对伸直”算，伸直位往两边最多约 {reach:.0f}°（父杆不比壳体宽时）。\n"
            "6. 肩、肘的重力力矩决定能不能选上：杆件越短越轻、重的东西越靠近肩部越好。")


def _item(name, status, value=None, limit=None, note=""):
    d = {"item": name, "status": status}
    if value is not None:
        d["value"] = value
    if limit is not None:
        d["limit"] = limit
    if note:
        d["note"] = note
    return d


def evaluate(concept: Any, cond: dict) -> dict:
    """一个构型：格式与结构 → 按需求的核对 → analysis.robot 初筛。返回 {"items", "overall", "screen"}"""
    if not isinstance(concept, dict):
        return {"items": [_item("格式", "fail", note="构型不是一个对象")], "overall": "fail"}
    c = copy.deepcopy(concept)
    items: list[dict] = []
    if "reach" in cond:                                  # 臂展点由程序按需求加：安装面上 x = 臂展
        pts = list(((c.get("workspace") or {}).get("points_mm")) or [])
        c["workspace"] = {"points_mm": [[cond["reach"], 0.0, 0.0]] + pts}
    rep = screen(c, cond.get("payload"))
    if rep["items"] and rep["items"][0]["item"] == "结构" and rep["items"][0]["status"] == "fail":
        return {"items": rep["items"], "overall": "fail", "screen": rep}
    m = K.build(c)
    if "kind" in cond and c.get("kind") != cond["kind"]:
        items.append(_item("机器人类型", "fail", c.get("kind"), cond["kind"]))
    if "dof" in cond and m.tool_link:
        n = len(K.chain(m))
        items.append(_item("自由度", "pass" if n == int(cond["dof"]) else "fail", n, int(cond["dof"])))
    if "mount" in cond:
        got = (c.get("base") or {}).get("mount")
        items.append(_item("安装方式", "pass" if got == cond["mount"] else "fail", got, cond["mount"]))
    if cond.get("module_reuse"):
        groups: dict[str, int] = {}
        for j in c.get("joints") or []:
            if j.get("module_group"):
                groups[j["module_group"]] = groups.get(j["module_group"], 0) + 1
        best = max(groups.values(), default=0)
        items.append(_item("关节模组复用", "pass" if best >= 2 else "fail", best, "≥ 2",
                           "同一个 module_group 的关节数" if best >= 2 else "没有两个关节用同一种模组"))
    from analysis.common import materials

    known = {x["id"] for x in materials.all_materials()}
    bad_mat = sorted({lk["material"] for lk in c.get("links") or [] if lk.get("material") and lk["material"] not in known})
    if bad_mat:
        items.append(_item("杆件材料", "fail", "、".join(bad_mat), None, "材料库里没有；请从给出的材料 id 里选"))
    if "repeatability" in cond:
        items.append(_item("重复定位精度", "unknown", None, f"± {cond['repeatability']:g} mm",
                           "选件后按编码器分辨率与减速器回差算（这一步判不了）"))
    for it in rep["items"]:
        if it["item"].startswith("工作空间点 1 ") and "reach" in cond:
            it = {**it, "item": f"臂展点（安装面上 r = {cond['reach']:g} mm）"}
        items.append(it)
    st = {i["status"] for i in items}
    return {"items": items, "overall": "fail" if "fail" in st else "unknown" if "unknown" in st else "pass", "screen": rep}


def _passes(ev: dict) -> bool:
    """没有不通过；待确认只剩“选件后才能判”的项"""
    return ev["overall"] != "fail" and all(i["status"] != "unknown" or "选件后" in i.get("note", "") for i in ev["items"])


def feedback(evs: list[dict]) -> str:
    out = []
    for k, ev in enumerate(evs):
        bad = [i for i in ev["items"] if i["status"] != "pass"]
        lines = [f"- [{'不通过' if i['status'] == 'fail' else '待确认'}] {i['item']}"
                 + (f"：{i['value']}" if "value" in i else "") + (f"（要求 {i['limit']}）" if i.get("limit") is not None else "")
                 + (f"；{i['note']}" if i.get("note") else "") for i in bad]
        out.append(f"构型 {k}：" + ("全部通过" if not bad else "\n" + "\n".join(lines)))
    return "\n".join(out)


def design(statement: str, client, *, model: str = DEFAULT_MODEL, max_rounds: int = MAX_ROUNDS, progress=None,
           after_screen=None) -> dict:
    """原话 → 条件 → 最多 max_rounds 轮构型与初筛。返回全部记录。
    after_screen(构型, 条件) → {"ok", "items", "summary"}：初筛通过、采用的构型再做选件与装配校核（ADR-0115 44.3 之二）；
    不通过就把没通过的项交回 AI，与初筛共用轮数"""
    def say(text):
        if progress is not None:
            progress(text, None, None)

    out: dict = {"part_type": "robot", "statement": statement, "rounds": [], "ai": []}
    say("AI 列设计条件")
    r = client.complete(conditions_request(statement, model=model))
    out["ai"].append({k: r[k] for k in ("id", "provider", "model", "simulated") if k in r})
    cond, rej, miss, quotes = check_conditions(r["tool_input"], statement)
    out.update(conditions=cond, rejected=rej, missing=miss, quotes=quotes,
               questions=[q for q in (r["tool_input"] or {}).get("questions") or [] if isinstance(q, str)])
    if miss or rej:
        out["status"] = "needs_input"
        return out
    for k in range(1, max_rounds + 1):
        say(f"第 {k} 轮（最多 {max_rounds} 轮）：AI 提构型")
        r = client.complete(proposal_request(cond, out["rounds"], model=model))
        out["ai"].append({k_: r[k_] for k_ in ("id", "provider", "model", "simulated") if k_ in r})
        prop = r["tool_input"] if isinstance(r["tool_input"], dict) else {}
        cands = (prop.get("candidates") or [])[:MAX_CANDIDATES]
        say(f"第 {k} 轮：初筛 {len(cands)} 个构型（工作空间、奇异、需求）")
        evs = [evaluate(c, cond) for c in cands] or [{"items": [_item("构型", "fail", note="没有提交构型")], "overall": "fail"}]
        rd = {"proposal": prop, "evaluations": [{k_: v for k_, v in ev.items() if k_ != "screen"} for ev in evs],
              "feedback": feedback(evs)}
        out["rounds"].append(rd)
        ok = [i for i, ev in enumerate(evs) if _passes(ev)]
        if ok:
            rec = prop.get("recommend")
            pick = rec if isinstance(rec, int) and rec in ok else ok[0]
            if after_screen is not None:
                say(f"第 {k} 轮：构型 {pick} 选件与装配校核")
                bc = after_screen(cands[pick], cond)
                rd["build"] = {"candidate": pick, "ok": bc["ok"], "items": bc["items"], "summary": bc.get("summary", "")}
                if not bc["ok"]:
                    rd["feedback"] += (f"\n\n构型 {pick} 初筛通过，但按它选件、装配后没通过（下一轮请据此改构型）：\n"
                                       + "\n".join(f"- [不通过] {x}" for x in bc["items"])
                                       + (f"\n选件与模组外形：{bc['summary']}" if bc.get("summary") else ""))
                    continue
            out.update(status="pass", chosen_round=k, chosen_candidate=pick, chosen=cands[pick],
                       chosen_note="" if pick == rec else f"AI 推荐的构型 {rec} 没通过初筛，采用第一个通过的构型 {pick}")
            return out
    out["status"] = "stuck"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m assist.robot_design", description="AI 提整机构型、代码初筛（ADR-0115 44.2）")
    ap.add_argument("statement", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path)
    mode.add_argument("--record", action="store_true")
    ap.add_argument("--provider", choices=("claude", "deepseek"))
    ap.add_argument("--screen-only", action="store_true", help="只做初筛，不做选件与装配校核")
    a = ap.parse_args(argv)
    if a.record:
        from assist.llm import GatewayClient

        client = GatewayClient(a.provider, record_dir=RECORDINGS_DIR)
        model = client.model
    else:
        from ingest.llm_extract import RecordedClient

        client, model = RecordedClient(a.replay or RECORDINGS_DIR), DEFAULT_MODEL
    after = None
    if not a.screen_only:
        from assist.robot_build import build_check

        after = build_check
    res = design(a.statement.read_text(encoding="utf-8"), client, model=model, after_screen=after)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"结论：{res['status']}；{len(res['rounds'])} 轮", file=sys.stderr)
    for q in res.get("missing", []) + res.get("rejected", []):
        print(f"  缺 / 退回：{q}", file=sys.stderr)
    for k, rd in enumerate(res["rounds"], 1):
        names = [c.get("name") for c in rd["proposal"].get("candidates") or [] if isinstance(c, dict)]
        print(f"第 {k} 轮：{names}\n{rd['feedback']}", file=sys.stderr)
    if res.get("status") == "pass":
        print(f"采用：第 {res['chosen_round']} 轮构型 {res['chosen_candidate']}（{res['chosen'].get('name')}）"
              + (f"；{res['chosen_note']}" if res.get("chosen_note") else ""), file=sys.stderr)
    return 0 if res.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
