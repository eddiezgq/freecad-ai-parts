# -*- coding: utf-8 -*-
"""桥接写进 ERPNext 的本地时间在夏令时回拨那天也一直往前走（第 47 轮后 CI 发现作业卡工时“重叠”）。需要 node。"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = os.environ.get("WQ_NODE", "node")
ERP_JS = Path(__file__).resolve().parents[1] / "bridge" / "lib" / "erp.js"
pytestmark = pytest.mark.skipif(not shutil.which(NODE), reason="需要 node")

SCRIPT = """
const {erpDatetime} = require(process.argv[1]);
const [a, b, step] = JSON.parse(process.argv[2]);
const out = [];
for (let t = Date.parse(a); t < Date.parse(b); t += step) out.push(erpDatetime(new Date(t).toISOString()));
console.log(JSON.stringify(out));
"""


def run(a, b, step_s, tz="America/New_York"):
    r = subprocess.run([NODE, "-e", SCRIPT, str(ERP_JS), json.dumps([a, b, step_s * 1000])], capture_output=True,
                       text=True, check=True, env=dict(os.environ, WQ_TZ=tz))
    return json.loads(r.stdout)


def test_fall_back_stays_monotonic():
    v = run("2026-11-01T03:00:00Z", "2026-11-01T09:00:00Z", 7)
    assert all(x <= y for x, y in zip(v, v[1:]))
    assert v[0] == "2026-10-31 23:00:00"


def test_ordinary_times_unchanged():
    assert run("2026-07-01T12:34:56Z", "2026-07-01T12:34:57Z", 1) == ["2026-07-01 08:34:56"]
    assert run("2026-12-01T12:34:56Z", "2026-12-01T12:34:57Z", 1) == ["2026-12-01 07:34:56"]
    assert run("2026-11-01T04:59:59Z", "2026-11-01T05:00:00Z", 1) == ["2026-11-01 00:59:59"]
    assert run("2026-11-01T07:00:00Z", "2026-11-01T07:00:01Z", 1) == ["2026-11-01 02:00:00"]
    assert run("2026-11-01T06:00:00Z", "2026-11-01T06:00:01Z", 1, tz="Asia/Shanghai") == ["2026-11-01 14:00:00"]


def test_spring_forward_monotonic():
    v = run("2026-03-08T05:00:00Z", "2026-03-08T09:00:00Z", 11)
    assert all(x <= y for x, y in zip(v, v[1:]))
