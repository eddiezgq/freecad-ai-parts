"""一体化关节模组：ROBOTIS DYNAMIXEL X 系列 → smart_actuator 组件（ADR-0117 第 117.2 步）。

来源：ROBOTIS e-Manual 的规格表。e-Manual 网页由公开源码仓库（github.com/ROBOTIS-GIT/emanual）生成，
X 系列规格表是其中一份结构化数据文件 `_data/dxl_x_info.yml`（网页“Specifications”一节逐项取自它）。
按 ADR-0040 只收规格参数、逐项注明出处；源文件放 data/raw/robotis/（不入 git），在 data/sources.yaml 的 robotis 下登记
固定版本（仓库提交号）的下载网址与 SHA-256。本模块只读这份文件，不联网、不调用 AI。

取值规则：
- 堵转力矩、堵转电流、空载转速：规格表按几个电压各给一行，取厂商“推荐电压”那一行（Input Voltage 里的 Recommended），
  condition 写电压；推荐电压没有对应行的型号不收这几项（不插值）。
- 堵转力矩不是连续额定力矩（e-Manual 规格页注明），连续额定 rated_torque_nm 规格表里没有，不写。
- 质量、减速比、回差（N/A 不写）、分辨率（pulse/rev）照表。
- 供电：直流，电压范围照 Input Voltage；总线协议：X 系列控制表一节写明用 DYNAMIXEL Protocol 2.0（dynamixel_2）。
- 机械接口（舵盘孔位、壳体安装孔）只在图纸里，不写端口（ADR-0117）。
- 包络：规格表只给外形 W × H × D；舵盘在哪个面、轴线在面上的位置只在图纸里，所以取不依赖这两点的保守外框：
  设 a = max(W, H, D)，沿输出轴长 a（在输出面之后）、截面 2a × 2a（轴线在任何一面的任何位置都包得住），
  method = computed，公式写明。拿到图纸后换成实际外形。
不收：XL320（规格不在这份文件里）、2XL430 / 2XC430（一个壳里两个轴，不是一个关节）。

命令：python -m ingest.robotis_dxl data/raw/robotis/dxl_x_info.yml --out data/library/smart_actuator
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from ingest.units import to_standard

SOURCE_DOC = "src-robotis-emanual-dxl-x-info"
VENDOR = "ROBOTIS"
SKIP = {"common_x_specs": "公共字段", "xl320": "规格不在本文件", "2xl430-w250": "双轴", "2xc430-w250": "双轴"}
PAGE = "https://emanual.robotis.com/docs/en/dxl/x/{ref}/"
_NUM = r"(\d+(?:\.\d+)?)"
AT_ROW = re.compile(_NUM + r"\s*\[(N\.m|rev/min)\]\s*\(at\s*" + _NUM + r"\s*\[V\](?:,\s*" + _NUM + r"\s*\[A\])?")
RECOMMENDED = re.compile(r"Recommended\s*:\s*" + _NUM + r"\s*\[V\]")
V_RANGE = re.compile(_NUM + r"\s*~\s*" + _NUM + r"\s*\[V\]")
V_SINGLE = re.compile(r"^\s*" + _NUM + r"\s*\[V\]")
MASS = re.compile(_NUM + r"\s*\[?(g)\]?")
DIMS = re.compile(_NUM + r"\s*x\s*" + _NUM + r"\s*x\s*" + _NUM + r"\s*\[?mm\]?")
RATIO = re.compile(_NUM + r"\s*:\s*1")
ARCMIN = re.compile(_NUM + r"\s*\[arcmin\]")
RES = re.compile(r"(\d+)\s*\[pulse/rev\]")


REVIEW = ("解析结构化规格表（确定性程序，不经 AI）；2026-11-22 Claude 抽查 XM430-W350、XM540-W270、XC330-T181、XH540-W150 "
          "四个型号的网页规格表，各项与解析结果一致（经张国庆授权，ADR-0040）")


def load(path: Path) -> dict:
    """读规格表。源文件里有一处引用了没定义的锚点（*ttl_connection_5v_5v，只用于“物理接线”一栏，本模块不取），
    读之前把它换成字符串，其余原样。"""
    import yaml

    text = path.read_text(encoding="utf-8").replace("*ttl_connection_5v_5v", '"N/A"')
    return yaml.safe_load(text)


def _pv(value, note: str, ref: str, condition: str | None = None, method: str = "extracted", formula: str | None = None) -> dict:
    src = {"doc": SOURCE_DOC, "note": f"{PAGE.format(ref=ref)} Specifications：{note}"}
    if formula:
        src["formula"] = formula
    out = {"source": src, "method": method, "confidence": 1.0, "reviewed": True}   # 复核：见 REVIEW
    if isinstance(value, tuple):
        out["min"], out["max"] = value
    else:
        out["value"] = value
    if condition:
        out["condition"] = condition
    return out


def _at(text: str, unit: str, volts: float) -> tuple[float, float | None] | None:
    """规格表某一栏在给定电压那一行的 (值, 电流)"""
    for m in AT_ROW.finditer(text or ""):
        if m.group(2) == unit and float(m.group(3)) == volts:
            return float(m.group(1)), (float(m.group(4)) if m.group(4) else None)
    return None


def component(ref: str, row: dict) -> tuple[dict | None, list[str]]:
    """一个型号 → (组件, 没收的项与原因)"""
    gaps: list[str] = []
    model = ref.upper()
    v = row.get("voltage_en") or ""
    rec = RECOMMENDED.search(v)
    if not rec:
        return None, ["输入电压一栏没有推荐电压"]
    volts = float(rec.group(1))
    cond = f"{volts:g} V（厂商推荐电压）"
    params: dict = {}
    st = _at(row.get("stalltorque", ""), "N.m", volts)
    if st:
        params["stall_torque_nm"] = _pv(st[0], "Stall Torque", ref, cond)
        if st[1] is not None:
            params["stall_current_a"] = _pv(st[1], "Stall Torque 一栏括号内的电流", ref, cond)
    else:
        gaps.append(f"堵转力矩没有 {volts:g} V 那一行")
    sp = _at(row.get("noloadspeed", ""), "rev/min", volts)
    if sp:
        params["no_load_speed_rpm"] = _pv(to_standard(sp[0], "rev/min", "no_load_speed_rpm"), "No Load Speed", ref, cond)
    else:
        gaps.append(f"空载转速没有 {volts:g} V 那一行")
    m = MASS.search(str(row.get("weight", "")))
    if m:
        params["mass_kg"] = _pv(round(to_standard(float(m.group(1)), "g", "mass_kg"), 6), "Weight（原单位 g）", ref)
    else:
        gaps.append("质量")
    r = RATIO.search(str(row.get("gearratio", "")))
    if r:
        params["gear_ratio"] = _pv(float(r.group(1)), "Gear Ratio", ref)
    b = ARCMIN.search(str(row.get("backlash", "")))
    if b:
        params["backlash_arcmin"] = _pv(float(b.group(1)), "Backlash", ref)
    res = RES.search(str(row.get("resolution", "")))
    if res:
        params["resolution_counts_per_rev"] = _pv(int(res.group(1)), "Resolution", ref)
    vr = V_RANGE.search(v)
    vs = V_SINGLE.search(v)
    vrange = (float(vr.group(1)), float(vr.group(2))) if vr else (float(vs.group(1)),) * 2 if vs else None
    if vrange is None:
        return None, gaps + ["输入电压范围"]
    ports = [{"id": "power_in", "type": "electrical.power_supply", "dir": "in",
              "spec": {"current_type": _pv("dc", "Input Voltage（直流）", ref),
                       "voltage_v": _pv(vrange, "Input Voltage", ref) if vrange[0] != vrange[1]
                       else _pv(vrange[0], "Input Voltage", ref),
                       "phases": _pv(0, "直流", ref)}},
             {"id": "bus", "type": "signal.fieldbus", "dir": "bidir",
              "spec": {"protocol": _pv("dynamixel_2", "Control Table 一节：X 系列用 DYNAMIXEL Protocol 2.0；物理层 "
                                       + re.sub(r"<[^>]+>", " ", str(row.get("protocoltype", ""))).strip(), ref)}}]
    d = DIMS.search(str(row.get("dimensions", "")))
    if not d:
        return None, gaps + ["外形尺寸（包络）"]
    w, h, dep = (float(d.group(i)) for i in (1, 2, 3))
    a = max(w, h, dep)
    f = "保守外框：a = max(W, H, D)；沿输出轴长 a，截面 2a × 2a（舵盘在哪个面、轴线位置只在图纸里）"
    note = f"Dimensions (W x H x D) = {w:g} x {h:g} x {dep:g}"
    env = {"parts": [{"shape": "box", "label": "body（保守外框）", "z_start_mm": -a,
                      "length_mm": _pv(a, note, ref, method="computed", formula=f),
                      "width_mm": _pv(2 * a, note, ref, method="computed", formula=f),
                      "height_mm": _pv(2 * a, note, ref, method="computed", formula=f)}]}
    comp = {"id": f"smart_actuator.robotis.{ref}", "category": "smart_actuator", "vendor": VENDOR, "model": model,
            "series": "DYNAMIXEL X", "status": "active", "license": "params-only", "params": params, "ports": ports,
            "envelope": env,
            "note": (f"{REVIEW}。参数取自 ROBOTIS e-Manual 规格表（{SOURCE_DOC}，ADR-0040、ADR-0117），力矩与转速是输出端、推荐电压下的值；"
                     "堵转力矩不是连续额定（厂商没给连续额定，连续力矩校核为待确认）；"
                     "舵盘与壳体安装孔位只在厂商图纸里，没有收录，整机装配时这两处接口判待确认；包络是保守外框。")}
    return comp, gaps


def build(path: Path) -> tuple[list[dict], dict[str, list[str]]]:
    data = load(path)
    comps, report = [], {}
    for ref, row in data.items():
        if ref in SKIP:
            report[ref] = [f"不收：{SKIP[ref]}"]
            continue
        c, gaps = component(ref, row or {})
        if gaps:
            report[ref] = gaps
        if c:
            comps.append(c)
    return comps, report


def main(argv: list[str] | None = None) -> int:
    from kb.validation import errors

    ap = argparse.ArgumentParser(prog="python -m ingest.robotis_dxl", description=__doc__.splitlines()[0])
    ap.add_argument("source", type=Path, help="dxl_x_info.yml（固定版本，见 data/sources.yaml）")
    ap.add_argument("--out", type=Path, required=True, help="输出目录（data/library/smart_actuator）")
    ap.add_argument("--sha256", help="核对源文件的 SHA-256")
    a = ap.parse_args(argv)
    digest = hashlib.sha256(a.source.read_bytes()).hexdigest()
    if a.sha256 and digest != a.sha256:
        print(f"源文件 SHA-256 不符：{digest}", file=sys.stderr)
        return 1
    comps, report = build(a.source)
    a.out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for c in comps:
        errs = list(errors("component.schema.json", c))
        if errs:
            bad += 1
            print(c["id"], errs[:3], file=sys.stderr)
            continue
        (a.out / f"{c['id']}.json").write_text(json.dumps(c, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                                encoding="utf-8")
    print(f"{len(comps) - bad} 个型号写入 {a.out}；源文件 SHA-256 {digest}", file=sys.stderr)
    for ref, gaps in report.items():
        print(f"  {ref}：{'；'.join(gaps)}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
