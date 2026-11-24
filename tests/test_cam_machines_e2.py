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


@pytest.mark.parametrize("mid,vals", [
    ("HAAS-ST-10", {"X": (400, 30500), "Z": (406, 30500), "rpm": 6000, "kw": 11.2}),
    ("HAAS-VF-2", {"X": (762, 25400), "Y": (406, 25400), "Z": (508, 25400), "rpm": 8100, "kw": 22.4})])
def test_haas_values_from_spec_pages(mid, vals):
    """规格页原文（2026-11-24 浏览器读）：ST-10 行程 X 200（直径 400）、Z 406，快移 30.5 m/min，6000 r/min、11.2 kW；
    VF-2 行程 762 / 406 / 508，快移 25.4 m/min，8100 r/min、22.4 kW，换刀（切削到切削）4.5 s"""
    m = M.model(mid)
    assert not MM.validate(m) and m["example"] is False and "haascnc.com" in m["source"]
    ax = {a["id"]: a for a in m["axes"]}
    for k, (span, rapid) in ((k, v) for k, v in vals.items() if k in ax):
        assert (ax[k]["max"] - ax[k]["min"], ax[k]["rapid"]) == (span, rapid), k
    assert (m["spindle"]["max_rpm"], m["spindle"]["power_kw"]) == (vals["rpm"], vals["kw"])
    if mid == "HAAS-VF-2":
        assert m["tool_change_s"] == 4.5 and m["tool"]["gauge_point_mm"][2] == 610 - 254


def test_vf2_mill_program_releases():
    """VF-2 规格页公开了换刀时间，铣床不要换刀点：直接能编程——开槽、钻孔、攻丝出正式程序"""
    from tests import test_cam_post_q5 as Q5

    r = cam.run({"mode": "program", "machine": "HAAS-VF-2", "program": Q5._mill_prog(), "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": Q5.MSIM_MILL, "post": "fanuc"})
    p = r["data"]["programs"][0]
    assert r["status"] == "ok" and p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
