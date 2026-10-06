# -*- coding: utf-8 -*-
"""本体 API（第 17 轮 A 期 A9）：本体定义、搜索、对象、关系图、时间线、对象集查询、血缘、同步状态。

权限（A14）：敏感级别 0 公开、1 内部、2 部门、3 受限。老师（教学）可看 3；生产模式的厂长、审批人可看 2；其他人看到 1。
超过级别的对象类型整个看不到，超过级别的属性不返回。"""
from fastapi import Body, Depends, HTTPException

from hub.ont import schema as S

MAX_NODES = 150


def level(u):
    if u.get("teacher") and u.get("mode") == "teach":
        return 3
    if u.get("teacher") or u.get("role") in ("manager", "approver"):
        return 2
    return 1


def filter_chain(ch, lv):
    """链条按敏感级别过滤：看不到的节点换成“原因待查”（不暴露类型和编号），边保留"""
    onto = S.get()
    if not ch:
        return ch
    nodes = []
    for n in ch.get("nodes", []):
        t = n["type"]
        if t in onto.types and int(onto.types[t].get("sensitivity", 0) or 0) > lv:
            nodes.append({"id": n["id"], "type": "Hidden", "key": "", "display": "原因待查", "label": "原因待查", "domain": n["domain"],
                          "role": n["role"], "values": {}, "hidden": True})
        else:
            nodes.append(n)
    hidden = {n["id"] for n in nodes if n.get("hidden")}
    edges = [dict(e, basis={"how": "需要更高权限才能看到依据"} if (e["from"] in hidden or e["to"] in hidden) else e["basis"])
             for e in ch.get("edges", [])]
    summary = [x for x in ch.get("summary", []) if not hidden or "情景" not in x]
    return dict(ch, nodes=nodes, edges=edges, summary=summary)


def mount(app, H, user_of):
    onto = S.get()

    def sens_type(t):
        return int(onto.types[t].get("sensitivity", 0) or 0)

    def visible(u, t):
        return t in onto.types and sens_type(t) <= level(u)

    def clean_props(u, t, props):
        lv, spec = level(u), onto.types[t]
        out = {}
        for p, v in (props or {}).items():
            ps = spec["props"].get(p)
            if ps is None or int(ps.get("s", spec.get("sensitivity", 0)) or 0) > lv:
                continue
            out[p] = v
        return out

    def node(u, r):
        t = r["type"]
        sp = onto.types[t]
        return {"id": t + "|" + r["key"], "type": t, "key": r["key"], "display": r["display"], "domain": sp["domain"],
                "label": sp["label"]}

    @app.get("/api/ont/types")
    def ont_types(u=Depends(user_of)):
        counts = {r["type"]: r["n"] for r in H.db.q("select type, count(*) as n from ont_object where mode=%s group by type", (u["mode"],))}
        recent = {r["type"]: r["n"] for r in H.db.q(
            "select type, count(*) as n from ont_event where mode=%s and ts > now() - interval '1 day' group by type", (u["mode"],))}
        doms = onto.public()
        for d in doms:
            d["types"] = [dict(t, count=counts.get(t["name"], 0), changes_24h=recent.get(t["name"], 0), hidden=not visible(u, t["name"]))
                          for t in d["types"]]
            d["count"] = sum(t["count"] for t in d["types"] if not t["hidden"])
            d["with_data"] = sum(1 for t in d["types"] if t["count"])
        return {"domains": doms, "maturity": S.MATURITY, "level": level(u)}

    @app.get("/api/ont/search")
    def ont_search(q: str = "", type: str = "", limit: int = 30, u=Depends(user_of)):
        q = q.strip()
        if not q:
            return {"results": []}
        limit = max(1, min(int(limit), 100))
        types = [t for t in onto.types if visible(u, t) and (not type or t == type)]
        hits, seen = [], set()

        def add(rows, how):
            for r in rows:
                k = (r["type"], r["key"])
                if k in seen or r["type"] not in types:
                    continue
                seen.add(k)
                hits.append(dict(node(u, r), how=how))
        add(H.db.q("select o.type, o.key, o.display from ont_alias a join ont_object o on o.mode=a.mode and o.type=a.type and o.key=a.key "
                   "where a.mode=%s and lower(a.alias)=lower(%s) limit 10", (u["mode"], q)), "别名")
        add(H.db.q("select type, key, display from ont_object where mode=%s and lower(key)=lower(%s) and type = any(%s) limit 10",
                   (u["mode"], q, types)), "编号")
        like = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
        add(H.db.q("select type, key, display from ont_object where mode=%s and type = any(%s) and search ilike %s "
                   "order by length(key), key limit %s", (u["mode"], types, like, limit)), "包含")
        # 前面都没找到才做“相近”匹配（容错拼写），它在几十万对象时要零点几秒
        if not hits and H.ont is not None and getattr(H.ont.store, "trgm", False) and len(q) >= 3:
            add(H.db.q("select type, key, display from ont_object where mode=%s and type = any(%s) and search %% %s "
                       "order by similarity(search, %s) desc limit %s", (u["mode"], types, q, q, limit)), "相近")
        return {"results": hits[:limit]}

    def get_obj(u, t, key):
        if not visible(u, t):
            raise HTTPException(404, "没有这类对象，或你没有权限查看")
        r = H.db.one("select * from ont_object where mode=%s and type=%s and key=%s", (u["mode"], t, key))
        if r is None:
            raise HTTPException(404, "没有这个对象：{} {}".format(onto.types[t]["label"], key))
        return r

    @app.get("/api/ont/obj/{t}/{key:path}/graph")
    def ont_graph(t: str, key: str, depth: int = 1, u=Depends(user_of)):
        get_obj(u, t, key)
        depth = max(1, min(int(depth), 3))
        nodes, edges = {}, {}
        frontier = [(t, key)]
        start = H.db.one("select type, key, display from ont_object where mode=%s and type=%s and key=%s", (u["mode"], t, key))
        nodes[t + "|" + key] = dict(node(u, start), root=True, hop=0)
        for hop in range(1, depth + 1):
            nxt = []
            for ft, fk in frontier:
                rows = H.db.q("select * from ont_link where mode=%s and ((src_type=%s and src_key=%s) or (dst_type=%s and dst_key=%s)) limit 400",
                              (u["mode"], ft, fk, ft, fk))
                for lr in rows:
                    other = (lr["dst_type"], lr["dst_key"]) if (lr["src_type"], lr["src_key"]) == (ft, fk) else (lr["src_type"], lr["src_key"])
                    if not visible(u, other[0]):
                        continue
                    oid = other[0] + "|" + other[1]
                    if oid not in nodes:
                        if len(nodes) >= MAX_NODES:
                            continue
                        o = H.db.one("select type, key, display from ont_object where mode=%s and type=%s and key=%s",
                                     (u["mode"], other[0], other[1]))
                        nodes[oid] = dict(node(u, o) if o else {"id": oid, "type": other[0], "key": other[1], "display": other[1],
                                                                 "domain": onto.types[other[0]]["domain"], "label": onto.types[other[0]]["label"],
                                                                 "missing": True}, hop=hop)
                        nxt.append(other)
                    ls = onto.links[(lr["src_type"], lr["type"].split(".", 1)[1])]  # 通用链接也在这里
                    eid = "{}>{}>{}".format(lr["type"], lr["src_type"] + "|" + lr["src_key"], lr["dst_type"] + "|" + lr["dst_key"])
                    edges[eid] = {"id": eid, "from": lr["src_type"] + "|" + lr["src_key"], "to": lr["dst_type"] + "|" + lr["dst_key"],
                                  "type": lr["type"], "label": ls["l"], "inverse": ls.get("inv", ""), "props": lr["props"], "seq": lr["src_seq"]}
            frontier = nxt
        return {"nodes": list(nodes.values()), "edges": [e for e in edges.values() if e["from"] in nodes and e["to"] in nodes],
                "truncated": len(nodes) >= MAX_NODES}

    @app.get("/api/ont/obj/{t}/{key:path}/timeline")
    def ont_timeline(t: str, key: str, limit: int = 300, u=Depends(user_of)):
        get_obj(u, t, key)
        rows = H.db.q("select ts, kind, text, changes, src_seq from ont_event where mode=%s and type=%s and key=%s order by ts desc, id desc limit %s",
                      (u["mode"], t, key, max(1, min(int(limit), 1000))))
        props = onto.types[t]["props"]
        out = []
        for r in rows:
            ch = clean_props(u, t, {k: v for k, v in (r["changes"] or {}).items()})
            out.append({"ts": r["ts"].isoformat(), "kind": r["kind"], "text": r["text"],
                        "changes": [{"prop": k, "label": props[k]["l"], "unit": props[k].get("u", ""), "old": v[0], "new": v[1]}
                                    for k, v in ch.items() if k in props],
                        "seq": r["src_seq"]})
        return {"events": out}

    @app.get("/api/ont/obj/{t}/{key:path}")
    def ont_obj(t: str, key: str, u=Depends(user_of)):
        r = get_obj(u, t, key)
        spec = onto.types[t]
        props = clean_props(u, t, r["props"])
        attrs = [{"name": p, "label": ps["l"], "type": ps["t"], "unit": ps.get("u", ""), "value": props.get(p),
                  "source": r["prop_src"].get(p)} for p, ps in spec["props"].items() if p in props]
        groups = []
        for (ft, ln), ls in onto.links.items():
            out_ = ft == t
            in_ = ls["to"] in (t, S.ANY)
            for direction in (["out"] if out_ else []) + (["in"] if in_ else []):
                if direction == "out":
                    rows = H.db.q("select l.dst_type as t, l.dst_key as k, l.props, l.src_seq, o.display from ont_link l left join ont_object o on "
                                  "o.mode=l.mode and o.type=l.dst_type and o.key=l.dst_key where l.mode=%s and l.type=%s and l.src_key=%s "
                                  "order by l.ts desc nulls last limit 51", (u["mode"], ft + "." + ln, key))
                    label = ls["l"]
                else:
                    rows = H.db.q("select l.src_type as t, l.src_key as k, l.props, l.src_seq, o.display from ont_link l left join ont_object o on "
                                  "o.mode=l.mode and o.type=l.src_type and o.key=l.src_key where l.mode=%s and l.type=%s and l.dst_type=%s "
                                  "and l.dst_key=%s order by l.ts desc nulls last limit 51", (u["mode"], ft + "." + ln, t, key))
                    label = ls.get("inv") or ls["l"]
                by_type = {}
                for x in rows[:50]:
                    if visible(u, x["t"]):
                        by_type.setdefault(x["t"], []).append(x)
                for other, xs in by_type.items():
                    groups.append({"link": ft + "." + ln, "direction": direction, "label": label, "type": other,
                                   "type_label": onto.types[other]["label"], "more": len(rows) > 50,
                                   "items": [{"key": x["k"], "display": x["display"] or x["k"], "props": x["props"], "seq": x["src_seq"]}
                                             for x in xs]})
        aliases = [a["alias"] for a in H.db.q("select alias from ont_alias where mode=%s and type=%s and key=%s", (u["mode"], t, key))]
        return {"type": t, "key": key, "display": r["display"], "label": spec["label"], "label_en": spec.get("label_en", ""),
                "domain": spec["domain"], "maturity": spec["maturity"], "attrs": attrs, "links": groups, "aliases": aliases,
                "first_seq": r["first_seq"], "first_ts": r["first_ts"].isoformat() if r["first_ts"] else None,
                "updated_at": r["updated_at"].isoformat(), "sources": spec.get("sources", [])}

    @app.post("/api/ont/query")
    def ont_query(body: dict = Body(...), u=Depends(user_of)):
        """对象集：{type, where: [{prop, op(= != > < >= <= contains), value}], link: {name, key, direction}, limit}"""
        t = body.get("type")
        if not visible(u, t):
            raise HTTPException(404, "没有这类对象，或你没有权限查看")
        spec = onto.types[t]
        where, args = ["o.mode=%s", "o.type=%s"], [u["mode"], t]
        ops = {"=": "=", "!=": "<>", ">": ">", "<": "<", ">=": ">=", "<=": "<="}
        for w in body.get("where") or []:
            p, op, v = w.get("prop"), w.get("op", "="), w.get("value")
            if p not in spec["props"]:
                raise HTTPException(400, "{} 没有属性 {}".format(spec["label"], p))
            num = spec["props"][p]["t"] in ("num", "int")
            if op == "contains":
                where.append("o.props->>%s ilike %s")
                args += [p, "%" + str(v) + "%"]
            elif op in ops:
                where.append("({} {} %s)".format("(o.props->>%s)::float" if num else "o.props->>%s", ops[op]))
                args += [p, float(v) if num else str(v)]
            else:
                raise HTTPException(400, "不支持的条件 " + str(op))
        lk = body.get("link")
        if lk:
            ft, ln = (lk["name"].split(".", 1) + [""])[:2]
            if (ft, ln) not in onto.links:
                raise HTTPException(400, "没有链接 " + lk["name"])
            if lk.get("direction", "out") == "out":
                where.append("exists (select 1 from ont_link l where l.mode=o.mode and l.type=%s and l.src_key=o.key and l.dst_key=%s)")
            else:
                where.append("exists (select 1 from ont_link l where l.mode=o.mode and l.type=%s and l.dst_key=o.key and l.src_key=%s)")
            args += [lk["name"], lk["key"]]
        limit = max(1, min(int(body.get("limit", 500)), 5000))
        rows = H.db.q("select o.type, o.key, o.display, o.props from ont_object o where {} order by o.key limit %s".format(" and ".join(where)),
                      args + [limit])
        return {"type": t, "count": len(rows), "objects": [dict(node(u, r), props=clean_props(u, t, r["props"])) for r in rows]}

    @app.get("/api/ont/lineage/{seq}")
    def ont_lineage(seq: int, u=Depends(user_of)):
        r = H.db.one("select seq, ts, topic, type, mode, corr, payload from bus_message where seq=%s", (seq,))
        if r is None:
            raise HTTPException(404, "这条原始消息已经不在历史库里（可能已按保留天数清理）")
        if (r["mode"] or "teach") != u["mode"]:
            raise HTTPException(404, "不是当前模式的消息")
        return {"seq": r["seq"], "ts": r["ts"].isoformat(), "topic": r["topic"], "type": r["type"], "corr": r["corr"],
                "source": r["payload"].get("source"), "data": r["payload"].get("data")}

    @app.get("/api/ont/health")
    def ont_health(u=Depends(user_of)):
        return H.ont.health()

    @app.post("/api/ont/replay")
    def ont_replay(u=Depends(user_of)):
        if not (u.get("teacher") and u.get("role") == "manager"):
            raise HTTPException(403, "只有厂长（教师）可以重建本体")
        n = H.ont.replay(u["mode"])
        return dict(H.ont.health(), replayed=n)


# ================================================================== 第 17 轮 B 期：异常、追因、态势、规则
def mount_anomaly(app, H, user_of, who):
    import datetime as dt

    from hub.ont import anomaly as A
    from hub.ont import chain as CH
    from hub.ont import narrate as NR
    from hub.ont import situation as SIT
    onto = S.get()

    def D():
        d = H.ai.detector()
        d.init()
        return d

    def seen(u, a):
        t = a.get("subject_type")
        return not t or t not in onto.types or int(onto.types[t].get("sensitivity", 0) or 0) <= level(u)

    def row(a, cat):
        r = cat.get(a["rule"], {})
        return {"id": a["id"], "key": "A-{:05d}".format(a["id"]), "rule": a["rule"], "rule_name": r.get("name"), "domain": a["domain"],
                "domain_label": next((d["label"] for d in onto.domains if d["domain"] == a["domain"]), a["domain"]),
                "subject": {"type": a["subject_type"], "key": a["subject_key"]} if a["subject_type"] else None,
                "severity": a["severity"], "severity_label": A.LEVEL_LABEL[a["severity"]], "status": a["status"],
                "status_label": A.STATUS_LABEL[a["status"]], "role": a["role"], "title": a["title"],
                "text": (a["detail"] or {}).get("text"), "first_seen": a["first_seen"].isoformat(), "last_seen": a["last_seen"].isoformat(),
                "hits": a["hits"], "assignee": a["assignee"], "closed_reason": a["closed_reason"], "reopened": a["reopened"]}

    def can_act(u, a):
        r = D().catalog.get(a["rule"], {})
        return bool(u.get("teacher")) or u.get("role") == "manager" or u.get("role") in (r.get("role") or []) or u.get("role") == a["role"]

    @app.get("/api/ont/anomalies")
    def anomalies(status: str = "open", domain: str = "", role: str = "", limit: int = 300, u=Depends(user_of)):
        d = D()
        w, args = ["mode=%s"], [u["mode"]]
        if status == "open":
            w.append("status in ('open','ack','doing')")
        elif status == "closed":
            w.append("status in ('resolved','closed')")
        if domain:
            w.append("domain=%s")
            args.append(domain)
        if role:
            w.append("role=%s")
            args.append(role)
        rows = H.db.q("select * from anomaly where {} order by case severity when 'critical' then 0 when 'warn' then 1 else 2 end, "
                      "last_seen desc limit %s".format(" and ".join(w)), args + [max(1, min(int(limit), 1000))])
        return {"anomalies": [row(a, d.catalog) for a in rows if seen(u, a)],
                "last_round": d.last_round.get(u["mode"]), "levels": A.LEVEL_LABEL, "statuses": A.STATUS_LABEL}

    def get_a(u, aid):
        a = H.db.one("select * from anomaly where id=%s and mode=%s", (aid, u["mode"]))
        if a is None or not seen(u, a):
            raise HTTPException(404, "没有这个异常")
        return a

    @app.get("/api/ont/anomalies/{aid}")
    def anomaly(aid: int, u=Depends(user_of)):
        d = D()
        a = get_a(u, aid)
        if a["status"] in A.OPEN:
            stale = not a["chain"] or dt.datetime.fromisoformat(a["chain"]["computed_at"]) < dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=60)
            if stale:
                d.refresh_chains(u["mode"], A.Ctx(H.db, u["mode"]), every_s=60, ids=[aid])
                a = get_a(u, aid)
        r = d.catalog.get(a["rule"], {})
        det = a["detail"] or {}
        return dict(row(a, d.catalog), chain=filter_chain(a["chain"], level(u)), evidence=det.get("evidence") or [],
                    hint=det.get("hint"), values=det.get("values") or {},
                    rule_info={"id": a["rule"], "name": r.get("name"), "desc": r.get("desc"), "params": d.rule(a["rule"])["params"] if a["rule"] in d.catalog else {}},
                    notes=[{"ts": n["ts"].isoformat(), "who": n["who"], "kind": n["kind"], "text": n["text"]} for n in d.notes(aid)],
                    can_act=can_act(u, a), text_rules=NR.rules_text(a, filter_chain(a["chain"], level(u))))

    @app.post("/api/ont/anomalies/{aid}/{kind}")
    def anomaly_act(aid: int, kind: str, body: dict = Body(default={}), u=Depends(user_of)):
        d = D()
        a = get_a(u, aid)
        if kind == "narrate":
            return NR.narrate(H.ai.llm, a, filter_chain(a["chain"], level(u)))
        if kind not in ("ack", "doing", "assign", "note", "close"):
            raise HTTPException(404, "没有这个操作")
        if kind != "note" and not can_act(u, a):
            raise HTTPException(403, "这个异常由{}负责；你可以写备注".format(a["role"]))
        try:
            d.act(aid, who(u), kind, body.get("text", ""), body.get("role"))
        except A.RuleError as e:
            raise HTTPException(400, str(e))
        return anomaly(aid, u)

    @app.get("/api/ont/impact/{t}/{key:path}")
    def impact(t: str, key: str, u=Depends(user_of)):
        if t not in onto.types or int(onto.types[t].get("sensitivity", 0) or 0) > level(u):
            raise HTTPException(404, "没有这类对象，或你没有权限查看")
        return filter_chain(CH.for_object(A.Ctx(H.db, u["mode"]), t, key), level(u))

    @app.get("/api/ont/situation")
    def situation(u=Depends(user_of)):
        return SIT.cards(H.db, D(), u["mode"])

    @app.get("/api/ont/rules")
    def rules(u=Depends(user_of)):
        d = D()
        out = []
        counts = {r["rule"]: r for r in H.db.q("select rule, count(*) as n, max(first_seen) as last, "
                                               "sum(case when status in ('open','ack','doing') then 1 else 0 end) as open "
                                               "from anomaly where mode=%s group by rule", (u["mode"],))}
        for rid, base in d.catalog.items():
            r = d.rule(rid)
            st = d.stats.get(rid, {})
            c = counts.get(rid) or {}
            out.append({"id": rid, "name": base["name"], "domain": base["domain"],
                        "domain_label": next((x["label"] for x in onto.domains if x["domain"] == base["domain"]), base["domain"]),
                        "severity": base["severity"], "role": base["role"], "enabled": r["enabled"], "waiting": base["waiting"],
                        "params": r["params"], "defaults": base["params"], "desc": base.get("desc"), "hint": base.get("hint"),
                        "fired": c.get("n", 0), "open": c.get("open", 0), "last_fired": c["last"].isoformat() if c.get("last") else None,
                        "error": st.get("error"), "ms": st.get("ms"), "nodata": st.get("nodata", False)})
        changes = [{"ts": x["ts"].isoformat(), "who": x["who"], "rule": x["rule"], "field": x["field"], "old": x["old"], "new": x["new"]}
                   for x in H.db.q("select * from rule_change order by id desc limit 50")]
        try:
            from hub.ont import retro as RT                 # 第 17 轮 D 期：复盘的校准提示
            calib = RT.calibration(H.db, u["mode"])
        except Exception:  # noqa: BLE001
            calib = []
        return {"rules": out, "changes": changes, "can_edit": bool(u.get("teacher")) and u.get("role") == "manager",
                "last_round": d.last_round.get(u["mode"]), "calibration": calib}

    @app.post("/api/ont/rules/{rid}")
    def rule_set(rid: str, body: dict = Body(default={}), u=Depends(user_of)):
        if not (u.get("teacher") and u.get("role") == "manager"):
            raise HTTPException(403, "只有厂长（教师）可以调整规则")
        try:
            D().set_rule(rid, who(u), body.get("enabled"), body.get("params"))
        except KeyError:
            raise HTTPException(404, "没有这条规则")
        except (A.RuleError, ValueError, TypeError) as e:
            raise HTTPException(400, str(e))
        return rules(u)

    @app.post("/api/ont/rules/{rid}/backtest")
    def backtest(rid: str, body: dict = Body(default={}), u=Depends(user_of)):
        """用历史检验：过去 days 天，每 step_h 小时按当时的数据跑一次（只算，不开异常）"""
        d = D()
        if rid not in d.catalog or d.catalog[rid]["waiting"]:
            raise HTTPException(404, "没有这条规则，或它还没有数据")
        days, step = max(1, min(int(body.get("days", 7)), 14)), max(1, int(body.get("step_h", 6)))
        now = dt.datetime.now(dt.timezone.utc)
        try:
            params = d.cast_params(rid, body.get("params") or {})
        except (A.RuleError, ValueError) as e:
            raise HTTPException(400, str(e))
        out = []
        t = now - dt.timedelta(days=days)
        while t <= now:
            found, _ = d.detect(u["mode"], t, only={rid}, params={rid: params} if params else None)
            fs = found.get(rid) or []
            out.append({"at": t.isoformat(), "count": len(fs), "items": [{"key": f.fkey, "title": f.title, "severity": f.severity} for f in fs[:10]],
                        "error": d.stats.get(rid, {}).get("error") if found.get(rid) is None else None})
            t += dt.timedelta(hours=step)
        return {"rule": rid, "points": out, "total": sum(p["count"] for p in out),
                "note": "按每个时刻已入库的数据重算。读“当前状态”的规则（停机、库存、订单预测）回看过去时只能用当时最近一次的状态消息，结果是近似。"}
