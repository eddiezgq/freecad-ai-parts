"""问渠CAM C4b 双主轴（ADR-0106 C4b-1、ADR-0121）：副主轴夹住车好的右端、切断、背面车左端，一个程序；
夹持位置手算核对、交接程序行的顺序、回读与两段仿真一致；副主轴一侧整机仿真（C4b-2）做完前不出正式程序。示例机床 EX-MT-TS（虚构）。"""

from __future__ import annotations

import json

import pytest

from analysis import cam
from tests.verification import record_verdict

# 左 Ø30×30、中 Ø44×20（最大直径段）、右 Ø36×30，两端 C1：右端圆柱段 29 mm 长（去掉 1 mm 倒角）
PART = {"mode": "turn", "machine": "EX-MT-TS", "segments": [[30, 30], [44, 20], [36, 30]], "chamfer_mm": 1, "stock_d_mm": 50,
        "parting": {"tool_w": 3}, "machine_sim": {"tools": {"1": {"tool": "TR-CNMG"}, "2": {"tool": "TR-VNMG"}}, "work_offset_mm": [0, 0, 95]}}
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


def test_program_reads_back_but_waits_for_c4b2(tmp_path, monkeypatch):
    """配置齐了：合成的程序回读与两段仿真刀路一致；副主轴一侧整机仿真没做，正式程序不出，写明原因"""
    _post(tmp_path, monkeypatch)
    p = _run({**PART, "post": "tw"})
    assert p[0]["twin"]["readback"] == "ok"
    assert p[0]["release"] is None and any("C4b-2" in e for e in _errors(p[0])), _errors(p[0])


@pytest.mark.parametrize("family,cycles", [("fanuc", False), ("fanuc", True), ("siemens", False)])
def test_transfer_sequence(tmp_path, monkeypatch, family, cycles):
    """放开以后：右端工序 → 同步 → 副主轴接近、进给夹持 → 夹紧 → 切断 → 副主轴退回 → 停同步 → 切到副主轴、G55 → 左端（Z 反向、不用固定循环）
    → 松开、切回主主轴；回读一致"""
    _post(tmp_path, monkeypatch, family)
    monkeypatch.setattr(cam, "TWIN_RELEASE", True)
    p = _run({**PART, "post": "tw", "cycles": cycles})
    assert p[0]["release"] is not None, _errors(p[0])
    t = p[0]["release"]["text"]
    sie = family == "siemens"
    seq = ["M210", "B-433.0", "B-435.0", "M220", "T8 D1" if sie else "T0808", "B0.0", "M211",
           "SETMS(2)" if sie else "G14", "G55", "M221", "SETMS(1)" if sie else "G15"]
    at = [t.index(s) for s in seq]
    assert at == sorted(at), list(zip(seq, at, strict=True))
    sub = t[t.index("G55"):]
    assert "G71" not in sub and ("G71" in t) == (cycles and not sie)
    assert "X250.0 Z-150.0" in sub                        # 副主轴一侧的换刀点 Z 反向
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
