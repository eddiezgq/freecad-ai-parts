"""问渠CAM Q5a 可配置后处理（ADR-0106、ADR-0109）：每个开关打开 / 关掉，正式程序都能出（回读与整机仿真刀路逐段一致），程序时间不变；
内置配置的输出与以前一字不差；不合格的用户配置不列出、写明原因。"""

from __future__ import annotations

import json
import re

import pytest

from analysis import cam
from analysis.cam import postcfg, postproc
from tests.verification import record_verdict

TURN = {"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60]], "chamfer_mm": 1, "cycles": True,
        "grooves": [{"z": -18, "width": 4, "d": 21}], "threads": [{"z_start": 0, "z_end": -16, "d": 24, "pitch": 1.5}],
        "machine_sim": {"tools": {}}}
MSIM_MILL = {"work_offset_mm": [0, 0, 40], "tools": {"1": {"tool": "EM10", "length_mm": 120}, "4": {"tool": "DR8.5", "length_mm": 140},
                                                       "5": {"tool": "TAP-M10", "length_mm": 130}}}


def _mill_prog():
    slot = [{"t": "rapid", "x": 30, "y": 30, "z": 5}, {"t": "feed", "x": 30, "y": 30, "z": -3, "f": 200.0},
            {"t": "feed", "x": 70.12345, "y": 30, "z": -3, "f": 600.126}, {"t": "rapid", "x": 70.12345, "y": 30, "z": 5}]
    holes = [(20, 45), (80, 45)]
    drill = [{"t": "drill", "x": x, "y": y, "z": -20.0, "r": 2.0, "f": 300.0, "q": q, "safe": 5.0} for (x, y), q in zip(holes, (0.0, 6.0), strict=True)]
    tap = [{"t": "tap", "x": x, "y": y, "z": -15.0, "r": 3.0, "pitch": 1.5, "safe": 5.0} for x, y in holes]
    return {"number": 6001, "title": "后处理开关", "ops": [
        {"tool": {"n": 1, "d": 10.0, "kind": "endmill"}, "spindle": {"rpm": 4000}, "safe": 5.0, "title": "开槽", "moves": slot},
        {"tool": {"n": 4, "d": 8.5, "kind": "drill"}, "spindle": {"rpm": 2200}, "safe": 5.0, "title": "钻孔", "moves": drill},
        {"tool": {"n": 5, "d": 10.0, "kind": "tap", "pitch": 1.5}, "spindle": {"rpm": 400}, "safe": 5.0, "title": "攻丝", "moves": tap}]}


def _mill(post):
    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": _mill_prog(), "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": MSIM_MILL, "post": post})
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"][0]


def _turn(post):
    r = cam.run({**TURN, "post": post})
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"]


@pytest.fixture()
def posts_dir(tmp_path, monkeypatch):
    d = tmp_path / "posts"
    d.mkdir()
    monkeypatch.setenv("FAP_POSTS", str(d))

    def put(cid, family="fanuc", kinds=("lathe", "mill"), **opts):
        cfg = {"format": "cam-post/1", "id": cid, "name": cid, "family": family, "kinds": list(kinds), "source": "测试", **opts}
        (d / f"{cid}.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return cid
    return put


def _ok(p):
    errs = [c["text"] for c in p["checks"] if c["level"] == "error"]
    assert not errs and p["release"] is not None, errs
    return p["release"]["text"]


SWITCHES = {
    "seq": {"sequence": {"enabled": True, "start": 10, "step": 5}},
    "dec": {"decimals": {"coord": 4, "feed": 2}},
    "nocom": {"comments": "none"},
    "toolchg": {"tool_change": {"before": ["G91 G28 Z0", "G90"], "after": [], "optional_stop": True}},
    "mist": {"coolant": "mist"},
    "nocool": {"coolant": "off"},
    "drillcyc": {"cycles": {"drill": True}},
    "noturncyc": {"cycles": {"turn": False}},
    "subs": {"subprograms": True},
    "prog": {"program": {"number_digits": 5, "percent": False, "end": "M02"}},
    "all": {"sequence": {"enabled": True, "start": 100, "step": 10}, "subprograms": True, "cycles": {"drill": True, "turn": True},
            "tool_change": {"before": ["G91 G28 Z0", "G90"], "optional_stop": True}, "comments": "none"},
}


@pytest.mark.parametrize("name", list(SWITCHES))
def test_every_switch_reads_back_identically(name, posts_dir):
    """打开一个开关：铣（开槽、钻孔含啄钻、攻丝）、车（粗精车固定循环、切槽、车螺纹）的正式程序都能出（回读一致）；
    程序时间与内置 FANUC 一样——换刀前后动作会动机床，也进了整机仿真，时间变长"""
    base_m, base_t = _mill("fanuc"), _turn("fanuc")
    cid = posts_dir(f"t-{name}", **SWITCHES[name])
    pm, pt = _mill(cid), _turn(cid)
    tm = _ok(pm)
    tt = "\n".join(_ok(p) for p in pt)
    if "tool_change" in SWITCHES[name]:            # 换刀前回 Z 参考点是实打实的移动：进了仿真，时间变长
        assert pm["time"]["total_s"] > base_m["time"]["total_s"]
    else:
        assert pm["time"]["total_s"] == pytest.approx(base_m["time"]["total_s"])
    if "tool_change" not in SWITCHES[name]:
        assert [p["time"]["total_s"] for p in pt] == pytest.approx([p["time"]["total_s"] for p in base_t])
    checks = {"seq": lambda: re.search(r"^N10 ", tm, re.MULTILINE) and re.search(r"G71 P\d+ Q\d+", tt) and "N15 " in tm,
              "dec": lambda: "X70.1235" in tm and "F600.13" in tm and "X70.123 " not in tm,
              "nocom": lambda: "(OP1" not in tm and "FIRST PART" in tm and "NOT VERIFIED" in tm,
              "toolchg": lambda: tm.count("G91 G28 Z0\nG90\nT") == 3 and tm.count("M01") == 2,
              "mist": lambda: "M07" in tm and "M08" not in tm,
              "nocool": lambda: "M08" not in tm and "M09" not in tm and "M08" not in tt,
              "drillcyc": lambda: "G98 G81" in tm and "G98 G83" in tm and "G80" in tm,
              "noturncyc": lambda: "G71" not in tt and "G76" not in tt,
              "subs": lambda: tm.count("M98 P") == 3 and tm.count("M99") == 3,
              "prog": lambda: tm.startswith("(") is False and "O06001" in tm and "M02" in tm and "%" not in tm.split("\n")[0],
              "all": lambda: "M98 P" in tm and "G98 G81" in tm and re.search(r"^N100 ", tm, re.MULTILINE) is not None}
    assert checks[name](), (name, tm[:1500])
    record_verdict((f"后处理开关 {name}：回读与仿真刀路一致、时间不变", f"post switch {name}: read-back matches, time unchanged"),
                   "pass", "pass")


def test_builtin_configs_reproduce_previous_output():
    """内置配置的输出等于以前写死的写法：例子程序（examples/wenquest-cam）一字不变由 FreeCAD 例子测试核对；这里查默认值与开关缺省"""
    for cid, fam in (("fanuc", "fanuc"), ("siemens", "siemens"), ("gsk", "gsk"), ("hnc", "hnc")):
        c = postcfg.resolved(postproc.posts()[cid]["cfg"])
        assert c["family"] == fam and not c["sequence"]["enabled"] and not c["subprograms"] and c["coolant"] == "flood"
    assert postproc.posts()["fanuc"]["verified"] is False


def test_hnc_program_head():
    """华中 HNC-8：程序头 %程序号，其余按 FANUC 写法；回读一致"""
    p = _mill("hnc")
    t = _ok(p)
    assert re.search(r"^%6001 ", t, re.MULTILINE) and "M30" in t
    pt = _turn("hnc")
    assert all(_ok(x).split("\n")[1].startswith("%100") for x in pt)


def test_bad_user_configs_are_not_listed(posts_dir, tmp_path):
    """西门子要子程序、内冷、家族写错：不列进可选后处理，problems() 写明哪个文件、哪一项"""
    posts_dir("s-sub", family="siemens", subprograms=True)
    posts_dir("f-through", coolant="through")
    (tmp_path / "posts" / "bad.json").write_text('{"format": "cam-post/1", "id": "x", "name": "x", "family": "mazak", "kinds": ["mill"], "source": "t"}',
                                                 encoding="utf-8")
    probs = postcfg.problems()
    assert len(probs) == 3 and any("子程序" in p for p in probs) and any("内冷" in p for p in probs) and any("family" in p for p in probs)
    assert {"s-sub", "f-through", "x"}.isdisjoint(postproc.posts())
    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": _mill_prog(), "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": MSIM_MILL, "post": "s-sub"})
    p = r["data"]["programs"][0]
    assert p["release"] is None and any("没有 's-sub'" in c["text"] for c in p["checks"])
