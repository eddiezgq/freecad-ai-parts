# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：OpenFOAM 的读写只留一份，在 analysis/cfd/foam.py。这里保留工厂原来的名字。"""
from analysis.cfd.foam import (  # noqa: F401
    HEAD, FoamError, Mesh, _list_body, _numbers, _strip, environment, find_openfoam, latest_time, read_boundary, read_faces,
    read_field, read_labels, read_points, run, write,
)

ENV = environment()
