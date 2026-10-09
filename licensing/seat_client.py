"""工作台一侧的浮动席位（ADR-0066 第 6 项）：向企业数字工厂服务器租席位；连不上时按上次成功的记录给 7 天宽限。

记录存本机用户目录 ~/.freecad-ai-parts/seat.json（被授权方、功能、上次成功时间），不存授权文件本身。
"""

from __future__ import annotations

import datetime as dt
import json
import socket
import ssl
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from licensing.seats import GRACE_DAYS, grace_left

CACHE = Path.home() / ".freecad-ai-parts" / "seat.json"
CLIENT_ID = Path.home() / ".freecad-ai-parts" / "client_id"


def client_id(path: Path | None = None) -> str:
    path = path or CLIENT_ID
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        cid = uuid.uuid4().hex
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cid, encoding="utf-8")
        return cid


class SeatClient:
    def __init__(self, url: str, cafile: str | None = None, timeout: float = 10, cache: Path | None = None,
                 now=None, opener=None):
        self.url, self.cafile, self.timeout = url.rstrip("/"), cafile or None, timeout
        self.cache = cache or CACHE
        self.now = now or (lambda: dt.datetime.now(dt.UTC))
        self._open = opener or self._urlopen
        self.lease_id: str | None = None

    def _urlopen(self, path: str, body: dict | None):
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(self.url + path, data=data, headers={"Content-Type": "application/json"},
                                     method="POST")
        ctx = ssl.create_default_context(cafile=self.cafile) if self.cafile and self.url.startswith("https") else None
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as r:  # 企业自己的工厂服务器
                return 200, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read())
            except ValueError:
                return exc.code, {}

    def _save(self, info: dict) -> None:
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache.write_text(json.dumps({**info, "last_ok": self.now().isoformat()}, ensure_ascii=False),
                              encoding="utf-8")

    def _cached(self) -> dict:
        try:
            return json.loads(self.cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _offline(self, why: str) -> dict:
        c = self._cached()
        left = grace_left(c.get("last_ok"), self.now())
        if left > 0 and c.get("features"):
            return {"ok": True, "grace": True, "licensee": c.get("licensee", ""), "features": c["features"],
                    "reason": f"连不上工厂服务器（{why}），离线宽限还剩 {left:.1f} 天"}
        return {"ok": False, "grace": False, "features": [],
                "reason": f"连不上工厂服务器（{why}），离线宽限（{GRACE_DAYS} 天）已过或从未租到席位"}

    def _call(self, path: str, body: dict) -> dict:
        try:
            code, out = self._open(path, body)
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            return self._offline(str(getattr(exc, "reason", exc)))
        if code == 200 and out.get("lease_id"):
            self.lease_id = out["lease_id"]
            info = {"licensee": out.get("licensee", ""), "features": out.get("features", [])}
            self._save(info)
            return {"ok": True, "grace": False, **info, "reason": f"已租到席位（{out.get('used')}/{out.get('seats')}）"}
        return {"ok": False, "grace": False, "features": [], "reason": out.get("detail") or f"工厂返回 {code}"}

    def acquire(self, user: str, host: str | None = None, cid: str | None = None) -> dict:
        return self._call("/api/seats/lease", {"client_id": cid or client_id(), "user": user,
                                               "host": host or socket.gethostname()})

    def renew(self, user: str = "") -> dict:
        if not self.lease_id:
            return self.acquire(user)
        r = self._call("/api/seats/renew", {"lease_id": self.lease_id})
        if not r["ok"] and not r.get("grace") and "过期" in r["reason"]:
            return self.acquire(user)                       # 服务器重启或租约过期：重新租
        return r

    def release(self) -> None:
        if self.lease_id:
            try:
                self._open("/api/seats/release", {"lease_id": self.lease_id})
            except (urllib.error.URLError, OSError):
                pass
            self.lease_id = None
