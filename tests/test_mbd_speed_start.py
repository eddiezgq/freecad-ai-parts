"""匀速驱动的起步段：峰值、转速剔除起步的软约束过冲，选型需求注明。

《多体动力学》书第 1 章线索第 9 条（问渠 CAD 0.3.9 细则）：机构库曲柄滑块（缺省参数）匀速 600 rpm 从 t = 0 起步，
原来记录峰值 0.702 N·m（解析稳态 0.623，+13 %）、最高转速 646 rpm（+7.7 %），requirement() 直接取这两个数。
0.3.8 收紧闭环 τ 后峰值已在 0.624，起步 10 ms 内转速仍到 627 rpm。
"""
import pytest

import analysis
from analysis.mbd import requirement


def _run():
    return analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-LNK-SLIDER"}, "duration_s": 0.3, "sample_hz": 4000,
                                "drives": [{"joint": "crank", "kind": "speed", "value": 600}]})


def test_start_excluded_from_peak_and_speed():
    res = _run()
    d = res["data"]["drives"][0]
    assert d["peak_settled"] == pytest.approx(0.623, rel=0.03)
    assert d["speed_max"] <= 600.0 * 1.001
    assert d["speed_max_raw"] > d["speed_max"]                 # 原始值照样给出，便于核对
    req = requirement(res, "crank")
    assert req["output_torque_peak_nm"] == pytest.approx(0.623, rel=0.03)
    assert req["output_speed_rpm"] <= 600.0 * 1.001
