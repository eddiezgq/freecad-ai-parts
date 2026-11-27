"""多体动力学计算报告（ADR-0097 D8b，补充二十二）：事实清单 → Markdown 报告 + 曲线图 + 出处账；AI 只写解释，数字用占位符。

和有限元报告（assist/fea_report.py）同一规矩：报告里每个数字都由程序从结果文件取，旁边写一份出处账（`*.ledger.json`），
记着每个数来自结果的哪个 JSON 指针、做了什么运算（取值、最大绝对值、最大模长、均方根）；测试把报告里的数字逐个对回结果。
AI 的段落里出现数字、写“合格 / 满足要求 / 安全”，或用了不存在的占位符，那一段就退回不用。报告页眉写“草稿，须工程师审核”。
"""

from __future__ import annotations

import json
import math
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

PROMPT_VERSION = "mbd-explain/1"
DEFAULT_MODEL = "claude-sonnet-5-5"
TOOL_NAME = "write_mbd_explanation"
DRAFT_MARK = "草稿，须工程师审核"
VERDICT = {"pass": "通过", "fail": "不通过", "unknown": "不判"}
ANALYSIS_ZH = {"kinematic": "运动学", "dynamic": "动力学", "static": "静平衡", "static_then_dynamic": "先静平衡再动力学",
               "linear": "线性化", "static_then_linear": "先静平衡再线性化"}
FORBIDDEN = ("合格", "满足要求", "安全", "可以放心", "没有问题", "没问题", "足够", "够用", "可靠", "放心")
SYSTEM_PROMPT = (
    "你是机械工程师，给一份多体动力学计算报告写解释段落。只能用给你的事实，数字一律写成占位符 {{键}}，"
    "不能自己写数字；不判定合格与否（合格要工程师对照要求判），核查没通过的要如实说。每段两三句话。")


def fmt(v: float) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    a = abs(v)
    if a != 0 and (a >= 1e5 or a < 1e-3):
        return f"{v:.4g}"
    return f"{v:.4g}"


def _get(doc, ptr):
    cur = doc
    for p in ptr.split("/")[1:]:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    return cur


def apply_op(doc, ptr, op):
    """出处账里的运算：value、max_abs、max_norm、rms_abs、min、max"""
    x = _get(doc, ptr)
    if op == "value":
        return float(x)
    a = np.asarray([v for v in x if v is not None], float)
    if op == "max_abs":
        return float(np.max(np.abs(a)))
    if op == "max_norm":
        return float(np.max(np.linalg.norm(a, axis=1)))
    if op == "max":
        return float(np.max(a))
    if op == "min":
        return float(np.min(a))
    raise ValueError(op)


def facts(data: dict) -> dict[str, dict]:
    """键 → {label, value, unit, ptr, op}"""
    F: dict[str, dict] = {}

    def add(key, label, ptr, op, unit=""):
        try:
            v = apply_op(data, ptr, op)
        except (KeyError, IndexError, ValueError, TypeError):
            return
        if math.isfinite(v):
            F[key] = {"label": label, "value": v, "unit": unit, "ptr": ptr, "op": op}

    add("dof", "自由度", "/dof", "value")
    if data.get("times_s"):
        add("t_end", "仿真时长", "/times_s", "max", "s")
    for k, v in enumerate(data.get("verification", [])):
        if isinstance(v.get("value"), (int, float)):
            add(f"check_{v['key']}", v["name"], f"/verification/{k}/value", "value")
    for mid, m in (data.get("motions") or {}).items():
        add(f"drive_{mid}_peak", f"驱动 {mid} 峰值", f"/motions/{mid}/effort", "max_abs", m.get("unit", ""))
    for jid in (data.get("joints") or {}):
        add(f"joint_{jid}_force", f"运动副 {jid} 最大反力", f"/joints/{jid}/force_n", "max_norm", "N")
        add(f"joint_{jid}_torque", f"运动副 {jid} 最大反力矩", f"/joints/{jid}/torque_n_m", "max_norm", "N·m")
    for aid in (data.get("actuators") or {}):
        add(f"act_{aid}_peak", f"执行器 {aid} 峰值", f"/actuators/{aid}", "max_abs")
    for cid in (data.get("contacts") or {}):
        add(f"contact_{cid}_peak", f"接触 {cid} 最大法向力", f"/contacts/{cid}/normal_force_n", "max_abs", "N")
    for bid, f in (data.get("flex") or {}).items():
        if f.get("type") == "nonlinear_beam":                 # 大变形梁（ADR-0101）：截面内力和应力
            if f.get("max_stress_mpa"):
                add(f"beam_{bid}_stress", f"大变形梁 {bid} 最大正应力", f"/flex/{bid}/max_stress_mpa", "max", "MPa")
            add(f"beam_{bid}_axial", f"大变形梁 {bid} 最大轴力", f"/flex/{bid}/axial_n", "max_abs", "N")
            add(f"beam_{bid}_my", f"大变形梁 {bid} 最大弯矩（y 轴）", f"/flex/{bid}/moment_y_n_m", "max_abs", "N·m")
            add(f"beam_{bid}_mz", f"大变形梁 {bid} 最大弯矩（z 轴）", f"/flex/{bid}/moment_z_n_m", "max_abs", "N·m")
            continue
        if f.get("stress"):
            add(f"flex_{bid}_stress", f"柔性构件 {bid} 最大 von Mises 应力", f"/flex/{bid}/stress/peak_mpa", "value", "MPa")
        add(f"flex_{bid}_elastic", f"柔性构件 {bid} 最大弹性能", f"/flex/{bid}/elastic_energy_j", "max", "J")
    lin = data.get("linear")
    if lin:
        nz = [k for k, m in enumerate(lin["modes"]) if m["frequency_hz"] > 1e-6]
        for n, k in enumerate(nz[:6], 1):
            add(f"mode{n}_hz", f"第 {n} 阶固有频率", f"/linear/modes/{k}/frequency_hz", "value", "Hz")
            add(f"mode{n}_zeta", f"第 {n} 阶阻尼比", f"/linear/modes/{k}/damping_ratio", "value")
    return F


def build_request(data: dict, F: dict, *, model: str = DEFAULT_MODEL) -> dict:
    lines = [f"- {{{{{k}}}}}：{v['label']} = {fmt(v['value'])} {v['unit']}" for k, v in F.items()]
    checks = [f"- {v['name']}：{VERDICT.get(v['status'], v['status'])}" for v in data.get("verification", [])]
    user = (f"模型：{data.get('model', '')}；分析：{ANALYSIS_ZH.get(data.get('analysis'), data.get('analysis'))}\n"
            f"事实（写解释时数字只能用左边的占位符）：\n" + "\n".join(lines) + "\n核查：\n" + "\n".join(checks))
    return {"model": model, "prompt_version": PROMPT_VERSION, "system": SYSTEM_PROMPT, "user": user,
            "tool": {"name": TOOL_NAME, "description": "提交解释段落",
                     "input_schema": {"type": "object", "properties": {"paragraphs": {"type": "array", "items": {"type": "string"}}},
                                      "required": ["paragraphs"]}}}


def model_names(data: dict) -> set[str]:
    """结果里出现的构件、运动副、驱动、执行器、接触、柔性体、核查的名字（j1、R2、d1 这类常带数字）"""
    out = set()
    for k in ("bodies", "joints", "motions", "actuators", "contacts", "flex", "forces"):
        v = data.get(k)
        if isinstance(v, dict):
            out |= {str(x) for x in v}
    out |= {str(v.get("key")) for v in data.get("verification", []) if v.get("key")}
    return out


def check_paragraph(text: str, F: dict, names=()) -> str | None:
    """不合规返回原因，合规返回 None。names：模型里的名字，查数字前先去掉（《多体动力学》书第 45 章线索第 82 条：
    “驱动 d1 的力矩峰值为 {{drive_d1_peak}}”因 d1 带数字被退回，37 句正确解释退回 17 句）"""
    for k in re.findall(r"\{\{([^}]+)\}\}", text):
        if k not in F:
            return f"用了不存在的占位符 {k}"
    bare = re.sub(r"\{\{[^}]+\}\}", "", text)
    for n in sorted(names, key=len, reverse=True):
        bare = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", "", bare)
    if re.search(r"\d", bare):
        return "段落里直接写了数字"
    for w in FORBIDDEN:
        if w in bare:
            return f"段落里判定了“{w}”"
    return None


def explain(data: dict, F: dict, client=None, *, model: str = DEFAULT_MODEL, mbd_model: dict | None = None) -> dict:
    """AI 写解释，程序逐段、逐句核对。mbd_model 给了（运动学分析）就能核阶段、重力 / 惯性份额、效应（线索第 83 条）"""
    if client is None:
        return {"paragraphs": [], "rejected": [], "review": [], "by": "没有用 AI"}
    resp = client.complete(build_request(data, F, model=model))
    paras = (resp.get("tool_input") or {}).get("paragraphs") or []
    I = insight(mbd_model, data) if mbd_model else insight(None, data)
    names = model_names(data)
    ok, bad, review = [], [], []
    for p in paras:
        p = str(p)
        why = check_paragraph(p, F, names)
        if why is None:
            for sent in split_sentences(p):
                verdict, reason = check_sentence(sent, F, I, names)
                if verdict == "拦下":
                    why = f"“{sent}”：{reason}"
                    break
                if verdict == "交人看":
                    review.append({"text": sent, "why": reason})
        (bad.append({"text": p, "why": why}) if why else ok.append(p))
    miss = hidden_checks(ok, I)
    if miss:                    # 整段必须写到每一项不通过、不判的核查；隐去了就整份解释不用
        bad += [{"text": p, "why": f"解释里没写到不通过 / 不判的核查：{'、'.join(miss)}"} for p in ok]
        ok = []
    return {"paragraphs": ok, "rejected": bad, "review": review,
            "by": f"AI {resp.get('model', '')}（提示词 {PROMPT_VERSION}，响应 {resp.get('id', '')}）"}


# ---------------------------------------------------------------- 逐句核对（线索第 83 条）
# 《多体动力学》书第 45 章线索第 83 条（问渠 CAD 0.3.9 细则）：段落检查只拦“直接写数字、不存在的占位符、词表内判定词”，
# 54 句该拦的错误只拦下 12 句（名字不带数字时）——“{{a}} 大于 {{b}}”（实际小于）、“约为两倍”（实际六倍）、“j2 是最大的”、
# “出现在减速段”（实际加速段）、“主要来自惯性”（实际重力占 73 %）、“始终为负”、“各项核查都通过”、隐去不通过的核查、
# “计算考虑了关节摩擦”（模型没有）都放过。下面按书里的受控句式逐句核对；句式之外的因果断言交人看。
CAUSAL = ("因为", "由于", "所以", "因此", "因而", "从而", "可见", "导致", "说明", "表明", "意味着", "随着", "越", "决定", "取决于", "原因")
CN = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
FEATURES = ("摩擦", "阻尼", "弹簧", "接触", "柔性")
PH = re.compile(r"\{\{([^}]+)\}\}")
_UNIT_AFTER = re.compile(r"\}\}\s*(kN·m|N·m|kN|N|mm|m/s|m|s|Hz|MPa|J|W|rpm|°)")


def split_sentences(p: str) -> list[str]:
    return [x for x in re.split(r"(?<=[。；！？])", p) if x.strip()]


def _fact_meta(k: str):
    """事实键 → (类别, 对象)"""
    m = re.fullmatch(r"drive_(.+)_peak", k)
    if m:
        return "drive", m.group(1)
    m = re.fullmatch(r"joint_(.+)_(force|torque)", k)
    if m:
        return m.group(2), m.group(1)
    if k.startswith("check_"):
        return "check", k[6:]
    return None, None


def _drive_jets(mo, t):
    """驱动副的规定位移及其一、二阶导数（° 或 mm，按 dae 的时间函数精确求导）"""
    if "speed" in mo:
        v = mo["speed"] * (6.0 if mo["dof"] == "rotation" else 1.0)
        return v * t, np.full_like(t, v), np.zeros_like(t)
    from analysis.mbd.dae.expr import compile_expr
    f = compile_expr(mo["function"])
    js = np.array([f.jet(float(x)) for x in t])          # 每个时刻 (值, 一阶导, 二阶导)
    return js[:, 0], js[:, 1], js[:, 2]


def insight(mbd_model: dict | None, data: dict) -> dict:
    """程序替 AI 算“为什么”：每个驱动的峰值阶段、正负、重力份额；各类最大最小者；核查状态；模型含哪些效应"""
    I = {"drives": {}, "argmax": {}, "argmin": {}, "checks": {}, "features": {}}
    t = np.asarray(data.get("times_s") or [], float)
    mos = {m["id"]: m for m in (mbd_model or {}).get("motions") or []}
    g0 = None
    if mbd_model and data.get("analysis") == "kinematic" and any(mbd_model.get("gravity_mm_s2") or [0, 0, 0]):
        try:                    # 规定运动的运动学分析对载荷线性：重力置零再算一遍，差就是重力的份额
            from analysis.mbd.dae.run import run_model
            m0 = json.loads(json.dumps(mbd_model))
            m0["gravity_mm_s2"] = [0.0, 0.0, 0.0]
            g0, _ = run_model(m0)
        except Exception:  # noqa: BLE001 — 拿不到就不核原因（交人看）
            g0 = None
    for mid, m in (data.get("motions") or {}).items():
        e = np.asarray(m.get("effort") or [], float)
        if not len(e) or len(e) != len(t):
            continue
        k = int(np.argmax(np.abs(e)))
        tol = 1e-9 * np.max(np.abs(e))
        d = {"sign": "始终为正" if np.all(e >= -tol) else "始终为负" if np.all(e <= tol) else "有正有负"}
        if mid in mos and len(t) > 2:
            try:
                _, qd, qdd = _drive_jets(mos[mid], t)
                if abs(qdd[k]) <= 1e-6 * max(np.max(np.abs(qdd)), 1e-30) or np.max(np.abs(qdd)) * (t[-1] - t[0]) < 1e-6 * np.max(np.abs(qd)):
                    d["phase"] = "匀速段"
                elif abs(qd[k]) < 1e-9 * max(np.max(np.abs(qd)), 1e-30):
                    d["phase"] = "起点" if k < len(t) / 2 else "终点"
                else:
                    d["phase"] = "加速段" if qd[k] * qdd[k] > 0 else "减速段"
            except Exception:  # noqa: BLE001 — 式子求不了值就不核阶段（交人看）
                d.pop("phase", None)
        if g0 is not None and mid in (g0.get("motions") or {}):
            e0 = np.asarray(g0["motions"][mid]["effort"], float)
            gp, ip = e[k] - e0[k], e0[k]
            if abs(gp) + abs(ip) > 0:
                d["g_share"] = abs(gp) / (abs(gp) + abs(ip))
                d["cause"] = "重力" if d["g_share"] > 0.5 else "惯性"
        I["drives"][mid] = d
    F = facts(data)
    for cat in ("drive", "force", "torque"):
        ks = [k for k in F if _fact_meta(k)[0] == cat]
        if ks:
            I["argmax"][cat] = _fact_meta(max(ks, key=lambda k: F[k]["value"]))[1]
            I["argmin"][cat] = _fact_meta(min(ks, key=lambda k: F[k]["value"]))[1]
    for v in data.get("verification", []):
        I["checks"][v["key"]] = {"name": v["name"], "status": v["status"]}
    if mbd_model:
        fs = mbd_model.get("forces") or []
        I["features"] = {
            "摩擦": any("friction" in j for j in mbd_model.get("joints") or []),
            "阻尼": any(any("damping" in k and isinstance(x, int | float) and abs(x) > 0 for k, x in f.items()) for f in fs),
            "弹簧": any("spring" in str(f.get("type", "")) for f in fs),
            "接触": bool(mbd_model.get("contacts")),
            "柔性": bool(mbd_model.get("flex_bodies") or mbd_model.get("flex"))}
    return I


def cn_number(s: str):
    """中文倍数：两倍、三倍、十倍、一半、三成、四分之一 → 数；认不出返回 None"""
    def cn_int(x):
        if x == "十":
            return 10
        if x.startswith("十"):
            return 10 + CN[x[1]]
        if "十" in x:
            a, b = x.split("十")
            return CN[a] * 10 + (CN[b] if b else 0)
        return CN[x]
    m = re.search(r"([零一两二三四五六七八九十]+)分之([零一两二三四五六七八九十]+)", s)
    if m:
        return cn_int(m.group(2)) / cn_int(m.group(1))
    if "一半" in s:
        return 0.5
    m = re.search(r"([一两二三四五六七八九])成", s)
    if m:
        return CN[m.group(1)] / 10
    m = re.search(r"([零一两二三四五六七八九十]+)倍", s)
    return float(cn_int(m.group(1))) if m else None


def _mentioned(text, ents):
    out = []
    for e in ents:
        out += [(m.start(), e) for m in re.finditer(rf"(?<![A-Za-z0-9_]){re.escape(e)}(?![A-Za-z0-9_])", text)]
    return [e for _, e in sorted(out)]


def check_sentence(text: str, F: dict, I: dict, names=()) -> tuple[str, str]:
    """一句话 → ("通过" | "拦下" | "交人看", 原因)。数字、占位符、判定词由 check_paragraph 先查"""
    ents = sorted({_fact_meta(k)[1] for k in F if _fact_meta(k)[0] in ("drive", "force", "torque")}, key=len, reverse=True)
    keys = PH.findall(text)
    bare = PH.sub("", text)
    m = _UNIT_AFTER.search(text)
    if m:
        return "拦下", f"占位符后又写了单位“{m.group(1)}”（程序填数时会带单位）"
    for mm in PH.finditer(text):            # 主语与占位符一致
        k = mm.group(1)
        cat, ent = _fact_meta(k)
        clause = re.split(r"[，、；：]", text[:mm.start()])[-1]
        said = _mentioned(clause, ents)
        if said and ent is not None and cat in ("drive", "force", "torque") and said[-1] != ent:
            return "拦下", f"说的是 {said[-1]}，占位符是 {ent} 的量"
        if "反力矩" in clause and cat == "force":
            return "拦下", "说的是反力矩，占位符是反力"
        if "反力" in clause and "反力矩" not in clause and cat == "torque":
            return "拦下", "说的是反力，占位符是反力矩"
    said = _mentioned(text, ents)
    subj = said[0] if said else (_fact_meta(keys[0])[1] if keys else None)
    cat = "torque" if "反力矩" in text else "force" if "反力" in text else "drive" if ("驱动" in text or "力矩" in text) else None
    verified = False
    if re.search(r"(所有|各|全部).{0,10}最(大|小)", text) and subj and cat:
        which = "argmax" if "最大" in text else "argmin"
        truth = I["argmax" if which == "argmax" else "argmin"].get(cat)
        if truth != subj:
            return "拦下", f"最{'大' if which == 'argmax' else '小'}的是 {truth}，不是 {subj}"
        verified = True
    m = re.search(r"\{\{([^}]+)\}\}\s*(大于|高于|超过|小于|低于)\s*\{\{([^}]+)\}\}", text)
    if m:
        a, b = F[m.group(1)]["value"], F[m.group(3)]["value"]
        if (m.group(2) in ("大于", "高于", "超过")) != (a > b):
            return "拦下", f"比较说反了（{fmt(a)} 与 {fmt(b)}）"
        verified = True
    r = cn_number(bare)
    if r is not None:
        pair = keys[:2] if len(keys) >= 2 else None
        if pair is None and len(said) >= 2 and cat:
            pk = [next((k for k in F if _fact_meta(k) == (cat, n)), None) for n in said[:2]]
            pair = pk if all(pk) else None
        if pair is None:
            return "交人看", "倍数说不清比的是哪两个量"
        ratio = F[pair[0]]["value"] / F[pair[1]]["value"]
        if abs(ratio / r - 1) > 0.15:
            return "拦下", f"说是 {r:g} 倍，实际 {ratio:.3g} 倍"
        verified = True
    d = I["drives"].get(subj) if subj else None
    m = re.search(r"出现在(加速段|匀速段|减速段|起点|终点)", text)
    if m:
        if not d or "phase" not in d:
            return "交人看", "阶段无从核对"
        if d["phase"] != m.group(1):
            return "拦下", f"峰值在{d['phase']}，不在{m.group(1)}"
        verified = True
    m = re.search(r"主要(来自|由|是)(重力|惯性)", text)
    if m:
        if not d or "cause" not in d:
            return "交人看", "没有重力 / 惯性分解，原因无从核对"
        if d["cause"] != m.group(2):
            return "拦下", f"峰值处重力份额 {d['g_share']:.0%}，主要来自{d['cause']}"
        verified = True
    m = re.search(r"(始终为正|始终为负|有正有负)", text)
    if m:
        if not d:
            return "交人看", "正负的主语不是驱动"
        if d["sign"] != m.group(1):
            return "拦下", f"实际{d['sign']}"
        verified = True
    if re.search(r"(各项|全部|所有)核查(都|均|全部)?(通过)", text):
        bad = [c["name"] for c in I["checks"].values() if c["status"] != "pass"]
        if bad:
            return "拦下", f"{'、'.join(bad)} 没有通过"
        verified = True
    for c in I["checks"].values():
        if c["name"] in text:
            said_fail = bool(re.search(r"(没有通过|不通过|未通过)", text))
            said_unk = "不判" in text
            said_pass = not said_fail and not said_unk and "通过" in text
            truth = VERDICT.get(c["status"], c["status"])
            say = "不通过" if said_fail else "不判" if said_unk else "通过" if said_pass else None
            if say and say != truth:
                return "拦下", f"{c['name']} 的结论是{truth}，不是{say}"
            verified = verified or say is not None
    for w in FEATURES:
        if w in text:
            neg = bool(re.search(rf"(没有考虑|没有计入|未计入|未考虑|不含|没有).{{0,6}}{w}", text))
            pos = bool(re.search(rf"(考虑了|计入了|包括|含有?).{{0,6}}{w}", text)) and not neg
            if w not in I["features"]:
                if neg or pos:
                    return "交人看", f"不知道模型里有没有{w}"
                continue
            if neg and I["features"][w]:
                return "拦下", f"模型里有{w}"
            if pos and not I["features"][w]:
                return "拦下", f"模型里没有{w}"
            verified = verified or neg or pos
    if not verified and any(w in bare for w in CAUSAL):
        return "交人看", "句式之外的因果或趋势断言"
    return "通过", "核对过" if verified else "只有描述"


def hidden_checks(paragraphs, I) -> list[str]:
    """不通过、不判的核查，解释里一句没提（写名字或占位符）的"""
    txt = "".join(paragraphs)
    return [c["name"] for k, c in I["checks"].items() if c["status"] != "pass" and c["name"] not in txt and f"check_{k}" not in txt]


class _Ledger:
    def __init__(self):
        self.items = []

    def num(self, key, F):
        f = F[key]
        s = fmt(f["value"])
        self.items.append({"text": s, "key": key, "ptr": f["ptr"], "op": f["op"], "value": f["value"]})
        return s


def _plot(data, out: Path, name: str, title: str, series: dict, unit: str) -> str | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    t = data["times_s"]
    fig, ax = plt.subplots(figsize=(6, 2.6), dpi=120)
    for lab, ys in series.items():
        ax.plot(t, ys, label=lab)
    ax.set_xlabel("t / s")
    ax.set_ylabel(unit)
    if title:
        ax.set_title(title)
    ax.grid(alpha=0.3)
    if len(series) > 1:
        ax.legend(fontsize=7)
    fig.tight_layout()
    p = out / f"{name}.png"
    fig.savefig(p)
    plt.close(fig)
    return p.name


def build(data: dict, out: str | Path, *, client=None, result_file: str = "result.json", title: str | None = None) -> dict:
    """写 out/report.md、曲线图、out/report.ledger.json；result_file 是结果文件名（出处账里引用）"""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    F = facts(data)
    L = _Ledger()
    ex = explain(data, F, client)
    lines = [f"# {title or data.get('model', '多体动力学')} 计算报告", "",
             f"> {DRAFT_MARK}。本报告里的每个数字都由程序从结果文件 `{result_file}` 取得，出处见 `report.ledger.json`。", ""]
    lines += ["## 模型与分析", "", f"- 分析类型：{ANALYSIS_ZH.get(data.get('analysis'), data.get('analysis'))}"]
    if "dof" in F:
        lines.append(f"- 自由度：{L.num('dof', F)}")
    if "t_end" in F:
        lines.append(f"- 仿真时长：{L.num('t_end', F)} s")
    if data.get("redundant_constraints"):
        lines.append(f"- 删去的冗余约束：{'、'.join(data['redundant_constraints'])}")
    lines += ["", "## 核查结论", "", "| 核查 | 结论 | 数值 |", "| --- | --- | --- |"]
    for v in data.get("verification", []):
        key = f"check_{v['key']}"
        val = L.num(key, F) if key in F else "—"
        lines.append(f"| {v['name']} | {VERDICT.get(v['status'], v['status'])} | {val} |")
    keys = [k for k in F if k not in ("dof", "t_end") and not k.startswith("check_")]
    if keys:
        lines += ["", "## 主要结果", "", "| 项目 | 数值 | 单位 |", "| --- | --- | --- |"]
        lines += [f"| {F[k]['label']} | {L.num(k, F)} | {F[k]['unit']} |" for k in keys]
    figs = []
    if data.get("motions"):
        figs.append(_plot(data, out, "drives", "drive effort", {k: m["effort"] for k, m in data["motions"].items()},
                          "/".join(sorted({m["unit"] for m in data["motions"].values()}))))
    if data.get("joints") and len(data["times_s"]) > 1:
        figs.append(_plot(data, out, "reactions", "joint reaction |F|",
                          {k: np.linalg.norm(np.asarray(j["force_n"]), axis=1) for k, j in data["joints"].items()}, "N"))
    figs = [f for f in figs if f]
    if figs:
        lines += ["", "## 曲线", ""] + [f"![{f}]({f})" for f in figs]
    if ex["paragraphs"]:
        lines += ["", "## 解释（AI 起草，须审核）", ""]
        for p in ex["paragraphs"]:
            lines += [re.sub(r"\{\{([^}]+)\}\}", lambda m: f"{L.num(m.group(1), F)} {F[m.group(1)]['unit']}".strip(), p), ""]
    if ex.get("review"):
        lines += ["", "须工程师确认（AI 写的因果或趋势判断，程序无法核对）：", ""] + [
            "- " + re.sub(r"\{\{([^}]+)\}\}", lambda m: f"〔{F[m.group(1)]['label']}〕" if m.group(1) in F else "〔?〕", x["text"])
            for x in ex["review"]]
    if data.get("limitations"):
        lines += ["", "## 局限", ""] + [f"- {x}" for x in data["limitations"]]
    lines += ["", "## 审核", "", "| 编制 | 审核 | 批准 |", "| --- | --- | --- |", "|  |  |  |", ""]
    md = "\n".join(lines)
    (out / "report.md").write_text(md, encoding="utf-8")
    labels = sorted({str(data.get("model", ""))} | set(data.get("redundant_constraints") or [])
                    | {v["name"] for v in data.get("verification", [])}
                    | {k for sec in ("motions", "joints", "actuators", "contacts", "flex", "measures") for k in (data.get(sec) or {})}
                    | ({title} if title else set()) - {""})
    ledger = {"result_file": result_file, "labels": labels, "generated": datetime.now(UTC).isoformat(timespec="seconds"),
              "explanation": {"by": ex["by"], "rejected": ex["rejected"], "review": ex.get("review", [])}, "numbers": L.items}
    (out / "report.ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"markdown": out / "report.md", "ledger": out / "report.ledger.json", "figures": figs, "explanation": ex}


# ---------------------------------------------------------------- Word / PDF 正式报告（ADR-0102 第 1 步）
JOINT_ZH = {"fixed": "固定", "revolute": "转动", "translational": "移动", "cylindrical": "圆柱", "spherical": "球",
            "universal": "万向"}
FLEX_ZH = {"beam": "模态梁", "modal": "实体模态", "nonlinear_beam": "大变形梁"}
OP_ZH = {"value": "取值", "max_abs": "最大绝对值", "max_norm": "最大模长", "max": "最大", "min": "最小"}


class _DocLedger:
    """有限元报告的出处账（assist.fea_report.Ledger）加一种“运算值”：最大绝对值、最大模长……，账上记运算名"""

    def __init__(self, sources, lang):
        from assist.fea_report import Ledger

        self.L = Ledger(sources, lang)

    def __getattr__(self, k):
        return getattr(self.L, k)

    def op(self, src, ptr, op, unit=""):
        v = apply_op(self.L.sources[src], ptr, op)
        if op == "value":
            return self.L.num(src, ptr, unit)
        s = fmt_num(v)
        self.L.entries.append({"text": s, "source": src, "pointer": ptr, "kind": "op", "op": op})
        return s + (f" {unit}" if unit else "")


def fmt_num(v):
    from assist.fea_report import fmt as _f

    return _f(float(v))


def _strip_timing(data):
    return {k: v for k, v in data.items() if k not in ("solver",)}


def checklist(model: dict, data: dict) -> list[dict]:
    """审核清单：程序能判的给结论（来自核查），其余“须人工判断”"""
    rows = []
    for v in data.get("verification", []):
        rows.append({"item": v["name"], "verdict": VERDICT.get(v["status"], v["status"]), "basis": "程序核查"})
    rows += [
        {"item": "构件质量、质心、惯量与实物一致（来自 CAD 或材料）", "verdict": "须人工判断", "basis": "模型"},
        {"item": "运动副的类型、位置、轴向与实际机构一致", "verdict": "须人工判断", "basis": "模型"},
        {"item": "驱动、载荷与实际工况一致（时间历程、大小、方向）", "verdict": "须人工判断", "basis": "模型"},
        {"item": "柔性件的取法（模态 / 实体 / 大变形梁）适合本问题", "verdict": "须人工判断", "basis": "模型"},
        {"item": "AI 解释的文字与结果一致、没有超出结果的推断", "verdict": "须人工判断", "basis": "报告"},
    ]
    return rows


def build_docx(model: dict, data: dict, out, *, number: str | None = None, revision: str = "草稿", reason: str = "首次出稿",
               explanation: dict | None = None, today=None, lang: str = "zh", company: str | None = None,
               figures_dir=None) -> dict:
    """多体动力学正式报告（Word，旁边写出处账 *.ledger.json 与改版记录 *.record.json）。
    数字一律经出处账从模型、结果、改版记录里取；AI 只写解释，数字用 {{键}} 占位（explain() 的输出）。"""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    from assist import i18n
    from assist.fea_report import code_version, fingerprint

    if lang not in i18n.LANGS:
        raise ValueError(f"报告语言只能是 {i18n.LANGS}")
    if data.get("model") != model.get("name"):
        raise ValueError("结果不是用这个模型算的（模型名不一致）")

    def F(x):
        return i18n.final(x, lang)

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    today = today or datetime.now(UTC).date()
    rec_path = out.with_suffix(".record.json")
    record = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.is_file() else {"history": []}
    record["number"] = number or record.get("number") or "未编号（由质量体系分配）"
    files = {"model": fingerprint(model), "result": fingerprint(_strip_timing(data))}
    entry = {"revision": revision, "date": today.isoformat(), "reason": reason, "result_fingerprint": files["result"],
             "model_fingerprint": files["model"]}
    record["history"] = [h for h in record["history"] if h["revision"] != revision] + [entry]
    rec_path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    env = {"code": code_version(), "integrator": str((data.get("solver") or {}).get("integrator", "—")),
           "company": company or ""}
    L = _DocLedger({"model": model, "result": data, "record": record, "files": files, "env": env,
                 "explain": explanation or {}}, lang)
    Fx = facts(data)

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Noto Sans CJK SC"
    st.font.size = Pt(10)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Noto Sans CJK SC")
    last = len(record["history"]) - 1
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2)
        hp = s.header.paragraphs[0]
        head = (L.txt("env", "/company") + "　") if company else ""
        hp.text = head + F(f"{DRAFT_MARK}　报告编号 {L.txt('record', '/number', True)}　版次 {L.txt('record', f'/history/{last}/revision', True)}")
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    def h(text, lvl=1):
        o = F(text)
        if lang == "en" and lvl == 1 and re.match(r"^\d+\. ", o):
            L.label(o)
        doc.add_heading(o, level=lvl)

    def p(text, style=None):
        return doc.add_paragraph(F(text), style=style) if style else doc.add_paragraph(F(text))

    def table(head, rows):
        t = doc.add_table(rows=1, cols=len(head))
        t.style = "Table Grid"
        for c, x in zip(t.rows[0].cells, head, strict=True):
            c.text = F(x)
            for r in c.paragraphs[0].runs:
                r.bold = True
        for row in rows:
            for c, x in zip(t.add_row().cells, row, strict=True):
                c.text = F(x)
        return t

    an = model["analysis"]
    doc.add_heading(F(f"多体动力学计算报告：{L.txt('model', '/name')}"), 0)
    table(["项目", "内容"], [
        ["报告编号", L.txt("record", "/number", True)], ["版次", L.txt("record", f"/history/{last}/revision", True)],
        ["出稿日期", L.txt("record", f"/history/{last}/date")], ["状态", DRAFT_MARK],
        ["编制（签字 / 日期）", ""], ["审核（签字 / 日期）", ""], ["批准（签字 / 日期）", ""]])
    p("编制、审核、批准三栏由人签字，程序不代签。")

    # 一、结论摘要
    h("一、结论摘要")
    bad = [v for v in data.get("verification", []) if v["status"] == "fail"]
    p("程序核查：" + ("全部通过或不判。" if not bad else "有不通过的项（见第三节），结果须谨慎使用。"))
    p("本报告不作合格判定，由审核人按审核清单判断。")
    keys = [k for k in Fx if not k.startswith("check_") and k not in ("dof", "t_end")]
    if keys:
        table(["项目", "数值"], [[Fx[k]["label"], L.op("result", Fx[k]["ptr"], Fx[k]["op"], Fx[k]["unit"])] for k in keys])

    # 二、模型
    h("二、模型")
    rows = [[ANALYSIS_ZH.get(an["type"], an["type"]), L.num("model", "/analysis/end_time_s", "s") if "end_time_s" in an else "—",
             L.num("model", "/analysis/output_steps") if "output_steps" in an else "—", L.txt("env", "/integrator")]]
    table(["分析类型", "时长", "输出点数", "积分器"], rows)
    if "dof" in data:
        p(f"自由度 {L.num('result', '/dof')}。")
    h("构件", 2)
    bidx = {b["id"]: i for i, b in enumerate(model["bodies"])}

    def bname(i):
        """构件名：模型里写了显示名（如装配体零件的标签）时写“显示名（id）”"""
        b = model["bodies"][i]
        if b.get("name") and b["name"] != b["id"]:
            lp, rp = ("（", "）") if lang == "zh" else (" (", ")")
            return f"{L.txt('model', f'/bodies/{i}/name')}{lp}{L.txt('model', f'/bodies/{i}/id')}{rp}"
        return L.txt("model", f"/bodies/{i}/id")

    def jbody(i, side):
        bid = model["joints"][i][side]
        return L.txt("model", f"/bodies/{bidx[bid]}/name") if bid in bidx and model["bodies"][bidx[bid]].get("name") \
            else L.txt("model", f"/joints/{i}/{side}")

    brows = []
    for i, b in enumerate(model["bodies"]):
        if b.get("flex"):
            brows.append([bname(i), F(FLEX_ZH.get(b["flex"]["type"], b["flex"]["type"])), "—", "—"])
        else:
            brows.append([bname(i), F("刚体"), L.num("model", f"/bodies/{i}/mass_kg", "kg"),
                          L.vec("model", f"/bodies/{i}/cm_mm", "mm")])
    table(["名称", "类型", "质量", "质心"], brows)
    if model.get("joints"):
        h("运动副", 2)
        table(["名称", "类型", "构件 i", "构件 j", "运动副中心"], [
            [L.txt("model", f"/joints/{i}/id"), F(JOINT_ZH.get(j["type"], j["type"])), jbody(i, "body_i"),
             jbody(i, "body_j"), L.vec("model", f"/joints/{i}/point_mm", "mm")]
            for i, j in enumerate(model["joints"])])
    if data.get("redundant_constraints"):
        names = "、".join(L.txt("result", f"/redundant_constraints/{k}") for k in range(len(data["redundant_constraints"])))
        p(f"删去的冗余约束（反力里这些方向的分量不唯一）：{names}")

    # 三、可信度核查
    h("三、可信度核查")
    table(["核查项", "结论", "数值"], [
        [L.txt("result", f"/verification/{k}/name", True), VERDICT.get(v["status"], v["status"]),
         L.num("result", f"/verification/{k}/value") if isinstance(v.get("value"), (int, float)) else "—"]
        for k, v in enumerate(data.get("verification", []))])

    # 四、结果
    h("四、结果")
    tmp = Path(figures_dir) if figures_dir else Path(tempfile.mkdtemp(prefix="mbd-report-"))
    tmp.mkdir(parents=True, exist_ok=True)
    figs = []
    if data.get("motions"):
        figs.append((_plot(data, tmp, "drives", "drive effort", {k: m["effort"] for k, m in data["motions"].items()},
                           "/".join(sorted({m["unit"] for m in data["motions"].values()}))), "驱动力 / 力矩随时间"))
    if data.get("joints") and len(data["times_s"]) > 1:
        figs.append((_plot(data, tmp, "reactions", "",
                           {k: np.linalg.norm(np.asarray(j["force_n"]), axis=1) for k, j in data["joints"].items()}, "N"),
                     "运动副反力大小随时间"))
    for mid, ms in (data.get("measures") or {}).items():
        if isinstance(ms, dict) and ms.get("values") and len(ms["values"]) == len(data["times_s"]):
            figs.append((_plot(data, tmp, f"measure-{mid}", "", {mid: ms["values"]}, ms.get("unit", "")), f"测量量 {mid} 随时间"))
    if data.get("actuators"):
        figs.append((_plot(data, tmp, "actuators", "", dict(data["actuators"].items()), ""), "执行器输出随时间"))
    for f, cap in figs:
        if f:
            doc.add_picture(str(tmp / f), width=Cm(15))
            p(f"图：{cap}（按结果文件画）".replace(cap, cap if not re.search(r"[0-9]", cap) else L.label(cap)))
    lin = data.get("linear")
    if lin:
        h("固有频率", 2)
        nz = [k for k, m in enumerate(lin["modes"]) if m["frequency_hz"] > 1e-6]
        table(["阶次", "频率（Hz）", "阻尼比"], [
            [L.label(str(n + 1)), L.num("result", f"/linear/modes/{k}/frequency_hz"),
             L.num("result", f"/linear/modes/{k}/damping_ratio") if lin["modes"][k].get("damping_ratio") is not None else "—"]
            for n, k in enumerate(nz)])
    if not figures_dir:
        shutil.rmtree(tmp, ignore_errors=True)

    # 五、解释（AI）
    h("五、解释与说明（AI 起草，须工程师判断）")
    if not explanation or not explanation.get("paragraphs"):
        p("没有生成 AI 解释（本次出稿没有调用 AI，或 AI 的段落全部不合规被退回）。")
    else:
        p("下面的文字由 AI 起草；文字里的数值由程序从结果文件填入，AI 不判定合格。")
        for t in explanation["paragraphs"]:
            p(re.sub(r"\{\{([^}]+)\}\}", lambda m_: L.op("result", Fx[m_.group(1)]["ptr"], Fx[m_.group(1)]["op"],
                                                          Fx[m_.group(1)]["unit"]), t))
    if explanation and explanation.get("rejected"):
        p(f"退回不用的 AI 段落 {L.label(str(len(explanation['rejected'])))} 段（原文与原因记在出处账）。")
    if explanation and explanation.get("review"):
        # 线索第 83 条：受控句式之外的因果、趋势断言，程序核不了，交工程师看
        p("下面几句是 AI 写的因果或趋势判断，程序无法核对，须工程师确认：" + "；".join(
            re.sub(r"\{\{([^}]+)\}\}", lambda m_: f"〔{Fx[m_.group(1)]['label']}〕" if m_.group(1) in Fx else "〔?〕", x["text"])
            for x in explanation["review"]))

    # 六、局限
    h("六、局限")
    lims = data.get("limitations") or []
    for k in range(len(lims)):
        p(L.txt("result", f"/limitations/{k}", True), "List Bullet")
    p("多体模型的结果取决于模型对实物的简化（构件、运动副、力元、柔性件的取法），这些由审核人对照实物判断。")

    # 七、审核清单
    h("七、审核清单")
    p("程序给出能确定核查的项的结论，其余标“须人工判断”；审核人逐项勾选并签字。")
    table(["项目", "程序结论", "依据", "审核人勾选", "备注"],
          [[r["item"] if not re.search(r"[0-9]", r["item"]) else L.txt("result", f"/verification/{k}/name", True),
            r["verdict"], r["basis"], "☐", ""] for k, r in enumerate(checklist(model, data))])

    # 八、可追溯信息
    h("八、可追溯信息")
    table(["项目", "内容"], [
        ["模型内容指纹（SHA-256）", L.txt("files", "/model")],
        ["结果指纹（SHA-256，同一模型重算应相同）", L.txt("files", "/result")],
        ["积分器", L.txt("env", "/integrator")],
        ["本项目代码版本（git 提交）", L.txt("env", "/code", True)]])
    h("改版记录", 2)
    table(["版次", "日期", "原因", "结果指纹"], [
        [L.txt("record", f"/history/{k}/revision", True), L.txt("record", f"/history/{k}/date"),
         L.txt("record", f"/history/{k}/reason", True), L.txt("record", f"/history/{k}/result_fingerprint")]
        for k in range(len(record["history"]))])
    if explanation and explanation.get("by"):
        p(f"解释由 {L.txt('explain', '/by')} 起草。")

    doc.save(out)
    ledger = {"report": out.name, "lang": lang, "files": files, "entries": L.entries, "labels": L.labels,
              "explanation": {"by": (explanation or {}).get("by"), "rejected": (explanation or {}).get("rejected", []),
                              "review": (explanation or {}).get("review", [])}}
    led_path = out.with_suffix(".ledger.json")
    led_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    pdf = None
    try:
        from assist.fea_report import to_pdf

        pdf = to_pdf(out)
    except Exception:  # noqa: BLE001 — 没有 LibreOffice 或转换失败时只给 Word
        pdf = None
    return {"docx": out, "pdf": pdf, "ledger": led_path, "record": rec_path}
