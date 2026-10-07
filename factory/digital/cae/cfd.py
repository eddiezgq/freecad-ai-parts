# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：流体分析的建模、求解和后处理只留一份，在 analysis/cfd/solver.py。
工厂原来的接口收 STEP 的字节，这里写成临时文件再交给 analysis；其余名字原样转出。"""
import os
import tempfile

from analysis.cfd import solver as _S
from analysis.cfd.solver import (  # noqa: F401
    AIR, DIRS, LIMIT_S, MAX_CELLS, NPROC, _bf, _common, _fields, _last_residuals, _names, estimate_cells, flow_case, plan,
    run_solver, streamlines, tunnel, velocity_slice, wall_forces, write_mesh_dicts,
)


class _StepFile:
    """STEP 字节（或已有的文件路径）→ 临时文件路径"""

    def __init__(self, step):
        self.step, self.path = step, None

    def __enter__(self):
        if isinstance(self.step, (str, os.PathLike)) and os.path.isfile(self.step):
            return str(self.step)
        fd, self.path = tempfile.mkstemp(suffix=".step")
        with os.fdopen(fd, "wb") as f:
            f.write(self.step if isinstance(self.step, (bytes, bytearray)) else bytes(self.step))
        return self.path

    def __exit__(self, *exc):
        if self.path:
            os.unlink(self.path)


def stl_by_face(step_bytes, size_mm=None):
    """返回 (stl 文本, 包围盒 m, 面编号列表, 表面三角形)"""
    with _StepFile(step_bytes) as path:
        return _S.stl_by_face(path, size_mm, with_surface=True)


def solve(step_bytes, setup, workdir, progress=None):
    """返回 (stats, surface, aux)"""
    with _StepFile(step_bytes) as path:
        return _S.solve_full(path, setup, workdir, progress)
