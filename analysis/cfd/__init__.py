"""流体分析（ADR-0059，M11 第三步）：OpenFOAM 虚拟风洞——零件放进长方体风洞，算阻力、各面压力与受力；给表面温度时再算强制对流
散热量与平均散热系数。搬自问渠数字工厂第 16 轮。OpenFOAM 不随 FreeCAD 安装，需另装（见 MODULE["install"]）。

设置：
  analysis: "tunnel"（缺省）| "bench"（标准题核对：平行平板层流压降、平板层流换热，约半分钟）
  tunnel：step_path（零件 STEP，mm）；flow: {"velocity_ms"（0.01–60）, "direction": "+x" | "-x" | "+y" | "-y" | "+z" | "-z",
          "air_t_c"（缺省 25）}；heat: {"wall_t_c"}（可选：零件表面定温）；domain: {"ground": true}（零件放在地面上）；
          mesh: {"cells_target"（缺省 120000）, "level"（表面加密级别，缺省 3）}；solver: {"iterations"（缺省 800）}；
          turbulence: "auto" | "laminar" | "kOmegaSST"
结果 data（tunnel）：cells、Re、turbulence、converged、drag_n（压差 + 摩擦）、Cd（按迎风投影面积）、
  有换热时 heat_w、h_mean（W/(m²·K)）；faces：每个 CAD 面（编号与有限元的面编号相同）的面积、平均压力、受力、散热量、散热系数。
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from analysis.common import result

MODULE = {
    "id": "cfd", "name": "流体分析", "version": "1",
    "description": "虚拟风洞：阻力、各面压力与受力，强制对流散热量与散热系数（OpenFOAM，本机计算）",
    "python": ["gmsh", "numpy", "scipy"], "solvers": ["openfoam"],
    "install": ("单机安装版不带 OpenFOAM：可在企业数字工厂网页的“流体分析”（/cfd）上传零件 STEP 计算（ADR-0066）；"
                "本机计算需另装 OpenFOAM：Linux 装发行版的 openfoam 包（Ubuntu / Debian：apt install openfoam）；Windows 在 WSL 中装，"
                "或装 blueCFD-Core 并把放 simpleFoam 的目录设到环境变量 FAP_OPENFOAM_BIN。Python 包：pip install -e \".[fea]\""),
}
LIMITS = ["不可压定常（马赫数 < 0.2）；湍流按 k-ω SST + 壁面函数，层流 / 湍流按雷诺数 2000 自动选",
          "换热为强制对流：零件表面定温，空气常物性（25 ℃），不计浮力与辐射",
          "网格按目标单元数自动定；阻力、散热系数对网格敏感，重要结论宜加密网格复核"]


def _bench(setup):
    from analysis.cfd import bench as B

    with tempfile.TemporaryDirectory(prefix="fap-cfd-bench-") as tmp:
        cases = [B.poiseuille(str(Path(tmp) / "poiseuille")), B.plate(str(Path(tmp) / "plate"))]
    checks = [result.check(c["name"], c["value"], c["theory"], c["formula"]) for c in cases]
    return {"cases": [{k: c[k] for k in ("name", "value", "theory", "unit", "formula", "error")} for c in cases]}, checks


def run(setup: dict) -> dict:
    from analysis.cfd import foam
    from analysis.cfd import solver as S

    t0 = time.time()
    kind = setup.get("analysis", "tunnel")
    try:
        if kind == "bench":
            data, checks = _bench(setup)
            return result.make("cfd", MODULE["version"], setup, data, checks=checks, limitations=LIMITS,
                               solver={"name": "OpenFOAM"}, elapsed_s=time.time() - t0)
        if kind != "tunnel":
            raise ValueError(f"analysis 要是 tunnel 或 bench：{kind!r}")
        step = setup.get("step_path")
        if not step or not Path(step).is_file():
            raise ValueError("没有零件 STEP（step_path）")
        direction = (setup.get("flow") or {}).get("direction", "+x")
        if direction not in S.DIRS:
            raise ValueError(f"来流方向要是 {', '.join(S.DIRS)} 之一")
        with tempfile.TemporaryDirectory(prefix="fap-cfd-") as tmp:
            stats, faces = S.solve(step, setup, tmp)
    except (ValueError, foam.FoamError) as exc:
        return result.failed("cfd", MODULE["version"], setup, str(exc))
    msgs = []
    if not stats["converged"]:
        msgs.append(f"{stats['iterations']} 步内残差没有降到收敛标准，结果供参考；可加大迭代步数")
    stats.pop("seconds", None)
    data = {**stats, "faces": faces}
    return result.make("cfd", MODULE["version"], setup, data, limitations=LIMITS, messages=msgs,
                       solver={"name": "OpenFOAM"}, elapsed_s=time.time() - t0)
