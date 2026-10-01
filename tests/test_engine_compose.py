"""链路模板与候选求解（issue #53，ADR-0029）。"""

from __future__ import annotations

import copy

import pytest
from engine_helpers import FIXTURES, case_by_id

from engine.compose import compose_chain
from engine.result import FAIL

LIB = list(FIXTURES.values())


def _ids(cand):
    return [c["component"].split(".", 2)[-1] for c in cand.system["components"]]


def test_finds_golden_solution_with_adapters():
    req = case_by_id("valid/m200-adapters-r25-d400")["system"]["requirement"]
    res = compose_chain(req, LIB)
    top = res[0]
    assert top.overall == "pass" and top.adapters == 2
    assert {"test-vendor.m200", "test-vendor.r25-100", "test-vendor.sleeve-11-19", "test-vendor.plate-70-90"} <= set(_ids(top))
    conns = {(c["a"], c["b"]) for c in top.system["connections"]}
    assert ("motor.shaft", "sleeve.inner") in conns and ("plate.reducer_side", "reducer.motor_flange") in conns


def test_no_fail_and_ranked():
    req = case_by_id("valid/m400-r20-d400")["system"]["requirement"]
    res = compose_chain(req, LIB, top_n=20, include_unknown=True)
    assert res and all(c.overall != FAIL for c in res)
    keys = [c.sort_key() for c in res]
    assert keys == sorted(keys)
    rank = {"pass": 0, "warn": 1, "unknown": 2}
    assert [rank[c.overall] for c in res] == sorted(rank[c.overall] for c in res)
    assert [c.system["id"] for c in res] == [f"candidate-{i}" for i in range(1, len(res) + 1)]
    assert any(c.overall == "unknown" for c in res)  # 缺数据的 fixtures 只在要求时返回
    assert not any(c.overall == "unknown" for c in compose_chain(req, LIB, top_n=20))


def test_dedupe_one_drive_per_mechanical_chain():
    req = case_by_id("valid/m400-r20-d400")["system"]["requirement"]
    res = compose_chain(req, LIB, top_n=20)
    chains = [tuple(c["component"] for c in r.system["components"] if c["instance"] != "drive") for r in res]
    assert len(chains) == len(set(chains))


def test_deterministic_and_order_independent():
    req = case_by_id("valid/m750-r25-d750")["system"]["requirement"]
    a = [c.to_dict() for c in compose_chain(req, LIB, top_n=10)]
    b = [c.to_dict() for c in compose_chain(req, list(reversed(LIB)), top_n=10)]
    assert a == b


def test_top_n_and_impossible():
    req = case_by_id("valid/m400-r20-d400")["system"]["requirement"]
    assert len(compose_chain(req, LIB, top_n=1)) == 1
    impossible = {**req, "output_torque_cont_nm": 1000}
    assert compose_chain(impossible, LIB) == []


def test_reports_are_full_validations():
    req = case_by_id("valid/m750-r25-d750")["system"]["requirement"]
    top = compose_chain(req, LIB, top_n=1)[0]
    assert [c["check"] for c in top.report["checks"]] == [f"C{i}" for i in range(1, 12)]
    assert top.report["system"] == top.system["id"]


def test_missing_mass_ranks_later():
    req = case_by_id("valid/m750-r25-d750")["system"]["requirement"]
    lib = copy.deepcopy(LIB)
    for c in lib:
        if c["id"] == "test.servo_motor.test-vendor.m750":
            c["params"].pop("mass_kg")
    res = compose_chain(req, lib, top_n=10)
    m750 = [r for r in res if "test-vendor.m750" in _ids(r)]
    assert all(r.mass_kg is None for r in m750)


@pytest.mark.parametrize("cat", ["servo_motor", "reducer", "drive"])
def test_empty_category(cat):
    req = case_by_id("valid/m400-r20-d400")["system"]["requirement"]
    assert compose_chain(req, [c for c in LIB if c["category"] != cat]) == []
