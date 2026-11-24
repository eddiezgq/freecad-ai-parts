"""整机案例“和公开资料的对照”页（ADR-0115 44.3 之二第 8 步）。

同类机器人的公开规格（案例目录的 `reference.json`，每条带网址、查阅日期、原话）只作参照：
不进零件库、不参与校核、不作为方案依据。我们的数全部取 `out/` 里的结果文件。
原单位经 `ingest.units` 换成标准单位；厂商没给的显示“未公开”，我们结果里没有的显示“待确认”。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from ingest.units import to_standard

FIELDS = ("payload_kg", "reach_mm", "mass_kg", "repeatability_mm", "joint_speed_rpm")
NOT_PUBLISHED = "未公开"
MISSING = "待确认"


def _num(x, nd: int = 3) -> str:
    return f"{round(float(x), nd):g}"


def load_reference(path: str | Path) -> dict:
    """读参照文件，把每项的原单位换成标准单位（value / min / max），原话保留。"""
    ref = json.loads(Path(path).read_text(encoding="utf-8"))
    for r in ref["robots"]:
        for f in FIELDS:
            p = r.get(f)
            if p is None:
                continue
            for k in ("value", "min", "max"):
                if k in p:
                    p[k + "_std"] = to_standard(p[k], p["unit"], f)
    return ref


def ours(res: Mapping) -> dict:
    """我们的数：只取结果文件，没有的项不写。"""
    c = res.get("concept") or {}
    cond = c.get("conditions") or {}
    cad = res.get("cad") or {}
    rp = (res.get("build") or {}).get("repeatability") or {}
    vchecks = next(iter(((res.get("verify") or {}).get("checks") or {}).values()), {}).get("checks") or []
    s3 = next((x for x in vchecks if x.get("check") == "S3"), {})
    o = {"dof": cond.get("dof"), "payload_kg": cond.get("payload"), "reach_mm": cond.get("reach"),
         "mass_kg": cad.get("mass_kg"), "repeatability_mm": rp.get("worst_mm"), "joint_speed_rpm": s3.get("limit"),
         "joint_speed_required_rpm": cond.get("joint_speed"), "repeatability_required_mm": cond.get("repeatability")}
    return {k: v for k, v in o.items() if v is not None and not isinstance(v, bool)}


def _ref_cell(p: Mapping | None, nd: int = 3) -> str:
    if not p:
        return NOT_PUBLISHED
    if "value_std" in p:
        return _num(p["value_std"], nd)
    return f"{_num(p['min_std'], nd)}–{_num(p['max_std'], nd)}"


def _ratio(payload, mass) -> str:
    return _num(payload / mass, 2) if payload is not None and mass else MISSING


def page(res: Mapping, ref: Mapping, bom: Mapping | None = None) -> str:
    o = ours(res)
    rows = []
    for r in ref["robots"]:
        pl = (r.get("payload_kg") or {}).get("value_std")
        m = (r.get("mass_kg") or {}).get("value_std")
        rows.append([f"{r['vendor']} {r['name']}", _num(r["dof"]["value"], 0) if r.get("dof") else NOT_PUBLISHED,
                     _ref_cell(r.get("payload_kg")), _ref_cell(r.get("reach_mm"), 1), _ref_cell(r.get("mass_kg")),
                     _ratio(pl, m), "±" + _ref_cell(r.get("repeatability_mm"), 2) if r.get("repeatability_mm") else NOT_PUBLISHED,
                     _ref_cell(r.get("joint_speed_rpm"), 1)])

    def g(k, nd=3):
        return _num(o[k], nd) if k in o else MISSING

    mine = ["**本案例 A（我们的方案）**", g("dof", 0), g("payload_kg"), g("reach_mm", 1), g("mass_kg"),
            _ratio(o.get("payload_kg"), o.get("mass_kg")), "±" + g("repeatability_mm", 2), g("joint_speed_rpm", 1)]
    head = ["机器人", "自由度", "负载 kg", "臂展 mm", "自重 kg", "负载自重比", "重复定位 mm", "主臂关节最高速度 rpm"]
    out = ["# 案例 A：和公开资料的对照", "",
           "> 这些公开数字只作参照：不进零件库、不参与校核，我们的方案也不以它们为依据（ADR-0115 第 5 节）。",
           f"> 参照数取各厂商自己的规格页，查阅日期 {ref.get('accessed', MISSING)}；我们的数全部取 `out/` 里的结果文件。", "",
           "## 对照表", ""]
    out += ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    for row in [mine] + rows:
        out.append("| " + " | ".join(row) + " |")
    out += ["", ("我们的数出自：自由度、负载、臂展取 concept-result.json · conditions（臂展已由初筛验证能到）；"
                 "自重取 cad/cad-result.json · mass_kg；重复定位取 build-result.json · repeatability · worst_mm；"
                 "关节速度取 verify-result.json · S3（带载最紧一点）。"), ""]

    out += ["## 口径不同的地方（看表之前先看这里）", ""]
    out.append("- **自重**：我们的自重是三维装配里 5 个模组加 15 个自制件，不含夹爪、控制器、电源、线缆和桌面夹具；"
               "各厂商的自重口径见表下出处里的原话（例如 Magician 写整机净重，Lite 6 注明只算机械臂），含不含控制器各不相同。"
               "负载自重比因此只能看量级。")
    out.append("- **重复定位精度**：我们的 ±{} mm 是按编码器分辨率逐关节累加的最坏值（代码算的，偏保守），只对同向趋近成立；"
               "厂商给的是实测统计值（Niryo 注明按 ISO 9283）。两者不是同一种量，不能直接比高低。".format(g("repeatability_mm", 2)))
    req = o.get("joint_speed_required_rpm")
    out.append("- **关节速度**：我们的 {} rpm 是带满载、在检验动作最紧的一点上模组还能达到的转速（需求 {} rpm）；"
               "厂商给的是各自口径的最高值：Magician 注明带 250 g，Ned2 是名义值，其余没写带多少负载。".format(
                   g("joint_speed_rpm", 1), _num(req, 1) if req is not None else MISSING))
    out.append("- **自由度**：OpenMANIPULATOR-X 另有 1 个夹爪自由度，表里只计机械臂。")
    out.append("")

    out += ["## 从对照里看出的事", ""]
    if bom and o.get("mass_kg"):
        share = bom["made_mass_kg"] / o["mass_kg"]
        line = (f"- 我们的自重里自制支架和管件占 {share:.0%}（BOM：自制件 {_num(bom['made_mass_kg'])} kg，"
                f"外购模组 {_num(bom['purchased_mass_kg'])} kg）。")
        items = [x for x in ((res.get("fea") or {}).get("items") or []) if x.get("status") == "pass"]
        if items and all(x.get("safety_yield") and x.get("safety_fatigue") for x in items):
            line += (f"支架有限元里对屈服的安全系数最低 {_num(min(x['safety_yield'] for x in items), 1)}、"
                     f"对弯曲疲劳最低 {_num(min(x['safety_fatigue'] for x in items), 1)}，要求 1.2（fea-result.json），"
                     "支架有减薄的余地；减薄后负载自重比会提高。减薄要另定方案。")
        out.append(line)
    om = next((r for r in ref["robots"] if r["vendor"] == "ROBOTIS"), None)
    if om and om.get("mass_kg") and o.get("mass_kg"):
        out.append(f"- 同厂的 OpenMANIPULATOR-X 用小一号的模组、4 个自由度，自重 {_ref_cell(om['mass_kg'])} kg、负载同为 0.5 kg；"
                   f"我们 5 个自由度、臂展 {g('reach_mm', 1)} mm，自重 {g('mass_kg')} kg。"
                   "模组选型由我们的载荷与校核决定，不以它为依据。")
    reps = [r["repeatability_mm"]["value_std"] for r in ref["robots"] if r.get("repeatability_mm")]
    if reps:
        out.append(f"- 上表公开教学臂的重复定位精度在 ±{_num(min(reps), 2)}～±{_num(max(reps), 2)} mm，"
                   f"我们需求是 ±{_num(o['repeatability_required_mm'], 2) if 'repeatability_required_mm' in o else MISSING} mm、"
                   f"最坏估算 ±{g('repeatability_mm', 2)} mm；反向趋近时的回差（报告第 6 节）这几家的规格页都没有给，无从对照。")
    out.append("")

    out += ["## 节拍与续航", "",
            ("- 节拍：这几家的规格页都没有给统一工况下的节拍。我们的检验动作是各关节同时转 90°、用时 2 s（build-result.json · assumptions），"
             "只用来算载荷，不是节拍指标。"),
            "- 续航：桌面臂接市电，不适用。", "",
            "## 出处", ""]
    for r in ref["robots"]:
        urls = [r["url"]] + sorted({(r.get(f) or {}).get("url") for f in ("dof",) + FIELDS} - {None, r["url"]})
        quotes = "；".join(f"“{(r.get(f) or {}).get('quote')}”" for f in ("dof",) + FIELDS if r.get(f))
        out.append(f"- {r['vendor']} {r['name']}（{r['why']}）：" + "、".join(f"<{u}>" for u in urls) + f"。原话：{quotes}")
    return "\n".join(out) + "\n"


def write(case_dir: str | Path, res: Mapping, bom: Mapping | None = None) -> Path | None:
    """案例目录有 reference.json 时出 out/comparison.md，返回路径；没有就不出。"""
    case_dir = Path(case_dir)
    rp = case_dir / "reference.json"
    if not rp.exists():
        return None
    p = case_dir / "out" / "comparison.md"
    p.write_text(page(res, load_reference(rp), bom), encoding="utf-8")
    return p
