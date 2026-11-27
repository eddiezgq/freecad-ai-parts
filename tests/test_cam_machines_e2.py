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
    ("HAAS-VF-2", {"X": (762, 25400), "Y": (406, 25400), "Z": (508, 25400), "rpm": 8100, "kw": 22.4}),
    ("HAAS-VF-1", {"X": (508, 25400), "Y": (406, 25400), "Z": (508, 25400), "rpm": 8100, "kw": 22.4}),
    ("HAAS-VF-3", {"X": (1016, 25400), "Y": (508, 25400), "Z": (635, 25400), "rpm": 8100, "kw": 22.4}),
    ("HAAS-VF-4", {"X": (1270, 25400), "Y": (508, 25400), "Z": (635, 25400), "rpm": 8100, "kw": 22.4}),
    ("HAAS-ST-20", {"X": (426, 24000), "Z": (572, 24000), "rpm": 4000, "kw": 14.9}),
    ("HAAS-ST-30", {"X": (478, 24000), "Z": (826, 24000), "rpm": 3400, "kw": 22.4}),
    ("DN-LYNX-2100A", {"X": (410, 30000), "Z": (340, 36000), "rpm": 6000, "kw": 15.0}),
    ("OKUMA-LB3000EXII-L", {"X": (520, 25000), "Z": (565, 30000), "rpm": 5000, "kw": 22.0}),
    ("DMG-CLX-350-V1", {"X": (485, 30000), "Z": (540, 36000), "rpm": 5000, "kw": 16.5}),
    ("DMG-CLX-450-V1", {"X": (542, 30000), "Z": (830, 30000), "rpm": 4000, "kw": 25.5}),
    ("OKUMA-GENOS-L250-T", {"X": (320, 25000), "Z": (330, 30000), "rpm": 3000, "kw": 11.0}),
    ("OKUMA-GENOS-M460-VE", {"X": (762, 40000), "Y": (460, 40000), "Z": (460, 32000), "rpm": 15000, "kw": 22.0}),
    ("OKUMA-GENOS-M560-V", {"X": (1050, 40000), "Y": (560, 40000), "Z": (460, 32000), "rpm": 15000, "kw": 22.0}),
    ("OKUMA-GENOS-M660-V", {"X": (1500, 40000), "Y": (660, 40000), "Z": (660, 32000), "rpm": 15000, "kw": 22.0}),
    ("DN-PUMA-2100", {"X": (520, 30000), "Z": (590, 30000), "rpm": 4500, "kw": 25.0}),
    ("DN-PUMA-2600", {"X": (520, 30000), "Z": (830, 30000), "rpm": 3500, "kw": 30.0}),
    ("DN-PUMA-3100XL", {"X": (586, 30000), "Z": (2190, 30000), "rpm": 2800, "kw": 26.0}),
    ("DN-PUMA-GT3100", {"X": (520, 24000), "Z": (830, 30000), "rpm": 2800, "kw": 35.0})])
def test_haas_values_from_spec_pages(mid, vals):
    """规格页原文（2026-11-24 浏览器读）：ST-10 行程 X 200（直径 400）、Z 406，快移 30.5 m/min，6000 r/min、11.2 kW；
    VF-2 行程 762 / 406 / 508，快移 25.4 m/min，8100 r/min、22.4 kW，换刀（切削到切削）4.5 s"""
    m = M.model(mid)
    assert not MM.validate(m) and m["example"] is False and any(d in m["source"] for d in ("haascnc.com", "dn-solutions.com", "okuma.com", "dmgmori.com"))
    ax = {a["id"]: a for a in m["axes"]}
    for k, (span, rapid) in ((k, v) for k, v in vals.items() if k in ax):
        assert (ax[k]["max"] - ax[k]["min"], ax[k]["rapid"]) == (span, rapid), k
    assert (m["spindle"]["max_rpm"], m["spindle"]["power_kw"]) == (vals["rpm"], vals["kw"])
    gauge = {"HAAS-VF-2": 610 - 254, "HAAS-VF-1": 610 - 254, "HAAS-VF-3": 742 - 317.5, "HAAS-VF-4": 742 - 317.5}   # 主轴端面到工作台最大值 − Z 行程一半
    if mid in gauge:
        assert m["tool_change_s"] == 4.5 and m["tool"]["gauge_point_mm"][2] == gauge[mid]


def test_vf2_mill_program_releases():
    """VF-2 规格页公开了换刀时间，铣床不要换刀点：直接能编程——开槽、钻孔、攻丝出正式程序"""
    from tests import test_cam_post_q5 as Q5

    r = cam.run({"mode": "program", "machine": "HAAS-VF-2", "program": Q5._mill_prog(), "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": Q5.MSIM_MILL, "post": "fanuc"})
    p = r["data"]["programs"][0]
    assert r["status"] == "ok" and p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]


@pytest.mark.parametrize("mid,rpm,kw", [("MAZAK-QT-EZ-8", 6000, 15.0), ("MAZAK-QT-EZ-10", 4500, 15.0), ("MAZAK-QT-EZ-12", 4000, 22.0)])
def test_mazak_qt_ez_from_product_page(mid, rpm, kw):
    """马扎克美国官网 QT-Ez 产品页规格表（英制原文）：行程 X 9"、Z 25" 换成 228.6、635 mm；主轴转速、功率照抄；
    产品页没写快移，不编——各轴不带 rapid"""
    m = M.model(mid)
    assert not MM.validate(m) and m["example"] is False and "mazak.com" in m["source"] and "没公开" in m["source"]
    ax = {a["id"]: a for a in m["axes"]}
    assert (ax["X"]["max"] - ax["X"]["min"]) / 2 == pytest.approx(228.6) and ax["Z"]["max"] - ax["Z"]["min"] == pytest.approx(635.0)
    assert "rapid" not in ax["X"] and "rapid" not in ax["Z"]
    assert (m["spindle"]["max_rpm"], m["spindle"]["power_kw"]) == (rpm, kw)
    record_verdict(("真实机床：马扎克 QT-Ez 按官网产品页规格表录入，没公开的快移不编",
                    "real machine: Mazak QT-Ez entered from the official product-page spec table; unpublished rapids not invented"), "pass", "pass")


def test_mazak_missing_rapid_named_then_usable(tmp_path, monkeypatch):
    """只填了换刀点、换刀时间、没填快移：编程前报“没公开快移速度”（之前算用时会出 KeyError）；按实机填上快移后能编程"""
    monkeypatch.setenv("FAP_MACHINES_DIR", str(tmp_path / "m"))
    m = M.model("MAZAK-QT-EZ-10")
    base = {**{k: v for k, v in m.items() if not k.startswith("_")}, "lathe_home_mm": [200.0, 150.0], "tool_change_s": 0.5,
            "source": m["source"] + "；换刀点、换刀时间：车间实测（测试）"}
    M.save_model(base)
    req = {"mode": "turn", "machine": "MAZAK-QT-EZ-10", "segments": [[30, 30], [40, 20]], "machine_sim": {"tools": {}}}
    r = cam.run(req)
    assert r["status"] == "failed" and "没公开快移速度" in r["messages"][0]
    M.save_model({**base, "axes": [{**a, "rapid": 20000.0} for a in base["axes"]], "source": base["source"] + "；快移：车间实测（测试）"})
    assert cam.run(req)["status"] == "ok"
    record_verdict(("真实机床：快移没公开时编程前报出来，不出错", "real machine: unpublished rapid traverse is reported before programming instead of crashing"),
                   "error", "error")
