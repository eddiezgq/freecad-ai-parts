# -*- coding: utf-8 -*-
"""安全、健康与环境（第 18 轮 E2）：E1 重大隐患未关闭、E2 整改逾期、E3 许可缺资质、E4 培训到期、E5 挂锁期间设备运转、
E6 化学品存量、E7 危废暂存超期"""
import datetime as dt

from hub.ont.anomaly import Finding
from hub.ont.rules import rule


def _has(c, t):
    return c.get("has_" + t, lambda: bool(c.db.one("select to_regclass(%s) is not null as ok", (t,))["ok"]))


def _today(c):
    from hub import kpi
    return c.now.astimezone(kpi.TZ).date()


def _issues(c):
    if not _has(c, "safety_issue"):
        return []
    return c.get("open_safety_issues", lambda: c.db.q("select * from safety_issue where mode=%s and status<>'closed' order by id", (c.mode,)))


def _key(i):
    return "SI-{:05d}".format(i)


@rule("major_issue_open")
def major_issue_open(c, p, r):
    out = []
    for x in _issues(c):
        if x["level"] != "major":
            continue
        k = _key(x["id"])
        subj = ("Machine", x["unit"]) if x["unit"] else ("SafetyIssue", k)
        out.append(Finding(k, "重大隐患 {}：{}".format(k, x["subject"]),
                           "{}（{}）；发现人 {}；整改期限 {}".format(x["subject"], x["area"] or "—", x["found_by"] or "—", x["due_day"] or "—"),
                           severity="critical", subject=subj, about=[("SafetyIssue", k)] + ([("Machine", x["unit"])] if x["unit"] else []),
                           evidence=[{"table": "safety_issue", "id": x["id"]}], hint=r.get("hint"),
                           values={"issue_id": x["id"], "unit": x["unit"], "subject": x["subject"], "fix_minutes": x["fix_minutes"],
                                   "status": x["status"], "kind": x["kind"]}))
    return out


@rule("issue_overdue")
def issue_overdue(c, p, r):
    d0 = _today(c)
    out = []
    for x in _issues(c):
        if x["status"] in ("fixed", "closed") or not x["due_day"] or x["due_day"] >= d0:
            continue
        k = _key(x["id"])
        out.append(Finding(k, "隐患 {} 整改逾期 {} 天：{}".format(k, (d0 - x["due_day"]).days, x["subject"]),
                           "整改人 {}；期限 {}".format(x["owner"] or "没指派", x["due_day"]), subject=("SafetyIssue", k),
                           about=[("SafetyIssue", k)] + ([("Machine", x["unit"])] if x["unit"] else []), hint=r.get("hint"),
                           values={"issue_id": x["id"], "days": (d0 - x["due_day"]).days, "owner": x["owner"]}))
    return out


@rule("permit_unqualified")
def permit_unqualified(c, p, r):
    if not _has(c, "work_permit"):
        return []
    from hub import ehs as EH
    out = []
    for x in c.db.q("select * from work_permit where mode=%s and status in ('blocked','requested') order by id", (c.mode,)):
        ok, why = EH.qualified(c.db, c.mode, x["holder_id"], x["kind"], _today(c))
        if ok:
            continue
        k = "PTW-{:05d}".format(x["id"])
        out.append(Finding(k, "作业许可 {}（{}）缺资质：{}".format(k, EH.PERMITS[x["kind"]], why),
                           "设备 {}；申请人 {}".format((x["unit"] or "—").upper(), x["requested_by"] or "—"), severity="critical", subject=("WorkPermit", k),
                           about=[("WorkPermit", k)] + ([("Machine", x["unit"])] if x["unit"] else []), hint=r.get("hint"),
                           values={"permit_id": x["id"], "kind": x["kind"], "holder_id": x["holder_id"], "why": why}))
    return out


@rule("training_due")
def training_due(c, p, r):
    if not _has(c, "ehs_training"):
        return []
    from hub import ehs as EH
    names = {x["id"]: x["name"] for x in c.db.q("select id, name from ehs_person where mode=%s and active", (c.mode,))}
    out = []
    for t in EH.trainings(c.db, c.mode, _today(c)):
        if t["person_id"] not in names or t["days_left"] > int(p["days"]):
            continue
        k = "{}:{}".format(t["person_id"], t["kind"])
        late = t["days_left"] < 0
        out.append(Finding(k, "{}的“{}”培训{}".format(names[t["person_id"]], t["label"],
                                                  "已过期 {} 天".format(-t["days_left"]) if late else "还有 {} 天到期".format(t["days_left"])),
                           "有效期到 {}".format(t["valid_until"]), severity="warn" if late else "info", subject=("SafetyTraining", k),
                           hint=r.get("hint"), values={"person_id": t["person_id"], "kind": t["kind"], "days_left": t["days_left"]}))
    return out


@rule("lockout_violation")
def lockout_violation(c, p, r):
    if not _has(c, "work_permit"):
        return []
    machines = {m["unit"]: m for m in c.ov["machines"]}
    out = []
    for x in c.db.q("select * from work_permit where mode=%s and kind='loto' and status='active' and valid_from < now() - interval '30 seconds'",
                    (c.mode,)):
        m = machines.get(x["unit"]) or {}
        if m.get("state") not in ("run", "setup") or m.get("locked"):
            continue
        k = "PTW-{:05d}".format(x["id"])
        out.append(Finding(k, "{} 挂牌上锁期间在运转（许可 {} 还开着）".format(x["unit"].upper(), k),
                           "设备状态 {}；可能有人没走许可就拆了锁".format(m.get("state")), severity="critical", subject=("Machine", x["unit"]),
                           about=[("WorkPermit", k), ("Machine", x["unit"])], hint=r.get("hint"), values={"permit_id": x["id"], "unit": x["unit"]}))
    return out


@rule("chemical_stock")
def chemical_stock(c, p, r):
    if not _has(c, "chemical"):
        return []
    out = []
    for x in c.db.q("select * from chemical where mode=%s order by code", (c.mode,)):
        s, lo, hi = float(x["stock_kg"]), float(x["min_kg"]), float(x["max_kg"])
        if lo <= s <= hi:
            continue
        low = s < lo
        out.append(Finding(x["code"], "{} {}：{:.0f} kg（{} {:.0f} kg）".format(x["name"], "低于安全库存" if low else "超过现场限额", s,
                                                                         "安全库存" if low else "限额", lo if low else hi),
                           x["sds"] or "", subject=("Chemical", x["code"]), hint=r.get("hint"), values={"stock_kg": s, "min_kg": lo, "max_kg": hi}))
    return out


@rule("waste_overdue")
def waste_overdue(c, p, r):
    if not _has(c, "waste"):
        return []
    from hub import ehs as EH
    d0 = _today(c)
    out = []
    for x in c.db.q("select * from waste where mode=%s and hazardous and disposed_day is null order by id", (c.mode,)):
        age = (d0 - x["produced_day"]).days
        if age <= int(p["days"]):
            continue
        k = "W-{:05d}".format(x["id"])
        out.append(Finding(k, "危险废物 {}（{:g} kg）暂存 {} 天，超过 {} 天".format(EH.WASTES.get(x["kind"], (x["kind"],))[0], float(x["qty_kg"]), age, p["days"]),
                           "产生日期 {}".format(x["produced_day"]), subject=("Waste", k), hint=r.get("hint"), values={"age_days": age, "waste_id": x["id"]}))
    return out


_ = dt
