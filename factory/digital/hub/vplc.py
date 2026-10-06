# -*- coding: utf-8 -*-
"""虚拟 PLC 的枢纽一侧（《PLC 原理及实践》第 18 轮第 8 步）：班次记录、“虚拟 PLC”页的接口、任务单批准时下发程序。

班次 plc_run：老师在“虚拟 PLC”页上传程序试跑一班，或工程任务单里“PLC 程序”这项交付物在老师批准时自动下发。
枢纽把程序（ST，或 PLCopen XML 转成的 ST）先编译检查，再向设备发 plc.download；仿真车间里的虚拟 PLC
（vplc/runner.py）算出整个班次、按车间倍速回放，枢纽收 plc.shift / plc.cycle / machine.event 更新班次记录。
"""
import json
import logging
import os
import secrets
import threading

from fastapi import Body, Depends, File, Form, HTTPException, UploadFile
from psycopg.types.json import Jsonb

import wqbus
from wqbus.topics import PLC_UNITS, unit_topic

log = logging.getLogger("hub.vplc")
HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(os.path.dirname(HERE), "vplc", "examples")
EXAMPLE_FILES = {"press-01": ("press_p15_5_1.st", "程序 15.5.1（第 15 章参考程序）"), "sort-01": ("sorter_ref.st", "分拣线参考程序")}

SCHEMA = """
create table if not exists plc_run (
    id text primary key,
    mode text not null,
    unit text not null,
    title text not null default '',
    origin text not null default 'manual',          -- manual 老师试跑 / task 任务单批准
    task_sub text,
    program text not null,
    hours real not null default 8,
    seed integer not null default 1,
    status text not null default 'queued',          -- queued running done failed cancelled
    live jsonb not null default '{}'::jsonb,        -- 回放中：件数、合格、不合格、进度、状态、最近节拍
    alarms jsonb not null default '[]'::jsonb,
    summary jsonb,
    review jsonb,
    error text,
    created_by text,
    created_uid text,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz
);
alter table plc_run add column if not exists compat jsonb;     -- OpenPLC 兼容性检查的结果
create index if not exists plc_run_unit on plc_run (mode, unit, created_at desc);
create index if not exists plc_run_sub on plc_run (task_sub);
"""


def to_st(name, data, unit):
    """上传的文件 → ST 源程序。.xml 按 PLCopen XML 读（问渠实验台导出的格式）；其余按 ST 文本。"""
    from vplc.runner import tool
    text = data.decode("utf-8-sig", "replace") if isinstance(data, (bytes, bytearray)) else str(data)
    if (name or "").lower().endswith(".xml") or text.lstrip().startswith("<?xml") or "<project" in text[:500]:
        r = tool({"op": "import", "xml": text, "unit": PLC_UNITS[unit]}, timeout=60)
        if not r.get("ok"):
            raise ValueError("PLCopen XML 读不出来：" + (r.get("error") or "?"))
        return r["st"]
    return text


def check(st, unit):
    """编译检查 + 程序检查（与实验台“程序检查”同一套规则）。返回 {ok, error, review}。"""
    from vplc.runner import tool
    return tool({"op": "check", "st": st, "unit": PLC_UNITS[unit]}, timeout=60)


class VPLC:
    def __init__(self, db, publish):
        self.db, self.publish = db, publish
        self.lock = threading.Lock()

    def init(self):
        self.db.x(SCHEMA)

    # ------------------------------------------------------------ 下发
    def start(self, mode, unit, st, title="", origin="manual", task_sub=None, hours=8.0, seed=1, who="", uid=None,
              speed=None, review=None):
        if unit not in PLC_UNITS:
            raise ValueError("没有这台虚拟 PLC 设备：" + str(unit))
        if not 0 < float(hours) <= 12:
            raise ValueError("班次时长应在 0–12 小时之间")
        rid = "PLC-" + secrets.token_hex(4).upper()
        self.db.x("insert into plc_run (id, mode, unit, title, origin, task_sub, program, hours, seed, review, created_by, created_uid) "
                  "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (rid, mode, unit, title[:200], origin, task_sub, st, float(hours), int(seed), Jsonb(review) if review is not None else None,
                   who, uid))
        # 同一台设备上还在跑的班次，虚拟 PLC 收到新程序时会作废，这里先记下
        self.db.x("update plc_run set status='cancelled', finished_at=now() where mode=%s and unit=%s and id<>%s and status in ('queued','running')",
                  (mode, unit, rid))
        data = {"run_id": rid, "program": st, "hours": float(hours), "seed": int(seed)}
        if speed is not None:
            data["speed"] = float(speed)
        self.publish(unit_topic(unit, "cmd"), "plc.download", "hub", data, rid, mode)
        return rid

    # ------------------------------------------------------------ 总线
    def on_message(self, tp, msg):
        t, d = msg["type"], msg["data"]
        parts = tp.split("/")
        unit = parts[3] if len(parts) > 3 else None
        if unit not in PLC_UNITS:
            return
        rid = d.get("run_id")
        if not rid:
            return
        with self.lock:
            if t == "plc.shift":
                ph = d["phase"]
                if ph == "started":
                    self.db.x("update plc_run set status='running', started_at=coalesce(started_at, now()) where id=%s and status in ('queued','running')", (rid,))
                elif ph == "done":
                    self.db.x("update plc_run set status='done', summary=%s, finished_at=now() where id=%s and status<>'cancelled'",
                              (Jsonb(d.get("summary") or {}), rid))
                elif ph == "failed":
                    self.db.x("update plc_run set status='failed', error=%s, finished_at=now() where id=%s", ((d.get("error") or "")[:2000], rid))
                elif ph == "compat":
                    self.db.x("update plc_run set compat=%s where id=%s", (Jsonb(d.get("compat") or {}), rid))
                elif ph == "cancelled":
                    self.db.x("update plc_run set status='cancelled', finished_at=coalesce(finished_at, now()) where id=%s", (rid,))
            elif t == "plc.cycle":
                live = {k: d.get(k) for k in ("n", "good_n", "nok_n", "progress", "cycle_s", "peak_kN", "t_s")}
                self.db.x("update plc_run set live = live || %s where id=%s and status='running'", (Jsonb(live), rid))
            elif t == "machine.status":
                self.db.x("update plc_run set live = live || %s where id=%s and status='running'",
                          (Jsonb({"state": d["state"], "progress": d.get("progress"), "t_s": d.get("t_s")}), rid))
            elif t == "machine.event" and d["event"] in ("alarm", "fault"):
                a = {"code": d.get("code"), "message": d.get("message"), "t_s": d.get("t_s"), "ts": msg["ts"]}
                self.db.x("update plc_run set alarms = alarms || %s::jsonb where id=%s", (json.dumps([a], ensure_ascii=False), rid))

    # ------------------------------------------------------------ 查询
    def runs(self, mode, unit=None, limit=30, task_sub=None):
        sql = ("select id, unit, title, origin, task_sub, hours, status, live, alarms, summary, error, created_by, created_at, "
               "case when compat is null then null else jsonb_build_object('ok', compat->'ok', 'stage', compat->'stage') end as compat, "
               "started_at, finished_at from plc_run where mode=%s")
        args = [mode]
        if unit:
            sql += " and unit=%s"
            args.append(unit)
        if task_sub:
            sql += " and task_sub=%s"
            args.append(task_sub)
        sql += " order by created_at desc limit %s"
        args.append(int(limit))
        return [dict(r) for r in self.db.q(sql, args)]

    def get(self, rid, mode):
        r = self.db.one("select * from plc_run where id=%s and mode=%s", (rid, mode))
        return dict(r) if r else None


def mount(app, H, user_of, who, uid_of, is_teacher):

    def need_teacher(u):
        if not is_teacher(u):
            raise HTTPException(403, "只有老师可以下发程序试跑")

    def call(fn, *a, **k):
        try:
            return fn(*a, **k)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @app.get("/api/plc")
    def plc_overview(u=Depends(user_of)):
        units = []
        for unit, model in PLC_UNITS.items():
            cur = H.vplc.runs(u["mode"], unit, limit=1)
            units.append({"unit": unit, "model": model, "name": wqbus.UNITS[unit][1], "en": wqbus.UNITS[unit][2],
                          "example": EXAMPLE_FILES[unit][1], "current": cur[0] if cur else None})
        return {"units": units, "runs": H.vplc.runs(u["mode"], limit=40), "teacher": bool(is_teacher(u)),
                "speed": float(os.environ.get("WQ_SIM_SPEED", "20"))}

    @app.get("/api/plc/runs/{rid}")
    def plc_run(rid: str, u=Depends(user_of)):
        r = H.vplc.get(rid, u["mode"])
        if not r:
            raise HTTPException(404, "没有这个班次")
        if not is_teacher(u) and r.get("created_uid") != uid_of(u) and r.get("origin") != "task":
            r.pop("program", None)
        r.pop("created_uid", None)
        return r

    @app.post("/api/plc/runs")
    async def plc_start(unit: str = Form(...), hours: float = Form(8.0), title: str = Form(""), example: str = Form(""),
                        program: str = Form(""), file: UploadFile = File(None), u=Depends(user_of)):
        need_teacher(u)
        if unit not in PLC_UNITS:
            raise HTTPException(422, "没有这台设备")
        if example:
            with open(os.path.join(EXAMPLES, EXAMPLE_FILES[unit][0]), encoding="utf-8") as f:
                st = f.read()
            title = title or EXAMPLE_FILES[unit][1]
        elif file is not None:
            st = call(to_st, file.filename, await file.read(), unit)
            title = title or file.filename
        elif program.strip():
            st = program
        else:
            raise HTTPException(422, "请上传程序文件（.st 或 PLCopen XML），或选参考程序")
        c = check(st, unit)
        if not c.get("ok"):
            raise HTTPException(422, "程序编译不过：" + (c.get("error") or ""))
        rid = call(H.vplc.start, u["mode"], unit, st, title=title, hours=hours, who=who(u), uid=uid_of(u), review=c.get("review"))
        return {"id": rid}
