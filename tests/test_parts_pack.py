"""零件库订阅包（ADR-0066 第 7 项）：只收厂商授权与自有数据、签名、篡改拒载、水印可追、按授权加载。"""

from __future__ import annotations

import json
import zipfile

import pytest

from engine.golden import load_fixtures
from freecad_addon.core import library_choice
from licensing import issue
from licensing import parts_pack as pp

SECRET = "test-watermark-secret"


@pytest.fixture(scope="module")
def keypair():
    return issue.keygen()


def _components():
    comps = list(load_fixtures().values())[:4]
    out = []
    for i, c in enumerate(comps):
        c = json.loads(json.dumps(c))
        c["license"] = ["partner", "standard", "params-only", "open"][i]
        out.append(c)
    return out


@pytest.fixture
def pack(tmp_path, keypair):
    out = tmp_path / "pack.zip"
    r = pp.build(_components(), "示例机械", "2026.10", "t", keypair[0], SECRET, out)
    return out, r


def test_build_selects_and_signs(pack, keypair):
    out, r = pack
    assert r["count"] == 2 and len(r["skipped"]) == 2           # params-only、open 不进收费包
    info = pp.verify_pack(out, {"t": keypair[1]})
    assert info["customer"] == "示例机械" and info["count"] == 2
    with pytest.raises(pp.PackError, match="没有可以"):
        pp.build([c for c in _components() if c["license"] == "params-only"], "x", "v", "t", keypair[0], SECRET,
                 out.parent / "none.zip")


def _rewrite(src, dst, change):
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for n in zin.namelist():
            data = change(n, zin.read(n))
            if data is not None:
                zout.writestr(n, data)


@pytest.mark.parametrize(("change", "words"), [
    (lambda n, b: b.replace(b'"category"', b'"category" ', 1) if n.startswith("components/") else b, "被改动"),
    (lambda n, b: None if n.startswith("components/") else b, "增删"),
    (lambda n, b: b.replace("示例机械".encode(), "别家".encode()) if n == "manifest.json" else b, "签名不对"),
])
def test_tampering_rejected(pack, keypair, tmp_path, change, words):
    out, _ = pack
    bad = tmp_path / "bad.zip"
    _rewrite(out, bad, change)
    with pytest.raises(pp.PackError, match=words):
        pp.verify_pack(bad, {"t": keypair[1]})
    with pytest.raises(pp.PackError, match="不认识"):
        pp.verify_pack(out, {"other": keypair[1]})
    with pytest.raises(pp.PackError, match="不是零件库"):
        pp.verify_pack(tmp_path / "pack-missing.zip", {"t": keypair[1]})


def test_watermark_invisible_and_traceable(pack, keypair, tmp_path):
    out, _ = pack
    comps, _ = pp.open_pack(out, {"t": keypair[1]}, tmp_path / "cache")
    rec = json.loads(next(comps.rglob("*.json")).read_text(encoding="utf-8"))
    visible = "".join(ch for ch in rec["note"] if ch not in ("\u200b", "\u200c", "\u2060"))
    original = next(c for c in _components() if c["id"] == rec["id"])
    assert visible == (original.get("note") or "")                 # 看得见的文字没变
    assert pp.trace(rec["note"], ["另一家", "示例机械"], SECRET) == "示例机械"
    assert pp.trace(rec["note"], ["另一家"], SECRET) is None
    assert pp.trace(rec["note"], ["示例机械"], "wrong-secret") is None
    assert pp.trace("没有水印", ["示例机械"], SECRET) is None
    again = json.loads(json.dumps(rec, ensure_ascii=False))       # 另存一遍水印还在
    assert pp.trace(again["note"], ["示例机械"], SECRET) == "示例机械"
    assert pp.extract_tag(pp.watermark(rec, pp.tag(SECRET, "别家"))["note"]) == pp.tag(SECRET, "别家")  # 重打不叠加


def test_library_choice_gates_on_license(pack, keypair, tmp_path):
    out, _ = pack
    env = {"FAP_PARTS_PACK": str(out)}
    ch = library_choice.choose(env, settings={}, pack_allowed=False, public_keys={"t": keypair[1]})
    assert ch.pack is None and "需要授权" in ch.note
    ch = library_choice.choose(env, settings={}, pack_allowed=True, public_keys={"t": keypair[1]})
    assert ch.pack == out and "订阅零件库 2 个组件" in ch.note
    lib = library_choice.load(ch, public_keys={"t": keypair[1]}, cache=tmp_path / "cache")
    pid = next(c["id"] for c in _components() if c["license"] == "partner")
    assert pp.extract_tag(lib.get(pid)["note"]) == pp.tag(SECRET, "示例机械")    # 订阅包在公共库之上
    ch = library_choice.choose(env, settings={}, pack_allowed=True, public_keys={})
    assert ch.pack is None and "不能用" in ch.note


def test_cli(tmp_path, keypair, monkeypatch, capsys):
    src = tmp_path / "src"
    for c in _components():
        p = src / c["category"] / f"{c['id']}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "p.zip"
    monkeypatch.delenv("FAP_PACK_SECRET", raising=False)
    assert pp.main(["build", "--src", str(src), "--customer", "示例机械", "--version", "v1", "--key-id", "t",
                    "--out", str(out)]) == 2
    monkeypatch.setenv("FAP_PACK_SECRET", SECRET)
    monkeypatch.setenv("FAP_LICENSE_PRIVATE_KEY", keypair[0])
    assert pp.main(["build", "--src", str(src), "--customer", "示例机械", "--version", "v1", "--key-id", "t",
                    "--out", str(out)]) == 0
    assert pp.main(["check", str(out)]) == 1                      # keys.py 里没有测试公钥
    leaked = tmp_path / "leak.json"
    with zipfile.ZipFile(out) as z:
        leaked.write_bytes(z.read(next(n for n in z.namelist() if n.startswith("components/"))))
    assert pp.main(["trace", str(leaked), "--customers", "另一家,示例机械"]) == 0
    assert "示例机械" in capsys.readouterr().out
