# -*- coding: utf-8 -*-
"""质量追因与 8D 实验的通用实现（第 147 轮，照实验 25、32）：一座厂写一份配置，就有一个实验——
老师注入本厂的隐藏问题 → 学生在控制图上发现判异 → 按设备分层（只在某一台上偏，还是所有件一起偏）并说出是哪台设备 →
开 8D、选措施、老师批准 → 措施后再做一批全部合格且 Cpk ≥ 1.33 才算有效 → 写 D7、关闭。

用法（实验模块里）：
    from hub import labq
    globals().update(labq.build(CFG))
CFG 键：no（实验号）、items（物料编号前缀，元组）、problems（{问题: (特性代号, 分层 "station"/"shared")}）、
station（分层表的说明，如“按绕线机”）、station_layer（“只在某一台……”的选项文字）、eight_d_on（可选，{问题: (特性, …)}）、
t1_desc、t2_desc、t2_hint、t4_hint、t5_desc（任务文字，各厂自己写）。
第 148 轮：layers（可选，默认 ("station", "shared")）可以加 "lot"（来料批次：测量记录里的 lot 字段，如电路板厂的采样电阻卷号），
配 lot（批次表的说明）、lot_layer（选项文字）；分层答“批次”时，说出的那一批均值偏离名义值超过 3σ 就算对。
第 152 轮：problems 的特性可以写元组（一种问题让几项特性一起偏，任务 1 答哪一项都对，8D 开在哪一项上都认；第一项是主特性）；
chart="xbar"（演示工厂）：判异按“质量”页的均值–极差图（spc.for_characteristic），特性清单取 sim/errors.py 的 CHARS（计数型不列）。"""
import json
import random

from factory import data as F
from sim import errors as ERR

RULE_HINT = "判异规则 1：1 点出 3σ；2：连续 3 点中 2 点在 2σ 外同侧；3：连续 5 点中 4 点在 1σ 外同侧；4：连续 8 点在中心线同侧。σ 按清单里的过程散布。"
SHARED_LAYER = "所有件一起偏（共用的工序或设备）"


def build(cfg):
    no = cfg["no"]
    pre = "l{}_".format(no)
    items = tuple(cfg["items"])
    chars_of = {k: (tuple(v[0]) if isinstance(v[0], (tuple, list)) else (v[0],)) for k, v in cfg["problems"].items()}
    char_of = {k: v[0] for k, v in chars_of.items()}
    xbar = cfg.get("chart") == "xbar"
    layer_of = {k: v[1] for k, v in cfg["problems"].items()}
    eight_d_on = cfg.get("eight_d_on") or {}
    tasks = [
        {"id": pre + "t1", "points": 10, "title": "在控制图上发现判异", "desc": cfg["t1_desc"], "hint": RULE_HINT},
        {"id": pre + "t2", "points": 15, "title": "分层找原因", "desc": cfg["t2_desc"], "hint": cfg["t2_hint"]},
        {"id": pre + "t3", "points": 10, "title": "开 8D",
         "desc": "为出问题的特性开一张质量异常单，写 D1–D4（D2 写数据：哪些件、偏多少；D4 写分层得出的原因）。",
         "hint": "在“质量”页先在控制图上选中这个特性，再点“为当前特性开单”。"},
        {"id": pre + "t4", "points": 15, "title": "选对措施并用数据验证",
         "desc": "D5 从措施清单里选一项提交，老师批准后下发车间。车间再做一批后点“验证”：全部合格且 Cpk ≥ 1.33 才算有效。",
         "hint": cfg["t4_hint"]},
        {"id": pre + "t5", "points": 10, "title": "写 D7、关闭", "desc": cfg["t5_desc"], "hint": "8D 要验证有效、写了 D7 才能关闭。"},
    ]
    layer_text = {"station": cfg.get("station_layer"), "shared": SHARED_LAYER, "lot": cfg.get("lot_layer")}
    layers = [(k, layer_text[k]) for k in cfg.get("layers", ("station", "shared"))]

    def _save(db, user, tid, score, evidence):
        db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
             "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
             "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))

    def start(db, user):
        if not db.one("select 1 from task_result where user_name=%s and task_id=%s", (user, pre + "start")):
            _save(db, user, pre + "start", 0, {})

    def locked(db, u, anomaly_id=None):
        return False

    def current_problem(db):
        """最近一次注入的本实验问题（清除了也算：学生可能在措施之后才答）"""
        r = db.one("select * from quality_problem where mode='teach' and problem = any(%s) order by injected_at desc limit 1",
                   (list(char_of),))
        return dict(r) if r else None

    def _spec(item, code):
        for (it, _op), chars in F.MEASURE.items():
            if it == item:
                for c in chars:
                    if c["code"] == code:
                        return c
        return None

    def part_rows(db, limit=20000):
        return [m["data"] for m in db.messages(["quality.measurement"], mode="teach", order="asc", limit=limit)
                if str(m["data"].get("item", "")).startswith(items)]

    def signals(db, item, code, last=40):
        from hub import spc
        if xbar:
            return spc.for_characteristic(db, "teach", item, code).get("signals") or []
        c = _spec(item, code)
        v = [d["value_mm"] for d in part_rows(db) if d["item"] == item and d["characteristic"] == code][-last:]
        if not c or len(v) < 3:
            return []
        return spc.special_causes(v, c["nominal"], c["sigma"])

    def groups(db, item, code, field="assembled_on"):
        """分层：按设备（测量里记的 assembled_on）或来料批次（lot）分组的件数、均值、超差数"""
        out = {}
        for d in part_rows(db):
            if d["item"] != item or d["characteristic"] != code or not d.get(field):
                continue
            x = out.setdefault(d[field], {"n": 0, "sum": 0.0, "fails": 0})
            x["n"] += 1
            x["sum"] += d["value_mm"]
            x["fails"] += d["result"] == "fail"
        return {g: {"n": x["n"], "mean": round(x["sum"] / x["n"], 4), "fails": x["fails"]} for g, x in sorted(out.items())}

    def answer(db, user, tid, ans):
        start(db, user)
        p = current_problem(db)
        if tid == pre + "t1":
            if not p:
                return {"score": 0, "of": 10, "feedback": "老师还没注入问题"}
            item, _, code = str(ans.get("characteristic") or "").partition("|")
            s = 0
            if code in chars_of[p["problem"]]:
                s += 6
                try:
                    if int(ans.get("rule") or 0) in {x["rule"] for x in signals(db, item, code)}:
                        s += 4
                except ValueError:
                    pass
            _save(db, user, tid, s, {"answer": ans, "expected_char": char_of[p["problem"]]})
            return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else
                    ("特性找对了，但这条规则在最近的数据上没有触发。" if s == 6 else "再看看别的特性：哪一个的点子一路偏向一边？")}
        if tid == pre + "t2":
            if not p:
                return {"score": 0, "of": 15, "feedback": "老师还没注入问题"}
            s = 0
            if ans.get("by") == layer_of[p["problem"]]:
                s = 10 + (5 if _group_ok(db, p["problem"], str(ans.get("group") or "").strip()) else 0)
            _save(db, user, tid, s, {"answer": ans, "expected": layer_of[p["problem"]]})
            return {"score": s, "of": 15, "feedback": "正确。" if s == 15 else
                    ("分层的方向对了，具体是哪一台设备（哪一批来料）再核对一下。" if s == 10 else "再按设备分开比一比各组的均值：只有一台偏，还是大家一起偏？")}
        raise KeyError(tid)

    def _group_ok(db, problem, group):
        if layer_of[problem] != "lot":
            return group.lower() == ERR.PROBLEMS[problem]["unit"]
        code = char_of[problem]       # 来料批次：说出的那一批（任一件物料上）均值偏离名义值超过 3σ
        for (it, _op), cs in F.MEASURE.items():
            c = next((c for c in cs if c["code"] == code), None) if it.startswith(items) else None
            g = c and groups(db, it, code, "lot").get(group.upper())
            if g and abs(g["mean"] - c["nominal"]) > 3 * c["sigma"]:
                return True
        return False

    def _my_8d(db, user, problem):
        from hub.privacy import is_me
        codes = list(eight_d_on.get(problem, chars_of[problem]))
        rows = db.q("select * from quality_8d where mode='teach' and characteristic = any(%s) order by created_at", (codes,))
        return [dict(r) for r in rows if is_me(r["author"], user)]

    def check(db, user):
        """自动检查任务 3、4、5（看 8D 单）"""
        start(db, user)
        p = current_problem(db)
        if p:
            mine = _my_8d(db, user, p["problem"])
            if mine:
                done = [k for k in ("d1", "d2", "d3", "d4") if (mine[-1]["d"] or {}).get(k)]
                _save(db, user, pre + "t3", 4 + 6 * len(done) // 4, {"q8d": mine[-1]["id"], "written": done})
                fix = ERR.PROBLEMS[p["problem"]]["fix"]
                ok = [s for s in mine if s.get("fix") == fix and s["status"] in ("approved", "closed")]
                if ok:
                    eff = any((s.get("verify") or {}).get("effective") for s in ok)
                    _save(db, user, pre + "t4", 15 if eff else 8, {"q8d": ok[-1]["id"], "fix": fix, "effective": eff})
                    if any(s["status"] == "closed" for s in ok):
                        _save(db, user, pre + "t5", 10, {"q8d": ok[-1]["id"]})
                elif any(s.get("fix") and s["status"] in ("approved", "closed") for s in mine):
                    _save(db, user, pre + "t4", 3, {"note": "措施不对症"})
        return status(db, user)

    def status(db, user, teacher=False):
        rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like %s", (user, pre + "%"))}
        out_tasks = []
        for t in tasks:
            r = rows.get(t["id"])
            out_tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
        if xbar:
            chars = [{"value": "{}|{}".format(it, code), "label": "{} · {}".format(it, name)}
                     for it in items for code, name, _nom, lo, hi in ERR.CHARS if hi > lo]
        else:
            chars = [{"value": "{}|{}".format(it, c["code"]), "label": "{} · {}".format(it, c["name"])}
                     for (it, _op), cs in F.MEASURE.items() if it.startswith(items) for c in cs if c.get("sigma")]
        p = current_problem(db)
        out = {"user": user, "no": no, "title": cfg["title"], "tasks": out_tasks, "score": sum(t["score"] for t in out_tasks), "of": sum(t["points"] for t in tasks),
               "report_points": 40, "injected": bool(p), "characteristics": chars, "rules": [1, 2, 3, 4],
               "layers": [{"value": k, "label": t} for k, t in layers], "station": cfg.get("station"), "lot": cfg.get("lot"),
               "group_label": cfg.get("group_label")}
        if teacher:
            out["problem"] = p and {"problem": p["problem"], "name": ERR.PROBLEMS[p["problem"]]["name"], "injected_at": p["injected_at"],
                                    "cleared_at": p.get("cleared_at")}
            out["inject_kinds"] = [{"value": k, "label": ERR.PROBLEMS[k]["name"]} for k in char_of]
        return out

    def strata(db, sel):
        item, _, code = str(sel).partition("|")
        keys = [k for k, _ in layers]
        out = {"station": groups(db, item, code)} if "station" in keys else {}
        if "lot" in keys:
            out["lot"] = groups(db, item, code, "lot")
        return out

    def inject(db, send, u, kind):
        from hub import qproblem
        if u["mode"] != "teach" or not u.get("teacher"):
            raise PermissionError("只有教学模式的老师能注入问题")
        if kind in (None, "", "random"):
            kind = random.choice(list(char_of))
        if kind not in char_of:
            raise ValueError("没有这个问题：" + str(kind))
        qproblem.inject(db, send, "teach", u["name"], kind)
        return {"problem": kind, "text": "已注入：{}。学生看不到是哪一种，只能从数据里找。".format(ERR.PROBLEMS[kind]["name"])}

    def class_view(db):
        rows = db.q("select user_name, task_id, score from task_result where task_id like %s", (pre + "t%",))
        out = {}
        for r in rows:
            out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
        return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]

    return {"TASKS": tasks, "REPORT_POINTS": 40, "CHAR_OF": char_of, "CHARS_OF": chars_of, "LAYER_OF": layer_of, "LAYERS": layers,
            "start": start, "locked": locked, "current_problem": current_problem, "signals": signals, "groups": groups,
            "answer": answer, "check": check, "status": status, "strata": strata, "inject": inject, "class_view": class_view}
