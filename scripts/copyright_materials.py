"""软件著作权登记的鉴别材料（源程序、说明书 PDF）：问渠有限元、问渠多体动力学、问渠CAD。

    python scripts/copyright_materials.py --cad <wenquest-cad 仓库目录> [--out docs/copyright]

按《计算机软件著作权登记办法》第十条：源程序、文档各取前、后连续 30 页，不足 60 页的全部提交；源程序每页不少于 50 行，
文档每页不少于 30 行（有图的页除外）。
- 源程序：按 PRODUCTS 里的文件顺序（入口与界面在前、核心在后）连起来，去掉空行，每个文件前加一行文件名，
  长行按显示宽度折行；每页正好 50 行，页眉写软件全称、版本号、页码（第 n 页，共 N 页，连续编号）。
  只收自己写的代码：FreeCAD、CalculiX、Gmsh 等开源组件的代码一行不收；问渠CAD 收它自己的补丁、构建与测试脚本。
- 说明书：Markdown → HTML（pandoc，图片嵌入）→ Chromium 打印 PDF；封面写全称与版本号，每页页眉写全称与版本号，页脚页码。
- 另写 `summary.json`：每个软件的源程序行数、页数，交申请表“源程序量”一栏。
需要 pandoc 与 Playwright 的 Chromium。
"""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINES_PER_PAGE = 50
WRAP = 116                         # 一行的显示宽度（半角字符数；全角字符算 2）
HALF = 30                          # 前、后各 30 页

PRODUCTS = {
    "wenquest-fea": {
        "name": "问渠有限元分析软件", "version": "V1.0", "root": ROOT, "manual": ROOT / "docs/wenquest-fea/help/zh.md",
        "files": ["freecad_addon/gui/fem_commands.py", "freecad_addon/gui/fea_brand.py", "freecad_addon/gui/fea_panel.py",
                  "freecad_addon/fc/fem_flow.py", "freecad_addon/fc/fem_bridge.py", "freecad_addon/fc/fem_results.py",
                  "assist/fea_edition.py", "assist/fea_draft.py", "assist/features.py", "assist/fea_report.py",
                  "assist/fea_verification.py", "analysis/fea/study.py", "analysis/fea/geometry.py", "analysis/fea/solve.py",
                  "analysis/fea/structural.py", "analysis/fea/modal.py", "analysis/fea/dynamics.py", "analysis/fea/trust.py",
                  "analysis/fea/__init__.py"]},
    "wenquest-mbd": {
        "name": "问渠多体动力学分析软件", "version": "V1.0", "root": ROOT, "manual": ROOT / "docs/wenquest-mbd/help/zh.md",
        "files": ["freecad_addon/gui/mbd_brand.py", "freecad_addon/gui/mbd_assembly_panel.py", "freecad_addon/core/mbd_study.py",
                  "freecad_addon/fc/mbd_assembly.py", "freecad_addon/fc/mbd_mates.py", "freecad_addon/fc/mbd_flex.py",
                  "assist/mbd_edition.py", "assist/mbd_mates.py", "assist/mbd_report.py", "assist/mbd_verification.py",
                  "analysis/mbd/assembly.py", "analysis/mbd/mates.py", "analysis/mbd/flexsolid.py", "analysis/mbd/flexview.py",
                  "analysis/mbd/study.py", "analysis/mbd/loads.py", "analysis/mbd/dae/model.py", "analysis/mbd/dae/system.py",
                  "analysis/mbd/dae/solve.py", "analysis/mbd/dae/hht.py", "analysis/mbd/dae/advise.py",
                  "analysis/mbd/dae/nlbeam.py", "analysis/mbd/dae/run.py", "analysis/mbd/dae/*.py"]},
    "wenquest-cad": {
        "name": "问渠CAD辅助设计软件", "version": "V0.3", "root": None, "manual": ROOT / "docs/copyright/wenquest-cad/说明书.md",
        "files": ["build-wqcad.ps1", "ai-wqcad.ps1", "tests-wqcad.ps1", "build-occt.ps1", "diag-ai.ps1", "run_book_tests.py",
                  "run_ai_smoke.py", "run_ai_design_test.py", "diag_ai.py", "branding.xml", "tests/*.py",
                  "patches/series.txt", "patches/*.patch"]},
}


def file_list(root: Path, patterns: list[str]) -> list[Path]:
    """按给的顺序展开；通配符按文件名排序，已出现过的不再出现"""
    out: list[Path] = []
    for p in patterns:
        hits = sorted(root.glob(p)) if any(c in p for c in "*?") else [root / p]
        for h in hits:
            if h.is_file() and h not in out and "__pycache__" not in h.parts:
                out.append(h)
    return out


def _width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def _wrap(line: str) -> list[str]:
    out, cur, w = [], "", 0
    for ch in line.replace("\t", "    "):
        cw = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if w + cw > WRAP:
            out.append(cur)
            cur, w = "    ", 4
        cur += ch
        w += cw
    out.append(cur)
    return out


def source_lines(root: Path, files: list[Path]) -> tuple[list[str], int]:
    """（排版后的行，源程序原始行数）"""
    printed, raw = [], 0
    for f in files:
        text = f.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        raw += len(text)
        printed.append(f"# ===== 文件：{f.relative_to(root).as_posix()} =====")
        for ln in text:
            if ln.strip():
                printed.extend(_wrap(ln.rstrip()))
    return printed, raw


def pick_pages(lines: list[str]) -> tuple[list[list[str]], int]:
    pages = [lines[i:i + LINES_PER_PAGE] for i in range(0, len(lines), LINES_PER_PAGE)]
    total = len(pages)
    if total > 2 * HALF:
        pages = pages[:HALF] + pages[-HALF:]
    return pages, total


CSS_SRC = """
@page { size: A4; margin: 0; }
body { margin: 0; font-family: 'Noto Sans Mono CJK SC', monospace; }
.page { box-sizing: border-box; width: 210mm; height: 297mm; padding: 11mm 12mm 0 12mm; page-break-after: always; overflow: hidden; }
.head { display: flex; justify-content: space-between; font-family: 'Noto Sans CJK SC', sans-serif; font-size: 9pt;
        border-bottom: 0.4pt solid #000; padding-bottom: 1.5mm; margin-bottom: 2mm; }
pre { margin: 0; font-size: 8.2pt; line-height: 5.15mm; white-space: pre; }
"""


def source_pdf(name: str, version: str, pages: list[list[str]], out: Path, browser) -> None:
    body = []
    n = len(pages)
    for i, lines in enumerate(pages, 1):
        body.append(f"<div class='page'><div class='head'><span>{html.escape(name)} {version} 源程序</span>"
                    f"<span>第 {i} 页，共 {n} 页</span></div><pre>{html.escape(chr(10).join(lines))}</pre></div>")
    page = browser.new_page()
    page.set_content(f"<html><head><meta charset='utf-8'><style>{CSS_SRC}</style></head><body>{''.join(body)}</body></html>")
    page.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
    page.close()


CSS_DOC = """
body { font-family: 'Noto Sans CJK SC', sans-serif; font-size: 10.5pt; line-height: 1.6; }
h1 { font-size: 15pt; margin: 14pt 0 6pt; } h2 { font-size: 12.5pt; margin: 12pt 0 4pt; } h3 { font-size: 11pt; }
table { border-collapse: collapse; margin: 6pt 0; } th, td { border: 0.5pt solid #888; padding: 2pt 5pt; vertical-align: top; }
img { max-width: 100%; } code, pre { font-family: 'Noto Sans Mono CJK SC', monospace; font-size: 9pt; }
pre { white-space: pre-wrap; background: #f4f4f4; padding: 4pt; }
.cover { height: 240mm; display: flex; flex-direction: column; justify-content: center; align-items: center; page-break-after: always; }
.cover .t { font-size: 24pt; font-weight: 700; } .cover .v { font-size: 16pt; margin-top: 10mm; }
header#title-block-header { display: none; }
"""


def manual_pdf(name: str, version: str, md: Path, out: Path, browser) -> int:
    with tempfile.TemporaryDirectory() as td:
        frag = Path(td) / "body.html"
        subprocess.run(["pandoc", str(md), "-t", "html", "--embed-resources", "--standalone", "--resource-path", str(md.parent),
                        "--metadata", "pagetitle=manual", "-o", str(frag)], check=True)
        doc = frag.read_text(encoding="utf-8")
        body = doc[doc.index("<body>") + 6: doc.rindex("</body>")]
        cover = f"<div class='cover'><div class='t'>{html.escape(name)}</div><div class='v'>{version} 用户说明书</div></div>"
        page = browser.new_page()
        page.set_content(f"<html><head><meta charset='utf-8'><style>{CSS_DOC}</style></head><body>{cover}{body}</body></html>")
        head = (f"<div style='font-size:8.5pt;width:100%;padding:0 14mm;font-family:Noto Sans CJK SC;"
                f"display:flex;justify-content:space-between'><span>{html.escape(name)} {version}</span>"
                f"<span>用户说明书</span></div>")
        foot = ("<div style='font-size:8.5pt;width:100%;text-align:center;font-family:Noto Sans CJK SC'>"
                "第 <span class='pageNumber'></span> 页，共 <span class='totalPages'></span> 页</div>")
        page.pdf(path=str(out), format="A4", print_background=True, display_header_footer=True, header_template=head,
                 footer_template=foot, margin={"top": "18mm", "bottom": "16mm", "left": "16mm", "right": "16mm"})
        page.close()
    import re

    info = subprocess.run(["pdfinfo", str(out)], capture_output=True, text=True, check=True).stdout
    return int(re.search(r"Pages:\s+(\d+)", info).group(1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="软件著作权登记的鉴别材料")
    ap.add_argument("--cad", type=Path, required=True, help="wenquest-cad 仓库目录")
    ap.add_argument("--out", type=Path, default=ROOT / "docs/copyright")
    a = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright

    summary = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for key, p in PRODUCTS.items():
            root = Path(p["root"] or a.cad)
            files = file_list(root, p["files"])
            printed, raw = source_lines(root, files)
            pages, total = pick_pages(printed)
            d = a.out / key
            d.mkdir(parents=True, exist_ok=True)
            source_pdf(p["name"], p["version"], pages, d / f"{p['name']}{p['version']}-源程序.pdf", browser)
            mp = manual_pdf(p["name"], p["version"], p["manual"], d / f"{p['name']}{p['version']}-说明书.pdf", browser)
            summary[key] = {"name": p["name"], "version": p["version"], "files": [f.relative_to(root).as_posix() for f in files],
                            "source_lines": raw, "printed_lines": len(printed), "source_pages_total": total,
                            "source_pages_submitted": len(pages), "manual_pages": mp}
            print(key, json.dumps({k: v for k, v in summary[key].items() if k != "files"}, ensure_ascii=False), flush=True)
        browser.close()
    (a.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
