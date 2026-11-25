"""问渠CAM E3 发格 8060 / 8065 后处理（ADR-0126，ADR-0106 E3）：按发格官网《CNCelite 8058/8060/8065/8070 Programming manual》写——
G71 公制、G151 直径编程、G192 限速、G95 每转进给、T1 D1 换刀、G33 … K 车螺纹、T1 D1 M6 + D 长度补偿、G63 刚性攻丝、#MCS Z0 回机床 Z 零点；
FANUC 写法里在发格上意思不同的代码（G21、G50、G99、M29、G28、G43、M08）一个都不能留。回读按同一张对照表换回 FANUC 写法与仿真比。"""

from __future__ import annotations

import json
import re

import pytest

from analysis import cam
from analysis.cam import fagor, machines, postcfg, postproc, progdiff
from tests import test_cam_millturn_c2b as MT
from tests import test_cam_post_q5 as Q5
from tests.verification import record_verdict

BAD = ("G21", "G50", "G99", "M29", "G28", "G43", "G49", "M08", "M09", "G32", "G84")


def _codes(t):
    body = "\n".join(re.sub(r"\([^)]*\)", "", ln) for ln in t.splitlines())
    return {f"G{int(g)}" for g in re.findall(r"\bG(\d+)", body)} | {f"M{int(m):02d}" for m in re.findall(r"\bM(\d+)", body)}


def _rel(p):
    assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
    return p["release"]["text"]


def test_fagor_lathe_written_per_manual(tmp_path, monkeypatch):
    """外圆粗精车、切槽、车螺纹：能出、回读一致；没有 FANUC 那几个在发格上意思不同的代码；车削时间与同样不开冷却的 FANUC 相同（写法不同、刀路相同）"""
    d = tmp_path / "posts"
    d.mkdir()
    monkeypatch.setenv("FAP_POSTS", str(d))
    (d / "fa0.json").write_text(json.dumps({"format": "cam-post/1", "id": "fa0", "name": "fa0", "family": "fanuc", "kinds": ["lathe"],
                                            "source": "t", "coolant": "off", "cycles": {"drill": False, "turn": False}}), encoding="utf-8")
    base = [p["time"]["total_s"] for p in cam.run({**Q5.TURN, "post": "fa0"})["data"]["programs"]]
    progs = cam.run({**Q5.TURN, "post": "fagor-8065"})["data"]["programs"]
    for p in progs:
        t = _rel(p)
        assert re.match(r"^%\d{4}\n\(WENQUEST CAM\)", t)
        assert "G71 G18 G151 G40 G97 G95" in t and re.search(r"^T1 D1$", t, re.MULTILINE) and "G192 S3000" in t
        assert not _codes(t) & set(BAD), _codes(t) & set(BAD)
        assert not re.search(r"\bG(70|71) [PU]|\bG76\b", t)                 # 车削复合循环不写（发格的 G70 / G71 是单位）
    assert "G33 Z-16.0 K1.5" in "\n".join(_rel(p) for p in progs)
    assert [p["time"]["total_s"] for p in progs] == pytest.approx(base)
    record_verdict(("发格车床：按发格官方编程手册写（G71 公制、G151、G192、T D、G33 K），回读一致",
                    "Fagor lathe: written per the Fagor programming manual (G71 metric, G151, G192, T D, G33 K), read-back matches"),
                   "pass", "pass")


def test_fagor_mill_tool_length_tap_and_home():
    """开槽、钻孔、攻丝：T D1 M6，换刀后第一次 Z 不写 G43 / H（长度补偿随 D1）；攻丝 G63 攻进、S 负值反转退出、M03 回正转；回 Z 零点 #MCS Z0"""
    t = _rel(Q5._mill("fagor-8065"))
    assert "T1 D1 M6" in t and "T5 D1 M6" in t and "G71 G17 G40 G80 G90 G94" in t
    assert "G63 Z-15.0 F600.0 S400\nG63 Z3.0 S-400\nG00 Z5.0\nS400 M03" in t
    assert t.rstrip().endswith("#MCS Z0\nG90\nM30")
    assert not _codes(t) & set(BAD), _codes(t) & set(BAD)
    record_verdict(("发格铣床：长度补偿随 D、G63 刚性攻丝、#MCS 回 Z 零点，回读一致",
                    "Fagor mill: length offset via D, G63 rigid tapping, #MCS Z home, read-back matches"), "pass", "pass")


def test_round_trip_back_to_fanuc_line_by_line():
    """对照表可逆：FANUC 原文 → 发格 → FANUC，逐行一模一样（顺序号也在）"""
    for lathe, text in ((True, ("%\nO1001 (WENQUEST CAM)\n(X)\nG21 G18 G40 G97 G99\nN10 T0101\nN20 G50 S3000\nN30 G96 S120 M03\n"
                                "N40 G32 Z-16.0 F1.5\nN50 G01 X40.0 F0.2\nM30\n%\n")),
                        (False, ("%\nO6001 (WENQUEST CAM)\nG21 G17 G40 G49 G80 G90 G94\nT4 M06\nG54\nS400 M03\nG00 X20.0 Y45.0\n"
                                "G43 Z5.0 H04 M08\nM29 S400\nG98 G84 X20.0 Y45.0 Z-15.0 R3.0 F600.0\nG80\nG00 Z5.0 M09\nM05\n"
                                "G91 G28 Z0.0\nG90\nM30\n%\n"))):
        fg = fagor.to_fagor(text, lathe)
        back = fagor.to_fanuc(fg, lathe)
        want = [ln for ln in text.strip().split("\n") if ln != "%"]
        assert back.strip().split("\n") == want, (fg, back)


def test_mill_turn_not_output():
    """车铣（动力刀、C 轴）程序：发格是 #CAX / #FACE / #CYL（§18.1），还没做——不出、写明原因"""
    with pytest.raises(postcfg.PostConfigError, match="车铣"):
        postcfg.check({"format": "cam-post/1", "id": "f", "name": "f", "family": "fagor", "kinds": ["lathe"], "source": "t",
                       "millturn": {"live_on": ["M45"]}}, "t")
    with pytest.raises(fagor.FagorError, match="发格车铣还没做"):
        fagor.check_codes("G18\nG12.1\nG01 X10.0 C0.0\nG13.1\n", True)
    p = MT._run_mt("fagor-8065")
    assert p["release"] is None


def test_code_outside_manual_table_refused(tmp_path, monkeypatch):
    """配置的换刀前动作写了 G28（发格没有）：程序不出、点名 G28；换刀后动作写的机床冷却 M 代码（用户按机床说明书填）照认"""
    d = tmp_path / "posts"
    d.mkdir()
    monkeypatch.setenv("FAP_POSTS", str(d))
    cfg = json.loads((postcfg.BUILTIN / "fagor-8065.json").read_text(encoding="utf-8"))
    (d / "fg1.json").write_text(json.dumps({**cfg, "id": "fg1", "tool_change": {"before": ["G28 U0.0"], "after": []}}), encoding="utf-8")
    p = cam.run({**Q5.TURN, "post": "fg1"})["data"]["programs"][0]
    assert p["release"] is None and any("G28" in c["text"] for c in p["checks"] if c["level"] == "error")
    (d / "fg2.json").write_text(json.dumps({**cfg, "id": "fg2", "tool_change": {"before": [], "after": ["M8"]}}), encoding="utf-8")
    t = _rel(cam.run({**Q5.TURN, "post": "fg2"})["data"]["programs"][0])
    assert "T1 D1\nM8" in t
    record_verdict(("发格：手册代码表外的代码不出、点名", "Fagor: codes outside the manual's table are refused and named"), "error", "error")


@pytest.mark.parametrize("extra,msg", [
    ({"dialect": {"tool_call_lathe": "T{n}", "sources": [{"item": "tool_call_lathe", "doc": "x", "version": "x", "section": "x"}]}}, "不收 dialect"),
    ({"cycles": {"drill": False, "turn": True}}, "G70 / G71"),
    ({"subprograms": True}, "子程序"),
    ({"coolant": "flood"}, "冷却"),
])
def test_bad_fagor_configs_named(extra, msg):
    cfg = {"format": "cam-post/1", "id": "f", "name": "f", "family": "fagor", "kinds": ["lathe", "mill"], "source": "t", **extra}
    with pytest.raises(postcfg.PostConfigError, match=msg):
        postcfg.check(cfg, "t")


def test_okuma_still_waits_for_manual():
    with pytest.raises(postcfg.PostConfigError, match="官方编程手册"):
        postcfg.check({"format": "cam-post/1", "id": "o", "name": "o", "family": "okuma", "kinds": ["lathe"], "source": "t"}, "t")


def test_progdiff_recognises_fagor():
    """程序比对认得出发格程序（%号开头不再一律当华中），换回 FANUC 写法后与同一零件的 FANUC 程序刀路一样"""
    fg = _rel(cam.run({**Q5.TURN, "cycles": False, "post": "fagor-8065"})["data"]["programs"][0])
    fa = cam.run({**Q5.TURN, "cycles": False, "post": "fanuc"})["data"]["programs"][0]["release"]["text"]
    assert progdiff.detect(fg) == "fagor" and progdiff.detect("%1001\nG21 G18\n") == "hnc"
    iso = postproc.to_fanuc(fg, "fagor", True)
    assert "T0101" in iso and "G50 S3000" in iso and "G33" not in iso
    res = progdiff.compare(fg, fa, machines.get("EX-LATHE"))
    assert res["same"] and res["controllers"] == ["fagor", "fanuc"], res
