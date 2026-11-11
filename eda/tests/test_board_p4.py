# -*- coding: utf-8 -*-
"""第 111 轮 P4：板子层新字段、通用板子生成、工艺检查补齐、布局约束、热、读回、板子模型文件、报告。
要 KiCad（pcbnew）的用例在没有 KiCad 时跳过；热分析要 CalculiX（ccx），没有时跳过。故意改坏的例子都要查出来。"""

import copy
import dataclasses
import math
import os
import shutil
import warnings

import pytest
from conftest import DESIGNS, EDA, EXAMPLE_CAP
from shapely import affinity

from wqeda import parts
from wqeda.checks import layout, process
from wqeda.model import Feature
from wqeda.schema import capability
from wqeda.schema import design as D

A = os.path.join(DESIGNS, "drv-joint", "design.yaml")
B = os.path.join(DESIGNS, "drv-joint-b", "variant.yaml")
V24 = os.path.join(EDA, "examples", "drv-joint-24v", "variant.yaml")
A_PCB = os.path.join(DESIGNS, "drv-joint", "kicad", "drv-joint.kicad_pcb")
A_OUT = os.path.join(DESIGNS, "drv-joint", "out")
MODEL = os.path.join(DESIGNS, "drv-joint", "report", "board-model.json.gz")
try:
    import pcbnew  # noqa: F401

    HAS_KICAD = True
except ImportError:
    HAS_KICAD = False
kicad = pytest.mark.skipif(not HAS_KICAD, reason="要 KiCad 7 的 pcbnew 模块")
ccx = pytest.mark.skipif(shutil.which(os.environ.get("WQ_CCX", "ccx")) is None, reason="要 CalculiX（ccx）")


@pytest.fixture(scope="module")
def cap():
    return capability.load(EXAMPLE_CAP)


@pytest.fixture(scope="module")
def xa():
    return D.expand(D.load_design(A))


@pytest.fixture(scope="module")
def board():
    """A 版的板子模型：从仓库里的板子模型文件读（不需要 KiCad）"""
    from wqeda import model_io

    return model_io.load(MODEL)


def _with(board, **kw):
    b = copy.copy(board)
    for k, v in kw.items():
        setattr(b, k, v)
    return b


def _status(rows, key):
    return next(r for r in rows if r["key"] == key)


# ------------------------------------------------------------------------------------------------- 设计描述


def test_net_classes_follow_the_board(xa):
    """网络分类从 build.py 迁进设计描述：A 版与原来写死的一字不差；+1V8 只在 B 版出现"""
    from wqeda.gen.board import classes_of

    old = {
        "Power": (2.5, 0.3, ["VBUS", "MOT_A", "MOT_B", "MOT_C"], ["F.Cu", "B.Cu"]),
        "Branch": (0.5, 0.3, ["SW_A", "SW_B", "SW_C"], ["F.Cu", "B.Cu"]),
        "Supply": (0.25, 0.15, ["+12V", "+5V", "+3V3", "SW12", "VB_A", "VB_B", "VB_C"], ["F.Cu", "In2.Cu", "B.Cu"]),
        "Ground": (0.25, 0.15, ["GND"]),
    }
    assert classes_of(xa) == old
    xb = D.expand(*D.load_variant(B))
    assert classes_of(xb)["Supply"][2] == old["Supply"][2] + ["+1V8"]


def test_high_current_follows_spec():
    doc = D.load_design(A)
    assert D.expand(doc)["high_current"]["MOT_A"] == 8.5
    doc["spec"]["phase_current_a"] = 15.0
    x = D.expand(doc)
    assert x["high_current"]["MOT_A"] == 15.0 and x["high_current"]["VBUS"] == 9.0


def test_board_fields_are_validated():
    doc = D.load_design(A)
    bad = copy.deepcopy(doc)
    bad["board"]["constraints"].append({"key": "x", "kind": "near", "ref": "C40", "to": "U99", "pin": "1", "max_mm": 3})
    bad["board"]["constraints"].append({"key": "y", "kind": "spiral", "source": "示例值"})
    bad["board"]["stackup"]["source"] = ""
    bad["board"]["thermal"]["heat"].append({"model": "laser", "refs": ["Q1"]})
    bad["circuit"]["nets"]["high_current"]["MOT_A"] = "spec.no_such_field"
    p = D.validate_design(bad)
    assert any("U99" in x for x in p) and any("spiral" in x or "kind" in x for x in p)
    assert any("stackup" in x for x in p) and any("model" in x for x in p) and any("no_such_field" in x for x in p)
    assert any("source" in x for x in p)  # 约束 x 没写出处
    assert D.validate_design(doc) == []


# ------------------------------------------------------------------------------------------------- 工艺检查


def test_process_checks_on_drive_board(board, cap, xa):
    rows = process.run(board, cap, xa)
    st = {r["key"]: r["status"] for r in rows}
    assert st == {"F2": "pass", "F4": "pass", "F6": "pass", "F7": "pass", "F8": "pass", "T1": "pass", "C1": "pass"}
    assert _status(rows, "T1")["value"] == pytest.approx(0.959, abs=0.001)
    assert _status(rows, "F2")["value"] >= 0.127


def _track(board, net, layer="F"):
    return next(f for f in board.features if f.kind == "track" and f.net == net and f.layer == layer)


def test_broken_boards_are_caught(board, cap, xa):
    feats = list(board.features)
    # F2：一根走线中段旁边 0.09 mm 处放一小块别的网络的细铜。只取中段那一小块：整圈围住会压在同网络相邻的走线上，
    # 和这个网络连成一块，量不出间距（第 129 轮重新布线后原来那段走线就是这样）
    def sliver(f):
        return f.geom.buffer(0.10).exterior.buffer(0.01).intersection(f.geom.centroid.buffer(0.4))

    others = [f for f in feats if f.layer == "F" and f.kind != "opening"]
    t = next(
        f
        for f in sorted(feats, key=lambda f: -f.geom.length)
        if f.kind == "track" and f.net == "PWM_AH" and f.layer == "F"
        and not any(g.geom.intersects(sliver(f)) for g in others)
    )
    b = _with(board, features=feats + [Feature("F", sliver(t), "track", "X", width=0.02)])
    r = process.f2_space(b, cap)
    assert r["status"] == "fail" and r["value"] < 0.127 and r["count"] >= 1
    # F4：两个开窗之间只留 0.05 mm 阻焊
    o = next(f for f in feats if f.kind == "opening" and f.layer == "F.Mask")
    o2 = affinity.translate(o.geom, xoff=(o.geom.bounds[2] - o.geom.bounds[0]) + 0.05)
    b = _with(board, features=feats + [Feature("F.Mask", o2, "opening")])
    assert process.f4_mask(b, cap)["status"] == "fail"
    # F6：把一个器件外框挪到另一个上
    cy = dict(board.courtyards)
    side, g40 = cy["C40"]
    cy["C41"] = (side, g40)
    assert process.f6_overlap(_with(board, courtyards=cy))["status"] == "fail"
    # F8：器件外框贴到板边
    cy = dict(board.courtyards)
    x0, y0, _, _ = board.outline_geom.bounds
    side, gj = cy["J3"]
    cy["J3"] = (side, affinity.translate(gj, xoff=x0 - gj.bounds[0] + 0.1))
    assert process.f8_part_edge(_with(board, courtyards=cy), cap)["status"] == "fail"
    # F7：把一个二极管转 180°
    comps = [dataclasses.replace(c, rot=180.0) if c.ref == "D1" else c for c in board.components]
    assert process.f7_polarity(_with(board, components=comps), xa)["status"] == "fail"
    # T1：要求 100% 覆盖（SW 三个网络扎不到）
    x = dict(xa, rules=dict(xa["rules"], ict_coverage_min=1.0))
    assert process.t1_ict(board, x)["status"] == "fail"
    # C1：额定相电流改到 15 A，电机线不够宽
    doc = D.load_design(A)
    doc["spec"]["phase_current_a"] = 15.0
    r = process.c1_current(board, D.expand(doc))
    assert r["status"] == "fail" and "MOT_A" in r["detail"]


def test_missing_data_is_unknown_not_pass(board, cap, xa):
    nets_off = _with(board, has_nets=False, courtyards={})
    st = {r["key"]: r["status"] for r in process.run(nets_off, cap, xa)}
    assert st["T1"] == st["C1"] == st["F6"] == st["F8"] == "unknown"
    x = dict(xa, stackup={})
    assert process.c1_current(board, x)["status"] == "unknown"
    assert process.f7_polarity(board, None)["status"] == "unknown"
    empty = {"format": "wqeda.capability/1", "factory": "x", "pcb": {}}
    assert {r["status"] for r in process.run(board, empty, xa)[:2]} == {"unknown"}


@kicad
def test_two_paths_agree_on_shared_items(cap, xa):
    from wqeda.readers import gerber, kicad as kr

    k = kr.read(A_PCB)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        g = gerber.read(
            os.path.join(A_OUT, "gerber.zip"), os.path.join(A_OUT, "bom.csv"), os.path.join(A_OUT, "pos.csv")
        )
    rk = {r["key"]: r for r in process.run(k, cap, xa)}
    rg = {r["key"]: r for r in process.run(g, cap, xa)}
    for key in ("F2", "F4", "F7"):
        assert rk[key]["status"] == rg[key]["status"] == "pass"
    assert rk["F2"]["value"] == pytest.approx(rg["F2"]["value"], abs=0.01)
    assert rk["F4"]["value"] == pytest.approx(rg["F4"]["value"], abs=0.01)
    for key in ("F6", "F8", "T1", "C1"):  # 光绘里没有器件外框、没有网络
        assert rg[key]["status"] == "unknown"


# ------------------------------------------------------------------------------------------------- 布局约束


def test_layout_constraints_on_drive_board(board, xa):
    rows = {r["key"]: r for r in layout.run(board, xa)}
    assert all(rows["L-loop-" + p]["status"] == "pass" for p in "ABC")
    assert all(rows["L-kelvin-" + p]["status"] == "pass" for p in "ABC")
    assert rows["L-apart-hot"]["status"] == rows["L-edge-conn"]["status"] == "pass"
    # 第 111 轮查出五个去耦电容离电源脚超过 3 mm（C27–C29 6.7 mm、C42 3.5 mm、C45 3.0 mm），第 129 轮挪近后全部通过
    assert all(r["status"] == "pass" for r in rows.values()), [k for k, r in rows.items() if r["status"] != "pass"]
    assert rows["L-near-C27"]["value"] == pytest.approx(0.78, abs=0.02)
    assert rows["L-near-C45"]["value"] < 3


def _move(board, ref, dx, dy):
    feats = [
        dataclasses.replace(f, geom=affinity.translate(f.geom, dx, dy)) if f.ref == ref else f for f in board.features
    ]
    cy = dict(board.courtyards)
    if ref in cy:
        cy[ref] = (cy[ref][0], affinity.translate(cy[ref][1], dx, dy))
    return _with(board, features=feats, courtyards=cy)


def test_broken_layouts_are_caught(board, xa):
    def one(b, key):
        return {r["key"]: r for r in layout.run(b, xa)}[key]["status"]

    assert one(_move(board, "C40", -6, 0), "L-near-C40") == "fail"  # 去耦电容挪远
    assert one(_move(board, "NT1", 0, 8), "L-kelvin-A") == "fail"  # 采样线不从电阻焊盘引出
    assert one(_move(board, "C11", 0, -25), "L-loop-A") == "fail"  # 吸收电容挪远，回路变大
    assert one(_move(board, "C1", 14, -6), "L-apart-hot") == "fail"  # 电解电容挪到功率管旁边
    assert one(_move(board, "J3", 0, 25), "L-edge-conn") == "fail"  # 接插件挪到板子中间
    assert {r["status"] for r in layout.run(_with(board, has_nets=False), xa)} == {"unknown"}


# ------------------------------------------------------------------------------------------------- 热


def _k0(x):
    """K0(x) = ∫0^∞ exp(−x·cosh t) dt（梯形积分；不靠 scipy）"""
    n, h = 4000, 12.0 / 4000
    return h * (0.5 * math.exp(-x) + sum(math.exp(-x * math.cosh(i * h)) for i in range(1, n + 1)))


@ccx
def test_thermal_standard_problems():
    """标准题一：均匀发热平板两面对流，T = Ta + q/(2h)；标准题二：大平板中心点热源，θ(r) = P/(2πkt)·K0(r/L)，
    L = √(kt/2h)（四分之一模型）。误差都要 ≤ 5%"""
    from wqeda.thermal import ccx as run
    from wqeda.thermal import plate

    nx, ny, dx, t = 20, 10, 2.0, 1.6
    k = {(i, j): (20.0, 20.0) for i in range(nx) for j in range(ny)}
    q = {c: 2.0 / (nx * ny) for c in k}
    T = plate.cell_temps(run.run(plate.deck(nx, ny, dx, t, k, q, 10.0, 25.0)), nx, ny)
    exact = 25 + (2.0 / (nx * ny * dx * dx * 1e-6)) / (2 * 10)
    assert max(T.values()) == pytest.approx(exact, rel=0.05) and min(T.values()) == pytest.approx(exact, rel=0.05)
    nx = ny = 200
    kk, h = 20.0, 10.0
    k = {(i, j): (kk, kk) for i in range(nx) for j in range(ny)}
    nt = run.run(plate.deck(nx, ny, 1.0, t, k, {(0, 0): 0.25}, h, 0.0))
    L = math.sqrt(kk * t * 1e-3 / (2 * h)) * 1e3
    for r in (5, 10, 20, 40):
        th = 1.0 / (2 * math.pi * kk * t * 1e-3) * _k0(r / L)
        assert nt[plate.node_id(r, 0, 1, nx, ny)] == pytest.approx(th, rel=0.05)


def test_losses_match_hand_calculation(xa):
    """导通 8.5² × 4 mΩ = 0.289 W；开关：驱动器最小 0.13 A / 0.27 A 先限住，
    t = 15 nC / 0.13 A + 15 nC / 0.27 A = 171 ns，½ × 48 × 8.5 × 171 ns × 20 kHz = 0.698 W；采样电阻 8.5² × 2 mΩ"""
    from wqeda.thermal import board as tb

    rows = {r["ref"]: r for r in tb.losses(D.load_design(A), xa, parts.Devices.load())}
    q1 = dict(rows["Q1"]["parts"])
    assert q1["导通 I²·R_DS(on)"] == pytest.approx(8.5**2 * 0.004)
    t_sw = 15e-9 / 0.13 + 15e-9 / 0.27
    assert q1["开关 ½·V·I·(t_on+t_off)·f"] == pytest.approx(0.5 * 48 * 8.5 * t_sw * 20000)
    assert rows["R21"]["p_w"] == pytest.approx(8.5**2 * 0.002)
    assert rows["Q1"]["status"] == "pending"  # 器件数据没核对


@ccx
def test_board_thermal_judgement(board, xa):
    """R_DS(on) 只有 25 ℃ 的值：没超上限的判“未知”（损耗偏低），超了的判“不通过”；从不判“通过”"""
    from wqeda.thermal import board as tb

    r = tb.solve(board, D.load_design(A), xa, parts.Devices.load(), dx=2.0)
    fets = [x for x in r["rows"] if x["model"] == "mosfet"]
    assert len(fets) == 6 and all(x["tj_c"] > x["t_board_c"] for x in fets)
    assert {x["status"] for x in fets} <= {"unknown", "fail"}
    assert all(x["status"] == "fail" for x in fets if x["tj_c"] > x["tj_max_c"])
    assert r["total_w"] == pytest.approx(6 * (8.5**2 * 0.004 + 0.698) + 3 * 8.5**2 * 0.002, abs=0.01)


# ------------------------------------------------------------------------------------------------- 读回、板子模型文件


@kicad
def test_readback(tmp_path):
    import pcbnew

    from wqeda import readback

    doc = D.load_design(A)
    same = readback.compare(readback.read_kicad(A_PCB), doc)
    assert same["none"], readback.describe(same)
    b = pcbnew.LoadBoard(A_PCB)
    fp = b.FindFootprintByReference("C40")
    fp.SetPosition(pcbnew.VECTOR2I(fp.GetPosition().x + pcbnew.FromMM(1.5), fp.GetPosition().y))
    b.FindFootprintByReference("R30").SetOrientationDegrees(90)
    y1 = b.FindFootprintByReference("Y1")
    y1.Flip(y1.GetPosition(), False)
    path = str(tmp_path / "moved.kicad_pcb")
    pcbnew.SaveBoard(path, b)
    ch = readback.compare(readback.read_kicad(path), doc)
    moved = {m["ref"]: m for m in ch["moved"]}
    assert set(moved) == {"C40", "R30", "Y1"} and not ch["nets"]
    assert moved["C40"]["to"][0] == pytest.approx(moved["C40"]["from"][0] + 1.5)
    assert moved["R30"]["to"][2] == 90 and moved["Y1"]["to"][3] == "B"
    text = readback.patch(open(A, encoding="utf-8").read(), ch)
    new = D.read_yaml_text(text)
    assert D.validate_design(new) == []
    x = D.expand(new)
    assert tuple(x["placement"]["Y1"]) == tuple(moved["Y1"]["to"])
    assert "# 布局约束（第 111 轮）" in text  # 注释原样保留
    again = readback.compare(readback.read_kicad(path), new)
    assert again["none"]


@kicad
def test_board_model_file_is_current():
    """仓库里的板子模型文件（起草台用）和 KiCad 板子文件一致。按内容比（形状允许 0.002 mm 的差），不比字节：
    不同机器上 KiCad 把圆弧变多边形、shapely 写 WKB 的结果字节可以不同。不一致时只报第一处，不打印整个文件"""
    from wqeda import model_io
    from wqeda.readers import kicad as kr

    fresh = model_io.from_dict(model_io.to_dict(kr.read(A_PCB)))  # 和写文件时一样取整到 0.001 mm
    saved = model_io.load(MODEL)
    hint = "板子改了：重新运行 python3 -m wqeda.model_io 写出板子模型文件"
    assert len(fresh.features) == len(saved.features), hint
    for a, b in zip(fresh.features, saved.features, strict=True):
        same = (a.layer, a.kind, a.net, a.ref, a.pad, a.width) == (b.layer, b.kind, b.net, b.ref, b.pad, b.width)
        assert same and a.geom.hausdorff_distance(b.geom) < 0.002, "{}：{} {} {}".format(hint, a.layer, a.kind, a.ref)
    assert sorted(fresh.courtyards) == sorted(saved.courtyards), hint
    assert [(c.ref, c.x, c.y, c.rot, c.side) for c in fresh.components] == [
        (c.ref, c.x, c.y, c.rot, c.side) for c in saved.components], hint


def test_board_model_roundtrip(board, cap, xa):
    from wqeda import model_io

    again = model_io.from_dict(model_io.to_dict(board))
    assert [r["status"] for r in process.run(again, cap, xa)] == [r["status"] for r in process.run(board, cap, xa)]


# ------------------------------------------------------------------------------------------------- 报告


@kicad
def test_report_counts_everything(tmp_path):
    from wqeda import report

    rep = report.build(A, EXAMPLE_CAP, sim=False, thermal=False, drc=os.path.join(A_OUT, "drc.json"))
    n = rep["count"]
    keys = [r["key"] for r in rep["process"]]
    assert {"D1", "F1", "F2", "F4", "F6", "F7", "F8", "T1", "C1", "K1"} <= set(keys)
    assert n["fail"] == 0 and n["pass"] > 0  # 第 129 轮去耦电容挪近后，不算热就没有不通过
    assert rep["status"] != "pass"  # 还有待核对、未知，不能判通过
    report.write(str(tmp_path), rep)
    assert "板子报告" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert (tmp_path / "calc.html").exists() is False
