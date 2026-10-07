"""典型应用的工厂一侧（ADR-0061，M13 第三步）：设计院发布的方案在问渠数字工厂里走完
转为生产物料（ERP）→ 自制件工艺规程（AI 评审、审批）→ 接单与计划（MRP）→ 采购到货 → 车间执行（MES）→
工厂计算服务（有限元、数控编程、动力学）→ 厂情中枢（异常、推演、动作、简报、报告、对象搜索）。

先跑三个应用（带 --hub）把方案发布到工厂，再跑本脚本：
    python -m examples.apps.factory_flow --hub http://localhost:8100 [--erp http://localhost:8091] [--products COBOT-J2,…]

采购件的交期、单价零件库里没有，本脚本不填（工厂按“交期待确认”排程，价格留给采购员）；
订货客户、数量、交期是演练用的假设，写在报告的“假设”里。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from examples.apps import common as C

CUSTOMER = "示例·绿谷输送设备 GreenValley Conveyor (Demo)"
PRODUCTS = ["COBOT-J2", "SCARA-600", "LOCKSTITCH-DD"]
# 工厂复算设计院做过的轴：零件、应用、加扭矩的外圆直径（mm）、设计院动力学步骤与驱动、设计院有限元步骤
SHAFTS = {"COBOT-J2": ("RJ-201", "cobot_joint", 42.75, ("动力学", "j2"), "有限元：空心轴 RJ-201"),
          "LOCKSTITCH-DD": ("LS-101", "lockstitch", 10, ("动力学：针杆机构", "drive"), "有限元：上轴扭转")}


def _design_step(app, step):
    """设计院一侧的报告里某一步（没有时 None）。"""
    p = C.OUT / app / "report.json"
    if not p.exists():
        return None
    return next((x for x in json.loads(p.read_text(encoding="utf-8"))["steps"] if x["step"] == step), None)


class Hub:
    def __init__(self, base, erp=None):
        self.base, self.erp, self.tok = base.rstrip("/"), (erp or "").rstrip("/"), {}

    def call(self, method, path, body=None, role="manager", raw=None, ctype="application/json", base=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body, ensure_ascii=False).encode())
        h = {"Content-Type": ctype}
        if role and base is None:
            h["x-wq-token"] = self.login(role)
        req = urllib.request.Request((base or self.base) + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                b = r.read()
                return json.loads(b) if b[:1] in (b"{", b"[") else b
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} → {e.code} {e.read().decode('utf-8', 'replace')[:400]}") from None

    def login(self, role):
        if role not in self.tok:
            name = {"engineer": "演练·工艺员", "approver": "演练·技术负责人", "planner": "演练·计划员", "operator": "演练·操作工",
                    "manager": "演练·厂长", "quality": "演练·质检员"}[role]
            self.tok[role] = self.call("POST", "/api/login", {"name": name, "role": role, "mode": "teach"}, role=None)["token"]
        return self.tok[role]

    def get(self, path, role="manager"):
        return self.call("GET", path, role=role)

    def post(self, path, body=None, role="manager"):
        return self.call("POST", path, body if body is not None else {}, role=role)

    def upload_step(self, path: Path):
        bnd = uuid.uuid4().hex
        body = (f"--{bnd}\r\nContent-Disposition: form-data; name=\"step\"; filename=\"{path.name}\"\r\n"
                "Content-Type: application/step\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{bnd}--\r\n".encode()
        return self.call("POST", "/api/cae/geometry/upload", raw=body, ctype=f"multipart/form-data; boundary={bnd}", role="engineer")

    def wait(self, fn, seconds, every=3):
        t0 = time.time()
        while time.time() - t0 < seconds:
            v = fn()
            if v:
                return v
            time.sleep(every)
        return None

    def until(self, path, role, ends, seconds, every=3):
        """轮询 path，直到 status 落在 ends 里；超时返回 None。"""
        def probe():
            x = self.get(path, role)
            return x if x["status"] in ends else None
        return self.wait(probe, seconds, every)

    def proposal(self, pid, role="manager", seconds=120):
        self.post(f"/api/proposals/{pid}/confirm", role=role)
        return self.until(f"/api/proposals/{pid}", role, ("executed", "failed"), seconds, 2) or {"status": "timeout"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", required=True)
    ap.add_argument("--erp", help="ERPNext（或演示用的假 ERPNext）地址，给了就核对单据")
    ap.add_argument("--products", default=",".join(PRODUCTS))
    ap.add_argument("--qty", type=int, default=2)
    ap.add_argument("--speed", type=int, default=120, help="车间仿真倍速")
    ap.add_argument("--no-cae", action="store_true")
    a = ap.parse_args(argv)
    h = Hub(a.hub, a.erp)
    due = (dt.datetime.now(dt.UTC).date() + dt.timedelta(days=45)).isoformat()
    run = C.Run("factory_flow", "典型应用的工厂一侧：ERP、MRP、MES、工厂计算、厂情中枢", [
        {"title": "问渠数字工厂（本仓库 factory/digital）", "url": a.hub, "note": "本机原生启动的整座工厂：枢纽、假 ERPNext、桥接、车间仿真、计算服务"}],
        [f"订货客户“{CUSTOMER}”、每种产品 {a.qty} 台、交期 {due}：演练假设",
         "采购件交期、单价、成品售价零件库里没有，本脚本不填：工厂按“交期待确认”排程",
         f"车间仿真 {a.speed} 倍速；采购到货由脚本代替供应商送货",
         ("自制件工艺规程以方案带来的工艺路线为起点，第一道机加工工序的粗基准与装夹（回转件外圆 / 三爪卡盘，板件毛坯底面 / 平口钳）"
          "由脚本按工艺员的常规写法补上；工艺计算书没有，AI 评审会提醒")])
    st = {}
    err0 = len(h.call("GET", "/api/mock/errors", base=a.erp, role=None).get("errors", [])) if a.erp else 0

    for code in [x.strip() for x in a.products.split(",") if x.strip()]:
        d = None

        def design(code=code):
            nonlocal d
            ds = h.get("/api/cad/designs")
            hit = next((x for x in (ds.get("designs") if isinstance(ds, dict) else ds) if x["code"] == code), None)
            if not hit:
                run.add(f"{code}：设计方案", "skip", "工厂里没有这个方案（先用应用脚本带 --hub 发布）")
                return
            d = h.get(f"/api/cad/designs/{urllib.parse.quote(code)}")
            run.add(f"{code}：设计方案", "ok", f"第 {d.get('revision')} 版，外购件 {len(d['bom'])} 种、自制件 "
                    f"{len(d.get('made_parts') or [])} 种；校验结论 {(d.get('checks') or {}).get('overall')}")
        run.guard(f"{code}：设计方案", design)
        if not d:
            continue

        def erp(code=code):
            # 每次都走一遍：桥接在 ERPNext 里已有的供应商、物料、BOM 跳过，没有的补建（ERPNext 换过库也能接上）
            pv = h.post(f"/api/cad/designs/{urllib.parse.quote(code)}/production", {}, "engineer")
            sp = pv["preview"]
            p = h.proposal(pv["proposal_id"])
            run.add(f"{code}：转为生产物料（ERP）", "ok" if p["status"] == "executed" else "fail",
                    f"提议“{pv['title']}”经厂长确认后由桥接在 ERPNext 建 {len(sp['suppliers'])} 个供应商、{len(sp['items'])} 种物料、"
                    f"{len(sp['boms'])} 张 BOM（含工序）：{p['status']}；提醒：{'；'.join(sp['warnings']) or '无'}",
                    result=p.get("result"))
            if a.erp and p["status"] == "executed":
                # ADR-0062：再执行一次，同一版本不重复建 BOM，默认 BOM 只有一张（核对演示用的假 ERPNext）
                h.proposal(h.post(f"/api/cad/designs/{urllib.parse.quote(code)}/production", {}, "engineer")["proposal_id"])
                bs = [b for b in h.call("GET", "/api/mock/db/BOM", base=a.erp, role=None) if b["item"] == code]
                tag = f"第 {sp['revision']} 版"
                same = [b for b in bs if tag in (b.get("description") or "")]
                ok = len(same) == 1 and sum(1 for b in bs if b.get("is_default")) == 1 and same[0].get("is_default")
                run.add(f"{code}：改版与重复执行", "ok" if ok else "fail",
                        f"同一版本再执行一次：ERP 里第 {sp['revision']} 版 BOM {len(same)} 张、默认 BOM "
                        f"{sum(1 for b in bs if b.get('is_default'))} 张（共 {len(bs)} 张）")
        run.guard(f"{code}：转为生产物料（ERP）", erp)

        for mp in d.get("made_parts") or []:
            item = mp["code"]

            def proc(item=item, mp=mp):
                cur = h.get(f"/api/process/{urllib.parse.quote(item)}", "engineer")
                if cur.get("revision"):
                    run.add(f"{item}：工艺规程", "ok", f"已有第 {cur['revision']} 版，跳过")
                    return
                plan = dict(cur["factory_plan"], version=1, material=mp.get("material"),
                            blank={"material_item": (mp.get("raw") or {}).get("item_code")})
                turned = any("车" in o["operation"] for o in plan["operations"])
                first = True
                for o in plan["operations"]:
                    o["content"] = o["content"] or f"{o['operation'].split(' ')[0]}：按 {item} 图纸"
                    if first and any(k in o["operation"] for k in ("车", "铣", "磨")):
                        o["datum"] = "外圆（粗基准）" if turned else "毛坯底面（粗基准）"
                        o["clamping"] = "三爪卡盘" if turned else "平口钳"
                        first = False
                s = h.post("/api/process/submit", {"plan": plan, "note": "典型应用演练：按方案带来的工艺路线"}, "engineer")
                f = s["review"]["findings"]
                errs = [x for x in f if x["level"] == "error"]
                txt = "；".join(x["text"] for x in f[:4]) or "没有意见"
                if errs:
                    run.add(f"{item}：工艺规程", "fail", f"AI 工艺评审 {len(f)} 条意见、{len(errs)} 条错误，没批：{txt}")
                    return
                for c in s.get("comments") or []:
                    h.post(f"/api/process/submissions/{s['id']}/comments/{c['id']}", {"resolved": True}, "engineer")
                r = h.post(f"/api/process/submissions/{s['id']}/decision", {"decision": "approve", "note": "演练：评审意见已看过"}, "approver")
                run.add(f"{item}：工艺规程", "ok", f"工艺员提交 {len(plan['operations'])} 道工序，AI 工艺评审 {len(f)} 条意见（{txt}），"
                        f"技术负责人批准为第 {r.get('revision')} 版")
            run.guard(f"{item}：工艺规程", proc)

        def plan(code=code):
            pv = h.post("/api/plan/order", {"customer": CUSTOMER, "item": code, "qty": a.qty, "delivery_date": due}, "planner")
            p = h.proposal(h.post("/api/proposals", {"action": "create_order_and_plan", "customer": CUSTOMER, "item": code,
                                                     "qty": a.qty, "delivery_date": due}, "planner")["proposal_id"])
            st[code] = {"mr": pv["material_requests"], "wos": pv["work_orders"]}
            run.add(f"{code}：接单与计划（MRP）", "ok" if p["status"] == "executed" else "fail",
                    f"{a.qty} 台：工单 " + "、".join(f"{w['production_item']}×{w['qty']}（约 {w['est_minutes']:.0f} min）" for w in pv["work_orders"])
                    + "；请购 " + "、".join(f"{m['item_code']}×{m['qty']:g}" for m in pv["material_requests"])
                    + f"；提醒：{'；'.join(pv['warnings'][:3]) or '无'}；ERP 执行：{p['status']}", preview=pv)
        run.guard(f"{code}：接单与计划（MRP）", plan)
        if code not in st:
            continue

        def receive(code=code):
            items = [{"item_code": m["item_code"], "qty": m["qty"]} for m in st[code]["mr"]]
            if not items:
                run.add(f"{code}：采购到货", "ok", "库存够，不用买")
                return
            p = h.proposal(h.post("/api/purchase/receive", {"items": items})["proposal_id"])
            run.add(f"{code}：采购到货", "ok" if p["status"] == "executed" else "fail",
                    f"{len(items)} 种物料入原材料库（ERPNext 物料收货单）：{p['status']}")
        run.guard(f"{code}：采购到货", receive)

        def mes(code=code):
            h.post("/api/mes/cmd", {"unit": "sim", "command": "set_speed", "speed": a.speed}, "manager")
            mine = {w["production_item"] for w in st[code]["wos"]}
            wos = [w for w in h.get("/api/work_orders", "operator") if w.get("production_item") in mine
                   and w.get("status") not in ("Completed", "Stopped", "Cancelled")]
            latest = {}
            for w in sorted(wos, key=lambda w: w["name"]):
                latest[w["production_item"]] = w["name"]
            st[code]["wo"] = latest

            def go(wo):
                rel = h.post("/api/mes/release", {"work_order": wo}, "operator")["dispatched"]
                time.sleep(1)
                for x in rel:
                    h.post("/api/mes/cmd", {"unit": x["unit"], "command": "start", "work_order": wo, "operation": x["operation"]}, "operator")
                return rel

            def done(wo):
                evs = h.get(f"/api/history?type=machine.event&corr={urllib.parse.quote(wo)}&limit=500", "operator")
                return any(e["data"].get("event") == "op_complete" and e["data"].get("last_op") for e in evs)

            parts = [i for i in latest if i != code]
            t0 = time.time()
            units = []
            for i in parts:
                units += [x["unit"] for x in go(latest[i])]
            st[code]["units"] = units
            ok_parts = h.wait(lambda: all(done(latest[i]) for i in parts), 900, 5)
            t1 = time.time()
            time.sleep(8)
            go(latest[code])
            ok = h.wait(lambda: done(latest[code]), 900, 5)
            run.add(f"{code}：车间执行（MES）", "ok" if ok_parts and ok else "fail",
                    f"自制件工单 {'、'.join(f'{latest[i]}（{i}）' for i in parts) or '无'} 派到 {len(set(units))} 台设备，"
                    f"{'完工' if ok_parts else '超时'}（仿真 {t1 - t0:.0f} s）；总装工单 {latest[code]} {'完工' if ok else '超时'}"
                    f"（{time.time() - t1:.0f} s）", work_orders=latest)
        run.guard(f"{code}：车间执行（MES）", mes)

    # ---------------------------------------------------------------- 工厂计算服务（ADR-0060：内核与设计院同一份）
    if not a.no_cae:
        for code, (item, app, d_load, (dyn_step, dyn_key), fea_step) in SHAFTS.items():
            step = C.OUT / app / f"{item}.step"
            dyn = _design_step(app, dyn_step)
            if code not in a.products or not step.exists() or not dyn:
                continue
            torque = dyn["data"][dyn_key]["peak"]
            fd = (_design_step(app, fea_step) or {}).get("data", {})
            fea0 = fd.get("vm") or fd.get("vm_max")

            def cae(item=item, step=step, d_load=d_load, torque=torque, fea0=fea0):
                g = h.upload_step(step)
                ax = {"origin": [0, 0, 0], "dir": [0, 0, 1]}
                fs = g["faces"]
                load = min((f for f in fs if f.get("radius_mm") and abs(2 * f["radius_mm"] - d_load) < 0.01),
                           key=lambda f: f["center"][2])
                end = max((f for f in fs if f["kind"] == "plane"), key=lambda f: abs(f["center"][2] - load["center"][2]))
                dmax = 2 * max(f["radius_mm"] for f in fs if f.get("radius_mm"))
                setup = {"material_id": "45-QT", "mesh": {"size_mm": max(3, round(dmax / 10))}, "loads": [
                    {"type": "fixed", "faces": [end["id"]]},
                    {"type": "torque", "faces": [load["id"]], "value_nmm": torque * 1e3, "axis": ax}]}
                j = h.post("/api/cae/jobs", {"step_sha": g["sha"], "setup": setup, "item": item, "title": f"典型应用演练 {item} 扭转"}, "engineer")
                j = h.until(f"/api/cae/jobs/{j['id']}", "engineer", ("done", "failed"), 400)
                if not j or j["status"] != "done":
                    run.add(f"{item}：工厂有限元", "fail", f"任务没算完：{(j or {}).get('error')}")
                    return
                s = j["stats"]
                run.add(f"{item}：工厂有限元", "ok", f"工厂计算服务（与设计院同一份内核）复算：Ø{d_load:g} 段加设计院动力学的峰值扭矩 {torque:.1f} N·m、"
                        f"远端端面固定，{s['elements']} 个单元、最大 Von Mises {s['vm_max_mpa']:.1f} MPa、安全系数 {s['safety_factor']:.1f}"
                        + (f"（设计院 {fea0:.1f} MPa；网格与固定面不同，量级应一致）" if fea0 else ""))
                spec = h.post("/api/cam/spec/geometry", {"sha": g["sha"], "kind": "turn", "name": item, "seq": 10}, "engineer")
                cj = h.post("/api/cam/jobs", {"spec": spec, "title": f"典型应用演练 {item} 粗车"}, "engineer")
                cj = h.until(f"/api/cam/jobs/{cj['id']}", "engineer", ("done", "failed"), 300)
                ok = cj and cj["status"] == "done"
                run.add(f"{item}：工厂数控编程", "ok" if ok else "fail",
                        f"从 STEP 认出回转轮廓、生成粗车程序：{len(cj['programs']) if ok else 0} 个程序，"
                        f"{'；'.join(c['text'] for p in cj['programs'] for c in p.get('checks', [])) or '检查没有问题' if ok else (cj or {}).get('error')}")
            run.guard(f"{item}：工厂计算", cae)

        if "COBOT-J2" in a.products:
            def mbd():
                info = h.post("/api/mbd/models/load", {"source": "library", "id": "B-ARM-UR5E"}, "engineer")
                pose = {"shoulder_lift_joint": -1.2, "elbow_joint": 1.0}
                j = h.post("/api/mbd/jobs", {"model": {"source": "library", "id": "B-ARM-UR5E"}, "title": "典型应用演练 UR5e 保持姿态",
                                             "setup": {"duration_s": 0.5, "initial": pose,
                                                       "drives": [{"joint": x["name"], "kind": "hold"} for x in info["joints"]]}}, "engineer")
                j = h.until(f"/api/mbd/jobs/{j['id']}", "engineer", ("done", "failed"), 300)
                peak = {x["joint"]: x["peak"] for x in j["stats"]["drives"]} if j and j["status"] == "done" else {}
                run.add("UR5e：工厂动力学", "ok" if peak else "fail",
                        f"MuJoCo Menagerie 的 UR5e 模型保持姿态：肩关节 {peak.get('shoulder_lift_joint', float('nan')):.1f} N·m、"
                        f"肘关节 {peak.get('elbow_joint', float('nan')):.1f} N·m（与设计院的手算重力矩同一量级）")
            run.guard("UR5e：工厂动力学", mbd)

    # ---------------------------------------------------------------- 厂情中枢
    def hub_side():
        unit = next((u for c in st.values() for u in c.get("units", []) if u.startswith("cnc")), "cnc-l01-b")
        t0 = time.time()
        h.post("/api/mes/cmd", {"unit": unit, "command": "inject_fault", "minutes": 240, "reason": "典型应用演练：主轴过热"}, "manager")
        an = h.wait(lambda: next((x for x in h.get("/api/ont/anomalies", "manager")["anomalies"]
                                  if (x["subject"] or {}).get("key") == unit and x["status"] != "closed"), None), 120, 2)
        if not an:
            run.add("厂情中枢：异常", "fail", f"{unit} 停机后 120 s 内没出现异常")
            return
        dd = h.get(f"/api/ont/anomalies/{an['id']}", "manager")
        run.add("厂情中枢：异常与追因", "ok", f"{unit} 注入停机 {time.time() - t0:.0f} s 后出现异常“{an.get('title') or an['rule']}”；"
                f"因果链：{'；'.join(dd['chain']['summary'])[:200]}")
        o = h.get(f"/api/ont/anomalies/{an['id']}/options", "manager")
        if o.get("error"):
            run.add("厂情中枢：预案推演", "fail", f"推演出错：{o['error']}")
            return
        def cost(x):
            c = x.get("cost_total", (x.get("result") or {}).get("cost_total"))
            return f"（费用 {c:.0f}）" if c is not None else ""
        opts = "；".join(f"{x['key']} {x['label']}{cost(x)}" for x in o["options"])
        rec = next((x for x in o["options"] if x["key"] == o.get("recommended")), None)
        run.add("厂情中枢：预案推演", "ok", f"{len(o['options'])} 个方案：{opts}。推荐 {o.get('recommended')}：{o.get('reason')}")
        act_on = rec if rec and rec.get("changes") else next((x for x in o["options"] if x["kind"] == "expedite"), None)
        if act_on:
            act = h.post("/api/ont/actions", {"changes": act_on["changes"], "anomaly_id": an["id"], "snapshot_id": o["snapshot_id"]}, "manager")
            r = h.post(f"/api/ont/actions/{act['ids'][0]}/approve", {}, "manager")
            why = "按推荐" if act_on is rec else "推荐的是不处理；演练仍批准“维修加急”，看动作能否下到车间"
            run.add("厂情中枢：动作审批执行", "ok" if r["status"] in ("done", "executing") else "fail",
                    f"{why}：{act_on['key']} {act_on['label']} → {r['status']}，{(r.get('result') or {}).get('text', '')}")

    def hub_reset():
        """不管上面成不成，演练注入的停机都要复位、异常关掉，免得影响后面。"""
        unit = next((u for c in st.values() for u in c.get("units", []) if u.startswith("cnc")), "cnc-l01-b")
        for x in h.get("/api/ont/anomalies", "manager")["anomalies"]:
            if (x["subject"] or {}).get("key") == unit and x["status"] != "closed":
                h.post(f"/api/ont/anomalies/{x['id']}/close", {"text": "演练结束：复位"}, "manager")
        h.post("/api/mes/cmd", {"unit": unit, "command": "reset"}, "manager")
        h.post("/api/ont/shifts", {"mode": "continuous"}, "manager")
    run.guard("厂情中枢：异常", hub_side)
    run.guard("厂情中枢：复位", hub_reset)

    def hub_views():
        b = h.post("/api/ai/briefing/refresh", {}, "manager")
        rp = h.post("/api/reports/generate", {"kind": "daily"}, "manager")
        sit = h.get("/api/ont/situation", "manager")
        found = {}
        for code in a.products.split(","):
            r = h.get("/api/ont/search?q=" + urllib.parse.quote(code), "manager")["results"]
            found[code] = len(r)
        txt = json.dumps(b, ensure_ascii=False)
        run.add("厂情中枢：简报、日报、态势、搜索", "ok",
                f"AI 简报刷新（{len(txt)} 字）；日报“{rp.get('title', rp.get('id'))}”；全厂态势 {len(sit['cards'])} 块；"
                f"对象搜索命中：{'、'.join(f'{k} {v} 个' for k, v in found.items())}", report_id=rp.get("id"))
    run.guard("厂情中枢：简报、日报、态势、搜索", hub_views)

    if a.erp:
        def erp_check():
            errs = h.call("GET", "/api/mock/errors", base=a.erp, role=None).get("errors", [])[err0:]
            run.add("ERPNext 一致性", "ok" if not errs else "fail",
                    f"这次演练中假 ERPNext 记录的错误 {len(errs)} 条" + (f"：{errs[:3]}" if errs else ""))
        run.guard("ERPNext 一致性", erp_check)
    return run.save()


if __name__ == "__main__":
    import sys

    sys.exit(1 if any(x["status"] == "fail" for x in main()["steps"]) else 0)
