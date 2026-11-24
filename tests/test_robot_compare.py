"""整机案例“和公开资料的对照”页（ADR-0115 44.3 之二第 8 步）：单位换算、我们的数取结果文件、缺项不猜"""

import copy
from pathlib import Path

import pytest

from assist import robot_compare as C
from assist import robot_report as R

CASE = Path(__file__).resolve().parents[1] / "examples" / "robots" / "teaching-arm"


@pytest.fixture(scope="module")
def res():
    return R.load(CASE / "out")


@pytest.fixture()
def ref():
    return C.load_reference(CASE / "reference.json")


def test_reference_units_are_converted_through_ingest(ref):
    by = {r["name"]: r for r in ref["robots"]}
    assert by["Magician"]["payload_kg"]["value_std"] == pytest.approx(0.5)
    assert by["Magician"]["joint_speed_rpm"]["value_std"] == pytest.approx(320 / 6)
    assert by["Ned2"]["joint_speed_rpm"]["min_std"] == pytest.approx(5.0)
    assert by["OpenMANIPULATOR-X（RM-X52-TNM）"]["joint_speed_rpm"]["value_std"] == pytest.approx(46)


def test_every_reference_has_url_date_and_quotes(ref):
    assert ref["accessed"]
    for r in ref["robots"]:
        assert r["url"].startswith("https://")
        for f in ("dof",) + C.FIELDS:
            if f in r:
                assert r[f]["quote"]


def test_our_numbers_come_from_the_result_files(res, ref):
    md = C.page(res, ref, R.bom(res))
    o = C.ours(res)
    assert o["mass_kg"] == res["cad"]["mass_kg"]
    assert o["repeatability_mm"] == res["build"]["repeatability"]["worst_mm"]
    assert f"| 5 | 0.5 | 350 | {round(res['cad']['mass_kg'], 3):g} | 0.25 | ±0.95 |" in md
    assert "只作参照" in md and "None" not in md and "null" not in md
    assert "58%" in md and "最低 3.7" in md


def test_missing_values_are_not_guessed(res, ref):
    r = copy.deepcopy(res)
    r.pop("verify")
    r["cad"].pop("mass_kg")
    ref2 = copy.deepcopy(ref)
    ref2["robots"][0].pop("repeatability_mm")
    md = C.page(r, ref2)
    row = next(x for x in md.splitlines() if x.startswith("| **本案例 A"))
    assert row.count("待确认") == 3                    # 自重、负载自重比、关节速度
    assert "未公开" in next(x for x in md.splitlines() if "OpenMANIPULATOR-X" in x and x.startswith("|"))
    assert "None" not in md


def test_report_write_also_writes_comparison(tmp_path, res):
    import shutil

    shutil.copytree(CASE / "out", tmp_path / "out")
    shutil.copy(CASE / "reference.json", tmp_path / "reference.json")
    R.write(tmp_path / "out")
    assert (tmp_path / "out" / "comparison.md").read_text(encoding="utf-8") == \
        (CASE / "out" / "comparison.md").read_text(encoding="utf-8")
