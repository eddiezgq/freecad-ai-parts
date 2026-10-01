"""M4b #88：agent 布局流程（joint_layout 提示与 layout_demo 演示脚本）。"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastmcp import Client

from engine.golden import GOLDEN
from freecad_addon.core.geometry import bbox
from freecad_addon.core.scene import Scene
from kb.library import JsonLibrary
from mcp_server import layout_demo
from mcp_server.server import create_server

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "joint2-requirement.json"


class AabbBackend:
    """假后端：不同刚性组之间按包围盒重叠判干涉（足以检验演示的消除干涉流程）。"""

    def call(self, method, params=None):
        scene = Scene.from_dict(params["scene"])
        if method == "snapshot":
            return {"view": params["view"], "width": params["width"], "height": params["height"],
                    "png_base64": "iVBORw0KGgo="}
        names = sorted(scene.instances)
        boxes = {n: bbox(scene.component(n), scene.pose(n)) for n in names}
        hits = []
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if b in scene.group(a):
                    continue
                lo = [max(boxes[a]["min_mm"][k], boxes[b]["min_mm"][k]) for k in range(3)]
                hi = [min(boxes[a]["max_mm"][k], boxes[b]["max_mm"][k]) for k in range(3)]
                if all(h > lo_ for lo_, h in zip(lo, hi, strict=True)):
                    vol = (hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])
                    hits.append({"a": a, "b": b, "volume_mm3": vol, "connected": False, "same_group": False})
        return {"ok": not hits, "interferences": hits, "pass_through": [], "threshold_mm3": 1.0, "instances": names}

    def close(self):
        pass


@pytest.fixture(autouse=True)
def golden_library(monkeypatch):
    monkeypatch.delenv("FAP_LIBRARY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_prompt_lists_layout_workflow():
    async def run():
        async with Client(create_server(lambda: JsonLibrary(GOLDEN / "fixtures"), lambda: None)) as c:
            return await c.get_prompt("joint_layout", {"system": '{"id": "x"}'})

    text = asyncio.run(run()).messages[0].content.text
    for word in ("place_component", "connect_ports", "check_interference", "bbox_mm", "pass_through", "snapshot",
                 "use_layout"):
        assert word in text


def test_demo_resolves_interference_with_aabb_backend():
    req = __import__("json").loads(EXAMPLE.read_text(encoding="utf-8"))
    out = asyncio.run(layout_demo.run(req, backend_factory=AabbBackend))
    assert [r["ok"] for r in out["rounds"]] == [False, True]
    assert {h["a"] for h in out["rounds"][0]["interferences"]} | {
        h["b"] for h in out["rounds"][0]["interferences"]} >= {"drive"}
    moved = [s for s in out["steps"] if s["tool"] == "place_component" and "position_mm" in s["args"]]
    assert [m["args"]["instance"] for m in moved] == ["drive"]
    drive = next(i for i in out["layout"]["instances"] if i["instance"] == "drive")
    others = [i for i in out["layout"]["instances"] if i["instance"] != "drive"]
    assert drive["bbox_mm"]["min_mm"][0] == pytest.approx(max(o["bbox_mm"]["max_mm"][0] for o in others) + 20)
    assert out["verified"]["report"]["overall"] in ("pass", "warn")
    assert out["urdf"]["content"].startswith("<?xml") and out["snapshot_png"].startswith(b"\x89PNG")
    assert any("插入深度未知" in n for n in out["notes"])


def test_resolve_moves_rules():
    layout = {"instances": [
        {"instance": "a", "group": ["a", "b"], "position_mm": [0, 0, 0], "rotation": {"axis": [0, 0, 1], "angle_deg": 0},
         "bbox_mm": {"min_mm": [-10, -10, 0], "max_mm": [10, 10, 50]}},
        {"instance": "b", "group": ["a", "b"], "position_mm": [0, 0, 0], "rotation": {"axis": [0, 0, 1], "angle_deg": 0},
         "bbox_mm": {"min_mm": [-30, -30, 50], "max_mm": [30, 30, 80]}},
        {"instance": "d", "group": ["d"], "position_mm": [5, 1, 2], "rotation": {"axis": [1, 0, 0], "angle_deg": 90},
         "bbox_mm": {"min_mm": [-15, -40, 0], "max_mm": [25, 40, 100]}},
    ]}
    hits = [{"a": "a", "b": "d", "same_group": False}, {"a": "b", "b": "d", "same_group": False}]
    moves, stuck = layout_demo._resolve_moves(layout, hits, 20)
    # d 单独成组，移动 d（只移一次）：最小 x 移到 30 + 20 = 50，即平移 65
    assert moves == [{"instance": "d", "position_mm": [70, 1, 2], "rotation_axis": [1, 0, 0], "rotation_deg": 90}]
    assert stuck == []
    moves, stuck = layout_demo._resolve_moves(layout, [{"a": "a", "b": "b", "same_group": True}], 20)
    assert moves == [] and len(stuck) == 1


def test_demo_without_freecad(capsys, tmp_path, monkeypatch):
    monkeypatch.delenv("FAP_FREECAD", raising=False)
    assert layout_demo.main([str(EXAMPLE), "--out", str(tmp_path)]) == 2
    out = capsys.readouterr().out
    assert "跳过干涉检查与截图" in out and "<系统 candidate-1>" in out
    assert (tmp_path / "candidate-1.urdf").exists() and not (tmp_path / "layout-iso.png").exists()


@pytest.mark.freecad
def test_demo_with_real_freecad(capsys, tmp_path, monkeypatch):
    """M4b 验收的离线复现：真实 FreeCAD 中完成布局、消除干涉、截图。"""
    if "FreeCAD" in sys.modules or os.environ.get("FAP_REQUIRE_FREECAD") == "1":
        monkeypatch.setenv("FAP_FREECAD_PYTHON", os.environ.get("FAP_FREECAD_PYTHON", sys.executable))
    monkeypatch.setenv("FAP_FREECAD", "headless")
    assert layout_demo.main([str(EXAMPLE), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "第 1 轮：有干涉" in out and "第 2 轮：通过" in out and "需有通孔：plate" in out
    png = (tmp_path / "layout-iso.png").read_bytes()
    assert png[:4] == b"\x89PNG" and len(png) > 5000
