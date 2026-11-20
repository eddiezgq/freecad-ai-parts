"""问渠CAM 刀具库：株洲钻石（ZCC-CT）样本 → cam-tool/1（ADR-0106 Q4b）。

按 ADR-0040 只收公开样本里的参数（尺寸、刃数、切削参数），不转存样本文档、图片。样本 PDF 放 data/raw/cam/zcc/（不入 git），
在 data/sources.yaml 的 zcc-ct 下逐份登记网址与 SHA-256。本模块只读 PDF 的文字（pdftotext -layout），不调用 AI、不联网。

收录（第一批）：GM 系列整体硬质合金平底立铣刀 GM-2E / GM-3E / GM-4E / GM-4E-G（不等螺旋角）、球头立铣刀 GM-2B / GM-4B，
标准柄（刃径或 R 后不带 F / S）的规格；
样本标 ○（订货）的在名称里写“订货”。
- 尺寸页：D 刃径、d 柄径、H 刃长、L 全长、Z 刃数（样本 B355、B362–B363、B372–B373、B365–B366）。
- 切削参数页（B500 / B504 / B508 / B505）：每个直径给侧铣的主轴转速 n（min⁻¹）与进给速度 F（mm/min），换算
  vc = π·D·n / 1000（m/min）、fz = F / (n·Z)（mm）；按材料组取三列：铸铁 → K，碳钢、合金钢 ~750 N/mm² → P，不锈钢 → M。
  淬硬钢几列（~30 / 40 / 50 HRC）按硬度分，本刀具库的材料组不分硬度，不收（用到时报“样本没给范围”）。
  样本给的是推荐值（一个点），写成上下限相同的范围。最大切深按页上的图：侧铣 ae = 0.1D，ap = 1D（GM-2E、GM-3E）或 1.5D（GM-4E）。
  样本注 1：铣槽时转速取 50%–70%、进给取 40%–60%——本刀具库没有“铣槽”这一栏，不收；铣槽工序的切宽超过 ae 会报出来。
- 参数表没列的直径（如 4.5、5.5、7、9、11）不插值、不写切削参数。

第二批（2022–2023 可转位刀具样本 C 部分）：整体硬质合金切削丝锥 4201C / 4202C / 4202A（C167、C169、C172–C173，切削速度 C176），
螺纹铣刀 4111（C175，只收尺寸）。

命令：python -m ingest.cam_zcc data/raw/cam/zcc --out analysis/cam/libraries/zcc-ct.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

SOURCE = "zcc-ct"
# 系列 → 刀具种类、刃数、尺寸页（文件、PDF 页、样本页码）、参数页（文件、PDF 页、样本页码）、ap、ae（×D）
SERIES = {
    "GM-2E": {"kind": "flat_endmill", "z": 2, "dims": [("ZCC-CT_GMseries.pdf", 3, "B355")],
              "params": ("ZCC_B500-501.pdf", 1, "B500"), "ap": 1.0, "ae": 0.1},
    "GM-3E": {"kind": "flat_endmill", "z": 3, "dims": [("ZCC-CT_GMseries.pdf", 10, "B362"), ("ZCC-CT_GMseries.pdf", 11, "B363")],
              "params": ("ZCC_B504-505.pdf", 1, "B504"), "ap": 1.0, "ae": 0.1},
    "GM-4E": {"kind": "flat_endmill", "z": 4, "dims": [("ZCC-CT_GMseries.pdf", 20, "B372"), ("ZCC-CT_GMseries.pdf", 21, "B373")],
              "params": ("ZCC_B508,505.pdf", 1, "B508"), "ap": 1.5, "ae": 0.1},
    "GM-4E-G": {"kind": "flat_endmill", "z": 4, "dims": [("ZCC-CT_GMseries.pdf", 13, "B365"), ("ZCC-CT_GMseries.pdf", 14, "B366")],
                "params": ("ZCC_B504-505.pdf", 2, "B505"), "ap": 1.5, "ae": 0.1, "suffix": "-G", "base": "GM-4E",
                "name": "不等螺旋角"},
    # 球头：尺寸行多一列 R，参数表按 R 分行；最大切深按页上的图 ap = 0.1R、ae = 0.2R（vc 按名义直径 D 算，与样本页上的“切削速度”一致）
    "GM-2B": {"kind": "ball_endmill", "z": 2, "dims": [("ZCC-CT_GMseries.pdf", 30, "B382")],
              "params": ("ZCC_B514-515.pdf", 2, "B515"), "ap_r": 0.1, "ae_r": 0.2, "ball": True},
    "GM-4B": {"kind": "ball_endmill", "z": 4, "dims": [("ZCC-CT_GMseries.pdf", 33, "B385")],
              "params": ("ZCC_B516-517.pdf", 1, "B516"), "ap_r": 0.1, "ae_r": 0.2, "ball": True},
}
# 参数表的列（每列一对 n、F）：0 铸铁、1 碳钢合金钢 ~750N/mm²、2 ~30HRC、3 ~40HRC、4 不锈钢、5 ~50HRC
GROUP_COL = {"K": 0, "P": 1, "M": 4}
_NUM = r"(\d+(?:\.\d+)?)"


class ZccError(ValueError):
    pass


def page_text(pdf: Path, page: int) -> str:
    r = subprocess.run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(pdf), "-"], capture_output=True, text=True, check=True)
    return r.stdout


def dims_rows(text: str, base: str, suffix: str = "") -> list[dict]:
    """尺寸表：型号  D  d  H  L  Z  Picture n  ●/○。只收本系列标准柄（刃径后不带 F / S）的；stock：● 常备、○ 订货"""
    pat = re.compile(rf"^\s*({re.escape(base)}-D{_NUM}{re.escape(suffix)})\s+{_NUM}\s+{_NUM}\s+{_NUM}\s+{_NUM}\s+(\d+)\s+Picture\s*\d\s+([●○])\s*$")
    out = []
    for ln in text.splitlines():
        m = pat.match(ln)
        if not m:
            continue
        code, _dcode, D, d, H, L, Z, stock = m.groups()
        out.append({"code": code, "D": float(D), "d": float(d), "H": float(H), "L": float(L), "Z": int(Z), "stock": stock == "●"})
    return out


def ball_rows(text: str, base: str) -> list[dict]:
    """球头尺寸表：型号  D  R  d  H  L  Z  Picture n  ●/○（型号 GM-2B-R1.0，R 后不带 F / S 的是标准柄）"""
    pat = re.compile(rf"^\s*({re.escape(base)}-R{_NUM})\s+{_NUM}\s+{_NUM}\s+{_NUM}\s+{_NUM}\s+{_NUM}\s+(\d+)\s+Picture\s*\d\s+([●○])\s*$")
    out = []
    for ln in text.splitlines():
        m = pat.match(ln)
        if m:
            code, _r, D, R, d, H, L, Z, stock = m.groups()
            out.append({"code": code, "D": float(D), "R": float(R), "d": float(d), "H": float(H), "L": float(L), "Z": int(Z),
                        "stock": stock == "●"})
    return out


def param_rows(text: str) -> dict[float, list[tuple[float, float]]]:
    """参数表：直径（球头是 R0.5 这样的半径）+ 6 对 (n, F)"""
    out = {}
    pat = re.compile(r"^\s*R?(\d+(?:\.\d+)?)\s+" + r"\s+".join([r"(\d+)\s+(\d+)"] * 6) + r"\s*$")
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if m:
            v = [float(x) for x in m.groups()]
            out[v[0]] = [(v[1 + 2 * k], v[2 + 2 * k]) for k in range(6)]
            continue
        # pdftotext 偶尔把直径与数字拆成两行（直径单独一行，下一行是 12 个数）
        if re.fullmatch(r"\s*(\d+)\s*", ln) and i + 1 < len(lines):
            m2 = re.match(r"^\s*" + r"\s+".join([r"(\d+)\s+(\d+)"] * 6) + r"\s*$", lines[i + 1])
            if m2:
                v = [float(x) for x in m2.groups()]
                out[float(ln.strip())] = [(v[2 * k], v[2 * k + 1]) for k in range(6)]
    return out


# 整体硬质合金切削丝锥（样本 C 部分，2022–2023 版）：系列 → ([(PDF 页, 样本页)], 名称, 材料组与 vc 范围)。
# vc（C176）：灰铸铁 15–30、球墨铸铁 10–20 m/min——K 组取两者都在推荐范围内的 10–20；铝合金 20–50。
# 直槽：C176 注明直槽刀具的速度、进给降 20%–40%，取 0.6–0.8 倍（K 6–16、N 12–40）。成形丝锥（底孔不同）不收。
INDEXABLE = "zcc_catalog_2022-2023_Indexable.pdf"
TAPS = {
    "4201C": ([(69, "C167")], "螺旋槽丝锥（铸铁）", {"K": (10.0, 20.0)}),
    "4202C": ([(71, "C169")], "直槽丝锥（铸铁）", {"K": (6.0, 16.0)}),
    "4202A": ([(74, "C172"), (75, "C173")], "直槽丝锥（铝合金）", {"N": (12.0, 40.0)}),
}
TAP_PARAM_PAGE = "C176"


def tap_rows(text: str, prefix: str) -> list[dict]:
    """丝锥尺寸行：M d1  P  d2  [d3]  l1  l2  [l3]  a  [Picture n]  齿数  ●/○  底孔。型号（如 4201C-M10*1.5-6H，3P 倒角、6H）要在本页出现"""
    out = []
    for ln in text.splitlines():
        tok = ln.split()
        if not tok or not re.fullmatch(r"M\d+", tok[0]) or not any(t in ("●", "○") for t in tok):
            continue
        k = next(i for i, t in enumerate(tok) if t in ("●", "○"))
        nums = [t for t in tok[1:k] if re.fullmatch(r"\d+(?:\.\d+)?", t)]
        if "Picture" in tok[1:k]:                     # “Picture 1” 的 1 不是尺寸
            pi = tok.index("Picture")
            nums = [t for i, t in enumerate(tok[1:k], 1) if re.fullmatch(r"\d+(?:\.\d+)?", t) and i != pi + 1]
        if len(nums) not in (6, 8):
            continue
        P, d2 = float(nums[0]), float(nums[1])
        if len(nums) == 8:
            _d3, l1, l2, _l3, _a, z = nums[2:]
        else:
            l1, l2, _a, z = nums[2:]
        d = int(tok[0][1:])
        code = f"{prefix}-M{d}*{nums[0]}-6H"
        if code not in text:
            continue
        out.append({"code": code, "d": float(d), "P": P, "d2": d2, "l1": float(l1), "l2": float(l2), "z": int(z), "stock": tok[k] == "●",
                    "pre": float(tok[k + 1]) if k + 1 < len(tok) and re.fullmatch(r"\d+(?:\.\d+)?", tok[k + 1]) else None})
    return out


def taps(raw: Path) -> list[dict]:
    out = []
    for prefix, (pages, name, groups) in TAPS.items():
        rows = [(r, page) for pg, page in pages for r in tap_rows(page_text(raw / INDEXABLE, pg), prefix)]
        for r, page in rows:
            tid = r["code"].replace("*", "x")
            t = {"id": tid, "name": f"株洲钻石 {r['code']} 整体硬质合金{name}" + ("" if r["stock"] else "（订货）"), "kind": "tap",
                 "diameter_mm": r["d"], "pitch_mm": r["P"], "thread_angle_deg": 60.0, "flutes": r["z"], "flute_length_mm": r["l2"],
                 "overall_length_mm": r["l1"], "shank_diameter_mm": r["d2"], "tool_material": "carbide",
                 "cutting": [{"iso_group": g, "vc_m_min": {"min": lo, "max": hi}, "f_mm_rev": {"min": r["P"], "max": r["P"]}}
                             for g, (lo, hi) in groups.items()],
                 "source": {"kind": "catalog", "ref": SOURCE, "page": f"尺寸 {page}；切削速度 {TAP_PARAM_PAGE}（每转进给 = 螺距）"}}
            out.append(t)
    return out


def thread_mill_rows(text: str) -> list[dict]:
    """螺纹铣刀 4111（C175）：型号  M 公称  d1 刀径  P 螺距  d2 柄径  l1 全长  l2 刃长  齿数 …（推荐牌号与底孔可能折到下一行）"""
    pat = re.compile(rf"^\s*(4111-M(\d+)\*{_NUM})\s+M\d+\s+{_NUM}\s+{_NUM}\s+{_NUM}\s+{_NUM}\s+{_NUM}\s+(\d+)\b")
    out = []
    for ln in text.splitlines():
        m = pat.match(ln)
        if m:
            code, d, _p, d1, P, d2, l1, l2, z = m.groups()
            out.append({"code": code, "d": float(d), "d1": float(d1), "P": float(P), "d2": float(d2), "l1": float(l1), "l2": float(l2),
                        "z": int(z)})
    return out


def thread_mills(raw: Path) -> list[dict]:
    """螺纹铣刀只收尺寸：C176 的切削参数按“涂层 / 无涂层”分，样本没写 KTG4015 牌号有没有涂层，不收（用到时报“样本没给范围”）"""
    out = []
    for r in thread_mill_rows(page_text(raw / INDEXABLE, 77)):
        out.append({"id": r["code"].replace("*", "x"), "name": f"株洲钻石 {r['code']} 整体硬质合金螺纹铣刀（M{r['d']:g}×{r['P']:g}）",
                    "kind": "thread_mill", "diameter_mm": r["d1"], "pitch_mm": r["P"], "thread_angle_deg": 60.0, "flutes": r["z"],
                    "flute_length_mm": r["l2"], "overall_length_mm": r["l1"], "shank_diameter_mm": r["d2"], "tool_material": "carbide",
                    "source": {"kind": "catalog", "ref": SOURCE, "page": "尺寸 C175"}})
    return out


def build(raw: Path) -> dict:
    tools = []
    for series, spec in SERIES.items():
        pf, pp, ppage = spec["params"]
        params = param_rows(page_text(raw / pf, pp))
        if not params:
            raise ZccError(f"{pf} 第 {pp} 页读不出切削参数表")
        seen = set()
        for df, dp, dpage in spec["dims"]:
            txt = page_text(raw / df, dp)
            rows = ball_rows(txt, series) if spec.get("ball") else dims_rows(txt, spec.get("base", series), spec.get("suffix", ""))
            for r in rows:
                if r["code"] in seen:
                    continue
                seen.add(r["code"])
                if r["Z"] != spec["z"]:
                    raise ZccError(f"{r['code']}：刃数 {r['Z']} 与系列 {spec['z']} 不符")
                what = "球头立铣刀" if spec.get("ball") else "平底立铣刀"
                t = {"id": r["code"], "name": f"株洲钻石 {r['code']} 整体硬质合金{spec.get('name', '')}{what}"
                     + ("" if r["stock"] else "（订货）"), "kind": spec["kind"],
                     "diameter_mm": r["D"], "flutes": r["Z"], "flute_length_mm": r["H"], "overall_length_mm": r["L"],
                     "shank_diameter_mm": r["d"], "tool_material": "carbide"}
                page = f"尺寸 {dpage}"
                row = params.get(r["R"] if spec.get("ball") else r["D"])
                if row:
                    cut = []
                    for g, col in GROUP_COL.items():
                        n, F = row[col]
                        vc = round(math.pi * r["D"] * n / 1000.0, 1)
                        fz = round(F / (n * r["Z"]), 4)
                        cut.append({"iso_group": g, "vc_m_min": {"min": vc, "max": vc}, "fz_mm": {"min": fz, "max": fz},
                                    **({"ap_max_mm": round(spec["ap_r"] * r["R"], 4), "ae_max_mm": round(spec["ae_r"] * r["R"], 4)}
                                       if spec.get("ball") else
                                       {"ap_max_mm": round(spec["ap"] * r["D"], 3), "ae_max_mm": round(spec["ae"] * r["D"], 3)})})
                    t["cutting"] = cut
                    page += f"；切削参数 {ppage}（样本 n、F 换算：vc = πDn/1000，fz = F/(n·Z)）"
                t["source"] = {"kind": "catalog", "ref": SOURCE, "page": page}
                tools.append(t)
    tools += taps(raw) + thread_mills(raw)
    return {"format": "cam-tool/1", "name": "株洲钻石 立铣刀、丝锥、螺纹铣刀（样本参数）", "tools": tools}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="株洲钻石样本 → 问渠CAM 刀具库")
    ap.add_argument("raw", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    lib = build(a.raw)
    from analysis.cam import tools as TL

    TL.validate(lib) if hasattr(TL, "validate") else None
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(lib, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(lib['tools'])} 把刀 → {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
