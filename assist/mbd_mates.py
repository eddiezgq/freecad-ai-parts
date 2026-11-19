"""AI 起草运动副（ADR-0097 D5b，补充十一）：候选全部由 analysis/mbd/mates.py 的几何规则找出，
LLM 只在候选里挑、定类型（只能是候选给的类型或备选）、起中文名、选机架、说明理由；不能新造运动副、不能改位置和方向。
结果是“草稿”，要人确认后才建成 Assembly 运动副。没有 LLM 时用规则草稿（全收、机架取体积最大的零件）。
"""

from __future__ import annotations

import copy
import json

PROMPT_VERSION = "mbd-mates/1"
DEFAULT_MODEL = "claude-sonnet-5-5"
TOOL_NAME = "draft_joints"
SYSTEM_PROMPT = (
    "你是机械工程师，帮人把一个刚导入的装配体起草成多体动力学模型的运动副。"
    "程序已经从几何面找出了全部候选运动副（同轴的轴孔、同心的球窝、贴合的导轨面），每个候选都有几何证据。"
    "你只能在这些候选里挑：决定收不收、类型用候选给的还是它的备选、起一个工程上好懂的中文名；再从零件里选一个机架（固定不动的）。"
    "不能新造候选，不能改位置和方向。拿不准的候选要收下并在理由里说明请人核对，不要静默丢掉。"
)
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "ground": {"type": "string", "description": "机架零件 id"},
        "accept": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "type": {"type": "string"}, "name": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["id", "type", "name"]}},
        "reject": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["id", "reason"]}},
        "explanation": {"type": "string"},
    },
    "required": ["ground", "accept", "explanation"],
}


def build_request(parts: list[dict], found: dict, *, model: str = DEFAULT_MODEL, note: str = "") -> dict:
    plist = "\n".join(f"- {p['id']}：{p.get('label') or p['id']}，体积 {p.get('volume_mm3', 0):.0f} mm³" for p in parts)
    clist = "\n".join(f"- {c['id']}：{c['part1']} ↔ {c['part2']}，{c['type']}"
                      + (f"（备选 {'、'.join(c['alternatives'])}）" if c["alternatives"] else "")
                      + f"；证据：{c['evidence']}" for c in found["candidates"])
    user = (f"零件：\n{plist}\n\n候选运动副：\n{clist or '（没有）'}\n\n"
            f"没连上任何候选的零件：{'、'.join(found['unconnected']) or '无'}\n"
            + (f"\n使用者说明：{note.strip()}\n" if note.strip() else ""))
    return {"model": model, "prompt_version": PROMPT_VERSION, "system": SYSTEM_PROMPT, "user": user,
            "tool": {"name": TOOL_NAME, "description": "提交运动副草稿", "input_schema": TOOL_SCHEMA}}


class FakeClient:
    """测试用：返回给定的工具输入（模拟 LLM）"""

    def __init__(self, tool_input: dict):
        self.tool_input = tool_input

    def complete(self, request: dict) -> dict:
        return {"id": "fake", "tool_input": copy.deepcopy(self.tool_input), "simulated": True}


def rule_draft(parts: list[dict], found: dict) -> dict:
    from assist.mbd_report import JOINT_ZH

    label = {p["id"]: p.get("label") or p["id"] for p in parts}
    return {"ground": found["ground"]["part"] if found["ground"] else None,
            "accept": [{"id": c["id"], "type": c["type"],
                        "name": f"{JOINT_ZH.get(c['type'], c['type'])}副：{label.get(c['part1'], c['part1'])}–{label.get(c['part2'], c['part2'])}"}
                       for c in found["candidates"]],
            "notes": [], "by": "规则（没有用 AI）", "explanation": "全部候选按几何规则收下；机架取体积最大的零件"}


def draft(parts: list[dict], found: dict, client=None, *, note: str = "", model: str = DEFAULT_MODEL) -> dict:
    """返回草稿 {"ground", "accept": [{"id", "type", "name"}], "notes": [...], "by", "explanation"}。
    AI 的回答逐条核对：不认识的候选、不允许的类型、不存在的机架都不采用，并在 notes 里写明；漏掉没表态的候选按规则收下。"""
    if client is None:
        return rule_draft(parts, found)
    model = getattr(client, "model", None) or model          # 经网关时用那一家的模型名（录制按请求哈希存，两家各录各的）
    req = build_request(parts, found, model=model, note=note)
    resp = client.complete(req)
    ti = resp.get("tool_input") or {}
    by_id = {c["id"]: c for c in found["candidates"]}
    pids = {p["id"] for p in parts}
    notes, accept, seen = [], [], set()
    for a in ti.get("accept") or []:
        c = by_id.get(a.get("id"))
        if c is None:
            notes.append(f"AI 收了不存在的候选 {a.get('id')}，不采用")
            continue
        typ = a.get("type") or c["type"]
        if typ != c["type"] and typ not in c["alternatives"]:
            notes.append(f"AI 把 {c['id']} 改成 {typ}，几何上只能是 {[c['type'], *c['alternatives']]}，按 {c['type']} 起草")
            typ = c["type"]
        seen.add(c["id"])
        accept.append({"id": c["id"], "type": typ, "name": str(a.get("name") or c["id"])[:60], "reason": a.get("reason", "")})
    rejected = {r.get("id"): r.get("reason", "") for r in ti.get("reject") or [] if r.get("id") in by_id}
    for cid, c in by_id.items():
        if cid in seen:
            continue
        if cid in rejected:
            notes.append(f"AI 不收 {cid}（{c['part1']}–{c['part2']}）：{rejected[cid] or '没说理由'}；请确认")
        else:
            notes.append(f"AI 没对 {cid} 表态，按规则收下")
            accept.append({"id": cid, "type": c["type"], "name": cid})
    ground = ti.get("ground")
    if ground not in pids:
        notes.append(f"AI 选的机架 {ground} 不是装配里的零件，按体积最大的零件起草")
        ground = found["ground"]["part"] if found["ground"] else None
    return {"ground": ground, "accept": accept, "notes": notes, "explanation": ti.get("explanation", ""),
            "by": f"AI（{resp.get('provider', '模拟' if resp.get('simulated') else '')} {resp.get('model', '')}，"
                  f"提示词 {PROMPT_VERSION}，响应 {resp.get('id', '')}）"}


def as_json(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, indent=1)
