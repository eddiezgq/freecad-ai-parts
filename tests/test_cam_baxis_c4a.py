"""问渠CAM C4a B 轴车铣中心（单主轴，ADR-0106 C4a）：车刀能车的斜度（主偏角、副偏角）、B 轴车削按刀长写机床位置、
动力刀铣削按 B 定位。示例机床 EX-MT-B（虚构）。"""

from __future__ import annotations

import json

import pytest

from analysis import cam
from analysis.cam import holders as HD
from analysis.cam import machines, sim
from tests.verification import record_verdict

# 从左往右：Ø50 夹持段、45° 倒角下到 Ø36、Ø36 颈部、15° 斜坡上到 Ø44、Ø44 到右端（从右往左车就是 15° 下坡）
NECK = [[0, 50], [20, 50], [27, 36], [37, 36], [51.928, 44], [80, 44]]
L_TURN = 180.0


def _turn(machine, tool, post=None, profile=NECK, extra=None):
    st = {"mode": "turn", "machine": machine, "profile": profile, "stock_d_mm": 54,
          "machine_sim": {"tools": {"1": {"tool": tool, "length_mm": L_TURN}, "2": {"tool": tool, "length_mm": L_TURN}},
                          "work_offset_mm": [0, 0, 90]}, **(extra or {})}
    if post:
        st["post"] = post
    r = cam.run(st)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"][0]


def _errors(p):
    return [c["text"] for c in p["checks"] if c["level"] == "error"]


def test_turn_angles_from_catalog():
    """泰珂洛 C004：L 95°、J 93°、B 75°；刀片 C 80°、D 55°、V 35° → 副偏角 5°、32°、52°；端面走刀量角的形式（C）查不到"""
    assert HD.turn_angles("PCLNR 2525 M 12", "CNMG120408") == (95.0, 5.0)
    assert HD.turn_angles("PDJNR 2525 M 15", "DNMG150608") == (93.0, 32.0)
    assert HD.turn_angles("SVJBR 2525 M 16", "VNMG160404") == (93.0, 52.0)
    assert HD.turn_angles("PCBNR 2525 M 12", "CNMG120408") == (75.0, 25.0)
    assert HD.turn_angles("PCCNR 2525 M 12", "CNMG120408") is None
    assert HD.turn_angles("PCLNR 2525 M 12", "DNMG150608") is None        # 刀杆配 C 形刀片，装 D 形对不上


@pytest.mark.parametrize("kappa,kappa2,up,down,bad", [
    (95, 5, 0, 15, True), (93, 32, 0, 15, False), (93, 52, 0, 51, True), (93, 52, 0, 50, False), (75, 25, 90, 0, True), (95, 5, 90, 0, False)])
def test_angle_issues(kappa, kappa2, up, down, bad):
    """往下斜角 > 副偏角 − 2°、往上台阶 > 主偏角 → 车不了"""
    assert bool(HD.angle_issues(kappa, kappa2, up, down)) is bad


def test_pick_beta():
    """CNMG（κ 95、κ′ 5）车 15° 下坡、45° 台阶：B 转 −12° 以内都不够，−12° 正好（5 + 12 − 2 = 15）；带直角台阶就挑不到"""
    assert HD.pick_beta(95, 5, 45, 15) == -12
    assert HD.pick_beta(95, 5, 90, 15) is None
    assert HD.pick_beta(93, 32, 90, 15) == 0


def test_lathe_reports_neck_the_insert_cannot_reach():
    """普通车床：PCLNR + CNMG 车 15° 下坡——报副切削刃啃工件，仿真也量出过切；SVJBR + VNMG（κ′ 52°）车同一个不报，仿真不过切"""
    bad = _errors(_turn("EX-LATHE", "TR-CNMG"))
    assert any("往下斜角 15.0° 超过副偏角 5°" in e for e in bad) and any(e.startswith("过切") for e in bad), bad
    ok = _turn("EX-LATHE", "TR-VNMG")
    assert not _errors(ok) and ok["sim"]["dev_min_mm"] > -0.01, _errors(ok)
    record_verdict(("车刀车不到的下坡必须报出（主偏角、副偏角）", "turning insert that cannot reach a down slope must be reported"),
                   "pass", "pass")


@pytest.mark.parametrize("post", ["fanuc", "siemens"])
def test_b_axis_turning_tilts_and_releases(post):
    """EX-MT-B：同样的 PCLNR + CNMG，起草挑出 B −13°（副偏角变 18°），不报错、仿真不过切、整机仿真通过、出程序；
    程序 B 定位、不用刀补（T0100 / D0），X、Z 是机床轴的位置；回读的刀尖轨迹与普通车床上的一致（< 0.001 mm）"""
    p = _turn("EX-MT-B", "TR-CNMG", post)
    assert p["turn_b_deg"] == {"1": -13.0, "2": -13.0}
    assert not _errors(p) and p["machine_sim"]["status"] in ("pass", "unknown") and p["release"] is not None, _errors(p)
    t = p["release"]["text"]
    assert ("G0 B-13.0" in t and "T1 D0" in t) if post == "siemens" else ("G00 B-13.0" in t and "T0100" in t)
    assert "B-AXIS TURNING T1 L180.000 B-13" in t
    base = _turn("EX-LATHE", "TR-CNMG")
    mb = {**machines.get("EX-MT-B"), "bturn": {1: L_TURN, 2: L_TURN}}
    fa = [m["b"] for m in sim.parse(base["gcode"] or base["replay_in"]["gcode"], machines.get("EX-LATHE"))["moves"] if m["t"] == "feed"]
    fb = [m["b"] for m in sim.parse(p["gcode"], mb)["moves"] if m["t"] == "feed"]
    assert len(fa) == len(fb) and max(abs(x - y) for u, v in zip(fa, fb, strict=True) for x, y in zip(u, v, strict=True)) < 1e-3
    record_verdict((f"B 轴车削：转 B 车到普通刀车不到的下坡，{post} 出程序、回读一致", f"B-axis turning reaches the down slope, {post} released and reads back"),
                   "pass", "pass")


def test_b_axis_cannot_fix_everything():
    """直角台阶 + 15° 下坡：CNMG 怎么转 B 都不行（台阶要 B ≥ −5°，下坡要 B ≤ −12°），照样报错"""
    prof = [[0, 50], [20, 50], [20, 36], [37, 36], [51.928, 44], [80, 44]]
    p = _turn("EX-MT-B", "TR-CNMG", profile=prof)
    assert any("往下斜角 15.0°" in e for e in _errors(p)), _errors(p)
    assert "turn_b_deg" in p and p["turn_b_deg"] == {}


def test_b_axis_needs_tool_length():
    r = cam.run({"mode": "turn", "machine": "EX-MT-B", "profile": NECK, "stock_d_mm": 54, "machine_sim": {"tools": {"1": {"tool": "TR-CNMG"}}}})
    assert r["status"] != "ok" and any("length_mm" in m for m in r["messages"]), r["messages"]


def _mt(post, tmp_path=None, monkeypatch=None):
    from tests.test_cam_millturn_c2b import _mt_prog

    if tmp_path is not None:
        d = tmp_path / "posts"
        d.mkdir()
        mt = {"live_on": ["M13"], "live_off": ["M15"], "c_on": ["M18"], "c_off": ["M19"]}
        (d / "bmt.json").write_text(json.dumps({"format": "cam-post/1", "id": "bmt", "name": "FANUC B mill-turn", "family": "fanuc",
                                                "kinds": ["lathe"], "source": "测试", "millturn": mt}), encoding="utf-8")
        monkeypatch.setenv("FAP_POSTS", str(d))
    tools = {"1": {"tool": "TR-CNMG", "length_mm": L_TURN}, "5": {"tool": "EM6", "length_mm": 120}, "6": {"tool": "EM6", "length_mm": 120}}
    r = cam.run({"mode": "millturn", "machine": "EX-MT-B", "program": _mt_prog(), "stock": {"d": 52, "z_right": 0.5, "z_left": -60},
                 "post": post, "machine_sim": {"work_offset_mm": [0, 0, 90], "tools": tools}})
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"][0]


def test_live_milling_positions_b(tmp_path, monkeypatch):
    """动力刀铣削：端面槽 B90、圆柱面槽 B0 定位，整机仿真按运动链逆解 B、C，通过；
    刀长随 B 怎么补各家不同，后处理配置还没有这一项——写了动力刀 M 代码也不出程序，写明原因"""
    p = _mt("bmt", tmp_path, monkeypatch)
    g = p["gcode"]
    assert "T0505\nG00 B90.0" in g and "T0606\nG00 B0.0" in g
    errs = _errors(p)
    assert p["machine_sim"]["status"] in ("pass", "unknown") and not [e for e in errs if "正式程序" not in e], errs
    assert p["release"] is None and any("刀长随 B 怎么补" in e for e in errs), errs
    record_verdict(("B 轴车铣中心：动力刀铣削按 B 定位、整机仿真通过", "B-axis mill-turn: live milling positioned by B, machine sim passes"), "pass", "pass")
