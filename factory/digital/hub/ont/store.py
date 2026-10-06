# -*- coding: utf-8 -*-
"""本体存储：对象、链接、事件、别名四张表，加同步游标。

写入经过 Batch：同一批消息里对同一对象的多次修改先在内存里合并，最后一次性写库。
对象缓存常驻内存（教学工厂几万个对象，几十 MB），读不到才查库。"""
import datetime as dt
import json
import threading

from psycopg.types.json import Jsonb

from hub.ont import schema as S

SCHEMA = """
create table if not exists ont_object (
    mode       text not null,
    type       text not null,
    key        text not null,
    domain     text not null,
    display    text,
    props      jsonb not null default '{}',
    prop_src   jsonb not null default '{}',
    src_seqs   bigint[] not null default '{}',
    first_seq  bigint,
    first_ts   timestamptz,
    updated_at timestamptz not null default now(),
    search     text,
    primary key (mode, type, key)
);
create table if not exists ont_link (
    mode     text not null,
    type     text not null,
    src_type text not null,
    src_key  text not null,
    dst_type text not null,
    dst_key  text not null,
    props    jsonb not null default '{}',
    src_seq  bigint,
    ts       timestamptz,
    primary key (mode, type, src_type, src_key, dst_type, dst_key)
);
create index if not exists ont_object_lkey on ont_object (mode, lower(key));
create index if not exists ont_link_dst on ont_link (mode, dst_type, dst_key);
create index if not exists ont_link_src on ont_link (mode, src_type, src_key);
create index if not exists ont_link_tool on ont_link ((props->>'tool')) where props ? 'tool';
create table if not exists ont_event (
    id      bigserial primary key,
    mode    text not null,
    type    text not null,
    key     text not null,
    ts      timestamptz not null,
    kind    text not null,
    text    text,
    changes jsonb,
    src_seq bigint
);
create index if not exists ont_event_obj on ont_event (mode, type, key, ts);
create table if not exists ont_alias (
    mode  text not null,
    alias text not null,
    type  text not null,
    key   text not null,
    primary key (mode, alias, type, key)
);
create index if not exists ont_alias_low on ont_alias (lower(alias));
create table if not exists ont_state (
    name  text primary key,
    value jsonb not null
);
"""
TRGM = ["create extension if not exists pg_trgm",
        "create index if not exists ont_object_search on ont_object using gin (search gin_trgm_ops)"]
MAX_SRC = 50
MAX_CACHE = 100000          # 缓存的对象超过这个数就清空（都已写库，清了只是下次从库里读），控制枢纽内存


def _j(v):
    """jsonb 里不能放 datetime：统一转成 ISO 字符串"""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    return v


class Store:
    def __init__(self, db, onto=None):
        self.db = db
        self.onto = onto or S.get()
        self.cache = {}                     # (mode, type, key) → dict(props, prop_src, src, first_seq, first_ts, exists)
        self.lock = threading.RLock()
        self.trgm = False

    def init(self):
        self.db.x(SCHEMA)
        try:
            for s in TRGM:
                self.db.x(s)
            self.trgm = True
        except Exception:  # noqa: BLE001  —— 没有 pg_trgm 权限时退回普通 like 查询
            self.trgm = False

    # ------------------------------------------------------------ 读
    def load(self, mode, type_, key):
        k = (mode, type_, key)
        o = self.cache.get(k)
        if o is not None:
            return o
        r = self.db.one("select props, prop_src, src_seqs, first_seq, first_ts from ont_object where mode=%s and type=%s and key=%s", k)
        if r:
            o = {"props": dict(r["props"]), "prop_src": dict(r["prop_src"]), "src": list(r["src_seqs"] or []),
                 "first_seq": r["first_seq"], "first_ts": r["first_ts"], "exists": True}
        else:
            o = None
        if o is not None:
            self.cache[k] = o
        return o

    def get(self, mode, type_, key):
        o = self.load(mode, type_, key)
        return None if o is None else o["props"]

    def reset(self, mode=None):
        """清空本体（某个模式或全部），同步游标归零由调用方处理"""
        with self.lock:
            for t in ("ont_object", "ont_link", "ont_event", "ont_alias"):
                if mode:
                    self.db.x("delete from {} where mode=%s".format(t), (mode,))
                else:
                    self.db.x("truncate {}".format(t))
            self.cache = {k: v for k, v in self.cache.items() if mode and k[0] != mode}

    def state(self, name, default=None):
        r = self.db.one("select value from ont_state where name=%s", (name,))
        return r["value"] if r else default

    def set_state(self, name, value):
        self.db.x("insert into ont_state (name, value) values (%s, %s) on conflict (name) do update set value=excluded.value",
                  (name, Jsonb(value)))

    def batch(self):
        return Batch(self)


class Batch:
    """一批修改。mapper 只调用 obj / link / event / alias，最后 flush 写库"""

    def __init__(self, store):
        self.st = store
        self.onto = store.onto
        self.dirty = set()
        self.links = {}
        self.events = []
        self.aliases = set()

    def obj(self, mode, type_, key, props=None, seq=None, ts=None, event=None, text=None, silent=False, upd_ts=None):
        """新建或更新对象。props 里值为 None 的不覆盖。event：事件种类（None = 新建时记“出现”，属性变化时记“更新”；
        silent=True 只改属性不记事件——高频的状态刷新用）。返回对象的属性 dict"""
        spec = self.onto.type(type_)
        key = str(key)
        k = (mode, type_, key)
        o = self.st.load(mode, type_, key)
        created = o is None
        if created:
            o = {"props": {}, "prop_src": {}, "src": [], "first_seq": seq, "first_ts": ts, "exists": False}
            self.st.cache[k] = o
        changes = {}
        for p, v in (props or {}).items():
            if v is None:
                continue
            if p not in spec["props"]:
                raise KeyError("{} 没有属性 {}（请先在本体定义里加上）".format(type_, p))
            v = _j(v)
            old = o["props"].get(p)
            if old != v:
                changes[p] = [old, v]
                o["props"][p] = v
                if seq is not None:
                    o["prop_src"][p] = seq
        if seq is not None and (not o["src"] or o["src"][-1] != seq):
            o["src"].append(seq)
            if len(o["src"]) > MAX_SRC:
                o["src"] = o["src"][:1] + o["src"][-(MAX_SRC - 1):]
        if created or changes or seq is not None:
            self.dirty.add(k)
        if ts is not None:
            if created:
                self.events.append((mode, type_, key, ts, event or "created", text or "出现", Jsonb(changes) if changes else None, seq))
            elif event or (changes and not silent):
                self.events.append((mode, type_, key, upd_ts or ts, event or "updated", text if event else None,
                                    Jsonb(changes) if changes else None, seq))
        return o["props"]

    def event(self, mode, type_, key, ts, kind, text, seq=None, changes=None):
        self.events.append((mode, type_, key, ts, kind, text, Jsonb(changes) if changes else None, seq))

    def link(self, mode, frm, frm_key, name, to_key, props=None, seq=None, ts=None, to_type=None):
        spec = self.onto.link(frm, name)
        dst = spec["to"]
        if dst == S.ANY:
            if to_type not in self.onto.types:
                raise KeyError("{}.{} 是通用链接，要给出目标类型（to_type）".format(frm, name))
            dst = to_type
        k = (mode, frm + "." + name, frm, str(frm_key), dst, str(to_key))
        cur = self.links.get(k)
        merged = dict((cur or {}).get("props") or {}, **{a: _j(b) for a, b in (props or {}).items() if b is not None})
        self.links[k] = {"props": merged, "seq": seq if seq is not None else (cur or {}).get("seq"), "ts": ts or (cur or {}).get("ts")}

    def alias(self, mode, alias, type_, key):
        if alias and str(alias) != str(key):
            self.aliases.add((mode, str(alias), type_, str(key)))

    def flush(self, state=None):
        """写库（一个事务）；state = {名: 值} 同事务写进 ont_state（同步游标）"""
        st, db = self.st, self.st.db
        rows = []
        for k in self.dirty:
            o = st.cache[k]
            mode, type_, key = k
            spec = self.onto.type(type_)
            disp = S.title_of(spec, key, o["props"])
            search = " ".join(x for x in [key, disp] + [str(o["props"].get(p)) for p in ("name", "title", "subject") if o["props"].get(p)] if x)
            rows.append((mode, type_, key, spec["domain"], disp, Jsonb(o["props"]), Jsonb(o["prop_src"]), o["src"],
                         o["first_seq"], o["first_ts"], search))
            o["exists"] = True
        conn = db.conn()
        with conn.transaction(), conn.cursor() as cur:
            for name, value in (state or {}).items():
                cur.execute("insert into ont_state (name, value) values (%s, %s) on conflict (name) do update set value=excluded.value",
                            (name, Jsonb(value)))
            if rows:
                cur.executemany(
                    "insert into ont_object (mode, type, key, domain, display, props, prop_src, src_seqs, first_seq, first_ts, search) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (mode, type, key) do update set "
                    "display=excluded.display, props=excluded.props, prop_src=excluded.prop_src, src_seqs=excluded.src_seqs, "
                    "first_seq=coalesce(ont_object.first_seq, excluded.first_seq), first_ts=coalesce(ont_object.first_ts, excluded.first_ts), "
                    "search=excluded.search, updated_at=now()", rows)
            if self.links:
                cur.executemany(
                    "insert into ont_link (mode, type, src_type, src_key, dst_type, dst_key, props, src_seq, ts) values (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "on conflict (mode, type, src_type, src_key, dst_type, dst_key) do update set "
                    "props = ont_link.props || excluded.props, src_seq = coalesce(excluded.src_seq, ont_link.src_seq), ts = coalesce(ont_link.ts, excluded.ts)",
                    [k + (Jsonb(v["props"]), v["seq"], v["ts"]) for k, v in self.links.items()])
            if self.events:
                cur.executemany("insert into ont_event (mode, type, key, ts, kind, text, changes, src_seq) values (%s,%s,%s,%s,%s,%s,%s,%s)",
                                self.events)
            if self.aliases:
                cur.executemany("insert into ont_alias (mode, alias, type, key) values (%s,%s,%s,%s) on conflict do nothing",
                                list(self.aliases))
        n = len(rows), len(self.links), len(self.events)
        self.dirty, self.links, self.events, self.aliases = set(), {}, [], set()
        if len(st.cache) > MAX_CACHE:
            st.cache.clear()
        return n


def dumps(v):
    return json.dumps(v, ensure_ascii=False, default=str)
