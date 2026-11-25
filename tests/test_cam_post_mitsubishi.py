"""问渠CAM E3 三菱 M800V / M80V 后处理（ADR-0106 E3，ADR-0124、0125）：按三菱电机官网《Programming Manual》车床篇（IB-1501619）、
加工中心篇（IB-1501621）写。车床按 G 代码表 2（参数 #1037 cmdtyp = 3，FANUC 写法）；复合循环 G71 的凹槽加工随参数变，不用；
表 2 的 G12.1 是铣削插补（与 FANUC 极坐标插补意思不同），车铣不出；加工中心同步攻丝的 F 是每转还是每分随参数变，G84 不收；
冷却等 M 代码由机床厂定。"""

from __future__ import annotations

import re

import pytest

from analysis import cam
from analysis.cam import machines, postcfg, postproc, rs274
from tests import test_cam_post_q5 as Q5
from tests.verification import record_verdict


def _cfg(pid):
    return postcfg.configs()[pid]


def _errs(p):
    return [c["text"] for c in p["checks"] if c["level"] == "error"]


@pytest.mark.parametrize("cycles", [True, False])
def test_mitsubishi_lathe_codes_in_manual_table(cycles):
    """粗精车、切槽、车螺纹：能出、回读一致；每个 G、M 代码都在三菱手册 G 代码表 2 与 M 功能里；复合循环不写；冷却不写"""
    codes = _cfg("mitsubishi-m800-lathe")["dialect"]["codes"]
    progs = cam.run({**Q5.TURN, "cycles": cycles, "post": "mitsubishi-m800-lathe"})["data"]["programs"]
    for p in progs:
        assert p["release"] is not None, _errs(p)
        t = p["release"]["text"]
        body = "\n".join(re.sub(r"\([^)]*\)", "", ln) for ln in t.splitlines())
        gs = {postcfg._code_norm(g) for g in re.findall(r"\bG(\d+(?:\.\d)?)", body)}
        assert gs <= {postcfg._code_norm(g) for g in codes["g"]}
        assert not re.search(r"\bG7[016]\b|\bM0?[89]\b", body) and "T0101" in t and "G50 S" in t
    record_verdict(("三菱车床：代码都在三菱手册的 G 代码表 2 里，复合循环不用，回读一致",
                    "Mitsubishi lathe: every code is in G code list 2 of the Mitsubishi manual, no multiple repetitive cycles, read-back matches"),
                   "pass", "pass")


@pytest.mark.skipif(rs274.find() is None, reason="没有 rs274")
def test_mitsubishi_lathe_matches_rs274():
    for p in cam.run({**Q5.TURN, "cycles": False, "post": "mitsubishi-m800-lathe"})["data"]["programs"]:
        text = postproc.to_fanuc(p["release"]["text"], "mitsubishi-m800-lathe", True)
        res = rs274.compare(text, True, machines.get("EX-LATHE"), own_text=p["gcode"])
        assert res["ok"], res


def test_mitsubishi_mill_slot_and_drill_release_tapping_refused():
    """加工中心：开槽、钻孔能出（T1 M06、G43 Z H 同手册 12.2 的例子）；带攻丝的程序不出、点名 G84（同步攻丝 F 的单位随参数变）"""
    prog = Q5._mill_prog()
    prog["ops"] = prog["ops"][:2]
    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": prog, "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": Q5.MSIM_MILL, "post": "mitsubishi-m800-mill"})
    p = r["data"]["programs"][0]
    assert p["release"] is not None, _errs(p)
    t = p["release"]["text"]
    assert "T1 M06" in t and "G43 Z5.0 H01" in t and not re.search(r"\bM0?[89]\b", t)
    p2 = Q5._mill("mitsubishi-m800-mill")
    assert p2["release"] is None and any("G84" in e for e in _errs(p2))
    record_verdict(("三菱加工中心：开槽、钻孔能出；攻丝 F 单位随参数变，带攻丝的程序不出、点名 G84",
                    "Mitsubishi machining center: slot and drill programs output; tapping refused and G84 named (F unit depends on parameters)"),
                   "pass", "pass")


def test_mitsubishi_configs_cite_manual():
    for pid, ib in (("mitsubishi-m800-lathe", "IB-1501619"), ("mitsubishi-m800-mill", "IB-1501621")):
        c = _cfg(pid)
        assert ib in c["source"] and c["coolant"] == "off" and c.get("verified") is not True
        assert all("mitsubishielectric.com" in s["url"] for s in c["dialect"]["sources"])
    assert "12.1" not in _cfg("mitsubishi-m800-lathe")["dialect"]["codes"]["g"]
    assert "84" not in _cfg("mitsubishi-m800-mill")["dialect"]["codes"]["g"]
