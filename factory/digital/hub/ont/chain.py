# -*- coding: utf-8 -*-
"""追因与影响面（第 17 轮 B 期 B7、B8）：从异常（或任何对象）出发，沿本体链接往上游找原因、往下游算影响。

每条边写明依据：本体链接（含来源消息序号）、规则、或已有的计算（看板订单预测、MRP、成本模块、孪生）。
量化只用已有计算，不另写估算。走图最多 8 跳，最多 200 个节点。

6 条种子链路（digital/ontology/rules/chains.yaml 有说明）：
  down    设备停机 → 工序任务 → 工单 → 销售订单 → 客户
  quality 质量信号 → 零件 → 加工记录 → 刀具 / 设备（上游）；→ 同一刀具的其他零件（复检范围）
  field   现场设备报警 → 总成 → 输出轴 → 砂轮 → 同砂轮的轴 → 它们的现场设备 → 客户（排查范围）
  stock   缺料 → 物料 → 用到它的工单 → 销售订单 → 客户
  cost    成本差异 → 工序 → 调整、换刀、超时（差异分解）
  late    订单延期风险 → 工单 → 未完工序 → 设备状态（为什么会晚）
  money   （第 19 轮）应收逾期 / 毛利低 → 订单 → 记到订单上的动作费用 → 动作来自哪个异常（跨领域）"""
import datetime as dt

from hub.ont import schema as S

MAX_NODES = 200
ANCHOR = "@anomaly"           # 链条起点（异常本身）的占位，for_anomaly 换成真正的异常节点
GRIND = {"bearing_seat_d35": "grd-01", "bearing_seat_d35_r": "grd-01", "gear_seat_d40": "grd-01", "runout_bearing": "grd-01",
         "keyway_width_12": "key-01", "keyway_sym": "key-01"}


class Chain:
    def __init__(self, c, kind):
        self.c, self.db, self.mode = c, c.db, c.mode
        self.onto = S.get()
        self.kind = kind
        self.nodes, self.edges, self.summary, self.scope = {}, [], [], {}
        self.truncated = False

    # ---- 节点与边
    def node(self, type_, key, role="impact", values=None, display=None):
        if type_ is None or key is None:
            return None
        nid = "{}|{}".format(type_, key)
        if nid in self.nodes:
            n = self.nodes[nid]
            if values:
                n["values"].update(values)
            if role == "cause" and n["role"] == "impact":
                n["role"] = "cause"
            return nid
        if len(self.nodes) >= MAX_NODES:
            self.truncated = True
            return None
        if display is None and type_ in self.onto.types:
            r = self.db.one("select display from ont_object where mode=%s and type=%s and key=%s", (self.mode, type_, str(key)))
            display = r["display"] if r else str(key)
        spec = self.onto.types.get(type_, {})
        self.nodes[nid] = {"id": nid, "type": type_, "key": str(key), "display": display or str(key), "label": spec.get("label", type_),
                           "domain": spec.get("domain", "core"), "role": role, "values": dict(values or {})}
        return nid

    def edge(self, a, b, label, how, seq=None, text=None, values=None):
        if a and b:
            self.edges.append({"from": a, "to": b, "label": label, "basis": {"how": how, "seq": seq, "text": text}, "values": values or {}})

    def links(self, ltype, src=None, dst=None, extra="", args=()):
        w, a = ["mode=%s", "type=%s"], [self.mode, ltype]
        if src is not None:
            w.append("src_key=%s")
            a.append(str(src))
        if dst is not None:
            w.append("dst_key=%s")
            a.append(str(dst))
        return self.db.q("select * from ont_link where {} {} order by ts nulls last limit 300".format(" and ".join(w), extra), a + list(args))

    def obj(self, type_, key):
        r = self.db.one("select props from ont_object where mode=%s and type=%s and key=%s", (self.mode, type_, str(key)))
        return r["props"] if r else None

    def out(self):
        return {"kind": self.kind, "nodes": list(self.nodes.values()), "edges": self.edges, "summary": self.summary, "scope": self.scope,
                "truncated": self.truncated, "computed_at": dt.datetime.now(dt.timezone.utc).isoformat()}

    # ---- 共用的几段
    def work_order_to_customer(self, wo_nid, wo):
        """工单 → 销售订单 → 客户；返回 [(销售订单号, 节点)]"""
        sos = [(l["dst_key"], l["src_seq"]) for l in self.links("WorkOrder.sales_order", src=wo)]
        if not sos:      # 演示工单等没有链接：用看板订单的“工单”文字对上
            sos = [(o["name"], None) for o in self.c.ov["orders"] if wo in (o.get("work_orders") or "")]
        out = []
        for so, seq in sos:
            o = next((x for x in self.c.ov["orders"] if x["name"] == so), None)
            v = {}
            if o:
                late = None
                if o.get("projected"):
                    late = (dt.date.fromisoformat(o["projected"][:10]) - dt.date.fromisoformat(o["delivery_date"][:10])).days
                v = {"交期": o["delivery_date"], "预计完成": o.get("projected"), "晚（天）": late, "风险": o.get("risk")}
            sn = self.node("SalesOrder", so, values=v)
            self.edge(wo_nid, sn, "属于", "链接 WorkOrder.sales_order" if seq else "看板“订单与交期”的工单对应", seq)
            if o and v.get("预计完成"):
                self.edge(wo_nid, sn, "预计完成 {}（交期 {}）".format(v["预计完成"][:10], o["delivery_date"][:10]), "计算：看板订单预测（kpi.overview）")
            for l in self.links("SalesOrder.customer", src=so):
                cn = self.node("Customer", l["dst_key"])
                self.edge(sn, cn, "客户", "链接 SalesOrder.customer", l["src_seq"])
            if not self.links("SalesOrder.customer", src=so) and o and o.get("customer"):
                cn = self.node("Customer", o["customer"])
                self.edge(sn, cn, "客户", "看板订单的客户字段")
            out.append((so, sn, v))
        return out

    def part_tool(self, part_nid, part, unit=None):
        """零件 → 加工记录（某设备）→ 刀具 / 砂轮 → 设备；返回 [(刀具号, 节点, 加工记录)]"""
        out = []
        for l in self.links("PartSerial.processed", src=part):
            p = l["props"] or {}
            if unit and p.get("machine") != unit:
                continue
            if not p.get("tool"):
                continue
            life = p.get("tool_life_pct")
            tn = self.node("Tool", p["tool"], role="cause", values={"加工时剩余寿命 %": life} if life is not None else None)
            self.edge(part_nid, tn, "{}（{}{}）".format((p.get("operation") or "").split(" ")[0], (p.get("machine") or "").upper(),
                                                     "，刀具剩 {}%".format(life) if life is not None else ""),
                      "链接 PartSerial.processed（加工记录）", l["src_seq"], values={"start": p.get("start"), "end": p.get("end")})
            mn = self.node("Machine", p.get("machine"), role="cause")
            self.edge(tn, mn, "装在", "链接 Machine.tool")
            out.append((p["tool"], tn, p))
        return out

    def same_tool(self, tool, tn, exclude=(), label="同一刀具加工", limit=40):
        """同一把刀 / 同一片砂轮加工过的零件"""
        rows = self.db.q("select src_key, src_seq, props from ont_link where mode=%s and type='PartSerial.processed' and props->>'tool'=%s "
                         "order by ts limit %s", (self.mode, tool, limit + len(exclude) + 1))
        parts = []
        for r in rows:
            if r["src_key"] in exclude:
                continue
            pn = self.node("PartSerial", r["src_key"], values={"加工时剩余寿命 %": (r["props"] or {}).get("tool_life_pct")})
            self.edge(tn, pn, label, "链接 PartSerial.processed（props.tool = {}）".format(tool), r["src_seq"])
            parts.append((r["src_key"], pn))
        return parts

    def shaft_to_field(self, shaft, sn, alarmed=()):
        """输出轴 → 装入的总成 → 出厂的现场设备 → 客户"""
        for l in self.links("PartSerial.installed_in", src=shaft):
            an = self.node("PartSerial", l["dst_key"])
            self.edge(sn, an, "装入", "链接 PartSerial.installed_in（孪生出厂数据）")
            for b in self.links("PartSerial.became", src=l["dst_key"]):
                fu = self.obj("FieldUnit", b["dst_key"]) or {}
                fn = self.node("FieldUnit", b["dst_key"], values={"健康度": fu.get("health"), "报警": b["dst_key"] in alarmed})
                self.edge(an, fn, "出厂为", "链接 PartSerial.became")
                for cl in self.links("FieldUnit.customer", src=b["dst_key"]):
                    cn = self.node("Customer", cl["dst_key"])
                    self.edge(fn, cn, "客户", "链接 FieldUnit.customer")
                yield b["dst_key"], fu


# ------------------------------------------------------------------ 种子链路
def chain_down(c, unit, vals=None, anchor=ANCHOR):
    g = Chain(c, "down")
    m = next((x for x in c.ov["machines"] if x["unit"] == unit), None)
    mn = g.node("Machine", unit, role="subject", values={"状态": m["state"] if m else None, "原因": m["reason"] if m else None,
                                                         "预计还要（分钟）": round((m["down_until_s"] or 0) / 60) if m else None})
    g.edge(anchor, mn, "涉及", "规则")
    d = c.db.q("select key, props, src_seqs from ont_object where mode=%s and type='Downtime' and props->>'machine'=%s "
               "and not (props ? 'end') order by first_seq desc limit 1", (c.mode, unit))
    if d:
        dn = g.node("Downtime", d[0]["key"], role="cause", values={"原因": d[0]["props"].get("reason")})
        g.edge(dn, mn, "停机", "链接 Downtime.machine", (d[0]["src_seqs"] or [None])[0])
    jobs = [j for j in (m or {}).get("dispatched", []) if (j.get("done") or 0) < (j.get("qty") or 0)]
    wos = {}
    for j in jobs:
        r = c.db.one("select key from ont_object where mode=%s and type='OperationTask' and props->>'work_order'=%s and props->>'operation'=%s",
                     (c.mode, j["work_order"], j["operation"]))
        on = g.node("OperationTask", r["key"] if r else "{}/{}".format(j["work_order"], j["operation"]),
                    values={"剩余件数": (j.get("qty") or 0) - (j.get("done") or 0), "已开工": j.get("started")},
                    display=None if r else "{} · {}".format(j["work_order"], j["operation"]))
        g.edge(mn, on, "推迟（剩 {} 件）".format((j.get("qty") or 0) - (j.get("done") or 0)), "设备派工队列（machine.status.dispatched）")
        wn = g.node("WorkOrder", j["work_order"])
        g.edge(on, wn, "属于", "链接 OperationTask.work_order")
        wos[j["work_order"]] = wn
    late = []
    for wo, wn in wos.items():
        for so, sn, v in g.work_order_to_customer(wn, wo):
            late.append((so, v))
    mins = round((m["down_until_s"] or 0) / 60) if m else 0
    g.summary.append("{} {}（{}），预计还要约 {} 分钟（工厂时间）".format(unit.upper(), "故障" if m and m["state"] == "fault" else "停机",
                                                              (m or {}).get("reason") or "原因未填", mins))
    if jobs:
        g.summary.append("排在它上面、还没做完的工序 {} 道，涉及工单 {}".format(len(jobs), "、".join(wos)))
    for so, v in late:
        if v.get("晚（天）") is not None:
            g.summary.append("销售订单 {}：交期 {}，按现在的预测 {} 完成，{}".format(
                so, v["交期"][:10], (v["预计完成"] or "")[:10], "晚 {} 天".format(v["晚（天）"]) if v["晚（天）"] > 0 else "还来得及（余 {} 天）".format(-v["晚（天）"])))
    g.scope = {"work_orders": sorted(wos), "sales_orders": [s for s, _ in late], "remaining_min": mins}
    return g


def chain_quality(c, parts, unit=None, char=None, anchor=ANCHOR):
    g = Chain(c, "quality")
    tools = {}
    for p in parts:
        pn = g.node("PartSerial", p, role="subject")
        g.edge(anchor, pn, "测得", "规则（检验测量）")
        for tool, tn, rec in g.part_tool(pn, p, unit):
            tools.setdefault(tool, {"tn": tn, "parts": set()})["parts"].add(p)
    # 老师注入的情景（敏感级别 3，学生看到的是“原因待查”）
    for q in c.db.q("select id, problem from quality_problem where mode=%s and cleared_at is null", (c.mode,)) if _has(c, "quality_problem") else []:
        from sim.errors import PROBLEMS
        pr = PROBLEMS.get(q["problem"], {})
        if unit and pr.get("unit") != unit:
            continue
        qn = g.node("QualityProblem", str(q["id"]), role="cause", display=pr.get("name"))
        g.edge(qn, g.node("Machine", pr.get("unit"), role="cause"), "造成", "老师注入的问题情景")
    recheck = set()
    for tool, x in tools.items():
        life = g.nodes[x["tn"]]["values"].get("加工时剩余寿命 %")
        for k, _ in g.same_tool(tool, x["tn"], exclude=x["parts"], label="同一刀具加工（建议复检）"):
            recheck.add(k)
        if life is not None and life < 30:
            g.summary.append("{} 加工这些零件时剩余寿命只有 {}%，磨损是首要怀疑对象".format(tool, life))
    g.summary.insert(0, "{}{} 涉及零件 {} 件，追到 {} 把刀具 / 砂轮".format(char + "：" if char else "", "", len(parts), len(tools)))
    if recheck:
        g.summary.append("同一刀具加工的其他零件 {} 件，建议复检：{}".format(len(recheck), "、".join(sorted(recheck)[:12]) + ("…" if len(recheck) > 12 else "")))
    g.scope = {"parts": sorted(parts), "tools": sorted(tools), "recheck": sorted(recheck)}
    return g


def chain_field(c, units, anchor=ANCHOR, label="报警", how="规则 V1（数字孪生健康度）"):
    g = Chain(c, "field")
    wheels, scope_units, customers = {}, set(), set()
    for u in units:
        fu = g.obj("FieldUnit", u) or {}
        fn = g.node("FieldUnit", u, role="subject", values={"健康度": fu.get("health"), "报警": True})
        g.edge(anchor, fn, label, how)
        for b in g.links("PartSerial.became", dst=u):
            an = g.node("PartSerial", b["src_key"], role="cause")
            g.edge(fn, an, "出厂总成", "链接 PartSerial.became")
            for s in g.links("PartSerial.installed_in", dst=b["src_key"]):
                sn = g.node("PartSerial", s["src_key"], role="cause")
                g.edge(an, sn, "装的输出轴", "链接 PartSerial.installed_in（孪生出厂数据）")
                for tool, tn, rec in g.part_tool(sn, s["src_key"], "grd-01"):
                    wheels.setdefault(tool, (tn, set()))[1].add(s["src_key"])
    not_shipped = set()
    for tool, (tn, own) in wheels.items():
        for shaft, pn in g.same_tool(tool, tn, exclude=own, label="同一片砂轮磨出", limit=80):
            shipped = False
            for fu_key, fu in g.shaft_to_field(shaft, pn, alarmed=units):
                shipped = True
                scope_units.add(fu_key)
                if fu.get("customer"):
                    customers.add(fu["customer"])
            if not shipped:
                not_shipped.add(shaft)
    scope_units -= set(units)
    g.summary.append("{}设备 {} 台：{}".format("投诉的" if label == "投诉" else "报警", len(units), "、".join(units)))
    if wheels:
        g.summary.append("它们的输出轴由 {} 磨削".format("、".join(sorted(wheels))))
    g.summary.append("同一片砂轮磨出的轴装在另外 {} 台现场设备上{}".format(
        len(scope_units), "（{}），属于客户：{}".format("、".join(sorted(scope_units)), "、".join(sorted(customers))) if scope_units else ""))
    if not_shipped:
        g.summary.append("还有 {} 根同一片砂轮磨出的轴没有装机（在库或在制），装配前建议复检轴承位".format(len(not_shipped)))
    g.scope = {"alarmed": sorted(units), "wheels": sorted(wheels), "check_units": sorted(scope_units), "customers": sorted(customers),
               "not_shipped": sorted(not_shipped)}
    return g


def chain_stock(c, items, anchor=ANCHOR):
    from factory import data as F
    from hub import kpi
    g = Chain(c, "stock")
    wos, need, sos_direct = {}, {}, []
    mats = {m["code"]: m for m in c.ov["materials"]}
    for it in items:
        m = mats.get(it) or {}
        inn = g.node("Item", it, role="subject", values={"库存": m.get("qty"), "安全库存": m.get("safety"), "需要": m.get("need")})
        g.edge(anchor, inn, "缺", "规则（看板关键物料）")
        for w in c.db.erp_docs("Work Order", c.mode):
            d = w["data"]
            if d.get("status") in ("Completed", "Cancelled", "Stopped", "Closed") or d.get("production_item") not in F.BOMS:
                continue
            q = kpi.explode(d["production_item"], float(d.get("qty") or 0)).get(it)
            if not q:
                continue
            wn = g.node("WorkOrder", d["name"], values={"用量": q})
            g.edge(inn, wn, "需要 {:g}".format(q), "计算：BOM 多级展开（kpi.explode）")
            wos[d["name"]] = wn
            need[it] = need.get(it, 0) + q
        for o in c.ov["orders"]:
            q = kpi.explode(o["item"], float(o.get("qty") or 0)).get(it) if o.get("item") in F.BOMS else None
            if q or it in str(o.get("short") or ""):
                sn = g.node("SalesOrder", o["name"], values={"交期": o["delivery_date"], "风险": o.get("risk"), "用量": q})
                g.edge(inn, sn, "订单需要 {:g}".format(q) if q else "缺料影响",
                       "计算：BOM 多级展开（kpi.explode）" if q else "看板订单的缺料字段")
                for cl in g.links("SalesOrder.customer", src=o["name"]):
                    g.edge(sn, g.node("Customer", cl["dst_key"]), "客户", "链接 SalesOrder.customer", cl["src_seq"])
                sos_direct.append(o["name"])
    sos = []
    for wo, wn in wos.items():
        sos += [s for s, _, _ in g.work_order_to_customer(wn, wo)]
    for it in items:
        m = mats.get(it) or {}
        g.summary.append("{} 库存 {}，安全库存 {}，在手工单还要 {:g}".format(it, m.get("qty_text", m.get("qty")), m.get("safety"), need.get(it, 0)))
    if wos:
        g.summary.append("用到它的未完工单：{}；对应销售订单：{}".format("、".join(wos), "、".join(sorted(set(sos))) or "—"))
    if sos_direct:
        g.summary.append("在手订单里用到它的：{}".format("、".join(sorted(set(sos_direct)))))
    g.scope = {"items": items, "work_orders": sorted(wos), "sales_orders": sorted(set(sos) | set(sos_direct))}
    return g


def chain_cost(c, wo, anchor=ANCHOR):
    from hub import mrp
    g = Chain(c, "cost")
    k = mrp.wo_cost(c.db, wo, c.mode) or {"lines": []}
    wn = g.node("WorkOrder", wo, role="subject", values={"标准": k.get("std_cost"), "实际": k.get("actual_cost"), "差异 %": k.get("variance_pct")})
    g.edge(anchor, wn, "成本差异", "规则 F1")
    for l in k["lines"]:
        if (l.get("variance") or 0) <= 0:
            continue
        on = g.node("OperationTask", "{}/{}".format(wo, l["op_index"]), role="cause",
                    values={"差异 $": l["variance"], "调整 min": round(l["setup_s"] / 60), "换刀 min": round(l["tool_change_s"] / 60),
                            "超时 min": round((l["cycle_s"] - l["std_s"]) / 60, 1)})
        g.edge(on, wn, "差 ${:.2f}".format(l["variance"]), "计算：成本模块（mrp.wo_cost）")
        mn = g.node("Machine", l["unit"], role="cause")
        g.edge(mn, on, "在", "链接 OperationTask.machine")
    if k.get("variance") is not None:
        g.summary.append("工单 {} 实际比标准高 ${:.2f}（{}%）：调整与换刀 ${:.2f}，节拍超时 ${:.2f}".format(
            wo, k["variance"], k.get("variance_pct"), k.get("setup_cost", 0), k.get("overrun_cost", 0)))
        if k.get("worst_operation"):
            g.summary.append("差异最大的工序：{}".format(k["worst_operation"]))
    g.scope = {"work_order": wo}
    return g


def chain_late(c, so=None, wo=None, anchor=ANCHOR):
    g = Chain(c, "late")
    wos = []
    if so:
        o = next((x for x in c.ov["orders"] if x["name"] == so), {})
        sn = g.node("SalesOrder", so, role="subject", values={"交期": o.get("delivery_date"), "预计完成": o.get("projected"), "风险": o.get("risk")})
        g.edge(anchor, sn, "可能延期", "规则 S1（看板订单预测）")
        wos = [(l["src_key"], sn) for l in g.links("WorkOrder.sales_order", dst=so)]
        if not wos:
            wos = [(w, sn) for w in (o.get("work_orders") or "").replace("，", " ").replace("、", " ").split() if w.startswith(("MFG-WO", "WO-"))]
        if o.get("short"):
            g.summary.append("缺料：{}".format(o["short"]))
    else:
        wos = [(wo, None)]
    machines = {m["unit"]: m for m in c.ov["machines"]}
    for w, parent in wos:
        wn = g.node("WorkOrder", w, role="subject" if not so else "cause")
        if parent:
            g.edge(wn, parent, "属于", "链接 WorkOrder.sales_order")
        else:
            g.edge(anchor, wn, "逾期", "规则 S2")
        for t in g.db.q("select key, props from ont_object where mode=%s and type='OperationTask' and props->>'work_order'=%s order by key",
                        (c.mode, w)):
            p = t["props"]
            if p.get("completed_at"):
                continue
            on = g.node("OperationTask", t["key"], role="cause", values={"已完成": p.get("done")})
            g.edge(on, wn, "未完工", "链接 OperationTask.work_order", )
            for l in g.links("OperationTask.machine", src=t["key"]):
                m = machines.get(l["dst_key"]) or {}
                bad = m.get("state") in ("down", "fault") or m.get("bottleneck")
                mn = g.node("Machine", l["dst_key"], role="cause" if bad else "impact",
                            values={"状态": m.get("state"), "排队": m.get("queue"), "瓶颈": m.get("bottleneck")})
                g.edge(mn, on, "在", "链接 OperationTask.machine", l["src_seq"])
                if bad:
                    g.summary.append("{} {}{}".format(l["dst_key"].upper(), "停机：" + (m.get("reason") or "") if m.get("state") in ("down", "fault") else "",
                                                      "是瓶颈，排队 {} 件".format(m.get("queue")) if m.get("bottleneck") else ""))
    g.scope = {"work_orders": [w for w, _ in wos]}
    if so:
        o = next((x for x in c.ov["orders"] if x["name"] == so), {})
        g.summary.insert(0, "{} 交期 {}，预计 {} 完成".format(so, (o.get("delivery_date") or "")[:10], (o.get("projected") or "—")[:10]))
    return g


def chain_generic(c, t, k, anchor=ANCHOR, label="涉及"):
    """没有专门链路的：本对象加一跳邻居"""
    g = Chain(c, "generic")
    n = g.node(t, k, role="subject")
    g.edge(anchor, n, label, "规则")
    for l in c.db.q("select * from ont_link where mode=%s and ((src_type=%s and src_key=%s) or (dst_type=%s and dst_key=%s)) "
                    "and type <> 'Anomaly.about' limit 30", (c.mode, t, str(k), t, str(k))):
        out_ = (l["src_type"], l["src_key"]) == (t, str(k))
        o = g.node(l["dst_type"] if out_ else l["src_type"], l["dst_key"] if out_ else l["src_key"])
        spec = g.onto.links.get((l["src_type"], l["type"].split(".", 1)[1]), {})
        if out_:
            g.edge(n, o, spec.get("l", ""), "链接 " + l["type"], l["src_seq"])
        else:
            g.edge(o, n, spec.get("l", ""), "链接 " + l["type"], l["src_seq"])
    return g


def chain_money(c, so, anchor=ANCHOR, invoice=None):
    """第 19 轮 J-4：钱的链——（发票 →）订单毛利 ← 多花的各项 ← 采纳的动作 ← 动作来自哪个异常（哪个领域）。
    “从毛利追回缺料”：订单上记的急单、加班、外协费用，每一笔都能追到当初的异常"""
    from hub import finance as FN
    g = Chain(c, "money")
    son = g.node("SalesOrder", so, role="subject")
    if invoice:
        rn = g.node("Receivable", invoice.get("doc") or "INV-{:05d}".format(invoice["id"]), role="impact",
                    values={"未付（$）": invoice.get("amount"), "逾期（天）": invoice.get("days")},
                    display="发票 {}".format(invoice.get("doc") or invoice["id"]))
        g.edge(anchor, rn, "逾期", "规则 F2")
        g.edge(rn, son, "开票自", "经营与财务：发票的来源订单")
    else:
        g.edge(anchor, son, "毛利", "经营与财务：订单毛利")
    try:
        m = FN.margin(c.db, c.mode, so, store=False)
    except KeyError:
        m = None
    if not m:
        g.summary.append("订单 {} 还没做完，毛利还算不出来".format(so))
        return g
    if m.get("customer"):
        g.edge(son, g.node("Customer", m["customer"]), "客户", "链接 SalesOrder.customer")
    g.nodes[son]["values"].update({"毛利率": m["margin_pct"], "按标准": m["std_margin_pct"], "收入（$）": m["revenue"]})
    lines = {x["key"]: x for x in m["lines"]}
    acts = (lines.get("actions") or {}).get("actions") or []
    if acts:
        rows = {r["id"]: r for r in c.db.q("select id, type, title, anomaly_id from action where id = any(%s)", ([a["id"] for a in acts],))}
        for a in acts:
            an = g.node("Action", str(a["id"]), role="cause", values={"费用（$）": a["usd"]}, display=a["title"])
            g.edge(an, son, "费用记到订单", "经营与财务：订单毛利“急单、加班、外协、加急”")
            aid = (rows.get(a["id"]) or {}).get("anomaly_id")
            if aid:
                x = c.db.one("select id, rule, title, domain from anomaly where id=%s", (aid,))
                if x:
                    nid = "Anomaly|A-{:05d}".format(x["id"])
                    g.nodes[nid] = {"id": nid, "type": "Anomaly", "key": "A-{:05d}".format(x["id"]), "display": x["title"], "label": "异常",
                                    "domain": x["domain"], "role": "cause", "values": {"规则": x["rule"]}}
                    g.edge(nid, an, "采纳", "动作的来源异常")
    for k in ("idle", "scrap", "warranty"):
        x = lines.get(k)
        if x and x["usd"] > 0:
            g.edge(g.node("CostLine", k, role="cause", values={"$": x["usd"]}, display=x["label"]), son, "多花", x["how"])
    extra = [x for x in m["lines"] if x["key"] in ("actions", "idle", "scrap", "warranty") and x["usd"] > 0]
    g.summary.append("{} 毛利率 {:.1%}（按标准 {:.1%}）".format(so, m["margin_pct"] or 0, m["std_margin_pct"] or 0)
                     + ("；多花在：" + "、".join("{} ${:,.0f}".format(x["label"], x["usd"]) for x in extra) if extra else ""))
    srcs = [n for n in g.nodes.values() if n["type"] == "Anomaly"]
    if srcs:
        g.summary.append("追到 {} 个源头异常：{}".format(len(srcs), "；".join(n["display"] for n in srcs[:4])))
    return g


def _has(c, table):
    return c.get("has:" + table, lambda: bool(c.db.one("select to_regclass(%s) is not null as ok", (table,))["ok"]))


# ------------------------------------------------------------------ 入口
def for_anomaly(c, a):
    """异常（anomaly 表的一行）→ 链条"""
    v = (a["detail"] or {}).get("values") or {}
    anchor_id = "Anomaly|A-{:05d}".format(a["id"])
    rule = a["rule"]
    st, sk = a["subject_type"], a["subject_key"]

    def g_():
        if rule in ("P1", "M1", "P5"):
            return chain_down(c, sk)
        if rule in ("Q1", "Q2", "Q3", "Q4"):
            char = v.get("characteristic")
            parts = v.get("parts") if isinstance(v.get("parts"), list) else None          # Q4 的 parts 是件数，不是序列号
            parts = parts or ([v["part"]] if v.get("part") else v.get("bad") or [])
            if rule == "Q1" and not parts:
                parts = [m["data"]["part_serial"] for m in c.db.messages(["quality.measurement"], mode=c.mode, order="desc", limit=200)
                         if m["data"].get("characteristic") == char][:5]
            return chain_quality(c, parts, GRIND.get(char), char)
        if rule == "V1":
            return chain_field(c, [sk])
        if rule == "V2":
            return chain_field(c, v.get("units") or [])
        if rule in ("W3",) and v.get("item"):           # 第 18 轮 E5：来料不合格 → 等这种料的工单 → 订单
            g = chain_stock(c, [v["item"]])
            if g.summary:
                g.summary[0] = "{} 批 {}（{}）来料不合格，这批进不了库；等这种料的工单和订单如下".format(v["item"], v.get("lot"), str(v.get("supplier") or "").split(" ")[0])
            return g
        if rule in ("W1",):
            return chain_stock(c, [sk])
        if rule == "W2":
            return chain_stock(c, [x["item"] for x in v.get("lines") or []])
        if rule == "F1":
            return chain_cost(c, sk)
        if rule == "F2" and v.get("sales_order"):        # 第 19 轮：应收逾期 → 发票 → 订单 → 订单上多花的钱 → 源头异常
            return chain_money(c, v["sales_order"], invoice={"id": v.get("invoice_id"), "doc": v.get("doc"), "amount": v.get("amount"), "days": v.get("days")})
        if rule == "F5" and v.get("sales_order"):        # 第 19 轮：订单毛利低 → 多花的钱 → 源头异常（从毛利追回缺料）
            return chain_money(c, v["sales_order"])
        if rule in ("S1", "R3"):
            return chain_late(c, so=sk)
        if rule in ("C1", "C3", "C4"):                  # 第 18 轮 E1：投诉 → 现场设备 → 出厂数据 → 同批 → 排查范围
            us = [x for x in (v.get("units") or []) if x]
            if us:
                return chain_field(c, us, label="投诉", how="客户投诉（规则 {}）".format(rule))
            g = Chain(c, "none")
            g.summary.append("这张投诉没有设备序列号，追不到出厂数据；先联系客户确认设备铭牌")
            return g
        if rule in ("M2", "M3", "M4", "M5", "M6") and (v.get("unit") or st == "Machine"):    # 第 18 轮 E3：保养 / 点检 / 维修 → 设备 → 工单 → 订单
            unit = v.get("unit") or sk
            g = chain_down(c, unit)
            m = next((x for x in c.ov["machines"] if x["unit"] == unit), None) or {}
            state = {"run": "在运转", "idle": "空闲", "setup": "在调整", "down": "停机", "fault": "故障"}.get(m.get("state"), m.get("state") or "—")
            if g.summary:
                extra = ""
                if v.get("p_fail") is not None:
                    extra = "；未来 80 运行小时坏掉的概率 {:.0%}".format(v["p_fail"])
                if v.get("overdue_h"):
                    extra = "；保养逾期 {:.0f} 运行小时".format(v["overdue_h"]) + extra
                g.summary[0] = "{} 现在{}{}；如果停下来，影响下面这些工单和订单".format(unit.upper(), state, extra)
            return g
        if rule == "H2" and v.get("unit"):              # 第 18 轮 E4：缺人 → 设备 → 工单 → 订单
            g = chain_down(c, v["unit"])
            if g.summary:
                g.summary[0] = "{} {} {} 没人能开（{}）；这一班它停着，影响下面这些工单和订单".format(
                    str(v.get("day"))[5:], {"day": "早班", "night": "晚班"}.get(v.get("shift"), ""), v["unit"].upper(), v.get("why") or "")
            return g
        if rule == "N1" and v.get("unit"):              # 第 18 轮 E6：单耗突增 → 设备（劣化）→ 停机维修影响的工单 → 订单
            g = chain_down(c, v["unit"])
            k = "E-{}".format(v["unit"].upper())
            g.edge(g.node("Meter", k, role="cause", values={"单件电量（度）": v.get("recent"), "基线": v.get("base")}),
                   g.node("Machine", v["unit"]), "计量", "链接 Meter.machine")
            if g.summary:
                g.summary[0] = "{} 每件多用 {:.0%} 的电，多半在劣化；停机维修会影响下面这些工单和订单".format(v["unit"].upper(), float(v.get("change") or 0))
            return g
        if rule in ("E1", "E2", "E5") and (v.get("unit") or st == "Machine"):   # 第 18 轮 E2：隐患 / 违规 → 设备 → 工单 → 订单
            unit = v.get("unit") or sk
            g = chain_down(c, unit)
            m = next((x for x in c.ov["machines"] if x["unit"] == unit), None) or {}
            if v.get("issue_id"):
                k = "SI-{:05d}".format(v["issue_id"])
                g.edge(g.node("SafetyIssue", k, role="cause", values={"内容": v.get("subject"), "整改工时（分钟）": v.get("fix_minutes")}),
                       g.node("Machine", unit), "隐患在", "链接 SafetyIssue.machine")
            state = {"run": "在运转", "idle": "空闲", "setup": "在调整", "down": "停机", "fault": "故障"}.get(m.get("state"), m.get("state") or "—")
            if g.summary:
                g.summary[0] = "{} 现在{}{}；{}".format(unit.upper(), state, "（挂牌上锁 {}）".format(m["locked"]) if m.get("locked") else "",
                                                      "要停机整改约 {} 分钟".format(v["fix_minutes"]) if v.get("fix_minutes") else "")
            return g
        if rule == "S2":
            return chain_late(c, wo=sk)
        return chain_generic(c, st, sk) if st else Chain(c, "none")
    g = g_()
    # 链条的起点是异常本身
    g.nodes[anchor_id] = {"id": anchor_id, "type": "Anomaly", "key": "A-{:05d}".format(a["id"]), "display": a["title"], "label": "异常",
                          "domain": a["domain"], "role": "anomaly", "values": {"严重度": a["severity"], "规则": rule}}
    for e in g.edges:
        if e["from"] == ANCHOR:
            e["from"] = anchor_id
    g.edges = [e for e in g.edges if e["from"] and e["to"]]
    if not [e for e in g.edges if e["from"] == anchor_id]:
        sub = "{}|{}".format(st, sk)
        if sub in g.nodes:
            g.edge(anchor_id, sub, "涉及", "规则 " + rule)
    return g.out()


def for_object(c, t, k):
    """任何对象的临时影响面（不开异常）"""
    if t == "Machine":
        g = chain_down(c, k)
    elif t == "PartSerial":
        g = chain_quality(c, [k])
    elif t == "Tool":
        g = Chain(c, "quality")
        tn = g.node("Tool", k, role="subject")
        parts = g.same_tool(k, tn, label="加工过", limit=80)
        g.summary.append("{} 加工过 {} 件零件".format(k, len(parts)))
        for p, pn in parts:
            for _ in g.shaft_to_field(p, pn):
                pass
    elif t == "FieldUnit":
        g = chain_field(c, [k])
    elif t == "Item":
        g = chain_stock(c, [k])
    elif t == "SalesOrder":
        g = chain_late(c, so=k)
    elif t == "WorkOrder":
        g = chain_late(c, wo=k)
    else:
        g = chain_generic(c, t, k)
    g.edges = [e for e in g.edges if e["from"] != ANCHOR]
    return g.out()
