# -*- coding: utf-8 -*-
"""计算书（第 104 轮）：一份设计（或变体）→ 每个功能块的输入、公式、结果、判定、仿真对照、出处，写成 Markdown 和网页。

    python3 -m wqeda.calcbook <design.yaml | variant.yaml> --out <文件夹> [--no-sim]

计算和判定来自功能块的计算器（纯函数）；仿真核对用 ngspice（wqeda/sim.py）。不联网、不调 AI。
同一份设计、同一版 ngspice，每次生成的内容一样（不写生成时间）。"""

from __future__ import annotations

import argparse
import html
import os

from . import blocks, parts
from .blocks import common as c
from .schema import design

STATUS = {c.PASS: "通过", c.FAIL: "不通过", c.UNKNOWN: "未知", c.PENDING: "待核对"}
FIELDS = {"value": "数值", "note": "说明", "pins": "引脚"}
PREFIX_UNITS = {"H", "F", "Ω", "Hz", "W", "V", "A", "s", "V/A"}


def q(value, unit=""):
    """数 + 单位，带 SI 前缀：2.38e-05 H → 23.81 µH"""
    if value is None:
        return "—"
    if isinstance(value, str):
        return value + (" " + unit if unit else "")
    if unit in PREFIX_UNITS and value != 0 and not (1 <= abs(value) < 1000):
        for pre, f in (("G", 1e9), ("M", 1e6), ("k", 1e3), ("m", 1e-3), ("µ", 1e-6), ("n", 1e-9), ("p", 1e-12)):
            if abs(value) >= f * 0.9999999:
                return "{:.4g} {}{}".format(value / f, pre, unit)
    return "{:.4g}{}".format(value, " " + unit if unit else "")


def load(path):
    doc = design.read_yaml(path)
    if isinstance(doc, dict) and doc.get("format") == design.VARIANT_FORMAT:
        base, var = design.load_variant(path)
        out, changes = design.apply_variant(base, var)
        return out, base, var, changes
    doc = design.load_design(path)
    return doc, None, None, []


def build(path, sim=True, devices=None):
    doc, base, var, changes = load(path)
    devices = devices or parts.Devices.load()
    plist = design.all_parts(doc)
    units = blocks.calculate(doc, devices, plist)
    sims = {}
    if sim:
        from . import sim as simmod

        sims = simmod.run(doc)
    for u in units:
        s = sims.get(u["type"])
        u["sim"] = s
        if s:
            u["checks"] = u["checks"] + s["rows"]
    count = {k: 0 for k in STATUS}
    for u in units:
        for ch in u["checks"]:
            count[ch["status"]] += 1
    srcs = [r.get("source") for u in units for r in u["checks"] + u["items"] if r.get("source")]
    used = sorted(
        m
        for m, e in devices.entries.items()
        if (e.get("datasheet") or {}).get("title") and any(e["datasheet"]["title"] in x for x in srcs)
    )
    book = {
        "name": doc["name"],
        "rev": (var or {}).get("rev", doc.get("rev", "A")),
        "title": doc.get("title"),
        "notice": doc.get("notice", ""),
        "spec": doc["spec"],
        "units": units,
        "count": count,
        "changes": changes,
        "devices": {m: devices.entries[m] for m in used},
        "diff": None,
    }
    if base is not None:
        book["diff"] = diff(base, doc, devices)
    return book


def diff(base, new, devices):
    """变体和底稿比：器件哪些字段变了；计算结果哪些变了"""
    pa = {p["ref"]: p for p in design.all_parts(base)}
    pb = {p["ref"]: p for p in design.all_parts(new)}
    rows = []
    for ref in pa:
        if ref in pb and pa[ref] != pb[ref]:
            for k in ("value", "note", "pins"):
                if pa[ref][k] != pb[ref][k]:
                    rows.append({"ref": ref, "field": FIELDS[k], "base": pa[ref][k], "new": pb[ref][k]})
    ca = {(u["type"], i["key"]): i for u in blocks.calculate(base, devices, list(pa.values())) for i in u["items"]}
    calc = []
    for u in blocks.calculate(new, devices, list(pb.values())):
        for i in u["items"]:
            old = ca.get((u["type"], i["key"]))
            if old and old["value"] != i["value"]:
                calc.append(
                    {
                        "block": u["name"],
                        "name": i["name"],
                        "base": q(old["value"], i["unit"]),
                        "new": q(i["value"], i["unit"]),
                    }
                )
    return {"parts": rows, "calc": calc}


# ------------------------------------------------------------------------------------------------- Markdown


def _md_cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def to_markdown(b):
    L = ["# 计算书：{}（{} 版）".format(b["name"], b["rev"]), ""]
    if b["title"]:
        L += [b["title"], ""]
    L += [
        "> {}".format(b["notice"]),
        "> 由问渠电子功能块计算器生成（第 104 轮）。判定：通过 / 不通过 / 未知（缺数据）/ 待核对"
        "（用到的器件数据还没人对照规格书核对，不算通过）。",
        "",
    ]
    s = b["spec"]
    L += [
        "## 规格",
        "",
        "| 项 | 值 |",
        "|---|---|",
        "| 母线电压 | {} |".format(q(s["bus_voltage_v"], "V")),
        "| 额定 / 峰值相电流 | {} / {} |".format(q(s["phase_current_a"], "A"), q(s.get("phase_current_peak_a"), "A")),
        "| 电流出处 | {} |".format(_md_cell(s.get("current_source", "—"))),
        "| 降额与余量规则（示例值） | {} |".format("，".join("{} {:g}".format(k, v) for k, v in s["derating"].items())),
        "| 目标工厂 / 验收等级 | {} / {} |".format(
            s.get("target_factory") or "未定", s.get("acceptance_class") or "未定"
        ),
        "",
    ]
    n = b["count"]
    L += ["## 结论", "", "通过 {pass} 项，不通过 {fail} 项，待核对 {pending} 项，未知 {unknown} 项。".format(**n), ""]
    if b["changes"]:
        L += ["## 相对底稿改了什么", ""] + ["- {}：{}".format(r, t) for r, t in b["changes"]] + [""]
    if b["diff"]:
        L += ["## 跟着变的器件", "", "| 位号 | 字段 | 原来 | 现在 |", "|---|---|---|---|"]
        L += [
            "| {ref} | {field} | {base} | {new} |".format(**{k: _md_cell(v) for k, v in r.items()})
            for r in b["diff"]["parts"]
        ]
        L += ["", "## 跟着变的计算结果", "", "| 功能块 | 量 | 原来 | 现在 |", "|---|---|---|---|"]
        L += ["| {block} | {name} | {base} | {new} |".format(**r) for r in b["diff"]["calc"]] + [""]
    for u in b["units"]:
        L += ["## {}（{}）".format(u["name"], u["name_en"]), "", "原理图页：{}".format(u["block"]), ""]
        if u["items"]:
            L += ["| 量 | 结果 | 公式 | 说明 |", "|---|---|---|---|"]
            L += [
                "| {} | {} | {} | {} |".format(
                    i["name"],
                    q(i["value"], i["unit"]),
                    _md_cell(i["formula"]),
                    _md_cell("；".join(x for x in (i["note"], i["source"]) if x)),
                )
                for i in u["items"]
            ]
            L.append("")
        L += ["| 判定 | 要求 | 实有 | 规则 | 结论 | 说明 |", "|---|---|---|---|---|---|"]
        L += [
            "| {} | {} | {} | {} | **{}** | {} |".format(
                ch["name"],
                q(ch["need"], ch["unit"]),
                q(ch["have"], ch["unit"]),
                _md_cell(ch["rule"]),
                STATUS[ch["status"]],
                _md_cell("；".join(x for x in (ch["note"], ch["source"]) if x)),
            )
            for ch in u["checks"]
        ]
        if u.get("sim"):
            L += [
                "",
                "仿真核对：数字工厂电路分析例题“{}”，参数 {}。{}".format(
                    u["sim"]["example"],
                    "，".join("{}={:g}".format(k, v) for k, v in u["sim"]["params"].items()),
                    u["sim"]["note"],
                ),
            ]
        L.append("")
    if b["devices"]:
        L += ["## 用到的器件数据", "", "| 器件 | 厂家 | 规格书 | 网址 |", "|---|---|---|---|"]
        for m, e in b["devices"].items():
            ds = e.get("datasheet", {})
            L.append(
                "| {} | {} | {} {} | {} |".format(
                    m, e.get("maker", ""), ds.get("title", ""), ds.get("revision", ""), ds.get("url", "")
                )
            )
        L += ["", "这些数值录入时没有逐页对照 PDF 核对，标“待核对”。核对后在 `eda/parts/` 里把 checked 改成 true。", ""]
    return "\n".join(L)


# ------------------------------------------------------------------------------------------------- 网页

CSS = """
:root{--ink:#1c2430;--muted:#5b6675;--line:#d9dee5;--bg:#fbfbf9;--paper:#fff;--pass:#1f7a4d;--fail:#b3261e;
--pend:#9a6400;--unk:#5b6675;--head:#0f3d5e}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--ink:#e4e8ee;--muted:#9aa5b3;--line:#2f3945;
--bg:#12171d;--paper:#181f27;--pass:#5fc48f;--fail:#ff8a80;--pend:#e3b25a;--unk:#9aa5b3;--head:#8fc3ea}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.65 "Noto Sans CJK SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:26px;margin:0 0 6px;color:var(--head)}h2{font-size:19px;margin:36px 0 10px;color:var(--head);
border-bottom:2px solid var(--line);padding-bottom:4px}.sub{color:var(--muted);margin:0 0 4px}
.note{background:var(--paper);border-left:4px solid var(--head);padding:10px 14px;margin:16px 0;color:var(--muted)}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;background:var(--paper);margin:6px 0 4px;font-size:14px}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{font-weight:600;color:var(--muted)}
td.n{font-variant-numeric:tabular-nums;white-space:nowrap}.s{font-weight:700;white-space:nowrap}
.pass{color:var(--pass)}.fail{color:var(--fail)}.pending{color:var(--pend)}.unknown{color:var(--unk)}
.tally{display:flex;gap:18px;flex-wrap:wrap;font-size:16px}.tally b{font-size:22px}
.f{font-family:"Cambria Math","STIX Two Math",serif;color:var(--muted)}
@media print{body{background:#fff}main{padding:0}.note{border-left-color:#000}}
"""


def _e(s):
    return html.escape(str(s))


def to_html(b):
    h = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>计算书 {} {}</title><style>{}</style></head><body><main>".format(_e(b["name"]), _e(b["rev"]), CSS),
        "<h1>计算书：{}（{} 版）</h1>".format(_e(b["name"]), _e(b["rev"])),
    ]
    if b["title"]:
        h.append("<p class='sub'>{}</p>".format(_e(b["title"])))
    h.append(
        "<div class='note'>{}<br>由问渠电子功能块计算器生成（第 104 轮）。判定：通过 / 不通过 / 未知（缺数据）/ "
        "待核对（用到的器件数据还没人对照规格书核对，不算通过）。</div>".format(_e(b["notice"]))
    )
    n = b["count"]
    h.append(
        "<div class='tally'>"
        + "".join(
            "<span class='{}'><b>{}</b> {}</span>".format(k, n[k], STATUS[k])
            for k in (c.PASS, c.FAIL, c.PENDING, c.UNKNOWN)
        )
        + "</div>"
    )
    s = b["spec"]
    rows = [
        ("母线电压", q(s["bus_voltage_v"], "V")),
        ("额定 / 峰值相电流", "{} / {}".format(q(s["phase_current_a"], "A"), q(s.get("phase_current_peak_a"), "A"))),
        ("电流出处", s.get("current_source", "—")),
        ("降额与余量规则（示例值）", "，".join("{} {:g}".format(k, v) for k, v in s["derating"].items())),
        (
            "目标工厂 / 验收等级",
            "{} / {}".format(s.get("target_factory") or "未定", s.get("acceptance_class") or "未定"),
        ),
    ]
    h.append(
        "<h2>规格</h2><div class='wrap'><table>"
        + "".join("<tr><th>{}</th><td>{}</td></tr>".format(_e(a), _e(v)) for a, v in rows)
        + "</table></div>"
    )
    if b["changes"]:
        h.append(
            "<h2>相对底稿改了什么</h2><ul>"
            + "".join("<li>{}：{}</li>".format(_e(r), _e(t)) for r, t in b["changes"])
            + "</ul>"
        )
    if b["diff"]:
        h.append(
            "<h2>跟着变的器件</h2><div class='wrap'><table>"
            "<tr><th>位号</th><th>字段</th><th>原来</th><th>现在</th></tr>"
            + "".join(
                "<tr><td>{ref}</td><td>{field}</td><td>{base}</td><td>{new}</td></tr>".format(
                    **{k: _e(v) for k, v in r.items()}
                )
                for r in b["diff"]["parts"]
            )
            + "</table></div>"
        )
        h.append(
            "<h2>跟着变的计算结果</h2><div class='wrap'><table>"
            "<tr><th>功能块</th><th>量</th><th>原来</th><th>现在</th></tr>"
            + "".join(
                "<tr><td>{block}</td><td>{name}</td><td class='n'>{base}</td><td class='n'>{new}</td></tr>".format(
                    **{k: _e(v) for k, v in r.items()}
                )
                for r in b["diff"]["calc"]
            )
            + "</table></div>"
        )
    for u in b["units"]:
        h.append(
            "<h2>{} <span class='sub'>{}</span></h2><p class='sub'>原理图页：{}</p>".format(
                _e(u["name"]), _e(u["name_en"]), _e(u["block"])
            )
        )
        if u["items"]:
            h.append(
                "<div class='wrap'><table><tr><th>量</th><th>结果</th><th>公式</th><th>说明</th></tr>"
                + "".join(
                    "<tr><td>{}</td><td class='n'>{}</td><td class='f'>{}</td><td>{}</td></tr>".format(
                        _e(i["name"]),
                        _e(q(i["value"], i["unit"])),
                        _e(i["formula"]),
                        _e("；".join(x for x in (i["note"], i["source"]) if x)),
                    )
                    for i in u["items"]
                )
                + "</table></div>"
            )
        h.append(
            "<div class='wrap'><table>"
            "<tr><th>判定</th><th>要求</th><th>实有</th><th>规则</th><th>结论</th><th>说明</th></tr>"
            + "".join(
                "<tr><td>{}</td><td class='n'>{}</td><td class='n'>{}</td><td>{}</td><td class='s {}'>{}</td>"
                "<td>{}</td></tr>".format(
                    _e(ch["name"]),
                    _e(q(ch["need"], ch["unit"])),
                    _e(q(ch["have"], ch["unit"])),
                    _e(ch["rule"]),
                    ch["status"],
                    STATUS[ch["status"]],
                    _e("；".join(x for x in (ch["note"], ch["source"]) if x)),
                )
                for ch in u["checks"]
            )
            + "</table></div>"
        )
        if u.get("sim"):
            h.append(
                "<p class='sub'>仿真核对：数字工厂电路分析例题“{}”，参数 {}。{}</p>".format(
                    _e(u["sim"]["example"]),
                    _e("，".join("{}={:g}".format(k, v) for k, v in u["sim"]["params"].items())),
                    _e(u["sim"]["note"]),
                )
            )
    if b["devices"]:
        h.append(
            "<h2>用到的器件数据</h2><div class='wrap'><table><tr><th>器件</th><th>厂家</th><th>规格书</th></tr>"
            + "".join(
                "<tr><td>{}</td><td>{}</td><td><a href='{}'>{} {}</a></td></tr>".format(
                    _e(m),
                    _e(e.get("maker", "")),
                    _e(e.get("datasheet", {}).get("url", "")),
                    _e(e.get("datasheet", {}).get("title", "")),
                    _e(e.get("datasheet", {}).get("revision", "")),
                )
                for m, e in b["devices"].items()
            )
            + "</table></div><p class='sub'>这些数值录入时没有逐页对照 PDF 核对，标“待核对”。</p>"
        )
    h.append("</main></body></html>")
    return "\n".join(h)


def write(path, out, sim=True):
    b = build(path, sim=sim)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "calc.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(b) + "\n")
    with open(os.path.join(out, "calc.html"), "w", encoding="utf-8") as f:
        f.write(to_html(b) + "\n")
    return b


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成计算书")
    ap.add_argument("design")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-sim", action="store_true")
    a = ap.parse_args(argv)
    b = write(a.design, a.out, sim=not a.no_sim)
    print("通过 {pass}、不通过 {fail}、待核对 {pending}、未知 {unknown}".format(**b["count"]))
    return 1 if b["count"][c.FAIL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
