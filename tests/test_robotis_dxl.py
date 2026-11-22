"""ROBOTIS DYNAMIXEL X 规格表 → smart_actuator（ingest/robotis_dxl.py，ADR-0117 117.2）。

用虚构的小规格表测取值规则；再核对入库的 31 个型号都合 schema、来源登记且核过条款、数与规格表源文件抽查一致。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ingest import robotis_dxl as R
from kb.validation import errors

ROOT = Path(__file__).parents[1]
LIB = ROOT / "data" / "library" / "smart_actuator"

SAMPLE = """
common_x_specs:
  weight_430: &weight_430 "82 [g]"
  backlash_x: &backlash_x "15 [arcmin] (0.25 [&deg;])"
test-a100:
  weight: *weight_430
  dimensions: "28.5 x 46.5 x 34 [mm]"
  gearratio: "353.5 : 1"
  stalltorque: "3.8 [N.m] (at 11.1 [V], 2.1 [A], 1.810 [Nm/A])<br />**4.1 [N.m] (at 12.0 [V], 2.3 [A], 1.783 [Nm/A])**"
  noloadspeed: "43 [rev/min] (at 11.1 [V])<br />**46 [rev/min] (at 12.0 [V])**"
  voltage_en: "10.0 ~ 14.8 [V] (**Recommended : 12.0 [V]**)"
  backlash: *backlash_x
  resolution: "4096 [pulse/rev]"
  protocoltype: "TTL Half Duplex"
test-b200:
  weight: "23 [g]"
  dimensions: "20.0 x 34.0 x 26.0 [mm]"
  gearratio: "180.62 : 1"
  stalltorque: "0.65 [N.m] (at 9.0 [V], 0.61 [A], 1.066 [Nm/A])"
  noloadspeed: "83 [rev/min] (at 9.0 [V])"
  voltage_en: "6.5 ~ 12.0 [V] (**Recommended : 11.1 [V]**)"
  backlash: "N/A"
  resolution: "4096 [pulse/rev]"
2xl430-w250:
  weight: "98.2 [g]"
"""


@pytest.fixture
def sample(tmp_path):
    p = tmp_path / "x.yml"
    p.write_text(SAMPLE, encoding="utf-8")
    return R.build(p)


def test_values_at_the_recommended_voltage(sample):
    comps, _ = sample
    a = next(c for c in comps if c["model"] == "TEST-A100")
    p = a["params"]
    assert p["stall_torque_nm"]["value"] == 4.1 and "12 V" in p["stall_torque_nm"]["condition"]
    assert p["stall_current_a"]["value"] == 2.3
    assert p["no_load_speed_rpm"]["value"] == 46
    assert p["mass_kg"]["value"] == pytest.approx(0.082)
    assert p["gear_ratio"]["value"] == 353.5 and p["backlash_arcmin"]["value"] == 15
    assert "rated_torque_nm" not in p                                     # 厂商没给连续额定：不写
    spec = {q["id"]: q for q in a["ports"]}
    assert spec["power_in"]["spec"]["voltage_v"]["min"] == 10.0 and spec["power_in"]["spec"]["voltage_v"]["max"] == 14.8
    assert spec["bus"]["spec"]["protocol"]["value"] == "dynamixel_2"
    assert not {"output_flange", "mount"} & set(spec)                     # 孔位只在图纸里：不写
    assert not errors("component.schema.json", a)


def test_missing_row_at_recommended_voltage_is_left_out_not_guessed(sample):
    comps, report = sample
    b = next(c for c in comps if c["model"] == "TEST-B200")
    assert "stall_torque_nm" not in b["params"] and "no_load_speed_rpm" not in b["params"]   # 只有 9 V 一行，推荐 11.1 V
    assert any("11.1 V" in g for g in report["test-b200"])
    assert "backlash_arcmin" not in b["params"]                                              # N/A
    assert "2xl430-w250" in report and all(c["model"] != "2XL430-W250" for c in comps)      # 双轴不收


def test_envelope_is_a_conservative_box_around_any_axis_position(sample):
    comps, _ = sample
    env = next(c for c in comps if c["model"] == "TEST-A100")["envelope"]["parts"][0]
    a = max(28.5, 46.5, 34)
    assert env["z_start_mm"] == -a and env["length_mm"]["value"] == a
    assert env["width_mm"]["value"] == 2 * a and env["height_mm"]["value"] == 2 * a
    assert env["length_mm"]["method"] == "computed" and env["length_mm"]["source"]["formula"]


def test_library_entries_valid_registered_and_traceable():
    files = sorted(LIB.glob("*.json"))
    assert len(files) == 31
    src = yaml.safe_load((ROOT / "data" / "sources.yaml").read_text(encoding="utf-8"))
    rob = next(s for s in src["sources"] if s["id"] == "robotis")
    assert rob["terms_checked"] is True and rob["license"] == "params-only"
    assert R.SOURCE_DOC in {d["id"] for d in rob["documents"]}
    for f in files:
        c = json.loads(f.read_text(encoding="utf-8"))
        assert not errors("component.schema.json", c), f.name
        for k, v in c["params"].items():
            assert v["source"]["doc"] == R.SOURCE_DOC and "emanual.robotis.com" in v["source"]["note"], (f.name, k)
    xm = json.loads((LIB / "smart_actuator.robotis.xm430-w350.json").read_text(encoding="utf-8"))["params"]
    assert (xm["stall_torque_nm"]["value"], xm["no_load_speed_rpm"]["value"], xm["mass_kg"]["value"]) == (4.1, 46, 0.082)
    xl = json.loads((LIB / "smart_actuator.robotis.xm540-w270.json").read_text(encoding="utf-8"))["params"]
    assert (xl["stall_torque_nm"]["value"], xl["no_load_speed_rpm"]["value"], xl["mass_kg"]["value"]) == (10.6, 30, 0.165)
