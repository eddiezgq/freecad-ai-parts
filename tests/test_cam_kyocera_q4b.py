"""问渠CAM Q4b 第十批（ADR-0106）：京瓷外圆切槽刀片 GMM / GMG → 刀具库。不联网、不读样本 PDF（CI 没有原始样本）。

抽查值是看样本页图抄的，与刀具库独立：
- G048：GMM2420-020MW 刃宽 2.4、RE 0.2；GMM8030-080MW 刃宽 8、RE 0.8；GMG3020-000MS RE 0；
- G049：GMG3520-030MG 刃宽 3.5（G143 没有这一档，不写参数）；GMM5020-250R 全圆弧 RE 2.5；
- G143 切槽一栏：碳钢 4.0 档 f 0.10~0.25；不锈钢 4.0 档 0.10~0.20；铸铁 6.0/8.0 档 0.20~0.40；铝合金 2.0~3.0 档 0.05~0.20；
  切削速度 碳钢 TN90 100~220、合金钢 PR930 70~180 → P 70–220；不锈钢 → 60–160。
"""

from __future__ import annotations

import json

import yaml

from analysis import cam
from analysis.cam import tools as TL
from assist import cam_process as CP
from ingest import cam_kyocera as KY

LIB_PATH = TL.BUILTIN / "kyocera.json"
LIB = json.loads(LIB_PATH.read_text(encoding="utf-8"))
BY_ID = {t["id"]: t for t in LIB["tools"]}
TG = json.loads((TL.BUILTIN / "tungaloy.json").read_text(encoding="utf-8"))


def _cut(tid, g):
    return next(c for c in BY_ID[tid]["cutting"] if c["iso_group"] == g)


def test_library_shape_and_source():
    assert len(LIB["tools"]) == 39 and TL.readonly(LIB_PATH)
    for t in LIB["tools"]:
        assert t["kind"] == "groove" and t["id"] == "KY-" + t["insert"]["iso"] and "internal" not in t
        assert t["source"]["ref"] == "kyocera" and t["source"]["page"].startswith("尺寸 G04")
        assert not any(c["iso_group"] in ("S", "H") for c in t.get("cutting") or [])     # G143 没有这两组
    src = {s["id"]: s for s in yaml.safe_load((TL.ROOT / "data" / "sources.yaml").read_text(encoding="utf-8"))["sources"]}["kyocera"]
    assert src["license"] == "params-only" and src["terms_checked"] is True and len(src["documents"][0]["sha256"]) == 64


def test_spot_check_against_catalog_pages():
    for tid, w, r in (("KY-GMM2420-020MW", 2.4, 0.2), ("KY-GMM8030-080MW", 8.0, 0.8), ("KY-GMG3020-000MS", 3.0, 0.0),
                      ("KY-GMM5020-250R", 5.0, 2.5)):
        assert (BY_ID[tid]["insert"]["width_mm"], BY_ID[tid]["insert"]["nose_radius_mm"]) == (w, r), tid
    assert "cutting" not in BY_ID["KY-GMG3520-030MG"]                                 # 3.5 不在任何刃宽档
    assert _cut("KY-GMM4020-040MW", "P") == {"iso_group": "P", "vc_m_min": {"min": 70, "max": 220}, "f_mm_rev": {"min": 0.10, "max": 0.25}}
    assert _cut("KY-GMM4020-040MW", "M")["f_mm_rev"] == {"min": 0.10, "max": 0.20}
    assert _cut("KY-GMM4020-040MW", "M")["vc_m_min"] == {"min": 60, "max": 160}
    assert _cut("KY-GMM8030-080MW", "K")["f_mm_rev"] == {"min": 0.20, "max": 0.40}
    assert _cut("KY-GMG2520-030MG", "N")["f_mm_rev"] == {"min": 0.05, "max": 0.20}


def test_width_bands():
    assert [KY._band(w) for w in (2.0, 2.4, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 7.0, 8.0)] == [0, 0, 0, 0, None, 1, 2, 3, None, 3]


def test_draft_groove_picks_widest_square_insert_and_cuts(tmp_path):
    """槽宽 4：挑不超过 4 的最宽刀片、不要全圆弧、刀尖圆弧最小；进给取 G143 的中间值；算通、出程序"""
    lib = {**TG, "tools": [*TG["tools"], *LIB["tools"]]}
    part = {"mode": "turn", "machine": "EX-LATHE", "kienzle": "C45E", "segments": [[24, 30], [40, 60]], "chamfer_mm": 1,
            "grooves": [{"z": -27, "width": 4, "d": 20}], "parting": {"tool_w": 3}}
    d = CP.draft(part, "P", lib)
    card = {r["id"]: r for r in d["card"]}
    g = BY_ID[card["groove1"]["tool"]]
    assert g["insert"]["width_mm"] == 4.0 and g["insert"]["nose_radius_mm"] == 0.2 and card["groove1"]["status"] == "pass"
    p = BY_ID[card["part"]["tool"]]
    assert p["insert"]["width_mm"] == 2.4                                                 # 切断取最窄的
    s = d["setup"]
    mix = tmp_path / "mix.json"                                                        # 车刀泰珂洛 + 切槽刀京瓷
    mix.write_text(json.dumps(lib, ensure_ascii=False), encoding="utf-8")
    s["machine_sim"]["tool_library"] = str(mix)
    r = cam.run({**s, "post": "fanuc"})
    assert all(pr["release"] is not None for pr in r["data"]["programs"])


def test_full_radius_only_when_nothing_else():
    full = [t for t in LIB["tools"] if t["id"].endswith("R")]
    op = {"kind": "groove", "cands": full}
    assert CP._rule_pick(op)["id"] == "KY-GMM6020-300R"                               # 只有全圆弧：照挑（最宽）
    sq = BY_ID["KY-GMM6020-040MW"]
    assert CP._rule_pick({"kind": "groove", "cands": [*full, sq]})["id"] == sq["id"]      # 有方角的就不挑全圆弧
