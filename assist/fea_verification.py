"""问渠有限元验证手册（ADR-0096 第 4 步）：跑全部标准题，把算出来的值与参考值逐题列成中英两版 Word / PDF。

题目清单在 `assist/fea_verification_cases.json`，每题对应一个标准题测试；测试在断言之外用 `tests/verification.record`
记下算出来的值、参考值和容差。手册里的数字就是这一次测试算出来的，不另算、不手填。
某题的测试没通过、被跳过或没记下数，手册照样出，但在结论里写明，命令以非 0 退出。

用法：python -m assist.fea_verification --out <目录> [--only VM-01,VM-02] [--no-pdf]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).with_name("fea_verification_cases.json")
TEXT = {
    "title": {"zh": "问渠有限元验证手册", "en": "WenQuest FEA Verification Manual"},
    "intro": {"zh": "本手册逐题列出标准题的参考值（解析解、教材公式或 NAFEMS 标准题的目标值）与本软件的计算值。"
                    "每题的数字都是这一次运行相应的自动测试时算出来的，不另算、不手填；测试代码与题目清单随软件发布。",
              "en": "This manual lists, problem by problem, the reference values (analytical solutions, textbook formulas or NAFEMS "
                    "target values) and the values computed by this software. Every number was produced by running the "
                    "corresponding automated test for this edition; nothing is computed separately or typed in by hand. "
                    "The test code and the problem list ship with the software."},
    "env": {"zh": "运行环境", "en": "Environment"},
    "summary": {"zh": "结论", "en": "Summary"},
    "sum_line": {"zh": "共 {n} 题：通过 {ok} 题，未通过 {bad} 题，未运行 {skip} 题；对照的数值与结论共 {rows} 项，在容差内 {rows_ok} 项。",
                 "en": "{n} problems: {ok} passed, {bad} failed, {skip} not run; {rows} values and verdicts compared, "
                       "{rows_ok} within tolerance."},
    "list": {"zh": "题目一览", "en": "Problem list"},
    "item": {"zh": "项目", "en": "Item"}, "value": {"zh": "内容", "en": "Value"},
    "edition": {"zh": "版本（git 提交）", "en": "Version (git commit)"}, "date": {"zh": "日期", "en": "Date"},
    "solver": {"zh": "求解器", "en": "Solver"}, "mesher": {"zh": "网格程序", "en": "Mesher"},
    "python": {"zh": "Python / 操作系统", "en": "Python / OS"},
    "id": {"zh": "编号", "en": "No."}, "problem": {"zh": "题目", "en": "Problem"}, "result": {"zh": "结果", "en": "Result"},
    "source": {"zh": "出处", "en": "Source"}, "test": {"zh": "测试", "en": "Test"},
    "quantity": {"zh": "对照量", "en": "Quantity"}, "reference": {"zh": "参考值", "en": "Reference"},
    "computed": {"zh": "计算值", "en": "Computed"}, "error": {"zh": "误差", "en": "Error"},
    "tol": {"zh": "容差", "en": "Tolerance"}, "basis": {"zh": "参考值依据", "en": "Basis of reference"},
    "pass": {"zh": "通过", "en": "pass"}, "fail": {"zh": "未通过", "en": "fail"}, "skipped": {"zh": "未运行", "en": "not run"},
    "norows": {"zh": "这一题没有记下对照数（测试没通过或没运行）。", "en": "No values were recorded for this problem "
                                                                          "(the test failed or did not run)."},
    "verdict_names": {"zh": {"pass": "通过", "fail": "不通过", "unknown": "未知"}, "en": {"pass": "pass", "fail": "fail",
                                                                                          "unknown": "unknown"}},
    "notes": {"zh": "说明", "en": "Notes"},
    "note_scale": {"zh": "NAFEMS 模态题的材料为 E = 200 GPa、ρ = 8000 kg/m³，本手册用材料库的 45-QT（E = 210 GPa、ρ = 7850 kg/m³，"
                         "ν 同为 0.3）；线弹性的固有频率与 √(E/ρ) 成正比，参考频率按此换算后再比（换算系数写在“参考值依据”栏）。",
                   "en": "The NAFEMS modal problems use E = 200 GPa and ρ = 8000 kg/m³; this manual uses the library material 45-QT "
                         "(E = 210 GPa, ρ = 7850 kg/m³, same ν = 0.3). Linear-elastic natural frequencies scale with √(E/ρ), so the "
                         "reference frequencies are scaled accordingly before comparison (the factor is shown in the basis column)."},
    "note_fv52": {"zh": "FV52 的弯曲模态按侧面“硬”简支（Navier 条件）计算；NAFEMS 文本中的底面四条边 uz = 0 模型，"
                        "网格加密后弯曲模态收敛到比参考值低约 7 %（底边支承比闭式解的支承软），故只用它对照面内模态（第 8 阶）。",
                  "en": "The FV52 flexural modes are computed with hard simple supports on the side faces (Navier conditions). With the "
                        "bottom-edge uz = 0 supports of the NAFEMS text, the flexural modes converge about 7 % below the reference under "
                        "mesh refinement (bottom-edge supports are softer than those of the closed-form solution), so that model is "
                        "used for the in-plane mode (mode 8) only."},
}


def load_cases() -> dict:
    return json.loads(CASES.read_text(encoding="utf-8"))


def _env() -> dict:
    from analysis.common.solvers import find_ccx
    from assist.fea_report import code_version, gmsh_version

    ccx = find_ccx()
    ver = ""
    if ccx:
        try:
            out = subprocess.run([ccx, "-v"], capture_output=True, text=True, timeout=30, check=False).stdout
            ver = next((ln.strip() for ln in out.splitlines() if "Version" in ln), "")
        except (OSError, subprocess.SubprocessError):
            ver = ""
    return {"code": code_version(), "date": datetime.now(UTC).date().isoformat(), "solver": f"CalculiX {ver}".strip(),
            "gmsh": gmsh_version(), "python": f"Python {platform.python_version()} / {platform.system()} {platform.release()}"}


def run_tests(cases: list[dict], work: Path, timeout: int = 7200) -> tuple[list[dict], dict[str, str]]:
    """跑这些题的测试，返回（记下的行, 每个测试的结果 pass / fail / skipped）"""
    rec = work / "records.jsonl"
    junit = work / "junit.xml"
    rec.unlink(missing_ok=True)
    env = dict(os.environ, FAP_VERIFICATION_OUT=str(rec), FAP_LANG="zh")
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}", *[c["test"] for c in cases]]
    subprocess.run(cmd, cwd=ROOT, env=env, timeout=timeout, check=False)
    rows = [json.loads(x) for x in rec.read_text(encoding="utf-8").splitlines() if x.strip()] if rec.is_file() else []
    outcome: dict[str, str] = {}
    if junit.is_file():
        for tc in ET.parse(junit).getroot().iter("testcase"):
            node = f"{tc.get('classname', '').replace('.', '/')}.py::{tc.get('name')}"
            res = "pass"
            if tc.find("failure") is not None or tc.find("error") is not None:
                res = "fail"
            elif tc.find("skipped") is not None:
                res = "skipped"
            outcome[node] = res
    return rows, outcome


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def summarize(cases: list[dict], rows: list[dict], outcome: dict[str, str]) -> dict:
    by_case: dict[str, list[dict]] = {}
    for r in rows:
        by_case.setdefault(r["case"], []).append(r)
    out = []
    for c in cases:
        rs = by_case.get(c["test"], [])
        res = outcome.get(c["test"], "skipped")
        if res == "pass" and (not rs or not all(r["ok"] for r in rs)):
            res = "fail"                                  # 测试过了却没记下数、或有一项超出容差：不算通过
        out.append({**c, "rows": rs, "result": res})
    n_rows = sum(len(c["rows"]) for c in out)
    return {"cases": out, "n": len(out), "ok": sum(c["result"] == "pass" for c in out),
            "bad": sum(c["result"] == "fail" for c in out), "skip": sum(c["result"] == "skipped" for c in out),
            "rows": n_rows, "rows_ok": sum(r["ok"] for c in out for r in c["rows"])}


def _source(src: str, lang: str) -> str:
    """出处里“中文 / English”的写法按语言取一边（文献名照原样）"""
    import re

    from assist.i18n import has_cjk

    src = re.sub(r"（([^（）/]+?) / ([^（）]+?)）", lambda m: f"（{m.group(1)}）" if lang == "zh" else f" ({m.group(2)})", src)
    if " / " in src and has_cjk(src.split(" / ")[0]) and not has_cjk(src.split(" / ", 1)[1]):
        zh, en = src.split(" / ", 1)
        if lang == "zh" and ": " in en:
            return f"{zh}：{en.split(': ', 1)[1]}"
        return zh if lang == "zh" else en
    return src


def build(summary: dict, env: dict, out: Path, lang: str) -> Path:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    from assist import i18n

    T = {k: (v[lang] if isinstance(v, dict) and lang in v else v) for k, v in TEXT.items()}
    cats = load_cases()["categories"]
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Noto Sans CJK SC"
    st.font.size = Pt(9.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Noto Sans CJK SC")
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(1.8)
        hp = s.header.paragraphs[0]
        hp.text = f"{T['title']}   {i18n.t(env['code'], lang)}   {env['date']}"
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    def table(head, rows, widths=None):
        t = doc.add_table(rows=1, cols=len(head))
        t.style = "Table Grid"
        for c, x in zip(t.rows[0].cells, head, strict=True):
            c.text = x
            for r in c.paragraphs[0].runs:
                r.bold = True
        for row in rows:
            for c, x in zip(t.add_row().cells, row, strict=True):
                c.text = x
        if widths:
            for row in t.rows:
                for c, w in zip(row.cells, widths, strict=True):
                    c.width = Cm(w)
        return t

    doc.add_heading(T["title"], 0)
    doc.add_paragraph(T["intro"])
    doc.add_heading(T["env"], 1)
    table([T["item"], T["value"]], [[T["edition"], i18n.t(env["code"], lang)], [T["date"], env["date"]], [T["solver"], env["solver"]],
                                     [T["mesher"], f"Gmsh {env['gmsh']}"], [T["python"], env["python"]]], [5, 12])
    doc.add_heading(T["summary"], 1)
    doc.add_paragraph(T["sum_line"].format(**{k: summary[k] for k in ("n", "ok", "bad", "skip", "rows", "rows_ok")}))
    doc.add_heading(T["notes"], 2)
    for k in ("note_scale", "note_fv52"):
        doc.add_paragraph(T[k], style="List Bullet")
    doc.add_heading(T["list"], 1)
    table([T["id"], T["problem"], T["result"]], [[c["id"], c["title"][lang], T[c["result"]]] for c in summary["cases"]], [2, 13, 2.5])
    vn = TEXT["verdict_names"][lang]
    for cat, name in cats.items():
        group = [c for c in summary["cases"] if c["category"] == cat]
        if not group:
            continue
        doc.add_heading(name[lang], 1)
        for c in group:
            doc.add_heading(f"{c['id']}  {c['title'][lang]}", 2)
            doc.add_paragraph(f"{T['source']}: {_source(c['source'], lang)}")
            doc.add_paragraph(f"{T['test']}: {c['test']}    {T['result']}: {T[c['result']]}")
            if not c["rows"]:
                doc.add_paragraph(T["norows"])
                continue
            rows = []
            for r in c["rows"]:
                q = r["quantity"][0 if lang == "zh" else 1]
                if r["kind"] == "verdict":
                    rows.append([q, vn.get(r["reference"], r["reference"]), vn.get(r["computed"], r["computed"]), "—", "—",
                                 T["pass"] if r["ok"] else T["fail"], ""])
                    continue
                unit = f" {r['unit']}" if r["unit"] else ""
                err = f"{r['error'] * 100:+.3f} %" if r["rel"] else f"{r['error']:+.3g}{unit}"
                tol = f"± {r['tol'] * 100:g} %" if r["rel"] else f"± {r['tol']:g}{unit}"
                rows.append([q, _fmt(r["reference"]) + unit, _fmt(r["computed"]) + unit, err, tol,
                             T["pass"] if r["ok"] else T["fail"], r.get("formula", "")])
            table([T["quantity"], T["reference"], T["computed"], T["error"], T["tol"], T["result"], T["basis"]], rows,
                  [3.6, 2.4, 2.4, 1.7, 1.5, 1.3, 4.5])
    doc.save(out)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="问渠有限元验证手册（中英两版）")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", default="", help="只跑这些编号（逗号分隔），调试用")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    cases = load_cases()["cases"]
    if a.only:
        keep = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    with tempfile.TemporaryDirectory() as tmp:
        rows, outcome = run_tests(cases, Path(tmp))
    summary = summarize(cases, rows, outcome)
    env = _env()
    (a.out / "verification.json").write_text(json.dumps({"env": env, **summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    from assist.fea_report import to_pdf

    for lang, name in (("zh", "问渠有限元验证手册.docx"), ("en", "WenQuest-FEA-Verification-Manual.docx")):
        d = build(summary, env, a.out / name, lang)
        if not a.no_pdf:
            to_pdf(d)
    print(json.dumps({k: summary[k] for k in ("n", "ok", "bad", "skip", "rows", "rows_ok")}, ensure_ascii=False))
    return 0 if summary["bad"] == 0 and summary["skip"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
