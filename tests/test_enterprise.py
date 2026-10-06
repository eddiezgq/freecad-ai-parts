"""企业私有库（ADR-0055）：叠加取数、写入校验、依据必填、资料登记与历史记录。只用临时目录。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from freecad_addon.core.library_choice import choose, load, read_settings, write_setting
from kb.enterprise import EnterpriseError, EnterpriseLibrary
from kb.library import JsonLibrary, LayeredLibrary

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = JsonLibrary(ROOT / "data" / "library")
M = "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"
R = "reducer.harmonic-drive-llc.csf-25-100-2uh"


@pytest.fixture
def ent(tmp_path):
    return EnterpriseLibrary(tmp_path / "ent", create=True)


@pytest.fixture
def spec_pdf(tmp_path):
    p = tmp_path / "supplier-spec.pdf"
    p.write_bytes(b"%PDF-1.4 fake spec")
    return p


def test_empty_enterprise_library_changes_nothing(ent):
    lib = LayeredLibrary(ent, PUBLIC)
    assert lib.all() == PUBLIC.all() and lib.get(M) == PUBLIC.get(M)
    assert lib.origin(M) == "public" and lib.origin("nope") is None


def test_register_document_copies_hashes_and_dedups(ent, spec_pdf):
    d = ent.register_document(spec_pdf, "供应商规格书 A", "张工")
    assert d["id"].startswith("src-ent-") and (ent.directory / "docs" / d["file"]).is_file()
    assert len(d["sha256"]) == 64
    assert ent.register_document(spec_pdf, "再登记一次", "张工") == d  # 同一文件不重复
    assert [h["action"] for h in ent.history()] == ["register_document"]
    with pytest.raises(EnterpriseError, match="标题与登记人"):
        ent.register_document(spec_pdf, " ", "张工")


def test_set_value_copies_public_component_and_overrides_it(ent, spec_pdf):
    doc = ent.register_document(spec_pdf, "规格书", "张工")["id"]
    pv = {"value": 2, "method": "manual", "confidence": 1, "reviewed": True,
          "source": {"doc": doc, "page": 3, "note": "原文“Pilot dia. 2 mm”；录入人：张工"}}
    comp = ent.set_value(R, "params/backlash_arcmin", pv, "张工", PUBLIC.get)
    lib = LayeredLibrary(ent, PUBLIC)
    assert lib.origin(R) == "enterprise" and lib.get(R)["params"]["backlash_arcmin"] == pv
    assert PUBLIC.get(R)["params"].get("backlash_arcmin") != pv  # 公共库不变
    assert len(lib.all("reducer")) == len(PUBLIC.all("reducer"))  # 同 id 以企业为准，不重复
    assert comp == lib.get(R)
    # 重新打开仍在
    again = EnterpriseLibrary(ent.directory)
    assert again.get(R)["params"]["backlash_arcmin"] == pv
    actions = [h["action"] for h in again.history()]
    assert actions == ["register_document", "save_component", "set_value"]


@pytest.mark.parametrize(("source", "method", "reason"), [
    ({"doc": "src-ent-unregistered", "page": 1, "note": "x；录入人：张工"}, "manual", "未在企业库登记"),
    ({"doc": "DOC", "note": "原文“…”；录入人：张工"}, "manual", "页码与原文"),
    ({"doc": "DOC", "page": 3}, "manual", "页码与原文"),
    ({"page": 3, "note": "录入人：张工"}, "manual", "来源资料"),
    ({"doc": "DOC", "page": 3, "note": "原文“…”"}, "manual", "录入人"),
    ({}, "computed", "公式"),
])
def test_values_without_basis_are_refused(ent, spec_pdf, source, method, reason):
    doc = ent.register_document(spec_pdf, "规格书", "张工")["id"]
    src = {k: (doc if v == "DOC" else v) for k, v in source.items()}
    pv = {"value": 2, "method": method, "confidence": 1, "reviewed": True, "source": src}
    with pytest.raises(EnterpriseError, match=reason):
        ent.set_value(R, "params/backlash_arcmin", pv, "张工", PUBLIC.get)
    assert ent.get(R) is None  # 什么都没写


def test_schema_invalid_component_is_not_written(ent):
    bad = copy.deepcopy(PUBLIC.get(M))
    bad["params"]["rated_torque_nm"] = {"value": 1}  # 缺来源等必填
    with pytest.raises(EnterpriseError, match="schema"):
        ent.save_component(bad, "张工", "测试")
    assert ent.get(M) is None and not list((ent.directory / "components").rglob("*.json"))


def test_set_value_checks_target_and_component(ent, spec_pdf):
    doc = ent.register_document(spec_pdf, "规格书", "张工")["id"]
    pv = {"value": 2, "method": "manual", "confidence": 1, "reviewed": True,
          "source": {"doc": doc, "page": 3, "note": "原文；录入人：张工"}}
    with pytest.raises(EnterpriseError, match="没有端口"):
        ent.set_value(R, "ports/nope/x", pv, "张工", PUBLIC.get)
    with pytest.raises(EnterpriseError, match="字段须写成"):
        ent.set_value(R, "backlash", pv, "张工", PUBLIC.get)
    with pytest.raises(EnterpriseError, match="组件不存在"):
        ent.set_value("reducer.x.y", "params/a", pv, "张工", PUBLIC.get)


def test_choice_layers_enterprise_over_public(tmp_path, ent, spec_pdf):
    assert choose({}, ROOT, settings={}).enterprise is None
    c = choose({"FAP_ENTERPRISE_LIBRARY": str(ent.directory)}, ROOT, settings={})
    assert c.enterprise == ent.directory and c.note.startswith("企业库 0 个组件")
    lib = load(c)
    assert isinstance(lib, LayeredLibrary) and lib.get(M) == PUBLIC.get(M)
    bad = choose({}, ROOT, settings={"enterprise_library": str(tmp_path / "nope")})
    assert bad.enterprise is None and "企业库目录无效" in bad.note
    s = tmp_path / "settings.json"
    write_setting("enterprise_library", str(ent.directory), s)
    assert read_settings(s) == {"enterprise_library": str(ent.directory)}
    assert choose({}, ROOT, settings=read_settings(s)).enterprise == ent.directory
    assert read_settings(tmp_path / "missing.json") == {}
    json.loads(s.read_text(encoding="utf-8"))
