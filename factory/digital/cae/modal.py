# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：固有频率（模态）只留一份，在 analysis/fea/modal.py。"""
from analysis.fea import modal as _MO
from analysis.fea.modal import RIGID_HZ, read_freqs, read_modes, write_inp  # noqa: F401
from cae import _fap
from cae import solve as S


def solve(step_bytes, setup, workdir=None, n_modes=6):
    s = _fap.factory_setup(setup, S.MAX_ELEMENTS, S.TIME_LIMIT_S)
    try:
        with _fap.StepFile(step_bytes) as path:
            stats, surface, *rest = _MO.solve(path, s, _fap.ccx(S.CCX), workdir, n_modes)
    except S.TooBig as e:
        raise _fap.teach_message(S.TooBig, e) from None
    return (stats, _fap.f32(surface), *rest)
