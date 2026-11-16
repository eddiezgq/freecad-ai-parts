"""AI 起草算例（ADR-0093 补充十一第 4 步）：在真实零件样例上核对“代码核对”这一层。

假客户端给的是“一个正确的 AI 会给的提议”和几种典型的错误提议（编造的数、换算过的数、引用不在原话里、面选错、方向反了……），
测的是程序能不能把对的拼成算例、把错的拦下来变成追问。真实 LLM 的面选对率要用录制回放来量（`python -m assist.fea_draft eval`，
录制须在有密钥的机器上用 --record 生成），没有录制时那一项跳过——不算通过。不联网、不调用真实 LLM。
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from assist import fea_draft as D
from tests.test_fea_bench import _need_fea

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {s["id"]: s for s in json.loads(D.SAMPLES.read_text(encoding="utf-8"))["samples"]}


GOOD = {
    "S1-RJ201-torque": {
        "name": "rj201-torque",
        "bodies": [{"part": 1, "material": "45-QT", "material_quote": "45 钢调质"}],
        "items": [{"type": "fixed", "part": 1, "features": ["F6"], "quote": "Ø70 法兰那一端的端面固定"},
                  {"type": "torque", "part": 1, "features": ["F4"], "quote": "在 Ø42.75 花键段上加峰值扭矩 92.5 N·m",
                   "magnitude": {"value": 92.5, "unit": "N·m", "quote": "峰值扭矩 92.5 N·m"}},
                  {"type": "static", "quote": "加峰值扭矩"}],
        "questions": []},
    "S2-LS101-shaft": {
        "bodies": [{"part": 1, "material": "45-QT", "material_quote": "45 钢调质"}],
        "items": [{"type": "cyl_support", "part": 1, "features": ["F1"], "dofs": ["radial"], "quote": "两处 Ø12 轴承位只限制径向"},
                  {"type": "cyl_support", "part": 1, "features": ["F4"], "dofs": ["radial"], "quote": "两处 Ø12 轴承位只限制径向"},
                  {"type": "fixed", "part": 1, "features": ["F7"], "quote": "电机端（z = 297 的端面）固定"},
                  {"type": "torque", "part": 1, "features": ["F3"], "quote": "针杆端 Ø10、长 22 的轴段上加峰值扭矩 2.82 N·m",
                   "magnitude": {"value": 2.82, "unit": "N·m", "quote": "峰值扭矩 2.82 N·m"}},
                  {"type": "modal", "quote": "另算前 4 阶固有频率", "n_modes": {"value": 4, "quote": "前 4 阶固有频率"}}],
        "questions": []},
    "S3-ARMUPPER-elbow-torque": {
        "bodies": [{"part": 1, "material": "6061-T6", "material_quote": "6061-T6"}],
        "items": [{"type": "fixed", "part": 1, "features": ["F6"], "quote": "肩部 Ø138 减速器座固定"},
                  {"type": "torque", "part": 1, "features": ["F4"], "quote": "肘部 Ø107 减速器座上加 j3 峰值扭矩 46.4 N·m",
                   "magnitude": {"value": 46.4, "unit": "N·m", "quote": "峰值扭矩 46.4 N·m"}}],
        "questions": []},
    "S4-ARMUPPER-combination": {
        "bodies": [{"part": 1, "material": "6061-T6", "material_quote": "6061-T6"}],
        "load_cases": [{"id": "G", "name": "自重", "kind": "dead", "quote": "自重（重力竖直向下）"},
                       {"id": "W", "name": "工作", "kind": "operating", "quote": "工作载荷是肘部 Ø107 减速器座上的扭矩 46.4 N·m"}],
        "combinations": [{"id": "C1", "name": "1.35G+1.5W", "quote": "按 1.35 × 自重 + 1.5 × 工作 组合校核",
                          "factors": [{"case": "G", "value": 1.35}, {"case": "W", "value": 1.5}]}],
        "items": [{"type": "fixed", "part": 1, "features": ["F6"], "quote": "肩部 Ø138 减速器座固定"},
                  {"type": "gravity", "part": 1, "case": "G", "quote": "自重（重力竖直向下）", "direction": "-z",
                   "direction_quote": "重力竖直向下"},
                  {"type": "torque", "part": 1, "features": ["F4"], "case": "W", "quote": "肘部 Ø107 减速器座上的扭矩 46.4 N·m",
                   "magnitude": {"value": 46.4, "unit": "N·m", "quote": "扭矩 46.4 N·m"}}],
        "questions": []},
    "S5-J2HSG-missing-load": {
        "bodies": [{"part": 1, "material": "6061-T6", "material_quote": "6061-T6"}],
        "items": [{"type": "fixed", "part": 1, "features": ["F6"], "quote": "底面（-z 面）固定在机座上"},
                  {"type": "bearing_load", "part": 1, "features": ["F1"], "magnitude": None,
                   "quote": "Ø110 减速器座受减速器传来的径向力"}],
        "questions": ["Ø110 减速器座上的径向力多大、朝哪个方向？"]},
    "S6-RJ201-english-missing": {
        "bodies": [{"part": 1, "material": "40Cr-QT", "material_quote": "40Cr quenched and tempered"}],
        "items": [{"type": "fixed", "part": 1, "features": ["F6"], "quote": "Fix the end face on the Ø70 flange end"},
                  {"type": "bearing_load", "part": 1, "features": ["F2"], "magnitude": None,
                   "quote": "Apply a radial bearing load on the Ø50 bearing seat"}],
        "questions": ["How large is the radial bearing load on the Ø50 seat, and in which direction?"]},
}


@pytest.fixture(scope="module")
def parts():
    _need_fea()
    from examples.apps import common as C

    lib = list(C.library().all())
    paths = {p for s in SAMPLES.values() for p in s["parts"]}
    return {p: D.part_features([str(ROOT / p)], lib) for p in paths}


def _run(sid, proposal, parts):
    s = SAMPLES[sid]
    ps = [x for p in s["parts"] for x in parts[p]]
    return D.verify(proposal, s["statement"], ps, response_id="fake", model="fake")


def _edit(sid, fn):
    p = copy.deepcopy(GOOD[sid])
    fn(p)
    return p


@pytest.mark.parametrize("sid", list(GOOD))
def test_correct_proposal_on_real_parts_scores_full(sid, parts):
    """正确的提议：面全对、数全对、该问的问到、分析步对；原话给全了的样例草稿过全部算例规则（确认后可算）"""
    r = _run(sid, GOOD[sid], parts)
    sc = D.score(r, SAMPLES[sid]["answer"])
    assert sc["wrong_face"] == 0 and sc["missing"] == 0 and sc["wrong_value"] == 0, (sc, r["rejected"])
    assert sc["questions_hit"] == sc["questions_expected"] and sc["steps_ok"], (sc, r["questions"])
    pv = r["study"]["provenance"]
    assert pv["drafted_by"] == "ai" and pv["confirmed_by_human"] is False
    assert all(b["source"] in ("statement", "feature", "default") for b in pv["basis"])
    if not SAMPLES[sid]["answer"]["questions"]:
        assert r["errors"] == [] and r["questions"] == [], (r["errors"], r["questions"])


def test_combination_factors_and_one_static_step_per_combination(parts):
    r = _run("S4-ARMUPPER-combination", GOOD["S4-ARMUPPER-combination"], parts)
    st = r["study"]
    assert st["combinations"][0]["factors"] == {"G": 1.35, "W": 1.5}
    assert [s.get("combination") for s in st["steps"]] == ["C1"]
    # “重力竖直向下”没说零件坐标的哪个轴：不起草重力，追问
    assert not [x for x in st["loads"] if x["type"] == "gravity"] and any("重力" in q for q in r["questions"])


def test_gravity_with_axis_stated_uses_standard_g(parts):
    sid = "S4-ARMUPPER-combination"
    stmt = SAMPLES[sid]["statement"].replace("重力竖直向下", "重力沿 -z")
    p = copy.deepcopy(GOOD[sid])
    for x in p["load_cases"] + p["items"]:
        x["quote"] = x["quote"].replace("重力竖直向下", "重力沿 -z")
    p["items"][1]["direction_quote"] = "重力沿 -z"
    ps = [x for q in SAMPLES[sid]["parts"] for x in parts[q]]
    r = D.verify(p, stmt, ps)
    g = next(x for x in r["study"]["loads"] if x["type"] == "gravity")
    assert g["acceleration_m_s2"] == [0, 0, -D.STANDARD_GRAVITY] and g["case"] == "G"
    note = next(b["note"] for b in r["study"]["provenance"]["basis"] if b["target"] == "/loads/0")
    assert "9.80665" in note and r["errors"] == [] and r["questions"] == []
    p["items"][1]["direction"] = "+z"                          # 与原话相反
    r = D.verify(p, stmt, ps)
    assert any("不符" in x["reason"] for x in r["rejected"])


def test_torque_axis_comes_from_the_feature(parts):
    r = _run("S3-ARMUPPER-elbow-torque", GOOD["S3-ARMUPPER-elbow-torque"], parts)
    t = next(x for x in r["study"]["loads"] if x["type"] == "torque")
    assert t["axis"]["dir"] == [0.0, -1.0, 0.0] and t["axis"]["origin_mm"][0] == pytest.approx(425.0, abs=0.01)


def test_missing_magnitude_becomes_question_not_a_guess(parts):
    r = _run("S5-J2HSG-missing-load", GOOD["S5-J2HSG-missing-load"], parts)
    assert not [x for x in r["study"]["loads"] if x["type"] == "bearing_load"]
    assert any("大小" in q for q in r["questions"])
    assert r["errors"]                                   # 没有载荷、没有分析步：草稿还不能算


@pytest.mark.parametrize("bad,why", [
    (lambda p: p["items"][1]["magnitude"].update(value=100), "不在引用"),                       # 编造的数
    (lambda p: p["items"][1]["magnitude"].update(value=92500, unit="N·mm"), "不在引用"),        # AI 自己换算的数
    (lambda p: p["items"][1]["magnitude"].update(unit="kN·m"), "单位"),                          # 单位不是原话的
    (lambda p: p["items"][1]["magnitude"].update(quote="峰值扭矩 95 N·m"), "不在原话"),          # 引用改了字
    (lambda p: p["items"][1].update(quote="在花键段上加扭矩 92.5 N·m"), "不在原话"),
    (lambda p: p["items"][1].update(features=["F6"]), "类型不合乎"),                             # 扭矩加在端面上
    (lambda p: p["items"][1].update(features=["F99"]), "不在零件"),
    (lambda p: p["items"][1].update(features=["F4", "F3"]), "不同轴"),                           # 花键段 + 内孔：同轴但……
])
def test_bad_torque_proposals_are_rejected(parts, bad, why):
    p = _edit("S1-RJ201-torque", bad)
    r = _run("S1-RJ201-torque", p, parts)
    if why == "不同轴":               # 花键段 F4 与内孔 F3 同轴：可以合并，扭矩照样加——这一条测的是合并后面集变了，打分判面错
        sc = D.score(r, SAMPLES["S1-RJ201-torque"]["answer"])
        assert sc["wrong_face"] == 1
        return
    assert not [x for x in r["study"]["loads"] if x["type"] == "torque"]
    assert any(why in x["reason"] for x in r["rejected"]), r["rejected"]
    assert r["questions"], "拦下来的要变成追问"


def test_direction_must_come_from_statement(parts):
    p = _edit("S4-ARMUPPER-combination", lambda p: p["items"][1].update(direction="+z"))
    r = _run("S4-ARMUPPER-combination", p, parts)
    assert any("方向" in x["reason"] for x in r["rejected"]) and not [x for x in r["study"]["loads"] if x["type"] == "gravity"]
    p = _edit("S4-ARMUPPER-combination", lambda p: p["items"][1].update(direction_quote=None))
    r = _run("S4-ARMUPPER-combination", p, parts)
    assert any("原话没说方向" in x["reason"] for x in r["rejected"])


def test_bearing_load_must_be_radial(parts):
    """LS-101 的轴线是 z：原话说沿 -z，与轴线平行，不是径向力，要拦下"""
    s = "平缝机上轴 LS-101，45 钢调质。Ø12 轴承位受沿 -z 方向 50 N 的轴承力。"
    prop = {"bodies": [{"part": 1, "material": "45-QT", "material_quote": "45 钢调质"}],
            "items": [{"type": "bearing_load", "part": 1, "features": ["F1"], "quote": "Ø12 轴承位受沿 -z 方向 50 N 的轴承力",
                       "magnitude": {"value": 50, "unit": "N", "quote": "50 N"}, "direction": "-z", "direction_quote": "沿 -z 方向"}],
            "questions": []}
    r = D.verify(prop, s, parts["examples/apps/out/lockstitch/LS-101.step"])
    assert any("不垂直于轴线" in x["reason"] for x in r["rejected"])


def test_material_must_be_in_statement_and_library(parts):
    p = _edit("S1-RJ201-torque", lambda p: p["bodies"][0].update(material="40Cr-QT", material_quote="45 钢调质"))
    r = _run("S1-RJ201-torque", p, parts)
    assert "material" not in r["study"]["bodies"][0] and any("材料" in q for q in r["questions"])
    p = _edit("S1-RJ201-torque", lambda p: p["bodies"][0].update(material="S355J2", material_quote="45 钢调质"))
    assert "material" not in _run("S1-RJ201-torque", p, parts)["study"]["bodies"][0]
    assert not D._material_ok("45-QT", "45 钢（调质）", "Q345 调质") and D._material_ok("Q345", "Q345（Q355）", "Q345 钢板")
    assert D._material_ok("40Cr-QT", "40Cr（调质）", "40Cr quenched and tempered")       # 真实 LLM 验收时查出的漏洞
    assert D._material_ok("45-QT", "45 钢（调质）", "45钢调质")
    p = _edit("S1-RJ201-torque", lambda p: p["bodies"][0].update(material=None, material_quote=None))
    r = _run("S1-RJ201-torque", p, parts)
    assert any("材料" in q for q in r["questions"]) and r["errors"]


def test_combination_factor_must_be_stated(parts):
    p = _edit("S4-ARMUPPER-combination", lambda p: p["combinations"][0]["factors"][0].update(value=1.2))
    r = _run("S4-ARMUPPER-combination", p, parts)
    assert not r["study"]["combinations"] and any(x["type"] == "combination" for x in r["rejected"])
    p = _edit("S4-ARMUPPER-combination", lambda p: p["load_cases"][0].update(kind="accidental"))
    r = _run("S4-ARMUPPER-combination", p, parts)
    assert any("类别" in x["reason"] for x in r["rejected"])


def test_load_without_case_when_cases_exist_is_asked(parts):
    p = _edit("S4-ARMUPPER-combination", lambda p: p["items"][2].pop("case"))
    r = _run("S4-ARMUPPER-combination", p, parts)
    assert not [x for x in r["study"]["loads"] if x["type"] == "torque"] and any("工况" in q for q in r["questions"])


def test_bolt_preload_without_bolt_body_is_asked_not_faked(parts):
    p = _edit("S1-RJ201-torque", lambda p: p["items"].append(
        {"type": "bolt_preload", "part": 1, "features": ["F6"], "quote": "Ø70 法兰那一端的端面固定"}))
    r = _run("S1-RJ201-torque", p, parts)
    assert not r["study"].get("connections") and any("螺栓" in q for q in r["questions"])


def test_fillet_cannot_carry_load(tmp_path):
    _need_fea()
    from tests.test_fea_bench import _write

    def body(o):
        b = o.addBox(0, 0, 0, 100, 20, 10)
        o.fillet([b], [c for _d, c in o.getEntities(1)][:1], [2])
    step = _write(tmp_path / "f.step", body)
    ps = D.part_features([step], [])
    fid = next(k for k, x in ps[0]["ids"].items() if x["type"] == "fillet")
    s = "试块，Q235，圆角处固定。"
    r = D.verify({"bodies": [{"part": 1, "material": "Q235", "material_quote": "Q235"}],
                  "items": [{"type": "fixed", "part": 1, "features": [fid], "quote": "圆角处固定"}], "questions": []}, s, ps)
    assert not r["study"]["supports"] and any("类型不合乎" in x["reason"] for x in r["rejected"])


def test_parse_direction():
    assert D.parse_direction("沿 -y 方向")[0] == "-y"
    assert D.parse_direction("z 轴负向")[0] == "-z"
    assert D.parse_direction("in the negative x direction")[0] == "-x"
    assert D.parse_direction("竖直向下")[0] is None          # 零件坐标的哪个轴没说：不猜
    assert D.parse_direction("沿 -y 方向")[1] == ""
    assert D.parse_direction("径向力")[0] is None
    assert D.parse_direction("pushed upward")[0] is None
    assert D.parse_direction("a setup step")[0] is None


def test_confirm_requires_name_no_open_questions_and_valid_study(parts):
    from analysis.fea.study import StudyInvalid, validate

    r = _run("S1-RJ201-torque", GOOD["S1-RJ201-torque"], parts)
    with pytest.raises(StudyInvalid, match="AI 起草"):
        validate(r["study"])
    with pytest.raises(D.ConfirmRefused):
        D.confirm(r["study"], "  ")
    at = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
    s = D.confirm(r["study"], "张工", at)
    assert s["provenance"]["confirmed_by"] == "张工" and s["provenance"]["confirmed_at"] == "2026-11-16T09:00:00+00:00"
    validate(s)
    q = _run("S5-J2HSG-missing-load", GOOD["S5-J2HSG-missing-load"], parts)
    with pytest.raises(D.ConfirmRefused, match="追问"):
        D.confirm(q["study"], "张工")
    q["study"]["provenance"]["questions"] = []
    with pytest.raises(D.ConfirmRefused, match="不能算"):          # 追问删了，但载荷、分析步还没补
        D.confirm(q["study"], "张工")


def test_request_is_deterministic_and_lists_features(parts):
    ps = parts["examples/apps/out/cobot_arm/ARM-UPPER.step"]
    s = SAMPLES["S3-ARMUPPER-elbow-torque"]["statement"]
    a, b = D.build_request(s, ps), D.build_request(s, ps)
    assert a == b and a["prompt_version"] == D.PROMPT_VERSION
    assert "F6（零件 1）孔 / 座 Ø138" in a["user"] and "CSF-32-100-2UH" in a["user"] and "6061-T6" in a["user"]


def test_draft_end_to_end_with_fake_client_is_fast(parts):
    """起草一份（不含 LLM）在 1 分钟内（工业级要求 6）"""
    s = SAMPLES["S3-ARMUPPER-elbow-torque"]
    r = D.draft(s["statement"], [str(ROOT / p) for p in s["parts"]], D.FakeClient(GOOD[s["id"]]))
    assert r["simulated"] and r["elapsed_s"]["features"] + r["elapsed_s"]["check"] < 60
    assert D.score(r, s["answer"])["wrong_face"] == 0


def test_recorded_llm_meets_usability_threshold():
    """真实 LLM（录制回放）：面选错 ≤ 10 %、该给的都给了、该问的都问了。录制要在有密钥的机器上生成"""
    _need_fea()
    if not D.RECORDINGS_DIR.is_dir() or not any(D.RECORDINGS_DIR.glob("*.json")):
        pytest.skip("还没有真实 LLM 的录制：在有密钥的机器上跑 python -m assist.fea_draft eval --record")
    from ingest.llm_extract import RecordedClient

    r = D.evaluate(RecordedClient(D.RECORDINGS_DIR))
    assert r["passed"], json.dumps(r, ensure_ascii=False, indent=1)


def test_cli_confirm_refuses_open_questions(parts, tmp_path, capsys):
    q = _run("S5-J2HSG-missing-load", GOOD["S5-J2HSG-missing-load"], parts)
    f = tmp_path / "s.json"
    f.write_text(json.dumps(q["study"], ensure_ascii=False), encoding="utf-8")
    assert D.main(["confirm", str(f), "--by", "张工"]) == 2
    assert "追问" in capsys.readouterr().err
    r = _run("S1-RJ201-torque", GOOD["S1-RJ201-torque"], parts)
    f.write_text(json.dumps(r["study"], ensure_ascii=False), encoding="utf-8")
    assert D.main(["confirm", str(f), "--by", "张工"]) == 0
    assert json.loads(f.read_text(encoding="utf-8"))["provenance"]["confirmed_by"] == "张工"
