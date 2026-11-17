"""问渠有限元版的免费 / 专业两档与测试密钥（ADR-0096 第 5 步）。不需要 FreeCAD。"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from assist import fea_edition as E
from licensing import runtime
from licensing.issue import keygen
from licensing.license import sign

FREE = {"format": "fea-study/1", "name": "x", "bodies": [{"id": "b1", "step_path": "p.step", "material": "45-QT"}],
        "supports": [{"type": "fixed", "body": "b1", "faces": [3]}],
        "loads": [{"type": "torque", "body": "b1", "faces": [8], "value_nm": 92.5}],
        "steps": [{"id": "s1", "type": "static"}, {"id": "s2", "type": "modal", "n_modes": 4}, {"id": "s3", "type": "buckling"}]}


def _with(**kw):
    s = json.loads(json.dumps(FREE))
    for k, v in kw.items():
        s[k] = v
    return s


@pytest.mark.parametrize("study,need", [
    (_with(bodies=FREE["bodies"] * 2), "多个实体"),
    (_with(bodies=[{**FREE["bodies"][0], "kind": "shell", "thickness_mm": 2}]), "壳"),
    (_with(bodies=[{**FREE["bodies"][0], "kind": "beam"}]), "梁"),
    (_with(bodies=[{**FREE["bodies"][0], "plasticity": {"model": "perfectly_plastic"}}]), "弹塑性"),
    (_with(connections=[{"type": "tie"}]), "绑定、接触或螺栓"),
    (_with(steps=[{"id": "s1", "type": "static", "large_deformation": True}]), "大变形"),
    (_with(steps=[{"id": "s1", "type": "harmonic"}]), "谐响应"),
    (_with(steps=[{"id": "s1", "type": "random"}]), "随机振动"),
    (_with(steps=[{"id": "s1", "type": "transient"}]), "瞬态"),
    (_with(loads=[*FREE["loads"], {"type": "mass", "body": "b1"}]), "附加质量"),
    (_with(load_cases=[{"id": "G"}]), "工况组合"),
    (_with(mesh={"max_elements": 500000}), "超过 20 万单元的大模型"),
])
def test_pro_needs(study, need):
    assert need in E.pro_needs(study)


def test_free_study_needs_nothing():
    assert E.pro_needs(FREE) == []
    assert E.pro_needs(_with(mesh={"max_elements": 200000})) == []


@pytest.fixture
def fea(monkeypatch, tmp_path):
    """问渠有限元版、本机没有授权文件"""
    monkeypatch.setenv("FAP_EDITION", "fea")
    monkeypatch.setenv("FAP_LICENSE_FILE", str(tmp_path / "none.json"))
    monkeypatch.delenv("FAP_LICENSE_TEST_KEY", raising=False)
    monkeypatch.setattr(E, "EDITION_FILE", tmp_path / "no-edition.json")
    monkeypatch.setattr(runtime, "EDITION_FILE", tmp_path / "no-edition.json")
    return tmp_path


def test_full_edition_is_not_gated(monkeypatch, tmp_path):
    monkeypatch.delenv("FAP_EDITION", raising=False)
    monkeypatch.setattr(E, "EDITION_FILE", tmp_path / "none.json")
    assert E.edition() == "full" and E.pro_allowed()
    E.gate(_with(steps=[{"id": "s1", "type": "harmonic"}]), feature="正式报告")


def test_free_tier_refuses_pro_features(fea):
    E.gate(FREE)                                                  # 免费版能算的不拦
    with pytest.raises(E.NeedsPro, match="多个实体"):
        E.gate(_with(bodies=FREE["bodies"] * 2))
    with pytest.raises(E.NeedsPro, match="正式报告"):
        E.gate(feature="正式报告")


def _license(tmp_path, features, kid="test-ci"):
    priv, pub = keygen()
    today = dt.datetime.now().astimezone().date()
    doc = sign({"id": "L1", "key_id": kid, "licensee": "CI 验收", "issued": today.isoformat(),
                "expires": (today + dt.timedelta(days=30)).isoformat(), "kind": "floating", "seats": 1,
                "features": features}, priv)
    path = tmp_path / "license.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path, f"{kid}:{pub}"


def _edition_file(path, test_build):
    path.write_text(json.dumps({"edition": "fea", "test_build": test_build}), encoding="utf-8")
    return path


def test_test_key_only_in_test_builds(fea, monkeypatch):
    lic, key = _license(fea, [E.PRO])
    monkeypatch.setenv("FAP_LICENSE_FILE", str(lic))
    monkeypatch.setenv("FAP_LICENSE_TEST_KEY", key)
    ed = fea / "edition.json"
    monkeypatch.setattr(E, "EDITION_FILE", ed)
    monkeypatch.setattr(runtime, "EDITION_FILE", ed)

    _edition_file(ed, False)                                       # 正式安装包：设了测试公钥也不认
    assert not runtime.current().valid and not E.pro_allowed()
    with pytest.raises(E.NeedsPro):
        E.gate(feature="正式报告")

    _edition_file(ed, True)                                        # 验收用的安装包：认
    assert E.info() == {"edition": "fea", "test_build": True}
    assert E.pro_allowed()
    E.gate(_with(bodies=FREE["bodies"] * 2), feature="正式报告")


def test_test_key_id_must_start_with_test(fea, monkeypatch):
    ed = _edition_file(fea / "edition.json", True)
    _, key = _license(fea, [E.PRO], kid="k2026")
    assert "k2026" not in runtime.known_keys({"FAP_LICENSE_TEST_KEY": key}, ed)     # 不能冒充正式公钥编号
    assert runtime.known_keys({"FAP_LICENSE_TEST_KEY": "test-x:abc"}, ed)["test-x"] == "abc"


def test_license_without_fea_pro_stays_free(fea, monkeypatch):
    ed = _edition_file(fea / "edition.json", True)
    monkeypatch.setattr(runtime, "EDITION_FILE", ed)
    lic, key = _license(fea, ["parts-subscription"])
    monkeypatch.setenv("FAP_LICENSE_FILE", str(lic))
    monkeypatch.setenv("FAP_LICENSE_TEST_KEY", key)
    assert runtime.current().valid and not E.pro_allowed()


def test_install_writes_edition(tmp_path):
    from freecad_addon import install as I
    from freecad_addon.bundle import MANIFEST

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / MANIFEST).write_text("{}", encoding="utf-8")
    t = I.install(tmp_path / "Mod", bundle=bundle, edition="fea", test_build=True)
    assert json.loads((t / "lib" / "edition.json").read_text(encoding="utf-8")) == {"edition": "fea", "test_build": True}
    t = I.install(tmp_path / "Mod", bundle=bundle)                                  # 全功能版不写，按 full
    assert not (t / "lib" / "edition.json").exists()
    with pytest.raises(ValueError):
        I.install(tmp_path / "Mod2", edition="fea")                                  # 只用于自包含安装
    with pytest.raises(ValueError):
        I.edition_doc("pro")


def test_bundle_has_assist():
    """FEM 按钮、报告、中英切换都在 assist 包里：安装包要带上（ADR-0096 第 5 步发现缺了）"""
    from freecad_addon.bundle import PACKAGES

    assert "assist" in PACKAGES
