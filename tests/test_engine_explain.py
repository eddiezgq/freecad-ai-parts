"""方案解释（issue #54，ADR-0030）：每个非 pass 项都有原因与端口。"""

from __future__ import annotations

import pytest
import yaml

from engine.compose import compose_chain
from engine.explain import CHECK_NAMES, explain, explain_candidates
from engine.golden import cases, load_fixtures
from engine.validate import validate

FIX = load_fixtures()


def _report(path):
    return validate(yaml.safe_load(path.read_text(encoding="utf-8"))["system"], FIX.get)


@pytest.mark.parametrize("lang", ["zh", "en"])
@pytest.mark.parametrize("path", cases(), ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_every_non_pass_item_explained(path, lang):
    report = _report(path)
    text = explain(report, lang)
    assert text == explain(report, lang)  # 确定性
    for c in report["checks"]:
        name = CHECK_NAMES[c["check"]][0 if lang == "zh" else 1]
        assert f"{c['check']} {name}" in text or c["status"] == "pass"
        if c["status"] in ("fail", "warn", "unknown"):
            for f in c.get("findings") or [c]:
                if f["status"] == c["status"]:
                    if lang == "zh":
                        assert f["message"] in text
                    for p in f.get("ports", []):
                        assert p in text


def test_headline_by_overall():
    heads = {"pass": "可用", "warn": "有条件可用", "fail": "不可用", "unknown": "待确认"}
    for path in cases():
        report = _report(path)
        assert explain(report).startswith(heads[report["overall"]])


def test_margin_and_numbers_in_english():
    report = _report(next(p for p in cases() if p.stem == "c4-continuous-torque"))
    text = explain(report, "en")
    assert "measured 36 N·m vs limit 34 N·m" in text and "margin" in text


def test_candidates():
    req = yaml.safe_load((cases()[-1]).read_text(encoding="utf-8"))["system"]["requirement"]
    cands = compose_chain(req, list(FIX.values()), top_n=2)
    zh, en = explain_candidates(cands, "zh"), explain_candidates(cands, "en")
    assert "## 方案 1" in zh and "排序依据" in zh and "## Option 1" in en and "Ranking basis" in en
    assert explain_candidates([], "zh") == "没有找到可用的方案。"


def test_bad_lang():
    with pytest.raises(ValueError):
        explain(_report(cases()[0]), "fr")
