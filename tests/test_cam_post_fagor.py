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


FMT = {"format": "cam-post/1", "id": "fmt", "name": "Fagor mill-turn", "family": "fagor", "kinds": ["lathe"], "source": "t", "coolant": "off",
       "millturn": {"live_on": ["M45"], "live_off": ["M46"], "c_on": ["M18"], "c_off": ["M19"]}}
CYL = [{"t": "rapid", "x": 60, "c": 0, "z": -10}, {"t": "feed", "x": 44, "c": 0, "z": -10, "f": 100},
       {"t": "feed", "x": 44, "c": 90, "z": -10, "f": 200}, {"t": "feed", "x": 44, "c": 180, "z": -20, "f": 200},
       {"t": "rapid", "x": 60, "c": 180, "z": -20}]


def _run_fmt(tmp_path, monkeypatch, cyl_moves=None, cfg=None):
    d = tmp_path / "posts"
    d.mkdir(exist_ok=True)
    monkeypatch.setenv("FAP_POSTS", str(d))
    (d / "fmt.json").write_text(json.dumps(cfg or FMT), encoding="utf-8")
    pr = MT._mt_prog()
    if cyl_moves:
        pr["ops"][2]["moves"] = cyl_moves
    r = cam.run({"mode": "millturn", "machine": "EX-MT-CY", "program": pr, "stock": {"d": 52, "z_right": 0.5, "z_left": -60},
                 "post": "fmt", "machine_sim": {"tools": {}}})
    return r["data"]["programs"][0]


def test_fagor_mill_turn_face_and_cylinder(tmp_path, monkeypatch):
    """车铣（ADR-0131）：端面 G12.1 → G152、#CAX、#FACE [X,C,Q0]（X 半径、C mm），圆柱面 G7.1 C25 → #CYL [Z,C,X25.0,Q0]（C = 角度 × π ÷ 180 × 25：
    90° → 39.2699、180° → 78.5398），结尾 #… OFF、#CAX OFF、G151；进给照写（#CYL 的 F 也在给定半径上）；回读与仿真刀路一致"""
    t = _rel(_run_fmt(tmp_path, monkeypatch, CYL))
    assert not re.search(r"G12\.1|G13\.1|G0?7\.1|\bG9[89]\b", t)
    for frag in (("M18\nM45\nS2000\nG152\n#CAX\n#FACE [X,C,Q0]\nG00 X10.0 C-10.0 Z2.0\nG01 Z-3.0 F100.0\nC10.0 F200.0\nG00 Z2.0\n"
                  "#FACE OFF\n#CAX OFF\nG151\nM46\nM19\nG95"),
                 ("G152\n#CAX\n#CYL [Z,C,X25.0,Q0]\nG00 X30.0 C0.0 Z-10.0\nG01 X22.0 F100.0\nC39.2699 F200.0\nC78.5398 Z-20.0\nG00 X30.0\n"
                  "#CYL OFF\n#CAX OFF\nG151")):
        assert frag in t, frag
    back = postproc.to_fanuc(t, "fmt", True)
    assert "G07.1 C25.0\nG00 X60.0 C0.0 Z-10.0\nG01 X44.0 F100.0\nC90.0 F200.0\nC180.0 Z-20.0" in back and "G12.1\nG00 X20.0 C-10.0 Z2.0" in back
    record_verdict(("发格车铣：#CAX、#FACE、#CYL 按手册写（G152 明写半径），回读一致",
                    "Fagor mill-turn: #CAX, #FACE, #CYL per the manual (radius made explicit with G152), read-back matches"), "pass", "pass")


def _run_index(tmp_path, monkeypatch, angle):
    d = tmp_path / "posts"
    d.mkdir(exist_ok=True)
    monkeypatch.setenv("FAP_POSTS", str(d))
    (d / "fmt.json").write_text(json.dumps(FMT), encoding="utf-8")
    mv = MT.MT.flat_moves({"angle": angle, "r_outer": 25.0, "depth": 3.0,
                           "shape": {"type": "slot", "a": [0.0, -10.0], "b": [0.0, -30.0], "width": 12.0}}, 6.0, 3.0, 200.0, 100.0)
    live = {"right": [{"tool": {"n": 10, "d": 6.0}, "spindle": {"rpm": 3000}, "title": "平底槽", "interp": {"index": angle}, "moves": mv}]}
    r = cam.run({"mode": "turn", "machine": "EX-MT-CY", "segments": [[40, 30], [50, 40]], "live_ops": live, "post": "fmt",
                 "machine_sim": {"tools": {"10": {"tool": "EM6", "length_mm": 40}}, "chuck": {"jaw_len": 15, "jaw_d": 80}}})
    return r["data"]["programs"][0]


@pytest.mark.parametrize("angle,c", [(90.0, "C90.0"), (-60.0, "C300.0")])
def test_fagor_c_index_y_mill(tmp_path, monkeypatch, angle, c):
    """C 分度 + Y 轴铣（ADR-0133）：Ø50 上宽 12、深 3 的长圆平底槽；主轴当 C 轴先 #CAX（§18.1.1），完了 #CAX OFF；G19 同 FANUC（§4.2.1），
    X 在 G151 下仍是直径（§3.4）；分度角写成 0–360（发格普通回转轴绝对值的正负号是转向，§3.2.1：FANUC C-60 是 300° 的位置）；
    去料与积分值差 < 1%；回读与仿真刀路一致"""
    p = _run_index(tmp_path, monkeypatch, angle)
    assert p["sim"]["mill_removed_mm3"] == pytest.approx(MT._keyway_volume(w=12.0), rel=0.01)
    t = _rel(p)
    assert f"M45\nS3000\n#CAX\nG00 {c}\nG19" in t and "G00 Y0.0\nG18\n#CAX OFF\nM46" in t and not re.search(r"\bC-", t)
    assert "G00 X54.0 Y0.0 Z-10.0" in t                    # X 直径（Ø54 = 外圆 Ø50 外 2 mm）
    back = postproc.to_fanuc(t, "fmt", True)
    assert f"S3000\nG00 {c}\nG19" in back and "G18\nM46" in back and "#" not in back
    with pytest.raises(fagor.FagorError, match="ADR-0133"):
        fagor.to_fagor("O1001\nG21 G18 G40 G97 G99\nG01 C30.0 F100.0\nM30\n", True)
    if angle < 0:
        record_verdict(("发格 C 分度 + Y 轴铣：#CAX 后分度、G19 同 FANUC，负分度角写成 0–360（发格的正负号是转向），回读一致",
                        ("Fagor C-axis indexing + Y-axis milling: #CAX then index, G19 as FANUC, negative index angles written as 0-360 "
                         "(the sign is the direction on Fagor), read-back matches")),
                       "pass", "pass")


def test_fagor_mill_turn_refusals(tmp_path, monkeypatch):
    """不出：B 轴车铣配置、内置配置没写车铣行、坐标超过 4 位小数（§1.3.1）、本表外的 # 指令；G19 已按 ADR-0133 收"""
    fagor.check_codes("G71 G18\n#CAX\nG00 C30.0\nG19\nG18\n#CAX OFF\nM30\n", True)
    with pytest.raises(postcfg.PostConfigError, match="B 轴车铣"):
        postcfg.check({**FMT, "millturn": {**FMT["millturn"], "b_tool_comp": ["M99"]}}, "t")
    assert MT._run_mt("fagor-8065")["release"] is None
    with pytest.raises(fagor.FagorError, match="1.3.1"):
        fagor.check_codes("G71 G18\nG01 X10.12345 F0.1\nM30\n", True)
    with pytest.raises(fagor.FagorError, match="# 指令"):
        fagor.check_codes("G71 G18\n#FACE [X,C]\nM30\n", True)
    record_verdict(("发格车铣：没做的（B 轴）和超位数的不出、点名",
                    "Fagor mill-turn: unsupported cases (B axis) and excess decimals are refused and named"),
                   "error", "error")


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
