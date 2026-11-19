"""问渠CAM 的免费 / 专业两档（ADR-0104 决策 5）。不需要 FreeCAD。"""

from __future__ import annotations

import json

import pytest

from analysis.cam import machines
from assist import cam_edition as E
from assist import fea_edition, mbd_edition
from licensing import runtime
from tests.test_fea_edition import _license


@pytest.fixture
def cam(monkeypatch, tmp_path):
    """问渠CAM 版、本机没有授权文件"""
    monkeypatch.setenv("FAP_EDITION", "cam")
    monkeypatch.setenv("FAP_LICENSE_FILE", str(tmp_path / "none.json"))
    monkeypatch.delenv("FAP_LICENSE_TEST_KEY", raising=False)
    monkeypatch.setattr(fea_edition, "EDITION_FILE", tmp_path / "no-edition.json")
    monkeypatch.setattr(runtime, "EDITION_FILE", tmp_path / "no-edition.json")
    return tmp_path


def test_pro_needs():
    assert E.pro_needs({"mode": "turn", "post": "fanuc"}) == []
    assert E.pro_needs({"mode": "mill", "post": "siemens"}) == ["FANUC 以外的后处理"]
    assert E.pro_needs({"mode": "mill"}, machines.model("EX-5AX-AC")) == ["五轴 / 车铣复合机床"]
    assert E.pro_needs({"mode": "mill"}, machines.model("EX-VMC")) == []


def test_full_edition_is_not_gated(monkeypatch, tmp_path):
    monkeypatch.delenv("FAP_EDITION", raising=False)
    monkeypatch.setattr(fea_edition, "EDITION_FILE", tmp_path / "none.json")
    assert E.edition() == "full" and E.pro_allowed()
    E.gate({"post": "gsk"}, feature="ai")


def test_free_tier_refuses_pro_features(cam):
    assert E.edition() == "cam" and not E.pro_allowed()
    assert fea_edition.pro_allowed() and mbd_edition.pro_allowed()     # 另外两个产品的档位与本版无关
    E.gate({"mode": "turn", "post": "fanuc"}, machine_model=machines.model("EX-LATHE"))
    with pytest.raises(E.NeedsPro, match="FANUC 以外的后处理") as e:
        E.gate({"post": "siemens"})
    assert "授权" in str(e.value)
    with pytest.raises(E.NeedsPro, match="五轴"):
        E.gate({}, machine_model=machines.model("EX-MT-CY"))
    for f, word in (("ai", "AI 起草工艺"), ("card", "工艺卡")):
        with pytest.raises(E.NeedsPro, match=word):
            E.gate(feature=f)


def test_license_opens_pro_only_with_cam_pro(cam, monkeypatch):
    ed = cam / "edition.json"
    ed.write_text(json.dumps({"edition": "cam", "test_build": True}), encoding="utf-8")
    monkeypatch.delenv("FAP_EDITION")
    monkeypatch.setattr(fea_edition, "EDITION_FILE", ed)
    monkeypatch.setattr(runtime, "EDITION_FILE", ed)
    lic, key = _license(cam, [fea_edition.PRO, mbd_edition.PRO])     # 有限元、多体的专业版：本版仍是免费版
    monkeypatch.setenv("FAP_LICENSE_FILE", str(lic))
    monkeypatch.setenv("FAP_LICENSE_TEST_KEY", key)
    assert runtime.current().valid and not E.pro_allowed()
    lic, key = _license(cam, [fea_edition.PRO, mbd_edition.PRO, E.PRO])   # 三件套
    monkeypatch.setenv("FAP_LICENSE_FILE", str(lic))
    monkeypatch.setenv("FAP_LICENSE_TEST_KEY", key)
    assert E.pro_allowed()
    E.gate({"post": "gsk"}, feature="card", machine_model=machines.model("EX-5AX-AC"))
    ed.write_text(json.dumps({"edition": "cam", "test_build": False}), encoding="utf-8")   # 正式安装包不认测试公钥
    assert not E.pro_allowed()
