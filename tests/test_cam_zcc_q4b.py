"""问渠CAM Q4b 株洲钻石样本刀具库（ADR-0106 Q4b）：数据与样本页一致（抽查值照样本页抄录，与程序抽取独立）；
来源登记、条款核实；参数表没列的直径不插值；刀具库能直接用来起草、计算。"""

from __future__ import annotations

import math
import re

import pytest
import yaml

from analysis import cam
from analysis.cam import tools as TL
from assist import cam_process as CP
from ingest import cam_zcc
from tests.verification import record_verdict

LIB_PATH = TL.BUILTIN / "zcc-ct.json"
LIB = TL.load(LIB_PATH)

# 照样本页抄录（人看页面图读的数，不经程序）：型号 → (D, d, H, L, Z, 样本页, {材料组: (n, F)}, 参数页, ap×D)
SPOT = {
    "GM-2E-D3.0": (3.0, 6, 8, 50, 2, "B355", {"K": (14000, 455), "P": (14000, 455), "M": (7500, 100)}, "B500", 1.0),
    "GM-2E-D10.0": (10.0, 10, 25, 75, 2, "B355", {"K": (4200, 485), "P": (4200, 485), "M": (2200, 115)}, "B500", 1.0),
    "GM-3E-D6.0": (6.0, 6, 16, 50, 3, "B363", {"K": (7000, 650), "P": (7000, 650), "M": (3700, 150)}, "B504", 1.0),
    "GM-4E-D10.0": (10.0, 10, 25, 75, 4, "B373", {"K": (4200, 730), "P": (4200, 730), "M": (2200, 135)}, "B508", 1.5),
    "GM-4E-D20.0": (20.0, 20, 45, 100, 4, "B373", {"K": (2050, 670), "P": (2050, 670), "M": (1100, 105)}, "B508", 1.5),
    "GM-4E-D10.0-G": (10.0, 10, 25, 75, 4, "B366", {"K": (4200, 660), "P": (4200, 660), "M": (2200, 120)}, "B505", 1.5),
}
# 球头：型号 → (D, R, d, H, L, Z, 样本页, {材料组: (n, F)}, 参数页)；最大切深 ap = 0.1R、ae = 0.2R
BALL = {
    "GM-2B-R1.0": (2.0, 1.0, 6, 4, 50, 2, "B382", {"K": (24000, 900), "P": (24000, 900), "M": (11150, 230)}, "B515"),
    "GM-2B-R5.0": (10.0, 5.0, 10, 20, 75, 2, "B382", {"K": (4800, 1200), "P": (4800, 1200), "M": (2200, 430)}, "B515"),
    "GM-4B-R4.0": (8.0, 4.0, 8, 16, 60, 4, "B385", {"K": (6000, 2340), "P": (6000, 2340), "M": (2750, 820)}, "B516"),
}


def test_library_valid_and_sourced():
    assert not TL.validate(LIB) and not TL.engineering_errors(LIB)
    ids = [t["id"] for t in LIB["tools"]]
    assert len(ids) == len(set(ids)) == 171
    src = {s["id"]: s for s in yaml.safe_load((TL.ROOT / "data" / "sources.yaml").read_text(encoding="utf-8"))["sources"]}
    z = src["zcc-ct"]
    assert z["terms_checked"] and z["license"] == "params-only" and len(z["documents"]) == 7
    assert all(t["source"]["kind"] == "catalog" and t["source"]["ref"] == "zcc-ct" and re.match(r"尺寸 [BC]\d{3}", t["source"]["page"])
               for t in LIB["tools"])
    assert TL.readonly(LIB_PATH) and any(lib["path"] == str(LIB_PATH) for lib in TL.libraries())


@pytest.mark.parametrize("code", list(SPOT))
def test_spot_values_match_catalogue(code):
    D, d, H, L, Z, page, params, ppage, ap = SPOT[code]
    t = TL.get(LIB, code)
    assert (t["diameter_mm"], t["shank_diameter_mm"], t["flute_length_mm"], t["overall_length_mm"], t["flutes"]) == (D, d, H, L, Z)
    assert page in t["source"]["page"] and ppage in t["source"]["page"]
    rows = {c["iso_group"]: c for c in t["cutting"]}
    assert set(rows) == {"K", "P", "M"}
    for g, (n, F) in params.items():
        assert rows[g]["vc_m_min"]["min"] == rows[g]["vc_m_min"]["max"] == pytest.approx(math.pi * D * n / 1000, abs=0.05)
        assert rows[g]["fz_mm"]["min"] == pytest.approx(F / (n * Z), abs=5e-5)
        assert rows[g]["ap_max_mm"] == pytest.approx(ap * D) and rows[g]["ae_max_mm"] == pytest.approx(0.1 * D)
    record_verdict((f"株洲钻石 {code} 与样本 {page}、{ppage} 一致", f"ZCC {code} matches catalogue {page}, {ppage}"), "pass", "pass")


@pytest.mark.parametrize("code", list(BALL))
def test_ball_values_match_catalogue(code):
    D, R, d, H, L, Z, page, params, ppage = BALL[code]
    t = TL.get(LIB, code)
    assert t["kind"] == "ball_endmill"
    assert (t["diameter_mm"], t["shank_diameter_mm"], t["flute_length_mm"], t["overall_length_mm"], t["flutes"]) == (D, d, H, L, Z)
    assert page in t["source"]["page"] and ppage in t["source"]["page"]
    rows = {c["iso_group"]: c for c in t["cutting"]}
    for g, (n, F) in params.items():
        assert rows[g]["vc_m_min"]["max"] == pytest.approx(math.pi * D * n / 1000, abs=0.05)
        assert rows[g]["fz_mm"]["max"] == pytest.approx(F / (n * Z), abs=5e-5)
        assert rows[g]["ap_max_mm"] == pytest.approx(0.1 * R) and rows[g]["ae_max_mm"] == pytest.approx(0.2 * R)


# 丝锥、螺纹铣刀（样本 C167、C175 抄录）：型号 → (公称直径, 螺距, 柄径, 全长, 刃长, 齿数)
TAPS = {"4201C-M10x1.5-6H": (10.0, 1.5, 10.0, 100.0, 24.0, 4), "4201C-M12x1.75-6H": (12.0, 1.75, 9.0, 110.0, 29.0, 4)}
TMILLS = {"4111-M12x1.75": (9.75, 1.75, 12.0, 75.0, 24.0, 4), "4111-M8x1.25": (6.45, 1.25, 8.0, 60.0, 16.0, 4)}


def test_taps_and_thread_mills():
    for code, (d, p, d2, l1, l2, z) in TAPS.items():
        t = TL.get(LIB, code)
        assert (t["kind"], t["diameter_mm"], t["pitch_mm"], t["shank_diameter_mm"], t["overall_length_mm"], t["flute_length_mm"],
                t["flutes"]) == ("tap", d, p, d2, l1, l2, z)
        k = t["cutting"][0]
        assert k["iso_group"] == "K" and (k["vc_m_min"]["min"], k["vc_m_min"]["max"]) == (10.0, 20.0)
        assert k["f_mm_rev"]["min"] == k["f_mm_rev"]["max"] == p
        assert "C176" in t["source"]["page"]
    for code, (d1, p, d2, l1, l2, z) in TMILLS.items():
        t = TL.get(LIB, code)
        assert (t["kind"], t["diameter_mm"], t["pitch_mm"], t["shank_diameter_mm"], t["overall_length_mm"], t["flute_length_mm"],
                t["flutes"]) == ("thread_mill", d1, p, d2, l1, l2, z)
        assert "cutting" not in t                       # 牌号有没有涂层样本没写，切削参数不收
    straight = TL.get(LIB, "4202C-M10x1.5-6H")["cutting"][0]["vc_m_min"]
    assert (straight["min"], straight["max"]) == (6.0, 16.0)


def test_no_interpolation_for_missing_diameters():
    """参数表只到 1、2、3、4、5、6、8、10、12、14、16、18、20：4.5、5.5、7、9、11 不写切削参数（不插值）"""
    for code in ("GM-2E-D4.5", "GM-2E-D5.5", "GM-2E-D7.0", "GM-2E-D9.0", "GM-2E-D11.0"):
        t = TL.get(LIB, code)
        assert "cutting" not in t and "切削参数" not in t["source"]["page"]
        assert TL.verdict(TL.check_cutting(t, "P", vc=100.0)) == "unknown"


def test_parser_on_text():
    """抽取规则（不需要 PDF）：尺寸行、参数行（含直径单独一行的情况）"""
    dims = ("     GM-4E-D10.0                       10.0                    10              25                75"
            "                 4                     Picture 2                 ●\n"
            "     GM-4E-D10.0S                      10.0                     8              25                75"
            "                 4                     Picture 2                 ●\n"
            "     GM-4E-D12.0                       12.0                    12              30                75"
            "                 4                     Picture 2                 ○\n")
    rows = cam_zcc.dims_rows(dims, "GM-4E")
    assert [(r["code"], r["stock"]) for r in rows] == [("GM-4E-D10.0", True), ("GM-4E-D12.0", False)]
    par = ("  10   4200   730   4200   730   3800   670   3200   560   2200   135   2500   435\n"
           "  20\n"
           "       2050   670   2050   670   1900   620   1600   515   1100   105   1250   405\n")
    p = cam_zcc.param_rows(par)
    assert p[10.0][1] == (4200, 730) and p[20.0][4] == (1100, 105)


def test_draft_and_run_with_zcc_library():
    """用株洲钻石刀具库起草一个型腔、计算通过；参数等于样本推荐值"""
    part = {"mode": "mill", "machine": "EX-VMC", "kienzle": "C45E", "stock": {"box": [0, 0, 100, 60], "height": 40},
            "features": [{"type": "pocket", "rect": [20, 15, 80, 45], "corner_r": 6, "depth": 8}]}
    d = CP.draft(part, "P", LIB)
    row = d["card"][0]
    t = TL.get(LIB, row["tool"])
    assert t["diameter_mm"] <= 12 and row["status"] == "pass"
    assert TL.verdict(TL.check_cutting(t, "P", vc=row["params"]["vc"], fz=row["params"]["fz"], ap=row["params"]["ap"])) == "pass"
    s = d["setup"]
    s["machine_sim"]["tool_library"] = str(LIB_PATH)
    r = cam.run({**s, "post": "fanuc"})
    assert r["status"] == "ok" and r["data"]["programs"][0]["release"] is not None
