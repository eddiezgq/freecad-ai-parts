# -*- coding: utf-8 -*-
"""问题单（第 112 轮 P5）：工厂给客户的工程问题单，机器能读（wqeda.issues/1，YAML），也给人看（Markdown）。

每条问题必须引用工厂端检查结果的编号（R1、R2……）；位号、检查项、位置由代码从被引用的结果里取，不由 AI 写。

设计端：python3 -m wqeda.issues <问题单.yaml> <design.yaml | variant.yaml>
          [--gerber <光绘.zip> --bom <bom.csv> --cpl <pos.csv> --factory <工艺能力表.yaml>]
  把每条问题对到设计描述（哪个器件、哪一层）；给了新的资料包就重新查一遍，判每条“已解决 / 还在”。
纯计算部分不联网、不调 AI。"""

from __future__ import annotations

import argparse
import sys

import yaml

from .schema import design as D

FORMAT = "wqeda.issues/1"
OPEN = ("fail", "unknown", "pending")
LAYER = {
    "D1": "电路层：物料编号、位号（物料清单和坐标由设计描述导出）",
    "D2": "电路层：物料清单",
    "D4": "板子层：摆放的面",
    "F1": "板子层：布线线宽、网络分类",
    "F2": "板子层：布线间距、网络分类",
    "F3-drill": "板子层：过孔、焊盘孔径",
    "F3-ring": "板子层：过孔、焊盘孔环",
    "F4": "板子层：封装焊盘",
    "F5": "板子层：铺铜、走线到板边",
    "F6": "板子层：摆放",
    "F7": "板子层：摆放角度（极性）",
    "F8": "板子层：摆放",
    "T1": "电路层：ICT 测试点规则",
    "C1": "板子层：大电流路径、铺铜；规格的电流",
    "P1": "板子层：板框外形（或拼板）",
    "P2": "电路层：器件选型（封装引脚间距）",
    "P3": "电路层：器件选型（封装焊盘）",
}


def build(results, drafted, factory="", package=""):
    """results = 工厂端检查结果（带 id）；drafted = [{cites:[R..], question, options:[…]}]。
    → (问题单, 被退回的条目)。引用不存在或引用的是通过项，退回"""
    by_id = {r["id"]: r for r in results}
    out, rejected = [], []
    for i, d in enumerate(drafted or [], 1):
        cites = [c for c in (d.get("cites") or []) if isinstance(c, str)]
        bad = [c for c in cites if c not in by_id or by_id[c]["status"] not in OPEN]
        q = str(d.get("question") or "").strip()
        if not cites or bad or not q:
            why = (
                "没引用检查结果"
                if not cites
                else ("引用的 {} 不存在或已通过".format("、".join(bad)) if bad else "没写问题")
            )
            rejected.append({"index": i, "reason": why, "item": d})
            continue
        refs = sorted({r for c in cites for r in by_id[c].get("refs") or []})
        out.append(
            {
                "id": "Q{}".format(len(out) + 1),
                "cites": cites,
                "keys": [by_id[c]["key"] for c in cites],
                "refs": refs,
                "question": q[:600],
                "options": [str(o)[:300] for o in (d.get("options") or [])][:6],
                "reply_required": bool(d.get("reply_required", True)),
            }
        )
    cited = sorted({c for it in out for c in it["cites"]}, key=lambda s: int(s[1:]))
    doc = {
        "format": FORMAT,
        "factory": factory,
        "package": package,
        "results": [
            {k: by_id[c].get(k) for k in ("id", "key", "name", "status", "value", "limit", "unit", "detail", "refs")}
            for c in cited
        ],
        "issues": out,
    }
    return doc, rejected


def validate(doc):
    p = []
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        return ["format 应为 {}".format(FORMAT)]
    ids = {r.get("id") for r in doc.get("results") or []}
    for it in doc.get("issues") or []:
        if not it.get("cites") or any(c not in ids for c in it["cites"]):
            p.append("问题 {} 引用的检查结果不在问题单里".format(it.get("id")))
        if not it.get("question"):
            p.append("问题 {} 没写问题".format(it.get("id")))
    return p


def to_markdown(doc):
    L = ["# 工程问题单", "", "工厂：{}；资料包：{}".format(doc.get("factory") or "—", doc.get("package") or "—"), ""]
    for it in doc["issues"]:
        L += ["## {} {}".format(it["id"], "（需要回复）" if it["reply_required"] else ""), "", it["question"], ""]
        if it["refs"]:
            L.append("- 位号：" + "、".join(it["refs"]))
        L.append("- 依据：" + "、".join("{} {}".format(c, k) for c, k in zip(it["cites"], it["keys"], strict=True)))
        L += (
            ["- 建议选项：" + "；".join("{}. {}".format(chr(65 + i), o) for i, o in enumerate(it["options"]))]
            if it["options"]
            else []
        )
        L.append("")
    L += ["---", "", "依据的检查结果：", ""]
    for r in doc["results"]:
        L.append("- {} {} {}：{}".format(r["id"], r["key"], r["name"], r.get("detail") or ""))
    return "\n".join(L)


def to_yaml(doc):
    return (
        "# 问渠贴片工程问题单（wqeda.issues/1）：每条引用检查结果编号；设计端用 python3 -m wqeda.issues 对到设计描述\n"
        + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=200)
    )


# ------------------------------------------------------------------------------------------------- 设计端


def match(doc, design_path, recheck=None):
    """问题单 → 设计描述：每条对到器件和层；recheck = 新资料包的检查结果（factory.check_package 的 results），
    给了就判每条是否已解决"""
    raw = D.read_yaml(design_path)
    if raw.get("format") == D.VARIANT_FORMAT:
        base, var = D.load_variant(design_path)
        x = D.expand(base, var)
    else:
        x = D.expand(D.load_design(design_path))
    parts = {q["ref"]: q for q in x["parts"]}
    now = {r["key"]: r for r in recheck or []}
    rows = []
    for it in doc["issues"]:
        found, hints = [], []
        for ref in it["refs"]:
            q = parts.get(ref)
            if q is None:
                hints.append("{} 不在设计描述里".format(ref))
                continue
            found.append(ref)
            if "D1" in it["keys"] and not q.get("item"):
                hints.append("{} 没有物料编号，所以没进物料清单（坐标里有它）".format(ref))
            where = x["placement"].get(ref)
            hints.append(
                "{}：功能块 {}，{} {}{}".format(
                    ref,
                    q.get("block"),
                    q["value"],
                    q["fp"].split(":")[-1],
                    "，摆在 ({:g}, {:g}) {}°".format(*where[:3]) if where else "",
                )
            )
        layers = sorted({LAYER.get(k, "—") for k in it["keys"]})
        state = "未复查"
        if recheck is not None:
            left = []
            for k in it["keys"]:
                r = now.get(k)
                if r is None:
                    continue
                if r["status"] in OPEN and (not it["refs"] or set(it["refs"]) & set(r.get("refs") or [])):
                    left.append(k)
            state = "还在（{}）".format("、".join(left)) if left else "已解决"
        rows.append(
            {
                "id": it["id"],
                "keys": it["keys"],
                "refs": it["refs"],
                "found": found,
                "layers": layers,
                "hints": hints,
                "state": state,
            }
        )
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="问题单对到设计描述；给了新资料包就判是否已解决")
    ap.add_argument("issues")
    ap.add_argument("design")
    ap.add_argument("--gerber")
    ap.add_argument("--bom")
    ap.add_argument("--cpl")
    ap.add_argument("--factory")
    a = ap.parse_args(argv)
    doc = D.read_yaml(a.issues)
    probs = validate(doc)
    if probs:
        print("\n".join(probs), file=sys.stderr)
        return 2
    recheck = None
    if a.gerber and a.factory:
        from . import factory
        from .schema import capability

        recheck = factory.check_package(a.gerber, capability.load(a.factory), a.bom, a.cpl)["results"]
    rows = match(doc, a.design, recheck)
    for r in rows:
        print("{} [{}] {}：{}".format(r["id"], "、".join(r["keys"]), r["state"], "；".join(r["layers"])))
        for h in r["hints"]:
            print("    " + h)
    return 0 if all(r["state"] in ("已解决", "未复查") for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
