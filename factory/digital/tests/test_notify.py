# -*- coding: utf-8 -*-
"""第 17 轮 D 期第 3 步：主动提醒——站内通知与订阅、异常与升级、动作、邮件（本地测试邮件服务器）、群机器人（本地假服务器）、
免打扰、教学模式只发站内、首页提醒条。"""
import datetime as dt
import http.server
import json
import os
import socketserver
import threading

import pytest
from psycopg.types.json import Jsonb

BASE = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0]


# ---------------------------------------------------------------- 本地测试邮件服务器（最小 SMTP）与群机器人假服务器
class _SMTP(socketserver.StreamRequestHandler):
    def handle(self):
        w = lambda s: self.wfile.write((s + "\r\n").encode())            # noqa: E731
        w("220 test")
        data, rcpt = [], []
        while True:
            line = self.rfile.readline().decode(errors="ignore").rstrip("\r\n")
            if not line:
                return
            cmd = line.upper()
            if cmd.startswith(("EHLO", "HELO")):
                w("250 ok")
            elif cmd.startswith("MAIL"):
                w("250 ok")
            elif cmd.startswith("RCPT"):
                rcpt.append(line.split(":", 1)[1].strip(" <>"))
                w("250 ok")
            elif cmd == "DATA":
                w("354 go")
                while True:
                    ln = self.rfile.readline().decode(errors="ignore")
                    if ln.rstrip("\r\n") == ".":
                        break
                    data.append(ln)
                self.server.mails.append({"to": rcpt[:], "data": "".join(data)})
                w("250 ok")
            elif cmd == "QUIT":
                w("221 bye")
                return
            else:
                w("250 ok")


class _Hook(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        self.server.posts.append({"path": self.path, "body": json.loads(self.rfile.read(n))})
        out = json.dumps({"errcode": 0, "errmsg": "ok"}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def servers():
    smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SMTP)
    smtp.mails = []
    hook = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Hook)
    hook.posts = []
    for s in (smtp, hook):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    yield smtp, hook
    smtp.shutdown()
    hook.shutdown()


@pytest.fixture(scope="module")
def db():
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_notify_test with (force)")
            c.execute("create database wq_notify_test")
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    from hub.ont import actions as AC
    from hub.ont import anomaly as A
    from hub.ont import notify as NT
    from hub.ont import plan as P
    d = DB(BASE + "/wq_notify_test")
    d.init()
    A.Detector(d).init()
    P.init(d)
    AC.init(d)
    NT.init(d)
    return d


def _anomaly(db, mode, rule="P1", severity="warn", role="planner", domain="production", title="GRD-01 停机：换砂轮", minutes_ago=0, so=None):
    now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
    chain = {"scope": {"sales_orders": [so]}} if so else None
    r = db.one("insert into anomaly (mode, rule, fkey, domain, subject_type, subject_key, severity, role, title, detail, first_seen, last_seen, chain) "
               "values (%s,%s,%s,%s,'Machine','grd-01',%s,%s,%s,%s,%s,%s,%s) returning id",
               (mode, rule, "k{}".format(now.timestamp()), domain, severity, role, title, Jsonb({"text": "预计还要约 90 分钟"}), now, now,
                Jsonb(chain) if chain else None))
    return r["id"]


def _u(name, role, mode="teach", teacher=False):
    return {"name": name, "role": role, "mode": mode, "teacher": teacher}


def test_inbox_follows_target_and_subscription(db):
    from hub.ont import notify as NT
    aid = _anomaly(db, "teach", severity="warn", role="engineer", domain="production", so="SAL-ORD-2026-00019")
    NT.on_alerts(db, "teach", [{"anomaly_id": aid, "change": "open"}])
    assert any(x["ref"] == "A-{:05d}".format(aid) for x in NT.feed(db, _u("工艺员庚", "engineer"))["items"])      # 负责角色总能看到
    # 计划员默认订阅交付、物料，没订“生产”，这条也不是发给计划员的：不显示
    assert not any(x["ref"] == "A-{:05d}".format(aid) for x in NT.feed(db, _u("计划员甲", "planner"))["items"])
    mgr = NT.feed(db, _u("厂长乙", "manager"))
    it = next(x for x in mgr["items"] if x["ref"] == "A-{:05d}".format(aid))
    assert "影响 1 张订单" in it["body"] and it["url"].endswith("a={}".format(aid)) and not it["read"]
    NT.save_sub(db, "厂长乙", "teach", "manager", {"domains": ["quality"], "min_severity": "warn"})
    assert not any(x["ref"] == "A-{:05d}".format(aid) for x in NT.feed(db, _u("厂长乙", "manager"))["items"])     # 厂长只订了质量
    NT.save_sub(db, "厂长乙", "teach", "manager", {"domains": None, "min_severity": "warn"})
    NT.mark_read(db, "厂长乙", [it["id"]])
    assert next(x for x in NT.feed(db, _u("厂长乙", "manager"))["items"] if x["id"] == it["id"])["read"]
    # 升级再发一条，标题注明“升级”
    NT.on_alerts(db, "teach", [{"anomaly_id": aid, "change": "escalate"}])
    assert any(x["title"].startswith("（升级）") for x in NT.feed(db, _u("厂长乙", "manager"))["items"])


def test_escalate_once_after_30_minutes(db):
    from hub.ont import notify as NT
    old = _anomaly(db, "teach", severity="critical", role="engineer", domain="maintenance", minutes_ago=45, title="CNC-L01-B 故障")
    new = _anomaly(db, "teach", severity="critical", role="engineer", domain="maintenance", minutes_ago=5, title="HMC-01 故障")
    first = NT.escalate(db, "teach")
    assert len(first) == 1 and not NT.escalate(db, "teach")
    n = db.one("select * from notification where id=%s", (first[0],))
    assert n["ref"] == "A-{:05d}".format(old) and n["target"] == "role:manager" and "30 分钟没人确认" in n["title"]
    assert not db.one("select 1 as x from notification where kind='escalate' and ref=%s", ("A-{:05d}".format(new),))


def test_teach_mode_never_sends_outside(db, servers, monkeypatch):
    from hub.ont import notify as NT
    smtp, hook = servers
    monkeypatch.setenv("WQ_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("WQ_SMTP_PORT", str(smtp.server_address[1]))
    monkeypatch.setenv("WQ_SMTP_SECURE", "none")
    NT.save_sub(db, "老师丙", "teach", "manager", {"domains": None, "min_severity": "info", "email": "t@example.com", "channels": {"email": True}})
    db.x("insert into notify_channel (mode, kind, name, url_enc, tail) values ('teach','wecom','x',%s,'0000')",
         (NT.enc("http://127.0.0.1:{}/teach".format(hook.server_address[1])),))
    n0, p0 = len(smtp.mails), len(hook.posts)
    aid = _anomaly(db, "teach", severity="critical", role="manager")
    NT.on_alerts(db, "teach", [{"anomaly_id": aid, "change": "open"}])
    assert len(smtp.mails) == n0 and len(hook.posts) == p0


def test_prod_email_and_group_robots(db, servers, monkeypatch):
    from hub.ont import notify as NT
    smtp, hook = servers
    monkeypatch.setenv("WQ_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("WQ_SMTP_PORT", str(smtp.server_address[1]))
    monkeypatch.setenv("WQ_SMTP_SECURE", "none")
    monkeypatch.setenv("WQ_MAIL_FROM", "factory@example.com")
    monkeypatch.setenv("WQ_PUBLIC_URL", "https://factory.example.test")
    NT.save_sub(db, "厂长丁", "prod", "manager", {"domains": None, "min_severity": "warn", "email": "boss@example.com", "channels": {"email": True}})
    NT.save_sub(db, "质检戊", "prod", "quality", {"domains": ["quality"], "min_severity": "warn", "email": "qc@example.com", "channels": {"email": True}})
    port = hook.server_address[1]
    for kind, dom in (("wecom", None), ("dingtalk", "maintenance"), ("feishu", "quality")):
        db.x("insert into notify_channel (mode, kind, name, domain, url_enc, tail) values ('prod',%s,%s,%s,%s,'0000')",
             (kind, kind, dom, NT.enc("http://127.0.0.1:{}/{}".format(port, kind))))
    n0, p0 = len(smtp.mails), len(hook.posts)
    aid = _anomaly(db, "prod", severity="critical", role="manager", domain="maintenance", title="GRD-01 主轴故障", so="SAL-ORD-2026-00019")
    NT.on_alerts(db, "prod", [{"anomaly_id": aid, "change": "open"}])
    mails = smtp.mails[n0:]
    assert [m["to"] for m in mails] == [["boss@example.com"]]                     # 质检只订了质量
    assert "GRD-01" in mails[0]["data"] and "https://factory.example.test/ont?view=anomalies" in mails[0]["data"]
    posts = {p["path"]: p["body"] for p in hook.posts[p0:]}
    assert set(posts) == {"/wecom", "/dingtalk"}                                   # 飞书群只收质量
    assert posts["/wecom"]["msgtype"] == "markdown" and "GRD-01" in posts["/wecom"]["markdown"]["content"]
    assert posts["/dingtalk"]["markdown"]["title"].startswith("严重")
    sent = db.one("select sent from notification where ref=%s and target='role:manager' order by id limit 1", ("A-{:05d}".format(aid),))["sent"]
    assert sent["email"] == ["厂长丁"] and len(sent["groups"]) == 2


def test_quiet_hours_block_all_but_critical(db, servers, monkeypatch):
    from hub.ont import notify as NT
    smtp, hook = servers
    monkeypatch.setenv("WQ_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("WQ_SMTP_PORT", str(smtp.server_address[1]))
    monkeypatch.setenv("WQ_SMTP_SECURE", "none")
    db.x("delete from notify_channel where mode='prod'")
    NT.save_sub(db, "厂长丁", "prod", "manager", {"domains": None, "min_severity": "warn", "email": "boss@example.com", "channels": {"email": True},
                                               "quiet": {"from": "00:00", "to": "23:59"}})
    n0 = len(smtp.mails)
    w = _anomaly(db, "prod", severity="warn", role="manager", title="警告级")
    NT.on_alerts(db, "prod", [{"anomaly_id": w, "change": "open"}])
    assert len(smtp.mails) == n0
    c = _anomaly(db, "prod", severity="critical", role="manager", title="严重级")
    NT.on_alerts(db, "prod", [{"anomaly_id": c, "change": "open"}])
    assert len(smtp.mails) == n0 + 1
    assert NT.in_quiet({"from": "22:00", "to": "07:00"}, dt.datetime(2026, 10, 6, 4, 0, tzinfo=dt.timezone.utc))     # 纽约 00:00
    assert not NT.in_quiet({"from": "22:00", "to": "07:00"}, dt.datetime(2026, 10, 6, 16, 0, tzinfo=dt.timezone.utc))


def test_action_events_reach_approvers_and_initiator(db):
    from hub.ont import notify as NT
    a = {"id": 77, "type": "expedite", "title": "维修加急 GRD-01", "initiator": "计划员甲", "mode": "teach"}
    NT.on_action(db, "teach", a, "submitted")
    mgr = NT.feed(db, _u("厂长乙", "manager"))["items"]
    assert any(x["title"].startswith("待批准：ACT-00077") for x in mgr)
    planner2 = NT.feed(db, _u("计划员己", "planner"))["items"]
    assert not any("ACT-00077" in x["title"] for x in planner2)                      # 花钱的只给厂长
    NT.on_action(db, "teach", a, "rejected", "厂长乙", "先等备件到货")
    mine = NT.feed(db, _u("计划员甲", "planner"))["items"]
    assert any(x["title"].startswith("被驳回：ACT-00077") and "先等备件到货" in x["body"] for x in mine)


def test_webhook_url_is_encrypted_and_banner(db):
    from hub.ont import notify as NT
    u = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcd-1234"
    assert NT.dec(NT.enc(u)) == u and "abcd" not in NT.enc(u)
    aid = _anomaly(db, "teach", severity="warn", rule="P1", so="SAL-ORD-2026-00019")
    b = NT.banner(db, "teach", limit=20)
    it = next(x for x in b if x["id"] == aid)
    assert it["text"].startswith("厂情中枢：") and "影响 1 张订单" in it["text"] and "方案" in it["text"]
