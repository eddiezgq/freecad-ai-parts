# -*- coding: utf-8 -*-
"""第 3 轮 D2、D3、D7：线上用问渠账号登录、学生与老师的权限、AI 限次。

学习平台的核对接口用假的代替（不联网）；枢纽不启动总线和数据库（WQ_HUB_NO_START=1）。
"""
import importlib
import os

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

ACCOUNTS = {
    "stu-cookie": {"id": 101, "fullname": "王小明", "username": "xiaoming", "can_create_courses": False},
    "tea-cookie": {"id": 7, "fullname": "李老师", "username": "teacher_li", "can_create_courses": True},
}


class _Teach:
    def __init__(self):
        self.started = []

    def start(self, name):
        self.started.append(name)


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


@pytest.fixture()
def hub(monkeypatch):
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_AUTH", "wenquest")
    monkeypatch.setenv("WQ_SSO_URL", "https://learn.example.com/api/v1/auth/sso")
    monkeypatch.setenv("WQ_LOGIN_URL", "https://learn.example.com/pages/login/login")
    monkeypatch.setenv("WQ_AI_PER_HOUR", "3")
    monkeypatch.setenv("WQ_SECRET", "test-secret")
    import httpx

    def fake_get(url, cookies=None, timeout=None):
        assert url == "https://learn.example.com/api/v1/auth/sso"
        u = ACCOUNTS.get((cookies or {}).get("wq_sso", ""))
        return _Resp(200, {"token": "x", "user": u}) if u else _Resp(401, {"code": "not_logged_in"})

    monkeypatch.setattr(httpx, "get", fake_get)
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    app_mod.H.teach = _Teach()

    class _AI:
        def chat(self, msgs, mode, role, name):
            return {"answer": "好", "sources": []}

        def evaluate(self, mode):
            return []

        def briefing(self, mode):
            return {"summary": "ok"}

    app_mod.H.ai = _AI()
    yield app_mod
    for k in ("WQ_AUTH", "WQ_SSO_URL", "WQ_LOGIN_URL", "WQ_AI_PER_HOUR"):
        os.environ.pop(k, None)
    importlib.reload(app_mod)


def _client(app_mod, cookie=None):
    c = TestClient(app_mod.app)
    if cookie:
        c.cookies.set("wq_sso", cookie)
    return c


def _login(c, **body):
    return c.post("/api/login", json=body)


def test_not_signed_in_is_refused_and_told_where_to_sign_in(hub):
    c = _client(hub)
    info = c.get("/api/login/info").json()
    assert info["auth"] == "wenquest" and info["account"] is None
    assert info["login_url"] == "https://learn.example.com/pages/login/login"
    r = _login(c, role="planner", mode="teach")
    assert r.status_code == 401
    assert c.get("/api/overview").status_code == 401
    # 自己伪造的旧式凭证也不行
    assert c.get("/api/overview", headers={"x-wq-token": "abc.def"}).status_code == 401


def test_student_gets_teach_mode_and_station_roles_only(hub):
    c = _client(hub, "stu-cookie")
    assert c.get("/api/login/info").json()["account"] == {"fullname": "王小明", "teacher": False}
    r = _login(c, mode="prod")                     # 学生要生产模式也只给教学模式
    assert r.status_code == 200
    u = r.json()["user"]
    assert u["name"] == "王小明（101）" and u["teacher"] is False
    assert u["mode"] == "teach" and u["role"] == "planner"
    assert hub.H.teach.started == ["王小明（101）"]
    assert _login(c, role="manager").status_code == 403
    tok = r.json()["token"]
    h = {"x-wq-token": tok}
    assert c.post("/api/me/switch", json={"role": "quality"}, headers=h).status_code == 200
    assert c.post("/api/me/switch", json={"role": "manager"}, headers=h).status_code == 403
    assert c.post("/api/me/switch", json={"mode": "prod"}, headers=h).status_code == 403
    # 教师控制台：重置情景、制造故障、改倍速
    assert c.post("/api/scenario/reset", json={}, headers=h).status_code == 403
    for cmd in ("inject_fault", "set_speed", "load_scenario"):
        assert c.post("/api/mes/cmd", json={"unit": "grd-01", "command": cmd}, headers=h).status_code == 403


def test_teacher_can_use_manager_role_and_production_mode(hub):
    c = _client(hub, "tea-cookie")
    r = _login(c)
    assert r.status_code == 200
    u = r.json()["user"]
    assert u["teacher"] is True and u["role"] == "manager"
    h = {"x-wq-token": r.json()["token"]}
    r2 = c.post("/api/me/switch", json={"mode": "prod"}, headers=h)
    assert r2.status_code == 200 and r2.json()["user"]["mode"] == "prod"


def test_ai_questions_are_limited_per_person_per_hour(hub):
    c = _client(hub, "stu-cookie")
    h = {"x-wq-token": _login(c).json()["token"]}
    q = {"messages": [{"role": "user", "content": "瓶颈在哪？"}]}
    for _ in range(3):
        assert c.post("/api/ai/chat", json=q, headers=h).status_code == 200
    r = c.post("/api/ai/chat", json=q, headers=h)
    assert r.status_code == 429 and "3 次" in r.json()["detail"]
    # 别人不受影响
    c2 = _client(hub, "tea-cookie")
    h2 = {"x-wq-token": _login(c2).json()["token"]}
    assert c2.post("/api/ai/chat", json=q, headers=h2).status_code == 200


def test_tokens_expire(hub, monkeypatch):
    c = _client(hub, "stu-cookie")
    tok = _login(c).json()["token"]
    real = hub.time.time
    monkeypatch.setattr(hub.time, "time", lambda: real() + 8 * 86400)
    assert c.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "x"}]},
                  headers={"x-wq-token": tok}).status_code == 401


def test_local_mode_keeps_name_login(monkeypatch):
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.delenv("WQ_AUTH", raising=False)
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    app_mod.H.teach = _Teach()
    c = TestClient(app_mod.app)
    assert c.get("/api/login/info").json()["auth"] == "local"
    r = c.post("/api/login", json={"name": "测试", "role": "manager", "mode": "prod"})
    assert r.status_code == 200 and r.json()["user"]["teacher"] is True
