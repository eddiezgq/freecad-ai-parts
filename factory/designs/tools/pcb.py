# -*- coding: utf-8 -*-
"""第 111 轮起，板子生成搬到问渠电子的通用生成器 eda/wqeda/gen/board.py；这里只留旧名字，给还在用的脚本。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                                "eda"))

from wqeda.gen.board import (  # noqa: E402,F401
    FPDIR,
    MM,
    ORIGIN,
    P,
    add_pour,
    add_zone,
    autoroute,
    fill_zones,
    import_ses,
    load_fp,
    outline,
)
from wqeda.gen.board import dsn_keepouts as _keepouts  # noqa: E402,F401
from wqeda.gen.board import dsn_rules as _dsn_rules  # noqa: E402,F401
