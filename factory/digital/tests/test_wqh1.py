# -*- coding: utf-8 -*-
"""第 75 轮：WQ-H1 轮式人形的动力学模型。原件与零件库副本一致；16 个关节与机器人厂物料清单对应；总质量 = 各零件之和、
与 MuJoCo 编译结果一致；位置伺服下零位、抱箱位静止 1 秒不发散；重力下（双手各 2.5 kg、手臂前伸抱箱）各关节力矩在模组上限以内。"""
import math
from pathlib import Path

import numpy as np
import pytest

from cae import wqcr5 as W, wqh1 as H

mujoco = pytest.importorskip("mujoco")
REPO = Path(__file__).resolve().parents[3]


def test_copy_is_in_sync():
    if not (REPO / "library").is_dir():         # freecad-ai-parts 没有问渠的零件库
        pytest.skip("本仓库没有 library/（只在问渠仓库比对副本）")
    assert (REPO / "library" / "generators" / "wqh1.py").read_bytes() == Path(H.__file__).read_bytes(), \
        "改原件后运行 python3 factory/digital/cae/wqh1.py --sync"


def test_same_robot_as_the_bom():
    import yaml
    plant = yaml.safe_load((REPO / "factory" / "plants" / "wenquest-robot.yaml").read_text(encoding="utf-8"))
    bom = dict((c, q) for c, q in next(b for b in plant["boms"] if b["item"] == "WQ-H1")["components"])
    assert H.bom_count() == {k: bom[k] for k in ("WQJ-L", "WQJ-M", "WQJ-S")}
    assert len(H.JOINTS) == 16 and len(set(H.JOINTS)) == 16
    assert H.MODULES is W.MODULES                                      # 关节模组只有一份数据
    item = next(i for i in plant["items"] if i["code"] == "WQ-H1")
    assert item.get("library") == "B-HUM-WQH1/default"
    # 物料清单里的每一样（螺钉除外）都在模型里有一块质量
    names = " ".join(n for b in H.bodies() for n, _, _ in b["parts"])
    for code in bom:
        if code.startswith(("WQJ-", "SCR-")):
            continue
        assert code in names or (code == "WQ-AGV300" and "WQ-AGV300" in names), code


def test_mass_and_inertia_match_mujoco():
    m = mujoco.MjModel.from_xml_string(H.mjcf())
    parts = sum(p["mass"] for b in H.bodies() for _, p, _ in b["parts"])
    assert abs(H.total_mass() - parts) < 1e-9
    assert abs(sum(m.body_mass) - parts) < 1e-4                        # MJCF 里质量写 6 位有效数字
    assert all(m.body_inertia[i].min() > 0 for i in range(1, m.nbody))
    assert m.njnt == 16 and m.nu == 16


@pytest.mark.parametrize("key,payload", [("home", 0.0), ("carry", 0.0), ("carry", H.PAYLOAD_KG)])
def test_holds_still_and_torques_within_limits(key, payload):
    m = mujoco.MjModel.from_xml_string(H.mjcf(payload_kg=payload))
    d = mujoco.MjData(m)
    mujoco.mj_resetDataKeyframe(m, d, m.key(key).id)
    d.ctrl[:] = d.qpos[:]
    mujoco.mj_forward(m, d)
    for j, mod, tau in zip(H.JOINTS, H.JOINT_MODULE, d.qfrc_bias):
        assert abs(tau) < H.torque_limit(mod), (j, tau)               # 静止时要扛的重力矩
    q0 = d.qpos.copy()
    for _ in range(int(1.0 / m.opt.timestep)):
        mujoco.mj_step(m, d)
    assert np.all(np.isfinite(d.qpos)) and math.degrees(np.abs(d.qpos - q0).max()) < 5.0
    assert np.abs(d.qvel).max() < 0.05


def test_carry_pose_hands_in_front():
    m = mujoco.MjModel.from_xml_string(H.mjcf())
    d = mujoco.MjData(m)
    mujoco.mj_resetDataKeyframe(m, d, m.key("carry").id)
    mujoco.mj_kinematics(m, d)
    l, r = d.site("l_tcp").xpos, d.site("r_tcp").xpos
    assert l[0] > 0.6 and r[0] > 0.6 and abs(l[1] + r[1]) < 1e-9 and abs(l[2] - r[2]) < 1e-9


def test_motion_analysis_can_pick_it():
    """“运动与动力分析”能直接选 B-HUM-WQH1：保持抱箱位时肩关节的驱动力矩 = −重力矩"""
    from cae import mbd, mbd_models as MM
    assert "B-HUM-WQH1" in MM.robots() and MM.robots()["B-HUM-WQH1"][2] == "l_wrist"
    pose = {j: math.radians(v) for j, v in H.CARRY_DEG.items()}
    spec = lambda: mbd.load_spec(path=MM.robot_path("B-HUM-WQH1"))  # noqa: E731
    s, ch, _ = mbd.simulate(spec(), {"duration_s": 0.5, "initial": pose, "drives": [{"joint": j, "kind": "hold"} for j in pose]})
    model, _ = mbd.build(spec(), {})
    qp = np.zeros(model.nq)
    for j, v in pose.items():
        qp[model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j)]] = v
    g = mbd.gravity_torques(model, qp)
    for j in ("LA1", "RA1"):
        assert abs(ch["drive." + j][-1] + g[j]) / abs(g[j]) < 0.02
