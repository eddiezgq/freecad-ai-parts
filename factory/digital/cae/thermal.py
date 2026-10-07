# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：热分析（稳态 / 瞬态温度场、热—结构耦合）只留一份，在 analysis/thermal/solver.py。
setup 同工厂原来的（material 为 cae/materials.py 的条目，含 k_w_mk、c_j_kgk、alpha_1e6）。"""
from analysis.thermal import solver as _T
from analysis.thermal.solver import TET_FACES, _face_index, _tri_area, read_frd_all  # noqa: F401
from cae import _fap
from cae import solve as S


def solve(step_bytes, setup, workdir=None):
    s = _fap.factory_setup(setup, S.MAX_ELEMENTS, S.TIME_LIMIT_S)
    try:
        with _fap.StepFile(step_bytes) as path:
            stats, surface, *rest = _T.solve(path, s, _fap.ccx(S.CCX), workdir)
    except S.TooBig as e:
        raise _fap.teach_message(S.TooBig, e) from None
    return (_fap.finish_stats(stats, setup["material"]), _fap.f32(surface), *rest)
