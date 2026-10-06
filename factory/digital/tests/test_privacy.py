# -*- coding: utf-8 -*-
"""第 4 轮 C5：线上版（问渠账号）发到总线的消息里没有姓名；本地版照旧写姓名。"""
import importlib
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from test_auth import ACCOUNTS, _Resp, _Teach  # noqa: E402


def test_actor_is_role_and_stable_pseudonym(monkeypatch):
    monkeypatch.setenv("WQ_AUTH", "wenquest")
    from hub import privacy
    a = privacy.actor("王小明（101）", "planner")
    assert a.startswith("planner·") and "王" not in a and "101" not in a
    assert privacy.actor("王小明（101）", "operator").split("·")[1] == a.split("·")[1]   # 换角色编号不变
    assert privacy.actor("李四（102）", "planner") != a
    assert privacy.is_me(a, "王小明（101）") and not privacy.is_me(a, "李四（102）")
    monkeypatch.setenv("WQ_AUTH", "local")
    assert privacy.actor("王小明", "planner") == "王小明"
    assert privacy.is_me("王小明", "王小明")


class _MES:
    def __init__(self):
        self.calls = []

    def command(self, unit, cmd, mode, user, *a, **k):
        self.calls.append(("command", unit, cmd, user))

    def release(self, wo, mode, user, units=None):
        self.calls.append(("release", wo, user))
        return []


class _DB:
    def one(self, sql, args=None):
        if "from ncr" in sql:
            return {"ncr_id": "NCR-1", "part_serial": "P1", "item": "SH-301", "work_order": "WO-1"}
        return None

    def x(self, *a, **k):
        pass


def test_nothing_the_student_does_puts_a_name_on_the_bus(monkeypatch):
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_AUTH", "wenquest")
    monkeypatch.setenv("WQ_SSO_URL", "https://learn.example.com/api/v1/auth/sso")
    monkeypatch.setenv("WQ_SECRET", "test-secret")
    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, cookies=None, timeout=None: _Resp(200, {"user": ACCOUNTS["stu-cookie"]}))
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    app_mod.H.teach = _Teach()
    app_mod.H.mes = _MES()
    app_mod.H.db = _DB()
    sent = []
    monkeypatch.setattr(app_mod.H, "publish", lambda tp, ty, src, data, corr=None, mode=None: sent.append((src, data)))
    c = TestClient(app_mod.app)
    c.cookies.set("wq_sso", "stu-cookie")
    tok = c.post("/api/login", json={"role": "operator"}).json()["token"]
    h = {"x-wq-token": tok}
    assert c.post("/api/mes/cmd", json={"unit": "grd-01", "command": "start", "work_order": "WO-1"}, headers=h).status_code == 200
    assert c.post("/api/mes/release", json={"work_order": "WO-1"}, headers=h).status_code == 200
    tok = c.post("/api/me/switch", json={"role": "quality"}, headers=h).json()["token"]
    assert c.post("/api/ncr/NCR-1", json={"disposition": "rework"}, headers={"x-wq-token": tok}).status_code == 200
    blob = json.dumps([app_mod.H.mes.calls, sent], ensure_ascii=False)
    assert "王小明" not in blob and "（101）" not in blob and "xiaoming" not in blob
    assert "operator·" in blob and "quality·" in blob
    monkeypatch.setenv("WQ_AUTH", "local")
    importlib.reload(app_mod)
