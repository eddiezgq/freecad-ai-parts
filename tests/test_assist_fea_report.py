"""有限元报告（ADR-0093 补充十一第 5 步）：真实零件的结果（RJ-201、LS-101、整臂大臂）出报告，报告里每个数字逐个对回文件。

夹具 `tests/fixtures/fea-report/` 是用本仓库真实零件、按第 4 步起草并确认（确认人写“样例（测试用，非真人确认）”）后算出的结果，
原样存（gzip）。测试不联网、不调用真实 LLM；AI 解释用假客户端与录制回放。
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date
from pathlib import Path

import pytest

from assist import fea_report as R

ROOT = Path(__file__).resolve().parents[1]
NAMES = R.fixture_names()


def _docx_text(path: Path) -> str:
    from docx import Document

    d = Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    for s in d.sections:
        parts += [p.text for p in s.header.paragraphs]
    return "\n".join(parts)


def _build(name, tmp_path, **kw):
    s, r = R.load_fixture(name)
    kw.setdefault("number", "QR-FEA-0001")
    kw.setdefault("today", date(2026, 11, 16))
    got = R.build(s, r, tmp_path / f"{name}.docx", base_dir=ROOT, study_path=R.FIXTURES / f"{name}.study.json", **kw)
    return s, r, got


def _trace(text: str, ledger: dict, sources: dict) -> None:
    """出处账里每一笔都对得上文件；把账上的字样从报告里拿掉后，报告里不剩任何数字"""
    for e in ledger["entries"]:
        v = R._ptr_get(sources[e["source"]], e["pointer"])
        if e["kind"] == "number":
            assert e["text"] == R.fmt(v), e
            assert float(e["text"]) == pytest.approx(v, rel=5e-4, abs=1e-12), e
        else:
            assert e["text"] == str(v), e
    rest = text
    for t in sorted({e["text"] for e in ledger["entries"]} | set(ledger["labels"]), key=len, reverse=True):
        rest = rest.replace(t, "")
    left = re.findall(r".{0,15}[0-9].{0,15}", rest)
    assert not left, f"报告里有来路不明的数字：{left[:5]}"


@pytest.mark.parametrize("name", NAMES)
def test_every_number_in_report_traces_to_files(name, tmp_path):
    from analysis.common import materials

    s, r, got = _build(name, tmp_path)
    ledger = json.loads(got["ledger"].read_text(encoding="utf-8"))
    record = json.loads(got["record"].read_text(encoding="utf-8"))
    # 账上的文件指纹现算一遍
    assert ledger["files"]["study"] == R.sha256_file(R.FIXTURES / f"{name}.study.json")
    for i, b in enumerate(s["bodies"]):
        assert ledger["files"][f"step{i}"] == R.sha256_file(ROOT / b["step_path"])
    assert ledger["files"]["result"] == R.fingerprint(r["data"])
    mats = {b["material"]: materials._table()[b["material"]] for b in s["bodies"] if b.get("material")}
    env = {"code": R.code_version(), "gmsh": R.gmsh_version(), "solver": f"{r['solver']['name']} {r['solver']['version']}",
           "module": f"fea {r['module_version']}"}
    sources = {"study": s, "result": r, "materials": {"materials": mats}, "record": record, "files": ledger["files"],
               "env": env, "library": R.library_sources(s), "explain": {}}
    _trace(_docx_text(got["docx"]), ledger, sources)


def test_report_content_rj201(tmp_path):
    """RJ-201：网格收敛不通过（轴肩处疑似奇异点）——安全系数不给并写明原因；审核清单把奇异点处理标“须人工判断”；
    外购件、草稿标记、三栏签字只留栏位"""
    _s, _r, got = _build("rj201-torque", tmp_path)
    t = _docx_text(got["docx"])
    assert R.DRAFT_MARK in t and "安全系数：不给" in t and "可信度核查没有通过" in t
    assert "编制（签字 / 日期）" in t and "程序不代签" in t
    rows = R.checklist(*R.load_fixture("rj201-torque"))
    v = {x["item"]: x["verdict"] for x in rows}
    assert v["网格收敛（最大应力）（s1）"] == "不通过" and v["奇异点处理（s1）"] == "须人工判断"
    assert v["材料"] == "通过" and v["载荷来源"] == "通过" and v["反力平衡（s1）"] == "通过"
    assert v["AI 起草的算例"] == "通过"
    assert "GB/T 699-2015" in t and "CalculiX 2.21" in t


def test_report_content_arm_combination_and_library_source(tmp_path):
    """大臂：按组合算；依据里提到的 CSF-32 外形直径的出处（规格书与页码）进可追溯信息"""
    s, _r, got = _build("arm-upper-combination", tmp_path)
    t = _docx_text(got["docx"])
    assert "按组合" in t and "工况与组合" in t
    lib = R.library_sources(s)
    assert any(x["model"].startswith("CSF-32") and x["doc"] == "src-hd-csg-csf-gear-units" for x in lib), lib
    assert "src-hd-csg-csf-gear-units" in t


def test_report_modal_table(tmp_path):
    _s, r, got = _build("ls101-shaft-modal", tmp_path)
    t = _docx_text(got["docx"])
    m = next(x for x in r["data"]["steps"] if x["type"] == "modal")
    assert "固有频率" in t and R.fmt(m["freqs"][0]["hz"]) in t


def test_revision_history(tmp_path):
    _build("rj201-torque", tmp_path, revision="A", reason="首版")
    _build("rj201-torque", tmp_path, revision="A", reason="首版（重出）")
    _s, _r, got = _build("rj201-torque", tmp_path, revision="B", reason="网格加密后重算")
    rec = json.loads(got["record"].read_text(encoding="utf-8"))
    assert [h["revision"] for h in rec["history"]] == ["A", "B"] and rec["history"][0]["reason"] == "首版（重出）"
    assert rec["number"] == "QR-FEA-0001"
    t = _docx_text(got["docx"])
    assert "网格加密后重算" in t and "首版（重出）" in t


def test_report_refuses_mismatched_or_failed_result(tmp_path):
    s, r = R.load_fixture("rj201-torque")
    s2 = copy.deepcopy(s)
    s2["loads"][0]["value_nm"] = 100.0
    with pytest.raises(ValueError, match="不是用这份算例算的"):
        R.build(s2, r, tmp_path / "x.docx", base_dir=ROOT)
    bad = {**r, "status": "failed", "messages": ["没有算出"]}
    with pytest.raises(ValueError, match="不出报告"):
        R.build(s, bad, tmp_path / "x.docx", base_dir=ROOT)


# ---------------------------------------------------------------- AI 解释

GOOD = {"paragraphs": [
    "在花键段加载后，避开约束面的最大 von Mises 应力为 {{s1.vm_max_mpa}}，出现在轴肩过渡处；最大位移为 {{s1.u_max_mm}}。",
    ("三层网格下该处应力依次为 {{s1.conv2.level0}}、{{s1.conv2.level1}}、{{s1.conv2.level2}}，随加密持续增大，"
     "网格收敛核查不通过，疑似应力奇异点，因此程序没有给出安全系数。")],
    "suggestions": ["核对图纸上轴肩处是否有过渡圆角；如有，在模型中补上后重算。",
                    "若该处确为尖角，评定时避开奇异点，或改用名义应力法并由工程师判断。"]}


def test_explanation_fills_numbers_from_result(tmp_path):
    _s, r = R.load_fixture("rj201-torque")
    e = R.explain(r, R.FakeClient(GOOD))
    assert not e["rejected"] and len(e["paragraphs"]) == 2
    _s, r, got = _build("rj201-torque", tmp_path, explanation=e)
    t = _docx_text(got["docx"])
    st = r["data"]["steps"][0]
    assert f"{R.fmt(st['vm_max_mpa'])} MPa，出现在轴肩过渡处" in t
    assert "{{" not in t and "AI 起草" in t
    ledger = json.loads(got["ledger"].read_text(encoding="utf-8"))
    assert any(x["pointer"] == "/data/steps/0/trust/items/2/values/2" for x in ledger["entries"])


@pytest.mark.parametrize("bad,why", [
    ("最大应力约为 30 MPa。", "数字"),
    ("最大应力约为三十兆帕。", "汉字"),
    ("结构满足强度要求。", "合格判定"),
    ("该零件不合格。", "合格判定"),
    ("网格已收敛，结果可信。", "没有全部通过"),
    ("最大应力为 {{s1.safety_factor}}。", "不在事实清单"),
    ("最大应力为 {s1.vm_max_mpa}。", "数字"),                   # 单花括号：不是占位符，数字照样退回
])
def test_bad_explanation_paragraphs_are_rejected(bad, why):
    _s, r = R.load_fixture("rj201-torque")
    e = R.verify_explanation({"paragraphs": [bad, GOOD["paragraphs"][0]], "suggestions": []}, r)
    assert len(e["paragraphs"]) == 1 and e["rejected"] and why in e["rejected"][0]["reason"], e["rejected"]


def test_no_judgement_phrase_allowed():
    _s, r = R.load_fixture("rj201-torque")
    e = R.verify_explanation({"paragraphs": ["本说明不作合格判定，是否合格由审核人按清单判断。"], "suggestions": []}, r)
    assert not e["rejected"]


def test_request_lists_facts_with_placeholders():
    _s, r = R.load_fixture("ls101-shaft-modal")
    req = R.build_request(r)
    assert "{{m1.f1_hz}}" in req["user"] and "{{s1.vm_max_mpa}}" in req["user"] and "安全系数：不给" in req["user"]
    assert req == R.build_request(r)


def test_recorded_explanations_pass():
    if not R.RECORDINGS_DIR.is_dir() or not any(R.RECORDINGS_DIR.glob("*.json")):
        pytest.skip("还没有真实 LLM 的录制：用 .github/workflows/fea-draft-eval.yml 在云端录制")
    from ingest.llm_extract import RecordedClient

    res = R.evaluate(RecordedClient(R.RECORDINGS_DIR))
    assert res["passed"], json.dumps(res, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 复现、PDF、命令行


def test_same_study_reruns_to_same_fingerprint(tmp_path):
    """同一算例文件重算，结果指纹相同（可复现）"""
    from tests.test_fea_bench import _need_fea, _write

    _need_fea()
    from analysis.fea import run_study

    step = _write(tmp_path / "bar.step", lambda o: o.addBox(0, 0, 0, 100, 10, 10))
    study = {"format": "fea-study/1", "name": "bar", "bodies": [{"id": "b1", "step_path": step, "material": "45-QT"}],
             "supports": [{"type": "fixed", "body": "b1", "faces": [1]}],
             "loads": [{"type": "force", "body": "b1", "faces": [2], "vector_n": [0, 0, -100]}],
             "steps": [{"id": "s1", "type": "static"}], "mesh": {"size_mm": 5}, "checks": {"convergence": False}}
    a, b = run_study(study), run_study(study)
    assert a["status"] == b["status"] == "ok"
    assert R.fingerprint(a["data"]) == R.fingerprint(b["data"])


def test_pdf_via_libreoffice(tmp_path):
    import shutil

    if not (shutil.which("soffice") or shutil.which("libreoffice")):
        pytest.skip("本机没有 LibreOffice")
    _s, _r, got = _build("rj201-torque", tmp_path)
    pdf = R.to_pdf(Path(got["docx"]))
    assert pdf and pdf.stat().st_size > 10_000 and pdf.read_bytes()[:4] == b"%PDF"


def test_cli_report_with_existing_result(tmp_path, monkeypatch, capsys):
    import gzip
    import shutil

    name = "rj201-torque"
    shutil.copy(R.FIXTURES / f"{name}.study.json", tmp_path / "s.json")
    with gzip.open(R.FIXTURES / f"{name}.result.json.gz", "rb") as f:
        (tmp_path / "r.json").write_bytes(f.read())
    monkeypatch.chdir(ROOT)
    from assist.fea import main

    assert main(["report", str(tmp_path / "s.json"), "--result", str(tmp_path / "r.json"), "-o", str(tmp_path / "rep.docx"),
                 "--number", "QR-1", "--revision", "A", "--no-pdf"]) == 0
    assert (tmp_path / "rep.docx").is_file() and (tmp_path / "rep.ledger.json").is_file()
    assert "报告" in capsys.readouterr().out


def test_mcp_tools(tmp_path):
    """MCP：fea_draft 先给特征清单与规则、再核对调用方 AI 的提议；fea_report 出报告，不带解释时返回事实清单与规则"""
    from tests.test_fea_bench import _need_fea

    _need_fea()
    from mcp_server import tools

    stmt = "肩关节空心轴 RJ-201，45 钢调质。Ø70 法兰那一端的端面固定，在 Ø42.75 花键段上加峰值扭矩 92.5 N·m。"
    step = str(ROOT / "examples/apps/out/cobot_joint/RJ-201.step")
    a = tools.fea_draft(stmt, [step])
    assert "F6" in a["context"] and "proposal_schema" in a
    prop = {"bodies": [{"part": 1, "material": "45-QT", "material_quote": "45 钢调质"}],
            "items": [{"type": "fixed", "part": 1, "features": ["F6"], "quote": "Ø70 法兰那一端的端面固定"},
                      {"type": "torque", "part": 1, "features": ["F4"], "quote": "峰值扭矩 92.5 N·m",
                       "magnitude": {"value": 92.5, "unit": "N·m", "quote": "峰值扭矩 92.5 N·m"}}], "questions": []}
    b = tools.fea_draft(stmt, [step], prop)
    assert b["study"]["provenance"]["drafted_by"] == "ai" and not b["rejected"] and not b["errors"]
    with pytest.raises(tools.ToolInputError):
        tools.fea_draft(stmt, [str(tmp_path / "none.step")])
    s, r = R.load_fixture("rj201-torque")
    s["bodies"][0]["step_path"] = step
    r["setup"]["bodies"][0]["step_path"] = step
    out = tools.fea_report(s, str(tmp_path / "rep.docx"), result=r, number="QR-2")
    assert out["status"] == "ok" and Path(out["docx"]).is_file() and "{{s1.vm_max_mpa}}" in out["explain_request"]["facts"]
    out = tools.fea_report(s, str(tmp_path / "rep.docx"), result=r, explanation={"paragraphs": ["结构合格。"], "suggestions": []})
    assert out["explanation_rejected"] and "合格判定" in out["explanation_rejected"][0]["reason"]
