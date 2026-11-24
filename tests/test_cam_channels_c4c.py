"""问渠CAM C4c 多通道（ADR-0106 C4c-2，ADR-0122）：双主轴 + 上下两个刀架，通道 1 车右端、通道 2 在副主轴上车背面，同时干、等待点同步。
两条程序等待号成对、顺序对，各自回读一致；节拍 = max(右端, 背面) + 交接，手算核对、比一个刀架干短；时间线查出下刀架碰主主轴一侧。
示例机床 EX-MT-TT（虚构）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis import cam
from tests.test_cam_twin_c4b import PART as PART_TS
from tests.test_cam_twin_c4b import TWIN
from tests.verification import record_verdict

PART = {**PART_TS, "machine": "EX-MT-TT"}
CH = {"fanuc": {"wait": "M{n}", "wait_first": 100}, "siemens": {"wait": "WAITM({n},1,2)", "wait_first": 1}}


def _post(tmp_path, monkeypatch, family="fanuc", channels=True):
    d = tmp_path / "posts"
    d.mkdir()
    cfg = {"format": "cam-post/1", "id": "tw", "name": "twin", "family": family, "kinds": ["lathe"], "source": "测试", "twin": TWIN}
    if channels:
        cfg["channels"] = CH[family]
    (d / "tw.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("FAP_POSTS", str(d))


def _run(setup):
    r = cam.run(setup)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"]


def _errors(p):
    return [c["text"] for c in p["checks"] if c["level"] == "error"]


def _after(text, items):
    pos = 0
    for s_ in items:                                       # 依次往后找：每一项都在前一项之后
        pos = text.find(s_, pos)
        assert pos >= 0, (s_, items)
        pos += len(s_)


def test_channel_view_by_hand():
    """通道 2（下刀架，X2 朝 −X）单独看：轴改名 X、Z，整台机床绕 Z 转 180°——刀具朝向 [−1,0,0] → [1,0,0]、下刀架部件 X −260 ~ −120 → 120 ~ 260；
    上刀架和它的部件拿掉；主轴参数换成副主轴的（5000 r/min、11 kW）。通道 1 的视图与 EX-MT-TS 一样多一个上刀架"""
    from analysis.cam import machine_model as MM
    from analysis.cam import machines

    raw = machines.model("EX-MT-TT")
    v = MM.channel_model(raw, 2)
    assert [a["id"] for a in v["axes"]] == ["X", "Z", "B", "C"]
    assert next(a for a in v["axes"] if a["id"] == "X")["direction"][0] == 1
    assert v["tool"]["direction"][0] == 1 and v["lathe_home_mm"] == [250.0, 150.0]
    assert [c["id"] for c in v["components"]] == ["chuck", "sub_chuck", "turret2"]
    assert next(c for c in v["components"] if c["id"] == "turret2")["box_mm"][0::3] == [120, 260]
    assert (v["spindle"]["max_rpm"], v["spindle"]["power_kw"]) == (5000, 11.0)
    v1 = MM.channel_model(raw, 1)
    assert [a["id"] for a in v1["axes"]] == ["X", "Y", "Z", "B", "C"] and "turret2" not in {c["id"] for c in v1["components"]}
    assert "EX-MT-TT" in {m["id"] for m in machines.all_machines()}
    record_verdict(("两个刀架：下刀架单独看的机床与手算一致", "two turrets: lower-turret view of the machine matches hand calculation"), "pass", "pass")


@pytest.mark.parametrize("family", ["fanuc", "siemens"])
def test_two_programs_waits_paired(tmp_path, monkeypatch, family):
    """两条程序：通道 1 右端 → 等待 1 → 接料、切断、退回 → 等待 2；通道 2 副主轴坐标 → 等待 1 → 等待 2 → 背面 → 卸件。等待号成对、各自回读一致"""
    _post(tmp_path, monkeypatch, family)
    p = _run({**PART, "post": "tw"})
    assert p[0]["release"] is not None and p[1]["release"] is not None, _errors(p[0]) + _errors(p[1])
    assert p[0]["twin"]["readback"] == "ok" and (p[0]["channel"], p[1]["channel"]) == (1, 2)
    t1, t2 = p[0]["release"]["text"], p[1]["release"]["text"]
    sie = family == "siemens"
    w1, w2 = ("WAITM(1,1,2)", "WAITM(2,1,2)") if sie else ("M100", "M101")
    _after(t1, ["T2 D1" if sie else "T0202", w1, "M210", "B-435.0", "M220", "T8 D1" if sie else "T0808", "B0.0", "M211", w2])
    _after(t2, ["G55", w1, w2, "T11 D1" if sie else "T1111", "T12 D1" if sie else "T1212", "M221"])
    for t in (t1, t2):
        assert t.count(w1) == 1 and t.count(w2) == 1
    assert "G14" not in t1 + t2 and "G15" not in t1 + t2 and "SETMS" not in t1 + t2     # 两个刀架各管一个主轴，不切换
    assert "T11" not in t1 and "T08" not in t2 and "T8 " not in t2
    assert "X250.0 Z-150.0" in t2                                                       # 通道 2 的换刀点（调头坐标 Z 反向）
    record_verdict((f"两个刀架：{family} 两条程序等待号成对、顺序对、回读一致", f"two turrets: {family} two programs, waits paired and in order, read-back matches"),
                   "pass", "pass")


def test_cycle_time_by_hand():
    """节拍 = max(右端不含切断, 背面) + 交接（切断 + 副主轴移动）；副主轴移动：快移 433 mm、进给 2 mm、快移 435 mm（B 快移 20000 mm/min、夹持进给 500 mm/min）
    = 1.299 + 0.24 + 1.305 = 2.844 s；一个刀架干（单通道）= 右端 + 背面 + 交接，比两个刀架长"""
    p = _run(PART)
    c = p[0]["channels"]
    assert c["sub_move_s"] == pytest.approx(60 * 433 / 20000 + 60 * 2 / 500 + 60 * 435 / 20000, abs=1e-3)
    assert c["transfer_s"] == pytest.approx(c["part_s"] + c["sub_move_s"], abs=2e-3)
    assert c["cycle_s"] == pytest.approx(max(c["right_s"], c["back_s"]) + c["transfer_s"], abs=2e-3)
    assert c["single_s"] == pytest.approx(c["right_s"] + c["back_s"] + c["transfer_s"], abs=2e-3)
    assert c["cycle_s"] < c["single_s"]
    assert c["right_s"] + c["part_s"] == pytest.approx(p[0]["time"]["total_s"], abs=2e-3)       # 与单段的加工时间一致
    assert c["back_s"] == pytest.approx(p[1]["time"]["total_s"], abs=2e-3)
    w1, w2 = c["channels"][0]["wait_s"], c["channels"][1]["wait_s"]
    assert w1 == pytest.approx(max(0.0, c["back_s"] - c["right_s"]), abs=2e-3)
    assert w2 == pytest.approx(max(0.0, c["right_s"] - c["back_s"]) + c["transfer_s"], abs=2e-3)
    record_verdict(("两个刀架：节拍 = 两边较长的 + 交接，与手算一致", "two turrets: cycle time = longer side + transfer, matches hand calculation"),
                   "pass", "pass")


def test_turret_clash_on_timeline(tmp_path, monkeypatch):
    """下刀架的换刀点挪到主主轴卡盘前（X60、调头坐标 Z490 → 机床 Z 450 − 490 = −40，卡盘 Z −80 ~ 0、半径 105）：
    开机通道 2 停在那里时通道 1 在车右端——时间线查出下刀架的刀碰主主轴一侧，两条程序都不出"""
    _post(tmp_path, monkeypatch)
    d = tmp_path / "machines"
    d.mkdir()
    m = json.loads((Path(cam.__file__).parent / "machines" / "EX-MT-TT.json").read_text(encoding="utf-8"))
    m["channels"][1]["lathe_home_mm"] = [60.0, 490.0]
    (d / "EX-MT-TT.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("FAP_MACHINES", str(d))
    p = _run({**PART, "post": "tw"})
    assert any(e.startswith("两个刀架同时干时：通道 2") and "主主轴一侧的卡盘" in e and "第 0.00 s" in e for e in _errors(p[0])), _errors(p[0])
    assert p[0]["release"] is None and p[1]["release"] is None
    record_verdict(("两个刀架：时间线查出下刀架碰主主轴一侧", "two turrets: timeline finds lower turret hitting the main-spindle side"), "error", "error")


def test_missing_channel_lines_named(tmp_path, monkeypatch):
    """后处理配置没写 channels：两条程序都不出，写明缺什么"""
    _post(tmp_path, monkeypatch, channels=False)
    p = _run({**PART, "post": "tw"})
    assert p[0]["release"] is None and p[1]["release"] is None
    assert any("没写 channels" in e for e in _errors(p[0])), _errors(p[0])


def test_single_turret_machine_unchanged(tmp_path, monkeypatch):
    """一个刀架的双主轴（EX-MT-TS）：照旧一个程序（C4b），没有节拍报告"""
    _post(tmp_path, monkeypatch)
    p = _run({**PART_TS, "post": "tw"})
    assert "channels" not in p[0] and "channel" not in p[1] and p[1]["release"] is None and p[0]["release"] is not None
