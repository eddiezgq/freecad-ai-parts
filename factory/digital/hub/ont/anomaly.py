# -*- coding: utf-8 -*-
"""异常（第 17 轮 B 期）：规则目录、检测循环、异常生命周期、规则调整与审计。

- 规则目录在 digital/ontology/rules/<领域>.yaml（编号、名称、严重度、负责角色、阈值、开关、说明、处理提示）；
  检测函数在 hub/ont/rules/<领域>.py（只读、只返回“发现”）。
- 异常存在自己的表里（生命周期、指派、备注不随本体重建丢失），对账时映射成本体里的“异常”对象。
- 生命周期：open 新发现 → ack 已确认 → doing 处理中 → resolved 已解决（条件连续两轮消失自动解除）/ closed 人工关闭。
  同一规则、同一对象只开一个；严重度升高记事件并重发提醒；人工关闭后 24 小时内复现则重新打开。"""
import datetime as dt
import glob
import logging
import os
import threading
import time

import yaml
from psycopg.types.json import Jsonb

from hub.ont import schema as S

log = logging.getLogger("hub.anomaly")
RULE_DIR = os.path.join(S.DIR, "rules")
LEVELS = {"info": 0, "warn": 1, "critical": 2}
LEVEL_LABEL = {"info": "提示", "warn": "警告", "critical": "严重"}
STATUS_LABEL = {"open": "新发现", "ack": "已确认", "doing": "处理中", "resolved": "已解决", "closed": "已关闭"}
OPEN = ("open", "ack", "doing")
ROLES = ("planner", "engineer", "operator", "quality", "manager", "sales", "lead")      # lead 班组长：第 18 轮 E4
MISS_TO_RESOLVE = 2
REOPEN_H = 24
CHAIN_EVERY_S = 300           # 开着的异常每 5 分钟重算一次链条

SCHEMA = """
create table if not exists anomaly (
    id          bigserial primary key,
    mode        text not null,
    rule        text not null,
    fkey        text not null,
    domain      text not null,
    subject_type text,
    subject_key text,
    severity    text not null,
    status      text not null default 'open',
    role        text,
    title       text not null,
    detail      jsonb not null default '{}',
    chain       jsonb,
    first_seen  timestamptz not null,
    last_seen   timestamptz not null,
    hits        int not null default 1,
    misses      int not null default 0,
    assignee    text,
    closed_at   timestamptz,
    closed_by   text,
    closed_reason text,
    reopened    int not null default 0
);
create index if not exists anomaly_open on anomaly (mode, status);
create index if not exists anomaly_fkey on anomaly (mode, rule, fkey);
create table if not exists anomaly_note (
    id          bigserial primary key,
    anomaly_id  bigint not null,
    ts          timestamptz not null default now(),
    who         text,
    kind        text not null,
    text        text
);
create index if not exists anomaly_note_a on anomaly_note (anomaly_id);
create table if not exists rule_change (
    id      bigserial primary key,
    ts      timestamptz not null default now(),
    who     text,
    rule    text not null,
    field   text not null,
    old     jsonb,
    new     jsonb
);
create table if not exists ont_metric_daily (
    mode    text not null,
    day     date not null,
    domain  text not null,
    metric  text not null,
    value   double precision,
    primary key (mode, day, domain, metric)
);
"""


class RuleError(ValueError):
    pass


# ------------------------------------------------------------------ 规则目录
def load_catalog(path=RULE_DIR):
    """读规则目录，校验：编号唯一、领域存在、检测函数存在（待数据的规则可以没有函数）、严重度和角色合法"""
    from hub.ont import rules as R
    onto = S.get()
    doms = {d["domain"] for d in onto.domains}
    from factory import plant
    demo = plant.is_demo()
    out = {}
    for f in sorted(glob.glob(os.path.join(path, "*.yaml"))):
        name = os.path.basename(f)
        if name.startswith(("chains", "playbooks")):
            continue
        doc = yaml.safe_load(open(f, encoding="utf-8")) or {}
        dom = doc.get("domain")
        if dom not in doms:
            raise RuleError("{}：领域 {} 不在本体里".format(name, dom))
        for rid, r in (doc.get("rules") or {}).items():
            where = "{} 的 {}".format(name, rid)
            if rid in out:
                raise RuleError("{}：规则编号重复".format(where))
            for k in ("name", "severity", "role"):
                if not r.get(k):
                    raise RuleError("{}：缺少 {}".format(where, k))
            if r["severity"] not in LEVELS:
                raise RuleError("{}：severity 只能是 {}".format(where, "、".join(LEVELS)))
            roles = r["role"] if isinstance(r["role"], list) else [r["role"]]
            if any(x not in ROLES for x in roles):
                raise RuleError("{}：role 只能是 {}".format(where, "、".join(ROLES)))
            # 第 30 轮 H-2：E1–E7 的规则（demo_only）只在演示工厂跑；企业工厂没有这些领域的数据，按“待数据”处理
            waiting = r.get("status") == "waiting" or bool(r.get("demo_only")) and not demo
            fn = r.get("fn")
            if not waiting and fn not in R.REG:
                raise RuleError("{}：检测函数 {} 不存在（hub/ont/rules/）".format(where, fn))
            out[rid] = dict(r, id=rid, domain=dom, role=roles, params=dict(r.get("params") or {}),
                            enabled=bool(r.get("enabled", True)) and not waiting, waiting=waiting)
    return out


# ------------------------------------------------------------------ 发现
class Finding:
    """检测函数返回的一条“发现”。fkey 在同一规则内唯一（一般就是对象编号）。"""

    def __init__(self, fkey, title, detail="", severity=None, subject=None, evidence=None, hint=None, values=None,
                 about=None, alert_key=None):
        self.fkey = str(fkey)
        self.title = title
        self.detail = detail
        self.severity = severity
        self.subject = subject                 # (类型, 编号)
        self.evidence = evidence or []         # 原始记录：[{topic, id/ts/name/item, seq?}]
        self.hint = hint
        self.values = values or {}
        self.about = about or ([subject] if subject else [])
        self.alert_key = alert_key             # 提醒的 key（沿用原 AI 提醒的写法，首页去重用）


class Ctx:
    """一轮检测的共享数据（按需计算，只算一次）"""

    def __init__(self, db, mode, now=None):
        self.db, self.mode = db, mode
        self.now = now or dt.datetime.now(dt.timezone.utc)
        self._c = {}

    def get(self, name, fn):
        if name not in self._c:
            self._c[name] = fn()
        return self._c[name]

    @property
    def ov(self):
        from hub import kpi
        return self.get("ov", lambda: kpi.overview(self.db, self.now, self.mode))


# ------------------------------------------------------------------ 检测与生命周期
class Detector:
    def __init__(self, db, catalog=None):
        self.db = db
        self.catalog = catalog or load_catalog()
        self.lock = threading.RLock()
        self.stats = {}          # 规则 → {runs, fired, last_fired, error, ms}
        self.last_round = {}     # 模式 → {ts, ms, findings}
        self._ready = False

    _init_lock = threading.Lock()

    def init(self):
        with Detector._init_lock:            # 后台检测线程和网页请求可能同时第一次建表
            if not self._ready:
                self.db.x(SCHEMA)
                self._ready = True

    # ---- 规则配置（阈值、开关）：ont_state 里的覆盖值 + 目录默认值
    def config(self):
        r = self.db.one("select value from ont_state where name='rules'") if self._has_state() else None
        return (r or {}).get("value") or {}

    def _has_state(self):
        return bool(self.db.one("select to_regclass('ont_state') is not null as ok")["ok"])

    def rule(self, rid):
        base = self.catalog[rid]
        over = self.config().get(rid) or {}
        return dict(base, enabled=over.get("enabled", base["enabled"]) and not base["waiting"],
                    params=dict(base["params"], **(over.get("params") or {})))

    def cast_params(self, rid, params):
        """网页送来的阈值是字符串：按目录默认值的类型转换；没有的参数报错"""
        base = self.catalog[rid]["params"]
        out = {}
        for k, v in (params or {}).items():
            if k not in base:
                raise RuleError("规则 {} 没有参数 {}".format(rid, k))
            d = base[k]
            out[k] = type(d)(v) if isinstance(d, (int, float)) and not isinstance(d, bool) else v
        return out

    def set_rule(self, rid, who, enabled=None, params=None):
        from hub.ont.store import Store
        if rid not in self.catalog:
            raise KeyError(rid)
        base = self.catalog[rid]
        if base["waiting"] and enabled:
            raise RuleError("这条规则还没有数据（待数据），不能启用")
        Store(self.db).init()
        cfg = self.config()
        cur = self.rule(rid)
        over = dict(cfg.get(rid) or {})
        changes = []
        if enabled is not None and bool(enabled) != cur["enabled"]:
            over["enabled"] = bool(enabled)
            changes.append(("enabled", cur["enabled"], bool(enabled)))
        for k, v in self.cast_params(rid, params).items():
            if cur["params"].get(k) != v:
                over.setdefault("params", {})[k] = v
                changes.append(("params." + k, cur["params"].get(k), v))
        cfg[rid] = over
        self.db.x("insert into ont_state (name, value) values ('rules', %s) on conflict (name) do update set value=excluded.value",
                  (Jsonb(cfg),))
        for f, o, n in changes:
            self.db.x("insert into rule_change (who, rule, field, old, new) values (%s,%s,%s,%s,%s)", (who, rid, f, Jsonb(o), Jsonb(n)))
        return self.rule(rid)

    # ---- 跑规则
    def detect(self, mode, now=None, only=None, params=None):
        """跑全部启用的规则，返回 {规则: [Finding]}（不写库）"""
        from hub.ont import rules as R
        c = Ctx(self.db, mode, now)
        out = {}
        for rid in self.catalog:
            if only and rid not in only:
                continue
            r = self.rule(rid)
            if params and rid in params:
                r = dict(r, params=dict(r["params"], **params[rid]))
            if not r["enabled"] and not only:
                continue
            st = self.stats.setdefault(rid, {"runs": 0, "fired": 0, "last_fired": None, "error": None, "ms": 0})
            t0 = time.time()
            try:
                fs = list(R.REG[r["fn"]](c, r["params"], r) or [])
                st["error"] = None
            except Exception as e:  # noqa: BLE001  —— 一条规则出错只跳过这一条
                if type(e).__name__ == "UndefinedTable":          # 这个模块还没启用（如没开数字孪生）：当作没有数据
                    st.update(runs=st["runs"] + 1, error=None, nodata=True)
                    out[rid] = []
                    continue
                log.exception("规则 %s 出错", rid)
                st["error"] = "{}：{}".format(type(e).__name__, e)
                out[rid] = None
                continue
            st["runs"] += 1
            st["ms"] = round((time.time() - t0) * 1000)
            for f in fs:
                f.severity = f.severity or r["severity"]
            out[rid] = fs
        return out, c

    def run(self, mode, now=None):
        """一轮：检测 → 更新异常 → 返回要发的提醒（新开、升级、重开）"""
        self.init()
        t0 = time.time()
        with self.lock:
            found, c = self.detect(mode, now)
            alerts = []
            for rid, fs in found.items():
                if fs is None:            # 规则出错：已开的异常保持原样，不当成“条件消失”
                    continue
                alerts += self._apply(mode, self.rule(rid), fs, c.now)
            self.refresh_chains(mode, c)
            self.last_round[mode] = {"ts": time.time(), "ms": round((time.time() - t0) * 1000),
                                     "findings": sum(len(v or []) for v in found.values())}
        return alerts

    def refresh_chains(self, mode, c, every_s=CHAIN_EVERY_S, ids=None):
        """开着的异常：链条没算过或超过 every_s 秒就重算（出错不影响检测）"""
        from hub.ont import chain as CH
        rows = self.db.q("select * from anomaly where mode=%s and status = any(%s) and (chain is null or "
                         "(chain->>'computed_at')::timestamptz < now() - make_interval(secs => %s))" + (" and id = any(%s)" if ids else ""),
                         [mode, list(OPEN), every_s] + ([list(ids)] if ids else []))
        for a in rows:
            try:
                ch = CH.for_anomaly(c, a)
            except Exception as e:  # noqa: BLE001
                log.exception("异常 %s 的链条计算出错", a["id"])
                ch = {"error": "{}：{}".format(type(e).__name__, e), "nodes": [], "edges": [], "summary": [],
                      "computed_at": dt.datetime.now(dt.timezone.utc).isoformat()}
            self.db.x("update anomaly set chain=%s where id=%s", (Jsonb(ch), a["id"]))

    def _apply(self, mode, r, fs, now):
        db = self.db
        rid = r["id"]
        cur = {a["fkey"]: a for a in db.q("select * from anomaly where mode=%s and rule=%s and status = any(%s)", (mode, rid, list(OPEN)))}
        seen, alerts = set(), []
        st = self.stats.setdefault(rid, {"runs": 0, "fired": 0, "last_fired": None, "error": None, "ms": 0})
        for f in fs:
            if f.fkey in seen:
                continue
            seen.add(f.fkey)
            detail = {"text": f.detail, "evidence": f.evidence, "hint": f.hint or r.get("hint"), "values": f.values,
                      "about": [list(x) for x in f.about if x], "alert_key": f.alert_key}
            a = cur.get(f.fkey)
            if a:
                up = LEVELS[f.severity] > LEVELS[a["severity"]]
                # 标题变了（例如停机原因、时长变了）就清掉旧的因果链，下次打开立即重算，不让链条说法和标题对不上
                db.x("update anomaly set last_seen=%s, hits=hits+1, misses=0, chain=case when title is distinct from %s then null else chain end, "
                     "title=%s, detail=%s, severity=%s where id=%s",
                     (now, f.title, f.title, Jsonb(detail), f.severity if up or LEVELS[f.severity] < LEVELS[a["severity"]] else a["severity"],
                      a["id"]))
                if up:
                    self.note(a["id"], "system", "escalate", "严重度升为“{}”：{}".format(LEVEL_LABEL[f.severity], f.title))
                    alerts.append(self._alert(a["id"], f, rid, "escalate"))
                continue
            # 人工关闭后 24 小时内复现 → 重新打开
            prev = db.one("select * from anomaly where mode=%s and rule=%s and fkey=%s and status='closed' and closed_at > %s "
                          "order by closed_at desc limit 1", (mode, rid, f.fkey, now - dt.timedelta(hours=REOPEN_H)))
            if prev:
                db.x("update anomaly set status='open', last_seen=%s, hits=hits+1, misses=0, reopened=reopened+1, title=%s, detail=%s, "
                     "severity=%s, closed_at=null where id=%s", (now, f.title, Jsonb(detail), f.severity, prev["id"]))
                self.note(prev["id"], "system", "reopen", "关闭后 {} 小时内再次出现，重新打开".format(REOPEN_H))
                alerts.append(self._alert(prev["id"], f, rid, "reopen"))
                continue
            st["fired"] += 1
            st["last_fired"] = now.isoformat()
            sub = f.subject or (None, None)
            r_ = db.one("insert into anomaly (mode, rule, fkey, domain, subject_type, subject_key, severity, role, title, detail, "
                        "first_seen, last_seen) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                        (mode, rid, f.fkey, r["domain"], sub[0], sub[1], f.severity, r["role"][0], f.title, Jsonb(detail), now, now))
            self.note(r_["id"], "system", "open", f.title)
            alerts.append(self._alert(r_["id"], f, rid))
        # 没再出现的：连续两轮消失 → 自动解除
        for fk, a in cur.items():
            if fk in seen:
                continue
            m = a["misses"] + 1
            if m >= MISS_TO_RESOLVE:
                db.x("update anomaly set status='resolved', misses=%s, closed_at=%s, closed_by='system', "
                     "closed_reason='条件已消失（连续两轮检测未再出现），自动解除' where id=%s", (m, now, a["id"]))
                self.note(a["id"], "system", "resolve", "条件已消失，自动解除")
            else:
                db.x("update anomaly set misses=%s where id=%s", (m, a["id"]))
        return alerts

    def _alert(self, aid, f, rid, change="open"):
        """给首页提醒和 AI 助手的 ai.alert 内容（格式沿用原 AI 提醒）；change：open / escalate / reopen（第 17 轮 D 期通知用）"""
        r = self.catalog[rid]
        return {"level": f.severity, "title": f.title, "detail": f.detail, "evidence": f.evidence,
                "action_hint": f.hint or r.get("hint") or "", "key": f.alert_key or "{}:{}".format(rid, f.fkey),
                "anomaly_id": aid, "rule": rid, "domain": r["domain"], "change": change}

    # ---- 人的操作
    def note(self, aid, who, kind, text):
        self.db.x("insert into anomaly_note (anomaly_id, who, kind, text) values (%s,%s,%s,%s)", (aid, who, kind, text))

    def act(self, aid, who, kind, text="", role=None, now=None):
        a = self.db.one("select * from anomaly where id=%s", (aid,))
        if a is None:
            raise KeyError(aid)
        if kind == "ack":
            if a["status"] != "open":
                raise RuleError("只有“新发现”的异常可以确认")
            self.db.x("update anomaly set status='ack', assignee=coalesce(assignee, %s) where id=%s", (who, aid))
            self.note(aid, who, "ack", text or "已确认")
        elif kind == "doing":
            if a["status"] not in ("open", "ack"):
                raise RuleError("这个异常已经结束")
            self.db.x("update anomaly set status='doing' where id=%s", (aid,))
            self.note(aid, who, "doing", text or "开始处理")
        elif kind == "assign":
            if role not in ROLES:
                raise RuleError("指派给哪个角色？")
            self.db.x("update anomaly set role=%s where id=%s", (role, aid))
            self.note(aid, who, "assign", "指派给{}{}".format(role, "：" + text if text else ""))
        elif kind == "note":
            if not text.strip():
                raise RuleError("备注不能为空")
            self.note(aid, who, "note", text.strip())
        elif kind == "close":
            if a["status"] not in OPEN:
                raise RuleError("这个异常已经结束")
            if not text.strip():
                raise RuleError("关闭要写原因（怎么处理的）")
            self.db.x("update anomaly set status='closed', closed_at=%s, closed_by=%s, closed_reason=%s where id=%s",
                      (now or dt.datetime.now(dt.timezone.utc), who, text.strip(), aid))
            self.note(aid, who, "close", text.strip())
        else:
            raise RuleError("不认识的操作 " + kind)
        return self.db.one("select * from anomaly where id=%s", (aid,))

    def notes(self, aid):
        return self.db.q("select ts, who, kind, text from anomaly_note where anomaly_id=%s order by id", (aid,))
