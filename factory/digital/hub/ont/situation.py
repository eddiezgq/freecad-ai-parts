# -*- coding: utf-8 -*-
"""指挥台第一屏“全厂态势”（第 17 轮 B 期 B10）：每个领域一块态势卡。

指标只取已有计算（看板、孪生、本体计数）；每天记一次（ont_metric_daily），趋势取近 7 天。
没有数据的领域写明“待接入”和缺什么数据。"""
import datetime as dt

from hub.ont import schema as S

WAITING = {
    "energy": "还没有计量读数（教学模式由仿真车间每 15 分钟发一个；生产模式要接电表）",
}


def _count(db, mode, type_, where="", args=()):
    r = db.one("select count(*) as n from ont_object where mode=%s and type=%s " + where, (mode, type_) + tuple(args))
    return r["n"] if r else 0


def metrics(db, mode, ov, now):
    from hub import kpi
    k = {x["key"]: x for x in ov["kpis"]}
    day0 = kpi.local_day_start(now)
    try:
        from hub import twin as TW
        fl = TW.fleet(db, mode)
    except Exception:  # noqa: BLE001
        fl = []
    open_so = 0
    try:
        open_so = db.one("select count(*) as n from twin_event where mode=%s and kind='order' and status='ordered'", (mode,))["n"]
    except Exception:  # noqa: BLE001
        pass
    pend = 0
    for t in ("design_submission", "process_submission"):
        try:
            pend += db.one("select count(*) as n from {} where mode=%s and status in ('pending', 'submitted')".format(t), (mode,))["n"]
        except Exception:  # noqa: BLE001
            pass
    q8d = 0
    try:
        q8d = db.one("select count(*) as n from quality_8d where mode=%s and closed_at is null", (mode,))["n"]
    except Exception:  # noqa: BLE001
        pass
    down_min = sum((v.get("down_s") or 0) for v in (ov["oee"]["machines"] or {}).values()) / 60
    pos = [d for d in db.erp_docs("Purchase Order", mode) if d["data"].get("status") not in ("Completed", "Closed", "Cancelled")]
    wos = [d for d in db.erp_docs("Work Order", mode) if d["data"].get("status") not in ("Completed", "Closed", "Cancelled", "Stopped")]
    try:                                    # 第 18 轮 E1：客户与服务的指标
        from hub import crm, service as SV
        sk = SV.kpis(db, mode)
        pipe = crm.pipeline(db, mode)
    except Exception:  # noqa: BLE001
        sk, pipe = {}, {}
    try:                                    # 第 18 轮 E2：安全环保
        from hub import ehs as EH
        ek = EH.kpis(db, mode)
    except Exception:  # noqa: BLE001
        ek = None
    try:                                    # 第 18 轮 E3：设备维护
        from hub import maint as MT
        mk = MT.kpis(db, mode)
    except Exception:  # noqa: BLE001
        mk = None
    try:                                    # 第 18 轮 E5：供应链
        from hub import supply as SP
        sk2 = SP.kpis(db, mode)
    except Exception:  # noqa: BLE001
        sk2 = None
    try:                                    # 第 18 轮 E4：人员与组织
        from hub import people as PE
        pk = PE.kpis(db, mode, now)
    except Exception:  # noqa: BLE001
        pk = None
    try:                                    # 第 18 轮 E7：经营与财务
        from hub import finance as FN
        fk = FN.kpis(db, mode)
        obj = FN.objectives(db, mode)
    except Exception:  # noqa: BLE001
        fk, obj = None, []
    try:                                    # 第 18 轮 E6：能源与环境
        from hub import energy as EG
        nk = EG.kpis(db, mode)
    except Exception:  # noqa: BLE001
        nk = None
    M = {
        "strategy": [("oee", "全厂 OEE（今日）", ov["oee"]["value"], "pct"), ("output", "本周产量", (k.get("output") or {}).get("value"), "int")] + ([
            ("objectives_met", "经营目标达标", "{} / {}".format(sum(1 for o in obj if o["tone"] == "good"), len(obj)), "text")] if obj else []),
        "customer": [("satisfaction", "满意度（近 30 天，5 分制）", sk.get("satisfaction"), "num"),
                     ("open_complaints", "开着的投诉", sk.get("open_complaints"), "int"),
                     ("funnel", "漏斗金额", pipe.get("funnel_amount"), "usd"),
                     ("alarm_customers", "有报警设备的客户", len({u["customer"] for u in fl if u["health"] in ("red", "yellow")}), "int")],
        "sales": [("on_time", "准时交付率（本月）", ov["on_time"]["value"], "pct"),
                  ("risk_orders", "风险订单", sum(1 for o in ov["orders"] if o["tone"] in ("bad", "warn")), "int")],
        "product": [("pending_design", "待审批设计 / 工艺", pend, "int"),
                    ("analysis_7d", "近 7 天分析作业", _count(db, mode, "AnalysisJob", "and first_ts > %s", (now - dt.timedelta(days=7),)), "int")],
        "supply": [("short_items", "缺料项", sum(1 for m in ov["materials"] if m["tone"] == "bad"), "int"), ("open_po", "在途采购单", len(pos), "int")] + ([
            ("on_time", "供应商准时率（近 30 天）", sk2["on_time"], "pct"), ("pass_rate", "来料合格率（近 30 天）", sk2["pass_rate"], "pct"),
            ("single_source", "单一来源的物料类别", sk2["single_source"], "int")] if sk2 else []),
        "planning": [("open_wo", "未完工单", len(wos), "int"), ("wip", "在制品（件）", ov["wip"]["now"], "int")],
        "production": [("oee", "OEE（今日）", ov["oee"]["value"], "pct"),
                       ("down", "停机设备", ov["machine_counts"].get("down", 0) + ov["machine_counts"].get("fault", 0), "int")],
        "quality": [("fpy", "一次合格率（本周）", ov["quality"]["fpy_week"]["value"], "pct"),
                    ("ncr_8d", "开着的不合格品 / 8D", ov["quality"]["ncr_open"] + q8d, "int")],
        "warehouse": [("below_safety", "低于安全库存", sum(1 for m in ov["materials"] if m["tone"] in ("bad", "warn")), "int"),
                      ("moves_today", "今日搬运任务", _count(db, mode, "TransportTask", "and first_ts >= %s", (day0,)), "int")],
        "service": [("units_red", "现场设备 红 / 黄", "{} / {}".format(sum(1 for u in fl if u["health"] == "red"),
                                                                    sum(1 for u in fl if u["health"] == "yellow")), "text"),
                    ("open_service", "待上门的服务", sk.get("open_jobs", open_so), "int"),
                    ("response_h", "投诉平均响应（小时）", sk.get("response_h"), "num"),
                    ("first_fix", "一次修复率", sk.get("first_fix"), "pct"),
                    ("warranty_cost", "保修成本（近 30 天）", sk.get("warranty_cost"), "usd")],
        "maintenance": [("down_min", "今日停机（分钟）", round(down_min), "int")] + ([
            ("pm_overdue", "保养逾期的设备", mk["overdue"], "int"), ("open_repairs", "开着的维修单", mk["open_repairs"], "int"),
            ("failure_down_7d", "近 7 天故障停机（分钟）", round(mk["failure_down_7d"]), "int"), ("mtbf", "平均故障间隔（小时）", mk["mtbf"], "num")] if mk else []),
        "ehs": [("open_issues", "开着的隐患（重大）", "{}（{}）".format(ek["open_issues"], ek["major_open"]), "text"),
                ("on_time", "整改按期率（近 30 天）", ek["on_time"], "pct"),
                ("locked", "挂牌上锁的设备", ek["locked"], "int"),
                ("training_due", "培训 30 天内到期 / 已过期", ek["training_due"], "int"),
                ("near_miss", "未遂（近 30 天）", ek["near_miss_30d"], "int"), ("major_open", "开着的重大隐患", ek["major_open"], "int")] if ek else [],
        "people": [("attendance", "这一班出勤率", pk["attendance_rate"], "pct"), ("gaps", "24 小时内排班缺口", pk["gaps"], "int"),
                   ("single_points", "单点依赖的设备", pk["single_points"], "int"), ("overtime_h", "本周加班（小时）", pk["overtime_h_week"], "num")]
        if pk else [],
        "energy": [("kwh", "今天用电（度）", nk["kwh"], "int"), ("cost", "今天电费", nk["cost"], "usd"), ("peak_share", "峰时用电占比", nk["peak_share"], "pct"),
                   ("idle_share", "空转电量占比", nk["idle_share"], "pct"), ("co2_kg", "今天碳排放（kg）", nk["co2_kg"], "int"),
                   ("demand_ratio", "需量 / 合同需量（本月）", nk["demand_ratio"], "pct")] if nk else [],
        "finance": [("cost_var", "本周成本偏差", ov["cost"]["value"], "pct_signed")] + ([
            ("gross_margin", "毛利率（做完的订单）", fk["gross_margin"], "pct"), ("ar_overdue", "逾期应收", fk["ar_overdue"], "usd"),
            ("dso", "应收周转天数", fk["dso"], "num"), ("budget_used", "预算已用（本月）", fk["budget_used"], "pct"), ("cash", "现金", fk["cash"], "usd")] if fk else []),
    }
    return M


def record(db, mode, day, M):
    for dom, ms in M.items():
        for key, _, v, fmt in ms:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                db.x("insert into ont_metric_daily (mode, day, domain, metric, value) values (%s,%s,%s,%s,%s) "
                     "on conflict (mode, day, domain, metric) do update set value=excluded.value", (mode, day, dom, key, float(v)))


def backfill(db, mode, now, days=6):
    """第一次打开时回算过去几天（每天按当天 17:00 下班时的看板算）；算不出来的跳过"""
    from hub import kpi
    for i in range(1, days + 1):
        t = kpi.local_day_start(now - dt.timedelta(days=i)) + dt.timedelta(hours=17)
        try:
            record(db, mode, t.astimezone(kpi.TZ).date(), metrics(db, mode, kpi.overview(db, t, mode), t))
        except Exception:  # noqa: BLE001
            continue


def cards(db, detector, mode, now=None, live=True):
    """live=False：时间回看（不记当天指标、异常按那时开着的算）"""
    from hub import kpi
    now = now or dt.datetime.now(dt.timezone.utc)
    detector.init()
    ov = kpi.overview(db, now, mode)
    M = metrics(db, mode, ov, now)
    today = now.astimezone(kpi.TZ).date()
    if live:
        record(db, mode, today, M)
    if live and not db.one("select 1 as x from ont_metric_daily where mode=%s and day < %s limit 1", (mode, today)):
        backfill(db, mode, now)
    trend = {}
    for r in db.q("select day, domain, metric, value from ont_metric_daily where mode=%s and day > %s and day <= %s order by day",
                  (mode, today - dt.timedelta(days=7), today)):
        trend.setdefault((r["domain"], r["metric"]), []).append([r["day"].isoformat(), r["value"]])
    an = {}
    q = ("select domain, severity, count(*) as n from anomaly where mode=%s and status in ('open','ack','doing') group by 1, 2" if live else
         "select domain, severity, count(*) as n from anomaly where mode=%s and first_seen <= %s and (closed_at is null or closed_at > %s) group by 1, 2")
    for r in db.q(q, (mode,) if live else (mode, now, now)):
        an.setdefault(r["domain"], {})[r["severity"]] = r["n"]
    running, waiting = {}, {}
    for rid, r in detector.catalog.items():
        (waiting if r["waiting"] else running).setdefault(r["domain"], []).append(rid)
    out = []
    for d in S.get().domains:
        dom = d["domain"]
        if dom == "core":
            continue
        ms = [{"key": k, "label": lab, "value": v, "fmt": f, "trend": trend.get((dom, k), [])} for k, lab, v, f in M.get(dom, [])]
        out.append({"domain": dom, "label": d["label"], "row": d["row"], "order": d["order"], "metrics": ms,
                    "anomalies": an.get(dom, {}), "rules_live": sorted(running.get(dom, [])), "rules_waiting": sorted(waiting.get(dom, [])),
                    "waiting": WAITING.get(dom) if not ms else None})
    return {"cards": out, "now": now.isoformat(), "total_open": sum(sum(x.values()) for x in an.values())}
