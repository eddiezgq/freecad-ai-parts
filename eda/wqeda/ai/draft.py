# -*- coding: utf-8 -*-
"""起草流程（第 105 轮 P3）：需求 → 模型起草 → 代码校验 → 套到模板上展开 → 计算器（和仿真）判定 → 摆给人看。

模型通过参数传进来（model(requirement, catalog, lang, feedback) → (回答 JSON, 记录编号)），服务里是网关，测试里是替身。
AI 的数只有通过校验才进设计；结论都由代码判。草稿不会自动写进任何设计文件：人确认后才下载。"""

from __future__ import annotations

import copy

import yaml

from .. import blocks, calcbook, parts
from ..blocks import common as c
from ..schema import design
from . import catalog as cat
from .check import check, check_edits

MAX_ROUNDS = 2


def for_model(catalog):
    """交给模型的目录：规格不带模板默认值（免得模型照抄），单元参数带（不改就沿用模板）"""
    out = copy.deepcopy(catalog)
    for s in out["spec"]:
        s.pop("default", None)
    return out


def apply(template, rep, requirement="", runs=()):
    """模板 + 通过校验的值 → 设计描述（带来源记录）；必须有的规格缺了返回 None"""
    if rep["missing"]:
        return None
    doc = copy.deepcopy(template)
    prov = {"spec": {}, "params": {}}
    for k, e in rep["spec"].items():
        doc["spec"][k] = e["value"]
        prov["spec"][k] = {x: e[x] for x in ("source", "quote", "why") if e.get(x)}
    for u in doc["blocks"]:
        for unit in u.get("units") or []:
            for k, e in rep["params"].get(unit["type"], {}).items():
                unit["params"][k] = e["value"]
                prov["params"].setdefault(unit["type"], {})[k] = {
                    x: e[x] for x in ("source", "quote", "why") if e.get(x)
                }
    doc["spec"]["example_values"] = True
    doc["name"] = template["name"] + "-DRAFT"
    doc["rev"] = "草稿"
    doc["title"] = "AI 起草的设计（待人确认）：{}".format(requirement[:60]) if requirement else "设计草稿（待人确认）"
    doc["notice"] = (
        "草稿：规格和参数由 AI 起草、人确认；电路由功能块生成，判定由代码做。板子层（摆放、铺铜）沿用模板，"
        "P4 再按新规格做布局。示例设计，不能直接投产。"
    )
    doc["draft"] = {"template": template["name"], "requirement": requirement, "runs": list(runs), "provenance": prov}
    return doc


def evaluate(doc, devices=None, sim=False):
    """设计描述 → 计算结果（和计算书网页、Markdown、YAML）"""
    devices = devices or parts.Devices.load()
    units = blocks.calculate(doc, devices, design.all_parts(doc))
    if sim:
        from .. import sim as simmod

        s = simmod.run(doc)
        for u in units:
            if u["type"] in s:
                u["sim"] = s[u["type"]]
                u["checks"] = u["checks"] + s[u["type"]]["rows"]
    count = {k: 0 for k in calcbook.STATUS}
    for u in units:
        for ch in u["checks"]:
            count[ch["status"]] += 1
    book = {
        "name": doc["name"],
        "rev": doc.get("rev", ""),
        "title": doc.get("title"),
        "notice": doc.get("notice", ""),
        "spec": doc["spec"],
        "units": units,
        "count": count,
        "changes": [],
        "devices": {},
        "diff": None,
    }
    fails = [
        {
            "block": u["name"],
            "name": ch["name"],
            "need": ch["need"],
            "have": ch["have"],
            "unit": ch["unit"],
            "rule": ch["rule"],
        }
        for u in units
        for ch in u["checks"]
        if ch["status"] == c.FAIL
    ]
    return {
        "count": count,
        "fails": fails,
        "html": calcbook.to_html(book),
        "markdown": calcbook.to_markdown(book),
        "yaml": to_yaml(doc),
    }


def to_yaml(doc):
    head = (
        "# 问渠电子设计描述（wqeda.design/1）——AI 起草、人确认的草稿。draft.provenance 记着每个数的来源：\n"
        "# requirement 需求原文 / rule 规则推出 / assumption AI 假设 / person 人填；没写来源的沿用模板。\n"
    )
    return head + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=200)


def run(requirement, model, template, lang="zh", devices=None, sim=False, rounds=MAX_ROUNDS):
    """→ {"catalog", "rounds": [{"answer", "run", "report", "result"}], "final": 最后一轮}"""
    catalog = cat.build(template)
    feedback, out = None, []
    for _ in range(max(1, rounds)):
        answer, rid = model(requirement, for_model(catalog), lang, feedback)
        rep = check(answer, requirement, catalog)
        doc = apply(template, rep, requirement, [r["run"] for r in out] + [rid])
        result = evaluate(doc, devices, sim) if doc else None
        out.append(
            {
                "answer": answer,
                "run": rid,
                "report": rep,
                "result": result,
                "passed": bool(result and not result["fails"] and not rep["rejected"]),
            }
        )
        if doc is None or (result and not result["fails"]):
            break  # 缺关键数据：等人回答，不再让模型猜；没有不通过：不用再改
        feedback = {"previous": answer, "fails": result["fails"]}
    return {"catalog": catalog, "rounds": out, "final": out[-1]}


def merge_edits(prev_report, values, catalog):
    """页面上的当前值 → 新报告：值没动的保留原来源，改了的记成“人填”"""
    rep, probs = check_edits(values, catalog)
    for k, e in rep["spec"].items():
        old = prev_report.get("spec", {}).get(k)
        if old and old["value"] == e["value"]:
            rep["spec"][k] = old
    defaults = {u["type"]: {p["key"]: p["default"] for p in u["params"]} for u in catalog["units"]}
    for t, prm in rep["params"].items():
        for k in list(prm):
            old = prev_report.get("params", {}).get(t, {}).get(k)
            if old and old["value"] == prm[k]["value"]:
                prm[k] = old
            elif not old and prm[k]["value"] == defaults.get(t, {}).get(k):
                del prm[k]  # 和模板一样、也不是 AI 给的：沿用模板，不记成人填
    rep["params"] = {t: prm for t, prm in rep["params"].items() if prm}
    return rep, probs
