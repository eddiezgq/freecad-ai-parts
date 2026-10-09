"""签发授权（ADR-0066 第 5 项）。私钥只从环境变量 FAP_LICENSE_PRIVATE_KEY 读。

    python -m licensing.issue keygen                         # 生成一对密钥：私钥自己保管，公钥加到 licensing/keys.py
    python -m licensing.issue sign --key-id k2026 --licensee "某某机械" --expires 2027-12-31 \\
        --kind floating --seats 5 --features parts-subscription,seats --out 某某机械.license.json
    python -m licensing.issue sign ... --kind node --node XXXX-XXXX-...   # 单机授权，node 为客户的机器指纹
    python -m licensing.issue check 某某机械.license.json [--node 指纹]   # 用 keys.py 里的公钥校验
    python -m licensing.issue fingerprint                    # 本机指纹
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path

from licensing import keys
from licensing.fingerprint import fingerprint
from licensing.license import LicenseError, sign, verify


def keygen() -> tuple[str, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    k = Ed25519PrivateKey.generate()
    raw = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode(), base64.b64encode(pub).decode()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="签发与校验 FreeCAD AI Parts 授权")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen")
    s = sub.add_parser("sign")
    s.add_argument("--key-id", required=True)
    s.add_argument("--licensee", required=True)
    s.add_argument("--expires", required=True)
    s.add_argument("--kind", choices=("floating", "node"), required=True)
    s.add_argument("--seats", type=int, default=1)
    s.add_argument("--features", required=True, help="逗号分隔")
    s.add_argument("--node", default=None)
    s.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("check")
    c.add_argument("file", type=Path)
    c.add_argument("--node", default=None)
    sub.add_parser("fingerprint")
    a = p.parse_args(argv)
    if a.cmd == "keygen":
        priv, pub = keygen()
        print("私钥（只存在你自己的保险处，设为环境变量 FAP_LICENSE_PRIVATE_KEY；不要发给任何人、不要进仓库）：")
        print(priv)
        print("公钥（加到 licensing/keys.py 的 PUBLIC_KEYS，起一个编号，如 \"k2026\"）：")
        print(pub)
        return 0
    if a.cmd == "fingerprint":
        print(fingerprint())
        return 0
    if a.cmd == "check":
        v = verify(json.loads(a.file.read_text(encoding="utf-8")), keys.PUBLIC_KEYS, dt.datetime.now().astimezone().date(), a.node)
        print(v.reason)
        return 0 if v.valid else 1
    priv = os.environ.get("FAP_LICENSE_PRIVATE_KEY")
    if not priv:
        print("没有设置环境变量 FAP_LICENSE_PRIVATE_KEY（签发私钥）", file=sys.stderr)
        return 2
    lic = {"id": str(uuid.uuid4()), "key_id": a.key_id, "licensee": a.licensee, "issued": dt.datetime.now().astimezone().date().isoformat(),
           "expires": a.expires, "kind": a.kind, "seats": a.seats,
           "features": [f.strip() for f in a.features.split(",") if f.strip()]}
    if a.node:
        lic["node"] = a.node
    try:
        doc = sign(lic, priv)
    except LicenseError as exc:
        print(f"不能签发：{exc}", file=sys.stderr)
        return 2
    a.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已签发：{a.out}（{a.licensee}，{a.kind}，{a.seats} 席，到 {a.expires}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
