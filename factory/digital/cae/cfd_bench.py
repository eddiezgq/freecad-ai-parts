# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：流体分析的标准题只留一份，在 analysis/cfd/bench.py（同样四道题、同样门槛）。"""
from analysis.cfd.bench import NU, all_cases, cylinder, duct, plate, poiseuille  # noqa: F401

if __name__ == "__main__":
    import json
    import sys
    import time
    t = time.time()
    print(json.dumps(all_cases(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cfdbench"), ensure_ascii=False, indent=1, default=float))
    print(round(time.time() - t, 1), "s")
