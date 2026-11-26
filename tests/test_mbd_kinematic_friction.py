"""运动学分析的驱动力矩计入运动副摩擦。

《多体动力学》书第 20 章线索第 27 条（问渠 CAD 0.3.8 细则）。曲柄滑块（曲柄 50 mm、连杆 150 mm、600 rpm、滑块阻力 200 N，
三个转动副销半径 10 mm、导轨同一 μ），转角驱动做运动学分析：原来 μ = 0.2 与无摩擦的驱动力矩完全相同、无提示。
参考值：书第 20 章 mini-mbd 同一摩擦律、不计导轨反力矩（问渠自己的导轨模型）的逆动力学（ex20_1_fric 的 mu2_nm）。
"""
import pytest

from analysis.mbd.dae.run import run_model

R, L = 50.0, 150.0
M1, M2, M3 = 0.5, 0.8, 1.0
# 曲柄转角 → 驱动力矩（N·m），μ = 0.2 / 无摩擦；只取离摩擦换向远的点（0°、180° 附近滑块换向，90°、270° 附近连杆角速度过零、B 销换向）
REF = {30: (20.051510370299656, 16.308907018784343), 45: (21.75814099437244, 18.14855611285574),
       60: (18.506553691534425, 15.46075104343527), 210: (9.585272537164935, 7.442174035666355),
       225: (13.5801954931836, 11.170230707567637), 240: (16.985280527996878, 14.33932703892685)}


def _model(mu):
    J = [{"id": "O", "type": "revolute", "body_i": "ground", "body_j": "crank", "point_mm": [0, 0, 0], "axis": [0, 0, 1]},
         {"id": "A", "type": "revolute", "body_i": "crank", "body_j": "rod", "point_mm": [R, 0, 0], "axis": [0, 0, 1]},
         {"id": "B", "type": "revolute", "body_i": "rod", "body_j": "sl", "point_mm": [R + L, 0, 0], "axis": [0, 0, 1]},
         {"id": "P", "type": "translational", "body_i": "ground", "body_j": "sl", "point_mm": [R + L, 0, 0], "axis": [1, 0, 0]}]
    if mu:
        for j in J:
            j["friction"] = {"mu_static": mu, "mu_dynamic": mu, "stiction_speed": 1e-3, "transition_speed": 2e-3,
                             **({"pin_radius_mm": 10.0} if j["type"] == "revolute" else {})}
    small = {"ixx": 1e-4, "iyy": 1e-4}
    return {"format": "mbd-model/1", "name": "曲柄滑块（关节摩擦）", "gravity_mm_s2": [0, 0, 0],
            "bodies": [{"id": "crank", "mass_kg": M1, "cm_mm": [R / 2, 0, 0], "inertia_kg_m2": small | {"izz": M1 * 0.05 ** 2 / 12}},
                       {"id": "rod", "mass_kg": M2, "cm_mm": [R + L / 2, 0, 0], "inertia_kg_m2": small | {"izz": M2 * 0.15 ** 2 / 12}},
                       {"id": "sl", "mass_kg": M3, "cm_mm": [R + L, 0, 0], "inertia_kg_m2": small | {"izz": 1e-4}}],
            "joints": J, "measures": [{"id": "v", "type": "joint_velocity", "joint": "P"}],
            "forces": [{"id": "F", "type": "force", "body": "sl", "point_mm": [R + L, 0, 0], "fx_n": "-200.0*sign(v)"}],
            "motions": [{"id": "mo", "joint": "O", "dof": "rotation", "function": "3600.0*time"}],
            "analysis": {"type": "kinematic", "end_time_s": 0.1, "output_steps": 360}}


@pytest.mark.parametrize("mu,col", [(0.2, 0), (0.0, 1)])
def test_kinematic_drive_torque_with_friction(mu, col):
    d, _ = run_model(_model(mu))
    eff = d["motions"]["mo"]["effort"]
    for deg, ref in REF.items():
        assert abs(eff[deg]) == pytest.approx(abs(ref[col]), abs=1e-3)
    if mu:
        assert next(v for v in d["verification"] if v["key"] == "friction_iteration")["status"] == "pass"
