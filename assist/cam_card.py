"""问渠CAM：工艺卡与程序单（ADR-0104 第 1 节卖点 4、第 2 节“报告”；C1）。

Word（.docx）一份，中英两种：
1. 表头：零件、材料（Kienzle 行与 ISO 材料组）、机床、数控系统与后处理（是否经实机验证）、整机仿真指纹与结论、编号 / 版本 / 日期；
2. 工序表：每道工序的刀号、刀具、vc、f 或 fz、ap、主轴转速、理由（AI 起草时）、核对结论；
3. 刀具清单：刀号、刀具库 id、名称、种类、直径或刀片、刀长、数据出处；
4. 程序单：每个程序的号、装夹、行数、时间（切削、快移、换刀、合计）、检查结论（错误、提示、未知各几条）；
5. 检查清单与 AI 起草说明（notes）；
6. 首件须空运行、单段试切确认；后处理未经实机验证时写明；编制 / 审核 / 批准。
每个印出来的数都记进出处账（`*.ledger.json`）：来自哪个文件（工艺草稿 draft、计算结果 result、刀具库 library）的哪一处。
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

from analysis.cam import tools as TL
from assist.fea_report import Ledger, fingerprint

LANGS = ("zh", "en")
TXT = {
    "title": ("数控加工工艺卡与程序单", "CNC Process Card and Program Sheet"),
    "draft": ("草稿：工艺由程序起草（AI 只在候选里挑刀、在刀具样本范围里定参数），须工艺员审核；首件须空运行、单段试切确认。",
              ("DRAFT: drafted by software (AI only picks among candidate tools within the tool catalogue ranges); "
               "must be reviewed by a process engineer. First part: dry run and single block.")),
    "head": ("基本信息", "General"), "ops": ("工序", "Operations"), "tools": ("刀具清单", "Tool list"),
    "progs": ("程序单", "Programs"), "checks": ("检查清单", "Checks"), "notes": ("起草说明", "Drafting notes"),
    "sign": ("审核", "Approval"),
    "part": ("零件", "Part"), "material": ("材料", "Material"), "machine": ("机床", "Machine"),
    "post": ("数控系统 / 后处理", "Control / post"), "sim": ("整机仿真", "Machine simulation"),
    "number": ("编号", "No."), "rev": ("版本", "Revision"), "date": ("日期", "Date"), "by": ("起草", "Drafted by"),
    "op_cols": (["序", "工序", "刀号", "刀具", "vc m/min", "f mm/r · fz mm", "ap mm", "S r/min（参考）", "理由", "核对"],
                ["#", "Operation", "T", "Tool", "vc m/min", "f mm/r · fz mm", "ap mm", "S rpm (ref.)", "Reason", "Check"]),
    "tool_cols": (["刀号", "刀具库 id", "名称", "种类", "直径 / 刀片", "刀长 mm", "出处"],
                  ["T", "Library id", "Name", "Kind", "Dia. / insert", "Length mm", "Source"]),
    "prog_cols": (["程序", "装夹", "行数", "切削 s", "快移 s", "换刀 s", "合计 s", "错误", "提示", "未知"],
                  ["Program", "Setup", "Lines", "Cut s", "Rapid s", "Tool s", "Total s", "Errors", "Warnings", "Unknown"]),
    "sign_cols": (["编制", "审核", "批准"], ["Prepared", "Reviewed", "Approved"]),
    "pass": ("在样本范围内", "within catalogue"), "unknown": ("待确认（样本没有该材料组）", "to confirm (no catalogue data)"),
    "verified": ("已经实机验证", "verified on a machine"), "not_verified": ("未经实机验证", "NOT verified on a machine"),
    "no_release": ("没有出正式程序", "no released program"), "first": ("首件须空运行、单段试切确认", "First part: dry run and single block"),
    "sim_pass": ("通过", "pass"), "sim_unknown": ("通过，有未知项", "pass with unknown items"), "sim_error": ("不通过", "FAIL"),
    "none": ("无", "none"),
}
KIND = {"flat_endmill": ("平底立铣刀", "flat end mill"), "ball_endmill": ("球头立铣刀", "ball end mill"),
        "bull_endmill": ("圆鼻立铣刀", "bull nose end mill"), "drill": ("钻头", "drill"), "turn": ("外圆车刀", "turning tool"),
        "groove": ("切槽刀", "grooving tool"), "thread_turn": ("螺纹车刀", "threading tool"), "bore": ("镗刀", "boring bar"),
        "center_drill": ("中心钻", "center drill"), "chamfer_mill": ("倒角刀", "chamfer mill"), "face_mill": ("面铣刀", "face mill"),
        "tap": ("丝锥", "tap"), "reamer": ("铰刀", "reamer")}
LEVEL = {"error": 0, "warn": 1, "unknown": 2}
# 车削工序 → 刀号（analysis.cam._turn 的约定）
TURN_T = {"rough": 1, "finish": 2, "groove": 3, "thread": 4, "drill": 5, "bore": 6}


def _x(key, lang):
    v = TXT[key]
    return v[LANGS.index(lang)]


OP_EN = [(r"^粗车外圆$", "Rough turning"), (r"^精车外圆$", "Finish turning"), (r"^切槽 宽 (.+)$", r"Grooving, width \1"),
         (r"^车螺纹 M(.+)×(.+)$", r"Threading M\1x\2"), (r"^钻孔$", "Drilling"), (r"^钻孔 Ø(.+)$", r"Drilling Ø\1"),
         (r"^镗孔$", "Boring"), (r"^铣型腔$", "Pocket milling"), (r"^铣外轮廓$", "Contour milling"),
         (r"^铣槽 宽 (.+)$", r"Slot milling, width \1"), (r"^右端（第一次装夹）$", "Right end (1st setup)"),
         (r"^左端（调头装夹）$", "Left end (2nd setup, part flipped)"), (r"^铣削$", "Milling"),
         (r"^规则（没有用 AI）$", "Rules (no AI)"), (r"^草稿$", "Draft")]


def _tr(text, lang):
    """程序生成的文字：英文时先查本模块的对照，再交给 assist.i18n（查不到的原样保留）"""
    import re

    from assist import i18n

    text = str(text)
    if lang != "en":
        return text
    for pat, rep in OP_EN:
        if re.match(pat, text):
            return re.sub(pat, rep, text)
    return i18n.t(text, lang)


def _tno(draft, row):
    if draft["setup"]["mode"] == "turn":
        k = row["id"].rstrip("0123456789")
        return TURN_T[k]
    return int(row["id"][1:])


def _rpm(vc, d, cap):
    return min(1000.0 * vc / (math.pi * d), cap) if d else None


def build_docx(draft: dict, result: dict, out, *, lang: str = "zh", number: str | None = None, revision: str = "草稿",
               today=None, company: str | None = None) -> dict:
    """draft：assist.cam_process.draft 的结果；result：analysis.cam.run(draft["setup"] + post) 的结果。
    写 out（.docx）与旁边的 *.ledger.json。"""
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    if lang not in LANGS:
        raise ValueError(f"语言只能是 {LANGS}")
    if result.get("status") != "ok":
        raise ValueError("计算没有成功，不出工艺卡")
    data = result["data"]
    lib_path = (draft["setup"].get("machine_sim") or {}).get("tool_library")
    lib = TL.load(lib_path) if lib_path else TL.load()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    today = today or datetime.now(UTC).date()
    L = Ledger({"draft": draft, "result": data, "library": lib}, lang)

    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = sec.page_height, sec.page_width
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(1.5))
    st = doc.styles["Normal"]
    st.font.name = "Noto Sans CJK SC"
    st.font.size = Pt(9)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Noto Sans CJK SC")

    def table(cols, rows):
        t = doc.add_table(rows=1, cols=len(cols))
        t.style = "Table Grid"
        for i, c in enumerate(cols):
            t.rows[0].cells[i].text = c
        for r in rows:
            cells = t.add_row().cells
            for i, v in enumerate(r):
                cells[i].text = "" if v is None else str(v)
        return t

    doc.add_heading(_x("title", lang), level=0)
    doc.add_paragraph(_x("draft", lang))
    # 1. 基本信息
    setup = draft["setup"]
    progs = data["programs"]
    rel = next((p.get("release") for p in progs if p.get("release")), None)
    ms = next((p.get("machine_sim") for p in progs if p.get("machine_sim")), None)
    m = data["machine"]
    post = (f"{rel['post']} {rel['version']} — " + _x("verified" if rel["verified"] else "not_verified", lang)) if rel \
        else _x("no_release", lang)
    simtxt = (_x("sim_" + ms["status"], lang) + f" · {ms['fingerprint']}") if ms else _x("none", lang)
    head = [(_x("part", lang), setup.get("item") or "—"),
            (_x("material", lang), f"{setup.get('kienzle') or '—'} · ISO {draft['iso_group']}"),
            (_x("machine", lang), f"{m['id']} {m['name']}"),
            (_x("post", lang), post), (_x("sim", lang), simtxt),
            (_x("number", lang), number or ("未编号" if lang == "zh" else "unnumbered")),
            (_x("rev", lang), _tr(revision, lang)), (_x("date", lang), today.isoformat()),
            (_x("by", lang), _tr(draft["by"], lang))]
    for v in (simtxt, today.isoformat(), post):
        L.labels.append(v)
    doc.add_heading(_x("head", lang), level=1)
    table(["", ""], head)
    # 2. 工序
    doc.add_heading(_x("ops", lang), level=1)
    from analysis.cam import machines as Mc

    max_rpm = float(Mc.get(m["id"])["max_rpm"])
    rows = []
    for i, row in enumerate(draft["card"]):
        p = row["params"]
        base = f"/card/{i}/params"
        tool = TL.get(lib, row["tool"])
        feed = (L.num("draft", base + "/f") if "f" in p else L.num("draft", base + "/fz") if "fz" in p else "—")
        d = tool.get("diameter_mm")
        if d is None and setup["mode"] == "turn":
            d = _op_diameter(setup, row["id"])
        s = _rpm(p["vc"], d, max_rpm) if d else None
        if s is not None:
            L.entries.append({"text": str(round(s)), "source": "derived", "pointer": f"/card/{i}",
                              "kind": "formula", "formula": "S = 1000·vc/(π·d)，不超过机床最高转速"})
        rows.append([i + 1, _tr(row["title"], lang), f"T{_tno(draft, row):02d}", f"{row['tool']} {_tr(row['tool_name'], lang)}".strip(),
                     L.num("draft", base + "/vc"), feed, L.num("draft", base + "/ap") if "ap" in p else "—",
                     str(round(s)) if s is not None else "—", row.get("reason") or "",
                     _x("pass" if row["status"] == "pass" else "unknown", lang)])
    table(TXT["op_cols"][LANGS.index(lang)], rows)
    # 3. 刀具清单
    doc.add_heading(_x("tools", lang), level=1)
    mtools = (setup.get("machine_sim") or {}).get("tools") or {}
    trows = []
    for tno in sorted(mtools, key=int):
        e = mtools[tno]
        t = TL.get(lib, e["tool"])
        ti = lib["tools"].index(t)
        if "diameter_mm" in t:
            dia = "Ø" + L.num("library", f"/tools/{ti}/diameter_mm")
        else:
            ins = t.get("insert") or {}
            dia = ins.get("iso") or (("r" + L.num("library", f"/tools/{ti}/insert/nose_radius_mm")) if "nose_radius_mm" in ins else "—")
            if ins.get("iso"):
                L.labels.append(ins["iso"])
        length = L.num("draft", f"/setup/machine_sim/tools/{tno}/length_mm") if "length_mm" in e else "—"
        src = t["source"]
        trows.append([f"T{int(tno):02d}", t["id"], _tr(t.get("name", ""), lang), KIND[t["kind"]][LANGS.index(lang)], dia, length,
                      _tr(f"{src['kind']} · {src['ref']}", lang)])
        L.labels += [t["id"], f"T{int(tno):02d}"]
    table(TXT["tool_cols"][LANGS.index(lang)], trows)
    # 4. 程序单
    doc.add_heading(_x("progs", lang), level=1)
    prow = []
    for pi, p in enumerate(progs):
        cnt = {k: sum(1 for c in p["checks"] if c["level"] == k) for k in LEVEL}
        text = (p.get("release") or {}).get("text") or ""
        lines = len(text.splitlines()) if text else 0
        tb = f"/programs/{pi}/time"
        prow.append([f"O{p.get('number', pi + 1)}", _tr(p.get("title", ""), lang), lines or "—",
                     L.num("result", tb + "/cut_s"), L.num("result", tb + "/rapid_s"), L.num("result", tb + "/tool_s"),
                     L.num("result", tb + "/total_s"), cnt["error"], cnt["warn"], cnt["unknown"]])
        L.labels.append(f"O{p.get('number', pi + 1)}")
    table(TXT["prog_cols"][LANGS.index(lang)], prow)
    sep = "；" if lang == "zh" else "; "
    doc.add_paragraph(_x("first", lang) + ("" if rel and rel["verified"] else sep + _x("not_verified", lang)))
    # 5. 检查与说明
    doc.add_heading(_x("checks", lang), level=1)
    seen = set()
    for p in progs:
        for c in sorted(p["checks"], key=lambda c: LEVEL.get(c["level"], 3)):
            if c["level"] not in LEVEL or c["text"] in seen:
                continue
            seen.add(c["text"])
            doc.add_paragraph(f"[{c['level']}] " + _tr(c["text"], lang), style="List Bullet")
            L.labels.append(c["text"])
    if not seen:
        doc.add_paragraph(_x("none", lang))
    doc.add_heading(_x("notes", lang), level=1)
    for n in draft["notes"] or [_x("none", lang)]:
        doc.add_paragraph(_tr(n, lang), style="List Bullet")
        L.labels.append(n)
    if draft.get("explanation"):
        doc.add_paragraph(draft["explanation"])
    doc.add_heading(_x("sign", lang), level=1)
    table(TXT["sign_cols"][LANGS.index(lang)], [["", "", ""]])
    doc.save(out)
    ledger = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "lang": lang,
              "draft_fingerprint": fingerprint(draft), "numbers": L.entries, "labels": L.labels}
    lp = out.with_suffix(".ledger.json")
    lp.write_text(json.dumps(ledger, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return {"docx": out, "ledger": lp, "ops": len(rows), "programs": len(prow)}


def _op_diameter(setup, op_id):
    """车削工序的转速按哪个直径算：粗、精车按最大直径，槽按槽底，螺纹按大径，镗孔按内孔最大直径"""
    k = op_id.rstrip("0123456789")
    n = int(op_id[len(k):] or 1)
    if k in ("rough", "finish"):
        return max(float(d) for d, _ in setup["segments"])
    if k == "groove":
        return float(setup["grooves"][n - 1]["d"])
    if k == "thread":
        return float(setup["threads"][n - 1]["d"])
    if k == "bore":
        return max(float(d) for d, _ in setup["bore"]["segments"])
    if k == "drill":
        return float(setup["bore"].get("drill_d") or 0) or None
    return None
