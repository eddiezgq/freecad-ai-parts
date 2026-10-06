# -*- coding: utf-8 -*-
"""AI 代理（第 17 轮 D 期 D1–D3）：在工厂本体上干活的 AI 工厂助手。

- 工具全部是 17A–17C 已有的能力：搜索对象、读对象、沿关系走、算指标、异常与因果链、推演、按预案比较方案、起草动作，
  外加原助手的查总线消息、看板数据、算料、起草订单提议。只读的直接用；写的只能起草（动作草稿 / 提议），人提交、审批后才执行。
- 引用：每个工具结果里的对象、消息、异常、推演都编上号 [n]；回答里的结论写成“……[n]”，页面上点开看依据。
- 数字核对：回答里的每个数字都要能在本次工具结果（或问题）里找到，找不到的句子标“未经核实”，记进运行记录。
- 两种引擎：有模型时由模型自己决定调哪些工具（国内 DeepSeek，美国 Claude，见 hub/llm.py）；
  没配模型时用规则版——识别十类常见问题，按固定步骤调同一套工具，答案同样带引用。
- 每次运行都存进 ai_run（运行记录），本体里是“AI 运行”对象。
- 教学模式：对学生只提示方向、不代做，不起草动作和订单；老师看到的是完整回答。"""
import datetime as dt
import json
import logging
import re
import time

from psycopg.types.json import Jsonb

from factory import data as F
from hub import kpi, mrp
from wqbus import UNITS

log = logging.getLogger("agent")

SCHEMA = """
create table if not exists ai_run (
    id            bigserial primary key,
    mode          text not null,
    "user"        text,
    role          text,
    kind          text not null default 'chat',
    question      text,
    engine        text,
    steps         jsonb not null default '[]',
    answer        text,
    refs          jsonb not null default '[]',
    "check"       jsonb,
    duration_ms   integer,
    usage         jsonb,
    feedback      smallint,
    feedback_text text,
    anomaly_id    bigint,
    created_at    timestamptz not null default now()
);
create index if not exists ai_run_ts on ai_run (mode, created_at);
"""
KEEP_DAYS = 180

NUM = re.compile(r"(?<![A-Za-z\-\d])\d[\d,]*(?:\.\d+)?")
REF = re.compile(r"\[(\d{1,3})\]")
MACHINES = [u for u, v in UNITS.items() if v[0] in ("machining", "quality")]
INTENTS = {
    "draft": "起草动作", "machine": "设备停机的影响与对策", "handle": "某个异常怎么处理", "order": "新订单能不能接（算料）",
    "cost": "工单成本为什么超", "late": "订单为什么晚 / 交期", "bottleneck": "瓶颈在哪", "material": "物料够不够",
    "quality": "质量趋势", "anomalies": "现在有哪些异常", "object": "查一个对象", "overview": "全厂概况",
}


def init(db):
    db.x(SCHEMA)


# ====================================================================== 一次运行：引用与步骤
class Run:
    def __init__(self, u, kind="chat"):
        self.u, self.kind = u, kind
        self.refs, self._idx = [], {}
        self.steps = []
        self.outputs = []            # 工具的完整结果（数字核对用；运行记录里存的是截断后的）
        self.t0 = time.time()

    def ref(self, kind, key, label, url=None, **extra):
        k = (kind, str(key))
        if k in self._idx:
            return self._idx[k]
        n = len(self.refs) + 1
        self.refs.append(dict({"n": n, "kind": kind, "key": str(key), "label": label, "url": url}, **extra))
        self._idx[k] = n
        return n

    def obj(self, type_, key, display=None):
        from hub.ont import schema as S
        lab = S.get().types.get(type_, {}).get("label", type_)
        return self.ref("object", "{}|{}".format(type_, key), "{} {}".format(lab, display or key), "/ont/{}/{}".format(type_, key), type=type_)

    def msg(self, seq, label):
        return self.ref("message", seq, label, None, seq=seq)

    def anomaly(self, a):
        return self.ref("anomaly", a["id"], "异常 A-{:05d} {}".format(a["id"], a["title"]), "/ont?view=anomalies&a={}".format(a["id"]))

    def scenario(self, sid, title):
        return self.ref("scenario", sid, "推演 SC-{:05d} {}".format(sid, title), "/ont/sim?scenario={}".format(sid))

    def page(self, key, label, url):
        return self.ref("page", key, label, url)


# ====================================================================== 数字核对
def _norm(s):
    s = s.replace(",", "")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.lstrip("0") or "0"


def _variants(x):
    out = {_norm(repr(x)) if isinstance(x, float) else _norm(str(x))}
    for v in (x, x * 100, x / 100, x / 60, x * 60, x / 24, x * 24, x / 1440, x / 3600):
        for d in (0, 1, 2):
            r = round(v, d)
            out.add(_norm(("{:.%df}" % d).format(r)))
    return out


def source_numbers(texts):
    nums = set()
    for t in texts:
        t = re.sub(r"(?<=\d)T(?=\d)", " ", t)
        for s in NUM.findall(t):
            try:
                nums |= _variants(float(s.replace(",", "")))
            except ValueError:
                continue
            nums.add(_norm(s))
    return nums


def check_answer(answer, sources, nrefs):
    """回答里的数字逐个核对；引用编号不能越界。返回 {ok, unverified:[{sentence, numbers}], bad_refs:[...]}"""
    src = source_numbers(sources)
    unverified = []
    body = REF.sub("", answer)
    for sent in re.split(r"(?<=[。；！？\n])", body):
        bad = []
        for s in NUM.findall(sent):
            n = _norm(s)
            if n in src or len(n) == 1 and n in "0123456789":      # 一位数（“三个方案”“第 2 步”）不核对
                continue
            bad.append(s)
        if bad:
            unverified.append({"sentence": sent.strip(), "numbers": bad})
    bad_refs = sorted({int(m) for m in REF.findall(answer) if not 1 <= int(m) <= nrefs})
    return {"ok": not unverified and not bad_refs, "unverified": unverified, "bad_refs": bad_refs}


# ====================================================================== 工具
class Tools:
    """工具层：包装 17A–17C 的接口。每个工具返回可 JSON 化的结果，对象 / 消息 / 异常 / 推演都带引用编号 ref。"""

    def __init__(self, H, u, run, locked=None):
        self.H, self.db, self.u, self.run = H, H.db, u, run
        self.mode = u["mode"]
        self.locked = locked or (lambda u, aid=None: False)

    # ---- 权限
    def _level(self):
        from hub.ont.api import level
        return level(self.u)

    def _visible(self, t):
        from hub.ont import schema as S
        onto = S.get()
        return t in onto.types and int(onto.types[t].get("sensitivity", 0) or 0) <= self._level()

    def _ctx(self):
        from hub.ont import anomaly as A
        return A.Ctx(self.db, self.mode)

    def _chain(self, ch):
        from hub.ont.api import filter_chain
        ch = filter_chain(ch, self._level())
        nodes = []
        for n in (ch or {}).get("nodes", [])[:40]:
            if n.get("hidden") or n["type"] in ("Anomaly", "Hidden"):
                nodes.append({"label": n.get("display") or n.get("label"), "role": n.get("role")})
                continue
            nodes.append({"ref": self.run.obj(n["type"], n["key"], n.get("display")), "type": n["type"], "key": n["key"],
                          "display": n.get("display"), "role": n.get("role"), "values": n.get("values") or {}})
        edges = [{"from": e["from"].split("|")[-1], "to": e["to"].split("|")[-1], "label": e["label"],
                  "how": (e.get("basis") or {}).get("how")} for e in (ch or {}).get("edges", [])[:60]]
        for e in (ch or {}).get("edges", [])[:60]:
            seq = (e.get("basis") or {}).get("seq")
            if seq:
                self.run.msg(seq, "总线消息 #{}（{}）".format(seq, e["label"]))
        return {"summary": (ch or {}).get("summary", []), "nodes": nodes, "edges": edges, "scope": (ch or {}).get("scope", {})}

    # ---- ① 搜索对象
    def search_objects(self, q, type=None, limit=10):
        q = (q or "").strip()
        if not q:
            return {"results": []}
        from hub.ont import schema as S
        types = [t for t in S.get().types if self._visible(t) and (not type or t == type)]
        rows = self.db.q("select o.type, o.key, o.display from ont_alias a join ont_object o on o.mode=a.mode and o.type=a.type and o.key=a.key "
                         "where a.mode=%s and lower(a.alias)=lower(%s) limit 10", (self.mode, q))
        rows += self.db.q("select type, key, display from ont_object where mode=%s and type = any(%s) and (lower(key)=lower(%s) or search ilike %s) "
                          "order by (lower(key)=lower(%s)) desc, length(key), key limit %s",
                          (self.mode, types, q, "%" + q.replace("%", r"\%").replace("_", r"\_") + "%", q, int(limit)))
        out, seen = [], set()
        for r in rows:
            if r["type"] not in types or (r["type"], r["key"]) in seen:
                continue
            seen.add((r["type"], r["key"]))
            out.append({"ref": self.run.obj(r["type"], r["key"], r["display"]), "type": r["type"], "key": r["key"], "display": r["display"]})
        return {"results": out[:limit]}

    # ---- ② 读对象
    def get_object(self, type, key):
        if not self._visible(type):
            return {"error": "没有这类对象，或你没有权限查看"}
        r = self.db.one("select * from ont_object where mode=%s and type=%s and key=%s", (self.mode, type, key))
        if r is None:
            return {"error": "没有这个对象：{} {}".format(type, key)}
        from hub.ont import schema as S
        spec = S.get().types[type]
        lv = self._level()
        props = {spec["props"].get(p, {}).get("l", p): v for p, v in (r["props"] or {}).items()
                 if p in spec["props"] and int(spec["props"][p].get("s", spec.get("sensitivity", 0)) or 0) <= lv}
        ev = self.db.q("select ts, kind, text, src_seq as seq from ont_event where mode=%s and type=%s and key=%s order by ts desc limit 8",
                       (self.mode, type, key))
        events = []
        for e in ev:
            item = {"ts": e["ts"].isoformat(), "text": e["text"]}
            if e["seq"]:
                item["ref"] = self.run.msg(e["seq"], "{} {}：{}".format(spec["label"], key, e["text"]))
            events.append(item)
        return {"ref": self.run.obj(type, key, r["display"]), "type": type, "label": spec["label"], "key": key,
                "display": r["display"], "props": props, "recent_events": events}

    # ---- ③ 沿关系走
    def neighbors(self, type, key):
        if not self._visible(type):
            return {"error": "没有这类对象，或你没有权限查看"}
        from hub.ont import schema as S
        onto = S.get()
        rows = self.db.q("select * from ont_link where mode=%s and ((src_type=%s and src_key=%s) or (dst_type=%s and dst_key=%s)) limit 120",
                         (self.mode, type, key, type, key))
        out = []
        for lr in rows:
            fwd = (lr["src_type"], lr["src_key"]) == (type, key)
            ot, ok = (lr["dst_type"], lr["dst_key"]) if fwd else (lr["src_type"], lr["src_key"])
            if not self._visible(ot):
                continue
            spec = onto.types[lr["src_type"]].get("links", {}).get(lr["name"], {})
            out.append({"ref": self.run.obj(ot, ok), "type": ot, "key": ok, "relation": spec.get("l" if fwd else "inv", lr["name"])})
        return {"of": {"ref": self.run.obj(type, key), "type": type, "key": key}, "links": out}

    # ---- ④ 影响面（追因）
    def impact(self, type, key):
        if not self._visible(type):
            return {"error": "没有这类对象，或你没有权限查看"}
        from hub.ont import chain as CH
        return self._chain(CH.for_object(self._ctx(), type, key))

    # ---- ⑤ 指标
    def metrics(self, section="kpis"):
        ov = kpi.overview(self.db, None, self.mode)
        self.run.page("home", "首页 · 运营总览（{}）".format(ov["local_time"]), "/")
        keep = {"kpis", "machines", "orders", "week", "quality", "materials", "oee", "cost", "on_time", "wip", "bottleneck", "local_time"}
        out = {k: v for k, v in ov.items() if k in keep and (section == "all" or k == section or k == "local_time")}
        out["ref"] = self.run.page("home", "", "/")
        return out

    # ---- ⑥ 异常
    def list_anomalies(self, status="open", domain=None):
        from hub.ont import anomaly as A
        w, args = ["mode=%s"], [self.mode]
        w.append("status in ('open','ack','doing')" if status == "open" else "status in ('resolved','closed')")
        if domain:
            w.append("domain=%s")
            args.append(domain)
        rows = self.db.q("select * from anomaly where {} order by case severity when 'critical' then 0 when 'warn' then 1 else 2 end, last_seen desc "
                         "limit 30".format(" and ".join(w)), args)
        out = []
        for a in rows:
            if a["subject_type"] and not self._visible(a["subject_type"]):
                continue
            out.append({"ref": self.run.anomaly(a), "id": a["id"], "key": "A-{:05d}".format(a["id"]), "rule": a["rule"], "domain": a["domain"],
                        "severity": A.LEVEL_LABEL[a["severity"]], "status": A.STATUS_LABEL[a["status"]], "title": a["title"],
                        "text": (a["detail"] or {}).get("text"), "subject": [a["subject_type"], a["subject_key"]],
                        "first_seen": a["first_seen"].isoformat()})
        return {"anomalies": out}

    def _anomaly(self, aid):
        a = self.db.one("select * from anomaly where id=%s and mode=%s", (int(aid), self.mode))
        if a is None or (a["subject_type"] and not self._visible(a["subject_type"])):
            return None
        return a

    def get_anomaly(self, id):
        a = self._anomaly(id)
        if a is None:
            return {"error": "没有这个异常"}
        if not a["chain"]:
            from hub.ont import chain as CH
            a = dict(a, chain=CH.for_anomaly(self._ctx(), a))
        det = a["detail"] or {}
        ev = []
        for e in det.get("evidence") or []:
            if e.get("seq"):
                ev.append(self.run.msg(e["seq"], "总线消息 #{}".format(e["seq"])))
        return {"ref": self.run.anomaly(a), "id": a["id"], "title": a["title"], "text": det.get("text"), "values": det.get("values") or {},
                "status": a["status"], "severity": a["severity"], "chain": self._chain(a["chain"]), "evidence_refs": ev,
                "hint": det.get("hint")}

    # ---- ⑦ 推演
    def _snap(self, snapshot_id=None):
        if snapshot_id:
            r = self.db.one("select id, state, exact from sim_snapshot where id=%s and mode=%s", (int(snapshot_id), self.mode))
            if r:
                return r["id"], r["state"], r["exact"]
        return self.H.plan_snaps.take(self.mode)

    def _ctx_plan(self, st):
        from hub.ont import plan as P
        return P.context(self.db, self.mode, dt.datetime.fromisoformat(st["factory_now"]))

    def _save_scenario(self, title, sid, changes, result, anomaly_id=None):
        row = self.db.one("insert into scenario (mode, title, snapshot_id, changes, result, created_by, anomaly_id) values (%s,%s,%s,%s,%s,%s,%s) "
                          "returning id", (self.mode, title, sid, Jsonb(changes), Jsonb(result), "AI 代理（{}）".format(self.u.get("name")), anomaly_id))
        return row["id"]

    @staticmethod
    def _brief(r, names=None):
        sos = [s for s in r["sales_orders"] if not names or s["name"] in names]
        return {"sales_orders": [{k: s.get(k) for k in ("name", "delivery_date", "projected", "late_days", "note", "split")} for s in sos],
                "cost_total": r["cost_total"], "costs": r["costs"], "overtime_min": r["overtime_min"],
                "overtime_units": r["overtime_units"], "ok": r["ok"], "failed_checks": [c["text"] for c in r["checks"] if not c["ok"]]}

    def simulate(self, changes=None, down_unit=None, down_minutes=None, snapshot_id=None, title=None):
        from hub.ont import plan as P
        sid, st, exact = self._snap(snapshot_id)
        changes = [c for c in (changes or []) if c.get("type") != "insert_order"]
        try:
            if down_unit:
                st = P.hypothesis(st, down_unit.lower(), float(down_minutes or 60))
            r = P.simulate(st, changes, self._ctx_plan(st))
        except P.PlanError as e:
            return {"error": str(e)}
        hyp = "假设 {} 再停 {:.0f} 分钟".format(down_unit.upper(), float(down_minutes or 60)) if down_unit else None
        title = title or "；".join(x for x in [hyp, "、".join(P.CHANGE_TYPES[c["type"]] for c in changes) or "不处理"] if x)
        scid = self._save_scenario(title, sid, ([{"type": "breakdown", "unit": down_unit.lower(), "minutes": float(down_minutes or 60)}] if down_unit else []) + changes, r)
        return dict(self._brief(r), ref=self.run.scenario(scid, title), scenario_id=scid, snapshot_id=sid, exact=exact, hypothesis=hyp,
                    factory_now=st["factory_now"])

    # ---- ⑧ 按预案比较方案
    def compare_options(self, anomaly_id=None, down_unit=None, down_minutes=None, snapshot_id=None):
        from hub.ont import chain as CH
        from hub.ont import plan as P
        from hub.ont import playbook as PB
        sid, st, exact = self._snap(snapshot_id)
        hyp = None
        if anomaly_id:
            a = self._anomaly(anomaly_id)
            if a is None:
                return {"error": "没有这个异常"}
        elif down_unit:
            unit = down_unit.lower()
            try:
                st = P.hypothesis(st, unit, float(down_minutes or 60))
            except P.PlanError as e:
                return {"error": str(e)}
            hyp = "假设 {} 再停 {:.0f} 分钟".format(unit.upper(), float(down_minutes or 60))
            a = {"id": None, "rule": "P1", "subject_type": "Machine", "subject_key": unit, "detail": {"values": {}},
                 "chain": CH.for_object(self._ctx(), "Machine", unit), "title": hyp}
        else:
            return {"error": "要给出异常编号，或假设哪台设备停机多久"}
        try:
            ev = PB.evaluate(a, st, self._ctx_plan(st))
        except P.PlanError as e:
            return {"error": str(e)}
        locked = self.locked(self.u, a.get("id"))
        opts = []
        for o in ev["options"]:
            r = o["result"]
            title = "{}{} {}".format((hyp + "；") if hyp else "", o["key"], o["label"])
            hyp_ch = [{"type": "breakdown", "unit": a["subject_key"], "minutes": float(down_minutes or 60)}] if hyp else []
            scid = self._save_scenario(title, sid, hyp_ch + o["changes"], r, a.get("id"))
            item = {"key": o["key"], "label": o["label"], "kind": o["kind"], "note": o["note"], "changes": o["changes"],
                    "ref": self.run.scenario(scid, title), "scenario_id": scid,
                    "sales_orders": [{k: s.get(k) for k in ("name", "delivery_date", "projected", "late_days", "note")} for s in r["sales_orders"]],
                    "cost_total": r["cost_total"], "overtime_min": r["overtime_min"], "ok": r["ok"],
                    "failed_checks": [c["text"] for c in r["checks"] if not c["ok"]]}
            if not locked:
                item["recommended"] = o["recommended"]
            opts.append(item)
        out = {"options": opts, "affected": ev["affected"], "snapshot_id": sid, "exact": exact, "hypothesis": hyp,
               "factory_now": st["factory_now"], "anomaly_id": a.get("id")}
        if a.get("id"):
            out["anomaly_ref"] = self.run.anomaly(a)
        if locked:
            out["note"] = "比对模式：你提交自己的分析之前，不显示建议和推荐理由"
        else:
            out["recommended"], out["reason"] = ev["recommended"], ev["reason"]
        return out

    # ---- ⑨ 起草动作（只起草）
    def draft_action(self, changes, anomaly_id=None, scenario_id=None, snapshot_id=None):
        from hub.ont import actions as AC
        from hub.ont import plan as P
        if self.mode == "teach" and not self.u.get("teacher"):
            return {"error": "教学模式下 AI 不代做：请自己在推演工作台或指挥台采纳方案"}
        if not AC.can_initiate(self.u):
            return {"error": "动作由计划员或厂长发起"}
        changes = [c for c in (changes or []) if c.get("type") in AC.TYPES]
        if not changes:
            return {"error": "没有可以起草的动作（假设停机、插单只能用于推演）"}
        try:
            sid, st, exact = self._snap(snapshot_id)
            tr = dict(AC.trial(self.db, self.H.plan_snaps, self.mode, changes, st), snapshot_id=sid)
            ids = [AC.create(self.db, self.mode, self.u, c["type"], c, scenario_id, anomaly_id, tr) for c in changes]
        except (AC.ActionError, P.PlanError) as e:
            return {"error": str(e)}
        for i in ids:
            AC.log(self.db, i, "AI 代理", "agent", "AI 代理替 {} 起草；要发起人在动作收件箱提交，再按权限审批".format(self.u.get("name")))
        refs = [self.run.ref("action", i, "动作 ACT-{:05d}（草稿）".format(i), "/ont/actions?box=mine") for i in ids]
        return {"drafted": ["ACT-{:05d}".format(i) for i in ids], "refs": refs, "status": "草稿",
                "next": "在动作收件箱“我发起的”里提交，再按权限审批后才执行"}

    # ---- 原助手的工具
    def query_messages(self, types=None, topic_like=None, corr=None, hours=24, limit=30):
        hours = min(float(hours or 24), 24 * 14)
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
        rows = self.db.messages(types, since=since, mode=self.mode, topic_like=topic_like, corr=corr, limit=min(int(limit or 30), 50), order="desc")
        return {"messages": [{"ref": self.run.msg(r["_seq"], "总线消息 #{} {}".format(r["_seq"], r["type"])), "seq": r["_seq"], "ts": r["ts"],
                              "topic": r["_topic"], "type": r["type"], "corr": r.get("corr"), "data": r["data"]} for r in rows]}

    def work_order_cost(self, work_order):
        c = mrp.wo_cost(self.db, work_order, self.mode)
        if not c:
            return {"error": "该工单还没有加工记录"}
        return dict(c, ref=self.run.obj("WorkOrder", work_order))

    def plan_order(self, qty, delivery_date, customer=None, item="WQR-105"):
        return mrp.plan_order(self.db, customer or F.CUSTOMERS[0], item, int(qty), delivery_date, self.mode)

    def propose_order(self, qty, delivery_date, customer=None, item="WQR-105"):
        if self.mode == "teach":
            return {"error": "教学模式下 AI 不代做：请学生在计划员工作区自己录入订单"}
        from hub.ai import _order_title
        pv = mrp.plan_order(self.db, customer or F.CUSTOMERS[0], item, int(qty), delivery_date, self.mode)
        pid = self.H.ai.propose("create_order_and_plan", pv, self.mode, self.u.get("name"), _order_title(pv))
        return {"proposal_id": pid, "status": "pending", "preview": pv, "ref": self.run.ref("proposal", pid, "提议 " + pid, "/planner")}

    # ---- 调用入口（模型和规则版共用；每步记进运行记录）
    def call(self, name, args):
        fn = getattr(self, name, None) if name in TOOL_NAMES else None
        t = time.time()
        try:
            out = fn(**(args or {})) if fn else {"error": "未知工具 " + str(name)}
        except TypeError as e:
            out = {"error": "参数不对：{}".format(e)}
        except Exception as e:  # noqa: BLE001
            log.exception("工具 %s 出错", name)
            out = {"error": "{} 出错：{}".format(name, type(e).__name__)}
        self.run.outputs.append(json.dumps(out, ensure_ascii=False, default=str))
        self.run.steps.append({"tool": name, "args": args or {}, "ms": int((time.time() - t) * 1000),
                               "summary": _summary(out), "output": _clip(out)})
        return out


def _clip(out, n=6000):
    s = json.dumps(out, ensure_ascii=False, default=str)
    return out if len(s) <= n else {"_clipped": s[:n]}


def _summary(out):
    if not isinstance(out, dict):
        return ""
    if out.get("error"):
        return "出错：" + out["error"]
    for k, f in (("results", "找到 {} 个对象"), ("anomalies", "{} 个异常"), ("options", "{} 个方案"), ("messages", "{} 条消息"),
                 ("links", "{} 条关系"), ("nodes", "链条 {} 个节点"), ("drafted", "起草 {} 个动作")):
        if k in out:
            return f.format(len(out[k]))
    if "sales_orders" in out:
        return "推演：多花 ${:,.0f}".format(out.get("cost_total") or 0)
    return "完成"


TOOL_NAMES = ["search_objects", "get_object", "neighbors", "impact", "metrics", "list_anomalies", "get_anomaly", "simulate",
              "compare_options", "draft_action", "query_messages", "work_order_cost", "plan_order", "propose_order"]

_S = lambda **p: {"type": "object", "properties": p}                                    # noqa: E731
_CH = {"type": "array", "items": {"type": "object"}, "description": "改动清单（与推演工作台相同）：reassign / reorder / overtime / expedite / "
       "urgent_purchase / outsource / split_delivery，参数照 compare_options 返回的 changes"}
TOOLS = [
    {"name": "search_objects", "description": "在工厂本体里按编号、名称、别名搜索对象（设备、工单、订单、物料、零件、客户……）",
     "input_schema": dict(_S(q={"type": "string"}, type={"type": "string", "description": "可选：限定类型，如 Machine、SalesOrder"}), required=["q"])},
    {"name": "get_object", "description": "读一个对象：属性和最近事件", "input_schema": dict(_S(type={"type": "string"}, key={"type": "string"}), required=["type", "key"])},
    {"name": "neighbors", "description": "列出一个对象直接相连的对象和关系", "input_schema": dict(_S(type={"type": "string"}, key={"type": "string"}), required=["type", "key"])},
    {"name": "impact", "description": "追因与影响面：从一个对象出发沿本体链接找原因、算影响（停机→工单→订单→客户，缺料→工单→订单……）",
     "input_schema": dict(_S(type={"type": "string"}, key={"type": "string"}), required=["type", "key"])},
    {"name": "metrics", "description": "看板指标（全部从历史库算）。section：kpis/machines/orders/week/quality/materials/oee/cost/all",
     "input_schema": _S(section={"type": "string"})},
    {"name": "list_anomalies", "description": "厂情中枢的异常清单（规则自动识别）", "input_schema": _S(status={"type": "string", "enum": ["open", "closed"]}, domain={"type": "string"})},
    {"name": "get_anomaly", "description": "读一个异常：说明、数值、因果链", "input_schema": dict(_S(id={"type": "integer"}), required=["id"])},
    {"name": "simulate", "description": "推演：当前快照（可加“假设某设备再停 N 分钟”）+ 改动，快进算每张订单的预计完成、晚几天、多花的钱。不影响真车间",
     "input_schema": _S(changes=_CH, down_unit={"type": "string", "description": "假设停机的设备编号，如 grd-01"},
                        down_minutes={"type": "number"})},
    {"name": "compare_options", "description": "按处理预案自动推演几个候选方案并排序推荐。给异常编号，或给“假设某设备再停 N 分钟”",
     "input_schema": _S(anomaly_id={"type": "integer"}, down_unit={"type": "string"}, down_minutes={"type": "number"})},
    {"name": "draft_action", "description": "把方案起草成动作草稿（只起草，不提交、不执行；要人在动作收件箱提交、审批）。教学模式学生不可用",
     "input_schema": dict(_S(changes=_CH, anomaly_id={"type": "integer"}, scenario_id={"type": "integer"}), required=["changes"])},
    {"name": "query_messages", "description": "查总线历史消息。types 如 [\"machine.event\"]，topic_like 用 SQL like，corr 为工单号或提议号",
     "input_schema": _S(types={"type": "array", "items": {"type": "string"}}, topic_like={"type": "string"}, corr={"type": "string"},
                        hours={"type": "number"}, limit={"type": "integer"})},
    {"name": "work_order_cost", "description": "按总线历史算一张工单的标准成本、实际成本和按工序的差异",
     "input_schema": dict(_S(work_order={"type": "string"}), required=["work_order"])},
    {"name": "plan_order", "description": "对一张假设的新订单做算料（MRP），只计算不写入",
     "input_schema": dict(_S(customer={"type": "string"}, item={"type": "string"}, qty={"type": "integer"}, delivery_date={"type": "string"}),
                          required=["qty", "delivery_date"])},
    {"name": "propose_order", "description": "起草“接单并算料”提议（销售订单 + 工单 + 请购单），等人确认后才写入 ERPNext。仅生产模式可用",
     "input_schema": dict(_S(customer={"type": "string"}, item={"type": "string"}, qty={"type": "integer"},
                             delivery_date={"type": "string", "description": "YYYY-MM-DD"}), required=["qty", "delivery_date"])},
]


# ====================================================================== 代理
class Agent:
    def __init__(self, H, llm, locked=None):
        self.H, self.db, self.llm = H, H.db, llm
        self.locked = locked

    def student(self, u):
        return u["mode"] == "teach" and not u.get("teacher")

    def tools_for(self, u):
        drop = set()
        if u["mode"] == "teach":
            drop.add("propose_order")
        if self.student(u):
            drop.add("draft_action")
        return [t for t in TOOLS if t["name"] not in drop]

    # ---- 入口
    def ask(self, u, messages, kind="chat", anomaly_id=None):
        run = Run(u, kind)
        tools = Tools(self.H, u, run, self.locked)
        question = messages[-1]["content"] if messages else ""
        engine, note, usage = "rules", None, None
        if self.llm is not None and self.llm.available():
            try:
                text = self._llm(u, messages, tools)
                engine = self.llm.name
            except Exception as e:  # noqa: BLE001
                log.exception("模型调用失败，改用规则版")
                note = "模型暂时不可用（{}），以下为规则版回答".format(type(e).__name__)
                run.steps.clear()
                run.outputs.clear()
                run.refs.clear()
                run._idx.clear()
                text, intent = Rules(tools, self.student(u)).answer(question, messages)
        else:
            text, intent = Rules(tools, self.student(u)).answer(question, messages)
        sources = [question] + [m["content"] for m in messages if m["role"] == "user"] + \
                  run.outputs
        chk = check_answer(text, sources, len(run.refs))
        rid = self._save(u, kind, question, engine, run, text, chk, usage, anomaly_id)
        drafted = [r["key"] for r in run.refs if r["kind"] == "action"]
        props = [r["key"] for r in run.refs if r["kind"] == "proposal"]
        out = {"answer": text, "refs": run.refs, "check": chk, "run_id": rid, "engine": engine, "tools": [s["tool"] for s in run.steps],
               "proposals": props, "actions": drafted}
        if note:
            out["note"] = note
        return out

    def _system(self, u):
        from hub.ai import ROLE_NAMES
        base = ("你是“问渠减速器厂”的 AI 工厂代理，是全厂员工的同事。你通过工厂本体（设备、工单、订单、物料、零件、客户等对象和它们的关系）、"
                "异常与因果链、推演（快进副本）和历史库看到全厂。回答用中文，简洁，先给结论再给依据。\n"
                "规矩：① 数据只来自工具结果，不编造；② 每个结论后面用 [n] 标出依据，n 是工具结果里对象、消息、异常、推演的 ref 编号；"
                "③ 回答里的数字必须是工具结果里出现过的（可以四舍五入、换算成百分比或小时），不确定就再查；"
                "④ 处理方案先用 compare_options 或 simulate 推演再说，不凭感觉；⑤ 写操作只能起草（draft_action 动作草稿、propose_order 提议），"
                "起草前先问对方要不要，人提交、审批后才执行。\n"
                "工厂：唯一成品 WQR-105 二级圆柱齿轮减速器；本轮闭环零件是输出轴 SH-301（下料 → 粗车 → 调质 → 精车 → 铣键槽 → 磨外圆 → 检验）。"
                "设备编号：{}。今天是 {}。").format("、".join("{} {}".format(k, UNITS[k][1]) for k in MACHINES),
                                               dt.datetime.now(kpi.TZ).strftime("%Y-%m-%d %A"))
        if self.student(u):
            base += ("\n现在是教学模式，对方是扮演“{}”的学生。你是助教：引导他思考，告诉他去哪一页、看哪个数据，解释概念；"
                     "不要直接替他完成实验任务，不要直接说出实验题的答案（停机设备、延期订单、缺料、成本差异、该选哪个方案），"
                     "不起草任何东西。").format(ROLE_NAMES.get(u.get("role"), u.get("role")))
        elif u["mode"] == "teach":
            base += "\n现在是教学模式，对方是老师，可以给完整的分析。"
        else:
            base += "\n现在是生产模式，对方是{}。可以直接帮他把事办完（写操作仍只起草）。".format(ROLE_NAMES.get(u.get("role"), u.get("role")))
        return base

    def _llm(self, u, messages, tools):
        text, _trace = self.llm.run(self._system(u), messages[-12:], self.tools_for(u), tools.call, max_turns=8)
        return text

    def _save(self, u, kind, q, engine, run, text, chk, usage, anomaly_id):
        try:
            r = self.db.one('insert into ai_run (mode, "user", role, kind, question, engine, steps, answer, refs, "check", duration_ms, usage, anomaly_id) '
                            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                            (u["mode"], u.get("name"), u.get("role"), kind, q, engine, Jsonb(json.loads(json.dumps(run.steps, ensure_ascii=False, default=str))),
                             text, Jsonb(run.refs), Jsonb(chk), int((time.time() - run.t0) * 1000), Jsonb(usage) if usage else None, anomaly_id))
            return r["id"]
        except Exception:  # noqa: BLE001
            log.exception("保存运行记录失败")
            return None

    # ---- 让 AI 分析某个异常
    def analyze(self, u, aid):
        return self.ask(u, [{"role": "user", "content": "分析异常 A-{:05d}：原因、影响，以及怎么处理最划算".format(int(aid))}], kind="analyze",
                        anomaly_id=int(aid))


# ====================================================================== 规则版
UNIT_NAMES = sorted([(UNITS[k][1], k) for k in MACHINES], key=lambda x: -len(x[0]))
ALIASES = {"磨床": "grd-01", "车床a": "cnc-l01-a", "车床b": "cnc-l01-b", "锯床": "saw-01", "热处理": "ht-01", "键槽": "key-01",
           "滚齿": "hob-01", "检验站": "qc-01"}
CN_NUM = {"半": 0.5, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def find_machine(q):
    ql = q.lower().replace(" ", "")
    for k in sorted(MACHINES, key=len, reverse=True):
        if k in ql:
            return k
    for name, k in UNIT_NAMES:
        if name.replace(" ", "").lower() in ql:
            return k
    for a, k in ALIASES.items():
        if a in ql:
            return k
    return None


def find_minutes(q):
    m = re.search(r"(\d+(?:\.\d+)?|[半一两二三四五六七八九十]+)\s*(个)?\s*(分钟|小时|钟头|天|日)", q)
    if not m:
        return None
    s = m.group(1)
    v = float(s) if s[0].isdigit() else (CN_NUM.get(s) if s in CN_NUM else (10 + CN_NUM.get(s[-1], 0) if s.startswith("十") else None))
    if v is None:
        return None
    unit = m.group(3)
    return v * (1 if unit == "分钟" else 60 if unit in ("小时", "钟头") else 1440)


def find_item(q):
    ql = q.upper()
    for code in sorted(F.ITEMS, key=len, reverse=True):
        if code in ql or (code.startswith("BRG-") and code[4:] in ql):
            return code
    for code, v in F.ITEMS.items():
        zh = v[0].split(" ")[0]
        if len(zh) >= 2 and zh in q:
            return code
    return None


class _Recorder:
    """规则版调工具也走 Tools.call，这样每一步都进运行记录、数字核对也能用上"""

    def __init__(self, tools):
        self._t = tools

    def __getattr__(self, name):
        if name in TOOL_NAMES:
            return lambda *a, **kw: self._t.call(name, dict(zip(_argnames(self._t, name), a), **kw))
        return getattr(self._t, name)


def _argnames(tools, name):
    import inspect
    return [p for p in inspect.signature(getattr(tools, name)).parameters]


class Rules:
    """没配模型时的规则版：识别十类问题，按固定步骤调工具，回答带 [n] 引用。"""

    def __init__(self, tools, student):
        self.t, self.student = _Recorder(tools), student

    def answer(self, q, messages=None):
        intent = self.intent(q)
        fn = getattr(self, "a_" + intent)
        try:
            return fn(q), intent
        except Exception:  # noqa: BLE001
            log.exception("规则版回答出错（%s）", intent)
            return "这个问题我按规则没答出来。可以换个说法，或在厂情中枢指挥台里看。", intent

    def intent(self, q):
        if re.search(r"起草", q) and re.search(r"A-\d{5}|方案\s*[A-H]", q):
            return "draft"
        if re.search(r"(\d+)\s*台.*?(\d{1,2})\s*月\s*(\d{1,2})\s*日", q) and re.search(r"订单|安排|接单|生产|交货|WQR", q):
            return "order"
        if re.search(r"A-\d{5}", q) or (re.search(r"怎么办|怎么处理|方案|对策|建议", q) and not find_machine(q)):
            return "handle"
        if find_machine(q) and re.search(r"停|坏|故障|影响|怎么办|方案", q):
            return "machine"
        if re.search(r"成本", q):
            return "cost"
        if re.search(r"SAL-ORD-\d{4}-\d{5}", q) or re.search(r"延期|晚|交期|来得及|准时", q):
            return "late"
        if re.search(r"瓶颈", q):
            return "bottleneck"
        if re.search(r"质量|超差|漂移|合格|测量|尺寸|控制图|变大|变小", q):
            return "quality"
        if re.search(r"库存|缺.{0,3}料|够不够|物料|请购|轴承|钢", q) or find_item(q):
            return "material"
        if re.search(r"异常|问题|出了什么事|有什么事|报警", q):
            return "anomalies"
        if re.search(r"MFG-WO-\d{4}-\d{5}|[A-Z]{2,}-\d", q.upper()) or find_machine(q):
            return "object"
        return "overview"

    # ---- 教学模式（学生）：只给方向
    HINTS = {
        "machine": "提示：先在首页“车间实况”里找停机的设备，再打开厂情中枢指挥台里对应的异常，看中间的因果链——它连到哪些工单、哪张订单？"
                   "然后在推演工作台自己试几个方案（加班、改派、维修加急），比较交期和多花的钱。",
        "handle": "提示：处理方案要先推演再决定。在推演工作台用当前快照试至少 3 个方案，比较“准时、多花的钱、加班工时”，选一个并写下理由。",
        "late": "提示：先看“订单与交期”里这张订单的进度，再看“车间实况”里有没有设备停机、哪里在排队。交期风险 = 剩余工作量 ÷ 瓶颈能力。",
        "material": "提示：在首页“物料”一栏看哪些物料低于安全库存；再想想在手工单和订单还要用多少。作为计划员，什么时候请购、请购多少？",
        "quality": "提示：打开质量页的控制图，看最近几件的测量值是不是在单向移动。想一想：哪道工序、哪台设备、什么磨损会让尺寸慢慢变大？",
        "anomalies": "提示：首页的 AI 今日简报和厂情中枢的异常清单会列出正在发生的事。先自己从看板里找：哪台设备停了、哪张订单有风险、哪种物料不够？",
        "cost": "提示：成本差异 = 实际 − 标准。标准只按单件工时算；实际还要加上每道工序的调整时间和换刀。在“厂长”工作区打开工单的成本分解，看哪道工序差得最多。",
        "bottleneck": "提示：瓶颈是负荷最满、前面排队最多的设备。对比“车间实况”各台设备的排队件数，再看“本周计划与实际”下方的说明。",
        "draft": "教学模式下 AI 不代做：请在指挥台或推演工作台自己采纳方案，生成动作。",
    }

    def _hint(self, intent):
        return self.HINTS[intent]

    def _so_line(self, s):
        if s.get("late_days") is None:
            return "{} {}".format(s["name"], s.get("note") or "推演范围内做不完")
        return "{} 预计 {} 交，{}".format(s["name"], s["projected"], "晚 {} 天".format(s["late_days"]) if s["late_days"] > 0 else
                                       "按时（余 {} 天）".format(-s["late_days"]))

    def _options_text(self, r):
        lines = []
        for o in r["options"]:
            sos = "；".join(self._so_line(s) for s in o["sales_orders"] if s["name"] in r["affected"]) or "没有受影响的订单"
            lines.append("{} {}：{}，多花 ${:,.0f}{}{} [{}]".format(o["key"], o["label"], sos, o["cost_total"],
                                                              "，加班 {} 分钟".format(o["overtime_min"]) if o["overtime_min"] else "",
                                                              "（校验不通过：{}）".format("；".join(o["failed_checks"])) if not o["ok"] else "",
                                                              o["ref"]))
        return lines

    def _draft_offer(self, r):
        if self.t.u["mode"] == "teach" and not self.t.u.get("teacher"):
            return ""
        rec = r.get("recommended")
        if not rec or rec == next((o["key"] for o in r["options"] if o["kind"] == "none"), None):
            return ""
        if r.get("anomaly_id"):
            return "要起草，请说“起草 A-{:05d} 的方案 {}”；起草后在动作收件箱提交、审批才执行。".format(r["anomaly_id"], rec)
        return "这是假设情况，没有对应的异常；真的发生后，在指挥台打开那个异常就能采纳。"

    # ---- 各类问题
    def a_machine(self, q):
        if self.student:
            return self._hint("machine")
        unit = find_machine(q)
        mins = find_minutes(q)
        imp = self.t.impact("Machine", unit)
        mref = self.t.run.obj("Machine", unit, UNITS[unit][1])
        out = []
        sos = imp["scope"].get("sales_orders") or []
        wos = imp["scope"].get("work_orders") or []
        so_refs = "、".join("{} [{}]".format(s, self.t.run.obj("SalesOrder", s)) for s in sos)
        if mins and re.search(r"再|要是|如果|假如|假设", q):
            r = self.t.compare_options(down_unit=unit, down_minutes=mins)
            if r.get("error"):
                return "推演没做成：{}".format(r["error"])
            out.append("{}（{}）[{}] 如果再停 {:g} 小时：影响{}。".format(UNITS[unit][1], unit.upper(), mref, mins / 60,
                                                              " " + so_refs if so_refs else "的订单推演里没有"))
        else:
            open_a = self.t.db.one("select * from anomaly where mode=%s and subject_type='Machine' and subject_key=%s and status in ('open','ack','doing') "
                                   "order by last_seen desc limit 1", (self.t.mode, unit))
            out.append("{}（{}）[{}]：{}".format(UNITS[unit][1], unit.upper(), mref, "；".join(imp["summary"][:3]) or "没有排着的工单"))
            if wos:
                out.append("排在它上面的工单：{}；连到订单：{}。".format(
                    "、".join("{} [{}]".format(w, self.t.run.obj("WorkOrder", w)) for w in wos[:6]), so_refs or "无"))
            if not open_a:
                out.append("它现在没有开着的停机异常。想看“如果它再停一阵”，可以问：“{} 再停 4 小时会怎样？”".format(UNITS[unit][1]))
                return "\n".join(out)
            r = self.t.compare_options(anomaly_id=open_a["id"])
            if r.get("error"):
                return "\n".join(out + ["推演没做成：{}".format(r["error"])])
            out.append("对应的异常 {} [{}]。按预案推演了 {} 个方案：".format("A-{:05d}".format(open_a["id"]), r["anomaly_ref"], len(r["options"])))
        out += self._options_text(r)
        if r.get("reason"):
            out.append(r["reason"])
        if r.get("note"):
            out.append(r["note"])
        offer = self._draft_offer(r)
        if offer:
            out.append(offer)
        out.append("（推演用{}快照，工厂时间 {}；不影响真车间。）".format("精确" if r["exact"] else "近似", r["factory_now"][:16].replace("T", " ")))
        return "\n".join(out)

    def _pick_anomaly(self, q):
        m = re.search(r"A-(\d{5})", q)
        if m:
            return int(m.group(1))
        lst = self.t.list_anomalies()["anomalies"]
        with_plays = [a for a in lst if a["rule"] in _playbook_rules()]
        return (with_plays or lst or [{"id": None}])[0]["id"]

    def a_handle(self, q):
        if self.student:
            return self._hint("handle")
        aid = self._pick_anomaly(q)
        if not aid:
            return "现在没有开着的异常，不需要处理。"
        a = self.t.get_anomaly(aid)
        if a.get("error"):
            return a["error"]
        out = ["异常 A-{:05d} [{}]：{}。".format(aid, a["ref"], a["text"] or a["title"])]
        if a["chain"]["summary"]:
            out.append("影响：" + "；".join(a["chain"]["summary"][:3]) + "。")
        r = self.t.compare_options(anomaly_id=aid)
        if r.get("error"):
            return "\n".join(out + ["推演没做成：{}".format(r["error"])])
        if not r["options"] or len(r["options"]) == 1:
            out.append("这类异常还没有推演预案，按说明处理：{}".format(a.get("hint") or "见异常详情"))
            return "\n".join(out)
        out.append("按预案推演了 {} 个方案：".format(len(r["options"])))
        out += self._options_text(r)
        if r.get("reason"):
            out.append(r["reason"])
        if r.get("note"):
            out.append(r["note"])
        offer = self._draft_offer(r)
        if offer:
            out.append(offer)
        return "\n".join(out)

    def a_draft(self, q):
        if self.student:
            return self._hint("draft")
        m = re.search(r"A-(\d{5})", q)
        k = re.search(r"方案\s*([A-H])", q)
        if not m or not k:
            return "请说清楚异常编号和方案，例如“起草 A-00012 的方案 C”。"
        aid = int(m.group(1))
        r = self.t.compare_options(anomaly_id=aid)
        if r.get("error"):
            return r["error"]
        o = next((x for x in r["options"] if x["key"] == k.group(1)), None)
        if o is None:
            return "A-{:05d} 没有方案 {}（现有：{}）。".format(aid, k.group(1), "、".join(x["key"] for x in r["options"]))
        if not o["changes"]:
            return "方案 {}（{}）不需要做任何动作。".format(o["key"], o["label"])
        d = self.t.draft_action(o["changes"], anomaly_id=aid, scenario_id=o["scenario_id"], snapshot_id=r["snapshot_id"])
        if d.get("error"):
            return "没能起草：" + d["error"]
        return "已起草 {}（{}）[{}]，状态是草稿。{}。推演依据 [{}]。".format(
            "、".join(d["drafted"]), o["label"], "][".join(str(x) for x in d["refs"]), d["next"], o["ref"])

    def a_order(self, q):
        m = re.search(r"(\d+)\s*台.*?(\d{1,2})\s*月\s*(\d{1,2})\s*日", q)
        qty, mon, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        due = dt.date(dt.datetime.now(kpi.TZ).year, mon, day).isoformat()
        from hub.ai import _cust_keys
        cust = next((c for c in F.CUSTOMERS if any(k in q for k in _cust_keys(c))), F.CUSTOMERS[0])
        pv = self.t.plan_order(qty, due, cust)
        if self.t.mode == "teach":
            stock = next((r["stock"] for r in pv["mrp"] if r["item_code"] == "RM-45-D50"), 0)
            return ("这是计划员的任务，我不替你录入。提示：① 在“计划员”工作区点“新建订单”；② 看算料结果里 SH-301 要几根、45 钢够不够——"
                    "现在库存 {:g} kg，每根用 2.8 kg；③ 想想安全库存为什么也要算进去。").format(stock)
        p = self.t.call("propose_order", {"qty": qty, "delivery_date": due, "customer": cust})
        if p.get("error"):
            return p["error"]
        wo = pv["work_orders"][0] if pv["work_orders"] else None
        mr = "、".join("{} {:g}{}".format(x["item_code"], x["qty"], kpi.unit_label(x["uom"])) for x in pv["material_requests"])
        return ("已起草提议 {} [{}]：销售订单 {} × {} 台，交期 {}；工单 SH-301 × {}，计划 {} 至 {}；请购：{}。{}"
                "请在下方预览后确认，确认后才写入 ERPNext。").format(
            p["proposal_id"], p["ref"], cust.split(" ")[0], qty, due, wo["qty"] if wo else 0, wo["planned_start_date"] if wo else "—",
            wo["expected_delivery_date"] if wo else "—", mr or "无", ("注意：" + "；".join(pv["warnings"]) + "。") if pv["warnings"] else "")

    def a_cost(self, q):
        if self.student:
            return self._hint("cost")
        m = re.search(r"(MFG-WO-\d{4}-\d{5})", q)
        wo = m.group(1) if m else _latest_wo(self.t.db, self.t.mode)
        if not wo:
            return "还没有找到可计算成本的加工记录。"
        c = self.t.call("work_order_cost", {"work_order": wo})
        if c.get("error"):
            return c["error"]
        return ("{} [{}] 已完工 {} 件：加工标准成本 ${:.2f}，实际 ${:.2f}，高 ${:.2f}（{:+.1f}%）。其中调整与换刀 ${:.2f}，加工超时 ${:.2f}；"
                "差得最多的是“{}”。依据：{} 的 {} 条完工事件。").format(
            wo, c["ref"], c["parts_finished"], c["std_cost"], c["actual_cost"], c["variance"], c["variance_pct"] or 0, c["setup_cost"],
            c["overrun_cost"], c["worst_operation"], c["evidence"]["topic"], c["evidence"]["messages"])

    def a_late(self, q):
        if self.student:
            return self._hint("late")
        ov = self.t.call("metrics", {"section": "orders"})
        m = re.search(r"(SAL-ORD-\d{4}-\d{5})", q)
        orders = ov.get("orders") or []
        o = next((x for x in orders if m and x["name"] == m.group(1)), None) or next((x for x in orders if x["tone"] == "bad"), None) or \
            (orders[0] if orders else None)
        if not o:
            return "目前没有在手订单。"
        ch = self.t.call("impact", {"type": "SalesOrder", "key": o["name"]})
        so = self.t.run.obj("SalesOrder", o["name"])
        why = "；".join(ch.get("summary", [])[:3])
        return "{}（{}，{:g} 台，交期 {}）[{}]：{}，预计完成 {}。{}看板依据 [{}]。".format(
            o["name"], o["customer"].split(" ")[0], o["qty"], o["delivery_date"], so, o["risk"], o["projected"] or "—",
            ("原因：" + why + "。") if why else "", ov["ref"])

    def a_bottleneck(self, q):
        if self.student:
            return self._hint("bottleneck")
        ov = self.t.call("metrics", {"section": "all"})
        b = ov["week"]["bottleneck"]
        if not b:
            return "本周还没有足够的数据判断瓶颈。"
        o = ov["oee"]["machines"].get(b, {})
        return "本周瓶颈是 {}（{}）[{}]：负荷最高，今日 OEE {}，停机 {:.0f} 分钟。看板依据 [{}]。".format(
            b.upper(), UNITS[b][1], self.t.run.obj("Machine", b, UNITS[b][1]), "—" if o.get("oee") is None else "{:.0f}%".format(o["oee"] * 100),
            (o.get("down_s", 0)) / 60, ov["ref"])

    def a_material(self, q):
        if self.student:
            return self._hint("material")
        ov = self.t.call("metrics", {"section": "materials"})
        item = find_item(q)
        mats = ov.get("materials") or []
        rows = [m for m in mats if not item or m["code"] == item] or mats
        low = [m for m in rows if m["tone"] == "bad"]
        out = []
        for m in (low or rows)[:6]:
            r = self.t.run.obj("Item", m["code"], m["name"])
            out.append("{}（{}）[{}]：{}，库存 {}，在手工单与订单还需 {:g}。".format(m["name"], m["code"], r, m["status"], m["qty_text"], m["need"]))
        for m in low[:3]:
            ch = self.t.call("impact", {"type": "Item", "key": m["code"]})
            if ch.get("summary"):
                out.append("影响：" + "；".join(ch["summary"][:2]) + "。")
        if low:
            a = self.t.db.one("select id from anomaly where mode=%s and subject_type='Item' and subject_key=%s and status in ('open','ack','doing') limit 1",
                              (self.t.mode, low[0]["code"]))
            if a:
                out.append("处理方案可以问：“A-{:05d} 怎么处理？”".format(a["id"]))
        elif item:
            out.append("够用。")
        out.append("看板依据 [{}]。".format(ov["ref"]))
        return "\n".join(out)

    def a_quality(self, q):
        if self.student:
            return self._hint("quality")
        ov = self.t.call("metrics", {"section": "quality"})
        ch = ov["quality"]["chart"]
        out = []
        if ch.get("points"):
            refs = [self.t.run.msg(p["seq"], "测量 {}（总线消息 #{}）".format(p.get("serial") or "", p["seq"])) for p in ch["points"][-5:] if p.get("seq")]
            out.append("{} [{}]：最近 5 件均值上移 {:.1f} µm，距上限还有 {:.1f} µm{} 测量记录 {}".format(
                ch["title"], ov["ref"], ch["shift_um"], ch["margin_um"], "，尚未超差。" if ch["margin_um"] > 0 else "，已经超差。",
                "".join("[{}]".format(r) for r in refs)))
        an = [a for a in self.t.list_anomalies(domain="quality")["anomalies"]]
        for a in an[:3]:
            out.append("异常 {} [{}]：{}".format(a["key"], a["ref"], a["text"] or a["title"]))
        if an:
            g = self.t.get_anomaly(an[0]["id"])
            if g.get("chain", {}).get("summary"):
                out.append("追因：" + "；".join(g["chain"]["summary"][:3]) + "。")
        return "\n".join(out) or "最近没有质量趋势或质量异常。"

    def a_anomalies(self, q):
        if self.student:
            return self._hint("anomalies")
        lst = self.t.list_anomalies()["anomalies"]
        if not lst:
            return "现在没有开着的异常，全厂运行平稳。"
        out = ["现在开着 {} 个异常（按严重程度）：".format(len(lst))]
        for a in lst[:8]:
            out.append("· {} {} [{}]：{}".format(a["severity"], a["key"], a["ref"], a["title"]))
        out.append("问“A-xxxxx 怎么处理？”可以看推演出的方案。")
        return "\n".join(out)

    def a_object(self, q):
        m = re.search(r"(MFG-WO-\d{4}-\d{5}|SAL-ORD-\d{4}-\d{5}|[A-Z]{2,}[A-Z0-9]*-[A-Z0-9\-]+)", q.upper())
        unit = find_machine(q)
        term = unit or (m.group(1) if m else q.strip())
        res = self.t.search_objects(term)["results"]
        if not res:
            return "本体里没有找到“{}”。".format(term)
        o = res[0]
        g = self.t.get_object(o["type"], o["key"])
        if g.get("error"):
            return g["error"]
        props = "；".join("{}：{}".format(k, v) for k, v in list(g["props"].items())[:8] if v not in (None, "", [], {}))
        ev = g["recent_events"][:3]
        return "{} {} [{}]：{}。{}".format(g["label"], g["display"] or g["key"], g["ref"], props or "没有更多属性",
                                         ("最近：" + "；".join("{} {}{}".format(e["ts"][5:16].replace("T", " "), e["text"],
                                                                               " [{}]".format(e["ref"]) if e.get("ref") else "") for e in ev) + "。") if ev else "")

    def a_overview(self, q):
        ov = self.t.call("metrics", {"section": "kpis"})
        k = {x["key"]: x for x in ov["kpis"]}

        def pct(x, d=0):
            return "—" if x is None else ("{:." + str(d) + "f}%").format(x * 100)
        return ("现在 {}：OEE {}，在制品 {} 件，本周完工 {}/{}，一次合格率 {} [{}]。可以问我：某台设备停了影响什么、某个异常怎么处理、"
                "某张订单为什么晚、某种物料够不够、某张工单成本为什么超。").format(
            ov["local_time"], pct(k["oee"]["value"]), k["wip"]["value"], k["output"]["value"], k["output"]["total"],
            pct(k["fpy"]["value"], 1), ov["ref"])


def _playbook_rules():
    from hub.ont import playbook as PB
    return set(PB.catalog()[0])


def _latest_wo(db, mode):
    r = db.one("select corr from bus_message where type='machine.event' and mode=%s and corr like 'MFG-WO-%%' "
               "and payload->'data'->>'event'='op_complete' order by ts desc limit 1", (mode,))
    return r["corr"] if r else None


# ====================================================================== 运行记录查询
def runs(db, mode, user=None, only_bad=False, kind=None, limit=200):
    w, a = ["mode=%s"], [mode]
    if user:
        w.append('"user"=%s')
        a.append(user)
    if only_bad:
        w.append("(feedback < 0 or (\"check\"->>'ok')::boolean is false)")
    if kind:
        w.append("kind=%s")
        a.append(kind)
    rows = db.q('select id, "user", role, kind, question, engine, answer, "check", duration_ms, feedback, created_at, '
                "jsonb_array_length(steps) as nsteps from ai_run where {} order by id desc limit %s".format(" and ".join(w)), a + [int(limit)])
    return [dict(r, created_at=r["created_at"].isoformat(), ok=(r["check"] or {}).get("ok")) for r in rows]


def prune(db):
    db.x("delete from ai_run where created_at < now() - make_interval(days => %s)", (KEEP_DAYS,))
