"""浮动席位与离线激活（ADR-0066 第 6 项）：超额拒绝、过期收回、宽限到期、激活码。"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error

import pytest

from licensing import fingerprint as fp
from licensing import issue
from licensing.license import verify
from licensing.seat_client import SeatClient
from licensing.seats import SeatPool, SeatsFull, grace_left


def test_pool_limits_and_expiry():
    pool = SeatPool(2, ttl_s=60)
    a = pool.lease("pc-a", "张三", "PC-A", 0)
    pool.lease("pc-b", "李四", "PC-B", 1)
    with pytest.raises(SeatsFull, match="张三"):
        pool.lease("pc-c", "王五", "PC-C", 2)
    assert pool.lease("pc-a", "张三", "PC-A", 3).lease_id == a.lease_id      # 同一台电脑重启：拿回原席位
    assert pool.renew(a.lease_id, 50) is not None
    assert pool.lease("pc-c", "王五", "PC-C", 70).user == "王五"              # 李四 61 秒没续租，被收回
    assert pool.renew("nope", 70) is None
    assert pool.release(a.lease_id) and not pool.release(a.lease_id)
    assert [x.user for x in pool.active(80)] == ["王五"]


def test_pool_concurrent_over_limit():
    import threading

    pool, lock, got, full = SeatPool(3), threading.Lock(), [], []

    def take(i):
        with lock:                                   # 服务端用锁串行（seats_api.Seats）
            try:
                got.append(pool.lease(f"pc-{i}", f"u{i}", "h", 0))
            except SeatsFull:
                full.append(i)

    ts = [threading.Thread(target=take, args=(i,)) for i in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(got) == 3 and len(full) == 7


def test_grace_left():
    now = dt.datetime(2026, 10, 9, 12, tzinfo=dt.UTC)
    assert grace_left(None, now) == 0
    assert grace_left((now - dt.timedelta(days=2)).isoformat(), now) == pytest.approx(5)
    assert grace_left((now - dt.timedelta(days=8)).isoformat(), now) < 0
    assert grace_left((now + dt.timedelta(days=1)).isoformat(), now) == 0      # 时钟往回拨过
    assert grace_left("乱写", now) == 0


class FakeServer:
    def __init__(self):
        self.pool, self.down, self.calls = SeatPool(1, ttl_s=900), False, []

    def __call__(self, path, body):
        self.calls.append(path)
        if self.down:
            raise urllib.error.URLError("Connection refused")
        if path == "/api/seats/lease":
            try:
                x = self.pool.lease(body["client_id"], body["user"], body["host"], 0)
            except SeatsFull as exc:
                return 409, {"detail": str(exc)}
            return 200, {"lease_id": x.lease_id, "licensee": "示例机械", "features": ["seats"], "seats": 1, "used": 1}
        if path == "/api/seats/renew":
            x = self.pool.renew(body["lease_id"], 0)
            if x is None:
                return 404, {"detail": "租约已过期或不存在，请重新租"}
            return 200, {"lease_id": x.lease_id, "licensee": "示例机械", "features": ["seats"], "seats": 1, "used": 1}
        if path == "/api/seats/release":
            return 200, {"released": self.pool.release(body["lease_id"])}
        raise AssertionError(path)


def test_client_lease_grace_and_full(tmp_path):
    server = FakeServer()
    clock = {"t": dt.datetime(2026, 10, 1, tzinfo=dt.UTC)}
    c = SeatClient("https://factory.example.com", cache=tmp_path / "seat.json", now=lambda: clock["t"], opener=server)
    r = c.acquire("张三", "PC-A", cid="pc-a")
    assert r["ok"] and not r["grace"] and r["features"] == ["seats"]
    assert json.loads((tmp_path / "seat.json").read_text(encoding="utf-8"))["licensee"] == "示例机械"
    other = SeatClient("https://factory.example.com", cache=tmp_path / "b.json", opener=server)
    r2 = other.acquire("李四", "PC-B", cid="pc-b")
    assert not r2["ok"] and "席位已满" in r2["reason"]
    # 服务器断了：宽限内照常
    server.down = True
    clock["t"] += dt.timedelta(days=3)
    r = c.renew("张三")
    assert r["ok"] and r["grace"] and "4.0 天" in r["reason"]
    clock["t"] += dt.timedelta(days=5)
    r = c.renew("张三")
    assert not r["ok"] and "宽限" in r["reason"]
    # 服务器回来、租约已被收回：自动重新租
    server.down = False
    server.pool = SeatPool(1)
    r = c.renew("张三")
    assert r["ok"] and server.calls[-2:] == ["/api/seats/renew", "/api/seats/lease"]
    c.release()
    assert server.pool.active(0) == []


def test_activation_code_roundtrip(tmp_path, monkeypatch):
    me = "ABCD-EF01-2345-6789-ABCD-EF01"
    code = fp.activation_code(me)
    assert code.startswith("FAP1-") and fp.parse_activation(code.lower()) == me
    bad = code[:-1] + ("0" if code[-1] != "0" else "1")
    with pytest.raises(ValueError, match="抄错"):
        fp.parse_activation(bad)
    with pytest.raises(ValueError, match="格式"):
        fp.parse_activation("FAP1-1234")
    priv, pub = issue.keygen()
    monkeypatch.setenv("FAP_LICENSE_PRIVATE_KEY", priv)
    out = tmp_path / "n.json"
    assert issue.main(["sign", "--key-id", "t", "--licensee", "小厂", "--expires", "2099-12-31", "--kind", "node",
                       "--features", "parts-subscription", "--activation", code, "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert verify(doc, {"t": pub}, dt.date(2026, 10, 9), node=me).valid
    assert issue.main(["sign", "--key-id", "t", "--licensee", "小厂", "--expires", "2099-12-31", "--kind", "node",
                       "--features", "x", "--activation", bad, "--out", str(out)]) == 2


@pytest.mark.freecad
def test_license_dialog(tmp_path, monkeypatch):
    import os

    import FreeCADGui

    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    FreeCADGui.showMainWindow()
    from freecad_addon.core import library_choice
    from freecad_addon.gui import license_dialog
    from licensing import runtime

    monkeypatch.setattr(library_choice, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(runtime, "USER_LICENSE", tmp_path / "license.json")
    dlg = license_dialog.LicenseDialog()
    assert "没有授权文件" in dlg.status.text()
    dlg.auto.setChecked(True)
    dlg.reject()
    assert library_choice.read_settings()["seat_auto"] is True
    license_dialog.start_seat_if_configured()                 # 没设工厂地址：不租
    assert license_dialog.SeatKeeper._instance is None
