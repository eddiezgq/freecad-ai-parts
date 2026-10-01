"""组件知识库测试（issue #25，ADR-0018）。"""

import copy
import json
from pathlib import Path

import pytest

from kb.db import migrate
from kb.sources import SourceRegistry
from kb.store import (
    ImportRejected,
    change_log,
    check_component,
    export_snapshot,
    get_component,
    import_component,
    list_components,
)

GOLDEN_FIXTURES = sorted((Path(__file__).parent / "golden" / "fixtures").glob("*.json"))
EMPTY = SourceRegistry([])


def _fixture(name: str) -> dict:
    return json.loads((Path(__file__).parent / "golden" / "fixtures" / f"{name}.json").read_text("utf-8"))


def _as_real(comp: dict, doc: str) -> dict:
    """把虚构组件改成“真实”组件：去掉 test. 前缀，来源文档换成 doc。"""
    real = json.loads(json.dumps(comp).replace('"src-test-fixture"', json.dumps(doc)))
    real["id"] = real["id"].removeprefix("test.")
    return real


def _registry(license_: str = "pending", terms_checked: bool = False) -> SourceRegistry:
    return SourceRegistry.from_dict({"sources": [{
        "id": "acme", "vendor": "Acme", "license": license_, "terms_checked": terms_checked,
        "documents": [{"id": "src-acme-catalog"}],
    }]})


MOTOR = "test.servo_motor.test-vendor.m400"


# ---------- 不需要数据库的把关逻辑 ----------


def test_project_sources_file_loads():
    reg = SourceRegistry.load()
    assert "harmonic-drive" in reg.sources
    assert not reg.sources["harmonic-drive"].approved


def test_test_component_rejected_by_default():
    reasons = check_component(_fixture(MOTOR), EMPTY)
    assert any("虚构测试组件" in r for r in reasons)
    assert any("测试专用来源文档" in r for r in reasons)


def test_test_component_allowed_when_explicit():
    assert check_component(_fixture(MOTOR), EMPTY, allow_test=True) == []


def test_unregistered_document_rejected():
    reasons = check_component(_as_real(_fixture(MOTOR), "src-unknown-doc"), EMPTY)
    assert any("未在 data/sources.yaml 登记" in r for r in reasons)


def test_unapproved_source_rejected():
    reasons = check_component(_as_real(_fixture(MOTOR), "src-acme-catalog"), _registry())
    assert any("尚未核实条款或取得授权" in r for r in reasons)


@pytest.mark.parametrize("license_,checked", [("partner", False), ("params-only", True)])
def test_approved_source_accepted(license_: str, checked: bool):
    assert check_component(_as_real(_fixture(MOTOR), "src-acme-catalog"), _registry(license_, checked)) == []


def test_schema_invalid_rejected():
    comp = _fixture(MOTOR)
    del comp["envelope"]
    assert any(r.startswith("schema：") for r in check_component(comp, EMPTY, allow_test=True))


def test_duplicate_port_ids_rejected():
    comp = _fixture(MOTOR)
    comp["ports"].append(copy.deepcopy(comp["ports"][0]))
    assert any("端口 id 重复" in r for r in check_component(comp, EMPTY, allow_test=True))


def test_document_registered_twice_is_error():
    with pytest.raises(ValueError):
        SourceRegistry.from_dict({"sources": [
            {"id": "a", "documents": [{"id": "src-x"}]}, {"id": "b", "documents": [{"id": "src-x"}]}]})


# ---------- 数据库 ----------


def test_migrate_is_idempotent(db):
    assert migrate(db) == []


@pytest.mark.parametrize("path", GOLDEN_FIXTURES, ids=lambda p: p.stem)
def test_import_then_get_round_trip(db, path: Path):
    comp = json.loads(path.read_text("utf-8"))
    result = import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)
    assert result["status"] == "created"
    assert get_component(db, comp["id"]) == comp


def test_rejected_import_writes_nothing(db):
    with pytest.raises(ImportRejected):
        import_component(db, _fixture(MOTOR), registry=EMPTY, changed_by="test")
    assert list_components(db) == []


def test_reimport_unchanged(db):
    comp = _fixture(MOTOR)
    import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)
    again = import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)
    assert again == {"id": MOTOR, "status": "unchanged", "changes": 0}


def test_update_requires_reason(db):
    comp = _fixture(MOTOR)
    import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)
    comp["params"]["mass_kg"]["value"] = 1.3
    with pytest.raises(ValueError):
        import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)


def test_update_records_history(db):
    comp = _fixture(MOTOR)
    import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)
    old_mass = copy.deepcopy(comp["params"]["mass_kg"])
    comp["params"]["mass_kg"]["value"] = 1.3
    comp["ports"][0]["spec"]["diameter_mm"]["value"] = 16
    result = import_component(db, comp, registry=EMPTY, changed_by="reviewer", reason="复核更正",
                              allow_test=True)
    assert result == {"id": MOTOR, "status": "updated", "changes": 2}
    assert get_component(db, MOTOR) == comp
    log = change_log(db, MOTOR)
    assert [(e["scope"], e["name"]) for e in log] == [("component", "created"), ("param", "mass_kg"),
                                                      ("port", "shaft")]
    assert log[1]["old_value"] == old_mass
    assert log[1]["new_value"]["value"] == 1.3
    assert {e["reason"] for e in log[1:]} == {"复核更正"}
    assert {e["changed_by"] for e in log[1:]} == {"reviewer"}


def test_removed_param_is_logged(db):
    comp = _fixture(MOTOR)
    import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)
    del comp["params"]["mass_kg"]
    import_component(db, comp, registry=EMPTY, changed_by="test", reason="来源不支持该值", allow_test=True)
    entry = change_log(db, MOTOR)[-1]
    assert (entry["name"], entry["new_value"]) == ("mass_kg", None)


def test_list_by_category(db):
    for name in [MOTOR, "test.reducer.test-vendor.r20-100", "test.drive.test-vendor.d400"]:
        import_component(db, _fixture(name), registry=EMPTY, changed_by="test", allow_test=True)
    assert list_components(db, "reducer") == ["test.reducer.test-vendor.r20-100"]
    assert len(list_components(db)) == 3


def test_export_snapshot_round_trip(db, tmp_path: Path):
    comps = [json.loads(p.read_text("utf-8")) for p in GOLDEN_FIXTURES]
    for comp in comps:
        import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)
    files = export_snapshot(db, tmp_path)
    assert len(files) == len(comps)
    exported = {json.loads(f.read_text("utf-8"))["id"]: json.loads(f.read_text("utf-8")) for f in files}
    assert exported == {c["id"]: c for c in comps}
    assert all(f.parent.name == exported[f.stem]["category"] for f in files)
