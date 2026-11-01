# -*- coding: utf-8 -*-
"""第 58 轮 D-1：WQ-CR5 的动力学模型。原件与零件库副本、教材的 MJCF 一致；DH 与整机标定一致；关节模组的电机、减速器与
电机选型助手一致；零件逐项相加的质量、惯量与 MuJoCo 编译结果一致（惯量正定、满足三角不等式）；带 5 kg 负载、手臂伸直水平时
各关节的重力矩小于减速器的额定力矩；MJCF 的末端位置与 DH 正运动学一致。"""
import math
from pathlib import Path

import numpy as np
import pytest

from cae import motors, wqcr5 as W
from sim import calib as C

mujoco = pytest.importorskip("mujoco")
REPO = Path(__file__).resolve().parents[3]


def test_copies_are_in_sync():
    if not (REPO / "library").is_dir():         # freecad-ai-parts 没有问渠的零件库和教材，只比对问渠这边（第 59 轮）
        pytest.skip("本仓库没有 library/、textbook/（只在问渠仓库比对副本）")
    assert (REPO / "library" / "generators" / "wqcr5.py").read_bytes() == Path(W.__file__).read_bytes(), \
        "改原件后运行 python3 factory/digital/cae/wqcr5.py --sync"
    assert (REPO / "textbook" / "robotics" / "models" / "mjcf" / "wqcr5.xml").read_text(encoding="utf-8") == W.mjcf()


def test_same_robot_as_the_factory():
    assert W.DH == C.NOMINAL
    assert W.JOINT_MODULE == C.JOINT_SIZE
    assert W.HOME_DEG == C.HOME
    motor = {m[0]: m for m in motors.MOTORS}
    gear = {g[0]: g for g in motors.HARMONIC}
    for mod in W.MODULES.values():
        nm, peak, jm = mod["motor"]
        assert motor[nm][3] == peak and motor[nm][5] == jm
        gn, rated, rep = mod["gear"]
        assert gear[gn][1] == rated and gear[gn][2] == rep
    assert W.ETA == motors.ETA and W.GEAR_RATIO in motors.RATIOS
    import yaml
    plant = yaml.safe_load((REPO / "factory" / "plants" / "wenquest-robot.yaml").read_text(encoding="utf-8"))
    fr = {m["item"]: next(c["nominal"] for c in m["chars"] if c["code"] == "joint_friction")
          for m in plant["measurements"] if any(c["code"] == "joint_friction" for c in m["chars"])}
    assert {mod["code"]: mod["frictionloss"] for mod in W.MODULES.values()} == fr      # 名义库仑摩擦 = 关节测试台的空载摩擦力矩


def test_mass_and_inertia_match_mujoco():
    m = mujoco.MjModel.from_xml_string(W.mjcf())
    for i, l in enumerate(W.links()):
        b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "link{}".format(i + 1))
        assert m.body_mass[b] == pytest.approx(l["mass"], rel=1e-5)
        assert np.allclose(m.body_ipos[b], l["com"], atol=1e-6)
        ev = np.linalg.eigvalsh(l["I"])
        assert ev.min() > 0 and ev[0] + ev[1] >= ev[2] - 1e-12
        assert sorted(m.body_inertia[b]) == pytest.approx(sorted(ev), rel=1e-4)
    assert 15 < W.total_mass() < 22                       # 5 kg 一类协作臂的量级
    assert np.allclose(m.dof_armature, W.armature())


def test_tcp_matches_dh_and_gravity_is_within_ratings():
    m = mujoco.MjModel.from_xml_string(W.mjcf(payload_kg=W.PAYLOAD_KG))
    d = mujoco.MjData(m)
    tcp = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, "tcp")
    rng = np.random.default_rng(3)
    for _ in range(5):
        q = rng.uniform(-2.5, 2.5, 6)
        d.qpos[:] = q
        mujoco.mj_forward(m, d)
        assert np.allclose(d.site_xpos[tcp], C.fk(q), atol=1e-9)
    d.qpos[:] = 0                                          # DH 零位：手臂伸直、水平
    d.qvel[:] = 0
    mujoco.mj_forward(m, d)
    rated = [W.MODULES[s]["gear"][1] for s in W.JOINT_MODULE]
    assert all(abs(t) < r for t, r in zip(d.qfrc_bias, rated))
    assert abs(d.qfrc_bias[1]) > 0.5 * rated[1] * 0.5     # 肩关节用得上大关节（不是随便选的）


def test_position_servo_variant():
    kp, kv = [2000, 2000, 1000, 300, 300, 300], [200, 200, 100, 30, 30, 30]
    m = mujoco.MjModel.from_xml_string(W.mjcf(actuator="position", kp=kp, kv=kv))
    assert m.nu == 6 and m.actuator_gainprm[0, 0] == 2000


def test_design_reproduces_the_standard_wqcr5():
    """第 63 轮：按 5 kg、臂展 860 mm 用教材 30.3 节的方法设计，得到的就是标准 WQ-CR5（大臂 0.40、小臂 0.36，模组 L L M S S S）"""
    r = W.design()
    assert r["ok"] and r["standard"] and r["a2"] == 0.4 and r["a3"] == 0.36 and r["modules"] == ["L", "L", "M", "S", "S", "S"]
    assert r["mass_kg"] == round(W.total_mass(), 2)
    j1 = r["joints"][0]
    assert j1["own"] == "WQJ-M" and j1["module"] == "WQJ-L"          # J1 自己中关节就够，按“与 J2 同一种”用大关节
    assert all(j["use_peak"] <= 1 and j["use_rms"] <= 1 for j in r["joints"])


def test_geometry_context_restores_and_rated_torques_match_motor_table():
    dh0 = [dict(p) for p in W.DH]
    with W.geometry(0.5, 0.45, ["L"] * 6):
        assert W.DH[1]["a"] == -0.5 and W.JOINT_MODULE == ("L",) * 6
        heavy = W.total_mass()
    assert W.DH == dh0 and W.JOINT_MODULE == ("L", "L", "M", "S", "S", "S") and heavy > W.total_mass()
    motor = {m[0]: m for m in motors.MOTORS}
    assert all(motor[k][2] == v for k, v in W.MOTOR_RATED.items())


def test_design_grows_with_payload_and_reports_infeasible():
    small, big, too_big = W.design(3, 700), W.design(7, 860), W.design(10, 860)
    order = W.ORDER.index
    assert small["ok"] and big["ok"] and not too_big["ok"]
    assert all(order(a) <= order(b) for a, b in zip(small["modules"], big["modules"]))
    assert small["a2"] - small["a3"] == pytest.approx(W.DEAD_ZONE) and small["a2"] + small["a3"] == pytest.approx(0.6)
