"""问渠CAM Q4a 刀具库、机床库（ADR-0106）：用户刀具库的列出、保存核对、新建模板；用户机床的复制、保存核对、行程生效。"""

from __future__ import annotations

import json

import pytest

from analysis import cam
from analysis.cam import machines as M
from analysis.cam import tools as TL


def test_tool_library_save_checks_and_lists(tmp_path):
    env = {"FAP_TOOLS": str(tmp_path / "tools")}
    lib = {"format": "cam-tool/1", "name": "我的刀具库", "tools": []}
    t = TL.template("flat_endmill", "EM12", 7)
    with pytest.raises(TL.ToolError, match="diameter_mm"):          # 平底刀没写直径：schema 不过
        TL.save({**lib, "tools": [t]}, TL.user_dir(env) / "mine.json")
    t["diameter_mm"] = 12.0
    t["cutting"] = [{"iso_group": "P", "vc_m_min": {"min": 200, "max": 120}, "fz_mm": {"min": 0.05, "max": 0.08}}]
    with pytest.raises(TL.ToolError, match="下限 200 大于上限 120"):
        TL.save({**lib, "tools": [t]}, TL.user_dir(env) / "mine.json")
    t["cutting"][0]["vc_m_min"] = {"min": 120, "max": 200}
    dup = {**t, "id": "EM12B"}
    with pytest.raises(TL.ToolError, match="刀号重复"):
        TL.save({**lib, "tools": [t, dup]}, TL.user_dir(env) / "mine.json")
    p = TL.save({**lib, "tools": [t]}, TL.user_dir(env) / "mine.json")
    libs = TL.libraries(env)
    assert libs[0]["readonly"] and libs[-1] == {"name": "我的刀具库", "path": str(p), "readonly": False, "error": ""}
    assert all(x["readonly"] for x in libs[:-1])                  # 示例库、厂商样本库只读（Q4b）
    assert TL.get(TL.load(p), "EM12")["diameter_mm"] == 12.0
    with pytest.raises(TL.ToolError, match="只读"):
        TL.save(TL.load(), TL.EXAMPLE)
    assert "insert" in TL.template("turn", "T1", 1) and "diameter_mm" not in TL.template("turn", "T1", 1)


def test_copied_machine_travel_takes_effect(tmp_path):
    """复制示例车床、把 X 行程上限改成 30：原来能出的程序报超程"""
    env = {"FAP_MACHINES_DIR": str(tmp_path / "machines"), "FAP_MACHINES": str(tmp_path / "none.yaml")}
    m = M.copy_model("EX-LATHE", "MY-LATHE", "我的车床", env)
    assert m["example"] is False and "复制" in m["source"]
    x = next(a for a in m["axes"] if a["id"] == "X")
    x["min"], x["max"] = 50.0, 30.0
    with pytest.raises(M.MachineError, match="下限 50 不小于上限 30"):
        M.save_model(m, env)
    x["min"] = -2.0
    p = M.save_model(m, env)
    assert json.loads(p.read_text(encoding="utf-8"))["id"] == "MY-LATHE"
    assert M.model("MY-LATHE", env)["name"] == "我的车床"
    import os

    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        setup = {"mode": "turn", "machine": "MY-LATHE", "segments": [[30, 40], [40, 60]], "chamfer_mm": 1}
        r = cam.run(setup)
        assert any("超程" in c["text"] for p_ in r["data"]["programs"] for c in p_["checks"]), r["data"]["programs"][0]["checks"]
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
