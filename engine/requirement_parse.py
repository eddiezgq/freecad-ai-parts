"""一句话需求的解析（ADR-0037）：LLM 报“原文说了什么”，代码逐项核对后组成结构化需求。

LLM 对每个指标给出字段名、数值（或枚举值）、原文中的单位写法和原文引用。代码核对：
- 字段名属于需求 schema；引用是原句的子串（忽略空白）；数值以完整数字出现在引用中；
- 单位写在引用中，并经 ingest.units（pint，唯一的换算入口）换算到标准单位；数值字段没有单位时不采用；
- 关键词一致：连续扭矩的引用不能是“峰值”，峰值扭矩的引用须含“峰值 / peak / 最大”等；枚举值须有关键词支持。
缺少输出连续扭矩或输出转速时不猜，给出追问；安全系数没说时取 1.2 并注明；其他没说的字段不写。

    python -m engine.requirement_parse "一句话需求" [--record]   # --record 真实调用并录制（需要密钥）
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from ingest.llm_extract import (
    DEFAULT_MODEL,
    TOOL_INSTRUCTION,
    LLMClient,
    RecordedClient,
)
from ingest.units import UnitError, to_standard
from kb.validation import errors as schema_errors

PROMPT_VERSION = "requirement/2"
TOOL_NAME = "record_requirement"
RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "tests" / "recordings" / "requirement"
DEFAULT_SAFETY_FACTOR = 1.2  # ADR-0008

PEAK_WORDS = ("峰值", "peak", "最大", "max", "瞬时", "短时", "最高")
# 连续扭矩的关键词窗口中不得出现：峰值类，以及电机自身的特殊工况扭矩（不是需求的连续值）
NOT_CONTINUOUS = (*PEAK_WORDS, "堵转", "过载", "启动", "起动", "加速", "制动", "stall", "overload", "starting",
                  "acceleration")
MAX_QUOTE = 80  # 引用的最大长度（字符），防止以整句为引用
MULTIPLIERS = ("万", "千", "亿", "k", "K", "M")

# 字段 → (说明, 必须出现其一的关键词, 不得出现的关键词)。关键词须出现在数字前面、同一分句之内
# （上一个数字或分隔符之后），不分大小写；ASCII 关键词按单词边界匹配，中文按子串匹配
NUMERIC_FIELDS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "output_torque_cont_nm": ("输出端连续（额定）扭矩", ("扭矩", "转矩", "力矩", "torque"), NOT_CONTINUOUS),
    "output_torque_peak_nm": ("输出端峰值扭矩", PEAK_WORDS, ()),
    "output_speed_rpm": ("输出端转速", ("转速", "速度", "speed", "rpm", "r/min", "转/分"), ()),
    "safety_factor": ("连续扭矩安全系数", ("安全系数", "safety factor", "safetyfactor"), ()),
    "load_inertia_kgm2": ("负载惯量", ("惯量", "inertia"), ()),
    "inertia_ratio_limit": ("惯量比上限", ("惯量比", "inertia ratio", "inertiaratio"), ()),
    "max_envelope_diameter_mm": ("外径上限", ("外径", "直径", "diameter", "Φ", "ø"), ()),
    "max_envelope_length_mm": ("长度上限", ("长度", "长", "length"), ()),
    "supply.voltage_v": ("供电电压", ("v", "伏", "电压", "voltage"), ()),
}
UNITLESS = {"safety_factor", "inertia_ratio_limit"}
REQUIRED = ("output_torque_cont_nm", "output_speed_rpm")

ENUM_FIELDS: dict[str, dict[Any, tuple[str, ...]]] = {
    "supply.current_type": {"ac": ("ac", "交流", "单相", "三相", "vac"), "dc": ("dc", "直流", "vdc")},
    "supply.phases": {1: ("单相", "single-phase", "single phase", "1相", "1-phase", "1ph"),
                      3: ("三相", "three-phase", "three phase", "3相", "3-phase", "3ph"),
                      0: ("dc", "直流", "vdc")},
    "fieldbus_protocol": {"ethercat": ("ethercat",), "canopen": ("canopen",), "modbus_rtu": ("modbus",),
                          "profinet": ("profinet",), "ethernet_ip": ("ethernet/ip", "ethernetip", "eip"),
                          "pulse_dir": ("脉冲", "pulse")},
}
ALL_FIELDS = (*NUMERIC_FIELDS, *ENUM_FIELDS)

# 中文常见单位写法 → ingest.units 认识的写法（只是改写，换算仍由 pint 完成）
UNIT_WORDS = {"转/分": "rpm", "转/分钟": "rpm", "牛米": "N*m", "牛·米": "N*m", "毫米": "mm", "伏": "V",
              "伏特": "V", "千克·平方米": "kg*m^2", "公斤·平方米": "kg*m^2"}

QUESTIONS = {
    "output_torque_cont_nm": "输出端连续（额定）扭矩是多少 N·m？",
    "output_speed_rpm": "输出端需要的转速是多少 rpm？",
    "supply": "供电是交流还是直流、电压多少 V、单相还是三相？",
}

SYSTEM_PROMPT = """你是机电关节模组需求的解析助手。只报告用户原话里明确说出的指标，不推测、不补全、不换算单位。
对每个指标调用一次 items 条目：
- field：字段名，只能取字段清单中的名字
- value：原话中的数字（照抄，不换算），或枚举字段的取值
- unit：原话中紧跟数字的单位写法（照抄，如 N·m、rpm、kg·cm²、V、mm）；枚举字段与无单位的数填空字符串
- quote：原话中支持该指标的一段连续文字（照抄），须含说明这是什么指标的词（如“连续扭矩”“峰值”“转速”“外径”）以及数字与单位
没有说的指标不要报；含义不清的不要报，写进 unclear。"""


def _catalog() -> str:
    lines = [f"{f} ; 数值 ; {NUMERIC_FIELDS[f][0]}" for f in NUMERIC_FIELDS]
    lines += [f"{f} ; 枚举 {sorted(map(str, ENUM_FIELDS[f]))}" for f in ENUM_FIELDS]
    return "\n".join(lines)


TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {"field": {"type": "string"}, "value": {"type": ["number", "string"]},
                           "unit": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["field", "value", "unit", "quote"]}},
        "unclear": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["items"],
}


def build_request(statement: str, *, model: str = DEFAULT_MODEL) -> dict:
    return {
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "system": SYSTEM_PROMPT + TOOL_INSTRUCTION.format(name=TOOL_NAME),
        "user": f"字段清单（field ; 类型 ; 说明）：\n{_catalog()}\n\n用户原话：\n{statement}",
        "tool": {"name": TOOL_NAME, "description": "记录从用户原话中识别出的需求指标", "input_schema": TOOL_SCHEMA},
    }


# ---------------------------------------------------------------- 核对（纯函数）

_WS = re.compile(r"\s+")
# 数字：千分位（1,500）或普通数字，可带小数；前面不能紧挨字母或数字（M5、IP65 不算）
_NUM = re.compile(r"(?<![A-Za-z0-9.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d.]|,\d{3})")
_SEP = re.compile(r"[，,；;、。:：（）()]")


def _squash(s: str) -> str:
    return _WS.sub("", s or "").casefold()


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    """text 中是否出现任一关键词：ASCII 词按单词边界（ac 不匹配 actuator），中文按子串。"""
    folded = (text or "").casefold()
    squashed = _squash(text)
    for w in words:
        wf = w.casefold()
        if wf.isascii():
            if re.search(rf"(?<![a-z]){re.escape(wf)}(?![a-z])", folded):
                return True
        elif _squash(w) in squashed:
            return True
    return False


def _occurrences(quote: str, value: float) -> list[re.Match]:
    return [m for m in _NUM.finditer(quote) if float(m.group(1).replace(",", "")) == value]


def _window(quote: str, m: re.Match) -> str:
    """数字前面、同一分句之内的文字：从上一个数字或分隔符之后，到这个数字为止。"""
    before = quote[: m.start()]
    cut = 0
    for prev in _NUM.finditer(before):
        cut = max(cut, prev.end())
    for sep in _SEP.finditer(before):
        if not before[sep.start() - 1: sep.start()].isdigit() or sep.group() not in ",.":
            cut = max(cut, sep.end())
    return before[cut:]


def _unit_follows(quote: str, m: re.Match, unit: str) -> bool:
    """单位紧跟在数字后面（允许空白），且单位之后不再接字母（mm 不等于 m）。"""
    rest = quote[m.end():].lstrip()
    u = unit.strip()
    if not rest.startswith(u):
        return False
    nxt = rest[len(u): len(u) + 1]
    return not (nxt.isascii() and nxt.isalpha()) and nxt not in ("²", "³", "·", "/", "^")


def _check_item(statement: str, item: dict) -> tuple[str, Any] | str:
    """核对一项；通过返回 (字段, 标准值)，否则返回原因。"""
    field, value, unit, quote = item.get("field"), item.get("value"), item.get("unit", ""), item.get("quote", "")
    if not isinstance(field, str) or field not in ALL_FIELDS:
        return f"未知字段 {field!r}"
    if not isinstance(quote, str) or not isinstance(unit, str):
        return "quote 与 unit 须为字符串"
    if not quote.strip() or _squash(quote) not in _squash(statement):
        return f"引用 {quote!r} 不在原话中"
    if len(quote.strip()) > MAX_QUOTE:
        return f"引用过长（超过 {MAX_QUOTE} 字），须只引用说明该指标的分句"
    if field in ENUM_FIELDS:
        options = ENUM_FIELDS[field]
        key = value
        if field == "supply.phases" and isinstance(value, str) and value.isdigit():
            key = int(value)
        if isinstance(key, (list, dict, bool)) or key not in options:
            return f"{field} 的取值 {value!r} 不在可选值中"
        if not _has_any(quote, options[key]):
            return f"引用 {quote!r} 中没有支持 {field}={key} 的关键词"
        return field, key
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{field} 须为数字，收到 {value!r}"
    label, must, forbid = NUMERIC_FIELDS[field]
    occ = _occurrences(quote, float(value))
    if not occ:
        return f"数字 {value} 不在引用 {quote!r} 中"
    reasons = []
    for m in occ:  # 引用中同一数字出现多次时，任一处满足全部条件即可
        tail = quote[m.end():].lstrip()
        win = _window(quote, m)
        if field in UNITLESS:
            if unit.strip():
                reasons.append(f"{field} 没有单位，收到 {unit!r}")
                continue
            if tail[:1] in MULTIPLIERS:
                reasons.append(f"数字 {value} 后跟倍数词 {tail[:1]!r}，请确认")
                continue
        else:
            if not unit.strip():
                reasons.append(f"{field} 没有单位，不猜")
                continue
            if not _unit_follows(quote, m, unit):
                if tail[:1] in MULTIPLIERS and not unit.strip().startswith(tail[:1]):
                    reasons.append(f"数字 {value} 后跟倍数词 {tail[:1]!r}，请确认")
                else:
                    reasons.append(f"单位 {unit!r} 没有紧跟在数字 {value} 后面")
                continue
        if not _has_any(win, must) and not (field in ("output_speed_rpm", "supply.voltage_v") and _has_any(unit, must)):
            reasons.append(f"数字 {value} 前面没有说明这是{label}的关键词")
            continue
        if forbid and _has_any(win, forbid):
            reasons.append(f"引用说的是峰值、最大或特殊工况的值，不是{label}")
            continue
        break
    else:
        return "；".join(dict.fromkeys(reasons))
    if field in UNITLESS:
        return field, float(value)
    std_field = field.split(".")[-1]
    try:
        std = to_standard(float(value), UNIT_WORDS.get(unit.strip(), unit), std_field)
    except UnitError as exc:
        return f"{field}：{exc}"
    if std <= 0:
        return f"{field} 须为正数"
    return field, round(std, 12)


def interpret(statement: str, tool_input: dict) -> dict:
    """由 LLM 的工具输入与原话得到结果：status 为 ok（可用于选型）或 needs_input（需追问）。"""
    accepted: dict[str, Any] = {}
    basis: dict[str, str] = {}
    rejected: list[dict] = []
    conflicts: set[str] = set()
    for item in tool_input.get("items", []) if isinstance(tool_input, dict) else []:
        if not isinstance(item, dict):
            rejected.append({"field": None, "reason": "条目不是对象"})
            continue
        out = _check_item(statement, item)
        if isinstance(out, str):
            rejected.append({"field": item.get("field"), "reason": out})
            continue
        field, val = out
        if field in accepted and accepted[field] != val:
            conflicts.add(field)
        accepted.setdefault(field, val)
        basis.setdefault(field, item["quote"])
    for f in sorted(conflicts):
        rejected.append({"field": f, "reason": "原话中有多个不同的值，无法确定"})
        accepted.pop(f)
        basis.pop(f)

    req: dict[str, Any] = {"statement": statement}
    defaults: list[str] = []
    questions: list[str] = []
    for f in NUMERIC_FIELDS:
        if f in accepted and not f.startswith("supply."):
            req[f] = accepted[f]
    if "fieldbus_protocol" in accepted:
        req["fieldbus_protocol"] = accepted["fieldbus_protocol"]
    supply = {k.split(".")[1]: accepted[k] for k in ("supply.current_type", "supply.voltage_v", "supply.phases")
              if k in accepted}
    if supply.get("current_type") == "dc" and "phases" not in supply:
        supply["phases"] = 0
        defaults.append("直流供电，相数按 schema 约定记 0")
    if supply:
        if len(supply) == 3:
            if (supply["current_type"] == "dc") != (supply["phases"] == 0):
                rejected.append({"field": "supply", "reason": "供电类型与相数矛盾"})
                questions.append(QUESTIONS["supply"])
            else:
                req["supply"] = supply
        else:
            missing = [k for k in ("current_type", "voltage_v", "phases") if k not in supply]
            rejected.append({"field": "supply", "reason": f"供电信息不全（缺 {', '.join(missing)}），未采用"})
            questions.append(QUESTIONS["supply"])
    if "safety_factor" not in req:
        req["safety_factor"] = DEFAULT_SAFETY_FACTOR
        defaults.append(f"安全系数未说明，按默认值 {DEFAULT_SAFETY_FACTOR}（ADR-0008）")
    questions[:0] = [QUESTIONS[f] for f in REQUIRED if f not in req]  # 必填项的追问放在最前
    if "output_torque_peak_nm" in req and "output_torque_cont_nm" in req \
            and req["output_torque_peak_nm"] < req["output_torque_cont_nm"]:
        rejected.append({"field": "output_torque_peak_nm", "reason": "峰值扭矩小于连续扭矩，请确认"})
        questions.append("峰值扭矩小于连续扭矩，请确认两者")
        req.pop("output_torque_peak_nm")
    status = "ok" if all(f in req for f in REQUIRED) else "needs_input"
    if status == "ok":
        errs = schema_errors("requirement.schema.json", req)
        if errs:
            status = "needs_input"
            rejected.append({"field": None, "reason": "需求不符合 schema：" + "；".join(errs[:3])})
    unclear = [u for u in (tool_input.get("unclear") or []) if isinstance(u, str)] if isinstance(tool_input, dict) \
        else []
    return {"status": status, "requirement": req, "basis": basis, "defaults": defaults, "rejected": rejected,
            "questions": questions, "unclear": unclear}


def parse(statement: str, client: LLMClient | None = None, *, model: str = DEFAULT_MODEL) -> dict:
    if not isinstance(statement, str) or not statement.strip():
        raise ValueError("需求原话不能为空")
    client = client or RecordedClient(RECORDINGS_DIR)
    response = client.complete(build_request(statement.strip(), model=model))
    result = interpret(statement.strip(), response.get("tool_input") or {})
    result["llm"] = {"model": model, "prompt_version": PROMPT_VERSION, "response_id": response.get("id"),
                     "simulated": bool(response.get("simulated"))}
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="一句话需求 → 结构化需求（ADR-0037）")
    p.add_argument("statement")
    p.add_argument("--record", action="store_true", help="真实调用 LLM 并录制（需要 ANTHROPIC_API_KEY）")
    args = p.parse_args(argv)
    if args.record:
        from ingest.llm_extract import AnthropicClient

        client: LLMClient = AnthropicClient(record_dir=RECORDINGS_DIR)
    else:
        client = RecordedClient(RECORDINGS_DIR)
    result = parse(args.statement, client)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
