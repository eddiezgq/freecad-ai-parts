# -*- coding: utf-8 -*-
"""人员与组织（第 18 轮 E4）：H1 单点依赖、H2 排班缺口、H3 资质到期、H4 加班超限、H5 出勤异常。"""

from hub.ont.anomaly import Finding
from hub.ont.rules import rule

BOTTLENECK = ("grd-01",)


def _has(c, t):
    return c.get("has_" + t, lambda: bool(c.db.one("select to_regclass(%s) is not null as ok", (t,))["ok"]))


@rule("single_point")
def single_point(c, p, r):
    from hub import people as PE
    if not _has(c, "roster_post"):
        return []
    out = []
    for x in PE.single_points(c.db, c.mode):
        out.append(Finding(x["unit"], "{} 只有 {} 一个人能独立操作".format(x["unit"].upper(), x["emp_name"]),
                           "技能矩阵里熟练以上只有 1 人：{} 请假这台设备就停，也只能开一个班".format(x["emp_name"]),
                           severity="warn", subject=("Machine", x["unit"]), about=[("Employee", x["emp_id"]), ("Machine", x["unit"])],
                           hint=r.get("hint"), values={"unit": x["unit"], "emp_id": x["emp_id"]}))
    return out


@rule("roster_gap")
def roster_gap(c, p, r):
    from hub import people as PE
    if not _has(c, "roster_post") or not PE.enabled(c.db, c.mode):
        return []
    out = []
    now = PE.factory_now(c.db, c.mode) if c.mode == "teach" else c.now          # 教学模式按工厂时间（车间可能倍速运行）
    for g in PE.gaps(c.db, c.mode, now, hours=float(p.get("hours", 24))):
        k = "{}/{}/{}".format(g["day"], g["shift"], g["unit"])
        out.append(Finding(k, "{} {} {} 没人能开：{}".format(g["day"][5:], g["shift_name"], g["unit"].upper(), g["why"]),
                           "这一班这台设备会停在“缺人”" + ("；它是瓶颈，影响整条线" if g["unit"] in BOTTLENECK else ""),
                           severity="critical" if g["unit"] in BOTTLENECK else "warn", subject=("Machine", g["unit"]),
                           about=[("Machine", g["unit"])] + ([("Employee", g["emp_id"])] if g["emp_id"] else []), hint=r.get("hint"),
                           values={"unit": g["unit"], "day": g["day"], "shift": g["shift"], "emp_id": g["emp_id"], "why": g["why"]}))
    return out


@rule("skill_expiring")
def skill_expiring(c, p, r):
    from hub import kpi
    if not _has(c, "skill"):
        return []
    d0 = c.now.astimezone(kpi.TZ).date()
    names = {x["id"]: x["name"] for x in c.db.q("select id, name from ehs_person where mode=%s", (c.mode,))}
    out = []
    for x in c.db.q("select * from skill where mode=%s and valid_until is not null order by emp_id, unit", (c.mode,)):
        left = (x["valid_until"] - d0).days
        if left > int(p.get("days", 30)):
            continue
        k = "{}/{}".format(x["emp_id"], x["unit"])
        out.append(Finding(k, "{} 的 {} 操作资质 {}".format(names.get(x["emp_id"], x["emp_id"]), x["unit"].upper(),
                                                       "已过期 {} 天".format(-left) if left < 0 else "{} 天后到期".format(left)),
                           "到期 {}；过期后按学徒排班（60% 速度）".format(x["valid_until"]), severity="warn" if left < 0 else "info",
                           subject=("Employee", x["emp_id"]), about=[("Employee", x["emp_id"]), ("Machine", x["unit"])], hint=r.get("hint"),
                           values={"emp_id": x["emp_id"], "unit": x["unit"], "days_left": left}))
    return out


@rule("overtime_over")
def overtime_over(c, p, r):
    from hub import kpi
    from hub import people as PE
    if not _has(c, "overtime_log"):
        return []
    d0 = c.now.astimezone(kpi.TZ).date()
    names = {x["id"]: x["name"] for x in c.db.q("select id, name from ehs_person where mode=%s", (c.mode,))}
    out = []
    for e, h in sorted(PE.overtime_week(c.db, c.mode, d0).items()):
        if h <= float(p.get("hours", 12)):
            continue
        out.append(Finding("{}/{}".format(e, PE.week_days(d0)[0].isoformat()), "{} 本周加班 {:g} 小时（上限 {:g}）".format(names.get(e, e), h, float(p.get("hours", 12))),
                           "下一次加班换人", severity="warn", subject=("Employee", e), hint=r.get("hint"), values={"emp_id": e, "hours": h}))
    return out


@rule("absence_high")
def absence_high(c, p, r):
    from hub import people as PE
    if not _has(c, "attendance"):
        return []
    out = []
    for t, x in sorted(PE.absence_rate(c.db, c.mode, int(p.get("days", 7))).items()):
        if x["scheduled"] < int(p.get("min_scheduled", 10)) or x["rate"] <= float(p.get("rate", 0.1)):
            continue
        out.append(Finding(t, "{} 近 {} 天缺勤率 {:.0%}".format(t, int(p.get("days", 7)), x["rate"]),
                           "排班 {} 人次，请假或缺勤 {} 人次".format(x["scheduled"], x["missed"]), severity="warn", subject=("Department", t),
                           hint=r.get("hint"), values={"team": t, "rate": x["rate"], "missed": x["missed"], "scheduled": x["scheduled"]}))
    return out
