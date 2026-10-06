# -*- coding: utf-8 -*-
"""流体分析的 AI（第 16 轮）：一句话填表（规则先解析，有模型时补全——国内 DeepSeek，美国 Claude），结果解释（规则先写，有模型时改写）。
AI 只填表、只解释，不替学生点“开始计算”。"""
import json
import re

DIR_WORDS = [
    (r"(沿|顺着?)?\s*长边|长度方向", "long"), (r"(沿|顺着?)?\s*短边|宽度方向", "short"),
    (r"从下往上|向上吹|自下而上|\+\s*z", "+z"), (r"从上往下|向下吹|自上而下|-\s*z|−\s*z", "-z"),
    (r"从左往右|\+\s*x", "+x"), (r"从右往左|-\s*x|−\s*x", "-x"),
    (r"从前往后|\+\s*y", "+y"), (r"从后往前|-\s*y|−\s*y", "-y"),
]


def _num(pat, s):
    m = re.search(pat, s)
    return float(m.group(1)) if m else None


def rules_setup(text, bbox=None):
    """一句话 → 表单。返回 {form, notes, unmatched}"""
    s = (text or "").replace("，", ",").replace("。", ",").replace("°C", "℃").replace("度", "℃")
    form, notes, used = {}, [], []

    def take(m, note):
        used.append(m.span())
        notes.append(note)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(m/s|米每秒|米/秒|m/ s)", s)
    if m:
        form["velocity_ms"] = float(m.group(1)); take(m, "风速 {} m/s".format(form["velocity_ms"]))
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(km/h|公里每小时)", s)
        if m:
            form["velocity_ms"] = round(float(m.group(1)) / 3.6, 2); take(m, "风速 {} km/h = {} m/s".format(m.group(1), form["velocity_ms"]))
    m = re.search(r"(空气|气温|环境|室温|来流)[^,\d]{0,4}(-?\d+(?:\.\d+)?)\s*℃", s)
    if m:
        form["air_t_c"] = float(m.group(2)); take(m, "空气 {} ℃".format(form["air_t_c"]))
    m = re.search(r"(表面|壁面|外壳|箱体|零件|散热器|壳体)[^,\d]{0,6}(-?\d+(?:\.\d+)?)\s*℃", s)
    if m:
        form["wall_t_c"] = float(m.group(2)); form["heat"] = True; take(m, "表面 {} ℃，算散热系数".format(form["wall_t_c"]))
    if re.search(r"不(算|要|用)?(换热|散热|温度)|只(算|看)(阻力|流场)", s):
        form["heat"] = False; notes.append("只算流场和阻力，不算换热")
    elif re.search(r"散热|换热|冷却|h\b", s) and "heat" not in form:
        form["heat"] = True; notes.append("算散热系数")
    if re.search(r"(放|装|固定)在?(地面|地上|机座|底座|桌面|底板)|落地", s):
        form["ground"] = True; notes.append("放在地面 / 机座上，底面不吹风")
    elif re.search(r"悬空|吊着|自由来流", s):
        form["ground"] = False; notes.append("悬空，四面来风")
    for pat, d in DIR_WORDS:
        m = re.search(pat, s)
        if not m:
            continue
        if d in ("long", "short"):
            if not bbox:
                continue
            L = [bbox[3] - bbox[0], bbox[4] - bbox[1]]
            ax = "xy"[(L.index(max(L)) if d == "long" else L.index(min(L)))]
            form["direction"] = "+" + ax
            take(m, "风沿{}吹 → +{}".format("长边" if d == "long" else "短边", ax.upper()))
        else:
            form["direction"] = d; take(m, "来流方向 {}".format(d))
        break
    rest = s
    for a, b in sorted(used, reverse=True):
        rest = rest[:a] + " " * (b - a) + rest[b:]
    unmatched = [x.strip() for x in re.split(r"[,;；、\s]+", rest) if len(x.strip()) >= 2 and re.search(r"\d", x)]
    return {"form": form, "notes": notes, "unmatched": unmatched[:5], "engine": "rules"}


SETUP_TOOL = {
    "name": "fill", "description": "把老师/学生的一句话填进流体分析表单（只填说到的项）",
    "input_schema": {"type": "object", "properties": {
        "velocity_ms": {"type": "number"}, "direction": {"type": "string", "enum": ["+x", "-x", "+y", "-y", "+z", "-z"]},
        "air_t_c": {"type": "number"}, "heat": {"type": "boolean"}, "wall_t_c": {"type": "number"}, "ground": {"type": "boolean"},
        "notes": {"type": "array", "items": {"type": "string"}, "description": "每填一项写一句中文说明"}}},
}


def setup(llm, text, bbox=None):
    base = rules_setup(text, bbox)
    if llm is None or not llm.available() or not base["unmatched"] and base["form"]:
        return base
    got = {}

    def call_tool(name, args):
        got.update(args)
        return {"ok": True}
    try:
        llm.run("你帮学生设置流体分析（虚拟风洞）。零件外形包围盒 mm：{}（x0,y0,z0,x1,y1,z1）。只填用户说到的项；调用 fill 一次。".format(bbox),
                [{"role": "user", "content": text[:300]}], [SETUP_TOOL], call_tool, max_turns=2)
    except Exception:  # noqa: BLE001
        return base
    form = {k: got[k] for k in ("velocity_ms", "direction", "air_t_c", "heat", "wall_t_c", "ground") if k in got}
    if not form:
        return base
    form = {**base["form"], **form}
    return {"form": form, "notes": got.get("notes") or base["notes"], "unmatched": [], "engine": llm.name}


def rules_explain(st, faces):
    lines = []
    lam = st.get("turbulence") == "laminar"
    lines.append("风速 {} m/s 沿 {}，按零件长度 {} mm 算雷诺数 Re ≈ {:.0f}，{}。".format(
        st["velocity_ms"], st["direction"], st["L_char_mm"], st["Re"],
        "很小，整个流场按层流算" if lam else "按湍流算（k-ω SST 湍流模型、壁面函数）：零件是钝体，前缘一分离流动就乱了，风扇吹出的风本身也有湍流"))
    dp, df = st.get("drag_pressure_n") or 0, st.get("drag_friction_n") or 0
    lines.append("阻力 {:.3f} N，其中压差阻力 {:.3f} N、摩擦阻力 {:.3f} N——{}；阻力系数 C_d ≈ {:.2f}（按迎风面积 {:.0f} cm²、动压 {:.1f} Pa）。".format(
        st["drag_n"], dp, df, ("钝体以压差阻力为主：迎风面正压、背风面负压（尾流）" + ("；摩擦阻力接近零甚至为负，是因为侧面分离后有回流、局部摩擦力朝前" if df < 0.02 * abs(dp) else ""))
        if abs(dp) > 3 * abs(df) else "细长体摩擦阻力占比大",
        st.get("Cd") or 0, (st.get("frontal_m2") or 0) * 1e4, st.get("q_dyn_pa") or 0))
    if st.get("heat_w") is not None:
        big = max([f["area_mm2"] for f in faces] or [0])
        hs = [f for f in faces if f.get("h_w_m2k") is not None and f["area_mm2"] >= 0.1 * big]    # 小棱边、倒角不算
        hs.sort(key=lambda f: -f["h_w_m2k"])
        hi, lo = (hs[0], hs[-1]) if hs else (None, None)
        lines.append("表面 {} ℃、空气 {} ℃ 时共散热 {:.1f} W，平均散热系数 h = {:.1f} W/(m²·K)。".format(
            st["wall_t_c"], st["air_t_c"], st["heat_w"], st["h_mean"]))
        if hi and lo and hi is not lo:
            lines.append("各面差别大：面 {} 最大 {:.1f}，面 {} 最小 {:.1f}。迎风面和边界层刚开始的地方 h 大（边界层薄），"
                         "背风面、角落和贴近地面的地方 h 小（风到不了、空气已被加热）。".format(hi["id"], hi["h_w_m2k"], lo["id"], lo["h_w_m2k"]))
        k_air, L = 0.0262, st["L_char_mm"] / 1000
        h_lam = 0.664 * st["Re"] ** 0.5 * 0.73 ** (1 / 3) * k_air / L
        h_tur = 0.037 * st["Re"] ** 0.8 * 0.73 ** (1 / 3) * k_air / L
        lines.append("用教材平板公式核对量级（特征长度 {:.0f} mm）：层流边界层 Nu = 0.664·Re^½·Pr^⅓ → h ≈ {:.1f}；全湍流 Nu = 0.037·Re^0.8·Pr^⅓ → h ≈ {:.1f} W/(m²·K)。"
                     "算出的平均 h 落在两者之间是正常的（前缘附近层流、分离和尾流区紊乱、背风面风小）。点“送到温度场”就用这些 h 代替查表的散热系数。".format(
                         st["L_char_mm"], h_lam, h_tur))
    if not st.get("converged"):
        lines.append("注意：迭代到步数上限还没完全收敛（钝体尾流本身会摆动），阻力和 h 看前两三位有效数字即可；要更准可选“细”网格再算。")
    return {"text": "\n".join(lines), "engine": "rules"}


EXPLAIN_TOOL = {
    "name": "explain", "description": "给学生讲清这次流体分析的结果",
    "input_schema": {"type": "object", "required": ["text"], "properties": {
        "text": {"type": "string", "description": "4–7 句中文：流动状态、阻力构成、散热系数分布及原因、和教材公式的量级对照、结果可信度；只用给出的数字"}}},
}


def explain(llm, st, faces):
    base = rules_explain(st, faces)
    if llm is None or not llm.available():
        return base
    got = {}

    def call_tool(name, args):
        got.update(args)
        return {"ok": True}
    ctx = {"stats": st, "faces": sorted(faces, key=lambda f: -f["area_mm2"])[:20], "rule_notes": base["text"]}
    try:
        llm.run("你是传热与流体力学老师，根据 CFD 结果给本科生讲解。只用给出的数据；调用 explain 一次。",
                [{"role": "user", "content": json.dumps(ctx, ensure_ascii=False, default=str)[:12000]}], [EXPLAIN_TOOL], call_tool, max_turns=2)
    except Exception:  # noqa: BLE001
        return base
    return {"text": got["text"].strip(), "engine": llm.name} if got.get("text") else base
