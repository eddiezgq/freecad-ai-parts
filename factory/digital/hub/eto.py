# -*- coding: utf-8 -*-
"""按单设计（ETO，第 139 轮）：作业号、估算、报价。

客户拿着要求或图纸来，产品是这一单专门设计的，接单时还没有物料清单和工艺。这里管 139a 这一段：
- 作业（eto_job）：每张询价一个作业号，后面的报价、订单、设计、采购、工单、检验、发票都挂在它上面；
- 估算（eto_estimate）：逐行估材料、外购件、工序工时、外协、设计工时；报价发出后那一版冻结，再改出新版本（改版留底）；
- compute()：确定性地算每个数量阶梯的成本和报价（纯函数）；单价、费率、工时缺的标“未知”，**有未知项不能发报价**；
- draft()：AI 读询价起草估算行（只给结构和工时，不给价格：价格取物料主数据，没有的由估算员填）；
  没有模型时，要求里写了现有产品编号就照它的物料清单和工艺起草；
- quote_preview()：发报价的提议内容；人确认后桥接在 ERPNext 建 Project（作业号）、物料（编号 = 作业号）、报价单。

企业之间不同的（作业号前缀、风险预留、加价率、设计费率、报价有效期、分期开票里程碑）是配置数据：
工厂清单的 eto 一节（factory/data.py 的 ETO；演示工厂是示例值）。
"""
import datetime as dt
import json
import math
import re

from factory import data as F
from factory import plant as _plant

SCHEMA = """
create table if not exists eto_job (
    mode         text not null,
    job_no       text not null,
    customer     text not null,
    title        text not null,
    requirement  text not null default '',
    qty          integer not null,
    qty_breaks   jsonb not null default '[]',
    due_date     date,
    status       text not null default 'estimating',   -- estimating / quoted（“报价确认中”看有没有未完的提议）
    created_by   text,
    created_at   timestamptz not null default now(),
    project      text,
    quotation    text,
    quoted_rev   integer,
    primary key (mode, job_no)
);
create table if not exists eto_estimate (
    mode        text not null,
    job_no      text not null,
    rev         integer not null,
    lines       jsonb not null,
    note        text,
    source      text,
    created_by  text,
    created_at  timestamptz not null default now(),
    primary key (mode, job_no, rev)
);
"""

KINDS = ("material", "buyout", "operation", "outside", "engineering")
KIND_ZH = {"material": "材料", "buyout": "外购件", "operation": "工序", "outside": "外协", "engineering": "设计"}
MILESTONE_ON = _plant.ETO_ON
MAX_BREAKS = 5


class EtoError(ValueError):
    pass


# ---------------------------------------------------------------- 配置
def config():
    """当前工厂的 ETO 配置（工厂清单的 eto 一节；演示工厂是示例值）；没配置的项为空，算出来是“未知”。"""
    c = getattr(F, "ETO", None)
    if not c:
        return {"prefix": "JOB-", "milestones": [], "example": False, "configured": False}
    return dict(json.loads(json.dumps(c)), example=_plant.is_demo(), configured=True)


def init(db):
    db.x(SCHEMA)


# ---------------------------------------------------------------- 估算（纯函数）
def _num(v):
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise EtoError("不是数字：{}".format(v))
    if math.isnan(x) or math.isinf(x):
        raise EtoError("不是数字：{}".format(v))
    return x


def op_rate(op):
    """工序的小时费率 = 工作站的折旧 + 人工 + 能耗（与标准成本同一来源）；查不到为 None"""
    ws = F.OPERATIONS.get(op)
    if ws not in F.WORKSTATIONS:
        return None
    r = float(sum(F.WORKSTATIONS[ws][1]))
    return r if r > 0 else None


def norm_line(raw):
    """一行估算：规整字段、查主数据，返回 (行, 错误清单)。行里不改动估算员给的值，只补出处。"""
    errs = []
    k = raw.get("kind")
    if k not in KINDS:
        return dict(raw), ["类别要写 {} 之一".format("、".join(KINDS))]
    ln = {"kind": k, "desc": str(raw.get("desc") or "").strip()[:200], "source": raw.get("source") or "human"}
    try:
        if k in ("material", "buyout"):
            code = str(raw.get("item_code") or "").strip()
            ln["item_code"] = code or None
            if code and code not in F.ITEMS:
                errs.append("物料 {} 不在物料主数据里（新物料不填编号，写说明）".format(code))
            ln["qty_per"] = _num(raw.get("qty_per"))
            ln["uom"] = str(raw.get("uom") or (F.ITEMS[code][2] if code in F.ITEMS else "") or "").strip() or None
            price = _num(raw.get("unit_price"))
            ln["price_from"] = "估算员" if price is not None else None
            if price is None and code in F.ITEMS and F.ITEMS[code][3] not in (None, ""):
                price, ln["price_from"] = float(F.ITEMS[code][3]), "物料主数据"
            ln["unit_price"] = price
            ln["lead_days"] = _num(raw.get("lead_days"))
            if not ln["desc"] and code in F.ITEMS:
                ln["desc"] = F.ITEMS[code][0]
        elif k == "operation":
            op = str(raw.get("op") or "").strip()
            ln["op"] = op
            if op not in F.OPERATIONS:
                errs.append("工序 {} 不在本厂工序表里".format(op or "（空）"))
            ln["setup_min"] = _num(raw.get("setup_min"))
            ln["run_min"] = _num(raw.get("run_min"))
            ln["rate_h"] = op_rate(op) if op in F.OPERATIONS else None
        elif k == "outside":
            ln["unit_price"] = _num(raw.get("unit_price"))
            ln["lead_days"] = _num(raw.get("lead_days"))
            ln["supplier"] = str(raw.get("supplier") or "").strip() or None
        else:
            ln["hours"] = _num(raw.get("hours"))
    except EtoError as e:
        errs.append(str(e))
    for f in ("qty_per", "unit_price", "setup_min", "run_min", "hours", "lead_days"):
        if isinstance(ln.get(f), float) and ln[f] < 0:
            errs.append("{} 不能是负数".format(f))
    if k in ("outside", "engineering") and not ln["desc"]:
        errs.append("要写说明")
    return ln, errs


def _missing(ln, eng_rate):
    """这一行缺什么（缺的为“未知”）"""
    k = ln["kind"]
    if k in ("material", "buyout"):
        return [x for x, f in (("用量", "qty_per"), ("单价", "unit_price")) if ln.get(f) is None]
    if k == "operation":
        m = [x for x, f in (("调整时间", "setup_min"), ("单件工时", "run_min")) if ln.get(f) is None]
        return m + ([] if ln.get("rate_h") is not None or ln.get("op") not in F.OPERATIONS else ["工位费率"])
    if k == "outside":
        return [] if ln.get("unit_price") is not None else ["单价"]
    return [x for x, ok in (("工时", ln.get("hours") is not None), ("设计费率", eng_rate is not None)) if not ok]


def compute(lines, qtys, cfg=None):
    """每个数量阶梯的成本与报价。lines：原始估算行；qtys：数量阶梯。

    材料、外购件、外协按件 × 数量；工序 = (调整 + 单件 × 数量) / 60 × 工位费率（调整一批一次）；
    设计 = 工时 × 设计费率（一次性）。成本 = 小计 × (1 + 风险预留)；报价 = 成本 × (1 + 加价率)。
    有未知项时对应金额为 None、不能报价。"""
    cfg = config() if cfg is None else cfg
    eng_rate = _num(cfg.get("engineering_rate_per_h"))
    cont = _num(cfg.get("contingency_pct"))
    markup = _num(cfg.get("markup_pct"))
    rows, errors, unknown = [], [], []
    for i, raw in enumerate(lines or []):
        ln, errs = norm_line(raw)
        ln["errors"] = errs
        ln["missing"] = [] if errs else _missing(ln, eng_rate)
        errors += ["第 {} 行：{}".format(i + 1, e) for e in errs]
        if ln["missing"]:
            unknown.append("第 {} 行（{} {}）缺{}".format(i + 1, KIND_ZH.get(ln.get("kind"), ""), ln.get("desc") or ln.get("op") or "",
                                                       "、".join(ln["missing"])))
        rows.append(ln)
    if cont is None:
        unknown.append("风险预留比例没有配置（工厂清单 eto.contingency_pct）")
    if markup is None:
        unknown.append("加价率没有配置（工厂清单 eto.markup_pct）")
    try:
        qs = sorted({int(q) for q in qtys})
    except (TypeError, ValueError):
        raise EtoError("数量阶梯要写整数")
    if not qs or qs[0] <= 0:
        raise EtoError("数量要大于 0")
    if len(qs) > MAX_BREAKS:
        raise EtoError("数量阶梯最多 {} 档".format(MAX_BREAKS))
    breaks = []
    for q in qs:
        cat = {"material": 0.0, "operations": 0.0, "outside": 0.0, "engineering": 0.0}
        bad = set()
        for ln in rows:
            k = ln.get("kind")
            key = {"material": "material", "buyout": "material", "operation": "operations", "outside": "outside",
                   "engineering": "engineering"}.get(k)
            if key is None or ln["errors"]:
                bad.add(key or "material")
                continue
            if ln["missing"]:
                bad.add(key)
                continue
            if k in ("material", "buyout"):
                cat[key] += ln["qty_per"] * ln["unit_price"] * q
            elif k == "operation":
                cat[key] += (ln["setup_min"] + ln["run_min"] * q) / 60 * ln["rate_h"]
            elif k == "outside":
                cat[key] += ln["unit_price"] * q
            else:
                cat[key] += ln["hours"] * eng_rate
        b = {"qty": q}
        for key, v in cat.items():
            b[key] = None if key in bad else round(v, 2)
        known = not bad and cont is not None and markup is not None
        sub = sum(cat.values())
        b["subtotal"] = round(sub, 2) if not bad else None
        b["contingency"] = round(sub * cont / 100, 2) if known else None
        b["cost"] = round(sub * (1 + cont / 100), 2) if known else None
        b["price"] = round(sub * (1 + cont / 100) * (1 + markup / 100), 2) if known else None
        b["unit_price"] = round(b["price"] / q, 2) if known else None
        b["margin_pct"] = round((b["price"] - b["cost"]) / b["price"] * 100, 1) if known and b["price"] else None
        breaks.append(b)
    return {"lines": rows, "breaks": breaks, "errors": errors, "unknown": unknown,
            "can_quote": bool(rows) and not errors and not unknown,
            "basis": {"contingency_pct": cont, "markup_pct": markup, "engineering_rate_per_h": eng_rate,
                      "example": bool(cfg.get("example"))}}


# ---------------------------------------------------------------- 起草
def _flat(code, qty, out):
    """多级展开：原材料、外购件累计用量；自制件、部件和产品本身各自的工序（件数累计）"""
    if code not in F.BOMS:
        out["leaf"][code] = out["leaf"].get(code, 0.0) + qty
        return
    out["make"][code] = out["make"].get(code, 0.0) + qty
    for c, q in F.BOMS[code][1]:
        _flat(c, q * qty, out)


def from_product(code):
    """照现有产品起草：材料、外购件按物料清单展开到底；工序按各级工艺路线（单件工时 × 每台件数）"""
    out = {"leaf": {}, "make": {}}
    _flat(code, 1.0, out)
    lines = []
    for c, q in sorted(out["leaf"].items(), key=lambda x: (F.ITEMS[x[0]][1], x[0])):
        lines.append({"kind": "material" if F.ITEMS[c][1] == "raw" else "buyout", "item_code": c, "desc": F.ITEMS[c][0], "qty_per": round(q, 4),
                      "source": "product:" + code})
    try:
        from sim.engine import OP_UNITS, SETUP_MIN
    except ImportError:  # pragma: no cover
        OP_UNITS, SETUP_MIN = {}, {}
    for c, n in out["make"].items():
        for op, mins in F.ROUTINGS[F.BOMS[c][0]]:
            unit = (OP_UNITS.get(op) or [None])[0]
            lines.append({"kind": "operation", "op": op, "desc": "{} {}".format(c, F.ITEMS[c][0]), "run_min": round(mins * n, 2),
                          "setup_min": SETUP_MIN.get(unit), "source": "product:" + code})
    return lines


PRODUCT_RE = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+")


def _ai_catalog():
    ops = list(F.OPERATIONS)
    items = [{"code": c, "name": v[0], "uom": v[2], "kind": v[1]} for c, v in F.ITEMS.items() if v[1] in ("raw", "buy")][:120]
    prods = [{"code": c, "name": F.ITEMS[c][0]} for c in F.BOMS if F.ITEMS.get(c, ("", ""))[1] == "fg"][:20]
    return ops, items, prods


TOOL = {"name": "submit_estimate", "description": "提交估算行（只给结构、用量和工时，不给价格）",
        "input_schema": {"type": "object", "required": ["lines"], "properties": {
            "note": {"type": "string", "description": "给估算员的说明：依据、假设、要客户确认的问题"},
            "lines": {"type": "array", "items": {"type": "object", "required": ["kind"], "properties": {
                "kind": {"type": "string", "enum": list(KINDS)},
                "desc": {"type": "string"}, "item_code": {"type": "string"}, "qty_per": {"type": "number"},
                "uom": {"type": "string"}, "op": {"type": "string"}, "setup_min": {"type": "number"},
                "run_min": {"type": "number"}, "hours": {"type": "number"}}}}}}}


def draft(llm, job):
    """起草估算行。返回 {"lines", "note", "source"}。AI 给的价格一律丢掉（价格只取主数据或估算员填）。"""
    req = job.get("requirement") or ""
    if llm is not None and getattr(llm, "available", lambda: False)():
        ops, items, prods = _ai_catalog()
        got = {}

        def call(name, args):
            if name == TOOL["name"]:
                got.update(args)
                return {"ok": True}
            return {"error": "没有这个工具"}
        system = (
            "你是机械厂的估算员助手，为一张按单设计（ETO）的询价起草估算行。只调用一次 submit_estimate 提交。\n"
            "规则：工序只能用本厂工序表里的名字（原样照抄）；材料、外购件能对上物料表的写 item_code，对不上的不写编号、写清说明；"
            "不要写任何价格或费率（系统从主数据取，取不到由估算员填）；run_min 是一件的加工分钟，setup_min 是一批的调整分钟；"
            "engineering 行写设计、出图、编程的工时；外协（outside）只写说明。拿不准的写进 note 请估算员核对，不要编数据。\n"
            "本厂工序表：{}\n物料表（原材料、外购件）：{}\n现有产品：{}".format(
                json.dumps(ops, ensure_ascii=False), json.dumps(items, ensure_ascii=False), json.dumps(prods, ensure_ascii=False)))
        user = "客户：{}\n名称：{}\n数量：{}\n交期：{}\n要求：\n{}\n\n客户图纸的文字（第 139f 段）：\n{}".format(
            job.get("customer"), job.get("title"), job.get("qty"), job.get("due_date") or "未定", req, job.get("drawing_text") or "（没有）")
        llm.run(system, [{"role": "user", "content": user}], [TOOL], call, max_turns=3)
        if got.get("lines") is not None:
            lines = []
            for x in got["lines"][:80]:
                x = {k: v for k, v in dict(x).items() if k not in ("unit_price", "rate_h", "price")}
                x["source"] = "ai"
                lines.append(x)
            return {"lines": lines, "note": str(got.get("note") or "")[:2000], "source": "ai:" + getattr(llm, "name", "")}
    for code in PRODUCT_RE.findall(req.upper()):
        if code in F.BOMS:
            return {"lines": from_product(code), "source": "rules",
                    "note": "没有可用的 AI 模型：照现有产品 {} 的物料清单和工艺起草，请按客户要求改动的部分逐行改。".format(code)}
    return {"lines": [], "source": "rules",
            "note": "没有可用的 AI 模型：请手工填估算行；要求里写上参照的现有产品编号（如 WQR-105），可照它起草。"}


# ---------------------------------------------------------------- 作业与估算（数据库）
def _job_out(r):
    if not r:
        return None
    d = dict(r)
    for k in ("due_date",):
        d[k] = d[k].isoformat() if d.get(k) else None
    d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
    return d


def new_job(db, mode, user, customer, title, requirement, qty, qty_breaks=None, due_date=None, cfg=None):
    cfg = config() if cfg is None else cfg
    customer, title = str(customer or "").strip(), str(title or "").strip()
    if not customer or not title:
        raise EtoError("客户和名称必填")
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise EtoError("数量要写整数")
    if qty <= 0:
        raise EtoError("数量要大于 0")
    breaks = sorted({qty} | {int(x) for x in (qty_breaks or []) if str(x).strip()})
    if len(breaks) > MAX_BREAKS or breaks[0] <= 0:
        raise EtoError("数量阶梯最多 {} 档、都要大于 0".format(MAX_BREAKS))
    due = None
    if due_date:
        try:
            due = dt.date.fromisoformat(str(due_date)[:10])
        except ValueError:
            raise EtoError("交期格式要写 YYYY-MM-DD")
    prefix = "{}{}-".format(cfg.get("prefix") or "JOB-", dt.date.today().year)
    for _ in range(5):
        n = db.one("select count(*) as n from eto_job where mode=%s and job_no like %s", (mode, prefix + "%"))["n"]
        job_no = "{}{:04d}".format(prefix, n + 1)
        r = db.one("insert into eto_job (mode, job_no, customer, title, requirement, qty, qty_breaks, due_date, created_by) "
                   "values (%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing returning *",
                   (mode, job_no, customer, title[:140], str(requirement or "")[:8000], qty, json.dumps(breaks), due, user))
        if r:
            return _job_out(r)
    raise EtoError("作业号冲突，请再试一次")


def jobs(db, mode):
    pend = {r["j"] for r in db.q("select preview->'job'->>'job_no' as j from ai_proposal where action='eto_quote' and mode=%s "
                                   "and status in ('pending','confirmed')", (mode,))}
    out = []
    for r in db.q("select * from eto_job where mode=%s order by created_at desc", (mode,)):
        j = _job_out(r)
        if j["job_no"] in pend:
            j["status"] = "quoting"
        out.append(j)
    return out


def pending_quote(db, mode, job_no):
    """还没执行完的报价提议（等人确认，或已确认、桥接正在写 ERPNext）"""
    r = db.one("select proposal_id from ai_proposal where action='eto_quote' and mode=%s and status in ('pending','confirmed') "
               "and preview->'job'->>'job_no'=%s order by created_at desc limit 1", (mode, job_no))
    return r["proposal_id"] if r else None


def job(db, mode, job_no):
    j = _job_out(db.one("select * from eto_job where mode=%s and job_no=%s", (mode, job_no)))
    if j:
        j["pending_proposal"] = pending_quote(db, mode, job_no)
        if j["pending_proposal"]:
            j["status"] = "quoting"
    return j


def latest(db, mode, job_no):
    r = db.one("select * from eto_estimate where mode=%s and job_no=%s order by rev desc limit 1", (mode, job_no))
    if r:
        r = dict(r)
        r["created_at"] = r["created_at"].isoformat()
    return r


def revisions(db, mode, job_no):
    return [{"rev": r["rev"], "source": r["source"], "created_by": r["created_by"], "created_at": r["created_at"].isoformat()}
            for r in db.q("select rev, source, created_by, created_at from eto_estimate where mode=%s and job_no=%s order by rev",
                          (mode, job_no))]


def save_estimate(db, mode, job_no, lines, note, user, source="human"):
    """存估算：当前版本还没报出去就覆盖它；已报价（冻结）就出新版本。返回版本号。"""
    j = job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    if j["status"] == "quoting":
        raise EtoError("报价提议还在等确认，确认或否决之后再改")
    if not isinstance(lines, list) or len(lines) > 200:
        raise EtoError("估算行要是一个列表（最多 200 行）")
    cur = latest(db, mode, job_no)
    frozen = j.get("quoted_rev") or 0
    rev = cur["rev"] if cur and cur["rev"] > frozen else (cur["rev"] + 1 if cur else 1)
    db.x("insert into eto_estimate (mode, job_no, rev, lines, note, source, created_by) values (%s,%s,%s,%s,%s,%s,%s) "
         "on conflict (mode, job_no, rev) do update set lines=excluded.lines, note=excluded.note, source=excluded.source, "
         "created_by=excluded.created_by, created_at=now()",
         (mode, job_no, rev, json.dumps(lines, ensure_ascii=False), str(note or "")[:2000], source, user))
    if j["status"] == "quoted":
        db.x("update eto_job set status='estimating' where mode=%s and job_no=%s", (mode, job_no))
    return rev


def detail(db, mode, job_no, cfg=None):
    j = job(db, mode, job_no)
    if not j:
        return None
    est = latest(db, mode, job_no)
    lines = est["lines"] if est else []
    out = {"job": j, "estimate": est, "revisions": revisions(db, mode, job_no),
           "result": compute(lines, j["qty_breaks"] or [j["qty"]], cfg), "config": config() if cfg is None else cfg}
    out["frozen"] = bool(est and j.get("quoted_rev") and est["rev"] <= j["quoted_rev"])
    return out


def quote_preview(db, mode, job_no, cfg=None):
    """发报价的提议内容：数量阶梯里客户要的那档报在报价单上，其余各档写进条款；有未知或错误项抛 EtoError"""
    cfg = config() if cfg is None else cfg
    d = detail(db, mode, job_no, cfg)
    if not d:
        raise KeyError(job_no)
    j, res = d["job"], d["result"]
    if j["status"] == "quoting":
        raise EtoError("这张作业已经有一份报价提议在等确认")
    if d["frozen"]:
        raise EtoError("第 {} 版已经报过价；要改价先改估算（会出新版本）".format(j["quoted_rev"]))
    if not res["can_quote"]:
        raise EtoError("还不能报价：" + "；".join((res["errors"] + res["unknown"])[:6]) if (res["errors"] or res["unknown"])
                       else "还不能报价：没有估算行")
    main = next(b for b in res["breaks"] if b["qty"] == j["qty"])
    today = dt.date.today()
    valid = today + dt.timedelta(days=int(cfg.get("valid_days") or 30))
    terms = ["作业号 {}；第 {} 版估算。".format(job_no, d["estimate"]["rev"]),
             "数量阶梯（单价）：" + "；".join("{} 件 {:.2f}".format(b["qty"], b["unit_price"]) for b in res["breaks"])]
    ms = [m for m in cfg.get("milestones") or [] if m.get("pct")]
    if ms:
        terms.append("付款：" + "；".join("{} {:g}%".format(m["name"], m["pct"]) for m in ms))
    if cfg.get("example"):
        terms.append("（演示工厂，费率与比例为示例值）")
    return {
        "job": {"job_no": job_no, "title": j["title"], "customer": j["customer"], "qty": j["qty"], "due_date": j["due_date"],
                "rev": d["estimate"]["rev"]},
        "item": {"item_code": job_no, "item_name": j["title"][:140], "item_group": F.KIND_GROUP["fg"], "stock_uom": "Nos",
                 "description": (j["requirement"] or j["title"])[:2000]},
        "project": {"project_name": job_no, "customer": j["customer"], "expected_end_date": j["due_date"],
                    "notes": "{} · {}".format(j["title"], j["customer"])},
        "quotation": {"party": j["customer"], "transaction_date": today.isoformat(), "valid_till": valid.isoformat(),
                      "qty": j["qty"], "rate": main["unit_price"], "amount": main["price"], "terms": "\n".join(terms)},
        "breaks": res["breaks"],
        "basis": res["basis"],
    }


def project_of(j):
    """作业在 ERPNext 里的项目名：真 ERPNext 按编号规则命名（如 PROJ-0001），不一定等于作业号；报价执行时记下"""
    return (j or {}).get("project") or (j or {}).get("job_no")


def on_proposal_done(db, action, preview, mode):
    """桥接建好 Project、物料、报价单后：作业记为已报价，冻结这一版估算"""
    if action != "eto_quote":
        return
    pv = preview if isinstance(preview, dict) else json.loads(preview)
    jn = pv["job"]["job_no"]
    r = db.one("select result from ai_proposal where action='eto_quote' and mode=%s and status='executed' "
               "and preview->'job'->>'job_no'=%s order by decided_at desc nulls last limit 1", (mode, jn))
    created = ((r or {}).get("result") or {}).get("created") or []
    name = {dt_: n for dt_, n in created}
    db.x("update eto_job set status='quoted', quoted_rev=%s, project=coalesce(%s, project), quotation=coalesce(%s, quotation) "
         "where mode=%s and job_no=%s", (pv["job"]["rev"], name.get("Project"), name.get("Quotation"), mode, jn))


def reset(db, mode):
    db.x("delete from eto_estimate where mode=%s", (mode,))
    db.x("delete from eto_job where mode=%s", (mode,))
