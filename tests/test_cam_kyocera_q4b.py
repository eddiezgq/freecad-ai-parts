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


# ---------------------------------------------------------------- 切槽刀杆（ADR-0118）
HL_PATH = TL.BUILTIN / "kyocera-holders.json"
HL = json.loads(HL_PATH.read_text(encoding="utf-8"))
HBY = {h["id"]: h for h in HL["holders"]}


def test_groove_holders_spot_check_g056():
    """G056 图抄的：KGMR2525M-3 CDX 9、25×25、LH 27、LF 150、WF 23.8、CW 3–4；KGMR2020K-5 WF 17.8、CW 5–6；
    KGM 2525M-8 CDX 25、LH 40；1212H-3、1616H-3、2020K-4、2020K-5、2525M-5 只有右手"""
    assert len(HL["holders"]) == 13
    h = HBY["KY-KGMR2525M-3"]
    assert (h["max_depth_mm"], h["h_mm"], h["b_mm"], h["head_mm"], h["l1_mm"], h["f_mm"]) == (9, 25, 25, 27, 150, 23.8)
    assert h["insert"]["groove_width_mm"] == {"min": 3, "max": 4} and h["use"] == "groove"
    assert HBY["KY-KGMR2020K-5"]["f_mm"] == 17.8 and HBY["KY-KGMR2020K-5"]["insert"]["groove_width_mm"] == {"min": 5, "max": 6}
    assert (HBY["KY-KGML2525M-8"]["max_depth_mm"], HBY["KY-KGML2525M-8"]["head_mm"]) == (25, 40)
    for c in ("1212H-3", "1616H-3", "2020K-4", "2020K-5", "2525M-5"):
        assert "KY-KGMR" + c in HBY and "KY-KGML" + c not in HBY


def test_pick_groove_by_width_and_depth():
    from analysis.cam import holders as HD

    assert HD.pick_groove(4.0, 2.0)["id"] == "KY-KGMR2525M-3"          # 3–4 和 4–5 都装得上：25×25 里取槽深小的
    assert HD.pick_groove(4.0, 9.5)["id"] == "KY-KGMR2525M-4"          # 9.5 深：CDX 9 的不行
    assert HD.pick_groove(4.0, 12.0) is None                           # 都不到 12
    assert HD.pick_groove(8.0, 20.0)["id"] == "KY-KGMR2525M-8"
    assert HD.pick_groove(4.0, 2.0, hand="L")["id"] == "KY-KGML2525M-3"
    assert HD.pick_groove(2.4) is None                                 # 没有装 2.4 的
    assert HD.pick_groove(4.0, 2.0, ref="tungaloy") is None            # 刀座各家不通用：别家的刀片不配京瓷刀杆
    assert HD.pick_groove(4.0, 2.0, ref="kyocera")["id"] == "KY-KGMR2525M-3"


def test_square_vendor_holder_box():
    from analysis.cam import holders as HD

    bx, notes = HD.boxes(HD.as_tool_holder(HBY["KY-KGMR2525M-3"]))
    assert bx == [[27.0, -25.0, 23.8 - 25.0, 150.0, 0.0, 23.8]] and notes


def test_draft_pairs_groove_holder_and_checks_depth(tmp_path):
    """槽宽 4、槽深 10（ø40 上切到 ø20）：配 CDX 10 的 KGMR2525M-4，算通；硬换成 CDX 9 的刀杆 → 报错"""
    lib = {**TG, "tools": [*TG["tools"], *LIB["tools"]]}
    part = {"mode": "turn", "machine": "EX-LATHE", "kienzle": "C45E", "segments": [[24, 30], [40, 60]], "chamfer_mm": 1,
            "grooves": [{"z": -27, "width": 4, "d": 20}]}
    d = CP.draft(part, "P", lib)
    hd = d["setup"]["machine_sim"]["tools"]["3"]["holder"]
    assert hd["vendor_code"] == "KGMR2525M-4" and hd["max_depth_mm"] == 10
    mix = tmp_path / "mix.json"
    mix.write_text(json.dumps(lib, ensure_ascii=False), encoding="utf-8")
    s = d["setup"]
    s["machine_sim"]["tool_library"] = str(mix)
    r = cam.run({**s, "post": "fanuc"})
    assert not [c for pr in r["data"]["programs"] for c in pr["checks"] if c["level"] == "error"]
    from analysis.cam import holders as HD

    s["machine_sim"]["tools"]["3"]["holder"] = HD.as_tool_holder(HBY["KY-KGMR2525M-3"])
    r2 = cam.run({**s, "post": "fanuc"})
    assert any(c["level"] == "error" and "最大槽深 9" in c["text"] and "槽深 10.000" in c["text"]
               for pr in r2["data"]["programs"] for c in pr["checks"])


def test_draft_no_holder_deep_enough_notes_it():
    lib = {**TG, "tools": [*TG["tools"], *LIB["tools"]]}
    part = {"mode": "turn", "machine": "EX-LATHE", "kienzle": "C45E", "segments": [[24, 30], [40, 60]], "chamfer_mm": 1,
            "grooves": [{"z": -27, "width": 4, "d": 14}]}                       # 槽深 13：没有够深的
    d = CP.draft(part, "P", lib)
    assert "holder" not in d["setup"]["machine_sim"]["tools"]["3"]
    assert any("最大槽深都不到 13.000" in n for n in d["notes"])
