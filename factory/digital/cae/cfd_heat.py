# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：强制对流的温度场只留一份，在 analysis/cfd/heat.py。"""
from analysis.cfd.heat import PR_T, solve_T  # noqa: F401
