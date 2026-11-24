"""整机案例的支架减薄（ADR-0115 44.3 之二第 9 步）：只选规格板厚、按疲劳 ≥ 2.0 接受、从末端往基座试、不合格就停"""

import json
import shutil
from pathlib import Path

import pytest

from assist import robot_cad as RC
from assist import robot_fea as RF
from assist import robot_thin as T

CASE = Path(__file__).resolve().parents[1] / "examples" / "robots" / "teaching-arm"


@pytest.fixture()
def case(tmp_path):
    out = tmp_path / "out"
    (out / "cad").mkdir(parents=True)
    for f in ("concept-result.json", "build-result.json", "verify-result.json", "fea-result.json"):
        shutil.copy(CASE / "out" / f, out / f)
    cad = json.loads((CASE / "out" / "cad" / "cad-result.json").read_text(encoding="utf-8"))
    before = json.loads((CASE / "out" / "thin-result.json").read_text(encoding="utf-8"))["before"]["parts"]
    for p in cad["parts"]:                       # 案例已减薄过：按 thin-result.json · before 退回减薄前的样子
        if p["name"].endswith("U 形支架"):
            p.update(plate_mm=before[p["name"]]["plate_mm"], mass_kg=before[p["name"]]["mass_kg"])
    (out / "cad" / "cad-result.json").write_text(json.dumps(cad, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_only_stock_thicknesses_down_to_3_mm():
    assert T.thinner(8.0) == 6.0 and T.thinner(4.0) == 3.0 and T.thinner(3.0) is None
    assert RC.clevis_plate_mm({"clevis_mm": {"j2": 3}}, "j2") == 3.0
    assert RC.clevis_plate_mm(None, "j2") == RC.DESIGN["plate_mm"]
    with pytest.raises(RC.CadError):
        RC.clevis_plate_mm({"clevis_mm": {"j2": 3.5}}, "j2")


def test_accept_needs_trusted_fea_and_fatigue_margin():
    assert T.accept({"status": "pass", "safety_fatigue": 2.0})
    assert not T.accept({"status": "pass", "safety_fatigue": 1.9})          # 过了需求 1.2，但没留够余量
    assert not T.accept({"status": "unknown", "safety_fatigue": 9.0})       # 有限元不可信不接受


def test_mesh_has_two_layers_through_the_plate():
    assert RF.mesh_mm({"plate_mm": 3.0}) == 1.5
    assert RF.mesh_mm({"plate_mm": 4.0}) == RF.MESH_MM == RF.mesh_mm({"plate_mm": 8.0}) == RF.mesh_mm({})


def test_run_goes_from_the_tip_and_stops_at_a_failure(case):
    calls = []

    def trial(plates, name, jid):
        calls.append((jid, plates["clevis_mm"][jid]))
        sf = {"j4": 30.0, "j3": 1.5, "j2": 6.0}[jid]
        return {"status": "pass", "safety_yield": 3 * sf, "safety_fatigue": sf, "mass_kg": 0.09}

    r = T.run(case, trial=trial)
    assert calls == [("j4", 3.0), ("j3", 3.0), ("j2", 3.0)]               # 4 mm 往下只有 3 mm 一级
    assert r["plates"]["clevis_mm"] == {"j4": 3.0, "j2": 3.0}               # j3 余量不够，留 4 mm
    assert [t["accepted"] for t in r["trials"]] == [True, False, True]
    saved = json.loads((case / "plates.json").read_text(encoding="utf-8"))
    assert saved == r["plates"]
    b = r["before"]["parts"]
    assert b["j2 U 形支架"]["plate_mm"] == 4.0 and b["j2 U 形支架"]["moving"] and not b["j1 基座"]["moving"]
    assert (case / "out" / "thin-result.json").exists()


def test_report_shows_before_and_after(case):
    from assist import robot_report as R

    T.run(case, trial=lambda p, n, j: {"status": "pass", "safety_fatigue": 5.0, "mass_kg": 0.09})
    res = R.load(case / "out")
    cad = res["cad"]
    for p in cad["parts"]:                                              # 假装已按 plates.json 重出了装配
        if p["name"].endswith("U 形支架"):
            p.update(plate_mm=3.0, mass_kg=0.09)
    lines = R.thin_section(res)
    md = "\n".join(lines)
    assert "| j2 U 形支架 | 4 → 3 |" in md and "跟着转的 0.0768 kg，固定不动的 0 kg" in md
    assert "None" not in md
