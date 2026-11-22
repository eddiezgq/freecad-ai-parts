"""问渠CAM Q4b 第三批（ADR-0106）：泰珂洛 ISO-EcoTurn 车刀片样本 → 刀具库。不联网、不读样本 PDF（CI 没有原始样本）。

抽查值是看样本页图（第 26、58、59 页）抄的，与程序抽取独立：
- 第 26 页 WN 刀片：WNMG060404E-SM、WNMG060408E-SW、WNMA060416E 的 RE、IC；
- 第 58 页 P 组（中碳钢、合金钢一栏）：TM = T9215 150–400 与 T9225 120–300 → 120–400，f 0.2–0.5，ap ≤ 3；
  TF = 150–400、120–300、80–220 → 80–400，f 0.03–0.15，ap ≤ 0.5；SW = 180–400、150–400、120–300 → 120–400，f 0.3–0.6，ap ≤ 2；
- 第 59 页 M 组 SM：T6215 140–240 / 160–280 / 80–150，T6225、AH6225 90–200 / 110–240 / 60–110 → 60–280，f 0.2–0.5，ap ≤ 3；
  K 组 TM（T515，灰铸铁一栏）150–700，f 0.2–0.5，ap ≤ 3；无断屑槽（T515）150–700，f 0.2–0.6，ap ≤ 2。
"""

from __future__ import annotations

import json
import re

import pytest

from analysis import cam
from analysis.cam import tools as TL
from assist import cam_process as CP
from ingest import cam_tungaloy as TG

LIB_PATH = TL.BUILTIN / "tungaloy.json"
LIB = json.loads(LIB_PATH.read_text(encoding="utf-8"))
BY_ID = {t["id"]: t for t in LIB["tools"]}


def _cut(tid, g):
    return next(c for c in BY_ID[tid]["cutting"] if c["iso_group"] == g)


def test_spot_check_against_catalog_pages():
    for tid, re_, ic in (("TG-WNMG060404E-SM", 0.4, 9.525), ("TG-WNMG060408E-SW", 0.8, 9.525), ("TG-WNMA060416E", 1.6, 9.525)):
        ins = BY_ID[tid]["insert"]
        assert (ins["nose_radius_mm"], ins["inscribed_circle_mm"]) == (re_, ic), tid
    c = _cut("TG-CNMG090408E-TM", "P")
    assert (c["vc_m_min"], c["f_mm_rev"], c["ap_max_mm"]) == ({"min": 120, "max": 400}, {"min": 0.2, "max": 0.5}, 3)
    c = _cut("TG-CNMG090404E-TF", "P")
    assert (c["vc_m_min"], c["f_mm_rev"], c["ap_max_mm"]) == ({"min": 80, "max": 400}, {"min": 0.03, "max": 0.15}, 0.5)
    c = _cut("TG-WNMG060408E-SW", "P")
    assert (c["vc_m_min"], c["f_mm_rev"], c["ap_max_mm"]) == ({"min": 120, "max": 400}, {"min": 0.3, "max": 0.6}, 2)
    c = _cut("TG-WNMG060404E-SM", "M")
    assert (c["vc_m_min"], c["f_mm_rev"], c["ap_max_mm"]) == ({"min": 60, "max": 280}, {"min": 0.2, "max": 0.5}, 3)
    assert [g["iso_group"] for g in BY_ID["TG-WNMG060404E-SM"]["cutting"]] == ["M"]        # SM 只有 M 组材质
    c = _cut("TG-CNMG090408E-TM", "K")
    assert (c["vc_m_min"], c["f_mm_rev"], c["ap_max_mm"]) == ({"min": 150, "max": 700}, {"min": 0.2, "max": 0.5}, 3)
    c = _cut("TG-WNMA060416E", "K")
    assert (c["vc_m_min"], c["f_mm_rev"], c["ap_max_mm"]) == ({"min": 150, "max": 700}, {"min": 0.2, "max": 0.6}, 2)


def test_library_shape_and_sources():
    assert len(LIB["tools"]) == 176 and TL.readonly(LIB_PATH)
    for t in LIB["tools"]:
        assert t["kind"] == "turn" and t["id"] == "TG-" + t["insert"]["iso"]
        assert "tool_material" not in t and "holder" not in t and "cutting_edge_angle_deg" not in t["insert"]   # 样本按刀杆、材质分，不写
        assert t["source"]["ref"] == "tungaloy" and re.match(r"尺寸 \d{1,2}(；切削条件 58–59)?", t["source"]["page"])
    from pathlib import Path

    import yaml

    reg = yaml.safe_load(Path("data/sources.yaml").read_text(encoding="utf-8"))
    src = {s["id"]: s for s in reg["sources"]}["tungaloy"]
    assert src["license"] == "params-only" and src["terms_checked"] is True and len(src["documents"][0]["sha256"]) == 64


def test_parsers_on_catalog_text():
    dims = ("         TF                 CNMG090402E-TF                      0.2 9.525 4.76 3.81\n"
            "                            CNMG090404E-SS\n"                                # 这行没印尺寸：不收
            "     -    WNMA060404E                                0.4 9.525 4.76 3.81\n")
    assert [r["code"] for r in TG.dims_rows(dims)] == ["CNMG090402E-TF", "WNMA060404E"]
    cond = ("                          TF    T9215    0.1 - 0.5    0.03 - 0.15    150 - 400        150 - 400       120 - 300\n"
            "      精加工    SS    AH6235    0.5 - 3     0.08 - 0.2      50 - 150          70 - 170                  -\n"
            "             无断屑槽    T515     0.05 - 2     0.2 - 0.6          150 - 700                   150 - 300\n")
    rows = TG.cond_rows(cond)
    assert [(r["breaker"], r["grade"]) for r in rows] == [("TF", "T9215"), ("SS", "AH6235"), ("无断屑槽", "T515")]
    assert rows[1]["vc"] == [(50, 150), (70, 170), None]
    t = TG.cutting_table(rows)
    assert t["SS"]["M"]["vc"] == [50, 170] and t["TF"]["P"]["vc"] == [150, 400] and t["无断屑槽"]["K"]["vc"] == [150, 700]
    with pytest.raises(TG.TungaloyError):
        TG.cutting_table([{"breaker": "XX", "grade": "Z9999", "ap": (1, 2), "f": (0.1, 0.2), "vc": [(1, 2), None, None]}])


def test_draft_turning_with_tungaloy_library():
    """用泰珂洛库起草阶梯轴：粗车挑样本切深大的断屑槽、刀尖 ≤ R0.8 的 80° 刀片，参数按机床功率降到 80% 以内；精车取最小刀尖圆弧；算通、出程序"""
    part = {"mode": "turn", "machine": "EX-LATHE", "kienzle": "C45E", "segments": [[30, 40], [40, 60], [35, 25], [30, 30]], "chamfer_mm": 1}
    d = CP.draft(part, "P", LIB)
    card = {r["id"]: r for r in d["card"]}
    assert card["rough"]["tool"] == "TG-CNMG090408E-TM" and card["finish"]["tool"].endswith("02E-TF")
    p = card["rough"]["params"]
    assert 120 <= p["vc"] < 260 and any("80%" in n for n in d["notes"])            # 中间值 260 超功率，降到样本范围内
    s = d["setup"]
    s["machine_sim"]["tool_library"] = str(LIB_PATH)
    r = cam.run({**s, "post": "fanuc"})
    assert r["status"] == "ok"
    for prog in r["data"]["programs"]:
        assert prog["release"] is not None and not [c for c in prog["checks"] if c["level"] == "error"]
