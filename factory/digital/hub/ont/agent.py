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
SV_RULES = ("C1", "C3", "C4", "V1", "V2")             # 这几类异常的方案按服务派工估算（与 hub.service.SERVICE_RULES 相同）
INTENTS = {
    "draft": "起草动作", "machine": "设备停机的影响与对策", "handle": "某个异常怎么处理", "order": "新订单能不能接（算料）",
    "cost": "工单成本为什么超", "late": "订单为什么晚 / 交期", "bottleneck": "瓶颈在哪", "material": "物料够不够",
    "quality": "质量趋势", "anomalies": "现在有哪些异常", "safety": "安全环保", "maint": "设备维护", "people": "人员与排班", "supplier": "采购与来料", "energy": "能源与环境", "finance": "经营与财务", "object": "查一个对象", "overview": "全厂概况",
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
        if a.get("rule") in SV_RULES:
            return self._service_options(a)
        try:
            if a.get("rule") == "E1":                  # 第 18 轮 E2：重大隐患 → 停机挂牌 / 限时整改 / 停机 + 改派加班（车间推演）
                from hub import ehs as EH
                ev = EH.options(self.db, self.mode, a, st, self._ctx_plan(st))
            elif a.get("rule") == "E3":
                from hub import ehs as EH
                ev = EH.permit_options(self.db, self.mode, a)
            elif a.get("rule") in ("M2", "M4"):          # 第 18 轮 E3：保养时机
                from hub import maint as MT
                ev = MT.options(self.db, self.mode, a, st, self._ctx_plan(st))
            elif a.get("rule") == "M3":
                from hub import maint as MT
                ev = MT.inspection_options(self.db, self.mode, a)
            elif a.get("rule") == "M5":
                from hub import maint as MT
                ev = MT.parts_options(self.db, self.mode, a)
            elif a.get("rule") == "W3":                  # 第 18 轮 E5：来料不合格（推演到料日）
                from hub import supply as SP
                ev = SP.options(self.db, self.mode, a, st, self._ctx_plan(st))
            elif a.get("rule") in ("W4", "W6"):
                from hub import supply as SP
                ev = SP.alt_options(self.db, self.mode, a)
            elif a.get("rule") in ("F2", "F3", "F4", "F5", "F6", "F7"):     # 第 18 轮 E7：应收、信用、现金、预算（看现金流）
                from hub import finance as FN
                ev = FN.options(self.db, self.mode, a)
            elif a.get("rule") in ("N2", "N3", "N5"):    # 第 18 轮 E6：空转（自动待机）、峰时 / 需量（错峰），车间推演算电费和交期
                from hub import energy as EG
                ev = EG.options(self.db, self.mode, a, st, self._ctx_plan(st))
            elif a.get("rule") in ("N1", "N4", "N6"):
                from hub import energy as EG
                ev = EG.fix_options(self.db, self.mode, a)
            elif a.get("rule") == "H2":                  # 第 18 轮 E4：排班缺口（车间推演）
                from hub import people as PE
                ev = PE.options(self.db, self.mode, a, st, self._ctx_plan(st))
            elif a.get("rule") == "H1":
                from hub import people as PE
                ev = PE.training_options(self.db, self.mode, a)
            else:
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

    def _service_options(self, a):
        """投诉、现场报警、批次问题：方案按工程师排班估算（第 18 轮 E1-3），不进车间仿真"""
        from hub import service as SV
        ev = SV.anomaly_options(self.db, self.mode, a)
        locked = self.locked(self.u, a.get("id"))
        today = SV.field_today(self.db, self.mode).isoformat()
        opts = []
        for o in ev["options"]:
            s = o["service"]
            title = "{} {}".format(o["key"], o["label"])
            scid = self._save_scenario(title, None, o["changes"], o["result"], a.get("id"))
            item = {"key": o["key"], "label": o["label"], "kind": o["kind"], "note": o["note"], "changes": o["changes"],
                    "ref": self.run.scenario(scid, title), "scenario_id": scid, "sales_orders": [],
                    "units": s["units"], "customers": s["customers"], "engineers": s["engineers"], "days": s["days"], "finish": s["finish"],
                    "spares": s["spares"], "cost": s["cost"], "cost_total": s["cost"]["total"], "overtime_min": 0, "ok": o["result"]["ok"],
                    "failed_checks": [c["text"] for c in o["result"]["checks"] if not c["ok"]], "uncovered_high": o["uncovered_high"]}
            if not locked:
                item["recommended"] = o["recommended"]
            opts.append(item)
        out = {"options": opts, "affected": [], "service": True, "scope": ev.get("scope"), "snapshot_id": None, "exact": True,
               "hypothesis": None, "factory_now": today, "anomaly_id": a.get("id"), "anomaly_ref": self.run.anomaly(a)}
        if not opts:
            out["note"] = ev.get("reason")
        elif locked:
            out["note"] = "比对模式：你提交自己的分析之前，不显示建议和推荐理由"
        else:
            out["recommended"], out["reason"] = ev["recommended"], ev["reason"]
        return out

    # ---- ⑩ 客户 360
    def customer_360(self, customer):
        from hub import service_api as SA
        name = self._customer_name(customer)
        if not name:
            return {"error": "没有找到客户“{}”".format(customer)}
        r = SA.c360(self.db, self.mode, name)
        if r.get("contract") and not self._visible("Contract"):        # 合同是 2 级敏感：看不到就不给条款
            r["contract"] = {"name": r["contract"]["name"], "hidden": "合同条款你没有权限查看"}
        r["ref"] = self.run.obj("Customer", name, name.split(" ")[0])
        r["page"] = self.run.page("c360:" + name, "客户与服务 · 客户 360（{}）".format(name.split(" ")[0]), "/service?tab=c360&customer=" + name)
        for c in r["complaints"]:
            c["ref"] = self.run.obj("Complaint", c["key"])
        for u in r["units"]:
            u["ref"] = self.run.obj("FieldUnit", u["serial"])
        for o in r["orders"]:
            o["ref"] = self.run.obj("SalesOrder", o["name"])
        if r.get("contract"):
            r["contract"] = dict(r["contract"], ref=self.run.obj("Contract", r["contract"]["name"]))
        r["counts"] = {"orders": len(r["orders"]), "units": len(r["units"]), "red": sum(1 for x in r["units"] if x["health"] == "red"),
                       "yellow": sum(1 for x in r["units"] if x["health"] == "yellow"),
                       "open_complaints": sum(1 for c in r["complaints"] if c["status"] != "已关闭"), "jobs": len(r["jobs"])}
        return r

    def _customer_name(self, q):
        q = (q or "").strip()
        if not q:
            return None
        names = set(F.CUSTOMERS)
        for m in self.db.erp_docs("Customer", self.mode):
            names.add(m["data"].get("customer_name") or m["data"]["name"])
        from hub import service as SV
        for u in SV.units(self.db, self.mode).values():
            names.add(u["customer"])
        ql = q.lower()
        for n in sorted(names, key=len):
            if n and (n.lower() == ql or ql in n.lower()):
                return n
        from hub.ai import _cust_keys
        for n in sorted(names, key=len):
            if n and any(k and len(k) >= 2 and k in q for k in _cust_keys(n)):
                return n
        for word, site in SITE_WORDS:
            if word in q:
                from twin import field as TF
                return TF.SITES[site]["customer"]
        return None

    # ---- ⑪ 投诉追溯与排查范围
    def complaint_scope(self, complaint=None, serial=None):
        """投诉（CP-xxxxx）或设备序列号 → 同批次（同一片砂轮、同一张工单）的设备，以及它们现在的健康度"""
        from hub import service as SV
        from hub.ont import anomaly as A
        from hub.ont import chain as CH
        cid = None
        if complaint:
            m = re.search(r"(\d+)", str(complaint))
            cid = int(m.group(1)) if m else None
            c = self.db.one("select * from complaint where mode=%s and id=%s", (self.mode, cid)) if cid else None
            if c is None:
                return {"error": "没有这个投诉：{}".format(complaint)}
            serial = serial or c["serial"]
        if not serial:
            return {"error": "要给投诉号（CP-xxxxx）或设备序列号"}
        us = SV.units(self.db, self.mode)
        if serial not in us:
            return {"error": "现场设备里没有 {}（出厂数据查不到，无法追溯）".format(serial)}
        ch = CH.chain_field(A.Ctx(self.db, self.mode), [serial], label="投诉" if cid else "报警").out()
        chain = self._chain(ch)
        others = [s for s in (ch.get("scope") or {}).get("check_units", []) if s != serial and s in us]
        rows = sorted([us[s] for s in others], key=lambda x: -x["risk"])
        out = {"serial": serial, "unit_ref": self.run.obj("FieldUnit", serial), "customer": us[serial]["customer"],
               "health": us[serial]["health"], "chain": chain,
               "check_units": [{"serial": x["serial"], "customer": x["customer"], "site": x["site"], "health": x["health"],
                                "worst_bearing_used": x["worst_bearing"]["used"], "in_warranty": x["in_warranty"], "risk": x["risk"],
                                "ref": self.run.obj("FieldUnit", x["serial"])} for x in rows],
               "customers": sorted({x["customer"] for x in rows})}
        if cid:
            out["complaint"] = "CP-{:05d}".format(cid)
            out["complaint_ref"] = self.run.obj("Complaint", out["complaint"])
            a = self.db.one("select * from anomaly where mode=%s and rule in ('C1','C3','C4') and detail->'values'->>'complaint'=%s "
                            "order by id desc limit 1", (self.mode, out["complaint"]))
            if a:
                out["anomaly_id"] = a["id"]
                out["anomaly_ref"] = self.run.anomaly(a)
        return out

    # ---- ⑫ 服务派工估算
    def service_estimate(self, serials, kind="inspect"):
        """几台设备上门（inspect 点检 / bearing 换轴承）：按工程师排班估算天数、人天、备件、费用（只算不排）"""
        from hub import service as SV
        us = SV.units(self.db, self.mode)
        if isinstance(serials, str):
            serials = re.findall(r"WQR105-[A-Z0-9]+-\d{2}", serials.upper()) or [serials]
        wanted = []
        for s in serials or []:
            if s not in us:
                continue
            k = "repair:bearing:" + us[s]["worst_bearing"]["id"] if kind == "bearing" else ("inspect" if kind == "inspect" else SV.repair_kind(us[s]))
            wanted.append({"serial": s, "kind": k})
        if not wanted:
            return {"error": "没有找到这些现场设备"}
        est = SV.estimate(self.db, self.mode, wanted)
        est["page"] = self.run.page("service-schedule", "客户与服务 · 工程师排班", "/service?tab=service")
        for j in est["jobs"]:
            j["ref"] = self.run.obj("FieldUnit", j["serial"])
        return est

    # ---- ⑬ 安全概况（第 18 轮 E2）
    def ehs_overview(self):
        """开着的隐患（重大在前）、挂牌上锁的设备、作业中的许可、培训到期、危废超期"""
        from hub import ehs as EH
        k = EH.kpis(self.db, self.mode)
        rows = self.db.q("select * from safety_issue where mode=%s and status<>'closed' order by (level='major') desc, id limit 15", (self.mode,))
        issues = []
        for r in rows:
            x = EH.issue_row(r)
            issues.append({k2: x[k2] for k2 in ("key", "unit", "level_label", "subject", "status_label", "due_day", "overdue", "fix_minutes")})
            issues[-1]["ref"] = self.run.obj("SafetyIssue", x["key"])
        names = {p["id"]: p["name"] for p in self.db.q("select id, name from ehs_person where mode=%s", (self.mode,))}
        permits = [dict(EH.permit_row(self.db, r, names), ref=self.run.obj("WorkPermit", "PTW-{:05d}".format(r["id"])))
                   for r in self.db.q("select * from work_permit where mode=%s and status in ('active','blocked','requested') order by id", (self.mode,))]
        due = [dict(t, name=names.get(t["person_id"])) for t in EH.trainings(self.db, self.mode) if t["days_left"] <= 30]
        out = {"kpis": k, "issues": issues, "permits": [{k2: p[k2] for k2 in ("key", "kind_label", "unit", "holder", "status_label", "block_reason", "ref")}
                                                         for p in permits],
               "trainings_due": [{k2: t[k2] for k2 in ("name", "label", "valid_until", "days_left")} for t in due]}
        out["page"] = self.run.page("ehs", "安全环保", "/ehs")
        return out

    # ---- ⑭ 某台设备的安全状态
    def machine_safety(self, unit):
        from hub import ehs as EH
        unit = (unit or "").lower()
        if unit not in UNITS:
            return {"error": "没有这台设备：{}".format(unit)}
        EH.seed(self.db, self.mode)
        hz = [dict(h, risk=EH.risk(h["likelihood"], h["severity"]), ref=self.run.obj("Hazard", h["id"]))
              for h in self.db.q("select id, name, likelihood, severity, controls from hazard where mode=%s and unit=%s order by id", (self.mode, unit))]
        iss = [dict({k2: EH.issue_row(r)[k2] for k2 in ("key", "level_label", "subject", "status_label", "due_day", "fix_minutes")},
                    ref=self.run.obj("SafetyIssue", "SI-{:05d}".format(r["id"])))
               for r in self.db.q("select * from safety_issue where mode=%s and unit=%s and status<>'closed' order by id", (self.mode, unit))]
        locks = [{"key": "PTW-{:05d}".format(r["id"]), "ref": self.run.obj("WorkPermit", "PTW-{:05d}".format(r["id"]))}
                 for r in EH.active_locks(self.db, self.mode) if r["unit"] == unit]
        m = next((x for x in kpi.overview(self.db, None, self.mode)["machines"] if x["unit"] == unit), {})
        return {"unit": unit, "name": UNITS[unit][1], "ref": self.run.obj("Machine", unit, UNITS[unit][1]), "state": m.get("state"),
                "locked": m.get("locked"), "hazards": [{k2: h[k2] for k2 in ("id", "name", "risk", "controls", "ref")} for h in hz],
                "open_issues": iss, "locks": locks}

    # ---- ⑮ 风险评估
    def risk_assess(self, likelihood, severity):
        from hub import ehs as EH
        try:
            r = EH.risk(likelihood, severity)
        except (TypeError, ValueError) as e:
            return {"error": str(e)}
        r["rule"] = "可能性 × 严重度（各 1–5 分）：≥ 15 重大，8–14 较大，其余一般"
        return r

    # ---- ⑯ 设备台账与保养状态（第 18 轮 E3）
    def maint_overview(self):
        from hub import maint as MT
        rows = sorted(MT.assets(self.db, self.mode), key=lambda x: (-x["overdue_h"], x["due_in_h"]))
        out = {"kpis": MT.kpis(self.db, self.mode), "horizon_h": MT.HORIZON_H,
               "machines": [dict({k: x[k] for k in ("unit", "name", "asset", "run_h", "pm_h", "overdue_h", "due_in_h", "p_fail", "expected_loss_usd",
                                                    "failures_30d", "state", "locked")}, ref=self.run.obj("Machine", x["unit"], x["name"])) for x in rows]}
        out["page"] = self.run.page("maint", "设备维护 · 台账与保养", "/maint")
        return out

    # ---- ⑰ 故障风险与预期损失
    def failure_risk(self, unit, hours=None):
        from hub import maint as MT
        unit = (unit or "").lower()
        if not MT.REL.params(unit):
            return {"error": "没有这台设备的保养计划：{}".format(unit)}
        r = MT.risk(self.db, self.mode, unit, float(hours or MT.HORIZON_H))
        r.pop("curve", None)
        r["ref"] = self.run.obj("Machine", unit, UNITS[unit][1])
        r["formula"] = "F(t) = 1 − exp(−(t/η)^β)；已运行 t 小时、再运行 H 小时内坏掉的概率 = 1 − exp(−[((t+H)/η)^β − (t/η)^β])"
        return r

    # ---- ⑱ 维修与备件
    def repairs_spares(self):
        from hub import maint as MT
        MT.init(self.db)
        reps = [dict({k: r[k] for k in ("unit", "title", "status")}, key="MR-{:05d}".format(r["id"]), status_label=MT.STATUS[r["status"]],
                     parts=r["parts"], ref=self.run.obj("RepairOrder", "MR-{:05d}".format(r["id"])))
                for r in self.db.q("select * from maint_repair where mode=%s and status<>'closed' order by id", (self.mode,))]
        pms = [{"key": "PM-{:05d}".format(r["id"]), "unit": r["unit"], "status_label": MT.PM_STATUS[r["status"]]}
               for r in self.db.q("select * from maint_pm where mode=%s and status<>'closed' order by id", (self.mode,))]
        spares = [dict(x, ref=self.run.obj("SparePart", x["item_code"])) for x in
                  ({"item_code": k, "stock": MT.stock_of(self.db, self.mode, k), "min": v} for k, v in MT.SPARE_MIN.items())]
        return {"repairs": reps, "pms": pms, "spares": spares, "page": self.run.page("maint-repairs", "设备维护 · 维修与备件", "/maint?tab=repairs")}

    # ---- ㉒ 供应商评分卡（第 18 轮 E5）
    def supplier_scorecard(self):
        from hub import supply as SP
        rows = [dict(x, ref=self.run.obj("Supplier", x["supplier"], x["supplier"].split(" ")[0])) for x in SP.scorecard(self.db, self.mode)]
        return {"suppliers": rows, "single_source": SP.single_source(self.db, self.mode), "kpis": SP.kpis(self.db, self.mode),
                "tco_formula": "每件总拥有成本 = 单价 × 价格指数 + (1 − 合格率) × ${:g} + (1 − 准时率) × ${:g}".format(SP.REJECT_COST, SP.LATE_COST),
                "page": self.run.page("supply-suppliers", "采购与来料 · 供应商", "/supply?tab=suppliers")}

    # ---- ㉓ 批次追溯
    def batch_trace(self, lot=None, serial=None):
        from hub import supply as SP
        if not lot and not serial:
            return {"error": "给批号（如 L261007-0012）或零件 / 设备序列号"}
        r = SP.trace(self.db, self.mode, lot, serial)
        if lot and not r.get("row"):
            return {"error": "没有这个批次：{}".format(lot)}
        r["page"] = self.run.page("supply-batches", "采购与来料 · 批次", "/supply?tab=batches")
        if lot:
            r["ref"] = self.run.obj("Batch", lot)
        return r

    # ---- ㉔ 采购在途与风险
    def purchasing_status(self):
        from hub import supply as SP
        rows = SP.lots(self.db, self.mode, ("ordered", "transit", "arrived", "rejected", "suspect"), limit=60)
        return {"open_lots": [dict(x, ref=self.run.obj("Batch", x["lot"]) if x["lot"] else None) for x in rows], "kpis": SP.kpis(self.db, self.mode),
                "page": self.run.page("supply-lots", "采购与来料 · 采购单与到货", "/supply?tab=lots")}

    # ---- ㉕ 能耗总览（第 18 轮 E6）
    def energy_overview(self, day=None):
        from hub import energy as EG
        d = None
        if day:
            try:
                d = dt.date.fromisoformat(str(day)[:10])
            except ValueError:
                return {"error": "日期格式 YYYY-MM-DD"}
        o = EG.overview(self.db, self.mode, d)
        if not o["hours"]:
            return {"error": "还没有计量读数（教学模式由仿真车间每 15 分钟发一个；生产模式要接电表）"}
        o.pop("series", None)
        o["units"] = [dict(u, ref=self.run.obj("Meter", "E-" + u["unit"].upper(), u["name"])) for u in o["units"]]
        o["demand"] = EG.demand(self.db, self.mode)
        o["env"] = EG.env_now(self.db, self.mode)
        o["settings"] = EG.settings(self.db, self.mode)
        o["page"] = self.run.page("energy-overview", "能源与环境 · 总览", "/energy?tab=overview")
        return o

    # ---- ㉖ 单耗与空转
    def unit_energy(self, unit=None):
        from hub import energy as EG
        rows = EG.unit_energy(self.db, self.mode)
        idle = EG.idle_by_unit(self.db, self.mode)
        if unit:
            u = str(unit).lower()
            rows = [x for x in rows if x["unit"] == u]
            idle = [x for x in idle if x["unit"] == u]
        return {"unit_energy": [dict(x, ref=self.run.obj("Machine", x["unit"], x["name"])) for x in rows],
                "idle": sorted(idle, key=lambda x: -x["idle_kwh"]), "air": EG.air_excess(self.db, self.mode), "peak": EG.peak_share(self.db, self.mode),
                "page": self.run.page("energy-unit", "能源与环境 · 单耗", "/energy?tab=unit")}

    # ---- ㉗ 碳核算
    def carbon_account(self, month=None):
        from hub import energy as EG
        try:
            c = EG.carbon(self.db, self.mode, month)
        except ValueError:
            return {"error": "月份格式 YYYY-MM"}
        c["ref"] = self.run.obj("CarbonAccount", c["month"])
        c["page"] = self.run.page("energy-carbon", "能源与环境 · 碳与环境", "/energy?tab=carbon")
        return c

    # ---- ㉘ 订单毛利分解（第 18 轮 E7）
    def order_margin(self, sales_order=None):
        from hub import finance as FN
        if sales_order:
            try:
                m = FN.margin(self.db, self.mode, sales_order, store=False)
            except KeyError:
                return {"error": "没有这张订单：{}".format(sales_order)}
            return dict(m, ref=self.run.obj("SalesOrder", sales_order), page=self.run.page("finance-margins", "经营与财务 · 订单毛利", "/finance?tab=margins"))
        ms = FN.margins(self.db, self.mode)
        tgt = next((o["target"] for o in FN.objectives(self.db, self.mode) if o["metric"] == "gross_margin"), 0.25)
        return {"margins": [dict(m, ref=self.run.obj("SalesOrder", m["sales_order"])) for m in ms], "gross_margin": FN.gross_margin(self.db, self.mode),
                "target": tgt, "page": self.run.page("finance-margins", "经营与财务 · 订单毛利", "/finance?tab=margins")}

    # ---- ㉙ 应收应付与现金流
    def ar_ap_cash(self):
        from hub import finance as FN
        a = FN.ar(self.db, self.mode)
        return {"ar": a, "ap": FN.ap(self.db, self.mode), "credit": FN.credit(self.db, self.mode), "cashflow": FN.cashflow(self.db, self.mode),
                "dso": FN.dso(self.db, self.mode), "page": self.run.page("finance-arap", "经营与财务 · 应收应付", "/finance?tab=arap")}

    # ---- ㉚ 经营目标与预算
    def objectives_budget(self):
        from hub import finance as FN
        return {"objectives": [dict(o, ref=self.run.obj("Objective", o["code"], o["name"])) for o in FN.objectives(self.db, self.mode)],
                "budget": FN.budget_view(self.db, self.mode), "page": self.run.page("finance-objectives", "经营与财务 · 经营目标", "/finance?tab=objectives")}

    # ---- ⑲ 员工与技能（第 18 轮 E4）
    def people_skills(self, unit=None):
        from hub import people as PE
        m = PE.matrix(self.db, self.mode)
        units = [u for u in m["units"] if not unit or u["unit"] == str(unit).lower()]
        if unit and not units:
            return {"error": "没有这台需要人的设备：{}".format(unit)}
        rows = []
        for u in units:
            who = [{"id": r["id"], "name": r["name"], "level": PE.LEVELS.get(r["cells"][u["unit"]]["level"]), "shift": PE.SHIFT_NAME.get(r["shift"]),
                    "ref": self.run.obj("Employee", r["id"], r["name"])}
                   for r in m["rows"] if u["unit"] in r["cells"] and r["cells"][u["unit"]]["level"]]
            rows.append(dict(u, people=who, ref=self.run.obj("Machine", u["unit"], u["name"])))
        return {"skills": rows, "single_points": [x["unit"] for x in PE.single_points(self.db, self.mode)],
                "employees": len(PE.employees(self.db, self.mode)), "page": self.run.page("people-skills", "人员 · 技能矩阵", "/people?tab=skills")}

    # ---- ⑳ 排班与缺口
    def roster_gaps(self, hours=24):
        from hub import people as PE
        b = PE.today_board(self.db, self.mode)
        gaps = [dict(g, ref=self.run.obj("Machine", g["unit"], UNITS[g["unit"]][1])) for g in PE.gaps(self.db, self.mode, hours=float(hours or 24))]
        return {"now": {"day": b["day"], "shift": b["shift_name"]}, "on_shift": [x for x in b["people"] if x["units"]],
                "absent": [x for x in b["people"] if x["attendance"] not in ("在岗", "迟到")], "roster_gaps": gaps, "enabled": PE.enabled(self.db, self.mode),
                "page": self.run.page("people-roster", "人员 · 排班", "/people?tab=roster")}

    # ---- ㉑ 加班与负荷
    def overtime_load(self):
        from hub import people as PE
        names = {p["id"]: p["name"] for p in PE.employees(self.db, self.mode)}
        ot = PE.overtime_week(self.db, self.mode)
        return {"overtime": [{"emp_id": k, "name": names.get(k, k), "hours": v, "over": v > PE.OT_WEEK_LIMIT_H} for k, v in sorted(ot.items(), key=lambda x: -x[1])],
                "limit_h": PE.OT_WEEK_LIMIT_H, "absence": PE.absence_rate(self.db, self.mode), "kpis": PE.kpis(self.db, self.mode),
                "page": self.run.page("people-overtime", "人员 · 出勤与加班", "/people?tab=attendance")}

    # ---- ⑨ 起草动作（只起草）
    def draft_action(self, changes, anomaly_id=None, scenario_id=None, snapshot_id=None):
        from hub.ont import actions as AC
        from hub.ont import plan as P
        if self.mode == "teach" and not self.u.get("teacher"):
            return {"error": "教学模式下 AI 不代做：请自己在推演工作台或指挥台采纳方案"}
        changes = [c for c in (changes or []) if c.get("type") in AC.TYPES]
        if not changes:
            return {"error": "没有可以起草的动作（假设停机、插单只能用于推演）"}
        if not all(AC.can_initiate(self.u, c["type"]) for c in changes):
            svc = any(AC.TYPES[c["type"]].get("service") for c in changes)
            return {"error": "服务动作由售后、销售或厂长发起" if svc else "动作由计划员或厂长发起"}
        try:
            if all(AC.TYPES[c["type"]].get("service") for c in changes):
                tr = AC.trial(self.db, self.H.plan_snaps, self.mode, changes)
            else:
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
            if name in DEMO_ONLY_TOOLS and not _demo_plant():
                out = {"error": DEMO_ONLY_NOTE}
            else:
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
    if "check_units" in out:
        return "同批次 {} 台".format(len(out["check_units"]))
    if "units" in out and "complaints" in out:
        return "客户 360：{} 台设备、{} 个投诉".format(len(out["units"]), len(out["complaints"]))
    if "issues" in out and "kpis" in out:
        return "隐患 {} 条".format(len(out["issues"]))
    if "machines" in out and "horizon_h" in out:
        return "设备 {} 台".format(len(out["machines"]))
    if "p_fail" in out:
        return "故障概率 {:.0%}".format(out["p_fail"])
    if "repairs" in out and "spares" in out:
        return "维修单 {} 张".format(len(out["repairs"]))
    if "suppliers" in out and "single_source" in out:
        return "供应商 {} 家".format(len(out["suppliers"]))
    if "lines" in out and "margin_pct" in out:
        return "毛利率 {}".format("{:.1%}".format(out["margin_pct"]) if out["margin_pct"] is not None else "—")
    if "margins" in out:
        return "订单 {} 张".format(len(out["margins"]))
    if "ar" in out and "cashflow" in out:
        return "应收 ${:,.0f}".format(out["ar"]["total"])
    if "objectives" in out and "budget" in out:
        return "目标 {} 个".format(len(out["objectives"]))
    if "by_bucket" in out and "units" in out:
        return "用电 {:,.0f} 度".format(out.get("kwh") or 0)
    if "unit_energy" in out:
        return "单耗 {} 项".format(len(out["unit_energy"]))
    if "t_co2e" in out:
        return "碳排放 {:g} t".format(out["t_co2e"])
    if "open_lots" in out:
        return "未完的批次 {} 个".format(len(out["open_lots"]))
    if "parts" in out and ("lot" in out or "serial" in out):
        return "批次追溯：{} 个零件".format(len(out["parts"]))
    if "skills" in out and "single_points" in out:
        return "设备 {} 台，单点依赖 {} 台".format(len(out["skills"]), len(out["single_points"]))
    if "roster_gaps" in out:
        return "排班缺口 {} 个".format(len(out["roster_gaps"]))
    if "overtime" in out and "limit_h" in out:
        return "加班 {} 人".format(len(out["overtime"]))
    if "hazards" in out:
        return "危险源 {} 条".format(len(out["hazards"]))
    if "person_days" in out:
        return "派工 {} 台，{} 天".format(out["units"], out["days"])
    if "sales_orders" in out:
        return "推演：多花 ${:,.0f}".format(out.get("cost_total") or 0)
    return "完成"


TOOL_NAMES = ["search_objects", "get_object", "neighbors", "impact", "metrics", "list_anomalies", "get_anomaly", "simulate",
              "compare_options", "draft_action", "query_messages", "work_order_cost", "plan_order", "propose_order",
              "customer_360", "complaint_scope", "service_estimate", "ehs_overview", "machine_safety", "risk_assess",
              "maint_overview", "failure_risk", "repairs_spares", "people_skills", "roster_gaps", "overtime_load", "supplier_scorecard", "batch_trace", "purchasing_status",
              "energy_overview", "unit_energy", "carbon_account", "order_margin", "ar_ap_cash", "objectives_budget"]

_S = lambda **p: {"type": "object", "properties": p}                                    # noqa: E731
_CH = {"type": "array", "items": {"type": "object"}, "description": "改动清单（与推演工作台相同）：reassign / reorder / overtime / expedite / "
       "urgent_purchase / outsource / split_delivery，参数照 compare_options 返回的 changes"}
# 第 30 轮 H-2：E1–E7 领域的工具（第 18 轮加的）只在演示工厂；企业工厂（工厂清单 demo_data: false）里不给模型、规则版调用也只回“没有”
DEMO_ONLY_TOOLS = frozenset((
    "customer_360", "complaint_scope", "service_estimate", "ehs_overview", "machine_safety", "risk_assess", "maint_overview",
    "failure_risk", "repairs_spares", "people_skills", "roster_gaps", "overtime_load", "supplier_scorecard", "batch_trace",
    "purchasing_status", "energy_overview", "unit_energy", "carbon_account", "order_margin", "ar_ap_cash", "objectives_budget"))

DEMO_ONLY_INTENTS = frozenset(("finance", "energy", "people", "supplier", "maint", "safety", "complaint", "service", "customer"))
DEMO_ONLY_NOTE = "本厂没有这个领域的数据（客户与服务、安全环保、设备维护、人员、供应链、能源、经营与财务只在演示工厂）"


def _demo_plant():
    from factory import plant
    return plant.is_demo()


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
    {"name": "compare_options", "description": "按处理方案自动推演几个候选方案并排序推荐。给异常编号，或给“假设某设备再停 N 分钟”",
     "input_schema": _S(anomaly_id={"type": "integer"}, down_unit={"type": "string"}, down_minutes={"type": "number"})},
    {"name": "draft_action", "description": "把方案起草成动作草稿（只起草，不提交、不执行；要人在动作收件箱提交、审批）。教学模式学生不可用",
     "input_schema": dict(_S(changes=_CH, anomaly_id={"type": "integer"}, scenario_id={"type": "integer"}), required=["changes"])},
    {"name": "customer_360", "description": "客户 360：一个客户的合同条款（违约金、响应时限、保修期）、订单、现场设备健康度、投诉、服务单、满意度。"
     "customer 可以是客户名或简称，也可以说“港口”“矿山”“食品厂”",
     "input_schema": dict(_S(customer={"type": "string"}), required=["customer"])},
    {"name": "complaint_scope", "description": "投诉追溯与排查范围：从投诉（CP-xxxxx）或设备序列号往回追到出厂的输出轴、加工它的工单和砂轮，"
     "再找出同一批次装在别的客户那里的设备（按风险排序）",
     "input_schema": _S(complaint={"type": "string"}, serial={"type": "string"})},
    {"name": "service_estimate", "description": "服务派工估算（只算不排）：几台现场设备上门，按 6 位工程师的排班算几天做完、几个人天、备件、费用、保修内多少。"
     "kind：inspect 点检 / bearing 换轴承 / auto 按报警决定",
     "input_schema": dict(_S(serials={"type": "array", "items": {"type": "string"}}, kind={"type": "string", "enum": ["inspect", "bearing", "auto"]}),
                          required=["serials"])},
    {"name": "ehs_overview", "description": "安全概况：开着的隐患（重大在前、整改期限）、挂牌上锁的设备、作业许可（含缺资质被拦下的）、30 天内到期的安全培训、危废超期",
     "input_schema": _S()},
    {"name": "machine_safety", "description": "某台设备的安全状态：危险源与风险值、开着的隐患、是否挂牌上锁",
     "input_schema": dict(_S(unit={"type": "string", "description": "设备编号，如 grd-01"}), required=["unit"])},
    {"name": "risk_assess", "description": "风险评估：可能性 × 严重度（各 1–5 分）→ 风险值和等级",
     "input_schema": dict(_S(likelihood={"type": "integer"}, severity={"type": "integer"}), required=["likelihood", "severity"])},
    {"name": "maint_overview", "description": "设备台账与保养状态：每台设备自上次保养运行了多少小时、保养周期、是否逾期、未来两周坏掉的概率和预期损失、近 30 天故障次数",
     "input_schema": _S()},
    {"name": "failure_risk", "description": "某台设备的故障风险（威布尔失效率模型）：未来 hours 运行小时坏掉的概率、预期停机、预期损失，保养后的概率",
     "input_schema": dict(_S(unit={"type": "string"}, hours={"type": "number"}), required=["unit"])},
    {"name": "repairs_spares", "description": "开着的维修单、保养单和维修备件库存（对比最低库存）", "input_schema": _S()},
    {"name": "people_skills", "description": "员工与技能：每台需要人的设备谁会开（学徒 / 熟练 / 可带徒、哪个班），熟练以上只有一个人的设备（单点依赖）。unit 可选",
     "input_schema": _S(unit={"type": "string", "description": "设备编号，如 grd-01"})},
    {"name": "roster_gaps", "description": "排班与缺口：这一班谁在岗、谁请假，未来 hours 小时内哪一班哪台设备没人能开",
     "input_schema": _S(hours={"type": "number"})},
    {"name": "overtime_load", "description": "加班与负荷：本周每人加班小时（对比上限）、近 7 天各班组缺勤率", "input_schema": _S()},
    {"name": "supplier_scorecard", "description": "供应商评分卡：每家的准时率、来料合格率（近 30 天）、过去一年的历史、价格指数、提前期、默认还是备选；单一来源的物料类别；总拥有成本公式",
     "input_schema": _S()},
    {"name": "batch_trace", "description": "批次追溯：给批号查这批料用到了哪些零件、工单、现场设备；或给零件 / 设备序列号查用了哪些批次、哪家供应商",
     "input_schema": _S(lot={"type": "string"}, serial={"type": "string"})},
    {"name": "purchasing_status", "description": "采购在途与风险：已下单、在途、到货待检、不合格、可疑的批次，承诺到货日和晚了几天", "input_schema": _S()},
    {"name": "energy_overview", "description": "能耗总览：某天（默认最近一天）的用电、峰平谷电量、电费、峰时占比、碳排放、每台设备的运行 / 空转 / 待机 / 关机电量；"
     "本月需量对比合同需量；车间油雾、噪声；现在的自动待机、错峰设定", "input_schema": _S(day={"type": "string", "description": "YYYY-MM-DD"})},
    {"name": "unit_energy", "description": "单耗与空转：每台设备每个物料最近几件的单件运行电量对比基线（单耗突增）；近 12 小时各设备空转电量；空压机比该用的多多少（漏气）；近 24 小时峰时占比",
     "input_schema": _S(unit={"type": "string", "description": "设备编号，如 grd-01"})},
    {"name": "carbon_account", "description": "碳核算（外购电力，范围 2）：某月电量 × 电网排放因子，每台设备的排放，每件产品的碳足迹；水、压缩空气用量",
     "input_schema": _S(month={"type": "string", "description": "YYYY-MM"})},
    {"name": "order_margin", "description": "订单毛利：给订单号看收入、料、工、电、废品、急单加班外协、保修的分解和毛利率（每项说明来源）；不给就列出做完的订单的毛利和目标",
     "input_schema": _S(sales_order={"type": "string", "description": "如 SAL-ORD-2026-00021"})},
    {"name": "ar_ap_cash", "description": "应收应付与现金流：应收账龄（未到期 / 逾期分档）、每张未付发票、客户信用额度与余额、应付到期、未来 8 周现金流预测、应收周转天数",
     "input_schema": _S()},
    {"name": "objectives_budget", "description": "经营目标与预算：指标树（目标、现在的值、红黄绿、近 7 天红了几天），本月各成本中心预算、实际、按进度应花",
     "input_schema": _S()},
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
        drop = set() if _demo_plant() else set(DEMO_ONLY_TOOLS)     # 第 30 轮 H-2：企业工厂不给 E1–E7 的工具
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
        from factory import plant
        facts = ("工厂：唯一成品 WQR-105 二级圆柱齿轮减速器；本轮闭环零件是输出轴 SH-301（下料 → 粗车 → 调质 → 精车 → 铣键槽 → 磨外圆 → 检验）。"
                 if plant.is_demo() else plant.brief())
        base = ("你是“" + plant.display_name() + "”的 AI 工厂代理，是全厂员工的同事。你通过工厂本体（设备、工单、订单、物料、零件、客户等对象和它们的关系）、"
                "异常与因果链、推演（快进副本）和历史库看到全厂。回答用中文，简洁，先给结论再给依据。\n"
                "规矩：① 数据只来自工具结果，不编造；② 每个结论后面用 [n] 标出依据，n 是工具结果里对象、消息、异常、推演的 ref 编号；"
                "③ 回答里的数字必须是工具结果里出现过的（可以四舍五入、换算成百分比或小时），不确定就再查；"
                "④ 处理方案先用 compare_options 或 simulate 推演再说，不凭感觉；⑤ 写操作只能起草（draft_action 动作草稿、propose_order 提议），"
                "起草前先问对方要不要，人提交、审批后才执行。\n"
                + facts.replace("{", "{{").replace("}", "}}") +
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
SITE_WORDS = [("港口", "port"), ("码头", "port"), ("矿", "mine"), ("皮带", "mine"), ("食品", "food"), ("包装线", "food")]
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
        if intent in DEMO_ONLY_INTENTS and not _demo_plant():       # 第 30 轮 H-2：企业工厂没有 E1–E7 的数据
            return DEMO_ONLY_NOTE, intent
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
        if re.search(r"毛利|应收|应付|欠款|欠钱|催款|回款|收款|账龄|现金流|现金|预算|超支|信用额度|信用冻结|经营目标|指标树|发票|DSO|周转天数", q) \
                and not re.search(r"CP-\d{5}|投诉", q):                       # 第 18 轮 E7：经营与财务
            return "finance"
        if re.search(r"电费|用电|电量|能耗|单耗|空转|待机|峰时|谷时|错峰|需量|碳排|碳足迹|碳核算|排放|漏气|压缩空气|空压机|油雾|噪声|度电|节能|N[1-6]\b", q) \
                and not re.search(r"CP-\d{5}|投诉|危废|废弃物", q):          # 第 18 轮 E6：能源与环境
            return "energy"
        if re.search(r"排班|缺人|请假|出勤|缺勤|迟到|技能矩阵|单点依赖|一个人会|会开|顶班|带教|调班|在岗|人手|本周加班|加班超|技能培训|员工", q) \
                and not re.search(r"工程师|上门|服务|WQR105-", q):          # 第 18 轮 E4：人员与排班（客户现场的服务排班归客户与服务）
            return "people"
        if (re.search(r"L\d{6}-\d{4}", q) or re.search(r"供应商|评分卡|准时率|来料|批次|批号|在途|单一来源|备选|总拥有成本|采购单", q)) \
                and not re.search(r"CP-\d{5}|投诉|现场|客户", q):          # 第 18 轮 E5：采购与来料（客户投诉的追溯归客户与服务）
            return "supplier"
        if (re.search(r"MR-\d{5}|PM-\d{5}|IC-\d{5}", q) or re.search(r"保养|维修单|点检|备件|台账|失效|概率|MTBF|平均故障间隔|运行小时", q)) \
                and not re.search(r"上门|派工|WQR105-", q):            # 客户现场的上门点检归客户与服务
            return "maint"
        if re.search(r"SI-\d{5}|PTW-\d{5}", q) or re.search(r"安全(?!库存)|隐患|挂牌|上锁|作业许可|许可证|培训|危险源|事故|未遂|化学品|危废|废弃物|风险评估|可能性", q):
            return "safety"
        if re.search(r"CP-\d{5}", q) or re.search(r"投诉|召回|排查范围|同一?批|这批|装在谁|还装在|追溯", q):
            return "complaint"
        if re.search(r"派工|工程师|上门|排班|点检|服务单|售后|保修", q):
            return "service"
        if not re.search(r"SAL-ORD|A-\d{5}", q) and (re.search(r"客户|满意度|合同|商机|报价|线索|漏斗", q) or
                                                       (any(w in q for w, _ in SITE_WORDS) and re.search(r"怎么了|情况|最近|怎么样", q))):
            return "customer"
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
        "customer": "提示：打开“客户与服务”页，选这个客户看客户 360：合同条款（违约金、响应时限、保修期）、现场设备的健康度、开着的投诉、最近的回访分。"
                    "想一想：哪一项最需要先处理？",
        "complaint": "提示：从投诉的那台设备出发往回追——它装的是哪根输出轴？那根轴是哪张工单、哪片砂轮磨的？同一片砂轮还磨了哪些轴、装到了谁家？"
                     "先自己列出排查范围，再到指挥台里对照因果链。",
        "safety": "提示：打开“安全环保”页：隐患一栏看重大隐患和整改期限，作业许可一栏看谁挂着锁、谁缺资质。处理重大隐患前先做风险评估"
                  "（可能性 × 严重度），再到指挥台比较“立即停机 / 限时整改 / 停机 + 改派加班”三个方案的交期和花费。",
        "maint": "提示：打开“设备维护”页的台账：看每台设备自上次保养运行了多少小时、离保养周期还差多少；点开一台看失效率曲线。"
                 "自己用 F(t) = 1 − exp(−(t/η)^β) 算一算再运行两周坏掉的概率，乘上修理费和停机损失，再和保养的花费比。",
        "supplier": "提示：打开“采购与来料”页：供应商一栏看各家的准时率、合格率和价格，哪几类物料只有一家；到货与检验一栏看抽样数据，按模板的上下限自己判定。"
                    "想一想：便宜的供应商算上晚到和不合格，真的便宜吗？",
        "finance": "提示：打开“经营与财务”页：经营目标一栏看哪些指标是红的；订单毛利一栏点开一张订单，看料、工、电、废品各花了多少；"
                   "应收应付一栏看账龄和现金流预测。想一想：逾期的客户是先催款还是先停发货？现金哪一周最紧？",
        "energy": "提示：打开“能源与环境”页：总览里看每台设备的电量条——灰色的“空转”是开着没活；曲线上红色是峰时。"
                  "想一想：空转的设备设“空闲 N 分钟自动待机”能省多少，再开要预热会不会耽误交期？热处理炉挪到峰时以外开，一天省多少电费？"
                  "单件电量乘电网排放因子（页面上写着）就是这一件的碳排放（电力部分）。",
        "people": "提示：打开“人员”页：技能矩阵里标红的列是只有一个人会开的设备；排班表里标红的格子是这一班没人能开。"
                  "想一想：缺人的这一班，从哪里调人？调走的人原来的岗位怎么办？加班要花多少钱？",
        "service": "提示：在“客户与服务”页的排班表里看 6 位工程师的空闲。同区域每人每天 2 单、跨区域 1 单；想一想：先修哪台、谁去、几天能做完、要带几件备件？",
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
        if r.get("service"):
            for o in r["options"]:
                lines.append("{} {}：{} 台设备、{} 个客户，派 {}，{} 天做完（到 {}），备件 {}，花 ${:,.0f}（保修内 ${:,.0f}）{} [{}]".format(
                    o["key"], o["label"], o["units"], len(o["customers"]), "、".join(o["engineers"]) or "—", o["days"], o["finish"] or "—",
                    "、".join("{} × {}".format(k, v) for k, v in o["spares"].items()) or "不用",
                    o["cost"]["total"], o["cost"]["warranty"],
                    "（还有 {} 台高风险设备没覆盖）".format(len(o["uncovered_high"])) if o["uncovered_high"] else "", o["ref"]))
            return lines
        for o in r["options"]:
            sos = "；".join(self._so_line(s) for s in o["sales_orders"] if s["name"] in r["affected"]) or o.get("note") or "没有受影响的订单"
            lines.append("{} {}：{}，{} ${:,.0f}{}{} [{}]".format(o["key"], o["label"], sos, "省" if o["cost_total"] < 0 else "多花", abs(o["cost_total"]),
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
                                   "and rule in ('P1','M1','P5') order by last_seen desc limit 1", (self.t.mode, unit))
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
            out.append("对应的异常 {} [{}]。推演了 {} 个处理方案：".format("A-{:05d}".format(open_a["id"]), r["anomaly_ref"], len(r["options"])))
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
        order = list(_playbook_rules_ordered())
        with_plays = sorted([a for a in lst if a["rule"] in order], key=lambda a: (order.index(a["rule"]), a["id"]))
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
            out.append("这类异常还没有可推演的处理方案，按说明处理：{}".format(a.get("hint") or "见异常详情"))
            return "\n".join(out)
        out.append("推演了 {} 个处理方案：".format(len(r["options"])))
        out += self._options_text(r)
        if r.get("reason"):
            out.append(r["reason"])
        if r.get("note"):
            out.append(r["note"])
        offer = self._draft_offer(r)
        if offer:
            out.append(offer)
        return "\n".join(out)

    # ---- 客户与服务（第 18 轮 E1）
    def a_customer(self, q):
        if self.student:
            return self._hint("customer")
        name = self.t._customer_name(q)
        if not name:
            lst = [a for a in self.t.list_anomalies(domain="customer")["anomalies"]] + self.t.list_anomalies(domain="service")["anomalies"]
            if not lst:
                return "没听出是哪个客户。可以说客户名或简称，例如“东港码头最近怎么了？”。现在没有开着的客户或服务异常。"
            return "\n".join(["没听出是哪个客户。现在开着的客户与服务异常："] +
                             ["· {} {} [{}]：{}".format(a["severity"], a["key"], a["ref"], a["title"]) for a in lst[:6]])
        r = self.t.customer_360(name)
        if r.get("error"):
            return r["error"]
        k = r["counts"]
        out = ["{} [{}]：".format(name, r["ref"])]
        c = r.get("contract")
        if c and c.get("hidden"):
            out.append("合同 {} [{}]：{}。".format(c["name"], c["ref"], c["hidden"]))
        elif c:
            out.append("合同 {} [{}]：延期违约金 {}，投诉响应 {:g} 小时，保修 {} 个月。".format(
                c["name"], c["ref"], "${:g}/天".format(c["penalty_per_day"]) if c["penalty_per_day"] else "无",
                c.get("response_h") or 24, c.get("warranty_months") or 12))
        else:
            out.append("没有生效的合同（按默认：响应 24 小时、保修 12 个月）。")
        if r["orders"]:
            out.append("订单：" + "；".join("{} 交期 {} [{}]".format(o["name"], o["delivery_date"], o["ref"]) for o in r["orders"][:4]) + "。")
        if r["units"]:
            bad = [u for u in r["units"] if u["health"] in ("red", "yellow")]
            out.append("现场设备 {} 台{}".format(k["units"], "，都正常。" if not bad else "，要注意的：" + "；".join(
                "{} [{}] {}{}".format(u["serial"], u["ref"], "红" if u["health"] == "red" else "黄",
                                      "（{}）".format("、".join(u["alerts"][:2])) if u["alerts"] else "") for u in bad[:5]) + "。"))
        opens = [x for x in r["complaints"] if x["status"] != "已关闭"]
        if opens:
            out.append("开着的投诉：" + "；".join("{} [{}] {}（{}，{}）".format(x["key"], x["ref"], x["subject"], x["severity"], x["status"])
                                            for x in opens[:4]) + "。")
        else:
            out.append("没有开着的投诉。")
        if r["jobs"]:
            out.append("服务单：" + "；".join("{} {} {}".format(j["key"], j["serial"], j["kind"]) for j in r["jobs"][:3]) + "。")
        out.append("回访满意度：{}。".format("{:g} 分（最近 {} 次）".format(r["satisfaction"], r["surveys"]) if r["satisfaction"] is not None else "还没有回访打分"))
        out.append("详见 [{}]。".format(r["page"]))
        return "\n".join(out)

    def a_complaint(self, q):
        if self.student:
            return self._hint("complaint")
        m = re.search(r"CP-(\d{5})", q)
        sm = re.search(r"(WQR105-[A-Z0-9]+-\d{2})", q.upper())
        cid = None
        if m:
            cid = "CP-" + m.group(1)
        elif not sm:
            row = self.t.db.one("select id from complaint where mode=%s and status<>'closed' order by id desc limit 1", (self.t.mode,)) \
                if self.t.db.one("select to_regclass('complaint') is not null as ok")["ok"] else None
            if row is None:
                return "现在没有开着的投诉。要追某台设备，请给序列号（如 WQR105-H2504-06）。"
            cid = "CP-{:05d}".format(row["id"])
        r = self.t.complaint_scope(complaint=cid, serial=sm.group(1) if sm else None)
        if r.get("error"):
            return r["error"]
        out = ["{}{} [{}]（{}）：".format("投诉 {} [{}]，设备 ".format(r["complaint"], r["complaint_ref"]) if r.get("complaint") else "设备 ",
                                    r["serial"], r["unit_ref"], r["customer"])]
        if r["chain"]["summary"]:
            out.append("追溯：" + "；".join(r["chain"]["summary"][:4]) + "。")
        if r["check_units"]:
            out.append("同批次的输出轴还装在 {} 台设备上（{} 个客户），按风险排：".format(len(r["check_units"]), len(r["customers"])))
            for x in r["check_units"][:8]:
                out.append("· {} [{}] {}，健康度{}，最先到期的轴承已用 {:.0f}%{}".format(
                    x["serial"], x["ref"], x["customer"], {"red": "红", "yellow": "黄"}.get(x["health"], "绿"), x["worst_bearing_used"] * 100,
                    "，保修内" if x["in_warranty"] else "，已过保"))
        else:
            out.append("同批次没有装到别的设备上，排查范围只有这一台。")
        if r.get("anomaly_id"):
            o = self.t.compare_options(anomaly_id=r["anomaly_id"])
            if not o.get("error") and o.get("options"):
                out.append("对应异常 A-{:05d} [{}]，按排班估算了 {} 个方案：".format(r["anomaly_id"], r["anomaly_ref"], len(o["options"])))
                out += self._options_text(o)
                if o.get("reason"):
                    out.append(o["reason"])
                offer = self._draft_offer(o)
                if offer:
                    out.append(offer)
        return "\n".join(out)

    def a_service(self, q):
        if self.student:
            return self._hint("service")
        sers = re.findall(r"WQR105-[A-Z0-9]+-\d{2}", q.upper())
        if not sers:
            from hub import service as SV
            us = SV.units(self.t.db, self.t.mode)
            sers = [u["serial"] for u in sorted(us.values(), key=lambda x: -x["risk"]) if u["health"] in ("red", "yellow")]
            if not sers:
                return "现场设备都正常，没有要上门的。"
        kind = "bearing" if re.search(r"换.{0,2}轴承", q) else "inspect" if re.search(r"点检|检查", q) else "auto"
        r = self.t.service_estimate(sers, kind)
        if r.get("error"):
            return r["error"]
        out = ["{} 台设备上门（{}）：派 {}，{} 天做完（{} 到 {}），{:g} 个人天；备件 {}；共 ${:,.0f}，其中保修内由工厂承担 ${:,.0f}，向客户收 ${:,.0f}。".format(
            r["units"], {"bearing": "换轴承", "inspect": "点检"}.get(kind, "按报警修"), "、".join(r["engineers"]) or "—", r["days"], r["start"],
            r["finish"] or "—", r["person_days"], "、".join("{} × {}".format(k, v) for k, v in r["spares"].items()) or "不用",
            r["cost"]["total"], r["cost"]["warranty"], r["cost"]["billable"])]
        for j in r["jobs"][:8]:
            out.append("· {} [{}] {}：{} {}{}".format(j["serial"], j["ref"], j["customer"], j.get("day") or "排不进", j.get("engineer_name") or "",
                                                     "（跨区域）" if j.get("other_region") else ""))
        if r["unplanned"]:
            out.append("还有 {} 台 21 天内排不进。".format(len(r["unplanned"])))
        out.append("这是估算，没有真的排班；排班表 [{}]。".format(r["page"]))
        return "\n".join(out)

    # ---- 采购与来料（第 18 轮 E5）
    def a_supplier(self, q):
        if self.student:
            return self._hint("supplier")
        m = re.search(r"L\d{6}-\d{4}", q)
        if re.search(r"怎么处理|怎么办|方案|该不该", q):
            a = self.t.db.one("select id from anomaly where mode=%s and rule in ('W3','W4','W6') and status in ('open','ack','doing') "
                              "order by case rule when 'W3' then 0 when 'W4' then 1 else 2 end, id desc limit 1", (self.t.mode,))
            if a:
                return self.a_handle("A-{:05d} 怎么处理".format(a["id"]))
        if m or re.search(r"批次|批号|追溯", q):
            lot = m.group(0) if m else None
            if not lot:
                x = self.t.db.one("select lot from lot where mode=%s and lot is not null and status in ('rejected','suspect') order by id desc limit 1", (self.t.mode,))
                lot = x["lot"] if x else None
            if not lot:
                return "现在没有不合格或可疑的批次。可以给我一个批号（如 L261007-0012）来追溯。"
            r = self.t.batch_trace(lot=lot)
            if r.get("error"):
                return r["error"]
            x = r["row"]
            out = ["批次 {} [{}]：{} × {:g}，{}，{}（{}）。".format(lot, r["ref"], x["item"], x["qty"], x["supplier"].split(" ")[0], x["status_label"], r["page"])]
            out.append("用到了 {} 个零件、{} 张工单{}。".format(len(r["parts"]), len(r["work_orders"]),
                                                       "，装进了现场设备 " + "、".join(u["serial"] for u in r["units"][:5]) if r["units"] else ""))
            return "\n".join(out)
        if re.search(r"在途|到货|采购单|晚", q) and not re.search(r"准时率|评分", q):
            r = self.t.purchasing_status()
            k = r["kpis"]
            out = ["采购与来料 [{}]：在途 {} 批，到货待检 {} 批，不合格待处理 {} 批。".format(r["page"], k["in_transit"], k["waiting_inspection"], k["rejected_open"])]
            for x in r["open_lots"][:8]:
                out.append("· {} {} × {:g}（{}）：{}{}".format(x["lot"] or "#{}".format(x["id"]), x["item"], x["qty"], x["supplier"].split(" ")[0], x["status_label"],
                                                          "，承诺 {}".format(x["promised"]) if x["promised"] else ""))
            return "\n".join(out)
        r = self.t.supplier_scorecard()
        out = ["供应商评分卡 [{}]（近 30 天；括号里是过去一年）：".format(r["page"])]
        for x in r["suppliers"]:
            if not x["active"]:
                continue
            out.append("· {} [{}]（{}，{}）：准时率 {}（{:.0%}），合格率 {}（{:.0%}），价格指数 {:g}，提前期 {} 天".format(
                x["supplier"].split(" ")[0], x["ref"], x["cat_name"], "默认" if x["role"] == "default" else "备选",
                "{:.0%}".format(x["on_time"]) if x["on_time"] is not None else "—", x["hist_on_time"],
                "{:.0%}".format(x["pass_rate"]) if x["pass_rate"] is not None else "—", x["hist_pass"], x["price_index"], x["lead_days"]))
        out.append("单一来源：" + ("、".join(s["cat_name"] for s in r["single_source"]) or "没有") + "。" + r["tco_formula"] + "。")
        return "\n".join(out)

    # ---- 经营与财务（第 18 轮 E7）
    def a_finance(self, q):
        if self.student:
            return self._hint("finance")
        if re.search(r"怎么处理|怎么办|方案|该不该", q):
            a = self.t.db.one("select id from anomaly where mode=%s and rule in ('F2','F3','F4','F6') and status in ('open','ack','doing') "
                              "order by case severity when 'critical' then 0 when 'warn' then 1 else 2 end, id desc limit 1", (self.t.mode,))
            if a:
                return self.a_handle("A-{:05d} 怎么处理".format(a["id"]))
        so = re.search(r"SAL-ORD-\d{4}-\d{5}", q)
        if so or re.search(r"毛利", q):
            r = self.t.order_margin(so.group(0) if so else None)
            if r.get("error"):
                return r["error"]
            if so:
                out = ["订单 {} [{}]：{} × {:g}，收入 ${:,.0f}，成本 ${:,.0f}，毛利 ${:,.0f}（{}；按标准 {}）[{}]。".format(
                    r["sales_order"], r["ref"], r["item"], r["qty"], r["revenue"], r["cost"], r["margin"],
                    "{:.1%}".format(r["margin_pct"]) if r["margin_pct"] is not None else "—",
                    "{:.1%}".format(r["std_margin_pct"]) if r["std_margin_pct"] is not None else "—", r["page"])]
                out += ["· {} ${:,.0f}：{}".format(x["label"], x["usd"], x["how"]) for x in r["lines"]]
                return "\n".join(out)
            if not r["margins"]:
                return "还没有做完的订单，算不了毛利 [{}]。".format(r["page"])
            out = ["做完的订单毛利率 {}（目标 {:.0%}）[{}]：".format("{:.1%}".format(r["gross_margin"]) if r["gross_margin"] is not None else "—", r["target"], r["page"])]
            out += ["· {} [{}] {}：毛利率 {}".format(m["sales_order"], m["ref"], str(m["customer"] or "").split(" ")[0],
                                                "{:.1%}".format(m["margin_pct"]) if m["margin_pct"] is not None else "—") for m in r["margins"][:8]]
            return "\n".join(out)
        if re.search(r"目标|指标树|预算|超支", q):
            r = self.t.objectives_budget()
            out = ["经营目标 [{}]：".format(r["page"])]
            for o in r["objectives"]:
                v = o["value"]
                fmt = (lambda x: "{:.0%}".format(x)) if o["unit"] == "pct" else (lambda x: "{:g}".format(round(float(x), 1)))
                out.append("· {} [{}]：{}（目标 {}{}）{}".format(o["name"], o["ref"], fmt(v) if v is not None else "—", "≥" if o["direction"] == "ge" else "≤",
                                                          fmt(o["target"]), {"good": "达标", "warn": "接近", "bad": "偏离", "mute": "没有数"}[o["tone"]]))
            b = r["budget"]
            out.append("{} 预算（月度进度 {:.0%}）：".format(b["month"], b["progress"]) + "；".join(
                "{} ${:,.0f} / ${:,.0f}{}".format(x["name"], x["actual"], x["budget"], "（超）" if x["ratio"] and x["ratio"] > 1.1 else "") for x in b["rows"]) + "。")
            return "\n".join(out)
        r = self.t.ar_ap_cash()
        a = r["ar"]
        out = ["应收 ${:,.0f}（逾期 ${:,.0f}），应收周转 {} 天 [{}]。账龄：{}。".format(a["total"], a["overdue"], r["dso"] if r["dso"] is not None else "—", r["page"],
                                                                     "；".join("{} ${:,.0f}".format(a["buckets"][k], v) for k, v in a["aging"].items()))]
        for x in [x for x in a["invoices"] if x["overdue_days"] > 0][:5]:
            out.append("· {} {} ${:,.0f} 逾期 {:.0f} 天{}".format(x["party"].split(" ")[0], x["doc"] or "期初", x["outstanding"], x["overdue_days"],
                                                           "（已催 {} 次）".format(x["dunned_n"]) if x["dunned_n"] else ""))
        cf = r["cashflow"]
        out.append("应付 ${:,.0f}。现金 ${:,.0f}；未来 8 周最低在第 {} 周 ${:,.0f}。".format(r["ap"]["total"], cf["cash"], cf["low"]["week"], cf["low"]["balance"]))
        over = [c for c in r["credit"] if c["used"] and c["used"] > 1]
        if over:
            out.append("信用超限：" + "；".join("{} ${:,.0f} / ${:,.0f}".format(c["customer"].split(" ")[0], c["exposure"], c["limit"]) for c in over) + "。")
        return "\n".join(out)

    # ---- 能源与环境（第 18 轮 E6）
    def a_energy(self, q):
        if self.student:
            return self._hint("energy")
        unit = find_machine(q)
        if re.search(r"怎么处理|怎么办|方案|该不该|怎么省", q):
            a = self.t.db.one("select id from anomaly where mode=%s and rule like 'N%%' and status in ('open','ack','doing') {} "
                              "order by case severity when 'critical' then 0 when 'warn' then 1 else 2 end, id desc limit 1".format(
                                  "and subject_key=%s" if unit else ""), (self.t.mode, unit) if unit else (self.t.mode,))
            if a:
                return self.a_handle("A-{:05d} 怎么处理".format(a["id"]))
        if re.search(r"碳|排放", q):
            r = self.t.carbon_account()
            if r.get("error"):
                return r["error"]
            out = ["{} 碳核算 [{}]（{}，排放因子 {:g} kg/度）：用电 {:,.0f} 度，排放 {:g} 吨 CO2e（{:g} 小时的数据）[{}]。".format(
                r["month"], r["ref"], r["scope"], r["factor"], r["kwh"], r["t_co2e"], r["hours"], r["page"])]
            top = sorted(r["units"], key=lambda x: -x["kwh"])[:3]
            out.append("用电最多：" + "；".join("{} {:,.0f} 度".format(x["unit"].upper(), x["kwh"]) for x in top) + "。")
            for p in r["products"]:
                out.append("· {} 每件约 {:g} 度、{:g} kg CO2e（{} 道工序{}）".format(p["item"], p["kwh"], p["co2_kg"], p["ops"],
                                                                         "；{} 这个月还没有做过的件，没算进去".format("、".join(u.upper() for u in p["missing"])) if p["missing"] else ""))
            return "\n".join(out)
        if unit or re.search(r"单耗|空转|待机|漏气|压缩空气|空压机|每件", q):
            r = self.t.unit_energy(unit)
            out = ["单耗与空转 [{}]：".format(r["page"])]
            for x in r["unit_energy"]:
                if x["recent"] is None:
                    continue
                out.append("· {} [{}] {}：最近 {} 件每件 {:.2f} 度，基线 {:.2f} 度（{}），{}".format(
                    x["unit"].upper(), x["ref"], x["item"], x["recent_parts"], x["recent"], x["base"] or 0, "近 7 天" if x["base_from"] == "history" else "标准值",
                    "高 {:.0%}".format(x["change"]) if (x["change"] or 0) > 0.05 else "正常"))
            idle = [x for x in r["idle"] if x["idle_kwh"] > 0][:5]
            if idle:
                out.append("近 12 小时空转：" + "；".join("{} {:.1f} 度（{:.0%}）".format(x["unit"].upper(), x["idle_kwh"], x["idle_share"]) for x in idle) + "。")
            a = r["air"]
            if a["hours"]:
                out.append("空压机近 {:g} 小时平均 {:.1f} kW，按开着的用气设备应 {:.1f} kW{}。".format(
                    a["hours"], a["actual_kw"], a["expected_kw"], "，多出 {:.1f} kW，可能漏气".format(a["excess_kw"]) if a["excess_kw"] > 3 else ""))
            return "\n".join(out)
        r = self.t.energy_overview()
        if r.get("error"):
            return r["error"]
        out = ["{} 用电 [{}]：{:,.0f} 度（峰 {:,.0f} / 平 {:,.0f} / 谷 {:,.0f}），电费 ${:,.2f}，峰时占 {:.0%}；碳排放 {:,.0f} kg；空转 {:,.0f} 度（{:.0%}）。".format(
            r["day"], r["page"], r["kwh"], r["by_bucket"]["peak"], r["by_bucket"]["flat"], r["by_bucket"]["valley"], r["cost"], r["peak_share"],
            r["co2_kg"], r["idle_kwh"], r["idle_share"])]
        top = sorted(r["units"], key=lambda x: -x["kwh"])[:3]
        out.append("用电最多：" + "；".join("{} [{}] {:,.0f} 度".format(x["unit"].upper(), x["ref"], x["kwh"]) for x in top) + "。")
        d = r["demand"]
        out.append("本月最大需量 {:.0f} kW，合同 {:.0f} kW（{:.0%}）。".format(d["kw"], d["contract_kw"], d["ratio"]))
        out.append("车间环境：" + "；".join("{} {} {}（限值 {:g}）".format(v["label"], v["value"] if v["value"] is not None else "—", v["unit"], v["limit"])
                                         for v in r["env"].values()) + "。")
        return "\n".join(out)

    # ---- 人员与排班（第 18 轮 E4）
    def a_people(self, q):
        if self.student:
            return self._hint("people")
        unit = find_machine(q)
        if re.search(r"怎么处理|怎么办|方案|该不该", q):
            a = self.t.db.one("select id from anomaly where mode=%s and rule in ('H2','H1') and status in ('open','ack','doing') "
                              "{} order by rule desc, id desc limit 1".format("and subject_key=%s" if unit else ""), (self.t.mode, unit) if unit else (self.t.mode,))
            if a:
                return self.a_handle("A-{:05d} 怎么处理".format(a["id"]))
        if re.search(r"加班|缺勤|出勤率", q) and not re.search(r"排班|缺人|请假", q):
            r = self.t.overtime_load()
            out = ["加班与出勤 [{}]：本周加班上限 {:g} 小时/人。".format(r["page"], r["limit_h"])]
            out += ["· {}：{:g} 小时{}".format(x["name"], x["hours"], "（超限）" if x["over"] else "") for x in r["overtime"][:8]] or ["本周还没有人加班。"]
            out.append("近 7 天缺勤率：" + "；".join("{} {:.0%}（{}/{}）".format(t, x["rate"], x["missed"], x["scheduled"]) for t, x in sorted(r["absence"].items())) + "。")
            return "\n".join(out)
        if re.search(r"技能|会开|单点|一个人|带教|培训", q):
            r = self.t.people_skills(unit)
            if r.get("error"):
                return r["error"]
            out = ["技能矩阵 [{}]：{} 台设备只有一个人能独立操作（单点依赖：{}）。".format(r["page"], len(r["single_points"]),
                                                                  "、".join(u.upper() for u in r["single_points"]) or "没有")]
            for x in r["skills"][:6 if not unit else 1]:
                out.append("· {} [{}]：{}".format(x["unit"].upper(), x["ref"], "、".join("{} [{}]（{}，{}）".format(p["name"], p["ref"], p["level"], p["shift"])
                                                                                   for p in x["people"]) or "没人会开"))
            return "\n".join(out)
        r = self.t.roster_gaps()
        out = ["{} {}，在岗 {} 人，请假或缺勤 {} 人 [{}]。".format(r["now"]["day"], r["now"]["shift"], len(r["on_shift"]), len(r["absent"]), r["page"])]
        if not r["enabled"]:
            out.append("（车间“要有人”现在没打开：缺人不会让设备停下。）")
        if r["roster_gaps"]:
            out.append("24 小时内的排班缺口：")
            out += ["· {} {} {} [{}]：{}".format(g["day"][5:], g["shift_name"], g["unit"].upper(), g["ref"], g["why"]) for g in r["roster_gaps"][:8]]
            a = self.t.db.one("select id from anomaly where mode=%s and rule='H2' and status in ('open','ack','doing') order by id desc limit 1", (self.t.mode,))
            if a:
                out.append("处理方案可以问：“A-{:05d} 怎么处理？”".format(a["id"]))
        else:
            out.append("24 小时内没有排班缺口。")
        return "\n".join(out)

    # ---- 设备维护（第 18 轮 E3）
    def a_maint(self, q):
        if self.student:
            return self._hint("maint")
        unit = find_machine(q)
        if re.search(r"怎么|处理|方案|该不该", q) and (unit or re.search(r"保养", q)):
            a = self.t.db.one("select id from anomaly where mode=%s and rule in ('M2','M4') and status in ('open','ack','doing') "
                              "{} order by id desc limit 1".format("and subject_key=%s" if unit else ""), (self.t.mode, unit) if unit else (self.t.mode,))
            if a:
                return self.a_handle("A-{:05d} 怎么处理".format(a["id"]))
        if unit and re.search(r"概率|风险|坏|失效", q):
            r = self.t.failure_risk(unit)
            if r.get("error"):
                return r["error"]
            return ("{}（{}）[{}]：自上次保养已运行 {:g} 小时（保养周期 {:g} 小时{}）。按失效率模型（β = {:g}，η = {:g} 小时），未来 {:g} 运行小时坏掉的概率 {:.1%}，"
                    "预期停机 {:g} 分钟、预期损失 ${:,.0f}（修理 ${:,.0f} + 停机损失 ${:,.0f} 乘概率）；保养后同样时间里坏掉的概率 {:.1%}，一次保养约 ${:,.0f}。").format(
                UNITS[unit][1], unit.upper(), r["ref"], r["run_h"], r["pm_h"], "，逾期 {:g} 小时".format(r["overdue_h"]) if r["overdue_h"] else "",
                r["beta"], r["eta_h"], r["horizon_h"], r["p_fail"], r["expected_down_min"], r["expected_loss_usd"], r["repair_usd"], r["lost_usd"],
                r["p_after_pm"], r["pm_usd"])
        if re.search(r"维修单|备件|MR-|等件", q):
            r = self.t.repairs_spares()
            out = ["维修与备件 [{}]：开着的维修单 {} 张，保养单 {} 张。".format(r["page"], len(r["repairs"]), len(r["pms"]))]
            for x in r["repairs"][:6]:
                out.append("· {} [{}] {} {}（{}）".format(x["key"], x["ref"], x["unit"].upper(), x["title"], x["status_label"]))
            out.append("备件：" + "；".join("{} [{}] 库存 {:g}（最低 {}）{}".format(x["item_code"], x["ref"], x["stock"], x["min"], "，不足" if x["stock"] < x["min"] else "")
                                         for x in r["spares"]) + "。")
            return "\n".join(out)
        r = self.t.maint_overview()
        k = r["kpis"]
        out = ["设备维护 [{}]：保养逾期 {} 台，开着的维修单 {} 张，点检异常待处理 {} 条，近 7 天故障停机 {:g} 分钟。".format(
            r["page"], k["overdue"], k["open_repairs"], k["open_inspections"], k["failure_down_7d"])]
        for x in r["machines"][:6]:
            out.append("· {} [{}] {}：已运行 {:g} / {:g} 小时{}，未来 {:g} 运行小时坏掉的概率 {:.1%}".format(
                x["unit"].upper(), x["ref"], x["name"], x["run_h"], x["pm_h"], "，逾期 {:g} 小时".format(x["overdue_h"]) if x["overdue_h"] else "",
                r["horizon_h"], x["p_fail"]))
        a = self.t.db.one("select id from anomaly where mode=%s and rule in ('M2','M4') and status in ('open','ack','doing') order by id desc limit 1", (self.t.mode,))
        if a:
            out.append("保养时机的方案可以问：“A-{:05d} 怎么处理？”".format(a["id"]))
        return "\n".join(out)

    # ---- 安全环保（第 18 轮 E2）
    def a_safety(self, q):
        if self.student:
            return self._hint("safety")
        m = re.search(r"SI-(\d{5})", q)
        if m and re.search(r"怎么|处理|方案|办", q):
            a = self.t.db.one("select id from anomaly where mode=%s and rule in ('E1','E2') and fkey=%s order by id desc limit 1",
                              (self.t.mode, "SI-" + m.group(1)))
            if a:
                return self.a_handle("A-{:05d} 怎么处理".format(a["id"]))
        r2 = re.search(r"可能性\D{0,4}(\d)\D{1,8}严重度?\D{0,4}(\d)", q)
        if r2:
            r = self.t.risk_assess(int(r2.group(1)), int(r2.group(2)))
            if r.get("error"):
                return r["error"]
            return "可能性 {} × 严重度 {} = 风险值 {}，属于“{}”风险。{}。".format(r["likelihood"], r["severity"], r["score"], r["level"], r["rule"])
        unit = find_machine(q)
        if unit:
            r = self.t.machine_safety(unit)
            if r.get("error"):
                return r["error"]
            out = ["{}（{}）[{}]：现在{}{}。".format(r["name"], unit.upper(), r["ref"], {"run": "在运转", "idle": "空闲", "down": "停机", "fault": "故障",
                                                                                   "setup": "在调整"}.get(r["state"], r["state"] or "—"),
                                                "，挂牌上锁（{}）".format(r["locked"]) if r["locked"] else "")]
            if r["hazards"]:
                out.append("危险源：" + "；".join("{} [{}] 风险值 {}（{}），控制措施：{}".format(h["name"], h["ref"], h["risk"]["score"], h["risk"]["level"],
                                                                                    "、".join(h["controls"])) for h in r["hazards"]) + "。")
            if r["open_issues"]:
                out.append("开着的隐患：" + "；".join("{} [{}] {}（{}，{}，期限 {}）".format(i["key"], i["ref"], i["subject"], i["level_label"], i["status_label"],
                                                                                 i["due_day"]) for i in r["open_issues"]) + "。")
            else:
                out.append("没有开着的隐患。")
            return "\n".join(out)
        r = self.t.ehs_overview()
        k = r["kpis"]
        out = ["安全概况 [{}]：开着的隐患 {} 条（重大 {} 条，逾期 {} 条），挂牌上锁的设备 {} 台，培训 30 天内到期 / 已过期 {} 项，危废超期 {} 批。".format(
            r["page"], k["open_issues"], k["major_open"], k["overdue"], k["locked"], k["training_due"], k["waste_over"])]
        for i in r["issues"][:6]:
            out.append("· {} [{}] {}：{}（{}{}）".format(i["key"], i["ref"], i["level_label"], i["subject"], i["status_label"], "，已逾期" if i["overdue"] else ""))
        for p in [p for p in r["permits"] if p["block_reason"]][:3]:
            out.append("· 许可 {} [{}] 被拦下：{}".format(p["key"], p["ref"], p["block_reason"]))
        for t in r["trainings_due"][:4]:
            out.append("· {}的“{}”培训{}".format(t["name"], t["label"], "已过期" if t["days_left"] < 0 else " {} 到期".format(t["valid_until"])))
        a = self.t.db.one("select id from anomaly where mode=%s and rule='E1' and status in ('open','ack','doing') order by id desc limit 1", (self.t.mode,))
        if a:
            out.append("重大隐患的处理方案可以问：“A-{:05d} 怎么处理？”".format(a["id"]))
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
        per, shown, more = {}, 0, {}
        for a in lst:                                  # 同一条规则最多列 2 个，其余合并成一句（例如多台设备单点依赖）
            r = a.get("rule") or a["key"]
            per[r] = per.get(r, 0) + 1
            if per[r] > 2 or shown >= 20:
                more[r] = more.get(r, 0) + 1
                continue
            shown += 1
            out.append("· {} {} [{}]：{}".format(a["severity"], a["key"], a["ref"], a["title"]))
        if more:
            out.append("……还有 {} 个（{}），见厂情中枢异常清单。".format(sum(more.values()), "、".join("{} {} 个".format(k, n) for k, n in more.items())))
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


def _playbook_rules_ordered():
    from hub.ont import playbook as PB
    return list(PB.catalog()[0])


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
