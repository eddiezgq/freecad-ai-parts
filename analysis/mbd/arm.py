"""参数化串联机械臂（MJCF）：底座竖直轴 j1，其后各关节绕水平轴（j2、j3 …），各杆沿 +X 伸出。

质量全部由使用者给：杆的质量（均布）、各关节处的模组质量（电机 + 减速器，可取自所选零件的样本质量）、末端负载。
不估任何质量；没给的项就是 0（不计）。长度单位 mm、质量 kg（对外）；生成的 MJCF 用米。
关节转角正向：j1 从上往下看逆时针；j2 起绕 −Y，正转角使杆抬起（与机构模型一致）。
"""

from __future__ import annotations

from collections.abc import Mapping


class ArmError(ValueError):
    pass


def _num(x, name: str, *, positive: bool = False) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ArmError(f"{name} 须为数字")
    if positive and x <= 0:
        raise ArmError(f"{name} 须大于 0")
    if x < 0:
        raise ArmError(f"{name} 不能为负")
    return float(x)


def joint_names(spec: Mapping) -> list[str]:
    return [f"j{i}" for i in range(1, len(spec["links"]) + 2)]


def mjcf(spec: Mapping) -> str:
    """spec：{"base_height_mm", "links": [{"length_mm", "mass_kg"}], "joint_masses_kg": [...], "payload_kg"}。
    links 为 j2 之后的各杆（大臂、小臂……），至少 1 根；joint_masses_kg 对应 j2、j3 …（j1 的模组在底座上，不影响关节力矩）。"""
    links = spec.get("links")
    if not isinstance(links, list) or not 1 <= len(links) <= 5:
        raise ArmError("links 须为 1–5 根杆")
    h = _num(spec.get("base_height_mm", 0), "base_height_mm") / 1000
    jm = list(spec.get("joint_masses_kg") or [])
    if len(jm) > len(links):
        raise ArmError("joint_masses_kg 的个数不能多于杆数（对应 j2、j3 …）")
    payload = _num(spec.get("payload_kg", 0), "payload_kg")
    parts = []
    for i, link in enumerate(links):
        L = _num(link.get("length_mm"), f"第 {i + 1} 根杆的 length_mm", positive=True) / 1000
        m = _num(link.get("mass_kg"), f"第 {i + 1} 根杆的 mass_kg", positive=True)
        mod = _num(jm[i], f"joint_masses_kg[{i}]") if i < len(jm) else 0.0
        name = f"j{i + 2}"
        geom = (f'<geom type="capsule" fromto="0 0 0 {L} 0 0" size="{max(0.01, L * 0.04):.4f}" mass="{m}" '
                'rgba="0.24 0.47 0.67 1"/>')
        module = (f'<body name="{name}_module"><inertial pos="0 0 0" mass="{mod}" diaginertia="1e-6 1e-6 1e-6"/></body>'
                  if mod > 0 else "")
        pos = "0 0 0" if i == 0 else f"{float(links[i - 1]['length_mm']) / 1000} 0 0"
        j1 = '<joint name="j1" type="hinge" axis="0 0 1"/>' if i == 0 else ""  # 底座转轴与肩关节同在第一根杆上
        head = f'<body name="link{i + 1}" pos="{pos}">{j1}<joint name="{name}" type="hinge" axis="0 -1 0"/>{module}{geom}'
        parts.append((head, "</body>"))
    tip = float(links[-1]["length_mm"]) / 1000
    end = (f'<body name="payload" pos="{tip} 0 0"><inertial pos="0 0 0" mass="{payload}" '
           f'diaginertia="1e-6 1e-6 1e-6"/></body>' if payload > 0 else "")
    end += f'<site name="tool" pos="{tip} 0 0"/>'
    inner = "".join(o for o, _ in parts) + end + "".join(c for _, c in reversed(parts))
    return ('<mujoco model="arm"><compiler angle="radian" autolimits="true"/><option timestep="0.0005"/>'
            f'<worldbody><body name="base" pos="0 0 {h}">'
            '<geom type="cylinder" size="0.04 0.02" mass="0" rgba="0.3 0.3 0.3 1"/>'
            f'{inner}</body></worldbody></mujoco>')
