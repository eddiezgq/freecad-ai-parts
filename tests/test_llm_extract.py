"""LLM 结构化抽取（issue #29，ADR-0021）的测试。

全部使用模拟响应或录制回放，不联网、不调用真实 LLM。模拟响应只检验代码核对流程，不代表准确率。
"""

from __future__ import annotations

import copy
import json
import os
import sys
import types

import pytest

from ingest import llm_extract as lx
from ingest.llm_extract import (
    DEFAULT_MODEL,
    PROMPT_VERSION,
    RecordedClient,
    RecordingMissing,
    build_request,
    extract_document,
    request_key,
    targets,
    write_recording,
)
from ingest.llm_simulate import SimulatedClient, proposals_from_answer, simulated_response
from ingest.pdf_extract import extract
from ingest.synthetic import FontMissing, datasheets, find_font
from ingest.units import to_standard
from kb.validation import errors

pytest.importorskip("pdfplumber")
DOC_ID = "src-test-fixture"


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    pytest.importorskip("reportlab")
    try:
        find_font("latin")
        find_font("cjk")
    except FontMissing:
        if os.environ.get("CI"):
            raise
        pytest.skip("本地未安装生成 PDF 所需的字体；CI 中必须运行")
    d = tmp_path_factory.mktemp("sheets")
    return {s.id: (s.answer, extract(s.render(d / f"{s.id}.pdf"))) for s in datasheets(0) + datasheets(1)}


def _sheet(rendered, category: str, lang: str | None = None):
    for answer, doc in rendered.values():
        if answer["category"] == category and (lang is None or answer["lang"] == lang):
            return answer, doc
    raise LookupError(category)


def _run(answer, doc, proposals=None, **kw):
    client = SimulatedClient(simulated_response(answer, proposals, **kw))
    return extract_document(doc, answer["category"], DOC_ID, client)


def _proposal(answer, target):
    return next(p for p in proposals_from_answer(answer) if p["target"] == target)


# ---------------------------------------------------------------- 字段清单


@pytest.mark.parametrize("category", ["servo_motor", "reducer", "drive", "bearing", "adapter"])
def test_targets_cover_category_schema(category):
    tmap = targets(category)
    cat = json.loads((lx.SCHEMA_DIR / "categories" / f"{category}.schema.json").read_text(encoding="utf-8"))
    for name in cat["properties"]["params"]["properties"]:
        assert f"params/{name}" in tmap
    for key in cat.get("x-key-fields", []):
        assert tmap[f"params/{key}"][0].key
    assert {t for t in tmap if t.startswith("dims/")} == {f"dims/{d}" for d in lx.CATEGORY_DIMS[category]}
    pattern = json.loads((lx.SCHEMA_DIR / "extraction.schema.json").read_text(encoding="utf-8"))
    pattern = pattern["$defs"]["target"]["pattern"]
    for t, _ in tmap.values():
        assert lx.re.fullmatch(pattern, t.target), t.target


def test_synthetic_paths_are_targets():
    """模拟规格书答案中的 params/ports/dims 路径都是合法的抽取目标。"""
    for s in datasheets(0):
        tmap = targets(s.answer["category"])
        for e in s.answer["fields"]:
            for path in e["paths"]:
                if not path.startswith("envelope/"):
                    assert path in tmap, path


def test_request_key_is_stable_and_versioned(rendered):
    _, doc = _sheet(rendered, "reducer")
    a = build_request(doc, "reducer")
    b = build_request(doc, "reducer")
    assert request_key(a) == request_key(b)
    assert request_key(build_request(doc, "reducer", prompt_version="extract/99")) != request_key(a)
    assert request_key(build_request(doc, "reducer", model="other")) != request_key(a)
    assert a["model"] == DEFAULT_MODEL and a["prompt_version"] == PROMPT_VERSION
    assert "params/ratio" in a["user"] and "=== 第 1 页 / page 1 ===" in a["user"]
    with pytest.raises(ValueError):
        build_request(doc, "fastener")


# ---------------------------------------------------------------- 全部读对时


def test_perfect_simulated_extraction(rendered):
    """全部读对的模拟响应：每个可抽取目标都被接受，换算后等于答案，结果符合 schema。"""
    for answer, doc in rendered.values():
        result = _run(answer, doc)
        assert errors("extraction.schema.json", result) == []
        assert result["rejected"] == [], result["rejected"][:3]
        assert result["extractor"]["simulated"] is True
        assert result["vendor"] == answer["component"]["vendor"]
        assert result["model"] == answer["component"]["model"]
        got = {i["target"]: i for i in result["items"]}
        tmap = targets(answer["category"])
        for e in answer["fields"]:
            for path in (p for p in e["paths"] if p in tmap):
                item = got[path]
                assert item["value"]["source"] == {"doc": DOC_ID, "page": e["page"]}
                assert item["value"]["method"] == "extracted" and item["value"]["reviewed"] is False
                assert item["value"].get("condition") == e.get("condition")
                for k, want in e["expected"].items():
                    have = item["value"][k]
                    if isinstance(want, float) or isinstance(have, float):
                        assert have == pytest.approx(want, rel=1e-3), (path, k)
                    else:
                        assert have == want, (path, k)
        assert len(got) == len(result["items"])
        key_targets = {t.target for t, _ in tmap.values() if t.key}
        assert set(result["missing_key_fields"]) == key_targets - set(got)


def test_unit_conversion_is_flagged(rendered):
    for answer, doc in rendered.values():
        result = _run(answer, doc)
        for item in result["items"]:
            converted = item["value"].get("value")
            field = item["target"].rsplit("/", 1)[-1]
            unit = item["printed"]["unit"]
            if unit and isinstance(converted, float) and to_standard(1, unit, field) != 1:
                assert any(i.startswith("单位换算") for i in item.get("issues", [])), item["target"]


def test_missing_key_fields_listed(rendered):
    answer, doc = _sheet(rendered, "servo_motor")
    proposals = [p for p in proposals_from_answer(answer) if p["target"] != "params/rated_torque_nm"]
    result = _run(answer, doc, proposals)
    assert "params/rated_torque_nm" in result["missing_key_fields"]


def test_empty_response(rendered):
    _, doc = _sheet(rendered, "bearing")
    for tool_input in ({}, {"items": "x"}, {"items": None}):
        client = SimulatedClient({"id": "x", "tool_input": tool_input, "simulated": True})
        result = extract_document(doc, "bearing", DOC_ID, client)
        assert result["items"] == [] and result["rejected"] == []
        assert "vendor" not in result
        assert set(result["missing_key_fields"]) == {t.target for t, _ in targets("bearing").values() if t.key}


# ---------------------------------------------------------------- 核对能挡住的错误


def _rejected_reason(answer, doc, mutate, target="params/mass_kg"):
    p = copy.deepcopy(_proposal(answer, target))
    mutate(p)
    result = _run(answer, doc, [p])
    assert result["items"] == [], result["items"]
    assert len(result["rejected"]) == 1
    return result["rejected"][0]["reason"]


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda p: p.update(value=p["value"] * 1.5), "不在印出的文字"),  # 编造数值
        (lambda p: p.update(target="params/no_such_param"), "不属于品类"),
        (lambda p: p.update(target="envelope/0/length_mm"), "不属于品类"),
        (lambda p: p.update(page=99), "页码"),
        (lambda p: p.update(page=True), "页码"),
        (lambda p: p.update(quote="Mass 999 kg"), "原文引用"),  # 引用不在原文
        (lambda p: p.update(printed_text="12345"), "原文引用中没有"),
        (lambda p: p.update(printed_label=""), "printed_label"),
        (lambda p: p.update(printed_unit="N·m"), ""),  # 量纲不符（单位不在该行或量纲错误）
        (lambda p: p.update(printed_unit="furlong"), ""),
        (lambda p: p.update(confidence=1.5), "置信度"),
        (lambda p: p.update(confidence="high"), "置信度"),
        (lambda p: p.update(value=float("nan")), "有限数字"),
        (lambda p: p.update(min=1, max=2), "数值写法"),
        (lambda p: p.update(condition="at 99 °C"), "工况"),
        (lambda p: p.update(printed_text=""), "printed_text"),
    ],
)
def test_rejections(rendered, mutate, reason):
    answer, doc = _sheet(rendered, "reducer")
    got = _rejected_reason(answer, doc, mutate)
    assert reason in got, got


def test_enum_value_must_be_allowed(rendered):
    answer, doc = _sheet(rendered, "reducer")
    got = _rejected_reason(answer, doc, lambda p: p.update(value="cycloidal"), "params/reducer_kind")
    assert "schema" in got


def test_enum_field_rejects_unit(rendered):
    answer, doc = _sheet(rendered, "reducer")
    got = _rejected_reason(answer, doc, lambda p: p.update(printed_unit="mm"), "params/reducer_kind")
    assert "单位" in got


def test_free_text_must_be_printed(rendered):
    answer, doc = _sheet(rendered, "reducer")
    got = _rejected_reason(answer, doc, lambda p: p.update(value="M8"), "ports/motor_flange/thread")
    assert "不一致" in got


def test_range_order(rendered):
    answer, doc = _sheet(rendered, "drive")
    p = copy.deepcopy(_proposal(answer, "ports/power_in/voltage_v"))
    p["min"], p["max"] = p["max"], p["min"]
    result = _run(answer, doc, [p])
    assert "下限大于上限" in result["rejected"][0]["reason"]


def test_conflicting_values_rejected(rendered):
    """同一 target 两个都“看起来对”的值（各自都在原文里）互相矛盾：全部拒绝，交复核。"""
    answer, doc = _sheet(rendered, "drive")
    good = _proposal(answer, "ports/motor_out/rated_current_a")
    wrong = dict(_proposal(answer, "ports/power_in/rated_current_a"), target="ports/motor_out/rated_current_a")
    assert good["value"] != wrong["value"]
    result = _run(answer, doc, [good, wrong])
    assert result["items"] == []
    assert [r["reason"] for r in result["rejected"]] == ["同一 target 有互相矛盾的值"] * 2


def test_duplicate_same_value_kept_once(rendered):
    answer, doc = _sheet(rendered, "reducer")
    p = _proposal(answer, "params/mass_kg")
    low = dict(p, confidence=0.4)
    result = _run(answer, doc, [low, p])
    assert [i["value"]["confidence"] for i in result["items"]] == [0.95]
    assert result["rejected"] == []


def test_garbage_proposals_do_not_crash(rendered):
    answer, doc = _sheet(rendered, "servo_motor")
    result = _run(answer, doc, ["x", 3, None, {}, {"target": 5, "page": "1"}])
    assert result["items"] == [] and len(result["rejected"]) == 5
    assert errors("extraction.schema.json", result) == []


def test_identity_optional(rendered):
    answer, doc = _sheet(rendered, "servo_motor")
    result = _run(answer, doc, with_identity=False)
    assert "vendor" not in result and "model" not in result


def test_zh_and_en_both_work(rendered):
    for lang in ("en", "zh"):
        answer, doc = _sheet(rendered, "drive", lang)
        assert _run(answer, doc)["rejected"] == []


# ---------------------------------------------------------------- 录制与回放


def test_record_and_replay(rendered, tmp_path):
    answer, doc = _sheet(rendered, "bearing")
    request = build_request(doc, "bearing")
    response = simulated_response(answer)
    path = write_recording(tmp_path, request, response)
    assert path.name == f"{request_key(request)}.json"
    result = extract_document(doc, "bearing", DOC_ID, RecordedClient(tmp_path))
    assert result["rejected"] == [] and result["extractor"]["simulated"] is True
    assert result["extractor"]["response_id"] == response["id"]

    with pytest.raises(RecordingMissing):
        extract_document(doc, "bearing", DOC_ID, RecordedClient(tmp_path), prompt_version="extract/x")
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["request_key"] = "0" * 64
    path.write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(RecordingMissing):
        extract_document(doc, "bearing", DOC_ID, RecordedClient(tmp_path))


def test_model_from_env(rendered, tmp_path, monkeypatch):
    answer, doc = _sheet(rendered, "bearing")
    monkeypatch.setenv("FAP_LLM_MODEL", "claude-opus-5-5")
    client = SimulatedClient(simulated_response(answer))
    result = extract_document(doc, "bearing", DOC_ID, client)
    assert client.requests[0]["model"] == "claude-opus-5-5"
    assert result["extractor"]["model"] == "claude-opus-5-5"


def test_load_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# 注释\nFAP_T1=abc\nexport FAP_T2='x y'\nFAP_T3=keep\nbad line\n", encoding="utf-8")
    monkeypatch.delenv("FAP_T1", raising=False)
    monkeypatch.delenv("FAP_T2", raising=False)
    monkeypatch.setenv("FAP_T3", "existing")
    lx.load_dotenv(env)
    assert os.environ["FAP_T1"] == "abc" and os.environ["FAP_T2"] == "x y" and os.environ["FAP_T3"] == "existing"
    lx.load_dotenv(tmp_path / "none.env")  # 不存在时什么也不做


def test_anthropic_client_needs_key(monkeypatch):
    monkeypatch.setattr(lx, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        lx.AnthropicClient()


def test_anthropic_client_maps_request_and_records(rendered, tmp_path, monkeypatch):
    """用假的 anthropic 模块检查请求参数与录制，不联网。"""
    answer, doc = _sheet(rendered, "bearing")
    sent = {}

    class Messages:
        def create(self, **kw):
            sent.update(kw)
            block = types.SimpleNamespace(type="tool_use", input=simulated_response(answer)["tool_input"])
            return types.SimpleNamespace(id="msg_1", stop_reason="tool_use",
                                         content=[types.SimpleNamespace(type="text"), block])

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda: types.SimpleNamespace(messages=Messages())
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setattr(lx, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    client = lx.AnthropicClient(record_dir=tmp_path)
    result = extract_document(doc, "bearing", DOC_ID, client)
    # 只用新旧 SDK 都接受的参数：anthropic 1.x 的 messages.create() 已不接受 temperature
    assert set(sent) == {"model", "max_tokens", "system", "tools", "tool_choice", "messages"}
    assert sent["tool_choice"] == {"type": "auto"}  # 部分模型不支持强制指定工具
    assert lx.TOOL_NAME in sent["system"] and "调用工具" in sent["system"]
    assert sent["messages"][0]["role"] == "user"
    assert "simulated" not in result["extractor"] and result["extractor"]["response_id"] == "msg_1"
    replay = extract_document(doc, "bearing", DOC_ID, RecordedClient(tmp_path))
    assert replay == result


def test_cli_replay(rendered, tmp_path, monkeypatch):
    sheet = datasheets(0)[0]
    pdf = sheet.render(tmp_path / "s.pdf")
    doc = extract(pdf)
    rec_dir = tmp_path / "rec"
    write_recording(rec_dir, build_request(doc, sheet.answer["category"]), simulated_response(sheet.answer))
    monkeypatch.delenv("FAP_LLM_MODEL", raising=False)
    out = tmp_path / "out.json"
    args = [str(pdf), "--category", sheet.answer["category"], "--doc", DOC_ID, "--replay", str(rec_dir)]
    assert lx.main([*args, "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["format"] == "extraction/1"
    assert lx.main([str(pdf), "--category", "reducer", "--doc", DOC_ID, "--replay", str(rec_dir)]) == 1


# ---------------------------------------------------------------- 评审发现的漏洞（手工构造的文档，不依赖字体）

from ingest.pdf_extract import Document, Page, Table


def _doc(rows, text=""):
    table = Table(page=1, index=0, rows=[["Item", "Value", "Unit"], *rows], bbox=(0, 0, 1, 1))
    lines = [" ".join(r) for r in rows]
    return Document(path="x.pdf", sha256="0" * 64, pages=[Page(1, "\n".join([*lines, text]).strip(), [table])])


MOTOR = _doc(
    [
        ["Rated torque", "20", "N·m"],
        ["Peak torque", "60", "N·m"],
        ["Mass", "1.2", "kg"],
        ["Max. speed", "2,000", "r/min"],
        ["Mounting", "4-M5x0.8", "—"],
        ["Spigot", "Φ40h7", "mm"],
        ["Mounting holes", "4", "pcs"],
        ["Shaft", "Φ14 ±0.01", "mm"],
        ["Shaft fit", "M5x0.8", "—"],
    ],
    text="Synth Motion SM-X1 AC Servo Motor",
)


def _p(target, text, unit, label, quote, **kw):
    return {"target": target, "printed_text": text, "printed_unit": unit, "printed_label": label,
            "quote": quote, "page": 1, "confidence": 0.9, **kw}


def _verify(doc, *proposals, category="servo_motor", **identity):
    return lx.verify({"items": list(proposals), **identity}, doc, category, DOC_ID)


@pytest.mark.parametrize(
    "proposal",
    [
        # 跨行引用：把峰值扭矩那一行的数当成额定扭矩
        _p("params/rated_torque_nm", "20 N·m Peak torque 60", "N·m", "Rated torque",
           "20 N·m Peak torque 60 N·m", value=60),
        _p("params/rated_torque_nm", "60", "N·m", "Rated torque", "Peak torque 60 N·m", value=60),
        # 单位谎报
        _p("params/mass_kg", "1.2", "lb", "Mass", "Mass 1.2 kg", value=1.2),
        _p("params/rated_torque_nm", "20", "kgf·cm", "Rated torque", "Rated torque 20 N·m", value=20),
        # 符号翻转
        _p("params/mass_kg", "1.2", "kg", "Mass", "Mass 1.2 kg", value=-1.2),
        # 千分位歧义
        _p("params/max_speed_rpm", "2,000", "r/min", "Max. speed", "Max. speed 2,000 r/min", value=2),
        # 记号里的数字
        _p("ports/mount_flange/hole_count", "4-M5x0.8", "", "Mounting", "Mounting 4-M5x0.8 —", value=5),
        _p("ports/mount_flange/pilot_diameter_mm", "Φ40h7", "mm", "Spigot", "Spigot Φ40h7 mm", value=7),
        # 公差符号
        _p("ports/shaft/diameter_mm", "Φ14 ±0.01", "mm", "Shaft", "Shaft Φ14 ±0.01 mm",
           nominal=14, tol_upper=-0.01, tol_lower=0.01),
        # 自由文字截断
        _p("ports/shaft/fit", "M5x0.8", "", "Shaft fit", "Shaft fit M5x0.8 —", value="M5"),
        # 工况不在该行
        _p("params/rated_torque_nm", "20", "N·m", "Rated torque", "Rated torque 20 N·m", value=20,
           condition="at 99 °C"),
        # 叫法不在该行
        _p("params/rated_torque_nm", "20", "N·m", "Continuous torque", "Rated torque 20 N·m", value=20),
        # 有单位的字段漏写单位
        _p("params/rated_torque_nm", "20", "", "Rated torque", "Rated torque 20 N·m", value=20),
        # 类型异常
        _p(["params/mass_kg"], "1.2", "kg", "Mass", "Mass 1.2 kg", value=1.2),
        _p({"a": 1}, "1.2", "kg", "Mass", "Mass 1.2 kg", value=1.2),
        _p("params/mass_kg", "1.2", "kg", "Mass", "Mass 1.2 kg", value=10**400),
        _p("params/mass_kg", "1.2", "kg", ["Mass"], "Mass 1.2 kg", value=1.2),
        _p("params/mass_kg", "1.2", "kg", "Mass", "Mass 1.2 kg", value=1.2, condition=5),
    ],
)
def test_review_rejections(proposal):
    result = _verify(MOTOR, proposal)
    assert result["items"] == [], result["items"]
    assert len(result["rejected"]) == 1


@pytest.mark.parametrize(
    ("proposal", "expected"),
    [
        (_p("ports/mount_flange/hole_count", "4-M5x0.8", "", "Mounting", "Mounting 4-M5x0.8 —", value=4), 4),
        (_p("ports/mount_flange/hole_count", "4", "pcs", "Mounting holes", "Mounting holes 4 pcs", value=4), 4),
        (_p("ports/mount_flange/pilot_diameter_mm", "Φ40h7", "mm", "Spigot", "Spigot Φ40h7 mm", value=40), 40),
        (_p("params/mass_kg", "1.2", "kg", "Mass", "| Mass | 1.2 | kg |", value=1.2), 1.2),
        (_p("params/mass_kg", "1.2", "kg", "mass", "Mass 1.2 kg", value=1.2), 1.2),
        # 全文用“.”作小数点，逗号是千分位
        (_p("params/max_speed_rpm", "2,000", "r/min", "Max. speed", "Max. speed 2,000 r/min", value=2000), 2000),
        (_p("ports/shaft/fit", "M5x0.8", "", "Shaft fit", "Shaft fit M5x0.8 —", value="M5x0.8"), "M5x0.8"),
    ],
)
def test_review_acceptances(proposal, expected):
    result = _verify(MOTOR, proposal)
    assert result["rejected"] == []
    assert result["items"][0]["value"]["value"] == expected


def test_tolerance_plus_minus():
    p = _p("ports/shaft/diameter_mm", "Φ14 ±0.01", "mm", "Shaft", "Shaft Φ14 ±0.01 mm",
           nominal=14, tol_upper=0.01, tol_lower=-0.01)
    v = _verify(MOTOR, p)["items"][0]["value"]
    assert (v["nominal"], v["tol_upper"], v["tol_lower"]) == (14, 0.01, -0.01)


def test_overflow_after_conversion():
    doc = _doc([["Max. speed", "1e308", "r/s"]])
    p = _p("params/max_speed_rpm", "1e308", "r/s", "Max. speed", "Max. speed 1e308 r/s", value=1e308)
    assert _verify(doc, p)["items"] == []


def test_ratio_forms():
    doc = _doc([["Ratio", "1:100", "—"], ["Ratio B", "i = 50", "—"], ["Ratio C", "80:1", "—"]])
    ok = [
        _p("params/ratio", "1:100", "", "Ratio", "Ratio 1:100", value=100),
    ]
    bad = [
        _p("params/ratio", "1:100", "", "Ratio", "Ratio 1:100", value=1),
    ]
    assert len(_verify(doc, *ok, category="reducer")["items"]) == 1
    assert _verify(doc, *bad, category="reducer")["items"] == []
    for text, label, n in (("i = 50", "Ratio B", 50), ("80:1", "Ratio C", 80)):
        r = _verify(doc, _p("params/ratio", text, "", label, f"{label} {text}", value=n), category="reducer")
        assert r["items"][0]["value"]["value"] == n


def test_enum_and_bool_mapping_flagged_for_review():
    doc = _doc([["Type", "Strain wave gear", "—"], ["Phases", "Single-phase", "—"], ["Phases B", "3", "—"],
                ["DIN rail", "Yes", "—"]])
    r = _verify(doc, _p("params/reducer_kind", "Strain wave gear", "", "Type", "Type Strain wave gear",
                        value="harmonic"), category="reducer")
    assert any("枚举映射" in i for i in r["items"][0]["issues"])
    r = _verify(doc, _p("ports/power_in/phases", "Single-phase", "", "Phases", "Phases Single-phase", value=1),
                category="drive")
    assert any("枚举映射" in i for i in r["items"][0]["issues"])
    r = _verify(doc, _p("ports/power_in/phases", "3", "", "Phases B", "Phases B 3", value=1), category="drive")
    assert r["items"] == []
    r = _verify(doc, _p("ports/mount/din_rail", "Yes", "", "DIN rail", "DIN rail Yes", value=True), category="drive")
    assert any("布尔映射" in i for i in r["items"][0]["issues"])
    r = _verify(doc, _p("ports/mount/din_rail", "Yes", "", "DIN rail", "DIN rail Yes", value="yes"), category="drive")
    assert r["items"] == []


def test_unit_from_page_header_is_flagged():
    doc = _doc([["Outer diameter", "82", ""]], text="All dimensions in mm")
    p = _p("dims/outer_diameter_mm", "82", "mm", "Outer diameter", "Outer diameter 82", value=82)
    item = _verify(doc, p, category="reducer")["items"][0]
    assert any("单位" in i for i in item["issues"])


def test_dims_restricted_and_positive():
    doc = _doc([["Body length", "-75", "mm"], ["Width", "40", "mm"]])
    r = _verify(doc, _p("dims/body_length_mm", "-75", "mm", "Body length", "Body length -75 mm", value=-75))
    assert r["items"] == []
    r = _verify(doc, _p("dims/width_mm", "40", "mm", "Width", "Width 40 mm", value=40))  # 电机没有 width
    assert "不属于品类" in r["rejected"][0]["reason"]


def test_glued_cells_not_matched():
    doc = _doc([["Width", "40", "50"]])
    p = _p("dims/overall_length_mm", "4050", "", "Width", "Width 40 50", value=4050)
    assert _verify(doc, p, category="reducer")["items"] == []


def test_identity_must_be_printed():
    r = _verify(MOTOR, vendor="Synth Motion", model="NOT-ON-PAGE")
    assert r["vendor"] == "Synth Motion" and "model" not in r
    assert [x["target"] for x in r["rejected"]] == ["model"]


def test_anthropic_client_rejects_truncated(monkeypatch, tmp_path):
    class Messages:
        def create(self, **kw):
            return types.SimpleNamespace(id="m", stop_reason="max_tokens", content=[])

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda: types.SimpleNamespace(messages=Messages())
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setattr(lx, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = lx.AnthropicClient(record_dir=tmp_path)
    with pytest.raises(RuntimeError, match="stop_reason"):
        client.complete(build_request(MOTOR, "servo_motor"))
    assert list(tmp_path.iterdir()) == []


def test_extract_document_rejects_bad_inputs():
    client = SimulatedClient({"id": "x", "tool_input": {}, "simulated": True})
    with pytest.raises(ValueError):
        extract_document(MOTOR, "servo_motor", "bad id", client)
    with pytest.raises(ValueError):
        extract_document(Document("x", "0" * 64, []), "servo_motor", DOC_ID, client)


def test_cli_refuses_unapproved_source(tmp_path):
    assert lx.main([str(tmp_path / "x.pdf"), "--category", "reducer", "--doc", "src-not-registered"]) == 2


# ---------------------------------------------------------------- 第二轮评审：利用方式与真实版式


@pytest.mark.parametrize(
    ("rows", "text", "proposal"),
    [
        # 正文行重复了表格内容：只写 "7" / "5" 也不能借到 h7、M5 里的数字
        ([["Spigot", "Φ40h7", "mm"]], "Spigot Φ40h7 mm",
         _p("ports/mount_flange/pilot_diameter_mm", "7", "mm", "Spigot", "Spigot Φ40h7 mm", value=7)),
        ([["Mounting", "4-M5x0.8", "—"]], "Mounting 4-M5x0.8 —",
         _p("ports/mount_flange/hole_count", "5", "", "Mounting", "Mounting 4-M5x0.8", value=5)),
        # 单位只做子串比较的漏洞
        ([["Rated torque", "1.2", "kN·m"]], "",
         _p("params/rated_torque_nm", "1.2", "N·m", "Rated torque", "Rated torque 1.2 kN·m", value=1.2)),
        ([["Peak current", "15", "A(0-p)"]], "",
         _p("ports/power_in/peak_current_a", "15", "A", "Peak current", "Peak current 15 A(0-p)", value=15)),
        ([["Mass", "1.2", "kg"]], "", _p("params/mass_kg", "1.2", "g", "Mass", "Mass 1.2 kg", value=1.2)),
        # 行内无单位，本页有两种同类单位：不能自选
        ([["Rated torque", "20", ""], ["Note", "kgf·cm", "N·m"]], "",
         _p("params/rated_torque_nm", "20", "N·m", "Rated torque", "Rated torque 20", value=20)),
    ],
)
def test_second_review_rejections(rows, text, proposal):
    doc = _doc(rows, text=text)
    assert _verify(doc, proposal)["items"] == []


def test_same_sentence_other_value_not_borrowed():
    doc = Document("x", "0" * 64, [Page(1, "Rated torque 20 N·m, peak torque 60 N·m", [])])
    bad = _p("params/rated_torque_nm", "60", "N·m", "Rated torque", "Rated torque 20 N·m, peak torque 60 N·m",
             value=60)
    good = dict(bad, printed_text="20", value=20)
    assert _verify(doc, bad)["items"] == []
    assert _verify(doc, good)["items"][0]["value"]["value"] == 20


def test_model_word_boundary():
    doc = Document("x", "0" * 64, [Page(1, "Synth Motion XYZ-400 servo", [])])
    r = _verify(doc, model="XYZ-40")
    assert "model" not in r
    assert _verify(doc, model="XYZ-400")["model"] == "XYZ-400"


def test_condition_in_footnote_flagged():
    doc = _doc([["Rated torque *1", "18.5", "N·m"]], text="*1 at input speed 2000 rpm")
    p = _p("params/rated_torque_nm", "18.5", "N·m", "Rated torque", "Rated torque *1 18.5 N·m", value=18.5,
           condition="at input speed 2000 rpm")
    item = _verify(doc, p, category="reducer")["items"][0]
    assert item["value"]["condition"] == "at input speed 2000 rpm"
    assert any("工况" in i for i in item["issues"])


@pytest.mark.parametrize(
    ("cell", "unit", "kw", "want"),
    [
        ("40±0.1", "mm", {"nominal": 40, "tol_upper": 0.1, "tol_lower": -0.1}, {"nominal": 40}),
        ("200-240", "V", {"min": 200, "max": 240}, {"min": 200, "max": 240}),
        ("1.2×10⁻⁴", "kg·m²", {"value": 1.2e-4}, {"value": 1.2e-4}),
        ("1.2×10⁻⁴", "×10⁻⁴ kg·m²", {"value": 1.2}, {"value": 1.2e-4}),
    ],
)
def test_realistic_number_forms(cell, unit, kw, want):
    target = {"mm": "ports/shaft/diameter_mm", "V": "ports/power_in/voltage_class_v",
              "kg·m²": "params/rotor_inertia_kgm2", "×10⁻⁴ kg·m²": "params/rotor_inertia_kgm2"}[unit]
    unit_cell = unit.split()[-1]
    doc = _doc([["Item X", cell, unit_cell]])
    p = _p(target, cell, unit, "Item X", f"Item X {cell} {unit_cell}", **kw)
    r = _verify(doc, p)
    assert r["rejected"] == [], r["rejected"]
    for k, v in want.items():
        assert r["items"][0]["value"][k] == pytest.approx(v)


def test_header_style_table_flagged():
    table = Table(1, 0, [["Model", "Rated torque (N·m)", "Mass (kg)"], ["SM-A", "20", "1.2"]], (0, 0, 1, 1))
    doc = Document("x", "0" * 64, [Page(1, "", [table])])
    p = _p("params/mass_kg", "1.2", "kg", "Mass", "SM-A 20 1.2", value=1.2)
    item = _verify(doc, p)["items"][0]
    assert any("表头" in i for i in item["issues"])


def test_ratio_slash():
    doc = _doc([["Ratio", "1/100", "—"]])
    r = _verify(doc, _p("params/ratio", "1/100", "", "Ratio", "Ratio 1/100", value=100), category="reducer")
    assert r["items"][0]["value"]["value"] == 100


def test_comma_decimal_document():
    doc = _doc([["Mass", "1,5", "kg"], ["Speed", "3,000", "r/min"]])
    assert _verify(doc, _p("params/mass_kg", "1,5", "kg", "Mass", "Mass 1,5 kg", value=1.5))["items"]
    assert _verify(doc, _p("params/max_speed_rpm", "3,000", "r/min", "Speed", "Speed 3,000", value=3000))["items"] == []



@pytest.mark.parametrize(
    ("cell", "upper", "lower"),
    [("14 -0.006/-0.017", -0.006, -0.017), ("14 +0.034/+0.016", 0.034, 0.016)],
)
def test_same_sign_tolerance_accepted(cell, upper, lower):
    """两侧同号的公差（g6、F7）合法（ADR-0022）。"""
    doc = _doc([["Shaft", cell, "mm"]])
    p = _p("ports/shaft/diameter_mm", cell, "mm", "Shaft", f"Shaft {cell} mm",
           nominal=14, tol_upper=upper, tol_lower=lower)
    r = _verify(doc, p)
    assert r["rejected"] == [], r["rejected"]
    v = r["items"][0]["value"]
    assert (v["tol_upper"], v["tol_lower"]) == (upper, lower)
