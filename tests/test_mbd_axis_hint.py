"""平面机构里个别转动副的轴写错时指出运动副。

《多体动力学》书线索第 76 条（问渠 CAD 0.3.9 细则）：四杆、曲柄滑块的第一个铰轴由 z 改成 x，原来抛数值库的
LinAlgError: Singular matrix，不指名运动副（0.3.6 的锁死检查之后，四杆报“锁死”、曲柄滑块报“还剩 1 个自由度”，仍不说是轴写错）。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_mbd_dead_point import _fourbar, _slider_crank

from analysis.mbd.dae.run import run_model
from analysis.mbd.dae.solve import SolveError


def test_four_bar_wrong_axis_named():
    m = _fourbar(100)
    m["joints"][0]["axis"] = [1, 0, 0]
    with pytest.raises(SolveError, match="运动副 R1 的轴与其余转动副"):
        run_model(m)


def test_slider_crank_wrong_axis_named():
    m = _slider_crank()
    m["joints"][0]["axis"] = [1, 0, 0]
    with pytest.raises(SolveError, match="运动副 R1、R2 的轴不平行"):
        run_model(m)


def test_planar_mechanism_no_hint():
    _, msgs = run_model(_fourbar(100))
    assert not any("轴不平行" in m or "轴写错" in m for m in msgs)
