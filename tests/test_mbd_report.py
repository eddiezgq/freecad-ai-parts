"""多体动力学计算报告（ADR-0097 D8b）：报告里每个数字都对得回结果；AI 段落带数字、判合格或乱用占位符的退回。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from assist import mbd_report as R

pytest.importorskip("scipy")
FIX = Path(__file__).parent / "fixtures" / "mbd-model" / "valid"


def _run(name):
    from analysis.mbd.dae.run import run_model

    doc = json.loads((FIX / name).read_text(encoding="utf-8"))
    data, _ = run_model(doc.get("instance", doc), FIX)
    return json.loads(json.dumps(data))           # 和写到文件再读回来一样


class FakeClient:
    def __init__(self, paragraphs):
        self.paragraphs = paragraphs
        self.requests = []

    def complete(self, req):
        self.requests.append(req)
        return {"id": "fake-1", "model": "fake", "tool_input": {"paragraphs": self.paragraphs}}


def _trace(md: str, ledger: dict, data: dict):
    for e in ledger["numbers"]:
        v = R.apply_op(data, e["ptr"], e["op"])
        assert e["text"] == R.fmt(v)
        assert float(e["text"]) == pytest.approx(v, rel=5e-4, abs=1e-12)
    rest = md
    for t in sorted({e["text"] for e in ledger["numbers"]} | set(ledger["labels"]), key=len, reverse=True):
        rest = rest.replace(t, "")
    rest = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", rest)          # 图片文件名
    left = re.findall(r".{0,12}\d.{0,12}", rest)
    assert not left, f"报告里有来路不明的数字：{left[:5]}"


@pytest.mark.parametrize("name", ["slider_crank_all_d1.json", "d4_linear_plant.json", "d7_pid_turntable.json"])
def test_every_number_traces_back(name, tmp_path):
    data = _run(name)
    got = R.build(data, tmp_path, title="样例")
    md = got["markdown"].read_text(encoding="utf-8")
    ledger = json.loads(got["ledger"].read_text(encoding="utf-8"))
    assert R.DRAFT_MARK in md
    assert ledger["numbers"]
    _trace(md, ledger, data)


def test_ai_paragraphs_checked(tmp_path):
    data = _run("d4_linear_plant.json")
    F = R.facts(data)
    assert "mode1_hz" in F
    good = "第一阶固有频率为 {{mode1_hz}}，阻尼比 {{mode1_zeta}}。"
    bad = ["频率约 12 Hz。", "结构合格。", "见 {{nonexistent}}。"]
    client = FakeClient([good, *bad])
    got = R.build(data, tmp_path, client=client)
    md = got["markdown"].read_text(encoding="utf-8")
    ledger = json.loads(got["ledger"].read_text(encoding="utf-8"))
    assert "{{" not in md and "AI 起草" in md
    assert len(ledger["explanation"]["rejected"]) == 3
    assert "{{mode1_hz}}" in client.requests[0]["user"]
    _trace(md, ledger, data)


def test_no_ai_no_explanation(tmp_path):
    got = R.build(_run("pendulum.json"), tmp_path)
    assert got["explanation"]["by"] == "没有用 AI"
    assert "AI 起草" not in got["markdown"].read_text(encoding="utf-8")


def test_nonlinear_beam_facts_trace_back(tmp_path):
    """ADR-0101 F3：大变形梁的截面内力、应力进报告，数字对得回结果"""
    from tests.test_mbd_nlbeam import cantilever

    data, _ = __import__("analysis.mbd.dae.run", fromlist=["run_model"]).run_model(
        cantilever([{"id": "p", "type": "force", "body": "rod", "point_mm": [1000.0, 0, 0], "fy_n": -100.0}]))
    data = json.loads(json.dumps(data))
    F = R.facts(data)
    assert {"beam_rod_stress", "beam_rod_axial", "beam_rod_mz"} <= set(F)
    got = R.build(data, tmp_path)
    md = got["markdown"].read_text(encoding="utf-8")
    ledger = json.loads(got["ledger"].read_text(encoding="utf-8"))
    assert "大变形梁 rod 最大正应力" in md
    _trace(md, ledger, data)


# ---------------------------------------------------------------- Word 正式报告（ADR-0102 第 1 步）
def _docx_text(path):
    from docx import Document

    d = Document(str(path))
    parts = [p_.text for p_ in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    for s in d.sections:
        parts += [p_.text for p_ in s.header.paragraphs]
    return "\n".join(parts)


def _trace_docx(text, ledger, sources):
    from assist.fea_report import _ptr_get

    for e in ledger["entries"]:
        if e["kind"] == "op":
            v = R.apply_op(sources[e["source"]], e["pointer"], e["op"])
            assert e["text"] == R.fmt_num(v), e
        else:
            v = _ptr_get(sources[e["source"]], e["pointer"])
            if e["kind"] == "number":
                assert float(e["text"]) == pytest.approx(v, rel=5e-4, abs=1e-12), e
            elif "original" not in e:
                assert e["text"] == str(v), e
    rest = text
    for t in sorted({e["text"] for e in ledger["entries"]} | set(ledger["labels"]), key=len, reverse=True):
        rest = rest.replace(t, "")
    left = re.findall(r".{0,15}[0-9].{0,15}", rest)
    assert not left, f"报告里有来路不明的数字：{left[:5]}"


def _model(name):
    doc = json.loads((FIX / name).read_text(encoding="utf-8"))
    return doc.get("instance", doc)


@pytest.mark.parametrize("name", ["slider_crank_all_d1.json", "d4_linear_plant.json", "d7_pid_turntable.json",
                                  "d6_flex_pendulum.json"])
def test_docx_every_number_traces_back(name, tmp_path):
    pytest.importorskip("docx")
    from datetime import date

    model = _model(name)
    data = _run(name)
    got = R.build_docx(model, data, tmp_path / "r.docx", number="QR-MBD-0001", today=date(2026, 11, 18))
    text = _docx_text(got["docx"])
    ledger = json.loads(got["ledger"].read_text(encoding="utf-8"))
    record = json.loads(got["record"].read_text(encoding="utf-8"))
    assert "多体动力学计算报告" in text and R.DRAFT_MARK in text and "审核清单" in text
    from assist.fea_report import code_version, fingerprint

    sources = {"model": model, "result": data, "record": record,
               "files": {"model": fingerprint(model), "result": fingerprint(R._strip_timing(data))},
               "env": {"code": code_version(), "integrator": str(data["solver"].get("integrator", "—")), "company": ""},
               "explain": {}}
    _trace_docx(text, ledger, sources)


def test_docx_explanation_and_revisions(tmp_path):
    pytest.importorskip("docx")
    from datetime import date

    model, data = _model("d4_linear_plant.json"), _run("d4_linear_plant.json")
    F = R.facts(data)
    ex = R.explain(data, F, FakeClient(["一阶固有频率 {{mode1_hz}}。", "约 5 Hz。"]))
    got = R.build_docx(model, data, tmp_path / "r.docx", explanation=ex, today=date(2026, 11, 18))
    text = _docx_text(got["docx"])
    assert "AI 起草" in text and "{{" not in text and "退回不用的 AI 段落" in text
    R.build_docx(model, data, tmp_path / "r.docx", revision="A", reason="审核意见修改", today=date(2026, 11, 19))
    rec = json.loads(got["record"].read_text(encoding="utf-8"))
    assert [h["revision"] for h in rec["history"]] == ["草稿", "A"]
    assert rec["history"][0]["result_fingerprint"] == rec["history"][1]["result_fingerprint"]   # 同一模型同一结果
    bad = dict(data, model="别的模型")
    with pytest.raises(ValueError, match="模型名不一致"):
        R.build_docx(model, bad, tmp_path / "x.docx")


@pytest.mark.parametrize("name", ["slider_crank_all_d1.json", "d4_linear_plant.json", "d7_pid_turntable.json",
                                  "d6_flex_pendulum.json"])
def test_docx_english_same_numbers_and_only_user_text_in_chinese(name, tmp_path):
    """ADR-0102 第 2 步：同一计算出中英两份报告，数字、出处、结果指纹完全相同；英文报告里剩下的中文只能是用户写的（模型名、构件和运动副名）"""
    pytest.importorskip("docx")
    from datetime import date

    from assist import i18n

    model, data = _model(name), _run(name)
    zh = R.build_docx(model, data, tmp_path / "zh.docx", number="QR-MBD-0001", today=date(2026, 11, 18))
    en = R.build_docx(model, data, tmp_path / "en.docx", number="QR-MBD-0001", today=date(2026, 11, 18), lang="en")
    lz, le = (json.loads(x["ledger"].read_text(encoding="utf-8")) for x in (zh, en))
    nums = [[(e["source"], e["pointer"], e["text"]) for e in x["entries"] if e["kind"] in ("number", "op")] for x in (lz, le)]
    assert nums[0] == nums[1] and lz["files"] == le["files"]
    text = _docx_text(en["docx"])
    user = {model["name"]} | {b["id"] for b in model["bodies"]} | {j["id"] for j in model.get("joints", [])} \
        | {j[k] for j in model.get("joints", []) for k in ("body_i", "body_j")} | set(data.get("redundant_constraints") or [])
    rest = text
    for u in sorted(user, key=len, reverse=True):
        rest = rest.replace(u, "")
    left = [ln for ln in rest.splitlines() if i18n.has_cjk(ln)]
    assert not left, f"英文报告里还有中文：{left[:5]}"
