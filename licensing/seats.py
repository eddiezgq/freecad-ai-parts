"""浮动席位（ADR-0066 第 6 项）：企业数字工厂服务器上的席位池。纯逻辑，时间由调用方给。

- 工作台启动时租一个席位（lease），定时续租（renew），关闭时归还（release）
- 租约过期（ttl 内没续租）自动收回；同一台电脑（client_id）再租拿回原来那个席位
- 席位满了拒绝
宽限：工作台连不上服务器时，上次成功续租后 GRACE_DAYS 天内照常可用（grace_left）。
"""

from __future__ import annotations

import datetime as dt
import secrets
from dataclasses import dataclass

GRACE_DAYS = 7
TTL_S = 15 * 60


class SeatsFull(RuntimeError):
    pass


@dataclass
class Lease:
    lease_id: str
    client_id: str
    user: str
    host: str
    started: float
    expires: float

    def public(self) -> dict:
        return {"lease_id": self.lease_id, "user": self.user, "host": self.host,
                "started": self.started, "expires": self.expires}


class SeatPool:
    def __init__(self, seats: int, ttl_s: float = TTL_S):
        self.seats, self.ttl_s = seats, ttl_s
        self._leases: dict[str, Lease] = {}

    def _prune(self, now: float) -> None:
        for lid in [lid for lid, x in self._leases.items() if x.expires < now]:
            del self._leases[lid]

    def active(self, now: float) -> list[Lease]:
        self._prune(now)
        return sorted(self._leases.values(), key=lambda x: x.started)

    def lease(self, client_id: str, user: str, host: str, now: float) -> Lease:
        self._prune(now)
        for x in self._leases.values():
            if x.client_id == client_id:
                x.user, x.host, x.expires = user, host, now + self.ttl_s
                return x
        if len(self._leases) >= self.seats:
            users = "、".join(f"{x.user}（{x.host}）" for x in self.active(now))
            raise SeatsFull(f"席位已满（{self.seats} 个）：{users}")
        x = Lease(secrets.token_urlsafe(16), client_id, user, host, now, now + self.ttl_s)
        self._leases[x.lease_id] = x
        return x

    def renew(self, lease_id: str, now: float) -> Lease | None:
        self._prune(now)
        x = self._leases.get(lease_id)
        if x is not None:
            x.expires = now + self.ttl_s
        return x

    def release(self, lease_id: str) -> bool:
        return self._leases.pop(lease_id, None) is not None


def grace_left(last_ok: str | None, now: dt.datetime, days: int = GRACE_DAYS) -> float:
    """离线宽限还剩几天（≤ 0 表示已过）；没有成功租过就是 0。"""
    if not last_ok:
        return 0.0
    try:
        t = dt.datetime.fromisoformat(last_ok)
    except ValueError:
        return 0.0
    if t > now:                                      # 本机时钟被往回拨过：不给宽限
        return 0.0
    return days - (now - t).total_seconds() / 86400
