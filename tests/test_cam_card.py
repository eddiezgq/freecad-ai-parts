"""问渠CAM C1 第 6 步：工艺卡与程序单（Word，中英；每个数记进出处账）。"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("docx")

from analysis import cam  # noqa: E402
from assist import cam_card as CC  # noqa: E402
from assist import cam_process as CP  # noqa: E402
from assist.fea_report import _ptr_get  # noqa: E402

TURN = {"mode": "turn", "machine": "EX-LATHE", "item": "带螺纹的阶梯轴（示例）", "segments": [[30, 40], [40, 60], [35, 25], [24, 30]],
        "chamfer_mm": 1, "kienzle": "C45E", "grooves": [{"z": -27, "width": 3, "d": 20}],
        "threads": [{"z_start": 0, "z_end": -26, "d": 24, "pitch": 1.5}], "bore": {"segments": [[16, 20], [12, 15]]}}


def _text(path):
    from docx import Document

    d = Document(str(path))
    out = [p.text for p in d.paragraphs]
    for t in d.tables:
        for r in t.rows:
            out += [c.text for c in r.cells]
    return "\n".join(out)


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_card_numbers_all_come_from_sources(tmp_path, lang):
    d = CP.draft(TURN, "P")
    r = cam.run({**d["setup"], "post": "fanuc"})
    o = CC.build_docx(d, r, tmp_path / f"card_{lang}.docx", lang=lang, number="GY-001")
    text = _text(o["docx"])
    fp = r["data"]["programs"][0]["machine_sim"]["fingerprint"]
    assert fp in text and "GY-001" in text and o["ops"] == 6 and o["programs"] == 2
    if lang == "zh":
        assert "首件须空运行、单段试切确认" in text and "未经实机验证" in text and "粗车外圆" in text
    else:
        assert "First part: dry run and single block" in text and "NOT verified" in text and "Rough turning" in text
        assert "Threading M24x1.5" in text
    led = json.loads(o["ledger"].read_text(encoding="utf-8"))
    src = {"draft": d, "result": r["data"]}
    n = 0
    for e in led["numbers"]:
        if e["source"] in src:
            v = _ptr_get(src[e["source"]], e["pointer"])
            from assist.fea_report import fmt
            assert fmt(v) == e["text"], e
            n += 1
        assert e["text"] in text
    assert n >= 6 * 2 + 2 * 4                         # 每道工序 vc 和进给，每个程序 4 个时间
    # 转速 S = 1000·vc/(π·d)：粗车按最大直径 40
    rough = d["card"][0]["params"]["vc"]
    assert str(round(1000 * rough / (3.141592653589793 * 40))) in text


def test_card_refuses_failed_result(tmp_path):
    d = CP.draft(TURN, "P")
    with pytest.raises(ValueError, match="没有成功"):
        CC.build_docx(d, {"status": "failed"}, tmp_path / "x.docx")
