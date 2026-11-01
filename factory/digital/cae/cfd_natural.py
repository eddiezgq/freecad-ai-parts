# -*- coding: utf-8 -*-
"""自然对流（第 62 轮）：静止空气里的热物体，浮力带动空气流动——没有风扇的电控箱（缝纫机电控箱最常见）、电控柜。

和强制对流（cfd.py 虚拟风洞）的区别：
  - 求解器 buoyantPimpleFoam（非定常跑到稳定，后段几帧平均；定常的 buoyantSimpleFoam 在这种网格上几步就发散），重力 (0 0 −9.81)，
    空气按理想气体（密度随温度变，浮力就从这里来），层流（Ra < 10⁹）；
  - 计算域是一间封闭的“房间”：六面墙都是车间温度、不滑移，离零件水平 1.5 倍、下面 1 倍、上面 3 倍特征尺寸——
    比开口边界稳得多（开口边界在 v1912 上几步就发散），房间够大时对零件表面的 h 影响很小；
  - 零件表面定温 t_wall（外壳平均温度的估计）；h = 散热量 / (面积 × (t_wall − t_air))。自然对流的 h ∝ ΔT^¼，
    表面温度估得差 30%，h 只差约 7%，所以不用反复迭代（网关拿公式估的温度来算）。
  - 辐射不在流体里算：外壳的辐射散热系数按 εσ(T_s² + T_a²)(T_s + T_a) 另加（温度场里一起用）。
"""
import time

import numpy as np

from cae import cfd as CF
from cae import foam as F

G = 9.81
LIMIT_S = 1500           # 非定常比强制对流慢：4 核约 5–8 分钟，留足余量


def domain(box):
    """计算域（封闭房间）：零件周围水平各留 1.5 倍特征尺寸，下面 1 倍，上面 3 倍（热羽流往上走）"""
    lo, hi = box[:3].copy(), box[3:].copy()
    Lc = float((hi - lo).max())
    a, b = lo.copy(), hi.copy()
    for k in (0, 1):
        a[k] -= 1.5 * Lc
        b[k] += 1.5 * Lc
    a[2] -= 1.0 * Lc
    b[2] += 3.0 * Lc
    return a, b, Lc


def case_files(case, parts, opens, t_air, t_wall, t_end, t_write):
    """非定常 buoyantPimpleFoam 跑到流动稳定（定常 buoyantSimpleFoam 在这种贴体网格上几步就发散）；每 t_write 秒写一次，后处理取后段平均"""
    F.write(case, "system/controlDict", """application buoyantPimpleFoam; startFrom startTime; startTime 0; stopAt endTime; endTime {e:g};
deltaT 0.002; adjustTimeStep yes; maxCo 2; maxDeltaT 0.1;
writeControl adjustableRunTime; writeInterval {w:g}; writeFormat ascii; writePrecision 8; writeCompression off;
timeFormat general; timePrecision 6; runTimeModifiable false;
""".format(e=t_end, w=t_write))
    F.write(case, "system/decomposeParDict", "numberOfSubdomains {0}; method simple;\nsimpleCoeffs {{ n ({0} 1 1); delta 0.001; }}\n".format(CF.NPROC))
    F.write(case, "constant/g", "dimensions [0 1 -2 0 0 0 0];\nvalue (0 0 {:.4g});\n".format(-G), "uniformDimensionedVectorField")
    F.write(case, "constant/thermophysicalProperties", """thermoType {{ type heRhoThermo; mixture pureMixture; transport const; thermo hConst;
  equationOfState perfectGas; specie specie; energy sensibleEnthalpy; }}
mixture {{ specie {{ molWeight {M}; }} thermodynamics {{ Cp {cp}; Hf 0; }} transport {{ mu {mu}; Pr {Pr}; }} }}
""".format(**CF.AIR))
    F.write(case, "constant/turbulenceProperties", "simulationType laminar;\n")
    F.write(case, "system/fvSchemes", """ddtSchemes { default Euler; }
gradSchemes { default Gauss linear; }
divSchemes { default none; div(phi,U) Gauss linearUpwind grad(U); div(phi,h) Gauss limitedLinear 1;
  div(phi,K) Gauss linear; div(phi,Ekp) Gauss linear; div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear; }
laplacianSchemes { default Gauss linear limited corrected 0.5; }
interpolationSchemes { default linear; }
snGradSchemes { default limited corrected 0.5; }
""")
    F.write(case, "system/fvSolution", """solvers {
  "rho.*" { solver PCG; preconditioner DIC; tolerance 0; relTol 0; }
  p_rgh { solver GAMG; smoother DIC; tolerance 1e-7; relTol 0.01; }
  p_rghFinal { $p_rgh; relTol 0; }
  "(U|h)" { solver PBiCGStab; preconditioner DILU; tolerance 1e-7; relTol 0.1; }
  "(U|h)Final" { $U; relTol 0; }
}
PIMPLE { momentumPredictor yes; nOuterCorrectors 2; nCorrectors 2; nNonOrthogonalCorrectors 0; pRefCell 0; pRefValue 101325; }
relaxationFactors { equations { ".*" 1; } }
""")
    F.write(case, "system/fvOptions", """limitT {{ type limitTemperature; active yes; selectionMode all; min {lo:.6g}; max {hi:.6g}; }}
""".format(lo=t_air + 273.15 - 5, hi=t_wall + 273.15 + 5))
    Ta, Tw = t_air + 273.15, t_wall + 273.15

    def bf(open_bc, wall_bc):
        out = {n: open_bc for n in opens}
        out.update({n: wall_bc for n in parts})
        return CF._bf(out)
    F.write(case, "0/U", "dimensions [0 1 -1 0 0 0 0];\ninternalField uniform (0 0 0);\n" + bf("type noSlip;", "type noSlip;"), "volVectorField")
    F.write(case, "0/p_rgh", "dimensions [1 -1 -2 0 0 0 0];\ninternalField uniform 101325;\n"
            + bf("type fixedFluxPressure; value uniform 101325;", "type fixedFluxPressure; value uniform 101325;"), "volScalarField")
    F.write(case, "0/p", "dimensions [1 -1 -2 0 0 0 0];\ninternalField uniform 101325;\n"
            + bf("type calculated; value uniform 101325;", "type calculated; value uniform 101325;"), "volScalarField")
    F.write(case, "0/T", "dimensions [0 0 0 1 0 0 0];\ninternalField uniform {:.6g};\n".format(Ta)
            + bf("type fixedValue; value uniform {:.6g};".format(Ta), "type fixedValue; value uniform {:.6g};".format(Tw)), "volScalarField")


def solve(step_bytes, setup, workdir, progress=None):
    """返回 (stats, surface, aux)，格式同 cfd.solve：每个 CAD 面的 h、散热量，表面 h，竖直截面上的速度、流线"""
    from scipy.spatial import cKDTree
    t0 = time.time()
    fl = setup.get("flow") or {}
    t_air = float(fl.get("air_t_c", 25.0))
    t_wall = float((setup.get("heat") or {}).get("wall_t_c", t_air + 20))
    if not 1 <= t_wall - t_air <= 150:
        raise ValueError("自然对流：表面要比空气热 1–150 ℃")
    stl, box, ids, surf = CF.stl_by_face(step_bytes)
    a, b, Lc = domain(box)
    size = box[3:] - box[:3]
    area = 2 * (size[0] * size[1] + size[1] * size[2] + size[0] * size[2])
    target = int((setup.get("mesh") or {}).get("cells_target", 80_000))      # 贴近零件的距离加密后约 10 万；18 万时 h 只差 3%
    level = int((setup.get("mesh") or {}).get("level", 3))
    cell = Lc / 4
    while CF.estimate_cells(a, b, cell, area, level) < target * 0.6 and cell > Lc / 40:
        cell /= 1.25
    while CF.estimate_cells(a, b, cell, area, level) > target and cell < Lc:
        cell *= 1.12
    case = workdir
    inside = a + (b - a) * np.array([0.03, 0.03, 0.97])
    CF.write_mesh_dicts(case, stl, box, "+z", cell, level, False, inside=inside, bounds=(a, b, Lc))
    # 不贴体（snap false）：贴体时边角挤出的歪斜单元在重力下会算出假流动，几步就发散；电控箱这种和坐标轴对齐的外形，
    # 六面体台阶网格本身就几乎是准的（斜面、圆角会成台阶，散热量偏差在几个百分点）
    import os
    fn = os.path.join(case, "system/snappyHexMeshDict")
    txt = open(fn).read().replace("snap true;", "snap false;", 1)
    # 自然对流的边界层只有几毫米到一两厘米厚：贴着零件 1.5 cm 内用表面那一级，5 cm 内低一级
    txt = txt.replace("refinementRegions { }", "refinementRegions {{ part {{ mode distance; levels ((0.015 {0}) (0.05 {1})); }} }}".format(
        int(level), max(1, int(level) - 1)), 1)
    open(fn, "w").write(txt)
    if progress:
        progress("网格")
    F.run(case, "blockMesh", timeout=120)
    F.run(case, "snappyHexMesh", "-overwrite", timeout=CF.LIMIT_S)
    mesh = F.Mesh(case)
    if mesh.n_cells > CF.MAX_CELLS * 1.2:
        raise ValueError("网格 {} 个单元，超过上限 {}".format(mesh.n_cells, CF.MAX_CELLS))
    parts = [k for k in mesh.boundary if k.startswith("part")]
    if not parts:
        raise ValueError("网格里没有零件表面：STEP 可能不是封闭实体")
    opens = ["xmin", "xmax", "ymin", "ymax", "zmin", "zmax"]
    t_end = float((setup.get("solver") or {}).get("t_end_s", 20))          # 0.26 m 的箱子，羽流几秒到顶，20 s 已稳定（后 40% 总散热量波动 < 2%）
    t_write = t_end / 10
    case_files(case, parts, opens, t_air, t_wall, t_end, t_write)
    if progress:
        progress("流场与温度场（自然对流，非定常跑到稳定）")
    log = CF.run_solver(case, "buoyantPimpleFoam", timeout=LIMIT_S)
    if CF.NPROC > 1:                                    # run_solver 只拼了最后一帧；后段平均要几帧
        F.run(case, "reconstructPar", "-newTimes", timeout=300)
    # 后 40% 时间里写出的几帧平均（羽流会轻微摆动）
    import glob
    import os
    times = sorted(float(os.path.basename(d)) for d in glob.glob(os.path.join(case, "[0-9]*")) if os.path.basename(d) != "0")
    use = [t for t in times if t >= 0.6 * t_end - 1e-6] or times[-1:]
    face, hface = {}, {}
    acc = {}
    for t in use:
        tn = "{:g}".format(t)
        T, _ = F.read_field(case, tn, "T", mesh)
        for pn in parts:
            Q, q, A = CF.wall_heat(mesh, T, pn, t_wall + 273.15)
            a0 = acc.setdefault(pn, [0.0, np.zeros_like(q), A])
            a0[0] += Q / len(use)
            a0[1] = a0[1] + q / len(use)
    U, _ = F.read_field(case, "{:g}".format(use[-1]), "U", mesh)
    T, _ = F.read_field(case, "{:g}".format(use[-1]), "T", mesh)
    res = {}
    Qt = At = 0.0
    for pn in parts:
        fid = int(pn.split("_f")[-1]) if "_f" in pn else 0
        Q, q, A = acc[pn]
        if A.sum() <= 0:                                      # 箱子里面的面（封闭空腔不在网格里）
            continue
        h = Q / (A.sum() * (t_wall - t_air))
        face[fid] = {"id": fid, "area_mm2": float(A.sum() * 1e6), "p_pa": 0.0, "force_n": [0.0, 0.0, 0.0], "heat_w": Q, "h_w_m2k": h}
        hface[pn] = q / (t_wall - t_air)
        Qt += Q
        At += A.sum()
    # 收敛：后段几帧的总散热量相对波动
    series = []
    for t in use:
        Tt, _ = F.read_field(case, "{:g}".format(t), "T", mesh)
        series.append(sum(CF.wall_heat(mesh, Tt, pn, t_wall + 273.15)[0] for pn in parts))
    spread = (max(series) - min(series)) / max(abs(np.mean(series)), 1e-9) if len(series) > 1 else 0.0
    # 瑞利数（按外形高度）：判断层流
    Tf = (t_wall + t_air) / 2 + 273.15
    nu, alpha = CF.AIR["mu"] / CF.AIR["rho"], CF.AIR["k"] / (CF.AIR["rho"] * CF.AIR["cp"])
    Ra = G * (1 / Tf) * (t_wall - t_air) * float(size[2]) ** 3 / (nu * alpha)
    vmax = float(np.linalg.norm(U, axis=1).max())
    stats = {"cells": int(mesh.n_cells), "cell_mm": round(cell * 1000, 2), "level": level, "iterations": len(times),
             "converged": bool(spread < 0.05), "heat_spread": float(spread), "t_end_s": t_end, "averaged_s": [float(use[0]), float(use[-1])],
             "residuals": res, "turbulence": "laminar", "mode": "natural",
             "Ra": float(Ra), "Re": None, "L_char_mm": round(Lc * 1000, 1), "velocity_ms": vmax, "direction": "+z", "air_t_c": t_air,
             "drag_n": 0.0, "drag_pressure_n": 0.0, "drag_friction_n": 0.0, "frontal_m2": 0.0, "Cd": None, "q_dyn_pa": 0.0,
             "wall_t_c": t_wall, "heat_w": float(Qt), "h_mean": float(Qt / (At * (t_wall - t_air))), "area_m2": float(At),
             "T_out_max_c": float(T.max() - 273.15)}
    fc, vh = [], []
    for pn in parts:
        sl = mesh.patch(pn)
        fc.append(mesh.Cf[sl])
        vh.append(hface.get(pn, np.zeros(len(mesh.Cf[sl]))))
    tree = cKDTree(np.concatenate(fc))
    _, k = tree.query(surf["pos"])
    vh = np.concatenate(vh)[k]
    surface = {"positions": surf["pos"] * 1000.0, "p": np.zeros(len(vh)), "h": vh, "triangles": surf["tri"], "face_of_triangle": surf["face"]}
    aux = {"slice": CF.velocity_slice(mesh, U, box, 2, a, b), "streamlines": CF.streamlines(mesh, U, box, 2, 1, a, b),
           "faces": [face[k] for k in sorted(face)]}
    stats["seconds"] = round(time.time() - t0, 1)
    return stats, surface, aux


def h_radiation(eps, t_surf_c, t_air_c):
    """辐射散热系数 W/(m²·K)：εσ(T_s² + T_a²)(T_s + T_a)（四周是同温的车间墙面）"""
    Ts, Ta = t_surf_c + 273.15, t_air_c + 273.15
    return eps * 5.670e-8 * (Ts * Ts + Ta * Ta) * (Ts + Ta)


def h_vertical_plate(dT, H):
    """教科书竖板层流自然对流的简化式 h = 1.42·(ΔT/H)^¼（空气），核对用"""
    return 1.42 * (dT / H) ** 0.25 if dT > 0 and H > 0 else 0.0


def check_ra(Ra):
    return "laminar" if Ra < 1e9 else "turbulent"

