# -*- coding: utf-8 -*-
"""设备维护：M1 同一设备反复停机"""
import datetime as dt

from hub.ont.anomaly import Finding
from hub.ont.rules import rule


@rule("repeat_down")
def repeat_down(c, p, r):
    since = c.now - dt.timedelta(hours=p["hours"])
    per = {}
    for e in c.db.messages(["machine.event"], since=since, mode=c.mode):
        if e["data"].get("event") in ("alarm", "fault"):
            per.setdefault(e["_topic"].split("/")[3], []).append(e)
    out = []
    for u, evs in per.items():
        if len(evs) >= p["times"]:
            reasons = [e["data"].get("message") or "" for e in evs]
            out.append(Finding(u, "{} {} 小时内停机 {} 次".format(u.upper(), p["hours"], len(evs)), "原因：" + "；".join(reasons),
                               subject=("Machine", u), hint="安排维修人员查根因；考虑预防性维护",
                               evidence=[{"topic": e["_topic"], "id": e["id"], "seq": e["_seq"]} for e in evs[-5:]],
                               values={"times": len(evs), "reasons": reasons}))
    return out
