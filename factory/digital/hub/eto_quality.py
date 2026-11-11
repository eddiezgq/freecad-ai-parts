# -*- coding: utf-8 -*-
"""按单设计（ETO，第 139 轮 139f）：客户图纸、检验计划、首件与终检、不合格品、发货关口、合格证。

- 客户图纸（附件）：上传到平台的文件库（stored_file），PDF 抽出文字，给 AI 起草估算和检验项时读；
- 检验计划：这一单要检的特性（编号、名称、哪个件、首件 / 终检、名义值、上下限、单位、方法），按版本存，**人批准后冻结**；
  AI 从客户要求和图纸文字起草（标“AI 读出，要核对”）；没有模型时，从“复制为新件”的原件已有的检验模板起草；
- 检验记录：测量值逐项按上下限判定（纯函数）：都在限内合格，有超差不合格，缺值“未知”（不算合格）；
  记录保存后不能改，要改只能作废并写原因、再记一条；不合格自动开不合格品单（ncr，走原来的处置：返修、报废、让步接收）；
  每条记录经提议（数据录入，自动确认）写进 ERPNext 质量检验单（挂工单的作业卡）；
- 发货关口（纯函数判断）：作业工单完工够数、检验计划已批准、本单每张专用件工单首件合格、终检合格（含让步接收）件数够、没有未处置的不合格品单；
  都满足才能生成发货提议（ERPNext 发货单）；
- 合格证：从检验记录生成（网页、可打印）。
"""
import datetime as dt
import io
import json
import re

from factory import data as F
from hub import eto as E
from hub import eto_design as ED

SCHEMA = """
alter table eto_job add column if not exists delivery_note text;
alter table eto_job add column if not exists shipped_at timestamptz;
create table if not exists eto_file (
    id          bigserial primary key,
    mode        text not null,
    job_no      text not null,
    sha256      text not null,
    name        text not null,
    mime        text,
    size        integer,
    text        text,
    uploaded_by text,
    created_at  timestamptz not null default now()
);
create table if not exists eto_qplan (
    mode        text not null,
    job_no      text not null,
    rev         integer not null,
    chars       jsonb not null,
    status      text not null default 'draft',      -- draft / approved
    created_by  text,
    created_at  timestamptz not null default now(),
    approved_by text,
    approved_at timestamptz,
    primary key (mode, job_no, rev)
);
create table if not exists eto_insp (
    id          bigserial primary key,
    mode        text not null,
    job_no      text not null,
    kind        text not null,                      -- fai 首件 / final 终检
    work_order  text not null,
    item        text not null,
    piece       integer not null,
    plan_rev    integer not null,
    readings    jsonb not null,
    result      text not null,                      -- pass / fail / unknown
    inspector   text,
    created_at  timestamptz not null default now(),
    ncr_id      text,
    proposal_id text,
    voided_at   timestamptz,
    voided_by   text,
    void_reason text
);
create or replace function eto_insp_lock() returns trigger language plpgsql as $$
begin
  if tg_op = 'UPDATE' and old.proposal_id is null and new.proposal_id is not null and new.ncr_id is not distinct from old.ncr_id
     and new.voided_at is not distinct from old.voided_at then
    return new;
  end if;
  if tg_op = 'DELETE' then
    if current_setting('wq.allow_reset', true) = 'on' then return old; end if;
    raise exception '检验记录不能删除，只能作废';
  end if;
  if new.readings is distinct from old.readings or new.result is distinct from old.result or new.piece is distinct from old.piece
     or new.kind is distinct from old.kind or new.work_order is distinct from old.work_order or new.inspector is distinct from old.inspector
     or (old.voided_at is not null and new.voided_at is distinct from old.voided_at) then
    raise exception '检验记录保存后不能改，只能作废并写原因';
  end if;
  return new;
end $$;
drop trigger if exists eto_insp_lock on eto_insp;
create trigger eto_insp_lock before update or delete on eto_insp for each row execute function eto_insp_lock();
"""
KINDS = ("fai", "final", "both")
CODE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
TEXT_LIMIT = 20000


def init(db):
    db.x(SCHEMA)


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


# ---------------------------------------------------------------- 客户图纸
def pdf_text(data):
    try:
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)[:TEXT_LIMIT]
    except Exception:  # noqa: BLE001 —— 扫描件、加密件抽不出文字：照样存，只是 AI 读不到
        return ""


def add_file(db, mode, job_no, sha, name, mime, size, text, who):
    if not E.job(db, mode, job_no):
        raise KeyError(job_no)
    db.x("insert into eto_file (mode, job_no, sha256, name, mime, size, text, uploaded_by) values (%s,%s,%s,%s,%s,%s,%s,%s)",
         (mode, job_no, sha, str(name)[:200], mime, size, text or "", who))


def files(db, mode, job_no):
    return [dict(r, created_at=r["created_at"].isoformat(), has_text=bool(r["text"]), text=None)
            for r in db.q("select id, sha256, name, mime, size, text, uploaded_by, created_at from eto_file where mode=%s and job_no=%s order by id",
                          (mode, job_no))]


def drawing_text(db, mode, job_no):
    return "\n\n".join("【{}】\n{}".format(r["name"], r["text"]) for r in
                       db.q("select name, text from eto_file where mode=%s and job_no=%s and text<>'' order by id", (mode, job_no)))[:TEXT_LIMIT]


# ---------------------------------------------------------------- 检验计划（纯函数部分）
def job_items(db, mode, job_no):
    """可以检的件：作业本身 + 发布设计里的本单新自制件"""
    rel = ED.released(db, mode, job_no) or ED.latest(db, mode, job_no)
    return [job_no] + [i["code"] for i in ((rel or {}).get("spec") or {}).get("items", []) if i.get("kind") == "make"]


def check_plan(chars, items, job_no):
    errs, seen = [], set()
    if not isinstance(chars, list) or not chars:
        return ["检验计划至少一项"]
    for i, c in enumerate(chars):
        at = "第 {} 项".format(i + 1)
        if not isinstance(c, dict):
            errs.append(at + "：格式不对")
            continue
        code = str(c.get("code") or "")
        if not CODE.match(code):
            errs.append("{}：编号用小写字母、数字、下划线，字母开头".format(at))
        elif code in seen:
            errs.append("{}：编号 {} 重复".format(at, code))
        seen.add(code)
        if not str(c.get("name") or "").strip():
            errs.append(at + "：要写名称")
        if c.get("item") not in items:
            errs.append("{}：件 {} 不是这一单的（可选：{}）".format(at, c.get("item"), "、".join(items)))
        if c.get("kind") not in KINDS:
            errs.append(at + "：要写首件 / 终检 / 两者")
        lo, hi, nom = _num(c.get("lo")), _num(c.get("hi")), _num(c.get("nominal"))
        if lo is None or hi is None:
            errs.append(at + "：上下限都要写（数字）")
        elif not lo <= hi or (nom is not None and not lo <= nom <= hi):
            errs.append(at + "：要 下限 ≤ 名义 ≤ 上限")
    if not errs and not any(c["item"] == job_no and c["kind"] in ("final", "both") for c in chars):
        errs.append("作业 {} 本身至少要有一项终检".format(job_no))
    return errs


def judge(chars, readings, kind, item):
    """一件的判定：返回 (结果, 逐项)。只看这个件、这类检验的特性"""
    out, any_fail, any_unknown = [], False, False
    for c in chars:
        if c["item"] != item or c["kind"] not in (kind, "both"):
            continue
        v = _num((readings or {}).get(c["code"]))
        if v is None:
            r = "unknown"
            any_unknown = True
        else:
            r = "pass" if float(c["lo"]) <= v <= float(c["hi"]) else "fail"
            any_fail = any_fail or r == "fail"
        out.append({"code": c["code"], "name": c["name"], "value": v, "lo": float(c["lo"]), "hi": float(c["hi"]),
                    "unit": c.get("unit") or "", "result": r})
    if not out:
        return "unknown", out
    return ("fail" if any_fail else ("unknown" if any_unknown else "pass")), out


def plan_from_templates(spec, job_no):
    """没有模型时：“复制为新件”的原件如有检验模板（如输出轴的零件检验），照抄它的检验项（数值来自本厂的模板，不是编的）"""
    tmpls = getattr(F, "INSPECTION_TEMPLATES", None) or {}
    if not tmpls and hasattr(F, "inspection_templates"):
        tmpls = F.inspection_templates()
    out = []
    for it in (spec or {}).get("items") or []:
        src = it.get("from")
        t = F.ITEMS.get(src or "", (None,) * 6)[5]
        for k, p in enumerate((tmpls.get(t) or []) if t else []):
            if p.get("numeric") and p.get("min") is not None and p.get("max") is not None:
                out.append({"code": "{}_{}".format(re.sub(r"[^a-z0-9]", "", it["code"].lower().split("-")[-1]) or "p", k + 1)[:32],
                            "name": p["parameter"], "item": it["code"], "kind": "both", "lo": p["min"], "hi": p["max"],
                            "nominal": round((p["min"] + p["max"]) / 2, 4), "unit": "", "method": "", "source": "template:" + t})
    return out


PLAN_TOOL = {"name": "submit_plan", "description": "提交检验项（只写图纸或要求里写明的尺寸和公差）",
             "input_schema": {"type": "object", "required": ["chars"], "properties": {
                 "note": {"type": "string"},
                 "chars": {"type": "array", "items": {"type": "object", "properties": {
                     "code": {"type": "string"}, "name": {"type": "string"}, "item": {"type": "string"},
                     "kind": {"type": "string", "enum": list(KINDS)}, "nominal": {"type": "number"}, "lo": {"type": "number"},
                     "hi": {"type": "number"}, "unit": {"type": "string"}, "method": {"type": "string"}}}}}}}


def draft_plan(llm, job, items, spec, text):
    if llm is not None and getattr(llm, "available", lambda: False)():
        got = {}

        def call(name, args):
            if name == PLAN_TOOL["name"]:
                got.update(args)
                return {"ok": True}
            return {"error": "没有这个工具"}
        system = ("你是机械厂质量工程师，为一张按单设计的订单起草检验计划。只调用一次 submit_plan。规则：只写客户要求或图纸文字里**明确写了**"
                  "尺寸和公差的特性（名义值、上下限照原文换算成数字），没写公差的不要编，写进 note 请人补；item 只能是：{}；"
                  "kind：首件 fai、终检 final、两者 both；code 用小写字母数字下划线。").format("、".join(items))
        user = "作业：{} {}\n客户要求：\n{}\n\n图纸文字：\n{}".format(job["job_no"], job["title"], job.get("requirement") or "", text or "（没有）")
        llm.run(system, [{"role": "user", "content": user}], [PLAN_TOOL], call, max_turns=3)
        if got.get("chars") is not None:
            return {"chars": [dict(c, source="ai") for c in got["chars"][:60]], "note": str(got.get("note") or "")[:2000],
                    "source": "ai:" + getattr(llm, "name", "")}
    chars = plan_from_templates(spec, job["job_no"])
    return {"chars": chars, "source": "rules",
            "note": "没有可用的 AI 模型：" + ("照原件的检验模板起草了 {} 项，" .format(len(chars)) if chars else "") +
                    "请按客户图纸补齐关键尺寸（名义值、上下限），作业本身至少一项终检。"}


# ---------------------------------------------------------------- 检验计划（数据库）
def _plan_row(r):
    if not r:
        return None
    d = dict(r)
    for k in ("created_at", "approved_at"):
        d[k] = d[k].isoformat() if d.get(k) else None
    return d


def plan_latest(db, mode, job_no):
    return _plan_row(db.one("select * from eto_qplan where mode=%s and job_no=%s order by rev desc limit 1", (mode, job_no)))


def plan_approved(db, mode, job_no):
    return _plan_row(db.one("select * from eto_qplan where mode=%s and job_no=%s and status='approved' order by rev desc limit 1",
                            (mode, job_no)))


def save_plan(db, mode, job_no, chars, who):
    if not E.job(db, mode, job_no):
        raise KeyError(job_no)
    if not isinstance(chars, list) or len(chars) > 100:
        raise E.EtoError("检验项要是列表（最多 100 项）")
    cur = plan_latest(db, mode, job_no)
    rev = cur["rev"] if cur and cur["status"] == "draft" else (cur["rev"] + 1 if cur else 1)
    db.x("insert into eto_qplan (mode, job_no, rev, chars, created_by) values (%s,%s,%s,%s,%s) "
         "on conflict (mode, job_no, rev) do update set chars=excluded.chars, created_by=excluded.created_by, created_at=now()",
         (mode, job_no, rev, json.dumps(chars, ensure_ascii=False), who))
    return rev


def approve_plan(db, mode, job_no, who):
    """批准检验计划（质量人员）：检查通过才批准；批准的那一版冻结，再改出新版本"""
    cur = plan_latest(db, mode, job_no)
    if not cur:
        raise E.EtoError("还没有检验计划")
    if cur["status"] == "approved":
        raise E.EtoError("第 {} 版已经批准".format(cur["rev"]))
    errs = check_plan(cur["chars"], job_items(db, mode, job_no), job_no)
    if errs:
        raise E.EtoError("检验计划没通过检查：" + "；".join(errs[:6]))
    if cur["created_by"] == who:
        raise E.EtoError("起草人不能自己批准，请另一位质量人员批准")
    db.x("update eto_qplan set status='approved', approved_by=%s, approved_at=now() where mode=%s and job_no=%s and rev=%s",
         (who, mode, job_no, cur["rev"]))
    return cur["rev"]


# ---------------------------------------------------------------- 检验记录
def record(db, mode, job_no, kind, work_order, piece, readings, who, wos):
    """记一件的检验。wos：作业的工单（eto_exec.work_orders 的结果）。返回记录（含是否开了不合格品单）"""
    if kind not in ("fai", "final"):
        raise E.EtoError("检验类别只能是首件或终检")
    plan = plan_approved(db, mode, job_no)
    if not plan:
        raise E.EtoError("检验计划还没批准，不能记检验")
    w = next((x for x in wos if x["name"] == work_order), None)
    if not w:
        raise E.EtoError("工单 {} 不是这个作业的".format(work_order))
    if kind == "final" and w["item"] != job_no:
        raise E.EtoError("终检只检作业本身（{}）".format(job_no))
    try:
        piece = int(piece)
    except (TypeError, ValueError):
        raise E.EtoError("件号要写整数")
    if not 1 <= piece <= int(w["qty"]):
        raise E.EtoError("件号 1–{:g}".format(w["qty"]))
    if kind == "fai" and piece != 1:
        raise E.EtoError("首件检验只检第 1 件")
    result, rows = judge(plan["chars"], readings, kind, w["item"])
    if not rows:
        raise E.EtoError("检验计划里没有 {} 的{}项".format(w["item"], "首件" if kind == "fai" else "终检"))
    r = db.one("insert into eto_insp (mode, job_no, kind, work_order, item, piece, plan_rev, readings, result, inspector) "
               "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id, created_at",
               (mode, job_no, kind, work_order, w["item"], piece, plan["rev"], json.dumps(rows, ensure_ascii=False), result, who))
    ncr = None
    if result == "fail":
        n = db.one("select count(*) as n from ncr")["n"] + 1
        ncr = "NCR-{:04d}".format(n)
        db.x("insert into ncr (ncr_id, created_at, part_serial, item, work_order, detail, mode) values (%s, now(), %s, %s, %s, %s, %s)",
             (ncr, "{}#{}".format(work_order, piece), w["item"], work_order,
              json.dumps({"job_no": job_no, "kind": kind, "inspection_id": r["id"],
                          "failed": [x for x in rows if x["result"] == "fail"]}, ensure_ascii=False), mode))
        db.x("update eto_insp set ncr_id=%s where id=%s", (ncr, r["id"]))
    return {"id": r["id"], "result": result, "readings": rows, "ncr_id": ncr, "plan_rev": plan["rev"]}


def void(db, mode, insp_id, who, reason):
    reason = str(reason or "").strip()
    if len(reason) < 4:
        raise E.EtoError("作废要写原因")
    n = db.x("update eto_insp set voided_at=now(), voided_by=%s, void_reason=%s where id=%s and mode=%s and voided_at is null",
             (who, reason[:500], insp_id, mode))
    if not n:
        raise E.EtoError("没有这条记录，或已经作废")


def records(db, mode, job_no):
    return [dict(r, created_at=r["created_at"].isoformat(), voided_at=r["voided_at"].isoformat() if r["voided_at"] else None)
            for r in db.q("select i.*, n.status as ncr_status from eto_insp i left join ncr n on n.ncr_id=i.ncr_id "
                          "where i.mode=%s and i.job_no=%s order by i.id", (mode, job_no))]


# ---------------------------------------------------------------- 发货关口与合格证
def ship_check(job, wos, plan, recs):
    """纯函数：发货前的关口，返回挡住发货的原因（空 = 可以发）"""
    jn, qty = job["job_no"], float(job["qty"])
    why = []
    if job.get("shipped"):
        why.append("已经发过货")
    if not plan:
        why.append("检验计划还没批准")
    top = [w for w in wos if w["item"] == jn]
    made = sum(w["produced"] for w in top)
    if made < qty:
        why.append("作业 {} 完工 {:g} / {:g} 件".format(jn, made, qty))
    live = [r for r in recs if not r.get("voided_at")]
    for w in wos:
        if w["item"] != jn and w.get("own"):
            fai = [r for r in live if r["kind"] == "fai" and r["work_order"] == w["name"]]
            if not fai or fai[-1]["result"] != "pass":
                why.append("{}（{}）首件检验{}".format(w["name"], w["item"], "不合格" if fai and fai[-1]["result"] == "fail" else "还没合格"))
    ok = set()
    for r in live:
        if r["kind"] == "final" and (r["result"] == "pass" or (r["result"] == "fail" and r.get("ncr_status") == "use_as_is")):
            ok.add((r["work_order"], r["piece"]))
    if len(ok) < qty:
        why.append("终检合格 {} / {:g} 件".format(len(ok), qty))
    opened = sorted({r["ncr_id"] for r in live if r.get("ncr_id") and r.get("ncr_status") == "open"})
    if opened:
        why.append("不合格品单还没处置：" + "、".join(opened))
    return why


def certificate(job, plan, recs, design):
    """合格证：终检合格（含让步接收）的件，逐项实测值"""
    live = [r for r in recs if not r.get("voided_at") and r["kind"] == "final" and
            (r["result"] == "pass" or (r["result"] == "fail" and r.get("ncr_status") == "use_as_is"))]
    last = {}
    for r in live:
        last[(r["work_order"], r["piece"])] = r
    return {"job_no": job["job_no"], "title": job["title"], "customer": job["customer"], "sales_order": job.get("sales_order"),
            "qty": job["qty"], "design_rev": (design or {}).get("rev"), "fingerprint": (design or {}).get("fingerprint"),
            "plan_rev": (plan or {}).get("rev"), "plan_approved_by": (plan or {}).get("approved_by"),
            "pieces": [{"work_order": k[0], "piece": k[1], "inspector": r["inspector"], "at": r["created_at"], "result": r["result"],
                        "concession": r["result"] == "fail", "ncr_id": r.get("ncr_id"), "readings": r["readings"]}
                       for k, r in sorted(last.items())],
            "issued_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


def ship_preview(db, mode, job_no, wos, today=None):
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    why = ship_check(dict(j, shipped=bool(j.get("delivery_note"))), wos, plan_approved(db, mode, job_no), records(db, mode, job_no))
    if why:
        raise E.EtoError("还不能发货：" + "；".join(why))
    return {"job": {"job_no": job_no, "title": j["title"], "customer": j["customer"], "project": E.project_of(j)},
            "sales_order": j["sales_order"], "qty": j["qty"], "day": (today or dt.date.today()).isoformat()}


def inspection_preview(job_no, rec, w, who, ops):
    """检验记录 → ERPNext 质量检验单的提议内容（挂工单最后一道工序的作业卡；检验工序优先）"""
    op = next((o for o in reversed(ops) if o in getattr(F, "INSPECTION_OPS", set())), ops[-1] if ops else None)
    return {"job": {"job_no": job_no}, "inspection_id": rec["id"], "kind": rec["kind"], "work_order": w["name"], "item": w["item"],
            "piece": rec["piece"], "operation": op, "result": rec["result"], "inspector": who, "day": dt.date.today().isoformat(),
            "readings": [{"spec": "{} ({})".format(r["name"], r["unit"]) if r["unit"] else r["name"], "lo": r["lo"], "hi": r["hi"],
                          "value": r["value"], "result": r["result"]} for r in rec["readings"]]}


def on_proposal_done(db, action, preview, mode):
    pv = preview if isinstance(preview, dict) else json.loads(preview)
    if action == "eto_ship":
        jn = pv["job"]["job_no"]
        r = db.one("select result from ai_proposal where action='eto_ship' and mode=%s and status='executed' and preview->'job'->>'job_no'=%s "
                   "order by decided_at desc nulls last limit 1", (mode, jn))
        dn = next((n for d_, n in ((r or {}).get("result") or {}).get("created") or [] if d_ == "Delivery Note"), None)
        db.x("update eto_job set delivery_note=%s, shipped_at=now(), status='shipped' where mode=%s and job_no=%s", (dn, mode, jn))
    elif action == "eto_inspection":
        r = db.one("select proposal_id from ai_proposal where action='eto_inspection' and mode=%s and (preview->>'inspection_id')::bigint=%s "
                   "order by created_at desc limit 1", (mode, pv["inspection_id"]))
        if r:
            db.x("update eto_insp set proposal_id=%s where id=%s and proposal_id is null", (r["proposal_id"], pv["inspection_id"]))


def reset(db, mode):
    """教学情景重载时清空（检验记录平时删不掉，这里在一个事务里打开开关）"""
    with db.conn().cursor() as cur:
        cur.execute("begin")
        cur.execute("set local wq.allow_reset = 'on'")
        cur.execute("delete from eto_insp where mode=%s", (mode,))
        cur.execute("commit")
    db.x("delete from eto_qplan where mode=%s", (mode,))
    db.x("delete from eto_file where mode=%s", (mode,))
