"""整机案例的报告与 BOM（ADR-0115 44.3 之二第 7 步）。

只读 `out/` 里各步的结果文件，不重算、不调用 AI、不联网：
- `bom.json`、`bom.csv`：外购件（零件库型号与资料出处）、自制件（三维模型体积 × 密度）、紧固件（按装配里的螺钉孔计数）、未列入的；
- `report.md`：交付六项——整机方案、校核结论、仿真数字与需求对照、模型与 BOM、用时、卡在哪里。
  每个数注明来自哪个结果文件的哪一项；结果文件里没有的写“待确认”和原因，不估。
"""

from __future__ import annotations

import csv
import io
import json
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {"concept": "concept-result.json", "build": "build-result.json", "cad": "cad/cad-result.json",
         "verify": "verify-result.json", "fea": "fea-result.json", "timing": "timing.json", "thin": "thin-result.json"}
STATUS = {"pass": "通过", "fail": "不通过", "unknown": "待确认", "not_applicable": "不适用"}
SCREW = "ISO 4762 内六角圆柱头螺钉 M2.5"
SCREW_LENGTH_NOTE = "长度待定：模组上螺纹孔的深度不在零件库，登记后才能定"
MISSING = "待确认"


def load(out_dir: str | Path) -> dict:
    d = Path(out_dir)
    res = {}
    for k, f in FILES.items():
        p = d / f
        if p.exists():
            res[k] = json.loads(p.read_text(encoding="utf-8"))
    return res


def _lib_component(cid: str) -> dict | None:
    from kb.library import JsonLibrary

    return JsonLibrary(ROOT / "data" / "library").get(cid)


def _param_source(comp: Mapping | None, key: str) -> str | None:
    p = ((comp or {}).get("params") or {}).get(key) or {}
    s = p.get("source") or {}
    return "；".join(x for x in (s.get("doc"), s.get("note")) if x) or None


def _st(s: str | None) -> str:
    return STATUS.get(s or "", s or MISSING)


def _n(x, nd: int = 3) -> str:
    if x is None or isinstance(x, bool):
        return MISSING
    return f"{round(float(x), nd):g}"


def bom(res: Mapping, component=_lib_component) -> dict:
    """BOM：外购件 + 自制件 + 紧固件 + 未列入。质量全部取已有结果，不另算。"""
    cad = res["cad"]
    build = res.get("build") or {}
    purchased, made, holes = [], [], {}
    by_comp: dict[str, dict] = {}
    for p in cad["parts"]:
        if p["kind"] == "actuator":
            r = by_comp.get(p["component"])
            if r is None:
                comp = component(p["component"])
                r = by_comp[p["component"]] = {
                    "kind": "purchased", "component": p["component"], "vendor": (comp or {}).get("vendor"),
                    "model": (comp or {}).get("model"), "qty": 0, "joints": [], "mass_kg_each": p["mass_kg"],
                    "mass_source": _param_source(comp, "mass_kg") or "零件库"}
                purchased.append(r)
            r["qty"] += 1
            r["joints"].append(p["joint"])
        else:
            made.append({"kind": "made", "drawing_no": f"TA-{len(made) + 1:02d}", "name": p["name"], "qty": 1,
                         "material": p.get("material"), "mass_kg": p["mass_kg"],
                         "mass_source": f"三维模型体积 {_n(p.get('volume_mm3'), 1)} mm³ × {p.get('material')} 密度"})
            for side in ("fixed", "load"):
                i = (p.get("interfaces") or {}).get(side) or {}
                if i.get("type") == "holes":
                    g = holes.setdefault(float(i["length_mm"]), {"qty": 0, "parts": []})
                    g["qty"] += len(i["centers"])
                    g["parts"].append(p["name"])
    fasteners = [{"kind": "fastener", "name": SCREW, "grip_mm": t, "qty": g["qty"], "parts": g["parts"],
                  "note": SCREW_LENGTH_NOTE} for t, g in sorted(holes.items())]
    not_listed = list(((build.get("bom") or {}).get("notes")) or [])
    pm = sum(r["mass_kg_each"] * r["qty"] for r in purchased)
    mm = sum(r["mass_kg"] for r in made)
    return {"format": "robot-bom/1", "purchased": purchased, "made": made, "fasteners": fasteners,
            "not_listed": not_listed, "purchased_mass_kg": round(pm, 4), "made_mass_kg": round(mm, 4),
            "total_mass_kg": round(pm + mm, 4), "assembly_mass_kg": cad.get("mass_kg"),
            "fastener_mass": "未计（螺钉长度待定）"}


def bom_csv(b: Mapping) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["序号", "类别", "图号 / 零件库编号", "名称 / 型号", "厂商", "材料", "数量", "单件质量 kg", "说明"])
    k = 0
    for r in b["purchased"]:
        k += 1
        w.writerow([k, "外购件", r["component"], r["model"], r["vendor"], "", r["qty"], r["mass_kg_each"],
                    "关节 " + "、".join(r["joints"]) + "；质量出处：" + r["mass_source"]])
    for r in b["made"]:
        k += 1
        w.writerow([k, "自制件", r["drawing_no"], r["name"], "", r["material"], r["qty"], r["mass_kg"], r["mass_source"]])
    for r in b["fasteners"]:
        k += 1
        w.writerow([k, "紧固件", "", r["name"], "", "", r["qty"], "", f"夹紧厚度 {r['grip_mm']:g} mm；{r['note']}"])
    for s in b["not_listed"]:
        w.writerow(["", "未列入", "", "", "", "", "", "", s])
    return buf.getvalue()


def _table(head: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    out += ["| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in r) + " |" for r in rows]
    return out


def _check(checks: list[Mapping], name: str) -> Mapping:
    return next((c for c in checks if c.get("check") == name), {})


def requirement_rows(res: Mapping) -> list[list]:
    """需求逐条对照：要求、结果、结论、来源"""
    c = res["concept"]
    cond = c.get("conditions") or {}
    b = res.get("build") or {}
    v = res.get("verify") or {}
    ev = c["rounds"][c["chosen_round"] - 1]["evaluations"][c.get("chosen_candidate", 0)]["items"]
    item = {x["item"]: x for x in ev}
    vchecks = next(iter((v.get("checks") or {}).values()), {}).get("checks") or []
    rows = [["自由度", _n(cond.get("dof"), 0), _n(item.get("自由度", {}).get("value"), 0),
             _st(item.get("自由度", {}).get("status")), "concept-result.json · 初筛「自由度」"]]
    reach = next((x for k, x in item.items() if k.startswith("臂展点")), {})
    rows.append(["臂展（工具点在安装面上的最远水平距离）", f"{_n(cond.get('reach'), 1)} mm",
                 f"能到，位置误差 {_n(reach.get('value'))} mm", _st(reach.get("status")), "concept-result.json · 初筛「臂展点」"])
    rows.append(["末端负载", f"{_n(cond.get('payload'))} kg", "载荷、选件、仿真、有限元都按满载算", "—", "build-result.json · assumptions"])
    rp = b.get("repeatability") or {}
    rows.append(["末端重复定位精度", f"±{_n(cond.get('repeatability'))} mm",
                 f"编码器分辨率一项最坏 ±{_n(rp.get('worst_mm'), 2)} mm；反向趋近时回差再多 {_n(rp.get('backlash_lost_motion_mm'), 1)} mm",
                 _st(rp.get("status")) + "（同向趋近）", "build-result.json · repeatability"])
    s3 = _check(vchecks, "S3")
    rows.append(["关节最高角速度", f"{_n((cond.get('joint_speed') or 0) * 6, 0)}°/s（{_n(cond.get('joint_speed'), 1)} rpm）",
                 f"带载最紧一点能到 {_n(s3.get('limit'), 1)} rpm", _st(s3.get("status")), "verify-result.json · S3"])
    rows.append(["装在桌面上", "桌面", _n(None) if not item.get("安装方式") else item["安装方式"].get("value"),
                 _st(item.get("安装方式", {}).get("status")), "concept-result.json · 初筛「安装方式」"])
    reuse = item.get("关节模组复用", {})
    rows.append(["同一种关节模组重复使用", "是", f"{_n(reuse.get('value'), 0)} 个关节用同一型号", _st(reuse.get("status")),
                 "concept-result.json · 初筛「关节模组复用」"])
    rows.append(["学生能自己装拆", "—", "支架与模组全用 M2.5 螺钉；套管与杆件的连接还没设计", MISSING, "本报告第 6 节"])
    rows.append(["全部自制件能在普通数控车床、铣床上加工", "—", "支架、管件是板、管、圆角与孔；没有做工艺性的代码检查", MISSING, "本报告第 6 节"])
    cost = b.get("cost") or {}
    rows.append(["外购件成本尽量低", "—", cost.get("note") or MISSING, _st(cost.get("status")), "build-result.json · cost"])
    return rows


def report(res: Mapping, b: Mapping) -> str:
    c, cad = res["concept"], res["cad"]
    build = res.get("build") or {}
    v = res.get("verify") or {}
    fea = res.get("fea")
    L = ["# 案例 A：教学用桌面五轴机械臂——设计报告", "",
         ("本报告由 `python -m assist.robot_report` 从各步结果文件生成（ADR-0115 44.3）。括号或“来源”栏写的是数字出自哪个文件、哪一项；"
          "“待确认”表示结果里没有、或代码判不了，原因写在旁边或第 6 节。"), "", "## 需求原话", ""]
    L += ["> " + x for x in c["statement"].strip().splitlines()]
    L += ["", "AI 从原话里摘出的条件（每条带原话引用，代码核对过单位）：", ""]
    L += _table(["条件", "值", "单位", "原话"], [[q["what"], _n(q["value"], 3) if isinstance(q["value"], (int, float)) else q["value"],
                                                q["unit"], q["quote"]] for q in c.get("quotes") or []])
    if c.get("questions"):
        L += ["", "AI 提出的问题（本次没有人作答，按原话和默认假设做）：", ""] + [f"- {q}" for q in c["questions"]]

    L += ["", "## 1 整机方案", ""]
    for k, r in enumerate(c["rounds"], 1):
        for i, (cand, ev) in enumerate(zip(r["proposal"]["candidates"], r["evaluations"])):
            L.append(f"- 第 {k} 轮构型 {i}「{cand['name']}」：初筛 {_st(ev['overall'])}。AI 的理由：{cand.get('reason', '')}")
            bad = [x for x in ev["items"] if x["status"] not in ("pass", "not_applicable")]
            L += [f"  - 初筛 {_st(x['status'])}：{x['item']}（{x.get('note', '')}）" for x in bad]
        fb = [ln.strip() for ln in (r.get("feedback") or "").splitlines() if "[不通过]" in ln]
        if fb and k < len(c["rounds"]):
            L.append("  - 按这一轮选件、装配后没通过，交回 AI 改：")
            L += [f"    - {ln.replace('- [不通过] ', '')}" for ln in fb]
    ch = c["chosen"]
    L += ["", f"采用第 {c['chosen_round']} 轮构型 {c.get('chosen_candidate', 0)}。"
              + (c.get("chosen_note") or ""), ""]
    L += _table(["关节", "类型", "转轴", "行程 °", "父 → 子"], [[j["id"], j["type"], j["axis"], j.get("range_deg"),
                                                          f"{j['parent']} → {j['child']}"] for j in ch["joints"]])
    L.append("")
    L += _table(["杆件", "长度 mm", "截面 mm", "材料"], [[lk["id"], lk["length_mm"],
                                                   f"Ø{lk['section']['od_mm']} / Ø{lk['section']['id_mm']}" if lk.get("section") else MISSING,
                                                   lk.get("material")] for lk in ch["links"]])

    L += ["", "## 2 校核结论", "", "### 选件（复核多体动力学的载荷，verify-result.json · checks）", ""]
    for g, grp in (v.get("checks") or {}).items():
        comps = grp.get("component") or "、".join(((build.get("picks") or {}).get(g) or {}).get("components") or []) or MISSING
        L.append(f"模组组 {g}：{comps}，总结论 {_st(grp.get('overall'))}")
        L += [f"- {x['check']} {_st(x['status'])}：{x['message']}" for x in grp.get("checks") or []]
    picks = build.get("picks") or {}
    for g, p in picks.items():
        opts = p.get("options") or {}
        if opts:
            L += ["", f"并列方案（模组组 {g}，build-result.json · picks.{g}.options）："]
            L += [f"- {name}：{_st(o.get('overall'))}，装在臂上 {_n(o.get('module_mass_kg'))} kg/关节（{'、'.join(o.get('components') or [])}）"
                  for name, o in opts.items()]
    L += ["", "### 杆件强度（build-result.json · links）", ""]
    L += [f"- {x['item']}：{_st(x['status'])}；{x['note']}" for x in (build.get("links") or {}).get("items") or []]
    L += ["", "### 关节与支架装得下（build-result.json · fit）", ""]
    L += [f"- {x['joint']} {x['type']}：{_st(x['status'])}；{x['note']}" for x in (build.get("fit") or {}).get("joints") or []]
    L += ["", "### 三维装配（cad/cad-result.json）", "",
          (f"结论 {_st(cad.get('status'))}；干涉 {len(cad.get('interferences') or [])} 处；问题 {len(cad.get('problems') or [])} 条；"
           f"整机质量 {_n(cad.get('mass_kg'))} kg，重心 {cad.get('cog_mm')} mm。")]
    L += [f"- {x}" for x in cad.get("notes") or []]
    L += ["", "### 支架强度有限元（fea-result.json）", ""]
    if fea:
        L.append(f"结论 {_st(fea['status'])}；动载系数 {_n(fea.get('dynamic_factor'))}，要求安全系数 ≥ {_n(fea.get('required_safety'))}；"
                 "载荷取检验动作起点姿态（" + "、".join(f"{j} {_n(q, 1)}°" for j, q in (fea.get("pose_deg") or {}).items()) + "）。")
        L.append("")
        L += _table(["支架", "结论", "挑起 kg", "最大当量应力 MPa", "对屈服", "对弯曲疲劳", "说明"],
                    [[x["part"], _st(x["status"]), _n(x["load"]["mass_kg"]), _n(x.get("vm_max_mpa"), 2), _n(x.get("safety_yield"), 1),
                      _n(x.get("safety_fatigue"), 1), x.get("note") or ""] for x in fea["items"]])
    else:
        L.append(f"{MISSING}：没有 fea-result.json（支架有限元没跑）。")

    L += ["", "## 3 仿真数字与需求逐条对照", ""]
    L += _table(["需求", "要求", "结果", "结论", "来源"], requirement_rows(res))
    L += ["", "复核多体动力学（真实装配体）与选件时估算的关节力矩对照（verify-result.json · compare）：", ""]
    L += _table(["关节", "估算峰值 N·m", "复核峰值 N·m", "估算均方根 N·m", "复核均方根 N·m", "峰值变化"],
                [[x["joint"], _n(x["peak_est_nm"]), _n(x["peak_nm"]), _n(x.get("rms_est_nm")), _n(x.get("rms_nm")),
                  f"{x['change'] * 100:+.1f}%" if isinstance(x.get("change"), (int, float))
                  else ("—（两者都是 0）" if x["peak_nm"] == 0 and x["peak_est_nm"] == 0 else MISSING)] for x in v.get("compare") or []])
    smart = any(p.get("chain") == "smart" for p in (build.get("picks") or {}).values())
    L += ["", "检验动作与假设（build-result.json · assumptions）：", ""]
    L += [f"- {a}" + ("（其中供电与总线只对伺服链方案成立；本方案采用一体化关节模组）" if smart and "EtherCAT" in a else "")
          for a in build.get("assumptions") or []]

    L += ["", "## 4 三维模型与 BOM", "",
          "三维装配：`out/cad/assembly.step`（约 4 MB，不入库；`python -m assist.robot_case` 重新生成），各零件见 cad/cad-result.json · parts。",
          "BOM：`out/bom.json`、`out/bom.csv`。", ""]
    rows = [[r["component"], f"{r['vendor']} {r['model']}", r["qty"], _n(r["mass_kg_each"]), r["mass_source"]] for r in b["purchased"]]
    L += ["外购件：", ""] + _table(["零件库编号", "型号", "数量", "单件 kg", "质量出处"], rows)
    L += ["", "自制件：", ""] + _table(["图号", "名称", "材料", "质量 kg"],
                                     [[r["drawing_no"], r["name"], r["material"], _n(r["mass_kg"], 4)] for r in b["made"]])
    L += ["", "紧固件：", ""] + _table(["名称", "夹紧厚度 mm", "数量", "说明"],
                                     [[r["name"], f"{r['grip_mm']:g}", r["qty"], r["note"]] for r in b["fasteners"]])
    if b["not_listed"]:
        L += ["", "未列入："] + [f"- {s}" for s in b["not_listed"]]
    L += ["", (f"质量：外购件 {_n(b['purchased_mass_kg'])} kg + 自制件 {_n(b['made_mass_kg'])} kg = {_n(b['total_mass_kg'])} kg"
               f"（三维装配 {_n(b['assembly_mass_kg'])} kg）；紧固件{b['fastener_mass']}。")]

    L += thin_section(res)

    L += ["", "## 5 用时", ""]
    t = res.get("timing")
    if t:
        L.append(f"本机 {t.get('machine', MISSING)}，{t.get('date', '')}，AI {t.get('ai', MISSING)}。")
        L.append("")
        L += _table(["步骤", "谁做", "用时 s"], [[s["step"] + (f"（{s['note']}）" if s.get("note") else ""), s["who"], _n(s["seconds"], 1)]
                                                for s in t["steps"]])
        L += ["", f"合计 {_n(sum(s['seconds'] for s in t['steps']), 1)} s。要人确认的：需求条件（AI 摘的条件、AI 的问题）、采用哪个构型、最终结果入企业库。"]
    else:
        L.append(f"{MISSING}：没有 timing.json（用 `python -m assist.robot_case` 跑一遍才有）。")

    L += ["", "## 6 卡在哪里", ""] + [f"- {x}" for x in open_items(res, b)]
    return "\n".join(L) + "\n"


def thin_section(res: Mapping) -> list[str]:
    """支架减薄（第 9 步）：改前取 thin-result.json · before，改后取现在的 cad、fea、verify"""
    th = res.get("thin")
    if not th:
        return []
    before = th["before"]["parts"]
    cad = {p["name"]: p for p in res["cad"]["parts"]}
    fea = {x["part"]: x for x in (res.get("fea") or {}).get("items") or []}
    L = ["", "### 支架减薄（thin-result.json，ADR-0115 第 9 步）", "", f"规则：{th['rule']}。", ""]
    rows, saved = [], {True: 0.0, False: 0.0}
    for name, b0 in before.items():
        p, f = cad.get(name) or {}, fea.get(name) or {}
        if p.get("mass_kg") is not None:
            saved[b0["moving"]] += b0["mass_kg"] - p["mass_kg"]
        if b0.get("plate_mm") is None or p.get("plate_mm") == b0.get("plate_mm"):
            continue
        rows.append([name, f"{_n(b0['plate_mm'], 1)} → {_n(p.get('plate_mm'), 1)}", f"{_n(b0['mass_kg'], 4)} → {_n(p.get('mass_kg'), 4)}",
                     f"{_n(b0.get('safety_yield'), 1)} → {_n(f.get('safety_yield'), 1)}",
                     f"{_n(b0.get('safety_fatigue'), 1)} → {_n(f.get('safety_fatigue'), 1)}", _st(f.get("status"))])
    if rows:
        L += _table(["零件", "板厚 mm", "质量 kg", "对屈服", "对弯曲疲劳", "有限元"], rows)
    else:
        L.append("没有可以减的：每一级都没通过（见下面的试算记录）。")
    L += ["", (f"省下：跟着转的 {_n(saved[True], 4)} kg，固定不动的 {_n(saved[False], 4)} kg；"
               f"整机 {_n(th['before']['mass_kg'])} → {_n(res['cad'].get('mass_kg'))} kg。"), ""]
    after = {x["joint"]: x["peak_nm"] for x in (res.get("verify") or {}).get("compare") or []}
    L += ["关节峰值力矩（verify-result.json · compare，复核多体动力学）：", ""]
    L += _table(["关节", "减薄前 N·m", "减薄后 N·m"],
                [[j, _n(v), _n(after.get(j))] for j, v in th["before"]["peak_nm"].items()])
    L += ["", "试算记录：", ""] + _table(
        ["零件", "试的板厚", "对弯曲疲劳", "结果"],
        [[t["part"], f"{_n(t['from_mm'], 1)} → {_n(t['to_mm'], 1)} mm", _n(t.get("safety_fatigue"), 1),
          "接受" if t["accepted"] else f"不接受（{t.get('note') or _st(t.get('status'))}）"] for t in th["trials"]])
    L += ["", ("基座、舵盘法兰、壳体底座没减：法兰与壳体底座的 6 mm 由沉头孔深 3 mm 加压紧 3 mm 定，不是强度定的；"
               "基座底面在有限元里整面固定，桌面固定方式设计之前，底板和立板根部的真实受力算不出来。")]
    return L


def open_items(res: Mapping, b: Mapping) -> list[str]:
    """没判定、没设计、没数据的，如实列出（下一步的输入）"""
    build = res.get("build") or {}
    v = res.get("verify") or {}
    items = []
    for g, grp in (v.get("checks") or {}).items():
        items += [f"选件 {x['check']} 待确认（模组组 {g}）：{x['message']}" for x in grp.get("checks") or [] if x.get("status") == "unknown"]
    cost = build.get("cost") or {}
    if cost.get("status") != "pass":
        items.append(f"成本：{cost.get('note') or MISSING}")
    rp = build.get("repeatability") or {}
    if rp.get("backlash_lost_motion_mm"):
        items.append(f"重复定位精度只在同向趋近时满足；反向趋近时模组回差使末端再多走 {_n(rp['backlash_lost_motion_mm'], 1)} mm，"
                     "教学示教要求双向时需要换回差更小的模组或在控制上做单向趋近")
    items += [f"未列入 BOM：{s}" for s in b["not_listed"]]
    items.append("套管与杆件怎么连接（胶接、销或紧定螺钉）还没设计；基座怎么固定在桌面上还没设计")
    items.append(f"螺钉长度待定：{SCREW_LENGTH_NOTE.split('：', 1)[1]}")
    items.append("夹爪没有选型：末端只按 0.5 kg 负载和方案里的工具偏距算；夹爪自重不计（需求没说夹爪是否含在负载内，AI 也问了）")
    items.append("自制件工艺性（普通数控车铣能否加工、学生能否自己装拆）没有代码检查，现在靠设计规则（板、管、圆角、通孔）保证")
    fea = res.get("fea")
    if not fea:
        items.append("支架有限元没跑")
    elif fea["status"] != "pass":
        items += [f"支架有限元 {x['part']} {_st(x['status'])}：{x.get('note', '')}" for x in fea["items"] if x["status"] != "pass"]
    elif res.get("thin"):
        items.append("基座底板（120 × 120 mm）还没减：要等桌面固定方式设计好、按真实固定点算过有限元再定")
    else:
        lo = min(fea["items"], key=lambda x: x.get("safety_fatigue") or float("inf"))
        items.append(f"支架偏厚：最弱的 {lo['part']} 对弯曲疲劳 {_n(lo['safety_fatigue'], 1)}，其余富余更多；可让 AI 按有限元结果减薄（另行计划）")
    return items


def write(out_dir: str | Path) -> dict:
    d = Path(out_dir)
    res = load(d)
    for k in ("concept", "cad"):
        if k not in res:
            raise FileNotFoundError(f"缺 {FILES[k]}：先跑前面的步骤")
    b = bom(res)
    (d / "bom.json").write_text(json.dumps(b, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (d / "bom.csv").write_text(bom_csv(b), encoding="utf-8")
    (d / "report.md").write_text(report(res, b), encoding="utf-8")
    from assist import robot_compare

    robot_compare.write(d.parent, res, b)            # 案例目录有 reference.json 时出对照页（第 8 步）
    return b


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m assist.robot_report", description="整机案例的报告与 BOM（ADR-0115 44.3）")
    ap.add_argument("out_dir", type=Path, help="案例的 out/ 目录")
    a = ap.parse_args(argv)
    b = write(a.out_dir)
    print(f"BOM：外购件 {len(b['purchased'])} 项、自制件 {len(b['made'])} 件、螺钉 {sum(r['qty'] for r in b['fasteners'])} 个；"
          f"报告 {a.out_dir / 'report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
