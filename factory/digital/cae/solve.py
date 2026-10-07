# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：有限元静力只留一份，在 analysis/fea/solve.py。
工况 setup 同工厂原来的（material 为 cae/materials.py 的条目，loads、mesh 同）。"""
import os

from analysis.fea import solve as _S
from analysis.fea.solve import (  # noqa: F401
    GMSH2CCX_TET10, SOLVER, SUPPORT_DOFS, SUPPORTS, TooBig, _axis, _nset, band_nodes, consistent_loads, face_tris, mesh,
    read_frd, von_mises, write_inp,
)
from cae import _fap

CCX = os.environ.get("WQ_CCX", "ccx")
MAX_ELEMENTS = int(os.environ.get("WQ_CAE_MAX_ELEMENTS", "200000"))
TIME_LIMIT_S = int(os.environ.get("WQ_CAE_TIME_LIMIT_S", "300"))


def solve(step_bytes, setup, workdir=None):
    """返回 (stats, surface, full)"""
    s = _fap.factory_setup(setup, MAX_ELEMENTS, TIME_LIMIT_S)
    try:
        with _fap.StepFile(step_bytes) as path:
            stats, surface, full = _S.solve(path, s, _fap.ccx(CCX), workdir)
    except TooBig as e:
        raise _fap.teach_message(TooBig, e) from None
    return _fap.finish_stats(stats, setup["material"]), _fap.f32(surface), full
