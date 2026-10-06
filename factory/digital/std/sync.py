# -*- coding: utf-8 -*-
"""把教材的工艺数据表和读表模块同步到数字工厂（第 13 轮）。

工厂镜像只打包 factory/ 目录，看不到 textbook/；所以这里放一份副本。**原件在 textbook/mfgtech/std/ 和
textbook/tools/stdtab.py，只改原件**，改完运行：

    python3 factory/digital/std/sync.py

测试 tests/test_process.py 会核对副本与原件一字不差。
"""
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FILES = {
    REPO / "textbook" / "tools" / "stdtab.py": HERE / "stdtab.py",
    **{REPO / "textbook" / "mfgtech" / "std" / f"{n}.yaml": HERE / f"{n}.yaml" for n in ("it_grades", "econ_accuracy", "kienzle")},
}

if __name__ == "__main__":
    for src, dst in FILES.items():
        shutil.copyfile(src, dst)
        print(dst.relative_to(REPO))
