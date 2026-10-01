"""schema 测试。

- schema/ 下每个 *.schema.json 必须是合法的 JSON Schema（Draft 2020-12），$id 唯一
- tests/fixtures/ 下的合法样例必须通过校验，非法样例必须被拒绝
- 每种端口类型至少 1 个合法样例和 1 个非法样例（实施细则第九节）
- 端口类型的 x-connects-to 必须指向已定义的类型且互相对称
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schema"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCHEMA_FILES = sorted(SCHEMA_DIR.rglob("*.schema.json"))
ID_BASE = "https://github.com/eddiezgq/freecad-ai-parts/schema/"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry() -> Registry:
    resources = [(s["$id"], Resource.from_contents(s)) for s in map(_load, SCHEMA_FILES)]
    return Registry().with_resources(resources)


REGISTRY = _registry()


def _validator(relative_id: str) -> Draft202012Validator:
    schema = REGISTRY.contents(ID_BASE + relative_id)
    return Draft202012Validator(schema, registry=REGISTRY)


def _fixtures(group: str, kind: str) -> list[Path]:
    return sorted((FIXTURES / group / kind).glob("*.json"))


# ---------- schema 本身 ----------


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: str(p.relative_to(SCHEMA_DIR)))
def test_schema_is_valid(path: Path):
    Draft202012Validator.check_schema(_load(path))


def test_schema_ids_unique_and_match_paths():
    for path in SCHEMA_FILES:
        expected = ID_BASE + path.relative_to(SCHEMA_DIR).as_posix()
        assert _load(path)["$id"] == expected, path


# ---------- 参数值 ----------

PV = "common/param-value.schema.json"


@pytest.mark.parametrize("path", _fixtures("param-value", "valid"), ids=lambda p: p.stem)
def test_param_value_valid(path: Path):
    errors = list(_validator(PV).iter_errors(_load(path)["instance"]))
    assert not errors, [e.message for e in errors]


@pytest.mark.parametrize("path", _fixtures("param-value", "invalid"), ids=lambda p: p.stem)
def test_param_value_invalid(path: Path):
    assert not _validator(PV).is_valid(_load(path)["instance"]), _load(path)["why"]


# ---------- 端口 ----------

PORT = "port.schema.json"
PORT_TYPE_FILES = sorted((SCHEMA_DIR / "port-types").glob("*.schema.json"))
PORT_TYPES = [p.name.removesuffix(".schema.json") for p in PORT_TYPE_FILES]


@pytest.mark.parametrize("path", _fixtures("ports", "valid"), ids=lambda p: p.stem)
def test_port_valid(path: Path):
    errors = list(_validator(PORT).iter_errors(_load(path)["instance"]))
    assert not errors, [e.message for e in errors]


@pytest.mark.parametrize("path", _fixtures("ports", "invalid"), ids=lambda p: p.stem)
def test_port_invalid(path: Path):
    assert not _validator(PORT).is_valid(_load(path)["instance"]), _load(path)["why"]


def test_v1_has_eight_port_types():
    assert len(PORT_TYPES) == 8


@pytest.mark.parametrize("port_type", PORT_TYPES)
def test_each_port_type_has_valid_and_invalid_samples(port_type: str):
    def types(kind: str) -> set[str]:
        return {_load(p)["instance"].get("type") for p in _fixtures("ports", kind)}

    assert port_type in types("valid")
    assert port_type in types("invalid")


def test_connects_to_is_known_and_symmetric():
    connects = {t: _load(f)["x-connects-to"] for t, f in zip(PORT_TYPES, PORT_TYPE_FILES)}
    for t, targets in connects.items():
        for target in targets:
            assert target in connects, f"{t} -> 未定义的 {target}"
            assert t in connects[target], f"{t} -> {target} 不对称"
