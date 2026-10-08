# -*- coding: utf-8 -*-
"""企业账号（本仓库 ADR-0063）：密码哈希、登录与锁定、角色权限、停用与改密码后旧凭证失效、管理员管理账号。"""
import importlib
import os

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0] + "/wq_accounts"
PW = "Admin-pass-2026"


@pytest.fixture()
def db():
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(DSN.rsplit("/", 1)[0] + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_accounts with (force)")
            c.execute("create database wq_accounts")
    except psycopg.OperationalError:
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    d = DB(DSN)
    d.init()
    from hub import accounts
    accounts._CACHE.clear()
    d.x(accounts.SCHEMA)
    return d


def test_hash_and_rules(db):
    from hub import accounts as A
    h = A.hash_pw(PW)
    assert h.startswith("scrypt$") and PW not in h and A.check_pw(PW, h) and not A.check_pw("x" + PW, h)
    for bad in ("short1", "onlyletterslong", "1234567890123"):
        with pytest.raises(A.AccountError):
            A.create(db, "u1", bad, roles=["planner"])
    with pytest.raises(A.AccountError, match="至少分一个角色"):
        A.create(db, "u1", PW)
    with pytest.raises(A.AccountError, match="用户名"):
        A.create(db, "坏 名字", PW, roles=["planner"])
    A.create(db, "boss", PW, admin=True)
    with pytest.raises(A.AccountError, match="已存在"):
        A.create(db, "boss", PW, admin=True)
    with pytest.raises(A.AccountError, match="至少要留一个"):
        A.update(db, "boss", active=False)


def test_lockout(db, monkeypatch):
    from hub import accounts as A
    A.create(db, "zhang", PW, name="张工", roles=["engineer"])
    for _ in range(A.MAX_FAILED):
        with pytest.raises(A.AccountError, match="不对"):
            A.authenticate(db, "zhang", "wrong-pass-1")
    with pytest.raises(A.AccountError, match="分钟后再试"):
        A.authenticate(db, "zhang", PW)                       # 锁定期内密码对了也不行
    db.x("update fap_account set locked_until = now() - interval '1 second' where username='zhang'")
    assert A.authenticate(db, "zhang", PW)["roles"] == ["engineer"]
    with pytest.raises(A.AccountError, match="用户名或密码不对"):
        A.authenticate(db, "nobody", PW)                      # 不区分“没这个人”和“密码错”


@pytest.fixture()
def hub(db, monkeypatch):
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_AUTH", "enterprise")
    monkeypatch.setenv("WQ_SECRET", "test-secret")
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    app_mod.H.db = db
    from hub import accounts
    accounts.create(db, "boss", PW, name="王厂长", admin=True)
    yield app_mod
    os.environ.pop("WQ_AUTH", None)
    importlib.reload(app_mod)


def _login(c, user, pw=PW, **kw):
    return c.post("/api/login", json={"username": user, "password": pw, **kw})


def test_enterprise_flow(hub):
    c = TestClient(hub.app)
    assert c.get("/api/login/info").json()["auth"] == "enterprise"
    assert c.post("/api/login", json={"name": "随便", "role": "manager"}).status_code == 401   # 填名字进不来
    r = _login(c, "boss")
    assert r.status_code == 200 and r.json()["user"]["teacher"] is True and r.json()["user"]["role"] == "manager"
    boss = {"x-wq-token": r.json()["token"]}
    r = c.post("/api/accounts", json={"username": "li", "password": PW, "name": "李计划", "roles": ["planner", "quality"]},
               headers=boss)
    assert r.status_code == 200 and r.json()["roles"] == ["planner", "quality"]
    li = _login(c, "li").json()
    assert li["user"]["role"] == "planner" and li["user"]["mode"] == "prod" and li["user"]["member"] == ["planner", "quality"]
    lt = {"x-wq-token": li["token"]}
    assert c.get("/api/accounts", headers=lt).status_code == 403                            # 普通账号不能管账号
    assert c.post("/api/me/switch", json={"role": "quality"}, headers=lt).status_code == 200
    assert c.post("/api/me/switch", json={"role": "manager"}, headers=lt).status_code == 403  # 没分给他的角色
    # 管理员停用 → 旧凭证立即失效（缓存清掉）
    assert c.post("/api/accounts/li", json={"active": False}, headers=boss).json()["active"] is False
    assert c.post("/api/me/switch", json={"role": "planner"}, headers=lt).status_code == 401
    assert _login(c, "li").status_code == 401
    # 恢复、重置密码 → 用旧密码登录不了，旧凭证失效
    c.post("/api/accounts/li", json={"active": True, "password": "New-pass-2026"}, headers=boss)
    assert _login(c, "li").status_code == 401 and _login(c, "li", "New-pass-2026").status_code == 200
    # 本人改密码
    tok = {"x-wq-token": _login(c, "li", "New-pass-2026").json()["token"]}
    assert c.post("/api/me/password", json={"old": "bad", "new": "Third-pass-2026"}, headers=tok).status_code == 400
    assert c.post("/api/me/password", json={"old": "New-pass-2026", "new": "Third-pass-2026"}, headers=tok).status_code == 200
    assert c.post("/api/me/switch", json={"role": "planner"}, headers=tok).status_code == 401
    names = [a["username"] for a in c.get("/api/accounts", headers=boss).json()["accounts"]]
    assert names == ["boss", "li"] and "pw_hash" not in str(c.get("/api/accounts", headers=boss).json())
