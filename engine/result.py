"""校验结果与整体结论（实施细则第七节，ADR-0016、ADR-0025）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PASS, WARN, FAIL, UNKNOWN, NA = "pass", "warn", "fail", "unknown", "not_applicable"
# 合并多个子结果时取最严重的：fail > unknown > warn > pass；not_applicable 不参与
_SEVERITY = {PASS: 0, WARN: 1, UNKNOWN: 2, FAIL: 3}


def worst(statuses) -> str:
    """多个状态合并：取最严重的；全部不适用（或为空）时为 not_applicable。"""
    applicable = [s for s in statuses if s != NA]
    if not applicable:
        return NA
    return max(applicable, key=_SEVERITY.__getitem__)


@dataclass
class Finding:
    """一项校验中的一个具体判定（一个连接、一个公式、一个子条件）。"""

    status: str
    message: str
    ports: list[str] = field(default_factory=list)
    measured: float | None = None
    limit: float | None = None
    unit: str | None = None

    @property
    def margin_ratio(self) -> float | None:
        """余量：(限值 − 测量值) / 限值；“测量值须不大于限值”的判定才有意义。"""
        if self.measured is None or self.limit in (None, 0):
            return None
        return (self.limit - self.measured) / self.limit

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "message": self.message}
        if self.ports:
            out["ports"] = list(self.ports)
        if self.measured is not None:
            out.update(measured=self.measured, limit=self.limit, unit=self.unit, margin_ratio=self.margin_ratio)
        return out


@dataclass
class CheckResult:
    check: str
    findings: list[Finding] = field(default_factory=list)
    reason: str | None = None  # not_applicable 时须写明原因

    @property
    def status(self) -> str:
        if not self.findings:
            return NA
        return worst(f.status for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"check": self.check, "status": self.status}
        if self.status == NA:
            out["message"] = self.reason or "不适用"
            return out
        # 主要判定：与整体状态相同的第一条；单条时即实施细则第七节的格式
        main = next(f for f in self.findings if f.status == self.status)
        out.update({k: v for k, v in main.to_dict().items() if k != "status"})
        if len(self.findings) > 1:
            out["findings"] = [f.to_dict() for f in self.findings]
        return out


def not_applicable(check: str, reason: str) -> CheckResult:
    return CheckResult(check, [], reason)


def overall(results: list[CheckResult]) -> str:
    """整体结论：有 fail 即 fail；否则有 unknown 即 unknown；否则有 warn 即 warn；适用项全 pass 为 pass。"""
    status = worst(r.status for r in results)
    return PASS if status == NA else status
