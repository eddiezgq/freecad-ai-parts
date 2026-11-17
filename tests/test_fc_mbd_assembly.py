"""FreeCAD Assembly 工作台装配体 → 多体模型（ADR-0097 D5a 验收）。需要 FreeCAD。

在 FreeCAD 里用 Assembly 工作台的真实对象（AssemblyObject、GroundedJoint、Joint）搭曲柄滑块和两连杆空间摆，材料用 FreeCAD 材料库的钢；
导出的模型与手写模型（质量、惯量按长方体公式手算）算出的运动、驱动力矩一致到 1e-9。缺材料、齿轮副、没解好的装配报错。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

pytestmark = pytest.mark.freecad

STEEL = "06ae5c92-de7b-46c9-984d-4dd87964bc5c"      # FreeCAD 材料库 Steel-C15（7800 kg/m³）


@pytest.fixture
def env():
    import FreeCAD as App
    import JointObject
    import Materials

    doc = App.newDocument("mbd_asm_test")
    asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
    jg = asm.newObject("Assembly::JointGroup", "Joints")
    mat = Materials.MaterialManager().getMaterial(STEEL)
    rho = float(App.Units.Quantity(mat.PhysicalProperties["Density"]).getValueAs("kg/m^3"))
    yield {"App": App, "doc": doc, "asm": asm, "jg": jg, "JO": JointObject, "mat": mat, "rho": rho}
    App.closeDocument(doc.Name)


def box(e, name, size, corner, rot=None, material=True):
    App = e["App"]
    b = e["asm"].newObject("Part::Box", name)
    b.Length, b.Width, b.Height = size
    b.Placement = App.Placement(App.Vector(*corner), rot or App.Rotation())
    if material:
        b.ShapeMaterial = e["mat"]
    return b


def joint(e, name, kind, o1, o2, at, z=(0, 0, 1)):
    """kind: FreeCAD JointType 序号（0 Fixed、1 Revolute、2 Cylindrical、3 Slider、4 Ball、11 Gears）；at、z 是地面系"""
    App = e["App"]
    j = e["jg"].newObject("App::FeaturePython", name)
    e["JO"].Joint(j, kind)
    rot = App.Rotation(App.Vector(0, 0, 1), App.Vector(*z))
    g = App.Placement(App.Vector(*at), rot)
    j.Detach1 = j.Detach2 = True                     # 运动副坐标系直接给定，不让它按所选元素重算
    j.Reference1 = [e["asm"], [o1.Name + ".", o1.Name + "."]]
    j.Reference2 = [e["asm"], [o2.Name + ".", o2.Name + "."]]
    j.Placement1 = o1.Placement.inverse() * g
    j.Placement2 = o2.Placement.inverse() * g
    return j


def ground(e, obj):
    g = e["jg"].newObject("App::FeaturePython", "GroundedJoint")
    e["JO"].GroundedJoint(g, obj)


def box_body(bid, rho, size, center, R=np.eye(3)):
    a, b, c = (x * 1e-3 for x in size)
    m = rho * a * b * c
    I = R @ np.diag([m * (b * b + c * c) / 12, m * (a * a + c * c) / 12, m * (a * a + b * b) / 12]) @ R.T
    return {"id": bid, "mass_kg": m, "cm_mm": list(center),
            "inertia_kg_m2": {"ixx": I[0, 0], "iyy": I[1, 1], "izz": I[2, 2], "ixy": I[0, 1], "ixz": I[0, 2], "iyz": I[1, 2]}}


def export(e):
    from freecad_addon.fc import mbd_assembly as MA

    e["doc"].recompute()
    return MA.model_from_assembly(e["asm"])


def run(model):
    from analysis.mbd.dae import run as R

    return R.run_model(model)[0]


def test_slider_crank_from_assembly_matches_hand_model(env):
    e = env
    frame = box(e, "Frame", (20, 20, 20), (-60, -60, -10), material=False)
    crank = box(e, "Crank", (100, 10, 10), (0, -5, -5))
    rod = box(e, "Rod", (300, 10, 10), (100, -5, -5))
    slider = box(e, "Slider", (40, 20, 20), (380, -10, -10))
    ground(e, frame)
    joint(e, "J1", 1, frame, crank, (0, 0, 0))
    joint(e, "J2", 1, crank, rod, (100, 0, 0))
    joint(e, "J3", 1, rod, slider, (400, 0, 0))
    joint(e, "J4", 3, frame, slider, (400, 0, 0), z=(1, 0, 0))
    model, msgs = export(e)
    rho = e["rho"]
    hand = {"format": "mbd-model/1", "name": "hand", "gravity_mm_s2": [0, 0, -9810],
            "bodies": [box_body("Crank", rho, (100, 10, 10), (50, 0, 0)), box_body("Rod", rho, (300, 10, 10), (250, 0, 0)),
                       box_body("Slider", rho, (40, 20, 20), (400, 0, 0))],
            "joints": [{"id": "J1", "type": "revolute", "body_i": "ground", "body_j": "Crank", "point_mm": [0, 0, 0], "axis": [0, 0, 1]},
                       {"id": "J2", "type": "revolute", "body_i": "Crank", "body_j": "Rod", "point_mm": [100, 0, 0], "axis": [0, 0, 1]},
                       {"id": "J3", "type": "revolute", "body_i": "Rod", "body_j": "Slider", "point_mm": [400, 0, 0], "axis": [0, 0, 1]},
                       {"id": "J4", "type": "translational", "body_i": "ground", "body_j": "Slider", "point_mm": [400, 0, 0],
                        "axis": [1, 0, 0]}]}
    for b, h in zip(model["bodies"], hand["bodies"], strict=True):
        assert b["id"] == h["id"]
        assert b["mass_kg"] == pytest.approx(h["mass_kg"], rel=1e-9)
        assert b["cm_mm"] == pytest.approx(h["cm_mm"], abs=1e-9)
        for k in ("ixx", "iyy", "izz"):
            assert b["inertia_kg_m2"][k] == pytest.approx(h["inertia_kg_m2"][k], rel=1e-9)
    motion = {"id": "drive", "joint": "J1", "dof": "rotation", "speed": 60}
    an = {"type": "kinematic", "end_time_s": 0.5, "output_steps": 10}
    a = run({**model, "motions": [motion], "analysis": an})
    b = run({**hand, "motions": [motion], "analysis": an})
    assert np.allclose(a["motions"]["drive"]["effort"], b["motions"]["drive"]["effort"], rtol=1e-9, atol=1e-12)
    assert np.allclose(a["bodies"]["Slider"]["cm_mm"], b["bodies"]["Slider"]["cm_mm"], atol=1e-9)
    assert abs(max(a["motions"]["drive"]["effort"], key=abs)) > 0


def test_tilted_two_link_pendulum_matches_hand_model(env):
    """第二节转了 30°，惯量在地面轴下有积项：自由下落 0.2 s 的位置一致"""
    e = env
    App = e["App"]
    base = box(e, "Base", (20, 20, 20), (-10, -10, 10), material=False)
    l1 = box(e, "Link1", (200, 20, 10), (0, -10, -5))
    rot = App.Rotation(App.Vector(0, 0, 1), 30)
    c2 = np.array([200 + 75 * math.cos(math.radians(30)), 75 * math.sin(math.radians(30)), 0.0])
    corner = App.Vector(*c2) - rot.multVec(App.Vector(75, 10, 5))
    l2 = box(e, "Link2", (150, 20, 10), (corner.x, corner.y, corner.z), rot=rot)
    ground(e, base)
    joint(e, "R1", 1, base, l1, (0, 0, 0), z=(0, 1, 0))
    joint(e, "R2", 4, l1, l2, (200, 0, 0))
    model, _ = export(e)
    rho = e["rho"]
    th = math.radians(30)
    R = np.array([[math.cos(th), -math.sin(th), 0], [math.sin(th), math.cos(th), 0], [0, 0, 1]])
    hand = {"format": "mbd-model/1", "name": "hand", "gravity_mm_s2": [0, 0, -9810],
            "bodies": [box_body("Link1", rho, (200, 20, 10), (100, 0, 0)), box_body("Link2", rho, (150, 20, 10), c2.tolist(), R)],
            "joints": [{"id": "R1", "type": "revolute", "body_i": "ground", "body_j": "Link1", "point_mm": [0, 0, 0], "axis": [0, 1, 0]},
                       {"id": "R2", "type": "spherical", "body_i": "Link1", "body_j": "Link2", "point_mm": [200, 0, 0]}]}
    I2 = model["bodies"][1]["inertia_kg_m2"]
    assert abs(I2["ixy"]) > 1e-6
    for k in ("ixx", "iyy", "izz", "ixy", "ixz", "iyz"):
        assert I2[k] == pytest.approx(hand["bodies"][1]["inertia_kg_m2"][k], rel=1e-9, abs=1e-15)
    an = {"type": "dynamic", "end_time_s": 0.2, "output_steps": 10, "rtol": 1e-10, "atol": 1e-12}
    a = run({**model, "analysis": an})
    b = run({**hand, "analysis": an})
    assert np.allclose(a["bodies"]["Link2"]["cm_mm"], b["bodies"]["Link2"]["cm_mm"], atol=1e-7)
    assert np.allclose(a["joints"]["R1"]["torque_n_m"], b["joints"]["R1"]["torque_n_m"], rtol=1e-6, atol=1e-9)


def test_missing_material_and_gears_are_reported(env):
    from analysis.mbd.assembly import AssemblyError

    e = env
    frame = box(e, "Frame", (20, 20, 20), (-10, -10, -10), material=False)
    a = box(e, "Plain", (50, 10, 10), (0, -5, -5), material=False)
    g = box(e, "Wheel", (50, 10, 10), (0, 20, -5))
    ground(e, frame)
    joint(e, "R", 1, frame, a, (0, 0, 0))
    joint(e, "G", 11, frame, g, (0, 25, 0))
    with pytest.raises(AssemblyError) as err:
        export(e)
    text = "；".join(err.value.problems)
    assert "Plain" in text and "材料" in text
    assert "gear_mesh" in text


def test_joint_made_like_the_gui_with_element_references(env):
    """像界面里那样选面 + 顶点建转动副，FreeCAD 自己求解摆好零件；导出的运动副中心在所选顶点、轴沿面法向"""
    e = env
    App = e["App"]
    b1 = box(e, "Fixed", (10, 10, 10), (0, 0, 0), material=False)
    b2 = box(e, "Lid", (10, 10, 2), (40, 50, 60), rot=App.Rotation(15, 25, 35))
    ground(e, b1)
    j = e["jg"].newObject("App::FeaturePython", "Hinge")
    e["JO"].Joint(j, 1)
    j.Proxy.setJointConnectors(j, [[e["asm"], [b1.Name + ".Face6", b1.Name + ".Vertex7"]],
                                   [e["asm"], [b2.Name + ".Face5", b2.Name + ".Vertex1"]]])
    model, _ = export(e)
    jt = model["joints"][0]
    assert jt["type"] == "revolute" and jt["body_i"] == "ground" and jt["body_j"] == "Lid"
    assert jt["point_mm"] == pytest.approx([10, 10, 10], abs=1e-6)        # Face6 是顶面、Vertex7 在 (10, 10, 10)
    assert jt["axis"] == pytest.approx([0, 0, 1], abs=1e-9)
    data = run({**model, "analysis": {"type": "dynamic", "end_time_s": 0.05, "output_steps": 5}})
    assert next(v for v in data["verification"] if v["key"] == "constraint_residual")["status"] == "pass"
