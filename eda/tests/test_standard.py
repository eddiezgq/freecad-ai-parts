# -*- coding: utf-8 -*-
"""标准题：手写的小光绘文件、物料清单和坐标，线宽、孔径、孔环、铜到板边、位号都是已知的，检查结果要和手算一致。

板子 20 × 10 mm。坏板：0.1 mm 的线、0.2 mm 的孔配 0.45 mm 的焊盘（孔环 0.125）、一个 0.2 mm 焊盘中心离右边 0.15 mm
（铜到板边 0.05）；物料清单 R1 R2（写 2）、C1（写 2，只有 1 个位号）；坐标 R1、R3，R3 写在底面而附近焊盘只在顶面。
好板：0.2 mm 的线、0.3 mm 的孔配 0.7 mm 焊盘（孔环 0.2）；离板边最近的铜是 y = 1 那条 0.2 mm 的线，
铜到板边 1 − 0.1 = 0.9 mm；位号、数量、面都对。"""
import os

import pytest
from conftest import EXAMPLE_CAP

from wqeda.checks import basic
from wqeda.readers import gerber
from wqeda.schema import capability

BOM_HEAD = ["物料编号", "数值", "封装", "数量", "位号"]
POS_HEAD = ["Ref", "Val", "Package", "PosX", "PosY", "Rot", "Side"]
HEAD = "%TF.GenerationSoftware,KiCad,Pcbnew,7.0.11*%\n%TF.FileFunction,{}*%\n%FSLAX46Y46*%\n%MOMM*%\n%LPD*%\n"


def _um(v):
    return str(int(round(v * 1e6)))


def gbr(func, apertures, draws):
    s = HEAD.format(func)
    for code, d in apertures.items():
        s += "%ADD{}C,{:.6f}*%\n".format(code, d)
    for code, ops in draws:
        s += "D{}*\n".format(code)
        for x, y, op in ops:
            s += "X{}Y{}D0{}*\n".format(_um(x), _um(y), op)
    return s + "M02*\n"


def write_board(dirpath, track_w, drill, pad, edge_pad):
    os.makedirs(dirpath, exist_ok=True)
    outline = gbr("Profile,NP", {10: 0.1}, [(10, [(0, 0, 2), (20, 0, 1), (20, 10, 1), (0, 10, 1), (0, 0, 1)])])
    top = gbr("Copper,L1,Top", {10: track_w, 11: pad, 12: 0.2},
              [(10, [(1, 1, 2), (5, 1, 1)]), (11, [(8, 5, 3)]), (12, [(edge_pad, 5, 3)])])
    bot = gbr("Copper,L2,Bot", {11: pad}, [(11, [(8, 5, 3)])])
    drl = "M48\nMETRIC\nT1C{:.3f}\n%\nG90\nG05\nT1\nX8.0Y5.0\nM30\n".format(drill)
    files = {"t-Edge_Cuts.gm1": outline, "t-F_Cu.gtl": top, "t-B_Cu.gbl": bot, "t-PTH.drl": drl,
             # 阻焊、丝印层（空）：资料包通常都有，读光绘时按文件名认层要用到
             "t-F_Mask.gts": gbr("Soldermask,Top", {}, []), "t-B_Mask.gbs": gbr("Soldermask,Bot", {}, []),
             "t-F_Silkscreen.gto": gbr("Legend,Top", {}, []), "t-B_Silkscreen.gbo": gbr("Legend,Bot", {}, [])}
    for name, text in files.items():
        with open(os.path.join(dirpath, name), "w") as f:
            f.write(text)


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(",".join(r) for r in rows) + "\n")


@pytest.fixture
def cap():
    return capability.load(EXAMPLE_CAP)


def by_key(res):
    return {c["key"]: c for c in res["checks"]}


def test_bad_board(tmp_path, cap):
    write_board(tmp_path / "g", track_w=0.1, drill=0.2, pad=0.45, edge_pad=19.85)
    write_csv(tmp_path / "bom.csv", [BOM_HEAD, ["RES", "1k", "R_0402", "2", "R1 R2"],
                                     ["CAP", "1u", "C_0402", "2", "C1"]])
    write_csv(tmp_path / "pos.csv", [POS_HEAD, ["R1", "1k", "R_0402", "8", "5", "0", "top"],
                                     ["R3", "1k", "R_0402", "19.85", "5", "0", "bottom"]])
    b = gerber.read(str(tmp_path / "g"), str(tmp_path / "bom.csv"), str(tmp_path / "pos.csv"))
    assert b.outline == (0, 0, 20, 10) and b.copper_layers == 2
    r = by_key(basic.run(b, cap))
    assert r["F1"]["status"] == "fail" and r["F1"]["value"] == 0.1
    assert r["F3-drill"]["status"] == "fail" and r["F3-drill"]["value"] == 0.2
    assert r["F3-ring"]["status"] == "fail" and r["F3-ring"]["value"] == 0.125
    assert r["F5"]["status"] == "fail" and r["F5"]["value"] == pytest.approx(0.05)
    d1 = {tuple(a) for a in r["D1"]["at"]}
    assert r["D1"]["status"] == "fail"
    assert d1 == {("R2", "只在物料清单里"), ("C1", "只在物料清单里"), ("R3", "只在坐标里")}
    assert r["D2"]["status"] == "fail" and r["D2"]["count"] == 1
    assert r["D4"]["status"] == "fail" and r["D4"]["count"] == 1 and "R3" in r["D4"]["at"][0][2]


def test_good_board(tmp_path, cap):
    write_board(tmp_path / "g", track_w=0.2, drill=0.3, pad=0.7, edge_pad=15.0)
    write_csv(tmp_path / "bom.csv", [BOM_HEAD, ["RES", "1k", "R_0402", "2", "R1 R2"]])
    write_csv(tmp_path / "pos.csv", [POS_HEAD, ["R1", "1k", "R_0402", "8", "5", "0", "top"],
                                     ["R2", "1k", "R_0402", "15", "5", "0", "top"]])
    b = gerber.read(str(tmp_path / "g"), str(tmp_path / "bom.csv"), str(tmp_path / "pos.csv"))
    res = basic.run(b, cap)
    r = by_key(res)
    assert {k: c["status"] for k, c in r.items()} == {k: "pass" for k in r}
    assert r["F1"]["value"] == 0.2 and r["F3-ring"]["value"] == 0.2 and r["F5"]["value"] == pytest.approx(0.9)
    assert res["status"] == "pass"


def test_missing_capability_is_unknown_not_pass(tmp_path):
    write_board(tmp_path / "g", track_w=0.2, drill=0.3, pad=0.7, edge_pad=15.0)
    b = gerber.read(str(tmp_path / "g"))
    res = basic.run(b, {"format": capability.FORMAT, "factory": "空表", "pcb": {}})
    assert {c["key"]: c["status"] for c in res["checks"]} == {k: "unknown" for k in
                                                             ("D1", "D2", "D4", "F1", "F3-drill", "F3-ring", "F5")}
    assert res["status"] == "unknown" and "没有物料清单" in res["notes"]
