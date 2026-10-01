"""人工复核队列（issue #30，ADR-0023）与组件组装的测试。"""

from __future__ import annotations

import copy
import os

import psycopg
import pytest

from ingest.assemble import assemble, component_id, derive, envelope
from ingest.llm_extract import extract_document, targets
from ingest.llm_simulate import SimulatedClient, proposals_from_answer, simulated_response
from ingest.synthetic import FontMissing, datasheets, find_font
from kb import review as rv
from kb.sources import SourceRegistry
from kb.store import change_log, get_component

DOC = "src-test-fixture"
REG = SourceRegistry.load()


def _answer_values(answer: dict) -> dict:
    tm = targets(answer["category"])
    out = {}
    for e in answer["fields"]:
        for p in e["paths"]:
            if p in tm:
                pv = dict(e["expected"])
                if e.get("condition"):
                    pv["condition"] = e["condition"]
                pv.update({"source": {"doc": DOC, "page": e["page"]}, "method": "extracted",
                           "confidence": 0.95, "reviewed": True})
                out[p] = pv
    return out


def _norm(comp: dict) -> dict:
    """组件的可比内容：值、端口类型与坐标系、包络尺寸（忽略来源与推导依据的写法）。"""
    out = {}
    for k, v in comp["params"].items():
        out["params/" + k] = {x: v[x] for x in ("value", "min", "max", "condition") if x in v}
    for p in comp["ports"]:
        out["port/" + p["id"]] = (p["type"], p["dir"], p.get("motion"), p.get("frame"))
        for k, v in p["spec"].items():
            out[f"ports/{p['id']}/{k}"] = {x: v[x] for x in ("value", "min", "max", "condition") if x in v}
    for i, part in enumerate(comp["envelope"]["parts"]):
        for k, v in part.items():
            out[f"env/{i}/{k}"] = v.get("value") if isinstance(v, dict) else v
    return out


# ---------------------------------------------------------------- 组装（纯函数）


@pytest.mark.parametrize("sheet", datasheets(0), ids=lambda s: s.id)
def test_assemble_matches_synthetic_answer(sheet):
    """全部读对时，组装出的组件与模拟规格书答案一致（值、端口、坐标系、包络）。"""
    a = sheet.answer
    comp, problems, _ = assemble(a["category"], a["component"]["vendor"], a["component"]["model"],
                                 _answer_values(a), test=True)
    assert problems == []
    assert comp["id"] == a["component"]["id"]
    assert _norm(comp) == _norm(a["component"])


def test_assemble_reports_missing_dims():
    a = next(s.answer for s in datasheets(0) if s.answer["category"] == "drive")
    values = {k: v for k, v in _answer_values(a).items() if k != "dims/depth_mm"}
    comp, problems, _ = assemble("drive", "Synth Motion", "X", values, test=True)
    assert comp is None and any("dims/depth_mm" in p for p in problems)


def test_assemble_reports_schema_gaps():
    a = next(s.answer for s in datasheets(0) if s.answer["category"] == "servo_motor")
    values = {k: v for k, v in _answer_values(a).items() if k != "ports/power_in/rated_current_a"}
    comp, problems, _ = assemble("servo_motor", "Synth Motion", "X", values, test=True)
    assert comp is None and any("rated_current_a" in p for p in problems)


def test_derive_only_fills_gaps():
    given = {"ports/inner/feature": {"value": "keyed"}, "ports/inner/fit": {"value": "P5", "reviewed": True},
             "ports/outer/fit": {"value": "P5", "reviewed": False}}
    d = derive("bearing", given)
    assert "ports/inner/feature" not in d and d["ports/inner/fit_system"]["method"] == "computed"
    assert d["ports/inner/fit_system"]["reviewed"] is True  # 依据已复核
    assert d["ports/outer/fit_system"]["reviewed"] is False  # 依据未复核
    assert d["ports/outer/feature"]["reviewed"] is False  # 按约定推出，须确认
    assert "ports/inner/clamping" not in d  # 不编造紧固方式（ADR-0024）
    assert derive("reducer", {"ports/motor_flange/thread": {"value": "M5"}})[
        "ports/motor_flange/hole_kind"]["value"] == "threaded"
    assert "ports/encoder_in/kind" not in derive("drive", {"ports/encoder_in/protocol": {"value": "vendor_proprietary"}})


def test_derive_mount_pattern_only_when_unambiguous():
    """ADR-0031：有水平孔距且 2 或 4 孔时推为 rect；其余情况不推断。"""
    def pv(v):
        return {"value": v, "reviewed": True}

    base = {"ports/mount/pitch_y_mm": pv(150), "ports/mount/hole_diameter_mm": pv(5.5)}
    for count in (2, 4):
        d = derive("drive", {**base, "ports/mount/pitch_x_mm": pv(30), "ports/mount/hole_count": pv(count)})
        assert d["ports/mount/pattern"]["value"] == "rect" and d["ports/mount/pattern"]["reviewed"] is True
    assert "ports/mount/pattern" not in derive(
        "drive", {**base, "ports/mount/pitch_x_mm": pv(30), "ports/mount/hole_count": pv(3)})
    assert "ports/mount/pattern" not in derive("drive", {**base, "ports/mount/pitch_x_mm": pv(30)})
    assert "ports/mount/pattern" not in derive("drive", {**base, "ports/mount/hole_count": pv(2)})


def test_component_id_rules():
    assert component_id("reducer", "Synth Gear", "SGH-13-100", test=True) == "test.reducer.synth-gear.sgh-13-100"
    assert component_id("bearing", "ACME Corp.", "6204 2RS") == "bearing.acme-corp.6204-2rs"
    with pytest.raises(ValueError):
        component_id("servo_motor", "汇川", "SV660")


def test_assemble_motor_needs_shaft_length():
    a = next(s.answer for s in datasheets(0) if s.answer["category"] == "servo_motor")
    values = {k: v for k, v in _answer_values(a).items() if k != "ports/shaft/usable_length_mm"}
    comp, problems, _ = assemble("servo_motor", "Synth Motion", "X", values, test=True)
    assert comp is None and any("shaft" in p for p in problems)


def test_assemble_port_type_ambiguous():
    a = next(s.answer for s in datasheets(0) if s.answer["category"] == "reducer")
    values = {k: v for k, v in _answer_values(a).items() if not k.startswith("ports/housing_mount/")}
    comp, problems, _ = assemble("reducer", "Synth Gear", "X", values, test=True)
    assert comp is None and any("housing_mount" in p for p in problems)


def test_assemble_notes_unused_dims():
    a = next(s.answer for s in datasheets(0) if s.answer["category"] == "drive")
    values = {**_answer_values(a), "dims/overall_length_mm": {"value": 1}}
    comp, _, notes = assemble("drive", "Synth Motion", "X", values, test=True)
    assert comp is not None and any("overall_length_mm" in n for n in notes)


def test_envelope_reducer_prefers_square():
    parts, _ = envelope("reducer", {"dims/overall_length_mm": {"value": 100}, "dims/square_mm": {"value": 60},
                                    "dims/outer_diameter_mm": {"value": 70}})
    assert parts[0]["shape"] == "box"


# ---------------------------------------------------------------- 复核队列（数据库）


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    """每个品类一份模拟抽取结果（全部读对）。"""
    pytest.importorskip("reportlab")
    pytest.importorskip("pdfplumber")
    try:
        find_font("latin")
        find_font("cjk")
    except FontMissing:
        if os.environ.get("CI"):
            raise
        pytest.skip("本地未安装生成 PDF 所需的字体；CI 中必须运行")
    from ingest.pdf_extract import extract

    d = tmp_path_factory.mktemp("rv")
    out = {}
    for s in datasheets(0):
        cat = s.answer["category"]
        if cat in out:
            continue
        doc = extract(s.render(d / f"{s.id}.pdf"))
        out[cat] = (s.answer, doc, extract_document(doc, cat, DOC, SimulatedClient(simulated_response(s.answer))))
    return out


def _commit(db, eid, **kw):
    plan = rv.commit(db, eid, reviewer="t", registry=REG, allow_test=True, **kw)
    return rv.commit(db, eid, reviewer="t", registry=REG, allow_test=True, confirm=plan["plan"], **kw)


def _accept_all(db, eid, by="tester"):
    for it in rv.pending(db, eid):
        if it["kind"] == "item":
            rv.decide(db, it["id"], "accept", reviewer=by)
        elif it["kind"] == "missing":
            rv.decide(db, it["id"], "absent", reviewer=by)
        else:
            rv.decide(db, it["id"], "dismiss", reviewer=by, error_category="other")


@pytest.mark.parametrize("category", ["servo_motor", "reducer", "drive", "bearing"])
def test_end_to_end(db, results, category):
    """抽取 → 入队 → 复核 → 组装写库：组件与答案一致，复核过的标为已复核，修改历史有记录。"""
    answer, _, result = results[category]
    eid = rv.enqueue(db, result, created_by="tester", registry=REG, allow_test=True)
    todo = rv.pending(db, eid)
    key_targets = {t.target for t, _ in targets(category).values() if t.key}
    assert {i["target"] for i in todo if i["kind"] == "item"} >= key_targets & {i["target"] for i in result["items"]}
    assert all(i["reasons"] for i in todo)
    _accept_all(db, eid)
    plan = rv.commit(db, eid, reviewer="tester", registry=REG, allow_test=True)
    assert plan["status"] == "needs_confirmation" and plan["frames"]
    assert get_component(db, answer["component"]["id"]) is None  # 未确认不写入
    with pytest.raises(rv.ReviewError, match="指纹"):
        rv.commit(db, eid, reviewer="tester", registry=REG, allow_test=True, confirm="0" * 16)
    out = rv.commit(db, eid, reviewer="tester", registry=REG, allow_test=True, confirm=plan["plan"])
    assert out["status"] == "created"
    comp = get_component(db, answer["component"]["id"])
    got, want = _norm(comp), _norm(answer["component"])
    assert got.keys() == want.keys()
    for k in want:
        assert got[k] == pytest.approx(want[k], rel=1e-3) if not isinstance(want[k], tuple) else got[k] == want[k], k
    reviewed = {f"params/{k}": v["reviewed"] for k, v in comp["params"].items()}
    for t in key_targets & set(reviewed):
        assert reviewed[t] is True
    auto = {i["target"] for i in rv.items(db, eid) if not i["needs_review"]}
    for t in auto & set(reviewed):
        assert reviewed[t] is False
    log = change_log(db, comp["id"])
    assert log and log[0]["changed_by"] == "tester" and f"#{eid}" in log[0]["reason"]
    with pytest.raises(rv.ReviewError):
        rv.decide(db, todo[0]["id"], "accept", reviewer="tester")


def test_duplicate_enqueue(db, results):
    _, _, result = results["bearing"]
    rv.enqueue(db, result, created_by="t", registry=REG, allow_test=True)
    with pytest.raises(rv.ReviewError, match="已经入队"):
        rv.enqueue(db, result, created_by="t", registry=REG, allow_test=True)


def test_enqueue_rejects_test_source_without_flag(db, results):
    _, _, result = results["bearing"]
    with pytest.raises(rv.ReviewError):
        rv.enqueue(db, result, created_by="t", registry=REG)
    bad = copy.deepcopy(result)
    bad["format"] = "x"
    with pytest.raises(rv.ReviewError, match="schema"):
        rv.enqueue(db, bad, created_by="t", registry=REG, allow_test=True)


def test_corrections_rejections_and_stats(db, results):
    """改值、拒绝、补字段、改判都写进组件；错误分类可统计；决定只增不改。"""
    answer, doc, _ = results["reducer"]
    proposals = proposals_from_answer(answer)
    # 读错质量（录成 2 倍）、漏掉减速比、多一条编造的提议
    mass = next(p for p in proposals if p["target"] == "params/mass_kg")
    proposals = [p for p in proposals if p["target"] not in ("params/ratio",)]
    bogus = dict(mass, target="params/backlash_arcmin", quote="Backlash 99 arcmin")
    result = extract_document(doc, "reducer", DOC, SimulatedClient(simulated_response(answer, proposals + [bogus])))
    eid = rv.enqueue(db, result, created_by="t", registry=REG, allow_test=True)
    todo = {i["target"]: i for i in rv.pending(db, eid)}
    assert todo["params/ratio"]["kind"] == "missing"
    rejected = [i for i in rv.pending(db, eid) if i["kind"] == "rejected"]
    assert len(rejected) == 1

    with pytest.raises(rv.ReviewError):
        rv.decide(db, todo["params/mass_kg"]["id"], "correct", reviewer="t", error_category="wrong_value",
                  value={"value": 1.0})  # 缺页码
    with pytest.raises(rv.ReviewError):
        rv.decide(db, todo["params/mass_kg"]["id"], "reject", reviewer="t")  # 缺错误分类
    with pytest.raises(rv.ReviewError):
        rv.decide(db, todo["params/mass_kg"]["id"], "absent", reviewer="t")  # item 不能 absent
    with pytest.raises(rv.ReviewError):
        rv.decide(db, todo["params/ratio"]["id"], "correct", reviewer="t", value={"value": -5}, page=1)

    _accept_all(db, eid)
    # 改判：质量其实读错了
    rv.decide(db, todo["params/mass_kg"]["id"], "correct", reviewer="t", error_category="wrong_value",
              value={"value": 1.5}, page=1, note="原文是 1.5 kg")
    # 缺失的减速比改为补上
    rv.decide(db, todo["params/ratio"]["id"], "correct", reviewer="t", value={"value": 50}, page=1)
    # 被拒的提议：确认拒得对
    rv.decide(db, rejected[0]["id"], "dismiss", reviewer="t", error_category="hallucinated")
    # 补一个没抽到的字段
    rv.add(db, eid, "params/output_bearing_dynamic_load_rating_n", {"value": 12000}, page=1, reviewer="t")

    hist = rv.history(db, todo["params/mass_kg"]["id"])
    assert [h["action"] for h in hist] == ["accept", "correct"]
    with pytest.raises(psycopg.Error):
        db.execute("DELETE FROM review_decisions")

    out = _commit(db, eid)
    comp = get_component(db, out["id"])
    assert comp["params"]["mass_kg"]["value"] == 1.5
    assert comp["params"]["mass_kg"]["method"] == "manual" and comp["params"]["mass_kg"]["reviewed"] is True
    assert comp["params"]["ratio"]["value"] == 50
    assert comp["params"]["output_bearing_dynamic_load_rating_n"]["value"] == 12000
    assert "backlash_arcmin" not in comp["params"]

    s = rv.stats(db, include_simulated=True)
    assert s["by_error"]["wrong_value"] == 1
    assert s["by_error"]["missed"] == 2
    assert s["by_error"]["hallucinated"] == 1
    assert s["by_target"]["params/mass_kg"] == {"wrong_value": 1}
    assert s["pending"] == 0
    assert rv.stats(db) == {"by_error": {}, "by_target": {}, "by_category": {}, "pending": 0}  # 默认不计模拟


def test_commit_blocks_until_reviewed(db, results):
    _, _, result = results["drive"]
    eid = rv.enqueue(db, result, created_by="t", registry=REG, allow_test=True)
    with pytest.raises(rv.ReviewIncomplete) as exc:
        _commit(db, eid)
    assert any("还没有决定" in p for p in exc.value.problems)


def test_conflicting_corrections_block_commit(db, results):
    _, _, result = results["bearing"]
    eid = rv.enqueue(db, result, created_by="t", registry=REG, allow_test=True)
    _accept_all(db, eid)
    rv.add(db, eid, "params/mass_kg", {"value": 9.9}, page=1, reviewer="t")
    with pytest.raises(rv.ReviewIncomplete, match="矛盾"):
        _commit(db, eid)


def test_cli(db, results, tmp_path, capsys):
    import json

    _, _, result = results["servo_motor"]
    f = tmp_path / "r.json"
    f.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    assert rv.main(["enqueue", str(f), "--by", "t", "--allow-test"], conn=db) == 0
    eid = db.execute("SELECT max(id) FROM extractions").fetchone()[0]
    assert rv.main(["list", "--extraction", str(eid)], conn=db) == 0
    first = rv.pending(db, eid)[0]
    assert rv.main(["show", str(first["id"])], conn=db) == 0
    assert rv.main(["decide", str(first["id"]), "reject", "--by", "t"], conn=db) == 1  # 缺错误分类
    _accept_all(db, eid)
    assert rv.main(["commit", str(eid), "--by", "t", "--allow-test"], conn=db) == 3
    plan = rv.commit(db, eid, reviewer="t", registry=REG, allow_test=True)["plan"]
    assert rv.main(["commit", str(eid), "--by", "t", "--allow-test", "--confirm", plan], conn=db) == 0
    assert rv.main(["list", "--all"], conn=db) == 1
    assert rv.main(["stats", "--include-simulated"], conn=db) == 0
    assert "已写入知识库" in capsys.readouterr().out


# ---------------------------------------------------------------- 第二轮：评审发现的问题


def _second_extraction(result, keep, change=None):
    """同一型号的另一份抽取（另一个文件）：只保留部分项，可改值。"""
    r = copy.deepcopy(result)
    r["document"]["sha256"] = "f" * 64
    r["items"] = [i for i in r["items"] if i["target"] in keep]
    for i in r["items"]:
        if change and i["target"] in change:
            i["value"]["value"] = change[i["target"]]
    r["rejected"], r["missing_key_fields"] = [], []
    return r


def test_update_merges_and_protects_reviewed_values(db, results):
    _, _, result = results["reducer"]
    eid = rv.enqueue(db, result, created_by="t", registry=REG, allow_test=True)
    _accept_all(db, eid)
    auto = next(i for i in rv.items(db, eid) if not i["needs_review"] and i["target"].startswith("params/")
                and isinstance(i["proposed"].get("value"), (int, float)))
    name = auto["target"].split("/", 1)[1]
    rv.decide(db, auto["id"], "accept", reviewer="t")  # 人工确认一个自动采纳项
    cid = _commit(db, eid)["id"]
    before = get_component(db, cid)

    # 第二份只给质量（关键字段，复核后改值）：须 --update；其余字段保留
    r2 = _second_extraction(result, {"params/mass_kg"}, {"params/mass_kg": 0.5})
    e2 = rv.enqueue(db, r2, created_by="t", registry=REG, allow_test=True)
    _accept_all(db, e2)
    with pytest.raises(rv.ReviewError, match="--update"):
        rv.commit(db, e2, reviewer="t", registry=REG, allow_test=True)
    out = _commit(db, e2, update=True)
    assert out["status"] == "updated"
    after = get_component(db, cid)
    assert after["params"]["mass_kg"]["value"] == 0.5
    assert set(after["params"]) == set(before["params"])
    assert after["params"][name] == before["params"][name] and after["params"][name]["reviewed"] is True
    assert after["envelope"] == before["envelope"]

    # 第三份：未复核的自动采纳值想改动已复核的值 → 拒绝
    r3 = _second_extraction(result, {auto["target"]}, {auto["target"]: auto["proposed"]["value"] * 2})
    r3["document"]["sha256"] = "e" * 64
    e3 = rv.enqueue(db, r3, created_by="t", registry=REG, allow_test=True)
    assert rv.pending(db, e3) == []
    with pytest.raises(rv.ReviewIncomplete, match="已复核"):
        rv.commit(db, e3, reviewer="t", registry=REG, allow_test=True, update=True)


def test_id_conflict_refused(db, results):
    answer, _, result = results["bearing"]
    eid = rv.enqueue(db, result, created_by="t", registry=REG, allow_test=True)
    _accept_all(db, eid)
    _commit(db, eid)
    r2 = _second_extraction(result, {i["target"] for i in result["items"]})
    model = answer["component"]["model"]
    e2 = rv.enqueue(db, r2, created_by="t", registry=REG, allow_test=True)
    _accept_all(db, e2)
    with pytest.raises(rv.ReviewError, match="id 冲突"):
        rv.commit(db, e2, reviewer="t", registry=REG, allow_test=True, update=True,
                  model=model.replace("-", " ").lower())


def test_append_only_and_guards(db, results):
    _, _, result = results["bearing"]
    eid = rv.enqueue(db, result, created_by="t", registry=REG, allow_test=True)
    for sql in ("UPDATE review_items SET needs_review=false", "DELETE FROM review_items",
                "TRUNCATE review_decisions CASCADE", "TRUNCATE review_items CASCADE",
                "UPDATE extractions SET result='{}'", "DELETE FROM extractions",
                "UPDATE extractions SET status='committed'"):
        with pytest.raises(psycopg.Error):
            db.execute(sql)
    _accept_all(db, eid)
    _commit(db, eid)
    with pytest.raises(psycopg.Error):
        db.execute("UPDATE extractions SET status='open'")


def test_simulated_needs_test_source(db, results):
    _, _, result = results["bearing"]
    r = copy.deepcopy(result)
    r["document"]["doc"] = "src-harmonic-drive-catalog"
    with pytest.raises(rv.ReviewError, match="模拟"):
        rv.enqueue(db, r, created_by="t", registry=REG)


def test_manual_value_page_range(db, results):
    _, _, result = results["bearing"]
    eid = rv.enqueue(db, result, created_by="t", registry=REG, allow_test=True)
    with pytest.raises(rv.ReviewError, match="页码"):
        rv.add(db, eid, "params/mass_kg", {"value": 1.0}, page=99, reviewer="t")


def test_reject_after_accept_and_withdrawn(db, results):
    _, _, result = results["bearing"]
    eid = rv.enqueue(db, result, created_by="t", registry=REG, allow_test=True)
    _accept_all(db, eid)
    mass = next(i for i in rv.items(db, eid) if i["target"] == "params/mass_kg")
    rv.decide(db, mass["id"], "reject", reviewer="t", error_category="hallucinated")
    added = rv.add(db, eid, "params/moment_load_rating_nm", {"value": 100}, page=1, reviewer="t")
    with pytest.raises(rv.ReviewError):
        rv.decide(db, added, "reject", reviewer="t", error_category="hallucinated")
    rv.decide(db, added, "reject", reviewer="t")  # 撤回：记为 withdrawn
    with pytest.raises(rv.ReviewError):
        rv.decide(db, mass["id"], "correct", reviewer="t", error_category="false_reject",
                  value={"value": 1.0}, page=1)  # item 不能用 false_reject
    s = rv.stats(db, eid, include_simulated=True)
    assert "withdrawn" not in s["by_error"] and s["by_error"]["hallucinated"] == 1
    out = _commit(db, eid)
    comp = get_component(db, out["id"])
    assert "mass_kg" not in comp["params"] and "moment_load_rating_nm" not in comp["params"]


def test_rejected_corrected_to_existing_target(db, results):
    answer, doc, _ = results["reducer"]
    proposals = proposals_from_answer(answer)
    mass = next(p for p in proposals if p["target"] == "params/mass_kg")
    bogus = dict(mass, quote="no such line")
    result = extract_document(doc, "reducer", DOC, SimulatedClient(simulated_response(answer, proposals + [bogus])))
    eid = rv.enqueue(db, result, created_by="t", registry=REG, allow_test=True)
    _accept_all(db, eid)
    rej = next(i for i in rv.items(db, eid) if i["kind"] == "rejected")
    mass_item = next(i for i in rv.items(db, eid) if i["target"] == "params/mass_kg")
    same = mass_item["proposed"]["value"]
    rv.decide(db, rej["id"], "correct", reviewer="t", error_category="false_reject", value={"value": same}, page=1)
    _, problems = rv.effective_values(db, eid)
    assert problems == []  # 值相同不算矛盾
    rv.decide(db, rej["id"], "correct", reviewer="t", error_category="false_reject", value={"value": 7.7}, page=1)
    _, problems = rv.effective_values(db, eid)
    assert any("矛盾" in p for p in problems)
