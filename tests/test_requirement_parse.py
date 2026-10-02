"""需求解析（ADR-0037）：核对规则逐条单测，录制回放确定，不编造未说的指标。不联网。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import requirement_parse as rp
from ingest.llm_extract import RecordingMissing, request_key

EXAMPLE = json.loads((Path(__file__).resolve().parent.parent / "examples" / "joint2-requirement.json")
                     .read_text(encoding="utf-8"))
S = EXAMPLE["statement"]


def item(field, value, unit, quote):
    return {"field": field, "value": value, "unit": unit, "quote": quote}


class Fake:
    def __init__(self, items, unclear=()):
        self.tool_input = {"items": items, "unclear": list(unclear)}
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return {"id": "fake", "tool_input": self.tool_input, "simulated": True}


def run(statement, *items, unclear=()):
    return rp.parse(statement, Fake(list(items), unclear))


def test_replay_of_example_matches_example_requirement():
    out = rp.parse(S)
    assert out["status"] == "ok" and out["llm"]["simulated"] is False  # 真实录制（claude-sonnet-5-5）
    want = {k: v for k, v in EXAMPLE.items() if k != "id"}
    assert out["requirement"] == want
    assert out["basis"]["output_torque_peak_nm"] == "峰值 50 N·m"
    assert out["defaults"] == ["单相供电，按定义为交流（ADR-0039）", "安全系数未说明，按默认值 1.2（ADR-0008）"]
    assert out["unclear"] and out["rejected"] == []
    assert rp.parse(S) == out  # 回放确定


def test_unrecorded_statement_raises():
    with pytest.raises(RecordingMissing):
        rp.parse("一句没有录制过的话")


def test_unit_conversion_via_pint():
    s = "输出连续扭矩 2550 kgf·cm，输出转速 0.5 r/s，负载惯量 2000 kg·cm²，外径不超过 12 cm"
    out = run(s, item("output_torque_cont_nm", 2550, "kgf·cm", "输出连续扭矩 2550 kgf·cm"),
              item("output_speed_rpm", 0.5, "r/s", "输出转速 0.5 r/s"),
              item("load_inertia_kgm2", 2000, "kg·cm²", "负载惯量 2000 kg·cm²"),
              item("max_envelope_diameter_mm", 12, "cm", "外径不超过 12 cm"))
    r = out["requirement"]
    assert out["status"] == "ok"
    assert r["output_torque_cont_nm"] == pytest.approx(250.07, rel=1e-4)
    assert r["output_speed_rpm"] == pytest.approx(30)
    assert r["load_inertia_kgm2"] == pytest.approx(0.2)
    assert r["max_envelope_diameter_mm"] == pytest.approx(120)


def test_chinese_unit_words():
    s = "连续扭矩 25 牛米，转速 30 转/分"
    out = run(s, item("output_torque_cont_nm", 25, "牛米", "连续扭矩 25 牛米"),
              item("output_speed_rpm", 30, "转/分", "转速 30 转/分"))
    assert out["status"] == "ok" and out["requirement"]["output_speed_rpm"] == 30


@pytest.mark.parametrize(("bad", "reason"), [
    (item("output_torque_cont_nm", 25, "N·m", "连续扭矩 25 N·m（编的）"), "不在原话中"),
    (item("output_torque_cont_nm", 26, "N·m", "输出连续扭矩 25 N·m"), "不在引用"),
    (item("output_torque_cont_nm", 50, "N·m", "峰值 50 N·m"), "关键词"),
    (item("output_torque_cont_nm", 25, "", "输出连续扭矩 25 N·m"), "没有单位"),
    (item("output_torque_cont_nm", 25, "kN·m", "输出连续扭矩 25 N·m"), "没有紧跟"),
    (item("output_speed_rpm", 30, "N·m", "输出连续扭矩 25 N·m"), "不在引用"),
    (item("output_speed_rpm", 25, "N·m", "输出连续扭矩 25 N·m"), "关键词"),
    (item("output_speed_rpm", "30", "rpm", "输出转速 30 rpm"), "须为数字"),
    (item("max_power_w", 400, "W", "输出转速 30 rpm"), "未知字段"),
    (item("fieldbus_protocol", "canopen", "", "EtherCAT 总线"), "关键词"),
    (item("fieldbus_protocol", "lin", "", "EtherCAT 总线"), "可选值"),
    (item("safety_factor", 1.5, "", "输出转速 30 rpm"), "不在引用"),
    (item("safety_factor", 30, "", "输出转速 30 rpm"), "关键词"),
])
def test_rejections(bad, reason):
    good = [item("output_torque_cont_nm", 25, "N·m", "输出连续扭矩 25 N·m"),
            item("output_speed_rpm", 30, "rpm", "输出转速 30 rpm")]
    out = run(S, *good, bad)
    assert any(reason in r["reason"] for r in out["rejected"]), out["rejected"]
    if bad["field"] == "safety_factor":
        assert out["requirement"]["safety_factor"] == rp.DEFAULT_SAFETY_FACTOR  # 被拒后按默认值
    elif bad["field"] not in ("output_torque_cont_nm", "output_speed_rpm"):
        assert bad["field"] not in out["requirement"]


def test_rejected_required_field_leads_to_question():
    out = run(S, item("output_torque_cont_nm", 50, "N·m", "峰值 50 N·m"),
              item("output_speed_rpm", 30, "rpm", "输出转速 30 rpm"))
    assert out["status"] == "needs_input"
    assert out["questions"][0] == rp.QUESTIONS["output_torque_cont_nm"]


def test_missing_required_and_nothing_invented():
    out = run("给第 2 关节选一套驱动，外径不超过 100 mm",
              item("max_envelope_diameter_mm", 100, "mm", "外径不超过 100 mm"), unclear=["没说扭矩"])
    assert out["status"] == "needs_input"
    assert out["questions"][:2] == [rp.QUESTIONS["output_torque_cont_nm"], rp.QUESTIONS["output_speed_rpm"]]
    assert set(out["requirement"]) == {"statement", "max_envelope_diameter_mm", "safety_factor"}
    assert out["unclear"] == ["没说扭矩"]


def test_conflicting_values_are_dropped():
    s = "连续扭矩 25 N·m，也可以说连续扭矩 30 N·m，转速 30 rpm"
    out = run(s, item("output_torque_cont_nm", 25, "N·m", "连续扭矩 25 N·m"),
              item("output_torque_cont_nm", 30, "N·m", "连续扭矩 30 N·m"),
              item("output_speed_rpm", 30, "rpm", "转速 30 rpm"))
    assert out["status"] == "needs_input" and "output_torque_cont_nm" not in out["requirement"]
    assert any("多个不同的值" in r["reason"] for r in out["rejected"])


def test_supply_rules():
    s = "连续扭矩 25 N·m，转速 30 rpm，48 V 直流供电"
    base = [item("output_torque_cont_nm", 25, "N·m", "连续扭矩 25 N·m"), item("output_speed_rpm", 30, "rpm", "转速 30 rpm")]
    out = run(s, *base, item("supply.voltage_v", 48, "V", "48 V 直流供电"),
              item("supply.current_type", "dc", "", "48 V 直流供电"))
    assert out["requirement"]["supply"] == {"current_type": "dc", "voltage_v": 48.0, "phases": 0}
    out = run(s, *base, item("supply.voltage_v", 48, "V", "48 V 直流供电"))
    assert "supply" not in out["requirement"] and rp.QUESTIONS["supply"] in out["questions"]
    assert out["status"] == "ok"  # 供电不是必填，缺了只追问


def test_peak_below_cont_is_questioned():
    s = "连续扭矩 25 N·m，峰值 20 N·m，转速 30 rpm"
    out = run(s, item("output_torque_cont_nm", 25, "N·m", "连续扭矩 25 N·m"),
              item("output_torque_peak_nm", 20, "N·m", "峰值 20 N·m"), item("output_speed_rpm", 30, "rpm", "转速 30 rpm"))
    assert "output_torque_peak_nm" not in out["requirement"] and out["questions"]


def test_stated_safety_factor():
    s = "连续扭矩 25 N·m，转速 30 rpm，安全系数 1.5"
    out = run(s, item("output_torque_cont_nm", 25, "N·m", "连续扭矩 25 N·m"),
              item("output_speed_rpm", 30, "rpm", "转速 30 rpm"), item("safety_factor", 1.5, "", "安全系数 1.5"))
    assert out["requirement"]["safety_factor"] == 1.5 and out["defaults"] == []


def test_request_is_stable_and_validates_input():
    f = Fake([])
    rp.parse(S, f)
    assert request_key(f.requests[0]) == request_key(rp.build_request(S))
    assert f.requests[0]["prompt_version"] == "requirement/2" and S in f.requests[0]["user"]
    with pytest.raises(ValueError):
        rp.parse("  ")
    garbage = rp.interpret(S, {"items": ["x", 3]})
    assert garbage["status"] == "needs_input" and len(garbage["rejected"]) == 2


def test_cli(capsys):
    assert rp.main([S]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


# ------------------------------------------------------------------ 独立评审发现的问题（#104）


def _one(statement, it):
    return rp.interpret(statement, {"items": [it]})


@pytest.mark.parametrize(("statement", "it", "reason"), [
    # 1. 单位须紧跟在数字后：mN·m 不能报成 N·m，mm 不能报成 m
    ("连续扭矩 500 mN·m，转速 30 rpm", item("output_torque_cont_nm", 500, "N·m", "连续扭矩 500 mN·m"), "没有紧跟"),
    ("长度不超过 120 mm", item("max_envelope_length_mm", 120, "m", "长度不超过 120 mm"), "没有紧跟"),
    # 2. 关键词须在该数字前、同一分句内
    ("额定扭矩 20 N·m，转速 50 rpm", item("output_torque_cont_nm", 50, "rpm", "额定扭矩 20 N·m，转速 50 rpm"), "关键词"),
    ("扭矩 20 N·m，最大转速 60 rpm", item("output_torque_peak_nm", 20, "N·m", "扭矩 20 N·m，最大"), "关键词"),
    # 3. 特殊工况扭矩不是连续扭矩
    ("堵转扭矩 50 N·m，转速 30 rpm", item("output_torque_cont_nm", 50, "N·m", "堵转扭矩 50 N·m"), "特殊工况"),
    ("最高扭矩 50 N·m", item("output_torque_cont_nm", 50, "N·m", "最高扭矩 50 N·m"), "特殊工况"),
    ("过载扭矩 50 N·m", item("output_torque_cont_nm", 50, "N·m", "过载扭矩 50 N·m"), "特殊工况"),
    # 4. 千分位是一个数；倍数词须追问
    ("speed 1,500 rpm", item("output_speed_rpm", 1, "rpm", "speed 1,500 rpm"), "不在引用"),
    ("转速 0.3万 rpm", item("output_speed_rpm", 0.3, "rpm", "转速 0.3万 rpm"), "倍数词"),
    # 5. ASCII 关键词按单词边界
    ("48 V single-axis actuator", item("supply.current_type", "ac", "", "actuator"), "关键词"),
    ("48 V single-axis actuator", item("supply.phases", 1, "", "single-axis"), "关键词"),
    # 引用过长
    ("连续扭矩 25 N·m" + "，说明" * 40, item("output_torque_cont_nm", 25, "N·m", "连续扭矩 25 N·m" + "，说明" * 40),
     "过长"),
    # 11. 类型不对的条目给出原因而不是崩溃
    ("连续扭矩 25 N·m", item("output_torque_cont_nm", 25, "N·m", 5), "字符串"),
    ("EtherCAT 总线", item("fieldbus_protocol", ["ethercat"], "", "EtherCAT 总线"), "可选值"),
    ("EtherCAT 总线", {"field": ["x"], "value": 1}, "未知字段"),
])
def test_review_findings_rejected(statement, it, reason):
    out = _one(statement, it)
    assert any(reason in r["reason"] for r in out["rejected"]), out["rejected"]
    field = it.get("field")
    if isinstance(field, str) and field != "safety_factor":
        assert field.split(".")[0] not in out["requirement"]


@pytest.mark.parametrize(("statement", "it", "want"), [
    ("speed 1,500 rpm", item("output_speed_rpm", 1500, "rpm", "speed 1,500 rpm"), 1500),
    ("连续扭矩25N·m", item("output_torque_cont_nm", 25, "N·m", "连续扭矩25N·m"), 25),
    ("扭矩 20 N·m，转速 50 rpm", item("output_speed_rpm", 50, "rpm", "扭矩 20 N·m，转速 50 rpm"), 50),
    ("负载惯量 2000 kg·cm²", item("load_inertia_kgm2", 2000, "kg·cm²", "负载惯量 2000 kg·cm²"), 0.2),
    ("220 VAC 单相", item("supply.voltage_v", 220, "VAC", "220 VAC 单相"), None),
])
def test_review_valid_forms_still_accepted(statement, it, want):
    out = _one(statement, it)
    if want is None:  # VAC 不是 pint 单位：拒绝并说明，不猜
        assert out["rejected"] and "supply" not in out["requirement"]
        return
    assert out["requirement"][it["field"]] == pytest.approx(want)


def test_phases_imply_ac():
    """单相、三相供电按定义是交流（ADR-0039）：原话没说“交流”也不追问；直流的推导不变。"""
    s = "连续扭矩 25 N·m，转速 30 rpm，380 V 三相供电"
    base = [item("output_torque_cont_nm", 25, "N·m", "连续扭矩 25 N·m"), item("output_speed_rpm", 30, "rpm", "转速 30 rpm")]
    out = run(s, *base, item("supply.voltage_v", 380, "V", "380 V 三相供电"), item("supply.phases", 3, "", "380 V 三相供电"))
    assert out["requirement"]["supply"] == {"current_type": "ac", "voltage_v": 380.0, "phases": 3}
    assert out["basis"]["supply.current_type"] == "380 V 三相供电" and out["questions"] == []
    # 明说直流却又说三相：矛盾，不采用并追问
    s2 = "连续扭矩 25 N·m，转速 30 rpm，48 V 直流 三相"
    out = run(s2, *base, item("supply.voltage_v", 48, "V", "48 V 直流 三相"),
              item("supply.current_type", "dc", "", "48 V 直流 三相"), item("supply.phases", 3, "", "48 V 直流 三相"))
    assert "supply" not in out["requirement"] and any("矛盾" in r["reason"] for r in out["rejected"])
