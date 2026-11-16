"""典型应用（ADR-0061，M13 第二步）：三个应用的快速模式都能跑完，关键结论不变。

不联网、不连工厂（不给 --hub，发布一步记“跳过”），没有 FreeCAD 时布局一步记“跳过”，平缝机的流体按参数跳过。
"""

from __future__ import annotations

import importlib

import pytest

from examples.apps import common as C


@pytest.fixture(autouse=True)
def _out(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path)
    monkeypatch.delenv("FAP_FREECAD", raising=False)


def _steps(app, *argv):
    rep = importlib.import_module(f"examples.apps.{app}").main(["--quick", *argv])
    return {s["step"]: s for s in rep["steps"]}


def _no_crash(steps):
    crashed = [k for k, s in steps.items() if s["status"] == "fail" and "trace" in s.get("data", {})]
    assert not crashed, {k: steps[k]["summary"] for k in crashed}


def test_cobot_joint():
    s = _steps("cobot_joint")
    _no_crash(s)
    assert "手算 Σm·g·r 92.5" in s["动力学"]["summary"]  # 重力矩与手算一致
    assert s["选型 j2"]["status"] == "unknown" and "CSF-32-100-2UH" in s["选型 j2"]["summary"]
    assert "（手算 11.4）" in s["动力学：腕关节 j4"]["summary"] and "CSF-17" in s["选型 j4"]["summary"]  # 腕关节（ADR-0062）
    assert s["数字孪生：减速器"]["status"] == "ok" and "剩余约" in s["数字孪生：减速器"]["summary"]  # 额定寿命 11-15 按样本补录（ADR-0094）
    assert s["发布到工厂"]["status"] == "skip"


def test_scara():
    s = _steps("scara")
    _no_crash(s)
    assert "没有能满足的组合" in s["选型（快）"]["summary"]  # 快节拍零件库供不了，如实报告
    assert s["数控编程：大臂"]["status"] == "ok"


def test_lockstitch():
    s = _steps("lockstitch", "--no-cfd")
    _no_crash(s)
    assert "ΔE" in s["动力学：针杆机构"]["summary"]  # 惯性力矩一转做功为零，给盈亏功（ADR-0062）
    hi, lo = s["选型（上限：刚性速度环）"], s["选型（下限：惯量吸收）"]
    assert hi["status"] == "fail" and "C9" in hi["summary"]  # 速度环刚：库里驱动器电流不够
    assert lo["status"] == "unknown" and "SGM7J-04A" in lo["summary"]  # 惯量吸收：400 W，缝制阻力待确认
    assert s["固有频率：上轴 LS-101"]["status"] == "ok"
    assert s["流体：控制箱散热器"]["status"] == "skip"


def test_cobot_arm():
    """整臂案例（ADR-0094）：六个关节都选得出；有限元的末端下垂与梁理论同一量级（多出的是壳体、法兰毂的变形）；
    关节扭矩与动力学的重力矩一致；Dunkerley 合成频率低于每一个分量；输出轴承寿命按样本公式给出。"""
    s = _steps("cobot_arm")
    _no_crash(s)
    for j in ("j1", "j2", "j3", "j4", "j5", "j6"):
        assert s[f"选型 {j}"]["status"] in ("ok", "unknown"), s[f"选型 {j}"]["summary"]
    assert "CSF-32-100-2UH" in s["选型 j2"]["summary"]
    assert "CSF-32-100-2UH" in s["选型 j1"]["summary"]                      # 第二版：j1 按输出轴承寿命 ≥ 35000 h 选（ADR-0094）
    assert "不满足" not in s["输出轴承寿命"]["summary"]
    f = s["电机法兰定制要求"]                                                # CSF-2UH 电机法兰由厂商按所配电机定制（ADR-0045、ADR-0053）
    assert f["status"] == "ok" and len(f["data"]["rows"]) == 6 and "分度圆直径 70" in f["summary"]
    d = s["有限元：整臂静力"]["data"]
    sag, hand = -d["tcp_u_mm"][2], d["hand_sag_mm"]
    assert hand < sag < 4 * hand                                            # 梁理论只算管子弯曲，是下限
    assert next(i for i in d["items"] if i["name"] == "反力平衡")["verdict"] == "pass"
    g = s["动力学"]["data"]["gravity"]["j2"]
    assert s["关节刚度"]["data"]["T2_nm"] == pytest.approx(g, rel=0.02)    # 两处独立算的肩关节重力矩一致
    m = s["模态：整臂"]["data"]
    assert m["f_dunkerley"] < min(m["freqs"][0]["hz"], m["f_j2"], m["f_j3"])
    assert "摆动寿命" in s["输出轴承寿命"]["summary"] and "j1" in s["输出轴承寿命"]["summary"]
    assert s["减速器寿命：j2"]["status"] == "ok"
