"""问渠 CAD「AI 设计整机」面板（ADR-0115 44.4）：装配与 BOM 放进文档；面板显示步骤与页签、回放示例、入企业库。需要 FreeCAD。

AI 与有限元用案例 A 已存的结果（examples/robots/teaching-arm/out），装配 STEP 按案例的方案重新生成（不入库）。
"""

from __future__ import annotations

import json
import os
import shutil

import pytest

pytestmark = pytest.mark.freecad

from freecad_addon.core import robot_design as C

OUT = C.CASE / "out"


@pytest.fixture
def gui():
    if not os.environ.get("DISPLAY"):
        pytest.skip("面板要界面（xvfb）")
    import FreeCADGui

    FreeCADGui.showMainWindow()
    return FreeCADGui


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    """案例 A 的结果目录；装配 STEP 由三维装配按案例的方案与板厚重出"""
    pytest.importorskip("gmsh")
    from assist import robot_cad

    d = tmp_path_factory.mktemp("robot")
    shutil.copytree(OUT, d / "out")
    o = d / "out"
    rc = robot_cad.main([str(o / "concept-result.json"), str(o / "build-result.json"), "-o", str(o / "cad"),
                         "--plates", str(C.CASE / "plates.json")])
    assert rc == 0
    return d


@pytest.fixture
def doc():
    import FreeCAD

    d = FreeCAD.newDocument("robot_design_test")
    name = d.Name
    yield d
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)


@pytest.fixture
def lib():
    from kb.library import JsonLibrary

    return JsonLibrary(C.ROOT / "data" / "library")


def _run_out(case, replay=False):
    table = [{"step": s, "who": "代码", "status": "pass", "seconds": 1.0, "note": ""} for s in C.STEPS]
    table[3]["status"] = "unknown"
    return {"out_dir": str(case), "steps": table, "status": "unknown", "stopped_at": None, "replay": replay, "do_fea": True}


def test_place_names_colours_and_bom(gui, doc, case):
    from freecad_addon.fc import robot_doc as D

    cad = json.loads((case / "out" / "cad" / "cad-result.json").read_text(encoding="utf-8"))
    r = D.place(doc, case)
    assert list(r["objects"]) == [p["name"] for p in cad["parts"]]
    for p in cad["parts"]:
        ob = r["objects"][p["name"]]
        assert ob.Shape.CenterOfMass.distanceToPoint(__import__("FreeCAD").Vector(*p["cog_mm"])) < 0.1
        want = D.GREY if p["kind"] == "actuator" else D.VERDICT["pass"] if p["kind"] == "bracket" else D.ALUMINIUM
        assert tuple(round(c, 2) for c in ob.ViewObject.ShapeColor[:3]) == tuple(round(c, 2) for c in want), p["name"]
    b = json.loads((case / "out" / "bom.json").read_text(encoding="utf-8"))
    assert r["bom_rows"] == len(b["purchased"]) + len(b["made"]) + len(b["fasteners"])
    assert r["sheet"].get("D2") == "XM540-W270"


def test_place_refuses_a_part_list_that_does_not_match(gui, doc, case, tmp_path):
    from freecad_addon.fc import robot_doc as D

    shutil.copytree(case / "out", tmp_path / "out")
    p = tmp_path / "out" / "cad" / "cad-result.json"
    cad = json.loads(p.read_text(encoding="utf-8"))
    cad["parts"][4]["cog_mm"] = [500.0, 500.0, 500.0]
    p.write_text(json.dumps(cad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(D.PlaceError, match="认不出"):
        D.place(doc, tmp_path)


def test_place_tolerates_the_kernel_volume_spread(gui, doc, case, tmp_path):
    """2026-11-26 问渠 CAD 1.1.4（OCCT 7.8.1）读回的自制件体积小 0.81%、重心偏 0.053 mm，原来的容差认不出 j1 舵盘法兰"""
    from freecad_addon.fc import robot_doc as D

    shutil.copytree(case / "out", tmp_path / "out")
    p = tmp_path / "out" / "cad" / "cad-result.json"
    cad = json.loads(p.read_text(encoding="utf-8"))
    for q in cad["parts"]:
        if q.get("volume_mm3"):
            q["volume_mm3"] = q["volume_mm3"] / (1 - 0.0081)
            q["cog_mm"] = [q["cog_mm"][0] + 0.053, *q["cog_mm"][1:]]
    p.write_text(json.dumps(cad, ensure_ascii=False), encoding="utf-8")
    r = D.place(doc, tmp_path)
    assert list(r["objects"]) == [q["name"] for q in cad["parts"]]


def test_panel_closes_the_empty_document_when_placing_fails(gui, case, lib, tmp_path):
    import FreeCAD

    from freecad_addon.gui.robot_design_panel import RobotDesignPanel

    shutil.copytree(case / "out", tmp_path / "out")
    p = tmp_path / "out" / "cad" / "cad-result.json"
    cad = json.loads(p.read_text(encoding="utf-8"))
    cad["parts"][4]["cog_mm"] = [500.0, 500.0, 500.0]
    p.write_text(json.dumps(cad, ensure_ascii=False), encoding="utf-8")
    before = set(FreeCAD.listDocuments())
    panel = RobotDesignPanel(lib, None, client_factory=lambda: None, fea_log=tmp_path / "fea.json")
    panel.done(_run_out(tmp_path))
    assert set(FreeCAD.listDocuments()) == before
    assert "认不出" in panel.model_info.text()


def test_panel_makes_the_new_result_the_active_document(gui, case, lib, tmp_path):
    import FreeCAD

    from freecad_addon.gui.robot_design_panel import RobotDesignPanel

    FreeCAD.newDocument("Older")
    panel = RobotDesignPanel(lib, None, client_factory=lambda: None, fea_log=tmp_path / "fea.json")
    panel.done(_run_out(case))
    assert panel.placed is not None
    assert FreeCAD.ActiveDocument.Name.startswith("AiRobot")
    FreeCAD.closeDocument("Older")


def test_panel_shows_steps_tabs_places_and_confirms(gui, case, lib, tmp_path):
    from freecad_addon.gui.robot_design_panel import RobotDesignPanel
    from kb.enterprise import EnterpriseLibrary

    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    p = RobotDesignPanel(lib, ent, client_factory=lambda: None, fea_log=tmp_path / "fea.json")
    p.load_example()
    assert "0.5 kg" in p.text.toPlainText()
    p.done(_run_out(case))
    assert all(s in p.steps.toPlainText() for s in C.STEPS)
    assert "整机方案" in p.views["构型"].toPlainText() and "支架强度有限元" in p.views["仿真"].toPlainText()
    assert p.placed is not None and len(p.placed["objects"]) == 20 and p.ok.isEnabled()
    p.drawing_no.setText("TA-000")
    p.vendor.setText("问渠（演示）")
    p.by.setText("张工")
    p.confirm()
    assert any("report.md" in d.get("title", "") for d in ent.documents()) and not p.ok.isEnabled()


def test_replayed_example_is_not_added_to_the_library(gui, case, lib, tmp_path):
    from freecad_addon.gui.robot_design_panel import RobotDesignPanel
    from kb.enterprise import EnterpriseLibrary

    p = RobotDesignPanel(lib, EnterpriseLibrary(tmp_path / "ent", create=True), client_factory=lambda: None)
    p.done(_run_out(case, replay=True))
    assert not p.ok.isEnabled() and "回放" in p.progress.text()


def test_start_replays_only_the_exact_example(gui, lib, monkeypatch):
    from freecad_addon.gui import robot_design_panel as P

    seen = {}
    monkeypatch.setattr(P, "_in_background", lambda work, done: seen.setdefault("work", work))
    monkeypatch.setattr(C, "run", lambda statement, client, **kw: seen.update(statement=statement, client=client, **kw))
    p = P.RobotDesignPanel(lib, None, client_factory=lambda: "live")
    p.load_example()
    p.do_fea.setChecked(False)
    p.start()
    seen.pop("work")()
    assert seen["replay"] and seen["statement"] == C.example_text() and seen["client"] != "live" and seen["do_fea"] is False
    p.text.setPlainText(C.example_text().replace("0.5", "0.6"))
    p.start()
    seen.pop("work")()
    assert not seen["replay"] and seen["client"] == "live"


def test_start_without_a_key_says_why(gui, lib, monkeypatch):
    from freecad_addon.gui import robot_design_panel as P

    monkeypatch.setattr(P, "_in_background", lambda work, done: pytest.fail("不该开始"))

    def no_key():
        raise RuntimeError("没有 ANTHROPIC_API_KEY")

    p = P.RobotDesignPanel(lib, None, client_factory=no_key)
    p.text.setPlainText("一台三轴臂")
    p.start()
    assert "没有开始" in p.progress.text() and "载入示例" in p.progress.text() and p.go.isEnabled()


def test_steps_table_and_progress_update_while_running(gui, lib, monkeypatch):
    from freecad_addon.gui import robot_design_panel as P

    monkeypatch.setattr(P, "_in_background", lambda work, done: None)
    p = P.RobotDesignPanel(lib, None, client_factory=lambda: None)
    p.text.setPlainText("x")
    p.start()
    table = [{"step": s, "who": "代码", "status": "waiting", "seconds": None, "note": ""} for s in C.STEPS]
    table[4]["status"] = "running"
    p._status = (table, "支架有限元：j2 U 形支架", 2, 10)
    p._tick()
    assert "进行中" in p.steps.toPlainText() and "j2 U 形支架" in p.progress.text() and "3 / 10" in p.progress.text()
    assert p.bar.maximum() == 10 and p.bar.value() == 2 and not p.go.isEnabled()
    p.ticker.stop()


def test_command_and_tool_window(gui, lib):
    from PySide import QtCore, QtWidgets

    from freecad_addon.gui import robot_design_panel as P

    r = P.RobotDesignCommand().GetResources()
    assert r["MenuText"] and r["ToolTip"]
    P._LAST_PANEL = P._WIN = None
    p = P.open_panel(lib, None)
    win = P._WIN
    assert win.isVisible() and win.objectName() == "FapRobotDesignPanel" and win.windowFlags() & QtCore.Qt.Tool
    assert not isinstance(win, QtWidgets.QDockWidget) and P.open_panel(lib, None) is p
    win.close()


# ---------------------------------------------------------------- 案例 B（龙门取放，ADR-0115 44.5.5 第三步之二）
@pytest.fixture(scope="module")
def gcase(tmp_path_factory):
    """案例 B 的结果目录；装配 STEP 由三维装配按案例的方案与选件重出（不做有限元，用保存的结果）"""
    pytest.importorskip("gmsh")
    pytest.importorskip("mujoco")
    from assist import gantry_cad

    d = tmp_path_factory.mktemp("gantry")
    shutil.copytree(C.GANTRY_CASE / "out", d / "out")
    o = d / "out"
    cr = json.loads((o / "concept-result.json").read_text(encoding="utf-8"))
    br = json.loads((o / "build-result.json").read_text(encoding="utf-8"))
    gantry_cad.run(cr, br, o, fea=False)                    # 只为写 cad/assembly.step
    return d


def test_place_gantry_names_colours_and_bom(gui, doc, gcase):
    from freecad_addon.fc import robot_doc as D

    res = json.loads((gcase / "out" / "cad-result.json").read_text(encoding="utf-8"))
    parts = res["cad"]["parts"]
    r = D.place(doc, gcase, "gantry")
    assert list(r["objects"]) == [p["name"] for p in parts] and len(parts) == 10
    for p in parts:
        ob = r["objects"][p["name"]]
        want = D.GREY if p["kind"] in ("module", "gripper") else D.VERDICT["pass"] if p["kind"] == "frame" else D.ALUMINIUM
        assert tuple(round(c, 2) for c in ob.ViewObject.ShapeColor[:3]) == tuple(round(c, 2) for c in want), p["name"]
    b = json.loads((gcase / "out" / "bom.json").read_text(encoding="utf-8"))
    assert r["bom_rows"] == len(b["purchased"]) + len(b["made"]) == 10
    assert r["sheet"].get("D2") == "EGC-80-TB-KF-GK"


def test_panel_gantry_example(gui, gcase, lib, tmp_path):
    from freecad_addon.gui.robot_design_panel import RobotDesignPanel

    p = RobotDesignPanel(lib, None, client_factory=lambda: None, fea_log=tmp_path / "fea.json")
    assert set(p.examples) == set(C.EXAMPLES)
    p.examples[C.GANTRY_NAME].click()
    assert "1500 mm" in p.text.toPlainText() and p.replay
    table = [{"step": s, "who": "代码", "status": "pass", "seconds": 1.0, "note": ""} for s in C.GANTRY_STEPS]
    p.done({"out_dir": str(gcase), "steps": table, "status": "pass", "stopped_at": None, "replay": True, "do_fea": True,
            "kind": "gantry"})
    assert all(s in p.steps.toPlainText() for s in C.GANTRY_STEPS)
    assert "节拍" in p.views["校核"].toPlainText() and "门架有限元" in p.views["仿真"].toPlainText()
    assert p.placed is not None and len(p.placed["objects"]) == 10 and not p.ok.isEnabled()
