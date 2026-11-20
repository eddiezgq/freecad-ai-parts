"""问渠CAM Q5b 海德汉 TNC 对话格式（ADR-0106 Q5b）：铣的标准程序（开槽、钻孔含啄钻、攻丝）在每个开关下都能出正式程序，
回读（换回 ISO）与整机仿真刀路逐段一致，程序时间与 FANUC 一样；不合格配置不列出、写明原因。"""

from __future__ import annotations

import re

import pytest

from analysis import cam
from analysis.cam import klartext, postcfg, postproc
from tests.test_cam_post_q5 import (  # noqa: F401  （fixture）
    MSIM_MILL,
    _mill,
    _mill_prog,
    _ok,
    posts_dir,
)
from tests.verification import record_verdict

SWITCHES = {
    "plain": {},
    "dec": {"decimals": {"coord": 4, "feed": 2}},
    "nocom": {"comments": "none"},
    "utf8": {"comments": "utf8"},
    "toolchg": {"tool_change": {"before": ["M140 MB MAX"], "after": ["M8"], "optional_stop": True}},
    "mist": {"coolant": "mist"},
    "nocool": {"coolant": "off"},
    "drillcyc": {"cycles": {"drill": True}},
    "subs": {"subprograms": True},
    "end": {"program": {"end": "M02"}},
    "all": {"subprograms": True, "cycles": {"drill": True}, "tool_change": {"before": ["M140 MB MAX"], "optional_stop": True},
            "comments": "none", "decimals": {"coord": 4}},
}


def _numbered(t):
    """每段段号从 0 起步长 1，续行不编号；BEGIN / END PGM 前后呼应"""
    nums = [int(ln.split()[0]) for ln in t.splitlines() if not ln.startswith(" ")]
    return nums == list(range(len(nums))) and re.match(r"^0 BEGIN PGM 6001 MM$", t.splitlines()[0]) and t.rstrip().endswith("END PGM 6001 MM")


@pytest.mark.parametrize("name", list(SWITCHES))
def test_heidenhain_every_switch_reads_back(name, posts_dir):  # noqa: F811
    base = _mill("fanuc")
    cid = posts_dir(f"h-{name}", family="heidenhain", kinds=("mill",), **SWITCHES[name])
    p = _mill(cid)
    t = _ok(p)
    assert _numbered(t), t[:800]
    if "tool_change" in SWITCHES[name]:             # 换刀前退刀是实打实的移动：进了仿真，时间变长
        assert p["time"]["total_s"] > base["time"]["total_s"]
    else:
        assert p["time"]["total_s"] == pytest.approx(base["time"]["total_s"])
    checks = {"plain": lambda: "TOOL CALL 4 Z S2200" in t and "CYCL DEF 207 RIGID TAPPING" in t and "CYCL DEF 200" not in t
                              and "M140 MB MAX" in t and " G0" not in t,
              "dec": lambda: "X+70.1235" in t and "F600.13" in t,
              "nocom": lambda: "; OP1" not in t and "FIRST PART" in t and "NOT VERIFIED" in t,
              "utf8": lambda: "; OP1" in t,
              "toolchg": lambda: t.count("M140 MB MAX\n") == 4 and len(re.findall(r"^\d+ M1$", t, re.MULTILINE)) == 2,
              "mist": lambda: " M7" in t and not re.search(r" M8\b", t),
              "nocool": lambda: not re.search(r" M[89]\b", t),
              "drillcyc": lambda: t.count("CYCL DEF 200 DRILLING") == 2 and "Q202=+6.0" in t and t.count("M99") == 4,
              "subs": lambda: t.count("CALL LBL") == 3 and re.search(r"\d+ LBL 3\n", t) and t.count("LBL 0") == 3
                              and re.search(r"M140 MB MAX\n\d+ M30\n\d+ LBL 1\n", t) is not None,
              "end": lambda: re.search(r"^\d+ M2$", t, re.MULTILINE) and "M30" not in t,
              "all": lambda: "CALL LBL 1" in t and "CYCL DEF 200" in t and "; OP" not in t}
    assert checks[name](), (name, t[:2000])
    record_verdict((f"海德汉后处理开关 {name}：回读与仿真刀路一致", f"Heidenhain post switch {name}: read-back matches"), "pass", "pass")


def test_heidenhain_builtin_and_cycle_parameters():
    """内置海德汉配置：只铣、未经实机验证；钻孔循环参数：表面 = R − 2，深度、第二安全距离按安全高度算；回读换回 G98 G83 / G84"""
    assert postproc.posts()["heidenhain"]["mill"] and not postproc.posts()["heidenhain"]["lathe"]
    t = _ok(_mill("heidenhain"))
    assert "Q201=-16.0" in t and "Q203=+1.0" in t and "Q204=+4.0" in t and "Q239=+1.5" in t
    iso = klartext.to_iso(t)
    assert "M29 S400" in iso and iso.count("G98 G84 Z-15 R3 F600") == 2


def test_heidenhain_readback_catches_tampering():
    """回读真的在比：改一个坐标、删一个孔的调用，回读刀路与仿真对不上"""
    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": _mill_prog(),
                 "stock": {"box": [0, 0, 100, 60], "height": 40}, "machine_sim": MSIM_MILL,
                 "post": "heidenhain"})
    p = r["data"]["programs"][0]
    from analysis.cam import machines

    mach = machines.get("EX-VMC")
    t = p["release"]["text"]
    assert cam._same_path(p["gcode"], klartext.to_iso(t), mach)
    bad = t.replace("X+70.123", "X+70.2")
    assert not cam._same_path(p["gcode"], klartext.to_iso(bad), mach)
    lines = t.splitlines()
    drop = next(i for i, ln in enumerate(lines) if ln.endswith("X+80.0 Y+45.0 R0 FMAX M99"))
    assert not cam._same_path(p["gcode"], klartext.to_iso("\n".join(lines[:drop] + lines[drop + 1:])), mach)


def test_heidenhain_bad_configs(posts_dir, tmp_path):  # noqa: F811
    """车床、段号开关、%、ISO 写法的换刀动作：不列出，problems() 写明原因"""
    posts_dir("h-lathe", family="heidenhain", kinds=("lathe", "mill"))
    posts_dir("h-seq", family="heidenhain", kinds=("mill",), sequence={"enabled": True})
    posts_dir("h-pct", family="heidenhain", kinds=("mill",), program={"percent": True})
    posts_dir("h-iso", family="heidenhain", kinds=("mill",), tool_change={"before": ["G91 G28 Z0"]})
    probs = postcfg.problems()
    assert len(probs) == 4
    assert any("只有铣" in p for p in probs) and any("段号" in p for p in probs) and any("BEGIN PGM" in p for p in probs) \
        and any("读不懂" in p for p in probs)
    assert {"h-lathe", "h-seq", "h-pct", "h-iso"}.isdisjoint(postproc.posts())


def test_klartext_to_iso_units():
    """回读换算：续行、段号、注释、LBL 展开、M140"""
    blocks = ["0 BEGIN PGM 1 MM", "1 ; X", "2 TOOL CALL 3 Z S1000", "3 CALL LBL 1", "4 M140 MB MAX", "5 M30",
              "6 LBL 1", "7 L X+1.5 Y-2.0 R0 FMAX M3", "8 L Z-1.0 R0 F100.0", "9 LBL 0", "10 END PGM 1 MM"]
    t = "\n".join(blocks)
    iso = klartext.to_iso(t)
    assert iso.split("\n")[2:9] == ["T3 M06", "S1000", "G00 X1.5 Y-2 M03", "G01 Z-1 F100", "G91 G28 Z0.0", "G90", "M30"]
    with pytest.raises(klartext.KlartextError):
        klartext.to_iso("0 BEGIN PGM 1 MM\n1 CALL LBL 9\n2 M30\n3 END PGM 1 MM")
    with pytest.raises(klartext.KlartextError):
        klartext.action_iso("L Z+5 R0 F100")
