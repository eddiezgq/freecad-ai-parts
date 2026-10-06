# -*- coding: utf-8 -*-
"""复盘（第 17 轮 D 期 D8）：推演好不好，用事后数据检验。

自动复盘：异常已解决、它采纳的动作已执行完、受影响的工单都做完了（或已过 14 天），就生成一份：
  ① 当时的快照和采纳的方案；② 推演预测 vs 实际（每张工单、订单的完工时刻，多花的钱）；
  ③ 偏差和可能的原因（停机比预计长 / 短、某工序实际节拍比推演慢、期间又出了别的异常、动作执行失败——都从历史库找证据）；
  ④ “如果当时……”：用当时的快照把各个预案方案重算一遍。
校准提示：同一台设备、同一工序，连续 3 次复盘都是实际比推演慢 10% 以上 → 在规则目录提示“建议检查标准工时 / 维修时长”（只提示，不自动改）。

时间基准：推演和实际都用工厂时间（仿真倍速运行时比真实时间快）——实际完工取车间事件里的 factory_ts。"""
import datetime as dt
import logging

from psycopg.types.json import Jsonb

from hub.ont import plan as P

log = logging.getLogger("retro")

SCHEMA = """
create table if not exists retro (
    id             bigserial primary key,
    mode           text not null,
    anomaly_id     bigint,
    action_id      bigint,
    scenario_id    bigint,
    snapshot_id    bigint,
    title          text not null,
    predicted      jsonb,
    actual         jsonb,
    deviation      jsonb,
    counterfactual jsonb,
    causes         jsonb,
    partial        boolean not null default false,
    created_at     timestamptz not null default now()
);
create index if not exists retro_anomaly on retro (mode, anomaly_id);
"""
WAIT_DAYS = 14
ACTION_TYPES = ("reassign", "reorder", "overtime", "expedite", "urgent_purchase", "outsource", "split_delivery")
SLOW_PCT = 10.0


def init(db):
    db.x(SCHEMA)


def _fdt(s):
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def _snapshot_for(db, act):
    """动作试运行用的快照；没有记下的话取动作创建前最近的一张"""
    sid = ((act["trial"] or {}).get("snapshot_id"))
    if sid:
        r = db.one("select id, state, exact from sim_snapshot where id=%s", (sid,))
        if r:
            return r
    return db.one("select id, state, exact from sim_snapshot where mode=%s and ts <= %s order by ts desc limit 1", (act["mode"], act["created_at"]))


def actual_finish(db, mode, wo, since=None):
    """工单实际完工（工厂时间）：最后一道工序每件的 cycle_end；全部件做完才算完工。返回 (完工时刻或 None, 已完成件数, 每件完工时刻)"""
    evs = db.messages(["machine.event"], corr=wo, mode=mode)
    ends = [e["data"] for e in evs if e["data"].get("event") == "cycle_end" and e["data"].get("op_index") == (e["data"].get("n_ops") or 0) - 1]
    qty = max([int(e.get("qty") or 0) for e in ends] or [0])
    ts = sorted(_fdt(e["factory_ts"]) for e in ends if e.get("factory_ts"))
    done = len({e["part_serial"] for e in ends})
    return (ts[-1] if ts and qty and done >= qty else None), done, ts


def _so_rows(ctx, wo_finish, tz):
    """订单：用工单完工时刻推交付（与推演同一算法：最后一根轴做完 + 下游工作日）"""
    from hub import kpi
    out = []
    for so in ctx.get("sales_orders") or []:
        ws = [w for w in so.get("work_orders") or [] if w in wo_finish]
        if not ws or any(wo_finish[w] is None for w in ws):
            out.append({"name": so["name"], "delivery_date": str(so["delivery_date"])[:10], "projected": None, "late_days": None})
            continue
        fin = max(wo_finish[w] for w in ws).astimezone(tz).date()
        proj = kpi.add_working_days(fin, P.DOWNSTREAM_DAYS.get(so.get("item"), 0))
        due = dt.date.fromisoformat(str(so["delivery_date"])[:10])
        late = kpi.working_days_between(due, proj) if proj > due else -kpi.working_days_between(proj, due)
        out.append({"name": so["name"], "delivery_date": due.isoformat(), "projected": proj.isoformat(), "late_days": late})
    return out


def build(db, anomaly, actions, now=None):
    """算一份复盘（不写库）。actions：这个异常下已执行的动作（按 id 排）"""
    from hub.ont import playbook as PB
    from sim.calendar import Calendar
    mode = anomaly["mode"]
    act = actions[0]
    snap = _snapshot_for(db, act)
    if snap is None:
        raise P.PlanError("找不到当时的快照")
    st = snap["state"]
    f0 = _fdt(st["factory_now"])
    tz = Calendar.from_dict(st.get("calendar")).tzi
    ctx = P.context(db, mode, f0)
    changes = [dict(a["params"]) for a in actions]
    pred = P.simulate(st, changes, ctx)
    names = PB.affected(anomaly, ctx)
    watch = sorted({w for so in ctx["sales_orders"] if so["name"] in names for w in so.get("work_orders") or []} & set(pred["work_orders"]))
    watch = [w for w in watch if not pred["work_orders"][w].get("done_before")]
    # ---- 实际
    act_fin, act_done = {}, {}
    for w in watch:
        fin, done, _ = actual_finish(db, mode, w)
        act_fin[w], act_done[w] = fin, done
    partial = any(v is None for v in act_fin.values())
    pred_fin = {w: (_fdt(pred["work_orders"][w]["finish"]) if pred["work_orders"][w]["finish"] else None) for w in watch}
    wo_rows, worst = [], None
    for w in watch:
        p_, a_ = pred_fin[w], act_fin[w]
        row = {"work_order": w, "predicted": p_.isoformat() if p_ else None, "actual": a_.isoformat() if a_ else None,
               "done": act_done[w], "qty": pred["work_orders"][w]["qty"]}
        if p_ and a_:
            dp, da = (p_ - f0).total_seconds(), (a_ - f0).total_seconds()
            row["diff_h"] = round((da - dp) / 3600, 2)
            row["pct"] = round((da - dp) / dp * 100, 1) if dp > 0 else 0.0
            if worst is None or abs(row["pct"]) > abs(worst["pct"]):
                worst = row
        wo_rows.append(row)
    pred_so = [s for s in pred["sales_orders"] if s["name"] in names]
    fin_map = {w: (_fdt(x["finish"]) if x.get("finish") else None) for w, x in pred["work_orders"].items() if x.get("done_before")}
    fin_map.update(act_fin)
    act_so = [s for s in _so_rows(ctx, fin_map, tz) if s["name"] in names]
    # 多花的钱：执行了的动作的费用（与推演同一口径）+ 按实际交付算的违约金
    act_costs = [c for c in pred["costs"] if "违约金" not in c["what"]]
    for s in act_so:
        pen = P.PENALTY_PER_DAY.get(s["name"])
        if pen and s["late_days"] and s["late_days"] > 0:
            act_costs.append({"what": "{} 违约金（晚 {} 天）".format(s["name"], s["late_days"]), "usd": pen * s["late_days"]})
    predicted = {"factory_now": f0.isoformat(), "changes": changes, "work_orders": {w: r["predicted"] for w, r in zip(watch, wo_rows)},
                 "sales_orders": pred_so, "costs": pred["costs"], "cost_total": pred["cost_total"], "downtime": pred["downtime"]}
    actual = {"work_orders": {r["work_order"]: r["actual"] for r in wo_rows}, "done": {r["work_order"]: r["done"] for r in wo_rows},
              "sales_orders": act_so, "costs": act_costs, "cost_total": round(sum(c["usd"] for c in act_costs), 2)}
    deviation = {"work_orders": wo_rows, "finish_pct": worst["pct"] if worst else None, "finish_diff_h": worst["diff_h"] if worst else None,
                 "cost_diff": round(actual["cost_total"] - pred["cost_total"], 2),
                 "late_diff": [{"name": a["name"], "predicted": p_["late_days"], "actual": a["late_days"]}
                               for a, p_ in zip(act_so, pred_so) if a["late_days"] != p_["late_days"]]}
    causes = _causes(db, mode, st, pred, f0, now, actions, anomaly)
    # ---- 如果当时……
    cf = []
    try:
        ev = PB.evaluate(dict(anomaly, chain=anomaly.get("chain")), st, ctx)
        chosen = {c["type"] for c in changes}
        for o in ev["options"]:
            kinds = {c["type"] for c in o["changes"]}
            cf.append({"key": o["key"], "label": o["label"], "chosen": bool(kinds) and kinds <= chosen or (not kinds and not chosen),
                       "recommended": o["recommended"], "cost_total": o["result"]["cost_total"],
                       "sales_orders": [{k: s.get(k) for k in ("name", "projected", "late_days")} for s in o["result"]["sales_orders"]]})
    except Exception as e:  # noqa: BLE001
        log.warning("复盘的“如果当时”没算成：%s", e)
    title = "{}：采纳{}".format(anomaly["title"], "、".join(a["title"] for a in actions))
    return {"title": title[:200], "snapshot_id": snap["id"], "predicted": predicted, "actual": actual, "deviation": deviation,
            "counterfactual": cf, "causes": causes, "partial": partial, "watch": watch, "exact": snap["exact"]}


def _causes(db, mode, st, pred, f0, now, actions, anomaly):
    """偏差的可能原因：都从历史库找证据（总线消息序号）"""
    out = []
    # ① 停机：快照里在停的设备，预计恢复 vs 实际恢复
    for u, m in (st.get("machines") or {}).items():
        if m.get("state") in ("down", "fault") and m.get("down_until") is not None:
            exp = _fdt(st["epoch"]) + dt.timedelta(seconds=float(m["down_until"]))
            for c in [c for c in (actions or []) if c["params"].get("type") == "expedite" and c["params"].get("unit") == u]:
                exp = f0 + (exp - f0) * float(c["params"].get("factor", 0.5))
            rec = [r for r in db.q("select seq, payload from bus_message where mode=%s and type='machine.event' and topic like %s "
                                   "and payload->'data'->>'event'='recover' order by seq", (mode, "%/" + u + "/event"))
                   if r["payload"]["data"].get("factory_ts") and _fdt(r["payload"]["data"]["factory_ts"]) >= f0]
            if rec:
                at = _fdt(rec[0]["payload"]["data"]["factory_ts"])
                diff = (at - exp).total_seconds() / 60
                if abs(diff) >= 10:
                    out.append({"kind": "downtime", "unit": u, "minutes": round(diff),
                                "text": "{} 实际恢复比推演{} {:.0f} 分钟".format(u.upper(), "晚" if diff > 0 else "早", abs(diff)),
                                "seq": rec[0]["seq"]})
    # ② 节拍：推演里每台设备每道工序的平均单件时间 vs 实际
    pc = {}
    for g in pred.get("gantt") or []:
        s, e = _fdt(g["start"]), _fdt(g["end"])
        pc.setdefault((g["unit"], g["op"]), []).append((e - s).total_seconds())
    ac = {}
    for r in db.q("select topic, payload from bus_message where mode=%s and type='machine.event' and payload->'data'->>'event'='cycle_end' "
                  "and payload->'data'->>'factory_ts' >= %s order by seq", (mode, f0.isoformat().replace("+00:00", "Z"))):
        d = r["payload"]["data"]
        u = r["topic"].split("/")[3]
        ac.setdefault((u, d["operation"].split(" ")[0]), []).append(float(d.get("cycle_time_s") or 0))
    for k, ps in pc.items():
        a = ac.get(k)
        if not a or len(a) < 2:
            continue
        pm, am = sum(ps) / len(ps), sum(a) / len(a)
        pct = (am - pm) / pm * 100 if pm else 0
        if abs(pct) >= SLOW_PCT:
            out.append({"kind": "slow_op" if pct > 0 else "fast_op", "unit": k[0], "op": k[1], "pct": round(pct, 1),
                        "text": "{} {} 实际单件 {:.0f} 秒，推演 {:.0f} 秒（{:+.0f}%）".format(k[0].upper(), k[1], am, pm, pct)})
    # ③ 期间又出了别的异常
    for a in db.q("select id, title, rule, first_seen from anomaly where mode=%s and id<>%s and rule in ('P1','M1','P5','W1','W2','Q1','Q2','Q3') "
                  "and first_seen > %s and first_seen < coalesce(%s, now()) order by first_seen limit 5",
                  (mode, anomaly["id"], actions[0]["created_at"], now)):
        out.append({"kind": "other_anomaly", "anomaly_id": a["id"], "text": "期间又出了异常 A-{:05d}：{}".format(a["id"], a["title"])})
    # ④ 动作没执行成
    for c in actions:
        if c["status"] == "failed":
            out.append({"kind": "action_failed", "action_id": c["id"], "text": "动作 ACT-{:05d} 执行失败".format(c["id"])})
    return out


def create(db, anomaly_id, force=False, now=None):
    """给一个异常生成复盘（已有就返回已有的）；条件不满足返回 None"""
    init(db)
    a = db.one("select * from anomaly where id=%s", (anomaly_id,))
    if a is None:
        return None
    old = db.one("select id, partial from retro where anomaly_id=%s order by id desc limit 1", (anomaly_id,))
    if old and not (old["partial"] and force):
        return old["id"]
    acts = db.q("select * from action where anomaly_id=%s and status in ('done','failed') order by id", (anomaly_id,))
    acts = [x for x in acts if x["type"] in ACTION_TYPES]
    if not acts:
        return None
    r = build(db, a, acts, now)
    if r["partial"] and not force:
        last = max((x["executed_at"] or x["created_at"]) for x in acts)
        if (now or dt.datetime.now(dt.timezone.utc)) - last < dt.timedelta(days=WAIT_DAYS):
            return None                                   # 等受影响的工单做完
    sc = db.one("insert into scenario (mode, title, snapshot_id, changes, result, created_by, anomaly_id) values (%s,%s,%s,%s,%s,%s,%s) returning id",
                (a["mode"], "复盘：" + r["title"][:120], r["snapshot_id"], Jsonb(r["predicted"]["changes"]),
                 Jsonb({"cost_total": r["predicted"]["cost_total"], "sales_orders": r["predicted"]["sales_orders"]}), "复盘", anomaly_id))
    row = db.one("insert into retro (mode, anomaly_id, action_id, scenario_id, snapshot_id, title, predicted, actual, deviation, counterfactual, causes, partial) "
                 "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                 (a["mode"], anomaly_id, acts[0]["id"], sc["id"], r["snapshot_id"], r["title"], Jsonb(r["predicted"]), Jsonb(r["actual"]),
                  Jsonb(r["deviation"]), Jsonb(r["counterfactual"]), Jsonb(r["causes"]), r["partial"]))
    try:
        from hub.ont.anomaly import Detector
        Detector(db).note(anomaly_id, "system", "retro", "已生成复盘 RT-{:05d}".format(row["id"]))
    except Exception:  # noqa: BLE001
        pass
    return row["id"]


def due(db, mode, now=None):
    """自动复盘：异常已解决、有执行完的动作、还没复盘的 → 试着生成"""
    init(db)
    out = []
    for r in db.q("select distinct a.id from anomaly a join action c on c.anomaly_id=a.id where a.mode=%s and a.status in ('resolved','closed') "
                  "and c.status in ('done','failed') and not exists (select 1 from retro t where t.anomaly_id=a.id) "
                  "and a.closed_at > now() - interval '30 days' limit 20", (mode,)):
        try:
            rid = create(db, r["id"], now=now)
            if rid:
                out.append(rid)
        except Exception:  # noqa: BLE001
            log.exception("自动复盘 A-%05d 出错", r["id"])
    # 之前“未完”的复盘：受影响的工单做完了就重新生成一份完整的
    for r in db.q("select distinct on (anomaly_id) anomaly_id, partial, created_at from retro where mode=%s order by anomaly_id, id desc", (mode,)):
        if not r["partial"] or r["created_at"] > dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10):
            continue
        try:
            a = db.one("select * from anomaly where id=%s", (r["anomaly_id"],))
            acts = [x for x in db.q("select * from action where anomaly_id=%s and status in ('done','failed') order by id", (r["anomaly_id"],))
                    if x["type"] in ACTION_TYPES]
            if a and acts and not build(db, a, acts, now)["partial"]:
                out.append(create(db, r["anomaly_id"], force=True, now=now))
        except Exception:  # noqa: BLE001
            log.exception("更新复盘 A-%05d 出错", r["anomaly_id"])
    return out


def calibration(db, mode):
    """同一台设备、同一工序：最近 3 次复盘都是实际比推演慢 10% 以上 → 提示检查标准工时；停机连续 3 次比推演长 → 提示检查维修时长"""
    init(db)
    rows = db.q("select id, causes from retro where mode=%s order by id desc limit 60", (mode,))
    seen, hints = {}, []
    for r in rows:
        keys = set()
        for c in r["causes"] or []:
            if c.get("kind") == "slow_op":
                keys.add(("slow_op", c["unit"], c["op"]))
            elif c.get("kind") == "downtime" and c.get("minutes", 0) > 0:
                keys.add(("downtime", c["unit"], None))
        for k in keys:
            seen.setdefault(k, []).append(r["id"])
    # 只看“最近 3 次涉及这台设备的复盘”是否都慢
    for (kind, unit, op), ids in seen.items():
        involved = [r["id"] for r in rows if any(c.get("unit") == unit for c in r["causes"] or [])][:3]
        if len(involved) >= 3 and all(i in ids for i in involved):
            hints.append({"kind": kind, "unit": unit, "op": op, "retros": ["RT-{:05d}".format(i) for i in involved],
                          "text": ("{} {}：连续 3 次复盘实际都比推演慢 10% 以上，建议检查标准工时".format(unit.upper(), op) if kind == "slow_op" else
                                   "{}：连续 3 次复盘停机都比推演长，建议检查维修时长的估计".format(unit.upper()))})
    return hints


def row(r):
    return {"id": r["id"], "key": "RT-{:05d}".format(r["id"]), "anomaly_id": r["anomaly_id"], "action_id": r["action_id"], "scenario_id": r["scenario_id"],
            "snapshot_id": r["snapshot_id"], "title": r["title"], "predicted": r["predicted"], "actual": r["actual"], "deviation": r["deviation"],
            "counterfactual": r["counterfactual"], "causes": r["causes"], "partial": r["partial"], "created_at": r["created_at"].isoformat()}
