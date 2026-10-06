# -*- coding: utf-8 -*-
"""热分析的 AI 解释（第 14 轮 H7）：规则先写，有模型时由模型改写（国内 DeepSeek，美国 Claude）。"""
import json
import re


def rules_explain(job):
    st, setup = job["stats"], job["setup"]
    f = setup.get("formula") or {}
    lines, actions = [], []
    tin, tout = st.get("heat_in_w", 0), st.get("heat_out_convection_w", 0)
    lines.append("最高温度 {:.1f} ℃，最低 {:.1f} ℃，表面平均 {:.1f} ℃。".format(st["t_max_c"], st["t_min_c"], st["t_surface_mean_c"]))
    if tin and not setup.get("transient"):
        lines.append("热平衡：进来 {:.1f} W，经对流散走 {:.1f} W{}。".format(tin, tout, "，两者相等，说明计算收敛" if abs(tin - tout) < 0.02 * tin
                                                                         else "，差的部分从固定温度的面流走"))
    groups = st.get("film_groups") or []
    tinf = next((l["t_inf_c"] for l in setup.get("thermal") or [] if l["type"] == "convection"), None)
    if groups and tinf is not None:
        g = max(groups, key=lambda x: x["heat_w"])
        lines.append("散热主要靠对流面：面积 {:.4f} m²，平均比环境高 {:.1f} ℃，散走 {:.1f} W。温升 ≈ 发热 ÷（散热系数 × 面积），"
                     "要降温就三条路：减少发热、加大散热面积（散热筋、散热片）、提高散热系数（风扇、改善通风）。".format(
                         g["area_m2"], g["mean_c"] - tinf, g["heat_w"]))
    lim = f.get("limit_c")
    if f.get("t_oil_c") is not None:
        lines.append("教材公式油温 {} ℃（K_s = {}、A = {} m²），有限元外表面平均 {:.1f} ℃：公式把整个箱体当成一个温度，有限元能看出底部、角落更热、上部更凉。".format(
            f["t_oil_c"], f["K_s"], f["A_m2"], groups[0]["mean_c"] if groups else st["t_surface_mean_c"]))
    if lim is not None:
        if st["t_max_c"] > lim:
            lines.append("最高温度超过限值约 {} ℃：".format(lim) + ("加散热筋（每侧 6–10 条，筋高 20–30 mm）或在输入轴端装风扇（散热系数从 17 提到 30 以上）再算。" if f.get("t_oil_c") is not None
                                                          else "装风扇（散热系数 50 以上）、加片数或片高再算。"))
            actions.append({"kind": "example", "label": "加 8 条散热筋重算" if f.get("t_oil_c") is not None else "片数加到 13 片重算",
                            "params": {"fins": 8} if f.get("t_oil_c") is not None else {"fins": 13}})
        else:
            lines.append("最高温度低于限值约 {} ℃，满足要求，还有 {:.0f} ℃ 余量。".format(lim, lim - st["t_max_c"]))
    if setup.get("analysis") == "thermo_mech":
        lines.append("热应力最大 {:.1f} MPa（安全系数 {}），热变形最大 {:.4g} mm。热应力来自膨胀受约束：约束越死、温差越大，热应力越大；能让零件自由伸长（一端游动支承、留膨胀间隙）就能大幅减小。".format(
            st.get("vm_max_mpa", 0), st.get("safety_factor", "—"), st.get("u_max_mm", 0)))
    if setup.get("transient") and st.get("series"):
        s = st["series"]
        lines.append("瞬态：{:.0f} 秒内平均温度从 {:.1f} ℃ 变到 {:.1f} ℃。".format(s[-1][0], s[0][2], s[-1][2]))
    return {"text": "\n".join(lines), "actions": actions, "engine": "rules"}


EXPLAIN_TOOL = {
    "name": "explain",
    "description": "解释温度场计算结果并给建议",
    "input_schema": {"type": "object", "required": ["text"], "properties": {
        "text": {"type": "string", "description": "3–6 句中文：最热在哪里、为什么（发热、散热面积、散热系数、导热路径）、和公式估算差在哪、是否超限、怎么改；不要编造没给的数字"}}},
}


def explain(llm, job):
    base = rules_explain(job)
    if llm is None or not llm.available():
        return base
    got = {}

    def call_tool(name, args):
        got.update(args)
        return {"ok": True}
    ctx = {"setup": {k: v for k, v in job["setup"].items() if k != "material"}, "stats": job["stats"], "rule_notes": base["text"]}
    try:
        llm.run("你是传热学和机械设计课的老师，给学生解释有限元温度场结果。只根据给出的数据；调用 explain 一次。",
                [{"role": "user", "content": json.dumps(ctx, ensure_ascii=False, default=str)[:12000]}], [EXPLAIN_TOOL], call_tool, max_turns=2)
    except Exception:  # noqa: BLE001
        return base
    if not got.get("text"):
        return base
    return {"text": got["text"].strip(), "actions": base["actions"], "engine": llm.name}


# ---------------------------------------------------------------- 一句话设置热边界（第 14 轮 H7）
NUM = r"(-?\d+(?:\.\d+)?)"
FILM_WORDS = [("水冷", "water", 1000.0), ("油", "oil", 100.0), ("强制风冷", "air-forced", 50.0), ("直吹", "air-forced", 50.0),
              ("1500", "fan-1500", 38.0), ("风扇", "fan-1000", 31.0), ("通风差", "air-still", 8.15), ("静止", "air-still", 8.15),
              ("自然", "air-vent", 17.45), ("通风", "air-vent", 17.45), ("空气", "air-vent", 17.45)]
GROUP_WORDS = [("inner", ("内壁", "箱内", "内表面", "内腔")), ("outer", ("外表面", "外壁", "外面")), ("bottom", ("底面", "底部", "机座")),
               ("pad", ("接触面", "贴合面", "CPU", "芯片", "发热面"))]
GROUP_NAME = {"inner": "箱内壁", "outer": "外表面", "bottom": "底面", "pad": "CPU 接触面"}
KIND_LABEL = {"temperature": "固定温度", "convection": "对流散热", "heat_flux": "面发热", "heat_body": "整体发热"}


def _num_unit(clause, unit_re):
    m = re.search(NUM + r"\s*(?:" + unit_re + ")", clause, re.I)
    return float(m.group(1)) if m else None


def _plane_faces(faces, solid, axis, sign):
    """零件最外侧、法向朝 ±axis 的平面（例如底面 = 朝 −Z 且在最低处）"""
    bb = (solid or {}).get("bbox_mm")
    if not bb:
        return []
    lim = bb[axis] if sign < 0 else bb[axis + 3]
    out = []
    for f in faces:
        n = f.get("normal") or [0, 0, 0]
        if f["kind"] == "plane" and n[axis] * sign > 0.999 and abs(f["center"][axis] - lim) < 1e-3:
            out.append(f["id"])
    return out


def _th_faces(clause, faces, solid, groups):
    c = clause.replace(" ", "")
    for g, words in GROUP_WORDS:
        if any(w.lower() in c.lower() for w in words) and (groups or {}).get(g):
            return list(groups[g]), GROUP_NAME[g]
    if any(w in c for w in ("底面", "底部")):
        return _plane_faces(faces, solid, 2, -1), "底面"
    if "顶面" in c or "上表面" in c:
        return _plane_faces(faces, solid, 2, 1), "顶面"
    from hub import cae_ai
    tags, _, proj = cae_ai.tag_faces(faces, solid)
    return cae_ai._faces_for(clause, faces, tags, proj), None


def rules_setup(text, faces, solid=None, groups=None):
    """规则理解一句话 → 热边界行。返回 {rows, material_id, transient, ref_temp_c, notes, unmatched}"""
    from hub import cae_ai
    rows, notes, unmatched = [], [], []
    out = {"material_id": cae_ai._material(text), "transient": None, "ref_temp_c": None}
    amb = None
    m = re.search(r"(?:环境|室温|气温|周围)[^，,；;。\d-]*" + NUM, text)
    if m:
        amb = float(m.group(1))
    m = re.search(r"(?:初温|初始温度|一开始)[^，,；;。\d-]*" + NUM, text)
    t0_all = float(m.group(1)) if m else None
    for clause in [x for x in re.split(r"[，,；;。\n]", text) if x.strip()]:
        c = clause.replace(" ", "")
        w = _num_unit(clause, r"k?W(?![/·])")
        if w is not None and re.search(r"\d\s*kW", clause, re.I):
            w *= 1000
        temp = _num_unit(clause, r"℃|°C|度")
        if re.search(r"瞬态|升温过程|随时间|冷却过程", c) or re.search(NUM + r"\s*(?:秒|分钟|min|小时)", clause):
            t = re.search(NUM + r"\s*(秒|分钟|min|小时)", clause)
            dur = float(t.group(1)) * {"秒": 1, "分钟": 60, "min": 60, "小时": 3600}[t.group(2)] if t else 600.0
            t0 = t0_all if t0_all is not None else (amb if amb is not None else 20.0)
            out["transient"] = {"duration_s": dur, "t0_c": t0}
            notes.append("“{}” → 瞬态 {:g} 秒，初温 {:g} ℃".format(clause.strip(), dur, out["transient"]["t0_c"]))
            continue
        if re.search(r"初温|初始温度|一开始", c) and not re.search(r"发热|功率|散热|对流", c):
            continue                                                    # 初温已在上面统一取
        if re.search(r"参考温度|装配温度|无应力", c) and temp is not None:
            out["ref_temp_c"] = temp
            notes.append("“{}” → 无应力参考温度 {:g} ℃".format(clause.strip(), temp))
            continue
        if re.search(r"(?:环境|室温|气温|周围)", c) and not re.search(r"散热|对流|冷却|风|发热|功率", c):
            continue                                                    # 只说了环境温度，用在对流行上
        kind = None
        if w is not None and re.search(r"整体|体积|内部均匀|均匀发热|线圈", c):
            kind = "heat_body"
        elif w is not None or re.search(r"发热|功率|损耗", c):
            kind = "heat_flux"
        elif re.search(r"对流|散热|冷却|风冷|风扇|通风|水冷|空气", c):
            kind = "convection"
        elif temp is not None and re.search(r"保持|恒温|固定|定温|温度为|温度是|贴着|维持", c):
            kind = "temperature"
        if kind is None:
            if not cae_ai._material(clause):
                unmatched.append(clause.strip())
            continue
        row = {"kind": kind, "faces": [], "rest": False}
        where = None
        if kind != "heat_body":
            if kind == "convection" and re.search(r"其余|其他|其它|剩下|别的|所有", c):
                row["rest"] = True
                where = "其余所有面"
            else:
                row["faces"], where = _th_faces(clause, faces, solid, groups)
                if not row["faces"]:
                    if kind == "convection":                            # 没说哪些面：默认其余所有面
                        row["rest"] = True
                        where = "其余所有面（没说哪些面，默认）"
                    else:
                        unmatched.append(clause.strip())
                        continue
        if kind in ("heat_flux", "heat_body"):
            if w is None:
                unmatched.append(clause.strip())
                continue
            row["value"] = w
        elif kind == "temperature":
            row["value"] = temp
        else:
            h = re.search(r"(?:h|散热系数|换热系数)\s*[=＝为是]?\s*" + NUM, clause, re.I) or re.search(NUM + r"\s*W\s*/", clause)
            film = next(((fid, hv) for word, fid, hv in FILM_WORDS if word in c), None)
            if h:
                row["h"], row["film"] = float(h.group(1)), ""
            elif film:
                row["film"], row["h"] = film
            else:
                row["film"], row["h"] = "air-vent", 17.45
            row["tinf"] = temp if temp is not None else (amb if amb is not None else 20.0)
        rows.append(row)
        desc = {"heat_flux": "{:g} W".format(row.get("value", 0)), "heat_body": "{:g} W".format(row.get("value", 0)),
                "temperature": "{:g} ℃".format(row.get("value", 0)),
                "convection": "h = {:g} W/(m²·K)，环境 {:g} ℃".format(row.get("h", 0), row.get("tinf", 0))}[kind]
        tgt = "" if kind == "heat_body" else "：" + (where if row["rest"] else
                                                        "面 " + "、".join(str(i) for i in row["faces"]) + ("（{}）".format(where) if where else ""))
        notes.append("“{}” → {} {}{}".format(clause.strip(), KIND_LABEL[kind], desc, tgt))
    if rows and not any(r["kind"] in ("temperature", "convection") for r in rows):
        rows.append({"kind": "convection", "faces": [], "rest": True, "film": "air-vent", "h": 17.45, "tinf": amb if amb is not None else 20.0})
        notes.append("没说怎么散热：其余所有面按自然对流（通风良好，h = 17.45）补上，否则热量散不出去")
    return dict(out, rows=rows, notes=notes, unmatched=unmatched)


SETUP_TOOL = {
    "name": "fill_thermal",
    "description": "把一句话变成温度场的热边界表（只填表，不计算）",
    "input_schema": {"type": "object", "required": ["rows"], "properties": {
        "material_id": {"type": "string"},
        "rows": {"type": "array", "items": {"type": "object", "required": ["kind"], "properties": {
            "kind": {"enum": list(KIND_LABEL), "description": "temperature 固定温度（value ℃）；convection 对流（h W/(m²·K)、tinf ℃）；heat_flux 面上总发热（value W）；heat_body 整体发热（value W，不用选面）"},
            "faces": {"type": "array", "items": {"type": "integer"}}, "rest": {"type": "boolean", "description": "对流用于其余所有面"},
            "value": {"type": "number"}, "h": {"type": "number"}, "tinf": {"type": "number"}}}},
        "transient": {"type": "object", "properties": {"duration_s": {"type": "number"}, "t0_c": {"type": "number"}}},
        "ref_temp_c": {"type": "number"}, "notes": {"type": "array", "items": {"type": "string"}},
        "unmatched": {"type": "array", "items": {"type": "string"}}}},
}


def setup(llm, text, faces, solid=None, groups=None):
    """先模型、后规则；返回里带 engine"""
    from cae import materials as M
    from hub import cae_ai
    text = (text or "").strip()[:500]
    if not text:
        raise ValueError("请写一句话描述哪里发热、怎么散热")
    if llm is not None and llm.available():
        got = {}

        def call_tool(name, args):
            got.update(args)
            return {"ok": True}
        try:
            tags, _, _ = cae_ai.tag_faces(faces, solid)
            system = ("你是传热学助手。根据零件面清单（编号、类型、标签、位置；groups 是已经按位置分好的面组）把一句话变成热边界表，"
                      "调用 fill_thermal 一次。散热系数参考：自然对流通风差 8.15、通风良好 17.45、风扇 31–38、强制风冷 50、油 100、水 1000 W/(m²·K)；"
                      "没说环境温度就用 20 ℃；至少要有一个固定温度或对流的行；不确定的写进 unmatched。材料库编号：{}。").format(
                "、".join("{}={}".format(m["id"], m["name"]) for m in M.MATERIALS))
            user = json.dumps({"sentence": text, "faces": cae_ai._face_brief(faces, tags), "groups": groups or {}}, ensure_ascii=False)
            llm.run(system, [{"role": "user", "content": user[:14000]}], [SETUP_TOOL], call_tool, max_turns=2)
            ids = {f["id"] for f in faces}
            rows = []
            for r in got.get("rows") or []:
                if r.get("kind") not in KIND_LABEL:
                    continue
                r = {k: r[k] for k in ("kind", "faces", "rest", "value", "h", "tinf") if k in r}
                r["faces"] = [i for i in r.get("faces") or [] if i in ids]
                r["rest"] = bool(r.get("rest"))
                if r["kind"] == "heat_body" or r["faces"] or r["rest"]:
                    r.setdefault("film", "")
                    rows.append(r)
            if rows:
                mid = got.get("material_id") if got.get("material_id") in M.BY_ID else None
                return {"rows": rows, "material_id": mid, "transient": got.get("transient"), "ref_temp_c": got.get("ref_temp_c"),
                        "notes": got.get("notes") or [], "unmatched": got.get("unmatched") or [], "engine": llm.name}
        except Exception as e:  # noqa: BLE001
            return dict(rules_setup(text, faces, solid, groups), engine="rules", note="模型暂时不可用（{}），已用规则理解".format(str(e)[:60]))
    return dict(rules_setup(text, faces, solid, groups), engine="rules")
