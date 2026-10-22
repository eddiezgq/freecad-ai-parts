# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "freecad"))

import wq_cam_keyway  # noqa: E402
import wq_drawing  # noqa: E402
import wq_publish  # noqa: E402
import wq_shaft  # noqa: E402


def test_default_shaft_blank_matches_factory_bom():
    from factory import data as F
    assert wq_publish.blank_kg(wq_shaft.PARAMS) == dict(F.BOMS["SH-301"][1])["RM-45-D50"]


def test_keyway_gcode_stays_inside_slot_and_reaches_depth():
    g, info = wq_cam_keyway.generate(wq_shaft.PARAMS)
    pts = wq_cam_keyway.parse(g)
    cut = [p for p in pts if not p[3]]
    kw = wq_shaft.PARAMS["keyway"]
    assert min(p[2] for p in cut) == -kw["t"]
    xs = [p[0] for p in cut]
    # 刀心在槽两端各内缩半个刀径
    assert min(xs) - kw["b"] / 2 >= info["slot"]["x_from"] - 1e-9
    assert max(xs) + kw["b"] / 2 <= info["slot"]["x_to"] + 1e-9
    assert info["slot"]["x_to"] - info["slot"]["x_from"] == kw["L"]
    assert g.startswith("%") and "M30" in g


def test_shorter_keyway_changes_gcode_not_bom():
    p = {**wq_shaft.PARAMS, "keyway": dict(wq_shaft.PARAMS["keyway"], L=42.0)}
    _, info = wq_cam_keyway.generate(p)
    assert info["slot"]["x_to"] - info["slot"]["x_from"] == 42.0
    assert wq_publish.bom(p) == wq_publish.bom(wq_shaft.PARAMS)


def test_longer_shaft_needs_more_steel():
    p = dict(wq_shaft.PARAMS, segments=[(30, 60)] + list(wq_shaft.PARAMS["segments"][1:]))
    assert wq_publish.blank_kg(p) > wq_publish.blank_kg(wq_shaft.PARAMS)


def test_drawing_is_valid_svg_with_title_block():
    import xml.dom.minidom
    s = wq_drawing.svg(wq_shaft.PARAMS, revision=3, author="王小明")
    doc = xml.dom.minidom.parseString(s.encode("utf-8"))
    text = s
    assert doc.documentElement.tagName == "svg"
    assert "rev 3" in text and "王小明" in text and "总长 167" in text


def test_workbench_loads_the_way_freecad_runs_initgui(tmp_path, monkeypatch):
    """FreeCAD 执行 InitGui.py 时可能用分开的 globals / locals，Windows 上还没有 __file__（第 39 轮第 5 步复现）：
    照这样执行一遍，命令和工作台要注册上，按钮按文件夹里有的宏出现，点按钮能调到宏的 run_dialog()。"""
    import shutil
    import types
    mod = tmp_path / "Mod" / "WenQuest"
    mod.mkdir(parents=True)
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "freecad", "Mod", "WenQuest")
    for f in ("InitGui.py", "wq_workbench.py"):
        shutil.copy(os.path.join(src, f), mod / f)
    (mod / "wq_cam.py").write_text("CALLED = []\ndef run_dialog():\n    CALLED.append(1)\n", encoding="utf-8")
    reg = {"cmds": {}, "wb": []}

    class Workbench:
        def appendToolbar(self, name, cmds):
            reg["toolbar"] = list(cmds)

        def appendMenu(self, name, cmds):
            reg["menu"] = list(cmds)

    gui = types.SimpleNamespace(Workbench=Workbench, addCommand=lambda n, c: reg["cmds"].__setitem__(n, c),
                                addWorkbench=lambda w: reg["wb"].append(w))
    monkeypatch.setitem(sys.modules, "FreeCADGui", gui)
    monkeypatch.setitem(sys.modules, "FreeCAD", types.SimpleNamespace())
    for m in ("wq_workbench", "wq_cam"):
        monkeypatch.delitem(sys.modules, m, raising=False)
    monkeypatch.setattr(sys, "path", [str(mod)] + [p for p in sys.path])
    code = compile((mod / "InitGui.py").read_text(encoding="utf-8"), "InitGui.py", "exec")
    exec(code, {"__builtins__": __builtins__}, {})          # 分开的 globals / locals，没有 __file__
    assert list(reg["cmds"]) == ["WQ_Cam"] and len(reg["wb"]) == 1
    reg["wb"][0].Initialize()
    assert reg["toolbar"] == ["WQ_Cam"]
    reg["cmds"]["WQ_Cam"].Activated()
    assert sys.modules["wq_cam"].CALLED == [1]
