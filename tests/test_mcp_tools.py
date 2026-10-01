"""M4a #65：组件库接口与查询工具。"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from engine.golden import GOLDEN
from kb.library import JsonLibrary, KbLibrary, default_library
from mcp_server import tools
from mcp_server.server import create_server

FIXDIR = GOLDEN / "fixtures"
LIB = JsonLibrary(FIXDIR)


def test_json_library():
    assert LIB.get("test.servo_motor.test-vendor.m400")["model"] == "M400"
    assert LIB.get("nope") is None
    motors = LIB.all("servo_motor")
    assert motors and all(c["category"] == "servo_motor" for c in motors)
    assert [c["id"] for c in motors] == sorted(c["id"] for c in motors)
    with pytest.raises(FileNotFoundError):
        JsonLibrary(FIXDIR / "missing")


def test_json_library_duplicate(tmp_path):
    comp = LIB.get("test.servo_motor.test-vendor.m400")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.json").write_text(json.dumps(comp), encoding="utf-8")
    (tmp_path / "y.json").write_text(json.dumps(comp), encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        JsonLibrary(tmp_path)


def test_default_library(monkeypatch):
    monkeypatch.setenv("FAP_LIBRARY", str(FIXDIR))
    assert isinstance(default_library(), JsonLibrary)
    monkeypatch.delenv("FAP_LIBRARY")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        default_library()


def test_search_filters():
    r = tools.search_components(LIB, category="servo_motor", params={"rated_torque_nm": {"min": 1.0}})
    ids = [c["id"] for c in r["components"]]
    assert "test.servo_motor.test-vendor.m400" in ids and "test.servo_motor.test-vendor.m200" not in ids
    assert r["excluded_missing"] == 1  # m400-no-rated-torque 缺该参数
    assert all(c["key_params"]["rated_torque_nm"]["value"] >= 1.0 for c in r["components"])
    r = tools.search_components(LIB, category="servo_motor", params={"ports/shaft/diameter_mm": {"max": 11}})
    assert {c["id"] for c in r["components"]} == {"test.servo_motor.test-vendor.m200",
                                                 "test.servo_motor.test-vendor.m200-hipeak"}
    r = tools.search_components(LIB, text="m400 proprietary")
    assert [c["id"] for c in r["components"]] == ["test.servo_motor.test-vendor.m400-proprietary-enc"]
    assert tools.search_components(LIB, vendor="TEST VENDOR", category="drive")["total"] >= 3
    r = tools.search_components(LIB, limit=2)
    assert len(r["components"]) == 2 and r["truncated"] is True


def test_search_range_param_requires_whole_range():
    comp = json.loads(json.dumps(LIB.get("test.drive.test-vendor.d400")))
    lib = JsonLibrary(FIXDIR)
    lib._comps["test.drive.test-vendor.d400"] = comp
    r = tools.search_components(lib, category="drive", params={"ports/power_in/voltage_v": {"min": 210}})
    assert "test.drive.test-vendor.d400" not in [c["id"] for c in r["components"]]  # 200–240 不全在 ≥ 210 内


@pytest.mark.parametrize(("kw", "msg"), [
    ({"category": "robot"}, "未知品类"),
    ({"params": {"rated_torque_nm": {"min": 1}}}, "须指定品类"),
    ({"category": "servo_motor", "params": {"torque": {"min": 1}}}, "没有参数"),
    ({"category": "servo_motor", "params": {"rated_torque_nm": {"min": 2, "max": 1}}}, "大于"),
    ({"category": "servo_motor", "params": {"rated_torque_nm": {"min": "a"}}}, "数字"),
    ({"category": "servo_motor", "params": {"rated_torque_nm": {"low": 1}}}, "min, max"),
    ({"category": "servo_motor", "params": {"ip_rating": {"min": 1}}}, "不是数值"),
    ({"category": "servo_motor", "params": {"dims/square_mm": {"min": 1}}}, "没有参数"),
    ({"limit": 0}, "limit"),
])
def test_search_errors(kw, msg):
    with pytest.raises(tools.ToolInputError, match=msg):
        tools.search_components(LIB, **kw)


def test_get_component():
    assert tools.get_component(LIB, "test.reducer.test-vendor.r20-100")["category"] == "reducer"
    with pytest.raises(tools.ToolInputError):
        tools.get_component(LIB, "nope")


def _call(name, args):
    async def run():
        async with Client(create_server(lambda: LIB)) as client:
            return (await client.call_tool(name, args)).data
    return asyncio.run(run())


def test_mcp_tools_roundtrip():
    r = _call("search_components", {"category": "reducer", "params": {"ratio": {"min": 100, "max": 100}}})
    assert r["total"] == len([c for c in LIB.all("reducer")])
    assert _call("get_component", {"component_id": "test.drive.test-vendor.d400"})["id"] == "test.drive.test-vendor.d400"
    with pytest.raises(ToolError, match="组件不存在"):
        _call("get_component", {"component_id": "nope"})


def test_kb_library(db):
    from kb.sources import SourceRegistry
    from kb.store import import_component

    for cid in ("test.servo_motor.test-vendor.m400", "test.reducer.test-vendor.r20-100"):
        import_component(db, LIB.get(cid), registry=SourceRegistry.load(), changed_by="t", allow_test=True)
    kb = KbLibrary(db)
    assert kb.get("test.servo_motor.test-vendor.m400") == LIB.get("test.servo_motor.test-vendor.m400")
    assert [c["id"] for c in kb.all("reducer")] == ["test.reducer.test-vendor.r20-100"]
    r = tools.search_components(kb, category="servo_motor", params={"rated_torque_nm": {"min": 1}})
    assert r["total"] == 1
