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
    assert len(LIB["tools"]) == 271 and TL.readonly(LIB_PATH)          # 176 片车刀片 + 41 片外螺纹 + 54 片内螺纹刀片
    for t in LIB["tools"]:
        assert t["kind"] in ("turn", "thread_turn") and t["id"] == "TG-" + t["insert"]["iso"]
        if t["kind"] == "thread_turn":
            continue
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


# ---------------------------------------------------------------- 刀杆库（ADR-0112）：综合样本 C 部分外圆刀杆
HOLDERS_PATH = TL.BUILTIN / "tungaloy-holders.json"
HOLDERS = json.loads(HOLDERS_PATH.read_text(encoding="utf-8"))
H_BY = {h["iso5608"]: h for h in HOLDERS["holders"]}


def test_holder_spot_check_and_schema():
    """C020（看样本页图抄的）：PCLNR/L2525M12E 25 25 150 28 25 32 0.8 CN/GN**1204；PCLNR/L3225P16E 代号 P = 170 与表里 LF 150 对不上，不收"""
    import jsonschema

    jsonschema.validate(HOLDERS, json.loads((TL.BUILTIN.parents[2] / "schema" / "cam-holder.schema.json").read_text(encoding="utf-8")))
    for code in ("PCLNR2525M12E", "PCLNL2525M12E"):
        h = H_BY[code]
        assert (h["h_mm"], h["b_mm"], h["l1_mm"], h["head_mm"], h["h1_mm"], h["f_mm"], h["nose_radius_mm"]) == (25, 25, 150, 28, 25, 32, 0.8)
        assert h["insert"] == {"codes": ["CN", "GN"], "size": "1204"} and h["source"]["page"] == "C020"
    assert "PCLNR3225P16E" not in H_BY and len(HOLDERS["holders"]) == 293


def test_holder_rows_parser():
    head = "        H          B              LF              LH                 HF           WF           RE**\n"
    row = "  PCLNR/L2525M12E        25     25     150     28     25     32     0.8     CN/GN**1204...\n"
    assert TG.holder_rows(row) == []                                                # 这一页没有表头：不认
    r = TG.holder_rows(head + row)[0]
    assert (r["base"], r["rest"], r["hands"], r["wf"], r["lh"], r["codes"], r["size"]) == \
        ("PCLN", "2525M12E", ["R", "L"], 32.0, 28.0, ["CN", "GN"], "1204")


def test_pick_holder_for_insert():
    from analysis.cam import holders as HD

    assert HD.insert_key("CNMG120408-TM") == ("CN", "1204") and HD.insert_key("WNMA060416E") == ("WN", "0604")
    assert HD.pick("CNMG120408-TM")["iso5608"][2] == "L"                           # C 形 → L 形 95°
    assert HD.pick("DNMG110404E-TSF")["iso5608"][:3] in ("PDJ", "ADJ", "DDJ")      # D 形 → J 形 93°
    h = HD.pick("CNMG090408E-TM")
    assert h["insert"]["size"] == "0904" and (h["h_mm"], h["b_mm"]) == (25, 25) and h["iso5608"][4] == "R"
    assert HD.pick("XXMG120408") is None
    bx, notes = HD.boxes(HD.as_tool_holder(h))
    assert bx[0][0] == h["head_mm"] and f"离刀尖 {h['head_mm']:g} mm" in notes[0]   # 刀头长按样本 LH


def test_draft_pairs_holders_and_checks_shank():
    part = {"mode": "turn", "machine": "EX-LATHE", "kienzle": "C45E", "segments": [[30, 40], [40, 60], [35, 25], [30, 30]], "chamfer_mm": 1}
    d = CP.draft(part, "P", LIB)
    s = d["setup"]
    assert s["machine_sim"]["tools"]["1"]["holder"]["iso5608"] == "ACLNR2525M0904-A"
    assert any("起草配的" in n for n in d["notes"])
    s["machine_sim"]["tool_library"] = str(LIB_PATH)
    r = cam.run({**s, "post": "fanuc"})
    for prog in r["data"]["programs"]:
        texts = [c["text"] for c in prog["checks"]]
        assert not any("没写刀杆代号" in t for t in texts) and any("刀头外形各家不同" in t for t in texts)


# ---------------------------------------------------------------- 螺纹刀片（综合样本 E 部分 TungThread，ISO 米制 60°）
def test_thread_inserts_spot_check():
    """E018、E019、E067 看样本页图抄的：16ER15ISO IC 9.525 RE 0.19；22ER40ISO-B RE 0.52；27ER60ISO IC 15.875 RE 0.75；
    TungThread 切削速度：P 各材质两档硬度合集 60–200，M 50–130，K 50–150（AH725 50–100、T313V 70–150 等）"""
    for tid, ic, re_, pitch, page in (("TG-16ER15ISO", 9.525, 0.19, 1.5, "E018"), ("TG-22ER40ISO-B", 12.7, 0.52, 4.0, "E019"),
                                      ("TG-27ER60ISO", 15.875, 0.75, 6.0, "E018")):
        t = BY_ID[tid]
        assert (t["kind"], t["pitch_mm"], t["thread_angle_deg"]) == ("thread_turn", pitch, 60)
        assert (t["insert"]["inscribed_circle_mm"], t["insert"]["nose_radius_mm"]) == (ic, re_) and t["source"]["page"].startswith(f"尺寸 {page}")
        c = {x["iso_group"]: x for x in t["cutting"]}
        assert c["P"]["vc_m_min"] == {"min": 60, "max": 200} and c["M"]["vc_m_min"] == {"min": 50, "max": 130}
        assert c["K"]["vc_m_min"] == {"min": 50, "max": 150} and c["P"]["f_mm_rev"] == {"min": pitch, "max": pitch}
    assert not any("EL" in t["id"] or "IL" in t["id"] for t in LIB["tools"] if t["kind"] == "thread_turn")   # 左手不收


def test_thread_row_parser():
    line = "        55°                   16   1.5    R   16ER15ISO          9.525 0.9    0.7   0.19 16IR15ISO    9.525 0.9 0.7 0.11\n"
    assert TG.thread_rows(line) == [{"code": "16ER15ISO", "pitch": 1.5, "ic": 9.525, "re": 0.19}]
    assert TG._pitch_code("175") == 1.75 and TG._pitch_code("60") == 6.0
    with pytest.raises(TG.TungaloyError, match="螺距栏"):
        TG.thread_rows(" 16   2    R   16ER15ISO   9.525 0.9 0.7 0.19\n")


def test_draft_threaded_shaft_with_tungaloy():
    """M24×1.5 外螺纹：螺纹刀按螺距从泰珂洛库里挑，算通、出程序"""
    part = {"mode": "turn", "machine": "EX-LATHE", "kienzle": "C45E", "segments": [[24, 30], [40, 60]], "chamfer_mm": 1,
            "threads": [{"z_start": 0, "z_end": -26, "d": 24, "pitch": 1.5}]}
    d = CP.draft(part, "P", LIB)
    card = {r["id"]: r for r in d["card"]}
    assert BY_ID[card["thread1"]["tool"]]["pitch_mm"] == 1.5 and card["thread1"]["status"] == "pass"
    s = d["setup"]
    s["machine_sim"]["tool_library"] = str(LIB_PATH)
    r = cam.run({**s, "post": "fanuc"})
    assert all(p["release"] is not None for p in r["data"]["programs"])


# ---------------------------------------------------------------- 内孔刀（ADR-0113）：内螺纹刀片、内外挑刀、最小孔径
def test_internal_thread_inserts_spot_check():
    """E017、E018 图抄的：06IR10ISO IC 4 RE 0.05；16IR15ISO IC 9.525 RE 0.11；都标 internal"""
    for tid, ic, re_ in (("TG-06IR10ISO", 4.0, 0.05), ("TG-16IR15ISO", 9.525, 0.11)):
        t = BY_ID[tid]
        assert t["internal"] is True and (t["insert"]["inscribed_circle_mm"], t["insert"]["nose_radius_mm"]) == (ic, re_)
    assert sum(1 for t in LIB["tools"] if t.get("internal")) == 54


def test_operations_pick_by_internal_flag():
    part = {"mode": "turn", "machine": "EX-LATHE", "segments": [[40, 30]], "bore": {"segments": [[26, 20]], "drill_d": 20},
            "threads": [{"z_start": 0, "z_end": -10, "d": 30, "pitch": 1.5, "internal": True},
                        {"z_start": 0, "z_end": -10, "d": 40, "pitch": 1.5}]}
    ops = {o["id"]: o for o in CP.operations(part, LIB)}
    assert ops["thread1"]["cands"] and all(t.get("internal") for t in ops["thread1"]["cands"])
    assert ops["thread2"]["cands"] and not any(t.get("internal") for t in ops["thread2"]["cands"])
    assert not any(t.get("internal") for o in ("rough", "finish") for t in ops[o]["cands"])
    # 没分内外的老刀具库（示例库）：内螺纹照旧按螺距挑
    old = CP.operations(part, TL.load())
    assert next(o for o in old if o["id"] == "thread1")["cands"]


def test_inner_tool_checks(tmp_path):
    """内螺纹用了外螺纹刀片、外圆用了内螺纹刀片 → 错误；内孔刀最小孔径 Ø30 进不了 M24×1.5 的小径 Ø22.376 → 错误"""
    import analysis.cam as C

    sc = {"threads": [{"d": 24, "pitch": 1.5, "internal": True}], "bore": None}
    st = {"machine_sim": {"tool_library": str(LIB_PATH), "tools": {"7": {"tool": "TG-16ER15ISO"}, "4": {"tool": "TG-16IR15ISO"}}}}
    texts = [c["text"] for c in C.inner_tool_checks(st, sc)]
    assert any("是外圆刀" in t for t in texts) and any("是内孔刀，不能车外圆" in t for t in texts)
    lib = {"format": "cam-tool/1", "name": "测试", "tools": [{**BY_ID["TG-16IR15ISO"], "min_bore_mm": 30.0}]}
    f = tmp_path / "lib.json"
    f.write_text(json.dumps(lib, ensure_ascii=False), encoding="utf-8")
    st2 = {"machine_sim": {"tool_library": str(f), "tools": {"7": {"tool": "TG-16IR15ISO"}}}}
    texts = [c["text"] for c in C.inner_tool_checks(st2, sc)]
    assert any("最小能进 Ø30" in t and "22.376" in t for t in texts)
