# -*- coding: utf-8 -*-
"""工厂读本仓库的零件库（ADR-0058 第 4 条、M10 第 6d 项）：公共库叠加企业库、按品类和关键词查、企业库同 id 覆盖；
现场运行记录导出为 FreeCAD 数字孪生的 CSV。不联网、不连数据库。"""
import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PUBLIC = ROOT / "data" / "library"


@pytest.fixture()
def lib(monkeypatch, tmp_path):
    monkeypatch.setenv("FAP_LIBRARY_DIR", str(PUBLIC))
    monkeypatch.setenv("FAP_ENTERPRISE_DIR", str(tmp_path / "ent"))
    from hub import fap_library
    return importlib.reload(fap_library), tmp_path / "ent"


def test_public_library_is_listed(lib):
    m, _ = lib
    items = m.search()
    assert items and all(i["library"] == "public" for i in items)
    reducers = m.search("reducer", "csf 25")
    assert reducers and all(i["category"] == "reducer" for i in reducers)
    assert any("25" in (i["model"] or "") for i in reducers)
    full = m.get(reducers[0]["id"])
    assert full["library"] == "public" and full["params"]
    # 参数照原样：每个值都带出处
    assert all("source" in pv for pv in full["params"].values() if isinstance(pv, dict) and "value" in pv)
    assert m.get("no.such.part") is None


def test_enterprise_overrides_by_id(lib):
    m, ent = lib
    base = m.search("reducer")[0]
    comp = dict(m.get(base["id"]))
    comp.pop("library")
    comp["model"] = comp["model"] + "（企业补录）"
    (ent / "components").mkdir(parents=True)
    (ent / "components" / "x.json").write_text(json.dumps(comp, ensure_ascii=False), encoding="utf-8")
    hit = m.get(base["id"])
    assert hit["library"] == "enterprise" and hit["model"].endswith("（企业补录）")
    assert len(m.search()) == len(m.search(""))


def test_missing_dirs_give_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("FAP_LIBRARY_DIR", str(tmp_path / "none"))
    monkeypatch.setenv("FAP_ENTERPRISE_DIR", str(tmp_path / "none2"))
    from hub import fap_library
    m = importlib.reload(fap_library)
    assert m.search() == [] and m.get("x") is None


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def q(self, sql, args=None):
        return self.rows if "twin_log" in sql else []


def test_twin_records_csv_reads_back(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.delenv("WQ_AUTH", raising=False)
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    rows = [{"day": "2026-09-02", "data": {"run_h": 7.5, "torque_mean_nm": 31.0, "torque_max_nm": 70.0, "n_in_rpm": 1450.0}},
            {"day": "2026-09-01", "data": {"run_h": 0, "torque_mean_nm": None}},
            {"day": "2026-08-31", "data": {"run_h": 8.0, "torque_mean_nm": 29.0, "n_in_rpm": 1500.0}}]
    app_mod.H.db = _DB(rows)

    class _Teach:
        def start(self, name):
            pass

    app_mod.H.teach = _Teach()
    c = TestClient(app_mod.app)
    tok = c.post("/api/login", json={"name": "测试", "role": "engineer", "mode": "teach"}).json()["token"]
    r = c.get("/api/twin/units/GB-001/records.csv?instance=j2", headers={"x-wq-token": tok})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().split("\n")
    assert lines[0] == "day,instance,hours,output_torque_avg_nm,output_torque_max_nm,input_speed_rpm"
    assert lines[1] == "2026-08-31,j2,8.0,29.0,,1500.0" and lines[2] == "2026-09-02,j2,7.5,31.0,70.0,1450.0"
    assert len(lines) == 3
    app_mod.H.db = _DB([])
    assert c.get("/api/twin/units/GB-404/records.csv", headers={"x-wq-token": tok}).status_code == 404
