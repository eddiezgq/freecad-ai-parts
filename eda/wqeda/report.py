# -*- coding: utf-8 -*-
"""一块板子的一份报告（第 111 轮 P4）：电气（计算书）、工艺（含布局约束）、热，四种结论一起统计。

    python3 -m wqeda.report <design.yaml | variant.yaml> --factory <工艺能力表.yaml> --out <文件夹>
        [--board <板子.kicad_pcb>] [--gerber <光绘.zip> --bom <bom.csv> --cpl <pos.csv>] [--drc <drc.json>]
        [--no-sim] [--no-thermal]

板子默认用设计描述旁边 kicad/<名字>.kicad_pcb；变体没有自己的板子时用 --board 指定（例如 24 V 变体用 A 版的板子）。
给了光绘，就从光绘再查一遍，列出两条路共有的项结论是否一致。出 report.md、report.html、report.json。
判定全由确定性代码做；同一份输入每次生成的内容一样（不写生成时间）。"""

from __future__ import annotations

import argparse
import html
import json
import os
import warnings

from . import calcbook, parts
from .blocks import common as c
from .checks import basic, layout, process
from .readers import gerber as gerber_reader
from .readers import kicad as kicad_reader
from .schema import capability
from .schema import design as D

STATUS = calcbook.STATUS
ORDER = (c.PASS, c.FAIL, c.PENDING, c.UNKNOWN)


def _overall(statuses):
    st = set(statuses)
    return next((s for s in (c.FAIL, c.UNKNOWN, c.PENDING) if s in st), c.PASS)


def default_board(path):
    """设计描述旁边 kicad/ 里唯一的板子文件；没有或不止一个返回 None"""
    folder = os.path.join(os.path.dirname(os.path.abspath(path)), "kicad")
    found = sorted(f for f in os.listdir(folder) if f.endswith(".kicad_pcb")) if os.path.isdir(folder) else []
    return os.path.join(folder, found[0]) if len(found) == 1 else None


def drc_item(path):
    if not path or not os.path.exists(path):
        return basic._r("K1", "KiCad 设计规则检查（DRC）", c.UNKNOWN, "track", detail="没有 DRC 结果") | {
            "why": "KiCad 按工程里的线宽、间距、连通规则查一遍；有错误或没连上的焊盘，板子就不能做"
        }
    d = json.load(open(path, encoding="utf-8"))
    ok = d.get("errors") == 0 and d.get("unconnected") == 0
    return {
        "key": "K1",
        "name": "KiCad 设计规则检查（DRC）",
        "status": c.PASS if ok else c.FAIL,
        "why": "KiCad 按工程里的线宽、间距、连通规则查一遍；有错误或没连上的焊盘，板子就不能做",
        "value": "错误 {}、未连接 {}、警告 {}".format(d.get("errors"), d.get("unconnected"), d.get("warnings")),
        "limit": "错误 0、未连接 0",
        "unit": "",
        "at": [],
        "count": 0,
        "detail": "警告是丝印类问题，不影响电气和制造（工程设置里降为警告）",
    }


def build(path, cap_path, board_path=None, gerbers=None, drc=None, sim=True, thermal=True, devices=None, board=None):
    devices = devices or parts.Devices.load()
    doc_raw = D.read_yaml(path)
    var = None
    if doc_raw.get("format") == D.VARIANT_FORMAT:
        base, var = D.load_variant(path)
        doc, _ = D.apply_variant(base, var)
        x = D.expand(base, var)
    else:
        doc = D.load_design(path)
        x = D.expand(doc)
    cap = capability.load(cap_path)
    book = calcbook.build(path, sim=sim, devices=devices)
    board_path = board_path or default_board(path)
    if board is None:
        board = kicad_reader.read(board_path) if board_path else None
    sec = (
        board_checks(doc, x, board, cap, devices, thermal=thermal, book=book)
        if board is not None
        else {"process": [], "layout": [], "thermal": None}
    )
    proc, lay, th = sec["process"], sec["layout"], sec["thermal"]
    if drc is not False:
        proc.append(drc_item(drc))
    paths = None
    if gerbers and board is not None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            g = gerber_reader.read(gerbers["zip"], gerbers.get("bom"), gerbers.get("cpl"))
        gk = {r["key"]: r for r in basic.run(g, cap)["checks"] + process.run(g, cap, x)}
        paths = []
        for r in proc:
            other = gk.get(r["key"])
            if other is None:
                continue
            same = r["status"] == other["status"] or other["status"] == c.UNKNOWN
            paths.append(
                {
                    "key": r["key"],
                    "name": r["name"],
                    "kicad": r["status"],
                    "gerber": other["status"],
                    "kicad_value": r["value"],
                    "gerber_value": other["value"],
                    "agree": r["status"] == other["status"],
                    "consistent": same,
                }
            )
    count = {k: 0 for k in STATUS}
    for u in book["units"]:
        for ch in u["checks"]:
            count[ch["status"]] += 1
    for r in proc + lay:
        count[r["status"]] += 1
    for r in (th or {}).get("rows", []):
        if r["model"] in ("mosfet", "calc"):
            count[r["status"]] += 1
    return {
        "name": doc["name"],
        "rev": x["rev"],
        "title": doc.get("title"),
        "notice": doc.get("notice", ""),
        "factory": cap.get("factory"),
        "fictional_factory": bool(cap.get("fictional")),
        "board_file": os.path.relpath(board_path, os.path.dirname(os.path.abspath(path))) if board_path else None,
        "count": count,
        "status": _overall(k for k, v in count.items() if v),
        "electrical": {
            "count": book["count"],
            "units": [
                {
                    "type": u["type"],
                    "block": u.get("block"),
                    "name": u.get("name", u["type"]),
                    "checks": [
                        {
                            "name": ch["name"],
                            "status": ch["status"],
                            "need": ch.get("need"),
                            "have": ch.get("have"),
                            "unit": ch.get("unit", ""),
                            "rule": ch.get("rule", ""),
                        }
                        for ch in u["checks"]
                    ],
                }
                for u in book["units"]
            ],
        },
        "process": proc,
        "layout": lay,
        "paths": paths,
        "thermal": th,
        "spec": doc["spec"],
    }


def board_checks(doc, x, board, cap, devices, thermal=True, dx=None, book=None):
    """板子这一章（工艺、布局约束、热）：起草台也用它，按新规格查模板板子（不重新布线）"""
    proc = basic.run(board, cap)["checks"] + process.run(board, cap, x)
    lay = layout.run(board, x)
    th = None
    if thermal:
        from .thermal import board as tb

        th = tb.solve(board, doc, x, devices, dx=dx or tb.DX_MM, book=book)
    count = {k: 0 for k in STATUS}
    for r in proc + lay:
        count[r["status"]] += 1
    for r in (th or {}).get("rows", []):
        if r["model"] in ("mosfet", "calc"):
            count[r["status"]] += 1
    return {"process": proc, "layout": lay, "thermal": th, "count": count}


# ------------------------------------------------------------------------------------------------- 输出


def _factory(rep):
    f = rep["factory"] or ""
    return f + ("（虚构的示例工厂）" if rep["fictional_factory"] and "虚构" not in f else "")


def _v(r):
    v, lim, u = r.get("value"), r.get("limit"), r.get("unit") or ""

    def fmt(a):
        return "{:g}".format(a) if isinstance(a, float) else ("—" if a is None else str(a))

    if lim is None:
        return fmt(v) + (" " + u if v is not None and u else "")
    return "{} / 限 {}{}".format(fmt(v), fmt(lim), " " + u if u else "")


def _tj(r):
    """“结温 / 上限”一栏：功率管写结温；按计算书损耗算的（calc）写板子允许温度"""
    if r.get("tj_c") is not None:
        return "{} / {}".format(r["tj_c"], r["tj_max_c"])
    if r.get("t_limit_c") is not None:
        return "板温上限 {:g}".format(r["t_limit_c"])
    return "—"


def to_markdown(rep):
    L = ["# 板子报告：{}（{} 版）".format(rep["name"], rep["rev"]), ""]
    if rep["title"]:
        L += [rep["title"], ""]
    L += [
        "> {}".format(rep["notice"]),
        "> 由问渠电子统一检查引擎生成（第 111 轮）：电气、工艺、热一份报告。判定全由确定性代码做。",
        "",
    ]
    n = rep["count"]
    L += [
        "**结论：{}** —— 通过 {}、不通过 {}、待核对 {}、未知 {}".format(
            STATUS[rep["status"]], n[c.PASS], n[c.FAIL], n[c.PENDING], n[c.UNKNOWN]
        ),
        "",
    ]
    L += ["- 板子文件：`{}`".format(rep["board_file"] or "（没有）"), "- 工艺能力表：{}".format(_factory(rep)), ""]
    L += [
        "## 一、电气（计算书）",
        "",
        "每个功能块的计算和仿真核对，细节见计算书 {}。".format(rep.get("calc_link", "calc.md").replace(".html", ".md")),
        "",
        "| 功能块 | 通过 | 不通过 | 待核对 | 未知 |",
        "|---|---|---|---|---|",
    ]
    for u in rep["electrical"]["units"]:
        k = {s: sum(1 for ch in u["checks"] if ch["status"] == s) for s in ORDER}
        L.append("| {} | {} | {} | {} | {} |".format(u["name"], k[c.PASS], k[c.FAIL], k[c.PENDING], k[c.UNKNOWN]))
    L += ["", "## 二、工艺", "", "| 项 | 结论 | 量到 / 限值 | 说明 |", "|---|---|---|---|"]
    for r in rep["process"]:
        L.append(
            "| {} {} | {} | {} | {} |".format(
                r["key"], r["name"], STATUS[r["status"]], _v(r), calcbook._md_cell(r.get("detail") or r["why"])
            )
        )
    if rep["paths"]:
        L += [
            "",
            "两条路（KiCad 板子文件 / 光绘 + 物料清单 + 坐标）共有的项：",
            "",
            "| 项 | KiCad | 光绘 | 一致 |",
            "|---|---|---|---|",
        ]
        for p in rep["paths"]:
            L.append(
                "| {} {} | {} | {} | {} |".format(
                    p["key"],
                    p["name"],
                    STATUS[p["kicad"]],
                    STATUS[p["gerber"]],
                    "一致" if p["agree"] else ("光绘判不了" if p["consistent"] else "不一致"),
                )
            )
    L += ["", "### 布局约束", "", "| 约束 | 结论 | 量到 / 限值 | 说明 | 出处 |", "|---|---|---|---|---|"]
    for r in rep["layout"]:
        L.append(
            "| {} | {} | {} | {} | {} |".format(
                r["name"], STATUS[r["status"]], _v(r), calcbook._md_cell(r["detail"]), calcbook._md_cell(r["source"])
            )
        )
    th = rep["thermal"]
    L += ["", "## 三、热", ""]
    if not th or not th.get("rows"):
        L.append("没算：{}".format((th or {}).get("detail", "没有板子")))
    else:
        L += [
            "- 结论：{}；板上最高 {:.1f} ℃，总损耗 {:.2f} W".format(STATUS[th["status"]], th["t_max_c"], th["total_w"]),
            "- 条件：环境 {:g} ℃，两面对流 {:g} W/(m²·K)。{}".format(th["ambient_c"], th["h_w_m2k"], th["source"]),
            "- 导热：{}；{}".format(th["k_source"], th["grid"]),
            "- {}".format(th["detail"]),
            "",
            "| 位号 | 损耗 W | 其中 | 焊盘下板温 ℃ | 结温 ℃ / 上限 | 结论 | 说明 |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in th["rows"]:
            parts_ = "；".join("{} {:.3f}".format(a, b) for a, b in r["parts"])
            tj = _tj(r)
            st = STATUS[r["status"]] if r["model"] in ("mosfet", "calc") else "（只算损耗）"
            L.append(
                "| {} | {:.3f} | {} | {} | {} | {} | {} |".format(
                    r["ref"], r["p_w"], parts_, r.get("t_board_c"), tj, st, calcbook._md_cell("；".join(r["notes"]))
                )
            )
    return "\n".join(L)


def _cls(s):
    return {c.PASS: "pass", c.FAIL: "fail", c.PENDING: "pending", c.UNKNOWN: "unknown"}[s]


HEAT_JS = """
(function(){var d=JSON.parse(document.getElementById('tdata').textContent),cv=document.getElementById('heat');
if(!cv)return;var s=6,ctx=cv.getContext('2d');cv.width=d.nx*s;cv.height=d.ny*s;
var lo=Math.min.apply(null,d.t),hi=Math.max.apply(null,d.t);
function col(v){var u=(v-lo)/Math.max(1e-9,hi-lo),S=[[255,245,235],[253,174,107],[230,85,13],[127,39,4]];
var k=Math.min(2,Math.floor(u*3)),f=u*3-k,a=S[k],b=S[k+1];
return 'rgb('+[0,1,2].map(function(i){return Math.round(a[i]+(b[i]-a[i])*f);}).join(',')+')';}
for(var j=0;j<d.ny;j++)for(var i=0;i<d.nx;i++){ctx.fillStyle=col(d.t[j*d.nx+i]);ctx.fillRect(i*s,(d.ny-1-j)*s,s,s);}
document.getElementById('lo').textContent=lo.toFixed(0);document.getElementById('hi').textContent=hi.toFixed(0);})();
"""


def to_html(rep):
    e = html.escape
    h = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>板子报告 {} {}</title><style>{}"
        "canvas{{max-width:100%;image-rendering:pixelated;border:1px solid var(--line)}}"
        ".legend{{color:var(--muted);font-size:13px}}</style></head><body><main>".format(
            e(rep["name"]), e(rep["rev"]), calcbook.CSS
        ),
        "<h1>板子报告：{}（{} 版）</h1>".format(e(rep["name"]), e(rep["rev"])),
    ]
    if rep["title"]:
        h.append("<p class='sub'>{}</p>".format(e(rep["title"])))
    h.append(
        "<div class='note'>{}<br>由问渠电子统一检查引擎生成（第 111 轮）：电气、工艺、热一份报告。"
        "判定全由确定性代码做；"
        "待核对 = 用到的器件数据还没人对照规格书核对，不算通过。</div>".format(e(rep["notice"]))
    )
    n = rep["count"]
    h.append(
        "<div class='tally'>"
        + "".join("<span class='{}'><b>{}</b> {}</span>".format(_cls(k), n[k], STATUS[k]) for k in ORDER)
        + "</div>"
    )
    h.append(
        "<p class='sub'>板子文件 {}；工艺能力表：{}</p>".format(e(rep["board_file"] or "（没有）"), e(_factory(rep)))
    )

    h.append(
        "<h2>一、电气（计算书）</h2><p class='sub'>细节见<a href='{}'>计算书</a>。</p>".format(
            e(rep.get("calc_link", "calc.html"))
        )
        + "<div class='wrap'><table><tr><th>功能块</th><th>通过</th><th>不通过</th><th>待核对</th><th>未知</th></tr>"
    )
    for u in rep["electrical"]["units"]:
        k = {s: sum(1 for ch in u["checks"] if ch["status"] == s) for s in ORDER}
        h.append(
            "<tr><td>{}</td>{}</tr>".format(
                e(u["name"]), "".join("<td class='n {}'>{}</td>".format(_cls(s), k[s]) for s in ORDER)
            )
        )
    h.append("</table></div>")

    def rows(items, src=False):
        out = [
            "<div class='wrap'><table><tr><th>项</th><th>结论</th><th>量到 / 限值</th><th>说明</th>{}</tr>".format(
                "<th>出处</th>" if src else ""
            )
        ]
        for r in items:
            at = "".join("<br><small>{}</small>".format(e(" ".join(str(v) for v in a))) for a in r.get("at", [])[:5])
            out.append(
                "<tr><td>{} {}<br><small class='sub'>{}</small></td><td class='s {}'>{}</td><td class='n'>{}</td>"
                "<td>{}{}</td>{}</tr>".format(
                    e(r["key"]),
                    e(r["name"]),
                    e(r["why"]),
                    _cls(r["status"]),
                    STATUS[r["status"]],
                    e(_v(r)),
                    e(r.get("detail") or ""),
                    at,
                    "<td>{}</td>".format(e(r.get("source", ""))) if src else "",
                )
            )
        out.append("</table></div>")
        return out

    h.append("<h2>二、工艺</h2>")
    h += rows(rep["process"])
    if rep["paths"]:
        h.append(
            "<p class='sub'>两条路（KiCad 板子文件 / 光绘 + 物料清单 + 坐标）共有的项：</p><div class='wrap'><table>"
            "<tr><th>项</th><th>KiCad</th><th>光绘</th><th>一致</th></tr>"
        )
        for p in rep["paths"]:
            h.append(
                "<tr><td>{} {}</td><td class='{}'>{}</td><td class='{}'>{}</td><td>{}</td></tr>".format(
                    e(p["key"]),
                    e(p["name"]),
                    _cls(p["kicad"]),
                    STATUS[p["kicad"]],
                    _cls(p["gerber"]),
                    STATUS[p["gerber"]],
                    "一致" if p["agree"] else ("光绘判不了" if p["consistent"] else "不一致"),
                )
            )
        h.append("</table></div>")
    h.append("<h3>布局约束</h3>")
    h += rows(rep["layout"], src=True)

    th = rep["thermal"]
    h.append("<h2>三、热</h2>")
    if not th or not th.get("rows"):
        h.append("<p>没算：{}</p>".format(e((th or {}).get("detail", "没有板子"))))
    else:
        h.append(
            "<p><span class='s {}'>{}</span>；板上最高 {:.1f} ℃，总损耗 {:.2f} W。"
            "条件：环境 {:g} ℃，两面对流 {:g} W/(m²·K)。"
            "{}</p><p class='sub'>导热：{}；{}。{}</p>".format(
                _cls(th["status"]),
                STATUS[th["status"]],
                th["t_max_c"],
                th["total_w"],
                th["ambient_c"],
                th["h_w_m2k"],
                e(th["source"]),
                e(th["k_source"]),
                e(th["grid"]),
                e(th["detail"]),
            )
        )
        h.append(
            "<canvas id='heat' role='img' aria-label='板子温度分布'></canvas><p class='legend'>板子温度分布（顶视，"
            "<span id='lo'></span> ℃ 浅 → <span id='hi'></span> ℃ 深）</p>"
        )
        h.append(
            "<div class='wrap'><table><tr><th>位号</th><th>损耗 W</th><th>其中</th><th>焊盘下板温 ℃</th>"
            "<th>结温 ℃ / 上限</th><th>结论</th><th>说明</th></tr>"
        )
        for r in th["rows"]:
            tj = _tj(r)
            st = (
                "<span class='s {}'>{}</span>".format(_cls(r["status"]), STATUS[r["status"]])
                if r["model"] in ("mosfet", "calc")
                else "只算损耗"
            )
            h.append(
                "<tr><td>{}</td><td class='n'>{:.3f}</td><td>{}</td><td class='n'>{}</td><td class='n'>{}</td>"
                "<td>{}</td><td>{}</td></tr>".format(
                    e(r["ref"]),
                    r["p_w"],
                    e("；".join("{} {:.3f}".format(a, b) for a, b in r["parts"])),
                    r.get("t_board_c"),
                    tj,
                    st,
                    e("；".join(r["notes"])),
                )
            )
        h.append("</table></div>")
        h.append(
            "<script type='application/json' id='tdata'>{}</script><script>{}</script>".format(
                json.dumps(th["temps"], separators=(",", ":")), HEAT_JS
            )
        )
    h.append("</main></body></html>")
    return "\n".join(h)


def _json(rep):
    out = dict(rep)
    if out.get("thermal"):
        out["thermal"] = {k: v for k, v in out["thermal"].items() if k != "temps"}
    return out


def write(out, rep, book_path=None, sim=True):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(rep) + "\n")
    with open(os.path.join(out, "report.html"), "w", encoding="utf-8") as f:
        f.write(to_html(rep) + "\n")
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(_json(rep), f, ensure_ascii=False, indent=1, sort_keys=True, default=str)
        f.write("\n")
    if book_path:
        calcbook.write(book_path, out, sim=sim)


def main(argv=None):
    ap = argparse.ArgumentParser(description="一块板子的报告：电气、工艺、热")
    ap.add_argument("design")
    ap.add_argument("--factory", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--board")
    ap.add_argument("--gerber")
    ap.add_argument("--bom")
    ap.add_argument("--cpl")
    ap.add_argument("--drc")
    ap.add_argument("--no-sim", action="store_true")
    ap.add_argument("--no-thermal", action="store_true")
    ap.add_argument("--calc", help="已有计算书网页的相对链接（给了就不在报告文件夹里再写一份计算书）")
    a = ap.parse_args(argv)
    g = {"zip": a.gerber, "bom": a.bom, "cpl": a.cpl} if a.gerber else None
    rep = build(a.design, a.factory, a.board, g, a.drc, sim=not a.no_sim, thermal=not a.no_thermal)
    if a.calc:
        rep["calc_link"] = a.calc
    write(a.out, rep, None if a.calc else a.design, sim=not a.no_sim)
    n = rep["count"]
    print(
        "{}：通过 {}、不通过 {}、待核对 {}、未知 {}".format(
            STATUS[rep["status"]], n[c.PASS], n[c.FAIL], n[c.PENDING], n[c.UNKNOWN]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
