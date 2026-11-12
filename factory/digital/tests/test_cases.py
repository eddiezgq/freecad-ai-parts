# -*- coding: utf-8 -*-
"""第 161 轮：设计案例——factory/cases 里每个案例的 case.json 齐全（八步、引用的文件都在、校核全部通过），
接口按工厂列出案例、给文件，不出案例目录。案例本身由 tools/cases 生成（要 build123d、gmsh、ccx，这里不重跑）。"""
import json
import os
import subprocess
import sys

import pytest

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
sys.path.insert(0, DIG)
from hub import cases as C  # noqa: E402

STEPS = ["brief", "concept", "calc", "sim", "cad", "process", "make", "review"]
ALL = [(p, c) for p in sorted(os.listdir(C.ROOT)) if os.path.isdir(os.path.join(C.ROOT, p))
       for c in C.LEVELS if os.path.isfile(os.path.join(C.ROOT, p, c, "case.json"))]


def test_there_are_cases():
    assert ("gearbox", "A") in ALL


@pytest.mark.parametrize("plant,cid", ALL)
def test_case_complete(plant, cid):
    c = C.case(plant, cid)
    assert c["plant"] == plant and c["id"] == cid
    assert [s["key"] for s in c["steps"]] == STEPS
    for s in c["steps"]:
        assert s["summary"] and s["summary_en"] and s["title_en"]
        for f in [x["file"] for x in s["figs"] + s["files"]] + ([s["md"]] if s["md"] else []):
            assert C.file_path(plant, cid, f), f
        for t in s["tools"]:
            assert t["route"].startswith("/") and t["label"] and t["label_en"]
    assert c["checks"] and all(k["ok"] for k in c["checks"]), [k for k in c["checks"] if not k["ok"]]
    assert c["all_ok"] is True
    assert "没有实物试制" in c["honest"]


def test_file_guard():
    assert C.file_path("gearbox", "A", "1_任务书.md")
    assert C.file_path("gearbox", "A", "../A/1_任务书.md") is None or C.file_path("gearbox", "A", "../A/1_任务书.md").endswith("1_任务书.md")
    assert C.file_path("gearbox", "A", "../../../plants/wenquest-gearbox.yaml") is None
    assert C.file_path("gearbox", "A", "case.json") is None
    assert C.file_path("gearbox", "Z", "1_任务书.md") is None
    assert C.file_path("..", "A", "x") is None


def test_gearbox_a_numbers():
    """样板案例的关键结论：45 钢疲劳不够、40Cr 够；有限元与手算相差在 5% 以内；改进后过程能力过 1.33"""
    c = C.case("gearbox", "A")
    k = {x["what"]: x for x in c["checks"]}
    assert float(k["选定方案疲劳安全系数"]["value"]) >= 1.5
    assert "45 钢只有" in c["steps"][3]["summary"]
    assert float(k["改进后最低过程能力 Cpk"]["value"]) >= 1.33
    files = c["files"]
    assert "SH-301-B.step" in files and sum(f.endswith(".nc") for f in files) == 6


CODE = ("import sys, json; sys.path[:0] = [{!r}, {!r}]\nfrom hub import app, cases\n"
        "print(json.dumps({{'plant': cases.plant_key(app.PLANT.plant_id()), 'list': cases.listing(cases.plant_key(app.PLANT.plant_id()))}}, ensure_ascii=False))")


@pytest.mark.parametrize("plant,expect", [(None, "gearbox"), ("motor", "motor")])
def test_listing_by_plant(plant, expect):
    env = dict(os.environ)
    if plant:
        env["WQ_PLANT_FILE"] = os.path.join(FAC, "plants", "wenquest-{}.yaml".format(plant))
    else:
        env.pop("WQ_PLANT_FILE", None)
    r = subprocess.run([sys.executable, "-c", CODE.format(DIG, FAC)], capture_output=True, text=True, env=env, cwd=DIG, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["plant"] == expect
    if expect == "gearbox":
        assert [x["id"] for x in out["list"]][:1] == ["A"] and out["list"][0]["all_ok"]
    assert all(set(x) >= {"id", "title", "title_en", "n_checks", "n_ok"} for x in out["list"])
