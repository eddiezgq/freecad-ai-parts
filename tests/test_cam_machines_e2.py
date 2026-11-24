"""问渠CAM E2 真实机床（ADR-0106 E2）：参数只取厂商公开规格页、写出处；规格页没公开的（换刀点、换刀时间等）不编，编程前报出来，
按实机填好后能用。第一台：哈斯 ST-10Y。"""

from __future__ import annotations

import pytest

from analysis import cam
from analysis.cam import machine_model as MM
from analysis.cam import machines as M
from tests.verification import record_verdict


def test_haas_st10y_values_and_source():
    """数与规格页一致（行程 X 200、Y ±51、Z 406；快移 12 / 12 / 30.5 m/min；6000 r/min、11.2 kW），出处写在 source；不是示例"""
    m = M.model("HAAS-ST-10Y")
    assert not MM.validate(m) and m["example"] is False
    ax = {a["id"]: a for a in m["axes"]}
    assert (ax["X"]["max"] - ax["X"]["min"]) / 2 == 200 and (ax["Y"]["min"], ax["Y"]["max"]) == (-51, 51)
    assert ax["Z"]["max"] - ax["Z"]["min"] == 406
    assert (ax["X"]["rapid"], ax["Y"]["rapid"], ax["Z"]["rapid"]) == (12000, 12000, 30500)
    assert (m["spindle"]["max_rpm"], m["spindle"]["power_kw"]) == (6000, 11.2)
    assert "haascnc.com" in m["source"] and "没公开" in m["source"]
    assert "lathe_home_mm" not in m and "tool_change_s" not in m
    record_verdict(("真实机床：参数与厂商规格页一致、写明出处", "real machine: values match the maker's spec page, source given"), "pass", "pass")


def test_unpublished_items_named_then_usable(tmp_path, monkeypatch):
    """没填换刀点、换刀时间：编程时报“规格页没公开……”；按实机填好（用户机床目录）后车一根轴能算通"""
    monkeypatch.setenv("FAP_MACHINES_DIR", str(tmp_path / "m"))
    with pytest.raises(M.MachineError, match="没公开换刀点、换刀时间"):
        M.get("HAAS-ST-10Y")
    m = M.model("HAAS-ST-10Y")
    M.save_model({**{k: v for k, v in m.items() if not k.startswith("_")}, "lathe_home_mm": [250.0, 100.0], "tool_change_s": 0.5,
                  "source": m["source"] + "；换刀点、换刀时间：车间实测（测试）"})
    r = cam.run({"mode": "turn", "machine": "HAAS-ST-10Y", "segments": [[30, 30], [40, 20]], "machine_sim": {"tools": {}}})
    assert r["status"] == "ok", r["messages"]
    assert not [c for p in r["data"]["programs"] for c in p["checks"] if c["level"] == "error" and "超出" in c["text"]]
    record_verdict(("真实机床：规格页没公开的数不编，编程前报出来", "real machine: unpublished values are not invented and are reported before programming"),
                   "error", "error")
