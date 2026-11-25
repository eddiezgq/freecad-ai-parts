"""问渠CAM E3 NUM Flexium / Flexium+ 后处理（ADR-0127，ADR-0106 E3）：按 NUM 官网《Flexium Programming Manual》M00018EN-03 写——
% 程序号、G71 公制、G92 S 限速、G97 S M03 + G96 X S 恒线速、G95 每转进给、T D M06、G38 … K 车螺纹、D 长度补偿、G84 Z K 刚性攻丝、
G00 G52 Z0 回 Z 零点、M02 结束；FANUC 写法里在 NUM 上意思不同的代码（G21、G49、G43、G50、G99、M29、G28、G32、M30）一个都不能留。
回读按同一张对照表换回 FANUC 写法与仿真比。"""

from __future__ import annotations

import json
import re

import pytest

from analysis import cam
from analysis.cam import machines, num, postcfg, postproc, progdiff, rs274
from tests import test_cam_millturn_c2b as MT
from tests import test_cam_post_q5 as Q5
from tests.verification import record_verdict

BAD = ("G21", "G49", "G43", "G50", "G99", "G98", "M29", "G28", "G32", "M30", "G02", "G03")


def _codes(t):
    body = "\n".join(re.sub(r"\([^)]*\)", "", ln) for ln in t.splitlines())
    return {f"G{int(g):02d}" for g in re.findall(r"\bG(\d+)", body)} | {f"M{int(m):02d}" for m in re.findall(r"\bM(\d+)", body)}


def _rel(p):
    assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
    return p["release"]["text"]


def test_num_lathe_written_per_manual(tmp_path, monkeypatch):
    """外圆粗精车、切槽、车螺纹：能出、回读一致；没有 FANUC 那几个在 NUM 上意思不同的代码；车削时间与同样关掉循环的 FANUC 相同（写法不同、刀路相同）"""
    d = tmp_path / "posts"
    d.mkdir()
    monkeypatch.setenv("FAP_POSTS", str(d))
    (d / "fa1.json").write_text(json.dumps({"format": "cam-post/1", "id": "fa1", "name": "fa1", "family": "fanuc", "kinds": ["lathe"],
                                            "source": "t", "cycles": {"drill": False, "turn": False}}), encoding="utf-8")
    base = [p["time"]["total_s"] for p in cam.run({**Q5.TURN, "post": "fa1"})["data"]["programs"]]
    progs = cam.run({**Q5.TURN, "post": "num-flexium"})["data"]["programs"]
    for p in progs:
        t = _rel(p)
        assert re.match(r"^%\d{4} \(WENQUEST CAM\)\n\(NUM: X IN DIAMETER", t)
        assert "G71 G18 G40 G97 G95" in t and re.search(r"^T1 D1 M06$", t, re.MULTILINE) and "G92 S3000" in t
        assert "G97 S796 M03\nG96 X48.0 S120\nG00 X48.0 Z2.0 M08" in t       # 120 m/min 在 Ø48 上 = 795.8 → 796 rpm
        assert not _codes(t) & set(BAD), _codes(t) & set(BAD)
        assert t.rstrip().endswith("M05\nM02")
    assert "G38 Z-16.0 K1.5" in "\n".join(_rel(p) for p in progs)
    assert [p["time"]["total_s"] for p in progs] == pytest.approx(base)
    record_verdict(("NUM 车床：按 NUM 官方编程手册写（% 程序号、G71 公制、G92 S、G97 + G96 X、T D M06、G38 K、M02），回读一致",
                    "NUM lathe: written per the NUM programming manual (% number, G71 metric, G92 S, G97 + G96 X, T D M06, G38 K, M02), read-back matches"),
                   "pass", "pass")


def test_num_mill_tool_length_tap_and_home():
    """开槽、钻孔、攻丝：T D M06，换刀后第一次 Z 不写 G43 / H（长度补偿随 D）；攻丝 S G84 Z K（螺距 = F ÷ S）；回 Z 零点 G00 G52 Z0；
    冷却 M08 / M09 照写（NUM 手册表里有）；时间与 FANUC 相同"""
    p = Q5._mill("num-flexium")
    t = _rel(p)
    assert "T1 D1 M06" in t and "T5 D5 M06" in t and "G71 G17 G40 G80 G90 G94" in t
    assert "G00 X20.0 Y45.0\nG00 Z3.0\nS400 G84 Z-15.0 K1.5\nG80\nG00 Z5.0" in t
    assert t.rstrip().endswith("G00 G52 Z0\nG90\nM02") and "M08" in t and "M09" in t
    assert not _codes(t) & set(BAD), _codes(t) & set(BAD)
    assert p["time"]["total_s"] == pytest.approx(Q5._mill("fanuc")["time"]["total_s"])
    record_verdict(("NUM 铣床：长度补偿随 D、G84 Z K 刚性攻丝、G52 回 Z 零点，回读一致",
                    "NUM mill: length offset via D, G84 Z K rigid tapping, G52 Z home, read-back matches"), "pass", "pass")


def test_round_trip_back_to_fanuc_line_by_line():
    """对照表可逆：FANUC 原文 → NUM → FANUC，逐行一模一样（顺序号也在）"""
    for lathe, text in ((True, ("%\nO1001 (WENQUEST CAM)\n(X)\nG21 G18 G40 G97 G99\nN10 T0101\nN20 G50 S3000\nN30 G96 S120 M03\n"
                                "G00 X48.0 Z2.0 M08\nN40 G32 Z-16.0 F1.5\nN50 G01 X40.0 F0.2\nT0102\nG96 S150 M04\nX0.5 Z1.0\nM30\n%\n")),
                        (False, ("%\nO6001 (WENQUEST CAM)\nG21 G17 G40 G49 G80 G90 G94\nT4 M06\nG54\nS400 M03\nG00 X20.0 Y45.0\n"
                                "G43 Z5.0 H04 M08\nM29 S400\nG98 G84 X20.0 Y45.0 Z-15.0 R3.0 F600.0\nG80\nG00 Z5.0 M09\nM05\n"
                                "G91 G28 Z0.0\nG90\nM30\n%\n"))):
        nm = num.to_num(text, lathe)
        back = num.to_fanuc(nm, lathe)
        want = [ln for ln in text.strip().split("\n") if ln != "%"]
        assert back.strip().split("\n") == want, (nm, back)
    nm = num.to_num("O1001\nG21 G18 G40 G97 G99\nT0102\nG50 S3000\nG96 S150 M04\nX0.5 Z1.0\nM30\n", True)
    assert "T1 D2 M06" in nm and "G97 S3000 M04\nG96 X0.5 S150" in nm       # Ø0.5 上算出 95493 rpm，受 G92 S3000 限速


def test_num_refusals():
    """不按手册写不出：G96 后面那一段没有 X、程序号 ≥ 9000、铣床换刀后长度补偿 H 号不是刀号、表外代码（G02、G04、G92 X）"""
    with pytest.raises(num.NumError, match="当前直径"):
        num.to_num("O1001\nG21 G18\nG96 S120 M03\nG00 Z2.0\n", True)
    with pytest.raises(num.NumError, match="9000"):
        num.to_num("O9001\nG21 G18\n", True)
    with pytest.raises(num.NumError, match="H05"):
        num.to_num("O6001\nG21 G17 G40 G49\nT5 M06\nG43 Z5.0 H06\n", False)
    for bad, code in (("G02 X10.0 Y0.0 I5.0 J0.0", "G2"), ("G04 F1.0", "G4"), ("G92 X0.0", "G92")):
        with pytest.raises(num.NumError, match=code):
            num.check_codes(f"G71 G17\n{bad}\nM02\n", False)
    with pytest.raises(num.NumError, match="换不回"):
        num.to_fanuc("%1001\nG71 G17 G40 G80 G90 G94\nG38 Z1.0 K1.5\n", False)


def test_mill_turn_not_output():
    """车铣（动力刀、C 轴）：还没做——配置不收；程序里出现 G12.1 等按代码表拒出、写明“NUM 车铣还没做”"""
    with pytest.raises(postcfg.PostConfigError, match="车铣"):
        postcfg.check({"format": "cam-post/1", "id": "n", "name": "n", "family": "num", "kinds": ["lathe"], "source": "t",
                       "millturn": {"live_on": ["M45"]}}, "t")
    with pytest.raises(num.NumError, match="NUM 车铣还没做"):
        num.check_codes("G18\nG12.1\nG01 X10.0 C0.0\nG13.1\n", True)
    assert MT._run_mt("num-flexium")["release"] is None


def test_code_outside_manual_table_refused(tmp_path, monkeypatch):
    """配置的换刀前动作写了 G28（NUM 没有）：程序不出、点名 G28；换刀后动作写的机床 M 代码（用户按机床说明书填）照认"""
    d = tmp_path / "posts"
    d.mkdir()
    monkeypatch.setenv("FAP_POSTS", str(d))
    cfg = json.loads((postcfg.BUILTIN / "num-flexium.json").read_text(encoding="utf-8"))
    (d / "n1.json").write_text(json.dumps({**cfg, "id": "n1", "tool_change": {"before": ["G28 U0.0"], "after": []}}), encoding="utf-8")
    p = cam.run({**Q5.TURN, "post": "n1"})["data"]["programs"][0]
    assert p["release"] is None and any("G28" in c["text"] for c in p["checks"] if c["level"] == "error")
    (d / "n2.json").write_text(json.dumps({**cfg, "id": "n2", "tool_change": {"before": [], "after": ["M41"]}}), encoding="utf-8")
    t = _rel(cam.run({**Q5.TURN, "post": "n2"})["data"]["programs"][0])
    assert "T1 D1 M06\nM41" in t
    record_verdict(("NUM：手册代码表外的代码不出、点名", "NUM: codes outside the manual's table are refused and named"), "error", "error")


@pytest.mark.parametrize("extra,msg", [
    ({"dialect": {"tool_call_lathe": "T{n}", "sources": [{"item": "tool_call_lathe", "doc": "x", "version": "x", "section": "x"}]}}, "不收 dialect"),
    ({"cycles": {"drill": False, "turn": True}}, "G70 / G71"),
    ({"cycles": {"drill": True, "turn": False}}, "G70 / G71"),
    ({"subprograms": True}, "子程序"),
])
def test_bad_num_configs_named(extra, msg):
    cfg = {"format": "cam-post/1", "id": "n", "name": "n", "family": "num", "kinds": ["lathe", "mill"], "source": "t", **extra}
    with pytest.raises(postcfg.PostConfigError, match=msg):
        postcfg.check(cfg, "t")


def test_progdiff_recognises_num():
    """程序比对认得出 NUM 程序（% 开头不再一律当华中），换回 FANUC 写法后与同一零件的 FANUC 程序刀路一样"""
    nm = _rel(cam.run({**Q5.TURN, "cycles": False, "post": "num-flexium"})["data"]["programs"][0])
    fa = cam.run({**Q5.TURN, "cycles": False, "post": "fanuc"})["data"]["programs"][0]["release"]["text"]
    assert progdiff.detect(nm) == "num" and progdiff.detect(_rel(Q5._mill("num-flexium"))) == "num"
    assert progdiff.detect("%1001\nG21 G18\n") == "hnc" and progdiff.detect(_rel(Q5._mill("fagor-8065"))) == "fagor"
    iso = postproc.to_fanuc(nm, "num", True)
    assert "T0101" in iso and "G50 S3000" in iso and "G96 S120 M03" in iso and "G38" not in iso
    res = progdiff.compare(nm, fa, machines.get("EX-LATHE"))
    assert res["same"] and res["controllers"] == ["num", "fanuc"], res


@pytest.mark.skipif(rs274.find() is None, reason="没有 rs274")
def test_num_lathe_matches_rs274():
    """L2：换回的 FANUC 程序交 LinuxCNC 解释器读，与问渠CAM 自己的刀路一致"""
    for p in cam.run({**Q5.TURN, "post": "num-flexium"})["data"]["programs"]:
        text = postproc.to_fanuc(p["release"]["text"], "num-flexium", True)
        res = rs274.compare(text, True, machines.get("EX-LATHE"), own_text=p["gcode"])
        assert res["ok"], res


def test_num_config_cites_manual():
    c = json.loads((postcfg.BUILTIN / "num-flexium.json").read_text(encoding="utf-8"))
    assert c["family"] == "num" and "M00018EN-03" in c["source"] and c.get("verified") is not True
    assert set(num.CODES_G) >= {"71", "92", "96", "38", "52", "84"} and "30" not in num.CODES_M
