# -*- coding: utf-8 -*-
"""整机运动学标定（第 55 轮）：机器人厂“整机标定”页的接口，与实验 26“一台协作机器人的运动学标定”的自动评分（60 分）+ 报告（40 分）。

一台 WQ-CR5 的标定都由 sim/calib.py 算（确定性：同一出厂编号、同样的关节零位、同样的位姿选法，结果一样）。
仿真车间在整机标定工位算出“标定后绝对定位误差”，测量消息带上这台机器人 6 台关节的零位残差；页面、实验按这些数重新算一遍，
可以换位姿（数量、铺满 / 集中）重新辨识。机器人的“真实”偏差只给老师看（讲评用）。任务成绩编号加前缀 l26_。"""
import json
import math

import numpy as np

from sim import calib as C

ITEM = "WQ-CR5"
TASKS = [
    {"id": "l26_t1", "points": 10, "title": "用名义 DH 参数算末端位置",
     "desc": "实验页给出一组关节角。用名义 DH 参数（表在页上）逐个关节乘变换矩阵，算工具点在基座坐标系里的位置 x、y、z（mm），填上。",
     "hint": "T = Rz(θ)·Tz(d)·Tx(a)·Rx(α)，六个相乘，再乘工具点 [50, 0, 100, 1]ᵀ（mm）。允许差 0.5 mm。"},
    {"id": "l26_t2", "points": 10, "title": "选测量位姿：铺满与集中",
     "desc": "在“整机标定”页对你这台机器人各做一次：30 个位姿铺满工作空间、30 个位姿集中在常用姿态附近。哪一种条件数大？",
     "hint": "条件数 = 最大奇异值 / 最小（有效）奇异值。条件数大，测量噪声被放大到参数里。"},
    {"id": "l26_t3", "points": 10, "title": "辨识：哪两个关节零位偏得最多",
     "desc": "用 30 个铺满的位姿辨识。看参数偏差表，零位 Δθ 绝对值最大的是哪两个关节？",
     "hint": "看 Δθ 一列的绝对值。"},
    {"id": "l26_t4", "points": 10, "title": "验证：这台机器人合格吗",
     "desc": "另取 20 个位姿验证。填标定后的平均绝对定位误差（mm），判断合格与否（≤ 0.5 mm 合格）。",
     "hint": "看验证位姿的“标定后”一列的平均值。"},
    {"id": "l26_t5", "points": 10, "title": "位姿少了会怎样",
     "desc": "用 8 个铺满的位姿再辨识一次，与 30 个比，验证误差怎样变化？为什么？",
     "hint": "参数有 24 个、每个位姿只给 3 个方程；有几个组合本来就分不开。"},
    {"id": "l26_t6", "points": 10, "title": "复盘：零位偏差从哪来",
     "desc": "整机的关节零位偏差主要从哪里来？如果关节测试台的零位标定程序漂了，整机标定会看到什么？",
     "hint": "实验 25 的第三种隐藏问题。"},
]
REPORT_POINTS = 40
T5_CHOICES = [
    ("worse_ill", "验证误差变大：位姿少，方程勉强够，条件数变大，噪声和几何以外的误差被放大进参数"),
    ("same", "没有变化：参数只有 24 个，8 个位姿已经有 24 个方程"),
    ("better", "变小：位姿少，测量误差也少"),
]
T6_CHOICES = [
    ("bench", "关节测试台的零位标定残差；测试台零位漂了，辨识出的各关节零位偏差会一起偏同一个量"),
    ("gear", "谐波减速器的背隙"),
    ("tracker", "激光跟踪仪的测量噪声"),
]


# ---------------------------------------------------------------- 机器人与标定
def robots(db, mode, limit=200):
    """做过整机标定的机器人（最新在前）：出厂编号、工单、标定前 / 后误差、合格与否、6 台关节的零位残差"""
    out, seen = [], set()
    for m in db.messages(["quality.measurement"], mode=mode, order="desc", limit=4000):
        d = m["data"]
        if d.get("item") != ITEM or d.get("characteristic") != "cr_abs" or d["part_serial"] in seen:
            continue
        seen.add(d["part_serial"])
        c = d.get("calib") or {}
        out.append({"serial": d["part_serial"], "work_order": d.get("work_order"), "ts": m.get("ts"), "after_mm": d["value_mm"],
                    "before_mm": c.get("before_mm"), "cond": c.get("cond"), "pass": d.get("result") == "pass",
                    "zero_arcsec": c.get("zero_arcsec")})
        if len(out) >= limit:
            break
    return out


def zeros_of(db, mode, serial):
    r = next((x for x in robots(db, mode) if x["serial"] == serial), None)
    if r is None:
        raise KeyError(serial)
    return r["zero_arcsec"]


def case(db, mode, serial, n=C.N_DEFAULT, spread="full", teacher=False):
    n = int(n)
    if not 6 <= n <= 80:
        raise ValueError("位姿数在 6–80 之间")
    if spread not in ("full", "cluster"):
        raise ValueError("位姿分布：full 铺满 / cluster 集中")
    out = C.case(serial, zeros_of(db, mode, serial), n, spread, detail=True)
    truth = out.pop("_truth")
    if teacher:
        out["truth"] = truth
    return out


def nominal():
    return {"dh": [{"joint": j, "a_mm": round(x["a"] * 1000, 3), "alpha_deg": round(math.degrees(x["alpha"]), 3), "d_mm": round(x["d"] * 1000, 3)}
                   for j, x in zip(C.JOINTS, C.NOMINAL)],
            "tool_mm": [round(v * 1000, 3) for v in C.TOOL], "sigma": {"tracker_mm": C.SIG_TRACKER * 1000, "unmodeled_mm": C.SIG_UNMODELED * 1000},
            "limit_mm": C.LIMIT_MM, "params": C.NP, "rank": C.structural_rank()}


# ---------------------------------------------------------------- 实验 26
def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def my_robot(db, user, mode="teach"):
    """学生选的那台（没选就是最近标定的一台）"""
    r = _get(db, user, "l26_start")
    ev = (r or {}).get("evidence") or {}
    if isinstance(ev, str):
        ev = json.loads(ev)
    rs = robots(db, mode)
    if ev.get("serial") and any(x["serial"] == ev["serial"] for x in rs):
        return ev["serial"]
    return rs[0]["serial"] if rs else None


def pick(db, user, serial, mode="teach"):
    if not any(x["serial"] == serial for x in robots(db, mode)):
        raise KeyError(serial)
    _save(db, user, "l26_start", 0, {"serial": serial})
    return {"serial": serial}


def fk_question(serial):
    """任务 1 的关节角（按出厂编号定，每台不一样）"""
    q = C.poses((serial, "lab26-fk"), 1, "full")[0]
    return [round(math.degrees(x), 1) for x in q]


def note_try(db, user, serial, n, spread, res):
    """学生在“整机标定”页做过的辨识（任务 2、5 的依据）"""
    r = _get(db, user, "l26_tries")
    ev = (r or {}).get("evidence") or {}
    if isinstance(ev, str):
        ev = json.loads(ev)
    ev["{}|{}|{}".format(serial, n, spread)] = {"cond": res["cond"], "after_mm": res["after_mean_mm"]}
    _save(db, user, "l26_tries", 0, ev)


def _tries(db, user):
    r = _get(db, user, "l26_tries")
    ev = (r or {}).get("evidence") or {}
    return json.loads(ev) if isinstance(ev, str) else ev


def answer(db, user, tid, ans, mode="teach"):
    serial = my_robot(db, user, mode)
    if serial is None:
        return {"score": 0, "of": 10, "feedback": "还没有标定过的机器人：先接一台 WQ-CR5，做到整机标定"}
    z = zeros_of(db, mode, serial)
    if tid == "l26_t1":
        qd = fk_question(serial)
        want = C.fk([math.radians(x) for x in qd]) * 1000
        try:
            got = np.array([float(ans[k]) for k in ("x", "y", "z")])
        except (KeyError, TypeError, ValueError):
            return {"score": 0, "of": 10, "feedback": "填 x、y、z（mm）"}
        err = float(np.linalg.norm(got - want))
        s = 10 if err <= 0.5 else (5 if err <= 5 else 0)
        _save(db, user, tid, s, {"serial": serial, "q_deg": qd, "answer": got.tolist(), "err_mm": round(err, 3)})
        return {"score": s, "of": 10, "feedback": "正确（差 {:.2f} mm）。".format(err) if s == 10 else
                ("差 {:.1f} mm：大方向对了，检查一下符号或某个关节的 a、d。".format(err) if s == 5 else "差得较多：先核对第一个关节的变换。")}
    if tid == "l26_t2":
        tr = _tries(db, user)
        full, clus = tr.get("{}|30|full".format(serial)), tr.get("{}|30|cluster".format(serial))
        s = 0
        if full and clus:
            s += 5
            if ans.get("larger") == ("cluster" if clus["cond"] > full["cond"] else "full"):
                s += 5
        _save(db, user, tid, s, {"serial": serial, "answer": ans, "full": full, "cluster": clus})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else ("两种都做了，再比一比条件数。" if s == 5 else
                                                                         "先在“整机标定”页对这台机器人各做一次：30 个铺满、30 个集中。")}
    if tid == "l26_t3":
        res = C.case(serial, z, C.N_DEFAULT, "full", detail=True)
        top = sorted(res["identified"], key=lambda r: -abs(r["dtheta_deg"]))[:2]
        want = {r["joint"] for r in top}
        got = set(ans.get("joints") or [])
        s = 10 if got == want else (5 if len(got & want) == 1 and len(got) <= 2 else 0)
        _save(db, user, tid, s, {"serial": serial, "answer": sorted(got), "expected": sorted(want)})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else ("对了一个。" if s == 5 else "看参数偏差表里零位 Δθ 的绝对值。")}
    if tid == "l26_t4":
        res = C.case(serial, z)
        try:
            v = float(ans.get("after_mm"))
        except (TypeError, ValueError):
            return {"score": 0, "of": 10, "feedback": "填标定后的平均误差（mm）"}
        s = (5 if abs(v - res["after_mean_mm"]) <= 0.02 else 0) + (5 if bool(ans.get("pass")) == res["pass"] else 0)
        _save(db, user, tid, s, {"serial": serial, "answer": ans, "after_mm": res["after_mean_mm"], "pass": res["pass"]})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "核对验证位姿“标定后”一列的平均值，和 0.5 mm 比。"}
    if tid == "l26_t5":
        tr = _tries(db, user)
        tried = bool(tr.get("{}|8|full".format(serial)))
        s = (5 if tried else 0) + (5 if ans.get("choice") == "worse_ill" else 0)
        _save(db, user, tid, s, {"serial": serial, "answer": ans, "tried8": tried})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else ("先在“整机标定”页用 8 个铺满的位姿辨识一次。" if not tried else
                                                                         "再想想：方程数刚够时，噪声怎样传到参数里？")}
    if tid == "l26_t6":
        s = 10 if ans.get("choice") == "bench" else 0
        _save(db, user, tid, s, {"answer": ans})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "关节在装进整机之前，零位是在哪里标定的？"}
    raise KeyError(tid)


def status(db, user, teacher=False, mode="teach"):
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l26_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    serial = my_robot(db, user, mode)
    out = {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
           "report_points": REPORT_POINTS, "serial": serial, "robots": [x["serial"] for x in robots(db, mode)][:30],
           "fk_q_deg": fk_question(serial) if serial else None, "nominal": nominal(),
           "t5_choices": [{"value": k, "label": v} for k, v in T5_CHOICES], "t6_choices": [{"value": k, "label": v} for k, v in T6_CHOICES],
           "joints": list(C.JOINTS)}
    return out


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l26_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
