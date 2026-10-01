"""golden 用例的结构测试（M1）。

引擎在 M3 才实现，这里先保证用例本身是良构的：
- 每个用例的 system 通过 system.schema.json 校验
- 引用的组件都在 tests/golden/fixtures/ 中，且通过 component.schema.json 校验
- 连接引用的实例与端口都存在，且每个端口最多连接一次
- expected 的取值合法；C1–C11 每项至少有一个 invalid 用例覆盖（实施细则第九节）
- 至少 3 个 valid 用例，且每个 unknown 用例的整体结论为 unknown

预期结果由人手算并审定；不得为了让测试通过而修改预期（CLAUDE.md）。
"""

import json
from collections import Counter
from pathlib import Path

import pytest
import yaml
from test_schema import _validator

GOLDEN = Path(__file__).resolve().parent / "golden"
CASES = sorted(GOLDEN.glob("*/*.yaml"))
FIXTURES = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (GOLDEN / "fixtures").glob("*.json")}
CHECKS = {f"C{i}" for i in range(1, 12)}
STATUS = {"pass", "warn", "fail", "unknown"}
CHECK_VALUES = STATUS | {"any"}


def _case(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _kind(path: Path) -> str:
    return path.parent.name


@pytest.mark.parametrize("cid", sorted(FIXTURES), ids=str)
def test_fixture_component_valid(cid: str):
    component = FIXTURES[cid]
    assert component["id"] == cid
    assert cid.startswith("test."), "golden 组件必须是虚构组件（ADR-0015）"
    errors = list(_validator("component.schema.json").iter_errors(component))
    assert not errors, [e.message for e in errors]


@pytest.mark.parametrize("path", CASES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_case_structure(path: Path):
    case = _case(path)
    assert case["id"] == f"{_kind(path)}/{path.stem}"
    system = case["system"]
    errors = list(_validator("system.schema.json").iter_errors(system))
    assert not errors, [e.message for e in errors]

    instances = {}
    for c in system["components"]:
        assert c["instance"] not in instances, f"实例名重复：{c['instance']}"
        assert c["component"] in FIXTURES, f"组件不存在：{c['component']}"
        instances[c["instance"]] = FIXTURES[c["component"]]

    used = Counter()
    for conn in system["connections"]:
        for ref in (conn["a"], conn["b"]):
            inst, port = ref.split(".")
            assert inst in instances, f"实例不存在：{ref}"
            assert port in {p["id"] for p in instances[inst]["ports"]}, f"端口不存在：{ref}"
            used[ref] += 1
    assert all(n == 1 for n in used.values()), f"端口重复连接：{used}"


@pytest.mark.parametrize("path", CASES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_case_expected_values(path: Path):
    expected = _case(path)["expected"]
    assert expected["overall"] in STATUS
    checks = dict(expected["checks"])
    others = checks.pop("others", None)
    assert others in (None, "not_fail")
    assert set(checks) <= CHECKS
    assert set(checks.values()) <= CHECK_VALUES
    if _kind(path) == "unknown":
        assert expected["overall"] == "unknown"
    if _kind(path) == "valid":
        assert expected["overall"] in {"pass", "warn"}
    assert _case(path).get("calc"), "每个用例都要写手算过程"


def test_coverage():
    kinds = Counter(_kind(p) for p in CASES)
    assert kinds["valid"] >= 3
    assert kinds["unknown"] >= 1
    covered = set()
    for p in CASES:
        if _kind(p) == "invalid":
            covered |= {k for k, v in _case(p)["expected"]["checks"].items() if v in {"fail", "warn"}}
    assert CHECKS <= covered, f"未覆盖：{sorted(CHECKS - covered)}"
