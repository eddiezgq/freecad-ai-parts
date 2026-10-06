# -*- coding: utf-8 -*-
"""把链条讲成人话（第 17 轮 B 期 B9）。

规则版：链条自带的说明句子，始终可用。
模型版：按地区用已配置的模型（国内 DeepSeek、美国 Claude，见 hub/llm.py）润色；只给它链条和数值，
输出里出现的每个数字都必须在输入里出现过，否则退回规则版。"""
import json
import re

NUM = re.compile(r"\d+(?:\.\d+)?")


def rules_text(a, ch):
    lines = [a["title"] + "。"] + [s.rstrip("。") + "。" for s in (ch or {}).get("summary", [])]
    hint = ((a.get("detail") or {}).get("hint") or "").strip()
    if hint:
        lines.append("建议：" + hint.rstrip("。") + "。")
    return "".join(lines)


def _numbers(text):
    return {n.lstrip("0") or "0" for n in NUM.findall(text)}


def narrate(llm, a, ch):
    base = rules_text(a, ch)
    if llm is None or not llm.available():
        return {"text": base, "by": "rules"}
    facts = {"异常": a["title"], "说明": (a.get("detail") or {}).get("text"), "链条": (ch or {}).get("summary", []),
             "对象": [n["label"] + " " + n["display"] for n in (ch or {}).get("nodes", [])][:40],
             "建议": (a.get("detail") or {}).get("hint")}
    system = ("你是工厂厂情中枢的助手。把下面的异常和因果链写成给车间负责人看的一段话（150 字以内，中文）："
              "先说发生了什么，再说为什么、影响到谁，最后一句建议。只能用给出的事实和数字，不增加、不推测。")
    src = json.dumps(facts, ensure_ascii=False)
    try:
        text, _ = llm.run(system, [{"role": "user", "content": src}], [], lambda n, x: None, max_turns=1)
    except Exception as e:  # noqa: BLE001
        return {"text": base, "by": "rules", "note": "模型调用失败（{}），用规则版".format(type(e).__name__)}
    text = (text or "").strip()
    extra = _numbers(text) - _numbers(src)
    if not text or extra:
        return {"text": base, "by": "rules", "note": "模型输出里有输入中没有的数字（{}），已退回规则版".format("、".join(sorted(extra))[:60])}
    return {"text": text, "by": llm.name}


def polish(llm, base, facts, instruction, limit=200):
    """通用的“有模型就改写成人话”（第 17 轮 D 期 D5）：推荐理由、日报周报的文字。
    数字逐个核对：输出里不能有输入（facts + base）里没有的数字，否则退回规则文字。"""
    if llm is None or not llm.available() or not base:
        return {"text": base, "by": "rules"}
    src = json.dumps({"规则文字": base, "事实": facts}, ensure_ascii=False, default=str)
    system = ("你是工厂厂情中枢的助手。{}（{} 字以内，中文）。只能用给出的事实和数字，不增加、不推测；"
              "保留全部单号和金额。").format(instruction, limit)
    try:
        text, _ = llm.run(system, [{"role": "user", "content": src}], [], lambda n, x: None, max_turns=1)
    except Exception as e:  # noqa: BLE001
        return {"text": base, "by": "rules", "note": "模型调用失败（{}），用规则版".format(type(e).__name__)}
    text = (text or "").strip()
    extra = _numbers(text) - _numbers(src)
    if not text or extra:
        return {"text": base, "by": "rules", "note": "模型输出里有输入中没有的数字（{}），已退回规则版".format("、".join(sorted(extra))[:60])}
    return {"text": text, "by": llm.name}
