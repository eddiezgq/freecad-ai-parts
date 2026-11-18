"""问渠多体动力学版的免费 / 专业两档（ADR-0102 第 4 步）。不需要 FreeCAD。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist import fea_edition
from assist import mbd_edition as E
from licensing import runtime
from tests.test_fea_edition import _license

FIX = Path(__file__).parent / "fixtures" / "mbd-model" / "valid"


def _model(name):
    d = json.loads((FIX / name).read_text(encoding="utf-8"))
    return d.get("instance", d)


@pytest.mark.parametrize("name,needs", [
    ("pendulum.json", []),
    ("slider_crank_all_d1.json", []),
    ("universal_static_then_dynamic.json", []),
    ("d2_force_elements.json", ["梁元件"]),
    ("d3_contacts.json", ["接触"]),
    ("d4_linear_plant.json", ["线性化与模态"]),
    ("d6_flex_pendulum.json", ["柔性体"]),
    ("d7_pid_turntable.json", ["控制器"]),
])
def test_pro_needs_of_fixtures(name, needs):
    got = E.pro_needs(_model(name))
    assert set(needs) <= set(got) and (needs or got == []), got


def test_pro_needs_details():
    m = _model("slider_crank_all_d1.json")
    m["bodies"] = m["bodies"] * 6                                   # 18 个构件
    m["joints"][0]["friction"] = {"mu_static": 0.1}
    m["joints"][1]["clearance"] = {"radial_mm": 0.05}
    m["forces"].append({"type": "gear_mesh"})
    m["analysis"]["integrator"] = "HHT"
    got = E.pro_needs(m)
    assert {"超过 15 个构件", "摩擦", "间隙", "齿轮啮合", "HHT 隐式积分"} <= set(got)
    m = _model("slider_crank_all_d1.json")
    assert E.pro_needs(m, flex_parts={"Lever": {"material": "45-QT"}}) == ["柔性体"]
    m["bodies"] = (m["bodies"] * 5)[:15]
    assert E.pro_needs(m) == []                                     # 15 个刚性构件还是免费版


@pytest.fixture
def mbd(monkeypatch, tmp_path):
    """问渠多体动力学版、本机没有授权文件"""
    monkeypatch.setenv("FAP_EDITION", "mbd")
    monkeypatch.setenv("FAP_LICENSE_FILE", str(tmp_path / "none.json"))
    monkeypatch.delenv("FAP_LICENSE_TEST_KEY", raising=False)
    monkeypatch.setattr(fea_edition, "EDITION_FILE", tmp_path / "no-edition.json")
    monkeypatch.setattr(runtime, "EDITION_FILE", tmp_path / "no-edition.json")
    return tmp_path


def test_full_edition_is_not_gated(monkeypatch, tmp_path):
    monkeypatch.delenv("FAP_EDITION", raising=False)
    monkeypatch.setattr(fea_edition, "EDITION_FILE", tmp_path / "none.json")
    assert E.edition() == "full" and E.pro_allowed()
    E.gate(_model("d6_flex_pendulum.json"), feature="正式报告")


def test_free_tier_refuses_pro_features(mbd):
    assert E.edition() == "mbd" and not E.pro_allowed()
    assert fea_edition.pro_allowed()                                 # 有限元的档位与本版无关
    E.gate(_model("slider_crank_all_d1.json"))                       # 免费版能算的不拦
    with pytest.raises(E.NeedsPro, match="柔性体") as e:
        E.gate(_model("d6_flex_pendulum.json"))
    assert "授权" in str(e.value)
    with pytest.raises(E.NeedsPro, match="正式报告"):
        E.gate(feature="正式报告")
    with pytest.raises(E.NeedsPro, match="AI 帮着挑运动副"):
        E.gate(feature="AI 帮着挑运动副")


def _edition_file(path, test_build):
    path.write_text(json.dumps({"edition": "mbd", "test_build": test_build}), encoding="utf-8")
    return path


def test_license_opens_pro_only_with_mbd_pro(mbd, monkeypatch):
    ed = _edition_file(mbd / "edition.json", True)
    monkeypatch.delenv("FAP_EDITION")
    monkeypatch.setattr(fea_edition, "EDITION_FILE", ed)
    monkeypatch.setattr(runtime, "EDITION_FILE", ed)
    lic, key = _license(mbd, [fea_edition.PRO])                     # 只有问渠有限元专业版：本版仍是免费版
    monkeypatch.setenv("FAP_LICENSE_FILE", str(lic))
    monkeypatch.setenv("FAP_LICENSE_TEST_KEY", key)
    assert fea_edition.info() == {"edition": "mbd", "test_build": True}
    assert runtime.current().valid and not E.pro_allowed()
    lic, key = _license(mbd, [fea_edition.PRO, E.PRO])              # 套装：一个授权文件两个都开
    monkeypatch.setenv("FAP_LICENSE_FILE", str(lic))
    monkeypatch.setenv("FAP_LICENSE_TEST_KEY", key)
    assert E.pro_allowed()
    E.gate(_model("d6_flex_pendulum.json"), feature="正式报告")
    _edition_file(ed, False)                                        # 正式安装包：测试公钥不认
    assert not E.pro_allowed()


def test_install_and_deps_for_mbd(tmp_path):
    from freecad_addon import install as I
    from freecad_addon.bundle import MANIFEST
    from installer.windows.deps import requirements

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / MANIFEST).write_text("{}", encoding="utf-8")
    t = I.install(tmp_path / "Mod", bundle=bundle, edition="mbd", test_build=True)
    assert json.loads((t / "lib" / "edition.json").read_text(encoding="utf-8")) == {"edition": "mbd", "test_build": True}
    with pytest.raises(ValueError):
        I.install(tmp_path / "Mod2", edition="mbd")                   # 只用于自包含安装
    root = Path(__file__).resolve().parents[1]
    reqs = requirements(root / "pyproject.toml", "mbd")
    names = {r.split("=")[0].split(">")[0] for r in reqs}
    assert {"gmsh", "scipy", "python-docx", "matplotlib", "fmpy", "anthropic"} <= names and "mujoco" not in names
