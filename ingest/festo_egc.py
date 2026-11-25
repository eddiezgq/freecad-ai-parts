"""直线模组：费斯托 EGC-TB-KF（同步带）与 EGC-BS-KF（滚珠丝杠）→ linear_module 组件（ADR-0129 129.2，ADR-0115 44.5.3）。

来源：费斯托产品目录分册（印 2026/10）。www.festo.com 对脚本下载返回 403、使用条款禁止自动抓取，
所以由项目负责人 2026-11-25 在浏览器里下载，放 data/raw/festo/（不入 git）；SHA-256 登记在 data/sources.yaml 的 festo 下。
本模块是对照目录原页逐项录入的表（ROWS）：每一行记页码和目录原文（pdftotext 抽出的文字，空白压成一格），
数值逐个写出。测试在有目录 PDF 时重新抽字，核对每行原文都在那一页上、每个数都在原文里（tests/test_festo_egc.py）；
没有 PDF 时只核对表与零件库文件一致。不联网、不调用 AI；单位在这里用 pint 换成标准单位（ingest/units.py）。

取值规则：
- 只收标准滑台 GK/GP 的数（加长滑台 GV/GQ、附加滑台、夹紧单元、ATEX 另做）。
- 行程订货时任选：每个尺寸（丝杠型再按导程）一条，写最大工作行程 max_stroke_mm；质量写行程 0 mm 的基本质量（含滑台）
  与每加 10 mm 行程的增重；包络长度写行程 0 mm 的总长 L1（选定行程后加行程与两端行程余量）。
- 允许的力与力矩是目录“参考寿命 5000 km 下的最大允许值”（动态），condition 照写；Mx 是滚转，My / Mz 同值，分别写俯仰、偏摆。
- 每转行程：同步带写目录的“进给常数”，丝杠写导程。
- 丝杠型的最高速度：目录第 11 页“空载力矩在最高运行速度下”那一行按导程给的速度，与第 19 页速度—行程曲线的平台值一致；
  行程长了速度下降（曲线，数据表注 4），condition 写明。
- 水平 / 垂直最大负载目录只给加速度—负载曲线，没有单个数，不写；电机法兰、滑台孔位不写端口（ADR-0129）。

命令：python -m ingest.festo_egc --out data/library/linear_module
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from ingest.assemble import assemble
from ingest.units import to_standard

VENDOR = "Festo SE & Co. KG"
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "festo"
DOCS = {"src-festo-egc-tb": RAW / "204380_documentation.pdf", "src-festo-egc-bs": RAW / "201447_documentation.pdf"}
REVIEW = "对照目录原页逐项录入：Claude（经张国庆授权，ADR-0040）（2026-11-25）"
LOAD = "参考寿命 5000 km 下的最大允许值（动态；几项同时作用时还要满足载荷比较系数 fv ≤ 1）；标准滑台 GK/GP"

# 每行：(目标字段, 页码, 目录原文, 单位, {型号键: 数值}, condition)
TB = ("50", "70", "80", "120", "185")
BS = ("70-10", "80-10", "80-20", "120-10", "120-25", "185-40")


def _cols(keys, values):
    return dict(zip(keys, values, strict=True))


def _bs_by_size(values):
    """丝杠型按尺寸给的数展开到各导程"""
    size = dict(zip(("70", "80", "120", "185"), values, strict=True))
    return {k: size[k.split("-")[0]] for k in BS}


ROWS = {
    "src-festo-egc-tb": [
        ("params/max_stroke_mm", 11, "EGC-…-GK/-GP [mm] 50 … 1900 50 … 5000 50 … 8500 50 … 8500 (50002)) 50 … 8500", "mm",
         _cols(TB, (1900, 5000, 8500, 8500, 8500)), "工作行程上限，标准滑台 GK/GP（120 带 ATEX 时 5000）"),
        ("params/max_thrust_n", 11, "Max. feed force Fx [N] 50 100 350 800 2500", "N", _cols(TB, (50, 100, 350, 800, 2500)), None),
        ("params/max_speed_m_s", 11, "Max. speed [m/s] 3 5", "m/s", _cols(TB, (3, 5, 5, 5, 5)), "目录表格 70–185 合并为一格 5"),
        ("params/max_accel_m_s2", 11, "Max. acceleration [m/s2] 50", "m/s^2", _cols(TB, (50,) * 5), None),
        ("params/repeatability_mm", 11, "Repetition accuracy [mm] ±0.08 ±0.1", "mm", _cols(TB, (0.08, 0.08, 0.08, 0.08, 0.1)),
         "目录表格 50–120 合并为一格 ±0.08"),
        ("params/mass_kg", 11, "EGC-…-GK/-GP 620 1850 3000 10500 32600", "g", _cols(TB, (620, 1850, 3000, 10500, 32600)),
         "行程 0 mm 的基本质量（含滑台），标准滑台 GK/GP"),
        ("params/mass_per_10mm_stroke_kg", 11, "Additional weight per 10 mm stroke 19 44 62 150 300", "g",
         _cols(TB, (19, 44, 62, 150, 300)), None),
        ("params/carriage_mass_kg", 11, "EGC-…-GK/-GP 130 370 620 2180 6500", "g", _cols(TB, (130, 370, 620, 2180, 6500)),
         "运动质量（Moving mass），标准滑台 GK/GP"),
        ("params/lead_mm", 12, "Feed constant [mm/rev] 58 78 90 125 232", "mm", _cols(TB, (58, 78, 90, 125, 232)),
         "进给常数（带轮每转的行程）"),
        ("params/force_lateral_n", 15, "Fymax. [N] 650 1850 3050 6890 15200", "N", _cols(TB, (650, 1850, 3050, 6890, 15200)), LOAD),
        ("params/force_normal_n", 15, "Fzmax [N] 650 1850 3050 6890 15200", "N", _cols(TB, (650, 1850, 3050, 6890, 15200)), LOAD),
        ("params/moment_roll_nm", 15, "Mxmax. [Nm] 3.5 16 36 144 529", "N*m", _cols(TB, (3.5, 16, 36, 144, 529)), LOAD),
        ("params/moment_pitch_nm", 15, "EGC-…-GK/-GP [Nm] 10 51 97 380 1157", "N*m", _cols(TB, (10, 51, 97, 380, 1157)),
         f"My；{LOAD}"),
        ("params/moment_yaw_nm", 15, "EGC-…-GK/-GP [Nm] 10 51 97 380 1157", "N*m", _cols(TB, (10, 51, 97, 380, 1157)),
         f"Mz（目录与 My 同列）；{LOAD}"),
    ] + [
        ("dims/width_mm", 23, quote, "mm", {size: b1}, "B1")
        for size, quote, b1 in (
            ("50", "50 48 39 11.5 20 35 1 27 8 20 15 – M4", 48),
            ("70", "70 69 58.6 16.5 30 45 1 38 10 28 20 – M5", 69),
            ("80", "80 82 72.6 22 40 60 1 48 16 46.5 25 9 M5", 82),
            ("120", "120 120 107 33 80 40 1 62 23 59 35 – M8", 120),
            ("185", "185 186 169 53 120 80 1 95 32 90 60 – M10", 186),
        )
    ] + [
        (f"dims/{field}", 23, quote, "mm", {size: value}, cond)
        for size, quote, h1, l1 in (
            ("50", "50 M3 5 42.5 16.5 37.6 35.5 10.5 10.5 18 155 – 77.5 –", 42.5, 155),
            ("70", "70 M5 5 64 28 53.7 50.8 13 13 29 246 346 123 173", 64, 246),
            ("80", "80 M5 5 76.5 34.5 65 61.5 17.5 15 35 286 386 143 193", 76.5, 286),
            ("120", "120 M6 9 111.5 51.6 95.9 91.1 22 22 54 446 546 223 273", 111.5, 446),
            ("185", "185 M8 9 172.5 80.5 152.6 143 25 25 80 612 712 306 356", 172.5, 612),
        )
        for field, value, cond in (("height_mm", h1, "H1（含滑台）"),
                                   ("base_length_mm", l1, "L1，标准滑台 GK，行程 0 mm；选定行程后加行程与两端行程余量"))
    ],
    "src-festo-egc-bs": [
        ("params/lead_mm", 11, "Spindelsteigung [mm/U] 10 10 20 10 25 40", "mm", _cols(BS, (10, 10, 20, 10, 25, 40)), "丝杠导程"),
        ("params/max_stroke_mm", 11, "EGC-...-GK/-GP [mm] 50 ... 1000 50 ... 2000 50 ... 2500 50 ... 3000", "mm",
         _bs_by_size((1000, 2000, 2500, 3000)), "工作行程上限，标准滑台 GK/GP"),
        ("params/max_thrust_n", 11, "Max. Vorschubkraft Fx1) [N] 400 650 1500 3000", "N", _bs_by_size((400, 650, 1500, 3000)),
         "最大进给力；进给力影响寿命（目录第 17 页）"),
        ("params/max_speed_m_s", 11, "bei max. Verfahrgeschwindigkeit2) [m/s] 0,5 0,5 1 0,6 1,5 2", "m/s",
         _cols(BS, (0.5, 0.5, 1, 0.6, 1.5, 2)),
         "短行程时的最高运行速度（第 19 页速度—行程曲线的平台值）；行程长了随行程下降，转速与速度与行程有关（数据表注 4）"),
        ("params/max_accel_m_s2", 11, "Max. Beschleunigung [m/s2] 15", "m/s^2", _cols(BS, (15,) * 6), None),
        ("params/repeatability_mm", 11, "Wiederholgenauigkeit [mm] ±0,02", "mm", _cols(BS, (0.02,) * 6), None),
        ("params/mass_kg", 12, "EGC-...-GK/-GP 1500 2700 12500 30000", "g", _bs_by_size((1500, 2700, 12500, 30000)),
         "行程 0 mm 的基本质量（含滑台），标准滑台 GK/GP"),
        ("params/mass_per_10mm_stroke_kg", 12, "Gewichtszuschlag pro 10 mm Hub 50 80 190 390", "g", _bs_by_size((50, 80, 190, 390)),
         None),
        ("params/carriage_mass_kg", 12, "EGC-...-GK/-GP 400 740 2400 8600", "g", _bs_by_size((400, 740, 2400, 8600)),
         "运动质量（Bewegte Masse），标准滑台 GK/GP"),
        ("params/force_lateral_n", 15, "Fymax. [N] 1850 3050 6890 15200", "N", _bs_by_size((1850, 3050, 6890, 15200)), LOAD),
        ("params/force_normal_n", 15, "Fzmax. [N] 1850 3050 6890 15200", "N", _bs_by_size((1850, 3050, 6890, 15200)), LOAD),
        ("params/moment_roll_nm", 15, "Mxmax. [Nm] 16 36 144 529", "N*m", _bs_by_size((16, 36, 144, 529)), LOAD),
        ("params/moment_pitch_nm", 15, "EGC-...-GK/-GP [Nm] 51 97 380 1157", "N*m", _bs_by_size((51, 97, 380, 1157)), f"My；{LOAD}"),
        ("params/moment_yaw_nm", 15, "EGC-...-GK/-GP [Nm] 51 97 380 1157", "N*m", _bs_by_size((51, 97, 380, 1157)),
         f"Mz（目录与 My 同列）；{LOAD}"),
        ("dims/width_mm", 25, "69 58,6 16,5 30 45 29 39 1 38 6 ß13", "mm", {"70-10": 69}, "B1"),
        ("dims/width_mm", 25, "82 72,6 22 40 60 35 46,75 1 48 8 @18", "mm", {"80-10": 82, "80-20": 82}, "B1"),
        ("dims/width_mm", 25, "120 107 33 40 80 64 78 1 62 12 @28", "mm", {"120-10": 120, "120-25": 120}, "B1"),
        ("dims/width_mm", 25, "186 169 53 120 80 80 114 1 95 25 @44", "mm", {"185-40": 186}, "B1"),
        ("dims/height_mm", 26, "M5 – M5 5 64 22,5 50,5 13 13 36", "mm", {"70-10": 64}, "H1（含滑台）"),
        ("dims/height_mm", 26, "M5 9 M5 5 76,5 27 62 17,5 15 46", "mm", {"80-10": 76.5, "80-20": 76.5}, "H1（含滑台）"),
        ("dims/height_mm", 26, "M6 – M8 9 111,5 42,5 89,5 22 22 54", "mm", {"120-10": 111.5, "120-25": 111.5}, "H1（含滑台）"),
        ("dims/height_mm", 26, "M8 – M10 9 172,5 65,2 141,5 25 25 80", "mm", {"185-40": 172.5}, "H1（含滑台）"),
        ("dims/base_length_mm", 26, "70 GK/GP 50 ... 1000 168 86,5", "mm", {"70-10": 168},
         "L1，标准滑台 GK/GP，行程 0 mm；选定行程后加行程与两端行程余量"),
        ("dims/base_length_mm", 26, "80 GK/GP < 1477 196 101", "mm", {"80-10": 196, "80-20": 196},
         "L1，标准滑台 GK/GP，行程 0 mm；行程 ≥ 1477 mm 时 L1 为 236（加长约 40 mm），另加行程与两端行程余量"),
        ("dims/base_length_mm", 26, "120 GK/GP < 1704 309 156", "mm", {"120-10": 309, "120-25": 309},
         "L1，标准滑台 GK/GP，行程 0 mm；行程 ≥ 1704 mm 时 L1 为 369（加长约 60 mm），另加行程与两端行程余量"),
        ("dims/base_length_mm", 26, "185 GK/GP < 2361 412 209", "mm", {"185-40": 412},
         "L1，标准滑台 GK/GP，行程 0 mm；行程 ≥ 2361 mm 时 L1 为 512（加长约 100 mm），另加行程与两端行程余量"),
    ],
}


def model(doc: str, key: str) -> str:
    if doc == "src-festo-egc-tb":
        return f"EGC-{key}-TB-KF-GK"
    size, lead = key.split("-")
    return f"EGC-{size}-BS-KF-{lead}P-GK"


def _pv(doc: str, page: int, quote: str, value, condition: str | None) -> dict:
    out = {"value": value, "source": {"doc": doc, "page": page, "note": f"{REVIEW}，目录第 {page} 页原文“{quote}”"},
           "method": "manual", "confidence": 1.0, "reviewed": True}
    if condition:
        out["condition"] = condition
    return out


def values(doc: str) -> dict[str, dict]:
    """型号键 → 目标字段 → 参数值对象（已换成标准单位）"""
    out: dict[str, dict] = {}
    for target, page, quote, unit, cols, cond in ROWS[doc]:
        field = target.split("/", 1)[1]
        for key, v in cols.items():
            std = round(to_standard(v, unit, field), 9)
            std = int(std) if std == int(std) else std
            out.setdefault(key, {})[target] = _pv(doc, page, quote, std, cond)
    drive = "belt" if doc == "src-festo-egc-tb" else "ballscrew"
    for vals in out.values():
        vals["params/drive_type"] = _pv(doc, 1, "Toothed belt axes EGC-TB-KF" if drive == "belt" else
                                            "Spindelachsen EGC-BS-KF", drive, None)
    return out


def build() -> tuple[list[dict], list[str]]:
    comps, problems = [], []
    for doc in ROWS:
        for key, vals in values(doc).items():
            comp, probs, _ = assemble("linear_module", VENDOR, model(doc, key), vals,
                                      note=f"参数取自厂商公开目录 {doc}（ADR-0040），对照原页逐项录入（ingest/festo_egc.py）；"
                                           "行程订货时任选，选定行程后的质量与长度由选型代码按基本值加算")
            if probs or comp is None:
                problems.append(f"{model(doc, key)}：{'；'.join(probs)}")
            else:
                comps.append(comp)
    return comps, problems


def page_text(pdf: Path, page: int) -> str:
    """pdftotext 抽一页的文字，空白压成一格（测试核对原文用）"""
    import subprocess

    raw = subprocess.run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(pdf), "-"],
                         capture_output=True, text=True, check=True).stdout
    return re.sub(r"\s+", " ", raw)


def main(argv: list[str] | None = None) -> int:
    from kb.validation import errors

    ap = argparse.ArgumentParser(prog="python -m ingest.festo_egc", description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True, help="输出目录（data/library/linear_module）")
    a = ap.parse_args(argv)
    for doc, pdf in DOCS.items():
        if pdf.exists():
            print(f"{doc}：{pdf.name} SHA-256 {hashlib.sha256(pdf.read_bytes()).hexdigest()}", file=sys.stderr)
    comps, problems = build()
    a.out.mkdir(parents=True, exist_ok=True)
    bad = len(problems)
    for p in problems:
        print(p, file=sys.stderr)
    for c in comps:
        errs = list(errors("component.schema.json", c))
        if errs:
            bad += 1
            print(c["id"], errs[:3], file=sys.stderr)
            continue
        (a.out / f"{c['id']}.json").write_text(json.dumps(c, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                                encoding="utf-8")
    print(f"{len(comps)} 个型号写入 {a.out}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
