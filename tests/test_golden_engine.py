"""golden 运行器（issue #52）：引擎对全部 golden 用例的结果须与人工审定的预期一致。

预期由人手算并审定，不得为了让测试通过而修改预期（CLAUDE.md）。
"""

from __future__ import annotations

import pytest
import yaml

from engine.golden import cases, compare, load_fixtures, main
from engine.validate import validate

FIXTURES = load_fixtures()


@pytest.mark.parametrize("path", cases(), ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_golden_case(path):
    case = yaml.safe_load(path.read_text(encoding="utf-8"))
    report = validate(case["system"], FIXTURES.get)
    problems, _ = compare(case["expected"], report)
    assert problems == [], problems
    assert [c["check"] for c in report["checks"]] == [f"C{i}" for i in range(1, 12)]
    for c in report["checks"]:
        assert c["message"], c  # 每项都有说明（不适用时写明原因）


def _report(overall, **checks):
    return {"overall": overall, "checks": [{"check": k, "status": v} for k, v in checks.items()]}


def test_compare_detects_mismatch():
    exp = {"overall": "fail", "checks": {"C3": "fail", "C9": "any", "others": "not_fail"}}
    assert compare(exp, _report("fail", C3="fail", C9="fail", C4="pass")) == ([], {"C9": "fail"})
    problems, _ = compare(exp, _report("warn", C3="warn", C4="fail", C9="pass"))
    assert len(problems) == 3  # 整体、C3、C4 不得为 fail


def test_compare_rejects_malformed_expected():
    rep = _report("fail", C3="fail")
    assert compare({"overall": "fail", "checks": {"C33": "fail"}}, rep)[0]
    assert compare({"overall": "fail", "checks": {"c3": "fail"}}, rep)[0]
    assert compare({"overall": "fail", "checks": {"C3": "fial"}}, rep)[0]
    assert compare({"overall": "fail", "checks": {"others": "pass"}}, rep)[0]


def test_cli(capsys):
    assert main([]) == 0
    assert "个用例与预期一致" in capsys.readouterr().out
