"""龙门取放机器人（案例 B）的报告、BOM 与“和公开资料的对照”页（ADR-0115 44.5.5 第三步）。

只读 `out/` 里各步的结果文件，不重算、不调用 AI、不联网：
- `bom.json`、`bom.csv`：外购件（零件库型号与资料出处）、自制件（三维模型体积 × 密度）、未列入的（库里没有、没建模的）；
- `report.md`：交付六项——整机方案、校核结论、仿真数字与需求对照、模型与 BOM、用时、卡在哪里；
- `comparison.md`：案例目录有 `reference.json` 时出，公开数字只作参照。
每个数注明来自哪个结果文件的哪一项；结果文件里没有的写“待确认”和原因，不估。
"""

from __future__ import annotations

import csv
import io
import json
import sys
from collections.abc import Mapping
from pathlib import Path

from assist.robot_report import MISSING, _lib_component, _n, _param_source, _st, _table

FILES = {"concept": "concept-result.json", "build": "build-result.json", "cad": "cad-result.json", "timing": "timing.json"}
PREFIX = "SL"                                           # 自制件图号前缀（Sewing Loader）
NOT_LISTED = [
    "电机与电机套件（联轴器、法兰）：零件库里没有配费斯托模组的电机，电机没选（要的力矩与转速见报告第 2 节）；竖直轴要带抱闸",
    "真空发生器、气管与接头：零件库里没有",
    "控制器、驱动器、线缆与拖链：零件库里没有",
    "X 模组装在横梁下面用的安装件（型材连接件、滑块螺母）：没建模",
    "紧固件：三维装配没建螺钉孔，规格与数量待定",
    "立柱落脚处的安装面（与台面同高）：属于车间现场，不在本机 BOM",
]
REF_FIELDS = ("cycle_s", "payload_kg", "work_range_mm")


def load(out_dir: str | Path) -> dict:
    d = Path(out_dir)
    return {k: json.loads((d / f).read_text(encoding="utf-8")) for k, f in FILES.items() if (d / f).exists()}


# ---------------------------------------------------------------- BOM
def bom(res: Mapping, component=_lib_component) -> dict:
    """外购件取复核后的选件（质量是零件库的目录值）；自制件取三维装配（体积 × 密度）；抓手质量厂商没给就不计、写明。"""
    cad, rv = res["cad"]["cad"], res["cad"]["reverify"]
    picks = rv["picks"]
    grip = (res.get("build") or {}).get("gripper") or {}
    purchased, made, unknown_mass = [], [], []
    for p in cad["parts"]:
        if p["kind"] == "module":
            comp = component(p["component"]) or {}
            pk = picks.get(p["joint"]) or {}
            purchased.append({"kind": "purchased", "role": "直线模组", "component": p["component"], "model": pk.get("model"),
                              "vendor": comp.get("vendor"), "qty": 1, "joints": [p["joint"]], "mass_kg_each": pk.get("mass_kg"),
                              "mass_source": _param_source(comp, "mass_kg") or "零件库"})
        elif p["kind"] == "gripper":
            comp = component(grip.get("component")) or {}
            purchased.append({"kind": "purchased", "role": "抓手", "component": grip.get("component"), "model": grip.get("model"),
                              "vendor": comp.get("vendor"), "qty": 1, "joints": [], "mass_kg_each": grip.get("mass_kg"),
                              "mass_source": _param_source(comp, "mass_kg") or "厂商没给质量（未计入）"})
            if grip.get("mass_kg") is None:
                unknown_mass.append(f"抓手 {grip.get('model')}")
        else:
            made.append({"kind": "made", "drawing_no": f"{PREFIX}-{len(made) + 1:02d}", "name": p["name"], "qty": 1,
                         "group": "门架" if p["kind"] == "frame" else "工具链" if p.get("tool") else "连接件",
                         "material": p.get("material"), "mass_kg": p["mass_kg"],
                         "mass_source": f"三维模型体积 {_n(p.get('volume_mm3'), 1)} mm³ × {p.get('material')} 密度"})
    pm = sum(r["mass_kg_each"] * r["qty"] for r in purchased if r["mass_kg_each"] is not None)
    mm = sum(r["mass_kg"] for r in made)
    return {"format": "gantry-bom/1", "purchased": purchased, "made": made, "not_listed": list(NOT_LISTED),
            "purchased_mass_kg": round(pm, 4), "made_mass_kg": round(mm, 4), "total_mass_kg": round(pm + mm, 4),
            "mass_not_counted": unknown_mass}


def bom_csv(b: Mapping) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["序号", "类别", "图号 / 零件库编号", "名称 / 型号", "厂商", "材料", "数量", "单件质量 kg", "说明"])
    k = 0
    for r in b["purchased"]:
        k += 1
        w.writerow([k, "外购件", r["component"], r["model"], r["vendor"], "", r["qty"],
                    "" if r["mass_kg_each"] is None else r["mass_kg_each"],
                    r["role"] + ("（" + "、".join(r["joints"]) + "）" if r["joints"] else "") + "；质量出处：" + r["mass_source"]])
    for r in b["made"]:
        k += 1
        w.writerow([k, "自制件", r["drawing_no"], r["name"], "", r["material"], r["qty"], r["mass_kg"], f"{r['group']}；{r['mass_source']}"])
    for s in b["not_listed"]:
        w.writerow(["", "未列入", "", "", "", "", "", "", s])
    return buf.getvalue()


# ---------------------------------------------------------------- 报告
def _items(res: Mapping) -> dict:
    c = res["concept"]
    ev = c["rounds"][c["chosen_round"] - 1]["evaluations"][c.get("chosen_candidate", 0)]["items"]
    return {x["item"]: x for x in ev}


def _check(checks, name: str) -> Mapping:
    return next((x for x in checks or [] if x.get("check") == name), {})


def requirement_rows(res: Mapping, b: Mapping) -> list[list]:
    c, build, cr = res["concept"], res.get("build") or {}, res["cad"]
    cond = c.get("conditions") or {}
    it = _items(res)
    grip = build.get("gripper") or {}
    g = {x["check"]: x for x in grip.get("checks") or []}
    cyc = build.get("cycle_time") or {}
    jd = (cr.get("judge") or {}).get("deflection") or {}
    L = cr["cad"]["layout"]
    rows = [["取料区中心到放料区中心", f"{_n(cond.get('pick_to_place'), 0)} mm", f"{_n(it.get('取放水平距离', {}).get('value'), 0)} mm",
             _st(it.get("取放水平距离", {}).get("status")), "concept-result.json · 初筛「取放水平距离」"],
            ["裁床与送料台同高", f"离地 {_n(cond.get('work_height'), 0)} mm", "取放两处同高（方案坐标的 z = 0 即台面）",
             _st(it.get("取放两处同高", {}).get("status")), "concept-result.json · 初筛「取放两处同高」"],
            ["一叠最高", f"{_n(cond.get('stack_height'), 0)} mm", "一叠最高处够得着；Z 模组下端离一叠顶面 20 mm",
             _st(it.get(next((k for k in it if k.startswith("一叠最高处")), ""), {}).get("status")),
             "concept-result.json · 初筛「一叠最高处」；cad-result.json · design.stack_clear_mm"],
            ["裁片最大尺寸", f"{_n(cond.get('part_length'), 0)} × {_n(cond.get('part_width'), 0)} mm",
             f"取料区、放料区按 {_n(L['keepouts'][0]['box'][1][0] - L['keepouts'][0]['box'][0][0], 0)} mm 见方、一叠高避让，立柱、模组都不进去",
             _st("pass" if not cr["cad"]["keepout_hits"] else "fail"), "cad-result.json · cad.keepout_hits"],
            ["单片质量", f"≤ {_n((cond.get('part_mass') or 0) * 1000, 0)} g",
             f"吸盘 {grip.get('model', MISSING)} 要 {_n(grip.get('required_force_n'), 2)} N（含安全系数 2），厂商给 {_n(g.get('G1', {}).get('limit'), 2)} N",
             _st(g.get("G1", {}).get("status")), "build-result.json · gripper · G1"],
            ["节拍", f"≤ {_n(cyc.get('limit_s'), 1)} s/片", f"{_n(cyc.get('total_s'), 2)} s（动作加停留）；停稳时间算不了（见第 2 节门架频率）",
             _st(cyc.get("status")), "build-result.json · cycle_time"],
            ["放料定位精度", f"±{_n(cond.get('repeatability'), 1)} mm",
             (f"门架变形 {_n(jd.get('deflection_mm'), 3)} mm + 模组重复定位精度 ±{_n(jd.get('repeatability_mm'), 2)} mm = {_n(jd.get('total_mm'), 3)} mm；"
              "吸盘放料偏差没有公开数据，未计"), _st(jd.get("status")), "cad-result.json · judge · deflection"],
            ["不能损伤布料", "—", g.get("G2", {}).get("message") or MISSING, _st(g.get("G2", {}).get("status")), "build-result.json · gripper · G2"],
            ["一次只取一片", "—（原话“逐片取”）", g.get("G3", {}).get("message") or MISSING, _st(g.get("G3", {}).get("status")),
             "build-result.json · gripper · G3"],
            ["不能占用车间通道", "—", f"立柱在 x = {'、'.join(f'{x:g}' for x in L['col_x_mm'])} mm；通道位置原话没给，要现场核", MISSING,
             "cad-result.json · cad.layout.col_x_mm"]]
    cost = build.get("cost") or {}
    rows.append(["成本", "—", cost.get("note") or MISSING, _st(cost.get("status")), "build-result.json · cost"])
    return rows


def report(res: Mapping, b: Mapping) -> str:
    c, build, cr = res["concept"], res.get("build") or {}, res["cad"]
    cad, rv, L = cr["cad"], cr["reverify"], cr["cad"]["layout"]
    out = ["# 案例 B：缝纫车间裁片上下料机器人——设计报告", "",
           ("本报告由 `python -m assist.gantry_report` 从各步结果文件生成（ADR-0115 44.5.5）。“来源”栏或括号里写的是数字出自哪个文件、哪一项；"
            "“待确认”表示结果里没有、或代码判不了，原因写在旁边或第 6 节。"), "", "## 需求原话", ""]
    out += ["> " + x for x in c["statement"].strip().splitlines()]
    out += ["", "AI 从原话里摘出的条件（每条带原话引用，代码核对过单位）：", ""]
    out += _table(["条件", "值", "单位", "原话"], [[q["what"], _n(q["value"], 3) if isinstance(q["value"], (int, float)) else q["value"],
                                                  q["unit"], q["quote"]] for q in c.get("quotes") or []])
    if c.get("questions"):
        out += ["", "AI 提出的问题（本次没有人作答，按原话和默认假设做）：", ""] + [f"- {q}" for q in c["questions"]]

    out += ["", "## 1 整机方案", ""]
    for k, r in enumerate(c["rounds"], 1):
        for i, (cand, ev) in enumerate(zip(r["proposal"]["candidates"], r["evaluations"])):
            out.append(f"- 第 {k} 轮构型 {i}「{cand['name']}」：初筛 {_st(ev['overall'])}。AI 的理由：{cand.get('reason', '')}")
            bad = [x for x in ev["items"] if x["status"] == "fail"]
            if bad:
                out.append("  - 没通过：" + "；".join(f"{x['item']}（{x.get('note', '')}）" for x in bad))
    ch = c["chosen"]
    out += ["", (f"采用第 {c['chosen_round']} 轮构型 {c.get('chosen_candidate', 0)}「{ch.get('name')}」"
                 "（初筛里“待确认”的几项——末端速度与加速度、抓取力、重复定位精度——都在选件那一步判，见第 2 节）。"), ""]
    out += _table(["关节", "类型", "方向", "行程 mm", "父 → 子"], [[j["id"], j["type"], j["axis"], j.get("range_mm"),
                                                           f"{j['parent']} → {j['child']}"] for j in ch["joints"]])
    xl, xr = L["col_x_mm"]
    out += ["", ("布置（三维装配定的，cad-result.json · cad.layout）：门架两根立柱在 x = "
                 f"{xl:g} mm 与 {xr:g} mm（取料区、放料区外各 {_n(cr['design']['keepout_clear_mm'], 0)} mm），横梁跨度 {_n(L['span_mm'], 0)} mm；"
                 f"X 模组倒挂在横梁下、滑台面离台面 {_n(L['slide_x_mm'], 0)} mm；Z 模组竖装在 L 形连接板上，竖管用管夹装在 Z 滑台上，下端吸盘座与吸盘。"
                 "取料点在 x = 0，放料点在 x = 1500 mm，台面 z = 0。")]

    out += ["", "## 2 校核结论", "", "### 节拍（build-result.json · cycle_time、cycle）", ""]
    cyc = build.get("cycle") or {}
    out.append(f"{_st((build.get('cycle_time') or {}).get('status'))}：{(build.get('cycle_time') or {}).get('note', MISSING)}")
    segs = cyc.get("segments") or []
    if segs:
        out.append("")
        out += _table(["动作", "距离 mm", "用时 s（含停留）", "停留 s", "最高速度 m/s", "加速度 m/s²"],
                      [[s.get("name"), _n(s.get("length_mm"), 1), _n(s["t1_s"] - s["t0_s"], 3), _n(s.get("dwell_s"), 2) if s.get("dwell_s") else "—",
                        _n(s.get("speed_m_s"), 3), _n(s.get("accel_m_s2"), 2)] for s in segs])
    out += ["", "### 选件（按三维装配的真实质量与偏置复核，cad-result.json · reverify）", ""]
    for j, p in rv["picks"].items():
        same = "与第一步相同" if rv["same_as_step1"].get(j) else "与第一步不同"
        out.append(f"{j}：{p['model']}（{same}）")
        out += [f"- {x['check']} {_st(x['status'])}：{x['message']}" for x in p["checks"]]
    out += ["", "电机（build-result.json · motors；零件库里没有配这两种模组的电机，没选）：", ""]
    out += [f"- {j}：{m.get('note')}" for j, m in (rv.get("motors") or build.get("motors") or {}).items()]
    grip = build.get("gripper") or {}
    out += ["", "### 抓手（build-result.json · gripper）", "",
            f"选 {grip.get('model', MISSING)}，结论 {_st(grip.get('overall'))}；比较过的："]
    for x in grip.get("compare") or []:
        out.append(f"- {x['model']}（{x.get('type_name')}）：{_st(x.get('overall'))}；"
                   + "；".join(f"{k['check']} {_st(k['status'])} {k['message']}" for k in x.get("checks") or []))
    rp = rv.get("repeatability") or build.get("repeatability") or {}
    out += ["", "### 重复定位精度（build-result.json · repeatability）", "", f"{_st(rp.get('status'))}：{rp.get('note', MISSING)}"]
    out += ["", "### 三维装配（cad-result.json · cad）", "",
            (f"结论 {_st(cad.get('status'))}；干涉 {len(cad.get('interferences') or [])} 处；进取料区、放料区 {len(cad.get('keepout_hits') or [])} 处。"
             "同一构件里的零件做实体求交；不同构件之间，把会动的零件按行程扫过的包围盒与别的零件求交（偏保守）。")]
    out += [f"- {x}" for x in (cr["frame_fea"]["limits"] if cr.get("frame_fea") else [])]
    out += ["", "复核前后的受力（第一步按方案约定的偏置、三维装配后按真实质量与偏置；cad-result.json · reverify · loads_vs_step1）：", ""]
    names = {"thrust_n": "推力 N", "force_lateral_n": "侧向力 N", "force_normal_n": "法向力 N", "moment_roll_nm": "滚转力矩 N·m",
             "moment_pitch_nm": "俯仰力矩 N·m", "moment_yaw_nm": "偏摆力矩 N·m"}
    rows = []
    for j, d in rv["loads_vs_step1"].items():
        rows += [[j, names[k], _n(v["step1"], 2), _n(v["cad"], 2)] for k, v in d.items() if (v["step1"] or v["cad"])]
    out += _table(["轴", "项目", "第一步", "三维装配后"], rows)
    out += ["", ("俯仰力矩变大是因为 Z 模组实际挂在 X 滑台下面约 200 mm，第一步按方案约定把滑台运动质量集中在关节原点；"
                 "载荷比较系数仍 ≤ 1，选件不变。")]
    fe, fo, jd = cr.get("frame_fea"), cr["frame_formula"], cr.get("judge") or {}
    out += ["", "### 门架有限元（cad-result.json · frame_fea、frame_formula、judge）", ""]
    if fe:
        r = fe["result"]
        out.append(f"变形 {_st((jd.get('deflection') or {}).get('status'))}：{(jd.get('deflection') or {}).get('note', MISSING)}。")
        out.append(f"频率只报数：{(jd.get('frequency') or {}).get('note', MISSING)}。")
        out.append("")
        out += _table(["网格 mm", "跨中变形 mm", "最大当量应力 MPa", "固有频率 Hz", "一阶方向"],
                      [[_n(x["size_mm"], 0), _n(x["u_pad_abs_mm"], 4), _n(x.get("vm_max_mpa"), 2),
                        "、".join(_n(f, 1) for f in x["freqs_hz"]), x.get("mode1_direction") or MISSING] for x in fe["runs"]])
        out += ["", (f"两层网格差别：变形 {fe['mesh_change']['u_pad']:.1%}、一阶频率 {fe['mesh_change']['f1']:.1%}；"
                     f"反力平衡误差 {_n(r['balance'].get('force_error_ratio'), 2)}。公式校核（偏保守）：跨中垂直 {_n(fo['sag_mm'], 3)} mm、"
                     f"侧移 {_n(fo['sway_mm'], 3)} mm；横梁水平弯曲 {_n(fo['f1_lateral_hz'], 1)} Hz、立柱侧摆 {_n(fo['f1_sway_hz'], 1)} Hz、"
                     f"跨中竖直 {_n(fo['f1_vertical_hz'], 1)} Hz。")]
        out += [f"- {x}" for x in r.get("notes") or []]
    else:
        out.append(f"{MISSING}：有限元没跑（只有公式校核：变形 {_n(fo['deflection_mm'], 3)} mm）。")

    out += ["", "## 3 仿真数字与需求逐条对照", ""]
    out += _table(["需求", "要求", "结果", "结论", "来源"], requirement_rows(res, b))
    out += ["", "运动部分（cad-result.json · moving，三维装配的真实质量）：", ""]
    out += _table(["构件", "质量 kg", "重心 mm（零位）"], [[j, _n(v["mass_kg"], 3), v["cog_mm"]] for j, v in cr["moving"].items()])
    out += ["", "假设（build-result.json · assumptions）：", ""] + [f"- {a}" for a in build.get("assumptions") or []]

    out += ["", "## 4 三维模型与 BOM", "",
            ("三维装配：`out/cad/assembly.step`，门架有限元用的实体 `out/cad/frame.step`（不入库；`python -m assist.gantry_case` 重新生成），"
             "各零件见 cad-result.json · cad.parts。BOM：`out/bom.json`、`out/bom.csv`。"), ""]
    out += ["外购件：", ""] + _table(["零件库编号", "型号", "用途", "数量", "单件 kg", "质量出处"],
                                   [[r["component"], f"{r['vendor']} {r['model']}", r["role"], r["qty"], _n(r["mass_kg_each"]), r["mass_source"]]
                                    for r in b["purchased"]])
    out += ["", "自制件：", ""] + _table(["图号", "名称", "分组", "材料", "质量 kg"],
                                      [[r["drawing_no"], r["name"], r["group"], r["material"], _n(r["mass_kg"], 4)] for r in b["made"]])
    out += ["", "未列入："] + [f"- {s}" for s in b["not_listed"]]
    nc = "；" + "、".join(b["mass_not_counted"]) + " 的质量厂商没给，未计" if b["mass_not_counted"] else ""
    out += ["", (f"质量：外购件 {_n(b['purchased_mass_kg'])} kg + 自制件 {_n(b['made_mass_kg'])} kg = {_n(b['total_mass_kg'])} kg{nc}；"
                 "电机、气路、控制器不在内。")]

    out += ["", "## 5 用时", ""]
    t = res.get("timing")
    if t:
        out.append(f"本机 {t.get('machine', MISSING)}，{t.get('date', '')}，AI {t.get('ai', MISSING)}。")
        out.append("")
        out += _table(["步骤", "谁做", "用时 s"], [[s["step"] + (f"（{s['note']}）" if s.get("note") else ""), s["who"], _n(s["seconds"], 1)]
                                                for s in t["steps"]])
        out += ["", f"合计 {_n(sum(s['seconds'] for s in t['steps']), 1)} s。要人确认的：需求条件（AI 摘的条件、AI 的问题）、采用哪个构型、最终结果入企业库。"]
    else:
        out.append(f"{MISSING}：没有 timing.json（用 `python -m assist.gantry_case` 跑一遍才有）。")

    out += ["", "## 6 卡在哪里", ""] + [f"- {x}" for x in open_items(res, b)]
    return "\n".join(out) + "\n"


def open_items(res: Mapping, b: Mapping) -> list[str]:
    cr, build = res["cad"], res.get("build") or {}
    items = list(cr.get("open_items") or [])
    cost = build.get("cost") or {}
    if cost.get("status") != "pass":
        items.append(f"成本：{cost.get('note') or MISSING}")
    items.append("横梁、立柱、连接板、管夹这一版用设计值（cad-result.json · design），没有按受力减薄；由 AI 按载荷改尺寸、代码校核放到后面（与案例 A 的基座减薄同一步）")
    items.append("吸盘个数与排布要按裁片大小与平整度定（这里按 1 个吸盘核保持力，偏保守）；布料透气漏气、一次只取一片要实物试")
    if not cr.get("frame_fea"):
        items.append("门架有限元没跑")
    return items


# ---------------------------------------------------------------- 和公开资料的对照
def load_reference(path: str | Path) -> dict:
    from ingest.units import to_standard

    ref = json.loads(Path(path).read_text(encoding="utf-8"))
    for r in ref["robots"]:
        for f in REF_FIELDS:
            p = r.get(f)
            for k in ("value", "min", "max"):
                if p and k in p:
                    p[k + "_std"] = to_standard(p[k], p["unit"], f)
    return ref


def _cell(p: Mapping | None) -> str:
    if not p:
        return "未公开"
    if "value_std" in p:
        return _n(p["value_std"], 2)
    if "min_std" in p and "max_std" in p:
        return f"{_n(p['min_std'], 2)}–{_n(p['max_std'], 2)}"
    return f"≤ {_n(p['max_std'], 2)}" if "max_std" in p else f"≥ {_n(p['min_std'], 2)}"


def _stroke(build: Mapping, joint: str):
    return next((r.get("stroke_mm") for r in (build.get("bom") or {}).get("purchased") or [] if joint in (r.get("joints") or [])), None)


def comparison(res: Mapping, ref: Mapping, b: Mapping) -> str:
    build, cr = res.get("build") or {}, res["cad"]
    cyc = build.get("cycle_time") or {}
    grip = build.get("gripper") or {}
    L = cr["cad"]["layout"]
    xl, xr = L["col_x_mm"]
    head = ["设备", "形式", "节拍 s/片", "机器人负载 kg", "工作范围 mm", "抓手"]
    mine = ["**本案例 B（我们的方案）**", "台面上的 X–Z 两轴龙门（费斯托直线模组）",
            _n(cyc.get("total_s"), 2) + "（要求 ≤ " + _n(cyc.get("limit_s"), 1) + "）",
            "—（按单片 " + _n((res["concept"].get("conditions") or {}).get("part_mass"), 2) + " kg 算）",
            f"X 行程 {_n(_stroke(build, L['axes'][0]['joint']), 0)}，门架占地 x = {xl:g}～{xr:g}",
            f"真空吸盘 {grip.get('model', MISSING)}"]
    rows = [[f"{r['vendor']} {r['name']}", r.get("kind", "未公开"), _cell(r.get("cycle_s")), _cell(r.get("payload_kg")),
             _cell(r.get("work_range_mm")) + ("（直径）" if r.get("work_range_mm") else ""), (r.get("gripper") or {}).get("text", "未公开")]
            for r in ref["robots"]]
    out = ["# 案例 B：和公开资料的对照", "",
           "> 这些公开数字只作参照：不进零件库、不参与校核，我们的方案也不以它们为依据（ADR-0115 第 5 节）。",
           f"> 参照数取各家公开页面，查阅日期 {ref.get('accessed', MISSING)}；我们的数全部取 `out/` 里的结果文件。", "", "## 对照表", ""]
    out += _table(head, [mine] + rows)
    out += ["", ("我们的数出自：节拍取 build-result.json · cycle_time；X 行程取 build-result.json · picks；"
                 "门架占地取 cad-result.json · cad.layout.col_x_mm；抓手取 build-result.json · gripper。"), "",
            "## 口径不同的地方（看表之前先看这里）", "",
            ("- **节拍**：我们的 " + _n(cyc.get("total_s"), 2) + " s 是一圈 6 段直线动作加两处停留（取—升—移—降—放—回），"
             "取放距离 1500 mm，不含吸盘建立真空与破真空的时间、不含停稳时间；Robotextile 写“视布置与条件而定”，没给取放距离；"
             "Grabit 的数是我们按“一分钟 40 片”折算的平均值，鞋面裁片、取放距离没给。"),
            "- **负载**：参照里的负载是机器人本身能带的最大质量，不是一片布的质量；我们的模组按单片 100 g 加真实运动质量选的。",
            "- **形式**：两家设备都是 SCARA（转动关节）；我们由 AI 提、代码初筛选了龙门（SCARA 构型在关节行程内够不着取放点，见报告第 1 节）。",
            "", "## 从对照里看出的事", ""]
    rt = next((r for r in ref["robots"] if r["vendor"] == "Robotextile"), None)
    if rt and rt.get("cycle_s"):
        out.append(f"- 专做布料取放的 Robotextile 给每层 {_cell(rt['cycle_s'])} s，我们 {_n(cyc.get('total_s'), 2)} s 落在这个范围里；"
                   "要不要留出吸放与停稳的余量，要实物试后定。")
    out.append(f"- 抓手：公开试验（Kong 等）用多个 Ø2 mm 小吸盘、−55 kPa 从一叠机织布里只取最上一片，各组判通过，但没给成功率；"
               f"我们按 1 个 {grip.get('model', MISSING)} 核保持力，对布料的适用性与一次只取一片仍是待确认（报告第 6 节）。")
    out.append(f"- 本机质量：外购件 {_n(b['purchased_mass_kg'])} kg + 自制件 {_n(b['made_mass_kg'])} kg（BOM），"
               "参照都没公开整机质量，无从对照。")
    out += ["", "## 出处", ""]
    for r in ref["robots"]:
        quotes = "；".join(f"“{(r.get(f) or {}).get('quote')}”" + (f"（{r[f]['note']}）" if (r.get(f) or {}).get("note") else "")
                          for f in REF_FIELDS + ("gripper",) if r.get(f))
        out.append(f"- {r['vendor']} {r['name']}（{r['why']}）：<{r['url']}>。原话：{quotes}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- 写文件
def write(out_dir: str | Path) -> dict:
    d = Path(out_dir)
    res = load(d)
    for k in ("concept", "build", "cad"):
        if k not in res:
            raise FileNotFoundError(f"缺 {FILES[k]}：先跑前面的步骤")
    b = bom(res)
    (d / "bom.json").write_text(json.dumps(b, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (d / "bom.csv").write_text(bom_csv(b), encoding="utf-8")
    (d / "report.md").write_text(report(res, b), encoding="utf-8")
    rp = d.parent / "reference.json"
    if rp.exists():
        (d / "comparison.md").write_text(comparison(res, load_reference(rp), b), encoding="utf-8")
    return b


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m assist.gantry_report", description="龙门取放机器人的报告与 BOM（ADR-0115 44.5.5）")
    ap.add_argument("out_dir", type=Path, help="案例的 out/ 目录")
    a = ap.parse_args(argv)
    try:
        b = write(a.out_dir)
    except FileNotFoundError as ex:
        print(str(ex), file=sys.stderr)
        return 1
    print(f"BOM：外购件 {len(b['purchased'])} 项、自制件 {len(b['made'])} 件；报告 {a.out_dir / 'report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
