# -*- coding: utf-8 -*-
"""AI 草稿的校验（第 105 轮 P3）：纯函数，不联网、不调 AI。

AI 的回答格式：
    {"spec":   [{"key", "value", "source", "quote", "why"}],
     "units":  [{"type", "params": [{"key", "value", "source", "quote", "why"}]}],
     "questions": [文字], "unsupported": [文字]}
source 只能是 requirement（需求原文，quote 必须是原文里的一段，并且含有这个数）、rule（规则推出，why 写用了哪些数）、
assumption（AI 假设，why 写成要人回答的问题）。必须有的规格（母线电压、额定 / 峰值相电流）不许是 AI 假设：
没给就 value 写 null、提问。不在目录里、超出范围、来源不合格的，一律退回（不进设计），并说明原因。"""

from __future__ import annotations

import re
import unicodedata

from .catalog import SOURCES


def _norm(s):
    s = unicodedata.normalize("NFKC", str(s or ""))
    return re.sub(r"\s+", "", s).casefold()


def _num_in(value, text):
    t = _norm(text)
    for form in {"{:g}".format(value), str(value), "{:.0f}".format(value) if float(value).is_integer() else ""}:
        if form and form in t:
            return True
    return False


def _value_ok(meta, v):
    kind, allowed = meta["kind"], meta["allowed"]
    if kind == "number":
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return "应是数"
        lo, hi = allowed
        if not lo <= v <= hi:
            return "超出本版支持的范围 {:g}–{:g}".format(lo, hi)
    elif kind == "choice":
        if v not in allowed:
            return "不在可选项里：{}".format("、".join(str(x) for x in allowed))
    elif kind == "text":
        if not isinstance(v, str) or len(v) > 200:
            return "应是一段不超过 200 字的文字"
    return None


def _entry(e, meta, requirement, required=False):
    """一条 AI 给的值 → (接受的条目或 None, 问题文字或 None)"""
    v, src = e.get("value"), e.get("source")
    quote, why = (e.get("quote") or "").strip(), (e.get("why") or "").strip()
    if v is None:
        return None, None
    if src not in SOURCES:
        return None, "来源应是需求原文、规则推出或 AI 假设"
    bad = _value_ok(meta, v)
    if bad:
        return None, bad
    if src == "requirement":
        if not quote or _norm(quote) not in _norm(requirement):
            return None, "标为需求原文，但引用的话不在需求里"
        if meta["kind"] == "number" and not _num_in(v, quote):
            return None, "标为需求原文，但引用的话里没有这个数"
    elif src == "rule" and not why:
        return None, "标为规则推出，但没写用了哪些数"
    elif src == "assumption":
        if required:
            return None, "这是必须有的规格，不能由 AI 假设；需求没给就应留空并提问"
        if not why:
            return None, "AI 假设要写成一个要人回答的问题"
    return {"value": v, "source": src, "quote": quote, "why": why}, None


def check(out, requirement, catalog):
    """→ {"spec": {键: 条目}, "params": {类型: {键: 条目}}, "missing": [必须有但没给的规格],
    "rejected": [{"where", "key", "value", "reason"}], "questions": [...], "unsupported": [...]}"""
    spec_meta = {m["key"]: m for m in catalog["spec"]}
    unit_meta = {u["type"]: {p["key"]: p for p in u["params"]} for u in catalog["units"]}
    fixed = {u["type"] for u in catalog["fixed_units"]}
    rep = {"spec": {}, "params": {}, "missing": [], "rejected": [], "questions": [], "unsupported": []}
    if not isinstance(out, dict):
        rep["rejected"].append({"where": "草稿", "key": "", "value": None, "reason": "回答不是 JSON 对象"})
        rep["missing"] = [k for k, m in spec_meta.items() if m["required"]]
        return rep
    for e in out.get("spec") or []:
        k = e.get("key") if isinstance(e, dict) else None
        if k not in spec_meta:
            rep["rejected"].append({"where": "规格", "key": k, "value": None, "reason": "不认识的规格字段"})
            continue
        got, why = _entry(e, spec_meta[k], requirement, spec_meta[k]["required"])
        if got:
            rep["spec"][k] = got
        elif why:
            rep["rejected"].append({"where": "规格", "key": k, "value": e.get("value"), "reason": why})
    for u in out.get("units") or []:
        t = u.get("type") if isinstance(u, dict) else None
        if t not in unit_meta:
            if t not in fixed:
                rep["rejected"].append({"where": "单元", "key": t, "value": None, "reason": "目录里没有这种单元"})
            elif u.get("params"):
                rep["rejected"].append({"where": t, "key": "", "value": None, "reason": "这种单元本版没有可以改的参数"})
            continue
        for e in u.get("params") or []:
            k = e.get("key") if isinstance(e, dict) else None
            if k not in unit_meta[t]:
                rep["rejected"].append({"where": t, "key": k, "value": None, "reason": "这个参数不能改或不存在"})
                continue
            got, why = _entry(e, unit_meta[t][k], requirement)
            if got:
                rep["params"].setdefault(t, {})[k] = got
            elif why:
                rep["rejected"].append({"where": t, "key": k, "value": e.get("value"), "reason": why})
    rep["missing"] = [k for k, m in spec_meta.items() if m["required"] and k not in rep["spec"]]
    rep["questions"] = [str(q)[:300] for q in out.get("questions") or []][:20]
    rep["unsupported"] = [str(q)[:300] for q in out.get("unsupported") or []][:20]
    return rep


def check_edits(edits, catalog):
    """人在页面上改的数（没有来源要求，来源记成“人填”）。
    {"spec": {键: 值}, "params": {类型: {键: 值}}} → (报告, 问题)"""
    spec_meta = {m["key"]: m for m in catalog["spec"]}
    unit_meta = {u["type"]: {p["key"]: p for p in u["params"]} for u in catalog["units"]}
    rep = {"spec": {}, "params": {}}
    probs = []
    for k, v in (edits.get("spec") or {}).items():
        if k not in spec_meta:
            probs.append("不认识的规格字段 {}".format(k))
        elif v is not None:
            bad = _value_ok(spec_meta[k], v)
            if bad:
                probs.append("{}：{}".format(spec_meta[k]["name"], bad))
            else:
                rep["spec"][k] = {"value": v, "source": "person", "quote": "", "why": ""}
    for t, prm in (edits.get("params") or {}).items():
        for k, v in (prm or {}).items():
            meta = unit_meta.get(t, {}).get(k)
            if meta is None:
                probs.append("{} 的 {} 不能改".format(t, k))
                continue
            bad = _value_ok(meta, v)
            if bad:
                probs.append("{}：{}".format(meta["name"], bad))
            else:
                rep["params"].setdefault(t, {})[k] = {"value": v, "source": "person", "quote": "", "why": ""}
    missing = [k for k, m in spec_meta.items() if m["required"] and k not in rep["spec"]]
    rep["missing"] = missing
    return rep, probs
