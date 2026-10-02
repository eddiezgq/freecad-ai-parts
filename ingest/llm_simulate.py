"""模拟 LLM 响应（ADR-0021）：由模拟规格书的答案生成，只用来检验抽取的代码核对流程。

模拟响应在抽取结果中标记 extractor.simulated = true，不得计入准确率评测（#31）。
"""

from __future__ import annotations

import copy
import re

from ingest.llm_extract import targets
from ingest.synthetic import FIELDS, row_label

_RANGE = re.compile(r"–| ~ ")
_LIST = re.compile(r", | / ")


def _number(text: str) -> float:
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    return float(nums[-1])


def proposals_from_answer(answer: dict) -> list[dict]:
    """答案中印出的每一行 → 对每个可抽取的 target 各一条“读对了”的提议。"""
    category, lang, layout = answer["category"], answer["lang"], answer["layout"]
    fields = {f.key: f for f in FIELDS[category]}
    known = targets(category)
    out = []
    for e in answer["fields"]:
        label = row_label(e, lang, layout)
        if "row" in e:  # 多型号目录：引用整行（ingest.synthetic_multi）
            quote = " ".join(e["row"])
        else:
            quote = " ".join([label, e["text"]] + ([e["unit"] or "—"] if layout == "three_col" else []))
        expected = e["expected"]
        for tgt in e["paths"]:
            if tgt not in known:
                continue
            spec = known[tgt][0]
            p = {
                "target": tgt, "printed_label": e["name"], "printed_text": e["text"], "printed_unit": e["unit"],
                "page": e["page"], "quote": quote, "confidence": 0.95,
            }
            if e.get("condition"):
                p["condition"] = e["condition"]
            numeric = spec.kind in ("number", "integer") and spec.enum is None
            if numeric and "min" in expected:
                lo, hi = _RANGE.split(e["text"])
                p["min"], p["max"] = _number(lo), _number(hi)
            elif numeric:
                p["value"] = _number(e["text"])
            else:
                p["value"] = expected["value"]
            if fields[e["key"]].vocab is None and isinstance(expected.get("value"), list):
                p["value"] = _LIST.split(e["text"])
            out.append(p)
    return out


def simulated_response(answer: dict, proposals: list[dict] | None = None, *, with_identity: bool = True) -> dict:
    """组装成客户端返回的格式；proposals 为空时用“全部读对”的提议。"""
    tool_input: dict = {"items": copy.deepcopy(proposals if proposals is not None else proposals_from_answer(answer))}
    if with_identity:
        comp = answer["component"]
        tool_input["vendor"], tool_input["model"] = comp["vendor"], comp["model"]
    return {"id": f"sim-{answer['datasheet_id']}", "tool_input": tool_input, "simulated": True}


class SimulatedClient:
    """不看请求内容，直接返回给定的模拟响应。"""

    def __init__(self, response: dict):
        self.response = response
        self.requests: list[dict] = []

    def complete(self, request: dict) -> dict:
        self.requests.append(request)
        return copy.deepcopy(self.response)
