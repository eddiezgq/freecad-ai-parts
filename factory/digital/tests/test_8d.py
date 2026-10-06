# -*- coding: utf-8 -*-
"""第 13 轮 N7：问题情景与 8D——老师注入、学生填 8D、措施批准后下发、用措施后的数据验证、关闭。"""
import datetime as dt
import os
import random

import pytest

import wqbus

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0] + "/wq_8d_test"


@pytest.fixture
def db():
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(DSN.rsplit("/", 1)[0] + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_8d_test with (force)")
            c.execute("create database wq_8d_test")
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    d = DB(DSN)
    d.init()
    return d


def measure(db, n, mean, sd, lo=35.002, hi=35.018, seed=1, when=None):
    rng = random.Random(seed)
    for i in range(n):
        v = round(rng.gauss(mean, sd), 4)
        m = wqbus.make("quality.measurement", "sim/qc-01", {
            "part_serial": f"P{seed}-{i}", "item": "SH-301", "characteristic": "bearing_seat_d35_r", "nominal_mm": 35.010,
            "lower_tol_mm": lo, "upper_tol_mm": hi, "value_mm": v, "result": "pass" if lo <= v <= hi else "fail"}, mode="teach")
        if when:
            m["ts"] = when.isoformat().replace("+00:00", "Z")
        db.insert_message("wq/gearbox/quality/qc-01/measurement", m)


def test_full_8d_cycle(db):
    from hub import qproblem as Q
    sent = []

    def send(cmd, **extra):
        sent.append((cmd, extra))
    Q.inject(db, send, "teach", "老师", "tailstock_offset")
    assert sent[-1] == ("set_problem", {"problem": "tailstock_offset"}) and Q.active(db, "teach")[0]["problem"] == "tailstock_offset"
    with pytest.raises(PermissionError):
        Q.inject(db, send, "prod", "老师", "tailstock_offset")
    # 措施前：右轴承位偏大、超差
    measure(db, 30, 35.0145, 0.0018, seed=1, when=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1))
    s = Q.create(db, "teach", "学生甲", "u1", "SH-301", "bearing_seat_d35_r", "右轴承位偏大，Cpk 低", {"d2": "右轴承位比左大约 0.004"})
    with pytest.raises(ValueError):
        Q.submit_fix(db, s["id"])                                   # 没选措施
    Q.update(db, s["id"], {"d1": "甲乙丙", "d3": "全检、隔离", "d4": "尾座偏移 → 锥度", "d5": "校正尾座"}, fix="align_tailstock")
    s = Q.submit_fix(db, s["id"])
    assert s["status"] == "submitted"
    s = Q.decide_fix(db, send, s["id"], "老师", True)
    assert sent[-1] == ("apply_fix", {"fix": "align_tailstock"}) and s["status"] == "approved"
    assert Q.active(db, "teach") == []                               # 对症：问题情景已消除
    with pytest.raises(ValueError):
        Q.close(db, s["id"], "学生甲")                                # 还没验证
    measure(db, 12, 35.0100, 0.0012, seed=2, when=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5))
    v = Q.verify(db, s["id"])
    assert v["before"]["n"] == 30 and v["before"]["Cpk"] < 1.0
    assert v["after"]["n"] == 12 and v["after"]["Cpk"] >= 1.33 and v["effective"]
    with pytest.raises(ValueError):
        Q.close(db, s["id"], "学生甲")                                # 没写 D7
    Q.update(db, s["id"], {"d7": "磨床点检表加尾座校正项；工序卡磨外圆加首件测锥度"})
    assert Q.close(db, s["id"], "学生甲")["status"] == "closed"


def test_wrong_fix_does_not_clear_the_problem(db):
    from hub import qproblem as Q
    send = lambda *a, **k: None  # noqa: E731
    Q.inject(db, send, "teach", "老师", "center_hole")
    s = Q.create(db, "teach", "学生乙", "u2", "SH-301", "runout_bearing", "圆跳动超差",
                 {"d1": "乙", "d2": "跳动 0.013", "d3": "全检", "d4": "砂轮", "d5": "换砂轮"})
    Q.update(db, s["id"], {}, fix="change_wheel")
    Q.submit_fix(db, s["id"])
    Q.decide_fix(db, send, s["id"], "老师", True)
    assert [a["problem"] for a in Q.active(db, "teach")] == ["center_hole"]


def test_api_teacher_injects_student_fills_8d_teacher_approves(db, monkeypatch):
    """用老师和学生两个账号走一遍：学生看不到问题清单；老师注入、批准；措施下发到仿真车间。"""
    import importlib
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_AUTH", "wenquest")
    monkeypatch.setenv("WQ_SSO_URL", "https://learn.example.com/api/v1/auth/sso")
    monkeypatch.setenv("WQ_SECRET", "test-secret")
    import httpx
    from test_auth import ACCOUNTS, _Resp, _Teach, _client

    def fake_get(url, cookies=None, timeout=None):
        u = ACCOUNTS.get((cookies or {}).get("wq_sso", ""))
        return _Resp(200, {"token": "x", "user": u}) if u else _Resp(401, {"code": "not_logged_in"})
    monkeypatch.setattr(httpx, "get", fake_get)
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    app_mod.H.teach = _Teach()
    app_mod.H.db = db
    sent = []

    class _MES:
        def command(self, unit, cmd, mode, user, work_order=None, operation=None, **extra):
            sent.append((unit, cmd, extra))
    app_mod.H.mes = _MES()
    try:
        stu, tea = _client(app_mod, "stu-cookie"), _client(app_mod, "tea-cookie")
        hs = {"x-wq-token": stu.post("/api/login", json={"role": "quality", "mode": "teach"}).json()["token"]}
        ht = {"x-wq-token": tea.post("/api/login", json={"role": "quality", "mode": "teach"}).json()["token"]}
        assert "problems" not in stu.get("/api/quality/problems/catalog", headers=hs).json()
        assert "tailstock_offset" in tea.get("/api/quality/problems/catalog", headers=ht).json()["problems"]
        assert stu.post("/api/quality/problems", json={"problem": "tailstock_offset"}, headers=hs).status_code == 403
        r = tea.post("/api/quality/problems", json={"problem": "tailstock_offset"}, headers=ht)
        assert r.status_code == 200 and sent[-1] == ("sim", "set_problem", {"problem": "tailstock_offset"})
        q = stu.post("/api/quality/8d", json={"characteristic": "bearing_seat_d35_r", "title": "右轴承位偏大"}, headers=hs).json()
        d = {"d1": "甲", "d2": "右大左小", "d3": "全检", "d4": "尾座偏移", "d5": "校正尾座"}
        assert stu.post(f"/api/quality/8d/{q['id']}", json={"action": "save", "d": d, "fix": "align_tailstock"}, headers=hs).status_code == 200
        assert stu.post(f"/api/quality/8d/{q['id']}", json={"action": "submit"}, headers=hs).json()["status"] == "submitted"
        assert stu.post(f"/api/quality/8d/{q['id']}", json={"action": "approve"}, headers=hs).status_code == 403
        assert tea.post(f"/api/quality/8d/{q['id']}", json={"action": "approve"}, headers=ht).json()["status"] == "approved"
        assert sent[-1] == ("sim", "apply_fix", {"fix": "align_tailstock"})
        assert tea.get("/api/quality/problems", headers=ht).json() == []
    finally:
        for k in ("WQ_AUTH", "WQ_SSO_URL"):
            os.environ.pop(k, None)
        importlib.reload(app_mod)


def test_verify_stats_one_sided():
    """跳动、对称度只有上限（下限 0）：验证用单边 Cpu，不按双边公式把能力算低（教材《机械设计》4.9.3 节）。"""
    from hub import qproblem as Q
    rng = random.Random(3)
    rows = [{"data": {"value_mm": abs(rng.gauss(0.004, 0.0012)), "lower_tol_mm": 0.0, "upper_tol_mm": 0.012, "result": "pass"}}
            for _ in range(20)]
    s = Q._stats(rows)
    assert s["one_sided"] and s["Cpk"] > 1.33                       # 双边公式只有约 1.1
    two = [{"data": {"value_mm": rng.gauss(35.010, 0.0012), "lower_tol_mm": 35.002, "upper_tol_mm": 35.018, "result": "pass"}}
           for _ in range(20)]
    assert not Q._stats(two)["one_sided"]
