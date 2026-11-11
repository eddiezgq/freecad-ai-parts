"""第 139 轮 139e0：情景重载后工厂时钟回到起点，新工单的工时和上一次情景里同一工位的工时叠在一起，ERPNext 按工位台数拒收（417）。
桥接把这条工时顺延到冲突那张作业卡的最后一条工时之后、时长不变；别的错误照旧报出来。需要 node。"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.test_eto import mock_erp  # noqa: F401  （夹具）

ERP_JS = Path(__file__).resolve().parents[1] / "bridge" / "lib" / "erp.js"
SCRIPT = """
const {ERP} = require(process.argv[1]);
const e = new ERP({url: process.argv[2], log: () => {}});
(async () => {
  const out = [];
  for (const m of JSON.parse(process.argv[3])) {
    try { out.push((await e.onCycleEnd(m)).map((x) => x.payload.data)); } catch (err) { out.push({error: String(err.message)}); }
  }
  console.log(JSON.stringify(out));
})();
"""


def run(url, msgs):
    r = subprocess.run([os.environ.get("WQ_NODE", "node"), "-e", SCRIPT, str(ERP_JS), url, json.dumps(msgs)], capture_output=True, text=True,
                       timeout=60, env=dict(os.environ, WQ_TZ="UTC"))
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def cycle(wo, op, start, end):
    return {"mode": "teach", "corr": wo, "ts": end, "data": {"work_order": wo, "operation": op, "factory_start_ts": start, "factory_ts": end,
                                                          "cycle_time_s": 60}}


def test_overlap_after_scenario_reload_is_shifted(mock_erp):  # noqa: F811
    url, M = mock_erp
    ws = next(n for n, w in M.db["Workstation"].items() if int(w.get("production_capacity") or 1) == 1)
    op = "闭环测试工序"
    for name, wo, logs in (("JC-OLD", "WO-OLD", [("2026-11-12 09:00:00", "2026-11-12 09:30:00"), ("2026-11-12 09:30:00", "2026-11-12 10:00:00")]),
                           ("JC-NEW", "WO-NEW", [])):
        M.db.setdefault("Job Card", {})[name] = {"name": name, "work_order": wo, "operation": op, "workstation": ws, "for_quantity": 5,
                                                  "docstatus": 0, "status": "Open",
                                                  "time_logs": [{"from_time": a, "to_time": b, "completed_qty": 1} for a, b in logs]}
    # 新情景：同一工位 09:10–09:20（和上一次情景的 JC-OLD 叠在一起）→ 顺延到 10:00:01 起、仍是 10 分钟
    out = run(url, [cycle("WO-NEW", op, "2026-11-12T09:10:00Z", "2026-11-12T09:20:00Z"),
                    cycle("WO-NEW", op, "2026-11-12T09:20:00Z", "2026-11-12T09:25:00Z")])
    assert all(not isinstance(x, dict) for x in out), out
    logs = M.db["Job Card"]["JC-NEW"]["time_logs"]
    assert (logs[0]["from_time"], logs[0]["to_time"]) == ("2026-11-12 10:00:01", "2026-11-12 10:10:01")
    assert logs[1]["time_in_mins"] == 5 and logs[1]["from_time"] >= "2026-11-12 10:00:01"
    assert M.db["Job Card"]["JC-NEW"]["total_completed_qty"] == 2
    # 不重叠的照原样记
    out = run(url, [cycle("WO-NEW", op, "2026-11-12T11:00:00Z", "2026-11-12T11:05:00Z")])
    assert M.db["Job Card"]["JC-NEW"]["time_logs"][-1]["from_time"] == "2026-11-12 11:00:00"
    # 别的 417（超过工单数量）不顺延，照旧报错
    M.db["Job Card"]["JC-NEW"]["for_quantity"] = 3
    out = run(url, [cycle("WO-NEW", op, "2026-11-12T12:00:00Z", "2026-11-12T12:05:00Z")])
    assert "超过工单数量" in out[0]["error"]
