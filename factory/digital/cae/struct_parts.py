# -*- coding: utf-8 -*-
"""强度、模态的参数化示例零件（第 66 轮 D-2）：WQ-CR5 大臂（铝管 + 两端的端部法兰）。教材《机器人学》第 31 章的算例在这里再算一遍。

gmsh（OpenCASCADE）现做 STEP（单位 mm）：管轴沿 z，z = 0 的端面装在 J2 模组上（固定），z = L 的端面接 J3 模组（受力）。
预设工况取机器人厂原件 wqcr5.py 的 upper_arm_end_loads()：手臂水平伸直、工具朝下、带 5 kg 负载时，J3 端以外的部分
（J3 模组、小臂、手腕、负载）压在大臂端面上的力和力矩；零件坐标 x 沿 J2 的轴，y 朝上，z 沿管轴。
同时给出梁理论的估算（教材式 (31.1.x)、(31.2.x)），让学生把云图和手算对上。
"""
import math
import os
import tempfile

DEFAULTS = {"wqcr5_upper": {"L": 400.0, "D": 90.0, "t": 3.0, "flange_t": 10.0, "bore": 50.0, "payload_kg": 5.0}}
LABELS = {"wqcr5_upper": "WQ-CR5 大臂（铝管 + 法兰，强度与模态）"}
PARAM_NAMES = {"wqcr5_upper": {"L": "关节间距（大臂长）mm", "D": "铝管外径 mm", "t": "铝管壁厚 mm", "flange_t": "端部法兰厚 mm",
                               "bore": "法兰中间的线缆孔径 mm", "payload_kg": "负载 kg（定预设载荷）"}}
ANALYSIS = {"wqcr5_upper": "static"}


def params_of(key, p=None):
    out = dict(DEFAULTS[key])
    for k, v in (p or {}).items():
        if k in out:
            out[k] = float(v)
    if not 1.0 <= out["t"] <= out["D"] / 4:
        raise ValueError("壁厚要在 1 mm 到外径的 1/4 之间")
    if not 40 <= out["D"] <= 160:
        raise ValueError("外径要在 40–160 mm")
    if not 200 <= out["L"] <= 700:
        raise ValueError("大臂长要在 200–700 mm")
    if not 4 <= out["flange_t"] <= out["L"] / 5:
        raise ValueError("法兰厚要在 4 mm 到大臂长的 1/5 之间")
    if not 10 <= out["bore"] <= out["D"] - 2 * out["t"] - 6:
        raise ValueError("线缆孔要在 10 mm 到管内径减 6 mm 之间")
    if not 0 <= out["payload_kg"] <= 10:
        raise ValueError("负载要在 0–10 kg")
    return out


def build(key, p):
    """铝管两端各一块端部法兰（外径同管、中间开线缆孔），整体一块：J2、J3 模组用螺钉装在法兰的端面上（螺孔省略）。
    用 gmsh 的 OpenCASCADE 内核建模、写 STEP（问渠 CAE、教材的构建环境都有 gmsh，不必再装 build123d）"""
    from cae.geometry import _LOCK, _gmsh
    L, D, t, ft, b = p["L"], p["D"], p["t"], p["flange_t"], p["bore"]
    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        gmsh = _gmsh()
        gmsh.clear()
        gmsh.model.add("wqcr5_upper")
        occ = gmsh.model.occ
        outer = occ.addCylinder(0, 0, 0, 0, 0, L, D / 2)
        cav = occ.addCylinder(0, 0, ft, 0, 0, L - 2 * ft, D / 2 - t)
        bore = occ.addCylinder(0, 0, 0, 0, 0, L, b / 2)
        occ.cut([(3, outer)], [(3, cav), (3, bore)])
        occ.synchronize()
        f = os.path.join(tmp, key + ".step")
        gmsh.write(f)
        gmsh.clear()
        return open(f, "rb").read()


def end_faces(p, faces):
    """J2 端（z = 0）、J3 端（z = L）的端面"""
    def pick(z):
        return [f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][2] - z) < 1e-3]
    return pick(0.0), pick(p["L"])


def beam(p, loads):
    """梁理论（把整根当作外径 D、壁厚 t 的等截面悬臂管，法兰当刚性不计）：根部弯矩、应力，端部下沉，一阶固有频率（只算这根管）"""
    from cae import materials as MT
    m = MT.get("6061-T6")
    E, nu, rho = m["E_mpa"], m["nu"], m["density"] * 1e-9 * 1e3          # MPa、—、kg/mm³
    L, ro, ri = p["L"], p["D"] / 2, p["D"] / 2 - p["t"]
    I = math.pi / 4 * (ro ** 4 - ri ** 4)                                 # mm⁴
    J = 2 * I
    A = math.pi * (ro ** 2 - ri ** 2)
    G = E / (2 * (1 + nu))
    Fy, Mx, Tz = loads["force_n"][1], loads["moment_nm"][0] * 1e3, loads["moment_nm"][2] * 1e3
    M_root = abs(Mx - Fy * L)                                            # N·mm：端部力矩 + 端部力 × 管长
    sig = M_root * ro / I
    tau = abs(Tz) * ro / J
    vm = math.sqrt(sig ** 2 + 3 * tau ** 2)
    delta = abs(Fy) * L ** 3 / (3 * E * I) + abs(Mx) * L ** 2 / (2 * E * I)
    phi = abs(Tz) * L / (G * J)
    f1 = 1.875104 ** 2 / (2 * math.pi) * math.sqrt(E * 1e6 * I * 1e-12 / (rho * 1e9 * A * 1e-6 * (L * 1e-3) ** 4))
    # 端部法兰的质量当作端部集中质量（瑞利法：均布梁折到端部的等效质量 0.2357 m）
    m_tube = rho * A * (L - 2 * p["flange_t"])                            # kg
    m_tip = rho * math.pi * (ro ** 2 - (p["bore"] / 2) ** 2) * p["flange_t"]
    f1_tip = math.sqrt(3 * E * I / L ** 3 * 1e3 / (0.2357 * m_tube + m_tip)) / (2 * math.pi)
    return {"M_root_nm": round(M_root / 1e3, 2), "T_nm": round(abs(Tz) / 1e3, 2), "sigma_mpa": round(sig, 2), "tau_mpa": round(tau, 3),
            "vm_mpa": round(vm, 2), "delta_mm": round(delta, 5), "twist_deg": round(math.degrees(phi), 5), "f1_hz": round(f1, 1), "f1_tip_hz": round(f1_tip, 1), "m_tip_kg": round(m_tip, 3),
            "I_mm4": round(I), "yield_mpa": m["yield_mpa"], "sf": round(m["yield_mpa"] / vm, 1)}


def example(key, p, faces):
    """预设的约束与载荷（网页“填入示范题”）和梁理论的估算"""
    from cae import wqcr5 as W
    fixed, tip = end_faces(p, faces)
    with W.geometry(a2=p["L"] / 1000):                    # 大臂的截面不影响 J3 端以外的重力，只有长度影响姿态（伸直时也不影响）
        ld = W.upper_arm_end_loads(p["payload_kg"])
    F = [round(float(x), 2) for x in ld["force_n"]]
    M = [round(float(x), 3) for x in ld["moment_nm"]]
    b = beam(p, {"force_n": F, "moment_nm": M})
    rows = [{"kind": "fixed", "faces": fixed},
            {"kind": "force", "faces": tip, "fx": F[0], "fy": F[1], "fz": F[2]},
            {"kind": "moment", "faces": tip, "mx": M[0], "my": M[1], "mz": M[2]}]
    formula = dict(b, name="梁理论（《机器人学》31.1–31.3 节）：σ = M·r/I，τ = T·r/J，δ = F L³/(3EI) + M L²/(2EI)，f₁ = (1.875²/2π)·√(EI/(ρA L⁴))；计入端部法兰的质量 f₁ ≈ √(3EI/L³ ÷ (0.2357 m管 + m法兰))/2π",
                   note="预设载荷 = 手臂水平伸直、工具朝下、带 {:g} kg 时 J3 端以外部分的重力（不含这根管自己的重量）；梁理论把法兰当作刚性、"
                        "不计法兰与管连接处的应力集中；固有频率只算这根管一端固定，装到机器人上以后关节的柔性和负载让整机的一阶频率低得多（31.5 节）".format(p["payload_kg"]))
    return {"analysis": "static", "material_id": "6061-T6", "rows": rows, "formula": formula, "groups": {"fixed": fixed, "tip": tip},
            "title": "WQ-CR5 大臂 Ø{:g}×{:g}（伸直、{:g} kg）".format(p["D"], p["t"], p["payload_kg"]),
            "mesh_mm": float(round(min(8.0, max(5.0, 2.7 * p["t"]))))}
