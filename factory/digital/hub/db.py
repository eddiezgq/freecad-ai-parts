# -*- coding: utf-8 -*-
"""历史库（PostgreSQL）。bus_message 存总线上的每一条消息；其余几张小表存状态变化、
AI 提议、教学任务得分和 FreeCAD 上传的文件。"""
import json
import os
import threading

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DSN = os.environ.get("WQ_DB", "postgresql://postgres@localhost:5433/wq_factory")

SCHEMA = """
create table if not exists bus_message (
    seq         bigserial primary key,
    id          uuid unique,
    ts          timestamptz not null,
    topic       text not null,
    type        text,
    source      text,
    mode        text,
    corr        text,
    payload     jsonb not null,
    valid       boolean not null default true,
    received_at timestamptz not null default now()
);
create index if not exists bus_message_type_ts on bus_message (type, ts);
create index if not exists bus_message_topic_ts on bus_message (topic, ts);
create index if not exists bus_message_corr on bus_message (corr);

-- 设备状态变化（从 machine.status 提取，只记变化点），算 OEE 用
create table if not exists machine_state_log (
    unit  text not null,
    ts    timestamptz not null,
    state text not null,
    mode  text,
    primary key (unit, ts)
);

create table if not exists ai_proposal (
    proposal_id  text primary key,
    created_at   timestamptz not null default now(),
    mode         text not null,
    action       text not null,
    title        text,
    preview      jsonb not null,
    status       text not null default 'pending',   -- pending / confirmed / rejected / executed / failed
    requested_by text,
    confirmed_by text,
    decided_at   timestamptz,
    result       jsonb
);

create table if not exists ncr (
    ncr_id      text primary key,
    created_at  timestamptz not null,
    part_serial text not null,
    item        text,
    work_order  text,
    detail      jsonb,
    status      text not null default 'open',       -- open / rework / scrap / use_as_is
    decided_by  text,
    decided_at  timestamptz,
    mode        text
);

create table if not exists task_result (
    user_name  text not null,
    task_id    text not null,
    score      integer not null,
    done_at    timestamptz not null default now(),
    evidence   jsonb,
    primary key (user_name, task_id)
);

create table if not exists stored_file (
    sha256     text primary key,
    name       text not null,
    mime       text,
    size       integer,
    content    bytea not null,
    created_at timestamptz not null default now()
);

-- 企业版第一期（第 8 轮）：设计提交与审批、批注、登录过的人、企业成员
create table if not exists design_submission (
    id          text primary key,
    mode        text not null,
    item        text not null,
    status      text not null,             -- pending 待审 / approved 已批准 / rejected 退回 / withdrawn 撤回
    author      text not null,
    author_uid  text,
    ts          timestamptz not null default now(),
    note        text,
    files       jsonb not null,             -- [{kind: step|glb|drawing|gcode|diff, name, url, sha256, size}]
    gcode       jsonb,                      -- {operation, machine, url, sha256, ...}
    params      jsonb,
    base_rev    integer,                    -- 提交时的现行版本
    revision    integer,                    -- 批准后的版本号
    diff        jsonb,                      -- 与现行版的差异统计
    decided_by  text,
    decided_at  timestamptz,
    decision    text
);
create index if not exists design_submission_item on design_submission (mode, item, ts desc);
create table if not exists design_comment (
    id          bigserial primary key,
    sub_id      text not null,
    author      text not null,
    ts          timestamptz not null default now(),
    body        text not null,
    anchor      jsonb,                      -- 三维模型上的点 {x, y, z}（mm），没有就是整体意见
    resolved    boolean not null default false
);
create index if not exists design_comment_sub on design_comment (sub_id, id);
-- 工艺规程（第 13 轮）：与设计提交并列；批注沿用 design_comment（sub_id 前加 P）
create table if not exists process_submission (
    id          text primary key,
    mode        text not null,
    item        text not null,
    status      text not null,
    author      text not null,
    author_uid  text,
    ts          timestamptz not null default now(),
    note        text,
    plan        jsonb not null,
    review      jsonb,
    revision    integer,
    decided_by  text,
    decided_at  timestamptz,
    decision    text
);
create index if not exists process_submission_item on process_submission (mode, item, ts desc);
-- 问题情景与 8D 质量异常单（第 13 轮：hub/qproblem.py）
create table if not exists quality_problem (
    id          serial primary key,
    mode        text not null,
    problem     text not null,
    magnitude   double precision,
    injected_by text,
    injected_at timestamptz not null default now(),
    cleared_at  timestamptz,
    cleared_how text
);
create table if not exists quality_8d (
    id          text primary key,
    mode        text not null,
    item        text not null,
    characteristic text,
    title       text not null,
    status      text not null,
    author      text not null,
    author_uid  text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    d           jsonb not null default '{}'::jsonb,
    fix         text,
    fix_by      text,
    fix_at      timestamptz,
    verify      jsonb,
    closed_at   timestamptz
);
create table if not exists known_user (
    uid         text primary key,
    name        text not null,
    teacher     boolean not null default false,
    last_seen   timestamptz not null default now()
);
-- 工程任务单（第 11 轮《机械设计》2.7（5））：学习平台下达，学生在“我的任务”提交，AI 设计评审员出意见，老师批准、评分；
-- 批注沿用 design_comment（sub_id 前加 T），多两列：level（AI 意见的级别）、reply（学生的回复）
create table if not exists task_sheet (
    id          text primary key,
    code        text not null,              -- TS-33-1
    book        text,
    no          text,                       -- 33.1
    spec        jsonb not null,             -- 任务单说明文件的内容（教材构建时生成）
    course_id   integer not null,
    course_name text,
    cmid        integer,                    -- 学习平台课程里对应的作业（成绩回传用）
    due         timestamptz,
    issued_by   text,
    issued_at   timestamptz not null default now(),
    status      text not null default 'open',
    unique (code, course_id)
);
create table if not exists task_submission (
    id           text primary key,
    task_id      text not null references task_sheet (id),
    author       text not null,
    author_uid   text not null,
    status       text not null default 'draft',   -- draft / submitted / returned / approved / graded
    deliverables jsonb not null default '{}'::jsonb,
    review       jsonb,
    submitted_at timestamptz,
    rounds       integer not null default 0,
    decided_by   text,
    decided_at   timestamptz,
    decision     text,
    score        jsonb,
    pushed_at    timestamptz,
    updated_at   timestamptz not null default now(),
    unique (task_id, author_uid)
);
alter table design_comment add column if not exists level text;
alter table design_comment add column if not exists reply text;
create table if not exists enterprise_member (
    uid         text primary key,
    roles       text[] not null,
    added_by    text,
    added_at    timestamptz not null default now()
);
"""


class DB:
    def __init__(self, dsn=DSN):
        self.dsn = dsn
        self._local = threading.local()

    def conn(self):
        c = getattr(self._local, "c", None)
        if c is None or c.closed:
            c = psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row)
            self._local.c = c
        return c

    def init(self):
        with self.conn().cursor() as cur:
            cur.execute(SCHEMA)

    def q(self, sql, args=None):
        with self.conn().cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall() if cur.description else []

    def one(self, sql, args=None):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql, args=None):
        with self.conn().cursor() as cur:
            cur.execute(sql, args)
            return cur.rowcount

    # ------------------------------------------------------------ 消息
    def insert_message(self, topic, msg, valid=True):
        """返回 True 表示新消息（id 未见过）。"""
        n = self.x(
            "insert into bus_message (id, ts, topic, type, source, mode, corr, payload, valid) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (id) do nothing",
            (msg.get("id"), msg.get("ts"), topic, msg.get("type"), msg.get("source"), msg.get("mode"),
             msg.get("corr"), Jsonb(msg), valid))
        return n == 1

    def insert_invalid(self, topic, raw, reason):
        try:
            body = json.loads(raw)
        except Exception:  # noqa: BLE001
            body = {"raw": raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)}
        self.x("insert into bus_message (id, ts, topic, type, source, mode, corr, payload, valid) "
               "values (gen_random_uuid(), now(), %s, null, %s, %s, null, %s, false)",
               (topic, body.get("source") if isinstance(body, dict) else None,
                body.get("mode") if isinstance(body, dict) else None, Jsonb({"invalid": reason, "body": body})))

    def messages(self, types=None, since=None, until=None, mode=None, topic_like=None, corr=None,
                 limit=None, order="asc"):
        where, args = ["valid"], []
        if types:
            where.append("type = any(%s)")
            args.append(list(types))
        if since is not None:
            where.append("ts >= %s")
            args.append(since)
        if until is not None:
            where.append("ts <= %s")
            args.append(until)
        if mode:
            where.append("mode = %s")
            args.append(mode)
        if topic_like:
            where.append("topic like %s")
            args.append(topic_like)
        if corr:
            where.append("corr = %s")
            args.append(corr)
        sql = "select seq, topic, payload from bus_message where {} order by ts {}, seq {}".format(
            " and ".join(where), order, order)
        if limit:
            sql += " limit %d" % int(limit)
        return [dict(r["payload"], _topic=r["topic"], _seq=r["seq"]) for r in self.q(sql, args)]

    def latest_per_topic(self, types, mode=None, topic_like=None):
        where, args = ["valid", "type = any(%s)"], [list(types)]
        if mode:
            where.append("mode = %s")
            args.append(mode)
        if topic_like:
            where.append("topic like %s")
            args.append(topic_like)
        sql = ("select distinct on (topic) topic, payload from bus_message where {} "
               "order by topic, ts desc, seq desc").format(" and ".join(where))
        return {r["topic"]: r["payload"] for r in self.q(sql, args)}

    def erp_docs(self, doctype, mode=None):
        """ERPNext 单据的最新快照：每个单号取最后一条 erp.doc。"""
        where, args = ["valid", "type = 'erp.doc'", "payload->'data'->>'doctype' = %s",
                       "payload->'data'->>'action' <> 'failed'"], [doctype]
        if mode:
            where.append("mode = %s")
            args.append(mode)
        sql = ("select distinct on (payload->'data'->>'name') payload from bus_message where {} "
               "order by payload->'data'->>'name', ts desc, seq desc").format(" and ".join(where))
        return [r["payload"] for r in self.q(sql, args)]
