"""装配体中性描述 → 多体模型（ADR-0097 D5a）：纯 Python 部分。FreeCAD 部分见 test_fc_mbd_assembly.py。"""

from __future__ import annotations

import numpy as np
import pytest

from analysis.mbd import assembly as A

RHO = 7850.0


def cube_solid(c, a=10.0, label="s", rho=RHO, material="Steel"):
    I = (a ** 3) * (2 * a * a) / 12                    # 单位密度立方体对质心：V·(a²+a²)/12
    return {"label": label, "volume_mm3": a ** 3, "cm_mm": list(c), "inertia_unit_mm5": np.diag([I, I, I]).tolist(),
            "material": material, "density_kg_m3": rho}


def frame(o, z=(0, 0, 1)):
    return {"origin_mm": list(o), "z": list(z), "x": [1, 0, 0]}


def asm(parts, joints):
    return {"name": "t", "parts": [{"id": "Frame", "label": "机架", "grounded": True, "solids": []}] + parts, "joints": joints}


def test_two_solids_combine_with_parallel_axis():
    p = {"id": "P", "label": "两块", "solids": [cube_solid((0, 0, 0)), cube_solid((20, 0, 0))]}
    m, c, I, pr = A.mass_properties(p)
    m1 = RHO * 1e-6
    assert not pr and m == pytest.approx(2 * m1)
    assert c == pytest.approx([10, 0, 0])
    i0 = m1 * (2 * 1e-4) / 12
    d2 = (10e-3) ** 2
    assert I[0, 0] == pytest.approx(2 * i0, rel=1e-12)
    assert I[1, 1] == pytest.approx(2 * (i0 + m1 * d2), rel=1e-12)
    assert I[2, 2] == pytest.approx(2 * (i0 + m1 * d2), rel=1e-12)


def test_mass_override_scales_inertia():
    p = {"id": "P", "solids": [cube_solid((0, 0, 0))], "mass_kg": 1.0}
    m, _, I, _ = A.mass_properties(p)
    assert m == 1.0
    assert I[0, 0] == pytest.approx(1.0 * 2e-4 / 12, rel=1e-12)


def test_model_from_description_maps_joints_and_names():
    model, msgs = A.to_model(asm(
        [{"id": "Crank", "label": "曲柄", "solids": [cube_solid((50, 0, 0))]},
         {"id": "Slider 1", "label": "滑块", "solids": [cube_solid((200, 0, 0))]}],
        [{"id": "Joint", "type": "Revolute", "part1": "Frame", "part2": "Crank", "frame1": frame((0, 0, 0)), "frame2": frame((0, 0, 0))},
         {"id": "Joint001", "type": "Slider", "part1": "Frame", "part2": "Slider 1",
          "frame1": frame((150, 0, 0), (1, 0, 0)), "frame2": frame((200, 0, 0), (1, 0, 0))}]))
    assert [b["id"] for b in model["bodies"]] == ["Crank", "Slider_1"]
    assert model["bodies"][0]["name"] == "曲柄"
    j = {x["id"]: x for x in model["joints"]}
    assert j["Joint"]["type"] == "revolute" and j["Joint"]["body_i"] == "ground" and j["Joint"]["axis"] == [0, 0, 1]
    assert j["Joint001"]["type"] == "translational" and j["Joint001"]["body_j"] == "Slider_1"
    assert any("重力" in m for m in msgs)
    from kb.validation import errors
    assert not errors("mbd-model.schema.json", model)


def test_all_problems_listed_together():
    with pytest.raises(A.AssemblyError) as e:
        A.to_model(asm(
            [{"id": "NoMat", "label": "没材料", "solids": [cube_solid((0, 0, 0), material="Default")]},
             {"id": "Gear", "label": "齿轮", "solids": [cube_solid((0, 0, 0))]}],
            [{"id": "G", "label": "齿轮副", "type": "Gears", "part1": "Frame", "part2": "Gear", "frame1": frame((0, 0, 0)),
              "frame2": frame((0, 0, 0))},
             {"id": "R", "label": "没解好", "type": "Revolute", "part1": "Frame", "part2": "Gear", "frame1": frame((0, 0, 0)),
              "frame2": frame((5, 0, 0))}]))
    probs = e.value.problems
    assert any("没材料" in p and "材料" in p for p in probs)
    assert any("齿轮副" in p and "gear_mesh" in p for p in probs)
    assert any("没解好" in p and "求解装配" in p for p in probs)


def test_no_grounded_part_is_an_error():
    with pytest.raises(A.AssemblyError, match="固定"):
        A.to_model({"parts": [{"id": "P", "solids": [cube_solid((0, 0, 0))]}], "joints": []})
