# -*- coding: utf-8 -*-
"""第 14 轮 设计优化：标准题（悬臂梁定强度最轻截面，与解析解比）、输出轴轻量化、多目标帕累托、计算服务的优化任务。"""
import math
import os
import shutil
import time

import pytest

pytest.importorskip("optuna")
pytest.importorskip("build123d")
if not shutil.which(os.environ.get("WQ_CCX", "ccx")):
    pytest.skip("没有 CalculiX（ccx）", allow_module_level=True)

from cae import optimize as O  # noqa: E402


def test_cantilever_fully_stressed():
    """悬臂梁 L 200、宽 20、端部 1000 N，45 钢屈服 355、安全系数 ≥ 2：最轻的高 h* = √(6FL/(b·σ许))"""
    r = O.run({"problem": "beam", "n_trials": 16})
    h = r["best"][0]["x"]["h"]
    exact = math.sqrt(6 * 1000 * 200 / (20 * 355 / 2))
    assert h == pytest.approx(exact, rel=0.03)
    assert r["base"]["x"] == {"h": 25.0} and r["base"]["base"]                     # 第一次评估是现行设计
    assert all(t["ok"] == (t["sf"] >= 2.0) for t in r["trials"])


def test_shaft_lighter_than_current():
    """SH-301：齿轮位、轴伸直径可变，安全系数 ≥ 1.3、0→350 N·m 脉动下无限寿命：找到满足约束、比现行设计轻的尺寸"""
    r = O.run({"problem": "shaft", "n_trials": 16})
    base, best = r["base"], r["best"][0]
    assert base["ok"] and best["ok"] and best["mass_kg"] < base["mass_kg"]
    assert best["sf"] >= 1.3 and best["life_inf"]
    assert any(not t["ok"] for t in r["trials"])                                   # 太细的被约束挡住


def test_errors():
    with pytest.raises(ValueError):
        O.run({"problem": "shaft", "vars": [{"name": "length"}]})
    with pytest.raises(ValueError):
        O.run({"problem": "nothing"})


def test_service_opt_job(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from cae import service
    monkeypatch.setattr(service, "DATA", str(tmp_path))
    with TestClient(service.app) as c:
        pr = c.get("/opt/problems").json()
        assert {p["id"] for p in pr["problems"]} == {"shaft", "housing", "heatsink"}
        assert c.post("/opt/jobs", json={"spec": {"problem": "x"}}).status_code == 400
        j = c.post("/opt/jobs", json={"spec": {"problem": "heatsink", "n_trials": 4, "vars": [{"name": "fins", "low": 7, "high": 11}]},
                                      "factory": "wq_test", "owner": "7"}).json()
        assert j["status"] == "queued" and j["kind"] == "opt"
        for _ in range(600):
            j = c.get("/jobs/" + j["id"]).json()
            if j["status"] in ("done", "failed"):
                break
            time.sleep(0.5)
        assert j["status"] == "done", j.get("error")
        t = c.get("/opt/jobs/{}/trials".format(j["id"])).json()
        assert t["final"] and len(t["trials"]) == 4 and t["trials"][0]["x"] == {"fins": 9}
        assert j["stats"]["trials"] == 4


def test_opt_one_sentence_and_explain_rules():
    from hub import opt_ai as A
    r = A.setup(None, "输出轴越轻越好，安全系数不小于 1.5，寿命无限，齿轮位只能在 38 到 44 之间，算 30 次", "shaft", {}, list(O.VARS["shaft"]))
    assert r["form"] == {"vars": {"d_gear": {"on": True, "low": 38.0, "high": 44.0}}, "obj": "mass", "sf_min": 1.5, "life": "infinite", "n": 30}
    assert not r["unmatched"] and r["engine"] == "rules"
    r = A.setup(None, "箱体最高温度不超过 75 度，散热筋越少越好，筋高 20 到 35", "housing", {}, list(O.VARS["housing"]))
    assert r["form"]["t_max"] == 75 and r["form"]["vars"]["fin_h"] == {"on": True, "low": 20.0, "high": 35.0}
    res = {"trials": [{"ok": True, "violation": []}] * 3, "seconds": 9, "constraints": {"sf_min": 1.3},
           "base": {"ok": True, "violation": [], "mass_kg": 1.238, "sf": 1.46},
           "best": [{"ok": True, "mass_kg": 1.147, "sf": 1.36}]}
    t = A.rules_explain({"spec": {"problem": "shaft"}}, res)["text"]
    assert "-7.4%" in t and "强度卡住" in t
