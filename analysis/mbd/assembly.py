"""装配体（中性描述）→ 多体模型 mbd-model/1（ADR-0097 D5a，补充九）。

中性描述由 freecad_addon/fc/mbd_assembly.py 在 FreeCAD 里收集，这里只做确定性的换算和检查，不碰 FreeCAD：

    {"name": 装配体名,
     "parts": [{"id": FreeCAD 对象名, "label": 显示名, "grounded": bool, "mass_kg": 可选覆盖,
                "solids": [{"label", "volume_mm3", "cm_mm": [3], "inertia_unit_mm5": 3×3（单位密度、对质心、地面轴的惯性张量），
                            "material": 材料名或 None, "density_kg_m3": 数或 None}]}],
     "joints": [{"id", "label", "type": FreeCAD JointType, "part1", "part2",
                 "frame1": {"origin_mm": [3], "z": [3], "x": [3]}, "frame2": {...}}]}

规则：不估密度（没材料就报错）；不支持的运动副报错而不是丢掉。
"""

from __future__ import annotations

import re

import numpy as np

GRAVITY_MM_S2 = [0.0, 0.0, -9810.0]
DEFAULT_MATERIALS = {"Default", "", None}
JOINT_MAP = {"Fixed": "fixed", "Revolute": "revolute", "Cylindrical": "cylindrical", "Slider": "translational",
             "Ball": "spherical"}
UNSUPPORTED_HINT = {
    "Gears": "FreeCAD 的齿轮副只有半径，没有齿数和模数；请在模型里用 gear_mesh 力元",
    "Belt": "带传动请用两个转动副加 gear_mesh 以外的方式建模（D8 前不支持）",
    "RackPinion": "齿轮齿条 D3 不支持",
    "Screw": "螺旋副不支持（可用移动副 + 转动副 + 驱动关系近似）",
    "Distance": "距离约束不是运动副，请改成运动副",
    "Parallel": "平行约束不是运动副，请改成运动副",
    "Perpendicular": "垂直约束不是运动副，请改成运动副",
    "Angle": "角度约束不是运动副，请改成运动副",
}
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,63}$")


class AssemblyError(ValueError):
    """装配体不能变成模型：problems 是给使用者看的逐条原因"""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("；".join(self.problems))


def _id(raw: str, used: set) -> str:
    s = re.sub(r"[^A-Za-z0-9_\-]", "_", raw or "")
    if not s or not s[0].isalpha():
        s = "p_" + s
    s = s[:60]
    base, k = s, 2
    while s in used or s == "ground":
        s = f"{base[:56]}_{k}"
        k += 1
    used.add(s)
    return s


def mass_properties(part: dict) -> tuple[float, np.ndarray, np.ndarray, list[str]]:
    """(质量 kg, 质心 mm, 对质心的惯性张量 kg·m²（地面轴）, 问题列表)"""
    problems = []
    ms, cms, Is = [], [], []
    for s in part.get("solids", []):
        rho = s.get("density_kg_m3")
        if s.get("material") in DEFAULT_MATERIALS or rho is None or rho <= 0:
            problems.append(f"零件“{part.get('label') or part['id']}”的“{s.get('label', '')}”没有设材料（或是 Default），"
                            "不能算质量和惯量：请在 FreeCAD 里给它指定材料")
            continue
        V = float(s["volume_mm3"])
        if V <= 0:
            problems.append(f"零件“{part.get('label') or part['id']}”的“{s.get('label', '')}”体积为 0（不是实体？）")
            continue
        ms.append(rho * V * 1e-9)
        cms.append(np.asarray(s["cm_mm"], float))
        Is.append(rho * np.asarray(s["inertia_unit_mm5"], float) * 1e-15)
    if problems or not ms:
        if not problems:
            problems.append(f"零件“{part.get('label') or part['id']}”没有实体，不能算质量")
        return 0.0, np.zeros(3), np.zeros((3, 3)), problems
    m = float(sum(ms))
    c = sum(mi * ci for mi, ci in zip(ms, cms, strict=True)) / m
    I = np.zeros((3, 3))
    for mi, ci, Ii in zip(ms, cms, Is, strict=True):
        d = (ci - c) * 1e-3
        I += Ii + mi * ((d @ d) * np.eye(3) - np.outer(d, d))       # 平行轴定理
    over = part.get("mass_kg")
    if over is not None:
        if over <= 0:
            return 0.0, c, I, [f"零件“{part.get('label') or part['id']}”的质量覆盖要大于 0"]
        I *= over / m                     # 按质量比例缩放惯量（形状不变、密度均匀改变）
        m = float(over)
    return m, c, I, []


def to_model(asm: dict, *, gravity_mm_s2=None, analysis=None) -> tuple[dict, list[str]]:
    """中性描述 → (mbd-model/1, 消息)。有问题抛 AssemblyError（列出全部问题，不只第一个）"""
    problems, messages = [], []
    used: set = set()
    pid = {}
    bodies = []
    grounded = set()
    for p in asm.get("parts", []):
        if p.get("grounded"):
            grounded.add(p["id"])
            pid[p["id"]] = "ground"
            continue
        m, c, I, pr = mass_properties(p)
        problems += pr
        bid = _id(p["id"], used)
        pid[p["id"]] = bid
        if pr:
            continue
        bodies.append({"id": bid, "name": p.get("label") or p["id"], "mass_kg": m, "cm_mm": [float(x) for x in c],
                       "inertia_kg_m2": {"ixx": float(I[0, 0]), "iyy": float(I[1, 1]), "izz": float(I[2, 2]),
                                         "ixy": float(I[0, 1]), "ixz": float(I[0, 2]), "iyz": float(I[1, 2])},
                       "source": f"FreeCAD {p['id']}" + (f"，质量按使用者填写 {p['mass_kg']} kg" if p.get("mass_kg") else "")})
    if not grounded:
        problems.append("装配体里没有固定零件（Grounded）：请把机架设为固定")
    joints = []
    jused: set = set()
    for j in asm.get("joints", []):
        name = j.get("label") or j["id"]
        typ = j.get("type")
        if typ not in JOINT_MAP:
            problems.append(f"运动副“{name}”（{typ}）不能用于动力学：" + UNSUPPORTED_HINT.get(typ, "不认识的类型"))
            continue
        a, b = j.get("part1"), j.get("part2")
        if a not in pid or b not in pid:
            problems.append(f"运动副“{name}”连的零件不在装配体里（{a}、{b}）")
            continue
        bi, bj = pid[a], pid[b]
        if bi == "ground" and bj == "ground":
            messages.append(f"运动副“{name}”两边都是固定零件，已略过")
            continue
        f1, f2 = j["frame1"], j["frame2"]
        o1, o2 = np.asarray(f1["origin_mm"], float), np.asarray(f2["origin_mm"], float)
        z1, z2 = _unit(f1["z"]), _unit(f2["z"])
        # 装配求解后两个运动副坐标系应当重合（点重合，Z 轴共线）；不重合说明装配没解好，按它建模会装不上
        gap = o2 - o1
        if typ in ("Slider", "Cylindrical"):
            gap = gap - (gap @ z1) * z1          # 沿轴可以错开，只看偏离轴线的距离
        if np.linalg.norm(gap) > 1e-3:
            problems.append(f"运动副“{name}”两侧坐标系相距 {np.linalg.norm(gap):.4g} mm：请先在 FreeCAD 里求解装配")
            continue
        if abs(abs(z1 @ z2) - 1) > 1e-6:
            problems.append(f"运动副“{name}”两侧 Z 轴不共线：请先在 FreeCAD 里求解装配")
            continue
        jt = {"id": _id(j["id"], jused), "type": JOINT_MAP[typ], "body_i": bi, "body_j": bj,
              "point_mm": [float(x) for x in o1]}
        if typ in ("Revolute", "Cylindrical", "Slider"):
            jt["axis"] = [float(x) for x in z1]
        joints.append(jt)
    if problems:
        raise AssemblyError(problems)
    if gravity_mm_s2 is None:
        gravity_mm_s2 = GRAVITY_MM_S2
        messages.append("重力取 −Z 方向 9810 mm/s²（FreeCAD 装配体里没有重力方向，若机构不是 Z 向上请改）")
    model = {"format": "mbd-model/1", "name": asm.get("name") or "FreeCAD 装配体", "gravity_mm_s2": list(gravity_mm_s2),
             "bodies": bodies, "joints": joints, "analysis": analysis or {"type": "dynamic", "end_time_s": 1.0},
             "source": "FreeCAD Assembly 工作台装配体（ADR-0097 D5a）：质量、惯量由实体与材料密度精确积分"}
    return model, messages


def _unit(v):
    a = np.asarray(v, float)
    n = np.linalg.norm(a)
    if n < 1e-12:
        raise AssemblyError(["运动副坐标系的 Z 轴是零向量"])
    return a / n
