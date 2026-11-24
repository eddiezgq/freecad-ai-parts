"""问渠CAM 后处理“写法差别”（ADR-0124，ADR-0106 E3）：同属 ISO 家族的各家数控系统，换刀、限速、车铣插补开关、动力刀开转的写法按配置写；
回读按同一份模板换回 FANUC 写法再与仿真比，一致才出；没写出处的写法不收；大隈、发格家族在官方手册到之前不能用；核对记录写进程序头。
这里的配置是**测试用的写法**（不是哪一家的真实写法，各家的真实配置按官方手册另做）。"""

from __future__ import annotations

import json

import pytest

from analysis import cam
from analysis.cam import postcfg
from tests import test_cam_millturn_c2b as MT
from tests import test_cam_post_q5 as Q5
from tests.verification import record_verdict

SRC = {"doc": "测试用写法（不是厂商写法）", "version": "—", "section": "—"}
DIALECT = {"tool_call_lathe": "T{n}{oo}", "tool_call_mill": ["M06 T{n}"], "spindle_limit": "G92 S{s}",
           "polar": ["G112", "G113"], "cylindrical": ["G107 C{d}", "G107 C0"]}


def _cfg(cid, dialect=None, family="fanuc", **extra):
    dl = dict(DIALECT if dialect is None else dialect)
    dl["sources"] = [{"item": k, **SRC} for k in dl if k not in ("sources",)]
    return {"format": "cam-post/1", "id": cid, "name": cid, "family": family, "kinds": ["lathe", "mill"], "source": "测试", "dialect": dl, **extra}


@pytest.fixture()
def put(tmp_path, monkeypatch):
    d = tmp_path / "posts"
    d.mkdir()
    monkeypatch.setenv("FAP_POSTS", str(d))

    def f(cfg):
        (d / f"{cfg['id']}.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return cfg["id"]
    return f


def _ok(p):
    errs = [c["text"] for c in p["checks"] if c["level"] == "error"]
    assert p["release"] is not None and not errs, errs
    return p["release"]["text"]


@pytest.mark.parametrize("cycles", [False, True])
def test_turn_and_mill_written_in_dialect_and_read_back(put, cycles):
    """车：T101（刀号不补零、刀补两位）、G92 S 限速；铣：M06 T1。回读一致才出；车削程序时间与 FANUC 一样（写法不同、刀路相同）"""
    cid = put(_cfg("dl"))
    base = [p["time"]["total_s"] for p in cam.run({**Q5.TURN, "cycles": cycles, "post": "fanuc"})["data"]["programs"]]
    pt = cam.run({**Q5.TURN, "cycles": cycles, "post": cid})["data"]["programs"]
    tt = "\n".join(_ok(p) for p in pt)
    assert "T101" in tt and "T0101" not in tt and "G92 S" in tt and "G50 S" not in tt
    assert [p["time"]["total_s"] for p in pt] == pytest.approx(base)
    tm = _ok(Q5._mill(cid))
    assert "M06 T1" in tm and "T1 M06" not in tm
    record_verdict((f"写法差别：车（固定循环 {'开' if cycles else '关'}）、铣按配置写，回读一致",
                    f"dialect: turning (cycles {'on' if cycles else 'off'}) and milling written per config, read-back matches"), "pass", "pass")


def test_millturn_switches_and_live_rpm(put):
    """车铣：极坐标插补 G112 / G113、圆柱插补 G107 C直径 / G107 C0、动力刀 M133 P转速（行里带 {rpm}，不再另写 S），回读一致"""
    cid = put(_cfg("dlmt", millturn={"live_on": ["M133 P{rpm}"], "live_off": ["M135"], "c_on": ["M154"], "c_off": ["M155"]}))
    t = _ok(MT._run_mt(cid))
    for frag in ("M154\nM133 P2000\nG112", "G113\nM135\nM155", "G107 C50.0", "G107 C0"):
        assert frag in t, (frag, t)
    assert "G12.1" not in t and "G07.1" not in t and "\nS2000\n" not in t
    record_verdict(("写法差别：车铣插补开关、动力刀转速按配置写，回读一致", "dialect: mill-turn switches and live-tool speed per config, read-back matches"),
                   "pass", "pass")


def test_repeated_field_and_sequence_numbers(put):
    """T{nn}{oo}{oo}（刀号、刀补、刀尖圆弧补同号，六位）加顺序号：T010101 写出来、回读还原"""
    cid = put(_cfg("dl6", {"tool_call_lathe": "T{nn}{oo}{oo}"}, sequence={"enabled": True, "start": 10, "step": 10}))
    tt = "\n".join(_ok(p) for p in cam.run({**Q5.TURN, "post": cid})["data"]["programs"])
    assert " T010101" in tt and " T020202" in tt


def test_turn_cycles_none(put):
    cid = put(_cfg("dln", {"turn_cycles": "none"}))
    tt = "\n".join(_ok(p) for p in cam.run({**Q5.TURN, "cycles": True, "post": cid})["data"]["programs"])
    assert "G71" not in tt and "G76" not in tt


@pytest.mark.parametrize("cfg,msg", [
    ({**_cfg("x1"), "dialect": {**DIALECT, "sources": [{"item": "polar", **SRC}]}}, "没写出处"),
    (_cfg("x2", {"turn_cycles": "one_block"}), "单段写法"),
    (_cfg("x3", {"tool_call_lathe": "T{n}{q}"}), "不认识的占位符"),
    (_cfg("x4", family="siemens"), "只用于 ISO 家族"),
    ({"format": "cam-post/1", "id": "x5", "name": "x5", "family": "okuma", "kinds": ["lathe"], "source": "测试"}, "官方编程手册"),
])
def test_bad_dialect_configs_named(cfg, msg):
    with pytest.raises(postcfg.PostConfigError, match=msg):
        postcfg.check(cfg, "t")
    record_verdict(("写法差别：没出处、不认识、家族不对的配置不收，写明原因", "dialect: unsourced or invalid configs are rejected with the reason"),
                   "error", "error")


def test_checks_written_into_program_head(put):
    cid = put(_cfg("dlc", checks=[{"level": "L2", "tool": "LinuxCNC 2.9.4 rs274", "date": "2026-11-24", "by": "问渠CAM 标准题",
                                   "evidence": "tests/test_cam_rs274.py"}]))
    t = _ok(cam.run({**Q5.TURN, "post": cid})["data"]["programs"][0])
    assert "(CHECKED L2 LinuxCNC 2.9.4 rs274 2026-11-24)" in t and "NOT VERIFIED" in t


def test_no_dialect_output_unchanged():
    """没写 dialect 的内置配置：与以前一字不差（同 Q5 的标准题）"""
    Q5.test_builtin_configs_reproduce_previous_output()
