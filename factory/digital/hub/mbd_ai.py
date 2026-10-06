# -*- coding: utf-8 -*-
"""运动与动力分析的 AI（第 12 轮 D4、D5）：一句话设置、结果解释与建议。
和第 11 轮一样：AI 只填表、写解释；有模型时由模型理解（国内 DeepSeek，美国 Claude），没有或出错时用规则兜底。"""
import json
import math
import re

NUM = r"(-?\d+(?:\.\d+)?)"
CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "半": 0.5}
# 机械臂关节的中文叫法（UR / Franka 通用的顺序：J1 底座 … J6 末端）
ARM_WORDS = [("底座", 0), ("腰", 0), ("基座", 0), ("大臂", 1), ("肩", 1), ("小臂", 2), ("肘", 2), ("腕1", 3), ("腕一", 3),
             ("腕2", 4), ("腕二", 4), ("腕3", 5), ("腕三", 5), ("手腕", 3)]


def _num(text):
    """“两秒”“3 kg”“0.5 秒” → 数字"""
    m = re.search(NUM, text)
    if m:
        return float(m.group(1))
    for w, v in CN_NUM.items():
        if w in text:
            return float(v)
    return None


def _arm_joint(clause, joints):
    m = re.search(r"[Jj]\s*([1-7])|关节\s*([1-7])", clause)
    if m:
        k = int(m.group(1) or m.group(2)) - 1
        return joints[k] if k < len(joints) else None
    for w, k in ARM_WORDS:
        if w in clause and k < len(joints):
            return joints[k]
    for j in joints:
        if j in clause:
            return j
    return None


def rules_setup(text, model):
    """model = {kind: mech|robot|upload, joints: [名], driver, labels: {名: 中文}, followers: [名], end_body}
    返回网页表单要的 {drives: {关节: {...}}, loads: {关节: 值}, payloads, forces, duration, gravity, notes, unmatched}"""
    joints, labels = model["joints"], model.get("labels") or {}
    out = {"drives": {}, "loads": {}, "payloads": [], "forces": [], "duration": None, "gravity": None, "notes": [], "unmatched": []}
    t = text.replace("：", ":").replace("（", "(").replace("）", ")")
    # 全句：时长、重力
    m = re.search(NUM + r"\s*(?:秒|s\b)", t) or re.search(r"([一两二三四五六七八九十半])\s*秒", t)
    if m:
        out["duration"] = float(m.group(1)) if re.match(NUM, m.group(1)) else float(CN_NUM[m.group(1)])
    if re.search(r"不计重力|没有重力|忽略重力|失重", t):
        out["gravity"] = False
    for clause in [c.strip() for c in re.split(r"[，,；;。\n]", t) if c.strip()]:
        c = clause.replace(" ", "")
        done = False
        # 负载质量
        mk = re.search(NUM + r"\s*(?:kg|公斤|千克)", clause, re.I)
        if mk and model.get("end_body"):
            out["payloads"].append({"body": model["end_body"], "mass": float(mk.group(1)), "y": 100 if model["kind"] == "robot" else 0})
            out["notes"].append("“{}” → 末端负载 {:g} kg（挂在 {}）".format(clause, float(mk.group(1)), model["end_body"]))
            done = True
        if model["kind"] == "mech":
            drv = model["driver"]
            ms = re.search(NUM + r"\s*(?:rpm|r/min|转/分|转每分)", clause, re.I)
            mr = re.search(NUM + r"\s*rad/s", clause)
            if ms or mr:
                rpm = float(ms.group(1)) if ms else float(mr.group(1)) * 60 / (2 * math.pi)
                out["drives"][drv] = {"kind": "speed", "speed": rpm}
                out["notes"].append("“{}” → {} 匀速 {:g} r/min".format(clause, labels.get(drv, drv), rpm))
                done = True
            mf = re.search(NUM + r"\s*(k?)N(?![·.\s]*m)", clause)
            if mf and re.search(r"阻力|负载|载荷|推|拉|力", c):
                F = float(mf.group(1)) * (1000 if mf.group(2) else 1)
                body = next((f for f in model.get("followers", []) if labels.get(f, f) in clause or f in clause), None)
                body = body or ("slider" if "slider" in model.get("bodies", []) else None)
                if body:
                    out["forces"].append({"body": body, "fx": -abs(F), "fz": 0})
                    out["notes"].append("“{}” → {} 上 {:g} N 阻力（与运动方向相反，沿 −X）".format(clause, labels.get(body, body), abs(F)))
                    done = True
            mt = re.search(NUM + r"\s*(k?)\s*N\s*[·.\*]?\s*m", clause, re.I)
            if mt:
                T = float(mt.group(1)) * (1000 if mt.group(2) else 1)
                tgt = next((f for f in model.get("followers", []) if labels.get(f, f) in clause or f in clause), None)
                if tgt is None and model.get("followers"):
                    tgt = model["followers"][-1]                     # “输出轴”等：最后一个从动件
                if tgt:
                    out["loads"][tgt] = -abs(T) if "阻" in c or "负载" in c else T
                    out["notes"].append("“{}” → {} 负载力矩 {:g} N·m".format(clause, labels.get(tgt, tgt), out["loads"][tgt]))
                    done = True
        else:
            j = _arm_joint(clause, joints)
            md = re.search(NUM + r"\s*(?:°|度)", clause)
            if j and md:
                ang = float(md.group(1))
                rel = bool(re.search(r"转|抬|摆|再|增加|加", c)) and not re.search(r"转到|到", c)
                out["drives"][j] = {"kind": "move", "rel": rel, "to": ang}
                out["notes"].append("“{}” → {} 点到点{} {:g}°".format(clause, j, "（相对现在）" if rel else "（转到）", ang))
                done = True
            elif j and re.search(r"不动|保持|锁", c):
                out["drives"][j] = {"kind": "hold"}
                out["notes"].append("“{}” → {} 保持不动".format(clause, j))
                done = True
            elif re.search(r"搬|移到|运到|放到|取", c) and not out["drives"]:
                # 没说具体关节：用示范动作（底座转 90°、大臂抬 30°）
                for k, d in ((0, 90), (1, 30)):
                    if k < len(joints):
                        out["drives"][joints[k]] = {"kind": "move", "rel": True, "to": d}
                out["notes"].append("“{}” → 没说关节角度，用示范动作：{} 转 90°、{} 抬 30°（可在表里改）".format(clause, joints[0], joints[1] if len(joints) > 1 else ""))
                done = True
        if not done and not re.search(r"秒|重力|UR|FR3|机械臂|曲柄滑块|四杆|机构", clause, re.I):
            out["unmatched"].append(clause)
    return out


SETUP_TOOL = {
    "name": "fill_mbd_setup",
    "description": "把一句话变成动力学设置表（只填表，不计算）",
    "input_schema": {"type": "object", "properties": {
        "drives": {"type": "object", "description": "关节名 → {kind: speed|move|sine|hold|torque|free, speed(r/min), to(度), rel(是否相对现在), t0, t1(秒), amp(度), freq(Hz), torque(N·m)}"},
        "loads": {"type": "object", "description": "机构从动件关节名 → 负载力矩 N·m 或力 N（阻力为负）"},
        "payloads": {"type": "array", "items": {"type": "object", "properties": {"body": {"type": "string"}, "mass": {"type": "number"}, "y": {"type": "number"}}}},
        "forces": {"type": "array", "items": {"type": "object", "properties": {"body": {"type": "string"}, "fx": {"type": "number"}, "fz": {"type": "number"}}}},
        "duration": {"type": "number"}, "gravity": {"type": "boolean"},
        "notes": {"type": "array", "items": {"type": "string"}}, "unmatched": {"type": "array", "items": {"type": "string"}}}},
}


def setup(llm, text, model):
    text = (text or "").strip()[:500]
    if not text:
        raise ValueError("请写一句话描述怎么驱动、加什么负载")
    if llm is not None and llm.available():
        got = {}

        def call_tool(name, args):
            got.update(args)
            return {"ok": True}
        system = ("你是机构与机器人动力学助手。根据模型清单把用户的一句话变成驱动和负载设置，调用 fill_mbd_setup 一次。"
                  "转速用 r/min，角度用度，时间用秒；机构只能驱动主动件 {}；机械臂关节按 J1–J6 顺序是 {}；不确定的写进 unmatched，不要猜。").format(
            model.get("driver"), "、".join(model["joints"]))
        try:
            llm.run(system, [{"role": "user", "content": json.dumps({"sentence": text, "model": model}, ensure_ascii=False)}],
                    [SETUP_TOOL], call_tool, max_turns=2)
            if got.get("drives") or got.get("payloads") or got.get("forces") or got.get("loads"):
                ok = set(model["joints"])
                got["drives"] = {k: v for k, v in (got.get("drives") or {}).items() if k in ok}
                got["loads"] = {k: v for k, v in (got.get("loads") or {}).items() if k in ok}
                bodies = set(model.get("bodies") or [])
                for key in ("payloads", "forces"):
                    got[key] = [x for x in got.get(key) or [] if not bodies or x.get("body") in bodies]
                for k in ("notes", "unmatched"):
                    got.setdefault(k, [])
                return dict(got, engine=llm.name)
        except Exception as e:  # noqa: BLE001
            return dict(rules_setup(text, model), engine="rules", note="模型暂时不可用（{}），已用规则理解".format(str(e)[:60]))
    return dict(rules_setup(text, model), engine="rules")


# ---------------------------------------------------------------- 结果解释
def rules_explain(job, labels=None, fixed=()):
    """fixed：没有关节、直接固定在地面上的构件（如机械臂底座），它的“反力”是安装处受力"""
    st, setup = job["stats"], job["setup"]
    labels = labels or {}
    lab = lambda j: labels.get(j, j)  # noqa: E731
    lines, actions = [], []
    drv = [d for d in st["drives"] if d["kind"] != "coupled"]
    if drv:
        big = max(drv, key=lambda d: d["peak"])
        sig = [d for d in drv if d["peak"] >= 0.2 * big["peak"]]          # 只在受力明显的驱动里比较
        top = max(sig, key=lambda d: d["peak"] / max(abs(d["rms"]), 1e-9) if d["rms"] else 0)
        pk = st["peaks"].get("drive." + big["joint"], {})
        lines.append("驱动力矩最大的是{}：峰值 {:.3g}、均方根 {:.3g}（单位 N·m 或 N），出现在第 {:.2f} 秒。".format(
            lab(big["joint"]), big["peak"], big["rms"], pk.get("at_s", 0)))
        if top["rms"] and top["peak"] / top["rms"] > 1.6:
            lines.append("{}的峰值是均方根的 {:.1f} 倍：力矩主要花在加速、减速上（惯性力），峰值出现在加减速段的起止时刻。"
                         "把运动时间放长一些，或加速段占比放大（梯形速度更平缓），峰值会明显下降。".format(lab(top["joint"]), top["peak"] / top["rms"]))
            if any(d.get("kind") == "move" for d in setup.get("drives") or []):
                actions.append({"kind": "retime", "factor": 1.5, "label": "运动时间放长到 1.5 倍重算"})
        else:
            lines.append("峰值与均方根接近：力矩主要用来平衡重力或工作阻力，放慢运动帮助不大，要减小负载、加平衡（配重、弹簧）或换更大的电机和减速器。")
        neg = [d for d in drv if d["power_mean"] < -0.05 * max(d["power_peak"], 1e-9)]
        if neg:
            lines.append("{}的平均功率为负：这段运动里负载在“带着电机走”（下放、制动），电机处于发电状态，驱动器要能吸收回馈能量（制动电阻或能量回馈）。".format(
                "、".join(lab(d["joint"]) for d in neg)))
    rf = [(k[3:-4], v) for k, v in st["peaks"].items() if k.startswith("rf.") and k.endswith(".abs") and "wq_payload" not in k]
    for b, v in [x for x in rf if x[0] in fixed]:
        m = st["peaks"].get("rm.{}.abs".format(b), {})
        lines.append("{}的安装处（与地面、机座的连接）最大受力 {:.4g} N、力矩 {:.4g} N·m：安装螺栓和机座按这个校核。".format(
            lab(b), v["max_abs"], m.get("max_abs", 0)))
    rf = [x for x in rf if x[0] not in fixed]
    if rf:
        b, v = max(rf, key=lambda x: x[1]["max_abs"])
        lines.append("关节反力最大的是{}与上一个构件之间的铰链：{:.4g} N（第 {:.2f} 秒）。轴承、销轴要按这个力校核；".format(
            lab(b), v["max_abs"], v["at_s"]) + "杆件强度可以“送去有限元”算。")
    if (job.get("model") or {}).get("source") == "library":
        lines.append("电机够不够，用“电机选型”按这次的力矩和转速核对（峰值、均方根、转速三项都要满足）。")
    return {"text": "\n".join(lines), "actions": actions, "engine": "rules"}


EXPLAIN_TOOL = {
    "name": "explain",
    "description": "解释动力学结果并给建议",
    "input_schema": {"type": "object", "required": ["text"], "properties": {
        "text": {"type": "string", "description": "3–6 句中文：峰值在什么时刻、为什么（惯性、重力、阻力、机构位置）、对电机和轴承意味着什么、怎么改；不要编造没给的数字"},
        "retime": {"type": "boolean", "description": "是否建议把点到点运动时间放长到 1.5 倍"}}},
}


def explain(llm, job, labels=None, fixed=()):
    base = rules_explain(job, labels, fixed)
    if llm is None or not llm.available():
        return base
    got = {}

    def call_tool(name, args):
        got.update(args)
        return {"ok": True}
    ctx = {"model": job.get("model"), "setup": job["setup"], "drives": job["stats"]["drives"],
           "peaks": {k: v for k, v in job["stats"]["peaks"].items() if k.startswith(("drive.", "rf.")) and k.endswith((".abs",)) or k.startswith("drive.")},
           "labels": labels, "rule_notes": base["text"]}
    try:
        llm.run("你是机械原理与机器人课的老师，给学生解释多体动力学计算结果。只根据给出的数据；调用 explain 一次。",
                [{"role": "user", "content": json.dumps(ctx, ensure_ascii=False, default=str)}], [EXPLAIN_TOOL], call_tool, max_turns=2)
    except Exception:  # noqa: BLE001
        return base
    if not got.get("text"):
        return base
    acts = [{"kind": "retime", "factor": 1.5, "label": "运动时间放长到 1.5 倍重算"}] if got.get("retime") and any(
        d.get("kind") == "move" for d in job["setup"].get("drives") or []) else base["actions"]
    return {"text": got["text"].strip(), "actions": acts, "engine": llm.name}
