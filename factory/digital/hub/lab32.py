# -*- coding: utf-8 -*-
"""实验 32“机壳与关键零件质量异常的追因与 8D”（第 141 轮，缝纫机厂）：五个任务的自动评分（60 分）+ 报告（40 分）。

照实验 25 的做法：老师注入缝纫机厂五种隐藏问题之一（sim/errors.py 的 sand_moist、inoc_fade、hmc_pin、age_tc、ind_coil）→
学生在质量页的控制图上发现判异 → 按精镗那台卧加分组看，问题只在一台卧加，还是所有件一起偏（共用的工序或设备），并说出是哪台设备 →
开 8D、选纠正措施，老师批准后下发车间 → 措施后再做一批全部合格且 Cpk ≥ 1.33 才算有效 → 写 D7、关闭。任务成绩编号加前缀 l32_。"""
import json

from factory import data as F
from sim import errors as ERR

TASKS = [
    {"id": "l32_t1", "points": 10, "title": "在控制图上发现判异",
     "desc": "老师注入问题后，车间接着做铸件、机壳和轴（老师或计划员接几张平缝机、包缝机的单，或直接下铸件、机壳、上轴的工单）。在“质量”页逐个看铸件、机壳、轴的特性，找出数据出了问题的那一个，说出触发的是哪条判异规则。",
     "hint": "判异规则 1：1 点出 3σ；2：连续 3 点中 2 点在 2σ 外同侧；3：连续 5 点中 4 点在 1σ 外同侧；4：连续 8 点在中心线同侧。σ 按清单里的过程散布。"},
    {"id": "l32_t2", "points": 15, "title": "分层找原因",
     "desc": "机壳的测量记着精镗用的哪台卧加，可以按卧加分组看均值。问题只出在某一台卧加镗的机壳上，还是所有件随时间一起偏（原因在大家共用的工序或设备上：混砂、浇注孕育、时效炉、高频淬火）？再说出是哪台设备。",
     "hint": "分层：按可能的原因把数据分开比。只在一组里偏 → 原因在那一台；所有组一起偏 → 原因在共用的上游工序。设备编号在“设备”页能查（如 hmc-3、mix-1、pour-1、age-1、ihd-1）。"},
    {"id": "l32_t3", "points": 10, "title": "开 8D",
     "desc": "为出问题的特性开一张质量异常单，写 D1–D4（D2 写数据：哪些件、偏多少；D4 写分层得出的原因）。",
     "hint": "在“质量”页先在控制图上选中这个特性，再点“为当前特性开单”。"},
    {"id": "l32_t4", "points": 15, "title": "选对措施并用数据验证",
     "desc": "D5 从措施清单里选一项提交，老师批准后下发车间。车间再做一批后点“验证”：全部合格且 Cpk ≥ 1.33 才算有效。",
     "hint": "只有对症的措施能让数据恢复。放宽公差、三坐标全检、返镗这类措施，治不了根本原因。铸件气孔这类问题，8D 开在缺陷本身（气孔数）上，验证看措施后还有没有不合格。"},
    {"id": "l32_t5", "points": 10, "title": "写 D7、关闭",
     "desc": "写 D7 预防再发生：改了哪些工艺文件、加了什么防错（比如型砂水分在线监测与实验室比对、孕育剂保管规定、夹具定位销定期更换与首件三坐标、时效炉热电偶定期校准、感应器使用次数记录与首件剖检），然后关闭 8D。",
     "hint": "8D 要验证有效、写了 D7 才能关闭。"},
]
REPORT_POINTS = 40
CHAR_OF = {"sand_moist": "cast_moist", "inoc_fade": "cast_hb", "hmc_pin": "hs_pos", "age_tc": "hs_coax_up", "ind_coil": "ls_hrc"}
# 8D 可以开在哪些特性上：型砂含水是型砂实验室的过程参数（示例能力 Cpk 正好 1.33，验证不稳），措施效果看铸件气孔数（计数型，措施后没有不合格即有效）
EIGHT_D_ON = {"sand_moist": ("cast_pores", "cast_moist")}
LAYER_OF = {"sand_moist": "shared", "inoc_fade": "shared", "hmc_pin": "station", "age_tc": "shared", "ind_coil": "shared"}
LAYERS = [("station", "只在某一台卧加镗的机壳上"), ("shared", "所有件一起偏（共用的工序或设备）")]
PREFIX = ("CAST-", "HSG-", "LS-", "OL-")


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def start(db, user):
    if not _get(db, user, "l32_start"):
        _save(db, user, "l32_start", 0, {})


def locked(db, u, anomaly_id=None):
    return False


def current_problem(db):
    """最近一次注入的缝纫机厂问题（清除了也算：学生可能在措施之后才答）"""
    r = db.one("select * from quality_problem where mode='teach' and problem = any(%s) order by injected_at desc limit 1",
               (list(CHAR_OF),))
    return dict(r) if r else None


def _spec(item, code):
    for (it, _op), chars in list(F.MEASURE.items()) + list(_sampling()):
        if it == item:
            for c in chars:
                if c["code"] == code:
                    return c
    return None


def part_rows(db, limit=20000):
    return [m["data"] for m in db.messages(["quality.measurement"], mode="teach", order="asc", limit=limit)
            if str(m["data"].get("item", "")).startswith(PREFIX)]


def signals(db, item, code, last=40):
    from hub import spc
    c = _spec(item, code)
    v = [d["value_mm"] for d in part_rows(db) if d["item"] == item and d["characteristic"] == code][-last:]
    if not c or len(v) < 3:
        return []
    return spc.special_causes(v, c["nominal"], c["sigma"])


def groups(db, item, code, by):
    """分层：按精镗那台卧加分组的件数、均值、超差数"""
    key = {"station": "assembled_on"}.get(by)
    out = {}
    for d in part_rows(db):
        if d["item"] != item or d["characteristic"] != code:
            continue
        g = d.get(key) if key else None
        if not g:
            continue
        x = out.setdefault(g, {"n": 0, "sum": 0.0, "fails": 0})
        x["n"] += 1
        x["sum"] += d["value_mm"]
        x["fails"] += d["result"] == "fail"
    return {g: {"n": x["n"], "mean": round(x["sum"] / x["n"], 4), "fails": x["fails"]} for g, x in sorted(out.items())}


def answer(db, user, tid, ans):
    start(db, user)
    p = current_problem(db)
    if tid == "l32_t1":
        if not p:
            return {"score": 0, "of": 10, "feedback": "老师还没注入问题"}
        sel = str(ans.get("characteristic") or "")
        item, _, code = sel.partition("|")
        s = 0
        if code == CHAR_OF[p["problem"]]:
            s += 6
            rules = {x["rule"] for x in signals(db, item, code)}
            try:
                if int(ans.get("rule") or 0) in rules:
                    s += 4
            except ValueError:
                pass
        _save(db, user, tid, s, {"answer": ans, "expected_char": CHAR_OF[p["problem"]]})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else
                ("特性找对了，但这条规则在最近的数据上没有触发。" if s == 6 else "再看看别的特性：哪一个的点子一路偏向一边？")}
    if tid == "l32_t2":
        if not p:
            return {"score": 0, "of": 10, "feedback": "老师还没注入问题"}
        exp = LAYER_OF[p["problem"]]
        by = ans.get("by")
        s = 0
        if by == exp:
            s = 10
            val = str(ans.get("group") or "").strip().lower()
            s += 5 if val == ERR.PROBLEMS[p["problem"]]["unit"] else 0
        _save(db, user, tid, s, {"answer": ans, "expected": exp})
        return {"score": s, "of": 15, "feedback": "正确。" if s == 15 else
                ("分层的方向对了，具体是哪一台设备再核对一下。" if s == 10 else "再按卧加分开比一比各组的均值：只有一台偏，还是大家一起偏？")}
    raise KeyError(tid)


def _my_8d(db, user, problem):
    from hub.privacy import is_me
    codes = list(EIGHT_D_ON.get(problem, (CHAR_OF[problem],)))
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
            _save(db, user, "l32_t3", 4 + 6 * len(done) // 4, {"q8d": mine[-1]["id"], "written": done})
            fix = ERR.PROBLEMS[p["problem"]]["fix"]
            ok = [s for s in mine if s.get("fix") == fix and s["status"] in ("approved", "closed")]
            if ok:
                eff = any((s.get("verify") or {}).get("effective") for s in ok)
                _save(db, user, "l32_t4", 15 if eff else 8, {"q8d": ok[-1]["id"], "fix": fix, "effective": eff})
                if any(s["status"] == "closed" for s in ok):
                    _save(db, user, "l32_t5", 10, {"q8d": ok[-1]["id"]})
            elif any(s.get("fix") and s["status"] in ("approved", "closed") for s in mine):
                _save(db, user, "l32_t4", 3, {"note": "措施不对症"})
    return status(db, user)


def status(db, user, teacher=False):
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l32_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    chars = [{"value": "{}|{}".format(it, c["code"]), "label": "{} · {}".format(it, c["name"])}
             for (it, _op), cs in list(F.MEASURE.items()) + list(_sampling()) if it.startswith(PREFIX) for c in cs
             if c.get("sigma")]
    p = current_problem(db)
    out = {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
           "report_points": REPORT_POINTS, "injected": bool(p), "characteristics": chars, "rules": [1, 2, 3, 4],
           "layers": [{"value": k, "label": t} for k, t in LAYERS]}
    if teacher:
        out["problem"] = p and {"problem": p["problem"], "name": ERR.PROBLEMS[p["problem"]]["name"], "injected_at": p["injected_at"],
                                "cleared_at": p.get("cleared_at")}
        out["inject_kinds"] = [{"value": k, "label": ERR.PROBLEMS[k]["name"]} for k in CHAR_OF]
    return out


def strata(db, sel):
    """实验 32 页的分层表：某特性按精镗那台卧加分组（只有机壳有）"""
    item, _, code = str(sel).partition("|")
    return {"station": groups(db, item, code, "station")}


def inject(db, send, u, kind):
    from hub import qproblem
    if u["mode"] != "teach" or not u.get("teacher"):
        raise PermissionError("只有教学模式的老师能注入问题")
    if kind in (None, "", "random"):
        import random
        kind = random.choice(list(CHAR_OF))
    if kind not in CHAR_OF:
        raise ValueError("没有这个问题：" + str(kind))
    qproblem.inject(db, send, "teach", u["name"], kind)
    return {"problem": kind, "text": "已注入：{}。学生看不到是哪一种，只能从数据里找。".format(ERR.PROBLEMS[kind]["name"])}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l32_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]


def _sampling():
    """计量室抽检特性（第 138 轮）也能选：(物料, 抽检之后的工序) → 特性"""
    for (it, after), rules in (getattr(F, "SAMPLING", None) or {}).items():
        yield (it, after), [dict(c, name=c["name"] + "（计量室抽检）") for r in rules for c in r.get("chars", [])]
