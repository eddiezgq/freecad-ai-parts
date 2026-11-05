# -*- coding: utf-8 -*-
"""电路分析计算书（第 79 轮）：题目、参数、网表、读数与公式对照、曲线截图（浏览器截）、容差分析、说明。Word，与其他 CAE 报告同一套。"""
import base64
import datetime as dt
import io


def _fmt(v, unit=""):
    if v is None:
        return "—"
    a = abs(v)
    for k, s in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"), (1e-6, "μ"), (1e-9, "n"), (1e-12, "p")):
        if unit and a >= k:
            return "{:.4g} {}{}".format(v / k, s, unit)
    return "{:.4g} {}".format(v, unit).strip()


def build(b, rows, meas, images=(), mc=None, who=""):
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    d = Document()
    st = d.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    for name in ("Title", "Heading 1"):
        d.styles[name].element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "黑体")
    for sec in d.sections:
        sec.left_margin = sec.right_margin = Cm(2.2)

    def table(data):
        t = d.add_table(rows=len(data), cols=len(data[0]))
        t.style = "Table Grid"
        for i, r in enumerate(data):
            for k, v in enumerate(r):
                t.cell(i, k).text = str(v)
                if i == 0:
                    for run in t.cell(i, k).paragraphs[0].runs:
                        run.bold = True
        d.add_paragraph()

    d.add_heading("电路分析计算书：例题 {} {}".format(b["no"], b["title"]), 0)
    d.add_paragraph("关节伺服驱动板 DRV-JOINT　{}　{}　问渠数字工厂 · 电路分析（ngspice）".format(who, dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    d.add_heading("一、问题", 1)
    d.add_paragraph(b["question"])
    d.add_heading("二、参数（示例值）", 1)
    labels = {p["key"]: p["label"] for p in b["param_defs"]}
    table([["参数", "取值"]] + [[labels.get(k, k), "{:g}".format(v)] for k, v in b["params"].items()])
    if b.get("derived"):
        table([["由参数算出", "值"]] + [[k, "—" if v is None else str(v)] for k, v in b["derived"].items()])
    d.add_heading("三、读数与公式对照", 1)
    table([["读数", "仿真", "公式", "差", "允许", "结论"]] + [
        [r["label"], _fmt(r["sim"], r["unit"]), _fmt(r["formula"], r["unit"]),
         "—" if r["diff"] is None else "{:.2%}".format(r["diff"]), "{:.0%}".format(r["allow"]), "✓" if r["ok"] else "✗"] for r in rows])
    if b.get("note_formula"):
        d.add_paragraph("说明：" + b["note_formula"])
    for im in images or []:
        try:
            raw = base64.b64decode(str(im.get("data", "")).split(",", 1)[-1])
            d.add_picture(io.BytesIO(raw), width=Cm(15.5))
            d.add_paragraph(im.get("caption") or "")
        except Exception:  # noqa: BLE001 - 截图坏了就跳过
            pass
    if mc:
        d.add_heading("四、容差分析（蒙特卡洛）", 1)
        d.add_paragraph("元件按容差均匀取值，跑 {} 次（随机种子 {}）：读数 {} 均值 {:.5g}，标准差 {:.3g}，3σ 区间 [{:.5g}, {:.5g}]，名义值 {:.5g}。".format(
            mc.get("n"), mc.get("seed"), mc.get("meas"), mc.get("mean", 0), mc.get("std", 0), mc.get("lo3", 0), mc.get("hi3", 0), mc.get("nominal") or 0))
    d.add_heading("五、网表", 1)
    for an, net in b["netlists"].items():
        d.add_paragraph("【{}】".format(an))
        p = d.add_paragraph(net)
        for run in p.runs:
            run.font.name = "Consolas"
            run.font.size = Pt(8)
    d.add_heading("六、局限", 1)
    d.add_paragraph("器件用通用模型（运放宏模型、VDMOS、理想开关），参数是示例值，不代表任何厂商的器件；结果用于教学和方案比较，选型以器件手册为准。")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
