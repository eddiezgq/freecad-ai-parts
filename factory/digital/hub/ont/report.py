# -*- coding: utf-8 -*-
"""厂情日报 / 经营周报（第 17 轮 D 期 D7）。

- 数字全部由规则从历史库算，与看板（hub.kpi.overview）、异常表、动作表、复盘表同一套数据；文字可由模型改写（D5，数字逐个核对）。
- 日报：生产模式每天 07:30（工厂时间）生成前一天的；周报：每周一 08:00 生成上周的。教学模式不定时，点“生成”即时生成（最近 24 小时 / 7 天）。
- 存进 report 表，本体里是“厂情报告”对象；按订阅推送（站内、邮件、群机器人）。"""
import datetime as dt
import logging

from psycopg.types.json import Jsonb

from hub import kpi

log = logging.getLogger("report")

SCHEMA = """
create table if not exists report (
    id           bigserial primary key,
    mode         text not null,
    kind         text not null,               -- daily / weekly
    title        text not null,
    period_start timestamptz not null,
    period_end   timestamptz not null,
    data         jsonb not null,
    text         text,
    engine       text,
    created_by   text,
    created_at   timestamptz not null default now()
);
create index if not exists report_ts on report (mode, kind, period_start);
"""
DAILY_AT = (7, 30)
WEEKLY_AT = (0, 8, 0)              # 周一 08:00
SEV = {"critical": "严重", "warn": "警告", "info": "提示"}


def init(db):
    db.x(SCHEMA)


def _pct(v, d=0):
    return "—" if v is None else ("{:." + str(d) + "f}%").format(v * 100)


def window(kind, mode, now=None):
    """报告覆盖的时段：生产模式按自然日 / 自然周（工厂时间），教学模式按最近 24 小时 / 7 天"""
    now = now or dt.datetime.now(dt.timezone.utc)
    if mode == "teach":
        return now - dt.timedelta(days=1 if kind == "daily" else 7), now
    today0 = kpi.local_day_start(now)
    if kind == "daily":
        return today0 - dt.timedelta(days=1), today0
    wk0 = today0 - dt.timedelta(days=now.astimezone(kpi.TZ).weekday())
    return wk0 - dt.timedelta(days=7), wk0


def build(db, mode, kind, start, end):
    """算一份报告的数据（不写库）"""
    ov = kpi.overview(db, end, mode)
    k = {x["key"]: x for x in ov["kpis"]}
    data = {"kind": kind, "start": start.isoformat(), "end": end.isoformat(), "local_time": ov["local_time"]}
    data["kpis"] = {
        "oee": ov["oee"]["value"], "on_time": ov["on_time"]["value"], "fpy_week": ov["quality"]["fpy_week"]["value"],
        "output_week": k["output"]["value"], "plan_week": k["output"]["total"], "wip": ov["wip"]["now"], "cost_var": ov["cost"]["value"],
        "down_machines": [m["code"] for m in ov["machines"] if m["state"] in ("down", "fault")],
    }
    # ---- 异常：时段内新发现、处理完、到时段末还开着
    new = db.q("select id, rule, domain, severity, title, subject_type, subject_key from anomaly where mode=%s and first_seen >= %s and first_seen < %s "
               "order by first_seen", (mode, start, end))
    closed = db.q("select id, rule, domain, severity, title, closed_reason from anomaly where mode=%s and closed_at >= %s and closed_at < %s",
                  (mode, start, end))
    still = db.q("select id, rule, domain, severity, title, subject_type, subject_key, chain from anomaly where mode=%s and first_seen < %s "
                 "and (closed_at is null or closed_at >= %s) order by case severity when 'critical' then 0 when 'warn' then 1 else 2 end, last_seen desc",
                 (mode, end, end))
    by_dom = {}
    for a in new:
        d = by_dom.setdefault(a["domain"], {"new": 0, "closed": 0, "open": 0})
        d["new"] += 1
    for a in closed:
        by_dom.setdefault(a["domain"], {"new": 0, "closed": 0, "open": 0})["closed"] += 1
    for a in still:
        by_dom.setdefault(a["domain"], {"new": 0, "closed": 0, "open": 0})["open"] += 1
    data["anomalies"] = {"new": len(new), "closed": len(closed), "open": len(still), "by_domain": by_dom,
                         "open_list": [{"id": a["id"], "key": "A-{:05d}".format(a["id"]), "severity": a["severity"], "title": a["title"],
                                        "rule": a["rule"]} for a in still[:12]]}
    data["anomaly_ids"] = sorted({a["id"] for a in new} | {a["id"] for a in closed} | {a["id"] for a in still})
    # ---- 动作
    acts = db.q("select id, type, title, status, created_at, executed_at, initiator, approver from action where mode=%s and "
                "((created_at >= %s and created_at < %s) or (executed_at >= %s and executed_at < %s))", (mode, start, end, start, end)) \
        if _has(db, "action") else []
    st = {}
    for a in acts:
        st[a["status"]] = st.get(a["status"], 0) + 1
    data["actions"] = {"total": len(acts), "by_status": st,
                       "executed": [{"key": "ACT-{:05d}".format(a["id"]), "title": a["title"], "status": a["status"]}
                                    for a in acts if a["executed_at"] and start <= a["executed_at"] < end],
                       "failed": [{"key": "ACT-{:05d}".format(a["id"]), "title": a["title"]} for a in acts if a["status"] == "failed"]}
    # ---- 交付风险
    data["risk_orders"] = [{"name": o["name"], "customer": o["customer"].split(" ")[0], "delivery_date": o["delivery_date"],
                            "projected": o["projected"], "risk": o["risk"], "tone": o["tone"]} for o in ov["orders"] if o["tone"] in ("bad", "warn")]
    data["low_materials"] = [{"code": m["code"], "name": m["name"], "status": m["status"], "qty_text": m["qty_text"]}
                             for m in ov["materials"] if m["tone"] == "bad"]
    # ---- 推演与实际（复盘）
    rts = db.q("select id, title, deviation from retro where mode=%s and created_at >= %s and created_at < %s order by id", (mode, start, end)) \
        if _has(db, "retro") else []
    data["retros"] = [{"key": "RT-{:05d}".format(r["id"]), "title": r["title"], "finish_pct": (r["deviation"] or {}).get("finish_pct"),
                       "cost_diff": (r["deviation"] or {}).get("cost_diff")} for r in rts]
    # ---- 今天（本周）要关注的 3 件
    focus = []
    for a in still:
        if len(focus) >= 3:
            break
        sc = ((a["chain"] or {}).get("scope") or {})
        n = len(sc.get("sales_orders") or [])
        focus.append({"text": "{}（{}）{}".format(a["title"], "A-{:05d}".format(a["id"]), "，影响 {} 张订单".format(n) if n else ""),
                      "url": "/ont?view=anomalies&a={}".format(a["id"])})
    for o in data["risk_orders"]:
        if len(focus) >= 3:
            break
        if not any(o["name"] in f["text"] for f in focus):
            focus.append({"text": "{} {}，交期 {}".format(o["name"], o["risk"], o["delivery_date"]), "url": "/"})
    for m in data["low_materials"]:
        if len(focus) >= 3:
            break
        focus.append({"text": "{}（{}）{}，库存 {}".format(m["name"], m["code"], m["status"], m["qty_text"]), "url": "/"})
    data["focus"] = focus
    if kind == "weekly":
        data.update(_weekly(db, mode, start, end))
    return data


def _has(db, t):
    return bool(db.one("select to_regclass(%s) is not null as ok", (t,))["ok"])


def _weekly(db, mode, start, end):
    from hub import mrp
    out = {}
    d0, d1 = start.astimezone(kpi.TZ).date(), end.astimezone(kpi.TZ).date()
    tr = {}
    for r in db.q("select day, domain, metric, value from ont_metric_daily where mode=%s and day >= %s and day < %s and "
                  "metric in ('oee','on_time','fpy','down_min','cost_var','risk_orders','short_items') order by day", (mode, d0, d1)) \
            if _has(db, "ont_metric_daily") else []:
        tr.setdefault(r["metric"], []).append([r["day"].isoformat(), r["value"]])
    out["trends"] = tr
    rec = db.q("select rule, subject_type, subject_key, count(*) as n, max(title) as title from anomaly where mode=%s and first_seen >= %s "
               "and first_seen < %s group by 1, 2, 3 having count(*) >= 2 order by n desc limit 8", (mode, start, end))
    out["recurring"] = [{"rule": r["rule"], "subject": r["subject_key"], "n": r["n"], "title": r["title"]} for r in rec]
    hits = db.q("select rule, count(*) as n from anomaly where mode=%s and first_seen >= %s and first_seen < %s group by 1 order by n desc",
                (mode, start, end))
    out["rule_hits"] = {r["rule"]: r["n"] for r in hits}
    wos = [r["corr"] for r in db.q("select distinct corr from bus_message where mode=%s and type='machine.event' and corr like 'MFG-WO-%%' "
                                   "and ts >= %s and ts < %s and payload->'data'->>'event'='cycle_end'", (mode, start, end))]
    costs = []
    for w in wos[:40]:
        c = mrp.wo_cost(db, w, mode)
        if c and c.get("variance") is not None:
            costs.append({"work_order": w, "variance": round(c["variance"], 2), "variance_pct": c.get("variance_pct"), "worst": c.get("worst_operation")})
    out["cost_top"] = sorted(costs, key=lambda x: -x["variance"])[:5]
    if _has(db, "retro"):
        r = db.one("select id, title, deviation from retro where mode=%s and created_at >= %s and created_at < %s "
                   "order by abs(coalesce((deviation->>'finish_pct')::float, 0)) desc limit 1", (mode, start, end))
        out["worst_retro"] = {"key": "RT-{:05d}".format(r["id"]), "title": r["title"], "finish_pct": (r["deviation"] or {}).get("finish_pct")} if r else None
    return out


def text_of(kind, data):
    """规则文字（一段话 + 分节），数字全部来自 data"""
    k = data["kpis"]
    a = data["anomalies"]
    head = "{}（截至 {}）：OEE {}，准时交付率 {}，本周完工 {}/{}，一次合格率 {}，在制品 {} 件。".format(
        "厂情日报" if kind == "daily" else "经营周报", data["local_time"], _pct(k["oee"]), _pct(k["on_time"]), k["output_week"], k["plan_week"],
        _pct(k["fpy_week"], 1), k["wip"])
    lines = [head, "异常：新发现 {} 个，处理完 {} 个，还开着 {} 个。".format(a["new"], a["closed"], a["open"])]
    ac = data["actions"]
    if ac["total"]:
        lines.append("动作：{} 个（{}）。".format(ac["total"], "、".join("{} {}".format(_ST.get(s, s), n) for s, n in ac["by_status"].items())))
    if data["risk_orders"]:
        lines.append("交付风险：" + "；".join("{} {}".format(o["name"], o["risk"]) for o in data["risk_orders"]) + "。")
    if data["retros"]:
        lines.append("推演与实际：" + "；".join("{} 完工偏差 {}".format(r["key"], "{:+.1f}%".format(r["finish_pct"]) if r["finish_pct"] is not None else "—")
                                           for r in data["retros"]) + "。")
    if data["focus"]:
        lines.append("{}要关注：".format("今天" if kind == "daily" else "本周") + "；".join("{}. {}".format(i + 1, f["text"]) for i, f in enumerate(data["focus"])) + "。")
    if kind == "weekly":
        if data.get("recurring"):
            lines.append("反复出现：" + "；".join("{}（{} 次）".format(r["title"], r["n"]) for r in data["recurring"][:3]) + "。")
        if data.get("cost_top"):
            lines.append("成本差异最大：" + "；".join("{} 高 ${:,.2f}".format(c["work_order"], c["variance"]) for c in data["cost_top"][:3]) + "。")
    return "\n".join(lines)


_ST = {"draft": "草稿", "submitted": "待批准", "approved": "已批准", "rejected": "已驳回", "executing": "执行中", "done": "已完成", "failed": "失败"}


def generate(db, mode, kind, now=None, by="系统", llm=None, notify=True):
    if kind not in ("daily", "weekly"):
        raise ValueError("报告种类只能是 daily 或 weekly")
    init(db)
    start, end = window(kind, mode, now)
    data = build(db, mode, kind, start, end)
    text = text_of(kind, data)
    engine = "rules"
    if mode != "teach" and llm is not None and llm.available():
        from hub.ont import narrate as NR
        p = NR.polish(llm, text, {k: data[k] for k in ("kpis", "anomalies", "actions", "risk_orders", "focus")},
                      "把这份{}改写成给厂长看的简报：先一句总评，再分点；保留全部数字和单号".format("日报" if kind == "daily" else "周报"), limit=400)
        if p["by"] != "rules":
            text, engine = p["text"], p["by"]
    d0 = start.astimezone(kpi.TZ)
    title = ("厂情日报 {}" if kind == "daily" else "经营周报 {} 起").format(d0.strftime("%Y-%m-%d") if mode != "teach" else
                                                                     end.astimezone(kpi.TZ).strftime("%Y-%m-%d %H:%M"))
    r = db.one("insert into report (mode, kind, title, period_start, period_end, data, text, engine, created_by) values (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
               "returning id", (mode, kind, title, start, end, Jsonb(data), text, engine, by))
    if notify:
        try:
            from hub.ont import notify as NT
            NT.emit(db, mode, "role:manager", "report", title, text.split("\n")[0], "/ont/reports?id={}".format(r["id"]),
                    "RPT-{:05d}".format(r["id"]), "core", "info")
        except Exception:  # noqa: BLE001
            log.exception("报告通知失败")
    return r["id"]


def due(db, mode, now=None):
    """生产模式的定时：每天 07:30 生成前一天的日报；周一 08:00 生成上周的周报。返回该生成的种类"""
    if mode == "teach":
        return []
    init(db)
    now = now or dt.datetime.now(dt.timezone.utc)
    lt = now.astimezone(kpi.TZ)
    out = []
    if (lt.hour, lt.minute) >= DAILY_AT:
        s, _ = window("daily", mode, now)
        if not db.one("select 1 as x from report where mode=%s and kind='daily' and period_start=%s", (mode, s)):
            out.append("daily")
    if lt.weekday() == WEEKLY_AT[0] and (lt.hour, lt.minute) >= WEEKLY_AT[1:]:
        s, _ = window("weekly", mode, now)
        if not db.one("select 1 as x from report where mode=%s and kind='weekly' and period_start=%s", (mode, s)):
            out.append("weekly")
    return out


def row(r, full=False):
    out = {"id": r["id"], "key": "RPT-{:05d}".format(r["id"]), "kind": r["kind"], "title": r["title"], "period_start": r["period_start"].isoformat(),
           "period_end": r["period_end"].isoformat(), "engine": r["engine"], "created_by": r["created_by"], "created_at": r["created_at"].isoformat(),
           "summary": (r["text"] or "").split("\n")[0]}
    if full:
        out.update(data=r["data"], text=r["text"])
    return out
