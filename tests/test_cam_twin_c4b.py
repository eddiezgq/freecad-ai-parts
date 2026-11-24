"""问渠CAM C4b 双主轴（ADR-0106 C4b-1、C4b-2，ADR-0121）：副主轴夹住车好的右端、切断、背面车左端，一个程序；
夹持位置手算核对、交接程序行的顺序、回读与两段仿真一致；背面加工用朝副主轴的刀，整机仿真按 Z 镜像的机床算；交接时的碰撞。示例机床 EX-MT-TS（虚构）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis import cam
from tests.verification import record_verdict

# 左 Ø30×30、中 Ø44×20（最大直径段）、右 Ø36×30，两端 C1：右端圆柱段 29 mm 长（去掉 1 mm 倒角）
PART = {"mode": "turn", "machine": "EX-MT-TS", "segments": [[30, 30], [44, 20], [36, 30]], "chamfer_mm": 1, "stock_d_mm": 50,
        "parting": {"tool_w": 3}, "back_tools": {"1": 11, "2": 12},
        "machine_sim": {"tools": {"1": {"tool": "TR-CNMG"}, "2": {"tool": "TR-VNMG"}, "8": {"tool": "GR3"},
                                  "11": {"tool": "TR-CNMG"}, "12": {"tool": "TR-VNMG"}}, "work_offset_mm": [0, 0, 95]}}
TWIN = {"sync_on": ["M210"], "sync_off": ["M211"], "sub_clamp": ["M220"], "sub_unclamp": ["M221"],
        "sub_select": ["G14"], "main_select": ["G15"], "sub_offset": ["G55"]}


def _post(tmp_path, monkeypatch, family="fanuc", twin=None):
    d = tmp_path / "posts"
    d.mkdir()
    tw = dict(TWIN if twin is None else twin)
    if family == "siemens" and twin is None:
        tw.update({"sub_select": ["SETMS(2)"], "main_select": ["SETMS(1)"]})
    (d / "tw.json").write_text(json.dumps({"format": "cam-post/1", "id": "tw", "name": "twin", "family": family, "kinds": ["lathe"],
                                           "source": "测试", "twin": tw}), encoding="utf-8")
    monkeypatch.setenv("FAP_POSTS", str(d))


def _run(setup):
    r = cam.run(setup)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"]


def _errors(p):
    return [c["text"] for c in p["checks"] if c["level"] == "error"]


def test_grip_position_by_hand():
    """夹右端 Ø36 圆柱段：长 30 − 倒角 1 = 29 mm，在 grip_mm [10, 30] 内取 29；夹爪端面在零件 Z−30，机床 Z = 95 − 30 = 65，
    副主轴 B = 65 − 500 = −435，接近点再退 2 mm；退回 B0 后左端面（副主轴工件零点）在机床 Z 95 + 435 − 80 = 450"""
    p = _run(PART)
    tw = p[0]["twin"]
    assert (tw["d"], tw["grip_len"], tw["grip"], tw["approach"], tw["home"], tw["z0"]) == (36.0, 29.0, -435.0, -433.0, 0.0, 450.0)
    assert p[1]["title"] == "左端（副主轴背面加工）" and p[1]["twin_of"] == p[0]["number"]
    record_verdict(("双主轴：副主轴夹持位置与手算一致", "twin spindle: sub-spindle grip position matches hand calculation"), "pass", "pass")


def test_back_tools_required(tmp_path, monkeypatch):
    """背面加工没写 back_tools：报错点名缺的刀号，不出程序"""
    _post(tmp_path, monkeypatch)
    p = _run({**PART, "post": "tw", "back_tools": None})
    assert any("back_tools" in e and "T1" in e and "T2" in e for e in _errors(p[1])), _errors(p[1])
    assert p[0]["release"] is None


def test_mirrored_machine_by_hand():
    """Z 镜像：刀具 Z 行程 [−500, 700] → [−700, 500]（X 不变）；副主轴停在夹持位置 B −435：卡盘 Z 500 ~ 580 → 65 ~ 145 → 镜像 −65 ~ −145"""
    from analysis.cam import machine_model as MM
    from analysis.cam import machines

    m = MM.mirror_z(MM.main_model(machines.model("EX-MT-TS"), -435.0))
    z = next(a for a in m["axes"] if a["id"] == "Z")
    x = next(a for a in m["axes"] if a["id"] == "X")
    assert (z["min"], z["max"], x["min"], x["max"]) == (-700.0, 500.0, -5.0, 400.0)
    cy = next(c for c in m["components"] if c["id"] == "sub_chuck")["cylinder_mm"]
    assert (cy["p0"][2], cy["p1"][2]) == (-65.0, -145.0)
    record_verdict(("双主轴：背面整机仿真的镜像机床与手算一致", "twin spindle: mirrored machine for back working matches hand calculation"), "pass", "pass")


@pytest.mark.parametrize("family,cycles", [("fanuc", False), ("fanuc", True), ("siemens", False)])
def test_transfer_sequence(tmp_path, monkeypatch, family, cycles):
    """整机仿真（含背面镜像、交接）通过，出程序：右端工序 → 同步 → 副主轴接近、进给夹持 → 夹紧 → 切断 → 副主轴退回 → 停同步 → 切到副主轴、G55 → 左端（Z 反向、不用固定循环）
    → 松开、切回主主轴；回读一致"""
    _post(tmp_path, monkeypatch, family)
    p = _run({**PART, "post": "tw", "cycles": cycles})
    assert p[0]["release"] is not None, _errors(p[0])
    t = p[0]["release"]["text"]
    sie = family == "siemens"
    seq = ["M210", "B-433.0", "B-435.0", "M220", "T8 D1" if sie else "T0808", "Z-80.0", "X54.0", "B0.0", "M211",
           "SETMS(2)" if sie else "G14", "G55", "M221", "SETMS(1)" if sie else "G15"]
    pos = 0
    for s_ in seq:                                         # 依次往后找：每一项都在前一项之后
        pos = t.find(s_, pos)
        assert pos >= 0, (s_, seq)
    assert t.index("M210") > t.index("T0202" if not sie else "T2 D1")   # 接料在右端车完之后
    sub = t[t.index("G55"):]
    assert "G71" not in sub and ("G71" in t) == (cycles and not sie)
    assert "X250.0 Z-150.0" in sub                        # 副主轴一侧的换刀点 Z 反向
    assert ("T11 D1" in sub and "T12 D1" in sub) if sie else ("T1111" in sub and "T1212" in sub)   # 背面用朝副主轴的刀
    assert p[1]["machine_sim"]["status"] in ("pass", "unknown")
    record_verdict((f"双主轴：{family} 交接程序行按顺序、回读一致", f"twin spindle: {family} transfer sequence in order, read-back matches"), "pass", "pass")


def test_missing_twin_lines_named(tmp_path, monkeypatch):
    _post(tmp_path, monkeypatch, twin={k: v for k, v in TWIN.items() if k != "sub_offset"})
    p = _run({**PART, "post": "tw"})
    assert p[0]["release"] is None and any("twin 没写 sub_offset" in e for e in _errors(p[0])), _errors(p[0])


@pytest.mark.parametrize("extra,msg", [
    ({"segments": [[30, 30], [44, 40], [36, 8]]}, "副主轴夹不住"),              # 右端圆柱段 7 mm < 最短 10 mm
    ({"machine_sim": {**PART["machine_sim"], "work_offset_mm": [0, 0, 10]}}, "超出行程"),   # B = 10 − 30 − 500 = −520 < −480
    ({"grooves": [{"z": -10, "width": 4, "d": 32}]}, "有槽")])
def test_cannot_pick_up(extra, msg):
    r = cam.run({**PART, **extra})
    assert r["status"] != "ok" and any(msg in m for m in r["messages"]), r["messages"]


def test_without_parting_or_sub_spindle_unchanged():
    """不切断的毛坯：照旧两次装夹；没有副主轴的机床：结果与原来一样"""
    p = _run({k: v for k, v in PART.items() if k != "parting"})
    assert len(p) == 2 and "twin" not in p[0] and p[1]["title"] == "左端（调头装夹）"
    a = _run({**PART, "machine": "EX-MT-CY"})
    assert "twin" not in a[0] and "twin_of" not in a[1] and a[1]["title"] == "左端（调头装夹）"


@pytest.mark.parametrize("change,where", [
    ({"r": 130}, "副主轴过来接料"),                          # 卡盘半径 130 > 换刀点刀尖半径 125：副主轴过来时扫到刀
    ({"p0": [0, 0, 448], "r": 30}, "切断时副主轴夹着工件"),   # 卡盘前端伸出 52 mm，到 Z−82：挡住切断刀
    ({"p0": [0, 0, 452], "r": 30}, "")])                     # 伸出 48 mm：切断够得着，背面加工时刀碰到卡盘
def test_collisions_found(tmp_path, monkeypatch, change, where):
    d = tmp_path / "machines"
    d.mkdir()
    m = json.loads((Path(cam.__file__).parent / "machines" / "EX-MT-TS.json").read_text(encoding="utf-8"))
    m["components"][-1]["cylinder_mm"].update(change)
    (d / "EX-MT-TS.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("FAP_MACHINES", str(d))
    p = _run(PART)
    if where:
        assert any(e.startswith(where) and "副主轴卡盘" in e for e in _errors(p[0])), _errors(p[0])
    else:
        assert p[1]["machine_sim"]["status"] == "error" and any("副主轴卡盘" in e for e in _errors(p[1])), _errors(p[1])
