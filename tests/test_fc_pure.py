"""不需要 FreeCAD 的部分：轴的穿过通道（ADR-0033）、worker 客户端的启动配置与错误。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from freecad_addon.core.corridors import corridors
from freecad_addon.core.system_layout import layout_system
from freecad_addon.fc import client
from kb.library import JsonLibrary

ROOT = Path(__file__).resolve().parent.parent
LIB = JsonLibrary(ROOT / "tests/golden/fixtures")


def _scene(case: str):
    system = yaml.safe_load((ROOT / f"tests/golden/valid/{case}.yaml").read_text(encoding="utf-8"))["system"]
    return layout_system(system, LIB.get)[0]


def test_corridor_through_adapter_plate():
    cs = corridors(_scene("m200-adapters-r25-d400"))
    assert len(cs) == 1
    c = cs[0]
    assert (c.male, c.female, c.diameter) == ("motor.shaft", "sleeve.inner", 11.0)
    # 轴伸段 z 0–30；套筒孔口在轴端（插入深度未知，按 0），故通道为 z 0–30
    assert c.start == pytest.approx((0, 0, 0)) and c.end == pytest.approx((0, 0, 30))


def test_no_corridor_when_shaft_fully_inside_bore():
    # 电机轴直接插入减速器孔：孔口在电机法兰面（z=0），即轴伸段起点，没有穿过段
    assert corridors(_scene("m400-r20-d400")) == []


def test_worker_command_missing_python(monkeypatch, tmp_path):
    monkeypatch.setenv("FAP_FREECAD_PYTHON", str(tmp_path / "nope/python"))
    with pytest.raises(client.WorkerError) as exc:
        client.worker_command()
    assert exc.value.kind == "unavailable" and "fetch_freecad" in str(exc.value)


def test_worker_command_layout(monkeypatch, tmp_path):
    py = tmp_path / "usr/bin/python"
    py.parent.mkdir(parents=True)
    py.write_text("")
    (tmp_path / "usr/lib").mkdir()
    monkeypatch.setenv("FAP_FREECAD_PYTHON", str(py))
    monkeypatch.delenv("FAP_FREECAD_LIB", raising=False)
    with pytest.raises(client.WorkerError, match="FAP_FREECAD_LIB"):
        client.worker_command()
    (tmp_path / "usr/lib/FreeCAD.so").write_text("")
    monkeypatch.setenv("DISPLAY", ":9")
    cmd, env = client.worker_command()
    assert cmd == [str(py), "-m", "freecad_addon.fc.worker"]
    parts = env["PYTHONPATH"].split(":")
    assert parts[:2] == [str(tmp_path / "usr/lib"), str(client.REPO_ROOT)]
    monkeypatch.setattr(client.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY")
    monkeypatch.setattr(client.shutil, "which", lambda name: "/usr/bin/xvfb-run")
    cmd, _ = client.worker_command()
    assert cmd[:2] == ["xvfb-run", "-a"] and cmd[-1] == "freecad_addon.fc.worker"


def test_worker_unavailable_raises_on_call(monkeypatch, tmp_path):
    monkeypatch.setenv("FAP_FREECAD_PYTHON", str(tmp_path / "missing"))
    with pytest.raises(client.WorkerError) as exc:
        client.HeadlessWorker().call("ping")
    assert exc.value.kind == "unavailable"


def test_pass_through_volume_reference():
    # ADR-0033 中引用的数值：直径 11 的轴穿过 10 mm 厚的板
    assert math.pi * 5.5**2 * 10 == pytest.approx(950.33, abs=0.01)
