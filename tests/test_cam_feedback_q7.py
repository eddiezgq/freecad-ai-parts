"""问渠CAM Q7a 问题反馈包（ADR-0106 Q7a）：内容齐（说明、环境、文档副本、用户配置、报告视图）；不收授权文件；没写说明不生成。"""

from __future__ import annotations

import json
import zipfile

import pytest

from freecad_addon.core import cam_feedback as FB


@pytest.fixture()
def home(tmp_path, monkeypatch):
    base = tmp_path / ".freecad-ai-parts"
    for sub in ("tools", "machines", "posts"):
        (base / sub).mkdir(parents=True)
        (base / sub / f"my-{sub}.json").write_text("{}", encoding="utf-8")
    (base / "license.json").write_text('{"signature": "SECRET"}', encoding="utf-8")
    (base / "posts" / "license-copy.json").write_text('{"signature": "SECRET"}', encoding="utf-8")
    monkeypatch.setenv("FAP_TOOLS", str(base / "tools"))
    monkeypatch.setenv("FAP_MACHINES_DIR", str(base / "machines"))
    monkeypatch.setenv("FAP_POSTS", str(base / "posts"))
    monkeypatch.setenv("FAP_LICENSE_FILE", str(base / "license.json"))
    return base


def test_package_contents(home, tmp_path):
    doc = tmp_path / "零件.FCStd"
    doc.write_bytes(b"PK fake")
    zp = FB.build(tmp_path / "out", "  车削第二次装夹报撞刀，但刀离卡爪很远  ", document=doc,
                  environment={"wenquest_cam": "abc123", "freecad": "1.0.2", "edition": "cam"},
                  log="Traceback ...\nAPI_KEY=sk-123456\nValueError: x")
    names = FB.contents(zp)
    assert {"description.txt", "environment.json", "document/零件.FCStd", "report-view.txt", "config/tools/my-tools.json",
            "config/machines/my-machines.json", "config/posts/my-posts.json"} <= set(names)
    assert not any("license" in n.lower() for n in names)
    with zipfile.ZipFile(zp) as z:
        assert "撞刀" in z.read("description.txt").decode("utf-8")
        envj = json.loads(z.read("environment.json"))
        assert envj["wenquest_cam"] == "abc123" and envj["freecad"] == "1.0.2" and "os" in envj
        log = z.read("report-view.txt").decode("utf-8")
        assert "sk-123456" not in log and "ValueError" in log
        assert all(b"SECRET" not in z.read(n) for n in z.namelist())


def test_empty_description_and_missing_document(home, tmp_path):
    with pytest.raises(FB.FeedbackError):
        FB.build(tmp_path, "   ")
    with pytest.raises(FB.FeedbackError):
        FB.build(tmp_path, "x", document=tmp_path / "nope.FCStd")
    zp = FB.build(tmp_path, "只写了说明")
    assert "document/" not in "".join(FB.contents(zp))
