"""问渠CAM 窗口背后的逻辑（ADR-0104 产品化第 2 步）：文字输入、夹具模板、起草、计算、保存。不需要 FreeCAD。"""

from __future__ import annotations

import pytest

from assist import cam_edition, fea_edition
from freecad_addon.core import cam_study as S
from licensing import runtime


def _part(**kw):
    return S.turn_part(item="带螺纹的阶梯轴", segments="30x40, 40x60, 35x25, 24x30", chamfer=1, kienzle="C45E",
                       grooves="-27, 3, 20", threads="0, -26, 24, 1.5", bore="16x20, 12x15", **kw)


def test_text_input():
    p = _part()
    assert p["segments"] == [[30, 40], [40, 60], [35, 25], [24, 30]]
    assert p["grooves"] == [{"z": -27.0, "width": 3.0, "d": 20.0}] and p["threads"][0]["pitch"] == 1.5
    assert p["bore"] == {"segments": [[16.0, 20.0], [12.0, 15.0]]}
    assert S.parse_segments("30×40；40*60\n35x25") == [[30, 40], [40, 60], [35, 25]]
    with pytest.raises(S.StudyError, match="直径x长度"):
        S.parse_segments("30x40, 40")
    with pytest.raises(S.StudyError, match="槽每行要 3 个数"):
        S.turn_part(item="x", segments="30x40", grooves="-10, 3")
    with pytest.raises(S.StudyError, match="先选工件材料"):
        S.iso_group(None)
    assert S.iso_group("C45E") == "P"


def test_draft_run_save_turning(tmp_path):
    p = _part()
    d = S.draft(p)
    d["setup"]["machine_sim"]["fixtures"] = S.lathe_jaws(p, jaw_len=15, jaw_d=80)
    d["setup"]["post"] = "fanuc"
    r = S.run(d["setup"])
    lines = S.summary(r)
    assert len(lines) == 3 and "整机仿真通过（有未知项）" in lines[1] and "正式程序已出" in lines[1]
    cs = S.checks(r)
    assert cs and [c["level"] for c in cs] == sorted((c["level"] for c in cs), key=S.LEVEL_ORDER.get)
    files = S.save(r, tmp_path, draft_doc=d, pdf=False)
    names = [f.name for f in files]
    assert "O1001_fanuc.nc" in names and "O1002_fanuc.nc" in names and "工艺卡与程序单.docx" in names
    assert "FIRST PART" in (tmp_path / "O1001_fanuc.nc").read_text(encoding="utf-8")


def test_jaws_too_long_blocks_program(tmp_path):
    p = _part()
    d = S.draft(p)
    d["setup"]["machine_sim"]["fixtures"] = S.lathe_jaws(p, jaw_len=60, jaw_d=80)     # 夹到第二次装夹要车的地方
    d["setup"]["post"] = "fanuc"
    r = S.run(d["setup"])
    assert any("卡爪" in c["text"] for c in S.checks(r) if c["level"] == "error")
    with pytest.raises(S.StudyError, match="没有可以保存的正式程序"):
        S.save({"data": {"programs": [p for p in r["data"]["programs"] if p.get("release") is None]}}, tmp_path)


def test_vise_template():
    j = S.vise_jaws({"box": [0, 0, 100, 60], "height": 40}, grip=10)
    assert j[0]["box_mm"][4] == 0 and j[1]["box_mm"][1] == 60 and j[0]["box_mm"][5] == pytest.approx(-30)


def test_free_tier_gates(monkeypatch, tmp_path):
    monkeypatch.setenv("FAP_EDITION", "cam")
    monkeypatch.setenv("FAP_LICENSE_FILE", str(tmp_path / "none.json"))
    monkeypatch.delenv("FAP_LICENSE_TEST_KEY", raising=False)
    monkeypatch.setattr(fea_edition, "EDITION_FILE", tmp_path / "no.json")
    monkeypatch.setattr(runtime, "EDITION_FILE", tmp_path / "no.json")
    p = _part()
    d = S.draft(p)                                                   # 规则起草：免费版能用
    with pytest.raises(cam_edition.NeedsPro, match="AI 起草工艺"):
        S.draft(p, client=object())
    with pytest.raises(cam_edition.NeedsPro, match="FANUC 以外"):
        S.run({**d["setup"], "post": "siemens"})
    r = S.run({**d["setup"], "post": "fanuc"})
    files = S.save(r, tmp_path, draft_doc=None)                      # 程序免费；工艺卡是专业版
    assert files
    with pytest.raises(cam_edition.NeedsPro, match="工艺卡"):
        S.save(r, tmp_path, draft_doc=d, pdf=False)
