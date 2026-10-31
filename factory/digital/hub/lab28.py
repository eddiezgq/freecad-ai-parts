# -*- coding: utf-8 -*-
"""负载跑合台：仿真与实测对比（第 58 轮）——机器人厂“负载跑合”页的接口，与实验 28 的自动评分（60 分）+ 报告（40 分）。

一台 WQ-CR5 的跑合数据都由 sim/runin.py 算（确定性）：做过整机标定的机器人（lab26.robots）才有出厂编号和它装的 6 台关节在测试台上
测得的空载摩擦力矩。“仿真”的力矩用零件库的 WQ-CR5（名义摩擦）——问渠“运动与动力分析”用的是同一个模型。
这台机器人的“真实”摩擦只给老师看。任务成绩编号加前缀 l28_。教材对照：《机器人学》29.4 节、26.4 节。"""
import json

from hub import lab26
from sim import runin as R

TASKS = [
    {"id": "l28_t1", "points": 10, "title": "读实测：肩关节 J2 的峰值力矩",
     "desc": "在“负载跑合”页选你的机器人，看 J2 的实测力矩曲线。标准动作中 J2 力矩绝对值的最大值是多少（N·m）？",
     "hint": "页上的表有每个关节的实测峰值；也可以下载 CSV 自己算。允许差 2%。"},
    {"id": "l28_t2", "points": 10, "title": "比较：哪个关节的仿真与实测差得最多",
     "desc": "仿真（零件库模型，名义摩擦）与实测的力矩之差，按均方根算，哪个关节最大？",
     "hint": "表里“均方根差”一列。"},
    {"id": "l28_t3", "points": 10, "title": "辨识 J1 的摩擦",
     "desc": "用 τ_实测 − τ_刚体 = f_c tanh(θ̇/0.01) + f_v θ̇ 对 J1 做最小二乘（只用 |θ̇| > 0.05 rad/s 的点），填 J1 的库仑摩擦 f_c 和黏性摩擦 f_v。",
     "hint": "页上“辨识”给出结果，报告里写出你自己的计算过程（CSV 里有 τ_刚体）。允许差 5%。"},
    {"id": "l28_t4", "points": 10, "title": "差从哪里来",
     "desc": "对照这台机器人装的关节在测试台上测的空载摩擦力矩，仿真与实测的差主要来自哪一项？",
     "hint": "比一比辨识出的 f_c 与测试台的值，f_v 与名义值。"},
    {"id": "l28_t5", "points": 10, "title": "力矩裕量：这台机器人合格吗",
     "desc": "填 J2 实测力矩的均方根（N·m），并判断整台机器人的力矩裕量是否合格（各关节均方根 ≤ 减速器额定力矩，峰值 ≤ 关节力矩上限）。",
     "hint": "J2 用大关节模组 WQJ-L：谐波 32 号，额定 137 N·m。允许差 3%。"},
    {"id": "l28_t6", "points": 10, "title": "复盘：把辨识结果写回模型",
     "desc": "把辨识出的摩擦写回模型再算一遍，仿真与实测的均方根差变成多少？剩下的差是什么？",
     "hint": "页上“更新模型后的均方根差”一列，和测量噪声比。"},
]
REPORT_POINTS = 40
T4_CHOICES = [
    ("viscous", "主要来自黏性摩擦：测试台只测空载的库仑摩擦，零件库模型的黏性摩擦按名义值，这台机器人的不一样；库仑摩擦与测试台的值一致"),
    ("coulomb", "主要来自库仑摩擦：测试台测得不准"),
    ("inertia", "主要来自连杆的质量和惯量：零件库模型估错了"),
]
T6_CHOICES = [
    ("noise", "降到测量噪声的量级：剩下的是力矩测量噪声，模型已经和这台机器人一致"),
    ("zero", "降到零：辨识后模型完全准确"),
    ("same", "几乎不变：摩擦不是差别的来源"),
]


def robots(db, mode):
    return lab26.robots(db, mode)


def _robot(db, mode, serial):
    r = next((x for x in robots(db, mode) if x["serial"] == serial), None)
    if r is None:
        raise KeyError(serial)
    return r


def case(db, mode, serial, teacher=False):
    r = _robot(db, mode, serial)
    out = R.case(serial, r.get("friction_nm"))
    truth = out.pop("_truth")
    if teacher:
        out["truth"] = truth
    return out


def csv_text(db, mode, serial):
    """跑合数据（50 Hz）：t、各关节 θ̇、实测、仿真、刚体逆动力学（供学生自己做辨识）"""
    c = case(db, mode, serial)
    import numpy as np
    t, Q, QD, QDD = R.motion()
    rig = np.array([R._rigid_torque(q, qd, qdd) for q, qd, qdd in zip(Q, QD, QDD)])[::2]
    S = c["series"]
    head = ["t_s"] + ["qd{}_rad_s".format(i + 1) for i in range(6)] + ["tau_meas{}_Nm".format(i + 1) for i in range(6)] + \
           ["tau_sim{}_Nm".format(i + 1) for i in range(6)] + ["tau_rigid{}_Nm".format(i + 1) for i in range(6)]
    lines = [",".join(head)]
    for k, tk in enumerate(S["t"]):
        row = [tk] + [S["qd"][i][k] for i in range(6)] + [S["meas"][i][k] for i in range(6)] + [S["sim"][i][k] for i in range(6)] + \
              [round(float(rig[k, i]), 3) for i in range(6)]
        lines.append(",".join(str(x) for x in row))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 实验 28
def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def my_robot(db, user, mode="teach"):
    r = _get(db, user, "l28_start")
    ev = (r or {}).get("evidence") or {}
    if isinstance(ev, str):
        ev = json.loads(ev)
    rs = robots(db, mode)
    if ev.get("serial") and any(x["serial"] == ev["serial"] for x in rs):
        return ev["serial"]
    return rs[0]["serial"] if rs else None


def pick(db, user, serial, mode="teach"):
    _robot(db, mode, serial)
    _save(db, user, "l28_start", 0, {"serial": serial})
    return {"serial": serial}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def answer(db, user, tid, ans, mode="teach"):
    serial = my_robot(db, user, mode)
    if serial is None:
        return {"score": 0, "of": 10, "feedback": "还没有做过整机标定的机器人：先接一台 WQ-CR5（实验 24），做到整机标定"}
    c = case(db, mode, serial)
    J = {j["joint"]: j for j in c["joints"]}
    if tid == "l28_t1":
        v = _num(ans.get("peak"))
        if v is None:
            return {"score": 0, "of": 10, "feedback": "填 J2 的峰值力矩（N·m）"}
        want = J["J2"]["peak_meas"]
        s = 10 if abs(v - want) <= 0.02 * want else (5 if abs(v - want) <= 0.1 * want else 0)
        _save(db, user, tid, s, {"serial": serial, "answer": v, "expected": want})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else ("接近了：看实测（不是仿真）那一列。" if s == 5 else "看 J2 实测曲线的最高点（取绝对值）。")}
    if tid == "l28_t2":
        want = max(c["joints"], key=lambda j: j["rms_diff"])["joint"]
        s = 10 if ans.get("joint") == want else 0
        _save(db, user, tid, s, {"serial": serial, "answer": ans.get("joint"), "expected": want})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "看表里“均方根差”一列的最大值。"}
    if tid == "l28_t3":
        fc, fv = _num(ans.get("fc")), _num(ans.get("fv"))
        if fc is None or fv is None:
            return {"score": 0, "of": 10, "feedback": "填 J1 的 f_c（N·m）和 f_v（N·m·s/rad）"}
        w = J["J1"]
        s = (5 if abs(fc - w["fc_hat"]) <= 0.05 * abs(w["fc_hat"]) else 0) + (5 if abs(fv - w["fv_hat"]) <= 0.05 * abs(w["fv_hat"]) else 0)
        _save(db, user, tid, s, {"serial": serial, "answer": [fc, fv], "expected": [w["fc_hat"], w["fv_hat"]]})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "核对：只用 |θ̇| > 0.05 rad/s 的点，两列回归量 tanh(θ̇/0.01) 和 θ̇。"}
    if tid == "l28_t4":
        s = 10 if ans.get("choice") == "viscous" else 0
        _save(db, user, tid, s, {"serial": serial, "answer": ans})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "把辨识出的 f_c 和测试台的值放在一起比，再看 f_v 与名义值。"}
    if tid == "l28_t5":
        v = _num(ans.get("rms"))
        if v is None:
            return {"score": 0, "of": 10, "feedback": "填 J2 实测力矩的均方根（N·m）"}
        want = J["J2"]["rms_meas"]
        s = (5 if abs(v - want) <= 0.03 * want else 0) + (5 if bool(ans.get("pass")) == c["pass"] else 0)
        _save(db, user, tid, s, {"serial": serial, "answer": ans, "expected": [want, c["pass"]]})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "均方根 = √(平均 τ²)；合格要每个关节都满足两条。"}
    if tid == "l28_t6":
        s = 10 if ans.get("choice") == "noise" else 0
        _save(db, user, tid, s, {"serial": serial, "answer": ans})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "更新后的均方根差和测量噪声 σ 比一比。"}
    raise KeyError(tid)


def status(db, user, teacher=False, mode="teach"):
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l28_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "serial": my_robot(db, user, mode), "robots": [x["serial"] for x in robots(db, mode)][:30],
            "t4_choices": [{"value": k, "label": v} for k, v in T4_CHOICES], "t6_choices": [{"value": k, "label": v} for k, v in T6_CHOICES],
            "joints": ["J1", "J2", "J3", "J4", "J5", "J6"]}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l28_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
