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
        "id": "acme", "vendor": "Test Vendor", "license": license_, "terms_checked": terms_checked,
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


# ---------- 独立评审（PR #33）发现的问题的回归测试 ----------


def _schema_of(conn) -> str:
    return conn.execute("SHOW search_path").fetchone()[0].split(",")[0].strip()


def _url_with_search_path(url: str, schema: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}options=-c%20search_path%3D{schema},public"


def test_connect_commits_writes(db, db_url):
    from kb.db import connect

    conn = connect(_url_with_search_path(db_url, _schema_of(db)))
    try:
        import_component(conn, _fixture(MOTOR), registry=EMPTY, changed_by="test", allow_test=True)
    finally:
        conn.close()
    assert get_component(db, MOTOR) == _fixture(MOTOR)


def test_non_autocommit_connection_rejected(db, db_url):
    import psycopg

    conn = psycopg.connect(_url_with_search_path(db_url, _schema_of(db)))
    try:
        with pytest.raises(ValueError):
            migrate(conn)
        with pytest.raises(ValueError):
            import_component(conn, _fixture(MOTOR), registry=EMPTY, changed_by="test", allow_test=True)
    finally:
        conn.close()


def test_port_change_and_reorder_both_logged(db):
    comp = _fixture(MOTOR)
    import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)
    comp["ports"].reverse()
    shaft = next(p for p in comp["ports"] if p["id"] == "shaft")
    shaft["spec"]["diameter_mm"]["value"] = 16
    import_component(db, comp, registry=EMPTY, changed_by="test", reason="改直径并重排", allow_test=True)
    names = [(e["scope"], e["name"]) for e in change_log(db, MOTOR)[1:]]
    assert names == [("port", "shaft"), ("component", "port_order")]
    assert get_component(db, MOTOR) == comp


def test_reorder_only_logged(db):
    comp = _fixture(MOTOR)
    import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)
    comp["ports"].reverse()
    result = import_component(db, comp, registry=EMPTY, changed_by="test", reason="重排", allow_test=True)
    assert result["changes"] == 1
    assert change_log(db, MOTOR)[-1]["name"] == "port_order"


def test_component_field_change_logged(db):
    comp = _fixture(MOTOR)
    import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)
    comp["status"] = "discontinued"
    import_component(db, comp, registry=EMPTY, changed_by="test", reason="停产", allow_test=True)
    entry = change_log(db, MOTOR)[-1]
    assert (entry["scope"], entry["name"], entry["old_value"], entry["new_value"]) == (
        "component", "status", "active", "discontinued")


@pytest.mark.parametrize("changed_by,reason", [("", "复核"), ("   ", "复核"), ("test", ""), ("test", "   ")])
def test_blank_reason_or_changed_by_rejected(db, changed_by, reason):
    comp = _fixture(MOTOR)
    import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)
    comp["params"]["mass_kg"]["value"] = 1.3
    with pytest.raises(ValueError):
        import_component(db, comp, registry=EMPTY, changed_by=changed_by, reason=reason, allow_test=True)


def test_blank_changed_by_rejected_on_create(db):
    with pytest.raises(ValueError):
        import_component(db, _fixture(MOTOR), registry=EMPTY, changed_by=" ", allow_test=True)


@pytest.mark.parametrize("bad", ["a string", None, 42])
def test_non_object_rejected_cleanly(bad):
    assert check_component(bad, EMPTY) == ["组件必须是 JSON 对象"]


def test_malformed_ports_rejected_cleanly(db):
    comp = _fixture(MOTOR)
    comp["ports"] = None
    with pytest.raises(ImportRejected):
        import_component(db, comp, registry=EMPTY, changed_by="test", allow_test=True)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_number_rejected(bad):
    comp = _fixture(MOTOR)
    comp["params"]["mass_kg"]["value"] = bad
    assert any("不是有限数值" in r for r in check_component(comp, EMPTY, allow_test=True))


def test_nul_character_rejected():
    comp = _fixture(MOTOR)
    comp["note"] = "abc\x00def"
    assert any("NUL" in r for r in check_component(comp, EMPTY, allow_test=True))


def test_unapproved_document_in_envelope_rejected():
    comp = _as_real(_fixture(MOTOR), "src-acme-catalog")
    reg = _registry("partner")
    comp["envelope"]["parts"][0]["length_mm"]["source"]["doc"] = "src-other-doc"
    assert any("src-other-doc" in r for r in check_component(comp, reg))


def test_get_missing_component_returns_none(db):
    assert get_component(db, "servo_motor.nobody.nothing") is None


def test_change_log_is_append_only(db):
    import psycopg

    import_component(db, _fixture(MOTOR), registry=EMPTY, changed_by="test", allow_test=True)
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("UPDATE change_log SET reason = 'x'")
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("DELETE FROM change_log")


def test_export_is_byte_stable_and_prunes(db, tmp_path: Path):
    import_component(db, _fixture(MOTOR), registry=EMPTY, changed_by="test", allow_test=True)
    first = export_snapshot(db, tmp_path)[0].read_bytes()
    second = export_snapshot(db, tmp_path)[0].read_bytes()
    assert first == second
    stale = tmp_path / "reducer" / "test.reducer.old.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    export_snapshot(db, tmp_path, prune=True)
    assert not stale.exists()


# ---------- 厂商与来源一致（issue #34，ADR-0019） ----------


def _vendor_registry(vendor: str = "Test Vendor", covers: list[str] | None = None) -> SourceRegistry:
    return SourceRegistry.from_dict({"sources": [{
        "id": "acme", "vendor": vendor, "license": "partner", "covers_vendors": covers or [],
        "documents": [{"id": "src-acme-catalog"}],
    }]})


def test_document_of_same_vendor_accepted():
    comp = _as_real(_fixture(MOTOR), "src-acme-catalog")
    assert check_component(comp, _vendor_registry("  test   VENDOR ")) == []


def test_document_of_other_vendor_rejected():
    comp = _as_real(_fixture(MOTOR), "src-acme-catalog")
    reasons = check_component(comp, _vendor_registry("Acme"))
    assert any("不能用于厂商 Test Vendor" in r for r in reasons)


def test_distributor_document_accepted_when_vendor_listed():
    comp = _as_real(_fixture(MOTOR), "src-acme-catalog")
    assert check_component(comp, _vendor_registry("Distributor Ltd", ["Test Vendor"])) == []
