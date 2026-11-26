"""模态柔性梁转得快时提示改用大变形梁（几何刚化）。

《多体动力学》书第 26 章线索第 49 条（问渠 CAD 0.3.8 细则）。Kane 旋转梁（L 8 m、A 72.968 mm²、E 68950 MPa、ρ 2766.67、
I 8218.9 mm⁴）升速到 2、4 rad/s：模态柔性梁（beam）不计几何刚化，梢部最大变形偏大 3.0 %、12.3 %，无提示；
大变形梁（nonlinear_beam）同工况差 0.5 % 以内。悬臂第一阶弯曲频率约 2.91 rad/s。
本测试只验提示（原工况 15 s 升速每个要算几分钟）：同一根梁 1.45 s 升速、共 2 s。
"""
from analysis.mbd.dae.run import run_model


def _kane(rad_s, typ="beam"):
    flex = {"type": typ, "from_mm": [0, 0, 0], "to_mm": [8000, 0, 0], "y_axis": [0, 1, 0], "youngs_modulus_mpa": 68950.0,
            "shear_modulus_mpa": 26000.0, "density_kg_m3": 2766.67, "area_mm2": 72.968, "iyy_mm4": 8218.9, "izz_mm4": 8218.9,
            "ixx_mm4": 16437.8, "elements": 6}
    if typ == "beam":
        flex["fixed_interface_modes"] = 2
    # Kane 升速律：T 内 θ = Ω/T·(t²/2 + (T/2π)²(cos(2πt/T) − 1))，之后匀速
    T, deg = 1.45, rad_s * 57.29577951308232       # T 不落在输出点上（正好在 T 时 min、max 两边的导数都算上）
    c = (T / 6.283185307179586) ** 2
    fn = (f"{deg!r}/{T!r}*(min(time,{T!r})^2/2+{c!r}*(cos(6.283185307179586*min(time,{T!r})/{T!r})-1))"
          f"+{deg!r}*max(time-{T!r},0)")
    return {"format": "mbd-model/1", "name": "Kane 旋转梁", "gravity_mm_s2": [0, 0, 0], "bodies": [{"id": "beam", "flex": flex}],
            "joints": [{"id": "hub", "type": "revolute", "body_i": "ground", "body_j": "beam", "point_mm": [0, 0, 0], "axis": [0, 0, 1]}],
            "motions": [{"id": "spin", "joint": "hub", "dof": "rotation", "function": fn}],
            "analysis": {"type": "dynamic", "end_time_s": 2.0, "output_steps": 20}}


def _warned(msgs):
    return any("转得快" in m and "nonlinear_beam" in m for m in msgs)


def test_fast_modal_beam_warns():
    _, msgs = run_model(_kane(2.0))            # 2 / 2.91 ≈ 0.69
    assert _warned(msgs)


def test_slow_modal_beam_no_warning():
    _, msgs = run_model(_kane(0.5))            # 0.5 / 2.91 ≈ 0.17
    assert not _warned(msgs)
