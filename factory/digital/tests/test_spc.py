# -*- coding: utf-8 -*-
"""第 13 轮第 6 步：质量统计——控制图、判异、过程能力、测量系统分析（与手算、已知方差的模拟数据核对）。"""
import random
import statistics as st

import pytest

from hub import spc


def test_xbar_r_by_hand():
    v = [10, 12, 11, 13, 9, 11, 10, 12, 14, 13]           # 2 个子组，n = 5
    c = spc.xbar_r(v, 5)
    assert c["xbar"] == [11, 12] and c["R"] == [4, 4]
    assert c["center"] == 11.5 and c["Rbar"] == 4
    assert c["UCL"] == pytest.approx(11.5 + 0.577 * 4) and c["UCL_R"] == pytest.approx(2.114 * 4)
    assert c["sigma_within"] == pytest.approx(4 / 2.326)


def test_i_mr_and_capability_by_hand():
    v = [35.010, 35.012, 35.008, 35.011, 35.009]
    c = spc.i_mr(v)
    mrb = (0.002 + 0.004 + 0.003 + 0.002) / 4
    assert c["MRbar"] == pytest.approx(mrb) and c["sigma_within"] == pytest.approx(mrb / 1.128)
    k = spc.capability(v, 35.002, 35.018)
    sw = mrb / 1.128
    assert k["Cp"] == pytest.approx(0.016 / (6 * sw))
    assert k["Cpk"] == pytest.approx(min(35.018 - 35.01, 35.01 - 35.002) / (3 * sw))
    assert k["Ppk"] == pytest.approx(0.008 / (3 * st.stdev(v)))


def test_special_cause_rules_fire_once_each():
    pts = [0.1, -0.2, 0.3, -0.1, 3.5, 0.0]                  # 规则 1：第 5 点
    assert [(o["rule"], o["index"]) for o in spc.special_causes(pts, 0, 1)] == [(1, 4)]
    drift = [-0.2, 0.1, -0.1] + [0.4] * 9                   # 规则 4：从第 11 点起连续 8 点在上侧
    r = spc.special_causes(drift, 0, 1)
    assert [(o["rule"], o["index"]) for o in r] == [(4, 10)]
    assert spc.special_causes([2.5, 0.0, 2.4], 0, 1)[0]["rule"] == 2


def test_capability_recovers_a_known_process():
    rng = random.Random(7)
    v = [rng.gauss(35.010, 0.002) for _ in range(500)]
    ch = spc.xbar_r(v, 5)
    k = spc.capability(v, 35.002, 35.018, ch["sigma_within"])
    assert k["Cp"] == pytest.approx(0.016 / 0.012, rel=0.08)   # 真值 1.33
    assert k["Cpk"] == pytest.approx(0.008 / 0.006, rel=0.10)


def test_grr_anova_by_hand_and_on_simulated_data():
    # 手算：2 名检验员 × 2 个零件 × 2 次
    d = {"A": {"p1": [1.0, 1.2], "p2": [2.0, 2.2]}, "B": {"p1": [1.1, 1.3], "p2": [2.1, 2.3]}}
    g = spc.grr_anova(d)
    assert g["EV"] == pytest.approx(0.1414214, rel=1e-6)   # 每格两次读数相差 0.2：MS_E = 0.02
    assert g["PV"] > 0.6 and g["ndc"] >= 5
    # 模拟：零件 σ = 0.010，检验员 σ = 0.001，重复性 σ = 0.0015
    rng = random.Random(3)
    parts = {"p{}".format(i): rng.gauss(35.01, 0.010) for i in range(10)}
    bias = {o: rng.gauss(0, 0.001) for o in "ABC"}
    est = []
    for _ in range(40):
        data = {o: {p: [x + bias[o] + rng.gauss(0, 0.0015) for _ in range(3)] for p, x in parts.items()} for o in "ABC"}
        est.append(spc.grr_anova(data, tol=0.016)["EV"])
    assert st.fmean(est) == pytest.approx(0.0015, rel=0.06)
    r = spc.grr_anova(data, tol=0.016)
    assert 0 < r["pct_GRR"] < 30 and r["verdict"]


def test_for_characteristic_reads_the_inspection_records():
    class FakeDB:
        def messages(self, types, mode=None, order="asc", limit=0):
            rng = random.Random(1)
            return [{"id": i, "data": {"item": "SH-301", "characteristic": "bearing_seat_d35", "value_mm": rng.gauss(35.010, 0.002),
                                        "lower_tol_mm": 35.002, "upper_tol_mm": 35.018}} for i in range(40)]
    r = spc.for_characteristic(FakeDB(), "teach", "SH-301", "bearing_seat_d35")
    assert r["count"] == 40 and r["chart"]["k"] == 8 and 0.8 < r["capability"]["Cpk"] < 2.0
    assert "note" in spc.for_characteristic(FakeDB(), "teach", "SH-301", "gear_seat_d40")
