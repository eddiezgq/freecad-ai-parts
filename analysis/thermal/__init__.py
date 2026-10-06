"""热分析 · 热应力（ADR-0056，M10 第四步）：零件 STEP → 稳态 / 瞬态温度场，或热—结构耦合。

设置（单位：mm、W、W/(m²·K)、℃、s）：
  analysis: "thermal"（缺省）| "thermo_mech"
  step_path、material（材料库 id，需要导热系数、比热、密度；耦合另需弹性模量、泊松比、线膨胀系数）
  thermal: [{"type": "temperature", "faces": [..], "value_c": 80},
            {"type": "convection", "faces": [..] 或 "rest", "h_w_m2k": 17.45, "t_inf_c": 20},
            {"type": "heat_flux", "faces": [..], "power_w": 300},     面上总发热功率，均匀分布
            {"type": "heat_body", "power_w": 50}]                     整个零件体积均匀发热
  transient: {"duration_s", "steps", "t0_c"}（缺省为稳态）
  loads: 热—结构耦合时的支承与机械载荷（同有限元模块，扭矩用 value_nm）；ref_temp_c：无应力参考温度（缺省 20）
  mesh: {"size_mm"}

结果 data：最高 / 最低温度及位置、表面平均温度、输入功率与对流散走的热量（核对热平衡）、各对流面组的平均温度与散热量；
瞬态另有最高 / 平均温度随时间；耦合另有热应力、热变形、安全系数；表面结果（供显示）。
"""

from __future__ import annotations

import time
from pathlib import Path

from analysis.common import materials, result
from analysis.common.solvers import ccx_version, find_ccx

MODULE = {
    "id": "thermal", "name": "热分析 · 热应力", "version": "1",
    "description": "零件的稳态 / 瞬态温度场、热平衡，及热—结构耦合的热应力（Gmsh + CalculiX，本机计算）",
    "python": ["gmsh", "numpy", "scipy"], "solvers": ["ccx"],
    "install": '安装：pip install -e ".[fea]"；CalculiX 用 FreeCAD 自带的，或设置环境变量 FAP_CCX',
}
LIMITS = ["材料热物性取 20–100 ℃ 的典型值，不随温度变化", "表面散热系数为给定常数（可由流体分析或教材取值）；不计辐射，除非已含在系数中",
          "热应力为线弹性；约束面附近的应力来自理想化的约束"]


def run(setup: dict) -> dict:
    from analysis.fea import _internal_loads, _lists
    from analysis.thermal import solver

    t0 = time.time()
    kind = setup.get("analysis", "thermal")
    step = setup.get("step_path")
    if not isinstance(step, str) or not Path(step).is_file():
        return result.failed("thermal", MODULE["version"], setup, f"找不到零件 STEP 文件：{step!r}")
    if kind not in ("thermal", "thermo_mech"):
        return result.failed("thermal", MODULE["version"], setup, f"analysis 须为 thermal 或 thermo_mech：{kind!r}")
    try:
        mat = materials.get(setup.get("material", ""))
        need = ["thermal_conductivity_w_per_m_k", "specific_heat_j_per_kg_k", "density_kg_m3"]
        if kind == "thermo_mech":
            need += ["elastic_modulus_mpa", "poisson_ratio", "thermal_expansion_per_k"]
        materials.require(mat, need, "热分析")
        inner = {**setup, "material": mat, "loads": _internal_loads(setup.get("loads") or [])}
        stats, surface, _ = solver.solve(step, inner, find_ccx())
    except (materials.MissingData, ValueError, RuntimeError, KeyError) as exc:
        return result.failed("thermal", MODULE["version"], setup, f"没有算出：{exc}")
    msgs = []
    if not setup.get("transient") and stats["heat_in_w"] > 0:
        bal = abs(stats["heat_out_convection_w"] - stats["heat_in_w"]) / stats["heat_in_w"]
        if bal > 0.05 and not any(t["type"] == "temperature" for t in setup.get("thermal") or []):
            msgs.append(f"热平衡差 {bal:.0%}：网格可能太粗")
    return result.make("thermal", MODULE["version"], setup, {**stats, "surface": _lists(surface)}, limitations=LIMITS,
                       messages=msgs, solver={"name": "CalculiX", "version": ccx_version(find_ccx()) or "未知"},
                       elapsed_s=time.time() - t0)
