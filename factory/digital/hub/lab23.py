# -*- coding: utf-8 -*-
"""实验 23“两周情景：一张急单的全厂决策”（第 19 轮 J-7）：两周课程设计，4–6 人一组，每人一个角色。
老师在“情景导演”里一幕一幕地放；组里该谁处理谁做决定、发起动作，厂长（老师）批准；最后复盘。

自动评分 60 分（按平台里的事实），报告 40 分（老师在课程里批改）：
- l23_t1 组队与角色（5）：登记小组和自己的角色；
- l23_t2 每幕的决定（25）：第 2–8 幕每幕一个小组决定（选方案 + 理由），要由这一幕该负责的角色提交；
  每幕：下一幕开演之前交 40%、和中枢推荐一致 40%（选了别的处理方案 20%）、理由写到点子上 20%；全组同分；
- l23_t3 发起动作（10）：组员针对这一幕的异常发起了动作（执行了算满，提交待批算一半）；全组同分；
- l23_t4 复盘（20）：这张订单的毛利率（差 1 个百分点以内 8）、哪一幕记到订单上的钱最多（7）、动作费用合计（差 5% 以内 5）。
比对模式：开始实验后，某一幕本组还没交决定，这一幕的异常在指挥台上不显示建议，AI 只给提示。任务编号前缀 l23_。"""
import json

TASKS = [
    {"id": "l23_t1", "points": 5, "title": "组队与分角色",
     "desc": "填小组名和你的角色。4–6 人一组；计划员、质量、班组长、安全员、维修各至少一人（人少的组一人兼两个角色，用“兼”的角色再登记一次）。",
     "hint": "右上角的角色要和登记的一致：轮到你的幕，用这个角色做决定、发起动作。"},
    {"id": "l23_t2", "points": 25, "title": "每一幕的决定",
     "desc": "老师每放一幕，厂情中枢出一个异常。由这一幕该负责的角色，在下面打开这一幕、看方案（推演结果），代表小组选一个方案、写理由，在下一幕开演之前提交。",
     "hint": "看清每个方案多花多少钱、交期变不变、风险在哪；理由里写代价。提交以后指挥台才显示中枢的建议。"},
    {"id": "l23_t3", "points": 10, "title": "发起动作",
     "desc": "做完决定，同一个人到指挥台在选的方案下“采纳，生成动作”，提交给厂长（老师）批准。",
     "hint": "动作要挂在这一幕的异常上（从指挥台的异常里采纳，不要另起）。"},
    {"id": "l23_t4", "points": 20, "title": "复盘：这张订单赚了多少",
     "desc": "老师点“复盘”以后，在情景复盘里看这张订单的毛利分解和每一幕记到订单上的钱。填：毛利率；哪一幕记到订单上的钱最多；动作费用合计。",
     "hint": "毛利率填百分数（如 25.5）；动作费用 = 毛利分解里“急单、加班、外协、加急”那一行。"},
]
REPORT_POINTS = 40
ROLES = {"planner": "计划员", "quality": "质量", "lead": "班组长", "safety": "安全员", "maintenance": "维修", "service": "售后", "operator": "操作工",
         "engineer": "工艺员"}
DECIDE_BEATS = [2, 3, 4, 5, 6, 7, 8]
SCHEMA = """
create table if not exists lab23_member (
    user_name text not null,
    team      text not null,
    role      text not null,
    at        timestamptz not null default now(),
    primary key (user_name, role)
);
create table if not exists lab23_decision (
    run_id      bigint not null,
    team        text not null,
    beat_no     int not null,
    anomaly_id  bigint,
    option      text not null,
    label       text,
    reason      text,
    by          text,
    role        text,
    recommended text,
    at          timestamptz not null default now(),
    primary key (run_id, team, beat_no)
);
"""


def init(db):
    db.x(SCHEMA)


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence, keep_max=True):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score={}, evidence=excluded.evidence, done_at=now()".format(
             "greatest(task_result.score, excluded.score)" if keep_max else "excluded.score"),
         (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def start(db, user):
    if not _get(db, user, "l23_start"):
        _save(db, user, "l23_start", 0, {})


def team_of(db, user):
    init(db)
    r = db.one("select team from lab23_member where user_name=%s order by at desc limit 1", (user,))
    return r["team"] if r else None


def members(db, team):
    out = {}
    for r in db.q("select user_name, role from lab23_member where team=%s order by at", (team,)):
        out.setdefault(r["user_name"], []).append(r["role"])
    return out


def _run(db):
    from hub import story as ST
    return ST.run(db) or ST.last_run(db)


def beat_anomaly(db, run_id, n):
    """这一幕的主异常（预计的那条）"""
    r = db.one("select seen from story_beat where run_id=%s and beat_no=%s", (run_id, n))
    for x in (r["seen"] if r else None) or []:
        if x.get("id"):
            return x
    return None


def locked(db, u, anomaly_id=None):
    """比对模式：学生开始了实验 23、本组这一幕还没交决定 → 这一幕的异常不显示建议"""
    if not u or u.get("mode") != "teach" or u.get("teacher"):
        return False
    try:
        if not _get(db, u["name"], "l23_start"):
            return False
        team = team_of(db, u["name"])
        r = _run(db)
        if not team or r is None:
            return False
        decided = {x["beat_no"] for x in db.q("select beat_no from lab23_decision where run_id=%s and team=%s", (r["id"], team))}
        for b in db.q("select beat_no, seen from story_beat where run_id=%s", (r["id"],)):
            if b["beat_no"] not in DECIDE_BEATS or b["beat_no"] in decided:
                continue
            ids = {int(x["id"]) for x in b["seen"] or [] if x.get("id")}
            if anomaly_id is None or int(anomaly_id) in ids:
                return True
        return False
    except Exception:  # noqa: BLE001
        return False


def register(db, user, team, role):
    init(db)
    team = str(team or "").strip()[:30]
    if not team:
        raise ValueError("填小组名")
    if role not in ROLES:
        raise ValueError("角色只能是：" + "、".join(ROLES.values()))
    db.x("insert into lab23_member (user_name, team, role) values (%s,%s,%s) on conflict (user_name, role) do update set team=excluded.team, at=now()",
         (user, team, role))
    db.x("update lab23_member set team=%s where user_name=%s", (team, user))          # 一个人只在一个组
    start(db, user)
    _save(db, user, "l23_t1", 5, {"team": team, "roles": members(db, team).get(user)})
    return {"score": 5, "of": 5, "feedback": "已登记：{} 组，{}。".format(team, "、".join(ROLES[x] for x in members(db, team).get(user, [])))}


def decide(H, u, n, option, reason):
    """小组对第 n 幕的决定：由这一幕该负责的角色提交（组里登记过这个角色的人）"""
    from hub import story as ST
    db = H.db
    init(db)
    user = u["name"]
    team = team_of(db, user)
    if not team:
        raise ValueError("先完成任务 1：登记小组和角色")
    r = _run(db)
    if r is None:
        raise ValueError("老师还没开始两周情景")
    n = int(n)
    if n not in DECIDE_BEATS:
        raise ValueError("第 2–8 幕才要做决定")
    sc = ST.scenario(r["scenario"])
    b = ST.beat_of(sc, n)
    x = beat_anomaly(db, r["id"], n)
    if x is None:
        raise ValueError("第 {} 幕还没演，或者厂情中枢还没报出异常".format(n))
    mine = members(db, team).get(user, [])
    need = b.get("roles") or []
    if not set(mine) & set(need):
        raise PermissionError("第 {} 幕该{}处理（你登记的是{}）".format(n, "或".join(ROLES.get(k, k) for k in need), "、".join(ROLES.get(k, k) for k in mine)))
    if db.one("select 1 as x from lab23_decision where run_id=%s and team=%s and beat_no=%s", (r["id"], team, n)):
        raise ValueError("本组第 {} 幕已经交过决定".format(n))
    reason = str(reason or "").strip()
    if len(reason) < 15:
        raise ValueError("理由写完整一点（至少 15 个字）：多花多少、交期、风险")
    res, _, _, _ = H.anomaly_options(u, x["id"])
    opts = {o["kind"]: o for o in res.get("options") or []}
    if option not in opts:
        raise ValueError("选一个方案（{}）".format("、".join(o["label"] for o in opts.values())))
    best = next((o["kind"] for o in opts.values() if o.get("recommended")), None)
    role = next(k for k in mine if k in need)
    db.x("insert into lab23_decision (run_id, team, beat_no, anomaly_id, option, label, reason, by, role, recommended) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
         (r["id"], team, n, x["id"], option, opts[option]["label"], reason[:600], user, role, best))
    return status(db, user)


def _decision_points(db, run_id, d):
    """一幕决定的分（满分 25 / 7）：准时 40%、和推荐一致 40%（另一个处理方案 20%）、理由 20%"""
    nxt = db.one("select executed_at from story_beat where run_id=%s and beat_no=%s", (run_id, d["beat_no"] + 1))
    end = db.one("select ended_at from story_run where id=%s", (run_id,))
    late = (nxt and d["at"] > nxt["executed_at"]) or (end and end["ended_at"] and d["at"] > end["ended_at"])
    p = 0.0 if late else 0.4
    if d["recommended"] and d["option"] == d["recommended"]:
        p += 0.4
    elif d["option"] != "none":
        p += 0.2
    words = ("$", "钱", "成本", "多花", "费", "交期", "晚", "风险", "安全", "停")
    if sum(1 for w in words if w in (d["reason"] or "")) >= 2:
        p += 0.2
    elif len(d["reason"] or "") >= 15:
        p += 0.1
    return round(25.0 / len(DECIDE_BEATS) * p, 2), {"on_time": not late, "match": d["option"] == d["recommended"]}


def check(db, user):
    """自动检查任务 2、3（全组同分）"""
    init(db)
    start(db, user)
    team = team_of(db, user)
    r = _run(db)
    if not team or r is None:
        return status(db, user)
    ds = db.q("select * from lab23_decision where run_id=%s and team=%s order by beat_no", (r["id"], team))
    s2, ev2 = 0.0, []
    for d in ds:
        pts, how = _decision_points(db, r["id"], d)
        s2 += pts
        ev2.append(dict(beat=d["beat_no"], option=d["label"], by=d["by"], points=pts, **how))
    names = list(members(db, team))
    s3, ev3 = 0.0, []
    for n in DECIDE_BEATS:
        x = beat_anomaly(db, r["id"], n)
        if not x:
            continue
        acts = db.q("select id, status, initiator from action where mode='teach' and anomaly_id=%s and initiator = any(%s)", (x["id"], names))
        if acts:
            v = 1.0 if any(a["status"] in ("done", "executing") for a in acts) else (0.5 if any(a["status"] in ("submitted", "approved") for a in acts) else 0.25)
            s3 += v
            ev3.append({"beat": n, "actions": [{"id": a["id"], "status": a["status"], "by": a["initiator"]} for a in acts]})
    s3 = round(10.0 * s3 / len(DECIDE_BEATS), 2)
    for m in names:                                   # 全组同分（按最新的事实，可升可降）
        if ds:
            _save(db, m, "l23_t2", round(s2), {"team": team, "beats": ev2}, keep_max=False)
        if ev3:
            _save(db, m, "l23_t3", round(s3), {"team": team, "beats": ev3}, keep_max=False)
    return status(db, user)


def answer(H, user, tid, ans):
    from hub import story as ST
    db = H.db
    start(db, user)
    if tid != "l23_t4":
        raise KeyError(tid)
    try:
        rv = ST.review(H)
    except ValueError as e:
        return {"score": 0, "of": 20, "feedback": str(e)}
    m = rv["margin"]
    if not m:
        return {"score": 0, "of": 20, "feedback": "订单还没做完，老师复盘以后再填"}
    acts = next((x["usd"] for x in m["lines"] if x["key"] == "actions"), 0.0)
    s = 0
    try:
        if abs(float(ans.get("margin_pct")) - m["margin_pct"] * 100) <= 1.0:
            s += 8
        if acts and abs(float(ans.get("actions_usd")) - acts) <= max(5.0, acts * 0.05) or (not acts and float(ans.get("actions_usd")) == 0):
            s += 5
    except (TypeError, ValueError):
        return {"score": 0, "of": 20, "feedback": "毛利率、动作费用填数字"}
    if rv.get("top_beat") and str(ans.get("top_beat")) == str(rv["top_beat"]):
        s += 7
    _save(db, user, "l23_t4", s, {"answer": ans, "expected": {"margin_pct": round(m["margin_pct"] * 100, 2), "top_beat": rv.get("top_beat"),
                                                             "actions_usd": round(acts, 2)}})
    return {"score": s, "of": 20, "feedback": "正确。" if s == 20 else "得 {} / 20 分：毛利率 {:.1%}，记到订单上最多的是第 {} 幕，动作费用 ${:,.0f}。".format(
        s, m["margin_pct"], rv.get("top_beat") or "—", acts)}


def status(db, user):
    from hub import story as ST
    init(db)
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l23_%%'", (user,))}
    tasks = []
    for t in TASKS:
        x = rows.get(t["id"])
        tasks.append(dict(t, score=x["score"] if x else 0, done=bool(x and x["score"] >= t["points"]), evidence=x["evidence"] if x else None))
    team = team_of(db, user)
    st = ST.state(db)
    r = st.get("run")
    ds = {d["beat_no"]: d for d in db.q("select * from lab23_decision where run_id=%s and team=%s", (r["id"], team))} if r and team else {}
    beats = []
    for b in st["beats"]:
        x = beat_anomaly(db, r["id"], b["n"]) if r else None
        d = ds.get(b["n"])
        beats.append({"n": b["n"], "day": b["day"], "title": b["title"], "story": b["story"], "domain_name": b["domain_name"], "status": b["status"],
                      "roles": [{"key": k, "name": ROLES.get(k, k)} for k in b["roles"]], "decide": b["n"] in DECIDE_BEATS,
                      "anomaly": x, "look": b["look"],
                      "decision": {"option": d["option"], "label": d["label"], "reason": d["reason"], "by": d["by"], "at": d["at"].isoformat(),
                                   "recommended": d["recommended"] if d else None} if d else None})
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS), "report_points": REPORT_POINTS,
            "team": team, "members": [{"user": k, "roles": [ROLES.get(x, x) for x in v]} for k, v in members(db, team).items()] if team else [],
            "my_roles": members(db, team).get(user, []) if team else [], "roles": [{"key": k, "name": v} for k, v in ROLES.items()],
            "run": r, "order": st.get("order"), "beats": beats, "locked": locked(db, {"name": user, "mode": "teach"}) if team else False}


def class_view(db):
    init(db)
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l23_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    teams = {r["user_name"]: r["team"] for r in db.q("select distinct on (user_name) user_name, team from lab23_member order by user_name, at desc")}
    return [{"user": k, "team": teams.get(k), "scores": v, "total": sum(v.values())} for k, v in sorted(out.items(), key=lambda kv: (teams.get(kv[0]) or "", kv[0]))]
