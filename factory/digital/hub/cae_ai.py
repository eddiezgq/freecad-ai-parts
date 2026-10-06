# -*- coding: utf-8 -*-
"""仿真与分析的 AI（第 11 轮 F3、F7）：
1. 一句话设置：“左端面固定，键槽侧面加 350 N·m 扭矩，45 钢调质” → 选面、填好约束与载荷表，给人确认后才计算。
   有模型时由模型（国内 DeepSeek，美国 Claude）理解；没配模型或出错时用规则兜底（端面 / 圆柱面 / 键槽面 / 孔 / 面编号）。
2. 结果解释：最危险在哪、为什么、怎么改；建议可一键执行（换材料重算、到设计台改尺寸）。
AI 只填设置、写解释，不直接出数字结果；计算一律由求解器做。
"""
import json
import re

import numpy as np

from cae import materials as M

KINDS = ("fixed", "bearing", "coupling", "force", "pressure", "torque")


# ---------------------------------------------------------------- 面的“名字”
def _unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n else v


def main_axis(faces, solid=None):
    """零件主轴：面积最大的圆柱面的轴线；没有圆柱面时取外形最长的方向"""
    cyl = sorted([f for f in faces if f["kind"] == "cylinder" and f.get("axis") and f.get("axis_origin")],
                 key=lambda f: -f["area_mm2"])
    if cyl:
        return np.asarray(cyl[0]["axis_origin"], float), _unit(cyl[0]["axis"]), True
    bb = (solid or {}).get("bbox_mm")
    if not bb:
        pts = np.array([f["center"] for f in faces])
        lo, hi = pts.min(0), pts.max(0)
    else:
        lo, hi = np.array(bb[:3]), np.array(bb[3:])
    d = np.zeros(3)
    d[int(np.argmax(hi - lo))] = 1
    return (lo + hi) / 2, d, False


def tag_faces(faces, solid=None):
    """给每个面起人能听懂的名字（规则和模型都用）。返回 {id: [标签…]}，和 (原点, 轴向, 是否回转体)"""
    o, d, rot = main_axis(faces, solid)
    proj = {f["id"]: float(np.dot(np.asarray(f["center"]) - o, d)) for f in faces}
    lo, hi = min(proj.values()), max(proj.values())
    span = max(hi - lo, 1e-6)
    outer_r = max([f.get("radius_mm") or 0 for f in faces if f["kind"] == "cylinder"] + [0])
    tags = {}
    for f in faces:
        t = []
        c = np.asarray(f["center"], float)
        n = _unit(f.get("normal") or [0, 0, 0])
        side = "左" if proj[f["id"]] < lo + 0.5 * span else "右"
        if f["kind"] == "plane":
            along = abs(float(np.dot(n, d)))
            if along > 0.99:
                if abs(proj[f["id"]] - lo) < 1e-3 * span + 1e-6:
                    t += ["左端面", "端面"]
                elif abs(proj[f["id"]] - hi) < 1e-3 * span + 1e-6:
                    t += ["右端面", "端面"]
                else:
                    t += ["轴肩面" if rot else "台阶面", side + "侧台阶"]
            elif along < 0.01 and rot:
                rv = (c - o) - d * np.dot(c - o, d)
                rr = np.linalg.norm(rv)
                if rr < outer_r - 1e-3:                          # 在外圆以内的轴向平面：键槽
                    if rr > 1e-6 and abs(float(np.dot(n, rv / rr))) > 0.99:
                        t += ["键槽底面", "键槽"]
                    else:
                        t += ["键槽侧面", "键槽"]
                else:
                    t += ["铣扁面"]
            if not rot:
                ax = int(np.argmax(np.abs(n)))
                t += ["{}{}面".format("+" if n[ax] > 0 else "-", "XYZ"[ax])]
        elif f["kind"] == "cylinder" and f.get("axis"):
            a = _unit(f["axis"])
            dia = 2 * (f.get("radius_mm") or 0)
            if abs(float(np.dot(a, d))) > 0.99:
                # 外圆还是孔：外表面法向背离轴线
                ao = np.asarray(f.get("axis_origin") or o, float)
                rv = (c - ao) - a * np.dot(c - ao, a)
                concave = np.linalg.norm(rv) > 1e-6 and float(np.dot(n, rv)) < 0 and f.get("normal")
                name = "孔" if concave else "外圆"
                t += [name, "{} Ø{:g}".format(name, round(dia, 2)), "圆柱面", side + "端" + name]
            else:
                t += ["键槽端部圆弧" if dia < outer_r else "横向圆柱面", "圆柱面"]
        elif f["kind"] == "cone":
            t += ["倒角"]
        else:
            t += ["曲面"]
        tags[f["id"]] = t
    # 同直径外圆的左右：同一直径有多个时，按轴向位置排“左边那个 / 右边那个”
    by_d = {}
    for f in faces:
        if "外圆" in tags[f["id"]]:
            by_d.setdefault(round(2 * f["radius_mm"], 2), []).append(f["id"])
    for dia, ids in by_d.items():
        ids.sort(key=lambda i: proj[i])
        if len(ids) > 1:
            tags[ids[0]].append("最左的 Ø{:g}".format(dia))
            tags[ids[-1]].append("最右的 Ø{:g}".format(dia))
    ext = [f["id"] for f in faces if "外圆" in tags[f["id"]]]
    if ext:
        tags[min(ext, key=lambda i: proj[i])].append("左端轴伸")
        tags[max(ext, key=lambda i: proj[i])].append("右端轴伸")
    return tags, (o, d, rot), proj


# ---------------------------------------------------------------- 规则兜底
MAT_WORDS = [("20CrMnTi", "20CrMnTi-CQ"), ("40Cr", "40Cr-QT"), ("45", "45-QT"), ("Q235", "Q235"), ("Q345", "Q345"),
             ("Q355", "Q345"), ("HT200", "HT200"), ("灰铸铁", "HT200"), ("QT500", "QT500-7"), ("球墨", "QT500-7"),
             ("6061", "6061-T6"), ("7075", "7075-T6"), ("304", "304"), ("不锈钢", "304"), ("ABS", "ABS"),
             ("PA66", "PA66"), ("尼龙", "PA66")]
NUM = r"(-?\d+(?:\.\d+)?)"


def _material(text):
    t = text.replace(" ", "")
    for w, mid in MAT_WORDS:
        if w.lower() in t.lower():
            return mid
    return None


def _faces_for(clause, faces, tags, proj):
    """一句里说的是哪些面"""
    c = clause.replace(" ", "")
    ids = [int(x) for x in re.findall(r"面\s*(\d+)", clause) + re.findall(r"(\d+)\s*号面", clause)]
    ids = [i for i in ids if i in tags]
    if ids:
        return ids
    dia = re.search(r"[Øøφ∅Φ]\s*" + NUM + r"|直径\s*" + NUM, clause)
    dia = float(dia.group(1) or dia.group(2)) if dia else None
    want_left, want_right = "左" in c, "右" in c
    both = "两" in c or "各" in c or "所有" in c

    def pick(cands):
        if not cands:
            return []
        if both or len(cands) == 1:
            return cands
        if want_left and not want_right:
            return [min(cands, key=lambda i: proj[i])]
        if want_right and not want_left:
            return [max(cands, key=lambda i: proj[i])]
        return cands

    def has(i, *words):
        return any(w in tags[i] for w in words)
    if "端面" in c:
        if "左" in c and not want_right:
            return [i for i in tags if has(i, "左端面")]
        if "右" in c and not want_left:
            return [i for i in tags if has(i, "右端面")]
        return [i for i in tags if has(i, "端面")]
    if "键槽" in c:
        if "底" in c:
            return [i for i in tags if has(i, "键槽底面")]
        if "侧" in c or "壁" in c:
            walls = sorted([i for i in tags if has(i, "键槽侧面")])
            return walls[:1] if ("一侧" in c or "侧面" in c) and not both else walls
        return [i for i in tags if has(i, "键槽")]
    if "孔" in c:
        cands = [i for i in tags if has(i, "孔")]
        if dia:
            cands = [i for i in cands if abs(2 * (next(f for f in faces if f["id"] == i).get("radius_mm") or 0) - dia) < 0.05]
        return pick(cands)
    if any(w in c for w in ("圆柱", "外圆", "轴承", "轴伸", "轴颈", "Ø", "ø", "φ", "直径", "联轴器")):
        cands = [i for i in tags if has(i, "外圆")]
        if dia:
            cands = [i for i in cands if abs(2 * (next(f for f in faces if f["id"] == i).get("radius_mm") or 0) - dia) < 0.05]
        elif "轴伸" in c and (want_left or want_right):
            return [i for i in tags if has(i, "右端轴伸" if want_right else "左端轴伸")]
        return pick(cands)
    m = re.search(r"([+-]?)([XYZxyz])\s*(?:向|方向)?面", clause)
    if m:
        name = "{}{}面".format(m.group(1) or "+", m.group(2).upper())
        return [i for i in tags if name in tags[i]]
    return []


def _direction(clause, axis_d):
    c = clause.replace(" ", "")
    m = re.search(r"([+-])\s*([XYZxyz])", clause) or re.search(r"([XYZxyz])\s*(正|负)", clause)
    if m:
        if m.group(1) in "+-":
            sgn, ax = (1 if m.group(1) == "+" else -1), m.group(2)
        else:
            sgn, ax = (1 if m.group(2) == "正" else -1), m.group(1)
        v = [0, 0, 0]
        v["xyz".index(ax.lower())] = sgn
        return v
    if "向下" in c or "竖直" in c or "垂直向下" in c or "重力" in c:
        return [0, -1, 0]
    if "向上" in c:
        return [0, 1, 0]
    if "轴向" in c:
        return list(axis_d)
    return [0, -1, 0]


def rules_setup(text, faces, solid=None):
    """规则理解一句话。返回 {rows, material_id, notes, unmatched}"""
    tags, (o, d, rot), proj = tag_faces(faces, solid)
    rows, notes, unmatched = [], [], []
    mat = _material(text)
    for clause in [x for x in re.split(r"[，,；;。\n]|\s+并且\s+", text) if x.strip()]:
        c = clause.replace(" ", "")
        kind = None
        if re.search(r"扭矩|转矩|力矩", c):
            kind = "torque"
        elif re.search(r"压力|压强|MPa|N/mm", c, re.I) and not re.search(r"固定|支承|支撑", c):
            kind = "pressure"
        elif re.search(NUM + r"\s*k?N(?![·.\s]*m)", clause) or "的力" in c or "加力" in c or "受力" in c:
            kind = "force"
        elif "限制转动" in c or "不能转" in c or "联轴器" in c or "止转" in c:
            kind = "coupling"
        elif re.search(r"轴承|支承|支撑|铰支", c):
            kind = "bearing"
        elif re.search(r"固定|夹紧|焊死|约束", c):
            kind = "fixed"
        if kind is None:
            if not _material(clause):
                unmatched.append(clause.strip())
            continue
        ids = _faces_for(clause, faces, tags, proj)
        if not ids:
            unmatched.append(clause.strip())
            continue
        row = {"kind": kind, "faces": ids}
        if kind == "torque":
            m = re.search(NUM + r"\s*(k?)\s*N\s*[·.\*]?\s*m", clause, re.I) or re.search(NUM, clause)
            v = float(m.group(1)) if m else 0
            if m and m.lastindex and m.lastindex >= 2 and m.group(2).lower() == "k":
                v *= 1000
            row["value"] = v
        elif kind == "pressure":
            m = re.search(NUM, clause)
            row["value"] = float(m.group(1)) if m else 0
        elif kind == "force":
            m = re.search(NUM + r"\s*(k?)N", clause, re.I)
            v = float(m.group(1)) * (1000 if m and m.group(2).lower() == "k" else 1) if m else 0
            dv = _direction(clause, d)
            row.update(fx=v * dv[0], fy=v * dv[1], fz=v * dv[2])
        elif kind == "bearing" and "止推" in c and len(ids) > 1:
            # “两个 Ø35 轴承位支承，左边那个止推”：止推放在指定的一边，其余只限径向
            first = min(ids, key=lambda i: proj[i]) if "右" not in c else max(ids, key=lambda i: proj[i])
            rows.append({"kind": "bearing", "faces": [first], "thrust": True})
            notes.append("“{}” → 轴承支承兼止推：面 {}（{}）".format(clause.strip(), first, tags[first][1] if len(tags[first]) > 1 else tags[first][0]))
            row = {"kind": "bearing", "faces": [i for i in ids if i != first], "thrust": False}
        elif kind == "bearing":
            row["thrust"] = "止推" in c
        rows.append(row)
        notes.append("“{}” → {}：{}".format(clause.strip(), {"fixed": "固定", "bearing": "轴承支承", "coupling": "限制转动",
                                                          "force": "力", "pressure": "压力", "torque": "扭矩"}[kind],
                                             "、".join("面 {}（{}）".format(i, tags[i][1] if tags[i][0] in ("外圆", "孔") else tags[i][0]) for i in row["faces"])))
    # 有轴承又没有止推：第一个轴承兼止推，否则零件会沿轴向滑走
    brg = [r for r in rows if r["kind"] == "bearing"]
    if brg and not any(r.get("thrust") for r in brg) and not any(r["kind"] == "fixed" for r in rows):
        brg[0]["thrust"] = True
        notes.append("轴承都没说止推：第一个轴承同时限制轴向，否则零件会沿轴向滑走")
    return {"rows": rows, "material_id": mat, "notes": notes, "unmatched": unmatched}


# ---------------------------------------------------------------- 模型
SETUP_TOOL = {
    "name": "fill_setup",
    "description": "把用户的一句话变成有限元设置表（只填表，不计算）",
    "input_schema": {"type": "object", "required": ["rows"], "properties": {
        "material_id": {"type": "string", "description": "材料库编号，没说就不填"},
        "rows": {"type": "array", "items": {"type": "object", "required": ["kind", "faces"], "properties": {
            "kind": {"enum": list(KINDS), "description": "fixed 固定；bearing 轴承支承（圆柱面，限径向）；coupling 限制转动（圆柱面）；force 力；pressure 压力；torque 扭矩"},
            "faces": {"type": "array", "items": {"type": "integer"}},
            "value": {"type": "number", "description": "torque: N·m；pressure: MPa"},
            "fx": {"type": "number"}, "fy": {"type": "number"}, "fz": {"type": "number"},
            "thrust": {"type": "boolean", "description": "bearing 是否兼作止推（限制轴向）"}}}},
        "notes": {"type": "array", "items": {"type": "string"}, "description": "每条说明一句话怎么理解的、选了哪些面"},
        "unmatched": {"type": "array", "items": {"type": "string"}, "description": "没看懂或找不到面的部分"}}},
}


def _face_brief(faces, tags):
    out = []
    for f in faces:
        x = {"id": f["id"], "kind": f["kind"], "tags": tags[f["id"]], "area_mm2": f["area_mm2"],
             "center": f["center"]}
        if f.get("radius_mm"):
            x["diameter_mm"] = round(2 * f["radius_mm"], 3)
        if f.get("normal") and f["kind"] == "plane":
            x["normal"] = f["normal"]
        out.append(x)
    return out


def llm_setup(llm, text, faces, solid=None):
    tags, (o, d, rot), _ = tag_faces(faces, solid)
    got = {}

    def call_tool(name, args):
        got.update(args)
        return {"ok": True}
    system = ("你是机械工程师的有限元助手。根据零件的面清单（每个面有编号、类型、标签、尺寸、位置）把用户的一句话变成约束与载荷表，"
              "调用 fill_setup 一次。规则：轴承支承、限制转动只能用圆柱面；扭矩单位 N·m，压力 MPa，力 N（fx/fy/fz 分量，"
              "向下 = -y）；“左/右”指沿零件主轴 {} 坐标小/大的一端；有轴承时至少一个要止推；不确定的写进 unmatched，不要猜。"
              "材料库编号：{}。").format(
        [round(float(x), 3) for x in d], "、".join("{}={}".format(m["id"], m["name"]) for m in M.MATERIALS))
    user = json.dumps({"sentence": text, "faces": _face_brief(faces, tags)}, ensure_ascii=False)
    llm.run(system, [{"role": "user", "content": user}], [SETUP_TOOL], call_tool, max_turns=2)
    if not got.get("rows"):
        raise ValueError("模型没有给出设置")
    ids = {f["id"] for f in faces}
    rows = []
    for r in got["rows"]:
        if r.get("kind") in KINDS and r.get("faces") and set(r["faces"]) <= ids:
            rows.append({k: r[k] for k in ("kind", "faces", "value", "fx", "fy", "fz", "thrust") if k in r})
    mid = got.get("material_id") if got.get("material_id") in M.BY_ID else None
    return {"rows": rows, "material_id": mid, "notes": got.get("notes") or [], "unmatched": got.get("unmatched") or []}


def setup(llm, text, faces, solid=None):
    """先模型、后规则；返回里带 engine"""
    text = (text or "").strip()[:500]
    if not text:
        raise ValueError("请写一句话描述怎么约束、加什么载荷")
    if llm is not None and llm.available():
        try:
            r = llm_setup(llm, text, faces, solid)
            if r["rows"]:
                return dict(r, engine=llm.name)
        except Exception as e:  # noqa: BLE001 —— 模型出错就用规则
            r = rules_setup(text, faces, solid)
            return dict(r, engine="rules", note="模型暂时不可用（{}），已用规则理解".format(str(e)[:60]))
    return dict(rules_setup(text, faces, solid), engine="rules")


# ---------------------------------------------------------------- 结果解释
def stronger(mid):
    order = ["Q235", "45-QT", "40Cr-QT", "20CrMnTi-CQ"]
    if mid in order and order.index(mid) < len(order) - 1:
        return order[order.index(mid) + 1]
    if mid in ("6061-T6",):
        return "7075-T6"
    if mid in ("ABS",):
        return "PA66"
    if mid in ("HT200",):
        return "QT500-7"
    return None


def design_suggestion(job, params):
    """SH-301：键槽所在轴段加粗一档（键按 GB/T 1095 重选），给设计台用"""
    if job.get("item") != "SH-301" or not params or not params.get("keyway"):
        return None
    from hub import design as D
    p = json.loads(json.dumps(params))
    i = p["keyway"]["segment"]
    d0 = p["segments"][i][0]
    d1 = min(d0 + 4, D.LIMITS["d"][1])
    if d1 <= d0:
        return None
    p["segments"][i][0] = d1
    rec = D.gbt1095(d1)
    if rec:
        p["keyway"]["b"], p["keyway"]["t"] = float(rec["b"]), float(rec["t"])
    if not D.check(D.normalize(p))["ok"]:
        return None
    return {"kind": "design", "item": "SH-301", "params": p,
            "label": "到设计台试：键槽轴段 Ø{:g} → Ø{:g}（键 {:g}×{:g}，GB/T 1095）".format(d0, d1, p["keyway"]["b"], p["keyway"]["t"]),
            "note": "仿真建议：键槽轴段 Ø{:g} → Ø{:g}".format(d0, d1)}


def rules_explain(job, faces=None, params=None):
    st = job["stats"]
    mat = M.get(job["setup"]["material_id"])
    tags = tag_faces(faces)[0] if faces else {}
    where = "、".join("面 {}（{}）".format(i, (tags.get(i) or ["—"])[0]) for i in st.get("vm_max_faces") or []) or "零件内部"
    sf = st.get("safety_factor")
    lines = ["最危险的位置在{}，Von Mises 应力 {:.0f} MPa，安全系数 {:.2f}（{} {} MPa）。".format(
        where, st["vm_max_mpa"], sf or 0, mat["strength_kind"], mat["strength_mpa"])]
    sharp = any(any(k in (tags.get(i) or []) for k in ("键槽底面", "键槽侧面", "轴肩面", "台阶面")) for i in st.get("vm_max_faces") or [])
    if sharp:
        lines.append("这里是两个面相交的内角（尖角）：载荷在这里拐弯，应力集中；模型里没有圆角，算出的峰值会随网格加密继续变大，"
                     "要看趋势而不是只看这个数。实际零件的键槽底有 0.25–0.4 mm 圆角（GB/T 1095），轴肩应按标准加过渡圆角。")
    if st.get("vm_peak_all_mpa", 0) > st["vm_max_mpa"] * 1.01:
        lines.append("约束面附近还有 {:.0f} MPa 的局部高值，是“完全固定”这种理想约束造成的，评估时已避开。".format(st["vm_peak_all_mpa"]))
    fat = job.get("fatigue")
    if fat:
        lines.append("疲劳：" + ("这个载荷谱下无限寿命。" if fat.get("infinite") else "按这个载荷谱约 {:.3g} 小时出现疲劳裂纹；起动冲击那几个大循环贡献了大部分损伤。".format(fat["life_hours"])))
    actions = []
    if sf is not None and sf < 1.5:
        lines.append("改进方向：① 降低这里的应力——加大该处轴径、按标准加圆角，或改用花键传扭；② 提高材料强度；③ 减小载荷或起动冲击（软起动）。")
        nm = stronger(mat["id"])
        if nm:
            actions.append({"kind": "material", "material_id": nm, "label": "换成 {} 重算".format(M.BY_ID[nm]["name"])})
        ds = design_suggestion(job, params)
        if ds:
            actions.append(ds)
    else:
        lines.append("静强度裕量足够；若零件承受反复载荷，再做疲劳校核。")
    return {"text": "\n".join(lines), "actions": actions, "engine": "rules"}


EXPLAIN_TOOL = {
    "name": "explain",
    "description": "给出结果解释和可执行的建议",
    "input_schema": {"type": "object", "required": ["text"], "properties": {
        "text": {"type": "string", "description": "3–6 句中文：最危险在哪、为什么、数字说明什么、怎么改；不要编造没有给出的数字"},
        "material_id": {"type": "string", "description": "如果建议换材料，填材料库编号"},
        "design_change": {"type": "boolean", "description": "是否建议加大键槽轴段直径（仅 SH-301）"}}},
}


def explain(llm, job, faces=None, params=None):
    base = rules_explain(job, faces, params)
    if llm is None or not llm.available():
        return base
    tags = tag_faces(faces)[0] if faces else {}
    got = {}

    def call_tool(name, args):
        got.update(args)
        return {"ok": True}
    mat = M.get(job["setup"]["material_id"])
    ctx = {"part": job.get("item") or "上传的零件", "material": {k: mat[k] for k in ("id", "name", "yield_mpa", "ultimate_mpa", "sigma_1")},
           "setup": job["setup"]["loads"], "stats": job["stats"], "fatigue": job.get("fatigue"),
           "hot_faces": {i: tags.get(i) for i in job["stats"].get("vm_max_faces") or []},
           "design_params": params if job.get("item") == "SH-301" else None,
           "rule_notes": base["text"]}
    system = ("你是机械设计老师，给学生解释有限元和疲劳计算结果。只根据给出的数据，讲清楚最危险的位置、原因（应力集中、尖角奇异、约束影响等）、"
              "安全系数和寿命意味着什么、怎么改进。调用 explain 一次。可选材料：{}。").format(
        "、".join("{}={}".format(m["id"], m["name"]) for m in M.MATERIALS))
    try:
        llm.run(system, [{"role": "user", "content": json.dumps(ctx, ensure_ascii=False, default=str)}], [EXPLAIN_TOOL], call_tool, max_turns=2)
    except Exception:  # noqa: BLE001
        return base
    if not got.get("text"):
        return base
    actions = []
    if got.get("material_id") in M.BY_ID and got["material_id"] != mat["id"]:
        actions.append({"kind": "material", "material_id": got["material_id"], "label": "换成 {} 重算".format(M.BY_ID[got["material_id"]]["name"])})
    if got.get("design_change"):
        ds = design_suggestion(job, params)
        if ds:
            actions.append(ds)
    return {"text": got["text"].strip(), "actions": actions or base["actions"], "engine": llm.name}
