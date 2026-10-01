"""校验规则数据表（schema/rules/）的测试。

- 每张表通过自己的 schema 校验
- 来源引用必须指向表内声明的来源
- 状态为 verified 的表，每一项都必须已核对
- ISO 273：同一螺纹 精装 < 中等 < 粗装，且都大于螺纹公称直径
- ISO 286：孔-轴配对不重复
- 兼容矩阵：覆盖全部 4×4×4 组合，且每个组合只出现一次
"""

import itertools
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

RULES = Path(__file__).resolve().parent.parent / "schema" / "rules"
TABLES = sorted(p for p in RULES.glob("*.json") if not p.name.endswith(".schema.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _table(name: str) -> dict:
    return _load(RULES / f"{name}.json")


def test_three_tables_present():
    names = {p.stem for p in TABLES}
    assert names == {"iso273-clearance-holes", "iso286-fits", "feature-clamping-matrix", "bearing-fits"}


@pytest.mark.parametrize("path", TABLES, ids=lambda p: p.stem)
def test_table_matches_its_schema(path: Path):
    schema = _load(path.with_name(path.stem + ".schema.json"))
    errors = list(Draft202012Validator(schema).iter_errors(_load(path)))
    assert not errors, [e.message for e in errors]


@pytest.mark.parametrize("path", TABLES, ids=lambda p: p.stem)
def test_verified_status_requires_every_entry_verified(path: Path):
    table = _load(path)
    if table["status"] == "verified":
        assert all(e["verified"] for e in table["entries"])


@pytest.mark.parametrize("name", ["iso286-fits", "bearing-fits"])
def test_fit_sources_are_declared(name: str):
    table = _table(name)
    declared = {s["id"] for s in table["sources"]}
    for e in table["entries"]:
        assert set(e["sources"]) <= declared, e


def test_iso273_series_ordering():
    for e in _table("iso273-clearance-holes")["entries"]:
        nominal = float(e["thread"][1:])
        assert nominal < e["fine_mm"] < e["medium_mm"] < e["coarse_mm"], e


def test_iso273_threads_unique():
    threads = [e["thread"] for e in _table("iso273-clearance-holes")["entries"]]
    assert len(threads) == len(set(threads))


def test_fit_pairs_unique():
    pairs = [(e["hole"], e["shaft"]) for e in _table("iso286-fits")["entries"]]
    assert len(pairs) == len(set(pairs))


def test_matrix_complete_and_unique():
    features = ["plain", "keyed", "d_cut", "spline"]
    clamping = ["key", "clamp_ring", "set_screw", "press_fit"]
    keys = [
        (e["shaft_feature"], e["bore_feature"], e["clamping"])
        for e in _table("feature-clamping-matrix")["entries"]
    ]
    assert len(keys) == len(set(keys))
    assert set(keys) == set(itertools.product(features, features, clamping))


def test_matrix_non_pass_has_reason():
    for e in _table("feature-clamping-matrix")["entries"]:
        if e["result"] != "pass":
            assert e.get("reason"), e


def test_bearing_fit_ranges_and_mating():
    for e in _table("bearing-fits")["entries"]:
        assert e["d_over_mm"] < e["d_upto_mm"], e
        assert e["mating"] == ("shaft" if e["ring"] == "inner" else "housing"), e
        cls = e["classes"]
        if e["mating"] == "shaft":
            assert all(c[0].islower() for c in cls), e
        else:
            assert all(c[0].isupper() for c in cls), e


def test_bearing_fit_ranges_do_not_overlap():
    groups = {}
    for e in _table("bearing-fits")["entries"]:
        key = (e["ring"], e["load_on_ring"], e["load"])
        groups.setdefault(key, []).append((e["d_over_mm"], e["d_upto_mm"]))
    for key, ranges in groups.items():
        ranges.sort()
        for (a0, a1), (b0, b1) in itertools.pairwise(ranges):
            assert a1 <= b0, (key, ranges)
