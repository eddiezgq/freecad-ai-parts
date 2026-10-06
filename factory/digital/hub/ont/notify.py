# -*- coding: utf-8 -*-
"""主动提醒（第 17 轮 D 期 D6）：通知中心、订阅、邮件、企业微信 / 钉钉 / 飞书群机器人、防打扰。

- 通知发给“某个人”（@名字）或“某个角色”（role:manager）；站内铃铛按订阅（领域、严重程度）过滤。
- 来源：新的 / 升级 / 重开的异常（规则库每 20 秒一轮）、动作（待我批准、被批准 / 驳回 / 执行失败）、日报周报、
  “严重”异常 30 分钟没人确认再提醒厂长一次。
- 同一异常只发一次，升级再发（由异常生命周期保证：检测只在新开、升级、重开时返回提醒）。
- 渠道：站内（总有）；邮件（服务器配了 WQ_SMTP_* 才有，发到订阅里填的邮箱）；群机器人（厂长在“通知设置”贴地址，可按领域分群）。
- 教学模式只发站内通知；免打扰时段只挡邮件和群消息，“严重”的照发。"""
import base64
import datetime as dt
import hashlib
import json
import logging
import os
import smtplib
import ssl
import threading
from email.message import EmailMessage

import httpx
from psycopg.types.json import Jsonb

log = logging.getLogger("notify")

SCHEMA = """
create table if not exists notification (
    id         bigserial primary key,
    mode       text not null,
    target     text not null,                 -- @名字 / role:角色 / *
    kind       text not null,                 -- anomaly / escalate / action / report / test
    ref        text,
    domain     text,
    severity   text,
    title      text not null,
    body       text,
    url        text,
    owner_role text,                          -- 异常的负责角色：负责的人不受订阅过滤
    created_at timestamptz not null default now(),
    sent       jsonb
);
create index if not exists notification_ts on notification (mode, created_at);
create table if not exists notify_read (
    "user"  text not null,
    id      bigint not null,
    primary key ("user", id)
);
create table if not exists notify_sub (
    "user"   text not null,
    mode     text not null,
    role     text,
    domains  jsonb,                           -- null = 按角色默认
    min_severity text,
    email    text,
    channels jsonb,                           -- {"email": true}
    quiet    jsonb,                           -- {"from": "22:00", "to": "07:00"}
    updated_at timestamptz not null default now(),
    primary key ("user", mode)
);
create table if not exists notify_channel (
    id         bigserial primary key,
    mode       text not null,
    kind       text not null,                 -- wecom / dingtalk / feishu
    name       text,
    domain     text,                          -- 空 = 全部领域
    min_severity text not null default 'warn',
    url_enc    text not null,
    tail       text,
    created_by text,
    created_at timestamptz not null default now()
);
"""
RANK = {"info": 0, "warn": 1, "critical": 2}
SEV_LABEL = {"info": "提示", "warn": "警告", "critical": "严重"}
# 按角色的默认订阅（D6）：厂长全部“警告”以上；计划员交付、物料；设备员设备；质检质量
ROLE_DEFAULT = {
    "manager": {"domains": None, "min_severity": "warn"},
    "approver": {"domains": None, "min_severity": "critical"},
    "planner": {"domains": ["sales", "planning", "supply", "warehouse", "core"], "min_severity": "warn"},
    "engineer": {"domains": ["maintenance", "production", "core"], "min_severity": "warn"},
    "operator": {"domains": ["production", "maintenance"], "min_severity": "critical"},
    "quality": {"domains": ["quality", "service", "core"], "min_severity": "warn"},
    "sales": {"domains": ["sales", "customer", "service"], "min_severity": "warn"},
}
CHANNEL_KINDS = {"wecom": "企业微信群机器人", "dingtalk": "钉钉群机器人", "feishu": "飞书群机器人"}
ESCALATE_MIN = 30
_lock = threading.Lock()


def init(db):
    db.x(SCHEMA)


# ---------------------------------------------------------------- 地址加密（群机器人地址里带密钥）
def _key():
    return hashlib.sha256(("wq-notify|" + os.environ.get("WQ_SECRET", "dev")).encode()).digest()


def enc(s):
    k = _key()
    b = s.encode()
    return base64.urlsafe_b64encode(bytes(c ^ k[i % len(k)] for i, c in enumerate(b))).decode()


def dec(s):
    k = _key()
    b = base64.urlsafe_b64decode(s.encode())
    return bytes(c ^ k[i % len(k)] for i, c in enumerate(b)).decode()


# ---------------------------------------------------------------- 订阅
def sub_of(db, user, mode, role):
    r = db.one('select * from notify_sub where "user"=%s and mode=%s', (user, mode))
    d = ROLE_DEFAULT.get(role or "", {"domains": None, "min_severity": "warn"})
    out = {"domains": d["domains"], "min_severity": d["min_severity"], "email": None, "channels": {"email": False},
           "quiet": None, "custom": False}
    if r:
        out.update({k: r[k] for k in ("email", "quiet") if r[k] is not None})
        if r["domains"] is not None:
            out["domains"] = None if r["domains"] == ["*"] else r["domains"]
        if r["min_severity"]:
            out["min_severity"] = r["min_severity"]
        if r["channels"]:
            out["channels"] = r["channels"]
        out["custom"] = True
    return out


def save_sub(db, user, mode, role, body):
    sev = body.get("min_severity") or "warn"
    if sev not in RANK:
        raise ValueError("严重程度只能是 info / warn / critical")
    email = (body.get("email") or "").strip() or None
    if email and ("@" not in email or len(email) > 200):
        raise ValueError("邮箱格式不对")
    q = body.get("quiet")
    if q and not (isinstance(q, dict) and _hm(q.get("from")) is not None and _hm(q.get("to")) is not None):
        raise ValueError("免打扰时段格式：{\"from\": \"22:00\", \"to\": \"07:00\"}")
    db.x('insert into notify_sub ("user", mode, role, domains, min_severity, email, channels, quiet) values (%s,%s,%s,%s,%s,%s,%s,%s) '
         'on conflict ("user", mode) do update set role=excluded.role, domains=excluded.domains, min_severity=excluded.min_severity, '
         "email=excluded.email, channels=excluded.channels, quiet=excluded.quiet, updated_at=now()",
         (user, mode, role, Jsonb(["*"] if body.get("domains") is None else list(body["domains"])), sev, email,
          Jsonb(body.get("channels") or {"email": bool(email)}), Jsonb(q) if q else None))
    return sub_of(db, user, mode, role)


def _hm(s):
    try:
        h, m = str(s).split(":")
        return int(h) * 60 + int(m)
    except Exception:  # noqa: BLE001
        return None


def in_quiet(quiet, now=None):
    if not quiet:
        return False
    from hub import kpi
    t = (now or dt.datetime.now(dt.timezone.utc)).astimezone(kpi.TZ)
    m = t.hour * 60 + t.minute
    a, b = _hm(quiet.get("from")), _hm(quiet.get("to"))
    if a is None or b is None or a == b:
        return False
    return a <= m < b if a < b else (m >= a or m < b)


def matches(sub, domain, severity):
    if severity and RANK.get(severity, 0) < RANK.get(sub["min_severity"], 1):
        return False
    if domain and sub["domains"] is not None and domain not in sub["domains"]:
        return False
    return True


# ---------------------------------------------------------------- 发
def emit(db, mode, target, kind, title, body=None, url=None, ref=None, domain=None, severity=None, external=True, owner_role=None):
    """写一条站内通知，并按订阅推到邮件和群机器人（教学模式只站内）"""
    init_once(db)
    r = db.one("insert into notification (mode, target, kind, ref, domain, severity, title, body, url, owner_role) "
               "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id", (mode, target, kind, ref, domain, severity, title, body, url, owner_role))
    sent = {}
    if external and mode != "teach":
        try:
            sent = _external(db, mode, target, kind, title, body, url, domain, severity)
        except Exception:  # noqa: BLE001
            log.exception("外发通知失败")
        if sent:
            db.x("update notification set sent=%s where id=%s", (Jsonb(sent), r["id"]))
    return r["id"]


_ready = set()


def init_once(db):
    k = id(db)
    if k not in _ready:
        with _lock:
            if k not in _ready:
                init(db)
                _ready.add(k)


def _recipients(db, mode, target):
    """外发用：目标对应的订阅（只有填了邮箱、开了邮件的人才会收到邮件）"""
    rows = db.q('select * from notify_sub where mode=%s and email is not null', (mode,))
    out = []
    for r in rows:
        if target == "*" or target == "@" + r["user"] or (target.startswith("role:") and target[5:] == (r["role"] or "")) or \
                (target.startswith("role:") and target[5:] == "manager" and r["role"] == "manager"):
            out.append(r)
    return out


def _external(db, mode, target, kind, title, body, url, domain, severity, now=None):
    sent = {"email": [], "groups": []}
    full = public_url(url)
    text = "{}\n{}{}".format(title, (body or "").strip(), ("\n" + full) if full else "")
    urgent = severity == "critical"
    for r in _recipients(db, mode, target):
        s = sub_of(db, r["user"], mode, r["role"])
        if not (s["channels"] or {}).get("email") or not s["email"]:
            continue
        if kind in ("anomaly", "escalate") and not matches(s, domain, severity):
            continue
        if in_quiet(s["quiet"], now) and not urgent:
            continue
        if send_mail(s["email"], "【问渠厂情中枢】" + title, text):
            sent["email"].append(r["user"])
    if kind in ("anomaly", "escalate", "report", "test"):
        for ch in db.q("select * from notify_channel where mode=%s", (mode,)):
            if ch["domain"] and domain and ch["domain"] != domain:
                continue
            if severity and RANK.get(severity, 0) < RANK.get(ch["min_severity"], 1):
                continue
            if send_group(ch["kind"], dec(ch["url_enc"]), title, text):
                sent["groups"].append(ch["id"])
    return {k: v for k, v in sent.items() if v}


def public_url(path):
    if not path:
        return ""
    base = os.environ.get("WQ_PUBLIC_URL", "").rstrip("/")
    return (base + path) if base and path.startswith("/") else path


def smtp_ready():
    return bool(os.environ.get("WQ_SMTP_HOST"))


def send_mail(to, subject, text):
    host = os.environ.get("WQ_SMTP_HOST")
    if not host:
        return False
    port = int(os.environ.get("WQ_SMTP_PORT") or 2525)
    secure = (os.environ.get("WQ_SMTP_SECURE") or "tls").lower()
    sender = os.environ.get("WQ_MAIL_FROM") or os.environ.get("WQ_SMTP_USER") or "noreply@localhost"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    msg.set_content(text)
    try:
        if secure == "ssl":
            s = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
        else:
            s = smtplib.SMTP(host, port, timeout=15)
            if secure == "tls":
                s.starttls(context=ssl.create_default_context())
        with s:
            if os.environ.get("WQ_SMTP_USER"):
                s.login(os.environ["WQ_SMTP_USER"], os.environ.get("WQ_SMTP_PASSWORD", ""))
            s.send_message(msg)
        return True
    except Exception:  # noqa: BLE001
        log.exception("发邮件失败（%s）", to)
        return False


def group_payload(kind, title, text):
    if kind == "wecom":
        return {"msgtype": "markdown", "markdown": {"content": "**{}**\n{}".format(title, text.split("\n", 1)[-1])}}
    if kind == "dingtalk":
        return {"msgtype": "markdown", "markdown": {"title": title, "text": "### {}\n{}".format(title, text.split("\n", 1)[-1])}}
    return {"msg_type": "text", "content": {"text": text}}                       # 飞书


def send_group(kind, url, title, text):
    try:
        r = httpx.post(url, json=group_payload(kind, title, text), timeout=10)
        ok = r.status_code < 300
        if ok:
            try:
                b = r.json()
                ok = b.get("errcode", 0) == 0 and b.get("code", 0) in (0, None) and b.get("StatusCode", 0) == 0
            except ValueError:
                pass
        if not ok:
            log.warning("群机器人返回 %s：%s", r.status_code, r.text[:200])
        return ok
    except Exception:  # noqa: BLE001
        log.exception("群机器人发送失败")
        return False


# ---------------------------------------------------------------- 来源：异常、升级、动作
def on_alerts(db, mode, alerts):
    """规则库一轮检测返回的提醒（新开、升级、重开）→ 通知（按负责角色 + 厂长）"""
    for a in alerts or []:
        aid = a.get("anomaly_id")
        if not aid:
            continue
        row = db.one("select * from anomaly where id=%s", (aid,))
        if row is None:
            continue
        ch = row["chain"]
        if not ch:
            try:
                from hub.ont import anomaly as A
                from hub.ont import chain as CH
                ch = CH.for_anomaly(A.Ctx(db, mode), row)
            except Exception:  # noqa: BLE001
                ch = None
        sc = ((ch or {}).get("scope") or {})
        n_so = len(sc.get("sales_orders") or [])
        title = "{}：{}".format(SEV_LABEL.get(row["severity"], row["severity"]), row["title"])
        body = ((row["detail"] or {}).get("text") or "") + ("；影响 {} 张订单".format(n_so) if n_so else "")
        url = "/ont?view=anomalies&a={}".format(aid)
        kind_txt = {"escalate": "升级", "reopen": "重开"}.get(a.get("change"), "")
        if kind_txt:
            title = "（{}）{}".format(kind_txt, title)
        owner = row["role"] or "manager"
        emit(db, mode, "role:" + owner, "anomaly", title, body, url, "A-{:05d}".format(aid), row["domain"], row["severity"], owner_role=owner)
        if owner != "manager":
            emit(db, mode, "role:manager", "anomaly", title, body, url, "A-{:05d}".format(aid), row["domain"], row["severity"], external=False,
                 owner_role=owner)


def escalate(db, mode, now=None):
    """“严重”异常 30 分钟没人确认（还是“新发现”）→ 再提醒厂长一次"""
    init_once(db)
    now = now or dt.datetime.now(dt.timezone.utc)
    rows = db.q("select * from anomaly where mode=%s and status='open' and severity='critical' and first_seen < %s",
                (mode, now - dt.timedelta(minutes=ESCALATE_MIN)))
    out = []
    for a in rows:
        ref = "A-{:05d}".format(a["id"])
        if db.one("select 1 as x from notification where mode=%s and kind='escalate' and ref=%s", (mode, ref)):
            continue
        out.append(emit(db, mode, "role:manager", "escalate", "（{} 分钟没人确认）严重：{}".format(ESCALATE_MIN, a["title"]),
                        (a["detail"] or {}).get("text"), "/ont?view=anomalies&a={}".format(a["id"]), ref, a["domain"], "critical"))
    return out


def on_action(db, mode, a, event, who=None, text=None):
    """动作的状态变化 → 通知相关的人"""
    key = "ACT-{:05d}".format(a["id"])
    url = "/ont/actions"
    if event == "submitted":
        from hub.ont import actions as AC
        costly = AC.TYPES.get(a["type"], {}).get("costly")
        emit(db, mode, "role:manager", "action", "待批准：{} {}".format(key, a["title"]), "{} 提交{}".format(a["initiator"], "（花钱，要厂长批）" if costly else ""),
             url + "?box=todo", key, "core", "warn", external=False)
        if not costly:
            emit(db, mode, "role:planner", "action", "待批准：{} {}".format(key, a["title"]), "{} 提交".format(a["initiator"]), url + "?box=todo",
                 key, "core", "warn", external=False)
    elif event in ("done", "failed", "rejected", "approved"):
        label = {"done": "已执行", "failed": "执行失败", "rejected": "被驳回", "approved": "已批准"}[event]
        emit(db, mode, "@" + (a["initiator"] or ""), "action", "{}：{} {}".format(label, key, a["title"]),
             "{}{}".format(who or "", ("：" + text) if text else ""), url + "?box=mine", key, "core", "critical" if event == "failed" else "info",
             external=False)


# ---------------------------------------------------------------- 读
def feed(db, u, limit=50):
    """站内铃铛：发给我 / 我的角色 / 全体的，按我的订阅过滤异常类"""
    init_once(db)
    s = sub_of(db, u["name"], u["mode"], u.get("role"))
    targets = ["*", "@" + u["name"], "role:" + (u.get("role") or "")]
    if u.get("teacher") and u["mode"] == "teach":
        targets.append("role:manager")
    rows = db.q('select n.*, (r.id is not null) as read from notification n left join notify_read r on r.id=n.id and r."user"=%s '
                "where n.mode=%s and n.target = any(%s) and n.created_at > now() - interval '14 days' order by n.id desc limit 300",
                (u["name"], u["mode"], targets))
    out = []
    for r in rows:
        if r["kind"] in ("anomaly", "escalate") and not r["target"].startswith("@") and r["owner_role"] != u.get("role") \
                and not matches(s, r["domain"], r["severity"]):
            continue                          # 负责这个异常的角色总能看到；别人按订阅过滤
        out.append({"id": r["id"], "kind": r["kind"], "title": r["title"], "body": r["body"], "url": r["url"], "ref": r["ref"],
                    "severity": r["severity"], "created_at": r["created_at"].isoformat(), "read": r["read"]})
        if len(out) >= limit:
            break
    return {"items": out, "unread": sum(1 for x in out if not x["read"])}


def mark_read(db, user, ids):
    for i in ids:
        db.x('insert into notify_read ("user", id) values (%s,%s) on conflict do nothing', (user, int(i)))


def banner(db, mode, limit=3):
    """首页提醒条：开着的“严重”异常和带预案的“警告”异常（停机、缺料、交期）"""
    from hub.ont import playbook as PB
    books = PB.catalog()[0]
    rows = db.q("select * from anomaly where mode=%s and status in ('open','ack','doing') and "
                "(severity='critical' or (severity='warn' and rule = any(%s))) "
                "order by coalesce(array_position(%s::text[], rule), 99), case severity when 'critical' then 0 else 1 end, first_seen desc limit %s",
                (mode, list(books), list(books), limit))     # 先放能推演处理方案的，按预案目录的顺序（停机 → 交期 → 缺料），再放其他严重的
    out = []
    for a in rows:
        sc = ((a["chain"] or {}).get("scope") or {})
        n_so = len(sc.get("sales_orders") or [])
        n_opt = len(books.get(a["rule"]) or [])
        txt = "厂情中枢：{}".format(a["title"])
        if n_so:
            txt += "，影响 {} 张订单".format(n_so)
        if n_opt > 1:
            txt += "，有 {} 个处理方案可以推演比较".format(n_opt)
        out.append({"id": a["id"], "key": "A-{:05d}".format(a["id"]), "severity": a["severity"], "text": txt,
                    "url": "/ont?view=anomalies&a={}".format(a["id"])})
    return out


def _dump(x):
    return json.dumps(x, ensure_ascii=False, default=str)
