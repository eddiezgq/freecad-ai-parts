"""零件库订阅包（ADR-0066 第 7 项）：按客户生成、签名、带水印；授权里有 parts-subscription 才加载。

包（zip）：
    manifest.json   {"pack": {customer, issued, version, key_id, count, files: {路径: sha256}}, "signature": …}
    components/<品类>/<id>.json
- 签名覆盖 pack 的规范化 JSON；文件被改、增、删都校验不过
- 水印：每条记录的 note 末尾加一串零宽字符，编码 HMAC(水印密钥, 客户名) 的前 64 位；看不见，复制、另存都在。
  外泄的记录用 trace 对照客户名单找出来源。水印密钥只在签发人的环境变量 FAP_PACK_SECRET 里
- 只收 license 为 partner（厂商授权）或 standard（按标准生成的自有数据）的记录；params-only 等不进收费包

    python -m licensing.parts_pack build --src 组件目录 --customer 某某机械 --version 2026.10 --key-id k2026 --out 包.zip
    python -m licensing.parts_pack check 包.zip
    python -m licensing.parts_pack trace 外泄的记录.json --customers 某某机械,另一家
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import shutil
import sys
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from licensing.license import canonical

ALLOWED = ("partner", "standard")
FEATURE = "parts-subscription"
_ZW = {"0": "\u200b", "1": "\u200c"}
_MARK = "\u2060"


class PackError(ValueError):
    pass


def tag(secret: str, customer: str) -> str:
    return hmac.new(secret.encode(), customer.encode(), hashlib.sha256).hexdigest()[:16]


def _encode(t: str) -> str:
    bits = bin(int(t, 16))[2:].zfill(len(t) * 4)
    return _MARK + "".join(_ZW[b] for b in bits) + _MARK


def extract_tag(text: str) -> str | None:
    if _MARK not in (text or ""):
        return None
    inner = text.split(_MARK)[-2] if text.count(_MARK) >= 2 else ""
    bits = "".join("0" if ch == _ZW["0"] else "1" for ch in inner if ch in _ZW.values())
    if len(bits) != 64:
        return None
    return f"{int(bits, 2):016x}"


def watermark(comp: Mapping, t: str) -> dict:
    out = dict(comp)
    note = (out.get("note") or "").split(_MARK)[0]
    out["note"] = note + _encode(t)
    return out


def trace(text: str, customers: Iterable[str], secret: str) -> str | None:
    t = extract_tag(text)
    if t is None:
        return None
    return next((c for c in customers if hmac.compare_digest(tag(secret, c), t)), None)


def select(components: Iterable[Mapping]) -> tuple[list[dict], list[str]]:
    keep, skipped = [], []
    for c in components:
        if c.get("license") in ALLOWED:
            keep.append(dict(c))
        else:
            skipped.append(c["id"])
    return keep, skipped


def build(components: Iterable[Mapping], customer: str, version: str, key_id: str, private_key_b64: str,
          secret: str, out: Path, today: dt.date | None = None) -> dict:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    keep, skipped = select(components)
    if not keep:
        raise PackError("没有可以进收费包的记录（只收厂商授权 partner 或自有 standard 数据）")
    t = tag(secret, customer)
    files: dict[str, bytes] = {}
    for c in keep:
        files[f"components/{c['category']}/{c['id']}.json"] = json.dumps(
            watermark(c, t), ensure_ascii=False, indent=2).encode("utf-8")
    pack = {"customer": customer, "issued": (today or dt.datetime.now().astimezone().date()).isoformat(),
            "version": version, "key_id": key_id, "count": len(keep),
            "files": {p: hashlib.sha256(b).hexdigest() for p, b in sorted(files.items())}}
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
    manifest = {"pack": pack, "signature": base64.b64encode(key.sign(canonical(pack))).decode()}
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for p, b in sorted(files.items()):
            z.writestr(p, b)
    return {"count": len(keep), "skipped": skipped, "customer": customer}


def verify_pack(path: Path, public_keys: Mapping[str, str]) -> dict:
    """校验签名与每个文件；返回 pack 信息。不合格抛 PackError。"""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackError(f"不是零件库订阅包：{exc}") from exc
    with z:
        try:
            manifest = json.loads(z.read("manifest.json"))
            pack, sig = manifest["pack"], manifest["signature"]
        except (KeyError, ValueError) as exc:
            raise PackError("订阅包缺少 manifest.json 或格式不对") from exc
        pub = public_keys.get(pack.get("key_id", ""))
        if not pub:
            raise PackError(f"不认识签发它的公钥（{pack.get('key_id')}）")
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(base64.b64decode(sig), canonical(pack))
        except (InvalidSignature, ValueError) as exc:
            raise PackError("订阅包签名不对：被改动过，或不是我们签发的") from exc
        names = {n for n in z.namelist() if n != "manifest.json" and not n.endswith("/")}
        if names != set(pack["files"]):
            raise PackError("订阅包里的文件与清单不符（有增删）")
        for n in names:
            if hashlib.sha256(z.read(n)).hexdigest() != pack["files"][n]:
                raise PackError(f"订阅包里的 {n} 被改动过")
    return pack


def open_pack(path: Path, public_keys: Mapping[str, str], cache: Path) -> tuple[Path, dict]:
    """校验后解到 cache/<sha>/，返回组件目录与 pack 信息。"""
    pack = verify_pack(path, public_keys)
    digest = hashlib.sha256(canonical(pack)).hexdigest()[:16]
    target = cache / digest
    if not (target / "components").is_dir():
        if target.exists():
            shutil.rmtree(target)
        with zipfile.ZipFile(path) as z:
            for n in pack["files"]:
                dest = target / n
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(n))
    return target / "components", pack


def _load_components(src: Path) -> list[dict]:
    out = []
    for p in sorted(src.rglob("*.json")):
        c = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(c, dict) and "id" in c and "category" in c:
            out.append(c)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="零件库订阅包：生成、校验、追查水印")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--src", type=Path, required=True)
    b.add_argument("--customer", required=True)
    b.add_argument("--version", required=True)
    b.add_argument("--key-id", required=True)
    b.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("check")
    c.add_argument("pack", type=Path)
    t = sub.add_parser("trace")
    t.add_argument("file", type=Path)
    t.add_argument("--customers", required=True, help="逗号分隔的客户名单")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        from licensing import keys

        try:
            p = verify_pack(a.pack, keys.PUBLIC_KEYS)
        except PackError as exc:
            print(exc)
            return 1
        print(f"订阅包有效：{p['customer']}，版本 {p['version']}，{p['count']} 条")
        return 0
    secret = os.environ.get("FAP_PACK_SECRET")
    if not secret:
        print("没有设置环境变量 FAP_PACK_SECRET（水印密钥）", file=sys.stderr)
        return 2
    if a.cmd == "trace":
        text = a.file.read_text(encoding="utf-8")
        notes = [text]
        try:
            notes = [json.load(io.StringIO(text)).get("note", "")]
        except (ValueError, AttributeError):
            pass
        who = trace(notes[0], [x.strip() for x in a.customers.split(",") if x.strip()], secret)
        print(f"来源：{who}" if who else "没有找到水印，或不是名单里的客户")
        return 0 if who else 1
    priv = os.environ.get("FAP_LICENSE_PRIVATE_KEY")
    if not priv:
        print("没有设置环境变量 FAP_LICENSE_PRIVATE_KEY（签发私钥）", file=sys.stderr)
        return 2
    try:
        r = build(_load_components(a.src), a.customer, a.version, a.key_id, priv, secret, a.out)
    except PackError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"已生成 {a.out}：{r['customer']}，{r['count']} 条；未收（不是厂商授权或自有数据）{len(r['skipped'])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
