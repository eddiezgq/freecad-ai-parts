# -*- coding: utf-8 -*-
"""工作台课程接口（第 4 轮）：学习平台的网关用只读钥匙，服务器对服务器地取真实案例和生产数据。

路径都在 /api/course/ 下（C1），只读；请求头 Authorization: Bearer <WQ_FACTORY_READ_KEY>（C2）。
返回的数据里操作人只写角色，不含姓名、账号编号（C4）；每次返回带 as_of、source（C6）；列表一页最多 10 000 行（C7）；
只开放教学情景 lab7（C10）。另有嵌入式 3D 车间用的嵌入凭证与回放数据（C8）、零件库对照（C9）。
"""
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.request

from fastapi import Depends, Header, HTTPException, Query, Request

from factory import data as F
import wqbus
from wqbus import layout as L

PAGE_MAX = 10000
CASE_MODE = {"lab7": "teach"}                       # C10：生产模式的数据不开放
KINDS = ("measurement", "event", "agv", "order", "kpi")
ORDER_DOCTYPES = ("Sales Order", "Work Order", "Purchase Order", "Material Request")
ROLE_ZH = {"planner": "计划员", "engineer": "工艺员", "operator": "操作工", "quality": "质检员", "manager": "厂长",
           "system": "系统", "sim": "仿真", "ai": "AI 助手"}
GUIDE_URL = "https://github.com/eddiezgq/WenQuest/blob/main/factory/digital/实验7_数字工厂闭环.md"
EMBED_TTL_MAX = 1800


# ---------------------------------------------------------------- 钥匙与公共部分（C2、C6、C7）
def _key():
    return os.environ.get("WQ_FACTORY_READ_KEY", "")


def require_key(authorization: str = Header(default="")):
    k = _key()
    got = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not k or not got or not hmac.compare_digest(got.encode(), k.encode()):
        raise HTTPException(401, "需要数字工厂只读钥匙（Authorization: Bearer …）")
    return True


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    if isinstance(t, str):
        return t
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def head(source, **kw):
    return dict({"as_of": iso(now_utc()), "source": source}, **kw)


def public_base(request):
    return (os.environ.get("WQ_PUBLIC_URL") or str(request.base_url)).rstrip("/")


def split_name(text, codes=False):
    """“深沟球轴承 6205-2RS Ball bearing 25×52×15” → {zh: 深沟球轴承 6205-2RS, en: Ball bearing 25×52×15}
    codes=True 时把英文部分里的规格代号（带数字或 Ø 的，如 Ø35、k6、W3）也补进中文名：检验项目要靠它区分。"""
    toks = str(text).split()
    last_cjk = max((i for i, t in enumerate(toks) if re.search(r"[一-鿿]", t)), default=-1)
    cut = next((i for i in range(last_cjk + 1, len(toks)) if re.match(r"[A-Za-z]", toks[i])), len(toks))
    extra = [t for t in toks[cut:] if codes and re.search(r"[0-9Ø]", t) and t not in toks[:cut]]
    zh, en = " ".join(toks[:cut] + extra), " ".join(toks[cut:])
    return {"zh": zh or en, "en": en or zh}


def role_of(source):
    """总线消息的 source → 角色（C4）：sim/… → sim；workbench/planner·a7f3 → planner；hub → system"""
    s = str(source or "")
    if s.startswith("sim"):
        return "sim"
    if s.startswith("ai"):
        return "ai"
    tail = s.split("/", 1)[1] if "/" in s else s
    if "·" in tail:
        r = tail.split("·")[0]
        return r if r in ROLE_ZH else "user"
    return "system" if s in ("hub", "system", "") or s.startswith(("hub", "bridge", "mes/system")) else "user"


# ---------------------------------------------------------------- 零件库对照（C9）
class LibraryMap:
    """每天读一次零件库的 latest.json 与 index.json，建立 ERPNext 物料号 → 库规格编号的对照。"""

    def __init__(self):
        self.map, self.at, self.lock = {}, 0.0, threading.Lock()

    def _load(self):
        d = os.environ.get("WQ_LIBRARY_DIR", "/library")
        try:
            latest = json.load(open(os.path.join(d, "latest.json"), encoding="utf-8"))
            idx = json.load(open(os.path.join(d, latest["index"].split("library/", 1)[1]), encoding="utf-8"))
        except (OSError, ValueError, KeyError, IndexError):
            url = os.environ.get("WQ_LIBRARY_URL", "")
            if not url:
                return {}
            try:
                latest = json.load(urllib.request.urlopen(url.rstrip("/") + "/library/latest.json", timeout=10))
                idx = json.load(urllib.request.urlopen(url.rstrip("/") + "/" + latest["index"], timeout=30))
            except Exception:  # noqa: BLE001
                return {}
        out = {}
        for it in idx.get("items", []):
            for code in it.get("erp_items") or []:
                out.setdefault(code, it["ref"])
        return out

    def get(self, code):
        with self.lock:
            if time.time() - self.at > 86400 or not self.at:
                self.map, self.at = self._load(), time.time()
        return self.map.get(code)


LIB = LibraryMap()


# ---------------------------------------------------------------- 产品（工厂设计数据）
def ws_code(ws_name):
    return ws_name.split()[-1].lower()                     # “数控车床 CNC-L01” → cnc-l01


def ws_units(ws_name):
    return [u for u, v in wqbus.UNITS.items() if v[3] == ws_name]


def ws_rate(ws_name):
    return float(sum(F.WORKSTATIONS[ws_name][1]))


def routing(item):
    if item not in F.BOMS:
        return []
    return [{"seq": i + 1, "operation": split_name(op), "workstation": ws_code(F.OPERATIONS[op]), "minutes": m}
            for i, (op, m) in enumerate(F.ROUTINGS[F.BOMS[item][0]])]


def bom_tree(code, qty=1):
    name, kind, uom = F.ITEMS[code][0], F.ITEMS[code][1], F.ITEMS[code][2]
    node = {"item_code": code, "name": split_name(name), "kind": kind, "qty": qty, "uom": uom,
            "library_ref": LIB.get(code)}
    if code in F.BOMS:
        node["children"] = [bom_tree(c, q) for c, q in F.BOMS[code][1]]
    return node


def std_cost(code):
    """标准成本（美元/件）：材料 = 外购件与原材料价格 × 用量（逐级累加）；工序 = 工时 × 工位费率（逐级累加）"""
    if code not in F.BOMS:
        return {"material": float(F.ITEMS[code][3] or 0), "operations": 0.0}
    mat = ops = 0.0
    for c, q in F.BOMS[code][1]:
        s = std_cost(c)
        mat += s["material"] * q
        ops += s["operations"] * q
    ops += sum(m / 60 * ws_rate(F.OPERATIONS[op]) for op, m in F.ROUTINGS[F.BOMS[code][0]])
    return {"material": mat, "operations": ops}


GAUGES = [("硬度", "硬度计"), ("粗糙度", "粗糙度仪"), ("公法线", "公法线千分尺"), ("噪声", "声级计"), ("温升", "温度计"),
          ("转速", "转速表"), ("直径", "三坐标"), ("孔径", "三坐标"), ("中心距", "三坐标"), ("平行度", "三坐标"),
          ("键槽", "三坐标"), ("偏差", "内径表")]


def characteristic(c):
    text = c["parameter"]
    m = re.search(r"\(([^()]*)\)\s*$", text)
    unit = m.group(1) if m else None
    base = text[: m.start()].strip() if m else text
    out = {"name": split_name(base, codes=True), "numeric": bool(c["numeric"]), "unit": unit}
    if c["numeric"]:
        out.update({"min": c["min"], "max": c["max"]})
        out["gauge"] = next((g for k, g in GAUGES if k in base), None)
    else:
        out.update({"requirement": c["value"], "gauge": "目测"})
    return out


def quality_plans():
    tpl = F.inspection_templates()
    by_tpl = {}
    for code, v in F.ITEMS.items():
        if v[5]:
            by_tpl.setdefault(v[5], []).append(code)
    return [{"template": t, "item_code": (by_tpl.get(t) or [None])[0], "items": by_tpl.get(t, []),
             "characteristics": [characteristic(c) for c in cs]} for t, cs in tpl.items()]


def product_specs():
    a1 = F.center_distance(2, 24, 72)
    a2 = F.center_distance(3, 20, 70)
    return {"ratio": round(F.ratio(), 3), "input_speed_rpm": F.INPUT_SPEED_RPM,
            "output_speed_rpm": round(F.INPUT_SPEED_RPM / F.ratio(), 1),
            "center_distance_mm": [a1, a2], "stages": [
                {"pinion": {"code": a, **F.GEARS[a]}, "gear": {"code": b, **F.GEARS[b]}} for a, b in F.STAGES]}


def product_summary(code):
    return {"code": code, "name": split_name(F.ITEMS[code][0]), "summary": F.ITEMS[code][6], "image": None,
            "specs": product_specs() if code == "WQR-105" else {}}


def product_detail(code):
    tree = bom_tree(code)
    items, stack = [], [tree]
    while stack:
        n = stack.pop()
        items.append(n["item_code"])
        stack.extend(n.get("children", []))
    made = [i for i in items if i in F.BOMS]
    used_ws = sorted({F.OPERATIONS[op] for i in made for op, _ in F.ROUTINGS[F.BOMS[i][0]]})
    costs = {}
    for i in made:
        s = std_cost(i)
        costs[i] = {"material": round(s["material"], 2), "operations": round(s["operations"], 2),
                    "total": round(s["material"] + s["operations"], 2), "currency": "USD"}
    return head(["factory-data"], **product_summary(code), bom=tree,
                routings={i: routing(i) for i in made},
                workstations=[{"unit": ws_code(w), "name": split_name(wqbus.UNITS[ws_units(w)[0]][1] + " " +
                                                                        wqbus.UNITS[ws_units(w)[0]][2]),
                               "units": ws_units(w), "rate_per_hour": ws_rate(w),
                               "rate_parts": dict(zip(("depreciation", "labour", "energy"), F.WORKSTATIONS[w][1])),
                               "capacity": F.WORKSTATIONS[w][0]} for w in used_ws],
                quality_plans=[q for q in quality_plans() if set(q["items"]) & set(items)],
                std_cost=costs)


# ---------------------------------------------------------------- 设计版本（FreeCAD 发布，历史库）
def designs(db, item, base):
    rel = db.messages(["design.release"], mode="teach")
    gcs = db.messages(["design.gcode"], mode="teach")
    out = []
    for r in rel:
        d = r["data"]
        if str(d.get("item", "")).upper() != item.upper():
            continue
        files = []
        for f in d.get("files") or []:
            kind = {"drawing": "svg"}.get(f.get("kind"), f.get("kind"))
            files.append({"kind": kind, "name": f.get("name"), "url": base + "/api/files/" + f["sha256"], "sha256": f["sha256"]})
        g = next((x["data"] for x in reversed(gcs) if x["data"].get("item") == d["item"]
                  and x["data"].get("revision") == d["revision"]), None)
        gco = None
        if g:
            sha = g.get("sha256") or str(g.get("gcode_ref", "")).rsplit("/", 1)[-1]
            row = db.one("select name, content from stored_file where sha256=%s", (sha,)) if sha else None
            if row:
                files.append({"kind": "gcode", "name": row["name"], "url": base + "/api/files/" + sha, "sha256": sha})
            gco = {"operation": split_name(g.get("operation", "")), "machine": g.get("machine"),
                   "est_time_s": g.get("est_time_s"), "cut_length_mm": g.get("cut_length_mm"),
                   "lines": bytes(row["content"]).count(b"\n") if row else None}
        out.append({"revision": d["revision"], "released_at": r["ts"], "author_role": _author_role(d.get("author")),
                    "change_note": d.get("change_note") or "", "params": d.get("params") or {},
                    "bom": d.get("bom") or [], "files": files, "gcode": gco})
    out.sort(key=lambda x: x["revision"])
    return head(["freecad", "historian"], item=item.upper(), revisions=out)


def _author_role(a):
    a = str(a or "")
    return a.split("·")[0] if "·" in a else "engineer"


# ---------------------------------------------------------------- 生产数据（历史库）
def _range(frm, to):
    try:
        t1 = dt.datetime.fromisoformat(to.replace("Z", "+00:00")) if to else now_utc()
        t0 = dt.datetime.fromisoformat(frm.replace("Z", "+00:00")) if frm else t1 - dt.timedelta(days=7)
    except ValueError:
        raise HTTPException(400, "from、to 要用 ISO 时间，如 2026-10-01T00:00:00Z")
    t0 = t0 if t0.tzinfo else t0.replace(tzinfo=dt.timezone.utc)
    t1 = t1 if t1.tzinfo else t1.replace(tzinfo=dt.timezone.utc)
    if t1 <= t0:
        raise HTTPException(400, "to 要晚于 from")
    return t0, t1


def _page(db, sql, args, page):
    rows = db.q(sql + " limit %s offset %s", list(args) + [PAGE_MAX + 1, (page - 1) * PAGE_MAX])
    return rows[:PAGE_MAX], (page + 1 if len(rows) > PAGE_MAX else None)


BUS_ROWS = ("select ts, topic, payload from bus_message where valid and mode=%s and type=%s and ts >= %s and ts <= %s "
            "order by ts, seq")


def data_rows(db, case, kind, t0, t1, page):
    mode = CASE_MODE[case]
    if kind == "measurement":
        rows, nxt = _page(db, BUS_ROWS, (mode, "quality.measurement", t0, t1), page)
        keys = ("part_serial", "item", "work_order", "characteristic", "name", "nominal_mm", "lower_tol_mm",
                "upper_tol_mm", "value_mm", "result")
        return [dict({"ts": iso(r["ts"])}, **{k: r["payload"]["data"].get(k) for k in keys}) for r in rows], nxt
    if kind == "agv":
        rows, nxt = _page(db, BUS_ROWS, (mode, "logistics.status", t0, t1), page)
        return [{"ts": iso(r["ts"]), "unit": r["topic"].split("/")[3], **{k: r["payload"]["data"].get(k)
                for k in ("x_m", "y_m", "heading_deg", "load", "task")}} for r in rows], nxt
    if kind == "event":
        sql = ("select * from (select ts, seq, topic, payload, null as state from bus_message where valid and mode=%s "
               "and type='machine.event' and ts >= %s and ts <= %s "
               "union all select ts, 0 as seq, 'wq/gearbox/x/' || unit || '/status' as topic, null as payload, state "
               "from machine_state_log where mode=%s and ts >= %s and ts <= %s) x order by ts, seq")
        rows, nxt = _page(db, sql, (mode, t0, t1, mode, t0, t1), page)
        out = []
        for r in rows:
            unit = r["topic"].split("/")[3]
            if r["payload"] is None:
                out.append({"ts": iso(r["ts"]), "unit": unit, "event": "state", "state": r["state"], "work_order": None,
                            "operation": None, "code": None, "message": None, "cycle_time_s": None, "actor_role": "sim"})
                continue
            d = r["payload"]["data"]
            out.append({"ts": iso(r["ts"]), "unit": unit, "event": d["event"], "state": None,
                        "work_order": d.get("work_order"), "operation": d.get("operation"), "code": d.get("code"),
                        "message": d.get("message") or d.get("reason"), "cycle_time_s": d.get("cycle_time_s"),
                        "actor_role": role_of(r["payload"].get("source"))})
        return out, nxt
    if kind == "order":
        sql = ("select ts, payload from bus_message where valid and mode=%s and type='erp.doc' and ts >= %s and ts <= %s "
               "and payload->'data'->>'doctype' = any(%s) and payload->'data'->>'action' <> 'failed' order by ts, seq")
        rows, nxt = _page(db, sql, (mode, t0, t1, list(ORDER_DOCTYPES)), page)
        out = []
        for r in rows:
            d = r["payload"]["data"]
            it = (d.get("items") or [{}])[0]
            out.append({"ts": iso(r["ts"]), "doctype": d["doctype"], "name": d["name"], "action": d["action"],
                        "status": d.get("status"), "customer": d.get("customer") or d.get("supplier"),
                        "item_code": d.get("production_item") or it.get("item_code"),
                        "qty": d.get("qty") if d.get("qty") is not None else it.get("qty"),
                        "delivery_date": d.get("delivery_date") or d.get("expected_delivery_date") or it.get("schedule_date"),
                        "produced_qty": d.get("produced_qty")})
        return out, nxt
    if kind == "kpi":
        return kpi_rows(db, mode, t0, t1), None
    raise HTTPException(400, "kind 只能是 " + "、".join(KINDS))


def kpi_rows(db, mode, t0, t1):
    """每个本地日期一行（工作日），指标算法与看板相同（hub/kpi.py）；otd 为当月累计准时交付率。"""
    from hub import kpi
    if t1 - t0 > dt.timedelta(days=62):
        raise HTTPException(400, "kpi 一次最多取 62 天")
    out = []
    d = t0.astimezone(kpi.TZ).date()
    last = t1.astimezone(kpi.TZ).date()
    while d <= last:
        if d.weekday() < 5:
            day0 = dt.datetime(d.year, d.month, d.day, tzinfo=kpi.TZ).astimezone(dt.timezone.utc)
            end = min(day0 + dt.timedelta(days=1), t1)
            if end > day0:
                ov = kpi.Overview(db, now=end, mode=mode)
                c = ov.cost(day0)
                out.append({"date": d.isoformat(), "otd": _r(ov.on_time()[0]), "oee": _r(ov.oee(day0)["value"]),
                            "fpy": _r(ov.fpy(day0)["value"]), "wip": ov.wip(end),
                            "output": sum(sum(v.values()) for v in ov.completions(day0, end).values()),
                            "cost_variance_pct": _r(c["value"] * 100 if c.get("value") is not None else None, 2)})
        d += dt.timedelta(days=1)
    return out


def _r(v, n=4):
    return None if v is None else round(float(v), n)


# ---------------------------------------------------------------- 嵌入凭证与回放（C8）
def _secret():
    return (os.environ.get("WQ_SECRET") or "wq-local").encode()


def embed_token(ttl):
    exp = int(time.time()) + max(60, min(int(ttl), EMBED_TTL_MAX))
    raw = base64.urlsafe_b64encode(json.dumps({"k": "embed", "exp": exp}).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return raw + "." + sig, exp


def check_embed_token(tok):
    try:
        raw, sig = tok.split(".")
        if not hmac.compare_digest(sig, hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:32]):
            return False
        p = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        return p.get("k") == "embed" and p.get("exp", 0) > time.time()
    except Exception:  # noqa: BLE001
        return False


def replay_rows(db, t0, t1):
    """回放一段：设备状态和 AGV 位置（只教学情景）。开头补上每台设备在 t0 之前的最后状态。"""
    first = db.q("select distinct on (topic) topic, ts, payload from bus_message where valid and mode='teach' "
                 "and type in ('machine.status','logistics.status') and ts < %s and ts > %s - interval '1 day' "
                 "order by topic, ts desc, seq desc", (t0, t0))
    rows = db.q("select topic, ts, payload from bus_message where valid and mode='teach' "
                "and type in ('machine.status','logistics.status') and ts >= %s and ts < %s order by ts, seq limit 50000",
                (t0, t1))
    out = []
    for r in list(first) + list(rows):
        d = r["payload"]["data"]
        unit = r["topic"].split("/")[3]
        if r["payload"]["type"] == "machine.status":
            x = {k: d.get(k) for k in ("state", "queue", "work_order", "operation", "qty", "qty_done", "reason")}
            out.append({"ts": iso(r["ts"]), "unit": unit, "kind": "machine", **x})
        else:
            out.append({"ts": iso(r["ts"]), "unit": unit, "kind": "agv",
                        **{k: d.get(k) for k in ("x_m", "y_m", "heading_deg", "load")}})
    return out


# ---------------------------------------------------------------- 路由
def mount(app, H):
    K = Depends(require_key)

    @app.get("/api/course/products", dependencies=[K])
    def course_products():
        return head(["factory-data"], items=[product_summary(c) for c, v in F.ITEMS.items() if v[1] == "fg"])

    @app.get("/api/course/products/{code}", dependencies=[K])
    def course_product(code: str):
        code = code.upper()
        if code not in F.ITEMS or F.ITEMS[code][1] != "fg":
            raise HTTPException(404, "没有这个产品")
        return product_detail(code)

    @app.get("/api/course/designs/{item}", dependencies=[K])
    def course_designs(item: str, request: Request):
        if item.upper() not in F.ITEMS:
            raise HTTPException(404, "没有这个物料")
        return designs(H.db, item, public_base(request))

    @app.get("/api/course/cases", dependencies=[K])
    def course_cases(request: Request):
        return head(["factory-data"], items=[{
            "id": "lab7", "name": {"zh": "实验 7：数字工厂闭环", "en": "Lab 7: the closed loop in a digital factory"},
            "summary": "WQR-105 减速器厂的一周：接单、算料排产、设计发布、车间加工、在线检测与不合格品处置、看板与 AI 提醒。",
            "mode": "teach", "guide_url": GUIDE_URL, "products": ["WQR-105"]}, {
            "id": "lab8", "name": {"zh": "实验 8：输出轴强度与疲劳校核", "en": "Lab 8: strength and fatigue check of the output shaft"},
            "summary": "有限元（Gmsh + CalculiX）算 SH-301 在 350 N·m 下的应力与安全系数，手算核对；用跑合试验台的转矩记录做雨流计数和疲劳寿命；"
                       "按 AI 建议换材料、改尺寸再算对比。",
            "mode": "teach", "products": ["SH-301"], "tool_url": public_base(request) + "/cae",
            "guide_url": public_base(request) + "/api/cae/lab8/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab8/report-template.docx"}, {
            "id": "lab9", "name": {"zh": "实验 9：机械臂关节力矩与电机选型", "en": "Lab 9: joint torques and motor sizing for a robot arm"},
            "summary": "多体动力学（MuJoCo）算 UR5e 搬运 3–4 kg 时各关节的力矩、转速、功率，手算重力矩核对，比较运动规划，"
                       "按峰值 / 均方根力矩和转速选伺服电机与谐波减速器；生活例子曲柄滑块（虚功原理核对、连杆送有限元）。",
            "mode": "teach", "products": ["B-ARM-UR5E", "C-LNK-SLIDER"], "tool_url": public_base(request) + "/mbd",
            "guide_url": public_base(request) + "/api/cae/lab9/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab9/report-template.docx"}, {
            "id": "lab10", "name": {"zh": "实验 10：输出轴数控车削与键槽铣削编程", "en": "Lab 10: CNC programming of the output shaft"},
            "summary": "从工艺规程的粗车、精车、铣键槽三道工序出发编 FANUC 程序：编程直径取公差带中间、余量传递、G96/G50、分层粗车、"
                       "斜线下刀；浏览器里试切（回放、去除材料、比对、功率与超程检查），加工时间与工艺规程比，挂到工艺规程审批后下发车间。",
            "mode": "teach", "products": ["SH-301"], "tool_url": public_base(request) + "/cam",
            "guide_url": public_base(request) + "/api/cae/lab10/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab10/report-template.docx"}, {
            "id": "lab11", "name": {"zh": "实验 11：减速器热平衡与输出轴轻量化", "en": "Lab 11: gearbox heat balance and output-shaft lightweighting"},
            "summary": "按传动效率算 WQR-105 的发热，教材公式估油温，有限元温度场看箱体上的温度分布；比较散热筋、风扇的降温效果，算热应力；"
                       "用设计优化（Optuna 驱动有限元）在安全系数和无限寿命要求下找最轻的输出轴并送回设计台；选做 CPU 散热片和平面拓扑优化。",
            "mode": "teach", "products": ["WQR-105", "SH-301"], "tool_url": public_base(request) + "/opt",
            "guide_url": public_base(request) + "/api/cae/lab11/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab11/report-template.docx"}, {
            "id": "lab12", "name": {"zh": "实验 12：一根轴的数字化设计与两个典型案例", "en": "Lab 12: digital design of a shaft and two case studies"},
            "summary": "零件库选件 → 在线设计台建 SH-301 B 版（台阶圆角）并发布；协作机器人关节空心轴 RJ-201 按扭转刚度核对、用“运动与动力分析”的"
                       "关节力矩记录算疲劳寿命、比较钢与铝；平缝机上轴 LS-101 比较两种轴承支承的固有频率并与梁理论对照、上传 CSV 载荷谱。",
            "mode": "teach", "products": ["SH-301", "RJ-201", "LS-101"], "tool_url": public_base(request) + "/cae",
            "guide_url": public_base(request) + "/api/cae/lab12/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab12/report-template.docx"}, {
            "id": "lab13", "name": {"zh": "实验 13：减速器数字孪生与预测性维护", "en": "Lab 13: digital twin and predictive maintenance of a gearbox"},
            "summary": "卖出去的每台 WQR-105 都有一个分身：出厂数据 + 现场运行数据 + 寿命模型（轴承 L10、输出轴疲劳、热平衡油温、润滑油）。"
                       "手算轴承载荷与寿命核对；从油温残差和振动诊断散热变差、轴承损坏；开维修单进 ERPNext、维修后寿命复位；假如分析与机队数据反馈设计。",
            "mode": "teach", "products": ["WQR-105"], "tool_url": public_base(request) + "/twin",
            "guide_url": public_base(request) + "/api/cae/lab13/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab13/report-template.docx"}, {
            "id": "lab14", "name": {"zh": "实验 14：减速器风扇冷却的流体与传热分析", "en": "Lab 14: CFD and heat transfer of fan cooling for a gearbox"},
            "summary": "OpenFOAM 虚拟风洞：先用四道标准题（平板间层流、平板换热、湍流通道、绕圆柱）核对方法；WQR-105 箱体轴端风扇冷却的流场、"
                       "阻力和各面散热系数 h，与平板公式比；h 加辐射送进有限元温度场算油温，和查表 K_s 比；改风速、风向、散热筋；选做 CPU 散热片风道、AGV 电控箱通风口布置。",
            "mode": "teach", "products": ["WQR-105"], "tool_url": public_base(request) + "/cfd",
            "guide_url": public_base(request) + "/api/cae/lab14/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab14/report-template.docx"}, {
            "id": "lab15", "name": {"zh": "实验 15：车间异常的追因、推演与决策", "en": "Lab 15: root cause, what-if simulation and decisions for shop-floor anomalies"},
            "summary": "老师注入停机、缺料或质量漂移；学生先用看板、车间终端、订单页手工追因，写出因果链；在推演工作台用仿真车间的快进副本试 3 个以上方案，"
                       "比较交期、成本和加班，选一个并说明理由；提交后再看厂情中枢的建议和 AI 分析（比对模式）；采纳、批准、执行，最后看推演与实际的自动复盘。",
            "mode": "teach", "products": ["WQR-105", "SH-301"], "tool_url": public_base(request) + "/lab15",
            "guide_url": public_base(request) + "/api/cae/lab15/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab15/report-template.docx"}, {
            "id": "lab16", "name": {"zh": "实验 16：客户投诉的追溯、召回与服务决策", "en": "Lab 16: complaint traceability, recall and service decisions"},
            "summary": "老师注入批次投诉：同一片砂轮磨的几根输出轴装在不同客户的现场，陆续出轴承问题。学生从投诉的设备往回追到输出轴、砂轮，"
                       "再往前找出同批次的设备、列排查范围，用数字孪生标出高风险的；比较“只修 / 修 + 高风险点检 / 整批排查”三个方案的客户数、费用、天数和遗漏风险，"
                       "选一个并说明理由（比对模式）；起草派工、备件出库和客户通知，批准、执行，最后看工程师上门和客户回访。",
            "mode": "teach", "products": ["WQR-105", "SH-301"], "tool_url": public_base(request) + "/lab16",
            "guide_url": public_base(request) + "/api/cae/lab16/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab16/report-template.docx"}, {
            "id": "lab17", "name": {"zh": "实验 17：安全隐患的识别、评估与停机决策", "en": "Lab 17: hazard identification, risk assessment and lockout decisions"},
            "summary": "老师注入重大隐患（磨床防护罩缺失等）。学生先做风险评估（危险源、可能性 × 严重度），再自己追“停这台设备影响哪些工单、订单”；"
                       "在指挥台比较“立即停机挂牌 / 限时整改 / 停机 + 改派加班”的交期和花费，选一个并说明理由（比对模式）；"
                       "起草停机挂牌整改，批准后车间里设备真的停下，维修工整改后验收解锁，最后看订单的实际影响。",
            "mode": "teach", "products": ["WQR-105", "SH-301"], "tool_url": public_base(request) + "/lab17",
            "guide_url": public_base(request) + "/api/cae/lab17/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab17/report-template.docx"}, {
            "id": "lab18", "name": {"zh": "实验 18：设备维护策略——保养时机的决策", "en": "Lab 18: maintenance strategy and preventive-maintenance timing"},
            "summary": "车间设备按威布尔失效率随机损坏，保养后复位。学生看设备台账和失效率曲线，手算保养逾期设备未来 80 运行小时坏掉的概率和预期损失；"
                       "在指挥台比较“现在保养 / 下班后保养 / 不做”（比对模式）；起草保养工单，到时间挂牌上锁、维修工保养、验收解锁；"
                       "运行一段时间后对比保养过与没保养的设备的故障记录，用故障记录估平均故障间隔。",
            "mode": "teach", "products": ["WQR-105", "SH-301"], "tool_url": public_base(request) + "/lab18",
            "guide_url": public_base(request) + "/api/cae/lab18/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab18/report-template.docx"}, {
            "id": "lab19", "name": {"zh": "实验 19：排班与技能——缺人时的决策", "en": "Lab 19: staffing and skills — deciding when someone is missing"},
            "summary": "车间设备要有人才能开：按排班和技能矩阵，没人停、学徒按 60% 速度。学生先在技能矩阵里找单点依赖；老师让一位关键操作工请假，"
                       "学生手算瓶颈设备停一个班少做多少件，在指挥台比较“调人顶岗 / 学徒带教 / 加班顶班 / 不处理”（比对模式）；"
                       "起草调班或加班动作，批准后车间按新排班开；最后设计技能培训计划，把单点依赖降到 0。",
            "mode": "teach", "products": ["WQR-105", "SH-301"], "tool_url": public_base(request) + "/lab19",
            "guide_url": public_base(request) + "/api/cae/lab19/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab19/report-template.docx"}, {
            "id": "lab20", "name": {"zh": "实验 20：供应链——来料不合格与供应商选择", "en": "Lab 20: supply chain — rejected incoming material and supplier selection"},
            "summary": "料从下单到用掉都在平台和 ERPNext 里：采购单、到货、来料检验、批次、用到哪些零件。学生先看供应商评分卡、找出单一来源；"
                       "老师注入一批不合格的轴承，学生按检验模板看抽样数据判定；在指挥台比较“退货等补发 / 备选急单 / 让步接收 / 不处理”（比对模式）并执行；"
                       "最后算两家供应商的总拥有成本，写供应商建议。",
            "mode": "teach", "products": ["WQR-105", "SH-301"], "tool_url": public_base(request) + "/lab20",
            "guide_url": public_base(request) + "/api/cae/lab20/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab20/report-template.docx"}, {
            "id": "lab21", "name": {"zh": "实验 21：能源——空转、错峰与单件碳足迹", "en": "Lab 21: energy — idling, peak shifting and the carbon footprint of a part"},
            "summary": "车间 16 个计量点每 15 分钟一个读数：每台设备的运行、空转、待机电量，峰平谷电费，碳排放。学生先找空转最多的设备，"
                       "按运行功率和工时算输出轴每件的电量和碳足迹；老师注入“卧加下班忘关、热处理峰时开炉”，学生在指挥台比较几种自动待机方案（比对模式）"
                       "并执行；最后算错峰和待机一个月各省多少钱、少排多少碳，区分“省钱”和“省电”。",
            "mode": "teach", "products": ["WQR-105", "SH-301"], "tool_url": public_base(request) + "/lab21",
            "guide_url": public_base(request) + "/api/cae/lab21/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab21/report-template.docx"}, {
            "id": "lab22", "name": {"zh": "实验 22：经营——订单毛利、应收与现金", "en": "Lab 22: business — order margin, receivables and cash"},
            "summary": "钱在工厂里走两条路：订单 → 开票 → 收款，采购 → 收货 → 发票 → 付款，都在 ERPNext 里。学生先在指挥台的指标树里找没达标的经营指标，"
                       "按分解表算一张订单的毛利（料、工、电、废品、急单加班、保修）；老师注入一笔客户逾期不付的发票，学生比较“催款 / 信用冻结 / 不处理”"
                       "（比对模式，看现金流预测）并执行；最后算应收周转天数，找现金最紧的一周，体会“赚钱”和“有钱”的区别。",
            "mode": "teach", "products": ["WQR-105", "SH-301"], "tool_url": public_base(request) + "/lab22",
            "guide_url": public_base(request) + "/api/cae/lab22/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab22/report-template.docx"}, {
            "id": "lab23", "name": {"zh": "实验 23：两周情景——一张急单的全厂决策", "en": "Lab 23: two-week scenario — whole-plant decisions on one rush order"},
            "summary": "两周课程设计，4–6 人一组、每人一个角色。老师在“情景导演”里一幕一幕地放：客户下急单 → 缺料 → 来料不合格 → 缺人 → "
                       "赶工时的安全隐患 → 设备保养逾期 → 空转与峰时 → 交付后应收逾期。每一幕由该负责的角色代表小组看推演、选方案、写理由"
                       "（比对模式）并发起动作；最后复盘：这张订单的毛利里能看到每一幕花的钱，从钱一路追回源头。",
            "mode": "teach", "products": ["WQR-105", "SH-301"], "tool_url": public_base(request) + "/lab23",
            "guide_url": public_base(request) + "/api/cae/lab23/guide.docx",
            "report_template_url": public_base(request) + "/api/cae/lab23/report-template.docx"}])

    @app.get("/api/course/layout", dependencies=[K])
    def course_layout():
        units = []
        for u, (x, y, w, d) in L.LAYOUT.items():
            v = wqbus.UNITS[u]
            ops = [split_name(op) for op, ws in F.OPERATIONS.items() if ws == v[3]]
            units.append({"unit": u, "name": {"zh": v[1], "en": v[2]}, "x_m": x, "y_m": y, "w_m": w, "d_m": d,
                          "area": v[0], "operations": ops})
        return head(["factory-data"], floor={"w_m": L.FLOOR[0], "d_m": L.FLOOR[1]}, units=units,
                    aisles=[{"axis": "x", "y_m": a, "width_m": 2.2} for a in L.AISLES] +
                           [{"axis": "y", "x_m": L.CROSS_X, "from_y_m": L.AISLES[0], "to_y_m": L.AISLES[1], "width_m": 2.2}],
                    agv_home={a: {"x_m": p[0], "y_m": p[1]} for a, p in L.AGV_HOME.items()})

    @app.get("/api/course/data", dependencies=[K])
    def course_data(case: str = "lab7", kind: str = "measurement", frm: str = Query(default="", alias="from"),
                    to: str = "", page: int = Query(default=1, ge=1)):
        if case not in CASE_MODE:
            raise HTTPException(404, "没有这个教学情景（目前只有 lab7）")
        if kind not in KINDS:
            raise HTTPException(400, "kind 只能是 " + "、".join(KINDS))
        t0, t1 = _range(frm, to)
        rows, nxt = data_rows(H.db, case, kind, t0, t1, page)
        return head("historian", case=case, kind=kind, **{"from": iso(t0), "to": iso(t1)}, rows=rows, page=page, next=nxt)

    @app.get("/api/course/embed-token", dependencies=[K])
    def course_embed_token(ttl: int = EMBED_TTL_MAX):
        tok, exp = embed_token(ttl)
        return {"token": tok, "expires": iso(dt.datetime.fromtimestamp(exp, dt.timezone.utc))}

    # 嵌入页面自己用的两个接口（不用只读钥匙）：总线地址（实时，匿名只读）；回放数据（要嵌入凭证）
    @app.get("/api/embed/config")
    def embed_config():
        return {"mqtt_ws": os.environ.get("WQ_MQTT_WS", "ws://localhost:9001/mqtt"), "mode": "teach"}

    @app.get("/api/embed/replay")
    def embed_replay(token: str = "", t0: str = "", minutes: float = Query(default=10, gt=0, le=60)):
        if not check_embed_token(token):
            raise HTTPException(401, "回放需要有效的嵌入凭证（30 分钟内有效）")
        try:
            a = dt.datetime.fromisoformat(t0.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "t0 要用 ISO 时间，如 2026-10-20T13:00:00Z")
        a = a if a.tzinfo else a.replace(tzinfo=dt.timezone.utc)
        b = a + dt.timedelta(minutes=minutes)
        return {"from": iso(a), "to": iso(b), "rows": replay_rows(H.db, a, b)}
