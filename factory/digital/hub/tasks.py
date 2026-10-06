# -*- coding: utf-8 -*-
"""工程任务单（第 11 轮《机械设计》2.7（3）5b、2.7（4）（5））：学习平台下达 → 学生在“我的任务”交交付物 → AI 设计评审员
出意见 → 学生逐条回复、修改 → 老师关闭意见、批准（连带批准任务里的设计发布、工艺规程）→ 加工、检验 → 老师评分 →
学习平台把分数写进课程成绩簿。

两种入口：
- 学生、老师：数字工厂登录凭证（x-wq-token），路径 /api/tasks、/api/task-submissions；
- 学习平台网关：服务器对服务器的任务单钥匙 WQ_FACTORY_TASK_KEY（Authorization: Bearer），路径 /api/tasks/course/…，
  只管下达、读进度和分数、记“已回传”。
"""
import datetime as dt
import hmac
import logging
import os
import uuid

from fastapi import Body, Depends, File, Form, Header, HTTPException, UploadFile

import wqbus
from hub import task_review as R

log = logging.getLogger("hub.tasks")

STATUS_ZH = {"draft": "未提交", "submitted": "待老师审阅", "returned": "退回修改", "approved": "已批准", "graded": "已评分"}
MAX_FILE = 50 * 1024 * 1024
MIME = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "step": "application/step",
        "png": "image/png", "jpg": "image/jpeg", "zip": "application/zip", "txt": "text/plain",
        "xml": "application/xml", "st": "text/plain"}


def _key():
    return os.environ.get("WQ_FACTORY_TASK_KEY", "")


def require_key(authorization: str = Header(default="")):
    k = _key()
    got = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not k or not got or not hmac.compare_digest(got.encode(), k.encode()):
        raise HTTPException(401, "需要数字工厂任务单钥匙（Authorization: Bearer …）")
    return True


# ---------------------------------------------------------------- 数据
def issue(db, spec, course_id, course_name="", cmid=None, due=None, issued_by=""):
    """下达（同一门课同一张任务单再下达 = 更新交期和内容）。返回任务单编号"""
    from psycopg.types.json import Jsonb
    code = spec.get("编号")
    if not code or not spec.get("交付物") or not spec.get("评分"):
        raise ValueError("任务单内容不完整（缺编号、交付物或评分）")
    r = db.one("select id from task_sheet where code=%s and course_id=%s", (code, int(course_id)))
    if r:
        db.x("update task_sheet set spec=%s, course_name=%s, cmid=%s, due=%s, status='open' where id=%s",
             (Jsonb(spec), course_name, cmid, due, r["id"]))
        return r["id"]
    tid = uuid.uuid4().hex[:12]
    db.x("insert into task_sheet (id, code, book, no, spec, course_id, course_name, cmid, due, issued_by) "
         "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
         (tid, code, spec.get("book"), spec.get("no"), Jsonb(spec), int(course_id), course_name, cmid, due, issued_by))
    return tid


def task(db, tid):
    r = db.one("select * from task_sheet where id=%s", (tid,))
    return dict(r) if r else None


def submission(db, sid):
    r = db.one("select * from task_submission where id=%s", (sid,))
    if not r:
        return None
    r = dict(r)
    r["comments"] = [dict(c) for c in db.q("select * from design_comment where sub_id=%s order by id", ("T" + sid,))]
    return r


def mine(db, tid, uid, author, create=True):
    r = db.one("select id from task_submission where task_id=%s and author_uid=%s", (tid, str(uid)))
    if r:
        return submission(db, r["id"])
    if not create:
        return None
    sid = uuid.uuid4().hex[:12]
    db.x("insert into task_submission (id, task_id, author, author_uid) values (%s,%s,%s,%s) on conflict do nothing",
         (sid, tid, author, str(uid)))
    return mine(db, tid, uid, author, create=False)


def _editable(s):
    if s["status"] not in ("draft", "returned"):
        raise ValueError("已经提交（{}），不能再改；退回后才能修改".format(STATUS_ZH[s["status"]]))


def _deliverable(t, i):
    ds = t["spec"].get("交付物") or []
    if not (0 <= i < len(ds)):
        raise KeyError("没有这项交付物")
    return ds[i]


def set_deliverable(db, s, i, value):
    from psycopg.types.json import Jsonb
    _editable(s)
    d = dict(s["deliverables"] or {})
    d[str(i)] = value
    db.x("update task_submission set deliverables=%s, updated_at=now() where id=%s", (Jsonb(d), s["id"]))
    return submission(db, s["id"])


def check_file(x, name):
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "stp":
        ext = "step"
    allowed = x.get("格式")
    if allowed and ext not in allowed:
        raise ValueError("“{}”要交 {} 格式，收到的是 {}".format(x["名称"][0], "、".join(allowed), name))
    return ext


def run_review(db, t, s, loaders):
    f = R.review(t["spec"], s["deliverables"], author_uid=s["author_uid"], **loaders)
    total = R.suggested_score(f)
    return {"findings": f, "suggested_score": total, "suggested_items": R.rubric_split(t["spec"], total), "by": R.AI_REVIEWER}


def submit(db, t, s, loaders):
    """提交：AI 设计评审员先审，意见写成批注（上一轮没关闭的 AI 意见作废，老师的意见保留）"""
    from psycopg.types.json import Jsonb
    _editable(s)
    rev = run_review(db, t, s, loaders)
    db.x("delete from design_comment where sub_id=%s and author=%s and not resolved", ("T" + s["id"], R.AI_REVIEWER))
    names = [x["名称"][0] for x in t["spec"].get("交付物") or []]
    for f in rev["findings"]:
        if f["level"] == "info":
            continue
        where = "〔{}〕".format(names[f["d"]]) if f["d"] is not None and f["d"] < len(names) else ""
        db.x("insert into design_comment (sub_id, author, body, level) values (%s,%s,%s,%s)",
             ("T" + s["id"], R.AI_REVIEWER, where + f["text"], f["level"]))
    db.x("update task_submission set status='submitted', review=%s, submitted_at=now(), rounds=rounds+1, updated_at=now() "
         "where id=%s", (Jsonb(rev), s["id"]))
    return submission(db, s["id"])


def comment(db, s, author, body, level=None):
    body = (body or "").strip()[:2000]
    if not body:
        raise ValueError("意见不能为空")
    db.x("insert into design_comment (sub_id, author, body, level) values (%s,%s,%s,%s)", ("T" + s["id"], author, body, level))
    return submission(db, s["id"])


def reply(db, s, cid, body):
    body = (body or "").strip()[:1000]
    if not body:
        raise ValueError("回复不能为空")
    db.x("update design_comment set reply=%s where sub_id=%s and id=%s", (body, "T" + s["id"], int(cid)))
    return submission(db, s["id"])


def resolve(db, s, cid, resolved=True):
    db.x("update design_comment set resolved=%s where sub_id=%s and id=%s", (bool(resolved), "T" + s["id"], int(cid)))
    return submission(db, s["id"])


def decide(db, t, s, decision, who_, note="", on_approve=None):
    if s["status"] != "submitted":
        raise ValueError("只有“待老师审阅”的提交能批准或退回（现在：{}）".format(STATUS_ZH[s["status"]]))
    if decision == "return":
        if not note.strip():
            raise ValueError("退回要写明原因")
        db.x("update task_submission set status='returned', decided_by=%s, decided_at=now(), decision=%s, updated_at=now() "
             "where id=%s", (who_, note, s["id"]))
        return submission(db, s["id"])
    if decision != "approve":
        raise ValueError("decision 只能是 approve / return")
    open_must = [c for c in s["comments"] if not c["resolved"] and c.get("level") == "error"]
    if open_must:
        raise ValueError("还有 {} 条“必改”意见没有关闭，先逐条看学生的回复并关闭".format(len(open_must)))
    linked = on_approve(t, s) if on_approve else []
    db.x("update task_submission set status='approved', decided_by=%s, decided_at=now(), decision=%s, updated_at=now() "
         "where id=%s", (who_, (note or "") + ("（" + "；".join(linked) + "）" if linked else ""), s["id"]))
    return submission(db, s["id"])


def grade(db, t, s, items, who_, note=""):
    from psycopg.types.json import Jsonb
    if s["status"] not in ("approved", "graded"):
        raise ValueError("批准以后才能评分（制造与检验复盘要看检验结果）")
    rub = t["spec"].get("评分") or []
    if len(items) != len(rub):
        raise ValueError("要给评分量规的每一项打分（共 {} 项）".format(len(rub)))
    pts = []
    for v, x in zip(items, rub):
        v = float(v)
        if not (0 <= v <= x["分"]):
            raise ValueError("“{}”的分数要在 0–{} 之间".format(x["项"][0], x["分"]))
        pts.append(v)
    sc = {"items": pts, "total": round(sum(pts), 1), "by": who_, "at": dt.datetime.now(dt.timezone.utc).isoformat(), "note": note[:1000]}
    db.x("update task_submission set status='graded', score=%s, pushed_at=null, updated_at=now() where id=%s", (Jsonb(sc), s["id"]))
    return submission(db, s["id"])


def inspection(db, mode, item, since):
    """批准以后这个零件的三坐标检验记录（仿真车间）"""
    if not item or not since:
        return []
    out = []
    for m in db.messages(["quality.measurement"], since=since, mode=mode, order="desc", limit=200):
        d = m["data"]
        if d.get("item") == item:
            out.append({k: d.get(k) for k in ("part_serial", "characteristic", "nominal_mm", "lower_tol_mm", "upper_tol_mm",
                                               "value_mm", "result", "work_order")} | {"ts": m.get("ts")})
    return out


def summary(db, t, s, name_of=None):
    rv = s.get("review") or {}
    cm = s.get("comments") or []
    return {"id": s["id"], "author_uid": s["author_uid"], "name": (name_of(s["author_uid"]) if name_of else None) or s["author"],
            "status": s["status"], "status_zh": STATUS_ZH[s["status"]], "rounds": s["rounds"],
            "open_errors": sum(1 for c in cm if not c["resolved"] and c.get("level") == "error"),
            "open_warnings": sum(1 for c in cm if not c["resolved"] and c.get("level") == "warning"),
            "suggested": rv.get("suggested_score"), "total": (s.get("score") or {}).get("total"),
            "submitted_at": s.get("submitted_at"), "decided_at": s.get("decided_at"), "pushed_at": s.get("pushed_at")}


def task_view(t):
    sp = t["spec"]
    return {"id": t["id"], "code": t["code"], "no": t["no"], "book": t["book"], "title": sp.get("标题"), "role": sp.get("角色"),
            "hours": sp.get("学时"), "stations": sp.get("工位"), "background": sp.get("背景"),
            "deliverables": [{"i": i, "name": x["名称"], "accept": x["验收"], "kind": x.get("类型", "文件"), "formats": x.get("格式"),
                              "item": x.get("零件"), "must_list": x.get("必列")} for i, x in enumerate(sp.get("交付物") or [])],
            "steps": sp.get("步骤"), "review_points": sp.get("评审要点"), "rubric": sp.get("评分"), "docs": sp.get("docs") or [],
            "course_id": t["course_id"], "course_name": t["course_name"], "due": t["due"], "status": t["status"],
            "docs_base": _docs_base(sp)}


def _docs_base(sp):
    """任务单、评分量规、空白计算书的下载地址（在学习平台，凭全站登录下载）：https://learn.<域名>/api/v1/task-docs/书/编号/"""
    import urllib.parse
    u = urllib.parse.urlparse(os.environ.get("WQ_SSO_URL", ""))
    if not (u.scheme and u.netloc and sp.get("book") and sp.get("no")):
        return None
    return "{}://{}/api/v1/task-docs/{}/{}/".format(u.scheme, u.netloc, sp["book"], sp["no"])


# ---------------------------------------------------------------- 接口
def mount(app, H, user_of, who, uid_of, emit_as):
    from hub import plm, process
    from hub import cae_api

    def is_teacher(u):
        return bool(u.get("teacher"))

    def need_teacher(u):
        if not is_teacher(u):
            raise HTTPException(403, "只有老师可以做这个操作")

    def call(fn, *a, **k):
        try:
            return fn(*a, **k)
        except KeyError as e:
            raise HTTPException(404, str(e).strip("'"))
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))

    def name_of(uid):
        r = H.db.one("select name from known_user where uid=%s", (str(uid),))
        return r and r["name"]

    def get_task(tid):
        t = task(H.db, tid)
        if not t:
            raise HTTPException(404, "没有这张任务单")
        return t

    def get_sub(sid, u, teacher_only=False):
        s = submission(H.db, sid)
        if not s:
            raise HTTPException(404, "没有这次提交")
        if teacher_only:
            need_teacher(u)
        elif not is_teacher(u) and s["author_uid"] != uid_of(u):
            raise HTTPException(403, "这是别人的提交")
        return s

    def get_job(jid):
        return cae_api.call("GET", "/jobs/{}".format(jid)).json()

    def loaders(mode):
        def get_design(sid):
            return plm.get(H.db, sid)
        return {"get_file": lambda url: plm.load_file(H.db, url), "get_design": get_design, "get_job": get_job,
                "get_process": lambda sid: process.get(H.db, sid)}

    def full(t, s, u):
        out = dict(s)
        out["comments"] = [dict(c) for c in s["comments"]]
        out["task"] = task_view(t)
        out["status_zh"] = STATUS_ZH[s["status"]]
        out["name"] = name_of(s["author_uid"]) or s["author"]
        out["mine"] = s["author_uid"] == uid_of(u)
        item = next((x.get("零件") for x in t["spec"].get("交付物") or [] if x.get("零件")), None)
        out["inspection"] = inspection(H.db, u["mode"], item, s["decided_at"]) if s["status"] in ("approved", "graded") else []
        if getattr(H, "vplc", None) is not None and any(x.get("类型") == "PLC 程序" for x in t["spec"].get("交付物") or []):
            out["plc_runs"] = H.vplc.runs(u["mode"], task_sub=s["id"], limit=5)       # 批准后在虚拟 PLC 上跑的班次
        out["stage"] = ("graded" if s["status"] == "graded" else "inspected" if out["inspection"] else
                        "approved" if s["status"] == "approved" else s["status"])
        out.pop("author_uid", None) if not is_teacher(u) else None
        return out

    # ---- 学生与老师
    @app.get("/api/tasks")
    def tasks_list(u=Depends(user_of)):
        rows = H.db.q("select * from task_sheet where status='open' order by issued_at desc")
        out = []
        for r in rows:
            t = dict(r)
            v = {k: v for k, v in task_view(t).items() if k in ("id", "code", "no", "title", "role", "hours", "stations", "due", "course_name")}
            if is_teacher(u):
                subs = H.db.q("select status, count(*) n from task_submission where task_id=%s group by status", (t["id"],))
                v["counts"] = {x["status"]: x["n"] for x in subs}
            s = mine(H.db, t["id"], uid_of(u), who(u), create=False)
            v["mine"] = summary(H.db, t, s) if s else None
            out.append(v)
        return out

    @app.get("/api/tasks/{tid}")
    def task_get(tid: str, u=Depends(user_of)):
        t = get_task(tid)
        s = mine(H.db, tid, uid_of(u), who(u), create=False)
        return {"task": task_view(t), "submission": full(t, s, u) if s else None}

    @app.post("/api/tasks/{tid}/deliverables/{i}/file")
    async def task_file(tid: str, i: int, file: UploadFile = File(...), u=Depends(user_of)):
        t = get_task(tid)
        x = call(_deliverable, t, i)
        kind = x.get("类型", "文件")
        if kind not in ("文件", "PLC 程序"):
            raise HTTPException(422, "这项交付物不是上传文件")
        data = await file.read()
        if len(data) > MAX_FILE:
            raise HTTPException(413, "文件超过 50 MB")
        ext = call(check_file, x, file.filename or "")
        f = plm.store(H.db, file.filename, MIME.get(ext, file.content_type or "application/octet-stream"), data)
        s = mine(H.db, tid, uid_of(u), who(u))
        if kind == "PLC 程序":           # 第 18 轮第 8 步：PLC 程序（ST 或 PLCopen XML），上传时就编译检查
            from hub import vplc as V
            unit = x.get("设备") or "press-01"
            try:
                st = V.to_st(file.filename, data, unit)
                c = V.check(st, unit)
            except ValueError as e:
                c = {"ok": False, "error": str(e), "review": []}
            chk = {"ok": bool(c.get("ok")), "error": c.get("error"),
                   "errors": sum(1 for r in c.get("review") or [] if r.get("level") == "error"),
                   "warnings": sum(1 for r in c.get("review") or [] if r.get("level") == "warning")}
            return full(t, call(set_deliverable, H.db, s, i, {"kind": "PLC 程序", "files": [f], "unit": unit, "check": chk}), u)
        return full(t, call(set_deliverable, H.db, s, i, {"kind": "文件", "files": [f]}), u)

    @app.post("/api/tasks/{tid}/deliverables/{i}/design")
    async def task_design(tid: str, i: int, step: UploadFile = File(None), drawing: UploadFile = File(None),
                          note: str = Form(""), u=Depends(user_of)):
        """设计发布：教学模式下也进待审（hold），任务单批准时一并批准、发 design.release"""
        t = get_task(tid)
        x = call(_deliverable, t, i)
        if x.get("类型") != "设计发布":
            raise HTTPException(422, "这项交付物不是设计发布")
        s = mine(H.db, tid, uid_of(u), who(u))
        call(_editable, s)
        blobs = {}
        for k, f in (("step", step), ("drawing", drawing)):
            if f is not None and f.filename:
                b = await f.read()
                if len(b) > MAX_FILE:
                    raise HTTPException(413, "文件超过 50 MB")
                blobs[k] = (b, f.filename)
        if "step" not in blobs:
            raise HTTPException(422, "要上传 STEP 模型（图纸可以一起传）")
        old = (s["deliverables"] or {}).get(str(i)) or {}
        r = call(plm.submit, H.db, emit_as(u), u["mode"], who(u), uid_of(u), x["零件"], step=blobs["step"][0],
                 step_name=blobs["step"][1], drawing=blobs.get("drawing", (None, None))[0],
                 drawing_name=blobs.get("drawing", (None, None))[1], note=("任务单 {} ".format(t["code"]) + note)[:500], hold=True)
        if old.get("plm"):                                   # 换掉上一次没批准的提交
            o = plm.get(H.db, old["plm"])
            if o and o["status"] == "pending":
                plm.decide(H.db, emit_as(u), old["plm"], o["author"], "withdrawn", "任务单里换成了新版本")
        return full(t, call(set_deliverable, H.db, s, i, {"kind": "设计发布", "plm": r["id"]}), u)

    @app.post("/api/tasks/{tid}/deliverables/{i}/link")
    def task_link(tid: str, i: int, body: dict = Body(...), u=Depends(user_of)):
        """分析：选“仿真与分析”的作业；工艺规程：选自己的工艺规程提交"""
        t = get_task(tid)
        x = call(_deliverable, t, i)
        kind = x.get("类型")
        s = mine(H.db, tid, uid_of(u), who(u))
        if kind == "分析":
            jid = (body.get("job") or "").strip()
            j = get_job(jid)
            if j.get("factory") != cae_api.FACTORY_ID or str(j.get("owner")) != uid_of(u):
                raise HTTPException(403, "只能选自己算的作业")
            return full(t, call(set_deliverable, H.db, s, i, {"kind": "分析", "job": jid, "item": j.get("item"), "status": j.get("status")}), u)
        if kind == "工艺规程":
            sid = (body.get("process") or "").strip()
            p = process.get(H.db, sid)
            if not p or p["author_uid"] != uid_of(u):
                raise HTTPException(404, "没有你的这份工艺规程提交")
            return full(t, call(set_deliverable, H.db, s, i, {"kind": "工艺规程", "process": sid}), u)
        raise HTTPException(422, "这项交付物不是分析或工艺规程")

    @app.post("/api/tasks/{tid}/deliverables/{i}/change")
    def task_change(tid: str, i: int, body: dict = Body(...), u=Depends(user_of)):
        t = get_task(tid)
        x = call(_deliverable, t, i)
        if x.get("类型") != "更改单":
            raise HTTPException(422, "这项交付物不是更改单")
        rows = [{k: str(r.get(k) or "")[:300] for k in ("item", "change", "reason")} for r in (body.get("rows") or [])[:50]]
        s = mine(H.db, tid, uid_of(u), who(u))
        return full(t, call(set_deliverable, H.db, s, i, {"kind": "更改单", "rows": rows}), u)

    @app.post("/api/tasks/{tid}/precheck")
    def task_precheck(tid: str, u=Depends(user_of)):
        """AI 预检：随时可点，只给意见、不记录"""
        t = get_task(tid)
        s = mine(H.db, tid, uid_of(u), who(u))
        return run_review(H.db, t, s, loaders(u["mode"]))

    @app.post("/api/tasks/{tid}/submit")
    def task_submit(tid: str, u=Depends(user_of)):
        t = get_task(tid)
        s = mine(H.db, tid, uid_of(u), who(u))
        return full(t, call(submit, H.db, t, s, loaders(u["mode"])), u)

    @app.get("/api/tasks/{tid}/submissions")
    def task_subs(tid: str, u=Depends(user_of)):
        need_teacher(u)
        t = get_task(tid)
        rows = H.db.q("select id from task_submission where task_id=%s order by submitted_at desc nulls last", (tid,))
        return {"task": task_view(t), "submissions": [summary(H.db, t, submission(H.db, r["id"]), name_of) for r in rows]}

    @app.get("/api/task-submissions/{sid}")
    def sub_get(sid: str, u=Depends(user_of)):
        s = get_sub(sid, u)
        return full(get_task(s["task_id"]), s, u)

    @app.post("/api/task-submissions/{sid}/comments")
    def sub_comment(sid: str, body: dict = Body(...), u=Depends(user_of)):
        s = get_sub(sid, u)
        t = get_task(s["task_id"])
        if body.get("reply_to"):                          # 学生回复（也可以老师补充）
            return full(t, call(reply, H.db, s, body["reply_to"], body.get("body")), u)
        need_teacher(u)
        lv = body.get("level") if body.get("level") in ("error", "warning") else None
        return full(t, call(comment, H.db, s, "老师·" + (u.get("name") or "")[:30], body.get("body"), lv), u)

    @app.post("/api/task-submissions/{sid}/comments/{cid}")
    def sub_resolve(sid: str, cid: int, body: dict = Body(default={}), u=Depends(user_of)):
        s = get_sub(sid, u, teacher_only=True)
        return full(get_task(s["task_id"]), resolve(H.db, s, cid, body.get("resolved", True)), u)

    def on_approve_for(u):
        def go(t, s):
            done = []
            for i, x in enumerate(t["spec"].get("交付物") or []):
                got = (s["deliverables"] or {}).get(str(i)) or {}
                if x.get("类型") == "设计发布" and got.get("plm"):
                    p = plm.get(H.db, got["plm"])
                    if p and p["status"] == "pending":
                        plm.approve(H.db, emit_as(u), got["plm"], who(u), "任务单 {} 批准".format(t["code"]), check_self=False)
                        done.append("{} 设计发布生效".format(x.get("零件")))
                if x.get("类型") == "PLC 程序" and got.get("files") and getattr(H, "vplc", None) is not None:
                    # 批准的程序下载到数字工厂的虚拟 PLC，跑一个班次（第 18 轮第 8 步）
                    from hub import vplc as V
                    unit = got.get("unit") or x.get("设备") or "press-01"
                    f = got["files"][0]
                    try:
                        st = V.to_st(f["name"], plm.load_file(H.db, f["url"]) or b"", unit)
                        c = V.check(st, unit)
                        if c.get("ok"):
                            rid = H.vplc.start(u["mode"], unit, st, title="{} · {}".format(t["code"], s.get("author") or ""),
                                               origin="task", task_sub=s["id"], hours=float(x.get("班次小时") or 8),
                                               who=who(u), uid=s.get("author_uid"), review=c.get("review"))
                            done.append("程序已下载到虚拟 PLC，{}开始一个班次（{}）".format(wqbus.UNITS[unit][1], rid))
                        else:
                            done.append("程序编译不过，没有下载到虚拟 PLC：" + (c.get("error") or ""))
                    except Exception as e:  # noqa: BLE001 —— 下载不成功不影响批准，写进批准记录
                        log.exception("下发 PLC 程序失败")
                        done.append("程序没能下载到虚拟 PLC：" + str(e)[:200])
                if x.get("类型") == "工艺规程" and got.get("process"):
                    p = process.get(H.db, got["process"])
                    if p and p["status"] == "pending":
                        for c in p["comments"]:
                            if not c["resolved"]:
                                process.resolve(H.db, got["process"], c["id"])
                        p2 = process.approve(H.db, emit_as(u), got["process"], who(u), "任务单 {} 批准".format(t["code"]),
                                             approver_uid=uid_of(u))
                        try:
                            from hub import cam_api
                            cam_api.release_programs(H.db, emit_as(u, "cam"), p2)     # 挂在工序上的数控程序随之下发（第 13 轮）
                        except Exception:  # noqa: BLE001 —— 没有数控程序可下发不影响批准
                            pass
                        done.append("{} 工艺规程生效".format(x.get("零件")))
            return done
        return go

    @app.post("/api/task-submissions/{sid}/decision")
    def sub_decision(sid: str, body: dict = Body(...), u=Depends(user_of)):
        s = get_sub(sid, u, teacher_only=True)
        t = get_task(s["task_id"])
        return full(t, call(decide, H.db, t, s, body.get("decision"), who(u), (body.get("note") or "")[:500], on_approve_for(u)), u)

    @app.post("/api/task-submissions/{sid}/grade")
    def sub_grade(sid: str, body: dict = Body(...), u=Depends(user_of)):
        s = get_sub(sid, u, teacher_only=True)
        t = get_task(s["task_id"])
        return full(t, call(grade, H.db, t, s, body.get("items") or [], who(u), body.get("note") or ""), u)

    # ---- 学习平台网关（任务单钥匙）
    @app.post("/api/tasks/course/issue")
    def gw_issue(body: dict = Body(...), _=Depends(require_key)):
        tid = call(issue, H.db, body.get("spec") or {}, body.get("course_id"), body.get("course_name") or "",
                   body.get("cmid"), body.get("due"), body.get("issued_by") or "")
        return {"id": tid}

    @app.get("/api/tasks/course/{course_id}")
    def gw_course(course_id: int, _=Depends(require_key)):
        out = []
        for r in H.db.q("select * from task_sheet where course_id=%s order by issued_at", (course_id,)):
            t = dict(r)
            subs = [summary(H.db, t, submission(H.db, x["id"]), name_of)
                    for x in H.db.q("select id from task_submission where task_id=%s", (t["id"],))]
            for x in subs:
                sc = (H.db.one("select score from task_submission where id=%s", (x["id"],)) or {}).get("score") or {}
                x["score_items"], x["score_note"] = sc.get("items"), sc.get("note")
            out.append({"id": t["id"], "code": t["code"], "title": t["spec"].get("标题"), "cmid": t["cmid"], "due": t["due"],
                        "status": t["status"], "submissions": subs})
        return out

    @app.post("/api/tasks/course/{course_id}/pushed")
    def gw_pushed(course_id: int, body: dict = Body(...), _=Depends(require_key)):
        """学习平台写进成绩簿以后记一笔（再评分会清掉，提醒重新回传）"""
        ids = [str(x) for x in body.get("submissions") or []]
        n = 0
        for sid in ids:
            r = H.db.one("select s.id from task_submission s join task_sheet t on t.id=s.task_id where s.id=%s and t.course_id=%s",
                         (sid, course_id))
            if r:
                H.db.x("update task_submission set pushed_at=now() where id=%s", (sid,))
                n += 1
        return {"marked": n}
