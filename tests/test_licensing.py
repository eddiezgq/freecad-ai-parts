"""授权文件（ADR-0066 第 5 项）：签名、篡改、过期、功能、单机指纹。"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from licensing import fingerprint as fp
from licensing import issue, keys, runtime
from licensing.license import LicenseError, sign, verify

TODAY = dt.date(2026, 10, 9)


@pytest.fixture(scope="module")
def keypair():
    return issue.keygen()


def _lic(**kw):
    lic = {"id": "L-1", "key_id": "test", "licensee": "示例机械", "issued": "2026-10-01", "expires": "2027-09-30",
           "kind": "floating", "seats": 5, "features": ["parts-subscription", "seats"]}
    lic.update(kw)
    return lic


def test_valid_and_features(keypair):
    priv, pub = keypair
    v = verify(sign(_lic(), priv), {"test": pub}, TODAY)
    assert v.valid and v.seats == 5 and v.allows("parts-subscription") and not v.allows("advanced-mrp")
    assert "示例机械" in v.reason


@pytest.mark.parametrize(("change", "words"), [
    (lambda d: d["license"].__setitem__("seats", 50), "签名不对"),
    (lambda d: d["license"].__setitem__("expires", "2099-01-01"), "签名不对"),
    (lambda d: d["license"]["features"].append("everything"), "签名不对"),
    (lambda d: d.__setitem__("signature", d["signature"][:-4] + "AAA="), "签名不对"),
    (lambda d: d["license"].__setitem__("key_id", "other"), "不认识"),
    (lambda d: d.pop("signature"), "格式不对"),
])
def test_tampering_rejected(keypair, change, words):
    priv, pub = keypair
    doc = json.loads(json.dumps(sign(_lic(), priv)))
    change(doc)
    v = verify(doc, {"test": pub}, TODAY)
    assert not v.valid and words in v.reason and not v.allows("seats")


def test_other_key_rejected(keypair):
    _, pub = keypair
    other_priv, _ = issue.keygen()
    assert not verify(sign(_lic(), other_priv), {"test": pub}, TODAY).valid


def test_expiry_and_clock(keypair):
    priv, pub = keypair
    doc = sign(_lic(expires="2026-10-08"), priv)
    v = verify(doc, {"test": pub}, TODAY)
    assert not v.valid and "到期" in v.reason and "公开功能照常" in v.reason
    assert verify(doc, {"test": pub}, dt.date(2026, 10, 8)).valid          # 到期当天还能用
    assert "晚于今天" in verify(sign(_lic(issued="2026-12-01"), priv), {"test": pub}, TODAY).reason


def test_node_lock(keypair):
    priv, pub = keypair
    doc = sign(_lic(kind="node", seats=1, node="AAAA-BBBB"), priv)
    assert verify(doc, {"test": pub}, TODAY, node="AAAA-BBBB").valid
    v = verify(doc, {"test": pub}, TODAY, node="CCCC-DDDD")
    assert not v.valid and "指纹不符" in v.reason
    with pytest.raises(LicenseError, match="指纹"):
        sign(_lic(kind="node"), priv)


@pytest.mark.parametrize("bad", [{"seats": 0}, {"kind": "site"}, {"features": "all"}, {"expires": "明年"}])
def test_bad_fields_not_signed(keypair, bad):
    with pytest.raises((LicenseError, ValueError)):
        sign(_lic(**bad), keypair[0])


def test_fingerprint_stable():
    parts = ["machine:abc", "mac:001122334455"]
    assert fp.fingerprint(parts) == fp.fingerprint(list(reversed(parts)))
    assert fp.fingerprint(parts) != fp.fingerprint(["machine:abc"])
    assert len(fp.fingerprint()) == 29
    with pytest.raises(RuntimeError):
        fp.fingerprint([])


def test_runtime_and_cli(keypair, tmp_path, monkeypatch, capsys):
    priv, pub = keypair
    assert keys.PUBLIC_KEYS == {}                       # 正式公钥由项目负责人加
    assert not runtime.current(tmp_path / "none.json").valid
    monkeypatch.setenv("FAP_LICENSE_PRIVATE_KEY", priv)
    out = tmp_path / "a.license.json"
    assert issue.main(["sign", "--key-id", "test", "--licensee", "示例机械", "--expires", "2099-12-31",
                       "--kind", "floating", "--seats", "3", "--features", "parts-subscription", "--out", str(out)]) == 0
    v = runtime.current(out, public_keys={"test": pub})
    assert v.valid and v.allows("parts-subscription")
    assert not runtime.current(out).valid               # keys.py 里没有这把测试公钥
    monkeypatch.setattr(keys, "PUBLIC_KEYS", {"test": pub})
    monkeypatch.setenv("FAP_LICENSE_FILE", str(out))
    assert runtime.allows("parts-subscription") and not runtime.allows("x")
    assert issue.main(["check", str(out)]) == 0
    me = fp.fingerprint()
    node_file = tmp_path / "n.license.json"
    issue.main(["sign", "--key-id", "test", "--licensee", "小厂", "--expires", "2099-12-31", "--kind", "node",
                "--features", "parts-subscription", "--node", me, "--out", str(node_file)])
    assert runtime.current(node_file).valid             # 本机指纹相符
    monkeypatch.delenv("FAP_LICENSE_PRIVATE_KEY")
    assert issue.main(["sign", "--key-id", "test", "--licensee", "x", "--expires", "2099-12-31", "--kind", "floating",
                       "--features", "a", "--out", str(tmp_path / "x.json")]) == 2
    capsys.readouterr()
