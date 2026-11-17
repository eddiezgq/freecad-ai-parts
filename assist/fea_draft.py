"""AI 起草有限元算例（ADR-0093 补充十一第 4 步）：AI 只提议，代码逐项核对，人确认。

流程：
1. 程序识别各零件的特征（`assist.features`，确定性），编号 F1、F2……给 AI 看；
2. AI 用一次工具调用提议：实体与材料、支承、载荷、连接、分析步、工况与组合，每项写明用哪几个特征、数值和单位、原话里的引用；
3. 代码核对（本模块，纯函数，不联网）——不过的不采用，列进“未采用及原因”，缺的改成追问：
   - 引用必须是原话里的一段；数值以完整数字紧跟单位出现在引用里，单位经 `ingest.units` 换算；
   - 特征存在、属于该实体，类型合乎这项（轴承载荷、圆柱支承、扭矩要轴段或孔，对称要平面；圆角、倒角不加载）；轴线取特征的轴线；
   - 方向必须在原话里按零件坐标写明（“-z”“y 轴负向”等），与 AI 写的一致；只说“向下”不算（零件文件看不出哪边朝上），改成追问；轴承载荷要垂直于轴线；
   - 材料在材料库里，且原话里有它的牌号；
   - 原话没给的大小、方向、材料、工况系数一律不猜，改成追问；网格、核查用缺省并注明“缺省”；
4. 输出算例草稿（provenance.drafted_by = "ai"、confirmed_by_human = false，带每项依据与追问）；人改完、清掉追问、确认后才能算。

LLM 客户端沿用 `ingest.llm_extract`（真实调用、录制、回放）；测试只用假客户端与录制回放。
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from ingest.units import UnitError, to_standard

PROMPT_VERSION = "fea-draft/2"
DEFAULT_MODEL = "claude-sonnet-5-5"
TOOL_NAME = "propose_fea_study"
ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = ROOT / "tests" / "recordings" / "fea_draft"
SAMPLES = ROOT / "tests" / "fixtures" / "fea-draft" / "samples.json"
STANDARD_GRAVITY = 9.80665           # 标准重力加速度（定义值，CGPM 1901）

SUPPORTS = ("fixed", "cyl_support", "symmetry", "pinned")
LOADS = ("force", "pressure", "torque", "moment", "bearing_load", "gravity", "remote_load")
CONNECTIONS = ("bonded", "bolt_preload")
STEPS = ("static", "modal")
TYPES = SUPPORTS + LOADS + CONNECTIONS + STEPS
AXIAL = ("shaft_segment", "bore")                    # 有轴线的特征
PLANAR = ("end_face", "shoulder", "keyway_or_flat")
NO_LOAD = ("fillet", "chamfer")                      # 圆角、倒角不当支承、不加载
ALLOWED = {"cyl_support": AXIAL, "bearing_load": AXIAL, "torque": AXIAL, "symmetry": PLANAR}
# 数值字段 → 换算用的字段名（后缀决定标准单位）
FIELD = {"force": "force_n", "bearing_load": "force_n", "remote_load": "force_n", "torque": "torque_nm",
         "moment": "moment_nm", "pressure": "pressure_mpa", "gravity": "acceleration_m_s2"}
CASE_WORDS = {"dead": ("自重", "重力", "self-weight", "self weight", "dead"),
              "operating": ("工作", "运行", "operating", "working", "service"),
              "accidental": ("急停", "冲击", "碰撞", "事故", "emergency", "impact", "crash", "accidental"),
              "test": ("试验", "测试", "test", "proof")}
MODAL_WORDS = ("模态", "固有频率", "振型", "共振", "modal", "natural frequenc", "mode shape", "eigen")
GRAVITY_WORDS = ("自重", "重力", "self-weight", "self weight", "gravity", "own weight")
DOF_WORDS = {"radial": ("径向", "radial"), "axial": ("轴向", "axial"),
             "tangential": ("切向", "周向", "转动", "tangential", "rotation", "circumferential")}
# 壳、梁（ADR-0095；起草见 ADR-0096 第 1 步）：能用的类型、各类特征作用在哪（面、边、顶点）
THIN_TYPES = {"shell": ("fixed", "pinned", "force", "pressure", "gravity", "static", "modal"),
              "beam": ("fixed", "pinned", "force", "gravity", "static", "modal")}
THIN_WHERE = {"shell_face": "faces", "shell_edge": "edges", "beam_member": "edges", "beam_end": "vertices",
              "beam_joint": "vertices"}
PINNED_WORDS = ("简支", "铰支", "铰接", "铰链", "pinned", "simply supported", "simple support", "hinged")
SECTION_WORDS = {"rect": ("矩形", "方钢", "扁钢", "rectangular", "rectangle", "square bar", "flat bar"),
                 "circle": ("圆钢", "实心圆", "圆截面", "圆棒", "solid round", "round bar", "solid circular"),
                 "pipe": ("圆管", "钢管", "管", "pipe", "tube")}
SECTION_DIMS = {"rect": ("width", "height"), "circle": ("diameter",), "pipe": ("outer_diameter", "wall")}
HEAT = {"QT": ("调质", "quenched and tempered", "q&t", "qt"), "CQ": ("渗碳", "carburiz", "case harden"),
        "T6": ("t6",)}

SYSTEM_PROMPT = """你是机械工程师的助手，把工程师的一句话起草成有限元算例。你只提议，程序会逐项核对，工程师确认后才计算。

规则：
1. 零件的面只能用下面清单里的特征编号（F1、F2……）引用，不要写面号；清单里找不到合适的特征，就写进 questions。
2. 每一项都要有 quote：从工程师原话里逐字摘一段（不改字、不翻译、不补字），作为这一项的依据。
3. 数值（力、扭矩、压力、加速度、阶数、组合系数）只能用原话里出现的数，单位照原话写；原话没给的数一律不填（null），并在 questions 里问。
   不要用常识或经验补数，不要换算。
4. 方向（力、轴承载荷、重力、力矩）写成 +x、-x、+y、-y、+z、-z 之一，并给出原话里说方向的那段 direction_quote；原话没说方向就不填，并提问。
5. 材料用材料库的 id；原话没说材料就不填，并提问。
6. 扭矩、圆柱支承、轴承载荷的轴线由程序按所选特征的轴线定，你只选特征。圆柱支承的约束方向（radial、tangential、axial）按原话写。
7. 原话分了工况、给了组合系数才写 load_cases 和 combinations；系数只用原话里的数。
8. 原话要求模态 / 固有频率才写 modal 分析步。
9. 原话里有而你拿不准的（哪个面、哪个方向、载荷属于哪个工况），宁可提问，不要猜。
10. 清单里标“壳（STEP 是中面）”的零件：bodies 里写 thickness（厚度，原话里的数和单位）；支承、载荷选壳面或边的特征
    （边界边上的固定、简支、力用边）。只能用 fixed、pinned、force、pressure、gravity。
11. 清单里标“梁（STEP 是轴线）”的零件：bodies 里写 section（截面）：shape 为 rect（矩形实心）、circle（实心圆）、pipe（圆管）之一，
    尺寸只用原话里的数（rect 写 width、height 和 orientation——宽度方向，按零件坐标 ±x/±y/±z，附 orientation_quote；
    circle 写 diameter；pipe 写 outer_diameter、wall），并附 section_quote（原话里说截面的那段）。
    支承、载荷选杆件（边）或端点、节点（顶点）。只能用 fixed、pinned、force、gravity。
12. 原话说“简支 / 铰支 / pinned”的用 pinned（只限平动、不限转动）；说“固定 / 固支 / 夹紧”的用 fixed。
"""
TOOL_INSTRUCTION = "\n必须调用一次工具 {name} 提交起草结果。"

_VAL = {"type": ["object", "null"], "properties": {"value": {"type": "number"}, "unit": {"type": "string"},
                                                   "quote": {"type": "string"}}, "required": ["value", "quote"]}
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "算例名（简短，英文或拼音）"},
        "bodies": {"type": "array", "items": {"type": "object", "properties": {
            "part": {"type": "integer", "description": "零件序号（清单里的“零件 k”）"},
            "material": {"type": ["string", "null"], "description": "材料库 id"},
            "material_quote": {"type": ["string", "null"]},
            "thickness": {**_VAL, "description": "壳：厚度"},
            "section": {"type": ["object", "null"], "description": "梁：截面", "properties": {
                "shape": {"enum": ["rect", "circle", "pipe"]},
                "width": _VAL, "height": _VAL, "diameter": _VAL, "outer_diameter": _VAL, "wall": _VAL,
                "orientation": {"type": ["string", "null"], "enum": ["+x", "-x", "+y", "-y", "+z", "-z", None]},
                "orientation_quote": {"type": ["string", "null"]},
                "section_quote": {"type": "string"}}, "required": ["shape", "section_quote"]}}, "required": ["part"]}},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "type": {"enum": list(TYPES)},
            "part": {"type": "integer"},
            "features": {"type": "array", "items": {"type": "string"}},
            "part_b": {"type": "integer", "description": "bonded：另一侧的零件"},
            "features_b": {"type": "array", "items": {"type": "string"}},
            "magnitude": _VAL,
            "direction": {"type": ["string", "null"], "enum": ["+x", "-x", "+y", "-y", "+z", "-z", None]},
            "direction_quote": {"type": ["string", "null"]},
            "dofs": {"type": "array", "items": {"enum": ["radial", "tangential", "axial"]}},
            "n_modes": _VAL,
            "case": {"type": ["string", "null"]},
            "quote": {"type": "string"}}, "required": ["type", "quote"]}},
        "load_cases": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "name": {"type": "string"},
            "kind": {"enum": ["dead", "operating", "accidental", "test", "other"]}, "quote": {"type": "string"}},
            "required": ["id", "kind", "quote"]}},
        "combinations": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "name": {"type": "string"}, "quote": {"type": "string"},
            "factors": {"type": "array", "items": {"type": "object", "properties": {
                "case": {"type": "string"}, "value": {"type": "number"}}, "required": ["case", "value"]}}},
            "required": ["id", "factors", "quote"]}},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["bodies", "items", "questions"],
}


# ---------------------------------------------------------------- 零件特征清单


def part_features(step_paths: list[str], library=None) -> list[dict]:
    """每个零件：{"part": k, "path", "recog", "ids": {"F3": 特征}}；特征编号全局连续，给 AI 看的清单在 "text" 里"""
    from assist.features import geometry_kind, recognize, recognize_thin

    if library is None:
        from kb.library import JsonLibrary

        library = list(JsonLibrary(ROOT / "data" / "library").all())
    out, n = [], 0
    for k, p in enumerate(step_paths, 1):
        kind = geometry_kind(str(p))
        r = recognize(str(p), library) if kind == "solid" else recognize_thin(str(p))
        faces = {f["id"]: f for f in r["faces"]}
        ids, lines = {}, [f"零件 {k}：{Path(p).name}；{r['text'].splitlines()[0]}"]
        for x in r["features"]:
            n += 1
            fid = f"F{n}"
            ids[fid] = x
            bb = [faces[i]["bbox"] for i in x.get("faces") or [] if i in faces] or [x["bbox"]]
            lo = np.min([b[:3] for b in bb], axis=0)
            hi = np.max([b[3:] for b in bb], axis=0)
            span = "，".join(f"{a} {lo[j]:.1f}…{hi[j]:.1f}" if hi[j] - lo[j] > 0.05 else f"{a} = {lo[j]:.1f}"
                            for j, a in enumerate("xyz"))
            extra = f"；轴线方向 {[round(v, 3) for v in x['axis']]}" if isinstance(x.get("axis"), list) else ""
            lines.append(f"- {fid}（零件 {k}）{x['text']}；范围 {span}{extra}")
        out.append({"part": k, "path": str(p), "kind": kind, "recog": r, "ids": ids, "text": "\n".join(lines)})
    return out


def materials_catalog() -> list[dict]:
    from analysis.common import materials

    return [{"id": m["id"], "name": m["name"]} for m in materials.all_materials()]


def build_request(statement: str, parts: list[dict], *, model: str = DEFAULT_MODEL) -> dict:
    mats = "\n".join(f"- {m['id']}：{m['name']}" for m in materials_catalog())
    user = (f"工程师原话：\n{statement.strip()}\n\n零件特征清单（程序识别，面编号对应 STEP）：\n"
            + "\n\n".join(p["text"] for p in parts) + f"\n\n材料库：\n{mats}")
    return {"model": model, "prompt_version": PROMPT_VERSION,
            "system": SYSTEM_PROMPT + TOOL_INSTRUCTION.format(name=TOOL_NAME), "user": user,
            "tool": {"name": TOOL_NAME, "description": "提交起草的有限元算例", "input_schema": TOOL_SCHEMA}}


class FakeClient:
    """测试用：返回给定的工具输入（模拟 LLM，不是录制）"""

    def __init__(self, tool_input: dict):
        self.tool_input = tool_input

    def complete(self, request: dict) -> dict:
        return {"id": "fake", "tool_input": copy.deepcopy(self.tool_input), "simulated": True}


# ---------------------------------------------------------------- 核对（纯函数）

_NUM = re.compile(r"(?<![\d.])[+\-]?\d+(?:\.\d+)?(?![\d.])")


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").replace("−", "-").replace("–", "-")
    return re.sub(r"\s+", "", t).casefold()


def _in_statement(quote: Any, statement: str) -> bool:
    return isinstance(quote, str) and bool(quote.strip()) and _norm(quote) in _norm(statement)


def _value_with_unit(v: dict, statement: str, field: str | None) -> tuple[float | None, str | None]:
    """核对一个数值：引用在原话里、数值是引用里一个完整的数且紧跟单位；返回 (标准单位的值, 不通过的原因)"""
    if not isinstance(v, dict) or not isinstance(v.get("value"), (int, float)) or isinstance(v.get("value"), bool):
        return None, "没有数值"
    if not _in_statement(v.get("quote"), statement):
        return None, f"数值的引用“{v.get('quote')}”不在原话里"
    q = _norm(v["quote"])
    unit = _norm(v.get("unit") or "")
    hits = [m for m in _NUM.finditer(q) if math.isclose(float(m.group()), float(v["value"]), rel_tol=1e-9, abs_tol=1e-12)]
    if not hits:
        return None, f"数值 {v['value']} 不在引用“{v['quote']}”里（不采用编造或换算过的数）"
    if field is None:                                  # 无量纲（阶数、组合系数）
        return float(v["value"]), None
    if not unit or not any(q[m.end():].startswith(unit) for m in hits):
        return None, f"单位“{v.get('unit')}”没有紧跟数值出现在引用里"
    try:
        return to_standard(float(v["value"]), v["unit"], field), None
    except UnitError as e:
        return None, f"单位不对：{e}"


_AXIS = {"x": 0, "y": 1, "z": 2}


def parse_direction(quote: str) -> tuple[str | None, str]:
    """从原话的一段里读方向：只认按零件坐标写明的 ±x/y/z（含“z 轴负向”“negative z”）。
    “向下 / 向上”不认：零件文件看不出哪边朝上，按某个轴猜就是编造（真实 LLM 验收时 AI 自己也是这样问的）"""
    t = unicodedata.normalize("NFKC", quote or "").replace("−", "-").casefold()
    m = re.search(r"(?<![a-z0-9])([+\-])\s*([xyz])(?![a-z])", t)
    if m:
        return m.group(1) + m.group(2), ""
    m = re.search(r"(?<![a-z])([xyz])\s*轴?\s*(正|负)\s*(?:向|方向)", t)
    if m:
        return ("+" if m.group(2) == "正" else "-") + m.group(1), ""
    m = re.search(r"\b(positive|negative)\s+([xyz])\b", t)
    if m:
        return ("+" if m.group(1) == "positive" else "-") + m.group(2), ""
    return None, ""


def _vec(d: str, mag: float) -> list[float]:
    v = [0.0, 0.0, 0.0]
    v[_AXIS[d[1]]] = mag if d[0] == "+" else -mag
    return v


def _has(word: str, q: str) -> bool:
    """原话的一段 q 里有 word，且前后不紧挨字母数字（“45”不能匹配到“Q345”里）。保留空格比，
    否则“40Cr quenched”去掉空格成了“40crquenched”，牌号后面紧挨字母就认不出来"""
    t = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", q or "")).casefold()
    w = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", word)).casefold().strip()
    return re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", t) is not None


def _material_ok(mid: str, name: str, quote: str) -> bool:
    """原话里要有这个材料：id 或名称，或牌号 + 对应的热处理词（“45 钢调质”“40Cr quenched and tempered”）"""
    q = _norm(quote)
    raw = quote or ""
    grade, _, heat = mid.partition("-")
    plain = re.sub(r"[（(].*?[）)]", "", name)
    if _has(mid, raw) or _norm(name) in q:
        return True
    if heat:
        return _has(grade, raw) and (any(_norm(w) in q for w in HEAT.get(heat, ())) or _has(heat, raw))
    return _has(plain, raw)


def _feat_line(fid: str, x: dict) -> str:
    return f"{fid}：{x['text']}"[:120]


def _section_shape(quote: str) -> str | None:
    """原话里说的截面形状：矩形管（方管）本版不支持，返回 "box"；认不出返回 None"""
    q = _norm(quote)
    if any(_norm(w) in q for w in ("方管", "矩形管", "rectangular tube", "square tube", "box section", "hollow section")):
        return "box"
    for shape in ("pipe", "rect", "circle"):            # 先认管（“圆钢管”里有“圆钢”）
        if any(_norm(w) in q for w in SECTION_WORDS[shape]):
            return shape
    return None


def _thin_body(b: dict, part: dict, statement: str, members: list[dict]) -> tuple[dict, list[dict], str | None]:
    """壳的厚度、梁的截面：只用原话里的数。返回（要并进实体的字段, 依据, 不通过的原因）"""
    if part["kind"] == "shell":
        val, why = _value_with_unit(b.get("thickness"), statement, "thickness_mm")
        if why:
            return {}, [], f"厚度：{why}"
        return {"thickness_mm": val}, [{"target": "thickness_mm", "quote": b["thickness"]["quote"]}], None
    sec = b.get("section")
    if not isinstance(sec, dict) or not _in_statement(sec.get("section_quote"), statement):
        return {}, [], "截面：原话里找不到说截面的那段"
    said = _section_shape(sec["section_quote"])
    if said == "box":
        return {}, [], "截面：矩形管（方管）本版不支持（只有矩形实心、实心圆、圆管）"
    if said is None or said != sec.get("shape"):
        return {}, [], f"截面：AI 写的形状 {sec.get('shape')} 与原话“{sec['section_quote']}”不符"
    out, basis = {"shape": said}, []
    for d in SECTION_DIMS[said]:
        val, why = _value_with_unit(sec.get(d), statement, f"{d}_mm")
        if why:
            return {}, [], f"截面的 {d}：{why}"
        out[f"{d}_mm"] = val
        basis.append({"target": f"section/{d}_mm", "quote": sec[d]["quote"]})
    if said == "rect":
        oq = sec.get("orientation_quote")
        d, _ = parse_direction(oq) if _in_statement(oq, statement) else (None, "")
        if d is None or d != sec.get("orientation"):
            return {}, [], "截面：矩形截面的宽度方向原话没按零件坐标写明（±x / ±y / ±z）"
        vec = _vec(d, 1.0)
        if any(abs(float(np.dot(vec, m["direction"]))) > 1e-6 for m in members if "direction" in m):
            return {}, [], f"截面：宽度方向 {d} 不垂直于杆件轴线"
        out["orientation"] = vec
        basis.append({"target": "section/orientation", "quote": oq})
    if said == "pipe" and out["wall_mm"] * 2 > out["outer_diameter_mm"]:
        return {}, [], "截面：壁厚超过外半径"
    return {"section": out}, basis, None


THIN_ASK = {"shell": "零件 {k}（{name}）是壳（中面）：板厚是多少（mm）？",
            "beam": "零件 {k}（{name}）是梁（轴线）：截面是什么（矩形宽 × 高与宽度方向、实心圆直径、圆管外径 × 壁厚，mm）？"}


def verify(tool_input: Any, statement: str, parts: list[dict], *, response_id: str = "", model: str = "") -> dict:
    """核对 AI 的提议，拼成算例草稿。返回 {"study", "questions", "rejected", "errors"}"""
    if not isinstance(tool_input, dict):
        raise TypeError("AI 的提议不是一个对象")
    by_part = {p["part"]: p for p in parts}
    basis: list[dict] = []
    questions = [str(q)[:300] for q in tool_input.get("questions") or [] if str(q).strip()]
    rejected: list[dict] = []

    def reject(i, typ, why, ask=None):
        rejected.append({"item": i, "type": typ, "reason": why})
        if ask:
            questions.append(ask[:300])

    # 实体与材料
    mats = {m["id"]: m for m in materials_catalog()}
    bodies, bid = [], {}
    for b in tool_input.get("bodies") or []:
        k = b.get("part")
        if k not in by_part or k in bid:
            reject(None, "body", f"零件序号 {k} 不存在或重复")
            continue
        bid[k] = f"b{k}"
        body = {"id": bid[k], "step_path": by_part[k]["path"]}
        m, mq = b.get("material"), b.get("material_quote")
        if m in mats and _in_statement(mq, statement) and _material_ok(m, mats[m]["name"], mq):
            body["material"] = m
            basis.append({"target": f"/bodies/{len(bodies)}/material", "source": "statement", "quote": mq[:200],
                          "note": f"{m}：{mats[m]['name']}"})
        else:
            why = "原话没说材料" if not m else f"材料 {m} 不在材料库或原话里没有这个牌号"
            reject(None, "material", f"零件 {k}：{why}", f"零件 {k}（{Path(by_part[k]['path']).name}）用什么材料（材料库里的牌号）？")
        kind = by_part[k].get("kind", "solid")
        if kind != "solid":
            body["kind"] = kind
            members = [x for x in by_part[k]["ids"].values() if x["type"] == "beam_member"]
            extra, bs, why = _thin_body(b, by_part[k], statement, members)
            if why:
                reject(None, kind, f"零件 {k}：{why}", THIN_ASK[kind].format(k=k, name=Path(by_part[k]["path"]).name))
            body.update(extra)
            for x in bs:
                basis.append({"target": f"/bodies/{len(bodies)}/{x['target']}", "source": "statement", "quote": x["quote"][:200]})
        bodies.append(body)
    for k, p in by_part.items():
        if k not in bid:
            bid[k] = f"b{k}"
            body = {"id": bid[k], "step_path": p["path"]}
            if p.get("kind", "solid") != "solid":
                body["kind"] = p["kind"]
                questions.append(THIN_ASK[p["kind"]].format(k=k, name=Path(p["path"]).name))
            bodies.append(body)
            questions.append(f"零件 {k}（{Path(p['path']).name}）用什么材料（材料库里的牌号）？")

    # 工况与组合
    cases, combos = [], []
    for c in tool_input.get("load_cases") or []:
        if not _in_statement(c.get("quote"), statement) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", str(c.get("id", ""))):
            reject(None, "load_case", f"工况 {c.get('id')} 的引用不在原话里或 id 不合格")
            continue
        q = _norm(c["quote"])
        hit = [k for k, ws in CASE_WORDS.items() if any(_norm(w) in q for w in ws)]
        if hit and c["kind"] not in hit:
            reject(None, "load_case", f"工况 {c['id']} 的类别 {c['kind']} 与原话“{c['quote']}”不符（应为 {hit[0]}）")
            continue
        cases.append({"id": c["id"], "name": str(c.get("name") or c["id"])[:80], "kind": c["kind"]})
        basis.append({"target": f"/load_cases/{len(cases) - 1}", "source": "statement", "quote": c["quote"][:200]})
    case_ids = {c["id"] for c in cases}
    for c in tool_input.get("combinations") or []:
        if not _in_statement(c.get("quote"), statement):
            reject(None, "combination", f"组合 {c.get('id')} 的引用不在原话里")
            continue
        fac, bad = {}, None
        for f in c.get("factors") or []:
            v, why = _value_with_unit({"value": f.get("value"), "quote": c["quote"]}, statement, None)
            if f.get("case") not in case_ids or why:
                bad = why or f"组合引用了不存在的工况 {f.get('case')}"
                break
            fac[f["case"]] = v
        if bad or not fac:
            reject(None, "combination", f"组合 {c.get('id')}：{bad or '没有系数'}",
                   f"组合 {c.get('id')} 的各工况系数是多少（按哪本标准）？")
            continue
        combos.append({"id": c["id"], "name": str(c.get("name") or c["id"])[:80], "factors": fac,
                       "basis": c["quote"][:200]})
        basis.append({"target": f"/combinations/{len(combos) - 1}", "source": "statement", "quote": c["quote"][:200]})

    supports, loads, conns, steps = [], [], [], []
    for i, it in enumerate(tool_input.get("items") or []):
        typ = it.get("type")
        if typ not in TYPES:
            reject(i, typ, "不认识的类型")
            continue
        if not _in_statement(it.get("quote"), statement):
            reject(i, typ, f"引用“{it.get('quote')}”不在原话里",
                   f"AI 提议了一项 {typ}，但在原话里找不到依据（没采用）；需要的话请写明作用在哪、多大")
            continue
        if typ in STEPS:
            if typ == "static":
                steps.append(({"id": "s1", "type": "static"}, {"source": "statement", "quote": it["quote"][:200]}))
                continue
            if not any(_norm(w) in _norm(it["quote"]) for w in MODAL_WORDS):
                reject(i, typ, "原话没要求模态 / 固有频率")
                continue
            st, b = {"id": "m1", "type": "modal"}, {"source": "statement", "quote": it["quote"][:200]}
            if it.get("n_modes"):
                n, why = _value_with_unit(it["n_modes"], statement, None)
                if why or n is None or n != int(n) or not 1 <= n <= 50:
                    reject(i, typ, f"阶数：{why or '不是 1–50 的整数'}")
                    continue
                st["n_modes"] = int(n)
                b["note"] = f"阶数按原话“{it['n_modes']['quote']}”"
            else:
                b["note"] = "阶数原话没给，用缺省 6 阶"
            steps.append((st, b))
            continue
        if typ == "bolt_preload":
            reject(i, typ, "算例里没有螺栓实体，不能加螺栓预紧",
                   "螺栓预紧怎么处理：把螺栓作为实体加进来，还是简化（例如螺栓孔处固定、或按等效压力加在螺栓头支承面）？")
            continue
        k = it.get("part")
        if (typ != "gravity" or k is not None) and k not in by_part:
            reject(i, typ, f"零件序号 {k} 不存在")
            continue
        fids = it.get("features") or []
        feats = []
        thin = by_part[k].get("kind", "solid") if k is not None else "solid"
        if thin != "solid" and typ not in THIN_TYPES[thin]:
            reject(i, typ, f"{'壳' if thin == 'shell' else '梁'}本版只能用 {'、'.join(THIN_TYPES[thin])}",
                   f"“{it['quote']}”在{'壳' if thin == 'shell' else '梁'}上怎么处理（固定、简支、力"
                   + ("、压力" if thin == "shell" else "") + "）？")
            continue
        if typ == "pinned":
            if thin == "solid":
                reject(i, typ, "实体零件不用简支：用固定或圆柱支承", f"“{it['quote']}”的支承限制哪些方向？")
                continue
            if not any(_norm(w) in _norm(it["quote"]) for w in PINNED_WORDS):
                reject(i, typ, "原话没说简支 / 铰支", f"“{it['quote']}”是固定（夹紧）还是简支（只限平动）？")
                continue
        where = "faces"
        if typ != "gravity":
            if not fids:
                reject(i, typ, "没有选特征", f"“{it['quote']}”作用在哪个面上？")
                continue
            missing = [f for f in fids if f not in by_part[k]["ids"]]
            if missing:
                reject(i, typ, f"特征 {missing} 不在零件 {k} 上", f"“{it['quote']}”作用在零件 {k} 的哪个面上？")
                continue
            feats = [by_part[k]["ids"][f] for f in fids]
            if thin != "solid":
                kinds = {THIN_WHERE.get(x["type"]) for x in feats}
                if None in kinds or len(kinds) != 1 or (typ == "pressure" and kinds != {"faces"}):
                    need = "壳面" if typ == "pressure" else "同一类特征（都是面、都是边或都是顶点）"
                    reject(i, typ, f"特征 {fids} 不合乎 {typ}（要{need}）", f"“{it['quote']}”作用在哪里？")
                    continue
                where = kinds.pop()
            wrong = [f for f, x in zip(fids, feats, strict=True)
                     if x["type"] in NO_LOAD or (typ in ALLOWED and x["type"] not in ALLOWED[typ])]
            if wrong:
                need = {"cyl_support": "轴段或孔（圆柱面）", "bearing_load": "轴段或孔（圆柱面）", "torque": "轴段或孔",
                        "symmetry": "平面"}.get(typ, "不是圆角、倒角的面")
                reject(i, typ, f"特征 {wrong} 的类型不合乎 {typ}（要{need}）", f"“{it['quote']}”作用在哪个面上？")
                continue
        faces = sorted({f for x in feats for f in x.get(where) or []})
        b = {"source": "statement", "quote": it["quote"][:200], "features": [_feat_line(f, x) for f, x in zip(fids, feats, strict=True)]}
        notes = []
        axis = None
        if typ in ("cyl_support", "bearing_load", "torque"):
            a0 = feats[0]
            if any(not _same_axis(a0, x) for x in feats[1:]):
                reject(i, typ, "所选特征不同轴", f"“{it['quote']}”用哪一段轴 / 孔？")
                continue
            axis = {"origin_mm": [float(v) for v in a0["axis_origin"]], "dir": [float(v) for v in a0["axis"]]}
            notes.append("轴线取特征的轴线")
        rec: dict[str, Any] = {"type": typ, "body": bid[k] if k is not None else None}
        if typ != "gravity":
            rec[where] = faces
        if typ == "pinned":                              # 简支 = 三个平动为零、转动自由（ADR-0095）
            rec = {"type": "displacement", "body": rec["body"], where: faces, "ux_mm": 0.0, "uy_mm": 0.0, "uz_mm": 0.0}
            notes.append("简支：三个平动为零、转动不限")
        if typ == "cyl_support":
            dofs = [d for d in it.get("dofs") or [] if any(_norm(w) in _norm(it["quote"]) for w in DOF_WORDS.get(d, ()))]
            if not dofs or len(dofs) != len(it.get("dofs") or []):
                reject(i, typ, "约束方向在原话里找不到", f"“{it['quote']}”的支承限制哪些方向（径向 / 切向 / 轴向）？")
                continue
            rec.update(axis=axis, dofs=dofs)
        if typ in FIELD:
            mag = it.get("magnitude")
            if typ == "gravity" and not mag:
                if not any(_norm(w) in _norm(it["quote"]) for w in GRAVITY_WORDS):
                    reject(i, typ, "原话没说自重 / 重力")
                    continue
                val = STANDARD_GRAVITY
                notes.append("大小取标准重力加速度 9.80665 m/s²（定义值）")
                b["source"] = "statement"
            else:
                val, why = _value_with_unit(mag, statement, FIELD[typ])
                if why:
                    ask = f"“{it['quote']}”的大小是多少（带单位）？"
                    reject(i, typ, f"大小：{why}", ask)
                    continue
            if typ in ("force", "bearing_load", "remote_load", "gravity", "moment"):
                d, dnote = parse_direction(it.get("direction_quote") or "") if _in_statement(it.get("direction_quote"), statement) else (None, "")
                if d is None or d != it.get("direction"):
                    why = "原话没说方向" if d is None else f"AI 写的方向 {it.get('direction')} 与原话（{d}）不符"
                    reject(i, typ, why, f"“{it['quote']}”朝哪个方向（零件坐标的 ±x / ±y / ±z）？")
                    continue
                if dnote:
                    notes.append(dnote)
                v = _vec(d, val)
                if typ == "bearing_load" and abs(np.dot(v, axis["dir"])) > 1e-6 * val:
                    reject(i, typ, f"轴承载荷的方向 {d} 不垂直于轴线", f"“{it['quote']}”的径向力朝哪个方向（要垂直于轴线）？")
                    continue
                key = {"force": "vector_n", "bearing_load": "force_n", "remote_load": "force_n", "gravity": "acceleration_m_s2",
                       "moment": "vector_nm"}[typ]
                rec[key] = v
                if typ == "bearing_load":
                    rec["axis"] = axis
                if typ == "remote_load":
                    reject(i, typ, "远端载荷要给作用点坐标，本版起草不处理", f"“{it['quote']}”的作用点在哪（坐标 mm）？")
                    continue
            elif typ == "torque":
                rec.update(value_nm=val, axis=axis)
                notes.append("扭矩方向按特征轴线的正向（线弹性下正负不影响应力大小）")
            elif typ == "pressure":
                rec["value_mpa"] = val
        if typ == "gravity":
            if k is None:
                targets = list(by_part)
            else:
                targets = [k]
        if cases and typ in LOADS:
            if it.get("case") not in case_ids:
                reject(i, typ, "有工况时每个载荷都要归到一个工况", f"“{it['quote']}”属于哪个工况？")
                continue
            rec["case"] = it["case"]
        if typ == "bonded":
            kb = it.get("part_b")
            fb = it.get("features_b") or []
            if kb not in by_part or kb == k or not fb or any(f not in by_part[kb]["ids"] for f in fb):
                reject(i, typ, "绑定的另一侧零件或特征不对", f"“{it['quote']}”连接的是哪两个面？")
                continue
            xb = [by_part[kb]["ids"][f] for f in fb]
            conns.append(({"type": "bonded", "a": {"body": bid[k], "faces": faces},
                           "b": {"body": bid[kb], "faces": sorted({f for x in xb for f in x["faces"]})}},
                          {**b, "features": b["features"] + [_feat_line(f, x) for f, x in zip(fb, xb, strict=True)]}))
            continue
        if notes:
            b["note"] = "；".join(notes)
        if typ == "gravity":
            for t in targets:
                r = {**rec, "body": bid[t]}
                loads.append((r, b))
        elif typ in SUPPORTS:
            supports.append((rec, b))
        else:
            loads.append((rec, b))

    # 分析步：有载荷而 AI 没提静力的，缺省加一个静力步；有组合时每个组合一个静力步
    if loads and not any(s["type"] == "static" for s, _ in steps):
        steps.insert(0, ({"id": "s1", "type": "static"}, {"source": "default", "note": "有载荷，缺省做静力分析"}))
    if combos:
        rest = [x for x in steps if x[0]["type"] != "static"]
        steps = [({"id": f"s_{c['id']}", "type": "static", "combination": c["id"]},
                  {"source": "statement", "quote": c["basis"], "note": f"按组合 {c['id']} 算"}) for c in combos] + rest
    if not supports:
        questions.append("零件怎么支承（哪个面固定或限制哪些方向）？")

    study: dict[str, Any] = {"format": "fea-study/1", "name": _name(tool_input.get("name")), "bodies": bodies,
                             "supports": [s for s, _ in supports], "loads": [x for x, _ in loads],
                             "steps": [s for s, _ in steps]}
    if conns:
        study["connections"] = [c for c, _ in conns]
    if cases:
        study["load_cases"] = cases
        study["combinations"] = combos
    for key, rows in (("supports", supports), ("loads", loads), ("connections", conns), ("steps", steps)):
        for j, (_x, b) in enumerate(rows):
            basis.append({"target": f"/{key}/{j}", **b})
    basis.append({"target": "/mesh", "source": "default", "note": "网格尺寸缺省（包围盒对角线 / 30，载荷面加密）"})
    basis.append({"target": "/checks", "source": "default", "note": "可信度核查缺省：反力平衡、网格质量、三层网格收敛"})
    study["provenance"] = {"drafted_by": "ai", "confirmed_by_human": False, "basis": basis,
                           "questions": _dedupe(questions),
                           "note": f"AI 起草（提示词 {PROMPT_VERSION}，模型 {model or '未记录'}，响应 {response_id or '未记录'}）；"
                                   "未采用的提议见起草记录。须工程师逐项核对、清掉追问后确认"}
    return {"study": study, "questions": study["provenance"]["questions"], "rejected": rejected,
            "errors": check_study(study)}


def _same_axis(a: dict, b: dict) -> bool:
    d1, d2 = np.array(a["axis"]), np.array(b["axis"])
    if abs(abs(np.dot(d1, d2)) - 1) > 1e-3:
        return False
    v = np.array(b["axis_origin"]) - np.array(a["axis_origin"])
    return float(np.linalg.norm(v - d1 * np.dot(v, d1))) < max(0.05, 0.002 * a["diameter_mm"] / 2)


def _name(x: Any) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(x or "ai-draft")).strip("-")
    return (s or "ai-draft")[:60]


def _dedupe(xs: list[str]) -> list[str]:
    seen, out = set(), []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def check_study(study: dict) -> list[str]:
    """按算例的全部规则核对（假定已确认），返回不通过的原因；草稿缺东西时这里会列出来"""
    from analysis.fea.study import StudyInvalid, validate

    s = copy.deepcopy(study)
    s["provenance"] = {**s.get("provenance", {}), "confirmed_by_human": True}
    try:
        validate(s)
    except StudyInvalid as e:
        return [str(e)]
    return []


# ---------------------------------------------------------------- 起草、确认


def draft(statement: str, step_paths: list[str], client, *, model: str = DEFAULT_MODEL, library=None) -> dict:
    t0 = time.perf_counter()
    parts = part_features(step_paths, library)
    request = build_request(statement, parts, model=model)
    t1 = time.perf_counter()
    resp = client.complete(request)
    t2 = time.perf_counter()
    out = verify(resp["tool_input"], statement, parts, response_id=resp.get("id", ""), model=model)
    out["features"] = [p["text"] for p in parts]
    out["simulated"] = bool(resp.get("simulated"))
    out["elapsed_s"] = {"features": round(t1 - t0, 2), "llm": round(t2 - t1, 2), "check": round(time.perf_counter() - t2, 2)}
    return out


class ConfirmRefused(ValueError):
    pass


def confirm(study: dict, by: str, at: datetime | None = None) -> dict:
    """工程师确认：追问清掉、算例全部规则通过才记确认人与时间；不代签"""
    if not str(by or "").strip():
        raise ConfirmRefused("要写确认人")
    pv = study.get("provenance") or {}
    if pv.get("questions"):
        raise ConfirmRefused("还有追问没答：" + "；".join(pv["questions"][:5]) + "（答完把它们从 provenance.questions 里删掉）")
    errs = check_study(study)
    if errs:
        raise ConfirmRefused("算例不能算：" + "；".join(errs))
    s = copy.deepcopy(study)
    s["provenance"] = {**pv, "drafted_by": pv.get("drafted_by", "human"), "confirmed_by_human": True,
                       "confirmed_by": by.strip()[:80],
                       "confirmed_at": (at or datetime.now(UTC)).isoformat(timespec="seconds")}
    return s


# ---------------------------------------------------------------- 验收打分（与人工标注答案比）


def _where(x: dict) -> set:
    """作用位置：面号照旧用整数；边、顶点（壳、梁）加前缀，免得与面号相混"""
    return set(x.get("faces", ())) | {f"e{i}" for i in x.get("edges", ())} | {f"v{i}" for i in x.get("vertices", ())}


def _groups(study: dict) -> dict[tuple[str, str], dict]:
    """按（类型，实体）归并：面的并集与载荷大小（同一类型的多项合在一起比，分成几项写都算对）"""
    out: dict[tuple[str, str], dict] = {}
    for x in study["supports"] + study["loads"]:
        g = out.setdefault((x["type"], x["body"]), {"faces": set(), "values": []})
        g["faces"] |= _where(x)
        v = x.get("value_nm", x.get("value_mpa"))
        if v is None:
            vec = x.get("vector_n") or x.get("force_n") or x.get("acceleration_m_s2") or x.get("vector_nm")
            v = float(np.linalg.norm(vec)) if vec else None
        if v is not None:
            g["values"].append(float(v))
    for c in study.get("connections") or []:
        out.setdefault(("bonded", c["a"]["body"]), {"faces": set(), "values": []})["faces"] |= set(c["a"]["faces"])
    return out


def _round(x: Any) -> Any:
    if isinstance(x, float):
        return round(x, 9) + 0.0
    if isinstance(x, list):
        return [_round(v) for v in x]
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    return x


def score(result: dict, answer: dict) -> dict:
    """与人工标注的答案比。answer：{"items": [{type, body, faces?, value?}], "questions": [[关键词…]…], "steps": [...]}。
    面选错 = 该有的项面不对 + 不该有的项；漏掉 = 该有的项没起草（原话给全了却变成追问，也算漏）"""
    got = _groups(result["study"])
    want: dict[tuple[str, str], dict] = {}
    for e in answer.get("items", []):
        w = want.setdefault((e["type"], e["body"]), {"faces": set(), "values": []})
        w["faces"] |= _where(e)
        if "value" in e:
            w["values"].append(float(e["value"]))
    right = wrong_face = missing = wrong_value = 0
    for k, w in want.items():
        g = got.get(k)
        if g is None:
            missing += 1
        elif g["faces"] != w["faces"]:
            wrong_face += 1
        elif w["values"] and sorted(round(v, 9) for v in g["values"]) != sorted(round(v, 9) for v in w["values"]):
            wrong_value += 1
        else:
            right += 1
    extra = [k for k in got if k not in want]
    # 壳的厚度、梁的截面（answer.bodies：[{"body", "thickness_mm" | "section"}]）：没起草算漏，数不对算数错
    have = {b["id"]: b for b in result["study"]["bodies"]}
    for e in answer.get("bodies", []):
        b = have.get(e["body"], {})
        for key, val in e.items():
            if key == "body":
                continue
            if key not in b:
                missing += 1
            elif json.dumps(_round(b[key]), sort_keys=True) != json.dumps(_round(val), sort_keys=True):
                wrong_value += 1
            else:
                right += 1
    n = max(1, len(want))
    qs = " ".join(result["questions"]).casefold()
    q_hit = [any(w.casefold() in qs for w in group) for group in answer.get("questions", [])]
    steps = sorted(s["type"] for s in result["study"]["steps"])
    return {"expected": len(want), "right": right, "wrong_face": wrong_face + len(extra), "extra": [list(k) for k in extra],
            "wrong_value": wrong_value, "missing": missing, "face_error_rate": (wrong_face + len(extra)) / n,
            "questions_expected": len(q_hit), "questions_hit": sum(q_hit),
            "steps_ok": steps == sorted(answer["steps"]) if "steps" in answer else None}


def evaluate(client, samples_path: Path = SAMPLES) -> dict:
    """跑全部样例并打分；门槛：面选错 ≤ 10 %、起草（不含 LLM）< 60 s"""
    samples = json.loads(samples_path.read_text(encoding="utf-8"))["samples"]
    rows = []
    for s in samples:
        r = draft(s["statement"], [str(ROOT / p) for p in s["parts"]], client)
        sc = score(r, s["answer"])
        rows.append({"id": s["id"], **sc, "rejected": len(r["rejected"]), "elapsed_s": r["elapsed_s"],
                     "simulated": r["simulated"]})
    n = sum(x["expected"] for x in rows) or 1
    wrong = sum(x["wrong_face"] for x in rows)
    q_exp = sum(x["questions_expected"] for x in rows)
    return {"samples": rows, "face_error_rate": wrong / n, "items": n,
            "question_hit_rate": (sum(x["questions_hit"] for x in rows) / q_exp) if q_exp else None,
            "max_local_s": max(x["elapsed_s"]["features"] + x["elapsed_s"]["check"] for x in rows),
            "passed": wrong / n <= 0.10 and all(x["missing"] == 0 and x["wrong_value"] == 0 and x["steps_ok"] is not False
                                                and x["questions_hit"] == x["questions_expected"] for x in rows)
            and max(x["elapsed_s"]["features"] + x["elapsed_s"]["check"] for x in rows) < 60}


# ---------------------------------------------------------------- 命令行


def _client(args):
    from ingest.llm_extract import AnthropicClient, RecordedClient

    if args.record is not None:
        return AnthropicClient(record_dir=args.record)
    if args.live:
        return AnthropicClient()
    return RecordedClient(args.replay or RECORDINGS_DIR)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m assist.fea_draft", description="AI 起草有限元算例（ADR-0093 补充十一）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft", help="起草：一句话 + STEP 零件 → 算例草稿")
    d.add_argument("statement")
    d.add_argument("steps", nargs="+")
    d.add_argument("-o", "--out", type=Path, default=Path("study.draft.json"))
    c = sub.add_parser("confirm", help="工程师确认（追问清掉后）")
    c.add_argument("study", type=Path)
    c.add_argument("--by", required=True)
    e = sub.add_parser("eval", help="在真实零件样例上打分（面选对率、追问）")
    for p in (d, e):
        mode = p.add_mutually_exclusive_group()
        mode.add_argument("--replay", type=Path, default=None)
        mode.add_argument("--record", type=Path, nargs="?", const=RECORDINGS_DIR, default=None)
        mode.add_argument("--live", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "confirm":
        s = json.loads(a.study.read_text(encoding="utf-8"))
        try:
            s = confirm(s, a.by)
        except ConfirmRefused as ex:
            print(f"没有确认：{ex}", file=sys.stderr)
            return 2
        a.study.write_text(json.dumps(s, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"已确认：{s['provenance']['confirmed_by']} {s['provenance']['confirmed_at']}")
        return 0
    client = _client(a)
    if a.cmd == "eval":
        r = evaluate(client)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["passed"] else 1
    r = draft(a.statement, a.steps, client)
    a.out.write_text(json.dumps(r["study"], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"算例草稿写到 {a.out}（AI 起草，未确认，不能算）")
    for x in r["rejected"]:
        print(f"未采用：{x['type']}：{x['reason']}")
    for q in r["questions"]:
        print(f"追问：{q}")
    for x in r["errors"]:
        print(f"还不能算：{x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
