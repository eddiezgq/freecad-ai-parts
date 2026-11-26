"""问渠CAM E3 凯恩帝 Fi 系列后处理（ADR-0106 E3，ADR-0124、0125）：按凯恩帝官网《凯恩帝Fi系列车床标准编程手册》《铣床标准编程手册》V5.1 写。
车床按 G 代码体系 A（参数 GSP = 0，FANUC 写法）；不写小数点的数值随参数 PODI 变，凡能带小数点的地址都带小数点；
复合螺纹循环 G76 的 P、Q 随 PQDOT、PODI、POD 变，复合循环不用；车铣没核对、不出；加工中心攻丝 F 是导程还是进给随参数变，G84 不收，
FANUC 刚性攻丝的 M29 在凯恩帝是“冲屑关闭”。"""

from __future__ import annotations

import re

import pytest

from analysis import cam
from analysis.cam import machines, postcfg, postproc, rs274
from tests import test_cam_post_q5 as Q5
from tests.verification import record_verdict

# 凯恩帝手册 8.5：可以带小数点的地址（不带小数点时单位随参数 PODI 变）
_DEC = "XYZUVWABCIJKQRFE"


def _cfg(pid):
    return postcfg.configs()[pid]


def _errs(p):
    return [c["text"] for c in p["checks"] if c["level"] == "error"]


def _body(t):
    return "\n".join(re.sub(r"\([^)]*\)", "", ln) for ln in t.splitlines())


def _no_bare_numbers(t):
    """能带小数点的地址都带了小数点（G、M、T、S、H、N、O、P 是编号或整数，不算）"""
    return re.findall(rf"\b[{_DEC}]-?\d+(?![\d.])", _body(t))


@pytest.mark.parametrize("cycles", [True, False])
def test_knd_lathe_codes_in_manual_table(cycles):
    """粗精车、切槽、车螺纹：能出、回读一致；每个 G、M 代码都在凯恩帝手册的 G 代码体系 A 与 M 代码表里；复合循环不写；数值都带小数点"""
    codes = _cfg("knd-fi-lathe")["dialect"]["codes"]
    progs = cam.run({**Q5.TURN, "cycles": cycles, "post": "knd-fi-lathe"})["data"]["programs"]
    for p in progs:
        assert p["release"] is not None, _errs(p)
        t = p["release"]["text"]
        body = _body(t)
        gs = {postcfg._code_norm(g) for g in re.findall(r"\bG(\d+(?:\.\d)?)", body)}
        ms = {postcfg._code_norm(m) for m in re.findall(r"\bM(\d+)", body)}
        assert gs <= {postcfg._code_norm(g) for g in codes["g"]}
        assert ms <= {postcfg._code_norm(m) for m in codes["m"]}
        assert not re.search(r"\bG7[0-6]\b", body) and "T0101" in t and "G50 S" in t
        assert not _no_bare_numbers(t), _no_bare_numbers(t)
    record_verdict(("凯恩帝车床：代码都在凯恩帝手册的 G 代码体系 A 里，复合循环不用，数值都带小数点，回读一致",
                    "KND lathe: every code is in G code system A of the KND manual, no multiple repetitive cycles, every value has a decimal point, read-back matches"),
                   "pass", "pass")


@pytest.mark.skipif(rs274.find() is None, reason="没有 rs274")
def test_knd_lathe_matches_rs274():
    for p in cam.run({**Q5.TURN, "cycles": False, "post": "knd-fi-lathe"})["data"]["programs"]:
        text = postproc.to_fanuc(p["release"]["text"], "knd-fi-lathe", True)
        res = rs274.compare(text, True, machines.get("EX-LATHE"), own_text=p["gcode"])
        assert res["ok"], res


def test_knd_mill_slot_and_drill_release_tapping_refused():
    """加工中心：开槽、钻孔能出（T1 M06、G43 Z H01 同手册例子），数值都带小数点；带攻丝的程序不出、点名 G84"""
    codes = _cfg("knd-fi-mill")["dialect"]["codes"]
    prog = Q5._mill_prog()
    prog["ops"] = prog["ops"][:2]
    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": prog, "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": Q5.MSIM_MILL, "post": "knd-fi-mill"})
    p = r["data"]["programs"][0]
    assert p["release"] is not None, _errs(p)
    t = p["release"]["text"]
    body = _body(t)
    assert "T1 M06" in t and "G43 Z5.0 H01" in t and "M08" in t and not re.search(r"\bM29\b", body)
    assert {postcfg._code_norm(m) for m in re.findall(r"\bM(\d+)", body)} <= {postcfg._code_norm(m) for m in codes["m"]}
    assert not _no_bare_numbers(t), _no_bare_numbers(t)
    p2 = Q5._mill("knd-fi-mill")
    assert p2["release"] is None and any("G84" in e for e in _errs(p2))
    record_verdict(("凯恩帝加工中心：开槽、钻孔能出；攻丝 F 是导程还是进给随参数变，带攻丝的程序不出、点名 G84",
                    "KND machining center: slot and drill programs output; tapping refused and G84 named (F is lead or feed depending on parameters)"),
                   "pass", "pass")


def test_knd_configs_cite_manual():
    for pid, doc in (("knd-fi-lathe", "车床标准编程手册"), ("knd-fi-mill", "铣床标准编程手册")):
        c = _cfg(pid)
        assert doc in c["source"] and "V5.1" in c["source"] and c.get("verified") is not True
        assert all("yangbentong.com" in s["url"] and "knd" in s["version"] for s in c["dialect"]["sources"])
    lg = _cfg("knd-fi-lathe")["dialect"]["codes"]["g"]
    assert not {"84", "84.5", "93", "12.1", "112", "07.1", "107"} & set(lg)
    assert not {"84", "74", "93"} & set(_cfg("knd-fi-mill")["dialect"]["codes"]["g"])
