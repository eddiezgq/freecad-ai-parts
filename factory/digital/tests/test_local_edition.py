# -*- coding: utf-8 -*-
"""第 30 轮 H-5：学校机房的本地版（factory/local/）。

- 本地版（WQ_EDITION=local、填名字登录）里学生只能选学生岗位、只能用教学模式；当老师要输老师密码（WQ_TEACHER_PASSWORD）
- 不是本地版时照旧：填名字的人都是老师（开发机、CI 演练用）
- /api/config 带 edition；机房里学生用老师电脑的 IP 打开时，总线、ERPNext 地址里的 localhost 换成这个 IP
- 启动脚本：Windows 脚本存成带 BOM 的 UTF-8；首次启动生成老师密码；不挂企业零件库

枢纽不启动总线和数据库（WQ_HUB_NO_START=1）。
"""
import base64
import hashlib
import hmac
import importlib
import json
import os

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # factory/
LOCAL = os.path.join(ROOT, "local")


class _Teach:
    def start(self, name):
        pass


def _hub(monkeypatch, edition, password="Laoshi-2026"):
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.delenv("WQ_AUTH", raising=False)
    monkeypatch.setenv("WQ_SECRET", "test-secret")
    if edition:
        monkeypatch.setenv("WQ_EDITION", edition)
    else:
        monkeypatch.delenv("WQ_EDITION", raising=False)
    if password is None:
        monkeypatch.delenv("WQ_TEACHER_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("WQ_TEACHER_PASSWORD", password)
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    app_mod.H.teach = _Teach()
    return app_mod


@pytest.fixture()
def local(monkeypatch):
    app_mod = _hub(monkeypatch, "local")
    yield app_mod
    monkeypatch.undo()
    importlib.reload(app_mod)


@pytest.fixture()
def server(monkeypatch):
    app_mod = _hub(monkeypatch, None, None)
    yield app_mod
    monkeypatch.undo()
    importlib.reload(app_mod)


def _login(c, **body):
    return c.post("/api/login", json=body)


def test_local_student_gets_student_roles_only(local):
    c = TestClient(local.app)
    info = c.get("/api/login/info").json()
    assert info["edition"] == "local" and info["teacher_password"] is True and "manager" not in info["student_roles"]
    r = _login(c, name="王小明", role="planner", mode="teach")
    assert r.status_code == 200, r.text
    u = r.json()["user"]
    assert u["teacher"] is False and u["role"] == "planner" and u["mode"] == "teach"
    for role in ("quality", "maintenance", "lead", "service", "safety", "operator", "engineer"):
        assert _login(c, name="王小明", role=role).json()["user"]["role"] == role
    # 学生不能当厂长；要生产模式也只给教学模式
    assert _login(c, name="王小明", role="manager").status_code == 403
    assert _login(c, name="王小明", role="planner", mode="prod").json()["user"]["mode"] == "teach"
    # 不选角色：学生缺省计划员
    assert _login(c, name="王小明").json()["user"]["role"] == "planner"


def test_local_student_cannot_switch_to_teacher_things(local):
    c = TestClient(local.app)
    tok = _login(c, name="王小明", role="planner").json()["token"]
    h = {"x-wq-token": tok}
    assert c.post("/api/me/switch", json={"role": "manager"}, headers=h).status_code == 403
    assert c.post("/api/me/switch", json={"mode": "prod"}, headers=h).status_code == 403
    assert c.post("/api/me/switch", json={"role": "quality"}, headers=h).json()["user"]["role"] == "quality"


def test_local_teacher_needs_password(local):
    c = TestClient(local.app)
    r = _login(c, name="李老师", role="manager", mode="prod", teacher_password="Laoshi-2026")
    assert r.status_code == 200, r.text
    u = r.json()["user"]
    assert u["teacher"] is True and u["role"] == "manager" and u["mode"] == "prod"
    assert _login(c, name="李老师", teacher_password="Laoshi-2026").json()["user"]["role"] == "manager"
    bad = _login(c, name="李老师", role="manager", teacher_password="wrong")
    assert bad.status_code == 403 and "老师密码不对" in bad.json()["detail"]


def test_local_wrong_password_locks_after_five(local):
    c = TestClient(local.app)
    for _ in range(5):
        assert _login(c, name="x", teacher_password="nope").status_code == 403
    r = _login(c, name="x", teacher_password="Laoshi-2026")
    assert r.status_code == 429
    # 学生照常能进
    assert _login(c, name="王小明", role="planner").status_code == 200


def test_local_without_teacher_password_nobody_is_teacher(monkeypatch):
    app_mod = _hub(monkeypatch, "local", "")
    try:
        c = TestClient(app_mod.app)
        r = _login(c, name="李老师", teacher_password="anything")
        assert r.status_code == 403 and "没有设老师密码" in r.json()["detail"]
        assert _login(c, name="王小明", role="planner").json()["user"]["teacher"] is False
    finally:
        monkeypatch.undo()
        importlib.reload(app_mod)


def test_local_old_token_without_teacher_flag_is_student(local):
    raw = base64.urlsafe_b64encode(json.dumps({"name": "旧凭证", "role": "manager", "mode": "teach"}).encode()).decode()
    tok = raw + "." + hmac.new(b"test-secret", raw.encode(), hashlib.sha256).hexdigest()[:32]
    assert local.user_of(tok)["teacher"] is False


def test_server_name_login_unchanged(server):
    """不是本地版（开发机、CI 演练）：填名字的人都是老师，和以前一样"""
    c = TestClient(server.app)
    info = c.get("/api/login/info").json()
    assert info["edition"] == "server" and info["teacher_password"] is False
    u = _login(c, name="测试教师", role="manager", mode="prod").json()["user"]
    assert u["teacher"] is True and u["role"] == "manager" and u["mode"] == "prod"
    assert _login(c, name="测试学生").json()["user"]["role"] == "manager"


def test_config_edition_and_lan_host(local, monkeypatch):
    monkeypatch.setenv("WQ_MQTT_WS", "ws://localhost:9001")
    monkeypatch.setenv("WQ_ERPNEXT_URL", "http://localhost:8091")
    c = TestClient(local.app, base_url="http://192.168.1.20:8100")
    cfg = c.get("/api/config").json()
    assert cfg["edition"] == "local"
    assert cfg["mqtt_ws"] == "ws://192.168.1.20:9001" and cfg["erpnext_url"] == "http://192.168.1.20:8091"
    cfg = TestClient(local.app, base_url="http://localhost:8100").get("/api/config").json()
    assert cfg["mqtt_ws"] == "ws://localhost:9001"


def test_config_server_no_rewrite(server, monkeypatch):
    monkeypatch.setenv("WQ_MQTT_WS", "ws://localhost:9001")
    cfg = TestClient(server.app, base_url="http://192.168.1.20:8100").get("/api/config").json()
    assert cfg["edition"] == "server" and cfg["mqtt_ws"] == "ws://localhost:9001"


# ---------------------------------------------------------------- 启动脚本
def _read(name):
    with open(os.path.join(LOCAL, name), "rb") as f:
        return f.read()


@pytest.mark.parametrize("name", ["start.ps1", "stop.ps1"])
def test_windows_scripts_are_utf8_with_bom(name):
    b = _read(name)
    assert b.startswith(b"\xef\xbb\xbf"), name + " 要存成带 BOM 的 UTF-8（Windows PowerShell 5.1 才不会读成乱码）"
    b.decode("utf-8")


def test_update_ps1_is_utf8_with_bom():
    with open(os.path.join(ROOT, "digital", "update.ps1"), "rb") as f:
        assert f.read().startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize("name", ["start.sh", "start.ps1"])
def test_start_scripts_local_defaults(name):
    s = _read(name).decode("utf-8-sig")
    for key in ("WQ_EDITION", "WQ_TEACHER_PASSWORD", "WQ_SECRET", "WQ_PLANT_FILE", "mock", "/api/health"):
        assert key in s, (name, key)
    assert "FAP_ENTERPRISE_LIBRARY" not in s          # 企业零件库是那边的企业功能，这边不挂
    assert "240" in s or "120" in s                   # 最多等 4 分钟


def test_readme_for_lab_admin():
    s = _read("README.md").decode("utf-8")
    for key in ("Docker Desktop", "内存", "8100", "IP", "stop", "WQ_TEACHER_PASSWORD", "更新"):
        assert key in s, key
