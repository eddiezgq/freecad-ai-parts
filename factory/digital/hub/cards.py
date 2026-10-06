"""工艺文件生成器（第 13 轮 7.3（4）N2）：由一份工艺规程数据（数据格式 v2，见 std/SH-301_process.yaml）生成全套工艺文件。

- 机械加工工艺过程卡片：以工序为单位的全过程概貌；
- 机械加工工序卡片：每道机械加工工序一张，含工序简图（hub/sketch.py）、定位夹紧、工步、切削用量与工时；
- 检验卡片：图纸全部特性逐条列出检验方法、量检具、频次和记录方式，另附各工序的自检项目；
- 刀具卡片。

栏目参照 JB/T 9165.2《工艺规程格式》的机械加工工艺过程卡片和机械加工工序卡片，栏目名中英对照（第 13 轮 Q13）。
书（textbook/mfgtech）和数字工厂用同一个程序：书里的卡片样例与工厂里提交、审批、执行的是同一份数据。

    python3 -m hub.cards std/SH-301_process.yaml --out /tmp/cards      # 输出 HTML，装了 playwright 时另出 PDF，装了 python-docx 时另出 Word
"""
from __future__ import annotations

import math
import sys
from html import escape
from pathlib import Path

import yaml

try:
    from . import sketch as SK
except ImportError:  # 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sketch as SK  # type: ignore

L = {  # 栏目名：中文 + 英文
    "process_card": ("机械加工工艺过程卡片", "Machining Process Routing Sheet"),
    "op_card": ("机械加工工序卡片", "Machining Operation Sheet"),
    "insp_card": ("检验卡片", "Inspection Sheet"),
    "tool_card": ("刀具卡片", "Tool List"),
    "product_model": ("产品型号", "Product model"), "product_name": ("产品名称", "Product"),
    "drawing_no": ("零件图号", "Drawing No."), "part_name": ("零件名称", "Part name"),
    "material": ("材料牌号", "Material"), "blank_kind": ("毛坯种类", "Blank type"), "blank_size": ("毛坯外形尺寸", "Blank size"),
    "per_blank": ("每毛坯可制件数", "Parts per blank"), "per_unit": ("每台件数", "Qty per product"),
    "seq": ("工序号", "Op. No."), "op_name": ("工序名称", "Operation"), "op_content": ("工序内容", "Operation content"),
    "shop": ("车间", "Shop"), "equipment": ("设备", "Machine"), "tooling": ("工艺装备", "Tooling"),
    "t_setup": ("准终", "Setup"), "t_unit": ("单件", "Per piece"), "time": ("工时 / min", "Time / min"),
    "fixture": ("夹具", "Fixture"), "coolant": ("切削液", "Coolant"), "simul": ("同时加工件数", "Parts per cycle"),
    "step": ("工步号", "Step"), "step_content": ("工步内容", "Step content"), "step_tool": ("刀具 / 量具", "Tool / gauge"),
    "n": ("主轴转速 r/min", "Spindle r/min"), "vc": ("切削速度 m/min", "Cutting speed m/min"),
    "f": ("进给量 mm/r", "Feed mm/r"), "ap": ("背吃刀量 mm", "Depth of cut mm"), "passes": ("进给次数", "Passes"),
    "tb": ("机动", "Machining"), "ta": ("辅助", "Handling"),
    "sketch": ("工序简图", "Operation sketch"), "datum": ("定位基准", "Locating datum"), "clamping": ("装夹", "Workholding"),
    "char": ("检验项目", "Characteristic"), "req": ("技术要求", "Requirement"), "gauge": ("量检具", "Gauge"),
    "freq": ("检验频次", "Frequency"), "record": ("记录", "Record"), "no": ("序号", "No."),
    "tool_id": ("刀具号", "Tool ID"), "tool_name": ("名称", "Name"), "tool_spec": ("规格", "Specification"),
    "tool_ops": ("用于工序", "Used in op."), "tool_life": ("寿命 / 修磨", "Life / regrind"),
    "prepared": ("编制", "Prepared"), "checked": ("审核", "Checked"), "standardized": ("标准化", "Standardized"),
    "approved": ("批准", "Approved"), "page": ("第 {} 页 共 {} 页", "Page {} of {}"),
    "mark": ("标记", "Mark"), "count": ("处数", "Qty"), "ecn": ("更改文件号", "Change notice"), "sign": ("签字", "Sign"),
    "date": ("日期", "Date"), "doc_no": ("文件编号", "Doc. No."), "rev": ("版本", "Rev."),
    "op_insp": ("工序检验（操作者自检与巡检）", "In-process inspection (operator & patrol)"),
    "final_insp": ("终检（图纸全部特性）", "Final inspection (all drawing characteristics)"),
    "key": ("★ 关键特性", "★ key characteristic"),
}


def lab(key, br=True):
    zh, en = L[key]
    return f"{escape(zh)}<br><small>{escape(en)}</small>" if br else f"{zh} {en}"


def load(path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 由切削用量算转速与机动时间（每个数都由程序算，不手填）
def step_values(st: dict) -> dict:
    """工步的转速 n、切削速度、进给、背吃刀量、进给次数、机动时间 t_b 与辅助时间 t_a（min）。"""
    out = {"n": None, "vc": st.get("vc"), "f": st.get("f"), "ap": st.get("ap"), "passes": st.get("passes"),
           "tb": st.get("tb_min"), "ta": st.get("ta_min")}
    kind = st.get("op")
    vc = st.get("vc")
    if kind == "face":
        n = 1000 * vc / (math.pi * st["d"])
        out.update(n=n, tb=(st["d"] / 2 + 2) / (n * st["f"]) * st.get("passes", 1))
    elif kind == "drill":
        n = 1000 * vc / (math.pi * st["d"])
        out.update(n=n, tb=st["depth"] / (n * st["f"]), passes=1)
    elif kind == "turn":
        pd = st["passes_detail"]                 # [[切前直径, 背吃刀量, 走刀长度（含切入切出）], ...]
        ns = [1000 * vc / (math.pi * d) for d, _, _ in pd]
        tb = sum(Lw / (n * st["f"]) for (d, ap, Lw), n in zip(pd, ns))
        aps = sorted({ap for _, ap, _ in pd})
        out.update(n=(min(ns), max(ns)), tb=tb, passes=len(pd), ap=aps[0] if len(aps) == 1 else (aps[0], aps[-1]))
    elif kind == "keyway":
        n = 1000 * vc / (math.pi * st["d"])
        vf = st["fz"] * st["z"] * n
        out.update(n=n, f=st["fz"] * st["z"], ap=st.get("ap_layer"),
                   passes=st.get("layers"), tb=st["layers"] * st["travel"] / vf, vf=vf)
    if st.get("tb_min") is not None:
        out["tb"] = st["tb_min"]
    return out


def op_basic_time(op: dict) -> float:
    return sum((step_values(s)["tb"] or 0) for s in op.get("steps") or [])


# ---------------------------------------------------------------- 检查（生成之前；AI 工艺评审员也调用）
def check(plan: dict) -> list[str]:
    """数据格式 v2 的完整性：返回问题列表（空表示可以生成全套卡片）。"""
    probs = []
    tools = {t["id"] for t in plan.get("tool_list") or []}
    gauges = {g["id"] for g in plan.get("gauges") or []}
    chars = {c["id"]: c for c in plan.get("characteristics") or []}
    finals = [o for o in plan["operations"] if o.get("final_inspection")]
    if not finals:
        probs.append("没有终检工序（final_inspection: true）。")
    covered = {i["char"] for o in finals for i in o.get("inspect") or []}
    for cid, c in chars.items():
        if cid not in covered:
            probs.append(f"图纸特性 {cid}“{c['name']}”在终检里没有检验项目。")
    for o in plan["operations"]:
        if "minutes" not in o:
            probs.append(f"工序 {o['seq']} 没有单件工时。")
        for s in o.get("steps") or []:
            t = s.get("tool")
            if t and t.startswith("T") and t[1:].isdigit() and t not in tools:
                probs.append(f"工序 {o['seq']} 工步 {s['step']} 的刀具 {t} 不在刀具卡里。")
            g = s.get("gauge")
            if g and g.startswith("G") and g[1:].isdigit() and g not in gauges:
                probs.append(f"工序 {o['seq']} 工步 {s['step']} 的量具 {g} 不在量具表里。")
        for i in o.get("inspect") or []:
            g = i.get("gauge", "")
            if g.startswith("G") and g[1:].isdigit() and g not in gauges:
                probs.append(f"工序 {o['seq']} 检验项目“{i['char']}”的量具 {g} 不在量具表里。")
        tb = op_basic_time(o)
        if tb and tb > o.get("minutes", 0):
            probs.append(f"工序 {o['seq']} 各工步机动时间合计 {tb:.1f} min，大于单件工时 {o.get('minutes')} min。")
    return probs


# ---------------------------------------------------------------- HTML
CSS = """
@page { size: A4 landscape; margin: 9mm; }
body { font-family: 'Noto Sans CJK SC','Noto Sans SC','Microsoft YaHei',sans-serif; color:#1d2327; margin:0; background:#fff; }
.card { page-break-after: always; break-after: page; padding: 0; margin: 0 auto 18px; max-width: 279mm; }
.card:last-child { page-break-after: auto; break-after: auto; }
table { border-collapse: collapse; width: 100%; table-layout: fixed; }
td, th { border: 1px solid #1d2327; padding: 1px 3px; font-size: 8.3pt; line-height: 1.15; vertical-align: middle; word-wrap: break-word; }
th { font-weight: 600; background: #f3f5f6; }
small { font-size: 7pt; color: #4a5560; font-weight: normal; }
.title { font-size: 15pt; font-weight: 700; text-align: center; letter-spacing: 2px; }
.title small { font-size: 8.5pt; letter-spacing: 0; display:block; }
.c { text-align: center; } .r { text-align: right; } .l { text-align: left; }
.sketch { text-align: center; padding: 2px; } .sketch svg { width: 100%; height: auto; max-height: 54mm; }
.foot td { font-size: 8.5pt; height: 15px; }
.star { color: #b5443b; font-weight: 700; }
.note { font-size: 8pt; color: #4a5560; margin-top: 3px; }
"""


def _fmt(v, nd=0):
    if v is None or v == "":
        return ""
    if isinstance(v, tuple):
        return "–".join(_fmt(x, nd) for x in v)
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return escape(str(v))


def _head(plan, kind, page, pages, extra_rows=""):
    d = plan["doc"]
    b = plan["blank"]
    return f"""<table>
<colgroup><col style="width:17%"><col style="width:11%"><col style="width:13%"><col style="width:11%"><col style="width:16%"><col style="width:11%"><col style="width:10%"><col style="width:11%"></colgroup>
<tr><td rowspan="2" class="c"><b>{escape(d['factory'])}</b></td><td rowspan="2" colspan="3" class="title">{escape(L[kind][0])}<small>{escape(L[kind][1])}</small></td>
<th>{lab('product_model')}</th><td class="c">{escape(d['product_model'])}</td><th>{lab('drawing_no')}</th><td class="c">{escape(d['drawing_no'])}</td></tr>
<tr><th>{lab('product_name')}</th><td class="c">{escape(d['product_name'])}</td><th>{lab('part_name')}</th><td class="c">{escape(d['part_name'])}</td></tr>
<tr><th>{lab('material')}</th><td class="c">{escape(str(plan['material']))}</td><th>{lab('blank_kind')}</th><td class="c">{escape(b['kind'])}</td>
<th>{lab('blank_size')}</th><td class="c">{escape(b['spec'])}×{b['length_mm']}</td><th>{lab('doc_no')} / {lab('rev', False).split()[0]}</th>
<td class="c">{escape(d['number'])} / {escape(d['revision'])}<br><small>{L['page'][0].format(page, pages)}</small></td></tr>
{extra_rows}</table>"""


def _foot(plan):
    s = plan["doc"].get("signatures") or {}
    def sg(k):
        v = s.get(k) or {}
        return f"{escape(v.get('by', ''))} {escape(v.get('date', ''))}"
    ch = plan["doc"].get("changes") or []
    rows = "".join(f"<td class='c'>{escape(str(c.get(k, '')))}</td>" for c in ch[:1] for k in ("mark", "count", "ecn", "by", "date")) or "<td></td>" * 5
    return f"""<table class="foot" style="margin-top:-1px">
<tr><th>{lab('mark')}</th><th>{lab('count')}</th><th>{lab('ecn')}</th><th>{lab('sign')}</th><th>{lab('date')}</th>
<th>{lab('prepared')}</th><th>{lab('checked')}</th><th>{lab('standardized')}</th><th>{lab('approved')}</th></tr>
<tr>{rows}<td class="c">{sg('prepared')}</td><td class="c">{sg('checked')}</td><td class="c">{sg('standardized')}</td><td class="c">{sg('approved')}</td></tr>
</table>"""


def _equip(ws):
    parts = ws.split(" ")
    return parts[0], parts[-1]


def process_card(plan, page, pages) -> str:
    gauges = {g["id"]: g["name"] for g in plan.get("gauges") or []}
    tools = {t["id"]: t for t in plan.get("tool_list") or []}
    rows = []
    for o in plan["operations"]:
        name, eq = _equip(o["workstation"])
        tl = []
        if o.get("fixture"):
            tl.append(o["fixture"])
        for t in tools.values():
            if o["seq"] in t.get("ops", []):
                tl.append(f"{t['name']} {t['id']}")
        gs = sorted({i.get("gauge") for i in o.get("inspect") or [] if (i.get("gauge") or "") in gauges})
        if gs:
            tl.append("量具 " + "、".join(gs))
        content = o["content"] + (f"（{o['card']}）" if o.get("card") else "")
        rows.append(f"<tr><td class='c'>{o['seq']}</td><td class='c'>{escape(o['operation'].split(' ')[0])}<br><small>{escape(o['operation'].split(' ', 1)[1])}</small></td>"
                    f"<td class='l'>{escape(content)}</td><td class='c'>{escape(o.get('shop', ''))}</td>"
                    f"<td class='c'>{escape(name)}<br><small>{escape(eq)}</small></td><td class='l'>{'；'.join(escape(x) for x in tl)}</td>"
                    f"<td class='c'>{_fmt(o.get('setup_min'))}</td><td class='c'>{_fmt(o['minutes'])}</td></tr>")
    tot = sum(o["minutes"] for o in plan["operations"])
    rows.append(f"<tr><td colspan='6' class='r'>单件工时合计 Total per piece</td><td></td><td class='c'><b>{tot:g}</b></td></tr>")
    body = f"""<table style="margin-top:-1px">
<colgroup><col style="width:5%"><col style="width:9%"><col style="width:33%"><col style="width:6%"><col style="width:9%"><col style="width:26%"><col style="width:6%"><col style="width:6%"></colgroup>
<tr><th rowspan="2">{lab('seq')}</th><th rowspan="2">{lab('op_name')}</th><th rowspan="2">{lab('op_content')}</th><th rowspan="2">{lab('shop')}</th>
<th rowspan="2">{lab('equipment')}</th><th rowspan="2">{lab('tooling')}</th><th colspan="2">{lab('time')}</th></tr>
<tr><th>{lab('t_setup')}</th><th>{lab('t_unit')}</th></tr>
{''.join(rows)}</table>"""
    d = plan["doc"]
    extra = f"<tr><th>{lab('per_blank')}</th><td class='c'>{d['per_blank']}</td><th>{lab('per_unit')}</th><td class='c'>{d['per_unit']}</td><th>批量 <small>Batch</small></th><td class='c'>{d.get('batch', '')}</td><th>零件质量 <small>Mass</small></th><td class='c'>{plan['part'].get('mass_kg', '')} kg</td></tr>"
    return f"<section class='card'>{_head(plan, 'process_card', page, pages, extra)}{body}{_foot(plan)}</section>"


def op_card(plan, o, page, pages) -> str:
    tools = {t["id"]: t for t in plan.get("tool_list") or []}
    gauges = {g["id"]: g["name"] for g in plan.get("gauges") or []}
    name, eq = _equip(o["workstation"])
    extra = (f"<tr><th>{lab('shop')}</th><td class='c'>{escape(o.get('shop', ''))}</td><th>{lab('seq')}</th><td class='c'><b>{o['seq']}</b></td>"
             f"<th>{lab('op_name')}</th><td class='c'><b>{escape(o['operation'].split(' ')[0])}</b><br><small>{escape(o['operation'].split(' ', 1)[1])}</small></td>"
             f"<th>{lab('equipment')}</th><td class='c'>{escape(name)} {escape(eq)}</td></tr>"
             f"<tr><th>{lab('fixture')}</th><td colspan='3' class='l'>{escape(o.get('fixture', o.get('clamping', '')))}</td><th>{lab('coolant')}</th>"
             f"<td class='c'>{escape(o.get('coolant', ''))}</td><th>{lab('time')}</th><td class='c'>{lab('t_setup', False).split()[0]} {_fmt(o.get('setup_min'))} / {lab('t_unit', False).split()[0]} {_fmt(o['minutes'])}</td></tr>"
             f"<tr><th>{lab('datum')}</th><td colspan='3' class='l'>{escape(o.get('datum', ''))}</td><th>{lab('clamping')}</th><td colspan='3' class='l'>{escape(o.get('clamping', ''))}</td></tr>")
    kseq = next((x["seq"] for x in plan["operations"] if x["operation"].startswith("铣键槽")), None)
    svg = SK.shaft_sketch(plan["part"], o, keyway_done=bool(kseq and o["seq"] >= kseq)) if plan["part"].get("kind") == "shaft" else ""
    sk = f"<table style='margin-top:-1px'><tr><th style='width:4%'>{lab('sketch')}</th><td class='sketch'>{svg}</td></tr></table>"
    rows = []
    tb_sum = ta_sum = 0.0
    for st in o.get("steps") or []:
        v = step_values(st)
        t = st.get("tool", "")
        tool = f"{tools[t]['name']} {t}" if t in tools else t
        g = st.get("gauge", "")
        gauge = f"量具 {g}" if g in gauges else g
        tb_sum += v["tb"] or 0
        ta_sum += v["ta"] or 0
        n = v["n"]
        n_txt = (f"{n[0]:.0f}–{n[1]:.0f}" if isinstance(n, tuple) else f"{n:.0f}") if n else ""
        f_txt = (_fmt(v["f"], 2) if isinstance(v["f"], float) else _fmt(v["f"])) if v["f"] is not None else ""
        if st.get("op") == "keyway":
            f_txt = f"{st['fz']} mm/z<br><small>v<sub>f</sub> {v['vf']:.0f} mm/min</small>"
        ap = v["ap"]
        ap_txt = (f"{ap[0]:g}–{ap[1]:g}" if isinstance(ap, tuple) else f"{ap:g}") if ap is not None else ""
        note = f"<br><small>{escape(st['note'])}</small>" if st.get("note") else ""
        tb_txt = f"{v['tb']:.2f}" if v["tb"] else ""
        rows.append(f"<tr><td class='c'>{st['step']}</td><td class='l'>{escape(st['content'])}{note}</td><td class='l'>{escape(tool)}{'；' if tool and gauge else ''}{escape(gauge)}</td>"
                    f"<td class='c'>{n_txt}</td><td class='c'>{_fmt(v['vc'])}</td><td class='c'>{f_txt}</td><td class='c'>{ap_txt}</td>"
                    f"<td class='c'>{_fmt(v['passes'])}</td><td class='c'>{tb_txt}</td><td class='c'>{_fmt(v['ta'], 1) if v['ta'] else ''}</td></tr>")
    rows.append(f"<tr><td colspan='8' class='r'>机动时间合计 Σt<sub>b</sub>（由切削用量算出）；单件工时含辅助、布置工作地与休息时间，按企业工时标准 WQ-TS-01（教学示意值）</td>"
                f"<td class='c'><b>{tb_sum:.2f}</b></td><td class='c'>{ta_sum:g}</td></tr>" if tb_sum else "")
    steps = f"""<table style="margin-top:-1px">
<colgroup><col style="width:4%"><col style="width:34%"><col style="width:17%"><col style="width:7%"><col style="width:7%"><col style="width:7%"><col style="width:7%"><col style="width:5%"><col style="width:6%"><col style="width:6%"></colgroup>
<tr><th rowspan="2">{lab('step')}</th><th rowspan="2">{lab('step_content')}</th><th rowspan="2">{lab('step_tool')}</th><th rowspan="2">{lab('n')}</th>
<th rowspan="2">{lab('vc')}</th><th rowspan="2">{lab('f')}</th><th rowspan="2">{lab('ap')}</th><th rowspan="2">{lab('passes')}</th><th colspan="2">{lab('time')}</th></tr>
<tr><th>{lab('tb')}</th><th>{lab('ta')}</th></tr>{''.join(rows)}</table>"""
    insp = "".join(f"<tr><td class='l'>{escape(i['char'])}</td><td class='l'>{escape(gauges.get(i.get('gauge', ''), i.get('gauge', '')))}</td><td class='l'>{escape(i.get('freq', ''))}</td></tr>"
                   for i in o.get("inspect") or [])
    insp_t = (f"<table style='margin-top:-1px'><colgroup><col style='width:50%'><col style='width:28%'><col style='width:22%'></colgroup>"
              f"<tr><th>{lab('op_insp')}</th><th>{lab('gauge')}</th><th>{lab('freq')}</th></tr>{insp}</table>") if insp else ""
    return f"<section class='card'>{_head(plan, 'op_card', page, pages, extra)}{sk}{steps}{insp_t}{_foot(plan)}</section>"


def inspection_card(plan, page, pages) -> str:
    gauges = {g["id"]: g["name"] for g in plan.get("gauges") or []}
    chars = {c["id"]: c for c in plan.get("characteristics") or []}
    final = next(o for o in plan["operations"] if o.get("final_inspection"))
    rows = []
    for k, i in enumerate(final.get("inspect") or [], 1):
        c = chars.get(i["char"], {"name": i["char"], "spec": ""})
        star = "<span class='star'>★</span> " if c.get("key") else ""
        rec = "质量系统 <small>QMS</small>" if i.get("record") == "QMS" else "记录表 <small>sheet</small>"
        rows.append(f"<tr><td class='c'>{k}</td><td class='c'>{star}{escape(i['char'])}</td><td class='l'>{escape(c['name'])}</td><td class='l'>{escape(c.get('spec', ''))}</td>"
                    f"<td class='l'>{escape(gauges.get(i.get('gauge', ''), i.get('gauge', '')))}</td><td class='l'>{escape(i.get('freq', ''))}</td><td class='c'>{rec}</td></tr>")
    t1 = f"""<table style="margin-top:-1px">
<colgroup><col style="width:4%"><col style="width:6%"><col style="width:20%"><col style="width:24%"><col style="width:20%"><col style="width:14%"><col style="width:12%"></colgroup>
<tr><th colspan="7" class="l">{lab('final_insp')}（工序 {final['seq']}，{escape(final['workstation'])}）　<span class="star">{L['key'][0]}</span></th></tr>
<tr><th>{lab('no')}</th><th>特性<br><small>Char.</small></th><th>{lab('char')}</th><th>{lab('req')}</th><th>{lab('gauge')}</th><th>{lab('freq')}</th><th>{lab('record')}</th></tr>
{''.join(rows)}</table>"""
    rows2 = []
    for o in plan["operations"]:
        if o.get("final_inspection"):
            continue
        for i in o.get("inspect") or []:
            rows2.append(f"<tr><td class='c'>{o['seq']}</td><td class='l'>{escape(o['operation'].split(' ')[0])}</td><td class='l'>{escape(i['char'])}</td>"
                         f"<td class='l'>{escape(gauges.get(i.get('gauge', ''), i.get('gauge', '')))}</td><td class='l'>{escape(i.get('freq', ''))}</td></tr>")
    t2 = f"""<table style="margin-top:-1px">
<colgroup><col style="width:6%"><col style="width:10%"><col style="width:42%"><col style="width:24%"><col style="width:18%"></colgroup>
<tr><th colspan="5" class="l">{lab('op_insp')}</th></tr>
<tr><th>{lab('seq')}</th><th>{lab('op_name')}</th><th>{lab('char')}</th><th>{lab('gauge')}</th><th>{lab('freq')}</th></tr>{''.join(rows2)}</table>"""
    note = ("<div class='note'>首件检验：每批第一件及换刀、调整、停机修复后的第一件，按本工序全部项目检验并经检验员确认后才能继续加工。"
            "带 ★ 的关键特性的数据录入质量系统，用于控制图和过程能力分析。</div>")
    return (f"<section class='card'>{_head(plan, 'insp_card', page, pages)}{t1}{note}{_foot(plan)}</section>"
            f"<section class='card'>{_head(plan, 'insp_card', page + 1, pages)}{t2}{_foot(plan)}</section>")


def tool_card(plan, page, pages) -> str:
    rows = "".join(f"<tr><td class='c'>{escape(t['id'])}</td><td class='l'>{escape(t['name'])}</td><td class='l'>{escape(t['spec'])}</td>"
                   f"<td class='c'>{'、'.join(str(x) for x in t.get('ops', []))}</td><td class='l'>{escape(t.get('life', ''))}</td></tr>"
                   for t in plan.get("tool_list") or [])
    grows = "".join(f"<tr><td class='c'>{escape(g['id'])}</td><td class='l' colspan='4'>{escape(g['name'])}</td></tr>" for g in plan.get("gauges") or [])
    t = f"""<table style="margin-top:-1px">
<colgroup><col style="width:8%"><col style="width:14%"><col style="width:48%"><col style="width:10%"><col style="width:20%"></colgroup>
<tr><th>{lab('tool_id')}</th><th>{lab('tool_name')}</th><th>{lab('tool_spec')}</th><th>{lab('tool_ops')}</th><th>{lab('tool_life')}</th></tr>{rows}
<tr><th colspan="5" class="l">量检具 <small>Gauges</small></th></tr>{grows}</table>"""
    return f"<section class='card'>{_head(plan, 'tool_card', page, pages)}{t}{_foot(plan)}</section>"


def machining_ops(plan):
    return [o for o in plan["operations"] if o.get("steps") and not o.get("final_inspection") and not o.get("card")]


def html(plan: dict, title: str | None = None) -> str:
    ops = machining_ops(plan)
    pages = 1 + len(ops) + 3
    parts = [process_card(plan, 1, pages)]
    parts += [op_card(plan, o, i + 2, pages) for i, o in enumerate(ops)]
    parts.append(inspection_card(plan, pages - 2, pages))
    parts.append(tool_card(plan, pages, pages))
    t = title or f"{plan['doc']['part_name']} {plan['doc']['drawing_no']} 工艺文件"
    return (f"<!doctype html><html lang='zh'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{escape(t)}</title><style>{CSS}</style></head><body>{''.join(parts)}</body></html>")


# ---------------------------------------------------------------- Word（可编辑；工序简图转成 PNG 插入）
def docx(plan: dict, path) -> Path:
    import io
    import re

    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Mm, Pt
    from docx.oxml.ns import qn

    def strip(h):
        h = re.sub(r"<br\s*/?>", "\n", h)
        return re.sub(r"<[^>]+>", "", h).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")

    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Mm(297), Mm(210)
    for m in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, m, Mm(10))
    st = doc.styles["Normal"]
    st.font.size = Pt(9)
    rpr = st.element.get_or_add_rPr()
    rpr.get_or_add_rFonts().set(qn("w:eastAsia"), "Noto Sans CJK SC")

    def table_from_html(tbl_html):
        rows = re.findall(r"<tr>(.*?)</tr>", tbl_html, re.S)
        grid = []
        for r in rows:
            row = []
            for m in re.finditer(r"<(t[dh])([^>]*)>(.*?)</t[dh]>", r, re.S):
                cs = re.search(r"colspan=['\"]?(\d+)", m.group(2))
                rs = re.search(r"rowspan=['\"]?(\d+)", m.group(2))
                row.append((m.group(1), int(cs[1]) if cs else 1, int(rs[1]) if rs else 1, strip(m.group(3))))
            grid.append(row)
        # 列数：按第一行（计入行合并占位）
        occ = {}
        place = []
        ncol = 0
        for i, row in enumerate(grid):
            j = 0
            for kind, cs, rs, txt in row:
                while (i, j) in occ:
                    j += 1
                place.append((i, j, cs, rs, kind, txt))
                for di in range(rs):
                    for dj in range(cs):
                        occ[(i + di, j + dj)] = True
                j += cs
                ncol = max(ncol, j)
        t = doc.add_table(rows=len(grid), cols=max(ncol, 1))
        t.style = "Table Grid"
        for i, j, cs, rs, kind, txt in place:
            cell = t.cell(i, j)
            far = t.cell(min(i + rs - 1, len(grid) - 1), min(j + cs - 1, ncol - 1))
            if far is not cell and (rs > 1 or cs > 1):
                cell = cell.merge(far)
            cell.text = txt.strip()
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(8)
                    r.bold = kind == "th"
        return t

    page = html(plan)
    for k, card in enumerate(re.findall(r"<section class='card'>(.*?)</section>", page, re.S)):
        if k:
            doc.add_page_break()
        for chunk in re.split(r"(<table.*?</table>)", card, flags=re.S):
            if chunk.startswith("<table"):
                svg = re.search(r"(<svg.*?</svg>)", chunk, re.S)
                if svg:
                    try:
                        import cairosvg
                        png = cairosvg.svg2png(bytestring=svg.group(1).encode("utf-8"), scale=2.5)
                        doc.add_paragraph("工序简图 Operation sketch")
                        doc.add_picture(io.BytesIO(png), width=Mm(250))
                    except Exception:  # noqa: BLE001
                        doc.add_paragraph("工序简图见 HTML / PDF 版。")
                    continue
                table_from_html(chunk)
            elif strip(chunk).strip():
                doc.add_paragraph(strip(chunk).strip())
    path = Path(path)
    doc.save(path)
    return path


def pdf(html_text: str, path) -> Path | None:
    """HTML → PDF（需要 playwright 与 Chromium；工厂镜像里没有，网页上用浏览器打印）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    path = Path(path)
    tmp = path.with_suffix(".tmp.html")
    tmp.write_text(html_text, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(tmp.resolve().as_uri())
        pg.pdf(path=str(path), landscape=True, format="A4", print_background=True, prefer_css_page_size=True)
        b.close()
    tmp.unlink()
    return path


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="由工艺规程数据生成全套工艺文件")
    ap.add_argument("plan")
    ap.add_argument("--out", default=".")
    a = ap.parse_args(argv)
    plan = load(a.plan)
    probs = check(plan)
    for p in probs:
        print("问题：", p)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{plan['item']}_工艺文件"
    h = html(plan)
    (out / f"{stem}.html").write_text(h, encoding="utf-8")
    made = [out / f"{stem}.html"]
    p = pdf(h, out / f"{stem}.pdf")
    if p:
        made.append(p)
    try:
        made.append(docx(plan, out / f"{stem}.docx"))
    except ImportError:
        pass
    for m in made:
        print(m)
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
