"""问渠 CAD「AI 设计整机」面板的逻辑（ADR-0115 44.4，freecad_addon/core/robot_design.py）。不联网、不调用真实 AI。"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from assist import robot_fea as RF
from freecad_addon.core import robot_design as C

OUT = C.CASE / "out"


def _load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def _fake(**kw):
    """把六步都换成假的：{步序号: (状态, 说明) 或异常}"""
    def make(k):
        def f(_case):
            v = kw.get(f"s{k}", ("pass", f"第 {k} 步"))
            if isinstance(v, Exception):
                raise v
            return v
        return f
    return {name: make(k) for k, name in enumerate(C.STEPS)}


def test_six_steps_in_order_and_progress(tmp_path):
    seen = []
    r = C.run("x", None, out_dir=tmp_path, steps=_fake(), progress=lambda t, text, d, n: seen.append(text))
    assert [s["step"] for s in r["steps"]] == list(C.STEPS) and r["status"] == "pass" and r["stopped_at"] is None
    assert seen[0] == C.STEPS[0] and C.STEPS[-1] in seen
    timing = json.loads((tmp_path / "out" / "timing.json").read_text(encoding="utf-8"))
    assert [s["step"] for s in timing["steps"]] == list(C.STEPS)
    assert (tmp_path / "requirement.txt").read_text(encoding="utf-8") == "x"


def test_a_failed_step_stops_the_run_and_says_why(tmp_path):
    r = C.run("x", None, out_dir=tmp_path, steps=_fake(s2=RuntimeError("壳体放不下")))
    st = [s["status"] for s in r["steps"]]
    assert st == ["pass", "pass", "fail", "waiting", "waiting", "waiting"]
    assert r["stopped_at"] == C.STEPS[2] and r["status"] == "fail" and "壳体放不下" in r["steps"][2]["note"]
    timing = json.loads((tmp_path / "out" / "timing.json").read_text(encoding="utf-8"))
    assert timing["status"] == "fail" and timing["stopped_at"] == C.STEPS[2]


def test_without_fea_the_result_is_pending_not_pass(tmp_path):
    steps = _fake()
    steps.pop(C.STEPS[4])                                 # 用真的有限元这一步（不勾时不算）
    r = C.run("x", None, out_dir=tmp_path, steps=steps, do_fea=False)
    assert r["steps"][4]["status"] == "skipped" and r["status"] == "unknown"
    assert not (tmp_path / "out" / "fea-result.json").exists()
    timing = json.loads((tmp_path / "out" / "timing.json").read_text(encoding="utf-8"))
    assert "没勾" in timing["steps"][4]["note"]


def test_only_the_exact_example_replays():
    t = C.example_text()
    assert C.is_example(t) and C.is_example(t.replace("\n", "\r\n")) and C.is_example(t + "\n")
    assert not C.is_example(t.replace("0.5", "0.6"))


def test_fea_reuses_saved_results_only_when_the_fingerprint_matches(monkeypatch):
    """回放：案例已算的 10 个支架按指纹复用，一个也不现算；零件或载荷变了指纹就变"""
    import analysis

    cr, br, cad, vr = _load("concept-result.json"), _load("build-result.json"), _load("cad/cad-result.json"), _load("verify-result.json")
    monkeypatch.setattr(analysis, "run", lambda *a, **k: pytest.fail("指纹一样不该现算"))
    monkeypatch.setattr(RF, "extract", lambda *a, **k: pytest.fail("指纹一样不该取零件"))
    starts = []
    r = RF.analyse(cr["chosen"], br, cad, vr, "nowhere.step", float(cr["conditions"]["payload"]), reuse=C.example_reuse(),
                   on_start=lambda k, n, name: starts.append((k, n)))
    saved = _load("fea-result.json")
    assert len(r["items"]) == len(saved["items"]) == 10 and all(i["reused"] for i in r["items"])
    assert [i["safety_fatigue"] for i in r["items"]] == [i["safety_fatigue"] for i in saved["items"]]
    assert r["status"] == saved["status"] and starts[0] == (0, 10) and starts[-1] == (9, 10)

    p = next(x for x in cad["parts"] if x["name"] == "j2 U 形支架")
    ld = RF.load_on(cr["chosen"], p, cad["parts"], 0.5, br["duty"]["initial"], RF.dynamic_factor(vr))
    kw = {"mesh": RF.mesh_mm(p), "convergence": True, "required": 1.2, "design": cad["design"]}
    fp = RF.fingerprint(p, ld, **kw)
    assert fp in C.example_reuse()
    assert RF.fingerprint(dict(p, plate_mm=4.0), ld, **kw) != fp
    assert RF.fingerprint(p, dict(ld, force_n=[f * 1.01 for f in ld["force_n"]]), **kw) != fp
    assert RF.fingerprint(p, ld, **dict(kw, mesh=2.0)) != fp
    assert RF.fingerprint(p, json.loads(json.dumps(ld)), **kw) == fp       # JSON 往返不变


def test_tabs_come_from_the_report_sections():
    t = dict(C.tabs(C.CASE))
    assert list(t) == [x for x, _ in C.TABS]
    assert all(t.values())
    assert "需求原话" in t["条件"] and "整机方案" in t["构型"] and "支架强度有限元" in t["仿真"]
    assert "BOM" in t["BOM"] and "卡在哪里" in t["用时与卡点"]


class _Ent:
    def __init__(self):
        self.docs = []

    def register_document(self, f, title, actor):
        assert Path(f).is_file()
        self.docs.append(title)
        return {"id": f"doc-{len(self.docs)}", "title": title}


def test_confirm_registers_results_but_not_a_replayed_example(tmp_path):
    import shutil

    shutil.copytree(OUT, tmp_path / "out")
    run = {"out_dir": str(tmp_path), "replay": True, "status": "unknown", "stopped_at": None}
    e = _Ent()
    with pytest.raises(C.ConfirmError, match="录制回放"):
        C.confirm(e, run, drawing_no="TA", name="教学臂", enterprise="问渠", actor="张")
    with pytest.raises(C.ConfirmError, match="都要填"):
        C.confirm(e, dict(run, replay=False), drawing_no="", name="教学臂", enterprise="问渠", actor="张")
    with pytest.raises(C.ConfirmError, match="没有跑完"):
        C.confirm(e, dict(run, replay=False, stopped_at=C.STEPS[2]), drawing_no="TA", name="x", enterprise="问渠", actor="张")
    docs = C.confirm(e, dict(run, replay=False), drawing_no="TA", name="教学臂", enterprise="问渠", actor="张")
    assert len(docs) >= 9 and any("report.md" in d["title"] for d in docs) and any("STEP" in d["title"] for d in docs)


def test_steps_table_html_has_every_step():
    tab = copy.deepcopy([{"step": s, "who": "代码", "status": "waiting", "seconds": None, "note": ""} for s in C.STEPS])
    tab[0].update(status="pass", seconds=1.0)
    h = C.steps_html(tab)
    assert all(s in h for s in C.STEPS) and "通过" in h and "等待" in h


def _need_pipeline():
    from analysis.common.solvers import find_ccx

    if os.environ.get("CI"):
        import gmsh  # noqa: F401
        import mujoco  # noqa: F401
        assert find_ccx(), "CI 中没有 ccx"
        return
    pytest.importorskip("gmsh")
    pytest.importorskip("mujoco")


def test_example_replays_from_requirement_to_report(tmp_path):
    """面板的回放示例从需求跑到报告：前四步现算（约 2–3 分钟），有限元按指纹全部复用，BOM 与案例一样"""
    _need_pipeline()
    r = C.run(C.example_text(), C.example_client(), replay=True, out_dir=tmp_path)
    assert r["stopped_at"] is None, r["steps"]
    assert [s["status"] for s in r["steps"]] == ["pass", "pass", "pass", "unknown", "pass", "pass"]
    assert "10 个用案例已算的有限元结果" in r["steps"][4]["note"]
    assert (tmp_path / "out" / "bom.csv").read_text(encoding="utf-8") == (OUT / "bom.csv").read_text(encoding="utf-8")
    assert dict(C.tabs(tmp_path))["仿真"]


def test_fea_time_estimate_from_this_machine(tmp_path):
    log = tmp_path / "fea-time.json"
    assert "用时不知道" in C.fea_estimate(log)
    C.record_fea_time(log, 1200.0, 2, 10)
    assert C.fea_estimate(log) == "本机上次每个支架约 10 分钟，10 个支架约 100 分钟"
