# -*- coding: utf-8 -*-
"""可制造性检查（第 88 轮）：提交的驱动板全部通过；故意改坏能报出来。要 KiCad 7 的 pcbnew 模块（CI 的 KiCad 步骤里跑）。"""
import os
import sys

import pytest

pcbnew = pytest.importorskip("pcbnew")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import dfm  # noqa: E402
import drv_joint as D  # noqa: E402

PCB = os.path.join(os.path.dirname(HERE), "drv-joint", "kicad", "drv-joint.kicad_pcb")


def _check(board, **cap):
    return {c["key"]: c for c in dfm.check(PCB, D, cap or None, board=board)["checks"]}


def test_committed_board_passes():
    r = dfm.check(PCB, D)
    assert r["pass"], [c for c in r["checks"] if not c["pass"]]


def test_tighter_spacing_rule_is_reported():
    b = pcbnew.LoadBoard(PCB)
    r = _check(b, space_min=0.4)                      # 板厂只能做 0.4 mm 线距：报出来
    assert not r["track_space"]["pass"] and r["track_space"]["at"]


def test_thin_track_and_missing_testpoint_are_reported():
    b = pcbnew.LoadBoard(PCB)
    t = next(t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK")
    t.SetWidth(pcbnew.FromMM(0.1))
    for fp in b.GetFootprints():                       # 去掉一个网络的测试点和过孔（把它们的网络清空）
        if fp.GetReference().startswith("TP1") and fp.GetLayer() == pcbnew.B_Cu:
            net = fp.Pads()[0].GetNetname()
            fp.Pads()[0].SetNetCode(0)
            for v in b.GetTracks():
                if v.GetClass() == "PCB_VIA" and v.GetNetname() == net:
                    v.SetNetCode(0)
            break
    r = _check(b, ict_coverage_min=1.0)
    assert not r["track_width"]["pass"]
    assert not r["ict"]["pass"] and net in r["ict"]["detail"]


def test_flipped_diode_is_reported():
    b = pcbnew.LoadBoard(PCB)
    b.FindFootprintByReference("D2").SetOrientationDegrees(270)
    assert not _check(b)["polarity"]["pass"]


def test_narrow_power_path_is_reported():
    b = pcbnew.LoadBoard(PCB)
    for t in b.GetTracks():
        if t.GetClass() == "PCB_TRACK" and t.GetNetname().startswith("MOT_A"):
            t.SetWidth(pcbnew.FromMM(1.0))
    assert not _check(b)["current"]["pass"]
