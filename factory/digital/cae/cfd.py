# -*- coding: utf-8 -*-
"""流体分析（第 16 轮）：OpenFOAM（独立程序）+ 自写的建模和后处理。

流程（虚拟风洞 / 风道）：
  STEP → 按 CAD 面分开的表面 STL（米）→ 背景网格 blockMesh（长方体风洞）→ snappyHexMesh 贴体（每个 CAD 面一个边界 f<编号>）
  → simpleFoam（不可压定常；层流或 k-ω SST）——冷态流场
  → 换热时改用 buoyantSimpleFoam（重力取 0 = 强制对流，空气理想气体常物性）——流场和温度场一起算
  → 后处理（numpy）：每个面的压力力、摩擦力、散热量和平均散热系数 h，阻力 / 压降，速度截面，表面压力 / h。
单位：网格和场都是国际单位（米、秒、帕、开尔文）；对外的结果给 mm、℃、W/(m²·K)。"""
import math
import os
import tempfile

import numpy as np

from cae import foam as F

AIR = {"rho": 1.184, "mu": 1.849e-5, "cp": 1007.0, "k": 0.02551, "Pr": 0.7296, "M": 28.96}       # 25 ℃、1 atm（Incropera 附表 A.4）
MAX_CELLS = 300_000
LIMIT_S = 900
NPROC = max(1, min(4, int(os.environ.get("WQ_CFD_NPROC", os.cpu_count() or 1))))      # 并行核数（最多 4）


def run_solver(case, app, timeout=LIMIT_S):
    """多核时分块并行（decomposePar → mpirun → reconstructPar），单核直接跑"""
    if NPROC <= 1:
        return F.run(case, app, timeout=timeout)
    import glob
    import shutil
    for d in glob.glob(os.path.join(case, "processor*")):
        shutil.rmtree(d, ignore_errors=True)
    F.run(case, "decomposePar", "-force", timeout=120)
    log = F.run(case, "mpirun", "--allow-run-as-root", "--oversubscribe", "-np", str(NPROC), app, "-parallel", timeout=timeout, log=app)
    F.run(case, "reconstructPar", "-latestTime", timeout=120)
    return log


# ---------------------------------------------------------------- 几何
def stl_by_face(step_bytes, size_mm=None):
    """STEP → ASCII STL（米），每个 CAD 面一个 solid（名 f<编号>）。返回 (stl 文本, 包围盒 m, 面编号列表, 表面三角形)"""
    from cae import geometry as G
    with G._LOCK, tempfile.TemporaryDirectory() as tmp:
        gmsh = G._gmsh()
        G.load_step(gmsh, step_bytes, tmp)
        bb = gmsh.model.getBoundingBox(-1, -1)
        diag = math.dist(bb[:3], bb[3:])
        gmsh.option.setNumber("Mesh.MeshSizeMax", size_mm or diag / 60)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
        gmsh.model.mesh.generate(2)
        parts, ids, surf = [], [], {"pos": [], "tri": [], "face": []}
        nv = 0
        for _, tag in gmsh.model.getEntities(2):
            ntags, xyz, _ = gmsh.model.mesh.getNodes(2, tag, includeBoundary=True)
            etypes, _, enodes = gmsh.model.mesh.getElements(2, tag)
            if not len(ntags) or not etypes:
                continue
            idx = {int(t): i for i, t in enumerate(ntags)}
            p = np.asarray(xyz, float).reshape(-1, 3) / 1000.0
            tri = np.array([idx[int(n)] for n in enodes[0]], int).reshape(-1, 3)
            lines = ["solid f{}".format(tag)]
            for a, b, c in tri:
                n = np.cross(p[b] - p[a], p[c] - p[a])
                ln = np.linalg.norm(n)
                n = n / ln if ln > 0 else n
                lines.append(" facet normal {:.6e} {:.6e} {:.6e}\n  outer loop\n   vertex {:.7e} {:.7e} {:.7e}\n"
                             "   vertex {:.7e} {:.7e} {:.7e}\n   vertex {:.7e} {:.7e} {:.7e}\n  endloop\n endfacet".format(
                                 *n, *p[a], *p[b], *p[c]))
            lines.append("endsolid f{}".format(tag))
            parts.append("\n".join(lines))
            ids.append(int(tag))
            surf["pos"].append(p)
            surf["tri"].append(tri + nv)
            surf["face"].append(np.full(len(tri), tag))
            nv += len(p)
        box = np.array(bb, float) / 1000.0
    surf = {k: np.concatenate(v) for k, v in surf.items()}
    return "\n".join(parts) + "\n", box, ids, surf


# ---------------------------------------------------------------- 风洞
DIRS = {"+x": (0, 1), "-x": (0, -1), "+y": (1, 1), "-y": (1, -1), "+z": (2, 1), "-z": (2, -1)}


def tunnel(box, direction="+x", up=2.0, down=5.0, side=1.5, ground=False):
    """风洞范围（米）：来流方向前面 up 倍、后面 down 倍、侧面 side 倍零件特征尺寸。ground=True：零件放在地面上（-z 面贴底）"""
    lo, hi = box[:3].copy(), box[3:].copy()
    size = hi - lo
    Lc = float(size.max())
    ax, sg = DIRS[direction]
    a, b = lo.copy(), hi.copy()
    for k in range(3):
        if k == ax:
            a[k] -= (up if sg > 0 else down) * Lc
            b[k] += (down if sg > 0 else up) * Lc
        else:
            a[k] -= side * Lc
            b[k] += side * Lc
    if ground:
        a[2] = lo[2] - 1e-4 * Lc
    return a, b, Lc


def _names(direction):
    ax, sg = DIRS[direction]
    n = "xyz"[ax]
    return ("{}min".format(n), "{}max".format(n)) if sg > 0 else ("{}max".format(n), "{}min".format(n))


def write_mesh_dicts(case, stl, box, direction, cell, level, ground=False, inside=None, bounds=None):
    """blockMesh（背景网格）+ snappyHexMesh（贴体）"""
    a, b, Lc = bounds if bounds else tunnel(box, direction, ground=ground)
    _common(case, 1)
    F.write(case, "system/fvSchemes", "ddtSchemes { default steadyState; }\ngradSchemes { default Gauss linear; }\ndivSchemes { default none; }\n"
            "laplacianSchemes { default Gauss linear corrected; }\ninterpolationSchemes { default linear; }\nsnGradSchemes { default corrected; }\n")
    F.write(case, "system/fvSolution", "solvers { }\n")
    n = np.maximum(np.ceil((b - a) / cell).astype(int), 1)
    os.makedirs(os.path.join(case, "constant/triSurface"), exist_ok=True)
    open(os.path.join(case, "constant/triSurface/part.stl"), "w").write(stl)
    v = [(a[0], a[1], a[2]), (b[0], a[1], a[2]), (b[0], b[1], a[2]), (a[0], b[1], a[2]),
         (a[0], a[1], b[2]), (b[0], a[1], b[2]), (b[0], b[1], b[2]), (a[0], b[1], b[2])]
    faces = {"xmin": "(0 4 7 3)", "xmax": "(1 2 6 5)", "ymin": "(0 1 5 4)", "ymax": "(3 7 6 2)", "zmin": "(0 3 2 1)", "zmax": "(4 5 6 7)"}
    F.write(case, "system/blockMeshDict", "convertToMeters 1;\nvertices ({});\nblocks ( hex (0 1 2 3 4 5 6 7) ({} {} {}) simpleGrading (1 1 1) );\n"
            "boundary ( {} );\n".format(" ".join("({:.6g} {:.6g} {:.6g})".format(*p) for p in v), *n,
                                         " ".join("{} {{ type {}; faces ({}); }}".format(k, "wall" if (ground and k == "zmin") else "patch", f)
                                                  for k, f in faces.items())))
    # 网格内一点（流体里）：在零件外、靠近风洞角落
    pin = inside if inside is not None else a + (b - a) * np.array([0.0731, 0.0687, 0.9123 if not ground else 0.9123])
    F.write(case, "system/snappyHexMeshDict", """castellatedMesh true; snap true; addLayers false;
geometry {{ part.stl {{ type triSurfaceMesh; name part; }} }};
castellatedMeshControls {{
  maxLocalCells 2000000; maxGlobalCells {maxg}; minRefinementCells 0; nCellsBetweenLevels 3; maxLoadUnbalance 0.1;
  features ();
  refinementSurfaces {{ part {{ level ({lv} {lv}); patchInfo {{ type wall; }} }} }}
  resolveFeatureAngle 30;
  refinementRegions {{ }}
  locationInMesh ({px:.6g} {py:.6g} {pz:.6g});
  allowFreeStandingZoneFaces true;
}}
snapControls {{ nSmoothPatch 3; tolerance 2.0; nSolveIter 50; nRelaxIter 5; nFeatureSnapIter 10; implicitFeatureSnap true; explicitFeatureSnap false; multiRegionFeatureSnap false; }}
addLayersControls {{ relativeSizes true; layers {{ }} expansionRatio 1.2; finalLayerThickness 0.5; minThickness 0.1; nGrow 0; featureAngle 60;
  nRelaxIter 3; nSmoothSurfaceNormals 1; nSmoothNormals 3; nSmoothThickness 10; maxFaceThicknessRatio 0.5; maxThicknessToMedialRatio 0.3;
  minMedianAxisAngle 90; nBufferCellsNoExtrude 0; nLayerIter 50; }}
meshQualityControls {{ maxNonOrtho 65; maxBoundarySkewness 20; maxInternalSkewness 4; maxConcave 80; minVol 1e-30; minTetQuality 1e-30;
  minArea -1; minTwist 0.02; minDeterminant 0.001; minFaceWeight 0.05; minVolRatio 0.01; minTriangleTwist -1; nSmoothScale 4; errorReduction 0.75; }}
mergeTolerance 1e-6;
""".format(maxg=MAX_CELLS * 3, lv=int(level), px=pin[0], py=pin[1], pz=pin[2]))
    return a, b, Lc, n


def estimate_cells(a, b, cell, area_m2, level):
    """背景网格数 + 表面加密增加的单元数（粗估：表面附近 3 层细格）"""
    base = float(np.prod(np.ceil((b - a) / cell)))
    fine = cell / 2 ** level
    return int(base + 3 * area_m2 / fine ** 2 * (1 - 1 / 8))


# ---------------------------------------------------------------- 求解设置
def _common(case, end, write_every=None):
    F.write(case, "system/controlDict", """application x; startFrom startTime; startTime 0; stopAt endTime; endTime {e}; deltaT 1;
writeControl timeStep; writeInterval {w}; writeFormat ascii; writePrecision 8; writeCompression off; timeFormat general; timePrecision 6;
runTimeModifiable false;
""".format(e=end, w=write_every or end))
    F.write(case, "system/decomposeParDict", "numberOfSubdomains {0}; method simple;\nsimpleCoeffs {{ n ({0} 1 1); delta 0.001; }}\n".format(NPROC))


def flow_case(case, U, patches, turbulence="kOmegaSST", nu=AIR["mu"] / AIR["rho"], end=600, inlet=None, outlet=None,
              walls=(), slips=(), symm=()):
    """不可压定常（simpleFoam）。U：来流速度矢量 m/s；patches：零件的边界名（壁面，无滑移）；inlet / outlet：风洞进出口；
    slips：风洞侧面（滑移）；walls：其余壁面（无滑移，例如地面）"""
    _common(case, end)
    lam = turbulence == "laminar"
    F.write(case, "system/fvSchemes", """ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; grad(U) cellLimited Gauss linear 1; grad(k) cellLimited Gauss linear 1; grad(omega) cellLimited Gauss linear 1; }
divSchemes { default none; div(phi,U) bounded Gauss linearUpwind grad(U); div(phi,k) bounded Gauss upwind; div(phi,omega) bounded Gauss upwind;
  div((nuEff*dev2(T(grad(U))))) Gauss linear; }
laplacianSchemes { default Gauss linear limited corrected 0.5; }
interpolationSchemes { default linear; }
snGradSchemes { default limited corrected 0.5; }
wallDist { method meshWave; }
""")
    F.write(case, "system/fvSolution", """solvers {
  p { solver GAMG; smoother GaussSeidel; tolerance 1e-7; relTol 0.05; }
  "(U|k|omega)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0.1; }
}
SIMPLE { nNonOrthogonalCorrectors 1; consistent yes; residualControl { p 2e-4; U 2e-5; "(k|omega)" 1e-4; } }
relaxationFactors { equations { U 0.9; ".*" 0.7; } fields { p 1; } }
""")
    F.write(case, "constant/transportProperties", "transportModel Newtonian;\nnu {:.6g};\n".format(nu))
    F.write(case, "constant/turbulenceProperties", "simulationType laminar;\n" if lam else
            "simulationType RAS;\nRAS { RASModel kOmegaSST; turbulence on; printCoeffs off; }\n")
    _fields(case, U, patches, lam, inlet, outlet, walls, slips, symm, compressible=False)


def heat_case(case, U, patches, t_air_c, t_wall_c, turbulence="kOmegaSST", end=800, inlet=None, outlet=None,
              walls=(), slips=(), symm=(), wall_temps=None):
    """强制对流换热（buoyantSimpleFoam，g = 0）：零件表面定温 t_wall_c（或 wall_temps{边界: ℃}），来流 t_air_c"""
    _common(case, end)
    lam = turbulence == "laminar"
    F.write(case, "constant/g", "dimensions [0 1 -2 0 0 0 0];\nvalue (0 0 0);\n", "uniformDimensionedVectorField")
    F.write(case, "constant/thermophysicalProperties", """thermoType {{ type heRhoThermo; mixture pureMixture; transport const; thermo hConst;
  equationOfState perfectGas; specie specie; energy sensibleEnthalpy; }}
mixture {{ specie {{ molWeight {M}; }} thermodynamics {{ Cp {cp}; Hf 0; }} transport {{ mu {mu}; Pr {Pr}; }} }}
""".format(**AIR))
    F.write(case, "constant/turbulenceProperties", "simulationType laminar;\n" if lam else
            "simulationType RAS;\nRAS { RASModel kOmegaSST; turbulence on; printCoeffs off; }\n")
    F.write(case, "system/fvSchemes", """ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; grad(U) cellLimited Gauss linear 1; }
divSchemes { default none; div(phi,U) bounded Gauss linearUpwind grad(U); div(phi,h) bounded Gauss linearUpwind default;
  div(phi,k) bounded Gauss upwind; div(phi,omega) bounded Gauss upwind; div(phi,K) bounded Gauss linear; div(phi,Ekp) bounded Gauss linear;
  div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear; }
laplacianSchemes { default Gauss linear limited corrected 0.5; }
interpolationSchemes { default linear; }
snGradSchemes { default limited corrected 0.5; }
wallDist { method meshWave; }
""")
    F.write(case, "system/fvSolution", """solvers {
  p_rgh { solver GAMG; smoother DIC; tolerance 1e-8; relTol 0.01; }
  "(U|h|k|omega)" { solver PBiCGStab; preconditioner DILU; tolerance 1e-8; relTol 0.1; }
}
SIMPLE { momentumPredictor yes; nNonOrthogonalCorrectors 1; pRefCell 0; pRefValue 101325;
  residualControl { p_rgh 1e-5; U 1e-6; h 1e-7; "(k|omega)" 1e-5; } }
relaxationFactors { fields { rho 1.0; p_rgh 0.7; } equations { U 0.3; h 0.3; "(k|omega)" 0.5; } }
""")
    _fields(case, U, patches, lam, inlet, outlet, walls, slips, symm, compressible=True, t_air=t_air_c + 273.15,
            t_wall=t_wall_c + 273.15, wall_temps={k: v + 273.15 for k, v in (wall_temps or {}).items()})


def _bf(entries):
    return "boundaryField {\n" + "".join("  {} {{ {} }}\n".format(k, v) for k, v in entries.items()) + "}\n"


def _fields(case, U, parts, lam, inlet, outlet, walls, slips, symm, compressible=False, t_air=298.15, t_wall=343.15, wall_temps=None):
    Umag = float(np.linalg.norm(U))
    I, Lt = 0.05, 0.01                                                     # 来流湍流度 5%、湍流长度 1 cm（风扇出风的量级）
    k0 = 1.5 * (Umag * I) ** 2
    om0 = math.sqrt(k0) / (0.09 ** 0.25 * Lt)
    Uv = "uniform ({:.6g} {:.6g} {:.6g})".format(*U)
    groups = {"inlet": [inlet] if inlet else [], "outlet": [outlet] if outlet else [], "wall": list(parts) + list(walls),
              "slip": list(slips), "symm": list(symm)}

    def bc(spec):
        out = {}
        for g, names in groups.items():
            for n in names:
                out[n] = spec[g](n) if callable(spec[g]) else spec[g]
        return out
    U_bc = {"inlet": "type fixedValue; value {};".format(Uv), "outlet": "type inletOutlet; inletValue uniform (0 0 0); value {};".format(Uv),
            "wall": "type noSlip;", "slip": "type slip;", "symm": "type symmetry;"}
    F.write(case, "0/U", "dimensions [0 1 -1 0 0 0 0];\ninternalField {};\n".format(Uv) + _bf(bc(U_bc)), "volVectorField")
    if compressible:
        p_bc = {"inlet": "type fixedFluxPressure; value uniform 101325;", "outlet": "type prghPressure; p uniform 101325; value uniform 101325;",
                "wall": "type fixedFluxPressure; value uniform 101325;", "slip": "type fixedFluxPressure; value uniform 101325;",
                "symm": "type symmetry;"}
        F.write(case, "0/p_rgh", "dimensions [1 -1 -2 0 0 0 0];\ninternalField uniform 101325;\n" + _bf(bc(p_bc)), "volScalarField")
        pp = {g: ("type symmetry;" if g == "symm" else "type calculated; value uniform 101325;") for g in groups}
        F.write(case, "0/p", "dimensions [1 -1 -2 0 0 0 0];\ninternalField uniform 101325;\n" + _bf(bc(pp)), "volScalarField")
        T_bc = {"inlet": "type fixedValue; value uniform {:.6g};".format(t_air),
                "outlet": "type inletOutlet; inletValue uniform {0:.6g}; value uniform {0:.6g};".format(t_air),
                "wall": lambda n: "type fixedValue; value uniform {:.6g};".format((wall_temps or {}).get(n, t_wall if n in parts else t_air))
                if n in parts or (wall_temps and n in wall_temps) else "type zeroGradient;",
                "slip": "type zeroGradient;", "symm": "type symmetry;"}
        F.write(case, "0/T", "dimensions [0 0 0 1 0 0 0];\ninternalField uniform {:.6g};\n".format(t_air) + _bf(bc(T_bc)), "volScalarField")
    else:
        p_bc = {"inlet": "type zeroGradient;", "outlet": "type fixedValue; value uniform 0;", "wall": "type zeroGradient;",
                "slip": "type zeroGradient;", "symm": "type symmetry;"}
        F.write(case, "0/p", "dimensions [0 2 -2 0 0 0 0];\ninternalField uniform 0;\n" + _bf(bc(p_bc)), "volScalarField")
    if not lam:
        def tf(name, val, wall, dims):
            spec = {"inlet": "type fixedValue; value uniform {:.6g};".format(val),
                    "outlet": "type inletOutlet; inletValue uniform {0:.6g}; value uniform {0:.6g};".format(val),
                    "wall": wall, "slip": "type zeroGradient;", "symm": "type symmetry;"}
            F.write(case, "0/" + name, "dimensions {};\ninternalField uniform {:.6g};\n".format(dims, val) + _bf(bc(spec)), "volScalarField")
        tf("k", k0, "type kqRWallFunction; value uniform {:.6g};".format(k0), "[0 2 -2 0 0 0 0]")
        tf("omega", om0, "type omegaWallFunction; value uniform {:.6g};".format(om0), "[0 0 -1 0 0 0 0]")
        nut = {"inlet": "type calculated; value uniform 0;", "outlet": "type calculated; value uniform 0;",
               "wall": "type nutkWallFunction; value uniform 0;", "slip": "type calculated; value uniform 0;", "symm": "type symmetry;"}
        F.write(case, "0/nut", "dimensions [0 2 -1 0 0 0 0];\ninternalField uniform 0;\n" + _bf(bc(nut)), "volScalarField")
        if compressible:
            at = {"inlet": "type calculated; value uniform 0;", "outlet": "type calculated; value uniform 0;",
                  "wall": "type compressible::alphatJayatillekeWallFunction; Prt 0.85; value uniform 0;",
                  "slip": "type calculated; value uniform 0;", "symm": "type symmetry;"}
            F.write(case, "0/alphat", "dimensions [1 -1 -1 0 0 0 0];\ninternalField uniform 0;\n" + _bf(bc(at)), "volScalarField")


# ---------------------------------------------------------------- 后处理
def wall_forces(mesh, p, U, nu, rho, patch, nut_w=None, compressible=False, p_ref=0.0):
    """一个壁面边界上的压力力和摩擦力（N）。不可压时 p 是运动压力（÷ρ），乘 ρ；摩擦按壁面第一层单元的速度梯度
    （湍流壁面函数时用 ν + ν_t,w）"""
    sl = mesh.patch(patch)
    Sf, Cf = mesh.Sf[sl], mesh.Cf[sl]
    own = mesh.owner[sl]
    pf = p[own] - p_ref                                                    # 壁面压力取第一层单元值（零梯度）
    if not compressible:
        pf = pf * rho
    Fp = (pf[:, None] * Sf).sum(0)
    n = Sf / np.linalg.norm(Sf, axis=1)[:, None]
    Uc = U[own]
    Ut = Uc - (Uc * n).sum(1)[:, None] * n
    d = np.abs(((mesh.C[own] - Cf) * n).sum(1))
    nu_e = nu + (nut_w if nut_w is not None else 0.0)
    tau = (rho * np.asarray(nu_e)[..., None] if np.ndim(nu_e) else rho * nu_e) * Ut / np.maximum(d, 1e-12)[:, None]
    Fv = (tau * np.linalg.norm(Sf, axis=1)[:, None]).sum(0)
    return Fp, Fv


def wall_heat(mesh, T, patch, t_wall_K, alphat_w=None, cp=AIR["cp"], mu=AIR["mu"], Pr=AIR["Pr"]):
    """壁面散热量（W，正 = 从壁面传给空气）与每个面元的热流 q（W/m²）：q = cp·(μ/Pr + α_t,w)·(T_w − T_c)/d"""
    sl = mesh.patch(patch)
    Sf, Cf = mesh.Sf[sl], mesh.Cf[sl]
    own = mesh.owner[sl]
    A = np.linalg.norm(Sf, axis=1)
    n = Sf / A[:, None]
    d = np.abs(((mesh.C[own] - Cf) * n).sum(1))
    a_eff = mu / Pr + (alphat_w if alphat_w is not None else 0.0)
    tw = t_wall_K if np.ndim(t_wall_K) else np.full(len(A), t_wall_K)
    q = cp * a_eff * (tw - T[own]) / np.maximum(d, 1e-12)
    return float((q * A).sum()), q, A


# ---------------------------------------------------------------- 一次完整计算（虚拟风洞）
def plan(box, setup):
    """定风洞范围、背景网格尺寸、加密级别，使估计单元数不超过上限"""
    fl = setup.get("flow") or {}
    direction = fl.get("direction", "+x")
    ground = bool((setup.get("domain") or {}).get("ground"))
    a, b, Lc = tunnel(box, direction, ground=ground)
    size = box[3:] - box[:3]
    area = 2 * (size[0] * size[1] + size[1] * size[2] + size[0] * size[2])      # 粗估表面积（包围盒）
    target = int((setup.get("mesh") or {}).get("cells_target", 120_000))
    level = int((setup.get("mesh") or {}).get("level", 3))
    cell = Lc / 4
    while estimate_cells(a, b, cell, area, level) < target * 0.6 and cell > Lc / 40:
        cell /= 1.25
    while estimate_cells(a, b, cell, area, level) > target and cell < Lc:
        cell *= 1.12
    return a, b, Lc, cell, level, direction, ground


def solve(step_bytes, setup, workdir, progress=None):
    """返回 (stats, surface, aux)。surface：零件表面三角形和每个顶点的 p、h；aux：速度截面、流线"""
    import time
    from scipy.spatial import cKDTree
    from cae import cfd_heat as CH
    t0 = time.time()
    fl = setup.get("flow") or {}
    Umag = float(fl.get("velocity_ms", 5.0))
    t_air = float(fl.get("air_t_c", 25.0))
    heat = setup.get("heat")
    if not 0.01 <= Umag <= 60:
        raise ValueError("风速要在 0.01–60 m/s 之间（不可压，马赫数 < 0.2）")
    stl, box, ids, surf = stl_by_face(step_bytes)
    a, b, Lc, cell, level, direction, ground = plan(box, setup)
    nu = AIR["mu"] / AIR["rho"]
    Re = Umag * Lc / nu
    turb = setup.get("turbulence", "auto")
    if turb == "auto":
        turb = "laminar" if Re < 2000 else "kOmegaSST"
    ax, sg = DIRS[direction]
    U = [0.0, 0.0, 0.0]
    U[ax] = sg * Umag
    case = workdir
    inside = a + (b - a) * np.array([0.03, 0.03, 0.97])
    write_mesh_dicts(case, stl, box, direction, cell, level, ground, inside=inside, bounds=(a, b, Lc))
    if progress:
        progress("网格")
    F.run(case, "blockMesh", timeout=120)
    F.run(case, "snappyHexMesh", "-overwrite", timeout=LIMIT_S)
    mesh = F.Mesh(case)
    if mesh.n_cells > MAX_CELLS * 1.2:
        raise ValueError("网格 {} 个单元，超过教学版上限 {}：请把加密级别调低".format(mesh.n_cells, MAX_CELLS))
    parts = [k for k in mesh.boundary if k.startswith("part")]
    if not parts:
        raise ValueError("网格里没有零件表面：零件可能不在风洞里，或 STEP 不是封闭实体")
    inl, outl = _names(direction)
    sides = [k for k in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax") if k not in (inl, outl)]
    walls = ["zmin"] if ground else []
    slips = [s for s in sides if s not in walls]
    iters = int((setup.get("solver") or {}).get("iterations", 800))
    flow_case(case, U, parts, turb, nu=nu, end=iters, inlet=inl, outlet=outl, walls=walls, slips=slips)
    if progress:
        progress("流场")
    log = run_solver(case, "simpleFoam")
    tt = F.latest_time(case)
    p, _ = F.read_field(case, tt, "p", mesh)
    Uf, _ = F.read_field(case, tt, "U", mesh)
    nut = nut_b = None
    if turb != "laminar":
        nut, nb = F.read_field(case, tt, "nut", mesh)
        nut_b = {k: nb.get(k) for k in parts}
    res = _last_residuals(log)
    # 每个 CAD 面：面积、平均压力、压力力、摩擦力
    rho = AIR["rho"]
    face = {}
    Fp_tot, Fv_tot = np.zeros(3), np.zeros(3)
    for pn in parts:
        fid = int(pn.split("_f")[-1]) if "_f" in pn else 0
        Fp, Fv = wall_forces(mesh, p, Uf, nu, rho, pn, (nut_b or {}).get(pn))
        sl = mesh.patch(pn)
        A = mesh.magSf[sl]
        face[fid] = {"id": fid, "area_mm2": float(A.sum() * 1e6), "p_pa": float((p[mesh.owner[sl]] * A).sum() / A.sum() * rho),
                     "force_n": (Fp + Fv).tolist()}
        Fp_tot += Fp
        Fv_tot += Fv
    q_dyn = 0.5 * rho * Umag ** 2
    size = box[3:] - box[:3]
    frontal = float(np.prod([size[k] for k in range(3) if k != ax]))
    drag = float((Fp_tot + Fv_tot)[ax] * sg)
    stats = {"cells": int(mesh.n_cells), "cell_mm": round(cell * 1000, 2), "level": level, "iterations": int(float(tt)),
             "converged": int(float(tt)) < iters, "residuals": res, "turbulence": turb, "Re": Re, "L_char_mm": round(Lc * 1000, 1),
             "velocity_ms": Umag, "direction": direction, "air_t_c": t_air, "drag_n": drag, "drag_pressure_n": float(Fp_tot[ax] * sg),
             "drag_friction_n": float(Fv_tot[ax] * sg), "frontal_m2": frontal, "Cd": drag / (q_dyn * frontal) if frontal else None,
             "q_dyn_pa": q_dyn}
    # 换热
    hface = None
    if heat:
        tw = float(heat.get("wall_t_c", 70.0))
        if abs(tw - t_air) < 1:
            raise ValueError("表面温度和空气温度至少差 1 ℃")
        if progress:
            progress("温度场")
        phi, phib = F.read_field(case, tt, "phi", mesh)
        T, wq = CH.solve_T(mesh, phi, phib, nut, {pn: tw + 273.15 for pn in parts}, {inl: t_air + 273.15, outl: t_air + 273.15},
                           nut_b=nut_b)
        Qt = At = 0.0
        hface = {}
        for pn in parts:
            fid = int(pn.split("_f")[-1]) if "_f" in pn else 0
            w = wq[pn]
            h = w["Q"] / (w["A"].sum() * (tw - t_air))
            face[fid].update(heat_w=w["Q"], h_w_m2k=h)
            hface[pn] = w["q"] / (tw - t_air)
            Qt += w["Q"]
            At += w["A"].sum()
        stats.update(wall_t_c=tw, heat_w=Qt, h_mean=Qt / (At * (tw - t_air)), area_m2=At,
                     T_out_max_c=float(T.max() - 273.15))
    # 表面：零件三角形的顶点 → 最近的网格边界面
    fc, vp, vh = [], [], []
    for pn in parts:
        sl = mesh.patch(pn)
        fc.append(mesh.Cf[sl])
        vp.append(p[mesh.owner[sl]] * rho)
        vh.append(hface[pn] if hface else np.zeros(mesh.boundary[pn]["nFaces"]))
    tree = cKDTree(np.concatenate(fc))
    _, k = tree.query(surf["pos"])
    vp, vh = np.concatenate(vp)[k], np.concatenate(vh)[k]
    surface = {"positions": surf["pos"] * 1000.0, "p": vp, "h": vh, "triangles": surf["tri"], "face_of_triangle": surf["face"]}
    aux = {"slice": velocity_slice(mesh, Uf, box, ax, a, b), "streamlines": streamlines(mesh, Uf, box, ax, sg, a, b),
           "faces": [face[k] for k in sorted(face)]}
    stats["seconds"] = round(time.time() - t0, 1)
    return stats, surface, aux


def _last_residuals(log):
    import re
    out = {}
    for fld, val in re.findall(r"Solving for (\w+), Initial residual = ([0-9.eE+-]+)", log[-6000:]):
        out[fld] = float(val)
    return out


def velocity_slice(mesh, U, box, ax, a, b, n=(160, 80)):
    """过零件中心、和地面平行的截面（法向取既不是来流方向、又尽量是竖直的轴）上的速度大小（网格中心最近点取值）"""
    from scipy.spatial import cKDTree
    up = 2 if ax != 2 else 1
    lat = [k for k in range(3) if k not in (ax, up)][0]
    c = (box[:3] + box[3:]) / 2
    xs = np.linspace(a[ax], b[ax], n[0])
    ys = np.linspace(a[lat], b[lat], n[1])
    P = np.zeros((n[1], n[0], 3))
    P[..., ax] = xs[None, :]
    P[..., lat] = ys[:, None]
    P[..., up] = c[up]
    tree = cKDTree(mesh.C)
    dist, k = tree.query(P.reshape(-1, 3))
    V = np.linalg.norm(U[k], axis=1).reshape(n[1], n[0])
    # 落在零件里面的点：离最近单元中心太远就当成实体
    hmax = np.cbrt(np.median(mesh.V)) * 1.5
    V[dist.reshape(n[1], n[0]) > hmax] = np.nan
    return {"axis": "xyz"[ax], "lateral": "xyz"[lat], "normal": "xyz"[up], "at_mm": float(c[up] * 1000),
            "x0_mm": float(xs[0] * 1000), "x1_mm": float(xs[-1] * 1000), "y0_mm": float(ys[0] * 1000), "y1_mm": float(ys[-1] * 1000),
            "nx": n[0], "ny": n[1], "speed": np.nan_to_num(V, nan=-1.0).round(4).tolist(),
            "vmax": float(np.nanmax(V)) if np.isfinite(V).any() else 0.0}


def streamlines(mesh, U, box, ax, sg, a, b, n_seed=40, steps=400):
    """从零件上游一个平面撒点，按网格中心最近点的速度积分流线（毫米）"""
    from scipy.spatial import cKDTree
    tree = cKDTree(mesh.C)
    lo, hi = box[:3], box[3:]
    size = hi - lo
    seeds = []
    rng = np.random.default_rng(1)
    for _ in range(n_seed):
        s = lo + rng.uniform(-0.15, 1.15, 3) * size
        s[ax] = (lo[ax] - 0.5 * size[ax]) if sg > 0 else (hi[ax] + 0.5 * size[ax])
        seeds.append(s)
    h = float(np.cbrt(np.median(mesh.V)))
    lines = []
    for s in seeds:
        pts = [s.copy()]
        x = s.copy()
        for _ in range(steps):
            _, k = tree.query(x)
            v = U[k]
            sp_ = np.linalg.norm(v)
            if sp_ < 1e-6:
                break
            x = x + v / sp_ * h * 0.8
            if np.any(x < a) or np.any(x > b):
                break
            pts.append(x.copy())
        if len(pts) > 5:
            arr = np.array(pts) * 1000.0
            sp_all = np.linalg.norm(U[tree.query(np.array(pts))[1]], axis=1)
            lines.append({"pts": arr[::2].round(2).tolist(), "speed": sp_all[::2].round(3).tolist()})
    return lines
