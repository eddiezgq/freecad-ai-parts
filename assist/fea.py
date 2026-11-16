"""命令行入口（ADR-0093 补充十一 §4）：python -m assist.fea draft|confirm|eval …；report 在第 5 步加。"""

from __future__ import annotations

import sys

from assist.fea_draft import main

if __name__ == "__main__":
    sys.exit(main())
