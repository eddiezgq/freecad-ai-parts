"""问渠CAM E3 哈斯车床后处理（ADR-0106 E3，ADR-0124）：按 Haas 官网在线《Lathe Operator's Manual》写——程序号 O 加 5 位、换刀 T101、
复合循环不用（G71 手册只写了单段写法）、车铣还没做（G112 / G107 的坐标写法与 FANUC 不同，不出）。
标准题：程序里每个 G、M 代码都在手册的代码表里；回读一致；换回 FANUC 写法后独立解释器 rs274 走出来与仿真一致（L2）。"""

from __future__ import annotations

import re

import pytest

from analysis import cam
from analysis.cam import machines, postproc, rs274
from tests import test_cam_millturn_c2b as MT
from tests import test_cam_post_q5 as Q5
from tests.verification import record_verdict

# Haas Lathe Operator's Manual（官网在线版，2026-11-24 查）第 16 章 G-Codes、第 17 章 M-Codes 的代码表（只收本题会用到的范围）
HAAS_G = {"00", "01", "02", "03", "04", "09", "10", "14", "15", "17", "18", "19", "20", "21", "28", "29", "31", "32", "40", "41", "42", "43",
          "50", "53", "54", "55", "56", "57", "58", "59", "61", "64", "70", "71", "72", "73", "74", "75", "76", "80", "81", "82", "83", "84",
          "85", "86", "89", "90", "92", "94", "95", "96", "97", "98", "99", "107", "112", "113"}
HAAS_M = {"00", "01", "02", "03", "04", "05", "08", "09", "10", "11", "14", "15", "19", "30", "41", "42", "97", "98", "99",
          "110", "111", "133", "134", "135"}


def _progs(**extra):
    r = cam.run({**Q5.TURN, "cycles": True, "post": "haas-lathe", **extra})
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"]


def test_haas_lathe_codes_all_in_manual():
    """粗精车、切槽、车螺纹（要了固定循环也出直线段）：正式程序能出；每个 G、M 代码都在 Haas 手册的代码表里；O 加 5 位；换刀 T101 / T202"""
    for p in _progs():
        assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
        t = p["release"]["text"]
        body = "\n".join(ln for ln in t.splitlines() if not ln.startswith("("))
        gs = {g.lstrip("0").rjust(2, "0") for g in re.findall(r"\bG(\d+)(?:\.\d+)?", body)}
        ms = {m.lstrip("0").rjust(2, "0") for m in re.findall(r"\bM(\d+)", body)}
        assert gs <= HAAS_G, gs - HAAS_G
        assert ms <= HAAS_M, ms - HAAS_M
        assert re.search(r"^O\d{5} ", t, re.MULTILINE) and "G71" not in t and "G76" not in t
        assert re.search(r"^T[1-9]0[1-9]$", t, re.MULTILINE) and not re.search(r"^T0\d0\d$", t, re.MULTILINE)
        assert "CHECKED L2" in t and "NOT VERIFIED" in t
    record_verdict(("哈斯车床：程序里的代码都在 Haas 官方手册里、回读一致", "Haas lathe: every code is in the Haas manual, read-back matches"),
                   "pass", "pass")


@pytest.mark.skipif(rs274.find() is None, reason="没有 rs274")
def test_haas_lathe_matches_rs274():
    for p in _progs(cycles=False):
        text = postproc.to_fanuc(p["release"]["text"], "haas-lathe", True)
        res = rs274.compare(text, True, machines.get("EX-LATHE"), own_text=p["gcode"])
        assert res["ok"], res


def test_haas_mill_turn_not_output():
    """车铣（动力刀）程序：哈斯的 G112 用直角坐标 XY、G107 另一套参数，还没按手册做——不出、写明原因"""
    p = MT._run_mt("haas-lathe")
    assert p["release"] is None and any("millturn" in c["text"] for c in p["checks"] if c["level"] == "error")


def test_haas_lathe_config_has_manual_code_table():
    """哈斯车床配置带手册代码表（ADR-0125）：出程序时就查，表外的不出；表与本题用到的代码一致"""
    import json

    from analysis.cam import postcfg

    cfg = json.loads((postcfg.BUILTIN / "haas-lathe.json").read_text(encoding="utf-8"))
    codes = cfg["dialect"]["codes"]
    assert HAAS_G <= set(codes["g"]) and HAAS_M <= set(codes["m"])
    assert any(s["item"] == "codes" and "haascnc.com" in s["url"] for s in cfg["dialect"]["sources"])
