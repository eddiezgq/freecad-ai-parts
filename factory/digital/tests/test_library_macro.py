# -*- coding: utf-8 -*-
"""零件库第 5 轮 P10①：FreeCAD 插入宏的非界面部分——搜索、规格、下载压缩包取 STEP、缓存、没有 STEP 的条目给提示。"""
import http.server
import io
import json
import os
import sys
import threading
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "freecad"))
import wq_library as W  # noqa: E402

VER = "2026.10.9"


@pytest.fixture()
def server(tmp_path):
    root = tmp_path / "site"
    (root / "library" / VER / "A-BRG-DG").mkdir(parents=True)
    (root / "library" / VER / "B-SCA-WQ4").mkdir(parents=True)
    (root / "pkg").mkdir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("6207.step", "ISO-10303-21; 6207")
        z.writestr("6206.step", "ISO-10303-21; 6206")
    (root / "pkg" / "A-BRG-DG.zip").write_bytes(buf.getvalue())
    hits = []

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        def log_message(self, *a):
            hits.append(self.path)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    base = "http://127.0.0.1:{}".format(srv.server_address[1])
    items = [{"ref": "A-BRG-DG/" + s, "id": "A-BRG-DG", "size": s, "part": "A", "kind": "family", "family": {"zh": "深沟球轴承"},
              "name": {"zh": "深沟球轴承 " + s}, "standards": ["GB/T 276-2013"], "erp_items": ["BRG-" + s]} for s in ("6206", "6207")]
    items.append({"ref": "B-SCA-WQ4", "id": "B-SCA-WQ4", "part": "B", "kind": "robot", "name": {"zh": "SCARA 机器人"}, "standards": []})
    (root / "library" / "latest.json").write_text(json.dumps({"version": VER, "index": "library/{}/index.json".format(VER)}))
    (root / "library" / VER / "index.json").write_text(json.dumps({"version": VER, "items": items}))
    (root / "library" / VER / "A-BRG-DG" / "entry.json").write_text(json.dumps({
        "id": "A-BRG-DG", "name": {"zh": "深沟球轴承"}, "default": "6207", "model": {"formats": ["step", "stl", "glb"]},
        "package": base + "/pkg/A-BRG-DG.zip",
        "sizes": [{"size": s, "files": {"glb": "A-BRG-DG/{}.glb".format(s)}} for s in ("6206", "6207")]}))
    (root / "library" / VER / "B-SCA-WQ4" / "entry.json").write_text(json.dumps({
        "id": "B-SCA-WQ4", "name": {"zh": "SCARA"}, "model": {"formats": ["glb", "urdf"]}, "package": "https://github.com/x",
        "sizes": [{"size": "default", "files": {"glb": "B-SCA-WQ4/default.glb"}}]}))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield base, hits
    srv.shutdown()


def test_search_and_fetch_step(server, tmp_path):
    base, hits = server
    lib = W.Library(base, cache=str(tmp_path / "cache"))
    assert lib.version == VER
    r = lib.search("6207")
    assert r[0][0]["id"] == "A-BRG-DG" and r[0][1] == "6207"
    assert lib.search("GB/T 276")[0][0]["id"] == "A-BRG-DG"
    assert lib.search("BRG-6206")[0][0]["id"] == "A-BRG-DG"                     # 工厂物料号也能搜
    p = lib.step("A-BRG-DG/6207")
    assert open(p).read().endswith("6207") and os.path.dirname(os.path.dirname(p)).endswith(VER)
    n = len([h for h in hits if h.endswith(".zip")])
    assert open(lib.step("A-BRG-DG/6206")).read().endswith("6206")              # 改规格：同一压缩包，不再下载
    assert len([h for h in hits if h.endswith(".zip")]) == n == 1
    assert lib.step("A-BRG-DG").endswith("6207.step")                            # 不写规格用默认规格
    with pytest.raises(KeyError):
        lib.step("A-BRG-DG/6208")
    assert not lib.has_step("B-SCA-WQ4")
    with pytest.raises(ValueError):
        lib.step("B-SCA-WQ4")


def test_cli(server, tmp_path, capsys, monkeypatch):
    base, _ = server
    monkeypatch.setitem(W.CONFIG, "library", base)
    monkeypatch.setitem(W.CONFIG, "cache", str(tmp_path / "c2"))
    assert W.main(["search", "6207"]) == 0
    assert "A-BRG-DG/6207" in capsys.readouterr().out
    assert W.main(["fetch", "A-BRG-DG/6207"]) == 0
    assert capsys.readouterr().out.strip().endswith("6207.step")
