"""问渠CAM 刀具库：泰珂洛（Tungaloy）ISO-EcoTurn 车刀片样本 → cam-tool/1（ADR-0106 Q4b 第三批）。

按 ADR-0040 只收公开样本里的参数，不转存样本文档、图片。样本 PDF 放 data/raw/cam/tungaloy/（不入 git），
在 data/sources.yaml 的 tungaloy 下登记网址与 SHA-256。本模块只读 PDF 的文字（pdftotext -layout），不调用 AI、不联网。

- 尺寸表：每行“代号（带断屑槽） … RE IC S D1”，收 RE（刀尖圆弧）、IC（内切圆）。行里没印尺寸的代号不收。
  *NMA 平面刀片（代号不带断屑槽）按样本的“无断屑槽”条件。
  PDF 页码与样本印的页码相同。
- 标准切削条件（第 58、59 页）：按断屑槽、材质给 ap、f、vc。每个代号有哪些材质，样本用符号标，文字抽不出来，
  所以按断屑槽取同一材料组各材质的合集：ap 上限取大，f、vc 取最小到最大。
  P：取“中碳钢、合金钢”一栏；M：三栏全范围（样本子标题照印为碳钢）；K：灰铸铁一栏；S：钛合金、镍基合金两栏全范围。
- 不写刀具材料（同一断屑槽有硬质合金也有金属陶瓷）、不写主偏角和刀杆（取决于刀杆，样本没有刀杆表）。

刀杆（ADR-0112，综合样本 2020–2021 C 部分“外圆车削”）：表头 H B LF LH HF WF RE 的行收进 cam-holder/1——
代号（R/L 拆成两把）、能装的刀片（“CN/GN**1204” → 前两位 CN、GN，尺寸位 1204）、h、b、l1、刀头长 LH、刀尖高 HF、刀尖偏距 WF、标准刀尖圆弧 RE。
代号不合 ISO 5608 写法（缺长度字母或刀片位）的行不收；页码按样本印的 C 页。

螺纹刀片（综合样本 2023–2024 E 部分 TungThread，ISO 米制 60°）：外螺纹右手刀片（代号 ..ER..ISO，含 -B、-M），收 IC、RE、螺距（表里螺距一栏，
与代号里的螺距位核对）、牙型角 60°；切削速度照 E067 TungThread 表，按材料组取各材质、各硬度行的合集（不收 CBN 牌号 BX330，这些刀片没有），
每转进给 = 螺距。内螺纹刀片（IR）刀具库没有“内 / 外”这一项，先不收；左手刀片不收。

命令：python -m ingest.cam_tungaloy data/raw/cam/tungaloy --out analysis/cam/libraries/tungaloy.json \
      --holders-out analysis/cam/libraries/tungaloy-holders.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SOURCE = "tungaloy"
PDF = "TR426-C_IsoEcoTurn_Apr.2026-0423.pdf"
COND_PAGES = (58, 59)
# 材质 → 材料组（第 58 页都是 P；第 59 页 M、K、S 按材质分）
GRADE_GROUP = {"T9205": "P", "T9215": "P", "T9225": "P", "NS9530": "P", "GT9530": "P", "AT9530": "P",
               "T6215": "M", "T6225": "M", "AH6225": "M", "AH6235": "M", "T515": "K", "AH8015": "S"}
ROW = re.compile(r"\b([A-Z]{4}\d{6}[A-Z]?-[A-Z0-9]+|[A-Z]{3}A\d{6}[A-Z]?)(?![-A-Z0-9])[^\n]*?\s(\d+(?:\.\d+)?) +(\d+(?:\.\d+)?) +(\d+(?:\.\d+)?) +(\d+(?:\.\d+)?) *$",
                 re.MULTILINE)
_R = r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)"
COND = re.compile(r"(?:^|\s)([A-Z]{2,3}|无断屑槽)\s+([A-Z]{1,2}\d{3,4})\s+" + _R + r"\s+" + _R + r"\s+" + _R
                  + r"(?:\s+(?:" + _R + r"|-))?(?:\s+(?:" + _R + r"|-))?\s*$", re.MULTILINE)


HOLDER_PDF = "GC_2020-2021_CN_C_Ex.Turning.pdf"
_N = r"(\d+(?:\.\d+)?)"
HOLDER_ROW = re.compile(r"\b([A-Z]{4})(R/L|R|L|N)(\d{4}[A-Z]\d{2}(?:\d{2})?[A-Z]?(?:-[A-Z0-9]+)?)\s+" + r"\s+".join([_N] * 7)
                        + r"\s+([A-Z]{2}(?:/[A-Z]{2})*)\*\*(\d{4})")
HOLDER_HEAD = re.compile(r"\bH\s+B\s+LF\s+LH\s+HF\s+WF\s+RE")


THREAD_PDF = "GC_2023-2024_CN_E_ThreadingTool.pdf"
THREAD_ROW = re.compile(r"(?:^|\s)(\d{1,2})\s+(\d+(?:\.\d+)?)\s+R\s+((\d{1,2})ER(\d{2,3})ISO(?:-[A-Z]+)?)(?![-A-Z0-9])[^\n]*?\s"
                        r"(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)", re.MULTILINE)
# E067 TungThread 切削速度（m/min）：各材料组取各材质、各硬度行的合集（BX330 是 CBN，ISO 米制刀片表里没有，不算）
THREAD_VC = {"P": (60.0, 200.0), "M": (50.0, 130.0), "K": (50.0, 150.0), "N": (100.0, 500.0), "S": (10.0, 80.0), "H": (10.0, 30.0)}
THREAD_VC_PAGE = "E067"


class TungaloyError(ValueError):
    pass


def page_text(pdf: Path, page: int) -> str:
    return subprocess.run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(pdf), "-"],
                          check=True, capture_output=True, text=True).stdout


def page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], check=True, capture_output=True, text=True).stdout
    return int(re.search(r"Pages:\s+(\d+)", out).group(1))


def dims_rows(text: str) -> list[dict]:
    """尺寸表的行 → [{code, re, ic, s, d1}]（RE IC S D1 四列都印了才收）"""
    return [{"code": c, "re": float(a), "ic": float(b), "s": float(s), "d1": float(d)} for c, a, b, s, d in ROW.findall(text)]


def cond_rows(text: str) -> list[dict]:
    """标准切削条件的行 → [{breaker, grade, ap, f, vc: [(lo, hi) | None, …]}]（vc 按样本各栏，从左到右；“-” 记 None）"""
    out = []
    for m in COND.finditer(text):
        g = m.groups()
        vcs = [(float(g[6]), float(g[7]))]
        for i in (8, 10):
            vcs.append((float(g[i]), float(g[i + 1])) if g[i] is not None else None)
        out.append({"breaker": g[0], "grade": g[1], "ap": (float(g[2]), float(g[3])), "f": (float(g[4]), float(g[5])), "vc": vcs})
    return out


def _cols(group: str, vcs: list) -> list:
    if group == "P":
        return [vcs[1]]                       # 中碳钢、合金钢
    if group == "K":
        return [vcs[0]]                       # 灰铸铁
    return [v for v in vcs if v is not None]  # M：三栏全范围；S：钛合金、镍基合金


def cutting_table(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """断屑槽 → 材料组 → 合集范围 {vc, f, ap_max}"""
    out: dict = {}
    for r in rows:
        grp = GRADE_GROUP.get(r["grade"])
        if grp is None:
            raise TungaloyError(f"不认识的材质 {r['grade']}（断屑槽 {r['breaker']}）")
        cols = [c for c in _cols(grp, r["vc"]) if c is not None]
        if not cols:
            continue
        e = out.setdefault(r["breaker"], {}).setdefault(grp, {"vc": [1e9, 0.0], "f": [1e9, 0.0], "ap_max": 0.0, "grades": []})
        e["vc"] = [min(e["vc"][0], *(c[0] for c in cols)), max(e["vc"][1], *(c[1] for c in cols))]
        e["f"] = [min(e["f"][0], r["f"][0]), max(e["f"][1], r["f"][1])]
        e["ap_max"] = max(e["ap_max"], r["ap"][1])
        e["grades"].append(r["grade"])
    return out


def build(raw: Path) -> dict:
    pdf = raw / PDF
    if not pdf.exists():
        raise TungaloyError(f"没有样本 {pdf}")
    conds = []
    for p in COND_PAGES:
        conds += cond_rows(page_text(pdf, p))
    table = cutting_table(conds)
    if not table:
        raise TungaloyError("标准切削条件读不出来")
    tools, seen = [], set()
    for page in range(1, page_count(pdf) + 1):
        if page in COND_PAGES:
            continue
        for r in dims_rows(page_text(pdf, page)):
            if r["code"] in seen:
                continue
            seen.add(r["code"])
            breaker = r["code"].split("-", 1)[1] if "-" in r["code"] else "无断屑槽"   # *NMA：平面刀片，样本按“无断屑槽”给条件
            t = {"id": "TG-" + r["code"], "name": f"泰珂洛 {r['code']} 车刀片", "kind": "turn",
                 "insert": {"iso": r["code"], "nose_radius_mm": r["re"], "inscribed_circle_mm": r["ic"]}}
            src = f"尺寸 {page}"
            cut = table.get(breaker)
            if cut:
                t["cutting"] = [{"iso_group": g, "vc_m_min": {"min": e["vc"][0], "max": e["vc"][1]},
                                 "f_mm_rev": {"min": e["f"][0], "max": e["f"][1]}, "ap_max_mm": e["ap_max"]}
                                for g, e in sorted(cut.items(), key=lambda kv: "PMKS".index(kv[0]))]
                src += f"；切削条件 58–59（断屑槽 {breaker} 各材质合集，具体材质按样本另选）"
            t["source"] = {"kind": "catalog", "ref": SOURCE, "page": src}
            tools.append(t)
    if not tools:
        raise TungaloyError("尺寸表读不出来")
    if (raw / THREAD_PDF).exists():
        tools += build_threads(raw)
    return {"format": "cam-tool/1", "name": "泰珂洛 车刀片、螺纹刀片（样本参数）", "tools": tools}


def holder_rows(text: str) -> list[dict]:
    """外圆刀杆表的行（这一页要有 H B LF LH HF WF RE 表头）→ [{code, hands, h, b, lf, lh, hf, wf, re, codes, size}]"""
    if not HOLDER_HEAD.search(text):
        return []
    out = []
    for m in HOLDER_ROW.finditer(text):
        g = m.groups()
        h, b, lf, lh, hf, wf, re_ = (float(v) for v in g[3:10])
        hands = ["R", "L"] if g[1] == "R/L" else [g[1]]
        out.append({"base": g[0], "rest": g[2], "hands": hands, "h": h, "b": b, "lf": lf, "lh": lh, "hf": hf, "wf": wf, "re": re_,
                    "codes": g[10].split("/"), "size": g[11]})
    return out


def build_holders(raw: Path) -> dict:
    from analysis.cam import holders as HD

    pdf = raw / HOLDER_PDF
    if not pdf.exists():
        raise TungaloyError(f"没有样本 {pdf}")
    out, seen, skipped = [], set(), []
    for page in range(1, page_count(pdf) + 1):
        for r in holder_rows(page_text(pdf, page)):
            for hand in r["hands"]:
                code = f"{r['base']}{hand}{r['rest']}"
                if code in seen:
                    continue
                try:
                    p = HD.parse(code)
                except HD.HolderError:
                    continue                                     # 代号不合 ISO 5608 写法（缺长度字母等），不收
                seen.add(code)
                if (p["h_mm"], p["b_mm"], p["l1_mm"]) != (r["h"], r["b"], r["lf"]):
                    skipped.append(f"{code}（代号 {p['h_mm']:g}×{p['b_mm']:g}×{p['l1_mm']:g}，表 {r['h']:g}×{r['b']:g}×{r['lf']:g}，C{page:03d}）")
                    continue                                     # 代号与表对不上：哪个对说不准，不收
                out.append({"id": "TG-" + code, "name": f"泰珂洛 {code} 外圆车刀杆", "iso5608": code, "use": "external",
                            "insert": {"codes": r["codes"], "size": r["size"]}, "f_mm": r["wf"], "h_mm": r["h"], "b_mm": r["b"],
                            "l1_mm": r["lf"], "h1_mm": r["hf"], "head_mm": r["lh"], "nose_radius_mm": r["re"],
                            "source": {"kind": "catalog", "ref": SOURCE, "page": f"C{page:03d}"}})
    if not out:
        raise TungaloyError("刀杆表读不出来")
    if skipped:
        print("代号与表对不上、没收：" + "；".join(skipped), file=sys.stderr)
    return {"format": "cam-holder/1", "name": "泰珂洛 外圆车刀杆（样本参数）", "holders": out}


def _pitch_code(d: str) -> float:
    """代号里的螺距位：两位按 0.1 mm（15 → 1.5），三位按 0.01 mm（175 → 1.75）"""
    return int(d) / (10.0 if len(d) == 2 else 100.0)


def thread_rows(text: str) -> list[dict]:
    out = []
    for m in THREAD_ROW.finditer(text):
        g = m.groups()
        pitch = float(g[1])
        if abs(pitch - _pitch_code(g[4])) > 1e-9:
            raise TungaloyError(f"{g[2]}：螺距栏 {pitch:g} 与代号 {g[4]} 对不上")
        out.append({"code": g[2], "pitch": pitch, "ic": float(g[5]), "re": float(g[8])})
    return out


def build_threads(raw: Path) -> list[dict]:
    pdf = raw / THREAD_PDF
    if not pdf.exists():
        raise TungaloyError(f"没有样本 {pdf}")
    tools, seen = [], set()
    for page in range(1, page_count(pdf) + 1):
        for r in thread_rows(page_text(pdf, page)):
            if r["code"] in seen:
                continue
            seen.add(r["code"])
            p = r["pitch"]
            tools.append({"id": "TG-" + r["code"], "name": f"泰珂洛 {r['code']} 外螺纹刀片（ISO 米制 60°，螺距 {p:g}）",
                          "kind": "thread_turn", "pitch_mm": p, "thread_angle_deg": 60,
                          "insert": {"iso": r["code"], "nose_radius_mm": r["re"], "inscribed_circle_mm": r["ic"]},
                          "cutting": [{"iso_group": g, "vc_m_min": {"min": lo, "max": hi}, "f_mm_rev": {"min": p, "max": p}}
                                      for g, (lo, hi) in THREAD_VC.items()],
                          "source": {"kind": "catalog", "ref": SOURCE,
                                     "page": f"尺寸 E{page:03d}；切削速度 {THREAD_VC_PAGE}（各材质合集，具体材质按样本另选；每转进给 = 螺距）"}})
    if not tools:
        raise TungaloyError("螺纹刀片表读不出来")
    return tools


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="泰珂洛 ISO-EcoTurn 样本 → 问渠CAM 刀具库")
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
