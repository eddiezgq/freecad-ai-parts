"""输出间隔里构件转得多（重陀螺每个间隔自转 8 rad）也能算完，结果与密输出一致。

《多体动力学》书第 3 章线索第 1 条（问渠 CAD 0.3.9 细则）：输出 25、50 点退出，报 SciPy 的
“array must not contain infs or NaNs”。原因：记录点上牛顿迭代从上一个记录点起步，而上一个记录点常在本段之前
（每段转角限 0.5 rad），稠密输出在那里是外推，起点太远发散出非数；分小步走的回退又只接 SolveError。
书里的验证题是 1 s、25 点对 400 点；这里取 0.2 s、5 点对 80 点（每个输出间隔同样自转 8 rad），省时间。
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _top_model import top_model

from analysis.mbd.dae.run import run_model


@pytest.mark.parametrize("name", ["tilt30", "horiz90"])
def test_heavy_top_coarse_output_matches_fine(name):
    out = {}
    for n in (5, 80):
        m = top_model(name, n)
        m["analysis"]["end_time_s"] = 0.2
        d, _ = run_model(m)                               # 原来 5 点时抛 ValueError
        out[n] = np.array(d["bodies"]["top"]["euler_parameters"])
        assert all(v["status"] == "pass" for v in d["verification"])
    assert np.max(np.abs(out[5] - out[80][::16])) < 1e-6
