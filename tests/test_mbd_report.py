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
