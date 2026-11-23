"""问渠CAM 刀具库：京瓷（Kyocera）切槽刀片样本 → cam-tool/1（ADR-0106 Q4b 第十批）。

按 ADR-0040 只收公开样本里的参数，不转存样本文档、图片。样本 PDF 放 data/raw/cam/kyocera/（不入 git），
在 data/sources.yaml 的 kyocera 下登记网址与 SHA-256。本模块不调用 AI、不联网。

收录：外圆切槽刀片 GMM / GMG（样本 G 分册 G048–G049，KGM 刀杆用），切削条件照 G143“GMG / GMM / GMN / GMGA”表。
- 尺寸：刃宽 CW、刀尖圆弧 RE（刃数、刀片厚 S、刀片长 INSL 不进刀具库，刀具库没有这几项）。
  这两页的表一格里叠几个代号（同一 CW 不同 RE），pdftotext 抽出来行序是乱的，所以尺寸按样本页逐行抄成下面的 ROWS，
  build() 再拿 PDF 文字核对：每个代号都要在它那一页出现，否则报错（防抄错页、抄漏）。
- 不收：GMG…RU（内切 undercut 专用形状，起草的切槽工序用不上）。
- 切削条件（G143，切槽一栏）：按刃宽档（2.0~3.0、4.0、5.0、6.0/8.0）给每种材料的进给 f；
  切削速度按牌号给，按材料组取表里各牌号的合集（具体牌号按样本另选）：
  P = 碳钢、合金钢两行，M = 不锈钢，K = 铸铁，N = 铝合金、黄铜两行；S、H 表里没有，不写。
  刃宽不在这几档里的（3.5）不插值、不写切削参数。横车（turning）一栏不收：刀具库一把刀只有一组进给，切槽工序用切槽进给。
  外圆条件；样本注：内孔切槽切削速度和进给各降 10%（本批只收外圆刀片）。

外圆切槽刀杆 KGM（ADR-0118，样本 G056“KGM External grooving”表）：收 cam-holder/1（use = groove）——厂家代号（R/L 有货的拆开）、
最大槽深 CDX、刀杆高 H、宽 B、刀头长 LH、刀尖高 HF、全长 LF、刀尖偏距 WF、可装刃宽 CW min ~ max。表格合并单元格多，同样照页图逐行抄成 HOLDERS，
导入时核对每个代号在 G056 上。自动车床用的 KGM（G055，样本标 2026 年 9 月停产）、深槽 KGM-T（G057，可切深度随工件直径变，G054 另有表）不收。

命令：python -m ingest.cam_kyocera data/raw/cam/kyocera --out analysis/cam/libraries/kyocera.json \
      --holders-out analysis/cam/libraries/kyocera-holders.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SOURCE = "kyocera"
PDF = "G_EN.pdf"
COND_PAGE = 143

# (样本页, 代号, CW, RE) —— 照 G048、G049 逐行抄
ROWS = [
    # G048 GMM …MW（断屑型，M 级）
    (48, "GMM2420-020MW", 2.4, 0.2),
    (48, "GMM3020-020MW", 3.0, 0.2), (48, "GMM3020-040MW", 3.0, 0.4),
    (48, "GMM4020-020MW", 4.0, 0.2), (48, "GMM4020-040MW", 4.0, 0.4), (48, "GMM4020-080MW", 4.0, 0.8),
    (48, "GMM5020-040MW", 5.0, 0.4), (48, "GMM5020-080MW", 5.0, 0.8),
    (48, "GMM6020-040MW", 6.0, 0.4), (48, "GMM6020-080MW", 6.0, 0.8),
    (48, "GMM8030-080MW", 8.0, 0.8),
    # G048 GMM …MS（锋利型，M 级）
    (48, "GMM3020-020MS", 3.0, 0.2), (48, "GMM3020-040MS", 3.0, 0.4),
    (48, "GMM4020-040MS", 4.0, 0.4), (48, "GMM5020-040MS", 5.0, 0.4), (48, "GMM6020-040MS", 6.0, 0.4),
    # G048 GMG …MS（锋利型，精密级）
    (48, "GMG3020-000MS", 3.0, 0.0), (48, "GMG3020-020MS", 3.0, 0.2), (48, "GMG3020-040MS", 3.0, 0.4),
    (48, "GMG4020-020MS", 4.0, 0.2), (48, "GMG4020-040MS", 4.0, 0.4), (48, "GMG4020-080MS", 4.0, 0.8),
    (48, "GMG5020-040MS", 5.0, 0.4), (48, "GMG5020-080MS", 5.0, 0.8),
    (48, "GMG6020-080MS", 6.0, 0.8),
    # G049 GMG …MG（精密级，磨制断屑槽）
    (49, "GMG2520-030MG", 2.5, 0.3), (49, "GMG3020-030MG", 3.0, 0.3), (49, "GMG3520-030MG", 3.5, 0.3),
    (49, "GMG4020-040MG", 4.0, 0.4), (49, "GMG5020-040MG", 5.0, 0.4), (49, "GMG6020-040MG", 6.0, 0.4),
    (49, "GMG8030-050MG", 8.0, 0.5),
    # G049 全圆弧（Full R）
    (49, "GMM3020-150R", 3.0, 1.5), (49, "GMM4020-200R", 4.0, 2.0), (49, "GMM5020-250R", 5.0, 2.5), (49, "GMM6020-300R", 6.0, 3.0),
    (49, "GMG3020-150R", 3.0, 1.5), (49, "GMG4020-200R", 4.0, 2.0), (49, "GMG5020-250R", 5.0, 2.5),
]

# G143 切槽进给 f（mm/rev），按刃宽档：2.0~3.0、4.0、5.0、6.0/8.0
BAND_TXT = ("2.0~3.0", "4.0", "5.0", "6.0/8.0")
FEED = {
    "P": ((0.05, 0.15), (0.10, 0.25), (0.15, 0.35), (0.20, 0.35)),     # 碳钢、合金钢（两行相同）
    "M": ((0.05, 0.15), (0.10, 0.20), (0.15, 0.35), (0.20, 0.35)),     # 不锈钢
    "K": ((0.05, 0.20), (0.10, 0.30), (0.15, 0.40), (0.20, 0.40)),     # 铸铁
    "N": ((0.05, 0.20), (0.08, 0.25), (0.10, 0.25), (0.12, 0.30)),     # 铝合金、黄铜（两行相同）
}
# G143 切削速度（m/min），各牌号合集
VC = {
    "P": (70.0, 220.0),    # 碳钢 TN90 100~220、CR9025/PR915/PR930 80~200；合金钢 80~200、70~180
    "M": (60.0, 160.0),    # 不锈钢 TN90 70~160、其余 60~150
    "K": (70.0, 200.0),    # 铸铁 PR905 100~200、KW10 70~150
    "N": (100.0, 500.0),   # 铝合金 KW10 200~500、黄铜 KW10 100~200
}
# 核对用：G143 表里必须能找到的文字
COND_CHECK = ["GMG / GMM / GMN / GMGA", "0.05~0.15", "0.10~0.25", "0.15~0.35", "0.20~0.35", "0.08~0.25", "0.12~0.30",
              "100~220", "60~150", "200~500", "100~200"]


HOLDER_PAGE = 56
# (代号后段, 有货的手向, CDX, H, B, LH, HF, LF, WF, CW min, CW max) —— 照 G056 逐行抄
HOLDERS = [
    ("1212H-3", "R", 9, 12, 12, 27, 12, 100, 10.8, 3, 3),
    ("1616H-3", "R", 9, 16, 16, 27, 16, 100, 14.8, 3, 4),
    ("2020K-3", "RL", 9, 20, 20, 27, 20, 125, 18.8, 3, 4),
    ("2525M-3", "RL", 9, 25, 25, 27, 25, 150, 23.8, 3, 4),
    ("2020K-4", "R", 10, 20, 20, 27, 20, 125, 18.3, 4, 5),
    ("2525M-4", "RL", 10, 25, 25, 27, 25, 150, 23.3, 4, 5),
    ("2020K-5", "R", 10, 20, 20, 27, 20, 125, 17.8, 5, 6),
    ("2525M-5", "R", 10, 25, 25, 27, 25, 150, 22.8, 5, 6),
    ("2525M-8", "RL", 25, 25, 25, 40, 25, 150, 22, 8, 8),
]
HOLDER_CHECK = ["CDX", "10.8", "14.8", "18.8", "23.8", "18.3", "23.3", "17.8", "22.8"]


class KyoceraError(ValueError):
    pass


def _page(pdf: Path, n: int) -> str:
    return subprocess.run(["pdftotext", "-f", str(n), "-l", str(n), "-layout", str(pdf), "-"],
                          check=True, capture_output=True, text=True).stdout


def _band(cw: float):
    """刃宽档：2.0~3.0 是区间，4.0、5.0 是单值，6.0/8.0 是两个单值（3.5、7 之类不在任何一档）"""
    if 2.0 - 1e-9 <= cw <= 3.0 + 1e-9:
        return 0
    for i, vals in ((1, (4.0,)), (2, (5.0,)), (3, (6.0, 8.0))):
        if any(abs(cw - v) < 1e-9 for v in vals):
            return i
    return None


def groove_tools(raw: Path) -> list[dict]:
    pdf = Path(raw) / PDF
    if not pdf.exists():
        raise KyoceraError(f"缺样本：{pdf}")
    pages = {n: _page(pdf, n) for n in {r[0] for r in ROWS} | {COND_PAGE}}
    for n, code, _cw, _re in ROWS:
        fam, rest = code[:3], code[3:]
        if rest not in pages[n] and code not in pages[n]:
            raise KyoceraError(f"G{n:03d} 上找不到 {code}")
        if fam not in pages[n]:
            raise KyoceraError(f"G{n:03d} 上找不到 {fam}")
    for s in COND_CHECK:
        if s not in pages[COND_PAGE]:
            raise KyoceraError(f"G{COND_PAGE} 上找不到 {s}（切削条件表对不上，样本版本变了？）")
    tools = []
    for n, code, cw, re_ in ROWS:
        b = _band(cw)
        fullr = abs(2 * re_ - cw) < 1e-9
        t = {"id": "KY-" + code,
             "name": f"京瓷 {code} 外圆切槽刀片（刃宽 {cw:g}{'，全圆弧' if fullr else ''}）",
             "kind": "groove",
             "insert": {"iso": code, "nose_radius_mm": re_, "width_mm": cw}}
        if b is not None:
            t["cutting"] = [{"iso_group": g, "vc_m_min": {"min": VC[g][0], "max": VC[g][1]},
                             "f_mm_rev": {"min": FEED[g][b][0], "max": FEED[g][b][1]}} for g in ("P", "M", "K", "N")]
            page = f"尺寸 G{n:03d}；切削条件 G{COND_PAGE}（切槽一栏，刃宽档 {BAND_TXT[b]}；切削速度为各牌号合集，具体牌号按样本另选）"
        else:
            page = f"尺寸 G{n:03d}；G{COND_PAGE} 没有刃宽 {cw:g} 这一档，不写切削参数"
        t["source"] = {"kind": "catalog", "ref": SOURCE, "page": page}
        tools.append(t)
    return tools


def build_holders(raw: Path) -> dict:
    pdf = Path(raw) / PDF
    if not pdf.exists():
        raise KyoceraError(f"缺样本：{pdf}")
    text = _page(pdf, HOLDER_PAGE)
    for s in [r[0] for r in HOLDERS] + HOLDER_CHECK:
        if s not in text:
            raise KyoceraError(f"G{HOLDER_PAGE:03d} 上找不到 {s}（刀杆表对不上，样本版本变了？）")
    out = []
    for rest, hands, cdx, h, b, lh, hf, lf, wf, cmin, cmax in HOLDERS:
        for hand in hands:
            code = f"KGM{hand}{rest}"
            out.append({"id": "KY-" + code, "name": f"京瓷 {code} 外圆切槽刀杆（刃宽 {cmin:g}{'' if cmin == cmax else f'–{cmax:g}'}，最大槽深 {cdx:g}）",
                        "vendor_code": code, "use": "groove",
                        "insert": {"groove_width_mm": {"min": float(cmin), "max": float(cmax)}},
                        "f_mm": float(wf), "h_mm": float(h), "b_mm": float(b), "l1_mm": float(lf), "h1_mm": float(hf),
                        "head_mm": float(lh), "max_depth_mm": float(cdx),
                        "source": {"kind": "catalog", "ref": SOURCE, "page": f"G{HOLDER_PAGE:03d}"}})
    return {"format": "cam-holder/1", "name": "京瓷 外圆切槽刀杆 KGM（样本参数）", "holders": out}


def build(raw: Path) -> dict:
    return {"format": "cam-tool/1", "name": "京瓷 外圆切槽刀片 GMM / GMG（样本参数）", "tools": groove_tools(raw)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="京瓷切槽样本 → 问渠CAM 刀具库")
    ap.add_argument("raw", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--holders-out", type=Path)
    a = ap.parse_args(argv)
    if a.holders_out:
        hl = build_holders(a.raw)
        a.holders_out.write_text(json.dumps(hl, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{len(hl['holders'])} 把刀杆 → {a.holders_out}", file=sys.stderr)
    lib = build(a.raw)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(lib, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(lib['tools'])} 把刀 → {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
