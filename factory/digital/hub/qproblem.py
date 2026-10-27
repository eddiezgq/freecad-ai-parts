"""问题情景与 8D 质量异常单（第 13 轮 7.3（4）N6、N7；教材第 58、71 章）。

老师在教学模式下注入一个隐藏的加工问题（sim/errors.py），学生从三坐标数据和控制图发现异常，开一张质量异常单，按 8D 填写：
D1 小组、D2 问题描述（现象、数据、5W2H）、D3 临时措施（围堵）、D4 根本原因（5 Why、鱼骨图）、D5 纠正措施（从措施清单选一项并说明）、
D6 实施与验证、D7 预防再发生（改工艺文件、防错）、D8 总结。
D5 措施由老师批准后下发到仿真车间（apply_fix）；只有对症的措施能消除问题。D6 的验证由程序从措施之后的测量数据算出：
措施后至少 VERIFY_N 件，全部合格且 Cpk ≥ 1.33 才算有效，有效后才能关闭。
"""
from __future__ import annotations

import datetime as dt
import math

from psycopg.types.json import Jsonb

from hub import spc
from sim import errors as ERR

VERIFY_N = 10
SECTIONS = ["d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8"]
SECTION_NAMES = {"d1": "D1 成立小组", "d2": "D2 描述问题", "d3": "D3 临时措施（围堵）", "d4": "D4 根本原因",
                 "d5": "D5 纠正措施", "d6": "D6 实施与验证", "d7": "D7 预防再发生", "d8": "D8 总结与表彰"}

# 表结构在 hub/db.py（quality_problem、quality_8d）


# ---------------------------------------------------------------- 问题情景（老师）
def inject(db, send, mode, user, problem, magnitude=None):
    if mode != "teach":
        raise PermissionError("只有教学模式能注入问题情景")
    if problem not in ERR.problems_for(_plant_id()):
        raise KeyError(problem)
    send("set_problem", problem=problem, **({"magnitude": float(magnitude)} if magnitude is not None else {}))
    mag = float(magnitude) if magnitude is not None else ERR.PROBLEMS[problem]["default"]
    db.x("update quality_problem set cleared_at=now(), cleared_how='replaced' where mode=%s and problem=%s and cleared_at is null",
         (mode, problem))
    db.x("insert into quality_problem (mode, problem, magnitude, injected_by) values (%s, %s, %s, %s)", (mode, problem, mag, user))
    return active(db, mode)


def clear(db, send, mode, user):
    send("clear_problems")
    db.x("update quality_problem set cleared_at=now(), cleared_how=%s where mode=%s and cleared_at is null", ("teacher:" + user, mode))
    return active(db, mode)


def active(db, mode):
    rows = db.q("select * from quality_problem where mode=%s and cleared_at is null order by injected_at", (mode,))
    return [dict(r, name=ERR.PROBLEMS[r["problem"]]["name"]) for r in rows]


def _plant_id():
    from factory import plant as PLANT
    act = PLANT.active()
    return act["ID"] if act else None


def catalog():
    """本厂的问题情景与措施（第 47 轮：机器人厂是关节的三种，减速器厂是输出轴的五种）"""
    pid = _plant_id()
    return {"problems": {k: {"name": v["name"], "default": v["default"]} for k, v in ERR.problems_for(pid).items()},
            "fixes": ERR.fixes_for(pid), "sections": SECTION_NAMES}


# ---------------------------------------------------------------- 8D
def _new_id(db):
    r = db.one("select count(*) as n from quality_8d")
    return "Q8D-{:04d}".format((r and r["n"] or 0) + 1)


def create(db, mode, author, author_uid, item, characteristic, title, d=None):
    sid = _new_id(db)
    d = {k: v for k, v in (d or {}).items() if k in SECTIONS}
    db.x("insert into quality_8d (id, mode, item, characteristic, title, status, author, author_uid, d) values "
         "(%s, %s, %s, %s, %s, 'open', %s, %s, %s)", (sid, mode, item, characteristic, title[:200], author, author_uid, Jsonb(d)))
    return get(db, sid)


def get(db, sid):
    r = db.one("select * from quality_8d where id=%s", (sid,))
    return dict(r) if r else None


def list_(db, mode, limit=100):
    return [dict(r) for r in db.q("select id, item, characteristic, title, status, author, created_at, fix, closed_at "
                                  "from quality_8d where mode=%s order by created_at desc limit %s", (mode, limit))]


def update(db, sid, sections: dict, fix: str | None = None):
    s = get(db, sid)
    if not s:
        raise KeyError(sid)
    if s["status"] == "closed":
        raise ValueError("已关闭的 8D 不能再改")
    d = dict(s["d"] or {})
    for k, v in (sections or {}).items():
        if k in SECTIONS:
            d[k] = str(v)[:4000]
    args = [Jsonb(d)]
    sql = "update quality_8d set d=%s, updated_at=now()"
    if fix is not None and s["status"] in ("open", "rejected"):
        if fix not in ERR.FIXES:
            raise ValueError("没有这项措施")
        sql += ", fix=%s"
        args.append(fix)
    db.x(sql + " where id=%s", args + [sid])
    return get(db, sid)


def submit_fix(db, sid):
    s = get(db, sid)
    if not s:
        raise KeyError(sid)
    if not s.get("fix"):
        raise ValueError("先在 D5 选定纠正措施")
    missing = [SECTION_NAMES[k] for k in ("d1", "d2", "d3", "d4", "d5") if not (s["d"] or {}).get(k)]
    if missing:
        raise ValueError("提交措施前要先写：" + "、".join(missing))
    db.x("update quality_8d set status='submitted', updated_at=now() where id=%s", (sid,))
    return get(db, sid)


def decide_fix(db, send, sid, user, approve: bool, note=""):
    """老师批准（措施下发到仿真车间）或退回 D5 措施。"""
    s = get(db, sid)
    if not s or s["status"] != "submitted":
        raise ValueError("这张 8D 不在待批准措施的状态")
    if not approve:
        d = dict(s["d"] or {})
        d["teacher_note"] = note[:1000]
        db.x("update quality_8d set status='rejected', d=%s, updated_at=now() where id=%s", (Jsonb(d), sid))
        return get(db, sid)
    send("apply_fix", fix=s["fix"])
    gone = [p for p in ERR.PROBLEMS if ERR.PROBLEMS[p]["fix"] == s["fix"]]
    if gone:
        db.x("update quality_problem set cleared_at=now(), cleared_how=%s where mode=%s and cleared_at is null and problem = any(%s)",
             ("8d:" + sid, s["mode"], gone))
    db.x("update quality_8d set status='approved', fix_by=%s, fix_at=now(), updated_at=now() where id=%s", (user, sid))
    return get(db, sid)


def verify(db, sid):
    """D6 验证：措施下发之前最近 30 件与之后的测量值对比（同一特性）。"""
    s = get(db, sid)
    if not s:
        raise KeyError(sid)
    if not s.get("fix_at"):
        raise ValueError("措施还没有实施，没有可验证的数据")
    rows = [m for m in db.messages(["quality.measurement"], mode=s["mode"], order="asc", limit=20000)
            if m["data"]["item"] == s["item"] and m["data"]["characteristic"] == s["characteristic"]]
    fix_at = s["fix_at"]
    if fix_at.tzinfo is None:
        fix_at = fix_at.replace(tzinfo=dt.timezone.utc)

    def ts(m):
        return dt.datetime.fromisoformat(m["ts"].replace("Z", "+00:00"))
    before = [m for m in rows if ts(m) < fix_at][-30:]
    after = [m for m in rows if ts(m) >= fix_at]
    out = {"before": _stats(before), "after": _stats(after), "need": VERIFY_N}
    a = out["after"]
    out["effective"] = bool(a and a["n"] >= VERIFY_N and a["fails"] == 0 and a["Cpk"] is not None and a["Cpk"] >= 1.33)
    db.x("update quality_8d set verify=%s, updated_at=now() where id=%s", (Jsonb(out), sid))
    return out


def _stats(rows):
    if len(rows) < 2:
        return {"n": len(rows), "fails": sum(r["data"]["result"] == "fail" for r in rows), "Cpk": None} if rows else None
    v = [r["data"]["value_mm"] for r in rows]
    lo, hi = rows[-1]["data"]["lower_tol_mm"], rows[-1]["data"]["upper_tol_mm"]
    c = spc.capability(v, lo, hi)
    if lo == 0:          # 跳动、对称度这类只有上限的特性（下限 0 是自然界限）：用单边 Cpu、Ppu（教材《机械设计》4.9.3 节）
        c["Cpk"] = (hi - c["mean"]) / (3 * c["sigma_within"]) if c["sigma_within"] > 0 else float("inf")
        c["Ppk"] = (hi - c["mean"]) / (3 * c["s"]) if c["s"] > 0 else float("inf")
    cpk = c["Cpk"] if math.isfinite(c["Cpk"]) else None
    return {"n": len(v), "mean": c["mean"], "fails": sum(r["data"]["result"] == "fail" for r in rows),
            "Cpk": cpk, "Ppk": c["Ppk"], "lsl": lo, "usl": hi, "one_sided": lo == 0}


def close(db, sid, user):
    s = get(db, sid)
    if not s:
        raise KeyError(sid)
    if not (s.get("verify") or {}).get("effective"):
        raise ValueError("措施还没有验证有效（措施后至少 {} 件全部合格、Cpk ≥ 1.33），不能关闭".format(VERIFY_N))
    if not (s["d"] or {}).get("d7"):
        raise ValueError("关闭前要写 D7 预防再发生（改了哪些工艺文件、加了什么防错）")
    db.x("update quality_8d set status='closed', closed_at=now(), updated_at=now() where id=%s", (sid,))
    return get(db, sid)
