"""授权文件的格式、签名与校验（ADR-0066 第 5 项）。

授权文件（JSON）：
    {"license": {"id", "key_id", "licensee", "issued", "expires", "kind", "seats", "features", "node"?},
     "signature": "<Ed25519 签名的 base64>"}
- kind：floating（浮动席位，装在企业数字工厂服务器上）或 node（单机绑定，node 为机器指纹）
- 签名覆盖 license 的规范化 JSON（键排序、无空白、UTF-8）
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

FIELDS = ("id", "key_id", "licensee", "issued", "expires", "kind", "seats", "features")
KINDS = ("floating", "node")


class LicenseError(ValueError):
    pass


@dataclass(frozen=True)
class Verdict:
    valid: bool
    reason: str                                   # 给人看的结论
    licensee: str = ""
    expires: str = ""
    kind: str = ""
    seats: int = 0
    features: frozenset[str] = field(default_factory=frozenset)

    def allows(self, feature: str) -> bool:
        return self.valid and feature in self.features


def canonical(lic: Mapping) -> bytes:
    return json.dumps(lic, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _check_fields(lic: Mapping) -> None:
    missing = [f for f in FIELDS if f not in lic]
    if missing:
        raise LicenseError("授权缺少字段：" + "、".join(missing))
    if lic["kind"] not in KINDS:
        raise LicenseError(f"授权类型只能是 {' / '.join(KINDS)}")
    if lic["kind"] == "node" and not lic.get("node"):
        raise LicenseError("单机授权要有机器指纹 node")
    if not isinstance(lic["seats"], int) or lic["seats"] < 1:
        raise LicenseError("席位数要是正整数")
    if not isinstance(lic["features"], list) or not all(isinstance(f, str) for f in lic["features"]):
        raise LicenseError("features 要是功能名列表")
    for k in ("issued", "expires"):
        dt.date.fromisoformat(lic[k])


def sign(lic: Mapping, private_key_b64: str) -> dict:
    """签发：返回完整的授权文件内容。"""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    _check_fields(lic)
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
    return {"license": dict(lic), "signature": base64.b64encode(key.sign(canonical(lic))).decode()}


def verify(doc: Mapping, public_keys: Mapping[str, str], today: dt.date, node: str | None = None) -> Verdict:
    """校验授权文件。today 由调用方给（纯函数）；node 为本机指纹（单机授权时要）。"""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        lic, sig = doc["license"], doc["signature"]
        _check_fields(lic)
    except (KeyError, TypeError, ValueError) as exc:
        return Verdict(False, f"授权文件格式不对：{exc}")
    pub = public_keys.get(lic["key_id"])
    if not pub:
        return Verdict(False, f"不认识签发它的公钥（{lic['key_id']}）")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(base64.b64decode(sig), canonical(lic))
    except (InvalidSignature, ValueError):
        return Verdict(False, "签名不对：授权文件被改动过，或不是我们签发的")
    info = {"licensee": lic["licensee"], "expires": lic["expires"], "kind": lic["kind"], "seats": lic["seats"],
            "features": frozenset(lic["features"])}
    if dt.date.fromisoformat(lic["issued"]) > today:
        return Verdict(False, f"签发日期 {lic['issued']} 晚于今天，本机日期可能不对", **info)
    if dt.date.fromisoformat(lic["expires"]) < today:
        return Verdict(False, f"授权已于 {lic['expires']} 到期；闭源功能停用，公开功能照常", **info)
    if lic["kind"] == "node" and lic["node"] != node:
        return Verdict(False, "这份单机授权不是这台电脑的（机器指纹不符）", **info)
    return Verdict(True, f"授权有效：{lic['licensee']}，到 {lic['expires']}", **info)
