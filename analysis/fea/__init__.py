"""有限元强度与固有频率（ADR-0056，M10 第三步）：零件 STEP → Gmsh 二阶四面体 → CalculiX。

设置（单位：mm、N、MPa、N·m）：
  analysis: "static"（缺省）| "modal" | "faces"（只列面清单）
  step_path: 零件 STEP 文件（FreeCAD 中由所选零件导出）
  material: 材料库 id（analysis/common/materials.yaml）
  loads: [{"type": "fixed", "faces": [..]},
          {"type": "cyl_support", "faces": [..], "axis": {"origin": [..], "dir": [..]}, "dofs": ["radial", "axial", "tangential"],
           "band_mm": 1},
          {"type": "force", "faces": [..], "vector_n": [x, y, z]},
          {"type": "pressure", "faces": [..], "value_mpa": p},
          {"type": "torque", "faces": [..], "value_nm": T, "axis": {...}}]
  mesh: {"size_mm": h}；n_modes（模态，缺省 6）；max_elements；time_limit_s

结果 data：
  static：最大 Von Mises 应力（不计约束面 1.5 个网格尺寸以内）及位置与所在面、全部节点中的峰值、最大位移、安全系数
          （按屈服强度；脆性材料按抗拉强度）、网格、表面结果（节点坐标、三角形、应力、位移，供显示）
  modal：前几阶固有频率（Hz、rpm）、第一阶振型
  faces：面清单（编号、类型、面积、中心、法向或轴线）
"""

from __future__ import annotations

import copy
import time
from pathlib import Path

from analysis.common import materials, result
from analysis.common.solvers import ccx_version, find_ccx

MODULE = {
    "id": "fea", "name": "有限元强度 · 固有频率", "version": "1",
    "description": "零件的应力、变形、安全系数与固有频率（Gmsh + CalculiX，本机计算）",
    "python": ["gmsh", "numpy", "scipy"], "solvers": ["ccx"],
    "install": '安装：pip install -e ".[fea]"；CalculiX 用 FreeCAD 自带的，或设置环境变量 FAP_CCX',
}
LIMITS_STATIC = ["线弹性、小变形；不计接触、残余应力与表面硬化", "约束面、加载面附近的应力来自理想化的边界条件，评估最大应力时已避开",
                 "尖角处的应力随网格加密而增大（理论奇异点），不宜直接作为设计依据"]
LIMITS_MODAL = ["只计零件本身的质量与刚度，装在上面的附加质量不计", "支承按理想约束，实际轴承刚度会使频率偏低"]


def _internal_loads(loads: list) -> list:
    out = copy.deepcopy(loads)
    for ld in out:
        if ld.get("type") == "torque":
            if "value_nm" not in ld:
                raise ValueError("扭矩须写 value_nm（N·m）")
            ld["value_nmm"] = float(ld.pop("value_nm")) * 1000
    return out


def _lists(d: dict) -> dict:
    return {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in d.items()}


def run(setup: dict) -> dict:
    from analysis.fea import geometry, modal, solve

    t0 = time.time()
    kind = setup.get("analysis", "static")
    step = setup.get("step_path")
    if not isinstance(step, str) or not Path(step).is_file():
        return result.failed("fea", MODULE["version"], setup, f"找不到零件 STEP 文件：{step!r}")
    ccx = find_ccx()
    try:
        if kind == "faces":
            faces, solid = geometry.faces(step)
            return result.make("fea", MODULE["version"], setup, {"faces": faces, "solid": solid},
                               elapsed_s=time.time() - t0)
        mat = materials.get(setup.get("material", ""))
        materials.require(mat, ["elastic_modulus_mpa", "poisson_ratio", "density_kg_m3"], "有限元")
        inner = {**setup, "material": mat, "loads": _internal_loads(setup.get("loads") or [])}
        if kind == "static":
            stats, surface, _ = solve.solve(step, inner, ccx)
            data = {**stats, "surface": _lists(surface)}
            limits = LIMITS_STATIC
        elif kind == "modal":
            stats, surface = modal.solve(step, inner, ccx, n_modes=int(setup.get("n_modes", 6)))
            data = {**stats, "surface": _lists(surface)}
            limits = LIMITS_MODAL
        else:
            return result.failed("fea", MODULE["version"], setup, f"analysis 须为 static、modal 或 faces：{kind!r}")
    except (materials.MissingData, ValueError, RuntimeError, KeyError) as exc:
        return result.failed("fea", MODULE["version"], setup, f"没有算出：{exc}")
    return result.make("fea", MODULE["version"], setup, data, limitations=limits,
                       solver={"name": "CalculiX", "version": ccx_version(ccx) or "未知"}, elapsed_s=time.time() - t0)
