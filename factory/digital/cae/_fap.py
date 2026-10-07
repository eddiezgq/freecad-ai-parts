# -*- coding: utf-8 -*-
"""工厂 cae/ 转接层的公共部分（本仓库 ADR-0060）：计算内核在 analysis/，这里把工厂的接口习惯（STEP 字节、工厂材料表的字段名、
WQ_* 环境变量、float32 的网页数据）换成 analysis 的，再换回来。"""
import os
import shutil
import tempfile

import numpy as np


class StepFile:
    """STEP 字节（或已有的文件路径）→ 临时文件路径"""

    def __init__(self, step):
        self.step, self.path = step, None

    def __enter__(self):
        if isinstance(self.step, (str, os.PathLike)) and os.path.isfile(self.step):
            return str(self.step)
        fd, self.path = tempfile.mkstemp(suffix=".step")
        with os.fdopen(fd, "wb") as f:
            f.write(bytes(self.step))
        return self.path

    def __exit__(self, *exc):
        if self.path:
            os.unlink(self.path)


def ccx(name):
    return shutil.which(name) or name


def material(m):
    """工厂材料表（cae/materials.py：E_mpa、nu、density g/cm³、strength_mpa、k_w_mk、c_j_kgk、alpha_1e6）→ analysis 的字段名。
    强度给成屈服强度：工厂表已按“有屈服用屈服、没有用抗拉”算好 strength_mpa（strength_kind 写明是哪一个）。"""
    rho_t = m.get("density_t_mm3")
    if rho_t is None:
        rho_t = float(m.get("density", 7.85)) * 1e-9
    out = {"id": m.get("id", "factory"), "name": m.get("name", ""), "elastic_modulus_mpa": float(m["E_mpa"]),
           "poisson_ratio": float(m["nu"]), "density_kg_m3": float(rho_t) * 1e12}
    strength = m.get("strength_mpa") or m.get("yield_mpa")
    if strength:
        out["yield_strength_mpa"] = float(strength)
    for src, dst, k in (("k_w_mk", "thermal_conductivity_w_per_m_k", 1.0), ("c_j_kgk", "specific_heat_j_per_kg_k", 1.0),
                        ("alpha_1e6", "thermal_expansion_per_k", 1e-6)):
        if m.get(src) is not None:
            out[dst] = float(m[src]) * k
    return out


def factory_setup(setup, max_elements, time_limit_s):
    s = dict(setup)
    s["material"] = material(setup["material"])
    s.setdefault("max_elements", max_elements)
    s.setdefault("time_limit_s", time_limit_s)
    s["strength_optional"] = True
    return s


def finish_stats(stats, m):
    """强度的名称按工厂材料表（屈服强度 / 抗拉强度）"""
    if "strength_mpa" in stats:
        stats["strength_kind"] = m.get("strength_kind") or ("屈服强度" if m.get("yield_mpa") else "抗拉强度")
    return stats


def f32(surface):
    """网页用的表面数据：坐标与结果 float32，索引 int32（与工厂原来的一样）"""
    return {k: (np.asarray(v).astype(np.int32) if k in ("triangles", "face_of_triangle") else np.asarray(v).astype(np.float32))
            for k, v in surface.items()}


def teach_message(exc_cls, exc):
    """工厂的提示说“教学版上限”"""
    return exc_cls(str(exc).replace("超过上限", "超过教学版上限"))
