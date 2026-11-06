# -*- coding: utf-8 -*-
"""第 92 轮（电子 E5）：编码器接口芯片 WQ-ENCIF。网页的 JS 行为模型与 Python 参考模型（它又与 RTL 逐拍一致）用同一组激励逐拍核对；
芯片设计产物（仿真波形、版图结果）齐全；“芯片设计”页的接口能取到产物。"""
import json
import os
import shutil
import subprocess
import sys

import pytest

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHIP = os.path.join(os.path.dirname(DIG), "designs", "wq-encif")
sys.path.insert(0, os.path.join(CHIP, "model"))
import encif as E  # noqa: E402

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="没有 Node")


@needs_node
def test_js_model_matches_reference_every_cycle():
    cs = {k: v.w for k, v in E.cases().items()}
    r = subprocess.run(["node", "tools/encif_check.mjs"], input=json.dumps({"cases": cs}), capture_output=True, text=True, cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    js = json.loads(r.stdout)
    for k, words in cs.items():
        ref = [list(x) for x in E.run(words)]
        bad = next((i for i, (a, b) in enumerate(zip(js[k], ref)) if a != b), None)
        assert len(js[k]) == len(ref) and bad is None, (k, bad, bad is not None and (js[k][bad], ref[bad]))


@needs_node
def test_bench_filter_effect():
    """“接上编码器”：毛刺短于 N+1 拍不计；N=0 时毛刺造成计数来回跳；SPI 读回的值等于芯片里的计数（读的那一刻）"""
    code = """
import { bench } from './web/src/lib/encif.js';
const out = [];
for (const [n, g] of [[3, 0], [3, 0.05], [0, 0.05]]) { const r = bench({ flen: n, glitchPerUs: g, glitchMax: 3 });
  out.push({ n, g, read: r.readValue, steps: r.steps, glitches: r.glitches, passed: r.passed, cnt: r.tr.cnt[r.readAt + 7 * 10 + 5] }); }
const rv = bench({ dir: -1 });
out.push({ rev: rv.readValue });
console.log(JSON.stringify(out));
"""
    r = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, cwd=DIG, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    clean, filt, raw, rev = json.loads(r.stdout)
    assert clean["glitches"] == 0 and clean["read"] > 0
    assert filt["glitches"] > 0 and filt["passed"] == 0 and filt["steps"] == clean["steps"]      # 3 拍以内的毛刺全滤掉
    assert raw["passed"] == raw["glitches"] and raw["steps"] == clean["steps"] + 2 * raw["glitches"]   # 不滤：每个毛刺一来一回
    assert filt["read"] == clean["read"] == raw["read"]
    assert rev["rev"] == -clean["read"]


def test_artifacts_present():
    s = json.load(open(os.path.join(CHIP, "out", "sim", "summary.json"), encoding="utf-8"))
    assert s["pass"] and len(s["cases"]) == 9
    for c in s["cases"]:
        assert os.path.exists(os.path.join(CHIP, "out", "sim", c["wave"]))
