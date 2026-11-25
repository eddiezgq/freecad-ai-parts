"""ADR-0130 的两个模型选项接到代码上：PID 的 antiwindup_tracking_s、分析的 dead_point。"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_mbd_dead_point import _fourbar, _turns
from test_mbd_pid_antiwindup import _overshoot, _table

from analysis.mbd.dae.run import run_model


def test_tracking_time_is_used():
    base = _table(20.0, 100.0, 2.0, steps=400)
    d05, _ = run_model(base)                                # 缺省 T_t = 0.05 s：超调 2.116°（书）
    slow = _table(20.0, 100.0, 2.0, steps=400)
    slow["controllers"][0]["antiwindup_tracking_s"] = 0.5   # 跟踪慢：积分退得慢，超调更大
    d5, _ = run_model(slow)
    assert _overshoot(d05) == pytest.approx(2.1159829227739095, abs=0.02)
    assert _overshoot(d5) > _overshoot(d05) + 0.5


def test_dead_point_reverse_keeps_old_branch():
    m = _fourbar(406)
    m["analysis"]["dead_point"] = "reverse"
    d, _ = run_model(m)
    assert abs(_turns(d)) < 0.01                            # 倒回：曲柄来回摆、不整周转（0.3.7 及以前的走法）
    m["analysis"]["dead_point"] = "continue"
    d, _ = run_model(m)
    assert abs(_turns(d)) == pytest.approx(2.0, abs=1e-6)
    assert math.isfinite(_turns(d))
