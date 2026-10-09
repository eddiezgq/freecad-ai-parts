# -*- coding: utf-8 -*-
"""浮动席位（ADR-0066 第 6 项）：企业的授权文件装在工厂服务器上（WQ_LICENSE_FILE，企业安装版放在 plant/license.json），
FreeCAD 工作台来这里租、续、还席位。没有授权文件或授权无效时拒绝租用；工厂自身的功能不受影响。"""
import datetime as dt
import json
import os
import threading
import time
from pathlib import Path

from fastapi import Body, HTTPException

from licensing import keys
from licensing.license import verify
from licensing.seats import SeatPool, SeatsFull

FEATURE = "seats"


class Seats:
    def __init__(self, path, public_keys=None, clock=time.time, today=None):
        self.path, self.public_keys = Path(path) if path else None, public_keys
        self.clock, self.today = clock, today or (lambda: dt.datetime.now().astimezone().date())
        self.lock = threading.Lock()
        self.pool, self.verdict, self._mtime = None, None, None

    def _load(self):
        """授权文件改了就重读（升级换授权不用重启）。"""
        if self.path is None or not self.path.is_file():
            self.pool, self.verdict, self._mtime = None, None, None
            return
        m = self.path.stat().st_mtime
        if m == self._mtime and self.verdict is not None:
            return
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        v = verify(doc, keys.PUBLIC_KEYS if self.public_keys is None else self.public_keys, self.today())
        old = self.pool
        self.pool = SeatPool(v.seats) if v.valid and v.kind == "floating" and FEATURE in v.features else None
        if self.pool and old:
            self.pool._leases = old._leases
        self.verdict, self._mtime = v, m

    def status(self):
        with self.lock:
            self._load()
            now = self.clock()
            if self.verdict is None:
                return {"licensed": False, "reason": "工厂服务器上没有授权文件"}
            v = self.verdict
            out = {"licensed": bool(self.pool), "reason": v.reason, "licensee": v.licensee,
                   "expires": v.expires, "seats": v.seats, "features": sorted(v.features)}
            if v.kind == "node":
                out["reason"] = "这是单机授权，不是浮动席位授权，不能在工厂服务器上发席位"
            elif v.valid and not self.pool:
                out["reason"] = "授权有效，但不含浮动席位（seats）功能"
            if self.pool:
                out["leases"] = [x.public() for x in self.pool.active(now)]
                out["used"] = len(out["leases"])
            return out

    def _ok(self, x):
        v = self.verdict
        return {"lease_id": x.lease_id, "expires": x.expires, "ttl_s": self.pool.ttl_s, "licensee": v.licensee,
                "features": sorted(v.features), "seats": v.seats, "used": len(self.pool.active(self.clock()))}

    def lease(self, client_id, user, host):
        with self.lock:
            self._load()
            if not self.pool:
                raise HTTPException(403, (self.verdict.reason if self.verdict and not self.verdict.valid
                                          else "工厂服务器上没有浮动席位授权"))
            if not client_id:
                raise HTTPException(400, "缺 client_id")
            try:
                return self._ok(self.pool.lease(client_id, user or "?", host or "?", self.clock()))
            except SeatsFull as exc:
                raise HTTPException(409, str(exc)) from exc

    def renew(self, lease_id):
        with self.lock:
            self._load()
            if not self.pool:
                raise HTTPException(403, "工厂服务器上没有有效的浮动席位授权")
            x = self.pool.renew(lease_id or "", self.clock())
            if x is None:
                raise HTTPException(404, "租约已过期或不存在，请重新租")
            return self._ok(x)

    def release(self, lease_id):
        with self.lock:
            return {"released": bool(self.pool and self.pool.release(lease_id or ""))}


def mount(app, seats=None):
    S = seats or Seats(os.environ.get("WQ_LICENSE_FILE") or "")

    @app.get("/api/seats")
    def seats_status():
        return S.status()

    @app.post("/api/seats/lease")
    def seats_lease(body: dict = Body(...)):
        return S.lease(str(body.get("client_id") or ""), str(body.get("user") or "")[:60], str(body.get("host") or "")[:60])

    @app.post("/api/seats/renew")
    def seats_renew(body: dict = Body(...)):
        return S.renew(str(body.get("lease_id") or ""))

    @app.post("/api/seats/release")
    def seats_release(body: dict = Body(...)):
        return S.release(str(body.get("lease_id") or ""))

    return S
